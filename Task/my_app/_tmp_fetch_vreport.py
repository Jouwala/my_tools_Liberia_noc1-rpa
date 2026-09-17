# -*- coding: utf-8 -*-
"""Fetch vreport (pluto) app page; find bundles."""
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:100]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s, html = get("/rdk/app/vreport/web/index.html")
print("[vreport index]", s, "len", len(html))
for m in re.finditer(r'(?:src|href)="([^"]+)"', html):
    print("  asset:", m.group(1))
print(html[:1200])
