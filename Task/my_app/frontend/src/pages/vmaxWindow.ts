/* ============================================================================
 * vmaxWindow —— VMAX 用户查询页「页面级唯一时间窗」
 * ============================================================================
 *
 * 为什么从各面板里抽出来（2026-10-30）：
 *   改版前本页有三个时间选择器 —— 顶部查询条一个（「今天 00:00 ~ 现在」）、
 *   「信令详单」面板一个（近 2h）、「XDR 记录」面板一个（近 2h）。
 *   三个各自独立、默认值还不一样，用户查同一个号码要在三个地方对时间，
 *   很容易出现「概览看的是今天、信令详单看的是近两小时」这种张冠李戴。
 *
 * 现在：**整页只有一个时间窗**（顶部查询条那一个），三个页签共用同一份 state，
 * 换页签不重置、也不各自再存一份。
 *
 * 三条约束：
 *   1. 默认窗口 = **最近 3 小时**。比之前的「今天 00:00」短得多
 *      （信令量大，全天窗口能到万级，慢且难读），又比之前的「近 2h」
 *      宽一点（留出跨小时排障的余量）。
 *   2. **URL 只记号码与视角**（2026-10-31 起不再记窗口）：
 *      时间窗滚动（总是最新的近 3h），`run()` 会把残留的旧 vqStart/vqEnd 清掉，
 *      首屏 `readInitialRange()` 也不再读它们 —— 旧链接里即使带固定时间也忽略。
 *   3. **整页一个保留期下限**。三个页签现在**并行**用同一个窗口取数，
 *      只要有一个页签查不到，这个窗口对用户就是废的 —— 所以页面级下限取
 *      所有页签里**最短**的那个上游保留期（XDR RAN 侧 24h），
 *      时间选择器直接把更早的点置灰，而不是让用户查完再收到一句
 *      上游的「无数据」。
 * ========================================================================== */

import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'

/** 默认窗口跨度（小时）——与 i18n 文案、helpContent 说明保持一致 */
export const DEFAULT_WINDOW_HOURS = 3

/**
 * 页面级保留期下限（小时）。
 *
 * 取 24 而不是各页签自己的 72/24：整页并行取数，窗口必须对**三个页签
 * 同时**成立，而 XDR 记录页签默认查 RAN 侧单表（ods_lte_xdr_uu_cmcc 等，
 * 上游热存储只留 24h）。取最短的那个，任何页签都不会因为窗口太长而空。
 */
export const PAGE_RETENTION_HOURS = 24

/** 整页共用的窗口类型（两端都非空：页面不允许清空时间窗） */
export type VmaxRange = [Dayjs, Dayjs]

/** 默认窗口：最近 N 小时 */
export function defaultRange(): VmaxRange {
  return [dayjs().subtract(DEFAULT_WINDOW_HOURS, 'hour'), dayjs()]
}

/**
 * 首屏窗口：永远取最近 3 小时（2026-10-31 改）。
 *
 * 改前这里优先读 URL 里的 vqStart/vqEnd，原样重放历史窗口，
 * 导致旧链接（如昨天 14:48~17:48）打开还是昨天的时间，用户误以为「写死」。
 * 现按需求改成滚动窗口：首屏一律 defaultRange()，URL 里即使带旧窗口也忽略，
 * run() 落盘时也会把残留的 vqStart/vqEnd 清掉，地址栏不再出现固定时间。
 */
export function readInitialRange(): VmaxRange {
  return defaultRange()
}

/** 把窗口夹进「保留期 ~ 现在」之间 */
export function clampRange(range: VmaxRange, retentionHours = PAGE_RETENTION_HOURS): VmaxRange {
  const floor = dayjs().subtract(retentionHours, 'hour')
  const start = range[0].isBefore(floor) ? floor : range[0]
  const end = range[1].isAfter(dayjs()) ? dayjs() : range[1]
  return start.isBefore(end) ? [start, end] : [end, end]
}

/** 窗口转成后端要的两段字符串（分钟精度） */
export function rangeToParams(range: VmaxRange | null): { start?: string; end?: string } {
  if (!range) return {}
  return {
    start: range[0].format('YYYY-MM-DD HH:mm'),
    end: range[1].format('YYYY-MM-DD HH:mm'),
  }
}

/**
 * 时间选择器的禁用规则：不让选未来，也不让选早于「上游保留期」的点。
 *
 * @param retentionHours 页签中最短的上游保留时长（小时）
 */
export function disabledRangeProps(retentionHours: number = PAGE_RETENTION_HOURS) {
  const earliest = dayjs().subtract(retentionHours, 'hour')
  return {
    // 整天都早于保留期起点，或整天都在未来 → 该日期不可选
    disabledDate: (d: Dayjs) =>
      d.endOf('day').isBefore(earliest) || d.startOf('day').isAfter(dayjs()),
    disabledTime: (d: Dayjs | null) => {
      if (!d) return {}
      // 当天：未来的小时禁用
      if (d.isSame(dayjs(), 'day')) {
        return { disabledHours: () => rangeHours(0, dayjs().hour() + 1) }
      }
      // 保留期边界那天：早于 earliest 的小时禁用
      if (d.isSame(earliest, 'day')) {
        return { disabledHours: () => rangeHours(0, earliest.hour()) }
      }
      return {}
    },
  }
}

/** 小时禁用表：把 [0, from) 与 (to, 23] 置灰（antd 的 disabledHours 要的是列表） */
export function rangeHours(from: number, to: number): number[] {
  return Array.from({ length: 24 }, (_, h) => h).filter((h) => h < from || h > to)
}
