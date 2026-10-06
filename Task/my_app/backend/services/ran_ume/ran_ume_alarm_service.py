# -*- coding: utf-8 -*-
"""
ran_ume_alarm_service.py - 按 Alarm Key / Alarm ID 从 RAN UME 查告警详情、处理建议与历史告警
==========================================================================================
数据来源（ZTE RAN UME，抓包见同目录 url_alarm_suggestion.txt）：

1. POST /api/fm-active/v1/activealarms/alarmkey
      body {"alarmkey": "<key>", "id": <ms>}
      → {"type":0, "alarm": {...}}，其中含 alarmcode / restype / reasoncode
        以及站点/小区信息（ran_fm_alarm_site_name、ran_fm_alarm_object_name、ran_fm_alarm_dn …）
2. POST /api/fm-active/v1/suggestions
      body {"restype":"<restype>","alarmcode":<code>,"reasoncode":<code>,
            "customermaintenancename":"","codetype":0}
      → {"defaultmaintenancename":"...", "customermaintenancename":"..."}
3. POST /api/fm-history/v1/hisalarms/pageinfo?timestamp=<ms>
      body condition.alarmraisedtime 时间窗 + secondarycondition.positionname = 站点名
      → {"totalcount":N, "alarms":[...]}

实测要点（2026-09-06，10.100.28.27:28001）：
- 历史接口的 secondarycondition 只有 `id` 与 `positionname` 两个键真正生效，
  其余键（sitename / mename / neid …）会被静默忽略并返回全库 69 万条。
- `positionname` 是前缀/包含匹配：传 "Zubah Town" 得站点级 15 条，
  传完整 positionname 得小区级 2 条。
- /api/fm-active/v1/activealarms/table 的 secondarycondition.id 在本机 UME 上不生效，
  故数字 Alarm ID 走「历史 by id」兜底。
- eFlow 与 UME 的告警编号分属两套体系：TT/告警表的 Alarm ID（id 列）是 eFlow
  编号，告警表 aid 列才是 UME 侧告警 ID。数字输入先经本地表把 eFlow 编号翻译成
  UME 侧 ID 再直查历史；本地无匹配行时退 eflow_tt 取 站点+时刻，按「站点+时刻」
  关联 UME 告警。

本模块只读，不写库。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ran_ume_alarm_service")

# ========== 配置（env > ran_ume_config.json > 内置默认） ==========
HOST = os.environ.get("RAN_UME_HOST", "10.100.28.27")
PORT = int(os.environ.get("RAN_UME_PORT", "28001"))
_USERNAME = os.environ.get("RAN_UME_USER", "NOC")
# 2026-09-27：原默认值为硬编码明文口令（已入库）。改为默认空串 —— 真实口令由
# credential_store 的 `zte_ume` 组提供；env/配置都取不到时留空让认证明确失败。
_PASSWORD = os.environ.get("RAN_UME_PASS", "")

try:
    from pathlib import Path
    from backend.services.task_config_files import load_json_config
    _CONF = load_json_config(Path(__file__).resolve().parents[1] / "ran_ume_config.json")
except Exception:
    _CONF = None
if _CONF:
    if not os.environ.get("RAN_UME_HOST"):
        HOST = _CONF.get("host", HOST)
    if not os.environ.get("RAN_UME_PORT"):
        PORT = int(_CONF.get("port", PORT))

ACTIVE_ALARMKEY_PATH = "/api/fm-active/v1/activealarms/alarmkey"
SUGGESTION_PATH = "/api/fm-active/v1/suggestions"
HISTORY_PATH = "/api/fm-history/v1/hisalarms/pageinfo"

DEFAULT_HISTORY_DAYS = 30
DEFAULT_HISTORY_LIMIT = 50


def _runtime_credentials() -> Tuple[str, str]:
    """环境变量 > 数据库(credential_store) > 模块默认值。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("zte_ume", _USERNAME, _PASSWORD,
                          env_user="RAN_UME_USER", env_secret="RAN_UME_PASS")


