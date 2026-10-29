# -*- coding: utf-8 -*-
"""eFlow 派单/站点解析 HTTP 客户端（Fiber Break 与 5G 站点告警共用）。

只做确定性的事：查实时告警、解析用户组 groupId、解析站点、调派单接口。
会话与重试**全部复用** `eflow_api_client`（`ensure_login` / `_http_request` /
`get_session_headers`），本模块不另建登录链路，避免出现第二套会话。

## 关键接口（来源：`backend/services/eflow_fiber/url_test.txt`）

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 用户组（拿 groupId） | GET | `/api/fms-assign-svr/v1/wo/userGroupList` |
| 派单（建 TT） | POST | `/api/alarm-assign/manual/assign` |
| 站点搜索（ME→站点 ID/名） | POST | `/api/cmdb/v1/data/search/Site` |
| 实时告警 | POST | `/api/fm-active/v1/activealarms/table` |

## Fiber 派单为什么必须带 site + sitename（2026-10-26 实测）

RAN 告警的 `site` 字段本身就是数字站点 ID（如 `4344`）、`sitename` 已绑定；
而 Fiber（TRM/IPRAN）告警的 `site` 是 **ME 名**（如 `6120HA_zardun_UPE128`）、
`sitename` 为 `--`。用 ME 名直接派单，接口返回 `status:true` 但 **TT 不生成**
（`ttid` 仍为 empty，`ttstatus` 停在 2）。必须在 payload 里把 `site` 换成
**数字站点 ID**、并补 `sitename` 站点名，TT 才会真正建出来
（实测 `site=3462` + `sitename=Zardun` → `ttid=TT202610260085`）。

## 5G 站点告警的字段形态（2026-10-28 实测，与 Fiber 不同）

5G（`zte.ran.gnodeb`）告警的 `site` **本来就是数字站点 ID**、`sitename` 已是
站点名（如 `4162` / `Liscr`），**不需要**从 ME 名解析。但它有两个 Fiber 没有的
特点，必须专门处理：

* **一站多小区**：一个 gNB 的多个小区各自产生一条告警（实测同站多个 cell
  同时升起 `200201001`），同一故障会派出一堆重复单。
* **码量大**：5G 告警码是 9 位（`200201001`），一条 DU 退服会带出**多个不同码**
  （实测同站同时有 `200201001` DU cell out-of-service 与 `200201009` X2 link
  is broken）。
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services import eflow_api_client as api
from backend.services.eflow_assign import eflow_site as _site
from backend.services.eflow_assign.assign_config import norm_code

logger = logging.getLogger("eflow_assign")

ASSIGN_API_PATH = "/api/alarm-assign/manual/assign"
GROUP_API_PATH = "/api/fms-assign-svr/v1/wo/userGroupList"
SITE_SEARCH_API_PATH = _site.SITE_SEARCH_API_PATH
ACTIVE_ALARM_API_PATH = "/api/fm-active/v1/activealarms/table"


def _referer() -> str:
    return f"https://{api.HOST}:{api.PORT}/iui/fm/angularFm/dist/index.html"


def _headers() -> str:
    """构造请求头（Cookie / forgerydefense 每次实时取，避免拿到过期会话）。

    与 `eflow_api_client._headers_extra` 同构；独立写一份是为了显式带上
    `Content-Type: application/json`（url_test.txt 的派单/查询都用它）。
    """
    cookie, tok = api.get_session_headers()
    return (
        f"Cookie: {cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {_referer()}\r\n"
        f"forgerydefense: {tok}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{api.HOST}:{api.PORT}\r\n"
    )


def _json_or_none(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def _iso_now() -> str:
    """eFlow 查询用的 ISO 时间戳（UTC，毫秒精度，带 Z）。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _val(v: Any) -> Any:
    """eFlow 告警字段是 {value, displayname, ...} 对象；统一取 value。"""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


