import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Card, Table, Segmented, Button, Space, Spin, Alert, Tag, Typography, Input, DatePicker,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import { ReloadOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons'
import { exportAoaReport } from '../utils/excelReport'
import dayjs, { Dayjs } from 'dayjs'
import api, { getMsSlaOverview } from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { useTheme, WH, WH_COLORS, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'

const { Text } = Typography
const { RangePicker } = DatePicker

// ---------- ä¸‹é’»è¡¨æ ¼é€šç”¨å·¥å…·ï¼ˆé¡¹ç›®ç»Ÿä¸€ä¸‹é’»è§„èŒƒï¼Œä¸Ž NurDashboard ä¸€è‡´ï¼‰ ----------
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

type Gran = 'daily' | 'monthly'

// æ ‡é‡æŒ‡æ ‡è¡Œï¼ˆmetric Ã— period é€è§†ï¼Œä¸ŽåŽç«¯ _pivot ç»“æž„å¯¹é½ï¼‰
interface ScalarRow { metric: string; [period: string]: number | string | null }
// WO SLA æ˜Žç»†è¡Œ
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
}

// NUR å±•ç¤ºå£å¾„ï¼šåŽŸå§‹å€¼ Ã— 100000ï¼ˆä¸Ž NurDashboard ä¸€è‡´ï¼‰
const NUR_SCALE = 100000
// WO Achieve ç›®æ ‡å€¼ï¼ˆå‚è€ƒ Excel æ¡ä»¶æ ¼å¼è¯­ä¹‰ï¼šâ‰¥95% è¾¾æ ‡ï¼‰
const WO_ACHIEVE_TARGET = 0.95

// NUR æŒ‡æ ‡æ˜¾ç¤ºåï¼ˆKPI List è¯­ä¹‰ï¼šNUR_NETWORK = Globalï¼‰
const NUR_NAMES: Record<string, string> = {
  NUR_NETWORK: 'Global', NUR_2G: '2G', NUR_3G: '3G', NUR_4G: '4G',
}
const NUR_COLORS: Record<string, string> = {
  Global: '#258cff', '2G': '#7c8ff0', '3G': '#a99cff', '4G': '#51cf66',
}
// NUR æŒ‡æ ‡å â†’ ä¸‹é’» tech å‚æ•°ï¼ˆNUR_NETWORK = Globalï¼‰
const NUR_TECH: Record<string, string> = {
  NUR_NETWORK: 'Global', NUR_2G: '2G', NUR_3G: '3G', NUR_4G: '4G',
}
// SLA æŒ‡æ ‡åï¼ˆKPI List è¯­ä¹‰ TTR/TTR_P1..P4ï¼‰â†’ ä¸‹é’» severity å‚æ•°
const SLA_SEV: Record<string, string> = {
  TTR: 'Total', TTR_P1: 'P1', TTR_P2: 'P2', TTR_P3: 'P3', TTR_P4: 'P4',
}
// Per-Site çš„ NUR è¡Œ â†’ ä¸‹é’» techï¼ˆå…¶ä½™ PS_* æŒ‡æ ‡ä¸æ”¯æŒä¸‹é’»ï¼‰
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
// NUR æ•°å€¼æ–‡å­—ç€è‰²ï¼ˆä¸Ž NurDashboard å®Œå…¨ä¸€è‡´ï¼‰ï¼š0â†’ä¸»é¢˜æ¬¡è¦è‰²ï¼Œè¶Šå¤§è¶Šåæš–çº¢ï¼ˆæ— èƒŒæ™¯å—ï¼Œä¿è¯æ·±è‰²ä¸»é¢˜å¯è¯»æ€§ï¼‰
function nurTextColor(v: number, max: number): string {
  if (v <= 0 || max <= 0) return 'var(--wh-text-muted)'
  const t = Math.min(1, v / max)
  if (t < 0.35) return 'var(--wh-blue)'
  if (t < 0.7) return 'var(--wh-sev-warning)'
  return 'var(--wh-sev-critical)'
}

const cardStyle: React.CSSProperties = {
  background: WH.cardBg, borderRadius: 'var(--wh-radius-md)', border: '1px solid rgba(0, 217, 255,0.12)',
}
const headStyle: React.CSSProperties = {
  borderBottom: '1px solid rgba(0, 217, 255,0.12)', color: WH.teal, fontSize: '0.8125rem', fontWeight: 600,
}
const TABLE_H = 240

// ---------- é€šç”¨æ ‡é‡è¡¨ï¼šè¡Œ=æŒ‡æ ‡ï¼ˆå¯æ˜ å°„æ˜¾ç¤ºåï¼‰ï¼Œåˆ—=æœŸé—´ï¼ˆé™åºï¼Œæœ€æ–°åœ¨å·¦ï¼‰ ----------
// colorBy: 'nur' ç”¨æŒ‰å€¼å¤§å°æ¸å˜ï¼ˆè“â†’é»„â†’çº¢ï¼Œä¸Ž NurDashboard ä¸€è‡´ï¼‰ï¼›'percent' ç”¨è¾¾æˆçŽ‡é˜ˆå€¼ï¼ˆâ‰¥ç›®æ ‡ç»¿/å¦åˆ™çº¢ï¼‰ï¼›ç¼ºçœ WH.text
// onDrill å­˜åœ¨æ—¶æ•°å€¼å•å…ƒæ ¼å¯ç‚¹å‡» â†’ ä¸‹é’» TT æ˜Žç»†ï¼ˆä»… NUR/SLA/Per-Site NUR è¡Œä½¿ç”¨ï¼‰
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
        // ç‚¹å‡»å•å…ƒæ ¼ â†’ ä¸‹é’»æž„æˆè¯¥æ•°å€¼çš„ TT æ˜Žç»†
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

// ---------- é€šç”¨è¶‹åŠ¿å›¾ï¼ˆæ·±è‰²åº• + åœ†ç‚¹è™šçº¿ï¼Œå‚è€ƒ NurDashboard é£Žæ ¼ï¼‰ ----------
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
      // æç¤ºï¼šæ•°æ®ç‚¹å¯ç‚¹å‡»ä¸‹é’»æ˜Žç»†
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

  // ç‚¹å‡»æ•°æ®ç‚¹ â†’ ä¸‹é’»ï¼šseriesName ä¸ºæ˜¾ç¤ºåï¼ˆçˆ¶ç»„ä»¶åè§£ metric/severityï¼‰ï¼Œx è½´ç±»ç›®ä¸ºæœŸé—´
  const onChartClick = useCallback((params: any, ev: any) => {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'line') return
    const period = params.name
    if (!period) return
    onDrill?.(ev, String(params.seriesName || ''), period)
  }, [onDrill])

  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  // æ³¨æ„ï¼šä¸èƒ½ä¼  lazyUpdateâ€”â€”å½“å‰ echarts ç‰ˆæœ¬ä¸‹ lazy åˆ·æ–°ä¸ä¼šè§¦å‘ç»˜åˆ¶ï¼Œå›¾ä¼šç©ºç™½
  return <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge
    onEvents={onDrill ? { click: onChartClick } : undefined} />
}

