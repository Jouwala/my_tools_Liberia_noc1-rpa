#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_xdr_client.py —— Talon XDR 信令详单查询客户端
==================================================

与 vmax_cca_client 同一主机（VMAX_HOST），共用同一套门户登录会话与 RSA 信封，
但业务接口属于 Talon XDR 框架（`/rdk/service/app/talon/xdr/...`），与 CCA
投诉接口（`/vmax/cca/view/...`）是两套互不相干的接口。

## 协议来源

2026-10-26 从浏览器完整抓包（url3.txt）复刻：

1) 业务接口全部走 **合并表** `exec_merge_query`（不是 `exec_query` 分表）：
   表单提交 `params=<RSA 密文>`，密文是 jqGrid 参数对象经 encryptLong 加密后的
   base64 —— 与 CCA 的 `_encrypted_query` 同一套，解密后是**明文 JSON**（不压缩）；
2) 列头由 `get_xdrheader_info` 返回，请求体是 JSON 双层信封
   `{"param": {"encryptedStr": ...}}` 且必须带 `X-Content-Type: application/x-vmax-s-rsa-encrypted`；
   响应本身又被包一层 `{"result": "<JSON 字符串>"}`，需二次解析；
3) 查询前需 `operationAuth`（页面级鉴权），源码见抓包的 `_xdr_2_entrance.js`。

## 关键参数陷阱（都踩过，别再试错）

- **`XDRTable` 必须为空串**：合并表查询用 `serviceName` 而非表名；填任何表名
  都返回 `3100100303 Query no data`。
- **`serviceName` 为 `"xdr_query"`**（非 CCA 下钻场景，见 `_xdr_main.js:295`）。
- **号码条件的 `type` 必须是 `"1"`**（纯文本），不能用页面组件的 `"6"`：
  用 `6` 时上游不报错也不过滤，分表回 `3100100202`、合并查询直接返回整窗
  所有用户的详单。详见 `_build_condition()` 的 docstring。
- 探测时若反复登录会触发上游
  `The maximum number of connections for the user is reached`，务必单次登录复用会话
  （本模块全程持 `VmaxCcaClient` 的锁与会话，不自行登录）。

## 已验证的 serviceType

2026-10-26 真号（231773777115，窗口 24h）实测：

| serviceType | 业务名 | 域 | 时间字段 | 保留 | 合并查询 | 列数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1100 | 5G Session | 5gsa | start_time | 72h | OK（12530 条） | 59 |
| 1300 | 信令面 | 5gsa | start_time | 72h | OK（40 条） | 88 |
| 1301 | User Plane Services | 5gsa | start_time | 72h | OK（6 条） | 88 |
| 32 | RAN 无线侧 | ran_service | btime | **24h** | OK（2651 条） | 46 |

⚠️ **保留期之外返回 `3100100202`，那是「该时段无数据」，不是故障也不是参数错**
（2026-10-26 实测：32 的近 24h 有 2577 条，换成前一天同一时刻的窗口就报这个码）。
`retention_hours` 就是为此加的：路由按它限制窗口，避免用户查到不存在的时段。

### RAN 域（32）的坑

`url3.txt` 抓包证实：RAN 类服务走 **`domain=ran_service`** 且时间字段是
**`btime`**、号码字段名是 **`"User Number"`**。三处任一用错都会被拒：

- 用 `5gsa` 域 → `3100100314`（域不匹配）
- 用 `start_time` 字段 → `3100100202`（字段不匹配）

⚠️ **`3100100202` 有两种成因，别只看这一个码下结论**：字段名用错，或查询时段
超出上游保留期。区分办法是看**同一时间窗下换类型**：若 1100 能查、32 不能，
基本就是保留期问题而非字段问题（2026-10-26 我按错误码单点推断，误判过一次）。

32 的数据含 RSRP/SINR 等无线测量列（如 `-92` / `-9.5`），是排障时看空口质量的关键。

`33/34` 列头能取到（ran_service 域，49/64 列），但查询返回 `3100100319`，
**尚未接**：`url3.txt` 只覆盖了 32。补一份 33/34 成功查询的抓包即可按同一模式接入
（大概率只差 `XDRTable` 或 `serviceName` 的取值）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaClient, VmaxCcaError, VmaxCcaUnavailable, get_client,
)
from backend.services.vmax_multi_data.vmax_report_client import encrypt_long

