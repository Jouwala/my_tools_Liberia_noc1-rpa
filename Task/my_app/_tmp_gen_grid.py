# -*- coding: utf-8 -*-
"""用当前路由代码生成前端无头测试夹具（含 tabs 页签树）。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend.routers import vmax_cxo_daily as r  # noqa: E402

g = json.loads(r.get_grid().body)
d = json.loads(r.get_days(40).body)
open("_tmp_grid_new.json", "w", encoding="utf-8").write(json.dumps(g, ensure_ascii=False))
open("_tmp_days_new.json", "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
print("kpis=%d tabs=%d days=%d 每日列=%d" % (
    len(g["kpis"]), len(g["tabs"]), len(d["days"]), len([k for k in d["days"][0] if k not in ("date", "dow")])))
print("tabs:", [(t["key"], len(t["kpis"]), [s["key"] for s in t["subtabs"]]) for t in g["tabs"]])
