# -*- coding: utf-8 -*-
"""portal_auth.py - 适配 uniplam 门户用户鉴权的 myapp 会话模块
=============================================================

背景：my_app 自身没有用户鉴权系统，数据接口原本全开放。现在要求「用户在
uniplam 门户（http://<host>/uniplam/）登录后，从门户点开 myapp 看板深链
时免重复登录，且 myapp 对看板数据做强制鉴权（未登录 401）」。

uniplam 门户鉴权形态（见 D:/01_RPA/liberia-noc_soc-数据看板统一门户）：
- 登录后返回一个【内存 Bearer token】（64 hex 随机串，无 Cookie / JWT / 签名），
  浏览器存 localStorage，密钥 `liberia_noc_auth_v1`；
- 校验入口：`GET /uniplam/api/auth/me`，header `Authorization: Bearer <token>`
  返回 `{user}` 或 401；
- 会话只存在门户进程内存，myapp 无法离线验证，必须回调门户 `/me` 换取用户。

本模块职责：
1. `POST /api/auth/portal-login {token}`：把门户 token 回调给门户 `/me` 验证；
   成功后签发 myapp 自己的 HttpOnly 会话 Cookie（门户 token 只进门一次）。
2. `POST /api/auth/logout`：注销 myapp 会话。
3. `GET /api/auth/me`：返回当前会话用户（供前端引导/展示）。
4. `require_user` / `current_user`：供鉴权中间件/端点读取当前用户。

--- 会话落盘 + 大屏常驻（2026-09-11 增强）---
原先会话只存 `_SESSIONS` 进程内存，后端一重启全部会话归零 → 所有看板被踢回
登录页。现改为 **SQLite/PG 双模落盘**（表 portal_sessions，走 get_raw_connection，
与 MY_APP_DB_MODE 保持一致），内存 dict 退化为 L1 缓存：

- 首次访问时把未过期会话从库里预热回内存；命中内存即不碰数据库；
- 新建 / 注销 / 过期清理同时写内存与库；
- 落盘是「尽力而为」：库不可用时仅告警并退回纯内存模式，绝不让鉴权 500。

大屏常驻登录两道手段：
- **滑动续期**：每次请求把有效期重置为「当前时间 + MYAPP_SESSION_TTL」，
  只要大屏还在轮询（看板自带自动刷新）就永不过期；绝对上限
  MYAPP_SESSION_MAX_TTL 默认 0 = 不设限。
- **常驻会话（kiosk）**：`GET /api/auth/kiosk?key=<MYAPP_KIOSK_KEY>&next=<路径>`
  一次性种下「永不过期」的 Cookie 并 302 跳回看板。适合不轮询的静态大屏、
  且断电/关机重启后仍免登录。需先设置 MYAPP_KIOSK_KEY（未设置则接口 404）。

配置（环境变量）：
- UNIPLAM_ME_URL  门户 `/me` 回调整（默认 http://127.0.0.1:9267/uniplam/api/auth/me）
- UNIPLAM_TIMEOUT 回调超时秒（默认 5）
- MYAPP_SESSION_TTL             滑动续期窗口秒（默认 8h）
- MYAPP_SESSION_MAX_TTL         会话绝对上限秒，自创建起算；0 = 不设限（默认 0）
- MYAPP_SESSION_SLIDING         是否滑动续期，1/0（默认 1）
- MYAPP_SESSION_COOKIE_MAX_AGE  Cookie 存活秒（默认 30 天；<=0 表示会话级 Cookie）
- MYAPP_SESSION_PERSIST_INTERVAL 落盘节流秒（默认 60，避免每个请求都写库）
- MYAPP_SESSION_COOKIE         会话 Cookie 名（默认 myapp_session）
- MYAPP_KIOSK_KEY              常驻会话密钥；为空则常驻接口关闭（默认空）
- MYAPP_KIOSK_COOKIE_MAX_AGE   常驻 Cookie 存活秒（默认 10 年）
"""
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend.security import client_is_local
from backend.database import get_raw_connection

logger = logging.getLogger(__name__)

UNIPLAM_ME_URL = os.environ.get("UNIPLAM_ME_URL", "http://127.0.0.1:9267/uniplam/api/auth/me")
UNIPLAM_TIMEOUT = float(os.environ.get("UNIPLAM_TIMEOUT", "5"))
SESSION_TTL = int(os.environ.get("MYAPP_SESSION_TTL", str(8 * 3600)))
SESSION_MAX_TTL = int(os.environ.get("MYAPP_SESSION_MAX_TTL", "0"))
SESSION_SLIDING = os.environ.get("MYAPP_SESSION_SLIDING", "1").strip().lower() not in ("0", "false", "no", "off")
SESSION_COOKIE_MAX_AGE = int(os.environ.get("MYAPP_SESSION_COOKIE_MAX_AGE", str(30 * 24 * 3600)))
SESSION_PERSIST_INTERVAL = float(os.environ.get("MYAPP_SESSION_PERSIST_INTERVAL", "60"))
SESSION_COOKIE = os.environ.get("MYAPP_SESSION_COOKIE", "myapp_session")
KIOSK_KEY = os.environ.get("MYAPP_KIOSK_KEY", "").strip()
KIOSK_COOKIE_MAX_AGE = int(os.environ.get("MYAPP_KIOSK_COOKIE_MAX_AGE", str(10 * 365 * 24 * 3600)))

