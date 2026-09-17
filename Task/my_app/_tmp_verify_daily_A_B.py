# -*- coding: utf-8 -*-
"""决定性验证（只读，3 次调用）：
A) mars /query/v2/history  granularity="1day"  22 天窗口   -> 一次拿全日粒度序列?
B) CXO /Summary/getTrendAnalysis 传 dayID/label/day 覆盖    -> 能否直接指定历史日?
"""
import base64
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX = "https://10.123.255.12:26180"
CXO_BASE = VMAX + "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server"
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
    data = text.encode("utf-8")
    hx = ""
    for i in range(0, len(data), 117):
        hx += _KEY.encrypt(data[i:i + 117], padding.PKCS1v15()).hex()
    return base64.b64encode(bytes.fromhex(hx)).decode()


def post(target, body, timeout=150):
    url = PROXY_BASE + urllib.parse.quote(target, safe="")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


cache = json.loads((_ROOT / "data/cxo_dashboard/last_known_good.json").read_text(encoding="utf-8"))
qp = cache["keys"]["summary/trend_91"]["data"]["queryParam"]
print("monitorid=%s cols=%s gr=%s" % (qp["monitorid"], qp["showColumns"], qp["granularity"]), flush=True)

today = date.today()
this_mon = today - timedelta(days=today.weekday())
start = this_mon - timedelta(days=14)          # 上上周一 2026-08-31
end = today + timedelta(days=1)                # 明天 00:00（含今天已出分区）
ndays = (end - start).days

# ---------- A) mars 1day ----------
cond = {
    "condition": {
        "filterListModel": qp["filterListModel"],
        "showColumns": qp["showColumns"],
        "times": {"lastTime": "%s 00:00:00" % start, "endTime": "%s 00:00:00" % end,
                  "granularity": "1day", "period": ndays, "type": 2},
        "size": 10000,
    },
    "uid": 0, "sceneid": "3", "monitorid": qp["monitorid"], "userName": USER_NAME,
}
try:
    r = post(VMAX + "/query/v2/history", {"param": enc(json.dumps(cond, separators=(",", ":")))})
    inner = r.get("data") if isinstance(r.get("data"), dict) else {}
    rows = inner.get("data") or []
    print("\n=== A) mars /query/v2/history 1day ===")
    print("code=%s msg=%s rows=%d field=%s" % (r.get("code"), str(r.get("msg"))[:100], len(rows), inner.get("field")))
    for row in rows[:24]:
        v = row[1] if len(row) > 1 else None
        gb = None
        try:
            gb = round(float(v) / 1073741824.0, 2)
        except (TypeError, ValueError):
            pass
        print("   %-22s raw=%-18s -> GB=%s" % (row[0], v, gb), flush=True)
except Exception as e:
    print("\n=== A) FAIL %s: %s" % (type(e).__name__, str(e)[:300]), flush=True)

# ---------- B) CXO getTrendAnalysis dayID/day 覆盖 ----------
BASE = {"province_id": "", "city_id": "", "area_id": ""}
monstr = "%s 23:59:59" % (this_mon - timedelta(days=14))
for extra in ({"dayID": 14, "label": "day-14"},
              {"day": monstr, "label": "day-14", "dayID": 14}):
    body = {**BASE, "graphId": "91", **extra}
    tag = "B) trend91 + %s" % json.dumps(extra, ensure_ascii=False)
    try:
        r = post(CXO_BASE + "/Summary/getTrendAnalysis", body, timeout=60)
        m = r.get("mars") or []
        dates = sorted({row[0][:10] for b in m for row in ((b or {}).get("data") or {}).get("data") or []})
        qpr = r.get("queryParam") or {}
        print("\n%s\ncode=%s xLen=%s xHead=%s qpr.day=%s qpr.dayID=%s | 原始行绝对日期=%s" % (
            tag, r.get("code"), len(r.get("xData") or []), (r.get("xData") or [])[:2],
            qpr.get("day"), qpr.get("dayID"), dates), flush=True)
    except Exception as e:
        print("\n%s FAIL %s: %s" % (tag, type(e).__name__, str(e)[:200]), flush=True)
