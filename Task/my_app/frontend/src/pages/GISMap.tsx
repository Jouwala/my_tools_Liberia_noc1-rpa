import { useEffect, useState, useMemo, Fragment } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Tag, Space, Badge, DatePicker, Segmented, Button } from 'antd'
import { DownloadOutlined, FilterOutlined } from '@ant-design/icons'
// 本模块用自研的 LeafletMap（原生 leaflet）取代 react-leaflet —— 后者是 Hippocratic-2.1
// 许可（非 OSI，含人权条款/仲裁/赔偿），见 components/LeafletMap.tsx 头部说明。
// ⚠️ 下面 LeafletMap 的 `Tooltip as MapTooltip` 别名必须保留：它与 antd 的 Tooltip 同名，
//    本模块只用地图内的常驻标注（县名），antd Tooltip 已随 2026-09-28 的工具栏精简一并移除。
import { MapContainer, CircleMarker, Marker, Popup, Polyline, Polygon, Pane, Tooltip as MapTooltip } from '../components/LeafletMap'
import dayjs, { Dayjs } from 'dayjs'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import { WH, cardStyle, controlCardStyle, pageWrap, useTheme } from '../theme'
import { MapController } from './gismap/MapController'
import { SiteDrilldownDrawer } from './gismap/SiteDrilldownDrawer'
import MapLegendOverlay from './gismap/MapLegendOverlay'
import RegionRankingOverlay from './gismap/RegionRankingOverlay'
import { placeCountyLabels, makeProjector } from './gismap/countyLabelLayout'
import type { MapLegendRow } from './gismap/MapLegendOverlay'
import type { Site, DrilldownData, DrilldownAnalytics, TopologyLink, LegendKey, LayerKey, TimePreset, BoundaryMode, CountyBoundary, UtilMeta, SiteTypeStat } from './gismap/types'
// KML_LINK_COLORS 已不在本模块使用：利用率叠加恒开（showUtil 恒真），
// 于是「按 kml_mw_links 原色分组」的那份图例成了不可达分支，2026-09-28 随图例迁移一并删除。
// 该常量仍留在 gismap/types.ts（链路数据自带 color，那里的注释是它的说明处）。
import { SITE_COLORS, UTIL_LEVEL_COLORS, UTIL_LEVEL_ORDER, utilLevelOf } from './gismap/types'
import { BASEMAP_PMTILES_URL, BASEMAP_ATTRIBUTION, BASEMAP_MAX_ZOOM } from './gismap/basemap'
import { PmtilesLayer } from './gismap/PmtilesLayer'
import { LayerToggleControl } from './gismap/LayerToggleControl'
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
/* 可选取景档位（2026-10-14 用户要求「能添加 7.5、8、8.5」）。
   三档都落在「看得清站点、又还认得出是哪个县」的区间里：
     · 7.5 —— 接近原先的看全视角，国土左右仍会略裁，但比 8 多看见一些
     · 8   —— 默认档（**中档**）。与上一轮「默认大一号」的结论一致
     · 8.5 —— 最大，适合看 Montserrado/Margibi 那一带的密集站点
   不上整数 7：7 就是改动前的旧档，用户已明确要「大一号」，留着反而是退路噪声。
   ⚠️ 这三个小数档位要求 Leaflet 的 zoomSnap ≤ 0.5，否则会被静默吸附成整数
   （见 LeafletMap.tsx 里 zoomSnap 的注释）。 */
const ZOOM_LEVELS = [7.5, 8, 8.5] as const

/* ⚠️ 本页原先有一个 `LB_FIT_ZOOM = 8` 常量，2026-10-14 起被 ZOOM_LEVELS + 
   zoomLevel state 取代，**已整体删除**（AGENTS.md 原则 10：删除优于兼容）。
   原先围绕它的两条取舍仍然成立、只是换了承载方式：
     · 「默认看全全境」（2026-09-25）已被「默认大一号」（2026-10-14）推翻 ——
       zoom 8 在门户中列画布下可视约 4.67°纬 × 3.13°经，装不下国土的
       4.85° × 4.40°，东西边缘必然被裁。用户明确选了「内容变大」，故如此。
       想要看全，切到 7.5 档或把 ZOOM_LEVELS 改回含 7 的数组即可。
     · 「为什么不把画布改大来两者兼得」：中列宽度由门户版式决定，不是本页能决定的。 */

