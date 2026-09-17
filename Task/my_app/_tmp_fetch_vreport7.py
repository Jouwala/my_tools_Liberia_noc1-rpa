# -*- coding: utf-8 -*-
"""Dump statement.js sections around query execution."""
import re
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"


def get(path, timeout=60):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:100]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s, js = get("/rdk/app/vreport/web/template/statement.js")
# 查找查询执行相关函数
for kw in ("function query", "function execute", "function run", "reportview", "mutildata"):
    for m in re.finditer(re.escape(kw), js):
        i = m.start()
        frag = js[max(0, i - 100): i + 400].replace("\n", " ")
        frag = re.sub(r"\s+", " ", frag)
        print("--- [%s] @%d" % (kw, i))
        print(frag[:450])
        print()
