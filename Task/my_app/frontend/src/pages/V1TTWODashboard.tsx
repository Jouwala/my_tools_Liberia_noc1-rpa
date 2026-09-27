/* ==================== V1 TT&WO Dashboard（page=v1_ttwo） ====================
 * TT&WO 看板的「只保留上半部分」版：内容取自 page=ttwo，渲染到
 * 「MTTR 周趋势」（含其标题与图表）为止 —— 即 汇总卡（TT 总数 / WO 总数 /
 * WO 编号唯一）+ TT 统计（严重度 / 工单严重度 / SLA 状态 / 状态）+ MTTR 周趋势。
 *
 * 「MTTR Weekly Trend」标题之下的三个区块整体不出：
 *   领域与根因分析（按领域统计 TT / 根因主 / 根因子）、
 *   工单分析（按来源统计 WO / 按状态统计 WO）、
 *   站点信息（Power Sources / Power Vendor / Maintenance Team / Site Class）。
 *
 * 复用 TTWODashboard 的 only 切片而不是复制一份实现，原因：
 *   - 筛选条（全部时间/近 7·30·90·180 天/自定义 + 区域下拉 + 同步时间标签）、
 *     下钻弹窗（含模糊搜索与 Excel 导出）、主题取色与图表样式与 page=ttwo
 *     逐像素一致，上游改口径时两个页面同步生效，不会出现「同口径两套数」；
 *   - 两个页面共用同一个 /tt-wo-dashboard/overview 端点，数字必然相同；
 *   - 直链身份仍是独立的 ?page=v1_ttwo（可收藏、可上大屏、可入侧栏菜单）。
 * ================================================================ */
import TTWODashboard from './TTWODashboard'

export default function V1TTWODashboard() {
  return <TTWODashboard only="summary" />
}
