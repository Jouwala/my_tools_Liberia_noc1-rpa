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

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path

logger = logging.getLogger(__name__)

from backend.database import Base, engine, DB_PATH, DB_MODE
from backend.models.analysis import AnalysisArchive, UploadedFile
from backend.routers import (
    tables, upload, analysis, gis, tt_wo_dashboard, alarm_dashboard,
    wo_dashboard,
    packet_loss_dashboard, battery_dashboard, credentials,
    tasks, sp_dashboard, sp_material_summary, sp_details, sp_report, system,
    incident_overview, ip_trace, nur_dashboard, ms_sla_dashboard, ms_kpi_report,
    site_availability,
    avail_ms,
    avail_flm,
    ran_cells_kpi,
    bp_report,
    ume_in_kpi,
    ume_in_screen,
    email_recipients,
    realtime_proxy,
    settings,
    cm_flows,
    task_configs,
    email_reports,
    finebi_reports,
    mw_ume,
    mw_links,
    portals,
    whatsapp_outbox,
    tt_alert_whatsapp,
    eflow_qa,
    eflow_flow,
    cxo_dashboard,
    vmax_cxo_dashboard,
    vmax_cxo_daily,
    data_agent,
    olib_soc_dashboard,
    feedback,
    ui_config,
    portal_qc,
    portal_catalog,
    cn_kpi,
    native_boards,
    repeat_site_down,
    fme_ranking,
    cr_analysis,
    pm_analysis,
)
# 任务配置文件注册表（Settings「任务配置」页签 → 配置文件管理）
from backend.services import task_configs_registry  # noqa: F401  (注册副作用)
from backend.services import task_runner
from backend.services import portal_auth  # noqa: F401  (会话路由 + current_user 供鉴权中间件)
from backend import auth_switch  # noqa: F401  (日常开发免登录总开关，见 backend/auth_switch.py)
from backend.database import get_raw_connection

start_time = time.time()

# 冒烟测试/CI 模式：置 MY_APP_DISABLE_SCHEDULER=1 时跳过 APScheduler 启动，
# 避免后台定时任务在验证期间被触发（任务仍会注册，/api/tasks 可正常返回）。
DISABLE_SCHEDULER = os.environ.get("MY_APP_DISABLE_SCHEDULER", "0") == "1"

# 交互式 API 文档（Swagger UI / ReDoc / OpenAPI schema）默认关闭。
# 原因：FastAPI 这三条路径（/docs、/redoc、/openapi.json）是**框架内建**的，
# 不经过 /api/ 前缀，因此 require_session_middleware 的
# `if not path.startswith("/api/")` 分支会直接放行 —— 加 _PUBLIC_API 白名单
# 也管不到它们。实测 /openapi.json 会公开返回 189KB、223 条 API 路径的完整
# 攻击面地图（含 /api/tables/{table_name}/data 等），对未登录访问者可见。
# 需要内网调试时显式置 MY_APP_ENABLE_DOCS=1 打开，生产保持默认关闭。
_ENABLE_DOCS = os.environ.get("MY_APP_ENABLE_DOCS", "0") == "1"

