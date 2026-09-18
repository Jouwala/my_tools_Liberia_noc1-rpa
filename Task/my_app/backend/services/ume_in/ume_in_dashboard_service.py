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

用法：
    # 抓默认看板面板（dashboard_id=4, panel_id=39，最近 6 小时），打印结构化摘要
    python -m backend.services.ume_in.ume_in_dashboard_service

    # 指定看板/面板/时间窗，并把原始 JSON 落文件核对
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

from backend.services.ume_in.ume_in_kpi_service import UMEPortalClient, _runtime_credentials

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
    ap = argparse.ArgumentParser(description="UME 看板(guard-imonitor-service)数据抓取")
    ap.add_argument("--dashboard-id", type=int, default=DEFAULT_DASHBOARD_ID)
    ap.add_argument("--panel-id", type=int, nargs="*", default=[DEFAULT_PANEL_ID],
                    help="可传多个面板 id")
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="回看小时数")
    ap.add_argument("--begin", help=f"覆盖 begintime（{TIME_FMT}）")
    ap.add_argument("--end", help=f"覆盖 endtime（{TIME_FMT}）")
    ap.add_argument("--save", help="把原始 JSON 写到该文件路径")
    ap.add_argument("--full", action="store_true", help="打印完整 JSON（默认只打摘要）")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

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


if __name__ == "__main__":
    main()
