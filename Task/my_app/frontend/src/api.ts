import axios from 'axios'

// API 基地址解析顺序（优先级从高到低）：
//   1. URL 参数 ?api=https://xxx  —— 便于云端静态托管(CloudStudio)指向 cloudflared 隧道
//   2. localStorage('myapp-api-base') —— 持久化 URL 参数，避免 SPA 内跳转丢参数
//   3. 构建期注入 import.meta.env.VITE_API_BASE —— 构建云端版时写死默认值
//   4. '/api' —— 内网同源(nginx 反代)，默认值，现有系统行为不变
function resolveApiBase(): string {
  try {
    const urlBase = new URLSearchParams(window.location.search).get('api')?.trim()
    if (urlBase) {
      // 持久化，避免 SPA 路由切换后 URL 参数丢失
      localStorage.setItem('myapp-api-base', urlBase)
      return urlBase.replace(/\/$/, '')
    }
  } catch { /* ignore */ }
  try {
    const lsBase = localStorage.getItem('myapp-api-base')?.trim()
    if (lsBase) return lsBase.replace(/\/$/, '')
  } catch { /* ignore */ }
  const envBase = (import.meta.env?.VITE_API_BASE as string | undefined)?.trim()
  if (envBase) return envBase.replace(/\/$/, '')
  return '/api'
}

const api = axios.create({
  baseURL: resolveApiBase(),
  timeout: 120000,
  // 携带后端签发的 HttpOnly 会话 Cookie（uniplam 门户鉴权适配）
  withCredentials: true,
})

// 通知后端返回本地化数据（任务名/描述等后端数据字段）
export function setApiLocale(locale: 'zh' | 'en') {
  api.defaults.headers.common['Accept-Language'] = locale === 'en' ? 'en' : 'zh-CN'
}

// MS SLA 看板总览：NUR / SLA / Network KPI / Per-Site / WO（日+月）+ meta 新鲜度
// 数据源 ms_sla_dashboard.sqlite3，由 ms_sla_full 任务写库（TTL 60s 缓存）
// start/end（YYYY-MM-DD，可选）：限制 nur/sla/wo/Per-Site 站点占比实时计算区间
//（前端 Time Range 默认最近 6 个月，与 NUR 看板一致）
export function getMsSlaOverview(params?: Record<string, string>) {
  return api.get('/ms-sla-dashboard/overview', { params })
}

// 站点可用率与工单看板（FME / Supervisor 维度）
// 数据源：db/app.db master_site_db + eflow_tt + 远端站点级可用性日表 + 本地 TDD 小区表
export function getSiteAvailabilityFilters() {
  return api.get('/site-availability/filters')
}

// FME 工程师 WO / 站点可用率排名
export function getFmeRankingFilters() {
  return api.get('/fme-ranking/filters')
}

export function getFmeRankingOverview(params?: Record<string, string | number>) {
  return api.get('/fme-ranking/overview', { params })
}

// FME 下钻：该 FME 名下的 WO 明细
export function getFmeRankingWoDrilldown(params?: Record<string, string | number>) {
  return api.get('/fme-ranking/wo-drilldown', { params })
}

// FME 下钻：该 FME 名下的站点级可用率 + WO 明细
export function getFmeRankingSiteDrilldown(params?: Record<string, string | number>) {
  return api.get('/fme-ranking/site-drilldown', { params })
}

// ========== CR 变更分析（按 change_category 看计划 / 完成情况）==========
// 数据源：eflow_cr（eFlow 同步）。后端 backend/routers/cr_analysis.py，
// 口径（终态词表、按时/延期判定、概览与下钻共用一份 WHERE）见
// backend/services/cr_analysis_service.py 的模块 docstring。
export function getCrAnalysisFilters() {
  return api.get('/cr-analysis/filters')
}

export function getCrAnalysisOverview(params?: { start?: string; end?: string }) {
  return api.get('/cr-analysis/overview', { params })
}

// 下钻：metric 决定批次，category / sub_category / month 是叠加的维度过滤，
// 必须与点击来源的卡片维度完全一致，否则明细行数与卡片数字对不上。
export function getCrAnalysisDrilldown(params: {
  start?: string; end?: string; metric: string
  category?: string; sub_category?: string; month?: string; limit?: number
}) {
  return api.get('/cr-analysis/drilldown', { params })
}

