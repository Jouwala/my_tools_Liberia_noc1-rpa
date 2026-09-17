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

// params: month / supervisor / fme / tech / threshold / only_with_data
export function getSiteAvailabilityOverview(params?: Record<string, string | number>) {
  return api.get('/site-availability/overview', { params })
}

// params: month / site_id / site_name
export function getSiteAvailabilityTickets(params?: Record<string, string>) {
  return api.get('/site-availability/tickets', { params })
}

// RAN 2G/3G/4G Cells KPI 看板：按天统计各制式小区可用率达标情况
// 数据源：data/ran_cells_kpi.sqlite3（由 cells_kpi_sync 任务从 RAN_UME 小区数据物化，
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

// 客户业务 KPI（UME Dong customer 周度指标：IVR / P4M / VC / USSD / PPS / CPU / Memory）
// 数据源：主库表 ume_in_customer_kpi，由 ume_in_kpi_sync 任务（每日 05:45）写入。
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
