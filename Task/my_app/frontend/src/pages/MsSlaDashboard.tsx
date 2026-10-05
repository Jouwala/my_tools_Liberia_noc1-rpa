import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Card, Table, Segmented, Button, Space, Spin, Alert, Tag, Typography, Input, DatePicker,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import { ReloadOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons'
import { exportAoaReport, exportReport, type ReportSheetSpec, type HeaderCell } from '../utils/excelReport'
import dayjs, { Dayjs } from 'dayjs'
import api, { getMsSlaOverview } from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { useTheme, WH, WH_COLORS, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import NurCalcChainNote, { type WarningDetail } from '../components/NurCalcChainNote'

const { Text } = Typography
const { RangePicker } = DatePicker

// ---------- 下钻表格通用工具（项目统一下钻规范，与 NurDashboard 一致） ----------
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

// 粒度三档：天 / 周 / 月（周口径为 ISO 周 "YYYY-Wnn"，与 nur_calc / NurDashboard 一致）。
// 三张映射表的键名必须是字面量：check-i18n 守卫拒绝动态拼 key，会把
// `'msSla.tab' + g` 读成不存在的键而中断构建。页签用长名（天/周/月），
// 卡片标题与下钻提示用短名（Daily/Weekly/Monthly）。
type Gran = 'daily' | 'weekly' | 'monthly'
const GRANS: Gran[] = ['daily', 'weekly', 'monthly']
const GRAN_TAB_KEY: Record<Gran, string> = {
  daily: 'msSla.tabDay', weekly: 'msSla.tabWeek', monthly: 'msSla.tabMonth',
}
const GRAN_LABEL_KEY: Record<Gran, string> = {
  daily: 'msSla.daily', weekly: 'msSla.weekly', monthly: 'msSla.monthly',
}
const GRAN_TITLE_KEY: Record<Gran, string> = {
  daily: 'nur.daily', weekly: 'nur.weekly', monthly: 'nur.monthly',
}

/**
 * 各档粒度的默认查询区间（2026-09-28 需求）：天 = 当月 1 日→今天；周 = 最近 12 周；
 * 月 = 最近 9 个自然月（≈2026-01，eflow_tt 有效数据自 2026-01 起）。
 * 切档会重置为该档默认值，这是刻意的：三档窗口量级差 9 倍，沿用上一档区间会出现
 * 「周档位显示几百列」；页面上用 msSla.tabHint 横幅写明当前粒度与区间。
 */
function defaultRange(g: Gran): [Dayjs, Dayjs] {
  if (g === 'weekly') return [dayjs().subtract(11, 'week'), dayjs()]
  if (g === 'monthly') return [dayjs().startOf('month').subtract(8, 'month'), dayjs()]
  return [dayjs().startOf('month'), dayjs()]
}

// 标量指标行（metric × period 透视，与后端 _pivot 结构对齐）
interface ScalarRow { metric: string; [period: string]: number | string | null }
// WO SLA 明细行
interface WoRow {
  period: string; metric: string;
  total: number | null; within_sla: number | null; achieve: number | null
}
interface OverviewResp {
  meta: Record<string, string>
  nur: Record<Gran, ScalarRow[]>
  sla: Record<Gran, ScalarRow[]>
  network: Record<Gran, ScalarRow[]>
  persite: Record<Gran, ScalarRow[]>
  wo: Record<Gran, WoRow[]>
  /** nur_calc 口径告警（如"站点在 cm_site_summary 找不到小区信息，已排除不计"） */
  warnings?: string[]
  /** 告警的结构化明细（如未匹配站点清单），供告警条点击展开 */
  warning_details?: WarningDetail[]
}

// NUR 展示口径：原始值 × 100000（与 NurDashboard 一致）
const NUR_SCALE = 100000
// WO Achieve 目标值（参考 Excel 条件格式语义：≥95% 达标）
const WO_ACHIEVE_TARGET = 0.95

// NUR 指标显示名（KPI List 语义：NUR_NETWORK = Global）
const NUR_NAMES: Record<string, string> = {
  NUR_NETWORK: 'Global', NUR_2G: '2G', NUR_3G: '3G', NUR_4G: '4G',
}
const NUR_COLORS: Record<string, string> = {
  Global: '#258cff', '2G': '#7c8ff0', '3G': '#a99cff', '4G': '#51cf66',
}
// NUR 指标名 → 下钻 tech 参数（NUR_NETWORK = Global）
const NUR_TECH: Record<string, string> = {
  NUR_NETWORK: 'Global', NUR_2G: '2G', NUR_3G: '3G', NUR_4G: '4G',
}
// SLA 指标名（KPI List 语义 TTR/TTR_P1..P4）→ 下钻 severity 参数
const SLA_SEV: Record<string, string> = {
  TTR: 'Total', TTR_P1: 'P1', TTR_P2: 'P2', TTR_P3: 'P3', TTR_P4: 'P4',
}
// Per-Site 的 NUR 行 → 下钻 tech（其余 PS_* 指标不支持下钻）
const PERSITE_NUR_TECH: Record<string, string> = { PS_NUR_2G: '2G', PS_NUR_3G: '3G' }

function fmtNur(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return (v * NUR_SCALE).toFixed(2)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}
function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return Number(v).toFixed(2)
}
// NUR 数值文字着色（与 NurDashboard 完全一致）：0→主题次要色，越大越偏暖红（无背景块，保证深色主题可读性）
function nurTextColor(v: number, max: number): string {
  if (v <= 0 || max <= 0) return 'var(--wh-text-muted)'
  const t = Math.min(1, v / max)
  if (t < 0.35) return 'var(--wh-blue)'
  if (t < 0.7) return 'var(--wh-sev-warning)'
  return 'var(--wh-sev-critical)'
}

// ---------- 页面级导出：结果转 Excel 单元格（口径与页面上 fmt* 完全一致，明细保精度） ----------
// 页面用 '-' 表示「无数据」；导出文件里用 '—'，避免与真实的 0 混淆（项目硬性要求）
// 表格数值保持原始精度（不带单位），与页面 ScalarTable 展示的裸数值一致，便于二次计算
function xlRaw(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v)
}
// NUR 展示口径：× 100000，2 位小数（与页面 fmtNur 一致）
function xlNur(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number((v * NUR_SCALE).toFixed(2))
}
// 百分比口径：0~1 → 百分点，2 位小数（与页面 fmtPct 一致）
function xlPct(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number((v * 100).toFixed(2))
}
// 期间列：与页面一样降序、最新在左（ScalarTable / WoTable 都用 .reverse()）
function periodsOf(rows: ScalarRow[] | undefined): string[] {
  if (!rows || rows.length === 0) return []
  return Object.keys(rows[0]).filter(k => k !== 'metric').sort().reverse()
}
// 指标显示名 + 期间列 → 二维数组（行=指标，列=期间）
function scalarSheetBody(
  rows: ScalarRow[], nameMap: Record<string, string> | undefined,
  cell: (v: any) => number | string,
): (number | string)[][] {
  const periods = periodsOf(rows)
  return rows.map(r => [nameMap?.[r.metric] || r.metric, ...periods.map(p => cell(r[p]))])
}
// WO 表的期间列表（降序，最新在左；表体与表头共用，保证列对齐）
function woPeriods(rows: WoRow[]): string[] {
  return Array.from(new Set((rows || []).map(r => r.period))).sort().reverse()
}
// WO SLA 表体：行=TTR/TTR_P1..P4 ×（Total / Within SLA / Achieve），列=期间（降序）
function woSheetBody(rows: WoRow[]): (number | string)[][] {
  const metrics = ['TTR', 'TTR_P1', 'TTR_P2', 'TTR_P3', 'TTR_P4']
  const byPeriod: Record<string, Record<string, WoRow>> = {}
  for (const r of rows || []) {
    if (!byPeriod[r.period]) byPeriod[r.period] = {}
    byPeriod[r.period][r.metric] = r
  }
  const periods = woPeriods(rows)
  return metrics.flatMap(m => (['total', 'within_sla', 'achieve'] as const).map(item => {
    // 值单元格统一走 xlRaw／xlPct，避免「取不到数据」被写成 0
    const cell = item === 'achieve' ? xlPct : xlRaw
    return [
      m, item,
      ...periods.map(p => cell(byPeriod[p]?.[m]?.[item] as number | null | undefined)),
    ]
  }))
}
// WO 表头：多层合并，期间横跨 Total / Within SLA / Achieve 三列
function woSheetHeader(t: (k: string) => string, rows: WoRow[]): HeaderCell[][] {
  const periods = woPeriods(rows)
  return [[
    { text: t('msSla.exportMetric'), rowSpan: 2 },
    { text: t('msSla.exportMetaItem'), rowSpan: 2 },
    ...periods.map(p => ({ text: p, colSpan: 3 })),
  ], [
    ...periods.flatMap(() => [
      { text: t('msSla.total') }, { text: t('msSla.withinSla') }, { text: t('msSla.achieve') },
    ]),
  ]]
}