// ========== PM 执行分析（按 PM 计划看预防性维护工单的完成 / 超期）==========
// 数据源：eflow_pm（eFlow 同步）。后端 backend/routers/pm_analysis.py，
// 口径（字段名陷阱、真实流程顺序、pmt_overdue 语义、概览与下钻共用一份 WHERE）
// 见 backend/services/pm_caliber.py 的模块 docstring。
export function getPmAnalysisFilters() {
  return api.get('/pm-analysis/filters')
}

export function getPmAnalysisOverview(params?: { start?: string; end?: string }) {
  return api.get('/pm-analysis/overview', { params })
}

// 下钻：metric 决定批次，pmp_no / status / site_name / handler / month 是叠加的
// 维度过滤，必须与点击来源的卡片维度完全一致，否则明细行数与卡片数字对不上。
export function getPmAnalysisDrilldown(params: {
  start?: string; end?: string; metric: string
  pmp_no?: string; status?: string; site_name?: string
  handler?: string; month?: string; limit?: number
}) {
  return api.get('/pm-analysis/drilldown', { params })
}

// ========== Speedtest 竞对分析（ORANGE vs MTN）==========
// 数据源：speedtest_data（Speedtest.xlsx 导入）。后端 backend/routers/bm_speedtest.py，
// 口径（品牌归一、左闭右开时间窗、概览与下钻共用同一份 WHERE）
// 见 backend/services/bm_speedtest_caliber.py 的模块 docstring。
export function getBmSpeedtestFilters() {
  return api.get('/bm-speedtest/filters')
}

export function getBmSpeedtestOverview(params?: { start?: string; end?: string }) {
  return api.get('/bm-speedtest/overview', { params })
}

// 单指标趋势 + 滚动均值；metric 非法时后端回落 download
export function getBmSpeedtestTrend(params?: {
  start?: string; end?: string; metric?: string; window?: number
}) {
  return api.get('/bm-speedtest/trend', { params })
}

// 下钻：metric + winner 组合表示「该指标更强的那一方的胜日明细」，
// 行数与该指标的胜场天数严格相等；day / brand 是叠加的维度过滤。
export function getBmSpeedtestDrilldown(params?: {
  start?: string; end?: string; metric?: string
  day?: string; brand?: string; winner?: string; limit?: number
}) {
  return api.get('/bm-speedtest/drilldown', { params })
}

// ========== TT 复盘报告（NOC 操作人分析 / 派单机制真相 / 单 TT 复盘 / MD 导出）==========
// 新增于 2026-09-23；对应后端 routers/eflow_qa.py 中 _tt_postmortem_* 端点
export function getTtPostmortem(ttNo: string) {
  return api.get(`/eflow-qa/_tt_postmortem/${encodeURIComponent(ttNo)}`)
}

export function getNocAnalystReport(params?: Record<string, string | number>) {
  return api.get('/eflow-qa/_tt_postmortem_noc', { params })
}

// NOC 操作人分析 · 三层下钻（2026-09-23 新增，均为只读）
// ① NOC → TT 明细，slice: all / mismatch / night / sla_fail / slow
//    owner: IPT（第三方，按设计不建 WO）/ ZTE（自维）；不传 = 全部
export function getNocTtDrilldown(params: {
  noc: string; month?: string; slice?: string; limit?: number; owner?: string
}) {
  return api.get('/eflow-qa/_tt_postmortem_noc_tt', { params })
}

// ② NOC → 异常站点聚合
export function getNocSiteDrilldown(params: { noc: string; month?: string; only_abnormal?: boolean }) {
  return api.get('/eflow-qa/_tt_postmortem_noc_sites', { params })
}

// ③ 单 TT → 告警链路 + 根因一致性审计（最底层）
export function getNocTtDetail(params: { tt_no: string; noc?: string }) {
  return api.get('/eflow-qa/_tt_postmortem_tt_detail', { params })
}

// ④ 单 TT → 里程碑时间轴 + 应做/实做 + 偏离清单 + 时间归因（复盘报告原生结构）
//    与 getNocTtDetail 的分工：本接口给「时间都花哪了」，那个给「根因对不对」。
export function getTtTimeline(ttNo: string) {
  return api.get(`/eflow-qa/_tt_postmortem_timeline/${encodeURIComponent(ttNo)}`)
}

