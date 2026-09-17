# -*- coding: utf-8 -*-
"""Fetch insight app (pluto = Multi Dimension Analysis) page and bundles; find server endpoints."""
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

s, html = get("/rdk/app/insight/web/index.html?component=pluto")
print("[insight index]", s, "len", len(html))
srcs = re.findall(r'(?:src|href)="([^"]+)"', html)
for x in srcs:
    print("  asset:", x)

# 常见 bundle 位置
for cand in ("/rdk/app/insight/web/main.js", "/rdk/app/insight/web/app.js"):
    s2, b2 = get(cand)
    print("%-50s -> %s len=%d" % (cand, s2, len(b2)))
