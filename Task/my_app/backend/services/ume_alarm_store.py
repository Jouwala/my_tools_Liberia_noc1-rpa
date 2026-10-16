# -*- coding: utf-8 -*-
"""ZTE UME 告警推送的**状态表**读写（`ume_alarm_whatsapp_log`）。

## 为什么另起一张表、不复用 `tt_alarm_store`

`tt_alarm_store` 的表结构是给 eFlow **工单（TT）语义**定制的：主键 `tt_no`、
`last_tt_modified`、`mail_notified_time` / `mail_summary_time` 这些列在 UME 告警上
没有对应概念。硬套会把「TT」语义泄漏进告警层（`AGENTS.md` 第三节第 1、3 条）。
本表的业务模型更简单也更明确：

  * 主键 `alarm_key`（= 上游 `alarmId`）—— 一条告警一行；
  * `first_seen_time` 首次出现时间；
  * `send_status` / `send_count` / `last_send_time` —— 首推与催报的节流基准；
  * `cleared_time` —— 告警消失的时间；非空即「已恢复通知已发/待发」的幂等键；
  * `recover_notified` —— 恢复通知发没发的幂等键（'Y'/'N'）。

## 幂等建表（沿用项目既有做法，不进 Alembic）

`CREATE TABLE IF NOT EXISTS` + 幂等补列 + 补主键约束三件事缺一不可，
与 `tt_alarm_store` 同源（那里有 2026-10-06 / 10-07 两次事故的完整记录）：
  * `CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op，**不会补列**；
  * `ON CONFLICT (col)` 在没有唯一约束的老库上会直接报错。

故这里同样把「建表列集合」作为**单一事实来源**：补列清单 = 建表列去掉主键，
加列只需改 `LOG_COLUMNS` 一处。

## send_status 语义（铁律，沿用 `tt_alarm_store`）

只有推送进程**确认投递成功后**才写 `'Y'`；超时/失败一律 `'N'` 并把原因写进
`last_error`。绝不伪造成功。
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from backend.dialect_helpers import upsert

logger = logging.getLogger("ume_alarm_store")

LOG_TABLE = "ume_alarm_whatsapp_log"

# 主键列（不参与补列，建表时即存在）
LOG_PK = ("alarm_key",)

# 日志表列（upsert 与 SELECT 共用，避免两处列名分叉）
LOG_COLUMNS = (
    "alarm_key", "alarm_id", "alarm_code", "level", "object", "occur_time",
    "description", "location",
    # 发送状态
    "send_status", "send_count", "last_send_time", "last_error",
    # bootstrap 标记：'Y' = 首轮只登记、不上报的历史存量（永不补发首推）
    "bootstrapped",
    # 跟踪 / 生命周期
    "first_seen_time", "last_seen_time", "cleared_time",
    # 恢复通知幂等键
    "recover_notified", "recover_time",
    "updated_time",
)

# 列类型映射（建表与补列共用；缺省 TEXT）。除 send_count 外全 TEXT。
COLUMN_TYPES = {"send_count": "INTEGER"}

# 需要向老表补齐的列全集：建表列 - 主键（单一事实来源）
ENSURE_COLUMNS = tuple(c for c in LOG_COLUMNS if c not in LOG_PK)


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _pk_constraint_name(table: str) -> str:
    """PG 约束名按表名派生（同 schema 内唯一），不能写成固定常量。"""
    return f"{table}_pk"


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite(conn):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def _pk_covered(conn, table: str) -> set:
    """该表「主键或唯一约束」已覆盖的列集合（sqlite / PG 双模）。"""
    covered: set = set()
    try:
        if _is_sqlite(conn):
            for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
                if not row[2]:
                    continue
                cols = [r[2] for r in
                        conn.execute(f"PRAGMA index_info({row[1]})").fetchall()]
                if len(cols) == 1:
                    covered.update(cols)
            return covered
        rows = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey) "
            "WHERE t.relname = ? AND i.indisunique AND i.indisvalid "
            "AND i.indpred IS NULL AND i.indexprs IS NULL",
            (table,),
        ).fetchall()
        covered.update(r[0] for r in rows)
    except Exception as e:  # noqa: BLE001
        logger.debug("读取 %s 唯一约束失败（将尝试补约束）: %s", table, e)
    return covered


def _ensure_pk_constraint(conn, table: str) -> bool:
    """给已存在的老表幂等补主键约束（仅 PG；sqlite 建表即带）。"""
    if _is_sqlite(conn):
        return False
    want = tuple(LOG_PK)
    if all(c in _pk_covered(conn, table) for c in want):
        return False
    pk_col = want[0]
    dup = conn.execute(
        f"SELECT {pk_col}, COUNT(*) AS c FROM {table} "
        f"WHERE {pk_col} IS NOT NULL GROUP BY {pk_col} HAVING COUNT(*) > 1 LIMIT 5"
    ).fetchall()
    nulls = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {pk_col} IS NULL"
    ).fetchone()[0]
    if dup or nulls:
        raise RuntimeError(
            f"{table} 无法补主键：{pk_col} 存在 {len(dup)} 组重复值、{nulls} 个 NULL。"
            f"重复样本={[r[0] for r in dup]}。请人工裁决（切勿自动删行）。"
        )
    try:
        conn.execute(f"ALTER TABLE {table} ADD CONSTRAINT "
                     f"{_pk_constraint_name(table)} PRIMARY KEY ({pk_col})")
        conn.commit()
        logger.info("%s：已补主键约束 (%s)", table, pk_col)
        return True
    except Exception as e:  # noqa: BLE001
        code = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
        msg = str(e).lower()
        if code == "42710" or "already exists" in msg or "duplicate" in msg:
            return False
        raise


def _ensure_columns(conn, table: str) -> None:
    """幂等补列（补列集合 = 建表列 - 主键）。"""
    present = _existing_columns(conn, table)
    for col in ENSURE_COLUMNS:
        if col in present:
            continue
        col_type = COLUMN_TYPES.get(col, "TEXT")
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception as e:  # noqa: BLE001
            code = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
            msg = str(e).lower()
            if code == "42701" or "already exists" in msg or "duplicate" in msg:
                continue
            raise


def _build_create_sql(table: str) -> str:
    defs = []
    for col in LOG_COLUMNS:
        col_type = COLUMN_TYPES.get(col, "TEXT")
        if col in LOG_PK:
            defs.append(f"    {col} {col_type} PRIMARY KEY")
        else:
            defs.append(f"    {col} {col_type}")
    return f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(defs) + "\n)"


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 补列 + 补主键 + 建索引（sqlite / PG 双模）。"""
    conn.execute(_build_create_sql(table))
    _ensure_columns(conn, table)
    _ensure_pk_constraint(conn, table)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_status "
        f"ON {table} (send_status, last_send_time)"
    )


