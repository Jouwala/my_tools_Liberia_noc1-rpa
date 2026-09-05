"""任务执行日志统计查询（架构优化 Phase 4，从 task_runner.py 拆出）

职责：task_execution_log 表的建表维护与健康度统计 / 失败聚类 / 历史查询，
全部为只读统计（向量化的单条 SQL），供 Task Manager 前端展示。

注意：get_task_history 的进程内内存兜底由调用方（task_runner）通过
fallback_history 参数传入，避免本模块反向依赖 task_runner。
"""
import os
import logging
from datetime import datetime

import sqlite3
from backend.database import DB_PATH, get_raw_connection
from backend.dialect_helpers import table_columns

logger = logging.getLogger("task_runner")


def _ensure_task_log_table(conn):
    """确保 task_execution_log 表存在且含 error_trace 列。

    兼容旧库：旧表在 CREATE TABLE IF NOT EXISTS 时已存在但缺 error_trace 列，
    该语句不会自动加列，需通过 PRAGMA 检查后 ALTER 补列，否则查询报错
    'no such column: error_trace'。
    """
    if isinstance(conn, sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                task_name TEXT,
                category TEXT,
                trigger_type TEXT,
                success INTEGER,
                started_at TEXT,
                completed_at TEXT,
                elapsed_seconds REAL,
                result_json TEXT,
                error TEXT,
                error_trace TEXT
            )
        """)
    else:
        # PG：以 GENERATED ALWAYS AS IDENTITY 取代 sqlite 的 AUTOINCREMENT
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_execution_log (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_name TEXT,
                category TEXT,
                trigger_type TEXT,
                success INTEGER,
                started_at TEXT,
                completed_at TEXT,
                elapsed_seconds REAL,
                result_json TEXT,
                error TEXT,
                error_trace TEXT
            )
        """)
    try:
        cols = set(table_columns(conn, "task_execution_log"))
        if "error_trace" not in cols:
            conn.execute("ALTER TABLE task_execution_log ADD COLUMN error_trace TEXT")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"确保 error_trace 列失败: {e}")
def _fetch_latest_runs() -> dict:
    """
    一次性查出每个任务的最新一条执行记录（单条 SQL + 子查询分组），
    避免前端 list + 逐任务 detail 产生的 N+1 请求。
    返回 {task_id: [run_dict]}（每个任务仅含最新 1 条，足够卡片展示）。
    """
    result: dict = {}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT l.task_id, l.task_name, l.category, l.trigger_type, l.success,
                      l.started_at, l.completed_at, l.elapsed_seconds, l.error, l.error_trace
               FROM task_execution_log l
               INNER JOIN (
                   SELECT task_id, MAX(id) AS max_id
                   FROM task_execution_log
                   GROUP BY task_id
               ) m ON l.task_id = m.task_id AND l.id = m.max_id"""
            ).fetchall()
            for r in rows:
                result[r[0]] = [{
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }]
            conn.close()
    except Exception as e:
        logger.warning(f"批量查询最新执行记录失败: {e}")
    return result
def get_task_stats(task_id: str, days: int | None = None) -> dict:
    """统计某任务在保留期内的执行健康度（成功率 / 平均·最大耗时）。"""
    result = {
        "task_id": task_id,
        "total_runs": 0,
        "success_runs": 0,
        "failed_runs": 0,
        "success_rate": None,
        "avg_elapsed": None,
        "max_elapsed": None,
        "first_seen": None,
        "last_seen": None,
    }
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            where = "WHERE task_id = ?"
            params: list = [task_id]
            if days:
                # PG 无 datetime('now', '-N days')；改用 Python 计算截止时间，双模通用
                from datetime import timedelta
                _cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                where += " AND started_at >= ?"
                params.append(_cutoff)
            row = conn.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(success),0),
                           AVG(elapsed_seconds), MAX(elapsed_seconds),
                           MIN(started_at), MAX(started_at)
                    FROM task_execution_log {where}""",
                params,
            ).fetchone()
            conn.close()
            if row and row[0]:
                total = row[0]
                succ = row[1]
                result.update({
                    "total_runs": total,
                    "success_runs": succ,
                    "failed_runs": total - succ,
                    "success_rate": round(succ / total, 4) if total else None,
                    "avg_elapsed": round(row[2], 2) if row[2] is not None else None,
                    "max_elapsed": round(row[3], 2) if row[3] is not None else None,
                    "first_seen": row[4],
                    "last_seen": row[5],
                })
    except Exception as e:
        logger.warning(f"统计任务健康度失败 ({task_id}): {e}")
    return result


