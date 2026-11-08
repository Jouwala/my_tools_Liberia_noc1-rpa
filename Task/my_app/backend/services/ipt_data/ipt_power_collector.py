# -*- coding: utf-8 -*-
"""IPT 站点电源信息采集服务（定时 5 分钟，task_id=ipt_power_collect）。

数据源：IPT Digital Platform（RMS 能源监控平台，AWS 外网）
  - `POST /energy/sites/filter-map`：1 个请求拉全站（~500 站）清单与连接状态
    → ipt_power_sites（⚠ 只有 id/name/坐标/连接状态/criticality，不含电源数值）
  - `GET  /energy/sites/<id>/popup`：**KPI 层**（~1.5KB）——负载功率/电池电压/SOC/
    太阳能/油位/油机开关 + 站点级活动告警（Mains Fail、Engine standby 等）
  - `GET  /energy/sites/<id>/diagram`：**明细层**（~5KB）——完整电源全景
    （负载电流/电池组名与容量/油机 R-S-T 相电压相电流/运行模式/市电整流器/
    油箱容量/太阳能组件/环境），popup 不含这些字段
  - `GET  /energy/sites?query=&page=&pageSize=100`：分页列全站完整属性（回填站点表）

全站 5 分钟分辨率（2026-11-04 重设计 / 2026-11-06 降频，实测依据）：
  上游没有任何批量电源接口（filter-map 无数值、events/recent 只有最近事件），
  唯一路径是逐站请求。实测并发 32 线程：
    - popup：501 站 60.1s、0 错误 → **每轮全采**，全站每 5 分钟一条 KPI 快照；
    - diagram：200 站 73.8s、外推 501 站 ~185s 且出现超时 → 即使 240s 硬上限
      放得下，也会挤占全站 popup 的时间并放大上游压力，
      **保持环形游标分片轮采**（单轮 ≤60 站、16 线程 ~15s），约 20 分钟覆盖全站，
      明细（油机相电压/电池容量等）以「最新一条 diagram」为准，
      页面「立即刷新」可随时对单站实时拉 diagram 补齐。

采集范围由同目录 watch_sites.json 控制：
  - `sites`：关注站，每轮必采 diagram（保持完整明细的 5 分钟分辨率）；
    **不要配 `"*"`**（旧语义 = 单轮全采 500 站 diagram，必然超时）。
  - `full_kpi`：`{"enabled": true, "workers": 8, "budget_s": 200}` —— 全站 popup
    KPI 层（关闭则退回只有分片轮采的旧行为）。
  - `full_shard`：`{"enabled": true, "max_sites": 60, "budget_s": 70}` —— diagram
    明细分片轮采；站点按 site_id 排序，ipt_power_meta.shard_cursor 环形游标。

存储：主库（sqlite/pg 双模由 backend.database.DB_MODE 决定）：
  - ipt_power_sites        站点清单 + 连接状态（每轮全量刷新，属性由 /sites 分页回填）
  - ipt_power_snapshots    电源快照（**全站 5 分钟一条**；popup 行只填 KPI 列、
                           raw 为 NULL 控表体积，diagram 行补全明细列并写 raw）
  - ipt_power_site_detail  每站最新一条 diagram 精简明细（JSON，已剥除设备凭据，
                           2026-11-04 前 raw 存全量 diagram 且被 /site/{id} 原样下发，
                           其中 fuelTanks[].device 带控制器明文口令，属凭据泄漏，已修复）
  - ipt_power_meta         采集运行状态 + shard_cursor

时间列统一「YYYY-MM-DD HH:MM:SS」本地字符串，规避 PG 下 ISO 带 T 的字符串比较失效问题。
"""
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.database import get_raw_connection
from backend.services.ipt_data.ipt_energy_client import IptEnergyClient, IptEnergyError

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
WATCH_FILE = os.path.join(_HERE, "watch_sites.json")

SITES_TABLE = "ipt_power_sites"
SNAP_TABLE = "ipt_power_snapshots"
DETAIL_TABLE = "ipt_power_site_detail"
META_TABLE = "ipt_power_meta"
RETENTION_DAYS = 7           # 快照保留期（超出即删）。2026-11-03 原定 2 天控表体积，
                             # 2026-11-08 如意要求改 7 天：页面时间窗本就有 168h(7d) 档、
                             # 接口 hours 上限 192h，2 天保留期让 72h/7d 两档永远只能看到
                             # 2 天曲线。当天实测 513 站 × 288 轮/天，2 天 = 33.7 万行 /
                             # 555MB（含索引），线性外推 7 天约 103 万行 / 1.9GB；
                             # popup 行 raw=NULL 仍是控体积的关键（当前仅 4.5 万行有 raw）。

