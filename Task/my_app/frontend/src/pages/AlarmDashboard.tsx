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
import { useI18n } from '../i18n'
import DraggableClickModal from '../components/DraggableClickModal'

// ========== Warehouse 风格设计令牌 ==========
const WH = {
  bg: 'linear-gradient(180deg, #0a1929 0%, #0d2138 100%)',
  cardBg: 'linear-gradient(145deg, #141f33 0%, #112540 100%)',
  cardBorder: '1px solid rgba(100,255,218,0.18)',
  cardBorderHover: '1px solid rgba(100,255,218,0.55)',
  teal: '#64ffda',
  blue: '#4fc3f7',
  indigo: '#7986cb',
  text: '#e6f4ff',
  textMuted: '#94a3b8',
  textDim: '#64748b',
  sev: { Critical: '#ff4757', Major: '#ff922b', Warning: '#ffd43b', Info: '#4fc3f7' },
  accentGrad: 'linear-gradient(135deg, #64ffda, #4fc3f7)',
}
const WH_COLORS = ['#64ffda', '#4fc3f7', '#7986cb', '#ffd43b', '#ff6b6b', '#51cf66', '#b197fc', '#ffa94d', '#63e6be', '#5c7cfa']
const CHART_HEIGHT = 280

const darkTooltip = () => ({
  backgroundColor: 'rgba(10,25,41,0.95)',
  borderColor: 'rgba(100,255,218,0.25)',
  borderWidth: 1,
  textStyle: { color: '#e6f4ff', fontSize: 12 },
  extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.4);',
})
const axisLabel = () => ({ color: '#94a3b8', fontSize: 11 })
const axisLine = () => ({ lineStyle: { color: '#22324d' } })
const splitLine = () => ({ lineStyle: { type: 'dashed' as const, color: 'rgba(255,255,255,0.06)' } })

