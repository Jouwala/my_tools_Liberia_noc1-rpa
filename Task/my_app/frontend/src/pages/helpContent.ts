/* ==================== 帮助页共享文案数据 ====================
 * Help.tsx（站内渲染）与 helpMarkdown.ts（Markdown 导出）共用，
 * 改这里两处同步生效。依据 docs/manual/ 与 backend/task_registry.py 整理。
 * ================================================ */

export type Locale = 'zh' | 'en'

/* ---------- 页面清单（与 App.tsx menuItems 顺序一致，help 自身除外） ---------- */
export const PAGE_LIST: { key: string; iframe?: boolean }[] = [
  { key: 'sync' },
  { key: 'email_reports' },
  { key: 'alarm' },
  { key: 'ttwo' },
  { key: 'eflow_qa' },
  { key: 'nur' },
  { key: 'ms_sla' },
  { key: 'cxoDashboard', iframe: true },
  { key: 'mwUmeTopology', iframe: true },
  { key: 'mwRealTime', iframe: true },
  { key: 'gis' },
  { key: 'realtime_alarm' },
  { key: 'alarmManagement', iframe: true },
  { key: 'packet_loss' },
  { key: 'battery' },
  { key: 'ume_in_kpi' },
  { key: 'ip_trace', iframe: true },
  { key: 'incident_overview', iframe: true },
  { key: 'warehouse', iframe: true },
  { key: 'overview' },
  { key: 'tables' },
  { key: 'upload' },
  { key: 'archive' },
  { key: 'dashboard' },
  { key: 'settings' },
  { key: 'portalLogin' },
]

/** 页面 key → 菜单名 i18n key（App.tsx menuItems 的既有映射） */
export const NAV_KEY_MAP: Record<string, string> = {
  sync: 'nav.sync',
  email_reports: 'nav.emailReports',
  alarm: 'nav.alarm',
  ttwo: 'nav.ttwo',
  eflow_qa: 'nav.eflowQa',
  nur: 'nav.nur',
  ms_sla: 'nav.msSla',
  cxoDashboard: 'nav.cxoDashboard',
  mwUmeTopology: 'nav.mwUmeTopology',
  mwRealTime: 'nav.mwRealTime',
  gis: 'nav.gis',
  realtime_alarm: 'nav.realtimeAlarm',
  alarmManagement: 'nav.alarmManagement',
  packet_loss: 'nav.packetLoss',
  battery: 'nav.battery',
  ume_in_kpi: 'nav.umeInKpi',
  ip_trace: 'nav.ipTrace',
  incident_overview: 'nav.incidentOverview',
  warehouse: 'nav.sp',
  overview: 'nav.overview',
  tables: 'nav.tables',
  upload: 'nav.upload',
  archive: 'nav.archive',
  dashboard: 'nav.dashboard',
  settings: 'nav.settings',
  portalLogin: 'nav.portalLogin',
}

/** 分类（页面按用途分组展示） */
export const CATEGORIES: { id: string; pages: string[] }[] = [
  { id: 'tasks', pages: ['sync', 'email_reports', 'upload', 'tables', 'overview'] },
  {
    id: 'boards',
    pages: ['alarm', 'ttwo', 'nur', 'ms_sla', 'cxoDashboard', 'mwUmeTopology', 'mwRealTime', 'alarmManagement', 'packet_loss', 'battery', 'ume_in_kpi', 'gis', 'realtime_alarm', 'incident_overview', 'warehouse'],
  },
  { id: 'analysis', pages: ['eflow_qa', 'dashboard', 'archive', 'ip_trace'] },
  { id: 'system', pages: ['settings', 'portalLogin'] },
]

/* ---------- 各页面功能描述与使用要点（zh / en） ---------- */

export interface PageDoc { desc: string; usage: string[] }

