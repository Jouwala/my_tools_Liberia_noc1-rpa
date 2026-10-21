import { useEffect, useState, useMemo, useCallback, Fragment } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Spin, Tag, Space, Badge, DatePicker, Segmented, Button, Input, Table, Alert } from 'antd'
import { DownloadOutlined, FilterOutlined, SearchOutlined, RobotOutlined } from '@ant-design/icons'
// 本模块用自研的 LeafletMap（原生 leaflet）取代 react-leaflet —— 后者是 Hippocratic-2.1
// 许可（非 OSI，含人权条款/仲裁/赔偿），见 components/LeafletMap.tsx 头部说明。
// ⚠️ 下面 LeafletMap 的 `Tooltip as MapTooltip` 别名必须保留：它与 antd 的 Tooltip 同名，
//    本模块只用地图内的常驻标注（县名），antd Tooltip 已随 2026-09-28 的工具栏精简一并移除。
// 注：Polyline 已不在本模块使用 —— MW 链路自 2026-10-19 起改由
// gismap/TopologyLayer.tsx 用 Leaflet 原生 API 批量建层（页面内 844 个
// <Polyline> 组件是单帧 1547ms 阻塞的根因），故从 import 中移除。
import { MapContainer, CircleMarker, Marker, Popup, Polygon, Pane, Tooltip as MapTooltip } from '../components/LeafletMap'
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
import type { MapLegendRow, MapLegendGroup } from './gismap/MapLegendOverlay'
import type { Site, DrilldownData, DrilldownAnalytics, TopologyLink, LegendKey, LayerKey, TimePreset, BoundaryMode, CountyBoundary, UtilMeta, SiteTypeStat, RealtimeAlarmRow, RcaCluster, RcaMeta } from './gismap/types'
// KML_LINK_COLORS 已不在本模块使用：利用率叠加恒开（showUtil 恒真），
// 于是「按 kml_mw_links 原色分组」的那份图例成了不可达分支，2026-09-28 随图例迁移一并删除。
// 该常量仍留在 gismap/types.ts（链路数据自带 color，那里的注释是它的说明处）。
import { SITE_COLORS, UTIL_LEVEL_COLORS, UTIL_LEVEL_ORDER, utilLevelOf } from './gismap/types'
import { BASEMAP_PMTILES_URL, BASEMAP_ATTRIBUTION, BASEMAP_MAX_ZOOM } from './gismap/basemap'
import { PmtilesLayer } from './gismap/PmtilesLayer'
// MW 链路批量图层（2026-10-19）：844 条线改用 Leaflet 原生批量建层，
// 原因与实测数据见该文件头注释（原 844 个 <Polyline> 造成单帧 1547ms 阻塞）。
import { TopologyLayer } from './gismap/TopologyLayer'
import { LayerToggleControl } from './gismap/LayerToggleControl'
import { MapOverlayToggle } from './gismap/MapOverlayToggle'
import { PersonnelLayer, PersonnelToggleButton } from './gismap/PersonnelLayer'
import { exportAoaReport } from '../utils/excelReport'
import DraggableClickModal from '../components/DraggableClickModal'
import { fmtTs } from './gismap/helpers'

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

/* TT 优先级（ticket_severity）的进度条色阶（2026-10-16 新增卡）。
   P1 红 → P2 橙 → P3 黄 → P4 蓝，Unknown 灰 —— 由高到低的暖→冷梯度，
   让「最严重的那条」在竖排卡片里一眼可辨。

   ⚠️ 必须用**十六进制实值**，不能写 WH.xxx：与上面 SITE_TYPE_TAG_COLORS、
   COUNTY_BAND_COLORS 同一约束 —— 这些值最终进的是内联 style 的 background，
   虽然这里并非 canvas，但保持与全页一致的做法，避免有人误以为可以混用令牌。
   （ECharts/canvas 那条约束见 AGENTS.md 三.3；这里是为了一致性。） */
const PRIORITY_COLORS: Record<string, string> = {
  P1: '#ff4d4f',
  P2: '#ff922b',
  P3: '#f6cf00',
  P4: '#4dabf7',
  Unknown: '#9aa5b5',
}

/* ===== RCA 标签映射（2026-10-21）=====
   显式 switch 返回**字面量键**：动态拼 key（如 'gis.rca.cause.' + s）会被
   check:i18n 守卫读成不存在的键名而拦截（见 AGENTS.md 三.1b 与 NocAnalyst
   sliceLabelKey 的同类案例）。新增 cause 档位时在这里加 case + i18n 两处字典。 */
function rcaCauseLabelKey(c: string): string {
  switch (c) {
    case 'transmission': return 'gis.rca.cause.transmission'
    case 'fiber': return 'gis.rca.cause.fiber'
    case 'power': return 'gis.rca.cause.power'
    case 'site_outage': return 'gis.rca.cause.site_outage'
    default: return 'gis.rca.cause.other'
  }
}

function rcaKindLabelKey(k: string): string {
  switch (k) {
    case 'topology': return 'gis.rca.kind.topology'
    default: return 'gis.rca.kind.same_cause'
  }
}

/* cause → antd Tag 预设色名（Tag 要色板名而非十六进制，与优先级列同款约束）。
   传输=青、光纤=紫、电源=橙、断站=红、其它=灰 —— 语义族与告警族色系错开。 */
function rcaCauseTagColor(c: string): string {
  switch (c) {
    case 'transmission': return 'cyan'
    case 'fiber': return 'purple'
    case 'power': return 'orange'
    case 'site_outage': return 'red'
    default: return 'default'
  }
}

/* ===== 图例配色（2026-10-17 重新设计）=====

   用户反馈「图例总是不好区分」。原来的 SITE_COLORS 是**六个互不相干的色相**
   （大红/黄/灰/蓝/绿/紫），色相之间没有亲疏关系 —— 读者只能逐行看文字。

   现在按**语义族**重新分配色相，同族用同色相不同深浅：
     · 告警族（红橙）  overdue 深红 / ontime 橙 / rt_alarm 中红
     · 工单族（蓝青）  tt 蓝 / wo 青
     · 其它            vip 紫（重要但非告警）、normal 灰（无状态）
   这样「同组=同族色」本身就是线索，不必读字。

   ⚠️ 关键约束：**这份配色必须与地图上实际画的圆点同源**，否则图例骗人。
      因此 GISMap 里站点圆点的 getMarkerColor 也改为走 colorFor()，
      而不是直接读 SITE_COLORS —— 见该函数。
   ⚠️ 值必须是十六进制实值：它们要喂给 Leaflet 的 SVG（fillColor），
      解析不了 CSS 变量（与 SITE_COLORS 段头注释同一约束）。 */
const LEGEND_COLORS: Record<string, string> = {
  rt_alarm_overdue: '#e03131',   // 深红：SLA 已超时（最紧急）
  rt_alarm_ontime: '#ff922b',    // 橙：在 SLA 内
  rt_alarm: '#ff6b6b',           // 中红：全量模式的实时告警档
  his_alarm: '#868e96',          // 灰：历史
  tt: '#4dabf7',                 // 蓝
  wo: '#20c997',                 // 青
  vip: '#9775fa',                // 紫：重要站点（与告警状态无关）
  normal: '#adb5bd',             // 浅灰：无任何状态
}

/* 取图例/站点圆点色。集中一处，保证「图例色 == 地图点色」。
   未知 key 回落到 SITE_COLORS.normal（与改动前一致，不臆造颜色）。 */
const colorFor = (key: string): string => LEGEND_COLORS[key] || SITE_COLORS.normal

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

/* 取景水平位移量（像素，**正值 = 内容右移**）。用于让开贴左缘的浮层。

   ---- 2026-10-15（本次，符号反转：左移 → 右移 73px ≈ 画布 10%）----
   用户要求：「地图被图例遮挡，把地图向右移动一点」。
   起因是**同一天浮层整体换边**：用户要求「图例全部放到左边」，
   LayerToggleControl 与 RegionRankingOverlay 都由 right:10 改为 left:10 贴左缘
   （见各组件文件头的记录）。遮挡源因此从「右边缘」变成「左边缘」——
   实测（Playwright，视口 1600×1000 / 中列画布 **730×858**，坐标相对画布左缘）：
     · #gis-layers-panel（图层面板）   x  10..142  y  10..78
     · .gis-rank-overlay（区域排名条） x  10..253  y  86..347  ← 主要遮挡源
     · .gis-legend-overlay（图例）     x   8..219  y 698..824
   站点圆点（**只取 .leaflet-site-pane**，别用 [style*=650] 那类宽选择器 ——
   它会把 .leaflet-overlay-pane 的县界多边形一起算进来，实测虚增 162 个"点"）
   在不位移时横跨 x 81..763，其中 **8 个**落在区域排名条（x≤253）之下。

   取 73（≈画布 10%）的依据 —— **用户在页面上直接观察后拍板此值**：
     ·   0（不位移）→ 被压 8（含多个红色实时告警点），东侧已被切 6
     ·  -73（10%）  → 被压 3 ← **本次取值**（用户「10% 就正好」）
     · -110（15%）  → 被压 2
     · -130（18%）  → 被压 1
     · -172（≈24%） → 被压 0，但东侧切到 14 —— 用户认为 25% 那档「移动得太多」
   ⚠️ 这是**用户的视觉判断优先于「遮挡归零」**的结果，不是测量失误：
     10% 下面板右下角仍压着 3 个点（x 180..203 / y 300..345，含红色告警点）。
     要彻底归零需右移约 24%，而那会明显切掉东缘。以下硬约束解释了为什么
     二者不可兼得，**别再试图找一个"都满足"的值**：
       zoom 8 下国土像素宽约 **682px**，画布仅 730px，左侧面板又占 253px，
       682+253 > 730 —— 算术上无法共存。
     若将来要两者兼得，出路是**降一档缩放**（实测 zoom 7.5 时国土跨度降到
     341px，可完全装下）或**缩窄 .gis-rank-overlay**，而不是继续调这个位移值。
     想复测请用 TMP/_probe_v2_measure.py（输出 covered / clipped / xRange）。

   ⚠️⚠️ 方向别凭直觉猜：本常量对应 MapController 的 `map.panBy([v, 0])`，
   而 **panBy 的 x 是「视图中心移动的向量」**，与「内容移动方向」相反 ——
   传**负** x = 视图中心西移 = **内容右移**（正是本次要的效果）。
   2026-10-13 那轮要「内容左移」时传的是正 x（当时的用法），
   方向标定见 MapController 文件内的屏幕坐标实测表。

   ---- 2026-10-13（历史：左移 205，现已推翻）----
   当时用户要求「把地图向左移动，避免被**右边**的统计遮挡」，浮层在右侧
   （排名条 x 477..720），故取 205 左移。该前提已随浮层换边失效，勿据此回改。

   ⚠️ 该值只影响**平移**，不改 zoom，也不改 center 的算法。
   门户中列宽度改了（见 PORTAL_MAP_WIDTH 的耦合提示）就要重新实测这个值 ——
   偏大时国土被推出右边界，偏小时西侧仍被浮层压住。
   ⚠️ 改本值时**必须同步**看 gismap/countyLabelLayout.ts 的 shiftWestPx ——
   县名标签的锚点是按「平移后」的坐标算的，两处用的是同一个常量
   （该参数语义为「正值 = 内容左移」= 本常量的**相反数**）。

   ⚠️⚠️ 2026-10-15 追加：本值**只在 v2 门户内嵌时生效**（见 isPortalGisShift）。
      直开 /myapp/?page=gis 与 MsPortal / olbrportal / v1 三个壳的内嵌一律传 0，
      地图落在内层页自己的**居中**取景。原因：这里是「避让 v2 门户左侧那两条
      面板」的补偿量，只有 v2 的版式需要它；对没有该面板的入口平移是纯损失。
      用法见下方组件内的 shiftWestPx = embedded ? SHIFT_WEST_PX : 0。 */
const SHIFT_WEST_PX = -73

/* 取景垂直位移量（像素，**正值 = 内容上移**）。2026-10-15 用户要求「地图向上平移 3%」。
   3% 按画布高度 858px 折算 ≈ **26px**（见 PORTAL_MAP_HEIGHT / 实测画布 730×858）。
   语义与 SHIFT_WEST_PX 对称，直接喂给 MapController 的 panBy y 分量：
     正值 = 内容上移（对应 panBy 传正 y，方向标定见 MapController 注释）。
   ⚠️ 县名标签的纵向锚点**未**接入本值（countyLabelLayout 的 to() 只管 x 的平移）；
   26px 的纵向偏差远小于标签自身高度（18px）以外的容差，暂不处理 ——
   若将来纵向位移量级变大（>40px），需像 x 那样把 y 也喂进 makeProjector。
   ⚠️ 与 SHIFT_WEST_PX 同一口径：**只在 v2 门户内嵌时生效**，其余入口传 0。 */
const SHIFT_SOUTH_PX = 26

/**
 * 是否处于 v2 门户（/v2/olbrportal/）的 gis 内嵌上下文 —— 决定要不要施加上述位移。
 *
 * 判据是 **v2 专属**的 `?gisShift=1`（由该壳的 mapItems() 拼进 iframe src）。
 * ⚠️ 刻意**不用** `mwembed=1`、也不用 `isShellLessEmbed()` 那类「是否被无外壳嵌入」的
 *    判据：实测 **v2 / MsPortal / olbrportal(根) / v1 四个壳内嵌 gis 时全都带
 *    mwembed=1**，据它判定会让另外三个壳一起被平移，那些壳未必有 v2 的左侧面板。
 *    这条教训 EmailReports.tsx 的 isPortalFilesMode 已经记过一次，同因同果。
 * 一次性求值：URL 在页面生命周期内不变，且平移只在挂载/center 变化时重算。
 */
