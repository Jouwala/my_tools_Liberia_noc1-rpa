import { useEffect, useState, useMemo } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Tag, Space, Badge, DatePicker, Segmented, Button } from 'antd'
import { DownloadOutlined, FilterOutlined } from '@ant-design/icons'
// 本模块用自研的 LeafletMap（原生 leaflet）取代 react-leaflet —— 后者是 Hippocratic-2.1
// 许可（非 OSI，含人权条款/仲裁/赔偿），见 components/LeafletMap.tsx 头部说明。
// ⚠️ 下面 LeafletMap 的 `Tooltip as MapTooltip` 别名必须保留：它与 antd 的 Tooltip 同名，
//    本模块只用地图内的常驻标注（县名），antd Tooltip 已随 2026-09-28 的工具栏精简一并移除。
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline, Polygon, Pane, Tooltip as MapTooltip } from '../components/LeafletMap'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import { WH, cardStyle, controlCardStyle, pageWrap, useTheme } from '../theme'
import { MapController } from './gismap/MapController'
import { SiteDrilldownDrawer } from './gismap/SiteDrilldownDrawer'
import MapLegendOverlay from './gismap/MapLegendOverlay'
import type { MapLegendRow } from './gismap/MapLegendOverlay'
import type { Site, DrilldownData, DrilldownAnalytics, TopologyLink, LegendKey, LayerKey, TimePreset, BoundaryMode, CountyBoundary, UtilMeta, SiteTypeStat } from './gismap/types'
// KML_LINK_COLORS 已不在本模块使用：利用率叠加恒开（showUtil 恒真），
// 于是「按 kml_mw_links 原色分组」的那份图例成了不可达分支，2026-09-28 随图例迁移一并删除。
// 该常量仍留在 gismap/types.ts（链路数据自带 color，那里的注释是它的说明处）。
import { SITE_COLORS, UTIL_LEVEL_COLORS, UTIL_LEVEL_ORDER, utilLevelOf } from './gismap/types'
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

/* 站点资产等级 Tag 配色（2026-09-28 新增）：ERA / COOL / NORMAL 三档。
   与 SITE_COLORS（告警状态色）**刻意分开**：这组描述的是站点等级（资产属性），
   不是当前告警状态；若沿用红/黄会让人误以为「ERA 站点在告警」。
   用中性偏冷的三种色：紫（ERA，专用站）/ 青（COOL，制冷站）/ 蓝（NORMAL，常规站）。
   未知等级（后端归一化后仍出现的新值）走 antd 默认灰 Tag，保证新数据能被看见。 */
