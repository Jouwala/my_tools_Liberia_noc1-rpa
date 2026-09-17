# -*- coding: utf-8 -*-
"""幂等性：再跑一轮同步后，全部 50 个指标的「已完整历史日」数值必须完全一致。"""
import json
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STORE = "data/vmax_cxo_daily/daily.json"
shutil.copyfile(STORE, "_tmp_daily_before50.json")
r = subprocess.run([sys.executable, "-c",
                    "import sys;sys.path.insert(0,'.');"
                    "from backend.services.vmax_cxo_daily_cache import run_vmax_cxo_daily_sync as f;"
                    "import json;print(json.dumps(f(),ensure_ascii=False))"],
                   capture_output=True, text=True, encoding="utf-8")
res = json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
print("同步结果: kpis=%s/%s groups=%s written=%s elapsed=%ss errors=%s"
      % (res["kpi_fetched"], res["kpi_total"], res["request_groups"], res["rows_written"],
         res["elapsed_seconds"], res["errors"]))

before = json.load(open("_tmp_daily_before50.json", encoding="utf-8"))
after = json.load(open(STORE, encoding="utf-8"))
TODAY = "2026-09-16"
diffs, checked = [], 0
for day, row in before["days"].items():
    if day >= TODAY:
        continue
    for kid, b in row.items():
        if not b.get("complete"):
            continue
        a = (after["days"].get(day) or {}).get(kid)
        if not a:
            diffs.append("%s kpi=%s 丢失" % (day, kid)); continue
        for f in ("sum", "avg", "max", "min", "n"):
            if b.get(f) != a.get(f):
                diffs.append("%s kpi=%s %s: %s -> %s" % (day, kid, f, b.get(f), a.get(f)))
        checked += 1
print("对比条目: %d（50 指标 × 已完整历史日；今天仍在累积故跳过）" % checked)
if diffs:
    print("[FAIL] %d 处变动:" % len(diffs))
    for d in diffs[:10]:
        print("   " + d)
else:
    print("[PASS] 50 个指标全部完全一致 -> 批量取数幂等、无串列")
sys.exit(1 if diffs else 0)