logger = logging.getLogger("vmax_cca.xdr")

SERVICE_PATH = "/rdk/service/app/talon/xdr/server/scripts/service/"
AUTH_HEADER = {"X-Content-Type": "application/x-vmax-s-rsa-encrypted"}

# 业务域：不同 serviceType 归属不同的 Talon 域，Referer 与时间字段名都跟着变。
# 2026-10-26 从 url3.txt 抓包确认：RAN 类（32）走 domain=ran_service 且时间字段是
# `btime`；5G 会话/信令面（1100/1300/1301）走 domain=5gsa 且时间字段是 `start_time`。
# 用错会返回 `3100100314 Query no data`（不是参数格式错，是域不匹配）。
DOMAIN_5GSA = "5gsa"
DOMAIN_RAN = "ran_service"

# 已验证可用的 serviceType 与业务名（前端下拉与文档共用这一份真值）
# 每项配置该类型所属的域、时间字段名与可回溯时长，query() 据此拼请求。
#
# retention_hours：该类型数据在上游热存储的保留时长。超出这个范围的窗口上游
# 直接回 `3100100202 Query no data`，用户会误以为「没数据/故障」，所以在入口
# 就按它限制（见 routers/vmax_xdr_query.py）。2026-10-26 实测：
#   · 32 的抓包窗口（前一天同一时刻起）已查不到，近 24h 有 2577 条 → 取 24h；
#   · 1100/1300/1301 之前能回溯数天（抓包里 10-25 的窗口当时可查），保留 72h 上限。
XDR_SERVICES: List[Dict[str, Any]] = [
    {"id": "1100", "name": "5G Session", "name_zh": "5G 会话",
     "domain": DOMAIN_5GSA, "time_field": "start_time", "retention_hours": 72},
    {"id": "1300", "name": "Signaling Plane", "name_zh": "信令面",
     "domain": DOMAIN_5GSA, "time_field": "start_time", "retention_hours": 72},
    {"id": "1301", "name": "User Plane Services", "name_zh": "用户面业务",
     "domain": DOMAIN_5GSA, "time_field": "start_time", "retention_hours": 72},
    # RAN 侧（2026-10-26 接入）：时间字段是 btime，号码字段名是 "User Number"。
    # 实测 2651 条，含 RSRP/SINR 等无线测量列，是排障时看空口质量的关键数据。
    # 热存储只留约 24 小时，窗口上限必须跟着收窄。
    {"id": "32", "name": "RAN XDR", "name_zh": "RAN 无线侧",
     "domain": DOMAIN_RAN, "time_field": "btime", "retention_hours": 24},
]
_SERVICE_BY_ID = {s["id"]: s for s in XDR_SERVICES}
_VALID_SERVICE_IDS = set(_SERVICE_BY_ID)

# 单页上限：上游分页参数，前端也会二次限制
MAX_PAGE_SIZE = 200
DEFAULT_TIMEOUT = (10, 120)      # 合并查询 1 万级记录实测要几十秒

