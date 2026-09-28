/* ==================== WO Dashboard（page=wo） ====================
 * 「WO 版的 TT 看板」：版式与 page=tt **逐块一致**，只是数据源换成 eflow_wo。
 *
 * 出什么（与 page=tt 完全对应）：
 *   汇总卡（WO 总数）→ 统计（严重度 / SLA 状态 / 状态）→
 *   MTTR 趋势（P1~P4 × 日/周/月 双轴图）。
 * MTTR 趋势之下的下半部分（领域与根因分析、工单分析、站点信息）只属完整页
 * page=ttwo；「跟 TT 页一样」的要求下 page=tt 与 page=wo 都不出（2026-09-27 确认）。
 *
 * 与 page=tt 的差异只有三处，都是「WO 表本身的语义」决定的：
 *   1. SLA 状态取**关联 eflow_tt 的 sla_status** —— eflow_wo 没有该列，SLA 是 TT 侧
 *      概念。关联键 wo.tt_no = tt.tt_no，实测覆盖率 99.99%，关联不上的行进 Unknown
 *      而不是丢弃（保证卡片之和 = WO 总数）。
 *   2. 不出「TT 总数」卡：它算的是 eflow_tt 的行数，放在 WO 页没有意义。
 *      也不出「WO 编号(唯一)」卡：本页每行本身就是一个 WO，与「WO 总数」语义重叠，
 *      同屏放两个一模一样的数字会被当成 bug。
 *   3. MTTR 用 WO 自己的 alarm_occur_time / alarm_clear_time（同一公式、同一
 *      0<dur<43200 剔除规则），所以本页的 MTTR 是**WO 的周转时效**，
 *      与 page=tt 的 TT 时效是两个数。
 *
 * 复用 TTWODashboard 的 source 开关而不是复制一份实现，原因：
 *   - 筛选条（区域 / 高级过滤）、下钻弹窗（含模糊搜索与 Excel 导出）、主题取色、
 *     图表样式与 MTTR 三档粒度全部共用，上游改样式时两页同步生效；
 *   - 复制会立刻分叉：本项目已多次踩过「同一张图两个版本、只有一处被修」的坑。
 *
 * **无 ZTE/3rd 归属过滤**：该归属的定义是「TT 的 wo_no 是否非空」，在 WO 表上
 * 每行本身就是一个 WO，没有对应概念，故该下拉在本页不显示（见 TTWODashboard
 * 的 isWoSource 分支）。
 * ================================================================ */
import TTWODashboard from './TTWODashboard'

export default function WODashboard() {
  return <TTWODashboard only="wo" source="wo" />
}
