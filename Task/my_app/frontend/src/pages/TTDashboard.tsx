/* ==================== TT Dashboard（page=tt） ====================
 * 只保留 TT 侧内容的直链页面：内容取自 TT&WO 看板（page=ttwo）的 TT 部分 ——
 * 汇总卡（只留「TT 总数」）+ 统计（严重度 / SLA 状态 / 状态，数字卡片网格）+
 * MTTR 趋势（日/周/月 三档 × P1~P4 四张「柱=TT 数量 + 线=MTTR」双轴图）。
 *
 * WO 侧内容整体不出：WO 总数 / WO 编号(唯一) 两张汇总卡、工单分析（按来源统计 WO /
 * 按状态统计 WO）、站点信息；领域与根因分析也一并去掉（它不是 TT 统计，属完整页内容）。
 *
 * 复用 TTWODashboard 的 only 切片而不是复制一份实现，原因：
 *   - 筛选条（全部时间/近 7·30·90·180 天/自定义 + 区域下拉 + 归属 + 高级过滤）、
 *     下钻弹窗（含模糊搜索与 Excel 导出）、主题取色与图表样式与 page=ttwo 完全一致，
 *     上游改口径时两个页面同步生效，不会出现「同口径两套数」；
 *   - 两个页面共用同一个 /tt-wo-dashboard/overview 端点，数字必然相同；
 *   - 直链身份仍是独立的 ?page=tt（可收藏、可上大屏、可入侧栏菜单）。
 * ================================================================ */
import TTWODashboard from './TTWODashboard'

export default function TTDashboard() {
  return <TTWODashboard only="tt" />
}
