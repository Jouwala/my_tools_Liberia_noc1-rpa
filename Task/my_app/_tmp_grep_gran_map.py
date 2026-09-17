# -*- coding: utf-8 -*-
"""本地：在 mars bundle 中找 granularity 取值映射/转换（UI id -> 后端枚举）。"""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8", errors="replace").read()

print("### granularity: 赋值点")
seen = set()
for m in re.finditer(r"granularity\s*:", js):
    ctx = js[max(0, m.start() - 160):m.end() + 160]
    key = ctx[-90:]
    if key in seen:
        continue
    seen.add(key)
    print("  -", ctx.replace("\n", "\\n")[:330], flush=True)
    if len(seen) > 18:
        break

print()
print("### selectTime 用法")
seen2 = set()
for m in re.finditer(r"selectTime", js):
    ctx = js[max(0, m.start() - 200):m.end() + 200]
    key = ctx[:70]
    if key in seen2:
        continue
    seen2.add(key)
    print("  -", ctx.replace("\n", "\\n")[:400], flush=True)
    if len(seen2) > 10:
        break

print()
for pat in (r"replace\(\s*[\"']1[\"']", r"granularity\s*=\s*", r"[\"']1day[\"']\s*[,:]", r"Gr\w*\s*=\s*\{[^}]{0,200}min"):
    print("### /%s/ ->" % pat)
    for m in list(re.finditer(pat, js))[:6]:
        print("  -", js[max(0, m.start() - 180):m.end() + 180].replace("\n", "\\n")[:360], flush=True)
