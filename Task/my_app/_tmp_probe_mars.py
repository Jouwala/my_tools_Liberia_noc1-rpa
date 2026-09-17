# -*- coding: utf-8 -*-
"""Dump per-series mars/queryParam entries."""
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
mars = resp.get("mars")
print("mars entries:", len(mars) if isinstance(mars, list) else "n/a")
for i, m in enumerate(mars or []):
    code = (m or {}).get("code")
    msg = (m or {}).get("msg")
    data = (m or {}).get("data") or {}
    rows = data.get("data") or []
    print("--- mars[%d] code=%s msg=%s rows=%d" % (i, code, msg, len(rows)))
    if rows:
        print("    first row:", rows[0])
        print("    last row:", rows[-1])

# option.series 里 series[0] 的 data 是 ECharts 格式，查 x 轴实际值
opt = resp.get("option") or {}
for s in opt.get("series") or []:
    markLine = s.get("markLine")
    print("series name=%s, len(data)=%d" % (s.get("name"), len(s.get("data") or [])))
