/* PMTiles 矢量底图图层（Leaflet + protomaps-leaflet）
 *
 * 职责：把一个 PMTiles 归档渲染成 Leaflet 图层，并按深浅主题切换配色。
 *
 * 为什么单独成文件：这是 LeafletMap.tsx 的**可选扩展**，protomaps-leaflet 只在这个
 * 文件里被 import。这样即使将来弃用矢量底图，删掉这一个文件即可，
 * LeafletMap.tsx 与栅格 TileLayer 不受影响（见该文件「不引入新依赖」的设计意图）。
 *
 * 用法（与既有 <TileLayer> 写法对称）：
 *   <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} />
 *
 * ⚠️ 三个实测要点：
 *  1. **必须传 backgroundColor**。自有瓦片没有 earth 图层，海洋/空白处的底色完全由
 *     这个参数决定；不传会得到透明背景，在深色主题下表现为「地图是黑的」，看起来
 *     像渲染失败。（浅色主题下则像白纸，同样难看出问题。）
 *  2. **主题切换要重建图层**。protomaps 的 paintRules/labelRules 是在构造时传入的，
 *     没有运行时换配色的 API，故 isDark 变化时必须 remove 旧层再 add 新层。
 *     依赖数组里带上 isDark 即可。若只改 paintRules 而不重建，切主题不会生效。
 *  3. **showLabels 默认 false**（2026-10-02 用户要求）。瓦片里地名密度极高
 *     （hamlet 12607 + isolated_dwelling 2590），全开会「密密麻麻什么都看不清」。
 *     关闭的做法是**传空 labelRules 数组**而不是删规则 —— protomaps 没有开关参数，
 *     空数组即「不标注任何文字」。与第 2 点同理，它必须进依赖数组才能实时生效。
 *  4. **showRoads 默认 true**（2026-10-03 新增开关）。关闭时不生成 transportation
 *     的 paintRules，也不生成路名 labelRules（道路没了路名浮空会很怪）。
 *     与 showLabels 同一机制：构造时固化，须进依赖数组、靠重建图层生效。
 */
import { useEffect } from 'react'
import { leafletLayer } from 'protomaps-leaflet'
import { useMap, isMapAlive } from '../../components/LeafletMap'
import { basemapTheme, BASEMAP_MAX_ZOOM, BASEMAP_ATTRIBUTION } from './basemap'
import { buildLabelRules, buildPaintRules } from './pmtilesPaint'

export function PmtilesLayer({
  url,
  isDark,
  maxZoom = BASEMAP_MAX_ZOOM,
  showLabels = false,
  showRoads = true,
}: {
  url: string
  isDark?: boolean
  maxZoom?: number
  /** 是否绘制地名称注。默认关闭（理由见文件头第 3 点）。 */
  showLabels?: boolean
  /** 是否绘制道路/铁路。默认开启（保持既有观感）。
   *  关闭时 paintRules 不生成 transportation 规则、labelRules 也不生成路名 ——
   *  与 showLabels 同理，因规则在构造时固化，需重建图层才生效。 */
  showRoads?: boolean
}) {
  const map = useMap()

  useEffect(() => {
    // 见 isMapAlive 注释：地图已销毁时 addTo 会 appendChild(undefined) 打崩整页
    if (!isMapAlive(map)) return

    const theme = basemapTheme(isDark)
    const layer = leafletLayer({
      url,
      paintRules: buildPaintRules(theme, showRoads),
      // 关闭时传空数组（不是删规则）：protomaps 无开关参数，空数组 = 不标任何文字
      labelRules: showLabels ? buildLabelRules(theme, showRoads) : [],
      // 海陆未覆盖处的底色。**不可省**，理由见文件头。
      backgroundColor: theme.background,
      // 数据本身到 z14；超采样到 z14 以上时由 maxDataZoom 控制放大行为
      maxDataZoom: maxZoom,
      attribution: BASEMAP_ATTRIBUTION,
    } as Parameters<typeof leafletLayer>[0])

    layer.addTo(map)
    return () => {
      layer.remove()
    }
    // isDark / showLabels / showRoads 都必须进依赖：都在构造时固化，需重建图层才生效
  }, [map, url, isDark, maxZoom, showLabels, showRoads])

  return null
}
