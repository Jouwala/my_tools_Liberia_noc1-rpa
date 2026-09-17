# -*- coding: utf-8 -*-
"""校验新增/追加的注册点：路由可 import、任务已注册、worker 分组已含新任务。"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.routers import vmax_cxo_daily  # noqa: F401
print("router import OK, routes:", [r.path for r in vmax_cxo_daily.router.routes])

from backend.task_registry import TASK_SPECS
spec = [s for s in TASK_SPECS if s["task_id"] == "vmax_cxo_daily_sync"]
print("task spec entries:", len(spec))
if spec:
    print("  cron=%s category=%s gateway=%s name=%s" % (
        spec[0]["default_cron"], spec[0]["category"], spec[0].get("gateway"), spec[0]["name"]))
print("total tasks:", len(TASK_SPECS))

from backend.worker_watchdog import GROUP_TASK_MAP  # noqa: E402
grp = {g: [t.strip() for t in "".join(v).split(",") if t.strip()] for g, v in GROUP_TASK_MAP.items()}
found = [g for g, ts in grp.items() if "vmax_cxo_daily_sync" in ts]
print("vmax_cxo_daily_sync in group:", found)
print("cxo_dashboard_cache_sync still in group:", [g for g, ts in grp.items() if "cxo_dashboard_cache_sync" in ts])
print("group sizes:", {g: len(ts) for g, ts in grp.items()})

import backend.main as m  # noqa: E402
paths = [getattr(r, "path", "") for r in m.app.routes]
print("app has /api/vmax-cxo-daily/grid:", "/api/vmax-cxo-daily/grid" in paths)
print("existing vmax route untouched:", "/api/vmax-cxo-dashboard/summary" in paths)
print("existing cxo route untouched:", "/api/cxo-dashboard/cache" in paths)
print("new daily routes on app:", [p for p in paths if "vmax-cxo" in p])
