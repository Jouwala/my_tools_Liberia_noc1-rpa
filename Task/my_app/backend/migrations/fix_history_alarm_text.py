"""修复 app.history_alarm 列类型漂移（数值列 -> TEXT）。

背景：
- history_alarm 由 eflow_alarm_service._write_alarm_to_appdb 以 upsert_key="id" 做
  append 累积写入，schema 在首次建表时由 pandas 推断（毫秒时间戳列落成 bigint/integer/
  double precision）。
- 后续 API 返回的数据若在某数值列出现非数值/空串，append 时即报
  psycopg2.errors.DatatypeMismatch，整表同步失败。
- 这与 eflow_tt 等动态表的设计一致：本应全部按 TEXT 存（SQLite 动态类型语义），
  消费方在读取时再按需 CAST/coerce。故将这些数值列统一转为 TEXT，零数据丢失。

范围：仅 app.history_alarm（realtime_alarm 走 if_exists="replace"，每次重建、类型跟随
当前数据，不会僵化，故不动）。

用法：
  python fix_history_alarm_text.py            # 执行
  python fix_history_alarm_text.py --dry-run  # 仅预览
  python fix_history_alarm_text.py --undo     # 用备份 SQL 回滚
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import os  # noqa: E402

# 手动加载 backend/.env（项目 venv 无 dotenv 依赖）
for _f in (ROOT / "backend" / ".env", ROOT / ".env"):
    if _f.is_file():
        for _line in _f.read_text(encoding="utf-8", errors="replace").splitlines():
            _line = _line.strip()
            if _line.startswith("DATABASE_URL="):
                os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip().strip('"').strip("'")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL 未设置（请确认 backend/.env）")

TARGET_SCHEMA = "app"
TARGET_TABLE = "history_alarm"
NUMERIC_TYPES = ("double precision", "bigint", "integer", "numeric", "real",
                 "timestamp without time zone", "timestamp with time zone")


def get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, connect_timeout=30)


def plan_columns(cur):
    cur.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
        (TARGET_SCHEMA, TARGET_TABLE),
    )
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--undo", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    try:
        if args.undo:
            backup = ROOT / "backup" / f"undo_{TARGET_TABLE}_text.sql"
            if not backup.is_file():
                raise SystemExit(f"回滚脚本不存在: {backup}")
            sql = backup.read_text(encoding="utf-8")
            print(f"执行回滚脚本: {backup}")
            cur.execute(sql)
            conn.commit()
            print("回滚完成")
            return

        cols = plan_columns(cur)
        to_fix = [(c, t) for c, t in cols if t in NUMERIC_TYPES]
        print(f"{TARGET_SCHEMA}.{TARGET_TABLE}: 总列 {len(cols)}，需转 TEXT 的数值列 {len(to_fix)}")

        if not to_fix:
            print("无需转换（已全部为 TEXT）。")
            return

        rollback_lines = []
        for col, dtype in to_fix:
            print(f"  ALTER {col}  ({dtype} -> text)")
            if not args.dry_run:
                cur.execute(
                    f'ALTER TABLE {TARGET_SCHEMA}.{TARGET_TABLE} '
                    f'ALTER COLUMN "{col}" TYPE text USING "{col}"::text'
                )
            rollback_lines.append(
                f'ALTER TABLE {TARGET_SCHEMA}.{TARGET_TABLE} '
                f'ALTER COLUMN "{col}" TYPE {dtype};'
            )

        if not args.dry_run:
            conn.commit()
            # 回滚脚本
            backup = ROOT / "backup" / f"undo_{TARGET_TABLE}_text.sql"
            backup.write_text("\n".join(rollback_lines) + "\n", encoding="utf-8")
            print(f"已提交并生成回滚脚本: {backup}")

            # 复检
            cur.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_schema=%s AND table_name=%s AND data_type<>'text'""",
                (TARGET_SCHEMA, TARGET_TABLE),
            )
            leftover = cur.fetchone()[0]
            print(f"复检：剩余非 TEXT 列 = {leftover}")
            if leftover:
                raise SystemExit("仍有非 TEXT 列，请检查")
            print("OK: history_alarm 数值列已全部转为 TEXT")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
