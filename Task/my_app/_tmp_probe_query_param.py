# -*- coding: utf-8 -*-
"""Dump queryParam/kpiConfig/mars of trend response to find supported params."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX_BASE = ("https://10.123.255.12:26180/rdk/service/app/insight/"
             "realtimeguarantee/ds_dashboard_Overseas/server")
BASE = {"province_id": "", "city_id": "", "area_id": ""}


def post(endpoint, body):
    url = PROXY_BASE + urllib.parse.quote(VMAX_BASE + endpoint, safe="")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

resp = post("/Summary/getTrendAnalysis", {**BASE, "graphId": "91"})
print("queryParam:", json.dumps(resp.get("queryParam"), ensure_ascii=False, indent=1)[:1500])
print()
print("kpiConfig:", json.dumps(resp.get("kpiConfig"), ensure_ascii=False, indent=1)[:2000])
print()
mars = resp.get("mars")
print("mars type:", type(mars).__name__)
if isinstance(mars, (dict, list)):
    print("mars:", json.dumps(mars, ensure_ascii=False, indent=1)[:1500])
else:
    print("mars:", str(mars)[:500])
# option 的 time 相关字段
opt = resp.get("option") or {}
print()
print("option keys:", list(opt.keys()))
