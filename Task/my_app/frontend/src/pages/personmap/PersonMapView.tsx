/* 人员位置地图（?page=person）—— 地图视图
 *
 * **职责**：画出「人员针 + 其 WO 涉及站点的圆点 + 选中时的连线」，
 * 把点击/悬停结果回传给页面。筛选、KPI、统计图、表格都在 `PersonMap.tsx`，
 * 本文件只管地图这一块（AGENTS.md 三.2：单个文件不超 500 行、按单一职责拆分）。
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
 *   · 悬停人 → 在针上方显示姓名/电话提示（电话后端已脱敏）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useTheme } from '../../theme'
// `Tooltip as MapTooltip`：地图内常驻标注，与 antd 的 Tooltip 同名，必须别名
import {
  Marker, CircleMarker, Polyline, Polygon, Tooltip as MapTooltip, useMap, isMapAlive, Pane,
} from '../../components/LeafletMap'
import api from '../../api'
import { cachedGet } from '../../cache'
import { PmtilesLayer } from '../gismap/PmtilesLayer'
import type { LatLngBoundsExpression } from 'leaflet'
import { MapController } from '../gismap/MapController'
import { BASEMAP_PMTILES_URL } from '../gismap/basemap'
import { SITE_COLORS } from '../gismap/types'
import { escapeHtml, personIconSvg } from '../gismap/personIcon'
import { MapSearch } from './MapSearch'
import { NoSitesNote } from './NoSitesNote'
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

/** 站点三档配色（2026-10-21 用户指定）：
 *    绿 = 负责但当前**没有**该人的未关闭 WO；浅蓝 = 该人在此站**有**未关闭 WO；
 *    红 = 该站当前**有实时告警**。优先级 红 > 浅蓝 > 绿。
 *  ⚠ 必须是**实值十六进制**：Leaflet 的 CircleMarker / Polyline 走 SVG 呈现属性，
 *    解析不了 `var(--wh-*)`（与 ECharts 同一约束，AGENTS.md 三.3 取色表）。
 *  深浅两套的理由：`#4fc3f7` 这类浅蓝在白色底图上对比不足，浅色主题压深一档。 */
const SITE_TONE = {
  dark: { ok: '#51cf66', wo: '#4fc3f7', alarm: '#ff1e1e' },
  light: { ok: '#2f9e44', wo: '#1e88d2', alarm: '#e03131' },
} as const

