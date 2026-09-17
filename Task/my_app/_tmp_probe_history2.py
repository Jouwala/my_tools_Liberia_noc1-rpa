# -*- coding: utf-8 -*-
"""Gentle single-shot probe of /query/v2/history (day granularity)."""
import base64
import json
import sys
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
        hex_all += ct.hex()
    return base64.b64encode(bytes.fromhex(hex_all)).decode()


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FILTER = {"filterType": "0", "filterGroupList": [{
    "filter_type": "0", "items": None, "filterType": "0",
    "filterModelList": [
        {"filed": "interfaceid", "operation": "0", "value": "11", "valueDesc": "", "id": "interfaceid"},
        {"filed": "rat", "operation": "0", "value": 6, "valueDesc": "", "id": "rat"},
    ]}]}

cond = {
    "condition": {
        "filterListModel": FILTER,
        "showColumns": ["clttime", "ppc400401001"],
        "times": {"lastTime": "2026-08-31 00:00:00", "endTime": "2026-09-15 00:00:00",
                  "granularity": "day", "period": "", "type": 2},
        "size": 10000,
    },
    "uid": 0, "sceneid": "3", "monitorid": 250005,
    "userName": "ZeeshanM",
}
payload = {"param": encrypt_long(json.dumps(cond, separators=(",", ":")))}
print("payload param len:", len(payload["param"]))

url = PROXY_BASE + urllib.parse.quote(VMAX + "/query/v2/history", safe="")
req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        body = r.read().decode("utf-8", "replace")
        print("status:", r.status, "len:", len(body))
        print(body[:2000])
except Exception as e:
    print("FAIL:", type(e).__name__, str(e)[:400])
