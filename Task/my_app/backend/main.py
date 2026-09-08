"""数据洞察 SaaS MVP - FastAPI后端主入口

架构优化 Phase 1（2026-08-06）：
- 业务端点已全部下沉至独立 router，本文件仅保留：
  app 创建、CORS、router 注册、startup 事件、静态文件挂载。
- 端点迁移去向：
  /api/tasks*、/api/eflow/*            -> routers/tasks.py
  /api/sp-data/*、/api/data 等 SP 看板  -> routers/sp_dashboard.py
  /api/health、/api/data-source/*、/api/db/info -> routers/system.py
"""
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

# 2026-08-14 修复：backend 继承看门狗 CMD 窗口的控制台，窗口关闭时 CTRL_CLOSE_EVENT
# 导致 uvicorn 与看门狗同时退出（exit_code=1 0xC000013A）。
# 仅在 stdout 已被重定向到文件时脱离控制台（由看门狗托管时），开发模式不受影响。
if sys.platform == "win32" and not sys.stdout.isatty():
    try:
        import ctypes
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

# 确保可以import backend模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.database import Base, engine, DB_PATH, DB_MODE
from backend.models.analysis import AnalysisArchive, UploadedFile
from backend.routers import (
    tables, upload, analysis, gis, tt_wo_dashboard, alarm_dashboard,
    packet_loss_dashboard, battery_dashboard, credentials,
    tasks, sp_dashboard, system,
    incident_overview, ip_trace, nur_dashboard, ms_sla_dashboard,
    site_availability,
    email_recipients,
    realtime_proxy,
    settings,
    cm_flows,
    task_configs,
    email_reports,
    finebi_reports,
    mw_ume,
    portals,
    whatsapp_outbox,
    eflow_qa,
    cxo_dashboard,
    vmax_cxo_dashboard,
    feedback,
)
# 任务配置文件注册表（Settings「任务配置」页签 → 配置文件管理）
from backend.services import task_configs_registry  # noqa: F401  (注册副作用)
from backend.services import task_runner
from backend.database import get_raw_connection

start_time = time.time()

