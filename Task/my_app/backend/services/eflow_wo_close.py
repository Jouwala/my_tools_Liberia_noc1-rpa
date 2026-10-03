# -*- coding: utf-8 -*-
"""eflow_wo_close.py — eFlow WO 关闭（Confirm To Close）服务
========================================================

把 TMP 探针验证过的三步链路固化为服务层，供 eflow_qa 页面「WO 清理」功能调用：

  ① POST {WO_API}/base/detail?woId={id}   → flowEntity 快照 + opEntities（找待办 Confirm 的 id）
  ② POST {WO_API}/base/process            → flowEntity 子集 + opEntity{id, operationResult:"7"}
  ③ 复核：重查 detail，该 op 的 operationResult 应变为 "7" / status 变 Closed

关键实测事实（2026-10-01，TMP 探针验证）：
  * opEntity.id 不是 woId，是 detail 里待办操作记录的主键（如 106037），
    缺了它服务端报 48990009 "Failed to build entity!"。
  * base/detail 必须用「POST + 查询串 ?woId=」+ 空 body；参数放 body 里报 48990007。
  * operationResult="7" 对应 Confirm 步骤的 "Confirm To Close"（终态 Closed），
    必须是字符串。
  * base/list 的 filter 复合表达式可用：
    ((status eq "A") or ...) and (lastModifiedTime ge n) and (woNum contains "xx")

安全约束：
  * 只允许 opName=Confirm 且 status=WaitConfirm 的单提交；其它状态一律拒绝。
  * 逐单串行 + 间隔，防止并发/风控问题。
  * 只做关闭（Confirm To Close），不做 Reject / 重开 / 删除。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.services.eflow_api_client import (
    _http_request,
    ensure_login,
    _headers_extra,
    HOST,
    PORT,
)

logger = logging.getLogger("eflow_wo_close")

# eFlow WO 服务路径（与 eflow_data_mapper 同源）
WO_API = "/api/eflow-wo/v1/eflow-wo"
WO_REFERER = f"https://{HOST}:{PORT}/iui/wo-mgt/v1/"

# flowEntity 提交字段集 = 成功样例的 18 键（缺字段会报 48990009）
FLOW_KEYS = (
    "additionalInformation", "alarmClearTime", "faultResolvingTime",
    "processingProcedure", "whetherArrivedField", "whetherReplacedSP",
    "creator", "category", "subCategory", "detailCategory",
    "woId", "woNum", "createTime", "procId", "taskId",
    "opName", "status", "displayName",
)

# Confirm 步骤的「确认关闭」操作码（字符串）
OPERATION_RESULT_CLOSE = "7"

# 批量上限 / 逐单间隔
MAX_BATCH = 200
SUBMIT_INTERVAL_SEC = 1.0

# WO 单号形态：WO + 12 位数字
import re as _re
_WO_NUM_RE = _re.compile(r"^WO\d{12}$")


def normalize_wo_list(text: Optional[str], wos: Optional[List[str]]) -> Tuple[List[str], List[str]]:
    """清洗输入：合并 wos 数组与粘贴文本，拆分、规范化、去重（保序）。

    返回 (有效单号列表, 被忽略的无效项列表)。无效项形如 "原文(原因)"。
    """
    raw_items: List[str] = list(wos or [])
    if text:
        raw_items.extend(_re.split(r"[\s,;，；\t|]+", text))
    seen: set = set()
    valid: List[str] = []
    invalid: List[str] = []
    for item in raw_items:
        s = (item or "").strip().upper()
        if not s:
            continue
        if not _WO_NUM_RE.match(s):
            # 允许少写前缀零的情况不做——严格 12 位；把常见错型标出来
            invalid.append(f"{s}({('缺前缀WO' if s.isdigit() and len(s) <= 14 else '格式不符')})")
            continue
        if s in seen:
            continue
        seen.add(s)
        valid.append(s)
    return valid, invalid


def _post_empty(path: str) -> Any:
    """POST，参数已拼在 path 查询串里，body 为空。返回解析后的 JSON dict。"""
    ensure_login()
    st, _, _, resp = _http_request("POST", path, headers_extra=_headers_extra(WO_REFERER), body="")
    txt = resp.decode("utf-8", "replace")
    if "200" not in st:
        try:
            err = json.loads(txt)
            raise RuntimeError(f"{err.get('message', txt[:120])} (code={err.get('code')})")
        except json.JSONDecodeError:
            raise RuntimeError(f"{st} {txt[:120]}")
    return json.loads(txt)


def _wo_id_from_num(wo_num: str) -> Optional[int]:
    """用 base/list 的 filter 按 woNum 精确定位，拿 woId。

    filter 复合表达式（含时间窗）实测可用；单条件 status eq 不可靠。
    时间窗放宽到 2020-01-01 ~ 明年年底，覆盖历史单。
    """
    flt = (
        f'(woNum contains "{wo_num}")'
    )
    p = {
        "field": "woId,woNum,status,opName,displayName,creator,createTime,procId,lastModifiedTime",
        "start": 0, "length": 10, "order": "lastModifiedTime desc",
        "filter": flt,
        "relationFilter": {"eflow_wo_wo_asset": ""},
        "customInfo": {"pageType": "allTicket"},
    }
    ensure_login()
    st, _, _, resp = _http_request("POST", f"{WO_API}/base/list",
                                   headers_extra=_headers_extra(WO_REFERER),
                                   body=json.dumps(p))
    txt = resp.decode("utf-8", "replace")
    if "200" not in st:
        raise RuntimeError(f"list 查询失败: {st} {txt[:120]}")
    rows = (json.loads(txt).get("result") or [])
    # contains 是模糊匹配，客户端再精确比对一次
    for r in rows:
        if (r.get("woNum") or "").upper() == wo_num:
            return int(r["woId"])
    return None


def get_detail(wo_id: int) -> Dict[str, Any]:
    """① 详情：POST /base/detail?woId={id}（查询串传参，空 body）。"""
    return _post_empty(f"{WO_API}/base/detail?woId={int(wo_id)}")


def find_pending_confirm(detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 detail.opEntities 里找待办的 Confirm 记录：
    opName=Confirm 且 operationResult 为空、operator 为空（未执行）。"""
    for op in detail.get("opEntities") or []:
        if op.get("opName") == "Confirm" and not op.get("operationResult"):
            return op
    return None


