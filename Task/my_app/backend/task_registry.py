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

logger = logging.getLogger(__name__)

# 兼容旧 eFlow API 的同步历史（main.py 的 /api/eflow/status 会读取）
sync_history = []


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
    """生成懒加载包装：调用时才 import 目标模块函数"""
    def _run():
        module = importlib.import_module(module_path)
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

    # 6. MS SLA 完整同步（每6小时）
    dict(task_id="ms_sla_full", name="MS SLA 完整同步", name_en="MS SLA Full Sync",
         loader=("backend.services.ms_sla_service", "run_full_sync"),
         description="SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）",
         description_en="SLA metrics sync + Contract KPIs report update (self-contained, no external files)",
         default_cron="0 */6 * * *", category="ms_sla"),

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

    # 9. RAN UME Main KPI 同步（每天凌晨4点）
    dict(task_id="main_kpi_sync", name="RAN Main KPI 同步", name_en="RAN Main KPI Sync",
         loader=("backend.services.ran_ume_main_kpi", "run_main_kpi_sync"),
         description="RAN UME Main KPI 历史指标同步（2G/3G/4G x Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传",
         description_en="RAN UME Main KPI history sync (2G/3G/4G x Cells/Sites/Group/NW), export Excel and incremental SQLite update + FTP upload",
         default_cron="0 4 * * *", category="main_kpi"),

    # 10. RAN UME Network KPI（Zeenshan）同步（每天凌晨5点）
    dict(task_id="network_kpi_sync", name="RAN Network KPI 同步", name_en="RAN Network KPI Sync",
         loader=("backend.services.ran_ume_network_kpi", "run_network_kpi_sync"),
         description="RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G x Group/NW），导出 Excel 并导入 SQLite + FTP 上传",
         description_en="RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G x Group/NW), export Excel and import to SQLite + FTP upload",
         default_cron="0 5 * * *", category="network_kpi"),

    # 11. CNN UME KPI 同步（每天凌晨6点）
    dict(task_id="cnn_kpi_sync", name="CNN UME KPI 同步", name_en="CNN UME KPI Sync",
         loader=("backend.services.ccn_ume_kpi_service", "run_cnn_kpi_sync"),
         description="CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN",
         description_en="CNN UME Core Network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN",
         default_cron="0 6 * * *", category="cnn_kpi"),

    # 12. SP 备件数据同步（每天凌晨7点）
    dict(task_id="sp_data_sync", name="SP 备件数据同步", name_en="SP Spare Data Sync",
         loader=("backend.services.get_sp_table", "run_sp_data_sync"),
         description="从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db",
         description_en="Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db",
         default_cron="0 7 * * *", category="sp"),

    # 13. iPRAN UME KPI 同步（每天凌晨8点）
    dict(task_id="ipran_kpi_sync", name="iPRAN UME KPI 同步", name_en="iPRAN UME KPI Sync",
         loader=("backend.services.ipran_ume_kpi_service", "run_ipran_kpi_sync"),
         description="iPRAN UME M6000 路由器 KPI 同步（HQ M6K-FW 等），导出 Excel 并导入 SQLite + FTP 上传",
         description_en="iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel and import to SQLite + FTP upload",
         default_cron="0 8 * * *", category="ipran_kpi"),

    # 14. Liberia 站点宕 1 小时报告邮件（每小时第5分钟）
    dict(task_id="liberia_email_1h", name="Liberia 宕站 1小时报告邮件", name_en="Liberia Site-Down 1H Report Email",
         loader=("backend.services.liberia_email_report", "run_1h_report"),
         description="发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单",
         description_en="Email Liberia Orange Site Down hourly Report (inline images + Excel) to recipient lists",
         default_cron="5 * * * *", category="email"),

    # 15. Liberia 站点宕 8 小时报告邮件（每8小时第10分钟）
    dict(task_id="liberia_email_8h", name="Liberia 宕站 8小时报告邮件", name_en="Liberia Site-Down 8H Report Email",
         loader=("backend.services.liberia_email_report", "run_8h_report"),
         description="发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单",
         description_en="Email Liberia Orange Site Down 8 hours Report (inline images + Excel) to recipient lists",
         default_cron="10 */8 * * *", category="email"),

    # 16. MS Contract KPIs Achievements Daily Report 邮件（数据本地 ms_sla）
    dict(task_id="kpi_ms_contract", name="MS Contract KPIs 日报邮件", name_en="MS Contract KPIs Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ms_contract_kpi"),
         description="发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）",
         description_en="Email MS Contract KPIs Achievements Daily Report (local data + remote recipient list)",
         default_cron="30 17 * * *", category="kpi_email"),

    # 17. MS WOs SLA Achievements Daily Report 邮件（数据本地 ms_sla）
    dict(task_id="kpi_ms_wo_sla", name="MS WOs SLA 日报邮件", name_en="MS WOs SLA Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ms_wo_sla"),
         description="发送 MS WOs SLA Achievements Daily Report（本地数据 + 远程名单）",
         description_en="Email MS WOs SLA Achievements Daily Report (local data + remote recipient list)",
         default_cron="35 17 * * *", category="kpi_email"),

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

    # 20. MS Network Availability Daily Report 邮件（远程 FTP 图片，无 Excel）
    dict(task_id="kpi_ran_availability", name="MS Network Availability 日报邮件", name_en="MS Network Availability Daily Report Email",
         loader=("backend.services.kpi_email_report", "run_ran_availability"),
         description="发送 MS Network Availability Daily Report（远程 FTP 图片 + 远程名单，无 Excel）",
         description_en="Email MS Network Availability Daily Report (remote FTP images + remote recipient list, no Excel)",
         default_cron="30 9 * * *", category="kpi_email"),

    # 21. EWS 恢复后自动补发失败邮件（每 20 分钟探测 EWS 可用性并补发）
    dict(task_id="email_recovery", name="EWS 恢复后邮件补发", name_en="Email Recovery after EWS Restored",
         loader=("backend.services.email_recovery", "run_email_recovery_task"),
         description="探测 EWS 是否恢复；恢复后自动补发近 3 小时内因 EWS 超时失败的邮件任务",
         description_en="Probe EWS reachability; auto re-send email tasks that failed due to EWS timeout in last 3h once server is back",
         default_cron="*/20 * * * *", category="email"),

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
    dict(task_id="battery_kpi_sync", name="电池 KPI 同步", name_en="Battery KPI Sync",
         loader=("backend.services.battary_kpi_fetch.battery_kpi_service", "run_battery_kpi_sync"),
         description="从 UME(192.168.170.2) 拉取电池实时 KPI（健康度/SOC/充放电状态），全程内存不落盘，写入 battery_kpi.sqlite3 供电池看板使用",
         description_en="Fetch battery realtime KPI (health/SOC/charge status) from UME(192.168.170.2), in-memory only, write to battery_kpi.sqlite3 for Battery Dashboard",
         default_cron="5 * * * *", category="battery"),
    # 28. 电池 KPI 邮件（每天 07:00 与 19:00）
    dict(task_id="battery_email", name="电池 KPI 邮件", name_en="Battery KPI Email",
         loader=("backend.services.battary_kpi_fetch.battery_kpi_service", "run_battery_email"),
         description="将电池 KPI 报表（Excel）发送至远程名单中的邮箱，每日 07:00 与 19:00 各一次",
         description_en="Email the battery KPI report (Excel) to recipients from remote FTP list, daily at 07:00 & 19:00",
         default_cron="0 7,19 * * *", category="battery"),

    # 27. 邮箱空间守卫（每小时第 0 分钟）：容量超阈值自动清理最旧邮件，避免存储上限告警
    dict(task_id="mailbox_cleanup", name="邮箱空间清理", name_en="Mailbox Storage Guard",
         loader=("backend.services.mailbox_cleanup", "run_mailbox_cleanup"),
         description="每小时检查 Exchange 邮箱（ztenoc.olr@orange.com）：邮件数>500 且 空间>70% 时，硬删除最旧 200 封邮件，避免 'storage limit' 告警",
         description_en="Hourly guard for Exchange mailbox (ztenoc.olr@orange.com): when count>500 AND usage>70%, hard-delete the 200 oldest emails to avoid the 'storage limit' warning",
         default_cron="0 * * * *", category="mailbox"),

    # 28. Incident Overview 数据同步（每小时整点）：从远程 FineBI FTP 拉取最新 incident_overview.xlsx
    dict(task_id="incident_overview_sync", name="Incident Overview 数据同步", name_en="Incident Overview Data Sync",
         loader=("backend.services.incident_overview_sync", "run_incident_overview_sync"),
         description="每小时整点从远程 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，落盘为版本化文件 + current.json 指针（Excel 一直打开也不会失败），best-effort 刷新 incident_overview.xlsx 快照",
         description_en="Hourly on-the-hour: pull the latest incident_overview.xlsx from remote FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ across all subfolders, store as versioned file + current.json pointer (immune to Excel lock), best-effort refresh snapshot",
         default_cron="0 * * * *", category="incident_overview"),

    # 29. 数据库数据新鲜度巡检（每小时第 15 分钟）
    dict(task_id="db_freshness_check", name="数据库数据新鲜度巡检", name_en="DB Data Freshness Check",
         loader=("backend.services.db_freshness_check", "run_db_freshness_check"),
         description="每小时巡检远程 DB（db_writer_api）与本地回退库各表最新数据日期，滞后时输出调用链路与检查方向",
         description_en="Hourly freshness audit of remote DBs (via db_writer_api) and local fallback DBs; outputs call chain and troubleshooting guidance when stale",
         default_cron="15 * * * *", category="general"),

    # 30. 失败任务自动重试（每 10 分钟扫描，失败后无成功记录补上缺口即重试）
    dict(task_id="auto_retry_failed", name="失败任务自动重试", name_en="Failed Task Auto Retry",
         loader=("backend.services.auto_retry", "run_auto_retry_task"),
         description="每 10 分钟扫描失败任务；若失败造成的数据缺口尚未被后续成功执行补上（或已超 24h 硬上限则放弃）且未超过重试次数上限，自动重新投递执行（邮件任务由 EWS 补发机制负责，默认排除）",
         description_en="Scan failed tasks every 10 minutes; re-run those whose data gap has not been filled by a later successful run (give up beyond the 24h hard cap) and under the retry budget (email tasks are handled by EWS recovery and excluded)",
         default_cron="*/10 * * * *", category="general"),

    # 31. RAN UME CM 小区配置数据同步（每天 8:30）
    dict(task_id="cm_data_sync", name="RAN CM 小区数据同步", name_en="RAN CM Cell Data Sync",
         loader=("backend.services.cm_data.cm_data_export", "run_cm_data_sync"),
         description="从 RAN UME 获取 GSM/UMTS/LTE/NR 小区配置数据，经 API 全量替换写入远程 db.sqlite3（cm_cell_data/cm_site_summary），本地仅保留一份最新 Excel",
         description_en="Fetch GSM/UMTS/LTE/NR cell config data from RAN UME, full-replace write to remote db.sqlite3 (cm_cell_data/cm_site_summary) via API, keep only the latest local Excel",
         default_cron="30 8 * * *", category="cm_data"),
]

