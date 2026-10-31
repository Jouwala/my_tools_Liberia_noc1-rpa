/* 人员位置地图（?page=person）—— 地图视图
 *
 * **职责**：画出「人员针 + 其 WO 涉及站点的圆点 + 选中时的连线」，以及
 * 县界底图（2026-10-23 起每县一种类别色 + 县名标签），把点击/悬停结果回传给页面。
 * 筛选、KPI、统计图、表格都在 `PersonMap.tsx`，
 * 本文件只管地图这一块（AGENTS.md 三.2：单个文件不超 500 行、按单一职责拆分）。
 *
 * **模块分工**（2026-10-24 按 500 行纪律拆分后）：
 *   · `useTerritory.ts`    「默认站点」辖区模式的取数与派生（pinPersons 等）；
 *   · `TerritoryLayer.tsx` 辖区连线/站点的原生批量建层；`LayerToggles.tsx` 图层开关浮层
 *     （「人员」默认开 +「默认站点」默认关，2026-10-24 起双开关）；
 *   · `useCountyTags.ts`   县界类别色 / 填充透明度 / 县名标签两行统计文本的派生；
 *   · `CountyLabels.tsx`   县名标签的避让 effect 与渲染；
 *   · `personPinHtml.ts`   人员针图标（颜色/尺寸/徽标 HTML/iconKey）的拼装；
 *   · `NoSitesNote.tsx`    空态说明条（地图版 `MapNoSitesNote` + 抽屉共用文案）；
 *   · `MapTopRightOverlays.tsx` / `CountyLayer.tsx` / `PersonPinsLayer.tsx`
 *     右上角浮层列（图层开关 + 站点类别图例）/ 县界底图 / 人员针
 *     （2026-10-28 站内类别图例落地后本文件回到 500 行纪律内）。
 *
 * **站点层口径**（2026-10-19 经用户确认）：只画该人员**实际处理过工单**的站点
 * （后端 `eflow_wo.site_id` 去重），**不画** `person.managed_regions` 的全县站点。
 * 原因见 `backend/routers/personnel.py` 的 `/managed-sites` 头注释：
 * managed_regions 是县名文本，实测 5/26 个有坐标的人写着「全部 15 县」，
 * 按区域画会变成「半个国家的人都是同一片」，看不出谁管哪片。
 * 县名只在页面表格里作为文本展示。
 *
 * **交互**（照搬 GIS 页 PersonnelLayer 已验证的做法，不重新发明）：
 *   · 点人 → 选中；点地图空白 → 清除。Leaflet 的 marker 点击会冒泡到 map，
 *     故用 `personClickRef` 标志位区分「点人」与「点空白」，否则点人的瞬间
 *     就被地图处理器清空，表现为「点不中」。
 *   · 悬停人 → 在针上方显示姓名/电话提示（电话 2026-10-23 起完整显示，
 *     见 backend/routers/personnel.py::_display_phone）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Spin } from 'antd'
import { useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import { Polyline, useMap, isMapAlive, Pane } from '../../components/LeafletMap'
import api from '../../api'
import { cachedGet } from '../../cache'
import { PmtilesLayer } from '../gismap/PmtilesLayer'
import type { LatLngBoundsExpression } from 'leaflet'
import { MapController } from '../gismap/MapController'
import { BASEMAP_PMTILES_URL } from '../gismap/basemap'
import { MapSearch } from './MapSearch'
import { MapNoSitesNote } from './NoSitesNote'
import { TerritoryLayer } from './TerritoryLayer'
import { CountyLabels } from './CountyLabels'
import { CountyLayer } from './CountyLayer'
import { SitesLayer } from './SitesLayer'
import { siteColor, siteCategory, type PersonSiteCategory } from './siteTone'
/* 图例浮层**直接复用**实时告警页那一份（`gismap/MapLegendOverlay`）——
 * 2026-10-30 对齐：人员页原先另起了一份 `personmap/PersonLegendOverlay`，
 * 样式（位置 / 分组 / 色块 / 置灰删除线 / 点击隐藏）逐项照抄一遍，
 * 于是两页浮层各改各的，很快就会分叉。
 * 现只保留**人员页自己的一处差异**：多一个「该人有未关闭 WO」档
 * （这一档在实时告警页不存在，行文案见 `person.siteLegend.wo`）。
 * 组件与行/组类型都取自 gismap 那份，故样式永远一致。 */
import MapLegendOverlay from '../gismap/MapLegendOverlay'
import type { MapLegendRow, MapLegendGroup } from '../gismap/MapLegendOverlay'
import { colorFor } from '../gismap/types'
import { PersonPinsLayer } from './PersonPinsLayer'
import { SiteClassLayer } from './SiteClassLayer'
import { MapTopRightOverlays } from './MapTopRightOverlays'
import { useSiteClasses } from './useSiteClasses'
import { useTerritory } from './useTerritory'
import { useCountyTags } from './useCountyTags'
import type { PersonRow, ManagedSite } from './types'
import type { CountyBoundary } from '../gismap/types'