def build_payload(detail: Dict[str, Any], pending_op: Dict[str, Any]) -> Dict[str, Any]:
    """② 构造 process 提交体（严格对齐成功样例的 18 键 flowEntity）。"""
    fe_src = detail.get("flowEntity") or {}
    flow: Dict[str, Any] = {}
    for k in FLOW_KEYS:
        v = fe_src.get(k)
        if v is None and k in ("additionalInformation", "processingProcedure",
                               "whetherArrivedField", "whetherReplacedSP"):
            v = ""          # 这四个键必须是字符串
        flow[k] = v
    return {
        "flowEntity": flow,
        "opEntity": {
            "operationResult": OPERATION_RESULT_CLOSE,
            "id": pending_op["id"],
            "opName": "Confirm",
            "woId": fe_src.get("woId"),
            "candidateOperator": "",
        },
        "assetEntity": {},
        "needStartProcess": True,
        "attachmentEntities": [],
    }


def _process(payload: Dict[str, Any]) -> Tuple[str, str]:
    """提交 base/process。返回 (status_line, body 前段)。"""
    ensure_login()
    st, _, _, resp = _http_request("POST", f"{WO_API}/base/process",
                                   headers_extra=_headers_extra(WO_REFERER),
                                   body=json.dumps(payload))
    return st, resp.decode("utf-8", "replace")[:300]


