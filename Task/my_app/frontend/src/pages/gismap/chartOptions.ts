// GIS 下钻抽屉的 ECharts 配置构建函数。
//
// 设计约定：
// 1) 所有函数是纯函数：输入数据 + 主题 -> option，不做副作用，便于 useMemo 缓存；
// 2) 数据口径来自后端聚合接口（全量 GROUP BY），不使用受 LIMIT 截断的明细列表；
// 3) 注意：当前 echarts 版本下不能传 lazyUpdate，否则图会空白（见 MsSlaDashboard 注释）。
import { darkTooltip, axisLabel, axisLine, splitLine, WH_COLORS } from '../../theme'
import type { NameValue, MwHistoryPoint, RatKpiSeries } from './types'
import type { TFn } from './types'

/** 图表统一配色（跟随主题的调色板取自 WH_COLORS，保证与全站一致） */
const PALETTE = WH_COLORS

/** 严重度/状态的语义色：命中则用语义色，否则回落到调色板 */
const SEMANTIC: Record<string, string> = {
  // 严重度
  critical: '#ff4d4f', high: '#ff4d4f',
  major: '#ff922b', medium: '#ff922b',
  minor: '#ffd43b', low: '#52c41a',
  warning: '#faad14',
  // 状态
  closed: '#52c41a', pass: '#52c41a', 'within sla': '#52c41a',
  opened: '#ff4d4f', open: '#ff4d4f', failed: '#ff4d4f',
  unknown: '#8c8c8c', '-': '#8c8c8c',
  // 根因
  power: '#ff922b', ran: '#40a9ff', transmission: '#b37feb',
  'auto-recovery': '#52c41a',
}

const semanticColor = (name: string, idx: number): string =>
  SEMANTIC[String(name).trim().toLowerCase()] || PALETTE[idx % PALETTE.length]

const fmtPct = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(Number(v)) ? '-' : `${(Number(v) * 100).toFixed(digits)}%`

/** 空数据统一占位（避免画出一张空白坐标轴） */
export const hasData = (rows?: unknown[] | null): boolean => !!rows && rows.length > 0

// ==================== 1. 站点可用率趋势（多制式折线 + 阈值线） ====================

export interface AvailPoint { tech: string; day: string; availability: number }

export const buildAvailabilityOption = (
  rows: AvailPoint[],
  opts: { isDark: boolean; threshold: number; t: TFn; height?: number },
) => {
  const { isDark, threshold, t } = opts
  const days = Array.from(new Set(rows.map(r => r.day))).sort()
  const techs = Array.from(new Set(rows.map(r => r.tech)))
  const byTechDay = new Map<string, number>()
  rows.forEach(r => byTechDay.set(`${r.tech}|${r.day}`, r.availability))

  const series = techs.map((tech, i) => ({
    name: tech,
    type: 'line' as const,
    smooth: false,
    symbol: 'circle',
    symbolSize: days.length > 45 ? 3 : 5,
    connectNulls: true,
    data: days.map(d => {
      const v = byTechDay.get(`${tech}|${d}`)
      return v == null ? null : +(v * 100).toFixed(3)
    }),
    lineStyle: { width: 2, color: PALETTE[i % PALETTE.length] },
    itemStyle: {
      color: (p: any) => (p.value != null && p.value / 100 < threshold ? '#ff4d4f' : PALETTE[i % PALETTE.length]),
    },
  }))

  // 阈值参考线（仅一条，挂在首个系列上）
  if (series.length) {
    ;(series[0] as any).markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: '#ff4d4f', type: 'dashed', width: 1 },
      label: { formatter: `${(threshold * 100).toFixed(2)}%`, color: '#ff4d4f', fontSize: 10 },
      data: [{ yAxis: +(threshold * 100).toFixed(3) }],
    }
  }

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...darkTooltip(isDark), valueFormatter: (v: any) => (v == null ? '-' : `${v}%`) },
    legend: { data: techs, textStyle: axisLabel(isDark), top: 0, right: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 52, right: 16, top: 28, bottom: days.length > 20 ? 46 : 30 },
    xAxis: {
      type: 'category',
      data: days.map(d => d.slice(5)),
      axisLabel: { ...axisLabel(isDark), rotate: days.length > 20 ? 45 : 0, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
      splitLine: splitLine(isDark),
    },
    // 60 天数据点较多，开启缩放便于看局部
    dataZoom: days.length > 30
      ? [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 8, ...(isDark ? { textStyle: { color: '#aebbd4' } } : {}) }]
      : undefined,
    series,
  }
}