// 分区标题（Warehouse 青蓝渐变图标）
const SectionTitle = ({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    margin: '22px 0 14px', padding: '0 0 10px',
    borderBottom: '1px solid rgba(100,255,218,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 6,
      background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: 14,
    }}>{icon}</span>
    <span style={{ fontSize: 16, fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {sub && <span style={{ fontSize: 12, color: WH.textDim, marginLeft: 4 }}>{sub}</span>}
  </div>
)

// 顶部概览卡片（可下钻）
const SummaryCard = ({ icon, value, label, color, onClick }: {
  icon: React.ReactNode; value: string | number; label: string; color: string; onClick: () => void
}) => (
  <Card size="small" hoverable onClick={onClick} style={{
    background: WH.cardBg, border: WH.cardBorder, borderRadius: 12,
    cursor: 'pointer', transition: 'all .2s', position: 'relative', overflow: 'hidden',
    boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
  }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div>
        <div style={{ fontSize: 30, fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
        <div style={{ fontSize: 12, color: WH.textMuted, marginTop: 4, fontWeight: 500 }}>{label}</div>
      </div>
      <span style={{ fontSize: 38, opacity: 0.16, color }}>{icon}</span>
    </div>
    <div style={{ textAlign: 'right', fontSize: 10, color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
      {label !== 'Critical Alerts' ? '点击下钻' : '点击下钻'} <RightOutlined style={{ fontSize: 9 }} />
    </div>
  </Card>
)

// 历史告警指标卡片（可点击下钻）
const HistoryMetricCard = ({ icon, value, label, sub, color, onClick }: {
  icon: React.ReactNode; value: string | number; label: string; sub: string;
  color: string; onClick: (e?: React.MouseEvent) => void
}) => {
  const { t } = useI18n()
  return (
  <Card size="small" hoverable onClick={onClick} style={{
    background: WH.cardBg, border: WH.cardBorder, borderRadius: 12,
    boxShadow: '0 4px 16px rgba(0,0,0,0.25)', cursor: 'pointer', transition: 'all .2s',
    position: 'relative', overflow: 'hidden',
  }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
        <div style={{ fontSize: 12, color: WH.textMuted, marginTop: 3, fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: 10, color: WH.textDim, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>
      </div>
      <span style={{ fontSize: 34, opacity: 0.18, color, flexShrink: 0 }}>{icon}</span>
    </div>
    <div style={{ textAlign: 'right', fontSize: 10, color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
      {t('alarm.drillHint')} <RightOutlined style={{ fontSize: 9 }} />
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
  const { t } = useI18n()

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
      width: k.includes('time') || k.includes('date') ? 150 : 120,
      ellipsis: true,
      sorter: (a: any, b: any) => strSorter(a, b, k),
      filters: getUniqueFilters(drillData, k),
      onFilter: (v: any, r: any) => String(r[k]) === v,
      defaultSortOrder: k === 'server_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // ========== ECharts 图表配置（Warehouse 暗色风格） ==========

  // 持续时长分布（柱状，可点击下钻）
  const durationOption = useMemo(() => {
    if (!data?.duration_buckets) return {}
    const order = data.duration_bucket_order || []
    const allData = order.map((b: string) => data.duration_buckets[b] || 0)
    const mainsData = order.map((b: string) => (data.mains_duration_buckets || {})[b] || 0)
    return {
      tooltip: {
        ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const title = `<div style="font-weight:600;margin-bottom:4px">${ps[0].axisValue}</div>`
          return title + ps.map((p: any) => `${p.marker} ${p.seriesName}: <strong>${p.value}</strong>`).join('<br/>')
        },
      },
      legend: { data: ['All Alarms', 'Mains Fail (MW)'], bottom: 0, textStyle: { fontSize: 11, color: WH.textMuted } },
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: 'category', data: order, axisLabel: axisLabel(), axisLine: axisLine() },
      yAxis: { type: 'value', splitLine: splitLine(), axisLabel: axisLabel() },
      series: [
        {
          name: 'All Alarms', type: 'bar', barMaxWidth: 24, barGap: '30%',
          data: allData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#64ffda' }, { offset: 1, color: '#4fc3f7' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
        {
          name: 'Mains Fail (MW)', type: 'bar', barMaxWidth: 24,
          data: mainsData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#ff6b6b' }, { offset: 1, color: '#ffa94d' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
      ],
    }
  }, [data])

  // 区域告警数（柱状，可点击下钻）
  const regionOption = useMemo(() => {
    if (!data?.region_alarm_count) return {}
    const entries = Object.entries(data.region_alarm_count).filter(([, v]) => (v as number) > 0).sort((a: any, b: any) => b[1] - a[1])
    if (!entries.length) return {}
    const mainsData = entries.map(([k]) => (data.region_mains_count || {})[k] || 0)
    const siteData = entries.map(([k]) => (data.region_sites_count || {})[k] || 0)
    return {
      tooltip: {
        ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const region = entries[idx][0]
          return `<div style="font-weight:600;margin-bottom:4px">${region}</div>` +
            `Alarms: <strong>${entries[idx][1]}</strong><br/>Affected Sites: <strong>${siteData[idx]}</strong><br/>Mains Fail: <strong>${mainsData[idx]}</strong>`
        },
      },
      grid: { left: 40, right: 20, top: 10, bottom: 40 },
      xAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { ...axisLabel(), fontWeight: 500, color: WH.text }, axisLine: axisLine() },
      yAxis: { type: 'value', splitLine: splitLine(), axisLabel: axisLabel() },
      series: [{
        type: 'bar', barMaxWidth: 28,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: WH_COLORS[i % WH_COLORS.length] }, { offset: 1, color: '#0d2138' }] },
            borderRadius: [4, 4, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 10, color: WH.textMuted, fontWeight: 600 },
      }],
    }
  }, [data])

  // 各技术制式饼图（可点击下钻）
  const techPieOption = useMemo(() => {
    if (!data?.logical_total) return {}
    const entries = Object.entries(data.logical_total).filter(([t]) => t !== 'OTHER')
    return {
      tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} alarms ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: WH.textMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['38%', '65%'], center: ['35%', '50%'],
        data: entries.map(([tech, val]: any, i: number) => ({
          name: tech,
          value: val.cell,
          itemStyle: { color: WH_COLORS[i % WH_COLORS.length] },
        })),
        label: { fontSize: 10, color: WH.text, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(100,255,218,0.4)' } },
      }],
    }
  }, [data?.logical_total])

  // 告警类型 Top（横向柱状，可点击下钻）
  const alarmTypeOption = useMemo(() => {
    if (!data?.alarm_type_top) return {}
    const entries = Object.entries(data.alarm_type_top).sort((a: any, b: any) => b[1] - a[1]).slice(0, 8)
    const fullNames = entries.map(([k]) => k)
    return {
      tooltip: { ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any[]) => `${ps[0].name}: <strong>${ps[0].value}</strong>` },
      grid: { left: 20, right: 80, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(), axisLabel: axisLabel() },
      yAxis: { type: 'category', data: fullNames.slice().reverse(), axisLabel: { ...axisLabel(), color: WH.text }, axisLine: axisLine() },
      series: [{
        type: 'bar', barMaxWidth: 20,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#ff6b6b' }, { offset: 1, color: '#ffa94d' }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: WH.textMuted, formatter: (p: any) => p.value.toLocaleString() },
      }],
    }
  }, [data?.alarm_type_top])

  // 严重等级饼图（可点击下钻）
  const sevPieOption = useMemo(() => {
    if (!data?.severity_stats) return {}
    const entries = Object.entries(data.severity_stats)
    return {
      tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['32%', '62%'], center: ['50%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: WH.sev[k] || WH_COLORS[0] } })),
        label: { fontSize: 11, formatter: '{b}\n{d}%', color: WH.text },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(100,255,218,0.4)' } },
      }],
    }
  }, [data?.severity_stats])

  // 网络类型饼图（可点击下钻）
  const netTypeOption = useMemo(() => {
    if (!data?.networktype) return {}
    const entries = Object.entries(data.networktype)
    return {
      tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: WH.textMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v], i) => ({ name: k, value: v, itemStyle: { color: WH_COLORS[i % WH_COLORS.length] } })),
        label: { fontSize: 9, color: WH.text, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.networktype])

  // 站点属性饼图（可点击下钻）
  const siteAttrOption = useMemo(() => {
    if (!data?.site_attribute) return {}
    const entries = Object.entries(data.site_attribute)
    const attrColors: Record<string, string> = { REGULAR: '#51cf66', ERA: '#7986cb', '--': '#64748b' }
    return {
      tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10, color: WH.textMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: attrColors[k] || WH_COLORS[0] } })),
        label: { fontSize: 9, color: WH.text, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.site_attribute])

  // ========== 渲染 ==========
  if (loading) return (
    <div style={{ background: WH.bg, borderRadius: 12, textAlign: 'center', padding: 60 }}>
      <Spin size="large" />
      <div style={{ marginTop: 12, color: WH.textMuted }}>Loading Alarm Dashboard...</div>
    </div>
  )

  if (error) return (
    <Alert type="error" message="Failed to load Alarm Dashboard" description={error} showIcon style={{ margin: 16 }} />
  )

  if (!data) return <Empty description="No alarm data available" />

  const { logical_total } = data
  const sevStats = data.severity_stats || {}
  const fmt = (n: number) => n?.toLocaleString() || '0'
  const hist = data.history || {}

  // 图表点击 → 下钻
  const chartClick = (builder: (p: any) => DrillReq) => (p: any) => openDrilldown(p, builder(p))

  const pageWrap: React.CSSProperties = {
    background: WH.bg,
    borderRadius: 12,
    padding: 4,
    minHeight: 'calc(100vh - 110px)',
  }

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* ====== 1. 头部警报横幅 ====== */}
      <Card size="small" style={{
        background: 'linear-gradient(135deg, #1a0f14 0%, #112540 100%)',
        borderLeft: `4px solid ${WH.sev.Critical}`,
        borderRadius: 12,
        boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        marginBottom: 4,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FireOutlined style={{ fontSize: 22, color: '#ff6b6b' }} />
            <span style={{ fontSize: 15, fontWeight: 700, color: '#ff8787' }}>
              Real-time Alarm Status
            </span>
            <Tag color="error" style={{ borderRadius: 12, fontWeight: 600, cursor: 'pointer' }}
              onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'all', title: 'Total Active Alarms' })}>
              {fmt(data.total_alarms)} Active Alarms
            </Tag>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: WH.textDim }}>
            <ClockCircleOutlined />
            <span>Updated: {data.generated_at}</span>
          </div>
        </div>
      </Card>

      {/* ====== 2. 核心指标卡片（全部可下钻） ====== */}
      <Row gutter={[12, 12]}>
        <Col span={6}>
          <SummaryCard
            icon={<AlertOutlined />}
            value={fmt(data.total_alarms)}
            label="Total Active Alarms"
            color={WH.teal}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: 'Total Active Alarms' })} />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<EnvironmentOutlined />}
            value={fmt(data.affected_sites)}
            label="Affected Sites"
            color={WH.blue}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: 'Affected Sites (all active alarms)' })} />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<ClockCircleOutlined />}
            value={fmt(data.total_alarm_hours)}
            label="Total Alarm Hours"
            color={WH.indigo}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'all', title: 'Total Alarm Hours (all active alarms)' })} />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<WarningOutlined />}
            value={fmt(sevStats.Critical || 0)}
            label="Critical Alerts"
            color={WH.sev.Critical}
            onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'severity', value: 'Critical', title: 'Critical Alerts' })} />
        </Col>
      </Row>

      {/* ====== 2.5 历史告警派单时效分析（可下钻） ====== */}
      <SectionTitle icon={<HistoryOutlined />} title="History Alarm Dispatch Timeliness" sub={`historical alarms · data as of ${hist.generated_at || 'N/A'} · click card to drill down`} />
      <Row gutter={[12, 12]}>
        <Col span={6}>
          <HistoryMetricCard
            icon={<HistoryOutlined />}
            value={fmt(hist.total || 0)}
            label="Total History Alarms"
            sub={t('alarm.dispatchedWithTT', { n: fmt(hist.with_tt || 0) })}
            color={WH.blue}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'all', title: 'Total History Alarms' })} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<SendOutlined />}
            value={fmt(hist.dispatch_delay_eflow || 0)}
            label="Dispatch Delay (Eflow)"
            sub="Assigned - Server > Assign Delay +10%"
            color={WH.indigo}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'dispatch_delay_eflow', title: 'Dispatch Delay (Eflow)' })} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<FieldTimeOutlined />}
            value={fmt(hist.alarm_fetch_delay || 0)}
            label="Alarm Fetch Delay"
            sub="Server - AlarmRaised > 5 min"
            color={WH.teal}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'alarm_fetch_delay', title: 'Alarm Fetch Delay' })} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<HourglassOutlined />}
            value={fmt(hist.dispatch_overdue_total || 0)}
            label="Dispatch Overdue Total"
            sub={t('alarm.overdueDesc')}
            color={WH.sev.Critical}
            onClick={(e) => openDrilldown(e, { source: 'history', metric: 'dispatch_overdue_total', title: 'Dispatch Overdue Total' })} />
        </Col>
      </Row>

      {/* ====== 3. 技术制式 + 严重等级 + 网络类型 ====== */}
      <SectionTitle icon={<ApiOutlined />} title="Alarm Breakdown" sub="by Technology, Severity & Network Type" />
      <Row gutter={[12, 12]}>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Technology Distribution</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={techPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'tech', value: p.name, title: `Tech = ${p.name}` })) }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Severity Distribution</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={sevPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'severity', value: p.name, title: `Severity = ${p.name}` })) }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Network Type</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={netTypeOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'networktype', value: p.name, title: `Network = ${p.name}` })) }} />
          </Card>
        </Col>
      </Row>

      {/* ====== 4. 技术制式详细卡片（可下钻） ====== */}
      <Row gutter={[12, 12]} style={{ marginTop: 4 }}>
        {Object.entries(logical_total || {})
          .filter(([tech]) => tech !== 'OTHER')
          .map(([tech, val]: any, idx: number) => (
            <Col span={6} key={tech}>
              <Card size="small" hoverable onClick={() => openDrilldown(null, { source: 'realtime', dimension: 'tech', value: tech, title: `Tech = ${tech}` })} style={{
                background: WH.cardBg, borderRadius: 12,
                border: WH.cardBorder, cursor: 'pointer', transition: 'all .2s',
                boxShadow: '0 4px 16px rgba(0,0,0,0.25)', position: 'relative', overflow: 'hidden',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: WH_COLORS[idx % WH_COLORS.length],
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#06222e', fontSize: 16, fontWeight: 800,
                  }}>{tech}</div>
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: WH_COLORS[idx % WH_COLORS.length], lineHeight: 1.2 }}>{fmt(val.site || 0)}</div>
                    <div style={{ fontSize: 11, color: WH.textMuted }}>Sites · {fmt(val.cell || 0)} Cells</div>
                  </div>
                </div>
                <div style={{ textAlign: 'right', fontSize: 10, color: WH.teal, fontWeight: 600, marginTop: 4, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
                  点击下钻 <RightOutlined style={{ fontSize: 9 }} />
                </div>
              </Card>
            </Col>
          ))}
      </Row>

      {/* ====== 5. 持续时长分布 + 区域告警分布 ====== */}
      <SectionTitle icon={<BarChartOutlined />} title="Duration & Regional Distribution" sub="alarm persistence & geographic spread" />
      <Row gutter={[12, 12]}>
        <Col span={12}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Alarm Duration Distribution</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={durationOption} style={{ height: CHART_HEIGHT + 30 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'duration', value: String(p.name), title: `Duration = ${p.name}` })) }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Alarms by Region</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={regionOption} style={{ height: CHART_HEIGHT + 30 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'region', value: String(p.name), title: `Region = ${p.name}` })) }} />
          </Card>
        </Col>
      </Row>

      {/* ====== 6. 告警类型 Top + 站点属性 ====== */}
      <SectionTitle icon={<PieChartOutlined />} title="Alarm Type & Site Attribute" sub="most frequent alarm types & site classification" />
      <Row gutter={[12, 12]}>
        <Col span={14}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Top Alarm Types</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={alarmTypeOption} style={{ height: CHART_HEIGHT + 40 }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'alarm_type', value: String(p.name), title: `Alarm Type = ${p.name}` })) }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Site Attribute</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <ReactECharts option={siteAttrOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick(p => ({ source: 'realtime', dimension: 'site_attribute', value: String(p.name), title: `Site Attr = ${p.name}` })) }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600, color: WH.text }}>Severity Tags</span>} style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 0' }}>
              {Object.entries(sevStats).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '2px 4px', borderRadius: 6 }}
                  onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'severity', value: k, title: `Severity = ${k}` })}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(100,255,218,0.08)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <Tag color={WH.sev[k] || '#999'} style={{ borderRadius: 12, fontWeight: 500 }}>{k}</Tag>
                  <span style={{ fontSize: 18, fontWeight: 700, color: WH.sev[k] || WH.text }}>{fmt(v as number)}</span>
                </div>
              ))}
              <div style={{ marginTop: 8, borderTop: '1px solid rgba(100,255,218,0.18)', paddingTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '2px 4px', borderRadius: 6 }}
                  onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'all', title: 'Total Active Alarms' })}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(100,255,218,0.08)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <Tag color="cyan" style={{ borderRadius: 12, fontWeight: 500 }}>Total</Tag>
                  <span style={{ fontSize: 18, fontWeight: 700, color: WH.teal }}>{fmt(data.total_alarms)}</span>
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* ====== 7. 各区域 Top 告警类型（可下钻） ====== */}
      {data.region_alarm_type && Object.keys(data.region_alarm_type).length > 0 && (
        <>
          <SectionTitle icon={<DashboardOutlined />} title="Regional Alarm Profile" sub="top alarm types per region" />
          <Card size="small" style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }}>
            <Row gutter={[8, 8]}>
              {Object.entries(data.region_alarm_type)
                .filter(([, v]: any) => Object.keys(v).length > 0)
                .slice(0, 10)
                .map(([region, types]: any) => (
                  <Col span={6} key={region} style={{ marginBottom: 8 }}>
                    <div style={{
                      background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px',
                      borderLeft: `3px solid ${WH.teal}`,
                    }}>
                      <div style={{ fontWeight: 700, fontSize: 13, color: WH.text, marginBottom: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Tag color="cyan" style={{ borderRadius: 8, marginRight: 6, cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'region', value: region, title: `Region = ${region}` })}>{region}</Tag>
                        <span style={{ fontSize: 11, color: WH.textDim, cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'region', value: region, title: `Region = ${region}` })}>
                          {data.region_alarm_count[region]} alarms ↗
                        </span>
                      </div>
                      {Object.entries(types).map(([type, count]: any, i: number) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0', color: WH.textMuted, cursor: 'pointer' }}
                          onClick={(e) => openDrilldown(e, { source: 'realtime', dimension: 'alarm_type', value: type, title: `Alarm Type = ${type}` })}
                          onMouseEnter={ev => { (ev.currentTarget as HTMLElement).style.color = WH.teal }}
                          onMouseLeave={ev => { (ev.currentTarget as HTMLElement).style.color = WH.textMuted }}
                        >
                          <Tooltip title={type}>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 130 }}>
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
        dark
        onClose={() => setDrillOpen(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan" style={{ borderRadius: 10 }}>{filteredDrillData.length} records</Tag>{drillTotal > drillData.length && <Tag color="red" style={{ borderRadius: 10 }}>{t('alarm.recordCount', { total: fmt(drillTotal), shown: drillData.length })}</Tag>}</span>}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <Input
            prefix={<SearchOutlined />}
            placeholder="Search across all fields..."
            allowClear
            size="middle"
            style={{ width: 350 }}
            value={drillSearch}
            onChange={e => setDrillSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={exportToExcel}
            disabled={!filteredDrillData.length}
          >
            Export Excel
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '60px auto' }} />
        ) : (
          <Table
            dataSource={filteredDrillData}
            columns={drillColumns}
            size="small"
            rowKey={(r: any) => `${r.site_id ?? 'x'}|${r.server_time ?? r.alarm_raised_time ?? r.tt_id ?? 'x'}|${r.alarm_title ?? 'x'}`}
            pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => `${total} items` }}
            scroll={{ x: 'max-content' }}
          />
        )}
      </DraggableClickModal>
    </div>
  )
}
