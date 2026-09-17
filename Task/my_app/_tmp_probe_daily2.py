# -*- coding: utf-8 -*-
"""Probe VMAX CXO getTrendAnalysis for day-granularity / date-range support (read-only, 10 calls max)."""
import json
import sys
import time
import urllib.parse
import urllib.request

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX_BASE = ("https://10.123.255.12:26180/rdk/service/app/insight/"
             "realtimeguarantee/ds_dashboard_Overseas/server")
BASE = {"province_id": "", "city_id": "", "area_id": ""}
TO = 25


def post(endpoint, body, timeout=TO):
    url = PROXY_BASE + urllib.parse.quote(VMAX_BASE + endpoint, safe="")
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def brief(tag, resp, baseline=None):
    out = {"tag": tag}
    if not isinstance(resp, dict):
        out["non_dict"] = str(resp)[:200]
        print(json.dumps(out, ensure_ascii=False), flush=True)
        return
    o = resp.get("option") or {}
    x = resp.get("xData") or (o.get("xAxis", {}) or {}).get("data") or []
    if not x and isinstance(o.get("xAxis"), list) and o["xAxis"]:
        x = o["xAxis"][0].get("data") or []
    ser = o.get("series") or []
    out["xLen"] = len(x)
    out["xHead"] = x[:3]
    out["xTail"] = x[-3:]
    out["series"] = [(s.get("name"), len(s.get("data") or [])) for s in ser][:8]
    if baseline is not None and x:
        out["sameXAsBaseline"] = (x == baseline)
    err = resp.get("error") or resp.get("msg") or resp.get("message")
    if err:
        out["error"] = str(err)[:160]
    print(json.dumps(out, ensure_ascii=False), flush=True)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

baseline_x = None
try:
    r = post("/Summary/getTrendAnalysis", {**BASE, "graphId": "91"}, timeout=60)
    brief("BASELINE graphId=91", r)
    baseline_x = r.get("xData") or ((r.get("option") or {}).get("xAxis") or {}).get("data") or []
except Exception as e:
    print("BASELINE FAIL %s %s" % (type(e).__name__, str(e)[:200]), flush=True)

CASES = [
    {"timeType": "day"},
    {"timeType": "1"},
    {"granularity": "day"},
    {"type": "day"},
    {"dateType": "day"},
    {"period": "day"},
    {"timeType": "day", "startTime": "2026-08-24 00:00:00", "endTime": "2026-09-15 00:00:00"},
    {"beginTime": "2026-08-24 00:00:00", "endTime": "2026-09-15 00:00:00"},
    {"days": "21"},
]
for extra in CASES:
    tag = "+ %s" % json.dumps(extra, ensure_ascii=False)
    try:
        brief("trend91 " + tag, post("/Summary/getTrendAnalysis", {**BASE, "graphId": "91", **extra}), baseline_x)
    except Exception as e:
        print("FAIL trend91 %s -> %s %s" % (tag, type(e).__name__, str(e)[:150]), flush=True)
    time.sleep(1)

for extra in ({"time": "2026-09-14 00:00:00"},
              {"startTime": "2026-09-14 00:00:00", "endTime": "2026-09-14 23:59:59"}):
    body = {**BASE, "tabId": 0, "infoId": 391, "view_id": 2, **extra}
    try:
        r = post("/Service/getIndicatorData", body) or {}
        o = r.get("option") or {}
        s = (o.get("series") or [{}])[0]
        print("INDICATOR %s -> series=%s dataLen=%s nulls=%s time=%s" % (
            json.dumps(extra), s.get("name"), len(s.get("data") or []),
            sum(1 for v in (s.get("data") or []) if v in (None, "", "-")), r.get("time")), flush=True)
    except Exception as e:
        print("INDICATOR FAIL %s -> %s" % (json.dumps(extra), str(e)[:150]), flush=True)