def get_recent_failures(days: int = 3, limit: int = 200) -> dict:
    """按 error 首行聚类近期失败，便于快速判断是否为同一根因。

    2026-09-05 分层（P0-3）：每簇增加 status 字段——
      active         该簇涉及任务当前最新一次执行仍是失败（正在持续故障）
      recovered      簇内所有任务在错误发生后都已有成功记录（历史故障已恢复）
      needs_attention 簇内存在任务从未成功过（无任何 success=1 记录）
    避免已恢复的历史故障（如 EWS 降级期失败）长期占据红色榜首误导排障。
    """
    clusters: dict[str, dict] = {}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            # PG 无 datetime('now', '-N days')；改用 Python 计算截止时间，双模通用
            from datetime import timedelta
            _cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT task_id, task_name, error, started_at
               FROM task_execution_log
               WHERE success = 0
                 AND started_at >= ?
               ORDER BY started_at DESC LIMIT ?""",
                (_cutoff, limit),
            ).fetchall()
            conn.close()
            for task_id, task_name, error, started_at in rows:
                key = (error or "未知错误").split("\n")[0][:120]
                c = clusters.get(key)
                if not c:
                    c = {"error_first_line": key, "count": 0, "tasks": {}, "last_seen": None}
                    clusters[key] = c
                c["count"] += 1
                c["tasks"][task_id] = c["tasks"].get(task_id, 0) + 1
                if not c["last_seen"] or (started_at or "") > c["last_seen"]:
                    c["last_seen"] = started_at
    except Exception as e:
        logger.warning(f"聚合失败记录失败: {e}")

    # ---- 分层判定：一次 SQL 查出每个任务「最新一条执行是否成功」与「是否存在成功记录」 ----
    latest_success: dict[str, bool] = {}
    ever_success: dict[str, bool] = {}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            latest = conn.execute(
                """SELECT l.task_id, l.success FROM task_execution_log l
                   INNER JOIN (SELECT task_id, MAX(id) AS max_id FROM task_execution_log
                               GROUP BY task_id) m ON l.task_id = m.task_id AND l.id = m.max_id"""
            ).fetchall()
            latest_success = {r[0]: bool(r[1]) for r in latest}
            ever = conn.execute(
                "SELECT DISTINCT task_id FROM task_execution_log WHERE success = 1"
            ).fetchall()
            ever_success = {r[0] for r in ever}
            conn.close()
    except Exception as e:
        logger.warning(f"失败分层查询异常（按 active 处理）: {e}")

    items = []
    for c in clusters.values():
        task_ids = list(c["tasks"].keys())
        if any(tid not in ever_success for tid in task_ids):
            status = "needs_attention"
        elif any(not latest_success.get(tid, False) for tid in task_ids):
            status = "active"
        else:
            status = "recovered"
        c["status"] = status
        items.append(c)
    items.sort(key=lambda x: (x["status"] != "active", x["status"] != "needs_attention", -x["count"]))
    return {"days": days, "total_failures": sum(c["count"] for c in items), "clusters": items}


def get_task_history_by_task(task_id: str, limit: int = 200) -> list[dict]:
    """某任务的执行历史（按时间倒序），供前端历史弹窗分页 / 导出。"""
    rows: list[dict] = []
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            cur = conn.execute(
                "SELECT task_id, task_name, category, trigger_type, success, "
                "started_at, completed_at, elapsed_seconds, result_json, error, error_trace "
                "FROM task_execution_log WHERE task_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (task_id, limit),
            )
            for r in cur.fetchall():
                rows.append({
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "result_json": r[8],
                    "error": r[9], "error_trace": r[10],
                })
            conn.close()
    except Exception as e:
        logger.warning(f"查询任务历史失败 ({task_id}): {e}")
    return rows


def get_task_history(limit: int = 20, fallback_history: list | None = None) -> list[dict]:
    """获取最近的任务执行历史"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error, error_trace
               FROM task_execution_log
               ORDER BY started_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            conn.close()
            return [
                {
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }
                for r in rows
            ]
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_task_history: exception swallowed", exc_info=True)
        return list(reversed((fallback_history or [])[-limit:]))


def get_global_history(
    limit: int = 50,
    offset: int = 0,
    task_id: str | None = None,
    success: int | None = None,
    trigger: str | None = None,
    keyword: str | None = None,
    start: str | None = None,
    end: str | None = None,
    fallback_history: list | None = None,
) -> dict:
    """全局执行历史（总历史记录）：跨所有任务，支持过滤 + 分页。

    返回 {"history": [...], "total": int}。双模（sqlite / PG）通用：
    - 全部用 '?' 占位符（PG 包装层会自动转 %s）
    - WHERE / 时间范围用字符串比较（started_at 为 ISO，字典序即时间序）

    过滤项：
    - task_id：精确匹配任务 ID
    - success：1 / 0（None 表示不过滤）
    - trigger：manual / scheduled / manual_stop ...
    - keyword：模糊匹配 task_name / error / task_id（LIKE %kw%）
    - start / end：ISO 时间范围（started_at >= start 且 <= end）
    """
    where_clauses: list[str] = []
    params: list = []
    if task_id:
        where_clauses.append("task_id = ?")
        params.append(task_id)
    if success is not None:
        where_clauses.append("success = ?")
        params.append(1 if success else 0)
    if trigger:
        where_clauses.append("trigger_type = ?")
        params.append(trigger)
    if keyword:
        where_clauses.append("(task_name LIKE ? OR error LIKE ? OR task_id LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if start:
        where_clauses.append("started_at >= ?")
        params.append(start)
    if end:
        where_clauses.append("started_at <= ?")
        params.append(end)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            total = conn.execute(
                f"SELECT COUNT(*) FROM task_execution_log {where_sql}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT task_id, task_name, category, trigger_type, success,
                           started_at, completed_at, elapsed_seconds, error, error_trace
                    FROM task_execution_log {where_sql}
                    ORDER BY started_at DESC LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
            conn.close()
            history = [
                {
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }
                for r in rows
            ]
            return {"history": history, "total": total}
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_global_history: exception swallowed", exc_info=True)
        # 内存兜底：仅做 task_id / success / keyword 过滤（时间窗忽略），保证接口永不空失败
        fb = list(reversed((fallback_history or [])[-1000:]))
        if task_id:
            fb = [r for r in fb if r.get("task_id") == task_id]
        if success is not None:
            fb = [r for r in fb if bool(r.get("success")) == bool(success)]
        if keyword:
            kw = keyword.lower()
            fb = [
                r for r in fb
                if (r.get("task_name") or "").lower().find(kw) >= 0
                or (r.get("error") or "").lower().find(kw) >= 0
                or (r.get("task_id") or "").lower().find(kw) >= 0
            ]
        return {"history": fb[offset:offset + limit], "total": len(fb)}
