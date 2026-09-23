import { useState, lazy, Suspense, useEffect, useCallback, useMemo, useRef, Fragment } from 'react'
import type { ReactNode } from 'react'
import { ConfigProvider, Layout, Menu, theme, Button, Spin, Tooltip, Select, Modal, Input, Popconfirm } from 'antd'
import {
  DatabaseOutlined,
  ClusterOutlined,
  AppstoreOutlined,
  UploadOutlined,
  DashboardOutlined,
  GlobalOutlined,
  HistoryOutlined,
  TableOutlined,
  BarChartOutlined,
  TeamOutlined,
  TranslationOutlined,
  SyncOutlined,
  AlertOutlined,
  DisconnectOutlined,
  ThunderboltOutlined,
  SettingOutlined,
  AimOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  AreaChartOutlined,
  FundProjectionScreenOutlined,
  FundOutlined,
  DotChartOutlined,
  SafetyOutlined,
  PieChartOutlined,
  LoginOutlined,
  SunOutlined,
  MoonOutlined,
  ExportOutlined,
  SelectOutlined,
  MenuUnfoldOutlined,
  MenuFoldOutlined,
  MailOutlined,
  ApartmentOutlined,
  CloseOutlined,
  FieldTimeOutlined,
  BookOutlined,
  QuestionCircleOutlined,
  MessageOutlined,
  EditOutlined,
  PlusOutlined,
  DeleteOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SearchOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  DesktopOutlined,
  FileDoneOutlined,
  SolutionOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'

import { I18nProvider, useI18n } from './i18n'
import { TaskStatusProvider } from './TaskStatusContext'
import { ThemeProvider, useTheme, WH, useIsMobile } from './theme'
import { invalidateCache } from './cache'
import {
  getMenuLayout,
  saveMenuLayout,
  resetMenuLayout,
  getAuthMe,
  runAuthBootstrap,
  setOnUnauthorized,
  type MenuLayoutPayload,
} from './api'

// 路由级代码分割：每个页面独立成 chunk，按需加载，首屏不再一次性下载全部页面
const TableBrowser = lazy(() => import('./pages/TableBrowser'))
const DataUpload = lazy(() => import('./pages/DataUpload'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const GISMap = lazy(() => import('./pages/GISMap'))
const ArchiveList = lazy(() => import('./pages/ArchiveList'))
const DataSync = lazy(() => import('./pages/DataSync'))
const WarehouseDashboard = lazy(() => import('./pages/WarehouseDashboard'))
const SpMaterialSummary = lazy(() => import('./pages/SpMaterialSummary'))
const SpDetailsReport = lazy(() => import('./pages/SpDetailsReport'))
const SpReport = lazy(() => import('./pages/SpReport'))
const ComReport = lazy(() => import('./pages/ComReport'))
const MsWoSLReport = lazy(() => import('./pages/MsWoSLReport'))
const MsContractKpiReport = lazy(() => import('./pages/MsContractKpiReport'))
const Overview = lazy(() => import('./pages/Overview'))
const TTWODashboard = lazy(() => import('./pages/TTWODashboard'))
const AlarmDashboard = lazy(() => import('./pages/AlarmDashboard'))
const PacketLossDashboard = lazy(() => import('./pages/PacketLossDashboard'))
const BatteryDashboard = lazy(() => import('./pages/BatteryDashboard'))
const Settings = lazy(() => import('./pages/Settings'))
const IpTrace = lazy(() => import('./pages/IpTrace'))
const IncidentOverview = lazy(() => import('./pages/IncidentOverview'))
const NurDashboard = lazy(() => import('./pages/NurDashboard'))
const MsSlaDashboard = lazy(() => import('./pages/MsSlaDashboard'))
// 只保留一半内容的直链页（同一实现的切片，见 pages/MsNurOnly.tsx / MsSlaOnly.tsx）
const MsNurOnly = lazy(() => import('./pages/MsNurOnly'))
const MsSlaOnly = lazy(() => import('./pages/MsSlaOnly'))
const AlarmManagement = lazy(() => import('./pages/AlarmManagement'))
const CxoDashboard = lazy(() => import('./pages/CxoDashboard'))
const VmaxCxoDashboard = lazy(() => import('./pages/VmaxCxoDashboard'))
const VmaxCxoDashboardDaily = lazy(() => import('./pages/VmaxCxoDashboardDaily'))
const VmaxCxoDashboard90Days = lazy(() => import('./pages/VmaxCxoDashboard90Days'))
const ImonitorScreen = lazy(() => import('./pages/ImonitorScreen'))
const EmailReports = lazy(() => import('./pages/EmailReports'))
const MwUmeDashboard = lazy(() => import('./pages/MwUmeDashboard'))
const MwRealTimeDashboard = lazy(() => import('./pages/MwRealTimeDashboard'))
const PortalLogin = lazy(() => import('./pages/PortalLogin'))
const EflowQa = lazy(() => import('./pages/EflowQa'))
const EflowFlow = lazy(() => import('./pages/EflowFlow'))
const SiteAvailability = lazy(() => import('./pages/SiteAvailability'))
const FmeRanking = lazy(() => import('./pages/FmeRanking'))
const NocAnalyst = lazy(() => import('./pages/NocAnalyst'))
const RepeatSiteDown = lazy(() => import('./pages/RepeatSiteDown'))
const RanCellsKpi = lazy(() => import('./pages/RanCellsKpi'))
const CnKpi = lazy(() => import('./pages/CnKpi'))
const NativeBoard = lazy(() => import('./pages/NativeBoard'))
const UmeInKpi = lazy(() => import('./pages/UmeInKpi'))
const Help = lazy(() => import('./pages/Help'))
const IssueFeedback = lazy(() => import('./pages/IssueFeedback'))

const { Header, Sider, Content } = Layout

/**
 * 原生看板（原 my-finebi 看板迁移）—— 除两个示例页外的全部看板。
 * key 形如 finebi_<slug>，slug 与后端 backend/services/native_catalog.py 一一对应。
 * 顺序 = 侧栏展示顺序；labelKey 在 i18n.tsx 的 nav.* 下。
 */
const FINEBI_BOARDS: { slug: string; icon: React.ReactNode; labelKey: string }[] = [
  { slug: 'metro_ring', icon: <ClusterOutlined />, labelKey: 'nav.fbMetroRing' },
  { slug: 'ipran_hq', icon: <ClusterOutlined />, labelKey: 'nav.fbIpranHq' },
  { slug: 'ipran_4region', icon: <ClusterOutlined />, labelKey: 'nav.fbIpran4Region' },
  { slug: 'fw_daily', icon: <SafetyOutlined />, labelKey: 'nav.fbFwDaily' },
  { slug: 'cn_kpi_monthly', icon: <FundProjectionScreenOutlined />, labelKey: 'nav.fbCnKpiMonthly' },
  { slug: 'daily_availability', icon: <AreaChartOutlined />, labelKey: 'nav.fbDailyAvail' },
  { slug: 'availability_daily', icon: <AreaChartOutlined />, labelKey: 'nav.fbAvailDaily' },
  { slug: 'availability_tt', icon: <AreaChartOutlined />, labelKey: 'nav.fbAvailTt' },
  { slug: 'kpi_4g', icon: <LineChartOutlined />, labelKey: 'nav.fbKpi4g' },
  { slug: 'kpi_3g', icon: <LineChartOutlined />, labelKey: 'nav.fbKpi3g' },
  { slug: 'kpi_2g', icon: <LineChartOutlined />, labelKey: 'nav.fbKpi2g' },
  { slug: 'mttr', icon: <BarChartOutlined />, labelKey: 'nav.fbMttr' },
  { slug: 'cm_dashboard', icon: <BarChartOutlined />, labelKey: 'nav.fbCmDashboard' },
  { slug: 'spare', icon: <DatabaseOutlined />, labelKey: 'nav.fbSpare' },
  { slug: 'progress', icon: <FundOutlined />, labelKey: 'nav.fbProgress' },
  { slug: 'progress_v3', icon: <FundOutlined />, labelKey: 'nav.fbProgressV3' },
]

/** page key（finebi_<slug>）→ slug，供路由 switch 反查 */
const FINEBI_PAGE_TO_SLUG: Record<string, string> = Object.fromEntries(
  FINEBI_BOARDS.map((b) => [`finebi_${b.slug}`, b.slug]),
)

type PageKey = 'overview' | 'tables' | 'upload' | 'dashboard' | 'alarm' | 'ttwo' | 'gis' | 'realtime_alarm' | 'packet_loss' | 'archive' | 'sync' | 'warehouse' | 'sp_material' | 'sp_details' | 'sp_report' | 'com_report' | 'ms_wo_sla' | 'ms_contract_kpi' | 'battery' | 'settings' | 'ip_trace' | 'incident_overview' | 'nur' | 'ms_sla' | 'ms_nur_only' | 'ms_sla_only' | 'alarmManagement' | 'cxoDashboard' | 'vmaxCxoDashboard' | 'vmaxCxoDashboard_Daily' | 'vmaxCxoDashboard_90Days' | 'imonitor' | 'email_reports' | 'mwUmeTopology' | 'mwRealTime' | 'portalLogin' | 'eflow_qa' | 'eflow_flow' | 'site_avail' | 'fme_ranking' | 'noc_analyst' | 'repeat_site_down' | 'ran_cells_kpi' | 'cn_kpi' | 'ume_in_kpi' | 'feedback' | 'help' | `finebi_${string}`

const VALID_PAGES: PageKey[] = ['overview', 'tables', 'upload', 'dashboard', 'alarm', 'ttwo', 'gis', 'realtime_alarm', 'packet_loss', 'archive', 'sync', 'warehouse', 'sp_material', 'sp_details', 'sp_report', 'com_report', 'ms_wo_sla', 'ms_contract_kpi', 'battery', 'settings', 'ip_trace', 'incident_overview', 'nur', 'ms_sla', 'ms_nur_only', 'ms_sla_only', 'alarmManagement', 'cxoDashboard', 'vmaxCxoDashboard', 'vmaxCxoDashboard_Daily', 'vmaxCxoDashboard_90Days', 'imonitor', 'email_reports', 'mwUmeTopology', 'mwRealTime', 'portalLogin', 'eflow_qa', 'eflow_flow', 'site_avail', 'fme_ranking', 'noc_analyst', 'repeat_site_down', 'ran_cells_kpi', 'cn_kpi', 'ume_in_kpi', 'feedback', 'help', ...FINEBI_BOARDS.map((b) => `finebi_${b.slug}` as PageKey)]

/* ==================== 自动刷新（大屏 / NOC 值班场景） ====================
 * 背景：各页面此前只在挂载时拉取一次数据（legacy iframe 页面同样只在 onload
 * 加载一次），大屏长期挂机后永远停留在旧数据。这里在 App 外壳层实现统一的
 * 自动刷新：到点后重挂载当前页面组件（key 变化 → useEffect 重新取数；legacy
 * 页面的 iframe 因 cacheBust 变化整体重载），对所有页面一视同仁、无需逐页改造。
 *
 * 支持「软刷新」协议的 legacy 页面（如 mw_ume_topology.html 监听 myapp-refresh）
 * 会优先在 iframe 内原地重拉数据：不重载文档、保留布局/筛选/浏览器全屏状态，
 * 大屏不闪屏。硬重挂载仅作为其余页面的兜底手段。
 *
 * 用户可在顶栏选择间隔（持久化 localStorage）；未显式选择时所有页面默认
 * 开启、每 5 分钟（AR_PAGE_DEFAULT_SEC）。为不破坏正在进行的操作，到点时若
 * 检测到「用户正忙」（正在输入、弹窗/抽屉/下拉打开、标签页在后台）则本轮
 * 跳过、下个间隔再试——空闲挂机的大屏必然按时刷新。 */
const AR_STORAGE_KEY = 'myapp_auto_refresh_sec'
/** 当前「生效」间隔（用户选择 > 本页默认 > 全局默认），供 legacy 页面显示用 */
const AR_EFFECTIVE_KEY = 'myapp_auto_refresh_effective'
const AR_OPTIONS = [0, 30, 60, 300, 600, 900, 1800]
const AR_PAGE_DEFAULT_SEC = 300 // 所有页面默认间隔（秒）
// 按页面覆盖的默认间隔：实时看板数据每 15 分钟同步一次，刷新过快无意义；
// 90 天经营看板的数据由 olib_soc_kpi_daily_sync 每天 02:20 增量入库（一天只变一次），
// 15 分钟足够及时反映最新完成日，也避免无谓查询；帮助页为静态文案，固定关闭自动刷新
const AR_PAGE_DEFAULTS: Partial<Record<PageKey, number>> = {
  mwRealTime: 900, help: 0, vmaxCxoDashboard_90Days: 900,
}
// 支持软刷新协议（postMessage myapp-refresh 原地重拉数据）的 legacy 页面
// imonitor：跨端口 iframe 无法由外壳重挂载来刷新（会整页闪白），改由页面自己
// 监听 myapp-refresh 后在 iframe 内原地重载（见 ImonitorScreen.tsx）。
const AR_SOFT_REFRESH_PAGES: PageKey[] = ['mwUmeTopology', 'mwRealTime', 'vmaxCxoDashboard_90Days', 'imonitor']

/**
 * antd 深色档 map token —— 全量对齐 vmax 90 天看板口径。
 *
 * 背景（2026-09-18）：只把 --wh-* 自研令牌换成 vmax 色值是不够的。
 * my_app 的界面由**两套互不相干的调色系统**画出来：
 *   1) 自研 CSS 层（index.css 的 --wh-* / 各页内联样式）—— 已对齐 vmax；
 *   2) antd 组件层 —— antd v6 的 darkAlgorithm 会从种子色**派生出一整套中性灰**：
 *        #141414 容器底 / #272727 表头 / #303030 描边 / #424242 描边
 *        rgba(255,255,255,.85) 正文 / rgba(255,255,255,.25) 次级文字
 *      这些灰**一点蓝都不带**，跟 vmax 的深空蓝（#02050c / #08122c / #153db0 /
 *      #f5f7ff）根本不是一个体系。实测 ?page=tables 深色下出现次数最多的颜色是
 *      rgba(255,255,255,.85)×2091、#303030×1180、#272727×626 —— 也就是说那张
 *      表格页**基本就是 antd 默认深色主题**，而不是 vmax。
 *
 * 这就是「?page=sync 深色 ≠ ?page=vmaxCxoDashboard_90Days 深色」的主因：
 * 后者是内嵌的独立 HTML（CSS 100% 是 vmax），前者是 React + antd。
 *
 * 因此这里把 antd 的 map token 也钉到 vmax 值上，让两套体系同源。
 * 只影响深色档；浅色档继续用 antd 原值。
 *
 * 注意：antd v6 生成的是静态 CSS-in-JS（不是 CSS 变量模式），且规则用 :where()
 * 包裹（特异性 0），所以 index.css 里已有的 .ant-* 覆盖仍然会赢 —— 两者不冲突。
 */
const VMAX_DARK_TOKEN = {
  /* 种子色（antd 由这些派生 hover / active / bg 等） */
  colorPrimary: '#00d9ff',
  colorInfo: '#258cff',
  colorSuccess: '#0bc78c',
  colorWarning: '#f6cf00',
  colorError: '#ff5c6c',
  colorLink: '#7fd2ee',

  /* 背景四层：页面 / 容器（卡片·表格·输入框）/ 浮层（弹窗·下拉·抽屉）/ 聚光（Tooltip） */
  colorBgBase: '#02050c',
  colorBgLayout: '#02050c',
  colorBgContainer: '#08122c',
  colorBgElevated: '#070d31',
  colorBgSpotlight: '#0a1730',
  colorBgMask: 'rgba(2, 5, 12, 0.65)',

  /* 文字四层 */
  colorText: '#f5f7ff',
  colorTextSecondary: '#aebbd4',
  colorTextTertiary: '#6f8cb4',
  colorTextQuaternary: '#4a5f7d',
  colorTextHeading: '#f5f7ff',
  colorTextDescription: '#aebbd4',
  colorTextPlaceholder: '#6f8cb4',
  colorTextDisabled: '#4a5f7d',

  /* 描边：主描边用 vmax 的实心宝蓝，次级 / 分割线用暗一档的 #173158 */
  colorBorder: '#153db0',
  colorBorderSecondary: '#173158',
  colorSplit: '#173158',

  /* 填充：hover / active / 标签底 / 开关 —— vmax 是「蓝色叠加」而不是「白色叠加」 */
  colorFill: 'rgba(37, 140, 255, 0.16)',
  colorFillSecondary: 'rgba(37, 140, 255, 0.14)',
  colorFillTertiary: 'rgba(37, 140, 255, 0.10)',
  colorFillQuaternary: 'rgba(37, 140, 255, 0.06)',
} as const

function arReadOverride(): number | null {
  try {
    const raw = localStorage.getItem(AR_STORAGE_KEY)
    if (raw == null) return null
    const v = parseInt(raw, 10)
    return AR_OPTIONS.includes(v) ? v : null
  } catch { return null }
}

/** 是否处于「不应打扰」状态：用户正在输入 / 弹层打开 / 标签页在后台 */
function arInteractionInProgress(): boolean {
  if (document.hidden) return true
  try {
    // 正在表单/搜索框输入：重挂载会丢焦点与未提交内容，本轮跳过
    const ae = document.activeElement as HTMLElement | null
    if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return true
    // antd Modal/ImagePreview 等弹层会锁定 body 滚动；Drawer/Select/DatePicker 打开时有 open 类
    if (document.body && document.body.style.overflow === 'hidden') return true
    if (document.querySelector('.ant-drawer-open, .ant-select-open, .ant-picker-open')) return true
  } catch { /* noop */ }
  return false
}

/* ==================== 侧边栏宽度（可拖拽） ====================
 * 菜单项名称长短差异很大（中文「eFlow 知识库」vs 英文「CXO Dashboard」），
 * 固定 200px 总有一侧不够用/太浪费。这里允许拖动右边缘调宽，宽度持久化到
 * localStorage；双击或键盘操作可复位/微调。移动端侧栏是浮层抽屉（宽度由
 * 视口决定），不启用拖拽。 */
const SIDER_W_KEY = 'myapp_sider_width'
const SIDER_W_MIN = 176
const SIDER_W_MAX = 420

/** 默认宽度：读 CSS 令牌 --wh-sider-width（12.5rem）并按根字号换算。
 *  本项目根字号是 18px → 12.5rem = 225px；硬编码 200 会让默认侧栏莫名变窄。 */
function defaultSiderWidth(): number {
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue('--wh-sider-width').trim()
    const num = parseFloat(raw)
    if (!Number.isFinite(num)) return 225
    if (raw.endsWith('rem')) {
      const root = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
      return Math.round(num * root)
    }
    return Math.round(num) // px 等绝对单位
  } catch { return 225 }
}

/** 夹紧到 [MIN, MAX]，并保证不超视口 42%（窄屏下不至于把内容挤没） */
function clampSiderWidth(v: number): number {
  const byViewport = Math.floor(window.innerWidth * 0.42)
  const max = Math.max(SIDER_W_MIN, Math.min(SIDER_W_MAX, byViewport))
  return Math.min(max, Math.max(SIDER_W_MIN, Math.round(v)))
}

function readSiderWidth(): number {
  const fallback = defaultSiderWidth()
  try {
    const raw = localStorage.getItem(SIDER_W_KEY)
    if (raw == null) return fallback
    const v = parseInt(raw, 10)
    return Number.isFinite(v) ? clampSiderWidth(v) : fallback
  } catch { return fallback }
}

/* ==================== 侧边栏菜单结构（全局共享 + 仅本机可改） ====================
 * 结构最初写死在 menuItems 里（改个目录名要改代码 + 重新构建），后来改成各浏览器
 * localStorage（A 改了目录名 B 看不到，同一套系统两套导航）。现在：
 *   - **服务端唯一真相源**：GET /api/ui/menu-layout，所有访问者读同一份；
 *   - **只有本机能改**：PUT/DELETE 走 require_protected（回环直放，远程 403），
 *     前端用返回的 editable 决定是否显示编辑入口；
 *   - 浏览器只留一份本地镜像（首屏不闪），随后被服务端返回覆盖。
 * 无论哪种来源都过 normalizeMenuLayout：过滤非法页面、去重，并补回代码里新增的
 * 目录与页面（老配置不会把新页面藏起来，也不会把新页面全堆进最后一个目录）。 */
type MenuGroup = { key: string; label?: string; hidden?: boolean; items: PageKey[] }
type MenuLayout = { v: number; groups: MenuGroup[]; itemLabels?: Partial<Record<PageKey, string>> }

const MENU_LAYOUT_CACHE_KEY = 'myapp_menu_layout_cache_v1'
/** 旧的「每浏览器一份」布局键，仅用于一次性导入到服务端 */
const MENU_LAYOUT_LEGACY_KEY = 'myapp_menu_layout_v1'
/** 目录的「收起」状态：纯粹是当前浏览器的阅读偏好（像侧栏宽度），不进服务端 */
const MENU_COLLAPSED_KEY = 'myapp_menu_collapsed_groups'

function readCollapsedGroups(): string[] {
  try {
    const raw = localStorage.getItem(MENU_COLLAPSED_KEY)
    const arr = raw ? JSON.parse(raw) : null
    return Array.isArray(arr) ? arr.filter((k): k is string => typeof k === 'string') : []
  } catch { return [] }
}

/** 页面元数据：图标 + i18n 默认名。菜单渲染与编辑器共用这一份真相源 */
const PAGE_META: Record<PageKey, { icon: ReactNode; labelKey: string }> = {
  sync: { icon: <SyncOutlined />, labelKey: 'nav.sync' },
  email_reports: { icon: <MailOutlined />, labelKey: 'nav.emailReports' },
  eflow_qa: { icon: <BookOutlined />, labelKey: 'nav.eflowQa' },
  eflow_flow: { icon: <ApartmentOutlined />, labelKey: 'nav.eflowFlow' },
  alarm: { icon: <AlertOutlined />, labelKey: 'nav.alarm' },
  ttwo: { icon: <BarChartOutlined />, labelKey: 'nav.ttwo' },
  nur: { icon: <LineChartOutlined />, labelKey: 'nav.nur' },
  ms_sla: { icon: <FundOutlined />, labelKey: 'nav.msSla' },
  // 只保留一半内容的直链页：图标沿用其数据源看板，便于在侧栏一眼认出父子关系
  ms_nur_only: { icon: <LineChartOutlined />, labelKey: 'nav.msNurOnly' },
  ms_sla_only: { icon: <FundOutlined />, labelKey: 'nav.msSlaOnly' },
  site_avail: { icon: <SafetyOutlined />, labelKey: 'nav.siteAvail' },
  fme_ranking: { icon: <BarChartOutlined />, labelKey: 'nav.fmeRanking' },
  noc_analyst: { icon: <TeamOutlined />, labelKey: 'noc.navLabel' },
  repeat_site_down: { icon: <DisconnectOutlined />, labelKey: 'nav.repeatSiteDown' },
  ran_cells_kpi: { icon: <AreaChartOutlined />, labelKey: 'nav.ranCellsKpi' },
  cn_kpi: { icon: <FundProjectionScreenOutlined />, labelKey: 'nav.cnKpi' },
  ume_in_kpi: { icon: <DotChartOutlined />, labelKey: 'nav.umeInKpi' },
  cxoDashboard: { icon: <PieChartOutlined />, labelKey: 'nav.cxoDashboard' },
  vmaxCxoDashboard: { icon: <DashboardOutlined />, labelKey: 'nav.vmaxCxoDashboard' },
  vmaxCxoDashboard_Daily: { icon: <LineChartOutlined />, labelKey: 'nav.vmaxCxoDashboardDaily' },
  vmaxCxoDashboard_90Days: { icon: <FundOutlined />, labelKey: 'nav.vmaxCxoDashboard90Days' },
  imonitor: { icon: <DesktopOutlined />, labelKey: 'nav.imonitor' },
  alarmManagement: { icon: <AlertOutlined />, labelKey: 'nav.alarmManagement' },
  incident_overview: { icon: <FileSearchOutlined />, labelKey: 'nav.incidentOverview' },
  mwUmeTopology: { icon: <ApartmentOutlined />, labelKey: 'nav.mwUmeTopology' },
  mwRealTime: { icon: <FieldTimeOutlined />, labelKey: 'nav.mwRealTime' },
  gis: { icon: <GlobalOutlined />, labelKey: 'nav.gis' },
  realtime_alarm: { icon: <AlertOutlined />, labelKey: 'nav.realtimeAlarm' },
  packet_loss: { icon: <DisconnectOutlined />, labelKey: 'nav.packetLoss' },
  battery: { icon: <ThunderboltOutlined />, labelKey: 'nav.battery' },
  ip_trace: { icon: <AimOutlined />, labelKey: 'nav.ipTrace' },
  overview: { icon: <BarChartOutlined />, labelKey: 'nav.overview' },
  tables: { icon: <TableOutlined />, labelKey: 'nav.tables' },
  upload: { icon: <UploadOutlined />, labelKey: 'nav.upload' },
  archive: { icon: <HistoryOutlined />, labelKey: 'nav.archive' },
  dashboard: { icon: <DashboardOutlined />, labelKey: 'nav.dashboard' },
  warehouse: { icon: <AppstoreOutlined />, labelKey: 'nav.sp' },
  sp_material: { icon: <DatabaseOutlined />, labelKey: 'nav.spMaterial' },
  sp_details: { icon: <FileSearchOutlined />, labelKey: 'nav.spDetails' },
  sp_report: { icon: <BarChartOutlined />, labelKey: 'nav.spReport' },
  com_report: { icon: <FundOutlined />, labelKey: 'nav.comReport' },
  ms_wo_sla: { icon: <FileDoneOutlined />, labelKey: 'nav.msWoSl' },
  ms_contract_kpi: { icon: <SolutionOutlined />, labelKey: 'nav.msContractKpi' },
  settings: { icon: <SettingOutlined />, labelKey: 'nav.settings' },
  portalLogin: { icon: <LoginOutlined />, labelKey: 'nav.portalLogin' },
  feedback: { icon: <MessageOutlined />, labelKey: 'nav.feedback' },
  help: { icon: <QuestionCircleOutlined />, labelKey: 'nav.help' },
  // 原生看板（原 my-finebi 看板迁移）：由 FINEBI_BOARDS 统一注入，避免两处维护
  ...Object.fromEntries(FINEBI_BOARDS.map((b) => [
    `finebi_${b.slug}`,
    { icon: b.icon, labelKey: b.labelKey },
  ])),
}

/** 默认目录结构（key 稳定，用于旧布局兼容与默认名称回退） */
const DEFAULT_GROUPS: { key: string; labelKey: string; items: PageKey[] }[] = [
  { key: 'grp_sync', labelKey: 'nav.grp.sync', items: ['sync', 'email_reports', 'eflow_qa', 'eflow_flow'] },
  {
    key: 'grp_monitor',
    labelKey: 'nav.grp.monitor',
    items: ['alarm', 'ttwo', 'nur', 'ms_nur_only', 'ms_sla', 'ms_sla_only', 'ms_wo_sla', 'ms_contract_kpi', 'site_avail', 'fme_ranking', 'noc_analyst', 'repeat_site_down', 'ran_cells_kpi', 'cn_kpi', 'ume_in_kpi', 'cxoDashboard', 'vmaxCxoDashboard', 'vmaxCxoDashboard_Daily', 'vmaxCxoDashboard_90Days', 'imonitor', 'alarmManagement', 'incident_overview'],
  },
  {
    key: 'grp_network',
    labelKey: 'nav.grp.network',
    items: ['mwUmeTopology', 'mwRealTime', 'gis', 'realtime_alarm', 'packet_loss', 'battery', 'ip_trace'],
  },
  {
    key: 'grp_analysis',
    labelKey: 'nav.grp.analysis',
    items: ['overview', 'tables', 'upload', 'archive', 'dashboard', 'warehouse', 'sp_material', 'sp_details', 'sp_report', 'com_report'],
  },
  // 原生看板（原 my-finebi 看板逐个迁移而来，不依赖 my-finebi 进程）
  {
    key: 'grp_finebi',
    labelKey: 'nav.grp.finebi',
    items: FINEBI_BOARDS.map((b) => `finebi_${b.slug}` as PageKey),
  },
  { key: 'grp_system', labelKey: 'nav.grp.system', items: ['settings', 'portalLogin', 'feedback', 'help'] },
]

/** 页面 → 它「默认」所属的目录 key。
 *  新增页面时用它把页面放回正确的目录，而不是无脑塞进最后一个目录
 *  （见 normalizeMenuLayout 第 2 步）。 */
const DEFAULT_GROUP_OF: Partial<Record<PageKey, string>> = {}
for (const g of DEFAULT_GROUPS) for (const k of g.items) DEFAULT_GROUP_OF[k] = g.key

function defaultMenuLayout(): MenuLayout {
  return { v: 1, groups: DEFAULT_GROUPS.map(g => ({ key: g.key, items: [...g.items] })) }
}

/** 内置目录的 i18n 名称键；用户新建的目录返回 undefined */
function builtinGroupLabelKey(key: string): string | undefined {
  return DEFAULT_GROUPS.find(g => g.key === key)?.labelKey
}

/** 校验 + 归一化菜单结构（服务端数据 / 本地镜像 / 旧 localStorage 都走这里）。
 *  返回 null 表示结构不可用，由调用方回落默认结构。
 *  - 过滤非页面键、跨目录去重；
 *  - 代码里新增的页面并入最后一个目录（否则新页面在菜单里「失踪」）；
 *  - 空目录合法保留（用户新建后先在侧栏看到它，再往里搬页面）。 */
function normalizeMenuLayout(raw: unknown): MenuLayout | null {
  const obj = raw as MenuLayout | null | undefined
  if (!obj || typeof obj !== 'object' || !Array.isArray(obj.groups) || !obj.groups.length) return null
  const seen = new Set<PageKey>()
  const groups: MenuGroup[] = []
  for (const g of obj.groups) {
    if (!g || typeof g.key !== 'string' || !Array.isArray(g.items)) continue
    const items = g.items.filter((k): k is PageKey =>
      (VALID_PAGES as string[]).includes(k as unknown as string) && !seen.has(k))
    items.forEach(k => seen.add(k))
    groups.push({
      key: g.key,
      label: typeof g.label === 'string' && g.label.trim() ? g.label : undefined,
      hidden: g.hidden === true ? true : undefined,
      items,
    })
  }
  if (!groups.length) return null

  // 1) 补回「代码里新增、但保存的布局里还没有」的内置目录。
  //    并把该目录默认该有的页面从别的目录**收回来** —— 这些页面只可能是被
  //    下面第 2 步的旧逻辑（新页面一律并入最后一个目录）塞进去的，
  //    不可能是用户有意搬动，因为目录本身就是这次才有的。
  const present = new Set(groups.map(g => g.key))
  DEFAULT_GROUPS.forEach((dg, idx) => {
    if (present.has(dg.key)) return
    present.add(dg.key)
    const members = dg.items.filter(k => seen.has(k))
    if (members.length) {
      const claim = new Set<PageKey>(members)
      for (const g of groups) g.items = g.items.filter(k => !claim.has(k))
    }
    groups.splice(Math.min(idx, groups.length), 0, { key: dg.key, items: [...members] })
  })

  // 2) 仍然没出现在任何目录里的新页面：并入它「默认所属」的目录；
  //    没有默认归属时才退回最后一个目录（保持旧行为，不至于让页面失踪）。
  const byKey = new Map(groups.map(g => [g.key, g]))
  const fresh = (VALID_PAGES as PageKey[]).filter(k => !seen.has(k))
  for (const k of fresh) {
    const target = byKey.get(DEFAULT_GROUP_OF[k] ?? '') ?? groups[groups.length - 1]
    target.items.push(k)
    seen.add(k)
  }

  const itemLabels = obj.itemLabels && typeof obj.itemLabels === 'object' ? obj.itemLabels : undefined
  return { v: 1, groups, itemLabels }
}

/** 从 localStorage 读一份布局（可用于镜像或旧键迁移） */
function readStoredMenuLayout(key: string): MenuLayout | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? normalizeMenuLayout(JSON.parse(raw)) : null
  } catch { return null }
}

