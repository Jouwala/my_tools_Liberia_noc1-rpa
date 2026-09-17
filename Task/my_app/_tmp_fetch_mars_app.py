# -*- coding: utf-8 -*-
"""Fetch mars (Realtime Assurance) app index to find its query API."""
import re
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(4)
    return None, "FAILED"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s, html = get("/rdk/app/mars/web/index.html")
print("[mars index]", s, "len", len(html))
for m in re.finditer(r'(?:src|href)="([^"]+)"', html):
    print("  asset:", m.group(1))
