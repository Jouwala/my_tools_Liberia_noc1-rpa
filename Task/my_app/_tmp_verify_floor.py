# -*- coding: utf-8 -*-
"""钉死数据地板：只查 09-01..09-09 窗口，看返回的最早日期。1 次调用。"""
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


qp = json.loads((_ROOT / "data/cxo_dashboard/last_known_good.json").read_text(encoding="utf-8"))[
    "keys"]["summary/trend_91"]["data"]["queryParam"]

for gran, last, endd, per in (("1hour", "2026-09-01 00:00:00", "2026-09-09 00:00:00", 8 * 24),
                              ("15min", "2026-09-04 00:00:00", "2026-09-10 00:00:00", 6 * 96)):
    cond = {"condition": {
        "filterListModel": qp["filterListModel"], "showColumns": qp["showColumns"],
        "times": {"lastTime": last, "endTime": endd, "granularity": gran, "period": per, "type": 2},
        "size": 10000},
        "uid": 0, "sceneid": "3", "monitorid": qp["monitorid"], "userName": "ZeeshanM"}
    url = PROXY_BASE + urllib.parse.quote(VMAX + "/query/v2/history", safe="")
    req = urllib.request.Request(url, data=json.dumps({"param": enc(json.dumps(cond, separators=(",", ":")))}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
        rows = ((resp.get("data") or {}).get("data")) or []
        ds = sorted({x[0][:10] for x in rows})
        print("%s %s..%s -> code=%s rows=%d 日期数=%d 最早=%s 最晚=%s" % (
            gran, last[:10], endd[:10], resp.get("code"), len(rows), len(ds),
            ds[0] if ds else "-", ds[-1] if ds else "-"), flush=True)
    except Exception as e:
        print("%s FAIL %s %s" % (gran, type(e).__name__, str(e)[:200]), flush=True)
