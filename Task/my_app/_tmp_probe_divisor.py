# -*- coding: utf-8 -*-
"""校验：原始 mars 小时值 与 看板显示值(value) 量级是否一致 -> 判断是否需要 divisor。只读。"""
import json
import sys
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backend.services.vmax_cxo_daily_cache import (  # noqa: E402
    PROXY_BASE, VMAX_HOST, HISTORY_ENDPOINT, GRANULARITY, _REQ_TIMEOUT, _encrypt_param, _EMPTY_FILTER)

cache = json.loads((ROOT / "data" / "cxo_dashboard" / "last_known_good.json").read_text(encoding="utf-8"))
keys = cache.get("keys") or {}
sess = requests.Session()
sess.trust_env = False
user = requests.get("http://127.0.0.1:8790/health", timeout=5).json().get("user") or ""

# 各页签页: (monitorid, [codes]) —— 覆盖所有新增指标所在监控
GROUPS = {
    5112: ["ppc400464046", "ppc400464050", "ppc400464051", "ppc400464030", "ppc400464031", "ppc400464013"],
    5113: ["ppc400461018", "ppc400461040", "ppc400461041", "ppc400461044", "ppc400461045", "ppc400461013", "ppc400461014"],
    5114: ["ppc400403047", "ppc400403048", "ppc400403018", "ppc400403019"],
    5115: ["ppc400465047", "ppc400465048", "ppc400465045", "ppc400465046", "ppc400465041",
           "ppc400465042", "ppb400465067", "ppc400465022", "ppc400465021", "ppc400465028", "ppc400465029"],
    5116: ["ppc400465047", "ppc400465041"],
}


def board_value(mon, code):
    for k, entry in keys.items():
        if "indicator" not in k:
            continue
        data = (entry or {}).get("data") or {}
        qp = (data.get("queryData") or {}).get("queryParam") or data.get("queryParam") or {}
        if qp.get("monitorid") == mon and code in (qp.get("showColumns") or []):
            return data.get("value"), (data.get("title") or "")
    return None, ""


for mon, codes in GROUPS.items():
    cond = {"condition": {"filterListModel": _EMPTY_FILTER, "showColumns": ["clttime"] + codes,
                          "times": {"lastTime": "2026-09-16 06:00:00", "endTime": "2026-09-16 10:00:00",
                                    "granularity": GRANULARITY, "period": 2, "type": 2}, "size": 10000},
            "uid": 0, "sceneid": "3", "monitorid": mon, "userName": user}
    payload = {"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))}
    body = sess.post(PROXY_BASE + urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe=""),
                     json=payload, timeout=_REQ_TIMEOUT).json()
    d = body.get("data") if isinstance(body.get("data"), dict) else {}
    fld = d.get("field") or []
    rows = d.get("data") or []
    hdr = d.get("header") or []
    print("=" * 108)
    print("monitorid=%s  code=%s  rows=%d" % (mon, body.get("code"), len(rows)))
    for c in codes:
        if c not in fld:
            print("   %-18s <不在响应 field 中>" % c)
            continue
        i = fld.index(c)
        raw = rows[-1][i] if rows else None          # 用最后一个小时点
        bv, btitle = board_value(mon, c)
        hdrname = hdr[i] if i < len(hdr) else ""
        try:
            ratio = float(raw) / float(str(bv).rstrip("ms%skbps").strip() or 1) if bv else None
        except Exception:
            ratio = None
        print("   %-18s raw=%-16s board=%-16s ratio=%-8s hdr=%s"
              % (c, raw, bv, ("%.4f" % ratio) if ratio else "-", hdrname[:46]))
