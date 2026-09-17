# -*- coding: utf-8 -*-
"""Fetch monitor 250005 design.json."""
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(p, timeout=30):
    url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:120]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

candidates = [
    "/rdk/app/mars/web/mars_home/custom_250005/design.json",
    "/mars_home/custom_250005/design.json",
    "/rdk/app/mars/web/mars_home/custom_250005/design.json?v=1",
]
for p in candidates:
    st, b = get(p)
    print("%-70s -> %s len=%d" % (p, st, len(b)))
    if st == 200 and len(b) > 100:
        open(r"d:\01_RPA\Task\my_app\_tmp_design_250005.json", "w", encoding="utf-8").write(b)
        print("SAVED")
        print(b[:1500])
        break
    time.sleep(1)
