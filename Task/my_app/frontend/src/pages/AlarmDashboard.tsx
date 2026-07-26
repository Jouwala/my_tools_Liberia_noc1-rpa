// Alarm Dashboard - 实时告警综合看板（置于 TT&WO Dashboard 上方）
import { useEffect, useState, useMemo, useCallback } from 'react'
import { Card, Row, Col, Tag, Spin, Alert, Empty, Tooltip, Modal, Table, Input, Button } from 'antd'
import {
  AlertOutlined, WarningOutlined, ClockCircleOutlined,
  ApiOutlined, PieChartOutlined, BarChartOutlined,
  DashboardOutlined, EnvironmentOutlined, FireOutlined,
  HistoryOutlined, SendOutlined, FieldTimeOutlined, HourglassOutlined,
  DownloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import api from '../api'
import { cachedGet } from '../cache'
import { useI18n } from '../i18n'

// ========== 样式常量 ==========
const cardShadow = { boxShadow: '0 2px 12px rgba(0,0,0,0.04)', borderRadius: 12, border: '1px solid #f0f0f0' }
const chartCardStyle = { borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.04)', border: '1px solid #f0f0f0' }
const CHART_HEIGHT = 280
const COLORS = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16', '#a0d911', '#2f54eb']
const SEVERITY_COLORS: Record<string, string> = {
  Critical: '#f5222d', Major: '#ff7a45', Warning: '#faad14', Info: '#1677ff',
}
const tooltipStyle = {
  backgroundColor: 'rgba(50, 50, 50, 0.92)',
  borderColor: 'transparent',
  borderRadius: 8,
  padding: [10, 14] as [number, number],
  textStyle: { color: '#fff', fontSize: 12 },
}

// 分区标题（与 TT&WO 保持统一风格）
const SectionTitle = ({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    margin: '20px 0 14px', padding: '0 0 10px',
    borderBottom: '2px solid #f0f0f0',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 6,
      background: 'linear-gradient(135deg, #f5222d, #ff7875)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#fff', fontSize: 14,
    }}>{icon}</span>
    <span style={{ fontSize: 16, fontWeight: 700, color: '#1f1f1f', letterSpacing: '-0.3px' }}>{title}</span>
    {sub && <span style={{ fontSize: 12, color: '#999', marginLeft: 4 }}>{sub}</span>}
  </div>
)

