# -*- coding: utf-8 -*-
"""确认多列批量响应的精确结构（field/header/行序），只读探测。"""
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
    PROXY_BASE, VMAX_HOST, HISTORY_ENDPOINT, GRANULARITY, _REQ_TIMEOUT, _encrypt_param, _EMPTY_FILTER)

sess = requests.Session()
sess.trust_env = False
user = requests.get("http://127.0.0.1:8790/health", timeout=5).json().get("user") or ""

# 5115 (OTTVoice) 全部 11 列，验证"一次多列 + 列序不可预期"
CODES = ["ppc400465047", "ppc400465048", "ppc400465045", "ppc400465046", "ppc400465041",
         "ppc400465042", "ppb400465067", "ppc400465022", "ppc400465021", "ppc400465028", "ppc400465029"]
cond = {
    "condition": {"filterListModel": _EMPTY_FILTER,
                  "showColumns": ["clttime"] + CODES,
                  "times": {"lastTime": "2026-09-16 00:00:00", "endTime": "2026-09-16 10:00:00",
                            "granularity": GRANULARITY, "period": 2, "type": 2},
                  "size": 10000},
    "uid": 0, "sceneid": "3", "monitorid": 5115, "userName": user,
}
payload = {"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))}
url = PROXY_BASE + urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe="")
t0 = time.time()
body = sess.post(url, json=payload, timeout=_REQ_TIMEOUT).json()
d = body.get("data") if isinstance(body.get("data"), dict) else {}
rows = d.get("data") or []
print("用时 %.2fs code=%s" % (time.time() - t0, body.get("code")))
print("header  :", json.dumps(d.get("header"), ensure_ascii=False)[:300])
print("field   :", json.dumps(d.get("field"), ensure_ascii=False)[:600])
print("rows    :", len(rows))
print("row[0]  :", json.dumps(rows[0], ensure_ascii=False) if rows else None)
print("row[-1] :", json.dumps(rows[-1], ensure_ascii=False) if rows else None)
print()
print("请求列序 == 响应 field 序 ?", ["clttime"] + CODES == (d.get("field") or []))
print("请求列数=%d  field 列数=%d  行宽=%d" % (1 + len(CODES), len(d.get("field") or []),
                                              len(rows[0]) if rows else 0))
# 用 field 索引把每列抽出来看看
fld = d.get("field") or []
if rows and fld:
    for i, name in enumerate(fld):
        vals = [r[i] for r in rows[:3]]
        print("   field[%d]=%-16s sample=%s" % (i, name, vals))
