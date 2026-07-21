"""数据洞察 SaaS MVP - FastAPI后端主入口"""
import time
import sys
import os
from datetime import datetime

# 确保可以import backend模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.database import Base, engine, DB_PATH
from backend.models.analysis import AnalysisArchive, UploadedFile
from backend.routers import tables, upload, analysis, gis, tt_wo_dashboard
from apscheduler.schedulers.background import BackgroundScheduler

start_time = time.time()

app = FastAPI(
    title="数据洞察 SaaS MVP",
    description="上传工作簿、自动识别字段与质量问题、生成多维图表和结论，GIS展示与下钻，分析归档检索",
    version="1.0.0",
)

# CORS配置 - 允许前端开发服务器
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(tables.router)
app.include_router(upload.router)
app.include_router(analysis.router)
app.include_router(gis.router)
app.include_router(tt_wo_dashboard.router)


# FTP同步调度器
ftp_scheduler = BackgroundScheduler()

# FTP同步状态记录
ftp_sync_history = []


def scheduled_ftp_sync():
    """定时FTP同步任务"""
    from backend.services.ftp_sync import sync_from_ftp
    import logging
    logger = logging.getLogger("ftp_sync")
    logger.info("定时FTP同步开始 (每小时第22分钟)")
    result = sync_from_ftp()
    ftp_sync_history.append(result)
    # 只保留最近20条记录
    while len(ftp_sync_history) > 20:
        ftp_sync_history.pop(0)
    logger.info(f"FTP同步完成: success={result['success']}, downloaded={result['downloaded']}")


@app.on_event("startup")
async def startup_event():
    """启动时创建必要的表和索引"""
    # 创建ORM模型表
    Base.metadata.create_all(bind=engine)

    # 确保uploaded_files表存在（如果init_db没创建）
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT,
            table_name TEXT,
            row_count INTEGER,
            col_count INTEGER,
            columns_info TEXT,
            quality_issues TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    # 启动FTP同步调度器 - 每小时第22分钟
    ftp_scheduler.add_job(
        scheduled_ftp_sync,
        trigger='cron',
        minute=22,
        id='ftp_sync_hourly',
        replace_existing=True,
    )
    ftp_scheduler.start()

    elapsed = time.time() - start_time
    print(f"服务启动完成，耗时: {elapsed:.2f}秒")
    print(f"数据库: {DB_PATH}")
    print(f"FTP同步调度已启动 (每小时第22分钟)")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


@app.post("/api/ftp/sync")
def trigger_ftp_sync():
    """手动触发FTP同步"""
    from backend.services.ftp_sync import sync_from_ftp
    result = sync_from_ftp()
    ftp_sync_history.append(result)
    while len(ftp_sync_history) > 20:
        ftp_sync_history.pop(0)
    return result


@app.get("/api/ftp/status")
def ftp_sync_status():
    """FTP同步状态"""
    job = ftp_scheduler.get_job('ftp_sync_hourly')
    return {
        "scheduler_running": ftp_scheduler.running,
        "next_run": str(job.next_run_time) if job else None,
        "schedule": "每小时第22分钟",
        "history": ftp_sync_history[-10:],  # 最近10条
    }


@app.get("/api/data-source/timestamps")
def get_data_timestamps():
    """数据源时间信息：FTP同步时间 + 数据最新时间"""
    import sqlite3

    # FTP最近一次成功同步时间（优先内存记录，其次文件修改时间）
    last_sync = None
    for h in reversed(ftp_sync_history):
        if h.get("success"):
            last_sync = h.get("timestamp")
            break

    # 内存无记录时，用本地文件的修改时间作为fallback
    if not last_sync:
        from pathlib import Path
        from backend.services.ftp_sync import LOCAL_TT, LOCAL_WO
        mtimes = []
        for f in [LOCAL_TT, LOCAL_WO]:
            if f.exists():
                mtimes.append(f.stat().st_mtime)
        if mtimes:
            last_sync = datetime.fromtimestamp(max(mtimes)).isoformat()

    # 数据源最新时间
    conn = sqlite3.connect(str(DB_PATH))
    latest_tt = conn.execute(
        "SELECT MAX(created_time) FROM eflow_tt WHERE created_time IS NOT NULL"
    ).fetchone()[0]
    latest_wo = conn.execute(
        "SELECT MAX(created_time) FROM eflow_wo WHERE created_time IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    # 取TT/WO中较晚的一个
    latest_data = max(filter(None, [latest_tt, latest_wo]), default=None)

    return {
        "last_ftp_sync": last_sync,
        "latest_data_time": latest_data,
        "latest_tt_time": latest_tt,
        "latest_wo_time": latest_wo,
    }


@app.get("/api/db/info")
def db_info():
    """数据库概览信息"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
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


# 提供前端静态文件（生产环境）
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