def load_records(conn, alarm_keys: Iterable[str],
                 table: str = LOG_TABLE) -> Dict[str, Dict[str, Any]]:
    """按 alarm_key 批量读历史记录（分块，避开 IN 子句变量上限）。"""
    keys = [k for k in alarm_keys if k]
    out: Dict[str, Dict[str, Any]] = {}
    cols = ("alarm_key, alarm_code, level, object, occur_time, send_status, "
            "send_count, last_send_time, first_seen_time, last_seen_time, "
            "cleared_time, recover_notified, recover_time, bootstrapped, last_error")
    for i in range(0, len(keys), 200):
        chunk = keys[i:i + 200]
        marks = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT {cols} FROM {table} WHERE alarm_key IN ({marks})",
            tuple(chunk))
        names = [d[0] for d in cur.description]
        for r in cur.fetchall():
            row = dict(zip(names, r))
            out[str(row["alarm_key"])] = row
    return out


def load_open_records(conn, table: str = LOG_TABLE) -> Dict[str, Dict[str, Any]]:
    """读所有「已出现过、尚未标记清除」的记录（用于检测恢复）。

    只取有发送过或有登记的行（send_count>=0 全量），排除已发过恢复通知的。
    """
    cols = ("alarm_key, alarm_code, level, object, occur_time, send_status, "
            "send_count, last_send_time, first_seen_time, last_seen_time, "
            "cleared_time, recover_notified, recover_time, bootstrapped, last_error")
    cur = conn.execute(
        f"SELECT {cols} FROM {table} "
        f"WHERE (cleared_time IS NULL OR cleared_time = '') "
        f"AND (recover_notified IS NULL OR recover_notified <> 'Y')")
    names = [d[0] for d in cur.description]
    return {str(row[0]): dict(zip(names, row)) for row in cur.fetchall()}


