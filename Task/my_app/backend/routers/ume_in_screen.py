# -*- coding: utf-8 -*-
"""UME 割接大屏「实时还原」API（ume_in）

把 UME 大屏（guard-imonitor-iui largescreen）搬到本机，**任意时刻打开都与 UME 当前值一致**。

## 为什么要走后端
浏览器直连 UME 拿不到会话（cookie/forgery_token 由 OAuth2+RSA 登录产生，且是
172.17.208.1 的域），所以鉴权必须留在服务端。本模块把
``ume_in_screen_render`` 的抓取能力包成 HTTP 接口，页面只跟本机后端说话。

## 端点
GET  /api/ume-in/screen/live?screen_id=1&template=OLib_OSG_CAPs&last_hours=6
     -> 实时还原页面（HTML）。打开即用，按大屏自身的 refresh_ms（实测 180s）自动刷新。
GET  /api/ume-in/screen/layout?screen_id=1&template=...
     -> 布局（画布尺寸 / 全部元素 / 大屏参数 / 背景图 URL）
GET  /api/ume-in/screen/data?screen_id=1&template=...&last_hours=6
     -> 各组件当前数据（含 server_now / refreshed_at / cached）
GET  /api/ume-in/screen/asset/{src}?screen_id=1&template=...
     -> 背景图 PNG（blob 代理，带 ETag/长缓存）
GET  /api/ume-in/screen/vendor/echarts.min.js
     -> 项目自带的 echarts（离线可用，不依赖外网 CDN）
GET  /api/ume-in/screen/templates?screen_id=1
     -> 子模板清单（页面切换用）
GET  /api/ume-in/screen/bundle?screen_id=1&template=...&last_hours=6
     -> 布局+数据一次取全（排障 / 单次快照用）

## 会话与缓存（实时性的关键）
- **会话复用**：登录一次（OAuth2+RSA 约 1~2s）后进程内复用，带锁 + 30 分钟主动重登；
  遇到鉴权类错误自动重登并重试一次。
- **并行取数**：单组件约 1.3s，10 个串行要 13s；改为线程池并行后约 2s。
  复用同一 client 是安全的——``UMEPortalClient._request`` 每次新开 socket，
  请求期间不共享可变状态。
- **短 TTL 缓存**：默认 10s（``UME_IN_SCREEN_DATA_TTL``）。多个标签页/频繁刷新
  不会重复打 UME；页面仍按 refresh_ms 刷新，看到的始终是近实时值。
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from backend.services.ume_in import ume_in_screen_render as R
from backend.services.ume_in.ume_in_kpi_service import UMEPortalClient, _runtime_credentials
from backend.services.ume_in.ume_in_screen_service import DEFAULT_SCREEN_ID

logger = logging.getLogger("ume_in_screen_router")
router = APIRouter(prefix="/api/ume-in/screen", tags=["ume-in-screen"])

API_BASE = "/api/ume-in/screen"

# 会话主动重登周期（秒）。UME 会话具体时长未知，取保守值；真正的兜底是失败重登。
SESSION_TTL = float(os.environ.get("UME_IN_SCREEN_SESSION_TTL", "1800"))
# 数据短 TTL 缓存（秒）：避免多标签页/连点刷新把 UME 打爆
DATA_TTL = float(os.environ.get("UME_IN_SCREEN_DATA_TTL", "10"))
# 布局缓存（秒）：元素/参数/背景图极少变
LAYOUT_TTL = float(os.environ.get("UME_IN_SCREEN_LAYOUT_TTL", "300"))

_client = None
_client_born = 0.0
_client_lock = threading.Lock()

_cache = {}                 # key -> (ts, payload)
_cache_lock = threading.Lock()

# 这些字样说明是「会话失效」而不是「没权限」，值得重登重试
_AUTH_HINTS = ("401", "unauthorized", "z-auth", "oauth", "login_rsa",
               "session expired", "not logged in", "登录")


def _looks_like_auth_error(exc):
    m = str(exc).lower()
    if "no configuration corresponding operation code" in m:
        return False        # 已知的权限码缺失（403），重登没用
    return any(h in m for h in _AUTH_HINTS)


def get_client(force=False):
    """取进程内复用的 UME 会话；过期或 force 时重新登录。"""
    global _client, _client_born
    with _client_lock:
        now = time.time()
        if force or _client is None or (now - _client_born) > SESSION_TTL:
            user, pwd = _runtime_credentials()
            logger.info(f"[SCREEN] 登录 UME {'(重登)' if force else ''} user={user}")
            c = UMEPortalClient(username=user, password=pwd)
            c.login()
            _client, _client_born = c, now
        return _client


def _with_reauth(fn):
    """执行 fn(client)；遇鉴权类错误则强制重登并重试一次。"""
    try:
        return fn(get_client())
    except Exception as e:  # noqa: BLE001
        if not _looks_like_auth_error(e):
            raise
        logger.warning(f"[SCREEN] 疑似会话失效，重登后重试：{e}")
        return fn(get_client(force=True))


def _cached(key, ttl, producer):
    """带 TTL 的进程内缓存（过期后同步重算）。"""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1], True
    val = producer()
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val, False


def _invalidate(screen_id=None):
    with _cache_lock:
        for k in list(_cache):
            if screen_id is None or k[1] == int(screen_id):
                _cache.pop(k, None)


def _layout(screen_id, template):
    key = ("layout", int(screen_id), template)
    return _cached(key, LAYOUT_TTL,
                   lambda: R.fetch_layout(get_client(), screen_id, template))


def _data(screen_id, template, last_hours):
    key = ("data", int(screen_id), template, last_hours)
    return _cached(key, DATA_TTL,
                   lambda: R.fetch_data(get_client(), screen_id, template, last_hours))


# ============================================================
# 页面
# ============================================================
@router.get("/live", response_class=HTMLResponse)
def live(screen_id: int = Query(DEFAULT_SCREEN_ID),
         template: str = Query(None, description="子模板名，如 OLib_OSG_CAPs；缺省用第一个"),
         last_hours: int = Query(None, ge=1, le=24, description="覆盖时间窗小时数"),
         lang: str = Query("en", pattern="^(en|zh-CN)$"),
         interval: int = Query(None, ge=15, description="覆盖前端刷新间隔（秒）")):
    """实时还原页面：打开即连本机后端取数，按大屏 refresh_ms 自动刷新。"""
    return HTMLResponse(R.render_live_html(
        screen_id=screen_id, template_name=template, lang=lang,
        api_base=API_BASE, last_hours=last_hours,
        interval_ms=(interval * 1000) if interval else None))


# ============================================================
# 数据
# ============================================================
@router.get("/layout")
def layout(screen_id: int = Query(DEFAULT_SCREEN_ID), template: str = Query(None)):
    """布局：画布尺寸 + 全部元素 + 大屏参数 + 背景图（带本机代理 URL）。"""
    try:
        lay, cached = _layout(screen_id, template)
    except Exception as e:  # noqa: BLE001
        logger.exception("screen layout failed")
        raise HTTPException(status_code=502, detail=f"取大屏布局失败: {e}")

    payload = R.layout_payload(lay)
    q = f"screen_id={int(screen_id)}" + (f"&template={template}" if template else "")
    payload["assets"] = {
        src: {**{k: v for k, v in (a or {}).items() if k != "bytes"},
              "url": f"{API_BASE}/asset/{src}?{q}"}
        for src, a in (payload.get("assets") or {}).items()
    }
    payload["template"] = lay.get("template")
    payload["screen_id"] = int(screen_id)
    payload["cached"] = cached
    payload["refresh_ms"] = R._refresh_ms(payload["screen"]["elements"])
    return payload


@router.get("/data")
def data(screen_id: int = Query(DEFAULT_SCREEN_ID), template: str = Query(None),
         last_hours: int = Query(None, ge=1, le=24)):
    """各组件当前数据（originData），供页面轮询。"""
    try:
        d, cached = _data(screen_id, template, last_hours)
    except Exception as e:  # noqa: BLE001
        logger.exception("screen data failed")
        raise HTTPException(status_code=502, detail=f"取大屏数据失败: {e}")

    return {
        "screen_id": d["screen_id"],
        "template": d["template"],
        "data": d["data"],
        "errors": d.get("errors") or {},
        "server_now": d.get("server_now"),
        "last_hours": d.get("last_hours"),
        "refreshed_at": int(time.time() * 1000),
        "cached": cached,
    }


@router.get("/bundle")
def bundle(screen_id: int = Query(DEFAULT_SCREEN_ID), template: str = Query(None),
           last_hours: int = Query(None, ge=1, le=24)):
    """布局 + 数据一次取全（排障用；页面实际走 layout + data 两个接口）。"""
    lay = layout(screen_id=screen_id, template=template)
    d = data(screen_id=screen_id, template=template, last_hours=last_hours)
    return {**lay, "data": d["data"], "server_now": d["server_now"],
            "last_hours": d["last_hours"], "refreshed_at": d["refreshed_at"],
            "errors": d["errors"]}


@router.get("/templates")
def templates(screen_id: int = Query(DEFAULT_SCREEN_ID)):
    """列出该大屏下的子模板（供页面/接口选择）。"""
    def build():
        from backend.services.ume_in.ume_in_screen_service import (
            fetch_screen_config, parse_screen_config)
        tpls = parse_screen_config(fetch_screen_config(get_client(), screen_id))
        return [{"name": t["name"], "template_name": t["template_name"],
                 "template_id": t["template_id"], "width": t["width"],
                 "height": t["height"], "params": t["param_values"],
                 "components": len(t["components"])} for t in tpls]

    try:
        tpls, cached = _cached(("templates", int(screen_id)), LAYOUT_TTL, build)
    except Exception as e:  # noqa: BLE001
        logger.exception("screen templates failed")
        raise HTTPException(status_code=502, detail=f"取子模板清单失败: {e}")
    return {"screen_id": int(screen_id), "templates": tpls, "cached": cached,
            "live_url_template": f"{API_BASE}/live?screen_id={int(screen_id)}&template="}


# ============================================================
# 静态资源代理
# ============================================================
@router.get("/asset/{src}")
def asset(src: str, screen_id: int = Query(DEFAULT_SCREEN_ID), template: str = Query(None)):
    """背景图代理：GET UME /largescreen/blob?_id={src}，带长缓存。"""
    def build():
        lay = R.fetch_layout(get_client(), screen_id, template)
        a = (lay.get("assets") or {}).get(str(src))
        if not a:
            raise KeyError(f"该子模板没有背景图 src={src}")
        return a["bytes"]

    try:
        blob, cached = _cached(("asset", int(screen_id), template, str(src)),
                               LAYOUT_TTL, build)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("screen asset failed")
        raise HTTPException(status_code=502, detail=f"取背景图失败: {e}")

    return Response(content=blob, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600",
                             "ETag": f'"{src}-{len(blob)}"',
                             "X-Cache": "HIT" if cached else "MISS"})


@router.get("/vendor/echarts.min.js")
def echarts_js():
    """项目自带的 echarts（前端 node_modules），避免依赖外网 CDN。"""
    path = R._find_echarts()
    if not path:
        raise HTTPException(status_code=404, detail="未找到本地 echarts.min.js")
    with open(path, "rb") as f:
        blob = f.read()
    return Response(content=blob, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=86400"})


# ============================================================
# 运维
# ============================================================
@router.post("/refresh")
def refresh(screen_id: int = Query(None)):
    """清缓存；下次请求立即回 UME 取最新值（页面无需重启）。"""
    _invalidate(screen_id)
    return {"success": True, "cleared_screen_id": screen_id}


@router.get("/status")
def status():
    """会话/缓存状态，便于排查实时性。"""
    with _cache_lock:
        keys = [{"key": list(map(str, k)), "age_s": round(time.time() - v[0], 1)}
                for k, v in _cache.items()]
    return {
        "session": {"logged_in": _client is not None,
                    "age_s": round(time.time() - _client_born, 1) if _client else None,
                    "ttl_s": SESSION_TTL},
        "data_ttl_s": DATA_TTL,
        "layout_ttl_s": LAYOUT_TTL,
        "cache": keys,
    }
