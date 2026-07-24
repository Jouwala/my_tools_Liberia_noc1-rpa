"""Alarm Dashboard API - 实时告警综合看板"""
import re
from datetime import datetime, timezone
import pandas as pd
from fastapi import APIRouter, Query
from backend.database import get_raw_connection, DB_PATH

router = APIRouter(prefix="/api/alarm-dashboard", tags=["alarm-dashboard"])

REGION_CODE = {
    "Bomi": "BM", "Bong": "BG", "Gbarpolu": "GP", "Grand_Bassa": "GB",
    "Grand_Cape_Mount": "GC", "Grand_Gedeh": "GG", "Grand_Kru": "GK",
    "Lofa": "LF", "Margibi": "MB", "Maryland": "MD", "Montserrado": "ML",
    "Nimba": "NB", "River_Cess": "RC", "River_Gee": "RG", "Sinoe": "SE",
}
COL_ORDER = ["GG", "GP", "GB", "GK", "RG", "NB", "SE", "RC", "GC", "BM", "BG", "LF", "MB", "ML", "MD"]
BUCKET_ORDER = ["0-2", "2-4", "4-6", "6-12", "12-24", ">48"]

# ========== 历史告警派单时效分析（向量化计算）==========
# 业务规则：
#   1. 派单延迟Eflow: (Assigned Time - servertime) > Assign Delay * 1.1 (超过允许派单时限10%)
#   2. 告警获取时间大: (servertime - alarmraisedtime) > 5 分钟
#   3. 总的派单超期单数: (Assigned Time - alarmraisedtime) > 5 分钟 且 > Assign Delay * 1.1
THRESHOLD_5MIN_MS = 5 * 60 * 1000
HIS_SEV_MAP = {1: "Critical", 2: "Major", 3: "Warning", 4: "Info"}


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()[0] > 0


def _load_history_df():
    """加载 history_alarm 并计算三个派单时效指标（全部向量化）。返回 (df, metrics)。"""
    conn = get_raw_connection()
    if not _table_exists(conn, "history_alarm"):
        conn.close()
        return None, None

    cols = (
        "alarmraisedtime, servertime, assigned_time, assign_delay, "
        "tt_id, site_id, site_name, region, perceivedseverity, "
        "alarm_title, codename, durationname"
    )
    df = pd.read_sql_query(f"SELECT {cols} FROM history_alarm", conn)
    conn.close()

    if df.empty:
        return df, None

    # 时间戳数值化（毫秒）
    df["alarmraisedtime"] = pd.to_numeric(df["alarmraisedtime"], errors="coerce")
    df["servertime"] = pd.to_numeric(df["servertime"], errors="coerce")
    df["assigned_time"] = pd.to_numeric(df["assigned_time"], errors="coerce")
    # Assign Delay '900s' -> 900 秒
    df["assign_delay_sec"] = (
        df["assign_delay"].astype(str).str.extract(r"(\d+)", expand=False).astype(float)
    )

    # 三个耗时差值（毫秒）
    df["assign_minus_server"] = df["assigned_time"] - df["servertime"]      # 派单耗时
    df["fetch_delay"] = df["servertime"] - df["alarmraisedtime"]           # 告警获取耗时
    df["assign_minus_raise"] = df["assigned_time"] - df["alarmraisedtime"] # 总派单耗时

    delay_limit_ms = df["assign_delay_sec"] * 1.1 * 1000  # 允许派单时限 + 10% 容差

    m_dispatch_delay = df["assign_minus_server"] > delay_limit_ms
    m_fetch_delay = df["fetch_delay"] > THRESHOLD_5MIN_MS
    m_overdue = (df["assign_minus_raise"] > THRESHOLD_5MIN_MS) & (
        df["assign_minus_raise"] > delay_limit_ms
    )

    df["_m_dispatch_delay"] = m_dispatch_delay
    df["_m_fetch_delay"] = m_fetch_delay
    df["_m_overdue"] = m_overdue

    # 最新数据时间
    latest_ms = df["servertime"].max()
    latest_iso = (
        datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if pd.notna(latest_ms) else "N/A"
    )

    has_tt = df["tt_id"].notna() & (df["tt_id"].astype(str).str.strip() != "") & (df["tt_id"].astype(str) != "-")

    metrics = {
        "total": int(len(df)),
        "with_tt": int(has_tt.sum()),
        "dispatch_delay_eflow": int(m_dispatch_delay.sum()),
        "alarm_fetch_delay": int(m_fetch_delay.sum()),
        "dispatch_overdue_total": int(m_overdue.sum()),
        "generated_at": latest_iso,
    }
    return df, metrics


