# -*- coding: utf-8 -*-
"""Fetch VMAX portal dashboard page to discover app structure and JS bundles."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def get(path):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:150]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

candidates = [
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/index.html",
    "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/index.html",
    "/web/index.html",
    "/web/",
    "/",
]
for p in candidates:
    status, body = get(p)
    print("%-80s -> %s len=%d" % (p, status, len(body)))
    if status == 200 and len(body) > 200:
        print(body[:600])
        print("...")
        break
