# -*- coding: utf-8 -*-
import io, sys, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from backend.services.eflow_api_client import ensure_login, _http_request, _headers_extra, TT_API_PATH
from backend.services import eflow_data_mapper as dm

ensure_login()
hdr = _headers_extra(dm.TT_REFERER)

for length in (100, 2000):
    payload = {**dm.TT_PAYLOAD_BASE, "start": 0, "length": length, "order": "lastModifiedTime desc"}
    t0 = time.time()
    st, hdrs, rh, rsp = _http_request("POST", TT_API_PATH, headers_extra=hdr, body=json.dumps(payload))
    data = json.loads(rsp.decode("utf-8"))
    res = data.get("result") or []
    print(f"length={length}: status={st} rows={len(res)} total={data.get('total')} bytes={len(rsp)} time={time.time()-t0:.2f}s")
    # 找 091 是否在首页
    hit = next((r for r in res if str(r.get('woNum')).strip().upper()=='TT202609100091'), None)
    print("   091 in first page:", bool(hit))
    if hit:
        print("   091 status:", hit.get("status"), "site:", hit.get("assetName"), "occur:", hit.get("alarmOccurTime"))