export const PAGE_DOCS: Record<Locale, Record<string, PageDoc>> = {
  zh: {
    sync: {
      desc: '全站控制中心：查看所有定时同步/采集任务的状态与排程，手动执行、停止、启停、修改 cron 排程，查看执行历史与按天失败聚合。详见本页「任务管理详解」。',
      usage: ['数据没更新时第一个打开这里：点统计卡即筛选，用「失败聚合」排查昨天夜里哪些任务挂了', '单任务「排程」弹窗修改 cron（写入 task_schedule_config，持久化，重启不丢）', '「全局历史」跨任务检索执行记录；任务完成后语音播报可在本页开关'],
    },
    email_reports: {
      desc: '汇总三类任务产物并供下载：邮件发送的最新报告附件、FineBI FTP 报表、eFlow TT 规则检查结果（规则表/矫正表/报告）。',
      usage: ['顶部页签切换类别，点文件名或「下载」保存；可设每类保留最近 N 份', 'eFlow 规则页签可「立即执行」手动触发一次检查（3 秒后自动刷新一次，任务慢时需手动再刷）'],
    },
    alarm: {
      desc: '全网当前活跃告警的综合视图：总量、级别、站点等多维统计与趋势。',
      usage: ['点任意数字弹出可搜索的下钻明细表', '「实时」数据来自 eFlow 活动告警（eflow_active_alarm 每 30 分钟同步），并非秒级推送'],
    },
    ttwo: {
      desc: '故障工单（TT）与工作单（WO）的处理量、时效、积压趋势分析。',
      usage: ['下拉 + 分段控件 + 日期区间组合筛选，点数字下钻明细', '页头显示数据最近同步时间；数据来自 eFlow 每小时同步（eflow_sync）与每日全量兜底（eflow_sync_full）'],
    },
    eflow_qa: {
      desc: 'eFlow TT 判定规则知识库：规则/案例文档全文检索，并内置 TT 快速分析与 TT 批量核查。',
      usage: [
        '空格分隔多关键词检索，或从左侧目录选择文章',
        '输入 TT 单号一键分析：派单归属、时间差、根因分布与结论要点',
        'TT 批量核查：上传 xlsx/csv/txt 单号清单或直接粘贴，逐单判定工单级别是否正常（正常/需调整/无法判定），可导出 Excel',
        'TT 批量核查支持「下载模板 → 填写 → 上传核查」闭环：点「下载模板」得到带表头的 xlsx，填好单号后把同一个文件传回来即可',
      ],
    },
    nur: {
      desc: '网络不可用率（NUR）的日/周/月趋势、多维分析与站点达标情况。',
      usage: ['切换粒度与日期区间，多维下拉筛选', '点数字下钻明细表（支持列内筛选与排序），可一键导出 Excel'],
    },
    ms_sla: {
      desc: 'MS 合同 KPI 与工单 SLA 达成情况：NUR / SLA / Network KPI / Per-Site / WO SLA（指标为行、期间为列）。',
      usage: ['粒度只有日/月两档；下钻明细与 NUR 页一致', '数字以 nur_calc 实时计算为准（ms_sla_full 每 6 小时驱动），可能与历史快照文件不一致——以本页为准'],
    },
    cxoDashboard: {
      desc: 'Service / Network / Summary 三层经营看板（源自 VMAX 实时保障看板）。',
      usage: ['iframe 页面内嵌一份完整数据快照：上游不可用时仍能完整渲染，代价是看到的可能不是最新数据', '要最新数据需重跑对应同步任务；凭据在「系统设置 → 凭据 → vmax_cxo」'],
    },
    mwUmeTopology: {
      desc: 'ZXMW 微波网络拓扑与带宽利用率 NOC 看板（日粒度）。',
      usage: ['数据每天 05:15 由 mw_ume_kpi_sync 写入 mw_ume_bw_ultilazation，本页一天只变一次', '风险榜、抽屉、趋势图均可交互'],
    },
    mwRealTime: {
      desc: '与微波拓扑同构的 15 分钟粒度实时版（拓扑骨架、风险榜、抽屉、趋势完全一致）。',
      usage: ['默认只展示最新一个 15 分钟槽位，滑杆可回看最近 2 小时窗口', '页面默认 900 秒自动刷新，且支持「软刷新」（不重载 iframe、不闪屏）'],
    },
    gis: {
      desc: '站点地图：告警/工单在地图上的分布、拓扑线、区域面与多维筛选（历史/工单口径）。',
      usage: ['区域下拉 + 图层 Tag 开关筛选；图例点击可隐藏该类图层；时间支持分段切换与自定义区间', '点站点打开右侧抽屉，四个页签明细可搜索、可导出 Excel'],
    },
    realtime_alarm: {
      desc: 'GIS 地图的实时模式：当前活跃告警站点的地图分布（带红色「实时」标识）。',
      usage: ['操作与 GIS 地图页一致', '数据来自 eFlow 活动告警（eflow_active_alarm），每 30 分钟同步一次'],
    },
    alarmManagement: {
      desc: '宕站（Site Outage）监控看板：以「站点是否宕」为视角，ERA / Regular / ALL 三个视图。',
      usage: ['每天 01:00 site_outage_screenshot 自动对本页截图，03:00 whatsapp_send 发送到 WhatsApp 群', '注意：改动此页面 DOM 会连带影响自动截图任务，改前先确认截图选择器仍有效'],
    },
    packet_loss: {
      desc: 'LTE 丢包看板（RAN UME SDR / IPRAN IPPD）：最近 7 个完整自然日、小时粒度，当天没过完不展示。',
      usage: ['口径与 Packet_Loss 自动化 Excel 报告完全一致；Popover 可查看口径说明', 'Switch 控制是否包含 OK 站点；支持下钻明细与拓扑叠加'],
    },
    battery: {
      desc: '站点电池健康度 / SOC / 充放电状态与告警明细。',
      usage: ['第一维度是「数据新鲜度」：默认只统计 24 小时内的新鲜读数（battery_kpi_sync 每小时 :05），关闭「仅新鲜」会混入旧数据导致失真', '点站点名下钻电池明细与历史读数；支持导出 Excel'],
    },
    ume_in_kpi: {
      desc: '客户业务 KPI 看板：从 UME 门户（172.17.208.1:28808）抓取 Dong customer 周度业务指标，覆盖 IVR / P4M / VC / USSD / PPS / CPU / Memory 共 7 个模板（1 天粒度）。除业务量与成功率外，本页把失败按「系统侧 / 用户侧」归因——只有系统侧失败率与资源利用率会触发告警，因此像 PPS 的「余额不足」、USSD 的「用户失败」这类业务正常结果不会被误报为故障。',
      usage: [
        '顶部「立即同步」手动触发一次抓取（约 10~60 秒）；日常由 ume_in_kpi_sync 任务每天 05:45 自动同步',
        '「近 7 / 14 / 30 天」切换趋势回看窗口；表头可排序、可按状态筛选',
        '业务 KPI 表点行首展开，查看每个 SERVICE 的业务量、成功率、系统侧/用户侧失败与失败原因标签',
        '「失败率构成」按归因堆叠显示各 KPI 的失败率；「成功率多日趋势」看逐日变化',
        '资源利用率以「日均」判定（≥80% 关注、≥90% 异常），峰值仅作参考——瞬时打满属正常尖峰',
        '「导出 Excel」输出 6 个 sheet：KPI 汇总 / 服务明细 / 失败分解 / 资源 / 趋势 / 告警',
      ],
    },
    ip_trace: {
      desc: 'IP 链路探测：从服务器侧探测到目标站点的链路连通性与路径节点。',
      usage: ['输入目标开始探测，结果表格/地图实时刷新', '探测是可中断的长任务，卡住时可手动停止'],
    },
    incident_overview: {
      desc: 'OLR 事件（Incident）总览看板：卡片、矩阵、SLA 图表、分页明细与地图。',
      usage: ['数据每小时整点由 incident_overview_sync 从 FineBI FTP 取最新 incident_overview.xlsx（版本化落盘，上游文件被占用也不会取数失败）'],
    },
    warehouse: {
      desc: '备件/耗材库存看板（Spare Management），与原工具看板完全一致。',
      usage: ['数据来自 sp_data_sync（每天 07:00 从 SFTP 拉取的 5 份备件报表）', '按仓库/备件类型查看库存与明细'],
    },
    overview: {
      desc: '数据库体检页：库内有多少张表、每张表多少行、Top10 规模排名。',
      usage: ['「行数」列可排序；页面只读——只回答「数据在不在、大不大」'],
    },
    tables: {
      desc: '表浏览器：不写 SQL 就能翻看任意表、看字段画像、导入导出，是最常用的兜底工具。',
      usage: ['表下拉选表 → 分页浏览，关键字搜索防抖；导出 xlsx / CSV', '列显隐可保存为视图模板（同一张表常看固定几列时先存模板）', '「画像」页签查看字段级统计；支持 Excel/CSV 导入'],
    },
    upload: {
      desc: '拖拽 Excel/CSV 入库，并给出数据质量评分。',
      usage: ['拖文件到上传区即可；上传后先看「问题面板 / 结论面板」再决定用不用这批数据', '历史列表可手动刷新'],
    },
    archive: {
      desc: '分析归档：历史分析结果的检索、详情查看与删除，与分析仪表盘配套。',
      usage: ['关键字搜索 + 分页浏览；详情含结论文字与图表快照', '删除需二次确认，谨慎操作'],
    },
    dashboard: {
      desc: '分析仪表盘：选一张表自动生成多维图表与结论，可归档保存。',
      usage: ['选表 → 修改分析名称 → 生成分析 → 归档', '开启「联动筛选」后点饼图/柱图即设置筛选，再点取消'],
    },
    settings: {
      desc: '系统设置：凭据、邮件收件人、远程主机、任务配置四个页签。',
      usage: ['凭据：12 组上游账号，支持测试连接与显示明文（默认掩码；明文存于 db/app.db 的 credentials 表）', '邮件收件人：分组编辑，可重置为默认', '远程主机：改完即时生效无需重启（写 backend/data/settings.json）', '任务配置：任务的业务参数（非排程），优先级 环境变量 > 配置文件 > 默认值'],
    },
    portalLogin: {
      desc: '门户一键登录：用已保存的凭据自动登录上游门户（Playwright 自动化），省去逐个手输账号口令。',
      usage: ['点「登录」后轮询状态并打开门户窗口；「关闭窗口」可关掉会话', '与系统设置共用同一份凭据；会话 cookie 缓存在后端 auth_cache/，请按敏感信息对待'],
    },
  },
  en: {
    sync: {
      desc: 'Central control room for all scheduled sync/collection tasks: view status & schedules, run/stop/enable/disable, edit cron schedules, inspect run history and daily failure summary. See the "Task Manager Deep Dive" section on this page.',
      usage: ['First stop when data looks stale: click a stat card to filter, use the failure summary to see which tasks failed overnight', 'Edit cron in the "Schedule" dialog (persisted in task_schedule_config, survives restarts)', '"Global History" searches runs across tasks; voice announcement on completion toggles here'],
    },
    email_reports: {
      desc: 'Collects three kinds of task artifacts for download: latest email report attachments, FineBI FTP reports, and eFlow TT rule check results (rules / corrections / report).',
      usage: ['Switch categories via tabs; click a file name or "Download" to save; set how many recent files to keep per category', 'The eFlow rule tab supports "Run Now" to trigger a check manually (auto-refreshes once after 3s; refresh manually if the task is slow)'],
    },
    alarm: {
      desc: 'Combined view of all current active network alarms: totals, severity, site-level multi-dimension statistics and trends.',
      usage: ['Click any number to open a searchable drill-down table', '"Realtime" data comes from eFlow active alarms (eflow_active_alarm every 30 min) — not second-level push'],
    },
    ttwo: {
      desc: 'Processing volume, timeliness and backlog trends of trouble tickets (TT) and work orders (WO).',
      usage: ['Filter with selects + segmented control + date range; click numbers to drill down', 'The header shows the latest sync time; data comes from hourly eflow_sync plus the nightly eflow_sync_full backfill'],
    },
    eflow_qa: {
      desc: 'eFlow TT rule knowledge base: full-text search over rule/case documents, with built-in TT quick analysis.',
      usage: ['Search with space-separated keywords or pick an article from the catalog on the left', 'Enter a TT number for one-click analysis: assignment, time gap, root-cause distribution and key conclusions'],
    },
    nur: {
      desc: 'Network Unavailability Rate (NUR) daily/weekly/monthly trends, multi-dimension analysis and site compliance.',
      usage: ['Switch granularity and date range, filter by dimensions', 'Click numbers to drill into a detail table (in-column filters & sorting); export to Excel'],
    },
    ms_sla: {
      desc: 'MS contract KPIs and WO SLA attainment: NUR / SLA / Network KPI / Per-Site / WO SLA (metrics as rows, periods as columns).',
      usage: ['Granularity is daily/monthly only; drill-down reuses the NUR detail table', 'Numbers come from the live nur_calc calculation (driven by ms_sla_full every 6h) and may differ from historical snapshot files — trust this page'],
    },
    cxoDashboard: {
      desc: 'Service / Network / Summary three-tier executive dashboard (from the VMAX assurance board).',
      usage: ['The iframe embeds a full data snapshot: it renders even when the upstream is down, but may not show the latest data', 'Re-run the sync task to refresh; credentials live in Settings → Credentials → vmax_cxo'],
    },
    mwUmeTopology: {
      desc: 'ZXMW microwave network topology & bandwidth utilization NOC board (daily granularity).',
      usage: ['Data is written daily at 05:15 by mw_ume_kpi_sync into mw_ume_bw_ultilazation — the page changes once a day', 'Risk ranking, drawer and trend chart are all interactive'],
    },
    mwRealTime: {
      desc: '15-minute realtime variant of the microwave topology board (same skeleton, risk ranking, drawer and trends).',
      usage: ['Shows only the latest 15-minute slot by default; the slider reviews the last 2 hours', 'Auto-refreshes every 900s with soft refresh (no iframe reload, no flicker)'],
    },
    gis: {
      desc: 'Site map: alarm/ticket distribution, topology lines, region polygons and multi-dimension filters (history/ticket view).',
      usage: ['Region dropdown + layer tags to filter; click a legend item to hide that layer; time supports segments and custom range', 'Click a site to open the right drawer: four tabs, searchable, exportable to Excel'],
    },
    realtime_alarm: {
      desc: 'Realtime mode of the GIS map: current active-alarm sites on the map (red "realtime" badge).',
      usage: ['Interactions are identical to the GIS Map page', 'Data comes from eFlow active alarms (eflow_active_alarm) synced every 30 minutes'],
    },
    alarmManagement: {
      desc: 'Site Outage Monitor board: watches whether sites are down, with ERA / Regular / ALL views.',
      usage: ['Auto-screenshotted daily at 01:00 by site_outage_screenshot and sent to WhatsApp at 03:00 by whatsapp_send', 'Caution: DOM changes on this page affect the screenshot task — verify the screenshot selectors still work first'],
    },
    packet_loss: {
      desc: 'LTE packet loss board (RAN UME SDR / IPRAN IPPD): last 7 complete calendar days at hourly granularity; the ongoing day is hidden.',
      usage: ['Criteria match the Packet_Loss automation Excel report exactly; the Popover explains them', 'The switch controls whether OK sites are included; supports drill-down and topology overlay'],
    },
    battery: {
      desc: 'Site battery health / SOC / charge-discharge status and alarm details.',
      usage: ['The first dimension is data freshness: by default only readings ≤24h old are counted (battery_kpi_sync hourly :05); turning off "fresh only" mixes in stale data', 'Click a site name to drill into batteries and history; export to Excel supported'],
    },
    ume_in_kpi: {
      desc: 'Customer Service KPI dashboard: pulls Dong customer weekly service KPIs from the UME portal (172.17.208.1:28808) across 7 templates — IVR / P4M / VC / USSD / PPS / CPU / Memory (1-day granularity). Besides volume and success rate, failures are attributed to "system side" vs "user side" — only system-side failure rate and resource utilisation raise alerts, so business-normal outcomes such as PPS "insufficient balance" or USSD "user failure" are not misreported as faults.',
      usage: [
        'Click "Sync now" to trigger a fetch manually (about 10-60 s); the ume_in_kpi_sync task normally runs daily at 05:45',
        'Switch "Last 7 / 14 / 30 days" to change the trend window; columns are sortable and filterable by status',
        'Expand a row in the service KPI table to see per-SERVICE volume, success rate, system/user-side failures and failure-reason tags',
        '"Failure-rate composition" stacks each KPI\'s failure rate by attribution; "Success-rate trend" shows the daily movement',
        'Resource utilisation is judged on the daily average (≥80% warning, ≥90% critical); peaks are informational only — brief saturation is normal',
        '"Export Excel" writes 6 sheets: KPI summary / service detail / failure breakdown / resources / trend / alerts',
      ],
    },
    ip_trace: {
      desc: 'IP trace: probe link connectivity and path nodes from the server side to a target site.',
      usage: ['Enter a target and start; the result table/map refreshes live', 'Tracing is a stoppable long task — stop it manually if it hangs'],
    },
    incident_overview: {
      desc: 'OLR incident overview board: cards, matrix, SLA charts, paginated details and a map.',
      usage: ['Data is fetched hourly by incident_overview_sync from the latest incident_overview.xlsx on the FineBI FTP (versioned files, resilient to the upstream file being locked)'],
    },
    warehouse: {
      desc: 'Spare-parts / consumables inventory board (Spare Management), identical to the original tool.',
      usage: ['Data comes from sp_data_sync (5 spare-part reports pulled from SFTP daily at 07:00)', 'Browse inventory and details by warehouse / spare type'],
    },
    overview: {
      desc: 'Database health-check page: how many tables exist, rows per table, Top10 by size.',
      usage: ['Sort by the "Rows" column; the page is read-only — it only answers "is the data there and how big"'],
    },
    tables: {
      desc: 'Table Browser: browse any table without SQL, view column profiles, import & export — the go-to fallback tool.',
      usage: ['Pick a table → paginate & search (debounced); export xlsx / CSV', 'Column visibility can be saved as view templates — save one when you always look at the same columns', 'The "Profile" tab shows per-column statistics; Excel/CSV import supported'],
    },
    upload: {
      desc: 'Drag-and-drop Excel/CSV ingestion with a data-quality score.',
      usage: ['Drop a file to upload; check the issue/conclusion panels before trusting the data', 'The history list can be refreshed manually'],
    },
    archive: {
      desc: 'Analysis archive: search, view and delete past analysis results; pairs with the Dashboard.',
      usage: ['Keyword search + pagination; details include conclusion text and chart snapshots', 'Deletion asks for confirmation — be careful'],
    },
    dashboard: {
      desc: 'Analysis dashboard: pick a table to auto-generate multi-dimension charts and conclusions, archiveable.',
      usage: ['Pick a table → rename → generate → archive', 'With "linked filters" on, clicking a pie/bar applies it as a filter; click again to cancel'],
    },
    settings: {
      desc: 'System settings: credentials, email recipients, remote host, and task configuration — four tabs.',
      usage: ['Credentials: 12 upstream account groups with connection test and plaintext reveal (masked by default; stored plaintext in the credentials table of db/app.db)', 'Email recipients: edit groups, reset to defaults', 'Remote host: takes effect immediately, no restart needed (written to backend/data/settings.json)', 'Task config: business parameters (not schedules); priority: env var > config file > default'],
    },
    portalLogin: {
      desc: 'One-click portal login: auto-logs into upstream portals with saved credentials (Playwright automation).',
      usage: ['Click "Login" then poll status until the portal window opens; "Close Window" ends the session', 'Shares credentials with Settings; session cookies are cached under backend auth_cache/ — treat as sensitive'],
    },
  },
}

