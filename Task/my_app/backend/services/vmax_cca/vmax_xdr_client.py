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
- 探测时若反复登录会触发上游
  `The maximum number of connections for the user is reached`，务必单次登录复用会话
  （本模块全程持 `VmaxCcaClient` 的锁与会话，不自行登录）。

## 已验证的 serviceType

2026-10-26 真号（231773777115，窗口 24h）实测：

| serviceType | 业务名 | 域 | 时间字段 | 合并查询 | 列头字段数 |
| --- | --- | --- | --- | --- | --- |
| 1100 | 5G Session | 5gsa | start_time | OK（12530 条） | 59 |
| 1300 | 信令面 | 5gsa | start_time | OK（40 条） | 88 |
| 1301 | User Plane Services | 5gsa | start_time | OK（6 条） | 88 |
| 32 | RAN 无线侧 | ran_service | btime | OK（2651 条，2026-10-26） | 46 |

### RAN 域（32）的坑

`url3.txt` 抓包证实：RAN 类服务走 **`domain=ran_service`** 且时间字段是
**`btime`**、号码字段名是 **`"User Number"`**。三处任一用错都会被拒：

- 用 `5gsa` 域 → `3100100314 Query no data`
- 用 `start_time` 字段 → `3100100202`
- 这两条错误码**不是**「数据为空」，是域/字段不匹配，别当成没数据。

32 的数据含 RSRP/SINR 等无线测量列（如 `-92` / `-9.5`），是排障时看空口质量的关键。

`33/34` 列头能取到（ran_service 域，49/64 列），但查询返回 `3100100319`，
**尚未接**：`url3.txt` 只覆盖了 32。补一份 33/34 成功查询的抓包即可按同一模式接入
（大概率只差 `XDRTable` 或 `serviceName` 的取值）。
"""
from __future__ import annotations

import json
import logging
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
# 每项配置该类型所属的域与时间字段名，query() 据此拼请求。
XDR_SERVICES: List[Dict[str, str]] = [
    {"id": "1100", "name": "5G Session", "name_zh": "5G 会话",
     "domain": DOMAIN_5GSA, "time_field": "start_time"},
    {"id": "1300", "name": "Signaling Plane", "name_zh": "信令面",
     "domain": DOMAIN_5GSA, "time_field": "start_time"},
    {"id": "1301", "name": "User Plane Services", "name_zh": "用户面业务",
     "domain": DOMAIN_5GSA, "time_field": "start_time"},
    # RAN 侧（2026-10-26 接入）：时间字段是 btime，号码字段名是 "User Number"。
    # 实测 2651 条，含 RSRP/SINR 等无线测量列，是排障时看空口质量的关键数据。
    {"id": "32", "name": "RAN XDR", "name_zh": "RAN 无线侧",
     "domain": DOMAIN_RAN, "time_field": "btime"},
]
_SERVICE_BY_ID = {s["id"]: s for s in XDR_SERVICES}
_VALID_SERVICE_IDS = set(_SERVICE_BY_ID)

# 单页上限：上游分页参数，前端也会二次限制
MAX_PAGE_SIZE = 200
DEFAULT_TIMEOUT = (10, 120)      # 合并查询 1 万级记录实测要几十秒


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

    # ---------- 列头 ----------
    def fetch_headers(self, service_type: str,
                      condition: List[Dict[str, str]],
                      domain: str = DOMAIN_5GSA) -> Dict[str, Any]:
        """取列定义 -> {"field": [...原始字段名], "header": [...显示名]}。

        响应被包在 `{"result": "<JSON 字符串>"}` 里，需要二次解析
        （2026-10-26 实测：直接取顶层 field 恒为空）。
        """
        c = self.cca
        body = json.dumps({"param": {"encryptedStr": _encrypt({
            "serviceType": service_type, "queryType": 2, "condition": condition})}})
        with c._lock:                                   # noqa: SLF001
            if not c._logged_in:
                c._login()
            resp = c.session.post(c.host + SERVICE_PATH + "get_xdrheader_info",
                                  data=body,
                                  headers=_headers(c, json_body=True, domain=domain),
                                  timeout=DEFAULT_TIMEOUT, verify=False)
        if resp.status_code != 200:
            raise VmaxCcaUnavailable("get_xdrheader_info -> HTTP %s" % resp.status_code)
        try:
            outer = json.loads(resp.text)
        except ValueError as exc:
            raise VmaxXdrError("列头响应不是 JSON: %s" % resp.text[:200]) from exc
        inner = outer.get("result") if isinstance(outer, dict) else None
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
        return {"field": list(inner.get("field") or []),
                "header": list(inner.get("header") or [])}

    # ---------- 查询 ----------
    def query(self, msisdn: str, service_type: str,
              starttime: str, endtime: str,
              page: int = 1, page_size: int = 20) -> Dict[str, Any]:
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

        # 时间字段名与号码字段名随域变化（RAN 侧是 btime + "User Number"），
        # 用错会返回 3100100314 —— 那是域/字段不匹配，不是数据为空。
        condition = [
            {"field": spec["time_field"], "value": "%s,%s" % (starttime, endtime), "type": "4"},
            {"field": "serviceType", "value": service_type, "type": "-1"},
            {"field": "dbType", "value": "", "type": ""},
            {"field": "msisdn", "value": msisdn, "type": "6",
             "name": "User Number" if domain == DOMAIN_RAN else "MSISDN"},
        ]
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
            raise VmaxXdrError("XDR 查询失败: %s" % (msg or "上游返回 status=%s" % status))

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