# ==========================================================
# 用户组
# ==========================================================
def fetch_user_groups() -> Dict[str, Dict[str, Any]]:
    """返回 {组名: {id, name, acceptType}}。失败返回空 dict 并记日志。"""
    api.ensure_login()
    status, hdrs, raw, body = api._http_request(
        "GET", GROUP_API_PATH, headers_extra=_headers())
    data = _json_or_none(body)
    groups: Dict[str, Dict[str, Any]] = {}
    if not isinstance(data, dict):
        logger.warning("[Assign] userGroupList 返回非 JSON: %s", status)
        return groups
    try:
        lst = data["entity"]["userGroupList"]["data"]
    except (KeyError, TypeError):
        logger.warning("[Assign] userGroupList 结构异常: %s", list(data.keys()))
        return groups
    for g in lst or []:
        name = str(g.get("name") or "").strip()
        if name:
            groups[name] = g
    return groups


def resolve_group(name: str) -> Optional[Dict[str, Any]]:
    """按名解析目标用户组；找不到返回 None（调用方据此报错，不静默换组）。"""
    groups = fetch_user_groups()
    if not groups:
        return None
    if name in groups:
        return groups[name]
    # 大小写不敏感兜底（页面手填可能大小写不一致）
    low = name.strip().lower()
    for gname, g in groups.items():
        if gname.lower() == low:
            return g
    return None


# ==========================================================
# 站点解析（已拆到 eflow_site.py，这里只做再导出）
# ==========================================================
from backend.services.eflow_assign.eflow_site import (  # noqa: E402,F401
    SiteIndex,
    _norm_name,
    _only_digit_suffix_diff,
    _pick,
    _vowel_swap_only,
    resolve_site,
    site_name_from_me,
)