# ========== 网关分组（按「获取数据的外部系统」归类，与 category 平行） ==========
# category 颗粒度较细（ran_ume / main_kpi / network_kpi / packet_loss 都属 RAN UME），
# gateway 用于任务管理页的一级分组展示。新增 category 时务必在此补充映射，否则回退 "system"。
CATEGORY_GATEWAY: dict[str, str] = {
    # ZTE eFlow API：TT/WO/CR/PM/Site/Person 及 incident_overview 同源
    "eflow": "eflow_api",
    "incident_overview": "eflow_api",
    # RAN UME：PM/KPI/丢包率/CM 配置数据均来自 RAN UME
    "ran_ume": "ran_ume",
    "main_kpi": "ran_ume",
    "network_kpi": "ran_ume",
    "packet_loss": "ran_ume",
    "cm_data": "ran_ume",
    # CNN / iPRAN UME 核心网与路由器
    "cnn_kpi": "cnn_ume",
    "ipran_kpi": "ipran_ume",
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
}

# 将 gateway 注入每个 spec，作为一级分组真相源（前端按此动态分组，不再硬编码 ROW_GROUPS）
for _spec in TASK_SPECS:
    _spec.setdefault("gateway", CATEGORY_GATEWAY.get(_spec.get("category"), "system"))


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
            call_chain=call_chain,
        )
    logger.info(f"任务注册完成：{len(TASK_SPECS)} 个任务")
    return len(TASK_SPECS)
