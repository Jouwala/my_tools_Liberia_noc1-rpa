// Packet Loss Dashboard - 丢包看板（参考 RealTime Alarm Map 风格）
// 数据源: lte_pl.sqlite3（RAN UME SDR/IPRAN IPPD 丢包率，最近 7 个完整自然日小时粒度，当天未过完不展示）
// 口径与 Excel 报告（Packet_Loss_Status_Output Automation）完全一致：
//   STATUS = 0~23 标志块（最近 3 天同整点丢包均 >0.5% 记 1）全 0 -> OK，否则 NOK
//   FINAL_STATUS = STATUS=OK 强制 No Packet loss[<0.1]，否则按 Last 1 day Max PL 五级分类
import { useEffect, useState, useMemo, useCallback } from 'react'
import { Card, Row, Col, Tag, Spin, Alert, Empty, Table, Input, Button, Switch } from 'antd'
import {
  AlertOutlined, WarningOutlined, EnvironmentOutlined,
  PieChartOutlined, DashboardOutlined,
  DownloadOutlined, SearchOutlined, RightOutlined,
  ClockCircleOutlined, CheckCircleOutlined, DisconnectOutlined,
  ApartmentOutlined, PlusOutlined, MinusOutlined, UndoOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
// 用自研的 LeafletMap（原生 leaflet）取代 react-leaflet —— 后者是 Hippocratic-2.1
// 许可（非 OSI，含人权条款/仲裁/赔偿），见 components/LeafletMap.tsx 头部说明。
import { MapContainer, CircleMarker, Polyline, useMap } from '../components/LeafletMap'
import { BASEMAP_PMTILES_URL, BASEMAP_ATTRIBUTION, BASEMAP_MAX_ZOOM } from './gismap/basemap'
import { PmtilesLayer } from './gismap/PmtilesLayer'
// center/zoom 变化后同步 setView —— MapContainer 只在挂载时吃一次 zoom，
// 换档（窗口宽度跨阈值）必须靠它把新档位应用到已存在的地图实例。
import { MapController } from './gismap/MapController'
/* 县底色 + 县名标签（2026-11-11 用户要求「跟其他页面地图一样加州的背景颜色」）：
   与人员页共用同一套组件 / 色表 / 县界缓存键，不另写一份。 */
import { CountyLayer } from './personmap/CountyLayer'
import { CountyLabels } from './personmap/CountyLabels'
import { useCountyTags } from './personmap/useCountyTags'
import { countyOfOrg } from './iptPower/countySoc'
import type { CountyBoundary } from './gismap/types'
import { exportAoaReport } from '../utils/excelReport'
import dayjs from 'dayjs'
import api from '../api'
import { cachedGet } from '../cache'
import DraggableClickModal from '../components/DraggableClickModal'
// 统一说明气泡（三.3c）：ExplainIcon 挂角上/标题，ExplainPopover 包住数字本身
import { ExplainIcon, ExplainPopover } from '../components/MetricExplain'
import { useI18n, numLocale } from '../i18n'
import { WH, DARK, LIGHT, WH_COLORS, LIGHT_COLORS, useTheme, useIsMobile, darkTooltip, axisLabel, axisLine, splitLine, pageWrap, cardStyle } from '../theme'

const STATUS_ORDER = ['Critical[>5]', 'Major[1-5]', 'Minor[0.5-1]', 'Warning[0.1-0.5]', 'No Packet loss[<0.1]']
const STATUS_COLORS: Record<string, string> = {
  'Critical[>5]': '#ff4757',
  'Major[1-5]': '#ff922b',
  'Minor[0.5-1]': '#ffd43b',
  'Warning[0.1-0.5]': '#74c0fc',
  'No Packet loss[<0.1]': '#51cf66',
}
const STATUS_COLORS_LIGHT: Record<string, string> = {
  'Critical[>5]': '#d92d20',
  'Major[1-5]': '#ea580c',
  'Minor[0.5-1]': '#ca8a04',
  'Warning[0.1-0.5]': '#0369a1',
  'No Packet loss[<0.1]': '#15803d',
}
const STATUS_SHORT: Record<string, string> = {
  'Critical[>5]': 'Critical',
  'Major[1-5]': 'Major',
  'Minor[0.5-1]': 'Minor',
  'Warning[0.1-0.5]': 'Warning',
  'No Packet loss[<0.1]': 'OK',
}

// 指标计算说明（鼠标悬停「?」查看，可复制）
const getMetricExplain = (t: (key: string) => string): Record<string, string> => ({
  'Total Sites': t('pl.explain.totalSites'),
  'Critical': t('pl.explain.critical'),
  'Major': t('pl.explain.major'),
  'Minor': t('pl.explain.minor'),
  'Warning': t('pl.explain.warning'),
  'No Packet loss': t('pl.explain.noPacketLoss'),
  'Affected Sites': t('pl.explain.affectedSites'),
  'Data Granularity': t('pl.explain.granularity'),
})

// 拓扑视图：按 backhaul/transport 类型（gateway 字段）聚合站点，
// 每个 gateway 计算质心作为「汇聚节点」，并把每个成员站点连到其最近的同网关邻居，
// 形成 hub-and-spoke 拓扑。以下为各 gateway 的配色。
const GW_COLORS: Record<string, string> = {
  'MW': '#36cfc9',            // 微波
  'Satellite Link': '#ffc53d', // 卫星链路
  'IPRAN': '#9254de',         // IPRAN
  'Start Link': '#ff7a45',    // Start Link
}
const gwColor = (gw: string) => GW_COLORS[gw] || '#8c8c8c'

// 右 1/3 列三图（饼/趋势/区域）的_plot 高度：列窄，240 足够且让三卡总高 ≈ 左地图卡，
// 地图画布 flex:1 填满左卡剩余高度（线框图的大地图展示区）
const CHART_HEIGHT = 240

// 地图下方控制行（线框图 Layers·Topology·Site Filters / Map Controls）的小控件样式
const CTL_LABEL: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 4,
  fontSize: '0.6875rem', color: WH.textMuted, cursor: 'pointer', userSelect: 'none',
}
const CTL_BTN: React.CSSProperties = {
  height: 22, width: 22, minWidth: 22, padding: 0,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6875rem',
}

/* 全国取景（与 ipt / 人员页的 LB_CENTER 同源：bbox 3.9,-11.7 ~ 8.75,-7.3）。
   ⚠ center 必须是模块级常量：CountyLabels 的避让投影与 MapController 的 effect
   吃它的引用相等性（理由见 PersonMapView 的 LB_CENTER 注释）。 */
