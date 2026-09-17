# -*- coding: utf-8 -*-
"""Fetch portal main.js bundle and extract app names / rdk service paths."""
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
print("[main.js]", s, "len", len(js))

# 找 rdk 应用路径引用
apps = sorted(set(re.findall(r'rdk/app/[A-Za-z0-9_/.\-]+', js)))
print("rdk/app refs:", len(apps))
for a in apps[:60]:
    print("  ", a)

# 找 insight 应用名
apps2 = sorted(set(re.findall(r'insight/[A-Za-z0-9_/.\-]+', js)))
print("insight refs:", len(apps2))
for a in apps2[:60]:
    print("  ", a)