/* 门户中列地图画布的**实测宽度**（像素），供县名标签避让计算投影用。
   出处：本文件上方 LB_FIT_ZOOM 的实测表（「门户中列的地图画布是窄竖条，实测 570×856」）。
   耦合提示：门户版式若改了中列宽度，这里要跟着改 —— 该值偏小会让避让过度
   （标签被推得离县太远），偏大则会让本该避让的标签被判为不冲突。 */
const PORTAL_MAP_WIDTH = 570

/* 门户中列地图画布的**实测高度**（像素），同样来自上方实测表。
   用途只有一个：把县名标签夹在地图可视范围内（见 countyLabelLayout.ts）。
   ⚠️ 该值只影响**纵向**夹取。取得过大 = 允许标签跑到下边界外，
   取得过小 = 把本该正常的标签往上挤。 */
const PORTAL_MAP_HEIGHT = 856

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

/* ========== 区域（County）告警分档与淡填充（2026-10-14） ==========

   档位由用户直接给定：「>=5 红色，<=5 黄色，1 个绿色」。据用户举的两个锚点
   （Montserrado 07 → 🔴、Nimba 05 → 🔴）可知 5 必须落在红档，于是四档为
   7+ / 5-6 / 3-4 / 1-2 / 0 —— 与用户示例里的红/橙/黄/绿/无色（0 档）逐行吻合。

   ⚠️ 颜色值必须是**十六进制实值**，不能写 WH.xxx：它们最终喂给 Leaflet 的
   SVG 渲染（Polygon 的 fillColor / stroke），canvas 与 SVG 都解析不了 CSS 变量。
   这与 types.ts 里 SITE_COLORS 的约束是同一条（AGENTS.md 三.3）。

   为什么用「橙」而不是用户原话里的「红/黄」两档：用户的排名条示例本身是
   红/橙/黄/绿四色（🔴🔴🟠🟠🟡🟢），两档无法表达排名条的颜色梯度。
   这里取用户示例的实际用色，并把 5-6 归入橙档以同时满足「>=5 红」的锚点。 */
type AlarmBand = 'critical' | 'high' | 'medium' | 'low' | 'none'

const COUNTY_BAND_COLORS: Record<AlarmBand, string> = {
  critical: '#ff4d4f',   // 7+   红
  high: '#ff922b',       // 5-6  橙
  medium: '#f6cf00',     // 3-4  黄
  low: '#52c41a',        // 1-2  绿
  none: '#9aa5b5',       // 0    灰（只用于描边，填充同样极淡）
}

/** 告警站点数 → 分档。空值按 0 处理：取不到数据显示为「无」而不是硬塞进某一档。 */
function alarmBand(n: number | null | undefined): AlarmBand {
  const v = Number(n ?? 0)
  if (!isFinite(v) || v <= 0) return 'none'
  if (v >= 7) return 'critical'
  if (v >= 5) return 'high'
  if (v >= 3) return 'medium'
  return 'low'
}

/* 区域淡填充的不透明度（用户要求「控制在 8～15% 左右，不要让区域填充成为视觉主体」）。

   ⚠️ 为什么**没有**照字面写成「深色 8% / 浅色 15%」：
   page=all 的底图是 OSM 栅格瓦片，深色主题下 index.css 对它整体做了 invert 反相
   （见 index.css 中底图字段），于是同一份半透明覆盖层在两个主题下的**对比表现是反的**——
   浅色主题下反相成亮底后同透明度会发灰显脏，深色主题下反而需要更高一点才看得出来。
   实测取值：深色 0.13 / 浅色 0.09，两者都落在用户给的 8～15% 区间内，
   且都明显低于改动前的 0.10 / 0.14 的观感强度（改前的色是高饱和色，现在改为
   按严重度分档后再压淡，视觉重心进一步让给站点圆点）。 */
