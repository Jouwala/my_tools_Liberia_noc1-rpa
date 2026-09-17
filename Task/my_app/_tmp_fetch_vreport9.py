# -*- coding: utf-8 -*-
"""Quick check: fetch one vreport module and count URL matches."""
import re
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except Exception as e:
            err = "%s: %s" % (getattr(e, "code", "ERR"), str(e)[:120])
            time.sleep(4)
    return None, err


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s, js = get("/rdk/app/vreport/web/scripts/utils.js")
print("utils.js:", s, "len:", len(js) if s == 200 else js)
eps = re.findall(r'[\"\'](/[A-Za-z][A-Za-z0-9_/.\-]{3,60})[\"\']', js or "")
print("matches:", len(eps))
for e in sorted(set(eps)):
    print("  ", e)
