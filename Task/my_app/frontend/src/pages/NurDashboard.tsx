import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Card, Table, Select, DatePicker, Button, Space, Spin, Alert, Tag, Tooltip, Typography, Input,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import { ReloadOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons'
import { exportAoaReport } from '../utils/excelReport'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'

const { RangePicker } = DatePicker
const { Text } = Typography

// ---------- ä¸‹é’»è¡¨æ ¼é€šç”¨å·¥å…·ï¼ˆé¡¹ç›®ç»Ÿä¸€ä¸‹é’»è§„èŒƒï¼Œä¸Ž TT&WO Dashboard ä¸€è‡´ï¼‰ ----------
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

// NUR å±•ç¤ºå£å¾„ï¼šåŽŸå§‹å€¼ Ã— 100000ï¼ˆåŽç«¯ä¿æŒåŽŸå§‹æ•°å€¼ï¼Œä»…å‰ç«¯å±•ç¤ºç¼©æ”¾ï¼‰
const NUR_SCALE = 100000

// è¶‹åŠ¿å›¾ç³»åˆ—é…è‰²ï¼ˆæµ…è‰²ä¸»é¢˜ç”¨æ·±è‰²ç³»ä¿è¯å¯¹æ¯”åº¦ï¼‰
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
  elapsed_seconds: number
}
interface OptionsResp {
  vendors: string[]
  projects: string[]
  exclude_options: string[]
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
// NUR æ•°å€¼æ–‡å­—ç€è‰²ï¼š0â†’ä¸»é¢˜æ­£æ–‡è‰²ï¼Œè¶Šå¤§è¶Šåæš–çº¢ï¼ˆæ— èƒŒæ™¯å—ï¼Œä¿è¯æ·±è‰²ä¸»é¢˜å¯è¯»æ€§ï¼‰
function nurTextColor(v: number, max: number): string {
  if (v <= 0 || max <= 0) return WH.textMuted
  const t = Math.min(1, v / max)
  if (t < 0.35) return '#7ecbff'
  if (t < 0.7) return '#ffd43b'
  return '#ff6b6b'
}

const cardStyle: React.CSSProperties = {
  background: WH.cardBg, borderRadius: 'var(--wh-radius-md)', border: '1px solid rgba(0, 217, 255,0.12)',
}
const headStyle: React.CSSProperties = {
  borderBottom: '1px solid rgba(0, 217, 255,0.12)', color: WH.teal, fontSize: '0.8125rem', fontWeight: 600,
}
// è¡¨æ ¼/å›¾è¡¨ç­‰é«˜ï¼Œä¿è¯"è¶‹åŠ¿å›¾å¤§å°è·Ÿè¡¨æ ¼ä¸€æ ·"
const TABLE_H = 240

// ---------- NUR è¡¨ï¼šè¡Œ=æŒ‡æ ‡ï¼Œåˆ—=æœŸé—´ï¼ˆå‡åºï¼Œå·¦â†’å³ä¸Žè¶‹åŠ¿å›¾ X è½´ä¸€è‡´ï¼‰ï¼›æ•°å€¼å¯ç‚¹å‡»ä¸‹é’» ----------
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
        // ç‚¹å‡»å•å…ƒæ ¼ â†’ ä¸‹é’»æž„æˆè¯¥æ•°å€¼çš„ TT æ˜Žç»†
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

// ---------- SLA è¡¨ï¼šè¡Œ=P1..P4/Total Ã—ï¼ˆTotal/Within SLA/Achieveï¼‰ï¼Œåˆ—=æœŸé—´ï¼ˆé™åºï¼Œæœ€æ–°åœ¨å·¦ï¼‰ ----------
// æ•°å€¼å¯ç‚¹å‡»ä¸‹é’»ï¼šseverity + itemï¼ˆtotal/pass/achieveï¼‰+ period ä¼ ç»™ /nur/detail
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

// ---------- è¶‹åŠ¿å›¾ï¼ˆæ·±è‰²åº• + åœ†ç‚¹ + è™šçº¿è¿žæŽ¥ï¼Œé£Žæ ¼å‚è€ƒ FineBI æˆªå›¾ï¼‰ ----------
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
      // æç¤ºï¼šæ•°æ®ç‚¹å¯ç‚¹å‡»ä¸‹é’»æ˜Žç»†
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
    // bottom é¢„ç•™ 84pxï¼š45Â° æ—‹è½¬çš„æ—¥æœŸæ ‡ç­¾çº¦å  48pxï¼Œé¿å…ä¸Žåº•éƒ¨å›¾ä¾‹é‡å 
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
      // æ•°æ®ç‚¹å¯ç‚¹å‡»ï¼ˆä¸‹é’»æ˜Žç»†ï¼‰
      cursor: 'pointer' as const,
      emphasis: { focus: 'series' as const },
    })),
  }
}

