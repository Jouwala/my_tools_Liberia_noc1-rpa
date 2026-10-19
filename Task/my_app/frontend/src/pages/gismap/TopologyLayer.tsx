/* MW 链路批量图层（2026-10-19）
 *
 * 职责：把 `/gis/topology` 返回的 844 条链路一次性画到地图上，并把 popup
 * 内容以 HTML 字符串绑定到每条线上。
 *
 * ============ 为什么不再用 844 个 <Polyline> 组件 ============
 * 原实现在 GISMap.tsx 里直接写：
 *     {topologyLinks.map(link => (
 *        <Polyline ...><Popup>…React 元素…</Popup></Polyline>
 *     ))}
 * 这会让 React 一次性挂载 844 个 Polyline + 844 个 Popup 组件（另有 844 个
 * portal 容器节点）。实测（无头 Chrome，2026-10-19，本机）：
 *   · t=932ms  站点圆点 + 县界画完，首屏已可见；
 *   · t=2480ms 这 844 条线**在同一帧**建出 844 个 SVG path，单帧阻塞 1547ms。
 * 用户感知就是「地图出来了，然后卡住一秒半」。
 *
 * 改为在**一个 useEffect 里用 Leaflet 原生 API 批量建层**后：
 *   · 只创建 1 个 L.LayerGroup + 844 个轻量 L.Polyline，无 React 组件开销；
 *   · popup 用预拼好的 HTML 字符串 bindPopup（Leaflet 直接 setInnerHTML），
 *     不再为每条线 render 一棵 React 子树；
 *   · 建层是同步的，但因为不经 React 协调，单帧耗时降到百毫秒级。
 *
 * ============ 维护约束（改之前先读） ============
 * 1. **样式函数仍由 GISMap 传入**（styleOf）。颜色/线宽/透明度/虚线的分级规则
 *    是业务口径，集中在 GISMap.linkColor 等处并有详细注释，不在本文件重建。
 * 2. **popup HTML 由调用方拼好**（popupHtmlOf）。文案来自 i18n 的 t()，本文件
 *    不持有任何文案；这样语言切换时调用方重算即可。
 * 3. 依赖数组里带上 topologyLinks 与两个回调：样式或文案变化必须重建图层。
 *    建层成本已降到百毫秒级，重建可接受；若将来链路数继续增长，再考虑
 *    只 setStyle 不重建的增量路径。
 * 4. **必须过 isMapAlive**：地图已销毁时建层会 appendChild(undefined) 打崩整页
 *    （2026-09-28 白屏事故，见 LeafletMap.tsx 的 isMapAlive 注释）。
 */
import { useEffect } from 'react'
import L from 'leaflet'
import { useMap, isMapAlive } from '../../components/LeafletMap'
import type { TopologyLink } from './types'

export function TopologyLayer({
  links,
  styleOf,
  popupHtmlOf,
}: {
  links: TopologyLink[]
  /** 单条链路 → Leaflet pathOptions（颜色/线宽/透明度/虚线） */
  styleOf: (l: TopologyLink) => L.PathOptions
  /** 单条链路 → popup 的 HTML 字符串（已转义，见调用方） */
  popupHtmlOf: (l: TopologyLink) => string
}) {
  const map = useMap()

  useEffect(() => {
    // 见文件头第 4 条：已销毁的 map 上建层会打崩整页
    if (!isMapAlive(map)) return
    if (!links.length) return

    const group = L.layerGroup()
    for (const link of links) {
      const line = L.polyline(
        [[link.lat_a, link.lng_a], [link.lat_b, link.lng_b]],
        styleOf(link),
      )
      line.bindPopup(popupHtmlOf(link))
      line.addTo(group)
    }
    group.addTo(map)

    return () => {
      group.remove()
    }
  }, [map, links, styleOf, popupHtmlOf])

  return null
}