/* ---------- 通用操作 / 常见问题（zh / en） ---------- */

export interface Tip { title: string; body: string }
export interface Faq { q: string; a: string }

export interface CommonText {
  intro: string[]
  caps: { do: string[]; dont: string[] }
  tips: Tip[]
  faq: Faq[]
  categories: Record<string, string>
}

const COMMON_ZH: CommonText = {
  intro: [
    '面向网络运维的自动化数据平台：定时从 eFlow、各制式网管（RAN/iPRAN/CNN/MW UME、CN EMS）、FineBI、FTP、邮箱等上游系统采集与同步数据，统一入库后以看板、表格与报告的形式呈现。',
    '典型链路：定时任务采集 → 数据入库（PostgreSQL 主库 + 各任务独立 SQLite）→ 看板展示 / Excel 报表与邮件、WhatsApp 分发 → 告警与工单闭环分析。',
    '服务场景是「每天要看板、要发报表、报表不能漏」的 NOC 运维：41+ 个定时任务、20+ 个功能页、失败自动重试与漏跑补投、进程级看门狗自愈。',
  ],
  caps: {
    do: [
      '41+ 个定时任务驱动数据采集与报表投递（backend/task_registry.py 统一注册）',
      '所有功能页在一个 SPA 内，中英文可切换，看板指标可点击下钻',
      '通用表能力：任意表浏览、字段画像、Excel/CSV 导入导出、视图模板',
      '自动补漏：失败任务自动重试、漏跑任务自动补投；进程自愈：看门狗托管 + 心跳强杀重拉',
    ],
    dont: [
      '没有多用户体系：没有注册/角色/审计，任何能访问入口的人都拥有完整操作能力',
      '不对外提供 HTTPS：TLS 需由前置 nginx 终结；上游证书校验默认关闭',
      '不做数据编辑：数据「抓进来只读」，页面无业务写回上游的能力（仅凭据/收件人/排程等配置可写）',
      '不是高可用服务：单实例锁（db/instance.lock）保证同机只跑一份，无集群与故障转移',
    ],
  },
  tips: [
    { title: '侧边栏导航', body: '侧边栏默认收起，点左上角 ☰ 按钮展开/收起；移动端以抽屉浮层从顶栏下方滑出。' },
    { title: '新标签页打开', body: '在左侧菜单项上右键 → 「在新标签页打开」，适合大屏/多屏分屏值守。' },
    { title: '直链访问', body: '任何页面都可用 ?page=<key> 直接打开，例如 /myapp/?page=battery，可收藏、可分享。' },
    { title: '自动刷新', body: '顶栏下拉选择间隔（默认 5 分钟，可选 0/30s~30min）；正在输入、弹窗打开或标签页在后台时本轮自动跳过，不打断操作。' },
    { title: '主题与语言', body: '右上角切换深/浅色主题与中/英文界面，偏好自动保存在本机（localStorage）。' },
    { title: '数据新鲜度', body: '部分页面页头显示「最近同步」时间。看板数据由定时任务写入，各任务频率不同（告警 30 分钟、微波拓扑每天 05:15、丢包每天 06:30 等），完整清单见「任务管理详解」。' },
  ],
  faq: [
    { q: '看板数据没有更新？', a: '① 先到「任务管理」查看对应任务的最近执行结果与失败聚合；② 检查顶栏「自动刷新」间隔是否被调成关闭；③ 注意部分数据本身低频同步：实时告警每 30 分钟、微波拓扑每天 05:15、丢包每天 06:30、事件总览每小时整点。仍不对可看「数据库数据新鲜度巡检」的执行日志，它会输出调用链与排查方向。' },
    { q: '页面数字与预期口径不一致？', a: '注意各页口径：电池看板默认只统计 24 小时内新鲜读数；MS SLA 看板以实时计算为准（可能与快照文件不一致）；丢包看板只展示最近 7 个完整自然日；CXO 看板内嵌快照，重跑同步任务才更新。' },
    { q: '任务长期停在 pending 不执行？', a: '多半是该任务未被归入任何 worker 组（GROUP_TASK_MAP），队列里永远无人认领——这是本项目已发生过三次的事故模式（finebi_report_sync、whatsapp_send_ext、sp_email_details）。新增任务必须在 worker_watchdog.py 的 GROUP_TASK_MAP 登记分组。' },
    { q: '任务反复 failed？', a: '到 log/worker_runtime*.log 找该 task_id 的堆栈（排障首选日志；每组 worker 一个文件，任务所属组见执行认领日志）。上游不可达 → 先到「系统设置 → 凭据」点「测试连接」；口令变了 → 更新凭据。auto_retry_failed 每 10 分钟自动重试（MAX_ATTEMPTS=2，超 24 小时放弃），无需手动反复点执行。' },
    { q: '任务一直「执行中」不动？', a: '调度器没有 per-task 超时（设计缺口）。僵尸运行态由 worker 每 300 秒扫描回收（30 分钟 + PID 存活核对），无需手工干预；若任务真在长跑（如 Playwright 探测），可在任务管理页手动「停止」。' },
    { q: '邮件没发出去？', a: 'EWS 邮箱故障时邮件任务会失败，email_recovery（每 20 分钟）会在恢复后自动补发近 3 小时内失败的邮件——先查它的执行历史，而不是手动重跑原邮件任务。邮箱空间满由 mailbox_cleanup（每小时）守卫。' },
    { q: '如何在大屏/另一个标签页打开看板？', a: '右键点击左侧菜单项 → 「在新标签页打开」；或直接访问直链 http://<host>/myapp/?page=<key>。配合顶栏「自动刷新」即可长期挂机展示。' },
    { q: '上传的数据质量如何确认？', a: '「数据上传」页入库后会给出问题面板与质量评分；确认无问题后可到「表浏览器」查看数据与字段画像，再用「分析仪表盘」出图。' },
    { q: '忘记某个指标/术语的定义？', a: '多数看板的指标旁有口径说明图标（Metric Explain）；更完整的术语表与逐页手册见项目文档 docs/manual/（01-overview 术语表、11-feature-guide 功能页手册）。' },
  ],
  categories: {
    tasks: '任务与数据',
    boards: '监控看板',
    analysis: '分析与工具',
    system: '系统管理',
  },
}

