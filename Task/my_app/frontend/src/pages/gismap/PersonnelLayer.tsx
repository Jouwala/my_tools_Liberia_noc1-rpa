/* GIS 人员图层（2026-10-16 新增）
 *
 * 需求（用户原话）：「页面可以添加个按钮来显示人员位置，使用小人的图标，
 * 点击人员可以看到属于该人员的 WO 信息；点击 WO 地图可以显示人员和站点的路线规划。」
 *
 * 本组件**自包含**：工具栏开关按钮 + 人员小人标记 + WO 弹窗 + 路线连线，
 * 全部收在这一个文件里，GISMap.tsx 只负责把 <PersonnelLayer> 挂进地图。
 * 这样做的理由：GISMap.tsx 已 1600+ 行，把人员逻辑再塞进去会让它继续膨胀
 * （AGENTS.md 第三节 2 要求单个文件不超 500 行、接近上限先拆边界）。
 *
 * ⚠ 三个**必须**如实呈现的已知限制（否则会被当成 bug，见后端 personnel.py 头注释）：
 *   1. 只有 26/136 人有坐标（`person` 表），界面要说明覆盖率，别让人以为漏了人；
 *   2. 坐标是**静态登记值、不是实时定位**（无 GPS 时间戳/轨迹），界面必须标注；
 *   3. 人员↔WO 靠姓名匹配（无外键），有漏配可能。
 *
 * ⚠ 只在 mode==='all'（gis 页）渲染 —— realtime_alarm 页不挂本组件。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Badge, Button, Empty, Spin, Table, Tag, Tooltip } from 'antd'
import { EnvironmentOutlined, UserOutlined } from '@ant-design/icons'
import api from '../../api'
import { useI18n } from '../../i18n'
import DraggableClickModal from '../../components/DraggableClickModal'
import { Marker, Polyline, useMap, isMapAlive } from '../../components/LeafletMap'
import { SITE_COLORS } from './types'

export interface PersonMarker {
  name: string
  name_key: string
  lat: number
  lng: number
  phone: string
  managed_regions: string
  status: string
  /** 未关闭 WO 数 */
  wo_count: number
  /** 全部 WO 数（含已关闭）—— 标签显示 WO:开/总 */
  wo_count_total: number
}

interface PersonWorkOrder {
  wo_no: string
  tt_no?: string
  title?: string
  status?: string
  creator?: string
  created_time?: string
  last_modified_time?: string
  operation_step?: string
  ticket_severity?: string
  alarm_severity?: string
  ne_type?: string
  vendor?: string
  /** 传输类型（后端取 eflow_wo.domain：TRM_MW/TRM_IPRAN/TRM_DWDM…） */
  domain?: string
  alarm_occur_time?: string
  alarm_clear_time?: string
  /** 告警时长（库内形如 0d4h27m） */
  fault_duration_time?: string
  sla_time?: string
  site_id?: string
  site_name?: string
  site_type?: string
  region?: string
  lat: number | null
  lng: number | null
}

interface RouteResult {
  mode: 'osrm' | 'straight'
  degraded: boolean
  reason?: string | null
  distance_m: number
  duration_s: number | null
  geometry: { type: 'LineString'; coordinates: [number, number][] }
}

/** 悬停连线的终点：该人员有未关闭 WO 且站点当前有实时告警 */
interface AlertSite {
  site_id: string
  site_name: string
  region: string
  lat: number
  lng: number
  open_wo: number
}

/** HTML 转义 —— 姓名/电话来自数据库，直接拼进 divIcon 的 html 字符串里，
 *  若含 `<` `&` `"` 会破坏结构甚至注入。**所有拼进 html 的动态值都必须过这里**
 *  （AGENTS.md 三.4：外部输入一律视为不可信）。 */