METRIC_MASK_COL = {
    "dispatch_delay_eflow": "_m_dispatch_delay",
    "alarm_fetch_delay": "_m_fetch_delay",
    "dispatch_overdue_total": "_m_overdue",
}
METRIC_TITLE = {
    "all": "全部历史告警",
    "dispatch_delay_eflow": "派单延迟 Eflow (Assigned Time - Server Time 超时限10%)",
    "alarm_fetch_delay": "告警获取时间大 (Server - AlarmRaised > 5min)",
    "dispatch_overdue_total": "总的派单超期单数 (Assigned - AlarmRaised > 5min 且超时限10%)",
}


def _ms_to_str(ms):
    try:
        if pd.isna(ms):
            return None
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return None


def _ms_to_min(ms):
    try:
        if pd.isna(ms):
            return None
        return round(float(ms) / 60000, 1)
    except (ValueError, TypeError):
        return None


def _parse_duration_to_hours(s: str) -> float:
    """Parse '6h 35min 48s' or '8d 5h 27min 52s' into hours."""
    if not s:
        return 0.0
    h = 0.0
    m = re.search(r"(\d+)d", s)
    if m:
        h += int(m.group(1)) * 24
    m = re.search(r"(\d+)h", s)
    if m:
        h += int(m.group(1))
    m = re.search(r"(\d+)min", s)
    if m:
        h += int(m.group(1)) / 60
    m = re.search(r"(\d+)s", s)
    if m:
        h += int(m.group(1)) / 3600
    return h


def _duration_bucket(h: float) -> str:
    if h < 2:
        return "0-2"
    if h < 4:
        return "2-4"
    if h < 6:
        return "4-6"
    if h < 12:
        return "6-12"
    if h < 24:
        return "12-24"
    return ">48"


def _tech_from_record(r: dict) -> str:
    t = (r.get("type") or "")
    m = re.search(r"-(\d+G)\b", t)
    if m:
        return m.group(1)
    rt = r.get("restypename") or ""
    if "ENODEB" in rt or "GNB" in rt:
        return "4G"
    if "NODEB" in rt:
        return "3G"
    if "BTS" in rt:
        return "2G"
    return "OTHER"


def _safe_str(val, default="--"):
    if val is None or str(val).strip() == "" or str(val) == "None":
        return default
    return str(val)