# 过期清理节流（秒）：避免每个请求都跑一遍全表 DELETE
_PURGE_INTERVAL = 300.0

router = APIRouter(prefix="/api/auth", tags=["auth"])

# L1 缓存：sid -> {username, role, exp, created, last_seen, allowedGroups, allowedCards, persistent}
# exp <= 0 表示永不过期（常驻会话）。真相源是数据库，这里只是热路径缓存。
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_warm_done = False
_last_persist: dict[str, float] = {}
_last_purge = 0.0
_db_warned = False


def _new_sid() -> str:
    return secrets.token_urlsafe(32)


def _now() -> float:
    return time.time()


def _new_user(username: str, role: str = "viewer") -> dict:
    """构造会话用户主体（与门户 /me 返回的 user 结构对齐）。"""
    return {"username": username, "role": role}


# ============================================================
# 持久化（双模：MY_APP_DB_MODE=sqlite -> db/app.db；=pg -> app schema）
# 所有库操作均「尽力而为」：失败只告警一次，不影响鉴权主流程。
# ============================================================
def _ensure_table(conn) -> None:
    """幂等建表（'?' 占位符 + BIGINT 同时兼容 sqlite 与 PostgreSQL）。

    exp <= 0 约定为「永不过期」（常驻大屏会话）。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_sessions (
            sid TEXT PRIMARY KEY,
            username TEXT,
            role TEXT,
            exp BIGINT,
            created BIGINT,
            last_seen BIGINT,
            allowed_groups TEXT,
            allowed_cards TEXT,
            persistent INTEGER
        )
        """
    )


def _row_to_session(row) -> dict[str, Any]:
    try:
        groups = json.loads(row["allowed_groups"]) if row["allowed_groups"] else None
    except Exception:  # noqa: BLE001
        groups = None
    try:
        cards = json.loads(row["allowed_cards"]) if row["allowed_cards"] else None
    except Exception:  # noqa: BLE001
        cards = None
    return {
        "username": row["username"] or "",
        "role": row["role"] or "viewer",
        "exp": float(row["exp"] or 0),
        "created": float(row["created"] or 0),
        "last_seen": float(row["last_seen"] or 0),
        "allowedGroups": groups,
        "allowedCards": cards,
        "persistent": bool(row["persistent"]),
    }


def _db_warn(exc: Exception, action: str) -> None:
    global _db_warned
    if not _db_warned:
        _db_warned = True
        logger.warning("[portal-auth] 会话%s失败，已退回纯内存模式（同类告警后续静默）: %s", action, exc)


def _db_upsert(sid: str, s: dict) -> None:
    try:
        with get_raw_connection() as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO portal_sessions "
                "(sid, username, role, exp, created, last_seen, allowed_groups, allowed_cards, persistent) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(sid) DO UPDATE SET "
                "username=excluded.username, role=excluded.role, exp=excluded.exp, "
                "last_seen=excluded.last_seen, allowed_groups=excluded.allowed_groups, "
                "allowed_cards=excluded.allowed_cards, persistent=excluded.persistent",
                (
                    sid,
                    s.get("username", ""),
                    s.get("role", "viewer"),
                    int(s.get("exp", 0) or 0),
                    int(s.get("created", 0) or 0),
                    int(s.get("last_seen", 0) or 0),
                    json.dumps(s["allowedGroups"]) if s.get("allowedGroups") is not None else None,
                    json.dumps(s["allowedCards"]) if s.get("allowedCards") is not None else None,
                    1 if s.get("persistent") else 0,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        _db_warn(exc, "落盘")


def _db_delete(sid: str) -> None:
    try:
        with get_raw_connection() as conn:
            _ensure_table(conn)
            conn.execute("DELETE FROM portal_sessions WHERE sid=?", (sid,))
    except Exception as exc:  # noqa: BLE001
        _db_warn(exc, "删除")


def _db_get(sid: str) -> Optional[dict]:
    try:
        with get_raw_connection() as conn:
            _ensure_table(conn)
            row = conn.execute(
                "SELECT sid, username, role, exp, created, last_seen, allowed_groups, allowed_cards, persistent "
                "FROM portal_sessions WHERE sid=?",
                (sid,),
            ).fetchone()
        return _row_to_session(row) if row is not None else None
    except Exception as exc:  # noqa: BLE001
        _db_warn(exc, "读取")
        return None


def _db_load_all(now: float) -> dict[str, dict]:
    """把未过期会话全部读回内存（进程重启后恢复登陆态）。"""
    out: dict[str, dict] = {}
    try:
        with get_raw_connection() as conn:
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT sid, username, role, exp, created, last_seen, allowed_groups, allowed_cards, persistent "
                "FROM portal_sessions WHERE exp <= 0 OR exp > ?",
                (int(now),),
            ).fetchall()
        for row in rows:
            out[row["sid"]] = _row_to_session(row)
    except Exception as exc:  # noqa: BLE001
        _db_warn(exc, "预热")
    return out