/** 默认取景：利比里亚全国居中（与 GIS 页 LB_CENTER / ZOOM 同源思路，
 *  但本页画布更宽，用 zoom=7.5 即可装下全境）。
 *
 *  ⚠ 这两个常量**必须是模块级常量**：`MapController` 的 effect 依赖 `center` 的
 *  引用相等性，若每次渲染新建数组，它就会每次渲染都 `setView` 一次（瞬移），
 *  把下方聚焦 effect 的 `flyToBounds` 动画掐掉（2026-10-21 实测）。 */
const LB_CENTER: [number, number] = [(3.9 + 8.75) / 2, (-11.7 + -7.3) / 2]
const LB_ZOOM = 7.5

/** 人员针所在 pane 的层级。**必须显式给 z-index**，理由见 `<Pane>` 处的注释。
 *  取值与 `GISMap.tsx` 的 personPane 一致（680）：人员针要压在站点圆点
 *  （overlay pane 400）与连线之上，且高于 tooltip pane(650)。 */
const PERSON_PANE = 'personPane'
const PERSON_PANE_Z = 680

/** 站点圆点 pane（2026-10-30，与实时告警页的 sitePane 同层级）。
 *  650：高于 overlay(400) 的县块填充，低于 countyLabel(670) 与 personPane(680)。 */
const PERSON_SITE_PANE = 'sitePane'
const PERSON_SITE_PANE_Z = 650

/** 站点配色与半径已抽到 `personmap/siteTone.ts`（2026-10-30，与实时告警页对齐）：
 *  色值取自 `gismap/types.ts` 的 `LEGEND_COLORS`（两页同一份真相源），
 *  分档判定与「人员 → 站点」连线共用 `siteTone.ts::siteCategory`。
 *  旧的三档配色（绿/浅蓝/红，`SITE_TONE`）已删除。 */

/** 县块类别配色（COUNTY_PALETTE）、县块填充不透明度（COUNTY_FILL_OPACITY）、
 * 县名标签两行统计文本的构造（typeCountsLine / TRM·CAT 常量表）与「县 → 类别色」
 * 的稳定映射，已抽到 `personmap/useCountyTags.ts`（2026-10-24，PersonMapView
 * 行数纪律，AGENTS.md 三.2）。本文件只保留渲染。 */

