#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cxo_dashboard_cache.py — CXO 看板 last-known-good 缓存同步（worker 定时任务，每 10 分钟）

背景：
    cxo_dashboard.html 此前只有两条数据链路：构建时内嵌的静态快照（会过期、Health 页
    完全没有）+ 打开页面时的实时拉取（VMAX/代理不可用时静默退回旧快照 → 看板大片空数据）。
    本任务补第三层：后台周期性经本机 8790 VMAX 代理（scripts/realtime_proxy_vmax.py，
    单会话、自带 re-login）拉取看板全部接口，按「接口粒度」合并为 last-known-good：
    某接口本次返回空/失败时保留旧值，只有拿到非空新值才覆盖。

产出：
    data/cxo_dashboard/last_known_good.json   —— 缓存主文件（GET /api/cxo-dashboard/cache 透传给前端）
    data/cxo_dashboard/history.jsonl          —— 每次运行追加一行 Summary KPI + Health 概要，积累趋势

关键约定（与前端 refreshInner 逐字对齐，改接口清单时两侧同步）：
    - Service 10 业务：getIndicatorData(逐 infoId) + geMapRender + getDelimitPie + getLimitTable
    - getDelimitPie 的 time 必须取同业务第一个 getIndicatorData 响应的 time 字段
      （发 "now" 会落在聚合窗口外 -> 空饼图，见 cxo_dashboard.html refreshInner 注释）
    - Network 5 个 tab 全部 view_id=2
    - Summary trend 只拉 91/92/93/94/95/99（96-98 实时无数据）
    - Health 走 GET /healthView/*，params 放目标 URL 的 ?params=<json>

运行时长：结果 dict 带 elapsed_seconds（秒），结束打印总耗时。
"""
import json
import logging
import os
import sys
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path

import requests

from backend.services.atomic_write import atomic_replace_file
from backend.services.realtime_proxy_ctl import (PROXIES, _proxy_healthy,
                                                 ensure_proxy)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent  # my_app/
DATA_DIR = _ROOT / "data" / "cxo_dashboard"
CACHE_FILE = DATA_DIR / "last_known_good.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX_BASE = ("https://10.123.255.12:26180/rdk/service/app/insight/"
             "realtimeguarantee/ds_dashboard_Overseas/server")

BASE_QUERY = {"province_id": "", "city_id": "", "area_id": ""}

# 与 cxo_dashboard.html 内嵌 DATA / refreshInner 完全一致的业务清单
SERVICE_MANIFEST = {
    "Mobility":   {"view_id": 2, "infoIds": [391, 392, 393]},
    "Voice":      {"view_id": 2, "infoIds": [412, 413, 414]},
    "Data":       {"view_id": 2, "infoIds": [431, 433, 434]},
    "Video":      {"view_id": 2, "infoIds": [451]},
    "SMS":        {"view_id": 1, "infoIds": [202, 204, 205, 206, 207, 208]},
    "Web Browse": {"view_id": 1, "infoIds": [221, 223, 224, 225, 226, 227, 228]},
    "Game":       {"view_id": 1, "infoIds": [242, 243, 244, 245]},
    "OTTVoice":   {"view_id": 1, "infoIds": list(range(262, 273))},
    "OTTVideo":   {"view_id": 1, "infoIds": [282, 283]},
}

NET_TABS = {  # 全部 view_id=2
    1: [391, 392, 393],
    2: [411, 412, 413, 414],
    3: [431, 433, 434],
    4: [451],
    5: [471, 472, 473],
}

SUMMARY_TREND_IDS = [91, 92, 93, 94, 95, 99]  # 96-98 实时无数据，跳过
SUMMARY_OVERVIEW_IDS = [131, 132, 133, 134]

_REQ_TIMEOUT = (10, 60)


# ---------- 空值判定（按组件类型；空值 => 保留旧缓存） ----------
def _series_has_data(option):
    for s in (option or {}).get("series") or []:
        data = s.get("data") if isinstance(s, dict) else None
        if isinstance(data, (list, tuple)) and len(data) > 0:
            return True
    return False


def _is_empty(kind, resp):
    if not isinstance(resp, dict):
        return True
    if kind == "indicator":
        return not _series_has_data(resp.get("option"))
    if kind == "map":
        return not resp.get("option")
    if kind == "gemap":  # Summary/geMapRender 的 series 在顶层
        return not resp.get("series")
    if kind == "delimit":
        return not (resp.get("isCauseAnalysis") and _series_has_data(resp.get("option")))
    if kind == "limit":
        data = resp.get("data")
        return not (resp.get("header") and isinstance(data, list) and data)
    if kind == "overview":
        return resp.get("kpiValue") is None
    if kind == "trend":
        yd_ok = any((s or {}).get("yData") for s in (resp.get("yData") or []))
        return not (_series_has_data(resp.get("option")) or yd_ok)
    if kind in ("userData", "cityUser"):
        return not resp.get("option")
    if kind == "health_ue":
        v = resp.get("value")
        value_ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
        subs = list(resp.get("repeat1data") or []) + list(resp.get("repeat2data") or [])
        sub_ok = any((x or {}).get("score") not in (None, "", "--", "NA") for x in subs)
        return not (value_ok or sub_ok)
    if kind in ("health_voice", "health_data"):
        # 行存在但值全为 "--"/"NA" 同样视为空（源头分区为空时的典型返回），
        # 这样曾经有过真实数据的缓存才能兜底
        def _ok(v):
            return v not in (None, "", "--", "NA")
        data = resp.get("data") or []
        if kind == "health_voice":
            return not any(_ok((x or {}).get("value")) for x in data)
        return not any(_ok((x or {}).get("lteNum")) or _ok((x or {}).get("nrNum"))
                       for x in data)
    return True


# ---------- 8790 代理请求 ----------
def _proxy_post(session, endpoint, body):
    url = PROXY_BASE + urllib.parse.quote(VMAX_BASE + endpoint, safe="")
    r = session.post(url, json=body, timeout=_REQ_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _proxy_get(session, endpoint, params=None):
    vurl = VMAX_BASE + endpoint
    if params is not None:
        vurl += "?params=" + urllib.parse.quote(json.dumps(params), safe="")
    url = PROXY_BASE + urllib.parse.quote(vurl, safe="")
    r = session.get(url, timeout=_REQ_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 缓存读写 ----------
def _load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if isinstance(cache, dict) and isinstance(cache.get("keys"), dict):
            return cache
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[cxo_cache] 旧缓存读取失败，重建: %s", e)
    return {"version": 1, "updated_at": None, "keys": {}}


def _save_cache(cache):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / f"last_known_good.{os.getpid()}.{uuid.uuid4().hex}.tmp.json"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    atomic_replace_file(str(tmp), str(CACHE_FILE), max_retries=15, base_wait=1.0)


def _append_history(keys):
    row = {"ts": _now_str()}
    for oid in SUMMARY_OVERVIEW_IDS:
        entry = keys.get(f"summary/overview_{oid}")
        if entry:
            row[f"overview_{oid}"] = (entry.get("data") or {}).get("kpiValue")
    ue = keys.get("health/userExperience")
    if ue:
        row["health_overall"] = (ue.get("data") or {}).get("value")
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- 主入口 ----------
def run_cxo_dashboard_cache_sync() -> dict:
    start = time.time()
    stats = {"fetched": 0, "updated": 0, "kept": 0, "failed": 0}
    errors = []

    # 1) 确保 8790 VMAX 代理存活（复用已有实例；代理是 DETACHED 进程，重启不杀）
    proxy_state = ensure_proxy(PROXIES[1])
    if proxy_state.get("status") == "starting":
        # 进程已拉起但登录慢：再等最多 30 秒健康检查
        deadline = time.time() + 30
        while time.time() < deadline and not _proxy_healthy(PROXIES[1]["port"]):
            time.sleep(1.0)
        proxy_state["status"] = "running" if _proxy_healthy(PROXIES[1]["port"]) else "starting"
    if proxy_state.get("status") != "running":
        msg = f"VMAX 代理不可用: {proxy_state}"
        print(f"[cxo_cache] FAIL {msg}")
        return {"success": False, "error": msg,
                "elapsed_seconds": round(time.time() - start, 2)}

    cache = _load_cache()
    keys = cache.setdefault("keys", {})
    session = requests.Session()
    session.trust_env = False  # 忽略系统代理环境变量，强制直连本机 8790

    def upsert(key, kind, resp, data_time=None):
        stats["fetched"] += 1
        if _is_empty(kind, resp):
            stats["kept"] += 1  # 空响应：保留旧值（last-known-good 核心）
            return
        entry = {"fetched_at": datetime.now().isoformat(timespec="seconds")}
        if data_time:
            entry["data_time"] = data_time
        entry["data"] = resp
        keys[key] = entry
        stats["updated"] += 1

    def fetch_post(key, kind, endpoint, body):
        try:
            resp = _proxy_post(session, endpoint, body)
        except Exception as e:
            stats["failed"] += 1
            errors.append(f"{key}: {type(e).__name__}: {e}")
            return None
        dt = resp.get("time") if isinstance(resp, dict) else None
        upsert(key, kind, resp, dt)
        return resp

    def fetch_get(key, kind, endpoint, params=None):
        try:
            resp = _proxy_get(session, endpoint, params)
        except Exception as e:
            stats["failed"] += 1
            errors.append(f"{key}: {type(e).__name__}: {e}")
            return None
        upsert(key, kind, resp)
        return resp

    # 2) Service：10 业务 × (指标 + 地图 + 因果饼 + TopN)
    for biz, cfg in SERVICE_MANIFEST.items():
        vid, prim = cfg["view_id"], cfg["infoIds"][0]
        prim_resp = None
        for info_id in cfg["infoIds"]:
            r = fetch_post(f"service/{biz}/indicator/{info_id}", "indicator",
                           "/Service/getIndicatorData",
                           {**BASE_QUERY, "tabId": 0, "infoId": info_id, "view_id": vid})
            if info_id == prim:
                prim_resp = r
        fetch_post(f"service/{biz}/map", "map", "/Service/geMapRender",
                   {**BASE_QUERY, "infoId": prim, "view_id": vid})
        # getDelimitPie 的 time 必须用同业务第一个指标的快照时间（发 now 落在窗口外 -> 空）
        data_time = (prim_resp or {}).get("time") or _now_str()
        fetch_post(f"service/{biz}/delimit", "delimit", "/network/getDelimitPie",
                   {**BASE_QUERY, "infoId": prim, "time": data_time, "gdprFlag": "false"})
        fetch_post(f"service/{biz}/limit", "limit", "/Service/getLimitTable",
                   {**BASE_QUERY, "infoId": prim, "view_id": vid})

    # 3) Network：5 个 tab（view_id=2）逐指标 + 一张网络地图
    for tab, ids in NET_TABS.items():
        for info_id in ids:
            fetch_post(f"net/tab/{tab}/indicator/{info_id}", "indicator",
                       "/Service/getIndicatorData",
                       {**BASE_QUERY, "tabId": 0, "infoId": info_id, "view_id": 2})
        fetch_post(f"net/tab/{tab}/map", "map", "/Service/geMapRender",
                   {**BASE_QUERY, "infoId": ids[0], "view_id": 2})

    # 4) Summary：趋势 + KPI 卡 + 地图 + 用户构成/城市
    for g in SUMMARY_TREND_IDS:
        fetch_post(f"summary/trend_{g}", "trend", "/Summary/getTrendAnalysis",
                   {**BASE_QUERY, "graphId": str(g)})
    for oid in SUMMARY_OVERVIEW_IDS:
        fetch_post(f"summary/overview_{oid}", "overview", "/Summary/getOverviewedInfo",
                   {**BASE_QUERY, "infoId": oid})
    fetch_post("summary/geMap", "gemap", "/Summary/geMapRender", {**BASE_QUERY})
    fetch_post("summary/userData", "userData", "/Summary/getUserData", {**BASE_QUERY})
    fetch_post("summary/cityUser", "cityUser", "/Summary/getCityUser", {**BASE_QUERY})

    # 5) Health：GET /healthView/*（当前 VMAX 分区 aggr_ds_cxo_score 为空 -> 一直 kept）
    fetch_get("health/userExperience", "health_ue", "/healthView/getUserExperience")
    fetch_get("health/voiceService", "health_voice", "/healthView/getVoiceService", {"id": ""})
    fetch_get("health/dataService", "health_data", "/healthView/getDataService",
              {"id": "", "rat": 6, "selectId": "", "time": ""})

    # 6) 落盘（原子替换，扛文件占用）
    cache["version"] = 1
    cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        _save_cache(cache)
    except Exception as e:
        stats["failed"] += 1
        errors.append(f"save_cache: {type(e).__name__}: {e}")
        elapsed = round(time.time() - start, 2)
        print(f"[cxo_cache] 缓存落盘失败 ({elapsed}s): {e}")
        return {"success": False, "error": f"缓存落盘失败: {e}",
                **stats, "elapsed_seconds": elapsed, "errors": errors[:20]}
    try:
        _append_history(keys)
    except Exception as e:
        errors.append(f"history: {type(e).__name__}: {e}")

    elapsed = round(time.time() - start, 2)
    result = {
        "success": stats["updated"] > 0,
        **stats,
        "total_keys": len(keys),
        "elapsed_seconds": elapsed,
        "errors": errors[:20],
    }
    print(f"[cxo_cache] done in {elapsed}s: fetched={stats['fetched']} "
          f"updated={stats['updated']} kept={stats['kept']} "
          f"failed={stats['failed']} keys={len(keys)}")
    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(run_cxo_dashboard_cache_sync(), ensure_ascii=False, indent=2))
