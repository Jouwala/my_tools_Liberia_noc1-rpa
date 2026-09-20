# -*- coding: utf-8 -*-
"""UME 看板（guard-imonitor-service dashboard）数据抓取脚本（ume_in）

数据来源（见 backend/services/ume_in/url.txt）：
    https://172.17.208.1:28808/em-portal/  （账号 10172755）
    看板接口  POST /api/guard-imonitor-service/v1/comm/fixPmDatas
    Body：{"begintime":"2026-09-18 09:48:00","dashboard_id":4,
           "panel_id":39,"endtime":"2026-09-18 15:48:00"}

与 ume_in_kpi_service.py 的关系：
- **鉴权完全复用**其 ``UMEPortalClient``（原始 socket + TLS 免证书校验 →
  OAuth2 authorize → RSA 公钥 → login_rsa → 拿 cookie/forgery_token，全程内存不落盘）。
- 本模块只是把请求打到 **另一个服务** （guard-imonitor-service 看板），
  body 结构不同：时间是**本地时间字符串**（"%Y-%m-%d %H:%M:%S"，非 PM-analysis 的 ISO UTC），
  且靠 ``dashboard_id`` + ``panel_id`` 定位看板上的某块面板。

每日落库（本模块新增能力）：
- 每天只记 **1 行/曲线**：取「裁决时间」（默认 20:00）截至前 **3 个 5 分钟粒度点**
  （即 time ∈ {20:00, 19:55, 19:50}）的 **最大值** 作为当天的值，异常标志取该最大点。
- 直写主库表 ``ume_in_dashboard_daily``（复用 mw_ume 的 save_to_db：全 TEXT 列 +
  唯一索引 upsert，主键 day+dashboard_id+panel_id+series_name，重跑幂等）。
- **滚动保留 14 天**：每次同步后 DELETE day < 今天-14 的行。
- 仅做能力，未接调度器；接入定时任务时需另行登记 task_registry / worker 分组 / 前端帮助。

用法：
    # 预览：抓默认看板面板（dashboard_id=4, panel_id=39，最近 6 小时），打印结构化摘要（不落库）
    python -m backend.services.ume_in.ume_in_dashboard_service

    # 每日同步落库：当天 20:00 裁决前 3 粒度取最大 → 落库 → 清理 14 天前
    python -m backend.services.ume_in.ume_in_dashboard_service --sync

    # 回补指定日 / 指定裁决小时 / 多面板（dashboard:panel 逗号分隔）
    python -m backend.services.ume_in.ume_in_dashboard_service --sync --decision-day 2026-09-17
    python -m backend.services.ume_in.ume_in_dashboard_service --sync --hour 15 --panels "4:39,4:40"

    # 预览指定看板/面板/时间窗，并把原始 JSON 落文件核对
    python -m backend.services.ume_in.ume_in_dashboard_service \
        --dashboard-id 4 --panel-id 39 --hours 6 --save TMP/dash_4_39.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

from backend.database import get_raw_connection
from backend.services.ume_in.ume_in_kpi_service import (
    UMEPortalClient,
    _runtime_credentials,
)
# 落库复用项目统一的 sqlite/PG 双模 upsert（全 TEXT 列 + key_cols 唯一索引）
from backend.services.mw_ume.mw_ume_kpi_service import save_to_db

logger = logging.getLogger("ume_in_dashboard_service")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 非 Windows / 已被重定向时忽略
    pass

# ============================================================
# 看板接口配置（可用环境变量覆盖）
# ============================================================
DASHBOARD_PATH = os.environ.get(
    "UME_IN_DASHBOARD_PATH", "/api/guard-imonitor-service/v1/comm/fixPmDatas"
)

# 默认看板/面板（与用户抓包一致：dashboard_id=4, panel_id=39）
DEFAULT_DASHBOARD_ID = int(os.environ.get("UME_IN_DASHBOARD_ID", "4"))
DEFAULT_PANEL_ID = int(os.environ.get("UME_IN_PANEL_ID", "39"))

# 默认回看窗口（抓包样例为 6 小时：09:48:00 ~ 15:48:00）
DEFAULT_HOURS = int(os.environ.get("UME_IN_DASHBOARD_HOURS", "6"))

# 看板 body 里的时间格式：本地时间字符串（**不是** PM-analysis 的 ISO UTC）
TIME_FMT = "%Y-%m-%d %H:%M:%S"

# ============================================================
# 落库 / 每日聚合 / 保留期配置（可用环境变量覆盖）
# ============================================================
# 每天只存 1 行/曲线：取“裁决时间”（默认 20:00）截至前 3 个 5 分钟粒度点的最大值。
TABLE_NAME = os.environ.get("UME_IN_DASHBOARD_TABLE", "ume_in_dashboard_daily")
RETENTION_DAYS = int(os.environ.get("UME_IN_DASHBOARD_RETENTION_DAYS", "14"))
DECISION_HOUR = int(os.environ.get("UME_IN_DASHBOARD_DECISION_HOUR", "20"))  # 20:00
GRANULARITY_MIN = int(os.environ.get("UME_IN_DASHBOARD_GRANULARITY_MIN", "5"))
POINTS_PER_DAY = int(os.environ.get("UME_IN_DASHBOARD_POINTS_PER_DAY", "3"))
# 每日任务要记录的面板清单 (dashboard_id, panel_id)；默认与抓包一致
DEFAULT_PANELS = [(DEFAULT_DASHBOARD_ID, DEFAULT_PANEL_ID)]

# 落库列（全 TEXT）：每天×每曲线一行；主键 day+dashboard_id+panel_id+series_name
HEADERS = [
    "day", "dashboard_id", "panel_id", "series_name", "series_type",
    "value_max", "value_max_time", "points_found",
    "is_abnormal", "is_wave_abnormal", "is_threshold_abnormal",
    "is_ai_suspected", "is_ai_abnormal", "is_avg_abnormal",
    "window_begin", "window_end", "fetch_time",
]
KEY_COLS = ["day", "dashboard_id", "panel_id", "series_name"]


# ============================================================
# 时间窗：本地时间字符串
# ============================================================
def build_window(hours=DEFAULT_HOURS, end_dt=None):
    """返回 (begintime, endtime) 本地时间字符串，窗口为 [end-hours, end]。"""
    end_dt = end_dt or datetime.now()
    begin_dt = end_dt - timedelta(hours=hours)
    return begin_dt.strftime(TIME_FMT), end_dt.strftime(TIME_FMT)


# ============================================================
# 单面板抓取
# ============================================================
def fetch_panel(client, dashboard_id, panel_id, begintime, endtime):
    """调用看板 fixPmDatas 接口，返回解析后的 JSON（无法解析时返回 {"_raw": text}）。"""
    payload = {
        "begintime": begintime,
        "dashboard_id": int(dashboard_id),
        "panel_id": int(panel_id),
        "endtime": endtime,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    logger.info(f"[DASH] POST {DASHBOARD_PATH} {payload}")

    # _request_retry / _auth_headers 复用了 UMEPortalClient 的会话 cookie + forgery_token
    status, _hdrs, _raw, resp = client._request_retry(
        "POST", DASHBOARD_PATH, headers_extra=client._auth_headers(), body=body
    )
    text = resp.decode("utf-8", errors="replace")
    if "200" not in status:
        raise Exception(f"看板请求失败: dashboard={dashboard_id} panel={panel_id} "
                        f"{status} {text[:300]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[DASH] 响应非 JSON，返回原文前 500 字符供排查")
        return {"_raw": text[:500], "_status": status}


def fetch_panels(client, dashboard_id, panel_ids, begintime, endtime):
    """逐面板抓取，返回 {panel_id: data 或 {"error": ...}}（单面板失败不影响其它）。"""
    out = {}
    for pid in panel_ids:
        try:
            out[pid] = fetch_panel(client, dashboard_id, pid, begintime, endtime)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[DASH] panel={pid} failed: {e}")
            out[pid] = {"error": str(e)}
        time.sleep(0.3)  # 轻微限速，避免打爆看板后端
    return out


def parse_panel_result(data):
    """把 fixPmDatas 响应拆成结构化摘要。

    响应结构（实测）：
        {"err_code":0, "err_message":"Success.",
         "result":{"data":[{"series_types":{"series_name","series_type"},
                              "pmdata":[{"time","value","isAbnormal",
                                          "isWaveAbnormal","isThresholdAbnormal",
                                          "isAiAbnormal","isAvgAbnormal", ...}]}],
                   "map":{...请求回显...},
                   "panelStatus":"normal",
                   "abnormalPMData":[...]}}
    任一层缺失都容错返回 None/空，不抛异常。
    """
    if not isinstance(data, dict):
        return {"ok": False, "error": "响应不是对象"}

    err_code = data.get("err_code")
    err_message = data.get("err_message")
    result = data.get("result") or {}
    series_raw = result.get("data") or []

    series = []
    total_points = 0
    abnormal_points = 0
    for s in series_raw:
        st = s.get("series_types") or {}
        pts = s.get("pmdata") or []
        total_points += len(pts)
        n_abn = 0
        for p in pts:
            if any(str(p.get(k, "0")) == "1" for k in
                   ("isAbnormal", "isWaveAbnormal", "isThresholdAbnormal",
                    "isAiAbnormal", "isAvgAbnormal")):
                n_abn += 1
        abnormal_points += n_abn
        series.append({
            "series_name": st.get("series_name"),
            "series_type": st.get("series_type"),
            "points": len(pts),
            "abnormal": n_abn,
            "first_time": pts[0].get("time") if pts else None,
            "last_time": pts[-1].get("time") if pts else None,
            "last_value": pts[-1].get("value") if pts else None,
        })

    return {
        "ok": err_code in (0, "0", None),
        "err_code": err_code,
        "err_message": err_message,
        "panel_status": result.get("panelStatus"),
        "series_count": len(series),
        "total_points": total_points,
        "abnormal_points": abnormal_points,
        "abnormal_pm_count": len(result.get("abnormalPMData") or []),
        "series": series,
    }


# ============================================================
# 每日聚合：“裁决时间”前 N 个粒度点取最大 → 1 行/曲线
# ============================================================
def _num(v):
    """PM value 转 float；不可解析返回 None。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def decision_time(day=None, hour=DECISION_HOUR):
    """当天裁决时刻（默认 20:00:00）。day 可为 None(今天)/"YYYY-MM-DD"/date。"""
    if day is None:
        base = datetime.now()
    elif isinstance(day, str):
        base = datetime.strptime(day[:10], "%Y-%m-%d")
    else:  # date / datetime
        base = datetime(day.year, day.month, day.day)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def target_point_times(dec_dt, n=POINTS_PER_DAY, step=GRANULARITY_MIN):
    """裁决时刻截至前 n 个粒子的 time 集（含裁决点）：如 {20:00, 19:55, 19:50}。"""
    return {(dec_dt - timedelta(minutes=step * i)).strftime(TIME_FMT) for i in range(n)}