const COMMON_EN: CommonText = {
  intro: [
    'An automation platform for network operations: scheduled jobs collect & sync data from upstream systems (eFlow, various NMS — RAN/iPRAN/CNN/MW UME & CN EMS, FineBI, FTP, mailboxes), store it centrally, and present it as dashboards, tables and reports.',
    'Typical pipeline: scheduled collection → central storage (PostgreSQL main DB + per-task SQLite files) → dashboards / Excel reports & email, WhatsApp delivery → alarm & ticket analysis.',
    'Built for the NOC scenario "boards every day, reports must go out": 41+ scheduled tasks, 20+ pages, auto-retry & missed-run backfill, watchdog-based process self-healing.',
  ],
  caps: {
    do: [
      '41+ scheduled tasks drive collection & report delivery (registered in backend/task_registry.py)',
      'All pages in one SPA, Chinese/English switchable, board metrics click-to-drill-down',
      'Generic table powers: browse any table, column profiles, Excel/CSV import & export, view templates',
      'Auto backfill: failed-task retry & missed-run backfill; process self-healing: watchdogs + heartbeat force-restart',
    ],
    dont: [
      'No multi-user system: no signup/roles/audit — anyone reaching the entry has full control',
      'No HTTPS out of the box: TLS must be terminated by a front nginx; upstream TLS verification is off by default',
      'No data editing: data is "collected read-only"; pages cannot write back to upstreams (only credentials/recipients/schedules are configurable)',
      'Not highly available: a single-instance lock (db/instance.lock) allows only one copy per machine; no clustering/failover',
    ],
  },
  tips: [
    { title: 'Sidebar navigation', body: 'The sidebar is collapsed by default — click the ☰ button (top-left) to expand/collapse; on mobile it slides out as a drawer under the header.' },
    { title: 'Open in a new tab', body: 'Right-click any menu item → "Open in new tab", handy for wall screens / multi-monitor duty.' },
    { title: 'Direct links', body: 'Every page can be opened with ?page=<key>, e.g. /myapp/?page=battery — bookmarkable and shareable.' },
    { title: 'Auto refresh', body: 'Pick an interval in the header (default 5 minutes; 0/30s~30min available). While you are typing, a dialog is open, or the tab is in the background, the round is skipped to avoid interrupting you.' },
    { title: 'Theme & language', body: 'Switch dark/light theme and Chinese/English in the top-right; preferences are remembered locally (localStorage).' },
    { title: 'Data freshness', body: 'Some pages show a "last synced" time in the header. Boards are fed by scheduled tasks with different frequencies (alarms every 30 min, microwave topology daily 05:15, packet loss daily 06:30...). See "Task Manager Deep Dive" for the full catalog.' },
  ],
  faq: [
    { q: 'The board data is not updating?', a: '① Check the task\'s latest result and the failure summary in "Task Manager"; ② check whether the header "Auto refresh" was set to Off; ③ remember some data is inherently low-frequency: alarms every 30 min, microwave topology daily 05:15, packet loss daily 06:30, incident overview hourly. The "DB Data Freshness Check" task history also logs the call chain and direction when stale.' },
    { q: 'Numbers do not match the expected criteria?', a: 'Watch each page\'s definition: the battery board counts only readings ≤24h fresh by default; the MS SLA board follows the live calculation (snapshot files may differ); packet loss shows only the last 7 complete days; the CXO board embeds a snapshot refreshed only by re-running its sync task.' },
    { q: 'A task stays pending forever?', a: 'Most likely the task was never assigned to a worker group (GROUP_TASK_MAP) — nobody claims it from the queue. This accident happened three times in this project (finebi_report_sync, whatsapp_send_ext, sp_email_details). New tasks MUST be registered in GROUP_TASK_MAP in worker_watchdog.py.' },
    { q: 'A task keeps failing?', a: 'Find the stack trace for the task_id in log/worker_runtime*.log (the first log to check; one file per worker group). Upstream unreachable → run "Test Connection" in Settings → Credentials; changed password → update credentials. auto_retry_failed retries every 10 min (MAX_ATTEMPTS=2, gives up after 24h) — no need to click Run repeatedly.' },
    { q: 'A task stuck in "running"?', a: 'The scheduler has no per-task timeout (known design gap). Zombie running states are recycled by the worker every 300s (30-min staleness + PID liveness) — no manual action needed; if the task genuinely runs long (e.g. Playwright probing), stop it manually from Task Manager.' },
    { q: 'An email was not delivered?', a: 'When the EWS mailbox is down, email tasks fail; email_recovery (every 20 min) re-sends those from the last 3 hours once EWS is back — check its history first instead of re-running the original task. Mailbox full is guarded by mailbox_cleanup (hourly).' },
    { q: 'How to open a board on a wall screen / another tab?', a: 'Right-click the menu item → "Open in new tab"; or open http://<host>/myapp/?page=<key> directly. Combine with the header auto refresh for unattended display.' },
    { q: 'How do I verify uploaded data quality?', a: 'The "Data Upload" page shows an issue panel and a quality score after ingestion; then inspect the data and column profiles in "Table Browser" and chart it in "Dashboard".' },
    { q: 'Where are metric/term definitions?', a: 'Most boards show a metric-explain icon next to indicators; the full glossary and per-page manual live in docs/manual/ (01-overview glossary, 11-feature-guide).' },
  ],
  categories: {
    tasks: 'Tasks & Data',
    boards: 'Monitoring Boards',
    analysis: 'Analysis & Tools',
    system: 'System',
  },
}

