"""gp_ran 运行记录存储（旁路 SQLite，不进 app.db）。

为什么单独一个 sqlite 文件，而不是往 app.db / PG 加一张表：
1. **内容敏感**。`D023` 是 IMSI（用户身份），清单本体只以 CSV 落在 `backend/data/gp_ran/`
   （已被 .gitignore 挡住）。这里只存**计数与文件路径**，不存任何 IMSI，
   主库因此不会被复制/备份/镜像链路带着一份用户身份清单走。
2. **不污染主库结构**。加表要走 alembic（本项目 PG 为主，还得双方言兼容），
   而这份数据是外部数仓的可重建快照，删了重跑即可，没有迁移价值。
3. 同 `olib_soc_kpi_store.py` / `avail_recon` / `bp_report` 的既有做法：
   旁路库放 `backend/data/<模块>/`，整目录不入库。

⚠ 这里的 `sqlite3.connect` 打开的是**本模块独占的旁路库**，不是 `db/app.db`。
禁止照此写法去连主库（主库一律走 `backend.database.get_raw_connection`）。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gp_ran.store")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "gp_ran"
SQLITE_PATH = DATA_DIR / "gp_ran.sqlite3"
# 保留多少次的 CSV（每次 2 个文件、单个约 14MB）。30 次 ≈ 840MB，够回看一个月。
KEEP_RUNS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TEXT    NOT NULL,   -- 本次运行时刻（UTC, ISO）
    kind          TEXT    NOT NULL,   -- volte / n78
    window_start  TEXT    NOT NULL,   -- 窗口起始日 YYYY-MM-DD（含）
    window_end    TEXT    NOT NULL,   -- 窗口截止日 YYYY-MM-DD（不含）
    users         INTEGER NOT NULL,   -- 窗口内 DISTINCT D023(IMSI) 数
    rows_scanned  INTEGER,            -- 窗口内明细行数（数仓上游是否缺数的体检项）
    data_last     TEXT,               -- 窗口内最大记录时间，用于展示「数据截至」
    csv_path      TEXT,
    csv_bytes     INTEGER,
    seconds       REAL,
    status        TEXT    NOT NULL,   -- ok / error
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_runs_kind_time ON user_runs(kind, run_at);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_store() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_run(kind: str, window_start: str, window_end: str, users: int,
               csv_path: str = "", csv_bytes: int = 0, seconds: float = 0.0,
               status: str = "ok", detail: str = "",
               rows_scanned: Optional[int] = None, data_last: str = "",
               run_at: Optional[str] = None) -> int:
    """写一条运行记录，返回自增 id。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "INSERT INTO user_runs (run_at, kind, window_start, window_end, users, "
            "rows_scanned, data_last, csv_path, csv_bytes, seconds, status, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_at or utc_now_iso(), kind, window_start, window_end, users,
             rows_scanned, data_last, csv_path, csv_bytes, round(seconds, 1),
             status, detail))
        return int(cur.lastrowid or 0)


def latest_runs(limit: int = 20, kind: str = "") -> List[Dict[str, Any]]:
    """最近若干次运行（看板/任务页用）。库还没建过就返回空列表，不抛。"""
    try:
        with _connect() as conn:
            if not conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='user_runs'").fetchone():
                return []
            sql = "SELECT * FROM user_runs"
            params: tuple = ()
            if kind:
                sql += " WHERE kind = ?"
                params = (kind,)
            sql += " ORDER BY id DESC LIMIT ?"
            return [dict(r) for r in conn.execute(sql, params + (int(limit),))]
    except sqlite3.Error as exc:
        logger.warning("[gp_ran] 读运行记录失败（按空处理）: %s", exc)
        return []


def median_users(kind: str, window_end: str, n: int = 8) -> Optional[int]:
    """最近 n 次成功运行的 users 中位数，供「本次比历史低很多」的体检用。

    取中位数而不是均值：上游偶尔缺数会把均值拉偏，中位数不会。
    只统计**同一个 kind**、且窗口截止日早于 window_end 的历史（不与本次比）。
    """
    rows = latest_runs(limit=n + 1, kind=kind)
    vals = sorted(r["users"] for r in rows
                  if r.get("status") == "ok" and r.get("window_end") != window_end)
    vals = vals[-n:]
    if len(vals) < 3:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) // 2


def purge_files(keep: int = KEEP_RUNS) -> Dict[str, Any]:
    """只保留最近 keep 次运行的 CSV，更早的删掉（记录行保留，路径置空）。

    删之前把路径限定在本模块的 DATA_DIR 之下，避免历史记录里混进别处路径时被误删。
    """
    info = {"keep": keep, "deleted": 0, "kept": 0, "run_at": utc_now_iso()}
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        rows = conn.execute(
            "SELECT csv_path, MAX(id) AS last_id FROM user_runs "
            "WHERE csv_path IS NOT NULL AND csv_path <> '' "
            "GROUP BY csv_path ORDER BY last_id DESC").fetchall()
        paths = [r["csv_path"] for r in rows]
        for p in paths[keep:]:
            try:
                fp = Path(p).resolve()
            except OSError:
                continue
            if not str(fp).startswith(str(DATA_DIR.resolve())):
                continue                      # 不在本模块目录下的路径一律不碰
            if fp.exists():
                try:
                    fp.unlink()
                    info["deleted"] += 1
                except OSError as exc:
                    logger.warning("[gp_ran] 删除旧 CSV 失败 %s: %s", fp, exc)
        info["kept"] = len(paths) - info["deleted"]
    return info
