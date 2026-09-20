/* ==================== MS SLA Only（page=ms_sla_only） ====================
 * 只保留 SLA 的直链页面：内容取自 MS Operation KPI 看板（page=ms_sla）的
 * SLA 部分 —— KPI List SLA 日/月 达成率表 + SLA Achieve Trend，
 * 以及 WOs SLA 区（工单 TTR/TTR_P1..P4 的 Total / Within SLA / Achieve + 趋势）。
 * NUR、Network KPIs、Per-Site KPIs 一律不出。
 *
 * 复用 MsSlaDashboard 的 only 切片而不是复制一份实现，原因：
 *   - 日/月粒度切换、时间范围、达成率阈值着色（≥95% 绿）、下钻弹窗与
 *     导出、数据新鲜度（last sync / KPI List mtime）与 page=ms_sla 完全一致，
 *     上游改口径时两个页面同步生效；
 *   - 直链身份仍是独立的 ?page=ms_sla_only（可收藏、可上大屏、可入侧栏菜单）。
 * ================================================================ */
import MsSlaDashboard from './MsSlaDashboard'

export default function MsSlaOnly() {
  return <MsSlaDashboard only="sla" />
}
