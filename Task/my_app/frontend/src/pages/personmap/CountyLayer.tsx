/* 县界底图层（2026-10-28 从 PersonMapView 抽出，行数纪律 AGENTS.md 三.2）
 *
 * 只画 15 个县的**类别色**多边形：颜色只表达「这是哪个县」，不带任何数值语义 ——
 * 与 GIS 页按实时告警数分档的 `COUNTY_BAND_COLORS` 是两回事，照搬会让人
 * 误读为人员告警分布（原始论证见 `useCountyTags.ts` 文件头与手册 11a）。
 *
 * 取自：`/gis/county-boundaries`（与 GIS 页共用同一份静态 GeoJSON，前端
 * `cachedGet` 缓存），县 → 颜色映射由 `useCountyTags.ts` 按县名字典序稳定分配。
 */
import { Polygon } from '../../components/LeafletMap'
import { COUNTY_FILL_OPACITY } from './useCountyTags'
import type { CountyBoundary } from '../gismap/types'

export function CountyLayer({
  counties, countyColor, isDark,
}: {
  counties: CountyBoundary[]
  /** 县名 → 十六进制类别色（SVG 不认 CSS 变量，故由调用方给实值） */
  countyColor: Map<string, string>
  isDark: boolean
}) {
  return (
    <>
      {counties.map(c => (
        <Polygon
          key={`county-${c.name}`}
          positions={c.polygons as any}
          pathOptions={{
            color: countyColor.get(c.name) || '#9aa5b5',
            fillColor: countyColor.get(c.name) || '#9aa5b5',
            fillOpacity: isDark ? COUNTY_FILL_OPACITY.dark : COUNTY_FILL_OPACITY.light,
            weight: 1.5,
            opacity: 0.85,
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
    </>
  )
}
