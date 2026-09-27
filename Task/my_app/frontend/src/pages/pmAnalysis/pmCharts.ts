/* ============================================================================
 * PM 执行分析 —— ECharts 配置构造
 * ============================================================================
 *
 * 与 `crAnalysis/crCharts.ts` 同构。这里的函数都是**纯函数**：
 * 输入数据 + 主题，输出 option，无 React 依赖。
 *
 * ⚠️ 取色铁律：ECharts 是 canvas，**解析不了 `WH.xxx`（'var(--wh-*)' 字符串）**，
 *    必须用 `DARK` / `LIGHT` 的**实值**（AGENTS.md 第三节 3）。
 *    所以本文件一律从 `P = isDark ? DARK : LIGHT` 取色，绝不 import WH。
 * ========================================================================== */

import { DARK, LIGHT, axisLabel, axisLine, darkTooltip, splitLine } from '../../theme'
import { fmtNum, fmtRate, type MonthRow, type PlanRow, type SiteRow, type StatusRow } from './pmTypes'

/** 语义配色：正在进行的用暖色（要注意），已完成的用冷/绿色（安心）。
 *  超期一律红，且与「未超期」形成强对比 —— 这是本页最重要的视觉信号。 */
export function chartColors(isDark: boolean) {
  return {
    total: isDark ? '#4ea8ff' : '#1677ff',
    closed: isDark ? '#22c55e' : '#16a34a',
    open: isDark ? '#f59e0b' : '#d97706',
    overdue: isDark ? '#ef4444' : '#dc2626',
    onTime: isDark ? '#22c55e' : '#16a34a',
    notStarted: isDark ? '#8b9dc3' : '#64748b',
  }
}

export type ChartColors = ReturnType<typeof chartColors>

/** 图①：PM 计划维度的「已完成 / 未完成」堆叠柱（堆叠和 = 该计划工单总量） */
export function planChartOption(
  rows: PlanRow[], isDark: boolean, C: ChartColors,
  labels: { closed: string; open: string; total: string; overdueRate: string },
) {
  const P = isDark ? DARK : LIGHT
  const names = rows.map(r => r.pmp_no)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark),
      // 堆叠柱看的是构成，总量与超期率要显式给出来，否则用户要自己算
      formatter: (ps: any[]) => {
        const name = ps?.[0]?.name ?? ''
        const ex = rows.find(r => r.pmp_no === name)
        if (!ex) return name
        const line = (label: string, val: number | string) => `${label}: <b>${val}</b>`
        return [
          `<b>${name}</b>`,
          line(labels.closed, ex.closed),
          line(labels.open, ex.open),
          '— — —',
          line(labels.total, ex.total),
          line(labels.overdueRate, fmtRate(ex.overdue_rate)),
        ].join('<br/>')
      },
    },
    legend: { textStyle: { color: P.text }, top: 0 },
    grid: { left: 48, right: 24, top: 40, bottom: 70 },
    xAxis: {
      type: 'category', data: names,
      axisLabel: { ...axisLabel(isDark), rotate: 30, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    series: [
      {
        name: labels.closed, type: 'bar', stack: 'plan',
        data: rows.map(r => r.closed), itemStyle: { color: C.closed }, barMaxWidth: 40,
      },
      {
        name: labels.open, type: 'bar', stack: 'plan',
        data: rows.map(r => r.open), itemStyle: { color: C.open }, barMaxWidth: 40,
      },
    ],
  }
}

