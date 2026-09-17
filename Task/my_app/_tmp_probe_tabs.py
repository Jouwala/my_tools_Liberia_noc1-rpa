# -*- coding: utf-8 -*-
"""页签指标全量目录（含过滤条件签名），只读缓存。

关键：同一 code 在不同页签可能带不同 filterListModel（维度过滤），必须按
(monitorid, code, filter签名) 去重，否则日值口径会串。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
cache = json.loads((ROOT / "data" / "cxo_dashboard" / "last_known_good.json").read_text(encoding="utf-8"))
keys = cache.get("keys") or {}

SERVICE_MANIFEST = {
    "Mobility": [391, 392, 393], "Voice": [412, 413, 414], "Data": [431, 433, 434],
    "Video": [451], "SMS": [202, 204, 205, 206, 207, 208],
    "Web Browse": [221, 223, 224, 225, 226, 227, 228], "Game": [242, 243, 244, 245],
    "OTTVoice": list(range(262, 273)), "OTTVideo": [282, 283],
}
NET_TABS = {1: "Mobility", 2: "Service Request", 3: "Accessibility", 4: "Retainability", 5: "InterWorking"}
NET_IDS = {1: [391, 392, 393], 2: [411, 412, 413, 414], 3: [431, 433, 434], 4: [451], 5: [471, 472, 473]}


def qp_of(entry):
    data = (entry or {}).get("data") or {}
    if not isinstance(data, dict):
        return {}, {}
    for path in (("queryData", "queryParam"), ("queryParam",)):
        node = data
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
        if isinstance(node, dict) and node:
            return node, data
    return {}, data


def title_of(data):
    for k in ("title", "name", "showName"):
        v = data.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            return v.get("en") or v.get("zh") or ""
    return ""


def sig(qp):
    """过滤条件签名：把 filterModelList 压成 filed=value 串，便于人眼与去重。"""
    fil = ((qp.get("condition") or {}).get("filterListModel") or {})
    out = []
    for grp in (fil.get("filterGroupList") or []):
        for m in (grp.get("filterModelList") or []):
            out.append("%s=%s" % (m.get("filed"), m.get("value")))
    return ",".join(out) if out else "<empty>"


rows = []
def collect(scope, tab, i, key):
    qp, data = qp_of(keys.get(key))
    cols = [c for c in (qp.get("showColumns") or []) if c != "clttime"]
    rows.append(dict(scope=scope, tab=tab, id=i, title=title_of(data), mon=qp.get("monitorid"),
                     codes=cols, filter=sig(qp), period=qp.get("times", {}).get("period"),
                     uid=qp.get("uid"), sceneid=qp.get("sceneid")))

for biz, ids in SERVICE_MANIFEST.items():
    for i in ids:
        collect("service", biz, i, f"service/{biz}/indicator/{i}")
for tab, name in NET_TABS.items():
    for i in NET_IDS[tab]:
        collect("network", name, i, f"net/tab/{tab}/indicator/{i}")

print("=== 全量页签指标（%d 条记录）===" % len(rows))
print("%-8s %-16s %-5s %-6s %-19s %-7s %s" % ("scope", "tab", "id", "mon", "codes", "period", "filter"))
for r in rows:
    print("%-8s %-16s %-5s %-6s %-19s %-7s %s" % (
        r["scope"], r["tab"], r["id"], r["mon"], (",".join(r["codes"]) or "-")[:19], r["period"], r["filter"]))

print()
print("=== 按 (mon, filter) 分组统计（决定批量取数的分组数）===")
grp = {}
for r in rows:
    for c in r["codes"]:
        grp.setdefault((r["mon"], r["filter"]), set()).add(c)
for (mon, f), codes in sorted(grp.items(), key=lambda x: (x[0][0] is None, x[0][0] or 0, x[0][1])):
    print("  mon=%-7s filter=%-40s codes=%d" % (mon, f[:40], len(codes)))
print("  合计取数分组:", len(grp), " 去重指标:", sum(len(v) for v in grp.values()))

print()
print("=== 多列指标（一次请求返回多列）===")
for r in rows:
    if len(r["codes"]) > 1:
        print("  %-16s id=%-5s %s" % (r["tab"], r["id"], r["codes"]))

uniq = {}
for r in rows:
    for c in r["codes"]:
        uniq.setdefault((r["mon"], c, r["filter"]), set()).add("%s:%s" % (r["scope"][0].upper(), r["tab"]))
print()
print("=== 去重指标总数: %d ===" % len(uniq))
json.dump({"rows": rows, "distinct": [{"mon": m, "code": c, "filter": f, "tabs": sorted(t)}
                                      for (m, c, f), t in uniq.items()]},
          open(ROOT / "_tmp_tab_catalog.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写 _tmp_tab_catalog.json")
