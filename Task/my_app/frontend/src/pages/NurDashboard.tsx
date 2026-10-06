import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Card, Table, Select, DatePicker, Button, Space, Spin, Alert, Tag, Tooltip, Typography, Input,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import { ReloadOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons'
import { exportAoaReport, exportReport, type ReportSheetSpec } from '../utils/excelReport'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import NurCalcChainNote, { type WarningDetail } from '../components/NurCalcChainNote'

const { RangePicker } = DatePicker
const { Text } = Typography

// ---------- 下钻表格通用工具（项目统一下钻规范，与 TT&WO Dashboard 一致） ----------
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

type Gran = 'daily' | 'weekly' | 'monthly'
const GRANS: Gran[] = ['daily', 'weekly', 'monthly']
const TECHS = ['2G', '3G', '4G', '5G']

/* ---------- 站点维度筛选（2026-09-30 新增，2026-10-05 增补 starlink）----------
 * 列属性全部来自站点主数据 master_site_db（后端 /nur/options 的 site_filters 下发候选值），
 * 顺序即界面上下拉的展示顺序；列名与后端 nur_calc.SITE_FILTER_COLS 一一对应。
 * 过滤同时作用于分子（TT）与分母（小区数），因此切换筛选后 NUR 比值仍是「这批站点的
 * 不可用率」，不是只筛分子得出的假象。
 * starlink_recently_migrated 是 Yes/No 二值列，与其余多值分类共用同一套筛选机制。 */
const SITE_FILTER_COLS = [
  'trm_type', 'site_caregory', 'province_county', 'region', 'starlink_recently_migrated',
] as const
type SiteFilterCol = typeof SITE_FILTER_COLS[number]
// 下拉宽度（按候选值长度给：province_county 有 'Grand Cape Mount' 这类长值）
const SITE_FILTER_WIDTH: Record<SiteFilterCol, string> = {
  trm_type: '8.75rem', site_caregory: '7.5rem', province_county: '10.625rem', region: '7.5rem',
  starlink_recently_migrated: '8.125rem',
}
/**
 * 站点筛选列的 i18n 键映射。
 *
 * 必须是显式 switch 返回字面量键 —— 动态拼 `t('nur.' + col)` 会被 `npm run check:i18n`
 * 读成键名 `nur.` 而报「字典缺失」（见 Task/my_app/AGENTS.md 第三节第 1b 条 /
 * TTWODashboard.tsx 的 advFilterLabelKey 同款处理）。
 */
const siteFilterLabelKey = (col: string): string => {
  switch (col) {
    case 'trm_type': return 'nur.trmType'
    case 'site_caregory': return 'nur.siteCategory'
    case 'province_county': return 'nur.provinceCounty'
    case 'region': return 'nur.region'
    case 'starlink_recently_migrated': return 'nur.starlinkMigrated'
    default: return col
  }
}

// NUR 展示口径：原始值 × 100000（后端保持原始数值，仅前端展示缩放）
const NUR_SCALE = 100000

// 趋势图系列配色（浅色主题用深色系保证对比度）
const NUR_SERIES_COLORS: Record<string, Record<'dark' | 'light', string>> = {
  Global_NUR: { dark: '#258cff', light: '#0284c7' },
  '2G_NUR': { dark: '#7c8ff0', light: '#4f46e5' },
  '3G_NUR': { dark: '#a99cff', light: '#7c3aed' },
  '4G_NUR': { dark: '#0bc78c', light: '#16a34a' },
  '5G_NUR': { dark: '#00d9ff', light: '#0d9488' },
}
const SLA_SERIES_COLORS: Record<string, Record<'dark' | 'light', string>> = {
  P1: { dark: '#ff5c6c', light: '#dc2626' },
  P2: { dark: '#ff922b', light: '#ea580c' },
  P3: { dark: '#f6cf00', light: '#ca8a04' },
  P4: { dark: '#0bc78c', light: '#16a34a' },
  Total: { dark: '#258cff', light: '#0284c7' },
}

interface NurRow { metric: string; [period: string]: number | string | null }
interface SlaRow {
  metric: string; total: number; within_sla: number; achieve: number | null;
  [key: string]: number | string | null
}
interface ExcludeStatus {
  count: number; column: string | null; loaded_at: number | null;
  error: string | null; source: string
}
interface OverviewResp {
  nur: Record<Gran, NurRow[]>
  sla: Record<Gran, SlaRow[]>
  cells_by_tech: Record<string, number>
  denominator_cells: Record<string, number>
  tt_total: number
  exclude: ExcludeStatus
  warnings: string[]
  /** 告警的结构化明细（如未匹配站点清单），供告警条点击展开 */
  warning_details?: WarningDetail[]
  elapsed_seconds: number
}
interface OptionsResp {
  vendors: string[]
  projects: string[]
  exclude_options: string[]
  /** 站点维度筛选候选值：{trm_type|site_caregory|province_county|region|starlink_recently_migrated: [值...]} */
  site_filters?: Record<string, string[]>
  exclude_status: ExcludeStatus
}

function fmtNur(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return (v * NUR_SCALE).toFixed(2)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}
// NUR 数值文字着色：0→主题正文色，越大越偏暖红（无背景块，保证深色主题可读性）
function nurTextColor(v: number, max: number): string {
  if (v <= 0 || max <= 0) return WH.textMuted
  const t = Math.min(1, v / max)
  if (t < 0.35) return '#7ecbff'
  if (t < 0.7) return '#ffd43b'
  return '#ff6b6b'
}

// ---------- 页面级导出：表格数据转 Excel 单元格（口径与页面 fmt* 一致，明细保精度） ----------
// 页面用 '-' 表示「无数据」；导出文件里用 '—'，避免与真实的 0 混淆（项目硬性要求）
// 表格数值保持原始精度（不带单位），与页面表格展示的裸数值一致，便于二次计算
function xlRaw(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v)
}
// NUR 展示口径：× 100000，2 位小数（与页面 fmtNur 一致）
function xlNur(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number((v * NUR_SCALE).toFixed(2))
}
// SLA 达成率口径：0~1 → 百分点，2 位小数（与页面 fmtPct 一致）
function xlPct(v: number | null | undefined): number | string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number((v * 100).toFixed(2))
}
// NUR 表的期间列：与页面 NurTable 一样降序、最新在左
function nurPeriods(rows: NurRow[]): string[] {
  if (!rows || rows.length === 0) return []
  return Object.keys(rows[0]).filter(k => k !== 'metric').sort().reverse()
}
// SLA 表的期间列：页面 SlaTable 从 `<period>__total` 反解期间名，同样降序
function slaPeriods(rows: SlaRow[]): string[] {
  if (!rows || rows.length === 0) return []
  return Object.keys(rows[0]).filter(k => k.endsWith('__total'))
    .map(k => k.replace('__total', '')).sort().reverse()
}
// NUR 表体：行=Global/2G/3G/4G/5G，列=期间（与页面同布局）
function nurSheetBody(rows: NurRow[]): (number | string)[][] {
  const periods = nurPeriods(rows)
  return (rows || []).map(r => [r.metric, ...periods.map(p => xlNur(r[p] as number | null | undefined))])
}
// SLA 表体：行=严重级别 ×（Total / Within SLA / Achieve），列=期间（与页面同布局）
// Total / Within SLA 是工单条数（整数口径），Achieve 是 0~1 达成率 → 百分点
// 三个 item 名复用 msSla.* 键 —— 页面 SlaTable 里它们是英文字面量，导出走 t() 保持可翻译
function slaSheetBody(rows: SlaRow[], t: (k: string) => string): (number | string)[][] {
  const periods = slaPeriods(rows)
  return (rows || []).flatMap(r => [
    [r.metric, t('msSla.total'), ...periods.map(p => xlRaw(r[`${p}__total`] as number | null | undefined))],
    [r.metric, t('msSla.withinSla'), ...periods.map(p => xlRaw(r[`${p}__pass`] as number | null | undefined))],
    [r.metric, t('msSla.achieve'), ...periods.map(p => xlPct(r[`${p}__achieve`] as number | null | undefined))],
  ])
}

