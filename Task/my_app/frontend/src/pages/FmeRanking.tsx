import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, Row, Select, Space, Spin, Statistic, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import {
  DownloadOutlined, ReloadOutlined, SearchOutlined, TrophyOutlined, RightOutlined,
  ArrowUpOutlined, ArrowDownOutlined, WarningOutlined, FireOutlined,
  SafetyOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import {
  getFmeRankingFilters, getFmeRankingOverview,
  getFmeRankingWoDrilldown, getFmeRankingSiteDrilldown,
} from '../api'
import { useI18n, numLocale } from '../i18n'
import DraggableClickModal from '../components/DraggableClickModal'
import { ExplainCorner } from '../components/MetricExplain'
import { useTheme, WH, WH_COLORS, LIGHT_COLORS, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, pageWrap } from '../theme'

const { Text, Title } = Typography

type FmeRow = {
  fme_name: string
  supervisors: string[]
  site_count: number
  sites_with_availability: number
  availability: number | null
  sites_below_threshold: number
  wo_total: number
  wo_open: number
  wo_closed: number
  // SLA 达成率 = (Pass + Within SLA) / (Pass + Failed)；无计入口径记录时为 null
  sla_pass: number
  sla_fail: number
  sla_total: number
  sla_rate: number | null
  sla_ranked: boolean
  availability_rank: number
  wo_rank: number
  sla_rank: number | null
}
type Overview = {
  meta: { month: string; tech: string; threshold: number; generated_at?: string; elapsed_seconds?: number; warnings?: string[]; wo?: { source_rows: number; matched_rows: number; unmatched_rows: number; time_field: string }; sla?: { field: string; counted: number; rule: string } }
  summary: { fme_count: number; site_count: number; sites_with_availability: number; wo_total: number; wo_open: number; wo_closed: number; sla_pass: number; sla_fail: number; sla_total: number; sla_rate: number | null }
  rows: FmeRow[]
}
type Filters = { months?: string[]; supervisors?: string[]; fmes?: string[] }
type DrillColumn = { key: string; zh: string; en: string }

const TECHS = [{ value: 'G', label: '2G' }, { value: 'U', label: '3G' }, { value: 'L', label: '4G' }, { value: 'Tdd', label: 'TDD' }]

const fmt = (value: unknown) => value == null || value === '' ? '-' : String(value)

// ============ olbrportal 风格卡片 ============
// 参考 /olbrportal/ 的 .card：左侧渐变竖条 + 图标徽标 + 标题 + 描述 + meta 行 + hover 高亮，
// 并叠加 AlarmDashboard 的 ExplainCorner / 下钻提示，保证与本项目既有看板视觉一致。
const OlbrCard = ({ rank, rankColor, icon, title, sub, metrics, onClick, explain, hint }: {
  rank?: number
  rankColor?: string
  icon: React.ReactNode
  title: string
  sub?: string
  metrics: { label: string; value: string; color?: string }[]
  onClick: (e: React.MouseEvent) => void
  explain?: string
  hint: string
}) => (
  <Card
    size="small"
    hoverable
    onClick={onClick}
    className="wh-card-interactive"
    style={{ ...cardStyle, cursor: 'pointer', position: 'relative', overflow: 'hidden', height: '100%' }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    {/* olbrportal 的卡片左侧渐变竖条 */}
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
    {explain && <ExplainCorner text={explain} />}

    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--wh-space-sm)' }}>
      {/* 图标徽标（olbr .c-ico） */}
      <span style={{
        display: 'grid', placeItems: 'center', width: 32, height: 32, flexShrink: 0,
        borderRadius: 'var(--wh-radius-sm)', background: WH.teal20,
        color: rankColor || WH.teal, fontSize: '1rem',
      }}>{icon}</span>

      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-xs)' }}>
          {rank != null && (
            <span style={{
              font: '700 0.625rem/1 var(--wh-font-mono, monospace)', letterSpacing: '.08em',
              padding: '3px 6px', borderRadius: 4, flexShrink: 0,
              color: rankColor || WH.teal, background: WH.teal20,
            }}>#{rank}</span>
          )}
          <Tooltip title={title}>
            <span style={{
              fontSize: '0.8125rem', fontWeight: 600, color: WH.text, lineHeight: 1.35,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{title}</span>
          </Tooltip>
        </div>
        {sub && (
          <div style={{
            fontSize: '0.6875rem', color: WH.textDim, marginTop: 3, lineHeight: 1.45,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{sub}</div>
        )}
      </div>
    </div>

    {/* meta 指标行（olbr .meta） */}
    <div style={{
      display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap',
      marginTop: 'var(--wh-space-sm)', fontVariantNumeric: 'tabular-nums',
      fontSize: '0.6875rem', color: WH.textMuted,
    }}>
      {metrics.map((m, i) => (
        <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {i > 0 && <span style={{ opacity: 0.45 }}>·</span>}
          <span style={{ color: m.color || WH.textMuted, fontWeight: m.color ? 700 : 500 }}>{m.value}</span>
          <span>{m.label}</span>
        </span>
      ))}
    </div>

    <div style={{
      textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600,
      marginTop: 6, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2,
    }}>
      {hint} <RightOutlined style={{ fontSize: '0.5625rem' }} />
    </div>
  </Card>
)

// 分区标题（Warehouse 青蓝渐变图标，与 AlarmDashboard 一致）
const SectionTitle = ({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: '0.75rem 0 0.5rem', padding: '0 0 0.5rem',
    borderBottom: '1px solid rgba(0, 217, 255,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 'var(--wh-radius-sm)',
      background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: '0.875rem',
    }}>{icon}</span>
    <span style={{ fontSize: '1rem', fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {sub && <span style={{ fontSize: '0.75rem', color: WH.textDim, marginLeft: 4 }}>{sub}</span>}
  </div>
)

export default function FmeRanking() {
  const { t, locale } = useI18n()
  const { isDark, palette } = useTheme()
  const [filters, setFilters] = useState<Filters>({})
  const [month, setMonth] = useState(() => dayjs().format('YYYY-MM'))
  const [tech, setTech] = useState('L')
  const [supervisor, setSupervisor] = useState('')
  const [fme, setFme] = useState('')
  const [search, setSearch] = useState('')
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ========== 下钻状态 ==========
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillTitle, setDrillTitle] = useState('')
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillTab, setDrillTab] = useState<'sites' | 'wo'>('sites')
  const [drillFme, setDrillFme] = useState('')
  const [siteRows, setSiteRows] = useState<any[]>([])
  const [siteCols, setSiteCols] = useState<DrillColumn[]>([])
  const [siteMeta, setSiteMeta] = useState<{ total: number; truncated?: boolean }>({ total: 0 })
  const [woRows, setWoRows] = useState<any[]>([])
  const [woCols, setWoCols] = useState<DrillColumn[]>([])
  const [woMeta, setWoMeta] = useState<{ total: number; truncated?: boolean }>({ total: 0 })
  const [drillSearch, setDrillSearch] = useState('')
  // 二次下钻：从站点行进入该站点的 WO
  const [siteWoRows, setSiteWoRows] = useState<any[] | null>(null)
  const [siteWoSite, setSiteWoSite] = useState('')
  const [siteWoLoading, setSiteWoLoading] = useState(false)

  useEffect(() => {
    getFmeRankingFilters().then(res => {
      const next = res.data || {}
      setFilters(next)
      if (next.months?.length && !next.months.includes(month)) setMonth(next.months[next.months.length - 1])
    }).catch(() => undefined)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await getFmeRankingOverview({ month, tech, supervisor, fme })
      setData(res.data)
      if (res.data?.error) setError(res.data.error)
    } catch (err: any) {
      setData(null); setError(err?.message || String(err))
    } finally { setLoading(false) }
  }, [month, tech, supervisor, fme])
  useEffect(() => { load() }, [load])

  const rows = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return data?.rows || []
    return (data?.rows || []).filter(row => row.fme_name.toLowerCase().includes(keyword) || row.supervisors.join(' ').toLowerCase().includes(keyword))
  }, [data, search])

  const fmtPct = (value: number | null) => value == null ? '-' : `${(value * 100).toFixed(3)}%`
  const valueColor = (value: number | null) => value != null && value < (data?.meta.threshold ?? 0.9965) ? WH.danger : WH.ok
  // SLA 达成率：百分比显示（1 位小数）；无样本时为 '-'
  const fmtSla = (row: FmeRow) => row.sla_rate == null ? '-' : `${(row.sla_rate * 100).toFixed(1)}%`
  // SLA 颜色：达成率 < 90% 视为需要关注（红），否则绿
  const slaColor = (row: FmeRow) => row.sla_rate == null ? WH.textDim : row.sla_rate < 0.9 ? WH.danger : WH.ok

  // ========== 前/后三名 ==========
  // 可用率口径：剔除无可用率数据的 FME 后再取前后三名（无数据不参与排名）
  const availRanked = useMemo(
    () => (data?.rows || []).filter(r => r.availability != null)
      .slice().sort((a, b) => (b.availability as number) - (a.availability as number)),
    [data])
  const woRanked = useMemo(
    () => (data?.rows || []).slice().sort((a, b) => b.wo_total - a.wo_total || a.fme_name.localeCompare(b.fme_name)),
    [data])
  // SLA 口径：后端已做小样本保护（sla_ranked=false 的不参与名次），前端只取入了榜的
  const slaRanked = useMemo(
    () => (data?.rows || []).filter(r => r.sla_ranked && r.sla_rate != null)
      .slice().sort((a, b) => (b.sla_rate as number) - (a.sla_rate as number) || a.fme_name.localeCompare(b.fme_name)),
    [data])
  const topAvail = useMemo(() => availRanked.slice(0, 3), [availRanked])
  const bottomAvail = useMemo(() => availRanked.slice(-3).reverse(), [availRanked])
  const topWo = useMemo(() => woRanked.slice(0, 3), [woRanked])
  const bottomWo = useMemo(() => woRanked.slice(-3).reverse(), [woRanked])
  const topSla = useMemo(() => slaRanked.slice(0, 3), [slaRanked])
  const bottomSla = useMemo(() => slaRanked.slice(-3).reverse(), [slaRanked])

  // ========== 下钻加载 ==========
  const openFmeDrilldown = useCallback((trigger: any, fmeName: string, tab: 'sites' | 'wo' = 'sites') => {
    let anchor: { x: number; y: number } | null = null
    if (trigger && typeof trigger.clientX === 'number') anchor = { x: trigger.clientX, y: trigger.clientY }
    else if (trigger?.event?.event && typeof trigger.event.event.clientX === 'number') anchor = { x: trigger.event.event.clientX, y: trigger.event.event.clientY }
    setDrillAnchor(anchor)
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillSearch('')
    setSiteWoRows(null); setSiteWoSite('')
    setDrillTab(tab)
    setDrillFme(fmeName)
    setDrillTitle(t('fme.drillFme', { v: fmeName }))
    setSiteRows([]); setWoRows([])

    const common = { month, tech, supervisor, fme: fmeName }
    Promise.all([
      getFmeRankingSiteDrilldown(common),
      getFmeRankingWoDrilldown({ month, supervisor, fme: fmeName }),
    ]).then(([siteRes, woRes]) => {
      setSiteRows(siteRes.data?.rows || [])
      setSiteCols(siteRes.data?.columns || [])
      setSiteMeta({ total: siteRes.data?.total || 0, truncated: siteRes.data?.truncated })
      setWoRows(woRes.data?.rows || [])
      setWoCols(woRes.data?.columns || [])
      setWoMeta({ total: woRes.data?.total || 0, truncated: woRes.data?.truncated })
    }).catch(err => {
      console.error('FME drilldown API error:', err)
      setDrillTitle(t('fme.drillLoadFailed'))
    }).finally(() => setDrillLoading(false))
  }, [month, tech, supervisor, t])

  // 站点行 -> 该站点 WO（二次下钻）
  const openSiteWo = useCallback((siteId: unknown, siteName: unknown) => {
    const label = String(siteName ?? siteId ?? '')
    setSiteWoSite(label)
    setSiteWoLoading(true)
    setSiteWoRows([])
    getFmeRankingWoDrilldown({ month, fme: drillFme, limit: 500 })
      .then(res => {
        const all = res.data?.rows || []
        const sid = String(siteId ?? '').trim()
        const matched = all.filter((r: any) =>
          (sid && String(r.site_id ?? '').trim() === sid) ||
          (!sid && String(r.site_name ?? '').trim().toLowerCase() === label.trim().toLowerCase()))
        setSiteWoRows(matched)
      })
      .catch(err => { console.error('site WO drilldown error:', err); setSiteWoRows([]) })
      .finally(() => setSiteWoLoading(false))
  }, [month, drillFme])

  // 模糊搜索（当前 tab）
  const filterRows = useCallback((list: any[]) => {
    if (!drillSearch.trim()) return list
    const lower = drillSearch.toLowerCase()
    return list.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower)))
  }, [drillSearch])

  const visibleSiteRows = useMemo(() => filterRows(siteRows), [siteRows, filterRows])
  const visibleWoRows = useMemo(() => filterRows(siteWoRows ?? woRows), [siteWoRows, woRows, filterRows])

  // 动态列：用后端返回的 zh/en 标题
  const buildColumns = useCallback((cols: DrillColumn[], list: any[]) => cols.map(col => ({
    title: locale === 'en' ? col.en : col.zh,
    dataIndex: col.key,
    key: col.key,
    minWidth: /time|date/i.test(col.key) ? 150 : 120,
    ellipsis: true,
    sorter: (a: any, b: any) => String(a[col.key] ?? '').localeCompare(String(b[col.key] ?? '')),
    filters: Array.from(new Set(list.map(r => r[col.key]).filter(v => v != null && v !== '')))
      .slice(0, 60).map(v => ({ text: String(v), value: String(v) })),
    onFilter: (v: any, r: any) => String(r[col.key]) === v,
    render: col.key === 'availability'
      ? (v: number | null) => <span style={{ color: valueColor(v), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(v)}</span>
      : col.key === 'wo_total' || col.key === 'wo_open'
        ? (v: number) => <Text strong style={{ color: col.key === 'wo_open' && v ? WH.danger : undefined }}>{fmt(v)}</Text>
        : col.key === 'days_below_threshold'
          ? (v: number) => v ? <Tag color="red">{v}</Tag> : 0
          : undefined,
  })), [locale, valueColor])

  const siteColumns = useMemo(() => {
    const cols = buildColumns(siteCols, visibleSiteRows)
    // 站点名列可点击 -> 继续下钻到该站点 WO
    return cols.map(c => c.key !== 'site_name' ? c : {
      ...c,
      render: (v: unknown, r: any) => (
        <a onClick={e => { e.stopPropagation(); openSiteWo(r.site_id, r.site_name) }} style={{ fontWeight: 600 }}>
          {fmt(v)}
        </a>
      ),
    })
  }, [siteCols, visibleSiteRows, buildColumns, openSiteWo])

  const woColumns = useMemo(() => buildColumns(woCols, visibleWoRows), [woCols, visibleWoRows, buildColumns])

  // 导出当前下钻表
  const exportDrill = useCallback(() => {
    const list = drillTab === 'sites' ? visibleSiteRows : visibleWoRows
    const cols = drillTab === 'sites' ? siteCols : woCols
    if (!list.length) return
    const header = cols.map(c => locale === 'en' ? c.en : c.zh)
    const body = list.map(r => cols.map(c => r[c.key] == null ? '' : String(r[c.key])))
    const ws = XLSX.utils.aoa_to_sheet([header, ...body])
    ws['!cols'] = header.map(() => ({ wch: 18 }))
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, drillTab === 'sites' ? 'Sites' : 'WO')
    XLSX.writeFile(wb, `FME_${drillFme.replace(/[^\w]+/g, '_')}_${drillTab}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [drillTab, visibleSiteRows, visibleWoRows, siteCols, woCols, drillFme, locale])

  const exportRows = useCallback(() => {
    if (!rows.length) return
    const header = [t('fme.col.rank'), t('fme.col.fme'), t('fme.col.supervisor'), t('fme.col.sites'), t('fme.col.availability'), t('fme.col.below'),
      t('fme.col.slaRate'), t('fme.col.slaPass'), t('fme.col.slaFail'), t('fme.col.slaRank'),
      t('fme.col.wo'), t('fme.col.open'), t('fme.col.closed'), t('fme.col.woRank')]
    const body = rows.map(row => [row.availability_rank, row.fme_name, row.supervisors.join(', '), row.site_count, fmtPct(row.availability), row.sites_below_threshold,
      fmtSla(row), `${row.sla_pass}/${row.sla_total}`, row.sla_fail, row.sla_rank ?? '',
      row.wo_total, row.wo_open, row.wo_closed, row.wo_rank])
    const ws = XLSX.utils.aoa_to_sheet([header, ...body]); ws['!cols'] = header.map((_, i) => ({ wch: i === 1 ? 24 : 16 }))
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, 'FME Ranking')
    XLSX.writeFile(wb, `FME_Ranking_${month}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [rows, month, t, fmtSla])

  const chart = useMemo(() => {
    const chartRows = rows.slice(0, 15)
    const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0]?.dataIndex ?? 0
          const row = chartRows[idx]
          if (!row) return ''
          const head = `<div style="font-weight:600;margin-bottom:4px">${row.fme_name}</div>`
          const lines = ps.map((p: any) => {
            const v = p.value
            if (v == null) return `${p.marker} ${p.seriesName}: <strong>-</strong>`
            const isPct = p.seriesName !== t('fme.wo')
            return `${p.marker} ${p.seriesName}: <strong>${isPct ? Number(v).toFixed(3) + '%' : v}</strong>`
          })
          // SLA 明细（pass/total）作为补充信息
          const slaLine = row.sla_total
            ? `<div style="margin-top:3px;opacity:.8">${t('fme.col.slaPass')}: ${row.sla_pass} / ${row.sla_total}</div>`
            : ''
          return head + lines.join('<br/>') + slaLine
        },
      },
      legend: { bottom: 0, textStyle: { color: cTextMuted } },
      grid: { left: 54, right: 58, top: 26, bottom: 58 },
      xAxis: { type: 'category', data: chartRows.map(row => row.fme_name), axisLabel: { ...axisLabel(isDark), rotate: 35, interval: 0 }, axisLine: axisLine(isDark) },
      yAxis: [
        // 左轴：可用率（95~100，放大差异）
        { type: 'value', name: t('fme.axis.availability'), min: 95, max: 100, axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark) },
        // 右轴：WO 数量
        { type: 'value', name: t('fme.axis.wo'), axisLabel: axisLabel(isDark), splitLine: { show: false } },
        // 第三轴（右侧内缩）：SLA 达成率，独立 0~100% 刻度，避免与可用率的 95~100 混淆
        { type: 'value', name: t('fme.axis.sla'), min: 0, max: 100, position: 'right', offset: 44, axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: { show: false } },
      ],
      series: [
        { name: t('fme.availability'), type: 'bar', data: chartRows.map(row => row.availability == null ? null : +(row.availability * 100).toFixed(3)), itemStyle: { color: palette.teal, borderRadius: [4, 4, 0, 0] }, cursor: 'pointer' },
        { name: t('fme.wo'), type: 'line', yAxisIndex: 1, data: chartRows.map(row => row.wo_total), smooth: true, symbol: 'circle', itemStyle: { color: palette.blue }, lineStyle: { width: 2 }, cursor: 'pointer' },
        {
          name: t('fme.slaRate'), type: 'line', yAxisIndex: 2,
          data: chartRows.map(row => row.sla_rate == null ? null : +(row.sla_rate * 100).toFixed(2)),
          smooth: true, symbol: 'circle', symbolSize: 7, connectNulls: false,
          itemStyle: { color: palette.sev.Major },
          lineStyle: { width: 2, type: 'dashed' },
          cursor: 'pointer',
        },
      ],
    }
  }, [rows, isDark, palette, t])

  // 卡片渲染辅助
  // span: 大屏下每张卡占的列数（一行 6 张 = 4）；divider: 在该卡左侧画一条分隔线，
  // 用于把同一行里的 Top 3 与 Bottom 3 分开（第 4 张卡，即 Bottom 的第一张）
  const cardHint = t('fme.drillFmeHint')
  const renderCard = (row: FmeRow, rank: number, kind: 'avail' | 'wo' | 'sla', tone: 'top' | 'bottom', accent: string, icon: React.ReactNode, explain: string, span: number = 4, divider: boolean = false) => (
    <Col
      xs={24} sm={12} lg={span}
      key={`${kind}-${tone}-${row.fme_name}`}
      style={{
        marginBottom: 'var(--wh-space-sm)',
        // 用内左边框 + 内边距做分隔，避免影响栅格宽度导致换行
        borderLeft: divider ? '1px solid rgba(0, 217, 255, 0.25)' : undefined,
        paddingLeft: divider ? 'calc(var(--wh-space-sm) + 4px)' : undefined,
      }}
    >
      <OlbrCard
        rank={rank}
        rankColor={accent}
        icon={icon}
        title={row.fme_name}
        sub={row.supervisors.length ? row.supervisors.join(', ') : t('fme.col.supervisor')}
        explain={explain}
        hint={cardHint}
        metrics={kind === 'avail'
          ? [
              { label: t('fme.col.availability'), value: fmtPct(row.availability), color: accent },
              { label: t('fme.col.slaRate'), value: fmtSla(row), color: slaColor(row) },
              { label: t('fme.stat.sites'), value: String(row.site_count) },
              { label: t('fme.col.below'), value: String(row.sites_below_threshold), color: row.sites_below_threshold ? WH.danger : undefined },
              { label: t('fme.col.wo'), value: String(row.wo_total) },
            ]
          : kind === 'wo'
          ? [
              { label: t('fme.col.wo'), value: String(row.wo_total), color: accent },
              { label: t('fme.col.open'), value: String(row.wo_open), color: row.wo_open ? WH.danger : undefined },
              { label: t('fme.col.slaRate'), value: fmtSla(row), color: slaColor(row) },
              { label: t('fme.col.availability'), value: fmtPct(row.availability) },
              { label: t('fme.stat.sites'), value: String(row.site_count) },
            ]
          : [
              { label: t('fme.col.slaRate'), value: fmtSla(row), color: accent },
              { label: t('fme.col.wo'), value: `${row.sla_pass}/${row.sla_total}`, color: row.sla_fail ? WH.danger : undefined },
              { label: t('fme.col.availability'), value: fmtPct(row.availability) },
              { label: t('fme.col.wo'), value: String(row.wo_total) },
              { label: t('fme.stat.sites'), value: String(row.site_count) },
            ]}
        onClick={(e) => openFmeDrilldown(e, row.fme_name, kind === 'wo' ? 'wo' : 'sites')}
      />
    </Col>
  )

  const columns = [
    { title: t('fme.col.rank'), dataIndex: 'availability_rank', width: 72, sorter: (a: FmeRow, b: FmeRow) => a.availability_rank - b.availability_rank, render: (v: number) => v <= 3 ? <Tag color={v === 1 ? 'gold' : v === 2 ? 'blue' : 'purple'} icon={<TrophyOutlined />}>{v}</Tag> : v },
    { title: t('fme.col.fme'), dataIndex: 'fme_name', fixed: 'left' as const, width: 190, sorter: (a: FmeRow, b: FmeRow) => a.fme_name.localeCompare(b.fme_name), render: (v: string, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'sites')} style={{ fontWeight: 600 }}>{fmt(v)}</a></Tooltip> },
    { title: t('fme.col.supervisor'), dataIndex: 'supervisors', width: 150, render: (v: string[]) => fmt(v?.join(', ')) },
    { title: t('fme.col.sites'), dataIndex: 'site_count', width: 95, sorter: (a: FmeRow, b: FmeRow) => a.site_count - b.site_count, render: (v: number, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'sites')}>{v}</a></Tooltip> },
    { title: t('fme.col.availability'), dataIndex: 'availability', width: 130, sorter: (a: FmeRow, b: FmeRow) => (a.availability ?? -1) - (b.availability ?? -1), render: (v: number | null, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'sites')}><span style={{ color: valueColor(v), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(v)}</span></a></Tooltip> },
    { title: t('fme.col.below'), dataIndex: 'sites_below_threshold', width: 110, sorter: (a: FmeRow, b: FmeRow) => a.sites_below_threshold - b.sites_below_threshold, render: (v: number, row: FmeRow) => v ? <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'sites')}><Tag color="red">{v}</Tag></a></Tooltip> : 0 },
    // SLA 达成率：可下钻到该 FME 的 WO 明细（SLA 状态在 WO 行上）
    { title: t('fme.col.slaRate'), dataIndex: 'sla_rate', width: 125, sorter: (a: FmeRow, b: FmeRow) => (a.sla_rate ?? -1) - (b.sla_rate ?? -1), render: (v: number | null, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'wo')}><span style={{ color: slaColor(row), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtSla(row)}</span></a></Tooltip> },
    { title: t('fme.col.slaPass'), dataIndex: 'sla_pass', width: 110, sorter: (a: FmeRow, b: FmeRow) => a.sla_pass - b.sla_pass, render: (v: number, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'wo')}><span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}/{row.sla_total}</span></a></Tooltip> },
    { title: t('fme.col.slaFail'), dataIndex: 'sla_fail', width: 105, sorter: (a: FmeRow, b: FmeRow) => a.sla_fail - b.sla_fail, render: (v: number, row: FmeRow) => v ? <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'wo')}><Tag color="red">{v}</Tag></a></Tooltip> : 0 },
    { title: t('fme.col.slaRank'), dataIndex: 'sla_rank', width: 110, sorter: (a: FmeRow, b: FmeRow) => (a.sla_rank ?? 0) - (b.sla_rank ?? 0), render: (v: number | null) => v == null ? <Tooltip title={t('fme.slaRankSmallSample')}><Text type="secondary">-</Text></Tooltip> : <Tag color="orange">{v}</Tag> },
    { title: t('fme.col.wo'), dataIndex: 'wo_total', width: 100, sorter: (a: FmeRow, b: FmeRow) => a.wo_total - b.wo_total, render: (v: number, row: FmeRow) => <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'wo')}><Text strong>{v.toLocaleString(numLocale(locale))}</Text></a></Tooltip> },
    { title: t('fme.col.open'), dataIndex: 'wo_open', width: 95, render: (v: number, row: FmeRow) => v ? <Tooltip title={t('fme.drillCellHint')}><a onClick={e => openFmeDrilldown(e, row.fme_name, 'wo')}><Tag color="red">{v}</Tag></a></Tooltip> : 0 },
    { title: t('fme.col.closed'), dataIndex: 'wo_closed', width: 95 },
    { title: t('fme.col.woRank'), dataIndex: 'wo_rank', width: 100, sorter: (a: FmeRow, b: FmeRow) => a.wo_rank - b.wo_rank, render: (v: number) => <Tag color="cyan">{v}</Tag> },
  ]

  return <div style={pageWrap}>
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" style={cardStyle}>
        <Space wrap>
          <Select value={month} onChange={setMonth} options={(filters.months || [month]).map(v => ({ value: v, label: v }))} style={{ width: 130 }} aria-label={t('fme.month')} />
          <Select value={tech} onChange={setTech} options={TECHS.map(item => ({ ...item, label: t(`fme.tech.${item.value}`) }))} style={{ width: 120 }} aria-label={t('fme.tech')} />
          <Select allowClear showSearch value={supervisor || undefined} onChange={v => setSupervisor(v || '')} options={(filters.supervisors || []).map(v => ({ value: v, label: v }))} placeholder={t('fme.supervisor')} style={{ width: 170 }} />
          <Select allowClear showSearch value={fme || undefined} onChange={v => setFme(v || '')} options={(filters.fmes || []).map(v => ({ value: v, label: v }))} placeholder={t('fme.fme')} style={{ width: 170 }} />
          <Input allowClear prefix={<SearchOutlined />} value={search} onChange={e => setSearch(e.target.value)} placeholder={t('fme.search')} style={{ width: 190 }} />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('fme.refresh')}</Button>
          <Button icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>{t('fme.export')}</Button>
        </Space>
      </Card>
      {error && <Alert type="error" showIcon message={error} />}
      {data?.meta.warnings?.map(w => <Alert key={w} type="warning" showIcon message={w} />)}

      {/* ====== 前 / 后三名卡片（置于图表上方；一行 6 张，左 3 张 Top，右 3 张 Bottom） ====== */}
      {!!availRanked.length && (
        <>
          {/* 可用率：一行 6 张 */}
          <Row gutter={[12, 12]} align="stretch" justify="space-between" style={{ marginBottom: 0 }}>
            <Col xs={24} xl={12}>
              <SectionTitle icon={<TrophyOutlined />} title={t('fme.topAvail')} sub={t('fme.topAvailSub')} />
            </Col>
            <Col xs={24} xl={12}>
              <SectionTitle icon={<WarningOutlined />} title={t('fme.bottomAvail')} sub={t('fme.bottomAvailSub')} />
            </Col>
          </Row>
          <Row gutter={[12, 12]} align="stretch">
            {topAvail.map((row, i) => renderCard(row, i + 1, 'avail', 'top', [WH.sev.Warning, WH.blue, WH.indigo][i] || WH.teal, <TrophyOutlined />, t('fme.explain.topAvail'), 4))}
            {bottomAvail.map((row, i) => renderCard(row, availRanked.length - i, 'avail', 'bottom', WH.sev.Critical, <ArrowDownOutlined />, t('fme.explain.bottomAvail'), 4, i === 0))}
          </Row>

          {/* WO：一行 6 张 */}
          <Row gutter={[12, 12]} align="stretch" style={{ marginTop: 'var(--wh-space-sm)', marginBottom: 0 }}>
            <Col xs={24} xl={12}>
              <SectionTitle icon={<FireOutlined />} title={t('fme.topWo')} sub={t('fme.topWoSub')} />
            </Col>
            <Col xs={24} xl={12}>
              <SectionTitle icon={<ArrowDownOutlined />} title={t('fme.bottomWo')} sub={t('fme.bottomWoSub')} />
            </Col>
          </Row>
          <Row gutter={[12, 12]} align="stretch">
            {topWo.map((row, i) => renderCard(row, i + 1, 'wo', 'top', WH.sev.Major, <ArrowUpOutlined />, t('fme.explain.topWo'), 4))}
            {bottomWo.map((row, i) => renderCard(row, woRanked.length - i, 'wo', 'bottom', WH.ok, <ArrowDownOutlined />, t('fme.explain.bottomWo'), 4, i === 0))}
          </Row>

          {/* SLA 达成率：一行 6 张（小样本 FME 已由后端排除，不参与名次） */}
          {!!slaRanked.length && (
            <>
              <Row gutter={[12, 12]} align="stretch" style={{ marginTop: 'var(--wh-space-sm)', marginBottom: 0 }}>
                <Col xs={24} xl={12}>
                  <SectionTitle icon={<SafetyOutlined />} title={t('fme.topSla')} sub={t('fme.topSlaSub')} />
                </Col>
                <Col xs={24} xl={12}>
                  <SectionTitle icon={<ClockCircleOutlined />} title={t('fme.bottomSla')} sub={t('fme.bottomSlaSub')} />
                </Col>
              </Row>
              <Row gutter={[12, 12]} align="stretch">
                {topSla.map((row, i) => renderCard(row, i + 1, 'sla', 'top', WH.ok, <SafetyOutlined />, t('fme.explain.topSla'), 4))}
                {bottomSla.map((row, i) => renderCard(row, slaRanked.length - i, 'sla', 'bottom', WH.sev.Critical, <ClockCircleOutlined />, t('fme.explain.bottomSla'), 4, i === 0))}
              </Row>
            </>
          )}
        </>
      )}

      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} lg={4}><Card style={cardStyle}><Statistic title={t('fme.stat.fme')} value={data?.summary.fme_count || 0} /></Card></Col>
        <Col xs={12} sm={8} lg={4}><Card style={cardStyle}><Statistic title={t('fme.stat.sites')} value={data?.summary.site_count || 0} /></Card></Col>
        <Col xs={12} sm={8} lg={4}><Card style={cardStyle}><Statistic title={t('fme.stat.wo')} value={data?.summary.wo_total || 0} valueStyle={{ color: palette.blue }} /></Card></Col>
        <Col xs={12} sm={8} lg={4}><Card style={cardStyle}><Statistic title={t('fme.stat.open')} value={data?.summary.wo_open || 0} valueStyle={{ color: data?.summary.wo_open ? WH.danger : WH.ok }} /></Card></Col>
        {/* SLA 达成率总览：分子/分母放在 suffix 里说明口径 */}
        <Col xs={12} sm={8} lg={4}>
          <Card style={cardStyle}>
            <Statistic
              title={t('fme.stat.sla')}
              value={data?.summary.sla_rate == null ? '-' : +(data.summary.sla_rate * 100).toFixed(1)}
              suffix={data?.summary.sla_rate == null ? '' : '%'}
              valueStyle={{ color: (data?.summary.sla_rate ?? 1) < 0.9 ? WH.danger : WH.ok }}
            />
            {!!data?.summary.sla_total && (
              <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                {t('fme.stat.slaDetail', { pass: data.summary.sla_pass, total: data.summary.sla_total })}
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}><Card style={cardStyle}><Statistic title={t('fme.stat.slaFail')} value={data?.summary.sla_fail || 0} valueStyle={{ color: data?.summary.sla_fail ? WH.danger : WH.ok }} /></Card></Col>
      </Row>

      <Card title={<Title level={5} style={{ margin: 0, color: WH.text }}>{t('fme.chartTitle')}</Title>} extra={<Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('fme.chartHint')}</Text>} style={cardStyle}>
        {rows.length
          ? <ReactECharts
              option={chart}
              style={{ height: 330 }}
              notMerge
              onEvents={{
                click: (p: any) => { if (p?.name) openFmeDrilldown(p, String(p.name), 'sites') },
              }}
            />
          : <Empty description={t('fme.noData')} />}
      </Card>

      <Card title={t('fme.tableTitle')} extra={<Text type="secondary">{t('fme.generated', { v: data?.meta.generated_at || '-' })}</Text>} style={cardStyle}>
        <Table rowKey="fme_name" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 20, showSizeChanger: true }} scroll={{ x: 1180 }} size="small" />
      </Card>
      {data?.meta.wo && <Text type="secondary">{t('fme.woMeta', { source: data.meta.wo.source_rows, matched: data.meta.wo.matched_rows, unmatched: data.meta.wo.unmatched_rows, field: data.meta.wo.time_field || '-' })}</Text>}
    </Space>

    {/* ====== 下钻弹窗（项目统一风格：DraggableClickModal，跟随主题） ====== */}
    <DraggableClickModal
      open={drillOpen}
      anchor={drillAnchor}
      onClose={() => setDrillOpen(false)}
      width="94%"
      title={
        <span style={{ color: WH.text }}>
          {siteWoSite ? t('fme.drillSiteWo') + ' · ' + siteWoSite : drillTitle}
          {!siteWoSite && <Tag color="cyan" style={{ borderRadius: 10, marginLeft: 8 }}>
            {t('common.records', { n: drillTab === 'sites' ? visibleSiteRows.length : visibleWoRows.length })}
          </Tag>}
        </span>
      }
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('common.searchAllFields')}
          allowClear
          size="middle"
          style={{ width: 'min(100%, 21.875rem)' }}
          value={drillSearch}
          onChange={e => setDrillSearch(e.target.value)}
        />
        <Space>
          {siteWoSite && <Button onClick={() => { setSiteWoSite(''); setSiteWoRows(null) }}>{t('fme.drillBack')}</Button>}
          <Button type="primary" icon={<DownloadOutlined />} onClick={exportDrill}
            disabled={!(drillTab === 'sites' ? visibleSiteRows.length : visibleWoRows.length)}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </div>

      {siteWoSite ? (
        siteWoLoading ? <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
          : <Table dataSource={visibleWoRows} columns={woColumns} size="small"
              rowKey={(r: any) => String(r.wo_no ?? r.tt_no ?? Math.random())}
              pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
              scroll={{ x: 'max-content' }} />
      ) : drillLoading ? (
        <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
      ) : (
        <>
          {(drillTab === 'sites' ? siteMeta.truncated : woMeta.truncated) &&
            <Alert type="warning" showIcon style={{ marginBottom: 8 }}
              message={t('fme.drillTruncated', { n: drillTab === 'sites' ? siteRows.length : woRows.length })} />}
          <Tabs
            activeKey={drillTab}
            onChange={k => setDrillTab(k as 'sites' | 'wo')}
            items={[
              {
                key: 'sites',
                label: `${t('fme.drillTabSites')} (${siteMeta.total})`,
                children: (
                  <Table dataSource={visibleSiteRows} columns={siteColumns} size="small"
                    rowKey={(r: any) => String(r.site_id ?? r.site_name ?? Math.random())}
                    pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: <Empty description={t('fme.drillNoData')} /> }} />
                ),
              },
              {
                key: 'wo',
                label: `${t('fme.drillTabWo')} (${woMeta.total})`,
                children: (
                  <Table dataSource={visibleWoRows} columns={woColumns} size="small"
                    rowKey={(r: any) => String(r.wo_no ?? r.tt_no ?? Math.random())}
                    pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: <Empty description={t('fme.drillNoData')} /> }} />
                ),
              },
            ]}
          />
        </>
      )}
    </DraggableClickModal>
  </div>
}
