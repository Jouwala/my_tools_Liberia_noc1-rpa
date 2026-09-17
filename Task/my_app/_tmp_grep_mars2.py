# -*- coding: utf-8 -*-
"""Extract /api/ and service URL patterns from mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()
eps = sorted(set(re.findall(r'[\"\'](/api/[A-Za-z0-9_/.\-]{2,70})[\"\']', js)))
print("/api/ endpoints:", len(eps))
for e in eps:
    print("  ", e)
print()
# http.get/post("/xxx") 模式
eps2 = sorted(set(re.findall(r'(?:get|post|put)\([\"\'](/[A-Za-z][A-Za-z0-9_/.\-]{2,70})[\"\']', js)))
print("http verb endpoints:", len(eps2))
for e in eps2[:80]:
    print("  ", e)
