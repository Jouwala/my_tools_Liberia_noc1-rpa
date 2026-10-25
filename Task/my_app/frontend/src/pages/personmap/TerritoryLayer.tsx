/* 「默认站点」辖区批量图层（2026-10-23，?page=person 地图开关）
 *
 * 职责：把 `/gis/personnel/fme-territories` 返回的 24 人 / 1010 条人-站对
 * 一次性画到地图上：每人**一条颜色**的「质心 → 各站点」连线 + 去重后的
 * 站点小圆点（带悬停提示）。
 *
 * ============ 为什么不用 React 组件逐条渲染 ============
 * 与 gismap/TopologyLayer.tsx 同一教训（2026-10-19 实测）：844 个 <Polyline>
 * 在同一帧建出 844 个 SVG path、单帧阻塞 1547ms。本层 1010 条线 + 824 个点，
 * 量级只大不小，故照搬其解法 —— **一个 useEffect 里用 Leaflet 原生 API
 * 批量建层**（L.layerGroup + 轻量 L.Polyline / L.CircleMarker），
 * 不经 React 协调，建层成本百毫秒级。
 *
 * ============ 结构决定 ============
 * · 连线：`interactive: false` —— 连线没有点击行为，若保持默认可交互，
 *   会像县界多边形那样拦下本该落到人员针/地图空白上的点击
 *   （PersonMapView 的 map click 处理器靠 sourceTarget 判定，线没有 setIcon，
 *   会被当成「点空白」；干脆不参与命中）。
 * · 站点圆点：**按 site_id 去重** —— `A / B` 双人共担的站点会有两人各一条
 *   线指向它，但点只画一个（中性色），归属信息由线的颜色表达；
 *   重复画两个点只会出现一深一浅的重影。
 * · 选中的人员（selectedKey）：其连线**不画** —— 选中后 PersonMapView 的
 *   详细图层（三档配色的大圆点 + 连线）会在同一批站点上画一遍，
 *   两层叠画就是同坐标双圈重影。站点小圆点保留（被大圆点盖住，无害）。
 * · 必须过 isMapAlive：已销毁的 map 上建层会 appendChild(undefined) 打崩
 *   整页（2026-09-28 白屏事故，见 LeafletMap.tsx 注释）。
 */
import { useEffect } from 'react'
import L from 'leaflet'
import { useMap, isMapAlive } from '../../components/LeafletMap'
import type { TerritoryPerson, TerritorySite } from './types'

export function TerritoryLayer({
  persons, selectedKey, colorOf, siteOwners, tipHtmlOf, isDark,
}: {
  persons: TerritoryPerson[]
  /** 当前选中人员（其连线让位给详细图层，见文件头） */
  selectedKey: string | null
  /** 人 → 辖区色（PersonMapView 按名字序稳定分配） */
  colorOf: (nameKey: string) => string
  /** site_id → 负责人名列表（A/B 双人共担会有两个），站点提示用 */
  siteOwners: Map<string, string[]>
  /** 站点悬停提示的 HTML 字符串（调用方拼好并已转义） */
  tipHtmlOf: (site: TerritorySite, owners: string[]) => string
  isDark: boolean
}) {
  const map = useMap()

  useEffect(() => {
    if (!isMapAlive(map) || !persons.length) return

    const group = L.layerGroup()

    // 站点小圆点：去重后只画一次（中性色 —— 归属由线色表达，点色不掺和）
    const dotColor = isDark ? '#9db2cc' : '#5f748c'
    const seen = new Set<string>()
    for (const tp of persons) {
      for (const s of tp.sites) {
        if (seen.has(s.site_id)) continue
        seen.add(s.site_id)
        const dot = L.circleMarker([s.lat, s.lng], {
          radius: 3,
          color: dotColor,
          fillColor: dotColor,
          fillOpacity: 0.55,
          weight: 1,
        })
        dot.bindTooltip(tipHtmlOf(s, siteOwners.get(s.site_id) || []),
          { sticky: true, direction: 'top' })
        dot.addTo(group)
      }
    }

    // 质心 → 站点连线：每人一色；选中者的线让位给详细图层。
    // weight/opacity 取值（2026-10-23 目检后定）：首版 1px/0.35 在全国取景下
    // 几乎看不见（视觉审查反馈「连线稀疏、读不出放射状辖区」），
    // 提到 1.5px/0.5 —— 24 人的线在此亮度下仍不糊，辖区轮廓读得出来。
    for (const tp of persons) {
      if (tp.name_key === selectedKey) continue
      const color = colorOf(tp.name_key)
      for (const s of tp.sites) {
        L.polyline(
          [[tp.centroid.lat, tp.centroid.lng], [s.lat, s.lng]],
          { color, weight: 1.5, opacity: 0.5, interactive: false },
        ).addTo(group)
      }
    }

    group.addTo(map)
    return () => { group.remove() }
  }, [map, persons, selectedKey, colorOf, siteOwners, tipHtmlOf, isDark])

  return null
}
