"""方言无关助手（sqlite / pg 双模）。

设计原则
--------
调用方（服务 / 路由）继续保持 sqlite 原生写法：``?`` 占位符 +
``conn.execute(sql, params).fetchall()``。PG 模式下由 ``backend.database``
的 ``_PsycopgRaw`` 在连接层把 ``?`` 转成 ``%s`` 并暴露同构接口，本模块
**只负责方言耦合**的部分：

* 表枚举（sqlite_master  ↔ information_schema）
* 列枚举（PRAGMA table_info ↔ information_schema.columns）
* 调优类 PRAGMA（PG 无等价物，静默跳过）
* upsert（INSERT OR REPLACE ↔ INSERT ... ON CONFLICT）
* DataFrame 写入（pandas to_sql，走 SQLAlchemy 引擎）

判定方式：``isinstance(conn, sqlite3.Connection)`` 走 sqlite 分支，否则走 PG
分支。这样服务/路由代码无需 import DB_MODE，纯靠连接对象类型分派。
"""
import sqlite3

from backend.database import engine  # SQLAlchemy 引擎（双模），供 write_df / to_sql 使用


def list_table_names(conn):
    """当前连接可见的基表名（list，按名）。"""
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [r[0] for r in cur.fetchall()]
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(current_schemas(false)) AND table_type='BASE TABLE'"
    )
    return [r[0] for r in cur.fetchall()]


def table_columns(conn, table):
    """表列名（list，按定义顺序）。"""
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = ANY(current_schemas(false)) ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def safe_pragma(conn, stmt):
    """仅 sqlite 执行 PRAGMA（调优类：busy_timeout / WAL / synchronous 等）。

    PG 无等价物，静默跳过。返回 cursor 或 None。
    """
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(stmt)
    return None


def upsert(conn, table, rows, conflict_cols):
    """批量 upsert。rows: list[dict]。

    sqlite: ``INSERT OR REPLACE``；pg: ``INSERT ... ON CONFLICT (conflict_cols) DO UPDATE``。
    返回写入行数。
    """
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" * len(cols))
    col_sql = ", ".join(cols)
    if isinstance(conn, sqlite3.Connection):
        sql = f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})"
        for r in rows:
            conn.execute(sql, [r[c] for c in cols])
        conn.commit()
        return len(rows)
    conflict_sql = ", ".join(conflict_cols)
    set_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in conflict_cols)
    sql = (
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {set_sql}"
    )
    for r in rows:
        conn.execute(sql, [r[c] for c in cols])
    conn.commit()
    return len(rows)


def write_df(df, table, engine_override=None, if_exists="append", index=False):
    """DataFrame 写入表（双模，走 SQLAlchemy 引擎）。

    engine_override 不传时用全局 engine（= app.db / 默认 PG schema）。
    写非 app 库时由调用方传入对应 engine。
    """
    eng = engine_override or engine
    df.to_sql(table, eng, if_exists=if_exists, index=index)
    return len(df)