@router.get("/overview")
def alarm_dashboard_overview():
    """实时告警综合看板数据"""
    conn = get_raw_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM realtime_alarm"
    ).fetchall()]
    conn.close()

    # 计算增强字段
    for r in rows:
        r["_tech"] = _tech_from_record(r)
        r["_hours"] = _parse_duration_to_hours(r.get("durationname") or "")
        r["_bucket"] = _duration_bucket(r["_hours"])
        r["_region_code"] = REGION_CODE.get(r.get("region") or "", "--")

    total = len(rows)
    servertime_ms = max((r.get("servertime") or 0) for r in rows) if rows else 0
    server_iso = datetime.fromtimestamp(servertime_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if servertime_ms else "N/A"

    # ---- 按技术制式汇总 ----
    tech_stats = {}
    for r in rows:
        t = r["_tech"]
        if t not in tech_stats:
            tech_stats[t] = {"sites": set(), "cells": 0}
        tech_stats[t]["sites"].add(r.get("site_id"))
        tech_stats[t]["cells"] += 1

    logical_total = {
        tech: {"site": len(st["sites"]), "cell": st["cells"]}
        for tech, st in tech_stats.items()
    }

    # ---- 按区域 × 技术制式 ----
    region_tech = {}
    for r in rows:
        rc = r["_region_code"]
        if rc == "--":
            continue
        tech = r["_tech"]
        region_tech.setdefault(rc, {}).setdefault(tech, {"sites": set(), "cells": 0})
        region_tech[rc][tech]["sites"].add(r.get("site_id"))
        region_tech[rc][tech]["cells"] += 1

    logical_site_map = {}
    logical_cell_map = {}
    for rc in COL_ORDER:
        logical_site_map[rc] = {}
        logical_cell_map[rc] = {}
        for tech in ["2G", "3G", "4G", "5G"]:
            d = region_tech.get(rc, {}).get(tech, {"sites": set(), "cells": 0})
            logical_site_map[rc][tech] = len(d["sites"])
            logical_cell_map[rc][tech] = d["cells"]

    # ---- 持续时长分布 ----
    all_buckets = {b: 0 for b in BUCKET_ORDER}
    mains_buckets = {b: 0 for b in BUCKET_ORDER}
    for r in rows:
        all_buckets[r["_bucket"]] = all_buckets.get(r["_bucket"], 0) + 1
        if r.get("transmission_type") == "MW":
            mains_buckets[r["_bucket"]] = mains_buckets.get(r["_bucket"], 0) + 1

    # ---- 严重等级 ----
    severity_map = {1: "Critical", 2: "Major", 3: "Warning", 4: "Info"}
    severity_stats = {}
    severity_raw = {}
    for r in rows:
        sev = r.get("perceivedseverity") or 0
        label = severity_map.get(sev, f"P{sev}")
        severity_stats[label] = severity_stats.get(label, 0) + 1
        severity_raw[label] = severity_raw.get(label, 0) + 1

    # ---- 站点属性分布 ----
    site_attr = {}
    for r in rows:
        a = _safe_str(r.get("site_attribute"))
        site_attr[a] = site_attr.get(a, 0) + 1

    # ---- 网络类型分布 ----
    nettype = {}
    for r in rows:
        n = _safe_str(r.get("networktype"))
        nettype[n] = nettype.get(n, 0) + 1

    # ---- 区域告警数 ----
    region_alarm_count = {rc: 0 for rc in COL_ORDER}
    region_mains_count = {rc: 0 for rc in COL_ORDER}
    region_sites_count = {rc: 0 for rc in COL_ORDER}
    for r in rows:
        rc = r["_region_code"]
        if rc in region_alarm_count:
            region_alarm_count[rc] = region_alarm_count.get(rc, 0) + 1
            if r.get("transmission_type") == "MW":
                region_mains_count[rc] = region_mains_count.get(rc, 0) + 1
    # 受影响站点数
    for r in rows:
        rc = r["_region_code"]
        if rc in region_sites_count:
            region_sites_count[rc] = len({r2.get("site_id") for r2 in rows if r2["_region_code"] == rc})

    # ---- 告警类型(Top) ----
    alarm_type_stats = {}
    for r in rows:
        at = _safe_str(r.get("alarm_title") or r.get("codename") or "--", "Unknown")
        alarm_type_stats[at] = alarm_type_stats.get(at, 0) + 1
    alarm_type_top = dict(sorted(alarm_type_stats.items(), key=lambda x: x[1], reverse=True)[:10])

    # ---- 站点状态 ----
    site_status_stats = {}
    for r in rows:
        ss = _safe_str(r.get("site_status"), "Unknown")
        site_status_stats[ss] = site_status_stats.get(ss, 0) + 1

    # ---- 受影响的唯一站点数 ----
    affected_sites = len({r.get("site_id") for r in rows if r.get("site_id")})

    # ---- 累计告警小时数 ----
    total_alarm_hours = sum(r["_hours"] for r in rows)

    # ---- 各区域主要告警类别(最多5个) ----
    region_alarm_type = {}
    for rc in COL_ORDER:
        region_rows = [r for r in rows if r["_region_code"] == rc]
        if region_rows:
            rtypes = {}
            for r in region_rows:
                at = _safe_str(r.get("alarm_title") or r.get("codename") or "--", "Unknown")
                rtypes[at] = rtypes.get(at, 0) + 1
            region_alarm_type[rc] = dict(sorted(rtypes.items(), key=lambda x: x[1], reverse=True)[:5])

    # ---- 历史告警派单时效指标 ----
    _, history_metrics = _load_history_df()

    return {
        "generated_at": server_iso,
        "total_alarms": total,
        "affected_sites": affected_sites,
        "total_alarm_hours": round(total_alarm_hours, 1),
        "logical_total": logical_total,
        "severity_stats": severity_stats,
        "duration_buckets": all_buckets,
        "duration_bucket_order": BUCKET_ORDER,
        "mains_duration_buckets": mains_buckets,
        "site_attribute": site_attr,
        "networktype": nettype,
        "region_alarm_count": region_alarm_count,
        "region_mains_count": region_mains_count,
        "region_sites_count": region_sites_count,
        "alarm_type_top": alarm_type_top,
        "site_status_stats": site_status_stats,
        "region_alarm_type": region_alarm_type,
        "logical_site": logical_site_map,
        "logical_cell": logical_cell_map,
        "column_order": COL_ORDER,
        "history": history_metrics or {
            "total": 0, "with_tt": 0, "dispatch_delay_eflow": 0,
            "alarm_fetch_delay": 0, "dispatch_overdue_total": 0, "generated_at": "N/A",
        },
    }


@router.get("/history-drilldown")
def alarm_history_drilldown(
    metric: str = Query("all"),
    limit: int = Query(500, ge=1, le=5000),
):
    """历史告警明细下钻。
    metric: all | dispatch_delay_eflow | alarm_fetch_delay | dispatch_overdue_total
    limit: 返回明细行数上限（默认500）
    """
    df, _ = _load_history_df()
    if df is None or df.empty:
        return {"title": METRIC_TITLE.get(metric, metric), "count": 0, "total": 0, "data": []}

    mask_col = METRIC_MASK_COL.get(metric)
    if mask_col:
        df = df[df[mask_col]]

    total_matched = len(df)
    # 按 servertime 倒序，截取前 limit 行
    df = df.sort_values("servertime", ascending=False).head(limit)

    # 构建输出行（向量化转可读格式）
    out = df.copy()
    out["alarm_raised_time"] = out["alarmraisedtime"].map(_ms_to_str)
    out["server_time"] = out["servertime"].map(_ms_to_str)
    out["assigned_time_str"] = out["assigned_time"].map(_ms_to_str)
    out["fetch_delay_min"] = out["fetch_delay"].map(_ms_to_min)
    out["assign_delay_min"] = out["assign_minus_server"].map(_ms_to_min)
    out["total_assign_min"] = out["assign_minus_raise"].map(_ms_to_min)
    out["severity"] = out["perceivedseverity"].map(
        lambda v: HIS_SEV_MAP.get(v, f"P{v}" if pd.notna(v) else "--")
    )
    out["alarm_name"] = out["alarm_title"].where(
        out["alarm_title"].notna() & (out["alarm_title"].astype(str).str.strip() != ""),
        out["codename"],
    )

    keep = [
        "tt_id", "site_id", "site_name", "region", "alarm_name", "severity",
        "durationname", "alarm_raised_time", "server_time", "assigned_time_str",
        "assign_delay", "fetch_delay_min", "assign_delay_min", "total_assign_min",
    ]
    records = out[keep].astype(object).where(out[keep].notna(), None).to_dict(orient="records")

    return {
        "title": METRIC_TITLE.get(metric, metric),
        "count": len(records),
        "total": total_matched,
        "data": records,
    }
