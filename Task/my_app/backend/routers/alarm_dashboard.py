"""Alarm Dashboard API - 实时告警综合看板"""
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import openpyxl
import pandas as pd
from fastapi import APIRouter, Query
from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import list_table_names


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _row_as_dict(cursor):
    """单行 cursor -> dict 或 None（双模兼容）"""
    cols = [d[0] for d in cursor.description]
    r = cursor.fetchone()
    return dict(zip(cols, r)) if r is not None else None


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
    return name in set(list_table_names(conn))


def _load_history_df():
    """加载 history_alarm 并计算三个派单时效指标（全部向量化）。返回 (df, metrics)。"""
    with get_raw_connection() as conn:
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

        # 最新数据时间（告警本身的最新 servertime，仅作回退）
        latest_ms = df["servertime"].max()
        latest_iso = (
            datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if pd.notna(latest_ms) else "N/A"
        )

        has_tt = df["tt_id"].notna() & (df["tt_id"].astype(str).str.strip() != "") & (df["tt_id"].astype(str) != "-")

        # 真正的“数据更新时间” = realtime_alarm 最后成功同步的时刻（eflow_active_alarm 任务）
        sync_iso = _last_alarm_sync_iso()

        metrics = {
            "total": int(len(df)),
            "with_tt": int(has_tt.sum()),
            "dispatch_delay_eflow": int(m_dispatch_delay.sum()),
            "alarm_fetch_delay": int(m_fetch_delay.sum()),
            "dispatch_overdue_total": int(m_overdue.sum()),
            "generated_at": sync_iso or latest_iso,
        }
        return df, metrics


# ---- 轻量 TTL 缓存：避免看板并发/自动刷新时重复全表扫描 ----
_CACHE_TTL = 60  # 秒
_cache: dict = {}  # key -> (expires_ts, value)


def _cache_get(key):
    item = _cache.get(key)
    if item and item[0] > time.time():
        return item[1]
    return None


def _cache_set(key, value):
    _cache[key] = (time.time() + _CACHE_TTL, value)
    return value


def _history_metrics_sql():
    """用纯 SQL 聚合计算历史告警派单时效 5 项指标（免 pandas 全表载入）。
    与 _load_history_df 的向量化口径完全一致（已比对验证）。"""
    cached = _cache_get("history_metrics")
    if cached is not None:
        return cached

    with get_raw_connection() as conn:
        if not _table_exists(conn, "history_alarm"):
            conn.close()
            return None
        # history_alarm 现已统一为 TEXT 列（与 SQLite 动态类型语义一致），
        # PG 侧数值运算需先安全 CAST（空串/非数字 -> NULL，避免 text 运算/转换报错）。
        def _bn(col):
            return (f"CASE WHEN \"{col}\" IS NOT NULL AND \"{col}\" ~ '^[0-9]+$' "
                    f"THEN \"{col}\"::bigint ELSE NULL END")
        _ad = ("NULLIF(TRIM(REPLACE(REPLACE(COALESCE(\"assign_delay\",''),'min',''),'s','')),'')"
               "::double precision")
        cur = conn.execute(
            f"""
        SELECT COUNT(*) AS total,
          SUM(CASE WHEN "tt_id" IS NOT NULL AND TRIM(CAST("tt_id" AS TEXT))!=''
                    AND CAST("tt_id" AS TEXT)!='-' THEN 1 ELSE 0 END) AS with_tt,
          SUM(CASE WHEN ({_bn('assigned_time')} - {_bn('servertime')})
                    > {_ad}*1.1*1000 THEN 1 ELSE 0 END) AS dispatch_delay,
          SUM(CASE WHEN ({_bn('servertime')} - {_bn('alarmraisedtime')})
                    > 300000 THEN 1 ELSE 0 END) AS fetch_delay,
          SUM(CASE WHEN ({_bn('assigned_time')} - {_bn('alarmraisedtime')}) > 300000
                    AND ({_bn('assigned_time')} - {_bn('alarmraisedtime')})
                        > {_ad}*1.1*1000 THEN 1 ELSE 0 END) AS overdue,
          MAX({_bn('servertime')}) AS latest_ms
        FROM history_alarm
        """
        )
        row = _row_as_dict(cur)
        conn.close()

        if not row or not row["total"]:
            return None

        latest_ms = row["latest_ms"]
        latest_iso = (
            datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if latest_ms else "N/A"
        )
        metrics = {
            "total": int(row["total"]),
            "with_tt": int(row["with_tt"] or 0),
            "dispatch_delay_eflow": int(row["dispatch_delay"] or 0),
            "alarm_fetch_delay": int(row["fetch_delay"] or 0),
            "dispatch_overdue_total": int(row["overdue"] or 0),
            "generated_at": _last_alarm_sync_iso() or latest_iso,
        }
        return _cache_set("history_metrics", metrics)


