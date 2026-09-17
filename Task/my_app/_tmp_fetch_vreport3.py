# -*- coding: utf-8 -*-
"""Fetch vreport key modules: statement, vReportConstant, time_component; grep server URLs."""
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
    WEB + "/scripts/vReportConstant.js",
    WEB + "/template/statement.js",
    WEB + "/template/assembly/time_component.js",
]
for m in mods:
    s, js = get(m)
    print("=" * 72)
    print("[%s] %s len=%d" % (m.split("/")[-1], s, len(js)))
    eps = sorted(set(re.findall(r'["\'](/rdk/service/[^"\']+|/vreport[^"\']*)["\']', js)))
    for e in eps:
        print("   endpoint:", e)
    # 时间粒度相关
    for kw in ("granularity", "timeType", "time_type", "day", "hour"):
        hits = re.findall(r'.{0,60}%s.{0,60}' % kw, js)
        if hits:
            print("   [%s] %d hits, e.g.:" % (kw, len(hits)))
            for h in hits[:4]:
                print("      ", h.replace("\n", " ")[:130])