// NUR è¶‹åŠ¿ï¼šGlobal/2G/3G/4G/5Gï¼ˆå±•ç¤ºå€¼ Ã—100000ï¼‰ï¼›ç‚¹å‡»æ•°æ®ç‚¹ â†’ ä¸‹é’»æ˜Žç»†
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

  // ç‚¹å‡»æ•°æ®ç‚¹ â†’ ä¸‹é’»ï¼šç³»åˆ—å Global_NUR_Daily â†’ tech=Globalï¼›x è½´ç±»ç›®ä¸ºæœŸé—´
  const onChartClick = useCallback((params: any, ev: any) => {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'line') return
    const period = params.name
    if (!period) return
    const metric = String(params.seriesName || '').replace(`_${cap}`, '')
    onDrill?.(ev, metric.replace('_NUR', ''), period)
  }, [cap, onDrill])

  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  // æ³¨æ„ï¼šä¸èƒ½ä¼  lazyUpdateâ€”â€”å½“å‰ echarts ç‰ˆæœ¬ä¸‹ lazy åˆ·æ–°ä¸ä¼šè§¦å‘ç»˜åˆ¶ï¼Œå›¾ä¼šç©ºç™½
  return (
    <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge
      onEvents={{ click: onChartClick }} />
  )
}

