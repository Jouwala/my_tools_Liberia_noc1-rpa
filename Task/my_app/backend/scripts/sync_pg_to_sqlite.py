"""PG → SQLite 全量同步脚本

用途：把远程 PostgreSQL (myapp 库) 的所有用户数据同步到本地 SQLite 文件，
     作为离线备份 / 回退快照。

映射规则：
  - PG schema "app"  → db/app.db（表名不变）
  - PG 其它 schema   → db/app.db（表名加 schema 前缀，如 battery.battery_latest → battery_battery_latest）

运行方式：
  python backend/scripts/sync_pg_to_sqlite.py

依赖：
  - psycopg2（PG 模式已安装）
  - 环境变量从 backend/.env 自动加载
"""

import os
import sys
import sqlite3
import time
import logging
from pathlib import Path

# ── 路径 / 环境 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent          # 项目根
sys.path.insert(0, str(ROOT))

# 读 backend/.env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)
except Exception:
    pass

import psycopg2
import psycopg2.extras

# ── 配置 ──────────────────────────────────────────────────────
PG_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH = ROOT / "db" / "app.db"
BATCH_SIZE = 5000  # 每批写入行数

# 需要跳过的系统/元数据表
SKIP_TABLES = {"alembic_version"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pg2sqlite")


# ── 工具函数 ──────────────────────────────────────────────────
def get_pg_tables(conn):
    """获取所有用户表及其 schema，返回 [(schema, table), ...]"""
    cur = conn.cursor()
    cur.execute("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """)
    return cur.fetchall()


def get_pg_columns(conn, schema, table):
    """获取指定表的列信息 [(col_name, data_type), ...]"""
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table))
    return cur.fetchall()


def pg_type_to_sqlite(pg_type: str) -> str:
    """把 PG 数据类型粗映射到 SQLite 类型"""
    t = pg_type.lower()
    if t in ("integer", "bigint", "smallint", "serial", "bigserial"):
        return "INTEGER"
    if t.startswith("numeric") or t in ("real", "double precision", "float"):
        return "REAL"
    if t == "boolean":
        return "INTEGER"
    if t in ("jsonb", "json"):
        return "TEXT"
    if t.startswith("timestamp") or t in ("date", "time"):
        return "TEXT"
    if t in ("bytea",):
        return "BLOB"
    return "TEXT"


def sanitize_table_name(schema: str, table: str) -> str:
    """生成 SQLite 表名：app schema 保持原名，其它加前缀"""
    if schema == "app":
        return table
    return f"{schema}_{table}"


def sync_table(pg_conn, sqlite_conn, schema: str, table: str):
    """同步单张表"""
    sqlite_name = sanitize_table_name(schema, table)

    if table in SKIP_TABLES:
        log.info(f"  跳过（系统表）: {schema}.{table}")
        return 0

    # 1. 读取 PG 列定义
    columns = get_pg_columns(pg_conn, schema, table)
    if not columns:
        log.warning(f"  无列信息: {schema}.{table}，跳过")
        return 0

    col_names_raw = [c[0] for c in columns]
    # PG 可能有仅大小写不同的同名列（如 STATUS / status），SQLite 不区分，需去重
    seen_lower = {}
    col_names = []
    for name in col_names_raw:
        key = name.lower()
        if key in seen_lower:
            continue
        seen_lower[key] = True
        col_names.append(name)
    col_defs = ", ".join(f'"{c}" {pg_type_to_sqlite(next(ct[1] for ct in columns if ct[0] == c))}' for c in col_names)

    # 2. 在 SQLite 中重建表
    sqlite_conn.execute(f'DROP TABLE IF EXISTS "{sqlite_name}"')
    sqlite_conn.execute(f'CREATE TABLE "{sqlite_name}" ({col_defs})')

    # 3. 从 PG 读取数据并批量写入 SQLite
    cur = pg_conn.cursor()
    col_list = ", ".join(f'"{c}"' for c in col_names)
    cur.execute(f'SELECT {col_list} FROM "{schema}"."{table}"')

    placeholders = ", ".join(["?"] * len(col_names))
    insert_sql = f'INSERT INTO "{sqlite_name}" VALUES ({placeholders})'

    total = 0
    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break
        # 处理不可序列化的类型
        cleaned = []
        for row in rows:
            cleaned.append(tuple(
                str(v) if isinstance(v, (list, dict, bytes)) else v
                for v in row
            ))
        sqlite_conn.executemany(insert_sql, cleaned)
        total += len(cleaned)

    sqlite_conn.commit()
    return total


def main():
    """定时任务入口：PG → SQLite 全量快照同步，返回 result dict 供 task_runner 记录"""
    if not PG_URL:
        log.error("DATABASE_URL 未设置，无法连接 PG")
        return {"success": False, "error": "DATABASE_URL not set"}

    log.info(f"PG 连接: {PG_URL.split('@')[-1]}")
    log.info(f"SQLite 目标: {SQLITE_PATH}")

    pg_conn = None
    sqlite_conn = None
    try:
        # 连接 PG
        pg_conn = psycopg2.connect(PG_URL, connect_timeout=10)
        pg_conn.set_session(readonly=True)

        # 连接 SQLite
        sqlite_conn = sqlite3.connect(str(SQLITE_PATH), timeout=60)
        sqlite_conn.execute("PRAGMA synchronous=NORMAL")
        sqlite_conn.execute("PRAGMA busy_timeout=30000")

        # 获取所有表
        tables = get_pg_tables(pg_conn)
        log.info(f"发现 {len(tables)} 张 PG 表")

        # 逐表同步
        t0 = time.time()
        total_rows = 0
        errors = []

        for schema, table in tables:
            sqlite_name = sanitize_table_name(schema, table)
            try:
                rows = sync_table(pg_conn, sqlite_conn, schema, table)
                if rows > 0:
                    log.info(f"  ✓ {schema}.{table} → {sqlite_name}  ({rows:,} 行)")
                total_rows += rows
            except Exception as e:
                log.error(f"  ✗ {schema}.{table} 失败: {e}")
                errors.append(f"{schema}.{table}: {e}")

        # 汇总
        elapsed = time.time() - t0
        log.info("=" * 60)
        log.info(f"同步完成: {total_rows:,} 行, 耗时 {elapsed:.1f}s")

        # 显示文件大小
        size_mb = SQLITE_PATH.stat().st_size / (1024 * 1024)
        log.info(f"SQLite 文件大小: {size_mb:.1f} MB")

        success = len(errors) == 0
        return {
            "success": success,
            "tables_synced": len(tables) - len(errors),
            "tables_failed": len(errors),
            "total_rows": total_rows,
            "elapsed_seconds": round(elapsed, 1),
            "sqlite_size_mb": round(size_mb, 1),
            "errors": errors if errors else None,
        }
    except Exception as e:
        log.error(f"同步异常: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if pg_conn:
            pg_conn.close()
        if sqlite_conn:
            sqlite_conn.close()


if __name__ == "__main__":
    main()
