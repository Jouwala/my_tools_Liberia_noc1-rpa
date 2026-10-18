/* ============================================================================
 * CR 变更分析 —— ECharts 配置构造
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（AGENTS.md 第三节 2 的单文件 500 行上限）。
 * 这里的函数都是**纯函数**：输入数据 + 主题，输出 option，无 React 依赖。
 *
 * ⚠️ 取色铁律：ECharts 是 canvas，**解析不了 `WH.xxx`（'var(--wh-*)' 字符串）**，
 *    必须用 `DARK` / `LIGHT` 的**实值**（AGENTS.md 第三节 3）。
 *    所以本文件一律从 `P = isDark ? DARK : LIGHT` 取色，绝不 import WH。
 * ========================================================================== */

import { DARK, LIGHT, axisLabel, axisLine, darkTooltip, splitLine } from '../../theme'
import { fmtRate, type CatRow, type MonthRow, type StatusRow } from './crTypes'

/** 图表语义配色：按「计划 / 执行 / 未执行 / 按时 / 延期 / 关闭 / 进行中」分配。
 *  界面与表格的染色统一从这里取，避免同一含义两种颜色。 */
export function chartColors(isDark: boolean) {
  return {
    total: isDark ? '#4ea8ff' : '#1677ff',
    planned: isDark ? '#00d9ff' : '#0891b2',
    executed: isDark ? '#22c55e' : '#16a34a',
    unexecuted: isDark ? '#f59e0b' : '#d97706',
    onTime: isDark ? '#22c55e' : '#16a34a',
    delayed: isDark ? '#ef4444' : '#dc2626',
    closed: isDark ? '#8b9dc3' : '#64748b',
    open: isDark ? '#f59e0b' : '#d97706',
  }
}

export type ChartColors = ReturnType<typeof chartColors>

/** 图①：类别维度的「已执行 / 未执行」堆叠柱（堆叠和 = 该类别总量） */
export function planChartOption(
  rows: CatRow[], isDark: boolean, C: ChartColors,
  labels: { executed: string; unexecuted: string; total: string; rate: string },
) {
  const P = isDark ? DARK : LIGHT
  const cats = rows.map(r => r.category)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark),
      // 堆叠柱看的是构成，总量要显式给出来，否则用户要自己加
      formatter: (ps: any[]) => {
        const name = ps?.[0]?.name ?? ''
        const ex = rows.find(r => r.category === name)
        if (!ex) return name
        // val 允许 string：比率那行传进来的是 '62.8%' / '—'
        const line = (label: string, val: number | string) => `${label}: <b>${val}</b>`
        return [
          `<b>${name}</b>`,
          line(labels.executed, ex.executed),
          line(labels.unexecuted, ex.unexecuted),
          '— — —',
          line(labels.total, ex.total),
          line(labels.rate, fmtRate(ex.completion_rate)),
        ].join('<br/>')
      },
    },
    legend: { textStyle: { color: P.text }, top: 0 },
    grid: { left: 48, right: 24, top: 40, bottom: 56 },
    xAxis: {
      type: 'category', data: cats,
      axisLabel: { ...axisLabel(isDark), rotate: cats.some(c => c.length > 8) ? 22 : 0 },
      axisLine: axisLine(isDark),
    },
    yAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    series: [
      {
        name: labels.executed, type: 'bar', stack: 'plan',
        data: rows.map(r => r.executed),
        itemStyle: { color: C.executed }, barMaxWidth: 44,
      },
      {
        name: labels.unexecuted, type: 'bar', stack: 'plan',
        data: rows.map(r => r.unexecuted),
        itemStyle: { color: C.unexecuted }, barMaxWidth: 44,
      },
    ],
  }
}

/** 图②：按时率环形。中央写明比率，分母由调用方在卡头提示里说明 */
export function onTimeChartOption(
  onTime: number, delayed: number, rate: number | null,
  isDark: boolean, C: ChartColors, color: string,
  labels: { onTime: string; delayed: string },
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
        { name: labels.onTime, value: onTime, itemStyle: { color: C.onTime } },
        { name: labels.delayed, value: delayed, itemStyle: { color: C.delayed } },
      ],
    }],
    // 中央写比率，避免「按时率 100%」在样本极小时被误读（分母见卡头提示）
    graphic: rate == null ? [] : [{
      type: 'text', left: 'center', top: '38%',
      style: {
        text: fmtRate(rate), fill: color,
        fontSize: 22, fontWeight: 'bold', textAlign: 'center',
      },
    }],
  }
}

