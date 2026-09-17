# -*- coding: utf-8 -*-
"""Dump full dbCommonConfig.js."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
P = ("/rdk/service/app/insight/realtimeguarantee/"
     "ds_dashboard_Overseas/server/utils/dbCommonConfig.js")

url = PROXY_BASE + urllib.parse.quote(VMAX + P, safe="")
with urllib.request.urlopen(url, timeout=30) as r:
    body = r.read().decode("utf-8", "replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
open(r"d:\01_RPA\Task\my_app\_tmp_dbconfig.json", "w", encoding="utf-8").write(body)
j = json.loads(body)
print("top keys:", list(j.keys()))
# 找 Summary trend 相关配置
def walk(o, path=""):
    if isinstance(o, dict):
        s = json.dumps(o, ensure_ascii=False)
        if "day-7" in s or "dayID" in s or ("granularity" in o) or "Trend" in (o.get("label") or ""):
            print("HIT at", path, ":", s[:800])
            return True
        for k, v in o.items():
            walk(v, path + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + "[%d]" % i)

walk(j)
