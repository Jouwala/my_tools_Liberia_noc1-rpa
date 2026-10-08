"""定时任务注册表 —— 从 main.py 拆分出的数据驱动任务定义（P2#8 重构）

设计说明：
- 原 `main.py::_register_all_tasks`（336 行、21 个任务）改为「定义与注册分离」：
  本模块维护声明式任务清单 `TASK_SPECS`，`register_all_tasks()` 统一注册。
- 业务函数采用**懒加载**（调用时才 import），避免启动期导入重型服务模块
  （UME 登录、playwright、exchangelib 等），保持后端快速启动。
- 新增任务只需在 `TASK_SPECS` 追加一条记录，无需改动注册逻辑。
"""
import importlib
import logging
import sys
import threading

logger = logging.getLogger(__name__)

# 兼容旧 eFlow API 的同步历史（main.py 的 /api/eflow/status 会读取）
sync_history = []


# ========== 并发导入保护（2026-09-10 事故修复）==========
# 事故：worker 进程 QUEUE_ENABLED=0（MY_APP_TASK_QUEUE 未设置，start_hidden.ps1 未导出）
# 时，task_runner.run_task_async 会走 threading.Thread 分支，在【同一个进程内并发】
# 执行多个任务。多个线程同时首次 import 同一重量级依赖（典型 requests）时，会撞上
# CPython 的 import 竞态：
#   ImportError: cannot import name 'HTTPAdapter' from partially initialized
#   module 'requests.adapters' (most likely due to a circular import)
# 失败方还会把半成品模块残留在 sys.modules，使同进程内后续导入持续失败，且症状会
# 演变（module 'requests' has no attribute 'exceptions'）。
# 实测时间线（2026-09-10 09:35:01）：auto_retry 一次投递 eflow_sync / ipran_kpi_sync /
# mailbox_cleanup，三者被同一 worker 进程内 3 个线程同时拉起，抢到导入锁的
# eflow_sync 成功，另两个失败。
# 修复：① 任务模块 import 走全局锁串行化；② 失败时清理残留并重试一次（自愈）；
#       ③ worker 启动期用 preload_common_deps() 串行预热公共重依赖，从根上消除
#          "运行期首次导入"的并发窗口。
_IMPORT_LOCK = threading.RLock()

# 判定"半成品"的哨兵属性：这些模块正常初始化完成后必定具备对应属性。
_HEALTH_CHECKS = {
    "requests": ("exceptions", "adapters"),
}


def _purge_modules(root: str) -> int:
    """从 sys.modules 移除 root 及其全部子模块（含半成品残留）。"""
    names = [m for m in list(sys.modules) if m == root or m.startswith(root + ".")]
    for m in names:
        sys.modules.pop(m, None)
    return len(names)


def _repair_broken_modules() -> list:
    """清理处于"半成品"状态的模块，使其下次可被完整重新导入。"""
    repaired = []
    for root, attrs in _HEALTH_CHECKS.items():
        mod = sys.modules.get(root)
        if mod is None:
            continue
        missing = [a for a in attrs if not hasattr(mod, a)]
        if missing:
            n = _purge_modules(root)
            repaired.append(f"{root}(missing={','.join(missing)}, purged={n})")
    return repaired


def safe_import(module_path: str):
    """串行化 + 自愈的模块导入（并发执行任务时避免 import 竞态）。

    锁内做两件事：① 修掉上一次失败留下的半成品模块；② 导入目标模块。
    这样即便前一次已被污染，下一次调用也能自愈。
    """
    with _IMPORT_LOCK:
        repaired = _repair_broken_modules()
        if repaired:
            logger.warning(f"检测到半成品模块残留并已清理: {'; '.join(repaired)}")
        return importlib.import_module(module_path)


def preload_common_deps() -> tuple:
    """启动期预热重量级公共依赖（单线程串行）。

    把"运行期首次导入"提前到"启动期串行导入"，消除多个任务线程并发首次导入
    同一模块的窗口。失败不阻断启动，只告警并返回明细供排查。
    """
    targets = [
        "requests",
        "requests.adapters",
        "requests.exceptions",
        "urllib3",
        "certifi",
        "exchangelib",
        "openpyxl",
        "pandas",
    ]
    ok, failed = [], []
    with _IMPORT_LOCK:
        for name in targets:
            try:
                importlib.import_module(name)
                ok.append(name)
            except BaseException as e:  # noqa: BLE001
                failed.append(f"{name}({type(e).__name__}: {e})")
    if failed:
        logger.warning(f"公共依赖预热部分失败: {'; '.join(failed)}")
    return ok, failed


# ========== eFlow 同步任务函数（含历史记录维护，直接引用非懒加载） ==========

def scheduled_eflow_sync():
    """定时 eFlow API 数据同步任务（兼容旧接口）"""
    from backend.services.sync_from_eflow_api import sync_from_eflow_api
    logger.info("定时 eFlow API 同步开始")
    result = sync_from_eflow_api(mode="delta")
    sync_history.append(result)
    while len(sync_history) > 20:
        sync_history.pop(0)
    logger.info(f"eFlow 同步完成: success={result['success']}, tables={result['tables_synced']}")
    return result


def scheduled_eflow_sync_full():
    """每日 eFlow 全量兜底同步：拉全量窗口，补齐增量遗漏并刷新报告"""
    from backend.services.sync_from_eflow_api import sync_from_eflow_api
    logger.info("每日 eFlow 全量兜底同步开始")
    result = sync_from_eflow_api(mode="full")
    logger.info(f"eFlow 全量同步完成: success={result['success']}, tables={result['tables_synced']}")
    return result


def _run_eflow_active_alarm():
    """eFlow 实时告警同步（仅记录条数摘要，避免 ~300KB 告警列表写入执行日志）"""
    from backend.services.eflow_api_client import fetch_and_save_active_alarm
    res = fetch_and_save_active_alarm()
    rows = res.get("realtime_alarm", []) if isinstance(res, dict) else []
    return {"realtime_alarm_count": len(rows)}


def _run_eflow_history_alarm():
    """eFlow 历史告警同步（仅记录条数摘要，避免完整历史告警列表写入执行日志）"""
    from backend.services.eflow_api_client import fetch_and_save_history_alarm
    res = fetch_and_save_history_alarm()
    rows = res.get("history_alarm", []) if isinstance(res, dict) else []
    return {"history_alarm_count": len(rows)}


def _lazy_loader(module_path: str, func_name: str):
    """生成懒加载包装：调用时才 import 目标模块函数。

    import 走 safe_import（全局锁 + 自愈），避免多任务线程并发首次导入
    同一模块时的 import 竞态（详见文件上方 _IMPORT_LOCK 说明）。
    """
    def _run():
        module = safe_import(module_path)
        return getattr(module, func_name)()
    _run.__name__ = f"_run_{func_name}"
    return _run


# ========== 声明式任务清单 ==========
# 每条记录二选一：
#   func:   直接可调用的函数（用于需要特殊包装的任务）
#   loader: (module_path, func_name) 元组，注册时自动生成懒加载包装

