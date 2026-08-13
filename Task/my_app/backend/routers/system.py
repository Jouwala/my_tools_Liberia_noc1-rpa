"""系统信息 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/health                     健康检查
- /api/data-source/timestamps     数据源时间信息（eFlow 同步时间 + 数据最新时间）
- /api/db/info                    数据库概览信息
"""
import logging

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


@router.get("/api/db/info")
def db_info():
    """数据库概览信息"""
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
