# -*- coding: utf-8 -*-
"""Fetch mars scripts bundle to find global encryptData."""
import re
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
p = "/rdk/app/mars/web/scripts.06a0ecc50e5c0439c760.bundle.js"
url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
body = ""
for _ in range(3):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
        break
    except Exception:
        time.sleep(5)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
open(r"d:\01_RPA\Task\my_app\_tmp_mars_scripts.js", "w", encoding="utf-8").write(body)
print("saved", len(body))
i = body.find("encryptData")
print("encryptData at", i)
if i > -1:
    frag = body[max(0, i - 500): i + 1200]
    print(re.sub(r"\s+", " ", frag))
