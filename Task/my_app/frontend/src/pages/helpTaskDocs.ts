/* ==================== 任务清单详解数据（供 Help 页「任务管理详解」使用） ====================
 * 内容依据 backend/task_registry.py 的 TASK_SPECS（55 条声明）、
 * backend/worker_watchdog.py 的 GROUP_TASK_MAP（worker 分组）以及
 * docs/manual/04-task-system.md、14-integrations.md、03-data-layer.md 整理。
 * 改动后端任务注册表时请同步更新本文件（字段：cron / group / script / flow / maintain）。
 * ================================================ */

export interface TaskDocText {
  name: string
  desc: string
  /** 工作流：上游 → 处理 → 落地/出口 */
  flow: string[]
  /** 维护要点 */
  maintain: string[]
}

export interface TaskDoc {
  id: string
  group: 'u' | 'n' | 'm' | 'c'
  cron: string
  /** 工作流脚本（backend/services/ 下的模块） */
  script: string
  zh: TaskDocText
  en: TaskDocText
}

export const WORKER_GROUP_INFO: Record<string, { zh: string; en: string }> = {
  u: {
    zh: 'RAN UME 单账号会话，组内必须串行（并发会被踢会话）',
    en: 'RAN UME single-account session; tasks run serially (parallel runs kick the session)',
  },
  n: {
    zh: '网管 / eFlow API / 远程系统：彼此独立但保守同组',
    en: 'NMS / eFlow API / remote systems: independent but conservatively grouped',
  },
  m: {
    zh: '内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖',
    en: 'Housekeeping tasks: EWS mail session + screenshot/WhatsApp file dependencies',
  },
  c: {
    zh: 'CN EMS 独立会话：缓存同步与日聚合共享 _pmcache，同组保证互斥',
    en: 'CN EMS dedicated session: cache sync & daily aggregation share _pmcache, serialized for mutual exclusion',
  },
}