function writeMenuCache(layout: MenuLayout) {
  try { localStorage.setItem(MENU_LAYOUT_CACHE_KEY, JSON.stringify(layout)) } catch { /* noop */ }
}

/** 转成接口 payload（内部结构 -> 后端宽松结构） */
function toMenuPayload(layout: MenuLayout): MenuLayoutPayload {
  return {
    v: 1,
    groups: layout.groups.map(g => ({
      key: g.key,
      label: g.label,
      hidden: g.hidden,
      items: g.items as string[],
    })),
    itemLabels: layout.itemLabels as Record<string, string> | undefined,
  }
}

/**
 * 嵌入（embed）模式解析：URL 带 ?embed=1（或 ?embed=true / ?layout=bare）时，
 * 只渲染当前页面本体，隐藏侧栏 / Header / 跳转链接等一切外壳元素，
 * 供门户 iframe 或大屏单模块嵌入使用。
 * ⚠️ 刻意不用「有无 ?page= 参数」来判断 —— ?page= 是应用内导航的常态 URL，
 *    且 /myapp/ 打开后会被 replaceState 归一化成 ?page=sync；
 *    若拿它当开关，侧栏会在进入同步页的下一秒消失且再也点不回来。
 */
function readEmbedMode(): boolean {
  try {
    const sp = new URLSearchParams(window.location.search)
    return sp.get('embed') === '1' || sp.get('embed') === 'true' || sp.get('layout') === 'bare'
  } catch { return false }
}

