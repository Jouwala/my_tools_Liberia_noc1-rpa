# -*- coding: utf-8 -*-
"""Extract granularity token enum + history query params from saved mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8", errors="replace").read()

i = js.find("granularityList=[")
print("### granularityList @", i)
print(js[i:i + 900].replace("\n", "\\n"), flush=True)
print()

for kw in ('"1day"', '"1hour"', '"1min"', '"1week"', '"1month"', 'granularity:"', 'selectPeriods', 'period:'):
    hits = [m.start() for m in re.finditer(re.escape(kw), js)]
    print("### %s -> %d hits" % (kw, len(hits)))
    for h in hits[:3]:
        print("   ", js[max(0, h - 220):h + 220].replace("\n", "\\n"), flush=True)
    print()