# ---- 全站 popup KPI 层（2026-11-04：全站 5 分钟分辨率，2026-11-06 降频）----
KPI_DEFAULT_WORKERS = 8      # 2026-11-05 复盘：12+8=20 并发把上游拖垮（顺序探测
                             # 空闲期 0.9~4.3s，采集期批量 12s 超时、0~40/501），
                             # 降为 popup 8 + diagram 3 = 11 并发上限
KPI_DEFAULT_BUDGET_S = 200.0  # 兼容字段：_drain 统一用 hard_deadline，本值当前
                              # 不参与运行逻辑；与 watch_sites.json 保持口径一致
KPI_ROUND_HARD_DEADLINE_S = 240.0  # 整轮硬上限（任务入口起算，含 filter-map/回填/明细层）。
# 2026-11-06 D：cron 由 */2 改 */5 后空出 200s，但 2 分钟时代定的 100s 上限
# 没跟着调，改后 10 轮里 7 轮仍撞截断、尾部 30~170 站被砍（21:27=333/501、
# 21:46=327/501）。放至 240s 留 60s 给落库与下一轮；_drain 跑完即止不会白等，
# 也不增加任何瞬时 rps。max_instances=1 保证轮次不重叠，
# STALE_RUNNING_SECONDS=1800s 不会把 240s 的长轮误判成僵尸。
POOL_REQ_TIMEOUT_S = 20.0   # 池内单请求超时。2026-11-05 顺序探测曾出现 17s 仍成功，
                            # 12s 会把「慢但会成功」的请求误杀；且客户端提前放弃后
                            # 服务端仍在算，连接越堆越慢，形成超时风暴 → 放宽到 20s
POOL_REQ_INTERVAL_S = 0.3   # 每工作线程两次请求之间的间隔（降低瞬时 rps，
                            # 8 线程 × 0.3s ≈ 瞬时 <5rps，减轻上游压力）
KPI_CURSOR_KEY = "kpi_cursor"   # popup 环形游标：硬上限截断时下轮从断点续采
DEGRADED_RATIO = 0.25       # 一轮 popup 成功率低于此值视为「上游被压垮/故障」
BACKOFF_META_KEY = "failure_backoff"
BACKOFF_BASE_S = 300.0      # 首次失败退避 5 分钟（5 分钟节拍下约跳 1 轮）
BACKOFF_MAX_S = 1800.0      # 指数退避封顶 30 分钟
# 2026-11-06 B：上游瞬时抖动 != 任务失败。只有连续 N 轮「连上轮站点清单都
# 拿不到、整轮完全无法采集」才判失败并告警；前 N-1 轮记 success + skipped，
# 数据陈旧由 db_freshness_check 的「IPT 站点电源快照」20 分钟巡检兜底。
UPSTREAM_FAIL_ALERT_STREAK = 3

# ---- diagram 明细分片轮采 ----
SHARD_REQUEST_INTERVAL = 0.0     # 并发拉取，不再逐站 sleep
SHARD_DEFAULT_MAX_SITES = 60     # 单轮分片站数上限（16 线程实测 ~15s）
SHARD_DEFAULT_BUDGET_S = 70.0    # 分片时间预算（秒）
SHARD_WORKERS = 3                # diagram 分片并发（2026-11-05 与 popup 8 合计 11 并发；
                                 # 63 站 × ~2s / 3 线程 ≈ 42s，仍在 240s 硬上限内）
SHARD_CURSOR_KEY = "shard_cursor"             # ipt_power_meta 中的环形游标
META_BACKFILL_KEY = "site_meta_backfill_at"   # 站点属性回填时间戳
META_BACKFILL_COOLDOWN_S = 3600               # 回填冷却（防每轮重复拉 6 页）
SITE_META_PAGE_SIZE = 100                     # /sites 服务端 pageSize 上限实测 100
SITE_META_MAX_PAGES = 8                       # 8 页 = 800 站上限，足够覆盖 ~500 站


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# popup KPI 行也有的列（diagram 行全部覆盖）
_SNAP_EXTRA_COLS = {
    "source": "TEXT DEFAULT 'diagram'",        # popup | diagram（本轮 popup+diagram 合成也记 diagram）
    "alarm_count": "INTEGER",                  # 活动告警数（popup site.events / diagram events）
    "alarm_names": "TEXT",                     # JSON [{name, criticality, created?, category?}]
    "solar_available": "INTEGER",              # 1=有太阳能设备（0 也可能是夜间 0W）0=无（显示 -）
    "fuel_capacity": "REAL",                   # 油箱容量 L（明细层才有）
    "main_source_on": "INTEGER",               # 整流器主源开关（AC Off 判定，明细层才有）
}
_SNAP_EXTRA_NAMES = tuple(_SNAP_EXTRA_COLS)