const SITE_TYPE_TAG_COLORS: Record<string, string> = {
  ERA: 'purple',
  COOL: 'cyan',
  NORMAL: 'blue',
}

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
  /* 站点下钻抽屉里「统计范围」的天数（2026-09-28）。
     抽屉自带的独立选择器，默认 7 天 —— 与地图初始时间窗口「近7天」一致，
     所以刚打开抽屉时看到的数字与地图上的口径相同。
     但它**不跟随**地图时间窗口：改地图的时间预设不会动这个值，反之亦然。
     （曾按「跟随地图窗口」实现过，用户澄清要的是「初始显示默认的，用户可以选择其范围」，
      即抽屉要有自己的、可见可改的默认档位，故改回独立状态。） */
  const [drillRangeDays, setDrillRangeDays] = useState(7)
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
  /* MW 链路与利用率叠加：2026-09-28 按用户要求**去掉两个开关，恒为开启**。
     保留 state 而非常量：`showTopology` / `showUtil` 在渲染与请求依赖里被引用了十余处，
     改成常量要动一大片且以后想加回开关还得再拆一遍；保持可变状态成本更低，
     且语义不变（当前没有任何 UI 能把它改成 false）。 */
  const [showTopology] = useState(true)
  const [showUtil] = useState(true)
  const [topologyLinks, setTopologyLinks] = useState<TopologyLink[]>([])
  const [utilMeta, setUtilMeta] = useState<UtilMeta | null>(null)
  const [regionBoundaries, setRegionBoundaries] = useState<{ region: string; polygon: [number, number][]; color: string; site_count: number }[]>([])
  /* 边界蒙层：2026-09-28 按用户要求**去掉三选一开关，恒为 county（县界）**。
     原先是 none / region / county 三档互斥（2026-09-25 起默认 county）。
     县界是三者中信息量最大的一档：15 个县的**真实**行政边界 + 县名与告警站数常驻标签，
     且点击县界能下钻筛选。做成常开正是「Boundary 默认为 Country」的落地。
     与 showTopology 一样保留 state 形式（不写成常量）：渲染分支与下方取数 effect
     仍按状态读取，保持可变状态的改动面小于全量替换。 */
  const [boundaryMode] = useState<BoundaryMode>('county')
  const [counties, setCounties] = useState<CountyBoundary[]>([])
  /* 站点等级（ERA / COOL / NORMAL）统计：随 /gis/sites 一起下发，不额外发请求。
     口径 = **全量站点表**（827），刻意与旁边的「站点总数」对齐，而不是跟随地图上的
     可见站点数 —— 详见后端 `_site_type_stats()` 的注释。 */
  const [siteTypeStats, setSiteTypeStats] = useState<SiteTypeStat[]>([])
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
  /* 2026-09-28：原先这里用 useDataTimestamps() 取「同步时间 / 最新数据时间」两个
     Tag 显示在工具栏，按用户要求已移除（属数据源健康信息，与地图判读无关）。
     整条 hook 去掉了 —— 留着不消费会让页面每次都多跑一遍时间戳计算。 */

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
        // 站点等级统计：全量口径，与上面的 sites.length 同源，不受图例/图层隐藏影响
        if (res.data.site_type_stats) setSiteTypeStats(res.data.site_type_stats || [])
      })
      .catch(err => {
        // 不吞异常：后端 500 时明确报错，避免页面静默停留在旧数据造成“筛选不生效”假象
        console.error('[GISMap] loadSites failed:', err?.response?.status, err?.response?.data || err)
        setSites([])
      })
      .finally(() => setLoading(false))
  }

  /* 拉取 MW 链路。`showUtil` 变化时**必须重拉**（不同 query 返回的数据结构不同：
     with_util=0 时后端不返回 util/level 字段），故依赖数组含 showUtil。
     不用 cachedGet：叠加数据每 15 分钟就换一个槽位，缓存住会让页面显示过期槽位。 */
  useEffect(() => {
    if (!showTopology) return
    api.get('/gis/topology', { params: showUtil ? { with_util: 1 } : {} })
      .then(res => {
        setTopologyLinks(res.data.links || [])
        setUtilMeta(res.data.util_meta || null)
      })
      .catch(err => {
        // 不吞异常：叠加失败要能在控制台看见，界面回落为「无利用率」而非静默空白
        console.error('[GISMap] topology failed:', err?.response?.status, err?.response?.data || err)
        setTopologyLinks([])
        setUtilMeta(null)
      })
  }, [showTopology, showUtil])

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

  /* 站点下钻的时间范围（2026-09-28）。
     抽屉里是**独立**的 7/30/60/90/180 天选择器，默认 7 天 —— 与地图初始时间窗口
     「近7天」一致，所以刚打开抽屉时看到的数字与地图上的口径相同。
     但二者互不影响：改地图的时间预设不会动抽屉的值，改抽屉也不会动地图。

     为什么不「跟随地图窗口」：曾按那个口径实现过（地图切窗口就重拉抽屉、并传
     time_start/time_end 精确区间），但用户澄清要的是「初始显示默认的，用户可以选择其范围」——
     即抽屉要有**自己可见、可改、有默认值**的档位，而不是一个被地图暗中决定的隐式值。
     跟随式还有一个固有怪处：地图是「近7天」时抽屉无档可高亮（7 不在 30/60/90/180 里），
     用户看不出当前到底是几天。

     备注：后端 days 与 time_start/time_end 都支持（gis.py::_resolve_window），
     这里只用 days —— 它的语义就是「最近 N 天」，正是这个下拉要表达的。 */

  // 用户在抽屉里改天数 → 只重拉下钻数据，不重新打开抽屉
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

  const handleSiteClick = (site: Site) => {
    setSelectedSite(site.site_id)
    setDrilldownLoading(true)
    setDrawerVisible(true)
    // 每次点开都回到默认档位：上一个站点改过的天数不该带到下一个
    setDrillRangeDays(7)

    api.get(`/${mode === 'realtime' ? 'gis/realtime/drilldown' : 'gis/drilldown'}/${site.site_id}`,
      { params: { days: 7 } })
      .then(res => setDrilldown(res.data))
      .catch(() => setDrilldown(null))
      .finally(() => setDrilldownLoading(false))

    // 图表用的全量聚合统计（与明细并行请求，互不阻塞）
    // 实时告警地图场景下无历史告警，无需拉取
    if (mode === 'realtime') {
      setAnalytics(null)
    } else {
      setAnalyticsLoading(true)
      api.get(`/gis/drilldown/${site.site_id}/analytics`, { params: { days: 7 } })
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
    if (activeLayers.has('his_alarm') && hisAnyHit(site)) return 'his_alarm'
    if (site.vip_site === 'Y' || site.vip_site === 'Yes') return 'vip'
    return 'normal'
  }

  /* 「His」档命中判定：历史告警 / TT工单 / WO工单 **任一**有数据即算命中。
     2026-09-28 用户要求把原先独立的 His Alarm / TT / WO 三个图层合并成一个 His：
     运维视角下这三者都属「非实时、需要回顾的历史记录」，分成三档反而要在图例里
     来回对照。合并后站点配色语义简化为「现在有告警(RT) / 历史上出过事(His)」。
     ⚠️ 必须用 `||` 汇总三类：只要任何一类有数据，该站点就属于 His 档、
     在 His 图层开启时被画出来；漏掉任一类会让「有工单但无告警」的站点整片消失。 */
  const hisAnyHit = (site: Site): boolean =>
    site.his_alarm_count > 0 || site.open_tt > 0 || site.wo_count > 0

  /* ===== MW 链路渲染样式（利用率叠加）=====
     两条铁律：
     1. **没有利用率数据的线绝不显示成绿色**。无数据显示绿色会被读成「这条线正常」，
        而实际含义是「不知道」——运维据此漏判比不显示更危险。故 no_kpi 回退 KML 原色，
        并在悬浮提示里明写「无 KPI 数据」。
     2. 线宽也随分级递增（critical 最粗），让高利用率线在缩小的全国视图上仍能被一眼看到 ——
        只靠颜色时，1.5px 的红线在全境视图下几乎看不见。 */

  /** 链路渲染色：有 KPI 按 4 级色，无 KPI 回退 KML 原色（缺色再回退蓝色） */
  const linkColor = (l: TopologyLink): string => {
    if (showUtil) {
      const lv = l.level && l.level !== 'no_kpi' ? l.level : utilLevelOf(l.util)
      const c = UTIL_LEVEL_COLORS[lv]
      if (c) return c
    }
    return l.color || '#0a84ff'
  }

  /** 链路线宽：有 KPI 时按分级加粗，无 KPI 保持原来的 1.5 */
  const linkWeight = (l: TopologyLink): number => {
    if (!showUtil) return 1.5
    switch (l.level) {
      case 'critical': return 3.4
      case 'major': return 2.8
      case 'minor': return 1.9
      case 'healthy': return 1.5
      default: return 1.5
    }
  }

  /** 利用率数值格式化；null/非法值显示 — 而不是 0（AGENTS.md 三.6） */
  const fmtUtil = (v: number | null | undefined): string =>
    v == null || !isFinite(Number(v)) ? '—' : `${Number(v).toFixed(1)}%`

  /** 分级显示名。
       ⚠️ 刻意用 switch 返回字面量键，**不要**写成 `t('gis.utilLevel.' + lv)`：
       漏键守卫（scripts/check-i18n.mjs:130）只匹配 `t('单引号字面量')`，
       动态拼出来的键它看不见 —— 拼错时会「检查通过但界面显示 gis.utilLevel.xxx」。
       这与 AGENTS.md 三.1b 记载的 `noc.slice.` 踩坑是同一类，故沿用其显式 switch 写法。 */
  const levelLabel = (lv: string): string => {
    switch (lv) {
      case 'critical': return t('gis.utilLevel.critical')
      case 'major': return t('gis.utilLevel.major')
      case 'minor': return t('gis.utilLevel.minor')
      case 'healthy': return t('gis.utilLevel.healthy')
      default: return t('gis.utilLevel.healthy')
    }
  }

  /** 统计各分级链路数（供图例显示），仅统计有 KPI 的线 */
  const utilLevelCounts = useMemo(() => {
    const m: Record<string, number> = {}
    if (!showUtil) return m
    for (const l of topologyLinks) {
      const lv = l.level && l.level !== 'no_kpi' ? l.level : utilLevelOf(l.util)
      if (lv === 'no_kpi') continue
      m[lv] = (m[lv] || 0) + 1
    }
    return m
  }, [topologyLinks, showUtil])

  const filteredSites = useMemo(() => {
    return sites.filter(site => {
      if (mode === 'realtime') {
        /* 实时模式的可见性判定（2026-09-28 随图层合并调整）：
           全量模式的 tt / wo 图层键已并入 his_alarm，实时模式**刻意保持原样** ——
           实时模式的 tt/wo 统计来自告警的 tt_id 关联，是「当前告警带的工单」，
           与全量模式里那份历史工单口径完全不同，跟着改会改变实时页的既有表现。
           即：模式不同则图层键语义不同，这一点在下方 layerOptions 里同样体现。 */
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

  const presetOptions = [
    { value: 'all', label: <span style={{ color: timePreset === 'all' ? WH.teal : WH.text }}>{t('gis.timeAll')}</span> },
    { value: '7d', label: <span style={{ color: timePreset === '7d' ? WH.teal : WH.text }}>{t('gis.timeLast7')}</span> },
    { value: '30d', label: <span style={{ color: timePreset === '30d' ? WH.teal : WH.text }}>{t('gis.timeLast30')}</span> },
    { value: '90d', label: <span style={{ color: timePreset === '90d' ? WH.teal : WH.text }}>{t('gis.timeLast90')}</span> },
    { value: '180d', label: <span style={{ color: timePreset === '180d' ? WH.teal : WH.text }}>{t('gis.timeLast180')}</span> },
    { value: 'custom', label: <span style={{ color: timePreset === 'custom' ? WH.teal : WH.text }}>{t('gis.timeCustom')}</span> },
  ]

  const FILTER_CONFIG = [
    /* 区域（region）**并入高级筛选**（2026-09-28 用户要求）。
       它原先是一个独立常驻下拉，与高级筛选里已有的「省/县」在语义上重复 ——
       区域是大区（3 个），省/县是县（15 个），用户排查时总是两个一起用。
       并入后共用一个「高级筛选」按钮与计数徽标，工具栏少一行。
       ⚠️ region 不来自 filterOptions（后端把它单独放在 `regions` 里，
       因为它是 `_GIS_FILTER_COLS` 之外的特例列），故这里手工给它喂 options。 */
    { key: 'region', label: t('gis.regionLabel'), options: regions },
    { key: 'trm_type', label: t('gis.filter.trmType') },
    /* 站点等级（ERA/COOL/NORMAL）提到原先「站点类型」的位置（2026-09-28 用户要求：
       「过滤的站点类型要对应 RRA/COOL/NORMAL，而不是 INDOOR/OUTDOOR」）。
       它对应库里的 `site_caregory` 列，与「站点总数」旁的三个统计 Tag 同源同口径，
       所以按这里筛出来的站数会与那些 Tag 对上（实测 204/64/559，合计 827）。
       `site_type`（Indoor/Outdoor）保留在后面 —— 它是另一个维度（物理站型），
       弹窗里也会显示，不是错的，只是不该占据用户找「站点类型」时的位置。 */
    { key: 'site_caregory', label: t('gis.filter.siteCategory') },
    { key: 'site_type', label: t('gis.filter.siteType') },
    { key: 'hubsite', label: t('gis.filter.hubSite') },
    { key: 'vip_site', label: t('gis.filter.vipSite') },
    { key: 'supervisor', label: t('gis.filter.supervisor') },
    { key: 'fme_name', label: t('gis.filter.fmeName') },
    { key: 'province_county', label: t('gis.filter.province') },
    { key: 'network_type', label: t('gis.filter.networkType') },
    { key: 'power_sources', label: t('gis.filter.powerSources') },
  ]

  /* 生效筛选数：**必须把 region 算进去**。region 存在独立 state 里
     （见 FILTER_CONFIG 的说明），只数 selectedFilters 会让「选了区域」
     这个筛选状态在按钮徽标上消失，用户以为没生效。 */
  const activeFilterCount = Object.values(selectedFilters).filter(Boolean).length
    + (selectedRegion ? 1 : 0)

  const handleFilterChange = (key: string, value: string | undefined) => {
    setSelectedFilters(prev => ({ ...prev, [key]: value }))
  }

  const clearAllFilters = () => {
    setSelectedFilters({})
    // region 同样是「高级筛选」的一部分，清除时一并复位，否则按钮的徽标
    // 会一直挂着 1，看起来像清不干净
    setSelectedRegion(undefined)
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
      /* 全量模式：按合并后的四档统计（RT / His / VIP / normal）。
         his_alarm 一档现在**涵盖历史告警 + TT + WO**（见 hisAnyHit），
         故 tt / wo 不再单独计数 —— 若继续单独计数，图例会出现
         「His 100、TT 200、WO 300」这种既重复又无法相加的读数。 */
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

  /* 图例可见性（2026-09-25 修正「假 0」，2026-09-28 随图层合并调整）：
     - rt_alarm_overdue / rt_alarm_ontime 是**实时模式专属**——categoryCounts 只在
       mode==='realtime' 时给它们计数，在 ?page=gis（mode='all'）下恒为 0。
       原实现只在 realtime 模式过滤 rt_alarm/his_alarm，这两个键在 all 模式没被过滤掉，
       于是页面上出现「Realtime Alarm (Overdue) (0)」这种看着像故障、实则是空指标的
       图例（用户 2026-09-25 反馈）。修法：按模式对称过滤。
     - tt / wo 两项**只在实时模式保留**：全量模式下它们已被合并进 his_alarm 一档
       （见 hisAnyHit），再列出来会让同一批站点被数两遍。 */
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
      // 实时模式：无历史告警；rt_alarm 由 overdue/ontime 两档细分取代，TT/WO 保留
      ? (item.key !== 'rt_alarm' && item.key !== 'his_alarm')
      // 全量模式：无实时告警状态；TT/WO 已并入 His 一档
      : (item.key !== 'rt_alarm_overdue' && item.key !== 'rt_alarm_ontime'
        && item.key !== 'tt' && item.key !== 'wo')
  ) as { key: LegendKey; color: string; label: string; count: number }[]

  /* ---- 地图图例浮层的数据（2026-09-28：图例从控制卡片迁到地图上竖排）----
     这里把图例项翻译成浮层要的 MapLegendRow[]。浮层组件刻意不引 i18n，
     所有文案在此处 `t()` 好再传进去（原因见 MapLegendOverlay.tsx 头部注释）。 */
  const siteLegendRows: MapLegendRow[] = legendItems.map(item => ({
    id: item.key,
    color: item.color,
    label: item.label,
    count: item.count,
    shape: 'dot' as const,
    hidden: hiddenLegends.has(item.key),
    hiddenNote: t('gis.legend.hidden'),
    // History 一档涵盖告警/TT/WO 三类，光看名字看不出来，补个 hover 说明
    hint: item.key === 'his_alarm' ? t('gis.legend.hisAlarmHint') : undefined,
    onClick: () => toggleLegend(item.key),
  }))

  /* MW 链路利用率图例：只列**实际出现**的分级（计数 0 的不占位）。
     showUtil 恒真，故这一组恒显示；「无 KPI 数据」一档用灰色虚线示意
     「这些线没被上色」，让「为什么只有一部分线变红」在图例层面自解释。 */
  const utilLegendRows: MapLegendRow[] = [
    ...UTIL_LEVEL_ORDER.filter(lv => (utilLevelCounts[lv] || 0) > 0).map(lv => ({
      id: `util-${lv}`,
      color: UTIL_LEVEL_COLORS[lv],
      label: levelLabel(lv),
      count: utilLevelCounts[lv] || 0,
      shape: 'line' as const,
    })),
    ...(utilMeta && utilMeta.no_kpi > 0
      ? [{
        id: 'util-no-kpi',
        color: WH.textDim,
        label: t('gis.utilNoKpiLegend'),
        count: utilMeta.no_kpi,
        shape: 'dashed' as const,
      }]
      : []),
  ]

  const toggleLayer = (key: LayerKey) => {
    setActiveLayers(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  /* 图层开关（2026-09-28 用户要求）：
       全量模式 —— 只剩 **RealTime / History** 两项。原先的 His Alarm / TT / WO
                   合并成一个 History（数据口径见 hisAnyHit：历史告警 / TT / WO 任一命中）。
       实时模式 —— **保持原样**（RealTime / TT / WO）。实时页的 TT/WO 是「当前告警
                   所带工单」（由告警 tt_id 派生），是告警关联关系的直观体现，
                   不属于「历史记录」，合并进 History 会丢失这层语义。 */
  const layerOptions: { key: LayerKey; label: string; color: string }[] = (
    mode === 'realtime'
      ? [
        { key: 'rt_alarm', label: t('gis.layer.rtAlarm'), color: SITE_COLORS.rt_alarm },
        { key: 'tt', label: t('gis.layer.tt'), color: SITE_COLORS.tt },
        { key: 'wo', label: t('gis.layer.wo'), color: SITE_COLORS.wo },
      ]
      : [
        { key: 'rt_alarm', label: t('gis.layer.rtAlarm'), color: SITE_COLORS.rt_alarm },
        { key: 'his_alarm', label: t('gis.layer.hisAlarm'), color: SITE_COLORS.his_alarm },
      ]
  ) as { key: LayerKey; label: string; color: string }[]

  const labelStyle = { color: WH.textMuted, fontSize: '0.8125rem', fontWeight: 500 }

  // 底图深色适配：CARTO dark 瓦片现已要求 API key，不可用；采用与 MW 拓扑页一致的
  // 方案 —— 瓦片始终用 OSM，深色时对 tile-pane 施加 CSS invert 滤镜（标注反色仍可读），
  // 不引入任何外部依赖。滤镜规则见 index.css 的 .gis-dark-map。
  const mapClassName = isDark ? 'gis-dark-map' : ''

  /* 页面根节点改成**纵向 flex 列**（2026-09-28 用户要求「地图组件自适应铺满页面，
     现在下面有大量空白」）。

     原先地图高度写死 `calc(100vh - 290px)`，那个 290 是「页头 + 边距 + 工具栏」的
     手工估计值，而工具栏高度**会随窗口宽度变化**（窄屏时第一行的按钮/Tag 换行，
     多出一整行）。于是减多了就留白、减少了就溢出，两者不可兼得。实测：
       1600×950  地图顶 93px   290 给出 660px   实际应 857px  → 底部空 198px
       1366×768  地图顶 129px  290 给出 478px   实际应 639px  → 底部空 162px
       1920×1080 地图顶 93px   290 给出 790px   实际应 987px  → 底部空 198px
     任何固定数字都无法同时对上这三种情况。

     改成布局驱动后不再需要估算：
       - 根节点 minHeight = --wh-page-min-height（全局令牌，已含页头/边距/内边距）
       - 根节点 display:flex / flexDirection:column，工具栏卡片 flexShrink:0 保持内容高度
       - 地图卡片 flex:1 + minHeight:0，吃掉剩余的全部高度（minHeight:0 不可省，
         否则 flex 子项的 min-height:auto 会让它按内容撑开、压不下去也撑不满）
       - 地图本身 height:100%，跟着卡片走
     这样换任何分辨率、工具栏怎么换行，地图都会贴到视口底部。 */
  const rootStyle: React.CSSProperties = {
    ...pageWrap,
    display: 'flex',
    flexDirection: 'column',
    /* flex:1 不可省 —— 根节点的父级 <main class="ant-layout-content dashboard-layout-shell">
       是一个 **flex 列容器**，根节点作为它的子项默认 flex-grow:0，于是只按自己的
       min-height（--wh-page-min-height = 842px @950 视口）占高，而不是撑满 950px。
       实测：不写 flex:1 时整页止于 842px，地图底边距视口底恒为 114px（各分辨率都一样，
       因为差的就是「视口高 − 令牌算出的最小高」里那部分没被认领的空间）。
       写成 flex:1 后根节点认领全部剩余高度，地图才能贴到视口底。 */
    flex: 1,
    minHeight: 0,
  }

  return (
    <div style={rootStyle}>
      <Card style={controlCardStyle} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Row gutter={[16, 12]} align="middle">
          <Col>
            <Space wrap style={{ gap: 'var(--wh-space-md)' }}>
              {/* 2026-09-28 用户要求精简工具栏，此处移除了四样东西：
                  ① 独立的「区域筛选」下拉 —— 已并入下方「高级筛选」的区县/省份下拉；
                  ② Synced / Latest Data Time 两个同步时间 Tag —— 属数据源健康信息，
                     与地图判读无关，需要时去 Overview 页看；
                  ③ 「显示 MW 链路」「链路利用率」两个 Switch —— 恒为开启，见 showTopology/showUtil；
                  ④ 「边界」三选一 Segmented —— 恒为县界，见 boundaryMode。
                  保留「站点总数」是因为它是下面 ERA/COOL/NORMAL 分档的合计锚点。 */}
              <Tag color="cyan">{t('gis.totalSites')}: {sites.length}</Tag>
              {/* 站点等级分档统计（2026-09-28 用户要求「在旁边添加 RRA/COOL/NORMAL 的统计」）。
                  数据来自后端 site_type_stats，与上面 sites.length **同为全量口径**（827），
                  故三档之和恒等于站点总数 —— 这个可校验性是刻意保留的，
                  不要改成跟随地图可见站点数，否则两个数字对不上会被当成 bug。
                  「（用户原话是 RRA，经确认为 ERA 的笔误）」
                  每档单独上色（ERA 紫 / COOL 青 / NORMAL 蓝），与站点标记色系区分开：
                  这三档描述的是站点**资产等级**，不是告警状态，用告警的红黄会误导。 */}
              {siteTypeStats.map(st => (
                <Tag key={st.name} color={SITE_TYPE_TAG_COLORS[st.name] || 'default'}>
                  {st.name}: {st.count}
                </Tag>
              ))}
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
          {/* 高级筛选 / 清除 / 导出 Excel（2026-09-28 用户要求「放到第一行最右边，
              不要单独占一行」）。原先这三样自占一行，白白吃掉卡片的一行高度。
              用 flex:1 的空 Col 把这一组推到第一行最右；wrap 时这一组会自然落到
              下一行，窄屏（门户内嵌）不会挤爆。 */}
          <Col flex="auto" />
          <Col>
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
          </Col>
        </Row>
        {/* 高级筛选面板：按钮已上移到第一行，这里只剩展开的面板 */}
        <div>
          {showFilters && (
            <Row gutter={[8, 8]} style={{ marginTop: 'var(--wh-space-sm)' }}>
              {FILTER_CONFIG.map(fc => {
                // 区域（region）的候选值来自接口的 `regions` 字段，不在 filterOptions 里
                const opts = fc.options || filterOptions[fc.key] || []
                if (opts.length === 0) return null
                /* region 走独立状态：它最终变成 `?region=` 顶层查询参数（后端
                   `_build_filter_where` 对它与其它列的处理不同），而不是 filter_params。
                   其余列统一进 selectedFilters，由 `_attach_filter_cols` 回填的
                   站点字段做**客户端精确匹配**（见 filteredSites）。 */
                const isRegion = fc.key === 'region'
                const value = isRegion ? selectedRegion : selectedFilters[fc.key]
                return (
                  <Col key={fc.key}>
                    <Select
                      size="small"
                      style={{ width: 'min(100%, 8.75rem)' }}
                      allowClear
                      showSearch
                      placeholder={fc.label}
                      value={value}
                      onChange={(v) => (isRegion ? setSelectedRegion(v) : handleFilterChange(fc.key, v))}
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

      {/* OSS 统计卡（仅实时模式）。卡片上的 flexShrink:0 —— 根节点已是 flex 列
          （见 rootStyle），不加会被 flex 压扁；与 controlCardStyle 同理，
          理由见 theme.ts:132-138 的注释。 */}
      {mode === 'realtime' && ossStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginBottom: '0.75rem', flexShrink: 0 }}>
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

      {/* 2026-09-29 起：滚轮即缩放，门户内嵌时也一样（用户要求「鼠标在地图上滑轮
          滑动，地图能放大和缩小」）。
          改动前的写法是：scrollWheelZoom={!isEmbeddedInPortal()} + <MapWheelZoomOnClick />，
          即「内嵌时先关掉滚轮缩放，点击地图后才打开，鼠标移出又收回」。
          那是 2026-09-18 为「别把门户页面的滚动吃掉」特意做的（Leaflet 官方
          click-to-activate 模式），现已按用户要求整体撤销。
          现在两处都删掉：Leaflet 的 scrollWheelZoom 默认就是 true，无需显式传；
          辅助组件 components/MapWheelZoomOnClick.tsx 也已一并删除（原则 10：
          删除优于兼容 —— 不留 deprecated shim）。将来若要恢复该行为，
          从 git 历史取回该文件即可，不要凭空重写。 */}
      {/* body 加 position: relative —— 它是下方图例浮层的定位锚点。
          这样就不必再套一层 div 包裹地图（套了得把地图那一大段整体缩进两格，是纯噪声 diff）。 */}
      {/* flex:1 + minHeight:0 —— 见上方 rootStyle 的说明：本卡片负责吃掉
          工具栏之下剩余的全部高度，使地图贴到视口底。 */}
      <Card
        styles={{ body: { padding: 0, position: 'relative', height: '100%' } }}
        style={{ ...cardStyle, overflow: 'hidden', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
      >
        {loading ? (
          <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
        ) : (
          <>
          <MapContainer
            center={center}
            zoom={LB_FIT_ZOOM}
            className={mapClassName}
            style={{ height: '100%', width: '100%', background: 'var(--wh-page-bg)' }}
          >
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
                onClick={() => handleSiteClick(site)}
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
                onClick={() => handleCountyClick(c)}
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
                  /* 有 KPI → 4 级利用率色；无 KPI → KML 原色（红/黄/蓝/绿）。
                     两种语义并存，图例已分别说明（见上方图例区）。 */
                  color: linkColor(link),
                  weight: linkWeight(link),
                  // 有 KPI 的线更不透明，让告警线从密集底图里突出来
                  opacity: showUtil && link.level && link.level !== 'no_kpi' ? 0.9 : 0.65,
                }}
              >
                {/* 悬浮显示利用率明细（用户 2026-09-28 明确要求 Tx/Rx/最大值）。
                    用 Popup 而非 Tooltip：Popup 可点选停留，便于运维照着数值去核对；
                    Tooltip 一移开就消失，抄数字时很难用。 */}
                <Popup>
                  <div style={{ fontSize: '0.75rem', lineHeight: 1.6, minWidth: '11rem' }}>
                    <div style={{ fontWeight: 600 }}>{link.name || `${link.site_a_name}-${link.site_b_name}`}</div>
                    {link.util == null ? (
                      /* 无 KPI：明确写出「无数据」，不要让用户以为是 0% 或页面坏了。
                         同时说明原因（两端站点未在 MW KPI 数据中匹配到），
                         避免被当成 bug 反复上报。 */
                      <div style={{ color: WH.textDim }}>
                        {t('gis.utilNoKpi')}
                      </div>
                    ) : (
                      <>
                        <div>
                          {t('gis.utilMax')}: <b style={{ color: linkColor(link) }}>{fmtUtil(link.util)}</b>
                          {' '}
                          <span style={{ color: linkColor(link) }}>{levelLabel(link.level || utilLevelOf(link.util))}</span>
                        </div>
                        <div>{t('gis.utilTx')}: {fmtUtil(link.tx_util)}</div>
                        <div>{t('gis.utilRx')}: {fmtUtil(link.rx_util)}</div>
                        {link.source && link.target && (
                          <div style={{ color: WH.textDim, fontSize: '0.6875rem' }}>
                            {t('gis.utilMatchedAs')}: {link.source} → {link.target}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </Popup>
              </Polyline>
            ))}
          </MapContainer>
          {/* 图例浮层（2026-09-28 用户要求「直接在地图上显示，竖排」；位置为**左下**）。
              放在地图容器**之后**是关键：浮层 z-index 与 Leaflet 控件同为 1000，
              同层时 DOM 靠后者胜，故它压在站点圆点/县名标注之上。 */}
          <MapLegendOverlay
            title={t('gis.legendTitle')}
            rows={siteLegendRows}
            utilTitle={t('gis.utilLegendTitle')}
            utilRows={utilLegendRows}
            utilNote={showTopology && showUtil && utilMeta
              ? t('gis.utilNote', {
                matched: utilMeta.matched,
                total: utilMeta.total,
                slot: utilMeta.slot || '—',
              })
              : undefined}
            note={t('gis.legendNote')}
          />
          </>
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
        /* 下钻统计范围（2026-09-28）：抽屉自带的独立选择器，默认 7 天。
           注意 JSX 属性列表里只能用这种块注释，不能用花括号包起来的 JSX 注释写法，
           那种写法会被当成属性解析并报 TS1003。 */
        rangeDays={drillRangeDays}
        onRangeDaysChange={handleRangeDaysChange}
      />
    </div>
  )
}
