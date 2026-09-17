# -*- coding: utf-8 -*-
"""Find granularity option values in mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()
# 找 granularity 枚举定义
for pat in (r'granularity[\"\':\s]{0,4}(?:=|:)\s*\[([^\]]{0,400})\]',
            r'\[?\{[^{}\[]{0,80}granularity[^{}\]]{0,200}\}',
            r'[\"\'](15min|1hour|hour|day|week|month|1min|5min|30min)[\"\']'):
    print("### pattern:", pat[:60])
    hits = re.findall(pat, js)
    uniq = sorted(set(map(str, hits)))[:30]
    print("count:", len(hits))
    for h in uniq[:20]:
        s = str(h)[:220]
        print("  ", s)
    print()
