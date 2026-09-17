# -*- coding: utf-8 -*-
"""决定性验证：22 天窗口能否经 mars 历史查询取回（含枚举日粒度成员探测 + 6 个 CXO KPI 覆盖率）。只读。"""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
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


def enc(t):
    d = t.encode("utf-8")
    hx = ""
    for i in range(0, len(d), 117):
        hx += _KEY.encrypt(d[i:i + 117], padding.PKCS1v15()).hex()
    return base64.b64encode(bytes.fromhex(hx)).decode()


def post(target, body, timeout=150):
    url = PROXY_BASE + urllib.parse.quote(target, safe="")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def hist(qp, gran, last, end, period, timeout=150):
    cond = {"condition": {
        "filterListModel": qp["filterListModel"],
        "showColumns": qp["showColumns"],
        "times": {"lastTime": last, "endTime": end, "granularity": gran, "period": period, "type": 2},
        "size": 10000},
        "uid": 0, "sceneid": "3", "monitorid": qp["monitorid"], "userName": USER_NAME}
    return post(VMAX + "/query/v2/history", {"param": enc(json.dumps(cond, separators=(",", ":")))}, timeout)


cache = json.loads((_ROOT / "data/cxo_dashboard/last_known_good.json").read_text(encoding="utf-8"))
keys = cache["keys"]
qp91 = keys["summary/trend_91"]["data"]["queryParam"]
today = date.today()
this_mon = today - timedelta(days=today.weekday())
start = this_mon - timedelta(days=14)          # 2026-08-31 上上周一
end = today + timedelta(days=1)
LAST, END = "%s 00:00:00" % start, "%s 00:00:00" % end
DAYS = (end - start).days

print("window %s -> %s (%d days)" % (LAST, END, DAYS), flush=True)

# ---------- D) 探测枚举里是否存在日粒度成员（非法值秒回，不查库） ----------
CAND = ["1min", "5min", "10min", "30min", "1hour", "2hour", "3hour", "4hour", "6hour", "8hour",
        "12hour", "24hour", "1Day", "1DAY", "24hour1", "1day", "date", "1date", "1week", "1W"]
print("\n### 枚举探测（msg=enum 表示不支持）", flush=True)
ok_tok = []
for g in CAND:
    try:
        r = hist(qp91, g, LAST, END, 1, timeout=25)
        msg = str(r.get("msg") or "")[:60]
        if r.get("code") == 0:
            ok_tok.append(g)
            print("  %-8s OK   rows=%d" % (g, len(((r.get("data") or {}).get("data")) or [])), flush=True)
        else:
            print("  %-8s code=%s %s" % (g, r.get("code"), msg), flush=True)
    except Exception as e:
        print("  %-8s EXC %s" % (g, str(e)[:70]), flush=True)
print("可用粒度:", ok_tok, flush=True)

# ---------- C) 22 天 @1hour 覆盖率（流量 KPI） ----------
def report(tag, r, unit_div=None):
    if not isinstance(r, dict):
        print(tag, "non-dict", str(r)[:200], flush=True)
        return
    inner = r.get("data") if isinstance(r.get("data"), dict) else {}
    rows = inner.get("data") or []
    per_day = defaultdict(list)
    for row in rows:
        try:
            per_day[row[0][:10]].append(float(row[1]))
        except (TypeError, ValueError, IndexError):
            pass
    print("\n%s code=%s msg=%s rows=%d days=%d" % (tag, r.get("code"), str(r.get("msg"))[:60],
                                                  len(rows), len(per_day)), flush=True)
    for d in sorted(per_day):
        v = per_day[d]
        print("   %s n=%-3d sum=%-14s mean=%-10s %s" % (
            d, len(v), round(sum(v), 2), round(sum(v) / len(v), 2),
            ("-> GB_day=%.1f" % (sum(v) / unit_div)) if unit_div else ""), flush=True)
    return per_day


try:
    report("### C) trend91 Total Traffic @1hour x %d天" % DAYS, hist(qp91, "1hour", LAST, END, DAYS * 24),
           unit_div=1073741824.0)
except Exception as e:
    print("C FAIL %s: %s" % (type(e).__name__, str(e)[:250]), flush=True)

# ---------- E) 5 个 KPI 各自 22 天 @1hour 是否都能回（monitorid 250005 / 5112） ----------
print("\n### E) 6 个 CXO 趋势 KPI 的 22 天 @1hour 覆盖", flush=True)
for gid in ("92", "93", "94", "95", "99"):
    qp = ((keys.get("summary/trend_%s" % gid) or {}).get("data") or {}).get("queryParam") or {}
    if not qp:
        print("  trend %s 无 queryParam" % gid, flush=True)
        continue
    try:
        r = hist(qp, "1hour", LAST, END, DAYS * 24)
        inner = r.get("data") if isinstance(r.get("data"), dict) else {}
        rows = inner.get("data") or []
        ds = sorted({row[0][:10] for row in rows})
        print("  trend %s mon=%s col=%s code=%s rows=%d days=%d [%s..%s]" % (
            gid, qp["monitorid"], qp["showColumns"][1], r.get("code"), len(rows), len(ds),
            ds[0] if ds else "-", ds[-1] if ds else "-"), flush=True)
    except Exception as e:
        print("  trend %s FAIL %s %s" % (gid, type(e).__name__, str(e)[:150]), flush=True)
    time.sleep(1)
