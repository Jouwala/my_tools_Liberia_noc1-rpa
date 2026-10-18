# -*- coding: utf-8 -*-
"""SP 未关闭单口径守卫（pytest，无副作用、不碰生产数据）。

## 为什么有这个测试

2026-10-18 查明：「SPMS 未关闭」这个数字在三个页面各算一遍，其中两处用
`COUNT(*)` 数**明细行**，而 inband/outband_details 是「一单多物料多行」的表。
实测 23 行未关闭只对应 12 张不同的单 —— 用户看到「23」会当成 23 张单。

本测试钉死三件事，防止口径再次分叉：

1. `sp_common` 的纯函数口径（词表、归一化、空值、在途态）正确。
2. `portal_qc` 的**大数字与下钻行数相等** —— 这是用户能直接看到的自洽性，
   曾经坏过（23 vs 23 行内容不同粒度的假自洽）。
3. `sp_report_service` 的卡片口径走的是同一个去重函数（静态断言 import）。

不连生产库：第 2 条用内存 SQLite 造两张小表。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from backend.services import sp_common

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 纯函数口径
# 注意语义：True = **未关闭**（函数名 is_open_status 指 open 单）。
@pytest.mark.parametrize("value,expected", [
    ("Closed", False),
    ("closed", False),
    ("CLOSED", False),
    ("WaitingForReturn", True),
    ("WaitingForConfirm", True),
    ("  WaitingForReturn  ", True),       # 前后空白要归一化
    ("", False),                          # 空状态不算未关闭
    (None, False),
    ("nan", False),                       # pandas 读出来的 NaN
    ("WaitingForUpdate", False),          # 在途态，默认剔除
])
def test_is_open_status(value, expected):
    assert sp_common.is_open_status(value) is expected


def test_ignored_words_are_parted_from_open():
    """在途态必须同时出现在「忽略」与「非未关闭」两套名单里，不能漏进 closed 名单。"""
    for word in sp_common.SP_IGNORED_WORDS:
        assert word in sp_common.SP_NOT_OPEN_WORDS
        assert word not in sp_common.SP_CLOSED_WORDS


def test_open_predicate_sql_has_no_percent():
    """GET 连接包装层会把字面 % 转成 %% —— 谓词里出现 % 会静默改变语义。"""
    sql = sp_common.open_predicate_sql('"Status"')
    assert "%" not in sql
    assert "NOT IN" in sql


def test_open_predicate_ignore_words_override():
    """传 () 表示「只按 closed 词表判」—— 供原始快照语义显式选择。"""
    with_ignore = sp_common.open_predicate_sql('"Status"')
    without = sp_common.open_predicate_sql('"Status"', ignore_words=())
    assert "waitingforupdate" in with_ignore
    assert "waitingforupdate" not in without


# ---------------------------------------------------- 按单据号去重（内存 SQLite）
def _make_db() -> sqlite3.Connection:
    """造一张模拟 outband_details：同一张 SPOB-1 有 3 行物料。"""
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE outband_details ("Outbound No." TEXT, "Status" TEXT)')
    conn.executemany(
        'INSERT INTO outband_details VALUES (?, ?)',
        [
            ("SPOB-1", "WaitingForReturn"),   # 一单三物料 → 应算 1
            ("SPOB-1", "WaitingForReturn"),
            ("SPOB-1", "WaitingForReturn"),
            ("SPOB-2", "WaitingForConfirm"),  # 应算 1
            ("SPOB-3", "Closed"),             # 已关闭 → 不算
            ("SPOB-4", "WaitingForUpdate"),   # 在途态 → 默认不算
            ("SPOB-5", ""),                   # 空状态 → 不算
            (None, "WaitingForConfirm"),      # 无单号 → 无法定位单据，不算
        ],
    )
    return conn


def test_count_open_docs_is_deduped():
    conn = _make_db()
    assert sp_common.count_open_docs(conn, "outband_details") == 2
    conn.close()


def test_open_doc_numbers_matches_count():
    conn = _make_db()
    docs = sp_common.open_doc_numbers(conn, "outband_details")
    assert docs == ["SPOB-1", "SPOB-2"]
    assert len(docs) == sp_common.count_open_docs(conn, "outband_details")
    conn.close()


def test_count_open_docs_rows_dedupes_python_rows():
    """Excel 解析出来的行（Python 侧）必须与 SQL 侧同一个答案。"""
    rows = [
        ["SPOB-1", "WaitingForReturn"],
        ["SPOB-1", "WaitingForReturn"],
        ["SPOB-2", "WaitingForConfirm"],
        ["SPOB-3", "Closed"],
        ["SPOB-4", "WaitingForUpdate"],
    ]
    # status_idx=1, doc_idx=0
    assert sp_common.count_open_docs_rows(rows, 1, 0) == 2
    # ignore_statuses=False 时 WaitingForUpdate 要计入 → 3
    assert sp_common.count_open_docs_rows(rows, 1, 0, ignore_statuses=False) == 3


# --------------------------------- portal_qc 大数字 == 下钻行数（用户可见的自洽）
def test_portal_qc_spms_summary_equals_drill_total(monkeypatch):
    """SPMS 大数字（按单去重）必须等于下钻子查询的行数。

    这正是用户报的诉求：面板写 23、下钻 23 行，但两者粒度不同。现在两处都
    按单号聚合，数字必须逐条相等。
    """
    from backend.routers import portal_qc

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # portal_qc 需要这两张表；inband 留空以聚焦 outbound
    conn.execute('CREATE TABLE inband_details ("Inbound No." TEXT, "Status" TEXT, '
                 '"Material No." TEXT, "Material Name" TEXT, "Inbound Qty" TEXT, '
                 '"Warehouse Name" TEXT, "Create Time" TEXT, "Closed Time" TEXT)')
    conn.execute('CREATE TABLE outband_details ("Outbound No." TEXT, "Status" TEXT, '
                 '"Material No." TEXT, "Material Name" TEXT, "Outbound Qty" TEXT, '
                 '"Warehouse Name" TEXT, "Create Time" TEXT, "Closed Time" TEXT)')
    conn.executemany(
        'INSERT INTO outband_details VALUES (?,?,?,?,?,?,?,?)',
        [
            ("SPOB-1", "WaitingForReturn", "M1", "AAPL", "1", "W1", "2026-10-16 10:00:00", None),
            ("SPOB-1", "WaitingForReturn", "M1", "AAPL", "2", "W1", "2026-10-16 10:00:00", None),
            ("SPOB-1", "WaitingForReturn", "M2", "BBBB", "1", "W1", "2026-10-16 10:00:00", None),
            ("SPOB-2", "WaitingForConfirm", "M3", "CCCC", "1", "W1", "2026-10-15 09:00:00", None),
            ("SPOB-3", "Closed", "M4", "DDDD", "1", "W1", "2026-10-14 08:00:00", "2026-10-14 09:00:00"),
        ],
    )

    # 两张表都存在 → 不必走 table_columns 探测；但仍让探测器正常工作
    monkeypatch.setattr(portal_qc, "_sp_status_column", lambda c, t: "Status")

    total, detail = portal_qc._sp_open_counts(conn)
    assert total == 2, f"大数字应按单去重=2，实际 {total}（detail={detail}）"
    assert detail["outband_details"] == 2
    assert detail["inband_details"] == 0

    src, where, params = portal_qc._detail_source(conn, "spms")
    drill_total = conn.execute(
        f"SELECT COUNT(*) FROM {src} WHERE {where}", params
    ).fetchone()[0]
    assert drill_total == total, (
        f"下钻行数({drill_total}) 必须等于大数字({total}) —— "
        "否则用户在弹窗里数出来的行数与卡片对不上"
    )
    conn.close()


# ------------------------------------------- sp_report 走同一个去重函数（静态断言）
def test_sp_report_service_uses_shared_dedup():
    """sp_report 卡片口径必须来自 sp_common，不得再自己数行。"""
    src = (PROJECT_ROOT / "backend" / "services" / "sp_report_service.py").read_text(encoding="utf-8")
    assert "count_open_docs_rows" in src, "sp_report_service 应使用 sp_common.count_open_docs_rows"
    # 旧的「按行数」写法若复活，这里会命中
    assert not re.search(r"open_count\s*=\s*sum\(", src), \
        "sp_report_service 不应再出现 open_count = sum(...) 的按行计数"


def test_portal_qc_uses_shared_dedup():
    """portal_qc 的大数字必须走 sp_common.count_open_docs（COUNT DISTINCT）。"""
    src = (PROJECT_ROOT / "backend" / "routers" / "portal_qc.py").read_text(encoding="utf-8")
    assert "_sp.count_open_docs" in src
