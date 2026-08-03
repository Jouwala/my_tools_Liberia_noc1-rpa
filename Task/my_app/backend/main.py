"""数据洞察 SaaS MVP - FastAPI后端主入口"""
import time
import sys
import os
import logging
from datetime import datetime

# 修复非UTF-8控制台环境下中文输出崩溃
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:main>: exception swallowed", exc_info=True)
    pass

# 确保可以import backend模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.database import Base, engine, DB_PATH
from backend.models.analysis import AnalysisArchive, UploadedFile
from backend.routers import tables, upload, analysis, gis, tt_wo_dashboard, alarm_dashboard, packet_loss_dashboard
from backend.services import task_runner
from backend.security import require_protected
from backend.database import get_raw_connection
from backend.services.sp_dashboard import (
    get_dashboard_data,
    get_warehouses as sp_list_warehouses,
    get_detail_rows,
)

start_time = time.time()

app = FastAPI(
    title="数据洞察 SaaS MVP",
    description="上传工作簿、自动识别字段与质量问题、生成多维图表和结论，GIS展示与下钻，分析归档检索",
    version="1.0.0",
)

# CORS配置 - 仅允许明确来源（避免 allow_origins="*" + 凭据的跨域风险）
# 可用环境变量 MY_APP_CORS_ORIGINS 覆盖，逗号分隔
_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "MY_APP_CORS_ORIGINS",
        "http://127.0.0.1:7038,http://localhost:7038,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
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
app.include_router(alarm_dashboard.router)
app.include_router(packet_loss_dashboard.router)


# ========== 通用任务调度系统 ==========
# 任务定义与注册已迁移至 backend/task_registry.py（P2#8 拆分）：
# 原 _register_all_tasks 336 行 → 声明式 TASK_SPECS + 通用注册循环；
# sync_history 亦由 task_registry 统一维护（旧 eFlow API 兼容）。
from backend.task_registry import sync_history, register_all_tasks


def _register_all_tasks():
    """注册所有可调度的任务（声明式定义见 backend/task_registry.py）"""
    return register_all_tasks(task_runner)

def _init_db_with_retry(max_retries: int = 12, wait: int = 5):
    """db 初始化可能因后台进程(Windows Search 索引 / 杀软实时扫描)临时锁住
    app.db 而失败，这里加重试穿过锁释放窗口，避免后端启动卡死。"""
    import sqlite3
    last_err = None
    for i in range(1, max_retries + 1):
        try:
            # 创建ORM模型表
            Base.metadata.create_all(bind=engine)
            # 确保uploaded_files表存在
            with get_raw_connection(str(DB_PATH), timeout=30) as conn:
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
                # 初始化调度配置表
                task_runner._init_schedule_table()
                return
        except Exception as e:
            last_err = e
            print(f"[startup] db 初始化遇锁({type(e).__name__})，{wait}s 后重试 ({i}/{max_retries}): {e}")
            time.sleep(wait)
    raise last_err or RuntimeError("db init failed after retries")


@app.on_event("startup")
async def startup_event():
    """启动时创建必要的表和索引（app.db 可能被后台索引/杀软临时锁住，加重试穿过）"""
    _init_db_with_retry()

    # 注册所有任务并启动调度器
    _register_all_tasks()
    task_runner.schedule_all_tasks()
    task_runner.start_scheduler()

    elapsed = time.time() - start_time
    print(f"服务启动完成，耗时: {elapsed:.2f}秒")
    print(f"数据库: {DB_PATH}")
    print(f"已注册 {len(task_runner.list_tasks())} 个定时任务")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


@app.post("/api/eflow/sync", dependencies=[Depends(require_protected)])
def trigger_eflow_sync():
    """手动触发 eFlow API 数据同步（兼容旧接口）"""
    result = task_runner.run_task("eflow_sync", trigger="manual")
    if result.get("result") and isinstance(result["result"], dict):
        # 兼容旧接口返回格式
        inner = result["result"]
        if "tables_synced" in inner:
            sync_history.append(inner)
            while len(sync_history) > 20:
                sync_history.pop(0)
            return inner
    return result


@app.get("/api/eflow/status")
def eflow_sync_status():
    """eFlow API 同步状态（兼容旧接口）"""
    detail = task_runner.get_task_detail("eflow_sync")
    return {
        "scheduler_running": task_runner.get_scheduler().running,
        "next_run": detail.get("next_run") if detail else None,
        "schedule": "每小时第22分钟",
        "history": sync_history[-10:],
    }


# ========== 通用任务管理 API ==========
def _req_lang(request: Request) -> str:
    """从 Accept-Language 头推断语言（en 优先，其余回退 zh）。"""
    accept = (request.headers.get("Accept-Language") or "").lower()
    return "en" if accept.startswith("en") else "zh"


@app.get("/api/tasks")
def list_all_tasks(request: Request):
    """列出所有已注册的定时任务（含最新执行记录，单次返回，避免前端 N+1）"""
    return {"tasks": task_runner.list_tasks(include_runs=True, lang=_req_lang(request))}


@app.get("/api/tasks/history")
def get_tasks_history(limit: int = 20):
    """获取任务执行历史"""
    return {"history": task_runner.get_task_history(limit)}


@app.get("/api/tasks/failures")
def tasks_failures(days: int = 3, limit: int = 200):
    """按 error 首行聚类近期失败，便于快速判断是否为同一根因"""
    return task_runner.get_recent_failures(days, limit)


