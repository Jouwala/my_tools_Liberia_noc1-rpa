# -*- coding: utf-8 -*-
"""Quick status probe of VMAX static paths (which bundles are reachable through the proxy)."""
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATHS = [
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/web/index.html",
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/web/",
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/index.html",
    "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/main.html",
    "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/dbCommonConfig.js",
    "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/Summary/getTrendAnalysis.js",
    "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/dbCommonConfig.js",
    "/rdk/app/insight/web/index.html?component=pluto",
]
for p in PATHS:
    url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            b = r.read()
            print("%-92s -> %s len=%d" % (p, r.status, len(b)), flush=True)
    except Exception as e:
        print("%-92s -> ERR %s %s" % (p, type(e).__name__, str(e)[:120]), flush=True)
