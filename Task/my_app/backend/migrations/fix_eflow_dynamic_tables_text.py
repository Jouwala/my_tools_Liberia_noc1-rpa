"""修复 eFlow 动态表在 PG 中的过期数值类型（只读检查 + ALTER 到 TEXT）。

背景
----
sync_from_eflow_api._upsert_df 的设计是「动态全 TEXT 表」：列集合随网管版本演进，
所有值按字符串写入。SQLite 的动态类型系统容忍这一点；但 app.db 的 eflow_* 表
带有历史遗留的 REAL/INTEGER/TIMESTAMP 声明（旧导入路径产生），迁移到 PG 后变成
DOUBLE PRECISION/BIGINT/timestamp，插入非数值文本（如 'TRM'、'BSC1(1)'）时 PG
报错：无效的类型 double precision 输入语法。

本脚本把 app schema 下六个 _upsert_df 管理的动态表（eflow_tt / eflow_wo /
eflow_cr / eflow_pm / eflow_site / person）中所有非 TEXT 列改为 TEXT，
完全对齐 SQLite 行为。数据零丢失（数值列用 ::text 无损转换）。

- 不触碰 realtime_alarm / history_alarm（由 pandas write_df 写入、消费方依赖
  数值列做运算，如告警时长差）。
- 幂等：已是 TEXT 的列自动跳过，可反复重跑。
- 可回滚：--undo 文件记录原始类型，可一键还原。

用法
----
    python backend/migrations/fix_eflow_dynamic_tables_text.py --dry-run   # 只预览
    python backend/migrations/fix_eflow_dynamic_tables_text.py             # 执行
    python backend/migrations/fix_eflow_dynamic_tables_text.py --undo 文件  # 还原
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

logger = tl.logger  # reuse transfer_lib logging (basicConfig)

SCHEMA = "app"
TABLES = ["eflow_tt", "eflow_wo", "eflow_cr", "eflow_pm", "eflow_site", "person"]
TEXTISH = {"text", "character varying", "character", "name"}


def _pg_conn():
    tl.load_env(ROOT / "backend" / ".env")
    url = tl.get_pg_url()
    if not url:
        raise SystemExit("未找到 DATABASE_URL（环境变量或 backend/.env）")
    import psycopg2

    return psycopg2.connect(url, connect_timeout=15)


def non_text_cols(cur, table):
    """返回 [(column_name, data_type), ...]，只含非 TEXT 列（按 ordinal_position）。"""
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s AND data_type NOT IN ('text','character varying','character','name') "
        "ORDER BY ordinal_position",
        (SCHEMA, table),
    )
    return cur.fetchall()


def collect_all(conn):
    cur = conn.cursor()
    plan = {}  # table -> [(col, orig_type)]
    for t in TABLES:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            (f"{SCHEMA}.{t}",),
        )
        if not cur.fetchone()[0]:
            logger.warning("[skip] 表不存在: %s.%s", SCHEMA, t)
            continue
        plan[t] = non_text_cols(cur, t)
    return plan


def build_undo_sql(plan):
    lines = ["-- 回滚脚本：把 TEXT 列还原为原始类型（数值列还原为 double precision/bigint）", ""]
    for t, cols in plan.items():
        for col, orig in cols:
            lines.append(f'ALTER TABLE {tl.pg_quote(SCHEMA)}.{tl.pg_quote(t)} '
                         f'ALTER COLUMN {tl.pg_quote(col)} TYPE {orig} USING NULLIF({tl.pg_quote(col)}, \'\')::{orig};')
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="eflow 动态表非 TEXT 列 -> TEXT")
    parser.add_argument("--dry-run", action="store_true", help="只预览不改库")
    parser.add_argument("--undo", metavar="FILE", help="执行回滚脚本（还原原始类型）")
    parser.add_argument("--undo-out", default=None, help="回滚脚本输出路径（默认 backup/ 下）")
    args = parser.parse_args(argv)

    if args.undo:
        conn = _pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(Path(args.undo).read_text(encoding="utf-8"))
            conn.commit()
            print(f"UNDO 执行完成: {args.undo}")
        finally:
            conn.close()
        return 0

    conn = _pg_conn()
    try:
        plan = collect_all(conn)
        total = sum(len(v) for v in plan.values())
        print(f"== 计划转换: {total} 列（{sum(bool(v) for v in plan.values())} 张表受影响）")
        for t, cols in plan.items():
            print(f"  {SCHEMA}.{t}: {len(cols)} 列")
            for c, o in cols[:8]:
                print(f"      {c}  ({o})")
            if len(cols) > 8:
                print(f"      ... 共 {len(cols)} 列")

        if total == 0:
            print("== 无需转换，所有动态表已是 TEXT 形态")
            return 0
        if args.dry_run:
            print("== dry-run：未执行任何 ALTER")
            return 0

        undo_path = args.undo_out or (ROOT / "backup" / f"undo_eflow_text_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.sql")
        undo_path.parent.mkdir(parents=True, exist_ok=True)
        undo_path.write_text(build_undo_sql(plan), encoding="utf-8")
        print(f"== 回滚脚本已写入: {undo_path}")

        cur = conn.cursor()
        altered = 0
        for t, cols in plan.items():
            for col, orig in cols:
                sql = (
                    f"ALTER TABLE {tl.pg_quote(SCHEMA)}.{tl.pg_quote(t)} "
                    f"ALTER COLUMN {tl.pg_quote(col)} TYPE TEXT USING {tl.pg_quote(col)}::text"
                )
                cur.execute(sql)
                altered += 1
        conn.commit()
        print(f"== 已转换 {altered} 列 -> TEXT")

        # 复核
        plan2 = collect_all(conn)
        remain = sum(len(v) for v in plan2.values())
        print(f"== 复核：剩余非 TEXT 列 {remain}")
        if remain:
            print("!! 有残留非 TEXT 列：")
            for t, cols in plan2.items():
                for c, o in cols:
                    print(f"    {t}.{c} ({o})")
            return 1
        print("== 全部完成")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    logging = __import__("logging")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
