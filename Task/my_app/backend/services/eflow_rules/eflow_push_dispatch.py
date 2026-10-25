# -*- coding: utf-8 -*-
"""eflow_push_dispatch.py - 实际派单结果的解析与「规则 vs 实际」一致性分类
=========================================================================

从 `eflow_push_rules_checker.py` 拆出（原文件超过 AGENTS.md 三.2 的 500 行约定）。
本模块只做两件**确定性**的事，不含任何规则求值逻辑：

  1. `parse_actual_dispatch()` —— 从 eflow_tt 的一行还原「这单实际被派给了谁」；
  2. `classify()`            —— 把「规则判定」与「实际派单」放在一起，给出四类之一。

规则语义仍只由 `eflow_rules_matcher` / `tt_rule_evidence` 决定，本模块不引入第二套判定。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# 四类互斥（求和 = 总数）。顺序即页面统计卡的顺序。
CATEGORIES = ("correct", "mismatch", "undecidable", "unmatched")

# 一致性差异的子类型 → 前端 i18n key 后缀（前端按这个取文案，不动态拼 key）
DIFF_KINDS = (
    "should_have_wo",      # 规则说该建 WO，实际没有 WO 且流程也没到过目标组
    "pushed_elsewhere",    # 规则说推给 A，实际推给了 B
    "unexpected_wo",       # 规则没有要求建 WO，实际却建了
    "both_no_wo",          # 规则没要求 + 实际也没有 —— 一致
    "both_wo",             # 规则要求 + 实际建了（或流程已到过目标组）—— 一致
)


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
# 实际派单结果
# ------------------------------------------------------------------ #

_HANDLER_RE = re.compile(r"Assign To:\s*(.*?)\s*Assignee Group:\s*(.*?)(?:\s*Remark:|$)", re.S)
# Assignee Group 的写法实测有两种（同为 eFlow 导出，格式不统一）：
#   G:ZTE_FE_FE(ZTE_FE_FE)   —— 组名(编码)
#   G:ZTE_NOC_FO             —— 只有组名，**不带括号**
# 只认带括号的写法会漏掉第二种，页面就会把「实际派给 ZTE_NOC_FO」显示成 `—`（2026-10-23 实测）。
_GROUP_RE = re.compile(r"G:([^\s().,;]+)(?:\(([^)]*)\))?")
_PERSON_RE = re.compile(r"P:([^\s().,;]+)(?:\(([^)]*)\))?")

# FO Accept 由机器人代办时，Assignee Group 只是「下一步接手方」，不代表规则没生效
_ROBOT_OPERATORS = ("ferobot", "autorobot")

# eFlow 各流程节点的明细列（找「目标组是否到达过」时全量扫这些列）
STAGE_KEYS = (
    "fo_accept_detail", "fo_process_detail", "bo_accept_detail", "bo_process_detail",
    "third_accept_detail", "third_process_detail", "confirm_detail", "closed_detail",
    "create_detail", "process_description",
)


def _code_of(m: Optional["re.Match[str]"]) -> str:
    """`G:name(code)` / `G:name` → 可读编码（优先括号里的编码，缺省用组名本身）。"""
    if not m:
        return ""
    return (m.group(2) or m.group(1) or "").strip()


def parse_actual_dispatch(rec: Dict[str, Any]) -> Dict[str, Any]:
    """从 eflow_tt 的一行还原「实际派单结果」。

    字段（实测格式，见 eflow_tt.fo_accept_detail 样例）：
      Assign To:P:FE Robot(fe_robot). Assignee Group:G:ZTE_FE_FE(ZTE_FE_FE).
    只解析 FO Accept 环节 —— 那正是推单规则作用的步骤。
    解析不出来时全部留空，页面显示 `—`（AGENTS.md 三.6：取不到不得显示成 0）。
    """
    wo = _s(rec.get("wo_no"))
    detail = _s(rec.get("fo_accept_detail"))
    person, group = "", ""
    m = _HANDLER_RE.search(detail)
    if m:
        person = _code_of(_PERSON_RE.search(m.group(1)))
        group = _code_of(_GROUP_RE.search(m.group(2)))

    op_m = re.search(r"Operator:\s*([^().]*)", detail)
    operator = (op_m.group(1).strip() if op_m else "")
    robot_handled = operator.lower().replace(" ", "") in _ROBOT_OPERATORS

    # 目标组是否**真的走到过**：看所有 *Detail 字段里有没有出现过 `G:<组名>`。
    # 用来区分「规则说该派 A，实际流程到达过 A」与「A 从未出现」——
    # 前者是正常自动派单（只是 wo_no 没写回 TT），后者才是真的没派。
    blob = " ".join(_s(rec.get(k)) for k in STAGE_KEYS)
    return {
        "wo_no": wo,
        "has_wo": bool(wo),
        "dispatch_person": person,
        "dispatch_group": group,
        "operator": operator,
        "robot_handled": robot_handled,
        "stage_blob": blob,
        "parsed": bool(detail),
    }


def group_reached(group_code: str, actual: Dict[str, Any]) -> bool:
    """目标组是否在该单的流程明细里出现过（不论在哪个环节）。

    `3rd_Power` 在 eFlow 里可能写作 `3rd_Power` / `3rd Power`，两种都算。
    """
    g = _s(group_code).lower()
    if not g:
        return False
    blob = (actual.get("stage_blob") or "").lower()
    variants = {g, g.replace("_", " "), g.replace(" ", "_")}
    return any(v in blob for v in variants)


# ------------------------------------------------------------------ #
# 一致性分类
# ------------------------------------------------------------------ #

def classify(hit: Optional[Dict[str, Any]], actual: Dict[str, Any],
             undecidable: bool) -> Tuple[str, str]:
    """(category, diff_kind)。

    category  ∈ CATEGORIES（四类互斥）
    diff_kind ∈ DIFF_KINDS（仅用于明细说明；一致的情形也会给一个 kind）

    为什么不能只看 `wo_no` 是否为空：
      实测 FO Accept 常由 FE Robot 代做、真正的派单结果落在后续环节；
      另有大量单自动派单已发生，但 eFlow 没把 WO 号写回 TT。只看 wo_no
      会把这类正常单全部算成「规则要求建 WO 却没建」（2026-10-23 实测 793 条误报）。
    """
    if undecidable:
        return "undecidable", ""
    if hit is None:
        return "unmatched", ""

    rule_wo = bool(hit.get("built_wo"))
    has_wo = bool(actual.get("has_wo"))

    # 目标处理组（`ZTE_NOC_FO [ZTE_NOC_FO]` → ZTE_NOC_FO）是否在流程里到达过。
    # 只用于「建了 WO 但推给了别的组」这一种判断；**不能用来替代 wo_no**（见下）。
    want = _s(hit.get("target_handler")).split("[")[0].strip()
    reached = group_reached(want, actual) if want else False

    if rule_wo and not has_wo:
        # 规则判定「应建 WO」但实际 `wo_no` 为空 → 确实不一致。
        #
        # ⚠ 2026-10-23 修正口径：本分支**只**应命中「规则本身就该建 WO」的单。
        #   此前规则 200「Regular电源故障推送TT到IPT」被误判为 built_wo=true
        #   （它转给第三方 IPT，本来就不建 WO —— 业务口径：推 IPT 不建 WO，
        #   只有推 ZTE 的才建 WO），于是 338 张正常单全落到这里。
        #   根因在 `eflow_push_rule_eval._rule_builds_wo`：旧实现只看「路径里
        #   出现过 FOProcess」，现已改为看**路径终止段**（ThirdAccept = 转第三方 = 不建 WO）。
        #
        #   建 WO 的判据仍然只能是 `wo_no`：`third_accept_detail` 里出现目标组
        #   只说明「路由到过该组」，不等于产生了现场工单。
        return "mismatch", "should_have_wo"
    if rule_wo and has_wo:
        if not want:
            return "correct", "both_wo"
        if reached or actual.get("robot_handled"):
            return "correct", "both_wo"
        return "mismatch", "pushed_elsewhere"
    if not rule_wo and has_wo:
        return "mismatch", "unexpected_wo"
    return "correct", "both_no_wo"
