# -*- coding: utf-8 -*-
r"""
GIS RealTime Alarm 根因聚合服务（Root Cause Aggregation，2026-10-21）

做什么
------
把「一批断站为什么同时断」从人工翻链路变成「一次内存聚类 + 一段带证据的结论」。

输入全部由路由层（routers/gis.py 的 /realtime/rca）取好传入，本模块
**不碰数据库**（router→service 单向依赖，方向与 gis_mw_overlay 一致）：

- rca_rows      —— `_scan_realtime_alarms` 的第 9 个返回值：每条实时告警一行，
                   含 link_path（核心站→本站的 site_id 链，'>' 分隔）等拓扑字段。
- in_scope_sids —— 通过高级筛选 + 主站点表 JOIN 的 site_id 集合（口径与
                   /realtime/sites 完全同一次扫描、同一个 _build_filter_where）。
- site_info     —— 全部告警站的 {site_id: {site_name, lat, lng, region}}
                   （**不带筛选**，供「范围外根因站」取坐标）。

三类簇
------
A 拓扑根因簇：上游告警站的 site_id 出现在其它告警站的 link_path 祖先里，
  即「我断了 → 挂在我下面的站跟着断」。归属规则：**每个断站只归属其最深的
  告警祖先**（最邻近的可证实故障点，运维可操作性最强；"最大簇优先"会让远端
  核心吞掉本地故障）。一个站可以同时是下游簇的根、上游簇的成员（两级故障
  各成一簇，互不双计）。
B 同因聚集簇：无可用 link_path 的站（卫星站等，link_path 为 '--'/空）按
  「告警问题 + 10 分钟时间窗」聚集 —— 同一批站在同一窗口内报同一问题，
  疑似批量事件（如同区域大面积停电、核心侧批量操作）。
C eFlow 佐证：realtime_alarm.impact_site_list / impact_site_number 是 eFlow
  已标注的根因告警影响面（分隔符实测不统一，按 [,;\s]+ 兼容切分）。命中簇
  成员则挂到该簇 evidence.eflow_impact 提升置信度；匹配不上计入
  meta.eflow_root_unmatched 显式展示，不静默丢弃。

置信度（确定性公式，纯启发式）
------
A 簇：0.5 + 0.15*(成员≥2) + 0.2*(eFlow 佐证) + 0.15*(根因告警与成员首警
      时间差 ≤10 分钟)，上限 0.95
B 簇：0.4 + 0.15*(站点≥3) + 0.2*(同 alarmcode) + 0.15*(窗口跨度 ≤10 分钟)，
      上限 0.90

LLM 叙事（rca_narrative）
------
沿用 alarm_attribution_service 的约定：先把确定性统计算好，模型只负责
**解释**；evidence 随响应下发供用户核对；provider=='local'/无 key/调用异常
一律降级为 local_summary（本地规则文案），不返回错误页。api_key 只随请求体
进出，本模块不落盘、不写日志。

MOCK 说明：本模块不写任何数据。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 簇数上限：截断时 meta.truncated=True 显式暴露（AGENTS.md 三.1b：截断不得静默）。
CLUSTER_LIMIT = 100
# B 簇时间窗：与簇首告警相差超过该毫秒数则开新窗（10 分钟）。
TIME_WINDOW_MS = 10 * 60 * 1000
# 单簇根因站最多下发的告警明细条数（防极端情况下根因站带几百条告警撑爆响应）。
ROOT_ALARM_CAP = 10

# 根因类型关键词（大写子串匹配，按优先级排序；POWER 优先于 SITE OUTAGE：
# "SITE OUTAGE DUE TO POWER OFF" 的真实根因是电源，不能被字面靠前的词截胡）。
_CAUSE_RULES: List[Tuple[str, str]] = [
    ("POWER", "power"),
    ("FIBER", "fiber"),
    ("MW LINK", "transmission"),
    ("MICROWAVE", "transmission"),
    ("SITE OUTAGE", "site_outage"),
    ("SITE DOWN", "site_outage"),
]

# link_path 的合法分隔符；'--' 与空串视为无链路（卫星站/未标注）。
_PATH_SPLIT = re.compile(r"[>\s]+")
# impact_site_list 分隔符：实测逗号/分号/空格混用，一并兼容。
_IMPACT_SPLIT = re.compile(r"[,;\s]+")


def _cause_type_of(titles: List[str]) -> str:
    """按关键词优先级把一组告警标题归为单一根因类型。"""
    joined = " ".join(str(t or "").upper() for t in titles)
    for kw, cause in _CAUSE_RULES:
        if kw in joined:
            return cause
    return "other"


def _chain_of(link_path: str) -> List[str]:
    """'4542>3297>4070>4071>3651' → ['4542','3297','4070','4071','3651']。

    '--' / 空 / 纯空白 → []（无链路）。token 只保留数字位（链路里存的是
    site_id；防脏数据里混入非数字 token 后参与祖先匹配）。
    """
    if not link_path or str(link_path).strip() in ("", "--"):
        return []
    out = []
    for tok in _PATH_SPLIT.split(str(link_path).strip()):
        if tok.isdigit():
            out.append(tok)
    return out


def _norm_name(s: str) -> str:
    """站点名归一（C 簇名字匹配用）：去非字母数字 + 小写，与 gis.py
    _norm_site_name 同口径 —— 源数据里站名有大小写/标点差异，精确等于会漏。"""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _parse_impact(impact_list: str) -> Tuple[List[str], List[str]]:
    """impact_site_list → (sid 候选, 站名候选)。纯数字 token 按 sid、其余按站名。"""
    sids: List[str] = []
    names: List[str] = []
    for tok in _IMPACT_SPLIT.split(str(impact_list or "")):
        tok = tok.strip()
        if not tok:
            continue
        (sids if tok.isdigit() else names).append(tok)
    return sids, names


def _site_view(sid: str, site_info: Dict[str, Dict], rows_of_site: List[Dict]) -> Dict[str, Any]:
    """站点展示信息：site_info 命中取坐标/站名；未命中（不在主表）回退告警行。"""
    info = site_info.get(sid) or {}
    first = rows_of_site[0] if rows_of_site else {}
    return {
        "site_id": sid,
        "site_name": info.get("site_name") or str(first.get("site_name") or sid),
        "region": info.get("region") or str(first.get("region") or ""),
        "lat": info.get("lat"),
        "lng": info.get("lng"),
        "in_master": bool(info),
    }


def compute_rca(rca_rows: List[Dict[str, Any]],
               in_scope_sids: Set[str],
               site_info: Dict[str, Dict]) -> Dict[str, Any]:
    """确定性根因聚类主入口。输入见模块头注释；输出结构见计划文档 §1.3。"""
    in_scope_sids = set(in_scope_sids or [])
    rows_by_site: Dict[str, List[Dict]] = {}
    for r in rca_rows or []:
        rows_by_site.setdefault(str(r.get("site_id") or ""), []).append(r)
    alarmed_sids: Set[str] = set(rows_by_site.keys())
    in_scope_alarm = {s for s in alarmed_sids if s in in_scope_sids}

    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "empty": not rca_rows,
        "alarm_rows": len(rca_rows or []),
        "alarmed_sites": len(alarmed_sids),
        "in_scope_sites": len(in_scope_alarm),
        "orphan_alarm_rows": sum(
            1 for r in rca_rows or []
            if str(r.get("site_id") or "") not in site_info
        ),
        "eflow_root_unmatched": 0,
        "truncated": False,
        "limit": CLUSTER_LIMIT,
    }

    if not rca_rows:
        meta.update(with_link_path=0, satellite_sites=0, covered_sites=0,
                    uncovered_sites=0, topology_clusters=0, same_cause_clusters=0)
        meta["uncovered_site_ids"] = []
        return {"clusters": [], "meta": meta}

    # ---- 每站首警（B 簇窗口与置信度都要用）----
    first_alarm: Dict[str, Dict] = {}
    for sid, rs in rows_by_site.items():
        timed = [r for r in rs if r.get("raised_ms")]
        first_alarm[sid] = min(timed, key=lambda r: r["raised_ms"]) if timed else rs[0]

    # ---- 每站链路（行间容错）：link_path 理论上是站点属性，取该站**任一行**
    #      的可用链路即可 —— 不能只信首警行（实测同一站各行可能有一行缺路径），
    #      否则一条脏行就让整个站点错失拓扑归属。
    chain_by_site: Dict[str, List[str]] = {}
    lp_src_by_site: Dict[str, Dict] = {}
    for sid, rs in rows_by_site.items():
        for r in rs:
            ch = _chain_of(str(r.get("link_path") or ""))
            if ch:
                chain_by_site[sid] = ch
                lp_src_by_site[sid] = r
                break

    # ---- 算法 A：拓扑根因簇（最深告警祖先归属）----
    assign: Dict[str, str] = {}  # 成员 site_id -> 根因 site_id
    with_link_path = 0
    for sid in in_scope_alarm:
        chain = chain_by_site.get(sid)
        # 无链路站不参与 A（可能是卫星站，也可能是脏数据）—— 计入 no_path 统计
        if not chain:
            continue
        with_link_path += 1
        # 自链尾向链头扫：第一个也在告警的祖先 = 最深告警祖先。
        # 链尾通常是自己，显式排除；链中段的其它 token 才是祖先候选。
        for anc in reversed([a for a in chain if a != sid]):
            if anc in alarmed_sids:
                assign[sid] = anc
                break

    clusters: List[Dict[str, Any]] = []
    by_root: Dict[str, List[str]] = {}
    for member, root in assign.items():
        by_root.setdefault(root, []).append(member)

    covered_sids: Set[str] = set(assign.keys()) | set(by_root.keys())

    for root_sid, members in by_root.items():
        member_ids = sorted(members, key=lambda s: -(len(rows_by_site.get(s) or [])))
        root_rows = rows_by_site.get(root_sid) or []
        root_titles = [r.get("alarm_title") or "" for r in root_rows]
        root_first_ms = first_alarm.get(root_sid, {}).get("raised_ms")
        member_first_ms = min(
            (first_alarm[s]["raised_ms"] for s in member_ids if first_alarm.get(s, {}).get("raised_ms")),
            default=None,
        )
        time_close = (
            root_first_ms is not None and member_first_ms is not None
            and abs(member_first_ms - root_first_ms) <= TIME_WINDOW_MS
        )
        cluster = {
            "cluster_id": f"topo:{root_sid}",
            "kind": "topology",
            "cause_type": _cause_type_of(root_titles),
            "root": _site_view(root_sid, site_info, root_rows),
            "root_in_scope": root_sid in in_scope_sids,
            "members": [],
            "member_count": len(member_ids),
            "evidence": {
                "link_paths": sorted({
                    str(lp_src_by_site.get(s, {}).get("link_path") or "")
                    for s in member_ids if s in lp_src_by_site
                }),
                "time_window": _time_window_of([first_alarm.get(s, {}) for s in member_ids]),
                "shared_code": None,
                "shared_problem": None,
                "eflow_impact": None,
            },
            # 置信度先给基础分，C 簇佐证后再加分
            "confidence": round(min(0.95,
                0.5 + (0.15 if len(member_ids) >= 2 else 0.0)
                + (0.15 if time_close else 0.0)), 2),
        }
        cluster["root"]["alarms"] = [
            {
                "alarm_title": r.get("alarm_title") or "",
                "alarmcode": r.get("alarmcode") or "",
                "severity": r.get("severity") or "",
                "raised_ms": r.get("raised_ms"),
            }
            for r in sorted(root_rows, key=lambda r: -(r.get("raised_ms") or 0))
        ][:ROOT_ALARM_CAP]
        cluster["root"]["in_scope"] = root_sid in in_scope_sids
        for m in member_ids:
            mv = _site_view(m, site_info, rows_by_site.get(m) or [])
            mv.update({
                "in_scope": True,
                "alarm_count": len(rows_by_site.get(m) or []),
                "tt_id": next((str(r.get("tt_id")) for r in rows_by_site[m] if r.get("tt_id")), ""),
                "link_path": str((lp_src_by_site.get(m) or first_alarm.get(m) or {}).get("link_path") or ""),
                "transmission_type": str((lp_src_by_site.get(m) or first_alarm.get(m) or {}).get("transmission_type") or ""),
            })
            cluster["members"].append(mv)
        clusters.append(cluster)

    # ---- 算法 B：同因聚集簇（无链路、未被 A 覆盖的 in_scope 站）----
    b_candidates = [
        s for s in in_scope_alarm
        if s not in covered_sids and s not in chain_by_site
    ]
    # 代表行 = 站点首警；raised_ms 缺失的行不参与时间窗（计划 §8），但仍计入 uncovered。
    b_reps = [first_alarm[s] for s in b_candidates if first_alarm.get(s, {}).get("raised_ms")]
    groups: Dict[str, List[Dict]] = {}
    for rep in b_reps:
        key = (str(rep.get("oss_specific_problem") or "")
               or str(rep.get("alarmcode") or ""))[:80] or "unknown"
        groups.setdefault(key, []).append(rep)
    b_seq = 0
    for key, reps in groups.items():
        reps.sort(key=lambda r: r["raised_ms"])
        windows: List[List[Dict]] = []
        cur: List[Dict] = []
        base_ms = None
        for rep in reps:
            if base_ms is None or rep["raised_ms"] - base_ms > TIME_WINDOW_MS:
                if cur:
                    windows.append(cur)
                cur = [rep]
                base_ms = rep["raised_ms"]
            else:
                cur.append(rep)
        if cur:
            windows.append(cur)
        for win in windows:
            sids = sorted({str(r.get("site_id") or "") for r in win})
            if len(sids) < 2:
                continue
            b_seq += 1
            shared_code = len({str(r.get("alarmcode") or "") for r in win}) == 1
            span_ms = (win[-1]["raised_ms"] - win[0]["raised_ms"]) if len(win) > 1 else 0
            rep0 = win[0]
            rep_sid = str(rep0.get("site_id") or "")
            cluster = {
                "cluster_id": f"same:{b_seq}",
                "kind": "same_cause",
                "cause_type": _cause_type_of([key]),
                # 无拓扑语义的「根」：窗口内最早告警的站（疑似源头/最先受影响）
                "root": _site_view(rep_sid, site_info, rows_by_site.get(rep_sid) or []),
                "root_in_scope": True,
                "members": [],
                "member_count": len(sids),
                "evidence": {
                    "link_paths": [],
                    "time_window": {
                        "start_ms": win[0]["raised_ms"],
                        "end_ms": win[-1]["raised_ms"],
                        "span_min": round(span_ms / 60000.0, 1),
                        "count": len(sids),
                    },
                    "shared_code": str(rep0.get("alarmcode") or "") if shared_code else None,
                    "shared_problem": key,
                    "eflow_impact": None,
                },
                "confidence": round(min(0.90,
                    0.4 + (0.15 if len(sids) >= 3 else 0.0)
                    + (0.20 if shared_code else 0.0)
                    + (0.15 if span_ms <= TIME_WINDOW_MS else 0.0)), 2),
            }
            cluster["root"]["alarms"] = [
                {
                    "alarm_title": r.get("alarm_title") or "",
                    "alarmcode": r.get("alarmcode") or "",
                    "severity": r.get("severity") or "",
                    "raised_ms": r.get("raised_ms"),
                }
                for r in (rows_by_site.get(rep_sid) or [])[:ROOT_ALARM_CAP]
            ]
            cluster["root"]["in_scope"] = True
            for m in sids:
                mv = _site_view(m, site_info, rows_by_site.get(m) or [])
                mv.update({
                    "in_scope": True,
                    "alarm_count": len(rows_by_site.get(m) or []),
                    "tt_id": next((str(r.get("tt_id")) for r in rows_by_site[m] if r.get("tt_id")), ""),
                    "link_path": str(first_alarm.get(m, {}).get("link_path") or ""),
                    "transmission_type": str(first_alarm.get(m, {}).get("transmission_type") or ""),
                })
                cluster["members"].append(mv)
            clusters.append(cluster)
            covered_sids.update(sids)

    # ---- 算法 C：eFlow 佐证（impact_site_list 命中簇成员则提升置信度）----
    impact_rows = [
        r for r in rca_rows
        if str(r.get("impact_site_list") or "").strip() not in ("", "--")
    ]
    matched_impact_rows = 0
    for cluster in clusters:
        member_sids = {m["site_id"] for m in cluster["members"]}
        member_names = {_norm_name(m["site_name"]) for m in cluster["members"]}
        root_impacts = [
            r for r in impact_rows
            if str(r.get("site_id") or "") == cluster["root"]["site_id"]
        ]
        if not root_impacts:
            continue
        matched_members: Set[str] = set()
        best_impact: Optional[Dict] = None
        for r in root_impacts:
            sids_c, names_c = _parse_impact(str(r.get("impact_site_list") or ""))
            hit = {s for s in sids_c if s in member_sids} | {
                m for m in member_sids
                if _norm_name(next((x["site_name"] for x in cluster["members"] if x["site_id"] == m), "")) in
                {_norm_name(n) for n in names_c}
            }
            if hit:
                matched_members |= hit
                matched_impact_rows += 1
                best_impact = best_impact or {
                    "impact_site_number": r.get("impact_site_number"),
                    "impact_site_list": str(r.get("impact_site_list") or ""),
                    "matched_members": sorted(hit),
                }
        if best_impact:
            cluster["evidence"]["eflow_impact"] = best_impact
            cluster["confidence"] = round(
                min(0.95 if cluster["kind"] == "topology" else 0.90,
                    cluster["confidence"] + 0.2), 2)
    meta["eflow_root_unmatched"] = len(impact_rows) - matched_impact_rows

    # ---- 汇总 ----
    clusters.sort(key=lambda c: (-c["member_count"], -c["confidence"]))
    truncated = len(clusters) > CLUSTER_LIMIT
    meta.update(
        with_link_path=with_link_path,
        satellite_sites=len(in_scope_alarm) - with_link_path,
        covered_sites=len(covered_sids & in_scope_alarm),
        uncovered_sites=len(in_scope_alarm) - len(covered_sids & in_scope_alarm),
        topology_clusters=sum(1 for c in clusters if c["kind"] == "topology"),
        same_cause_clusters=sum(1 for c in clusters if c["kind"] == "same_cause"),
        truncated=truncated,
    )
    # 未归因站 id 清单（2026-10-21b）：路由层据此从同一份 rca_rows 里挑出
    # 未归因站的**告警明细行**（uncovered_alarm_rows，弹窗直接用项目默认
    # 告警明细列渲染）。排序保证同输入同输出（快照内可复现）。
    meta["uncovered_site_ids"] = sorted(in_scope_alarm - covered_sids)
    return {"clusters": clusters[:CLUSTER_LIMIT], "meta": meta}


def _time_window_of(rows: List[Dict]) -> Optional[Dict[str, Any]]:
    """一批站点首警行 → {start_ms, end_ms, span_min, count}；无有效时间返回 None。"""
    times = sorted(r.get("raised_ms") for r in rows if r.get("raised_ms"))
    if not times:
        return None
    return {
        "start_ms": times[0],
        "end_ms": times[-1],
        "span_min": round((times[-1] - times[0]) / 60000.0, 1),
        "count": len(times),
    }


# ==================== LLM 叙事（降级模式与 alarm_attribution_service 一致） ====================

def local_summary(result: Dict[str, Any], lang: str = "zh") -> str:
    """本地规则结论：无 LLM 时的降级路径，也是喂给 LLM 的事实底稿。

    只复述确定性聚类结果（簇数、Top 根因、影响面），绝不添加推断。
    """
    clusters = result.get("clusters") or []
    meta = result.get("meta") or {}
    is_en = (lang or "zh").lower() == "en"
    if not clusters:
        return ("No active alarms to aggregate." if is_en
                else "当前没有可聚合的活跃告警。")
    lines: List[str] = []
    if is_en:
        lines.append(
            f"Root cause aggregation over {meta.get('in_scope_sites', 0)} alarmed "
            f"site(s) in scope ({meta.get('alarm_rows', 0)} alarms): "
            f"{meta.get('topology_clusters', 0)} topology cluster(s), "
            f"{meta.get('same_cause_clusters', 0)} same-cause cluster(s)."
        )
        for c in clusters[:5]:
            root = c.get("root") or {}
            lines.append(
                f"- [{c.get('kind')}] {root.get('site_name')}: cause={c.get('cause_type')}, "
                f"{c.get('member_count')} downstream site(s) affected, "
                f"confidence={c.get('confidence')}."
            )
        lines.append("(Deterministic clustering only; not interpreted by AI.)")
    else:
        lines.append(
            f"对筛选范围内 {meta.get('in_scope_sites', 0)} 个告警站"
            f"（{meta.get('alarm_rows', 0)} 条告警）聚合出："
            f"拓扑根因簇 {meta.get('topology_clusters', 0)} 个、"
            f"同因聚集簇 {meta.get('same_cause_clusters', 0)} 个。"
        )
        for c in clusters[:5]:
            root = c.get("root") or {}
            lines.append(
                f"- [{c.get('kind')}] {root.get('site_name')}："
                f"疑似根因类型 {c.get('cause_type')}，"
                f"影响 {c.get('member_count')} 站，置信度 {c.get('confidence')}。"
            )
        lines.append("（以上为确定性聚类结果，未经过 AI 解读。）")
    return "\n".join(lines)


def build_prompt(result: Dict[str, Any], lang: str = "zh") -> str:
    """把聚类事实拼成提示词。

    安全考量（沿用 alarm_attribution_service.build_prompt 的约定）：
    **不把原始告警行塞给模型**，只给聚合后的簇级统计 —— 既控制 token，
    也降低「表内数据含指令」的提示注入面。
    """
    is_en = (lang or "zh").lower() == "en"
    facts = local_summary(result, lang=lang)
    if is_en:
        return (
            "You are a telecom NOC analyst. Based on the aggregated root-cause "
            "clusters below, explain the shared root causes of these site outages "
            "and give 3 concrete next actions (e.g. which site to dispatch to "
            "first). Be concise. Do not invent data beyond the clusters given.\n\n"
            f"CLUSTERS:\n{facts}"
        )
    return (
        "你是电信网络运维（NOC）分析师。请基于下面的根因聚合簇，说明这批断站"
        "的共同根因，并给出 3 条可执行的下一步动作（例如优先派修哪个根因站）。"
        "要求简洁、直接，**不要编造簇里没有的数据**。\n\n"
        f"聚类事实：\n{facts}"
    )


def rca_narrative(result: Dict[str, Any], provider: str = "local", api_key: str = "",
                  model: str = "", base_url: str = "", lang: str = "zh") -> Dict[str, Any]:
    """LLM 叙事入口：确定性结果由服务端算好传入，模型只做解释；不可用即降级。

    返回 {analysis, provider, note?}；analysis 恒有值（最坏是 local_summary），
    调用方无需为 AI 可用性写分支。
    """
    summary = local_summary(result, lang=lang)
    base: Dict[str, Any] = {"analysis": summary, "provider": "local"}

    provider = (provider or "local").lower()
    if provider == "local" or not api_key:
        return base

    prompt = build_prompt(result, lang=lang)
    try:
        # 复用 alarm_attribution_service 的分发与自建端点能力（不重复实现，
        # 也避免 import incident_ai_service 的路径在这里再写一遍）。
        from backend.services.alarm_attribution_service import _call_openai_compatible
        if base_url:
            payload, status = _call_openai_compatible(provider, api_key, model, prompt, base_url)
        else:
            from backend.services import incident_ai_service as ai_svc
            payload, status = ai_svc.dispatch(
                provider, {"api_key": api_key, "prompt": prompt, "model": model}
            )
        if status != 200 or not payload.get("analysis"):
            raise RuntimeError(payload.get("error") or f"status={status}")
        base["analysis"] = payload["analysis"]
        base["provider"] = provider
    except Exception as e:  # noqa: BLE001
        # 降级约定与 alarm_attribution_service.attribute 一致：本地结论 + note，
        # 而不是把错误抛给用户。
        logger.warning("[gis-rca] AI 调用失败，回退本地规则: %s", e)
        base["note"] = f"AI 调用失败，已回退本地规则：{e}"
    return base