def probe_alarm_session(cookie: str, forgery_token: str) -> bool:
    """探活 RAN UME 会话：POST 一个**故意没有查询条件**的告警查询。

    为什么必须探**业务端点**：MW UME 2026-10-04 实测探登录首页返回 200
    （假绿，首页对未登录也放行），业务端点才返回 401。这里用
    `ACTIVE_ALARMKEY_PATH` —— 本服务真正在用的当前告警接口。

    判定：401/403/419/499 = 会话死（419/499 是本上游的会话类状态码，
    见 `_post` 的处理）；其余状态码（400/500 等）= 会话活着，只是空 body
    的参数不合法（上游先校验会话再解析参数）。异常按不可用处理 ——
    拿不到证据就不复用，退回真实登录。

    ⚠️ 只发**一发**空 payload 的 POST，不做分页、不落库、不重试；本函数
    由 `auth_manager.get_auth(probe=...)` 在取会话路径调用，每轮至多一發。
    绝不挪进请求热路径（本项目已因「每任务登录一次」把 eFlow 打崩过一次）。
    """
    import requests
    try:
        from backend.security_tls import tls_verify, silence_insecure_warning
    except ImportError:  # pragma: no cover
        tls_verify = lambda _s: False  # noqa: E731
        silence_insecure_warning = lambda _v: None  # noqa: E731
    verify = tls_verify("ume")
    silence_insecure_warning(verify)

    base = f"https://{HOST}:{PORT}"
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "Referer": f"{base}/uportal/framework/default.html",
        "X-Requested-With": "XMLHttpRequest",
        "language-option": "en-US",
        "timeZoneInfo": "Default,Atlantic/Reykjavik,",
        "Origin": base,
    }
    if forgery_token:
        # 头名必须是不带端口后缀的裸 forgerydefense（cookie 名可能带 -28001，
        # 但请求头带后缀同样 403 —— 见 auth_manager 顶部实测记录）
        headers["forgerydefense"] = forgery_token
    try:
        r = requests.post(f"{base}{ACTIVE_ALARMKEY_PATH}", headers=headers,
                          json={}, verify=verify, timeout=15)
        alive = r.status_code not in (401, 403, 419, 499)
        if not alive:
            logger.info("[ALARM] 共享会话已失效（探测 %s -> %s）",
                        ACTIVE_ALARMKEY_PATH, r.status_code)
        return alive
    except Exception as e:  # noqa: BLE001
        # 区分「探测本身坏了」与「会话真死了」：否则日志里两者长得一样
        logger.warning("[ALARM] 会话探测异常（%s: %s），按不可用处理",
                       type(e).__name__, e)
        return False


def _auth(force_refresh: bool = False) -> Tuple[str, str]:
    """取 (cookie, forgery_token)，复用 auth_manager 的共享缓存避免同账户互踢。

    2026-10-06：接入 `probe_alarm_session` 探活。此前快路径只按 TTL 判过期、
    不做探活，死 cookie 会被发给调用方（RAN UME 实测 113 分钟即失效，
    而 TTL 当时 86400）→ 本服务会拿死会话打出一片 401。
    """
    try:
        from backend.services.auth_manager import get_auth, invalidate_cache
    except ImportError:  # pragma: no cover
        from auth_manager import get_auth, invalidate_cache  # type: ignore
    if force_refresh:
        try:
            invalidate_cache(HOST, PORT)
        except Exception:
            logger.debug("invalidate_cache 失败", exc_info=True)
    user, pwd = _runtime_credentials()
    r = get_auth(HOST, PORT, user, pwd, probe=probe_alarm_session)
    return r.get("cookie", ""), r.get("forgery_token", "")


