# -*- coding: utf-8 -*-
"""
eflow_alarm_query.py - 按 alarm_id 直查 eFlow 告警（本地库未命中时的兜底）

本地 db/app.db 的 realtime_alarm 只滚存约 48h，history_alarm 同步时还会过滤掉
无 TT ID 的记录，所以相当一部分 TT 的 alarm_id 在本地查不到。此时直接调 eFlow
活接口按 id 查（参考 backend/services/eflow_rules/url_aid.txt 抓包）：

1. POST /api/fm-active/v1/activealarms/table   secondarycondition.id = alarm_id
2. POST /api/fm-history/v1/hisalarms/pageinfo  secondarycondition.id = alarm_id
   （历史接口必须带告警发生时间窗口，用 TT 的 alarm_occur_time 前后扩窗）

返回的行键名统一清洗为 snake_case（与 realtime_alarm / history_alarm 列名一致），
供 inspect_tt.build_skill_prompt / build_alarm_block 直接使用。

结果按 alarm_id 做进程内 TTL 缓存（命中 5 分钟 / 未命中 60 秒），
/tt-alarm 与 /tt-ai 两个端点短时间内的重复查询只打一次 eFlow。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from backend.services.eflow_api_client import (
    _http_request, _safe_json_loads, ensure_login, get_session_headers,
    parse_response, HOST, PORT,
)
from backend.services.eflow_alarm_service import (
    ALARM_API_PATH, ALARM_REFERER, HIS_ALARM_API_PATH,
    _clean_column_name, _normalize_alarm_rows,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_HIT = 300
_CACHE_TTL_MISS = 60
_DEFAULT_BACK_DAYS = 45

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def _headers_extra() -> str:
    cookie, token = get_session_headers()
    return (
        f"Cookie: {cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z"


def _post_json(path: str, payload: Dict[str, Any], label: str):
    """POST 一次并解析 rows；返回 (rows, total_or_None, error_or_None)。"""
    headers = _headers_extra()
    status, _, _, body = _http_request(
        "POST", path, headers_extra=headers, body=json.dumps(payload))
    data, ok = _safe_json_loads(body.decode("utf-8"), label=label)
    if not ok or not isinstance(data, (dict, list)):
        return [], None, f"{label} 响应解析失败: {str(data)[:160]}"
    if isinstance(data, dict) and data.get("code") not in (0, None, "0"):
        return [], None, f"{label} 返回 code={data.get('code')}: {str(data)[:160]}"
    raw_rows = data if isinstance(data, list) else (parse_response(data) or [])
    rows = _normalize_alarm_rows(raw_rows or [])
    total = data.get("totalcount") or data.get("total") if isinstance(data, dict) else None
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    return rows, total, None


def _query_active(aid: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """实时告警按 id 查（告警仍在 active 列表时命中）。"""
    payload = {
        "timestamp": _iso_now(),
        "condition": {
            "alarmcodefiltermode": 0,
            "extensionconds": {"maintainstatus": {"filtertype": 1, "valuelist": ["0"]}},
            "sortinfo": {"sortdirection": 0, "sortfield": "servertime",
                         "combinesortinfos": []},
            "timezonetype": 0, "querymetype": 2, "id": -1, "visibles": [1],
        },
        "pagesize": 200, "page": 1,
        "secondarycondition": {"id": aid},
        "queryid": "T" + uuid.uuid4().hex,
        "activeTabId": "fm-active_ALARM_MONITOR",
        "manual": True,
    }
    rows, _, err = _post_json(ALARM_API_PATH, payload, "ActiveAlarmById")
    if err:
        return None, err
    return (rows[0] if rows else None), None


def _query_history(aid: str, start_ms: int, end_ms: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """历史告警按 id 查（需要告警发生时间窗口）。"""
    payload = {
        "querynum": 200,
        "condition": {
            "alarmcodefiltermode": 0,
            "alarmraisedtime": {"mode": "0", "start": start_ms, "end": end_ms},
            "extensionconds": {"maintainstatus": {"filtertype": 1, "valuelist": ["0"]}},
            "sortinfo": {"language": "en", "sortdirection": 0,
                         "sortfield": "alarmclearedtime", "combinesortinfos": []},
            "timezonetype": 0, "querymetype": 0, "id": -1, "idstr": "-1",
            "usefromsize": True,
        },
        "secondarycondition": {"id": aid},
        "timestamp": _iso_now(),
        "manual": True,
    }
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows, _, err = _post_json(f"{HIS_ALARM_API_PATH}?timestamp={now_ms}",
                              payload, "HistoryAlarmById")
    if err:
        return None, err
    return (rows[0] if rows else None), None


def _snake(row: Dict[str, Any]) -> Dict[str, Any]:
    """显示名列名 → snake_case（与本地告警表列名对齐）。"""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        key = _clean_column_name(str(k))
        if key in out:
            key = f"{key}_1"
        out[key] = v
    return out


def find_alarm_by_id(alarm_id: str, occur_time: Optional[datetime] = None) -> Dict[str, Any]:
    """按 alarm_id 查 eFlow：实时 → 历史。

    occur_time：TT 的告警发生时刻（UTC naive 或 aware 均可），用于确定历史接口
    的时间窗口；缺省回退到近 45 天。

    返回 {"found", "source": "eflow_active"|"eflow_history"|"", "row", "error",
          "elapsed_sec", "cached"}
    """
    aid = str(alarm_id or "").strip()
    if aid.endswith(".0") and aid[:-2].isdigit():
        aid = aid[:-2]
    t0 = time.time()
    if not aid.isdigit():
        return {"found": False, "source": "", "row": None, "cached": False,
                "error": f"alarm_id 非法: {alarm_id!r}", "elapsed_sec": 0.0}

    with _lock:
        ent = _cache.get(aid)
        if ent:
            ts, res = ent
            ttl = _CACHE_TTL_HIT if res.get("found") else _CACHE_TTL_MISS
            if time.time() - ts < ttl:
                return dict(res, cached=True, elapsed_sec=round(time.time() - t0, 3))

    ensure_login()

    result: Dict[str, Any]
    try:
        row, err = _query_active(aid)
        source = "eflow_active"
        if err or row is None:
            if occur_time is not None:
                if occur_time.tzinfo is None:
                    occur_time = occur_time.replace(tzinfo=timezone.utc)
                win_start = occur_time - timedelta(days=3)
            else:
                win_start = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_BACK_DAYS)
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            row, err2 = _query_history(
                aid, int(win_start.timestamp() * 1000), end_ms)
            source = "eflow_history"
            if err2:
                err = err or err2
        if row is None:
            result = {"found": False, "source": "", "row": None, "cached": False,
                      "error": err or "eFlow 实时/历史告警中均无该 alarm_id",
                      "elapsed_sec": round(time.time() - t0, 2)}
        else:
            result = {"found": True, "source": source, "row": _snake(row),
                      "cached": False, "error": None,
                      "elapsed_sec": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        logger.exception("eFlow 按 alarm_id 查询失败")
        result = {"found": False, "source": "", "row": None, "cached": False,
                  "error": f"{type(e).__name__}: {e}",
                  "elapsed_sec": round(time.time() - t0, 2)}

    with _lock:
        _cache[aid] = (time.time(), result)
    return result
