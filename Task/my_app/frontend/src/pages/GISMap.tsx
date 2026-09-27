import { useEffect, useState, useMemo } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Tag, Space, Badge, DatePicker, Segmented, Tooltip, Switch, Button } from 'antd'
import { DownloadOutlined, FilterOutlined } from '@ant-design/icons'
// Tooltip 与 antd 的 Tooltip 重名：antd 那个用于悬浮提示（顶部同步时间等），
// react-leaflet 这个用于地图内的常驻标注（县名）。别名区分，避免误用。
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, Polygon, Pane, Tooltip as MapTooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import MapWheelZoomOnClick, { isEmbeddedInPortal } from '../components/MapWheelZoomOnClick'
import { useDataTimestamps } from '../useDataTimestamps'
import { WH, WH_COLORS, cardStyle, controlCardStyle, pageWrap, useTheme } from '../theme'
import { MapController } from './gismap/MapController'
import { SiteDrilldownDrawer } from './gismap/SiteDrilldownDrawer'
import type { Site, DrilldownData, DrilldownAnalytics, TopologyLink, LegendKey, LayerKey, TimePreset, BoundaryMode, CountyBoundary } from './gismap/types'
import { SITE_COLORS, KML_LINK_COLORS } from './gismap/types'
import { exportAoaReport } from '../utils/excelReport'

/* 默认取景：**完整居中显示利比里亚全境**（2026-09-25 改，按用户需求）。
   需求原话：「打开默认为当前点一下减号的效果，注意要保持利比里亚居中」——
   即打开就要看全整个国家，而不是放大到只看得见中间一块。

   为什么不能继续用写死的 zoom=8（原实现）：
     门户中列的地图画布是窄竖条（实测 570×856），各档在该画布下的可视范围：
       zoom 7 → 约 9.34°纬 × 6.26°经   ✅ 装得下国土（4.85°纬 × 4.40°经）
       zoom 8 → 约 4.67°纬 × 3.13°经   ❌ 装不下（纬差 0.18，经差 1.27）
       zoom 9 → 约 2.33°纬 × 1.56°经   ❌ 完全装不下
     也就是说 zoom 8 无论怎么调中心都会裁掉国土东西边缘，与「保持利比里亚居中（看全）」
     直接冲突。改画布尺寸也救不回来：中列宽度是门户版式定的，不是本页能决定的。
     故本页默认改用 zoom=LB_FIT_ZOOM（=7），并把中心对齐国土 bbox 中心。

   ⚠️ 为什么中心用「国土 bbox 中心」而不是「站点重心」：
     站点重心（827 站实测 6.5461N / 9.8475E）受站点分布不均影响，会往西南偏；
     而用户要的是「利比里亚居中」，指的是**国土**在画面正中。
     用 bbox 中心（6.325N / 9.5W）才与这句话的字面意思一致，也能保证东西南北留白均匀。
     bbox 取值与 mw_real_time.html 的 LB_BOUNDS 保持一致（单一真相源在那边，
     这里只是同一组数字的第二处副本 —— 若哪天国土范围变了，两处要一起改）。 */
const LB_BOUNDS = { south: 3.9, west: -11.7, north: 8.75, east: -7.3 }
const LB_CENTER: [number, number] = [
  (LB_BOUNDS.south + LB_BOUNDS.north) / 2,
  (LB_BOUNDS.west + LB_BOUNDS.east) / 2,
]
/* zoom 7 = 在门户中列画布下刚好装下全境的最低档（见上方实测表）。
   不写成 6：zoom 6 会多出一圈无意义的空白海域，站点被挤在中间一小块。 */
const LB_FIT_ZOOM = 7

/* 站点分类配色 SITE_COLORS 与 MW 链路线色 KML_LINK_COLORS 已移入
   ./gismap/types.ts —— 下钻抽屉也要用同一组色，定义在这里会造成循环依赖。
   详见 types.ts 内的撞色说明。 */