def _post(path: str, payload: Dict[str, Any], timeout: int = 45) -> Tuple[Optional[dict], Optional[str]]:
    """POST 到 UME。返回 (json_dict, error)。401/403/419/499 会强制重登后重试一次。"""
    import requests
    try:
        from backend.security_tls import tls_verify, silence_insecure_warning
    except ImportError:  # pragma: no cover
        tls_verify = lambda _s: False  # noqa: E731
        silence_insecure_warning = lambda _v: None  # noqa: E731
    verify = tls_verify("ume")
    silence_insecure_warning(verify)

    base = f"https://{HOST}:{PORT}"
    last_err = None
    for attempt in (0, 1):
        cookie, token = _auth(force_refresh=bool(attempt))
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Cookie": cookie,
            "forgerydefense": token,
            "Referer": f"{base}/uportal/framework/default.html",
            "X-Requested-With": "XMLHttpRequest",
            "language-option": "en-US",
            "timeZoneInfo": "Default,Atlantic/Reykjavik,",
            "Origin": base,
        }
        try:
            r = requests.post(f"{base}{path}", headers=headers, json=payload,
                              verify=verify, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            continue
        if r.status_code == 200:
            try:
                return r.json(), None
            except Exception:
                return None, f"响应非 JSON：{r.text[:200]}"
        last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code not in (401, 403, 419, 499):
            break
    return None, last_err


# ------------------------- 字段解包 -------------------------

def _val(x: Any) -> Any:
    """UME 扩展字段 {value, displayname} → 原始 value。"""
    if isinstance(x, dict):
        return x.get("value")
    return x


def _disp(x: Any) -> Any:
    """UME 扩展字段 → 展示名（英文），没有则回落 value。"""
    if isinstance(x, dict):
        d = x.get("displayname")
        if d not in (None, ""):
            return d
        return x.get("value")
    return x


def _ms_to_str(ms: Any) -> str:
    """毫秒时间戳 → 'YYYY-MM-DD HH:MM:SS'（UME 侧为 GMT，按 UTC 呈现）。"""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _dt_to_ms(v: Any) -> int:
    """'YYYY-MM-DD HH:MM:SS' / datetime / 毫秒值 → 毫秒时间戳（UTC），解析失败返回 0。"""
    if v in (None, "", "--", "—"):
        return 0
    if isinstance(v, (int, float)):
        return int(float(str(v)))
    if isinstance(v, datetime):
        return int(v.replace(tzinfo=v.tzinfo or timezone.utc).timestamp() * 1000)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return 0


def _json_or_none(s: Any) -> Optional[dict]:
    if not isinstance(s, str) or not s.strip().startswith("{"):
        return None
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# ------------------------- 三个原子查询 -------------------------

def fetch_alarm_by_key(alarmkey: str) -> Tuple[Optional[dict], Optional[str]]:
    """POST /api/fm-active/v1/activealarms/alarmkey → alarm 对象。"""
    data, err = _post(ACTIVE_ALARMKEY_PATH,
                      {"alarmkey": alarmkey, "id": int(time.time() * 1000)})
    if err:
        return None, err
    alarm = (data or {}).get("alarm")
    if not alarm:
        return None, "UME 未返回该 Alarm Key 对应的活动告警（可能已清除，请改用历史查询）"
    return alarm, None


def fetch_suggestions(restype: Any, alarmcode: Any, reasoncode: Any) -> Tuple[Optional[dict], Optional[str]]:
    """POST /api/fm-active/v1/suggestions → 处理建议。"""
    code = alarmcode if alarmcode not in (None, "") else reasoncode
    if code in (None, ""):
        return None, "缺少 alarmcode，无法查询处理建议"
    payload = {
        "restype": str(restype or ""),
        "alarmcode": code,
        "reasoncode": reasoncode if reasoncode not in (None, "") else code,
        "customermaintenancename": "",
        "codetype": 0,
    }
    data, err = _post(SUGGESTION_PATH, payload)
    if err:
        return None, err
    if not data:
        return None, "UME 未返回处理建议"
    return {
        "default": (data.get("defaultmaintenancename") or "").strip(),
        "customer": (data.get("customermaintenancename") or "").strip(),
        "restype": str(restype or ""),
        "alarmcode": code,
    }, None


def fetch_history(position: str, days: int = DEFAULT_HISTORY_DAYS,
                  limit: int = DEFAULT_HISTORY_LIMIT) -> Tuple[Optional[dict], Optional[str]]:
    """POST /api/fm-history/v1/hisalarms/pageinfo，按 positionname 过滤历史告警。"""
    if not position:
        return None, "缺少站点/小区位置，无法查询历史告警"
    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=days)).timestamp() * 1000)
    payload = {
        "querynum": limit,
        "condition": {
            "alarmcodefiltermode": 0,
            "alarmraisedtime": {"mode": "0", "start": start_ms, "end": end_ms},
            "sortinfo": {"language": "en", "sortdirection": 0,
                         "sortfield": "alarmraisedtime", "combinesortinfos": []},
            "timezonetype": 0, "querymetype": 0, "id": -1, "idstr": "-1",
            "usefromsize": True, "from": 0, "size": limit,
        },
        "secondarycondition": {"positionname": position},
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "manual": True,
    }
    data, err = _post(f"{HISTORY_PATH}?timestamp={end_ms}", payload, timeout=60)
    if err:
        return None, err
    rows = (data or {}).get("alarms") or []
    items = []
    for a in rows:
        items.append({
            "raised_time": _ms_to_str(a.get("alarmraisedtime") or a.get("offsetalarmraisedtime")),
            "cleared_time": _ms_to_str(a.get("alarmclearedtime") or a.get("offsetalarmclearedtime")),
            "alarmcode": a.get("alarmcode"),
            "name": a.get("codename") or _disp(a.get("alarmtitle")),
            "severity": a.get("perceivedseverityname"),
            "object": _val(a.get("ran_fm_alarm_object_name")),
            "object_type": _val(a.get("ran_fm_alarm_object_type")),
            "clear_state": a.get("clearstatename") or ("Uncleared" if a.get("clearstate") == 0 else ""),
            "duration": a.get("durationname"),
            "restype": a.get("restypename"),
            "alarmkey": a.get("alarmkey"),
        })
    try:
        total = int((data or {}).get("totalcount") or 0)
    except (TypeError, ValueError):
        total = len(items)
    return {"position": position, "days": days, "total": total,
            "count": len(items), "items": items}, None


