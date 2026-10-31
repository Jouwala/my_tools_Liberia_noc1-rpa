# -*- coding: utf-8 -*-
"""SOC 多维趋势看板本地库：data/soc_trend/soc_trend.sqlite3。

设计约定
--------
* 数仓 GBase 只读（VmaxGbaseClient 强制 SELECT/SHOW/DESC），本库是**唯一落盘点**；
* 行粒度 ``(day, hh, cat, dim, member)``，只存**原始计数器**，比率/速率一律读取侧现算 ——
  上游口径调整时不会出现两套数字（对齐 olib_soc_report「存原始值、算口径」的做法）；
* 写入方只有 soc_trend_sync（任务 47），读取方是 routers/soc_trend.py；
* 幂等：同一天重复同步先 DELETE 后 INSERT，重跑不产生重复行。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("soc_trend")

_ROOT = Path(__file__).resolve().parents[3]                              # my_app/
DATA_DIR = _ROOT / "data" / "soc_trend"
DB_PATH = DATA_DIR / "soc_trend.sqlite3"

# 原始计数器列（与 GBase ppb 字段的对应关系见 soc_trend_sync.COUNTER_SQL）
COUNTER_COLS = (
    "ul_bytes", "dl_bytes",
    "conn_att", "conn_ok",
    "rt_att_ul", "rt_bad_ul", "rt_att_dl", "rt_bad_dl",
    "dis_bad_ul", "dis_bad_dl",
    "loss_bad_ul", "loss_bad_dl",
    "rtt_att_ul", "rtt_sum_ul", "rtt_att_dl", "rtt_sum_dl",
    "vt_num", "vt_den",
)
_ALL_COLS = ("day", "hh", "cat", "dim", "member") + COUNTER_COLS + ("rows_n",)
_DAY_ALL_COLS = ("day", "cat", "dim", "member") + COUNTER_COLS + ("rows_n",)

_WRITE_LOCK = threading.Lock()                                           # sqlite 单写者


def db_path() -> Path:
    return DB_PATH


def connect(readonly: bool = False) -> sqlite3.Connection:
    """打开本地库（无则建目录建表）。只读方传 readonly=True 拿 URI 连接。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.as_posix(), uri=True,
                               timeout=15, check_same_thread=False)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.execute("pragma journal_mode=wal")
        conn.execute("pragma busy_timeout=15000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建表（幂等，首次落盘前调用一次即可）。"""
    counters = " REAL,\n    ".join(COUNTER_COLS) + " REAL"
    with _WRITE_LOCK:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS kpi_hour (
    day    TEXT NOT NULL,             -- 'YYYY-MM-DD'（数仓分区日，本地时区口径）
    hh     INTEGER NOT NULL,          -- 0~23
    cat    TEXT NOT NULL,             -- flow/video/web/game/ottvoice/ottvideo（tcp=flow 别名，control 不落行）
    dim    TEXT NOT NULL,             -- total / area / ne
    member TEXT NOT NULL,             -- total='all'；area=area_id；ne=targetid
    %(counters)s,
    rows_n INTEGER DEFAULT 0,
    PRIMARY KEY (day, hh, cat, dim, member)
);
CREATE INDEX IF NOT EXISTS idx_kpi_hour_day ON kpi_hour (day, dim, cat);

CREATE TABLE IF NOT EXISTS kpi_day (
    day    TEXT NOT NULL,
    cat    TEXT NOT NULL,
    dim    TEXT NOT NULL,
    member TEXT NOT NULL,
    %(counters)s,
    rows_n INTEGER DEFAULT 0,
    PRIMARY KEY (day, cat, dim, member)
);
CREATE INDEX IF NOT EXISTS idx_kpi_day_day ON kpi_day (day, dim, cat);

-- 区域成员（每日同步时从 dim_comm_area 刷新，行数极少）
CREATE TABLE IF NOT EXISTS dim_area (
    area_id   TEXT PRIMARY KEY,
    area_name TEXT,
    city_name TEXT,
    updated_at TEXT
);
-- 网元成员（targetid -> 名称；成员清单来自 olib_soc_report 实测映射，见 sync 模块）
CREATE TABLE IF NOT EXISTS dim_ne (
    targetid  TEXT PRIMARY KEY,
    ne_name   TEXT,
    updated_at TEXT
);
-- 业务 APP 小时明细（每类目每分区 Top-N，见 sync.TOP_APPS_PER_CAT；member='service:appid'）
CREATE TABLE IF NOT EXISTS kpi_app_hour (
    day    TEXT NOT NULL,
    hh     INTEGER NOT NULL,
    cat    TEXT NOT NULL,
    member TEXT NOT NULL,
    %(counters)s,
    rows_n INTEGER DEFAULT 0,
    PRIMARY KEY (day, hh, cat, member)
);
CREATE INDEX IF NOT EXISTS idx_kpi_app_hour_day ON kpi_app_hour (day, cat);
-- 业务 APP 字典（member -> APP 名；每次同步按 dim_service 刷新）
CREATE TABLE IF NOT EXISTS dim_app (
    member   TEXT PRIMARY KEY,
    cat      TEXT,
    app_name TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT, finished_at TEXT, status TEXT,
    hour_days INTEGER, day_days INTEGER, skipped_days INTEGER,
    error TEXT, seconds REAL
);
""" % {"counters": counters})
        conn.commit()


# ==========================================================================
# 写入（仅 soc_trend_sync 使用）
# ==========================================================================
def replace_day(conn: sqlite3.Connection, gran: str, day: str, rows: Sequence[Dict[str, Any]]) -> int:
    """整日替换（先删后插，幂等）。gran: 'hour' | 'day'。"""
    table = "kpi_hour" if gran == "hour" else "kpi_day"
    cols = _ALL_COLS if gran == "hour" else _DAY_ALL_COLS
    placeholders = ",".join("?" for _ in cols)
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), placeholders)
    tuples = [tuple(row.get(c) or 0 for c in cols) for row in rows]
    with _WRITE_LOCK:
        cur = conn.cursor()
        cur.execute("DELETE FROM %s WHERE day = ?" % table, (day,))
        cur.executemany(sql, tuples)
        conn.commit()
    return len(tuples)


def replace_dims(conn: sqlite3.Connection, areas: Sequence[Dict[str, Any]],
                 nes: Sequence[Dict[str, Any]]) -> None:
    """刷新区域/网元成员表（全量覆盖，两张表行数都只有个位数~两位数）。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _WRITE_LOCK:
        cur = conn.cursor()
        cur.execute("DELETE FROM dim_area")
        cur.executemany("INSERT INTO dim_area (area_id, area_name, city_name, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        [(str(r["area_id"]), r.get("area_name"), r.get("city_name"), now)
                         for r in areas])
        cur.execute("DELETE FROM dim_ne")
        cur.executemany("INSERT INTO dim_ne (targetid, ne_name, updated_at) VALUES (?, ?, ?)",
                        [(str(r["targetid"]), r.get("ne_name"), now) for r in nes])
        conn.commit()


