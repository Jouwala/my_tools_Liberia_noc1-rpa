# -*- coding: utf-8 -*-
"""TT/WO 看板 Ticket Severity 统计口径回归测试。"""

from backend.routers.tt_wo_dashboard import _ticket_severity_key


def test_unknown_ticket_severity_is_excluded_case_insensitively():
    """Unknown 的大小写变体均不应生成统计键。"""
    assert _ticket_severity_key("unknown") is None
    assert _ticket_severity_key(" UNKNOWN ") is None
    assert _ticket_severity_key("Unknown") is None


def test_historical_misspelling_unkonw_is_excluded():
    """数据库历史误拼写 unkonw 也不能出现在 Ticket Severity 统计中。"""
    assert _ticket_severity_key("unkonw") is None
    assert _ticket_severity_key(" UNKONW ") is None


def test_real_ticket_severity_is_preserved():
    """真实级别仍保持原始展示值。"""
    assert _ticket_severity_key("P1") == "P1"
    assert _ticket_severity_key(" P2 ") == "P2"
