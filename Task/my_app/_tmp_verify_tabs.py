# -*- coding: utf-8 -*-
"""校验页签树与 KPI_SPECS 的一致性，并核对与参考看板 manifest 是否逐条对齐。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from backend.services.vmax_cxo_daily_cache import (  # noqa: E402
    KPI_SPECS, KPI_TABS, TAB_ORDER, build_tab_tree, _FILTER_MODEL)

SERVICE_MANIFEST = {
    "Mobility": [391, 392, 393], "Voice": [412, 413, 414],
    "Data": [431, 433, 434], "Video": [451],
    "SMS": [202, 204, 205, 206, 207, 208],
    "Web Browse": [221, 223, 224, 225, 226, 227, 228],
    "Game": [242, 243, 244, 245], "OTTVoice": list(range(262, 273)),
    "OTTVideo": [282, 283],
}
NET_TABS = {1: ("Mobility", [391, 392, 393]), 2: ("Service Request", [411, 412, 413, 414]),
            3: ("Accessibility", [431, 433, 434]), 4: ("Retainability", [451]),
            5: ("InterWorking", [471, 472, 473])}

ok = fail = 0


def check(cond, label, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + label)
    else:
        fail += 1
        print("  FAIL  %s  %s" % (label, extra))


print("=== A) 规模与一致性 ===")
check(len(KPI_SPECS) == 50, "KPI_SPECS = 50 个", len(KPI_SPECS))
missing_tabs = [k for k in KPI_SPECS if k not in KPI_TABS]
check(not missing_tabs, "每个 KPI 都有页签归属", missing_tabs)
ghost = [k for k in KPI_TABS if k not in KPI_SPECS]
check(not ghost, "KPI_TABS 没有悬空 id", ghost)
codes = [(s["monitorid"], s["code"]) for s in KPI_SPECS.values()]
dupe = {c for c in codes if codes.count(c) > 1}
print("  同一 (monitor,code) 出现多次（不同过滤配方属正常）:", len(dupe))

print()
print("=== B) 与参考看板 manifest 对齐（按 code 比较，id 可能沿用既有编号）===")
tree = {t["key"]: t for t in build_tab_tree()}


def codes_of(ids):
    return sorted({(KPI_SPECS[i]["monitorid"], KPI_SPECS[i]["code"]) for i in ids if i in KPI_SPECS})


board_codes = {}          # 参考看板的 (monitor, code) 归属
for biz, ids in SERVICE_MANIFEST.items():
    board_codes.setdefault(("service", biz), set())
for _, (name, ids) in sorted(NET_TABS.items()):
    board_codes.setdefault(("network", name), set())

# 参考看板 manifest 里的 id -> code 取自 last_known_good 的实测目录
import json as _json  # noqa: E402
_cat = _json.loads(open("_tmp_tab_catalog.json", encoding="utf-8").read())["rows"]
for r in _cat:
    key = (r["scope"], r["tab"])
    for c in r["codes"]:
        board_codes.setdefault(key, set()).add((r["mon"], c))

for scope in ("service", "network"):
    for sub in tree[scope]["subtabs"]:
        want = sorted(board_codes.get((scope, sub["key"]), set()))
        got = codes_of(sub["kpis"])
        check(got == want, "%s/%s 指标集合一致（%d 个）" % (scope, sub["key"], len(want)),
              "got=%s want=%s" % (got, want))
check(sorted(tree["summary"]["kpis"]) == ["91", "92", "93", "94", "95", "99"],
      "summary = 原 6 个趋势 KPI", tree["summary"]["kpis"])

print()
print("=== C) 页签树结构 ===")
for t in build_tab_tree():
    if t["subtabs"]:
        print("  %-8s 子页签 %d 个: %s" % (t["key"], len(t["subtabs"]),
              ", ".join("%s(%d)" % (s["key"], len(s["kpis"])) for s in t["subtabs"])))
    else:
        print("  %-8s 指标 %d 个: %s" % (t["key"], len(t["kpis"]), ",".join(t["kpis"])))
allp = set()
for t in build_tab_tree():
    allp |= set(t["kpis"])
    for s in t["subtabs"]:
        allp |= set(s["kpis"])
check(len(allp) == 50, "50 个指标全部能通过页签访问", len(allp))

print()
print("=== D) 批量取数分组（请求数）===")
groups = {}
for kid, spec in KPI_SPECS.items():
    fm = spec.get("filter_model") or _FILTER_MODEL
    groups.setdefault((spec["monitorid"], json.dumps(fm, sort_keys=True)), []).append(spec["code"])
for (mon, fsig), cs in sorted(groups.items(), key=lambda x: x[0][0]):
    tag = "空过滤" if '"filterModelList":[]' in fsig.replace(" ", "") else "interfaceid+rat"
    print("  mon=%-7s %-15s codes=%d" % (mon, tag, len(set(cs))))
print("  -> 每个同步周期只需 %d 个请求（单指标逐个请求则需 %d 个）" % (len(groups), len(KPI_SPECS)))

print()
print("===== %d passed, %d failed =====" % (ok, fail))
sys.exit(1 if fail else 0)
