# -*- coding: utf-8 -*-
"""对照：5112（视频类）用「我的 interfaceid+rat 过滤」vs「看板原样空过滤」，值是否不同。
若不同，说明现有 4 个视频 KPI 口径偏了，需按看板配方纠正。"""
import json
import statistics
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
    PROXY_BASE, VMAX_HOST, HISTORY_ENDPOINT, GRANULARITY, _REQ_TIMEOUT, _encrypt_param, _FILTER_MODEL)

EMPTY_FILTER = {"filterType": "0", "filterGroupList":
                [{"filter_type": "0", "items": None, "filterType": "0", "filterModelList": []}]}

sess = requests.Session()
sess.trust_env = False
user = requests.get("http://127.0.0.1:8790/health", timeout=5).json().get("user") or ""
LAST, END = "2026-09-09 00:00:00", "2026-09-16 08:00:00"


def call(monitor, code, filt, tag):
    cond = {"condition": {"filterListModel": filt, "showColumns": ["clttime", code],
                          "times": {"lastTime": LAST, "endTime": END,
                                    "granularity": GRANULARITY, "period": 2, "type": 2},
                          "size": 10000},
            "uid": 0, "sceneid": "3", "monitorid": monitor, "userName": user}
    url = PROXY_BASE + urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe="")
    t0 = time.time()
    body = sess.post(url, json={"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))},
                     timeout=_REQ_TIMEOUT).json()
    d = body.get("data") or {}
    rows = d.get("data") or []
    vals = [float(r[1]) for r in rows if len(r) > 1 and str(r[1]).replace(".", "").replace("-", "").isdigit()]
    print("[%-28s] %.1fs rows=%3d 均值=%8.3f 最大=%8.3f 尾值=%s" % (
        tag, time.time() - t0, len(rows),
        statistics.fmean(vals) if vals else float("nan"),
        max(vals) if vals else float("nan"), rows[-1] if rows else None))
    return rows


for code, name in (("ppc400464046", "Video DL Valid Throughput"),
                   ("ppc400464015", "Stalling Duration Ratio (%)"),
                   ("ppc400464013", "Avg Cache Duration (ms)")):
    a = call(5112, code, _FILTER_MODEL, "5112 interfaceid+rat")
    b = call(5112, code, EMPTY_FILTER, "5112 看板空过滤")
    same = [r[0] for r in a] == [r[0] for r in b] and [str(r[1]) for r in a] == [str(r[1]) for r in b]
    print("    -> %s 完全一致: %s" % (code, same))
    if not same:
        print("       差异示例 mine=%s  board=%s" % (a[:2], b[:2]))

# 对照 250005：确认带过滤是必要的（看板自己就带）
call(250005, "ppc400401001", _FILTER_MODEL, "250005 interfaceid+rat")
call(250005, "ppc400401001", EMPTY_FILTER, "250005 空过滤(对照)")