def _hist_raw_by_site_time(position: str, raised_ms: int,
                           window_ms: int = 120000, size: int = 30
                           ) -> Tuple[List[dict], Optional[str]]:
    """按站点 + 告警发生时刻前后扩窗查历史告警，返回 UME 原始行列表。

    与 fetch_history 的区别：不做字段压缩，保留 id / alarmkey / restype /
    reasoncode 等原始字段，供 TT 关联匹配使用。
    """
    if not position or not raised_ms:
        return [], "缺少站点或发生时刻"
    now = datetime.now(timezone.utc)
    start_ms = int(raised_ms - window_ms)
    end_ms = int(raised_ms + window_ms)
    payload = {
        "querynum": size,
        "condition": {
            "alarmcodefiltermode": 0,
            "alarmraisedtime": {"mode": "0", "start": start_ms, "end": end_ms},
            "sortinfo": {"language": "en", "sortdirection": 0,
                         "sortfield": "alarmraisedtime", "combinesortinfos": []},
            "timezonetype": 0, "querymetype": 0, "id": -1, "idstr": "-1",
            "usefromsize": True, "from": 0, "size": size,
        },
        "secondarycondition": {"positionname": position},
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "manual": True,
    }
    data, err = _post(f"{HISTORY_PATH}?timestamp={int(time.time() * 1000)}",
                      payload, timeout=60)
    if err:
        return [], err
    return ((data or {}).get("alarms") or []), None


