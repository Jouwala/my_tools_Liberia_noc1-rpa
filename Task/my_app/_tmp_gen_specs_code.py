# -*- coding: utf-8 -*-
"""生成 30 条新增 KPI_SPECS 的 Python 源码（避免手抄错）。"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / "_tmp_tab_catalog.json").read_text(encoding="utf-8"))["rows"]
probe = {(x["mon"], x["code"]): x for x in json.loads((ROOT / "_tmp_new_specs.json").read_text(encoding="utf-8"))}

# 与已有 KPI_SPECS 同 code 的 5112 条目：板子标题与单位取自看板 value（kbps / ms）
OVERLAP = {202: ("(kbps)", 2), 208: ("(ms)", 2)}
SEEN = set()
out = []
for r in rows:
    if r["scope"] != "service":            # 页签归属后面用 KPI_TABS 表达，这里按 service 侧取标题
        continue
    kid = str(r["id"])
    if kid in SEEN:
        continue
    mon, code = r["mon"], r["codes"][0]
    p = probe.get((mon, code))
    if not p:                              # 已在 KPI_SPECS 里的 14 个 5132 指标
        continue
    SEEN.add(kid)
    title = r["title"]
    unit = OVERLAP[kid][0] if kid in OVERLAP else p["unit"]
    digits = OVERLAP[kid][1] if kid in OVERLAP else p["digits"]
    if kid == "268":
        digits, note = 0, "counter_caution"
    elif re.search(r"reconnection", title, re.I):
        digits, note = 3, "frequency"
    elif re.search(r"drop|loss|retransmission", title, re.I):
        digits, note = 3, "unweighted"
    else:
        digits, note = (digits or 2), "unweighted"
    out.append('    "%s": {"title": %s, "unit": %r, "monitorid": %d, "code": %r,\n'
               '            "divisor": None, "agg": "avg", "digits": %d, "group": "service",\n'
               '            "filter_model": _EMPTY_FILTER, "note": %r},'
               % (kid, '"%s"' % title.replace('"', '\\"'), unit, mon, code, digits, note))

code = "\n".join(out)
print(code)
print()
print("# 共 %d 条" % len(out))
(ROOT / "_tmp_new_specs_code.txt").write_text(code, encoding="utf-8")