def _existing_columns(cur, table: str) -> set:
    """跨 sqlite/pg 查表已有哪些列（列名小写）。

    注意 cur 可能是 sqlite3.Connection（execute 返回游标）或 PG 包装
    （execute 直接返回带 fetchall 的游标包装），统一用 execute(...).fetchall()。
    """
    from backend.database import DB_MODE
    if DB_MODE == "pg":
        rows = cur.execute("SELECT column_name FROM information_schema.columns"
                           " WHERE table_name = ?", (table,)).fetchall()
        return {str(r[0]).lower() for r in rows}
    rows = cur.execute("PRAGMA table_info(%s)" % table).fetchall()
    return {str(r[1]).lower() for r in rows}


def _ensure_columns(cur, table: str, defs: Dict[str, str]) -> None:
    """增量加列（sqlite/pg 双模）：只加缺失列，不动已有结构。"""
    have = _existing_columns(cur, table)
    for name, typ in defs.items():
        if name not in have:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def _ensure_tables(conn) -> None:
    """惰性建表 + 索引 + 增量加列（sqlite / pg 双模，范式同 routers/feedback.py；
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
        CREATE TABLE IF NOT EXISTS {DETAIL_TABLE} (
            site_id TEXT PRIMARY KEY,
            detail TEXT,
            updated_at TEXT NOT NULL
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
    _ensure_columns(conn, SNAP_TABLE, _SNAP_EXTRA_COLS)
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


def _load_section(name: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """读 watch_sites.json 的一个对象段（不存在/关闭时返回 enabled=False 的默认值）。"""
    off = dict(defaults)
    off["enabled"] = False
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return off
        cfg = data.get(name) or {}
        if not isinstance(cfg, dict) or not cfg.get("enabled"):
            return off
        out = dict(defaults)
        out["enabled"] = True
        for k in defaults:
            if k == "enabled":
                continue
            v = cfg.get(k, defaults[k])
            if isinstance(defaults[k], float):
                out[k] = max(5.0, float(v))
            elif isinstance(defaults[k], int) and not isinstance(defaults[k], bool):
                out[k] = max(1, int(v))
        return out
    except (OSError, ValueError, TypeError):
        return off


def load_kpi_config() -> Dict[str, Any]:
    """读 watch_sites.json 的 full_kpi 段（全站 popup KPI 层）。"""
    return _load_section("full_kpi", {"enabled": True, "workers": KPI_DEFAULT_WORKERS,
                                      "budget_s": KPI_DEFAULT_BUDGET_S})


def load_shard_config() -> Dict[str, Any]:
    """读 watch_sites.json 的 full_shard 段（diagram 明细分片轮采）。

    单独读文件而不复用 load_watch()，是为了让旧版 worker 看到的仍是纯数组语义：
    新增字段只对升级后的代码生效，配置文件可以先落盘、后重启，不存在中间态风险。
    """
    return _load_section("full_shard", {"enabled": True, "max_sites": SHARD_DEFAULT_MAX_SITES,
                                        "budget_s": SHARD_DEFAULT_BUDGET_S})


def _meta_get(cur, key: str):
    cur.execute(f"SELECT value FROM {META_TABLE} WHERE key = ?", (key,))
    r = cur.fetchone()
    return r[0] if r else None


def _meta_set(cur, key: str, value: str) -> None:
    cur.execute(f"DELETE FROM {META_TABLE} WHERE key = ?", (key,))
    cur.execute(f"INSERT INTO {META_TABLE} (key, value) VALUES (?, ?)",
                (key, str(value)))


def _load_sites_from_db(cur) -> List[Dict[str, Any]]:
    """filter-map 失败时的降级清单：用上一轮 ipt_power_sites 继续采集。

    只提供采集必需的 id / name / 连接状态 / reference，**不写回站点表**
    （旧清单的 connectivity 不能冒充本轮刷新结果）。2026-11-06 C：一次外网
    抖动不再让整轮 ~500 站快照全部作废。
    """
    cur.execute(f"SELECT site_id, name, connectivity, internal_reference"
                f" FROM {SITES_TABLE}")
    rows = cur.fetchall() or []
    return [{"id": r[0], "name": r[1], "connectivity": r[2],
             "internalReference": r[3]} for r in rows if r[0]]


def _backfill_site_meta(cur, client) -> int:
    """补齐 filter-map 不提供的站点属性（参考号/区域/集群/优先级/配置）。

    filter-map 每轮 UPDATE 不会动这几列；只有首次 INSERT 才写，而它拿到的同样是
    filter-map 对象 → 501 站这几列长期全为 NULL（页面显示 '-'、按参考号搜不到）。
    这里用 GET /sites 分页（约 6 个请求）一次性回填；仅在有缺值且距上次回填 >1h 时执行。
    失败只记日志，不阻断电源采集。
    """
    cur.execute(f"SELECT COUNT(*) FROM {SITES_TABLE} WHERE internal_reference IS NULL")
    r = cur.fetchone()
    if not r or not r[0]:
        return 0
    last = _meta_get(cur, META_BACKFILL_KEY)
    try:
        last_ts = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") if last else None
    except (TypeError, ValueError):
        last_ts = None
    if last_ts and (datetime.now() - last_ts).total_seconds() < META_BACKFILL_COOLDOWN_S:
        return 0

    touched = 0
    try:
        for page in range(1, SITE_META_MAX_PAGES + 1):
            batch = client.list_sites(page=page, page_size=SITE_META_PAGE_SIZE)
            if not batch:
                break
            for s in batch:
                sid = s.get("id")
                if not sid:
                    continue
                ref = s.get("internalReference")
                cur.execute(
                    f"UPDATE {SITES_TABLE} SET internal_reference = ?, organization = ?,"
                    " cluster = ?, priority = ?, configuration = ? WHERE site_id = ?",
                    (None if ref is None else str(ref),
                     (s.get("flatOrganization") or {}).get("key"),
                     (s.get("cluster") or {}).get("name"),
                     (s.get("priority") or {}).get("name"),
                     (s.get("configuration") or {}).get("name"), sid))
                touched += 1
            if len(batch) < SITE_META_PAGE_SIZE:
                break
    except Exception as e:  # 回填是增强项，失败不影响主链路
        logger.warning("[ipt_power] 站点属性回填失败（不影响电源采集）：%s", e)
    _meta_set(cur, META_BACKFILL_KEY, _now())
    logger.info("[ipt_power] 站点属性回填：处理 %d 行", touched)
    return touched


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


_SNAP_COLS = ("site_id", "snap_time", "connectivity", "load_current", "load_power",
              "battery_voltage", "battery_current", "battery_power", "battery_soc",
              "battery_charging_state", "battery_temp1", "generator_on",
              "solar_power", "solar_current", "fuel_level", "fuel_ratio",
              "grid_on", "raw", "created_at") + _SNAP_EXTRA_NAMES


def _merge_alarms(popup_kpi: dict = None, diag_kpi: dict = None):
    """popup 站点级告警 + diagram 设备级 events 合并去重（按 name）。"""
    merged, seen = [], set()
    for src in (popup_kpi or {}).get("alarm_names") or [], (diag_kpi or {}).get("alarm_names") or []:
        for a in src:
            name = a.get("name")
            if name and name not in seen:
                seen.add(name)
                merged.append(a)
    return merged


def _write_snapshot(cur, site_id: str, snap_time: str, connectivity,
                    popup_kpi: dict = None, diag_kpi: dict = None,
                    diag_raw=None) -> None:
    """一轮一条快照：popup KPI 为底、diagram 明细字段覆盖（都有时 source=diagram）。

    popup 行 raw 写 NULL（KPI 列已含全部数值，raw 留空控制 7 天保留期内的表体积：
    513 站 × 288 轮/天，raw 全存会让表体积涨一个量级）；diagram 行 raw 存 slim 明细 JSON。
    """
    base = dict(popup_kpi or {})
    if diag_kpi:
        for k, v in diag_kpi.items():
            if v is not None:
                base[k] = v
        base["source"] = "diagram"
        base["alarm_names"] = _merge_alarms(popup_kpi, diag_kpi)
        base["alarm_count"] = len(base["alarm_names"])
    if not base:
        return
    vals = {
        "site_id": site_id, "snap_time": snap_time, "connectivity": connectivity,
        "load_current": base.get("load_current"), "load_power": base.get("load_power"),
        "battery_voltage": base.get("battery_voltage"),
        "battery_current": base.get("battery_current"),
        "battery_power": base.get("battery_power"), "battery_soc": base.get("battery_soc"),
        "battery_charging_state": base.get("battery_charging_state"),
        "battery_temp1": base.get("battery_temp1"), "generator_on": base.get("generator_on"),
        "solar_power": base.get("solar_power"), "solar_current": base.get("solar_current"),
        "fuel_level": base.get("fuel_level"), "fuel_ratio": base.get("fuel_ratio"),
        "grid_on": base.get("grid_on"),
        "raw": (json.dumps(diag_raw, ensure_ascii=False)
                if diag_raw is not None else None),
        "created_at": _now(),
        "source": base.get("source") or "popup",
        "alarm_count": base.get("alarm_count"),
        "alarm_names": (json.dumps(base.get("alarm_names") or [], ensure_ascii=False)
                        if base.get("alarm_names") is not None else None),
        "solar_available": base.get("solar_available"),
        "fuel_capacity": base.get("fuel_capacity"),
        "main_source_on": base.get("main_source_on"),
    }
    row = tuple(vals[c] for c in _SNAP_COLS)
    cur.execute(
        f"DELETE FROM {SNAP_TABLE} WHERE site_id = ? AND snap_time = ?",
        (site_id, snap_time))
    cur.execute(
        f"INSERT INTO {SNAP_TABLE} ({', '.join(_SNAP_COLS)})"
        f" VALUES ({', '.join('?' * len(_SNAP_COLS))})", row)


def save_snapshot(conn, site_id: str, diagram: Dict[str, Any],
                  connectivity: str = None, snap_time: str = None) -> None:
    """diagram 快照落库（router 的「立即刷新」与采集任务共用）。

    同时写快照行（source=diagram）与 ipt_power_site_detail 最新明细；
    raw 只存剥除设备凭据后的 slim JSON（修复 2026-11-04 前的凭据泄漏）。
    """
    diag_kpi = IptEnergyClient.normalize_diagram_full(diagram)
    slim = IptEnergyClient.slim_diagram(diagram)
    _write_snapshot(cur=conn, site_id=site_id, snap_time=snap_time or _now(),
                    connectivity=connectivity, diag_kpi=diag_kpi, diag_raw=slim)
    upsert_site_detail(conn, site_id, slim)


def upsert_site_detail(cur, site_id: str, slim: Dict[str, Any]) -> None:
    """维护每站最新一条 diagram 精简明细（页面详情卡/弹窗数据源）。"""
    cur.execute(f"DELETE FROM {DETAIL_TABLE} WHERE site_id = ?", (site_id,))
    cur.execute(
        f"INSERT INTO {DETAIL_TABLE} (site_id, detail, updated_at) VALUES (?, ?, ?)",
        (site_id, json.dumps(slim, ensure_ascii=False), _now()))


def _make_pool(client: "IptEnergyClient", jobs, workers: int):
    """创建并发采集线程池并提交全部任务，返回 (executor, futures)。

    requests.Session 非线程安全 → 每线程 fork 一个独立 Session 的客户端，
    token 全部复用主客户端，避免并发 OIDC 重登。
    jobs: [(key, fn)]，key 任意可哈希（site_id 或 (kind, site_id)），
    fn(cl) 为实际请求。单站异常在收割时记为失败，不在工作线程里抛出。
    线程池客户端统一用 POOL_REQ_TIMEOUT_S 短超时（卡顿站点快速失败，
    由重试/下一轮兜底），主客户端仍是 25s 长超时（filter-map/回填等单发请求）。
    """
    jobs = list(jobs)
    workers = max(1, min(workers, len(jobs))) if jobs else 1
    pool = [client.fork_for_thread(timeout=POOL_REQ_TIMEOUT_S) for _ in range(workers)]

    def work(i_job):
        i, (key, fn) = i_job
        cl = pool[i % workers]
        if POOL_REQ_INTERVAL_S > 0:
            time.sleep(POOL_REQ_INTERVAL_S)  # 同线程请求间留间隔，削瞬时峰值
        try:
            return key, fn(cl), None
        except Exception as e:  # noqa: BLE001 单站失败不阻断本轮
            return key, None, str(e)

    ex = ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(work, (i, j)) for i, j in enumerate(jobs)]
    return ex, futs


def _drain(ex, futs, total: int, label: str, deadline: float = None):
    """按 deadline 收割线程池结果 → (out: {key: result}, failed: [(key, err)])。

    到时未完成的站点直接放弃（cancel_futures），保证整轮不超
    KPI_ROUND_HARD_DEADLINE_S（240s）预算；
    被放弃的请求线程最多再跑一个 HTTP 超时就自然结束。
    """
    out: Dict[Any, Any] = {}
    failed = []
    timeout = (max(5.0, deadline - time.time()) if deadline else None)
    try:
        it = as_completed(futs, timeout=timeout)
        while True:
            try:
                f = next(it)
            except StopIteration:
                break
            except TimeoutError:
                logger.warning("[ipt_power] %s：预算/硬上限到时，放弃剩余 %d 项",
                               label, total - len(out) - len(failed))
                break
            key, res, err = f.result()
            if err is not None:
                failed.append((key, err))
                continue
            out[key] = res
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if failed:
        logger.warning("[ipt_power] %s：成功 %d / 失败 %d（首个失败：%s %s）",
                       label, len(out), len(failed), failed[0][0], failed[0][1][:120])
    return out, failed


def _popup_fn(site_id: str):
    """popup 请求闭包工厂（避免循环变量晚绑定）。"""
    return lambda cl: cl.get_site_popup(site_id)


def _backoff_load(cur):
    raw = _meta_get(cur, BACKOFF_META_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _backoff_record_failure(cur, err: str) -> Dict[str, Any]:
    """上游失败指数退避：连续失败 1/2/3... 次 → 退避 5/10/20... 分钟（封顶 30）。

    目的：上游平台故障（如 2026-11-04 21:36 filter-map 连续 HTTP 500）时，
    不再按 5 分钟节拍持续敲打故障中的上游、也不再每轮发失败通知。
    """
    b = _backoff_load(cur) or {}
    streak = int(b.get("streak", 0)) + 1
    wait = min(BACKOFF_BASE_S * (2 ** (streak - 1)), BACKOFF_MAX_S)
    until = time.time() + wait
    state = {"streak": streak, "until": until, "wait_s": wait,
             "last_error": err[:200], "time": _now()}
    _meta_set(cur, BACKOFF_META_KEY, json.dumps(state, ensure_ascii=False))
    logger.warning("[ipt_power] 上游失败退避 %.0fs（连续第 %d 次）：%s",
                   wait, streak, err[:120])
    return state


def _backoff_clear(cur) -> None:
    _meta_set(cur, BACKOFF_META_KEY, json.dumps(
        {"streak": 0, "until": 0, "time": _now()}))


def _diag_fn(site_id: str):
    """diagram 请求闭包工厂（避免循环变量晚绑定）。"""
    return lambda cl: cl.get_site_diagram(site_id)


def run_ipt_power_collect(watch: List[str] = None) -> Dict[str, Any]:
    """任务入口（task_runner loader 调用）。返回 summary dict。

    本轮采集顺序：⓪ 熔断退避检查（上游连续失败→指数退避静默跳过）→
    ① filter-map 刷全站状态 → ② 按需回填站点属性 →
    ③ full_kpi：并发拉全站 popup（~501 站 60s，失败有界补采一轮）→
    ④ full_shard：环形游标并发拉 diagram 明细（≤60 站 ~15s，关注站每轮必采）
    → ⑤ 合成快照落库（全站每轮一条，全站 5 分钟分辨率）→
    ⑥ 清理过期快照 + 写 last_run / shard_cursor。
    """
    started = time.time()
    summary: Dict[str, Any] = {"success": False, "sites_updated": 0,
                               "snapshots": 0, "snap_failed": 0,
                               "kpi_ok": 0, "kpi_failed": 0,
                               "detail_ok": 0, "detail_failed": 0,
                               "watch_count": 0, "meta_backfilled": 0,
                               "shard": None, "skipped": None,
                               "stale_sites": 0, "upstream_unavailable": False}
    watch = load_watch() if watch is None else watch
    kpi_cfg = load_kpi_config()
    shard_cfg = load_shard_config()
    hard_deadline = started + KPI_ROUND_HARD_DEADLINE_S

    # ⓪ 熔断退避：上游故障时按指数退避静默跳过整轮（success=True，
    #    不触发失败通知）。
    #
    #    ⚠ 2026-11-06 更正：这里原先写「页面新鲜度告警（>5 分钟）自然覆盖此状态」
    #    —— 但那条告警**从来不存在**：前端只认 success=false，全仓没有任何代码
    #    读 `last_snapshot`，i18n 里也没有相关文案，巡检也没覆盖快照表。
    #    也就是说「上游故障 → 静默跳过 → 页面数字停在几小时前」全程无信号，
    #    实测近 5 天有 8 段 >10 分钟的快照缺口（最长 24.1 分钟）。
    #    现在的真实覆盖来自巡检：db_freshness_check 的 APP_DB_CHECKS 里有一项
    #    「IPT 站点电源快照」（ipt_power_snapshots.created_at，窗口 20 分钟），
    #    退避期间它会按表陈旧报出来 —— 所以这里的静默跳过不再是盲区。
    #    改本段逻辑时不要动那条巡检项，两者是一套。
    conn = get_raw_connection()
    try:
        cur = conn.cursor()
        _ensure_tables(cur)
        backoff = _backoff_load(cur) or {}
        now_ts = time.time()
        if now_ts < float(backoff.get("until", 0) or 0):
            summary["success"] = True
            summary["skipped"] = "上游退避中，剩余 %.0fs（连续失败 %d 次后，上次错误：%s）" % (
                float(backoff["until"]) - now_ts, backoff.get("streak", 0),
                (backoff.get("last_error") or "")[:80])
            logger.info("[ipt_power] %s", summary["skipped"])
            return summary

        try:
            client = IptEnergyClient()
        except IptEnergyError as e:
            # 凭据缺失是本地配置错误，不是上游抖动，必须立即告警（不抑制）。
            _backoff_record_failure(cur, "登录: %s" % e)
            conn.commit()
            summary["skipped"] = str(e)
            logger.warning("[ipt_power] 跳过采集：%s", e)
            return summary

        # ① filter-map 单点（client 层已含 1 次短重试）：仍失败 → 用上轮站点
        #    清单降级继续采，不再整轮 return（2026-11-06 B+C）。
        sites: List[Dict[str, Any]] = []
        try:
            sites = client.filter_map() or []
        except Exception as e:
            logger.warning("[ipt_power] filter-map 失败，改用上轮站点清单继续采集：%s", e)
        stale_sites = False
        if not sites:
            sites = _load_sites_from_db(cur)
            if sites:
                stale_sites = True
                logger.warning("[ipt_power] 降级清单 %d 站，本轮跳过站点表刷新", len(sites))
        if not sites:
            # 连上轮清单都没有（首次部署 / 表被清），才是真正无法采集。
            # 前 N-1 次静默（success=True + skipped），第 N 次起才判失败告警。
            state = _backoff_record_failure(cur, "filter-map 与降级清单均不可用")
            conn.commit()
            streak = int(state.get("streak", 1))
            summary["upstream_unavailable"] = True
            summary["skipped"] = ("上游不可用且无历史站点清单（连续第 %d 次；"
                                  "数据陈旧由 20 分钟巡检兜底）" % streak)
            summary["success"] = streak < UPSTREAM_FAIL_ALERT_STREAK
            logger.warning("[ipt_power] %s", summary["skipped"])
            return summary

        if stale_sites:
            summary["stale_sites"] = len(sites)
        else:
            summary["sites_updated"] = _upsert_sites(cur, sites)
            # 上游抖动时不再打 6 页 /sites 属性回填，避免额外加压。
            summary["meta_backfilled"] = _backfill_site_meta(cur, client)
        priority_ids = _resolve_watch(watch, sites)
        priority_set = set(priority_ids)
        all_ids = sorted(s["id"] for s in sites if s.get("id"))
        connectivity_map = {s.get("id"): s.get("connectivity") for s in sites}
        snap_time = _now()   # 整轮统一快照时间：全站每轮恰好一条

        # ① diagram 明细计划：关注站每轮必采 + 环形游标分片轮采其余站点
        detail_ids: List[str] = list(priority_ids)
        shard_info = None
        if shard_cfg["enabled"] and all_ids:
            n = len(all_ids)
            try:
                cursor = int(_meta_get(cur, SHARD_CURSOR_KEY) or 0) % n
            except (TypeError, ValueError):
                cursor = 0
            rotated = all_ids[cursor:] + all_ids[:cursor]
            consumed = 0
            for sid in rotated:
                if consumed >= shard_cfg["max_sites"]:
                    break
                consumed += 1          # 关注站本轮已采，跳过但仍推进游标
                if sid in priority_set:
                    continue
                detail_ids.append(sid)
            next_cursor = (cursor + consumed) % n
            _meta_set(cur, SHARD_CURSOR_KEY, next_cursor)
            shard_info = {
                "cursor": cursor, "next_cursor": next_cursor,
                "consumed": consumed, "total": n,
                "rounds_full_cycle": math.ceil(n / max(1, consumed)),
                "detail_requested": len(detail_ids),
            }

        # ② diagram 池**先起、后台跑**（与 popup 同时进行，避免明细分层被
        #    popup 预算挤掉——2026-11-04 首轮实测 popup 占满 82s 导致分片被跳过）
        diag_by_id: Dict[str, Any] = {}
        diag_futs = []
        diag_ex = None
        if detail_ids:
            diag_jobs = [(("diag", sid), _diag_fn(sid)) for sid in detail_ids]
            diag_ex, diag_futs = _make_pool(client, diag_jobs, SHARD_WORKERS)

        # ③ popup 池前台跑（并发 8）。任务按 kpi_cursor **环形轮转**：硬上限
        #    到时只完成列表前一段，若每轮都从 sorted(all_ids) 的开头重来，
        #    列表尾部的站会永远拿不到新快照（2026-11-05 实测 1 小时内 62 站
        #    无任何快照）；下轮从断点续采，保证全站最终都能轮到。
        popup_by_id: Dict[str, Any] = {}
        if kpi_cfg["enabled"] and all_ids:
            t0 = time.time()
            n_ids = len(all_ids)
            try:
                kpi_cursor = int(_meta_get(cur, KPI_CURSOR_KEY) or 0) % n_ids
            except (TypeError, ValueError):
                kpi_cursor = 0
            rotated_ids = all_ids[kpi_cursor:] + all_ids[:kpi_cursor]
            popup_jobs = [(sid, _popup_fn(sid)) for sid in rotated_ids]
            pex, pfuts = _make_pool(client, popup_jobs, kpi_cfg["workers"])
            popup_out, popup_fail = _drain(pex, pfuts, len(popup_jobs),
                                           "全站 popup KPI", deadline=hard_deadline)
            popup_by_id = dict(popup_out)
            logger.info("[ipt_power] 全站 popup：%d/%d 站，%.1fs（游标 %d）",
                        len(popup_out), len(all_ids), time.time() - t0, kpi_cursor)

            # ③b popup 失败补采（仅一轮、受同一硬上限约束）：晚高峰上游
            #    持续并发下偶发读超时，短超时快速失败后在此兜底一次。
            if popup_fail and time.time() < hard_deadline:
                retry_jobs = [(sid, _popup_fn(sid)) for sid, _err in popup_fail]
                rex, rfuts = _make_pool(client, retry_jobs, kpi_cfg["workers"])
                retry_out, _retry_fail = _drain(rex, rfuts, len(retry_jobs),
                                                "popup 补采", deadline=hard_deadline)
                popup_by_id.update(retry_out)
                if retry_out:
                    logger.info("[ipt_power] popup 补采：+%d/%d 站",
                                len(retry_out), len(retry_jobs))
            summary["kpi_ok"] = len(popup_by_id)
            summary["kpi_failed"] = len(all_ids) - len(popup_by_id)
            _meta_set(cur, KPI_CURSOR_KEY, (kpi_cursor + len(popup_by_id)) % n_ids)

        # ④ 收割 diagram 池（与 popup 并行完成，受同一硬上限约束）
        if detail_ids:
            t0 = time.time()
            diag_out, diag_fail = _drain(diag_ex, diag_futs, len(detail_ids),
                                         "diagram 明细", deadline=hard_deadline)
            # _drain 的 key 是 ("diag", site_id)（与 popup 池区分），拆包回 site_id
            diag_by_id = {key[1]: res for key, res in diag_out.items()}
            summary["detail_ok"] = len(diag_by_id)
            summary["detail_failed"] = len(detail_ids) - len(diag_by_id)
            logger.info("[ipt_power] diagram 明细：%d/%d 站，%.1fs",
                        len(diag_by_id), len(detail_ids), time.time() - t0)
        if shard_info is not None:
            shard_info["stop_reason"] = ("ok" if summary["detail_failed"] == 0
                                         else ("hard_deadline" if time.time() >= hard_deadline
                                               else "partial"))
            shard_info["round_elapsed_s"] = round(time.time() - started, 1)
            summary["shard"] = shard_info
            logger.info("[ipt_power] 分片轮采：%s", shard_info)

        # ③ 合成落库：全站每轮一条（popup KPI 为底，有 diagram 的站覆盖明细字段）
        for sid in all_ids:
            popup = popup_by_id.get(sid)
            diag = diag_by_id.get(sid)
            if popup is None and diag is None:
                summary["snap_failed"] += 1
                continue
            popup_kpi = IptEnergyClient.normalize_popup(popup) if popup else None
            diag_kpi = IptEnergyClient.normalize_diagram_full(diag) if diag else None
            slim = IptEnergyClient.slim_diagram(diag) if diag else None
            _write_snapshot(cur, sid, snap_time, connectivity_map.get(sid),
                            popup_kpi=popup_kpi, diag_kpi=diag_kpi, diag_raw=slim)
            if slim is not None:
                upsert_site_detail(cur, sid, slim)
            summary["snapshots"] += 1
        summary["watch_count"] = len(priority_ids) + (shard_info or {}).get("consumed", 0)

        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(f"DELETE FROM {SNAP_TABLE} WHERE snap_time < ?", (cutoff,))

        # ⑤ 低成功率熔断：filter-map 成功但 popup 几乎全超时（2026-11-05
        #    09:49~09:55 连续 4 轮 0/216/40/7）说明上游已被拖垮，此时继续
        #    每 5 分钟打满 240s 只会雪上加霜且拿不到数据 → 计入退避，
        #    让上游喘息 5/10/20 分钟（指数，封顶 30），成功即自动清零。
        degraded = bool(all_ids and kpi_cfg["enabled"] and
                        summary["kpi_ok"] < DEGRADED_RATIO * len(all_ids))
        summary["degraded"] = degraded
        _meta_set(cur, "last_run", json.dumps({
            "time": _now(), "success": True,
            "sites": summary["sites_updated"],
            "snapshots": summary["snapshots"],
            "snap_failed": summary["snap_failed"],
            "kpi_ok": summary["kpi_ok"], "kpi_failed": summary["kpi_failed"],
            "detail_ok": summary["detail_ok"], "detail_failed": summary["detail_failed"],
            "watch": summary["watch_count"], "degraded": degraded,
            "meta_backfilled": summary["meta_backfilled"],
            "stale_sites": summary["stale_sites"],
            "shard": summary["shard"],
            "duration_s": round(time.time() - started, 1),
        }, ensure_ascii=False))
        if degraded:
            _backoff_record_failure(cur, "popup 成功率仅 %d/%d（<%.0f%%）" % (
                summary["kpi_ok"], len(all_ids), DEGRADED_RATIO * 100))
        else:
            _backoff_clear(cur)
        conn.commit()
        summary["success"] = True
    finally:
        conn.close()

    summary["duration_s"] = round(time.time() - started, 1)
    logger.info("[ipt_power] 采集完成：%s", summary)
    return summary