export default function GISMap({ mode = 'all' }: { mode?: 'all' | 'realtime' }) {
  const [sites, setSites] = useState<Site[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [selectedRegion, setSelectedRegion] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [drilldown, setDrilldown] = useState<DrilldownData | null>(null)
  const [drilldownLoading, setDrilldownLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedSite, setSelectedSite] = useState<string>('')
  const [analytics, setAnalytics] = useState<DrilldownAnalytics | null>(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  // 下钻统计/明细窗口天数（默认 60 天）
  const [drillRangeDays, setDrillRangeDays] = useState(60)
  /* 默认隐藏的图例类别（2026-09-25 用户要求）：
       'normal' —— 「无任何告警/工单」的站点，数量最多（实测 739/827），
                   默认铺满地图会把真正需要关注的告警站淹没。
       注意**只隐 normal**：VIP 站点（实测 50 个）按用户要求保留显示 —— 它们是
       重要站点，即使当前无告警也需要保持可见；其余类别由 activeLayers 控制。

     hiddenLegends 语义是「被点击隐藏的类别」，与图例的删除线状态同源，
     所以这里给初值即可让图例正确显示为「已隐藏」，用户点一下就能恢复。 */
  const [hiddenLegends, setHiddenLegends] = useState<Set<LegendKey>>(
    new Set<LegendKey>(['normal'])
  )
  const [timePreset, setTimePreset] = useState<TimePreset>(mode === 'realtime' ? 'all' : '7d')
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(null)
  /* MW 链路开关：**默认开启**（2026-09-25 用户要求）。
     与 activeLayers 的实时告警一起构成全量模式的默认视图：只看「实时告警 + MW 链路」。 */
  const [showTopology, setShowTopology] = useState(true)
  const [topologyLinks, setTopologyLinks] = useState<TopologyLink[]>([])
  const [regionBoundaries, setRegionBoundaries] = useState<{ region: string; polygon: [number, number][]; color: string; site_count: number }[]>([])
  /* 边界蒙层三选一（2026-09-25 新增 county，并按用户要求把默认值定为 county）：
       none   —— 不显示任何蒙层
       region —— 由站点坐标 Voronoi 推算的 3 个大区（旧默认）
       county —— 用户提供的 15 个县**真实**行政边界（现默认，2026-09-25 用户要求）
     取代了原先的 showRegions 布尔开关：两个蒙层若同时开启会互相遮盖，
     且语义不同（推算 vs 真实），用互斥的三选一表达更准确。 */
  const [boundaryMode, setBoundaryMode] = useState<BoundaryMode>('county')
  const [counties, setCounties] = useState<CountyBoundary[]>([])
  const [ossStats, setOssStats] = useState<{ oss_specific_problem: string; count: number; sites: number }[]>([])

  /* 默认图层（2026-09-25 用户要求调整为「默认只显示实时告警 + MW 链路」）：
       all      —— 只开 rt_alarm（＋上方 showTopology 的 MW 链路）。
                   注意本开关**不只是配色**：getSiteCategory + filteredSites 会据此
                   把该类别站点从地图上过滤掉（:265-267），所以关掉 his_alarm/tt/wo
                   后，无实时告警的站点不再绘制 —— 这正是「只显示实时告警」的效果。
       realtime —— 实时告警页保留原有的 rt_alarm + tt + wo（tt/wo 由告警的 tt_id 派生，
                   是告警关联工单的直观体现，不属于「用户额外打开的图层」）。

     其余图层（历史告警 / TT / WO）用户点击图层 Tag 即可打开，状态存在本组件
     activeLayers 里，刷新页面回到此默认值（本页不做持久化，与既有行为一致）。 */
  const [activeLayers, setActiveLayers] = useState<Set<LayerKey>>(
    new Set(mode === 'realtime' ? ['rt_alarm', 'tt', 'wo'] : ['rt_alarm'])
  )

  const [filterOptions, setFilterOptions] = useState<Record<string, string[]>>({})
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string | undefined>>({})
  const [showFilters, setShowFilters] = useState(false)
  const { t } = useI18n()
  const { isDark } = useTheme()
  const { lastSync, latestData, alarmLastSync, isSynced } = useDataTimestamps()

  // 实时数据：RealTime Alarm Map 不使用时间范围
  const timeRange = useMemo((): { start: string; end: string } | null => {
    if (mode === 'realtime') return null
    if (timePreset === 'all') return null
    if (timePreset === 'custom' && customRange) {
      return { start: customRange[0].format('YYYY-MM-DD'), end: customRange[1].format('YYYY-MM-DD') }
    }
    if (timePreset === 'custom') return null
    const days = { '7d': 7, '30d': 30, '90d': 90, '180d': 180 }[timePreset] || 0
    const end = dayjs().format('YYYY-MM-DD')
    const start = dayjs().subtract(days, 'day').format('YYYY-MM-DD')
    return { start, end }
  }, [timePreset, customRange, mode])

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
    const cacheKey = `gis:${mode}:sites:${selectedRegion || ''}:${timeRange?.start || ''}:${timeRange?.end || ''}`

    cachedGet(cacheKey, () => api.get(mode === 'realtime' ? '/gis/realtime/sites' : '/gis/sites', { params }))
      .then(res => {
        setSites(res.data.sites || [])
        if (mode === 'realtime' && res.data.realtime_alarm_summary) {
          setOssStats(res.data.realtime_alarm_summary.oss_problem_stats || [])
        }
        if (regions.length === 0) setRegions(res.data.regions || [])
        if (Object.keys(filterOptions).length === 0 && res.data.filter_options) {
          setFilterOptions(res.data.filter_options || {})
        }
      })
      .catch(err => {
        // 不吞异常：后端 500 时明确报错，避免页面静默停留在旧数据造成“筛选不生效”假象
        console.error('[GISMap] loadSites failed:', err?.response?.status, err?.response?.data || err)
        setSites([])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (showTopology && topologyLinks.length === 0) {
      api.get('/gis/topology')
        .then(res => setTopologyLinks(res.data.links || []))
        .catch(() => {})
    }
  }, [showTopology])

  useEffect(() => {
    cachedGet('gis:region-boundaries', () => api.get('/gis/region-boundaries'))
      .then(res => setRegionBoundaries(res.data.regions || []))
      .catch(() => {})
  }, [])

  // 县界是静态 GeoJSON（后端 1 小时缓存），只在首次切到 county 模式时拉取，
  // 避免每次进页面都多传约 400KB。
  useEffect(() => {
    if (boundaryMode !== 'county' || counties.length > 0) return
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => setCounties(res.data.counties || []))
      .catch(err => {
        // 不吞异常：边界拉不到时明确报错，界面回落为「无蒙层」而不是静默空白
        console.error('[GISMap] county boundaries failed:', err?.response?.status, err?.response?.data || err)
        setCounties([])
      })
  }, [boundaryMode, counties.length])

  /* 点击县界 → 复用既有的 province_county 高级筛选形成下钻闭环。
     用 db_name（与站点表 province_county 对齐的值）：附件里叫 "Rivercess"，
     而库里是 "River Cess"，直接拿 name 去筛会得到 0 个站点。 */
  const handleCountyClick = (c: CountyBoundary) => {
    setSelectedFilters(prev => ({ ...prev, province_county: c.db_name }))
    setShowFilters(true)
  }

  const handleSiteClick = (site: Site) => {
    setSelectedSite(site.site_id)
    setDrilldownLoading(true)
    setDrawerVisible(true)

    api.get(`/${mode === 'realtime' ? 'gis/realtime/drilldown' : 'gis/drilldown'}/${site.site_id}`,
      { params: { days: drillRangeDays } })
      .then(res => setDrilldown(res.data))
      .catch(() => setDrilldown(null))
      .finally(() => setDrilldownLoading(false))

    // 图表用的全量聚合统计（与明细并行请求，互不阻塞）
    // 实时告警地图场景下无历史告警，无需拉取
    if (mode === 'realtime') {
      setAnalytics(null)
    } else {
      setAnalyticsLoading(true)
      api.get(`/gis/drilldown/${site.site_id}/analytics`, { params: { days: drillRangeDays } })
        .then(res => setAnalytics(res.data))
        .catch(() => setAnalytics(null))
        .finally(() => setAnalyticsLoading(false))
    }
  }

  // 切换统计范围：仅重新拉取，不重新打开抽屉
  const handleRangeDaysChange = (days: number) => {
    setDrillRangeDays(days)
    if (!selectedSite) return
    setDrilldownLoading(true)
    api.get(`/${mode === 'realtime' ? 'gis/realtime/drilldown' : 'gis/drilldown'}/${selectedSite}`,
      { params: { days } })
      .then(res => setDrilldown(res.data))
      .catch(() => setDrilldown(null))
      .finally(() => setDrilldownLoading(false))
    if (mode !== 'realtime') {
      setAnalyticsLoading(true)
      api.get(`/gis/drilldown/${selectedSite}/analytics`, { params: { days } })
        .then(res => setAnalytics(res.data))
        .catch(() => setAnalytics(null))
        .finally(() => setAnalyticsLoading(false))
    }
  }

  const toggleLegend = (key: LegendKey) => {
    setHiddenLegends(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const getSiteCategory = (site: Site): LegendKey => {
    if (mode === 'realtime') {
      // 实时告警地图：TT/WO 由实时告警 tt_id 派生，优先着色以直观体现关联（TT/WO 颜色保持不变）
      if (activeLayers.has('tt') && (site.rt_tt_count || 0) > 0) return 'tt'
      if (activeLayers.has('wo') && (site.rt_wo_count || 0) > 0) return 'wo'
      if (activeLayers.has('rt_alarm')) {
        // 超时(当前时间 - servertime > assign_delay) => 大红；否则 => 黄
        if ((site.rt_alarm_overdue || 0) > 0) return 'rt_alarm_overdue'
        if (site.rt_alarm_count > 0) return 'rt_alarm_ontime'
      }
      if (site.vip_site === 'Y' || site.vip_site === 'Yes') return 'vip'
      return 'normal'
    }
    if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 'rt_alarm'
    if (activeLayers.has('his_alarm') && site.his_alarm_count > 0) return 'his_alarm'
    if (activeLayers.has('tt') && site.open_tt > 0) return 'tt'
    if (activeLayers.has('wo') && site.wo_count > 0) return 'wo'
    if (site.vip_site === 'Y' || site.vip_site === 'Yes') return 'vip'
    return 'normal'
  }

  const filteredSites = useMemo(() => {
    return sites.filter(site => {
      if (mode === 'realtime') {
        const cats = [
          (site.rt_alarm_overdue || 0) > 0 && 'rt_alarm_overdue',
          (site.rt_alarm_ontime || 0) > 0 && 'rt_alarm_ontime',
          (site.rt_tt_count || 0) > 0 && 'tt',
          (site.rt_wo_count || 0) > 0 && 'wo',
          (site.vip_site === 'Y' || site.vip_site === 'Yes') && 'vip',
        ].filter(Boolean) as LegendKey[]
        // rt_alarm_overdue / rt_alarm_ontime 均受 rt_alarm 图层开关控制
        const visible = cats.some(c => {
          const layer = (c === 'rt_alarm_overdue' || c === 'rt_alarm_ontime') ? 'rt_alarm' : c
          return activeLayers.has(layer as LayerKey) && !hiddenLegends.has(c)
        })
        if (!visible) return false
      } else {
        if (hiddenLegends.has(getSiteCategory(site))) return false
      }
      for (const [key, val] of Object.entries(selectedFilters)) {
        if (val && (site as any)[key] !== val) return false
      }
      return true
    })
  }, [sites, hiddenLegends, selectedFilters, activeLayers, mode])

  // ========== 导出 ==========
  /* 导出**当前地图上可见的站点**（filteredSites）：与用户在图例/图层/高级筛选里
     看到的那批点在口径上完全一致，而不是后端返回的全量 sites。
     副标题写明 可见数/总数 与当前模式，避免误读为全量。 */
  const exportSites = () => {
    if (!filteredSites.length) return
    const header = [
      t('gis.drilldown.colSiteId'), t('gis.drilldown.colSiteName'),
      t('gis.regionLabel'), t('gis.countyLabel'),
      t('gis.networkTypeLabel'), t('gis.drilldown.colSiteType'),
      t('gis.latitudeLabel'), t('gis.longitudeLabel'),
      t('gis.ttTotalLabel'), t('gis.openTtLabel'), t('gis.closedTtLabel'), t('gis.woTotalLabel'),
      t('gis.rtAlarmLabel'), t('gis.hisAlarmLabel'),
      t('gis.drilldown.colVipSite'), t('gis.drilldown.colHubSite'),
      t('gis.trmTypeLabel'), t('gis.fmeNameLabel'),
    ]
    const rows = filteredSites.map(s => [
      s.site_id, s.site_name, s.region, s.province_county,
      s.network_type, s.site_type, s.lat, s.lng,
      s.tt_count, s.open_tt, s.closed_tt, s.wo_count,
      s.rt_alarm_count, s.his_alarm_count, s.vip_site, s.hub_site,
      s.trm_type || '', s.fme_name || '',
    ])
    const modeLabel = mode === 'realtime' ? t('gis.modeRealtime') : t('gis.modeAll')
    void exportAoaReport({
      filename: `gis_sites_${mode}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'GIS Sites',
      title: `${t('nav.gis')} · ${modeLabel}`,
      subtitle: `${t('gis.totalSites')}: ${filteredSites.length}/${sites.length}`
        + `    |    ${t('gis.advancedFilter')}: ${activeFilterCount}`,
      header,
      rows,
      numericCols: [6, 7, 8, 9, 10, 11, 12, 13],
      tabColor: '#2F5496',
    })
  }

  // 记忆化：避免每次渲染都生成新数组导致 MapController 反复 setView（会重置用户的平移/缩放）
  const center = useMemo<[number, number]>(() => {    if (sites.length === 0) return LB_CENTER
    return [
      sites.reduce((s, p) => s + p.lat, 0) / sites.length,
      sites.reduce((s, p) => s + p.lng, 0) / sites.length,
    ]
  }, [sites])

  const getMarkerColor = (site: Site) => {
    const cat = getSiteCategory(site)
    switch (cat) {
      case 'rt_alarm': return SITE_COLORS.rt_alarm
      case 'rt_alarm_overdue': return SITE_COLORS.rt_alarm_overdue
      case 'rt_alarm_ontime': return SITE_COLORS.rt_alarm_ontime
      case 'his_alarm': return SITE_COLORS.his_alarm
      case 'tt': return SITE_COLORS.tt
      case 'wo': return SITE_COLORS.wo
      case 'vip': return SITE_COLORS.vip
      default: return SITE_COLORS.normal
    }
  }

  const getMarkerRadius = (site: Site) => {
    if (mode === 'realtime') {
      const ttVal = site.rt_tt_count || 0
      const woVal = site.rt_wo_count || 0
      if (activeLayers.has('tt') && ttVal > 5) return 9
      if (activeLayers.has('tt') && ttVal > 0) return 7
      if (activeLayers.has('wo') && woVal > 5) return 8
      if (activeLayers.has('wo') && woVal > 0) return 6
      if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 10
      return 4
    }
    if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 10
    if (activeLayers.has('his_alarm') && site.his_alarm_count > 5) return 9
    if (activeLayers.has('tt') && site.open_tt > 5) return 9
    if (activeLayers.has('tt') && site.open_tt > 0) return 7
    if (activeLayers.has('wo') && site.wo_count > 5) return 8
    if (activeLayers.has('wo') && site.wo_count > 0) return 6
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
    { value: 'all', label: <span style={{ color: timePreset === 'all' ? WH.teal : WH.text }}>{t('gis.timeAll')}</span> },
    { value: '7d', label: <span style={{ color: timePreset === '7d' ? WH.teal : WH.text }}>{t('gis.timeLast7')}</span> },
    { value: '30d', label: <span style={{ color: timePreset === '30d' ? WH.teal : WH.text }}>{t('gis.timeLast30')}</span> },
    { value: '90d', label: <span style={{ color: timePreset === '90d' ? WH.teal : WH.text }}>{t('gis.timeLast90')}</span> },
    { value: '180d', label: <span style={{ color: timePreset === '180d' ? WH.teal : WH.text }}>{t('gis.timeLast180')}</span> },
    { value: 'custom', label: <span style={{ color: timePreset === 'custom' ? WH.teal : WH.text }}>{t('gis.timeCustom')}</span> },
  ]

  const FILTER_CONFIG = [
    { key: 'trm_type', label: t('gis.filter.trmType') },
    { key: 'site_type', label: t('gis.filter.siteType') },
    { key: 'hubsite', label: t('gis.filter.hubSite') },
    { key: 'vip_site', label: t('gis.filter.vipSite') },
    { key: 'supervisor', label: t('gis.filter.supervisor') },
    { key: 'fme_name', label: t('gis.filter.fmeName') },
    { key: 'province_county', label: t('gis.filter.province') },
    { key: 'network_type', label: t('gis.filter.networkType') },
    { key: 'power_sources', label: t('gis.filter.powerSources') },
    { key: 'site_caregory', label: t('gis.filter.siteCategory') },
  ]

  const activeFilterCount = Object.values(selectedFilters).filter(Boolean).length

  const handleFilterChange = (key: string, value: string | undefined) => {
    setSelectedFilters(prev => ({ ...prev, [key]: value }))
  }

  const clearAllFilters = () => {
    setSelectedFilters({})
  }

  const categoryCounts = useMemo(() => {
    const counts = { tt: 0, wo: 0, vip: 0, normal: 0, rt_alarm: 0, rt_alarm_overdue: 0, rt_alarm_ontime: 0, his_alarm: 0 }
    if (mode === 'realtime') {
      sites.forEach(s => {
        if ((s.rt_alarm_overdue || 0) > 0) counts.rt_alarm_overdue++
        else if (s.rt_alarm_count > 0) counts.rt_alarm_ontime++
        if ((s.rt_tt_count || 0) > 0) counts.tt++
        if ((s.rt_wo_count || 0) > 0) counts.wo++
        if (s.vip_site === 'Y' || s.vip_site === 'Yes') counts.vip++
        else if (s.rt_alarm_count === 0 && (s.rt_tt_count || 0) === 0 && (s.rt_wo_count || 0) === 0) counts.normal++
      })
    } else {
      sites.forEach(s => {
        counts[getSiteCategory(s)]++
      })
    }
    return counts
  }, [sites, activeLayers, mode])

  // 图例 TT/WO 计数：显示工单总数（时间窗口内 eflow_tt/eflow_wo 的全部工单数），
  // 而不是“有工单的站点数”——TT 图例应等于工单总量（如 6 个月的全部 TT）
  const ticketTotals = useMemo(() => {
    if (mode === 'realtime') {
      return {
        tt: sites.reduce((s, x) => s + (x.rt_tt_count || 0), 0),
        wo: sites.reduce((s, x) => s + (x.rt_wo_count || 0), 0),
      }
    }
    return {
      tt: sites.reduce((s, x) => s + (x.tt_count || 0), 0),
      wo: sites.reduce((s, x) => s + (x.wo_count || 0), 0),
    }
  }, [sites, mode])

  /* 图例可见性（2026-09-25 修正「假 0」）：
     rt_alarm_overdue / rt_alarm_ontime 是**实时模式专属**——categoryCounts 只在
     mode==='realtime' 时给它们计数，在 ?page=gis（mode='all'）下恒为 0。
     而原实现只在 realtime 模式过滤 rt_alarm/his_alarm，这两个键在 all 模式
     没被过滤掉，于是页面上就出现「Realtime Alarm (Overdue) (0)」这种
     看起来像故障、实则是空指标的图例（用户 2026-09-25 反馈）。
     修法：按模式对称过滤——all 模式隐藏实时专属项，realtime 模式隐藏历史专属项。 */
  const legendItems: { key: LegendKey; color: string; label: string; count: number }[] = [
    { key: 'rt_alarm_overdue', color: SITE_COLORS.rt_alarm_overdue, label: t('gis.legend.rtAlarmOverdue'), count: categoryCounts.rt_alarm_overdue },
    { key: 'rt_alarm_ontime', color: SITE_COLORS.rt_alarm_ontime, label: t('gis.legend.rtAlarmOnTime'), count: categoryCounts.rt_alarm_ontime },
    { key: 'rt_alarm', color: SITE_COLORS.rt_alarm, label: t('gis.legend.rtAlarm'), count: categoryCounts.rt_alarm },
    { key: 'his_alarm', color: SITE_COLORS.his_alarm, label: t('gis.legend.hisAlarm'), count: categoryCounts.his_alarm },
    { key: 'tt', color: SITE_COLORS.tt, label: t('gis.legend.tt'), count: ticketTotals.tt },
    { key: 'wo', color: SITE_COLORS.wo, label: t('gis.legend.wo'), count: ticketTotals.wo },
    { key: 'vip', color: SITE_COLORS.vip, label: t('gis.legend.vip'), count: categoryCounts.vip },
    { key: 'normal', color: SITE_COLORS.normal, label: t('gis.legend.normal'), count: categoryCounts.normal },
  ].filter(item =>
    mode === 'realtime'
      // 实时模式：无历史告警；rt_alarm 由 overdue/ontime 两档细分取代
      ? (item.key !== 'rt_alarm' && item.key !== 'his_alarm')
      // 全量模式：无实时告警状态，Overdue/OnTime 两档无意义
      : (item.key !== 'rt_alarm_overdue' && item.key !== 'rt_alarm_ontime')
  ) as { key: LegendKey; color: string; label: string; count: number }[]

  const toggleLayer = (key: LayerKey) => {
    setActiveLayers(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const layerOptions: { key: LayerKey; label: string; color: string }[] = [
    { key: 'rt_alarm', label: t('gis.layer.rtAlarm'), color: SITE_COLORS.rt_alarm },
    { key: 'his_alarm', label: t('gis.layer.hisAlarm'), color: SITE_COLORS.his_alarm },
    { key: 'tt', label: t('gis.layer.tt'), color: '#258cff' },
    { key: 'wo', label: t('gis.layer.wo'), color: '#51cf66' },
  ].filter(lo => mode === 'realtime' ? lo.key !== 'his_alarm' : true) as { key: LayerKey; label: string; color: string }[]

  const labelStyle = { color: WH.textMuted, fontSize: '0.8125rem', fontWeight: 500 }

  // 底图深色适配：CARTO dark 瓦片现已要求 API key，不可用；采用与 MW 拓扑页一致的
  // 方案 —— 瓦片始终用 OSM，深色时对 tile-pane 施加 CSS invert 滤镜（标注反色仍可读），
  // 不引入任何外部依赖。滤镜规则见 index.css 的 .gis-dark-map。
  const mapClassName = isDark ? 'gis-dark-map' : ''

  return (
    <div style={pageWrap}>
      <Card style={controlCardStyle} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space wrap style={{ gap: 'var(--wh-space-md)' }}>
              <span style={labelStyle}>{t('gis.regionFilter')}</span>
              <Select
                value={selectedRegion}
                onChange={setSelectedRegion}
                style={{ width: 'min(100%, 12.5rem)' }}
                allowClear
                placeholder={t('gis.allRegions')}
                aria-label={t('gis.regionFilter')}
                options={regions.map(r => ({ value: r, label: `${r} (${regionStats[r] || 0})` }))}
              />
              <Tag color="cyan">{t('gis.totalSites')}: {sites.length}</Tag>
              <Tooltip title={t('datasource.lastSync')}>
                <Tag color={isSynced ? 'green' : 'red'}>
                  {isSynced ? t('datasource.synced') : t('datasource.notSynced')}
                  {isSynced && lastSync && `: ${lastSync}`}
                </Tag>
              </Tooltip>
              {mode === 'realtime' ? (
                // 实时模式：地图数据源是 realtime_alarm，显示告警同步时间（与 Alarm Dashboard 对齐），
                // 而非 TT/WO 工单创建时间，避免口径误导
                <Tooltip title={t('datasource.alarmSync')}>
                  <Tag color="geekblue">{t('datasource.alarmSync')}: {alarmLastSync || t('datasource.noData')}</Tag>
                </Tooltip>
              ) : (
                <Tooltip title={t('datasource.latestData')}>
                  <Tag color="geekblue">{t('datasource.latestData')}: {latestData}</Tag>
                </Tooltip>
              )}
              <Space style={{ gap: 'var(--wh-space-xs)' }}>
                <Switch size="small" checked={showTopology} onChange={setShowTopology} />
                <span style={{ fontSize: '0.8125rem', color: WH.text }}>{t('gis.topologyToggle')}</span>
              </Space>
              <Space style={{ gap: 'var(--wh-space-xs)' }}>
                <span style={{ fontSize: '0.8125rem', color: WH.text }}>{t('gis.boundaryMode')}</span>
                <Segmented
                  size="small"
                  value={boundaryMode}
                  onChange={(v) => setBoundaryMode(v as BoundaryMode)}
                  style={{ background: 'var(--wh-seg-bg)' }}
                  options={[
                    { value: 'none', label: t('gis.boundaryNone') },
                    { value: 'region', label: t('gis.boundaryRegion') },
                    { value: 'county', label: t('gis.boundaryCounty') },
                  ]}
                />
              </Space>
              <ExplainIcon text={t('gis.explain.note')} size={14} />
            </Space>
          </Col>
          <Col>
            <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: WH.text }}>{t('gis.layerFilter')}</span>
              {layerOptions.map(lo => (
                <Tag
                  key={lo.key}
                  color={activeLayers.has(lo.key) ? lo.color : undefined}
                  role="switch"
                  aria-checked={activeLayers.has(lo.key)}
                  aria-label={lo.label}
                  style={{
                    cursor: 'pointer',
                    opacity: activeLayers.has(lo.key) ? 1 : 0.4,
                    textDecoration: activeLayers.has(lo.key) ? 'none' : 'line-through',
                    borderRadius: 'var(--wh-radius-lg)',
                    padding: 'var(--wh-space-xs) var(--wh-space-sm)',
                    fontSize: '0.75rem',
                    transition: 'all 0.2s',
                  }}
                  onClick={() => toggleLayer(lo.key)}
                >
                  {lo.label}
                </Tag>
              ))}
            </Space>
          </Col>
          {mode !== 'realtime' && (
            <Col>
              <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
                <span style={labelStyle}>{t('gis.timeFilter')}</span>
                <Segmented
                  value={timePreset}
                  onChange={(v) => setTimePreset(v as TimePreset)}
                  options={presetOptions}
                  size="small"
                  style={{ background: 'var(--wh-seg-bg)' }}
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
          )}
          {mode === 'realtime' && (
            <Col>
              <Tag color="red" style={{ borderRadius: 'var(--wh-radius-lg)' }}>{t('gis.realtimeLive')}</Tag>
            </Col>
          )}
        </Row>
        <div style={{ marginTop: 'var(--wh-space-sm)' }}>
          {legendItems.map(item => {
            const hidden = hiddenLegends.has(item.key)
            return (
              <span
                key={item.key}
                onClick={() => toggleLegend(item.key)}
                role="switch"
                aria-checked={!hiddenLegends.has(item.key)}
                aria-label={`${item.label} (${item.count})`}
                style={{
                  cursor: 'pointer',
                  opacity: hidden ? 0.35 : 1,
                  textDecoration: hidden ? 'line-through' : 'none',
                  userSelect: 'none',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 'var(--wh-space-xs)',
                  fontSize: '0.75rem',
                  transition: 'opacity 0.2s',
                  marginRight: 'var(--wh-space-md)',
                  color: WH.text,
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
                {hidden && <span style={{ fontSize: '0.625rem', color: WH.textDim }}>({t('gis.legend.hidden')})</span>}
              </span>
            )
          })}
          {showTopology && (
            /* 图例改为按 kml_mw_links 的真实线色分组（2026-09-25 换数据源后）：
               旧 topology 表有 a_is_hub/b_is_hub，故用「Hub/普通」两档；
               kml_mw_links 没有 hub 标记，但每条线自带 color（红/黄/蓝/绿），
               按真实颜色分组比原来的二分更贴合数据本身。 */
            <>
              {KML_LINK_COLORS.map(lc => {
                const n = topologyLinks.filter(l => (l.color || '').toLowerCase() === lc.color).length
                if (n === 0) return null
                return (
                  <span key={lc.color} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--wh-space-xs)', fontSize: '0.75rem', marginRight: 'var(--wh-space-md)', color: WH.text }}>
                    <span style={{ display: 'inline-block', width: 20, height: 3, backgroundColor: lc.color, borderRadius: 2 }} />
                    {t(lc.labelKey)} ({n})
                  </span>
                )
              })}
            </>
          )}
        </div>
        <div style={{ marginTop: '0.375rem' }}>
          <span style={{ fontSize: '0.6875rem', color: WH.textDim }}>
            {t('gis.legendNote')}
          </span>
        </div>
        <div style={{ marginTop: 'var(--wh-space-sm)' }}>
          <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
            <Button
              size="small"
              type={showFilters ? 'primary' : 'default'}
              icon={<FilterOutlined />}
              onClick={() => setShowFilters(!showFilters)}
            >
              {t('gis.advancedFilter')}
              {activeFilterCount > 0 && <Badge count={activeFilterCount} size="small" style={{ marginLeft: 'var(--wh-space-xs)' }} />}
            </Button>
            {activeFilterCount > 0 && (
              <Button size="small" type="link" onClick={clearAllFilters} style={{ color: WH.teal }}>
                {t('gis.clearFilters')}
              </Button>
            )}
            {activeFilterCount > 0 && (
              <Tag color="cyan">{t('gis.totalSites')}: {filteredSites.length}/{sites.length}</Tag>
            )}
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={exportSites}
              disabled={!filteredSites.length}
            >
              {t('common.exportExcel')}
            </Button>
          </Space>
          {showFilters && (
            <Row gutter={[8, 8]} style={{ marginTop: 'var(--wh-space-sm)' }}>
              {FILTER_CONFIG.map(fc => {
                const opts = filterOptions[fc.key] || []
                if (opts.length === 0) return null
                return (
                  <Col key={fc.key}>
                    <Select
                      size="small"
                      style={{ width: 'min(100%, 8.75rem)' }}
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

      {mode === 'realtime' && ossStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, marginBottom: 'var(--wh-space-sm)' }}>
            {t('gis.ossStatsTitle')} ({ossStats.reduce((s, i) => s + i.count, 0)})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.625rem' }}>
            {ossStats.map(item => {
              const max = ossStats[0]?.count || 1
              const pct = Math.max(4, Math.round((item.count / max) * 100))
              return (
                <div key={item.oss_specific_problem} style={{ minWidth: 'min(100%, 10.625rem)', flex: '1 1 10.625rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.375rem', fontSize: '0.75rem', color: WH.text }}>
                    <span title={item.oss_specific_problem} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 'min(100%, 8.125rem)' }}>{item.oss_specific_problem}</span>
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>{item.count} / {item.sites}</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--wh-subtle-bg)', borderRadius: 3, marginTop: 3 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: WH.teal, borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* 门户内嵌时地图铺满整个区块：滚轮缩放先关掉，点击地图后才生效
          （避免门户页面滚动被地图吃掉，见 components/MapWheelZoomOnClick） */}
      <Card styles={{ body: { padding: 0 } }} style={{ ...cardStyle, overflow: 'hidden' }}>
        {loading ? (
          <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
        ) : (
          <MapContainer
            center={center}
            zoom={LB_FIT_ZOOM}
            className={mapClassName}
            style={{ height: 'calc(100vh - 290px)', width: '100%', background: 'var(--wh-page-bg)' }}
            scrollWheelZoom={!isEmbeddedInPortal()}
          >
            <MapWheelZoomOnClick />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapController center={center} zoom={LB_FIT_ZOOM} />
            <Pane name="sitePane" style={{ zIndex: 650 }} />
            {filteredSites.map(site => (
              <CircleMarker
                key={site.site_id}
                pane="sitePane"
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
                  <div style={{ minWidth: 'min(100%, 13.75rem)' }}>
                    <strong>{site.site_name}</strong> ({site.site_id})<br />
                    {t('gis.popup.region')}: {site.region}<br />
                    {t('gis.popup.type')}: {site.site_type} | {site.network_type}<br />
                    {mode === 'realtime' && activeLayers.has('rt_alarm') && site.rt_alarm_count > 0 && (
                      <span style={{ fontWeight: 600 }}>
                        ⚠ {t('gis.popup.rtAlarm')}: {site.rt_alarm_count}
                        {(site.rt_alarm_overdue || 0) > 0 && (
                          <span style={{ color: SITE_COLORS.rt_alarm_overdue }}> ({t('gis.popup.overdue')}: {site.rt_alarm_overdue})</span>
                        )}
                        {(site.rt_alarm_ontime || 0) > 0 && (
                          <span style={{ color: SITE_COLORS.rt_alarm_ontime }}> ({t('gis.popup.ontime')}: {site.rt_alarm_ontime})</span>
                        )}
                        <br />
                      </span>
                    )}
                    {mode === 'all' && activeLayers.has('rt_alarm') && site.rt_alarm_count > 0 && (
                      <span style={{ color: SITE_COLORS.rt_alarm, fontWeight: 600 }}>⚠ {t('gis.popup.rtAlarm')}: {site.rt_alarm_count}<br /></span>
                    )}
                    {mode === 'all' && activeLayers.has('his_alarm') && site.his_alarm_count > 0 && (
                      <span style={{ color: SITE_COLORS.his_alarm }}>{t('gis.popup.hisAlarm')}: {site.his_alarm_count}<br /></span>
                    )}
                    {(() => {
                      const ttVal = mode === 'realtime' ? (site.rt_tt_count || 0) : site.tt_count
                      const woVal = mode === 'realtime' ? (site.rt_wo_count || 0) : site.wo_count
                      return (
                        <>
                          {activeLayers.has('tt') && <>{t('gis.popup.tt')}: {ttVal} ({t('gis.popup.open')}: {mode === 'realtime' ? ttVal : site.open_tt})<br /></>}
                          {activeLayers.has('wo') && <>{t('gis.popup.wo')}: {woVal}<br /></>}
                        </>
                      )
                    })()}
                    <em style={{ color: '#258cff' }}>{t('gis.popup.clickDetail')}</em>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
            {boundaryMode === 'region' && regionBoundaries.map((rb, idx) => (
              <Polygon
                key={`region-${idx}`}
                positions={rb.polygon}
                pathOptions={{
                  color: rb.color,
                  fillColor: rb.color,
                  fillOpacity: isDark ? 0.12 : 0.18,
                  weight: 2,
                  opacity: 0.7,
                }}
              />
            ))}
            {boundaryMode === 'county' && counties.map(c => (
              <Polygon
                key={`county-${c.name}`}
                positions={c.polygons as any}
                eventHandlers={{ click: () => handleCountyClick(c) }}
                pathOptions={{
                  color: c.color,
                  fillColor: c.color,
                  // 用户 2026-09-25 选定「描边 + 淡色底块」：底块要淡到不干扰站点辨色，
                  // 故深色主题比浅色主题再低一档（深底上同透明度会显脏）。
                  fillOpacity: isDark ? 0.10 : 0.14,
                  weight: 1.5,
                  opacity: 0.85,
                  dashArray: '4 3',
                }}
              >
                {/* 县名常驻显示在县的中心（Leaflet permanent tooltip 自动定位到
                    Polygon 的质心）。数字口径（2026-09-25 用户要求改为告警数）：
                      显示的是该县**有实时告警的站点数**，不再是站点总数。
                      带上「告警」小字标明口径 —— 单看一个数字无法区分是站数还是告警数，
                      而两者在本页默认视图（只看实时告警）下容易混淆。
                    想看站点总数时，点该县会打开高级筛选，抽屉与图例都给得出总数。 */}
                <MapTooltip permanent direction="center" className="gis-county-label">
                  <span style={{ fontSize: '0.6875rem', fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {c.name} ({c.alarm_site_count ?? 0} {t('gis.countyAlarmUnit')})
                  </span>
                </MapTooltip>
              </Polygon>
            ))}
            {showTopology && topologyLinks.map((link, idx) => (
              <Polyline
                key={`topo-${idx}`}
                positions={[[link.lat_a, link.lng_a], [link.lat_b, link.lng_b]]}
                pathOptions={{
                  // 数据源换成 kml_mw_links 后每条线自带 color，直接采用其真实线色
                  // （红/黄/蓝/绿，与 KML 原作者标注一致）；缺色时回退蓝色。
                  color: link.color || '#0a84ff',
                  weight: 1.5,
                  opacity: 0.65,
                }}
              />
            ))}
          </MapContainer>
        )}
      </Card>

      <SiteDrilldownDrawer
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        loading={drilldownLoading}
        drilldown={drilldown}
        selectedSite={selectedSite}
        mode={mode}
        analytics={analytics}
        analyticsLoading={analyticsLoading}
        rangeDays={drillRangeDays}
        onRangeDaysChange={handleRangeDaysChange}
      />
    </div>
  )
}
