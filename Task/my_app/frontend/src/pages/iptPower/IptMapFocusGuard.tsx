/* ipt_power 地图「首次点圆点没反应」的修复（2026-11-09）
 *
 * **症状**：页面刚加载后，第一次点站点圆点**必定**打不开抽屉；第二个起都正常。
 * 与县底色无关（切到「不填充」同样复现），是 Leaflet 键盘模块的旧毛病。
 *
 * **根因**（headless Chrome 实测）：`leaflet-src.js:14009` 的 Keyboard._focus 在
 * mousedown 时执行 `this._map._container.focus()`，紧接着 `window.scrollTo(left, top)`
 * 试图补偿。但本页真正的滚动容器是内层 `#main-content`，不是 window —— 补偿落空，
 * 浏览器把刚聚焦的地图容器滚进视口，实测 `scrollTop: 0 → 35`。
 * 圆点因此从光标底下跑掉，mouseup 落到别的元素上，mousedown/mouseup 目标不同，
 * **浏览器根本不产生 click**，Leaflet 收不到 CircleMarker 的 click → 抽屉不开。
 * 第二次点击时容器已聚焦、不再滚动，所以正常。
 *
 * **修法**：只摘掉 Leaflet 建图时给容器加的 `tabindex`，`focus()` 对不可聚焦的
 * div 就是空操作，滚动无从发生。刻意**不** `preventDefault()` mousedown ——
 * 人员页（PersonMapView.tsx:251）那边连图标元素的 tabindex 都要反复摘，是因为
 * 它的人员针是自定义 Marker、每次重建都会长回 tabindex；本页圆点是 SVG path，
 * 没有第二处可聚焦元素，一刀就够，少拦一次默认行为就少一分拖地图被破坏的风险。
 *
 * 与 `PersonMapView` 同一取舍的验证口径：加载后立刻点第一个圆点，应直接打开抽屉，
 * 且 `#main-content.scrollTop` 全程保持 0。
 */
import { useEffect } from 'react'
import { useMap, isMapAlive } from '../../components/LeafletMap'

export function IptMapFocusGuard() {
  const map = useMap()
  useEffect(() => {
    if (!isMapAlive(map)) return
    map.getContainer().removeAttribute('tabindex')
  }, [map])
  return null
}
