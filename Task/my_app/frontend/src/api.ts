import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

// 通知后端返回本地化数据（任务名/描述等后端数据字段）
export function setApiLocale(locale: 'zh' | 'en') {
  api.defaults.headers.common['Accept-Language'] = locale === 'en' ? 'en' : 'zh-CN'
}

// MS SLA 看板总览：NUR / SLA / Network KPI / Per-Site / WO（日+月）+ meta 新鲜度
// 数据源 ms_sla_dashboard.sqlite3，由 ms_sla_full 任务写库（TTL 60s 缓存）
export function getMsSlaOverview() {
  return api.get('/ms-sla-dashboard/overview')
}

export default api
