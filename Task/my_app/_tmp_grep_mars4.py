# -*- coding: utf-8 -*-
"""Find encryptData implementation + RSA public key in mars bundle."""
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js = open(r"d:\01_RPA\Task\my_app\_tmp_mars_main.js", encoding="utf-8").read()

for kw in ("encryptData", "MIIBIjANBgkqhkiG9w0BAQ", "setPublicKey", "JSEncrypt"):
    print("###", kw)
    hits = [m.start() for m in re.finditer(re.escape(kw), js)]
    print("hits:", len(hits))
    for i in hits[:3]:
        frag = js[max(0, i - 300): i + 500]
        frag = re.sub(r"\s+", " ", frag)
        print(frag[:700])
        print("-" * 60)