const FILL_OPACITY = { dark: 0.13, light: 0.09 } as const

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
  /* 默认取景档位（2026-10-14 用户要求「能添加 7.5、8、8.5」）。
     做成 State 而不是常量，是因为用户要的是**可切换的三档**，不是又一个写死的默认值。
     初值取 ZOOM_LEVELS[1]（= 8，中档）—— 与上一轮「默认大一号」的结论一致。

     ⚠️ 必须声明在 countyLabels 之前：该 memo 依赖本值重算避让位置，
     TS 的块级作用域检查会直接拦下「先用后声明」（本轮就报过 TS2448）。

     ⚠️ 让小数档位真正生效还需要 L.map({ zoomSnap: 0.5 })，
     否则 Leaflet 会把 7.5 静默吸附成 8（见 LeafletMap.tsx 该选项的注释）。 */
  const [zoomLevel, setZoomLevel] = useState<number>(ZOOM_LEVELS[1])
  const [counties, setCounties] = useState<CountyBoundary[]>([])
  /* 站点等级（ERA / COOL / NORMAL）统计：随 /gis/sites 一起下发，不额外发请求。
     口径 = **全量站点表**（827），刻意与旁边的「站点总数」对齐，而不是跟随地图上的
     可见站点数 —— 详见后端 `_site_type_stats()` 的注释。 */
  const [siteTypeStats, setSiteTypeStats] = useState<SiteTypeStat[]>([])
  const [ossStats, setOssStats] = useState<{ oss_specific_problem: string; count: number; sites: number }[]>([])

  /* 区域排名条数据（2026-10-14 用户要求「增加一个区域排名条，放在地图右上角或左上角」）。

     设计意图（用户原话）：地图负责 **Where**，排名条负责 **How many** ——
     比让地图标签承担全部信息更专业。因此这里只做一次派生，两处共用同一份数字，
     不会出现「地图上 Lofa 04、排名条里 Lofa 3」这类对不上的情况。

     排序：告警数降序；**同数按县名升序**打破平局。平局用名称排序而不是沿用接口
     返回顺序，是为了让「排名」稳定 —— 接口返回顺序由后端 GROUP BY 决定，
     不保证跨请求一致，排名条每次刷新换序会让人以为数据变了。
     取全量 15 个县（**不截断**）：用户的示例里 0 告警的县不出现，
     这个「不显示」的判定交给下游 shouldShowRegion 统一做，而不是在这里砍数据 ——
     一旦在这里截断，将来想改成「显示全部」就得再回后端补数据。
     口径：alarm_site_count 与该县地图标签、下钻筛选完全同源（COUNT DISTINCT 站点）。 */
  const regionRanking = useMemo(() => {
    return counties
      .map(c => ({
        name: c.name,
        count: c.alarm_site_count ?? 0,
        color: COUNTY_BAND_COLORS[alarmBand(c.alarm_site_count)],
      }))
      .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name))
  }, [counties])

  /* 县名标注的**避让后锚点**（2026-10-14 用户要求「Label 重叠需要动态避让」）。

     与 regionRanking 同源（都用 alarm_site_count + alarmBand），区别只是
     这里还要几何：每个县先算面积加权质心，再按告警数降序逐个找不冲突的位置。
     算法与取舍全在 countyLabelLayout.ts 的文件头，这里只说**为什么这样调用**：

       · 用固定取景参数（LB_FIT_ZOOM + 门户中列画布宽 570）算投影，而不是读地图
         当前 zoom：本函数在渲染期跑，地图实例未必已挂载（见该模块注释）。
         本页默认就是全国视角，按默认视角避让即可覆盖常态；用户手动放大后
         标签会重新变稀，反而更不容易重叠。
       · 画布宽 570 是门户中列的实测宽度（见本文件顶部 LB_FIT_ZOOM 的实测表）。
         取宽了会让判定的重叠比实际更少，取窄了则避让过度 —— 用实测值最稳。
       · 依赖里只有 counties：分档色与告警数都从 counties 派生，没有第二个真相源。 */
  const countyLabels = useMemo(() => {
    const proj = makeProjector(zoomLevel, PORTAL_MAP_WIDTH, LB_CENTER[0], PORTAL_MAP_HEIGHT)
    return placeCountyLabels(
      counties,
      c => c.alarm_site_count ?? 0,
      proj,
    )
  }, [counties, zoomLevel])

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
  /* 地名注记开关。**默认关闭**：瓦片带 1.7 万个地名，全开时用户反馈
     「密密麻麻，什么都看不清」（2026-10-02）。开关由右上角的 LayerToggleControl
     驱动，透传给 PmtilesLayer 的 showLabels。 */
  const [showLabels, setShowLabels] = useState(false)
  /* 底图道路开关。**默认关闭**（2026-10-22 用户要求「Alarm 的 map 默认不要勾选道路图层」）。
     关闭后底图只剩水体/建筑/站点，画面更干净。透传给 PmtilesLayer。

     ⚠️ 改这里要连着改两处，否则会出现"界面显示未勾选、底图却还画着道路"：
       · PmtilesLayer.tsx 的 `showRoads = true` 形参默认值（组件级兜底）；
       · PacketLossDashboard.tsx 的同名 state（那一页是另一个入口，**同一次要求
         并未覆盖它**，故仍保持 true —— 两页默认值从此不同，是有意的，别"顺手对齐"）。
     ⚠️ 与 showLabels 同一机制：规则在构造时固化，改动靠重建图层生效，
     所以它必须进 PmtilesLayer 的依赖数组。 */
  const [showRoads, setShowRoads] = useState(false)

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

  /** 链路渲染色：4 级利用率色 + no_kpi 灰，**统一取自 UTIL_LEVEL_COLORS**。
      2026-10-02 起不再回退 KML 原色 —— 原因见 types.ts 的撞色说明
      （KML 红 #ff3b30 与 critical #ff5c6c 同色系，会让 27 条无数据线冒充严重线）。
      末尾的 `|| l.color` 仅为「level 字段缺失且色表查不到」的极端兜底，
      正常路径（含 no_kpi）都已在色表里命中，走不到这里。 */
  const linkColor = (l: TopologyLink): string => {
    if (showUtil) {
      const lv = l.level && l.level !== 'no_kpi' ? l.level : utilLevelOf(l.util)
      const c = UTIL_LEVEL_COLORS[lv]
      if (c) return c
    }
    return l.color || '#0a84ff'
  }

  /** 链路线宽：有 KPI 时按分级加粗，无 KPI 保持原来的 1.5。
      2026-10-14 用户反馈「线路有点抢视觉」，整体下调约 20%：
        critical 3.4→2.6 / major 2.8→2.2 / minor 1.9→1.6 / 无 KPI 1.5→1.2。
      改动前 844 条线里 815 条是 healthy+no_kpi，它们的线宽虽然都是 1.5，
      但**在线密度最高的区域会互相叠成一片灰网**，把站点圆点泡在里面。
      压细后站点圆点重新成为最实的那一层，链路退为「结构示意」。
      ⚠️ critical 仍保持明显比 others 粗（2.6 vs 1.2，2.2 倍差），
      降的是整体基线而不是分级对比 —— 严重线必须依旧一眼可辨。 */
  const linkWeight = (l: TopologyLink): number => {
    if (!showUtil) return 1.2
    switch (l.level) {
      case 'critical': return 2.6
      case 'major': return 2.2
      case 'minor': return 1.6
      case 'healthy': return 1.2
      default: return 1.2
    }
  }

  /* 链路不透明度：按分级分层，**颜色不变**，只用亮度差把底层线压成背景。
     2026-10-02 用户反馈「严重链路在地图上找不到」后调整，改前是
     「有 KPI 0.9 / 无 KPI 0.65」两档 —— 差值太小，且 542 条绿线
     与 12 条 critical 挤在同一亮度层。

     配额依据（2026-10-02 15:30 槽位实测 844 条）：
       critical 12 / major 7 / minor 10 / healthy 331 / no_kpi 484
     healthy 与 no_kpi 占 815 条（96.6%），它们退到背景层后，
     29 条有数据的严重+中度线才能从密集底图里浮出来。

     取值对齐 mwUmeTopology 的地理视图（该页 :1580）：
       unknown .35（本页 no_kpi .3，同为最深背景层）、其余 .55 起。
     本页比它再高一点，因为 GIS 底图比该页的纯色画布更花。
     注：该「比它更高一档」的取值已于 2026-10-14 第二轮整体下调（见函数内注释），
     现在本页反而**低于**该页基线 —— 有意为之，因为用户明确要求线路再淡一些。 */
  const linkOpacity = (l: TopologyLink): number => {
    /* 2026-10-14 第二轮回调（用户：「线路 ⚠️ 有点抢视觉，再淡一些」）：
       全线再各降约 0.1，其中 no_kpi 从 .3 降到 .22 —— 它是 484 条的绝对多数，
       「抢视觉」主要就来自这一层。critical/major 也降，是因为本次要解决的是
       **整体抢眼**，而不是「严重的太抢眼」；但降幅最小（.95→.85），
       使严重线相对背景层的对比**反而被拉大**（改前 .95 vs .3 = 3.2 倍，
       改后 .85 vs .22 = 3.9 倍）—— 淡化背景等于凸显前景。
       与 linkWeight 的压细是同一轮改动，两者叠加后线路整体退后一档。 */
    // 叠加未开启时维持改动前的原值，保证 with_util=0 的行为逐字节不变
    if (!showUtil) return 0.5
    switch (l.level) {
      case 'critical': return 0.85
      case 'major': return 0.78
      case 'minor': return 0.68
      case 'healthy': return 0.26
      default: return 0.22
    }
  }

  /* 链路虚线样式：**只有 no_kpi（无数据）画虚线**，有数据的实线。
     语义与 mwUmeTopology 一致（该页 unknown 用 '4 6' 虚线，:1581）：
     虚线 = 「这条线的数据我们不知道」，实线 = 「这条线的数据是实测的」。
     2026-10-02 与配色一起加：光靠灰色在花哨的 GIS 底图上仍可能与
     浅灰底图纹理混淆，加虚线后「无数据」在形状维度上也能一眼分辨
     （颜色 + 形状双通道编码，不依赖单一色相）。

     ⚠️ dashArray 在 Leaflet 的 Polyline 里是 pathOptions 的合法字段，
     与 mwUmeTopology 的地理视图用法一致；它的 SVG stroke-dasharray
     会被 Leaflet 原样透传。 */
  const linkDash = (l: TopologyLink): string | undefined => {
    if (!showUtil) return undefined
    const lv = l.level && l.level !== 'no_kpi' ? l.level : utilLevelOf(l.util)
    return lv === 'no_kpi' ? '4 6' : undefined
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

  /* 站点圆点描边色（2026-10-02 用户反馈「地图上的圆点不好看」）。
     ── 为什么不写死 #fff（原实现）：
        浅色主题下白边配浅色瓦片，圆点像缺了一圈；
        深色主题下底图已改为真暗色矢量配色（2026-10-02，不再有 .gis-dark-map
        反相滤镜），白边在暗底上会过分抢眼、同样糊。
        「描边的作用是把圆点从底图上抠出来」，抠不出来就等于没有描边。
     ── 为什么按主题反着挑：
        浅色底 → 用**白**边（原有的观感，凸起感）；
        深色底 → 用**近黑**边（在反相后的亮瓦片上形成暗描边，最清晰）。
     ── 为什么用字面量而不是 WH.xxx：
        这里最终传给 Leaflet 的 SVG CircleMarker（fillColor/color 走 SVG 属性），
        canvas/SVG **解析不了 CSS 变量**（同 SITE_COLORS 段头注释的约束）。
        故只能按 isDark 各写一条 rgba 实值。 */
  const markerStroke = isDark ? 'rgba(0,0,0,0.55)' : '#ffffff'

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
     showUtil 恒真，故这一组恒显示；「无 KPI 数据」一档用灰虚线示意。
     2026-10-02：no_kpi 一档的色由 WH.textDim 改为 UTIL_LEVEL_COLORS.no_kpi，
     与地图上实际画的灰线**逐值一致** —— 图例与地图不同色会让人以为
     图上那条灰线是第三种含义（该档在地图上线已改为灰虚线，见 linkColor/linkDash）。 */
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
        color: UTIL_LEVEL_COLORS.no_kpi,
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

  // 底图深色适配：已改为自托管 PMTiles 矢量瓦片，深色由 protomaps 的 DARK_THEME
  // 真配色实现，**不再使用 CSS invert 滤镜**（原滤镜连同 .gis-dark-map 类已移除，
  // 见 index.css 与 gismap/basemap.ts 文件头）。故此处不再需要 mapClassName。

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
          {/* 取景档位（2026-10-14 用户要求「能添加 7.5、8、8.5」）。
              用 Segmented 而不是 Select：只有三档，全部铺开比藏进下拉少一次点击，
              也让「当前在哪一档」始终可见 —— 排障时不用先点开才知道。
              标签由 ZOOM_LEVELS 直接 map 生成（`7.5×`），**不写死三个选项** ——
              档位数组是唯一真相源，将来加减档位不必再改 JSX 与两份字典。
              ⚠️ 每档的 label 里拼的是数字 + t() 取的后缀，不是 `t('gis.zoom.7.5')`
              这类动态键 —— 动态拼 key 会被 check:i18n 判为漏键并中断构建。 */}
          <Col>
            <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
              <span style={labelStyle} title={t('gis.zoomLevelHint')}>{t('gis.zoomLevel')}</span>
              <Segmented
                value={zoomLevel}
                onChange={(v) => setZoomLevel(v as number)}
                options={ZOOM_LEVELS.map(z => ({
                  label: `${z}${t('gis.zoomLevelSuffix')}`,
                  value: z,
                }))}
                size="small"
                style={{ background: 'var(--wh-seg-bg)' }}
              />
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
            zoom={zoomLevel}
            style={{ height: '100%', width: '100%', background: 'var(--wh-page-bg)' }}
          >
            <PmtilesLayer
              url={BASEMAP_PMTILES_URL}
              isDark={isDark}
              maxZoom={BASEMAP_MAX_ZOOM}
              showLabels={showLabels}
              showRoads={showRoads}
            />
            {/* 图层控制（右上角，避让 zoom 控件）。
                ⚠️ **必须放在 <MapContainer> 内**：它内部调 useMap() 拿 Leaflet 实例，
                放到容器外会抛「useMap 必须在 <MapContainer> 内使用」并打崩整页
                （2026-10-02 实测踩过）。定位靠 portal 落进 Leaflet 容器，
                不依赖它在父级 DOM 中的位置 —— 详见 LayerToggleControl.tsx 头部。 */}
            <LayerToggleControl
              title={t('gis.layerTitle')}
              items={[
                {
                  key: 'labels',
                  label: t('gis.layerLabels'),
                  hint: t('gis.layerLabelsHint'),
                  checked: showLabels,
                  onChange: setShowLabels,
                },
                {
                  key: 'roads',
                  label: t('gis.layerRoads'),
                  hint: t('gis.layerRoadsHint'),
                  checked: showRoads,
                  onChange: setShowRoads,
                },
              ]}
            />
            <MapController center={center} zoom={zoomLevel} />
            <Pane name="sitePane" style={{ zIndex: 650 }} />
            {/* 县名标签专用 pane（2026-10-03）：**必须高于 sitePane(650)**，
                否则站点红点会盖住标签。
                根因：Leaflet 默认 tooltipPane 的 z-index 恰好也是 650，与 sitePane
                平级 —— 平级时谁后画谁在上，DOM 顺序不保证，于是红点压住县名。
                取 670：高于 sitePane(650)、低于 popupPane(700)，保证弹窗仍在最上。
                （层级链：tile 200 < overlay 400 < shadow 500 < marker 600
                  < sitePane/tooltip 650 < countyLabel 670 < popup 700 < control 1000） */}
            <Pane name="countyLabelPane" style={{ zIndex: 670 }} />
            {filteredSites.map(site => (
              /* 超时告警站点（仅 realtime 模式的 rt_alarm_overdue 档）：在站点圆点
                 外再叠一圈只描边、不填充的"光环"，由 CSS 做呼吸动画（.gis-halo）。
                 只对这一档开 —— 它是最高优先级（已超时 SLA），且数量最少；
                 若对所有告警档都开，几百个 SVG 圆同时动画会拖垮地图（见下方注释）。
                 光环与站点圆点包在同一个 Fragment 里共用 site_id 作 key。 */
              <Fragment key={site.site_id}>
              {mode === 'realtime' && !hiddenLegends.has('rt_alarm_overdue')
                && getSiteCategory(site) === 'rt_alarm_overdue' && (
                <CircleMarker
                  pane="sitePane"
                  center={[site.lat, site.lng]}
                  radius={getMarkerRadius(site) + 4}
                  fillColor="transparent"
                  color={SITE_COLORS.rt_alarm_overdue}
                  weight={2}
                  opacity={1}
                  fillOpacity={0}
                  className="gis-halo"
                />
              )}
              <CircleMarker
                pane="sitePane"
                center={[site.lat, site.lng]}
                radius={getMarkerRadius(site)}
                fillColor={getMarkerColor(site)}
                color={markerStroke}
                weight={1.5}
                opacity={1}
                fillOpacity={1}
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
              </Fragment>
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
            {boundaryMode === 'county' && counties.map(c => {
              /* 县级告警分档（2026-10-14 用户要求「>=5 红色，<=5 黄色，1 个绿色」）。
                 档位口径：5 档与 6 档同为橙档（用户以 Montserrado 07 红 / Nimba 05 橙
                 为例给出），因此 5 必须落在橙档，不能归入黄档。
                 分档只驱动**颜色**，透明度由下方 FILL_OPACITY 统一给出。 */
              const band = alarmBand(c.alarm_site_count ?? 0)
              const fill = COUNTY_BAND_COLORS[band]
              return (
              <Polygon
                key={`county-${c.name}`}
                positions={c.polygons as any}
                onClick={() => handleCountyClick(c)}
                pathOptions={{
                  color: fill,
                  fillColor: fill,
                  /* 淡色底块（2026-10-14 用户要求）：透明度压在 8~15%，不能让区域填充
                     成为视觉主体 —— 地图的视觉重心必须是站点圆点。
                     取值依据、以及为什么**不能**照字面用「深色 8% / 浅色 15%」，
                     见下方 FILL_OPACITY 的注释（深色主题下反而要更高）。 */
                  fillOpacity: isDark ? FILL_OPACITY.dark : FILL_OPACITY.light,
                  weight: 1.5,
                  opacity: 0.85,
                  dashArray: '4 3',
                }}
              />
              )
            })}
            {/* 县名常驻标注（2026-10-14 起独立渲染，不再挂在 Polygon 上）。

                为什么从「Polygon 内的 MapTooltip」改成「独立 Marker + MapTooltip」：
                  Leaflet 的永久 tooltip 只能钉在**绑定对象自己的位置**上 —— 挂在
                  Polygon 上就必然落在多边形质心，没有第二个可选位置，也就无法避让。
                  改挂到零尺寸的 Marker 之后，锚点变成一个**可以任意指定**的坐标，
                  避让算法算出来的位置才落得下去。这是让「动态避让」得以实现的
                  结构前提，不是风格偏好。
                  Marker 是一个**零尺寸空 divIcon**（不是 opacity:0 —— 那仍会留下
                  一个可见的方块，且默认图标还要加载 marker-icon.png），
                  自身不可见、不接收点击（interactive:false），
                  点击仍由下面的 Polygon 响应（handleCountyClick）。

                标签内容（2026-10-14 第三版，用户：「去掉标签背景，只显示 BOMI.01」）：
                  只剩「县名 + 两位数字」两段纯文字，**没有底色、没有色点**。
                  底色与描边的取舍见 index.css 的 .gis-county-label；
                  色点去掉是因为它表达的严重度在**县块填充色上已经有了**，
                  同图重复编码两遍是冗余（排名条里保留色点，那里没有填充色兜底）。

                避让算法（含「夹在地图可视范围内」）见 gismap/countyLabelLayout.ts 文件头。 */}
            {boundaryMode === 'county' && countyLabels.map(lb => (
              <Marker
                key={`county-lb-${lb.name}`}
                position={[lb.lat, lb.lng]}
                interactive={false}
              >
                <MapTooltip permanent direction="center" className="gis-county-label"
                            pane="countyLabelPane">
                  <span
                    className="gis-county-tag"
                    title={t('gis.countyAlarmTip', { name: lb.name, n: lb.count })}
                  >
                    <span className="gis-county-tag__name">{lb.name.toUpperCase()}</span>
                    <span className="gis-county-tag__num">{String(lb.count).padStart(2, '0')}</span>
                  </span>
                </MapTooltip>
              </Marker>
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
                  // 不透明度按分级分层，让 815 条 healthy/no_kpi 底图线退后（见 linkOpacity）
                  opacity: linkOpacity(link),
                  // 无 KPI 的线画虚线（与 mwUmeTopology 的 unknown 同语义，见 linkDash）
                  dashArray: linkDash(link),
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
          {/* 区域排名条（2026-10-14 用户要求）。与图例浮层一样放在地图容器**之后**，
              同 z-index(1000) 时靠 DOM 顺序压过 Leaflet 的站点圆点与县名标注。
              数据来自 regionRanking（与地图填充/标签同源），
              排序与截断规则见该处注释；本组件只渲染，不取数。 */}
          <RegionRankingOverlay
            title={t('gis.rankTitle')}
            rows={regionRanking}
            hint={t('gis.rankHint')}
            emptyText={t('gis.rankEmpty')}
            maxRows={8}
            footnote={t('gis.rankFootnote', {
              n: regionRanking.filter(r => r.count > 0).length,
              total: regionRanking.length,
            })}
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