// 顶部概览卡片
const SummaryCard = ({ icon, value, label, color, bg }: {
  icon: React.ReactNode; value: string | number; label: string; color: string; bg: string
}) => (
  <Card size="small" hoverable style={{ background: bg, border: 'none', borderRadius: 12, boxShadow: `0 4px 12px ${color}15`, cursor: 'default' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div>
        <div style={{ fontSize: 28, fontWeight: 800, color, lineHeight: 1.2 }}>{value}</div>
        <div style={{ fontSize: 12, color: color + 'cc', marginTop: 4, fontWeight: 500 }}>{label}</div>
      </div>
      <span style={{ fontSize: 38, opacity: 0.12, color }}>{icon}</span>
    </div>
  </Card>
)

// 历史告警指标卡片（可点击下钻）
const HistoryMetricCard = ({ icon, value, label, sub, color, bg, onClick }: {
  icon: React.ReactNode; value: string | number; label: string; sub: string;
  color: string; bg: string; onClick: () => void
}) => {
  const { t } = useI18n()
  return (
  <Card size="small" hoverable onClick={onClick} style={{
    background: bg, border: `1px solid ${color}25`, borderRadius: 12,
    boxShadow: `0 4px 12px ${color}12`, cursor: 'pointer', transition: 'all .2s',
  }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color, lineHeight: 1.2 }}>{value}</div>
        <div style={{ fontSize: 12, color: color + 'dd', marginTop: 3, fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: 10, color: '#999', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>
      </div>
      <span style={{ fontSize: 34, opacity: 0.15, color, flexShrink: 0 }}>{icon}</span>
    </div>
    <div style={{ textAlign: 'right', fontSize: 10, color: color, fontWeight: 600, marginTop: 2 }}>
      {t('alarm.drillHint')}
    </div>
  </Card>
  )
}

// 通用排序器（与 TT&WO Dashboard 一致）
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

// 生成列filter（与 TT&WO Dashboard 一致）
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

  // ========== 历史告警下钻状态（与 TT&WO Dashboard 一致） ==========
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillTitle, setDrillTitle] = useState('')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillMetric, setDrillMetric] = useState<string>('all')
  const [drillTotal, setDrillTotal] = useState(0)

  useEffect(() => {
    setLoading(true)
    setError(null)
    cachedGet('alarm:overview', () => api.get('/alarm-dashboard/overview'))
      .then(res => { setData(res.data); setError(null) })
      .catch(err => { console.error('Alarm Dashboard API error:', err); setError(err.message || 'Failed to load') })
      .finally(() => setLoading(false))
  }, [])

  // 打开下钻弹窗并拉取明细
  const openDrilldown = useCallback((metric: string) => {
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillMetric(metric)
    api.get('/alarm-dashboard/history-drilldown', { params: { metric, limit: 500 } })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTitle(res.data.title || 'Drilldown')
        setDrillTotal(res.data.total || 0)
      })
      .catch(err => {
        console.error('Drilldown API error:', err)
        setDrillTitle('Failed to load data')
      })
      .finally(() => setDrillLoading(false))
  }, [])

  // 模糊搜索（跨字段全文检索）
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
    const fname = `Alarm_${drillMetric}_${dayjs().format('YYYYMMDD_HHmmss')}`
    XLSX.utils.book_append_sheet(wb, ws, fname.substring(0, 31))
    XLSX.writeFile(wb, `${fname}.xlsx`)
  }, [filteredDrillData, drillMetric])

  // 下钻表格列定义（动态生成，与 TT&WO Dashboard 一致）
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
      defaultSortOrder: k === 'alarm_raised_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // ========== ECharts 图表配置 ==========

  // 持续时长分布（柱状）
  const durationOption = useMemo(() => {
    if (!data?.duration_buckets) return {}
    const order = data.duration_bucket_order || []
    const allData = order.map((b: string) => data.duration_buckets[b] || 0)
    const mainsData = order.map((b: string) => (data.mains_duration_buckets || {})[b] || 0)
    return {
      tooltip: {
        ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const title = `<div style="font-weight:600;margin-bottom:4px">${ps[0].axisValue}</div>`
          return title + ps.map((p: any) => `${p.marker} ${p.seriesName}: <strong>${p.value}</strong>`).join('<br/>')
        },
      },
      legend: { data: ['All Alarms', 'Mains Fail (MW)'], bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: 'category', data: order, axisLabel: { fontSize: 11, color: '#666' }, axisLine: { lineStyle: { color: '#d9d9d9' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } }, axisLabel: { fontSize: 10 } },
      series: [
        {
          name: 'All Alarms', type: 'bar', barMaxWidth: 24, barGap: '30%',
          data: allData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#1677ff' }, { offset: 1, color: '#69b1ff' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
        {
          name: 'Mains Fail (MW)', type: 'bar', barMaxWidth: 24,
          data: mainsData,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#f5222d' }, { offset: 1, color: '#ff7875' }] },
            borderRadius: [4, 4, 0, 0],
          },
        },
      ],
    }
  }, [data])

  // 区域告警数（柱状）
  const regionOption = useMemo(() => {
    if (!data?.region_alarm_count) return {}
    const entries = Object.entries(data.region_alarm_count).filter(([, v]) => (v as number) > 0).sort((a: any, b: any) => b[1] - a[1])
    if (!entries.length) return {}
    // 附加上 mains 数据和受影响站点数
    const mainsData = entries.map(([k]) => (data.region_mains_count || {})[k] || 0)
    const siteData = entries.map(([k]) => (data.region_sites_count || {})[k] || 0)
    return {
      tooltip: {
        ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const region = entries[idx][0]
          const alarmVal = entries[idx][1]
          const siteVal = siteData[idx]
          const mainsVal = mainsData[idx]
          return `<div style="font-weight:600;margin-bottom:4px">${region}</div>` +
            `Alarms: <strong>${alarmVal}</strong><br/>Affected Sites: <strong>${siteVal}</strong><br/>Mains Fail: <strong>${mainsVal}</strong>`
        },
      },
      grid: { left: 40, right: 20, top: 10, bottom: 40 },
      xAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { fontSize: 11, fontWeight: 500, color: '#333' }, axisLine: { lineStyle: { color: '#d9d9d9' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } }, axisLabel: { fontSize: 10 } },
      series: [{
        type: 'bar', barMaxWidth: 28,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: COLORS[i % COLORS.length] }, { offset: 1, color: COLORS[(i + 1) % COLORS.length] }] },
            borderRadius: [4, 4, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 10, color: '#666', fontWeight: 600 },
      }],
    }
  }, [data])

  // 各技术制式饼图
  const techPieOption = useMemo(() => {
    if (!data?.logical_total) return {}
    const entries = Object.entries(data.logical_total).filter(([t]) => t !== 'OTHER')
    const totalCells = entries.reduce((s, [, v]: any) => s + v.cell, 0)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} alarms ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['38%', '65%'], center: ['35%', '50%'],
        data: entries.map(([tech, val]: any, i: number) => ({
          name: tech,
          value: val.cell,
          itemStyle: { color: COLORS[i % COLORS.length] },
        })),
        label: { fontSize: 10, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
      }],
    }
  }, [data?.logical_total])

  // 告警类型 Top（横向柱状）
  const alarmTypeOption = useMemo(() => {
    if (!data?.alarm_type_top) return {}
    const entries = Object.entries(data.alarm_type_top).sort((a: any, b: any) => b[1] - a[1]).slice(0, 8)
    const labels = entries.map(([k]) => k.length > 28 ? k.substring(0, 26) + '...' : k)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 20, right: 80, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } }, axisLabel: { fontSize: 10 } },
      yAxis: { type: 'category', data: labels.reverse(), axisLabel: { fontSize: 10, color: '#333' } },
      series: [{
        type: 'bar', barMaxWidth: 20,
        data: entries.map(([, v], i) => ({
          value: v,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#f5222d' }, { offset: 1, color: '#ff7875' }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: '#666', formatter: (p: any) => p.value.toLocaleString() },
      }],
    }
  }, [data?.alarm_type_top])

  // 严重等级饼图
  const sevPieOption = useMemo(() => {
    if (!data?.severity_stats) return {}
    const entries = Object.entries(data.severity_stats)
    const colorMap = (name: string) => SEVERITY_COLORS[name] || COLORS[Object.keys(data.severity_stats).indexOf(name) % COLORS.length]
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['32%', '62%'], center: ['50%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: colorMap(k) } })),
        label: { fontSize: 11, formatter: '{b}\n{d}%', color: '#333' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
      }],
    }
  }, [data?.severity_stats])

  // 网络类型饼图
  const netTypeOption = useMemo(() => {
    if (!data?.networktype) return {}
    const entries = Object.entries(data.networktype)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v], i) => ({ name: k, value: v, itemStyle: { color: COLORS[i % COLORS.length] } })),
        label: { fontSize: 9, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.networktype])

  // 站点属性饼图
  const siteAttrOption = useMemo(() => {
    if (!data?.site_attribute) return {}
    const entries = Object.entries(data.site_attribute)
    const attrColors: Record<string, string> = { REGULAR: '#52c41a', ERA: '#722ed1', '--': '#d9d9d9' }
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map(([k, v]) => ({ name: k, value: v, itemStyle: { color: attrColors[k] || COLORS[0] } })),
        label: { fontSize: 9, formatter: '{b}\n{d}%' },
      }],
    }
  }, [data?.site_attribute])

  // ========== 渲染 ==========
  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60 }}>
      <Spin size="large" />
      <div style={{ marginTop: 12, color: '#999' }}>Loading Alarm Dashboard...</div>
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* ====== 1. 头部警报横幅 ====== */}
      <Card size="small" style={{
        ...cardShadow,
        background: 'linear-gradient(135deg, #fff1f0 0%, #fff7f7 100%)',
        borderLeft: '4px solid #f5222d',
        marginBottom: 4,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FireOutlined style={{ fontSize: 22, color: '#f5222d' }} />
            <span style={{ fontSize: 15, fontWeight: 700, color: '#cf1322' }}>
              Real-time Alarm Status
            </span>
            <Tag color="red" style={{ borderRadius: 12, fontWeight: 600 }}>{fmt(data.total_alarms)} Active Alarms</Tag>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#999' }}>
            <ClockCircleOutlined />
            <span>Updated: {data.generated_at}</span>
          </div>
        </div>
      </Card>

      {/* ====== 2. 核心指标卡片 ====== */}
      <Row gutter={[12, 12]}>
        <Col span={6}>
          <SummaryCard
            icon={<AlertOutlined />}
            value={fmt(data.total_alarms)}
            label="Total Active Alarms"
            color="#f5222d"
            bg="linear-gradient(135deg, #fff1f0 0%, #fff7f7 100%)" />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<EnvironmentOutlined />}
            value={fmt(data.affected_sites)}
            label="Affected Sites"
            color="#fa8c16"
            bg="linear-gradient(135deg, #fff7e6 0%, #fffbe6 100%)" />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<ClockCircleOutlined />}
            value={fmt(data.total_alarm_hours)}
            label="Total Alarm Hours"
            color="#722ed1"
            bg="linear-gradient(135deg, #f9f0ff 0%, #efdbff 100%)" />
        </Col>
        <Col span={6}>
          <SummaryCard
            icon={<WarningOutlined />}
            value={fmt(sevStats.Critical || 0)}
            label="Critical Alerts"
            color="#f5222d"
            bg="linear-gradient(135deg, #fff1f0 0%, #fff7f7 100%)" />
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
            color="#1677ff"
            bg="linear-gradient(135deg, #e6f4ff 0%, #f0f8ff 100%)"
            onClick={() => openDrilldown('all')} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<SendOutlined />}
            value={fmt(hist.dispatch_delay_eflow || 0)}
            label="Dispatch Delay (Eflow)"
            sub="Assigned - Server > Assign Delay +10%"
            color="#fa8c16"
            bg="linear-gradient(135deg, #fff7e6 0%, #fffbe6 100%)"
            onClick={() => openDrilldown('dispatch_delay_eflow')} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<FieldTimeOutlined />}
            value={fmt(hist.alarm_fetch_delay || 0)}
            label="Alarm Fetch Delay"
            sub="Server - AlarmRaised > 5 min"
            color="#722ed1"
            bg="linear-gradient(135deg, #f9f0ff 0%, #efdbff 100%)"
            onClick={() => openDrilldown('alarm_fetch_delay')} />
        </Col>
        <Col span={6}>
          <HistoryMetricCard
            icon={<HourglassOutlined />}
            value={fmt(hist.dispatch_overdue_total || 0)}
            label="Dispatch Overdue Total"
            sub={t('alarm.overdueDesc')}
            color="#f5222d"
            bg="linear-gradient(135deg, #fff1f0 0%, #fff7f7 100%)"
            onClick={() => openDrilldown('dispatch_overdue_total')} />
        </Col>
      </Row>

      {/* ====== 3. 技术制式 + 严重等级 + 网络类型 ====== */}
      <SectionTitle icon={<ApiOutlined />} title="Alarm Breakdown" sub="by Technology, Severity & Network Type" />
      <Row gutter={[12, 12]}>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Technology Distribution</span>} style={chartCardStyle}>
            <ReactECharts option={techPieOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Severity Distribution</span>} style={chartCardStyle}>
            <ReactECharts option={sevPieOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Network Type</span>} style={chartCardStyle}>
            <ReactECharts option={netTypeOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
      </Row>

      {/* ====== 4. 技术制式详细卡片 ====== */}
      <Row gutter={[12, 12]} style={{ marginTop: 4 }}>
        {Object.entries(logical_total || {})
          .filter(([tech]) => tech !== 'OTHER')
          .map(([tech, val]: any, idx: number) => (
            <Col span={6} key={tech}>
              <Card size="small" hoverable style={{
                background: `linear-gradient(135deg, ${COLORS[idx % COLORS.length]}08, #ffffff)`,
                borderRadius: 12, border: `1px solid ${COLORS[idx % COLORS.length]}22`,
                cursor: 'default',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: COLORS[idx % COLORS.length],
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#fff', fontSize: 16, fontWeight: 700,
                  }}>{tech}</div>
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: COLORS[idx % COLORS.length], lineHeight: 1.2 }}>{fmt(val.site || 0)}</div>
                    <div style={{ fontSize: 11, color: '#999' }}>Sites · {fmt(val.cell || 0)} Cells</div>
                  </div>
                </div>
              </Card>
            </Col>
          ))}
      </Row>

      {/* ====== 5. 持续时长分布 + 区域告警分布 ====== */}
      <SectionTitle icon={<BarChartOutlined />} title="Duration & Regional Distribution" sub="alarm persistence & geographic spread" />
      <Row gutter={[12, 12]}>
        <Col span={12}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Alarm Duration Distribution</span>} style={chartCardStyle}>
            <ReactECharts option={durationOption} style={{ height: CHART_HEIGHT + 30 }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Alarms by Region</span>} style={chartCardStyle}>
            <ReactECharts option={regionOption} style={{ height: CHART_HEIGHT + 30 }} />
          </Card>
        </Col>
      </Row>

      {/* ====== 6. 告警类型 Top + 站点属性 ====== */}
      <SectionTitle icon={<PieChartOutlined />} title="Alarm Type & Site Attribute" sub="most frequent alarm types & site classification" />
      <Row gutter={[12, 12]}>
        <Col span={14}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Top Alarm Types</span>} style={chartCardStyle}>
            <ReactECharts option={alarmTypeOption} style={{ height: CHART_HEIGHT + 40 }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Site Attribute</span>} style={chartCardStyle}>
            <ReactECharts option={siteAttrOption} style={{ height: CHART_HEIGHT }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 600 }}>Severity Tags</span>} style={chartCardStyle}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 0' }}>
              {Object.entries(sevStats).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Tag color={SEVERITY_COLORS[k] || '#999'} style={{ borderRadius: 12, fontWeight: 500 }}>{k}</Tag>
                  <span style={{ fontSize: 18, fontWeight: 700, color: SEVERITY_COLORS[k] || '#333' }}>{fmt(v as number)}</span>
                </div>
              ))}
              <div style={{ marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Tag color="#1677ff" style={{ borderRadius: 12, fontWeight: 500 }}>Total</Tag>
                  <span style={{ fontSize: 18, fontWeight: 700, color: '#1677ff' }}>{fmt(data.total_alarms)}</span>
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* ====== 7. 各区域 Top 告警类型（表格风格） ====== */}
      {data.region_alarm_type && Object.keys(data.region_alarm_type).length > 0 && (
        <>
          <SectionTitle icon={<DashboardOutlined />} title="Regional Alarm Profile" sub="top alarm types per region" />
          <Card size="small" style={chartCardStyle}>
            <Row gutter={[8, 8]}>
              {Object.entries(data.region_alarm_type)
                .filter(([, v]: any) => Object.keys(v).length > 0)
                .slice(0, 10)
                .map(([region, types]: any) => (
                  <Col span={6} key={region} style={{ marginBottom: 8 }}>
                    <div style={{
                      background: '#fafafa', borderRadius: 8, padding: '10px 12px',
                      borderLeft: '3px solid #f5222d',
                    }}>
                      <div style={{ fontWeight: 700, fontSize: 13, color: '#1f1f1f', marginBottom: 6 }}>
                        <Tag color="red" style={{ borderRadius: 8, marginRight: 6 }}>{region}</Tag>
                        <span style={{ fontSize: 11, color: '#999' }}>{data.region_alarm_count[region]} alarms</span>
                      </div>
                      {Object.entries(types).map(([type, count]: any, i: number) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0', color: '#555' }}>
                          <Tooltip title={type}>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 130 }}>
                              {type.length > 22 ? type.substring(0, 20) + '..' : type}
                            </span>
                          </Tooltip>
                          <span style={{ fontWeight: 600, color: '#f5222d' }}>{count}</span>
                        </div>
                      ))}
                    </div>
                  </Col>
                ))}
            </Row>
          </Card>
        </>
      )}

      {/* ====== 历史告警下钻弹窗（与 TT&WO Dashboard 一致） ====== */}
      <Modal
        title={<span>{drillTitle} <Tag color="blue">{filteredDrillData.length} records</Tag>{drillTotal > drillData.length && <Tag color="red">{t('alarm.recordCount', { total: fmt(drillTotal), shown: drillData.length })}</Tag>}</span>}
        open={drillOpen}
        onCancel={() => setDrillOpen(false)}
        footer={null}
        width="92%"
        style={{ maxWidth: 1400 }}
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
            rowKey={(r: any, i?: number) => `${Object.values(r).slice(0, 3).join('-')}-${i}`}
            pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => `${total} items` }}
            scroll={{ x: 'max-content' }}
          />
        )}
      </Modal>
    </div>
  )
}
