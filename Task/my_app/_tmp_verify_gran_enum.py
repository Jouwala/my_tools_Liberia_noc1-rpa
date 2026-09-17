# -*- coding: utf-8 -*-
"""枚举 mars /query/v2/history 的 granularity 合法值（错误信息可判定；先锚定 15min 已知可用）。"""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
USER_NAME = "ZeeshanM"
PUB_B64 = ("MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/h5K+Yr5VRtCyeg3g85xbi91K4hc"
           "XehTtkPOZaC19SGyrNGzq8WmvGLbbvcU7NcpJ0I/cdg0sAcbcPlt/Q/RofmYgpD0gCK"
           "z2ZIpgcAszndY0DjKhOGbNPnoIRO9ln3giPqCIfdzF8MUCgIGVLWK1ha7STUwdAFZkb"
           "z45X4KVkwIDAQAB")
_KEY = load_der_public_key(base64.b64decode(PUB_B64))
_ROOT = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def enc(text):
    d = text.encode("utf-8")
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
qp = cache["keys"]["summary/trend_91"]["data"]["queryParam"]
today = date.today()
start = today - timedelta(days=3)
end = today + timedelta(days=1)


def call(gran, period, timeout=120):
    cond = {
        "condition": {
            "filterListModel": qp["filterListModel"],
            "showColumns": qp["showColumns"],
            "times": {"lastTime": "%s 00:00:00" % start, "endTime": "%s 00:00:00" % end,
                      "granularity": gran, "period": period, "type": 2},
            "size": 10000,
        },
        "uid": 0, "sceneid": "3", "monitorid": qp["monitorid"], "userName": USER_NAME,
    }
    r = post(VMAX + "/query/v2/history", {"param": enc(json.dumps(cond, separators=(",", ":")))}, timeout)
    inner = r.get("data") if isinstance(r.get("data"), dict) else {}
    rows = inner.get("data") or []
    return r.get("code"), str(r.get("msg") or "")[:110], rows


CANDIDATES = ["15min", "1hour", "1hour", "day", "1 Day", "1DAY", "1d", "d", "DAY", "daily",
              "1day", "week", "1week", "month", "min", "hour"]
seen = set()
for gran in CANDIDATES:
    if gran in seen:
        continue
    seen.add(gran)
    try:
        code, msg, rows = call(gran, 4)
        stamps = sorted({r[0][:10] for r in rows})[:5] if rows else []
        print("%-8s -> code=%s msg=%-70s rows=%-4d dates=%s" % (gran, code, msg, len(rows), stamps), flush=True)
        if rows:
            for r in rows[:6]:
                print("        ", json.dumps(r, ensure_ascii=False)[:120], flush=True)
    except Exception as e:
        print("%-8s -> EXC %s %s" % (gran, type(e).__name__, str(e)[:120]), flush=True)
    time.sleep(1)
