# -*- coding: utf-8 -*-
"""
批量快速测试 eflow_api_client.py 中所有对外 API 端点是否可正常取数。
策略：只登录一次，然后对每个端点发一个最小请求（length=1 / 小分页），
不跑完整导出/下载流水线，从而快速判断"能否取到数据"。
"""
import os
import sys
import json
import time
import traceback

# 让脚本能 import 到 eflow_api_client
BACKEND_SERVICES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "services")
sys.path.insert(0, BACKEND_SERVICES)

import eflow_api_client as api  # noqa: E402

results = []


def record(name, ok, http, rows, total, msg=""):
    results.append({
        "api": name,
        "ok": ok,
        "http": http,
        "rows": rows,
        "total": total,
        "msg": msg[:180],
    })
    flag = "OK " if ok else "FAIL"
    print(f"[{flag}] {name:<22} http={http:<10} rows={rows} total={total} {msg[:120]}")


def _status_code(status_line):
    parts = (status_line or "").split()
    return parts[1] if len(parts) > 1 else status_line


def probe_list(name, api_path, referer, fields, status_filter, relation_filter=None):
    """列表类端点：TT/WO/CR/PM。发 length=1 的最小查询。"""
    try:
        start_ms, end_ms = api._get_time_range_ms()
        flt = api.TIME_FILTER_TEMPLATE.format(status_filter=status_filter, start_ms=start_ms, end_ms=end_ms)
        payload = {
            "customInfo": {"pageType": "allTicket"},
            "field": fields,
            "filter": flt,
            "length": 1,
            "order": "lastModifiedTime desc",
            "start": 0,
        }
        if relation_filter:
            payload["relationFilter"] = relation_filter
        t0 = time.time()
        status, hdrs, raw, body = api._http_request(
            "POST", api_path, headers_extra=api._headers_extra(referer), body=json.dumps(payload)
        )
        code = _status_code(status)
        data, ok_json = api._safe_json_loads(body.decode("utf-8", errors="replace"), label=name)
        total = None
        if isinstance(data, dict):
            for k in ("recordsTotal", "total", "totalCount", "totalcount", "count"):
                if data.get(k) is not None:
                    total = data.get(k)
                    break
        rows = api.parse_response(data, label=name)
        ok = ("200" in status) and ok_json and (isinstance(rows, list))
        record(name, ok, code, len(rows) if isinstance(rows, list) else 0,
               total, f"{time.time()-t0:.1f}s" + ("" if ok else f" body={body[:120]}"))
    except Exception as e:
        record(name, False, "ERR", 0, None, f"{type(e).__name__}: {e}")


def probe_export(name, async_path, referer):
    """CMDB Site/Person 同步导出端点：只判断 HTTP 200 + 是否返回二进制文件。"""
    try:
        t0 = time.time()
        status, hdrs, raw, body = api._http_request(
            "POST", async_path, headers_extra=api._headers_extra(referer),
            body=json.dumps({"callScene": "ui"})
        )
        code = _status_code(status)
        is_xlsx = body[:2] == b"PK"  # xlsx/zip 签名
        ok = ("200" in status) and len(body) > 1000
        record(name, ok, code, "-", f"{len(body)}B",
               f"{time.time()-t0:.1f}s xlsx={is_xlsx}" + ("" if ok else f" body={body[:120]}"))
    except Exception as e:
        record(name, False, "ERR", 0, None, f"{type(e).__name__}: {e}")


def probe_active_alarm():
    name = "RealtimeAlarm"
    try:
        import uuid
        from datetime import datetime, timezone
        headers = (
            f"Cookie: {api._session_cookie}\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"Referer: {api.ALARM_REFERER}\r\n"
            f"forgerydefense: {api._forgery_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Origin: https://{api.HOST}:{api.PORT}\r\n"
            f"LogTracking: True\r\n"
        )
        now = datetime.now(timezone.utc)
        payload = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z",
            "condition": api.ALARM_CONDITION, "manual": False,
            "page": 1, "pagesize": 5,
            "queryid": "T" + uuid.uuid4().hex,
            "activeTabId": "fm-active_" + uuid.uuid4().hex,
        }
        t0 = time.time()
        status, hdrs, raw, body = api._http_request("POST", api.ALARM_API_PATH, headers_extra=headers, body=json.dumps(payload))
        code = _status_code(status)
        data, ok_json = api._safe_json_loads(body.decode("utf-8", errors="replace"), label=name)
        total = data.get("totalcount") or data.get("total") if isinstance(data, dict) else None
        rows = api.parse_response(data, label=name) if isinstance(data, (dict, list)) else []
        ok = ("200" in status) and ok_json
        record(name, ok, code, len(rows) if isinstance(rows, list) else 0, total,
               f"{time.time()-t0:.1f}s" + ("" if ok else f" body={body[:120]}"))
    except Exception as e:
        record(name, False, "ERR", 0, None, f"{type(e).__name__}: {e}")