def _load_history_df_cached():
    """下钻用：带 60s 缓存的全量 DataFrame 载入。"""
    cached = _cache_get("history_df")
    if cached is not None:
        return cached
    result = _load_history_df()
    if result[0] is not None:
        _cache_set("history_df", result)
    return result


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

# ========== 实时告警下钻（realtime_alarm 各维度筛选）==========
SEVERITY_MAP = {1: "Critical", 2: "Major", 3: "Warning", 4: "Info"}


def _load_realtime_rows():
    """加载 realtime_alarm 并预计算增强字段（技术制式/时长桶/区域码），带 60s 缓存。"""
    cached = _cache_get("realtime_rows")
    if cached is not None:
        return cached
    with get_raw_connection() as conn:
        cur = conn.execute("SELECT * FROM realtime_alarm")
        rows = _rows_as_dicts(cur)
        conn.close()
        for r in rows:
            r["_tech"] = _tech_from_record(r)
            r["_hours"] = _parse_duration_to_hours(r.get("durationname") or "")
            r["_bucket"] = _duration_bucket(r["_hours"])
            r["_region_code"] = REGION_CODE.get(r.get("region") or "", "--")
        return _cache_set("realtime_rows", rows)


# 各维度筛选器（与前端图表/卡片口径一致）
REALTIME_DIMENSION_FILTER = {
    "severity": lambda rows, v: [
        r for r in rows
        if SEVERITY_MAP.get(r.get("perceivedseverity") or 0, f"P{r.get('perceivedseverity')}") == v
    ],
    "tech": lambda rows, v: [r for r in rows if r.get("_tech") == v],
    "region": lambda rows, v: [r for r in rows if r.get("_region_code") == v],
    "alarm_type": lambda rows, v: [
        r for r in rows if (r.get("alarm_title") or r.get("codename") or "--") == v
    ],
    "site_attribute": lambda rows, v: [
        r for r in rows if _safe_str(r.get("site_attribute")) == v
    ],
    "networktype": lambda rows, v: [
        r for r in rows if _safe_str(r.get("networktype")) == v
    ],
    "duration": lambda rows, v: [r for r in rows if r.get("_bucket") == v],
}

REALTIME_DIMENSION_TITLE = {
    "all": "实时告警 (全部 Active Alarms)",
    "severity": "严重等级 = {v}",
    "tech": "技术制式 = {v}",
    "region": "区域 = {v}",
    "alarm_type": "告警类型 = {v}",
    "site_attribute": "站点属性 = {v}",
    "networktype": "网络类型 = {v}",
    "duration": "持续时长 = {v}",
}


def _realtime_record(r: dict) -> dict:
    sev = r.get("perceivedseverity")
    sev_label = SEVERITY_MAP.get(sev, f"P{sev}" if sev is not None else "--")
    return {
        "site_id": _safe_str(r.get("site_id")),
        "site_name": _safe_str(r.get("site_name")),
        "region": _safe_str(r.get("region")),
        "tech": _safe_str(r.get("_tech")),
        "alarm_title": _safe_str(r.get("alarm_title") or r.get("codename")),
        "severity": sev_label,
        "networktype": _safe_str(r.get("networktype")),
        "site_attribute": _safe_str(r.get("site_attribute")),
        "duration": _safe_str(r.get("durationname")),
        "alarm_raised_time": _ms_to_str(r.get("alarmraisedtime")),
        "server_time": _ms_to_str(r.get("servertime")),
        "assigned_time": _ms_to_str(r.get("assigned_time")),
        "assigned_status": _safe_str(r.get("assigned_status")),
        "tt_id": _safe_str(r.get("tt_id")),
        "vendor": _safe_str(r.get("vendor")),
        "transmission_type": _safe_str(r.get("transmission_type")),
    }


def _ms_to_str(ms):
    try:
        if pd.isna(ms):
            return None
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _ms_to_str: exception swallowed", exc_info=True)
        return None


def _ms_to_min(ms):
    try:
        if pd.isna(ms):
            return None
        return round(float(ms) / 60000, 1)
    except (ValueError, TypeError):
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _ms_to_min: exception swallowed", exc_info=True)
        return None


