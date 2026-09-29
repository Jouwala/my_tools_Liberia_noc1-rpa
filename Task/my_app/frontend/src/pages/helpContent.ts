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
  { key: 'v1_ttwo' },
  { key: 'tt' },
  { key: 'wo' },
  { key: 'eflow_qa' },
  { key: 'eflow_flow' },
  { key: 'nur' },
  { key: 'ms_nur_only' },
  { key: 'ms_sla' },
  { key: 'ms_sla_only' },
  { key: 'cxoDashboard', iframe: true },
  { key: 'mwUmeTopology', iframe: true },
  { key: 'mwRealTime', iframe: true },
  { key: 'gis' },
  { key: 'realtime_alarm' },
  { key: 'alarmManagement', iframe: true },
  { key: 'fme_ranking' },
  { key: 'site_avail' },
  { key: 'avail_ms' },
  { key: 'avail_flm' },
  { key: 'noc_analyst' },
  { key: 'repeat_site_down' },
  { key: 'cr_analysis' },
  { key: 'pm_analysis' },
  { key: 'bp_report' },
  { key: 'packet_loss' },
  { key: 'battery' },
  { key: 'ume_in_kpi' },
  { key: 'imonitor', iframe: true },
  { key: 'ip_trace', iframe: true },
  { key: 'incident_overview', iframe: true },
  { key: 'warehouse', iframe: true },
  { key: 'sp_material' },
  { key: 'sp_details' },
  { key: 'sp_report' },
  { key: 'com_report' },
  { key: 'warehouse_summary' },
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
  v1_ttwo: 'nav.v1Ttwo',
  tt: 'nav.tt',
  wo: 'nav.wo',
  eflow_qa: 'nav.eflowQa',
  eflow_flow: 'nav.eflowFlow',
  nur: 'nav.nur',
  ms_nur_only: 'nav.msNurOnly',
  ms_sla: 'nav.msSla',
  ms_sla_only: 'nav.msSlaOnly',
  cxoDashboard: 'nav.cxoDashboard',
  mwUmeTopology: 'nav.mwUmeTopology',
  mwRealTime: 'nav.mwRealTime',
  gis: 'nav.gis',
  realtime_alarm: 'nav.realtimeAlarm',
  alarmManagement: 'nav.alarmManagement',
  fme_ranking: 'nav.fmeRanking',
  site_avail: 'nav.siteAvail',
  avail_ms: 'nav.availMs',
  avail_flm: 'nav.availFlm',
  noc_analyst: 'noc.navLabel',
  repeat_site_down: 'nav.repeatSiteDown',
  cr_analysis: 'nav.crAnalysis',
  pm_analysis: 'nav.pmAnalysis',
  bp_report: 'nav.bpReport',
  packet_loss: 'nav.packetLoss',
  battery: 'nav.battery',
  ume_in_kpi: 'nav.umeInKpi',
  imonitor: 'nav.imonitor',
  ip_trace: 'nav.ipTrace',
  incident_overview: 'nav.incidentOverview',
  warehouse: 'nav.sp',
  sp_material: 'nav.spMaterial',
  sp_details: 'nav.spDetails',
  sp_report: 'nav.spReport',
  com_report: 'nav.comReport',
  warehouse_summary: 'nav.warehouseSummary',
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
    pages: ['alarm', 'ttwo', 'v1_ttwo', 'tt', 'wo', 'nur', 'ms_nur_only', 'ms_sla', 'ms_sla_only', 'cxoDashboard', 'mwUmeTopology', 'mwRealTime', 'alarmManagement', 'fme_ranking', 'site_avail', 'avail_ms', 'avail_flm', 'noc_analyst', 'repeat_site_down', 'cr_analysis', 'pm_analysis', 'bp_report', 'packet_loss', 'battery', 'ume_in_kpi', 'imonitor', 'gis', 'realtime_alarm', 'incident_overview', 'warehouse', 'sp_material', 'sp_details', 'sp_report', 'com_report', 'warehouse_summary'],
  },
  { id: 'analysis', pages: ['eflow_qa', 'eflow_flow', 'dashboard', 'archive', 'ip_trace'] },
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
      desc: '汇总三类任务产物并供下载：邮件发送的最新报告附件、FineBI FTP 报表、eFlow 规则检查结果。eFlow 页签底部列出**从 eFlow 获取的全部规则表**（TT 级别矫正规则 / 告警关联规则 / 推单·配置规则）与本次检查产物（级别矫正表 / 匹配报告）。',
      usage: [
        '顶部页签切换类别，点文件名或「下载」保存；可设每类保留最近 N 份',
        'eFlow 页签三个「立即…」按钮分别手动触发对应任务：立即检查（TT 规则 + 匹配矫正）、收集告警规则、收集推单规则；触发后 3 秒自动刷新一次，任务慢时需手动再刷',
        'eFlow 页签底部表格：蓝色标签为规则表（TT 规则随每日 04:20 检查刷新；告警/推单规则原本每 3 天 23:59 刷新，可用上面的「收集…」按钮随时刷新），灰色为本次检查产物',
      ],
    },
    alarm: {
      desc: '全网当前活跃告警的综合视图：总量、级别、站点等多维统计与趋势。',
      usage: ['点任意数字弹出可搜索的下钻明细表', '「实时」数据来自 eFlow 活动告警（eflow_active_alarm 每 30 分钟同步），并非秒级推送'],
    },
    ttwo: {
      desc: '故障工单（TT）与工作单（WO）的处理量、时效、积压趋势分析。TT 统计的三个维度（工单严重度 / SLA 状态 / 工单状态）都用数字卡片，点卡片下钻；MTTR 趋势按 Ticket Severity（P1/P2/P3/P4）拆成 4 张图，每张图是「柱 = TT 数量 + 线 = MTTR」双轴，并用页签切 日 / 周 / 月 三档粒度。默认时间窗近 30 天。',
      usage: [
        '下拉 + 分段控件 + 日期区间组合筛选，点卡片或图上的点下钻明细；默认时间窗为近 30 天（周/月粒度在 7 天里只剩一两个桶，看不出趋势）',
        '「全部归属」可切 ZTE / 3rd：WO 编号非空 = ZTE（我方派单），为空 = 3rd（第三方处理）',
        '「高级过滤」按钮展开站点维度筛选（区域/省县/网络制式/站点类型/VIP/TRM/主管/FME/供电方式/供电厂商/站点等级），选项来自站点表',
        'TT 统计卡片上的占比，分母是**该维度自身**的合计（看这一个维度内部的构成），不是 TT 总数',
        'MTTR 趋势上方页签切 日/周/月：三档一次加载，切换即时；周上的 TT 数量就是该周 7 个日点的合并，可互相印证',
        '每张 MTTR 图是双轴：柱子是「该时段该级别的 TT 单数」（左轴），折线是「MTTR 分钟均值」（右轴）。某时段该级别没有单时柱和线都不画，不是 0（「没有单」与「MTTR 为 0」是两回事）',
        '柱高与线高不是同一量纲：柱子看「量」，折线看「快慢」。线的样本量少时均值会跳，悬停提示里会补一句「其中 N 单计入 MTTR」说明实际参与计算的有多少单',
        '四张图的悬停提示与缩放（滚轮/底部滑杆）联动，拖任一张另外三张同步；日粒度点数多时会自动出现缩放条',
        '点图上任意点可下钻该时段的工单明细',
        '页头显示数据最近同步时间；数据来自 eFlow 每小时同步（eflow_sync）与每日全量兜底（eflow_sync_full）',
      ],
    },
    v1_ttwo: {
      desc: 'TT&WO 看板的「只保留上半部分」版：渲染到「MTTR 趋势」（含标题、日/周/月页签，每档四张「柱=TT 数量 + 线=MTTR」双轴分级图）为止，即 汇总卡（TT 总数 / WO 总数 / WO 编号唯一）+ TT 统计（工单严重度 / SLA 状态 / 工单状态，均为数字卡片）+ MTTR 趋势（P1/P2/P3/P4 × 日/周/月）；其下的领域与根因分析、工单分析、站点信息三个区块整体不出。默认时间窗近 30 天。',
      usage: [
        '筛选条（含全部归属 ZTE/3rd 与高级过滤）、MTTR 日/周/月页签与双轴图、卡片下钻明细与导出与 TT&WO 看板完全同源（共用 /tt-wo-dashboard/overview 端点），用法一致、数字必然相同',
        '直链 http://<host>/myapp/?page=v1_ttwo；完整版见 page=ttwo',
      ],
    },
    tt: {
      desc: 'TT&WO 看板的「只看 TT」版（数据源 eflow_tt）：汇总卡只留「TT 总数」→ 统计（严重度 / SLA 状态 / 状态，均为数字卡片，点卡下钻）→ MTTR 趋势（P1/P2/P3/P4 × 日/周/月，每张图为「柱=TT 数量 + 线=MTTR」双轴）。MTTR 趋势之下的下半部分整体不出：领域与根因分析、工单分析（按来源统计 WO / 按状态统计 WO）、站点信息；WO 总数 / WO 编号(唯一) 两张汇总卡也不出。默认时间窗近 30 天。',
      usage: [
        '分区标题为「统计」，严重度维度标题为「严重度」（完整版 TT&WO 看板上仍叫「TT 统计」「工单严重度」）',
        'MTTR 趋势每张图是双轴：柱子（中兴蓝 #0072BC）是「该时段该级别的 TT 单数」，折线（橙色）是「MTTR 分钟均值」。四张图的柱/线颜色固定不变 —— 级别由图本身（P1/P2/P3/P4 四张图）区分，颜色只用来分「量」与「时长」这两个量纲。某时段该级别没有单时柱和线都不画，不是 0',
        '筛选条（含全部归属 ZTE/3rd 与高级过滤）、卡片下钻明细、页面级 Excel 导出与 TT&WO 看板完全同源（共用 /tt-wo-dashboard/overview 端点），数字必然相同；导出文件名前缀为 TTWO_tt_',
        '直链 http://<host>/myapp/?page=tt；完整版见 page=ttwo，只看 WO 见 page=wo（版式与本页相同，数据源换成 eflow_wo）',
      ],
    },
    wo: {
      desc: 'TT 看板的「WO 数据源」版：版式与 page=tt 逐块一致，只是数据来自 eflow_wo。汇总卡只留「WO 总数」→ 统计（严重度 / SLA 状态 / 状态）→ MTTR 趋势（P1/P2/P3/P4 × 日/周/月双轴图）。MTTR 趋势之下的下半部分（领域与根因分析、工单分析、站点信息）与 page=tt 一样不出。默认时间窗近 30 天。',
      usage: [
        '点统计卡片或 MTTR 图上的点，弹出可搜索的 WO 明细下钻表',
        'SLA 状态取自关联的 TT（eflow_wo 没有该列，SLA 属 TT 侧概念）：按 wo.tt_no = tt.tt_no 关联，关联不上的计入 Unknown，所以各卡片之和 = WO 总数',
        'MTTR 用的是 WO 自己的 alarm_occur_time / alarm_clear_time，所以本页的 MTTR 是「WO 的周转时效」，与 page=tt 的 TT 时效是两个数',
        '汇总卡只留「WO 总数」一张：本页每行本身就是一个 WO，「WO 编号(唯一)」会与它一模一样；「TT 总数」算的是另一张表的行数，放在本页没有意义',
        'ZTE/3rd 归属下拉在本页不显示：该归属定义在「TT 的 wo_no」上，WO 表本身没有这个概念',
        '筛选条（区域 / 高级过滤）、下钻明细与页面级 Excel 导出与 TT&WO 看板同源，只是数据端点用 /wo-dashboard/overview；导出文件名前缀为 TTWO_wo_',
        '直链 http://<host>/myapp/?page=wo；完整版见 page=ttwo，只看 TT 见 page=tt',
      ],
    },
    eflow_qa: {
      desc: 'eFlow TT 判定规则知识库：规则/案例文档全文检索，并内置 TT 快速分析与 TT 批量核查。',
      usage: [
        '空格分隔多关键词检索，或从左侧目录选择文章',
        '输入 TT 单号一键分析：派单归属、时间差、根因分布与结论要点',
        'AI 分析结论下方附「规则命中证据」（本地规则引擎，与 Email Reports → eFlow TT Rules Check 页签同源）：命中规则名称与 ID、逐条条件匹配详情、规则来源文件 eflow_TT_rules.xlsx（可下载）、规则维护人与工单处理人',
        '模型不可用（本地代理未启动且 Open WebUI 不可达）时不再只报错：页面会给出一份「程序化判定」结论 —— 级别判定、命中规则、规则来源与处置建议全部由本地规则引擎算出',
        '「规则来源与责任人」另给推单规则（TT Push Order Rule，触发步骤 FO Accept）：Rule Name / Rule Type / Rule Trigger Step / Push Order Path / *Auto Operator / Target Handler，说明这单会不会自动推 WO、推给谁、谁自动处理（来源 eflow_push_rules.xlsx，可下载）',
        'TT 批量核查：上传 xlsx/csv/txt 单号清单或直接粘贴，逐单判定工单级别是否正常（正常/需调整/无法判定），可导出 Excel',
        'TT 批量核查支持「下载模板 → 填写 → 上传核查」闭环：点「下载模板」得到带表头的 xlsx，填好单号后把同一个文件传回来即可',
      ],
    },
    eflow_flow: {
      desc: 'eFlow 全流程查询：输入告警（告警 ID / 告警码）或 TT 单号，画出该单在 eFlow 里的全流程图 —— 规则驱动的完整状态机 + 该单实际走过的路径高亮。',
      usage: [
        '输入框支持三种输入：TT 单号（TT202609230060）、告警 ID（告警表的 id/aid）、告警码（如 99933）；按告警码查询会列出该码最近的 TT 供切换',
        '底图是规则驱动的状态机：告警发生 → TT 建单 → 自动派单 → FO/BO 接单 → FO/BO 处理 → 第三方接单/处理 → 确认 → 关单，节点下方的「生效/总数」是该步骤绑定的规则条数',
        '绿色节点 = 该单实际走过的步骤，黄色节点 = 当前所处步骤（来自 operation_type 字段），灰色 = 未涉及；粗青色连线 = 实际路径',
        '点击图中任意节点，下方「规则明细」表即切到该步骤绑定的规则（规则名 / 类型 / 触发步骤 / 状态 / 优先级 / 目标处理人 / 推送路径），再点「显示全部」可看全量规则',
        '「实际流程路径」表按时间列出该单真实走过的里程碑、操作人与说明；「TT 工单信息」表给出级别、当前处理人、SLA、根因等字段',
        'TT 若已派生现场工单，另有「WO 现场子流程」区块：WO 的 接单 → 处理 → 确认 → 关单 独立一条流水线，并列出各环节处理明细（来自 eflow_wo 的 *Detail 字段）',
        '「关联告警」表列出触发该 TT 的告警（realtime_alarm / history_alarm 的 tt_id 或 alarm_id 关联），含告警码、站点、网元、级别与发生时间',
        '判定口径与「NOC 操作人分析」「单 TT 复盘报告」同源：规则统一读 ocrule_details，因此不会出现「流程图说 A、复盘说 B」',
        '规则表由 eflow_push_rules_collect / eflow_alarm_rules_collect 定时采集（每 3 天 23:59），规则更新后流程图自动反映',
      ],
    },
    nur: {
      desc: '网络不可用率（NUR）的日/周/月趋势、多维分析与站点达标情况。',
      usage: ['切换粒度与日期区间，多维下拉筛选', '点数字下钻明细表（支持列内筛选与排序），可一键导出 Excel'],
    },
    ms_nur_only: {
      desc: 'NUR 看板的「只保留 NUR」版：内容与 page=nur 的 NUR 部分完全一致（NUR 日/周/月 的表格 + 趋势），不再渲染 SLA 三档，适合只看 NUR 的值班位或大屏。',
      usage: ['筛选条、下钻明细与导出与 NUR 看板同源，用法一致', '直链 http://<host>/myapp/?page=ms_nur_only；另一半内容见 page=ms_sla_only（SLA 口径，来自 MS Operation KPI 看板）'],
    },
    ms_sla: {
      desc: 'MS 合同 KPI 与工单 SLA 达成情况：NUR / Network KPI / Per-Site / WO SLA（指标为行、期间为列）。',
      usage: ['粒度三档「天 / 周 / 月」；Network KPIs 与 Per-Site KPIs 只有天/月两档（来自快照库），切到周档位时这两块不显示并给出提示', '切换天/周/月会重置时间范围为该档默认窗口（天=当月至今，周=最近 12 周，月=最近 9 个自然月），横幅上会写明当前区间', 'SLA 达成率（TTR / TTR_P1~P4）统一由 WOs SLA 区以「表格 + 趋势」呈现，不再另设 KPI List SLA 卡片', '下钻明细与 NUR 页一致；数字以 nur_calc 实时计算为准（ms_sla_full 每 6 小时驱动），可能与历史快照文件不一致——以本页为准'],
    },
    ms_sla_only: {
      desc: 'MS Operation KPI 看板的「只保留 SLA」版：WOs SLA 区的工单 SLA 达成率（TTR / TTR_P1~P4 的 Total / Within SLA / Achieve + 趋势），不渲染 NUR、Network、Per-Site。',
      usage: ['达成率 ≥95% 显示绿色、低于目标标红，与 page=ms_sla 同一口径', '粒度三档「天 / 周 / 月」：天默认当月至今、周默认最近 12 周、月默认 2026-01 至今；切档会重置时间范围（横幅上有说明）', '单元格与数据点可点击下钻 TT 明细，并可导出 Excel'],
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
      usage: [
        '区域下拉 + 图层 Tag 开关筛选；图例点击可隐藏该类图层；时间支持分段切换与自定义区间',
        '点站点打开右侧抽屉，四个页签明细可搜索、可导出 Excel',
        '「链路利用率」开关（默认开）：把 MW 微波实时页同一 15 分钟槽位的链路利用率叠加到地图链路线上，按 4 级着色（>80% 紧急 / ≥70% 重要 / ≥60% 次要 / <60% 正常），线越粗表示利用率越高',
        '点链路线可看该链路的最高/发送/接收利用率与匹配到的 MW 站点；显示「无 KPI 数据」的链路表示未匹配到实时指标（保持 KML 原线色），不是 0%',
        '叠加口径见图例下方说明：844 条 KML 链路中约 360 条能匹配到实时指标，其余仍在 MW 微波实时页查看',
      ],
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
    imonitor: {
      desc: 'UME iMonitor 大屏（guard-imonitor-iui，screen_id=1）：把 UME 门户（172.17.208.1:28808）的原版监控大屏原样嵌进 myapp，保留其全部图表与交互。页面经 nginx 8088 反代到上游（门户独立端口方案），首次进入会由注入脚本自动完成 em-portal 登录（账号取自 Settings → 凭据的「UME 客户业务 KPI 门户」，即 ume_in），无需手工输入；登录页的 frame-bust 已在反代里中和、iframe 另加 sandbox，保证登录过程不会把 myapp 外壳冲掉。',
      usage: [
        '首次进入约 3~6 秒完成自动登录后出图；会话有效期内再次进入直接秒开',
        '会话过期时大屏 SPA 会自己跳登录页，注入脚本自动重新登录并把 iframe 拉回 screen_id=1，全程无需干预',
        '工具条「重新登录」强制重走一次门户登录（换账号 / 门户把会话顶掉时用）；「刷新」只重载大屏页面',
        '「新窗口打开」在独立标签页里看这块大屏（与页内共用同一份浏览器会话，Cookie 按主机共享、不分端口）',
        '自动刷新（顶栏）到点后由本页在 iframe 内原地重载，不会整页闪白；该页已登记在 AR_SOFT_REFRESH_PAGES',
        '上游把 Content-Security-Policy: frame-ancestors 设为 self，故必须走反代（nginx/portal_ume_in_8088.conf）而不能直连；反代端口 8088 与 nginx 配置、PROXY_PREFIXES 三处需保持一致',
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
    noc_analyst: {
      desc: 'NOC 操作人分析：基于 eflow_tt.last_processer 量化每位 NOC 的根因错位率、平均处理时长、夜班单占比与 SLA 通过率，并给出红旗告警。页面按「能下钻尽下钻」设计——从人一路下钻到 TT，再下钻到告警链路。',
      usage: [
        '口径：按告警发生时间（alarm_occur_time）归属月份，而非最后修改时间；夜班 = Accept 操作时间落在 22:00–06:00',
        '错位率 = 错位单数 / 已填报根因单数；错位判定以 history_alarm.reason_type 为权威，与 NOC 填报的 root_cause 比对（典型为 POWER←TRM，即 NOC 填供电、系统指向传输）',
        '第 1 层下钻：概览数字卡、Top3/Bottom3 卡片、ECharts 柱状图、排名表每一列与红旗告警里的人名，全部可点',
        '第 2 层下钻：弹窗内按「全部 / 根因错位 / 夜班单 / SLA Fail / 慢单（≥12h）」五种切片切换，行数与该 NOC 的对应指标严格一致',
        '第 3 层下钻：切到「异常站点」页签按站点聚合（错位 / SLA Fail / 慢单 / 夜班），点站点名再看该站的全部 TT',
        '第 4 层下钻：点任意 TT 单号打开单 TT 复盘报告——按「时间归因 / 里程碑时间轴 / 应做·实做 / 偏离清单 / 告警链路」五个页签展开，与 EflowQa 页的程序化复盘报告同源同口径',
        '时间归因区「时间都花哪了」：把整月工单逐单解析后聚合，回答时间浪费在哪个环节。含 6 张可点数字卡、各环节占时比例饼图、偏离类型分布、分段表（合计/平均/P90/最长/超阈值单数）、里程碑耗时分布表',
        '「应派未派 WO 明细」：高等级断站（P1/P2、VIP、Hub）却没派现场工单的单子，按总历时降序，点 TT 号直接进该单的复盘报告「偏离清单」页签',
        '鼠标悬浮看名字：告警码（如 99933）悬浮显示官方告警名（SITE DOWN DUE TO POWER OFF）；「派单分类」（如 rule_stopped）悬浮显示成因说明与命中的推单规则名及状态（ACTIVE/STOP），一眼看出"为什么这单没建 WO"',
        '顶部「承接方」三档切换（ZTE 自派 / IPT 第三方 / 全部，默认 ZTE）：排给第三方（IPT）的单本来就不建 WO，若与自派单混在一起看，会把「应派未派 WO」抬高近 4 倍（实测 1140 → 修正后 296）。切换到「IPT 第三方」可单独复盘第三方的履约情况（该档「应派未派 WO」恒为 0，属正常）',
        '现场处置及时性「全月 WO 各跳耗时分布」：把现场工单的生命周期拆成 工单建单→FE 接单→出发→到场→处理完成→关单 各跳，看哪一跳最卡。实测最慢的是「工单建单 → FE 接单」（中位数约 11 小时），而接单之后的动作都只要几分钟',
        '「NOC / 人工动作及时性」：每个该由人完成的动作（FO Accept 接单、FO Process 填报、现场作业）等了多久、是否超过契约时限、超时限占比是多少',
        '单 TT 复盘「时间归因」页签里，分段表带「阶段」列可直接看出该单时间压在哪一类；下方还有该单的「现场处置时间轴（WO 生命周期）」逐跳明细（含操作人）；未派 WO 的单会明确提示"本单无 WO"，不会空白',
        '「阶段归并：时间压在谁手里」：把细分段按阶段合并（建单时延/接单等待/现场响应等待/现场作业/告警清除/提交关单/关单确认），便于比较 NOC、现场、系统各占多久。实测全月现场响应等待占 15.2%（中位数 6.4 小时）',
        '时间归因首次计算要逐单复盘全月工单（实测约 150 秒），结果按月份落盘缓存，之后打开是毫秒级；需要强制重算时点右上角「重新计算」',
        '弹窗内每个表格都可全字段搜索、列筛选与排序，并可导出 Excel（导出的是当前切片、当前搜索结果）',
      ],
    },
    fme_ranking: {
      desc: 'FME 排名看板：按 FME 统计站点可用率、工单量与 SLA 达成率，并排名。',
      usage: [
        'Top3 / Bottom3 卡片与排名表可点击下钻该 FME 的站点级可用率与 WO 明细',
        '两张条形图分别看可用率「Top5」与「尾部 5 个」：横向条形按名次自上而下排列，条端直接标出可用率数值；柱子用组内真实值域（而非固定 0~100），否则同一组都在 99% 以上时柱子会一样长、看不出差异',
        '条形图里的 WO 数量（蓝线）与 SLA 达成率（橙虚线）只在**该组内确实存在差异**时才出现；若全组数值相同则不画，避免一条贴地直线占满图例被误读成趋势',
        '点条形图的任一条可下钻到该 FME 的站点明细；下钻弹窗内还可切换到 WO 维度',
      ],
    },
    site_avail: {
      desc: '站点可用率看板：站点级可用率排名与达标情况。',
      usage: ['点站点名下钻该站的可用率明细', '可用率按站点统计口径计算，与 FME 排名页同源'],
    },
    avail_ms: {
      desc: 'MS Availability（可用率多维矩阵）：把全网可用率按「区域 / 制式 / 站点类型」三个维度呈现，日 / 周 / 月用页签切换粒度。数据来自本机派生库 avail_recon.sqlite3（任务 avail_recon_sync 每天 06:10 重建，口径为站点级加权可用率 SUM(分子)/SUM(分母)）。',
      usage: [
        '每张矩阵上方有该维度的趋势曲线（日 30 期 / 周 12 期 / 月 12 期，随页签变化）：一条线一个维度取值，所有点都按 SUM(分子)/SUM(分母) 加权，与表格数字严格一致',
        '曲线上的点也能点开下钻，打开的是**那个点自己的周期**（例如月档停在 2026-09 时点 2026-08 的点，弹窗就是 2026-08 的明细）',
        '区域那张曲线不含「未匹配主数据」（量级太低会把纵轴压扁），图下有一行说明，它的数据在表格末行',
        '点任意可用率数字下钻：弹窗内含近 30 期趋势、按日明细与「按调度组」的构成分解，第二个页签可看该组合相关的 TT 工单',
        '阈值输入框（默认 99.65%）决定「未达标」判定：低于阈值显示为红色，会实时重算，不改变数字本身',
        '区域维度的 ALL 行含「未匹配主数据」的站点，因此 ALL 不等于三个区域相加；末行单列该桶，点它只能看可用率明细、不能下钻 TT（派生库里没有那批站点的名单）',
        '4G 的 NERA 属未映射调度组：计入制式 4G 总量，在站点类型维度单列「其它」，只出现在 2025-12 ~ 2026-01 的月份；此时页面会出现黄色口径提示条',
        '取不到数据显示「—」而不是 0；页面顶部显示「数据截至」，派生库停更时能一眼看出来',
      ],
    },
    avail_flm: {
      desc: 'FLM 可用率：只看三个 FLM 区域（Montserrado / North East / South West）的可用率，行是区域、列分别是制式（2G/3G/4G）与站点类型（Regular / Cooli / ERA，列名用数据原值，需求表写作 Cool.i）；日 / 周 / 月用页签切换粒度。数据与「可用率多维矩阵」同源（本机派生库 avail_recon.sqlite3，口径 SUM(分子)/SUM(分母)），另外把「影响可用率的 TT 列表」直接列在页面上。',
      usage: [
        '两张表上方各有一条曲线：上面那条是三个区域的可用率走势（一个区域一条线），下面那条是三种站点类型的走势；日 30 期 / 周 12 期 / 月 12 期，随页签变化',
        '曲线上的点也能点开下钻，打开的是**那个点自己的周期**；阈值虚线（默认 99.65%）与表格的红色判定同一个值',
        '点任意可用率数字下钻：弹窗内含近 30 期趋势、按日明细与「按调度组」的构成分解，第二个页签是该切片的全部 TT 工单',
        '三个区域各有一张 KPI 卡（该区域全部制式合计），点卡片同样能下钻',
        '站点类型不做范围限制：三个区域都会显示 Regular / Cooli / ERA 三列（列名用数据原值）。需求里写的「NE 只有 Regular/Cool.i」与两个数据源都不符（NE 有 123 个 ERA 站点、派生库里 NE 的 ERA 分母 6.5 万），硬留空反而会让人以为 NE 没有 ERA 站点',
        '末行「未匹配主数据」是远端站点名匹配失败的部分：它不在三个区域之内，也不画进曲线（量级大会压扁纵轴），单列出来只为对账，点它只能看可用率明细、不能下钻 TT',
        '页面级「影响可用率的 TT 列表」列出**本期全部工单**，不做「是否影响业务」的判定（判定字段与 site_outage 在本期数据上完全一致，取其一都会让口径看起来比实际精确）；每行给出 2G/3G/4G 断站数与 MTTR，由使用者自己判断相关性',
        'TT 列表可按区域筛选（全部 / 三个区域）；月档工单数可达 3600+ 条，超过展示上限时页面会显示黄色提示，只有明细条数受影响、可用率数字不受影响',
        '点工单号可反查该工单所属「区域 × 站点类型」的可用率与同期全部工单',
        '4G 的 NERA 属未映射调度组：计入制式 4G 总量，但本页站点类型列只有三种，此时 4G 行会大于三列相加，页面会出现黄色口径提示条',
        '取不到数据显示「—」而不是 0；页面顶部显示「数据截至」，派生库停更时能一眼看出来',
      ],
    },
    repeat_site_down: {
      desc: '重复宕站看板：识别在统计窗口内反复宕站的站点，用于定位「修不好的站」。',
      usage: ['按日粒度统计站点宕站次数，点数字下钻该日宕站明细', '数据来自 eflow_tt 与 eflow_site，与告警看板口径互补'],
    },
    cr_analysis: {
      desc: 'CR 变更分析：按变更类别（change_category）看变更计划的排期与执行情况，回答「计划了多少、执行了多少、其中多少按时」。',
      usage: [
        '数据来自 eflow_cr（eFlow 同步），默认区间取全表实际时间范围',
        '四个核心计数：「已排期」= 有计划开始时间；「已执行」= 有实际开始时间；「未执行」= 排了期但没动；「按时/延期」= 实际开始早于 / 晚于计划开始',
        '两个核心比率的分母写在数字下方：计划达成率 = 已执行 ÷ 已排期，按时执行率 = 按时 ÷ 已执行。分母为 0 时显示「—」而不是 0',
        '页面上每个数字都可点：类别表格、图表柱子、月度趋势、子类别表格都能下钻到明细，明细行数与卡片数字严格一致',
        '下钻明细被截断时会显示黄色告警条，提示缩小时间范围——不要忽略它',
      ],
    },
    pm_analysis: {
      desc: 'PM 执行分析：按 PM 计划号（pmp_no）看预防性维护工单（PMT）的完成与超期情况，回答「计划执行到哪一步、多少超期、卡在谁那里」。',
      usage: [
        '数据来自 eflow_pm（eFlow 同步），默认区间取全表实际时间范围',
        '四个核心计数：「已完成」= 状态为 Closed；「未完成」= 尚未 Closed；「已超期」= 源表 pmt_overdue 为 Yes（直接用上游判定，不自己按日期算）；「未开始」= 已完成条目数为 0',
        '两个细分口径：「完成但超期」= 事后补录/迟交；「未完成且超期」= 真正压着没做完的，优先看这个',
        '三个比率的分母写在数字下方：工单关闭率 = 已完成 ÷ 工单总量，超期率 = 已超期 ÷ 工单总量（越低越好），已启动率 = 条目完成数 > 0 的占比。分母为 0 时显示「—」而不是 0',
        '「流程推进情况」按真实时序排列：创建 → 排期 → 受理 → PM 经理审批 → 执行 → FLM 领导审批。注意源表字段名有误导性——last_accept_time 实际早于 last_process_time，不要按字段名猜顺序',
        '页面上每个数字都可点：KPI 卡、比率卡、图表柱子、月度趋势、站点条形图、计划表格都能下钻到明细，明细行数与卡片数字严格一致',
        '下钻明细被截断时会显示黄色告警条，提示缩小时间范围——不要忽略它',
      ],
    },
    bp_report: {
      desc: 'BP 劣化小区报告：umlaut 口径的 Bad Performance 小区统计，支持按日/周/月查看并下钻到小区明细。',
      usage: [
        '口径：日 = 平均活跃用户数 > 2.5 且 DL 吞吐 < 3 Mbps 且 DL PRB 利用率 > 80%；周 = 4/7 天为 BP；月 = 3/4 个完整周为 BP',
        '⚠️ 口径不完整（页面顶部常驻黄色告警）：RAN_UME 侧没有采集「平均活跃用户数」，重算只覆盖 PRB 与吞吐两个条件，缺第三个条件的小区记为「不可判定」，不计入 BP',
        '因此本页从 RAN_UME 重算出的 BP 数会低于 Excel 原值，这是口径缺口、不是实现缺陷；但 Excel 已有的历史数据是完整的，两者并存',
        '「BP 小区数」列可点击下钻到小区明细，行数与数字严格一致；「全网小区数」列不可下钻（Excel 未提供全网小区名单）',
        '「明细行数」列显示 Excel BP Cells List 里该期实际有多少行，括号内是与展示值的差额——上游 Excel 各 sheet 本身就不一致，差异如实展示',
        '2023 年与 2024 年部分日期在 Excel 的 BP Cells List 里没有明细，这些期的下钻入口会置灰',
        '分区（Cluster1~6 / Rural / ERA）只能在 Excel 里维护，RAN_UME 没有这套维度；新增小区若不在字典内会归为 Unknown',
        '数据由 bp_report_sync 任务每天 06:20 从 RAN_UME 增量更新',
      ],
    },
    warehouse: {
      desc: '备件/耗材库存看板（Spare Management），与原工具看板完全一致。',
      usage: ['数据来自 sp_data_sync（每天 07:00 从 SFTP 拉取的 5 份备件报表）', '按仓库/备件类型查看库存与明细'],
    },
    // ---- SP 备件 / 耗材报表家族（2026-09-29 一次性补齐，此前四个页面都漏登记） ----
    sp_material: {
      desc: '备件物料统计汇总：按专业域/物料看入库、出库与库存的汇总分布。',
      usage: ['数据来自 sp_data_sync 拉取的备件报表', '点任意汇总数字可下钻到对应物料明细'],
    },
    sp_details: {
      desc: 'SP 备件明细报表：与邮件任务发出的合并工作簿是同一份文件，含 Inventory / Inbound / Outbound / Transfer 四张表。',
      usage: ['分页 + 筛选 + 排序；「未关闭」= Status 不含 Closed 的行', '表格只展示常用列，点任意一行查看该表全部列', '导出为当前筛选结果（最多 5000 行）'],
    },
    sp_report: {
      desc: '备件 Inbound & Outbound & Inventory 汇总报表：与邮件/WhatsApp 发出去的是同一份工作簿（每天 05:15 由 sp_report_generate 产出），含 Summary-Current / Summary-Changed / Inbound / Outbound / Inventory 五张表。',
      usage: ['统计卡片看总量与补库告警，点告警卡即筛选', 'Summary-Changed 渲染成「天 × 仓库」矩阵', '「显示列」可按分表自定义并本地记住；行详情弹窗始终显示全列'],
    },
    com_report: {
      desc: '耗材 Inbound & Outbound & Inventory 汇总报表：与备件页版式一致，只是数据源换成耗材工作簿。',
      usage: ['口径与备件页完全相同，见页面底部「报表口径说明」', '页面与 Excel 数字不一致时先看口径说明，不要在页面层改口径'],
    },
    warehouse_summary: {
      desc: '仓库汇总报表：按仓库汇总报表（WarehouseSummaryReport.xlsx）复刻，页签对应该文件的两个 sheet——Spars Parts / Consumables。每个页签含两段：WH/DOP 库存与消耗汇总（当前库存 / 累计 / 本月 / 本周消耗），以及高频消耗物料（每页 10 行，可翻完全部物料）。',
      usage: ['页签切换备件/耗材；两段表的每个数字都可点击下钻到明细', '高频物料按消耗量降序分页显示全部，Total 行是全量合计且不随翻页变化', '消耗口径是 Outbound Site Qty（站点出库），段②标题右侧有标签提示'],
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
      desc: 'Collects three kinds of task artifacts for download: latest email report attachments, FineBI FTP reports, and eFlow rule check results. The bottom of the eFlow tab lists **every rule sheet collected from eFlow** (TT severity rules / alarm correlation rules / push & config rules) plus this run\'s outputs (severity correction sheet / matching report).',
      usage: [
        'Switch categories via tabs; click a file name or "Download" to save; set how many recent files to keep per category',
        'The three "Run Now / Collect" buttons on the eFlow tab trigger the matching task manually: TT check + severity correction, alarm rule collection, push rule collection; each auto-refreshes once after 3s (refresh manually if the task is slow)',
        'Table at the bottom of the eFlow tab: blue tag = rule sheet (TT rules refresh with the daily 04:20 check; alarm/push rules normally refresh every 3 days at 23:59 — use the "Collect" buttons to refresh them on demand), grey = this run\'s outputs',
      ],
    },
    alarm: {
      desc: 'Combined view of all current active network alarms: totals, severity, site-level multi-dimension statistics and trends.',
      usage: ['Click any number to open a searchable drill-down table', '"Realtime" data comes from eFlow active alarms (eflow_active_alarm every 30 min) — not second-level push'],
    },
    ttwo: {
      desc: 'Processing volume, timeliness and backlog trends of trouble tickets (TT) and work orders (WO). All three TT statistics dimensions (ticket severity / SLA status / ticket status) are number cards you can click to drill down; the MTTR trend is split into 4 charts by ticket severity (P1/P2/P3/P4), each a dual-axis chart with bars = TT count and line = MTTR, with tabs switching day / week / month granularity. The default window is the last 30 days.',
      usage: [
        'Filter with selects + segmented control + date range; click a card or a chart point to drill down. The default window is the last 30 days (over a 7-day window the weekly/monthly views have only one or two buckets, which shows no trend)',
        '"All owners" switches ZTE / 3rd: a non-empty WO number means ZTE (dispatched by us), empty means 3rd (handled by a third party)',
        'The "Advanced filters" button reveals site-level filters (region / province-county / network type / site type / VIP / TRM / supervisor / FME / power source / power vendor / site category), fed from the site table',
        'The percentage on a TT statistics card uses that dimension\'s own total as denominator (its internal composition), not the overall TT total',
        'The tabs above the MTTR trend switch day/week/month: all three load at once, so switching is instant; the weekly TT count is exactly the merge of that week\'s seven daily points, so the two views cross-check each other',
        'Each MTTR chart has two axes: bars are the TT count of that severity in the period (left axis), the line is the mean MTTR in minutes (right axis). A period with no ticket of that severity draws neither — it is not 0 ("no ticket" and "MTTR is 0" are different things)',
        'Bar height and line height are different units: bars show volume, the line shows speed. A line based on few tickets jumps around, so the hover tooltip adds "(N in MTTR avg)" to say how many tickets actually went into the average',
        'The four charts share hover tooltips and zoom (wheel / bottom slider) — dragging one moves the other three; the zoom bar appears automatically for the daily view, which has many points',
        'Click any point on a chart to drill into that period\'s tickets',
        'The header shows the latest sync time; data comes from hourly eflow_sync plus the nightly eflow_sync_full backfill',
      ],
    },
    v1_ttwo: {
      desc: 'The "upper half only" cut of the TT&WO Dashboard: renders up to the MTTR Trend (title, day/week/month tabs and four dual-axis "bars = TT count, line = MTTR" per-severity charts per tab included) — summary cards (TT Total / WO Total / WO No. Unique) + TT statistics (ticket severity / SLA status / ticket status, all number cards) + MTTR trend (P1/P2/P3/P4 × day/week/month); the three blocks below it (Domain & Root Cause, Work Order Analytics, Site Information) are omitted. The default window is the last 30 days.',
      usage: [
        'Filters (including the ZTE/3rd owner switch and advanced filters), the MTTR day/week/month tabs and dual-axis charts, card drill-down and Excel export are shared with the TT&WO Dashboard (same /tt-wo-dashboard/overview endpoint), so usage is identical and the numbers necessarily match',
        'Direct link http://<host>/myapp/?page=v1_ttwo; the full version is page=ttwo',
      ],
    },
    tt: {
      desc: 'The "TT only" cut of the TT&WO Dashboard (source table eflow_tt): summary card (TT Total only) → Statistics (severity / SLA status / status, all number cards that drill down on click) → MTTR trend (P1/P2/P3/P4 × day/week/month, each a dual-axis "bars = TT count, line = MTTR" chart). Everything below the MTTR trend is omitted: Domain & Root Cause, Work Order Analytics (WO by source / WO by status) and Site Information; the WO Total / WO No. (Unique) cards are gone too. The default window is the last 30 days.',
      usage: [
        'The section title reads "Statistics" and the severity dimension "Severity" (the full TT&WO Dashboard still uses "TT Statistics" and "Ticket Severity")',
        'Each MTTR chart is dual-axis: bars (ZTE blue #0072BC) are the TT count of that severity in the period, the line (orange) is the mean MTTR in minutes. The bar/line colours are fixed across all four charts — the severity is identified by the chart itself (four separate P1/P2/P3/P4 charts), while the colours only distinguish the two measures (volume vs duration). A period with no ticket of that severity draws neither a bar nor a point — it is not 0',
        'Filters (including the ZTE/3rd owner switch and advanced filters), card drill-down and the page-level Excel export are shared with the TT&WO Dashboard (same /tt-wo-dashboard/overview endpoint), so the numbers necessarily match; the export filename is prefixed TTWO_tt_',
        'Direct link http://<host>/myapp/?page=tt; the full version is page=ttwo, WO only is page=wo (same layout, sourced from eflow_wo)',
      ],
    },
    wo: {
      desc: 'The eflow_wo-sourced twin of the TT Dashboard: the layout matches page=tt block for block, only the data comes from eflow_wo. Summary card (WO Total only) → Statistics (severity / SLA status / status) → MTTR trend (P1/P2/P3/P4 × day/week/month dual-axis charts). Everything below the MTTR trend (Domain & Root Cause, Work Order Analytics, Site Information) is omitted, exactly as on page=tt. The default window is the last 30 days.',
      usage: [
        'Click a statistics card or a point on an MTTR chart to open a searchable WO drill-down table',
        'SLA status comes from the linked TT (eflow_wo has no such column — SLA is a TT-side concept): joined on wo.tt_no = tt.tt_no, and unmatched rows count as Unknown, so the cards still sum to the WO total',
        'MTTR uses the WO\'s own alarm_occur_time / alarm_clear_time, so this page shows the WO turnaround time — a different number from the TT figure on page=tt',
        'Only the "WO Total" summary card remains: every row on this page is itself a WO, so "WO No. (Unique)" would print the same number twice, and "TT Total" counts rows of a different table and is meaningless here',
        'The ZTE/3rd owner switch is hidden on this page: that ownership is defined on the TT\'s wo_no, a concept the WO table does not have',
        'Filters (region / advanced filters), drill-down and the page-level Excel export are shared with the TT&WO Dashboard, but the data endpoint is /wo-dashboard/overview; the export filename is prefixed TTWO_wo_',
        'Direct link http://<host>/myapp/?page=wo; the full version is page=ttwo, TT only is page=tt',
      ],
    },
    eflow_qa: {
      desc: 'eFlow TT rule knowledge base: full-text search over rule/case documents, with built-in TT quick analysis.',
      usage: [
        'Search with space-separated keywords or pick an article from the catalog on the left',
        'Enter a TT number for one-click analysis: assignment, time gap, root-cause distribution and key conclusions',
        'Below the AI conclusion a "Rule match evidence" block (local rule engine, same source as Email Reports → eFlow TT Rules Check) lists the matched rule name/ID, per-condition match details, the rule source file eflow_TT_rules.xlsx (downloadable), the rule owner and the ticket handler',
        'When no model is reachable (local proxy down and Open WebUI unreachable) the page no longer just shows an error: it renders a "programmatic verdict" — severity verdict, matched rule, rule source and recommended actions all computed by the local rule engine',
        'Rule source & owners also lists the push order rule (TT Push Order Rule, triggerStep=FO Accept): Rule Name / Rule Type / Rule Trigger Step / Push Order Path / *Auto Operator / Target Handler — i.e. whether the TT is auto-pushed to a WO, to whom, and which operator acts automatically (source: eflow_push_rules.xlsx, downloadable)',
        'TT batch check: upload an xlsx/csv/txt list of TT numbers or paste them to judge each ticket severity (OK / needs adjustment / undetermined) and export to Excel',
        'The batch check supports a "download template → fill in → upload" loop: download the templated xlsx, fill in the numbers and upload the same file back',
      ],
    },
    eflow_flow: {
      desc: 'eFlow process flow: enter an alarm (alarm ID / alarm code) or a TT number to draw the ticket\'s full eFlow process — the rule-driven state machine plus the path actually traversed, highlighted.',
      usage: [
        'Three input types: TT number (TT202609230060), alarm ID (the alarm table id/aid), or alarm code (e.g. 99933); querying by alarm code lists the most recent TTs carrying it so you can switch',
        'The base diagram is the rule-driven state machine: Alarm Raised → TT Created → Auto Dispatch → FO/BO Accept → FO/BO Process → 3rd Party Accept/Process → Confirm → Closed; the active/total count under each node is how many rules bind to that step',
        'Green node = a step the ticket actually traversed, amber node = the current step (taken from the operation_type field), grey = not involved; thick cyan edges = the actual path',
        'Click any node to switch the "Rule details" table below to the rules bound to that step (rule name / type / trigger step / status / priority / target handler / push path); "Show all" reveals every rule',
        'The "Actual path" table lists the milestones the ticket really went through, with operator and note; "TT ticket information" gives severity, current handler, SLA and root cause',
        'If the TT spawned a field work order, a "WO field sub-process" block shows the WO\'s own Accept → Process → Confirm → Closed pipeline plus per-step handling detail (from the eflow_wo *Detail columns)',
        'The "Related alarms" table lists the alarms that raised this TT (linked via realtime_alarm / history_alarm tt_id or alarm_id), with alarm code, site, network element, severity and raised time',
        'Verdicts share one source with "NOC analyst" and the single-TT postmortem report: rules are all read from ocrule_details, so the flow diagram and the postmortem can never disagree',
        'The rule tables are collected by the eflow_push_rules_collect / eflow_alarm_rules_collect jobs (every 3 days at 23:59); the diagram reflects rule updates automatically',
      ],
    },
    nur: {
      desc: 'Network Unavailability Rate (NUR) daily/weekly/monthly trends, multi-dimension analysis and site compliance.',
      usage: ['Switch granularity and date range, filter by dimensions', 'Click numbers to drill into a detail table (in-column filters & sorting); export to Excel'],
    },
    ms_nur_only: {
      desc: 'The "NUR only" cut of the NUR Dashboard: identical to the NUR half of page=nur (NUR daily/weekly/monthly tables + trends), with the three SLA blocks removed — handy for a NUR-only desk or wall screen.',
      usage: ['Filters, drill-down and Excel export are shared with the NUR Dashboard, so usage is identical', 'Direct link http://<host>/myapp/?page=ms_nur_only; the other half is page=ms_sla_only (SLA scope, from the MS Operation KPI Dashboard)'],
    },
    ms_sla: {
      desc: 'MS contract KPIs and WO SLA attainment: NUR / Network KPI / Per-Site / WO SLA (metrics as rows, periods as columns).',
      usage: ['Three granularity tabs: day / week / month; Network KPIs and Per-Site KPIs only exist at day/month (they come from the snapshot DB), so they are hidden at week granularity with an explanatory banner', 'Switching day/week/month resets the time range to that tab default (day = current month to date, week = last 12 weeks, month = last 9 calendar months); the banner states the active range', 'SLA attainment (TTR / TTR_P1~P4) is presented once, by the WOs SLA block as table + trend; there is no separate KPI List SLA card', 'Drill-down reuses the NUR detail table; numbers come from the live nur_calc calculation (driven by ms_sla_full every 6h) and may differ from historical snapshot files — trust this page'],
    },
    ms_sla_only: {
      desc: 'The "SLA only" cut of the MS Operation KPI Dashboard: the WOs SLA block with WO SLA attainment (TTR / TTR_P1~P4 Total / Within SLA / Achieve + trend), without NUR, Network or Per-Site.',
      usage: ['Attainment ≥95% is green, below target is red — same scope as page=ms_sla', 'Three granularity tabs: day (default = current month to date), week (default = last 12 weeks) and month (default = January 2026 to date); switching a tab resets the time range (explained by the banner)', 'Click cells and data points to drill into TT details and export to Excel'],
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
      usage: [
        'Region dropdown + layer tags to filter; click a legend item to hide that layer; time supports segments and custom range',
        'Click a site to open the right drawer: four tabs, searchable, exportable to Excel',
        'The "Link Utilization" switch (on by default) overlays MW microwave link utilization from the same 15-min slot as the MW Realtime page, colored on a 4-level scale (>80% critical / ≥70% major / ≥60% minor / <60% healthy); thicker lines mean higher utilization',
        'Click a link to see its max/Tx/Rx utilization and the matched MW sites; a link showing "No KPI data" means it could not be matched to realtime metrics (it keeps its original KML color) — that is not 0%',
        'The overlay scope is explained below the legend: about 360 of the 844 KML links match realtime metrics; the rest are still viewable on the MW Realtime page',
      ],
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
    imonitor: {
      desc: 'UME iMonitor screen (guard-imonitor-iui, screen_id=1): embeds the original UME monitoring screen from the UME portal (172.17.208.1:28808) inside myapp, keeping all of its charts and interactions. The page is reverse-proxied to the upstream through nginx port 8088 (the portal dedicated-port scheme); on first visit an injected script signs in to em-portal automatically using the credentials from Settings → Credentials ("UME Customer Service KPI Portal", key ume_in). The login page frame-bust is neutralised in the proxy and the iframe additionally carries a sandbox, so the sign-in flow can never replace the myapp shell.',
      usage: [
        'The first visit takes about 3-6 s to sign in automatically, then the screen renders; later visits inside the same session open instantly',
        'When the session expires the screen SPA redirects itself to the login page, the injected script signs in again and the iframe is pulled back to screen_id=1 — no user action needed',
        'Toolbar "Re-login" forces a fresh portal login (use when the account changes or the portal drops the session); "Refresh" just reloads the screen page',
        'Open in new tab shows this screen in its own browser tab (it shares the same browser session — cookies are scoped per host, not per port)',
        'Auto Refresh (header) reloads the screen in place via the iframe instead of remounting the page, so there is no white flash; the page is listed in AR_SOFT_REFRESH_PAGES',
        'The upstream sets Content-Security-Policy: frame-ancestors self, so the page must go through the proxy (nginx/portal_ume_in_8088.conf) and cannot be embedded directly; port 8088 must stay in sync across the nginx config and PROXY_PREFIXES',
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
    noc_analyst: {
      desc: 'NOC operator analysis: quantifies each NOC operator\'s root-cause mismatch rate, average handling time, night-ticket share and SLA pass rate from eflow_tt.last_processer, and raises red flags. Built around "drill down wherever possible" — from the person to the ticket, then to the alarm chain.',
      usage: [
        'Scope: tickets are attributed to a month by alarm occurrence time (alarm_occur_time), not last-modified time; night = Accept operation time between 22:00 and 06:00',
        'Mismatch rate = mismatched tickets / tickets with a filed root cause. history_alarm.reason_type is authoritative and is compared against the NOC-filed root_cause (typically POWER←TRM: NOC filed power, the system says transmission)',
        'Layer 1: summary stat cards, Top3/Bottom3 cards, the ECharts bar chart, every column in the ranking table, and each operator named in the red-flag banner are all clickable',
        'Layer 2: the modal switches between five slices — All / Root-cause mismatch / Night / SLA failed / Slow (≥12h); row counts match that operator\'s metric exactly',
        'Layer 3: the "Abnormal sites" tab aggregates by site (mismatch / SLA fail / slow / night); click a site name to see all of its TTs',
        'Layer 4: click any TT number for the single-ticket postmortem — five tabs: time attribution / milestone timeline / should-do vs did / deviations / alarm chain, sharing the same source and definitions as the programmatic postmortem report on the EflowQa page',
        'Time attribution section ("where the time went"): every ticket of the month is parsed and aggregated to show where time is wasted. Six clickable stat cards, a stage-share pie chart, a deviation-type distribution, a segment table (total/average/P90/longest/over-threshold counts) and a milestone duration table',
        '"WO expected but not dispatched": high-severity site-down (P1/P2, VIP, Hub) tickets with no field work order, longest first. Click a TT number to open that ticket\'s postmortem on the "Deviations" tab',
        'Hover to see names: hover an alarm code (e.g. 99933) to see its official name (SITE DOWN DUE TO POWER OFF); hover a "Dispatch category" tag (e.g. rule_stopped) to see the reason plus the matched dispatch rule names and their status (ACTIVE/STOP), so it is obvious why no WO was raised',
        'Top-of-page "Handled by" switch (ZTE in-house / IPT 3rd party / All, defaults to ZTE): tickets routed to a third party (IPT) never get a WO by design, so mixing them with in-house tickets inflates "WO expected but not dispatched" by nearly 4x (1140 before the fix, 296 after). Switch to "IPT (3rd party)" to review third-party fulfilment on its own — that bucket legitimately shows 0 for "WO expected but not dispatched"',
        'Field-response timeliness — "Monthly WO hop durations": the work-order lifecycle split into created → FE accepted → start trip → arrive → work done → closed, so you can see which hop is stuck. In practice the slowest is "WO created → FE accepted" (median about 11 hours), while everything after acceptance takes only minutes',
        '"NOC / human action timeliness": how long each human-performed action (FO Accept, FO Process, field work) waited, whether it breached its contract deadline, and the over-deadline share',
        'In the single-ticket postmortem, the "Time attribution" tab\'s segment table carries a Phase column showing at a glance which kind of time dominates; below it sits the ticket\'s own "Field response timeline (WO lifecycle)" hop-by-hop detail with operators. Tickets with no WO say so explicitly instead of showing a blank area',
        '"Phases: who is holding the time": event-driven segments merged by phase (creation delay / accept wait / field response wait / field work / alarm cleared / submit close / confirm close), so NOC, field and system shares are comparable. In practice field response wait is 15.2% of the month with a 6.4-hour median',
        'The first computation parses every ticket of the month (about 150 s in practice); results are cached per month on disk, so later opens are millisecond-fast. Click "Recompute" at the top right to force a refresh',
        'Every table in the modal supports full-field search, column filters and sorting, and exports the current slice and search result to Excel',
      ],
    },
    fme_ranking: {
      desc: 'FME ranking board: site availability, work-order volume and SLA achievement per FME, ranked.',
      usage: [
        'Top3 / Bottom3 cards and the ranking table drill into that FME\'s site-level availability and WO details',
        'Two bar charts show availability for the "Top 5" and the "Bottom 5": horizontal bars are ordered by rank from top to bottom and print the availability value at the end of each bar. Each chart scales to its own real value range instead of a fixed 0–100, otherwise bars would all look the same length when the whole group sits above 99%',
        'The WO count (blue line) and SLA achievement (orange dashed line) appear only when values actually differ inside that group; when the whole group is identical the series is omitted rather than drawn as a flat line that reads like a trend',
        'Click any bar to drill into that FME\'s site details; the drill-down modal can also switch to the WO dimension',
      ],
    },
    site_avail: {
      desc: 'Site availability board: per-site availability ranking and target compliance.',
      usage: ['Click a site name to drill into its availability details', 'Availability uses the same per-site calculation as the FME ranking page'],
    },
    avail_ms: {
      desc: 'MS Availability (availability matrix): network availability presented across three dimensions — region / technology / site type — with day, week and month granularity on tabs. Data comes from the local derived database avail_recon.sqlite3 (rebuilt daily at 06:10 by the avail_recon_sync task; the measure is site-weighted availability, SUM(numerator)/SUM(denominator)).',
      usage: [
        'Each matrix has a trend chart above it (30 periods for day, 12 for week, 12 for month, following the active tab): one line per dimension value, every point weighted as SUM(numerator)/SUM(denominator) and therefore identical to the table figures',
        'Chart points are clickable too, and they open **that point\'s own period** (e.g. when the month tab sits on 2026-09, clicking the 2026-08 point opens 2026-08 detail)',
        'The region chart omits the "unmatched master data" line (its magnitude would flatten the y-axis); a note under the chart points to the last table row, where it is shown',
        'Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists the related TT tickets for that combination',
        'The threshold input (default 99.65%) drives the "below target" flag: values under it turn red and re-evaluate instantly — the figures themselves do not change',
        'The ALL row under Region includes sites not matched to master data, so ALL is not the sum of the three regions; that bucket gets its own last row — it can show availability detail but not TT tickets (the derived DB holds no site list for it)',
        '4G NERA is an unmapped dispatch group: counted in the 4G technology total, shown separately as "Other" under site type, and only present in the 2025-12 ~ 2026-01 months; a yellow note appears on the page then',
        'Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious',
      ],
    },
    avail_flm: {
      desc: 'FLM availability: covers only the three FLM regions (Montserrado / North East / South West), with regions as rows and technology (2G/3G/4G) and site type (Regular / Cooli / ERA; the column keeps the raw data value, the requirement writes Cool.i) as columns; day / week / month granularity on tabs. The data is the same source as the Availability Matrix (local derived database avail_recon.sqlite3, measure SUM(numerator)/SUM(denominator)), and the "TTs affecting availability" list is shown right on the page.',
      usage: [
        'Each table has a trend chart above it: the upper one tracks the three regions (one line per region), the lower one the three site types; 30 periods for day, 12 for week, 12 for month, following the active tab',
        'Chart points are clickable and open **that point\'s own period**; the dashed threshold line (default 99.65%) is the same value that turns table figures red',
        'Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists every TT ticket of that slice',
        'Each region also has a KPI card (all technologies combined) that can be clicked to drill down',
        'Site type is not scope-restricted: all three regions show the three columns Regular / Cooli / ERA (raw data value). The "NE has only Regular/Cool.i" note in the requirement contradicts both data sources (NE has 123 ERA sites and an ERA denominator of 65k in the derived database), and leaving cells blank would wrongly suggest NE has no ERA sites',
        'The last row "unmatched master data" is the part whose remote site names failed to match: it is outside the three regions and is not plotted (its magnitude would flatten the y-axis); it is listed for reconciliation only and can show availability detail but not TT tickets',
        'The page-level "TTs affecting availability" list shows **every TT of the period** with no "impacted service" judgement (that field and site_outage agree on every row of this period, so using either would make the definition look more precise than it is); each row carries the 2G/3G/4G down-site counts and MTTR so you can judge relevance yourself',
        'The TT list can be filtered by region (all / the three regions); a month can hold 3600+ tickets, and a yellow note appears when the display limit is hit — only the detail row count is affected, never the availability figures',
        'Click a ticket number to look up the availability of its region × site type together with all tickets of that slice',
        '4G NERA is an unmapped dispatch group: counted in the 4G technology total, but this page lists only the three site types, so the 4G row will exceed the sum of the three columns and a yellow note appears',
        'Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious',
      ],
    },
    repeat_site_down: {
      desc: 'Repeat site-down board: identifies sites that go down repeatedly within the window — for finding "sites that never get fixed".',
      usage: ['Counts site-downs per day; click a number to drill into that day\'s down sites', 'Data comes from eflow_tt and eflow_site, complementing the alarm board'],
    },
    cr_analysis: {
      desc: 'CR Change Analysis: shows change-plan scheduling and execution by change category, answering "how many were planned, how many executed, and how many of those were on time".',
      usage: [
        'Data comes from eflow_cr (synced from eFlow); the default range covers the full data span',
        'Four core counts: "Planned" = has a planned start time; "Executed" = has an actual start time; "Not Executed" = planned but never started; "On Time / Delayed" = actual start before / after planned start',
        'Each rate shows its denominator: Plan Completion Rate = executed ÷ planned, On-Time Rate = on time ÷ executed. Shows "—" instead of 0 when the denominator is zero',
        'Every number is clickable: the category table, chart bars, monthly trend and sub-category table all drill into details, and the detail row count matches the card figure exactly',
        'A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it',
      ],
    },
    pm_analysis: {
      desc: 'PM Execution Analysis: shows preventive-maintenance work orders (PMT) by PM plan number (pmp_no), answering "how far has each plan progressed, how many are overdue, and where are they stuck".',
      usage: [
        'Data comes from eflow_pm (synced from eFlow); the default range covers the full data span',
        'Four core counts: "Closed" = status is Closed; "Open" = not yet Closed; "Overdue" = the source column pmt_overdue is Yes (the upstream verdict is used as-is, never recomputed from dates); "Not Started" = completed item count is 0',
        'Two finer breakdowns: "Closed & Overdue" = back-filled / late delivery; "Open & Overdue" = genuinely still unfinished — look at this one first',
        'Each rate shows its denominator: Closure Rate = closed ÷ total, Overdue Rate = overdue ÷ total (lower is better), Started Rate = share of work orders with at least one item completed. Shows "—" instead of 0 when the denominator is zero',
        'The "Workflow Progress" funnel follows the REAL chronological order: Created → Scheduled → Accepted → PM Manager Approved → Processed → FLM Leader Approved. Beware: the source column names are misleading — last_accept_time actually precedes last_process_time, so never infer the order from the column names',
        'Every number is clickable: KPI cards, rate cards, chart bars, the monthly trend, the site bar chart and the plan table all drill into details, and the detail row count matches the card figure exactly',
        'A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it',
      ],
    },
    bp_report: {
      desc: 'Bad Performance Report: umlaut-caliber BP cell statistics, viewable by day/week/month and drillable down to cell detail.',
      usage: [
        'Caliber: daily = avg active users > 2.5 AND DL throughput < 3 Mbps AND DL PRB utilization > 80%; weekly = BP on 4 of 7 days; monthly = BP in 3 of 4 full weeks',
        '⚠️ Incomplete caliber (a permanent yellow banner sits at the top): RAN_UME does not collect "average active users", so recomputation covers only the PRB and throughput conditions. Cells missing the third condition are marked "Undecidable" and are not counted as BP',
        'Recomputed BP counts are therefore lower than the Excel figures — that is the caliber gap, not an implementation defect; the historical Excel data remains complete and both coexist',
        'The "BP cells" column drills into cell detail, and the row count matches the figure exactly; the "Total cells" column cannot drill down (Excel provides no whole-network cell roster)',
        'The "Detail rows" column shows how many rows the Excel BP Cells List actually holds for that period, with the difference from the displayed value in brackets — the upstream Excel sheets disagree with each other and the gap is shown as-is',
        'Periods with no detail in the Excel BP Cells List (all of 2023, plus some 2024 dates) have their drill-down entry greyed out',
        'Regions (Cluster1~6 / Rural / ERA) can only be maintained in Excel; RAN_UME has no such dimension, and new cells missing from the dictionary fall back to Unknown',
        'Data is incrementally refreshed from RAN_UME by the bp_report_sync task daily at 06:20',
      ],
    },
    warehouse: {
      desc: 'Spare-parts / consumables inventory board (Spare Management), identical to the original tool.',
      usage: ['Data comes from sp_data_sync (5 spare-part reports pulled from SFTP daily at 07:00)', 'Browse inventory and details by warehouse / spare type'],
    },
    // ---- SP spare-parts / consumables report family (added together 2026-09-29) ----
    sp_material: {
      desc: 'Spare-parts material summary: inbound, outbound and inventory rolled up by domain / material.',
      usage: ['Data comes from the spare-part reports pulled by sp_data_sync', 'Click any summary figure to drill into the matching material details'],
    },
    sp_details: {
      desc: 'SP Details Report: the same merged workbook that the email task sends, with Inventory / Inbound / Outbound / Transfer sheets.',
      usage: ['Paginate, filter and sort; "open" means Status does not contain Closed', 'Only common columns are shown — click any row for all columns of that sheet', 'Export covers the current filter (up to 5000 rows)'],
    },
    sp_report: {
      desc: 'Spare Parts Inbound & Outbound & Inventory summary: the same workbook emailed / sent over WhatsApp (produced daily at 05:15 by sp_report_generate), with Summary-Current / Summary-Changed / Inbound / Outbound / Inventory sheets.',
      usage: ['Stat cards show totals and replenishment alerts; clicking an alert card filters', 'Summary-Changed renders as a day × warehouse matrix', '"Columns" is configurable per sheet and remembered locally; the row-detail modal always shows every column'],
    },
    com_report: {
      desc: 'Consumables Inbound & Outbound & Inventory summary: same layout as the spare-parts page, reading the consumables workbook instead.',
      usage: ['Identical basis to the spare-parts page — see "Report basis" at the bottom', 'When the page and Excel disagree, read the basis notes first; never change the basis in the page layer'],
    },
    warehouse_summary: {
      desc: 'Warehouse Summary Report: mirrors WarehouseSummaryReport.xlsx — the tabs are its two sheets, Spars Parts / Consumables. Each tab has two sections: WH/DOP inventory & consumption (current inventory / total / this month / this week), and frequently used materials (10 rows per page, all materials reachable by paging).',
      usage: ['Switch tabs for spare parts vs consumables; every figure in both sections drills down', 'Frequently used materials are paged by consumption descending, showing all of them; the Total row is the full-scope total and does not change when you page', 'Consumption basis is Outbound Site Qty (site outbound), shown as a tag next to the second section title'],
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
    { q: '任务长期停在 pending 不执行？', a: '多半是该任务未被归入任何 worker 组（GROUP_TASK_MAP），队列里永远无人认领——这是本项目已发生过四次的事故模式（finebi_report_sync、whatsapp_send_ext、sp_email_details，以及 2026-09-18 查出的 olib_soc 看板增量与 vmax_multi_data_sync）。新增任务必须在 worker_watchdog.py 的 GROUP_TASK_MAP 登记分组；陈旧 pending 占住的单飞名额 6 小时后会被 worker 自动过期释放。2026-09-18 起这类停摆不再靠人肉发现：db_freshness_check（每小时）会把未归组 / 无执行记录 / 队列滞留 / 成功逾期四类健康异常按翻转去重主动微信+邮件通知。' },
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
    { q: 'A task stays pending forever?', a: 'Most likely the task was never assigned to a worker group (GROUP_TASK_MAP) — nobody claims it from the queue. This accident happened four times in this project (finebi_report_sync, whatsapp_send_ext, sp_email_details, and on 2026-09-18 the olib_soc dashboard sync plus vmax_multi_data_sync). New tasks MUST be registered in GROUP_TASK_MAP in worker_watchdog.py; a stale pending row holding the single-flight slot is now auto-expired by the worker after 6 hours. Since 2026-09-18 such stalls no longer need a human to spot them: db_freshness_check (hourly) pushes the four health findings (ungrouped / no execution record / stuck queue / overdue since last success) through WeChat + email, deduplicated by state flips.' },
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
    { name: '陈旧 pending 过期', body: 'pending 超 6 小时无人认领（典型原因：漏登记 worker 分组）会被置 failed 并补写执行日志，释放被它占住的单飞名额，让下一次调度能正常入队（否则一条陈旧记录会挡住该任务之后的每一次调度）。' },
    { name: '失败通知', body: '任务失败经微信 + 邮件双通道告警（services/weixin_notifier.py 支持 openclaw/wecom/serverchan/pushplus）。' },
    { name: '漏跑/停摆主动告警', body: 'db_freshness_check 每小时算四类健康异常（未归组 / 超出周期无执行记录 / 队列滞留 / 上次成功后逾期无新成功），由 services/task_health_alert.py 按「新异常通知一次、恢复通知一次、持续超 24h 再提一次」推微信+邮件，不必等看板没数据了才人工发现（2026-09-18 上线）。' },
    { name: '进程自愈', body: 'backend_watchdog / worker_watchdog 托管进程：端口探活、崩溃退避重拉（连崩 10 次放弃并告警）；心跳 log/heartbeat_*.json 超 3 分钟未更新判定 hung 强杀重拉。' },
    { name: '保留期', body: 'task_queue 与 task_execution_log 保留 3 天（task_runner.py / worker.py 自动清理），无需手工。' },
  ],
  maintain: [
    { title: '改排程（cron）', body: '「任务管理 → 排程」弹窗修改，写入主库 task_schedule_config 表，立即生效、重启不丢；无需改代码。' },
    { title: '改业务参数', body: '「系统设置 → 任务配置」页签（注意在系统设置里，不在任务管理页）。优先级：环境变量 > 配置文件 > 默认值。' },
    { title: '改上游账号口令', body: '「系统设置 → 凭据」选分组更新，点「测试连接」验证（凭据明文存于 db/app.db 的 credentials 表，缓存 30s）。' },
    { title: '改收件人', body: '「系统设置 → 邮件收件人」分组编辑，可重置默认；改完对所有 kpi_* / *_email 任务生效。' },
    { title: '手动执行 / 停止', body: '任务管理页「执行」立即投递一次、「停止」中断长任务。验证新排程/新脚本后应先手动跑一次看执行历史。' },
    { title: '新增一个任务', body: '① task_registry.py 的 TASK_SPECS 追加声明（task_id/name/cron/loader）；② worker_watchdog.py 的 GROUP_TASK_MAP 登记分组（漏了永远 pending，已四次踩坑；tests/test_worker_group_coverage.py 交叉校验 task_id 覆盖与两处组集合一致）；新建组则必须同步 GROUP_TASK_MAP 键与 start_hidden.ps1 的 MY_APP_WORKER_GROUPS、$groups 两处（restart_workers.py 的 ALL_GROUPS 自动取自 GROUP_TASK_MAP）；③ 业务函数放 backend/services/ 且抛异常不吞；④ stop.bat → start.bat 重启加载注册表（只改分组清单则 python restart_workers.py --mode watchdog --force，**要管理员权限**）；⑤ 手动执行验证并更新文档（04-task-system.md 清单与本帮助数据 helpTaskDocs.ts，改完跑 npm run docs）。' },
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
    { port: '—', proc: 'worker × 5 组（u/n/v/m/c，消费 task_queue）', guard: 'worker_watchdog.py' },
  ],
  portCols: ['端口', '进程', '谁负责活着'],
  inspect: [
    '任务管理页：有没有 failed、有没有长期 pending（失败聚合视图比翻列表快）',
    '页头同步标签：GIS / TT&WO / Dashboard 的「最近同步」是否在预期窗口内',
    '数据总览页：表数量与行数是否明显异常',
    '命令行：五个关键进程是否都在、心跳 heartbeat_*.json 是否新鲜（超 3 分钟会被强杀重拉）',
    '数据库新鲜度由 db_freshness_check 每小时 :15 自动巡检，滞后会给出调用链与排查方向；任务本身漏跑/停摆（未归组、无执行记录、队列滞留、成功逾期）也会在同一巡检里主动微信+邮件告警，不需要人工等看板空了才发现',
  ],
  logs: [
    { file: 'log/worker_runtime*.log', body: '任务执行主日志——排障首选，按 task_id 搜堆栈（每组 worker 一个文件：_u/_n/_v/_m/_c）' },
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
  configPriority: '三层配置，优先级从高到低：环境变量（backend/.env，203 个键，改后需重启） > 数据库/配置文件（凭据、收件人、排程、远程主机、任务参数——界面改，即时生效） > 代码默认值。',
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
    { name: 'Stale pending expiry', body: 'A pending row unclaimed for over 6 hours (typical cause: the task was never registered in a worker group) is marked failed with an execution-log entry, freeing the single-flight slot it held — otherwise one stale row would block every later trigger of that task.' },
    { name: 'Failure notification', body: 'Failures notify via WeChat + email (services/weixin_notifier.py supports openclaw/wecom/serverchan/pushplus).' },
    { name: 'Missed-run / stall alert', body: 'db_freshness_check computes four health findings hourly (ungrouped / no execution record within the cron-scaled window / stuck queue / overdue since last success); services/task_health_alert.py pushes them to WeChat + email, notifying once per new anomaly and once on recovery, re-raising after 24h (added 2026-09-18).' },
    { name: 'Process self-healing', body: 'backend_watchdog / worker_watchdog supervise processes: port probing, crash backoff (give up & alert after 10 consecutive crashes); heartbeats in log/heartbeat_*.json stale >3 min → force kill & restart.' },
    { name: 'Retention', body: 'task_queue & task_execution_log are kept 3 days (auto-cleaned), no manual work.' },
  ],
  maintain: [
    { title: 'Change schedule (cron)', body: 'Task Manager → "Schedule" dialog; persisted into task_schedule_config, effective immediately, survives restarts — no code change needed.' },
    { title: 'Change task parameters', body: 'Settings → "Task Config" tab (it lives under Settings, not Task Manager). Priority: env var > config file > default.' },
    { title: 'Change upstream credentials', body: 'Settings → Credentials, pick the group, update, then "Test Connection" (plaintext in db/app.db credentials table; 30s cache).' },
    { title: 'Change recipients', body: 'Settings → Email Recipients, edit groups or reset to defaults; applies to all kpi_* / *_email tasks.' },
    { title: 'Run / stop manually', body: '"Run" enqueues immediately, "Stop" interrupts a long task. After changing a schedule or script, run once manually and check the history.' },
    { title: 'Add a new task', body: '① Append an entry to TASK_SPECS in task_registry.py; ② register it in GROUP_TASK_MAP in worker_watchdog.py (missing = forever pending, four accidents so far; tests/test_worker_group_coverage.py cross-checks task_id coverage and the three group-set declarations) — a brand-new group must be synced in three places: GROUP_TASK_MAP keys, MY_APP_WORKER_GROUPS in start_hidden.ps1, ALL_GROUPS in restart_workers.py; ③ business function in backend/services/, throw exceptions; ④ restart via stop.bat → start.bat (group-list-only changes: python restart_workers.py --mode watchdog --force, **needs elevation**); ⑤ verify manually and update docs (04-task-system.md list & helpTaskDocs.ts, then npm run docs).' },
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
    { port: '—', proc: 'workers × 5 groups (u/n/v/m/c consuming task_queue)', guard: 'worker_watchdog.py' },
  ],
  portCols: ['Port', 'Process', 'Kept alive by'],
  inspect: [
    'Task Manager: any failed? any long-standing pending? (the failure summary view beats scrolling the list)',
    'Header sync badges: are "last synced" labels on GIS / TT&WO / Dashboard within the expected window',
    'Overview page: table count & row counts clearly abnormal?',
    'CLI: are the five key processes alive and heartbeats (heartbeat_*.json) fresh (>3 min stale → force-restart)',
    'DB freshness is audited hourly at :15 by db_freshness_check; staleness logs include the call chain. The same audit alerts proactively (WeChat + email) when tasks themselves stall — ungrouped, no execution record, stuck queue, or overdue since the last success',
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
  configPriority: 'Three config layers, highest first: environment variables (backend/.env, 203 keys, restart required) > DB/config files (credentials, recipients, schedules, remote host, task params — edited via UI, effective immediately) > code defaults.',
  credentialNote: [
    '12 credential groups: zte_ume, vmax_cxo, ipran_ume, ccn_ume, eflow, fms_portal, fw_kpi, mw_ume, sftp_sp, mail_126, owa_mail, weixin (maintained in Settings → Credentials)',
    'Read priority: env var > DB > empty; the list API returns masks, with separate "reveal" and "test connection" endpoints',
    'Credentials are stored plaintext in the credentials table of db/app.db (credential_store opens SQLite directly, bypassing MY_APP_DB_MODE) — always include the file in backups, treat as sensitive media',
    'Session cookies under backend/services/auth_cache/ are equivalent to valid logins — never ship, commit or screenshot them',
  ],
}

export const OPS: Record<Locale, OpsText> = { zh: OPS_ZH, en: OPS_EN }
