# -*- coding: utf-8 -*-
"""看若干原始指标条目的完整字段/量级，用于确定 unit 与个别 agg（只读）。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
cache = json.loads((ROOT / "data" / "cxo_dashboard" / "last_known_good.json").read_text(encoding="utf-8"))
keys = cache.get("keys") or {}

SAMPLES = [
    ("service/SMS/indicator/204", "TCP Average Network Site RTT"),
    ("service/SMS/indicator/205", "TCP Average Terminal Site RTT"),
    ("service/Web Browse/indicator/223", "Web DL Tput(>500KB)"),
    ("service/Web Browse/indicator/228", "Displaying Delay"),
    ("service/OTTVoice/indicator/262", "Local MOS"),
    ("service/OTTVoice/indicator/268", "Call Duration (ppb)"),
    ("service/OTTVoice/indicator/266", "Times of Local Reconnection"),
]

for key, label in SAMPLES:
    entry = keys.get(key) or {}
    data = entry.get("data") or {}
    print("=" * 100)
    print(key, "|", label)
    print("  data 字段:", sorted(data.keys()))
    for f in ("title", "name", "showName", "unit", "value", "kpiValue"):
        if f in data:
            print("   %s = %r" % (f, data[f]))
    qd = data.get("queryData") or {}
    if isinstance(qd, dict):
        print("  queryData 字段:", sorted(qd.keys()))
    opt = data.get("option") or {}
    if isinstance(opt, dict):
        ya = opt.get("yAxis")
        yal = ya if isinstance(ya, list) else [ya] if ya else []
        for y in yal:
            if isinstance(y, dict):
                print("   yAxis.name=%r  min=%r max=%r" % (y.get("name"), y.get("min"), y.get("max")))
        ser = opt.get("series") or []
        print("  series 数:", len(ser))
        for s in (ser[:2] if isinstance(ser, list) else []):
            if isinstance(s, dict):
                d = s.get("data") or []
                print("   series name=%r type=%r n=%d sample=%s" % (s.get("name"), s.get("type"), len(d), d[:4]))
        tp = opt.get("tooltip")
        if isinstance(tp, dict):
            fm = tp.get("formatter")
            print("   tooltip.formatter=%s" % (str(fm)[:160]))
    yd = data.get("yData")
    if isinstance(yd, list):
        print("  yData n=%d sample=%s" % (len(yd), yd[:5]))
    xd = data.get("xData")
    if isinstance(xd, list):
        print("  xData n=%d sample=%s" % (len(xd), xd[:3]))
