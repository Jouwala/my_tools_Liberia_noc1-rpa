# -*- coding: utf-8 -*-
"""为 44 个目录指标补齐：标题、单位、推测口径。只读缓存。"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
cache = json.loads((ROOT / "data" / "cxo_dashboard" / "last_known_good.json").read_text(encoding="utf-8"))
keys = cache.get("keys") or {}
cat = json.loads((ROOT / "_tmp_tab_catalog.json").read_text(encoding="utf-8"))

EXISTING = {
    (250005, "ppc400401001"), (250005, "ppb400499002"),
    (5112, "ppc400464046"), (5112, "ppc400464013"), (5112, "ppc400464049"), (5112, "ppc400464015"),
    (5132, "ppc300501005"), (5132, "ppc300501008"), (5132, "ppc300503001"), (5132, "ppc300504126"),
    (5132, "ppc300521001"), (5132, "ppc300522214"), (5132, "ppc300541302"), (5132, "ppc300542580"),
    (5132, "ppc300543001"), (5132, "ppc300543002"), (5132, "ppc300543357"), (5132, "ppc300543368"),
    (5132, "ppc300544532"), (5132, "ppb300542009"),
}


def find_entry(mon, code):
    """按 monitor+code 反查缓存条目，取展示字段。"""
    for k, entry in keys.items():
        if "indicator" not in k:
            continue
        data = (entry or {}).get("data") or {}
        for path in (("queryData", "queryParam"), ("queryParam",)):
            node = data
            for p in path:
                node = node.get(p) if isinstance(node, dict) else None
            if isinstance(node, dict) and node:
                if node.get("monitorid") == mon and code in (node.get("showColumns") or []):
                    return data, node
    return {}, {}


def title_of(data):
    for k in ("title", "name", "showName"):
        v = data.get(k)
        if isinstance(v, str) and v:
            return v.strip()
        if isinstance(v, dict):
            for kk in ("en", "zh"):
                if v.get(kk):
                    return str(v[kk]).strip()
    return ""


def unit_of(data):
    """单位藏在 data.value 的后缀里：'71.83ms' / '1748103702.00s' / '4.18' / '12.5%'。"""
    val = data.get("value")
    if isinstance(val, str):
        m = re.match(r"^\s*[-+]?[\d.,eE]+\s*(.*)$", val)
        if m:
            suf = m.group(1).strip()
            if suf in ("ms", "s", "min", "h", "KB", "MB", "GB", "Kbps", "Mbps", "times", "%"):
                return "(%s)" % suf
            if suf:
                return "(%s)" % suf
    for k in ("unit", "units", "yUnit"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


COUNT_RE = re.compile(r"^(times|number)\b|times of|number of|reconnection|drop times", re.I)


def guess(code, title, unit):
    """ppb* 多为计次；含 rate/ratio/成功率/时延/时长 的多为率或均值 -> avg。"""
    t = title or ""
    if code.startswith("ppb"):
        return "sum", 0
    if COUNT_RE.search(t):
        return "sum", 0
    digits = 3 if re.search(r"drop|loss|retransmission", t, re.I) else 2
    return "avg", digits


print("%-7s %-19s %-46s %-9s %-5s %-6s %s" % ("mon", "code", "title", "unit", "agg", "digits", "tabs"))
new = []
for item in cat["distinct"]:
    mon, code = item["mon"], item["code"]
    if (mon, code) in EXISTING:
        continue
    data, _ = find_entry(mon, code)
    title, unit = title_of(data), unit_of(data)
    agg, digits = guess(code, title, unit)
    new.append(dict(mon=mon, code=code, title=title, unit=unit, agg=agg, digits=digits, tabs=item["tabs"]))
    print("%-7s %-19s %-46s %-9s %-5s %-6s %s" % (mon, code, title[:46], unit[:9], agg, digits, ",".join(item["tabs"])))

print()
print("新增合计:", len(new))
json.dump(new, open(ROOT / "_tmp_new_specs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写 _tmp_new_specs.json")
