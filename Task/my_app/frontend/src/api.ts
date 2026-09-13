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