// ---------- WO SLA è¡¨ï¼šè¡Œ=TTR/TTR_P1..P4ï¼Œåˆ—=æœŸé—´ Ã—ï¼ˆTotal/Within SLA/Achieveï¼‰ ----------
// æ•°å€¼å¯ç‚¹å‡»ä¸‹é’»ï¼šseverityï¼ˆTTRâ†’Totalï¼‰+ itemï¼ˆtotal/pass/achieveï¼‰+ period ä¼ ç»™ /nur/detail
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
          // Achieve ä½ŽäºŽç›®æ ‡å€¼æ ‡çº¢ï¼ˆå‚è€ƒ Excel æ¡ä»¶æ ¼å¼è¯­ä¹‰ï¼‰
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

// ---------- WO Achieve è¶‹åŠ¿ï¼šTTR/TTR_P1..P4 è¾¾æˆçŽ‡ï¼ˆ%ï¼‰ ----------
function WoAchieveTrendChart({ rows }: { rows: WoRow[] }) {
  const { isDark } = useTheme()
  const option = useMemo(() => {
    const metrics = ['TTR', 'TTR_P1', 'TTR_P2', 'TTR_P3', 'TTR_P4'].filter(
      m => (rows || []).some(r => r.metric === m))
    const byPeriod: Record<string, Record<string, WoRow>> = {}
    for (const r of rows || []) {
      if (!byPeriod[r.period]) byPeriod[r.period] = {}
      byPeriod[r.period][r.metric] = r
    }
    const periods = Object.keys(byPeriod).sort()
    return trendOption({
      title: 'WO SLA Achieve Trend',
      periods,
      percent: true,
      isDark,
      series: metrics.map((m, i) => ({
        name: m,
        color: WH_COLORS[i % WH_COLORS.length],
        data: periods.map(p => {
          const v = byPeriod[p]?.[m]?.achieve
          return typeof v === 'number' ? +(v * 100).toFixed(2) : null
        }),
      })),
    })
  }, [rows, isDark])
  if (!rows?.length) return <div style={{ height: TABLE_H + 32 }} />
  return <ReactECharts option={option} style={{ height: TABLE_H + 32, width: '100%' }} notMerge />
}

