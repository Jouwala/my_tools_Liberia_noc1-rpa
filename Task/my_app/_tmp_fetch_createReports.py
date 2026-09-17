# -*- coding: utf-8 -*-
"""Save createReports.js + popupService.js, grep endpoints."""
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def save(p, dest):
    url = PROXY_BASE + urllib.parse.quote(VMAX + p, safe="")
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            open(dest, "w", encoding="utf-8").write(body)
            print("saved", dest, len(body))
            return
        except Exception as e:
            time.sleep(4)
    print("FAILED", p)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

save("/rdk/app/vreport/web/template/createReports.js",
     r"d:\01_RPA\Task\my_app\_tmp_createReports.js")
time.sleep(2)
save("/rdk/app/vreport/web/template/popupService.js",
     r"d:\01_RPA\Task\my_app\_tmp_popupService.js")