def _last_alarm_sync_iso() -> str:
    """realtime_alarm 数据实际最后成功同步的时间（eflow_active_alarm 任务最后成功完成的时刻）。
    优先返回真实刷新时间；无记录时回退到 None（由调用方回退到最新告警 servertime）。"""
    try:
        with get_raw_connection() as conn:
            cur = conn.execute(
                "SELECT completed_at FROM task_execution_log "
                "WHERE task_id='eflow_active_alarm' AND success=1 AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1"
            )
            row = _row_as_dict(cur)
        if row and row["completed_at"]:
            s = str(row["completed_at"]).replace("T", " ").replace("Z", "")
            return (s[:16] + " UTC") if len(s) >= 16 else (s + " UTC")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _last_alarm_sync_iso: exception swallowed", exc_info=True)
        pass
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
    with get_raw_connection() as conn:
        cur = conn.execute("SELECT * FROM realtime_alarm")
        rows = _rows_as_dicts(cur)
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
        # 受影响站点数（单次遍历，按区域收集唯一站点）
        _region_sites = {}
        for r in rows:
            rc = r["_region_code"]
            if rc in region_sites_count:
                _region_sites.setdefault(rc, set()).add(r.get("site_id"))
        for rc, sites in _region_sites.items():
            region_sites_count[rc] = len(sites)

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

        # ---- 历史告警派单时效指标（纯 SQL 聚合 + 60s 缓存，免 10 万行 pandas 载入）----
        history_metrics = _history_metrics_sql()

        return {
            "generated_at": _last_alarm_sync_iso() or server_iso,
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
                "generated_at": _last_alarm_sync_iso() or server_iso,
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
    df, _ = _load_history_df_cached()
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


@router.get("/realtime-drilldown")
def alarm_realtime_drilldown(
    dimension: str = Query("all"),
    value: str = Query(""),
    limit: int = Query(500, ge=1, le=5000),
):
    """实时告警明细下钻。
    dimension: all | severity | tech | region | alarm_type | site_attribute | networktype | duration
    value: 维度对应的取值（severity/tech/region/alarm_type/site_attribute/networktype/duration 需要）
    limit: 返回明细行数上限（默认500）
    """
    rows = _load_realtime_rows()
    if not rows:
        return {"title": "No data", "count": 0, "total": 0, "data": []}

    if dimension in ("all", "", None):
        filtered = rows
    else:
        fn = REALTIME_DIMENSION_FILTER.get(dimension)
        filtered = fn(rows, value) if fn else rows

    total_matched = len(filtered)
    filtered_sorted = sorted(
        filtered, key=lambda r: r.get("servertime") or 0, reverse=True
    )[:limit]

    records = [_realtime_record(r) for r in filtered_sorted]

    title_tmpl = REALTIME_DIMENSION_TITLE.get(dimension, dimension)
    title = title_tmpl.format(v=value) if "{v}" in title_tmpl else title_tmpl

    return {
        "title": title,
        "count": len(records),
        "total": total_matched,
        "data": records,
    }


# =====================================================================
# 告警总览 Alarm Overview（realtime_alarm 计数 / history_alarm 恢复&MTTR /
# xlsx 网络可用率 三合一）
# =====================================================================

# ZTE UME 5 级严重度模型：1=Critical, 2=Major, 3=Minor, 4=Warning, 5=Event
ALARM_CATEGORIES = ["Critical", "Major", "Minor", "Warning", "Event"]
SEV_INT_MAP = {1: "Critical", 2: "Major", 3: "Minor", 4: "Warning", 5: "Event"}
SEV_NAME_MAP = {
    "Critical": "Critical", "Major": "Major", "Minor": "Minor",
    "Warning": "Warning", "Event": "Event",
}
# 网络可用率阈值（百分比）：< 99.65 标红，>= 标深绿
NETWORK_THRESHOLD_PCT = 99.65
_MTTR_24H_MIN = 24 * 60

_RAN_UME_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ran_ume"
_NETWORK_KPI_XLSX = _RAN_UME_DIR / "Daily_Aailability_KPI.xlsx"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _alarm_category_counts(conn):
    """realtime_alarm 按 ZTE UME 5 级严重度统计各分类数字 + ALL。

    映射优先级：perceivedseverityname 直接命中 > perceivedseverity 整数映射。
    未命中已知 5 类的行归并为 Event（UMЕ 5 级之外/事件型告警兜底）。
    """
    if not _table_exists(conn, "realtime_alarm"):
        return {"ALL": 0, **{c: 0 for c in ALARM_CATEGORIES}}
    cur = conn.execute(
        'SELECT "perceivedseverity", "perceivedseverityname", COUNT(*) AS c '
        'FROM realtime_alarm GROUP BY "perceivedseverity", "perceivedseverityname"'
    )
    rows = _rows_as_dicts(cur)
    bucket = {c: 0 for c in ALARM_CATEGORIES}
    total = 0
    for r in rows:
        sev = r.get("perceivedseverity")
        name = _safe_str(r.get("perceivedseverityname"), "").strip()
        c = int(r.get("c") or 0)
        total += c
        cat = None
        if name in SEV_NAME_MAP:
            cat = SEV_NAME_MAP[name]
        elif sev is not None:
            try:
                cat = SEV_INT_MAP.get(int(sev))
            except (ValueError, TypeError):
                cat = None
        if cat is None:
            cat = "Event"
        if cat in bucket:
            bucket[cat] += c
    return {"ALL": total, **bucket}


def _recovery_mttr(conn):
    """history_alarm 按 site_class 统计恢复与 MTTR。

    仅计入 assign_rulename 不为 Null/空/'Null' 的记录。
    - recovered_24h：MTTR = (cleared - raised)/60000 < 24*60 分钟
    - avg_mttr_min：同口径平均分钟数（仅统计有有效 cleared/raised 的行）
    """
    if not _table_exists(conn, "history_alarm"):
        return []
    sql = f"""
    SELECT "site_class",
      COUNT(*) AS total,
      SUM(CASE WHEN "alarmclearedtime" IS NOT NULL AND "alarmclearedtime" ~ '^[0-9]+$'
                    AND "alarmraisedtime" IS NOT NULL AND "alarmraisedtime" ~ '^[0-9]+$'
                    AND ("alarmclearedtime"::bigint - "alarmraisedtime"::bigint) >= 0
                    AND ("alarmclearedtime"::bigint - "alarmraisedtime"::bigint)/60000.0 < {_MTTR_24H_MIN}
               THEN 1 ELSE 0 END) AS recovered_24h,
      AVG(CASE WHEN "alarmclearedtime" ~ '^[0-9]+$' AND "alarmraisedtime" ~ '^[0-9]+$'
                    AND ("alarmclearedtime"::bigint - "alarmraisedtime"::bigint) >= 0
               THEN ("alarmclearedtime"::bigint - "alarmraisedtime"::bigint)/60000.0 ELSE NULL END) AS avg_mttr_min
    FROM history_alarm
    WHERE "assign_rulename" IS NOT NULL AND TRIM("assign_rulename") != ''
      AND "assign_rulename" != 'Null'
    GROUP BY "site_class"
    ORDER BY "site_class"
    """
    cur = conn.execute(sql)
    out = []
    for r in _rows_as_dicts(cur):
        total = int(r.get("total") or 0)
        recovered = int(r.get("recovered_24h") or 0)
        avg = r.get("avg_mttr_min")
        out.append({
            "site_class": _safe_str(r.get("site_class"), "--"),
            "total": total,
            "recovered_24h": recovered,
            "avg_mttr_min": round(float(avg), 1) if avg is not None else None,
            "recovery_rate": round(recovered / total * 100, 1) if total else None,
        })
    return out


def _network_availability():
    """读取 Daily_Aailability_KPI.xlsx 的 Availability-NW 页，按 Cell Group 统计
    最新一天 Cell Availability 与本月（最新数据所在月）平均值。

    返回 {"rows":[{cell_group,latest_date,latest,month_avg,series}], "threshold_pct",
          "latest_month"}
    其中 series = [{"d": "YYYY-MM-DD", "v": 0.97375}, …]，最近 30 天的逐日值
    （2026-09-25 加，供前端画可用率趋势线）。
    ⚠️ 不返回「窗口天数」这个字段：路由 (alarm_overview) 是**逐字段挑着拼**响应的，
    多一个键要在两处同步；而前端本来就能从 series 的长度算出窗口，
    那个数还永远不会与数据本身脱节。少一处能对不上的地方。
    带 60s TTL 缓存（避免每次刷新重读 xlsx）。"""
    cached = _cache_get("network_availability")
    if cached is not None:
        return cached

    result = {"rows": [], "threshold_pct": NETWORK_THRESHOLD_PCT, "latest_month": None}
    try:
        if not _NETWORK_KPI_XLSX.is_file():
            logging.getLogger(__name__).warning(
                "[alarm-overview] network KPI xlsx 不存在: %s", _NETWORK_KPI_XLSX)
            return _cache_set("network_availability", result)
        wb = openpyxl.load_workbook(_NETWORK_KPI_XLSX, read_only=True, data_only=True)
        if "Availability-NW" not in wb.sheetnames:
            wb.close()
            logging.getLogger(__name__).warning(
                "[alarm-overview] 缺少 Availability-NW 页")
            return _cache_set("network_availability", result)
        ws = wb["Availability-NW"]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if len(rows) < 2:
            return _cache_set("network_availability", result)

        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        try:
            i_date = header.index("Begin Time")
            i_group = header.index("Cell Group")
            i_avail = header.index("Cell Availability")
        except ValueError:
            return _cache_set("network_availability", result)

        data = []
        for r in rows[1:]:
            if r[0] is None:
                continue
            bt = str(r[i_date]).strip()
            cg = str(r[i_group]).strip()
            try:
                av = float(r[i_avail])
            except (TypeError, ValueError):
                continue
            data.append((bt, cg, av))
        if not data:
            return _cache_set("network_availability", result)

        # 本月 = 全部数据中最晚一天所在的年-月
        max_date = max(d[0] for d in data)
        ym = max_date[:7]

        by_group = defaultdict(list)
        for bt, cg, av in data:
            by_group[cg].append((bt, av))

        out_rows = []
        for cg, items in by_group.items():
            items_sorted = sorted(items, key=lambda x: x[0])
            latest_date, latest_val = items_sorted[-1]
            month_items = [av for bt, av in items_sorted if bt[:7] == ym]
            month_avg = round(sum(month_items) / len(month_items), 5) if month_items else None
            out_rows.append({
                "cell_group": cg,
                "latest_date": latest_date,
                "latest": round(latest_val, 5),
                "month_avg": month_avg,
            })
        out_rows.sort(key=lambda x: x["cell_group"])

        # ---- 逐日序列（2026-09-25 加，供前端的可用率趋势线用）----
        # 上面那一步把 items_sorted 压成了「最新值 + 本月均值」两个标量，
        # 而**逐日数据本来就在手上**（items_sorted 就是 (日期, 可用率) 的列表），
        # 只是被丢掉了。前端要画「2G/3G/4G 可用率走势」就得把它带上 ——
        # 单独再开一个接口重读一次 xlsx 是白费：同一个文件、同一份缓存。
        #
        # 窗口取**最近 N 天**而不是全部 425 天：
        #   ① 前端只画得下 30 天（再多横轴就挤成一片，看不出起伏）；
        #   ② 425 个点 × 4 组会让这个响应的体积翻好几倍，而其中 90% 的画不出来。
        # 按天取尾部的 N 天，与前端「每格 1 天」的说明文字对得上。
        #
        # ⚠️ 不做任何补点：源文件里这 4 组各自连续、无缺口（实测 425 天全齐），
        # 但万一将来缺一天，前端会按「断线」渲染 —— 补 0 会画出一个
        # 「可用率跌到 0」的假谷底，那是比缺口更严重的撒谎。
        series_days = 30
        for row in out_rows:
            items_sorted = sorted(by_group[row["cell_group"]], key=lambda x: x[0])
            row["series"] = [{"d": bt, "v": round(av, 5)} for bt, av in items_sorted[-series_days:]]
        result = {
            "rows": out_rows,
            "threshold_pct": NETWORK_THRESHOLD_PCT,
            "latest_month": ym,
        }
    except Exception:
        logging.getLogger(__name__).warning(
            "[SILENT-EXCEPT] _network_availability: exception swallowed", exc_info=True)
    return _cache_set("network_availability", result)


@router.get("/alarm-overview")
def alarm_overview():
    """告警总览（Alarm Overview）：
    1) realtime_alarm 分类计数（ALL/Critical/Major/Minor/Warning/Event）
    2) history_alarm 恢复&MTTR（按 site_class，仅 assign_rulename 非 Null）
    3) 网络可用率（xlsx Availability-NW，按 Cell Group 最新值+本月均值）
    """
    with get_raw_connection() as conn:
        alarm_counts = _alarm_category_counts(conn)
        recovery = _recovery_mttr(conn)
    network = _network_availability()
    return {
        "generated_at": _last_alarm_sync_iso() or _now_iso(),
        "alarm_counts": alarm_counts,
        "recovery_mttr": recovery,
        "network_availability": network["rows"],
        "network_threshold_pct": network["threshold_pct"],
        "network_latest_month": network["latest_month"],
    }
