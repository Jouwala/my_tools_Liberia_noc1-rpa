# -*- coding: utf-8 -*-
"""Call insight menu_parse to find pluto component page."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def call(path, method="GET"):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    data = b"{}" if method == "POST" else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

raw = call("/rdk/service/app/insight/server/menu_parse", "POST")
open(r"d:\01_RPA\Task\my_app\_tmp_insight_menu.json", "w", encoding="utf-8").write(raw)
print(raw[:4000])