// ==================== 2. 丢包趋势（柱=最大，线=平均，右轴=采样数） ====================

export interface PlPoint { day: string; max_packet_loss: number; avg_packet_loss: number; samples: number }

export const buildPacketLossOption = (
  rows: PlPoint[],
  opts: { isDark: boolean; t: TFn },
) => {
  const { isDark, t } = opts
  const days = rows.map(r => String(r.day).slice(5))
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
    legend: { textStyle: axisLabel(isDark), top: 0, right: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 52, right: 52, top: 28, bottom: rows.length > 20 ? 46 : 30 },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { ...axisLabel(isDark), rotate: rows.length > 20 ? 45 : 0, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis: [
      {
        type: 'value', name: '%', nameTextStyle: axisLabel(isDark),
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark),
      },
      {
        type: 'value', name: t('gis.chart.samples'), nameTextStyle: axisLabel(isDark),
        axisLabel: axisLabel(isDark), splitLine: { show: false },
      },
    ],
    dataZoom: rows.length > 30
      ? [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 8 }]
      : undefined,
    series: [
      {
        name: t('gis.chart.maxLoss'), type: 'bar', barMaxWidth: 22,
        data: rows.map(r => r.max_packet_loss == null ? null : +Number(r.max_packet_loss).toFixed(3)),
        itemStyle: { color: '#ff922b', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: t('gis.chart.avgLoss'), type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
        data: rows.map(r => r.avg_packet_loss == null ? null : +Number(r.avg_packet_loss).toFixed(3)),
        lineStyle: { width: 2, color: '#40a9ff' }, itemStyle: { color: '#40a9ff' },
      },
      {
        name: t('gis.chart.samples'), type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none',
        data: rows.map(r => r.samples), lineStyle: { width: 1, type: 'dashed', color: '#8c8c8c' },
        itemStyle: { color: '#8c8c8c' },
      },
    ],
  }
}

// ==================== 3. 微波链路利用率趋势（每链路一条线） ====================

export interface MwLink {
  source: string; target: string
  tx_utilization?: number | null; rx_utilization?: number | null
  history?: MwHistoryPoint[]
}

export const buildMicrowaveOption = (
  links: MwLink[],
  opts: { isDark: boolean; t: TFn },
) => {
  const { isDark, t } = opts
  // 以「源→目标」为系列名，取并集日期轴
  const withHist = links.filter(l => hasData(l.history))
  const days = Array.from(new Set(withHist.flatMap(l => (l.history || []).map(h => h.day)))).sort()

  const series = withHist.flatMap((l, i) => {
    const key = `${l.source} → ${l.target}`
    const color = PALETTE[i % PALETTE.length]
    const map = new Map((l.history || []).map(h => [h.day, h]))
    return [{
      name: key,
      type: 'line' as const,
      smooth: false,
      symbol: 'circle',
      symbolSize: days.length > 30 ? 3 : 5,
      connectNulls: true,
      data: days.map(d => {
        const h = map.get(d)
        return h?.max_util == null ? null : +Number(h.max_util).toFixed(2)
      }),
      lineStyle: { width: 2, color },
      itemStyle: { color },
    }]
  })

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...darkTooltip(isDark), valueFormatter: (v: any) => (v == null ? '-' : `${v}%`) },
    legend: { type: 'scroll', textStyle: axisLabel(isDark), top: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 52, right: 16, top: 34, bottom: days.length > 20 ? 46 : 30 },
    xAxis: {
      type: 'category', data: days.map(d => String(d).slice(5)),
      axisLabel: { ...axisLabel(isDark), rotate: days.length > 20 ? 45 : 0, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis: {
      type: 'value', name: '%', nameTextStyle: axisLabel(isDark),
      axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark),
    },
    dataZoom: days.length > 30 ? [{ type: 'inside' }] : undefined,
    series,
  }
}

