# -*- coding: utf-8 -*-
"""Extract context around /query/v2 and granularity tokens in the saved mars bundle (local, no network)."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for fn in (r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", r"d:\01_RPA\Task\my_app\_tmp_mars_scripts.js"):
    try:
        js = open(fn, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        print("missing", fn)
        continue
    print("#" * 78)
    print(fn, "len", len(js))
    for kw in ("/query/v2", "granularity", "lastTime"):
        hits = list(re.finditer(re.escape(kw), js))
        print("== %s: %d hits" % (kw, len(hits)))
        seen = set()
        for m in hits[:14]:
            a, b = max(0, m.start() - 320), min(len(js), m.end() + 320)
            ctx = js[a:b]
            key = ctx[:80]
            if key in seen:
                continue
            seen.add(key)
            print("   ...", ctx.replace("\n", "\\n")[:640], flush=True)
        print()