# ---------------------------------------------------------------------------
# 分表（XDR Records）：每个 serviceType 下有哪些 XDR 表
# ---------------------------------------------------------------------------
# 权威来源是上游 `get_tabinfo`（入参 {"xdrServiceId": ..., "condition": []}），
# 2026-10-27 实测返回 {table_name, xdr_name} 数组，例如 32 域：
#   ods_lte_xdr_uu_cmcc / UU_XDR、ods_lte_xdr_x2_cmcc / X2_XDR、fact_lte_uemr / UEMR_XDR
# 这里保留一份静态兜底：上游限流或临时不可用时仍能给出下拉选项，
# 真正查询时仍会用 get_tabinfo 的结果校验表名（见 router 的白名单校验）。
XDR_TABLES_FALLBACK: Dict[str, List[Dict[str, str]]] = {
    "32": [
        {"table_name": "ods_lte_xdr_uu_cmcc", "xdr_name": "UU_XDR"},
        {"table_name": "ods_lte_xdr_x2_cmcc", "xdr_name": "X2_XDR"},
        {"table_name": "fact_lte_uemr", "xdr_name": "UEMR_XDR"},
    ],
    "33": [
        {"table_name": "ods_nr_xdr_uu_cmcc", "xdr_name": "Uu_XDR"},
        {"table_name": "ods_nr_xdr_xn_cmcc", "xdr_name": "Xn_XDR"},
        {"table_name": "fact_nr_uemr", "xdr_name": "UEMR_XDR"},
    ],
    "34": [
        {"table_name": "ods_umts_uu", "xdr_name": "UU_XDR"},
        {"table_name": "ods_umts_ho", "xdr_name": "HO_XDR"},
        {"table_name": "ods_umts_uemr", "xdr_name": "UEMR_XDR"},
    ],
    "1100": [
        {"table_name": "fact_pscp_s1mme", "xdr_name": "S1MME_XDR"},
        {"table_name": "fact_pscp_s11", "xdr_name": "S10S11_XDR"},
        {"table_name": "fact_pscp_s6a", "xdr_name": "S6A_XDR"},
        {"table_name": "fact_pscp_sgs", "xdr_name": "SGS_XDR"},
        {"table_name": "fact_pscp_gn", "xdr_name": "GN_XDR"},
    ],
    "1300": [
        {"table_name": "fact_5gsa_psup_flow", "xdr_name": "FLOW_XDR"},
        {"table_name": "fact_5gsa_psup_http", "xdr_name": "HTTP_XDR"},
        {"table_name": "fact_5gsa_psup_dns", "xdr_name": "DNS_XDR"},
        {"table_name": "fact_5gsa_psup_mms", "xdr_name": "MMS_XDR"},
        {"table_name": "fact_5gsa_psup_ftp", "xdr_name": "FTP_XDR"},
        {"table_name": "fact_5gsa_psup_email", "xdr_name": "EMAIL_XDR"},
        {"table_name": "fact_5gsa_psup_voip", "xdr_name": "SIP_XDR"},
        {"table_name": "fact_5gsa_psup_rtsp", "xdr_name": "RTSP_XDR"},
        {"table_name": "fact_5gsa_psup_https", "xdr_name": "HTTPS_XDR"},
        {"table_name": "fact_5gsa_nbup_coap", "xdr_name": "CoAP_XDR"},
    ],
    "1301": [
        {"table_name": "fact_5gsa_psup_video", "xdr_name": "VIDEO_XDR"},
        {"table_name": "fact_5gsa_psup_web", "xdr_name": "WEB_XDR"},
        {"table_name": "fact_5gsa_psup_app", "xdr_name": "APP_XDR"},
        {"table_name": "fact_5gsa_psup_ott_nslice", "xdr_name": "OTT_NSLICE_XDR"},
        {"table_name": "fact_5gsa_psup_ott_slice", "xdr_name": "OTT_SLICE_XDR"},
    ],
}

# get_tabinfo 结果缓存：表清单是静态配置，但上游接口慢（数百毫秒），
# 下拉开一次就够了；10 分钟 TTL 兼顾「现场新增表能及时看到」。
# 失败时用静态清单兜底并只缓存 60 秒 —— 上游被限流时不能让每次开页面
# 都去撞一次登录（会持续占用/触发上游的并发限制）。
_TABLE_CACHE_TTL = 600.0
_TABLE_FALLBACK_TTL = 60.0
_table_cache: Dict[str, Any] = {}          # service_type -> (expire_ts, tables)

# 列头缓存：get_xdrheader_info 慢（数百 ms），诊断一次取数会触发多次
# （每页/每源各一次）。按 (service_type, table) 缓存 10 分钟，失败不缓存。
# 2026-11-01 P0'-2：诊断 6 页 × 4 源原来最多打 24 次列头，现在每表只打 1 次。
_HEADER_CACHE_TTL = 600.0
_header_cache: Dict[str, Any] = {}        # key -> (expire_ts, cols)


class VmaxXdrError(VmaxCcaError):
    """XDR 查询失败（上游业务错误 / 报文无法解析）。"""


class VmaxXdrUnsupported(VmaxXdrError):
    """请求了尚未接入的 serviceType。"""


