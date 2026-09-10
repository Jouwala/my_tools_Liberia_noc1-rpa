# -*- coding: utf-8 -*-
"""
eflow_ume_link.py - 从 eFlow 压缩告警链路解析"原始 RAN UME 告警 AID"
=====================================================================
背景（见 backend/services/URL_EFLOW_ALARM.txt 抓包结论）：

TT 告警表里的 Alarm ID（id 列）很多是**压缩/归并后的根告警**（如 99933
SITE DOWN DUE TO POWER OFF，relationflag=1），其 aid 列是 eFlow 侧编号，
**不是** RAN UME 的真实告警 ID。真正的原始 UME 告警（alarmSource=
zte-ume-ran）藏在多级"点击详情"的下钻关系链里，需递归 relatedAlarms
才能拿到。链路如下（以 TT202609100095 / 报警 1764210465421 为例）：

  1. 根告警 99933（id=1764210465421, relationflag=1, servertime=<根>）
     POST /api/fm-history/v1/relation/relatedAlarms/table
     {"relatedalarmrequestbeans":[{id,relationflag,servertime,parentinfo?}]}
     → 直接下级：2× zte-ume-ran 原始告警（aid=1639656429564/…9033）
        + 3× RAN 层压缩告警（9980/9990/9910，relationflag=3）
  2. 对每个 relationflag=3 的压缩行，用它**该行自带的 servertime**再查一次
     relatedAlarms/table → 下一级原始 zte-ume-ran 告警（如 9990 → 10 个
     Cell is out of service，aid=1639656430232 等）
  3. 递归直至没有 relationflag=3 压缩行为止；alarmkey 以 "zte-ume-ran"
     开头的行，aid 字段就是 RAN UME 的真实告警 ID。

本模块只读，不写库。结果按 alarm_id 做进程内 TTL 缓存，避免同一 TT
多端点并发重复打 eFlow 关系表。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from backend.services.eflow_api_client import (
    _http_request, _safe_json_loads, ensure_login, get_session_headers,
    parse_response, HOST, PORT,
)
from backend.services.eflow_alarm_service import ALARM_REFERER, _normalize_alarm_rows

logger = logging.getLogger(__name__)

REL_TABLE_PATH = "/api/fm-history/v1/relation/relatedAlarms/table"
REL_PATH = "/api/fm-history/v1/relation/relatedAlarms"

_CACHE_TTL_HIT = 300    # 链路命中缓存 5 分钟
_CACHE_TTL_MISS = 120   # 未命中缓存 2 分钟
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()

_MAX_DEPTH = 4      # 递归最大深度（防极端链路死循环）
_MAX_NODES = 60     # 单次解析最多遍历节点数


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


def _post(path: str, payload: Dict[str, Any], timeout: int = 45):
    """POST 并返回解析后的 JSON（元组已解包）。失败返回 (status, None)。"""
    headers = _headers_extra()
    st, _hd, _raw, body = _http_request(
        "POST", path, headers_extra=headers, body=json.dumps(payload), retry=0)
    data, ok = _safe_json_loads(body.decode("utf-8"), label=path)
    return st, (data if ok else None)


def _flatten_related(data: Any) -> List[dict]:
    """把 relatedAlarms/table 的嵌套响应压平成 [含 relatedalarms 的 dict] 列表。

    真实响应形如 [[{id,total,relatedalarms:[...]}]]（外包一层 list），
    也兼容直接 list[dict] / dict 形态。逐层收集所有 has_key="relatedalarms"
    的对象，取其 relatedalarms 并拼接。
    """
    groups: List[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if "relatedalarms" in x:
                groups.append(x)
            for k, v in x.items():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(data)
    rows: List[dict] = []
    for g in groups:
        ra = g.get("relatedalarms")
        if isinstance(ra, list):
            rows.extend(ra)
    return rows


def _val(v):
    """eFlow 单元格对象 {value} → 值；普通标量原样返回。"""
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def _num(v):
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def _is_ume_orig(row: dict) -> bool:
    """原始 RAN UME 告警判定：alarmkey 以 zte-ume-ran 开头（probe/dump 确认）。"""
    ak = _val(row.get("alarmkey")) or str(row.get("alarmkey") or "")
    return str(ak).startswith("zte-ume-ran")


def _codename(row: dict) -> str:
    dac = row.get("displayalarmcode") or {}
    name = dac.get("alarmcodename") if isinstance(dac, dict) else None
    if isinstance(name, dict):  # 某些响应 alarmcodename 是 {en,zh}
        name = (name.get("zh") or name.get("en")) or ""
    return str(name or row.get("codename") or "").strip()


def _fmt_node(row: dict) -> dict:
    dac = row.get("displayalarmcode") or {}
    dac = dac if isinstance(dac, dict) else {}
    return {
        "id": _num(_val(row.get("id")) or ""),
        "relationflag": _val(row.get("relationflag")),
        "aid": _num(_val(row.get("aid")) or ""),
        "servertime": int(_val(row.get("servertime")) or 0) or None,
        "alarmkey": str(_val(row.get("alarmkey")) or ""),
        "codename": _codename(row),
        "alarmcode": _num(_val(dac.get("alarmcode")) or ""),
        "restype": str(_val(dac.get("restype")) or ""),
        "site_name": _val(row.get("sitename")) or _val(row.get("positionname")) or "",
        "is_ume_orig": _is_ume_orig(row),
    }


def resolve_alarm_chain(
    alarm_id: Any,
    root_servertime: Optional[int] = None,
    root_relationflag: Optional[int] = None,
) -> Dict[str, Any]:
    """按 eFlow 告警 id 递归 relatedAlarms/table，收集全部"原始 RAN UME 告警 AID"。

    参数：
      alarm_id          根告警的 eFlow Alarm ID（TT 告警表 id 列，如 1764210465421）
      root_servertime   根告警 servertime（毫秒）。缺省时优先从本地告警表/活查取得；
                        实在没有时退 now（可能导致关系表取不到，走 natural 兜底）。
      root_relationflag 根告警 relationflag（缺省 1）。

    返回：
      {"ok", "n_ume", "n_nodes", "aids":[<每节点 {fm-node…}>], "chain":[...],
       "error", "cached", "elapsed_sec"}
        aids= 所有 alarmkey 以 zte-ume-ran 开头的"原始 UME 告警"节点（已去重）；
             每个元素含真实 aid（UME 侧告警 ID）可直接送 ran_ume lookup_alarm。
        chain= 所有遍历到的节点（含压缩行），供前端展示关系链。
    """
    key = _num(str(alarm_id or "").strip())
    if not key.isdigit():
        return {"ok": False, "n_ume": 0, "n_nodes": 0, "aids": [], "chain": [],
                "error": f"alarm_id 非法: {alarm_id!r}", "cached": False, "elapsed_sec": 0.0}

    with _lock:
        ent = _cache.get(key)
        if ent:
            ts, res = ent
            ttl = _CACHE_TTL_HIT if res.get("ok") else _CACHE_TTL_MISS
            if time.time() - ts < ttl:
                return dict(res, cached=True)

    t0 = time.time()
    ensure_login()

    # 定位根节点 servertime / relationflag（若未提供）
    if not root_servertime or root_relationflag is None:
        _meta = _fetch_root_meta(key)
        root_servertime = root_servertime or _meta.get("servertime")
        if root_relationflag is None:
            root_relationflag = _meta.get("relationflag")

    try:
        chain: List[dict] = []
        aids: List[dict] = []
        seen_aid: set = set()
        visited: set = set()
        queue: List[dict] = [{
            "id": key, "relationflag": root_relationflag or 1,
            "servertime": root_servertime, "depth": 0,
            "alarmkey": "", "aid": "", "codename": "", "site_name": "",
            "is_ume_orig": False,
        }]

        while queue and len(visited) < _MAX_NODES:
            node = queue.pop(0)
            node_key = (node["id"], node["relationflag"])
            if node_key in visited or node.get("depth", 0) > _MAX_DEPTH:
                continue
            visited.add(node_key)
            chain.append(node)

            # 根节点没查过表则先查；若是纯 aid 已收集可跳过查表（压缩行仍需 drill）
            if not node.get("_root_meta_only"):
                table_rows = _related_of(node["id"], node["relationflag"], node.get("servertime"))
                for row in table_rows:
                    fn = _fmt_node(row)
                    fn["depth"] = node["depth"] + 1
                    # 所有访问到的节点（含原始 UME）都计入链路，便于前端完整展示下钻层级
                    if not any(c.get("id") == fn["id"] and c.get("relationflag") == fn["relationflag"] for c in chain):
                        chain.append(fn)
                    if fn["is_ume_orig"] and fn["aid"] and fn["aid"].isdigit():
                        if fn["aid"] not in seen_aid:
                            seen_aid.add(fn["aid"])
                            aids.append(fn)
                    elif (fn["relationflag"] in (3, 2) or fn["id"]) and fn.get("servertime"):
                        # 压缩行（rel=2/3，可能还带下级）入队继续 drill
                        if fn["id"] and fn["id"] not in [q["id"] for q in queue]:
                            queue.append({
                                "id": fn["id"], "relationflag": fn["relationflag"],
                                "servertime": fn["servertime"], "depth": node["depth"] + 1,
                                "alarmkey": fn["alarmkey"], "aid": fn.get("aid") or "",
                                "codename": fn["codename"], "site_name": fn["site_name"],
                                "is_ume_orig": fn["is_ume_orig"],
                            })
            node.pop("_root_meta_only", None)

        ok = bool(aids)
        result = {
            "ok": ok, "n_ume": len(aids), "n_nodes": len(chain),
            "aids": aids, "chain": chain,
            "error": None if ok else "关系链中未找到 zte-ume-ran 原始告警 AID",
            "cached": False, "elapsed_sec": round(time.time() - t0, 2),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("eflow_ume_link 解析关系链失败")
        result = {"ok": False, "n_ume": 0, "n_nodes": len(chain if 'chain' in locals() else []),
                  "aids": [], "chain": chain if 'chain' in locals() else [],
                  "error": f"{type(e).__name__}: {e}",
                  "cached": False, "elapsed_sec": round(time.time() - t0, 2)}

    with _lock:
        _cache[key] = (time.time(), result)
    return result


def _fetch_root_meta(alarm_id: str) -> dict:
    """尝试从相关告警表补根节点 servertime / relationflag（尽力而为，不阻塞）。"""
    meta: dict = {}
    try:
        from backend.services.eflow_alarm_query import find_alarm_by_id
        live = find_alarm_by_id(alarm_id)
        if live.get("found") and isinstance(live.get("row"), dict):
            row = live["row"]
            # _snake 归一化后的键：servertime / relationflag / id
            sv = row.get("servertime") or row.get("historyservertime")
            if sv:
                try:
                    meta["servertime"] = int(float(sv))
                except (TypeError, ValueError):
                    pass
            if row.get("relationflag") is not None:
                try:
                    meta["relationflag"] = int(row.get("relationflag"))
                except (TypeError, ValueError):
                    pass
    except Exception:  # noqa: BLE001
        logger.debug("_fetch_root_meta 失败（忽略）", exc_info=True)
    return meta


def _related_of(alarm_id: str, relationflag: Any, servertime: Optional[int]) -> List[dict]:
    """对单个节点查 relatedAlarms/table，返回下级行预处理列表。"""
    bean: Dict[str, Any] = {"id": int(alarm_id), "relationflag": int(relationflag)}
    if servertime:
        bean["servertime"] = int(servertime)
    else:
        bean["directids"] = []
    st, data = _post(REL_TABLE_PATH, {"relatedalarmrequestbeans": [bean]})
    if "200" not in st:
        logger.warning("relatedAlarms/table 非 200: %s id=%s", st, alarm_id)
        return []
    rows = _flatten_related(data)
    return rows


# ------------------------- 便捷入口 -------------------------

def get_ume_aids(alarm_id: Any, root_servertime: Optional[int] = None) -> List[str]:
    """只返回真实 UME aid 列表（给 /tt-ume-suggestion 快速用）。"""
    res = resolve_alarm_chain(alarm_id, root_servertime=root_servertime)
    return [a["aid"] for a in res.get("aids", [])]


if __name__ == "__main__":  # pragma: no cover
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("stdout 重配置失败", exc_info=True)
    logging.basicConfig(level=logging.INFO)
    aid = sys.argv[1] if len(sys.argv) > 1 else "1764210465421"
    res = resolve_alarm_chain(aid, root_servertime=1789054392000)
    print(f"ok={res['ok']} n_ume={res['n_ume']} n_nodes={res['n_nodes']} "
          f"error={res['error']} cached={res['cached']} elapsed={res['elapsed_sec']}s")
    for a in res["aids"]:
        print(f"  UME aid={a['aid']} rel={a['relationflag']} code={a['codename']} "
              f"site={a['site_name'][:40]}")
    print("\nchain:")
    for c in res["chain"]:
        print(f"  [d{c.get('depth')}] rel={c.get('relationflag')} id={c.get('id')} "
              f"sv={c.get('servertime')} aid={c.get('aid')} {"orig" if c.get('is_ume_orig') else 'comp'}")