const cardStyle: React.CSSProperties = {
  background: WH.cardBg, borderRadius: 'var(--wh-radius-md)', border: '1px solid rgba(0, 217, 255,0.12)',
}
const headStyle: React.CSSProperties = {
  borderBottom: '1px solid rgba(0, 217, 255,0.12)', color: WH.teal, fontSize: '0.8125rem', fontWeight: 600,
}
const TABLE_H = 240

// WO 达成率分面图：4 张（P1~P4）按 2 列排布，撑满整页宽度。
// 图高 320：分面从半宽受限的卡中卡里解放出来后，需要足够纵向空间让 45° 期间标签
// 与图例不打架；两行合计约 640px，与上方表格（TABLE_H=240 + 表头）合计刚好一屏有余。
const WO_TREND_H = 320
// 分面配色按严重度递增从蓝到红（P1 最轻 → P4 最重），与表格里 percent 着色语义一致
const WO_TREND_COLORS = ['#258cff', '#51cf66', '#ffd43b', '#ff6b6b']

// ---------- 通用标量表：行=指标（可映射显示名），列=期间（降序，最新在左） ----------
// colorBy: 'nur' 用按值大小渐变（蓝→黄→红，与 NurDashboard 一致）；'percent' 用达成率阈值（≥目标绿/否则红）；缺省 WH.text
// onDrill 存在时数值单元格可点击 → 下钻 TT 明细（仅 NUR/SLA/Per-Site NUR 行使用）
function ScalarTable({ rows, fmt, nameMap, colorBy, onDrill }: {
  rows: ScalarRow[]; fmt: (v: number | null) => string; nameMap?: Record<string, string>
  colorBy?: 'nur' | 'percent'
  onDrill?: (e: React.MouseEvent, metric: string, period: string) => void
}) {
  const { t } = useI18n()
  const periods = useMemo(() => {
    if (!rows || rows.length === 0) return []
    return Object.keys(rows[0]).filter(k => k !== 'metric').sort().reverse()
  }, [rows])
  const maxVal = useMemo(() => {
    let m = 0
    for (const r of rows || []) for (const p of periods) {
      const v = r[p]
      if (typeof v === 'number' && v > m) m = v
    }
    return m
  }, [rows, periods])
  const cellColor = (v: number | null): string => {
    if (v === null || v === undefined) return WH.textDim
    if (colorBy === 'nur') return nurTextColor(v, maxVal)
    if (colorBy === 'percent') return v >= WO_ACHIEVE_TARGET ? '#51cf66' : '#ff6b6b'
    return WH.text
  }
  const clickable = {
    cursor: 'pointer' as const,
    textDecoration: 'underline dotted rgba(148,163,184,0.55)', textUnderlineOffset: 3,
  }
  const columns = [
    {
      title: 'Metric', dataIndex: 'metric', key: 'metric', fixed: 'left' as const, minWidth: 110,
      render: (v: string) => <Text strong style={{ color: WH.text }}>{nameMap?.[v] || v}</Text>,
    },
    ...periods.map(p => ({
      title: p, dataIndex: p, key: p, minWidth: 92, align: 'right' as const,
      render: (v: number | null, r: ScalarRow) => {
        if (v === null || v === undefined) {
          return <span style={{ color: WH.textDim }}>-</span>
        }
        if (!onDrill) {
          return <span style={{ color: cellColor(v) }}>{fmt(v)}</span>
        }
        // 点击单元格 → 下钻构成该数值的 TT 明细
        return (
          <span
            title={t('nur.clickDrill')}
            onClick={e => onDrill(e, r.metric, p)}
            style={{ color: cellColor(v), ...clickable }}
          >
            {fmt(v)}
          </span>
        )
      },
    })),
  ]
  return (
    <div className="wh-table-responsive">
      <Table
        size="small" columns={columns} dataSource={rows} rowKey="metric"
        pagination={false} scroll={{ x: 'max-content', y: TABLE_H }}
        className="dark-table"
      />
    </div>
  )
}