def replace_app_day(conn: sqlite3.Connection, day: str, rows: Sequence[Dict[str, Any]]) -> int:
    """整日替换 APP 小时明细（幂等）。"""
    cols = ("day", "hh", "cat", "member") + COUNTER_COLS + ("rows_n",)
    placeholders = ",".join("?" for _ in cols)
    sql = "INSERT INTO kpi_app_hour (%s) VALUES (%s)" % (",".join(cols), placeholders)
    tuples = [tuple(row.get(c) or 0 for c in cols) for row in rows]
    with _WRITE_LOCK:
        cur = conn.cursor()
        cur.execute("DELETE FROM kpi_app_hour WHERE day = ?", (day,))
        cur.executemany(sql, tuples)
        conn.commit()
    return len(tuples)


def replace_app_dims(conn: sqlite3.Connection, apps: Sequence[Dict[str, Any]]) -> None:
    """刷新 APP 字典（INSERT OR REPLACE 增量累积；不删除历史成员，跨日 TopN 并集都能显示）。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _WRITE_LOCK:
        conn.executemany(
            "INSERT OR REPLACE INTO dim_app (member, cat, app_name, updated_at) VALUES (?,?,?,?)",
            [(str(r["member"]), r.get("cat"), r.get("app_name"), now) for r in apps])
        conn.commit()


def record_run(conn: sqlite3.Connection, run_id: str, started_at: str, finished_at: str,
               status: str, hour_days: int, day_days: int, skipped_days: int,
               error: str, seconds: float) -> None:
    with _WRITE_LOCK:
        conn.execute(
            "INSERT OR REPLACE INTO sync_runs "
            "(run_id, started_at, finished_at, status, hour_days, day_days, skipped_days, "
            " error, seconds) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, started_at, finished_at, status, hour_days, day_days, skipped_days,
             error, round(seconds, 2)))
        conn.commit()


# ==========================================================================
# 读取（routers / service 使用）
# ==========================================================================
def stored_days(conn: sqlite3.Connection, gran: str) -> List[str]:
    """本地已落盘的分区日（升序，'YYYY-MM-DD'）。"""
    table = "kpi_hour" if gran == "hour" else "kpi_day"
    rows = conn.execute("SELECT DISTINCT day FROM %s ORDER BY day" % table).fetchall()
    return [str(r[0]) for r in rows]


def fetch_rows(conn: sqlite3.Connection, gran: str, days: Sequence[str], cat: str,
               dim: str) -> List[Dict[str, Any]]:
    """取若干天 × 类目 × 维度的原始行（service 层再组装成序列/告警）。"""
    table = "kpi_hour" if gran == "hour" else "kpi_day"
    marks = ",".join("?" for _ in days)
    sql = ("SELECT * FROM %s WHERE day IN (%s) AND cat = ? AND dim = ? ORDER BY day, member"
           % (table, marks))
    return [dict(r) for r in conn.execute(sql, (*days, cat, dim)).fetchall()]


def area_names(conn: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    return {str(r["area_id"]): {"name": r["area_name"] or str(r["area_id"]),
                                "city": r["city_name"] or ""}
            for r in conn.execute("SELECT * FROM dim_area").fetchall()}


def ne_names(conn: sqlite3.Connection) -> Dict[str, str]:
    return {str(r["targetid"]): r["ne_name"] or str(r["targetid"])
            for r in conn.execute("SELECT * FROM dim_ne").fetchall()}


def app_names(conn: sqlite3.Connection) -> Dict[str, str]:
    return {str(r["member"]): r["app_name"] or str(r["member"])
            for r in conn.execute("SELECT * FROM dim_app").fetchall()}


def fetch_app_rows(conn: sqlite3.Connection, days: Sequence[str],
                   cat: str) -> List[Dict[str, Any]]:
    """取若干天 × 类目的 APP 小时明细（dim=app 序列用）。"""
    marks = ",".join("?" for _ in days)
    sql = ("SELECT * FROM kpi_app_hour WHERE day IN (%s) AND cat = ? ORDER BY day, hh"
           % marks)
    return [dict(r) for r in conn.execute(sql, (*days, cat)).fetchall()]


def last_run(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM sync_runs ORDER BY finished_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def window_end_hour(conn: sqlite3.Connection, day: str) -> int:
    """该日小时数据的最后完整小时（无数据返回 -1）。当天分区仍在累积，读它即可。"""
    row = conn.execute("SELECT MAX(hh) FROM kpi_hour WHERE day = ?", (day,)).fetchone()
    return int(row[0]) if row and row[0] is not None else -1


def day_has_data(conn: sqlite3.Connection, gran: str, day: str) -> bool:
    table = "kpi_hour" if gran == "hour" else "kpi_day"
    row = conn.execute("SELECT 1 FROM %s WHERE day = ? LIMIT 1" % table, (day,)).fetchone()
    return row is not None


def counters_sum(rows: Iterable[Dict[str, Any]], keys: Sequence[str]) -> Dict[str, float]:
    """把若干行的计数器列求和（缺失列按 0）。"""
    out = {k: 0.0 for k in keys}
    for row in rows:
        for k in keys:
            v = row.get(k)
            if v:
                out[k] += float(v)
    return out