def _headers(c: VmaxCcaClient, json_body: bool,
             domain: str = DOMAIN_5GSA) -> Dict[str, str]:
    """Referer 必须带正确的 domain：拿 5gsa 去查 RAN 类会被拒（3100100314）。"""
    h = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "%s/rdk/app/talon/xdr/web/index.html?domain=%s" % (c.host, domain),
        "X-Requested-With": "XMLHttpRequest",
    }
    if json_body:
        h["Content-Type"] = "application/json; charset=utf-8"
        h.update(AUTH_HEADER)
    else:
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    return h


def _encrypt(obj: Any) -> str:
    return encrypt_long(json.dumps(obj, ensure_ascii=False))


class VmaxXdrClient:
    """XDR 查询客户端。会话与登录全部复用 VmaxCcaClient，不重复登录。"""

    def __init__(self, cca: Optional[VmaxCcaClient] = None):
        self.cca = cca or get_client()

    # ---------- 内部 ----------
    def _post(self, path: str, data: Dict[str, str],
              domain: str = DOMAIN_5GSA,
              retry_on_session: bool = True) -> Dict[str, Any]:
        c = self.cca
        with c._lock:                                   # noqa: SLF001 复用既有串行锁
            if not c._logged_in:
                c._login()
            resp = c.session.post(c.host + SERVICE_PATH + path, data=data,
                                  headers=_headers(c, json_body=False, domain=domain),
                                  timeout=DEFAULT_TIMEOUT, verify=False)
            if resp.status_code in (401, 403, 404, 407) and retry_on_session:
                logger.info("[vmax_xdr] 会话失效(HTTP %s)，重登后重试", resp.status_code)
                c._logged_in = False
                return self._post(path, data, domain, retry_on_session=False)
        if resp.status_code != 200:
            raise VmaxCcaUnavailable("%s -> HTTP %s: %s"
                                     % (path, resp.status_code, resp.text[:200]))
        try:
            payload = json.loads(resp.text)
        except ValueError as exc:
            raise VmaxXdrError("%s 响应不是 JSON: %s" % (path, resp.text[:200])) from exc
        return payload if isinstance(payload, dict) else {"raw": payload}

    def _post_json(self, path: str, obj: Dict[str, Any],
                   domain: str = DOMAIN_5GSA,
                   retry_on_session: bool = True) -> Dict[str, Any]:
        """JSON 信封请求（get_tabinfo / get_xdrheader_info 用这套）。

        与 `_post` 的差别只在报文形态：body 是 `{"param":{"encryptedStr":...}}`
        且必须带 `X-Content-Type: application/x-vmax-s-rsa-encrypted`。
        响应被包一层 `{"result": "<JSON 字符串>"}`，这里统一拆掉再返回。
        """
        c = self.cca
        body = json.dumps({"param": {"encryptedStr": _encrypt(obj)}})
        with c._lock:                                   # noqa: SLF001
            if not c._logged_in:
                c._login()
            resp = c.session.post(c.host + SERVICE_PATH + path, data=body,
                                  headers=_headers(c, json_body=True, domain=domain),
                                  timeout=DEFAULT_TIMEOUT, verify=False)
            if resp.status_code in (401, 403, 404, 407) and retry_on_session:
                logger.info("[vmax_xdr] 会话失效(HTTP %s)，重登后重试", resp.status_code)
                c._logged_in = False
                return self._post_json(path, obj, domain, retry_on_session=False)
        if resp.status_code != 200:
            raise VmaxCcaUnavailable("%s -> HTTP %s: %s"
                                     % (path, resp.status_code, resp.text[:200]))
        try:
            outer = json.loads(resp.text)
        except ValueError as exc:
            raise VmaxXdrError("%s 响应不是 JSON: %s" % (path, resp.text[:200])) from exc
        if isinstance(outer, dict) and isinstance(outer.get("result"), str):
            try:
                outer = json.loads(outer["result"])
            except ValueError:
                pass
        return outer if isinstance(outer, dict) else {"raw": outer}

    # ---------- 分表清单 ----------
    def tables(self, service_type: str) -> List[Dict[str, str]]:
        """serviceType -> [{table_name, xdr_name}]（get_tabinfo，进程内缓存 10 分钟）。

        上游不可用时回落到 `XDR_TABLES_FALLBACK`：下拉不至于空白，
        真查询时仍会按这份清单做表名白名单校验。
        """
        if service_type not in _VALID_SERVICE_IDS:
            raise VmaxXdrUnsupported("serviceType %s 暂未接入" % service_type)
        cached = _table_cache.get(service_type)
        if cached and time.time() < cached[0]:
            return list(cached[1])
        spec = _SERVICE_BY_ID[service_type]
        try:
            payload = self._post_json(
                "get_tabinfo", {"xdrServiceId": service_type, "condition": []},
                domain=spec["domain"])
            status = payload.get("status")
            if status != 0:
                raise VmaxXdrError(str(payload.get("errMsg") or "status=%s" % status))
            rows = []
            for item in payload.get("data") or []:
                name = str(item.get("table_name") or "").strip()
                if name:
                    rows.append({"table_name": name,
                                 "xdr_name": str(item.get("xdr_name") or name)})
            if not rows:
                raise VmaxXdrError("get_tabinfo 返回空清单")
        except (VmaxCcaError, VmaxXdrError) as exc:
            fallback = XDR_TABLES_FALLBACK.get(service_type) or []
            logger.warning("[vmax_xdr] 取 %s 表清单失败(%s)，用静态清单兜底(%d 张)",
                           service_type, exc, len(fallback))
            _table_cache[service_type] = (time.time() + _TABLE_FALLBACK_TTL, fallback)
            return list(fallback)
        _table_cache[service_type] = (time.time() + _TABLE_CACHE_TTL, rows)
        return list(rows)

    # ---------- 列头 ----------
    def fetch_headers(self, service_type: str,
                      condition: Optional[List[Dict[str, str]]] = None,
                      domain: str = DOMAIN_5GSA,
                      table: str = "") -> Dict[str, Any]:
        """取列定义 -> {"field": [...原始字段名], "header": [...显示名]}。

        两种模式（对应前端 show_table_module.js 的 realCondition）：
        - 合并表：`queryType=2` + condition（不传 table）；
        - 分表：`queryType=1` + `XDRTable=<表名>`（UEMR_XDR 等），**不带 condition**。
        响应被包在 `{"result": "<JSON 字符串>"}` 里，`_post_json` 已统一拆包。

        2026-11-01 P0'-2：进程内缓存 10 分钟。诊断一次取数原来每页/每源
        各打一次 get_xdrheader_info（6 页×4 源最多 24 次，单次数百 ms），
        现在每张表只打 1 次。key 带 domain 避免 5gsa/ran 串表。
        """
        cache_key = "%s||%s||%s" % (service_type, table, domain)
        cached = _header_cache.get(cache_key)
        if cached and time.time() < cached[0]:
            return {"field": list(cached[1]["field"]),
                    "header": list(cached[1]["header"])}
        req: Dict[str, Any] = {"serviceType": service_type,
                               "queryType": 1 if table else 2}
        if table:
            req["XDRTable"] = table
        else:
            req["condition"] = condition or []
        outer = self._post_json("get_xdrheader_info", req, domain=domain)
        inner: Any = outer
        if isinstance(outer, dict) and "result" in outer:
            inner = outer.get("result")
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    inner = None
        # 上游默认把列头包一层 result；未包装时顶层就是 {"field": [...], "header": [...]}
        if not isinstance(inner, dict) and isinstance(outer, dict) and "field" in outer:
            inner = outer
        if not isinstance(inner, dict):
            raise VmaxXdrError("列头响应结构异常: %s" % str(outer)[:200])
        out = {"field": list(inner.get("field") or []),
               "header": list(inner.get("header") or [])}
        _header_cache[cache_key] = (time.time() + _HEADER_CACHE_TTL, out)
        return {"field": list(out["field"]), "header": list(out["header"])}

    # ---------- 查询 ----------
    def query(self, msisdn: str, service_type: str,
              starttime: str, endtime: str,
              page: int = 1, page_size: int = 20,
              imsi: Optional[str] = None) -> Dict[str, Any]:
        """按号码 + 时间窗查合并 XDR。

        starttime/endtime 必须是 "YYYY-MM-DD HH:MM:SS.000" 全格式（含毫秒），
        与 CCA 的 "YYYY-MM-DD HH:MM:SS" 不同 —— 上游按毫秒边界切分区。
        """
        if service_type not in _VALID_SERVICE_IDS:
            raise VmaxXdrUnsupported(
                "serviceType %s 暂未接入；当前支持 %s"
                % (service_type, ", ".join(sorted(_VALID_SERVICE_IDS))))
        spec = _SERVICE_BY_ID[service_type]
        domain = spec["domain"]
        page = max(1, int(page or 1))
        page_size = min(max(1, int(page_size or 20)), MAX_PAGE_SIZE)

        condition = _build_condition(spec, service_type, msisdn, starttime, endtime, imsi=imsi)
        # 参数结构照抄 _xdr_merge.js::initCommonConditionProcessor
        # （XDRTable 必为空串、serviceName 固定 xdr_query，见模块头注释）
        param = {
            "paging": {"currentPage": page, "pageSize": page_size},
            "orderBy": {"direction": "", "field": ""},
            "export": 0,
            "sqlMaxNum": "",
            "XDRTable": "",
            "serviceName": "xdr_query",
            "userCity": "",
            "loginfo": {"isRecord": 0, "comment": "", "jumpSigIsRecord": 0},
            "colModel": [],
            "queryReason": "",
            "appSessionId": "",
            "sourcePath": "",
            "condition": condition,
            "isFirst": page == 1,
            "timestamp": "",
            "filterFieldMap": {},
            "exportSensitive": "",
            "senoprename": "xdr_userinfo_query",
            "endTime": "",
        }
        payload = self._post("exec_merge_query", {
            "_search": "false", "nd": "1", "rows": str(page_size),
            "page": str(page), "sidx": "", "sord": "", "params": _encrypt(param)},
            domain=domain)

        # status: 0=成功, 1=业务失败（errMsg 带上游说明）
        status = payload.get("status")
        if status != 0:
            msg = str(payload.get("errMsg") or payload.get("msg") or "")
            # 只抛上游原文（含 operation code），由 router 决定怎么给用户看
            raise VmaxXdrError(msg or "上游返回 status=%s" % status)

        rows = payload.get("rows")
        cols = self.fetch_headers(service_type, condition, domain=domain)
        return {
            "msisdn": msisdn,
            "service_type": service_type,
            "window": {"starttime": starttime, "endtime": endtime},
            "page": payload.get("page", page),
            "page_size": page_size,
            "total_pages": payload.get("total", 0),
            "records": int(payload.get("records") or 0),
            "field": cols["field"],
            "header": cols["header"],
            "rows": [_row_to_dict(r, cols) for r in (rows or []) if isinstance(r, dict)],
        }

    # ---------- 分表查询（XDR Records：UEMR_XDR 等） ----------
    def query_table(self, msisdn: str, service_type: str, table: str,
                    starttime: str, endtime: str,
                    page: int = 1, page_size: int = 20,
                    imsi: Optional[str] = None,
                    columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """按号码 + 时间窗查**单张 XDR 表**（UEMR_XDR / UU_XDR / X2_XDR…）。

        与 `query()`（合并表 `exec_merge_query`）的差别照抄前端
        show_table_module.js::initCommonConditionProcessor：
        - 走 `exec_query`，`XDRTable = 表名`，**不传 `serviceName`**；
        - `colModel` 必须是该表的列名数组（先取 get_xdrheader_info）。
        `table` 必须来自 `tables(service_type)` 的清单 —— 上游把表名拼进
        SQL 的 FROM，任意字符串有注入风险，白名单校验由本方法与 router 双层做。

        `imsi`：RAN 域（32）必须传，否则 `$msisdn` 为空串查不到任何记录
        （见 `_build_condition` 的 2026-10-31 说明）。

        `columns`：P0'-2 列裁剪 —— 只取诊断真正要的列，大幅缩小 payload
        （88 列全取 × 1200 行 ≈ 数 MB）。传 None 则取全列（兼容旧调用）。
        实现：先取表头做白名单交集，交集为空则回退全列（避免上游拒空 colModel）。
        """
        if service_type not in _VALID_SERVICE_IDS:
            raise VmaxXdrUnsupported(
                "serviceType %s 暂未接入；当前支持 %s"
                % (service_type, ", ".join(sorted(_VALID_SERVICE_IDS))))
        spec = _SERVICE_BY_ID[service_type]
        domain = spec["domain"]
        page = max(1, int(page or 1))
        page_size = min(max(1, int(page_size or 20)), MAX_PAGE_SIZE)

        want = str(table or "").strip().lower()
        matched = next((t for t in self.tables(service_type)
                        if t["table_name"].lower() == want
                        or t["xdr_name"].lower() == want), None)
        if matched is None:
            raise VmaxXdrUnsupported(
                "表 %s 不属于 serviceType %s；可选：%s"
                % (table, service_type,
                   ", ".join(t["xdr_name"] for t in self.tables(service_type))))
        table_name = matched["table_name"]

        condition = _build_condition(spec, service_type, msisdn, starttime, endtime, imsi=imsi)
        cols = self.fetch_headers(service_type, domain=domain, table=table_name)
        if columns:
            want_set = {str(c) for c in columns}
            picked = [f for f in cols["field"] if f in want_set]
            col_model = picked or list(cols["field"])
        else:
            col_model = list(cols["field"])
        param = {
            "paging": {"currentPage": page, "pageSize": page_size},
            "orderBy": {"direction": "", "field": ""},
            "export": 0,
            "XDRTable": table_name,
            "userCity": "",
            "isFirst": page == 1,
            "sqlMaxNum": "",
            "loginfo": {"isRecord": 0, "comment": "", "jumpSigIsRecord": 0},
            "colModel": col_model,
            "queryReason": "",
            "appSessionId": "",
            "sourcePath": "",
            "condition": condition,
            "timestamp": "",
            "filterFieldMap": {},
            "exportSensitive": "",
            "senoprename": "xdr_userinfo_query",
            "endTime": "",
        }
        payload = self._post("exec_query", {
            "_search": "false", "nd": "1", "rows": str(page_size),
            "page": str(page), "sidx": "", "sord": "", "params": _encrypt(param)},
            domain=domain)

        status = payload.get("status")
        if status != 0:
            msg = str(payload.get("errMsg") or payload.get("msg") or "")
            # 3100100202 = 该窗口无记录（也可能是超出保留期）。对分表查询这不是故障：
            # 单张表本来就可能整段没有数据（如某号码两小时没上报 MR），
            # 当成 0 条正常返回，前端显示友好空态，而不是红色报错。
            if "3100100202" in msg:
                cols = self.fetch_headers(service_type, domain=domain, table=table_name)
                return {
                    "msisdn": msisdn, "service_type": service_type,
                    "table": table_name, "table_label": matched["xdr_name"],
                    "window": {"starttime": starttime, "endtime": endtime},
                    "page": page, "page_size": page_size, "total_pages": 0,
                    "records": 0, "field": cols["field"], "header": cols["header"],
                    "rows": [], "empty_reason": "no_data",
                }
            raise VmaxXdrError(msg or "上游返回 status=%s" % status)

        rows = payload.get("rows")
        # P0'-2：裁列时返回的 cell 数组长度 == colModel 长度，不是全表列数。
        # 必须按实际下发的 colModel 绑字段，否则「按表头顺序绑」会把值错位
        # （如第 3 个值本是 service，却被绑到全表的第 3 列名上）。
        # 这里用 colModel 重建 field/header 子集返回，保持「field[i] 对 rows[i]」。
        if col_model != list(cols["field"]):
            hdr_by_field = dict(zip(cols["field"], cols["header"]))
            use_cols = {"field": list(col_model),
                        "header": [hdr_by_field.get(f, f) for f in col_model]}
        else:
            use_cols = cols
        return {
            "msisdn": msisdn,
            "service_type": service_type,
            "table": table_name,
            "table_label": matched["xdr_name"],
            "window": {"starttime": starttime, "endtime": endtime},
            "page": payload.get("page", page),
            "page_size": page_size,
            "total_pages": payload.get("total", 0),
            "records": int(payload.get("records") or 0),
            "field": use_cols["field"],
            "header": use_cols["header"],
            "rows": [_row_to_dict(r, use_cols) for r in (rows or []) if isinstance(r, dict)],
        }


def _build_condition(spec: Dict[str, Any], service_type: str, msisdn: str,
                     starttime: str, endtime: str,
                     imsi: Optional[str] = None) -> List[Dict[str, str]]:
    """查询条件数组（合并表与分表共用一份，字段名随域变化）。

    ⚠ 号码条件必须用 `type="1"`（纯文本输入），**不能照抄页面组件的
    `type="6"`（SELECT_INPUT 下拉+输入组合）**。2026-10-27 实测
    （1301 / fact_5gsa_psup_video，窗口内确有该号码的记录）：

    - `type=6` + `msisdn=231777550122` → `3100100202`（明明有数据却查不到）；
    - `type=1` + 同一条件 → `status=0`，命中该号码的记录。

    合并查询上 `type=6` 更危险：它**完全不按号码过滤**——1301 的 2.5 小时窗口
    真号返回 3 条、伪造号码同样 3 条；1100 的 1 小时窗口真号与伪造号都是
    1122 条。也就是说会把别人的详单当成当前用户的结果展示（越权风险）。

    RAN 域的表没有 `msisdn` 列，号码列是隐藏的 `$msisdn`；且 UEMR/UU 记录
    实测 `$msisdn` 为空串（只带 IMSI），所以按 `$msisdn` 过滤会如实返回空，
    而不是像以前那样忽略条件、把整窗数据全吐出来。

    【2026-10-31 修】RAN 域**改按 IMSI 查**（P0 bug）：
    实测 `$msisdn` 列在该号码的 101 条 UEMR 记录里**全是空串**，
    只带 IMSI。也就是说「按号码查无线质量」这条路从来就没通过 ——
    界面上表现为「该时段无驻留小区记录」，被当成「用户没数据」，
    实际是查询条件错。改用 `{"field":"imsi","value":<imsi>,"type":"1"}`
    后同一窗口 0 条 → 101 条（见 docs/VMAX_DIAGNOSIS_REDESIGN.md §5.1）。

    `imsi` 由调用方先用 1300/1100 解析出来传进来；拿不到时**不静默**，
    在条件里仍带 `$msisdn`（保持旧行为，返回空），并由上层把
    「无 IMSI 映射，无法查无线质量」写进结论 —— 不能让「查不到」看起来像「正常」。
    """
    if spec["domain"] == DOMAIN_RAN:
        if imsi:
            return [
                {"field": spec["time_field"], "value": "%s,%s" % (starttime, endtime), "type": "4"},
                {"field": "serviceType", "value": service_type, "type": "-1"},
                {"field": "dbType", "value": "", "type": ""},
                {"field": "imsi", "value": str(imsi), "type": "1", "name": "IMSI"},
            ]
        number_field, number_name = "$msisdn", "User Number"
    else:
        number_field, number_name = "msisdn", "MSISDN"
    return [
        {"field": spec["time_field"], "value": "%s,%s" % (starttime, endtime), "type": "4"},
        {"field": "serviceType", "value": service_type, "type": "-1"},
        {"field": "dbType", "value": "", "type": ""},
        {"field": number_field, "value": msisdn, "type": "1", "name": number_name},
    ]


def _row_to_dict(row: Dict[str, Any], cols: Dict[str, List[str]]) -> Dict[str, str]:
    """上游每行是 {"id":0,"cell":[...]} 的定长数组，按列头顺序绑成字段名 -> 值。

    长度对不上时保留已对齐部分（上游加列会先表现在 header 里），
    多出的值丢弃，不让整行丢失。
    """
    cells = row.get("cell")
    if not isinstance(cells, list):
        return {}
    out: Dict[str, str] = {}
    for idx, name in enumerate(cols["field"]):
        if idx >= len(cells):
            break
        # "$xxx" 是隐藏的 ID 列（见 _xdr_ctrl.js 对 $ 前缀的处理），保留原值
        out[name] = "" if cells[idx] is None else str(cells[idx])
    return out


_default_xdr_client: Optional[VmaxXdrClient] = None


def get_xdr_client() -> VmaxXdrClient:
    """模块级单例：复用 CCA 的门户会话（上游按用户限并发，不做查询后 logout）。"""
    global _default_xdr_client
    if _default_xdr_client is None:
        _default_xdr_client = VmaxXdrClient()
    return _default_xdr_client
