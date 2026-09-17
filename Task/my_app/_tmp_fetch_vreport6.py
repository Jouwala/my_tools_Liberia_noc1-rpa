# -*- coding: utf-8 -*-
"""Grep vreport utils.js + vr_table.js + statement.js for query/data call patterns."""
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

for m in ("/scripts/utils.js", "/template/statement.js", "/template/vr_table.js"):
    s, js = get(WEB + m)
    print("=" * 76)
    print("[%s] %s len=%d" % (m, s, len(js)))
    # DataSourceService 用法
    for mm in re.finditer(r'DataSourceService\.(?:syncQuery|query|create)\(([^;]{0,220})', js):
        frag = re.sub(r"\s+", " ", mm.group(0))
        print("  DS:", frag[:200])
    # mutildata / reportview 调用
    for mm in re.finditer(r'[\"\'](/vReport/[^\"\']+)[\"\']', js):
        print("  EP:", mm.group(1))
