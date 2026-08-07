"""系统信息 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/health                     健康检查
- /api/data-source/timestamps     数据源时间信息（eFlow 同步时间 + 数据最新时间）
- /api/db/info                    数据库概览信息
"""
import logging

from fastapi import APIRouter

from backend.database import DB_PATH, get_raw_connection
from backend.task_registry import sync_history

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


@router.get("/api/data-source/timestamps")
def get_data_timestamps():
    """数据源时间信息：eFlow 同步时间 + 数据最新时间"""
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
            "latest_data_time": latest_data,
            "latest_tt_time": latest_tt,
            "latest_wo_time": latest_wo,
        }


@router.get("/api/db/info")
def db_info():
    """数据库概览信息"""
    with get_raw_connection(str(DB_PATH)) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]

        total_rows = 0
        table_info = []
        for t in tables:
            count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            total_rows += count
            table_info.append({"name": t, "rows": count})

        conn.close()
        return {
            "database": str(DB_PATH),
            "total_tables": len(tables),
            "total_rows": total_rows,
            "tables": table_info,
        }