const cardStyle: React.CSSProperties = {
  background: WH.cardBg, borderRadius: 'var(--wh-radius-md)', border: '1px solid rgba(0, 217, 255,0.12)',
}
const headStyle: React.CSSProperties = {
  borderBottom: '1px solid rgba(0, 217, 255,0.12)', color: WH.teal, fontSize: '0.8125rem', fontWeight: 600,
}
// 表格/图表等高，保证"趋势图大小跟表格一样"
const TABLE_H = 240

// ---------- NUR 表：行=指标，列=期间（升序，左→右与趋势图 X 轴一致）；数值可点击下钻 ----------
function NurTable({ rows, onDrill }: {
  rows: NurRow[]
  onDrill?: (e: React.MouseEvent, tech: string, period: string) => void
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

  const columns = [
    {
      title: 'Metric', dataIndex: 'metric', key: 'metric', fixed: 'left' as const, minWidth: 110,
      render: (v: string) => <Text strong style={{ color: WH.text }}>{v}</Text>,
    },
    ...periods.map(p => ({
      title: p, dataIndex: p, key: p, minWidth: 92, align: 'right' as const,
      render: (v: number | null, r: NurRow) => {
        if (typeof v !== 'number') {
          return <span style={{ color: WH.textDim }}>-</span>
        }
        // 点击单元格 → 下钻构成该数值的 TT 明细
        return (
          <span
            title={t('nur.clickDrill')}
            onClick={e => onDrill?.(e, String(r.metric).replace('_NUR', ''), p)}
            style={{
              color: nurTextColor(v, maxVal), cursor: 'pointer',
              textDecoration: 'underline dotted rgba(148,163,184,0.55)', textUnderlineOffset: 3,
            }}
          >
            {fmtNur(v)}
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

// ---------- SLA 表：行=P1..P4/Total ×（Total/Within SLA/Achieve），列=期间（降序，最新在左） ----------
// 数值可点击下钻：severity + item（total/pass/achieve）+ period 传给 /nur/detail
function SlaTable({ rows, onDrill }: {
  rows: SlaRow[]
  onDrill?: (e: React.MouseEvent, severity: string, item: string, period: string) => void
}) {
  const { t } = useI18n()
  const periods = useMemo(() => {
    if (!rows || rows.length === 0) return []
    const keys = Object.keys(rows[0]).filter(k => k.endsWith('__total'))
    return keys.map(k => k.replace('__total', '')).sort().reverse()
  }, [rows])

  const data = useMemo(() => {
    const out: any[] = []
    for (const r of rows || []) {
      for (const sub of [['total', 'Total'], ['pass', 'Within SLA'], ['achieve', 'Achieve']]) {
        const [sfx, label] = sub as [string, string]
        const row: any = {
          key: `${r.metric}_${sfx}`, severity: r.metric, metric: label, _item: sfx,
        }
        for (const p of periods) row[p] = r[`${p}__${sfx}`]
        out.push(row)
      }
    }
    return out
  }, [rows, periods])

  const columns = [
    {
      title: 'Severity', dataIndex: 'severity', key: 'severity',
      fixed: 'left' as const, minWidth: 84,
      onCell: (_: any, idx?: number) => ({ rowSpan: idx !== undefined && idx % 3 === 0 ? 3 : 0 }),
      render: (v: string) => (
        <Text strong style={{ color: v === 'Total' ? '#ffd43b' : '#7ecbff' }}>{v}</Text>
      ),
    },
    {
      title: 'Item', dataIndex: 'metric', key: 'metric', fixed: 'left' as const, minWidth: 92,
      render: (v: string) => <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{v}</Text>,
    },
    ...periods.map(p => ({
      title: p, dataIndex: p, key: p, minWidth: 92, align: 'right' as const,
      render: (v: number | null, row: any) => {
        if (typeof v !== 'number') {
          return <span style={{ color: WH.textDim }}>-</span>
        }
        const clickable = {
          cursor: 'pointer' as const,
          textDecoration: 'underline dotted rgba(148,163,184,0.55)', textUnderlineOffset: 3,
        }
        if (row.metric === 'Achieve') {
          const good = v >= 0.95
          return (
            <span
              title={t('nur.clickDrill')}
              onClick={e => onDrill?.(e, row.severity, row._item, p)}
              style={{ color: good ? '#51cf66' : '#ff6b6b', ...clickable }}
            >
              {fmtPct(v)}
            </span>
          )
        }
        return (
          <span
            title={t('nur.clickDrill')}
            onClick={e => onDrill?.(e, row.severity, row._item, p)}
            style={{ color: WH.text, ...clickable }}
          >
            {v}
          </span>
        )
      },
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

// ---------- 趋势图（深色底 + 圆点 + 虚线连接，风格参考 FineBI 截图） ----------
function trendOption(opts: {
  title: string
  periods: string[]
  series: { name: string; color: string; data: (number | null)[] }[]
  percent?: boolean
  tooltipSuffix?: string
  isDark: boolean
  clickHint?: string
}) {
  const { title, periods, series, percent, tooltipSuffix = '', isDark, clickHint } = opts
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
        ? '-' : `${percent ? `${Number(v).toFixed(2)}%` : Number(v).toFixed(2)}${tooltipSuffix}`),
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
      cursor: 'pointer' as const,
      emphasis: { focus: 'series' as const },
    })),
  }
}

// NUR 趋势：Global/2G/3G/4G/5G（展示值 ×100000）；点击数据点 → 下钻明细
function NurTrendChart({ rows, gran, onDrill }: {
  rows: NurRow[]; gran: Gran
  onDrill?: (e: any, tech: string, period: string) => void
}) {
  const { isDark } = useTheme()
  const { t } = useI18n()
  const cap = gran.charAt(0).toUpperCase() + gran.slice(1)
  const option = useMemo(() => {
    const periods = rows?.length
      ? Object.keys(rows[0]).filter(k => k !== 'metric').sort() : []
    return trendOption({
      title: `NUR Trend ${cap}`,
      periods,
      isDark,
      clickHint: t('nur.clickDrill'),
      series: (rows || []).map(r => ({
        name: `${r.metric}_${cap}`,
        color: NUR_SERIES_COLORS[r.metric]?.[isDark ? 'dark' : 'light'] || (isDark ? '#00d9ff' : '#0d9488'),
        data: periods.map(p => {
          const v = r[p]
          return typeof v === 'number' ? +(v * NUR_SCALE).toFixed(2) : null
        }),
      })),
    })
  }, [rows, gran, isDark, t, cap])

  // 点击数据点 → 下钻：系列名 Global_NUR_Daily → tech=Global；x 轴类目为期间
  const onChartClick = useCallback((params: any, ev: any) => {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'line') return
    const period = params.name
    if (!period) return
    const metric = String(params.seriesName || '').replace(`_${cap}`, '')
    onDrill?.(ev, metric.replace('_NUR', ''), period)
  }, [cap, onDrill])

  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  // 注意：不能传 lazyUpdate——当前 echarts 版本下 lazy 刷新不会触发绘制，图会空白
  return (
    <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge
      onEvents={{ click: onChartClick }} />
  )
}

// SLA 趋势：P1~P4 + Total 达成率（%）；点击数据点 → 下钻明细
function SlaTrendChart({ rows, gran, onDrill }: {
  rows: SlaRow[]; gran: Gran
  onDrill?: (e: any, severity: string, item: string, period: string) => void
}) {
  const { isDark } = useTheme()
  const { t } = useI18n()
  const cap = gran.charAt(0).toUpperCase() + gran.slice(1)
  const periods = useMemo(() => {
    if (!rows || rows.length === 0) return []
    return Object.keys(rows[0]).filter(k => k.endsWith('__total'))
      .map(k => k.replace('__total', '')).sort()
  }, [rows])
  const option = useMemo(() => {
    return trendOption({
      title: `SLA Achieve Trend ${cap}`,
      periods, percent: true, isDark,
      clickHint: t('nur.clickDrill'),
      series: (rows || []).map(r => ({
        name: `${r.metric}_${cap}`,
        color: SLA_SERIES_COLORS[r.metric]?.[isDark ? 'dark' : 'light'] || (isDark ? '#00d9ff' : '#0d9488'),
        data: periods.map(p => {
          const v = r[`${p}__achieve`]
          return typeof v === 'number' ? +(v * 100).toFixed(2) : null
        }),
      })),
    })
  }, [rows, gran, periods, isDark, t, cap])

  // 点击数据点 → 下钻：系列名 P1_Daily → severity=P1；达成率对应全部 TT（item=achieve）
  const onChartClick = useCallback((params: any, ev: any) => {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'line') return
    const period = params.name
    if (!period) return
    const severity = String(params.seriesName || '').replace(`_${cap}`, '')
    onDrill?.(ev, severity, 'achieve', period)
  }, [cap, onDrill])

  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  return (
    <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge
      onEvents={{ click: onChartClick }} />
  )
}

/**
 * NUR 看板主体（page=nur：NUR 三档 + SLA 三档）。
 *
 * only 用于派生两个「只保留一半」的直链页面（同一份实现切片，避免复制粘贴走样）：
 *   - only='nur' → 只渲染 NUR 日/周/月，供 page=ms_nur_only 使用；
 *   - only='sla' → 只渲染 SLA 日/周/月，供 page=ms_sla_only 使用；
 *   - 缺省     → NUR + SLA 全量，page=nur 行为与改造前完全一致。
 * 筛选条（Vendor/Project/Exclude/时间范围）、TT 下钻与导出两条直链同样具备。
 */
export default function NurDashboard({ only }: { only?: 'nur' | 'sla' } = {}) {
  const { t } = useI18n()
  const isMobile = useIsMobile()
  const showNur = only !== 'sla'
  const showSla = only !== 'nur'
  const [options, setOptions] = useState<OptionsResp | null>(null)
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [vendor, setVendor] = useState('')
  const [project, setProject] = useState('')
  const [exclude, setExclude] = useState('')
  // 站点维度筛选（trm_type/site_caregory/province_county/region/starlink_recently_migrated），空值=不筛。
  // 用 Record<string,string> 而非键联合类型：与 TTWODashboard 的高级过滤一致，
  // 避免 `{...prev, [col]: v}` 在联合键下被 TS 推成宽泛索引签名。
  const [siteFilters, setSiteFilters] = useState<Record<string, string>>({})
  // 默认展示最近 6 个月（含今天）
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>([
    dayjs().subtract(6, 'month'), dayjs(),
  ])

  /** 当前生效的站点维度筛选（只保留有值的项）——请求、下钻、导出三处共用同一份 */
  const activeSiteFilters = useMemo(() => {
    const out: Record<string, string> = {}
    for (const c of SITE_FILTER_COLS) {
      const v = siteFilters[c]
      if (v) out[c] = v
    }
    return out
  }, [siteFilters])

  const fetchOverview = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError('')
    try {
      const params: any = {}
      if (vendor) params.vendor = vendor
      if (project) params.project = project
      if (exclude) params.exclude = exclude
      Object.assign(params, activeSiteFilters)
      if (range && range[0]) params.start = range[0].format('YYYY-MM-DD')
      if (range && range[1]) params.end = range[1].format('YYYY-MM-DD')
      const resp = await api.get('/nur/overview', { params })
      setData(resp.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [vendor, project, exclude, activeSiteFilters, range])

  useEffect(() => {
    api.get('/nur/options').then(r => setOptions(r.data)).catch(() => {})
  }, [])

  useEffect(() => { fetchOverview() }, [fetchOverview])

  // ---------- 下钻（单元格 → TT 明细弹窗，项目统一下钻规范） ----------
  const [drillVisible, setDrillVisible] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillSearch, setDrillSearch] = useState('')
  const [drillTitle, setDrillTitle] = useState('')
  const [drillKey, setDrillKey] = useState('')

  const openDrill = useCallback((e: { clientX: number; clientY: number }, params: Record<string, string>, title: string, key: string) => {
    setDrillAnchor({ x: e.clientX, y: e.clientY })
    setDrillVisible(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillTitle(title)
    setDrillKey(key)
    // 继承看板当前筛选（vendor/project/exclude + 站点四维），period 已在 params 中精确定位
    // ⚠ 下钻必须与 /overview 逐条同口径，否则「表里的数字」与「下钻的行数」对不上
    const p: Record<string, string> = { ...params }
    // 时间窗：概览把 weekly/monthly 单元格裁到用户选定的窗口，下钻不裁就会返回
    // 整个 ISO 周/自然月（实测 W31 概览 2 / 下钻 1259）。这里与 :515-516 同源同格式。
    if (range && range[0]) p.start = range[0].format('YYYY-MM-DD')
    if (range && range[1]) p.end = range[1].format('YYYY-MM-DD')
    if (vendor) p.vendor = vendor
    if (project) p.project = project
    if (exclude) p.exclude = exclude
    Object.assign(p, activeSiteFilters)
    api.get('/nur/detail', { params: p })
      .then(res => setDrillData(res.data?.rows || []))
      .catch(() => setDrillData([]))
      .finally(() => setDrillLoading(false))
  }, [vendor, project, exclude, activeSiteFilters, range])

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
    const fname = `NUR_${drillKey}_${dayjs().format('YYYYMMDD_HHmmss')}`
    // 统一走 excelReport；sheet 名由模块做非法字符清洗与去重
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `NUR_${drillKey}`,
      title: 'NUR Drill-down',
      header,
      rows,
      numericCols: [],
    })
  }, [filteredDrillData, drillKey])

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

  const granTitle: Record<Gran, string> = {
    daily: t('nur.daily'), weekly: t('nur.weekly'), monthly: t('nur.monthly'),
  }

  const exStatus = data?.exclude || options?.exclude_status
  const exLoaded = exStatus?.loaded_at
    ? dayjs.unix(exStatus.loaded_at).format('MM-DD HH:mm')
    : '-'

  // ---------- 页面级导出：导出「当前页面显示的全部汇总数据」 ----------
  // 与下钻导出的区别：下钻导出的是弹窗里那批 TT 明细行；
  // 这里导出的是页面上的汇总卡（TT 总量 / 分母小区数 / 排除名单）+ NUR 三档表 + SLA 三档表，
  // 全部是当前 Vendor/Project/Exclude/时间范围筛选后的结果，多 sheet 一份文件。
  // 三档粒度一次全出（daily/weekly/monthly），因为它们在页面上是同时可见的；
  // only 切片时只导出该切片渲染的块（ms_nur_only 只出 NUR、NurDashboard 的 only='sla' 只出 SLA）。
  const exportPageExcel = useCallback(() => {
    if (!data) return
    // 筛选条件写进每个 sheet 的副标题，便于对账「这份文件是哪个口径下导出的」
    // 站点四维沿用筛选条同一批标签键（nur.trmType 等），不再另建 exportXxx 重复键
    const filterText = [
      `${t('nur.exportVendor')}: ${vendor || t('nur.all')}`,
      `${t('nur.exportProject')}: ${project || t('nur.all')}`,
      ...SITE_FILTER_COLS.map((c: string) =>
        `${t(siteFilterLabelKey(c))}: ${activeSiteFilters[c] || t('nur.all')}`),
      // 导出件脱离界面语境，裸 "Y"/"N" 会被误读，故写自解释文案
      `${t('nur.exportExclude')}: ${exclude === 'Y' ? t('nur.excludeY')
        : exclude === 'N' ? t('nur.excludeN') : t('nur.excludeAll')}`,
      `${t('nur.exportRange')}: ${range && range[0] && range[1]
        ? `${range[0].format('YYYY-MM-DD')} ${t('nur.exportTo')} ${range[1].format('YYYY-MM-DD')}`
        : t('nur.exportRangeAll')}`,
    ].join('    |    ')
    const sheets: ReportSheetSpec[] = []
    // ---------- Sheet1：汇总（页面上那排标签：TT 总量 / 分母小区数 / 排除名单） ----------
    const denom = data.denominator_cells || {}
    // 后端 build_cell_pivot 恒返回 2G/3G/4G/5G 四键（无该制式小区时为 0），
    // 只有整块缺失才显示 '—'，不把「缺失」误写成 0
    const kv = (k: string) => (denom[k] == null ? '—' : Number(denom[k]))
    sheets.push({
      name: t('nur.exportSummary'),
      title: t('nur.exportTitle'),
      subtitle: filterText,
      tabColor: 'FF2F5496',
      header: [t('nur.exportMetaItem'), t('nur.exportMetaValue')],
      rows: [
        [t('nur.exportTtTotal'), data.tt_total == null ? '—' : Number(data.tt_total)],
        [t('nur.denom'), `2G=${kv('2G')}  3G=${kv('3G')}  4G=${kv('4G')}  5G=${kv('5G')}`],
        [t('nur.exportInclude5g'), denom['5G'] ? t('nur.exportYes') : t('nur.exportNo')],
        [t('nur.exportInclude3g'), denom['3G'] ? t('nur.exportYes') : t('nur.exportNo')],
        [t('nur.exportExcludeCount'), exStatus?.count == null ? '—' : Number(exStatus.count)],
        [t('nur.excludeCol'), exStatus?.column || '—'],
        [t('nur.excludeSrc'), exStatus?.source || '—'],
        [t('nur.exportExcludeLoaded'), exLoaded],
      ],
      columnWidths: [24, 46],
    })
    // ---------- NUR 三档：每档一张（行=Global/2G/3G/4G/5G，列=期间，与页面同布局） ----------
    if (showNur) {
      for (const g of GRANS) {
        const rows = data.nur?.[g] || []
        // 空块自动跳过，不生成空 sheet
        if (!rows.length) continue
        sheets.push({
          name: `${t('nur.exportKpiNur')} ${granTitle[g]}`,
          title: `${t('nur.exportKpiNur')} ${granTitle[g]}`,
          subtitle: `${filterText}    |    ${t('nur.exportGran')}: ${granTitle[g]}    |    ${t('nur.unit')}`,
          header: [t('nur.exportMetric'), ...nurPeriods(rows)],
          rows: nurSheetBody(rows),
          columnWidths: [20, ...nurPeriods(rows).map(() => 14)],
        })
      }
    }
    // ---------- SLA 三档：每档一张（行=严重级别 × Total/Within SLA/Achieve） ----------
    if (showSla) {
      for (const g of GRANS) {
        const rows = data.sla?.[g] || []
        if (!rows.length) continue
        sheets.push({
          name: `${t('nur.exportKpiSla')} ${granTitle[g]}`,
          title: `${t('nur.exportKpiSla')} ${granTitle[g]}`,
          subtitle: `${filterText}    |    ${t('nur.exportGran')}: ${granTitle[g]}`,
          header: [
            t('nur.exportSeverity'), t('nur.exportMetaItem'),
            ...slaPeriods(rows),
          ],
          rows: slaSheetBody(rows, t),
          columnWidths: [14, 16, ...slaPeriods(rows).map(() => 14)],
        })
      }
    }
    const fname = `NUR_Dashboard_${dayjs().format('YYYYMMDD_HHmmss')}`
    void exportReport(sheets, `${fname}.xlsx`)
  }, [data, vendor, project, exclude, activeSiteFilters, range, exStatus, exLoaded, granTitle, showNur, showSla, t])

  return (
    <div style={{ padding: 'var(--wh-space-md)' }}>
      {/* NUR 计算链路说明（默认收起，点击展开；含后端 warnings 常驻告警）。
          内容与 page=ms_sla 共用 NurCalcChainNote，避免同口径两处各写一套后分叉。
          只在显示 NUR 时出现：ms_sla_only 不出 NUR，挂上去只会误导。 */}
      {showNur && (
        <NurCalcChainNote
          warnings={data?.warnings}
          warningDetails={data?.warning_details}
          withSla={showSla}
          style={{ marginBottom: 'var(--wh-space-md)' }}
        />
      )}

      {/* ---------- 筛选条 ---------- */}
      <Card size="small" style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}>
        <Space wrap style={{ gap: 'var(--wh-space-md)' }}>
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.vendor')}</Text>
            <Select allowClear placeholder={t('nur.all')} value={vendor || undefined}
              onChange={v => setVendor(v || '')} style={{ width: 'min(100%, 6.25rem)' as any }}
              options={(options?.vendors || ['ZTE', '3RD']).map(v => ({ value: v, label: v }))} />
          </Space>
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.project')}</Text>
            <Select allowClear placeholder={t('nur.all')} value={project || undefined}
              onChange={v => setProject(v || '')} style={{ width: 'min(100%, 10.625rem)' as any }}
              options={(options?.projects || []).map(v => ({ value: v, label: v }))} />
          </Space>
          {/* 站点维度筛选（trm_type / site_caregory / province_county / region /
              starlink_recently_migrated）：
              候选值由 /nur/options 的 site_filters 下发（站点主数据 master_site_db），
              后端按精确匹配过滤，分子与分母同口径。候选为空的列不渲染下拉。 */}
          {SITE_FILTER_COLS.map(col => {
            const opts = options?.site_filters?.[col] || []
            if (opts.length === 0) return null
            return (
              <Space key={col} wrap style={{ gap: 'var(--wh-space-xs)' }}>
                <Text style={{ color: WH.textMuted }}>{t(siteFilterLabelKey(col))}</Text>
                <Select allowClear showSearch placeholder={t('nur.all')}
                  value={siteFilters[col] || undefined}
                  onChange={v => setSiteFilters(prev => ({ ...prev, [col]: v || '' }))}
                  style={{ width: `min(100%, ${SITE_FILTER_WIDTH[col]})` as any }}
                  options={opts.map(v => ({ value: v, label: v }))}
                  filterOption={(input, option) =>
                    String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
              </Space>
            )
          })}
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.exclude')}</Text>
            {/* 三档语义（2026-10-06 按业务确认）：
                  空值 = 全部参与，不看排除名单；N = 同空值；Y = 从全部里扣掉名单内的单。
                选项写成自解释文案而非裸 'Y'/'N' —— 裸字母正是语义被误读的根源。 */}
            <Select allowClear placeholder={t('nur.excludeAll')} value={exclude || undefined}
              onChange={v => setExclude(v || '')} style={{ width: 'min(100%, 13rem)' as any }}
              options={[
                { value: 'Y', label: t('nur.excludeY') },
                { value: 'N', label: t('nur.excludeN') },
              ]} />
          </Space>
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.timeRange')}</Text>
            <RangePicker value={range as any} onChange={v => setRange(v as any)}
              allowClear placeholder={[t('nur.start'), t('nur.end')]} />
          </Space>
          <Button type="primary" icon={<ReloadOutlined />} onClick={() => fetchOverview()}>
            {t('nur.refresh')}
          </Button>
          {data && (
            <Tooltip title={`${t('nur.cellsByTech')}: ${TECHS.map(k => `${k}=${data.denominator_cells?.[k] ?? 0}`).join('  ')}`}>
              <Tag color="cyan">TT: {data.tt_total}</Tag>
            </Tooltip>
          )}
          {exStatus && (
            <Tooltip title={`${t('nur.excludeCol')}: ${exStatus.column || '-'} | ${t('nur.excludeSrc')}: ${exStatus.source}`}>
              <Tag color={exStatus.error ? 'red' : 'geekblue'}>
                {t('nur.excludeList')}: {exStatus.count} ({exLoaded})
              </Tag>
            </Tooltip>
          )}
          {/* 页面级导出：当前筛选下的汇总卡 + NUR/SLA 各粒度表（多 sheet） */}
          <Button icon={<DownloadOutlined />} onClick={exportPageExcel} disabled={!data}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 'var(--wh-space-md)' }} />}
      {/* data.warnings 已由上方 NurCalcChainNote 的常驻告警渲染（不随收起隐藏），此处不再重复 */}
      {exStatus?.error && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-md)' }}
          message={`${t('nur.excludeLoadFail')}: ${exStatus.error}`} />
      )}

      <Spin spinning={loading}>
        {/* ---------- 每个粒度一行：左表格 + 右趋势图（NUR 三行 + SLA 三行；only 切片时只出其一） ---------- */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
          {/* minmax(0,1fr)：防止宽表格撑破网格列，表格在卡片内横向滚动，趋势图保持等宽 */}
          {showNur && GRANS.map(g => (
            <div key={`nur_${g}`} style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0,1fr) minmax(0,1fr)', gap: 'var(--wh-space-md)' }}>
              <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
                title={`KPI List NUR ${granTitle[g]}`}
                extra={<Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
                  <Tag color="cyan" style={{ marginRight: 0 }}>{t('nur.unit')}</Tag>
                  {data && <Text style={{ color: WH.textMuted, fontSize: '0.6875rem' }}>
                    {t('nur.denom')}: {TECHS.map(k => `${k}=${data.denominator_cells?.[k] ?? 0}`).join(' / ')}
                  </Text>}
                </Space>}>
                <NurTable rows={data?.nur?.[g] || []}
                  onDrill={(e, tech, period) => handleNurDrill(e, g, tech, period)} />
              </Card>
              <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
                title={`NUR Trend ${granTitle[g]}`}>
                <NurTrendChart rows={data?.nur?.[g] || []} gran={g}
                  onDrill={(e, tech, period) => handleNurDrill(e, g, tech, period)} />
              </Card>
            </div>
          ))}
          {showSla && GRANS.map(g => (
            <div key={`sla_${g}`} style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0,1fr) minmax(0,1fr)', gap: 'var(--wh-space-md)' }}>
              <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
                title={`KPI List SLA ${granTitle[g]}`}>
                <SlaTable rows={data?.sla?.[g] || []}
                  onDrill={(e, sev, item, period) => handleSlaDrill(e, g, sev, item, period)} />
              </Card>
              <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
                title={`SLA Trend ${granTitle[g]}`}>
                <SlaTrendChart rows={data?.sla?.[g] || []} gran={g}
                  onDrill={(e, sev, item, period) => handleSlaDrill(e, g, sev, item, period)} />
              </Card>
            </div>
          ))}
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
