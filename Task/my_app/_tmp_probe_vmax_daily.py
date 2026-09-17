# -*- coding: utf-8 -*-
"""Probe VMAX API for daily-granularity / date-range support (read-only test)."""
import json
import sys
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX_BASE = ("https://10.123.255.12:26180/rdk/service/app/insight/"
             "realtimeguarantee/ds_dashboard_Overseas/server")
BASE = {"province_id": "", "city_id": "", "area_id": ""}


def post(endpoint, body):
    url = PROXY_BASE + urllib.parse.quote(VMAX_BASE + endpoint, safe="")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def show(tag, resp):
    print("=" * 70)
    print("[%s]" % tag)
    if not isinstance(resp, dict):
        print("  non-dict:", str(resp)[:300])
        return
    keys = list(resp.keys())
    print("  keys:", keys)
    print("  showName:", resp.get("showName"))
    xd = resp.get("xData")
    if isinstance(xd, list):
        print("  xData len=%d, first=%s, last=%s" % (len(xd), xd[:3], xd[-3:]))
    yd = resp.get("yData")
    if isinstance(yd, list):
        print("  series:", [(s or {}).get("name") for s in yd])
    err = resp.get("error") or resp.get("message") or resp.get("msg")
    if err:
        print("  error/msg:", str(err)[:300])
    s = json.dumps(resp, ensure_ascii=False)
    print("  raw size:", len(s))


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 1) baseline graphId 91
try:
    show("baseline graphId=91", post("/Summary/getTrendAnalysis", {**BASE, "graphId": "91"}))
except Exception as e:
    print("[baseline] FAIL:", e)

# 2) skipped ids 96/97/98
for g in ("96", "97", "98"):
    try:
        show("graphId=%s" % g, post("/Summary/getTrendAnalysis", {**BASE, "graphId": g}))
    except Exception as e:
        print("[graphId=%s] FAIL: %s" % (g, e))

# 3) try common time-range params on getTrendAnalysis
for extra in (
    {"timeType": "day"},
    {"timeType": "D"},
    {"type": "day"},
    {"granularity": "day"},
    {"startTime": "2026-09-01", "endTime": "2026-09-15"},
    {"beginTime": "2026-09-01 00:00:00", "endTime": "2026-09-15 23:59:59"},
    {"time": "2026-09-14 00:00:00"},
    {"date": "2026-09-14"},
    {"day": 7},
):
    body = {**BASE, "graphId": "91", **extra}
    try:
        show("graphId=91 + %s" % json.dumps(extra), post("/Summary/getTrendAnalysis", body))
    except Exception as e:
        print("[extra %s] FAIL: %s" % (extra, e))
