#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按 TT 单号从 eFlow 系统查询历史告警（本地 history_alarm 只滚动保留 48 小时，
更早的告警必须直接调 eFlow API 按时间范围拉取，再按单号过滤）。

用法:
    python tools/eflow_hisalarm_by_tt.py TT202608220047
    python tools/eflow_hisalarm_by_tt.py TT202608220047 --days-back 3   # 单号日期前再往前多查 3 天
    python tools/eflow_hisalarm_by_tt.py TT202608220047 --json

原理:
    1. 从单号推断日期（TT20260822xxxx -> 2026-08-22），查当天 00:00~24:00 (UTC)
    2. POST /api/fm-history/v1/hisalarms/pageinfo，alarmraisedtime 指定该窗口
    3. 本地按 TT ID == 单号 过滤，输出告警名 / 发生时间 / 恢复时间 / 制式 / 派单时间
    4. 当天查不到时自动向前扩 1 天重试（最多 --days-back 天）

依赖:
    复用 my_app 的 eflow_api_client / eflow_alarm_service（登录、请求、解析）。
    需要能访问 10.100.20.8:28001（可用 EFLOW_HOST / EFLOW_PORT 覆盖）。
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MY_APP = r"D:\01_RPA\Task\my_app"
if MY_APP not in sys.path:
    sys.path.insert(0, MY_APP)

PAGE_SIZE = 5000
MAX_PAGES = 6   # 一天告警 > 3 万条才会用满，兜底防失控

INTERESTING_COLS = [
    "Site Name", "Site ID", "Networktype", "restypename", "codename", "Alarm Title",
    "TT ID", "durationname", "col_2g_cells", "col_3g_cells", "col_4g_cells",
]
ASSIGN_COLS = ["Assign RuleName", "Assign Delay", "Assign Start Time",
               "Assigned Time", "Assigned Type"]


def ms_to_str(v):
    s = str(v)
    if s.replace(".0", "").isdigit() and len(s.replace(".0", "")) >= 13:
        ms = int(float(s))
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return s or "—"


