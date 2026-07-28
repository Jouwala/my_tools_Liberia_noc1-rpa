"""数据洞察 SaaS MVP - FastAPI后端主入口"""
import time
import sys
import os
from datetime import datetime

# 修复非UTF-8控制台环境下中文输出崩溃
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 确保可以import backend模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.database import Base, engine, DB_PATH
from backend.models.analysis import AnalysisArchive, UploadedFile
from backend.routers import tables, upload, analysis, gis, tt_wo_dashboard, alarm_dashboard
from backend.services import task_runner
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
app.include_router(alarm_dashboard.router)


# ========== 通用任务调度系统 ==========
# sync_history 保留兼容旧 eFlow API
sync_history = []


def scheduled_eflow_sync():
    """定时 eFlow API 数据同步任务（兼容旧接口）"""
    from backend.services.sync_from_eflow_api import sync_from_eflow_api
    import logging
    logger = logging.getLogger("eflow_sync")
    logger.info("定时 eFlow API 同步开始")
    result = sync_from_eflow_api()
    sync_history.append(result)
    while len(sync_history) > 20:
        sync_history.pop(0)
    logger.info(f"eFlow 同步完成: success={result['success']}, tables={result['tables_synced']}")
    return result


def _register_all_tasks():
    """注册所有可调度的任务"""

    # 1. eFlow API 数据同步（每小时第22分钟）
    task_runner.register_task(
        task_id="eflow_sync",
        name="eFlow 数据同步",
        name_en="eFlow Data Sync",
        func=scheduled_eflow_sync,
        description="从 ZTE eFlow API 获取 TT/WO/CR/PM/Site/Person 数据",
        description_en="Fetch TT/WO/CR/PM/Site/Person data from ZTE eFlow API",
        default_cron="22 * * * *",  # 每小时第22分钟
        category="eflow",
    )

    # 2. RAN UME PM 数据 + Availability 报表（每天凌晨2点）
    def _run_ran_ume():
        from backend.services.ran_ume_service import run_ran_ume_full_task
        return run_ran_ume_full_task()

    task_runner.register_task(
        task_id="ran_ume_daily",
        name="RAN UME 日报",
        name_en="RAN UME Daily Report",
        func=_run_ran_ume,
        description="RAN UME PM 数据获取 + Daily Availability KPI 报表生成 + FTP 上传",
        description_en="RAN UME PM data fetch + Daily Availability KPI report generation + FTP upload",
        default_cron="0 2 * * *",  # 每天凌晨2点
        category="ran_ume",
    )

    # 3. Site Outage 截图（每天凌晨1点）
    def _run_site_outage():
        from backend.services.site_outage_service import run_site_outage_screenshot
        return run_site_outage_screenshot()

    task_runner.register_task(
        task_id="site_outage_screenshot",
        name="Site Outage 截图",
        name_en="Site Outage Screenshot",
        func=_run_site_outage,
        description="Site Down Dashboard 自动截图（ERA/Regular/ALL）",
        description_en="Auto screenshot of Site Down Dashboard (ERA/Regular/ALL)",
        default_cron="0 1 * * *",  # 每天凌晨1点
        category="site_outage",
    )

    # 4. WhatsApp 发送（每天凌晨3点，在截图之后）
    def _run_whatsapp():
        from backend.services.whatsapp_service import run_whatsapp_send
        return run_whatsapp_send()

    task_runner.register_task(
        task_id="whatsapp_send",
        name="WhatsApp 消息发送",
        name_en="WhatsApp Message Send",
        func=_run_whatsapp,
        description="发送 Site Outage 截图和文件到 WhatsApp 群组",
        description_en="Send Site Outage screenshots and files to WhatsApp groups",
        default_cron="0 3 * * *",  # 每天凌晨3点
        category="whatsapp",
    )

    # 5. MS SLA 完整同步（每6小时）
    def _run_ms_sla_full():
        from backend.services.ms_sla_service import run_full_sync
        return run_full_sync()

    task_runner.register_task(
        task_id="ms_sla_full",
        name="MS SLA 完整同步",
        name_en="MS SLA Full Sync",
        func=_run_ms_sla_full,
        description="SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）",
        description_en="SLA metrics sync + Contract KPIs report update (self-contained, no external files)",
        default_cron="0 */6 * * *",  # 每6小时
        category="ms_sla",
    )

    # 6. eFlow 实时告警同步（每30分钟）
    def _run_eflow_active_alarm():
        from backend.services.eflow_api_client import fetch_and_save_active_alarm
        return fetch_and_save_active_alarm()

    task_runner.register_task(
        task_id="eflow_active_alarm",
        name="eFlow 实时告警同步",
        name_en="eFlow Realtime Alarm Sync",
        func=_run_eflow_active_alarm,
        description="从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite",
        description_en="Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite",
        default_cron="*/30 * * * *",  # 每30分钟
        category="eflow",
    )

    # 7. eFlow 历史告警同步（每3小时）
    def _run_eflow_history_alarm():
        from backend.services.eflow_api_client import fetch_and_save_history_alarm
        return fetch_and_save_history_alarm()

    task_runner.register_task(
        task_id="eflow_history_alarm",
        name="eFlow 历史告警同步",
        name_en="eFlow History Alarm Sync",
        func=_run_eflow_history_alarm,
        description="从 eFlow FM History 接口获取近7天历史告警，过滤 TT ID，保存 CSV + SQLite",
        description_en="Fetch last 7 days history alarms from eFlow FM History API, filter TT ID, save to CSV + SQLite",
        default_cron="0 */3 * * *",  # 每3小时
        category="eflow",
    )

    # 8. RAN UME Main KPI 同步（每天凌晨4点）
    def _run_main_kpi_sync():
        from backend.services.ran_ume_main_kpi import run_main_kpi_sync
        return run_main_kpi_sync()

    task_runner.register_task(
        task_id="main_kpi_sync",
        name="RAN Main KPI 同步",
        name_en="RAN Main KPI Sync",
        func=_run_main_kpi_sync,
        description="RAN UME Main KPI 历史指标同步（2G/3G/4G × Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传",
        description_en="RAN UME Main KPI history sync (2G/3G/4G × Cells/Sites/Group/NW), export Excel and incremental SQLite update + FTP upload",
        default_cron="0 4 * * *",  # 每天凌晨4点
        category="main_kpi",
    )

    # 9. RAN UME Network KPI（Zeenshan）同步（每天凌晨5点）
    def _run_network_kpi_sync():
        from backend.services.ran_ume_network_kpi import run_network_kpi_sync
        return run_network_kpi_sync()

    task_runner.register_task(
        task_id="network_kpi_sync",
        name="RAN Network KPI 同步",
        name_en="RAN Network KPI Sync",
        func=_run_network_kpi_sync,
        description="RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G × Group/NW），导出 Excel 并导入 SQLite + FTP 上传",
        description_en="RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G × Group/NW), export Excel and import to SQLite + FTP upload",
        default_cron="0 5 * * *",  # 每天凌暨5点
        category="network_kpi",
    )
    
    # 10. CNN UME KPI 同步（每天凌暨6点）
    def _run_cnn_kpi_sync():
        from backend.services.ccn_ume_kpi_service import run_cnn_kpi_sync
        return run_cnn_kpi_sync()
    
    task_runner.register_task(
        task_id="cnn_kpi_sync",
        name="CNN UME KPI 同步",
        name_en="CNN UME KPI Sync",
        func=_run_cnn_kpi_sync,
        description="CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN",
        description_en="CNN UME Core Network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN",
        default_cron="0 6 * * *",  # 每天凌暨6点
        category="cnn_kpi",
    )

    # 11. SP 备件数据同步（每天凌晨7点）
    def _run_sp_data_sync():
        from backend.services.get_sp_table import run_sp_data_sync
        return run_sp_data_sync()

    task_runner.register_task(
        task_id="sp_data_sync",
        name="SP 备件数据同步",
        name_en="SP Spare Data Sync",
        func=_run_sp_data_sync,
        description="从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db",
        description_en="Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db",
        default_cron="0 7 * * *",  # 每天凌晨7点
        category="sp",
    )


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
            conn = sqlite3.connect(str(DB_PATH), timeout=30)
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


