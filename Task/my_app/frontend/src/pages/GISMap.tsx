import { useEffect, useState, useMemo, useCallback } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Drawer, Descriptions, Table, Tag, Statistic, Tabs, Space, Badge, DatePicker, Segmented, Tooltip, Switch, Button, Input } from 'antd'
import { DownloadOutlined, SearchOutlined, FilterOutlined, AlertOutlined, ThunderboltOutlined } from '@ant-design/icons'
import * as XLSX from 'xlsx'
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, Polygon, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { useDataTimestamps } from '../useDataTimestamps'

interface Site {
  site_id: string
  site_name: string
  lat: number
  lng: number
  region: string
  province_county: string
  network_type: string
  site_type: string
  vip_site: string
  hub_site: string
  tt_count: number
  open_tt: number
  closed_tt: number
  wo_count: number
  rt_alarm_count: number
  his_alarm_count: number
  // 筛选列
  trm_type?: string
  area?: string
  hubsite?: string
  site_information?: string
  supervisor?: string
  updated_fme_name_new?: string
}

interface DrilldownData {
  site_info: Record<string, any>
  tt_list: any[]
  tt_count: number
  wo_list: any[]
  wo_count: number
  rt_alarm_list: any[]
  rt_alarm_count: number
  his_alarm_list: any[]
  his_alarm_count: number
  sla_stats: {
    total_tt: number
    closed_tt: number
    sla_met: number
    sla_violated: number
  }
}

interface TopologyLink {
  site_a_id: string
  site_a_name: string
  site_b_id: string
  site_b_name: string
  hop_count: number
  is_hub_link: boolean
  lat_a: number
  lng_a: number
  lat_b: number
  lng_b: number
}

type LegendKey = 'critical' | 'warning' | 'vip' | 'normal' | 'rt_alarm' | 'his_alarm'
type LayerKey = 'rt_alarm' | 'his_alarm' | 'tt' | 'wo'

