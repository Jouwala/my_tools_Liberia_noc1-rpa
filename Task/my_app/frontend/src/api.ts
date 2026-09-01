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

export default api
