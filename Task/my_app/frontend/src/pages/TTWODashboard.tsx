// TT&WO Dashboard 前端页面 - Warehouse 暗色科技风
import { useEffect, useState, useMemo, useCallback } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Segmented, DatePicker, Space, Tag, Tooltip, Statistic, Empty, Spin, Alert, Table, Input, Button } from 'antd'
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
import { useI18n, numLocale } from '../i18n'
import { useDataTimestamps } from '../useDataTimestamps'
import DraggableClickModal from '../components/DraggableClickModal'
import { ExplainIcon } from '../components/MetricExplain'
import { WH, WH_COLORS, LIGHT_COLORS, useTheme, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, controlCardStyle, pageWrap } from '../theme'

const { RangePicker } = DatePicker

// 统一 tooltip 样式（组件内按主题生成）
// 严重等级语义色（适配暗底）
const SEVERITY_COLORS = {
  critical: '#ff6b6b',
  major: '#ff922b',
  medium: '#ffd43b',
  minor: '#51cf66',
  info: '#4fc3f7',
}
const SEVERITY_COLORS_LIGHT = {
  critical: '#dc2626',
  major: '#ea580c',
  medium: '#ca8a04',
  minor: '#15803d',
  info: '#0284c7',
}

// 卡片标题样式
const cardTitleStyle = { fontSize: '0.875rem', fontWeight: 600, color: WH.text } as const