# ==========================================================
# 实时告警查询
# ==========================================================
def fetch_active_alarms() -> List[Dict[str, Any]]:
    """拉全量实时告警（未清除、maintainstatus=0），返回规范化 rows。

    不做告警码过滤 —— 让调用方同时能拿到目标码与关联码（99933）做关联判定。
    分页上限 500 条/页，最多 20 页（1 万条），足够覆盖当前量级（实测约 6752）。
    """
    api.ensure_login()
    all_rows: List[Dict[str, Any]] = []
    page = 1
    page_size = 500
    while page <= 20:
        payload = {
            "timestamp": _iso_now(),
            "condition": {
                "alarmcodefiltermode": 0,
                "extensionconds": {"maintainstatus": {"filtertype": 1, "valuelist": ["0"]}},
                "sortinfo": {"sortdirection": 0, "sortfield": "servertime",
                             "combinesortinfos": []},
                "timezonetype": 0, "querymetype": 2, "id": -1, "visibles": [1],
            },
            "pagesize": page_size, "page": page,
            "queryid": "T" + uuid.uuid4().hex,
            "activeTabId": "fm-active_ALARM_MONITOR",
            "manual": False,
        }
        status, hdrs, raw, body = api._http_request(
            "POST", ACTIVE_ALARM_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        data = _json_or_none(body)
        if data is None:
            logger.warning("[Assign] 实时告警返回非 JSON: %s", status)
            break
        rows = api.parse_response(data, label="ActiveAlarms")
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    logger.info("[Assign] 实时告警拉取 %d 条", len(all_rows))
    return all_rows


def fetch_active_alarms_by_codes(codes: List[str],
                                  restypes: Optional[List[str]] = None,
                                  ) -> List[Dict[str, Any]]:
    """**按告警码**在服务端过滤拉实时告警（2026-10-28 新增，5G 派单用）。

    ## 为什么需要服务端过滤（实测数据）

    全量拉取实测 **6752 条 / 4.4 秒**；而按码过滤后只回 **21 条 / 0.1 秒**。
    5G 告警码是 9 位且种类多，全量拉进来每轮都要在内存里过一遍，且 5G 派单
    只需要目标码 + 关联码。

    ## ⚠ `alarmcodeconds` **必须带 `restype`**（实测踩过）

    实测（2026-10-28）：
      * `alarmcodeconds` 只给 `alarmcode`（不带 restype）→ HTTP **499**、0 条；
      * 加上 `restype` → HTTP 200、正常返回。

    且 `restype` 与 `alarmcode` 是**笛卡尔积**语义：给 3 个 restype × 5 个码，
    eFlow 返回的是「这 15 个组合里存在的告警」。

    ## ⚠ `restype` 猜错 = 该码**永远不触发**（静默失效风险）

    目标 5G 码里有 4 个（200201018/41/43/60）当前**没有实例**，无法实测它们的
    restype。实测存在的 `200201001` 的 restype 是 `zte.ran.gnodeb`。
    若某个码的真实 restype 与配置不符，**服务端过滤会把它整个滤掉**，
    任务永远收不到它 —— 且没有任何报错。

    故本函数**始终附带全量兜底**：调用方另有一个「全量兜底拉取」开关
    （`fetch_active_alarms`）用于彻底排除该风险（见 5G 服务的实现）。

    Args:
        codes: 要过滤的告警码（字符串形式，如 `["200201001"]`）。
        restypes: 参与组合的 restype 列表；None/空表示不按 restype 过滤
                  （⚠ 实测 eFlow 会返回 499，故调用方必须显式给值）。
    """
    api.ensure_login()
    cond_list: List[Dict[str, Any]] = []
    rts = list(restypes or [])
    for rt in rts:
        for c in codes:
            cond_list.append({"restype": rt, "alarmcode": c})
    if not cond_list:
        return []

    all_rows: List[Dict[str, Any]] = []
    page = 1
    page_size = 500
    while page <= 20:
        payload = {
            "timestamp": _iso_now(),
            "condition": {
                "alarmcodeconds": cond_list,
                "alarmcodefiltermode": 0,
                "extensionconds": {"maintainstatus": {"filtertype": 1, "valuelist": ["0"]}},
                "sortinfo": {"sortdirection": 0, "sortfield": "servertime",
                             "combinesortinfos": []},
                "timezonetype": 0, "querymetype": 2, "id": -1, "visibles": [1],
            },
            "pagesize": page_size, "page": page,
            "queryid": "T" + uuid.uuid4().hex,
            "activeTabId": "fm-active_ALARM_MONITOR",
            "manual": False,
        }
        status, hdrs, raw, body = api._http_request(
            "POST", ACTIVE_ALARM_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        data = _json_or_none(body)
        if data is None:
            logger.warning("[Assign] 按码过滤的实时告警返回非 JSON: %s", status)
            break
        rows = api.parse_response(data, label="ActiveAlarmsByCode")
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    logger.info("[Assign] 按码过滤拉取 %d 条（codes=%s restypes=%s）",
                len(all_rows), ",".join(codes), ",".join(rts))
    return all_rows


def fetch_alarm_by_id(ident: str) -> List[Dict[str, Any]]:
    """按 `id` / `alarmkey` 单查实时告警（派单后回查 ttid 用的快路径）。

    ⚠ 这是**可选优化**，不是必需：回查逻辑必须能在全量拉取下同样工作
    （`secondarycondition` 若被 eFlow 侧忽略，会退化成「返回全量」，
    此时由调用方按 id 自行过滤）。故此处**即使返回多条也不报错**，
    只负责把候选行交回去。

    实测目的：Fiber 现实现回查靠全量重拉（6752 条 / 4.4s），单条告警最多
    重查 3 次 ≈ 白烧 13s；按 id 单查若生效可降到 0.1s 级别。
    """
    ident = str(ident or "").strip()
    if not ident:
        return []
    api.ensure_login()
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
        "secondarycondition": {"id": ident},
        "queryid": "T" + uuid.uuid4().hex,
        "activeTabId": "fm-active_ALARM_MONITOR",
        "manual": False,
    }
    try:
        status, hdrs, raw, body = api._http_request(
            "POST", ACTIVE_ALARM_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        data = _json_or_none(body)
        if data is None:
            logger.warning("[Assign] 单查告警 %s 返回非 JSON: %s", ident, status)
            return []
        rows = api.parse_response(data, label="ActiveAlarmById")
        logger.info("[Assign] 单查告警 %s → %d 条", ident, len(rows))
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning("[Assign] 单查告警 %s 异常: %s", ident, e)
        return []


# ==========================================================
# 派单
# ==========================================================
def build_assign_payload(alarm: Dict[str, Any], group: Dict[str, Any],
                         site_id: str, site_name: str) -> Dict[str, Any]:
    """按 url_test.txt 的捕获结构组装派单 payload。

    与捕获的差异只有两处（Fiber 必需，见模块 docstring）：
      * `site` 用解析出的数字站点 ID，不是 ME 名；
      * 额外补 `sitename`，让 eFlow TT 引擎能绑定站点、真正建出 TT。
    """
    a = alarm
    occ_ms = _val(a.get("alarmraisedtime")) or _val(a.get("servertime")) or 0
    srv_ms = _val(a.get("servertime")) or occ_ms

    def _fmt(ms: Any) -> str:
        try:
            return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return ""

    codename = str(_val(a.get("codename")) or _val(a.get("alarm_title")) or "").strip()
    alarmcode = _val(a.get("alarmcode"))
    data_row = {
        "alarmkey": _val(a.get("alarmkey")),
        "assignedtime": int(datetime.now().timestamp() * 1000),
        "id": _val(a.get("id")),
        "aid": str(_val(a.get("aid")) or ""),
        "alarmcode": f"{codename}({norm_code(alarmcode)})",
        "occurtime": _fmt(occ_ms),
        "site": site_id,
        "sitename": site_name,
        "perceivedseverity": _val(a.get("perceivedseverity")),
        "codename": codename,
        "me": _val(a.get("me")),
        "nbiid": str(_val(a.get("nbiid")) or ""),
        "position": _val(a.get("position")),
        "additionaltext": _val(a.get("additionaltext")) or "",
        "servertime": _fmt(srv_ms),
        "alarmtype": _val(a.get("alarmtype")),
        "plxTableDataIndex": 0,
        "plxTableDataKey": "key0",
    }
    return {
        "assignedType": 1,
        "alarmMsgType": 1,
        "data": [data_row],
        "assigneduser": api.USERNAME or "admin",
        "assigninformation": "",
        "groupId": group.get("id"),
        "autotag": "manual",
        "acceptType": group.get("acceptType", "FO"),
        "disableInput": codename,
    }


def assign_alarm(alarm: Dict[str, Any], group: Dict[str, Any],
                 site_id: str, site_name: str) -> Dict[str, Any]:
    """调用派单接口。返回 {"ok", "status", "message", "payload", "error"}。

    ⚠ 接口返回 `status:true` **不代表 TT 一定建出来**：Fiber 少传 site/sitename
    时同样返回 true 但 ttid 为空（见模块 docstring 的实测）。真正的成功判定由
    调用方回查 `ttid` 完成，本函数只如实报告接口回执。
    """
    payload = build_assign_payload(alarm, group, site_id, site_name)
    result: Dict[str, Any] = {"ok": False, "status": "", "message": "",
                              "payload": payload, "error": None}
    try:
        api.ensure_login()
        status, hdrs, raw, body = api._http_request(
            "POST", ASSIGN_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        result["status"] = str(status)
        data = _json_or_none(body) or {}
        result["message"] = str(data.get("message") or "")
        result["ok"] = bool(data.get("status")) and "200" in str(status)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        logger.exception("[Assign] 派单接口异常")
    return result
