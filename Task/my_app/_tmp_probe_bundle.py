# -*- coding: utf-8 -*-
"""Crawl VMAX CXO dashboard front-end bundles, find how getTrendAnalysis params are built."""
import json
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
TO = 25


def get(path, timeout=TO):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), ""


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENTRY = "/rdk/app/insight/realtimeguarantee/ds_dashboard_Overseas/web/index.html"
st, html = get(ENTRY, timeout=40)
print("ENTRY", st, "len", len(html), flush=True)
if html:
    open(r"d:\01_RPA\Task\my_app\_tmp_vmax_index.html", "w", encoding="utf-8").write(html)
    srcs = re.findall(r'src\s*=\s*["\']([^"\']+\.js[^"\']*)["\']', html) + \
           re.findall(r'href\s*=\s*["\']([^"\']+\.js[^"\']*)["\']', html)
    print("SCRIPTS", json.dumps(srcs[:40]), flush=True)
    for s in srcs[:25]:
        # resolve relative to entry dir
        if s.startswith("//"):
            p = "https:" + s
            path = urllib.parse.urlsplit(p).path
        elif s.startswith("/"):
            path = s
        else:
            path = ENTRY.rsplit("/", 1)[0] + "/" + s.split("?")[0]
        st2, body = get(path)
        hit = "getTrendAnalysis" in body
        print("%-14s %s len=%-9d hit=%s" % ("FETCH", st2, len(body), hit), flush=True)
        if hit:
            fn = r"d:\01_RPA\Task\my_app\_tmp_vmax_bundle_hit.js"
            open(fn, "w", encoding="utf-8").write(body)
            for m in re.finditer(r'getTrendAnalysis', body):
                a, b = max(0, m.start() - 700), min(len(body), m.end() + 700)
                print("---- ctx", m.start(), "----", flush=True)
                print(body[a:b].replace("\n", "\\n")[:1400], flush=True)
            break