export const COMMON: Record<Locale, CommonText> = { zh: COMMON_ZH, en: COMMON_EN }

/* ---------- 任务系统：机制与维护（依据 04-task-system.md / 13-operations.md） ---------- */

export interface OpsText {
  tabs: Record<string, string>
  lifecycle: { title: string; body: string }[]
  groupCols: string[]
  taskCols: Record<string, string>
  flowLabel: string
  maintainLabel: string
  scriptLabel: string
  searchPlaceholder: string
  allGroups: string
  expandHint: string
  mechanisms: { name: string; body: string }[]
  maintain: { title: string; body: string }[]
  upstreamDown: { sys: string; symptom: string; heal: string }[]
  upstreamCols: string[]
  ports: { port: string; proc: string; guard: string }[]
  portCols: string[]
  inspect: string[]
  logs: { file: string; body: string }[]
  logCols: string[]
  backup: { obj: string; body: string }[]
  cleanupSafe: string[]
  cleanupKeep: string[]
  configPriority: string
  credentialNote: string[]
}

const OPS_ZH: OpsText = {
  tabs: { intro: '平台简介', tasks: '任务管理详解', pages: '页面指南', ops: '运维与排障' },
  lifecycle: [
    { title: '① 调度到点', body: 'APScheduler 在后端进程内按 cron 到点触发（backend/task_runner.py）。默认 cron 写在 task_registry.py 的 TASK_SPECS，实际排程读 task_schedule_config 表——所以在页面改排程立即生效且重启不丢。' },
    { title: '② 入队', body: 'enqueue_task() 向主库 task_queue 写一行待执行记录。' },
    { title: '③ worker 认领', body: '对应分组的 worker 进程用 UPDATE…RETURNING 原子认领该行（backend/worker.py）。MY_APP_TASK_QUEUE=1 未设置时退化为调度器进程内线程执行。' },
    { title: '④ 执行', body: 'run_task() 调用真正的 service 函数（task_registry.py 里每条任务声明 func 或 loader=("模块路径","函数名") 懒加载）。业务函数抛异常即记为失败——不要在业务代码里吞异常。' },
    { title: '⑤ 回写终态', body: '_finish() 回写任务终态并写 task_execution_log 执行历史（队列与执行日志保留 3 天）。失败时经微信 + 邮件双通道通知。' },
  ],
  groupCols: ['组', '约束原因', '成员'],
  taskCols: { task: '任务', cron: '默认 cron', group: '组', script: '工作流脚本', flow: '工作流与数据流', maintain: '维护要点' },
  flowLabel: '工作流与数据流',
  maintainLabel: '维护要点',
  scriptLabel: '脚本',
  searchPlaceholder: '搜索任务 ID / 名称 / 说明…',
  allGroups: '全部分组',
  expandHint: '点击行首展开工作流与维护要点',
  mechanisms: [
    { name: '僵尸 running 回收', body: '无 per-task 超时（设计缺口）。worker 每 300s 扫描：running 超 30 分钟（STALE_RUNNING_SECONDS）且 PID 已死亡的记录按失败回收。' },
    { name: '失败自动重试', body: 'auto_retry_failed 每 10 分钟扫描：失败任务先判断数据缺口是否已被后续成功执行补上，未补上且未超 MAX_ATTEMPTS=2 才重投；超过 24h 硬上限直接放弃。' },
    { name: '漏跑补投', body: '时效窗口内应触发却完全没有执行记录的任务自动补投一次（MISS_GRACE_MIN=15 宽限；邮件类默认排除，由 EWS 补发机制负责）。' },
    { name: '失败通知', body: '任务失败经微信 + 邮件双通道告警（services/weixin_notifier.py 支持 openclaw/wecom/serverchan/pushplus）。' },
    { name: '进程自愈', body: 'backend_watchdog / worker_watchdog 托管进程：端口探活、崩溃退避重拉（连崩 10 次放弃并告警）；心跳 log/heartbeat_*.json 超 3 分钟未更新判定 hung 强杀重拉。' },
    { name: '保留期', body: 'task_queue 与 task_execution_log 保留 3 天（task_runner.py / worker.py 自动清理），无需手工。' },
  ],
  maintain: [
    { title: '改排程（cron）', body: '「任务管理 → 排程」弹窗修改，写入主库 task_schedule_config 表，立即生效、重启不丢；无需改代码。' },
    { title: '改业务参数', body: '「系统设置 → 任务配置」页签（注意在系统设置里，不在任务管理页）。优先级：环境变量 > 配置文件 > 默认值。' },
    { title: '改上游账号口令', body: '「系统设置 → 凭据」选分组更新，点「测试连接」验证（凭据明文存于 db/app.db 的 credentials 表，缓存 30s）。' },
    { title: '改收件人', body: '「系统设置 → 邮件收件人」分组编辑，可重置默认；改完对所有 kpi_* / *_email 任务生效。' },
    { title: '手动执行 / 停止', body: '任务管理页「执行」立即投递一次、「停止」中断长任务。验证新排程/新脚本后应先手动跑一次看执行历史。' },
    { title: '新增一个任务', body: '① task_registry.py 的 TASK_SPECS 追加声明（task_id/name/cron/loader）；② worker_watchdog.py 的 GROUP_TASK_MAP 登记分组（漏了永远 pending，已三次踩坑）；③ 业务函数放 backend/services/ 且抛异常不吞；④ stop.bat → start.bat 重启加载注册表；⑤ 手动执行验证并更新文档（04-task-system.md 清单与本帮助页）。' },
    { title: '改工作流脚本', body: '脚本都在 backend/services/ 下（任务清单有对应路径）。改动时注意：① 别改历史拼写名（packet_lost、battary_kpi_fetch、ultilazation 等，多处按字符串引用）；② 动态采集表不进 Alembic；③ 同步更新 task_registry.md / WORKER.md / 本帮助数据（frontend/src/pages/helpTaskDocs.ts）。' },
    { title: '任务卡 pending / failed 排查顺序', body: '① pending 不动 → 查是否漏分组；② failed → log/worker_runtime*.log（每组 worker 一个文件）找 task_id 堆栈 → 凭据「测试连接」；③ 数据停更 → db_freshness_check 的执行历史有调用链。' },
  ],
  upstreamDown: [
    { sys: 'eFlow / 各 UME 会话被踢', symptom: '该组任务连续 failed', heal: 'auto_retry_failed 每 10 分钟重试；凭据「测试连接」验证账号' },
    { sys: 'Exchange (EWS) 挂了', symptom: '邮件任务失败、报表漏发', heal: 'email_recovery 恢复后自动补发近 3 小时失败邮件' },
    { sys: '远程主机不可达', symptom: '写库/上传失败、新鲜度巡检告警', heal: 'db_freshness_check 输出调用链与检查方向；查「系统设置 → 远程主机」连通性' },
    { sys: 'FineBI 文件被占用', symptom: '（历史问题）取数失败', heal: '已改为版本化文件 + current.json 指针，被打开也不会失败' },
    { sys: 'CN EMS 服务端清理原始文件', symptom: '当日 KPI 缺失', heal: 'ems_kpi_cache_sync 每 15 分钟增量缓存抢在清理前保住数据' },
  ],
  upstreamCols: ['上游异常', '表现', '自愈手段'],
  ports: [
    { port: '7038', proc: 'uvicorn / FastAPI 后端（/api/*、/docs）', guard: 'backend_watchdog.py' },
    { port: '7090', proc: 'vite preview 前端（生产经 nginx /myapp/ 反代）', guard: 'start_hidden.ps1' },
    { port: '5432', proc: 'PostgreSQL 16 主库', guard: '自启脚本 pg_ctl 拉起' },
    { port: '8787 / 8790', proc: 'FMS / VMAX 实时代理（仅 127.0.0.1）', guard: 'backend 启动线程' },
    { port: '—', proc: 'worker × 4 组（u/n/m/c，消费 task_queue）', guard: 'worker_watchdog.py' },
  ],
  portCols: ['端口', '进程', '谁负责活着'],
  inspect: [
    '任务管理页：有没有 failed、有没有长期 pending（失败聚合视图比翻列表快）',
    '页头同步标签：GIS / TT&WO / Dashboard 的「最近同步」是否在预期窗口内',
    '数据总览页：表数量与行数是否明显异常',
    '命令行：五个关键进程是否都在、心跳 heartbeat_*.json 是否新鲜（超 3 分钟会被强杀重拉）',
    '数据库新鲜度由 db_freshness_check 每小时 :15 自动巡检，滞后会给出调用链与排查方向',
  ],
  logs: [
    { file: 'log/worker_runtime*.log', body: '任务执行主日志——排障首选，按 task_id 搜堆栈（每组 worker 一个文件：_u/_n/_m/_c）' },
    { file: 'log/backend_runtime.log', body: '后端业务日志（API、调度、代理）' },
    { file: 'log/backend_watchdog.log / worker_watchdog.log', body: '进程拉起与崩溃退避记录（连崩 10 次放弃并告警）' },
    { file: 'log/start_hidden_result.txt', body: '上一次启动的逐条结果——启动失败先看这个' },
    { file: 'log/heartbeat_*.json', body: '后端与 worker 心跳（15s 一次，超 3 分钟判 hung）' },
    { file: 'log/*_console.log(.err)', body: '各子进程 stdout/stderr' },
  ],
  logCols: ['日志文件（log/）', '内容'],
  backup: [
    { obj: '远程 PostgreSQL（主库）', body: 'pg_dump 备份业务数据与 task_queue/task_execution_log/task_schedule_config；pg_to_sqlite_sync 每小时 :45 已提供一份镜像到 db/app.db' },
    { obj: 'db/app.db（SQLite）', body: 'credentials 凭据表（明文）不随 PG 走——只备份 PG 会丢凭据，只备份 app.db 会丢业务数据，两者都要' },
    { obj: 'data/ + backend/data/', body: '各任务报表产物与 settings.json（丢 settings.json 会退回内置默认远程主机）' },
    { obj: 'backend/services/*.json', body: '上游连接参数与 TT 规则表等，属代码资产随仓库走' },
  ],
  cleanupSafe: [
    '运行日志 log/*.log（大文件先停服务再清，避免句柄占用；没有日志轮转，会一直涨）',
    '一次性调试产物：log/edge_cleanup*.txt、killlog*.txt、backend/restart_dbg.log 等',
    '历史空库 data/app.db、data/my_app.db（0 字节）；旧构建目录 frontend/dist、dist2、dist3（删前确认 nginx 未指向）',
  ],
  cleanupKeep: [
    'db/app.db —— 含凭据表（明文）与 PG 快照镜像，约 954MB，绝对不是垃圾文件',
    'backend/services/auth_cache/ —— 上游站点会话 cookie（等同有效登录态），不得外发',
    'data/ 下各任务目录 —— 报表产物与任务专用 SQLite',
    'backend/services/eflow_rules/eflow_TT_rules.xlsx —— 正式 TT 规则表（根目录同名文件只是副本）',
    '历史拼写目录/文件名（data/packet_lost、battary_kpi_fetch、mw_ume_bw_ultilazation 等）——多处按字符串引用，不要顺手改名',
  ],
  configPriority: '三层配置，优先级从高到低：环境变量（backend/.env，147 个键，改后需重启） > 数据库/配置文件（凭据、收件人、排程、远程主机、任务参数——界面改，即时生效） > 代码默认值。',
  credentialNote: [
    '12 个凭据分组：zte_ume、vmax_cxo、ipran_ume、ccn_ume、eflow、fms_portal、fw_kpi、mw_ume、sftp_sp、mail_126、owa_mail、weixin（系统设置 → 凭据 统一维护）',
    '读取优先级：环境变量 > 数据库 > 空；列表接口返回掩码，「显示明文」与「测试连接」单独提供',
    '凭据明文存于 db/app.db 的 credentials 表（credential_store 直连 SQLite，绕过 MY_APP_DB_MODE）——备份必带该文件，且按敏感介质保管',
    'backend/services/auth_cache/ 里的会话 cookie 等同有效登录态，不外发、不入 git、不进截图',
  ],
}