function isPortalGisShift(): boolean {
  try { return new URLSearchParams(window.location.search).get('gisShift') === '1' }
  catch { return false }
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

/** 县名的**比较键**（2026-10-21 新增）：去首尾空白 + 内部连续空白压成一个 + 转小写。

   为什么需要它：站点表的 `province_county` 与县界文件的 `db_name` 存在
   **大小写与空格不一致**的写法（库里同时有 'River Cess' 与 'River cess'，
   而县界文件里是 'River Cess'）。后端在 /county-boundaries 里用同一套
   归一化规则（`re.sub(r"\s+", " ", name.strip()).lower()`）对齐了两边 ——
   前端这里必须**用同一套规则**，否则按筛选后的站点归组时会漏掉 'River cess'。

   ⚠️ 不要改成更「宽松」的比较（如去掉所有空格）：那会让 'River Cess' 与
   'RiverCess' 合并，而它们在库里是**不同的县名写法**，合并会算错。 */
function countyKey(name: unknown): string {
  return String(name ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
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
  /* 是否施加「避让 v2 门户左侧面板」的平移。一次性求值（URL 不变），
     非 v2 内嵌时两个位移量都是 0，地图保持内层页自己的居中取景。 */
  const [shiftEnabled] = useState(isPortalGisShift)
  const shiftWestPx = shiftEnabled ? SHIFT_WEST_PX : 0
  const shiftSouthPx = shiftEnabled ? SHIFT_SOUTH_PX : 0
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
  /* 人员图层开关（2026-10-16）。只在 mode==='all'（gis 页）可用 ——
     realtime_alarm 页不挂该图层（用户明确要求「只在 gis 页」）。
     **默认开启**（2026-10-16 用户要求「默认显示」）。
     状态放在这里（而非 PersonnelLayer 内部）是因为开关按钮在工具栏、
     小人在地图里，两处 DOM 位置不同，需要共同的父级持有状态。 */
  const [showPersonnel, setShowPersonnel] = useState(true)
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
  const [ossStats, setOssStats] = useState<{ oss_specific_problem: string; count: number; with_tt: number; sites: number }[]>([])
  /* 按 TT 优先级统计（2026-10-16 用户要求）。
     后端在 priority_stats 里给出**有序**的档位（P1→P4→Unknown），
     前端只负责渲染，不再自行排序 —— 顺序即业务优先级，不该由前端猜。 */
  const [priorityStats, setPriorityStats] = useState<{ priority: string; count: number }[]>([])
  const [priorityTotal, setPriorityTotal] = useState(0)
  /* 每条实时告警一行（2026-10-21 用户要求「筛选时统计卡片跟着变化」）。

     为什么需要它：OSS 类别（SITE OUTAGE / Fiber Break…）与 TT 优先级（P1~P4）
     都是**告警级**属性，而地图站点对象上只有「该站共有几条告警」这种汇总值，
     没有按类别拆分的字段。后端把每条告警的 site_id / 类别 / TT / 优先级下发，
     前端就能按**当前筛选后可见的站点集合**重新分桶，卡片数字与地图上看到的东西
     因此不可能不一致（同一份数据、同一个 filterSites，两处读数必然相等）。

     空数组 = 未拿到（首次加载前）。此时三张卡回落到后端下发的汇总值，
     保证「没筛选也能看」，不会退化成空白。 */
  const [alarmRows, setAlarmRows] = useState<RealtimeAlarmRow[]>([])

  /* ===== 根因聚合分析（RCA，2026-10-21 用户需求）=====

     「高级筛选能不能结合网络拓扑做聚合的根因分析，快速给出一批断站的相同原因」。
     后端 GET /gis/realtime/rca：与 /gis/realtime/sites **同一次扫描**（realtime_alarm
     每 30 分钟整表重建，独立请求会跨代），把当前筛选范围内的断站聚成
     · topology   上游站断 → 其 link_path 下挂站跟着断（最深告警祖先归属）
     · same_cause 无链路站（卫星站等）按「告警问题 + 10 分钟窗」聚集
     两类簇，eFlow 的 impact_site_list 命中成员时作为佐证提升置信度。

     筛选口径：高级筛选是**纯前端行为**（loadSites 只发 region），所以这里
     把 selectedFilters + selectedRegion + 站名过滤显式传给后端、由后端复算 ——
     与地图看到的站点集合同一套参数，卡片数字与地图可对拍。

     根因站可以落在筛选范围外（root_in_scope=false）：断站原因往往在视野之外，
     这正是根因分析的价值，显示并加「范围外」标注（用户已确认）。 */
  const [rcaClusters, setRcaClusters] = useState<RcaCluster[]>([])
  const [rcaMeta, setRcaMeta] = useState<RcaMeta | null>(null)
  const [rcaLoading, setRcaLoading] = useState(false)
  const [rcaError, setRcaError] = useState('')
  /* 未归因站的**告警明细行**（2026-10-21b）：随 /realtime/rca 响应一并返回，
     行结构与 /realtime/oss-alarms 下钻完全同形 —— 未归因弹窗因此直接复用
     项目默认告警明细列（用户要求，与 Alarm Stats 条目下钻同一张表）。
     同源：与卡片脚注"未归因 N 站"出自同一次响应，数字必然一致。 */
  const [rcaUncoveredAlarms, setRcaUncoveredAlarms] = useState<any[]>([])
  const [rcaUncoveredTruncated, setRcaUncoveredTruncated] = useState(false)

  /* RCA 的 AI 解读弹窗（与 DataAgentBar 共用 localStorage 键：同一 provider 的
     key / base_url 在两处只填一次）。key 只存本机、只随 POST 体发送（后端不落盘）。 */
  const [rcaAiOpen, setRcaAiOpen] = useState(false)
  const [rcaAiAnchor, setRcaAiAnchor] = useState<{ x: number; y: number } | null>(null)
  const [rcaAiProvider, setRcaAiProvider] = useState(
    () => localStorage.getItem('myapp-data-agent-provider') || 'deepseek')
  const [rcaAiKey, setRcaAiKey] = useState(
    () => localStorage.getItem('myapp-data-agent-key-' + (localStorage.getItem('myapp-data-agent-provider') || 'deepseek')) || '')
  const [rcaAiBaseUrl, setRcaAiBaseUrl] = useState(
    () => localStorage.getItem('myapp-data-agent-baseurl-' + (localStorage.getItem('myapp-data-agent-provider') || 'deepseek')) || '')
  const [rcaAiModel, setRcaAiModel] = useState('')
  const [rcaAiText, setRcaAiText] = useState('')
  const [rcaAiNote, setRcaAiNote] = useState('')
  const [rcaAiLoading, setRcaAiLoading] = useState(false)

  /* ===== 告警明细下钻弹窗（2026-10-16）=====
     两个卡共用**同一个**弹窗：OSS 类别卡点开是「该类别下的告警」，
     优先级卡点开是「该优先级下的告警」。两者的行结构、列、导出、搜索完全一致，
     仅取数端点与标题不同，故用一组 state + 一个 kind 复用，而不是复制两套
     （AGENTS.md 三.7：不为外形相似而过早抽象，但这里是**同一个真实用例的两次实例**，
      且如果再复制一份就是 6 个 state + 2 个 handler 的重复）。

     kind: 'oss' | 'priority' —— 决定请求哪个端点、标题怎么显示。 */
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillKind, setDrillKind] = useState<'oss' | 'priority' | 'rca' | 'rca_uncovered'>('oss')
  // 标题里的主体（OSS 类别名 / 优先级档位），如 'SITE OUTAGE DUE TO POWER OFF' 或 'P3'
  const [drillKey, setDrillKey] = useState('')
  const [drillRows, setDrillRows] = useState<any[]>([])
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillTruncated, setDrillTruncated] = useState(false)
  const [drillSearch, setDrillSearch] = useState('')

  /* 打开下钻：kind 决定端点与参数。e.clientX/Y 让弹窗落在点击处
     （DraggableClickModal 的既定行为，与 AlarmDashboard 一致）。
     kind='rca'（根因簇下钻）与 'rca_uncovered'（未归因告警明细）**都不发请求** ——
     前者取 rcaClusters、后者取 rcaUncoveredAlarms（都来自同一次 /realtime/rca
     响应），直接 set 行，天然同源（AGENTS.md 三.1b）。未归因行是**告警明细行**
     （与 oss 下钻同形），所以列定义走默认的 drillColumns。 */
  const openDrill = (kind: 'oss' | 'priority' | 'rca' | 'rca_uncovered', key: string, e: React.MouseEvent) => {
    setDrillKind(kind)
    setDrillKey(key)
    setDrillAnchor({ x: e.clientX, y: e.clientY })
    setDrillSearch('')
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillRows([])
    setDrillTruncated(false)
    if (kind === 'rca') {
      const c = rcaClusters.find(x => x.cluster_id === key)
      setDrillRows(c ? c.members : [])
      setDrillLoading(false)
      return
    }
    if (kind === 'rca_uncovered') {
      setDrillRows(rcaUncoveredAlarms)
      setDrillTruncated(rcaUncoveredTruncated)
      setDrillLoading(false)
      return
    }
    const url = kind === 'oss' ? '/gis/realtime/oss-alarms' : '/gis/realtime/priority-alarms'
    const params = kind === 'oss' ? { problem: key } : { priority: key }
    api.get(url, { params })
      .then(res => {
        setDrillRows(res.data.data || [])
        setDrillTruncated(!!res.data.truncated)
      })
      .catch(err => {
        // 不吞异常：下钻失败要能在控制台看见，界面回落为空表
        console.error(`[GISMap] ${kind} drilldown failed:`, err?.response?.status, err?.response?.data || err)
        setDrillRows([])
      })
      .finally(() => setDrillLoading(false))
  }

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
  /* 站点名筛选（2026-10-21 用户要求「高级筛选里添加站点名字的过滤」）。

     为什么单独一个 state、而不是塞进 selectedFilters：
       ① 站点名是**文本输入**而不是下拉枚举 —— 站点有 800+ 个，把候选值全部
          下发会让 `filter_options` 体积翻几倍，且下拉里翻找一个站名比输入更慢；
       ② 匹配口径不同：其余筛选项是**精确相等**（`site[key] !== val`），
          站点名改用**不区分大小写的子串匹配**（站点名里有空格/括号/大小写差异，
          用户只记得 "Marshall" 时应当能命中 "Qcell LMTI (Marshall)"）；
       ③ 它不进 `selectedFilters`，也就不会被 `visiblePersonNames` 的
          「人员维度优先」分支误判（fme_name / supervisor 才是人员维度）。

     `siteNameQuery` 是**输入框里的原文**（未 trim），`siteNameFilter` 是
     **规范化后的生效值**（trim + 小写）。两者分离是为了让输入框保持
     "用户正在输入的原文"，而匹配用的是稳定口径。 */
  const [siteNameQuery, setSiteNameQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  /* 地名注记开关。**默认关闭**：瓦片带 1.7 万个地名，全开时用户反馈
     「密密麻麻，什么都看不清」（2026-10-02）。开关由右上角的 LayerToggleControl
     驱动，透传给 PmtilesLayer 的 showLabels。 */
  const [showLabels, setShowLabels] = useState(false)
  /* MW 利用率**图例组**的显隐（2026-10-26 用户要求「地图图例不显示 MW Link
     Utilization 的，弄个按钮放到 Zoom: 右边，并且默认不显示」）。

     ⚠️ 只控制**图例浮层里那一组条目**，不控制地图上的链路：链路仍由 showUtil/showTopology
     决定（恒真），照画不误。这与上面 gis.utilToggle 的历史语义（是否叠加利用率数据）
     是两件事，故不复用那个键（见 i18n 字典里 gis.utilLegendToggle 的注释）。
     ⚠️ 依赖 showUtil 的那个取数 effect **不受本状态影响**：用户「默认不显示图例」
     不等于「不要数据」，若把它并进依赖数组，默认态下就不会请求 with_util=1，
     链路会退化成无 KPI 灰虚线 —— 那是功能缺失，不是视觉偏好。 */
  const [showUtilLegend, setShowUtilLegend] = useState(false)
  /* 底图道路开关。**默认关闭**（2026-10-22 用户要求「Alarm 的 map 默认不要勾选道路图层」）。
     关闭后底图只剩水体/建筑/站点，画面更干净。透传给 PmtilesLayer。

     ⚠️ 改这里要连着改两处，否则会出现"界面显示未勾选、底图却还画着道路"：
       · PmtilesLayer.tsx 的 `showRoads = true` 形参默认值（组件级兜底）；
       · PacketLossDashboard.tsx 的同名 state（那一页是另一个入口，**同一次要求
         并未覆盖它**，故仍保持 true —— 两页默认值从此不同，是有意的，别"顺手对齐"）。
     ⚠️ 与 showLabels 同一机制：规则在构造时固化，改动靠重建图层生效，
     所以它必须进 PmtilesLayer 的依赖数组。 */
  const [showRoads, setShowRoads] = useState(false)

  const { t, locale } = useI18n()
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
          const sum = res.data.realtime_alarm_summary
          setOssStats(sum.oss_problem_stats || [])
          const pst = sum.priority_stats
          setPriorityStats(pst?.rows || [])
          setPriorityTotal(pst?.total || 0)
          /* 告警明细行：统计卡跟随筛选的依据（2026-10-21）。
             ⚠️ 字段缺失（旧后端 / 缓存里的旧响应）时置空数组而不是 undefined，
             前端的派生逻辑据此回落到后端汇总值，界面照常可用。 */
          setAlarmRows(sum.alarm_rows || [])
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

  /* ===== RCA 取数（2026-10-21）=====

     触发条件：仅实时模式；高级筛选 / 区域 / 站名过滤任一变化即重算。
     站名输入做 300ms 防抖（打字过程不逐字符打后端）。

     ⚠️ 不走 cachedGet：根因簇必须与「当前地图代」一致 —— realtime_alarm 每 30 分钟
     整表重建，若命中缓存跨了重建点，簇成员与地图点位会来自两代快照。
     ⚠️ loadSites 的缓存键里没有筛选参数（筛选是客户端行为），本请求把筛选
     参数显式发给后端复算，两边是同一套参数语义（见 state 块注释）。 */
  const loadRca = () => {
    setRcaLoading(true)
    setRcaError('')
    const params: Record<string, string> = {}
    Object.entries(selectedFilters).forEach(([k, v]) => { if (v) params[k] = v })
    if (selectedRegion) params.region = selectedRegion
    const nm = siteNameQuery.trim()
    if (nm) params.site_name = nm
    api.get('/gis/realtime/rca', { params })
      .then(res => {
        setRcaClusters(res.data.clusters || [])
        setRcaMeta(res.data.meta || null)
        setRcaUncoveredAlarms(res.data.uncovered_alarm_rows || [])
        setRcaUncoveredTruncated(!!res.data.uncovered_truncated)
      })
      .catch(err => {
        console.error('[GISMap] loadRca failed:', err?.response?.status, err?.response?.data || err)
        setRcaError(err?.response?.data?.detail || err?.message || 'rca failed')
        setRcaClusters([])
        setRcaUncoveredAlarms([])
        setRcaUncoveredTruncated(false)
      })
      .finally(() => setRcaLoading(false))
  }

  useEffect(() => {
    if (mode !== 'realtime') return
    const timer = setTimeout(loadRca, 300)
    return () => clearTimeout(timer)
    // selectedFilters 是对象，set 时换新引用即触发；站名 300ms 防抖也由本 effect 承担
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, selectedRegion, selectedFilters, siteNameQuery])

  /* ===== RCA AI 解读（2026-10-21）=====
     凭据与 DataAgentBar 共用 localStorage 键（同一 provider 只填一次 key）。
     生成时把**当前筛选参数**随 POST 体发给后端 —— 服务端重算确定性聚类再喂给
     LLM（不信任前端回传的簇，防口径漂移）；解读失败后端降级为本地规则文案，
     note 原样展示（降级透明，不静默替换）。 */
  const openRcaAi = (e: React.MouseEvent) => {
    setRcaAiAnchor({ x: e.clientX, y: e.clientY })
    setRcaAiOpen(true)
  }

  const onRcaAiProviderChange = (p: string) => {
    setRcaAiProvider(p)
    try { localStorage.setItem('myapp-data-agent-provider', p) } catch { /* 隐私模式 */ }
    setRcaAiKey(localStorage.getItem('myapp-data-agent-key-' + p) || '')
    setRcaAiBaseUrl(localStorage.getItem('myapp-data-agent-baseurl-' + p) || '')
  }

  const onRcaAiKeyChange = (k: string) => {
    setRcaAiKey(k)
    try { localStorage.setItem('myapp-data-agent-key-' + rcaAiProvider, k) } catch { /* 隐私模式 */ }
  }

  const onRcaAiBaseUrlChange = (u: string) => {
    setRcaAiBaseUrl(u)
    try { localStorage.setItem('myapp-data-agent-baseurl-' + rcaAiProvider, u) } catch { /* 隐私模式 */ }
  }

  const runRcaAi = () => {
    setRcaAiLoading(true)
    setRcaAiNote('')
    setRcaAiText('')
    const params: Record<string, string> = {}
    Object.entries(selectedFilters).forEach(([k, v]) => { if (v) params[k] = v })
    if (selectedRegion) params.region = selectedRegion
    const nm = siteNameQuery.trim()
    if (nm) params.site_name = nm
    api.post('/gis/realtime/rca-narrative', {
      ...params,
      provider: rcaAiProvider,
      api_key: rcaAiKey,
      model: rcaAiModel,
      base_url: rcaAiBaseUrl,
      lang: locale,
    })
      .then(res => {
        setRcaAiText(res.data?.narrative?.analysis || '')
        setRcaAiNote(res.data?.narrative?.note || '')
      })
      .catch(err => {
        console.error('[GISMap] rca-narrative failed:', err?.response?.status, err?.response?.data || err)
        setRcaAiNote(err?.response?.data?.detail || err?.message || '')
      })
      .finally(() => setRcaAiLoading(false))
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

  /* 2026-10-16：原「点击县界 → 写入 province_county 高级筛选」的 handleCountyClick
     已按用户要求删除 —— 区域不再可点击选中，过滤只走上方「高级筛选」。
     （原实现用 db_name 而非 name：库里有 "River Cess"/"Rivercess" 两种写法，
     直接拿 name 筛会得 0 个站点。该注意点保留在此备忘，供将来若需恢复时参考。） */

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

  /* 站点着色 —— **每站点恰好一个颜色**，且顺序即优先级。

     ---- 2026-10-17 调整优先级：告警状态提到 TT/WO 之前 ----
     原顺序是 tt > wo > 告警状态，后果被用户实测发现：**29 个有超时告警的站点
     全部同时带 TT**，于是全被涂成蓝色的「TT」，地图上一个红点也没有 ——
     最需要被看到的 SLA 超时反而被工单色盖住了。
     现在改为：overdue > wo > tt > ontime > vip > normal。
     即「超时」永远最醒目（红），其次工单，再其次准时告警。
     ⚠️ 这与图层开关仍相容：关掉 rt_alarm 图层后，站点会自然落到 tt/wo 判定，
        不会被涂成超时色（见下方 activeLayers.has('rt_alarm') 守卫）。
     ⚠️ 图例数字由本函数分桶得出（见 categoryCounts），所以改这里的顺序
        图例会自动跟着变，不会再出现「图例与地图各说各话」。 */
  const getSiteCategory = (site: Site): LegendKey => {
    if (mode === 'realtime') {
      // ① 超时告警（SLA 已破）—— 最高优先级，必须一眼可见
      if (activeLayers.has('rt_alarm') && (site.rt_alarm_overdue || 0) > 0) return 'rt_alarm_overdue'
      // ② 关联工单：WO 比 TT 更「下游」，先画 WO
      if (activeLayers.has('wo') && (site.rt_wo_count || 0) > 0) return 'wo'
      if (activeLayers.has('tt') && (site.rt_tt_count || 0) > 0) return 'tt'
      // ③ 未超时告警
      if (activeLayers.has('rt_alarm') && site.rt_alarm_count > 0) return 'rt_alarm_ontime'
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

  /** 单条链路的 Leaflet pathOptions（2026-10-19）。
      从原 JSX 的 `<Polyline pathOptions={...}>` 原样搬出，四个取值函数
      （linkColor/linkWeight/linkOpacity/linkDash）的口径与注释完全不变 ——
      这里只做组装，不新增任何样式规则。
      useCallback 是因为它会进 TopologyLayer 的 effect 依赖：每次渲染都换新
      函数引用会让 844 条线反复重建，必须稳定。 */
  const topoStyleOf = useCallback((l: TopologyLink) => ({
    color: linkColor(l),
    weight: linkWeight(l),
    opacity: linkOpacity(l),
    dashArray: linkDash(l),
  }), [linkColor, linkWeight, linkOpacity, linkDash])

  /** 单条链路的 popup HTML（2026-10-19）。
      原实现是 844 个 React `<Popup>` 组件，这里改为预拼字符串并由
      Leaflet 直接 setInnerHTML —— 省掉 844 棵 React 子树与 844 个 portal。
      内容与文案与原 JSX 逐项对应（标题 / 无数据说明 / Max+等级 / Tx / Rx / 匹配来源）。

      ⚠️ 链路名与站名来自 KML 导入数据，属外部输入，**必须转义**后再拼进 HTML，
      否则一个含 `<` 的站名就能破坏地图 DOM（AGENTS.md 三.4：外部输入一律不可信）。
      i18n 文案是我们自己的静态字符串，无需转义。 */
  const topoPopupHtml = useCallback((l: TopologyLink): string => {
    const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    const title = esc(l.name || `${l.site_a_name}-${l.site_b_name}`)
    const color = linkColor(l)
    let body: string
    if (l.util == null) {
      /* 无 KPI：明确写出「无数据」，不要让用户以为是 0% 或页面坏了。
         同时说明原因（两端站点未在 MW KPI 数据中匹配到），
         避免被当成 bug 反复上报。 */
      body = `<div style="color:${WH.textDim}">${esc(t('gis.utilNoKpi'))}</div>`
    } else {
      const lv = l.level || utilLevelOf(l.util)
      body =
        `<div>${esc(t('gis.utilMax'))}: <b style="color:${color}">${esc(fmtUtil(l.util))}</b> `
        + `<span style="color:${color}">${esc(levelLabel(lv))}</span></div>`
        + `<div>${esc(t('gis.utilTx'))}: ${esc(fmtUtil(l.tx_util))}</div>`
        + `<div>${esc(t('gis.utilRx'))}: ${esc(fmtUtil(l.rx_util))}</div>`
        + (l.source && l.target
          ? `<div style="color:${WH.textDim};font-size:0.6875rem">`
            + `${esc(t('gis.utilMatchedAs'))}: ${esc(l.source)} → ${esc(l.target)}</div>`
          : '')
    }
    return `<div style="font-size:0.75rem;line-height:1.6;min-width:11rem">`
      + `<div style="font-weight:600">${title}</div>${body}</div>`
  }, [t, linkColor, fmtUtil, levelLabel])

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

  /* 站点名匹配口径（2026-10-21 新增，与 siteNameQuery 的说明配套）：
     · `siteNameKey` —— 站点名的比较形式：去首尾空白 + 转小写。**不去非字母数字**：
       站点名里括号、连字符是名字的一部分（"Qcell LMTI (Marshall)"），
       用户输入时通常也保留它们，粗暴去掉会让 "LMTI Marshall" 命中不到
       "Qcell LMTI (Marshall)"，反而制造"输了却搜不到"的假象。
     · `siteNameFilter` —— 生效值：trim + 小写后的 query，空串表示不生效。
       放在 useMemo 里是为了不把「每次按键都新建一个字符串」变成
       filteredSites 的依赖抖动。 */
  const siteNameKey = useCallback((v: unknown) => String(v ?? '').trim().toLowerCase(), [])
  const siteNameFilter = useMemo(() => siteNameQuery.trim().toLowerCase(), [siteNameQuery])

  /* ===== 两类「缩小」必须分开（2026-10-21）=====

     ---- 为什么要拆 ----
     高级筛选（区域/等级/站型/FME/站点名…）是**数据范围筛选**：用户在说
     「我只关心这些站」。图层开关与图例隐藏是**呈现开关**：用户在说
     「别画 TT 的点」，它回答的是「画什么」而不是「关心什么」。

     统计卡回答的必须是「**我关心的这些站**怎么样」，所以它该跟前者走、
     不该跟后者走。若把图层开关也算进去，用户随手关掉一个图层，
     卡片数字就会跳 —— 那会被读成「数据变了」，而数据其实没变，
     只是他关了一层显示。这正是本次要消灭的那类误导。

     ---- 两个集合的用途 ----
       · `criteriaSites` —— 只过高级筛选。统计卡 / 图例 / 站点等级 Tag 的取数集合。
       · `filteredSites` —— 再过图层与图例。**地图上画哪些点**的唯一真相源，
         也是导出、点位、人员图层的依据（这些确实应当跟随显示开关）。

     口径变清晰的代价是多一次数组遍历（站点量级 827，忽略不计），
     换来的是「卡片数字只由用户的筛选意图决定」，可解释、不跳动。 */
  const criteriaSites = useMemo(() => {
    return sites.filter(site => {
      for (const [key, val] of Object.entries(selectedFilters)) {
        if (val && (site as any)[key] !== val) return false
      }
      if (siteNameFilter && !siteNameKey(site.site_name).includes(siteNameFilter)) return false
      return true
    })
  }, [sites, selectedFilters, siteNameFilter])

  /* 县告警数（**跟随筛选**）：2026-10-21 起不再用后端 /gis/county-boundaries 里的静态
     告警数，而是按当前筛选结果（criteriaSites）现场汇总。

     原因：后端返回的 alarm_site_count 是**全量**口径的静态值，用户在地图上按
     站名/高级条件筛选后，地图填充色、县标签数字、右侧「MAINTENANCE ALERTS」
     排名条仍显示全量数字 —— 与筛选后的站点点对不上，给人「筛选没生效」的错觉。

     口径与 siteNameFilter / selectedFilters 完全一致（同一份 criteriaSites），
     保证「地图上画出来的点」与「按县汇总出来的数字」同源。
     归一化用 countyKey：州/县名在数据源里有大小写与空格差异（如 River Cess / River cess）。 */
  const scopedCountyAlarms = useMemo(() => {
    const m = new Map<string, number>()
    for (const s of criteriaSites) {
      if ((s.rt_alarm_count || 0) <= 0) continue
      const k = countyKey(s.province_county)
      if (!k) continue
      m.set(k, (m.get(k) || 0) + 1)
    }
    return m
  }, [criteriaSites])

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
      .map(c => {
        const n = scopedCountyAlarms.get(countyKey(c.db_name)) ?? 0
        return {
          name: c.name,
          count: n,
          color: COUNTY_BAND_COLORS[alarmBand(n)],
        }
      })
      .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name))
  }, [counties, scopedCountyAlarms])

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
       · 依赖里只有 counties：分档色与告警数都从 counties 派生，没有第二个真相源。
       · 2026-10-13 新增 shiftWestPx：投影器必须知道 MapController 把内容平移了
         多少，否则标签会按「未平移」的坐标落地，与站点圆点脱节
         （站点由 Leaflet 自己按平移摆放，标签是本模块先算好的 lat/lng）。
         方向约定见 countyLabelLayout.ts 的 makeProjector 注释
         （该参数**正值 = 内容左移**；本页 SHIFT_WEST_PX 取负值即内容右移，
          直接透传即可 —— makeProjector 内部是 `x - shiftWestPx`，
         负值等价于 x 加上一个正数，正是右移）。 */
  const countyLabels = useMemo(() => {
    const proj = makeProjector(
      zoomLevel, PORTAL_MAP_WIDTH, LB_CENTER[0], PORTAL_MAP_HEIGHT, shiftWestPx,
    )
    return placeCountyLabels(
      counties,
      c => scopedCountyAlarms.get(countyKey(c.db_name)) ?? 0,
      proj,
    )
  }, [counties, zoomLevel, shiftWestPx, scopedCountyAlarms])


  const filteredSites = useMemo(() => {
    return criteriaSites.filter(site => {
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
      return true
    })
  }, [criteriaSites, hiddenLegends, activeLayers, mode])

  /* 人员图层跟随高级筛选（2026-10-16 用户报「选中 FME 人员地图没生效」）：
     原先 PersonnelLayer 只收 isDark/enabled/timeRange，完全不知道 selectedFilters，
     筛掉站点后小人不减。

     口径（经用户确认「人名筛选时只显示该人」）：
       ① 若高级筛选里选了**人员维度**的列（`fme_name` 或 `supervisor` = X）：
          只保留姓名 == X 的那个人（X 本人）。**不再带出其站点的其它相关人** ——
          「选一个人却列出好几个」会被当成筛错了。
       ② 否则若选了**非人员维度**（区域/站点类型/网络制式…）：
          保留「在可见站点里被记为 fme_name 或 supervisor」的人。
       ③ 完全没筛选：不过滤（返回 null），全员显示 —— **不制造回归**。
          （注意不能走 ②：有 7 个人的姓名在任何站点都没登记，走 ② 会把他们在
           默认视图里也抹掉，那是改动引入的回归。）

     姓名比对用**归一化**（与 PersonnelLayer.normName 同一套规则，勿各写一份）——
     person.name 有 `Ernest Feikai  Sherman,`（双空格 + 尾逗号）这类脏值。 */
  const normName = (v: unknown) => String(v ?? '')
    .replace(/\([^)]*\)/g, '')
    .replace(/^\s*[PGpg]\s*[:]\s*/, '')
    .replace(/\s+/g, ' ')
    .replace(/^[\s,]+|[\s,]+$/g, '')
    .toLowerCase()

  const visiblePersonNames = useMemo<Set<string> | null>(() => {
    const fmeSel = selectedFilters['fme_name']
    const supSel = selectedFilters['supervisor']
    // ① 人员维度筛选优先：只留被选中的那个人
    if ((fmeSel && fmeSel.trim()) || (supSel && supSel.trim())) {
      const out = new Set<string>()
      if (fmeSel && fmeSel.trim()) out.add(normName(fmeSel))
      if (supSel && supSel.trim()) out.add(normName(supSel))
      return out
    }
    // ③ 无任何筛选：不过滤
    // ⚠️ 站点名筛选（siteNameFilter）也算"有筛选"：它同样会把站点缩小到
    //    一部分，人物图层应当跟着缩到这些站点上，否则会剩下与可见站点无关的人。
    const hasAnyFilter = Object.values(selectedFilters).some(Boolean) || !!selectedRegion
      || !!siteNameFilter
    if (!hasAnyFilter) return null
    // ② 非人员维度：由可见站点反推相关人员
    const names = new Set<string>()
    for (const s of filteredSites) {
      const f = normName((s as any).fme_name)
      const p = normName((s as any).supervisor)
      if (f) names.add(f)
      if (p) names.add(p)
    }
    return names
  }, [filteredSites, selectedFilters, selectedRegion, siteNameFilter])

  /* ===== 统计卡跟随筛选（2026-10-21 用户要求：「当我筛选的时候，页面统计卡片和
     地图上统计没有跟着变化」）====================================

     ---- 问题的根因 ----
     三张卡（Alarm Stats / Site Stats / TT Priority Stats）与图例计数，原先都是
     **对后端一次性下发的汇总值**直接渲染（`ossStats` / `priorityStats` /
     `categoryCounts(sites)`）。而站点是**客户端筛选**的（filteredSites），
     于是筛选一改，地图上的点少了，卡片数字纹丝不动 —— 两边各自都对，
     但描述的是**不同的集合**，这正是最难排查的那种不一致。

     ---- 现在的做法：同一份数据、同一个筛选，两处读数必然相等 ----
     OSS 类别与 TT 优先级是**告警级**属性，站点对象上没有按类别拆分的字段，
     所以后端把每条告警的 (site_id, 类别, TT, 优先级) 一并下发（alarm_rows，
     实测约 118 行 / 10KB）。这里按 filteredSites 的站点 ID 集合过滤后重新分桶：

       · Alarm Stats  → 每类：告警数 / 其中带 TT 的告警数 / 涉及的去重站点数
       · Site Stats   → 每类：涉及的去重站点数（与 Alarm Stats 同源，只换读数字段）
       · Priority     → 带 TT 的告警按 P1~P4 / Unknown 分桶，分母 = 各档之和

     **无筛选时结果与后端汇总逐项相等** —— 因为后端那两个汇总本身就是由同一批
     alarm_rows 数出来的（见 gis.py 的 scoped_alarms 注释）。这不是巧合，是同源：
     两者读同一批行、同一套分桶规则，所以不会出现「筛选一清就跳数」。

     ---- 为什么用 criteriaSites 而不是 filteredSites（2026-10-21）----
     见 criteriaSites 的注释：统计只跟**数据范围筛选**（高级筛选 / 站点名）走，
     不跟图层开关与图例隐藏走。关掉一个图层只该少画几个点，不该让「这个站
     有几条告警」的读数发生变化 —— 那会让用户误以为数据在变。

     ---- 为什么回落 ----
     alarmRows 为空（旧缓存 / 字段缺失 / 非实时模式）时直接用后端汇总，
     保证最坏情况下卡片仍有内容可看，而不是空白。 */
  const scopedOssStats = useMemo(() => {
    if (!alarmRows.length) return ossStats
    const visible = new Set(criteriaSites.map(s => s.site_id))
    // { 类别: { count, with_tt, sites:Set } } —— 与后端的三字段口径逐项对齐
    const buckets = new Map<string, { count: number; with_tt: number; sites: Set<string> }>()
    for (const r of alarmRows) {
      if (!visible.has(r.site_id)) continue
      let b = buckets.get(r.problem)
      if (!b) {
        b = { count: 0, with_tt: 0, sites: new Set() }
        buckets.set(r.problem, b)
      }
      b.count++
      b.sites.add(r.site_id)
      // 与后端 _scan_realtime_alarms 同口径：tt_id 非空即算「带 TT」
      // （下钻表里 `priority` 为空串 ⇔ 无 TT，两者必然一致）
      if (r.tt_id) b.with_tt++
    }
    // 按告警数降序（与后端 sorted(counts, key=-count) 同一排序）
    return [...buckets.entries()]
      .map(([oss_specific_problem, b]) => ({
        oss_specific_problem,
        count: b.count,
        with_tt: b.with_tt,
        sites: b.sites.size,
      }))
      .sort((a, b) => b.count - a.count)
  }, [alarmRows, criteriaSites, ossStats])

  /* 优先级分档同理。⚠️ 分母只算**带 TT** 的告警（priority 非空）：
     没有 TT 就没有优先级可言，与后端 _priority_breakdown 的排除规则一致。
     `priority_source` 为 no_tt 的行其 priority 必为空串，这里一并排除。 */
  const scopedPriorityStats = useMemo(() => {
    if (!alarmRows.length) return priorityStats
    const visible = new Set(criteriaSites.map(s => s.site_id))
    const counts = new Map<string, number>()
    for (const r of alarmRows) {
      if (!visible.has(r.site_id) || !r.priority) continue
      counts.set(r.priority, (counts.get(r.priority) || 0) + 1)
    }
    return priorityStats
      .filter(item => counts.has(item.priority))
      .map(item => ({ ...item, count: counts.get(item.priority) || 0 }))
  }, [alarmRows, criteriaSites, priorityStats])

  /* 优先级卡合计 = 各档之和。与后端 priority_stats.total 同口径（都是带 TT 的告警数），
     写成 reduce 而不是取某个字段，是为了让「合计」永远等于上面各档之和 ——
     分母与分子来自同一次遍历，不会出现分子改了分母没改的错位。 */
  const scopedPriorityTotal = useMemo(
    () => scopedPriorityStats.reduce((s, x) => s + x.count, 0),
    [scopedPriorityStats],
  )

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

  /* 站点圆点色 —— **必须走 colorFor()**，与图例同一份色表（2026-10-17）。
     改配色时若只改了图例、没改这里，就会出现「图例红、地图黄」这种最难排查的
     不一致；集中到 colorFor 后只有一个真相源。 */
  const getMarkerColor = (site: Site) => colorFor(getSiteCategory(site))

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

  /* 站点等级分档：随筛选重算（2026-10-21 用户选择「跟随筛选范围重算」）。

     ⚠️ 为什么从「后端全量」改成「前端按筛选重算」——
       实时页原先显示 ERA: 201 / COOL: 64 / NORMAL: 559（合计 824，全量站点表），
       而旁边的 Total Sites 是 115（只有告警站）—— **两个数字本来就对不上**，
       用户无从判断哪个是"我关心的范围"。改成按筛选重算后，三档之和恒等于
       当前范围内的站点数，可校验性反而更强。

     ⚠️ 归一化口径必须与后端一致：后端 `_site_type_stats()` 用
       `_norm_site_category()` 归一（REGULAR / REGULAR(NORMAL) → NORMAL）。
       前端这里**不能重新实现**那套规则，否则「库里写作 REGULAR 的站」
       会被算成第四档、而 Tag 列表里看不到它。故：直接用后端下发的
       `site_caregory`（已归一，见 `_attach_filter_cols`），
       前端只做「按档位分组计数」，不碰归一化。

     档位顺序沿用后端返回顺序（ERA / COOL / NORMAL 固定在前），
     避免前端另排一套序。 */
  const scopedSiteTypeStats = useMemo(() => {
    const counts = new Map<string, number>()
    for (const s of criteriaSites) {
      const k = (s as any).site_caregory
      if (!k) continue
      counts.set(k, (counts.get(k) || 0) + 1)
    }
    // 保留后端返回的档位顺序（ERA/COOL/NORMAL 在前），只把数量换成筛选后的
    const order = siteTypeStats.map(st => st.name)
    const out = order
      .filter(name => counts.has(name))
      .map(name => ({ name, count: counts.get(name) || 0 }))
    // 后端没列出的新档位（脏值归一后的残留）追加在后面，不静默丢弃
    for (const [name, count] of counts) {
      if (!order.includes(name)) out.push({ name, count })
    }
    return out
  }, [criteriaSites, siteTypeStats])

  /* 生效筛选数：**必须把 region 算进去**。region 存在独立 state 里
     （见 FILTER_CONFIG 的说明），只数 selectedFilters 会让「选了区域」
     这个筛选状态在按钮徽标上消失，用户以为没生效。
     站点名同样是独立 state（siteNameQuery），也要算进去 —— 否则输入了站名
     徽标却不动，用户会以为没生效。 */
  const activeFilterCount = Object.values(selectedFilters).filter(Boolean).length
    + (selectedRegion ? 1 : 0)
    + (siteNameFilter ? 1 : 0)

  const handleFilterChange = (key: string, value: string | undefined) => {
    setSelectedFilters(prev => ({ ...prev, [key]: value }))
  }

  const clearAllFilters = () => {
    setSelectedFilters({})
    // region 同样是「高级筛选」的一部分，清除时一并复位，否则按钮的徽标
    // 会一直挂着 1，看起来像清不干净
    setSelectedRegion(undefined)
    // 站点名输入框也要复位（2026-10-21），否则文本还留在框里，
    // 用户会以为「清除」没清干净
    setSiteNameQuery('')
  }

  /* ---- 图例计数：两组用**不同模型**（2026-10-17 用户澄清后定稿）----

     用户两句反馈合起来才说清楚问题：
       ①「图例说 29 个 overdue，地图上一个红色都找不到」→ 告警状态必须与地图一致；
       ②「Related Tickets 的数字也不对」              → TT/WO 不能跟着地图颜色走。
     这两条**无法用同一个模型同时满足**，因为一个站点只有一个颜色：
       30 个站有 TT，但其中 29 个同时有超时告警、被涂成红色，
       若 TT 也按颜色数，就只剩 1 —— 数字没错，却完全没反映"有多少站在跟单"。

     故分开处理：
       · **告警状态组**（overdue / ontime / rt_alarm / his_alarm）：
         按 getSiteCategory 的颜色分桶 —— 必须与地图圆点一一对应；
       · **关联工单组**（tt / wo）与**站点等级组**（vip / normal）：
         按**独立条件**计数（该站是否有 TT / WO / VIP）——
         它们描述"这个站点具备什么属性"，与颜色无关，同一站点可计入多组。
     因此：告警两档之和 = 有告警的站点数；但 Tickets/等级组与它们会重叠，
     **全部相加不等于站点总数**，这是刻意且正确的 —— ⓘ 说明里已写明。

     ⚠️⚠️ 2026-10-21 修复**双计**：上面两套口径原先写在**同一个字典**里，
     于是同一个键被两条规则写：
       · 'vip' / 'normal' 既是颜色分桶的兜底桶、又是独立条件的键；
       · 'tt' / 'wo' 同理（实时模式下它们也是颜色桶）。
     结果同一批站点被数两遍 —— gis 页实测 VIP 显示 **99**（真值 50）、
     Normal 显示 **1539**（真值 774），实时页 VIP/Normal 各被加两次。
     修法见下方 countLegend：两套口径**写不同的键**（详见那里的注释）。 */
  /* 图例计数的**唯一实现**（2026-10-21 重构，修复「一个键被两条规则写」的双计）。

     ---- 背景 ----
     2026-10-17 定稿的图例模型是**三组、两种口径**：
       · 告警状态组（rt_alarm / his_alarm / rt_alarm_overdue / rt_alarm_ontime）
         —— 按**颜色分桶**（getSiteCategory），必须与地图圆点一一对应；
       · 关联工单组（tt / wo）与站点等级组（vip / normal）
         —— 按**独立条件**计数（该站是否带 TT / WO / 是否 VIP 站），
            它们描述"这个站点具备什么属性"，与颜色无关，同一站点可计入多组。
     这两条规则写在**同一个字典**里，于是键名撞车：
       · 'vip' / 'normal' 既是 getSiteCategory 的**兜底颜色桶**，又是独立条件的键；
       · 'tt' / 'wo' 同理（实时模式下它们也是颜色桶）。
     撞车的后果是同一批站点被数两遍：gis 页实测 VIP 显示 **99**（真值 50）、
     Normal 显示 **1539**（真值 774），实时页 VIP/Normal 各被加两次。

     ---- 修法：让两套口径**写不同的键** ----
     ① 颜色分桶**只对告警状态组的键生效** —— getSiteCategory 返回 'vip'/'normal'/
        'tt'/'wo' 时**不计数**（那些颜色是"地图上的兜底涂色"，不是独立属性）；
     ② 独立条件那组按属性计数：vip = vip_site 为 Y/Yes，**normal = 其余全部**
        （互斥且完备，故 vip + normal ≡ 站点总数，这是一个可自校验的不变式）。

     ⚠️ 「normal」的口径因此从「无告警且无工单」改为「非 VIP 站」：前者会把
     有历史告警的站点也算成"正常"，与图例「站点等级」这一定位不符。

     注：站点等级组与告警状态组**故意会重叠**（VIP 站也可能被涂成告警色），
     故各组数字**不能横向相加** —— 这一点已写进图例的 ⓘ 口径说明
     （i18n 的 `gis.legendNote`），改图例文案时一并维护。 */
  const countLegend = (list: Site[]) => {
    const counts = {
      tt: 0, wo: 0, vip: 0, normal: 0,
      rt_alarm: 0, rt_alarm_overdue: 0, rt_alarm_ontime: 0, his_alarm: 0,
    }
    for (const s of list) {
      // ① 告警状态组：颜色分桶（仅这四个键），与地图圆点严格对应
      const cat = getSiteCategory(s)
      if (cat === 'rt_alarm' || cat === 'his_alarm'
        || cat === 'rt_alarm_overdue' || cat === 'rt_alarm_ontime') {
        counts[cat]++
      }
      // ② 关联工单组：独立条件计数（该站是否带 TT / WO）
      if ((s.rt_tt_count || 0) > 0) counts.tt++
      if ((s.rt_wo_count || 0) > 0) counts.wo++
      // ③ 站点等级组：独立条件计数（VIP 站 vs 非 VIP 站），互斥且完备
      if (s.vip_site === 'Y' || s.vip_site === 'Yes') counts.vip++
      else counts.normal++
    }
    return counts
  }

  /* 无筛选时的图例计数（输入 = 全量 sites）。 */
  const categoryCounts = useMemo(
    () => countLegend(sites),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sites, activeLayers, mode],
  )

  /* 图例计数**跟随筛选**（2026-10-21 用户要求：「筛选的时候，地图上统计没有跟着变化」）。
     上一段的 `categoryCounts` 分两档：告警状态组走**每站点恰好一个桶**的颜色分桶
     （`getSiteCategory`），它天然不能改输入集合 —— 改成按 filteredSites 算，
     图例里「Overdue 108」就不再等于地图上红色点的个数，那恰恰是 2026-10-17
     专门重构过一次、消灭掉的「图例与地图各说各话」。

     故按**图例自身的口径**重算一份，输入集合换成 `criteriaSites`：
       · 告警状态组 → 仍走同一个 `getSiteCategory`，只是限定在筛选后的站点内，
         所以数字与地图上画出来的圆点依然一一对应；
       · 工单组 / 等级组 → 与上段同规则（独立条件计数），只是同口径地限定集合。
     即：**筛选是缩小「算哪些站」，不是改变「怎么算一个站」**。

     `legendCounts` = 有筛选时用这份，无筛选时用 `categoryCounts`（与后端全量一致，
     可直接对照）。两者在无筛选时**必然相等**（输入集合相同、规则相同），
     所以切换不会造成数字跳变 —— 这是刻意保留的自校验性质。 */
  const legendScoped = useMemo(
    () => countLegend(criteriaSites),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [criteriaSites, activeLayers, mode],
  )

  const legendCounts = activeFilterCount > 0 ? legendScoped : categoryCounts

  /* 实时模式的**告警/工单总数**（per-alarm，按条数累加）。
     2026-10-17：图例数字统一改成「站点数」之后，这些 per-alarm 的总数仍然有用 ——
     它们是「每档到底有多少条」的对照，写进图例的 ⓘ 口径说明，
     这样用户既能按站点读图例、又能看到告警总量，不会再把两者相加。
     （原先它们直接当图例数字用，与 Overdue/OnTime 的站点数混在一张表里，
       正是「加起来对不上」的另一个来源。） */
  const realtimeAlarmTotals = useMemo(() => {
    /* 取数集合跟 criteriaSites（2026-10-21）：与图例计数、三张卡同源，
       避免 ⓘ 说明里写着一套数字、图例条目写着另一套。
       这几个数是**告警条数**（每站累加），与图例的**站点数**不同单位，
       口径说明里已写明不要相加（见 2026-10-17 的注释）。 */
    const src = criteriaSites
    if (mode === 'realtime') {
      return {
        alarms: src.reduce((s, x) => s + (x.rt_alarm_count || 0), 0),
        overdue: src.reduce((s, x) => s + (x.rt_alarm_overdue || 0), 0),
        ontime: src.reduce((s, x) => s + (x.rt_alarm_ontime || 0), 0),
        tt: src.reduce((s, x) => s + (x.rt_tt_count || 0), 0),
        wo: src.reduce((s, x) => s + (x.rt_wo_count || 0), 0),
      }
    }
    return {
      alarms: 0, overdue: 0, ontime: 0,
      tt: src.reduce((s, x) => s + (x.tt_count || 0), 0),
      wo: src.reduce((s, x) => s + (x.wo_count || 0), 0),
    }
  }, [criteriaSites, mode])

  /* 图例可见性（2026-09-25 修正「假 0」，2026-09-28 随图层合并调整）：
     - rt_alarm_overdue / rt_alarm_ontime 是**实时模式专属**——categoryCounts 只在
       mode==='realtime' 时给它们计数，在 ?page=gis（mode='all'）下恒为 0。
       原实现只在 realtime 模式过滤 rt_alarm/his_alarm，这两个键在 all 模式没被过滤掉，
       于是页面上出现「Realtime Alarm (Overdue) (0)」这种看着像故障、实则是空指标的
       图例（用户 2026-09-25 反馈）。修法：按模式对称过滤。
     - tt / wo 两项**只在实时模式保留**：全量模式下它们已被合并进 his_alarm 一档
       （见 hisAnyHit），再列出来会让同一批站点被数两遍。 */
  const legendItems: { key: LegendKey; color: string; label: string; count: number }[] = [
    /* count 取 legendCounts（= 有筛选时按 criteriaSites 重算，无筛选时等于 categoryCounts），
       理由见 legendScoped 的注释。 */
    { key: 'rt_alarm_overdue', color: colorFor('rt_alarm_overdue'), label: t('gis.legend.rtAlarmOverdue'), count: legendCounts.rt_alarm_overdue },
    { key: 'rt_alarm_ontime', color: colorFor('rt_alarm_ontime'), label: t('gis.legend.rtAlarmOnTime'), count: legendCounts.rt_alarm_ontime },
    { key: 'rt_alarm', color: colorFor('rt_alarm'), label: t('gis.legend.rtAlarm'), count: legendCounts.rt_alarm },
    { key: 'his_alarm', color: colorFor('his_alarm'), label: t('gis.legend.hisAlarm'), count: legendCounts.his_alarm },
    /* tt / wo 改用**站点数**（2026-10-17 统一口径）。原先用 ticketTotals（工单条数），
       与左边的 Overdue/OnTime（站点数）不是同一个单位 —— 同一张图例里混着
       「站点数」与「工单数」，用户没法横向对照，也无法判断某档占比。
       工单**条数**仍保留在 ⓘ 口径说明里（realtimeAlarmTotals）。 */
    { key: 'tt', color: colorFor('tt'), label: t('gis.legend.tt'), count: legendCounts.tt },
    { key: 'wo', color: colorFor('wo'), label: t('gis.legend.wo'), count: legendCounts.wo },
    { key: 'vip', color: SITE_COLORS.vip, label: t('gis.legend.vip'), count: legendCounts.vip },
    { key: 'normal', color: SITE_COLORS.normal, label: t('gis.legend.normal'), count: legendCounts.normal },
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
    // History 一档涵盖告警/TT/WO 三类，光看名字看不出来，补个 hover 说明；
    // Overdue 的判定口径用户看不出来（2026-10-17 要求补说明「TT Overdue」）
    hint: item.key === 'his_alarm' ? t('gis.legend.hisAlarmHint')
      : item.key === 'rt_alarm_overdue' ? t('gis.legend.rtAlarmOverdueHint')
      : item.key === 'rt_alarm_ontime' ? t('gis.legend.rtAlarmOnTimeHint')
      : undefined,
    onClick: () => toggleLegend(item.key),
  }))

  /* ---- 图例分组（2026-10-17 用户要求「重新设计 legend，总是不好区分」）----

     把平铺列表按**语义**拆成三组，配合 LEGEND_COLORS 的同族配色：
       · 实时告警  —— Overdue / On Time（实时模式）；或 RealTime / History（全量）
       · 关联工单  —— TT / WO（仅实时模式）
       · 站点等级  —— VIP / 无状态
     组标题按模式给不同文案，空组（无条目）会被浮层自动跳过标题。
     ⚠️ 分组的顺序即阅读顺序：**先看告警（最需要关注）**，再看工单，最后看兜底态。 */
  const legendGroups: MapLegendGroup[] = useMemo(() => {
    const pick = (keys: LegendKey[]) =>
      siteLegendRows.filter(r => keys.includes(r.id as LegendKey))
    return [
      {
        title: mode === 'realtime' ? t('gis.legendGroup.alarm') : t('gis.legendGroup.status'),
        rows: pick(mode === 'realtime'
          ? ['rt_alarm_overdue', 'rt_alarm_ontime']
          : ['rt_alarm', 'his_alarm']),
      },
      {
        // 全量模式没有独立的 tt/wo 档（已并入 History），该组自然为空、不显示标题
        title: t('gis.legendGroup.ticket'),
        rows: pick(['tt', 'wo']),
      },
      {
        title: t('gis.legendGroup.site'),
        rows: pick(['vip', 'normal']),
      },
    ]
  }, [siteLegendRows, mode, t])

  /* MW 链路利用率图例：只列**实际出现**的分级（计数 0 的不占位）。
     ⚠️ 这一组的**显示与否**归工具栏的 showUtilLegend 管（默认不显示，2026-10-26），
     本数组始终照常计算 —— 收起来只是不传进浮层，不是不生成数据。
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

  /* ===== 实时模式：左侧统计列 + 右侧地图（2026-10-16 用户要求）=====

     布局意图：统计卡（OSS 实时告警分类）竖排在**左**，地图占满**右侧**。
     两个 div 是这条横向行的两层包裹，配合下方「统计卡 → 地图卡片」的 DOM 顺序生效。

     rowStyle —— 外层横向 flex 行。flex:1 让它吃掉工具栏之下剩余的全部高度
       （与 rootStyle 里那个 flex:1 是同一套理由，见上方注释）。

     statsColStyle —— 内层统计列（OSS Problem Stats 卡所在的列）。
       它是一个 **flex column**：以后若在统计卡下方再加卡片，会自动往下排。
       宽度取 **20rem(320px) 定宽**而不是百分比：
       · 列内是 OSS 类别名 + `07 / 210` 这类计数，属**定长文本**，
         门户中列只有 570~730px，纯百分比会把计数挤到换行；
       · 宽度让给地图比按比例切分更符合使用意图（站点密集，越宽越好）。
     minWidth 12rem(192px)：门户中列最窄时给左列兜底，同时保证地图仍有 200px 以上；
     maxWidth 24rem(384px)：超宽屏上不让左列被拉得过宽、统计项之间空得发虚。
     overflowY:auto + minHeight:0：统计项多于可视高度时**左列自己滚**，
       不撑高整行（撑高会把地图一起拉长并顶出视口底）；minHeight:0 是 overflow 生效的前提。

     inertStyle —— 非实时模式的中性样式。display:contents 让该 div 不生成盒子，
       子元素直接参与父级（rootStyle 的 flex 列）布局，等价于「没有这层 div」，
       因此 'all' 模式的纵向布局与改动前一致。详见调用处的长注释。 */
  const inertStyle: React.CSSProperties = { display: 'contents' }

  /* 「是否实时模式」的单一判断点。本页所有与本次横向布局相关的分支都读它，
     避免同一个 mode==='realtime' 散落多处后改一处漏一处。
     注：它与文件里既有的 mode 判断（如 legendItems / layerOptions 的过滤）**不冲突** ——
     那些是既有的、语义各异的判断，不在这里统一，这里只管布局这一件事。 */
  const isRealtime = mode === 'realtime'

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'stretch',
    gap: '0.75rem',
    flex: 1,
    minHeight: 0,
    /* 与上方工具栏卡片之间的间距。放在**行**上而不是某一列上 —— 放列上只会让
       那一列下沉，两列顶部就不齐了（这是本轮修完层级后量到的 13px 错位）。 */
    marginTop: '0.75rem',
  }

  const statsColStyle: React.CSSProperties = {
    /* flexGrow/Shrink 都为 0 = 不参与伸缩，宽度只由 flexBasis(20rem) + 上下限决定。
       若写成 flex:'1 1 …'，地图会被按比例分走一大块宽度。 */
    flex: '0 0 20rem',
    minWidth: '12rem',
    maxWidth: '24rem',
    minHeight: 0,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    /* 顶部间距由上方的 rowStyle 统一给（见那里的注释）—— 本列**不能**自己带
       marginTop，否则只有统计卡下沉、地图卡片仍贴顶，两列顶部错位。 */
  }

  /* ===== OSS 下钻弹窗的派生数据 ===== */

  /* 客户端全字段搜索：把一行的所有值拼成小写串做子串匹配。
     与 SiteDrilldownDrawer 的 helpers.filterBySearch 同一思路，但那一个接收的是
     字段名数组；这里行结构不同（告警行而非站点行），故就地实现，不硬套。 */
  const filteredDrillRows = useMemo(() => {
    const kw = drillSearch.trim().toLowerCase()
    if (!kw) return drillRows
    return drillRows.filter(r =>
      Object.values(r).some(v => String(v ?? '').toLowerCase().includes(kw))
    )
  }, [drillRows, drillSearch])

  /* 列定义。**列标题全部复用既有的 gis.drilldown.* 文案键**（站点/区域/TT/时间），
     只为新增的两列（告警标题、时长、是否超时）加键 —— 减少新增文案、也让本弹窗与
     站点下钻抽屉的列名保持一致口径。
     时间列用后端给的毫秒时间戳（servertime），经 fmtTs 格式化。 */
  const drillColumns = useMemo(() => [
    { title: t('gis.drilldown.siteId'), dataIndex: 'site_id', key: 'site_id', width: 110, ellipsis: true },
    { title: t('gis.drilldown.siteName'), dataIndex: 'site_name', key: 'site_name', width: 160, ellipsis: true },
    { title: t('gis.ossColAlarmTitle'), dataIndex: 'alarm_title', key: 'alarm_title', width: 220, ellipsis: true },
    { title: t('gis.ossColAlarmcode'), dataIndex: 'alarmcode', key: 'alarmcode', width: 100 },
    { title: t('gis.drilldown.region'), dataIndex: 'region', key: 'region', width: 120, ellipsis: true },
    { title: t('gis.drilldown.province'), dataIndex: 'province_county', key: 'province_county', width: 140, ellipsis: true },
    { title: t('gis.ossColTtId'), dataIndex: 'tt_id', key: 'tt_id', width: 150, ellipsis: true,
      render: (v: string) => v || <span style={{ color: WH.textDim }}>{t('gis.ossNoTt')}</span> },
    /* 优先级列（2026-10-16）。两侧下钻（OSS 卡 / 优先级卡）共用本列定义 ——
       它让「从 OSS 进来」时也能看到每条告警的优先级，不必再切到优先级卡。
       ⚠️ 无 TT 的行 priority 是 Unknown 但 source 是 no_tt，显示为「无 TT」
          而不是「未知」—— 两种「没有优先级」的原因不同，别混为一谈。
       Tag 的 color 直接用 antd 的预设色名（不引 PRIORITY_COLORS 的十六进制），
       因为 antd Tag 需要的是它的色板名而非任意颜色值。 */
    { title: t('gis.ossColPriority'), dataIndex: 'priority', key: 'priority', width: 100,
      render: (v: string, r: any) => {
        if (r?.priority_source === 'no_tt') {
          return <span style={{ color: WH.textDim }}>{t('gis.ossNoTt')}</span>
        }
        const label = v === 'Unknown' ? t('gis.priorityUnknown') : v
        const tagColor = v === 'P1' ? 'red' : v === 'P2' ? 'orange' : v === 'P3' ? 'gold' : v === 'P4' ? 'blue' : 'default'
        return <Tag color={tagColor} style={{ borderRadius: 10 }}>{label}</Tag>
      } },
    { title: t('gis.ossColAlarmTime'), dataIndex: 'servertime', key: 'servertime', width: 160,
      render: (v: number | null) => (v ? fmtTs(new Date(v)) : '—') },
    { title: t('gis.ossColDuration'), dataIndex: 'duration', key: 'duration', width: 110 },
    { title: t('gis.ossColOverdue'), dataIndex: 'overdue', key: 'overdue', width: 90,
      render: (v: boolean) => (v
        ? <Tag color="red" style={{ borderRadius: 10 }}>{t('gis.ossOverdueYes')}</Tag>
        : <Tag style={{ borderRadius: 10 }}>{t('gis.ossOverdueNo')}</Tag>) },
  ], [t])

  /* RCA 簇成员表的列（2026-10-21）：与告警下钻**不是同一形状**（成员是站点行、
     告警下钻是告警行），故单独一份列定义，弹窗按 drillKind 切换。
     站名列可点 —— 复用 handleSiteClick 打开站点下钻抽屉（根因/成员站的
     告警、TT、建议都在那个抽屉里，本弹窗不重复实现）。 */
  const rcaDrillColumns = useMemo(() => [
    { title: t('gis.drilldown.siteId'), dataIndex: 'site_id', key: 'site_id', width: 110, ellipsis: true },
    { title: t('gis.drilldown.siteName'), dataIndex: 'site_name', key: 'site_name', width: 160, ellipsis: true,
      render: (v: string, r: any) => (
        <a
          role="button"
          tabIndex={0}
          onClick={() => handleSiteClick({ site_id: r.site_id } as Site)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              handleSiteClick({ site_id: r.site_id } as Site)
            }
          }}
          style={{ color: WH.teal }}
        >
          {v}
        </a>
      ) },
    { title: t('gis.drilldown.region'), dataIndex: 'region', key: 'region', width: 120, ellipsis: true },
    { title: t('gis.rca.colAlarmCount'), dataIndex: 'alarm_count', key: 'alarm_count', width: 90 },
    { title: t('gis.ossColTtId'), dataIndex: 'tt_id', key: 'tt_id', width: 150, ellipsis: true,
      render: (v: string) => v || <span style={{ color: WH.textDim }}>{t('gis.ossNoTt')}</span> },
    { title: t('gis.rca.colLinkPath'), dataIndex: 'link_path', key: 'link_path', width: 220, ellipsis: true,
      render: (v: string) => (v && v !== '--' ? v : <span style={{ color: WH.textDim }}>{t('gis.rca.noPath')}</span>) },
  ], [t])

  /* 未归因弹窗**不再有独立列定义**（2026-10-21b，用户要求改用项目默认告警明细）：
     未归因行与 oss 下钻同形（见 openDrill 的 rca_uncovered 分支），列直接复用
     上面的 drillColumns —— 与点击 Alarm Stats 条目打开的是同一张表。 */

  /* 导出当前**筛选后**的行（与表格所见一致），走项目统一的 exportAoaReport。

     ⚠️ 这里**不用** helpers 的 exportToExcel：它按 dataIndex 直接取原始值导出，
        会把 servertime 导成裸毫秒数、把 overdue 导成 true/false，与界面上看到的
        「2026-10-16 12:00」「是/否」不一致。本弹窗的展示层做了格式化，导出必须
        跟着格式化后的口径走，所以就地拼 header/rows（与 GISMap 既有的 exportSites
        写法一致，那一处也是直接 exportAoaReport）。
     ⚠️ 文件名不再自己拼时间戳：exportAoaReport 内部会加（同 exportToExcel 的做法），
        自己再拼一遍会出现两个时间戳。 */
  const exportDrill = () => {
    if (!filteredDrillRows.length) return
    // RCA 成员表：形状不同（站点行），单独拼 header/rows 后走同一个 exportAoaReport
    if (drillKind === 'rca') {
      const c = rcaClusters.find(x => x.cluster_id === drillKey)
      const rootName = c?.root?.site_name || drillKey
      const header = [
        t('gis.drilldown.siteId'), t('gis.drilldown.siteName'),
        t('gis.drilldown.region'), t('gis.rca.colAlarmCount'),
        t('gis.ossColTtId'), t('gis.rca.colLinkPath'),
      ]
      const rows = filteredDrillRows.map((r: any) => [
        r.site_id, r.site_name, r.region, r.alarm_count,
        r.tt_id || t('gis.ossNoTt'), r.link_path || t('gis.rca.noPath'),
      ])
      void exportAoaReport({
        filename: `rca_${drillKey}`,
        sheetName: 'RCA Members',
        title: `${t('gis.rca.title')} · ${rootName}`,
        subtitle: `${t('common.records', { n: rows.length })}`
          + `    |    ${t('gis.rca.exportCause', { cause: t(rcaCauseLabelKey(c?.cause_type || 'other')) })}`,
        header,
        rows,
        tabColor: '#2F5496',
      })
      return
    }
    // 标题/文件名按 kind 区分，几种下钻导出的文件名不会重名。
    // rca_uncovered 与 oss/priority 同为告警明细行，共用下面的通用 11 列导出。
    const title = drillKind === 'oss'
      ? (drillKey || t('gis.ossStatsTitle'))
      : drillKind === 'rca_uncovered'
      ? t('gis.rca.uncoveredTitle')
      : `${t('gis.priorityStatsTitle')} · ${drillKey}`
    const header = [
      t('gis.drilldown.siteId'), t('gis.drilldown.siteName'),
      t('gis.ossColAlarmTitle'), t('gis.ossColAlarmcode'),
      t('gis.drilldown.region'), t('gis.drilldown.province'),
      t('gis.ossColTtId'), t('gis.ossColPriority'), t('gis.ossColAlarmTime'),
      t('gis.ossColDuration'), t('gis.ossColOverdue'),
    ]
    const rows = filteredDrillRows.map(r => [
      r.site_id, r.site_name, r.alarm_title, r.alarmcode,
      r.region, r.province_county,
      r.tt_id || t('gis.ossNoTt'),
      r.priority_source === 'no_tt'
        ? t('gis.ossNoTt')
        : (r.priority === 'Unknown' ? t('gis.priorityUnknown') : (r.priority || '')),
      r.servertime ? fmtTs(new Date(r.servertime)) : '—',
      r.duration,
      r.overdue ? t('gis.ossOverdueYes') : t('gis.ossOverdueNo'),
    ])
    void exportAoaReport({
      filename: `${drillKind}_alarms_${drillKey || 'all'}`,
      sheetName: 'Alarms',
      title,
      subtitle: `${t('common.records', { n: rows.length })}`,
      header,
      rows,
      tabColor: '#2F5496',
    })
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
              {/* 站点总数（2026-10-21 改为跟随筛选）：
                  无筛选时显示范围总数；有筛选时显示「筛选后 / 范围总数」，
                  这样一个 Tag 同时说清"现在看的是多少"和"一共多少"。

                  ⚠️ 范围总数用 `sites.length`（本次响应带回来的站点数），
                     不是 `site_type_stats` 的合计 —— 后者是**全量站点表**口径
                     （824），而实时页的 `sites` 只含有告警的站（115）。
                     两者本就不是一回事，这也是原先「Total Sites 115」
                     与「ERA 201+COOL 64+NORMAL 559」对不上的根因。
                     现在分档 Tag 也改成按筛选范围重算，两者重新对齐。 */}
              <Tag color="cyan">
                {t('gis.totalSites')}: {activeFilterCount > 0
                  ? `${criteriaSites.length}/${sites.length}`
                  : sites.length}
              </Tag>
              {/* 站点等级分档统计（2026-09-28 用户要求「在旁边添加 RRA/COOL/NORMAL 的统计」）。
                  数据来源与口径见 scopedSiteTypeStats 的注释（2026-10-21 改为跟随筛选）。
                  「（用户原话是 RRA，经确认为 ERA 的笔误）」
                  每档单独上色（ERA 紫 / COOL 青 / NORMAL 蓝），与站点标记色系区分开：
                  这三档描述的是站点**资产等级**，不是告警状态，用告警的红黄会误导。 */}
              {scopedSiteTypeStats.map(st => (
                <Tag key={st.name} color={SITE_TYPE_TAG_COLORS[st.name] || 'default'}>
                  {st.name}: {st.count}
                </Tag>
              ))}
              <ExplainIcon text={t('gis.explain.note')} size={14} />
            </Space>
          </Col>
          <Col>
            <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
              {/* 图层组标题在实时模式下**隐藏**（2026-10-16 用户要求「统计卡片竖着排列」）。
                  原因：实时模式的统计 Tag 已改到地图右侧竖排，而这一组（Realtime/TT/WO）
                  留在工具栏里，两者居中对齐后标题在这里反而成了多余的锚点。
                  'all' 模式不受影响，仍是原来的「图层：」+ 三个 Tag。 */}
              {mode !== 'realtime' && (
                <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: WH.text }}>{t('gis.layerFilter')}</span>
              )}
              {layerOptions.map(lo => (
                <Fragment key={lo.key}>
                <Tag
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
                {/* 人员图层开关：紧跟「Realtime」右侧（2026-10-16 用户要求）。
                    仅 gis 页（mode==='all'）提供；realtime_alarm 页不显示。 */}
                {lo.key === 'rt_alarm' && mode === 'all' && (
                  <PersonnelToggleButton
                    enabled={showPersonnel}
                    loading={false}
                    onToggle={() => setShowPersonnel(v => !v)}
                  />
                )}
                </Fragment>
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
                className="wh-seg"
                value={zoomLevel}
                onChange={(v) => setZoomLevel(v as number)}
                options={ZOOM_LEVELS.map(z => ({
                  label: `${z}${t('gis.zoomLevelSuffix')}`,
                  value: z,
                }))}
                size="small"
                style={{ background: 'var(--wh-seg-bg)' }}
              />
              {/* 「利用率图例」按钮紧跟 Segmented 之后 = 用户要的「Zoom: 右边」
                  （2026-10-26）。**必须留在同一个 Space 内**：换到隔壁 Col 或自占一行，
                  窄屏换行时就会与 Zoom: 分开，不再「在它右边」。
                  组件取舍见 gismap/MapOverlayToggle.tsx 文件头。 */}
              <MapOverlayToggle
                label={t('gis.utilLegendToggle')}
                hint={t('gis.utilLegendToggleHint')}
                show={showUtilLegend}
                onToggle={setShowUtilLegend}
              />
            </Space>
          </Col>
          {mode !== 'realtime' && (
            <Col>
              <Space wrap style={{ gap: 'var(--wh-space-sm)' }}>
                <span style={labelStyle}>{t('gis.timeFilter')}</span>
                <Segmented
                  className="wh-seg"
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
                /* ⚠️ 标签名**刻意与左边的「站点总数」不同**（2026-10-21）：
                   左边那个说的是「**筛选范围内**的站点数」（criteriaSites），
                   这里说的是「**地图上画出来的**站点数」（filteredSites，
                   额外扣掉被图层开关/图例隐藏的）。
                   两者的差别只在「图层开关关掉了什么」，所以用「地图显示」区分，
                   而不是两个都叫 Total Sites —— 那会让用户以为有两个总数对不上。 */
                <Tag color="cyan">{t('gis.onMap')}: {filteredSites.length}/{criteriaSites.length}</Tag>
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
              {/* 站点名输入框（2026-10-21 用户要求「添加站点名字的过滤」）。
                  放在**筛选面板的第一格**：站点名是最高频的定位手段，
                  应当一眼可见，而不是夹在一堆下拉中间。

                  为什么是 Input 而不是 Select：
                    · 站点有 800+ 个，把候选值全塞进下拉会让 `filter_options`
                      体积翻几倍，且在长列表里翻找某个站名比直接输入慢得多；
                    · 其余筛选项都是**枚举**（有限的几十个值），站点名不是。

                  为什么放前端而不是后端：
                    站点列表本来就全量下发到前端（`sites`），筛选在客户端做
                    （见 filteredSites）能即时响应，无需往返；后端也不必为
                    一个模糊文本查询再扫一遍站点表。

                  匹配口径：**不区分大小写的子串匹配**（见 siteNameKey 的说明），
                  与其它筛选项的"精确相等"不同 —— 站点名是自由文本，
                  精确相等几乎不可能手打对。 */}
              <Col>
                <Input
                  size="small"
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder={t('gis.filter.siteName')}
                  style={{ width: 'min(100%, 12.5rem)' }}
                  value={siteNameQuery}
                  onChange={e => setSiteNameQuery(e.target.value)}
                />
              </Col>
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

      {/* ===== 实时模式：统计卡左竖排 + 地图右（2026-10-16 用户要求）=====

          用户原话：「把统计卡片竖着排列，地图放到右边」。
          做法是给「统计列」与「地图卡片」套两层横向 flex 包裹（rowStyle + statsColStyle），
          宽度由 flex 分配而不是写死像素 —— 门户中列宽度可变（见 PORTAL_MAP_WIDTH
          的耦合提示），写死宽度在换版式时会立刻错位。

          为什么用 flex 而不是 antd 的 <Row>/<Col>：
            · 这里要的是「统计列固定宽度、地图吃掉剩余全部宽度」这种**不等分**分配，
              Row 的 24 栅格表达不出「定宽 320px + 剩余」的语义；
            · 左列内部还要自己撑满高度并独立滚动，Col 要多包一层才等价。

          ⚠️ 两层 div 都**无条件渲染**，非实时模式靠 inertStyle（display:contents）
             退化成「不存在」，因此 'all' 模式的纵向布局与改动前一致。
             首版曾把两层都写成 `{cond && (<div>…</div>)}` 条件包裹，在收口处
             连踩两个语法坑（闭合标签不能出现在表达式位置，TS1109；以及
             「只有闭合标签的条件块」让 tsc 解析错位，TS1381），故改为本写法。
             这也解释了下方「这里不关闭 statsColStyle」的注释为何存在。 */}
      <div style={isRealtime ? rowStyle : inertStyle}>
      <div style={isRealtime ? statsColStyle : inertStyle}>
      {/* OSS 统计卡（仅实时模式）。
          · flexShrink:0 —— 统计卡不参与纵向压缩，保持内容高度。
          · rowGap：本卡在行内层（statsColStyle，flex column）里，它与下方「无内容」
            之间的间距由卡片自己的 marginBottom 决定；横向布局下地图卡片在**旁边**
            而不是下方，所以这里不需要下边距，改成 0 让统计列顶部与地图卡片顶部齐平。
            （'all' 模式走不到本卡，故无需对两种布局分别取值。） */}
      {mode === 'realtime' && scopedOssStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginBottom: 0, flexShrink: 0 }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, marginBottom: 'var(--wh-space-sm)' }}>
            {t('gis.ossStatsTitle')} ({scopedOssStats.reduce((s, i) => s + i.count, 0)})
          </div>
          {/* 竖排（2026-10-16）：原先横排自动换行，搬到右侧统计列后列宽只剩 320px，
              横排会把每条压得极窄；改为纵向 flex + 每条占满列宽。
              'all' 模式走不到这里（本卡片只在实时模式渲染），故无需按模式分支。

              每条**可点击**下钻（同日用户要求）：整行是一个按钮语义的 div，
              点击打开该类别的告警明细弹窗。进度条宽度仍按告警总数归一（视觉排序用）。 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {scopedOssStats.map(item => {
              const max = scopedOssStats[0]?.count || 1
              const pct = Math.max(4, Math.round((item.count / max) * 100))
              return (
                <div
                  key={item.oss_specific_problem}
                  role="button"
                  tabIndex={0}
                  aria-label={t('gis.ossDrillHint', { name: item.oss_specific_problem })}
                  style={{
                    minWidth: 0, cursor: 'pointer', borderRadius: 'var(--wh-radius-sm)',
                    padding: '2px var(--wh-space-xs)', margin: '0 -var(--wh-space-xs)',
                    transition: 'background 0.15s',
                  }}
                  onClick={e => openDrill('oss', item.oss_specific_problem, e)}
                  onKeyDown={e => {
                    // 键盘可达（a11y）：Enter / Space 等效于点击
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openDrill('oss', item.oss_specific_problem, e as any)
                    }
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--wh-subtle-bg)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.375rem', fontSize: '0.75rem', color: WH.text }}>
                    <span title={item.oss_specific_problem} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{item.oss_specific_problem}</span>
                    {/* 读数（2026-10-16 用户要求改口径）：由「告警数 / 站点数」改为
                        「带 TT 的告警数 / 告警总数」。两个数同为**告警**单位，
                        相除即「TT 覆盖率」，比原来两个不同单位的量更有意义。 */}
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>
                      {item.with_tt ?? 0} / {item.count}
                    </span>
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

      {/* ===== Site Stats（2026-10-17 用户要求）=====
          用户原话：「OSS Problem Stats 名字改成 Alarm Stats，并在组件下面添加 Site Stats，
          内容是一样的，只是按照站点来统计每类告警的站点数」。

          与上方 Alarm Stats 的**唯一区别**是读数：
            · Alarm Stats：`带 TT 的告警数 / 告警总数`   —— 告警口径
            · Site Stats ：该类别涉及的**去重站点数**     —— 站点口径
          两者的类别集合、排序、可点击下钻都完全相同（同一份 ossStats），
          所以这里复用同一个数组，只换读数字段，不另发请求。

          ⚠️ 为什么站点数之和可能大于站点总数：一个站点可同时有多种告警类别
             （例如既 SITE OUTAGE 又 Fiber Break），各档会重复计它。
             这与图例里「同站点可计入多档」是同一条口径说明。 */}
      {mode === 'realtime' && scopedOssStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginTop: '0.75rem', marginBottom: 0, flexShrink: 0 }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, marginBottom: 'var(--wh-space-sm)' }}>
            {t('gis.siteStatsTitle')} ({scopedOssStats.reduce((s, i) => s + (i.sites || 0), 0)})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {scopedOssStats.map(item => {
              // 进度条按「本卡片内最大的站点数」归一，让各条长度可比
              const maxSites = Math.max(...scopedOssStats.map(x => x.sites || 0), 1)
              const pct = Math.max(4, Math.round(((item.sites || 0) / maxSites) * 100))
              return (
                <div
                  key={item.oss_specific_problem}
                  role="button"
                  tabIndex={0}
                  aria-label={t('gis.ossDrillHint', { name: item.oss_specific_problem })}
                  style={{
                    minWidth: 0, cursor: 'pointer', borderRadius: 'var(--wh-radius-sm)',
                    padding: '2px var(--wh-space-xs)', margin: '0 -var(--wh-space-xs)',
                    transition: 'background 0.15s',
                  }}
                  onClick={e => openDrill('oss', item.oss_specific_problem, e)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openDrill('oss', item.oss_specific_problem, e as any)
                    }
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--wh-subtle-bg)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.375rem', fontSize: '0.75rem', color: WH.text }}>
                    <span title={item.oss_specific_problem} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{item.oss_specific_problem}</span>
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>{item.sites ?? 0}</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--wh-subtle-bg)', borderRadius: 3, marginTop: 3 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: WH.blue, borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* ===== 按 TT 优先级统计（2026-10-16 用户要求）=====
          用户原话：「组件 OSS Problem Stats 下面添加有 TT 号码的，按照优先级进行统计的组件」。
          统计单位 = **带 TT 的告警**（没 TT 就没有优先级可言，故不参与）。
          优先级取自 eflow_tt.ticket_severity（P1~P4），后端做「镜像优先 + 实时补漏」。

          ⚠️ 关于「本地库一小时才更新、取不到」：后端实测后**没有**全量改走实时接口 ——
             实时接口只覆盖「最近修改的前若干行」，反而看不到 6 个 7~8 月的老单。
             故以镜像为主干、实时只补缺口，细节见 gis.py 的 _resolve_tt_priorities。
             这里只负责展示，拿到的数字与后端同源。

          每条可点击（同 OSS 卡）：点 P1 → 打开该优先级下的告警明细弹窗。 */}
      {mode === 'realtime' && scopedPriorityStats.length > 0 && (
        <Card size="small" style={{ ...cardStyle, marginTop: '0.75rem', marginBottom: 0, flexShrink: 0 }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, marginBottom: 'var(--wh-space-sm)' }}>
            {t('gis.priorityStatsTitle')} ({scopedPriorityTotal})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {scopedPriorityStats.map(item => {
              /* 进度条按总数归一（不用最大值）—— 这里各档之和就是总数，
                 用总数能让各条长度直接读出「占比」，比相对最大值更有信息量。 */
              const pct = scopedPriorityTotal > 0
                ? Math.max(2, Math.round((item.count / scopedPriorityTotal) * 100))
                : 2
              // 不渲染计数为 0 的档，避免 P1(0) 这种占位（与图例「假 0」是同一类问题）
              if (!item.count) return null
              return (
                <div
                  key={item.priority}
                  role="button"
                  tabIndex={0}
                  aria-label={t('gis.priorityDrillHint', { name: item.priority })}
                  style={{
                    minWidth: 0, cursor: 'pointer', borderRadius: 'var(--wh-radius-sm)',
                    padding: '2px var(--wh-space-xs)', margin: '0 -var(--wh-space-xs)',
                    transition: 'background 0.15s',
                  }}
                  onClick={e => openDrill('priority', item.priority, e)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openDrill('priority', item.priority, e as any)
                    }
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--wh-subtle-bg)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.375rem', fontSize: '0.75rem', color: WH.text }}>
                    <span style={{ minWidth: 0 }}>
                      {item.priority === 'Unknown' ? t('gis.priorityUnknown') : item.priority}
                    </span>
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>
                      {item.count}
                    </span>
                  </div>
                  <div style={{ height: 6, background: 'var(--wh-subtle-bg)', borderRadius: 3, marginTop: 3 }}>
                    {/* 优先级色阶：P1 红 → P2 橙 → P3 黄 → P4 蓝（Unknown 灰）。
                        与地图上的告警状态色**刻意分开**——那组描述站点当前状态，
                        这组描述工单等级；混用会让人以为 P1 站点在地图上也是红的。 */}
                    <div style={{ width: `${pct}%`, height: '100%', background: PRIORITY_COLORS[item.priority] || WH.textDim, borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* ===== 根因聚合分析（RCA，2026-10-21）=====
          与上方三张统计卡同一来源（/realtime/rca 与 /realtime/sites 同一次扫描），
          但回答的是另一个问题：这批断站里，哪些是**同一个原因**。
          · topology 簇：上游站断 → link_path 下挂站跟着断（优先派修根因站）
          · same_cause 簇：无链路站按「问题 + 10 分钟窗」聚集（疑似批量事件）
          每条可点开成员明细；「范围外」Tag 表示根因站在当前筛选范围外（用户决策：
          完整展示并标注）。置信度是后端确定性公式的启发式分值，非 AI 输出。 */}
      {mode === 'realtime' && (rcaClusters.length > 0 || rcaError) && (
        <Card size="small" style={{ ...cardStyle, marginTop: '0.75rem', marginBottom: 0, flexShrink: 0 }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, marginBottom: 'var(--wh-space-sm)', display: 'flex', alignItems: 'center', gap: 'var(--wh-space-xs)', flexWrap: 'wrap' }}>
            {/* 计数用**站数**（已归因/总）而不是簇数 —— 簇数与旁边 Site Stats 的
                站数不是同一单位，曾被当成"两边对不上"（2026-10-21 用户反馈）。
                簇有几组看列表行数即可，站数才需要与 Site Stats (N) 对拍。 */}
            <span title={t('gis.rca.titleHint', {
              covered: rcaMeta?.covered_sites ?? 0, total: rcaMeta?.in_scope_sites ?? 0,
              n: rcaClusters.length,
            })}>
              {t('gis.rca.title')}
              {' '}({rcaMeta ? `${rcaMeta.covered_sites}/${rcaMeta.in_scope_sites}` : rcaClusters.length})
            </span>
            {/* AI 解读：弹窗配置 provider/key（存本机），POST /realtime/rca-narrative。
                渐进加载 —— 簇列表先出，解读后到，AI 不可用时后端降级为本地规则文案。 */}
            <Button
              size="small"
              type="text"
              icon={<RobotOutlined />}
              style={{ marginLeft: 'auto' }}
              onClick={e => openRcaAi(e)}
            >
              {t('gis.rca.aiButton')}
            </Button>
          </div>
          {/* 口径脚注：覆盖数显式给出（"未归入任何簇"的站也要看得见，防静默漏站）。
              title 给出更细的口径拆解（有链路/卫星站/孤儿告警行）。
              可点击 → 打开未归因清单（孤立故障站列表，可对地图逐点核验）。 */}
          {rcaMeta && !rcaError && (
            <div
              role="button"
              tabIndex={0}
              aria-label={t('gis.rca.uncoveredTitle')}
              style={{
                fontSize: '0.6875rem', color: WH.textMuted, marginBottom: 'var(--wh-space-sm)',
                cursor: 'pointer', textDecoration: 'underline dotted',
                textDecorationColor: WH.textDim, textUnderlineOffset: 2,
              }}
              title={t('gis.rca.metaDetail', {
                rows: rcaMeta.alarm_rows, sites: rcaMeta.alarmed_sites,
                link: rcaMeta.with_link_path, sat: rcaMeta.satellite_sites,
                orphan: rcaMeta.orphan_alarm_rows, unmatched: rcaMeta.eflow_root_unmatched,
              })}
              onClick={e => openDrill('rca_uncovered', '', e)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  openDrill('rca_uncovered', '', e as any)
                }
              }}
            >
              {t('gis.rca.metaLine', {
                covered: rcaMeta.covered_sites, uncovered: rcaMeta.uncovered_sites,
                total: rcaMeta.in_scope_sites,
              })}
            </div>
          )}
          {rcaError && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 'var(--wh-space-sm)' }}
              message={<span style={{ fontSize: 12 }}>{t('gis.rca.fetchFailed')}: {rcaError}</span>}
            />
          )}
          {rcaLoading && (
            <div style={{ textAlign: 'center', padding: '0.75rem 0' }}>
              <Spin size="small" />
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {rcaClusters.map(c => {
              // 进度条按「最大簇成员数」归一；颜色按根因类型，与 Tag 同语义族
              const maxMembers = Math.max(...rcaClusters.map(x => x.member_count || 0), 1)
              const pct = Math.max(6, Math.round(((c.member_count || 0) / maxMembers) * 100))
              const causeBarColor: Record<string, string> = {
                transmission: '#13c2c2', fiber: '#9254de', power: '#fa8c16',
                site_outage: '#ff4d4f', other: '#9aa5b5',
              }
              return (
                <div
                  key={c.cluster_id}
                  role="button"
                  tabIndex={0}
                  aria-label={t('gis.rca.drillHint', { name: c.root?.site_name || c.cluster_id })}
                  style={{
                    minWidth: 0, cursor: 'pointer', borderRadius: 'var(--wh-radius-sm)',
                    padding: '2px var(--wh-space-xs)', margin: '0 -var(--wh-space-xs)',
                    transition: 'background 0.15s',
                  }}
                  onClick={e => openDrill('rca', c.cluster_id, e)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openDrill('rca', c.cluster_id, e as any)
                    }
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--wh-subtle-bg)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: WH.text }}>
                    <span style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, maxWidth: '7.5rem' }} title={c.root?.site_name}>
                        {c.root?.site_name || c.cluster_id}
                      </span>
                      <Tag color={rcaCauseTagColor(c.cause_type)} style={{ margin: 0, borderRadius: 10, fontSize: '0.6875rem' }}>
                        {t(rcaCauseLabelKey(c.cause_type))}
                      </Tag>
                      {!c.root_in_scope && (
                        <Tag
                          color="orange"
                          style={{ margin: 0, borderRadius: 10, fontSize: '0.6875rem' }}
                          title={t('gis.rca.outOfScopeHint')}
                        >
                          {t('gis.rca.outOfScope')}
                        </Tag>
                      )}
                    </span>
                    {/* 读数：受影响站数 · 置信度（确定性启发式，非 AI） */}
                    <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>
                      {t('gis.rca.memberCount', { n: c.member_count })} · {Math.round((c.confidence || 0) * 100)}%
                    </span>
                  </div>
                  <div style={{ height: 6, background: 'var(--wh-subtle-bg)', borderRadius: 3, marginTop: 3 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: causeBarColor[c.cause_type] || '#9aa5b5', borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
      {/* ⚠️ statsColStyle 必须在这里、也就是**地图卡片之前**收口。
          它只包住左侧的统计内容（当前只有 OSS 卡）；下方的地图卡片要是它的
          **兄弟节点**（同属 rowStyle 这一行），才能排在统计列右边。
          2026-10-16 曾把两个 </div> 都写到地图卡片之后，于是地图被套进了
          统计列内部、在列里换行显示成上下排列 —— 这是「还是上下排列」的根因。
          收口位置与下方标注「收口」的那对 </div> 共同决定这一行的成员，
          改动本段时务必对照行内注释确认盒子层级。 */}
      </div>


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
          工具栏之下剩余的全部高度，使地图贴到视口底。

          ⚠️ 实时模式下这张卡片位于行内层的 rowStyle（flex **row**）里，此时
             **必须再补一个 minWidth:0**：flex 子项默认 min-width:auto，会拒绝
             收缩到内容固有宽度以下，而 Leaflet 的地图容器固有宽度很大 ——
             缺了这个 0，地图卡片不肯变窄，会把左边的统计列挤出可视区，
             表现为「地图没有老实待在统计卡右边」。只有 row 方向才需要它，
             纵向的 'all' 模式不受影响（那里卡片还是 rootStyle 的 flex 列子项）。

          为什么用 isRealtime 变量而不是就地写 mode==='realtime'：
             同一判断在本卡片与下方包裹处各出现一次，抽出来保证两处口径一致
             （改模式名时只改一处）。 */}
      <Card
        styles={{ body: { padding: 0, position: 'relative', height: '100%' } }}
        style={{
          ...cardStyle, overflow: 'hidden', flex: 1,
          minHeight: 0,
          minWidth: isRealtime ? 0 : undefined,
          display: 'flex', flexDirection: 'column',
        }}
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
            <MapController center={center} zoom={zoomLevel}
              shiftWestPx={shiftWestPx} shiftSouthPx={shiftSouthPx} />
            <Pane name="sitePane" style={{ zIndex: 650 }} />
            {/* 县名标签专用 pane（2026-10-03）：**必须高于 sitePane(650)**，
                否则站点红点会盖住标签。
                根因：Leaflet 默认 tooltipPane 的 z-index 恰好也是 650，与 sitePane
                平级 —— 平级时谁后画谁在上，DOM 顺序不保证，于是红点压住县名。
                取 670：高于 sitePane(650)、低于 popupPane(700)，保证弹窗仍在最上。
                （层级链：tile 200 < overlay 400 < shadow 500 < marker 600
                  < sitePane/tooltip 650 < countyLabel 670 < popup 700 < control 1000） */}
            <Pane name="countyLabelPane" style={{ zIndex: 670 }} />
            {/* 人员图层专用 pane（2026-10-16）：**必须高于 sitePane(650)** ——
                否则小人图标会被站点圆点盖住（人员看得见比站点更重要，因为
                点击小人才能展开其 WO）。取 680：高于 countyLabel(670)、
                低于 popup(700)，保证人员弹窗仍在最上。
                层级链见上方 countyLabelPane 注释，此处只是插入一层。 */}
            <Pane name="personPane" style={{ zIndex: 680 }} />
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
            {/* 人员图层（仅 gis 页）：小人图标 + WO 弹窗 + 人员→站点路线。
                自包含组件，见 gismap/PersonnelLayer.tsx 头注释与已知限制说明。 */}
            {mode === 'all' && (
              <PersonnelLayer
                isDark={isDark}
                enabled={showPersonnel}
                timeRange={timeRange}
                visibleNames={visiblePersonNames}
              />
            )}
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
                 分档只驱动**颜色**，透明度由下方 FILL_OPACITY 统一给出。
                 ⚠️ 2026-10-21：告警数改取 scopedCountyAlarms（跟随筛选），
                 与县名标签、排名条同源 —— 三处不再各说各话。 */
              const scopedCount = scopedCountyAlarms.get(countyKey(c.db_name)) ?? 0
              const band = alarmBand(scopedCount)
              const fill = COUNTY_BAND_COLORS[band]
              return (
              <Polygon
                key={`county-${c.name}`}
                positions={c.polygons as any}
                /* 2026-10-16 用户要求：**区域不可点击选中**，过滤只能走上方「高级筛选」。
                   故移除 onClick（原为 handleCountyClick → 写入 province_county 筛选）。
                   县块仍保留颜色分档，只是不再接受点击。 */
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
                  自身不可见、不接收点击（interactive:false）。
                  （2026-10-16 起县块也不再响应点击 —— 区域不可选中，过滤只走高级筛选。）

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
            {/* MW 链路（2026-10-19）：844 条线改由 TopologyLayer 用 Leaflet 原生 API
                批量建层。原实现是 844 个 <Polyline> + 844 个 <Popup>，实测在
                t=2480ms 单帧建出 844 个 SVG path、阻塞主线程 1547ms。
                样式（topoStyleOf）与 popup（topoPopupHtml）仍在本组件内组装，
                分级口径与文案一律不变 —— 见 gismap/TopologyLayer.tsx 文件头。 */}
            {showTopology && (
              <TopologyLayer
                links={topologyLinks}
                styleOf={topoStyleOf}
                popupHtmlOf={topoPopupHtml}
              />
            )}
          </MapContainer>
          {/* 图例浮层（2026-09-28 用户要求「直接在地图上显示，竖排」；位置为**左下**）。
              放在地图容器**之后**是关键：浮层 z-index 与 Leaflet 控件同为 1000，
              同层时 DOM 靠后者胜，故它压在站点圆点/县名标注之上。 */}
          {/* MW 利用率图例组由工具栏的「利用率图例」按钮控制，**默认不显示**
              （2026-10-26 用户要求）。这里把 utilTitle/utilRows/utilNote **三样一起**
              置空：MapLegendOverlay 的 hasUtil 门槛是「有标题且有行」，只清后两样
              会留下一个空的分组标题，看起来像渲染坏了。
              ⚠️ 只影响图例，不影响地图上的链路绘制（见 showUtilLegend 的注释）。 */}
          <MapLegendOverlay
            title={t('gis.legendTitle')}
            groups={legendGroups}
            utilTitle={showUtilLegend ? t('gis.utilLegendTitle') : undefined}
            utilRows={showUtilLegend ? utilLegendRows : undefined}
            utilNote={showUtilLegend && showTopology && showUtil && utilMeta
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
      {/* 收口：这里只剩 rowStyle 这一层要关 —— statsColStyle 已在上方统计卡
          之后收口（见那处注释）。两个 div 都无条件渲染，故这里也无条件关闭。 */}
      </div>
      {/* 实时模式的横向行到此结束（见上方 rowStyle 的说明）。
          ⚠️ 抽屉**刻意留在行外**：它是 antd 的 portal 抽屉（挂到 body），
          放在 flex 行内不影响布局，但留在外面读起来更清楚 —— 它不是「右列的一部分」，
          而是整页的浮层。 */}

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

      {/* ===== 告警明细下钻弹窗 =====
          两个卡共用（OSS 类别卡 / TT 优先级卡），由 drillKind 决定端点与标题。
          一行一条**实时告警**，不是一行一个站点 —— 与卡片的读数同为「告警」单位，
          用户对照时不会有「数字对不上」的困惑。行数恒等于卡片上的 count
          （后端同源，见 /realtime/oss-alarms 与 /realtime/priority-alarms 的注释）。
          搜索走客户端全字段过滤；导出走项目统一的 exportAoaReport。 */}
      <DraggableClickModal
        open={drillOpen}
        anchor={drillAnchor}
        onClose={() => setDrillOpen(false)}
        title={
          <span style={{ color: WH.text }}>
            {/* 标题带上来源，避免「P3」这种孤零零的档位不知从哪张卡点到。
                rca：根因站名 + 类型/簇标签，一眼知道这是哪个根因的影响面。 */}
            {drillKind === 'rca_uncovered'
              ? (() => (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--wh-space-xs)', flexWrap: 'wrap' }}>
                    {t('gis.rca.uncoveredTitle')}
                    <Tag style={{ margin: 0, borderRadius: 10 }}>{t('gis.rca.uncoveredTag')}</Tag>
                  </span>
                ))()
              : drillKind === 'rca'
              ? (() => {
                  const c = rcaClusters.find(x => x.cluster_id === drillKey)
                  return (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--wh-space-xs)', flexWrap: 'wrap' }}>
                      {t('gis.rca.drillTitle', { name: c?.root?.site_name || drillKey })}
                      {c && (
                        <>
                          <Tag color={rcaCauseTagColor(c.cause_type)} style={{ margin: 0, borderRadius: 10 }}>
                            {t(rcaCauseLabelKey(c.cause_type))}
                          </Tag>
                          <Tag style={{ margin: 0, borderRadius: 10 }}>{t(rcaKindLabelKey(c.kind))}</Tag>
                        </>
                      )}
                    </span>
                  )
                })()
              : drillKind === 'priority'
              ? `${t('gis.priorityStatsTitle')} · ${drillKey === 'Unknown' ? t('gis.priorityUnknown') : drillKey}`
              : drillKey}
            <Tag color="cyan" style={{ marginLeft: 'var(--wh-space-sm)', borderRadius: 10 }}>
              {t('common.records', { n: filteredDrillRows.length })}
            </Tag>
            {/* 截断时显式告警，不静默（AGENTS.md 三.1b） */}
            {drillTruncated && (
              <Tag color="red" style={{ marginLeft: 'var(--wh-space-xs)', borderRadius: 10 }}>
                {t('gis.drillTruncated', { shown: drillRows.length })}
              </Tag>
            )}
          </span>
        }
      >
        {/* RCA 证据块（2026-10-21）：根因站的告警 + 簇证据摘要，位于表格上方。
            全部来自同一次 /realtime/rca 响应里的 cluster 对象，与成员表同源。 */}
        {drillKind === 'rca' && (() => {
          const c = rcaClusters.find(x => x.cluster_id === drillKey)
          if (!c) return null
          const ev = c.evidence || {}
          return (
            <div style={{
              marginBottom: '0.75rem', padding: '0.5rem 0.75rem',
              background: 'var(--wh-subtle-bg)', borderRadius: 'var(--wh-radius-sm)',
              fontSize: '0.75rem', color: WH.text, display: 'flex',
              flexDirection: 'column', gap: 4,
            }}>
              {/* 根因站告警（cap 10）：先看"根因站自己报了什么"再决定派谁去 */}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <span style={{ color: WH.textMuted, whiteSpace: 'nowrap' }}>{t('gis.rca.rootAlarms')}:</span>
                {(c.root?.alarms || []).map((a, i) => (
                  <Tag key={i} style={{ margin: 0, borderRadius: 10 }}>{a.alarm_title}</Tag>
                ))}
              </div>
              {/* 证据行：链路 / 时间窗 / 同码 / eFlow 佐证 —— 有哪条显示哪条 */}
              {ev.link_paths && ev.link_paths.length > 0 && (
                <div>{t('gis.rca.evidence.linkPath')}: <span style={{ fontFamily: 'monospace' }}>{ev.link_paths.slice(0, 3).join('  ')}</span></div>
              )}
              {ev.time_window && (
                <div>
                  {t('gis.rca.evidence.timeWindow')}: {fmtTs(new Date(ev.time_window.start_ms))} → {fmtTs(new Date(ev.time_window.end_ms))}
                  （{ev.time_window.span_min} min）
                </div>
              )}
              {ev.shared_problem && (
                <div>{t('gis.rca.evidence.sharedProblem')}: {ev.shared_problem}</div>
              )}
              {ev.eflow_impact && (
                <div>
                  {t('gis.rca.evidence.eflow')}
                  <Tag color="green" style={{ margin: '0 4px', borderRadius: 10 }}>
                    impact_site_number = {String(ev.eflow_impact.impact_site_number ?? '—')}
                  </Tag>
                </div>
              )}
            </div>
          )
        })()}
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
            onClick={exportDrill}
            disabled={!filteredDrillRows.length}
          >
            {t('common.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table
              dataSource={filteredDrillRows}
              columns={drillKind === 'rca' ? rcaDrillColumns : drillColumns}
              size="small"
              rowKey={(r: any) => (drillKind === 'rca'
                ? String(r.site_id)
                : `${r.site_id}|${r.servertime}|${r.alarmcode}`)}
              pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
              scroll={{ x: 'max-content' }}
              locale={{ emptyText: drillKind === 'rca_uncovered'
                ? t('gis.rca.uncoveredEmpty')
                : t('gis.ossDrillEmpty') }}
            />
          </div>
        )}
      </DraggableClickModal>

      {/* ===== RCA AI 解读弹窗（2026-10-21）=====
          第二个 DraggableClickModal：provider/key/model/base_url 配置 + 解读结果。
          key 与 DataAgentBar 共用 localStorage（同一 provider 只填一次）；
          provider='local' 走后端本地规则文案，不需要 key。 */}
      <DraggableClickModal
        open={rcaAiOpen}
        anchor={rcaAiAnchor}
        onClose={() => setRcaAiOpen(false)}
        title={
          <span style={{ color: WH.text, display: 'inline-flex', alignItems: 'center', gap: 'var(--wh-space-xs)' }}>
            <RobotOutlined style={{ color: WH.teal }} />
            {t('gis.rca.aiTitle')}
          </span>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
          <Alert
            type="info"
            showIcon
            message={<span style={{ fontSize: 12 }}>{t('gis.rca.aiHint')}</span>}
          />
          <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', flexWrap: 'wrap' }}>
            <Select
              size="small"
              style={{ width: 'min(100%, 10rem)' }}
              value={rcaAiProvider}
              onChange={onRcaAiProviderChange}
              options={[
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'openai', label: 'OpenAI' },
                { value: 'qianwen', label: 'Qianwen' },
                { value: 'doubao', label: 'Doubao' },
                { value: 'glm-coding', label: 'GLM' },
                { value: 'agnes', label: 'Agnes' },
                { value: 'local', label: t('gis.rca.aiProviderLocal') },
              ]}
            />
            <Input.Password
              size="small"
              style={{ width: 'min(100%, 18.75rem)' }}
              placeholder={t('gis.rca.aiKey')}
              value={rcaAiKey}
              onChange={e => onRcaAiKeyChange(e.target.value)}
              disabled={rcaAiProvider === 'local'}
            />
            <Input
              size="small"
              style={{ width: 'min(100%, 12.5rem)' }}
              placeholder={t('gis.rca.aiModel')}
              value={rcaAiModel}
              onChange={e => setRcaAiModel(e.target.value)}
            />
            <Input
              size="small"
              style={{ width: 'min(100%, 18.75rem)' }}
              placeholder={t('gis.rca.aiBaseUrl')}
              value={rcaAiBaseUrl}
              onChange={e => onRcaAiBaseUrlChange(e.target.value)}
            />
          </div>
          <div>
            <Button
              type="primary"
              size="small"
              loading={rcaAiLoading}
              disabled={rcaAiProvider !== 'local' && !rcaAiKey}
              onClick={runRcaAi}
            >
              {t('gis.rca.aiGenerate')}
            </Button>
            {/* local 模式 = 后端本地规则文案，不调用外部模型（无需 key） */}
            {rcaAiProvider === 'local' && (
              <Tag color="gold" style={{ marginLeft: 'var(--wh-space-sm)', borderRadius: 10 }}>
                {t('gis.rca.aiLocalTag')}
              </Tag>
            )}
          </div>
          {rcaAiLoading && <Spin style={{ display: 'block', margin: '0.75rem auto' }} />}
          {!rcaAiLoading && rcaAiNote && (
            <Alert
              type="warning"
              showIcon
              message={<span style={{ fontSize: 12 }}>{rcaAiNote}</span>}
            />
          )}
          {!rcaAiLoading && rcaAiText && (
            <pre style={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
              fontFamily: 'inherit', fontSize: 13, lineHeight: 1.75, color: WH.text,
              background: 'var(--wh-subtle-bg)', borderRadius: 'var(--wh-radius-sm)',
              padding: '0.625rem 0.875rem',
            }}>
              {rcaAiText}
            </pre>
          )}
        </div>
      </DraggableClickModal>
    </div>
  )
}