/**
 * MS Operation KPI çœ‹æ¿ä¸»ä½“ï¼ˆpage=ms_slaï¼šNUR / SLA / Network / Per-Site / WO SLAï¼‰ã€‚
 *
 * only ç”¨äºŽæ´¾ç”Ÿã€Œåªä¿ç•™ SLAã€çš„ç›´é“¾é¡µé¢ï¼ˆåŒä¸€ä»½å®žçŽ°åˆ‡ç‰‡ï¼Œé¿å…å¤åˆ¶ç²˜è´´èµ°æ ·ï¼‰ï¼š
 *   - only='sla' â†’ åªæ¸²æŸ“ KPI List SLAï¼ˆè¾¾æˆçŽ‡è¡¨ + è¶‹åŠ¿ï¼‰ä¸Ž WOs SLA åŒºï¼Œ
 *                  Network / Per-Site / NUR ä¸€å¾‹ä¸å‡ºï¼Œä¾› page=ms_sla_only ä½¿ç”¨ï¼›
 *   - only='nur' â†’ åªæ¸²æŸ“ KPI List NUR åŒºï¼ˆä¿ç•™ç»™åŒç±»åˆ‡ç‰‡å¤ç”¨ï¼‰ï¼›
 *   - ç¼ºçœ       â†’ å…¨é‡ï¼Œpage=ms_sla è¡Œä¸ºä¸Žæ”¹é€ å‰å®Œå…¨ä¸€è‡´ã€‚
 */
