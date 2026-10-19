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
import { Marker, CircleMarker, Polyline, Tooltip as MapTooltip, useMap, isMapAlive } from '../../components/LeafletMap'
import { PmtilesLayer } from '../gismap/PmtilesLayer'
import { MapController } from '../gismap/MapController'
import { BASEMAP_PMTILES_URL } from '../gismap/basemap'
import { SITE_COLORS } from '../gismap/types'
import { escapeHtml, personIconSvg } from '../gismap/personIcon'
import type { PersonRow, ManagedSite } from './types'

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
  const center: [number, number] = selectedPerson
    ? [selectedPerson.lat as number, selectedPerson.lng as number]
    : LB_CENTER
  const zoom = selectedPerson ? Math.max(LB_ZOOM, 8.5) : LB_ZOOM

  return (
    <>
      <MapController center={center} zoom={zoom} />
      <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} />

      {loading && people.length === 0 && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 500, pointerEvents: 'none',
        }}>
          <Spin />
        </div>
      )}

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
        const color = selected ? SITE_COLORS.rt_alarm_overdue
          : hovered ? '#fa8c16'
          : (isDark ? '#4fc3f7' : '#1890ff')
        const size = (selected || hovered) ? 32 : 26
        const iconH = size * 1.5
        const phone = (p.phone || '').trim()
        const tip = hovered
          ? `<span class="gis-person-tip"><b>${escapeHtml(p.name)}</b>` +
            (phone ? `<i>${escapeHtml(phone)}</i>` : '') + `</span>`
          : ''
        // 标签：未清除/未关闭（与 GIS 页同口径、同含义）
        const openCnt = p.open || 0
        const unclearedCnt = p.uncleared || 0
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
                `<span class="gis-person-badge" style="border-color:${badgeColor};color:${badgeColor}" ` +
                  `title="${escapeHtml(t('person.badgeHint', { uncleared: unclearedCnt, open: openCnt }))}">` +
                  `${escapeHtml(t('person.badgeLabel'))}:${unclearedCnt}/${openCnt}` +
                `</span>` +
              `</div>`
            }
            iconSize={[size, iconH]}
            iconAnchor={[size / 2, iconH]}
            iconKey={`${selected}-${hovered}-${size}-${unclearedCnt}-${openCnt}`}
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
