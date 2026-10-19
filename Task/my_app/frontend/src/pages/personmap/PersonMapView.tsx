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
import { Marker, CircleMarker, Polyline, Polygon, Tooltip as MapTooltip, useMap, isMapAlive } from '../../components/LeafletMap'
import api from '../../api'
import { cachedGet } from '../../cache'
import { PmtilesLayer } from '../gismap/PmtilesLayer'
import type { LatLngBoundsExpression } from 'leaflet'
import { MapController } from '../gismap/MapController'
import { BASEMAP_PMTILES_URL } from '../gismap/basemap'
import { SITE_COLORS } from '../gismap/types'
import { escapeHtml, personIconSvg } from '../gismap/personIcon'
import { MapSearch } from './MapSearch'
import type { PersonRow, ManagedSite } from './types'
import type { CountyBoundary } from '../gismap/types'

/** 默认取景：利比里亚全国居中（与 GIS 页 LB_CENTER / ZOOM 同源思路，
 *  但本页画布更宽，用 zoom=7.5 即可装下全境）。 */
const LB_CENTER: [number, number] = [(3.9 + 8.75) / 2, (-11.7 + -7.3) / 2]
const LB_ZOOM = 7.5

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
  const [hoverKey, setHoverKey] = useState<string | null>(null)
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

  /* 点人时置位，供 map 的 click 处理器跳过 —— Leaflet 会把 marker 的点击冒泡到 map，
     若不区分，点人的瞬间就会被 map 处理器当成「点空白」清掉选中态。 */
  const personClickRef = useRef(false)

  useEffect(() => {
    if (!isMapAlive(map)) return
    const onMapClick = (e: any) => {
      // 事件源判定：点在人员针（L.Marker，有 setIcon）上不清理。
      // 站点圆点是 L.CircleMarker，只有 setStyle/setRadius、没有 setIcon ——
      // 两者都能 getLatLng，故不能用 getLatLng 区分（GIS 页踩过这个坑）。
      const src = e?.sourceTarget
      if (src && typeof src.setIcon === 'function') {
        personClickRef.current = false
        return
      }
      if (personClickRef.current) {
        personClickRef.current = false
        return
      }
      onSelect(null)
    }
    map.on('click', onMapClick)
    return () => { map.off('click', onMapClick) }
  }, [map, onSelect])

  const selectedPerson = useMemo(
    () => people.find(p => p.name_key === selectedKey) || null,
    [people, selectedKey],
  )

  const handleClick = useCallback((p: PersonRow) => {
    personClickRef.current = true
    onSelect(p.name_key === selectedKey ? null : p.name_key)
  }, [onSelect, selectedKey])

  /* 选中人员时把它的站点纳入视野：不强制改 zoom，只做「若不在视野内则平移」，
     避免每次点人地图都跳一下。实现用两次 setView 太粗暴，这里直接让
     MapController 的 center 跟随选中人员。 */
  /* 搜索定位目标。MapController 只在 center/zoom **变化**时才 setView，
     而用户可能连续搜同一个站点附近的不同点 —— 用 tick 强制触发一次重定位。
     tick 用时间戳而不是递增计数：避免组件重建后计数器归零导致「不生效」。 */
  const [flyTarget, setFlyTarget] = useState<{ lat: number; lng: number; tick: number } | null>(null)

  /* 2026-10-19（用户要求「点击人员后地图自动聚焦到人和对应的站点」）：
     选中人员后不再只是「把地图中心挪到人身上」，而是用 fitBounds 把
     **该人员 + 其全部站点**一起框进视野 —— 站点往往分布在好几个县，
     只居中到人身上时站点会落在画布外，用户还得自己拖。

     为什么不做成 MapController 的 center/zoom：
       ① fitBounds 需要同时看人 + N 个站点，是一个**包围盒**，不是单个中心点；
       ② MapController 只在 center/zoom 变化时 setView，同一个人重复点选
          时它不会动，而用户预期是"再点一次也回到这个范围"。
     与搜索定位（flyTarget）同一套做法：用 tick 驱动的独立 effect。

     ⚠️ 依赖 sites 是有意的：点击人时 managed-sites 是异步回来的，
        先到的是空数组（此时只聚焦到人），站点到达后本 effect 重跑，
        再按完整包围盒 fit 一次 —— 这正是"聚焦到人和对应的站点"要的效果。 */
  const focusKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (!isMapAlive(map)) return
    if (!selectedKey) { focusKeyRef.current = null; return }
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

  const center: [number, number] = selectedPerson
    ? [selectedPerson.lat as number, selectedPerson.lng as number]
    : LB_CENTER
  const zoom = selectedPerson ? Math.max(LB_ZOOM, 8.5) : LB_ZOOM

  /* 搜索定位：直接对 map 调 flyTo，不走 MapController ——
     MapController 只在 center/zoom 变化时 setView，而「搜同一个站点附近的两个点」
     或「搜一个与当前选中人员重合的点」时 center 可能不变，导致点了没反应。
     直接用 tick 驱动的 effect 保证每次选中都飞一次。
     飞完把 flyTarget 置空，让后续「选中人员」的 center 重新生效。 */
  useEffect(() => {
    if (!flyTarget || !isMapAlive(map)) return
    map.flyTo([flyTarget.lat, flyTarget.lng], Math.max(map.getZoom(), 12), { duration: 0.6 })
    setFlyTarget(null)
    // 只依赖 tick：lat/lng 变化已隐含在新的 tick 里
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTarget?.tick])

  /* 搜索选中人员 → 与点击人员针同义：交给页面更新 selectedKey，
     视图中心由上面的 center 跟随（选中后自动飞行到该人）。 */
  const handlePickPerson = useCallback((nameKey: string) => {
    onSelect(nameKey)
  }, [onSelect])

  /* 搜索选中站点（2026-10-19 用户要求「定位并选中负责人」）：
     ① 飞行到该站点；
     ② 若后端回了可选的负责人键（该站点未关闭 WO 的负责人中、有坐标的那位），
        一并选中 —— 这样右侧连线与 KPI 会切到那个人。
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
      <MapController center={center} zoom={zoom} />
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
          }}
        />
      ))}

      {/* 选中人员的 WO 站点层 */}
      {sites.map(s => {
        // 有实时告警 → 大红；有未清除 WO → 橙；其余 → 主题青
        const color = s.has_alarm
          ? SITE_COLORS.rt_alarm_overdue
          : s.uncleared > 0 ? '#fa8c16' : (isDark ? '#00d9ff' : '#0d9488')
        return (
          <CircleMarker
            key={`site-${s.site_id}`}
            center={[s.lat, s.lng]}
            radius={s.has_alarm ? 8 : 6}
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

      {/* 人员 → 其站点连线（仅选中时） */}
      {selectedPerson && sites.map(s => (
        <Polyline
          key={`line-${s.site_id}`}
          positions={[[selectedPerson.lat as number, selectedPerson.lng as number], [s.lat, s.lng]]}
          pathOptions={{
            color: s.has_alarm ? SITE_COLORS.rt_alarm_overdue : '#8c8c8c',
            weight: s.has_alarm ? 2.5 : 1.5,
            opacity: 0.55,
            dashArray: '5 4',
          }}
        />
      ))}

      {/* 人员针 */}
      {people.map(p => {
        const selected = p.name_key === selectedKey
        const hovered = p.name_key === hoverKey
        /* 颜色优先级（2026-10-19 用户要求「WO 为 0 的人显示深绿以区别」）：
           选中红 > 悬停橙 > 未关闭 WO 为 0 深绿 > 其余蓝。
           深绿只用于**未选中未悬停**的大多数人 —— 选中/悬停必须仍是红/橙，
           否则用户点了一个「没单的人」时看不出选中态。 */
        const color = selected ? SITE_COLORS.rt_alarm_overdue
          : hovered ? '#fa8c16'
          : (p.open || 0) === 0 ? '#1a7f37'
          : (isDark ? '#4fc3f7' : '#1890ff')
        const size = (selected || hovered) ? 32 : 26
        const iconH = size * 1.5
        const phone = (p.phone || '').trim()
        // 常驻徽标已含姓名+电话，悬停气泡不再重复渲染同样的内容 ——
        // 只在常驻徽标之外没有信息时（即无）保留为空，避免两层气泡叠在一起。
        const tip = ''
        const openCnt = p.open || 0
        const sitesCnt = p.site_count || 0
        const unclearedCnt = p.uncleared || 0
        // 有未清除告警 → 红；否则灰。文字与边框共用同一个色，见 .gis-person-badge
        const badgeColor = unclearedCnt > 0 ? '#ff4d4f' : '#8c8c8c'
        return (
          <Marker
            key={p.name_key}
            position={[p.lat as number, p.lng as number]}
            pane="personPane"
            html={
              `<div class="gis-person-anchor">` +
                tip +
                personIconSvg(color, size, selected) +
                /* 常驻徽标（2026-10-19 用户要求）：
                     第一行 = 姓名 + 电话；
                     第二行 = 未关闭 WO 数 + 负责站点数。
                   徽标内容全部来自后端，拼进 html 前必须 escapeHtml（AGENTS.md 三.4）。 */
                `<span class="gis-person-badge" style="border-color:${badgeColor}" ` +
                  `title="${escapeHtml(t('person.badgeHint', { name: p.name, phone: phone || '-', open: openCnt, sites: sitesCnt, uncleared: unclearedCnt }))}">` +
                  `<span class="gis-person-badge-name">${escapeHtml(p.name)}` +
                    (phone ? `<i>${escapeHtml(phone)}</i>` : '') +
                  `</span>` +
                  `<span class="gis-person-badge-stats" style="color:${badgeColor}">` +
                    `<b>${openCnt}</b>${escapeHtml(t('person.badgeOpenShort'))}` +
                    `<em>|</em>` +
                    `<b>${sitesCnt}</b>${escapeHtml(t('person.badgeSitesShort'))}` +
                  `</span>` +
                `</span>` +
              `</div>`
            }
            iconSize={[size, iconH]}
            iconAnchor={[size / 2, iconH]}
            iconKey={`${selected}-${hovered}-${size}-${unclearedCnt}-${openCnt}-${sitesCnt}-${p.name}-${phone}`}
            zIndexOffset={selected ? 1000 : hovered ? 900 : 0}
            className="gis-person-marker"
            onClick={() => handleClick(p)}
            onMouseOver={() => setHoverKey(p.name_key)}
            onMouseOut={() => setHoverKey(cur => (cur === p.name_key ? null : cur))}
          />
        )
      })}
    </>
  )
}
