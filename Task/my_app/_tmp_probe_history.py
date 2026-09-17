# -*- coding: utf-8 -*-
"""Probe /query/v2/history with replicated mars RSA encryptLong."""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"

PUB_B64 = ("MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/h5K+Yr5VRtCyeg3g85xbi91K4hc"
           "XehTtkPOZaC19SGyrNGzq8WmvGLbbvcU7NcpJ0I/cdg0sAcbcPlt/Q/RofmYgpD0gCK"
           "z2ZIpgcAszndY0DjKhOGbNPnoIRO9ln3giPqCIfdzF8MUCgIGVLWK1ha7STUwdAFZkb"
           "z45X4KVkwIDAQAB")
_KEY = load_der_public_key(base64.b64decode(PUB_B64))


def encrypt_long(text):
    data = text.encode("utf-8")
    hex_all = ""
    for i in range(0, len(data), 117):
        ct = _KEY.encrypt(data[i:i + 117], padding.PKCS1v15())
        hex_all += ct.hex()          # each chunk -> 128 bytes -> 256 hex chars
    return base64.b64encode(bytes.fromhex(hex_all)).decode()


def post(path, obj):
    url = PROXY_BASE + urllib.parse.quote(VMAX + path, safe="")
    body = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FILTER = {"filterType": "0", "filterGroupList": [{
    "filter_type": "0", "items": None, "filterType": "0",
    "filterModelList": [
        {"filed": "interfaceid", "operation": "0", "value": "11", "valueDesc": "", "id": "interfaceid"},
        {"filed": "rat", "operation": "0", "value": 6, "valueDesc": "", "id": "rat"},
    ]}]}


def history(times, columns=("clttime", "ppc400401001"), monitorid=250005):
    cond = {
        "condition": {
            "filterListModel": FILTER,
            "showColumns": list(columns),
            "times": times,
            "size": 10000,
        },
        "uid": 0, "sceneid": "3", "monitorid": monitorid,
        "userName": "ZeeshanM",
    }
    payload = {"param": encrypt_long(json.dumps(cond, separators=(",", ":")))}
    return post("/query/v2/history", payload)


# 试 1: 天粒度，前两周完整窗口
for times in (
    {"lastTime": "2026-08-31 00:00:00", "endTime": "2026-09-15 00:00:00",
     "granularity": "day", "period": "", "type": 2},
    {"lastTime": "2026-08-31 00:00:00", "endTime": "2026-09-15 00:00:00",
     "granularity": "day", "type": 0},
):
    print("=" * 70)
    print("times:", json.dumps(times))
    try:
        r = history(times)
        s = json.dumps(r, ensure_ascii=False)
        print("resp len:", len(s))
        print(s[:1500])
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:300])
    time.sleep(3)
