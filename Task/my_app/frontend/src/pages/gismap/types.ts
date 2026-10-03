// GISMap 页面类型定义

export interface Site {
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
  rt_alarm_overdue?: number
  rt_alarm_ontime?: number
  rt_tt_count?: number
  rt_wo_count?: number
  trm_type?: string
  area?: string
  hubsite?: string
  site_information?: string
  supervisor?: string
  /** 现场维护工程师姓名（站点表 fme_name 列，人名如 "Mark D. Paye"） */
  fme_name?: string
}

// ========== 图表数据结构（与 backend/routers/gis.py 聚合接口对齐）==========

/** 名称/计数对，用于饼图、柱状图 */
export interface NameValue {
  name: string
  value: number
}

/** 微波链路逐日历史点 */
export interface MwHistoryPoint {
  day: string
  tx_util?: number | null
  rx_util?: number | null
  max_util?: number | null
}

/** 单个制式的站点级 KPI 序列（2G/3G/4G 页签） */
export interface RatKpiSeries {
  matched_by?: 'site_id' | 'site_name' | null
  site_name?: string | null
  metrics: { key: string; label: string; is_rate: boolean | null }[]
  daily: (Record<string, any> & { day: string })[]
  days: number
  error?: string
}

/**
 * /gis/drilldown/{id}/analytics 的返回。
 * 与明细列表不同：这里是站点全量聚合，不受 LIMIT 50/100 截断影响。
 */
export interface DrilldownAnalytics {
  site_id?: string
  site_name?: string
  range?: { start: string; end: string; days: number }
  tt?: {
    total?: number
    closed?: number
    open?: number
    sla_met?: number
    sla_violated?: number
    sla_rate?: number | null
    first_time?: string | null
    last_time?: string | null
    daily?: { day: string; total: number; closed: number }[]
    by_status?: NameValue[]
    by_severity?: NameValue[]
    by_sla?: NameValue[]
    by_root_cause?: NameValue[]
    duration_buckets?: NameValue[]
    duration_parsed?: number
    duration_total?: number
  }
  wo?: {
    total?: number
    daily?: { day: string; total: number }[]
    by_status?: NameValue[]
    by_source?: NameValue[]
    by_root_cause?: NameValue[]
    by_severity?: NameValue[]
  }
  his?: {
    total?: number
    daily?: { day: string; total: number }[]
    by_severity?: NameValue[]
    by_title?: NameValue[]
  }
  warnings?: string[]
}

export interface DrilldownData {
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
  /** 明细列表实际使用的时间窗口 */
  range?: { start: string; end: string; days: number }
  kpis?: {
    availability?: { tech: string; day: string; availability: number }[]
    packet_loss?: { day: string; max_packet_loss: number; avg_packet_loss: number; samples: number }[]
    microwave?: {
      source: string; target: string
      tx_utilization: number; rx_utilization: number
      capacity_mbps: number; level?: string; begin_time?: string
      max_util?: number
      /** 逐日利用率历史，用于趋势折线（后端 mw_ume_topology 提供） */
      history?: MwHistoryPoint[]
    }[]
    /** 分制式站点级 KPI 序列：{ '2G': {...}, '3G': {...}, '4G': {...} } */
    kpi_series?: Record<string, RatKpiSeries>
    warnings?: string[]
  }
}

export interface TopologyLink {
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
  /** 链路名（kml_mw_links.name，如 "Baypolu-Weala"）；旧 topology 表无此字段 */
  name?: string
  /** 线色，来自 kml_mw_links.color（4 色：红/黄/蓝/绿）。2026-09-25 起数据源换为 kml_mw_links */
  color?: string

  /* ===== MW 利用率叠加（?with_util=1，2026-09-28 新增）=====
     把 mwRealTime 的最新 15 分钟粒度利用率贴到 KML 线上。
     后端只对「能确认是同一条物理链路」的线返回数值，其余一律 util=null /
     level='no_kpi'，前端据此保留 KML 原线色 —— 详见
     backend/services/gis_mw_overlay.py 模块头注释（宁可少标绝不猜标）。 */

  /** max(tx_util, rx_util)；null = 未匹配到 KPI 数据（**不是** 0） */
  util?: number | null
  tx_util?: number | null
  rx_util?: number | null
  /** 利用率分级；'no_kpi' 专指「无数据」，与 'healthy'（有数据且正常）严格区分 */
  level?: UtilLevel
  /** 命中方式：coord=坐标匹配（语义中立，优先）/ name=站名兜底 / null=未命中 */
  matched_by?: 'coord' | 'name' | null
  /** 匹配到的 MW 端点站名（供悬浮提示核对，便于人工发现错配） */
  source?: string
  target?: string
}