app = FastAPI(
    title="数据洞察 SaaS MVP",
    description="上传工作簿、自动识别字段与质量问题、生成多维图表和结论，GIS展示与下钻，分析归档检索",
    version="1.0.0",
    docs_url="/docs" if _ENABLE_DOCS else None,
    redoc_url="/redoc" if _ENABLE_DOCS else None,
    openapi_url="/openapi.json" if _ENABLE_DOCS else None,
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
app.include_router(wo_dashboard.router)
app.include_router(alarm_dashboard.router)
app.include_router(packet_loss_dashboard.router)
app.include_router(battery_dashboard.router)
app.include_router(credentials.router)
app.include_router(email_recipients.router)
# Phase 1 拆分新增：任务管理 / SP 备件看板 / 系统信息
app.include_router(tasks.router)
app.include_router(sp_dashboard.router)
# SP 物料库存/消耗统计汇总（WH/DOP 报表模板，见 routers/sp_material_summary.py）
app.include_router(sp_material_summary.router)
# SP 备件明细报表（page=sp_details；数据源 = sp_email_details 任务生成的合并工作簿，
# 见 routers/sp_details.py 与 services/sp_details_service.py）
app.include_router(sp_details.router)
# SP 备件 / 耗材汇总报表（page=sp_report / com_report；数据源 = sp_report_generate 任务
# 生成的汇总工作簿，见 routers/sp_report.py 与 services/sp_report_service.py）
app.include_router(sp_report.router)
app.include_router(system.router)
# Incident Overview / IP Trace：从 Unified_Tools 集成（Phase 1 拆分时遗漏挂载，
# 导致 /api/incident-overview/* 与 /api/ip-trace/* 路由不存在、页面取不到数据）
app.include_router(incident_overview.router)
app.include_router(ip_trace.router)
# NUR / SLA 看板（eflow_tt + cm_site_summary 聚合）
app.include_router(nur_dashboard.router)
# MS SLA 看板（MS Contract KPIs / MS WOs SLA 日报数据，ms_sla_dashboard 库）
app.include_router(ms_sla_dashboard.router)
# MS Contract KPIs / WOs SLA 报表（page=ms_contract_kpi / ms_wo_sla；数据源 = ms_sla_full /
# kpi_ms_wo_sla 任务产出的工作簿本体，见 routers/ms_kpi_report.py）
app.include_router(ms_kpi_report.router)
# FME 站点可用率与工单看板（master_site_db + 远端站点级可用性 + eflow_tt）
app.include_router(site_availability.router)
# 可用率多维矩阵（page=avail_ms；读本机派生库 data/avail_recon.sqlite3，
# 区域/制式/站点类型 × 日/周/月三档，口径见 services/avail_ms_service.py）
app.include_router(avail_ms.router)
# FLM 可用率（page=avail_flm；同一派生库，改成「区域为行」的两张表 + 页面级 TT 列表，
# 口径见 services/avail_flm_service.py 顶部说明）
app.include_router(avail_flm.router)
# RAN 2G/3G/4G Cells KPI 看板（小区级可用率，达标值 99.65%）
app.include_router(ran_cells_kpi.router)
# BP Report 劣化小区报告（page=bp_report；读本机派生库 data/bp_report.sqlite3，
# Cluster 来自 Excel 的 BP Cells List、指标由 RAN_UME 更新，口径见 services/bp_caliber.py）
app.include_router(bp_report.router)
app.include_router(ume_in_kpi.router)
# UME 割接大屏「实时还原」：后端代理 UME 大屏鉴权+取数，页面任意时刻打开都是当前值
app.include_router(ume_in_screen.router)
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
app.include_router(mw_links.router)
# 一键门户登录（用默认浏览器打开 ZTE/CCN/iPRAN UME、eFlow、FW(UMC)、VMAX 并自动登录）
app.include_router(portals.router)
# WhatsApp 出图接口（供「WhatsApp 定时发图」Chrome 扩展拉取图片与配置）
app.include_router(whatsapp_outbox.router)
# TT 告警文本作业接口（eFlow P1 未清除单 → WhatsApp，供扩展认领/回报）
app.include_router(tt_alert_whatsapp.router)
# eFlow 知识库（Task/eflow_Q&A 只读：文档树 / 读取 / 检索）
app.include_router(eflow_qa.router)
# eFlow 全流程查询（输入告警/TT → 规则驱动的流程图 + 该单实际路径高亮，只读）
app.include_router(eflow_flow.router)
# CXO 看板 last-known-good 缓存（cxo_dashboard_cache_sync 定时任务写入，前端三层叠加兜底）
app.include_router(cxo_dashboard.router)
# VMAX CXO 原版视觉看板专用聚合接口（与现有简化版页面并存）
app.include_router(vmax_cxo_dashboard.router)
# VMAX CXO 天粒度看板（vmaxCxoDashboard_Daily）专用只读接口：
# 独立数据源 data/vmax_cxo_daily/daily.json，由新任务 vmax_cxo_daily_sync 写入，
# 与上面两个 CXO 接口/页面完全隔离（新增，不影响现有看板）
app.include_router(vmax_cxo_daily.router)
# VMAX 90 天经营看板（vmaxCxoDashboard_90Days）专用只读接口：
# 数据源 data/olib_soc_report/olib_soc_report.sqlite3 的 daily_kpi 表（数仓 GBase 直连取数，
# 任务 olib_soc_kpi_daily_sync 每日增量 / olib_soc_vmax_report 每月全量），与上面两个
# CXO 看板的数据源互不影响。
app.include_router(olib_soc_dashboard.router)
# 问题登记（用户反馈）：任何内网用户可提交问题，管理侧可筛选/处理/删除
app.include_router(feedback.router)
# 界面配置（侧栏菜单结构）：全局共享一份，仅本机可改（见 routers/ui_config.py）
app.include_router(ui_config.router)
# uniplam 门户鉴权适配：/api/auth/portal-login、/api/auth/logout、/api/auth/me（见 services/portal_auth.py）
app.include_router(portal_auth.router)
# MsPortal 静态门户「Quality Control」面板的数据库统计与明细下钻（只读，见 routers/portal_qc.py）
app.include_router(portal_qc.router)
# MsPortal 静态门户的看板目录：全局共享一份（所有人读同一份），仅本机可增删改
# （见 routers/portal_catalog.py）。未登录访客读不到——刻意不进 _PUBLIC_API 白名单。
app.include_router(portal_catalog.router)
# CN KPI 看板：原 my-finebi「CN KPI」看板原生重建（18 组件，经远端只读 SQL API 取数，
# 不依赖 my-finebi 进程）。数据源/口径见 services/cn_kpi_service.py 顶部说明。
app.include_router(cn_kpi.router)
# 原生看板（泛化版）：my-finebi 其余全部看板（IP RAN Metro Ring / 可用率 / 2G-3G-4G KPI /
# MTTR / CM / 备件 / Progress 等 17 个）统一由一套引擎驱动，经远端只读 SQL API 取数，
# 不依赖 my-finebi 进程；支持时间窗口过滤与 Excel 导出。
# 数据源/口径见 services/dashboard_service.py 顶部说明，看板定义见 native_catalog.py。
app.include_router(native_boards.router)
# Daily repeat site-down count dashboard (eflow_tt + eflow_site).
app.include_router(repeat_site_down.router)
# FME 工程师 WO / 站点可用率排名（master_site_db + eflow_wo + 站点可用率服务）
app.include_router(fme_ranking.router)
# CR 变更分析：按 change_category 看变更计划的排期与执行情况（数据源 eflow_cr）。
# 口径（终态词表、按时/延期判定、概览与下钻如何共用同一份 WHERE）见
# services/cr_analysis_service.py 的模块 docstring。
app.include_router(cr_analysis.router)
# PM 执行分析：按 PM 计划 (pmp_no) 看预防性维护工单的完成与超期情况（数据源 eflow_pm）。
# 口径（字段名陷阱、真实流程顺序、pmt_overdue 语义、概览与下钻如何共用同一份 WHERE）
# 见 services/pm_caliber.py 的模块 docstring。
app.include_router(pm_analysis.router)

# Data Agent（只读 NL2SQL + 告警归因）：探索性副驾，不参与任何定时报表/看板数字的产出。
# 定位、护栏与风险清单见 docs/DATA_AGENT_EVALUATION.md。
# 所有 SQL 经 services/sql_guard.py 白名单校验；本路由不含任何写接口。
app.include_router(data_agent.router)


# ========== 统一门户鉴权中间件 ==========
# 适配 uniplam 门户用户鉴权：远程访问数据接口需登录（会话 Cookie 或门户深链换的
# 会话），未登录返回 401；本机回环（内部调度/看门狗/同机脚本）放行，避免破坏
# 定时任务。放行清单集中维护，见 _PUBLIC_API。
_PUBLIC_API = (
    "/api/auth/",          # 登录/注销/会话查询（引导流程必须全开）
    "/api/health",         # 健康检查
    "/api/ui/menu-layout", # 侧栏菜单结构只读（首屏渲染依赖，且 PUT/DELETE 另有 require_protected）
    # 浏览器扩展消费由已登录网页签发的 45 秒一次性票据；接口本身不接受 Cookie 以外的
    # 身份替代物，票据随机且单次失效，故只能放行此精确子路径。
    "/api/portals/client-login/consume",
)


@app.middleware("http")
async def require_session_middleware(request: Request, call_next):
    # 非 API 一律放行（前端静态资源）
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    # CORS 预检放行（CORSMiddleware 在内层处理）
    if request.method == "OPTIONS":
        return await call_next(request)
    # 日常开发免登录总开关（见 backend/auth_switch.py）：整体放行，不再要求会话。
    # 默认开启鉴权，故本分支不影响现有行为；生产环境由 auth_switch 的生产保护兜底。
    if auth_switch.is_auth_bypass():
        return await call_next(request)
    # 公开路径放行
    if request.url.path.startswith(_PUBLIC_API):
        return await call_next(request)
    # 本机回环放行（内部调度/脚本/看门狗不受浏览器鉴权约束）
    if portal_auth.client_is_local(request):
        return await call_next(request)
    # 其余一律要求有效会话
    if portal_auth.current_user(request) is not None:
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "未登录：请通过统一门户登录"})


