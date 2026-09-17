# -*- coding: utf-8 -*-
"""Extract code context around /query/v2/history and /query/v2/polling in mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()

for kw in ("/query/v2/history", "/query/v2/predetect", "/query/v2/webMonitor"):
    print("=" * 76)
    print("###", kw)
    for m in re.finditer(re.escape(kw), js):
        i = m.start()
        frag = js[max(0, i - 700): i + 700]
        frag = re.sub(r"\s+", " ", frag)
        print(frag)
        print("-" * 60)