def _db_purge(now: float) -> None:
    try:
        with get_raw_connection() as conn:
            _ensure_table(conn)
            conn.execute("DELETE FROM portal_sessions WHERE exp > 0 AND exp <= ?", (int(now),))
    except Exception as exc:  # noqa: BLE001
        _db_warn(exc, "清理")


def _warm() -> None:
    """首次使用时预热内存缓存（须持有 _LOCK）。"""
    global _warm_done
    if _warm_done:
        return
    _warm_done = True
    loaded = _db_load_all(_now())
    if loaded:
        _SESSIONS.update(loaded)
        logger.info("[portal-auth] 从数据库恢复 %d 个会话", len(loaded))


# ============================================================
# 会话生命周期
# ============================================================
def _is_expired(s: dict) -> bool:
    exp = float(s.get("exp", 0) or 0)
    return exp > 0 and exp <= _now()


def _prune(force: bool = False) -> None:
    """清理过期会话（内存 + 库），节流执行（须持有 _LOCK）。"""
    global _last_purge
    now = _now()
    for sid in [sid for sid, s in _SESSIONS.items() if _is_expired(s)]:
        _SESSIONS.pop(sid, None)
        _last_persist.pop(sid, None)
    if not force and (now - _last_purge) < _PURGE_INTERVAL:
        return
    _last_purge = now
    _db_purge(now)


def _touch(sid: str, s: dict) -> None:
    """滑动续期 + last_seen，并按节流写回数据库（须持有 _LOCK）。"""
    if s.get("persistent"):
        return  # 常驻会话永不过期，无需续期
    now = _now()
    s["last_seen"] = now
    if SESSION_SLIDING:
        new_exp = now + SESSION_TTL
        if SESSION_MAX_TTL > 0:
            new_exp = min(new_exp, float(s.get("created", now) or now) + SESSION_MAX_TTL)
        if new_exp > float(s.get("exp", 0) or 0):
            s["exp"] = new_exp
    if (now - _last_persist.get(sid, 0.0)) >= SESSION_PERSIST_INTERVAL:
        _last_persist[sid] = now
        _db_upsert(sid, s)


def _cookie_kwargs(max_age: int) -> dict:
    kw: dict[str, Any] = {
        "key": SESSION_COOKIE,
        "path": "/",
        "httponly": True,
        "samesite": "lax",
    }
    if max_age and max_age > 0:
        kw["max_age"] = max_age
    return kw


