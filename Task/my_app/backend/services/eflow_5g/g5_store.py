# -*- coding: utf-8 -*-
"""5G 站点告警派单的**状态表**读写（`eflow_5g_assign_log`）。

## 为什么需要这张表

任务按分钟轮询实时告警，同一条未清除的 5G 告警会反复被扫到。没有状态表就会
**每轮重复派单**（同一告警建出一堆 TT）。本表用 `alarm_key`（上游告警唯一键）
做主键，记录每条告警的处理结果：

* `assign_status` —— 'Y' = 已确认派单成功（TT 建出）/ 'N' = 失败 /
  'S' = 跳过（站点已有 99933 或不满足派单条件）/ 'D' = 演练模式（未真派）；
* `tt_no` / `tt_proc_id` —— 派出的 TT 标识（回查得到才写，绝不伪造）；
* `site_id` / `site_name` —— 解析出的派单站点（便于排障「为何这条没派」）；
* `cell_name` —— 告警小区名（5G 特有：一站多小区去重时要看清楚是哪几个小区）；
* `skip_reason` —— 跳过的原因（关联 99933、站点解析失败等）；
* `send_status` —— WhatsApp 通报是否已确认送达（'Y'/'N'）；
* `first_seen_time` / `last_seen_time` / `updated_time` —— 生命周期。

## 与 Fiber 表的关系

表结构与 `eflow_fiber_assign_log` **一致**（多一个 `cell_name`），但
**表名独立** —— 两套派单是两条独立业务线（告警码、目标组、群组、合并判据
都可能不同），共用一张表会让「哪条告警归谁」变得不可查。

## 幂等建表

与 `ume_alarm_store` / `tt_alarm_store` / `fiber_store` 同源做法：
`CREATE TABLE IF NOT EXISTS` + 幂等补列 + PG 补主键约束 + 建索引，
四件事缺一不可，不进 Alembic。
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable

logger = logging.getLogger("eflow_5g_store")

LOG_TABLE = "eflow_5g_assign_log"
LOG_PK = ("alarm_key",)

LOG_COLUMNS = (
    "alarm_key", "alarm_id", "alarm_code", "site_id", "site_name",
    "cell_name", "me_name", "occur_time",
    "assign_status", "tt_no", "tt_proc_id", "skip_reason", "last_error",
    "send_status", "send_time",
    "first_seen_time", "last_seen_time", "updated_time",
)

COLUMN_TYPES: Dict[str, str] = {}  # 全 TEXT

ENSURE_COLUMNS = tuple(c for c in LOG_COLUMNS if c not in LOG_PK)


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite(conn):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def _build_create_sql(table: str) -> str:
    defs = []
    for col in LOG_COLUMNS:
        col_type = COLUMN_TYPES.get(col, "TEXT")
        if col in LOG_PK:
            defs.append(f"    {col} {col_type} PRIMARY KEY")
        else:
            defs.append(f"    {col} {col_type}")
    return f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(defs) + "\n)"


def _ensure_pk_constraint(conn, table: str) -> None:
    """给已存在的老表幂等补主键约束（仅 PG；sqlite 建表即带）。"""
    if _is_sqlite(conn):
        return
    try:
        rows = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey) "
            "WHERE t.relname = ? AND i.indisunique AND i.indisvalid "
            "AND i.indpred IS NULL AND i.indexprs IS NULL",
            (table,),
        ).fetchall()
        if any(r[0] == LOG_PK[0] for r in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_pk PRIMARY KEY ({LOG_PK[0]})")
        conn.commit()
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg:
            return
        logger.warning("补 %s 主键约束失败（忽略）: %s", table, e)


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 补列 + 补主键 + 建索引（sqlite / PG 双模）。"""
    conn.execute(_build_create_sql(table))
    present = _existing_columns(conn, table)
    for col in ENSURE_COLUMNS:
        if col in present:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {COLUMN_TYPES.get(col, 'TEXT')}")
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                continue
            raise
    _ensure_pk_constraint(conn, table)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_status "
        f"ON {table} (assign_status, updated_time)"
    )
    conn.commit()


def load_records(conn, alarm_keys: Iterable[str], table: str = LOG_TABLE) -> Dict[str, Dict[str, Any]]:
    """按 alarm_key 批量读记录（分块避开 IN 变量上限）。"""
    keys = [k for k in alarm_keys if k]
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(keys), 200):
        chunk = keys[i:i + 200]
        marks = ",".join("?" * len(chunk))
        cols = ", ".join(LOG_COLUMNS)
        for row in conn.execute(f"SELECT {cols} FROM {table} WHERE alarm_key IN ({marks})",
                                tuple(chunk)).fetchall():
            rec = dict(zip(LOG_COLUMNS, row))
            out[str(rec.get("alarm_key"))] = rec
    return out


def upsert_record(conn, rec: Dict[str, Any], table: str = LOG_TABLE) -> None:
    """按主键 upsert 一条记录（sqlite / PG 双模，走 dialect_helpers.upsert）。

    `upsert` 用 INSERT OR REPLACE / ON CONFLICT DO UPDATE 全列覆盖，若某轮只传
    部分列会把其余列写成 NULL。故先读已有行合并，再写回 —— 保证「只更状态」
    的调用不会冲掉 `tt_no` / `first_seen_time` 等既有字段。
    """
    from backend.dialect_helpers import upsert
    key = rec.get(LOG_PK[0])
    merged = {col: None for col in LOG_COLUMNS}
    if key:
        existing = load_records(conn, [key], table).get(str(key))
        if existing:
            merged.update(existing)
    merged.update({k: v for k, v in rec.items() if k in merged})
    merged["updated_time"] = _now()
    upsert(conn, table, [merged], list(LOG_PK))
    conn.commit()
