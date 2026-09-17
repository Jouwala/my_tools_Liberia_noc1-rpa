# -*- coding: utf-8 -*-
"""直读 task_queue 行，看新任务为何停在 pending。"""
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
cands = [ROOT / "backend" / "db" / "app.db", ROOT / "db" / "app.db"]
for db in cands:
    if not db.exists():
        continue
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    if "task_queue" not in names:
        con.close()
        continue
    cols = [d[1] for d in con.execute("pragma table_info(task_queue)")]
    print("DB:", db.relative_to(ROOT))
    print("  cols:", cols)
    q = "、".join(cols)
    print("  ---- 最近 6 行 ----")
    for row in con.execute("select * from task_queue order by id desc limit 6"):
        print("   ", dict(zip(cols, row)))
    print("  ---- 我的任务 ----")
    for row in con.execute("select * from task_queue where task_id like '%daily_sync%' order by id desc limit 3"):
        print("   ", dict(zip(cols, row)))
    con.close()
    break
else:
    print("未找到含 task_queue 的库；候选:", [str(c) for c in cands])
