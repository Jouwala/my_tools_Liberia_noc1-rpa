# -*- coding: utf-8 -*-
"""NL2SQL 输出提取的回归测试。

对应 2026-10-05 真实故障：用户问「查找告警已经清除后派单的TT」，
界面报 `错误: 语法错误 在 "AND" 或附近的 LINE 5: AND created_time > alarm_clear_time`。

根因：`_extract_sql` 用 `\\b(select|with)\\b` 在**全文**找语句起点，
而 `with` 是普通英文词 —— 模型前置解释里的 `with` 被当成 SQL 开头，
散文被截成「SQL」并通过了 `SELECT|WITH` 白名单，直到执行才炸。

这些用例是**确定性**的：直接把模型输出喂给提取函数，不需要联网。
"""
import pytest

from backend.services.nl2sql_service import _extract_sql


def test_fence_wins_over_prose_containing_with():
    """回归：前置解释含英文 'with' + 代码围栏 —— 必须取围栏内的 SQL。

    这是线上故障的最小复现。
    """
    raw = (
        "I will build this by joining tickets with their alarm records.\n\n"
        "```sql\n"
        "SELECT wo_no, created_time, alarm_clear_time\n"
        "FROM eflow_wo\n"
        "WHERE created_time > alarm_clear_time\n"
        "LIMIT 1000\n"
        "```"
    )
    out = _extract_sql(raw)
    assert out.lower().startswith("select"), out
    assert "I will build this" not in out
    assert "their alarm records" not in out
    assert "eflow_wo" in out


def test_no_fence_anchors_on_line_start_not_prose():
    """无围栏：整行以 SELECT 开头的那一行才是语句起点。"""
    raw = (
        "To find tickets created with cleared alarms, run this:\n"
        "SELECT wo_no FROM eflow_wo WHERE created_time > alarm_clear_time"
    )
    out = _extract_sql(raw)
    assert out.startswith("SELECT wo_no")
    assert "To find tickets" not in out


def test_trailing_prose_is_not_glued_onto_sql():
    """围栏后的悬空散文不能粘进 SQL —— 正是它变成了 'AND created_time > ...'。"""
    raw = (
        "```sql\n"
        "SELECT site_name, COUNT(*) AS c FROM eflow_tt GROUP BY site_name LIMIT 10\n"
        "```\n"
        "AND created_time > alarm_clear_time"
    )
    out = _extract_sql(raw)
    assert "AND created_time" not in out
    assert out.lower().endswith("limit 10")


def test_cte_with_recursive_is_recognized():
    """真 CTE（with x as (…)）必须被识别为语句起点。"""
    raw = "Here is the query:\nWITH t AS (SELECT 1 AS a)\nSELECT * FROM t"
    out = _extract_sql(raw)
    assert out.upper().startswith("WITH T AS")
    assert "Here is the query" not in out


def test_prose_with_alone_is_not_treated_as_cte():
    """散文里的 with 不得被当成 CTE 起点（with 后无 `标识符 as (`）。"""
    raw = "Tickets with cleared alarms are listed below.\nSELECT wo_no FROM eflow_wo"
    out = _extract_sql(raw)
    assert out.startswith("SELECT wo_no")
    assert "listed below" not in out


def test_plain_sql_unchanged():
    """本来正常的输出不能被改坏（无回归）。"""
    sql = "SELECT wo_no FROM eflow_wo WHERE created_time > alarm_clear_time LIMIT 1000"
    assert _extract_sql(sql) == sql


def test_trailing_semicolon_stripped():
    raw = "```sql\nSELECT 1;\n```"
    assert _extract_sql(raw) == "SELECT 1"


def test_empty_input():
    assert _extract_sql("") == ""


def test_unfenced_cannot_answer_is_returned_for_guard_to_reject():
    """既无围栏也无行首语句：原样返回，交由 sql_guard 明确拒绝（不猜）。"""
    raw = "CANNOT_ANSWER: schema 里没有清障时间字段"
    out = _extract_sql(raw)
    assert out == raw


@pytest.mark.parametrize(
    "raw",
    [
        # 各种「散文含 with/select 词 + 真 SQL」的组合
        "Note that with the alarm cleared, compare times.\nSELECT a FROM b",
        "Use a join with eflow_tt to get counts.\nselect a from b limit 1",
        "We select rows where cleared.\n```sql\nSELECT 1\n```",
    ],
)
def test_extraction_never_returns_prose_prefix(raw):
    """不变式：提取结果不得以散文开头。"""
    out = _extract_sql(raw)
    low = out.strip().lower()
    assert low.startswith(("select", "with", "cannot_answer")), out
