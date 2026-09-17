# -*- coding: utf-8 -*-
"""本地核对：6 个 CXO 趋势 KPI 的"日聚合"口径（day-1 = 昨天完整 96 桶）。只读，不联网。"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
c = json.loads((ROOT / "data/cxo_dashboard/last_known_good.json").read_text(encoding="utf-8"))
k = c["keys"]
print("KPI | showName                    | unit      | n   SUM           AVG         MAX")
for g in ("91", "92", "93", "94", "95", "99"):
    d = (k.get("summary/trend_%s" % g) or {}).get("data") or {}
    ser = {s.get("name"): (s.get("data") or []) for s in (d.get("option") or {}).get("series") or []}
    for label in ("day-1", "day-0"):
        v = []
        for x in ser.get(label) or []:
            try:
                v.append(float(x))
            except (TypeError, ValueError):
                pass
        if not v:
            continue
        print("%-3s| %-27s| %-9s| %-4s %-3s SUM=%-13.1f AVG=%-11.2f MAX=%-11.1f" % (
            g, (d.get("showName") or "")[:27], ((d.get("kpiConfig") or {}).get("unit") or "")[:9],
            label, len(v), sum(v), sum(v) / len(v), max(v)))
