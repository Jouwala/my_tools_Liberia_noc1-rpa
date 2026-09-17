# -*- coding: utf-8 -*-
"""Grep portal main.js for server endpoints and app menu API."""
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:150]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s, js = get("/rdk/app/portal/web/main.e2b1dad3ffe0d9173deb.bundle.js")
eps = sorted(set(re.findall(r'"(/rdk/service/[^"]+)"', js)))
print("rdk/service endpoints in portal bundle:", len(eps))
for e in eps[:80]:
    print("  ", e)
print()
eps2 = sorted(set(re.findall(r'"(/web/[^"]+)"', js)))
print("/web/ endpoints:", len(eps2))
for e in eps2[:60]:
    print("  ", e)
