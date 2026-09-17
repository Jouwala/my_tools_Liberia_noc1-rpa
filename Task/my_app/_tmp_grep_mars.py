# -*- coding: utf-8 -*-
"""Extract server endpoint strings from mars main bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()
eps = sorted(set(re.findall(r'[\"\'](/rdk/service/[A-Za-z0-9_/.\-]+)[\"\']', js)))
print("rdk/service endpoints:", len(eps))
for e in eps:
    print("  ", e)
print()
# 相对 service 调用
eps2 = sorted(set(re.findall(r'[\"\']((?:server|service)/[A-Za-z0-9_/.\-]{3,60})[\"\']', js)))
print("server/... relative:", len(eps2))
for e in eps2[:60]:
    print("  ", e)
# granularity / time 参数
for kw in ("granularity", "monitorid", "kpiCode"):
    hits = re.findall(r'.{0,50}%s.{0,50}' % kw, js)
    print()
    print("[%s] %d hits" % (kw, len(hits)))
    for h in hits[:5]:
        print("   ", h.replace("\n", " ")[:110])
