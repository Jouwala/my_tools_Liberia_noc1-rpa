# -*- coding: utf-8 -*-
"""两个探测：
  C. 通配列（clttime + "*" / 只给 clttime）能否让服务端吐出该 monitor 的全部可用列 -> 指标目录能不能穷举
  D. 一次 14 列（5132 全部现成配方）能否稳定返回 -> 扩展后的真实请求形态与 field 映射
"""
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

doc = json.loads((ROOT / "data" / "cxo_dashboard" / "last_known_good.json").read_text(encoding="utf-8"))
keys = doc["keys"]
qp = next(((v or {}).get("data") or {}).get("queryData", {}).get("queryParam")
          for k, v in keys.items() if k.startswith("service/Mobility/indicator/"))

sess = requests.Session()
sess.trust_env = False
user = requests.get("http://127.0.0.1:8790/health", timeout=5).json().get("user") or ""


def call(codes, tag, monitor=None):
    cond = {"condition": {"filterListModel": qp.get("filterListModel"), "showColumns": codes,
                          "times": {"lastTime": "2026-09-15 00:00:00", "endTime": "2026-09-16 08:00:00",
                                    "granularity": GRANULARITY, "period": 2, "type": 2},
                          "size": 10000},
            "uid": 0, "sceneid": qp.get("sceneid") or "3", "monitorid": monitor or qp.get("monitorid"),
            "userName": user}
    url = PROXY_BASE + urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe="")
    t0 = time.time()
    try:
        body = sess.post(url, json={"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))},
                         timeout=_REQ_TIMEOUT).json()
    except Exception as exc:                                    # noqa: BLE001
        print("\n[%s] EXC %s: %s" % (tag, type(exc).__name__, str(exc)[:150]))
        return None
    el = time.time() - t0
    d = body.get("data") if isinstance(body.get("data"), dict) else {}
    rows = d.get("data") or []
    print("\n[%s] %.1fs code=%s msg=%s" % (tag, el, body.get("code"), str(body.get("msg"))[:150]))
    if d:
        print("   field :", d.get("field"))
        print("   header:", d.get("header"))
        print("   rows  :", len(rows), "| sample:", rows[:1], rows[-1:])
    return body


# C1: 通配
call(["clttime", "*"], "C1 通配 *")
# C2: 只给时间列
call(["clttime"], "C2 只 clttime")
# D: 14 列一次
ALL5132 = ["ppc300501005", "ppc300501008", "ppc300503001", "ppc300504126", "ppc300521001",
           "ppc300522214", "ppc300541302", "ppc300542580", "ppc300543001", "ppc300543002",
           "ppc300543357", "ppc300543368", "ppc300544532", "ppb300542009"]
call(["clttime"] + ALL5132, "D 5132 x14 一次")
