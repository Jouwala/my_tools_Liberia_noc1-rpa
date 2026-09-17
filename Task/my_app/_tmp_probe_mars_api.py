# -*- coding: utf-8 -*-
"""Probe mars /query/v2 APIs (unencrypted GETs) to find monitor tree."""
import json
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def call(path, method="GET", body=None, timeout=30):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:200]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for p in (
    "/query/v2/webPath?filter=1",
    "/query/v2/webMonitor?filter=1",
):
    st, b = call(p)
    print("=== %s -> %s len=%d" % (p, st, len(b)))
    if st == 200:
        try:
            j = json.loads(b)
            print("code:", j.get("code"), "msg:", j.get("msg"))
            d = j.get("data")
            print("data preview:", json.dumps(d, ensure_ascii=False)[:1200])
        except Exception:
            print(b[:400])
    time.sleep(2)