/**
 * 状态语义配色 —— 状态卡与环形图共用同一张表。
 *
 * 为什么按状态名取色而不是按数组下标轮转：状态行的顺序由 `COUNT(*) DESC`
 * 决定，某个状态从有到无就会让**其余所有状态换色**，用户会以为看错了图。
 * 按语义固定后，「绿=已关闭 / 橙=等实施 / 蓝=审批中」不会随数据漂移。
 *
 * 键是后端归一后的 `status_key`（大写）；未列出的状态回落到调色板轮转，
 * 这样上游新增状态也能显示，不会变成一片灰。
 */
const STATUS_COLOR: Record<string, 'closed' | 'open' | 'planned' | 'total' | 'delayed' | 'onTime'> = {
  CLOSED: 'closed',
  CANCELED: 'delayed',
  'WAITING FOR IMPLEMENT': 'open',
  IMPLEMENTING: 'planned',
  'CM HEAD APPROVAL': 'total',
  'DOMAIN TD APPROVAL': 'total',
  'BO/FO HEAD APPROVAL': 'total',
  'WAITING FOR UPDATE': 'delayed',
}

/** 单个状态的配色（状态卡与环形图都调它） */
export function statusColor(key: string, index: number, C: ChartColors): string {
  const semantic = STATUS_COLOR[key]
  if (semantic) return C[semantic]
  const palette = [C.closed, C.planned, C.open, C.delayed, C.total, C.onTime, C.unexecuted]
  return palette[index % palette.length]
}

/** 图③：状态分布（**全量**，不随类别过滤变化 —— 卡头已标注） */
export function statusChartOption(
  rows: StatusRow[], isDark: boolean, C: ChartColors,
) {
  const P = isDark ? DARK : LIGHT
  return {
    tooltip: { trigger: 'item', ...darkTooltip(isDark) },
    legend: { type: 'scroll', bottom: 0, textStyle: { color: P.text, fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['40%', '66%'], center: ['50%', '44%'],
      label: { show: true, color: P.text, fontSize: 11, formatter: '{b}\n{c}' },
      labelLine: { lineStyle: { color: axisLine(isDark).lineStyle.color } },
      data: rows.map((s, i) => ({
        name: s.status,
        value: s.cnt,
        // ECharts 的 dataIndex 就是这里的下标 —— 点击回查 rows[dataIndex]
        itemStyle: { color: statusColor(s.status_key, i, C) },
      })),
    }],
  }
}

/**
 * 图⑤：审批流程耗时（步骤到达量柱 + 当前滞留量线）。
 *
 * 两步之间的「谁在等」不好从柱子里看出来，故滞留量用线叠上去，
 * 峰值就是当前最堵的一步。步骤名由调用方传入（i18n 不在这里做）。
 */
export function workflowChartOption(
  steps: { label: string; arrived: number; current: number }[],
  isDark: boolean, C: ChartColors,
  labels: { arrived: string; current: string },
) {
  const P = isDark ? DARK : LIGHT
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark) },
    legend: { textStyle: { color: P.text }, top: 0 },
    grid: { left: 48, right: 48, top: 40, bottom: 64 },
    xAxis: {
      type: 'category',
      data: steps.map(s => s.label),
      axisLabel: { ...axisLabel(isDark), rotate: 22, interval: 0 },
      axisLine: axisLine(isDark),
    },
    yAxis: [
      { type: 'value', name: '', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
      { type: 'value', name: '', axisLabel: axisLabel(isDark), splitLine: { show: false } },
    ],
    series: [
      {
        name: labels.arrived, type: 'bar', data: steps.map(s => s.arrived),
        itemStyle: { color: C.total }, barMaxWidth: 40,
      },
      {
        name: labels.current, type: 'line', yAxisIndex: 1, smooth: true,
        data: steps.map(s => s.current),
        itemStyle: { color: C.open }, lineStyle: { width: 2, color: C.open },
        symbolSize: 7,
      },
    ],
  }
}

/** 图④：月度趋势（登记量 / 执行量柱 + 关闭量线） */
export function monthChartOption(
  months: MonthRow[], isDark: boolean, C: ChartColors,
  labels: { total: string; executed: string; closed: string },
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
      { name: labels.executed, type: 'bar', data: months.map(m => m.executed), itemStyle: { color: C.executed }, barMaxWidth: 28 },
      {
        name: labels.closed, type: 'line', smooth: true, data: months.map(m => m.closed),
        itemStyle: { color: C.closed }, lineStyle: { width: 2, color: C.closed },
      },
    ],
  }
}
