# -*- coding: utf-8 -*-
"""盘点 VMAX CXO 缓存里已有的全部指标（monitorid + 列码 + 名称 + 单位），
为「天粒度还能扩展哪些指标」给出事实清单。只读 data/cxo_dashboard/last_known_good.json。"""
import json
import sys
from collections import OrderedDict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
LK = ROOT / "data" / "cxo_dashboard" / "last_known_good.json"
doc = json.loads(LK.read_text(encoding="utf-8"))
keys = doc.get("keys") or {}
print("文件 updated_at:", doc.get("updated_at"), "| 条目数:", len(keys))

rows = OrderedDict()
for k, v in keys.items():
    data = (v or {}).get("data") or {}
    # 两种形态：trend_* 用 data.queryParam；service|network/indicator 用 data.queryData.queryParam
    qp = data.get("queryParam") or ((data.get("queryData") or {}).get("queryParam")) or {}
    mon = qp.get("monitorid")
    cols = qp.get("showColumns") or []
    code = cols[1] if len(cols) > 1 else None
    if not mon or not code:
        continue
    # 指标名与单位：优先 mars.header，再 kpiConfig / data.title
    name, unit, div = None, None, None
    mars = data.get("mars") or (data.get("queryData") or {}).get("mars") or []
    blocks = mars if isinstance(mars, list) else [mars]
    for b in blocks:
        d = (b or {}).get("data") or {}
        hdr = d.get("header") or []
        fld = d.get("field") or []
        if code in fld:
            idx = fld.index(code)
            if idx < len(hdr):
                name = hdr[idx]
            break
    kc = data.get("kpiConfig") or {}
    if isinstance(kc, dict):
        unit = kc.get("unit")
        div = kc.get("unitChange")
        name = name or kc.get("showName")
    name = name or data.get("title")
    if isinstance(name, dict):
        name = name.get("en") or name.get("zh") or name.get("name") or "?"
    kind = "/".join(k.split("/")[:2])
    rows.setdefault((str(mon), code), {"keys": [], "name": name, "unit": unit, "div": div, "kind": kind})
    rows[(str(mon), code)]["keys"].append(k)

print("\n== 可复用的时间序列指标（monitorid + 列码 去重）==")
print("%-9s %-16s %-48s %-12s %-12s %s" % ("monitor", "code", "name", "unit", "unitChange", "来源"))
n = 0
for (mon, code), info in sorted(rows.items()):
    n += 1
    print("%-9s %-16s %-48s %-12s %-12s %s" % (
        mon, code, (info["name"] or "?")[:46], info["unit"] or "-", info["div"] or "-",
        ",".join(sorted({i.split("/")[1] if "/" in i else i for i in info["keys"]}))[:26]))
print("\n合计去重指标数:", n, "| 涉及 monitorid:", sorted({m for m, _ in rows}))
print("\n== 非时间序列条目（无日粒度语义，供参考）==")
for k, v in keys.items():
    data = (v or {}).get("data") or {}
    if not ((data.get("queryParam") or {}).get("monitorid")):
        print("  ", k, "| fields:", list(data)[:6])
