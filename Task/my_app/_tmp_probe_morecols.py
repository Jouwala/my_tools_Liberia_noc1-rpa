# -*- coding: utf-8 -*-
"""实测两个问题：
  A. /query/v2/history 能否「一次请求多列」（showColumns 带多个 KPI 码）-> 决定扩展到 ~45 指标的请求成本
  B. 网络类指标(5132)用看板自带的 filterListModel + 1hour 粒度是否可查 -> 决定能否复用现成配方
只读探测，不写任何业务文件。"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backend.services.vmax_cxo_daily_cache import (  # noqa: E402
    PROXY_BASE, VMAX_HOST, HISTORY_ENDPOINT, GRANULARITY, _REQ_TIMEOUT, _encrypt_param)

LK = ROOT / "data" / "cxo_dashboard" / "last_known_good.json"
doc = json.loads(LK.read_text(encoding="utf-8"))
keys = doc["keys"]

sess = requests.Session()
sess.trust_env = False
user = requests.get("http://127.0.0.1:8790/health", timeout=5).json().get("user") or ""


def call(cond, tag):
    payload = {"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))}
    url = PROXY_BASE + urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe="")
    t0 = time.time()
    r = sess.post(url, json=payload, timeout=_REQ_TIMEOUT)
    body = r.json()
    el = time.time() - t0
    code = body.get("code")
    d = body.get("data") if isinstance(body.get("data"), dict) else {}
    print("\n[%s] %.1fs code=%s msg=%s" % (tag, el, code, str(body.get("msg"))[:110]))
    print("   header:", d.get("header"))
    print("   field :", d.get("field"))
    rows = d.get("data") or []
    print("   rows  :", len(rows), "| first:", rows[0] if rows else None, "| last:", rows[-1] if rows else None)
    return body


# 取一个网络类指标（5132）看板自己的查询配方
qp = None
for k, v in keys.items():
    if k.startswith("service/Mobility/indicator/"):
        qp = ((v or {}).get("data") or {}).get("queryData", {}).get("queryParam")
        if qp:
            print("样板指标:", k, "| monitorid:", qp.get("monitorid"),
                  "| code:", (qp.get("showColumns") or [None, None])[1],
                  "| granularity:", qp.get("granularity"))
            break

end_time = "2026-09-16 08:00:00"
last_time = "2026-09-14 00:00:00"

# ---- B. 单列 + 看板 filterListModel + 强制 1hour ----
single = {
    "condition": {"filterListModel": qp.get("filterListModel"),
                  "showColumns": ["clttime", "ppc300543357"],
                  "times": {"lastTime": last_time, "endTime": end_time,
                            "granularity": GRANULARITY, "period": 2, "type": 2},
                  "size": 10000},
    "uid": 0, "sceneid": qp.get("sceneid") or "3", "monitorid": qp.get("monitorid"), "userName": user,
}
call(single, "B 单列 5132 S1 HO SR @1hour")

# ---- A. 一次 4 列（同一 monitorid）----
CODES = ["ppc300543357", "ppc300501005", "ppc300543001", "ppc300503001"]
multi = json.loads(json.dumps(single))
multi["condition"]["showColumns"] = ["clttime"] + CODES
call(multi, "A 多列 5132 x4 @1hour")

# ---- A2. 一次 4 列 + 不带 clttime 的极端情况（对照，看服务端是否强依赖 clttime）----
multi2 = json.loads(json.dumps(single))
multi2["condition"]["showColumns"] = ["clttime"] + CODES[:2]
call(multi2, "A2 多列 5132 x2 @1hour")