# ========== 全局异常处理器 ==========
# 此前本文件 0 个 exception_handler，未捕获异常只有 Starlette 默认输出：
# 响应体不含 traceback，排查线上问题时只能靠日志时间戳对齐，成本高。
# 这里补三个处理器，统一 JSON 形状 + 保留诊断上下文：
#   1) 未捕获异常 → 500，返回 request_id 供日志检索（不泄露堆栈给客户端）
#   2) 请求校验失败 → 422，返回 FastAPI 原始 errors 结构（兼容既有前端解析）
#   3) HTTPException → 沿用其 status/detail，但统一补 request_id
# 注意：Starlette 按异常类型精确匹配，注册顺序不影响结果；处理器只要在
# app 创建之后定义即可，无需早于 router 注册。

def _new_request_id() -> str:
    """生成短请求 ID，用于把客户端报错与服务端日志串起来。"""
    return uuid.uuid4().hex[:12]


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求参数校验失败：保持 FastAPI 默认 422 + errors 结构（前端已依赖）。"""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": _new_request_id()},
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    """业务主动抛出的 HTTPException：保留原 status/detail，仅补 request_id。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": _new_request_id()},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """兜底：未捕获异常返回 500。

    诊断上下文（异常类型、路径、方法、request_id）进日志；响应体只给
    request_id 与一句中文提示，**不回传堆栈**，避免泄露内网路径与库结构。
    """
    rid = _new_request_id()
    logger.error(
        "[unhandled] rid=%s %s %s -> %s: %s",
        rid, request.method, request.url.path, type(exc).__name__, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试", "request_id": rid},
    )


# ========== 通用任务调度系统 ==========
# 任务定义与注册已迁移至 backend/task_registry.py（P2#8 拆分）：
# 原 _register_all_tasks 336 行 → 声明式 TASK_SPECS + 通用注册循环；
# sync_history 亦由 task_registry 统一维护（旧 eFlow API 兼容）。
from backend.task_registry import sync_history, register_all_tasks, preload_common_deps


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
    # 启动期串行预热公共重依赖（2026-09-10 修复）：QUEUE_ENABLED=0 时定时/手动触发
    # 都经 _execute_task 在本进程内以【线程】并发执行任务，多线程同时首次 import
    # requests 等重依赖会撞 CPython import 竞态并残留半成品模块。提前串行导入消除窗口。
    try:
        _ok, _failed = preload_common_deps()
        print(f"[startup] 公共依赖预热完成：{len(_ok)} 个成功"
              + (f"，{len(_failed)} 个失败: {'; '.join(_failed)}" if _failed else ""))
    except Exception as _e:
        print(f"[startup] 公共依赖预热异常（不影响启动）: {_e}")
    # TT 快速分析依赖的知识库分析模块（eflow_Q&A/tools/inspect_tt.py）启动期预热：
    # 页面一进就并发打 inspect-tt / tt-ai / tt-ume-suggestion，把首次动态加载放在
    # 启动期串行做掉，避免「重启后第一次点分析」才首载（并发竞态 + 首击变慢）。
    try:
        from backend.routers import eflow_qa as _eflow_qa
        _warm_err = _eflow_qa.warmup()
        print("[startup] TT 分析模块预热完成" if not _warm_err
              else f"[startup] TT 分析模块预热失败（不影响启动）: {_warm_err}")
    except Exception as _e:
        print(f"[startup] TT 分析模块预热异常（不影响启动）: {_e}")
    # 原生看板缓存预热：这些看板源数据天粒度更新，一次冷取数要 4~6 秒
    # （成本几乎全在行数：metro_ring 8 组件共 4.4 万行）。后台串行预热，
    # 不阻塞 startup；磁盘缓存命中时几乎无事可做（看门狗重启后即属此列）。
    try:
        from backend.services import dashboard_service as _nb_svc
        _pw = _nb_svc.prewarm()
        _pending = _pw["pending"]
        if not _pending:
            print("[startup] 原生看板缓存预热：全部命中，无需回源")
        else:
            _show = ", ".join(_pending[:5]) + ("..." if len(_pending) > 5 else "")
            print(f"[startup] 原生看板缓存预热：{len(_pending)} 个待回源 -> {_show}")
    except Exception as _e:
        print(f"[startup] 原生看板缓存预热异常（不影响启动）: {_e}")

    # NUR/SLA 看板基础数据预热：冷路径首个请求要 ~3.9s（建基础表 + 首次连库 +
    # 拉 FTP 排除名单）。后台预热后用户首个请求只剩计算（~0.8s）。
    try:
        from backend.services import nur_calc as _nur
        _nur.warmup()
        print("[startup] NUR 看板基础数据预热已启动（后台）")
    except Exception as _e:
        print(f"[startup] NUR 看板预热异常（不影响启动）: {_e}")

    # SP 备件明细看板预热：首次要整份解析合并工作簿（实测 4.7s），
    # 后端重启后缓存为空，冷成本会落在第一个打开该页的用户头上。
    try:
        from backend.services import sp_details_service as _spd
        _spd.warmup()
        print("[startup] SP 备件明细看板预热已启动（后台）")
    except Exception as _e:
        print(f"[startup] SP 备件明细看板预热异常（不影响启动）: {_e}")

    # 丢包看板总览预热：daily_trend/top_sites 要扫 7 天+24 小时读数（约 2s）。
    try:
        from backend.routers import packet_loss_dashboard as _pl
        _pl.warmup()
        print("[startup] 丢包看板总览预热已启动（后台）")
    except Exception as _e:
        print(f"[startup] 丢包看板预热异常（不影响启动）: {_e}")

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