def probe_history_alarm():
    name = "HistoryAlarm"
    try:
        from datetime import datetime, timezone
        headers = (
            f"Cookie: {api._session_cookie}\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"Referer: {api.ALARM_REFERER}\r\n"
            f"forgerydefense: {api._forgery_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Origin: https://{api.HOST}:{api.PORT}\r\n"
            f"LogTracking: True\r\n"
        )
        his_start, his_end = api._get_his_alarm_time_range()
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        cond = dict(api.HIS_ALARM_CONDITION)
        cond["alarmraisedtime"] = {"mode": "0", "start": int(his_start.timestamp()*1000), "end": int(his_end.timestamp()*1000)}
        cond["from"] = 0
        cond["size"] = 5
        payload = {"querynum": 5, "condition": cond,
                   "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z",
                   "manual": True}
        t0 = time.time()
        status, hdrs, raw, body = api._http_request("POST", f"{api.HIS_ALARM_API_PATH}?timestamp={now_ms}", headers_extra=headers, body=json.dumps(payload))
        code = _status_code(status)
        data, ok_json = api._safe_json_loads(body.decode("utf-8", errors="replace"), label=name)
        total = data.get("totalcount") or data.get("total") if isinstance(data, dict) else None
        rows = api.parse_response(data, label=name) if isinstance(data, (dict, list)) else []
        ok = ("200" in status) and ok_json
        record(name, ok, code, len(rows) if isinstance(rows, list) else 0, total,
               f"{time.time()-t0:.1f}s" + ("" if ok else f" body={body[:120]}"))
    except Exception as e:
        record(name, False, "ERR", 0, None, f"{type(e).__name__}: {e}")


def main():
    print("=" * 90)
    print(f"eFlow API 批量测试  HOST={api.HOST}:{api.PORT}  USER={api.USERNAME}")
    print("=" * 90)

    # Step 0: 登录（所有端点前提）
    t0 = time.time()
    try:
        api.login()
        print(f"[OK ] login                  {time.time()-t0:.1f}s  cookies_len={len(api._session_cookie)}")
    except Exception as e:
        print(f"[FAIL] login  {type(e).__name__}: {e}")
        traceback.print_exc()
        print("\n登录失败，后续端点无法测试。")
        return

    print("-" * 90)

    # Step 1: 列表类端点
    probe_list("eFlow_TT", api.TT_API_PATH, api.TT_REFERER, api.TT_FIELDS, api.TT_STATUS_FILTER,
               {"eflow_ticket_ticket_asset_all": ""})
    probe_list("eFlow_WO", api.WO_API_PATH, api.WO_REFERER, api.WO_FIELDS, api.WO_STATUS_FILTER,
               {"eflow_wo_wo_asset": ""})
    probe_list("eFlow_CR", api.CR_API_PATH, api.CR_REFERER, api.CR_FIELDS, api.CR_STATUS_FILTER)
    probe_list("eFlow_PM", api.PM_API_PATH, api.PM_REFERER, api.PM_FIELDS, api.PM_STATUS_FILTER,
               {"eflow_pm_task_asset": ""})

    # Step 2: CMDB 导出类端点
    probe_export("CMDB_Site", api.SITE_ASYNC_PATH, api.SITE_REFERER)
    probe_export("CMDB_Person", api.PERSON_ASYNC_PATH, api.PERSON_REFERER)

    # Step 3: 告警端点
    probe_active_alarm()
    probe_history_alarm()

    # 汇总
    print("=" * 90)
    ok_n = sum(1 for r in results if r["ok"])
    print(f"汇总：{ok_n}/{len(results)} 个端点可正常取数")
    print("=" * 90)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_test_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"host": f"{api.HOST}:{api.PORT}", "results": results}, f, ensure_ascii=False, indent=2)
    print(f"结果已写入: {out}")


if __name__ == "__main__":
    main()
