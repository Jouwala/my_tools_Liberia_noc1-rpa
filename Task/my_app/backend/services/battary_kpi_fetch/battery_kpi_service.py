# -*- coding: utf-8 -*-
"""
Battery KPI 服务：UME 电池实时数据抓取 → 解析 → 写入 battery_kpi.sqlite3

数据源
------
`battary_kpi_fetch_socket.py`（纯 socket + RSA 登录，无浏览器）的
`/api/monitor-manager/v1/realtime-data/get-by-condition` 分页接口，
MOC = r32.uedm.batt，测量点 batt.health / batt.prst.soc / batt.charge.discharge.status。

与独立脚本的区别
----------------
- **全程内存不落盘**：不调用 standard-point（550KB 元数据，列名可由记录键直接推导）、
  不触发 export、不写 JSON/Excel/CSV。每小时执行一次，落盘会累积 ~1.5MB/次。
- 直接消费原始记录（已是扁平 dict），不引入 pandas。

Position 层级（实测恒为 5 段）
-----------------------------
    <Category>/<Site>/PowerCabinet/NFB_BattPack/<MonitorObject>
    例：Satelite Sites/ERA005_Gbagbala/PowerCabinet/NFB_BattPack/NFB_Batt1
  → category = 段0（Satelite Sites / Microwave Sites / Pilot）
  → site     = 段1（站点名，208 个）

落库设计（data/battery/battery_kpi.sqlite3）
-------------------------------------------
- `battery_latest`  : 每块电池最新快照，PK=position（每次同步 upsert 覆盖）
- `battery_reading` : **设备级去重历史**，PK=(position, reading_time)。
                      reading_time 取设备自身上报时间而非轮询时间，因此长期不上报的
                      电池不会每小时产生重复行——1532 块电池里实际只有 ~700 块在更新。
- `battery_trend`   : 每次轮询一行的全网聚合（供趋势图），PK=snapshot_ts
- `battery_meta`    : 同步元信息（last_sync_ts / rows / duration 等）

新鲜度口径（重要）
------------------
实测 1532 块电池中约 48% 的读数已超过 7 天（最老 2024 年），若把过期读数混入均值，
「平均 SOC / 平均健康度」会失真。因此：
- last_update = 三个测量点 updateTime 的最大值
- fresh (新鲜)   : age <= FRESH_HOURS(24h)
- delayed(延迟)  : 24h < age <= STALE_DAYS(7d)
- stale (过期)   : age > 7d
- no_data        : 三个时间都缺失
**均值类指标一律只在 fresh 子集上计算**，计数类指标同时给出总量与 fresh 量。
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("battery_kpi_service")

# matplotlib 使用非交互后端（无 GUI 环境也能导出 PNG）
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# ========== 路径与阈值配置 ==========
BATT_DATA_DIR = Path(
    os.environ.get("BATT_DATA_DIR", r"d:\01_RPA\Task\my_app\data\battery")
)
BATT_DB_PATH = BATT_DATA_DIR / "battery_kpi.sqlite3"

# 新鲜度阈值
FRESH_HOURS = float(os.environ.get("BATT_FRESH_HOURS", "24"))
STALE_DAYS = float(os.environ.get("BATT_STALE_DAYS", "7"))

# 业务阈值
HEALTH_DEGRADED = float(os.environ.get("BATT_HEALTH_DEGRADED", "90"))   # 健康度劣化线
HEALTH_GOOD = float(os.environ.get("BATT_HEALTH_GOOD", "95"))           # 良好线
SOC_CRITICAL = float(os.environ.get("BATT_SOC_CRITICAL", "20"))         # 严重低电量
SOC_LOW = float(os.environ.get("BATT_SOC_LOW", "50"))                   # 低电量

# 保留策略
READING_RETENTION_DAYS = int(os.environ.get("BATT_READING_RETENTION_DAYS", "90"))
TREND_RETENTION_DAYS = int(os.environ.get("BATT_TREND_RETENTION_DAYS", "180"))

NULL_TOKENS = {"--", "", "-", "null", "none", "n/a", "na"}

# 与看板一致的默认阈值（battery_meta 缺失时回落）
DEFAULTS = {
    "fresh_hours": FRESH_HOURS,
    "stale_days": STALE_DAYS,
    "health_degraded": HEALTH_DEGRADED,
    "health_good": HEALTH_GOOD,
    "soc_critical": SOC_CRITICAL,
    "soc_low": SOC_LOW,
}


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------

def _clean(v) -> str | None:
    """UME 用 '--' 表示空值，统一转 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in NULL_TOKENS:
        return None
    return s