TASK_SPECS = [
    # 1. eFlow API 数据同步（每小时第22分钟）
    dict(task_id="eflow_sync", name="eFlow 数据同步", name_en="eFlow Data Sync",
         func=scheduled_eflow_sync,
         description="从 ZTE eFlow API 获取 TT/WO/CR/PM/Site/Person 数据",
         description_en="Fetch TT/WO/CR/PM/Site/Person data from ZTE eFlow API",
         default_cron="22 * * * *", category="eflow"),

    # 2. eFlow 每日全量兜底（每天凌晨1点）
    dict(task_id="eflow_sync_full", name="eFlow 每日全量同步", name_en="eFlow Daily Full Sync",
         func=scheduled_eflow_sync_full,
         description="eFlow 全量兜底同步：拉取全量窗口（默认自 2026-01-01），补齐增量遗漏并刷新报告",
         description_en="eFlow daily full backfill sync (full window), refresh reports",
         default_cron="0 1 * * *", category="eflow"),

    # 3. RAN UME PM 数据 + Availability 报表（每天凌晨2点）
    dict(task_id="ran_ume_daily", name="RAN UME 日报", name_en="RAN UME Daily Report",
         loader=("backend.services.ran_ume_service", "run_ran_ume_full_task"),
         description="RAN UME PM 数据获取 + Daily Availability KPI 报表生成 + FTP 上传",
         description_en="RAN UME PM data fetch + Daily Availability KPI report generation + FTP upload",
         default_cron="0 2 * * *", category="ran_ume"),

    # 4. Site Outage 截图（每天凌晨1点）
    dict(task_id="site_outage_screenshot", name="Site Outage 截图", name_en="Site Outage Screenshot",
         loader=("backend.services.site_outage_service", "run_site_outage_screenshot"),
         description="Site Down Dashboard 自动截图（ERA/Regular/ALL）",
         description_en="Auto screenshot of Site Down Dashboard (ERA/Regular/ALL)",
         default_cron="0 1 * * *", category="site_outage"),

    # 5. WhatsApp 发送（每天凌晨3点，在截图之后）
    dict(task_id="whatsapp_send", name="WhatsApp 消息发送", name_en="WhatsApp Message Send",
         loader=("backend.services.whatsapp_service", "run_whatsapp_send"),
         description="发送 Site Outage 截图和文件到 WhatsApp 群组",
         description_en="Send Site Outage screenshots and files to WhatsApp groups",
         default_cron="0 3 * * *", category="whatsapp"),

    # 5b. WhatsApp 发送（扩展版）：投递作业并等待浏览器扩展在已登录的 WhatsApp Web 标签页中发送。
    #     与上面的 Playwright 版并存，互不影响；扩展见 Task/my_app/whatsapp_sender_extension。
    dict(task_id="whatsapp_send_ext", name="WhatsApp 消息发送（扩展）", name_en="WhatsApp Message Send (Extension)",
         loader=("backend.services.whatsapp_ext_service", "run_whatsapp_send_ext"),
         description="投递发送作业，由浏览器扩展在已登录的 WhatsApp Web 中发送 Site Outage 截图",
         description_en="Dispatch a send job; a browser extension sends Site Outage screenshots in the logged-in WhatsApp Web",
         default_cron="0 3 * * *", category="whatsapp"),

    # 5d. WhatsApp 发送（Baileys 通道）—— 第三种实现，与 Playwright / 扩展版**并行**。
    #     走 whatsapp-kb-bot/src/notify.js 进程（Baileys 协议直发，与聊天机器人/P1告警
    #     推送共用 auth-notify/ 凭据），回执是服务端 message id，**不是猜的**。
    #     与 whatsapp_send（Playwright 0 3 * * *）错开 1 小时避免同时投递双份。
    #     ⚠️ 默认不自动启用（enabled=False）—— 业务侧首次启用前必须：
    #       1) 确认 whatsapp-kb-bot notify 进程在跑、auth-notify/ 凭据有效
    #       2) 在「任务管理」页手动启用（同步把 enabled=True 落库）
    #     原因：Baileys 违反 WhatsApp ToS，启用后号码可能被封，必须走人工审批路径。
    #     已被主开关豁免（见 MASTER_SWITCH_EXEMPT_IDS），批量切换不参与。
    dict(task_id="whatsapp_send_baileys", name="WhatsApp 消息发送（Baileys）", name_en="WhatsApp Message Send (Baileys)",
         loader=("backend.services.whatsapp_send_baileys_service", "run_whatsapp_send_baileys"),
         description="通过 Baileys 协议直发 Site Outage 截图与文档到 WhatsApp 群组（与 Playwright/扩展版并行；默认禁用，需在「任务管理」页手动启用）",
         description_en="Dispatch Site Outage images and documents to WhatsApp groups via the Baileys protocol (parallel to Playwright/extension; disabled by default — enable manually from the Task Manager page)",
         default_cron="0 4 * * *", category="whatsapp",
         enabled=False),

    # 5c. eFlow P1 告警 → WhatsApp（每 5 分钟，触发制，2026-10-05 机制切换）。
    #     触发：扫 realtime_alarm（eflow_active_alarm 每 5 分钟同步）里「带 TT +
    #     告警升起时间在触发窗口内 + 告警码白名单」的告警；随后**实时回 eFlow 查单**
    #     （fetch_tt_live_batch）拿最新级别/更新时间/清除状态，不再受 eflow_tt
    #     每小时才落库的时延制约（旧机制端到端 45~75 分钟 → 现在分钟级）。
    #     重报：距最近一次工单更新 ≥20 分钟（停滞）且距上次成功发送 ≥20 分钟（冷却）
    #     → 再次通报（带 REMINDER 横幅）；工单有更新只刷新跟踪字段不打扰群里；
    #     告警清除（alarm_clear_time 非空 / 从 realtime_alarm 消失）自然止损。
    #     落库 eflow_tt_whatsapp_alert_log：send_status（发没发过）/ send_count
    #     （发送几次）/ last_known_update_time / last_alarm_seen_time（恢复通知的数据基础）。
    #     发送走 Baileys 推送进程（whatsapp-kb-bot/src/notify.js），投递前查心跳。
    #
    #     ⚠️ cron 相位是 `2-59/5` 而**不是** `*/5`（2026-10-05 定）：本任务的触发源
    #     `eflow_active_alarm` 跑 `*/5`，若两者同相位（都在 :00/:05/... 起跑），本任务
    #     有概率读到**上一轮**的 realtime_alarm（同步那 0.3~0.5s 还没写完），
    #     白等一个周期。错开 2 分钟起跑，保证每次都读到刚同步完的数据。
    #     这一相位选择与整点并发拥挤无关，只是为了让「同步 → 推送」的先后关系确定；
    #     调度器在整点会丢触发（见 `task_runner._scheduled_run` 的投递拒绝），
    #     那是全平台共性问题，不靠本任务的相位解决。
    dict(task_id="tt_alarm_whatsapp_alert", name="eFlow P1 告警 WhatsApp 推送",
         name_en="eFlow P1 Alarm WhatsApp Push",
         loader=("backend.services.tt_alarm_whatsapp_service", "run_tt_alarm_whatsapp_alert"),
         description="每 5 分钟扫 realtime_alarm 触发（带 TT + 窗口内 + 告警码白名单），实时查 eFlow 拿最新更新时间；P1 单首推即发，之后双档重报（自上次发送后工单无更新满 10 分钟催报、有更新满 30 分钟才报，均带 REMINDER 横幅），告警清除即止损；状态（是否已发/发了几次）落 eflow_tt_whatsapp_alert_log",
         description_en="Every 5 min: trigger from realtime_alarm (TT-linked, within window, code whitelist), live-fetch eFlow for the latest update time; first push immediately, then two-tier re-notify with a REMINDER banner (no update since last send -> nudge at 10 min; updated since last send -> wait 30 min), stop when cleared; send status (sent? how many times) recorded in eflow_tt_whatsapp_alert_log",
         default_cron="2-59/5 * * * *", category="whatsapp"),

    # 6. MS SLA 完整同步（每天 05:00）
    #    时序约束（2026-09-18 修复）：必须在 kpi_ms_contract(05:30) / kpi_ms_wo_sla(05:35)
    #    之前完成——两封邮件只读本任务产出的 data/ms_sla/*.xlsx，早于本任务就只能发前一版。
    #    实测耗时 9~11min，05:00 起跑 → 05:11 左右完成，留 19/24min 余量。
    #    上游 KPI list（FTP /webroot/WEB-INF/schedule/NUR_SLA/<date>/）实测约 15:04 发布，
    #    内容覆盖到发布当天；故 05:00 取到的正是「覆盖到昨天」的最新一版，不损失数据。
    dict(task_id="ms_sla_full", name="MS SLA 完整同步", name_en="MS SLA Full Sync",
         loader=("backend.services.ms_sla_service", "run_full_sync"),
         description="SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）",
         description_en="SLA metrics sync + Contract KPIs report update (self-contained, no external files)",
         default_cron="0 5 * * *", category="ms_sla"),

    # 7. eFlow 实时告警同步（每30分钟）
    dict(task_id="eflow_active_alarm", name="eFlow 实时告警同步", name_en="eFlow Realtime Alarm Sync",
         func=_run_eflow_active_alarm,
         description="从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite",
         description_en="Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite",
         default_cron="*/30 * * * *", category="eflow"),

    # 8. eFlow 历史告警同步（每3小时）
    dict(task_id="eflow_history_alarm", name="eFlow 历史告警同步", name_en="eFlow History Alarm Sync",
         func=_run_eflow_history_alarm,
         description="从 eFlow FM History 接口获取近7天历史告警，过滤 TT ID，保存 CSV + SQLite",
         description_en="Fetch last 7 days history alarms from eFlow FM History API, filter TT ID, save to CSV + SQLite",
         default_cron="0 */3 * * *", category="eflow"),

    # 8b. eFlow TT 规则收集 + 匹配检查（每天 04:20）：拉取最新规则并检查最新 1000 条 eflow_tt 的级别矫正
    dict(task_id="eflow_tt_rules_check", name="eFlow TT 规则收集与匹配检查", name_en="eFlow TT Rules Collect & Match Check",
         loader=("backend.services.eflow_rules.eflow_tt_rules_check_task", "run_eflow_tt_rules_check"),
         description="每天 04:20 从 eFlow 拉取激活的 TT Update Severity Rule（eflow_TT_rules.xlsx），再对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正（Email Reports → eflow_tt_rules_check 页签可下载规则/矫正表/报告）",
         description_en="Daily 04:20: collect active TT Update Severity Rules from eFlow (eflow_TT_rules.xlsx), then match the latest 1000 eflow_tt records and produce a severity correction report (downloadable under Email Reports → eflow_tt_rules_check tab)",
         default_cron="20 4 * * *", category="eflow"),

    # 9. RAN UME Main KPI 同步（每天凌晨4点）
    dict(task_id="main_kpi_sync", name="RAN Main KPI 同步", name_en="RAN Main KPI Sync",
         loader=("backend.services.ran_ume_main_kpi", "run_main_kpi_sync"),
         description="RAN UME Main KPI 历史指标同步（2G/3G/4G x Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传",
         description_en="RAN UME Main KPI history sync (2G/3G/4G x Cells/Sites/Group/NW), export Excel and incremental SQLite update + FTP upload",
         default_cron="0 4 * * *", category="main_kpi"),

    # 9b. RAN 小区可用性 1-Day KPI 同步（每天 04:30，替代独立 RPA 脚本 ran_kpi_avalability_1day.py）
    dict(task_id="cell_availability_sync", name="RAN 小区可用性 1-Day 同步", name_en="RAN Cell Availability 1-Day Sync",
         loader=("backend.services.ran_cell_availability_sync", "run_cell_availability_sync"),
         description="RAN UME 小区可用性天粒度 KPI 同步（FDD/UMTS/GSM/TDD 4 模板），写 ran_kpi_avalability_1day.sqlite3 + FTP 上传",
         description_en="RAN UME cell availability day-granularity KPI sync (FDD/UMTS/GSM/TDD), write ran_kpi_avalability_1day.sqlite3 + FTP upload",
         default_cron="30 4 * * *", category="availability"),

    # 9c. RAN 2G/3G/4G Cells KPI 同步（每天 04:50，紧跟小区可用性同步）
    #     复用 ran_cell_availability_sync 的 RAN_UME 小区数据获取方法，聚合当月每日
    #     Cells KPI（Total/Meeting/Below/Blank/%/Availability）物化到 ran_cells_kpi.sqlite3。
    dict(task_id="cells_kpi_sync", name="RAN Cells KPI 同步", name_en="RAN Cells KPI Sync",
         loader=("backend.services.ran_cells_kpi_sync", "run_cells_kpi_sync"),
         description="RAN UME 小区数据（2G/3G/4G）每日同步，聚合 Cells KPI（达标值 99.65%）物化写 ran_cells_kpi.sqlite3，只保留当月",
         description_en="Daily RAN UME cell data sync (2G/3G/4G), aggregate Cells KPI (target 99.65%) into ran_cells_kpi.sqlite3, current month only",
         default_cron="50 4 * * *", category="availability"),

    # 10. RAN UME Network KPI（Zeenshan）同步（每天凌晨5点）
    dict(task_id="network_kpi_sync", name="RAN Network KPI 同步", name_en="RAN Network KPI Sync",
         loader=("backend.services.ran_ume_network_kpi", "run_network_kpi_sync"),
         description="RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G x Group/NW），导出 Excel 并导入 SQLite + FTP 上传",
         description_en="RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G x Group/NW), export Excel and import to SQLite + FTP upload",
         default_cron="0 5 * * *", category="network_kpi"),

    # 10b. 可用率核对宽表 avail_recon 重建（每天 06:10）
    #      为什么需要：看板 daily_availability(id=9) / availability_tt(id=11) 共 15 个
    #      组件读 avail_recon.sqlite3.availability_daily。该表不是任何业务系统的原生表 ——
    #      FineBI 原版依赖**自助数据集**（基表在 FineDB 内部），且区域维度要跨库 JOIN
    #      Master_Site_Database，而远端只读 API 一次只能查一个库，只能用近似口径重建。
    #      2026-09-21 事故：这张表原本是 my-finebi 项目 data/ 下的**手工 ETL 快照**
    #      （TMP/etl_avail_recon_v2.py，其 PROJECT_DOCS 归类为「ETL 快照刷新 …… 变更后重跑」），
    #      my-finebi 门户退役后无人再跑 → 表冻结在 2026-09-13，看板静默停更两周。
    #      现收进 my_app 每日重建到本机 data/avail_recon.sqlite3（看板经 DB_ALIASES 直读）。
    #      为什么排 06:10 且归 u 组：源表 2G/3G/4G_Main_Kpi_Site_Daily 由同组的
    #      main_kpi_sync(04:00) 写入，同组串行 + 排队先后即可保证「先写后读」，
    #      也避免与写入方并发。整表只有 ~8k 行、实测 3s 跑完。
    dict(task_id="avail_recon_sync", name="可用率核对宽表重建", name_en="Availability Recon Rebuild",
         loader=("backend.services.avail_recon_sync", "run_avail_recon_sync"),
         description="重建 avail_recon 可用率核对宽表（读远端 Site_Daily × Master_Site_Database Region 近似聚合），写本机 data/avail_recon.sqlite3，供 Daily Availability KPI / Availability(TT) 看板",
         description_en="Rebuild the avail_recon availability reconciliation table (approx. aggregate of remote Site_Daily x Master_Site_Database region) into local data/avail_recon.sqlite3 for the Daily Availability KPI / Availability(TT) boards",
         default_cron="10 6 * * *", category="availability"),

    # 10b-2. BP Report 劣化小区报告更新（每天 06:20，紧跟 avail_recon_sync）
    #      为什么需要：BP Report 是 umlaut 口径的「劣化小区（Bad Performance）」清单
    #      （Daily: 活跃用户>2.5 且 DL 吞吐<3Mbps 且 DL PRB>80%；Weekly 4/7 天；
    #      Monthly 3/4 个完整周）。原始数据由 umlaut 以 Excel 交付，需要持续更新。
    #      两条数据来路，分工明确：
    #        ① Excel（data/umlaut_data/BP Report.xlsx）是一次性导入 —— 它提供
    #           `BP Cells List` 的 **cell → Cluster/Layer 字典**，因为 RAN_UME 侧
    #           完全没有 Cluster1~6/Rural 这套分区维度，无法从任何其它表推导。
    #           导入脚本 backend/services/bp_report_import.py（手工执行，不在调度内）。
    #        ② 本任务负责**指标更新**：从 RAN_UME 读 4G_Main_Kpi_Cell_Daily 的
    #           PRB/吞吐/流量，重算 is_bp 并重算日/周/月汇总，写本机
    #           data/bp_report.sqlite3，最后与 Excel 真值对账并写入 bp_sync_meta。
    #      为什么排 06:20 且归 u 组：源表由同组的 main_kpi_sync(04:00) 写入，
    #      同组串行 + 排队先后即可保证「先写后读」，也避免与写入方并发（与
    #      avail_recon_sync 同一条理由）。实测单日约 1.2s、3 天约 3.5s。
    #      ⚠️ 本任务**不新建 UME PM 模板** —— templateid 必须服务端已存在，
    #      不可臆造；只复用已物化的那张表。
    #      ⚠️ Active User 走**独立通道**（2026-09-30 接入）：该指标不在
    #      4G_Main_Kpi_Cell_Daily 里，且**加不进去** —— 那张表由日粒度任务
    #      （gr=86400）写入，而该指标只在**小时粒度**（gr=3600）可用；日粒度下
    #      UME 返回 HTTP 200 但**静默丢弃该列**（原文 PDF counter/indicator
    #      dimension is illegal）。故由 services/bp_active_user.py 按小时取数、
    #      本地聚合成**当日峰值**后并入第三条件判定。实测每天约 100s。
    #      取不到时该日 is_bp 仍记 NULL（不可判定），并在 bp_sync_meta 暴露。
    #      因口径由「两条件」变为「三条件」，caliber 版本同步升到 bp-v2。
    dict(task_id="bp_report_sync", name="BP 劣化小区报告更新", name_en="BP Report Sync",
         loader=("backend.services.bp_report_sync", "run_bp_report_sync"),
         description="从 RAN_UME 读取 4G 小区级 PRB/吞吐/流量，并按 UME 小时粒度取 Average DL Active User Number（当日峰值），按 umlaut 三条件口径重算 BP 劣化小区（日/周/月），更新本机 data/bp_report.sqlite3 并与 Excel 真值对账",
         description_en="Read per-cell 4G PRB/throughput/traffic from RAN_UME plus Average DL Active User Number at hourly granularity (daily peak), recompute Bad Performance cells by the umlaut three-condition caliber (daily/weekly/monthly), refresh local data/bp_report.sqlite3 and reconcile against the Excel ground truth",
         default_cron="20 6 * * *", category="availability"),

    # 10c. MTTR/TT 宽表重建（每天 07:40，紧跟 eflow_sync 的 07:22 那一轮）
    #      为什么需要：看板 mttr(id=15) 读 mttr_tt.sqlite3.tt_full，那是 Eflow_TT_FB 的
    #      宽表（Vender / MTTR1 / MTTR2 / MTTR_RANG_2H / Month / WK / Outage_Mins /
    #      Site Category / 各制式小区数），口径解析自 FineDB 数据集 4bc5a679。
    #      与 avail_recon 同源事故：该表原由已退役 my-finebi 的手工 ETL
    #      （TMP/etl_mttr_tt.py）维护，无调度 → 冻结在 2026-08-31，看板静默停更。
    #      现每日重建到本机 data/mttr_tt.sqlite3（看板经 DB_ALIASES 直读）。
    #      为什么 07:40 且归 m 组：数据源 Eflow_TT_FB 由 eflow_sync（n 组，每小时 :22、
    #      约 6min 跑完）写；:40 取到的一定是 :22 那一版。本任务只用远端**只读** API
    #      + 写本机文件，不占任何业务会话，与 db_freshness_check 等内务任务同组。
    dict(task_id="mttr_tt_sync", name="MTTR/TT 宽表重建", name_en="MTTR/TT Wide Table Rebuild",
         loader=("backend.services.mttr_tt_sync", "run_mttr_tt_sync"),
         description="重建 mttr_tt 宽表（Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category 参考库），写本机 data/mttr_tt.sqlite3，供 MTTR Monthly&Weekly 看板",
         description_en="Rebuild the mttr_tt wide table (Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category reference) into local data/mttr_tt.sqlite3 for the MTTR Monthly&Weekly board",
         default_cron="40 7 * * *", category="availability"),

    # 10d. Progress 宽表重建（每天 07:50，紧随 10c）
    #      为什么需要：看板 progress(id=18) / progress_v3(id=19) 读 progress.sqlite3.progress_full
    #      —— Eflow_TT_FB LEFT JOIN Eflow_WO_FB 的宽表，逐行复刻 FineDB 数据集 4bc5a679 的
    #      Progress 计算列（各环节 ORG/STATUS、FB_* 级联、ORG_Handler、Month、MTTR1/2）。
    #      同样因 my-finebi 退役、手工 ETL 无人调度 → 冻结在 2026-08-31。
    #      现每日重建到本机 data/progress.sqlite3（看板经 DB_ALIASES 直读）。
    #      注意：Duration(Hours)/SLA(%) 依赖「当前时间」，不落库，组件 SQL 实时算。
    dict(task_id="progress_sync", name="Progress 宽表重建", name_en="Progress Wide Table Rebuild",
         loader=("backend.services.progress_sync", "run_progress_sync"),
         description="重建 progress 宽表（Eflow_TT_FB LEFT JOIN Eflow_WO_FB，复刻 FineBI Progress 计算列），写本机 data/progress.sqlite3，供 Progress / Progress V3 看板",
         description_en="Rebuild the progress wide table (Eflow_TT_FB LEFT JOIN Eflow_WO_FB, replicating FineBI Progress computed columns) into local data/progress.sqlite3 for the Progress / Progress V3 boards",
         default_cron="50 7 * * *", category="availability"),

    # 11. CNN UME KPI 同步（每天凌晨6点）
    dict(task_id="cnn_kpi_sync", name="CNN UME KPI 同步", name_en="CNN UME KPI Sync",
         loader=("backend.services.ccn_ume_kpi_service", "run_cnn_kpi_sync"),
         description="CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN",
         description_en="CNN UME Core Network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN",
         default_cron="0 6 * * *", category="cnn_kpi"),

    # 12. SP 备件数据同步（2026-09-20 起改为每小时 :10，原为每天 07:00）
    #     为什么改小时级：上游 SFTP（sp/inbound、sp/outbound）本来就是**每小时 :00:03
    #     导出一份**（每天 24 个时间戳目录），而 MsPortal 的 QC 面板 SPMS 卡读的正是本任务
    #     写的 inband_details / outband_details —— 按天同步时那个数字最长滞后 24 小时。
    #     为什么排 :10：同组（n）的 eflow_sync 每小时 :00 起跑、实测约 6min 跑完，
    #     sp_online_sync 在 :35；:10 两边都不撞，且上游导出 :00:03 已落盘，拿到的一定是新那份。
    #     ⚠ 本任务与 n 组的 eflow_sync / eflow_active_alarm 等**串行**执行，而它末尾的
    #     FineBI 镜像（UNC inventory.db，113MB）偶尔报 "database is locked" —— 实测单次
    #     1~9min，最坏曾 2h+（见 get_sp_table.SFTP_CHANNEL_TIMEOUT 处的 2026-09-20 事故）。
    #     队列有单飞保护：上一轮没跑完就跳过本轮触发，不会堆叠，但那一小时的数就是旧的。
    #     若日后 QC 的 TT/WO/CR/PMT 出现「跟着 SP 一起变慢」，先怀疑这里占用了 n 组 worker。
    dict(task_id="sp_data_sync", name="SP 备件数据同步", name_en="SP Spare Data Sync",
         loader=("backend.services.get_sp_table", "run_sp_data_sync"),
         description="从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db，并镜像写入 FineBI WareHouseDashBoard inventory.db",
         description_en="Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db, then mirror into FineBI WareHouseDashBoard inventory.db",
         default_cron="10 * * * *", category="sp"),

    # 13. iPRAN UME KPI 同步（每天凌晨8点）
    dict(task_id="ipran_kpi_sync", name="iPRAN UME KPI 同步", name_en="iPRAN UME KPI Sync",
         loader=("backend.services.ipran_ume_kpi_service", "run_ipran_kpi_sync"),
         description="iPRAN UME M6000 路由器 KPI 同步（HQ M6K-FW 等），导出 Excel 并导入 SQLite + FTP 上传",
         description_en="iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel and import to SQLite + FTP upload",
         default_cron="0 8 * * *", category="ipran_kpi"),

    # 14. Liberia 站点宕 1 小时报告邮件（每小时第 15 分钟）
    #     时序约束：数据是 eflow_sync(每小时 :00，实测 ~6min 完成) 产出的
    #     data/eflow/tt_reports/*.xlsx，必须留足余量，故排在 :15。
    dict(task_id="liberia_email_1h", name="Liberia 宕站 1小时报告邮件", name_en="Liberia Site-Down 1H Report Email",
         loader=("backend.services.liberia_email_report", "run_1h_report"),
         description="发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单",
         description_en="Email Liberia Orange Site Down hourly Report (inline images + Excel) to recipient lists",
         default_cron="15 * * * *", category="email"),

    # 15. Liberia 站点宕 8 小时报告邮件（每8小时第 20 分钟）
    #     时序约束：同 liberia_email_1h。原先排在 :07，与 eflow_sync 的完成时刻
    #     （实测 :06~:07）几乎重合，实测出现过抢跑读到上一期报告的情况。
    dict(task_id="liberia_email_8h", name="Liberia 宕站 8小时报告邮件", name_en="Liberia Site-Down 8H Report Email",
         loader=("backend.services.liberia_email_report", "run_8h_report"),
         description="发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单",
         description_en="Email Liberia Orange Site Down 8 hours Report (inline images + Excel) to recipient lists",
         default_cron="20 */8 * * *", category="email"),

    # 16. MS Contract KPIs Achievements Daily Report 邮件（数据本地 ms_sla）
    #     时序约束：必须晚于 ms_sla_full(05:00，约 05:11 完成)
    dict(task_id="kpi_ms_contract", name="MS Contract KPIs 日报邮件", name_en="MS Contract KPIs Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ms_contract_kpi"),
         description="发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）",
         description_en="Email MS Contract KPIs Achievements Daily Report (local data + remote recipient list)",
         default_cron="30 5 * * *", category="kpi_email"),

    # 17. MS WOs SLA Achievements Daily Report 邮件（数据本地 ms_sla）
    #     时序约束：必须晚于 ms_sla_full(05:00，约 05:11 完成)
    dict(task_id="kpi_ms_wo_sla", name="MS WOs SLA 日报邮件", name_en="MS WOs SLA Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ms_wo_sla"),
         description="发送 MS WOs SLA Achievements Daily Report（本地数据 + 远程名单）",
         description_en="Email MS WOs SLA Achievements Daily Report (local data + remote recipient list)",
         default_cron="35 5 * * *", category="kpi_email"),

    # 18. SpareParts 备件报表邮件（数据本地 sp_email 生成端产出 + 远程共享名单）
    dict(task_id="kpi_sp_spareparts", name="SpareParts 备件报表邮件", name_en="SpareParts Report Email",
         loader=("backend.services.kpi_email_report", "run_sp_spareparts"),
         description="发送 SpareParts 报表（本地 sp_email 数据 + 远程共享名单）",
         description_en="Email SpareParts report (local sp_email data + remote shared recipient list)",
         default_cron="45 9 * * *", category="kpi_email"),

    # 19. Comsumables 耗材报表邮件（数据本地 sp_email 生成端产出 + 远程共享名单）
    dict(task_id="kpi_sp_consumables", name="Comsumables 耗材报表邮件", name_en="Comsumables Report Email",
         loader=("backend.services.kpi_email_report", "run_sp_consumables"),
         description="发送 Comsumables 报表（本地 sp_email 数据 + 远程共享名单）",
         description_en="Email Comsumables report (local sp_email data + remote shared recipient list)",
         default_cron="50 9 * * *", category="kpi_email"),

    # 19b. SP 备件报表生成（每天 05:15，先于 05:45/06:40 两个邮件任务）
    dict(task_id="sp_report_generate", name="SP 备件报表生成", name_en="SP Report Generate",
         loader=("backend.services.kpi_email_report", "run_sp_report_generate"),
         description="从 SFTP 下载备件数据，生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表到本地 data/sp_email",
         description_en="Download spare-part data from SFTP and generate Comsumables & SpareParts Inbound&Outbound&Inventory reports into local data/sp_email",
         default_cron="15 5 * * *", category="kpi_email"),

    # 19c. SP 备件明细报表（每天 07:00）：4 份明细合并为一个带时间戳的 Excel，邮件 + WhatsApp 群
    dict(task_id="sp_email_details", name="SP 备件明细报表邮件", name_en="SP Spare Parts Details Report Email",
         loader=("backend.services.kpi_email_report", "run_sp_details_email"),
         description="把 data/sp_email/data 下 4 份备件明细（inventory/inband/outband/transfer）合并为一个 Excel（sheet: Inventory/Inbound/Outbound/Transfer），附件名与主题携带时间戳发送；邮件主送 ansah.boadu@zte.com.cn，抄送 dong.xinmin@zte.com.cn（收件人可在 Settings → Email Recipient Settings 覆盖）；邮件发出后把同一份合并 Excel 作为文档发到 WhatsApp 群 WH&SP Management",
         description_en="Merge the 4 spare-part detail files (inventory/inband/outband/transfer) under data/sp_email/data into one Excel (sheets: Inventory/Inbound/Outbound/Transfer) with a timestamped filename and subject; email to ansah.boadu@zte.com.cn, cc dong.xinmin@zte.com.cn (recipients editable under Settings → Email Recipient Settings); after the email, also send the same merged Excel as a document to the WhatsApp group WH&SP Management",
         default_cron="0 7 * * *", category="kpi_email"),

    # 19c-2. SP 备件明细分文件邮件（每天 10:05，2026-09-30 新增）
    #        与 19c（sp_email_details，05:00）同数据源不同打包方式：19c 合并成一个多
    #        sheet 工作簿 + 发 WhatsApp 群；本任务把 6 份明细**一文件一邮件**发给
    #        NOC（主送 MS.NOC@zte.com.cn，抄送 li.jing132 / luo.wutao）。
    #        主题口径（用户 2026-09-30 指定）：Liberia OLR W.H <完整文件名> <日期时间>。
    #        为什么 10:05 而不是 10:00：整点是本组（kpi_email）邮件任务的密集时段，
    #        错开 5 分钟避免同组 worker 排队（与 05:30/05:35、09:45/09:50 的错峰同思路）。
    #        时序约束：数据由 sp_report_generate（05:15）产出，10:05 远在其后，
    #        不存在读不到当天快照的抢跑风险。
    #        ⚠️ 一文件一邮件 => 一次任务最多 6 次 EWS 会话，耗时约为单封的 6 倍。
    dict(task_id="sp_details_files_email", name="SP 备件明细分文件邮件",
         name_en="SP Spare Parts Details Files Email",
         loader=("backend.services.kpi_email_report", "run_sp_details_files_email"),
         description="每天 10:05 把 data/sp_email/data 下 6 份备件明细（inventory/inband/outband/transfer/transfer_return/ocrule）**一文件一邮件**逐个发送，主题为「Liberia OLR W.H <附件文件名> <日期时间>」；对外附件名把 inband/outband 写作 inbound/outbound（磁盘源名不变）；优先用未过滤的 *_source.xlsx 原始快照，缺失时逐份回退过滤版；任一份文件缺失即整体失败、一封都不发，单封发送失败则不中断后续并汇总点名。默认主送 MS.NOC@zte.com.cn，抄送 li.jing132@zte.com.cn / luo.wutao@zte.com.cn（收件人可在 Settings → Email Recipients 的 sp_details_files 分组覆盖）",
         description_en="Daily 10:05: send the 6 spare-part detail files (inventory/inband/outband/transfer/transfer_return/ocrule) under data/sp_email/data as ONE EMAIL PER FILE, each with a single attachment and the subject 'Liberia OLR W.H <attachment file name> <date time>'; outbound attachment names use inbound/outbound for inband/outband (on-disk source names unchanged); prefers the unfiltered *_source.xlsx raw snapshot and falls back per-file to the filtered version; if any file is missing the whole run fails and nothing is sent, while a single send failure does not stop the rest and is reported by name. Default To MS.NOC@zte.com.cn, Cc li.jing132@zte.com.cn / luo.wutao@zte.com.cn (recipients editable in Settings → Email Recipients, group sp_details_files)",
         default_cron="5 10 * * *", category="kpi_email"),

    # 19g. SP 物料库存与消耗报表邮件（每天 07:45）：2026-09-11 新增。
    #      数据与页面 myapp/?page=sp_material 同源（sp_material_summary_service 读
    #      inventory_details 快照 + outband_details），导出两行表头 Excel（13 列）后作附件发送。
    #      时序约束（2026-09-18 修复）：必须晚于 sp_data_sync(07:00，实测 1~9min 完成，
    #      偶发 SFTP 慢时可达 90min)——这两张表由 sp_data_sync 从 SFTP 拉取后写入 app.db，
    #      原先排在 06:45 会永远读到前一天的快照。
    dict(task_id="sp_material_report", name="SP 物料库存与消耗报表邮件",
         name_en="SP Material Stock & Consumption Report Email",
         loader=("backend.services.kpi_email_report", "run_sp_material_stock_consumption"),
         description="每天 07:45 把 SP 物料库存与消耗汇总（同 page=sp_material 页面口径）导出为 UNIFIED_EXCEL_V1 版式 Excel 附件（SP_Material_Summary_<当前快照>.xlsx）+ 同内容 PNG 内嵌正文并邮件发送；默认 15 主送 + 2 抄送（收件人可在 Settings → 邮件收件人 覆盖）",
         description_en="Daily 07:45: export the SP material stock & consumption summary (same scope as page=sp_material) to a UNIFIED_EXCEL_V1 Excel attachment (SP_Material_Summary_<snapshot>.xlsx) plus an inline PNG of the same table, and email it; default 15 To + 2 Cc (recipients editable under Settings → Email Recipients)",
         default_cron="45 7 * * *", category="kpi_email"),

    # 19d. SP 在线未关闭单报表生成（每天 06:00）：基于最新明细生成 sp_online 的 PNG+XLSX，供 06:20 发送
    dict(task_id="sp_online_report_generate", name="SP 在线未关闭单报表生成", name_en="SP Online Open Tickets Report Generate",
         loader=("backend.services.kpi_email_report", "run_sp_online_report_generate"),
         description="基于 data/sp_email/data 最新 inband/outband 明细，过滤未关闭单生成 sp_online 下 Inbound/Outbound 报表（PNG+XLSX，Create Time 倒序）",
         description_en="Generate open-ticket reports (Inbound/Outbound PNG+XLSX, sorted by Create Time desc) into data/sp_email/sp_online from the latest details",
         default_cron="0 6 * * *", category="kpi_email"),

    # 19e. SP 在线未关闭单报表发送（每天 06:20）：邮件（PNG 内嵌 + XLSX 附件）+ WhatsApp 群发
    dict(task_id="sp_online_report_send", name="SP 在线未关闭单报表发送", name_en="SP Online Open Tickets Report Send",
         loader=("backend.services.kpi_email_report", "run_sp_online_report"),
         description="发送 sp_online 未关闭单报表：邮件（Inbound/Outbound PNG 内嵌 + XLSX 附件，默认复用 SP 报表远程名单）+ WhatsApp 群（收件人可在 Settings → Email Recipient Settings 覆盖）",
         description_en="Send the open-ticket report: email (inline Inbound/Outbound PNG + XLSX attachments, default SP shared recipient list) + WhatsApp groups (recipients editable under Settings → Email Recipient Settings)",
         default_cron="20 6 * * *", category="kpi_email"),

    # 19f. Comsumables & SpareParts 报表 WhatsApp 发送（每天 07:15）：
    #      把 kpi_sp_consumables / kpi_sp_spareparts 两个邮件任务的同一批产物（合并总表 XLSX + 报表 PNG）
    #      发到 WhatsApp 群 WH&SP Management；只发 WhatsApp，不重复发邮件
    dict(task_id="sp_whatsapp_report", name="Comsumables&SpareParts Report Whatsapp",
         name_en="Comsumables&SpareParts Report Whatsapp",
         loader=("backend.services.kpi_email_report", "run_sp_whatsapp_report"),
         description="每天 07:15 把 Comsumables Report Email / SpareParts Report Email 所发送的 Excel（合并总表）与报表图片发送到 WhatsApp 群 WH&SP Management",
         description_en="Daily 07:15: send the same Excel (consolidated) and report images used by the Comsumables / SpareParts report emails to the WhatsApp group WH&SP Management",
         default_cron="15 7 * * *", category="whatsapp"),

    # 20. MS Network Availability Daily Report 邮件（远程 FTP 图片，无 Excel）
    dict(task_id="kpi_ran_availability", name="MS Network Availability 日报邮件", name_en="MS Network Availability Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ran_availability"),
         description="发送 MS Network Availability Daily Report（远程 FTP 图片 + 远程名单，无 Excel）",
         description_en="Email MS Network Availability Daily Report (remote FTP images + remote recipient list, no Excel)",
         default_cron="30 9 * * *", category="kpi_email"),

    # 21. EWS 恢复后自动补发失败邮件（每 10 分钟扫描；按小时/8小时/日报时效策略补发）
    dict(task_id="email_recovery", name="EWS 恢复后邮件补发", name_en="Email Recovery after EWS Restored",
        loader=("backend.services.email_recovery", "run_email_recovery_task"),
        description="每10分钟探测 EWS；按任务失败链的小时/8小时/日报时效策略补发失败邮件，成功后关闭失败链以防重复发送",
        description_en="Probe EWS every 10 minutes; recover failed emails using per-task hourly, 8-hour, and daily retry policies with failure-chain deduplication",
        default_cron="*/10 * * * *", category="email"),

    # 22. Packet Loss 丢包数据同步 + 报告生成（每天凌晨6:30）
    dict(task_id="packet_loss_sync", name="Packet Loss 丢包同步", name_en="Packet Loss Sync",
         loader=("backend.services.packet_loss_service", "run_packet_loss_sync"),
         description="RAN UME 丢包率（SDR/IPRAN IPPD）同步，入库 lte_pl.sqlite3 并生成丢包报告；报告/看板只展示最近 7 个完整自然日，当天未过完不展示",
         description_en="Sync Packet Loss Rate (SDR/IPRAN IPPD) from RAN UME into lte_pl.sqlite3 and generate the report; only the last 7 complete calendar days are shown (unfinished current day excluded)",
         default_cron="30 6 * * *", category="packet_loss"),

    # 22b. Packet Loss 丢包看板日报邮件（每天 06:45，依赖 06:30 同步生成的报告）
    dict(task_id="packet_loss_email", name="Packet Loss 丢包日报邮件", name_en="Packet Loss Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_packet_loss_email"),
         description="发送 Packet Loss 丢包看板日报邮件（本地截图 + 最新报告 xlsx + 远程收件人清单），经 OWA 账户发送",
         description_en="Send Packet Loss dashboard daily email (local screenshot + latest report xlsx + remote recipient list) via OWA",
         default_cron="45 6 * * *", category="packet_loss"),

    # 23. IP RAN M6K-FW Chart Email - 3组 ME+SmartGroup 折线图，每天 6:45
    dict(task_id="ipran_m6k_chart_email", name="IP RAN M6K-FW 图表邮件", name_en="IP RAN M6K-FW Chart Email",
         loader=("backend.services.ipran_chart_service", "run_ipran_m6k_chart_email"),
         description="从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成3张利用率折线图并发送",
         description_en="Query HQ_M6K_FW_bnctp_15mins by ME+SmartGroup, generate 3 utilization line charts and email",
         default_cron="45 6 * * *", category="email"),

    # 24. CNN Free Rating Group Chart Email - 4个 MO 柱状图，每天 7:45
    dict(task_id="ccn_free_rating_chart_email", name="CNN Free Rating 图表邮件", name_en="CNN Free Rating Chart Email",
         loader=("backend.services.ccn_free_rating_chart_service", "run_ccn_free_rating_chart_email"),
         description="从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成4张柱状图并发送",
         description_en="Query FREE_RATING by MO, generate 4 bar charts and email",
         default_cron="45 7 * * *", category="email"),

    # 25. FW 整机吞吐 KPI 同步 + 图表邮件 - 每天 7:15
    dict(task_id="fw_kpi_sync", name="FW 吞吐 KPI 同步+图表邮件", name_en="FW Throughput KPI Sync + Chart Email",
         loader=("backend.services.fw_kpi.fw_kpi_services", "run_fw_kpi_sync"),
         description="从 DPtech UMC 拉取整机吞吐数据，经 API 写入远程 fw_db.sqlite，生成近14天吞吐折线图并邮件发送",
         description_en="Fetch FW whole throughput from DPtech UMC, write to remote fw_db.sqlite via API, generate 14-day chart and email",
         default_cron="15 7 * * *", category="fw_kpi"),

    # 26. 电池 KPI 实时同步（每小时第 5 分钟）
    #     凭据：「设置 → 凭据管理 → Battery UME」(credential_store key=battery_ume)，
    #     该 UME 与 RAN UME(10.100.28.27) 不是同一台设备，账号不通用。
    dict(task_id="battery_kpi_sync", name="电池 KPI 同步", name_en="Battery KPI Sync",
         loader=("backend.services.battary_kpi_fetch.battery_kpi_service", "run_battery_kpi_sync"),
         description="从 UME(192.168.170.2) 拉取电池实时 KPI（健康度/SOC/充放电状态），全程内存不落盘，写入 battery_kpi.sqlite3 供电池看板使用；凭据见「凭据管理 → Battery UME」",
         description_en="Fetch battery realtime KPI (health/SOC/charge status) from UME(192.168.170.2), in-memory only, write to battery_kpi.sqlite3 for Battery Dashboard; credentials under Credential Settings > Battery UME",
         default_cron="5 * * * *", category="battery"),
    # 28. 电池 KPI 邮件（每天 07:10 与 19:10）
    #     时序约束：读 battery_kpi.sqlite3，由 battery_kpi_sync（每小时 :05）写入。
    #     原先排在 07:00/19:00，恰好落在 :05 同步之前，只能用到 55min 前的数据。
    dict(task_id="battery_email", name="电池 KPI 邮件", name_en="Battery KPI Email",
         loader=("backend.services.battary_kpi_fetch.battery_kpi_service", "run_battery_email"),
         description="将电池 KPI 报表（Excel）发送至远程名单中的邮箱，每日 07:10 与 19:10 各一次",
         description_en="Email the battery KPI report (Excel) to recipients from remote FTP list, daily at 07:10 & 19:10",
         default_cron="10 7,19 * * *", category="battery"),

    # 27. 邮箱空间守卫（每小时第 0 分钟）：容量超阈值自动清理最旧邮件，避免存储上限告警
    dict(task_id="mailbox_cleanup", name="邮箱空间清理", name_en="Mailbox Storage Guard",
         loader=("backend.services.mailbox_cleanup", "run_mailbox_cleanup"),
         description="每小时检查 Exchange 邮箱（ztenoc.olr@orange.com）：邮件数>500 且 空间>70% 时，硬删除最旧 200 封邮件，避免 'storage limit' 告警",
         description_en="Hourly guard for Exchange mailbox (ztenoc.olr@orange.com): when count>500 AND usage>70%, hard-delete the 200 oldest emails to avoid the 'storage limit' warning",
         default_cron="0 * * * *", category="mailbox"),

    # 28. Incident Overview 数据同步（每小时第 20 分钟）：从远程 FineBI FTP 拉取最新 incident_overview.xlsx
    #     刻意避开 :00–:05 —— FineBI 在 :53 删掉上一轮输出目录、新副本约 :02–:05 才落盘，整点取数会撞空档
    dict(task_id="incident_overview_sync", name="Incident Overview 数据同步", name_en="Incident Overview Data Sync",
         loader=("backend.services.incident_overview_sync", "run_incident_overview_sync"),
         description="每小时第 20 分钟从远程 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，落盘为版本化文件 + current.json 指针（Excel 一直打开也不会失败），best-effort 刷新 incident_overview.xlsx 快照；上游重算窗口内取不到文件时沿用 90 分钟内的本地副本，不判失败",
         description_en="Hourly at minute 20: pull the latest incident_overview.xlsx from remote FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ across all subfolders, store as versioned file + current.json pointer (immune to Excel lock), best-effort refresh snapshot; while upstream is regenerating it reuses a local copy younger than 90 minutes instead of failing",
         default_cron="20 * * * *", category="incident_overview"),

    # 28b. FineBI 报表文件同步（每小时第 10 分钟）：schedule 下每个文件夹取最新 Excel 供下载
    dict(task_id="finebi_report_sync", name="FineBI 报表文件同步", name_en="FineBI Report Files Sync",
         loader=("backend.services.finebi_report_sync", "run_finebi_report_sync"),
         description="每小时从 FineBI FTP /webroot/WEB-INF/schedule 的每个子文件夹取最新一份 Excel，下载到本地 data/finebi_reports 供 Task Report Files 页面下载；某目录本轮没有 Excel 而本机已有历史副本时只记 missing 不判失败（FineBI :53 重算空档是常态）",
         description_en="Hourly: pull the latest Excel from each subfolder of FineBI FTP /webroot/WEB-INF/schedule into local data/finebi_reports for the Task Report Files page; a folder empty this cycle is recorded as missing instead of failing the task when a local copy already exists (FineBI deletes the previous output folder at :53)",
         default_cron="10 * * * *", category="general"),

    # 29. 数据新鲜度巡检（每小时第 15 分钟）：远程库 + 本地回退库 + 本机文件型源
    dict(task_id="db_freshness_check", name="数据库数据新鲜度巡检", name_en="DB Data Freshness Check",
         loader=("backend.services.db_freshness_check", "run_db_freshness_check"),
         description="每小时巡检远程 DB（db_writer_api）、本地回退库各表最新数据日期，以及本机文件型数据源（FTP 落盘的 Excel）的落盘年龄，滞后时输出调用链路与检查方向",
         description_en="Hourly freshness audit of remote DBs (via db_writer_api), local fallback DBs, and local file-based sources (FTP-pulled Excel) by on-disk age; outputs call chain and troubleshooting guidance when stale",
         default_cron="15 * * * *", category="general"),

    # 30. 失败任务自动重试 + 漏跑补投（每 10 分钟扫描）
    dict(task_id="auto_retry_failed", name="失败任务自动重试", name_en="Failed Task Auto Retry",
         loader=("backend.services.auto_retry", "run_auto_retry_task"),
         description="每 10 分钟扫描：① 失败任务若数据缺口尚未被后续成功执行补上（或已超 24h 硬上限则放弃）且未超过重试次数上限，自动重新投递执行；② 时效窗口内应触发但根本没有任何执行记录的漏跑任务，自动补投一次（邮件任务由 EWS 补发机制负责，默认排除）",
         description_en="Scan every 10 minutes: (1) re-run failed tasks whose data gap has not been filled by a later successful run (give up beyond the 24h hard cap) and under the retry budget; (2) backfill missed tasks that should have fired within the time window but have no execution record at all (email tasks are handled by EWS recovery and excluded)",
         default_cron="*/10 * * * *", category="general"),

    # 31. RAN UME CM 小区配置数据同步（每天 8:30）
    dict(task_id="cm_data_sync", name="RAN CM 小区数据同步", name_en="RAN CM Cell Data Sync",
         loader=("backend.services.cm_data.cm_data_export", "run_cm_data_sync"),
         description="从 RAN UME 获取 GSM/UMTS/LTE/NR 小区配置数据，经 API 全量替换写入远程 db.sqlite3（cm_cell_data/cm_site_summary），本地仅保留一份最新 Excel",
         description_en="Fetch GSM/UMTS/LTE/NR cell config data from RAN UME, full-replace write to remote db.sqlite3 (cm_cell_data/cm_site_summary) via API, keep only the latest local Excel",
         default_cron="30 8 * * *", category="cm_data"),

    # 33. PG → SQLite 全量快照同步（每小时第 45 分钟）
    dict(task_id="pg_to_sqlite_sync", name="PG→SQLite 数据快照",
         name_en="PG→SQLite Data Snapshot",
         loader=("backend.scripts.sync_pg_to_sqlite", "main"),
         description="把远程 PostgreSQL 全库数据同步到本地 db/app.db 作为离线备份/回退快照",
         description_en="Sync all remote PostgreSQL data to local db/app.db as offline backup / fallback snapshot",
         default_cron="45 * * * *", category="general"),

    # 32. MW UME KPI 同步（每天 05:15，零落盘直写 app.db 表 mw_ume_bw_ultilazation）
    dict(task_id="mw_ume_kpi_sync", name="MW UME KPI 同步", name_en="MW UME KPI Sync",
         loader=("backend.services.mw_ume.mw_ume_kpi_service", "run_mw_ume_kpi_sync"),
         description="MW UME (ZXMW 微波) KPI 历史指标同步（FINBI 模板 1 天粒度），内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation（Begin Time + 元素标识列联合去重）",
         description_en="MW UME (ZXMW microwave) KPI history sync (FINBI 1-day), in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation (dedup by Begin Time + identity cols)",
         default_cron="15 5 * * *", category="mw_ume"),

    # 32b. MW UME KPI 实时同步（每 15 分钟，gr=900 取最近 2 小时，直写 mw_ume_bw_ultilazation_rt）
    dict(task_id="mw_ume_kpi_sync_rt", name="MW UME KPI 实时同步", name_en="MW UME KPI Realtime Sync",
         loader=("backend.services.mw_ume.mw_ume_kpi_service", "run_mw_ume_kpi_sync_rt"),
         description="MW UME (ZXMW 微波) KPI 实时指标同步（FINBI 模板 15 分钟粒度），每 15 分钟取最近 2 小时数据，内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation_rt（看板只取最新 15 分钟槽位）",
         description_en="MW UME (ZXMW microwave) realtime KPI sync (FINBI 15-min granularity): every 15 min fetch the last 2 hours, in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation_rt (dashboard uses only the latest 15-min slot)",
         default_cron="*/15 * * * *", category="mw_ume"),

    # 33. UME Dong customer 周度业务 KPI 同步（每天 05:45）
    #     门户 172.17.208.1:28808（em-portal），抓 7 个模板（IVR/P4M/VC/USSD/PPS/CPU/Memory），
    #     内存导出不落盘，直写主库表 ume_in_customer_kpi（Begin Time + KPI + NE + SERVICE 联合去重）。
    #     看板「客户业务 KPI」页 = frontend/src/pages/UmeInKpi.tsx（pageKey ume_in_kpi）。
    dict(task_id="ume_in_kpi_sync", name="客户业务 KPI 同步", name_en="Customer Service KPI Sync",
         loader=("backend.services.ume_in.ume_in_kpi_service", "run_ume_in_kpi_sync"),
         description="从 UME 门户 172.17.208.1:28808 抓取 Dong customer 周度业务 KPI（IVR / P4M / VC / USSD / PPS / CPU / Memory 共 7 个模板，1 天粒度，默认回看 7 天），内存导出不落盘，直写主库表 ume_in_customer_kpi（Begin Time + KPI + NE + SERVICE 联合去重）",
         description_en="Fetch Dong customer weekly service KPIs from UME portal 172.17.208.1:28808 (7 templates: IVR / P4M / VC / USSD / PPS / CPU / Memory, 1-day granularity, 7-day lookback), in-memory export without disk, direct write to table ume_in_customer_kpi (dedup by Begin Time + KPI + NE + SERVICE)",
         default_cron="45 5 * * *", category="ume_in"),

    # 33b. 客户业务 KPI 同步 + OSG 周报邮件（每天 06:30，2026-09-18 新增）
    #      一条任务分步执行：① ume_in_kpi_service.run_ume_in_kpi_sync()（同步 7 模板到
    #      ume_in_customer_kpi）→ ② ume_in/t_osg_build.py 取最新 7 天填充 OSG Weekly QoS
    #      Analysis Report 模板 → ③ 附件邮件发给 djoumene.reussite1@zte.com.cn
    #      （抄送 dong.xinmin@zte.com.cn，Settings → Email Recipient Settings 可覆盖）。
    #      与 ume_in_kpi_sync 同一 UME Dong 门户会话，故同组 n 串行（见 GROUP_TASK_MAP）。
    dict(task_id="ume_in_osg_report", name="客户业务 KPI + OSG 周报邮件",
         name_en="Customer Service KPI + OSG Weekly Report Email",
         loader=("backend.services.ume_in.osg_report_task", "run_ume_in_osg_report"),
         description="每天早上分步执行：先 ume_in KPI 同步（UME 门户 172.17.208.1:28808，7 模板直写 ume_in_customer_kpi），再按表里最新 7 天生成 OSG Weekly QoS Analysis Report Excel（backend/services/ume_in/t_osg_build.py），最后把该 Excel 作为附件邮件发送给 djoumene.reussite1@zte.com.cn，抄送 dong.xinmin@zte.com.cn（收件人可在 Settings → Email Recipient Settings 的 ume_in_osg_report 组覆盖）",
         description_en="Every morning, step by step: run the ume_in KPI sync (UME portal 172.17.208.1:28808, 7 templates into ume_in_customer_kpi), build the OSG Weekly QoS Analysis Report Excel from the latest 7 days (backend/services/ume_in/t_osg_build.py), then email that Excel to djoumene.reussite1@zte.com.cn, cc dong.xinmin@zte.com.cn (recipients editable under Settings → Email Recipient Settings, group ume_in_osg_report)",
         default_cron="30 6 * * *", category="ume_in"),

    # 34b. SP Online 在线工单同步（每 6 小时的第 35 分钟）：从 eFlow SP 接口拉全量
    #
    # ⚠ cron 于 2026-10-04 由 `35 * * * *` 改为 `35 */6 * * *`，原因是**登录频率**：
    #   本任务走 eFlow，而旧的 `AUTH_TOKEN_TTL=1800`（30 分钟）< 本任务的触发间隔
    #   3600 秒（1 小时）—— 意味着**每一轮运行前缓存必然已过期**，于是每小时都真实
    #   登录一次 = 24 次/天。eFlow 每次登录**新建一个服务端会话且从不释放**，
    #   这是 2026-10-04「eFlow 用户数持续增长」的主要贡献者（日志实测
    #   09-26~10-03 每天 15~26 次登录，与"每小时一次"完全吻合）。
    #
    #   两道防线（互相独立，任一生效即可压住频率）：
    #     1. `AUTH_TOKEN_TTL=86400`（24 小时，见 backend/.env）—— 正常路径下
    #        一天只有第 1 轮真实登录，其余命中缓存。
    #     2. 本 cron 放宽到 6 小时 —— **即使 TTL 配置失效或缓存被清**，
    #        登录次数也封顶在 4 次/天，不会再退化成 24 次/天。
    #
    #   为什么"每小时"本来就不必要：本任务拉的是**全量在线工单**（非增量流水），
    #   看板上呈现的是"当前在线工单状态"，6 小时的刷新粒度对工单场景足够
    #   —— 工单不是秒级变化的实时指标。若日后确需更高频，**同时**把 TTL 调长
    #   或确认缓存命中，不要只把 cron 调密。
    dict(task_id="sp_online_sync", name="SP Online 工单同步", name_en="SP Online Ticket Sync",
         loader=("backend.services.sp_online_sync", "run_sp_online_sync"),
         description="从 eFlow SP 接口（sp-outbound/sp-inbound/sp-transfer）拉全量在线工单，写入 app.db 表 sp_outbound / sp_inbound / sp_transfer（Table Browser 可查）。每 6 小时一轮，避免每轮都触发一次 eFlow 登录",
         description_en="Fetch all online tickets from eFlow SP APIs (sp-outbound/sp-inbound/sp-transfer) into app.db tables sp_outbound / sp_inbound / sp_transfer (visible in Table Browser). Runs every 6 hours to avoid a fresh eFlow login each round",
         default_cron="35 */6 * * *", category="sp_online"),

    # 34c. SP 物料主数据同步（每天 04:55）：从 eFlow SP 物料接口拉全量写入 sp_material
    dict(task_id="sp_material_sync", name="SP 物料主数据同步", name_en="SP Material Master Sync",
         loader=("backend.services.sp_material_sync", "run_sp_material_sync"),
         description="从 eFlow SP 物料接口（eflow-sp-material）拉全量物料主数据，写入 app.db 表 sp_material（按 materialNo 唯一键 upsert，Table Browser 可查）",
         description_en="Fetch the full material master from eFlow SP (eflow-sp-material) into app.db table sp_material (upsert by materialNo, visible in Table Browser)",
         default_cron="55 4 * * *", category="sp_material"),

    # 34. CN EMS KPI 原始文件缓存同步（每15分钟）：EMS SFTP 只保留约1天原始PM文件，
    #     靠白天持续增量缓存把整天数据在服务端清理前保住（fetch 模式只下载缺失文件，轻量）
    dict(task_id="ems_kpi_cache_sync", name="CN EMS KPI 缓存同步", name_en="CN EMS KPI Cache Sync",
         loader=("backend.services.cn_ems.ems_kpi_service", "run_ems_kpi_cache_sync"),
         description="每15分钟增量下载 CN EMS(10.100.2.240) 当日(UTC)原始 PM 测量文件到本地缓存 _pmcache（服务器仅保留约1天；只下载缺失文件不解析）",
         description_en="Every 15 min, incremental download of today's (UTC) raw PM measurement files from CN EMS SFTP into local _pmcache cache (server retains ~1 day; fetch-only, no parsing)",
         default_cron="*/15 * * * *", category="cn_ems"),

    # 35. CN EMS KPI 日粒度 CSV 生成（每天 00:20 GMT = 北京 08:20）：聚合前一个完整 UTC 日，
    #     按 Query_Template.xml + samples 公式输出 csv_out/<模板名>.csv（与 GUI 导出同格式）
    dict(task_id="ems_kpi_daily", name="CN EMS KPI 日粒度CSV", name_en="CN EMS KPI Daily CSV",
         loader=("backend.services.cn_ems.ems_kpi_service", "run_ems_kpi_daily"),
         description="聚合前一个完整UTC日的 CN EMS KPI 并生成 csv_out/<模板名>.csv（VLR/USSD/语音/位置更新/License/TDD/Data订阅者 7模板）；先 best-effort 补抓前一日窗口再纯本地缓存聚合",
         description_en="Aggregate previous complete UTC day of CN EMS KPIs into csv_out/<TEMPLATE>.csv per Query_Template.xml (7 templates); best-effort server refetch then parse purely from local cache",
         default_cron="20 0 * * *", category="cn_ems"),

    # 36. CXO 看板 last-known-good 缓存同步（每 10 分钟）：经本机 8790 VMAX 代理拉全量看板接口，
    #     空值保留旧值，落盘 data/cxo_dashboard/last_known_good.json 供前端兜底展示
    dict(task_id="cxo_dashboard_cache_sync", name="CXO看板数据缓存同步", name_en="CXO Dashboard Cache Sync",
         loader=("backend.services.cxo_dashboard_cache", "run_cxo_dashboard_cache_sync"),
         description="每10分钟经本机8790 VMAX代理拉取CXO看板全量接口，按接口粒度合并为last-known-good缓存（空值保留旧值），落盘 data/cxo_dashboard/last_known_good.json 供看板兜底展示",
         description_en="Every 10 min pull all CXO dashboard APIs via local 8790 VMAX proxy, merge per-endpoint into a last-known-good cache (empty fetch keeps old value), written to data/cxo_dashboard/last_known_good.json as the dashboard fallback",
         default_cron="*/10 * * * *", category="general"),

    # 37. eFlow 告警关联规则收集（每 3 天 23:59）：拉取规则类型目录 + 关联规则导出 Excel
    dict(task_id="eflow_alarm_rules_collect", name="eFlow 告警规则收集", name_en="eFlow Alarm Rules Collect",
         loader=("backend.services.eflow_rules.eflow_Alarm_Rule_Collector", "run_eflow_alarm_rules"),
         description="每 3 天 23:59 从 eFlow 拉取规则类型目录与告警关联规则（correlation-mgt），导出 backend/services/eflow_rules/eflow_alarm_rules.xlsx（Alarm_Rules + Rule_Types 两个 Sheet）",
         description_en="Every 3 days at 23:59: pull rule types and alarm correlation rules from eFlow (correlation-mgt) into backend/services/eflow_rules/eflow_alarm_rules.xlsx (sheets Alarm_Rules + Rule_Types)",
         default_cron="59 23 */3 * *", category="eflow"),

    # 38. eFlow 推单/配置规则收集（每 3 天 23:59）：config-center 空 filter 全量规则导出 Excel
    dict(task_id="eflow_push_rules_collect", name="eFlow 推单规则收集", name_en="eFlow Push Rules Collect",
         loader=("backend.services.eflow_rules.eflow_Push_Rule_Collector", "run_eflow_push_rules"),
         description="每 3 天 23:59 从 eFlow config-center 拉取全部规则（query filter=\"\"，推单/升级/分组/自动关闭等 28 种类型），逐条合并 detail，导出 backend/services/eflow_rules/eflow_push_rules.xlsx（Push_Rules + Rule_Type_Summary 两个 Sheet）",
         description_en="Every 3 days at 23:59: pull all rules from eFlow config-center (query filter=\"\", 28 rule types incl. push/level/group/auto-close), merge detail per rule into backend/services/eflow_rules/eflow_push_rules.xlsx (sheets Push_Rules + Rule_Type_Summary)",
         default_cron="59 23 */3 * *", category="eflow"),

    # 39. 日志文件清理（每天 03:17）：2026-09-11 新增。log/ 下 runtime 日志此前由各 watchdog
    #     以 open(...,"ab") 追加且把句柄交给子进程继承 —— Windows 下被占用的文件无法轮转，
    #     单文件曾涨到 177MB（合计 466MB）。已改为父进程 pipe 泵 + 单文件超 LOG_ROTATE_MAX_MB
    #     （默认 100MB）自动切 _pN 分片（见 backend/log_writer.py）。本任务负责把已无进程
    #     写入的旧命名日志补日期后缀，并删除 mtime 超过 7 天的 log/*.log（含分片）。
    dict(task_id="log_cleanup", name="日志文件清理", name_en="Log Files Cleanup",
         loader=("backend.services.log_cleanup", "run_log_cleanup"),
         description="清理 my_app/log 下超过保留期（默认7天）的日志文件，并把已无进程写入的旧命名日志补上日期后缀；与各 watchdog 按日期命名配合实现滚动保留",
         description_en="Purge log files older than retention (default 7 days) under my_app/log; rename legacy no-longer-written logs with a date suffix",
         default_cron="17 3 * * *", category="general"),

    # 40. VMAX CXO 天粒度日值归档（每小时 :15，2026-09-15 新增，服务 vmaxCxoDashboard_Daily 页）：
    #     VMAX 无原生天粒度（Granularity 枚举只到 1hour），故拉 1hour 明细本地按日聚合。
    #     上游小时明细仅保留约 8 天 -> 必须每天落盘累积成自己的日存，才能铺满「本周/前一周/前两周」。
    #     独立文件 + 独立目录 data/vmax_cxo_daily/，不读写 cxo_dashboard 的 last_known_good，
    #     也不调用 ensure_proxy（不把重启逻辑压到现有看板共用的 8790 代理上），故与任务 36 互不影响。
    dict(task_id="vmax_cxo_daily_sync", name="VMAX CXO天粒度日值归档", name_en="VMAX CXO Daily Value Archive",
         loader=("backend.services.vmax_cxo_daily_cache", "run_vmax_cxo_daily_sync"),
         description="每小时经8790 VMAX代理按监控批量拉取最近8天的1hour明细（共50个指标：6个CXO趋势 + 14个网络KPI + 30个服务/OTT KPI，压成8个多列请求），按流量SUM/用户PEAK/速率AVG聚合为日值，落盘 data/vmax_cxo_daily/daily.json 供页签化天粒度看板累积回看三周",
         description_en="Hourly: batch-pull the last 8 days of 1-hour detail for 50 KPIs (6 CXO trend + 14 network + 30 service/OTT) from the 8790 VMAX proxy as 8 multi-column requests, aggregate per day (SUM for volume, PEAK for users, AVG for rates) into data/vmax_cxo_daily/daily.json for the tabbed daily board",
         default_cron="15 * * * *", category="general"),

    # 41. VMAX 多报表指标采集（每小时 :45，2026-09-16 新增）：按用户抓包的 vreport 请求
    #     （backend/services/vmax_multi_data/url.txt）从 VMAX 取两个 CIService 报表的指标：
    #       sys_5gsa_traffic_ciservice（5GSA 流量，表 aggr_5gsa_flow_ciservice）
    #       sys_5gsa_video_ciservice （5GSA 视频）
    #     走 server/report_query（RSA encryptLong 信封 + X-Content-Type: application/x-vmax-s-rsa-encrypted），
    #     维度/指标默认取 design.json 的 defaultSelected，可在配置里指定；
    #     落盘 data/vmax_multi_data/<key>_latest.json + vmax_multi_data.sqlite3（kpi_rows/sync_runs）。
    #     与任务 40 错峰（:15/:45），同样复用 8790 代理会话，不新开 VMAX 门户会话。
    dict(task_id="vmax_multi_data_sync", name="VMAX 多报表指标采集", name_en="VMAX Multi-Report KPI Collect",
         loader=("backend.services.vmax_multi_data.vmax_multi_data_service", "run_vmax_multi_data_sync"),
         description="每小时经8790 VMAX代理按 url.txt 抓包的 vreport 报表（sys_5gsa_traffic_ciservice 5GSA流量 / sys_5gsa_video_ciservice 5GSA视频）拉取指标明细（report_query，RSA分块加密参数），落盘 data/vmax_multi_data/<报表>_latest.json 与 vmax_multi_data.sqlite3（kpi_rows 明细 + sync_runs 运行记录）",
         description_en="Hourly: fetch the vreport reports captured in url.txt (sys_5gsa_traffic_ciservice / sys_5gsa_video_ciservice) from VMAX via the 8790 proxy using server/report_query (RSA-encrypted params), persisting to data/vmax_multi_data/<key>_latest.json and vmax_multi_data.sqlite3 (kpi_rows + sync_runs)",
         default_cron="45 * * * *", category="general"),

    # 42. OLIB SOC VMAX 例行报表（每月 1 日 07:30，2026-09-16 新增）：用户 notebook
    #     （OLIB SOC VMAX Routine Report）原本是人工在 JupyterLab 上按天循环 SQL 出 Excel；
    #     这里直连数仓 GBase 8a（10.123.255.12:5258，MySQL 协议，pymysql）自动化。
    #     9 个块 → 9 个 sheet：traffic / Active_user / cache / GUW / Video / game / TCP /
    #     df_TOP_Service / df_TOP_Video，SQL 从 notebook 原样移植（表族 _day_ 分区 ≈90 天）。
    #     与任务 41 的区别：41 走门户 vreport 接口（只有预聚合粒度 + TopN 截断），
    #     本任务走数仓明细，能出业务/APP/缓存服务器/网元维度；已与门户口径逐字节对账一致。
    #     产物 data/olib_soc_report/OLIB SOC VMAX <label>.xlsx + olib_soc_report.sqlite3。
    dict(task_id="olib_soc_vmax_report", name="OLIB SOC VMAX 例行报表", name_en="OLIB SOC VMAX Routine Report",
         loader=("backend.services.olib_soc_report.olib_soc_report_service", "run_olib_soc_report"),
         description="直连 VMAX 数仓 GBase（10.123.255.12:5258, 库 zxvmax）按日分区跑 notebook 移植的 9 段 SQL（traffic/Active_user/cache/GUW/Video/game/TCP/TOP业务/TOP视频），生成多 sheet Excel 与运行记录；默认出上一个自然月，可配 last_n_days/weekly/explicit，窗口自动截断到数仓 90 天保留期内",
         description_en="Direct GBase DWH queries (daily partitions) for the 9 notebook report blocks, producing a multi-sheet Excel plus run records; default window = previous calendar month, clamped to the ~90-day partition retention",
         default_cron="30 7 1 * *", category="olib_soc"),

    # 43. OLIB SOC 看板 KPI 每日增量（06:20，2026-09-16 新增）：给 VMAX 90 天经营看板
    #     （?page=vmaxCxoDashboard_90Days）供数。只跑看板需要的 7 个块、只补 daily_kpi 里
    #     缺的日期（默认回看 7 天，幂等自愈），正常情况下每天 1 天数据、几秒钟，不出 Excel。
    #     2026-09-24 加固：除「整天没有行」的天，还补「有行但关键指标为 NULL」的天 ——
    #     某次运行单个块临时取数失败会写入一行但该列留 NULL，旧逻辑不认为是缺口，
    #     导致 2026-09-18~23 的 active_user 连丢 6 天（见 kpi_store.incomplete_days）。
    dict(task_id="olib_soc_kpi_daily_sync", name="OLIB SOC 看板 KPI 增量", name_en="OLIB SOC Dashboard KPI Sync",
         loader=("backend.services.olib_soc_report.olib_soc_report_service", "run_olib_soc_kpi_sync"),
         description="每日增量补齐 VMAX 90 天经营看板的 KPI 库（daily_kpi 表）：只跑流量/活跃用户/缓存/视频/游戏/TCP/TOP业务 7 个块，只取缺的日期 + 关键指标为 NULL 的残缺日 + 重取最新 1 天（默认回看 7 天，幂等自愈），不出 Excel",
         description_en="Daily incremental fill of the 90-day CXO dashboard KPI store (daily_kpi): 7 dashboard blocks, missing days plus days whose key metrics are NULL plus the newest day re-read (7-day lookback, idempotent), no Excel output",
         # 06:20（服务器 UTC）：数仓「前一天」分区不一定在零点后立刻完成，
         # 与 ems_kpi_daily(05:20) 同一批早班；配合 refresh_last_days 双保险。
         default_cron="20 6 * * *", category="olib_soc"),

    # 44. TMP 目录定期清理（每天 03:47，2026-09-18 新增）：TMP/ 是临时产物固定去处
    #     （见 CODE_CLEANUP_GUIDE），但体积没人管，上线首日实测 462MB（4 个
    #     _diag*_eflow_* 诊断目录占 ~380MB）。两段式回收：超 7 天条目同盘 mv 进
    #     TMP/_quarantine_YYYYMMDD/（可还原），隔离再超 7 天才真删；服务在用路径
    #     （charts/dl/状态文件）白名单永不处理。与 log_cleanup(03:17) 错峰。
    dict(task_id="tmp_cleanup", name="TMP 目录清理", name_en="TMP Directory Cleanup",
         loader=("backend.services.tmp_cleanup", "run_tmp_cleanup"),
         description="隔离 my_app/TMP 下超过保留期（默认7天）的临时产物到 _quarantine_ 目录，隔离满 7 天后彻底删除；白名单保护服务在用路径",
         description_en="Quarantine TMP entries idle beyond retention (default 7 days) into _quarantine_ dirs, purge quarantine after another 7 days; service paths whitelisted",
         default_cron="47 3 * * *", category="general"),

    # 45. TTs and MTTR 月粒度报表生成（每天 07:20，2026-10-04 新增）
    #     读 eflow_sync 每小时产出的 Site Down hourly Report（Processed Data 页），
    #     产出「分月 TTs / MTTR / SLA 目标」组合图工作簿给 EmailReports 页签下载。
    #     纯本地文件读写（实测 9.4 秒），不调 eFlow API，故归 m 组；
    #     排在 07:20 是为了读到 eflow_sync(每小时 :00) 当天第一期产出的数据。
    #     需要更高频的话在任务管理页改 cron 即可，不必改代码（产物按 mtime 只留最新 1 份）。
    dict(task_id="tt_mttr_report_generate", name="TTs and MTTR 报表生成", name_en="TTs and MTTR Report Generate",
         loader=("backend.services.tt_mttr_report", "run_tt_mttr_report"),
         description="从最新 Site Down hourly Report 生成 TTs and MTTR (Hour).xlsx：有 WO + 告警发生→清除历时<48h + Site Category 非空 + 2026-01 起，Summary 用 COUNTIFS/AVERAGEIFS 公式分月统计并出 P1~P4 组合图",
         description_en="Build TTs and MTTR (Hour).xlsx from the latest Site Down hourly Report: WO present + occur-to-clear < 48h + non-empty Site Category + from 2026-01; Summary counts via COUNTIFS/AVERAGEIFS formulas with P1-P4 combo charts",
         default_cron="20 7 * * *", category="eflow"),
]