def fetch_window_for_decision(dec_dt, minutes_before=40, minutes_after=10):
    """确保含目标点的拉取窗口 [dec-before, dec+after]（本地时间字符串）。"""
    begin = dec_dt - timedelta(minutes=minutes_before)
    end = dec_dt + timedelta(minutes=minutes_after)
    return begin.strftime(TIME_FMT), end.strftime(TIME_FMT)


def _reduce_series(series_obj, targets):
    """从单条曲线的 pmdata 中取目标粒度点，返回最大点摘要（含异常标志）。"""
    st = series_obj.get("series_types") or {}
    pts = [p for p in (series_obj.get("pmdata") or []) if p.get("time") in targets]
    base = {
        "series_name": st.get("series_name"), "series_type": st.get("series_type"),
        "value_max": None, "value_max_time": None, "points_found": len(pts),
        "is_abnormal": None, "is_wave_abnormal": None, "is_threshold_abnormal": None,
        "is_ai_suspected": None, "is_ai_abnormal": None, "is_avg_abnormal": None,
    }
    if not pts:
        return base

    # 取 value 最大点；并列时取时间更晚的那个（靠近裁决时刻）
    def keyf(p):
        v = _num(p.get("value"))
        return (v if v is not None else float("-inf"), str(p.get("time") or ""))

    best = max(pts, key=keyf)
    base.update({
        "value_max": best.get("value"),
        "value_max_time": best.get("time"),
        "is_abnormal": best.get("isAbnormal"),
        "is_wave_abnormal": best.get("isWaveAbnormal"),
        "is_threshold_abnormal": best.get("isThresholdAbnormal"),
        "is_ai_suspected": best.get("isAiSuspected"),
        "is_ai_abnormal": best.get("isAiAbnormal"),
        "is_avg_abnormal": best.get("isAvgAbnormal"),
    })
    return base


