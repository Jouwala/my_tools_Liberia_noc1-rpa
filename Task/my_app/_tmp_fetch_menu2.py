# -*- coding: utf-8 -*-
"""Try GET on menu_parse; also try menu with query params variants."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def call(path, method="GET", body=None):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:200]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for p in ("/rdk/service/app/portal/server/menu_parse",
          "/rdk/service/app/portal/server/menu_parse?menuType=all",
          "/rdk/service/app/portal/server/notice"):
    st, b = call(p)
    print("%-70s -> %s len=%d" % (p, st, len(b)))
    if st == 200 and len(b) > 50:
        print(b[:2000])