# ========== 网关分组（按「获取数据的外部系统」归类，与 category 平行） ==========
# category 颗粒度较细（ran_ume / main_kpi / network_kpi / packet_loss 都属 RAN UME），
# gateway 用于任务管理页的一级分组展示。新增 category 时务必在此补充映射，否则回退 "system"。
CATEGORY_GATEWAY: dict[str, str] = {
    # ZTE eFlow API：TT/WO/CR/PM/Site/Person 及 incident_overview / SP 在线工单同源
    "eflow": "eflow_api",
    "incident_overview": "eflow_api",
    "sp_online": "eflow_api",
    # eFlow SP 物料主数据（eflow-sp-material）同源 eFlow API
    "sp_material": "eflow_api",
    # RAN UME：PM/KPI/丢包率/CM 配置数据均来自 RAN UME
    "ran_ume": "ran_ume",
    "main_kpi": "ran_ume",
    "network_kpi": "ran_ume",
    "packet_loss": "ran_ume",
    "cm_data": "ran_ume",
    # UME Dong customer 业务 KPI（门户 172.17.208.1:28808，同属 UME 家族）
    "ume_in": "ran_ume",
    # CNN / iPRAN UME 核心网与路由器
    "cnn_kpi": "cnn_ume",
    "ipran_kpi": "ipran_ume",
    # MW UME 微波（ZXMW 系列）
    "mw_ume": "mw_ume",
    # CN EMS UME（ZTE U31 网管 10.100.2.240）
    "cn_ems": "cn_ems_ume",
    # 备件 SFTP
    "sp": "sp_sftp",
    # FW 吞吐（DPtech UMC）
    "fw_kpi": "dp_umc",
    # 电池 UME
    "battery": "battery_ume",
    # 邮件 / WhatsApp 通知通道
    "email": "email",
    "kpi_email": "email",
    "whatsapp": "whatsapp",
    # 系统 / 内部运维（不依赖外部数据网关）
    "site_outage": "system",
    "ms_sla": "system",
    "mailbox": "system",
    "general": "system",
    # VMAX 数仓 GBase 8a 直连（10.123.255.12:5258，只读取数）
    "olib_soc": "vmax_gbase",
}