function escapeHtml(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 人员「地图针」图标：内联 SVG（项目原则是不引图片资源，见 LeafletMap.tsx 文件头）。
 *
 * 造型参照用户给的参考图（2026-10-16）：水滴形地图针（上圆下尖）+
 * 正上方一个白色圆底 + 圆底内的人形剪影；针尖带一小段白色高光点。
 *  - `color` 由外部按主题/选中态给（深色主题浅蓝、浅色主题蓝、选中态红）；
 *  - 尺寸用 viewBox 等比缩放（`width`/`height` = s，viewBox 固定 24×36），
 *    这样换尺寸不会把造型拉变形。
 *  - 选中态：下方再描一圈半透明白色外发光，让人一眼看到「当前选中的人」。
 */
function personIconSvg(color: string, size: number, selected: boolean): string {
  const s = size
  const glow = selected
    ? `<path d="M12 0.5 C5.1 0.5 0.2 5.4 0.2 12.2 C0.2 17.6 4.9 23.2 10.2 30.6 C10.7 31.3 11.3 32.5 12 34 C12.7 32.5 13.3 31.3 13.8 30.6 C19.1 23.2 23.8 17.6 23.8 12.2 C23.8 5.4 18.9 0.5 12 0.5 Z" fill="#fff" opacity="0.55"/>`
    : ''
  return `
<svg width="${s}" height="${s * 1.5}" viewBox="0 0 24 36" xmlns="http://www.w3.org/2000/svg">
  ${glow}
  <!-- 水滴形针身 -->
  <path d="M12 1.5 C6 1.5 1.2 6.3 1.2 12.3 C1.2 17.5 6.2 23.4 12 32.5 C17.8 23.4 22.8 17.5 22.8 12.3 C22.8 6.3 18 1.5 12 1.5 Z"
        fill="${color}" stroke="#fff" stroke-width="1.2"/>
  <!-- 白色圆底 -->
  <circle cx="12" cy="12.2" r="6.1" fill="#fff"/>
  <!-- 人形剪影：头 + 肩 -->
  <circle cx="12" cy="10.2" r="2.5" fill="${color}"/>
  <path d="M7.4 17.2 C7.4 13.9 9.4 12.6 12 12.6 C14.6 12.6 16.6 13.9 16.6 17.2 Z"
        fill="${color}"/>
</svg>`
}

/** 工具栏开关按钮。与图层主体分开导出 —— 按钮在工具栏（控制卡片里），
 *  而小人/路线/弹窗必须挂在地图容器内，两者 DOM 位置不同，故拆成两个组件，
 *  由调用方（GISMap）持有 `enabled` 状态统一控制。 */
export function PersonnelToggleButton({
  enabled, loading, onToggle,
}: {
  enabled: boolean
  loading: boolean
  onToggle: () => void
}) {
  const { t } = useI18n()
  return (
    <Tooltip title={t('gis.person.toggleHint')}>
      <Button
        size="small"
        type={enabled ? 'primary' : 'default'}
        icon={<UserOutlined />}
        onClick={onToggle}
        loading={loading && enabled}
      >
        {t('gis.person.toggle')}
      </Button>
    </Tooltip>
  )
}

export function PersonnelLayer({
  isDark, enabled, timeRange,
}: {
  isDark: boolean
  /** 是否显示人员图层。状态由 GISMap 持有（工具栏按钮在那边）。 */
  enabled: boolean
  /** 页面「时间窗口」筛选（与地图站点统计同口径）。null = 全部时间，不过滤。
      2026-10-16 修：原先人员标签数字未跟随该筛选，用户指出后补上。 */
  timeRange: { start: string; end: string } | null
}) {
  const { t } = useI18n()
  const map = useMap()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [people, setPeople] = useState<PersonMarker[]>([])
  const [totalAll, setTotalAll] = useState<number>(0)

  // 选中的人员 + 其 WO 弹窗
  const [activePerson, setActivePerson] = useState<PersonMarker | null>(null)
  const [woModalOpen, setWoModalOpen] = useState(false)
  const [woModalAnchor, setWoModalAnchor] = useState<{ x: number; y: number } | null>(null)
  const [woLoading, setWoLoading] = useState(false)
  const [woList, setWoList] = useState<PersonWorkOrder[]>([])
  const [woTruncated, setWoTruncated] = useState(false)

  // 路线
  const [route, setRoute] = useState<RouteResult | null>(null)
  const [routeTarget, setRouteTarget] = useState<{ lat: number; lng: number } | null>(null)
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState<string | null>(null)

  /* 悬停连线（2026-10-16 用户需求）：鼠标悬停某人 → 画该人到他
     「未关闭 WO 且有实时告警」站点的所有连线；移出/点击后消失。
     `hoverSites` 存当前要画的站点；`hoverKey` 记录是谁的，避免陈旧响应覆盖。 */
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [hoverSites, setHoverSites] = useState<AlertSite[]>([])
  // 每人只取一次，避免来回悬停反复打接口
  const siteCacheRef = useRef<Map<string, AlertSite[]>>(new Map())

  /* 点击地图空白处 → 清除「选中的人员」与「已画的路线」（2026-10-16 用户要求：
     「点击人员选中，点击其他地方要恢复未选中状态，道路也是一样」）。

     为什么要区分「点人」与「点空白」：
       Leaflet 的 marker 点击会**冒泡到 map**，即点人也会触发 map 的 click。
       若不区分，点人的瞬间就会被 map 处理器立刻清空选中态 —— 表现为「点不中」。

     判别方式（两条互为保险，不依赖二者的事件触发顺序）：
       ① 事件源：Leaflet 把原始点击层放在 `e.sourceTarget`，点人时它是 marker → 跳过；
       ② 标志位：handlePersonClick 置位 personClickRef，兜底那些 sourceTarget
          不可靠的场景。两者命中任一即视为「点的是人」，不清理。 */
  const personClickRef = useRef(false)

  const clearSelection = useCallback(() => {
    setActivePerson(null)
    setWoModalOpen(false)
    setRoute(null)
    setRouteTarget(null)
    setRouteError(null)
  }, [])

  useEffect(() => {
    // map 实例可能随 GIS 页重建；isMapAlive 守卫避免对已销毁的 map 挂事件
    if (!enabled || !isMapAlive(map)) return
    const onMapClick = (e: any) => {
      // ① 事件源判定：点在**人员针**上不清理。
      //    识别方式：L.Marker 独有 `setIcon`（divIcon 换图用），而站点圆点
      //    （L.CircleMarker）只有 setStyle/setRadius、没有 setIcon
      //    —— 两者都能 getLatLng，故**不能**用 getLatLng 区分（实测踩过：
      //    会误把「点站点圆点」当成「点人员」而漏清选中态）。
      const src = e?.sourceTarget
      if (src && typeof src.setIcon === 'function') {
        personClickRef.current = false
        return
      }
      // ② 标志位兜底
      if (personClickRef.current) {
        personClickRef.current = false
        return
      }
      clearSelection()
    }
    map.on('click', onMapClick)
    return () => {
      map.off('click', onMapClick)
    }
  }, [enabled, map, clearSelection])

  /* 开启图层时才取数（不在页面加载时就打接口）—— 绝大多数用户不看这一层，
     常驻请求白费流量。关闭图层时清空路线与选中态。 */
  // 时间窗口参数（三处请求共用）：null（全部时间）时不带任何时间参数，后端即不过滤。
  // 与 GIS 站点统计**同一对参数名**，保证两边口径一致。
  const timeParams = useMemo<Record<string, string>>(() => {
    const p: Record<string, string> = {}
    if (timeRange) {
      p.time_start = timeRange.start
      p.time_end = timeRange.end
    }
    return p
  }, [timeRange])

  const loadPeople = useCallback(() => {
    setLoading(true)
    setError(null)
    api.get('/gis/personnel', { params: timeParams })
      .then(res => {
        setPeople(res.data.personnel || [])
        setTotalAll(res.data.total_all || 0)
      })
      .catch(err => {
        console.error('[PersonnelLayer] load failed:', err?.response?.status, err?.response?.data || err)
        setPeople([])
        setError(t('gis.person.loadFailed'))
      })
      .finally(() => setLoading(false))
  }, [t, timeRange])

  useEffect(() => {
    if (enabled) loadPeople()
    else {
      // 关闭图层：清掉所有叠加物，避免残留的小人/路线让人误会
      // 关闭图层：清掉所有叠加物，避免残留的小人/路线让人误会
      setActivePerson(null)
      setWoModalOpen(false)
      setRoute(null)
      setRouteTarget(null)
      setRouteError(null)
      setHoverKey(null)
      setHoverSites([])
    }
  }, [enabled, loadPeople])

  /* 悬停：拉该人员的告警站点集合并显示连线。
     用 hoverKey 守卫陈旧响应 —— 快速划过多人时，先发的请求可能后到，
     若不加守卫会把「上一个人的线」画在「现在这个人」身上。 */
  const handlePersonHover = (p: PersonMarker) => {
    setHoverKey(p.name_key)
    // 缓存键含时间窗口：窗口变了必须重取，否则会把「上一个窗口」的线画出来
    const cacheKey = `${p.name_key}|${timeParams.time_start || ''}|${timeParams.time_end || ''}`
    const cached = siteCacheRef.current.get(cacheKey)
    if (cached) {
      setHoverSites(cached)
      return
    }
    setHoverSites([])
    // 悬停连线同样跟随时间窗口（否则窗口设为 7 天时，线仍画「全部时间」的站点）
    api.get(`/gis/personnel/${encodeURIComponent(p.name_key)}/alert-sites`,
      { params: timeParams })
      .then(res => {
        const sites: AlertSite[] = res.data.sites || []
        siteCacheRef.current.set(cacheKey, sites)
        // 仅当悬停的仍是同一个人才落图（防陈旧覆盖）
        setHoverKey(cur => {
          if (cur === p.name_key) setHoverSites(sites)
          return cur
        })
      })
      .catch(err => {
        console.error('[PersonnelLayer] alert-sites failed:', err?.response?.status, err?.response?.data || err)
        // 悬停失败不弹错（属于辅助信息），静默为「无线」，但留控制台日志
        siteCacheRef.current.set(cacheKey, [])
        setHoverKey(cur => {
          if (cur === p.name_key) setHoverSites([])
          return cur
        })
      })
  }

  /** 移出人员：清除悬停连线。 */
  const handlePersonHoverOut = (p: PersonMarker) => {
    // 只有当移出的正是当前悬停的人时才清 —— 避免「从 A 移到 B」时
    // A 的 mouseout 把 B 刚画的线清掉（两个事件顺序不保证）。
    setHoverKey(cur => {
      if (cur === p.name_key) {
        setHoverSites([])
        return null
      }
      return cur
    })
  }

  const handlePersonClick = (p: PersonMarker, e?: { originalEvent?: MouseEvent }) => {
    // 标记「这次点击来自人员」，供 map 的 click 处理器跳过（Leaflet 冒泡，见 personClickRef 注释）
    personClickRef.current = true
    // 点击即清除悬停连线（用户要求「点击后消失」）
    setHoverKey(null)
    setHoverSites([])
    setActivePerson(p)
    // Leaflet 事件对象的原始 DOM 事件在 originalEvent（取点给弹窗定位用）
    const oe = e?.originalEvent
    setWoModalAnchor(oe ? { x: oe.clientX, y: oe.clientY } : null)
    setWoModalOpen(true)
    setWoLoading(true)
    setWoList([])
    setWoTruncated(false)
    // 默认只看未关闭单 + 跟随时间窗口 —— 与人员列表的 wo_count 同口径（见后端注释）
    api.get(`/gis/personnel/${encodeURIComponent(p.name_key)}/work-orders`,
      { params: timeParams })
      .then(res => {
        setWoList(res.data.wo_list || [])
        setWoTruncated(!!res.data.meta?.truncated)
      })
      .catch(err => {
        console.error('[PersonnelLayer] work-orders failed:', err?.response?.status, err?.response?.data || err)
        setWoList([])
      })
      .finally(() => setWoLoading(false))
  }

  /* 点击某条 WO → 关闭弹窗、画人员到该 WO 所属站点的路线。
     WO 自身无经纬度（后端已补站点坐标），故路线终点 = 站点坐标。 */
  const handleWoClick = (wo: PersonWorkOrder) => {
    if (!activePerson) return
    if (wo.lat == null || wo.lng == null) {
      setRouteError(t('gis.person.woNoCoord'))
      return
    }
    setWoModalOpen(false)
    setRouteLoading(true)
    setRouteError(null)
    setRoute(null)
    setRouteTarget({ lat: wo.lat, lng: wo.lng })
    api.get('/gis/route', {
      params: {
        from_lat: activePerson.lat, from_lng: activePerson.lng,
        to_lat: wo.lat, to_lng: wo.lng,
      },
    })
      .then(res => setRoute(res.data))
      .catch(err => {
        console.error('[PersonnelLayer] route failed:', err?.response?.status, err?.response?.data || err)
        setRoute(null)
        setRouteError(t('gis.person.routeFailed'))
      })
      .finally(() => setRouteLoading(false))
  }

  // 路线折线坐标：后端是 GeoJSON [lng,lat]，Leaflet 要 [lat,lng] —— 必须交换
  const routePositions = useMemo<[number, number][]>(() => {
    if (!route?.geometry?.coordinates) return []
    return route.geometry.coordinates.map(c => [c[1], c[0]] as [number, number])
  }, [route])

  const selectedKey = activePerson?.name_key
  // 当前悬停的人员对象（画连线要用它的坐标）
  const hoveredPerson = useMemo(
    () => (hoverKey ? people.find(p => p.name_key === hoverKey) || null : null),
    [hoverKey, people],
  )

  // 弹窗列（2026-10-16 按用户要求补常用信息）：
  // WO号 / TT单号 / 站点名 / 站点ID / 站点类型 / 传输类型 / TT级别 /
  // 告警级别 / 告警发生时间 / 清除时间 / 告警时长 / 状态 / 标题 / 操作。
  // `—` 是空值占位（AGENTS.md 三.6：取不到显示 —，不得显示 0）。
  const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))
  const woColumns = [
    { title: t('gis.drilldown.colWONo'), dataIndex: 'wo_no', key: 'wo_no', width: 150,
      render: dash },
    { title: t('gis.person.colTTNo'), dataIndex: 'tt_no', key: 'tt_no', width: 150,
      render: dash },
    { title: t('gis.drilldown.colSiteName'), dataIndex: 'site_name', key: 'site_name', width: 160,
      render: dash },
    { title: t('gis.person.colSiteId'), dataIndex: 'site_id', key: 'site_id', width: 90,
      render: dash },
    { title: t('gis.drilldown.colSiteType'), dataIndex: 'site_type', key: 'site_type', width: 90,
      render: dash },
    { title: t('gis.person.colTransType'), dataIndex: 'domain', key: 'domain', width: 100,
      render: dash },
    { title: t('gis.person.colTicketLevel'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 90,
      render: (v: string) => (v ? <Tag color="orange">{v}</Tag> : '—') },
    { title: t('gis.person.colAlarmSeverity'), dataIndex: 'alarm_severity', key: 'alarm_severity', width: 100,
      render: dash },
    { title: t('gis.drilldown.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 160,
      render: dash },
    { title: t('gis.person.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 160,
      render: dash },
    { title: t('gis.person.colFaultDuration'), dataIndex: 'fault_duration_time', key: 'fault_duration_time', width: 110,
      render: dash },
    { title: t('gis.drilldown.colStatus'), dataIndex: 'status', key: 'status', width: 130,
      render: (v: string) => <Tag color="cyan">{v || '—'}</Tag> },
    { title: t('gis.drilldown.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true },
    { title: t('gis.person.colAction'), key: 'action', width: 90, fixed: 'right' as const,
      render: (_: unknown, r: PersonWorkOrder) => (
        <Button
          type="link" size="small"
          disabled={r.lat == null || r.lng == null}
          onClick={(e) => { e.stopPropagation(); handleWoClick(r) }}
        >
          {t('gis.person.route')}
        </Button>
      ) },
  ]

  return (
    <>
      {/* 人员小人标记（地图针造型 + 常驻 WO 计数标签） */}
      {enabled && !loading && people.length > 0 && people.map(p => {
        const selected = p.name_key === selectedKey
        const hovered = p.name_key === hoverKey
        // 悬停/选中都放大，悬停用告警橙，让人一眼看出「这是当前在看的这个人」
        const color = selected ? SITE_COLORS.rt_alarm_overdue
          : hovered ? '#fa8c16'
          : (isDark ? '#4fc3f7' : '#1890ff')
        const size = (selected || hovered) ? 32 : 26
        const iconH = size * 1.5
        // 标签：WO:未关闭/总数。未关闭为 0 时用灰色，正常为红色，让「有活干」的人更醒目。
        const openCnt = p.wo_count || 0
        const totalCnt = p.wo_count_total || 0
        const badgeColor = openCnt > 0 ? '#ff4d4f' : '#8c8c8c'
        // 悬停时在针上方显示姓名与电话（电话号码后端已脱敏）
        const phone = (p.phone || '').trim()
        const tip = hovered
          ? `<span class="gis-person-tip">` +
              `<b>${escapeHtml(p.name)}</b>` +
              (phone ? `<i>${escapeHtml(phone)}</i>` : '') +
            `</span>`
          : ''
        return (
          <Marker
            key={p.name_key}
            position={[p.lat, p.lng]}
            pane="personPane"
            html={
              `<div class="gis-person-anchor">` +
                tip +
                personIconSvg(color, size, selected) +
                `<span class="gis-person-badge" style="border-color:${badgeColor};color:${badgeColor}">WO:${openCnt}/${totalCnt}</span>` +
              `</div>`
            }
            // 宽取 size（针身）与标签的最大值，避免标签被 divIcon 边界裁掉
            iconSize={[size, iconH]}
            // 锚在**针尖**：图标底部中点对准坐标，针尖才真正落在地理点上
            iconAnchor={[size / 2, iconH]}
            iconKey={`${selected}-${hovered}-${size}-${openCnt}-${totalCnt}`}
            zIndexOffset={selected ? 1000 : hovered ? 900 : 0}
            className="gis-person-marker"
            onClick={(e) => handlePersonClick(p, e as unknown as { originalEvent?: MouseEvent })}
            onMouseOver={() => handlePersonHover(p)}
            onMouseOut={() => handlePersonHoverOut(p)}
          />
        )
      })}

      {/* 悬停连线：从当前悬停的人到其「未关闭 WO 且有实时告警」的各站点。
          点击人员时由 handlePersonClick 清空（用户要求「点击后消失」）。 */}
      {enabled && hoveredPerson && hoverSites.map(s => (
        <Polyline
          key={`hover-${s.site_id}`}
          positions={[[hoveredPerson.lat, hoveredPerson.lng], [s.lat, s.lng]]}
          pathOptions={{
            color: SITE_COLORS.rt_alarm_overdue,
            weight: 2,
            opacity: 0.7,
            dashArray: '5 4',
          }}
        />
      ))}

      {/* 路线连线 */}
      {enabled && routePositions.length > 1 && (
        <Polyline
          positions={routePositions}
          pathOptions={{
            color: route?.degraded ? '#faad14' : '#52c41a',
            weight: 4,
            opacity: 0.85,
            dashArray: route?.degraded ? '6 6' : undefined,
          }}
        />
      )}
      {/* 路线终点站点的标记点 */}
      {enabled && routeTarget && (
        <Marker
          position={[routeTarget.lat, routeTarget.lng]}
          pane="personPane"
          html={`<svg width="18" height="18"><circle cx="9" cy="9" r="7" fill="${SITE_COLORS.rt_alarm_overdue}" stroke="#fff" stroke-width="2"/></svg>`}
          iconSize={[18, 18]}
          iconAnchor={[9, 9]}
          zIndexOffset={900}
        />
      )}

      {/* 人员 WO 弹窗 */}
      <DraggableClickModal
        open={woModalOpen && !!activePerson}
        title={activePerson ? t('gis.person.woTitle', { name: activePerson.name }) : ''}
        anchor={woModalAnchor}
        width="80%"
        onClose={() => setWoModalOpen(false)}
      >
        {woLoading ? (
          <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
        ) : woList.length === 0 ? (
          <Empty description={t('gis.person.noWo')} />
        ) : (
          <>
            {woTruncated && (
              <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                message={t('gis.person.truncated')} />
            )}
            <Table
              size="small"
              rowKey="wo_no"
              columns={woColumns as never}
              dataSource={woList}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              scroll={{ x: 1700 }}
              onRow={(r) => ({
                onClick: () => handleWoClick(r as PersonWorkOrder),
                style: { cursor: 'pointer' },
              })}
            />
          </>
        )}
      </DraggableClickModal>

      {/* 状态提示条（浮在地图左下，复用 WH 令牌配色） */}
      {enabled && (
        <div className="gis-personnel-status">
          {loading ? (
            <span><Spin size="small" /> {t('gis.person.loading')}</span>
          ) : error ? (
            <span style={{ color: SITE_COLORS.rt_alarm_overdue }}>{error}</span>
          ) : (
            <>
              <Badge status="processing" />
              <span>
                {t('gis.person.countSummary', { shown: people.length, total: totalAll })}
              </span>
              <span className="gis-personnel-note">· {t('gis.person.notRealtime')}</span>
              {/* 悬停某人时，提示画了多少条告警站点连线 */}
              {hoveredPerson && (
                <span className="gis-personnel-note">
                  · {t('gis.person.hoverLines', { name: hoveredPerson.name, n: hoverSites.length })}
                </span>
              )}
              {routeLoading && <span> · <Spin size="small" /> {t('gis.person.routeLoading')}</span>}
              {routeError && <span style={{ color: SITE_COLORS.rt_alarm_overdue }}> · {routeError}</span>}
              {route && !routeLoading && (
                <span>
                  {' · '}
                  <EnvironmentOutlined /> {route.distance_m >= 1000
                    ? `${(route.distance_m / 1000).toFixed(1)} km`
                    : `${Math.round(route.distance_m)} m`}
                  {route.duration_s != null && ` · ${Math.round(route.duration_s / 60)} min`}
                  {route.degraded && <span style={{ color: '#faad14' }}> ({t('gis.person.degraded')})</span>}
                </span>
              )}
            </>
          )}
        </div>
      )}
    </>
  )
}
