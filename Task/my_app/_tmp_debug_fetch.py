# -*- coding: utf-8 -*-
"""Debug single fetch with full error output."""
import sys
import traceback
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
p = "/rdk/app/vreport/web/scripts/utils.js"
url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
try:
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
        print("OK", r.status, len(body))
except Exception:
    tb = traceback.format_exc()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(tb[:2000])
