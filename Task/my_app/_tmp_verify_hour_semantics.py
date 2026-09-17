# -*- coding: utf-8 -*-
"""核对小时行口径：92 Active User / 93 Throughput 的 @1hour 与本地 @15min day-1 对比。只读。"""
import base64
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
PUB_B64 = ("MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/h5K+Yr5VRtCyeg3g85xbi91K4hc"
           "XehTtkPOZaC19SGyrNGzq8WmvGLbbvcU7NcpJ0I/cdg0sAcbcPlt/Q/RofmYgpD0gCK"
           "z2ZIpgcAszndY0DjKhOGbNPnoIRO9ln3giPqCIfdzF8MUCgIGVLWK1ha7STUwdAFZkb"
           "z45X4KVkwIDAQAB")
_KEY = load_der_public_key(base64.b64decode(PUB_B64))
_ROOT = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def enc(t):
    d = t.encode("utf-8")
    hx = ""
    for i in range(0, len(d), 117):
        hx += _KEY.encrypt(d[i:i + 117], padding.PKCS1v15()).hex()
    return base64.b64encode(bytes.fromhex(hx)).decode()


def post(target, body, timeout=120):
    url = PROXY_BASE + urllib.parse.quote(target, safe="")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


cache = json.loads((_ROOT / "data/cxo_dashboard/last_known_good.json").read_text(encoding="utf-8"))
keys = cache["keys"]
DAY = "2026-09-14"

for gid in ("91", "92", "93"):
    d = keys["summary/trend_%s" % gid]["data"]
    qp = d["queryParam"]
    cond = {"condition": {"filterListModel": qp["filterListModel"], "showColumns": qp["showColumns"],
            "times": {"lastTime": "%s 00:00:00" % DAY, "endTime": "2026-09-15 00:00:00",
                      "granularity": "1hour", "period": 24, "type": 2}, "size": 10000},
            "uid": 0, "sceneid": "3", "monitorid": qp["monitorid"], "userName": "ZeeshanM"}
    resp = post(VMAX + "/query/v2/history", {"param": enc(json.dumps(cond, separators=(",", ":")))})
    rows = [row for row in (((resp.get("data") or {}).get("data")) or []) if row[0].startswith(DAY)]
    vals = []
    for row in rows:
        try:
            vals.append(float(row[1]))
        except (TypeError, ValueError):
            pass
    ser = {s.get("name"): (s.get("data") or []) for s in (d.get("option") or {}).get("series") or []}
    q15 = []
    for x in ser.get("day-1") or []:
        try:
            q15.append(float(x))
        except (TypeError, ValueError):
            pass
    print("=== trend %s %s" % (gid, d.get("showName")), flush=True)
    print("  15min(option day-1) n=%d sum=%.1f avg=%.2f max=%.2f" % (
        len(q15), sum(q15), (sum(q15) / len(q15) if q15 else 0), max(q15) if q15 else 0), flush=True)
    print("  1hour(mars raw)     n=%d sum=%.1f avg=%.2f max=%.2f  code=%s" % (
        len(vals), sum(vals), (sum(vals) / len(vals) if vals else 0), max(vals) if vals else 0,
        resp.get("code")), flush=True)
    print("  hourly head:", json.dumps(rows[:4], ensure_ascii=False), flush=True)
