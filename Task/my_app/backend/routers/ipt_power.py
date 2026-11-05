# -*- coding: utf-8 -*-
"""
ipt_power.py - IPT 站点电源信息 API
====================================
供前端「站点电源查询」页面使用，数据来自 IPT Digital Platform（RMS 能源监控平台）：
- GET  /api/ipt-power/sites?keyword=&watch_only=   站点清单（ipt_power_sites）+ 最新快照摘要
- GET  /api/ipt-power/site/{site_id}?hours=24      单站详情：最新快照 + diagram 明细 + 历史序列
- POST /api/ipt-power/refresh                      实时直查 portal（绕开 2 分钟节拍）并落一条快照
- GET  /api/ipt-power/status                       采集运行状态（ipt_power_meta.last_run + 表计数）
- GET  /api/ipt-power/watch                        当前关注清单（watch_sites.json）

存储：主库表 ipt_power_sites / ipt_power_snapshots / ipt_power_site_detail / ipt_power_meta
（惰性建表 + 增量加列 sqlite/pg 双模，由 ipt_power_collector._ensure_tables 统一管理）。
2026-11-04 起全站 2 分钟分辨率：快照主源为轻量 popup KPI（全站每轮一条），
diagram 明细分片轮采并维护每站最新明细（ipt_power_site_detail，已剥设备凭据——
2026-11-04 前 /site/{id} 原样返回 raw 全量 diagram，其中带控制器明文口令，已修复）。
采集任务：ipt_power_collect（每 2 分钟，见 services/ipt_data/ipt_power_collector.py）。
与 settings / feedback 路由风格一致：内网本地访问不做额外鉴权。
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.database import get_raw_connection
from backend.services.ipt_data.ipt_power_collector import (
    DETAIL_TABLE,
    META_TABLE,
    SNAP_TABLE,
    SITES_TABLE,
    _ensure_tables,
    load_watch,
    save_snapshot,
)
from backend.services.ipt_data.ipt_energy_client import IptEnergyClient, IptEnergyError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ipt-power", tags=["ipt_power"])


def _conn():
    conn = get_raw_connection()
    cur = conn.cursor()
    _ensure_tables(cur)
    conn.commit()
    return conn


@router.get("/sites")
def list_sites(keyword: Optional[str] = Query(None, max_length=80),
               watch_only: bool = False, limit: int = Query(500, le=1000)):
    """站点清单 + 最新电源快照摘要（页面主表）。keyword 匹配名称/参考号/区域。"""
    watch = load_watch()
    watch_star = "*" in watch
    watch_keys = {w.casefold() for w in watch}
    conn = _conn()
    try:
        cur = conn.cursor()
        sql = (f"SELECT s.site_id, s.name, s.internal_reference, s.organization,"
               f" s.cluster, s.priority, s.configuration, s.connectivity, s.criticality,"
               f" s.lat, s.lon, s.connectivity_updated, s.updated_at,"
               f" k.snap_time, k.load_current, k.load_power, k.battery_voltage,"
               f" k.battery_soc, k.battery_charging_state, k.solar_power,"
               f" k.generator_on, k.fuel_ratio, k.fuel_level, k.fuel_capacity,"
               f" k.grid_on, k.main_source_on, k.solar_available,"
               f" k.alarm_count, k.alarm_names, k.source"
               f" FROM {SITES_TABLE} s"
               f" LEFT JOIN {SNAP_TABLE} k ON k.site_id = s.site_id"
               f" AND k.snap_time = (SELECT MAX(w.snap_time) FROM {SNAP_TABLE} w"
               f"                    WHERE w.site_id = s.site_id)")
        params = []
        conds = []
        if keyword:
            like = f"%{keyword}%"
            conds.append("(s.name LIKE ? OR CAST(s.internal_reference AS TEXT) LIKE ?"
                         " OR s.organization LIKE ? OR s.cluster LIKE ?)")
            params += [like, like, like, like]
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY s.name LIMIT ?"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["watched"] = bool(watch_star
                                or str(r["name"]).casefold() in watch_keys
                                or str(r["internal_reference"]).casefold() in watch_keys
                                or str(r["site_id"]).casefold() in watch_keys)
            if isinstance(r.get("alarm_names"), str):
                try:
                    r["alarm_names"] = json.loads(r["alarm_names"])
                except ValueError:
                    r["alarm_names"] = []
            elif r.get("alarm_names") is None:
                r["alarm_names"] = []
        if watch_only:
            rows = [r for r in rows if r["watched"]]
        return {"total": len(rows), "sites": rows}
    finally:
        conn.close()


@router.get("/site/{site_id}")
def site_detail(site_id: str, hours: int = Query(24, le=24 * 8)):
    """单站详情：站点信息 + 最新快照 + 历史序列（近 N 小时，时间升序）。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM {SITES_TABLE} WHERE site_id = ?", (site_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"站点不存在：{site_id}")
        site = dict(zip(cols, row))

        cur.execute(
            f"SELECT * FROM {SNAP_TABLE} WHERE site_id = ? ORDER BY snap_time DESC LIMIT 1",
            (site_id,))
        cols_k = [d[0] for d in cur.description]
        r = cur.fetchone()
        latest = dict(zip(cols_k, r)) if r else None
        # 安全：raw 是 diagram 的内部 JSON（含上游字段全集），不下发前端；
        # 明细统一走 ipt_power_site_detail（已剥除设备凭据）。
        if latest is not None:
            latest.pop("raw", None)
            if isinstance(latest.get("alarm_names"), str):
                try:
                    latest["alarm_names"] = json.loads(latest["alarm_names"])
                except ValueError:
                    latest["alarm_names"] = []

        # 每站最新 diagram 精简明细（油机相电压/电池容量与今日电压/油箱容量/环境等，
        # popup KPI 层没有这些字段；分片轮采更新，「立即刷新」实时补齐）
        cur.execute(
            f"SELECT detail, updated_at FROM {DETAIL_TABLE} WHERE site_id = ?", (site_id,))
        rd = cur.fetchone()
        detail = None
        if rd and rd[0]:
            try:
                detail = {"detail": json.loads(rd[0]), "updated_at": rd[1]}
            except (TypeError, ValueError):
                detail = None

        cutoff = (datetime.now() - timedelta(hours=int(hours))
                  ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            f"SELECT snap_time, load_current, load_power, battery_voltage,"
            f" battery_current, battery_power, battery_soc, battery_charging_state,"
            f" battery_temp1, generator_on, solar_power, solar_current,"
            f" fuel_level, fuel_ratio, grid_on, alarm_count"
            f" FROM {SNAP_TABLE} WHERE site_id = ? AND snap_time >= ?"
            f" ORDER BY snap_time",
            (site_id, cutoff))
        cols_h = [d[0] for d in cur.description]
        history = [dict(zip(cols_h, x)) for x in cur.fetchall()]
        return {"site": site, "latest": latest, "detail": detail, "history": history}
    finally:
        conn.close()


