# -*- coding: utf-8 -*-
"""Fetch full portal root HTML and probe app page candidates."""
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def get(path, timeout=30):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:150]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

status, body = get("/")
print("[root]", status, "len", len(body))
for m in re.finditer(r'src="([^"]+)"', body):
    print("  script:", m.group(1))

# RDK 常见 app 页面路径尝试
candidates = [
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/main.html",
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/view.html",
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/app.js",
    "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/dbCommonConfig.js",
]
for p in candidates:
    s, b = get(p)
    print("%-88s -> %s len=%d" % (p, s, len(b)))
    if s == 200 and len(b) > 100:
        print(b[:800])
        print("   ...")