/** 微波无逐日历史时，退化为「当前各链路 Tx/Rx 利用率」对比条形图 */
export const buildMicrowaveCurrentOption = (links: MwLink[], opts: { isDark: boolean; t: TFn }) => {
  const { isDark, t } = opts
  const names = links.map(l => `${l.source} → ${l.target}`)
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark) },
    legend: { textStyle: axisLabel(isDark), top: 0, right: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 8, right: 32, top: 28, bottom: 8, containLabel: true },
    xAxis: { type: 'value', axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark) },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { ...axisLabel(isDark), fontSize: 10 }, axisLine: axisLine(isDark),
    },
    series: [
      {
        name: 'Tx', type: 'bar', barMaxWidth: 14,
        data: links.map(l => l.tx_utilization == null ? null : +Number(l.tx_utilization).toFixed(2)),
        itemStyle: { color: '#ff922b', borderRadius: [0, 3, 3, 0] },
      },
      {
        name: 'Rx', type: 'bar', barMaxWidth: 14,
        data: links.map(l => l.rx_utilization == null ? null : +Number(l.rx_utilization).toFixed(2)),
        itemStyle: { color: '#40a9ff', borderRadius: [0, 3, 3, 0] },
      },
    ],
  }
}

// ==================== 4. 通用：饼图 / 横向条形 / 堆叠柱 ====================

export const buildPieOption = (
  rows: NameValue[],
  opts: { isDark: boolean; t: TFn; title?: string },
) => ({
  backgroundColor: 'transparent',
  tooltip: { trigger: 'item', ...darkTooltip(opts.isDark), formatter: '{b}: {c} ({d}%)' },
  legend: {
    type: 'scroll', orient: 'vertical', right: 4, top: 'middle',
    textStyle: { ...axisLabel(opts.isDark), fontSize: 11 }, itemWidth: 10, itemHeight: 8,
  },
  series: [{
    type: 'pie',
    radius: ['42%', '70%'],
    center: ['36%', '52%'],
    avoidLabelOverlap: true,
    label: { show: false },
    emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold', color: opts.isDark ? '#f5f7ff' : '#16233b' } },
    labelLine: { show: false },
    data: rows.map((r, i) => ({ ...r, itemStyle: { color: semanticColor(r.name, i) } })),
  }],
})

export const buildBarOption = (
  rows: NameValue[],
  opts: { isDark: boolean; t: TFn; horizontal?: boolean; color?: string },
) => {
  const { isDark, horizontal } = opts
  const names = rows.map(r => r.name)
  const values = rows.map(r => r.value)
  const cat = {
    type: 'category' as const,
    data: names,
    axisLabel: { ...axisLabel(isDark), fontSize: 10, interval: 0, ...(horizontal ? {} : { rotate: names.length > 5 ? 30 : 0 }) },
    axisLine: axisLine(isDark),
  }
  const val = { type: 'value' as const, axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) }
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark) },
    grid: horizontal
      ? { left: 8, right: 28, top: 12, bottom: 8, containLabel: true }
      : { left: 44, right: 16, top: 16, bottom: names.length > 5 ? 52 : 28 },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? { ...cat, inverse: true } : val,
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({
        value: v,
        itemStyle: { color: opts.color || semanticColor(names[i], i), borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
      })),
      barMaxWidth: 26,
      label: horizontal ? { show: true, position: 'right', ...axisLabel(isDark), fontSize: 10 } : undefined,
    }],
  }
}

/** 按日堆叠柱：总量 + 已闭环（用于 TT 频次，直观体现未闭环积压） */
export const buildStackedDailyOption = (
  rows: { day: string; total: number; closed?: number }[],
  opts: { isDark: boolean; t: TFn },
) => {
  const { isDark, t } = opts
  const days = rows.map(r => String(r.day).slice(5))
  const closed = rows.map(r => r.closed ?? 0)
  const open = rows.map(r => Math.max(0, (r.total ?? 0) - (r.closed ?? 0)))
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...darkTooltip(isDark) },
    legend: { textStyle: axisLabel(isDark), top: 0, right: 0, itemWidth: 12, itemHeight: 8 },
    grid: { left: 44, right: 16, top: 28, bottom: rows.length > 20 ? 46 : 30 },
    xAxis: {
      type: 'category', data: days,
      axisLabel: { ...axisLabel(isDark), rotate: rows.length > 20 ? 45 : 0, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    dataZoom: rows.length > 30 ? [{ type: 'inside' }] : undefined,
    series: [
      { name: t('gis.chart.ttClosed'), type: 'bar', stack: 'tt', data: closed, itemStyle: { color: '#52c41a' }, barMaxWidth: 20 },
      { name: t('gis.chart.ttOpen'), type: 'bar', stack: 'tt', data: open, itemStyle: { color: '#ff922b' }, barMaxWidth: 20 },
    ],
  }
}