class RefreshBody(BaseModel):
    query: str  # 站点名 / 参考号 / site_id


@router.post("/refresh")
def refresh_site(body: RefreshBody):
    """实时直查 portal 并落一条快照（页面「立即刷新」；不依赖采集任务节拍）。"""
    try:
        client = IptEnergyClient()
    except IptEnergyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        sites = client.find_sites(body.query.strip())
        if not sites:
            raise HTTPException(status_code=404, detail=f"未找到站点：{body.query}")
        site = sites[0]
        diagram = client.get_site_diagram(site["id"])
        conn = _conn()
        try:
            cur = conn.cursor()
            save_snapshot(cur, site["id"], diagram)
            # filter-map 摘要同步刷新站点行（避免站点表里还没有这一行）
            cur.execute(
                f"SELECT COUNT(*) FROM {SITES_TABLE} WHERE site_id = ?", (site["id"],))
            if cur.fetchone()[0] == 0:
                from backend.services.ipt_data.ipt_power_collector import _upsert_sites
                _upsert_sites(cur, [site])
            conn.commit()
        finally:
            conn.close()
        return {"site_id": site["id"], "name": site["name"],
                "diagram": diagram, "snap_time": None}
    except HTTPException:
        raise
    except IptEnergyError as e:
        raise HTTPException(status_code=502, detail=f"IPT 平台查询失败：{e}")


@router.get("/status")
def status():
    """采集运行状态（页面顶部的「最后采集」提示条数据源）。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT value FROM {META_TABLE} WHERE key = 'last_run'")
        r = cur.fetchone()
        last_run = json.loads(r[0]) if r and r[0] else None
        for table in (SITES_TABLE, SNAP_TABLE, DETAIL_TABLE):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            if last_run is not None:
                last_run["rows_" + table] = n
        cur.execute(f"SELECT MAX(snap_time) FROM {SNAP_TABLE}")
        r = cur.fetchone()
        if last_run is not None:
            last_run["last_snapshot"] = r[0] if r else None
        return {"last_run": last_run}
    finally:
        conn.close()


@router.get("/watch")
def get_watch():
    """当前关注清单（页面只读展示；修改直接编辑 watch_sites.json）。"""
    return {"sites": load_watch()}
