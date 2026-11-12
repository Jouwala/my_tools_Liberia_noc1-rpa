# -*- coding: utf-8 -*-
"""eflow_flow_rules.py — 按查询单（告警）给流程图规则打「相关」标注
==================================================================
eflow_flow 页查询告警/TT 后，节点规则明细默认只展示**与本单条件匹配**的规则。
本模块负责把 ocrule_details 挂到图上的每条规则，与采集表 `eflow_push_rules.xlsx`
（Push_Rules 工作表，全规则类型、含「条件」列）按（规则名, 规则类型）对齐，
再对本单取值帧求值，产出 match / match_state / 逐条件证据。

**不产生第二套判定**（与 tt_rule_evidence / eflow_push_rule_eval 同源）：
* 条件解析 —— `tt_rule_evidence._parse_push_conditions`
* 取值帧   —— `eflow_rules_matcher.build_value_frame`（站点属性同源：
  master_site_db.victims(hub_site=Y) + eflow_site.sitesubtype / "Site Type"，
  与 `eflow_rules_matcher.load_site_attrs` 同列同口径，仅连接改为双模）
* 求值     —— `eflow_rules_matcher.build_rule_mask` / `format_details`
  （空条件 = 兜底 = 全命中；未知字段 = 无法判定，不算未命中）

只读：不对任何库表做写操作。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection

logger = logging.getLogger(__name__)

# build_value_frame 需要的 eflow_tt 列（与 eflow_rules_matcher.get_eflow_tt_data 同列）
_TT_VALUE_COLUMNS = (
    "tt_no", "alarm_code", "vip_site", "hub_site", "site_id", "site_type",
    "site_information", "domain", "down_site_count", "alarm_description",
    "root_cause", "ticket_severity",
)


def _s(v: Any) -> str:
    from backend.services.eflow_rules import tt_rule_evidence as E
    return E._s(v)


def _eflow_site_cols(conn) -> Dict[str, str]:
    """探测 eflow_site 的 id / sitesubtype / assetType 列（已加引号，两方言兼容）。"""
    from backend.services.tt_postmortem import _qcol

    names: set = set()
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='eflow_site'"
        ).fetchall()
        names = {str(r[0]) for r in rows}
    except Exception:
        try:
            rows = conn.execute("PRAGMA table_info(eflow_site)").fetchall()
            names = {str(r[1]) for r in rows}
        except Exception:
            return {}

    def find(*cands) -> Optional[str]:
        for c in cands:
            if c in names:
                return _qcol(c)
        lower = {n.lower().replace(" ", ""): n for n in names}
        for c in cands:
            hit = lower.get(c.lower().replace(" ", ""))
            if hit:
                return _qcol(hit)
        return None

    cols = {
        "id": find("Site ID", "site_id"),
        "sub": find("sitesubtype", "Site Sub Type", "site_subtype"),
        "asset": find("Site Type", "site_type", "assettype"),
    }
    return cols if cols["id"] else {}


def _load_site_attrs(conn, site_id: str) -> Dict[str, Any]:
    """单站点属性，与 eflow_rules_matcher.load_site_attrs 同列同口径（双模连接版）。"""
    sid = _s(site_id)
    if not sid:
        return {}
    out: Dict[str, Any] = {}
    try:
        row = conn.execute(
            'SELECT "victims" FROM "master_site_db" '
            'WHERE UPPER("hub_site") = ? AND CAST("site_id" AS TEXT) = ?',
            ("Y", sid),
        ).fetchone()
        if row:
            try:
                out["downstreamSites"] = int(row[0])
            except (TypeError, ValueError):
                pass
    except Exception:
        logger.debug("[eflow_flow_rules] master_site_db 查询失败", exc_info=True)

    cols = _eflow_site_cols(conn)
    present = [(k, c) for k, c in (("id", cols.get("id")), ("sub", cols.get("sub")),
                                   ("asset", cols.get("asset"))) if c]
    if present:
        try:
            sel = ", ".join(c for _, c in present)
            row = conn.execute(
                f"SELECT {sel} FROM eflow_site WHERE CAST({cols['id']} AS TEXT) = ?",
                (sid,),
            ).fetchone()
            if row:
                for (k, _), v in zip(present, row):
                    if k == "id":
                        continue
                    v = _s(v)
                    if v:
                        out["siteSubType" if k == "sub" else "assetType"] = v
        except Exception:
            logger.debug("[eflow_flow_rules] eflow_site 查询失败", exc_info=True)
    return out


def _condition_index() -> Dict[Tuple[str, str], Dict[str, str]]:
    """Push_Rules 全量行 → {(规则名归一, 规则类型): 行}（mtime 缓存复用 tt_rule_evidence）。"""
    from backend.services.eflow_rules import tt_rule_evidence as E

    idx: Dict[Tuple[str, str], Dict[str, str]] = {}
    for rec in E._load_push_rule_rows():
        key = (_s(rec.get("规则名称")).lower(), _s(rec.get("规则类型")))
        if key[0]:
            idx.setdefault(key, rec)
    return idx


def annotate_graph(graph: Dict[str, Any], tt_no: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """按查询单（tt_no）给图上每条规则标注与本单的相关性，返回 (graph, rule_hits, meta)。

    match_state：
      matched      条件对本单求值为 True
      fallback     条件为空 = 兜底规则，全命中
      not_matched  条件求值为 False（与本单无关）
      undecidable  条件引用本地取不到的字段，无法判定
      no_data      采集表里没有这条规则（无条件原文）

    取值帧来自数据库里的真实 TT；求值循环在 annotate_graph_with_frame（多条件模拟共用）。
    任何异常不抛出：meta.available=False，graph 保持原样，页面降级为全部规则。
    """
    t0 = time.perf_counter()
    meta: Dict[str, Any] = {"available": False, "error": "", "tt_no": _s(tt_no),
                            "fields": {}, "evaluated": 0, "undecidable": 0}
    try:
        import pandas as pd
        from backend.services.eflow_rules import eflow_rules_matcher as M

        with get_raw_connection() as conn:
            row = conn.execute(
                f"SELECT {', '.join(_TT_VALUE_COLUMNS)} FROM eflow_tt WHERE tt_no = ?",
                (_s(tt_no),),
            ).fetchone()
            if not row:
                meta["error"] = f"本地 eflow_tt 未找到 {_s(tt_no)}，规则条件无法求值"
                return graph, [], meta
            tt_row = dict(row)
            attrs = _load_site_attrs(conn, tt_row.get("site_id"))

        vf = M.build_value_frame(pd.DataFrame([tt_row]), attrs={_s(tt_row.get("site_id")): attrs})
        return annotate_graph_with_frame(graph, vf, meta)
    except Exception as e:  # noqa: BLE001
        logger.warning("[eflow_flow_rules] 规则相关性标注失败：%s", e, exc_info=True)
        meta["error"] = f"{type(e).__name__}: {e}"
        return graph, [], meta
    finally:
        meta["elapsed_sec"] = round(time.perf_counter() - t0, 2)


def annotate_graph_with_frame(
    graph: Dict[str, Any], vf: Any, meta: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """对**已构造好**的取值帧逐规则求值（真实单与多条件模拟共用，口径单一来源）。

    match_state / 证据 / 节点相关计数 / hits 的语义与 annotate_graph 完全一致；
    区别只在取值帧来源：那里来自数据库 TT 行，这里由调用方构造（模拟 = 用户输入）。
    """
    t0 = time.perf_counter()
    if meta is None:
        meta = {"available": False, "error": "", "tt_no": "",
                "fields": {}, "evaluated": 0, "undecidable": 0}
    try:
        from backend.services.eflow_rules import eflow_rules_matcher as M
        from backend.services.eflow_rules import tt_rule_evidence as E

        meta["fields"] = {c: _s(vf[c].iloc[0]) for c in vf.columns}
        idx = _condition_index()
        try:
            meta["rules_file_mtime"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(E._push_rules_xlsx().stat().st_mtime))
        except OSError:
            pass

        evaluated = undecidable = 0
        for n in graph.get("nodes", []):
            related = 0
            for r in n.get("rules", []):
                rec = idx.get((_s(r.get("name")).lower(), _s(r.get("rule_type"))))
                if rec is None:
                    r.update({"match": None, "match_state": "no_data",
                              "match_details": "", "conditions_text": "", "unknown_fields": []})
                    continue
                r["conditions_text"] = _s(rec.get("条件"))
                r["rule_id"] = _s(rec.get("ID"))
                r["severity"] = _s(rec.get("严重级别"))
                r["create_by"] = _s(rec.get("创建人"))
                r["update_by"] = _s(rec.get("更新人"))
                r["create_time"] = _s(rec.get("创建时间"))
                conds = E._parse_push_conditions(r["conditions_text"])
                unknown = sorted({c["field"] for c in conds if c["field"] not in vf.columns})
                if unknown:
                    undecidable += 1
                    r.update({"match": None, "match_state": "undecidable",
                              "match_details": "", "unknown_fields": unknown})
                    continue
                evaluated += 1
                if not conds:
                    r.update({"match": True, "match_state": "fallback",
                              "match_details": "", "unknown_fields": []})
                    related += 1
                    continue
                try:
                    ok = bool(M.build_rule_mask(vf, conds).iloc[0])
                    detail = _s(M.format_details(vf, conds).iloc[0])
                except Exception:
                    logger.debug("[eflow_flow_rules] 规则 %s 求值失败", r.get("name"), exc_info=True)
                    r.update({"match": None, "match_state": "undecidable",
                              "match_details": "", "unknown_fields": []})
                    undecidable += 1
                    continue
                r.update({"match": ok, "match_state": "matched" if ok else "not_matched",
                          "match_details": detail, "unknown_fields": []})
                if ok:
                    related += 1
            n["related_rule_count"] = related

        # 命中该帧的规则 = 条件求值 True（含兜底），与页面「仅相关」同一口径
        hits: List[Dict[str, Any]] = []
        seen: set = set()
        for n in graph.get("nodes", []):
            for r in n.get("rules", []):
                if r.get("match") is not True:
                    continue
                k = (r.get("name"), n["id"])
                if k in seen:
                    continue
                seen.add(k)
                fallback = r.get("match_state") == "fallback"
                hits.append({
                    **r, "node": n["id"],
                    "reason_zh": "兜底规则（无条件，全部命中）" if fallback else "规则条件与本单匹配",
                    "reason_en": "Fallback rule (no conditions)" if fallback else "Rule conditions match this ticket",
                })

        meta.update({"available": True, "evaluated": evaluated, "undecidable": undecidable})
        return graph, hits, meta
    except Exception as e:  # noqa: BLE001
        logger.warning("[eflow_flow_rules] 取值帧规则标注失败：%s", e, exc_info=True)
        meta["error"] = f"{type(e).__name__}: {e}"
        return graph, [], meta
    finally:
        meta["elapsed_sec"] = round(time.perf_counter() - t0, 2)


def build_sim_frame(conditions: Dict[str, Any]) -> Tuple[Any, Dict[str, str]]:
    """把用户输入的多条件构造成单行取值帧（多条件模拟入口）。

    ⚠ **不在本函数里做任何字段归一化** —— 构造成合成 TT 行 + 站点属性后
    原样交给 `eflow_rules_matcher.build_value_frame`，YES/NO→1/0、大小写、
    数值列等全部走与真实单子**同一条**归一化路径，杜绝「模拟口径 ≠ 实单口径」。

    conditions 的键与取值帧字段对应（全部可选）：
      alarmCode→alarm_code  vipSite→vip_site  hubSite→hub_site
      netWorkType→domain    downSiteCount→down_site_count
      alarmDescription→alarm_description  reasonType→root_cause
      ticketSeverity→ticket_severity
      siteSubType/assetType/downstreamSites → attrs["__sim__"]（站点属性三件套）
    """
    import pandas as pd
    from backend.services.eflow_rules import eflow_rules_matcher as M

    c = {k: _s(v) for k, v in (conditions or {}).items()}
    row = {
        "tt_no": "(simulate)",
        "alarm_code": c.get("alarmCode", ""),
        "vip_site": c.get("vipSite", ""),
        "hub_site": c.get("hubSite", ""),
        # attrs 生效的前提是 site_id 列存在；用固定占位键，避免与真实站点混淆
        "site_id": "__sim__",
        "site_type": "",
        "site_information": "",
        "domain": c.get("netWorkType", ""),
        "down_site_count": c.get("downSiteCount", ""),
        "alarm_description": c.get("alarmDescription", ""),
        "root_cause": c.get("reasonType", ""),
        "ticket_severity": c.get("ticketSeverity", ""),
    }
    attrs: Dict[str, Any] = {"__sim__": {}}
    if c.get("siteSubType"):
        attrs["__sim__"]["siteSubType"] = c["siteSubType"]
    if c.get("assetType"):
        attrs["__sim__"]["assetType"] = c["assetType"]
    if c.get("downstreamSites"):
        attrs["__sim__"]["downstreamSites"] = c["downstreamSites"]

    vf = M.build_value_frame(pd.DataFrame([row]), attrs=attrs)
    fields = {col: _s(vf[col].iloc[0]) for col in vf.columns}
    return vf, fields