"""修复 `eflow_tt_whatsapp_alert_log` 老表缺列（生产事故 2026-10-06）。

背景
----
生产 PG 库（schema `app`）里的 `eflow_tt_whatsapp_alert_log` 是**早期版本**
建的，缺 `last_error` 等列。`CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op，
不会加列；而旧 `tt_alarm_store._ensure_columns` 的补列清单又漏了 `last_error`，
于是每次 `record_result` upsert 带 `last_error` → PG 报
`UndefinedColumn: 字段 "last_error" 不存在`，任务整轮失败
（「eFlow P1 Alarm WhatsApp Push」停摆）。

代码层已修：`_ensure_columns` 现在补**全量列**（`ENSURE_COLUMNS`），运行期
`ensure_log_table()` 会自动补齐。本脚本用于**迁移/巡检**：在部署前把现有库
一次性补齐，并在补完后复核，避免等到下次整点扫描才发现。

设计
----
* **单一事实来源**：列集合直接 import `tt_alarm_store.LOG_COLUMNS` / `COLUMN_TYPES`
  —— 不手抄列名，从结构上杜绝「脚本与代码分叉」。
* **幂等**：只补缺列，已存在的列跳过；可反复重跑。
* **双模**：`--target pg`（默认，schema app）或 `--target sqlite`（本地 db/app.db）。
* **dry-run**：先预览将补哪些列，再决定是否执行。
* **只加列、不改类型、不删数据**：ALTER ADD COLUMN 是纯增量、零数据风险。

用法
----
    python backend/migrations/fix_tt_alert_log_columns.py --dry-run        # 预览（PG）
    python backend/migrations/fix_tt_alert_log_columns.py                  # 执行（PG）
    python backend/migrations/fix_tt_alert_log_columns.py --target sqlite # 本地 app.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import transfer_lib as tl  # noqa: E402  (get_pg_url / pg_quote / load_env)

from backend.services.tt_alarm_store import (  # noqa: E402
    LOG_COLUMNS, LOG_PK, COLUMN_TYPES,
)

logger = tl.logger

SCHEMA = "app"
TABLE = "eflow_tt_whatsapp_alert_log"


def _want_columns():
    """需要存在的列全集（建表列 - 主键）。主键由建表逻辑保证，不补。"""
    return [(c, COLUMN_TYPES.get(c, "TEXT")) for c in LOG_COLUMNS if c not in LOG_PK]


# ---------------- PG ----------------
def _pg_conn():
    tl.load_env(ROOT / "backend" / ".env")
    url = tl.get_pg_url()
    if not url:
        raise SystemExit("未找到 DATABASE_URL（环境变量或 backend/.env）")
    import psycopg2
    return psycopg2.connect(url, connect_timeout=15)


def _pg_present(cur):
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s",
        (SCHEMA, TABLE),
    )
    return {r[0] for r in cur.fetchall()}


def _pg_table_exists(cur):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{SCHEMA}.{TABLE}",))
    return bool(cur.fetchone()[0])


def run_pg(dry_run: bool) -> int:
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        if not _pg_table_exists(cur):
            print(f"== 表 {SCHEMA}.{TABLE} 不存在 —— 无需补列"
                  f"（运行期 ensure_log_table 会按当前代码建全列）")
            return 0
        present = _pg_present(cur)
        missing = [(c, t) for c, t in _want_columns() if c not in present]
        print(f"== {SCHEMA}.{TABLE} 现有 {len(present)} 列，"
              f"应存在 {len(_want_columns())} 列")
        if not missing:
            print("== 无缺列，无需处理")
            return 0
        print(f"== 将补 {len(missing)} 列:")
        for c, t in missing:
            print(f"    ALTER TABLE ... ADD COLUMN {c} {t}")
        if dry_run:
            print("== dry-run：未执行任何 ALTER")
            return 0
        for c, t in missing:
            cur.execute(
                f"ALTER TABLE {tl.pg_quote(SCHEMA)}.{tl.pg_quote(TABLE)} "
                f"ADD COLUMN {tl.pg_quote(c)} {t}"
            )
        conn.commit()
        # 复核
        after = _pg_present(cur)
        remain = [c for c, _ in _want_columns() if c not in after]
        print(f"== 已补 {len(missing)} 列；复核剩余缺列: {remain or '无'}")
        return 1 if remain else 0
    finally:
        conn.close()


# ---------------- SQLite ----------------
def run_sqlite(dry_run: bool) -> int:
    import sqlite3
    db_path = ROOT / "db" / "app.db"
    if not db_path.exists():
        print(f"== 本地库不存在: {db_path}")
        return 0
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()
        if not exists:
            print(f"== 表 {TABLE} 不存在 —— 无需补列")
            return 0
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
        missing = [(c, t) for c, t in _want_columns() if c not in present]
        print(f"== {TABLE} 现有 {len(present)} 列；将补 {len(missing)} 列: "
              f"{[c for c, _ in missing] or '无'}")
        if not missing:
            return 0
        if dry_run:
            print("== dry-run：未执行任何 ALTER")
            return 0
        for c, t in missing:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {c} {t}")
        conn.commit()
        after = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
        remain = [c for c, _ in _want_columns() if c not in after]
        print(f"== 已补 {len(missing)} 列；复核剩余缺列: {remain or '无'}")
        return 1 if remain else 0
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="补齐 eflow_tt_whatsapp_alert_log 缺列")
    parser.add_argument("--target", choices=("pg", "sqlite"), default="pg",
                        help="目标库：pg（生产，默认）或 sqlite（本地 db/app.db）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不执行")
    args = parser.parse_args(argv)

    if args.target == "pg":
        return run_pg(args.dry_run)
    return run_sqlite(args.dry_run)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
