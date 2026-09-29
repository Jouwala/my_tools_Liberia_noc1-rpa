# -*- coding: utf-8 -*-
"""BP Report —— 物化库读写层。

=========================== 为什么是独立 sqlite3 而不是主库 ===========================

沿用 `ran_cells_kpi.sqlite3` / `avail_recon.sqlite3` 的既有**派生库**模式：

- 本表是**从上游重算出来的**，不是任何业务系统的原生表；放进主库 `db/app.db`
  就要背 alembic 迁移 + SQLite/PG 双方言负担（`db/app.db` 本身是 PG 的每小时镜像，
  见 docs/manual/03-data-layer.md:52），而它只被一个页面读。
- 回滚成本：删文件即回滚，不需要 `alembic downgrade`。
- 导入是**一次性**的（Excel 历史），更新是**每日增量**的，两者写同一批表、
  用同一套 UPSERT，天然幂等。

=========================== 表结构 ===========================

    bp_cell_dict      (cell_name)              小区 → Cluster/Layer 字典（一次性导入）
    bp_cell_daily     (day, cell_name)         逐小区逐日明细（Excel + RAN_UME 重算）
    bp_overall_daily  (day)                    全网日汇总
    bp_region_daily   (day, region)            分区日汇总
    bp_layer_daily    (day, layer)             分层日汇总
    bp_overall_week   (week)                   全网周汇总（含 bp_days/total_days）
    bp_overall_month  (month)                  全网月汇总（含 bp_weeks/total_weeks）
    bp_sync_meta      (key)                    同步状态、口径快照、对账差异

`source` 列（`excel` / `ume` / `both`）区分每条明细来自哪一侧：Excel 历史真值与
RAN_UME 重算值**并存不覆盖**，这样才能在 /meta 里给出对账差异。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("bp_report_store")

# 产物库：my_app 自持，后端每请求只读打开
SERVICE_DIR = Path(__file__).resolve().parent
DB_PATH = SERVICE_DIR.parent.parent / "data" / "bp_report.sqlite3"

# ============================================================
# DDL —— 全部 IF NOT EXISTS，可重复执行
# ============================================================

DDL_STATEMENTS: Tuple[str, ...] = (
    # 小区 → Cluster/Layer 字典。从 BP Cells List 一次性抽取（4269 行）。
    # 不设外键：字典是「尽力而为」的映射，RAN_UME 侧随时可能出现字典外的新小区。
    """CREATE TABLE IF NOT EXISTS bp_cell_dict(
        cell_name   TEXT PRIMARY KEY,
        me_id       TEXT,
        cluster     TEXT,
        layer       TEXT,
        first_day   TEXT,
        last_day    TEXT,
        bp_days     INTEGER,
        updated_at  TEXT
    )""",

    # 逐小区逐日明细。is_bp 三态：1=True / 0=False / NULL=不可判定（缺值）。
    # 用 NULL 而不是 0 表示不可判定，是为了让聚合能显式区分「不满足」与「没数据」。
    """CREATE TABLE IF NOT EXISTS bp_cell_daily(
        day         TEXT NOT NULL,
        cell_name   TEXT NOT NULL,
        me_id       TEXT,
        cluster     TEXT,
        layer       TEXT,
        is_bp       INTEGER,          -- 1/0/NULL
        prb_dl      REAL,             -- [FDD]DL PRB Utilization Rate (%)
        thr_dl      REAL,             -- [FDD]DL IP Throughput (Mbps)
        active_user REAL,             -- Average DL Active User Number（当前为 NULL）
        dl_gb       REAL,             -- DL 流量 GB（用于 Total Traffic 汇总）
        ul_gb       REAL,             -- UL 流量 GB
        region      TEXT,             -- Excel Regional sheet 的原生分区（Cluster1..6/Rural/ERA）
        source      TEXT,             -- excel / ume / both
        updated_at  TEXT,
        PRIMARY KEY (day, cell_name)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_bp_cell_daily_day ON bp_cell_daily(day)",
    "CREATE INDEX IF NOT EXISTS ix_bp_cell_daily_cluster ON bp_cell_daily(day, cluster)",
    "CREATE INDEX IF NOT EXISTS ix_bp_cell_daily_layer ON bp_cell_daily(day, layer)",

    # 全网日汇总（对应 Overall - Daily sheet）
    """CREATE TABLE IF NOT EXISTS bp_overall_daily(
        day            TEXT PRIMARY KEY,
        bp_cells       INTEGER,
        total_cells    INTEGER,
        bp_ratio       REAL,
        traffic_tb     REAL,          -- 4G_Data_Traffic(TB) - excluding ERA
        bp_cells_excel INTEGER,       -- Excel 原生值（对账用，重算时不覆盖）
        native_date    TEXT,          -- Excel 的 Mon/Tue 星期文本
        source         TEXT,
        updated_at     TEXT
    )""",

    # 分区日汇总（对应 Regional - Daily sheet）
    """CREATE TABLE IF NOT EXISTS bp_region_daily(
        day         TEXT NOT NULL,
        region      TEXT NOT NULL,
        bp_number   INTEGER,
        total_cell  INTEGER,
        bp_ratio    REAL,
        traffic_tb  REAL,
        source      TEXT,
        updated_at  TEXT,
        PRIMARY KEY (day, region)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_bp_region_daily_region ON bp_region_daily(region, day)",

    # 分层日汇总（对应 Frequency layer - Daily sheet）
    """CREATE TABLE IF NOT EXISTS bp_layer_daily(
        day         TEXT NOT NULL,
        region      TEXT NOT NULL,
        layer       TEXT NOT NULL,
        bp_number   INTEGER,
        total_cell  INTEGER,
        bp_ratio    REAL,
        source      TEXT,
        updated_at  TEXT,
        PRIMARY KEY (day, region, layer)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_bp_layer_daily_layer ON bp_layer_daily(layer, day)",

    # 全网周汇总（对应 Overall - 1 Weekly）。bp_days/total_days 是 4/7 判定的中间量，
    # 一起存下来，界面才能解释「为什么这周算/不算 BP 周」。
    """CREATE TABLE IF NOT EXISTS bp_overall_week(
        week        TEXT PRIMARY KEY,   -- ISO 周键 YYYY-Www
        bp_days     INTEGER,
        total_days  INTEGER,
        is_bp_week  INTEGER,
        bp_cells    INTEGER,
        total_cells INTEGER,
        bp_ratio    REAL,
        traffic_tb  REAL,
        native_period TEXT,             -- Excel 原生文本，如 'W48, 2023'
        source      TEXT,
        updated_at  TEXT
    )""",

    # 全网月汇总（对应 Overall - Monthly）。bp_weeks/total_weeks 是 3/4 判定的中间量。
    # total_weeks 只数**完整周**（周一与周日都在月内），与口径 '4 full weeks' 一致。
    """CREATE TABLE IF NOT EXISTS bp_overall_month(
        month       TEXT PRIMARY KEY,   -- YYYY-MM
        bp_weeks    INTEGER,
        total_weeks INTEGER,
        is_bp_month INTEGER,
        bp_cells    INTEGER,
        total_cells INTEGER,
        bp_ratio    REAL,
        traffic_tb  REAL,
        native_period TEXT,             -- Excel 原生文本，如 'Apr, 2023'
        source      TEXT,
        updated_at  TEXT
    )""",

    # 同步元信息（键值对）：上次同步时间、口径快照 JSON、对账差异 JSON、脏值计数
    """CREATE TABLE IF NOT EXISTS bp_sync_meta(
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at TEXT
    )""",
)


# ============================================================
# 连接管理
# ============================================================

def connect(path: Optional[os.PathLike] = None, read_only: bool = False) -> sqlite3.Connection:
    """打开物化库。

    Args:
        path:      库路径，默认 DB_PATH（测试可传临时文件）。
        read_only: True 时以 `mode=ro` 打开 —— **后端查询一律只读**，
                   避免一个查询接口意外写了库。

    注意不用 `Path.resolve()`：本机 Y: 是网络映射盘，resolve() 会展开成
    UNC 路径导致 sqlite 的 file: URI 解析失败（同 ran_cells_kpi_service.py:49-51 的坑）。
    """
    p = os.path.abspath(str(path or DB_PATH))
    if read_only:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    else:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def write_conn(path: Optional[os.PathLike] = None):
    """写事务上下文：正常提交，异常回滚并重新抛出。"""
    conn = connect(path, read_only=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)


def db_exists(path: Optional[os.PathLike] = None) -> bool:
    """物化库是否已存在且非空。页面用它决定是否提示「请先跑导入」。"""
    p = os.path.abspath(str(path or DB_PATH))
    return os.path.exists(p) and os.path.getsize(p) > 0


# ============================================================
# UPSERT —— 统一用 INSERT ... ON CONFLICT，两种写法都幂等
# ============================================================

def upsert_many(conn: sqlite3.Connection, table: str,
                columns: Sequence[str], rows: Iterable[Sequence[Any]],
                conflict_cols: Sequence[str]) -> int:
    """批量 UPSERT，返回写入行数。

    用 `ON CONFLICT(...) DO UPDATE SET` 而非 `INSERT OR REPLACE`：后者是
    DELETE + INSERT，会把没在本次 UPDATE 列表里的列（如 Excel 原生对照列）清空。
    """
    cols = list(columns)
    placeholders = ",".join("?" for _ in cols)
    update_cols = [c for c in cols if c not in conflict_cols]
    sql = (f'INSERT INTO {table}({",".join(cols)}) VALUES ({placeholders}) '
           f'ON CONFLICT({",".join(conflict_cols)}) DO UPDATE SET '
           + ",".join(f"{c}=excluded.{c}" for c in update_cols))
    batch = [tuple(r) for r in rows]
    if not batch:
        return 0
    conn.executemany(sql, batch)
    return len(batch)


def set_meta(conn: sqlite3.Connection, key: str, value: Any, now: str) -> None:
    """写一条元信息（值统一转字符串）。"""
    import json
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    conn.execute(
        'INSERT INTO bp_sync_meta(key, value, updated_at) VALUES (?,?,?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
        (key, value, now))


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    """读一条元信息；值是 JSON 时自动解析。"""
    import json
    row = conn.execute("SELECT value FROM bp_sync_meta WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    raw = row["value"]
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def all_meta(conn: sqlite3.Connection) -> Dict[str, Any]:
    """读全部元信息（/meta 端点用）。"""
    import json
    out: Dict[str, Any] = {}
    for row in conn.execute("SELECT key, value, updated_at FROM bp_sync_meta"):
        try:
            out[row["key"]] = json.loads(row["value"])
        except (TypeError, ValueError):
            out[row["key"]] = row["value"]
    return out


# ============================================================
# 通用查询辅助
# ============================================================

def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    """sqlite3.Row → dict 列表（router 直接 JSON 化）。"""
    return [dict(r) for r in rows]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    """表行数（对账用）。表不存在返回 0 而不是抛错。"""
    try:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    except sqlite3.Error:
        return 0


def scalar(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Any:
    """取单个标量值；无行返回 None。"""
    row = conn.execute(sql, tuple(params)).fetchone()
    return row[0] if row is not None else None


def distinct_values(conn: sqlite3.Connection, table: str, col: str) -> List[str]:
    """某列的全部去重取值（按声明顺序排序交给调用方）。"""
    try:
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL AND {col}<>''")
            if r[0] is not None]
    except sqlite3.Error:
        return []
