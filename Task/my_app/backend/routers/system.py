"""系统信息 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/health                     健康检查
- /api/data-source/timestamps     数据源时间信息（eFlow 同步时间 + 数据最新时间）
- /api/db/info                    数据库概览信息
"""
import logging
import threading
import time

from fastapi import APIRouter

from backend.database import DB_PATH, DB_MODE, get_raw_connection
from backend.dialect_helpers import list_table_names
from backend.task_registry import sync_history

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health_check():
    """健康检查：PG 模式直接报告 postgresql，避免 sqlite 文件存在性造成误导。"""
    if DB_MODE == "pg":
        return {"status": "ok", "db_mode": "pg", "database": "postgresql", "db_exists": True}
    return {"status": "ok", "db_mode": "sqlite", "database": str(DB_PATH), "db_exists": DB_PATH.exists()}


@router.get("/api/data-source/timestamps")
def get_data_timestamps():
    """数据源时间信息：eFlow 同步时间 + 告警同步时间 + 数据最新时间"""
    # eFlow 最近一次成功同步时间
    last_sync = None
    for h in reversed(sync_history):
        if h.get("success"):
            last_sync = h.get("timestamp")
            break

    # 数据源最新时间
    with get_raw_connection(str(DB_PATH)) as conn:

        # 内存无记录时，尝试从数据库获取最近同步时间
        if not last_sync:
            try:
                row = conn.execute("SELECT MAX(_sync_time) FROM eflow_tt").fetchone()
                if row and row[0]:
                    last_sync = row[0]
            except Exception:
                logger.warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
                pass

        # 实时告警最近一次成功同步时间（与 Alarm Dashboard 口径一致：
        # task_execution_log 中 eflow_active_alarm 任务最后成功完成时刻）
        alarm_last_sync = None
        try:
            row = conn.execute(
                "SELECT completed_at FROM task_execution_log "
                "WHERE task_id='eflow_active_alarm' AND success=1 AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                alarm_last_sync = str(row[0])
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)

        latest_tt = None
        latest_wo = None
        try:
            latest_tt = conn.execute(
                "SELECT MAX(created_time) FROM eflow_tt WHERE created_time IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
            pass
        try:
            latest_wo = conn.execute(
                "SELECT MAX(created_time) FROM eflow_wo WHERE created_time IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
            pass
        conn.close()

        # 取TT/WO中较晚的一个
        latest_data = max(filter(None, [latest_tt, latest_wo]), default=None)

        return {
            "last_sync": last_sync,
            "alarm_last_sync": alarm_last_sync,
            "latest_data_time": latest_data,
            "latest_tt_time": latest_tt,
            "latest_wo_time": latest_wo,
        }


# /api/db/info 会逐表 COUNT(*)：PG 模式实测 118 张表 / 1072 万行要 30s+，
# 首页每个访客都触发一次既拖垮首屏也压数据库。这里做进程内 TTL 缓存：
# 首次仍然慢（无历史数据），之后 10 分钟内直接返回快照。行数统计只是概览，
# 允许分钟级滞后；不缓存到磁盘，重启即失效，不会留下陈旧数据。
_DB_INFO_TTL = 600
_db_info_cache = {"at": 0.0, "data": None}
_db_info_lock = threading.Lock()


def _compute_db_info():
    """真正执行逐表统计（缓存未命中时调用）。"""
    with get_raw_connection(str(DB_PATH)) as conn:
        if DB_MODE == "pg":
            rows = conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(current_schemas(false)) AND table_type = 'BASE TABLE' "
                "ORDER BY table_schema, table_name"
            ).fetchall()
            tables = [f"{r[0]}.{r[1]}" for r in rows]
        else:
            tables = sorted(list_table_names(conn))

        total_rows = 0
        table_info = []
        for t in tables:
            if DB_MODE == "pg":
                schema, table = t.split(".", 1)
                count = conn.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0]
            else:
                count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            total_rows += count
            table_info.append({"name": t, "rows": count})

        conn.close()
        return {
            "db_mode": DB_MODE,
            "database": "postgresql" if DB_MODE == "pg" else str(DB_PATH),
            "total_tables": len(tables),
            "total_rows": total_rows,
            "tables": table_info,
        }


@router.get("/api/db/info")
def db_info():
    """数据库概览信息（10 分钟进程内缓存，避免每次逐表 COUNT(*) 拖 30 秒）。

    锁内计算是为了让并发首访只做一次统计；持锁期间其它 API 不受影响
    （FastAPI 的同步端点各自跑在线程池里）。
    """
    now = time.time()
    with _db_info_lock:
        cached = _db_info_cache["data"]
        if cached is not None and now - _db_info_cache["at"] < _DB_INFO_TTL:
            return cached
        data = _compute_db_info()
        _db_info_cache["at"] = time.time()
        _db_info_cache["data"] = data
        return data
