"""修复 `eflow_tt_whatsapp_alert_log` 老表：缺列 + 缺主键（生产事故 2026-10-06 / 10-07）。

背景
----
生产 PG 库（schema `app`）里的 `eflow_tt_whatsapp_alert_log` 是**早期版本**
建的，缺 `last_error` 等列。`CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op，
不会加列；而旧 `tt_alarm_store._ensure_columns` 的补列清单又漏了 `last_error`，
于是每次 `record_result` upsert 带 `last_error` → PG 报
`UndefinedColumn: 字段 "last_error" 不存在`，任务整轮失败
（「eFlow P1 Alarm WhatsApp Push」停摆）。

2026-10-07 复查时又发现**同一张表还有第二个更隐蔽的缺口**：它是早期由别处
（Excel 导入）建的，`tt_no` 上**没有任何主键/唯一约束**。而 `record_result`
走 `upsert(..., conflict_cols=["tt_no"])`，PG 分支生成
`INSERT ... ON CONFLICT ("tt_no") DO UPDATE` —— 没有唯一约束可匹配时 PG 报
`InvalidColumnReference: 没有匹配 ON CONFLICT 说明的唯一或者排除约束`。

两个缺口的**根因同源**：建表 DDL 只对新建表生效，老表的「列」与「约束」都
没有补齐路径。该缺陷更隐蔽 —— 只要扫描窗口内没有需落库的候选（`due=0`）就
永不触发，实测该表已**静默 5 天**没有写入（最后一行 2026-10-02）。

代码层已修：`_ensure_columns` 补**全量列**（`ENSURE_COLUMNS`）、
`_ensure_pk_constraint` 补**主键**，运行期 `ensure_log_table()` 会自动补齐
两者。本脚本用于**迁移/巡检**：在部署前把现有库一次性补齐，并在补完后复核，
避免等到下次整点扫描才发现。

设计
----
* **单一事实来源**：列集合与主键列直接 import `tt_alarm_store` 的
  `LOG_COLUMNS` / `COLUMN_TYPES` / `LOG_PK` —— 不手抄，从结构上杜绝
  「脚本与代码分叉」。
* **幂等**：只补缺列/缺约束，已有则跳过；可反复重跑。
* **双模**：`--target pg`（默认，schema app）或 `--target sqlite`（本地 db/app.db）。
  注意 sqlite 天然不需要补约束（建表即带主键，且 upsert 走 `INSERT OR REPLACE`）。
* **dry-run**：先预览将补什么，再决定是否执行。
* **只加不删**：ADD COLUMN / ADD CONSTRAINT 均为纯增量。若 `tt_no` 存在重复值或
  NULL，脚本**拒绝加约束并退出码 2**，交人工裁决 —— **绝不自动删行**。

用法
----
    python backend/migrations/fix_tt_alert_log_columns.py --dry-run        # 预览（PG）
    python backend/migrations/fix_tt_alert_log_columns.py                  # 执行（PG）
    python backend/migrations/fix_tt_alert_log_columns.py --target sqlite # 本地 app.db

退出码：0=无待处理（或已就绪）；1=仍有缺列/缺约束；2=有重复或 NULL，需人工裁决。
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
PK_COL = LOG_PK[0]
# 约束名按表名派生，与 tt_alarm_store._pk_constraint_name 保持一致
PK_CONSTRAINT = f"{TABLE}_pk"


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


def _pg_unique_cols(cur):
    """本表上「唯一/主键约束」覆盖的列集合（判 ON CONFLICT 能否成立）。"""
    cur.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_class t ON t.oid = i.indrelid "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey) "
        "WHERE t.relname = %s AND i.indisunique AND i.indisvalid "
        "AND i.indpred IS NULL AND i.indexprs IS NULL",
        (TABLE,),
    )
    return {r[0] for r in cur.fetchall()}


def _pg_ensure_pk(cur, dry_run: bool) -> int:
    """补主键约束（2026-10-07 事故：老表无约束 → upsert 的 ON CONFLICT 必失败）。

    返回 0=已就绪/已补成功，2=有重复或 NULL 需人工裁决，3=已执行待提交。
    """
    if PK_COL in _pg_unique_cols(cur):
        print(f"== {PK_COL} 已有唯一约束，ON CONFLICT 可用")
        return 0
    print(f"== {PK_COL} 无唯一约束 —— 写路径 record_result/upsert 会报 "
          f"InvalidColumnReference，需补主键")
    cur.execute(
        f"SELECT {tl.pg_quote(PK_COL)}, COUNT(*) FROM "
        f"{tl.pg_quote(SCHEMA)}.{tl.pg_quote(TABLE)} "
        f"WHERE {tl.pg_quote(PK_COL)} IS NOT NULL "
        f"GROUP BY {tl.pg_quote(PK_COL)} HAVING COUNT(*) > 1 LIMIT 5"
    )
    dup = cur.fetchall()
    cur.execute(
        f"SELECT COUNT(*) FROM {tl.pg_quote(SCHEMA)}.{tl.pg_quote(TABLE)} "
        f"WHERE {tl.pg_quote(PK_COL)} IS NULL"
    )
    nulls = cur.fetchone()[0]
    if dup or nulls:
        print(f"!! 无法补主键：{len(dup)} 组重复值、{nulls} 个 NULL"
              f"（重复样本 {[r[0] for r in dup]}）")
        print("!! 需人工裁决后再加约束 —— 本脚本不自动删行")
        return 2
    print(f"    ALTER TABLE ... ADD CONSTRAINT {PK_CONSTRAINT} "
          f"PRIMARY KEY ({PK_COL})")
    if dry_run:
        print("== dry-run：未执行 ADD CONSTRAINT")
        return 0
    cur.execute(
        f"ALTER TABLE {tl.pg_quote(SCHEMA)}.{tl.pg_quote(TABLE)} "
        f"ADD CONSTRAINT {PK_CONSTRAINT} PRIMARY KEY ({tl.pg_quote(PK_COL)})"
    )
    return 3


def run_pg(dry_run: bool) -> int:
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        if not _pg_table_exists(cur):
            print(f"== 表 {SCHEMA}.{TABLE} 不存在 —— 无需处理"
                  f"（运行期 ensure_log_table 会按当前代码建全列 + 主键）")
            return 0
        present = _pg_present(cur)
        missing = [(c, t) for c, t in _want_columns() if c not in present]
        print(f"== {SCHEMA}.{TABLE} 现有 {len(present)} 列，"
              f"应存在 {len(_want_columns())} 列")
        if missing:
            print(f"== 将补 {len(missing)} 列:")
            for c, t in missing:
                print(f"    ALTER TABLE ... ADD COLUMN {c} {t}")
            if dry_run:
                print("== dry-run：未执行 ADD COLUMN")
            else:
                for c, t in missing:
                    cur.execute(
                        f"ALTER TABLE {tl.pg_quote(SCHEMA)}.{tl.pg_quote(TABLE)} "
                        f"ADD COLUMN {tl.pg_quote(c)} {t}"
                    )
                conn.commit()
        else:
            print("== 无缺列")

        # ---- 约束检查：与补列同属「老库自愈」，缺它写路径必失败 ----
        cst = _pg_ensure_pk(cur, dry_run)
        if cst == 3:
            conn.commit()

        if dry_run:
            print("== dry-run 结束：未提交任何结构变更")
            return 0

        after = _pg_present(cur)
        remain = [c for c, _ in _want_columns() if c not in after]
        pk_ok = PK_COL in _pg_unique_cols(cur)
        print(f"== 复核：剩余缺列 {remain or '无'}；"
              f"{PK_COL} 唯一约束 {'已就绪' if pk_ok else '仍缺失'}")
        if cst == 2:
            return 2
        return 1 if (remain or not pk_ok) else 0
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
        # sqlite 无需补主键约束：建表即带 PRIMARY KEY，且 upsert 走
        # INSERT OR REPLACE（不需要冲突目标），无约束也照样正确。
        if PK_COL in present:
            print(f"== sqlite 无需补约束（{PK_COL} 建表即带主键，"
                  f"且 upsert 走 INSERT OR REPLACE）")
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
    parser = argparse.ArgumentParser(
        description="补齐 eflow_tt_whatsapp_alert_log 的缺列与缺主键约束（老库自愈）")
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