const PL_MAP_CENTER: [number, number] = [6.325, -9.5]

/* zoom 按视口分档（LeafletMap zoomSnap=0.5，半档合法）。2026-11-11 二次重排后
   地图占左 2/3 列（画布比旧的 1/3 宽一倍），故档位整体上移：国土在 zoom 8 约
   754×766px、7.5 约 533×542px、6 约 188×192px。县名标签避让走廊是
   [半盒宽, 画布宽-半盒宽]，zoom 偏高时沿海县质心落在走廊外会被兜底推回、
   半个标签裁出画布，故按画布实测留边选档：
     ≥1500 → 8    画布 ~1040×800，国土 754×766，四周留边 >100px
     ≥900  → 7.5  画布 ~630~790 宽，国土 533×542，留边充足
     <900  → 6    移动端画布 ~321×464，国土 188×192
   换档时 MapController 同步 setView、CountyLabels 按新 zoom 重算避让，
   两处吃同一个值不会漂移；用户手动滚轮缩放不受影响（effect 依赖不变不重跑）。 */
function zoomForWidth(w: number): number {
  if (w >= 1500) return 8
  if (w >= 900) return 7.5
  return 6
}

function useMapZoom(): number {
  const [zoom, setZoom] = useState(() => zoomForWidth(window.innerWidth))
  useEffect(() => {
    const onResize = () => setZoom(zoomForWidth(window.innerWidth))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return zoom
}

/* 本页县名标签没有悬停展开的两行统计（人员页那两行是传输/维护口径，丢包页
   不适用），typeLines 传空 Map。模块级常量保持引用稳定。 */
const NO_COUNTY_DETAILS = new Map<string, { trm: string; cat: string }>()

/* 把 Leaflet 实例递到地图卡**外**的控制行：缩放/复位按钮渲染在 MapContainer 之外，
   拿不到 useMap context，故用一个无渲染子组件桥接。顺带移除 Leaflet 默认左上角
   zoom 控件 —— 线框图把「Map Controls」统一放在地图下方控制行右侧，不留两套缩放。 */
function MapControlsBridge({ onMap }: { onMap: (m: ReturnType<typeof useMap> | null) => void }) {
  const map = useMap()
  useEffect(() => {
    map.zoomControl?.remove()
    onMap(map)
    return () => onMap(null)
  }, [map, onMap])
  return null
}

const SectionTitle = ({ icon, title, sub, explain }: {
  icon: React.ReactNode; title: string; sub?: string; explain?: string
}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: '0.5rem 0 0.875rem', padding: '0 0 0.625rem',
    borderBottom: '1px solid rgba(0, 217, 255,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 'var(--wh-radius-sm)',
      background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: '0.875rem',
    }}>{icon}</span>
    <span style={{ fontSize: '1rem', fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {explain ? <ExplainIcon text={explain} placement="bottom" /> : null}
    {sub && <span style={{ fontSize: '0.75rem', color: WH.textDim, marginLeft: 4 }}>{sub}</span>}
  </div>
)

/* 说明气泡统一走 components/MetricExplain（AGENTS.md 三.3/三.3c）：
   此前这里有两份自写气泡（头部标签一份 + 卡片角上一份），复制按钮、主题色、
   `**强调**` 渲染各自一套，改口径要同时记得两处。删掉后由 ExplainPopover / ExplainIcon 承担。 */
const SummaryCard = ({ icon, value, label, color, onClick, explain, t }: {
  icon: React.ReactNode; value: string | number; label: string; color: string; onClick: () => void;
  explain?: string; t: (key: string) => string
}) => (
  <Card size="small" hoverable onClick={onClick} className="wh-card-interactive" style={{
    ...cardStyle,
    cursor: 'pointer', transition: 'all .2s', position: 'relative', overflow: 'hidden',
  }}
    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorderHover }}
    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.border = WH.cardBorder }}
  >
    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: color, opacity: 0.9 }} />
    {explain && (
      <span style={{ position: 'absolute', top: 6, right: 8, zIndex: 2 }}>
        <ExplainIcon text={explain} placement="top" />
      </span>
    )}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div>
        {/* 数字本身也问得到（三.3c）：角上的 ⓘ 讲这一项，鼠标停在大数字上同样出这段构成 */}
        <ExplainPopover placement="bottom" text={explain || ''}>
          <div style={{ fontSize: '1.875rem', fontWeight: 800, color, lineHeight: 1.2, textShadow: `0 0 14px ${color}55` }}>{value}</div>
        </ExplainPopover>
        <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginTop: 'var(--wh-space-xs)', fontWeight: 500 }}>{label}</div>
      </div>
        <span style={{ fontSize: '2.375rem', opacity: 0.16, color }}>{icon}</span>
      </div>
      <div style={{ textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
        {t('pl.clickDrill')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
      </div>
    </Card>
  )

const strSorter = (a: any, b: any, key: string) => String(a[key] ?? '').localeCompare(String(b[key] ?? ''))
const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

interface PlSite {
  site_name: string; site_code: string; lat: number; lng: number
  region: string; province_county: string; gateway: string; network_type: string
  status: string; last_day_max_pl: number; total_pl: number; affected_hours: number
}

export default function PacketLossDashboard() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const isMobile = useIsMobile()
  // 地图档位随窗口宽度换档（见 zoomForWidth / useMapZoom）；
  // MapContainer 与 CountyLabels 吃同一个值，换档时视图与标签避让同步重算。
  const mapZoom = useMapZoom()
  // 县名标签只在宽视口（zoom ≥7.5 档，2/3 列画布 ≥~630px）显示：15 个全名标签在
  // 移动端窄画布（~321px）上几何上装不下、实测重叠不可读。县**底色**不受此限制、
  // 全视口常驻（用户要的「州背景颜色」）；窄图只留色块更干净。
  const showCountyLabels = mapZoom >= 7.5
  // 地图实例：控制行（缩放/复位）在 MapContainer 之外，靠 MapControlsBridge 递出来
  const [mapInstance, setMapInstance] = useState<ReturnType<typeof useMap> | null>(null)
  const METRIC_EXPLAIN = useMemo(() => getMetricExplain(t), [t])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<any>(null)
  const [mapSites, setMapSites] = useState<PlSite[]>([])
  // 默认显示 OK 站点（include_ok=true），地图展示全量有坐标站点
  const [includeOk, setIncludeOk] = useState(true)
  const [hiddenStatuses, setHiddenStatuses] = useState<Set<string>>(new Set())
  // 拓扑显示开关：开启后复用 GIS Map 的真实拓扑链路（/api/gis/topology），按传输类型着色
  const [showTopology, setShowTopology] = useState(false)
  /* 地名注记开关。**默认关闭**：瓦片带 1.7 万个地名，全开时用户反馈
     「密密麻麻，什么都看不清」（2026-10-02），与 GISMap.tsx 同处理。 */
  const [showLabels, setShowLabels] = useState(false)
  /* 底图道路开关。**默认关闭**（2026-11-11 用户要求本页「默认不要显示道路和
     地名」，与 Alarm 页对齐）。此前 2026-10-03 默认开启、2026-10-22 注释里
     「与 GISMap 默认值不同是有意的，别顺手对齐」的说法自本次起作废。 */
  const [showRoads, setShowRoads] = useState(false)
  const [gisTopology, setGisTopology] = useState<any[]>([])
  useEffect(() => {
    if (showTopology && gisTopology.length === 0) {
      api.get('/gis/topology')
        .then(res => setGisTopology(res.data.links || []))
        .catch(() => {})
    }
  }, [showTopology])

  /* 县界（2026-11-11 用户要求「跟其他页面地图一样添加州的背景颜色」）：
     与 GIS / 人员 / ipt 页共用同一份静态 GeoJSON（/gis/county-boundaries，
     后端 1 小时缓存 + 前端 cachedGet 同一缓存键，进过那些页再进本页取数免费）。
     每县一种类别色、80% 实心填充，只表达「这是哪个县」，不带数值语义 ——
     与人员页同一取舍，不铺 GIS 页的告警分档色（那会让人误读为丢包分布）。 */
  const [counties, setCounties] = useState<CountyBoundary[]>([])
  useEffect(() => {
    let alive = true
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => { if (alive) setCounties(res.data?.counties || []) })
      .catch(err => {
        // 不静默：县界拉不到时地图回落为「无县色」，控制台要留下原因
        console.error('[packet_loss] county boundaries failed:', err?.response?.status, err?.response?.data || err)
        if (alive) setCounties([])
      })
    return () => { alive = false }
  }, [])
  const { countyColor } = useCountyTags(counties)
  const toggleStatusVisible = useCallback((st: string) => {
    setHiddenStatuses(prev => {
      const next = new Set(prev)
      if (next.has(st)) next.delete(st); else next.add(st)
      return next
    })
  }, [])

  // 下钻
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillTitle, setDrillTitle] = useState('')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillTotal, setDrillTotal] = useState(0)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)

  // 地图站点点击下钻（2026-11-11 用户要求「站点支持点击下钻，弹窗用项目样式」）：
  // 复用统一 DraggableClickModal，不再用 Leaflet Popup 自造小窗。
  const [siteOpen, setSiteOpen] = useState(false)
  const [siteLoading, setSiteLoading] = useState(false)
  const [siteDetail, setSiteDetail] = useState<any>(null)
  const [siteSel, setSiteSel] = useState<PlSite | null>(null)
  const [siteAnchor, setSiteAnchor] = useState<{ x: number; y: number } | null>(null)
  const [siteSearch, setSiteSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      cachedGet('pl:overview', () => api.get('/packet-loss-dashboard/overview')),
      cachedGet(`pl:map:${includeOk}`, () => api.get('/packet-loss-dashboard/map-sites', { params: { include_ok: includeOk } })),
    ])
      .then(([ov, mp]) => {
        setData(ov.data)
        setMapSites(mp.data.sites || [])
        setError(null)
      })
      .catch(err => { console.error('Packet Loss API error:', err); setError(err.message || 'Failed to load') })
      .finally(() => setLoading(false))
  }, [includeOk])

  const openDrilldown = useCallback((trigger: any, status: string, title: string) => {
    let anchor: { x: number; y: number } | null = null
    if (trigger && typeof trigger.clientX === 'number') {
      anchor = { x: trigger.clientX, y: trigger.clientY }
    } else if (trigger?.event?.event && typeof trigger.event.event.clientX === 'number') {
      anchor = { x: trigger.event.event.clientX, y: trigger.event.event.clientY }
    }
    setDrillAnchor(anchor)
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillTitle(title)
    api.get('/packet-loss-dashboard/drilldown', { params: { status, limit: 800 } })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTotal(res.data.total || 0)
      })
      .catch(() => setDrillTitle('Failed to load data'))
      .finally(() => setDrillLoading(false))
  }, [])

  // 站点下钻：锚点取该站点在屏幕上的投影位置（CircleMarker onClick 无事件对象，
  // 用 mapInstance.latLngToContainerPoint + 容器 rect 换算成 clientX/Y），
  // 让 DraggableClickModal 以点击点为中心弹出，与状态卡下钻同一观感。
  const openSiteDrilldown = useCallback((s: PlSite) => {
    let anchor: { x: number; y: number } | null = null
    if (mapInstance) {
      const pt = mapInstance.latLngToContainerPoint([s.lat, s.lng])
      const rect = mapInstance.getContainer().getBoundingClientRect()
      anchor = { x: rect.left + pt.x, y: rect.top + pt.y }
    }
    setSiteAnchor(anchor)
    setSiteSel(s)
    setSiteOpen(true)
    setSiteLoading(true)
    setSiteDetail(null)
    setSiteSearch('')
    api.get('/packet-loss-dashboard/site-detail', { params: { site_code: s.site_code, site_name: s.site_name } })
      .then(res => setSiteDetail(res.data))
      .catch(() => setSiteDetail(null))
      .finally(() => setSiteLoading(false))
  }, [mapInstance])

  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower)))
  }, [drillData, drillSearch])

  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const fname = `PacketLoss_${dayjs().format('YYYYMMDD_HHmmss')}`
    // 统一走 excelReport：加标题行、表头填充、冻结窗格、列宽与自适应筛选
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: 'PacketLoss',
      title: 'Packet Loss Drill-down',
      header: keys,
      rows,
      numericCols: [],
    })
  }, [filteredDrillData])

  const drillColumns = useMemo(() => {
    if (!drillData.length) return []
    return Object.keys(drillData[0]).map(k => ({
      title: k.replace(/_/g, ' '),
      dataIndex: k,
      key: k,
      minWidth: 130,
      ellipsis: true,
      sorter: (a: any, b: any) => strSorter(a, b, k),
      filters: getUniqueFilters(drillData, k),
      onFilter: (v: any, r: any) => String(r[k]) === v,
    }))
  }, [drillData])

  // ========== 图表配置 ==========
  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const cText = isDark ? '#f5f7ff' : '#16233b'
  const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
  const cTeal = isDark ? '#00d9ff' : '#0d9488'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
  const statusColors = isDark ? STATUS_COLORS : STATUS_COLORS_LIGHT

  const statusPieOption = useMemo(() => {
    if (!data?.status_pie) return {}
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}<br/>{c} sites ({d}%)' },
      /* 图例改底部横排并带计数：竖排 right:0 在窄容器里会压到圆环上、计数被截断
         （2026-11-11 实测 200px 宽时 289 显示成「2…」）。环居中后不再与图例抢空间。 */
      legend: {
        orient: 'horizontal', bottom: 0, left: 'center', itemWidth: 10, itemHeight: 10,
        textStyle: { fontSize: 10, color: cTextMuted },
        formatter: (name: string) => {
          const hit = (data.status_pie || []).find((s: any) => s.status === name)
          return `${STATUS_SHORT[name] || name} ${hit ? hit.count : ''}`
        },
      },
      series: [{
        type: 'pie', radius: ['38%', '62%'], center: ['50%', '44%'],
        data: data.status_pie.map((s: any) => ({
          name: s.status, value: s.count, itemStyle: { color: statusColors[s.status] || cTeal },
        })),
        // 小扇区的外引导线（29/3/0 三条挤在右下角）改由图例计数 + tooltip 承担
        label: { show: false },
        labelLine: { show: false },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(0, 217, 255,0.4)' : 'rgba(13,148,136,0.35)' } },
      }],
    }
  }, [data, isDark, statusColors, cText, cTextMuted, cTeal])

  const regionOption = useMemo(() => {
    if (!data?.region_dist) return {}
    // 仅 3 个类别：竖条在全宽容器里太空，改横条（与 Top Sites 同语言），最大值红色强调
    const entries = (Object.entries(data.region_dist) as [string, any][]).slice().reverse()
    if (!entries.length) return {}
    const maxSites = Math.max(...entries.map(([, b]) => b.sites))
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const b = entries[idx][1]
          return `<div style="font-weight:600;margin-bottom:4px">${entries[idx][0]}</div>` +
            `Affected Sites: <strong>${b.sites}</strong><br/>Critical: <strong>${b.critical}</strong><br/>Max PL: <strong>${b.max_pl.toFixed(2)}%</strong>`
        },
      },
      grid: { left: 8, right: 40, top: 10, bottom: 10, containLabel: true },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { ...axisLabel(isDark), color: cText }, axisLine: axisLine(isDark) },
      series: [{
        type: 'bar', barMaxWidth: 18,
        data: entries.map(([, b]) => ({
          value: b.sites,
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#050d22' : '#dcebf5' }, { offset: 1, color: b.sites === maxSites ? (isDark ? '#ff5c6c' : '#d92d20') : cTeal }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, fontWeight: 600 },
      }],
    }
  }, [data, isDark, cText, cTextMuted, cTeal])

  const trendOption = useMemo(() => {
    if (!data?.daily_trend?.length) return {}
    const days = data.daily_trend.map((d: any) => d.day.slice(5))
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
      legend: { data: [t('pl.median'), t('pl.affectedSites')], bottom: 0, textStyle: { fontSize: 11, color: cTextMuted } },
      grid: { left: 50, right: 50, top: 20, bottom: 50 },
      xAxis: { type: 'category', data: days, axisLabel: axisLabel(isDark), axisLine: axisLine(isDark) },
      yAxis: [
        { type: 'value', name: t('pl.axis'), splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
        { type: 'value', name: t('pl.sites'), splitLine: { show: false }, axisLabel: axisLabel(isDark) },
      ],
      series: [
        {
          name: t('pl.median'), type: 'bar', barMaxWidth: 22,
          data: data.daily_trend.map((d: any) => d.median_pl),
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? '#00d9ff' : '#0d9488' }, { offset: 1, color: isDark ? '#258cff' : '#0284c7' }] },
            borderRadius: [4, 4, 0, 0],
          },
          label: { show: true, position: 'top', fontSize: 10, color: cTextMuted, formatter: (p: any) => `${p.value}%` },
        },
        {
          name: t('pl.affectedSites'), type: 'line', yAxisIndex: 1, smooth: true,
          data: data.daily_trend.map((d: any) => d.affected_sites),
          lineStyle: { color: isDark ? '#ff922b' : '#ea580c', width: 2 }, itemStyle: { color: isDark ? '#ff922b' : '#ea580c' }, symbolSize: 6,
        },
      ],
    }
  }, [data, t, isDark, cTextMuted])

  const topSitesOption = useMemo(() => {
    if (!data?.top_sites?.length) return {}
    const sites = data.top_sites.slice(0, 12).reverse()
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const idx = ps[0].dataIndex
          const s = sites[idx]
          return `<div style="font-weight:600;margin-bottom:4px">${s.site_name}</div>` +
            `Status: <strong>${STATUS_SHORT[s.status] || s.status}</strong><br/>` +
            `Last-1-day Median PL: <strong>${s.last_day_median_pl}%</strong><br/>` +
            `Last-1-day Max PL: ${s.last_day_max_pl}%<br/>` +
            `Affected Hours: <strong>${s.affected_hours}</strong><br/>Region: ${s.region || '-'}`
        },
      },
      // 移入左列窄容器后站名标签靠 containLabel 让位，避免被裁
      grid: { left: 8, right: 48, top: 10, bottom: 24, containLabel: true },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: {
        type: 'category',
        data: sites.map((s: any) => s.site_name.length > 18 ? s.site_name.slice(0, 16) + '..' : s.site_name),
        axisLabel: { ...axisLabel(isDark), color: cText }, axisLine: axisLine(isDark),
      },
      series: [{
        type: 'bar', barMaxWidth: 16,
        data: sites.map((s: any) => ({
          value: s.last_day_median_pl,
          itemStyle: { color: statusColors[s.status] || cTeal, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => `${p.value}%` },
      }],
    }
  }, [data, isDark, statusColors, cText, cTextMuted, cTeal])

  // ===== 站点下钻：逐日图 + 逐小时表 =====
  const siteDailyOption = useMemo(() => {
    const daily = siteDetail?.daily || []
    if (!daily.length) return {}
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
      legend: { data: [t('pl.site.colMax'), t('pl.site.colMedian')], bottom: 0, textStyle: { fontSize: 10, color: cTextMuted } },
      grid: { left: 40, right: 16, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: daily.map((d: any) => d.day.slice(5)), axisLabel: axisLabel(isDark), axisLine: axisLine(isDark) },
      yAxis: { type: 'value', name: '%', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [
        { name: t('pl.site.colMax'), type: 'bar', barMaxWidth: 18, data: daily.map((d: any) => d.max_pl),
          itemStyle: { color: isDark ? '#ff5c6c' : '#d92d20', borderRadius: [3, 3, 0, 0] } },
        { name: t('pl.site.colMedian'), type: 'line', smooth: true, data: daily.map((d: any) => d.median_pl),
          lineStyle: { color: cTeal, width: 2 }, itemStyle: { color: cTeal }, symbolSize: 5 },
      ],
    }
  }, [siteDetail, isDark, t, cTextMuted, cTeal])

  const filteredSiteHourly = useMemo(() => {
    const rows = siteDetail?.hourly || []
    if (!siteSearch.trim()) return rows
    const lo = siteSearch.toLowerCase()
    return rows.filter((r: any) => Object.values(r).some(v => v != null && String(v).toLowerCase().includes(lo)))
  }, [siteDetail, siteSearch])

  const siteHourlyColumns = useMemo(() => [
    { title: t('pl.site.hour'), dataIndex: 'hour', key: 'hour', width: 80, sorter: (a: any, b: any) => String(a.hour).localeCompare(String(b.hour)) },
    { title: t('pl.site.colMax'), dataIndex: 'max_pl', key: 'max_pl', width: 120, sorter: (a: any, b: any) => a.max_pl - b.max_pl, render: (v: number) => `${v}%` },
    { title: t('pl.site.colMedian'), dataIndex: 'median_pl', key: 'median_pl', width: 120, sorter: (a: any, b: any) => a.median_pl - b.median_pl, render: (v: number) => `${v}%` },
    { title: t('pl.site.colReadings'), dataIndex: 'readings', key: 'readings', width: 90, sorter: (a: any, b: any) => a.readings - b.readings },
    { title: t('pl.site.affected'), dataIndex: 'affected', key: 'affected', width: 100,
      render: (v: number) => v ? <Tag color="error">{t('pl.site.affected')}</Tag> : <Tag color="success">{t('pl.site.normal')}</Tag>,
      filters: [{ text: t('pl.site.affected'), value: 1 }, { text: t('pl.site.normal'), value: 0 }],
      onFilter: (v: any, r: any) => r.affected === v },
  ], [t])

  const exportSiteHourly = useCallback(() => {
    if (!filteredSiteHourly.length) return
    const header = [t('pl.site.hour'), t('pl.site.colMax'), t('pl.site.colMedian'), t('pl.site.colReadings'), t('pl.site.affected')]
    const rows = filteredSiteHourly.map((r: any) => [r.hour, r.max_pl, r.median_pl, r.readings, r.affected ? t('pl.site.affected') : t('pl.site.normal')])
    void exportAoaReport({
      filename: `PacketLoss_${siteSel?.site_code || siteSel?.site_name || 'site'}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'SiteDetail',
      title: `${siteSel?.site_name || ''} hourly PL`,
      header, rows, numericCols: [1, 2, 3],
    })
  }, [filteredSiteHourly, siteSel, t])

  // 图例过滤：隐藏选中的状态 → 地图上不渲染对应站点
  // 必须放在 early-return 之前，保证 hook 调用顺序在每次渲染都一致（否则会改变 hook 数量 → 组件崩溃）
  const visibleSites = useMemo(
    () => mapSites.filter(s => !hiddenStatuses.has(s.status)),
    [mapSites, hiddenStatuses],
  )

  /* 县名标签的数字 = 该县**当前可见**的 PL 站点数（随图例过滤 / 显示 OK 开关联动）。
     县名归一化复用 countyOfOrg：province_county 的 'River Cess' 要映射到 GeoJSON
     的 'Rivercess'（与 IPT organization 同一套别名，见 iptPower/countySoc.ts）。
     只用于显示，不参与避让优先级 —— 优先级走静态 site_count，筛选不引起标签跳位
     （IptCountyLayer 同一取舍）。 */
  const countySiteCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const s of visibleSites) {
      const name = countyOfOrg(s.province_county)
      if (name) m.set(name, (m.get(name) || 0) + 1)
    }
    return m
  }, [visibleSites])

  // 拓扑：复用 GIS Map 的真实链路（/api/gis/topology），按传输类型（gateway）着色。
  // 用「可见站点的坐标 → gateway」就近匹配链路两端，判定该链路属于哪种传输类型并取色。
  // 仅绘制至少一端落在当前可见 PL 站点内的链路（随图例显隐联动）。放在 early-return 前，保持 hook 顺序稳定。
  const topology = useMemo(() => {
    const pts: { lat: number; lng: number; gw: string }[] = []
    for (const s of visibleSites) {
      if (s.lat != null && s.lng != null) pts.push({ lat: s.lat, lng: s.lng, gw: s.gateway || '' })
    }
    const TH = 0.006 // ≈ 600m 容差，避免浮点/格式差异导致匹配不上
    const matchGw = (lat: number, lng: number): string => {
      let best = ''; let bd = TH * TH
      for (const p of pts) {
        const d = (p.lat - lat) ** 2 + (p.lng - lng) ** 2
        if (d < bd) { bd = d; best = p.gw }
      }
      return best
    }
    const edges: { positions: [[number, number], [number, number]]; color: string; isHub: boolean }[] = []
    const gwSeen = new Set<string>()
    for (const l of gisTopology) {
      const gw = matchGw(l.lat_a, l.lng_a) || matchGw(l.lat_b, l.lng_b)
      if (!gw) continue // 两端都不在当前可见 PL 站点内 → 跳过
      gwSeen.add(gw)
      edges.push({
        positions: [[l.lat_a, l.lng_a], [l.lat_b, l.lng_b]],
        color: gwColor(gw),
        /* 2026-09-25 数据源换成 kml_mw_links 后，后端不再提供 a_is_hub/b_is_hub，
           is_hub_link 恒为 false —— 若继续用它做线宽加粗，所有链路会一起变细。
           改用 KML 原作者的线色语义：红/黄是重点链路（少量、需强调），
           蓝/绿是常规链路（量大）。这样既保留加粗效果，又与 GIS 页的线色语义一致。 */
        isHub: l.color === '#ff3b30' || l.color === '#ffcc00',
      })
    }
    return { edges, gateways: [...gwSeen] }
  }, [visibleSites, gisTopology])

  // ========== 渲染 ==========
  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '3.75rem' }}>
      <Spin size="large" />
      <div style={{ marginTop: '0.75rem', color: WH.textMuted }}>{t('pl.loading')}</div>
    </div>
  )
  if (error) return <Alert type="error" message={t('pl.loadFailed')} description={error} showIcon style={{ margin: 'var(--wh-space-md)' }} />
  if (!data) return <Empty description={t('pl.noData')} />

  const sc = data.status_counts || {}
  const fmt = (n: number) => (n ?? 0).toLocaleString(numLocale(locale))
  const chartClick = (titlePrefix: string) => (p: any) => openDrilldown(p, p.name, `${titlePrefix} = ${STATUS_SHORT[p.name] || p.name}`)

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {/* 1. 头部横幅（全宽） */}
      <Card size="small" style={{
        ...cardStyle,
        background: isDark ? 'linear-gradient(135deg, #101a2e 0%, #050d22 100%)' : 'linear-gradient(135deg, #eef4fa 0%, #e0edf7 100%)',
        borderLeft: isDark ? '4px solid #ff5c6c' : '4px solid #d92d20',
        marginBottom: 'var(--wh-space-xs)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)', flexWrap: 'wrap' }}>
            <DisconnectOutlined style={{ fontSize: '1.375rem', color: WH.teal }} />
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: WH.text }}>{t('pl.status')}</span>
            <ExplainPopover text={METRIC_EXPLAIN['Affected Sites']} placement="bottom">
              <Tag color="error" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 600, cursor: 'pointer' }}
                onClick={e => openDrilldown(e, 'all', 'Sites with Packet Loss')}>
                {fmt(data.affected_sites)} {t('pl.affectedSites')}
              </Tag>
            </ExplainPopover>
            <ExplainPopover text={METRIC_EXPLAIN['Data Granularity']} placement="bottom">
              <Tag color="cyan" style={{ borderRadius: 'var(--wh-radius-lg)', fontWeight: 600 }}>{t('pl.granularity')}</Tag>
            </ExplainPopover>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-md)', fontSize: '0.75rem', color: WH.textDim }}>
            <ClockCircleOutlined />
            <span>{t('pl.updated')}: {data.generated_at ? String(data.generated_at).replace('T', ' ').slice(0, 19) : 'N/A'}</span>
          </div>
        </div>
      </Card>

      {/* 2. 核心指标卡片 */}
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} lg={4}>
          <SummaryCard icon={<EnvironmentOutlined />} value={fmt(data.total_sites)} label={t('pl.totalSites')} color={WH.teal}
            explain={METRIC_EXPLAIN['Total Sites']}
            onClick={() => openDrilldown(null, 'all', 'All Sites')} t={t} />
        </Col>
        {STATUS_ORDER.filter(s => s !== 'No Packet loss[<0.1]').map(st => (
          <Col xs={12} sm={8} lg={4} key={st}>
            <SummaryCard
              icon={st === 'Critical[>5]' ? <AlertOutlined /> : st === 'Major[1-5]' ? <WarningOutlined /> : <DashboardOutlined />}
              value={fmt(sc[st] || 0)} label={STATUS_SHORT[st]} color={STATUS_COLORS[st]}
              explain={METRIC_EXPLAIN[STATUS_SHORT[st]]}
              onClick={() => openDrilldown(null, st, st)} t={t} />
          </Col>
        ))}
        <Col xs={12} sm={8} lg={4}>
          <SummaryCard icon={<CheckCircleOutlined />} value={fmt(sc['No Packet loss[<0.1]'] || 0)} label={t('pl.noPacketLoss')} color={STATUS_COLORS['No Packet loss[<0.1]']}
            explain={METRIC_EXPLAIN['No Packet loss']}
            onClick={() => openDrilldown(null, 'No Packet loss[<0.1]', 'No Packet loss[<0.1]')} t={t} />
        </Col>
      </Row>

      {/* 3. 两列（2026-11-11 按用户线框图重排）：左 2/3 = 大地图卡（地图 + 下方控制行），
          右 1/3 = 饼图 / 趋势 / 区域三卡竖排；Top 10 移到下方全宽（见第 4 块）。
          移动端竖排、地图紧跟 KPI。桌面 alignItems:stretch 让左卡与右列同高，
          地图画布 flex:1 填满左卡剩余高度 —— 不留线框图里地图下方的空白带。 */}
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: '0.75rem', alignItems: 'stretch' }}>
      <div style={isMobile
        ? { width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column' }
        : { flex: '0 0 66.666%', width: '66.666%', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Card size="small"
          style={{ ...cardStyle, marginBottom: 0, flex: 1, display: 'flex', flexDirection: 'column' }}
          styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 } }}
          title={
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.map')} ({t('pl.mapAffected', { n: data?.affected_sites ?? 0 })})
              <span style={{ marginLeft: 8, fontWeight: 400, fontSize: '0.6875rem', color: WH.textDim }}>{t('pl.site.clickHint')}</span>
            </span>
          }>
          {/* 2026-09-29：滚轮即缩放，不再区分是否内嵌（与 GISMap.tsx 同步改动）。
              Leaflet 默认 scrollWheelZoom=true，故不再显式传参。
              桌面 flex:1 填满左卡（大地图展示区）；移动端固定 55vh。 */}
          <MapContainer center={PL_MAP_CENTER} zoom={mapZoom} style={isMobile
            ? { height: '55vh', minHeight: '18.75rem', width: '100%', background: 'var(--wh-page-bg)', borderRadius: 'var(--wh-radius-md)' }
            : { flex: 1, minHeight: '26rem', width: '100%', background: 'var(--wh-page-bg)', borderRadius: 'var(--wh-radius-md)' }}>
            {/* 档位同步：MapContainer 挂载后不再吃 zoom prop，换档由它 setView。
                不传 shift*：本页无左右浮层遮挡问题，不需要 GIS 页那套像素平移。 */}
            <MapController center={PL_MAP_CENTER} zoom={mapZoom} />
            {/* 递出地图实例给下方控制行的缩放/复位按钮，并移除默认左上 zoom 控件 */}
            <MapControlsBridge onMap={setMapInstance} />
            <PmtilesLayer
              url={BASEMAP_PMTILES_URL}
              isDark={isDark}
              maxZoom={BASEMAP_MAX_ZOOM}
              showLabels={showLabels}
              showRoads={showRoads}
            />
            {/* 县类别色底图：与人员页同一组件（装饰层 interactive:false，不抢
                站点圆点的点击）。先于拓扑线与站点圆点渲染，保证后两者压在其上。
                2026-11-11 用户「州的颜色的透明度改成 80%」→ **不透明度 0.2**
                （共用 COUNTY_FILL_OPACITY 的 0.8 是「不透明度 80%」，语义相反，
                不能直接改那个常量 —— 人员页仍要 0.8）。填充变淡后县名标签的
                深色主题对比度由下方 labelClass="pl-county-label" 配套处理。 */}
            <CountyLayer counties={counties} countyColor={countyColor} isDark={isDark} fillOpacity={0.2} />
            {/* 拓扑连线：复用 GIS Map 真实链路，按传输类型着色（MW / IPRAN 等）。
                先白色描边(casing)增强对比，再画彩色线；hub 链路更粗。 */}
            {showTopology && topology.edges.map((e, i) => (
              <Polyline key={`topo-c-${i}`} positions={e.positions}
                pathOptions={{ color: '#ffffff', weight: e.isHub ? 5 : 3, opacity: 0.3, interactive: false }} />
            ))}
            {showTopology && topology.edges.map((e, i) => (
              <Polyline key={`topo-${i}`} positions={e.positions}
                pathOptions={{ color: e.color, weight: e.isHub ? 3 : 1.8, opacity: 0.9, interactive: false }} />
            ))}
            {visibleSites.map(s => (
              <CircleMarker key={`${s.site_name}|${s.site_code}`} center={[s.lat, s.lng]}
                radius={Math.min(12, 5 + Math.log1p(s.last_day_max_pl) * 2)}
                fillColor={STATUS_COLORS[s.status] || WH.teal} color="#fff" weight={1} fillOpacity={0.85}
                onClick={() => openSiteDrilldown(s)} />
            ))}
            {/* 县名 + 可见站点数标签：紧凑样式（11px/10px、pointer-events:none，
                不拦圆点 Popup 的点击），数字随图例过滤联动；避让随换档（mapZoom）
                重算一次，手动滚轮缩放后标签跟着县走不重排 —— 与人员 / ipt 页同一取舍。
                仅宽视口渲染（showCountyLabels）：窄画布装不下 15 个全名标签，
                实测重叠不可读，故窄图只留县底色（见 showCountyLabels 注释）。 */}
            {showCountyLabels && (
              <CountyLabels
                counties={counties}
                typeLines={NO_COUNTY_DETAILS}
                center={PL_MAP_CENTER}
                zoom={mapZoom}
                displayCount={countySiteCounts}
                compact
                tipKey="pl.countyTagTip"
                labelClass="pl-county-label"
              />
            )}
          </MapContainer>
          {showTopology && topology.gateways.length > 0 && (
            <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', marginTop: '0.375rem', marginBottom: '0.125rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: '0.6875rem', color: WH.textMuted, fontWeight: 600 }}>{t('pl.topoLabel')}:</span>
              {topology.gateways.map(gw => (
                <span key={gw} style={{ fontSize: '0.6875rem', color: WH.textMuted, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 14, height: 4, borderRadius: 2, background: gwColor(gw), display: 'inline-block' }} />
                  {gw}
                </span>
              ))}
              <span style={{ fontSize: '0.625rem', color: WH.textDim }}>{t('pl.topoHint')}</span>
            </div>
          )}
          {/* 控制行（线框图）：左 = Layers · Topology · Site Filters，右 = Map Controls。
              图层开关由地图内浮层改为行内复选框，地图画面更干净；缩放/复位集中右侧。 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginTop: 'var(--wh-space-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-md)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
                <span style={{ fontSize: '0.6875rem', fontWeight: 600, color: WH.textMuted }}>{t('gis.layerTitle')}</span>
                <label style={CTL_LABEL} title={t('gis.layerLabelsHint')}>
                  <input type="checkbox" checked={showLabels} onChange={e => setShowLabels(e.target.checked)} style={{ margin: 0, cursor: 'pointer' }} />
                  {t('gis.layerLabels')}
                </label>
                <label style={CTL_LABEL} title={t('gis.layerRoadsHint')}>
                  <input type="checkbox" checked={showRoads} onChange={e => setShowRoads(e.target.checked)} style={{ margin: 0, cursor: 'pointer' }} />
                  {t('gis.layerRoads')}
                </label>
              </span>
              <Button size="small" type={showTopology ? 'primary' : 'default'}
                icon={<ApartmentOutlined />} onClick={() => setShowTopology(v => !v)}
                style={{ height: 22, fontSize: '0.6875rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {t('pl.topology')}
              </Button>
              <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
                <span style={{ fontSize: '0.6875rem', color: WH.textMuted }}>{t('pl.showOk')}</span>
                <Switch size="small" checked={includeOk} onChange={setIncludeOk} />
              </span>
              <span style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                {STATUS_ORDER.map(st => {
                  const hidden = hiddenStatuses.has(st)
                  return (
                    <span key={st} onClick={() => toggleStatusVisible(st)}
                      title={hidden ? t('pl.showOnMap') : t('pl.hideOnMap')}
                      style={{
                        fontSize: '0.6875rem', cursor: 'pointer', userSelect: 'none',
                        color: hidden ? WH.textDim : WH.textMuted,
                        opacity: hidden ? 0.45 : 1,
                        textDecoration: hidden ? 'line-through' : 'none',
                        display: 'flex', alignItems: 'center', gap: 4,
                      }}>
                      <span style={{ width: 10, height: 10, borderRadius: '50%', background: STATUS_COLORS[st], display: 'inline-block', opacity: hidden ? 0.3 : 1 }} />
                      {STATUS_SHORT[st]}
                    </span>
                  )
                })}
              </span>
            </div>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.6875rem', color: WH.textMuted, fontWeight: 600 }}>{t('pl.mapControls')}</span>
              <Button size="small" icon={<MinusOutlined />} style={CTL_BTN} title={t('pl.zoomOut')}
                onClick={() => mapInstance?.setZoom(mapInstance.getZoom() - 0.5)} />
              <Button size="small" icon={<PlusOutlined />} style={CTL_BTN} title={t('pl.zoomIn')}
                onClick={() => mapInstance?.setZoom(mapInstance.getZoom() + 0.5)} />
              <Button size="small" icon={<UndoOutlined />} style={CTL_BTN} title={t('pl.resetView')}
                onClick={() => mapInstance?.setView(PL_MAP_CENTER, mapZoom)} />
            </span>
          </div>
        </Card>
      </div>

      {/* ===== 右侧 1/3：三图竖排（线框图 Loss Distribution / Daily Trend / Regional Distribution）===== */}
      <div style={isMobile
        ? { width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)' }
        : { flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)' }}>
        <Card size="small" style={cardStyle} title={
          <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {t('pl.lossDistribution')} <ExplainIcon text={t('pl.explain.dist')} placement="bottom" />
          </span>}>
          <ReactECharts option={statusPieOption} style={{ height: CHART_HEIGHT }} onEvents={{ click: chartClick('Status') }} />
        </Card>
        <Card size="small" style={cardStyle} title={
          <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.dailyTrend')}</span>}>
          <ReactECharts option={trendOption} style={{ height: CHART_HEIGHT }} />
        </Card>
        <Card size="small" style={cardStyle} title={
          <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.byRegion')}</span>}>
          <ReactECharts option={regionOption} style={{ height: CHART_HEIGHT }} />
        </Card>
      </div>
      </div>

      {/* 4. Top 10 站点：线框图要求底部**全宽**横条排名（不再挤在左列窄容器） */}
      <SectionTitle icon={<PieChartOutlined />} title={t('pl.topSites')} sub={t('pl.topSitesSub')}
        explain={t('pl.explain.topSites')} />
      <Card size="small" title={<span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.topSitesTitle')}</span>} style={cardStyle}>
        <ReactECharts option={topSitesOption} style={{ height: 380 }} />
      </Card>

      {/* 下钻弹窗 */}
      <DraggableClickModal
        open={drillOpen}
        anchor={drillAnchor}
        onClose={() => setDrillOpen(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <ExplainPopover placement="bottom" text={t('pl.tip.drillCount', { n: filteredDrillData.length, total: drillData.length })}><Tag color="cyan" style={{ borderRadius: 10 }}>{t('pl.records', { n: filteredDrillData.length })}</Tag></ExplainPopover></span>}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
          <Input prefix={<SearchOutlined />} placeholder={t('pl.searchPlaceholder')} allowClear size="middle"
            style={{ width: 'min(100%, 21.875rem)' }} value={drillSearch} onChange={e => setDrillSearch(e.target.value)} />
          <Button type="primary" icon={<DownloadOutlined />} onClick={exportToExcel} disabled={!filteredDrillData.length}>
            {t('pl.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table dataSource={filteredDrillData} columns={drillColumns} size="small"
              rowKey={(r: any) => r.Site_Name}
              pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => `${total} ${t('pl.items')}` }}
              scroll={{ x: 'max-content' }} />
          </div>
        )}
      </DraggableClickModal>

      {/* 站点下钻弹窗（地图圆点点击，2026-11-11）：统一 DraggableClickModal，不自造小窗。
          关键指标 + 逐日图 + 逐小时表（搜索 / 导出），口径与状态卡 / Top 站点一致。 */}
      <DraggableClickModal
        open={siteOpen}
        anchor={siteAnchor}
        onClose={() => setSiteOpen(false)}
        width="min(94%, 62rem)"
        placement="top"
        title={
          <span style={{ color: WH.text, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            {siteSel?.site_name}{siteSel?.site_code ? ` (${siteSel.site_code})` : ''}
            {siteSel && <Tag color={siteSel.status === 'No Packet loss[<0.1]' ? 'success' : 'error'} style={{ borderRadius: 10 }}>{STATUS_SHORT[siteSel.status] || siteSel.status}</Tag>}
          </span>
        }
      >
        {siteLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : !siteDetail?.site ? (
          <Empty description={t('pl.site.loadFailed')} />
        ) : (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-md)', alignItems: 'center', marginBottom: '0.75rem' }}>
              <ExplainPopover placement="bottom" text={t('pl.site.explainStats')}>
                <span style={{ display: 'inline-flex', gap: 'var(--wh-space-md)', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.75rem', color: WH.textMuted }}>{t('pl.popup.maxPL')}: <strong style={{ color: statusColors[siteDetail.site.status] || cTeal, fontSize: '1rem' }}>{siteDetail.site.last_day_max_pl}%</strong></span>
                  <span style={{ fontSize: '0.75rem', color: WH.textMuted }}>{t('pl.popup.totalPL')}: <strong style={{ color: WH.text, fontSize: '1rem' }}>{siteDetail.site.total_pl}%</strong></span>
                  <span style={{ fontSize: '0.75rem', color: WH.textMuted }}>{t('pl.popup.affectedHours')}: <strong style={{ color: WH.text, fontSize: '1rem' }}>{siteDetail.site.affected_hours}</strong></span>
                </span>
              </ExplainPopover>
              <span style={{ fontSize: '0.75rem', color: WH.textDim }}>
                {t('pl.popup.region')}: {siteDetail.site.region || '-'} / {siteDetail.site.province_county || '-'} · {t('pl.popup.gateway')}: {siteDetail.site.gateway || '-'} · {t('pl.popup.network')}: {siteDetail.site.network_type || '-'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '0.25rem 0' }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.site.dailyTitle')}</span>
              <ExplainIcon text={t('pl.site.explainDaily')} placement="bottom" />
            </div>
            {siteDetail.daily?.length ? (
              <ReactECharts option={siteDailyOption} style={{ height: 200 }} />
            ) : (
              <Empty description={t('pl.site.noDetail')} />
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '0.75rem 0 0.5rem' }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{t('pl.site.hourlyTitle', { day: siteDetail.hourly_day || '-' })}</span>
              <ExplainIcon text={t('pl.site.explainHourly')} placement="bottom" />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
              <Input prefix={<SearchOutlined />} placeholder={t('pl.searchPlaceholder')} allowClear size="middle"
                style={{ width: 'min(100%, 21.875rem)' }} value={siteSearch} onChange={e => setSiteSearch(e.target.value)} />
              <Button type="primary" icon={<DownloadOutlined />} onClick={exportSiteHourly} disabled={!filteredSiteHourly.length}>
                {t('pl.exportExcel')}
              </Button>
            </div>
            <div className="wh-table-responsive">
              <Table dataSource={filteredSiteHourly} columns={siteHourlyColumns} size="small"
                rowKey={(r: any) => r.hour}
                pagination={{ pageSize: 12, size: 'small', showTotal: (total: number) => `${total} ${t('pl.items')}` }}
                scroll={{ x: 'max-content' }} />
            </div>
          </>
        )}
      </DraggableClickModal>
    </div>
  )
}
