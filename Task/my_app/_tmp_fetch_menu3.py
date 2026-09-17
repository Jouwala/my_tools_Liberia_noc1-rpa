# -*- coding: utf-8 -*-
"""Save full menu_parse; list every leaf app URL."""
import json
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def call(path):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

raw = call("/rdk/service/app/portal/server/menu_parse")
open(r"d:\01_RPA\Task\my_app\_tmp_menu.json", "w", encoding="utf-8").write(raw)
j = json.loads(raw)


def walk(nodes, path=""):
    for n in nodes or []:
        label = n.get("enlabel") or n.get("zhlabel") or ""
        url = n.get("url") or ""
        if url:
            print("%-60s %s" % (label[:60], url))
        walk(n.get("nodes"), path + "/" + label)


walk(j.get("menus"))