const OPS_EN: OpsText = {
  tabs: { intro: 'Platform', tasks: 'Task Manager Deep Dive', pages: 'Pages Guide', ops: 'Ops & Troubleshooting' },
  lifecycle: [
    { title: '① Schedule fires', body: 'APScheduler fires inside the backend process per cron (backend/task_runner.py). Default crons live in TASK_SPECS (task_registry.py); the effective schedule is read from the task_schedule_config table — so editing it on the page takes effect immediately and survives restarts.' },
    { title: '② Enqueue', body: 'enqueue_task() writes one pending row into the task_queue table (main DB).' },
    { title: '③ Worker claim', body: 'The group\'s worker atomically claims the row via UPDATE…RETURNING (backend/worker.py). Without MY_APP_TASK_QUEUE=1 tasks fall back to in-process threads.' },
    { title: '④ Run', body: 'run_task() invokes the real service function (each TASK_SPECS entry declares func or a lazy loader tuple). Throwing an exception marks the task failed — never swallow exceptions in business code.' },
    { title: '⑤ Finish', body: '_finish() writes the final state and an execution history row into task_execution_log (queue & logs kept 3 days). Failures notify via WeChat + email.' },
  ],
  groupCols: ['Group', 'Why grouped', 'Members'],
  taskCols: { task: 'Task', cron: 'Default cron', group: 'Group', script: 'Workflow script', flow: 'Workflow & data flow', maintain: 'Maintenance' },
  flowLabel: 'Workflow & data flow',
  maintainLabel: 'Maintenance',
  scriptLabel: 'Script',
  searchPlaceholder: 'Search task ID / name / description…',
  allGroups: 'All groups',
  expandHint: 'Expand a row for workflow & maintenance notes',
  mechanisms: [
    { name: 'Zombie running recycling', body: 'No per-task timeout (known gap). Worker scans every 300s: running rows older than 30 min (STALE_RUNNING_SECONDS) with a dead PID are marked failed.' },
    { name: 'Auto retry', body: 'auto_retry_failed scans every 10 min: a failed task is re-enqueued only if its data gap is not yet filled and attempts < MAX_ATTEMPTS=2; abandoned beyond the 24h hard cap.' },
    { name: 'Missed-run backfill', body: 'Tasks that should have fired but have no execution record at all are backfilled once (MISS_GRACE_MIN=15; email tasks excluded — handled by EWS recovery).' },
    { name: 'Failure notification', body: 'Failures notify via WeChat + email (services/weixin_notifier.py supports openclaw/wecom/serverchan/pushplus).' },
    { name: 'Process self-healing', body: 'backend_watchdog / worker_watchdog supervise processes: port probing, crash backoff (give up & alert after 10 consecutive crashes); heartbeats in log/heartbeat_*.json stale >3 min → force kill & restart.' },
    { name: 'Retention', body: 'task_queue & task_execution_log are kept 3 days (auto-cleaned), no manual work.' },
  ],
  maintain: [
    { title: 'Change schedule (cron)', body: 'Task Manager → "Schedule" dialog; persisted into task_schedule_config, effective immediately, survives restarts — no code change needed.' },
    { title: 'Change task parameters', body: 'Settings → "Task Config" tab (it lives under Settings, not Task Manager). Priority: env var > config file > default.' },
    { title: 'Change upstream credentials', body: 'Settings → Credentials, pick the group, update, then "Test Connection" (plaintext in db/app.db credentials table; 30s cache).' },
    { title: 'Change recipients', body: 'Settings → Email Recipients, edit groups or reset to defaults; applies to all kpi_* / *_email tasks.' },
    { title: 'Run / stop manually', body: '"Run" enqueues immediately, "Stop" interrupts a long task. After changing a schedule or script, run once manually and check the history.' },
    { title: 'Add a new task', body: '① Append an entry to TASK_SPECS in task_registry.py; ② register it in GROUP_TASK_MAP in worker_watchdog.py (missing = forever pending, three accidents so far); ③ business function in backend/services/, throw exceptions; ④ restart via stop.bat → start.bat; ⑤ verify manually and update docs (04-task-system.md list & this help).' },
    { title: 'Edit a workflow script', body: 'All scripts live under backend/services/ (paths listed in the task catalog). Mind: ① never "fix" historical spellings (packet_lost, battary_kpi_fetch, ultilazation — string-referenced); ② dynamic collection tables stay out of Alembic; ③ sync-update task_registry.md / WORKER.md / the help data (frontend/src/pages/helpTaskDocs.ts).' },
    { title: 'Pending / failed triage order', body: '① pending forever → check worker-group registration; ② failed → task_id stack in log/worker_runtime*.log (one file per worker group) → "Test Connection" for credentials; ③ data stalled → db_freshness_check history has the call chain.' },
  ],
  upstreamDown: [
    { sys: 'eFlow / UME session kicked', symptom: 'Consecutive failures in the group', heal: 'auto_retry_failed retries every 10 min; verify account via "Test Connection"' },
    { sys: 'Exchange (EWS) down', symptom: 'Email tasks fail, reports missing', heal: 'email_recovery re-sends last-3h failures automatically once restored' },
    { sys: 'Remote host unreachable', symptom: 'DB writes/uploads fail, freshness alerts', heal: 'db_freshness_check prints the call chain; check Settings → Remote Host connectivity' },
    { sys: 'FineBI file locked open', symptom: '(historical) fetch failures', heal: 'Fixed with versioned files + current.json pointer — locked files no longer break ingestion' },
    { sys: 'CN EMS server cleans raw files', symptom: 'Daily KPIs missing', heal: 'ems_kpi_cache_sync caches incrementally every 15 min before server cleanup' },
  ],
  upstreamCols: ['Upstream issue', 'Symptom', 'Self-healing'],
  ports: [
    { port: '7038', proc: 'uvicorn / FastAPI backend (/api/*, /docs)', guard: 'backend_watchdog.py' },
    { port: '7090', proc: 'vite preview frontend (production via nginx /myapp/)', guard: 'start_hidden.ps1' },
    { port: '5432', proc: 'PostgreSQL 16 main DB', guard: 'autostart scripts via pg_ctl' },
    { port: '8787 / 8790', proc: 'FMS / VMAX realtime proxies (127.0.0.1 only)', guard: 'backend startup threads' },
    { port: '—', proc: 'workers × 4 groups (u/n/m/c consuming task_queue)', guard: 'worker_watchdog.py' },
  ],
  portCols: ['Port', 'Process', 'Kept alive by'],
  inspect: [
    'Task Manager: any failed? any long-standing pending? (the failure summary view beats scrolling the list)',
    'Header sync badges: are "last synced" labels on GIS / TT&WO / Dashboard within the expected window',
    'Overview page: table count & row counts clearly abnormal?',
    'CLI: are the five key processes alive and heartbeats (heartbeat_*.json) fresh (>3 min stale → force-restart)',
    'DB freshness is audited hourly at :15 by db_freshness_check; staleness logs include the call chain',
  ],
  logs: [
    { file: 'log/worker_runtime*.log', body: 'Main task-execution log — first stop for troubleshooting; search by task_id for stacks (one file per worker group)' },
    { file: 'log/backend_runtime.log', body: 'Backend business log (API, scheduler, proxies)' },
    { file: 'log/backend_watchdog.log / worker_watchdog.log', body: 'Process spawn & crash-backoff records (gives up after 10 consecutive crashes)' },
    { file: 'log/start_hidden_result.txt', body: 'Per-step result of the last startup — check this first when startup fails' },
    { file: 'log/heartbeat_*.json', body: 'Backend & worker heartbeats (15s; >3 min stale = hung)' },
    { file: 'log/*_console.log(.err)', body: 'Child-process stdout/stderr' },
  ],
  logCols: ['Log file (log/)', 'Content'],
  backup: [
    { obj: 'Remote PostgreSQL (main DB)', body: 'pg_dump for business data + task_queue/task_execution_log/task_schedule_config; pg_to_sqlite_sync already mirrors it into db/app.db hourly at :45' },
    { obj: 'db/app.db (SQLite)', body: 'Hosts the plaintext credentials table — backing up only PG loses credentials, only app.db loses business data; back up both' },
    { obj: 'data/ + backend/data/', body: 'Task report artifacts and settings.json (losing it reverts the remote host to the built-in default)' },
    { obj: 'backend/services/*.json', body: 'Upstream connection params & TT rule sheets — code assets, travel with the repo' },
  ],
  cleanupSafe: [
    'Runtime logs log/*.log (stop services before deleting large ones to release handles; no log rotation exists)',
    'One-off debug artifacts: log/edge_cleanup*.txt, killlog*.txt, backend/restart_dbg.log, etc.',
    'Empty legacy DBs data/app.db & data/my_app.db (0 bytes); old build dirs frontend/dist, dist2, dist3 (confirm nginx no longer points there first)',
  ],
  cleanupKeep: [
    'db/app.db — hosts the plaintext credentials table + the PG snapshot mirror, ≈954MB, absolutely not garbage',
    'backend/services/auth_cache/ — upstream session cookies (equivalent to valid logins); never ship, commit or screenshot',
    'Task folders under data/ — report artifacts and per-task SQLite files',
    'backend/services/eflow_rules/eflow_TT_rules.xlsx — the authoritative TT rule sheet (the root-level same-name file is a copy)',
    'Historical spellings (data/packet_lost, battary_kpi_fetch, mw_ume_bw_ultilazation...) — string-referenced, never rename casually',
  ],
  configPriority: 'Three config layers, highest first: environment variables (backend/.env, 147 keys, restart required) > DB/config files (credentials, recipients, schedules, remote host, task params — edited via UI, effective immediately) > code defaults.',
  credentialNote: [
    '12 credential groups: zte_ume, vmax_cxo, ipran_ume, ccn_ume, eflow, fms_portal, fw_kpi, mw_ume, sftp_sp, mail_126, owa_mail, weixin (maintained in Settings → Credentials)',
    'Read priority: env var > DB > empty; the list API returns masks, with separate "reveal" and "test connection" endpoints',
    'Credentials are stored plaintext in the credentials table of db/app.db (credential_store opens SQLite directly, bypassing MY_APP_DB_MODE) — always include the file in backups, treat as sensitive media',
    'Session cookies under backend/services/auth_cache/ are equivalent to valid logins — never ship, commit or screenshot them',
  ],
}

export const OPS: Record<Locale, OpsText> = { zh: OPS_ZH, en: OPS_EN }
