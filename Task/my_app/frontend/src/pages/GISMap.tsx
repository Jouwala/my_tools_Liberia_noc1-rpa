import { useEffect, useState, useMemo } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Tag, Space, Badge, DatePicker, Segmented, Tooltip, Switch, Button } from 'antd'
import { FilterOutlined } from '@ant-design/icons'
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, Polygon, Pane } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import { useDataTimestamps } from '../useDataTimestamps'
import { WH, WH_COLORS, cardStyle, controlCardStyle, pageWrap } from '../theme'
import { MapController } from './gismap/MapController'
import { SiteDrilldownDrawer } from './gismap/SiteDrilldownDrawer'
import type { Site, DrilldownData, TopologyLink, LegendKey, LayerKey, TimePreset } from './gismap/types'

export default function GISMap({ mode = 'all' }: { mode?: 'all' | 'realtime' }) {
  const [sites, setSites] = useState<Site[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [selectedRegion, setSelectedRegion] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [drilldown, setDrilldown] = useState<DrilldownData | null>(null)
  const [drilldownLoading, setDrilldownLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedSite, setSelectedSite] = useState<string>('')
  const [hiddenLegends, setHiddenLegends] = useState<Set<LegendKey>>(new Set())
  const [timePreset, setTimePreset] = useState<TimePreset>(mode === 'realtime' ? 'all' : '7d')
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [showTopology, setShowTopology] = useState(false)
  const [topologyLinks, setTopologyLinks] = useState<TopologyLink[]>([])
  const [regionBoundaries, setRegionBoundaries] = useState<{ region: string; polygon: [number, number][]; color: string; site_count: number }[]>([])
  const [showRegions, setShowRegions] = useState(true)
  const [ossStats, setOssStats] = useState<{ oss_specific_problem: string; count: number; sites: number }[]>([])

  const [activeLayers, setActiveLayers] = useState<Set<LayerKey>>(
    new Set(mode === 'realtime' ? ['rt_alarm', 'tt', 'wo'] : ['rt_alarm', 'his_alarm', 'tt', 'wo'])
  )

  const [filterOptions, setFilterOptions] = useState<Record<string, string[]>>({})
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string | undefined>>({})
  const [showFilters, setShowFilters] = useState(false)
  const { t } = useI18n()
  const { lastSync, latestData, isSynced } = useDataTimestamps()

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

  const handleSiteClick = (site: Site) => {
    setSelectedSite(site.site_id)
    setDrilldownLoading(true)
    setDrawerVisible(true)

    api.get(`/${mode === 'realtime' ? 'gis/realtime/drilldown' : 'gis/drilldown'}/${site.site_id}`)
      .then(res => setDrilldown(res.data))
      .catch(() => setDrilldown(null))
      .finally(() => setDrilldownLoading(false))
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

  // 记忆化：避免每次渲染都生成新数组导致 MapController 反复 setView（会重置用户的平移/缩放）
  const center = useMemo<[number, number]>(() => {
    if (sites.length === 0) return [6.4, -9.4]
    return [
      sites.reduce((s, p) => s + p.lat, 0) / sites.length,
      sites.reduce((s, p) => s + p.lng, 0) / sites.length,
    ]
  }, [sites])

  const getMarkerColor = (site: Site) => {
    const cat = getSiteCategory(site)
    switch (cat) {
      case 'rt_alarm': return '#ff6b6b'
      case 'rt_alarm_overdue': return '#ff1e1e'
      case 'rt_alarm_ontime': return '#ffd400'
      case 'his_alarm': return '#ffa94d'
      case 'tt': return '#4fc3f7'
      case 'wo': return '#51cf66'
      case 'vip': return '#b197fc'
      default: return '#94a3b8'
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
    { key: 'area', label: t('gis.filter.area') },
    { key: 'hubsite', label: t('gis.filter.hubSite') },
    { key: 'site_information', label: t('gis.filter.siteInfo') },
    { key: 'vip_site', label: t('gis.filter.vipSite') },
    { key: 'supervisor', label: t('gis.filter.supervisor') },
    { key: 'updated_fme_name_new', label: t('gis.filter.fmeName') },
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

  const legendItems: { key: LegendKey; color: string; label: string; count: number }[] = [
    { key: 'rt_alarm_overdue', color: '#ff1e1e', label: t('gis.legend.rtAlarmOverdue'), count: categoryCounts.rt_alarm_overdue },
    { key: 'rt_alarm_ontime', color: '#ffd400', label: t('gis.legend.rtAlarmOnTime'), count: categoryCounts.rt_alarm_ontime },
    { key: 'rt_alarm', color: '#ff6b6b', label: t('gis.legend.rtAlarm'), count: categoryCounts.rt_alarm },
    { key: 'his_alarm', color: '#ffa94d', label: t('gis.legend.hisAlarm'), count: categoryCounts.his_alarm },
    { key: 'tt', color: '#4fc3f7', label: t('gis.legend.tt'), count: categoryCounts.tt },
    { key: 'wo', color: '#51cf66', label: t('gis.legend.wo'), count: categoryCounts.wo },
    { key: 'vip', color: '#b197fc', label: t('gis.legend.vip'), count: categoryCounts.vip },
    { key: 'normal', color: '#94a3b8', label: t('gis.legend.normal'), count: categoryCounts.normal },
  ].filter(item =>
    mode === 'realtime'
      ? (item.key !== 'rt_alarm' && item.key !== 'his_alarm')
      : true
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
    { key: 'rt_alarm', label: t('gis.layer.rtAlarm'), color: '#ff6b6b' },
    { key: 'his_alarm', label: t('gis.layer.hisAlarm'), color: '#ffa94d' },
    { key: 'tt', label: t('gis.layer.tt'), color: '#4fc3f7' },
    { key: 'wo', label: t('gis.layer.wo'), color: '#51cf66' },
  ].filter(lo => mode === 'realtime' ? lo.key !== 'his_alarm' : true) as { key: LayerKey; label: string; color: string }[]

  const labelStyle = { color: WH.textMuted, fontSize: 13, fontWeight: 500 }

  return (
    <div style={pageWrap}>
      <Card style={controlCardStyle} styles={{ body: { padding: 16 } }}>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space size="middle" wrap>
              <span style={labelStyle}>{t('gis.regionFilter')}</span>
              <Select
                value={selectedRegion}
                onChange={setSelectedRegion}
                style={{ width: 200 }}
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
              <Tooltip title={t('datasource.latestData')}>
                <Tag color="geekblue">{t('datasource.latestData')}: {latestData}</Tag>
              </Tooltip>
              <Space size={4}>
                <Switch size="small" checked={showTopology} onChange={setShowTopology} />
                <span style={{ fontSize: 13, color: WH.text }}>{t('gis.topologyToggle')}</span>
              </Space>
              <Space size={4}>
                <Switch size="small" checked={showRegions} onChange={setShowRegions} />
                <span style={{ fontSize: 13, color: WH.text }}>{t('gis.regionOverlay')}</span>
              </Space>
              <ExplainIcon text={t('gis.explain.note')} size={14} />
            </Space>
          </Col>
          <Col>
            <Space size="small" wrap>
              <span style={{ fontSize: 13, fontWeight: 500, color: WH.text }}>{t('gis.layerFilter')}</span>
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
          {mode !== 'realtime' && (
            <Col>
              <Space size="small" wrap>
                <span style={labelStyle}>{t('gis.timeFilter')}</span>
                <Segmented
                  value={timePreset}
                  onChange={(v) => setTimePreset(v as TimePreset)}
                  options={presetOptions}
                  size="small"
                  style={{ background: 'rgba(255,255,255,0.06)' }}
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
              <Tag color="red" style={{ borderRadius: 12 }}>{t('gis.realtimeLive')}</Tag>
            </Col>
          )}
        </Row>
        <div style={{ marginTop: 8 }}>
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
                  gap: 4,
                  fontSize: 12,
                  transition: 'opacity 0.2s',
                  marginRight: 16,
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
                {hidden && <span style={{ fontSize: 10, color: WH.textDim }}>({t('gis.legend.hidden')})</span>}
              </span>
            )
          })}
          {showTopology && (
            <>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, marginRight: 16, color: WH.text }}>
                <span style={{ display: 'inline-block', width: 20, height: 3, backgroundColor: '#ff6b6b', borderRadius: 2 }} />
                {t('gis.topologyHubLink')} ({topologyLinks.filter(l => l.is_hub_link).length})
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, marginRight: 16, color: WH.text }}>
                <span style={{ display: 'inline-block', width: 20, height: 2, backgroundColor: '#4fc3f7', borderRadius: 1 }} />
                {t('gis.topologyNormalLink')} ({topologyLinks.filter(l => !l.is_hub_link).length})
              </span>
            </>
          )}
        </div>
        <div style={{ marginTop: 6 }}>
          <span style={{ fontSize: 11, color: WH.textDim }}>
            {t('gis.legendNote')}
          </span>
        </div>
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
              <Button size="small" type="link" onClick={clearAllFilters} style={{ color: WH.teal }}>
                {t('gis.clearFilters')}
              </Button>
            )}
            {activeFilterCount > 0 && (
              <Tag color="cyan">{t('gis.totalSites')}: {filteredSites.length}/{sites.length}</Tag>
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

      {mode === 'realtime' && ossStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: WH.text, marginBottom: 8 }}>
            {t('gis.ossStatsTitle')} ({ossStats.reduce((s, i) => s + i.count, 0)})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {ossStats.map(item => {
              const max = ossStats[0]?.count || 1
              const pct = Math.max(4, Math.round((item.count / max) * 100))
              return (
                <div key={item.oss_specific_problem} style={{ minWidth: 170, flex: '1 1 170px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, fontSize: 12, color: WH.text }}>
                    <span title={item.oss_specific_problem} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 130 }}>{item.oss_specific_problem}</span>
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>{item.count} / {item.sites}</span>
                  </div>
                  <div style={{ height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, marginTop: 3 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: WH.teal, borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <Card styles={{ body: { padding: 0 } }} style={{ ...cardStyle, overflow: 'hidden' }}>
        {loading ? (
          <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
        ) : (
          <MapContainer
            center={center}
            zoom={8}
            style={{ height: 'calc(100vh - 290px)', width: '100%', background: '#0a1929' }}
            scrollWheelZoom={true}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapController center={center} zoom={8} />
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
                  <div style={{ minWidth: 220 }}>
                    <strong>{site.site_name}</strong> ({site.site_id})<br />
                    {t('gis.popup.region')}: {site.region}<br />
                    {t('gis.popup.type')}: {site.site_type} | {site.network_type}<br />
                    {mode === 'realtime' && activeLayers.has('rt_alarm') && site.rt_alarm_count > 0 && (
                      <span style={{ fontWeight: 600 }}>
                        ⚠ {t('gis.popup.rtAlarm')}: {site.rt_alarm_count}
                        {(site.rt_alarm_overdue || 0) > 0 && (
                          <span style={{ color: '#ff1e1e' }}> ({t('gis.popup.overdue')}: {site.rt_alarm_overdue})</span>
                        )}
                        {(site.rt_alarm_ontime || 0) > 0 && (
                          <span style={{ color: '#ffd400' }}> ({t('gis.popup.ontime')}: {site.rt_alarm_ontime})</span>
                        )}
                        <br />
                      </span>
                    )}
                    {mode === 'all' && activeLayers.has('rt_alarm') && site.rt_alarm_count > 0 && (
                      <span style={{ color: '#ff6b6b', fontWeight: 600 }}>⚠ {t('gis.popup.rtAlarm')}: {site.rt_alarm_count}<br /></span>
                    )}
                    {mode === 'all' && activeLayers.has('his_alarm') && site.his_alarm_count > 0 && (
                      <span style={{ color: '#ffa94d' }}>{t('gis.popup.hisAlarm')}: {site.his_alarm_count}<br /></span>
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
                    <em style={{ color: '#4fc3f7' }}>{t('gis.popup.clickDetail')}</em>
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
                  color: link.is_hub_link ? '#ff6b6b' : '#4fc3f7',
                  weight: link.is_hub_link ? 3 : 1.5,
                  opacity: 0.6,
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
      />
    </div>
  )
}
