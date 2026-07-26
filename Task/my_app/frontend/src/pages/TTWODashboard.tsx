// TT&WO Dashboard 前端页面 - 下钻版
import { useEffect, useState, useMemo, useCallback } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Segmented, DatePicker, Space, Tag, Tooltip, Statistic, Empty, Spin, Alert, Modal, Table, Input, Button } from 'antd'
import {
  ThunderboltOutlined, FileTextOutlined, NumberOutlined, ClockCircleOutlined,
  AlertOutlined, TagsOutlined, BarChartOutlined,
  PieChartOutlined, EnvironmentOutlined, TeamOutlined,
  DownloadOutlined, SearchOutlined
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { useDataTimestamps } from '../useDataTimestamps'

const { RangePicker } = DatePicker

const COLORS = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16', '#a0d911', '#2f54eb']

// 统一 tooltip 样式
const tooltipStyle = {
  backgroundColor: 'rgba(50, 50, 50, 0.92)',
  borderColor: 'transparent',
  borderRadius: 8,
  padding: [10, 14],
  textStyle: { color: '#fff', fontSize: 12 },
}

// ========== 全局样式常量 ==========
// 统一色谱常量
const SEVERITY_COLORS = {
  critical: '#ff4d4f',  // 深红
  major: '#ff7a45',     // 橙
  medium: '#ffc53d',    // 黄
  minor: '#73d13d',     // 绿
  info: '#40a9ff',      // 蓝
}
// 卡片通用样式
const cardShadow = { boxShadow: '0 2px 12px rgba(0,0,0,0.04)', borderRadius: 12, border: '1px solid #f0f0f0' }
// 图表卡片样式
const chartCardStyle = { borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.04)', border: '1px solid #f0f0f0' }
// 图表统一高度
const CHART_HEIGHT = 300
// 卡片标题样式
const cardTitleStyle = { fontSize: 14, fontWeight: 600, color: '#374151' } as const

// 分区标题样式（升级版：图标在渐变方块内 + 底部实线）
const SectionTitle = ({ icon, title }: { icon: React.ReactNode; title: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    margin: '28px 0 16px', padding: '0 0 10px',
    borderBottom: '2px solid #f0f0f0',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 6,
      background: 'linear-gradient(135deg, #1677ff, #4096ff)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#fff', fontSize: 14,
    }}>{icon}</span>
    <span style={{ fontSize: 16, fontWeight: 700, color: '#1f1f1f', letterSpacing: '-0.3px' }}>{title}</span>
  </div>
)

// 通用排序器
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

// 生成列filter
const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

