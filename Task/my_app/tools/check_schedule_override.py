# -*- coding: utf-8 -*-
"""【可复用诊断】核对「代码 default_cron vs task_schedule_config 生效值」。

只读，不写库。打印手册 13-operations.md 引用的三个示例任务，以及全部错配
task_id 与条数。用法：`cd Task\\my_app ; python tools\\check_schedule_override.py`。
用途见 docs/manual/13-operations.md「调度覆盖：改了代码默认值却不生效」一节。
"""
import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

t0 = time.time()

from backend.database import get_raw_connection  # noqa: E402
from backend.task_registry import TASK_SPECS  # noqa: E402

defaults = {s["task_id"]: (s.get("default_cron") or "") for s in TASK_SPECS}
with get_raw_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT task_id, cron FROM task_schedule_config")
    saved = {r[0]: (r[1] or "") for r in cur.fetchall()}

for tid in ("eflow_active_alarm", "sp_online_sync", "ipran_kpi_sync"):
    print(f"{tid}: 默认={defaults.get(tid)!r} 生效={saved.get(tid)!r}")

mis = sorted(t for t, c in saved.items() if t in defaults and c and c != defaults[t])
print("错配 task_id:", ", ".join(mis))
print(f"耗时 {time.time() - t0:.2f}s")