// ⑤ 本月里程碑时间轴批量聚合（时间归因 / 动作偏离 / 未派 WO），
//    逐单复用复盘报告口径；按 month 落磁盘缓存，首次约 150s、之后毫秒级。
//    owner=IPT/ZTE 按承接方切分（第三方单本就不建 WO，不分开会误报"应派未派"）。
//    refresh=true 强制重算（月份数据仍在增长时用）。
export function getNocTimelineAgg(params?: {
  month?: string; limit?: number; noc?: string; owner?: string; refresh?: boolean
}) {
  return api.get('/eflow-qa/_tt_postmortem_noc_timeline', { params, timeout: 600000 })
}

export function exportTtPostmortemMd(ttNo: string) {
  return api.post(`/eflow-qa/_tt_postmortem_export_md/${encodeURIComponent(ttNo)}`)
}

// Daily site-down occurrence dashboard: eflow_tt + eflow_site.
export function getRepeatSiteDownFilters() {
  return api.get('/repeat-site-down/filters')
}

export function getRepeatSiteDownOverview(params?: Record<string, string | number>) {
  return api.get('/repeat-site-down/overview', { params })
}

export function getRepeatSiteDownEvents(params?: Record<string, string | number>) {
  return api.get('/repeat-site-down/events', { params })
}

export function getRepeatSiteDownDayDrilldown(params: Record<string, string | number>) {
  return api.get('/repeat-site-down/day-drilldown', { params })
}

export function getRepeatSiteDownSiteDrilldown(params: Record<string, string | number>) {
  return api.get('/repeat-site-down/site-drilldown', { params })
}

export function getRepeatSiteDownEventDetail(params: Record<string, string | number>) {
  return api.get('/repeat-site-down/event-detail', { params })
}

// params: month / supervisor / fme / tech / threshold / only_with_data
export function getSiteAvailabilityOverview(params?: Record<string, string | number>) {
  return api.get('/site-availability/overview', { params })
}

// params: month / site_id / site_name
export function getSiteAvailabilityTickets(params?: Record<string, string>) {
  return api.get('/site-availability/tickets', { params })
}

// MS Availability（page=avail_ms，可用率多维矩阵）：区域/制式/站点类型 × 日/周/月
// 数据源：本机派生库 data/avail_recon.sqlite3（任务 avail_recon_sync 每天 06:10 重建），
// 口径 = SUM(Numerator)/SUM(Denominator)，见 backend/services/avail_ms_service.py
export function getAvailMsOptions() {
  return api.get('/avail-ms/options')
}

// params: period=day|week|month / value=周期值（空=库里最新一期） / threshold=未达标比率
export function getAvailMsMatrix(params: { period: string; value?: string; threshold?: number }) {
  return api.get('/avail-ms/matrix', { params })
}

// 页面曲线图：三个维度各自的多序列趋势，与矩阵/下钻同口径
// params: period / value=窗口右端周期（空=最新） / points=窗口期数（0=按档位默认） / threshold
export function getAvailMsTrend(params: {
  period: string; value?: string; points?: number; threshold?: number
}) {
  return api.get('/avail-ms/trend', { params })
}

// params: level=period|tt / period / value / region(ALL|区域名|UNMATCHED) / tech / site_type / threshold
export function getAvailMsDrilldown(params: Record<string, string | number>) {
  return api.get('/avail-ms/drilldown', { params })
}

// FLM 可用率（page=avail_flm）：区域为行、制式/站点类型为列 + 页面级 TT 列表
// 与 avail_ms 同库同口径（后端复用同一套聚合），差别只在行列摆法与那张 TT 列表，
// 两条已确认的口径（站点类型不做范围限制、TT 不做影响判定）见 backend/services/avail_flm_service.py
export function getAvailFlmOptions() {
  return api.get('/avail-flm/options')
}

// params: period=day|week|month / value=周期值（空=库里最新一期） / threshold=未达标比率
export function getAvailFlmMatrix(params: { period: string; value?: string; threshold?: number }) {
  return api.get('/avail-flm/matrix', { params })
}

// 本页两组曲线：区域趋势 + 站点类型趋势（后端已按本页的行列收窄，不再含 ALL / Other）
export function getAvailFlmTrend(params: {
  period: string; value?: string; points?: number; threshold?: number
}) {
  return api.get('/avail-flm/trend', { params })
}