// ---------- 通用趋势图（深色底 + 圆点虚线，参考 NurDashboard 风格） ----------
function trendOption(opts: {
  title: string
  periods: string[]
  series: { name: string; color: string; data: (number | null)[] }[]
  percent?: boolean
  isDark: boolean
  clickHint?: string
}) {
  const { title, periods, series, percent, isDark, clickHint } = opts
  return {
    backgroundColor: 'transparent',
    title: {
      text: title, left: 'center', top: 0,
      textStyle: { color: isDark ? '#f5f7ff' : '#16233b', fontSize: '0.8125rem', fontWeight: 600 },
      // 提示：数据点可点击下钻明细
      subtext: clickHint,
      subtextStyle: { color: isDark ? '#6f8cb4' : '#94a3b8', fontSize: '0.625rem', lineHeight: 14 },
      itemGap: 2,
    },
    tooltip: {
      ...darkTooltip(isDark), trigger: 'axis',
      valueFormatter: (v: any) => (v === null || v === undefined || Number.isNaN(v)
        ? '-' : `${Number(v).toFixed(2)}${percent ? '%' : ''}`),
    },
    legend: { bottom: 0, textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: '0.625rem' }, itemWidth: 14, itemHeight: 8 },
    // bottom 预留 84px：45° 旋转的日期标签约占 48px，避免与底部图例重叠
    grid: { left: 52, right: 16, top: 46, bottom: 84 },
    xAxis: {
      type: 'category' as const, data: periods, boundaryGap: false,
      axisLabel: { ...axisLabel(isDark), rotate: 45 }, axisLine: axisLine(isDark),
    },
    yAxis: {
      type: 'value' as const, splitLine: splitLine(isDark),
      axisLabel: { ...axisLabel(isDark), formatter: percent ? '{value}%' : '{value}' },
    },
    series: series.map(s => ({
      name: s.name, type: 'line' as const, data: s.data, connectNulls: false,
      lineStyle: { type: 'dashed' as const, width: 1.2, color: s.color },
      itemStyle: { color: s.color },
      symbol: 'circle' as const, symbolSize: 6, showSymbol: true,
      // 数据点可点击（下钻明细）
      cursor: clickHint ? ('pointer' as const) : undefined,
      emphasis: { focus: 'series' as const },
    })),
  }
}