// 分区标题样式
const SectionTitle = ({ icon, title, explain }: { icon: React.ReactNode; title: string; explain?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: 'var(--wh-space-xl) 0 var(--wh-space-md)', padding: '0 0 var(--wh-space-sm)',
    borderBottom: '1px solid rgba(100,255,218,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 'var(--wh-radius-sm)',
      background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: '0.875rem',
    }}>{icon}</span>
    <span style={{ fontSize: '1rem', fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {explain && <ExplainIcon text={explain} size={14} />}
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
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
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
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)

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

  // 加载数据
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

  const fmt = (n: number) => n?.toLocaleString(numLocale(locale)) || '0'

  // 下钻功能
  const openDrilldown = useCallback((e?: React.MouseEvent | null, dimension?: string, value?: string) => {
    if (e && typeof e.clientX === 'number') setDrillAnchor({ x: e.clientX, y: e.clientY })
    else setDrillAnchor(null)
    setDrillVisible(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillDimension(dimension || '')
    setDrillValue(value || '')
    const params: Record<string, string> = { dimension: dimension || '' }
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
      defaultSortOrder: k === 'alarm_occur_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // 图表配置
  const CHART_HEIGHT = 300

  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const tooltipStyle = darkTooltip(isDark)
  const cText = isDark ? '#e6f4ff' : '#16233b'
  const cTextMuted = isDark ? '#94a3b8' : '#3f5468'
  const cTeal = isDark ? '#64ffda' : '#0d9488'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
  const sevColors = isDark ? SEVERITY_COLORS : SEVERITY_COLORS_LIGHT

  // MTTR周趋势
  const mttrOption = useMemo(() => {
    if (!data?.mttr_weekly?.length) return {}
    const weeks = data.mttr_weekly.map((w: any) => w.week)
    const mttrs = data.mttr_weekly.map((w: any) => w.mttr)
    const counts = data.mttr_weekly.map((w: any) => w.count)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'cross', crossStyle: { color: '#999' } } },
      legend: { data: [t('ttwo.seriesTTCount'), t('ttwo.seriesMTTR')], bottom: 5, textStyle: { fontSize: 11, color: cTextMuted } },
      grid: { left: 60, right: 60, top: 30, bottom: 55 },
      xAxis: { type: 'category', data: weeks, axisLabel: { ...axisLabel(isDark), rotate: 45 }, axisLine: axisLine(isDark) },
      yAxis: [
        { type: 'value', name: t('ttwo.seriesTTCount'), position: 'left', nameTextStyle: { color: cTeal, fontSize: 11 }, axisLabel: { color: cTeal }, splitLine: splitLine(isDark) },
        { type: 'value', name: t('ttwo.seriesMTTR'), position: 'right', nameTextStyle: { color: isDark ? '#ff6b6b' : '#dc2626', fontSize: 11 }, axisLabel: { color: isDark ? '#ff6b6b' : '#dc2626' }, splitLine: { show: false } },
      ],
      series: [
        {
          name: t('ttwo.seriesTTCount'), type: 'bar', data: counts, yAxisIndex: 0, barMaxWidth: 28,
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? '#64ffda' : '#0d9488' }, { offset: 1, color: isDark ? '#4fc3f7' : '#0284c7' }] }, borderRadius: [4, 4, 0, 0] },
        },
        {
          name: t('ttwo.seriesMTTR'), type: 'line', data: mttrs, yAxisIndex: 1, smooth: true,
          itemStyle: { color: isDark ? '#ff6b6b' : '#dc2626' }, lineStyle: { width: 2.5 }, symbol: 'circle', symbolSize: 6,
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? 'rgba(255,107,107,0.25)' : 'rgba(220,38,38,0.18)' }, { offset: 1, color: 'rgba(255,107,107,0.02)' }] } },
        },
      ],
    }
  }, [data?.mttr_weekly, t, isDark, tooltipStyle, cTextMuted, cTeal])

  // Domain分布
  const domainOption = useMemo(() => {
    if (!data?.domain_stats) return {}
    const entries = Object.entries(data.domain_stats).sort((a: any, b: any) => a[1] - b[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 90, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any, i: number) => ({
          value: e[1],
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: cPalette[i % cPalette.length] }, { offset: 1, color: cPalette[(i + 3) % cPalette.length] }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.domain_stats, isDark, tooltipStyle, cText, cTextMuted, cPalette, locale])

  // 通用饼图配置
  const makePieOption = useCallback((entries: [string, any][], hasLegend = true) => ({
    tooltip: { ...tooltipStyle, trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
    legend: hasLegend ? { orient: 'vertical' as const, right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 } : undefined,
    series: [{
      type: 'pie', radius: ['35%', '65%'], center: ['35%', '50%'],
      data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
      label: { fontSize: 10, color: cText, formatter: '{b}\n{d}%' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 2, shadowColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.3)' } },
    }],
  }), [tooltipStyle, cText, cTextMuted, cPalette, isDark])

  const rcMainOption = useMemo(() => {
    if (!data?.root_cause?.main) return {}
    const entries = Object.entries(data.root_cause.main).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.main, makePieOption])

  const rcSubOption = useMemo(() => {
    if (!data?.root_cause?.sub) return {}
    const entries = Object.entries(data.root_cause.sub).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.sub, makePieOption])

  // WO Source 柱状图
  const woSourceOption = useMemo(() => {
    if (!data?.wo_stats?.source) return {}
    const entries = Object.entries(data.wo_stats.source).sort((a: any, b: any) => b[1] - a[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 80, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#51cf66' : '#15803d' }, { offset: 1, color: isDark ? '#94d82d' : '#4d7c0f' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.wo_stats?.source, isDark, tooltipStyle, cText, cTextMuted, locale])

  // WO Status 柱状图
  const woStatusOption = useMemo(() => {
    if (!data?.wo_stats?.status) return {}
    const entries = Object.entries(data.wo_stats.status).sort((a: any, b: any) => b[1] - a[1])
    const statusColors: Record<string, string[]> = isDark
      ? {
          Closed: ['#51cf66', '#94d82d'], Open: ['#4fc3f7', '#74c0fc'], 'In Progress': ['#ffd43b', '#fcc419'],
          Pending: ['#ffa94d', '#ff922b'], Cancelled: ['#adb5bd', '#dee2e6'],
        }
      : {
          Closed: ['#15803d', '#4d7c0f'], Open: ['#0284c7', '#0ea5e9'], 'In Progress': ['#ca8a04', '#a16207'],
          Pending: ['#ea580c', '#c2410c'], Cancelled: ['#64748b', '#94a3b8'],
        }
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 140, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 10, color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => {
          const colors = statusColors[e[0]] || statusColors['In Progress']
          return {
            value: e[1],
            itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: colors[0] }, { offset: 1, color: colors[1] }] }, borderRadius: [0, 4, 4, 0] },
          }
        }),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.wo_stats?.status, isDark, tooltipStyle, cText, cTextMuted, locale])

  // Power Sources 饼图
  const powerSourceOption = useMemo(() => {
    if (!data?.site_stats?.power_sources) return {}
    const entries = Object.entries(data.site_stats.power_sources).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 9, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
        label: { fontSize: 9, color: cText, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.3)' } },
      }],
    }
  }, [data?.site_stats?.power_sources, isDark, tooltipStyle, cText, cTextMuted, cPalette])

  // Maintenance Team 柱状图
  const fmeOption = useMemo(() => {
    if (!data?.site_stats?.maintenance_team) return {}
    const entries = Object.entries(data.site_stats.maintenance_team).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 130, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 9, color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 18,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#b197fc' : '#7c3aed' }, { offset: 1, color: isDark ? '#d0bfff' : '#a78bfa' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 9, color: cTextMuted },
      }],
    }
  }, [data?.site_stats?.maintenance_team, isDark, tooltipStyle, cText, cTextMuted])

  // Power Vendor 饼图
  const powerVendorOption = useMemo(() => {
    if (!data?.site_stats?.power_vendor) return {}
    const entries = Object.entries(data.site_stats.power_vendor)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['35%', '65%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
        label: { fontSize: 11, color: cText, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.3)' } },
      }],
    }
  }, [data?.site_stats?.power_vendor, isDark, tooltipStyle, cText, cPalette])

  // 统计卡片颜色映射
  const sevColor: Record<string, string> = {
    Critical: sevColors.critical, Major: sevColors.major, Medium: sevColors.medium, Minor: sevColors.minor,
    'Proactive Fault': sevColors.info, 'Incident Fault': sevColors.major, 'Custom Complain': isDark ? '#eb2f96' : '#be185d',
    Unknown: isDark ? '#adb5bd' : '#64748b'
  }
  const ticketColor: Record<string, string> = {
    P1: sevColors.critical, P2: sevColors.major, P3: sevColors.info, P4: sevColors.minor,
    'Critical(4H)': sevColors.critical, 'Major(24H)': sevColors.major, 'Warning': sevColors.medium, 'Minor(72H)': sevColors.minor,
    Unknown: isDark ? '#adb5bd' : '#64748b'
  }
  const slaColor: Record<string, string> = {
    Pass: isDark ? '#51cf66' : '#15803d',
    Failed: isDark ? '#ff6b6b' : '#dc2626',
    'Within SLA': isDark ? '#4fc3f7' : '#0284c7',
    Unknown: isDark ? '#adb5bd' : '#64748b',
  }
  const autoPalette = cPalette
  const autoColorCache: Record<string, string> = {}
  const getAutoColor = (key: string, idx: number) => {
    if (!autoColorCache[key]) autoColorCache[key] = autoPalette[idx % autoPalette.length]
    return autoColorCache[key]
  }

  // 可点击的统计标签（背景与文字随主题适配：深色主题用暗色玻璃底，浅色主题用语义色淡底）
  const renderStatTags = (stats: Record<string, number>, colorMap: Record<string, string>, dimension: string) => (
    <Space wrap size={[8, 8]}>
      {Object.entries(stats).map(([k, v], idx) => {
        const tagColor = colorMap[k] || getAutoColor(k, idx)
        const tagBg = isDark ? 'rgba(10,25,41,0.6)' : `${tagColor}1f`
        return (
          <Tag key={k}
            style={{ borderRadius: 'var(--wh-radius-lg)', padding: 'var(--wh-space-xs) 0.875rem', fontSize: '0.8125rem', lineHeight: '1.5rem', cursor: 'pointer', transition: 'all 0.2s', fontWeight: 500, background: tagBg, borderColor: tagColor, color: tagColor }}
            onClick={(e) => openDrilldown(e, dimension, k)}
          >
            {k}: <strong style={{ fontSize: '0.875rem' }}>{fmt(v)}</strong>
          </Tag>
        )
      })}
    </Space>
  )

  // Status 颜色编码（随主题适配：深色主题用亮色，浅色主题用饱和暗色保证对比度）
  const getStatusColor = (key: string): string => {
    const lower = key.toLowerCase()
    if (lower.includes('closed') || lower.includes('complete')) return isDark ? '#51cf66' : '#15803d'
    if (lower.includes('open') || lower.includes('in progress')) return isDark ? '#4fc3f7' : '#0284c7'
    if (lower.includes('waiting') || lower.includes('pending')) return isDark ? '#ffa94d' : '#ea580c'
    if (lower.includes('cancel') || lower.includes('reject')) return isDark ? '#adb5bd' : '#64748b'
    return isDark ? '#64ffda' : '#0d9488'
  }

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

  const renderStatusTags = (stats: Record<string, number>) => {
    const sorted = Object.entries(stats).sort((a, b) => (b[1] as number) - (a[1] as number))
    return (
      <div style={{ background: 'var(--wh-subtle-bg)', borderRadius: 'var(--wh-radius-md)', padding: 'var(--wh-space-md)', border: '1px solid var(--wh-subtle-border)' }}>
        <Space wrap size={[10, 10]}>
          {sorted.map(([k, v]) => (
            <Tooltip key={k} title={`Click to drill down: ${k}`}>
              <Tag
                style={{ borderRadius: 'var(--wh-radius-lg)', padding: '0.3125rem 0.875rem', fontSize: '0.8125rem', lineHeight: '1.5rem', margin: 0, cursor: 'pointer', transition: 'all 0.2s', border: 'none', background: `${getStatusColor(k)}20`, color: getStatusColor(k), fontWeight: 500 }}
                onClick={(e) => openDrilldown(e, 'status', k)}
              >
                <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: getStatusColor(k), marginRight: 6 }} />
                {shortenLabel(k)}: <strong style={{ fontSize: '0.875rem' }}>{fmt(v as number)}</strong>
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
      if (name) openDrilldown(null, dimension, name)
    }
  })

  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '6.25rem' }}>
      <Spin size="large" />
      <div style={{ marginTop: 'var(--wh-space-md)', color: WH.textMuted }}>{t('ttwo.loading')}</div>
    </div>
  )

  if (error) return (
    <div style={{ ...pageWrap, padding: 'var(--wh-space-lg)' }}>
      <Alert type="error" message={t('ttwo.loadFailed')} description={error} showIcon />
    </div>
  )

  if (!data) return <Empty description={t('ttwo.noData')} />

  const regions = data.filters?.regions || []
  const s = data.tt_stats || {}
  const sevStats = (s.alarm_severity && Object.keys(s.alarm_severity).length > 0) ? s.alarm_severity : (s.category || {})
  const sevDimension = (s.alarm_severity && Object.keys(s.alarm_severity).length > 0) ? 'alarm_severity' : 'category'
  const sevLabel = sevDimension === 'alarm_severity' ? t('ttwo.alarmSeverity') : t('ttwo.category')

  // 暗色汇总卡片生成器
  const SummaryCard = ({ color, icon, value, label, onClick, explain }: { color: string; icon: React.ReactNode; value: number; label: string; onClick?: (e: React.MouseEvent) => void; explain?: string }) => (
    <Card size="small" hoverable style={{ ...cardStyle, position: 'relative', cursor: onClick ? 'pointer' : 'default', borderLeft: `4px solid ${color}` }}
      onClick={onClick}>
      {explain && (
        <span style={{ position: 'absolute', top: 6, right: 8, zIndex: 2, cursor: 'help' }} onClick={e => e.stopPropagation()}>
          <ExplainIcon text={explain} />
        </span>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Statistic title={<span style={{ color: WH.textMuted }}>{label}</span>} value={value} valueStyle={{ fontSize: '2rem', fontWeight: 800, color, textShadow: `0 0 14px ${color}55` }} />
        <span style={{ fontSize: '2.5rem', opacity: 0.15, color }}>{icon}</span>
      </div>
    </Card>
  )

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      {/* 筛选栏 */}
      <Card size="small" style={{ ...controlCardStyle, background: WH.cardBg }}>
        <Space wrap align="center" size="middle">
          <Segmented
            options={[
              { label: <span style={{ color: timePreset === 'all' ? WH.teal : WH.text }}>{t('ttwo.allTime')}</span>, value: 'all' },
              { label: <span style={{ color: timePreset === 'last7' ? WH.teal : WH.text }}>{t('ttwo.last7Days')}</span>, value: 'last7' },
              { label: <span style={{ color: timePreset === 'last30' ? WH.teal : WH.text }}>{t('ttwo.last30Days')}</span>, value: 'last30' },
              { label: <span style={{ color: timePreset === 'last90' ? WH.teal : WH.text }}>{t('ttwo.last3Months')}</span>, value: 'last90' },
              { label: <span style={{ color: timePreset === 'last180' ? WH.teal : WH.text }}>{t('ttwo.last6Months')}</span>, value: 'last180' },
              { label: <span style={{ color: timePreset === 'custom' ? WH.teal : WH.text }}>{t('ttwo.custom')}</span>, value: 'custom' },
            ]}
            value={timePreset}
            onChange={setTimePreset}
            style={{ background: 'var(--wh-seg-bg)' }}
          />
          {timePreset === 'custom' && (
            <RangePicker value={customRange} onChange={setCustomRange} />
          )}
          <Select
            value={selectedRegion}
            onChange={setSelectedRegion}
            style={{ width: 'min(100%, 11.25rem)' }}
            allowClear
            placeholder={t('ttwo.allRegions')}
            options={regions.map((r: string) => ({ value: r, label: r }))}
          />
          <Tag
            icon={<ClockCircleOutlined />}
            color={isSynced ? 'green' : 'red'}
            style={{ marginLeft: 'auto', borderRadius: 'var(--wh-radius-lg)', padding: '0.125rem 0.75rem' }}
          >
            {isSynced ? t('ttwo.synced', { time: lastSync ?? '' }) : t('ttwo.notSynced')}
          </Tag>
        </Space>
      </Card>

      {/* 汇总卡片 */}
      <Row gutter={16}>
        <Col span={data.summary.wo_total > 0 ? 8 : 24}>
          <SummaryCard color="#4fc3f7" icon={<ThunderboltOutlined />} value={data.summary.tt_total} label={t('ttwo.ttTotal')} explain={t('ttwo.explain.ttTotal')} onClick={(e) => openDrilldown(e, 'all_tt')} />
        </Col>
        {data.summary.wo_total > 0 && <Col span={8}>
          <SummaryCard color="#51cf66" icon={<FileTextOutlined />} value={data.summary.wo_total} label={t('ttwo.woTotal')} explain={t('ttwo.explain.woTotal')} onClick={(e) => openDrilldown(e, 'all_wo')} />
        </Col>}
        {data.summary.wo_total > 0 && <Col span={8}>
          <SummaryCard color="#b197fc" icon={<NumberOutlined />} value={data.summary.wo_no_count} label={t('ttwo.woNoUnique')} explain={t('ttwo.explain.woNo')} onClick={(e) => openDrilldown(e, 'all_wo')} />
        </Col>}
      </Row>

      {/* TT 统计标签 */}
      <SectionTitle icon={<AlertOutlined />} title={t('ttwo.ttStatistics')} />
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>{sevLabel} <ExplainIcon text={t('ttwo.explain.severity')} /></span>} style={cardStyle} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(sevStats, sevColor, sevDimension)}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>{t('ttwo.ticketSeverity')} <ExplainIcon text={t('ttwo.explain.ticketSeverity')} /></span>} style={cardStyle} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(s.ticket_severity, ticketColor, 'ticket_severity')}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title={<span style={cardTitleStyle}>{t('ttwo.slaStatus')} <ExplainIcon text={t('ttwo.explain.sla')} /></span>} style={cardStyle} styles={{ body: { minHeight: 60 } }}>
            {renderStatTags(s.sla_status, slaColor, 'sla_status')}
          </Card>
        </Col>
      </Row>
      <Card size="small" title={<span style={cardTitleStyle}>{t('ttwo.status')}</span>} style={cardStyle}>
        {renderStatusTags(s.status || {})}
      </Card>

      {/* MTTR 周趋势 */}
      <SectionTitle icon={<BarChartOutlined />} title={t('ttwo.mttrTrend')} explain={t('ttwo.explain.mttr')} />
      <Card size="small" style={cardStyle}>
        <div role="img" aria-label="MTTR Weekly Trend chart">
          <ReactECharts option={mttrOption} style={{ height: CHART_HEIGHT }}
            onEvents={onChartClick('week')} />
        </div>
      </Card>

      {/* Domain + Root Cause */}
      <SectionTitle icon={<PieChartOutlined />} title={t('ttwo.domainRootCause')} />
      <Row gutter={[16, 16]}>
        <Col span={10}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.ttByDomain')}</span>} size="small" style={cardStyle}>
            <div role="img" aria-label="TT by Domain chart">
              <ReactECharts option={domainOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('domain')} />
            </div>
          </Card>
        </Col>
        <Col span={7}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.rootCauseMain')} <ExplainIcon text={t('ttwo.explain.rootCause')} /></span>} size="small" style={cardStyle}>
            <div role="img" aria-label="Root Cause Main chart">
              <ReactECharts option={rcMainOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('rc_main')} />
            </div>
          </Card>
        </Col>
        <Col span={7}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.rootCauseSub')} <ExplainIcon text={t('ttwo.explain.rootCause')} /></span>} size="small" style={cardStyle}>
            <div role="img" aria-label="Root Cause Sub chart">
              <ReactECharts option={rcSubOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('rc_sub')} />
            </div>
          </Card>
        </Col>
      </Row>

      {/* WO Source + Status */}
      {data.summary.wo_total > 0 && <>
        <SectionTitle icon={<TagsOutlined />} title={t('ttwo.woAnalytics')} />
        <Row gutter={[16, 16]}>
          <Col span={12}>
            <Card title={<span style={cardTitleStyle}>{t('ttwo.woBySource')}</span>} size="small" style={cardStyle}>
              <div role="img" aria-label="WO by Source chart">
                <ReactECharts option={woSourceOption} style={{ height: CHART_HEIGHT }}
                  onEvents={onChartClick('wo_source')} />
              </div>
            </Card>
          </Col>
          <Col span={12}>
            <Card title={<span style={cardTitleStyle}>{t('ttwo.woByStatus')}</span>} size="small" style={cardStyle}>
              <div role="img" aria-label="WO by Status chart">
                <ReactECharts option={woStatusOption} style={{ height: CHART_HEIGHT }}
                  onEvents={onChartClick('wo_status')} />
              </div>
            </Card>
          </Col>
        </Row>
      </>}

      {/* 站点信息 */}
      <SectionTitle icon={<EnvironmentOutlined />} title={t('ttwo.siteInfo')} />
      <Row gutter={[16, 16]}>
        {Object.entries(data.site_stats || {}).filter(([, v]) => v && Object.keys(v as any).length > 0).map(([key, stats]) => (
          <Col span={8} key={key}>
            <Card title={<span style={cardTitleStyle}>{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>} size="small" style={cardStyle}>
              <ReactECharts option={{
                tooltip: { ...tooltipStyle, trigger: 'axis' },
                grid: { left: 100, right: 30, top: 10, bottom: 10 },
                xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
                yAxis: { type: 'category', data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map(e => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
                series: [{ type: 'bar', barMaxWidth: 18, data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map((e: any, i: number) => ({ value: e[1], itemStyle: { color: cPalette[i % cPalette.length], borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: 'right', fontSize: 9, color: cTextMuted } }],
              }} style={{ height: CHART_HEIGHT }} onEvents={onChartClick(key)} />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 下钻 Modal */}
      <DraggableClickModal
        open={drillVisible}
        anchor={drillAnchor}
        onClose={() => setDrillVisible(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan">{t('common.records', { n: filteredDrillData.length })}</Tag></span>}
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