def compute_daily_rows(data, dashboard_id, panel_id, dec_dt, window, fetch_time):
    """把单面板响应聚合为今日行列表（每曲线一行），返回 (rows:list[list], parsed)。

    rows 按 HEADERS 顺序；即使未命中目标点（points_found=0）也落一行以便看出缺口。
    """
    parsed = parse_panel_result(data)
    result = (data or {}).get("result") or {}
    series_list = result.get("data") or []
    targets = target_point_times(dec_dt)
    day = dec_dt.strftime("%Y-%m-%d")
    wb, we = window

    rows = []
    for s in series_list:
        r = _reduce_series(s, targets)
        rows.append([
            day, str(dashboard_id), str(panel_id),
            r["series_name"] if r["series_name"] is not None else "",
            r["series_type"],
            r["value_max"], r["value_max_time"], str(r["points_found"]),
            r["is_abnormal"], r["is_wave_abnormal"], r["is_threshold_abnormal"],
            r["is_ai_suspected"], r["is_ai_abnormal"], r["is_avg_abnormal"],
            wb, we, fetch_time,
        ])
    return rows, parsed


def save_daily_rows(all_rows):
    """把聚合行 upsert 到主库表（复用 save_to_db），返回写入行数。"""
    if not all_rows:
        return 0
    return save_to_db(TABLE_NAME, HEADERS, all_rows, KEY_COLS)


