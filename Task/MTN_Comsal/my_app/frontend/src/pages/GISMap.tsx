import { useEffect, useState, useMemo, useCallback } from 'react'
import { Card, Row, Col, Select, Spin, Drawer, Descriptions, Table, Tag, Statistic, Tabs, Space, Badge, DatePicker, Segmented, Tooltip, Switch, Button, Input } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
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
}

interface DrilldownData {
  site_info: Record<string, any>
  tt_list: any[]
  tt_count: number
  wo_list: any[]
  wo_count: number
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

type LegendKey = 'critical' | 'warning' | 'vip' | 'normal'

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
  const [apiError, setApiError] = useState<string | null>(null)
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
    setApiError(null)
    const params: any = {}
    if (selectedRegion) params.region = selectedRegion
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }

    api.get('/gis/sites', { params })
      .then(res => {
        // 验证返回的是JSON而非HTML（SPA catch-all陷阱）
        if (typeof res.data === 'string' || !res.data.sites) {
          setApiError('API returned invalid data. Backend may not be running.')
          setSites([])
          return
        }
        setSites(res.data.sites || [])
        if (regions.length === 0) setRegions(res.data.regions || [])
      })
      .catch(err => {
        const msg = err.response?.status === 404
          ? 'GIS API not available. Backend may be missing scipy/shapely.'
          : `API error: ${err.message || 'Unknown error'}`
        setApiError(msg)
        setSites([])
      })
      .finally(() => setLoading(false))
  }

  // 加载拓扑数据
  useEffect(() => {
    if (showTopology && topologyLinks.length === 0) {
      api.get('/gis/topology')
        .then(res => setTopologyLinks(res.data.links || []))
        .catch(err => console.warn('Topology API error:', err.message))
    }
  }, [showTopology])

  // 加载Region边界
  useEffect(() => {
    api.get('/gis/region-boundaries')
      .then(res => {
        if (typeof res.data === 'object' && res.data.regions) {
          setRegionBoundaries(res.data.regions || [])
        }
      })
      .catch(err => console.warn('Region boundaries API error:', err.message))
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
    if (site.open_tt > 5) return 'critical'
    if (site.open_tt > 0) return 'warning'
    if (site.vip_site === 'Y' || site.vip_site === 'Yes') return 'vip'
    return 'normal'
  }

  const filteredSites = useMemo(() => {
    return sites.filter(site => !hiddenLegends.has(getSiteCategory(site)))
  }, [sites, hiddenLegends])

  const center: [number, number] = sites.length > 0
    ? [
        sites.reduce((s, p) => s + p.lat, 0) / sites.length,
        sites.reduce((s, p) => s + p.lng, 0) / sites.length,
      ]
    : [6.4, -9.4]

  const getMarkerColor = (site: Site) => {
    const cat = getSiteCategory(site)
    switch (cat) {
      case 'critical': return '#ff4d4f'
      case 'warning': return '#faad14'
      case 'vip': return '#722ed1'
      default: return '#52c41a'
    }
  }

  const getMarkerRadius = (site: Site) => {
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
  const categoryCounts = useMemo(() => {
    const counts = { critical: 0, warning: 0, vip: 0, normal: 0 }
    sites.forEach(s => {
      counts[getSiteCategory(s)]++
    })
    return counts
  }, [sites])

  const legendItems: { key: LegendKey; color: string; label: string; count: number }[] = [
    { key: 'critical', color: '#ff4d4f', label: t('gis.legend.critical'), count: categoryCounts.critical },
    { key: 'warning', color: '#faad14', label: t('gis.legend.warning'), count: categoryCounts.warning },
    { key: 'vip', color: '#722ed1', label: t('gis.legend.vip'), count: categoryCounts.vip },
    { key: 'normal', color: '#52c41a', label: t('gis.legend.normal'), count: categoryCounts.normal },
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
      </Card>

      <Card styles={{ body: { padding: 0 } }}>
        {loading ? (
          <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
        ) : apiError ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <div style={{ color: '#ff4d4f', fontSize: 16, marginBottom: 12 }}>⚠ {apiError}</div>
            <div style={{ color: '#888', fontSize: 13, marginBottom: 16 }}>Check backend console for errors. Make sure scipy/shapely are installed.</div>
            <Button onClick={loadSites}>Retry</Button>
          </div>
        ) : sites.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>
            No sites found. Try adjusting filters or check if data was synced.
          </div>
        ) : (
          <MapContainer
            center={center}
            zoom={8}
            style={{ height: 'calc(100vh - 245px)', width: '100%' }}
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
                  <div style={{ minWidth: 200 }}>
                    <strong>{site.site_name}</strong> ({site.site_id})<br />
                    {t('gis.popup.region')}: {site.region}<br />
                    {t('gis.popup.type')}: {site.site_type} | {site.network_type}<br />
                    TT: {site.tt_count} (Open: {site.open_tt})<br />
                    WO: {site.wo_count}<br />
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
              <Col span={8}>
                <Card size="small"><Statistic title={t('gis.drilldown.totalTT')} value={drilldown.tt_count} /></Card>
              </Col>
              <Col span={8}>
                <Card size="small"><Statistic title={t('gis.drilldown.totalWO')} value={drilldown.wo_count} /></Card>
              </Col>
              <Col span={8}>
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
