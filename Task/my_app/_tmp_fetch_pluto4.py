# -*- coding: utf-8 -*-
"""Dump full entrance main.js to find iframe src building logic."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"

url = PROXY_BASE + urllib.parse.quote(
    TARGET + "/rdk/app/insight/web/entrance/main.js", safe="")
with urllib.request.urlopen(url, timeout=30) as r:
    body = r.read().decode("utf-8", "replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(body[1500:])