def purge_old_rows(retention_days=RETENTION_DAYS):
    """删除 day < 今天-retention_days 的行（滚动保留，默认 14 天）。返回删除行数。

    day 为 "YYYY-MM-DD" 定宽日期，字典序比较与时间序一致；首次无表则静默跳过。
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    try:
        with get_raw_connection(timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute(f'DELETE FROM "{TABLE_NAME}" WHERE day < ?', (cutoff,))
            n = cur.rowcount or 0
            try:
                conn.commit()
            except Exception:  # noqa: BLE001 - PG autocommit 下 commit 可能空操作
                pass
        logger.info(f"[PURGE] {TABLE_NAME}: 删除 day<{cutoff} 共 {n} 行")
        return n
    except Exception as e:  # noqa: BLE001
        logger.info(f"[PURGE] 跳过（可能尚未建表）: {e}")
        return 0


# ============================================================
# 定时任务入口（只做能力，不自动接调度；需接入时由调用方 / 人工触发）
# ============================================================
def run_ume_in_dashboard_sync(panels=None, decision_day=None, hour=DECISION_HOUR,
                              retention_days=RETENTION_DAYS, client=None):
    """登录 → 逐面板拉当天裁决窗 → 取3粒度最大 → 落库 → 清理过期。

    Args:
        panels: [(dashboard_id, panel_id), ...]；None 用 DEFAULT_PANELS。
        decision_day: 裁决日（None=今天；"YYYY-MM-DD"=回补指定日）。
        hour: 裁决小时（默认 20）。
        retention_days: 保留天数（默认 14）。
        client: 复用已登录的 UMEPortalClient（None 则自行登录）。

    Returns: {success, rows_written, purged, table, day, panels, errors}
    """
    t0 = time.time()
    panels = panels or DEFAULT_PANELS
    result = {"success": False, "rows_written": 0, "purged": 0, "table": TABLE_NAME,
              "day": None, "panels": [], "errors": []}

    dec_dt = decision_time(decision_day, hour)
    result["day"] = dec_dt.strftime("%Y-%m-%d")
    fetch_time = datetime.now().strftime(TIME_FMT)
    window = fetch_window_for_decision(dec_dt)
    logger.info(f"[SYNC] ume_in dashboard day={result['day']} 裁决{dec_dt.strftime('%H:%M')} "
                f"窗 {window[0]}~{window[1]} panels={panels} table={TABLE_NAME}")

    owns_client = client is None
    cli = client or UMEPortalClient(**_login_args())
    if owns_client:
        cli.login()

    all_rows = []
    for (did, pid) in panels:
        try:
            data = fetch_panel(cli, did, pid, window[0], window[1])
            rows, parsed = compute_daily_rows(data, did, pid, dec_dt, window, fetch_time)
            if not parsed.get("ok"):
                result["errors"].append(
                    f"panel {did}/{pid}: err_code={parsed.get('err_code')} "
                    f"msg={parsed.get('err_message')}")
                continue
            if not rows:
                result["errors"].append(f"panel {did}/{pid}: 无曲线数据")
                continue
            all_rows.extend(rows)
            result["panels"].append({
                "dashboard_id": did, "panel_id": pid,
                "series": [{"name": r[HEADERS.index("series_name")],
                            "value_max": r[HEADERS.index("value_max")],
                            "at": r[HEADERS.index("value_max_time")],
                            "points_found": r[HEADERS.index("points_found")]}
                           for r in rows],
            })
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"panel {did}/{pid}: {e}")
            logger.error(f"[SYNC] panel {did}/{pid} failed: {e}")

    try:
        result["rows_written"] = save_daily_rows(all_rows)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"写库: {e}")
        logger.exception("[SYNC] save failed")

    try:
        result["purged"] = purge_old_rows(retention_days)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"清理: {e}")

    result["success"] = result["rows_written"] > 0 and not result["errors"]
    logger.info(f"[SYNC] done in {time.time() - t0:.1f}s rows={result['rows_written']} "
                f"purged={result['purged']} errors={result['errors']}")
    return result


# ============================================================
# 便捷入口（可被定时任务/其它模块直接调用）
# ============================================================
def fetch_dashboard(dashboard_id=DEFAULT_DASHBOARD_ID, panel_id=DEFAULT_PANEL_ID,
                    hours=DEFAULT_HOURS, client=None):
    """登录（或复用传入 client）后抓单面板，返回 (data, begintime, endtime)。"""
    owns_client = client is None
    cli = client or UMEPortalClient(**_login_args())
    if owns_client:
        cli.login()
    begintime, endtime = build_window(hours=hours)
    data = fetch_panel(cli, dashboard_id, panel_id, begintime, endtime)
    return data, begintime, endtime


def _login_args():
    """按运行时凭据构造 UMEPortalClient（不触发登录，交由调用方 .login()）。"""
    user, pwd = _runtime_credentials()
    return dict(username=user, password=pwd)


# ============================================================
# CLI
# ============================================================
def _summary(data):
    """打印友好的结构摘要：识别 err_code / panelStatus / series / 采样点 / 异常点。"""
    parsed = parse_panel_result(data)
    if not parsed.get("ok"):
        return (f"失败 err_code={parsed.get('err_code')} "
                f"msg={parsed.get('err_message') or parsed.get('error')}")
    lines = [f"panelStatus={parsed['panel_status']} "
             f"series={parsed['series_count']} points={parsed['total_points']} "
             f"abnormal={parsed['abnormal_points']}"]
    for s in parsed["series"]:
        lines.append(f"  · {s['series_name']}[{s['series_type']}] "
                     f"pts={s['points']} abnormal={s['abnormal']} "
                     f"last={s['last_value']}@{s['last_time']}")
    return "\n    ".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="UME 看板(guard-imonitor-service)数据抓取与落库")
    ap.add_argument("--dashboard-id", type=int, default=DEFAULT_DASHBOARD_ID)
    ap.add_argument("--panel-id", type=int, nargs="*", default=[DEFAULT_PANEL_ID],
                    help="可传多个面板 id")
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="预览模式回看小时数")
    ap.add_argument("--begin", help=f"覆盖 begintime（{TIME_FMT}）")
    ap.add_argument("--end", help=f"覆盖 endtime（{TIME_FMT}）")
    ap.add_argument("--save", help="把原始 JSON 写到该文件路径")
    ap.add_argument("--full", action="store_true", help="打印完整 JSON（默认只打摘要）")
    # ---- 落库/每日聚合模式 ----
    ap.add_argument("--sync", action="store_true",
                    help="每日同步模式：取当天20:00裁决前3粒度最大→落库→清理14天")
    ap.add_argument("--decision-day", help="回补指定日 YYYY-MM-DD（默今天）")
    ap.add_argument("--hour", type=int, default=DECISION_HOUR, help="裁决小时（默认 20）")
    ap.add_argument("--panels", help='面板清单，形如 "4:39,4:40"（dashboard:panel）')
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # ---- 同步落库模式 ----
    if args.sync:
        panels = _parse_panels_arg(args.panels) or DEFAULT_PANELS
        res = run_ume_in_dashboard_sync(panels=panels, decision_day=args.decision_day,
                                        hour=args.hour)
        print(f"\n[sync] day={res['day']} table={res['table']} "
              f"rows={res['rows_written']} purged={res['purged']} success={res['success']}")
        for p in res["panels"]:
            for s in p["series"]:
                print(f"  · dash={p['dashboard_id']} panel={p['panel_id']} "
                      f"{s['name']}: value_max={s['value_max']} @ {s['at']} "
                      f"(points_found={s['points_found']})")
        if res["errors"]:
            print("  errors:")
            for e in res["errors"]:
                print(f"    - {e}")
        return res

    # ---- 预览模式（打印结构，不落库）----
    user, pwd = _runtime_credentials()
    client = UMEPortalClient(username=user, password=pwd).login()

    if args.begin and args.end:
        begintime, endtime = args.begin, args.end
    else:
        begintime, endtime = build_window(hours=args.hours)

    results = fetch_panels(client, args.dashboard_id, args.panel_id, begintime, endtime)

    print(f"\n看板 dashboard_id={args.dashboard_id}  窗口 {begintime} ~ {endtime}")
    for pid, data in results.items():
        if isinstance(data, dict) and "error" in data:
            print(f"  panel={pid}: 失败 -> {data['error']}")
            continue
        print(f"  panel={pid}:\n    {_summary(data)}")
        if args.full:
            print(json.dumps(data, ensure_ascii=False, indent=2)[:8000])

    if args.save:
        os.makedirs(os.path.dirname(os.path.abspath(args.save)), exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump({"dashboard_id": args.dashboard_id, "begintime": begintime,
                       "endtime": endtime, "panels": results}, f, ensure_ascii=False, indent=2)
        print(f"\n[saved] {args.save}")

    return results


def _parse_panels_arg(s):
    """解析 "4:39,4:40" → [(4,39),(4,40)]；空/非法返回 None。"""
    if not s:
        return None
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            did, pid = part.split(":", 1)
            out.append((int(did), int(pid)))
        except ValueError:
            logger.warning(f"[CLI] 忽略非法 panel 描述: {part!r}")
    return out or None


if __name__ == "__main__":
    main()
