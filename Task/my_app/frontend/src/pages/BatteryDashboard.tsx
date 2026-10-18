// Battery Dashboard - 电池看板
// 数据源: battery_kpi.sqlite3（UME r32.uedm.batt 实时数据，battery_kpi_sync 每小时同步）
//
// 设计要点（依据真实数据调整，而非通用模板）：
// 1. 「数据新鲜度」是第一维度：实测约一半电池读数超过 7 天（最老到 2024 年）。
//    所有均值/状态/低电量指标默认只统计新鲜（≤24h）子集，否则平均值会被历史读数污染
//    （例：不过滤时「放电中」338 块，过滤后真实值仅 24 块）。
// 2. 健康度几乎无方差（98~100 占 99%），直方图信息量低 → 主视图用「健康度分级 + 无数据占比」，
//    细粒度直方图作为次要 Tab 保留。
// 3. 「放电中」= 站点市电中断的代理指标，单列为一级 KPI 与告警。
// 4. 新增站点类别（Satelite / Microwave / Pilot）维度与趋势图（每小时快照累积）。
import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Spin, Alert, Empty, Table, Input, Button, Switch,
  Slider, Select, Segmented, Tooltip as ATooltip, Radio, Modal, Statistic,
} from 'antd'
import {
  ThunderboltOutlined, WarningOutlined, HeartOutlined, ClockCircleOutlined,
  EnvironmentOutlined, DownloadOutlined, SearchOutlined, ReloadOutlined,
  AlertOutlined, PoweroffOutlined, ApartmentOutlined, LineChartOutlined,
  FilterOutlined, DashboardOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { exportAoaReport } from '../utils/excelReport'
import dayjs from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { WH, useTheme, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, pageWrap } from '../theme'
import { ExplainIcon } from '../components/MetricExplain'

const SEV_COLORS: Record<string, string> = {
  Critical: '#ff4757',
  Major: '#ff922b',
  Minor: '#ffd43b',
  OK: '#51cf66',
}

const SOC_COLORS: Record<string, string> = {
  '0% (Empty)': '#ff4757',
  '<20% (Critical)': '#ff6b6b',
  '20-50% (Low)': '#ff922b',
  '50-80%': '#ffd43b',
  '80-100%': '#51cf66',
  'No Data': '#64748b',
}

const HEALTH_COLORS: Record<string, string> = {
  '<80% (Severe)': '#ff4757',
  '80-90% (Degraded)': '#ff922b',
  '90-95% (Fair)': '#ffd43b',
  '>=95% (Good)': '#51cf66',
  'No Data': '#64748b',
}

const STATUS_COLORS: Record<string, string> = {
  Charge: '#51cf66',
  Discharge: '#ff922b',
  Unknown: '#64748b',
}

const FRESH_COLORS: Record<string, string> = {
  fresh: '#51cf66',
  delayed: '#ffd43b',
  stale: '#ff922b',
  no_data: '#64748b',
}

const CHART_H = 260

const SectionTitle = ({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: 'var(--wh-space-lg) 0 var(--wh-space-md)', padding: '0 0 var(--wh-space-sm)',
    borderBottom: '1px solid rgba(0, 217, 255,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 'var(--wh-radius-md)', background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: '0.875rem',
    }}>{icon}</span>
    <span style={{ fontSize: '1rem', fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {sub && <span style={{ fontSize: '0.75rem', color: WH.textDim, marginLeft: 'var(--wh-space-xs)' }}>{sub}</span>}
  </div>
)

const KpiCard = ({ value, label, sub, color, icon, hint }: {
  value: React.ReactNode; label: string; sub?: string; color: string
  icon: React.ReactNode; hint?: string
}) => (
  <Card size="small" className="wh-card-interactive" style={{
    ...cardStyle, position: 'relative', overflow: 'hidden', height: '100%',
  }}>
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: color, opacity: 0.9 }} />
    {hint && (
      <span style={{ position: 'absolute', top: 'var(--wh-space-xs)', right: 'var(--wh-space-sm)', zIndex: 2, cursor: 'help' }}>
        <ExplainIcon text={hint} />
      </span>
    )}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontSize: '1.625rem', fontWeight: 800, color, lineHeight: 1.2,
          textShadow: `0 0 14px ${color}55`, whiteSpace: 'nowrap',
        }}>{value}</div>
        <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginTop: 'var(--wh-space-xs)', fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ fontSize: '0.6875rem', color: WH.textDim, marginTop: '0.125rem' }}>{sub}</div>}
      </div>
      <span style={{ fontSize: '2.125rem', opacity: 0.16, color }}>{icon}</span>
    </div>
  </Card>
)

interface Battery {
  position: string; mo: string; site: string; category: string
  health: number | null; health_time: string | null
  soc: number | null; soc_time: string | null
  status: string; status_time: string | null
  last_update: string | null; age_hours: number | null; freshness: string
}