function ScalarTrendChart({ title, rows, percent, scale, nameMap, colors, onDrill }: {
  title: string
  rows: ScalarRow[]
  percent?: boolean
  scale?: number
  nameMap?: Record<string, string>
  colors?: Record<string, string>
  onDrill?: (e: any, seriesName: string, period: string) => void
}) {
  const { isDark } = useTheme()
  const { t } = useI18n()
  const option = useMemo(() => {
    const periods = rows?.length ? Object.keys(rows[0]).filter(k => k !== 'metric').sort() : []
    return trendOption({
      title,
      periods,
      percent,
      isDark,
      clickHint: onDrill ? t('nur.clickDrill') : undefined,
      series: (rows || []).map((r, i) => {
        const name = nameMap?.[r.metric] || r.metric
        return {
          name,
          color: colors?.[name] || WH_COLORS[i % WH_COLORS.length],
          data: periods.map(p => {
            const v = r[p]
            if (typeof v !== 'number') return null
            return +(v * (scale || (percent ? 100 : 1))).toFixed(2)
          }),
        }
      }),
    })
  }, [title, rows, percent, scale, nameMap, colors, isDark, onDrill, t])

  // 点击数据点 → 下钻：seriesName 为显示名（父组件反解 metric/severity），x 轴类目为期间
  const onChartClick = useCallback((params: any, ev: any) => {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'line') return
    const period = params.name
    if (!period) return
    onDrill?.(ev, String(params.seriesName || ''), period)
  }, [onDrill])

  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  // 注意：不能传 lazyUpdate——当前 echarts 版本下 lazy 刷新不会触发绘制，图会空白
  return <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge
    onEvents={onDrill ? { click: onChartClick } : undefined} />
}

// ---------- WO SLA 表：行=TTR/TTR_P1..P4，列=期间 ×（Total/Within SLA/Achieve） ----------
// 数值可点击下钻：severity（TTR→Total）+ item（total/pass/achieve）+ period 传给 /nur/detail
function WoTable({ rows, t, onDrill }: {
  rows: WoRow[]; t: (k: string) => string
  onDrill?: (e: React.MouseEvent, severity: string, item: string, period: string) => void
}) {
  const { periods, data } = useMemo(() => {
    const metrics = ['TTR', 'TTR_P1', 'TTR_P2', 'TTR_P3', 'TTR_P4']
    const byPeriod: Record<string, Record<string, WoRow>> = {}
    for (const r of rows || []) {
      if (!byPeriod[r.period]) byPeriod[r.period] = {}
      byPeriod[r.period][r.metric] = r
    }
    const ps = Object.keys(byPeriod).sort().reverse()
    return {
      periods: ps,
      data: metrics.map(m => {
        const row: any = { key: m, metric: m }
        for (const p of ps) {
          const r = byPeriod[p]?.[m]
          row[`${p}__total`] = r?.total ?? null
          row[`${p}__within`] = r?.within_sla ?? null
          row[`${p}__achieve`] = r?.achieve ?? null
        }
        return row
      }),
    }
  }, [rows])

  const clickable = {
    cursor: 'pointer' as const,
    textDecoration: 'underline dotted rgba(148,163,184,0.55)', textUnderlineOffset: 3,
  }
  const columns = [
    {
      title: 'Metric', dataIndex: 'metric', key: 'metric', fixed: 'left' as const, minWidth: 100,
      render: (v: string) => <Text strong style={{ color: WH.text }}>{v}</Text>,
    },
    ...periods.map(p => ({
      title: p, key: p, align: 'center' as const,
      children: [
        {
          title: t('msSla.total'), dataIndex: `${p}__total`, key: `${p}__total`, minWidth: 84, align: 'right' as const,
          render: (v: number | null, r: any) => (
            <span
              title={onDrill ? t('nur.clickDrill') : undefined}
              onClick={onDrill && v !== null ? (e: React.MouseEvent) => onDrill(e, SLA_SEV[r.metric] || r.metric, 'total', p) : undefined}
              style={{ color: v === null ? WH.textDim : WH.text, ...(onDrill && v !== null ? clickable : undefined) }}
            >
              {fmtNum(v)}
            </span>
          ),
        },
        {
          title: t('msSla.withinSla'), dataIndex: `${p}__within`, key: `${p}__within`, minWidth: 90, align: 'right' as const,
          render: (v: number | null, r: any) => (
            <span
              title={onDrill ? t('nur.clickDrill') : undefined}
              onClick={onDrill && v !== null ? (e: React.MouseEvent) => onDrill(e, SLA_SEV[r.metric] || r.metric, 'pass', p) : undefined}
              style={{ color: v === null ? WH.textDim : WH.text, ...(onDrill && v !== null ? clickable : undefined) }}
            >
              {fmtNum(v)}
            </span>
          ),
        },
        {
          title: t('msSla.achieve'), dataIndex: `${p}__achieve`, key: `${p}__achieve`, minWidth: 88, align: 'right' as const,
          // Achieve 低于目标值标红（参考 Excel 条件格式语义）
          render: (v: number | null, r: any) => (
            <span
              title={onDrill ? t('nur.clickDrill') : undefined}
              onClick={onDrill && v !== null ? (e: React.MouseEvent) => onDrill(e, SLA_SEV[r.metric] || r.metric, 'achieve', p) : undefined}
              style={{
                color: v === null ? WH.textDim : (v >= WO_ACHIEVE_TARGET ? '#51cf66' : '#ff6b6b'),
                fontWeight: v !== null && v < WO_ACHIEVE_TARGET ? 600 : 'normal',
                ...(onDrill && v !== null ? clickable : undefined),
              }}
            >
              {fmtPct(v)}
            </span>
          ),
        },
      ],
    })),
  ]
  return (
    <div className="wh-table-responsive">
      <Table
        size="small" columns={columns} dataSource={data} rowKey="key"
        pagination={false} scroll={{ x: 'max-content', y: TABLE_H }}
        className="dark-table"
      />
    </div>
  )
}