export function PersonMapView({
  people, loading, selectedKey, onSelect, sites, sitesLoading,
}: {
  people: PersonRow[]
  loading: boolean
  /** 当前选中人员的 name_key；null = 未选中 */
  selectedKey: string | null
  onSelect: (key: string | null) => void
  /** 选中人员的 WO 站点（由页面按 selectedKey 拉取后传进来） */
  sites: ManagedSite[]
  sitesLoading: boolean
}) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const map = useMap()
  /** 站点 → 三档颜色（红=有实时告警 > 浅蓝=该人在此站有未关闭 WO > 绿=负责但当前没单）。
   *  圆点与连线**共用这一个判定**，否则会出现「线是绿的、点是蓝的」这种看着像 bug 的画面。 */
  const siteTone = isDark ? SITE_TONE.dark : SITE_TONE.light
  const siteColor = (s: ManagedSite) => (
    s.has_alarm ? siteTone.alarm : s.wo_count > 0 ? siteTone.wo : siteTone.ok
  )
  /* 悬停**不再用 React state**（2026-10-21 改）：state 变化会把 hover 拼进图标，
     导致 Leaflet 重建 marker 图层、把针的 DOM 元素换掉，mousedown/mouseup 因此
     落在不同元素上、click 事件不产生（详见下方「人员针」处的实测时间线）。
     悬停反馈改由 CSS `.gis-person-marker:hover` 提供，DOM 保持不动。 */
  /* 县界（2026-10-19 用户要求「地图没有 country 的边界」）。
     与 GIS 页共用同一份静态 GeoJSON（`/gis/county-boundaries`，后端 1 小时缓存），
     经 `cachedGet` 走前端缓存，两页之间不会重复下载约 400KB。
     本页**只画轮廓**、不铺告警分档色 —— 那些分档（COUNTY_BAND_COLORS）是 GIS 页
     「按县统计实时告警」的语义，人员页没有对应口径，照搬会让人误读为人员告警分布。 */
  const [counties, setCounties] = useState<CountyBoundary[]>([])

  useEffect(() => {
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => setCounties(res.data?.counties || []))
      .catch(err => {
        // 不吞异常：边界拉不到就明确报错、界面回落为「无边界」，而不是静默空白
        console.error('[PersonMapView] county boundaries failed:', err?.response?.status, err?.response?.data || err)
        setCounties([])
      })
  }, [])

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

  const selectedPerson = useMemo(
    () => people.find(p => p.name_key === selectedKey) || null,
    [people, selectedKey],
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
    const p = people.find(x => x.name_key === selectedKey)
    if (!p || p.lat == null || p.lng == null) return
    const pts: [number, number][] = [[p.lat as number, p.lng as number]]
    for (const s of sites) {
      if (s.lat != null && s.lng != null) pts.push([s.lat as number, s.lng as number])
    }
    /* 同一个人且站点数没变 → 不重复 fit（悬停、主题切换等无关重渲染会触发本 effect）。
       站点从 0 变成 N 时 key 变了，会再 fit 一次，这是要的。 */
    const key = `${selectedKey}|${pts.length}`
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
    // 只按「选中的人 + 站点集合」驱动；people/sites 的其它变化不应重定位
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, sites])

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
        避免「搜一个无主站点，把正在看的上下文抹掉」。 */
  const handlePickSite = useCallback((site: ManagedSite) => {
    setFlyTarget({ lat: site.lat, lng: site.lng, tick: Date.now() })
    const ownerKey = site.owner_keys?.[0]
    if (ownerKey && people.some(p => p.name_key === ownerKey)) {
      onSelect(ownerKey)
    }
  }, [onSelect, people])

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

      {/* MapController 只负责「初始 / 取消选中后」的全国视角；
          选中态的取景由下方聚焦 effect 独占（见那里的注释）。 */}
      <MapController center={LB_CENTER} zoom={LB_ZOOM} />
      <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} />

      {/* 地图左上角搜索框（人员 + 站点） */}
      <MapSearch
        people={people}
        selectedKey={selectedKey}
        sites={sites}
        onPickPerson={handlePickPerson}
        onPickSite={handlePickSite}
      />


      {loading && people.length === 0 && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 500, pointerEvents: 'none',
        }}>
          <Spin />
        </div>
      )}

      {/* 县界轮廓（最底层，先于站点与人员绘制）。
          颜色取主题实值（SVG 不认 CSS 变量，与 GISMap 的 COUNTY_BAND_COLORS 同一约束）。
          虚线描边沿用 GIS 页的样式，保持两页地图形感一致。 */}
      {counties.map(c => (
        <Polygon
          key={`county-${c.name}`}
          positions={c.polygons as any}
          pathOptions={{
            color: isDark ? '#4a6a8f' : '#9fb3c8',
            fillColor: isDark ? '#4a6a8f' : '#9fb3c8',
            fillOpacity: isDark ? 0.06 : 0.04,
            weight: 1,
            opacity: 0.75,
            dashArray: '4 3',
            /* `interactive: false` —— 县界只是**装饰性底图**，没有任何点击行为。
               Leaflet 的 SVG 路径默认 interactive，会带 `pointer-events: auto`
               拦下命中：哪怕 z-index 已经把人员针抬到它上面，只要县界仍可交互，
               落在县界范围内的点击还是会先被它吃掉（2026-10-21 实测的命中链
               `mousedown → <path>` 就是它）。装饰层不该有命中，故显式关掉。 */
            interactive: false,
          }}
        />
      ))}

      {/* 负责站点层（2026-10-21 起集合 = `master_site_db.fme_name`，不再是「WO 涉及过的站」） */}
      {sites.map(s => {
        /* 三档取色，优先级 红 > 浅蓝 > 绿。
           「未清除」不再单独占一档颜色（用户的配色只有三色），
           改由**半径**表达：告警站 8px > 有未清除 7px > 其余 6px。 */
        const color = siteColor(s)
        return (
          <CircleMarker
            key={`site-${s.site_id}`}
            center={[s.lat, s.lng]}
            radius={s.has_alarm ? 8 : s.uncleared > 0 ? 7 : 6}
            color={color}
            fillColor={color}
            fillOpacity={0.75}
            weight={2}
          >
            <MapTooltip>
              <div style={{ minWidth: 160, fontSize: '0.75rem' }}>
                <div style={{ fontWeight: 700, marginBottom: 2 }}>{s.site_name || s.site_id}</div>
                <div>{t('person.siteId')}: {s.site_id}</div>
                <div>{t('person.county')}: {s.county || '—'}</div>
                <div>{t('person.colOpenWo')}: {s.wo_count}</div>
                <div>{t('person.colUncleared')}: {s.uncleared}</div>
                <div>{s.has_alarm ? t('person.siteHasAlarm') : t('person.siteNoAlarm')}</div>
              </div>
            </MapTooltip>
          </CircleMarker>
        )
      })}

      {/* 人员 → 其负责站点的连线（仅选中时）。
          2026-10-21 用户要求「连线颜色跟站点同色」：原先一律灰色虚线，
          在国家级缩放下几乎看不见，也分不出哪条指向告警站。 */}
      {selectedPerson && sites.map(s => (
        <Polyline
          key={`line-${s.site_id}`}
          positions={[[selectedPerson.lat as number, selectedPerson.lng as number], [s.lat, s.lng]]}
          pathOptions={{
            color: siteColor(s),
            weight: s.has_alarm ? 2.5 : 1.5,
            opacity: s.has_alarm ? 0.75 : 0.55,
            dashArray: '5 4',
            // 同县界：连线没有点击行为，别让它拦下本该落在人员针上的点击
            interactive: false,
          }}
        />
      ))}

      {/* 人员针
          ⚠⚠ 悬停态**绝不能**进图标（2026-10-21 实测，勿改回去）：
             以前 `hovered` 被拼进 `iconKey` / `html` / 尺寸，于是鼠标一进针，
             `Marker` 的 `useMemo([parent, iconKey])` 就**重建整个 L.Marker 图层**、
             把针的 DOM 元素换掉。无头浏览器抓到的真实时间线：
                 13880 mousedown <path>            （按下，命中人员针）
                 13883 mouseout   <path>           （悬停态复位 → 触发重建）
                 13896 DEL / ADD marker-icon       （DOM 元素被换掉）
                 13987 mouseup <DIV .leaflet-container>
             mousedown 与 mouseup 落在不同元素上，浏览器**根本不产生 click 事件**，
             Leaflet 收不到 marker click —— 这就是「点人没反应 / 抽屉闪一下就没」
             的直接原因。悬停现在纯 CSS 实现（`.gis-person-marker:hover`），
             不动 DOM；`selected` 才重建，而它只在一次点击**完成之后**变化。 */}
      {people.map(p => {
        const selected = p.name_key === selectedKey
        /* 颜色（2026-10-19 用户要求「WO 为 0 的人显示深绿以区别」）：
           选中红 > 未关闭 WO 为 0 深绿 > 其余蓝。
           深绿只用于**未选中**的大多数人 —— 选中必须仍是红，
           否则用户点了一个「没单的人」时看不出选中态。 */
        const color = selected ? SITE_COLORS.rt_alarm_overdue
          : (p.open || 0) === 0 ? '#1a7f37'
          : (isDark ? '#4fc3f7' : '#1890ff')
        const size = selected ? 32 : 26
        const iconH = size * 1.5
        const phone = (p.phone || '').trim()
        // 常驻徽标已含姓名+电话，悬停气泡不再重复渲染同样的内容 ——
        // 只在常驻徽标之外没有信息时（即无）保留为空，避免两层气泡叠在一起。
        const tip = ''
        const openCnt = p.open || 0
        const sitesCnt = p.site_count || 0
        const pmtCnt = p.pmt_open
        // null = 后端取不到 eflow_pm → 显示 —（不得显示 0，AGENTS.md 三.6）
        const pmtText = pmtCnt == null ? '—' : String(pmtCnt)
        const unclearedCnt = p.uncleared || 0
        // 有未清除告警 → 红；否则灰。文字与边框共用同一个色，见 .gis-person-badge
        const badgeColor = unclearedCnt > 0 ? '#ff4d4f' : '#8c8c8c'
        return (
          <Marker
            key={p.name_key}
            position={[p.lat as number, p.lng as number]}
            pane={PERSON_PANE}
            html={
              `<div class="gis-person-anchor">` +
                tip +
                personIconSvg(color, size, selected) +
                /* 常驻徽标（2026-10-19 用户要求，2026-10-21 加 PMT 一项）：
                     第一行 = 姓名 + 电话；
                     第二行 = 负责站点数 | 未关闭 WO 数 | 未关闭 PMT 数。
                   三项的顺序是用户 2026-10-21 指定的。
                   ⚠ PMT 那一项**不跟随页面 30 天窗口**（是「此刻还没关闭」的状态数），
                     与旁边两项口径不同 —— 后端 personnel.py::_pmt_open_index 有完整理由，
                     页面 ⓘ 说明里也必须讲清楚，否则用户会拿它跟 WO 那列做加减。
                   徽标内容全部来自后端，拼进 html 前必须 escapeHtml（AGENTS.md 三.4）。 */
                `<span class="gis-person-badge" style="border-color:${badgeColor}" ` +
                  `title="${escapeHtml(t('person.badgeHint', {
                    name: p.name, phone: phone || '-',
                    sites: sitesCnt, open: openCnt, pmt: pmtText, uncleared: unclearedCnt,
                  }))}">` +
                  `<span class="gis-person-badge-name">${escapeHtml(p.name)}` +
                    (phone ? `<i>${escapeHtml(phone)}</i>` : '') +
                  `</span>` +
                  `<span class="gis-person-badge-stats" style="color:${badgeColor}">` +
                    `<b>${sitesCnt}</b>${escapeHtml(t('person.badgeSitesShort'))}` +
                    `<em>|</em>` +
                    `<b>${openCnt}</b>${escapeHtml(t('person.badgeOpenShort'))}` +
                    `<em>|</em>` +
                    `<b>${pmtText}</b>${escapeHtml(t('person.badgePmtShort'))}` +
                  `</span>` +
                `</span>` +
              `</div>`
            }
            iconSize={[size, iconH]}
            iconAnchor={[size / 2, iconH]}
            /* iconKey 里**没有** hover —— 见上方「人员针」处的实测说明：
               悬停一旦进 iconKey，图层就会在指针下被重建，点击随之丢失。 */
            iconKey={`${selected}-${size}-${unclearedCnt}-${openCnt}-${sitesCnt}-${pmtText}-${p.name}-${phone}`}
            zIndexOffset={selected ? 1000 : 0}
            className="gis-person-marker"
            onClick={() => handleClick(p)}
          />
        )
      })}

      {/* 选中了人、但他一个负责站点都没有 → 在地图上把原因说出来（2026-10-21）。
          实测有人点 Franklin Peter 看到全空，报成「连线没画出来」；他其实是
          supervisor（覆盖 294 站），不是单站负责，站点集合刻意只认 fme_name。
          放**底部居中**：左上是 Leaflet 缩放控件与本层的搜索框，右下是 attribution，
          底部居中三样都避得开。
          `pointerEvents:none` —— 说明条不能拦地图点击，否则点它就取消不了选中。 */}
      {selectedPerson && !sitesLoading && sites.length === 0 && (
        <div style={{
          position: 'absolute', bottom: 28, left: '50%', transform: 'translateX(-50%)',
          maxWidth: 420, zIndex: 1000, pointerEvents: 'none',
          padding: 'var(--wh-space-xs, 4px) var(--wh-space-sm, 8px)',
          borderRadius: 'var(--wh-radius-sm, 4px)',
          background: 'var(--wh-card-bg, rgba(255, 255, 255, 0.9))',
          border: '1px solid rgba(128, 128, 128, 0.35)',
          boxShadow: '0 1px 4px rgba(0, 0, 0, 0.25)',
        }}>
          <NoSitesNote person={selectedPerson} />
        </div>
      )}
    </>
  )
}