export function PersonMapView({
  people, allPeople, loading, selectedKey, onSelect, sites, sitesLoading,
}: {
  people: PersonRow[]
  /** /personnel/stats 的**全量**人员行（含无坐标者）。「默认站点」模式下
   *  人员针挪到其辖区质心，其中部分人不在 `people`（无登记坐标），
   *  徽标的 WO/PMT 统计从这里按 name_key 联合。 */
  allPeople: PersonRow[]
  loading: boolean
  /** 当前选中人员的 name_key；null = 未选中 */
  selectedKey: string | null
  onSelect: (key: string | null) => void
  /** 选中人员的 WO 站点（由页面按 selectedKey 拉取后传进来） */
  sites: ManagedSite[]
  sitesLoading: boolean
}) {
  const { isDark } = useTheme()
  const { t } = useI18n()
  const map = useMap()
  /* 站点 → 颜色 / 半径：全部由 `personmap/siteTone.ts` 决定（2026-10-30）。
     圆点与连线**共用同一个分档函数**（`siteCategory`），否则会出现
     「线是绿的、点是蓝的」这种看着像 bug 的画面（用户 2026-10-21 要求）。
     色值与实时告警页共用 `LEGEND_COLORS` —— 两页同一份真相源。 */
  /* 悬停**不再用 React state**（2026-10-21 改）：state 变化会把 hover 拼进图标，
     导致 Leaflet 重建 marker 图层、把针的 DOM 元素换掉，mousedown/mouseup 因此
     落在不同元素上、click 事件不产生（实测时间线见 personPinHtml.ts 文件头）。
     悬停反馈改由 CSS `.gis-person-marker:hover` 提供，DOM 保持不动。 */
  /* 县界（2026-10-19 用户要求「地图没有 country 的边界」）。
     与 GIS 页共用同一份静态 GeoJSON（`/gis/county-boundaries`，后端 1 小时缓存），
     经 `cachedGet` 走前端缓存，两页之间不会重复下载约 400KB。
     2026-10-23 起**每县一种独立类别色**并加县名标签（色表与派生见
     useCountyTags.ts 的 COUNTY_PALETTE）——
     仍**不铺** GIS 页的告警分档色（COUNTY_BAND_COLORS）：那五档是「按县统计
     实时告警」的语义，人员页没有对应口径，照搬会让人误读为人员告警分布；
     类别色只表达「这是哪个县」，不带任何数值含义。 */
  const [counties, setCounties] = useState<CountyBoundary[]>([])

  /* 县界底图的派生数据：县 → 类别色（县块填充描边用）+ 每县两行统计文本
     （县名标签用）。已抽到 useCountyTags.ts（2026-10-24，行数纪律）；
     县名标签的避让与渲染整体在 CountyLabels.tsx（含 placement effect）。 */
  const { countyColor, countyTypeLines } = useCountyTags(counties)

  /* ---------- 「默认站点」辖区模式（2026-10-23 用户需求） ----------
     需求原话：「显示 master_site_db 里面不同 person 的默认站点，person 放到
     这些站点的中间，并且连线。默认不显示，打开地图上的显示开关才显示」。
     数据侧（取数 / 配色 / 站点归属 / pinPersons）抽在 useTerritory.ts
     （本文件行数纪律，AGENTS.md 三.2），这里只留渲染：开关浮层在
     LayerToggles.tsx、批量图层在 TerritoryLayer.tsx，加上人员针位置切换。选中某人时其辖区连线让位给详细图层（见 TerritoryLayer
     文件头的重影说明）。 */
  const {
    showTerritory, setShowTerritory, territory, terrLoading,
    terrColorOf, terrSiteOwners, territorySiteTip, pinPersons, territoryPins,
  } = useTerritory({ people, allPeople })

  /* ---------- 站点类别图例（2026-10-28 用户需求） ----------
     左下角浮层（SiteClassLegend）控制，默认一项都不选 → 地图上一个类别站点
     都不画。取数与过滤口径见 useSiteClasses.ts 文件头，渲染在
     SiteClassLayer.tsx。 */
  const siteClasses = useSiteClasses()

  useEffect(() => {
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => setCounties(res.data?.counties || []))
      .catch(err => {
        // 不吞异常：边界拉不到就明确报错、界面回落为「无边界」，而不是静默空白
        console.error('[PersonMapView] county boundaries failed:', err?.response?.status, err?.response?.data || err)
        setCounties([])
      })
  }, [])

  /* 县名标签（2026-10-23 用户要求「地图显示县名」）的避让 effect 与渲染
     已整体移到 CountyLabels.tsx（含投影/避让算法复用说明）。 */

  /* 「最近一次点中人员针」的时间戳，供 map 的 click 处理器跳过 —— Leaflet 会把
     marker 的点击冒泡到 map，若不区分，点人的瞬间就会被 map 处理器当成
     「点空白」清掉选中态。

     ⚠ 为什么用时间戳而不是布尔标志（2026-10-21 改）：布尔标志有两个死法 ——
       ① map 的 click 可能对同一次点击触发多次（Map 自身监听 + 冒泡目标各一次），
          第一路把标志复位后，第二路就带着 false 直落 `onSelect(null)`；
       ② 命中 marker 分支时又必须保留标志（不能复位），于是它会**残留到下一次点击**，
          让用户「点空白取消选中」的第一次点击静默失效。
       时间戳两路都吃得下：只要在窗口期内一律放行，不区分命中顺序。 */
  const personClickTsRef = useRef(0)

  /* `onSelect` 每次都可能是新闭包（父组件 useCallback 依赖变化），若直接放进 effect 依赖，
     父组件一重渲染就会 off/on 一次 map 事件 —— 本 effect 用 ref 存最新回调，只挂一次。
     仍保留 onSelectRef 而不用闭包里的 onSelect：见下方 `onMapClick` 的说明。 */
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  /* 「人员」图层开关（2026-10-24 用户要求「实时人员的信息也弄个开关」）：
     控制人员针 + 常驻徽标 + 选中者的站点圆点/连线 + 空态说明条。
     **关掉时必须同时清除选中**：留着选中态会出现「抽屉开着、地图上一片空」
     的自相矛盾画面（与点空白取消选中同一语义）。走 onSelectRef 而非直接
     onSelect —— 回调可能随父组件重渲染换新闭包，ref 永远是最新的。
     2026-10-29 加条件：「默认站点」开着时中心仍有该人的标签（针没消失），
     此时关人员开关**不该**清掉选中 —— 否则用户看到的是「关掉一个图层，
     正在看的抽屉被顺手关了」。只有两个开关都关、针真的看不见时才清。 */
  const [showPeople, setShowPeople] = useState(true)
  const togglePeople = useCallback((v: boolean) => {
    setShowPeople(v)
    if (!v && !showTerritory) onSelectRef.current(null)
  }, [showTerritory])

  /* 人员针的可见集合（2026-10-29 用户要求「显示 Default Site 的时候，中心要显示
     人员的图标和站点数、电话号码等，跟 People 一样的标签」）。
     中心标签归**辖区层**所有：「人员」开关关掉时它仍随辖区一起出，但此时无辖区
     连线的人（supervisor 等 6 人）不该凭空冒出来，所以走 territoryPins 而非 pinPersons。
       · 人员开 → pinPersons（辖区开 = 24 辖区人 + 6 有坐标非 FME = 30；辖区关 = 14 个有登记坐标的人）
       · 人员关 + 辖区开 → territoryPins（24 个中心标签，针在其站点几何中心）
       · 两个都关 → 空
     ⚠ 这改变了 2026-10-24 记下的「人员关 + 辖区开 = 0 针 + 1849 图形」纯辖区总览形态，
       见手册 11a 与 LayerToggles 的开关说明。必须声明在 showPeople 之后（块级作用域）。 */
  const visiblePins = showPeople ? pinPersons : (showTerritory ? territoryPins : [])
  const pinsVisible = showPeople || showTerritory

  useEffect(() => {
    if (!isMapAlive(map)) return
    const onMapClick = (e: any) => {
      // 事件源判定：点在人员针（L.Marker，有 setIcon）上不清理。
      // 站点圆点是 L.CircleMarker，只有 setStyle/setRadius、没有 setIcon ——
      // 两者都能 getLatLng，故不能用 getLatLng 区分（GIS 页踩过这个坑）。
      const src = e?.sourceTarget
      if (src && src !== map && typeof src.setIcon === 'function') return
      if (Date.now() - personClickTsRef.current < 400) return
      onSelectRef.current(null)
    }
    map.on('click', onMapClick)
    return () => { map.off('click', onMapClick) }
  }, [map])

  /* 按下鼠标**不要**让页面跳 —— 2026-10-21 实测的第三个根因，改动前务必读这段。
     Leaflet 给「可交互 marker 的图标元素」设了 `tabIndex='0'`（键盘可达性），
     也给地图容器设了 `tabIndex='0'`，并在 mousedown 时主动 `container.focus()`。
     浏览器把焦点元素滚动进视口是**默认行为**，而本页真正的滚动容器是内层的
     `#main-content`（不是 window，Leaflet 的 `window.scrollTo` 兜底管不到它），
     于是按下鼠标的瞬间整块内容上移 —— 实测 104px：
          hover: activeElement=BODY,              markerTop=611
          down : activeElement=.gis-person-marker, #main-content.scrollTop=104, markerTop=507
     人员针从光标底下跑掉了，`mouseup` 落到 `.leaflet-container` 上 ——
     mousedown 与 mouseup 目标不同，**浏览器不产生 click**，Leaflet 收不到 marker
     click。点不中人、抽屉闪一下就没，全都出在这一下跳动上。

     两道处理：
       ① 挂载后摘掉地图容器的 tabindex（Leaflet 建图时加的），让 focus() 无处可落；
       ② mousedown 捕获阶段再摘一次命中元素的 tabindex 并 preventDefault ——
          人员针的图标是**选中态变化时才重建**的， tabindex 会跟着重新长出来。
     只拦地图容器内部：搜索框是容器的**兄弟节点**（MapContainer 把 children 渲染在
     Leaflet 内层容器之外），所以输入框照常能点、能聚焦。 */
  useEffect(() => {
    if (!isMapAlive(map)) return
    const el = map.getContainer()
    el.removeAttribute('tabindex')
    const onDownCapture = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null
      const focusable = t && typeof t.closest === 'function'
        ? (t.closest('[tabindex]') as HTMLElement | null) : null
      if (focusable) focusable.removeAttribute('tabindex')
      e.preventDefault()
    }
    el.addEventListener('mousedown', onDownCapture, true)
    return () => el.removeEventListener('mousedown', onDownCapture, true)
  }, [map])

  /* 选中者取自 pinPersons（「默认站点」模式下位置 = 辖区质心而非登记坐标），
     下方的连线层（person → 站点）据此从质心起笔。 */
  const selectedPerson = useMemo(
    () => pinPersons.find(p => p.name_key === selectedKey) || null,
    [pinPersons, selectedKey],
  )

  /* 站点状态图例（2026-10-30，与实时告警页对齐）。
     **每站恰好一个档**（`siteCategory`），故各档之和 = 站点总数，
     图例数字与地图上画出来的点数必然一一对应（AGENTS.md 三.1b）。
     文案复用 `gis.legend.*` 那套（同一档位两页同一种说法），只把
     「该人有未关闭 WO」这一档换成人员页自己的说法。

     ⚠ 「点图例 = 隐藏该档」是实时告警页的既有能力（`toggleLegend`），
     人员页原先没有对应物 —— 这是「两页同构」的最后一块拼图：
     同一批站点、同一套颜色，若不能按档隐藏，用户在两页的操作习惯不一致。

     ⚠ 与实时告警页的差别（刻意）：那边**默认隐藏 normal**（739/827 个
     无状态站会把告警站淹没）；人员页画的是「选中人员的负责站」，量级只有
     几十个（实测人均 35 站），全部显示才有信息量，故默认一档都不隐藏。 */
  const [hiddenSiteCats, setHiddenSiteCats] = useState<Set<PersonSiteCategory>>(new Set())
  const toggleSiteCat = useCallback((id: PersonSiteCategory) => {
    setHiddenSiteCats(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const siteLegendGroups = useMemo<MapLegendGroup[]>(() => {
    const visible = showPeople ? sites : []
    const counts: Record<string, number> = {}
    for (const s of visible) {
      const c = siteCategory(s)
      counts[c] = (counts[c] || 0) + 1
    }
    const row = (id: PersonSiteCategory, color: string, label: string, hint?: string): MapLegendRow => ({
      id, color, label, count: counts[id] || 0, hint,
      shape: 'dot',
      hidden: hiddenSiteCats.has(id),
      hiddenNote: t('gis.legend.hidden'),
      onClick: () => toggleSiteCat(id),
    })
    return [
      {
        /* 组标题复用实时告警页那套键（`gis.legendGroup.*`）—— 两页组名逐字相同，
           刻意不另起一套 `person.siteLegend.group.*`（那会造成第二份真相源，
           改一边就分叉）。措辞差异只体现在「该人有未关闭 WO」那一**行**，
           行文案用 `person.siteLegend.wo`（语义确实不同，见该键注释）。 */
        title: t('gis.legendGroup.alarm'),
        rows: [
          row('rt_alarm_overdue', colorFor('rt_alarm_overdue'), t('gis.legend.rtAlarmOverdue'),
            t('gis.legend.rtAlarmOverdueHint')),
          row('rt_alarm_ontime', colorFor('rt_alarm_ontime'), t('gis.legend.rtAlarmOnTime'),
            t('gis.legend.rtAlarmOnTimeHint')),
        ],
      },
      {
        title: t('gis.legendGroup.ticket'),
        rows: [
          row('tt', colorFor('tt'), t('gis.legend.tt')),
          row('wo', colorFor('wo'), t('person.siteLegend.wo'), t('person.siteLegend.woHint')),
        ],
      },
      {
        title: t('gis.legendGroup.site'),
        rows: [
          row('vip', colorFor('vip'), t('gis.legend.vip')),
          row('normal', colorFor('normal'), t('gis.legend.normal')),
        ],
      },
    ]
  }, [sites, showPeople, hiddenSiteCats, toggleSiteCat, t])

  /* 被图例隐藏的档位 → 圆点与连线一起不画（2026-10-30）。
     ⚠ **图例计数仍按全量统计**（上面 counts 用的是全部站点），与实时告警页
     一致：那边隐藏某档后图例数字也不变（数字是「该档有多少站」，
     不是「当前画了几个点」）。两页口径相同，用户对照时才不会觉得数字跳了。
     ⚠ 连线一并隐藏：线是「人 → 站点」的指引，端点圆点都不见了还留着线，
     会指向一个看不见的站点。 */
  const visibleSites = useMemo(
    () => sites.filter(s => !hiddenSiteCats.has(siteCategory(s))),
    [sites, hiddenSiteCats],
  )

  const handleClick = useCallback((p: PersonRow) => {
    personClickTsRef.current = Date.now()
    onSelect(p.name_key === selectedKey ? null : p.name_key)
  }, [onSelect, selectedKey])

  /* 搜索定位目标。MapController 只在 center/zoom **变化**时才 setView，
     而用户可能连续搜同一个站点附近的不同点 —— 用 tick 强制触发一次重定位。
     tick 用时间戳而不是递增计数：避免组件重建后计数器归零导致「不生效」。 */
  const [flyTarget, setFlyTarget] = useState<{ lat: number; lng: number; tick: number } | null>(null)

  /* 2026-10-19（用户要求「点击人员后地图自动聚焦到人和对应的站点」）：
     选中人员后不再只是「把地图中心挪到人身上」，而是用 fitBounds 把
     **该人员 + 其全部站点**一起框进视野 —— 站点往往分布在好几个县，
     只居中到人身上时站点会落在画布外，用户还得自己拖。

     ⚠️ 本 effect 是**选中态下唯一的取景驱动方**（2026-10-21 改）。
        原先 `MapController` 还会按「选中人员」另算 center/zoom 再 setView 一次，
        两套驱动互相打断 —— MapController 的 setView 是**瞬移**，会直接掐掉
        本 effect 的 flyToBounds 动画。而且它依赖的 center 是每次渲染新建的数组，
        于是**悬停切换、站点到达、主题切换等任何重渲染**都会触发一次瞬移，
        表现为「点人之后地图不聚集到人+站点，反而跳回这个人身上、缩放被钉死」。
        现在 MapController 固定在全国视角（只管初始与回落），选中态全权归这里。

     ⚠️ 依赖 sites 是有意的：点击人时 managed-sites 是异步回来的，
        先到的是空数组（此时只聚焦到人），站点到达后本 effect 重跑，
        再按完整包围盒 fit 一次 —— 这正是"聚焦到人和对应的站点"要的效果。 */
  const focusKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (!isMapAlive(map)) return
    /* 取消选中 → 飞回全国视角。
       这一步原先由 `MapController` 的 center/zoom 跟随选中人员来做（见下方说明），
       现在 MapController 固定在全国视角，回落的动作就归到这里。
       用 `focusKeyRef.current !== null` 判断「之前确实选中过」：首次挂载时
       selectedKey 本来就是 null，不该无端播一次动画。 */
    if (!selectedKey) {
      if (focusKeyRef.current !== null) {
        focusKeyRef.current = null
        map.flyTo(LB_CENTER, LB_ZOOM, { duration: 0.6 })
      }
      return
    }
    const p = pinPersons.find(x => x.name_key === selectedKey)
    if (!p || p.lat == null || p.lng == null) return
    const pts: [number, number][] = [[p.lat as number, p.lng as number]]
    for (const s of sites) {
      if (s.lat != null && s.lng != null) pts.push([s.lat as number, s.lng as number])
    }
    /* 同一个人且站点数没变 → 不重复 fit（悬停、主题切换等无关重渲染会触发本 effect）。
       站点从 0 变成 N 时 key 变了，会再 fit 一次，这是要的。 */
    const key = `${selectedKey}|${pts.length}|${p.lat},${p.lng}`
    if (focusKeyRef.current === key) return
    focusKeyRef.current = key

    if (pts.length === 1) {
      map.flyTo(pts[0], Math.max(map.getZoom(), 10), { duration: 0.6 })
      return
    }
    const bounds = pts as LatLngBoundsExpression
    /* maxZoom：包围盒很小时（人 + 站点几乎重叠）fitBounds 会一路放大到
       街道级，反而看不出周边。封顶到 12 既贴得够近、又留得住上下文。 */
    map.flyToBounds(bounds, { padding: [56, 56], maxZoom: 12, duration: 0.7 })
    // 只按「选中的人 + 站点集合」驱动；key 里含质心坐标，开关切换导致
    // 同一人位置变化（登记坐标 ↔ 辖区质心）时会重新 fit 一次 —— 这是想要的。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, sites, pinPersons])

  /* 搜索定位：直接对 map 调 flyTo ——
     「搜同一个站点附近的两个点」或「搜一个与当前选中人员重合的点」时目标可能不变，
     靠 prop 变化驱动是不动的，故用 tick 驱动的 effect 保证每次选中都飞一次。
     飞完把 flyTarget 置空，后续取景仍归「选中人员」的聚焦 effect。 */
  useEffect(() => {
    if (!flyTarget || !isMapAlive(map)) return
    map.flyTo([flyTarget.lat, flyTarget.lng], Math.max(map.getZoom(), 12), { duration: 0.6 })
    setFlyTarget(null)
    // 只依赖 tick：lat/lng 变化已隐含在新的 tick 里
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTarget?.tick])

  /* 搜索选中人员 → 与点击人员针同义：交给页面更新 selectedKey，
     取景由上面的聚焦 effect 接管（自动飞到「人 + 站点」的包围盒）。 */
  const handlePickPerson = useCallback((nameKey: string) => {
    onSelect(nameKey)
  }, [onSelect])

  /* 搜索选中站点（2026-10-19 用户要求「定位并选中负责人」）：
     ① 飞行到该站点；
     ② 若后端回了可选的负责人键（该站点未关闭 WO 的负责人中、有坐标的那位），
        一并选中 —— 这样地图上的连线与右列 KPI 会切到那个人。
        无负责人 / 负责人无坐标时只定位，**不清空**当前选中，
        避免「搜一个无主站点，把正在看的上下文抹掉」。
     「人员」开关关掉且无中心标签时（两个开关都关）只定位、**不选中** ——
     负责人的针被藏了，选中一个看不见的人只会让抽屉和地图对不上。
     2026-10-29：辖区开着时中心有标签，针看得见，故判据从 showPeople 换成 pinsVisible。 */
  const handlePickSite = useCallback((site: ManagedSite) => {
    setFlyTarget({ lat: site.lat, lng: site.lng, tick: Date.now() })
    if (!pinsVisible) return
    const ownerKey = site.owner_keys?.[0]
    if (ownerKey && visiblePins.some(p => p.name_key === ownerKey)) {
      onSelect(ownerKey)
    }
  }, [onSelect, visiblePins, pinsVisible])

  return (
    <>
      {/* 人员针的 pane —— **必须在这里显式声明并给 z-index**。
          ⚠ 2026-10-21 实测的「点人没反应 / 抽屉闪一下就没」根因就在这一行：
            本视图给 Marker 传了 `pane="personPane"`，但**没有**渲染 `<Pane>`，
            于是 pane 由 `Marker` 内部的兜底 `map.createPane()` 创建 —— Leaflet 的
            `createPane` **不设 z-index**，新建的 pane 是 `z-index: auto`，
            在 CSS 绘制顺序里落在「有正 z-index 的定位元素」之下，
            也就是被 overlay pane（z-index 400，县界多边形与站点圆点所在）**整片盖住**。
            无头浏览器实测点击人员针的命中链是：
                mousedown → <path>（县界多边形）    mouseup → .leaflet-container
            两者不是同一个元素，**click 事件根本不产生**，Leaflet 只收到一次
            「点空白」→ `onSelect(null)` —— 表现就是选不中人、偶发选中后又被立刻清掉。
            GISMap.tsx:2740 用 `<Pane name="personPane" style={{ zIndex: 680 }} />`
            显式声明过，所以 GIS 页的人员针一直是能点的；本页漏了这一行。 */}
      <Pane name={PERSON_PANE} style={{ zIndex: PERSON_PANE_Z }} />

      {/* 站点圆点专用 pane（2026-10-30，与实时告警页对齐）。
          **必须显式声明**：若让 CircleMarker 的兜底 createPane 建，
          pane 拿不到 z-index，会掉到 overlayPane(400) 里与县块填充同层
          （谁后画谁在上）→ 圆点可能被县块盖住（与 2026-10-21 人员针那个坑同类）。
          取 650：高于 overlay(400) 的县块填充，低于 countyLabel(670) 与
          personPane(680)，层级链与 `GISMap.tsx` 完全一致。 */}
      <Pane name={PERSON_SITE_PANE} style={{ zIndex: PERSON_SITE_PANE_Z }} />

      {/* MapController 只负责「初始 / 取消选中后」的全国视角；
          选中态的取景由下方聚焦 effect 独占（见那里的注释）。 */}
      <MapController center={LB_CENTER} zoom={LB_ZOOM} />
      <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} />

      {/* 地图左上角搜索框（人员 + 站点）。
          「默认站点」模式下人员源换 pinPersons —— 辖区人员（含无登记坐标者）
          也要能被搜到并选中，否则开关一开图上有针、搜索框里却没有此人。
          人员源与地图上**实际可见**的针同源（visiblePins）：针藏起来时，
          搜索框不该再提供「选中一个看不见的人」的入口（站点搜索不受影响）。 */}
      <MapSearch
        people={visiblePins}
        selectedKey={selectedKey}
        sites={sites}
        onPickPerson={handlePickPerson}
        onPickSite={handlePickSite}
      />

      {/* 图层开关浮层（「人员」默认开 +「默认站点」默认关）——
          呈现在 LayerToggles.tsx；辖区取数与派生仍在
          useTerritory.ts，首次打开才拉 /fme-territories（~130KB，24 人 824 站）。 */}
      {/* 右上角浮层列：图层开关（人员 / 默认站点）+ 站点类别图例。
          布局与「为什么不能放左下角」的理由见 MapTopRightOverlays.tsx 文件头。 */}
      <MapTopRightOverlays
        showPeople={showPeople}
        onPeopleChange={togglePeople}
        showTerritory={showTerritory}
        terrLoading={terrLoading}
        onTerrChange={setShowTerritory}
        siteClasses={siteClasses}
      />


      {loading && people.length === 0 && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 500, pointerEvents: 'none',
        }}>
          <Spin />
        </div>
      )}

      {/* 县界（最底层，先于站点与人员绘制）：每县一种类别色，
          口径与「为什么不用后端 color」见 CountyLayer.tsx / useCountyTags.ts 头注释。 */}
      <CountyLayer counties={counties} countyColor={countyColor} isDark={isDark} />

      {/* 县名标签（2026-10-23 用户要求「地图显示县名」）：三行标签的
          避让 effect 与渲染整体在 CountyLabels.tsx（结构/样式/算法说明见那里）。
          center/zoom 必须是模块级常量 LB_CENTER/LB_ZOOM —— 投影按初始全国
          取景算一次，见文件头关于引用相等性的说明。 */}
      <CountyLabels
        counties={counties}
        typeLines={countyTypeLines}
        center={LB_CENTER}
        zoom={LB_ZOOM}
      />

      {/* 「默认站点」辖区层（2026-10-23，开关控制、默认关）：
          全部 FME 的质心 → 站点连线（每人一色）+ 去重站点小圆点。
          原生批量建层（TerritoryLayer 文件头有量级说明），pane 走默认 overlay
          （400），压在县块上、被人员针/选中站点层盖住 —— 背景语境层。 */}
      {showTerritory && territory && territory.length > 0 && (
        <TerritoryLayer
          persons={territory}
          selectedKey={selectedKey}
          colorOf={terrColorOf}
          siteOwners={terrSiteOwners}
          tipHtmlOf={territorySiteTip}
          isDark={isDark}
        />
      )}

      {/* 负责站点层（2026-10-21 起集合 = `master_site_db.fme_name`，不再是
          「WO 涉及过的站」）：圆点 + 悬停提示在 SitesLayer.tsx（行数纪律），
          取色与下方「人员 → 站点」连线共用 siteColor。
          「人员」开关关掉时一并隐藏 —— 站点圆点是「选中人的信息」的一部分。 */}
      {/* 按图例筛选出的类别站点（背景语境层：压在县界上、被负责站点层盖住） */}
      <SiteClassLayer
        sites={siteClasses.visibleSites}
        colorOf={siteClasses.colorOf}
        labelOf={siteClasses.labelOf}
        isDark={isDark}
      />

      <SitesLayer sites={showPeople ? visibleSites : []} isDark={isDark} />

      {/* 人员 → 其负责站点的连线（仅选中时）。
          2026-10-21 用户要求「连线颜色跟站点同色」：原先一律灰色虚线，
          在国家级缩放下几乎看不见，也分不出哪条指向告警站。
          2026-10-30：颜色改由 `siteTone.ts::siteColor` 给（与圆点同一份），
          线宽/透明度按**分档**给（告警档更粗更实），不再是「有告警与否」两档。 */}
      {showPeople && selectedPerson && visibleSites.map(s => {
        const cat = siteCategory(s)
        const isAlarm = cat === 'rt_alarm_overdue' || cat === 'rt_alarm_ontime'
        return (
          <Polyline
            key={`line-${s.site_id}`}
            positions={[[selectedPerson.lat as number, selectedPerson.lng as number], [s.lat, s.lng]]}
            pathOptions={{
              color: siteColor(s),
              weight: isAlarm ? 2.5 : 1.5,
              opacity: isAlarm ? 0.75 : 0.55,
              dashArray: '5 4',
              // 同县界：连线没有点击行为，别让它拦下本该落在人员针上的点击
              interactive: false,
            }}
          />
        )
      })}

      {/* 人员针（渲染在 PersonPinsLayer.tsx；「悬停态绝不能进 iconKey」的契约
          见 personPinHtml.ts 文件头，2026-10-21 实测踩过）。
          2026-10-29：判据从 showPeople 换成 pinsVisible —— 「默认站点」开着时，
          每个辖区的几何中心要带与 People 同样的标签（图标 + 姓名 + 电话 + 站点数），
          即使「人员」开关是关的。集合见上方 visiblePins 的注释。 */}
      {pinsVisible && (
        <PersonPinsLayer
          persons={visiblePins}
          selectedKey={selectedKey}
          isDark={isDark}
          pane={PERSON_PANE}
          onSelect={handleClick}
        />
      )}

      {/* 选中了人、但他一个负责站点都没有 → 在地图上把原因说出来（2026-10-21）。
          实测有人点 Franklin Peter 看到全空，报成「连线没画出来」；他其实是
          supervisor（覆盖 294 站），不是单站负责，站点集合刻意只认 fme_name。
          说明条本身（含底部居中的定位外壳）在 NoSitesNote.tsx 的 MapNoSitesNote
          （与下钻抽屉共用文案、容器不同）；抽屉里那条是裸 NoSitesNote。 */}
      {pinsVisible && selectedPerson && !sitesLoading && sites.length === 0 && (
        <MapNoSitesNote person={selectedPerson} />
      )}

      {/* 站点状态图例（2026-10-30，与实时告警页同构）。
          放左下角：右上角已被「图层开关 + 站点类别图例」占住。
          ⚠ 只在「人员」开关打开且**选中了人**时显示 —— 图例统计的是
          「该人员的负责站点」，没选中就没有站点可统计，画一个全 0 的图例
          只会让人以为数据是空的。 */}
      {showPeople && selectedPerson && (
        <MapLegendOverlay
          /* 标题复用实时告警页的 `gis.legendTitle`（"图例 / Legend"）——
             两页浮层标题逐字相同，便于左右对照。口径说明（ⓘ）用人员页自己的：
             分档优先级里有一档是人员页独有的，措辞必须不同。 */
          title={t('gis.legendTitle')}
          note={t('person.siteLegend.note')}
          groups={siteLegendGroups}
        />
      )}
    </>
  )
}