def find_alarm_by_event(site_name: str, raised_ms: int,
                        days: int = DEFAULT_HISTORY_DAYS,
                        limit: int = DEFAULT_HISTORY_LIMIT,
                        with_history: bool = False) -> Dict[str, Any]:
    """按 站点名 + 告警发生时刻 关联 UME 告警（TT 场景专用）。

    eFlow 与 UME 的告警 ID 分属两个体系（eflow_tt/告警表的 alarm_id 在 UME
    查不到），但同一条底层告警在两边的 alarmraisedtime 毫秒值一致、站点名
    即 UME 的 positionname 前缀。故用「站点 + 时刻」关联，取窗口内最早一条
    （同站同刻的 Cell interruption 等衍生告警成组出现，最早的通常是根告警），
    再走与 lookup_alarm 相同的建议/历史组装。

    返回结构与 lookup_alarm 一致，额外多一个 "match": "site_time"。
    """
    out: Dict[str, Any] = {
        "ok": False, "error": None, "input": f"{site_name}@{raised_ms}",
        "mode": "site_time", "match": "site_time", "elapsed_sec": 0.0,
        "alarm": None, "site_cell": None, "suggestion": None,
        "history": None, "history_cell": None,
    }
    t0 = time.time()
    site = str(site_name or "").strip()
    try:
        raised_ms = int(raised_ms)
    except (TypeError, ValueError):
        out["error"] = f"告警发生时刻非法: {raised_ms!r}"
        return out
    if not site:
        out["error"] = "缺少站点名，无法关联 UME 告警"
        out["elapsed_sec"] = round(time.time() - t0, 2)
        return out

    rows, err = _hist_raw_by_site_time(site, raised_ms)
    if err:
        out["error"] = f"UME 历史告警查询失败: {err}"
        out["elapsed_sec"] = round(time.time() - t0, 2)
        return out
    if not rows:
        out["error"] = (f"UME 近期历史中未找到站点 {site} 在告警时刻附近的告警"
                        f"（可能已滚出保留期或站点名不一致）")
        out["elapsed_sec"] = round(time.time() - t0, 2)
        return out

    alarm = min(rows, key=lambda a: int(a.get("alarmraisedtime") or 0))
    out["match_count"] = len(rows)
    out["match_codes"] = sorted({str(a.get("alarmcode") or "") for a in rows if a.get("alarmcode")})

    restype, alarmcode, reasoncode = _suggestion_source(alarm)
    out["alarm"] = {
        "alarmkey": alarm.get("alarmkey") or "",
        "alarm_id": str(alarm.get("id") or ""),
        "alarmcode": alarmcode,
        "reasoncode": reasoncode,
        "restype": restype,
        "restype_name": alarm.get("restypename") or "",
        "title_en": _disp(alarm.get("alarmtitle")) or alarm.get("codename") or "",
        "title_zh": _val(alarm.get("alarmtitle")) or "",
        "code_name": alarm.get("codename") or "",
        "severity": alarm.get("perceivedseverityname") or "",
        "alarm_type": alarm.get("alarmtypename") or "",
        "ack_state": alarm.get("ackstatename") or "",
        "clear_state": alarm.get("clearstatename") or ("Uncleared" if alarm.get("clearstate") == 0 else ""),
        "raised_time": _ms_to_str(alarm.get("alarmraisedtime")),
        "changed_time": _ms_to_str(alarm.get("alarmchangedtime")),
        "server_time": _ms_to_str(alarm.get("servertime") or alarm.get("historyservertime")),
        "duration": alarm.get("durationname") or "",
        "reason": alarm.get("reasonname") or "",
        "additional_text": alarm.get("additionaltext") or "",
        "source": "UME 历史告警（按站点+时刻关联）",
    }

    site_cell = _build_site_cell(alarm)
    out["site_cell"] = site_cell

    sug, sug_err = fetch_suggestions(restype, alarmcode, reasoncode)
    out["suggestion"] = sug
    if sug_err:
        out["suggestion_error"] = sug_err

    if with_history:
        pos_site = site_cell.get("site_name") or site_cell.get("object_name") or site
        h, h_err = fetch_history(pos_site, days=days, limit=limit)
        out["history"] = h
        if h_err:
            out["history_error"] = h_err

    out["ok"] = True
    out["elapsed_sec"] = round(time.time() - t0, 2)
    return out


# ------------------------- 本地维表补充 -------------------------