// 本期全部 TT 工单（页面级列表与下钻「相关 TT 工单」页签共用）
// params: period / value / region（空或 ALL=全部区域） / site_type（空=全部）
export function getAvailFlmTt(params: {
  period: string; value?: string; region?: string; site_type?: string
}) {
  return api.get('/avail-flm/tt', { params })
}

// params: level=period|tt / period / value / region / tech / site_type / threshold（与 avail-ms 同形）
export function getAvailFlmDrilldown(params: Record<string, string | number>) {
  return api.get('/avail-flm/drilldown', { params })
}

// CN KPI 看板（原 my-finebi「CN KPI」看板原生重建）
// 数据源：db_ps_cs_cn.sqlite3，经远端只读 SQL API（backend/config/remote_host.py）；
// **不依赖 my-finebi 进程**。18 个组件的 SQL 与图表类型对齐 FineBI 原看板。
// params: start/end=YYYY-MM-DD（自定义区间，留空=近31天）/ force=true 跳过后端 60s 缓存
export function getCnKpiOverview(params?: { start?: string; end?: string; force?: boolean }) {
  const q: Record<string, string | number> = {}
  if (params?.start) q.start = params.start
  if (params?.end) q.end = params.end
  if (params?.force) q.force = 1
  return api.get('/cn-kpi/overview', { params: Object.keys(q).length ? q : undefined })
}

// 远端只读 SQL API 连通性探测（供 CN KPI 页诊断提示）
export function getCnKpiHealth() {
  return api.get('/cn-kpi/health')
}

// ===== 原生看板（my-finebi 其余看板泛化迁移） =====
// 一套端点驱动 17 个看板（IP RAN Metro Ring / 可用率 / 2G-3G-4G KPI / MTTR /
// CM / 备件 / Progress 等），slug 见 backend/services/native_catalog.py。
// 数据源经远端只读 SQL API（backend/config/remote_host.py），**不依赖 my-finebi 进程**。
// params: start/end=YYYY-MM-DD（时间窗口，须成对；留空=各组件原口径全量）
//         force=true 跳过后端 60s 缓存
export interface NativeBoardWindow {
  start?: string
  end?: string
  force?: boolean
}

function _nbParams(p?: NativeBoardWindow) {
  const q: Record<string, string | number> = {}
  if (p?.start) q.start = p.start
  if (p?.end) q.end = p.end
  if (p?.force) q.force = 1
  return Object.keys(q).length ? q : undefined
}

/** 原生看板清单（菜单/路由用，轻量不含 SQL） */
export function listNativeBoards() {
  return api.get('/native-boards')
}

/** 单个原生看板整页数据 */
export function getNativeBoard(slug: string, params?: NativeBoardWindow) {
  return api.get(`/native-boards/${encodeURIComponent(slug)}`, { params: _nbParams(params) })
}

/** 原生看板远端连通性探测 */
export function getNativeBoardHealth(slug: string) {
  return api.get(`/native-boards/${encodeURIComponent(slug)}/health`)
}

/**
 * 导出原生看板数据为 Excel（每组件一个 sheet + 说明 sheet）。
 * 走 blob 下载，文件名优先取响应头 filename*（后端做了 RFC 5987 编码）。
 */
export async function exportNativeBoard(slug: string, params?: NativeBoardWindow) {
  const res = await api.get(`/native-boards/${encodeURIComponent(slug)}/export`, {
    params: _nbParams(params),
    responseType: 'blob',
  })
  const cd = String(res.headers?.['content-disposition'] || '')
  let name = `${slug}.xlsx`
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  const plain = /filename="?([^";]+)"?/i.exec(cd)
  if (utf8) {
    try { name = decodeURIComponent(utf8[1]) } catch { /* 保底用原值 */ }
  } else if (plain) {
    name = plain[1]
  }
  const url = URL.createObjectURL(res.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return name
}

// RAN 2G/3G/4G Cells KPI 看板：按天统计各制式小区可用率达标情况// 数据源：data/ran_cells_kpi.sqlite3（由 cells_kpi_sync 任务从 RAN_UME 小区数据物化，
// 只保留当月；缺失时后端回退实时聚合 data/ran_kpi_avalability_1day.sqlite3）
// params: month=YYYY-MM / threshold=0.9965 / prefer_db=0|1
export function getRanCellsKpiOverview(params?: Record<string, string | number>) {
  return api.get('/ran-cells-kpi/overview', { params })
}