# 将 gateway 注入每个 spec，作为一级分组真相源（前端按此动态分组，不再硬编码 ROW_GROUPS）
for _spec in TASK_SPECS:
    _spec.setdefault("gateway", CATEGORY_GATEWAY.get(_spec.get("category"), "system"))


# ========== 主开关豁免名单（Task Manager Master switch exemption）==========
# 背景（2026-10-05 排查）：主开关的 ON 语义是「全部任务都启用」，前端判定为
# `allTasks.every(t => t.enabled)`。但有些任务**按业务决定就该长期保持关闭**
# （典型：`whatsapp_send_ext` 与 Playwright 版 `whatsapp_send` 并存，只保留一条
# 发送通道即可）。这类任务一旦被单独关闭，`every()` 恒为 false，主开关会永远显示
# 关闭 —— 用户点开它，后端把 69 个全部写成启用，重新拉取后该任务仍是关闭
# （数据库覆盖优先），开关当场弹回，表现为「怎么点都关着」，且**每次都把用户
# 刻意关掉的任务重新打开**，属于静默违背用户意图。
#
# 因此引入显式豁免：列入本名单的 task_id 有两层语义 ——
#   ① `toggle_all_tasks` 跳过它们，一键操作不再擅自打开/关闭；
#   ② 前端主开关的「是否全部启用」判定排除它们，开关状态得以稳定保持。
# 任务自身的 enabled 仍可在界面上单独开关（豁免只针对「一键」）。
#
# 维护约定：新增豁免必须在此写明**为什么它应当长期保持关闭**，否则后来又有人
# 把它当成「忘开的任务」加回主开关，问题会复发。
MASTER_SWITCH_EXEMPT_IDS = frozenset({
    # 与 whatsapp_send 功能重叠（同为 Site Outage 截图投递，一个走 Playwright、
    # 一个走浏览器扩展），业务上只需保留一条通道，故长期关闭扩展版。
    "whatsapp_send_ext",
    # 2026-10-08 新增 whatsapp_send_baileys：第三种发图通道，走 Baileys 协议。
    # 与 whatsapp_send（Playwright）默认并存而非互斥，但因 Baileys 违反 WhatsApp ToS，
    # 默认禁用、走人工启用路径；批量主开关跳过它，避免「一键启用」把它打开。
    "whatsapp_send_baileys",
})