export default function MsSlaDashboard({ only }: { only?: 'nur' | 'sla' } = {}) {
  const { t } = useI18n()
  const isMobile = useIsMobile()
  const showNur = only !== 'sla'
  const showSla = only !== 'nur'
  // Network / Per-Site æ—¢éž NUR ä¹Ÿéž SLAï¼šåªåœ¨å…¨é‡æ¨¡å¼ä¸‹å‡ºçŽ°
  const showOthers = only == null
  const [gran, setGran] = useState<Gran>('daily')
  // é»˜è®¤æœ€è¿‘ 6 ä¸ªæœˆï¼ˆå«ä»Šå¤©ï¼‰ï¼Œä¸Ž NUR çœ‹æ¿ä¸€è‡´ï¼›ä»…è¿‡æ»¤å®žæ—¶è®¡ç®—éƒ¨åˆ†
  //ï¼ˆnur/sla/wo/Per-Site ç«™ç‚¹å æ¯”ï¼‰ï¼ŒNetwork/Per-Site å¿«ç…§ä¸å—å½±å“
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>([
    dayjs().subtract(6, 'month'), dayjs(),
  ])
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
  const granLabel = t(gran === 'daily' ? 'msSla.daily' : 'msSla.monthly')
  const granTitle: Record<Gran, string> = {
    daily: t('nur.daily'), monthly: t('nur.monthly'),
  }

  // ---------- ä¸‹é’»ï¼ˆå•å…ƒæ ¼ â†’ TT æ˜Žç»†å¼¹çª—ï¼Œé¡¹ç›®ç»Ÿä¸€ä¸‹é’»è§„èŒƒï¼‰ ----------
  const [drillVisible, setDrillVisible] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillSearch, setDrillSearch] = useState('')
  const [drillTitle, setDrillTitle] = useState('')
  const [drillKey, setDrillKey] = useState('')

  // MS SLA çœ‹æ¿æ—  vendor/project/exclude ç­›é€‰ï¼Œperiod å·²åœ¨ params ä¸­ç²¾ç¡®å®šä½
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
      `${t('nur.drillNur')}: ${tech} Â· ${period} (${granTitle[g]})`,
      `${tech}_${period}_${g}`)
  }

  const handleSlaDrill = (e: React.MouseEvent, g: Gran, sev: string, item: string, period: string) => {
    openDrill(e, { metric: 'sla', gran: g, period, severity: sev, item },
      `${t('nur.drillSla')}: ${sev} Â· ${item} Â· ${period} (${granTitle[g]})`,
      `${sev}_${item}_${period}_${g}`)
  }

  // Per-Site ä»… PS_NUR_2G/PS_NUR_3G è¡Œæ”¯æŒ NUR ä¸‹é’»ï¼ˆå…¶ä½™ PS_* ä¸º KPIï¼Œä¸ä¸‹é’»ï¼‰
  const handlePersiteDrill = (e: React.MouseEvent, g: Gran, metric: string, period: string) => {
    const tech = PERSITE_NUR_TECH[metric]
    if (!tech) return
    handleNurDrill(e, g, tech, period)
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
    const fname = `MS_SLA_${drillKey}_${dayjs().format('YYYYMMDD_HHmmss')}`
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `MS SLA ${drillKey}`,
      title: `MS SLA ${drillKey}`,
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

  return (
    <div style={{ padding: 'var(--wh-space-md)' }}>
      {/* ---------- é¡¶éƒ¨ï¼šæ•°æ®æ–°é²œåº¦ + æ—¥/æœˆåˆ‡æ¢ + åˆ·æ–° ---------- */}
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
            onChange={v => setGran(v as Gran)}
            options={[
              { value: 'daily', label: t('msSla.daily') },
              { value: 'monthly', label: t('msSla.monthly') },
            ]}
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
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={`${t('msSla.loadFailed')}: ${error}`} style={{ marginBottom: 'var(--wh-space-md)' }} />}
      {data && !lastSync && (
        <Alert type="warning" showIcon message={t('msSla.noData')} style={{ marginBottom: 'var(--wh-space-md)' }} />
      )}

      <Spin spinning={loading}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
          {/* ---------- Contract KPIs åŒº ---------- */}
          <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-md)' } }}
            title={`${t('msSla.contractKpis')} Â· ${granLabel}`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
              {/* NURï¼šè¡¨æ ¼ï¼ˆÃ—100000ï¼‰+ è¶‹åŠ¿ï¼ˆonly='sla' æ—¶ä¸æ¸²æŸ“ï¼‰ */}
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
              {/* SLAï¼šè¾¾æˆçŽ‡è¡¨æ ¼ + è¶‹åŠ¿ï¼ˆonly='nur' æ—¶ä¸æ¸²æŸ“ï¼‰ */}
              {showSla && (
              <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 'var(--wh-space-md)' }}>
                <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-sm)' } }}
                  title={`KPI List SLA ${granLabel}`}>
                  <ScalarTable rows={data?.sla?.[gran] || []} fmt={fmtPct} colorBy="percent"
                    onDrill={(e, m, p) => handleSlaDrill(e, gran, SLA_SEV[m] || m, 'achieve', p)} />
                </Card>
                <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
                  title={`SLA Achieve Trend ${granLabel}`}>
                  <ScalarTrendChart title={`SLA Achieve Trend ${granLabel}`} rows={data?.sla?.[gran] || []} percent
                    onDrill={(e, name, p) => handleSlaDrill(e, gran, SLA_SEV[name] || name, 'achieve', p)} />
                </Card>
              </div>
              )}
              {/* Network KPIsï¼šè¡¨æ ¼ + è¶‹åŠ¿ï¼ˆæ—¢éž NUR ä¹Ÿéž SLAï¼Œåªåœ¨å…¨é‡æ¨¡å¼ä¸‹æ¸²æŸ“ï¼‰ */}
              {showOthers && (
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
              {/* Per-Site å æ¯”ï¼šè¡¨æ ¼ + è¶‹åŠ¿ï¼ˆæ—¢éž NUR ä¹Ÿéž SLAï¼Œåªåœ¨å…¨é‡æ¨¡å¼ä¸‹æ¸²æŸ“ï¼‰ */}
              {showOthers && (
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
            </div>
          </Card>

          {/* ---------- WOs SLA åŒºï¼ˆå·¥å• SLA è¾¾æˆï¼Œå±ž SLA å†…å®¹ï¼šonly='sla' ä¿ç•™ã€only='nur' ä¸æ¸²æŸ“ï¼‰ ---------- */}
          {showSla && (
          <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-md)' } }}
            title={`${t('msSla.woSla')} Â· ${granLabel}`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
              <div>
                <WoTable rows={data?.wo?.[gran] || []} t={t}
                  onDrill={(e, sev, item, p) => handleSlaDrill(e, gran, sev, item, p)} />
              </div>
              <div>
                <Card size="small" style={cardStyle} styles={{ header: headStyle, body: { padding: 'var(--wh-space-xs)' } }}
                  title={`WO SLA Achieve Trend ${granLabel}`}>
                  <WoAchieveTrendChart rows={data?.wo?.[gran] || []} />
                </Card>
              </div>
            </div>
          </Card>
          )}
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
