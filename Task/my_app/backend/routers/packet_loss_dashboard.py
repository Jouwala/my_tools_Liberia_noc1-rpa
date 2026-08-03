# -*- coding: utf-8 -*-
"""
丢包看板 API（Packet Loss Dashboard）
数据源: data/packet_lost/lte_pl.sqlite3（由 packet_loss_service 写入）
设计参考 alarm_dashboard.py：带 TTL 的内存缓存 + 下钻明细。
"""
import time
import re
import sqlite3
import logging
from pathlib import Path

from fastapi import APIRouter, Query
from backend.database import get_raw_connection

logger = logging.getLogger("packet_loss_dashboard")

router = APIRouter(prefix="/api/packet-loss-dashboard", tags=["packet-loss-dashboard"])

PL_DB_PATH = Path(r"d:\01_RPA\Task\my_app\data\packet_lost\lte_pl.sqlite3")

STATUS_ORDER = ["Critical[>5]", "Major[1-5]", "Minor[0.5-1]", "Warning[0.1-0.5]", "No Packet loss[<0.1]"]

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
    conn = get_raw_connection(str(PL_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _median(xs) -> float:
    """数值列表的中位值（忽略 None）；空列表返回 0.0。"""
    vals = [x for x in xs if x is not None]
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    m = n // 2
    med = s[m] if n % 2 else (s[m - 1] + s[m]) / 2
    return round(med, 2)


def _load_summary_rows():
    cached = _cache_get("summary_rows")
    if cached is not None:
        return cached
    if not PL_DB_PATH.exists():
        return _cache_set("summary_rows", [])
    conn = _conn()
    try:
        if not _table_exists(conn, "site_pl_summary"):
            return _cache_set("summary_rows", [])
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM site_pl_summary ORDER BY LastDayMaxPL DESC").fetchall()]
    finally:
        conn.close()
    return _cache_set("summary_rows", rows)


def _load_meta():
    cached = _cache_get("meta")
    if cached is not None:
        return cached
    meta = {}
    if PL_DB_PATH.exists():
        conn = _conn()
        try:
            if _table_exists(conn, "pl_meta"):
                for r in conn.execute("SELECT key, value FROM pl_meta"):
                    meta[r["key"]] = r["value"]
        finally:
            conn.close()
    return _cache_set("meta", meta)


@router.get("/overview")
def pl_overview():
    """丢包看板总览：状态分布 / Top站点 / 区域分布 / 每日趋势"""
    rows = _load_summary_rows()
    meta = _load_meta()

    status_counts = {s: 0 for s in STATUS_ORDER}
    region_counts: dict = {}
    for r in rows:
        st = r.get("FinalStatus") or "No Packet loss[<0.1]"
        status_counts[st] = status_counts.get(st, 0) + 1
        if st != "No Packet loss[<0.1]":
            region = r.get("region") or "Unknown"
            bucket = region_counts.setdefault(region, {"sites": 0, "critical": 0, "max_pl": 0.0})
            bucket["sites"] += 1
            if st == "Critical[>5]":
                bucket["critical"] += 1
            bucket["max_pl"] = max(bucket["max_pl"], r.get("LastDayMaxPL") or 0)

    total_sites = len(rows)
    status_pie = [{"status": s, "count": status_counts.get(s, 0),
                   "pct": round(status_counts.get(s, 0) / total_sites * 100, 2) if total_sites else 0}
                  for s in STATUS_ORDER]

    # 中位数口径说明（避免两类陷阱）：
    # 1) 对所有读数取中位会被 0 拉成 0（逐小时 pl 约 59% 为 0，零膨胀）→ 失去意义。
    #    解决：daily_trend 是「全网当天丢包强度」聚合，取非零中位 = 有丢包时的典型值，合理。
    # 2) 但站点级（top_sites）若也取非零中位，会被偶发的 100% 全断小时顶到 100——
    #    实际上「半天正常半天全断」的站点和「整天全断」的站点都成 100，丧失区分度。
    #    解决：站点级取「所有整点读数（含 0）」的中位 = 当天典型小时丢包率。
    #    已按 FinalStatus != No Packet loss 预过滤掉健康站点，所以中位不为 0；
    #    持续全断 → 100（事实），间歇严重 → 介于 0~100（区分出来）。
    site_median: dict = {}
    daily_trend = []
    if PL_DB_PATH.exists():
        conn = _conn()
        try:
            if _table_exists(conn, "packet_loss_data"):
                # 每日：按天聚合 day -> 非零 pl 列表 + 受影响站点集合，用中位值替代求和
                day_data: dict = {}
                for r in conn.execute(
                    'SELECT substr("Begin Time",1,10) AS day, '
                    '"Packet Loss Rate(%)" AS pl, "Managed Element" AS me '
                    'FROM packet_loss_data '
                    'WHERE "Begin Time" >= (SELECT datetime(max("Begin Time"), \'-6 days\') FROM packet_loss_data)'):
                    if r["pl"] > 0:
                        d = day_data.setdefault(r["day"], {"nz": [], "aff": set()})
                        d["nz"].append(r["pl"])
                        if r["pl"] > 0.1:
                            d["aff"].add(r["me"])
                for day in sorted(day_data.keys()):
                    d = day_data[day]
                    daily_trend.append({"day": day, "median_pl": _median(d["nz"]),
                                        "affected_sites": len(d["aff"])})
                daily_trend = daily_trend[-7:]  # 仅保留最近 7 天，与标题一致

                # Top Sites：最近 24 个整点时刻为窗口，计算每站点「所有读数」的中位值（含 0）。
                # packet_loss_data."Managed Element" 形如 "Name(CODE)"，而 site_pl_summary 用 Site_Name + Site_Code，
                # 故按末尾 (CODE) 提取后按 Site_Code 关联，失败再退回按 Site_Name 关联。
                cut = conn.execute(
                    'SELECT "Begin Time" FROM packet_loss_data '
                    'GROUP BY "Begin Time" ORDER BY "Begin Time" DESC LIMIT 24').fetchall()
                if cut:
                    cutoff = cut[-1]["Begin Time"]  # 第 24 新的时刻 = 窗口起点
                    me_by_code: dict = {}
                    me_by_name: dict = {}
                    for r in conn.execute(
                        'SELECT "Managed Element" AS me, "Packet Loss Rate(%)" AS pl '
                        'FROM packet_loss_data WHERE "Begin Time" >= ?', (cutoff,)):
                        me = r["me"]
                        m = re.search(r"\((\d+)\)\s*$", me)
                        if m:
                            me_by_code.setdefault(m.group(1), []).append(r["pl"])
                            me_by_name.setdefault(me[:m.start()].strip(), []).append(r["pl"])
                        else:
                            me_by_name.setdefault(me, []).append(r["pl"])
                    for code, vals in me_by_code.items():
                        site_median[code] = _median(vals)
                    for nm, vals in me_by_name.items():
                        site_median.setdefault(nm, _median(vals))
        finally:
            conn.close()

    def _resolve_median(row) -> float:
        code = str(row.get("Site_Code") or "")
        if code and code in site_median:
            return site_median[code]
        nm = site_median.get(row["Site_Name"])
        return nm if nm is not None else 0.0

    top_sites = [
        {"site_name": r["Site_Name"], "site_code": r.get("Site_Code") or "",
         "region": r.get("region") or "", "gateway": r.get("gateway") or "",
         "status": r.get("FinalStatus") or "",
         "last_day_max_pl": round(r.get("LastDayMaxPL") or 0, 2),
         "last_day_median_pl": round(_resolve_median(r), 2),
         "affected_hours": r.get("AffectedHours") or 0}
        for r in rows if (r.get("FinalStatus") or "") != "No Packet loss[<0.1]"
    ]
    top_sites.sort(key=lambda x: x["last_day_median_pl"], reverse=True)
    top_sites = top_sites[:15]

    affected_total = sum(v for k, v in status_counts.items() if k != "No Packet loss[<0.1]")
    return {
        "generated_at": meta.get("last_sync_time"),
        "report_path": meta.get("report_path"),
        "total_sites": total_sites,
        "affected_sites": affected_total,
        "status_counts": status_counts,
        "status_pie": status_pie,
        "top_sites": top_sites,
        "region_dist": dict(sorted(region_counts.items(), key=lambda kv: -kv[1]["sites"])),
        "daily_trend": daily_trend,
    }


@router.get("/map-sites")
def pl_map_sites(include_ok: bool = Query(False)):
    """地图点位：有经纬度的站点 + 丢包状态（仅返回有丢包的站点 + 可选全部）"""
    rows = _load_summary_rows()
    sites = []
    for r in rows:
        st = r.get("FinalStatus") or "No Packet loss[<0.1]"
        if st == "No Packet loss[<0.1]" and include_ok is not True:
            continue
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        sites.append({
            "site_name": r["Site_Name"], "site_code": r.get("Site_Code") or "",
            "lat": r["latitude"], "lng": r["longitude"],
            "region": r.get("region") or "", "province_county": r.get("province_county") or "",
            "gateway": r.get("gateway") or "", "network_type": r.get("network_type") or "",
            "status": st, "last_day_max_pl": round(r.get("LastDayMaxPL") or 0, 2),
            "total_pl": round(r.get("TotalPL") or 0, 2),
            "affected_hours": r.get("AffectedHours") or 0,
        })
    return {"sites": sites, "total": len(sites)}


@router.get("/drilldown")
def pl_drilldown(status: str = Query(""), search: str = Query(""), limit: int = Query(500)):
    """下钻明细：按状态/关键字过滤站点汇总"""
    rows = _load_summary_rows()
    if status and status != "all":
        rows = [r for r in rows if r.get("FinalStatus") == status]
    if search:
        kw = search.lower()
        rows = [r for r in rows
                if kw in str(r.get("Site_Name", "")).lower()
                or kw in str(r.get("Site_Code", "")).lower()
                or kw in str(r.get("region", "")).lower()]
    total = len(rows)
    rows = rows[:limit]
    title = status if status and status != "all" else "All Sites"
    return {"title": title, "total": total, "data": rows}