/** 利用率分级（与后端 mw_ume_topology.level_of 口径一致）+ 'no_kpi' 无数据。
 *  2026-09-29 由 6 级合并为 4 级：healthy(原 healthy+negligible) / minor /
 *  major(原 moderate) / critical(原 major+critical)。 */
export type UtilLevel =
  | 'critical' | 'major' | 'minor' | 'healthy' | 'no_kpi'

/** /api/gis/topology?with_util=1 返回的叠加统计，用于向用户解释「为什么只有一半线有颜色」 */
export interface UtilMeta {
  total: number
  matched: number
  matched_by_coord: number
  matched_by_name: number
  no_kpi: number
  endpoint_hit: number
  endpoint_miss: number
  /** 数据槽位（如 "2026-09-28 08:30:00"），与 mwRealTime 页当前槽位一致 */
  slot?: string | null
  granularity?: string | null
}

/** 站点等级统计一档（/gis/sites 与 /gis/realtime/sites 的 `site_type_stats`）。
 *  后端按 `site_caregory` 归一化后给出，顺序固定为 ERA / COOL / NORMAL，其余脏值按数量追加。 */
export interface SiteTypeStat {
  name: string
  count: number
}

export type LegendKey = 'tt' | 'wo' | 'vip' | 'normal' | 'rt_alarm' | 'rt_alarm_overdue' | 'rt_alarm_ontime' | 'his_alarm'
export type LayerKey = 'rt_alarm' | 'his_alarm' | 'tt' | 'wo'
export type TimePreset = 'all' | '7d' | '30d' | '90d' | '180d' | 'custom'

/** 边界蒙层模式：不显示 / Voronoi 大区 / 真实县界（三选一，见 GISMap.tsx） */
export type BoundaryMode = 'none' | 'region' | 'county'

/**
 * 县（County）真实行政边界，来自 /gis/county-boundaries。
 * - name    附件 GeoJSON 里的原始县名（如 "Rivercess"）
 * - db_name 与站点表 province_county 对齐后的值（如 "River Cess"），点击下钻时用它筛选
 * - polygons 已是 [lat, lng]（后端生成时已交换），可直接交给 Leaflet
 */
export interface CountyBoundary {
  name: string
  db_name: string
  color: string
  /** 该县站点总数（口径同 /gis/sites） */
  site_count: number
  /** 该县**有实时告警的站点数**（COUNT DISTINCT，口径同 /gis/realtime/sites）。
   *  2026-09-25 新增：地图标签按用户要求改为显示此值而非 site_count。 */
  alarm_site_count: number
  polygons: [number, number][][]
}

// i18n 翻译函数类型
export type TFn = (key: string, params?: Record<string, string | number>) => string

/* 站点分类配色 —— GIS 页与下钻抽屉的**唯一**颜色真相源。
   放在 types.ts 的原因：GISMap.tsx 与 SiteDrilldownDrawer.tsx 都要用，
   若定义在 GISMap.tsx 里再由抽屉 import，会形成 GISMap → 抽屉 → GISMap 的循环依赖。

   ⚠ 值必须是**十六进制实值**，不能用 WH.xxx：这些颜色最终喂给 Leaflet 的
   SVG/Canvas 渲染（CircleMarker 的 fillColor），canvas 解析不了 CSS 变量。
   与 AGENTS.md 三.3「ECharts 用 DARK/LIGHT 实值」是同一条约束的同类场景。

   撞色修正（2026-09-25，用户反馈）：
     原 his_alarm=#ffa94d（橙）与 rt_alarm_ontime=#ffd400（黄）在深色底图上
     肉眼几乎分不出，且二者分属「历史/实时」两个互斥通道，同色会误导判断。
     现把 his_alarm 改为**灰色系 #8b95a5**：灰色天然表达「历史/已归档」的语义，
     与所有高饱和的实时色（红/黄）在明度与饱和度两个维度上都拉开距离。
     注意**不要**改用 #94a3b8 —— 那是 normal 的灰，会和「无告警站点」混淆。 */
