# -*- coding: utf-8 -*-
"""Save mars main bundle; grep for query server endpoints."""
import re
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
p = "/rdk/app/mars/web/main.d9aea57266589200ba1c.bundle.js"
url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
for _ in range(3):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            body = r.read().decode("utf-8", "replace")
        break
    except Exception:
        time.sleep(5)
open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", "w", encoding="utf-8").write(body)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("saved", len(body))
