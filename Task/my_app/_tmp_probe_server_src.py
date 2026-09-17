# -*- coding: utf-8 -*-
"""Probe dashboard server-side ECMA module source files."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
APP = "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server"


def get(path, timeout=20):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:100]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

candidates = [
    APP + "/Summary/getTrendAnalysis.js",
    APP + "/Summary.js",
    APP + "/summary/getTrendAnalysis.js",
    APP + "/getTrendAnalysis.js",
    APP + "/Summary/getTrendAnalysis/index.js",
    APP + "/utils/dbCommonConfig.js",
    APP + "/dbCommonConfig.js",
    APP + "/",
    APP + "/Service/getIndicatorData.js",
    APP + "/network/getDelimitPie.js",
]
for p in candidates:
    s, b = get(p)
    print("%-95s -> %s len=%d" % (p.replace(APP, "<APP>"), s, len(b)))
    if s == 200 and len(b) > 30:
        print(b[:1200])
        print("    ...")
