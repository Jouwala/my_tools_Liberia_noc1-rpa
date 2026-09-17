# -*- coding: utf-8 -*-
"""回归对比：批量化后，原有 20 个指标的「已完整历史日」数值必须一字不变。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

before = json.load(open("_tmp_daily_before.json", encoding="utf-8"))
after = json.load(open("data/vmax_cxo_daily/daily.json", encoding="utf-8"))
OLD = [str(i) for i in (91, 92, 93, 94, 95, 99)] + [str(i) for i in range(101, 115)]
TODAY = "2026-09-16"
AGG = {"91": "sum", "92": "max", "114": "sum"}

diffs, checked, skipped = [], 0, 0
for day, row in before["days"].items():
    if day >= TODAY:
        skipped += 1
        continue
    for kid in OLD:
        b = row.get(kid)
        a = (after["days"].get(day) or {}).get(kid)
        if not b or not b.get("complete"):
            continue
        if not a:
            diffs.append("%s kpi=%s 丢失" % (day, kid))
            continue
        for f in ("sum", "avg", "max", "min", "n"):
            if b.get(f) != a.get(f):
                diffs.append("%s kpi=%s %s: %s -> %s" % (day, kid, f, b.get(f), a.get(f)))
        checked += 1

print("=== 原有 20 个指标 · 已完整历史日 数值回归 ===")
print("  对比条目: %d（跳过今天 %s 的 %d 天，因为今天还在累积）" % (checked, TODAY, skipped))
if diffs:
    print("  [FAIL] 发现 %d 处变动:" % len(diffs))
    for d in diffs[:15]:
        print("     " + d)
else:
    print("  [PASS] 全部一字未变 -> 批量取数未串列")

print()
print("=== 新指标落盘情况 ===")
bk, ak = set(), set()
for row in before["days"].values():
    bk |= set(row)
for row in after["days"].values():
    ak |= set(row)
new_ids = sorted(ak - bk, key=lambda x: (len(x), x))
print("  指标总数: %d -> %d（新增 %d 个）" % (len(bk), len(ak), len(new_ids)))
print("  新增 id:", ",".join(new_ids))
missing = [k for k in ak if not any(k in r for r in after["days"].values())]
print()
print("=== 各日覆盖（新增指标）===")
for day in sorted(after["days"], reverse=True)[:9]:
    row = after["days"][day]
    cov = [k for k in new_ids if k in row]
    full = [k for k in cov if row[k].get("complete")]
    print("  %s  新增指标有数 %2d/%d（其中完整 %2d）  总指标 %d" % (
        day, len(cov), len(new_ids), len(full), len(row)))
sys.exit(1 if diffs else 0)