const exportXlsx = (rows: any[], name: string) => {
  if (!rows.length) return
  // 原用 XLSX.utils.json_to_sheet（列头取对象键），此处显式取键并映射为行，保持列头与列序不变。
  // 统一走 excelReport 以获得标题行、表头填充、冻结窗格、列宽与自适应筛选。
  const keys = Object.keys(rows[0])
  const header = keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
  const body = rows.map(r => keys.map(k => (r[k] == null ? '' : String(r[k]))))
  void exportAoaReport({
    filename: `${name}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
    sheetName: name,
    title: name,
    header,
    rows: body,
    numericCols: [],
  })
}

export default function BatteryDashboard() {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<any>(null)
  const [trend, setTrend] = useState<any>({ source: '', points: [] })
  const [trendDays, setTrendDays] = useState(7)

  // ===== 侧边栏筛选 =====
  const [search, setSearch] = useState('')
  const [cats, setCats] = useState<string[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [freshOnly, setFreshOnly] = useState(true)
  const [healthRange, setHealthRange] = useState<[number, number]>([0, 100])
  const [socRange, setSocRange] = useState<[number, number]>([0, 100])
  const [includeNullMetric, setIncludeNullMetric] = useState(true)

  // 健康度图表模式
  const [healthMode, setHealthMode] = useState<'bucket' | 'hist'>('bucket')
  // 告警表筛选
  const [alarmSev, setAlarmSev] = useState<string>('all')
  const [alarmSearch, setAlarmSearch] = useState('')
  // 站点下钻
  const [drillSite, setDrillSite] = useState<string | null>(null)
  const [drillData, setDrillData] = useState<any>(null)
  const [drillLoading, setDrillLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      api.get('/battery-dashboard/all'),
      api.get('/battery-dashboard/trend', { params: { days: trendDays } }),
    ])
      .then(([all, tr]) => {
        setData(all.data)
        setTrend(tr.data)
      })
      .catch(err => setError(err?.message || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [trendDays])

  useEffect(() => { load() }, [load])

  const batteries: Battery[] = data?.batteries || []
  const thresholds = data?.meta?.thresholds || {}

  const categoryOptions = useMemo(
    () => Array.from(new Set(batteries.map(b => b.category))).map(c => ({ label: c, value: c })),
    [batteries])

  // 除「仅新鲜」外的全部筛选（数据时效图需要看到过期项，故单独保留）
  const baseFiltered = useMemo(() => {
    const kw = search.trim().toLowerCase()
    return batteries.filter(b => {
      if (kw && !(b.site.toLowerCase().includes(kw) || b.position.toLowerCase().includes(kw)
        || b.mo.toLowerCase().includes(kw))) return false
      if (cats.length && !cats.includes(b.category)) return false
      if (statuses.length) {
        const st = b.status === 'Charge' || b.status === 'Discharge' ? b.status : 'Unknown'
        if (!statuses.includes(st)) return false
      }
      if (b.health == null) { if (!includeNullMetric) return false }
      else if (b.health < healthRange[0] || b.health > healthRange[1]) return false
      if (b.soc == null) { if (!includeNullMetric) return false }
      else if (b.soc < socRange[0] || b.soc > socRange[1]) return false
      return true
    })
  }, [batteries, search, cats, statuses, healthRange, socRange, includeNullMetric])

  const filtered = useMemo(
    () => (freshOnly ? baseFiltered.filter(b => b.freshness === 'fresh') : baseFiltered),
    [baseFiltered, freshOnly])

  const filterActive = search.trim() !== '' || cats.length > 0 || statuses.length > 0
    || healthRange[0] !== 0 || healthRange[1] !== 100
    || socRange[0] !== 0 || socRange[1] !== 100 || !includeNullMetric

  // ===== 客户端重算的 KPI / 分布（随筛选即时变化） =====
  const view = useMemo(() => {
    const socCrit = thresholds.soc_critical ?? 20
    const hDeg = thresholds.health_degraded ?? 90
    const socs = filtered.map(b => b.soc).filter((v): v is number => v != null)
    const healths = filtered.map(b => b.health).filter((v): v is number => v != null)
    const disch = filtered.filter(b => b.status === 'Discharge')
    const crit = filtered.filter(b => b.soc != null && b.soc < socCrit)
    const staleRows = baseFiltered.filter(b => b.freshness === 'stale' || b.freshness === 'no_data')
    const avg = (xs: number[]) => xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length * 10) / 10 : null

    const bucket = (arr: string[], order: string[]) => {
      const m: Record<string, number> = {}
      order.forEach(k => { m[k] = 0 })
      arr.forEach(k => { m[k] = (m[k] || 0) + 1 })
      return order.map(k => ({ name: k, value: m[k] }))
    }
    const socBucket = (s: number | null) => s == null ? 'No Data'
      : s <= 0 ? '0% (Empty)' : s < 20 ? '<20% (Critical)'
        : s < 50 ? '20-50% (Low)' : s < 80 ? '50-80%' : '80-100%'
    const healthBucket = (h: number | null) => h == null ? 'No Data'
      : h < 80 ? '<80% (Severe)' : h < hDeg ? '80-90% (Degraded)'
        : h < (thresholds.health_good ?? 95) ? '90-95% (Fair)' : '>=95% (Good)'

    const hist: Record<number, number> = {}
    filtered.forEach(b => {
      if (b.health == null) return
      const k = Math.floor(b.health / 2) * 2
      hist[k] = (hist[k] || 0) + 1
    })

    // 类别维度
    const catMap: Record<string, Battery[]> = {}
    baseFiltered.forEach(b => { (catMap[b.category] ||= []).push(b) })
    const byCategory = Object.entries(catMap).map(([category, items]) => {
      const f = items.filter(b => b.freshness === 'fresh')
      return {
        category,
        batteries: items.length,
        sites: new Set(items.map(b => b.site)).size,
        fresh_rate: items.length ? Math.round(f.length * 1000 / items.length) / 10 : 0,
        avg_soc: avg(f.map(b => b.soc).filter((v): v is number => v != null)),
        discharging: f.filter(b => b.status === 'Discharge').length,
        critical_soc: f.filter(b => b.soc != null && b.soc < socCrit).length,
      }
    }).sort((a, b) => b.batteries - a.batteries)

    return {
      total: filtered.length,
      sites: new Set(filtered.map(b => b.site)).size,
      freshCount: baseFiltered.filter(b => b.freshness === 'fresh').length,
      baseTotal: baseFiltered.length,
      freshRate: baseFiltered.length
        ? Math.round(baseFiltered.filter(b => b.freshness === 'fresh').length * 1000 / baseFiltered.length) / 10 : 0,
      avgSoc: avg(socs),
      avgHealth: avg(healths),
      discharging: disch.length,
      dischargingSites: new Set(disch.map(b => b.site)).size,
      critical: crit.length,
      criticalSites: new Set(crit.map(b => b.site)).size,
      degraded: filtered.filter(b => b.health != null && b.health < hDeg).length,
      stale: staleRows.length,
      staleSites: new Set(staleRows.map(b => b.site)).size,
      socDist: bucket(filtered.map(b => socBucket(b.soc)),
        ['0% (Empty)', '<20% (Critical)', '20-50% (Low)', '50-80%', '80-100%', 'No Data']),
      healthDist: bucket(filtered.map(b => healthBucket(b.health)),
        ['<80% (Severe)', '80-90% (Degraded)', '90-95% (Fair)', '>=95% (Good)', 'No Data']),
      statusDist: bucket(filtered.map(b => (b.status === 'Charge' || b.status === 'Discharge' ? b.status : 'Unknown')),
        ['Charge', 'Discharge', 'Unknown']),
      freshDist: bucket(baseFiltered.map(b => b.freshness), ['fresh', 'delayed', 'stale', 'no_data']),
      healthHist: Object.entries(hist).map(([k, v]) => ({ bin: `${k}-${Number(k) + 2}`, value: v }))
        .sort((a, b) => Number(a.bin.split('-')[0]) - Number(b.bin.split('-')[0])),
      byCategory,
    }
  }, [filtered, baseFiltered, thresholds])

  // 告警 / 站点：按当前筛选出的电池集合过滤
  const posSet = useMemo(() => new Set(baseFiltered.map(b => b.position)), [baseFiltered])
  const siteSet = useMemo(() => new Set(baseFiltered.map(b => b.site)), [baseFiltered])

  const alarms = useMemo(() => {
    const list = (data?.alarms || []).filter((a: any) => posSet.has(a.position))
    const kw = alarmSearch.trim().toLowerCase()
    return list.filter((a: any) => {
      if (alarmSev !== 'all' && a.severity !== alarmSev) return false
      if (kw && !(String(a.site).toLowerCase().includes(kw)
        || String(a.type).toLowerCase().includes(kw)
        || String(a.position).toLowerCase().includes(kw))) return false
      return true
    })
  }, [data, posSet, alarmSev, alarmSearch])

  const sites = useMemo(
    () => (data?.sites || []).filter((s: any) => siteSet.has(s.site)),
    [data, siteSet])

  const alarmCounts = useMemo(() => {
    const c: Record<string, number> = { Critical: 0, Major: 0, Minor: 0 }
    ;(data?.alarms || []).filter((a: any) => posSet.has(a.position))
      .forEach((a: any) => { c[a.severity] = (c[a.severity] || 0) + 1 })
    return c
  }, [data, posSet])

  const openDrill = useCallback((site: string) => {
    setDrillSite(site)
    setDrillLoading(true)
    setDrillData(null)
    api.get(`/battery-dashboard/site/${encodeURIComponent(site)}`)
      .then(res => setDrillData(res.data))
      .catch(() => setDrillData(null))
      .finally(() => setDrillLoading(false))
  }, [])

  const resetFilters = () => {
    setSearch(''); setCats([]); setStatuses([])
    setHealthRange([0, 100]); setSocRange([0, 100])
    setIncludeNullMetric(true); setFreshOnly(true)
  }

  // ===== 图表 option =====
  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const cText = isDark ? '#f5f7ff' : '#16233b'
  const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
  const cTextDim = isDark ? '#6f8cb4' : '#5b7288'
  const cTeal = isDark ? '#00d9ff' : '#0d9488'
  const cBlue = isDark ? '#258cff' : '#0284c7'
  const cIndigo = isDark ? '#7c8ff0' : '#6366f1'
  const cPieBorder = isDark ? '#050d22' : '#ffffff'

  const pieOption = (rows: { name: string; value: number }[], colors: Record<string, string>, title?: string) => ({
    tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: {
      type: 'scroll', bottom: 0, textStyle: { color: cTextMuted, fontSize: 11 },
      itemWidth: 10, itemHeight: 10,
    },
    series: [{
      type: 'pie', radius: ['45%', '70%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: cPieBorder, borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, color: cText, fontSize: 13, fontWeight: 700, formatter: '{b}\n{c}' } },
      data: rows.filter(r => r.value > 0).map(r => ({
        ...r, itemStyle: { color: colors[r.name] || cBlue },
      })),
    }],
    title: title ? {
      text: title, left: 'center', top: '38%',
      textStyle: { color: cTextDim, fontSize: 11, fontWeight: 400 },
    } : undefined,
  })

  const healthBarOption = useMemo(() => {
    const rows = healthMode === 'bucket'
      ? view.healthDist.map(r => ({ name: r.name, value: r.value, color: HEALTH_COLORS[r.name] }))
      : view.healthHist.map(r => ({ name: r.bin, value: r.value, color: cBlue }))
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 50, right: 16, top: 20, bottom: 46 },
      xAxis: {
        type: 'category', data: rows.map(r => r.name),
        axisLabel: { ...axisLabel(isDark), interval: 0, rotate: rows.length > 4 ? 20 : 0 },
        axisLine: axisLine(isDark),
      },
      yAxis: { type: 'value', axisLabel: axisLabel(isDark), axisLine: axisLine(isDark), splitLine: splitLine(isDark) },
      series: [{
        type: 'bar', barMaxWidth: 46,
        data: rows.map(r => ({ value: r.value, itemStyle: { color: r.color, borderRadius: [4, 4, 0, 0] } })),
        label: { show: true, position: 'top', color: cTextMuted, fontSize: 11 },
      }],
    }
  }, [view, healthMode, isDark])

  const categoryOption = useMemo(() => ({
    tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: cTextMuted, fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
    grid: { left: 50, right: 50, top: 20, bottom: 44 },
    xAxis: {
      type: 'category', data: view.byCategory.map(c => c.category),
      axisLabel: axisLabel(isDark), axisLine: axisLine(isDark),
    },
    yAxis: [
      { type: 'value', name: t('batt.batteries'), nameTextStyle: { color: cTextDim, fontSize: 10 }, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark), splitLine: splitLine(isDark) },
      { type: 'value', name: '%', max: 100, nameTextStyle: { color: cTextDim, fontSize: 10 }, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark), splitLine: { show: false } },
    ],
    series: [
      { name: t('batt.batteries'), type: 'bar', barMaxWidth: 38, data: view.byCategory.map(c => c.batteries), itemStyle: { color: cIndigo, borderRadius: [4, 4, 0, 0] } },
      { name: t('batt.critical'), type: 'bar', barMaxWidth: 38, data: view.byCategory.map(c => c.critical_soc), itemStyle: { color: isDark ? '#ff5c6c' : '#d92d20', borderRadius: [4, 4, 0, 0] } },
      { name: t('batt.freshRate'), type: 'line', yAxisIndex: 1, smooth: true, data: view.byCategory.map(c => c.fresh_rate), itemStyle: { color: cTeal }, lineStyle: { width: 2 } },
      { name: t('batt.avgSoc'), type: 'line', yAxisIndex: 1, smooth: true, data: view.byCategory.map(c => c.avg_soc), itemStyle: { color: isDark ? '#f6cf00' : '#ca8a04' }, lineStyle: { width: 2, type: 'dashed' } },
    ],
  }), [view, t, isDark])

  const trendOption = useMemo(() => {
    const pts = trend.points || []
    const isPoll = trend.source === 'poll'
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
      legend: { bottom: 0, textStyle: { color: cTextMuted, fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
      grid: { left: 50, right: 50, top: 20, bottom: 46 },
      xAxis: {
        type: 'category', data: pts.map((p: any) => p.snapshot_ts?.slice(5, 16)),
        axisLabel: { ...axisLabel(isDark), rotate: 30 }, axisLine: axisLine(isDark),
      },
      yAxis: [
        { type: 'value', name: '%', max: 100, nameTextStyle: { color: cTextDim, fontSize: 10 }, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark), splitLine: splitLine(isDark) },
        { type: 'value', name: t('batt.count'), nameTextStyle: { color: cTextDim, fontSize: 10 }, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark), splitLine: { show: false } },
      ],
      series: [
        { name: t('batt.avgSoc'), type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: pts.map((p: any) => p.avg_soc), itemStyle: { color: isDark ? '#f6cf00' : '#ca8a04' }, areaStyle: { color: isDark ? 'rgba(255,212,59,0.08)' : 'rgba(202,138,4,0.10)' } },
        ...(isPoll ? [{ name: t('batt.freshRate'), type: 'line', smooth: true, data: pts.map((p: any) => p.fresh_rate), itemStyle: { color: cTeal } }] : []),
        { name: t('batt.discharging'), type: 'bar', yAxisIndex: 1, barMaxWidth: 14, data: pts.map((p: any) => p.discharging), itemStyle: { color: isDark ? '#ff922b' : '#ea580c', borderRadius: [3, 3, 0, 0] } },
        { name: t('batt.critical'), type: 'bar', yAxisIndex: 1, barMaxWidth: 14, data: pts.map((p: any) => p.critical_soc), itemStyle: { color: isDark ? '#ff5c6c' : '#d92d20', borderRadius: [3, 3, 0, 0] } },
        ...(isPoll ? [] : [{ name: t('batt.samples'), type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none', lineStyle: { type: 'dotted', width: 1.5 }, data: pts.map((p: any) => p.reported), itemStyle: { color: cTextDim } }]),
      ],
    }
  }, [trend, t, isDark])

  // ===== 表格列 =====
  const alarmColumns = [
    {
      title: t('batt.severity'), dataIndex: 'severity', minWidth: 96, fixed: 'left' as const,
      filters: ['Critical', 'Major', 'Minor'].map(v => ({ text: v, value: v })),
      onFilter: (v: any, r: any) => r.severity === v,
      render: (v: string) => <Tag color={SEV_COLORS[v]} style={{ fontWeight: 600, border: 'none' }}>{v}</Tag>,
    },
    {
      title: t('batt.alarmType'), dataIndex: 'type', minWidth: 170,
      filters: Array.from(new Set(alarms.map((a: any) => a.type))).map(v => ({ text: v as string, value: v as string })),
      onFilter: (v: any, r: any) => r.type === v,
    },
    {
      title: t('batt.site'), dataIndex: 'site', minWidth: 170, ellipsis: true,
      sorter: (a: any, b: any) => String(a.site).localeCompare(String(b.site)),
      render: (v: string) => <a style={{ color: WH.teal }} onClick={() => openDrill(v)}>{v}</a>,
    },
    { title: t('batt.battery'), dataIndex: 'mo', minWidth: 110 },
    {
      title: 'SOC', dataIndex: 'soc', minWidth: 90, align: 'right' as const,
      sorter: (a: any, b: any) => (a.soc ?? 999) - (b.soc ?? 999),
      render: (v: number | null) => v == null ? <span style={{ color: WH.textDim }}>--</span>
        : <span style={{ color: v < 20 ? '#ff4757' : v < 50 ? '#ff922b' : WH.text, fontWeight: 600 }}>{v}%</span>,
    },
    {
      title: t('batt.health'), dataIndex: 'health', minWidth: 90, align: 'right' as const,
      sorter: (a: any, b: any) => (a.health ?? 999) - (b.health ?? 999),
      render: (v: number | null) => v == null ? <span style={{ color: WH.textDim }}>--</span> : `${v}%`,
    },
    {
      title: t('batt.status'), dataIndex: 'status', minWidth: 110,
      render: (v: string) => <Tag color={STATUS_COLORS[v] || STATUS_COLORS.Unknown} style={{ border: 'none' }}>{v}</Tag>,
    },
    { title: t('batt.detail'), dataIndex: 'detail', minWidth: 220, ellipsis: true },
    {
      title: t('batt.lastUpdate'), dataIndex: 'last_update', minWidth: 160,
      sorter: (a: any, b: any) => String(a.last_update || '').localeCompare(String(b.last_update || '')),
      render: (v: string, r: any) => (
        <span style={{ color: r.freshness === 'fresh' ? WH.textMuted : '#ff922b' }}>
          {v || '--'}{r.age_hours != null && r.age_hours > 24 ? ` (${(r.age_hours / 24).toFixed(0)}d)` : ''}
        </span>
      ),
    },
  ]

  const siteColumns = [
    {
      title: t('batt.severity'), dataIndex: 'severity', minWidth: 96, fixed: 'left' as const,
      filters: ['Critical', 'Major', 'Minor', 'OK'].map(v => ({ text: v, value: v })),
      onFilter: (v: any, r: any) => r.severity === v,
      render: (v: string) => <Tag color={SEV_COLORS[v]} style={{ fontWeight: 600, border: 'none' }}>{v}</Tag>,
    },
    {
      title: t('batt.site'), dataIndex: 'site', minWidth: 190, ellipsis: true,
      sorter: (a: any, b: any) => String(a.site).localeCompare(String(b.site)),
      render: (v: string) => <a style={{ color: WH.teal }} onClick={() => openDrill(v)}>{v}</a>,
    },
    {
      title: t('batt.category'), dataIndex: 'category', minWidth: 140,
      filters: categoryOptions.map(c => ({ text: c.label, value: c.value })),
      onFilter: (v: any, r: any) => r.category === v,
    },
    { title: t('batt.batteries'), dataIndex: 'batteries', minWidth: 90, align: 'right' as const, sorter: (a: any, b: any) => a.batteries - b.batteries },
    {
      title: t('batt.freshRate'), dataIndex: 'fresh_rate', minWidth: 110, align: 'right' as const,
      sorter: (a: any, b: any) => a.fresh_rate - b.fresh_rate,
      render: (v: number) => <span style={{ color: v >= 80 ? '#51cf66' : v >= 40 ? '#ffd43b' : '#ff922b' }}>{v}%</span>,
    },
    {
      title: t('batt.avgSoc'), dataIndex: 'avg_soc', minWidth: 100, align: 'right' as const,
      sorter: (a: any, b: any) => (a.avg_soc ?? 999) - (b.avg_soc ?? 999),
      render: (v: number | null) => v == null ? <span style={{ color: WH.textDim }}>--</span> : `${v}%`,
    },
    {
      title: t('batt.minSoc'), dataIndex: 'min_soc', minWidth: 100, align: 'right' as const,
      sorter: (a: any, b: any) => (a.min_soc ?? 999) - (b.min_soc ?? 999),
      render: (v: number | null) => v == null ? <span style={{ color: WH.textDim }}>--</span>
        : <span style={{ color: v < 20 ? '#ff4757' : v < 50 ? '#ff922b' : WH.text, fontWeight: 600 }}>{v}%</span>,
    },
    {
      title: t('batt.minHealth'), dataIndex: 'min_health', minWidth: 110, align: 'right' as const,
      sorter: (a: any, b: any) => (a.min_health ?? 999) - (b.min_health ?? 999),
      render: (v: number | null) => v == null ? <span style={{ color: WH.textDim }}>--</span>
        : <span style={{ color: v < 90 ? '#ff922b' : WH.text }}>{v}%</span>,
    },
    {
      title: t('batt.discharging'), dataIndex: 'discharging', minWidth: 100, align: 'right' as const,
      sorter: (a: any, b: any) => a.discharging - b.discharging,
      render: (v: number) => v > 0 ? <span style={{ color: '#ff922b', fontWeight: 600 }}>{v}</span> : v,
    },
    {
      title: t('batt.critical'), dataIndex: 'critical_soc', minWidth: 100, align: 'right' as const,
      sorter: (a: any, b: any) => a.critical_soc - b.critical_soc,
      render: (v: number) => v > 0 ? <span style={{ color: '#ff4757', fontWeight: 700 }}>{v}</span> : v,
    },
    {
      title: t('batt.stale'), dataIndex: 'stale', minWidth: 90, align: 'right' as const,
      sorter: (a: any, b: any) => a.stale - b.stale,
    },
    { title: t('batt.lastUpdate'), dataIndex: 'last_update', minWidth: 160 },
  ]

  if (loading) {
    return (
      <div style={{ ...pageWrap, display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Spin size="large" tip={t('batt.loading')} />
      </div>
    )
  }
  if (error) {
    return <div style={pageWrap}><Alert type="error" message={t('batt.loadFailed')} description={error} showIcon /></div>
  }
  if (!data?.available) {
    return (
      <div style={{ ...pageWrap, padding: 'var(--wh-space-lg)' }}>
        <Empty description={<span style={{ color: WH.textMuted }}>{data?.message || t('batt.noData')}</span>} />
      </div>
    )
  }

  return (
    <div style={pageWrap}>
      {/* ===== 顶部信息条 ===== */}
      <Card size="small" style={{ ...cardStyle, marginBottom: '0.75rem' }} styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-md)', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: WH.text }}>
            <ThunderboltOutlined style={{ color: WH.teal, marginRight: 'var(--wh-space-sm)' }} />{t('batt.title')}
          </span>
          <ExplainIcon text={t('batt.explain.title')} size={15} />
          <Tag color="cyan" style={{ border: 'none' }}>
            <ClockCircleOutlined /> {t('batt.lastSync')}: {formatDateTime(data.meta.last_sync_ts, { fallback: '--' })}
          </Tag>
          <Tag style={{ border: 'none', background: 'rgba(0, 217, 255,0.1)', color: WH.textMuted }}>
            {`${t('batt.freshDef')}: ≤${thresholds.fresh_hours}${t('batt.unitH')} · ${t('batt.staleDef')}: >${thresholds.stale_days}${t('batt.unitD')}`}
          </Tag>
          {Object.entries(alarmCounts).map(([sev, n]) => (
            <Tag key={sev} color={SEV_COLORS[sev]} style={{ border: 'none', fontWeight: 600 }}>{sev}: {n as number}</Tag>
          ))}
          <span style={{ flex: 1 }} />
          <Button size="small" icon={<ReloadOutlined />} onClick={load}
            style={{ color: WH.teal, borderColor: 'rgba(0, 217, 255,0.35)', background: 'transparent' }}>
            {t('batt.refresh')}
          </Button>
        </div>
      </Card>

      <Row gutter={12}>
        {/* ===== 侧边栏筛选 ===== */}
        <Col xs={24} lg={5} xl={4}>
          <Card size="small" style={{ ...cardStyle, marginBottom: '0.75rem', position: 'sticky', top: 'var(--wh-space-sm)' }}
            title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}><FilterOutlined style={{ color: WH.teal, marginRight: '0.375rem' }} />{t('batt.filters')}</span>}
            extra={<Button type="link" size="small" onClick={resetFilters} style={{ color: WH.teal, fontSize: '0.75rem' }}>{t('batt.reset')}</Button>}
          >
            <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: 'var(--wh-space-xs)' }}>{t('batt.searchSite')}</div>
            <Input allowClear size="small" prefix={<SearchOutlined style={{ color: WH.textDim }} />}
              placeholder={t('batt.searchPlaceholder')} value={search}
              onChange={e => setSearch(e.target.value)} style={{ marginBottom: '0.875rem' }} />

            <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: 'var(--wh-space-xs)' }}>{t('batt.category')}</div>
            <Select mode="multiple" allowClear size="small" style={{ width: '100%', marginBottom: '0.875rem' }}
              placeholder={t('batt.allCategories')} options={categoryOptions}
              value={cats} onChange={setCats} maxTagCount="responsive" />

            <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: 'var(--wh-space-xs)' }}>{t('batt.status')}</div>
            <Select mode="multiple" allowClear size="small" style={{ width: '100%', marginBottom: '0.875rem' }}
              placeholder={t('batt.allStatuses')}
              options={[{ label: t('batt.statusCharge'), value: 'Charge' }, { label: t('batt.statusDischarge'), value: 'Discharge' }, { label: t('batt.statusUnknown'), value: 'Unknown' }]}
              value={statuses} onChange={setStatuses} maxTagCount="responsive" />

            <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: '0.125rem' }}>
              {t('batt.health')} ({healthRange[0]} - {healthRange[1]}%)
            </div>
            <Slider range min={0} max={100} value={healthRange} onChange={v => setHealthRange(v as [number, number])}
              styles={{ track: { background: WH.teal } }} />

            <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: '0.125rem' }}>
              {t('batt.soc')} ({socRange[0]} - {socRange[1]}%)
            </div>
            <Slider range min={0} max={100} value={socRange} onChange={v => setSocRange(v as [number, number])}
              styles={{ track: { background: WH.blue } }} />

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.75rem' }}>
              <ATooltip title={t('batt.freshOnlyHint')}>
                <span style={{ fontSize: '0.75rem', color: WH.textMuted }}>{t('batt.freshOnly')}</span>
              </ATooltip>
              <Switch size="small" checked={freshOnly} onChange={setFreshOnly} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.625rem' }}>
              <ATooltip title={t('batt.includeNullHint')}>
                <span style={{ fontSize: '0.75rem', color: WH.textMuted }}>{t('batt.includeNull')}</span>
              </ATooltip>
              <Switch size="small" checked={includeNullMetric} onChange={setIncludeNullMetric} />
            </div>

            <div style={{ marginTop: '0.875rem', paddingTop: '0.625rem', borderTop: '1px dashed rgba(0, 217, 255,0.15)', fontSize: '0.6875rem', color: WH.textDim }}>
              {t('batt.matched')}: <span style={{ color: WH.teal, fontWeight: 700 }}>{filtered.length}</span> / {batteries.length}
              {filterActive && <Tag color="cyan" style={{ marginLeft: '0.375rem', border: 'none' }}>{t('batt.filtered')}</Tag>}
            </div>
          </Card>
        </Col>

        {/* ===== 主区 ===== */}
        <Col xs={24} lg={19} xl={20}>
          {/* KPI 卡片 */}
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.total} label={t('batt.kpiBatteries')} color={WH.teal}
                icon={<ThunderboltOutlined />} sub={`${view.sites} ${t('batt.sitesUnit')}`}
                hint={t('batt.hintBatteries')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.sites} label={t('batt.kpiSites')} color={WH.blue}
                icon={<EnvironmentOutlined />} hint={t('batt.hintSites')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={`${view.freshRate}%`} label={t('batt.kpiFreshRate')}
                color={view.freshRate >= 80 ? '#51cf66' : view.freshRate >= 50 ? '#ffd43b' : '#ff922b'}
                icon={<ClockCircleOutlined />} sub={`${view.freshCount}/${view.baseTotal}`}
                hint={t('batt.hintFreshRate')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.avgSoc == null ? '--' : `${view.avgSoc}%`} label={t('batt.kpiAvgSoc')}
                color={(view.avgSoc ?? 100) < 50 ? '#ff922b' : '#ffd43b'}
                icon={<DashboardOutlined />} hint={t('batt.hintAvgSoc')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.avgHealth == null ? '--' : `${view.avgHealth}%`} label={t('batt.kpiAvgHealth')}
                color="#51cf66" icon={<HeartOutlined />}
                sub={`${t('batt.degraded')}: ${view.degraded}`} hint={t('batt.hintAvgHealth')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.discharging} label={t('batt.kpiDischarging')} color="#ff922b"
                icon={<PoweroffOutlined />} sub={`${view.dischargingSites} ${t('batt.sitesUnit')}`}
                hint={t('batt.hintDischarging')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.critical} label={t('batt.kpiCriticalSoc')} color="#ff4757"
                icon={<AlertOutlined />} sub={`${view.criticalSites} ${t('batt.sitesUnit')}`}
                hint={t('batt.hintCriticalSoc')} />
            </Col>
            <Col xs={12} sm={8} lg={6} xxl={3}>
              <KpiCard value={view.stale} label={t('batt.kpiStale')} color="#7c8ff0"
                icon={<DatabaseOutlined />} sub={`${view.staleSites} ${t('batt.sitesUnit')}`}
                hint={t('batt.hintStale')} />
            </Col>
          </Row>

          {/* 分布图 */}
          <SectionTitle icon={<DashboardOutlined />} title={t('batt.distribution')} sub={t('batt.distributionSub')} />
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12} xl={8}>
              <Card size="small" style={cardStyle}
                title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}>{t('batt.socDist')}</span>}
                extra={<span style={{ fontSize: '0.6875rem', color: WH.textDim }}>{freshOnly ? t('batt.freshSubset') : t('batt.allData')}</span>}>
                <ReactECharts option={pieOption(view.socDist, SOC_COLORS)} style={{ height: CHART_H }} notMerge />
              </Card>
            </Col>
            <Col xs={24} md={12} xl={8}>
              <Card size="small" style={cardStyle}
                title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}>{t('batt.statusDist')}</span>}
                extra={<span style={{ fontSize: '0.6875rem', color: WH.textDim }}>{t('batt.statusHint')}</span>}>
                <ReactECharts option={pieOption(view.statusDist, STATUS_COLORS)} style={{ height: CHART_H }} notMerge />
              </Card>
            </Col>
            <Col xs={24} md={12} xl={8}>
              <Card size="small" style={cardStyle}
                title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}>{t('batt.freshnessDist')}</span>}
                extra={<span style={{ fontSize: '0.6875rem', color: WH.textDim }}>{t('batt.freshnessHint')}</span>}>
                <ReactECharts option={pieOption(view.freshDist, FRESH_COLORS)} style={{ height: CHART_H }} notMerge />
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card size="small" style={cardStyle}
                title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}>{t('batt.healthDist')}</span>}
                extra={
                  <Segmented className="wh-seg" size="small" value={healthMode} onChange={v => setHealthMode(v as any)}
                    options={[{ label: t('batt.byGrade'), value: 'bucket' }, { label: t('batt.histogram'), value: 'hist' }]} />
                }>
                <ReactECharts option={healthBarOption} style={{ height: CHART_H }} notMerge />
                <div style={{ fontSize: '0.6875rem', color: WH.textDim, marginTop: 'var(--wh-space-xs)' }}>{t('batt.healthNote')}</div>
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card size="small" style={cardStyle}
                title={<span style={{ color: WH.text, fontSize: '0.8125rem' }}><ApartmentOutlined style={{ marginRight: '0.375rem', color: WH.teal }} />{t('batt.byCategory')}</span>}>
                <ReactECharts option={categoryOption} style={{ height: CHART_H }} notMerge />
              </Card>
            </Col>
          </Row>

          {/* 趋势 */}
          <SectionTitle icon={<LineChartOutlined />} title={t('batt.trend')}
            sub={trend.source === 'poll' ? t('batt.trendPoll') : t('batt.trendReading')} />
          <Card size="small" style={cardStyle}
            extra={
              <Radio.Group size="small" value={trendDays} onChange={e => setTrendDays(e.target.value)}>
                <Radio.Button value={1}>{t('batt.range24h')}</Radio.Button>
                <Radio.Button value={7}>{t('batt.range7d')}</Radio.Button>
                <Radio.Button value={30}>{t('batt.range30d')}</Radio.Button>
              </Radio.Group>
            }>
            {(trend.points || []).length === 0
              ? <Empty description={<span style={{ color: WH.textMuted }}>{t('batt.noTrend')}</span>} />
              : <ReactECharts option={trendOption} style={{ height: 300 }} notMerge />}
          </Card>

          {/* 告警表 */}
          <SectionTitle icon={<WarningOutlined />} title={t('batt.alarms')} sub={`${alarms.length} ${t('batt.records')}`} />
          <Card size="small" style={cardStyle}>
            <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', marginBottom: '0.625rem', flexWrap: 'wrap' }}>
              <Segmented className="wh-seg" size="small" value={alarmSev} onChange={v => setAlarmSev(v as string)}
                options={[
                  { label: t('batt.all'), value: 'all' },
                  { label: `Critical (${alarmCounts.Critical || 0})`, value: 'Critical' },
                  { label: `Major (${alarmCounts.Major || 0})`, value: 'Major' },
                  { label: `Minor (${alarmCounts.Minor || 0})`, value: 'Minor' },
                ]} />
              <Input allowClear size="small" style={{ width: 'min(100%, 13.75rem)' as any }} prefix={<SearchOutlined style={{ color: WH.textDim }} />}
                placeholder={t('batt.searchAlarm')} value={alarmSearch} onChange={e => setAlarmSearch(e.target.value)} />
              <span style={{ flex: 1 }} />
              <Button size="small" icon={<DownloadOutlined />} onClick={() => exportXlsx(alarms, 'battery_alarms')}
                style={{ color: WH.teal, borderColor: 'rgba(0, 217, 255,0.35)', background: 'transparent' }}>
                {t('batt.export')}
              </Button>
            </div>
            <div className="wh-table-responsive">
              <Table rowKey={(r: any, i) => `${r.position}_${r.type}_${i}`} size="small"
                dataSource={alarms} columns={alarmColumns as any}
                scroll={{ x: 'max-content', y: 420 }}
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (n) => `${n} ${t('batt.records')}` }} />
            </div>
          </Card>

          {/* 站点汇总 */}
          <SectionTitle icon={<EnvironmentOutlined />} title={t('batt.siteSummary')} sub={`${sites.length} ${t('batt.sitesUnit')}`} />
          <Card size="small" style={cardStyle}>
            <div style={{ display: 'flex', marginBottom: '0.625rem', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
              <span style={{ fontSize: '0.75rem', color: WH.textDim }}>{t('batt.siteSummaryHint')}</span>
              <span style={{ flex: 1 }} />
              <Button size="small" icon={<DownloadOutlined />} onClick={() => exportXlsx(sites, 'battery_sites')}
                style={{ color: WH.teal, borderColor: 'rgba(0, 217, 255,0.35)', background: 'transparent' }}>
                {t('batt.export')}
              </Button>
            </div>
            <div className="wh-table-responsive">
              <Table rowKey="site" size="small" dataSource={sites} columns={siteColumns as any}
                scroll={{ x: 'max-content', y: 460 }}
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (n) => `${n} ${t('batt.sitesUnit')}` }} />
            </div>
          </Card>
        </Col>
      </Row>

      {/* 站点下钻 */}
      <Modal open={!!drillSite} onCancel={() => setDrillSite(null)} footer={null} width={'min(95vw, 61.25rem)' as any}
        title={<span><EnvironmentOutlined style={{ color: WH.teal, marginRight: 'var(--wh-space-sm)' }} />{drillSite}</span>}>
        {drillLoading ? <div style={{ textAlign: 'center', padding: '2.5rem' }}><Spin /></div> : (
          <>
            <Row gutter={[12, 12]} style={{ marginBottom: '0.75rem' }}>
              <Col xs={12} sm={6}><Statistic title={t('batt.batteries')} value={drillData?.batteries?.length || 0} /></Col>
              <Col xs={12} sm={6}><Statistic title={t('batt.fresh')} value={(drillData?.batteries || []).filter((b: any) => b.freshness === 'fresh').length} /></Col>
              <Col xs={12} sm={6}><Statistic title={t('batt.discharging')} value={(drillData?.batteries || []).filter((b: any) => b.status === 'Discharge' && b.freshness === 'fresh').length} /></Col>
              <Col xs={12} sm={6}><Statistic title={t('batt.historyPoints')} value={drillData?.readings?.length || 0} /></Col>
            </Row>
            <div className="wh-table-responsive">
              <Table rowKey="position" size="small" pagination={false} scroll={{ y: 260 }}
                dataSource={drillData?.batteries || []}
                columns={[
                  { title: t('batt.battery'), dataIndex: 'mo', minWidth: 120 },
                  { title: 'SOC', dataIndex: 'soc', minWidth: 90, align: 'right' as const, render: (v: number | null) => v == null ? '--' : `${v}%` },
                  { title: t('batt.health'), dataIndex: 'health', minWidth: 90, align: 'right' as const, render: (v: number | null) => v == null ? '--' : `${v}%` },
                  { title: t('batt.status'), dataIndex: 'status', minWidth: 110, render: (v: string) => <Tag color={STATUS_COLORS[v] || STATUS_COLORS.Unknown} style={{ border: 'none' }}>{v}</Tag> },
                  { title: t('batt.lastUpdate'), dataIndex: 'last_update', minWidth: 170 },
                  { title: t('batt.freshness'), dataIndex: 'freshness', minWidth: 100, render: (v: string) => <Tag color={FRESH_COLORS[v]} style={{ border: 'none' }}>{v}</Tag> },
                ]} />
            </div>
          </>
        )}
      </Modal>
    </div>
  )
}
