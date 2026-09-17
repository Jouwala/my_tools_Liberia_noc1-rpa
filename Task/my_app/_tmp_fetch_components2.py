# -*- coding: utf-8 -*-
"""Try rdk module URL conventions for components (requirejs baseUrl = /rdk/app/insight/web/)."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=30):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:80]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for p in (
    "/rdk/app/insight/web/base/entrance/components",
    "/rdk/app/insight/web/base/entrance/utils",
    "/rdk/app/insight/web/entrance/components",
):
    s, b = get(p)
    print("%-60s -> %s len=%d" % (p, s, len(b)))
    if s == 200 and len(b) > 40:
        print(b[:2500])
        break