def _to_float(v) -> float | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_dt(v) -> datetime | None:
    s = _clean(v)
    if s is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _split_position(position: str) -> tuple[str, str]:
    """Position → (category, site)。实测恒为 5 段，容错处理短路径。"""
    parts = [p for p in str(position or "").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return "Unknown", parts[0]
    return "Unknown", "Unknown"


def parse_records(records: list[dict], now: datetime | None = None) -> list[dict]:
    """原始记录 → 规范化行（含 category/site/age_hours/freshness）。"""
    now = now or datetime.now()
    rows: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        position = str(rec.get("position") or "").strip()
        mo = str(rec.get("mo") or "").strip()
        if not position:
            position = mo
        if not position:
            continue
        category, site = _split_position(position)

        health = _to_float(rec.get("batt.health.value"))
        soc = _to_float(rec.get("batt.prst.soc.value"))
        status = _clean(rec.get("batt.charge.discharge.status.value")) or "Unknown"

        t_health = _to_dt(rec.get("batt.health.updateTime"))
        t_soc = _to_dt(rec.get("batt.prst.soc.updateTime"))
        t_status = _to_dt(rec.get("batt.charge.discharge.status.updateTime"))
        times = [t for t in (t_health, t_soc, t_status) if t is not None]
        last_update = max(times) if times else None

        if last_update is None:
            age_hours = None
            freshness = "no_data"
        else:
            age_hours = round((now - last_update).total_seconds() / 3600.0, 2)
            if age_hours <= FRESH_HOURS:
                freshness = "fresh"
            elif age_hours <= STALE_DAYS * 24:
                freshness = "delayed"
            else:
                freshness = "stale"

        rows.append({
            "position": position,
            "mo": mo,
            "site": site,
            "category": category,
            "health": health,
            "health_time": t_health.strftime("%Y-%m-%d %H:%M:%S") if t_health else None,
            "soc": soc,
            "soc_time": t_soc.strftime("%Y-%m-%d %H:%M:%S") if t_soc else None,
            "status": status,
            "status_time": t_status.strftime("%Y-%m-%d %H:%M:%S") if t_status else None,
            "last_update": last_update.strftime("%Y-%m-%d %H:%M:%S") if last_update else None,
            "age_hours": age_hours,
            "freshness": freshness,
        })
    return rows


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------

DDL = [
    """
    CREATE TABLE IF NOT EXISTS battery_latest (
        position     TEXT PRIMARY KEY,
        mo           TEXT,
        site         TEXT,
        category     TEXT,
        health       REAL,
        health_time  TEXT,
        soc          REAL,
        soc_time     TEXT,
        status       TEXT,
        status_time  TEXT,
        last_update  TEXT,
        age_hours    REAL,
        freshness    TEXT,
        snapshot_ts  TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_latest_site ON battery_latest(site)",
    "CREATE INDEX IF NOT EXISTS idx_latest_fresh ON battery_latest(freshness)",
    """
    CREATE TABLE IF NOT EXISTS battery_reading (
        position     TEXT NOT NULL,
        reading_time TEXT NOT NULL,
        site         TEXT,
        category     TEXT,
        health       REAL,
        soc          REAL,
        status       TEXT,
        PRIMARY KEY (position, reading_time)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reading_time ON battery_reading(reading_time)",
    """
    CREATE TABLE IF NOT EXISTS battery_trend (
        snapshot_ts       TEXT PRIMARY KEY,
        total             INTEGER,
        sites             INTEGER,
        fresh             INTEGER,
        delayed           INTEGER,
        stale             INTEGER,
        no_data           INTEGER,
        fresh_rate        REAL,
        avg_health        REAL,
        avg_soc           REAL,
        charging          INTEGER,
        discharging       INTEGER,
        unknown_status    INTEGER,
        low_soc           INTEGER,
        critical_soc      INTEGER,
        degraded          INTEGER,
        discharging_sites INTEGER,
        critical_sites    INTEGER
    )
    """,
    "CREATE TABLE IF NOT EXISTS battery_meta (key TEXT PRIMARY KEY, value TEXT)",
]


def _connect() -> sqlite3.Connection:
    """连接电池库。统一走 backend.database 的 _ClosingConnection（可 with）。"""
    BATT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from backend.database import get_raw_connection
        return get_raw_connection(str(BATT_DB_PATH), timeout=30)
    except Exception:  # 独立运行（无 backend 包）时的兜底
        conn = sqlite3.connect(str(BATT_DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


def init_db(conn: sqlite3.Connection) -> None:
    for stmt in DDL:
        conn.execute(stmt)


def compute_trend(rows: list[dict], snapshot_ts: str) -> dict:
    """全网聚合（均值类只统计 fresh 子集）。"""
    total = len(rows)
    sites = len({r["site"] for r in rows})
    fresh_rows = [r for r in rows if r["freshness"] == "fresh"]

    def _cnt(pred, source=None) -> int:
        return sum(1 for r in (source if source is not None else rows) if pred(r))

    healths = [r["health"] for r in fresh_rows if r["health"] is not None]
    socs = [r["soc"] for r in fresh_rows if r["soc"] is not None]

    discharging_rows = [r for r in fresh_rows if r["status"] == "Discharge"]
    critical_rows = [r for r in fresh_rows if r["soc"] is not None and r["soc"] < SOC_CRITICAL]

    return {
        "snapshot_ts": snapshot_ts,
        "total": total,
        "sites": sites,
        "fresh": len(fresh_rows),
        "delayed": _cnt(lambda r: r["freshness"] == "delayed"),
        "stale": _cnt(lambda r: r["freshness"] == "stale"),
        "no_data": _cnt(lambda r: r["freshness"] == "no_data"),
        "fresh_rate": round(len(fresh_rows) * 100.0 / total, 2) if total else 0.0,
        "avg_health": round(sum(healths) / len(healths), 2) if healths else None,
        "avg_soc": round(sum(socs) / len(socs), 2) if socs else None,
        "charging": _cnt(lambda r: r["status"] == "Charge", fresh_rows),
        "discharging": len(discharging_rows),
        "unknown_status": _cnt(lambda r: r["status"] not in ("Charge", "Discharge"), fresh_rows),
        "low_soc": _cnt(lambda r: r["soc"] is not None and r["soc"] < SOC_LOW, fresh_rows),
        "critical_soc": len(critical_rows),
        "degraded": _cnt(lambda r: r["health"] is not None and r["health"] < HEALTH_DEGRADED, fresh_rows),
        "discharging_sites": len({r["site"] for r in discharging_rows}),
        "critical_sites": len({r["site"] for r in critical_rows}),
    }


def save_rows(rows: list[dict], snapshot_ts: str) -> dict:
    """写 battery_latest（全量替换）+ battery_reading（设备级去重）+ battery_trend。"""
    trend = compute_trend(rows, snapshot_ts)
    with _connect() as conn:
        init_db(conn)

        # 1) latest：先清空再整表写入，避免 UME 侧删除的电池残留
        conn.execute("DELETE FROM battery_latest")
        conn.executemany(
            """INSERT INTO battery_latest
               (position, mo, site, category, health, health_time, soc, soc_time,
                status, status_time, last_update, age_hours, freshness, snapshot_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(r["position"], r["mo"], r["site"], r["category"], r["health"], r["health_time"],
              r["soc"], r["soc_time"], r["status"], r["status_time"], r["last_update"],
              r["age_hours"], r["freshness"], snapshot_ts) for r in rows],
        )

        # 2) reading：按设备上报时间去重累积（未更新的电池不会产生新行）
        hist = [(r["position"], r["last_update"], r["site"], r["category"],
                 r["health"], r["soc"], r["status"])
                for r in rows if r["last_update"]]
        before = conn.execute("SELECT COUNT(*) FROM battery_reading").fetchone()[0]
        conn.executemany(
            """INSERT OR IGNORE INTO battery_reading
               (position, reading_time, site, category, health, soc, status)
               VALUES (?,?,?,?,?,?,?)""",
            hist,
        )
        after = conn.execute("SELECT COUNT(*) FROM battery_reading").fetchone()[0]
        new_readings = after - before

        # 3) trend
        cols = list(trend.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO battery_trend ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            [trend[c] for c in cols],
        )

        # 4) 清理超期数据
        cut_reading = (datetime.now() - timedelta(days=READING_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM battery_reading WHERE reading_time < ?", (cut_reading,))
        cut_trend = (datetime.now() - timedelta(days=TREND_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM battery_trend WHERE snapshot_ts < ?", (cut_trend,))

        # 5) meta
        for k, v in (
            ("last_sync_ts", snapshot_ts),
            ("last_rows", str(len(rows))),
            ("last_sites", str(trend["sites"])),
            ("fresh_hours", str(FRESH_HOURS)),
            ("stale_days", str(STALE_DAYS)),
            ("health_degraded", str(HEALTH_DEGRADED)),
            ("soc_critical", str(SOC_CRITICAL)),
            ("soc_low", str(SOC_LOW)),
        ):
            conn.execute("INSERT OR REPLACE INTO battery_meta (key, value) VALUES (?,?)", (k, v))

    trend["new_readings"] = new_readings
    return trend


# ---------------------------------------------------------------------------
# 报表 / 输出 / 邮件
# ---------------------------------------------------------------------------

# output_socket 输出目录：每次同步/邮件只保留「最新一份」数据文件（见 cleanup_output_socket）
BATT_OUTPUT_DIR = Path(__file__).resolve().parent / "output_socket"
# 远程 FTP 收件人名单目录（内含 ss_email.txt 主送 / cc_email.txt 抄送）
BATT_EMAIL_REMOTE = "/01_RPA/LBR_Tools/KPI/Battary/battary_email"
# Excel 备份目录：Battery KPI Email 任务把生成的 Excel 复制到这里作为备份数据（目录不存在自动创建）
BATT_BACKUP_DIR = Path(os.environ.get("BATT_BACKUP_DIR", r"d:\01_RPA\LBR_Tools\KPI\Battary\data_bak"))

SEV_ORDER = {"Critical": 0, "Major": 1, "Minor": 2, "OK": 3}


def _avg(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _load_meta(conn: sqlite3.Connection) -> dict:
    """读取 battery_meta（阈值/同步时间），缺省回落 DEFAULTS。"""
    meta = {k: v for k, v in conn.execute("SELECT key, value FROM battery_meta").fetchall()}
    out = dict(DEFAULTS)
    for k in ("fresh_hours", "stale_days", "health_degraded", "health_good",
              "soc_critical", "soc_low"):
        if k in meta:
            try:
                out[k] = float(meta[k])
            except (TypeError, ValueError):
                pass
    out["last_sync_ts"] = meta.get("last_sync_ts")
    return out


def cleanup_output_socket(keep_xlsx: int = 1, keep_png: int = 1,
                          protect: list = None) -> int:
    """只保留 output_socket 中最新的一份数据文件，删除其余（含历史多次导出）。

    由于邮件同时需要 Excel + 内嵌 Dashboard PNG，因此按扩展名分别保留：
      - ``keep_xlsx=1``：保留最新的 1 份 Excel
      - ``keep_png=1``：保留最新的 1 份 PNG
    ``protect`` 中的路径（当前任务正在使用/即将发送的文件）无论新旧都强制保留，
    避免并发清理/重跑时把对方正在发送的 ``--excel`` 文件误删（曾导致
    owa_mail_report 报"文件不存在"）。点文件（. 开头，如锁文件）一律跳过。
    返回被删除的文件数。
    """
    d = BATT_OUTPUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    removed = 0
    keep_set: set[Path] = set()
    for p in (protect or []):
        try:
            p = Path(p)
            if p.exists():
                keep_set.add(p.resolve())
        except Exception:
            pass

    def _in_keep(f: Path) -> bool:
        return f.resolve() in keep_set or f.name.startswith(".")

    def _keep_pool(ext: str, n: int) -> None:
        nonlocal removed
        pool = [f for f in d.iterdir()
                if f.is_file() and not f.name.startswith(".")
                and f.suffix.lower() == ext]
        pool.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for f in pool[:n]:
            keep_set.add(f.resolve())
        for f in pool[n:]:
            if _in_keep(f):
                continue
            try:
                f.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"[Battery] 清理 output_socket 失败 {f}: {e}")

    _keep_pool(".xlsx", keep_xlsx)
    _keep_pool(".png", keep_png)
    # 其它扩展名（如备份文件）全部删掉（受保护文件 / 点文件除外）
    for f in d.iterdir():
        if f.is_file() and not _in_keep(f):
            try:
                f.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"[Battery] 清理 output_socket 失败 {f}: {e}")
    if removed:
        logger.info(f"[Battery] output_socket 已清理，删除 {removed} 个旧文件，保留最新 Excel/PNG")
    return removed


def _build_alarms(rows: list[dict], meta: dict) -> list[dict]:
    """告警规则（与看板一致）：每块电池可命中多条。

    Critical  严重低电量     : fresh 且 SOC < soc_critical(20)
    Critical  放电且电量不足  : fresh 且 Discharge 且 SOC < soc_low(50)
    Major     站点放电中      : fresh 且 Discharge（市电中断代理指标）
    Major     健康度劣化      : fresh 且 health < health_degraded(90)
    Major     数据长期未更新   : age > 30d
    Minor     数据过期        : stale_days(7d) < age <= 30d
    Minor     无数据上报      : 三个测量点均无时间戳
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


def build_battery_report() -> dict:
    """从 battery_latest 聚合出邮件/导出所需的全部数据（口径与看板一致）。"""
    if not BATT_DB_PATH.exists():
        return {"available": False, "message": "无电池数据（请先执行 battery_kpi_sync）",
                "meta": {}, "kpi": {}, "alarms": [], "batteries": [], "sites": []}
    with _connect() as conn:
        if not _table_exists(conn, "battery_latest"):
            return {"available": False, "message": "无电池数据（请先执行 battery_kpi_sync）",
                    "meta": {}, "kpi": {}, "alarms": [], "batteries": [], "sites": []}
        rows = [dict(r) for r in conn.execute("SELECT * FROM battery_latest").fetchall()]
        meta = _load_meta(conn)
    if not rows:
        return {"available": False, "message": "无电池数据（battery_latest 为空）",
                "meta": meta, "kpi": {}, "alarms": [], "batteries": [], "sites": []}

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
    alarms = _build_alarms(rows, meta)
    sites = _build_sites(rows, alarms, meta)
    return {"available": True, "meta": meta, "kpi": kpi, "alarms": alarms,
            "batteries": rows, "sites": sites}


def export_battery_excel(report: dict | None = None,
                         report_path: str | Path | None = None) -> Path:
    """将电池报表导出为 Excel 至 output_socket（带时间戳文件名），随后清理旧文件只留最新一份。

    返回生成的文件路径。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    report = report or build_battery_report()
    BATT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = (Path(report_path) if report_path
            else BATT_OUTPUT_DIR / f"battery_latest_{datetime.now():%Y%m%d_%H%M%S}.xlsx")

    wb = Workbook()
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="1F4E78")
    head_font = Font(bold=True, color="FFFFFF")

    # ---- 汇总 ----
    ws = wb.active
    ws.title = "汇总 Summary"
    ws.append(["指标 Metric", "值 Value"])
    for c in ws[1]:
        c.font = head_font
        c.fill = head_fill
    if report.get("available"):
        k = report["kpi"]
        m = report.get("meta", {})
        summary_rows = [
            ("同步时间 Last Sync", m.get("last_sync_ts")),
            ("电池总数 Total Batteries", k.get("total_batteries")),
            ("站点数 Sites", k.get("total_sites")),
            ("新鲜电池 Fresh", k.get("fresh")),
            ("新鲜率% Fresh Rate", k.get("fresh_rate")),
            ("平均健康度(新鲜) Avg Health", k.get("avg_health")),
            ("平均SOC(新鲜) Avg SOC", k.get("avg_soc")),
            ("放电中 Discharging", k.get("discharging")),
            ("放电站点 Discharging Sites", k.get("discharging_sites")),
            ("严重低电量 Critical SOC", k.get("critical_soc")),
            ("严重低电量站点 Critical Sites", k.get("critical_sites")),
            ("健康度劣化 Degraded", k.get("degraded")),
            ("过期/无数据 Stale", k.get("stale")),
            ("过期站点 Stale Sites", k.get("stale_sites")),
        ]
        for name, val in summary_rows:
            ws.append([name, val])
        # 阈值说明
        ws.append([])
        ws.append(["阈值 Thresholds", ""])
        ws.append(["新鲜小时 fresh_hours", m.get("fresh_hours")])
        ws.append(["过期天 stale_days", m.get("stale_days")])
        ws.append(["健康劣化线 health_degraded", m.get("health_degraded")])
        ws.append(["严重低电量线 soc_critical", m.get("soc_critical")])
        ws.append(["低电量线 soc_low", m.get("soc_low")])
    else:
        ws.append(["状态 Status", report.get("message", "无数据")])

    # ---- 电池明细 ----
    ws2 = wb.create_sheet("电池明细 Battery Detail")
    cols2 = ["site", "category", "position", "health", "soc", "status",
             "last_update", "age_hours", "freshness"]
    ws2.append(cols2)
    for c in ws2[1]:
        c.font = head_font
        c.fill = head_fill
    for r in report.get("batteries", []):
        ws2.append([r.get(c) for c in cols2])

    # ---- 告警 ----
    ws3 = wb.create_sheet("告警 Alarms")
    cols3 = ["severity", "type", "site", "category", "position",
             "soc", "health", "status", "last_update", "age_hours", "detail"]
    ws3.append(cols3)
    for c in ws3[1]:
        c.font = head_font
        c.fill = head_fill
    for a in report.get("alarms", []):
        ws3.append([a.get(c) for c in cols3])

    # 自动列宽
    for ws_ in (ws, ws2, ws3):
        for col in ws_.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws_.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)

    wb.save(path)
    # 只保留最新一份 Excel/PNG（按扩展名分别保留），并保护本次刚生成的文件
    cleanup_output_socket(protect=[path])
    return path


def export_battery_dashboard_image(report: dict | None = None,
                                     image_path: str | Path | None = None) -> Path:
    """生成 Battery Live Dashboard 快照 PNG（参考 UI 截图风格），供邮件正文内嵌展示。

    输出 1200x800 的暗色主题图片，包含：
      - 顶部 8 个 KPI 卡片
      - 中间 3 个甜甜圈图：SOC 分布 / 充放电状态 / 数据新鲜度
      - 底部：健康度分级柱状图 + 站点类别（电池数 + Fresh% + Avg SOC 折线）组合图
    返回生成的 PNG 路径。
    """
    report = report or build_battery_report()
    BATT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = (Path(image_path) if image_path
            else BATT_OUTPUT_DIR / f"battery_dashboard_{datetime.now():%Y%m%d_%H%M%S}.png")

    if not report.get("available"):
        fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0B1120")
        ax.text(0.5, 0.5, "No battery data available",
                color="#FFFFFF", fontsize=18, ha="center", va="center")
        ax.set_facecolor("none")
        ax.axis("off")
        fig.savefig(path, dpi=120, bbox_inches="tight", facecolor="#0B1120")
        plt.close(fig)
        return path

    kpi = report["kpi"]
    meta = report.get("meta", {})
    rows = report.get("batteries", [])
    fresh_rows = [r for r in rows if r["freshness"] == "fresh"]

    # ---------- 计算各图表数据 ----------
    # SOC 分布（ fresh 子集 ）
    soc_buckets = [0, 0, 0, 0, 0]
    soc_labels = ["<20%", "20-50%", "50-80%", "80-100%", "N/A"]
    soc_colors = ["#F5222D", "#FAAD14", "#52C41A", "#52C41A", "#8C8C8C"]
    for r in fresh_rows:
        s = r["soc"]
        if s is None:
            soc_buckets[4] += 1
        elif s < 20:
            soc_buckets[0] += 1
        elif s < 50:
            soc_buckets[1] += 1
        elif s < 80:
            soc_buckets[2] += 1
        else:
            soc_buckets[3] += 1

    # 充放电状态（ fresh 子集 ）
    status_map: dict[str, int] = {}
    for r in fresh_rows:
        status_map[r["status"]] = status_map.get(r["status"], 0) + 1
    # 确保顺序
    status_labels = ["Charge", "Discharge", "Unknown"]
    status_values = [status_map.get(s, 0) for s in status_labels]
    status_colors = ["#52C41A", "#FA8C16", "#8C8C8C"]

    # 数据新鲜度（ 全部 ）
    fresh_all = {"fresh": 0, "delayed": 0, "stale": 0, "no_data": 0}
    for r in rows:
        fresh_all[r["freshness"]] = fresh_all.get(r["freshness"], 0) + 1
    fresh_labels = ["Fresh", "Delayed", "Stale", "No Data"]
    fresh_values = [fresh_all.get(k.lower().replace(" ", "_"), 0) for k in fresh_labels]
    fresh_colors = ["#52C41A", "#FAAD14", "#F5222D", "#8C8C8C"]

    # 健康度分级（ fresh 子集 ）
    h_deg = meta.get("health_degraded", HEALTH_DEGRADED)
    h_good = meta.get("health_good", HEALTH_GOOD)
    health_buckets = {
        f"< {h_deg:.0f}%\nDegraded": 0,
        f"{h_deg:.0f}-{h_good:.0f}%": 0,
        f"≥ {h_good:.0f}%\nGood": 0,
        "No Data": 0,
    }
    for r in fresh_rows:
        h = r["health"]
        if h is None:
            health_buckets["No Data"] += 1
        elif h < h_deg:
            health_buckets[f"< {h_deg:.0f}%\nDegraded"] += 1
        elif h < h_good:
            health_buckets[f"{h_deg:.0f}-{h_good:.0f}%"] += 1
        else:
            health_buckets[f"≥ {h_good:.0f}%\nGood"] += 1
    h_labels = list(health_buckets.keys())
    h_values = list(health_buckets.values())
    h_colors = ["#F5222D", "#FAAD14", "#52C41A", "#8C8C8C"]

    # 站点类别（ 全部电池 + fresh 子集 ）
    cat_rows: dict[str, list[dict]] = {}
    for r in rows:
        cat_rows.setdefault(r["category"], []).append(r)
    cat_names = list(cat_rows.keys())
    cat_bat = [len(v) for v in cat_rows.values()]
    cat_fresh_rate = []
    cat_avg_soc = []
    for cat, items in cat_rows.items():
        fresh_items = [r for r in items if r["freshness"] == "fresh"]
        socs = [r["soc"] for r in fresh_items if r["soc"] is not None]
        cat_fresh_rate.append(round(len(fresh_items) * 100.0 / len(items), 1) if items else 0.0)
        cat_avg_soc.append(round(sum(socs) / len(socs), 1) if socs else 0.0)

    # ---------- 绘图 ----------
    fig = plt.figure(figsize=(12, 8.25), facecolor="#0B1120")
    fig.suptitle("Battery Live Dashboard", color="#FFFFFF", fontsize=20, fontweight="bold", y=0.98)

    # 暗色主画布
    gs = fig.add_gridspec(3, 1, left=0.03, right=0.97, top=0.93, bottom=0.04,
                           hspace=0.35, height_ratios=[0.22, 0.39, 0.39])

    # ---- 顶部 KPI 卡片 ----
    kpi_spec = [
        (kpi.get("total_batteries"), "Batteries", "#00B8D9"),
        (kpi.get("total_sites"), "Sites covered", "#6554C0"),
        (f"{kpi.get('fresh_rate', 0)}%", "Fresh rate", "#36B37E"),
        (kpi.get("avg_soc"), "Avg SOC (fresh)", "#FFAB00"),
        (kpi.get("avg_health"), "Avg Health (fresh)", "#00B8D9"),
        (kpi.get("discharging"), "Discharging", "#FF5630"),
        (kpi.get("critical_soc"), "Critical SOC", "#FF5630"),
        (kpi.get("stale"), "No/Stale data", "#97A0AF"),
    ]

    gs_top = gs[0].subgridspec(1, 8, wspace=0.15)
    for i, (val, label, color) in enumerate(kpi_spec):
        ax = fig.add_subplot(gs_top[0, i])
        ax.set_facecolor("#151D2F")
        for spine in ax.spines.values():
            spine.set_color("#2C3A56")
            spine.set_linewidth(1)
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        # 顶部色条
        rect = Rectangle((0, 1.02), 1, 0.06, transform=ax.transAxes,
                          facecolor=color, edgecolor="none")
        ax.add_patch(rect)
        ax.text(0.5, 0.62, str(val), color="#FFFFFF", fontsize=18,
                ha="center", va="center", fontweight="bold")
        ax.text(0.5, 0.28, label, color="#97A0AF", fontsize=8,
                ha="center", va="center", wrap=True)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    # ---- 中间三个甜甜圈 ----
    gs_mid = gs[1].subgridspec(1, 3, wspace=0.18)

    def _donut(ax, values, labels, colors, title, center_text=""):
        ax.set_facecolor("#151D2F")
        non_zero = [v if v else 0 for v in values]
        if sum(non_zero) == 0:
            non_zero = [1]
            plot_labels = ["No data"]
            plot_colors = ["#8C8C8C"]
        else:
            plot_labels = [f"{l}\n{v}" for l, v in zip(labels, values) if v]
            plot_colors = [c for c, v in zip(colors, values) if v]
            non_zero = [v for v in values if v]
        wedges, _ = ax.pie(
            non_zero,
            labels=None,
            colors=plot_colors,
            startangle=90,
            wedgeprops=dict(width=0.45, edgecolor="#151D2F", linewidth=2),
        )
        # 图例在底部
        ax.legend(wedges, plot_labels, loc="lower center", bbox_to_anchor=(0.5, -0.18),
                  ncol=len(plot_labels), frameon=False, fontsize=8,
                  labelcolor="#FFFFFF", facecolor="none")
        ax.text(0, 0, center_text, color="#FFFFFF", ha="center", va="center",
                fontsize=12, fontweight="bold")
        ax.set_title(title, color="#FFFFFF", fontsize=12, fontweight="bold", pad=10)

    ax1 = fig.add_subplot(gs_mid[0, 0])
    _donut(ax1, soc_buckets, soc_labels, soc_colors, "SOC Distribution",
           f"{kpi.get('fresh', 0)} fresh")

    ax2 = fig.add_subplot(gs_mid[0, 1])
    _donut(ax2, status_values, status_labels, status_colors, "Charge/Discharge Status",
           f"{kpi.get('discharging', 0)} dischg")

    ax3 = fig.add_subplot(gs_mid[0, 2])
    _donut(ax3, fresh_values, fresh_labels, fresh_colors, "Data Freshness",
           f"{kpi.get('total_batteries', 0)} total")

    # ---- 底部：健康度 + 站点类别 ----
    gs_bot = gs[2].subgridspec(1, 2, wspace=0.18)

    # 健康度分级
    ax4 = fig.add_subplot(gs_bot[0, 0])
    ax4.set_facecolor("#151D2F")
    bars = ax4.bar(range(len(h_labels)), h_values, color=h_colors, edgecolor="#151D2F", linewidth=1)
    ax4.set_xticks(range(len(h_labels)))
    ax4.set_xticklabels(h_labels, color="#97A0AF", fontsize=8)
    ax4.tick_params(axis="y", colors="#97A0AF", labelsize=8)
    ax4.set_title("Health Distribution", color="#FFFFFF", fontsize=12, fontweight="bold", pad=10)
    for spine in ax4.spines.values():
        spine.set_color("#2C3A56")
    ax4.spines["top"].set_visible(False)
    ax4.spines["right"].set_visible(False)
    # 数值标签
    for bar, val in zip(bars, h_values):
        if val:
            ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(h_values)*0.02,
                     str(val), color="#FFFFFF", ha="center", va="bottom", fontsize=8)
    # 底部注释
    ax4.text(0.5, -0.18, f"Health clips at {h_good:.0f}-{100:.0f}%; variance is mostly in no-data share",
             transform=ax4.transAxes, color="#97A0AF", fontsize=7, ha="center")

    # 站点类别：柱 + 双线
    ax5 = fig.add_subplot(gs_bot[0, 1])
    ax5.set_facecolor("#151D2F")
    x = range(len(cat_names))
    bars = ax5.bar(x, cat_bat, color="#6554C0", alpha=0.7, label="Batteries")
    ax5.set_xticks(x)
    ax5.set_xticklabels(cat_names, color="#97A0AF", fontsize=8)
    ax5.tick_params(axis="y", colors="#97A0AF", labelsize=8)
    ax5.set_ylabel("Batteries", color="#97A0AF", fontsize=9)
    for spine in ax5.spines.values():
        spine.set_color("#2C3A56")
    ax5.spines["top"].set_visible(False)

    ax5_twin = ax5.twinx()
    ax5_twin.set_facecolor("none")
    ax5_twin.plot(x, cat_fresh_rate, color="#52C41A", marker="o", label="Fresh %")
    ax5_twin.plot(x, cat_avg_soc, color="#00B8D9", marker="s", label="Avg SOC")
    ax5_twin.tick_params(axis="y", colors="#97A0AF", labelsize=8)
    ax5_twin.set_ylabel("% / SOC", color="#97A0AF", fontsize=9)
    ax5_twin.set_ylim(0, 100)
    ax5_twin.spines["top"].set_visible(False)

    ax5.set_title("By Site Category", color="#FFFFFF", fontsize=12, fontweight="bold", pad=10)
    # 合并图例
    lines1, labels1 = ax5.get_legend_handles_labels()
    lines2, labels2 = ax5_twin.get_legend_handles_labels()
    ax5.legend(lines1 + lines2, labels1 + labels2, loc="upper right",
               frameon=False, fontsize=8, labelcolor="#FFFFFF", facecolor="none")

    fig.savefig(path, dpi=120, bbox_inches="tight", facecolor="#0B1120")
    plt.close(fig)
    logger.info(f"[Battery] Dashboard 图片已生成: {path}")
    return path


# ---------------------------------------------------------------------------
# Excel 备份（Battery KPI Email 任务附加步骤）
# ---------------------------------------------------------------------------

def backup_battery_excel(src: str | Path) -> Path | None:
    """把生成的电池 Excel 复制到备份目录（data_bak）作为备份数据。

    - 目录不存在则自动创建（parents=True）。
    - 复制失败仅记录警告并返回 None，**不影响邮件发送**。
    - 源文件名已带时间戳，备份目录会天然保留每次运行的独立副本。
    返回备份文件路径；失败/源缺失时返回 None。
    """
    src = Path(src)
    if not src.exists():
        logger.warning(f"[Battery] 备份跳过：源文件不存在 {src}")
        return None
    try:
        BATT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = BATT_BACKUP_DIR / src.name
        shutil.copy2(src, dst)
        logger.info(f"[Battery] Excel 已备份至: {dst}")
        return dst
    except Exception as e:
        logger.warning(f"[Battery] Excel 备份失败 {src} -> {BATT_BACKUP_DIR}: {e}")
        return None


# ---------------------------------------------------------------------------
# 跨进程互斥锁（避免同一时刻两个 run_battery_email 并发清理互相删掉对方正在发送的 --excel）
# ---------------------------------------------------------------------------
try:
    import msvcrt  # Windows 专用文件锁；非 Windows 环境降级为不加锁
except ImportError:  # pragma: no cover
    msvcrt = None


@contextlib.contextmanager
def _battery_email_lock(timeout: float = 90.0):
    """跨进程互斥锁：确保同一时刻仅一个邮件发送任务在执行。

    获取超时则退化为不加锁执行（避免任务卡死）。锁文件存放在 output_socket，
    但 cleanup_output_socket 会跳过点文件（. 开头），不会被误删。
    """
    lock_file = BATT_OUTPUT_DIR / ".email_send.lock"
    acquired = False
    f = None
    try:
        BATT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        f = open(lock_file, "w+")
        if msvcrt is None:
            acquired = True
        else:
            deadline = time.time() + timeout
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.time() > deadline:
                        break
                    time.sleep(0.5)
        yield acquired
    finally:
        if f is not None:
            try:
                if acquired and msvcrt is not None:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            try:
                f.close()
            except OSError:
                pass


def run_battery_email(to: str | None = None, cc: str | None = None) -> dict:
    """Task Manager 入口：生成最新电池报表 + Dashboard 图片 → 读取远程 FTP 收件人 → 通过 OWA 发送邮件。

    邮件正文内嵌 Battery Live Dashboard 快照 PNG，附件为 Excel 明细。
    每日 07:00 / 19:00 触发（cron ``0 7,19 * * *``）。
    内部在跨进程互斥锁内执行，避免并发重跑互相清理掉对方正在发送的附件。
    """
    with _battery_email_lock():
        return _run_battery_email_impl(to, cc)


def _run_battery_email_impl(to: str | None = None, cc: str | None = None) -> dict:
    """run_battery_email 的内部实现（已在互斥锁内执行）。"""
    started = time.time()
    try:
        from backend.services import kpi_email_report as ker
    except ImportError:  # 独立运行
        import kpi_email_report as ker  # type: ignore

    # 1) 重新生成最新报表 + 图片（邮件内容始终基于最近一次同步结果）
    report = build_battery_report()
    if not report.get("available"):
        return {"success": False, "error": report.get("message", "无电池数据")}

    try:
        excel_path = export_battery_excel(report=report)
    except Exception as e:
        return {"success": False, "error": f"导出 Excel 失败: {e}"}

    # 1.5) 备份 Excel 到 data_bak（失败仅警告，不影响邮件发送）
    backup_dst = backup_battery_excel(excel_path)

    try:
        img_path = export_battery_dashboard_image(report=report)
    except Exception as e:
        logger.warning(f"[Battery] Dashboard 图片生成失败，继续发送 Excel: {e}")
        img_path = None

    # 2) 收件人（远程 FTP 名单；to/cc 显式传入时优先，用于测试）
    try:
        to_arg, cc_arg = ker._resolve_recipients_remote(BATT_EMAIL_REMOTE, to, cc)
    except Exception as e:
        return {"success": False, "error": f"读取收件人名单失败: {e}"}
    if not to_arg:
        return {"success": False,
                "error": f"收件人为空（{BATT_EMAIL_REMOTE} 缺少 ss_email.txt 或为空）"}

    # 3) 发送（owa_mail_report.py via EWS，含瞬时错误重试）
    res = ker._run_script(
        data_dir=BATT_OUTPUT_DIR,
        name_filter="battery",
        to=to_arg,
        cc=cc_arg,
        excel=excel_path,
        images=[img_path] if img_path else None,
        subject_prefix="Battery KPI Report",
    )
    # 发送完成后再清理旧文件，并强制保护本次生成的文件，
    # 避免并发/重跑清理把正在使用的 --excel 文件误删（曾导致 owa 报"文件不存在"）
    cleanup_output_socket(
        protect=[excel_path, img_path] if img_path else [excel_path]
    )
    res["elapsed_sec"] = round(time.time() - started, 2)
    res["report"] = str(excel_path)
    res["backup"] = str(backup_dst) if backup_dst else None
    res["recipients_to"] = to_arg
    logger.info(f"[Battery] 邮件发送结果: {res}")
    return res


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

def fetch_battery_records() -> list[dict]:
    """登录 UME 并分页拉取全部电池实时数据（内存返回，不落盘）。"""
    try:
        from . import battary_kpi_fetch_socket as fetcher
    except ImportError:  # 独立运行
        import battary_kpi_fetch_socket as fetcher  # type: ignore

    credentials = fetcher.load_credentials(None)
    # fetcher 内部通过模块级 _HOST/_PORT 建连，必须显式注入
    fetcher._HOST = credentials["host"]
    fetcher._PORT = credentials["port"]
    logger.info(f"[Battery] 登录 UME {credentials['host']}:{credentials['port']} "
                f"user={credentials['username']}")

    auth = fetcher.login_rsa(credentials)
    if auth is None:
        logger.warning("[Battery] RSA 登录失败，尝试回退 auth_info.json")
        auth = fetcher.load_auth_info_fallback()
        if auth is None:
            raise RuntimeError(
                "Battery UME 鉴权失败：RSA 登录未成功且无可用 auth_info.json"
            )
    if not auth.get("host"):
        auth["host"] = credentials["host"]
        auth["port"] = credentials["port"]
        fetcher._HOST = auth["host"]
        fetcher._PORT = auth["port"]

    _first_page, records = fetcher.fetch_all_realtime(auth)
    logger.info(f"[Battery] 拉取完成，记录数={len(records)}")
    return records


# ---------------------------------------------------------------------------
# 任务入口
# ---------------------------------------------------------------------------

def run_battery_kpi_sync() -> dict:
    """Task Manager 入口：抓取电池实时 KPI → 解析 → 写 battery_kpi.sqlite3。

    返回摘要（写入 task_execution_log，不含明细以免日志膨胀）。
    """
    started = time.time()
    now = datetime.now()
    snapshot_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    records = fetch_battery_records()
    if not records:
        raise RuntimeError("Battery UME 未返回任何记录")

    rows = parse_records(records, now=now)
    trend = save_rows(rows, snapshot_ts)

    # 同步后立即导出最新报表到 output_socket（只保留最新一份，详见 cleanup_output_socket）
    try:
        rp = export_battery_excel()
        logger.info(f"[Battery] 已导出最新报表: {rp}")
    except Exception as e:
        logger.warning(f"[Battery] 导出 Excel 失败（不影响入库）: {e}")
        rp = None

    elapsed = round(time.time() - started, 2)
    summary = {
        "success": True,
        "snapshot_ts": snapshot_ts,
        "batteries": trend["total"],
        "sites": trend["sites"],
        "fresh": trend["fresh"],
        "fresh_rate": trend["fresh_rate"],
        "stale": trend["stale"],
        "avg_soc_fresh": trend["avg_soc"],
        "avg_health_fresh": trend["avg_health"],
        "discharging": trend["discharging"],
        "discharging_sites": trend["discharging_sites"],
        "critical_soc": trend["critical_soc"],
        "degraded": trend["degraded"],
        "new_readings": trend["new_readings"],
        "db": str(BATT_DB_PATH),
        "report": str(rp) if rp else None,
        "elapsed_sec": elapsed,
    }
    logger.info(f"[Battery] 同步完成: {summary}")
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    import json as _json
    print(_json.dumps(run_battery_kpi_sync(), ensure_ascii=False, indent=2))
