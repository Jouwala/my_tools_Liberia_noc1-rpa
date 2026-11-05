# -*- coding: utf-8 -*-
"""「系统名不是数据值」守卫的回归测试。

对应 2026-11-04 真实故障：用户问「my_app 的 task manager 有多少任务成功，多少失败」，
机器人答「查询执行成功，但没有匹配到任何记录」。

根因：模型把 **my_app**（系统名）当成了要过滤的数据值，生成
    WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'
而 `task_execution_log.task_name` 存的是中文任务名（"eFlow 实时告警同步"…），
没有一条含 "my_app" → 命中 0 行。**库里明明有 3 万多条执行记录。**

这些用例是**确定性**的：不联网、不调模型，只测纯函数。

运行：.venv\\Scripts\\python.exe -m pytest tests\\test_nl2sql_system_name_guard.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.nl2sql_service import (  # noqa: E402
    _SYSTEM_NAME_TOKENS,
    detect_system_name_filter,
    strip_system_name_filters,
)


# ---------------------------------------------------------------- 检测：必须命中
@pytest.mark.parametrize("sql,expected_cols", [
    # 线上故障的原始形态
    ("SELECT task_id FROM task_execution_log "
     "WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'",
     ["task_id", "task_name"]),
    ("SELECT 1 FROM t WHERE site_name = 'my_app'", ["site_name"]),
    ("SELECT 1 FROM t WHERE c = 'my app'", ["c"]),
    ("SELECT 1 FROM t WHERE c ILIKE '%task manager%'", ["c"]),
    ("SELECT 1 FROM t WHERE c = 'data_insight'", ["c"]),
    ("SELECT 1 FROM t WHERE c ILIKE '%kb bot%'", ["c"]),
    # 分隔符变体：my-app / MyApp 都算同一个词
    ("SELECT 1 FROM t WHERE c = 'my-app'", ["c"]),
    ("SELECT 1 FROM t WHERE c = 'MyApp'", ["c"]),
])
def test_detects_system_name_filter(sql, expected_cols):
    assert detect_system_name_filter(sql) == expected_cols


# ---------------------------------------------------------------- 检测：绝不能误伤
@pytest.mark.parametrize("sql", [
    # ⚠️ eflow / whatsapp 是数据里的**真值**，不是系统名 ——
    #    task_name 有 12192 行含 "eflow"，category 有 20408 行等于 "whatsapp"。
    #    收录进词表就会误伤正常查询。
    "SELECT 1 FROM task_execution_log WHERE task_name ILIKE '%eflow%'",
    "SELECT 1 FROM task_execution_log WHERE category = 'whatsapp'",
    # 载荷列里出现 my_app 是正常的（任务返回体带自己的模块名）
    "SELECT 1 FROM task_execution_log WHERE result_json ILIKE '%my_app%'",
    "SELECT 1 FROM task_execution_log WHERE error ILIKE '%my_app%'",
    "SELECT 1 FROM eflow_wo WHERE description ILIKE '%my_app%'",
    # 真实站名 / 真实值
    "SELECT 1 FROM eflow_site WHERE site_name ILIKE '%Wood Camp%'",
    "SELECT 1 FROM eflow_wo WHERE status = 'Closed'",
    # 只是**包含**系统名，不是整个值 —— 那是别的词
    "SELECT 1 FROM t WHERE c ILIKE '%my_app_task%'",
    "SELECT 1 FROM t WHERE c ILIKE '%my_application%'",
    # 数字比较不应被当成字符串比较
    "SELECT 1 FROM t WHERE success = 1",
])
def test_does_not_flag_normal_queries(sql):
    assert detect_system_name_filter(sql) == []


def test_token_list_excludes_real_data_values():
    """词表里不能出现 'eflow' / 'whatsapp' —— 它们是数据里的真值。"""
    norm = {t.lower().replace("_", "").replace(" ", "") for t in _SYSTEM_NAME_TOKENS}
    assert "eflow" not in norm
    assert "whatsapp" not in norm


# ---------------------------------------------------------------- 剥离：语义必须正确
def test_strip_removes_whole_where_when_all_branches_are_system_filters():
    """所有分支都是系统名过滤 → 整个 WHERE 没有贡献 → 删掉整个子句。

    这正是线上故障的形态：删掉 WHERE 后查询回到「统计全部任务」，
    命中 3 万多行，而不是 0 行。
    """
    sql = ("SELECT task_id, count(*) FROM task_execution_log "
           "WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%' "
           "GROUP BY task_id LIMIT 1000")
    out = strip_system_name_filters(sql)
    assert "my_app" not in out.lower()
    assert "WHERE" not in out.upper()
    # 后面的子句必须完整保留
    assert "GROUP BY task_id" in out
    assert "LIMIT 1000" in out


def test_strip_keeps_real_conditions_alongside():
    """真实条件必须原样保留 —— 只删被污染的那一项。"""
    sql = ("SELECT 1 FROM t "
           "WHERE success = 1 AND task_name ILIKE '%my_app%'")
    out = strip_system_name_filters(sql)
    assert "my_app" not in out.lower()
    assert "success = 1" in out
    assert "WHERE" in out.upper()


def test_strip_keeps_real_site_condition():
    sql = ("SELECT 1 FROM eflow_site "
           "WHERE site_name = 'Wood Camp' AND task_id ILIKE '%my_app%'")
    out = strip_system_name_filters(sql)
    assert "Wood Camp" in out
    assert "my_app" not in out.lower()


def test_strip_leaves_normal_sql_untouched():
    """没有系统名过滤时，一个字都不能改。

    ⚠️ 这条不变量很重要：守卫如果"顺手"改了格式（哪怕只是多一个尾随空格），
    用户核对 SQL 时就看不出到底改了什么，守卫也就失去了可审计性。
    """
    sql = ("SELECT site_name, count(*) FROM eflow_site "
           "WHERE site_name = 'Wood Camp' GROUP BY site_name LIMIT 100")
    assert strip_system_name_filters(sql) == sql


@pytest.mark.parametrize("sql", [
    # eflow / whatsapp 是数据里的真值 —— 一个字都不能动
    "SELECT task_name, count(*) FROM task_execution_log "
    "WHERE task_name ILIKE '%eFlow%' GROUP BY task_name LIMIT 100",
    "SELECT category, count(*) FROM task_execution_log "
    "WHERE category = 'whatsapp' GROUP BY category LIMIT 100",
    # 载荷列里的 my_app 合法
    "SELECT count(*) FROM task_execution_log WHERE result_json ILIKE '%my_app%'",
    # 真实条件
    "SELECT site_name, count(*) FROM eflow_site "
    "WHERE site_name ILIKE '%Wood Camp%' GROUP BY site_name LIMIT 100",
    "SELECT count(*) FROM eflow_wo WHERE status = 'Closed'",
    "SELECT count(*) FROM eflow_wo WHERE created_time >= '2026-01-01' AND status = 'Open'",
    # 只是包含，不是整个值
    "SELECT count(*) FROM t WHERE c ILIKE '%my_app_task%'",
])
def test_strip_is_byte_identical_on_normal_sql(sql):
    """正常 SQL 必须**逐字节**不变 —— 守卫不得引入任何格式改动。"""
    assert strip_system_name_filters(sql) == sql


def test_strip_preserves_or_branches_that_are_real():
    """OR 分支里有真条件时，真分支必须留下。"""
    sql = ("SELECT 1 FROM t "
           "WHERE site_name = 'Wood Camp' OR task_name ILIKE '%my_app%'")
    out = strip_system_name_filters(sql)
    assert "Wood Camp" in out
    assert "my_app" not in out.lower()


def test_strip_handles_nested_parentheses():
    """括号内的 AND/OR 不应被当成顶层切分点。"""
    sql = ("SELECT 1 FROM t "
           "WHERE (site_name = 'Wood Camp' AND status = 'Closed') "
           "AND task_id ILIKE '%my_app%'")
    out = strip_system_name_filters(sql)
    assert "Wood Camp" in out
    assert "Closed" in out
    assert "my_app" not in out.lower()


def test_strip_ignores_string_literal_containing_and_or():
    """字符串字面量里的 ' AND ' 不能被当成顶层关键字。"""
    sql = ("SELECT 1 FROM t "
           "WHERE title = 'A AND B' AND task_id ILIKE '%my_app%'")
    out = strip_system_name_filters(sql)
    assert "A AND B" in out
    assert "my_app" not in out.lower()


def test_strip_handles_subquery_where():
    """子查询里的 WHERE 不是顶层 —— 不该被误拆。"""
    sql = ("SELECT 1 FROM t WHERE id IN "
           "(SELECT id FROM u WHERE name = 'my_app') AND x = 1")
    out = strip_system_name_filters(sql)
    # 子查询里的系统名过滤保留不了（它是真的在过滤子查询），
    # 但**顶层** WHERE 必须完好 —— x = 1 不能丢
    assert "x = 1" in out