export const SITE_COLORS = {
  rt_alarm: '#ff6b6b',          // 实时告警（全量模式下的一档）
  rt_alarm_overdue: '#ff1e1e',  // 实时告警·已超时（大红）
  rt_alarm_ontime: '#ffd400',   // 实时告警·未超时（黄）
  his_alarm: '#8b95a5',         // 历史告警（灰 —— 见上方撞色说明）
  tt: '#258cff',
  wo: '#51cf66',
  vip: '#a99cff',
  normal: '#94a3b8',
} as const

/* MW 链路线色图例 —— 与 backend/services/mw_ume/mw_links_store.py 的
   STYLE_COLORS 一一对应（KML 样式名 → 色值），是那 4 个颜色的前端副本。
   改 KML 样式色时两处要一起改（后端 `STYLE_COLORS` 已声明同源约束）。 */
export const KML_LINK_COLORS = [
  { color: '#ff3b30', labelKey: 'gis.topologyColorRed' },
  { color: '#ffcc00', labelKey: 'gis.topologyColorYellow' },
  { color: '#0a84ff', labelKey: 'gis.topologyColorBlue' },
  { color: '#34c759', labelKey: 'gis.topologyColorGreen' },
] as const

/* MW 链路利用率分级配色 —— 对齐 `?page=mwUmeTopology` 的链路色阶。
   色值取自 frontend/public/legacy-vmax-theme.css 的 --vmax-lvl-* **深色档**
   （该文件是唯一真相源，见 legacy-vmax-theme.css:82-86）：
     healthy #0bc78c | minor #f6cf00 | major #ff7a45 | critical #ff5c6c | unknown #6f8cb4

   2026-10-02 用户要求「按 mwUmeTopology 的链路颜色显示」，故本表与那一页对齐。
   前三档与 mwRealTime 本就逐值相同（两页共用同一套 --vmax-lvl-*），
   本次实质变化只有 no_kpi 一档：由「回退 KML 原色」改为 **unknown 灰 #6f8cb4**。

   为什么 no_kpi 必须换掉 KML 原色（本次改动的核心，别改回去）：
     KML 原色含红 #ff3b30，与 critical 的 #ff5c6c 是**同色系**，在深色底图上几乎
     分不开。实测 844 条线里 27 条「无 KPI 的 KML 红线」会被读成 critical ——
     运维照着红线去排障，有 7 成概率查错链路。改灰后「红色 = 严重」才唯一。
     mwUmeTopology 页正是这么做的：unknown 用灰 + 虚线（该页 :1580-1581），
     本页照搬同一语义（虚线在 GISMap.tsx 的 linkDashOf 里加）。

   与 KML_LINK_COLORS 的关系：
     KML 4 色（红/黄/蓝/绿）是 KML 原作者的**人工标注**，语义未知。
     原先「匹配不到 KPI 就保留 KML 原色」的做法正是撞色根源；
     现改为统一灰虚线后，KML 原色只作历史说明保留在 KML_LINK_COLORS 里，
     不再参与 no_kpi 的实际渲染。两页显示同一指标，配色不一致会让人
     以为是两套口径，故本次刻意与 mwUmeTopology 复刻到逐值一致。

   同 KML_LINK_COLORS：值必须是十六进制实值，不能用 WH.xxx
   （Leaflet 走 SVG/Canvas，解析不了 CSS 变量）。 */

export const UTIL_LEVEL_COLORS: Record<UtilLevel, string> = {
  critical: '#ff5c6c',
  major: '#ff7a45',
  minor: '#f6cf00',
  healthy: '#0bc78c',
  no_kpi: '#6f8cb4',
}

/* 图例/提示里的分级展示顺序：由重到轻，与 mwRealTime 的分级顺序一致 */
export const UTIL_LEVEL_ORDER: UtilLevel[] = [
  'critical', 'major', 'minor', 'healthy',
]

/* 利用率 -> 分级。**前端独立实现**而非依赖后端 level 字段兜底：
   后端理论上总会给 level，但接口降级/字段缺失时不能让告警线悄悄变绿。
   口径与后端 mw_ume_topology.level_of 严格一致：
   >80 critical | >=70 major | >=60 minor | <60 healthy
   （临界值：critical 为严格大于 80，与页面 "> 80%" 的写法一致） */
export function utilLevelOf(u: number | null | undefined): UtilLevel {
  if (u == null || !isFinite(Number(u))) return 'no_kpi'
  const v = Number(u)
  if (v > 80) return 'critical'
  if (v >= 70) return 'major'
  if (v >= 60) return 'minor'
  return 'healthy'
}