// SLA è¶‹åŠ¿ï¼šP1~P4 + Total è¾¾æˆçŽ‡ï¼ˆ%ï¼‰ï¼›ç‚¹å‡»æ•°æ®ç‚¹ â†’ ä¸‹é’»æ˜Žç»†
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

  // ç‚¹å‡»æ•°æ®ç‚¹ â†’ ä¸‹é’»ï¼šç³»åˆ—å P1_Daily â†’ severity=P1ï¼›è¾¾æˆçŽ‡å¯¹åº”å…¨éƒ¨ TTï¼ˆitem=achieveï¼‰
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
 * NUR çœ‹æ¿ä¸»ä½“ï¼ˆpage=nurï¼šNUR ä¸‰æ¡£ + SLA ä¸‰æ¡£ï¼‰ã€‚
 *
 * only ç”¨äºŽæ´¾ç”Ÿä¸¤ä¸ªã€Œåªä¿ç•™ä¸€åŠã€çš„ç›´é“¾é¡µé¢ï¼ˆåŒä¸€ä»½å®žçŽ°åˆ‡ç‰‡ï¼Œé¿å…å¤åˆ¶ç²˜è´´èµ°æ ·ï¼‰ï¼š
 *   - only='nur' â†’ åªæ¸²æŸ“ NUR æ—¥/å‘¨/æœˆï¼Œä¾› page=ms_nur_only ä½¿ç”¨ï¼›
 *   - only='sla' â†’ åªæ¸²æŸ“ SLA æ—¥/å‘¨/æœˆï¼Œä¾› page=ms_sla_only ä½¿ç”¨ï¼›
 *   - ç¼ºçœ     â†’ NUR + SLA å…¨é‡ï¼Œpage=nur è¡Œä¸ºä¸Žæ”¹é€ å‰å®Œå…¨ä¸€è‡´ã€‚
 * ç­›é€‰æ¡ï¼ˆVendor/Project/Exclude/æ—¶é—´èŒƒå›´ï¼‰ã€TT ä¸‹é’»ä¸Žå¯¼å‡ºä¸¤æ¡ç›´é“¾åŒæ ·å…·å¤‡ã€‚
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
  // é»˜è®¤å±•ç¤ºæœ€è¿‘ 6 ä¸ªæœˆï¼ˆå«ä»Šå¤©ï¼‰
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>([
    dayjs().subtract(6, 'month'), dayjs(),
  ])

  const fetchOverview = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError('')
    try {
      const params: any = {}
      if (vendor) params.vendor = vendor
      if (project) params.project = project
      if (exclude) params.exclude = exclude
      if (range && range[0]) params.start = range[0].format('YYYY-MM-DD')
      if (range && range[1]) params.end = range[1].format('YYYY-MM-DD')
      const resp = await api.get('/nur/overview', { params })
      setData(resp.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [vendor, project, exclude, range])

  useEffect(() => {
    api.get('/nur/options').then(r => setOptions(r.data)).catch(() => {})
  }, [])

  useEffect(() => { fetchOverview() }, [fetchOverview])

  // ---------- ä¸‹é’»ï¼ˆå•å…ƒæ ¼ â†’ TT æ˜Žç»†å¼¹çª—ï¼Œé¡¹ç›®ç»Ÿä¸€ä¸‹é’»è§„èŒƒï¼‰ ----------
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
    // ç»§æ‰¿çœ‹æ¿å½“å‰ç­›é€‰ï¼ˆvendor/project/excludeï¼‰ï¼Œperiod å·²åœ¨ params ä¸­ç²¾ç¡®å®šä½
    const p: Record<string, string> = { ...params }
    if (vendor) p.vendor = vendor
    if (project) p.project = project
    if (exclude) p.exclude = exclude
    api.get('/nur/detail', { params: p })
      .then(res => setDrillData(res.data?.rows || []))
      .catch(() => setDrillData([]))
      .finally(() => setDrillLoading(false))
  }, [vendor, project, exclude])

  const handleNurDrill = (e: React.MouseEvent, g: Gran, tech: string, period: string) => {
    openDrill(e, { metric: 'nur', gran: g, period, tech },
      `${t('nur.drillNur')}: ${tech} Â· ${period} (${granTitle[g]})`,
      `${tech}_${period}_${g}`)
  }

  const handleSlaDrill = (e: React.MouseEvent, g: Gran, sev: string, item: string, period: string) => {
    openDrill(e, { metric: 'sla', gran: g, period, severity: sev, item },
      `${t('nur.drillSla')}: ${sev} Â· ${item} Â· ${period} (${granTitle[g]})`,
      `${sev}_${item}_${period}_${g}`)
  }

  // ä¸‹é’»å¼¹çª—å†…æ¨¡ç³Šæœç´¢
  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row =>
      Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
    )
  }, [drillData, drillSearch])

  // ä¸‹é’»å¯¼å‡º Excel
  // å·²è¿ç»Ÿä¸€æ ¼å¼ UNIFIED_EXCEL_V1ï¼šæ ·å¼ä¸Žé‚®ä»¶æŠ¥è¡¨åŒæºï¼Œè§ docs/EXCEL_EXPORT_STANDARD.md
  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const header = keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const fname = `NUR_${drillKey}_${dayjs().format('YYYYMMDD_HHmmss')}`
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `NUR ${drillKey}`,
      title: `NUR ${drillKey}`,
      header,
      rows,
      columnWidths: keys.map(() => 18),
    })
  }, [filteredDrillData, drillKey])

  // ä¸‹é’»è¡¨æ ¼åˆ—ï¼ˆåŠ¨æ€ç”Ÿæˆï¼Œalarm_occur_time é»˜è®¤é™åºï¼‰
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
      // MTTR ä¿ç•™ 2 ä½å°æ•°ï¼ˆåŽç«¯è¿”å›žåŽŸå§‹ç²¾åº¦ï¼‰
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

  return (
    <div style={{ padding: 'var(--wh-space-md)' }}>
      {/* ---------- ç­›é€‰æ¡ ---------- */}
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
          <Space wrap style={{ gap: 'var(--wh-space-xs)' }}>
            <Text style={{ color: WH.textMuted }}>{t('nur.exclude')}</Text>
            <Select allowClear placeholder={t('nur.all')} value={exclude || undefined}
              onChange={v => setExclude(v || '')} style={{ width: 'min(100%, 5rem)' as any }}
              options={[{ value: 'Y', label: 'Y' }, { value: 'N', label: 'N' }]} />
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
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 'var(--wh-space-md)' }} />}
      {data && data.warnings.length > 0 && (
        <Alert type="warning" showIcon message={data.warnings.join('; ')} style={{ marginBottom: 'var(--wh-space-md)' }} />
      )}
      {exStatus?.error && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-md)' }}
          message={`${t('nur.excludeLoadFail')}: ${exStatus.error}`} />
      )}

      <Spin spinning={loading}>
        {/* ---------- æ¯ä¸ªç²’åº¦ä¸€è¡Œï¼šå·¦è¡¨æ ¼ + å³è¶‹åŠ¿å›¾ï¼ˆNUR ä¸‰è¡Œ + SLA ä¸‰è¡Œï¼›only åˆ‡ç‰‡æ—¶åªå‡ºå…¶ä¸€ï¼‰ ---------- */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
          {/* minmax(0,1fr)ï¼šé˜²æ­¢å®½è¡¨æ ¼æ’‘ç ´ç½‘æ ¼åˆ—ï¼Œè¡¨æ ¼åœ¨å¡ç‰‡å†…æ¨ªå‘æ»šåŠ¨ï¼Œè¶‹åŠ¿å›¾ä¿æŒç­‰å®½ */}
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

      {/* ---------- ä¸‹é’»å¼¹çª—ï¼ˆç‚¹å‡»å•å…ƒæ ¼ â†’ TT æ˜Žç»†ï¼‰ ---------- */}
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
