# -*- coding: utf-8 -*-
"""TT/WO 看板「Ticket Severity / SLA 状态」排除 Unknown 的口径回归测试。

背景（2026-09-29 业务要求）：page=tt 的 Ticket Severity 与 SLA 状态两个维度
都不得统计、也不得显示 Unknown（含历史误拼写 unkonw）。空值由 ``_safe_str``
归并为字面量 'Unknown'，因此「空」与「真的写着 unknown」必须被一并拦截。
"""

from backend.routers.tt_wo_dashboard import (
    _EXCLUDED_SLA_STATUSES,
    _EXCLUDED_TICKET_SEVERITIES,
    _UNKNOWN_EXCLUDED_DIMENSIONS,
    _stat_key,
    _ticket_severity_key,
)


# ---------------- Ticket Severity ----------------

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


def test_empty_ticket_severity_is_excluded():
    """NULL / 空串 / 'None' 经 _safe_str 归并为 'Unknown'，同样被排除。"""
    assert _ticket_severity_key(None) is None
    assert _ticket_severity_key("") is None
    assert _ticket_severity_key("   ") is None
    assert _ticket_severity_key("None") is None


# ---------------- SLA 状态 ----------------

def test_empty_sla_status_is_excluded():
    """JOIN 不上关联 TT、或 TT 未算 SLA 的空值不再单独成 'Unknown' 一类。

    回归锁：此前 ``_safe_str`` 把 NULL/空串/'None' 归并为 'Unknown' 并计入
    sla_stats，看板上因此多出一张 Unknown 卡（2026-09-29 实测 8 条）。
    """
    assert _stat_key(None, _EXCLUDED_SLA_STATUSES, join_empty=True) is None
    assert _stat_key("", _EXCLUDED_SLA_STATUSES, join_empty=True) is None
    assert _stat_key("None", _EXCLUDED_SLA_STATUSES, join_empty=True) is None
    assert _stat_key("UNKNOWN", _EXCLUDED_SLA_STATUSES, join_empty=True) is None
    assert _stat_key("unkonw", _EXCLUDED_SLA_STATUSES, join_empty=True) is None


def test_real_sla_status_is_preserved():
    """Pass / Failed / Within SLA 等真实取值不受影响。"""
    for v in ("Pass", "Failed", "Within SLA"):
        assert _stat_key(v, _EXCLUDED_SLA_STATUSES, join_empty=True) == v


def test_exclusion_sets_are_consistent():
    """两个维度共用同一套排除语义，避免口径分叉。"""
    assert _EXCLUDED_TICKET_SEVERITIES == _EXCLUDED_SLA_STATUSES


def test_excluded_dimensions_cover_both():
    """已剔除 Unknown 的维度集合必须同时含两个维度（下钻据此返回空集）。"""
    assert _UNKNOWN_EXCLUDED_DIMENSIONS == frozenset({"ticket_severity", "sla_status"})
