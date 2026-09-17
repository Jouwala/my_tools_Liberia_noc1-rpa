# -*- coding: utf-8 -*-
"""VMAX 天粒度历史查询 - 决定性验证脚本（VMAX 恢复后运行，纯只读）。

依据（全部来自本地缓存 last_known_good.json 的 queryParam / mars 字段）：
  CXO 每个趋势图本身就是 mars DIM 查询：monitorid + showColumns(KPI码) + filterListModel
  + granularity:"15min"。mars 历史接口契约（从 mars 前端 bundle 取出）：
    POST /query/v2/history   body {"param": RSA_encryptLong(JSON)}
    JSON = {condition:{filterListModel, showColumns, times:{lastTime,endTime,
            granularity,period,type:2}, size}, uid, sceneid:"3", monitorid, userName}
    granularity 合法值: 5min | 15min | 1hour | 1day | 1week | 1month   （是 "1day" 不是 "day"）

本脚本只读，不写任何缓存/数据库。
"""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
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
CACHE = _ROOT / "data" / "cxo_dashboard" / "last_known_good.json"
TRENDS = ("91", "92", "93", "94", "95", "99")


def encrypt_long(text):
    data = text.encode("utf-8")
    hex_all = ""
    for i in range(0, len(data), 117):
        hex_all += _KEY.encrypt(data[i:i + 117], padding.PKCS1v15()).hex()
    return base64.b64encode(bytes.fromhex(hex_all)).decode()


def post_history(cond, timeout=180):
    payload = {"param": encrypt_long(json.dumps(cond, separators=(",", ":")))}
    url = PROXY_BASE + urllib.parse.quote(VMAX + "/query/v2/history", safe="")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def proxy_alive():
    try:
        with urllib.request.urlopen(PROXY_BASE.rstrip("/") + "/health", timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:120]}


def week_frame(today=None):
    """本周一 / 上周一 / 上上周一 / 今天。"""
    today = today or date.today()
    this_mon = today - timedelta(days=today.weekday())
    return this_mon - timedelta(days=14), this_mon - timedelta(days=7), this_mon, today


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("proxy health:", json.dumps(proxy_alive(), ensure_ascii=False), flush=True)
mm_start, w1_start, w0_start, today = week_frame()
last_time = "%s 00:00:00" % mm_start.isoformat()
end_time = "%s 00:00:00" % (today + timedelta(days=1)).isoformat()
print("window: %s -> %s  (%d days)" % (last_time, end_time, (today - mm_start).days), flush=True)

cache = json.loads(CACHE.read_text(encoding="utf-8"))
keys = cache.get("keys") or {}

for gid in TRENDS:
    data = ((keys.get("summary/trend_%s" % gid) or {}).get("data")) or {}
    q = data.get("queryParam") or {}
    monitorid, cols = q.get("monitorid"), q.get("showColumns")
    flm = q.get("filterListModel")
    if not monitorid or not cols or not flm:
        print("trend %s: 缺 queryParam，跳过" % gid, flush=True)
        continue
    cond = {
        "condition": {
            "filterListModel": flm,
            "showColumns": cols,
            "times": {"lastTime": last_time, "endTime": end_time,
                      "granularity": "1day", "period": (today - mm_start).days + 1, "type": 2},
            "size": 10000,
        },
        "uid": 0, "sceneid": "3", "monitorid": monitorid, "userName": USER_NAME,
    }
    print("=" * 78, flush=True)
    print("trend %s | %s | monitorid=%s cols=%s" % (gid, data.get("showName"), monitorid, cols), flush=True)
    t0 = time.time()
    try:
        r = post_history(cond)
    except Exception as e:
        print("  FAIL %s: %s" % (type(e).__name__, str(e)[:300]), flush=True)
        continue
    rows = ((r or {}).get("data") or {}).get("data") if isinstance((r or {}).get("data"), dict) else (r or {}).get("data")
    print("  code=%s msg=%s elapsed=%.1fs rows=%s" % (
        (r or {}).get("code"), str((r or {}).get("msg"))[:80], time.time() - t0,
        len(rows or [])), flush=True)
    for row in (rows or [])[:3]:
        print("   ", json.dumps(row, ensure_ascii=False)[:160], flush=True)
    for row in (rows or [])[-3:]:
        print("   ", json.dumps(row, ensure_ascii=False)[:160], flush=True)
    time.sleep(2)
