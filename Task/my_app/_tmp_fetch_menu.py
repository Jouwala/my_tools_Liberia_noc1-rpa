# -*- coding: utf-8 -*-
"""Call portal menu_parse to discover all insight apps (dashboard modules)."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
TARGET = "https://10.123.255.12:26180"


def post(path, body):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get(path):
    url = PROXY_BASE + urllib.parse.quote(TARGET + path, safe="")
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    j = post("/rdk/service/app/portal/server/menu_parse", {})
    s = json.dumps(j, ensure_ascii=False)
    print("menu_parse len:", len(s))
    open(r"d:\01_RPA\Task\my_app\_tmp_menu.json", "w", encoding="utf-8").write(s)
    print(s[:3000])
except Exception as e:
    print("menu_parse POST failed:", e)

try:
    j = post("/rdk/service/app/portal/server/config", {})
    print("config:", json.dumps(j, ensure_ascii=False)[:2000])
except Exception as e:
    print("config failed:", e)