// ---------- WO Achieve 趋势：按严重度拆成 4 张图（P1/P2/P3/P4），每图一条达成率曲线 ----------
// 原先把 TTR + TTR_P1~P4 五条线画在一张图里，P1/P4 常年贴 100%、P2/P3 在 60~95% 波动，
// 同轴下小波动被压平看不出趋势，故拆成分面。TTR（不分严重度的总达成率）不再单独成图 ——
// 它是下面 4 个分级的汇总，已经在 WOs SLA 表格的 TTR 行里可见。
const WO_SEVERITIES = ['TTR_P1', 'TTR_P2', 'TTR_P3', 'TTR_P4'] as const

function WoAchieveTrendChart({ rows, metric, t }: {
  rows: WoRow[]; metric: string; t: (k: string) => string
}) {
  const { isDark } = useTheme()
  const option = useMemo(() => {
    const byPeriod: Record<string, WoRow> = {}
    for (const r of rows || []) {
      if (r.metric === metric) byPeriod[r.period] = r
    }
    const periods = Object.keys(byPeriod).sort()
    const sev = SLA_SEV[metric] || metric
    return trendOption({
      title: sev,
      periods,
      percent: true,
      isDark,
      // 达成率阈值线由 trendOption 之外的 yAxis 处理；这里单序列，颜色取项目统一色板首色
      series: [{
        name: t('msSla.achieve'),
        color: WO_TREND_COLORS[WO_SEVERITIES.indexOf(metric as any) % WO_TREND_COLORS.length],
        data: periods.map(p => {
          const v = byPeriod[p]?.achieve
          return typeof v === 'number' ? +(v * 100).toFixed(2) : null
        }),
      }],
    })
  }, [rows, metric, isDark, t])
  // 该严重度无数据时占位，保持 2×2 网格的行高一致（不塌陷）
  if (!(rows || []).some(r => r.metric === metric)) {
    return <div style={{ height: WO_TREND_H }} />
  }
  return <ReactECharts option={option} style={{ height: WO_TREND_H, width: '100%' }} notMerge />
}

/**
 * MS Operation KPI 看板主体（page=ms_sla：NUR / Network / Per-Site / WO SLA）。
 *
 * SLA 达成率不再单独成卡（2026-09-28 按需求去掉 KPI List SLA 与 SLA Achieve Trend）：
 * 它与下方 WOs SLA 区的数据完全同源（都来自 nur_calc，指标/期间/百分比口径一致），
 * 由 WOs SLA 区以「表格 + 趋势」统一呈现，避免同一组达成率在页面上出现两遍。
 *
 * only 用于派生「只保留 SLA」的直链页面（同一份实现切片，避免复制粘贴走样）：
 *   - only='sla' → 只渲染 WOs SLA 区（SLA 达成率的表格 + 趋势 + 下钻），
 *                  Network / Per-Site / NUR 一律不出，供 page=ms_sla_only 使用；
 *   - only='nur' → 只渲染 KPI List NUR 区（保留给同类切片复用）；
 *   - 缺省       → 全量（NUR + Network + Per-Site + WOs SLA）。
 */