// RAN Cells KPI 小区级明细（看板数字下钻）：返回某制式某天（或整月）背后的小区列表
// params: month=YYYY-MM / tech=2G|3G|4G / day=YYYY-MM-DD（留空=整月汇总）
//         / threshold=0.9965 / scope=all|meeting|below|blank
export function getRanCellsKpiCells(params?: Record<string, string | number>) {
  return api.get('/ran-cells-kpi/cells', { params })
}

// BP Report 劣化小区报告（umlaut 口径：日均三条件 / 周 4/7 天 / 月 3/4 个完整周）
// 数据源：本机派生库 data/bp_report.sqlite3（Excel 一次性导入 + bp_report_sync 每日更新）
// ⚠️ 口径不完整：Average DL Active User Number 在 RAN_UME 侧未采集，
//    返回体 meta.active_user.available=false，页面须常驻告警，不要隐藏。
// params: start=YYYY-MM-DD / end=YYYY-MM-DD / granularity=day|week|month
export function getBpReportOverview(params?: Record<string, string | number>) {
  return api.get('/bp-report/overview', { params })
}

// BP Report 分区维度（Cluster1~6 / Rural / ERA / Unknown），对应 Excel 的 Regional - Daily
// params: start / end / region
export function getBpReportRegional(params?: Record<string, string | number>) {
  return api.get('/bp-report/regional', { params })
}

// BP Report 频层维度（L800 / L1800 20M / L1800 15M / L1800 10M / L2600 / Unknown）
// params: start / end / region / layer
export function getBpReportLayer(params?: Record<string, string | number>) {
  return api.get('/bp-report/layer', { params })
}

// BP Report 小区明细（**下钻**）：scope=bp 的行数 == 概览的 summary.bp_cells
// params: day=YYYY-MM-DD 或 start/end / region / layer
//         / scope=bp|nonbp|undecidable|all / limit
export function getBpReportCells(params?: Record<string, string | number>) {
  return api.get('/bp-report/cells', { params })
}

// BP Report 口径说明、脏值统计、同步状态与对账差异
export function getBpReportMeta() {
  return api.get('/bp-report/meta')
}

// 客户业务 KPI（UME Dong customer 周度指标：IVR / P4M / VC / USSD / PPS / CPU / Memory）
// params: days=7|14|30（回看天数，按已有数据的最后 N 天）
export function getUmeInOverview(params?: Record<string, string | number>) {
  return api.get('/ume-in/overview', { params })
}

// 立即从 UME 门户（172.17.208.1:28808）抓取 7 个模板并写库（约 10~60 秒）
export function syncUmeIn(params?: Record<string, string | number>) {
  return api.post('/ume-in/sync', null, { params, timeout: 300000 })
}

// SP 物料库存/消耗统计汇总（WH/DOP 汇总报表模板）
// 数据源：db/app.db inventory_details（每日全量快照，由 sp 数据同步任务写入）
// 口径见 backend/services/sp_material_summary_service.py 顶部 docstring
// params: anchor_date=YYYY-MM-DD（期初锚点，缺省=当前快照所在自然月 1 号）
//         current_date=YYYY-MM-DD（期末，缺省=库内 MAX(update_date)）
export function getSpMaterialSummary(params?: Record<string, string>) {
  return api.get('/sp-material/summary', { params })
}

// 汇总表格子下钻明细
// params: row_key=1st_wh|2nd_wh|gbarnga_dop|kweaken_dop|others|total
//         scope=anchor_spare_good|anchor_consumables|current_spare_good
//               |current_consumables|need_repair
export function getSpMaterialDetail(params: Record<string, string>) {
  return api.get('/sp-material/detail', { params })
}

/* ---------- SP 备件明细报表（page=sp_details / SpDetailsReport） ----------
 * 数据源：data/sp_email/data 下由任务 sp_email_details（SP Spare Parts Details
 * Report Email）每天生成的合并工作簿「SP Details Report <时间戳>.xlsx」
 * （sheet：Inventory / Inbound / Outbound / Transfer）—— 与邮件附件是同一份文件，
 * 口径见 backend/services/sp_details_service.py 顶部 docstring。 */