function MapController({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap()
  useEffect(() => {
    map.setView(center, zoom)
  }, [center, zoom, map])
  return null
}

type TimePreset = 'all' | '7d' | '30d' | '90d' | '180d' | 'custom'

export default function GISMap() {
  const [sites, setSites] = useState<Site[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [selectedRegion, setSelectedRegion] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [drilldown, setDrilldown] = useState<DrilldownData | null>(null)
  const [drilldownLoading, setDrilldownLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedSite, setSelectedSite] = useState<string>('')
  const [hiddenLegends, setHiddenLegends] = useState<Set<LegendKey>>(new Set())
  const [timePreset, setTimePreset] = useState<TimePreset>('7d')
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [showTopology, setShowTopology] = useState(false)
  const [topologyLinks, setTopologyLinks] = useState<TopologyLink[]>([])
  const [regionBoundaries, setRegionBoundaries] = useState<{ region: string; polygon: [number, number][]; color: string; site_count: number }[]>([])
  const [showRegions, setShowRegions] = useState(true)
  const [ttSearch, setTtSearch] = useState('')
  const [woSearch, setWoSearch] = useState('')
  const [rtAlarmSearch, setRtAlarmSearch] = useState('')
  const [hisAlarmSearch, setHisAlarmSearch] = useState('')

  // 图层筛选状态（默认全部开启）
  const [activeLayers, setActiveLayers] = useState<Set<LayerKey>>(new Set(['rt_alarm', 'his_alarm', 'tt', 'wo']))

  // 筛选列状态
  const [filterOptions, setFilterOptions] = useState<Record<string, string[]>>({})
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string | undefined>>({})
  const [showFilters, setShowFilters] = useState(false)
  const { t } = useI18n()
  const { lastSync, latestData, isSynced } = useDataTimestamps()

  // 根据preset计算实际时间范围
  const timeRange = useMemo((): { start: string; end: string } | null => {
    if (timePreset === 'all') return null
    if (timePreset === 'custom' && customRange) {
      return { start: customRange[0].format('YYYY-MM-DD'), end: customRange[1].format('YYYY-MM-DD') }
    }
    if (timePreset === 'custom') return null
    const days = { '7d': 7, '30d': 30, '90d': 90, '180d': 180 }[timePreset] || 0
    const end = dayjs().format('YYYY-MM-DD')
    const start = dayjs().subtract(days, 'day').format('YYYY-MM-DD')
    return { start, end }
  }, [timePreset, customRange])

  useEffect(() => {
    loadSites()
  }, [selectedRegion, timeRange])

  const loadSites = () => {
    setLoading(true)
    const params: any = {}
    if (selectedRegion) params.region = selectedRegion
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }
    const cacheKey = `gis:sites:${selectedRegion || ''}:${timeRange?.start || ''}:${timeRange?.end || ''}`

    cachedGet(cacheKey, () => api.get('/gis/sites', { params }))
      .then(res => {
        setSites(res.data.sites || [])
        if (regions.length === 0) setRegions(res.data.regions || [])
        if (Object.keys(filterOptions).length === 0 && res.data.filter_options) {
          setFilterOptions(res.data.filter_options || {})
        }
      })
      .finally(() => setLoading(false))
  }

  // 加载拓扑数据
  useEffect(() => {
    if (showTopology && topologyLinks.length === 0) {
      api.get('/gis/topology')
        .then(res => setTopologyLinks(res.data.links || []))
        .catch(() => {})
    }
  }, [showTopology])

  // 加载Region边界（全局数据，缓存避免切页重复请求）
  useEffect(() => {
    cachedGet('gis:region-boundaries', () => api.get('/gis/region-boundaries'))
      .then(res => setRegionBoundaries(res.data.regions || []))
      .catch(() => {})
  }, [])

  const handleSiteClick = (site: Site) => {
    setSelectedSite(site.site_id)
    setDrilldownLoading(true)
    setDrawerVisible(true)

    api.get(`/gis/drilldown/${site.site_id}`)
      .then(res => setDrilldown(res.data))
      .catch(() => setDrilldown(null))
      .finally(() => setDrilldownLoading(false))
  }

  const toggleLegend = (key: LegendKey) => {
    setHiddenLegends(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const getSiteCategory = (site: Site): LegendKey => {
    if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 'rt_alarm'
    if (activeLayers.has('his_alarm') && site.his_alarm_count > 0) return 'his_alarm'
    if (activeLayers.has('tt') && site.open_tt > 5) return 'critical'
    if (activeLayers.has('tt') && site.open_tt > 0) return 'warning'
    if (site.vip_site === 'Y' || site.vip_site === 'Yes') return 'vip'
    return 'normal'
  }

  const filteredSites = useMemo(() => {
    return sites.filter(site => {
      // 图例筛选
      if (hiddenLegends.has(getSiteCategory(site))) return false
      // 多列筛选
      for (const [key, val] of Object.entries(selectedFilters)) {
        if (val && (site as any)[key] !== val) return false
      }
      return true
    })
  }, [sites, hiddenLegends, selectedFilters])

  const center: [number, number] = sites.length > 0
    ? [
        sites.reduce((s, p) => s + p.lat, 0) / sites.length,
        sites.reduce((s, p) => s + p.lng, 0) / sites.length,
      ]
    : [6.4, -9.4]

  const getMarkerColor = (site: Site) => {
    const cat = getSiteCategory(site)
    switch (cat) {
      case 'rt_alarm': return '#f5222d'
      case 'his_alarm': return '#fa541c'
      case 'critical': return '#ff4d4f'
      case 'warning': return '#faad14'
      case 'vip': return '#722ed1'
      default: return '#52c41a'
    }
  }

  const getMarkerRadius = (site: Site) => {
    // 有实时告警的站点更大更醒目
    if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 10
    if (activeLayers.has('his_alarm') && site.his_alarm_count > 5) return 9
    const total = site.tt_count + site.wo_count
    if (total > 50) return 10
    if (total > 20) return 8
    if (total > 5) return 6
    return 4
  }

  const regionStats = sites.reduce((acc: Record<string, number>, s) => {
    acc[s.region] = (acc[s.region] || 0) + 1
    return acc
  }, {})

  const presetOptions = [
    { value: 'all', label: t('gis.timeAll') },
    { value: '7d', label: t('gis.timeLast7') },
    { value: '30d', label: t('gis.timeLast30') },
    { value: '90d', label: t('gis.timeLast90') },
    { value: '180d', label: t('gis.timeLast180') },
    { value: 'custom', label: t('gis.timeCustom') },
  ]

  // 统计当前时间窗口内的分类数量
  // 筛选列配置
  const FILTER_CONFIG = [
    { key: 'trm_type', label: 'TRM Type' },
    { key: 'site_type', label: 'Site Type' },
    { key: 'area', label: 'Area' },
    { key: 'hubsite', label: 'Hub Site' },
    { key: 'site_information', label: 'Site Info' },
    { key: 'vip_site', label: 'VIP Site' },
    { key: 'supervisor', label: 'Supervisor' },
    { key: 'updated_fme_name_new', label: 'FME Name' },
  ]

  const activeFilterCount = Object.values(selectedFilters).filter(Boolean).length

  const handleFilterChange = (key: string, value: string | undefined) => {
    setSelectedFilters(prev => ({ ...prev, [key]: value }))
  }

  const clearAllFilters = () => {
    setSelectedFilters({})
  }

  const categoryCounts = useMemo(() => {
    const counts = { critical: 0, warning: 0, vip: 0, normal: 0, rt_alarm: 0, his_alarm: 0 }
    sites.forEach(s => {
      counts[getSiteCategory(s)]++
    })
    return counts
  }, [sites, activeLayers])

  const legendItems: { key: LegendKey; color: string; label: string; count: number }[] = [
    { key: 'rt_alarm', color: '#f5222d', label: t('gis.legend.rtAlarm'), count: categoryCounts.rt_alarm },
    { key: 'his_alarm', color: '#fa541c', label: t('gis.legend.hisAlarm'), count: categoryCounts.his_alarm },
    { key: 'critical', color: '#ff4d4f', label: t('gis.legend.critical'), count: categoryCounts.critical },
    { key: 'warning', color: '#faad14', label: t('gis.legend.warning'), count: categoryCounts.warning },
    { key: 'vip', color: '#722ed1', label: t('gis.legend.vip'), count: categoryCounts.vip },
    { key: 'normal', color: '#52c41a', label: t('gis.legend.normal'), count: categoryCounts.normal },
  ]

  // 图层切换
  const toggleLayer = (key: LayerKey) => {
    setActiveLayers(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const layerOptions: { key: LayerKey; label: string; color: string }[] = [
    { key: 'rt_alarm', label: t('gis.layer.rtAlarm'), color: '#f5222d' },
    { key: 'his_alarm', label: t('gis.layer.hisAlarm'), color: '#fa541c' },
    { key: 'tt', label: t('gis.layer.tt'), color: '#1677ff' },
    { key: 'wo', label: t('gis.layer.wo'), color: '#52c41a' },
  ]

  // 模糊搜索过滤
  const filterBySearch = (data: any[], search: string) => {
    if (!search.trim()) return data
    const lower = search.toLowerCase()
    return data.filter(row =>
      Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
    )
  }

  const filteredTT = useMemo(() => {
    if (!drilldown?.tt_list) return []
    return filterBySearch(drilldown.tt_list, ttSearch)
  }, [drilldown?.tt_list, ttSearch])

  const filteredWO = useMemo(() => {
    if (!drilldown?.wo_list) return []
    return filterBySearch(drilldown.wo_list, woSearch)
  }, [drilldown?.wo_list, woSearch])

  const filteredRtAlarm = useMemo(() => {
    if (!drilldown?.rt_alarm_list) return []
    return filterBySearch(drilldown.rt_alarm_list, rtAlarmSearch)
  }, [drilldown?.rt_alarm_list, rtAlarmSearch])

  const filteredHisAlarm = useMemo(() => {
    if (!drilldown?.his_alarm_list) return []
    return filterBySearch(drilldown.his_alarm_list, hisAlarmSearch)
  }, [drilldown?.his_alarm_list, hisAlarmSearch])

  // 导出Excel
  const exportToExcel = useCallback((data: any[], filename: string, columns: { title: string; dataIndex: string }[]) => {
    if (!data.length) return
    const header = columns.map(c => c.title)
    const keys = columns.map(c => c.dataIndex)
    const rows = data.map(row => keys.map(k => {
      const v = row[k]
      return v == null ? '' : String(v)
    }))
    const ws = XLSX.utils.aoa_to_sheet([header, ...rows])
    // 设置列宽
    ws['!cols'] = columns.map(() => ({ wch: 18 }))
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, filename)
    XLSX.writeFile(wb, `${filename}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [])

  // 通用排序器
  const strSorter = (a: any, b: any, key: string) => {
    const va = a[key] ?? '', vb = b[key] ?? ''
    return String(va).localeCompare(String(vb))
  }

  // 生成唯一filter列表
  const getUniqueFilters = (data: any[], key: string) => {
    const vals = new Set<string>()
    data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
    return Array.from(vals).map(v => ({ text: v, value: v }))
  }

  // TT表格列定义
  const ttColumns = useMemo(() => {
    const data = drilldown?.tt_list || []
    return [
      { title: t('gis.drilldown.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'title') },
      { title: t('gis.drilldown.colTicketNo'), dataIndex: 'ticket_no', key: 'ticket_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'ticket_no') },
      { title: t('gis.drilldown.colWONo'), dataIndex: 'wo_no', key: 'wo_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'wo_no') },
      { title: t('gis.drilldown.colSiteId'), dataIndex: 'site_id', key: 'site_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_id') },
      { title: t('gis.drilldown.colSiteName'), dataIndex: 'site_name', key: 'site_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_name') },
      { title: t('gis.drilldown.colSiteClass'), dataIndex: 'site_class', key: 'site_class', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_class'),
        filters: getUniqueFilters(data, 'site_class'), onFilter: (v: any, r: any) => r.site_class === v },
      { title: t('gis.drilldown.colStatus'), dataIndex: 'status', key: 'status', width: 80,
        sorter: (a: any, b: any) => strSorter(a, b, 'status'),
        filters: getUniqueFilters(data, 'status'), onFilter: (v: any, r: any) => r.status === v,
        render: (v: string) => <Tag>{v}</Tag> },
      { title: t('gis.drilldown.colCreator'), dataIndex: 'creator', key: 'creator', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'creator'),
        filters: getUniqueFilters(data, 'creator'), onFilter: (v: any, r: any) => r.creator === v },
      { title: t('gis.drilldown.colSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 90,
        sorter: (a: any, b: any) => strSorter(a, b, 'ticket_severity'),
        filters: getUniqueFilters(data, 'ticket_severity'), onFilter: (v: any, r: any) => r.ticket_severity === v },
      { title: t('gis.drilldown.colSLATime'), dataIndex: 'sla_time', key: 'sla_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_time') },
      { title: t('gis.drilldown.colSLA'), dataIndex: 'sla_status', key: 'sla_status', width: 80,
        sorter: (a: any, b: any) => strSorter(a, b, 'sla_status'),
        filters: getUniqueFilters(data, 'sla_status'), onFilter: (v: any, r: any) => r.sla_status === v,
        render: (v: string) => v ? <Tag color={(v === 'Pass' || v === 'Within SLA') ? 'green' : 'red'}>{v}</Tag> : '-' },
      { title: t('gis.drilldown.colRegionId'), dataIndex: 'region_id', key: 'region_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'region_id') },
      { title: t('gis.drilldown.colCreated'), dataIndex: 'created_time', key: 'created_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'created_time') },
      { title: t('gis.drilldown.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 140,
        sorter: (a: any, b: any) => strSorter(a, b, 'alarm_occur_time'), defaultSortOrder: 'descend' as const },
      { title: t('gis.drilldown.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_clear_time') },
      { title: t('gis.drilldown.colRootCause'), dataIndex: 'root_cause', key: 'root_cause', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'root_cause'),
        filters: getUniqueFilters(data, 'root_cause'), onFilter: (v: any, r: any) => r.root_cause === v },
      { title: t('gis.drilldown.colSubRootCause'), dataIndex: 'sub_root_cause', key: 'sub_root_cause', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'sub_root_cause') },
      { title: t('gis.drilldown.colRootCauseDesc'), dataIndex: 'root_cause_description', key: 'root_cause_description', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'root_cause_description') },
      { title: t('gis.drilldown.colSLARemain'), dataIndex: 'sla_remain_time', key: 'sla_remain_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_remain_time') },
      { title: t('gis.drilldown.colFOProcess'), dataIndex: 'fo_process_detail', key: 'fo_process_detail', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'fo_process_detail') },
    ]
  }, [drilldown?.tt_list, t])

  // WO表格列定义
  const woColumns = useMemo(() => {
    const data = drilldown?.wo_list || []
    return [
      { title: t('gis.drilldown.colWONo'), dataIndex: 'wo_no', key: 'wo_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'wo_no') },
      { title: t('gis.drilldown.colTTNo'), dataIndex: 'tt_no', key: 'tt_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'tt_no') },
      { title: t('gis.drilldown.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'title') },
      { title: t('gis.drilldown.colStatus'), dataIndex: 'status', key: 'status', width: 80,
        sorter: (a: any, b: any) => strSorter(a, b, 'status'),
        filters: getUniqueFilters(data, 'status'), onFilter: (v: any, r: any) => r.status === v,
        render: (v: string) => <Tag>{v}</Tag> },
      { title: t('gis.drilldown.colCreator'), dataIndex: 'creator', key: 'creator', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'creator'),
        filters: getUniqueFilters(data, 'creator'), onFilter: (v: any, r: any) => r.creator === v },
      { title: t('gis.drilldown.colCreated'), dataIndex: 'created_time', key: 'created_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'created_time') },
      { title: t('gis.drilldown.colLastModified'), dataIndex: 'last_modified_time', key: 'last_modified_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'last_modified_time') },
      { title: t('gis.drilldown.colOpStep'), dataIndex: 'operation_step', key: 'operation_step', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'operation_step') },
      { title: t('gis.drilldown.colSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 90,
        sorter: (a: any, b: any) => strSorter(a, b, 'ticket_severity'),
        filters: getUniqueFilters(data, 'ticket_severity'), onFilter: (v: any, r: any) => r.ticket_severity === v },
      { title: t('gis.drilldown.colNEType'), dataIndex: 'ne_type', key: 'ne_type', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'ne_type') },
      { title: t('gis.drilldown.colVendor'), dataIndex: 'vendor', key: 'vendor', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'vendor') },
      { title: t('gis.drilldown.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 140,
        sorter: (a: any, b: any) => strSorter(a, b, 'alarm_occur_time'), defaultSortOrder: 'descend' as const },
      { title: t('gis.drilldown.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_clear_time') },
      { title: t('gis.drilldown.colSource'), dataIndex: 'source', key: 'source', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'source') },
      { title: t('gis.drilldown.colProjectName'), dataIndex: 'project_name', key: 'project_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'project_name') },
      { title: t('gis.drilldown.colTemplate'), dataIndex: 'template', key: 'template', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'template') },
      { title: t('gis.drilldown.colDescription'), dataIndex: 'description', key: 'description', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'description') },
      { title: t('gis.drilldown.colAlarmSeverity'), dataIndex: 'alarm_severity', key: 'alarm_severity', width: 90,
        sorter: (a: any, b: any) => strSorter(a, b, 'alarm_severity'),
        filters: getUniqueFilters(data, 'alarm_severity'), onFilter: (v: any, r: any) => r.alarm_severity === v },
      { title: t('gis.drilldown.colFaultDuration'), dataIndex: 'fault_duration_time', key: 'fault_duration_time', width: 110, sorter: (a: any, b: any) => strSorter(a, b, 'fault_duration_time') },
      { title: t('gis.drilldown.colSLATime'), dataIndex: 'sla_time', key: 'sla_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_time') },
      { title: t('gis.drilldown.colExpectedFinish'), dataIndex: 'expected_finish_time_e2e_sla_deadline_time', key: 'expected_finish_time', width: 160, sorter: (a: any, b: any) => strSorter(a, b, 'expected_finish_time_e2e_sla_deadline_time') },
      { title: t('gis.drilldown.colRegionId'), dataIndex: 'region_id', key: 'region_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'region_id') },
      { title: t('gis.drilldown.colSiteId'), dataIndex: 'site_id', key: 'site_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_id') },
      { title: t('gis.drilldown.colSiteName'), dataIndex: 'site_name', key: 'site_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_name') },
      { title: t('gis.drilldown.colSiteType'), dataIndex: 'site_type', key: 'site_type', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_type') },
      { title: t('gis.drilldown.colSiteInfo'), dataIndex: 'site_information', key: 'site_information', ellipsis: true, width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_information') },
      { title: t('gis.drilldown.colSiteClass'), dataIndex: 'site_class', key: 'site_class', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_class') },
      { title: t('gis.drilldown.colOrgId'), dataIndex: 'organization_id', key: 'organization_id', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'organization_id') },
      { title: t('gis.drilldown.colVipSite'), dataIndex: 'vip_site', key: 'vip_site', width: 70, sorter: (a: any, b: any) => strSorter(a, b, 'vip_site') },
      { title: t('gis.drilldown.colHubSite'), dataIndex: 'hub_site', key: 'hub_site', width: 70, sorter: (a: any, b: any) => strSorter(a, b, 'hub_site') },
    ]
  }, [drilldown?.wo_list, t])

  // 实时告警表格列定义
  const rtAlarmColumns = useMemo(() => [
    { title: 'Alarm Title', dataIndex: 'alarm_title', key: 'alarm_title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_title') },
    { title: 'Code Name', dataIndex: 'codename', key: 'codename', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'codename') },
    { title: 'Severity', dataIndex: 'perceivedseverity', key: 'perceivedseverity', width: 80,
      sorter: (a: any, b: any) => (a.perceivedseverity || 0) - (b.perceivedseverity || 0),
      render: (v: number) => {
        const map: Record<number, { label: string; color: string }> = { 1: { label: 'Critical', color: 'red' }, 2: { label: 'Major', color: 'orange' }, 3: { label: 'Warning', color: 'gold' }, 4: { label: 'Info', color: 'blue' } }
        const item = map[v] || { label: `P${v}`, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      } },
    { title: 'Duration', dataIndex: 'durationname', key: 'durationname', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'durationname') },
    { title: 'Alarm Raised', dataIndex: 'alarmraisedtime', key: 'alarmraisedtime', width: 160,
      sorter: (a: any, b: any) => (a.alarmraisedtime || 0) - (b.alarmraisedtime || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-' },
    { title: 'NE Type', dataIndex: 'restypename', key: 'restypename', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'restypename') },
    { title: 'Network', dataIndex: 'networktype', key: 'networktype', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'networktype') },
    { title: 'Site Attr', dataIndex: 'site_attribute', key: 'site_attribute', width: 90, sorter: (a: any, b: any) => strSorter(a, b, 'site_attribute') },
    { title: 'Site Status', dataIndex: 'site_status', key: 'site_status', width: 90, sorter: (a: any, b: any) => strSorter(a, b, 'site_status') },
    { title: 'NE IP', dataIndex: 'neip', key: 'neip', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'neip') },
  ], [])

  // 历史告警表格列定义
  const hisAlarmColumns = useMemo(() => [
    { title: 'Alarm Title', dataIndex: 'alarm_title', key: 'alarm_title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_title') },
    { title: 'Code Name', dataIndex: 'codename', key: 'codename', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'codename') },
    { title: 'Severity', dataIndex: 'perceivedseverity', key: 'perceivedseverity', width: 80,
      sorter: (a: any, b: any) => (a.perceivedseverity || 0) - (b.perceivedseverity || 0),
      render: (v: number) => {
        const map: Record<number, { label: string; color: string }> = { 1: { label: 'Critical', color: 'red' }, 2: { label: 'Major', color: 'orange' }, 3: { label: 'Warning', color: 'gold' }, 4: { label: 'Info', color: 'blue' } }
        const item = map[v] || { label: `P${v}`, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      } },
    { title: 'Duration', dataIndex: 'durationname', key: 'durationname', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'durationname') },
    { title: 'Alarm Raised', dataIndex: 'alarmraisedtime', key: 'alarmraisedtime', width: 160,
      sorter: (a: any, b: any) => (a.alarmraisedtime || 0) - (b.alarmraisedtime || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-' },
    { title: 'TT ID', dataIndex: 'tt_id', key: 'tt_id', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'tt_id') },
    { title: 'Assign Delay', dataIndex: 'assign_delay', key: 'assign_delay', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'assign_delay') },
    { title: 'NE Type', dataIndex: 'restypename', key: 'restypename', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'restypename') },
    { title: 'Site Attr', dataIndex: 'site_attribute', key: 'site_attribute', width: 90, sorter: (a: any, b: any) => strSorter(a, b, 'site_attribute') },
  ], [])

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space size="middle" wrap>
              <span>{t('gis.regionFilter')}</span>
              <Select
                value={selectedRegion}
                onChange={setSelectedRegion}
                style={{ width: 200 }}
                allowClear
                placeholder={t('gis.allRegions')}
                options={regions.map(r => ({ value: r, label: `${r} (${regionStats[r] || 0})` }))}
              />
              <Tag color="blue">{t('gis.totalSites')}: {sites.length}</Tag>
              <Tooltip title={t('datasource.lastSync')}>
                <Tag color={isSynced ? 'green' : 'red'}>
                  {isSynced ? t('datasource.synced') : t('datasource.notSynced')}
                  {isSynced && lastSync && `: ${lastSync}`}
                </Tag>
              </Tooltip>
              <Tooltip title={t('datasource.latestData')}>
                <Tag color="geekblue">{t('datasource.latestData')}: {latestData}</Tag>
              </Tooltip>
              <Space size={4}>
                <Switch
                  size="small"
                  checked={showTopology}
                  onChange={setShowTopology}
                />
                <span style={{ fontSize: 13 }}>{t('gis.topologyToggle')}</span>
              </Space>
              <Space size={4}>
                <Switch
                  size="small"
                  checked={showRegions}
                  onChange={setShowRegions}
                />
                <span style={{ fontSize: 13 }}>{t('gis.regionOverlay')}</span>
              </Space>
            </Space>
          </Col>
          <Col>
            <Space size="small" wrap>
              <span style={{ fontSize: 13, fontWeight: 500 }}>{t('gis.layerFilter')}</span>
              {layerOptions.map(lo => (
                <Tag
                  key={lo.key}
                  color={activeLayers.has(lo.key) ? lo.color : undefined}
                  style={{
                    cursor: 'pointer',
                    opacity: activeLayers.has(lo.key) ? 1 : 0.4,
                    textDecoration: activeLayers.has(lo.key) ? 'none' : 'line-through',
                    borderRadius: 12,
                    padding: '2px 10px',
                    fontSize: 12,
                    transition: 'all 0.2s',
                  }}
                  onClick={() => toggleLayer(lo.key)}
                >
                  {lo.label}
                </Tag>
              ))}
            </Space>
          </Col>
          <Col>
            <Space size="small" wrap>
              <span>{t('gis.timeFilter')}</span>
              <Segmented
                value={timePreset}
                onChange={(v) => setTimePreset(v as TimePreset)}
                options={presetOptions}
                size="small"
              />
              {timePreset === 'custom' && (
                <DatePicker.RangePicker
                  value={customRange}
                  onChange={(dates) => setCustomRange(dates as [Dayjs, Dayjs] | null)}
                  size="small"
                  format="YYYY-MM-DD"
                  placeholder={[t('gis.timeRangeLabel'), t('gis.timeRangeLabel')]}
                />
              )}
              {timeRange && (
                <Tag color="orange">{timeRange.start} ~ {timeRange.end}</Tag>
              )}
            </Space>
          </Col>
        </Row>
        <div style={{ marginTop: 8 }}>
          {legendItems.map(item => {
            const hidden = hiddenLegends.has(item.key)
            return (
              <span
                key={item.key}
                onClick={() => toggleLegend(item.key)}
                style={{
                  cursor: 'pointer',
                  opacity: hidden ? 0.35 : 1,
                  textDecoration: hidden ? 'line-through' : 'none',
                  userSelect: 'none',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 12,
                  transition: 'opacity 0.2s',
                  marginRight: 16,
                }}
              >
                <span style={{
                  display: 'inline-block',
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  backgroundColor: item.color,
                }} />
                {item.label} ({item.count})
                {hidden && <span style={{ fontSize: 10, color: '#999' }}>({t('gis.legend.hidden')})</span>}
              </span>
            )
          })}
          {showTopology && (
            <>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, marginRight: 16 }}>
                <span style={{ display: 'inline-block', width: 20, height: 3, backgroundColor: '#ff6b35', borderRadius: 2 }} />
                {t('gis.topologyHubLink')} ({topologyLinks.filter(l => l.is_hub_link).length})
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, marginRight: 16 }}>
                <span style={{ display: 'inline-block', width: 20, height: 2, backgroundColor: '#4a90d9', borderRadius: 1 }} />
                {t('gis.topologyNormalLink')} ({topologyLinks.filter(l => !l.is_hub_link).length})
              </span>
            </>
          )}
        </div>
        {/* 多列筛选器 */}
        <div style={{ marginTop: 8 }}>
          <Space size={8} wrap>
            <Button
              size="small"
              type={showFilters ? 'primary' : 'default'}
              icon={<FilterOutlined />}
              onClick={() => setShowFilters(!showFilters)}
            >
              {t('gis.advancedFilter')}
              {activeFilterCount > 0 && <Badge count={activeFilterCount} size="small" style={{ marginLeft: 4 }} />}
            </Button>
            {activeFilterCount > 0 && (
              <Button size="small" type="link" onClick={clearAllFilters}>
                {t('gis.clearFilters')}
              </Button>
            )}
            {activeFilterCount > 0 && (
              <Tag color="blue">{t('gis.totalSites')}: {filteredSites.length}/{sites.length}</Tag>
            )}
          </Space>
          {showFilters && (
            <Row gutter={[8, 8]} style={{ marginTop: 8 }}>
              {FILTER_CONFIG.map(fc => {
                const opts = filterOptions[fc.key] || []
                if (opts.length === 0) return null
                return (
                  <Col key={fc.key}>
                    <Select
                      size="small"
                      style={{ width: 140 }}
                      allowClear
                      showSearch
                      placeholder={fc.label}
                      value={selectedFilters[fc.key]}
                      onChange={(v) => handleFilterChange(fc.key, v)}
                      options={opts.map(v => ({ value: v, label: v }))}
                      filterOption={(input, option) =>
                        String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                      }
                    />
                  </Col>
                )
              })}
            </Row>
          )}
        </div>
      </Card>

      <Card styles={{ body: { padding: 0 } }}>
        {loading ? (
          <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
        ) : (
          <MapContainer
            center={center}
            zoom={8}
            style={{ height: 'calc(100vh - 290px)', width: '100%' }}
            scrollWheelZoom={true}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapController center={center} zoom={8} />
            {filteredSites.map(site => (
              <CircleMarker
                key={site.site_id}
                center={[site.lat, site.lng]}
                radius={getMarkerRadius(site)}
                fillColor={getMarkerColor(site)}
                color="#fff"
                weight={1}
                opacity={0.9}
                fillOpacity={0.7}
                eventHandlers={{ click: () => handleSiteClick(site) }}
              >
                <Popup>
                  <div style={{ minWidth: 220 }}>
                    <strong>{site.site_name}</strong> ({site.site_id})<br />
                    {t('gis.popup.region')}: {site.region}<br />
                    {t('gis.popup.type')}: {site.site_type} | {site.network_type}<br />
                    {activeLayers.has('rt_alarm') && site.rt_alarm_count > 0 && (
                      <span style={{ color: '#f5222d', fontWeight: 600 }}>⚠ {t('gis.popup.rtAlarm')}: {site.rt_alarm_count}<br /></span>
                    )}
                    {activeLayers.has('his_alarm') && site.his_alarm_count > 0 && (
                      <span style={{ color: '#fa541c' }}>{t('gis.popup.hisAlarm')}: {site.his_alarm_count}<br /></span>
                    )}
                    {activeLayers.has('tt') && <>TT: {site.tt_count} (Open: {site.open_tt})<br /></>}
                    {activeLayers.has('wo') && <>WO: {site.wo_count}<br /></>}
                    <em style={{ color: '#1677ff' }}>{t('gis.popup.clickDetail')}</em>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
            {showRegions && regionBoundaries.map((rb, idx) => (
              <Polygon
                key={`region-${idx}`}
                positions={rb.polygon}
                pathOptions={{
                  color: rb.color,
                  fillColor: rb.color,
                  fillOpacity: 0.18,
                  weight: 2,
                  opacity: 0.7,
                }}
              />
            ))}
            {showTopology && topologyLinks.map((link, idx) => (
              <Polyline
                key={`topo-${idx}`}
                positions={[[link.lat_a, link.lng_a], [link.lat_b, link.lng_b]]}
                pathOptions={{
                  color: link.is_hub_link ? '#ff6b35' : '#4a90d9',
                  weight: link.is_hub_link ? 3 : 1.5,
                  opacity: 0.6,
                }}
              />
            ))}
          </MapContainer>
        )}
      </Card>

      <Drawer
        title={
          <span>
            {t('gis.drilldown.title')} - {drilldown?.site_info?.site_name || selectedSite}
            {drilldown?.site_info?.vip_site === 'Yes' && <Tag color="purple" style={{ marginLeft: 8 }}>VIP</Tag>}
          </span>
        }
        styles={{ wrapper: { width: 720 } }}
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
      >
        {drilldownLoading ? (
          <Spin style={{ display: 'block', margin: '50px auto' }} />
        ) : drilldown ? (
          <div>
            <Card size="small" title={t('gis.drilldown.basicInfo')} style={{ marginBottom: 16 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label={t('gis.drilldown.siteId')}>{drilldown.site_info.site_id}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.siteName')}>{drilldown.site_info.site_name}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.region')}>{drilldown.site_info.region}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.province')}>{drilldown.site_info.province_county}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.networkType')}>{drilldown.site_info.network_type}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.siteType')}>{drilldown.site_info.site_type}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.vipSite')}>
                  {drilldown.site_info.vip_site === 'Yes' || drilldown.site_info.vip_site === 'Y'
                    ? <Tag color="purple">{t('common.yes')}</Tag>
                    : <Tag>{t('common.no')}</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.siteCategory')}>{drilldown.site_info.site_class || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.coords')}>
                  {drilldown.site_info.latitude?.toFixed(4)}, {drilldown.site_info.longitude?.toFixed(4)}
                </Descriptions.Item>
                <Descriptions.Item label={t('gis.drilldown.powerSource')}>{drilldown.site_info.power_sources}</Descriptions.Item>
              </Descriptions>
            </Card>

            <Row gutter={8} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card size="small"><Statistic title={t('gis.drilldown.totalTT')} value={drilldown.tt_count} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small"><Statistic title={t('gis.drilldown.totalWO')} value={drilldown.wo_count} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small"><Statistic title={t('gis.drilldown.rtAlarm')} value={drilldown.rt_alarm_count} valueStyle={{ color: drilldown.rt_alarm_count > 0 ? '#f5222d' : undefined }} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small">
                  <Statistic
                    title={t('gis.drilldown.slaAchievement')}
                    value={
                      drilldown.sla_stats.total_tt > 0
                        ? Math.round((drilldown.sla_stats.sla_met || 0) / drilldown.sla_stats.total_tt * 100)
                        : 0
                    }
                    suffix="%"
                  />
                </Card>
              </Col>
            </Row>

            <Tabs
              items={[
                {
                  key: 'rt_alarm',
                  label: <span><ThunderboltOutlined style={{ color: '#f5222d' }} /> {t('gis.drilldown.rtAlarmTab')} ({drilldown.rt_alarm_count})</span>,
                  children: (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Input
                          prefix={<SearchOutlined />}
                          placeholder={t('table.searchPlaceholder')}
                          allowClear
                          size="small"
                          style={{ width: 250 }}
                          value={rtAlarmSearch}
                          onChange={e => setRtAlarmSearch(e.target.value)}
                        />
                        <Button
                          type="primary"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => exportToExcel(
                            filteredRtAlarm,
                            `RT_Alarm_${drilldown.site_info?.site_name || selectedSite}`,
                            rtAlarmColumns
                          )}
                        >
                          {t('gis.exportRT')}
                        </Button>
                      </div>
                      <Table
                        dataSource={filteredRtAlarm}
                        columns={rtAlarmColumns}
                        size="small"
                        rowKey={(r: any, i?: number) => `rt-${r.alarmraisedtime}-${i}`}
                        pagination={{ pageSize: 10, size: 'small', showTotal: (t: number) => `${t} items` }}
                        scroll={{ x: 'max-content' }}
                      />
                    </>
                  ),
                },
                {
                  key: 'his_alarm',
                  label: <span><AlertOutlined style={{ color: '#fa541c' }} /> {t('gis.drilldown.hisAlarmTab')} ({drilldown.his_alarm_count})</span>,
                  children: (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Input
                          prefix={<SearchOutlined />}
                          placeholder={t('table.searchPlaceholder')}
                          allowClear
                          size="small"
                          style={{ width: 250 }}
                          value={hisAlarmSearch}
                          onChange={e => setHisAlarmSearch(e.target.value)}
                        />
                        <Button
                          type="primary"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => exportToExcel(
                            filteredHisAlarm,
                            `His_Alarm_${drilldown.site_info?.site_name || selectedSite}`,
                            hisAlarmColumns
                          )}
                        >
                          {t('gis.exportHIS')}
                        </Button>
                      </div>
                      <Table
                        dataSource={filteredHisAlarm}
                        columns={hisAlarmColumns}
                        size="small"
                        rowKey={(r: any, i?: number) => `his-${r.alarmraisedtime}-${i}`}
                        pagination={{ pageSize: 10, size: 'small', showTotal: (t: number) => `${t} items` }}
                        scroll={{ x: 'max-content' }}
                      />
                    </>
                  ),
                },
                {
                  key: 'tt',
                  label: `${t('gis.drilldown.ttTab')} (${drilldown.tt_count})`,
                  children: (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Input
                          prefix={<SearchOutlined />}
                          placeholder={t('table.searchPlaceholder')}
                          allowClear
                          size="small"
                          style={{ width: 250 }}
                          value={ttSearch}
                          onChange={e => setTtSearch(e.target.value)}
                        />
                        <Button
                          type="primary"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => exportToExcel(
                            filteredTT,
                            `TT_${drilldown.site_info?.site_name || selectedSite}`,
                            ttColumns
                          )}
                        >
                          {t('gis.exportTT')}
                        </Button>
                      </div>
                      <Table
                        dataSource={filteredTT}
                        columns={ttColumns}
                        size="small"
                        rowKey={(r: any, i?: number) => `${r.title}-${i}`}
                        pagination={{ pageSize: 10, size: 'small', showTotal: (t: number) => `${t} items` }}
                        scroll={{ x: 'max-content' }}
                      />
                    </>
                  ),
                },
                {
                  key: 'wo',
                  label: `${t('gis.drilldown.woTab')} (${drilldown.wo_count})`,
                  children: (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Input
                          prefix={<SearchOutlined />}
                          placeholder={t('table.searchPlaceholder')}
                          allowClear
                          size="small"
                          style={{ width: 250 }}
                          value={woSearch}
                          onChange={e => setWoSearch(e.target.value)}
                        />
                        <Button
                          type="primary"
                          size="small"
                          icon={<DownloadOutlined />}
                          onClick={() => exportToExcel(
                            filteredWO,
                            `WO_${drilldown.site_info?.site_name || selectedSite}`,
                            woColumns
                          )}
                        >
                          {t('gis.exportWO')}
                        </Button>
                      </div>
                      <Table
                        dataSource={filteredWO}
                        columns={woColumns}
                        size="small"
                        rowKey={(r: any, i?: number) => `${r.wo_no}-${i}`}
                        pagination={{ pageSize: 10, size: 'small', showTotal: (t: number) => `${t} items` }}
                        scroll={{ x: 'max-content' }}
                      />
                    </>
                  ),
                },
              ]}
            />
          </div>
        ) : (
          <div>{t('gis.drilldown.loadError')}</div>
        )}
      </Drawer>
    </div>
  )
}
