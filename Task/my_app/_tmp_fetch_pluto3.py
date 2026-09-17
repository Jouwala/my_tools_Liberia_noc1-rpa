# -*- coding: utf-8 -*-
"""Fetch entrance/main.js of insight app; follow component page for pluto."""
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

for cand in (
    "/rdk/app/insight/web/entrance/main.js",
    "/rdk/app/insight/web/app/main.js",
    "/rdk/app/insight/web/entrance/main.html",
):
    s, b = get(cand)
    print("%-55s -> %s len=%d" % (cand, s, len(b)))
    if s == 200 and len(b) > 50:
        print(b[:1500])
        print("   ...")
        break