/** 图②：超期环形。中央写明超期率，分母由调用方在卡头提示里说明 */
export function overdueChartOption(
  overdue: number, onTime: number, rate: number | null,
  isDark: boolean, C: ChartColors, color: string,
  labels: { overdue: string; onTime: string },
) {
  const P = isDark ? DARK : LIGHT
  return {
    tooltip: { trigger: 'item', ...darkTooltip(isDark) },
    legend: { bottom: 0, textStyle: { color: P.text } },
    series: [{
      type: 'pie', radius: ['52%', '72%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      label: { show: true, color: P.text, fontSize: 11, formatter: '{b}\n{c} ({d}%)' },
      labelLine: { lineStyle: { color: axisLine(isDark).lineStyle.color } },
      data: [
        { name: labels.overdue, value: overdue, itemStyle: { color: C.overdue } },
        { name: labels.onTime, value: onTime, itemStyle: { color: C.onTime } },
      ],
    }],
    // 中央写超期率；分母见卡头提示
    graphic: rate == null ? [] : [{
      type: 'text', left: 'center', top: '38%',
      style: {
        text: fmtRate(rate), fill: color,
        fontSize: 22, fontWeight: 'bold', textAlign: 'center',
      },
    }],
  }
}

/** 图③：状态分布（流程卡在哪一步）—— 全量，不随计划过滤变化 */
export function statusChartOption(
  rows: StatusRow[], isDark: boolean, C: ChartColors,
) {
  const P = isDark ? DARK : LIGHT
  const palette = [C.closed, C.open, C.notStarted, C.overdue, C.total, C.onTime]
  return {
    tooltip: { trigger: 'item', ...darkTooltip(isDark) },
    legend: { type: 'scroll', bottom: 0, textStyle: { color: P.text, fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['40%', '66%'], center: ['50%', '44%'],
      label: { show: true, color: P.text, fontSize: 11, formatter: '{b}\n{c}' },
      labelLine: { lineStyle: { color: axisLine(isDark).lineStyle.color } },
      data: rows.map((s, i) => ({
        name: s.status, value: s.cnt,
        itemStyle: { color: palette[i % palette.length] },
      })),
    }],
  }
}

/** 图④：月度趋势（生成量 / 完成量柱 + 超期量线） */
export function monthChartOption(
  months: MonthRow[], isDark: boolean, C: ChartColors,
  labels: { total: string; closed: string; overdue: string },
) {
  const P = isDark ? DARK : LIGHT
  return {
    tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
    legend: { textStyle: { color: P.text }, top: 0 },
    grid: { left: 48, right: 24, top: 40, bottom: 40 },
    xAxis: {
      type: 'category', data: months.map(m => m.month),
      axisLabel: axisLabel(isDark), axisLine: axisLine(isDark),
    },
    yAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    series: [
      { name: labels.total, type: 'bar', data: months.map(m => m.total), itemStyle: { color: C.total }, barMaxWidth: 28 },
      { name: labels.closed, type: 'bar', data: months.map(m => m.closed), itemStyle: { color: C.closed }, barMaxWidth: 28 },
      {
        name: labels.overdue, type: 'line', smooth: true, data: months.map(m => m.overdue),
        itemStyle: { color: C.overdue }, lineStyle: { width: 2, color: C.overdue },
      },
    ],
  }
}

/**
 * 图⑤：流程漏斗（横向条）。
 * ⚠️ 顺序必须是**真实时序**（调用方按 STEP_KEYS 传进来），不是字段名字母序。
 * ECharts 的横向条自下而上绘制，所以这里 reverse() 让「创建」显示在最上面。
 */
export function funnelChartOption(
  steps: { label: string; cnt: number }[], isDark: boolean, C: ChartColors,
  labels: { created: string; shareOfCreated: string },
) {
  const P = isDark ? DARK : LIGHT
  const ordered = [...steps].reverse()
  return {
    tooltip: {
      trigger: 'item', ...darkTooltip(isDark),
      formatter: (p: any) => {
        const all = steps[0]?.cnt || 0
        const pct = all ? Math.round((p.value / all) * 1000) / 10 : null
        return `<b>${p.name}</b><br/>${labels.created}: <b>${fmtNum(p.value)}</b>` +
          (pct == null ? '' : `<br/>${labels.shareOfCreated}: <b>${pct}%</b>`)
      },
    },
    grid: { left: 110, right: 60, top: 16, bottom: 16 },
    xAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    yAxis: {
      type: 'category', data: ordered.map(s => s.label),
      axisLabel: { ...axisLabel(isDark), fontSize: 11 },
      axisLine: axisLine(isDark),
    },
    series: [{
      type: 'bar', data: ordered.map(s => s.cnt), barMaxWidth: 22,
      itemStyle: { color: C.total, borderRadius: [0, 3, 3, 0] },
      label: {
        show: true, position: 'right', color: P.text, fontSize: 11,
        formatter: (p: any) => fmtNum(p.value),
      },
    }],
  }
}

/** 图⑥：超期最多的站点（横向条，运维抓手） */
export function siteChartOption(
  rows: SiteRow[], isDark: boolean, C: ChartColors,
  labels: { overdue: string; open: string },
) {
  const P = isDark ? DARK : LIGHT
  const top = rows.slice(0, 12)
  const ordered = [...top].reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark) },
    legend: { textStyle: { color: P.text }, top: 0 },
    grid: { left: 150, right: 40, top: 36, bottom: 16 },
    xAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    yAxis: {
      type: 'category', data: ordered.map(s => s.site_name),
      axisLabel: { ...axisLabel(isDark), fontSize: 10, width: 140, overflow: 'truncate' },
      axisLine: axisLine(isDark),
    },
    series: [
      {
        name: labels.overdue, type: 'bar', stack: 's',
        data: ordered.map(s => s.overdue), itemStyle: { color: C.overdue }, barMaxWidth: 16,
      },
      {
        name: labels.open, type: 'bar', stack: 's',
        data: ordered.map(s => Math.max(0, s.open - s.overdue)),
        itemStyle: { color: C.open }, barMaxWidth: 16,
      },
    ],
  }
}
