/* ============================================================================
 * AvailMsTrend.tsx —— 可用率多维矩阵页的三个维度曲线图（多序列折线）
 * ----------------------------------------------------------------------------
 * 与矩阵表同源同口径：每个点 = 该维度取值在那一期的 SUM(分子)/SUM(分母)，
 * 所以曲线上的点也能直接下钻到明细（点 -> openDrill + 该点所在周期值）。
 *
 * 为什么不与下钻弹窗里那张趋势图合并成一个组件：那张是「单个单元格」的单序列小图，
 * 这张是「整个维度」的多序列图，还要图例、缺失点断线、阈值虚线只画一条、点取下钻，
 * props 与交互都不同。按 AGENTS.md 第三节原则 7，抽象要等第二个**同形**用例出现，
 * 现在这两个只是长得像，硬合并会做出一个两边都别扭的组件。
 * ========================================================================== */
import { useMemo } from 'react'
import { Empty } from 'antd'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { axisLabel, axisLine, darkTooltip, splitLine, useTheme } from '../theme'

export interface TrendSeries {
  key: string
  values: (number | null)[]
  numerators: number[]
  denominators: number[]
  overall: number | null
  below_periods: number
}

interface Props {
  categories: string[]
  series: TrendSeries[]
  /** 未达标阈值（百分点，如 99.65），只作为虚线参考线画在图里 */
  thresholdPct: number
  /** 维度取值 -> 展示名（ALL / UNMATCHED / Other 走 i18n，其余是业务原值） */
  labelOf: (key: string) => string
  /** 点某个数据点：回调维度取值 + 该点所在周期值 */
  onPoint?: (key: string, value: string) => void
  height?: number
}

export default function AvailMsTrend({
  categories, series, thresholdPct, labelOf, onPoint, height = 230,
}: Props) {
  const { t } = useI18n()
  const { isDark, palette, colors } = useTheme()

  const option = useMemo(() => {
    const many = categories.length > 14
    return {
      tooltip: {
        trigger: 'axis',
        confine: true,
        // darkTooltip 已带主题底色/边框/阴影（含 extraCssText），不要再覆写 extraCssText：
        // 显式写在前会被展开覆盖（tsc TS2783），写在后会把主题阴影冲掉
        ...darkTooltip(isDark),
        formatter: (ps: any) => {
          const list = Array.isArray(ps) ? ps : [ps]
          const i = list[0]?.dataIndex
          if (i == null) return ''
          const head = `<div style="font-weight:600;margin-bottom:4px">${categories[i]}</div>`
          const rows = list.map((p: any) => {
            const s: TrendSeries | undefined = series[p.seriesIndex]
            const v = s?.values?.[i]
            const frac = v == null ? '' : ` (${s?.numerators?.[i] ?? 0}/${s?.denominators?.[i] ?? 0})`
            const txt = v == null ? '—' : `${(v * 100).toFixed(2)}%${frac}`
            return `<div style="display:flex;gap:8px;align-items:center">${p.marker}`
              + `<span style="flex:1">${p.seriesName}</span><b>${txt}</b></div>`
          }).join('')
          const foot = `<div style="opacity:.65;font-size:11px;margin-top:4px">${t('availMs.trendFracHint')}</div>`
          return head + rows + foot
        },
      },
      legend: {
        // 图例放顶部：日档 30 个日期要转 35° 才排得下，图例放底部会和它们叠在一起
        type: 'scroll', top: 0, left: 'center', icon: 'roundRect',
        textStyle: { color: palette.textMuted, fontSize: 11 },
        data: series.map(s => labelOf(s.key)),
      },
      grid: { left: 56, right: 18, top: 34, bottom: many ? 44 : 26 },
      xAxis: {
        type: 'category',
        data: categories,
        boundaryGap: false,
        axisLabel: { ...axisLabel(isDark), rotate: many ? 35 : 0, fontSize: 11 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value',
        // 纵轴不固定 0~100：可用率都在 70%~100% 这一小段里，从 0 起会把趋势压平
        min: (v: any) => Math.max(0, Math.floor(v.min - 0.5)),
        max: (v: any) => Math.min(100, Math.ceil(v.max + 0.5)),
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
        splitLine: splitLine(isDark),
      },
      series: series.map((s, i) => ({
        name: labelOf(s.key),
        type: 'line',
        smooth: true,
        // 缺失期留空断开，不用 0 补 —— 取不到数据不得画成 0（AGENTS.md 第三节原则 6）
        connectNulls: false,
        showSymbol: categories.length <= 20,
        symbolSize: 6,
        data: s.values.map(v => (v == null ? null : Number((v * 100).toFixed(3)))),
        // 折线本身也可点：否则用户必须正好命中那个 6px 的圆点才能下钻（点命中后
        // ECharts 会把事件的 dataIndex 定到最近的期），symbol 只做视觉提示
        triggerLineEvent: true,
        itemStyle: { color: colors[i % colors.length] },
        lineStyle: { color: colors[i % colors.length], width: 2 },
        emphasis: { focus: 'series' },
        // 阈值虚线只画一条，N 条叠在一起会显得很脏
        markLine: i === 0 && thresholdPct > 0 && thresholdPct <= 100
          ? {
            silent: true, symbol: 'none',
            data: [{ yAxis: thresholdPct }],
            lineStyle: { color: palette.sev.Major, type: 'dashed' },
            // 默认标签在线的右端外侧，会被 grid.right 裁掉；挪到线内侧上方
            label: {
              position: 'insideEndTop', color: palette.sev.Major,
              formatter: `${thresholdPct}%`, fontSize: 10,
            },
          }
          : undefined,
      })),
    }
  }, [categories, series, thresholdPct, labelOf, isDark, palette, colors, t])

  if (!series.length || !categories.length) return <Empty description={t('availMs.empty')} />

  return (
    <div role="img" aria-label={t('availMs.trendAria')}>
      <ReactECharts
        option={option}
        style={{ height }}
        notMerge
        onEvents={onPoint
          ? {
            click: (p: any) => {
              const s: TrendSeries | undefined = series[p?.seriesIndex]
              const v = categories[p?.dataIndex]
              // 只响应数据点：点空白/图例时不触发（否则会弹出无意义的"下钻"）
              if (s && v && s.values[p.dataIndex] != null) onPoint(s.key, v)
            },
          }
          : undefined}
      />
    </div>
  )
}
