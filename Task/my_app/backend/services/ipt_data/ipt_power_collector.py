# -*- coding: utf-8 -*-
"""IPT 站点电源信息采集服务（定时 2 分钟，task_id=ipt_power_collect）。

数据源：IPT Digital Platform（RMS 能源监控平台，AWS 外网）
  - `POST /energy/sites/filter-map`：1 个请求拉全站（~498 站）清单与连接状态 → ipt_power_sites
  - `GET  /energy/sites/<id>/diagram`：单站电源全景 → ipt_power_snapshots（按关注清单采）

采集范围由同目录 watch_sites.json 控制（JSON 数组）：
  - `["*"]`                      → 全站（498 站每轮 498 请求，单轮远超 2 分钟，不建议）
  - `["Jahtondo Town", "1882"]`  → 按站点名 / 参考号 / site_id 匹配（推荐，≤50 站单轮可完成）
  - `[]`                         → 只刷全站状态，不采电源明细（最轻）

存储：主库 db/app.db（惰性建表，sqlite/pg 双模，范式同 routers/feedback.py）：
  - ipt_power_sites     站点清单 + 连接状态（每轮全量刷新）
  - ipt_power_snapshots 电源快照（关注站点，2 分钟一条，默认保留 2 天）
  - ipt_power_meta      采集运行状态（页面 /api/ipt-power/status 读取）

时间列统一「YYYY-MM-DD HH:MM:SS」本地字符串，规避 PG 下 ISO 带 T 的字符串比较失效问题。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.database import get_raw_connection
from backend.services.ipt_data.ipt_energy_client import IptEnergyClient, IptEnergyError

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
WATCH_FILE = os.path.join(_HERE, "watch_sites.json")

SITES_TABLE = "ipt_power_sites"
SNAP_TABLE = "ipt_power_snapshots"
META_TABLE = "ipt_power_meta"
RETENTION_DAYS = 2           # 快照保留期（超出即删，2026-11-03 如意定：曲线只留 2 天，控表体积）
SITE_REQUEST_INTERVAL = 0.3  # 逐站拉 diagram 的间隔（秒），对外网平台限速


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_tables(conn) -> None:
    """惰性建表 + 索引（sqlite / pg 双模，范式同 routers/feedback.py；
    get_raw_connection 的 PG 包装已把 ? 占位转 %s，统一用 sqlite 写法）。"""
    ddl = [
        f"""
        CREATE TABLE IF NOT EXISTS {SITES_TABLE} (
            site_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            internal_reference TEXT,
            organization TEXT,
            cluster TEXT,
            priority TEXT,
            configuration TEXT,
            connectivity TEXT,
            criticality TEXT,
            lat REAL,
            lon REAL,
            connectivity_updated TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {SNAP_TABLE} (
            site_id TEXT NOT NULL,
            snap_time TEXT NOT NULL,
            connectivity TEXT,
            load_current REAL,
            load_power REAL,
            battery_voltage REAL,
            battery_current REAL,
            battery_power REAL,
            battery_soc REAL,
            battery_charging_state TEXT,
            battery_temp1 REAL,
            generator_on INTEGER,
            solar_power REAL,
            solar_current REAL,
            fuel_level REAL,
            fuel_ratio REAL,
            grid_on INTEGER,
            raw TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (site_id, snap_time)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {META_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """,
    ]
    for stmt in ddl:
        conn.execute(stmt)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ipt_snap_site_time ON {SNAP_TABLE} (site_id, snap_time)")
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ipt_sites_name ON {SITES_TABLE} (name)")


def load_watch() -> List[str]:
    """读 watch_sites.json（数组；兼容 {"sites": [...]} 包装）。"""
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict):
            return [str(x) for x in data.get("sites", [])]
    except (OSError, ValueError):
        pass
    return []


def _resolve_watch(watch: List[str], sites: List[Dict[str, Any]]) -> List[str]:
    """把 watch 配置解析成 site_id 列表。支持 '*' / 站点名 / 参考号 / site_id。"""
    if "*" in watch:
        return [s["id"] for s in sites]
    by_name = {s["name"].casefold(): s["id"] for s in sites}
    by_ref = {str(s.get("internalReference")): s["id"] for s in sites}
    known = {s["id"] for s in sites}
    out: List[str] = []
    for key in watch:
        if key in known:
            out.append(key)
        elif key.casefold() in by_name:
            out.append(by_name[key.casefold()])
        elif key in by_ref:
            out.append(by_ref[key])
        else:
            logger.warning("[ipt_power] watch 项无法匹配任何站点：%s", key)
    return out


_SITE_COLS = ("site_id", "name", "internal_reference", "organization", "cluster",
              "priority", "configuration", "connectivity", "criticality",
              "lat", "lon", "connectivity_updated", "updated_at")


def _upsert_sites(conn, sites: List[Dict[str, Any]]) -> int:
    """站点清单刷新：新站全插；已有站只更新 filter-map 实际提供的字段
    （连接状态/criticality/坐标/更新时间），保留此前由单站查询（refresh 接口）
    补齐的 internal_reference / organization / cluster / priority / configuration
    ——filter-map 不带这些字段，每轮先删后插会把它们抹成 NULL。"""
    now = _now()
    for s in sites:
        sid = s.get("id")
        conn.execute(f"SELECT 1 FROM {SITES_TABLE} WHERE site_id = ?", (sid,))
        exists = conn.fetchone() is not None
        if exists:
            conn.execute(
                f"UPDATE {SITES_TABLE} SET name = ?, connectivity = ?, criticality = ?,"
                " lat = ?, lon = ?, connectivity_updated = ?, updated_at = ?"
                " WHERE site_id = ?",
                (s.get("name"), s.get("connectivity"), s.get("criticality"),
                 s.get("latitude"), s.get("longitude"),
                 s.get("connectivityUpdated"), now, sid))
        else:
            conn.execute(
                f"INSERT INTO {SITES_TABLE} ({', '.join(_SITE_COLS)})"
                f" VALUES ({', '.join('?' * len(_SITE_COLS))})",
                (sid, s.get("name"), s.get("internalReference"),
                 (s.get("flatOrganization") or {}).get("key"),
                 (s.get("cluster") or {}).get("name"),
                 (s.get("priority") or {}).get("name"),
                 (s.get("configuration") or {}).get("name"),
                 s.get("connectivity"), s.get("criticality"),
                 s.get("latitude"), s.get("longitude"),
                 s.get("connectivityUpdated"), now))
    return len(sites)


def _snapshot_row(site_id: str, diagram: Dict[str, Any], now: str):
    """diagram 原始 JSON → 快照行（多电池/油箱取第一组，raw 存完整 JSON 兜底）。"""
    def first(key):
        lst = diagram.get(key) or []
        return lst[0] if isinstance(lst, list) and lst else {}

    load = first("loads")
    batt = first("batterySets")
    gen = first("generators")
    solar = first("solarSets")
    tank = first("fuelTanks")
    grid = first("grids")
    env = diagram.get("environment") or {}

    def num(v):
        return v if isinstance(v, (int, float)) else None

    return (
        site_id, now, None,
        num(load.get("loadCurrent")), num(load.get("loadPower")),
        num(batt.get("batteryVoltage")), num(batt.get("batteryCurrent")),
        num(batt.get("batteryPower")), num(batt.get("batteryStateOfCharge")),
        batt.get("chargingState"), num(batt.get("batteryTemperature1")),
        None if gen.get("generatorOn") is None else int(bool(gen.get("generatorOn"))),
        num(solar.get("solarPower")), num(solar.get("solarCurrent")),
        num(tank.get("fuelLevel")), num(tank.get("fuelRatio")),
        None if grid.get("gridOn") is None else int(bool(grid.get("gridOn"))),
        json.dumps(diagram, ensure_ascii=False), now,
    )


_SNAP_COLS = ("site_id", "snap_time", "connectivity", "load_current", "load_power",
              "battery_voltage", "battery_current", "battery_power", "battery_soc",
              "battery_charging_state", "battery_temp1", "generator_on",
              "solar_power", "solar_current", "fuel_level", "fuel_ratio",
              "grid_on", "raw", "created_at")


def save_snapshot(conn, site_id: str, diagram: Dict[str, Any],
                  connectivity: str = None, snap_time: str = None) -> None:
    """快照落库（router 的「立即刷新」与采集任务共用）。"""
    row = _snapshot_row(site_id, diagram, snap_time or _now())
    if connectivity:
        row = (site_id, row[1], connectivity) + row[3:]
    conn.execute(
        f"DELETE FROM {SNAP_TABLE} WHERE site_id = ? AND snap_time = ?",
        (row[0], row[1]))
    conn.execute(
        f"INSERT INTO {SNAP_TABLE} ({', '.join(_SNAP_COLS)})"
        f" VALUES ({', '.join('?' * len(_SNAP_COLS))})", row)


def run_ipt_power_collect(watch: List[str] = None) -> Dict[str, Any]:
    """任务入口（task_runner loader 调用）。返回 summary dict。"""
    started = time.time()
    summary: Dict[str, Any] = {"success": False, "sites_updated": 0,
                               "snapshots": 0, "snap_failed": 0,
                               "watch_count": 0, "skipped": None}
    watch = load_watch() if watch is None else watch

    try:
        client = IptEnergyClient()
    except IptEnergyError as e:
        summary["skipped"] = str(e)
        logger.warning("[ipt_power] 跳过采集：%s", e)
        return summary

    try:
        sites = client.filter_map()
    except Exception as e:
        summary["skipped"] = "filter-map 失败：%s" % e
        logger.warning("[ipt_power] %s", summary["skipped"])
        return summary
    if not sites:
        summary["skipped"] = "filter-map 返回空"
        return summary

    conn = get_raw_connection()
    try:
        cur = conn.cursor()
        _ensure_tables(cur)
        summary["sites_updated"] = _upsert_sites(cur, sites)
        watch_ids = _resolve_watch(watch, sites)
        summary["watch_count"] = len(watch_ids)

        for i, sid in enumerate(watch_ids):
            try:
                diagram = client.get_site_diagram(sid)
                save_snapshot(cur, sid, diagram)
                summary["snapshots"] += 1
            except Exception as e:  # 单站失败不阻断本轮
                summary["snap_failed"] += 1
                logger.warning("[ipt_power] 站点 %s 采集失败：%s", sid, e)
            if SITE_REQUEST_INTERVAL and i < len(watch_ids) - 1:
                time.sleep(SITE_REQUEST_INTERVAL)

        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(f"DELETE FROM {SNAP_TABLE} WHERE snap_time < ?", (cutoff,))

        cur.execute(f"DELETE FROM {META_TABLE} WHERE key = 'last_run'")
        cur.execute(
            f"INSERT INTO {META_TABLE} (key, value) VALUES ('last_run', ?)",
            (json.dumps({
                "time": _now(), "success": True,
                "sites": summary["sites_updated"],
                "snapshots": summary["snapshots"],
                "snap_failed": summary["snap_failed"],
                "watch": summary["watch_count"],
                "duration_s": round(time.time() - started, 1),
            }, ensure_ascii=False),))
        conn.commit()
        summary["success"] = True
    finally:
        conn.close()

    summary["duration_s"] = round(time.time() - started, 1)
    logger.info("[ipt_power] 采集完成：%s", summary)
    return summary