// ==================== 5. 分制式 KPI（2G/3G/4G 页签） ====================

/**
 * 单制式多指标趋势：按 is_rate 分成两个纵轴。
 * 比率类（0~1）走左轴按百分比显示；流量/计数类走右轴用原始量纲。
 * 由于 KPI 单位差异极大（Erl / GB / min），一次只画 1~3 条同类指标最易读，
 * 故这里按调用方传入的 selectedKeys 过滤。
 */
export const buildRatKpiOption = (
  series: RatKpiSeries,
  selectedKeys: string[],
  opts: { isDark: boolean; t: TFn },
) => {
  const { isDark, t } = opts
  const daily = series.daily || []
  const days = daily.map(d => String(d.day).slice(5))
  const metrics = (series.metrics || []).filter(m => selectedKeys.includes(m.key))
  const rateMetrics = metrics.filter(m => m.is_rate)
  const absMetrics = metrics.filter(m => !m.is_rate)
  const useDual = rateMetrics.length > 0 && absMetrics.length > 0

  // 比率类在库里以 0~1 存储，图上统一换算成百分数显示
  const value = (d: Record<string, any>, m: { key: string; is_rate: boolean | null }) => {
    const v = d[m.key]
    if (v == null) return null
    const n = Number(v)
    if (Number.isNaN(n)) return null
    return m.is_rate ? +(n * 100).toFixed(4) : n
  }

  const mk = (m: { key: string; label: string; is_rate: boolean | null }, i: number, axis: number) => ({
    name: m.label,
    type: 'line' as const,
    yAxisIndex: axis,
    smooth: false,
    symbol: 'circle',
    symbolSize: days.length > 30 ? 3 : 5,
    connectNulls: true,
    data: daily.map(d => value(d, m)),
    lineStyle: { width: 2, color: PALETTE[i % PALETTE.length] },
    itemStyle: { color: PALETTE[i % PALETTE.length] },
  })

  const yAxis = useDual
    ? [
        {
          type: 'value', scale: true,
          name: t('gis.chart.rateAxis'), nameTextStyle: axisLabel(isDark),
          axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark),
        },
        {
          type: 'value', scale: true,
          name: t('gis.chart.valueAxis'), nameTextStyle: axisLabel(isDark),
          axisLabel: axisLabel(isDark), splitLine: { show: false },
        },
      ]
    : [{
        type: 'value', scale: true,
        axisLabel: {
          ...axisLabel(isDark),
          formatter: rateMetrics.length > 0 ? '{value}%' : '{value}',
        },
        splitLine: splitLine(isDark),
      }]

  return {
    backgroundColor: 'transparent',
    // 比率类已换算为百分数，值本身即可读，无需额外后缀
    tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
    legend: { type: 'scroll', textStyle: axisLabel(isDark), top: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 56, right: useDual ? 66 : 18, top: 36, bottom: days.length > 20 ? 46 : 30 },
    xAxis: {
      type: 'category', data: days,
      axisLabel: { ...axisLabel(isDark), rotate: days.length > 20 ? 45 : 0, fontSize: 10 },
      axisLine: axisLine(isDark),
    },
    yAxis,
    dataZoom: days.length > 30 ? [{ type: 'inside' }] : undefined,
    series: [
      ...rateMetrics.map((m, i) => mk(m, i, 0)),
      ...absMetrics.map((m, i) => mk(m, rateMetrics.length + i, useDual ? 1 : 0)),
    ],
  }
}

/** 比率类指标换算后的百分数格式，供 tooltip / 卡片展示复用 */
export const fmtRate = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(Number(v)) ? '-' : `${(Number(v) * 100).toFixed(digits)}%`

export { fmtPct, semanticColor, PALETTE }