@app.get("/api/tasks/{task_id}")
def get_task_info(task_id: str, request: Request):
    """获取任务详情（含最近执行记录）"""
    detail = task_runner.get_task_detail(task_id, lang=_req_lang(request))
    if not detail:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return detail


@app.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_protected)])
def run_task_now(task_id: str):
    """立即执行指定任务（后台异步执行，立即返回 accepted）"""
    return task_runner.run_task_async(task_id, trigger="manual")


@app.get("/api/tasks/{task_id}/status")
def task_run_status(task_id: str):
    """查询任务是否正在运行"""
    return {"task_id": task_id, "running": task_runner.is_task_running(task_id)}


@app.get("/api/tasks/{task_id}/stats")
def task_stats(task_id: str, days: int | None = None):
    """任务健康度统计（成功率 / 平均·最大耗时）"""
    return task_runner.get_task_stats(task_id, days)


@app.get("/api/tasks/{task_id}/history")
def task_history(task_id: str, limit: int = 200):
    """某任务的执行历史（分页 / 导出用）"""
    return {"history": task_runner.get_task_history_by_task(task_id, limit)}


# ========== SP 备件仓库看板 API ==========
@app.get("/api/sp-data/summary")
def sp_data_summary():
    """各 SP 表的总行数、列、最近同步时间、衍生指标（供仓库看板）"""
    from backend.services.get_sp_table import get_sp_summary
    return get_sp_summary()


@app.get("/api/sp-data/rows")
def sp_data_rows(table: str, page: int = 1, size: int = 50, search: str = ""):
    """分页 + 模糊搜索返回某 SP 表的数据"""
    from backend.services.get_sp_table import get_sp_rows, SP_TABLES
    if table not in SP_TABLES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"未知表: {table}")
    return get_sp_rows(table, page=page, size=size, search=search)


# ========== SP 备件仓库看板（对齐 Unified_Tools/WareHouseDashBoard）==========
# 计算逻辑完整复用 app_sp_optimized.py（见 backend/services/sp_dashboard.py），
# 返回结构对齐参考 Flask 的 /api/data、/api/warehouses、/api/details。


@app.get("/api/data")
def sp_dashboard_data(date_start: str | None = None, date_end: str | None = None,
                      warehouse: str | None = None):
    """仓库看板主数据，结构对齐参考 Flask /api/data。"""
    data = get_dashboard_data(date_start, date_end, warehouse)
    return {"status": "success", "data": data}


@app.get("/api/warehouses")
def sp_dashboard_warehouses():
    """仓库下拉列表。"""
    return {"status": "success", "warehouses": sp_list_warehouses()}


@app.get("/api/details")
def sp_dashboard_details(
    type: str,
    column: str | None = None,
    value: str | None = None,
    mode: str = "exact",
    first_column: str | None = None,
    first_value: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    warehouse: str | None = None,
    status_column: str | None = None,
    status_value: str | None = None,
    status_mode: str = "exact",
    sla_filter: bool = False,
    sla_type: str | None = None,
):
    """明细查询，对齐参考 Flask /api/details。"""
    if type not in ("inband", "outband", "inventory"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"未知明细类型: {type}")
    result = get_detail_rows(
        detail_type=type,
        filter_column=column,
        filter_value=value,
        filter_mode=mode,
        first_column=first_column,
        first_value=first_value,
        date_start=date_start,
        date_end=date_end,
        warehouse=warehouse,
        status_column=status_column,
        status_value=status_value,
        status_mode=status_mode,
        sla_filter=sla_filter,
        sla_type=sla_type,
    )
    return {"status": "success", **result}


@app.post("/api/tasks/{task_id}/schedule")
def update_task_schedule(task_id: str, body: dict):
    """更新任务调度频率
    body: {"cron": "分 时 日 月 周"}
    示例: {"cron": "0 8 * * *"} 每天8点
          {"cron": "30 7 * * 1-5"} 工作日7:30
          {"cron": "0 */4 * * *"} 每4小时
    """
    cron = body.get("cron", "")
    if not cron:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="缺少 cron 表达式")
    return task_runner.update_task_schedule(task_id, cron)


@app.post("/api/tasks/{task_id}/toggle")
def toggle_task_enabled(task_id: str, body: dict):
    """启用/禁用任务
    body: {"enabled": true/false}
    """
    enabled = body.get("enabled", True)
    return task_runner.toggle_task(task_id, enabled)


@app.get("/api/data-source/timestamps")
def get_data_timestamps():
    """数据源时间信息：eFlow 同步时间 + 数据最新时间"""
    import sqlite3

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
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
                pass
        latest_tt = None
        latest_wo = None
        try:
            latest_tt = conn.execute(
                "SELECT MAX(created_time) FROM eflow_tt WHERE created_time IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
            pass
        try:
            latest_wo = conn.execute(
                "SELECT MAX(created_time) FROM eflow_wo WHERE created_time IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_data_timestamps: exception swallowed", exc_info=True)
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


@app.get("/api/db/info")
def db_info():
    """数据库概览信息"""
    import sqlite3
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


# 提供前端静态文件（生产环境）
# 注意：必须校验 assets 目录真实存在，否则 StaticFiles 会因目录缺失而抛出
# RuntimeError，导致整个 uvicorn 应用导入失败、后端无法启动（开发模式下前端由 Vite 提供，无需此挂载）。
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if (frontend_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
else:
    print("WARNING: frontend/dist/assets 不存在，跳过静态资源挂载（开发模式由 Vite 提供前端，不影响 API）")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)