def base_record(row: Dict[str, Any],
                existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造一条新记录（保留首见时间、发送计数与恢复幂等键）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ex = existing or {}
    return {
        "alarm_key": str(row.get("alarm_id") or row.get("alarm_key") or ""),
        "alarm_id": row.get("alarm_id"),
        "alarm_code": row.get("alarm_code"),
        "level": row.get("level"),
        "object": row.get("object"),
        "occur_time": row.get("occur_time"),
        "description": row.get("description"),
        "location": row.get("location"),
        "send_status": ex.get("send_status") or "N",
        "send_count": int(ex.get("send_count") or 0),
        "last_send_time": ex.get("last_send_time"),
        "last_error": ex.get("last_error"),
        "bootstrapped": ex.get("bootstrapped") or "N",
        "first_seen_time": ex.get("first_seen_time") or now,
        "last_seen_time": now,
        "cleared_time": ex.get("cleared_time"),
        # 恢复幂等键原样带过来：本表 upsert 是整行覆盖，漏传会把"已发过"抹成 NULL
        "recover_notified": ex.get("recover_notified") or "N",
        "recover_time": ex.get("recover_time"),
        "updated_time": now,
    }


def record_send(conn, row: Dict[str, Any], ok: bool, error: str = "",
                existing: Optional[Dict[str, Any]] = None,
                table: str = LOG_TABLE) -> Dict[str, Any]:
    """写回一条发送结果（upsert by alarm_key）。

    `ok=True` → `send_status='Y'`、`send_count`+1、`last_send_time=now`；
    `ok=False` → `send_status` **保持原值**（一次失败不该把先前成功抹掉），
    `last_error` 记原因。失败不计入 `send_count`。

    `existing` 是上一轮的记录；未提供时按 alarm_key 现查一次，避免整行覆盖时
    把「已发送/已恢复」等幂等列抹掉（同 `tt_alarm_store.record_result` 的教训）。
    """
    if existing is None:
        existing = load_records(conn, [str(row.get("alarm_id") or "")], table).get(
            str(row.get("alarm_id") or ""))
    rec = base_record(row, existing)
    if ok:
        rec["send_status"] = "Y"
        rec["send_count"] = int(rec["send_count"]) + 1
        rec["last_send_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec["last_error"] = ""
    else:
        # 失败不改 send_status（保留先前是否成功），只记错
        rec["last_error"] = str(error or "未确认投递")[:500]
    upsert(conn, table, [rec], ["alarm_key"])
    return rec


def touch_seen(conn, row: Dict[str, Any],
               existing: Optional[Dict[str, Any]] = None,
               table: str = LOG_TABLE) -> None:
    """仅刷新「仍在告警列表中」的登记（不改发送状态、不增计数）。"""
    rec = base_record(row, existing)
    upsert(conn, table, [rec], ["alarm_key"])


def mark_bootstrapped(conn, alarm_key: str, table: str = LOG_TABLE) -> None:
    """标记为「首轮登记的历史存量」——`bootstrapped='Y'`，此后不再补发首推。"""
    conn.execute(
        f"UPDATE {table} SET bootstrapped = 'Y' WHERE alarm_key = ?",
        (str(alarm_key),))
    conn.commit()


def mark_cleared(conn, alarm_key: str, table: str = LOG_TABLE) -> None:
    """把一条记录标为已清除（写 cleared_time）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"UPDATE {table} SET cleared_time = ? WHERE alarm_key = ? "
        f"AND (cleared_time IS NULL OR cleared_time = '')",
        (now, str(alarm_key)))
    conn.commit()


def mark_recover_notified(conn, alarm_key: str, table: str = LOG_TABLE) -> None:
    """标记恢复通知已发出（幂等键，避免重复发）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"UPDATE {table} SET recover_notified = 'Y', recover_time = ? "
        f"WHERE alarm_key = ?",
        (now, str(alarm_key)))
    conn.commit()