def fetch_day(target_date, limit_days, tt_no):
    """拉取 [date - limit_days, date + 1) 窗口内的历史告警，按 TT 过滤。

    返回 (命中行列表, 拉取总行数)。
    """
    from backend.services.eflow_api_client import (
        _http_request, ensure_login, get_session_headers, parse_response,
        _safe_json_loads, HOST, PORT,
    )
    from backend.services.eflow_alarm_service import (
        HIS_ALARM_API_PATH, HIS_ALARM_CONDITION, ALARM_REFERER,
        _normalize_alarm_rows,
    )

    end_dt = datetime(target_date.year, target_date.month, target_date.day,
                      0, 0, 0, tzinfo=timezone.utc) + timedelta(days=1)
    start_dt = end_dt - timedelta(days=limit_days + 1)
    print(f"查询窗口 (UTC): {start_dt:%Y-%m-%d %H:%M} ~ {end_dt:%Y-%m-%d %H:%M}"
          f"   服务器 {HOST}:{PORT}")

    ensure_login()
    cookie, token = get_session_headers()
    headers_extra = (
        f"Cookie: {cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    all_rows, offset, pages = [], 0, 0
    grand_total = None
    while pages < MAX_PAGES:
        condition = dict(HIS_ALARM_CONDITION)
        condition["alarmraisedtime"] = {
            "mode": "0",
            "start": int(start_dt.timestamp() * 1000),
            "end": int(end_dt.timestamp() * 1000),
        }
        condition["from"] = offset
        condition["size"] = PAGE_SIZE
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
            + f"{datetime.now(timezone.utc).microsecond:06d}"[:-3] + "Z"
        payload = {"querynum": PAGE_SIZE, "condition": condition,
                   "timestamp": iso_ts, "manual": True}
        path = f"{HIS_ALARM_API_PATH}?timestamp={now_ms}"
        status, _, _, body = _http_request(
            "POST", path, headers_extra=headers_extra,
            body=json.dumps(payload))
        data, ok = _safe_json_loads(body.decode("utf-8"),
                                    label=f"HisAlarm(offset={offset})")
        if not (ok and isinstance(data, dict) and data.get("code") in (0, None, "0")):
            raise RuntimeError(f"API 返回异常: {str(data)[:200]}")
        rows = _normalize_alarm_rows(parse_response(data, label="HisAlarm") or [])
        all_rows.extend(rows)
        pages += 1
        # 服务端单页实际上限可能是 2000（无视请求的 size），以 totalcount 为准
        tc = data.get("totalcount") or data.get("total")
        try:
            grand_total = int(tc) if tc is not None else grand_total
        except (TypeError, ValueError):
            pass
        print(f"  第 {pages} 页 offset={offset}: 拉到 {len(rows)} 条"
              + (f" / 总计 {grand_total}" if grand_total else ""))
        if not rows:
            break
        if grand_total and offset + len(rows) >= grand_total:
            break
        if len(rows) < 100:   # 异常小页，防死循环
            break
        offset += len(rows)   # 按实际返回数递增，不能用请求的 size

    hits = [r for r in all_rows
            if str(r.get("TT ID", "")).strip() == tt_no]
    # 翻页边界会产生重叠记录，按 id 去重
    seen, uniq_hits = set(), []
    for r in hits:
        k = str(r.get("id") or (str(r.get("TT ID")) + str(r.get("alarmraisedtime"))))
        if k not in seen:
            seen.add(k)
            uniq_hits.append(r)
    return uniq_hits, all_rows


def main():
    ap = argparse.ArgumentParser(description="按 TT 单号查 eFlow 历史告警")
    ap.add_argument("tt_no", help="TT 单号，如 TT202608220047")
    ap.add_argument("--days-back", type=int, default=2,
                    help="当天查不到时，向前再扩查的天数（默认 2）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tt = args.tt_no.strip().upper()
    # 从单号推断日期
    try:
        date_part = tt[2:10]           # TT202608220047 -> 20260822
        target = datetime.strptime(date_part, "%Y%m%d").date()
    except (ValueError, IndexError):
        print(f"✗ 无法从单号 {tt} 解析日期（预期格式 TTyyyymmddNNNN）")
        return 1

    try:
        hits, all_rows = fetch_day(target, args.days_back, tt)
    except Exception as e:
        print(f"✗ 查询失败: {type(e).__name__}: {e}")
        return 1

    if args.json:
        out = []
        for r in hits:
            out.append({k: r.get(k) for k in INTERESTING_COLS + ASSIGN_COLS} | {
                "alarmraisedtime": ms_to_str(r.get("alarmraisedtime")),
                "alarmclearedtime": ms_to_str(r.get("alarmclearedtime")),
            })
        print(json.dumps({"tt_no": tt, "scanned": len(all_rows), "hits": out},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"\n扫描告警 {len(all_rows)} 条，命中 {len(hits)} 条")
    print("=" * 84)
    if not hits:
        print(f"eFlow 历史告警里没有 TT ID = {tt} 的记录。")
        print("可能原因：该 TT 的告警 TT ID 为空/为 '-'（同步同样会丢弃）；或时间窗不在范围内。")
        print("备选：到 eFlow 界面 FM > History Alarm 按单号手动过滤确认。")
        return 1

    for i, r in enumerate(hits, 1):
        print(f"\n#{i}")
        for col in INTERESTING_COLS:
            v = r.get(col)
            if v is not None and str(v).strip() not in ("", "--"):
                print(f"  {col:20s} {str(v)[:90]}")
        for col in ASSIGN_COLS:
            v = r.get(col)
            if v is None or str(v).strip() in ("", "--"):
                continue
            if "Time" in col:
                v = ms_to_str(v)
            print(f"  {col:20s} {str(v)[:90]}")
        print(f"  {'告警发生':20s} {ms_to_str(r.get('alarmraisedtime'))}")
        print(f"  {'告警恢复':20s} {ms_to_str(r.get('alarmclearedtime'))}")

    # 同站点的其他告警 —— 判断派单时刻各制式真实状态的关键
    site_ids = {str(r.get("Site ID", "")).strip() for r in hits} - {"", "--"}
    others, oseen = [], set()
    for r in all_rows:
        if str(r.get("Site ID", "")).strip() in site_ids:
            k = str(r.get("id"))
            if k and k not in oseen:
                oseen.add(k)
                others.append(r)
    if len(others) > len(hits):
        print(f"\n【同站点（Site ID={'/'.join(sorted(site_ids))}）全部告警，按发生时间排序】")
        for r in sorted(others, key=lambda x: str(x.get("alarmraisedtime"))):
            mark = " ←本TT" if str(r.get("TT ID", "")).strip() == tt else ""
            print(f"  {ms_to_str(r.get('alarmraisedtime'))} 发生 → "
                  f"{ms_to_str(r.get('alarmclearedtime'))} 恢复 | "
                  f"{str(r.get('Type') or r.get('restypename'))[:10]:10s} | "
                  f"{str(r.get('codename'))[:36]:36s} | TT={str(r.get('TT ID'))[:16]}{mark}")
        print("  ↑ 判断「派单时刻各制式是否掉站」看这张表，不要看 TT 上的 impacted_service"
              "（那是事后追加的汇总）")

    # 3G 恢复 vs 派单时间
    print("\n" + "=" * 84)
    g3 = [r for r in others
          if "3G" in (str(r.get("codename", "")) + str(r.get("Type", ""))).upper()
          and "SITE DOWN" in str(r.get("codename", "")).upper()]
    if g3:
        for r in g3:
            clr, asn = r.get("alarmclearedtime"), r.get("Assign Start Time")
            note = ""
            try:
                c = int(float(str(clr).replace(".0", "")))
                a = int(float(str(asn).replace(".0", "")))
                note = ("  → 3G 恢复【早于】该告警的派单时点"
                        if c < a else "  → 3G 恢复【晚于】该告警的派单时点")
            except (TypeError, ValueError):
                pass
            print(f"3G 告警: 发生 {ms_to_str(r.get('alarmraisedtime'))} | "
                  f"恢复 {ms_to_str(clr)} | 规则派单 {ms_to_str(asn)}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
