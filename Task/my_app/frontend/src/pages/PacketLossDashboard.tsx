// Packet Loss Dashboard - 丢包看板（参考 RealTime Alarm Map 风格）
// 数据源: lte_pl.sqlite3（RAN UME SDR/IPRAN IPPD 丢包率，最近 7 个完整自然日小时粒度，当天未过完不展示）
// 口径与 Excel 报告（Packet_Loss_Status_Output Automation）完全一致：
//   STATUS = 0~23 标志块（最近 3 天同整点丢包均 >0.5% 记 1）全 0 -> OK，否则 NOK
//   FINAL_STATUS = STATUS=OK 强制 No Packet loss[<0.1]，否则按 Last 1 day Max PL 五级分类
import { useEffect, useState, useMemo, useCallback } from 'react'
import { Card, Row, Col, Tag, Spin, Alert, Empty, Table, Input, Button, Switch, Popover } from 'antd'
import {
  AlertOutlined, WarningOutlined, EnvironmentOutlined,
  PieChartOutlined, BarChartOutlined, DashboardOutlined,
  DownloadOutlined, SearchOutlined, RightOutlined,
  ClockCircleOutlined, CheckCircleOutlined, DisconnectOutlined,
  CopyOutlined, InfoCircleOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import api from '../api'
import { cachedGet } from '../cache'
import DraggableClickModal from '../components/DraggableClickModal'
import { useI18n, numLocale } from '../i18n'
import { WH, DARK, LIGHT, WH_COLORS, LIGHT_COLORS, useTheme, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine, pageWrap, cardStyle } from '../theme'

const STATUS_ORDER = ['Critical[>5]', 'Major[1-5]', 'Minor[0.5-1]', 'Warning[0.1-0.5]', 'No Packet loss[<0.1]']
const STATUS_COLORS: Record<string, string> = {
  'Critical[>5]': '#ff4757',
  'Major[1-5]': '#ff922b',
  'Minor[0.5-1]': '#ffd43b',
  'Warning[0.1-0.5]': '#74c0fc',
  'No Packet loss[<0.1]': '#51cf66',
}
const STATUS_COLORS_LIGHT: Record<string, string> = {
  'Critical[>5]': '#d92d20',
  'Major[1-5]': '#ea580c',
  'Minor[0.5-1]': '#ca8a04',
  'Warning[0.1-0.5]': '#0369a1',
  'No Packet loss[<0.1]': '#15803d',
}
const STATUS_SHORT: Record<string, string> = {
  'Critical[>5]': 'Critical',
  'Major[1-5]': 'Major',
  'Minor[0.5-1]': 'Minor',
  'Warning[0.1-0.5]': 'Warning',
  'No Packet loss[<0.1]': 'OK',
}

// 指标计算说明（鼠标悬停「?」查看，可复制）
const getMetricExplain = (t: (key: string) => string): Record<string, string> => ({
  'Total Sites': t('pl.explain.totalSites'),
  'Critical': t('pl.explain.critical'),
  'Major': t('pl.explain.major'),
  'Minor': t('pl.explain.minor'),
  'Warning': t('pl.explain.warning'),
  'No Packet loss': t('pl.explain.noPacketLoss'),
  'Affected Sites': t('pl.explain.affectedSites'),
  'Data Granularity': t('pl.explain.granularity'),
})

// 拓扑视图：按 backhaul/transport 类型（gateway 字段）聚合站点，
// 每个 gateway 计算质心作为「汇聚节点」，并把每个成员站点连到其最近的同网关邻居，
// 形成 hub-and-spoke 拓扑。以下为各 gateway 的配色。
const GW_COLORS: Record<string, string> = {
  'MW': '#36cfc9',            // 微波
  'Satellite Link': '#ffc53d', // 卫星链路
  'IPRAN': '#9254de',         // IPRAN
  'Start Link': '#ff7a45',    // Start Link
}
const gwColor = (gw: string) => GW_COLORS[gw] || '#8c8c8c'

const CHART_HEIGHT = 280

const SectionTitle = ({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: '1.375rem 0 0.875rem', padding: '0 0 0.625rem',
    borderBottom: '1px solid rgba(100,255,218,0.18)',
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

// 通用「计算说明」悬停气泡（带复制）。供指标卡以外的地方（如头部 Affected Sites 标签）复用
const MetricExplainPopover = ({ text, children, t }: { text: string; children: React.ReactNode; t: (key: string) => string }) => {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
      else {
        const ta = document.createElement('textarea')
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
      }
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }, [text])
  if (!text) return <>{children}</>
  return (
    <Popover trigger="hover" placement="bottom" mouseEnterDelay={0.1}
      content={
        <div style={{ maxWidth: '18.75rem', fontSize: '0.75rem', lineHeight: 1.7 }}>
          <div style={{ color: WH.textMuted, whiteSpace: 'pre-line' }}>{text}</div>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={copy}
            style={{ paddingLeft: 0, marginTop: 'var(--wh-space-sm)', height: 'auto', color: WH.teal }}>
            {copied ? t('pl.copied') : t('pl.copyExplain')}
          </Button>
        </div>
      }>
      {children}
    </Popover>
  )
}

const SummaryCard = ({ icon, value, label, color, onClick, explain, t }: {
  icon: React.ReactNode; value: string | number; label: string; color: string; onClick: () => void; explain?: string; t: (key: string) => string
}) => {
  const [copied, setCopied] = useState(false)
  const copyExplain = useCallback(async () => {
    if (!explain) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(explain)
      } else {
        const ta = document.createElement('textarea')
        ta.value = explain
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }, [explain])

  return (
    <Card size="small" hoverable onClick={onClick} className="wh-card-interactive" style={{
      ...cardStyle,
      cursor: 'pointer', transition: 'all .2s', position: 'relative', overflow: 'hidden',
    }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
    >
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: color, opacity: 0.9 }} />
      {explain && (
        <Popover
          trigger="hover"
          placement="top"
          mouseEnterDelay={0.1}
          content={
            <div style={{ maxWidth: '17.5rem', fontSize: '0.75rem', lineHeight: 1.7 }}>
              <div style={{ fontWeight: 700, color: WH.teal, marginBottom: 'var(--wh-space-xs)' }}>{label} · {t('pl.calcExplain')}</div>
              <div style={{ color: WH.textMuted, whiteSpace: 'pre-line' }}>{explain}</div>
              <Button size="small" type="link" icon={<CopyOutlined />} onClick={copyExplain}
                style={{ paddingLeft: 0, marginTop: 'var(--wh-space-sm)', height: 'auto', color: WH.teal }}>
                {copied ? t('pl.copied') : t('pl.copyExplain')}
              </Button>
            </div>
          }
        >
          <span
            onClick={e => e.stopPropagation()}
            style={{ position: 'absolute', top: 6, right: 8, zIndex: 2, cursor: 'help', color: WH.textDim, fontSize: '0.8125rem' }}
          >
            <InfoCircleOutlined />
          </span>
        </Popover>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '1.875rem', fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
          <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginTop: 'var(--wh-space-xs)', fontWeight: 500 }}>{label}</div>
        </div>
        <span style={{ fontSize: '2.375rem', opacity: 0.16, color }}>{icon}</span>
      </div>
      <div style={{ textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
        {t('pl.clickDrill')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
      </div>
    </Card>
  )
}

const strSorter = (a: any, b: any, key: string) => String(a[key] ?? '').localeCompare(String(b[key] ?? ''))
const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

interface PlSite {
  site_name: string; site_code: string; lat: number; lng: number
  region: string; province_county: string; gateway: string; network_type: string
  status: string; last_day_max_pl: number; total_pl: number; affected_hours: number
}

export default function PacketLossDashboard() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const isMobile = useIsMobile()
  const METRIC_EXPLAIN = useMemo(() => getMetricExplain(t), [t])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<any>(null)
  const [mapSites, setMapSites] = useState<PlSite[]>([])
  // 默认显示 OK 站点（include_ok=true），地图展示全量有坐标站点
  const [includeOk, setIncludeOk] = useState(true)
  const [hiddenStatuses, setHiddenStatuses] = useState<Set<string>>(new Set())
  // 拓扑显示开关：开启后复用 GIS Map 的真实拓扑链路（/api/gis/topology），按传输类型着色
  const [showTopology, setShowTopology] = useState(false)
  const [gisTopology, setGisTopology] = useState<any[]>([])
  useEffect(() => {
    if (showTopology && gisTopology.length === 0) {
      api.get('/gis/topology')
        .then(res => setGisTopology(res.data.links || []))
        .catch(() => {})
    }
  }, [showTopology])
  const toggleStatusVisible = useCallback((st: string) => {
    setHiddenStatuses(prev => {
      const next = new Set(prev)
      if (next.has(st)) next.delete(st); else next.add(st)
      return next
    })
  }, [])

  // 下钻
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillTitle, setDrillTitle] = useState('')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillTotal, setDrillTotal] = useState(0)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      cachedGet('pl:overview', () => api.get('/packet-loss-dashboard/overview')),
      cachedGet(`pl:map:${includeOk}`, () => api.get('/packet-loss-dashboard/map-sites', { params: { include_ok: includeOk } })),
    ])
      .then(([ov, mp]) => {
        setData(ov.data)
        setMapSites(mp.data.sites || [])
        setError(null)
      })
      .catch(err => { console.error('Packet Loss API error:', err); setError(err.message || 'Failed to load') })
      .finally(() => setLoading(false))
  }, [includeOk])

  const openDrilldown = useCallback((trigger: any, status: string, title: string) => {
    let anchor: { x: number; y: number } | null = null
    if (trigger && typeof trigger.clientX === 'number') {
      anchor = { x: trigger.clientX, y: trigger.clientY }
    } else if (trigger?.event?.event && typeof trigger.event.event.clientX === 'number') {
      anchor = { x: trigger.event.event.clientX, y: trigger.event.event.clientY }
    }
    setDrillAnchor(anchor)
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillTitle(title)
    api.get('/packet-loss-dashboard/drilldown', { params: { status, limit: 800 } })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTotal(res.data.total || 0)
      })
      .catch(() => setDrillTitle('Failed to load data'))
      .finally(() => setDrillLoading(false))
  }, [])

  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower)))
  }, [drillData, drillSearch])

  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const ws = XLSX.utils.aoa_to_sheet([keys, ...rows])
    ws['!cols'] = keys.map(() => ({ wch: 18 }))
    const wb = XLSX.utils.book_new()
    const fname = `PacketLoss_${dayjs().format('YYYYMMDD_HHmmss')}`
    XLSX.utils.book_append_sheet(wb, ws, fname.substring(0, 31))
    XLSX.writeFile(wb, `${fname}.xlsx`)
  }, [filteredDrillData])

  const drillColumns = useMemo(() => {
    if (!drillData.length) return []
    return Object.keys(drillData[0]).map(k => ({
      title: k.replace(/_/g, ' '),
      dataIndex: k,
      key: k,
      minWidth: 130,
      ellipsis: true,
      sorter: (a: any, b: any) => strSorter(a, b, k),
      filters: getUniqueFilters(drillData, k),
      onFilter: (v: any, r: any) => String(r[k]) === v,
    }))
  }, [drillData])

  // ========== 图表配置 ==========
  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const cText = isDark ? '#e6f4ff' : '#16233b'
  const cTextMuted = isDark ? '#94a3b8' : '#3f5468'
  const cTeal = isDark ? '#64ffda' : '#0d9488'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
  const statusColors = isDark ? STATUS_COLORS : STATUS_COLORS_LIGHT

  const statusPieOption = useMemo(() => {
    if (!data?.status_pie) return {}
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}<br/>{c} sites ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['38%', '65%'], center: ['38%', '50%'],
        data: data.status_pie.map((s: any) => ({
          name: s.status, value: s.count, itemStyle: { color: statusColors[s.status] || cTeal },
        })),
        label: { fontSize: 10, color: cText, formatter: '{c}' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.4)' : 'rgba(13,148,136,0.35)' } },
      }],
    }
  }, [data, isDark, statusColors, cText, cTextMuted, cTeal])

  const regionOption = useMemo(() => {
    if (!data?.region_dist) return {}
    const entries = Object.entries(data.region_dist) as [string, any][]
    if (!entries.length) return {}
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const b = entries[idx][1]
          return `<div style="font-weight:600;margin-bottom:4px">${entries[idx][0]}</div>` +
            `Affected Sites: <strong>${b.sites}</strong><br/>Critical: <strong>${b.critical}</strong><br/>Max PL: <strong>${b.max_pl.toFixed(2)}%</strong>`
        },
      },
      grid: { left: 40, right: 20, top: 10, bottom: 40 },
      xAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { ...axisLabel(isDark), rotate: 30 }, axisLine: axisLine(isDark) },
      yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [{
        type: 'bar', barMaxWidth: 28,
        data: entries.map(([, b], i) => ({
          value: b.sites,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: i === 0 ? (isDark ? '#ff4757' : '#d92d20') : cTeal }, { offset: 1, color: isDark ? '#0d2138' : '#dcebf5' }] },
            borderRadius: [4, 4, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 10, color: cTextMuted, fontWeight: 600 },
      }],
    }
  }, [data, isDark, cTextMuted, cTeal])

  const trendOption = useMemo(() => {
    if (!data?.daily_trend?.length) return {}
    const days = data.daily_trend.map((d: any) => d.day.slice(5))
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
      legend: { data: [t('pl.median'), t('pl.affectedSites')], bottom: 0, textStyle: { fontSize: 11, color: cTextMuted } },
      grid: { left: 50, right: 50, top: 20, bottom: 50 },
      xAxis: { type: 'category', data: days, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark) },
      yAxis: [
        { type: 'value', name: t('pl.axis'), splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
        { type: 'value', name: t('pl.sites'), splitLine: { show: false }, axisLabel: axisLabel(isDark) },
      ],
      series: [
        {
          name: t('pl.median'), type: 'bar', barMaxWidth: 22,
          data: data.daily_trend.map((d: any) => d.median_pl),
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? '#64ffda' : '#0d9488' }, { offset: 1, color: isDark ? '#4fc3f7' : '#0284c7' }] },
            borderRadius: [4, 4, 0, 0],
          },
          label: { show: true, position: 'top', fontSize: 10, color: cTextMuted, formatter: (p: any) => `${p.value}%` },
        },
        {
          name: t('pl.affectedSites'), type: 'line', yAxisIndex: 1, smooth: true,
          data: data.daily_trend.map((d: any) => d.affected_sites),
          lineStyle: { color: isDark ? '#ff922b' : '#ea580c', width: 2 }, itemStyle: { color: isDark ? '#ff922b' : '#ea580c' }, symbolSize: 6,
        },
      ],
    }
  }, [data, t, isDark, cTextMuted])

  const topSitesOption = useMemo(() => {
    if (!data?.top_sites?.length) return {}
    const sites = data.top_sites.slice(0, 12).reverse()
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const s = sites[idx]
          return `<div style="font-weight:600;margin-bottom:4px">${s.site_name}</div>` +
            `Status: <strong>${STATUS_SHORT[s.status] || s.status}</strong><br/>` +
            `Last-1-day Median PL: <strong>${s.last_day_median_pl}%</strong><br/>` +
            `Last-1-day Max PL: ${s.last_day_max_pl}%<br/>` +
            `Affected Hours: <strong>${s.affected_hours}</strong><br/>Region: ${s.region || '-'}`
        },
      },
      grid: { left: 20, right: 60, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: {
        type: 'category',
        data: sites.map((s: any) => s.site_name.length > 18 ? s.site_name.slice(0, 16) + '..' : s.site_name),
        axisLabel: { ...axisLabel(isDark), color: cText }, axisLine: axisLine(isDark),
      },
      series: [{
        type: 'bar', barMaxWidth: 16,
        data: sites.map((s: any) => ({
          value: s.last_day_median_pl,
          itemStyle: { color: statusColors[s.status] || cTeal, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => `${p.value}%` },
      }],
    }
  }, [data, isDark, statusColors, cText, cTextMuted, cTeal])

  // 图例过滤：隐藏选中的状态 → 地图上不渲染对应站点
  // 必须放在 early-return 之前，保证 hook 调用顺序在每次渲染都一致（否则会改变 hook 数量 → 组件崩溃）
  const visibleSites = useMemo(
    () => mapSites.filter(s => !hiddenStatuses.has(s.status)),
    [mapSites, hiddenStatuses],
  )

  // 拓扑：复用 GIS Map 的真实链路（/api/gis/topology），按传输类型（gateway）着色。
  // 用「可见站点的坐标 → gateway」就近匹配链路两端，判定该链路属于哪种传输类型并取色。
  // 仅绘制至少一端落在当前可见 PL 站点内的链路（随图例显隐联动）。放在 early-return 前，保持 hook 顺序稳定。
  const topology = useMemo(() => {
    const pts: { lat: number; lng: number; gw: string }[] = []
    for (const s of visibleSites) {
      if (s.lat != null && s.lng != null) pts.push({ lat: s.lat, lng: s.lng, gw: s.gateway || '' })
    }
    const TH = 0.006 // ≈ 600m 容差，避免浮点/格式差异导致匹配不上
    const matchGw = (lat: number, lng: number): string => {
      let best = ''; let bd = TH * TH
      for (const p of pts) {
        const d = (p.lat - lat) ** 2 + (p.lng - lng) ** 2
        if (d < bd) { bd = d; best = p.gw }
      }
      return best
    }
    const edges: { positions: [[number, number], [number, number]]; color: string; isHub: boolean }[] = []
    const gwSeen = new Set<string>()
    for (const l of gisTopology) {
      const gw = matchGw(l.lat_a, l.lng_a) || matchGw(l.lat_b, l.lng_b)
      if (!gw) continue // 两端都不在当前可见 PL 站点内 → 跳过
      gwSeen.add(gw)
      edges.push({
        positions: [[l.lat_a, l.lng_a], [l.lat_b, l.lng_b]],
        color: gwColor(gw),
        isHub: !!l.is_hub_link,
      })
    }
    return { edges, gateways: [...gwSeen] }
  }, [visibleSites, gisTopology])

  // ========== 渲染 ==========
  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '3.75rem' }}>
      <Spin size="large" />
      <div style={{ marginTop: '0.75rem', color: WH.textMuted }}>{t('pl.loading')}</div>
    </div>
  )
  if (error) return <Alert type="error" message={t('pl.loadFailed')} description={error} showIcon style={{ margin: 'var(--wh-space-md)' }} />
  if (!data) return <Empty description={t('pl.noData')} />

  const sc = data.status_counts || {}
  const fmt = (n: number) => (n ?? 0).toLocaleString(numLocale(locale))
  const chartClick = (titlePrefix: string) => (p: any) => openDrilldown(p, p.name, `${titlePrefix} = ${STATUS_SHORT[p.name] || p.name}`)

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: '0.75rem', alignItems: isMobile ? 'stretch' : 'flex-start' }}>
      {/* ===== 左侧 2/3：其余组件，排列顺序不变 ===== */}
      <div style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)' }}>
      {/* 1. 头部横幅 */}
      <Card size="small" style={{
        ...cardStyle,
        background: isDark ? 'linear-gradient(135deg, #101a2e 0%, #112540 100%)' : 'linear-gradient(135deg, #eef4fa 0%, #e0edf7 100%)',
        borderLeft: isDark ? '4px solid #ff4757' : '4px solid #d92d20',
        marginBottom: 'var(--wh-space-xs)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
            <DisconnectOutlined style={{ fontSize: '1.375rem', color: WH.teal }} />
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: WH.text }}>{t('pl.status')}</span>
            <MetricExplainPopover text={METRIC_EXPLAIN['Affected Sites']} t={t}>
              <Tag color="error" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 600, cursor: 'pointer' }}
                onClick={e => openDrilldown(e, 'all', 'Sites with Packet Loss')}>
                {fmt(data.affected_sites)} {t('pl.affectedSites')}
              </Tag>
            </MetricExplainPopover>
            <MetricExplainPopover text={METRIC_EXPLAIN['Data Granularity']} t={t}>
              <Tag color="cyan" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 600 }}>{t('pl.granularity')}</Tag>
            </MetricExplainPopover>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-md)', fontSize: '0.75rem', color: WH.textDim }}>
            <ClockCircleOutlined />
            <span>{t('pl.updated')}: {data.generated_at ? String(data.generated_at).replace('T', ' ').slice(0, 19) : 'N/A'}</span>
          </div>
        </div>
      </Card>

      {/* 2. 核心指标卡片 */}
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} lg={4}>
          <SummaryCard icon={<EnvironmentOutlined />} value={fmt(data.total_sites)} label={t('pl.totalSites')} color={WH.teal}
            explain={METRIC_EXPLAIN['Total Sites']}
            onClick={() => openDrilldown(null, 'all', 'All Sites')} t={t} />
        </Col>
        {STATUS_ORDER.filter(s => s !== 'No Packet loss[<0.1]').map(st => (
          <Col xs={12} sm={8} lg={4} key={st}>
            <SummaryCard
              icon={st === 'Critical[>5]' ? <AlertOutlined /> : st === 'Major[1-5]' ? <WarningOutlined /> : <DashboardOutlined />}
              value={fmt(sc[st] || 0)} label={STATUS_SHORT[st]} color={STATUS_COLORS[st]}
              explain={METRIC_EXPLAIN[STATUS_SHORT[st]]}
              onClick={() => openDrilldown(null, st, st)} t={t} />
          </Col>
        ))}
        <Col xs={12} sm={8} lg={4}>
          <SummaryCard icon={<CheckCircleOutlined />} value={fmt(sc['No Packet loss[<0.1]'] || 0)} label={t('pl.noPacketLoss')} color={STATUS_COLORS['No Packet loss[<0.1]']}
            explain={METRIC_EXPLAIN['No Packet loss']}
            onClick={() => openDrilldown(null, 'No Packet loss[<0.1]', 'No Packet loss[<0.1]')} t={t} />
        </Col>
      </Row>

      {/* 3. 状态分布 + 每日趋势 + 区域分布 */}
      <SectionTitle icon={<BarChartOutlined />} title={t('pl.lossDistribution')} sub={t('pl.lossDistSub')} />
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={7}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.statusDist')}</span>} style={cardStyle}>
            <ReactECharts option={statusPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick('Status') }} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.dailyTrend')}</span>} style={cardStyle}>
            <ReactECharts option={trendOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.byRegion')}</span>} style={cardStyle}>
            <ReactECharts option={regionOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
      </Row>

      {/* 4. Top 站点（地图已移至右侧 1/3 列） */}
      <SectionTitle icon={<PieChartOutlined />} title={t('pl.topSites')} sub={t('pl.topSitesSub')} />
      <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.topSitesTitle')}</span>} style={cardStyle}>
        <ReactECharts option={topSitesOption} style={{ height: 520 }} />
      </Card>
      </div>

      {/* ===== 右侧 1/3：Packet Loss Map 单独占整列，可固定（移动端整列堆叠在下方） ===== */}
      <div style={isMobile
        ? { width: '100%', minWidth: 0 }
        : { flex: '0 0 33.333%', width: '33.333%', position: 'sticky', top: 'var(--wh-space-md)', alignSelf: 'flex-start' }}>
        <Card size="small" style={{ ...cardStyle, marginBottom: 0 }} title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.map')} ({t('pl.mapAffected', { n: data?.affected_sites ?? 0 })})</span>
            <span style={{ fontSize: '0.6875rem', color: WH.textMuted, display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
              <Button size="small" type={showTopology ? 'primary' : 'default'}
                icon={<ApartmentOutlined />} onClick={() => setShowTopology(v => !v)}
                style={{ height: 22, fontSize: '0.6875rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {t('pl.topology')}
              </Button>
              {t('pl.showOk')} <Switch size="small" checked={includeOk} onChange={setIncludeOk} />
            </span>
          </div>
        }>
          <MapContainer center={[6.4, -9.4]} zoom={8} className={isDark ? 'gis-dark-map' : ''} style={{ height: isMobile ? '55vh' : 'calc(100vh - 180px)', minHeight: isMobile ? '18.75rem' : '26.25rem', width: '100%', background: 'var(--wh-page-bg)', borderRadius: 'var(--wh-radius-md)' }} scrollWheelZoom>
            <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {/* 拓扑连线：复用 GIS Map 真实链路，按传输类型着色（MW / IPRAN 等）。
                先白色描边(casing)增强对比，再画彩色线；hub 链路更粗。 */}
            {showTopology && topology.edges.map((e, i) => (
              <Polyline key={`topo-c-${i}`} positions={e.positions}
                pathOptions={{ color: '#ffffff', weight: e.isHub ? 5 : 3, opacity: 0.3, interactive: false }} />
            ))}
            {showTopology && topology.edges.map((e, i) => (
              <Polyline key={`topo-${i}`} positions={e.positions}
                pathOptions={{ color: e.color, weight: e.isHub ? 3 : 1.8, opacity: 0.9, interactive: false }} />
            ))}
            {visibleSites.map(s => (
              <CircleMarker key={`${s.site_name}|${s.site_code}`} center={[s.lat, s.lng]}
                radius={Math.min(12, 5 + Math.log1p(s.last_day_max_pl) * 2)}
                fillColor={STATUS_COLORS[s.status] || WH.teal} color="#fff" weight={1} fillOpacity={0.85}>
                <Popup>
                  <div style={{ fontSize: '0.75rem', lineHeight: 1.6 }}>
                    <strong>{s.site_name}</strong> {s.site_code && `(${s.site_code})`}<br />
                    {t('pl.popup.status')}: <strong style={{ color: STATUS_COLORS[s.status] }}>{STATUS_SHORT[s.status] || s.status}</strong><br />
                    {t('pl.popup.maxPL')}: <strong>{s.last_day_max_pl}%</strong><br />
                    {t('pl.popup.totalPL')}: {s.total_pl}% · {t('pl.popup.affectedHours')}: {s.affected_hours}<br />
                    {t('pl.popup.region')}: {s.region || '-'} / {s.province_county || '-'}<br />
                    {t('pl.popup.gateway')}: {s.gateway || '-'} · {t('pl.popup.network')}: {s.network_type || '-'}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          {showTopology && topology.gateways.length > 0 && (
            <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', marginTop: '0.375rem', marginBottom: '0.125rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: '0.6875rem', color: WH.textMuted, fontWeight: 600 }}>{t('pl.topoLabel')}:</span>
              {topology.gateways.map(gw => (
                <span key={gw} style={{ fontSize: '0.6875rem', color: WH.textMuted, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 14, height: 4, borderRadius: 2, background: gwColor(gw), display: 'inline-block' }} />
                  {gw}
                </span>
              ))}
              <span style={{ fontSize: '0.625rem', color: WH.textDim }}>{t('pl.topoHint')}</span>
            </div>
          )}
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: 'var(--wh-space-sm)', flexWrap: 'wrap' }}>
            {STATUS_ORDER.map(st => {
              const hidden = hiddenStatuses.has(st)
              return (
                <span key={st} onClick={() => toggleStatusVisible(st)}
                  title={hidden ? t('pl.showOnMap') : t('pl.hideOnMap')}
                  style={{
                    fontSize: '0.6875rem', cursor: 'pointer', userSelect: 'none',
                    color: hidden ? WH.textDim : WH.textMuted,
                    opacity: hidden ? 0.45 : 1,
                    textDecoration: hidden ? 'line-through' : 'none',
                    display: 'flex', alignItems: 'center', gap: 4,
                  }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: STATUS_COLORS[st], display: 'inline-block', opacity: hidden ? 0.3 : 1 }} />
                  {STATUS_SHORT[st]}
                </span>
              )
            })}
          </div>
        </Card>
      </div>

      {/* 下钻弹窗 */}
      <DraggableClickModal
        open={drillOpen}
        anchor={drillAnchor}
        onClose={() => setDrillOpen(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan" style={{ borderRadius: 10 }}>{t('pl.records', { n: filteredDrillData.length })}</Tag></span>}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
          <Input prefix={<SearchOutlined />} placeholder={t('pl.searchPlaceholder')} allowClear size="middle"
            style={{ width: 'min(100%, 21.875rem)' }} value={drillSearch} onChange={e => setDrillSearch(e.target.value)} />
          <Button type="primary" icon={<DownloadOutlined />} onClick={exportToExcel} disabled={!filteredDrillData.length}>
            {t('pl.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table dataSource={filteredDrillData} columns={drillColumns} size="small"
              rowKey={(r: any) => r.Site_Name}
              pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => `${total} ${t('pl.items')}` }}
              scroll={{ x: 'max-content' }} />
          </div>
        )}
      </DraggableClickModal>
    </div>
  )
}
