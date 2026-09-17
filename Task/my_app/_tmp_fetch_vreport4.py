# -*- coding: utf-8 -*-
"""Find full vreport query endpoints and request structure."""
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

s, js = get(WEB + "/template/statement.js")
# 找所有 DataSourceService / url / query 调用上下文
for m in re.finditer(r"url\s*[:=]\s*[\"']([^\"']+)[\"']", js):
    print("url:", m.group(1))
print()
for m in re.finditer(r"DataSourceService\.(syncQuery|query|create)\(\s*[\"']([^\"']+)[\"']", js):
    print("ds call:", m.group(0)[:120])
print()
# 查询 body 构造
idx = js.find("executeStatement")
print("executeStatement at", idx)
if idx > -1:
    print(js[idx - 200: idx + 2500])
