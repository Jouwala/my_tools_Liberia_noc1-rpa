# -*- coding: utf-8 -*-
"""eflow_push_rule_eval.py - 推单规则的批量求值
================================================

从 `eflow_push_rules_checker.py` 拆出（AGENTS.md 三.2：单文件不超过 500 行）。

本模块把 `eflow_push_rules.xlsx` 的 FOAccept 推单规则套到一批 eflow_tt 上，
逐行给出「命中了哪条规则」。**不引入第二套规则语义**：

  · 条件解析   —— `tt_rule_evidence._parse_push_conditions`（推单表条件列格式归一）
  · 条件求值   —— `eflow_rules_matcher.build_value_frame` / `build_rule_mask` / `format_details`
  · 规则字段   —— `tt_rule_evidence._push_rule_block`
  · 未知字段   —— `tt_postmortem._rule_wants_keys` + `_ticket_signature`（判断「可能适用」的范围）

与单 TT 版 `tt_rule_evidence.build_push_rule_evidence` 的判定顺序一致：
优先级升序 → 条件数降序 → ID 升序，取第一条为「实际生效」的推单规则。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 决定「FO 接单时是否自动建 WO / 推给谁」的触发步骤
# （与 tt_rule_evidence._PUSH_DECISION_STEP / tt_postmortem._analyze_dispatch_reason 同一口径）
DECISION_STEP = "FOAccept"


def _s(v: Any) -> str:
    """pandas / numpy 标量 → 干净字符串（NaN / None / NaT → 空串）。"""
    if v is None:
        return ""
    try:
        import pandas as pd
        if v is pd.NaT:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
    except Exception:  # noqa: BLE001
        pass
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


# ------------------------------------------------------------------ #
# 单条规则的求值
# ------------------------------------------------------------------ #

def _prepare_rule(rec: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """规则表一行 → 求值用的结构；条件全空或无法解析则返回 None。

    `unknown_fields` 非空表示这条规则引用了本地取不到的字段 ——
    它对**本批样本**无法判定，不能算「未命中」（tt_rule_evidence.md 第 2 条坑）。
    """
    from backend.services.eflow_rules import tt_rule_evidence as E
    from backend.services.eflow_rules import eflow_rules_matcher as M

    conds = E._parse_push_conditions(rec.get("条件") or "")
    if not conds:
        return None
    unknown = sorted({c["field"] for c in conds if c["field"] not in _KNOWN_FIELDS})
    blk = E._push_rule_block(rec, "")
    try:
        pri = int(float(_s(rec.get("优先级")) or 999))
    except (TypeError, ValueError):
        pri = 999
    return {
        "conds": conds,
        "unknown_fields": unknown,
        "block": blk,
        "priority": pri,
        "step": _s(rec.get("触发步骤")),
    }


# `eflow_rules_matcher.build_value_frame` 实际产出的列（eflow_rules_matcher.py:229-285）。
# 注意 siteSubType / assetType / downstreamSites 在某些站点查不到时会**为空值** ——
# 那是「数据缺失导致条件不成立」，条件求值本身能跑，所以仍算已知字段，
# 不进 unknown_fields；只有这里没列出的字段才算「本地无法判定」。
_KNOWN_FIELDS = {
    "alarmCode", "vipSite", "hubSite", "siteSubType", "assetType",
    "netWorkType", "downSiteCount", "alarmDescription", "downstreamSites",
}


def evaluate_rules(rules: List[Dict[str, Any]], vf, records: Sequence[Dict[str, Any]],
                   attrs: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """对一张 `build_value_frame` 结果跑全部 FOAccept 规则。

    返回：
      hits         每行的命中结果（长度 = len(vf)），元素为 None 或 dict
      per_rule     每条 FOAccept 规则 → 命中数 / 状态（含 undecidable / error）
      undecidable  每行是否落在「引用未知字段规则的可能范围内」（Series[bool]）

    判定规则与单 TT 版一致：同一行可能命中多条，取「优先级最小 → 条件数最多 → ID 最小」
    的第一条作为**实际生效**的推单规则（tt_rule_evidence.build_push_rule_evidence:485-492）。
    """
    import pandas as pd
    from backend.services.eflow_rules import eflow_rules_matcher as M
    from backend.services.eflow_rules import tt_rule_evidence as E
    from backend.services.tt_postmortem import _rule_wants_keys, _ticket_signature

    idx = vf.index
    n = len(idx)
    hits: List[Optional[Dict[str, Any]]] = [None] * n
    per_rule: List[Dict[str, Any]] = []

    # 判定顺序：优先级升序 → 条件数降序 → ID 升序（与 prepare_rules 同思路）
    ordered = sorted(
        [r for r in rules if r["step"] == DECISION_STEP],
        key=lambda r: (r["priority"], -len(r["conds"]), _s(r["block"].get("rule_id"))),
    )

    for rule in ordered:
        blk = rule["block"]
        rid = _s(blk.get("rule_id"))
        if rule["unknown_fields"]:
            # 无法在本地评估：不影响其它规则，单独记账（下面再算「可能范围」）
            per_rule.append({
                "rule_id": rid, "rule_name": _s(blk.get("rule_name")),
                "priority": rule["priority"], "status": "undecidable",
                "matched": 0, "unknown_fields": list(rule["unknown_fields"]),
                "trigger_step": _s(blk.get("trigger_step")),
                "push_path": _s(blk.get("push_path")),
                "target_handler": _s(blk.get("target_handler")),
                "auto_operator": _s(blk.get("auto_operator")),
                "built_wo": _rule_builds_wo(blk),
            })
            continue
        try:
            mask = M.build_rule_mask(vf, rule["conds"]).fillna(False).astype(bool)
        except Exception as e:  # noqa: BLE001
            logger.warning("推单规则 %s 求值失败：%s", rid, e)
            per_rule.append({
                "rule_id": rid, "rule_name": _s(blk.get("rule_name")),
                "priority": rule["priority"], "status": "error",
                "matched": 0, "unknown_fields": [],
                "trigger_step": _s(blk.get("trigger_step")),
                "push_path": _s(blk.get("push_path")),
                "target_handler": _s(blk.get("target_handler")),
                "auto_operator": _s(blk.get("auto_operator")),
                "built_wo": _rule_builds_wo(blk),
            })
            continue

        matched_count = int(mask.sum())
        per_rule.append({
            "rule_id": rid, "rule_name": _s(blk.get("rule_name")),
            "priority": rule["priority"],
            "status": "active" if matched_count else "no_hit",
            "matched": matched_count, "unknown_fields": [],
            "trigger_step": _s(blk.get("trigger_step")),
            "push_path": _s(blk.get("push_path")),
            "target_handler": _s(blk.get("target_handler")),
            "auto_operator": _s(blk.get("auto_operator")),
            "built_wo": _rule_builds_wo(blk),
        })
        if not matched_count:
            continue

        # 只给「还没被更高优先级规则认领」的行填结果
        free = mask & pd.Series([h is None for h in hits], index=idx)
        if not free.any():
            continue
        details = M.format_details(vf, rule["conds"]).fillna("")
        for pos in free[free].index:
            loc = idx.get_loc(pos)
            hits[loc] = {
                "rule_id": rid,
                "rule_name": _s(blk.get("rule_name")),
                "priority": rule["priority"],
                "trigger_step": _s(blk.get("trigger_step")),
                "push_path": _s(blk.get("push_path")),
                "auto_operator": _s(blk.get("auto_operator")),
                "target_handler": _s(blk.get("target_handler")),
                "built_wo": _rule_builds_wo(blk),
                "evidence": _s(details.iloc[loc]),
            }

    # ---- 未知字段规则的「可能范围」----
    # 这些规则本地判不了（缺 alarmName / category 等列），但它们的**适用对象**往往
    # 从规则名/描述就能看出来（「微波告警推单给WO」只管微波类单）。
    # 做法：用 tt_postmortem 已有的特征词推断（_rule_wants_keys + _ticket_signature），
    # 只把「特征吻合且尚未被任何已知规则命中」的行标成 undecidable。
    #
    # 为什么不保守地整批标 undecidable：那样这张卡会吃掉几乎所有未命中行，
    # 让「工具能力缺口」看起来像「规则覆盖问题」，比漏判更误导使用者。
    # 推断不出特征（wants 为空）时仍偏向保守 —— 不标，但该规则会在
    # missing_fields 告警里列出，提示需要人工核对。
    undecidable = pd.Series(False, index=idx)
    any_hit = pd.Series([h is not None for h in hits], index=idx)
    for rule in ordered:
        if not rule["unknown_fields"]:
            continue
        wants = _rule_wants_keys({"rule_name": rule["block"].get("rule_name"),
                                  "description": rule["block"].get("description")})
        if not wants:
            continue
        possible = pd.Series(True, index=idx)
        for loc_i, rec in enumerate(records):
            sid = _s(rec.get("site_id"))
            site = (attrs or {}).get(sid) or {}
            sig = _ticket_signature(rec, site.get("siteSubType") or rec.get("site_type"))
            if not all(sig.get(k) for k in wants):
                possible.iloc[loc_i] = False
        undecidable = undecidable | (possible & ~any_hit)

    return {"hits": hits, "per_rule": per_rule, "undecidable": undecidable}


def _rule_builds_wo(blk: Dict[str, Any]) -> bool:
    """这条规则会不会产生现场 WO？

    ⚠ 2026-10-23 修正（业务方明确口径：**推给 IPT 的不建 WO，只有给 ZTE 的才建 WO**）。

    旧实现只要推送路径里**出现过** FOProcess 就判定建 WO，于是：
      · 规则 200「Regular电源故障推送TT到**IPT**」（`FOAccept>FOProcess>ThirdAccept`，
        目标 `3rd_Power`）被判成该建 WO —— 它实际是转第三方，不建 WO。
        338 张单全部误判成 mismatch，占当时全部 mismatch 的 2/3。
      · 规则 240「Vmax-TT-order-push-rule」（`FOAccept>FOProcess`，目标 `SOC-CEM`）
        同样无 WO，若按「路径终止段」判也会误判。

    最终判据改为看**目标处理人是否属于 ZTE**（实测四类规则 100% 吻合）：
      · 目标 `ZTE_NOC_FO` / `ZTE_FE_*` 等 ZTE 组 → 建 WO（203/204：命中单 100% 有 wo_no）
      · 目标 `3rd_Power`（IPT）/ `SOC-CEM` 等非 ZTE 组 → 不建 WO（200/240：100% 无 wo_no）

    路径不参与判定：规则 240 的路径与 203/204 形态相近（只到 FOProcess），
    但目标组不同，结果就不同 —— 说明真正起作用的是**推给谁**，不是经过哪些节点。
    """
    target = _s(blk.get("target_handler"))
    if not target:
        # 无目标处理人时无法判断；复用推送路径的保守口径：只有明确终止于 FOProcess 才算
        path = _s(blk.get("push_path"))
        segs = [p.strip() for p in re.split(r"\s*>\s*", path) if p.strip()]
        if len(segs) < 2:
            return False
        return segs[-1].split(",")[0].split()[0].lower() == "foprocess"
    # `ZTE_NOC_FO [ZTE_NOC_FO]` → 取方括号前的组名；`ZTE_FE_FE(group)` → 取括号前
    name = target.split("[")[0].split("(")[0].strip().upper()
    return name.startswith("ZTE")


_RULES_CACHE: Dict[str, Any] = {"key": None, "rows": []}


def load_push_rules(xlsx_path) -> List[Dict[str, str]]:
    """读 `eflow_push_rules.xlsx` 中 **ACTIVE** 的 ttPushOrderRule 行，按 mtime 缓存。

    与 `tt_rule_evidence.build_push_rule_evidence` 的筛选条件完全一致
    （tt_rule_evidence.py:447-449），保证单 TT 分析与本批量检查看到同一批规则。
    """
    from pathlib import Path
    from backend.services.eflow_rules import tt_rule_evidence as E

    path = Path(xlsx_path)
    try:
        mtime = path.stat().st_mtime
    except OSError as e:
        raise RuntimeError(f"推单规则文件不可用：{path}（{e}）") from e
    if _RULES_CACHE["key"] == mtime and _RULES_CACHE["rows"]:
        return _RULES_CACHE["rows"]

    rows = [r for r in E._load_push_rule_rows()
            if _s(r.get("规则类型")) == "ttPushOrderRule"
            and _s(r.get("状态")).upper() == "ACTIVE"]
    _RULES_CACHE.update({"key": mtime, "rows": rows})
    return rows


def prepare_rule(rec: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """规则表一行 → 求值用的结构（条件全空或无法解析时返回 None）。"""
    return _prepare_rule(rec)