def _local_alarm_by_aid(aid: Any) -> Optional[dict]:
    """把数字 Alarm ID 解析为可查 UME 的键（TT 场景链路）。

    eFlow 与 UME 的告警编号分属两套体系：TT 的 alarm_id 与实时/历史告警表的
    Alarm ID（id 列）同属 eFlow 编号，告警表的 aid 列才是 UME 侧告警 ID。
    解析顺序：
      1. 实时/历史告警表按 id 列匹配（兼容 aid 列直配，覆盖直接粘贴 UME ID）
         → 取该行 aid（UME 侧）+ 站点 + 发生时刻；
      2. 告警表无匹配行时，退 eflow_tt 按 alarm_id 反查 站点 + 发生时刻。

    返回 {"source","site_name","site_id","raised_ms","aid"}，aid 可为空串。
    全部查不到返回 None。
    """
    s = str(aid or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if not s.isdigit():
        return None
    try:
        from backend.database import get_raw_connection
        conn = get_raw_connection()
    except Exception:
        return None
    try:
        # 1) 告警表：id 列 = eFlow 侧告警 ID（TT alarm_id 同体系），匹配后取 aid 列（UME 侧）
        for table in ("realtime_alarm", "history_alarm"):
            try:
                row = conn.execute(
                    f"SELECT site_name, site_id, alarmraisedtime, aid FROM {table} "
                    "WHERE TRIM(CAST(id AS TEXT))=? OR TRIM(CAST(aid AS TEXT))=? LIMIT 1",
                    (s, s)).fetchone()
            except Exception:
                continue
            if row:
                try:
                    raised_ms = int(float(str(row[2] or "0")))
                except (TypeError, ValueError):
                    raised_ms = 0
                return {
                    "source": table,
                    "site_name": str(row[0] or "").strip(),
                    "site_id": str(row[1] or "").strip(),
                    "raised_ms": raised_ms,
                    "aid": str(row[3] or "").strip(),
                }
        # 2) eflow_tt：按 alarm_id 反查 站点 + 发生时刻（告警表未同步该告警时兜底）
        try:
            row = conn.execute(
                "SELECT site_name, site_id, alarm_occur_time, alarm_server_time "
                "FROM eflow_tt WHERE TRIM(CAST(alarm_id AS TEXT))=? LIMIT 1",
                (s,)).fetchone()
        except Exception:
            row = None
        if row:
            return {
                "source": "eflow_tt",
                "site_name": str(row[0] or "").strip(),
                "site_id": str(row[1] or "").strip(),
                "raised_ms": _dt_to_ms(row[2]) or _dt_to_ms(row[3]),
                "aid": "",
            }
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _local_site_info(site_id: Any, site_name: Any) -> Optional[dict]:
    """用本地 cm_site_summary / cm_cell_data 补充区域、制式、小区清单。查不到返回 None。"""
    sid = str(site_id or "").strip()
    sname = str(site_name or "").strip()
    if not sid and not sname:
        return None
    select_site = None
    try:
        from backend.database import get_raw_connection
        conn = get_raw_connection()
    except Exception:
        return None
    try:
        for sql in (
            'SELECT "Site_ID","Site_Name","NumberOfCells","Tech","region","province_county","site_caregory" '
            'FROM cm_site_summary WHERE "Site_ID"=? OR upper("Site_Name")=upper(?)',
            'SELECT "Site_ID","Site_Name","NumberOfCells","Tech","region","province_county","site_caregory" '
            'FROM cm_site_summary WHERE "Site_ID"=? OR upper("site_name")=upper(?)',
        ):
            try:
                rows = conn.execute(sql, (sid, sname)).fetchall()
                select_site = sql
                break
            except Exception:
                continue
        if select_site is None:
            return None
        techs, regions, counties, cats, ncells = [], set(), set(), set(), 0
        for r in rows:
            if r[3]:
                techs.append(str(r[3]))
            if r[4]:
                regions.add(str(r[4]))
            if r[5]:
                counties.add(str(r[5]))
            if r[6]:
                cats.add(str(r[6]))
            try:
                ncells = max(ncells, int(r[2] or 0))
            except (TypeError, ValueError):
                pass
        cells: List[str] = []
        for sql in (
            'SELECT "Cell_Name","Tech" FROM cm_cell_data WHERE "Site_ID"=? OR upper("Site_Name")=upper(?) LIMIT 300',
            'SELECT "Cell_Name","Tech" FROM cm_cell_data WHERE "site_id"=? OR upper("site_name")=upper(?) LIMIT 300',
        ):
            try:
                for r in conn.execute(sql, (sid, sname)).fetchall():
                    nm = (r[0] or "").strip()
                    if nm and nm not in cells:
                        cells.append(nm)
                break
            except Exception:
                continue
        if not rows and not cells:
            return None
        return {
            "site_id": str(rows[0][0]) if rows else sid,
            "site_name": str(rows[0][1]) if rows else sname,
            "techs": sorted(set(techs)),
            "region": "/".join(sorted(regions)) if regions else "",
            "county": "/".join(sorted(counties)) if counties else "",
            "category": "/".join(sorted(cats)) if cats else "",
            "cell_count": ncells,
            "cells": cells,
        }
    except Exception:
        logger.debug("本地站点维表补充失败", exc_info=True)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ------------------------- 组装 -------------------------

def _build_site_cell(alarm: dict) -> dict:
    """从告警原始字段里抽取站点/小区信息。"""
    extra = _json_or_none(_val(alarm.get("ran_ems_fm_additional_params"))) or {}
    naf = _json_or_none(_val(alarm.get("ran_ems_fm_naf_params"))) or {}
    site_name = (_val(alarm.get("ran_fm_alarm_site_name"))
                 or extra.get("sitename_office") or "")
    site_id = extra.get("siteId_office") or ""
    if not site_id:
        pos = str(_val(alarm.get("positionname")) or "")
        segs = [p for p in pos.split(",") if "(" in p and ")" in p]
        if segs:
            site_id = segs[-1].split("(")[-1].split(")")[0]
    object_name = _val(alarm.get("ran_fm_alarm_object_name")) or extra.get("alarmobject_name") or ""
    object_type = _val(alarm.get("ran_fm_alarm_object_type")) or extra.get("alarmobject_type") or ""
    object_id = _val(alarm.get("ran_fm_alarm_object_id")) or extra.get("alarmobject_id") or ""

    info = {
        "site_name": site_name,
        "site_id": str(site_id),
        "object_name": object_name,
        "object_type": object_type,
        "object_id": str(object_id),
        "dn": _val(alarm.get("ran_fm_alarm_dn")) or "",
        "position": _val(alarm.get("positionname")) or "",
        "network_type": _disp(alarm.get("productRestype")) or "",
        "ne_name": alarm.get("mename") or "",
        "related_ne_name": alarm.get("relatedmename") or "",
        "ne_ip": alarm.get("neip") or "",
        "moc": alarm.get("moc") or alarm.get("mocname") or "",
        "naf_position": naf.get("nafPositionName") or "",
        "location": _val(alarm.get("ran_fm_alarm_location")) or "",
    }
    info["local"] = _local_site_info(info["site_id"], info["site_name"])
    return info


def _suggestion_source(alarm: dict) -> Tuple[Any, Any, Any]:
    return alarm.get("restype"), alarm.get("alarmcode"), alarm.get("reasoncode")


def lookup_alarm(alarm_id: str, days: int = DEFAULT_HISTORY_DAYS,
                 limit: int = DEFAULT_HISTORY_LIMIT,
                 with_history: bool = True) -> Dict[str, Any]:
    """按 Alarm Key（或数字 Alarm ID，走历史/站点+时刻兜底）查 UME。

    数字输入的解析链：
      1. 本地翻译：告警表 id 列（eFlow 侧告警 ID，与 TT alarm_id 同体系）
         匹配 → 取该行 aid 列（UME 侧告警 ID）；告警表无匹配行时退
         eflow_tt 按 alarm_id 反查 站点+发生时刻（见 _local_alarm_by_aid）；
      2. 用 UME 侧 ID 直查 UME 历史（secondarycondition.id）；
      3. 直查未命中且有站点+时刻 → find_alarm_by_event 按「站点+时刻」
         关联 UME 告警，带出详情/建议/历史。

    返回 {"ok","error","input","mode","elapsed_sec","alarm","site_cell",
          "suggestion","history","history_cell"}。
    """
    t0 = time.time()
    key = str(alarm_id or "").strip()
    out: Dict[str, Any] = {
        "ok": False, "error": None, "input": key, "mode": "", "elapsed_sec": 0.0,
        "alarm": None, "site_cell": None, "suggestion": None,
        "history": None, "history_cell": None,
    }
    if not key:
        out["error"] = "请输入 Alarm Key / Alarm ID"
        return out

    alarm: Optional[dict] = None
    mode = ""
    err: Optional[str] = None

    # 1) 优先按 alarmkey 查活动告警（抓包里的主路径）。
    #    纯数字 Alarm ID（TT 告警表 AID 列的形态）不是 alarmkey 串，直接跳过，
    #    省一次注定失败的 UME 往返。
    err_key: Optional[str] = None
    if key.isdigit():
        err_key = "数字 Alarm ID 不适用于 alarmkey 接口"
    else:
        alarm, err_key = fetch_alarm_by_key(key)

    # 2) 数字 Alarm ID 兜底：先经本地表把 eFlow 侧编号翻译成 UME 侧告警 ID
    #    （告警表 id 列 → aid 列），用 UME 侧 ID 直查历史；本地解析不出或
    #    UME 未命中时，再退「站点+时刻」关联（find_alarm_by_event）。
    if alarm is None and key.isdigit():
        local = _local_alarm_by_aid(key)
        ume_id = (local or {}).get("aid") or key
        data, e2 = _post(f"{HISTORY_PATH}?timestamp={int(time.time() * 1000)}", {
            "querynum": 1,
            "condition": {
                "alarmcodefiltermode": 0,
                "sortinfo": {"language": "en", "sortdirection": 0,
                             "sortfield": "alarmraisedtime", "combinesortinfos": []},
                "timezonetype": 0, "querymetype": 0, "id": -1, "idstr": "-1",
                "usefromsize": True, "from": 0, "size": 1,
            },
            "secondarycondition": {"id": ume_id},
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "manual": True,
        }, timeout=60)
        rows = ((data or {}).get("alarms") or []) if not e2 else []
        if rows:
            # 历史记录没有 alarmkey 接口的 alarm 包裹层，字段同构，直接复用
            alarm = rows[0]
            alarm.setdefault("alarmkey", ume_id)
            mode = "history_id"
            err = None
        elif local and local.get("site_name") and local.get("raised_ms"):
            # 3) 站点+时刻关联兜底（本地解析出站点/时刻但 UME 直查未命中时）
            ev = find_alarm_by_event(local["site_name"], local["raised_ms"],
                                     days=days, limit=limit,
                                     with_history=False)
            if ev.get("ok"):
                ev["input"] = key
                ev["aid_resolved"] = local
                ev["elapsed_sec"] = round(time.time() - t0, 2)
                return ev
            err = ev.get("error") or "AID 关联 UME 告警失败"
        else:
            err = e2 or ("UME 活动告警与历史告警中均无该 Alarm ID，"
                         "本地告警表与 TT 工单中也未找到该编号")
    elif alarm is not None:
        mode = "alarmkey"
        err = None
    else:
        err = err_key

    if alarm is None:
        out["error"] = err or "UME 未返回该告警"
        out["elapsed_sec"] = round(time.time() - t0, 2)
        return out

    restype, alarmcode, reasoncode = _suggestion_source(alarm)

    out["mode"] = mode
    out["alarm"] = {
        "alarmkey": alarm.get("alarmkey") or key,
        "alarm_id": str(alarm.get("id") or ""),
        "alarmcode": alarmcode,
        "reasoncode": reasoncode,
        "restype": restype,
        "restype_name": alarm.get("restypename") or "",
        "title_en": _disp(alarm.get("alarmtitle")) or alarm.get("codename") or "",
        "title_zh": _val(alarm.get("alarmtitle")) or "",
        "code_name": alarm.get("codename") or "",
        "severity": alarm.get("perceivedseverityname") or "",
        "alarm_type": alarm.get("alarmtypename") or "",
        "ack_state": alarm.get("ackstatename") or "",
        "clear_state": alarm.get("clearstatename") or ("Uncleared" if alarm.get("clearstate") == 0 else ""),
        "raised_time": _ms_to_str(alarm.get("alarmraisedtime")),
        "changed_time": _ms_to_str(alarm.get("alarmchangedtime")),
        "server_time": _ms_to_str(alarm.get("servertime") or alarm.get("historyservertime")),
        "duration": alarm.get("durationname") or "",
        "reason": alarm.get("reasonname") or "",
        "additional_text": alarm.get("additionaltext") or "",
        "source": "UME 活动告警" if mode == "alarmkey" else "UME 历史告警",
    }

    site_cell = _build_site_cell(alarm)
    out["site_cell"] = site_cell

    sug, sug_err = fetch_suggestions(restype, alarmcode, reasoncode)
    out["suggestion"] = sug
    if sug_err:
        out["suggestion_error"] = sug_err

    if with_history:
        pos_site = site_cell.get("site_name") or site_cell.get("object_name") or ""
        if pos_site:
            h, h_err = fetch_history(pos_site, days=days, limit=limit)
            out["history"] = h
            if h_err:
                out["history_error"] = h_err
        full_pos = site_cell.get("position") or ""
        if full_pos and full_pos != pos_site and str(site_cell.get("object_type") or "").upper() == "CELL":
            hc, hc_err = fetch_history(full_pos, days=days, limit=limit)
            out["history_cell"] = hc
            if hc_err:
                out["history_cell_error"] = hc_err

    out["ok"] = True
    out["elapsed_sec"] = round(time.time() - t0, 2)
    return out