@app.post("/api/eflow/sync")
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


@app.get("/api/tasks/{task_id}")
def get_task_info(task_id: str, request: Request):
    """获取任务详情（含最近执行记录）"""
    detail = task_runner.get_task_detail(task_id, lang=_req_lang(request))
    if not detail:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return detail


@app.post("/api/tasks/{task_id}/run")
def run_task_now(task_id: str):
    """立即执行指定任务（后台异步执行，立即返回 accepted）"""
    return task_runner.run_task_async(task_id, trigger="manual")


@app.get("/api/tasks/{task_id}/status")
def task_run_status(task_id: str):
    """查询任务是否正在运行"""
    return {"task_id": task_id, "running": task_runner.is_task_running(task_id)}


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
    conn = sqlite3.connect(str(DB_PATH))

    # 内存无记录时，尝试从数据库获取最近同步时间
    if not last_sync:
        try:
            row = conn.execute("SELECT MAX(_sync_time) FROM eflow_tt").fetchone()
            if row and row[0]:
                last_sync = row[0]
        except Exception:
            pass
    latest_tt = None
    latest_wo = None
    try:
        latest_tt = conn.execute(
            "SELECT MAX(created_time) FROM eflow_tt WHERE created_time IS NOT NULL"
        ).fetchone()[0]
    except Exception:
        pass
    try:
        latest_wo = conn.execute(
            "SELECT MAX(created_time) FROM eflow_wo WHERE created_time IS NOT NULL"
        ).fetchone()[0]
    except Exception:
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
