# -*- coding: utf-8 -*-
"""推单规则「是否产生 WO」判定的回归测试（**纯离线**：不读数据库、不读 xlsx、不联网）。

背景（2026-10-23 业务方明确口径）
--------------------------------
**推给 IPT 的不建 WO，只有推给 ZTE 的才建 WO。**

旧实现 `_rule_builds_wo` 只看「推送路径里是否出现过 FOProcess」，
于是规则 200「Regular电源故障推送TT到IPT」——路径 `FOAccept>FOProcess>ThirdAccept`、
目标 `3rd_Power`——被判成「应该建 WO」。它命中的 338 张单实际全部没有 wo_no，
因此全部落入 mismatch/should_have_wo，占当时全部 mismatch 的 2/3（510 条里的 338 条）。

判据最终改为**看目标处理人是否属于 ZTE 组**，理由是实测四类规则完全吻合：

| 规则 | 目标处理人          | 命中数 | 有 wo_no |
| ---- | ------------------- | ------ | -------- |
| 203  | ZTE_NOC_FO(group)   | 175    | 175 (100%) |
| 204  | ZTE_NOC_FO(group)   | 102    | 102 (100%) |
| 200  | 3rd_Power(group)    | 338    | 0 (0%)   |
| 240  | SOC-CEM(group)      | 172    | 0 (0%)   |

注意规则 240 的推送路径与 203/204 形态相近（都只到 FOProcess），
但目标组不同、结果就不同 —— 这正说明起作用的是「推给谁」而不是「经过哪些节点」。
按路径终止段判定会把它误判成建 WO，所以这里钉死按目标处理人判定。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.eflow_rules.eflow_push_rule_eval import _rule_builds_wo  # noqa: E402


# ------------------------------------------------------------------ #
# 目标处理人决定是否建 WO
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("target,expected", [
    # ZTE 组 → 建 WO（实测 203/204 命中单 100% 有 wo_no）
    ("ZTE_NOC_FO(group)", True),
    ("ZTE_FE_FE(group)", True),
    ("ZTE_BO_MW(group)", True),
    ("ZTE_BO_OCS-VAS(group)", True),
    # 多目标里含 ZTE → 建 WO（规则 201：ZTE_FE_FE; ZTE_NOC_FO）
    ("ZTE_FE_FE(group); ZTE_NOC_FO(group)", True),
    # 非 ZTE 组 → 不建 WO（实测 200 = 0%，240 = 0%）
    ("3rd_Power(group)", False),      # 规则 200：推 IPT
    ("SOC-CEM(group)", False),        # 规则 240
    ("WH_MG(group)", False),
    # 人员 + 非 ZTE 组 → 不建 WO
    ("GORSON PRINCE T(person); WH_KP(group)", False),
])
def test_target_handler_decides_wo(target, expected):
    """目标处理人是否 ZTE 决定是否建 WO —— 这是唯一判据。"""
    assert _rule_builds_wo({"target_handler": target, "push_path": ""}) is expected


def test_ipt_rule_200_does_not_build_wo():
    """规则 200 的完整形态：转第三方 IPT，即使路径经过 FOProcess 也不建 WO。

    这是本次修复的核心场景 —— 修复前它被判成 built_wo=True，
    导致 338 张正常单被误报为「该建 WO 却没建」。
    """
    blk = {
        "rule_name": "Regular电源故障推送TT到IPT",
        "push_path": "FOAccept,2>FOProcess,5>ThirdAccept",
        "target_handler": "3rd_Power(group)",
    }
    assert _rule_builds_wo(blk) is False


def test_zte_wo_rule_203_builds_wo():
    """规则 203 的完整形态：推 ZTE 建 WO（对照组）。"""
    blk = {
        "rule_name": "ERA断站推单到ZTE WO",
        "push_path": "FOAccept,2>FOProcess,8>FOProcess",
        "target_handler": "ZTE_NOC_FO(group)",
    }
    assert _rule_builds_wo(blk) is True


def test_path_is_not_the_criterion():
    """同样的推送路径、不同目标组 → 判定必须不同。

    规则 240 与 203/204 路径形态相近（都终止于 FOProcess），
    但 240 推的是 SOC-CEM（非 ZTE），实际 172 张单全部无 wo_no。
    若哪天有人把判据改回「看路径」，这条会立刻失败。
    """
    path = "FOAccept,2>FOProcess,8>FOProcess"
    assert _rule_builds_wo({"target_handler": "ZTE_NOC_FO(group)", "push_path": path}) is True
    assert _rule_builds_wo({"target_handler": "SOC-CEM(group)", "push_path": path}) is False


# ------------------------------------------------------------------ #
# 无目标处理人时的兜底
# ------------------------------------------------------------------ #

def test_no_target_falls_back_to_path():
    """没有目标处理人时回退到路径判断（保守口径：只有终止于 FOProcess 才算建 WO）。"""
    assert _rule_builds_wo({"target_handler": "", "push_path": "FOAccept,2>FOProcess,8>FOProcess"}) is True
    assert _rule_builds_wo({"target_handler": "", "push_path": "FOAccept,2>FOProcess,5>ThirdAccept"}) is False


def test_empty_rule_does_not_build_wo():
    """空块（无目标、无路径）不应判成建 WO。"""
    assert _rule_builds_wo({}) is False
    assert _rule_builds_wo({"target_handler": "", "push_path": ""}) is False


def test_only_fo_accept_does_not_build_wo():
    """路径只有 FOAccept 一段（无后续）→ 不建 WO。"""
    assert _rule_builds_wo({"target_handler": "", "push_path": "FOAccept"}) is False
