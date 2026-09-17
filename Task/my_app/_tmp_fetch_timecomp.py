# -*- coding: utf-8 -*-
"""Save time_component.js and grep drill/query endpoints."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
p = "/rdk/app/vreport/web/template/assembly/time_component.js"
url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
with urllib.request.urlopen(url, timeout=60) as r:
    body = r.read().decode("utf-8", "replace")
open(r"d:\01_RPA\Task\my_app\_tmp_timecomp.js", "w", encoding="utf-8").write(body)
print("saved", len(body))
