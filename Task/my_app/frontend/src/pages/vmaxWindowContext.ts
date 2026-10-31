/* ============================================================================
 * VmaxWindowContext —— 整页唯一时间窗 + 统一查询触发
 * ============================================================================
 *
 * 「VMAX 用户查询」页的三个页签（用户概览 / 信令详单 / XDR 记录）必须看
 * **同一个时间窗**：同一个号码、同一个窗口，用户才不会对着两套时间的结果
 * 互相打架（这正是改版前三个独立时间选择器的最大问题）。
 *
 * 为什么用 Context 而不是 props 层层传：
 *   两个子面板（VmaxXdrPanel / VmaxXdrRecordsPanel）是独立组件，
 *   props 透传要一路穿过父组件再穿回去，且将来加页签还得再加一层 prop。
 *
 * 上下文里给的是**只读**的窗口 + 一个 setter：
 *   - 顶部查询条是唯一能改窗口的地方（页面级控件）；
 *   - 子面板只读，不再各自渲染 RangePicker。
 *
 * 【并行取数】的核心是 query 这一份「已执行查询」的快照：
 *   顶部「查询」按钮每点一次就生成一份快照 {token, msisdn, range}，
 *   token 递增。三个页签各自 useEffect 盯着 token 的变化，
 *   token 一变就各自发自己的请求 —— **互不 await、互不阻塞**，
 *   哪个先回来哪个先渲染。
 *   这比「父组件 await 完 CCA 再往下传」快得多：CCA 慢 30s 不会
 *   挡住 XDR 详单先出结果。
 *
 *   快照里带 range（而不是让子面板去读 context.range）是有意的：
 *   用户点「查询」之后如果又动了时间选择器，已经发出去的那次查询
 *   用的必须是点按钮那一刻的窗口，否则 URL / 结果 / 屏幕三者对不上。
 * ========================================================================== */

import { createContext, useContext } from 'react'
import type { Dayjs } from 'dayjs'

export type VmaxRange = [Dayjs, Dayjs]

/** 一次「已执行的查询」的快照 */
export type VmaxQuerySnapshot = {
  /** 轮次序号：每次点「查询」+1，子面板靠它判断是否该重新取数 */
  token: number
  /** 本次查询的号码 */
  msisdn: string
  /** 本次查询用的时间窗（点按钮那一刻的值） */
  range: VmaxRange
}

export type VmaxWindowValue = {
  /** 整页共用的时间窗（当前控件值，可能是「改了还没查」的中间态） */
  range: VmaxRange
  /** 改窗口（只有顶部查询条会调） */
  setRange: (r: VmaxRange) => void
  /** 页签中最短的上游保留时长（小时）——时间选择器据此禁用过早的时间点 */
  retentionHours: number
  /** 最近一次已执行的查询；null = 还没查过 */
  query: VmaxQuerySnapshot | null
}

export const VmaxWindowContext = createContext<VmaxWindowValue | null>(null)

/** 取整页窗口；不在 VmaxUserQuery 下渲染时返回 null（调用方自行处理） */
export function useVmaxWindow(): VmaxWindowValue | null {
  return useContext(VmaxWindowContext)
}
