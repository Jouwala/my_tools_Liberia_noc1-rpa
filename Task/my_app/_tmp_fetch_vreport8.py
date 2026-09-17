# -*- coding: utf-8 -*-
"""Comprehensive endpoint search in vreport JS modules (drill/data/query)."""
import re
import sys
import time
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
        time.sleep(5)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except Exception as e2:
            return getattr(e2, "code", "ERR"), str(e2)[:100]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

mods = [
    "/scripts/utils.js",
    "/template/assembly/time_component.js",
    "/template/assembly/tree_component.js",
    "/template/assembly/dapUserUtil.js",
    "/template/assembly/log_component.js",
]
seen = {}
import time
for m in mods:
    time.sleep(2)
    s, js = get(WEB + m)
    if s != 200:
        print("[%s] %s" % (m, s))
        continue
    # 所有 /xxx/ 路径字符串（相对和绝对）
    for e in re.findall(r'[\"\'](/[A-Za-z][A-Za-z0-9_/.\-]{3,60})[\"\']', js):
        if any(k in e.lower() for k in ("vreport", "rdk/service", "drill", "data", "query", "chart", "report")):
            seen.setdefault(e, set()).add(m.split("/")[-1])

for e, srcs in sorted(seen.items()):
    print("%-72s (%s)" % (e, ",".join(sorted(srcs))))