// 统计卡片 + 各 sheet 元信息 + 数据来源
export function getSpDetailsSummary() {
  return api.get('/sp-details/summary')
}

// 某 sheet 的分页明细
// params: sheet=Inventory|Inbound|Outbound|Transfer
//         page / page_size / q（全列模糊搜索）/ sort（列名）/ order=asc|desc
//         filters=JSON 字符串，如 {"Status":"Closed"}（值为数组时按 IN 处理）
export function getSpDetailsRows(params: Record<string, string | number>) {
  return api.get('/sp-details/rows', { params })
}

// 某 sheet 的筛选下拉候选值（状态 / 仓库 / 物料大类 / 业务类型 / 域 / 物料状态）
export function getSpDetailsFilters(sheet: string) {
  return api.get('/sp-details/filters', { params: { sheet } })
}

/* ---------- SP 备件 / 耗材汇总报表（page=sp_report / com_report） ----------
 * 数据源：data/sp_email 下由任务 sp_report_generate（SP 备件报表生成，每天 05:15）
 * 产出的两份汇总工作簿「<前缀> <时间戳>.xlsx」（sheet：Summary-Current /
 * Summary-Changed / Inbound / Outbound / Inventory）—— 与邮件附件是同一份文件。
 * kind: 'spareparts'（备件，?page=sp_report）| 'consumables'（耗材，?page=com_report） */
export type SpReportKind = 'spareparts' | 'consumables'

// 统计卡片 + 各 sheet 元信息 + 每日矩阵 + 报表自带口径说明
// 另含「仓库汇总报表」页（page=warehouse_summary）用的两块：
//   warehouse_summary    WH/DOP × 库存·全量消耗·本月·本周（含 Total 行）
//   frequent_materials   高频消耗物料 Top N + 全量 Total 行
export function getSpReportSummary(kind: SpReportKind) {
  return api.get('/sp-report/summary', { params: { kind } })
}

// 某 sheet 的分页明细
// params: kind / sheet / page / page_size / q / sort / order / filters(JSON 字符串)
export function getSpReportRows(params: Record<string, string | number>) {
  return api.get('/sp-report/rows', { params })
}

// 某 sheet 的筛选下拉候选值
export function getSpReportFilters(kind: SpReportKind, sheet: string) {
  return api.get('/sp-report/filters', { params: { kind, sheet } })
}

/* ---------- MS Contract KPIs / WOs SLA 报表（page=ms_contract_kpi / ms_wo_sla） ----------
 * 数据源：data/ms_sla 下任务产出的报表工作簿本体（与邮件附件是同一份文件）——
 *   wo_sla       : ZTE OLR MS WOs SLA Achievements Daily Report_<日期>.xlsx（kpi_ms_wo_sla 任务）
 *   contract_kpi : ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx（ms_sla_full 任务）
 * 口径见 backend/services/ms_kpi_report_service.py 顶部 docstring。 */
export type MsKpiReportKind = 'wo_sla' | 'contract_kpi'

// 统计卡片 + KPI 矩阵（表头/日行/月行/逐指标统计）+ 分表元信息
export function getMsKpiReportSummary(kind: MsKpiReportKind) {
  return api.get('/ms-kpi-report/summary', { params: { kind } })
}

// 某 sheet 的分页明细（矩阵 sheet 会被压平成「一行一天」）
// params: kind / sheet / page / page_size / q / sort / order / filters(JSON 字符串)
export function getMsKpiReportRows(params: Record<string, string | number>) {
  return api.get('/ms-kpi-report/rows', { params })
}

// 某 sheet 的筛选下拉候选值（FineBI 规划的 Domain/Priority、自动化报表的团队/频率 …）
export function getMsKpiReportFilters(kind: MsKpiReportKind, sheet: string) {
  return api.get('/ms-kpi-report/filters', { params: { kind, sheet } })
}

/* ---------- 界面配置：侧栏菜单结构（全局共享，仅本机可写） ----------
 * 服务端唯一真相源：所有访问者看到同一份目录结构；只有本机（或持 X-API-Token）
 * 能保存，远程会 403。GET 返回 {layout, updated_at, editable}。 */
export interface MenuLayoutPayload {
  v?: number
  groups: { key: string; label?: string; hidden?: boolean; items: string[] }[]
  itemLabels?: Record<string, string>
}

