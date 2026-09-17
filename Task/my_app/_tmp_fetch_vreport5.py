# -*- coding: utf-8 -*-
"""Grep vreport modules for /vReport/* API endpoints across key templates."""
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
WEB = "/rdk/app/vreport/web"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:100]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mods = [
    "/template/target.js",
    "/template/dimension.js",
    "/template/vr_table.js",
    "/template/recentUsedReport.js",
    "/scripts/utils.js",
]
all_eps = {}
for m in mods:
    s, js = get(WEB + m)
    if s != 200:
        print("[%s] %s" % (m, s))
        continue
    eps = re.findall(r'[\"\'](/vReport/[^\"\']+|/rdk/service/[^\"\']+)[\"\']', js)
    for e in eps:
        all_eps.setdefault(e, set()).add(m.split("/")[-1])

for e, srcs in sorted(all_eps.items()):
    print("%-70s  (%s)" % (e, ",".join(sorted(srcs))))
