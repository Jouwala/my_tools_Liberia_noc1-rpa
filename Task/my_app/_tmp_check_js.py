# -*- coding: utf-8 -*-
"""抽出 vmax_cxo_dashboard_daily.html 的内联 JS 交给 node --check 做语法校验。"""
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
for name in ("vmax_cxo_dashboard_daily.html", "vmax_cxo_dashboard.html"):
    html = (ROOT / "frontend/public" / name).read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    js = "\n;\n".join(blocks)
    tmp = ROOT / "_tmp_inline_check.js"
    tmp.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    print("%-34s scriptBlocks=%d jsLen=%d node --check exit=%s" % (name, len(blocks), len(js), r.returncode))
    if r.returncode:
        print(r.stderr[:1200])
    tmp.unlink(missing_ok=True)
