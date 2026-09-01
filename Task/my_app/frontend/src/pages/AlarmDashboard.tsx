// Alarm Dashboard - 实时告警综合看板（置于 TT&WO Dashboard 上方）
// 设计风格参考 Warehouse 看板：深空蓝底 + 青/蓝渐变高亮，数字可下钻。
import { useEffect, useState, useMemo, useCallback } from 'react'
import { Card, Row, Col, Tag, Spin, Alert, Empty, Tooltip, Table, Input, Button } from 'antd'
import {
  AlertOutlined, WarningOutlined, ClockCircleOutlined,
  ApiOutlined, PieChartOutlined, BarChartOutlined,
  DashboardOutlined, EnvironmentOutlined, FireOutlined,
  HistoryOutlined, SendOutlined, FieldTimeOutlined, HourglassOutlined,
  DownloadOutlined, SearchOutlined, RightOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import api from '../api'
import { cachedGet } from '../cache'
import { useI18n, numLocale } from '../i18n'
import DraggableClickModal from '../components/DraggableClickModal'
import { ExplainCorner, ExplainIcon } from '../components/MetricExplain'
import { WH, DARK, LIGHT, WH_COLORS, LIGHT_COLORS, useTheme, darkTooltip, axisLabel, axisLine, splitLine, pageWrap, cardStyle } from '../theme'

const CHART_HEIGHT = 280

// 分区标题（Warehouse 青蓝渐变图标）
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

// 顶部概览卡片（可下钻）
const SummaryCard = ({ icon, value, label, color, onClick, explain }: {
  icon: React.ReactNode; value: string | number; label: string; color: string; onClick: () => void; explain?: string
}) => {
  const { t } = useI18n()
  return (
  <Card size="small" hoverable onClick={onClick} style={{
    ...cardStyle,
    cursor: 'pointer', transition: 'all .2s', position: 'relative', overflow: 'hidden',
  }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
    {explain && <ExplainCorner text={explain} />}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div>
        <div style={{ fontSize: '1.875rem', fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
        <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginTop: 'var(--wh-space-xs)', fontWeight: 500 }}>{label}</div>
      </div>
      <span style={{ fontSize: '2.375rem', opacity: 0.16, color }}>{icon}</span>
    </div>
    <div style={{ textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
      {t('alarm.drillHint')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
    </div>
  </Card>
  )
}

// 历史告警指标卡片（可点击下钻）
const HistoryMetricCard = ({ icon, value, label, sub, color, onClick, explain }: {
  icon: React.ReactNode; value: string | number; label: string; sub: string;
  color: string; onClick: (e?: React.MouseEvent) => void; explain?: string
}) => {
  const { t } = useI18n()
  return (
  <Card size="small" hoverable onClick={onClick} style={{
    ...cardStyle,
    cursor: 'pointer', transition: 'all .2s',
    position: 'relative', overflow: 'hidden',
  }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
    {explain && <ExplainCorner text={explain} />}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: '1.625rem', fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
        <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginTop: 3, fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: '0.625rem', color: WH.textDim, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>
      </div>
      <span style={{ fontSize: '2.125rem', opacity: 0.18, color, flexShrink: 0 }}>{icon}</span>
    </div>
    <div style={{ textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
      {t('alarm.drillHint')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
    </div>
  </Card>
  )
}

// 通用排序器
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}
const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

export default function AlarmDashboard() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<any>(null)
  const { t, locale } = useI18n()
  const { isDark } = useTheme()

  // ========== 下钻状态 ==========
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
    cachedGet('alarm:overview', () => api.get('/alarm-dashboard/overview'))
      .then(res => { setData(res.data); setError(null) })
      .catch(err => { console.error('Alarm Dashboard API error:', err); setError(err.message || 'Failed to load') })
      .finally(() => setLoading(false))
  }, [])

  type DrillReq =
    | { source: 'history'; metric: string; title: string }
    | { source: 'realtime'; dimension: string; value?: string; title: string }

  // 打开下钻弹窗并拉取明细（统一支持 history / realtime 两类数据源）
  const openDrilldown = useCallback((trigger: any, req: DrillReq) => {
    // 以点击位置为中心弹出（兼容 DOM 事件 与 ECharts params）
    let anchor: { x: number; y: number } | null = null
    if (trigger && typeof trigger.clientX === 'number') {
      anchor = { x: trigger.clientX, y: trigger.clientY }
    } else if (trigger && trigger.event && trigger.event.event && typeof trigger.event.event.clientX === 'number') {
      anchor = { x: trigger.event.event.clientX, y: trigger.event.event.clientY }
    }
    setDrillAnchor(anchor)
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillTitle(req.title)
    const isHistory = req.source === 'history'
    const url = isHistory ? '/alarm-dashboard/history-drilldown' : '/alarm-dashboard/realtime-drilldown'
    const params = isHistory
      ? { metric: (req as any).metric, limit: 500 }
      : { dimension: (req as any).dimension, value: (req as any).value ?? '', limit: 500 }
    api.get(url, { params })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTitle(res.data.title || req.title)
        setDrillTotal(res.data.total || 0)
      })
      .catch(err => {
        console.error('Drilldown API error:', err)
        setDrillTitle('Failed to load data')
      })
      .finally(() => setDrillLoading(false))
  }, [])

  // 模糊搜索
  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row =>
      Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
    )
  }, [drillData, drillSearch])

  // 导出Excel
  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const header = keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const ws = XLSX.utils.aoa_to_sheet([header, ...rows])
    ws['!cols'] = keys.map(() => ({ wch: 18 }))
    const wb = XLSX.utils.book_new()
    const fname = `Alarm_${dayjs().format('YYYYMMDD_HHmmss')}`
    XLSX.utils.book_append_sheet(wb, ws, fname.substring(0, 31))
    XLSX.writeFile(wb, `${fname}.xlsx`)
  }, [filteredDrillData])

  // 下钻表格列定义
  const drillColumns = useMemo(() => {
    if (!drillData.length) return []
    const keys = Object.keys(drillData[0])
    return keys.map(k => ({
      title: k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      dataIndex: k,
      key: k,
      minWidth: k.includes('time') || k.includes('date') ? 150 : 120,
      ellipsis: true,
      sorter: (a: any, b: any) => strSorter(a, b, k),
      filters: getUniqueFilters(drillData, k),
      onFilter: (v: any, r: any) => String(r[k]) === v,
      defaultSortOrder: k === 'server_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // ========== ECharts 图表配置（Warehouse 暗色风格） ==========

  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const cText = isDark ? '#e6f4ff' : '#16233b'
  const cTextMuted = isDark ? '#94a3b8' : '#3f5468'
  const cTeal = isDark ? '#64ffda' : '#0d9488'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS

  // 持续时长分布（柱状，可点击下钻）
  const durationOption = useMemo(() => {
    if (!data?.duration_buckets) return {}
    const order = data.duration_bucket_order || []
    const allData = order.map((b: string) => data.duration_buckets[b] || 0)
    const mainsData = order.map((b: string) => (data.mains_duration_buckets || {})[b] || 0)
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const title = `<div style="font-weight:600;margin-bottom:4px">${ps[0].axisValue}</div>`
          return title + ps.map((p: any) => `${p.marker} ${p.seriesName}: <strong>${p.value}</strong>`).join('<br/>')
        },
      },
      legend: { data: [t('alarm.seriesAll'), t('alarm.seriesMains')], bottom: 0, textStyle: { fontSize: 11, color: cTextMuted } },
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: 'category', data: order, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark) },
      yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [
        {
          name: t('alarm.seriesAll'), type: 'bar', barMaxWidth: 24, barGap: '30%',
          data: allData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? '#64ffda' : '#0d9488' }, { offset: 1, color: isDark ? '#4fc3f7' : '#0284c7' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
        {
          name: t('alarm.seriesMains'), type: 'bar', barMaxWidth: 24,
          data: mainsData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? '#ff6b6b' : '#dc2626' }, { offset: 1, color: isDark ? '#ffa94d' : '#ea580c' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
      ],
    }
  }, [data, t, isDark])

  // 区域告警数（柱状，可点击下钻）
  const regionOption = useMemo(() => {
    if (!data?.region_alarm_count) return {}
    const entries = Object.entries(data.region_alarm_count).filter(([, v]) => (v as number) > 0).sort((a: any, b: any) => b[1] - a[1])
    if (!entries.length) return {}
    const mainsData = entries.map(([k]) => (data.region_mains_count || {})[k] || 0)
    const siteData = entries.map(([k]) => (data.region_sites_count || {})[k] || 0)
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const region = entries[idx][0]
          return `<div style="font-weight:600;margin-bottom:4px">${region}</div>` +
            `${t('alarm.tipAlarms')}: <strong>${entries[idx][1]}</strong><br/>` +
            `${t('alarm.affectedSites')}: <strong>${siteData[idx]}</strong><br/>` +
            `${t('alarm.tipMainsFail')}: <strong>${mainsData[idx]}</strong>`
        },
      },
      grid: { left: 40, right: 20, top: 10, bottom: 40 },
      xAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { ...axisLabel(isDark), fontWeight: 500, color: cText }, axisLine: axisLine(isDark) },
      yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [{
        type: 'bar', barMaxWidth: 28,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: cPalette[i % cPalette.length] }, { offset: 1, color: isDark ? '#0d2138' : '#dcebf5' }] },
            borderRadius: [4, 4, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 10, color: cTextMuted, fontWeight: 600 },
      }],
    }
  }, [data, t, isDark])

  // 各技术制式饼图（可点击下钻）
  const techPieOption = useMemo(() => {
    if (!data?.logical_total) return {}
    const entries = Object.entries(data.logical_total).filter(([t]) => t !== 'OTHER')
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: t('alarm.pieTooltip') },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['38%', '65%'], center: ['35%', '50%'],
        data: entries.map(([tech, val]: any, i: number) => ({
          name: tech,
          value: val.cell,
          itemStyle: { color: cPalette[i % cPalette.length] },
        })),
        label: { fontSize: 10, color: cText, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.4)' : 'rgba(13,148,136,0.35)' } },
      }],
    }
  }, [data?.logical_total, t, isDark])

  // 告警类型 Top（横向柱状，可点击下钻）
  const alarmTypeOption = useMemo(() => {
    if (!data?.alarm_type_top) return {}
    const entries = Object.entries(data.alarm_type_top).sort((a: any, b: any) => b[1] - a[1]).slice(0, 8)
    const fullNames = entries.map(([k]) => k)
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any[]) => `${ps[0].name}: <strong>${ps[0].value}</strong>` },
      grid: { left: 20, right: 80, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: fullNames.slice().reverse(), axisLabel: { ...axisLabel(isDark), color: cText }, axisLine: axisLine(isDark) },
      series: [{
        type: 'bar', barMaxWidth: 20,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#ff6b6b' : '#dc2626' }, { offset: 1, color: isDark ? '#ffa94d' : '#ea580c' }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.alarm_type_top, locale, isDark])

  // 严重等级饼图（可点击下钻）
  const sevPieOption = useMemo(() => {
    if (!data?.severity_stats) return {}
    const entries = Object.entries(data.severity_stats)
    const sev = isDark ? DARK.sev : LIGHT.sev
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['32%', '62%'], center: ['50%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: sev[k] || cPalette[0] } })),
        label: { fontSize: 11, formatter: '{b}\n{d}%', color: cText },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.4)' : 'rgba(13,148,136,0.35)' } },
      }],
    }
  }, [data?.severity_stats, isDark])

  // 网络类型饼图（可点击下钻）
  const netTypeOption = useMemo(() => {
    if (!data?.networktype) return {}
    const entries = Object.entries(data.networktype)
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v], i) => ({ name: k, value: v, itemStyle: { color: cPalette[i % cPalette.length] } })),
        label: { fontSize: 9, color: cText, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.networktype, isDark])

  // 站点属性饼图（可点击下钻）
  const siteAttrOption = useMemo(() => {
    if (!data?.site_attribute) return {}
    const entries = Object.entries(data.site_attribute)
    const attrColors: Record<string, string> = {
      REGULAR: isDark ? '#51cf66' : '#15803d',
      ERA: isDark ? '#7986cb' : '#6366f1',
      '--': isDark ? '#64748b' : '#5b7288',
    }
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: attrColors[k] || cPalette[0] } })),
        label: { fontSize: 9, color: cText, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.site_attribute, isDark])

  // ========== 渲染 ==========
  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '3.75rem' }}>
      <Spin size="large" />
      <div style={{ marginTop: '0.75rem', color: WH.textMuted }}>{t('alarm.loading')}</div>
    </div>
  )

  if (error) return (
    <Alert type="error" message={t('alarm.loadFailed')} description={error} showIcon style={{ margin: 'var(--wh-space-md)' }} />
  )

  if (!data) return <Empty description={t('alarm.noData')} />

  const { logical_total } = data
  const sevStats = data.severity_stats || {}
  const fmt = (n: number) => n?.toLocaleString(numLocale(locale)) || '0'
  const hist = data.history || {}

  // 图表点击 → 下钻
  const chartClick = (builder: (p: any) => DrillReq) => (p: any) => openDrilldown(p, builder(p))

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)' }}>
      {/* ====== 1. 头部警报横幅 ====== */}
      <Card size="small" style={{
        ...cardStyle,
        background: isDark ? 'linear-gradient(135deg, #1a0f14 0%, #112540 100%)' : 'linear-gradient(135deg, #fdf0f0 0%, #fbe4e4 100%)',
        borderLeft: `4px solid ${WH.sev.Critical}`,
        marginBottom: 'var(--wh-space-xs)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
            <FireOutlined style={{ fontSize: '1.375rem', color: isDark ? '#ff6b6b' : '#dc2626' }} />
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: isDark ? '#ff8787' : '#b91c1c' }}>
              {t('alarm.realtimeStatus')}
            </span>
            <Tag color="error" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 600, cursor: 'pointer' }}
              onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'all', title: t('alarm.totalActive') })}>
              {fmt(data.total_alarms)} {t('alarm.activeAlarms')}
            </Tag>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-md)', fontSize: '0.75rem', color: WH.textDim }}>
            <ClockCircleOutlined />
            <span>{t('alarm.updated')} {data.generated_at}</span>
          </div>
        </div>
      </Card>

      {/* ====== 2. 核心指标卡片（全部可下钻） ====== */}
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={12} md={6}>
          <SummaryCard
            icon={<AlertOutlined />}
            value={fmt(data.total_alarms)}
            label={t('alarm.totalActive')}
            color={WH.teal}
            explain={t('alarm.explain.totalAlarms')}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: t('alarm.totalActive') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <SummaryCard
            icon={<EnvironmentOutlined />}
            value={fmt(data.affected_sites)}
            label={t('alarm.affectedSites')}
            color={WH.blue}
            explain={t('alarm.explain.affectedSites')}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: t('alarm.affectedSitesFull') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <SummaryCard
            icon={<ClockCircleOutlined />}
            value={fmt(data.total_alarm_hours)}
            label={t('alarm.totalHours')}
            color={WH.indigo}
            explain={t('alarm.explain.totalHours')}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: t('alarm.totalHoursFull') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <SummaryCard
            icon={<WarningOutlined />}
            value={fmt(sevStats.Critical || 0)}
            label={t('alarm.criticalAlerts')}
            color={WH.sev.Critical}
            explain={t('alarm.explain.critical')}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'severity', value: 'Critical', title: t('alarm.criticalAlerts') })} />
        </Col>
      </Row>

      {/* ====== 2.5 历史告警派单时效分析（可下钻） ====== */}
      <SectionTitle icon={<HistoryOutlined />} title={t('alarm.historySection')} sub={t('alarm.historySectionSub', { at: hist.generated_at || 'N/A' })} />
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={12} md={6}>
          <HistoryMetricCard
            icon={<HistoryOutlined />}
            value={fmt(hist.total || 0)}
            label={t('alarm.totalHistory')}
            sub={t('alarm.dispatchedWithTT', { n: fmt(hist.with_tt || 0) })}
            color={WH.blue}
            explain={t('alarm.explain.historyTotal')}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'all', title: t('alarm.totalHistory') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <HistoryMetricCard
            icon={<SendOutlined />}
            value={fmt(hist.dispatch_delay_eflow || 0)}
            label={t('alarm.dispatchDelay')}
            sub={t('alarm.dispatchDelayDesc')}
            color={WH.indigo}
            explain={t('alarm.explain.dispatchDelay')}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'dispatch_delay_eflow', title: t('alarm.dispatchDelay') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <HistoryMetricCard
            icon={<FieldTimeOutlined />}
            value={fmt(hist.alarm_fetch_delay || 0)}
            label={t('alarm.fetchDelay')}
            sub={t('alarm.fetchDelayDesc')}
            color={WH.teal}
            explain={t('alarm.explain.fetchDelay')}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'alarm_fetch_delay', title: t('alarm.fetchDelay') })} />
        </Col>
        <Col xs={12} sm={12} md={6}>
          <HistoryMetricCard
            icon={<HourglassOutlined />}
            value={fmt(hist.dispatch_overdue_total || 0)}
            label={t('alarm.dispatchOverdue')}
            sub={t('alarm.overdueDesc')}
            color={WH.sev.Critical}
            explain={t('alarm.explain.dispatchOverdue')}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'dispatch_overdue_total', title: t('alarm.dispatchOverdue') })} />
        </Col>
      </Row>

      {/* ====== 3. 技术制式 + 严重等级 + 网络类型 ====== */}
      <SectionTitle icon={<ApiOutlined />} title={t('alarm.breakdown')} sub={t('alarm.breakdownSub')} />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.techDist')} <ExplainIcon text={t('alarm.explain.tech')} /></span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.techDist')} ${t('alarm.chartSuffix')}`}><ReactECharts option={techPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'tech', value: p.name, title: t('alarm.drillTech', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.sevDist')}</span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.sevDist')} ${t('alarm.chartSuffix')}`}><ReactECharts option={sevPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'severity', value: p.name, title: t('alarm.drillSeverity', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.netType')}</span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.netType')} ${t('alarm.chartSuffix')}`}><ReactECharts option={netTypeOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'networktype', value: p.name, title: t('alarm.drillNetwork', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
      </Row>

      {/* ====== 4. 技术制式详细卡片（可下钻） ====== */}
      <Row gutter={[12, 12]} style={{ marginTop: 'var(--wh-space-xs)' }}>
        {Object.entries(logical_total || {})
          .filter(([tech]) => tech !== 'OTHER')
          .map(([tech, val]: any, idx: number) => (
            <Col xs={12} sm={12} md={6} key={tech}>
              <Card size="small" hoverable onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'tech', value: tech, title: t('alarm.drillTech', { v: tech }) })} style={{
                ...cardStyle,
                cursor: 'pointer', transition: 'all .2s',
                position: 'relative', overflow: 'hidden',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 'var(--wh-radius-md)',
                    background: cPalette[idx % cPalette.length],
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#06222e', fontSize: '1rem', fontWeight: 800,
                  }}>{tech}</div>
                  <div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: cPalette[idx % cPalette.length], lineHeight: 1.2 }}>{fmt(val.site || 0)}</div>
                    <div style={{ fontSize: '0.6875rem', color: WH.textMuted }}>{t('alarm.sites')} · {fmt(val.cell || 0)} {t('alarm.cells')}</div>
                  </div>
                </div>
                <div style={{ textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600, marginTop: 'var(--wh-space-xs)', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
                  {t('alarm.drillHint')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
                </div>
              </Card>
            </Col>
          ))}
      </Row>

      {/* ====== 5. 持续时长分布 + 区域告警分布 ====== */}
      <SectionTitle icon={<BarChartOutlined />} title={t('alarm.durationSection')} sub={t('alarm.durationSectionSub')} />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={12}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.durationDist')} <ExplainIcon text={t('alarm.explain.duration')} /></span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.durationDist')} ${t('alarm.chartSuffix')}`}><ReactECharts option={durationOption} style={{ height: CHART_HEIGHT + 30 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'duration', value: String(p.name), title: t('alarm.drillDuration', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.byRegion')} <ExplainIcon text={t('alarm.explain.region')} /></span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.byRegion')} ${t('alarm.chartSuffix')}`}><ReactECharts option={regionOption} style={{ height: CHART_HEIGHT + 30 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'region', value: String(p.name), title: t('alarm.drillRegion', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
      </Row>

      {/* ====== 6. 告警类型 Top + 站点属性 ====== */}
      <SectionTitle icon={<PieChartOutlined />} title={t('alarm.typeSection')} sub={t('alarm.typeSectionSub')} />
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.topTypes')}</span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.topTypes')} ${t('alarm.chartSuffix')}`}><ReactECharts option={alarmTypeOption} style={{ height: CHART_HEIGHT + 40 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'alarm_type', value: String(p.name), title: t('alarm.drillAlarmType', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.siteAttr')}</span>} style={cardStyle}>
            <div role="img" aria-label={`${t('alarm.siteAttr')} ${t('alarm.chartSuffix')}`}><ReactECharts option={siteAttrOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'site_attribute', value: String(p.name), title: t('alarm.drillSiteAttr', { v: p.name }) })) }} /></div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('alarm.sevTags')}</span>} style={cardStyle}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)', padding: 'var(--wh-space-sm) 0' }}>
              {Object.entries(sevStats).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '0.125rem var(--wh-space-xs)', borderRadius: 'var(--wh-radius-sm)' }}
                  onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'severity', value: k, title: t('alarm.drillSeverity', { v: k }) })}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(100,255,218,0.08)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <Tag color={WH.sev[k] || '#999'} style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 500 }}>{k}</Tag>
                  <span style={{ fontSize: '1.125rem', fontWeight: 700, color: WH.sev[k] || WH.text }}>{fmt(v as number)}</span>
                </div>
              ))}
              <div style={{ marginTop: 'var(--wh-space-sm)', borderTop: '1px solid rgba(100,255,218,0.18)', paddingTop: 'var(--wh-space-sm)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '0.125rem var(--wh-space-xs)', borderRadius: 'var(--wh-radius-sm)' }}
                  onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'all', title: t('alarm.totalActive') })}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(100,255,218,0.08)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <Tag color="cyan" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 500 }}>{t('alarm.totalTag')}</Tag>
                  <span style={{ fontSize: '1.125rem', fontWeight: 700, color: WH.teal }}>{fmt(data.total_alarms)}</span>
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* ====== 7. 各区域 Top 告警类型（可下钻） ====== */}
      {data.region_alarm_type && Object.keys(data.region_alarm_type).length > 0 && (
        <>
          <SectionTitle icon={<DashboardOutlined />} title={t('alarm.regionProfile')} sub={t('alarm.regionProfileSub')} />
          <Card size="small" style={cardStyle}>
            <Row gutter={[8, 8]}>
              {Object.entries(data.region_alarm_type)
                .filter(([, v]: any) => Object.keys(v).length > 0)
                .slice(0, 10)
                .map(([region, types]: any) => (
                  <Col xs={12} sm={12} md={6} key={region} style={{ marginBottom: 'var(--wh-space-sm)' }}>
                    <div style={{
                      background: 'var(--wh-subtle-bg)', borderRadius: 'var(--wh-radius-md)', padding: '0.625rem 0.75rem',
                      borderLeft: `3px solid ${WH.teal}`,
                    }}>
                      <div style={{ fontWeight: 700, fontSize: '0.8125rem', color: WH.text, marginBottom: '0.375rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Tag color="cyan" style={{ borderRadius: 'var(--wh-radius-sm)', marginRight: 'var(--wh-space-xs)', cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'region', value: region, title: t('alarm.drillRegion', { v: region }) })}>{region}</Tag>
                        <span style={{ fontSize: '0.6875rem', color: WH.textDim, cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'region', value: region, title: t('alarm.drillRegion', { v: region }) })}>
                          {t('alarm.regionAlarms', { n: data.region_alarm_count[region] })}
                        </span>
                      </div>
                      {Object.entries(types).map(([type, count]: any, i: number) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6875rem', padding: '0.125rem 0', color: WH.textMuted, cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'alarm_type', value: type, title: t('alarm.drillAlarmType', { v: type }) })}
                          onMouseEnter={ev => { (ev.currentTarget as HTMLElement).style.color = WH.teal }}
                          onMouseLeave={ev => { (ev.currentTarget as HTMLElement).style.color = WH.textMuted }}
                        >
                          <Tooltip title={type}>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '8.125rem' }}>
                              {type.length > 22 ? type.substring(0, 20) + '..' : type}
                            </span>
                          </Tooltip>
                          <span style={{ fontWeight: 600, color: '#ff8787' }}>{count}</span>
                        </div>
                      ))}
                    </div>
                  </Col>
                ))}
            </Row>
          </Card>
        </>
      )}

      {/* ====== 下钻弹窗（暗色主题，以点击位置为中心、可拖动） ====== */}
      <DraggableClickModal
        open={drillOpen}
        anchor={drillAnchor}
        onClose={() => setDrillOpen(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan" style={{ borderRadius: 10 }}>{t('common.records', { n: filteredDrillData.length })}</Tag>{drillTotal > drillData.length && <Tag color="red" style={{ borderRadius: 10 }}>{t('alarm.recordCount', { total: fmt(drillTotal), shown: drillData.length })}</Tag>}</span>}
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
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table
              dataSource={filteredDrillData}
              columns={drillColumns}
              size="small"
              rowKey={(r: any) => `${r.site_id ?? 'x'}|${r.server_time ?? r.alarm_raised_time ?? r.tt_id ?? 'x'}|${r.alarm_title ?? 'x'}`}
              pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => t('common.itemsTotal', { n: total }) }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </DraggableClickModal>
    </div>
  )
}
