# -*- coding: utf-8 -*-
"""整表替换 DDL 的 **schema 限定**守卫（2026-10-15 事故回归）。

事故：``eflow_active_alarm`` 每分钟的换表用裸表名，PG 的 ``DROP`` 会顺着
``search_path``（``app,eflow,lte_pl,…``，见 ``database._PsycopgRaw._SEARCH_PATH``）
逐级往下找 —— 当 ``eflow.realtime_alarm`` 不存在时，"写 eflow 副本"的那条
``DROP TABLE IF EXISTS "realtime_alarm"`` 命中并删掉了 **app.realtime_alarm**，
而紧随其后的 app 侧换表又反向删掉 eflow 那份。两份同名表每分钟互相抹一次，
实测 ``app.realtime_alarm`` 每分钟消失约 0.14s，期间库里只剩 36 列的过滤版副本。
后果：任务 ``tt_alarm_whatsapp_alert`` 报「realtime_alarm 表不存在或缺少
tt_id/alarmraisedtime 列」，同时所有读该表的接口（如 ``/api/gis/sites``）
重新暴露在这次的空窗下 —— 2026-09-29 那次「影子表 + 单条 DO 块原子换表」
的修复被跨 schema DROP 绕过了。

本文件锁两件事：
  1. 换表 SQL 必须带 schema 限定（裸名即回归）；
  2. 触发扫描的存在性/列判断只认归属 schema，不取 search_path 全 schema 并集
     （并集会被那份没有 tt_id 的 36 列副本污染）。
"""
import pytest

from backend.services import tt_alarm_trigger as T
from backend.services.eflow_alarm_service import _swap_table_sql

_TBL = "realtime_alarm"
_STG = "realtime_alarm__staging"


@pytest.mark.parametrize("schema", ["app", "eflow"])
def test_pg_swap_drops_only_its_own_schema(schema):
    sql = _swap_table_sql(_TBL, _STG, pg=True, schema=schema)
    assert f'DROP TABLE IF EXISTS "{schema}"."{_TBL}"' in sql, sql
    assert f'ALTER TABLE "{schema}"."{_STG}" RENAME TO "{_TBL}"' in sql, sql
    # 裸名 DROP / 裸名影子表都是本次事故的形态，不允许回归
    assert 'DROP TABLE IF EXISTS "realtime_alarm";' not in sql, sql
    assert f'ALTER TABLE "{_STG}"' not in sql, sql
    # 必须是单条语句（2026-09-29 的约束仍然有效：拆两条在 autocommit 下仍有空窗）
    assert sql.startswith("DO $$ BEGIN") and sql.endswith("END $$"), sql


def test_sqlite_swap_keeps_bare_names():
    """SQLite 没有 schema 概念，限定名会让它去找一个叫 app 的库/attach 名。"""
    assert _swap_table_sql(_TBL, _STG, pg=False) is None


class _FakePgCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakePgConn:
    """非 sqlite3.Connection 即被 _is_sqlite/_is_pg_conn 判成 PG；记录 SQL 与参数。"""

    def __init__(self, rows=()):
        self.calls = []
        self._rows = list(rows)

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _FakePgCursor(self._rows)


def test_table_exists_pins_trigger_schema():
    conn = _FakePgConn(rows=[("realtime_alarm",)])
    assert T._table_exists(conn, _TBL) is True
    sql, params = conn.calls[-1]
    assert "current_schemas" not in sql, "跨 schema 并集判断会让 eflow 副本污染结论"
    assert params == (_TBL, T.TRIGGER_SCHEMA), params


def test_available_columns_pins_trigger_schema():
    conn = _FakePgConn(rows=[("tt_id",), ("alarmraisedtime",)])
    cols = T._available_columns(conn, _TBL)
    sql, params = conn.calls[-1]
    assert "current_schemas" not in sql, sql
    assert params == (_TBL, T.TRIGGER_SCHEMA), params
    assert "tt_id" in cols and "alarmraisedtime" in cols


def test_trigger_schema_defaults_to_app():
    """默认必须指向同步任务的写入目标（app 库）；换部署可用 TT_TRIGGER_SCHEMA 覆盖。"""
    assert T.TRIGGER_SCHEMA == "app"