# 冒烟测试/CI 模式：置 MY_APP_DISABLE_SCHEDULER=1 时跳过 APScheduler 启动，
# 避免后台定时任务在验证期间被触发（任务仍会注册，/api/tasks 可正常返回）。
DISABLE_SCHEDULER = os.environ.get("MY_APP_DISABLE_SCHEDULER", "0") == "1"

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
# 云端静态托管(CloudStudio, *.app.workbuddy.link)跨域调用本机后端时使用。
# 也可用环境变量 MY_APP_CORS_ORIGIN_REGEX 覆盖，例如 "^https://.*\.example\.com$"
_ALLOWED_ORIGIN_REGEX = os.environ.get(
    "MY_APP_CORS_ORIGIN_REGEX",
    r"^https://.*\.app\.workbuddy\.link$",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
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
app.include_router(battery_dashboard.router)
app.include_router(credentials.router)
app.include_router(email_recipients.router)
# Phase 1 拆分新增：任务管理 / SP 备件看板 / 系统信息
app.include_router(tasks.router)
app.include_router(sp_dashboard.router)
app.include_router(system.router)
# Incident Overview / IP Trace：从 Unified_Tools 集成（Phase 1 拆分时遗漏挂载，
# 导致 /api/incident-overview/* 与 /api/ip-trace/* 路由不存在、页面取不到数据）
app.include_router(incident_overview.router)
app.include_router(ip_trace.router)
# NUR / SLA 看板（eflow_tt + cm_site_summary 聚合）
app.include_router(nur_dashboard.router)
# MS SLA 看板（MS Contract KPIs / MS WOs SLA 日报数据，ms_sla_dashboard 库）
app.include_router(ms_sla_dashboard.router)
# FME 站点可用率与工单看板（master_site_db + 远端站点级可用性 + eflow_tt）
app.include_router(site_availability.router)
# 实时代理控制（前端「启用实时刷新」开关按需拉起/关闭本地代理 8787/8790）
app.include_router(realtime_proxy.router)
# 全局设置（远程主机等，供「系统设置」页面读写）
app.include_router(settings.router)
# RAN CM 流程/网元配置（Settings「任务配置」页签 -> 网元配置）
app.include_router(cm_flows.router)
# 任务配置文件管理（Settings「任务配置」页签 -> 配置文件管理，通用）
app.include_router(task_configs.router)
# 邮件报告文件（EmailReports 页面：email 类任务生成的最新报告文件列表/下载）
app.include_router(email_reports.router)
# FineBI 报表文件（Task Report Files → FINEBI report 页签：FTP 同步的最新 Excel 列表/下载）
app.include_router(finebi_reports.router)
app.include_router(mw_ume.router)
# 一键门户登录（用默认浏览器打开 ZTE/CCN/iPRAN UME、eFlow、FW(UMC)、VMAX 并自动登录）
app.include_router(portals.router)
# WhatsApp 出图接口（供「WhatsApp 定时发图」Chrome 扩展拉取图片与配置）
app.include_router(whatsapp_outbox.router)
# eFlow 知识库（Task/eflow_Q&A 只读：文档树 / 读取 / 检索）
app.include_router(eflow_qa.router)
# CXO 看板 last-known-good 缓存（cxo_dashboard_cache_sync 定时任务写入，前端三层叠加兜底）
app.include_router(cxo_dashboard.router)
# VMAX CXO 原版视觉看板专用聚合接口（与现有简化版页面并存）
app.include_router(vmax_cxo_dashboard.router)
# 问题登记（用户反馈）：任何内网用户可提交问题，管理侧可筛选/处理/删除
app.include_router(feedback.router)


# ========== 通用任务调度系统 ==========
# 任务定义与注册已迁移至 backend/task_registry.py（P2#8 拆分）：
# 原 _register_all_tasks 336 行 → 声明式 TASK_SPECS + 通用注册循环；
# sync_history 亦由 task_registry 统一维护（旧 eFlow API 兼容）。
from backend.task_registry import sync_history, register_all_tasks


def _register_all_tasks():
    """注册所有可调度的任务（声明式定义见 backend/task_registry.py）"""
    return register_all_tasks(task_runner)

def _acquire_scheduler_lock():
    """单实例调度锁：多 backend 进程并存（如 7038 + 手动启动的 7040/8000 实例）时，
    只有拿到独占锁的实例才启动 APScheduler，其余实例仅提供 HTTP，
    避免同一任务被多个实例同时调度、dedup 后互相误判失败（08-13 main_kpi_sync 事故根因）。

    锁实现：msvcrt.LK_NBLCK 非阻塞独占 db/instance.lock；
    Windows 进程退出时锁自动释放，无需手动清理；
    句柄必须保持存活（存入 app.state），否则 GC 关闭文件会导致锁提前释放。
    """
    import msvcrt
    lock_path = DB_PATH.with_name("instance.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(lock_path, "a+", encoding="utf-8")
    except Exception as e:
        print(f"[startup] 无法创建锁文件 {lock_path}: {e}，按无锁模式启动调度器")
        return None, True
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        f.seek(0, 2)
        f.write(f"{os.getpid()} {datetime.now().isoformat()}\n")
        f.flush()
        print(f"[startup] 已获得调度器单实例锁 {lock_path} (pid={os.getpid()})")
        return f, True
    except OSError:
        print(f"[startup] 单实例锁被占用 {lock_path}：本实例仅提供 HTTP，不启动调度器")
        return f, False


def _init_db_with_retry(max_retries: int = 12, base_wait: int = 1, max_wait: int = 8):
    """db 初始化可能因后台进程(Windows Search 索引 / 杀软实时扫描)临时锁住
    app.db 而失败，这里加重试穿过锁释放窗口，避免后端启动卡死。

    退避策略：指数退避（1s, 2s, 4s, 8s...），快速穿过短暂锁窗口；
    max_wait 封顶，避免最坏情况等待过长。
    """
    import sqlite3
    last_err = None
    for i in range(1, max_retries + 1):
        try:
            if DB_MODE == "sqlite":
                # 创建ORM模型表（sqlite 模式由 create_all 管理；pg 模式交给 Alembic，风险 11）
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
                    # 初始化调度配置表
                    task_runner._init_schedule_table()
            # pg 模式：表结构由 Alembic 管理，此处不建表（避免与 Alembic 抢建，风险 11）
            return
        except Exception as e:
            last_err = e
            delay = min(base_wait * (2 ** (i - 1)), max_wait)
            print(f"[startup] db 初始化遇锁({type(e).__name__})，{delay}s 后重试 ({i}/{max_retries}): {e}")
            time.sleep(delay)
    raise last_err or RuntimeError("db init failed after retries")


@app.on_event("startup")
async def startup_event():
    """启动时创建必要的表和索引（app.db 可能被后台索引/杀软临时锁住，加重试穿过）"""
    _init_db_with_retry()

    # 单实例锁：拿不到锁的进程不启动调度器（仅 HTTP），避免双实例任务双份执行
    _lock_file, _got_lock = _acquire_scheduler_lock()
    app.state.scheduler_lock_file = _lock_file

    # 注册所有任务并启动调度器
    _register_all_tasks()
    if DISABLE_SCHEDULER:
        print("[startup] MY_APP_DISABLE_SCHEDULER=1: skip APScheduler start (smoke test mode)")
    elif not _got_lock:
        print("[startup] 单实例锁被占用：跳过调度器启动（任务由持锁实例调度，避免双份执行）")
    else:
        task_runner.schedule_all_tasks()
        task_runner.start_scheduler()

    elapsed = time.time() - start_time
    print(f"服务启动完成，耗时: {elapsed:.2f}秒")
    print(f"数据库: {DB_PATH}")
    print(f"已注册 {len(task_runner.list_tasks())} 个定时任务")

    # 自动拉起实时代理（8787 FMS / 8790 VMAX），让 CXO / Alarm 看板打开即有实时数据。
    # 用线程异步执行，不阻塞 startup；代理以 DETACHED 方式运行，backend 重启不会误杀。
    import threading
    from backend.services import realtime_proxy_ctl as _ctl
    def _auto_start_proxies():
        try:
            results = _ctl.ensure_all()
            print(f"[startup] 实时代理自动启动: {results}")
        except Exception as e:
            print(f"[startup] 实时代理自动启动失败（非致命）: {e}")
    threading.Thread(target=_auto_start_proxies, daemon=True).start()


# 提供前端静态文件（生产环境）
# 注意：必须校验 assets 目录真实存在，否则 StaticFiles 会因目录缺失而抛出
# RuntimeError，导致整个 uvicorn 应用导入失败、后端无法启动（开发模式下前端由 Vite 提供，无需此挂载）。
# 生产前端构建产物位于 _fe_dist（vite.config.ts 的 build.outDir，与 frontend/dist 同内容但在 IDE 监视树外，避免 EPERM）。
# nginx(:80)/myapp → vite preview(:7090) → _fe_dist；直连 7038 的截图/邮件工具也走这里，保持两者一致。
frontend_dist = Path(__file__).parent.parent.parent / "_fe_dist"

# index.html 是 SPA 入口，禁止浏览器启发式缓存：否则重新部署后浏览器仍会引用
# 旧 index.html -> 旧 hash JS，导致页面停留在旧版逻辑（如图例计数全 0、
# 时间窗口筛选失效）。带 hash 的 assets/ 资源不受影响，仍可长期缓存。
_INDEX_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _index_response() -> FileResponse:
    return FileResponse(frontend_dist / "index.html", headers=_INDEX_NO_CACHE_HEADERS)


if (frontend_dist / "assets").is_dir():
    # 根路径挂载（兼容旧 /assets 引用）
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static")
    # 与 Vite base:'/myapp/' 对齐：直连 7038（截图/无 nginx 场景）时，
    # 浏览器按 /myapp/assets/* 拉取 JS/CSS、按 /myapp 拉取 SPA，否则会回退成
    # index.html 导致模块加载失败、页面白屏。
    app.mount("/myapp/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static-myapp")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = frontend_dist / full_path
        if full_path.startswith("myapp/assets/"):
            # 已被 /myapp/assets 挂载处理，这里只兜底（理论上不会命中）
            return _index_response()
        if file_path.is_file():
            # 独立 HTML（如 mw_ume_topology.html / ip_trace.html）频繁热更新，禁止缓存，
            # 避免部署后 iframe 仍复用旧版 HTML 导致用户看不到新增按钮/逻辑。
            headers = _INDEX_NO_CACHE_HEADERS if file_path.suffix.lower() == ".html" else None
            return FileResponse(file_path, headers=headers)
        return _index_response()
else:
    print("WARNING: frontend/dist/assets 不存在，跳过静态资源挂载（开发模式由 Vite 提供前端，不影响 API）")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