export default function TTWODashboard() {
  const { t } = useI18n()
  const { lastSync, isSynced } = useDataTimestamps()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [timePreset, setTimePreset] = useState<string>('last7')
  const [customRange, setCustomRange] = useState<any>(null)
  const [selectedRegion, setSelectedRegion] = useState<string | undefined>(undefined)

  // 下钻状态
  const [drillVisible, setDrillVisible] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillTitle, setDrillTitle] = useState('')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillDimension, setDrillDimension] = useState('')
  const [drillValue, setDrillValue] = useState('')

  // 时间范围计算
  const timeRange = useMemo(() => {
    if (timePreset === 'all') return null
    if (timePreset === 'custom' && customRange) {
      return {
        start: customRange[0].format('YYYY-MM-DD'),
        end: customRange[1].format('YYYY-MM-DD'),
      }
    }
    const end = new Date()
    const start = new Date()
    const days: Record<string, number> = { last7: 7, last30: 30, last90: 90, last180: 180 }
    start.setDate(start.getDate() - (days[timePreset] || 7))
    return {
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
    }
  }, [timePreset, customRange])

  // 加载数据（切页复用缓存，30s 内不重复请求）
  useEffect(() => {
    setLoading(true)
    setError(null)
    const params: Record<string, string> = {}
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }
    if (selectedRegion) params.region = selectedRegion
    const cacheKey = `ttwo:overview:${timeRange?.start || ''}:${timeRange?.end || ''}:${selectedRegion || ''}`
    cachedGet(cacheKey, () => api.get('/tt-wo-dashboard/overview', { params }))
      .then(res => {
        setData(res.data)
        setError(null)
      })
      .catch(err => {
        console.error('TT&WO Dashboard API error:', err)
        setError(err.message || 'API request failed')
      })
      .finally(() => setLoading(false))
  }, [timeRange, selectedRegion])

  const fmt = (n: number) => n?.toLocaleString() || '0'

  // ========== 下钻功能 ==========
  const openDrilldown = useCallback((dimension: string, value?: string) => {
    setDrillVisible(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillDimension(dimension)
    setDrillValue(value || '')
    const params: Record<string, string> = { dimension }
    if (value) params.value = value
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }
    if (selectedRegion) params.region = selectedRegion
    api.get('/tt-wo-dashboard/drilldown', { params })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTitle(res.data.title || 'Drilldown')
      })
      .catch(() => {
        setDrillTitle('Failed to load data')
      })
      .finally(() => setDrillLoading(false))
  }, [timeRange, selectedRegion])

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
    const fname = `TTWO_${drillDimension}_${drillValue || 'all'}_${dayjs().format('YYYYMMDD_HHmmss')}`
    XLSX.utils.book_append_sheet(wb, ws, fname.substring(0, 31))
    XLSX.writeFile(wb, `${fname}.xlsx`)
  }, [filteredDrillData, drillDimension, drillValue])

  // 下钻表格列定义 (动态生成)
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
      defaultSortOrder: k === 'alarm_occur_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // ========== 图表配置 ==========

  // MTTR周趋势 (折线+柱状)
  const mttrOption = useMemo(() => {
    if (!data?.mttr_weekly?.length) return {}
    const weeks = data.mttr_weekly.map((w: any) => w.week)
    const mttrs = data.mttr_weekly.map((w: any) => w.mttr)
    const counts = data.mttr_weekly.map((w: any) => w.count)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'cross', crossStyle: { color: '#999' } } },
      legend: { data: ['TT Count', 'MTTR (min)'], bottom: 5, textStyle: { fontSize: 11 } },
      grid: { left: 60, right: 60, top: 30, bottom: 55 },
      xAxis: { type: 'category', data: weeks, axisLabel: { rotate: 45, fontSize: 10, color: '#666' }, axisLine: { lineStyle: { color: '#d9d9d9' } } },
      yAxis: [
        { type: 'value', name: 'TT Count', position: 'left', nameTextStyle: { color: '#1677ff', fontSize: 11 }, axisLabel: { color: '#1677ff' }, splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
        { type: 'value', name: 'MTTR (min)', position: 'right', nameTextStyle: { color: '#f5222d', fontSize: 11 }, axisLabel: { color: '#f5222d' }, splitLine: { show: false } },
      ],
      series: [
        {
          name: 'TT Count', type: 'bar', data: counts, yAxisIndex: 0, barMaxWidth: 28,
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#1677ff' }, { offset: 1, color: '#69b1ff' }] }, borderRadius: [4, 4, 0, 0] },
        },
        {
          name: 'MTTR (min)', type: 'line', data: mttrs, yAxisIndex: 1, smooth: true,
          itemStyle: { color: '#f5222d' }, lineStyle: { width: 2.5 }, symbol: 'circle', symbolSize: 6,
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(245,34,45,0.15)' }, { offset: 1, color: 'rgba(245,34,45,0.01)' }] } },
        },
      ],
    }
  }, [data?.mttr_weekly])

  // Domain分布
  const domainOption = useMemo(() => {
    if (!data?.domain_stats) return {}
    const entries = Object.entries(data.domain_stats).sort((a: any, b: any) => a[1] - b[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 90, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 11, color: '#333' } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any, i: number) => ({
          value: e[1],
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: COLORS[i % COLORS.length] }, { offset: 1, color: COLORS[(i + 1) % COLORS.length] }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: '#666', formatter: (p: any) => p.value.toLocaleString() },
      }],
    }
  }, [data?.domain_stats])

  // 通用饼图配置生成
  const makePieOption = (entries: [string, any][], hasLegend = true) => ({
    tooltip: { ...tooltipStyle, trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
    legend: hasLegend ? { orient: 'vertical' as const, right: 0, top: 'center', textStyle: { fontSize: 10 }, itemWidth: 10, itemHeight: 10 } : undefined,
    series: [{
      type: 'pie', radius: ['35%', '65%'], center: ['35%', '50%'],
      data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: COLORS[i % COLORS.length] } })),
      label: { fontSize: 10, formatter: '{b}\n{d}%' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 2, shadowColor: 'rgba(0,0,0,0.2)' } },
    }],
  })

  // Root Cause 主因饼图
  const rcMainOption = useMemo(() => {
    if (!data?.root_cause?.main) return {}
    const entries = Object.entries(data.root_cause.main).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.main])

  // Sub Root Cause 饼图
  const rcSubOption = useMemo(() => {
    if (!data?.root_cause?.sub) return {}
    const entries = Object.entries(data.root_cause.sub).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.sub])

  // WO Source 柱状图
  const woSourceOption = useMemo(() => {
    if (!data?.wo_stats?.source) return {}
    const entries = Object.entries(data.wo_stats.source).sort((a: any, b: any) => b[1] - a[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 80, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { color: '#333' } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#52c41a' }, { offset: 1, color: '#95de64' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: '#666', formatter: (p: any) => p.value.toLocaleString() },
      }],
    }
  }, [data?.wo_stats?.source])

  // WO Status 柱状图
  const woStatusOption = useMemo(() => {
    if (!data?.wo_stats?.status) return {}
    const entries = Object.entries(data.wo_stats.status).sort((a: any, b: any) => b[1] - a[1])
    const statusColors: Record<string, string[]> = {
      Closed: ['#52c41a', '#95de64'], Open: ['#1677ff', '#69b1ff'], 'In Progress': ['#faad14', '#ffd666'],
      Pending: ['#fa8c16', '#ffc069'], Cancelled: ['#d9d9d9', '#f0f0f0'],
    }
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 140, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 10, color: '#333' } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => {
          const colors = statusColors[e[0]] || ['#faad14', '#ffd666']
          return {
            value: e[1],
            itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: colors[0] }, { offset: 1, color: colors[1] }] }, borderRadius: [0, 4, 4, 0] },
          }
        }),
        label: { show: true, position: 'right', fontSize: 10, color: '#666', formatter: (p: any) => p.value.toLocaleString() },
      }],
    }
  }, [data?.wo_stats?.status])

  // Power Sources 饼图
  const powerSourceOption = useMemo(() => {
    if (!data?.site_stats?.power_sources) return {}
    const entries = Object.entries(data.site_stats.power_sources).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 9 }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: COLORS[i % COLORS.length] } })),
        label: { fontSize: 9, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
      }],
    }
  }, [data?.site_stats?.power_sources])

  // Maintenance Team 柱状图
  const fmeOption = useMemo(() => {
    if (!data?.site_stats?.maintenance_team) return {}
    const entries = Object.entries(data.site_stats.maintenance_team).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 130, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 9, color: '#333' } },
      series: [{
        type: 'bar', barMaxWidth: 18,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#722ed1' }, { offset: 1, color: '#b37feb' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 9, color: '#666' },
      }],
    }
  }, [data?.site_stats?.maintenance_team])

  // Power Vendor 饼图
  const powerVendorOption = useMemo(() => {
    if (!data?.site_stats?.power_vendor) return {}
    const entries = Object.entries(data.site_stats.power_vendor)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['35%', '65%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: COLORS[i % COLORS.length] } })),
        label: { fontSize: 11, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
      }],
    }
  }, [data?.site_stats?.power_vendor])

  // 统计卡片颜色映射（基于统一色谱 SEVERITY_COLORS）
  const sevColor: Record<string, string> = {
    Critical: SEVERITY_COLORS.critical, Major: SEVERITY_COLORS.major, Medium: SEVERITY_COLORS.medium, Minor: SEVERITY_COLORS.minor,
    'Proactive Fault': SEVERITY_COLORS.info, 'Incident Fault': SEVERITY_COLORS.major, 'Custom Complain': '#eb2f96',
    Unknown: '#d9d9d9'
  }
  const ticketColor: Record<string, string> = {
    P1: SEVERITY_COLORS.critical, P2: SEVERITY_COLORS.major, P3: SEVERITY_COLORS.info, P4: SEVERITY_COLORS.minor,
    'Critical(4H)': SEVERITY_COLORS.critical, 'Major(24H)': SEVERITY_COLORS.major, 'Warning': SEVERITY_COLORS.medium, 'Minor(72H)': SEVERITY_COLORS.minor,
    Unknown: '#d9d9d9'
  }
  const slaColor: Record<string, string> = { Pass: '#52c41a', Failed: '#f5222d', 'Within SLA': '#1677ff', Unknown: '#d9d9d9' }
  // 自动调色板：当colorMap没有匹配时自动分配颜色
  const autoPalette = ['#1677ff', '#52c41a', '#fa8c16', '#eb2f96', '#722ed1', '#13c2c2', '#faad14', '#f5222d']
  const autoColorCache: Record<string, string> = {}
  const getAutoColor = (key: string, idx: number) => {
    if (!autoColorCache[key]) autoColorCache[key] = autoPalette[idx % autoPalette.length]
    return autoColorCache[key]
  }

  // 可点击的统计标签（升级：统一尺寸 + hover效果）
  const renderStatTags = (stats: Record<string, number>, colorMap: Record<string, string>, dimension: string) => (
    <Space wrap size={[8, 8]}>
      {Object.entries(stats).map(([k, v], idx) => (
        <Tag key={k} color={colorMap[k] || getAutoColor(k, idx)}
          style={{ borderRadius: 16, padding: '4px 14px', fontSize: 13, lineHeight: '24px', cursor: 'pointer', transition: 'all 0.2s', fontWeight: 500 }}
          onClick={() => openDrilldown(dimension, k)}
        >
          {k}: <strong style={{ fontSize: 14 }}>{fmt(v)}</strong>
        </Tag>
      ))}
    </Space>
  )

  // Status 颜色编码（语义化固定色）
  const getStatusColor = (key: string): string => {
    const lower = key.toLowerCase()
    if (lower.includes('closed') || lower.includes('complete')) return '#52c41a'
    if (lower.includes('open') || lower.includes('in progress')) return '#1677ff'
    if (lower.includes('waiting') || lower.includes('pending')) return '#fa8c16'
    if (lower.includes('cancel') || lower.includes('reject')) return '#8c8c8c'
    return '#13c2c2'
  }

  // Status 长标签缩写
  const shortenLabel = (key: string): string => {
    const map: Record<string, string> = {
      'Waiting for FO Process(WO RCA to FO Confirm)': 'Wait FO (RCA Confirm)',
      'Waiting for FO Process(WO Reject to FO Confirm)': 'Wait FO (Reject Confirm)',
      'Waiting for FO Process': 'Wait FO Process',
      'Waiting for Third Accept': 'Wait Third Accept',
      'Waiting for Customer Confirm': 'Wait Customer Confirm',
    }
    return map[key] || key
  }

  // 渲染 Status 标签（带圆点指示器 + Tooltip + 点击下钻）
  const renderStatusTags = (stats: Record<string, number>) => {
    const sorted = Object.entries(stats).sort((a, b) => (b[1] as number) - (a[1] as number))
    return (
      <div style={{ background: '#fafafa', borderRadius: 8, padding: 12 }}>
        <Space wrap size={[10, 10]}>
          {sorted.map(([k, v]) => (
            <Tooltip key={k} title={`Click to drill down: ${k}`}>
              <Tag
                style={{ borderRadius: 16, padding: '5px 14px', fontSize: 13, lineHeight: '24px', margin: 0, cursor: 'pointer', transition: 'all 0.2s', border: 'none', background: `${getStatusColor(k)}14`, color: getStatusColor(k), fontWeight: 500 }}
                onClick={() => openDrilldown('status', k)}
              >
                <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: getStatusColor(k), marginRight: 6 }} />
                {shortenLabel(k)}: <strong style={{ fontSize: 14 }}>{fmt(v as number)}</strong>
              </Tag>
            </Tooltip>
          ))}
        </Space>
      </div>
    )
  }

  // 图表点击事件
  const onChartClick = (dimension: string) => ({
    click: (params: any) => {
      const name = params.name || params.data?.name
      if (name) openDrilldown(dimension, name)
    }
  })

  if (loading) return (
    <div style={{ textAlign: 'center', padding: 100 }}>
      <Spin size="large" />
      <div style={{ marginTop: 16, color: '#999' }}>Loading TT&WO data...</div>
    </div>
  )

  if (error) return (
    <div style={{ padding: 24 }}>
      <Alert type="error" message="Failed to load TT&WO Dashboard data" description={error} showIcon />
    </div>
  )

  if (!data) return <Empty description="No data returned" />

  const regions = data.filters?.regions || []
  const s = data.tt_stats || {}
    // 自适应: 使用 alarm_severity 或 category（取决于数据库结构）
    const sevStats = (s.alarm_severity && Object.keys(s.alarm_severity).length > 0) ? s.alarm_severity : (s.category || {})
    const sevDimension = (s.alarm_severity && Object.keys(s.alarm_severity).length > 0) ? 'alarm_severity' : 'category'
    const sevLabel = sevDimension === 'alarm_severity' ? 'Alarm Severity' : 'Category'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 筛选栏 */}
      <Card size="small" style={{ ...cardShadow, background: 'linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)', marginBottom: 4 }}>
        <Space wrap align="center" size="middle">
          <Segmented
            options={[
              { label: 'All Time', value: 'all' },
              { label: 'Last 7 days', value: 'last7' },
              { label: 'Last 30 days', value: 'last30' },
              { label: 'Last 3 months', value: 'last90' },
              { label: 'Last 6 months', value: 'last180' },
              { label: 'Custom', value: 'custom' },
            ]}
            value={timePreset}
            onChange={setTimePreset}
          />
          {timePreset === 'custom' && (
            <RangePicker value={customRange} onChange={setCustomRange} />
          )}
          <Select
            value={selectedRegion}
            onChange={setSelectedRegion}
            style={{ width: 180 }}
            allowClear
            placeholder="All Regions"
            options={regions.map((r: string) => ({ value: r, label: r }))}
          />
          <Tag
            icon={<ClockCircleOutlined />}
            color={isSynced ? 'green' : 'red'}
            style={{ marginLeft: 'auto', borderRadius: 12, padding: '2px 12px' }}
          >
            {isSynced ? `Synced: ${lastSync}` : 'Not synced'}
          </Tag>
        </Space>
      </Card>

      {/* 汇总卡片 - 渐变背景 + 图标水印 */}
      <Row gutter={16}>
        <Col span={data.summary.wo_total > 0 ? 8 : 24}>
          <Card size="small" hoverable style={{ background: 'linear-gradient(135deg, #e6f4ff 0%, #f0f5ff 100%)', border: 'none', borderRadius: 12, boxShadow: '0 4px 12px rgba(22,119,255,0.08)', cursor: 'pointer' }}
            onClick={() => openDrilldown('all_tt')}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Statistic title={<span style={{ color: '#5b8dd9' }}>TT Total</span>} value={data.summary.tt_total} valueStyle={{ fontSize: 32, fontWeight: 800, color: '#1677ff' }} />
              <ThunderboltOutlined style={{ fontSize: 42, opacity: 0.12, color: '#1677ff' }} />
            </div>
          </Card>
        </Col>
        {data.summary.wo_total > 0 && <Col span={8}>
          <Card size="small" hoverable style={{ background: 'linear-gradient(135deg, #f6ffed 0%, #fcffe6 100%)', border: 'none', borderRadius: 12, boxShadow: '0 4px 12px rgba(82,196,26,0.08)', cursor: 'pointer' }}
            onClick={() => openDrilldown('all_wo')}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Statistic title={<span style={{ color: '#7ab648' }}>WO Total</span>} value={data.summary.wo_total} valueStyle={{ fontSize: 32, fontWeight: 800, color: '#52c41a' }} />
              <FileTextOutlined style={{ fontSize: 42, opacity: 0.12, color: '#52c41a' }} />
            </div>
          </Card>
        </Col>}
        {data.summary.wo_total > 0 && <Col span={8}>
          <Card size="small" hoverable style={{ background: 'linear-gradient(135deg, #f9f0ff 0%, #efdbff 100%)', border: 'none', borderRadius: 12, boxShadow: '0 4px 12px rgba(114,46,209,0.08)', cursor: 'pointer' }}
            onClick={() => openDrilldown('all_wo')}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Statistic title={<span style={{ color: '#9254de' }}>WO No. (Unique)</span>} value={data.summary.wo_no_count} valueStyle={{ fontSize: 32, fontWeight: 800, color: '#722ed1' }} />
              <NumberOutlined style={{ fontSize: 42, opacity: 0.12, color: '#722ed1' }} />
            </div>
          </Card>
        </Col>}
      </Row>

      {/* TT 统计标签 */}
      <SectionTitle icon={<AlertOutlined />} title="TT Statistics" />
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>{sevLabel}</span>} style={cardShadow} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(sevStats, sevColor, sevDimension)}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>Ticket Severity</span>} style={cardShadow} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(s.ticket_severity, ticketColor, 'ticket_severity')}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>SLA Status</span>} style={cardShadow} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(s.sla_status, slaColor, 'sla_status')}
          </Card>
        </Col>
      </Row>
      <Card size="small" title={<span style={cardTitleStyle}>Status</span>} style={cardShadow}>
        {renderStatusTags(s.status || {})}
      </Card>

      {/* MTTR 周趋势 */}
      <SectionTitle icon={<BarChartOutlined />} title="MTTR Weekly Trend" />
      <Card size="small" style={chartCardStyle}>
        <ReactECharts option={mttrOption} style={{ height: CHART_HEIGHT }}
          onEvents={onChartClick('week')} />
      </Card>

      {/* Domain + Root Cause */}
      <SectionTitle icon={<PieChartOutlined />} title="Domain & Root Cause Analysis" />
      <Row gutter={[16, 16]}>
        <Col span={10}>
          <Card title={<span style={cardTitleStyle}>TT by Domain</span>} size="small" style={chartCardStyle}>
            <ReactECharts option={domainOption} style={{ height: CHART_HEIGHT }}
              onEvents={onChartClick('domain')} />
          </Card>
        </Col>
        <Col span={7}>
          <Card title={<span style={cardTitleStyle}>Root Cause (Main)</span>} size="small" style={chartCardStyle}>
            <ReactECharts option={rcMainOption} style={{ height: CHART_HEIGHT }}
              onEvents={onChartClick('rc_main')} />
          </Card>
        </Col>
        <Col span={7}>
          <Card title={<span style={cardTitleStyle}>Root Cause (Sub)</span>} size="small" style={chartCardStyle}>
            <ReactECharts option={rcSubOption} style={{ height: CHART_HEIGHT }}
              onEvents={onChartClick('rc_sub')} />
          </Card>
        </Col>
      </Row>

      {/* WO Source + Status（仅当WO数据存在时显示）*/}
      {data.summary.wo_total > 0 && <>
        <SectionTitle icon={<TagsOutlined />} title="Work Order Analytics" />
        <Row gutter={[16, 16]}>
          <Col span={12}>
            <Card title={<span style={cardTitleStyle}>WO by Source</span>} size="small" style={chartCardStyle}>
              <ReactECharts option={woSourceOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('wo_source')} />
            </Card>
          </Col>
          <Col span={12}>
            <Card title={<span style={cardTitleStyle}>WO by Status</span>} size="small" style={chartCardStyle}>
              <ReactECharts option={woStatusOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('wo_status')} />
            </Card>
          </Col>
        </Row>
      </>}

      {/* 站点信息（自适应：显示数据库中存在的站点统计字段）*/}
      <SectionTitle icon={<EnvironmentOutlined />} title="Site Information" />
      <Row gutter={[16, 16]}>
        {Object.entries(data.site_stats || {}).filter(([, v]) => v && Object.keys(v as any).length > 0).map(([key, stats]) => (
          <Col span={8} key={key}>
            <Card title={<span style={cardTitleStyle}>{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>} size="small" style={chartCardStyle}>
              <ReactECharts option={{
                tooltip: { ...tooltipStyle, trigger: 'axis' },
                grid: { left: 100, right: 30, top: 10, bottom: 10 },
                xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f0f0f0' } } },
                yAxis: { type: 'category', data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map(e => e[0]), axisLabel: { fontSize: 9, color: '#333' } },
                series: [{ type: 'bar', barMaxWidth: 18, data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map((e: any) => ({ value: e[1], itemStyle: { color: COLORS[0], borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: 'right', fontSize: 9, color: '#666' } }],
              }} style={{ height: CHART_HEIGHT }} onEvents={onChartClick(key)} />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 下钻 Modal */}
      <Modal
        title={<span>{drillTitle} <Tag color="blue">{filteredDrillData.length} records</Tag></span>}
        open={drillVisible}
        onCancel={() => setDrillVisible(false)}
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