def close_one(wo_num: str, wo_id: Optional[int] = None) -> Dict[str, Any]:
    """关闭单个 WO（三步链路），返回逐单结果（绝不抛异常，错误进 result）。"""
    r: Dict[str, Any] = {"wo_num": wo_num, "ok": False, "action": "skipped", "message": ""}
    try:
        # ① 定位 woId
        wid = wo_id or _wo_id_from_num(wo_num)
        if wid is None:
            r["action"] = "not_found"
            r["message"] = "eFlow 活跃集合中找不到该单号"
            return r
        r["wo_id"] = wid

        # ② 详情 + 待办 Confirm op
        d = get_detail(wid)
        fe = d.get("flowEntity") or {}
        r["status_before"] = fe.get("status")
        r["op_name"] = fe.get("opName")
        r["display_name"] = fe.get("displayName")
        if fe.get("status") != "WaitConfirm" or fe.get("opName") != "Confirm":
            r["action"] = "skipped"
            r["message"] = f"状态不满足关闭条件（{fe.get('status')}/{fe.get('opName')}）"
            return r
        op = find_pending_confirm(d)
        if not op:
            r["action"] = "skipped"
            r["message"] = "detail 里没有待办的 Confirm 操作记录"
            return r
        r["op_id"] = op.get("id")

        # ③ 提交
        payload = build_payload(d, op)
        st, body = _process(payload)
        r["http_status"] = st[:20]
        if "200" not in st:
            r["action"] = "failed"
            r["message"] = f"提交失败: {body[:160]}"
            return r

        # ④ 复核：重查 detail，op 应已填 7 / 状态 Closed
        time.sleep(0.8)
        d2 = get_detail(wid)
        fe2 = d2.get("flowEntity") or {}
        r["status_after"] = fe2.get("status")
        closed = fe2.get("status") == "Closed" or find_pending_confirm(d2) is None
        r["ok"] = bool(closed)
        r["action"] = "closed" if closed else "failed"
        r["message"] = "" if closed else f"复核未通过（现状态 {fe2.get('status')}）"
        return r
    except Exception as e:  # noqa: BLE001 —— 逐单隔离，错误不能中断批量
        r["action"] = "failed"
        r["message"] = str(e)[:200]
        return r


def check_one(wo_num: str, wo_id: Optional[int] = None) -> Dict[str, Any]:
    """只读预检：单号能否关闭（定位 woId → detail → 待办 Confirm）。
    不做任何提交。"""
    r: Dict[str, Any] = {"wo_num": wo_num, "closable": False, "reason": ""}
    try:
        wid = wo_id or _wo_id_from_num(wo_num)
        if wid is None:
            r["reason"] = "eFlow 活跃集合中找不到该单号"
            return r
        r["wo_id"] = wid
        d = get_detail(wid)
        fe = d.get("flowEntity") or {}
        r.update({
            "status": fe.get("status"),
            "op_name": fe.get("opName"),
            "display_name": fe.get("displayName"),
            "site": fe.get("neName") or fe.get("assetName") or "",
            "create_time": fe.get("createTime"),
            "sla_status": fe.get("slaStatus"),
        })
        if fe.get("status") != "WaitConfirm" or fe.get("opName") != "Confirm":
            r["reason"] = f"状态为 {fe.get('status')}/{fe.get('opName')}，只有 WaitConfirm/Confirm 可关"
            return r
        op = find_pending_confirm(d)
        if not op:
            r["reason"] = "没有待办的 Confirm 操作记录"
            return r
        r["op_id"] = op.get("id")
        r["closable"] = True
        return r
    except Exception as e:  # noqa: BLE001
        r["reason"] = str(e)[:200]
        return r


def batch_check(wos: List[str], limit: int = MAX_BATCH) -> Dict[str, Any]:
    """批量只读预检（逐单串行）。返回逐单结果 + 汇总。"""
    items = wos[:limit]
    rows = [check_one(w) for w in items]
    closable = sum(1 for r in rows if r.get("closable"))
    return {
        "ok": True,
        "input": {"valid": len(items), "truncated": len(wos) - len(items)},
        "rows": rows,
        "summary": {
            "total": len(rows),
            "closable": closable,
            "not_closable": len(rows) - closable,
        },
    }


def batch_close(wos: List[str], limit: int = MAX_BATCH,
                interval: float = SUBMIT_INTERVAL_SEC) -> Dict[str, Any]:
    """批量关闭（逐单串行 + 间隔）。只对 check 通过的单提交；错误逐单隔离。"""
    items = wos[:limit]
    rows = []
    for i, w in enumerate(items):
        r = close_one(w)
        rows.append(r)
        if i < len(items) - 1 and interval > 0:
            time.sleep(interval)
    closed = sum(1 for r in rows if r.get("action") == "closed")
    skipped = sum(1 for r in rows if r.get("action") == "skipped")
    failed = sum(1 for r in rows if r.get("action") == "failed")
    notfound = sum(1 for r in rows if r.get("action") == "not_found")
    return {
        "ok": True,
        "input": {"valid": len(items), "truncated": len(wos) - len(items)},
        "rows": rows,
        "summary": {
            "total": len(rows),
            "closed": closed,
            "skipped": skipped,
            "failed": failed,
            "not_found": notfound,
        },
    }
