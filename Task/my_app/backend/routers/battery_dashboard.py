# -*- coding: utf-8 -*-
"""
电池看板 API（Battery Dashboard）
数据源: data/battery/battery_kpi.sqlite3（由 battery_kpi_service 每小时写入）

设计要点（参考 packet_loss_dashboard.py：TTL 内存缓存 + 一次性聚合下发）
------------------------------------------------------------------
1. **新鲜度是第一公民**。实测约一半电池的读数已超过 7 天（最老 2024 年），
   若把过期读数混入均值，「平均 SOC/健康度」严重失真。因此所有均值类指标、
   充放电状态、低电量告警**一律只在 fresh 子集（默认 ≤24h）上计算**，
   过期数据单独作为「数据时效」维度和告警项呈现。
2. `/all` 一次性返回 KPI + 分布 + 站点汇总 + 告警 + 全量电池明细（~1500 行），
   前端侧边栏筛选（站点搜索、健康度/SOC 滑块、类别）全部在客户端即时完成，
   避免每次拖动滑块都打后端。
3. `/trend` 有两个数据源：
   - poll   : battery_trend，每次任务轮询一行的全网状态（随运行时长累积）
   - reading: battery_reading 按小时聚合的设备上报读数（历史立即可用）
   默认 auto：poll 样本 < 3 条时回退 reading，避免首日空图。
"""
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

logger = logging.getLogger("battery_dashboard")

router = APIRouter(prefix="/api/battery-dashboard", tags=["battery-dashboard"])

BATT_DB_PATH = Path(r"d:\01_RPA\Task\my_app\data\battery\battery_kpi.sqlite3")

# 默认阈值（实际以库中 battery_meta 为准，任务写入时会覆盖）
DEFAULTS = {
    "fresh_hours": 24.0,
    "stale_days": 7.0,
    "health_degraded": 90.0,
    "health_good": 95.0,
    "soc_critical": 20.0,
    "soc_low": 50.0,
}

SEV_ORDER = {"Critical": 0, "Major": 1, "Minor": 2, "OK": 3}

# ========== 简易 TTL 缓存 ==========
_cache: dict = {}
_CACHE_TTL = 60


def _cache_get(key: str):
    item = _cache.get(key)
    if item and time.time() - item[0] < _CACHE_TTL:
        return item[1]
    return None


def _cache_set(key: str, value):
    _cache[key] = (time.time(), value)
    return value