export default function MsSlaDashboard({ only }: { only?: 'nur' | 'sla' } = {}) {
  const { t } = useI18n()
  const isMobile = useIsMobile()
  const showNur = only !== 'sla'
  const showSla = only !== 'nur'
  // Network / Per-Site 既非 NUR 也非 SLA：只在全量模式下出现
  const showOthers = only == null
  const [gran, setGran] = useState<Gran>('daily')
  // Network / Per-Site 来自看板快照库（ms_sla_kpi），只有 daily/monthly 两级 dataset，
  // 周档位下后端返回空表 —— 前端直接不渲染这两块，避免出现空表与空图。
  const isWeekly = gran === 'weekly'
  // 默认区间由粒度档位决定；仅过滤实时计算部分（nur/sla/wo），Network/Per-Site 快照不受影响
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(defaultRange('daily'))
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {}
      if (range && range[0]) params.start = range[0].format('YYYY-MM-DD')
      if (range && range[1]) params.end = range[1].format('YYYY-MM-DD')
      const resp = await getMsSlaOverview(params)
      setData(resp.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  const meta = data?.meta || {}
  const lastSync = meta.last_sync_time ? formatDateTime(meta.last_sync_time) : '-'
  // 卡片标题用短名（Daily / Weekly / Monthly），页签与提示用长名（天 / 周 / 月）
  const granLabel = t(GRAN_LABEL_KEY[gran])
  const granLong = t(GRAN_TAB_KEY[gran])
  const granTitle = useMemo(
    () => Object.fromEntries(GRANS.map(g => [g, t(GRAN_TITLE_KEY[g])])) as Record<Gran, string>,
    [t],
  )
  // 切换 天/周/月 页签：同时把时间范围重置为该档默认窗口（见 defaultRange 注释）
  const changeGran = useCallback((v: Gran) => {
    setGran(v)
    setRange(defaultRange(v))
  }, [])

  // ---------- 下钻（单元格 → TT 明细弹窗，项目统一下钻规范） ----------
  const [drillVisible, setDrillVisible] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillSearch, setDrillSearch] = useState('')
  const [drillTitle, setDrillTitle] = useState('')
  const [drillKey, setDrillKey] = useState('')

  // MS SLA 看板无 vendor/project/exclude 筛选，period 已在 params 中精确定位
  const openDrill = useCallback((e: { clientX: number; clientY: number }, params: Record<string, string>, title: string, key: string) => {
    setDrillAnchor({ x: e.clientX, y: e.clientY })
    setDrillVisible(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillTitle(title)
    setDrillKey(key)
    api.get('/nur/detail', { params })
      .then(res => setDrillData(res.data?.rows || []))
      .catch(() => setDrillData([]))
      .finally(() => setDrillLoading(false))
  }, [])

  const handleNurDrill = (e: React.MouseEvent, g: Gran, tech: string, period: string) => {
    openDrill(e, { metric: 'nur', gran: g, period, tech },
      `${t('nur.drillNur')}: ${tech} · ${period} (${granTitle[g]})`,
      `${tech}_${period}_${g}`)
  }

  const handleSlaDrill = (e: React.MouseEvent, g: Gran, sev: string, item: string, period: string) => {
    openDrill(e, { metric: 'sla', gran: g, period, severity: sev, item },
      `${t('nur.drillSla')}: ${sev} · ${item} · ${period} (${granTitle[g]})`,
      `${sev}_${item}_${period}_${g}`)
  }

  // Per-Site 仅 PS_NUR_2G/PS_NUR_3G 行支持 NUR 下钻（其余 PS_* 为 KPI，不下钻）
  const handlePersiteDrill = (e: React.MouseEvent, g: Gran, metric: string, period: string) => {
    const tech = PERSITE_NUR_TECH[metric]
    if (!tech) return
    handleNurDrill(e, g, tech, period)
  }

  // 下钻弹窗内模糊搜索
  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row =>
      Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
    )
  }, [drillData, drillSearch])

  // 下钻导出 Excel
  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const header = keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const fname = `MS_SLA_${drillKey}_${dayjs().format('YYYYMMDD_HHmmss')}`
    // 统一走 excelReport；sheet 名由模块做非法字符清洗与去重
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `MS_SLA_${drillKey}`,
      title: 'MS SLA Drill-down',
      header,
      rows,
      numericCols: [],
    })
  }, [filteredDrillData, drillKey])

  // ---------- 页面级导出：导出「当前页面显示的全部汇总数据」 ----------
  // 与下钻导出的区别：下钻导出的是弹窗里那批 TT 明细行；
  // 这里导出的是页面上四张标量表（NUR / SLA / Network / Per-Site）+ WO SLA 表的当期值
  // （即当前 天|周|月 粒度下、当前时间范围筛选后的结果），多 sheet 一份文件。
  // only 切片时只导出该切片渲染的块（ms_sla_only 只出 SLA + WO）。
  const exportPageExcel = useCallback(() => {
    if (!data) return
    const sheetSubtitle = [
      `${t('msSla.exportGran')}: ${granLabel}`,
      `${t('msSla.exportRange')}: ${range && range[0] && range[1]
        ? `${range[0].format('YYYY-MM-DD')} ${t('msSla.exportTo')} ${range[1].format('YYYY-MM-DD')}`
        : t('msSla.exportRangeAll')}`,
      `${t('msSla.lastSync')}: ${lastSync}`,
    ].join('    |    ')
    const sheets: ReportSheetSpec[] = []
    // ---------- Sheet1：数据口径（页面顶部那排新鲜度标签 + 当前粒度） ----------
    sheets.push({
      name: 'Overview',
      title: t('msSla.exportTitle'),
      subtitle: sheetSubtitle,
      tabColor: 'FF2F5496',
      header: [t('msSla.exportMetaItem'), t('msSla.exportMetaValue')],
      rows: [
        [t('msSla.exportGran'), granLabel],
        [t('msSla.lastSync'), lastSync],
        [t('msSla.kpiListMtime'), meta.kpi_list_mtime || '—'],
      ],
      columnWidths: [24, 44],
    })
    // ---------- 各 KPI 标量表：行=指标，列=期间（降序，最新在左，与页面同布局） ----------
    // 「取值」sheet 记录该表的口径（NUR 乘 100000 / 其余为百分比），否则拿到文件无法判读量纲
    // sla 块与下方 WOs SLA sheet 同源（都来自 nur_calc 的同一组达成率），故与页面一致地不重复导出。
    const scalarBlocks: { key: string; name: string; rows: ScalarRow[]; cell: (v: any) => number | string; note: string }[] = [
      { key: 'nur', name: t('msSla.exportKpiNur'), rows: data.nur?.[gran] || [], cell: xlNur, note: t('msSla.unit') },
      { key: 'network', name: t('msSla.exportNetwork'), rows: data.network?.[gran] || [], cell: xlPct, note: '%' },
      { key: 'persite', name: t('msSla.exportPersite'), rows: data.persite?.[gran] || [], cell: xlPct, note: '%' },
    ]
    // 「取值」表始终出（page=ms_sla_only 也有 NUR 之外的百分比口径说明；纯 nur 切片下亦为一份说明）
    if (scalarBlocks.some(b => b.rows.length)) {
      sheets.push({
        name: 'Value Scale',
        title: t('msSla.exportMeta'),
        subtitle: sheetSubtitle,
        header: [t('msSla.exportMetaItem'), t('msSla.exportMetaValue')],
        rows: scalarBlocks.map(b => [b.name, b.note]),
        columnWidths: [30, 20],
      })
    }
    for (const b of scalarBlocks) {
      // 空块自动跳过（该粒度下无数据的表不出空 sheet）
      if (!b.rows.length) continue
      const nameMap = b.key === 'nur' ? NUR_NAMES : undefined
      sheets.push({
        name: b.name,
        title: b.name,
        subtitle: sheetSubtitle,
        header: [t('msSla.exportMetric'), ...periodsOf(b.rows)],
        rows: scalarSheetBody(b.rows, nameMap, b.cell),
        columnWidths: [24, ...periodsOf(b.rows).map(() => 16)],
      })
    }
    // ---------- WOs SLA：Total / Within SLA / Achieve 三列一组，按期间分组 ----------
    const woRows = data.wo?.[gran] || []
    if (woRows.length) {
      sheets.push({
        name: t('msSla.exportWo'),
        title: `${t('msSla.exportWo')} (${granLabel})`,
        subtitle: sheetSubtitle,
        header: woSheetHeader(t, woRows),
        rows: woSheetBody(woRows),
        columnWidths: [14, 16, ...woPeriods(woRows).flatMap(() => [14, 14, 14])],
      })
    }
    const fname = `MS_Operation_KPI_${gran}_${dayjs().format('YYYYMMDD_HHmmss')}`
    void exportReport(sheets, `${fname}.xlsx`)
  }, [data, gran, granLabel, range, lastSync, meta.kpi_list_mtime, t])

  // 下钻表格列（动态生成，alarm_occur_time 默认降序）
  const drillColumns = useMemo(() => {
    if (!drillData.length) return []
    const keys = Object.keys(drillData[0])
    return keys.map(k => {
      const col: any = {
        title: k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        dataIndex: k, key: k,
        minWidth: k.includes('time') || k.includes('date') ? 150 : 120,
        ellipsis: true,
        sorter: (a: any, b: any) => strSorter(a, b, k),
        filters: getUniqueFilters(drillData, k),
        onFilter: (v: any, r: any) => String(r[k]) === v,
        defaultSortOrder: k === 'alarm_occur_time' ? 'descend' as const : undefined,
      }
      // MTTR 保留 2 位小数（后端返回原始精度）
      if (k === 'mttr_min') {
        col.render = (v: any) => (v === null || v === undefined ? '-' : Number(v).toFixed(2))
      }
      return col
    })
  }, [drillData])

  return (
    <div style={{ padding: 'var(--wh-space-md)' }}>
      {/* ---------- 顶部：数据新鲜度 + 天/周/月页签 + 时间范围 + 刷新/导出 ---------- */}
      <Card size="small" style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}>
        <Space wrap style={{ gap: 'var(--wh-space-md)' }}>
          <Text style={{ color: WH.textMuted }}>{t('msSla.lastSync')}</Text>
          <Tag color={lastSync !== '-' ? 'cyan' : 'orange'}>{lastSync}</Tag>
          {meta.kpi_list_mtime && (
            <>
              <Text style={{ color: WH.textMuted }}>{t('msSla.kpiListMtime')}</Text>
              <Tag color="geekblue">{meta.kpi_list_mtime}</Tag>
            </>
          )}
          <Segmented
            value={gran}
            onChange={v => changeGran(v as Gran)}
            options={GRANS.map(g => ({ value: g, label: t(GRAN_TAB_KEY[g]) }))}
          />
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.timeRange')}</Text>
            <RangePicker
              value={range as any}
              onChange={v => setRange(v as any)}
              allowClear
              size="small"
              placeholder={[t('nur.start'), t('nur.end')]}
            />
          </Space>
          <Button type="primary" size="small" icon={<ReloadOutlined />} onClick={() => fetchData()}>
            {t('msSla.refresh')}
          </Button>
          {/* 页面级导出：当前粒度 + 当前时间范围下的全部汇总表（多 sheet） */}
          <Button size="small" icon={<DownloadOutlined />} onClick={exportPageExcel} disabled={!data}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </Card>

      {/* 当前档位的时间范围说明（切档会重置区间，这里讲清楚默认窗口，避免误解为丢数据） */}
      <Alert
        type="info" showIcon banner
        message={t('msSla.tabHint', {
          tab: granLong,
          range: range && range[0] && range[1]
            ? `${range[0].format('YYYY-MM-DD')} ~ ${range[1].format('YYYY-MM-DD')}`
            : t('msSla.exportRangeAll'),
        })}
        style={{ marginBottom: 'var(--wh-space-md)' }}
      />

      {error && <Alert type="error" showIcon message={`${t('msSla.loadFailed')}: ${error}`} style={{ marginBottom: 'var(--wh-space-md)' }} />}
      {data && !lastSync && (
        <Alert type="warning" showIcon message={t('msSla.noData')} style={{ marginBottom: 'var(--wh-space-md)' }} />
      )}

      {/* ---------- NUR 计算链路说明（默认收起，点击展开） ----------
          本页也渲染 KPI List NUR（与 NurDashboard 同源同口径），故共用同一份说明，
          避免同一个口径在两页各写一套、日后再分叉。
          只在显示 NUR 时出现：ms_sla_only（only='sla'）不出 NUR，挂上去只会误导。 */}
      {showNur && (
        <NurCalcChainNote
          warnings={data?.warnings}
          warningDetails={data?.warning_details}
          withSla={showSla}
        />
      )}

      <Spin spinning={loading}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
          {/* ---------- KPI List 区（NUR / SLA / Network / Per-Site 各一组表+趋势） ----------
              原「Contract KPIs」外层卡片已按需求去掉：外层与内层卡片两层描边叠在一起
              （2026-09-28 直链页 ms_sla_only 反馈），去掉后语义完全不变，仅少一层容器。 */}
          {showNur && (
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 'var(--wh-space-md)' }}>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
              title={`KPI List NUR ${granLabel}`} extra={<Tag color="cyan" style={{ marginRight: 0 }}>{t('msSla.unit')}</Tag>}>
              <ScalarTable rows={data?.nur?.[gran] || []} fmt={fmtNur} nameMap={NUR_NAMES} colorBy="nur"
                onDrill={(e, m, p) => handleNurDrill(e, gran, NUR_TECH[m] || m, p)} />
            </Card>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
              title={`NUR Trend ${granLabel}`}>
              <ScalarTrendChart title={`NUR Trend ${granLabel}`} rows={data?.nur?.[gran] || []}
                scale={NUR_SCALE} nameMap={NUR_NAMES} colors={NUR_COLORS}
                onDrill={(e, name, p) => handleNurDrill(e, gran, name, p)} />
            </Card>
          </div>
          )}
          {/* SLA 达成率趋势（KPI List SLA / SLA Achieve Trend）已按需求去掉（2026-09-28）：
              它与下方「WOs SLA」区的 WO SLA Achieve Trend 是**同一份数据** —— 两者都来自
              nur_calc 的实时计算，指标（TTR + TTR_P1~P4）、期间、百分比口径完全一致
              （实测 2026-09：TTR 0.8865 / TTR_P1 0.7143 / TTR_P2 0.936 两侧数值相同），
              一并保留会让页面出现两遍同样的达成率。SLA 达成率现在只在下方的 WOs SLA 区
              以「表格 + 趋势」呈现，下钻入口也在那里。 */}
          {/* Network KPIs：表格 + 趋势（既非 NUR 也非 SLA，只在全量模式下渲染；快照库无周粒度） */}
          {showOthers && !isWeekly && (
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 'var(--wh-space-md)' }}>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
              title={`Network KPIs ${granLabel}`}>
              <ScalarTable rows={data?.network?.[gran] || []} fmt={fmtPct} colorBy="percent" />
            </Card>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
              title={`Network KPIs Trend ${granLabel}`}>
              <ScalarTrendChart title={`Network KPIs Trend ${granLabel}`} rows={data?.network?.[gran] || []} percent />
            </Card>
          </div>
          )}
          {/* Per-Site 占比：表格 + 趋势（同上，快照库无周粒度） */}
          {showOthers && !isWeekly && (
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 'var(--wh-space-md)' }}>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
              title={`Per-Site KPIs ${granLabel}`}>
              <ScalarTable rows={data?.persite?.[gran] || []} fmt={fmtPct} colorBy="percent"
                onDrill={(e, m, p) => handlePersiteDrill(e, gran, m, p)} />
            </Card>
            <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
              title={`Per-Site KPIs Trend ${granLabel}`}>
              <ScalarTrendChart title={`Per-Site KPIs Trend ${granLabel}`} rows={data?.persite?.[gran] || []} percent />
            </Card>
          </div>
          )}
          {/* 全量页在周档位下，快照类 KPI 无数据 —— 明说原因，避免被当成加载失败 */}
          {showOthers && isWeekly && (
            <Alert type="warning" showIcon message={t('msSla.weeklyNoSnapshot')} />
          )}
          {/* ---------- WOs SLA 区（工单 SLA 达成，属 SLA 内容：only='sla' 保留、only='nur' 不渲染） ----------
              两块是**并列的独立卡片**（2026-09-28 调整）：趋势此前嵌在 WOs SLA 大卡内部，
              形成「卡中卡」的双层描边，且内层高度受限、4 张分面图挤在半宽里。现在与表格同级，
              趋势图得以撑满整页宽度。 */}
          {showSla && (
          <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-md)' } }}
            title={`${t('msSla.woSla')} · ${granLabel}`}>
            <WoTable rows={data?.wo?.[gran] || []} t={t}
              onDrill={(e, sev, item, p) => handleSlaDrill(e, gran, sev, item, p)} />
          </Card>
          )}
          {/* 按严重度分面：P1/P2 一行、P3/P4 一行（每行 2 图），横向撑满页面 */}
          {showSla && (
          <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
            title={`${t('msSla.woAchieveTrend')} ${granLabel}`}>
            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 'var(--wh-space-md)', width: '100%' }}>
              {WO_SEVERITIES.map(sev => (
                <WoAchieveTrendChart key={sev} rows={data?.wo?.[gran] || []} metric={sev} t={t} />
              ))}
            </div>
          </Card>
          )}
        </div>
      </Spin>

      {/* ---------- 下钻弹窗（点击单元格 → TT 明细） ---------- */}
      <DraggableClickModal
        open={drillVisible}
        anchor={drillAnchor}
        onClose={() => setDrillVisible(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan">{t('common.records', { n: filteredDrillData.length })}</Tag></span>}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: 'var(--wh-space-md)' }}>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('common.searchAllFields')}
            allowClear
            size="middle"
            style={{ width: 'min(100%, 21.875rem)' as any }}
            value={drillSearch}
            onChange={e => setDrillSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={exportToExcel}
            disabled={!filteredDrillData.length}
          >
            {t('common.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: 'var(--wh-space-2xl) auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table
              dataSource={filteredDrillData}
              columns={drillColumns}
              size="small"
              rowKey={(r: any, i?: number) => `${Object.values(r).slice(0, 3).join('-')}-${i}`}
              pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => t('common.itemsTotal', { n: total }) }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </DraggableClickModal>
    </div>
  )
}
