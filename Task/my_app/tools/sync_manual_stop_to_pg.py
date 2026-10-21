# -*- coding: utf-8 -*-
"""把 manually_stopped 标记同步到 PG 的 app.task_schedule_config。

背景见 tools/backfill_manual_stop_flag.py 与 tools/fix_task_schedule_dupes.py：
生产是双库（SQLite db/app.db + PG 192.168.100.20:5432/myapp）。
task_runner 的读写**只走 SQLite**（`_load/_save_schedule_config` 硬编码
sqlite3.connect），但 PG 侧存在同一张表且对外可见，两边不一致会让
「界面上关着、另一侧查出来是开着」这类问题无从排查。

本脚本只做一件事：把 SQLite 里这三行的 manually_stopped 写到 PG，
**不碰 cron / enabled / updated_at**（PG 侧有真主键，写入即替换，天然幂等）。

用法：
    python tools/sync_manual_stop_to_pg.py --check    # 只比对
    python tools/sync_manual_stop_to_pg.py --apply    # 写入 PG
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

TASK_IDS = ("whatsapp_send", "whatsapp_send_ext", "sp_whatsapp_report")


def _sqlite_rows():
    import sqlite3
    con = sqlite3.connect(str(ROOT / "db" / "app.db"), timeout=30)
    try:
        q = ",".join("?" * len(TASK_IDS))
        rows = con.execute(
            f"SELECT task_id, cron, enabled, manually_stopped, updated_at "
            f"FROM task_schedule_config WHERE task_id IN ({q}) ORDER BY task_id",
            TASK_IDS).fetchall()
        return {r[0]: r for r in rows}
    finally:
        con.close()


def _pg_connect():
    for f in (ROOT / "backend" / ".env", ROOT / ".env"):
        if f.is_file():
            load_dotenv(f, override=False)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 未设置（backend/.env 缺失？）")
    import psycopg2
    return psycopg2.connect(url, connect_timeout=15)


def _pg_rows(conn):
    cur = conn.cursor()
    q = ",".join(["%s"] * len(TASK_IDS))
    cur.execute(
        f"SELECT task_id, cron, enabled, manually_stopped, updated_at "
        f"FROM app.task_schedule_config WHERE task_id IN ({q}) ORDER BY task_id",
        TASK_IDS)
    return {r[0]: r for r in cur.fetchall()}


def main() -> int:
    ap = argparse.ArgumentParser(description="把 manually_stopped 同步到 PG")
    ap.add_argument("--apply", action="store_true", help="真正写 PG（缺省只读）")
    args = ap.parse_args()

    lit = _sqlite_rows()
    conn = _pg_connect()
    try:
        pgr = _pg_rows(conn)
        print("=== SQLite（真相源，task_runner 只读写这里）===")
        for t in TASK_IDS:
            r = lit.get(t)
            print(f"  {t:24s} {r}")
        print("\n=== PG（app schema）===")
        for t in TASK_IDS:
            r = pgr.get(t)
            print(f"  {t:24s} {r}")

        diff = [t for t in TASK_IDS
                if lit.get(t) and pgr.get(t)
                and int(lit[t][3]) != int(pgr[t][3])]
        print(f"\nmanually_stopped 不一致：{diff or '（无）'}")

        if not args.apply:
            print("\n[dry-run] 未写 PG。确认后加 --apply。")
            return 0
        if not diff:
            print("两侧已一致，无需写入。")
            return 0

        cur = conn.cursor()
        for t in diff:
            s = lit[t]
            cur.execute(
                "UPDATE app.task_schedule_config SET manually_stopped = %s WHERE task_id = %s",
                (int(s[3]), t))
            print(f"  PG 更新 {t}: manually_stopped {pgr[t][3]} → {s[3]}")
        conn.commit()
        print("\n=== 写入后复核 ===")
        for t in TASK_IDS:
            print(f"  {t:24s} {_pg_rows(conn)[t]}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())