# -*- coding: utf-8 -*-
"""只读 SQL 护栏测试（Data Agent NL2SQL 原型）。

重点覆盖**绕过尝试** —— 护栏的价值不在于拦住 `DROP TABLE`（谁都会写），
而在于拦住「把关键字藏在字符串/注释里」「多语句拼接」这类真实攻击面。

运行：scripts\\python.exe -m pytest tests\\test_sql_guard.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.sql_guard import (  # noqa: E402
    DEFAULT_LIMIT, MAX_LIMIT, SqlGuardError, enforce_limit, extract_tables, validate_sql,
)

TABLES = ["eflow_tt", "history_alarm", "realtime_alarm", "site_master"]


# ---------------------------------------------------------------- 必须拦截
@pytest.mark.parametrize("label,sql", [
    ("DROP", "DROP TABLE eflow_tt"),
    ("DELETE", "DELETE FROM eflow_tt WHERE 1=1"),
    ("UPDATE", "UPDATE eflow_tt SET title='x'"),
    ("INSERT", "INSERT INTO eflow_tt (title) VALUES ('x')"),
    ("TRUNCATE", "TRUNCATE TABLE eflow_tt"),
    ("ALTER", "ALTER TABLE eflow_tt ADD COLUMN x int"),
    ("GRANT", "GRANT ALL ON eflow_tt TO public"),
    ("多语句", "SELECT 1; DROP TABLE eflow_tt"),
    ("字符串藏分号多语句", "SELECT 'a' AS x FROM eflow_tt; DROP TABLE eflow_tt"),
    ("注释藏分号多语句", "SELECT 1 FROM eflow_tt /* x */; DELETE FROM eflow_tt"),
    ("行注释藏分号多语句", "SELECT 1 FROM eflow_tt -- x\n; DELETE FROM eflow_tt"),
    ("PG读文件", "SELECT pg_read_file('/etc/passwd')"),
    ("COPY", "COPY eflow_tt TO '/tmp/x.csv'"),
    ("schema前缀", "SELECT title FROM app.eflow_tt"),
    ("未知表", "SELECT * FROM secret_table"),
    ("系统表注入", "SELECT 1 FROM eflow_tt UNION SELECT 1 FROM pg_shadow"),
    ("非SELECT起始", "EXPLAIN SELECT 1"),
    ("SET会话", "SET search_path TO public"),
    ("空SQL", "   "),
])
def test_blocked(label, sql):
    with pytest.raises(SqlGuardError):
        validate_sql(sql, TABLES)


# ---------------------------------------------------------------- 必须放行
@pytest.mark.parametrize("label,sql,tables", [
    ("简单SELECT", "SELECT title, status FROM eflow_tt", ["eflow_tt"]),
    ("带WHERE", "SELECT * FROM eflow_tt WHERE site_name = 'x'", ["eflow_tt"]),
    ("聚合", "SELECT status, COUNT(*) FROM eflow_tt GROUP BY status", ["eflow_tt"]),
    ("JOIN", "SELECT a.title FROM eflow_tt a JOIN site_master b ON a.id=b.id",
     ["eflow_tt", "site_master"]),
    ("CTE", "WITH t AS (SELECT * FROM eflow_tt) SELECT COUNT(*) FROM t", ["eflow_tt"]),
    ("子查询", "SELECT * FROM (SELECT * FROM eflow_tt) s", ["eflow_tt"]),
    # 字面量**内部**的关键字/分号无副作用，必须放行。
    # 这是本护栏与「朴素黑名单」的关键区别，见 sql_guard.py 模块 docstring。
    ("字符串含分号关键字", "SELECT 'a; DROP TABLE eflow_tt' AS x FROM eflow_tt", ["eflow_tt"]),
    ("注释含关键字", "SELECT 1 /* DELETE FROM eflow_tt */ FROM eflow_tt", ["eflow_tt"]),
    ("字符串字面量含双写引号", "SELECT 'it''s ok' AS x FROM eflow_tt", ["eflow_tt"]),
])
def test_allowed(label, sql, tables):
    cleaned, referenced = validate_sql(sql, TABLES)
    assert [t.lower() for t in referenced] == [t.lower() for t in tables], label
    assert cleaned


def test_cte_alias_not_treated_as_table():
    """CTE 别名不是真实表，不应出现在引用清单里（否则会被表白名单误拒）。"""
    assert extract_tables("WITH t AS (SELECT * FROM eflow_tt) SELECT * FROM t") == ["eflow_tt"]


# ---------------------------------------------------------------- LIMIT
def test_limit_injected_when_missing():
    out = enforce_limit("SELECT * FROM eflow_tt", limit=50)
    assert "LIMIT 50" in out


def test_limit_preserved_when_present():
    sql = "SELECT * FROM eflow_tt LIMIT 10"
    assert enforce_limit(sql, limit=50) == sql


def test_oversized_limit_capped_not_rejected():
    """超上限的 LIMIT 收敛为 MAX_LIMIT。

    2026-10-05 行为变更：此前抛 SqlGuardError，导致介于 DEFAULT_LIMIT 与 MAX_LIMIT
    之间的值既不被收敛、也不会触发截断标记，形成静默灰区。现改为「一律压到
    MAX_LIMIT」，请求值与护栏上限始终自洽。上限本身同日由 1000 放宽到 50000。
    """
    out = enforce_limit("SELECT * FROM eflow_tt LIMIT 999999999")
    assert f"LIMIT {MAX_LIMIT}" in out
    assert "999999999" not in out


def test_midrange_limit_tightened_to_max_consistently():
    """中间值 LIMIT 不再被原样放行 —— 与超限值走同一条收敛路径。"""
    assert enforce_limit(f"SELECT * FROM eflow_tt LIMIT {MAX_LIMIT}") == \
        f"SELECT * FROM eflow_tt LIMIT {MAX_LIMIT}"
    assert f"LIMIT {MAX_LIMIT}" in enforce_limit(f"SELECT * FROM eflow_tt LIMIT {MAX_LIMIT + 1}")


def test_limit_capped_at_max():
    out = enforce_limit("SELECT * FROM eflow_tt", limit=10 ** 9)
    assert f"LIMIT {MAX_LIMIT}" in out


def test_default_limit_is_generous():
    """默认上限应足够宽松（2026-10-05 用户反馈 200 太紧）。

    这条断言是**防回退**的：若有人把上限调回小数值，正常查询会重新开始频繁触顶，
    而用户已经明确表示「数据不会导出很大、不需要限制 200」。
    """
    assert DEFAULT_LIMIT >= 10000, f"默认上限 {DEFAULT_LIMIT} 过小，会让正常查询频繁触顶"
    assert DEFAULT_LIMIT == MAX_LIMIT, "默认值与最大值应一致，避免再出现静默灰区"