def is_master_switch_exempt(task_id: str) -> bool:
    """该任务是否豁免于主开关（一键启用/禁用全部）的批量操作与状态判定。"""
    return task_id in MASTER_SWITCH_EXEMPT_IDS


def register_all_tasks(task_runner) -> int:
    """将 TASK_SPECS 中的全部任务注册到 task_runner，返回注册数量"""
    for spec in TASK_SPECS:
        func = spec.get("func")
        call_chain = None
        if func is None:
            module_path, func_name = spec["loader"]
            func = _lazy_loader(module_path, func_name)
            # 懒加载任务：静态分析只能解析到 import_module，故显式给出入口节点，
            # 让 Task Manager 调用链展示真实服务函数名（DB/文件标注由 task_runner 补充）
            call_chain = [f"{func_name} ({module_path.replace('.', '/')}.py)"]
        task_runner.register_task(
            task_id=spec["task_id"],
            name=spec["name"],
            name_en=spec["name_en"],
            func=func,
            description=spec["description"],
            description_en=spec["description_en"],
            default_cron=spec["default_cron"],
            category=spec["category"],
            gateway=spec.get("gateway", CATEGORY_GATEWAY.get(spec.get("category"), "system")),
            # enabled 默认 True；whatsapp_send_baileys 用 enabled=False 让新部署**默认禁用**，
            # 业务侧在「任务管理」页手动启用（走人工审批路径，避免 Baileys ToS 风险）。
            # 与 task_schedule_config 的优先级见 task_runner.register_task 内部三目运算。
            enabled=spec.get("enabled", True),
            call_chain=call_chain,
            # 主开关豁免随注册一并注入，供 task_runner 的批量切换与 /api/tasks 回传使用
            master_switch_exempt=is_master_switch_exempt(spec["task_id"]),
        )
    logger.info(f"任务注册完成：{len(TASK_SPECS)} 个任务")
    return len(TASK_SPECS)