async def verify_portal_token(portal_token: str) -> Optional[dict]:
    """回调 uniplam 门户 /me 验证门户 token，返回其返回的 {user}；失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=UNIPLAM_TIMEOUT) as client:
            resp = await client.get(
                UNIPLAM_ME_URL,
                headers={"Authorization": f"Bearer {portal_token}"},
            )
        if resp.status_code != 200:
            logger.info("[portal-auth] uniplam /me 返回 %s", resp.status_code)
            return None
        data = resp.json()
        user = data.get("user") if isinstance(data, dict) else None
        return user if isinstance(user, dict) else None
    except Exception as exc:  # noqa: BLE001  网络/解析失败一律视为验证不通过
        logger.warning("[portal-auth] uniplam /me 调用失败: %s", exc)
        return None


def create_session(user: dict, response: Response, persistent: bool = False) -> str:
    """为通过门户验证的用户建立 myapp 会话（内存 + 落盘 + Cookie），返回 sid。

    persistent=True 时签发「常驻会话」：exp=0 永不过期，用于大屏常驻展示。
    """
    sid = _new_sid()
    now = _now()
    payload = {
        "username": user.get("username", user.get("id", "")),
        "role": user.get("role", "viewer"),
        "exp": 0.0 if persistent else now + SESSION_TTL,
        "created": now,
        "last_seen": now,
        "allowedGroups": user.get("allowedGroups"),
        "allowedCards": user.get("allowedCards"),
        "persistent": persistent,
    }
    with _LOCK:
        _prune()
        _SESSIONS[sid] = payload
        _last_persist[sid] = now
    _db_upsert(sid, payload)
    response.set_cookie(
        value=sid,
        **_cookie_kwargs(KIOSK_COOKIE_MAX_AGE if persistent else SESSION_COOKIE_MAX_AGE),
    )
    return sid


def destroy_session(request: Request, response: Response):
    """注销当前会话（内存 + 落盘）并清除 Cookie。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        with _LOCK:
            _SESSIONS.pop(sid, None)
            _last_persist.pop(sid, None)
        _db_delete(sid)
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def read_session(request: Request) -> Optional[dict]:
    """按 Cookie 取当前有效会话；不存在/过期返回 None。内存未命中时回查数据库。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    with _LOCK:
        _warm()
        session = _SESSIONS.get(sid)
        if session is None:
            # 回查落盘（进程刚重启 / 另一进程创建 / 内存被清）
            session = _db_get(sid)
            if session is None:
                return None
            _SESSIONS[sid] = session
        if _is_expired(session):
            _SESSIONS.pop(sid, None)
            _last_persist.pop(sid, None)
            _db_delete(sid)
            return None
        _touch(sid, session)
        return session


def current_user(request: Request) -> Optional[dict]:
    """给鉴权中间件/端点读当前用户；本机回环（内部脚本/调度）视为已授权并给占位身份。"""
    if client_is_local(request):
        return {"username": "local", "role": "admin"}
    return read_session(request)


def require_user(request: Request):
    """FastAPI 依赖：确保当前请求已登录（或本机），否则 401。"""
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录：请通过统一门户登录")
    return user


# ============================================================
# 路由
# ============================================================
def _local_session(response: Response) -> dict:
    """本机回环直接放行并种下会话（避免本地开发被强制登录卡住）。"""
    sid = _new_sid()
    now = _now()
    payload = {
        "username": "local",
        "role": "admin",
        "exp": now + SESSION_TTL,
        "created": now,
        "last_seen": now,
        "allowedGroups": None,
        "allowedCards": None,
        "persistent": False,
    }
    with _LOCK:
        _SESSIONS[sid] = payload
        _last_persist[sid] = now
    _db_upsert(sid, payload)
    response.set_cookie(value=sid, **_cookie_kwargs(SESSION_COOKIE_MAX_AGE))
    return {"username": "local", "role": "admin"}


@router.post("/portal-login")
async def portal_login(payload: dict, request: Request, response: Response):
    """用门户 token 换 myapp 会话 Cookie。"""
    if client_is_local(request):
        return {"user": _local_session(response)}

    token = payload.get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="缺少门户 token")
    user = await verify_portal_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="门户登录验证失败：请先在门户登录后重试")
    create_session(user, response)
    return {"user": user}


@router.post("/logout")
async def logout(request: Request, response: Response):
    destroy_session(request, response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录：请通过统一门户登录")
    return {"user": user}


def _safe_next(next_path: Optional[str]) -> str:
    """校验跳转目标，只允许站内相对路径（防开放重定向）。"""
    p = (next_path or "/myapp/").strip()
    if not p.startswith("/") or p.startswith("//") or "://" in p or "\\" in p:
        return "/myapp/"
    return p


@router.get("/kiosk")
async def kiosk(key: str = "", next: str = ""):
    """大屏常驻登录：种下永不过期的会话 Cookie 后 302 跳回看板。

    用法：`/api/auth/kiosk?key=<MYAPP_KIOSK_KEY>&next=/myapp/?page=cxo_dashboard`
    仅当环境变量 MYAPP_KIOSK_KEY 非空时可用；密钥不符返回 403。
    """
    if not KIOSK_KEY:
        raise HTTPException(status_code=404, detail="未启用常驻会话（未设置 MYAPP_KIOSK_KEY）")
    if not secrets.compare_digest(key or "", KIOSK_KEY):
        raise HTTPException(status_code=403, detail="常驻会话密钥不正确")
    target = _safe_next(next)
    resp = RedirectResponse(url=target, status_code=302)
    create_session(_new_user("kiosk", "viewer"), resp, persistent=True)
    logger.info("[portal-auth] 已签发常驻会话 -> %s", target)
    return resp


@router.post("/kiosk-login")
async def kiosk_login(payload: dict, response: Response):
    """大屏常驻登录（JSON 版，供脚本/页面直接调用）。"""
    if not KIOSK_KEY:
        raise HTTPException(status_code=404, detail="未启用常驻会话（未设置 MYAPP_KIOSK_KEY）")
    key = payload.get("key")
    if not isinstance(key, str) or not secrets.compare_digest(key, KIOSK_KEY):
        raise HTTPException(status_code=403, detail="常驻会话密钥不正确")
    create_session(_new_user("kiosk", "viewer"), response, persistent=True)
    return {"user": {"username": "kiosk", "role": "viewer"}, "persistent": True}
