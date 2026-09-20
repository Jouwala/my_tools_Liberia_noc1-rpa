/* ==================== MS NUR Only（page=ms_nur_only） ====================
 * 只保留 NUR 的直链页面：内容取自 NUR 看板（page=nur）的 NUR 部分，
 * 即 NUR 日/周/月 三档的「表格 + 趋势」两列布局，SLA 三档整体不出。
 *
 * 复用 NurDashboard 的 only 切片而不是复制一份实现，原因：
 *   - 筛选条（Vendor / Project / Exclude / 时间范围）、TT 下钻弹窗、
 *     模糊搜索与 Excel 导出、数值着色与深色主题全部与 page=nur 逐像素一致，
 *     上游改口径时两个页面同步生效，不会出现「同口径两套数」；
 *   - 直链身份仍是独立的 ?page=ms_nur_only（可收藏、可上大屏、可入侧栏菜单）。
 * ================================================================ */
import NurDashboard from './NurDashboard'

export default function MsNurOnly() {
  return <NurDashboard only="nur" />
}
