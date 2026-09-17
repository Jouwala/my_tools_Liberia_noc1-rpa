# -*- coding: utf-8 -*-
"""Find how design.json is loaded in mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()
for kw in ("design.json", "getDimData", "webMonitor/"):
    print("###", kw)
    for m in list(re.finditer(re.escape(kw), js))[:4]:
        i = m.start()
        frag = js[max(0, i - 400): i + 400]
        print(re.sub(r"\s+", " ", frag)[:600])
        print("-" * 60)