def _conn():
    # 注意：不能用 with get_raw_connection(...)（退出时会提交并关闭连接）
    from backend.database import get_raw_connection
    conn = get_raw_connection(str(BATT_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _avg(xs):
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _load_meta(conn) -> dict:
    meta = dict(DEFAULTS)
    if _table_exists(conn, "battery_meta"):
        for r in conn.execute("SELECT key, value FROM battery_meta").fetchall():
            k, v = r["key"], r["value"]
            if k in DEFAULTS:
                try:
                    meta[k] = float(v)
                except (TypeError, ValueError):
                    meta[k] = v
            else:
                meta[k] = v
    return meta


# ---------------------------------------------------------------------------
# 分桶
# ---------------------------------------------------------------------------

def _soc_bucket(soc) -> str:
    if soc is None:
        return "No Data"
    if soc <= 0:
        return "0% (Empty)"
    if soc < 20:
        return "<20% (Critical)"
    if soc < 50:
        return "20-50% (Low)"
    if soc < 80:
        return "50-80%"
    return "80-100%"


SOC_ORDER = ["0% (Empty)", "<20% (Critical)", "20-50% (Low)", "50-80%", "80-100%", "No Data"]


def _health_bucket(h, meta) -> str:
    if h is None:
        return "No Data"
    if h < 80:
        return "<80% (Severe)"
    if h < meta["health_degraded"]:
        return "80-90% (Degraded)"
    if h < meta["health_good"]:
        return "90-95% (Fair)"
    return ">=95% (Good)"


HEALTH_ORDER = ["<80% (Severe)", "80-90% (Degraded)", "90-95% (Fair)", ">=95% (Good)", "No Data"]

FRESH_ORDER = ["fresh", "delayed", "stale", "no_data"]


def _counts(items, order):
    d = {k: 0 for k in order}
    for it in items:
        d[it] = d.get(it, 0) + 1
    return [{"name": k, "value": d.get(k, 0)} for k in order]


# ---------------------------------------------------------------------------
# 告警生成
# ---------------------------------------------------------------------------

def _build_alarms(rows: list[dict], meta: dict) -> list[dict]:
    """告警规则（每块电池可命中多条，按类型区分）。

    Critical  严重低电量        : fresh 且 SOC < soc_critical(20)
    Critical  放电且电量不足     : fresh 且 Discharge 且 SOC < soc_low(50)
    Major     站点放电中         : fresh 且 Discharge（市电中断代理指标）
    Major     健康度劣化         : fresh 且 health < health_degraded(90)
    Major     数据长期未更新      : age > 30d
    Minor     数据过期           : stale_days(7d) < age <= 30d
    Minor     无数据上报         : 三个测量点均无时间戳
    """
    alarms = []
    soc_crit = meta["soc_critical"]
    soc_low = meta["soc_low"]
    h_deg = meta["health_degraded"]
    stale_h = meta["stale_days"] * 24

    for r in rows:
        fresh = r["freshness"] == "fresh"
        soc, health, status = r["soc"], r["health"], r["status"]
        age = r["age_hours"]
        base = {
            "site": r["site"], "category": r["category"], "position": r["position"],
            "mo": r["mo"], "soc": soc, "health": health, "status": status,
            "last_update": r["last_update"], "age_hours": age,
            "freshness": r["freshness"],
        }
        if fresh and soc is not None and soc < soc_crit:
            alarms.append({**base, "severity": "Critical", "type": "Critical SOC",
                           "detail": f"SOC {soc}% < {soc_crit:.0f}%"})
        if fresh and status == "Discharge" and soc is not None and soc < soc_low:
            alarms.append({**base, "severity": "Critical", "type": "Discharging & Low SOC",
                           "detail": f"Discharge @ SOC {soc}%"})
        if fresh and status == "Discharge":
            alarms.append({**base, "severity": "Major", "type": "Discharging",
                           "detail": "On battery (mains suspected down)"})
        if fresh and health is not None and health < h_deg:
            alarms.append({**base, "severity": "Major", "type": "Health Degraded",
                           "detail": f"Health {health}% < {h_deg:.0f}%"})
        if age is not None and age > 24 * 30:
            alarms.append({**base, "severity": "Major", "type": "Data Very Stale",
                           "detail": f"No update for {age / 24:.0f} days"})
        elif age is not None and age > stale_h:
            alarms.append({**base, "severity": "Minor", "type": "Data Stale",
                           "detail": f"No update for {age / 24:.1f} days"})
        if r["freshness"] == "no_data":
            alarms.append({**base, "severity": "Minor", "type": "No Data",
                           "detail": "No measurement timestamp"})

    alarms.sort(key=lambda a: (SEV_ORDER.get(a["severity"], 9),
                               -(a["age_hours"] or 0) if a["type"].startswith("Data") else 0,
                               a["soc"] if a["soc"] is not None else 999))
    return alarms


def _build_sites(rows: list[dict], alarms: list[dict], meta: dict) -> list[dict]:
    by_site: dict[str, list[dict]] = {}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)

    sev_by_site: dict[str, str] = {}
    for a in alarms:
        cur = sev_by_site.get(a["site"], "OK")
        if SEV_ORDER[a["severity"]] < SEV_ORDER[cur]:
            sev_by_site[a["site"]] = a["severity"]

    out = []
    for site, items in by_site.items():
        fresh_items = [r for r in items if r["freshness"] == "fresh"]
        socs = [r["soc"] for r in fresh_items if r["soc"] is not None]
        healths = [r["health"] for r in fresh_items if r["health"] is not None]
        last_updates = [r["last_update"] for r in items if r["last_update"]]
        out.append({
            "site": site,
            "category": items[0]["category"],
            "batteries": len(items),
            "fresh": len(fresh_items),
            "fresh_rate": round(len(fresh_items) * 100.0 / len(items), 1) if items else 0.0,
            "avg_soc": _avg(socs),
            "min_soc": min(socs) if socs else None,
            "avg_health": _avg(healths),
            "min_health": min(healths) if healths else None,
            "discharging": sum(1 for r in fresh_items if r["status"] == "Discharge"),
            "charging": sum(1 for r in fresh_items if r["status"] == "Charge"),
            "critical_soc": sum(1 for r in fresh_items
                                if r["soc"] is not None and r["soc"] < meta["soc_critical"]),
            "stale": sum(1 for r in items if r["freshness"] in ("stale", "no_data")),
            "last_update": max(last_updates) if last_updates else None,
            "severity": sev_by_site.get(site, "OK"),
        })
    out.sort(key=lambda s: (SEV_ORDER.get(s["severity"], 9),
                            s["min_soc"] if s["min_soc"] is not None else 999,
                            -s["stale"]))
    return out


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("/all")
def get_all():
    """一次性返回看板所需的全部聚合与明细（TTL 60s）。"""
    cached = _cache_get("all")
    if cached is not None:
        return cached

    if not BATT_DB_PATH.exists():
        return _cache_set("all", {
            "available": False,
            "message": "无电池数据（请执行任务: battery_kpi_sync）",
            "meta": {}, "kpi": {}, "dist": {}, "sites": [], "alarms": [], "batteries": [],
        })

    conn = _conn()
    try:
        meta = _load_meta(conn)
        if not _table_exists(conn, "battery_latest"):
            return _cache_set("all", {
                "available": False,
                "message": "无电池数据（请执行任务: battery_kpi_sync）",
                "meta": meta, "kpi": {}, "dist": {}, "sites": [], "alarms": [], "batteries": [],
            })
        rows = [dict(r) for r in conn.execute("SELECT * FROM battery_latest").fetchall()]
        trend_points = conn.execute("SELECT COUNT(*) FROM battery_trend").fetchone()[0] \
            if _table_exists(conn, "battery_trend") else 0
    finally:
        conn.close()

    if not rows:
        return _cache_set("all", {
            "available": False,
            "message": "无电池数据（请执行任务: battery_kpi_sync）",
            "meta": meta, "kpi": {}, "dist": {}, "sites": [], "alarms": [], "batteries": [],
        })

    fresh_rows = [r for r in rows if r["freshness"] == "fresh"]
    socs = [r["soc"] for r in fresh_rows if r["soc"] is not None]
    healths = [r["health"] for r in fresh_rows if r["health"] is not None]
    discharging = [r for r in fresh_rows if r["status"] == "Discharge"]
    critical = [r for r in fresh_rows if r["soc"] is not None and r["soc"] < meta["soc_critical"]]

    kpi = {
        "total_batteries": len(rows),
        "total_sites": len({r["site"] for r in rows}),
        "fresh": len(fresh_rows),
        "fresh_rate": round(len(fresh_rows) * 100.0 / len(rows), 1),
        "avg_health": _avg(healths),
        "avg_soc": _avg(socs),
        "discharging": len(discharging),
        "discharging_sites": len({r["site"] for r in discharging}),
        "critical_soc": len(critical),
        "critical_sites": len({r["site"] for r in critical}),
        "degraded": sum(1 for r in fresh_rows
                        if r["health"] is not None and r["health"] < meta["health_degraded"]),
        "stale": sum(1 for r in rows if r["freshness"] in ("stale", "no_data")),
        "stale_sites": len({r["site"] for r in rows if r["freshness"] in ("stale", "no_data")}),
    }

    # 分布
    dist_health = _counts([_health_bucket(r["health"], meta) for r in fresh_rows], HEALTH_ORDER)
    dist_soc = _counts([_soc_bucket(r["soc"]) for r in fresh_rows], SOC_ORDER)
    status_names = ["Charge", "Discharge", "Unknown"]
    dist_status = _counts([(r["status"] if r["status"] in ("Charge", "Discharge") else "Unknown")
                           for r in fresh_rows], status_names)
    dist_fresh = _counts([r["freshness"] for r in rows], FRESH_ORDER)

    # 健康度直方图（fresh 子集，2% 一档；实测数据集中在 98-100，仅作细粒度参考）
    hist: dict[int, int] = {}
    for r in fresh_rows:
        if r["health"] is None:
            continue
        b = int(r["health"] // 2 * 2)
        hist[b] = hist.get(b, 0) + 1
    health_hist = [{"bin": f"{b}-{b + 2}", "value": v} for b, v in sorted(hist.items())]

    # 类别维度（Satelite / Microwave / Pilot）
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    dist_category = []
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        f = [r for r in items if r["freshness"] == "fresh"]
        dist_category.append({
            "category": cat,
            "batteries": len(items),
            "sites": len({r["site"] for r in items}),
            "fresh": len(f),
            "fresh_rate": round(len(f) * 100.0 / len(items), 1) if items else 0.0,
            "avg_soc": _avg([r["soc"] for r in f if r["soc"] is not None]),
            "discharging": sum(1 for r in f if r["status"] == "Discharge"),
            "critical_soc": sum(1 for r in f
                                if r["soc"] is not None and r["soc"] < meta["soc_critical"]),
        })

    alarms = _build_alarms(rows, meta)
    sites = _build_sites(rows, alarms, meta)

    alarm_summary = {"Critical": 0, "Major": 0, "Minor": 0}
    for a in alarms:
        alarm_summary[a["severity"]] = alarm_summary.get(a["severity"], 0) + 1

    payload = {
        "available": True,
        "meta": {
            "last_sync_ts": meta.get("last_sync_ts"),
            "thresholds": {
                "fresh_hours": meta["fresh_hours"],
                "stale_days": meta["stale_days"],
                "health_degraded": meta["health_degraded"],
                "health_good": meta["health_good"],
                "soc_critical": meta["soc_critical"],
                "soc_low": meta["soc_low"],
            },
            "trend_points": trend_points,
        },
        "kpi": kpi,
        "alarm_summary": alarm_summary,
        "dist": {
            "health": dist_health,
            "health_hist": health_hist,
            "soc": dist_soc,
            "status": dist_status,
            "freshness": dist_fresh,
            "category": dist_category,
        },
        "sites": sites,
        "alarms": alarms[:2000],
        "batteries": rows,
    }
    return _cache_set("all", payload)


@router.get("/trend")
def get_trend(days: int = Query(7, ge=1, le=180),
              source: str = Query("auto", pattern="^(auto|poll|reading)$"),
              min_samples: int = Query(3, ge=1, le=500)):
    """趋势数据。

    poll   : battery_trend —— 每次任务轮询的全网状态快照（随运行时长累积）
    reading: battery_reading —— 按小时聚合设备实际上报的读数（历史立即可用）
    auto   : poll 样本 < 3 条时回退 reading
    """
    key = f"trend:{days}:{source}:{min_samples}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not BATT_DB_PATH.exists():
        return _cache_set(key, {"source": source, "points": []})

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn()
    try:
        use = source
        if source == "auto":
            n = conn.execute("SELECT COUNT(*) FROM battery_trend").fetchone()[0] \
                if _table_exists(conn, "battery_trend") else 0
            use = "poll" if n >= 3 else "reading"

        if use == "poll":
            if not _table_exists(conn, "battery_trend"):
                return _cache_set(key, {"source": "poll", "points": []})
            pts = [dict(r) for r in conn.execute(
                "SELECT * FROM battery_trend WHERE snapshot_ts >= ? ORDER BY snapshot_ts",
                (cutoff,)).fetchall()]
            return _cache_set(key, {"source": "poll", "points": pts})

        if not _table_exists(conn, "battery_reading"):
            return _cache_set(key, {"source": "reading", "points": []})
        pts = [dict(r) for r in conn.execute(
            """
            SELECT substr(reading_time, 1, 13) || ':00:00' AS snapshot_ts,
                   COUNT(*)                                   AS reported,
                   COUNT(DISTINCT site)                       AS sites,
                   ROUND(AVG(soc), 2)                         AS avg_soc,
                   ROUND(AVG(health), 2)                      AS avg_health,
                   SUM(CASE WHEN status = 'Discharge' THEN 1 ELSE 0 END) AS discharging,
                   SUM(CASE WHEN status = 'Charge'    THEN 1 ELSE 0 END) AS charging,
                   SUM(CASE WHEN soc < 20            THEN 1 ELSE 0 END) AS critical_soc,
                   SUM(CASE WHEN soc < 50            THEN 1 ELSE 0 END) AS low_soc
            FROM battery_reading
            WHERE reading_time >= ?
            GROUP BY substr(reading_time, 1, 13)
            HAVING COUNT(*) >= ?
            ORDER BY 1
            """, (cutoff, min_samples)).fetchall()]
        return _cache_set(key, {"source": "reading", "points": pts})
    finally:
        conn.close()


@router.get("/site/{site}")
def get_site_detail(site: str):
    """单站点全部电池明细（下钻用）。"""
    if not BATT_DB_PATH.exists():
        return {"site": site, "batteries": [], "readings": []}
    conn = _conn()
    try:
        if not _table_exists(conn, "battery_latest"):
            return {"site": site, "batteries": [], "readings": []}
        batteries = [dict(r) for r in conn.execute(
            "SELECT * FROM battery_latest WHERE site = ? ORDER BY position", (site,)).fetchall()]
        readings = []
        if _table_exists(conn, "battery_reading"):
            readings = [dict(r) for r in conn.execute(
                """SELECT position, reading_time, soc, health, status
                   FROM battery_reading WHERE site = ?
                   ORDER BY reading_time DESC LIMIT 500""", (site,)).fetchall()]
        return {"site": site, "batteries": batteries, "readings": readings}
    finally:
        conn.close()