export function getMenuLayout() {
  return api.get('/ui/menu-layout')
}

export function saveMenuLayout(layout: MenuLayoutPayload) {
  return api.put('/ui/menu-layout', { layout })
}

export function resetMenuLayout() {
  return api.delete('/ui/menu-layout')
}

/* ---------- uniplam 门户鉴权适配 ----------
 * portal-login：把门户深链带进来的门户 token 交给后端换 myapp 会话 Cookie。
 * 401 拦截：数据接口返回 401 时通知 App 展示“请通过统一门户登录”引导。
 * 用模块级订阅避免在 api.ts 里耦合 React。 */

let onUnauthorized: (() => void) | null = null

/** App 注册“未登录”回调（会话失效 / 未登录访问数据接口时触发） */
export function setOnUnauthorized(fn: (() => void) | null) {
  onUnauthorized = fn
}

/** 用门户深链 token 换取 myapp 会话 Cookie（成功后前端再 replaceState 抽走 ?t=） */
export function portalLogin(token: string) {
  return api.post('/auth/portal-login', { token })
}

export function apiLogout() {
  return api.post('/auth/logout')
}

export function getAuthMe() {
  return api.get('/auth/me')
}

/** 探测后端鉴权模式（公开接口）：authEnabled=false 表示已开启日常开发免登录，
 *  前端据此跳过「请通过统一门户登录」引导（见 backend/auth_switch.py）。 */
export function getAuthMode() {
  return api.get('/auth/mode')
}

/* ---------- 启动前鉴权引导（preflight） ----------
 * 背景（2026-09-14 修复首屏 401）：门户深链带 ?t=<门户token> 打开看板时，「换会话」
 * 是异步请求，而业务页面一挂载就抢跑数据接口 → 首屏必然 401，表现为
 * 「Failed to load data / Request failed with status code 401，刷新就正常」
 * （刷新时 Cookie 已落地，所以第二次就好）。
 * 修法：把「换会话」提前到 React 渲染之前完成（见 main.tsx），并让页面在引导
 * 结束前不挂载，从结构上消除抢跑；runAuthBootstrap 记忆化，重复调用复用同一 Promise。 */

/** 门户登录态在 localStorage 的键（与 uniplam 门户 src/config.ts 保持一致） */
const PORTAL_TOKEN_KEY = 'liberia_noc_auth_v1'

/** 取门户 token：优先 URL 深链 ?t=（取到即从地址栏抽走，避免门户 token 长期留痕），
 *  其次门户登录态 localStorage —— myapp 与门户同源，可直接读到，
 *  因此书签 / 手输 URL 打开看板也能免重复登录。 */
export function readPortalToken(): string | null {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('t')?.trim()
    if (fromUrl) {
      const url = new URL(window.location.href)
      url.searchParams.delete('t')
      window.history.replaceState({}, '', url)
      return fromUrl
    }
  } catch { /* ignore */ }
  try { return localStorage.getItem(PORTAL_TOKEN_KEY) || null } catch { return null }
}

/** 启动前把门户 token 换成 myapp 会话 Cookie，返回「是否已具备访问数据的身份」。 */
export async function bootstrapAuth(): Promise<boolean> {
  const token = readPortalToken()
  if (token) {
    try {
      await portalLogin(token)
      return true
    } catch { /* token 失效 / 门户不可达：继续往下探测会话 */ }
  }
  try {
    const mode = await getAuthMode()
    if (mode.data?.authEnabled === false) return true // 日常开发免登录
  } catch { /* 探测失败按未登录处理 */ }
  try {
    await getAuthMe()
    return true
  } catch {
    return false
  }
}

let _bootstrapPromise: Promise<boolean> | null = null

/** 幂等获取启动鉴权结果：main.tsx 先跑一次，App 再取同一个 Promise（不会重复换会话）。 */
export function runAuthBootstrap(): Promise<boolean> {
  if (!_bootstrapPromise) _bootstrapPromise = bootstrapAuth()
  return _bootstrapPromise
}

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    // 401（跳过鉴权接口自身，避免 bootstrap 失败触发引导闪屏）
    if (error?.response?.status === 401) {
      const url = error?.config?.url ?? ''
      if (!String(url).startsWith('/auth/')) {
        onUnauthorized?.()
      }
    }
    return Promise.reject(error)
  },
)

export default api
