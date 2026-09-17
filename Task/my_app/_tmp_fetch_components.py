# -*- coding: utf-8 -*-
"""Fetch entrance components module to see pluto/mars conditions."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=30):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

body = get("/rdk/app/insight/web/base/entrance/components.js")
print(body)