/**
 * 直链 bare（仅模块）模式：URL 「首次加载时」显式带 ?page= 即只渲染该模块，
 * 隐藏侧栏 / Header 等外壳元素，供门户/大屏深链单模块嵌入使用。
 * 与 embedMode 的区别：bare 会被应用内导航（navigateTo）主动关闭，
 * 避免在左侧菜单里点一下就把外壳「点没」，故不能并入 readEmbedMode（后者
 * 在 popstate 里按 URL 重新读取，而 bare 需要保持应用内导航后的外壳状态）。
 */
function readBareModule(): boolean {
  try {
    return new URLSearchParams(window.location.search).get('page') != null
  } catch { return false }
}

function AppContent() {
  // 支持 ?page=xxx 直链定位（右键菜单「在新标签页打开」使用），非法值回退到默认页
  const [currentPage, setCurrentPage] = useState<PageKey>(() => {
    const p = new URLSearchParams(window.location.search).get('page')
    // 历史别名：?page=tt_q → eflow_qa（eFlow 知识库）
    const key = p === 'tt_q' ? 'eflow_qa' : p
    return key && (VALID_PAGES as string[]).includes(key) ? (key as PageKey) : 'sync'
  })
  // 嵌入模式初值随 URL 一次性求值；浏览器前进/后退（popstate）时重新求值（见下方 onPopState）
  const [embedMode, setEmbedMode] = useState<boolean>(readEmbedMode)
  // 直链 bare（仅模块）模式：URL 首次加载带 ?page= 即隐藏外壳。与应用内导航联动，
  // navigateTo 会置 false；popstate 不重读，保证外壳内前进/后退不丢外壳。
  const [bareModule, setBareModule] = useState<boolean>(readBareModule)
  // 会话失效 / 未登录访问数据接口 → 展示“请通过统一门户登录”引导（uniplam 鉴权适配）
  const [authGate, setAuthGate] = useState(false)
  // 启动鉴权引导（?t= 换会话 / 免登录探测 / 会话确认）是否已结束：
  // 结束前不挂载业务页面，避免页面在会话 Cookie 落地前抢跑数据接口拿到 401
  const [bootDone, setBootDone] = useState(false)
  // 侧边栏默认隐藏（完全收起、不占空间），展开/收起偏好持久化到 localStorage
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      // 默认隐藏：仅当用户曾明确展开（存 '0'）时才展开
      return localStorage.getItem('myapp_sider_collapsed') !== '0'
    } catch { return true }
  })
  const toggleSider = useCallback(() => {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('myapp_sider_collapsed', next ? '1' : '0') } catch { /* noop */ }
      return next
    })
  }, [])
  /** 关闭侧栏（遮罩 / X / Esc / 移动端选中菜单共用），与展开一样持久化偏好 */
  const closeSider = useCallback(() => {
    setCollapsed(true)
    try { localStorage.setItem('myapp_sider_collapsed', '1') } catch { /* noop */ }
  }, [])

  // ===== 侧边栏宽度拖拽（详见文件顶部 clampSiderWidth 说明） =====
  const [siderWidth, setSiderWidth] = useState<number>(readSiderWidth)
  const [resizing, setResizing] = useState(false)
  const resizeStartX = useRef(0)      // 按下时指针 x
  const resizeStartW = useRef(defaultSiderWidth()) // 按下时侧栏宽度
  const siderWidthRef = useRef(siderWidth)
  useEffect(() => { siderWidthRef.current = siderWidth }, [siderWidth])

  /** 应用并持久化宽度（键盘微调 / 双击复位走这里） */
  const applySiderWidth = useCallback((v: number) => {
    const next = clampSiderWidth(v)
    siderWidthRef.current = next
    setSiderWidth(next)
    try { localStorage.setItem(SIDER_W_KEY, String(next)) } catch { /* noop */ }
  }, [])

  const startSiderResize = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    // 移动端抽屉是浮层（宽度由视口决定），手柄根本不渲染，这里只做兜底
    if (window.innerWidth < 768) return
    // ⚠️ 这里不能 preventDefault()：Chrome 在 pointerdown 上被 preventDefault 后
    // 会抑制与之兼容的 mousedown/click/dblclick —— 双击复位将永远收不到事件。
    // 拖拽期的选中/光标问题由 body 上的 .wh-sider-resizing + 遮罩处理。
    try { window.getSelection()?.removeAllRanges() } catch { /* noop */ }
    resizeStartX.current = e.clientX
    resizeStartW.current = siderWidthRef.current
    setResizing(true)
  }, [])

  // 拖拽期间在 window 上监听：指针移出窗口/滑到 iframe 上方也不会丢事件
  useEffect(() => {
    if (!resizing) return
    const onMove = (e: PointerEvent) => {
      const next = clampSiderWidth(resizeStartW.current + (e.clientX - resizeStartX.current))
      // 同步写 ref：setState 是异步的，松手时的 finish() 若读 ref 会拿到上一帧的值
      siderWidthRef.current = next
      setSiderWidth(next)
    }
    const finish = () => {
      setResizing(false)
      // 松手时才落盘，避免拖拽过程中高频写 localStorage
      try { localStorage.setItem(SIDER_W_KEY, String(siderWidthRef.current)) } catch { /* noop */ }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    document.body.classList.add('wh-sider-resizing')
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      document.body.classList.remove('wh-sider-resizing')
    }
  }, [resizing])

  const onResizerKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 32 : 8
    if (e.key === 'ArrowLeft') { e.preventDefault(); applySiderWidth(siderWidthRef.current - step) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); applySiderWidth(siderWidthRef.current + step) }
    else if (e.key === 'Home' || e.key === 'Enter') { e.preventDefault(); applySiderWidth(defaultSiderWidth()) }
  }, [applySiderWidth])

  // 窗口变窄时把宽度收回到合法范围，避免侧栏把内容区挤没
  useEffect(() => {
    const onWinResize = () => setSiderWidth(w => clampSiderWidth(w))
    window.addEventListener('resize', onWinResize)
    return () => window.removeEventListener('resize', onWinResize)
  }, [])
  // ===== 侧边栏菜单（服务端唯一真相源，仅本机可改；详见文件顶部说明）=====
  const [menuLayout, setMenuLayout] = useState<MenuLayout>(
    () => readStoredMenuLayout(MENU_LAYOUT_CACHE_KEY) ?? defaultMenuLayout())
  const [menuEditable, setMenuEditable] = useState(false)
  const [menuQuery, setMenuQuery] = useState('')
  /** 被收起的目录 key（跨刷新保留，纯本地阅读偏好） */
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(readCollapsedGroups)
  const [menuEditOpen, setMenuEditOpen] = useState(false)
  const [menuSaveState, setMenuSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [menuSaveError, setMenuSaveError] = useState('')
  const menuSaveTimer = useRef<number | null>(null)
  const menuPending = useRef<MenuLayout | null>(null)

  /** 把待保存的改动真正发给服务端（关闭弹窗 / 卸载 / 防抖到点都会调） */
  const flushMenuSave = useCallback(() => {
    if (menuSaveTimer.current) {
      window.clearTimeout(menuSaveTimer.current)
      menuSaveTimer.current = null
    }
    const next = menuPending.current
    if (!next) return
    menuPending.current = null
    setMenuSaveState('saving')
    saveMenuLayout(toMenuPayload(next))
      .then(() => { setMenuSaveState('saved'); setMenuSaveError('') })
      .catch((e: any) => {
        setMenuSaveState('error')
        setMenuSaveError(String(e?.response?.data?.detail || e?.message || e))
      })
  }, [])

  /** 应用菜单结构：本地即时生效（+写镜像），再防抖 600ms 落盘到服务端。
   *  仅本机可写；非本机（editable=false）只改本地视图，不会发请求。 */
  const updateMenuLayout = useCallback((next: MenuLayout) => {
    setMenuLayout(next)
    writeMenuCache(next)
    if (!menuEditable) return
    menuPending.current = next
    if (menuSaveTimer.current) window.clearTimeout(menuSaveTimer.current)
    menuSaveTimer.current = window.setTimeout(flushMenuSave, 600)
  }, [menuEditable, flushMenuSave])

  // 首屏拉服务端结构（真相源）；本地镜像只负责「不闪」
  useEffect(() => {
    let alive = true
    getMenuLayout().then((res) => {
      if (!alive) return
      const data = res.data || {}
      setMenuEditable(!!data.editable)
      const server = normalizeMenuLayout(data.layout)
      if (server) {
        setMenuLayout(server)
        writeMenuCache(server)
        return
      }
      // 服务端**明确**没有配置（layout=null）：回落内置默认结构，并刷新本地镜像。
      // ⚠️ 不能继续沿用旧镜像 —— 否则管理员点「恢复默认」删掉配置后，
      //    其他浏览器会一直拿缓存里的旧结构，永远看不到「已恢复默认」。
      // （网络失败走下面的 catch，那种情况才应该保留镜像。）
      const legacy = data.editable ? readStoredMenuLayout(MENU_LAYOUT_LEGACY_KEY) : null
      const next = legacy ?? defaultMenuLayout()
      setMenuLayout(next)
      writeMenuCache(next)
      // 本机可把旧版「每浏览器一份」的布局一次性导入服务端，避免用户之前改的白做
      if (legacy) {
        saveMenuLayout(toMenuPayload(legacy)).catch(() => { /* 迁移失败不影响使用 */ })
        try { localStorage.removeItem(MENU_LAYOUT_LEGACY_KEY) } catch { /* noop */ }
      }
    }).catch(() => setMenuEditable(false))  // 后端不可用：只读，不误报可编辑
    return () => { alive = false }
  }, [])

  // 卸载/关页面时补交未落盘的改动，避免「刚改完就刷新」丢改动
  useEffect(() => () => { flushMenuSave() }, [flushMenuSave])

  const navigateTo = useCallback((page: PageKey) => {
    // 应用内菜单导航 = 在外壳内浏览：显式退出直链 bare 模式，
    // 避免点菜单把外壳隐藏掉（bare 只在首次加载的 URL 带 ?page= 时进入）。
    setBareModule(false)
    setCurrentPage(page)
    const url = new URL(window.location.href)
    // 同一页面重复点击不产生历史记录，避免后退键要按很多次
    if (url.searchParams.get('page') === page) return
    url.searchParams.set('page', page)
    window.history.pushState({ page }, '', url)
  }, [])
  const { t, locale, toggleLocale } = useI18n()
  const { isDark, toggle } = useTheme()
  const isMobile = useIsMobile()

  // 移动端抽屉：侧栏浮在内容之上时，Esc / 遮罩 / X 三条关闭路径都要可用，
  // 并且要锁住背景滚动、把焦点关进抽屉、关闭后再还给汉堡按钮。
  const drawerOpen = isMobile && !collapsed
  // 统一「外壳隐藏」开关：embedMode（?embed=1）或 直链 bare（?page=xxx）任一命中，
  // 即不渲染侧栏/Header 等外壳元素、模块占满视口。
  const shellHidden = embedMode || bareModule
  const toggleBtnRef = useRef<HTMLButtonElement | null>(null)
  const closeBtnRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!drawerOpen) return
    closeBtnRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      closeSider()
      // 焦点还给汉堡按钮，否则 Esc 关闭后焦点停在已卸载的按钮上、Tab 从页首重来
      requestAnimationFrame(() => toggleBtnRef.current?.focus())
    }
    document.addEventListener('keydown', onKey)
    // 背景锁定：在抽屉里滚动菜单时，后面的页面不应跟着滚
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [drawerOpen, closeSider])

  // ===== 自动刷新：状态 + 定时器（详见文件顶部说明） =====
  // 用户显式选择（含 0=关闭）持久化；null 表示未选择，所有页面默认 5 分钟
  const [arOverride, setArOverride] = useState<number | null>(arReadOverride)
  const [refreshTick, setRefreshTick] = useState(0)
  const [arSpin, setArSpin] = useState(false)
  const arSpinTimer = useRef<number | null>(null)
  const arEffective = arOverride ?? AR_PAGE_DEFAULTS[currentPage] ?? AR_PAGE_DEFAULT_SEC

  const performAutoRefresh = useCallback(() => {
    // 后台标签 / 弹窗打开：本轮跳过，避免打断交互与无谓请求
    if (arInteractionInProgress()) return
    // 软刷新：向所有 iframe 广播协议，支持者（mw_ume_topology.html 等）在
    // 文档内原地重拉数据 —— 不闪屏、不退出浏览器全屏、保留内部筛选状态
    document.querySelectorAll('iframe').forEach((f) => {
      try { f.contentWindow?.postMessage({ __type: 'myapp-refresh' }, '*') } catch { /* ignore */ }
    })
    setArSpin(true)
    if (arSpinTimer.current) window.clearTimeout(arSpinTimer.current)
    arSpinTimer.current = window.setTimeout(() => setArSpin(false), 800)
    // 硬刷新兜底：重挂载当前页面（useEffect 重取数 / iframe 因 cacheBust 重载）。
    // 软刷新页与元素级全屏中不做重挂载（重挂载会移除 iframe 导致全屏退出）
    if (AR_SOFT_REFRESH_PAGES.includes(currentPage)) return
    if (document.fullscreenElement) return
    invalidateCache() // 绕过 cachedGet 的 30s 前端缓存，确保拿到新数据
    setRefreshTick(x => x + 1)
  }, [currentPage])

  useEffect(() => {
    if (!arEffective) return
    const id = window.setInterval(performAutoRefresh, arEffective * 1000)
    return () => window.clearInterval(id)
  }, [arEffective, performAutoRefresh])

  // 把「当前生效的刷新间隔」公开给 legacy 页面（自刷新页要在界面上如实显示倒计时口径，
  // 不能各自硬编码一份默认值 —— 有效值来自 用户选择 > 本页默认 > 全局默认）。
  useEffect(() => {
    try { localStorage.setItem(AR_EFFECTIVE_KEY, String(arEffective)) } catch { /* noop */ }
  }, [arEffective])

  useEffect(() => () => { if (arSpinTimer.current) window.clearTimeout(arSpinTimer.current) }, [])

  const changeAutoRefresh = useCallback((v: number) => {
    setArOverride(v)
    try { localStorage.setItem(AR_STORAGE_KEY, String(v)) } catch { /* noop */ }
  }, [])
  const arLabel = useCallback((sec: number) =>
    sec <= 0 ? t('ar.off') : sec < 60 ? `${sec} ${t('ar.sec')}` : `${sec / 60} ${t('ar.min')}`
  , [t])

  /** 目录显示名：用户自定义 > 内置目录的 i18n 名 > key 兜底 */
  const groupLabelText = useCallback((g: MenuGroup) => {
    if (g.label) return g.label
    const k = builtinGroupLabelKey(g.key)
    return k ? t(k) : g.key
  }, [t])

  /** 页面显示名：用户自定义 > i18n 默认名 */
  const itemLabelText = useCallback((k: PageKey) =>
    menuLayout.itemLabels?.[k] || t(PAGE_META[k].labelKey)
  , [menuLayout, t])

  // 按当前布局展开的页面顺序（右键菜单兜底映射、页面标题、搜索都依赖它）
  const flatMenuItems = useMemo(
    () => menuLayout.groups.flatMap(g => g.items).map(k => ({ key: k, label: itemLabelText(k) })),
    [menuLayout, itemLabelText],
  )

  /** 侧栏里实际渲染的目录：隐藏的目录整个不出现（页面仍可通过 ?page= 直达） */
  const visibleGroups = useMemo(() => menuLayout.groups.filter(g => !g.hidden), [menuLayout])
  /** 已隐藏的目录：侧栏底部「已隐藏目录」区把它们列出来，点一下就恢复 ——
   *  否则一旦隐藏就再也找不到入口（只能去弹窗里翻），是个陷阱。 */
  const hiddenGroups = useMemo(() => menuLayout.groups.filter(g => g.hidden), [menuLayout])

  const menuSearching = menuQuery.trim() !== ''

  /** 侧栏菜单：无搜索词 = 全量；有搜索词 = 按目录名/页面名/页面 key 过滤（目录名命中则整组保留）。
   *  目录标题做成了可点击的「折叠头部」（见 .wh-menu-group-head）：
   *    点标题 → 收起/展开该目录；右侧眼睛 → 隐藏整个目录（仅本机可编辑时出现）。
   *  搜索时**强制展开** —— 否则命中的页面藏在收起的分组里，等于搜不到。 */
  const menuItems = useMemo(() => {
    const q = menuQuery.trim().toLowerCase()
    const build = (g: MenuGroup, items: PageKey[]) => {
      const collapsed = !menuSearching && collapsedGroups.includes(g.key)
      return {
        key: g.key,
        type: 'group' as const,
        label: (
          <div className="wh-menu-group-head">
            {/* 用 data-* + 容器上的事件委托触发，避免把 handler 塞进 memo 造成无谓重建 */}
            <button
              type="button"
              className="wh-menu-group-toggle"
              data-wh-group={g.key}
              data-wh-group-act="collapse"
              aria-expanded={!collapsed}
              title={collapsed ? t('menu.expandGroup') : t('menu.collapseGroup')}
            >
              <span className="wh-menu-group-name">{groupLabelText(g)}</span>
              {collapsed && <span className="wh-menu-group-count">{items.length}</span>}
            </button>
            {menuEditable && (
              <button
                type="button"
                className="wh-menu-group-eye"
                data-wh-group={g.key}
                data-wh-group-act="hide"
                aria-label={t('menu.hide')}
                title={t('menu.hide')}
              >
                <EyeOutlined />
              </button>
            )}
          </div>
        ),
        children: collapsed ? [] : items.map(k => ({ key: k, icon: PAGE_META[k].icon, label: itemLabelText(k) })),
      }
    }
    if (!q) return visibleGroups.map(g => build(g, g.items))
    return visibleGroups
      .map(g => {
        const groupHit = `${groupLabelText(g)} ${g.key}`.toLowerCase().includes(q)
        const items = groupHit
          ? g.items
          : g.items.filter(k => `${itemLabelText(k)} ${k}`.toLowerCase().includes(q))
        return build(g, items)
      })
      .filter(g => g.children.length)
  }, [visibleGroups, collapsedGroups, menuSearching, menuQuery, menuEditable, groupLabelText, itemLabelText, t])

  const menuNoMatch = menuSearching && menuItems.length === 0
  /** 命中页面总数（提示「找到 N 个页面」） */
  const menuMatchCount = useMemo(
    () => menuItems.reduce((n, g) => n + (g.children?.length || 0), 0),
    [menuItems],
  )
  /** 回车直接跳到第一个命中页面 */
  const menuFirstMatch = useMemo(() => {
    if (!menuSearching) return undefined
    const first = menuItems[0]?.children?.[0] as { key?: PageKey } | undefined
    return first?.key
  }, [menuSearching, menuItems])

  // ===== 菜单编辑器操作 =====
  const renameGroup = useCallback((key: string, label: string) => {
    updateMenuLayout({
      ...menuLayout,
      groups: menuLayout.groups.map(g => (g.key === key ? { ...g, label: label === '' ? undefined : label } : g)),
    })
  }, [menuLayout, updateMenuLayout])

  const moveGroup = useCallback((idx: number, delta: number) => {
    const groups = [...menuLayout.groups]
    const to = idx + delta
    if (to < 0 || to >= groups.length) return
    ;[groups[idx], groups[to]] = [groups[to], groups[idx]]
    updateMenuLayout({ ...menuLayout, groups })
  }, [menuLayout, updateMenuLayout])

  const addGroup = useCallback(() => {
    updateMenuLayout({
      ...menuLayout,
      groups: [...menuLayout.groups, { key: `grp_custom_${Date.now().toString(36)}`, label: t('menu.newGroupName'), items: [] }],
    })
  }, [menuLayout, updateMenuLayout, t])

  /** 删除目录：目录内的页面移动到第一个目录，保证页面不会凭空消失 */
  const removeGroup = useCallback((key: string) => {
    if (menuLayout.groups.length <= 1) return
    const groups = menuLayout.groups.map(g => ({ ...g, items: [...g.items] }))
    const idx = groups.findIndex(g => g.key === key)
    if (idx < 0) return
    const [removed] = groups.splice(idx, 1)
    groups[0].items.push(...removed.items)
    updateMenuLayout({ ...menuLayout, groups })
  }, [menuLayout, updateMenuLayout])

  const moveItem = useCallback((page: PageKey, toKey: string) => {
    const groups = menuLayout.groups.map(g => ({ ...g, items: g.items.filter(k => k !== page) }))
    const target = groups.find(g => g.key === toKey)
    if (!target) return
    target.items.push(page)
    updateMenuLayout({ ...menuLayout, groups })
  }, [menuLayout, updateMenuLayout])

  /** 页面在**目录内部**上下调序 */
  const moveItemWithin = useCallback((groupKey: string, idx: number, delta: number) => {
    const groups = menuLayout.groups.map(g => ({ ...g, items: [...g.items] }))
    const g = groups.find(x => x.key === groupKey)
    if (!g) return
    const to = idx + delta
    if (to < 0 || to >= g.items.length) return
    ;[g.items[idx], g.items[to]] = [g.items[to], g.items[idx]]
    updateMenuLayout({ ...menuLayout, groups })
  }, [menuLayout, updateMenuLayout])

  /** 目录显示/隐藏：隐藏后侧栏整组不出现（页面仍可 ?page= 直达、搜索也搜不到），
   *  但会在侧栏底部「已隐藏目录」区留一个恢复入口。 */
  const toggleGroupHidden = useCallback((key: string) => {
    updateMenuLayout({
      ...menuLayout,
      groups: menuLayout.groups.map(g => (g.key === key ? { ...g, hidden: g.hidden ? undefined : true } : g)),
    })
  }, [menuLayout, updateMenuLayout])

  const showGroup = useCallback((key: string) => {
    updateMenuLayout({
      ...menuLayout,
      groups: menuLayout.groups.map(g => (g.key === key ? { ...g, hidden: undefined } : g)),
    })
  }, [menuLayout, updateMenuLayout])

  const showAllGroups = useCallback(() => {
    updateMenuLayout({
      ...menuLayout,
      groups: menuLayout.groups.map(g => (g.hidden ? { ...g, hidden: undefined } : g)),
    })
  }, [menuLayout, updateMenuLayout])

  /** 目录收起/展开：纯本地阅读偏好（像侧栏宽度），写 localStorage 跨刷新保留 */
  const toggleGroupCollapsed = useCallback((key: string) => {
    setCollapsedGroups(prev => {
      const next = prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
      try { localStorage.setItem(MENU_COLLAPSED_KEY, JSON.stringify(next)) } catch { /* noop */ }
      return next
    })
  }, [])

  /** 侧栏菜单区的折叠/隐藏按钮：用**原生**监听而不是 React onClick。
   *  ⚠️ 坑：rc-menu 在 `<ul class="ant-menu">` 上有 React 的 click 处理器并调用
   *  `e.stopPropagation()`。React 合成事件是「在根节点统一派发、沿 React 树向上」，
   *  `<ul>` 一停，祖先 `#app-sider-menu` 上的 onClick 就再也不会被调用 ——
   *  表现是「按钮的点击事件确实冒泡到了容器，但 React 处理器不执行」。
   *  原生监听走的是浏览器真实传播，不受 React 合成事件影响。
   *  按钮命中才 stopPropagation（顺带挡掉 menu 的选中逻辑）；普通菜单项点击直接放行。 */
  const siderMenuRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = siderMenuRef.current
    if (!el) return
    const onAct = (e: Event) => {
      const t = e.target as HTMLElement | null
      const btn = t && typeof t.closest === 'function'
        ? (t.closest('[data-wh-group-act]') as HTMLElement | null) : null
      if (!btn) return
      const key = btn.getAttribute('data-wh-group') || ''
      switch (btn.getAttribute('data-wh-group-act')) {
        case 'collapse': if (key) toggleGroupCollapsed(key); break
        case 'hide': if (key) toggleGroupHidden(key); break
        case 'show': if (key) showGroup(key); break
        case 'show-all': showAllGroups(); break
        default: return
      }
      e.stopPropagation()
    }
    el.addEventListener('click', onAct)
    return () => el.removeEventListener('click', onAct)
  }, [toggleGroupCollapsed, toggleGroupHidden, showGroup, showAllGroups])

  const renameItem = useCallback((page: PageKey, label: string) => {
    const itemLabels = { ...(menuLayout.itemLabels || {}) }
    if (label === '') delete itemLabels[page]
    else itemLabels[page] = label
    updateMenuLayout({ ...menuLayout, itemLabels })
  }, [menuLayout, updateMenuLayout])

  /** 恢复默认：直接删掉服务端配置（所有用户回落内置结构），并同步本地 */
  const resetMenu = useCallback(() => {
    if (!menuSaveTimer.current && menuPending.current) flushMenuSave()
    if (menuSaveTimer.current) {
      window.clearTimeout(menuSaveTimer.current)
      menuSaveTimer.current = null
    }
    menuPending.current = null
    const def = defaultMenuLayout()
    setMenuLayout(def)
    writeMenuCache(def)
    if (!menuEditable) return
    setMenuSaveState('saving')
    resetMenuLayout()
      .then(() => { setMenuSaveState('saved'); setMenuSaveError('') })
      .catch((e: any) => {
        setMenuSaveState('error')
        setMenuSaveError(String(e?.response?.data?.detail || e?.message || e))
      })
  }, [menuEditable, flushMenuSave])

  // ===== 右键菜单（在新标签页打开）=====
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; key: PageKey } | null>(null)
  const [ctxHover, setCtxHover] = useState<'newTab' | 'currentTab' | null>(null)

  const onMenuContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    // 右键目录标题 → 直接打开菜单编辑器（仅本机；远端只读，不弹窗）
    if ((e.target as HTMLElement).closest('.ant-menu-item-group-title')) {
      if (menuEditable) setMenuEditOpen(true)
      return
    }
    const el = (e.target as HTMLElement).closest('li[data-menu-id]')
    if (!el) return
    // antd v6 的 data-menu-id 形如 "rc-menu-uuid-<key>"，剥离前缀还原业务 key
    let raw = el.getAttribute('data-menu-id') || ''
    let key = raw.replace(/^rc-menu-uuid-/, '')
    if (!(VALID_PAGES as string[]).includes(key)) {
      // 兜底：按「页面项」在菜单 DOM 中的出现顺序，映射回页面 key。
      // 必须用 menuItems（已套用隐藏目录过滤 + 搜索过滤）而不是 menuLayout 全量，
      // 否则有隐藏目录或正在搜索时，DOM 顺序与布局顺序不一致 → 右键会开错页面。
      // （分组标题不是 .ant-menu-item，不会混进来）
      const order = menuItems.flatMap(g => (g.children || []).map(c => c.key as PageKey))
      const idx = Array.from(document.querySelectorAll('#app-sider-menu .ant-menu-item')).indexOf(el)
      key = idx >= 0 ? (order[idx] ?? '') : ''
    }
    if (!(VALID_PAGES as string[]).includes(key)) return
    const menuW = 190
    const menuH = 96
    const pad = 8
    const x = Math.min(e.clientX, window.innerWidth - menuW - pad)
    const y = Math.min(e.clientY, window.innerHeight - menuH - pad)
    setCtxMenu({ x: Math.max(pad, x), y: Math.max(pad, y), key: key as PageKey })
  }, [menuItems, menuEditable])

  const closeCtxMenu = useCallback(() => {
    setCtxMenu(null)
    setCtxHover(null)
  }, [])

  /** 右键菜单本体：用来判断「这次事件是不是落在菜单里」 */
  const ctxMenuRef = useRef<HTMLDivElement | null>(null)

  // 右键菜单的关闭：在 window 上监听而**不是**用全屏遮罩。
  // 遮罩（position:fixed;inset:0）会吃掉用户的下一次左键/右键 —— 真实表现是
  // 「右键点了另一个页面项，菜单没挪过去；想右键目录标题开编辑器，得先点一下空白」。
  // 这里只在菜单外发生 pointerdown / contextmenu / 滚动 / Esc 时关闭，
  // 且不阻止事件本身，于是「右键另一个目标」会顺手把菜单挪过去或直接开编辑器。
  useEffect(() => {
    if (!ctxMenu) return
    const isInsideMenu = (t: EventTarget | null) =>
      t instanceof Node && !!ctxMenuRef.current && ctxMenuRef.current.contains(t)
    const onOutside = (e: Event) => { if (!isInsideMenu(e.target)) closeCtxMenu() }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeCtxMenu() }
    // capture 阶段先关菜单，随后 React 的 onContextMenu 仍会把菜单定位到新目标
    window.addEventListener('pointerdown', onOutside, true)
    window.addEventListener('contextmenu', onOutside, true)
    window.addEventListener('wheel', onOutside, { capture: true, passive: true })
    window.addEventListener('resize', onOutside)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onOutside, true)
      window.removeEventListener('contextmenu', onOutside, true)
      window.removeEventListener('wheel', onOutside, true)
      window.removeEventListener('resize', onOutside)
      window.removeEventListener('keydown', onKey)
    }
  }, [ctxMenu, closeCtxMenu])

  const openInNewTab = useCallback((key: PageKey) => {
    // 同源路径 + ?page= 参数，新标签页据此定位页面
    const url = `${window.location.pathname}?page=${key}`
    window.open(url, '_blank', 'noopener')
    closeCtxMenu()
  }, [closeCtxMenu])

  // 页面名同步到浏览器标签标题，便于新标签页识别；浏览器前进/后退也恢复页面
  useEffect(() => {
    const onPopState = () => {
      // 布局模式同样以 URL 为真相源：后退/前进跨越 embed 与外壳两种状态时同步切换
      setEmbedMode(readEmbedMode())
      const page = new URLSearchParams(window.location.search).get('page')
      if (page && (VALID_PAGES as string[]).includes(page)) setCurrentPage(page as PageKey)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  /* ===== uniplam 门户鉴权引导 =====
   * 「门户 token（?t= 或门户登录态）→ myapp 会话 Cookie」的换会话动作已在启动时
   * 完成（api.bootstrapAuth / runAuthBootstrap，见 main.tsx）。这里只负责：
   *   1. 取启动引导结果，决定是否展示登录引导；
   *   2. 会话失效（数据接口 401）时切到 authGate 引导。
   * 业务页面在 bootDone 之前不挂载，因此不会再出现「首屏 401、刷新才好」。 */
  useEffect(() => {
    setOnUnauthorized(() => setAuthGate(true))
    runAuthBootstrap()
      .then((ok) => {
        setAuthGate(!ok)   // 无身份 → 直接给「请通过统一门户登录」引导
        setBootDone(true)
      })
      .catch(() => {
        setAuthGate(true)
        setBootDone(true)
      })
    return () => setOnUnauthorized(null)
  }, [])

  const retryAuth = useCallback(() => {
    setAuthGate(false)
    getAuthMe()
      .then(() => setAuthGate(false))
      .catch(() => {
        // 仍无会话 → 交给门户登录；短暂停留让 authGate 关闭态可被再次触发
        setAuthGate(true)
      })
  }, [])

  /* URL 是当前页面状态的唯一真相源：地址栏 ←→ 页面双向同步。
 * - URL 已带 ?page= 时同步为 currentPage；历史别名（?page=tt_q）收敛成现名
 *   eflow_qa，旧书签不会分裂成两个 URL；
 * - 无 ?page=（即 /myapp/ 外壳入口）时【不强行补写】——补写会把它归一化成
 *   ?page=sync，与深链 bare（?page=xxx）的身份混为一谈，导致下次刷新外壳消失；
 *   外壳内导航由 navigateTo 的 pushState 负责写 ?page=。
 * - 用 replaceState 而不是 pushState：不产生多余历史，后退键仍回到上一个页面。
 * popstate 触发的变更 URL 已带正确参数，此处自然空转。 */
  useEffect(() => {
    const url = new URL(window.location.href)
    const existing = url.searchParams.get('page')
    if (existing === currentPage) return
    // 无显式 ?page=：保持 /myapp/ 的「外壳入口」URL 身份，不强行写入
    if (existing == null) return
    url.searchParams.set('page', currentPage)
    window.history.replaceState({ page: currentPage }, '', url)
  }, [currentPage])

  useEffect(() => {
    const label = flatMenuItems.find(m => m.key === currentPage)?.label
    if (label) document.title = `${label} - ${t('app.title')}`
  }, [currentPage, locale])

  const ctxItemBase: React.CSSProperties = {
    padding: 'var(--wh-space-xs) var(--wh-space-sm)',
    borderRadius: 'var(--wh-radius-md)',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--wh-space-sm)',
    color: 'var(--wh-text)',
    fontSize: '0.8125rem',
    userSelect: 'none',
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'sync':
        return <DataSync />
      case 'alarm':
        return <AlarmDashboard />
      case 'ttwo':
        return <TTWODashboard />
      case 'eflow_qa':
        return <EflowQa />
      case 'eflow_flow':
        return <EflowFlow />
      case 'nur':
        return <NurDashboard />
      case 'ms_sla':
        return <MsSlaDashboard />
      case 'ms_nur_only':
        return <MsNurOnly />
      case 'ms_sla_only':
        return <MsSlaOnly />
      case 'site_avail':
        return <SiteAvailability />
      case 'fme_ranking':
        return <FmeRanking />
      case 'noc_analyst':
        return <NocAnalyst />
      case 'repeat_site_down':
        return <RepeatSiteDown />
      case 'ran_cells_kpi':
        return <RanCellsKpi />
      case 'cn_kpi':
        return <CnKpi />
      case 'ume_in_kpi':
        return <UmeInKpi />
      case 'alarmManagement':
        return <AlarmManagement />
      case 'cxoDashboard':
        return <CxoDashboard />
      case 'vmaxCxoDashboard':
        return <VmaxCxoDashboard />
      case 'vmaxCxoDashboard_Daily':
        return <VmaxCxoDashboardDaily />
      case 'vmaxCxoDashboard_90Days':
        return <VmaxCxoDashboard90Days />
      case 'imonitor':
        return <ImonitorScreen />
      case 'mwUmeTopology':
        return <MwUmeDashboard />
      case 'mwRealTime':
        return <MwRealTimeDashboard />
      case 'email_reports':
        return <EmailReports />
      case 'gis':
        return <GISMap />
      case 'realtime_alarm':
        return <GISMap mode="realtime" />
      case 'packet_loss':
        return <PacketLossDashboard />
      case 'battery':
        return <BatteryDashboard />
      case 'ip_trace':
        return <IpTrace />
      case 'incident_overview':
        return <IncidentOverview />
      case 'warehouse':
        return <WarehouseDashboard />
      case 'sp_material':
        return <SpMaterialSummary />
      case 'sp_details':
        return <SpDetailsReport />
      case 'sp_report':
        return <SpReport />
      case 'com_report':
        return <ComReport />
      case 'ms_wo_sla':
        return <MsWoSLReport />
      case 'ms_contract_kpi':
        return <MsContractKpiReport />
      case 'overview':
        return <Overview />
      case 'tables':
        return <TableBrowser />
      case 'upload':
        return <DataUpload />
      case 'archive':
        return <ArchiveList />
      case 'dashboard':
        return <Dashboard />
      case 'settings':
        return <Settings />
      case 'portalLogin':
        return <PortalLogin />
      case 'feedback':
        return <IssueFeedback />
      case 'help':
        return <Help />
      default:
        // 原生看板（finebi_<slug>）：一套组件渲染 17 个看板
        if (FINEBI_PAGE_TO_SLUG[currentPage]) {
          return <NativeBoard slug={FINEBI_PAGE_TO_SLUG[currentPage]} />
        }
        return <Overview />
    }
  }

  return (
    <ConfigProvider
      locale={locale === 'zh' ? zhCN : enUS}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: isDark
          ? { ...VMAX_DARK_TOKEN, borderRadius: 6 }
          : { colorPrimary: '#13c2c2', colorInfo: '#13c2c2', borderRadius: 6 },
        components: isDark
          ? {
              // 表头 / 边框：antd 默认给 #272727 表头 + #303030 描边，换成 vmax 的
              // #08122c 表头 + #173158 描边（基准页 th 就是 #08122c / 文字 #55d7ff）
              Table: {
                colorBgContainer: '#050d22',
                headerBg: '#08122c',
                headerColor: '#55d7ff',
                headerSplitColor: '#173158',
                borderColor: '#173158',
                rowHoverBg: 'rgba(37, 140, 255, 0.10)',
                footerBg: '#08122c',
              },
              // 卡片：底色走 token，但把自带阴影调成 vmax 的内辉光观感
              Card: {
                colorBgContainer: '#08122c',
                headerBg: 'transparent',
                colorBorderSecondary: '#153db0',
              },
              // 弹窗 / 抽屉 / 下拉：浮层底用 #070d31（vmax mast 色）
              Modal: { contentBg: '#070d31', headerBg: '#070d31', titleColor: '#f5f7ff' },
              Drawer: { colorBgElevated: '#070d31' },
              Dropdown: { colorBgElevated: '#070d31', controlItemBgHover: 'rgba(37, 140, 255, 0.14)' },
              Tooltip: { colorBgSpotlight: '#0a1730', colorTextLightSolid: '#f5f7ff' },
              // 侧栏菜单：选中态用 vmax 的电光青 + 蓝色叠加底
              Menu: {
                itemBg: 'transparent',
                subMenuItemBg: 'transparent',
                itemSelectedBg: 'rgba(37, 140, 255, 0.16)',
                itemSelectedColor: '#00d9ff',
                itemHoverBg: 'rgba(37, 140, 255, 0.10)',
                itemColor: '#aebbd4',
              },
              Tabs: { itemSelectedColor: '#00d9ff', itemHoverColor: '#7fd2ee', inkBarColor: '#00d9ff', itemColor: '#aebbd4' },
              // 分段控件对应基准页的 .seg（底 rgba(9,34,74,.6) / 描边 #17499c / 选中字 #7fd2ee）
              Segmented: {
                trackBg: 'rgba(9, 34, 74, 0.60)',
                itemColor: '#aebbd4',
                itemHoverColor: '#f5f7ff',
                itemSelectedBg: '#17499c',
                itemSelectedColor: '#7fd2ee',
              },
              Alert: { colorTextHeading: '#f5f7ff' },
              Pagination: { itemBg: 'transparent' },
              Input: { colorBgContainer: 'rgba(9, 34, 74, 0.58)', activeBorderColor: '#258cff', hoverBorderColor: '#258cff' },
              Select: { colorBgContainer: 'rgba(9, 34, 74, 0.58)', optionSelectedBg: 'rgba(37, 140, 255, 0.16)' },
              Button: { defaultBg: 'rgba(9, 34, 74, 0.58)', defaultBorderColor: '#153db0', defaultColor: '#f5f7ff' },
              Tag: { defaultBg: 'rgba(37, 140, 255, 0.10)', defaultColor: '#aebbd4' },
              Progress: { remainingColor: '#173158' },
              Switch: { handleBg: '#f5f7ff' },
              Empty: { colorTextDescription: '#6f8cb4' },
            }
          : {
              Table: { headerBg: '#f0f5fa', headerColor: '#334155', rowHoverBg: '#e8f4f2' },
            },
      }}
    >
      <Layout
        className={`app-spatial-root${shellHidden ? ' wh-embed-mode' : ''}`}
        data-embed={shellHidden || undefined}
        style={{ minHeight: '100vh', background: 'transparent' }}
      >
        {/* 键盘用户 Tab 的第一站：直接跳到主内容，跳过整条侧边栏菜单。
            嵌入模式下没有侧栏，跳转链接属外壳元素，一并隐藏。 */}
        {!shellHidden && <a className="wh-skip-link" href="#main-content">{t('a11y.skip')}</a>}
        {!shellHidden && drawerOpen && (
          <button
            className="wh-sider-backdrop"
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={closeSider}
          />
        )}
        {/* 拖拽期不再盖遮罩层：遮罩会吞掉落在它上面的 mouseup/click，导致
            「双击复位」永远收不到 dblclick。改为在 CSS 里把内容区与 iframe
            的 pointer-events 关掉，事件照常冒泡到 window 上的拖拽监听。 */}
        {/* 外壳隐藏（embed/bare）：整个侧栏不渲染 —— 不是收起（收起仍占布局树），
            而是条件渲染，确保 DOM 里不存在目录导航及拖拽手柄等外壳元素。 */}
        {!shellHidden && (
        <Sider
          className="spatial-panel"
          collapsible
          collapsed={collapsed}
          collapsedWidth={0}
          trigger={null}
          theme={isDark ? 'dark' : 'light'}
          width={isMobile ? ('var(--wh-sider-width)' as any) : siderWidth}
          // 抽屉态是模态浮层，语义上要像对话框一样被读屏识别
          role={drawerOpen ? 'dialog' : 'navigation'}
          aria-modal={drawerOpen || undefined}
          aria-label={t('nav.menuLabel')}
          style={{
            // 收起时整体隐藏（含边框），由 Header 汉堡按钮展开
            borderRight: collapsed ? 'none' : '1px solid var(--wh-glass-border)',
            // position:sticky 仍是「定位元素」，拖拽手柄的绝对定位照旧以本层为祖先。
            // 桌面端必须把侧栏夹到视口高度（见下），移动端抽屉则是浮层。
            ...(drawerOpen
              ? {
                  // 移动端：抽屉浮层，从 Header 下方滑出，不覆盖 Header
                  position: 'fixed',
                  left: 0,
                  top: 'var(--wh-header-height)',
                  bottom: 0,
                  width: 'var(--wh-sider-width)',
                  zIndex: 1000,
                  height: 'auto',
                  boxShadow: 'var(--wh-shadow-3)',
                  // 抽屉有固定高度，显式给出 flex 容器语义
                  display: 'flex',
                  flexDirection: 'column',
                }
              : {
                  // ★ 滚动修复：只给外层 Layout 一个 minHeight 时，页面内容变高会把
                  //   侧栏一起撑高，`.ant-layout-sider-children{height:100%}` 拿到的是
                  //   「整页高度」，菜单区 flex:1 永远不溢出 → 不出滚动条 → 目录全展开后
                  //   底部的页面既看不到也滚不到。把高度夹死在 100vh 并 sticky 钉住视口，
                  //   菜单区才能在「视口高度 − 品牌条」内独立滚动。
                  position: 'sticky',
                  top: 0,
                  height: '100vh',
                  maxHeight: '100vh',
                  alignSelf: 'flex-start',
                  display: 'flex',
                  flexDirection: 'column',
                }),
          }}
        >
          <div style={{
            height: 'var(--wh-header-height)',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: WH.teal,
            fontWeight: 'bold',
            fontSize: collapsed ? '0.875rem' : '1rem',
            borderBottom: '1px solid var(--wh-glass-border)',
            background: 'var(--wh-glass-control)',
            position: 'relative',
            padding: '0 2rem',
          }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {collapsed ? t('app.titleShort') : t('app.title')}
            </span>
            {/* 菜单设置入口放在品牌条上而不是侧栏底部：长页面下侧栏会被内容撑高，
                放底部要滚到页面最下方才看得见，放顶部一进侧栏就能看到。
                只有本机（服务端判定 editable=true）才渲染：远端用户看到的是只读菜单。 */}
            {!collapsed && menuEditable && (
              <Tooltip title={t('menu.edit')} placement="right">
                <Button
                  type="text"
                  size="small"
                  className="wh-menu-edit-open"
                  aria-label={t('menu.edit')}
                  icon={<EditOutlined style={{ color: WH.teal }} />}
                  onClick={() => { setMenuEditOpen(true); closeCtxMenu() }}
                  style={{
                    position: 'absolute',
                    // 移动端抽屉右侧已有「关闭」按钮，菜单按钮让开一个身位
                    right: drawerOpen ? '3rem' : 'var(--wh-space-sm)',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    width: '1.75rem',
                    height: '1.75rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                />
              </Tooltip>
            )}
            {drawerOpen && (
              <Button
                ref={closeBtnRef as any}
                type="text"
                aria-label={t('nav.collapse')}
                icon={<CloseOutlined style={{ color: WH.teal, fontSize: '1rem' }} />}
                onClick={closeSider}
                style={{
                  position: 'absolute',
                  right: 'var(--wh-space-sm)',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: '2.25rem',
                  height: '2.25rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              />
            )}
          </div>
          {/* 页面搜索：35+ 个页面靠翻目录太低效，直接按名字找。
              回车跳第一个命中页；Esc 清空。收起态没有可搜索的界面，不渲染。 */}
          {!collapsed && (
            <div style={{ flexShrink: 0, padding: 'var(--wh-space-sm)', borderBottom: '1px solid var(--wh-glass-border)' }}>
              <Input
                size="small"
                allowClear
                className="wh-sider-search"
                value={menuQuery}
                onChange={(e) => setMenuQuery(e.target.value)}
                placeholder={t('nav.searchPh')}
                aria-label={t('nav.searchPh')}
                prefix={<SearchOutlined style={{ color: 'var(--wh-text-muted)' }} />}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    if (menuFirstMatch) { navigateTo(menuFirstMatch); if (isMobile) closeSider() }
                  } else if (e.key === 'Escape') {
                    e.stopPropagation(); setMenuQuery('')
                  }
                }}
              />
              {menuSearching && (
                <div className="wh-sider-search-hint">
                  {menuNoMatch ? t('nav.searchNoMatch') : t('nav.searchCount', { n: menuMatchCount })}
                </div>
              )}
            </div>
          )}
          {/* 菜单独立滚动：35+ 个页面在 1080P 上一屏放不下，滚菜单时不该带着整页走。
              高度由 .ant-layout-sider-children 的 flex 约束在视口内（见 index.css）。
              折叠/隐藏按钮用 ref + 原生监听处理（原因见 siderMenuRef 处的注释）。 */}
          <div
            id="app-sider-menu"
            ref={siderMenuRef}
            style={{ flex: 1, minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain' }}
          >
            <Menu
              theme={isDark ? 'dark' : 'light'}
              mode="inline"
              selectedKeys={[currentPage]}
              items={menuItems}
              onClick={({ key }) => { navigateTo(key as PageKey); closeCtxMenu(); if (isMobile) closeSider() }}
              onContextMenu={onMenuContextMenu}
              style={{ background: 'transparent', borderInlineEnd: 'none' }}
            />
            {/* 已隐藏目录的恢复区：没有它，隐藏之后就没入口找回来了（只能翻弹窗）。
                只有本机可编辑时才出现；远端用户按设计就是看不到被隐藏的目录。 */}
            {menuEditable && hiddenGroups.length > 0 && (
              <div className="wh-menu-hidden-box">
                <div className="wh-menu-hidden-title">
                  <EyeInvisibleOutlined aria-hidden="true" />
                  <span>{t('menu.hiddenGroups', { n: hiddenGroups.length })}</span>
                  {hiddenGroups.length > 1 && (
                    <button
                      type="button"
                      className="wh-menu-hidden-all"
                      data-wh-group-act="show-all"
                      title={t('menu.showAll')}
                    >
                      {t('menu.showAll')}
                    </button>
                  )}
                </div>
                {hiddenGroups.map(g => (
                  <div key={g.key} className="wh-menu-hidden-row">
                    <span className="wh-menu-hidden-name">{groupLabelText(g)}</span>
                    <button
                      type="button"
                      className="wh-menu-hidden-show"
                      data-wh-group={g.key}
                      data-wh-group-act="show"
                      title={t('menu.show')}
                    >
                      <EyeOutlined />
                      <span>{t('menu.showShort')}</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          {/* 右键菜单浮层：关闭逻辑在 window 上（见 ctxMenu 的 useEffect），
              不再用全屏透明遮罩 —— 遮罩会把用户的「下一次左键/右键」吃掉，
              表现为「想右键另一个页面，得先在空白处点一下」。 */}
          {ctxMenu && (
            <>
              <div
                ref={ctxMenuRef}
                role="menu"
                aria-label={t('nav.menuLabel')}
                style={{
                  position: 'fixed',
                  left: ctxMenu.x,
                  top: ctxMenu.y,
                  zIndex: 2001,
                  minWidth: '10.625rem',
                  padding: 'var(--wh-space-xs)',
                  background: 'var(--wh-glass-overlay)',
                  border: '1px solid var(--wh-glass-border)',
                  borderRadius: 'var(--wh-radius-md)',
                  boxShadow: 'var(--wh-shadow-3)',
                }}
              >
                <div
                  role="menuitem"
                  tabIndex={0}
                  style={{
                    ...ctxItemBase,
                    background: ctxHover === 'newTab' ? 'var(--wh-glass-control-hover)' : 'transparent',
                  }}
                  onMouseEnter={() => setCtxHover('newTab')}
                  onMouseLeave={() => setCtxHover(null)}
                  onClick={() => openInNewTab(ctxMenu.key)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openInNewTab(ctxMenu.key) } }}
                >
                  <ExportOutlined style={{ color: WH.teal }} />
                  {t('ctx.newTab')}
                </div>
                <div
                  role="menuitem"
                  tabIndex={0}
                  style={{
                    ...ctxItemBase,
                    background: ctxHover === 'currentTab' ? 'var(--wh-glass-control-hover)' : 'transparent',
                  }}
                  onMouseEnter={() => setCtxHover('currentTab')}
                  onMouseLeave={() => setCtxHover(null)}
                  onClick={() => { navigateTo(ctxMenu.key); closeCtxMenu() }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigateTo(ctxMenu.key); closeCtxMenu() } }}
                >
                  <SelectOutlined style={{ color: WH.teal }} />
                  {t('ctx.currentTab')}
                </div>
              </div>
            </>
          )}
          {/* 宽度拖拽手柄：仅桌面端且展开时出现（移动端抽屉为浮层，宽度由视口决定）。
              支持鼠标/触控拖动、键盘 ← → 微调（Shift 加速）、双击/Home/Enter 复位。 */}
          {!isMobile && !collapsed && (
            <div
              className={resizing ? 'wh-sider-resizer is-active' : 'wh-sider-resizer'}
              role="separator"
              aria-orientation="vertical"
              aria-label={t('nav.resize')}
              aria-valuenow={Math.round(siderWidth)}
              aria-valuemin={SIDER_W_MIN}
              aria-valuemax={SIDER_W_MAX}
              tabIndex={0}
              title={t('nav.resizeTip')}
              onPointerDown={startSiderResize}
              onDoubleClick={() => applySiderWidth(defaultSiderWidth())}
              onKeyDown={onResizerKeyDown}
            />
          )}
        </Sider>
        )}
        <Layout style={{ background: 'transparent', flex: 1, minWidth: 0 }}>
          {/* 嵌入模式：Header（汉堡 / 自动刷新 / 主题 / 语言切换）整体不渲染 */}
          {!shellHidden && (
          <Header className="spatial-navbar" style={{
            padding: isMobile ? '0 var(--wh-space-sm)' : '0 var(--wh-space-lg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--wh-glass-border)',
            position: 'relative',
            overflow: 'hidden',
            height: 'var(--wh-header-height)',
            flexShrink: 0,
          }}>
            {/* 背景网格纹理：颜色由 --wh-grid-line 提供，深浅主题各取一个强度 */}
            <div style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: 'linear-gradient(var(--wh-grid-line) 1px, transparent 1px), linear-gradient(90deg, var(--wh-grid-line) 1px, transparent 1px)',
              backgroundSize: '1.5rem 1.5rem',
              pointerEvents: 'none',
            }} />

            {/* 汉堡按钮：侧边栏默认隐藏，点击展开/收起 */}
            <Button
              ref={toggleBtnRef as any}
              type="text"
              className="wh-sider-toggle"
              aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
              aria-expanded={!collapsed}
              aria-controls="app-sider-menu"
              icon={collapsed ? <MenuUnfoldOutlined style={{ color: WH.teal, fontSize: isMobile ? '1.25rem' : '1.0625rem' }} /> : <MenuFoldOutlined style={{ color: WH.teal, fontSize: isMobile ? '1.25rem' : '1.0625rem' }} />}
              onClick={toggleSider}
              style={{
                position: 'absolute',
                left: 'var(--wh-space-sm)',
                top: '50%',
                transform: 'translateY(-50%)',
                zIndex: 10,
                width: isMobile ? '2.75rem' : '2.25rem',
                height: isMobile ? '2.75rem' : '2.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isMobile ? 'var(--wh-glass-control)' : 'transparent',
                border: isMobile ? '1px solid var(--wh-glass-border)' : '1px solid transparent',
                borderRadius: 'var(--wh-radius-md)',
              }}
            />

            {/* 左侧装饰箭头 */}
            <div className="wh-hide-mobile" aria-hidden="true" style={{
              position: 'absolute',
              left: '3.25rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--wh-decor)',
              fontSize: '1.125rem',
              letterSpacing: '0.25rem',
              userSelect: 'none',
            }}>
              ▶▶
            </div>

            {/* 右侧装饰箭头 */}
            <div className="wh-hide-mobile" aria-hidden="true" style={{
              position: 'absolute',
              right: '10rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--wh-decor)',
              fontSize: '1.125rem',
              letterSpacing: '0.25rem',
              userSelect: 'none',
            }}>
              ◀
            </div>

            {/* 居中标题 */}
            <div style={{
              flex: 1,
              textAlign: 'center',
              position: 'relative',
              zIndex: 1,
            }}>
              <h1 style={{
                margin: 0,
                fontSize: isMobile ? '1.125rem' : '1.375rem',
                fontWeight: 700,
                color: WH.teal,
                textShadow: 'var(--wh-title-shadow)',
                letterSpacing: '0.125rem',
                lineHeight: 1.2,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                padding: '0 var(--wh-space-sm)',
              }}>
                {flatMenuItems.find(m => m.key === currentPage)?.label || t('nav.overview')}
              </h1>
              {/* 底部发光装饰线 */}
              <div style={{
                width: '7.5rem',
                height: 2,
                margin: 'var(--wh-space-xs) auto 0',
                background: WH.accentGrad,
                boxShadow: 'var(--wh-title-rule-glow)',
                borderRadius: 1,
              }} />
            </div>

            {/* 右上角操作区：自动刷新 + 主题切换 + 语言切换 */}
            <div style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
              <Tooltip title={arEffective > 0 ? t('ar.every', { v: arLabel(arEffective) }) : t('ar.tip')}>
                {/* 大屏/NOC 场景的自动刷新开关；移动端隐藏（大屏均为桌面端） */}
                <Select
                  // 开启自动刷新时用强化描边做状态提示（玻璃底由 CSS 统一给）
                  className={arEffective > 0 ? 'wh-hide-mobile wh-select-active' : 'wh-hide-mobile'}
                  size="small"
                  aria-label={t('ar.label')}
                  value={arEffective}
                  onChange={changeAutoRefresh}
                  popupMatchSelectWidth={false}
                  suffixIcon={<SyncOutlined spin={arSpin} style={{ color: WH.teal }} />}
                  options={AR_OPTIONS.map(v => ({ value: v, label: arLabel(v) }))}
                  style={{ width: '7.25rem' }}
                />
              </Tooltip>
              <Tooltip title={isDark ? t('theme.toLight') : t('theme.toDark')}>
                <Button
                  size="small"
                  icon={isDark ? <SunOutlined /> : <MoonOutlined />}
                  onClick={toggle}
                  aria-label={isDark ? t('theme.toLight') : t('theme.toDark')}
                  style={{ color: WH.teal }}
                />
              </Tooltip>
              <Button
                size="small"
                icon={<TranslationOutlined />}
                onClick={toggleLocale}
                aria-label={t('lang.switch')}
                style={{ color: WH.teal }}
              >
                <span className="wh-hide-mobile">{t('lang.switch')}</span>
              </Button>
            </div>
          </Header>
          )}
          <Content id="main-content" className="dashboard-layout-shell" style={{
            // 外壳隐藏（embed/bare）：去掉外壳留白与圆角，让模块本体铺满视口（iframe / 大屏场景）
            margin: shellHidden ? 0 : 'var(--wh-content-margin)',
            padding: shellHidden ? 0 : 'var(--wh-content-padding)',
            overflow: 'auto',
            background: 'transparent',
            borderRadius: shellHidden ? 0 : 'var(--wh-radius-md)',
            display: 'flex',
            flexDirection: 'column',
            flex: shellHidden ? '1 1 auto' : undefined,
            height: shellHidden ? '100%' : undefined,
            minHeight: 0,
          }}>
            <Suspense fallback={
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
                <Spin size="large" />
              </div>
            }>
              {/* key=refreshTick：自动刷新到点后重挂载当前页面（见文件顶部说明）
                  bootDone 之前 / 未登录（authGate）时不挂载页面：避免页面在会话 Cookie
                  落地前抢跑数据接口拿到 401（首屏「Failed to load data」的根因） */}
              <Fragment key={refreshTick}>
                {!bootDone || authGate ? (
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
                    <Spin size="large" />
                  </div>
                ) : renderPage()}
              </Fragment>
            </Suspense>
          </Content>
        </Layout>
      </Layout>
      {/* ===== uniplam 门户鉴权引导（未登录 / 会话失效） ===== */}
      {authGate && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 2000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--wh-bg, #0b1626)',
          }}
        >
          <div style={{
            maxWidth: 'min(92vw, 26rem)',
            padding: '2.5rem 2rem',
            textAlign: 'center',
            borderRadius: 'var(--wh-radius-lg)',
            background: 'var(--wh-glass-panel, #122236)',
            border: '1px solid var(--wh-glass-border, #2a3f5a)',
            boxShadow: 'var(--wh-shadow-4)',
          }}>
            <div style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.75rem' }}>
              {t('auth.required')}
            </div>
            <p style={{ color: 'var(--wh-text-secondary, #aab7c4)', marginBottom: '1.5rem' }}>
              {t('auth.requiredTip')}
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
              <Button
                type="primary"
                onClick={() => {
                  const portalUrl = (import.meta.env?.VITE_UNIPLAM_URL as string)
                    || `${window.location.origin}/uniplam/`
                  window.open(portalUrl, '_blank', 'noopener,noreferrer')
                }}
              >
                {t('auth.goLogin')}
              </Button>
              <Button onClick={retryAuth}>{t('auth.retry')}</Button>
            </div>
          </div>
        </div>
      )}
      {/* 侧栏菜单编辑器：改名 / 新增 / 删除 / 显隐目录、目录与页面排序、跨目录移动。
          改动即时反映到侧栏，防抖 600ms 落盘到服务端（全局一致）。 */}
      <Modal
        open={menuEditOpen}
        title={t('menu.edit')}
        // 关窗时补交未落盘的改动，避免「改完立刻关闭」丢掉最后一次编辑
        onCancel={() => { setMenuEditOpen(false); flushMenuSave() }}
        footer={null}
        width={660}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <p className="wh-menu-edit-tip">{t('menu.editTip')}</p>
        {!menuEditable && <div className="wh-menu-edit-readonly">{t('menu.readOnlyTip')}</div>}
        {menuLayout.groups.map((g, gi) => (
          <div key={g.key} className={g.hidden ? 'wh-menu-edit-group is-hidden' : 'wh-menu-edit-group'}>
            <div className="wh-menu-edit-head">
              <Input
                size="small"
                disabled={!menuEditable}
                value={g.label ?? ''}
                placeholder={builtinGroupLabelKey(g.key) ? t(builtinGroupLabelKey(g.key)!) : t('menu.groupNamePh')}
                onChange={(e) => renameGroup(g.key, e.target.value)}
                aria-label={t('menu.renameGroup')}
                style={{ flex: 1, minWidth: 0 }}
              />
              <Tooltip title={g.hidden ? t('menu.show') : t('menu.hide')}>
                <Button
                  size="small"
                  type="text"
                  disabled={!menuEditable}
                  className="wh-menu-edit-hide"
                  aria-pressed={!!g.hidden}
                  icon={g.hidden ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                  aria-label={g.hidden ? t('menu.show') : t('menu.hide')}
                  onClick={() => toggleGroupHidden(g.key)}
                />
              </Tooltip>
              <Tooltip title={t('menu.moveUp')}>
                <Button
                  size="small"
                  type="text"
                  disabled={!menuEditable || gi === 0}
                  icon={<ArrowUpOutlined />}
                  aria-label={t('menu.moveUpGroup')}
                  onClick={() => moveGroup(gi, -1)}
                />
              </Tooltip>
              <Tooltip title={t('menu.moveDown')}>
                <Button
                  size="small"
                  type="text"
                  disabled={!menuEditable || gi === menuLayout.groups.length - 1}
                  icon={<ArrowDownOutlined />}
                  aria-label={t('menu.moveDownGroup')}
                  onClick={() => moveGroup(gi, 1)}
                />
              </Tooltip>
              <Popconfirm
                title={t('menu.deleteConfirm', { name: groupLabelText(g), n: g.items.length })}
                okText={t('common.ok')}
                cancelText={t('common.cancel')}
                disabled={!menuEditable || menuLayout.groups.length <= 1}
                onConfirm={() => removeGroup(g.key)}
              >
                <Button
                  size="small"
                  type="text"
                  danger
                  disabled={!menuEditable || menuLayout.groups.length <= 1}
                  icon={<DeleteOutlined />}
                  aria-label={t('menu.deleteGroup')}
                />
              </Popconfirm>
            </div>
            <div className="wh-menu-edit-items">
              {g.items.length === 0 && <div className="wh-menu-edit-empty">{t('menu.empty')}</div>}
              {g.items.map((k, ii) => (
                <div key={k} className="wh-menu-edit-item">
                  <span className="wh-menu-edit-icon" aria-hidden="true">{PAGE_META[k].icon}</span>
                  <Input
                    size="small"
                    disabled={!menuEditable}
                    value={menuLayout.itemLabels?.[k] ?? ''}
                    placeholder={t(PAGE_META[k].labelKey)}
                    onChange={(ev) => renameItem(k, ev.target.value)}
                    aria-label={t('menu.renamePage')}
                    style={{ flex: 1, minWidth: 0 }}
                  />
                  {/* 目录内部的顺序调整：只换本组内相邻两项，不跨目录 */}
                  <Tooltip title={t('menu.moveUp')}>
                    <Button
                      size="small"
                      type="text"
                      disabled={!menuEditable || ii === 0}
                      icon={<ArrowUpOutlined />}
                      aria-label={t('menu.moveUpPage')}
                      onClick={() => moveItemWithin(g.key, ii, -1)}
                    />
                  </Tooltip>
                  <Tooltip title={t('menu.moveDown')}>
                    <Button
                      size="small"
                      type="text"
                      disabled={!menuEditable || ii === g.items.length - 1}
                      icon={<ArrowDownOutlined />}
                      aria-label={t('menu.moveDownPage')}
                      onClick={() => moveItemWithin(g.key, ii, 1)}
                    />
                  </Tooltip>
                  <Select
                    size="small"
                    disabled={!menuEditable}
                    value={g.key}
                    className="wh-menu-edit-move"
                    aria-label={t('menu.moveTo')}
                    onChange={(to) => moveItem(k, to)}
                    options={menuLayout.groups.map(x => ({ value: x.key, label: groupLabelText(x) }))}
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
        <div className="wh-menu-edit-actions">
          <Button size="small" icon={<PlusOutlined />} disabled={!menuEditable} onClick={addGroup}>{t('menu.addGroup')}</Button>
          <Popconfirm
            title={t('menu.resetConfirm')}
            okText={t('common.ok')}
            cancelText={t('common.cancel')}
            disabled={!menuEditable}
            onConfirm={resetMenu}
          >
            <Button size="small" disabled={!menuEditable}>{t('menu.reset')}</Button>
          </Popconfirm>
          {/* 保存状态：让「改了到底存没存上」有明确反馈，而不是靠猜 */}
          <span
            className={`wh-menu-edit-status is-${menuSaveState}`}
            style={{ marginLeft: 'auto', alignSelf: 'center', maxWidth: '22rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            role="status"
            aria-live="polite"
          >
            {menuSaveState === 'saving' ? t('menu.saveSaving')
              : menuSaveState === 'saved' ? t('menu.saveSaved')
                : menuSaveState === 'error' ? `${t('menu.saveFailed')}：${menuSaveError}`
                  : ''}
          </span>
        </div>
      </Modal>
    </ConfigProvider>
  )
}

function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <TaskStatusProvider>
          <AppContent />
        </TaskStatusProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}

export default App
