# -*- coding: utf-8 -*-
"""Verify the served mw_ume_orange_links.geojson matches the local built file.

Compares md5 + feature counts for both access paths (vite 7090 direct, nginx 80).
Exit code 0 = all PASS.
"""
import hashlib
import json
import sys
import urllib.request
from collections import Counter

LOCAL = r"D:\01_RPA\Task\my_app\frontend\public\mw_ume_orange_links.geojson"
DIST = r"D:\01_RPA\Task\_fe_dist\mw_ume_orange_links.geojson"
PATHS = [
    ("7090 direct", "http://localhost:7090/myapp/mw_ume_orange_links.geojson"),
    ("80 via nginx", "http://localhost/myapp/mw_ume_orange_links.geojson"),
]


def md5(b):
    return hashlib.md5(b).hexdigest()[:12]


def main():
    src = open(LOCAL, "rb").read()
    exp = md5(src)
    fc = json.loads(src.decode("utf-8"))
    cnt = Counter(f["properties"].get("kind") for f in fc["features"])
    print(f"local : md5={exp} size={len(src)} features={len(fc['features'])} {dict(cnt)}")

    dist = open(DIST, "rb").read()
    print(f"dist  : md5={md5(dist)} size={len(dist)} "
          f"{'PASS' if md5(dist) == exp else 'FAIL'}")

    ok = md5(dist) == exp
    for tag, url in PATHS:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                b = r.read()
            h = md5(b)
            n = len(json.loads(b.decode("utf-8"))["features"])
            p = "PASS" if h == exp else "FAIL"
            print(f"{tag}: {p} md5={h} size={len(b)} features={n}")
            ok = ok and h == exp
        except Exception as e:
            print(f"{tag}: FAIL {e}")
            ok = False

    print("RESULT:", "ALL PASS" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