export const TASK_DOCS: TaskDoc[] = [
  {
    id: 'eflow_sync', group: 'n', cron: '22 * * * *',
    script: 'services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")',
    zh: {
      name: 'eFlow 数据同步',
      desc: '从 ZTE eFlow API 增量同步 TT/WO/CR/PM/Site/Person 六类数据',
      flow: ['每小时 :22 调 eFlow API 增量拉取 TT/WO/CR/PM/Site/Person', '清洗后写主库动态 eFlow 表（运行时按上游字段建表，不进 Alembic）', '为 TT&WO / 告警 / GIS / eFlow 知识库等页面供数'],
      maintain: ['增量只拉新变更；发现漏数据靠次日 eflow_sync_full 全量兜底', '凭据分组 eflow；会话被踢会连续 failed，由 auto_retry_failed 自动重试'],
    },
    en: {
      name: 'eFlow Data Sync',
      desc: 'Incrementally sync TT/WO/CR/PM/Site/Person from the ZTE eFlow API',
      flow: ['Hourly :22 pull delta TT/WO/CR/PM/Site/Person from eFlow API', 'Clean and write into dynamic eFlow tables in the main DB (runtime-created, not in Alembic)', 'Feeds TT&WO / alarms / GIS / eFlow knowledge base pages'],
      maintain: ['Delta mode only fetches changes; gaps are backfilled next night by eflow_sync_full', 'Credential group eflow; kicked sessions cause consecutive failures, auto-retried by auto_retry_failed'],
    },
  },
  {
    id: 'eflow_sync_full', group: 'n', cron: '0 1 * * *',
    script: 'services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")',
    zh: {
      name: 'eFlow 每日全量同步',
      desc: 'eFlow 全量兜底：拉全量窗口（默认自 2026-01-01），补齐增量遗漏并刷新报告',
      flow: ['每天 01:00 按全量窗口拉取全部记录', '与增量写同一批主库表，去重覆盖', '完成后刷新相关报告产物'],
      maintain: ['白天发现 eFlow 缺数的首要修复手段，可在任务管理页手动执行一次', '全量窗口起点可配置，调整时注意拉取时长'],
    },
    en: {
      name: 'eFlow Daily Full Sync',
      desc: 'Full-window backfill (default since 2026-01-01) to cover delta gaps and refresh reports',
      flow: ['Daily 01:00 pull the full window', 'Write into the same dynamic tables with dedup', 'Refresh related report artifacts afterwards'],
      maintain: ['First remedy when eFlow data is missing mid-day — run it manually from Task Manager', 'The window start is configurable; mind the fetch duration when adjusting'],
    },
  },
  {
    id: 'ran_ume_daily', group: 'u', cron: '0 2 * * *',
    script: 'services/ran_ume_service.py → run_ran_ume_full_task',
    zh: {
      name: 'RAN UME 日报',
      desc: 'RAN UME PM 数据获取 + Daily Availability KPI 报表生成 + FTP 上传',
      flow: ['RSA 加密登录 RAN UME 网管查询 PM 数据', '生成 Daily Availability KPI 报表', '报表经 FTP 上传远程主机，供后续邮件/看板使用'],
      maintain: ['凭据分组 zte_ume；u 组内串行，前序任务卡住会顺延', '查询模板与回溯天数在 services/ran_ume_config.json'],
    },
    en: {
      name: 'RAN UME Daily Report',
      desc: 'Fetch RAN UME PM data, generate the Daily Availability KPI report, upload via FTP',
      flow: ['RSA-encrypted login to RAN UME NMS, query PM data', 'Generate the Daily Availability KPI report', 'Upload the report via FTP for later mail/board consumption'],
      maintain: ['Credential group zte_ume; serial within group u — a stuck predecessor delays this task', 'Query templates and days_back live in services/ran_ume_config.json'],
    },
  },
  {
    id: 'site_outage_screenshot', group: 'm', cron: '0 1 * * *',
    script: 'services/site_outage_service.py → run_site_outage_screenshot',
    zh: {
      name: 'Site Outage 截图',
      desc: '对告警管理看板（Site Outage Monitor）的 ERA/Regular/ALL 三个视图自动截图',
      flow: ['Playwright 打开告警管理看板页面', '分别对 ERA / Regular / ALL 视图截图落盘', '产出供 03:00 的 whatsapp_send 发送'],
      maintain: ['截图对象是 iframe 页 alarm-management.html——改该页 DOM 前先确认截图选择器仍找得到', '与 whatsapp_send 同在 m 组，靠 cron 时间顺序（01:00 → 03:00）保证先后'],
    },
    en: {
      name: 'Site Outage Screenshot',
      desc: 'Auto-screenshot the ERA/Regular/ALL views of the Site Outage Monitor board',
      flow: ['Playwright opens the Alarm Management board', 'Screenshots each of ERA / Regular / ALL views to disk', 'Output is consumed by whatsapp_send at 03:00'],
      maintain: ['Screenshots the iframe page alarm-management.html — before changing its DOM, verify the screenshot selectors still resolve', 'Shares group m with whatsapp_send; ordering is guaranteed by cron times (01:00 → 03:00)'],
    },
  },
  {
    id: 'whatsapp_send', group: 'm', cron: '0 3 * * *',
    script: 'services/whatsapp_service.py → run_whatsapp_send',
    zh: {
      name: 'WhatsApp 消息发送',
      desc: '发送 Site Outage 截图和文件到 WhatsApp 群组（Playwright 自动化）',
      flow: ['读取 01:00 site_outage_screenshot 产出的截图', 'Playwright 操作 WhatsApp Web 发送到群组'],
      maintain: ['依赖截图任务先成功；WhatsApp Web 登录态失效时需人工重新扫码'],
    },
    en: {
      name: 'WhatsApp Message Send',
      desc: 'Send Site Outage screenshots and files to WhatsApp groups (Playwright automation)',
      flow: ['Reads screenshots produced by site_outage_screenshot at 01:00', 'Drives WhatsApp Web via Playwright to send to groups'],
      maintain: ['Depends on the screenshot task finishing first; re-scan QR manually when the WhatsApp Web session expires'],
    },
  },
  {
    id: 'whatsapp_send_ext', group: 'm', cron: '0 3 * * *',
    script: 'services/whatsapp_ext_service.py → run_whatsapp_send_ext',
    zh: {
      name: 'WhatsApp 消息发送（扩展）',
      desc: 'WhatsApp 发送（扩展版）：投递发送作业，由浏览器扩展在已登录的 WhatsApp Web 中发送，与 Playwright 版并存',
      flow: ['投递发送作业到队列', '浏览器扩展（whatsapp_sender_extension）在已登录的 WhatsApp Web 标签页中实际发送'],
      maintain: ['2026-08-31 上线时曾漏登记 worker 分组导致 pending 卡死，后补入 m 组——新增任务务必同步登记 GROUP_TASK_MAP'],
    },
    en: {
      name: 'WhatsApp Message Send (Extension)',
      desc: 'Extension-based WhatsApp sending: dispatches a send job; a browser extension sends it in the logged-in WhatsApp Web (coexists with the Playwright version)',
      flow: ['Dispatch a send job to the queue', 'The browser extension (whatsapp_sender_extension) actually sends it in the logged-in WhatsApp Web tab'],
      maintain: ['Missed its worker-group registration on 2026-08-31 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP'],
    },
  },
  {
    id: 'ms_sla_full', group: 'n', cron: '0 */6 * * *',
    script: 'services/ms_sla_service.py → run_full_sync',
    zh: {
      name: 'MS SLA 完整同步',
      desc: 'SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）',
      flow: ['每 6 小时按 nur_calc 实时口径重算 NUR/SLA/WO 指标', '写 data/ms_sla/ms_sla_dashboard.sqlite3', '供 MS SLA 看板与两份日报邮件使用'],
      maintain: ['看板数字以本任务的实时计算为准（与历史快照文件可能不一致）', '口径调整改 backend/services/nur_calc.py'],
    },
    en: {
      name: 'MS SLA Full Sync',
      desc: 'SLA metrics sync + Contract KPIs report update (self-contained, no external files)',
      flow: ['Every 6h recompute NUR/SLA/WO metrics via the live nur_calc logic', 'Write to data/ms_sla/ms_sla_dashboard.sqlite3', 'Feeds the MS SLA board and two daily report emails'],
      maintain: ['Board numbers follow this live calculation (snapshot files may differ)', 'Adjust criteria in backend/services/nur_calc.py'],
    },
  },
  {
    id: 'eflow_active_alarm', group: 'n', cron: '*/30 * * * *',
    script: 'services/eflow_api_client.py → fetch_and_save_active_alarm',
    zh: {
      name: 'eFlow 实时告警同步',
      desc: '从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite',
      flow: ['每 30 分钟拉 FM Active 活跃告警', '双写 app.db 的 realtime_alarm 与 eflow.sqlite3 副本（副本仅供报表）', '供实时告警看板 / 实时告警地图 / 告警管理看板使用'],
      maintain: ['页面只读 app.db；「实时」即 30 分钟粒度，并非秒级推送', '告警字段映射在 services/eflow_alarm_config.json'],
    },
    en: {
      name: 'eFlow Realtime Alarm Sync',
      desc: 'Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite',
      flow: ['Pull FM Active alarms every 30 min', 'Dual-write app.db realtime_alarm and an eflow.sqlite3 copy (report-only)', 'Feeds the realtime alarm board / realtime map / alarm management board'],
      maintain: ['Pages read app.db only; "realtime" means 30-minute granularity, not second-level push', 'Field mapping lives in services/eflow_alarm_config.json'],
    },
  },
  {
    id: 'eflow_history_alarm', group: 'n', cron: '0 */3 * * *',
    script: 'services/eflow_api_client.py → fetch_and_save_history_alarm',
    zh: {
      name: 'eFlow 历史告警同步',
      desc: '从 eFlow FM History 接口获取近 7 天历史告警，过滤 TT ID，保存 CSV + SQLite',
      flow: ['每 3 小时拉近 7 天 FM History 告警', '过滤出关联 TT 的记录后入库 history_alarm'],
      maintain: ['7 天窗口固定；更早的历史需查主库保留数据'],
    },
    en: {
      name: 'eFlow History Alarm Sync',
      desc: 'Fetch last-7-day history alarms from eFlow FM History API, filter by TT ID, save to CSV + SQLite',
      flow: ['Pull last 7 days of FM History alarms every 3h', 'Keep only TT-associated records into history_alarm'],
      maintain: ['The 7-day window is fixed; older history must be queried from retained DB data'],
    },
  },
  {
    id: 'eflow_tt_rules_check', group: 'n', cron: '20 4 * * *',
    script: 'services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check',
    zh: {
      name: 'eFlow TT 规则收集与匹配检查',
      desc: '每天 04:20 从 eFlow 拉取激活的 TT Update Severity Rule，对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正',
      flow: ['拉取最新规则生成 eflow_TT_rules.xlsx（正式规则表）', '对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正', '规则/矫正表/报告落盘，供任务报告文件页下载'],
      maintain: ['正式规则表是 backend/services/eflow_rules/eflow_TT_rules.xlsx——根目录同名文件只是副本，改它不生效', '「任务报告文件」页的 eFlow 规则页签可「立即执行」手动触发一次'],
    },
    en: {
      name: 'eFlow TT Rules Collect & Match Check',
      desc: 'Daily 04:20: collect active TT Update Severity Rules from eFlow, then match the latest 1000 eflow_tt records and produce severity corrections',
      flow: ['Fetch rules and regenerate eflow_TT_rules.xlsx (the authoritative rule sheet)', 'Match the latest 1000 eflow_tt records and correct severities', 'Rules/corrections/report saved for download on the Task Report Files page'],
      maintain: ['The authoritative rule sheet is backend/services/eflow_rules/eflow_TT_rules.xlsx — the root-level copy is a draft, editing it has no effect', 'The eFlow tab on the Task Report Files page supports "Run Now" to trigger manually'],
    },
  },
  {
    id: 'main_kpi_sync', group: 'u', cron: '0 4 * * *',
    script: 'services/ran_ume_main_kpi.py → run_main_kpi_sync',
    zh: {
      name: 'RAN Main KPI 同步',
      desc: 'RAN UME Main KPI 历史指标同步（2G/3G/4G × Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传',
      flow: ['登录 RAN UME 按 2G/3G/4G 模板查询 Main KPI 历史', '导出 Excel、增量更新 SQLite、FTP 上传远程主机'],
      maintain: ['查询模板与回溯天数在 services/main_kpi_config.json（days_back）', 'u 组串行，04:00 执行，前面任务（02:00 日报）卡住会顺延'],
    },
    en: {
      name: 'RAN Main KPI Sync',
      desc: 'RAN UME Main KPI history sync (2G/3G/4G × Cells/Sites/Group/NW), export Excel + incremental SQLite update + FTP upload',
      flow: ['Log into RAN UME, query Main KPI history per 2G/3G/4G templates', 'Export Excel, incrementally update SQLite, FTP upload'],
      maintain: ['Templates & days_back in services/main_kpi_config.json', 'Serial in group u at 04:00 — a stuck 02:00 daily task delays it'],
    },
  },
  {
    id: 'cell_availability_sync', group: 'u', cron: '30 4 * * *',
    script: 'services/ran_cell_availability_sync.py → run_cell_availability_sync',
    zh: {
      name: 'RAN 小区可用性 1-Day 同步',
      desc: 'RAN UME 小区可用性天粒度 KPI 同步（FDD/UMTS/GSM/TDD 4 模板），写 ran_kpi_avalability_1day.sqlite3 + FTP 上传',
      flow: ['按 FDD/UMTS/GSM/TDD 4 个模板查询小区可用性天粒度 KPI', '写 data/ran_kpi_avalability_1day.sqlite3', 'FTP 上传远程主机'],
      maintain: ['库名 ran_kpi_avalability_1day.sqlite3 的 avalability 是历史拼写，多处按字符串引用，不要改名'],
    },
    en: {
      name: 'RAN Cell Availability 1-Day Sync',
      desc: 'RAN UME cell availability daily KPI sync (FDD/UMTS/GSM/TDD templates), writes ran_kpi_avalability_1day.sqlite3 + FTP upload',
      flow: ['Query daily cell availability KPI via 4 templates (FDD/UMTS/GSM/TDD)', 'Write data/ran_kpi_avalability_1day.sqlite3', 'FTP upload to the remote host'],
      maintain: ['The misspelling "avalability" in the DB filename is historical and string-referenced — do NOT rename'],
    },
  },
  {
    id: 'cells_kpi_sync', group: 'u', cron: '50 4 * * *',
    script: 'services/ran_cells_kpi_sync.py → run_cells_kpi_sync',
    zh: {
      name: 'RAN Cells KPI 同步',
      desc: 'RAN UME 小区数据（2G/3G/4G）每日同步，聚合 Cells KPI（达标值 99.65%）物化写 ran_cells_kpi.sqlite3，只保留当月',
      flow: ['复用小区可用性同步的 UME 获取方法拉取 GSM/UMTS/FDD 小区数据', '按小区逐条折算可用率并统计达标/未达标/无数据', '物化写 data/ran_cells_kpi.sqlite3（表 cells_kpi_daily，只保留当月）'],
      maintain: ['口径与达标值定义在 services/ran_cells_kpi_service.py 顶部；2G 用信道折算，3G/4G 用服务时长/86400', '看板 RAN 小区 KPI 优先读物化库，缺失时回退实时聚合 ran_kpi_avalability_1day.sqlite3'],
    },
    en: {
      name: 'RAN Cells KPI Sync',
      desc: 'Daily RAN UME cell data sync (2G/3G/4G), aggregate Cells KPI (target 99.65%) into ran_cells_kpi.sqlite3, current month only',
      flow: ['Reuse the availability sync UME fetch to pull GSM/UMTS/FDD cell data', 'Derive per-cell availability and count meeting/below/blank', 'Materialize into data/ran_cells_kpi.sqlite3 (table cells_kpi_daily, current month only)'],
      maintain: ['Definitions live at the top of services/ran_cells_kpi_service.py; 2G uses channel ratio, 3G/4G use service time / 86400', 'The RAN Cells KPI dashboard reads the materialized DB first, falling back to live aggregation of ran_kpi_avalability_1day.sqlite3'],
    },
  },
  {
    id: 'network_kpi_sync', group: 'u', cron: '0 5 * * *',
    script: 'services/ran_ume_network_kpi.py → run_network_kpi_sync',
    zh: {
      name: 'RAN Network KPI 同步',
      desc: 'RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G × Group/NW），导出 Excel 并导入 SQLite + FTP 上传',
      flow: ['登录 RAN UME（Zeenshan）按 Group/NW 维度查 Network KPI 历史', '导出 Excel、导入 SQLite、FTP 上传'],
      maintain: ['查询模板在 services/network_kpi_config.json'],
    },
    en: {
      name: 'RAN Network KPI Sync',
      desc: 'RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G × Group/NW), export Excel + SQLite import + FTP upload',
      flow: ['Log into RAN UME (Zeenshan), query Network KPI history by Group/NW', 'Export Excel, import into SQLite, FTP upload'],
      maintain: ['Query templates in services/network_kpi_config.json'],
    },
  },
  {
    id: 'cnn_kpi_sync', group: 'n', cron: '0 6 * * *',
    script: 'services/ccn_ume_kpi_service.py → run_cnn_kpi_sync',
    zh: {
      name: 'CNN UME KPI 同步',
      desc: 'CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN',
      flow: ['登录 CNN UME 查核心网 KPI（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating）', '经 API 写入远程 DB CNN'],
      maintain: ['Free Rating 数据同时供 ccn_free_rating_chart_email 出图'],
    },
    en: {
      name: 'CNN UME KPI Sync',
      desc: 'CNN UME core-network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN',
      flow: ['Log into CNN UME, query core KPIs (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating)', 'Write to remote DB CNN via API'],
      maintain: ['Free Rating output also feeds the ccn_free_rating_chart_email charts'],
    },
  },
  {
    id: 'sp_data_sync', group: 'n', cron: '0 7 * * *',
    script: 'services/get_sp_table.py → run_sp_data_sync',
    zh: {
      name: 'SP 备件数据同步',
      desc: '从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db，并镜像写入 FineBI WareHouseDashBoard inventory.db',
      flow: ['登录备件 SFTP（凭据分组 sftp_sp）', '拉取 Inbound/Outbound/Inventory/OC Rule/Transfer 5 份报表', '清洗后写主库，供仓库看板与 SP 报表使用', '全部落库后镜像写入 FineBI inventory.db（UNC 路径；普通表整表替换、Inventory 只追加新行）', '最后按保留期清理 Inventory 历史快照（app.db 与镜像库同口径，默认 180 天）'],
      maintain: ['仓库看板 iframe 读的就是这批数据；报表缺失先看本任务是否成功', '镜像失败会在任务消息提示但影响不到 app.db；路径/开关在 Settings → 任务配置（mirror_db_path / mirror_enabled）', 'inventory_details 只追加不覆盖，靠保留期控制体积：Settings → 任务配置 inventory_retention_days（默认 180）。清理基准取表内最新 update_date，上游断流时不会清空整表', '仓库看板「Inventory Quantity Trend」直接读取本表全部日期（无日期参数时返回全量），调小保留天数会直接缩短趋势图历史'],
    },
    en: {
      name: 'SP Spare Data Sync',
      desc: 'Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db, then mirror into FineBI WareHouseDashBoard inventory.db',
      flow: ['Log into the spare-parts SFTP (credential group sftp_sp)', 'Fetch the 5 reports', 'Clean and write into the main DB for the warehouse board and SP reports', 'After all tables are stored, mirror into the FineBI inventory.db (UNC path; full replace for normal tables, append-only for Inventory)', 'Finally prune Inventory snapshots older than the retention window (same policy for app.db and the mirror, default 180 days)'],
      maintain: ['The warehouse board iframe reads exactly this data — if reports are missing, check this task first', 'Mirror failures are reported in the task message without affecting app.db; path/toggle in Settings → Task Config (mirror_db_path / mirror_enabled)', 'inventory_details is append-only and bounded by retention: Settings → Task Config, inventory_retention_days (default 180). The cutoff is based on the newest update_date in the table, so an upstream outage never wipes the table', 'The warehouse board\'s "Inventory Quantity Trend" reads every date in this table (no date filter = full history), so lowering the retention window directly shortens the trend chart'],
    },
  },
  {
    id: 'ipran_kpi_sync', group: 'u', cron: '0 8 * * *',
    script: 'services/ipran_ume_kpi_service.py → run_ipran_kpi_sync',
    zh: {
      name: 'iPRAN UME KPI 同步',
      desc: 'iPRAN UME M6000 路由器 KPI 同步（HQ M6K-FW 等），导出 Excel 并导入 SQLite + FTP 上传',
      flow: ['登录 iPRAN UME 查 M6000 路由器 KPI', '导出 Excel、写 data/ipran_ume/ipran_ume_kpi.sqlite3、FTP 上传'],
      maintain: ['产出同时供 ipran_m6k_chart_email（06:45）出图；u 组内排在 08:00'],
    },
    en: {
      name: 'iPRAN UME KPI Sync',
      desc: 'iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel + SQLite import + FTP upload',
      flow: ['Log into iPRAN UME, query M6000 router KPIs', 'Export Excel, write data/ipran_ume/ipran_ume_kpi.sqlite3, FTP upload'],
      maintain: ['Output also feeds ipran_m6k_chart_email (06:45); runs at 08:00 within group u'],
    },
  },
  {
    id: 'liberia_email_1h', group: 'm', cron: '5 * * * *',
    script: 'services/liberia_email_report.py → run_1h_report',
    zh: {
      name: 'Liberia 宕站 1小时报告邮件',
      desc: '发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单',
      flow: ['每小时 :05 汇总最近 1 小时宕站数据', '生成内嵌图 + Excel 报表', '发送到主送/抄送名单（收件人在系统设置维护）'],
      maintain: ['EWS 不可用时漏发由 email_recovery（每 20 分钟）自动补发'],
    },
    en: {
      name: 'Liberia Site-Down 1H Report Email',
      desc: 'Email the Liberia Orange Site Down hourly Report (inline charts + Excel) to recipient lists',
      flow: ['Hourly :05 aggregate the last hour of site-down data', 'Build the inline-chart + Excel report', 'Send to the to/cc lists (managed in Settings)'],
      maintain: ['When EWS is down, email_recovery (every 20 min) re-sends automatically once restored'],
    },
  },
  {
    id: 'liberia_email_8h', group: 'm', cron: '10 */8 * * *',
    script: 'services/liberia_email_report.py → run_8h_report',
    zh: {
      name: 'Liberia 宕站 8小时报告邮件',
      desc: '发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单',
      flow: ['每 8 小时（00/08/16 时 :10）汇总窗口内宕站数据', '生成内嵌图 + Excel 报表并发送'],
      maintain: ['与 1 小时版同一脚本不同入口；收件人名单改动后两种报表同时生效'],
    },
    en: {
      name: 'Liberia Site-Down 8H Report Email',
      desc: 'Email the Liberia Orange Site Down 8-hour Report (inline charts + Excel) to recipient lists',
      flow: ['Every 8 hours (:10 of 00/08/16) aggregate site-down data', 'Build and send the inline-chart + Excel report'],
      maintain: ['Same script as the 1H version, different entry; recipient changes apply to both'],
    },
  },
  {
    id: 'kpi_ms_contract', group: 'm', cron: '30 17 * * *',
    script: 'services/kpi_email_report.py → run_ms_contract_kpi',
    zh: {
      name: 'MS Contract KPIs 日报邮件',
      desc: '发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）',
      flow: ['读取 ms_sla_full（每 6 小时）产出的本地 ms_sla 数据', '生成 Contract KPIs 日报', '发送到远程名单中的收件人'],
      maintain: ['数据来自 ms_sla_full；17:30 发送时用的是 16:00 那一轮同步的数'],
    },
    en: {
      name: 'MS Contract KPIs Daily Report Email',
      desc: 'Email the MS Contract KPIs Achievements Daily Report (local data + remote recipient list)',
      flow: ['Read local ms_sla data produced by ms_sla_full (every 6h)', 'Build the Contract KPIs daily report', 'Send to recipients from the remote list'],
      maintain: ['Data comes from ms_sla_full; the 17:30 send uses the 16:00 sync round'],
    },
  },
  {
    id: 'kpi_ms_wo_sla', group: 'm', cron: '35 17 * * *',
    script: 'services/kpi_email_report.py → run_ms_wo_sla',
    zh: {
      name: 'MS WOs SLA 日报邮件',
      desc: '发送 MS WOs SLA Achievements Daily Report（本地数据 + 远程名单）',
      flow: ['读取本地 ms_sla 数据', '生成 WOs SLA 日报并发送到远程名单'],
      maintain: ['与 kpi_ms_contract 同一脚本不同入口，只差 5 分钟错峰'],
    },
    en: {
      name: 'MS WOs SLA Daily Report Email',
      desc: 'Email the MS WOs SLA Achievements Daily Report (local data + remote recipient list)',
      flow: ['Read local ms_sla data', 'Build and send the WOs SLA daily report to the remote list'],
      maintain: ['Same script as kpi_ms_contract with a different entry; 5 minutes apart to avoid overlap'],
    },
  },
  {
    id: 'kpi_sp_spareparts', group: 'm', cron: '45 9 * * *',
    script: 'services/kpi_email_report.py → run_sp_spareparts',
    zh: {
      name: 'SpareParts 备件报表邮件',
      desc: '发送 SpareParts 报表（本地 sp_email 数据 + 远程共享名单）',
      flow: ['读取 sp_report_generate（05:15）生成到 data/sp_email 的报表', '发送 SpareParts 报表到远程共享名单'],
      maintain: ['报表文件缺失说明 05:15 的生成任务失败，先修上游再重发本任务'],
    },
    en: {
      name: 'SpareParts Report Email',
      desc: 'Email the SpareParts report (local sp_email data + remote shared recipient list)',
      flow: ['Read reports generated into data/sp_email by sp_report_generate (05:15)', 'Send the SpareParts report to the remote shared list'],
      maintain: ['Missing report files mean the 05:15 generation failed — fix upstream first, then re-run this task'],
    },
  },
  {
    id: 'kpi_sp_consumables', group: 'm', cron: '50 9 * * *',
    script: 'services/kpi_email_report.py → run_sp_consumables',
    zh: {
      name: 'Comsumables 耗材报表邮件',
      desc: '发送 Comsumables 报表（本地 sp_email 数据 + 远程共享名单）',
      flow: ['读取 data/sp_email 下 sp_report_generate 产出的耗材报表', '发送到远程共享名单'],
      maintain: ['任务名 Comsumables 是历史拼写（实为 Consumables），注册表按此引用，勿改'],
    },
    en: {
      name: 'Comsumables Report Email',
      desc: 'Email the Comsumables (consumables) report (local sp_email data + remote shared list)',
      flow: ['Read the consumables report generated under data/sp_email', 'Send to the remote shared list'],
      maintain: ['The task name "Comsumables" is a historical misspelling referenced by the registry — do not rename'],
    },
  },
  {
    id: 'sp_report_generate', group: 'm', cron: '15 5 * * *',
    script: 'services/kpi_email_report.py → run_sp_report_generate',
    zh: {
      name: 'SP 备件报表生成',
      desc: '从 SFTP 下载备件数据，生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表到本地 data/sp_email',
      flow: ['登录 SFTP 下载备件原始数据', '生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表', '落盘 data/sp_email 供 09:45/09:50 两个邮件任务与 07:00 明细邮件使用'],
      maintain: ['是 3 个 SP 邮件任务的上游，失败会导致当天备件邮件整体缺报'],
    },
    en: {
      name: 'SP Report Generate',
      desc: 'Download spare-part data from SFTP and generate Comsumables & SpareParts Inbound&Outbound&Inventory reports into data/sp_email',
      flow: ['Log into SFTP and download raw spare data', 'Generate the Comsumables & SpareParts Inbound&Outbound&Inventory reports', 'Save to data/sp_email for the 09:45/09:50 email tasks and the 07:00 details email'],
      maintain: ['Upstream of 3 SP email tasks — its failure blanks all spare-part emails for the day'],
    },
  },
  {
    id: 'sp_email_details', group: 'm', cron: '0 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_details_email',
    zh: {
      name: 'SP 备件明细报表邮件',
      desc: '每天 07:00 发送 data/sp_email/data 下 5 份备件明细 Excel（inband/outband/inventory/ocrule/transfer）',
      flow: ['收集 data/sp_email/data 下 5 份 *_details.xlsx', '整包发送（默认收件人为固定地址，可在系统设置 → 邮件收件人覆盖）'],
      maintain: ['2026-09-01 上线时曾漏分组导致 pending 卡死，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP'],
    },
    en: {
      name: 'SP Spare Parts Details Report Email',
      desc: 'Daily 07:00: email the 5 spare-part detail Excel files (inband/outband/inventory/ocrule/transfer) under data/sp_email/data',
      flow: ['Collect the 5 *_details.xlsx files under data/sp_email/data', 'Send them in one email (default fixed recipients, overridable in Settings → Email Recipients)'],
      maintain: ['Missed its worker-group registration on 2026-09-01 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP'],
    },
  },
  {
    id: 'sp_whatsapp_report', group: 'm', cron: '15 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_whatsapp_report',
    zh: {
      name: 'Comsumables&SpareParts Report Whatsapp',
      desc: '每天 07:15 把 Comsumables / SpareParts 两个邮件任务的同一批产物（合并总表 XLSX + 报表 PNG）发送到 WhatsApp 群 WH&SP Management',
      flow: ['在 data/sp_email 下选取 Comsumables / SpareParts 的合并总表 XLSX（不含 " - Liberia" 分站点）', '收集两类报表的 PNG（主图在前、Summary-Changed 在后）', '复用 whatsapp_service 的 Playwright 发送机制发到群 WH&SP Management'],
      maintain: ['上游是 sp_report_generate（m 组 05:15），它失败会导致本任务找不到报表文件', '不发送邮件——邮件由 kpi_sp_consumables / kpi_sp_spareparts 负责'],
    },
    en: {
      name: 'Comsumables&SpareParts Report Whatsapp',
      desc: 'Daily 07:15: send the same assets used by the Comsumables / SpareParts report emails (consolidated XLSX + report PNGs) to the WhatsApp group WH&SP Management',
      flow: ['Pick the consolidated Comsumables / SpareParts XLSX under data/sp_email (excludes the " - Liberia" per-site files)', 'Collect the PNGs of both reports (main chart first, Summary-Changed last)', 'Send via the Playwright mechanism in whatsapp_service to the group WH&SP Management'],
      maintain: ['Upstream is sp_report_generate (group m, 05:15) — if it fails this task finds no report files', 'No email is sent here; emails are handled by kpi_sp_consumables / kpi_sp_spareparts'],
    },
  },
  {
    id: 'sp_material_report', group: 'm', cron: '33 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_material_stock_consumption',
    zh: {
      name: 'SP 物料库存与消耗报表邮件',
      desc: '每天 07:33 把 SP 物料库存与消耗汇总（同「SP 物料库存与消耗统计」页面 page=sp_material 的口径）导出为 UNIFIED_EXCEL_V1 版式 Excel 附件 + 同内容 PNG 内嵌正文并邮件发送',
      flow: ['调用 sp_material_summary_service.get_material_summary()（inventory_details 每日快照 + outband_details 报修出库）', '生成 UNIFIED_EXCEL_V1 版式 Excel（标题 / 副标题 / 两行合并表头 / 合计行在前 / 13 列 + Info 页），与页面「导出 Excel」逐格一致', '用 Pillow 把同一张汇总表画成 PNG（手法同 SP 报表图片：蓝表头 + 橙色区块条 + 斑马纹）', '落盘 data/sp_material_report（只保留最新一份）：Excel 作附件、PNG 内嵌正文发送'],
      maintain: ['默认 15 主送 + 2 抄送，可在系统设置 → 邮件收件人 覆盖', '汇总表无数据行时跳过发送并记为失败（多为上游 SP 数据同步未跑）', 'PNG 生成失败只告警不阻断，邮件仍带 Excel 发出'],
    },
    en: {
      name: 'SP Material Stock & Consumption Report Email',
      desc: 'Daily 07:33: export the SP material stock & consumption summary (same scope as the page=sp_material page) to a UNIFIED_EXCEL_V1 Excel attachment plus an inline PNG of the same table, and email it',
      flow: ['Call sp_material_summary_service.get_material_summary() (inventory_details daily snapshots + outband_details repair outbound)', 'Build a UNIFIED_EXCEL_V1 workbook (title / subtitle / two-row merged header / total row above the data / 13 columns + Info sheet), cell-for-cell identical to the page "Export Excel"', 'Draw the same summary table as a PNG with Pillow (same method as the SP report images: blue header + orange section bands + zebra rows)', 'Save to data/sp_material_report (keeps only the latest): the Excel as attachment, the PNG inlined in the body'],
      maintain: ['Default 15 To + 2 Cc, overridable in Settings → Email Recipients', 'Skips sending and reports failure when the summary has no data rows (usually the upstream SP data sync did not run)', 'If PNG rendering fails it only warns and does not block the email — the Excel is still sent'],
    },
  },
  {
    id: 'kpi_ran_availability', group: 'm', cron: '30 9 * * *',
    script: 'services/kpi_email_report.py → run_ran_availability',
    zh: {
      name: 'MS Network Availability 日报邮件',
      desc: '发送 MS Network Availability Daily Report（远程 FTP 图片 + 远程名单，无 Excel）',
      flow: ['从远程 FTP 拉取已生成的可用性图片（由 ran_ume_daily 02:00 产出并上传）', '组装日报（无 Excel 附件）发送到远程名单'],
      maintain: ['图片缺失通常是 ran_ume_daily（u 组 02:00）失败——查它而不是本任务'],
    },
    en: {
      name: 'MS Network Availability Daily Report Email',
      desc: 'Email the MS Network Availability Daily Report (remote FTP images + remote list, no Excel attachment)',
      flow: ['Fetch availability images from remote FTP (produced & uploaded by ran_ume_daily at 02:00)', 'Assemble the report (no Excel) and send to the remote list'],
      maintain: ['Missing images usually mean ran_ume_daily (group u, 02:00) failed — investigate that task instead'],
    },
  },
  {
    id: 'email_recovery', group: 'm', cron: '*/20 * * * *',
    script: 'services/email_recovery.py → run_email_recovery_task',
    zh: {
      name: 'EWS 恢复后邮件补发',
      desc: '每 20 分钟探测 EWS 是否恢复；恢复后自动补发近 3 小时内因 EWS 超时失败的邮件任务',
      flow: ['探测 Exchange（EWS）连通性', '扫描近 3 小时内因 EWS 超时失败的邮件任务', '恢复后逐个补发'],
      maintain: ['邮件没收到先查它的执行历史，而不是手动重跑原邮件任务'],
    },
    en: {
      name: 'Email Recovery after EWS Restored',
      desc: 'Probes EWS every 20 minutes; once restored, re-sends email tasks that failed due to EWS timeouts in the last 3 hours',
      flow: ['Probe Exchange (EWS) reachability', 'Scan email tasks failed by EWS timeout within the last 3h', 'Re-send them one by once EWS is back'],
      maintain: ['For missing emails check this task\'s history first instead of manually re-running the original email task'],
    },
  },
  {
    id: 'packet_loss_sync', group: 'u', cron: '30 6 * * *',
    script: 'services/packet_loss_service.py → run_packet_loss_sync',
    zh: {
      name: 'Packet Loss 丢包同步',
      desc: 'RAN UME 丢包率（SDR/IPRAN IPPD）同步，入库 lte_pl.sqlite3 并生成丢包报告；只展示最近 7 个完整自然日',
      flow: ['登录 RAN UME 拉丢包率（SDR/IPRAN IPPD）', '计算 STATUS（0~23 小时标志块）与 FINAL_STATUS 五级分类', '写 data/packet_lost/lte_pl.sqlite3（注意目录名是 packet_lost）并生成报告'],
      maintain: ['看板与报告口径与 Packet_Loss 自动化 Excel 完全一致；当天没过完不展示', '目录名 packet_lost 是历史拼写，不要改名'],
    },
    en: {
      name: 'Packet Loss Sync',
      desc: 'Sync packet loss rate (SDR/IPRAN IPPD) from RAN UME into lte_pl.sqlite3 and generate the report; only the last 7 complete days are shown',
      flow: ['Log into RAN UME and pull packet loss (SDR/IPRAN IPPD)', 'Compute STATUS (0-23 hourly flag blocks) and FINAL_STATUS five-level classification', 'Write data/packet_lost/lte_pl.sqlite3 (note the folder name) and generate the report'],
      maintain: ['Criteria match the Packet_Loss automation Excel exactly; the unfinished current day is hidden', 'The folder name packet_lost is historical — do not rename'],
    },
  },
  {
    id: 'packet_loss_email', group: 'u', cron: '45 6 * * *',
    script: 'services/kpi_email_report.py → run_packet_loss_email',
    zh: {
      name: 'Packet Loss 丢包日报邮件',
      desc: '发送 Packet Loss 丢包看板日报邮件（本地截图 + 最新报告 xlsx + 远程收件人清单），经 OWA 账户发送',
      flow: ['截取丢包看板画面 + 取 06:30 同步生成的最新报告 xlsx', '经 OWA 账户发送到远程收件人清单'],
      maintain: ['排在 06:45，紧跟 06:30 同步任务（同在 u 组串行，顺序有保证）'],
    },
    en: {
      name: 'Packet Loss Daily Report Email',
      desc: 'Send the Packet Loss dashboard daily email (local screenshot + latest report xlsx + remote recipients) via the OWA account',
      flow: ['Screenshot the packet-loss board + pick the latest report from the 06:30 sync', 'Send via OWA to the remote recipient list'],
      maintain: ['Runs 06:45 right after the 06:30 sync (same group u, serialized — order guaranteed)'],
    },
  },
  {
    id: 'ipran_m6k_chart_email', group: 'm', cron: '45 6 * * *',
    script: 'services/ipran_chart_service.py → run_ipran_m6k_chart_email',
    zh: {
      name: 'IP RAN M6K-FW 图表邮件',
      desc: '从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成 3 张利用率折线图并发送',
      flow: ['查询 ipran_ume_kpi.sqlite3 的 HQ_M6K_FW_bnctp_15mins 表', '按 ME+SmartGroup 生成 3 张利用率折线图', '发送图表邮件'],
      maintain: ['依赖前一天 08:00 ipran_kpi_sync 的数据；u 组任务失败时本邮件会出空图或失败'],
    },
    en: {
      name: 'IP RAN M6K-FW Chart Email',
      desc: 'Query HQ_M6K_FW_bnctp_15mins from ipran_ume_kpi.sqlite3, generate 3 utilization line charts by ME+SmartGroup and email them',
      flow: ['Query HQ_M6K_FW_bnctp_15mins in ipran_ume_kpi.sqlite3', 'Generate 3 utilization line charts by ME+SmartGroup', 'Send the chart email'],
      maintain: ['Depends on the previous day\'s 08:00 ipran_kpi_sync; empty charts or failure follow u-group sync failures'],
    },
  },
  {
    id: 'ccn_free_rating_chart_email', group: 'm', cron: '45 7 * * *',
    script: 'services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email',
    zh: {
      name: 'CNN Free Rating 图表邮件',
      desc: '从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成 4 张柱状图并发送',
      flow: ['查询 db_ps_cs_cn.sqlite3 的 FREE_RATING 模板表', '按 MO 生成 4 张柱状图并发送'],
      maintain: ['数据来自 cnn_kpi_sync（n 组，每天 06:00）写入的 DB CNN'],
    },
    en: {
      name: 'CNN Free Rating Chart Email',
      desc: 'Query FREE_RATING_GROUP_TEMPLATE_OSS_update_UME from db_ps_cs_cn.sqlite3, generate 4 bar charts by MO and email them',
      flow: ['Query the FREE_RATING template table in db_ps_cs_cn.sqlite3', 'Generate 4 bar charts by MO and send'],
      maintain: ['Data comes from cnn_kpi_sync (group n, daily 06:00) writing into DB CNN'],
    },
  },
  {
    id: 'fw_kpi_sync', group: 'n', cron: '15 7 * * *',
    script: 'services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync',
    zh: {
      name: 'FW 吞吐 KPI 同步+图表邮件',
      desc: '从 DPtech UMC 拉取整机吞吐数据，经 API 写入远程 fw_db.sqlite，生成近 14 天吞吐折线图并邮件发送',
      flow: ['登录 DPtech UMC（凭据分组 fw_kpi）拉整机吞吐', '经 API 写入远程 fw_db.sqlite', '生成近 14 天吞吐折线图并发送'],
      maintain: ['同步与出图发信在同一个任务里完成，失败时整链路（入库+邮件）都停'],
    },
    en: {
      name: 'FW Throughput KPI Sync + Chart Email',
      desc: 'Fetch whole-device throughput from DPtech UMC, write to remote fw_db.sqlite via API, generate a 14-day chart and email it',
      flow: ['Log into DPtech UMC (credential group fw_kpi), pull throughput', 'Write to remote fw_db.sqlite via API', 'Generate the 14-day throughput chart and send it'],
      maintain: ['Sync, chart and email happen in one task — a failure stops the whole chain (DB write + email)'],
    },
  },
  {
    id: 'battery_kpi_sync', group: 'u', cron: '5 * * * *',
    script: 'services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync',
    zh: {
      name: '电池 KPI 同步',
      desc: '从 UME 拉取电池实时 KPI（健康度/SOC/充放电状态），全程内存不落盘，写入 battery_kpi.sqlite3 供电池看板使用',
      flow: ['每小时 :05 登录 UME 拉电池实时 KPI', '全程内存处理（中间不落盘）', '写 data/battery/battery_kpi.sqlite3'],
      maintain: ['电池看板默认只统计 24h 内新鲜读数（BATT_FRESH_HOURS 等环境变量控制阈值）', '注意模块目录名是 battary_kpi_fetch（历史拼写），勿改'],
    },
    en: {
      name: 'Battery KPI Sync',
      desc: 'Fetch battery realtime KPI (health/SOC/charge status) from UME, in-memory only, write to battery_kpi.sqlite3 for the battery board',
      flow: ['Hourly :05 log into UME and pull battery KPI', 'Process fully in memory (no intermediate files)', 'Write data/battery/battery_kpi.sqlite3'],
      maintain: ['The battery board counts only readings ≤24h fresh by default (thresholds via BATT_FRESH_HOURS etc.)', 'The module folder battary_kpi_fetch is a historical misspelling — do not rename'],
    },
  },
  {
    id: 'battery_email', group: 'm', cron: '0 7,19 * * *',
    script: 'services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email',
    zh: {
      name: '电池 KPI 邮件',
      desc: '将电池 KPI 报表（Excel）发送至远程名单中的邮箱，每日 07:00 与 19:00 各一次',
      flow: ['从 battery_kpi.sqlite3 生成 Excel 报表', '发送到远程名单中的邮箱（每天两次）'],
      maintain: ['与同步任务同脚本不同入口；收件人来自远程 FTP 名单'],
    },
    en: {
      name: 'Battery KPI Email',
      desc: 'Email the battery KPI report (Excel) to recipients from the remote list, daily at 07:00 & 19:00',
      flow: ['Generate the Excel report from battery_kpi.sqlite3', 'Send to the remote recipient list (twice daily)'],
      maintain: ['Same script as the sync task, different entry; recipients come from the remote FTP list'],
    },
  },
  {
    id: 'mailbox_cleanup', group: 'm', cron: '0 * * * *',
    script: 'services/mailbox_cleanup.py → run_mailbox_cleanup',
    zh: {
      name: '邮箱空间清理',
      desc: '每小时检查 Exchange 邮箱：邮件数 >500 且空间 >70% 时，硬删除最旧 200 封邮件，避免 storage limit 告警',
      flow: ['每小时 :00 检查 Exchange 邮箱（exchangelib/EWS）', '邮件数 >500 且空间 >70% 时硬删除最旧 200 封'],
      maintain: ['删除的是发件箱历史（含已发报表邮件），是防止报表发不出去的守卫任务，不要停用'],
    },
    en: {
      name: 'Mailbox Storage Guard',
      desc: 'Hourly Exchange mailbox guard: when count >500 AND usage >70%, hard-delete the 200 oldest emails to avoid the storage-limit warning',
      flow: ['Hourly :00 inspect the Exchange mailbox (exchangelib/EWS)', 'Hard-delete the 200 oldest emails when count >500 and usage >70%'],
      maintain: ['It deletes sent-mail history (including old report emails) — it is the guard keeping report delivery alive, do not disable'],
    },
  },
  {
    id: 'incident_overview_sync', group: 'm', cron: '0 * * * *',
    script: 'services/incident_overview_sync.py → run_incident_overview_sync',
    zh: {
      name: 'Incident Overview 数据同步',
      desc: '每小时整点从 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，版本化落盘 + current.json 指针',
      flow: ['每小时整点扫描 FineBI FTP 的 TT_WO/ 全部子目录', '取最新 incident_overview.xlsx 落盘为版本化文件 + current.json 指针', 'best-effort 刷新 incident_overview.xlsx 快照，供事件总览页使用'],
      maintain: ['版本化设计使上游 Excel 被打开占用时也不会取数失败——这是历史踩坑后的修复，勿改回直接覆盖'],
    },
    en: {
      name: 'Incident Overview Data Sync',
      desc: 'Hourly on-the-hour: pull the latest incident_overview.xlsx from all subfolders of FineBI FTP /webroot/WEB-INF/schedule/TT_WO/, stored as versioned files + a current.json pointer',
      flow: ['Scan all TT_WO/ subfolders on FineBI FTP hourly', 'Save the latest incident_overview.xlsx as a versioned file + current.json pointer', 'Best-effort refresh of the incident_overview.xlsx snapshot for the incident overview page'],
      maintain: ['The versioned design survives the upstream Excel being locked open — a hard-won fix, do not revert to direct overwrite'],
    },
  },
  {
    id: 'finebi_report_sync', group: 'm', cron: '10 * * * *',
    script: 'services/finebi_report_sync.py → run_finebi_report_sync',
    zh: {
      name: 'FineBI 报表文件同步',
      desc: '每小时从 FineBI FTP /webroot/WEB-INF/schedule 的每个子文件夹取最新一份 Excel，下载到本地 data/finebi_reports 供任务报告文件页下载',
      flow: ['每小时 :10 遍历 schedule 下每个子文件夹', '各取最新一份 Excel 下载到 data/finebi_reports', '「任务报告文件 → FINEBI report」页签展示与下载'],
      maintain: ['2026-08-25 分组模式启用时曾因未归组而 pending 卡死断档，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP'],
    },
    en: {
      name: 'FineBI Report Files Sync',
      desc: 'Hourly: pull the latest Excel from each subfolder of FineBI FTP /webroot/WEB-INF/schedule into data/finebi_reports for the Task Report Files page',
      flow: ['Hourly :10 walk every subfolder under schedule', 'Download the latest Excel per folder into data/finebi_reports', 'Listed & downloadable under Task Report Files → FINEBI report tab'],
      maintain: ['Stuck pending and broke the chain when group mode enabled on 2026-08-25 (ungrouped); now in group m — always register new tasks in GROUP_TASK_MAP'],
    },
  },
  {
    id: 'db_freshness_check', group: 'm', cron: '15 * * * *',
    script: 'services/db_freshness_check.py → run_db_freshness_check',
    zh: {
      name: '数据库数据新鲜度巡检',
      desc: '每小时巡检远程 DB（db_writer_api）与本地回退库各表最新数据日期，滞后时输出调用链路与检查方向',
      flow: ['每小时 :15 巡检远程库与本地回退库各表的最新数据日期', '滞后时在执行日志输出调用链与排查方向'],
      maintain: ['怀疑「某类数据停更」时先看它的执行历史，按给出的调用链排查，比翻任务列表快'],
    },
    en: {
      name: 'DB Data Freshness Check',
      desc: 'Hourly freshness audit of remote DBs (via db_writer_api) and local fallback DBs; outputs call chain and guidance when stale',
      flow: ['Hourly :15 check the latest data date per table in remote & local fallback DBs', 'When stale, log the call chain and troubleshooting direction in the execution history'],
      maintain: ['Suspect stalled data? Check this task\'s history first and follow its call chain — faster than browsing the task list'],
    },
  },
  {
    id: 'auto_retry_failed', group: 'm', cron: '*/10 * * * *',
    script: 'services/auto_retry.py → run_auto_retry_task',
    zh: {
      name: '失败任务自动重试',
      desc: '每 10 分钟扫描：失败任务若数据缺口尚未被后续成功执行补上则自动重投（MAX_ATTEMPTS=2，超 24h 放弃）；漏跑任务在时效窗口内无任何执行记录时补投一次',
      flow: ['每 10 分钟扫描最近 24 小时执行记录', '失败任务：先判断数据缺口是否已被后续成功执行补上，未补上且未超次数上限才重投', '漏跑任务：时效窗口内应触发却无任何执行记录时补投（15 分钟宽限）；邮件任务默认排除（归 EWS 补发）'],
      maintain: ['重试不是「失败就重跑」——缺口已被补上就不重投；环境变量 AUTO_RETRY_* 可调'],
    },
    en: {
      name: 'Failed Task Auto Retry',
      desc: 'Scans every 10 min: re-enqueues failed tasks whose data gap is not yet filled (MAX_ATTEMPTS=2, give up after 24h); backfills missed tasks with no execution record at all',
      flow: ['Scan the last 24h of execution records every 10 min', 'Failed tasks: re-enqueue only if the data gap is unfilled and under the attempt budget', 'Missed tasks: backfill once when nothing ran in the time window (15-min grace); email tasks excluded (handled by EWS recovery)'],
      maintain: ['Retry is not "rerun on any failure" — filled gaps are skipped; tune via AUTO_RETRY_* env vars'],
    },
  },
  {
    id: 'cm_data_sync', group: 'u', cron: '30 8 * * *',
    script: 'services/cm_data/cm_data_export.py → run_cm_data_sync',
    zh: {
      name: 'RAN CM 小区数据同步',
      desc: '从 RAN UME 获取 GSM/UMTS/LTE/NR 小区配置数据，经 API 全量替换写入远程 db.sqlite3（cm_cell_data/cm_site_summary），本地仅保留一份最新 Excel',
      flow: ['登录 RAN UME 按 services/cm_data/cm_flows.json 定义的流程导出小区配置', '经远程主机 API 全量替换 db.sqlite3 的 cm_cell_data / cm_site_summary', '本地仅保留一份最新 Excel'],
      maintain: ['导出流程（flows/payload/moc）在 services/cm_data/cm_flows.json 维护；网管界面改版后优先检查这里'],
    },
    en: {
      name: 'RAN CM Cell Data Sync',
      desc: 'Fetch GSM/UMTS/LTE/NR cell config from RAN UME, full-replace write to remote db.sqlite3 (cm_cell_data/cm_site_summary) via API, keep only the latest local Excel',
      flow: ['Log into RAN UME and export cell config per flows defined in services/cm_data/cm_flows.json', 'Full-replace cm_cell_data / cm_site_summary in remote db.sqlite3 via the host API', 'Keep only the latest Excel locally'],
      maintain: ['Export flows (flows/payload/moc) live in services/cm_data/cm_flows.json — check there first when the NMS UI changes'],
    },
  },
  {
    id: 'pg_to_sqlite_sync', group: 'm', cron: '45 * * * *',
    script: 'backend/scripts/sync_pg_to_sqlite.py → main',
    zh: {
      name: 'PG→SQLite 数据快照',
      desc: '把远程 PostgreSQL 全库数据同步到本地 db/app.db 作为离线备份/回退快照',
      flow: ['每小时 :45 全量同步远程 PG 到本地 db/app.db', 'app.db 兼作凭据表（credentials，明文）宿主'],
      maintain: ['app.db 里的业务表是「上一小时的镜像」，别在它上面做实时假设；也不要把它当垃圾删除（含凭据 + 快照，≈954MB）'],
    },
    en: {
      name: 'PG→SQLite Data Snapshot',
      desc: 'Sync all remote PostgreSQL data into local db/app.db as an offline backup / fallback snapshot',
      flow: ['Hourly :45 full-sync remote PG into local db/app.db', 'app.db also hosts the plaintext credentials table'],
      maintain: ['Business tables in app.db are a one-hour-stale mirror — never assume realtime; do not delete the file (credentials + snapshot, ≈954MB)'],
    },
  },
  {
    id: 'mw_ume_kpi_sync', group: 'n', cron: '15 5 * * *',
    script: 'services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync',
    zh: {
      name: 'MW UME KPI 同步',
      desc: 'MW UME（ZXMW 微波）KPI 历史指标同步（FINBI 模板 1 天粒度），内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation',
      flow: ['每天 05:15 经 FINBI 模板导出 1 天粒度 KPI（内存处理，不落临时文件）', '按 Begin Time + 元素标识列联合去重后写主库 mw_ume_bw_ultilazation'],
      maintain: ['微波拓扑看板一天只变一次（05:15 后）；表名 ultilazation 是历史拼写，勿改'],
    },
    en: {
      name: 'MW UME KPI Sync',
      desc: 'MW UME (ZXMW microwave) KPI history sync (FINBI 1-day template), in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation',
      flow: ['Daily 05:15 export 1-day KPI via the FINBI template (in-memory, no temp files)', 'Dedup by Begin Time + identity columns, write mw_ume_bw_ultilazation'],
      maintain: ['The microwave topology board changes once a day (after 05:15); the misspelling ultilazation in the table name is historical — do not rename'],
    },
  },
  {
    id: 'mw_ume_kpi_sync_rt', group: 'n', cron: '*/15 * * * *',
    script: 'services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt',
    zh: {
      name: 'MW UME KPI 实时同步',
      desc: 'MW UME KPI 实时同步（FINBI 模板 15 分钟粒度），每 15 分钟取最近 2 小时数据，直写 app.db 表 mw_ume_bw_ultilazation_rt',
      flow: ['每 15 分钟经 FINBI 模板（gr=900）取最近 2 小时数据', '内存导出直写 mw_ume_bw_ultilazation_rt（覆盖窗口内槽位）', '微波实时看板默认只取最新一个 15 分钟槽位，滑杆可回看'],
      maintain: ['与日粒度任务共用网管会话，同在 n 组串行；看板默认 900 秒自动刷新且支持软刷新'],
    },
    en: {
      name: 'MW UME KPI Realtime Sync',
      desc: 'MW UME realtime KPI sync (FINBI 15-min template): every 15 min fetch the last 2 hours, direct write to app.db table mw_ume_bw_ultilazation_rt',
      flow: ['Every 15 min fetch the last 2 hours via FINBI (gr=900)', 'In-memory export, write mw_ume_bw_ultilazation_rt (overwrites slots in window)', 'The realtime board uses only the latest 15-min slot; the slider reviews history'],
      maintain: ['Shares the NMS session with the daily task — serialized in group n; the board auto-refreshes every 900s with soft refresh'],
    },
  },
  {
    id: 'ems_kpi_cache_sync', group: 'c', cron: '*/15 * * * *',
    script: 'services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync',
    zh: {
      name: 'CN EMS KPI 缓存同步',
      desc: '每 15 分钟增量下载 CN EMS 当日（UTC）原始 PM 测量文件到本地 _pmcache（服务器仅保留约 1 天；只下载缺失文件不解析）',
      flow: ['每 15 分钟经 SFTP 增量下载当日 UTC 原始 PM 文件', '只下载缺失文件，不做解析（轻量）', '落到本地 _pmcache 缓存'],
      maintain: ['CN EMS 服务器只保留约 1 天原始文件——本任务是把整天数据在服务端清理前抢回来的关键，不要停用'],
    },
    en: {
      name: 'CN EMS KPI Cache Sync',
      desc: 'Every 15 min, incremental download of today\'s (UTC) raw PM measurement files from CN EMS SFTP into local _pmcache (server retains ~1 day; fetch-only, no parsing)',
      flow: ['Incrementally download today\'s UTC raw PM files via SFTP every 15 min', 'Fetch-only, no parsing (lightweight)', 'Store into the local _pmcache'],
      maintain: ['The CN EMS server keeps raw files ~1 day — this task is what rescues the full day before server cleanup; do not disable'],
    },
  },
  {
    id: 'ems_kpi_daily', group: 'c', cron: '20 0 * * *',
    script: 'services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily',
    zh: {
      name: 'CN EMS KPI 日粒度CSV',
      desc: '聚合前一个完整 UTC 日的 CN EMS KPI 并生成 csv_out/<模板名>.csv（VLR/USSD/语音/位置更新/License/TDD/Data 订阅者 7 模板）',
      flow: ['每天 00:20 UTC（北京 08:20）先 best-effort 补抓前一日窗口', '纯本地 _pmcache 缓存聚合（不再依赖服务端）', '按 Query_Template.xml + samples 公式输出 csv_out/<模板名>.csv，共 7 个模板'],
      maintain: ['与缓存同步共享 _pmcache/daily_raw.json，同在 c 组串行保证互斥'],
    },
    en: {
      name: 'CN EMS KPI Daily CSV',
      desc: 'Aggregate the previous complete UTC day of CN EMS KPIs into csv_out/<TEMPLATE>.csv per Query_Template.xml (7 templates: VLR/USSD/voice/location update/License/TDD/data subscribers)',
      flow: ['Daily 00:20 UTC (08:20 Beijing): best-effort refetch of the previous-day window', 'Aggregate purely from the local _pmcache (server-independent)', 'Emit csv_out/<TEMPLATE>.csv per Query_Template.xml + samples formulas (7 templates)'],
      maintain: ['Shares _pmcache/daily_raw.json with the cache sync — serialized in group c for mutual exclusion'],
    },
  },
]
