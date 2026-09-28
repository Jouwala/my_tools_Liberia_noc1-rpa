/* 地图「点击后才允许滚轮缩放」（2026-09-18 加）
 *
 * 背景：门户 MsPortal 的 Central Liberia Regional Topology（#secTopo）把地图页
 *   iframe 内嵌进来并撑满整个区块。此时鼠标只要落在区块上，滚轮就被 Leaflet 的
 *   scrollWheelZoom 吃掉去缩放地图 —— 用户想滚动门户页面，却把地图放大了。
 *
 * 做法（Leaflet 官方推荐的 click-to-activate）：
 *   · 内嵌在门户里时，初始关闭滚轮缩放（MapContainer 的 scrollWheelZoom={false}）；
 *   · 点击地图 → 打开滚轮缩放；指针移出地图、或地图失焦（点到别处）→ 立刻收回；
 *   · 关闭状态下 Leaflet 不消费 wheel 事件，滚动按浏览器默认链式传给门户页面，
 *     页面照常滚动（不会出现「滚不动」的死区）。
 *   · 独立打开（window.top === window.self 且不带 mwembed=1）时本组件完全不介入，
 *     行为与改动前一致：滚轮即缩放。
 *
 * 注意：判断「是否内嵌」而不是「是否门户」，是因为门户的看板预览弹窗（viewer.html）
 *   也是 iframe 内嵌，同样不希望地图抢走外层页面的滚动。
 */
import { useEffect } from 'react'
import { useMap } from './LeafletMap'

/** 是否处于内嵌上下文：门户 iframe 的 src 带 mwembed=1；兜底看是否被 iframe 套住。
 *  跨域取 window.top 会抛异常 —— 抛异常说明确实在被别人嵌，按内嵌处理。 */
export function isEmbeddedInPortal(): boolean {
  try {
    if (new URLSearchParams(window.location.search).get('mwembed') === '1') return true
  } catch (e) { /* ignore */ }
  try {
    return window.self !== window.top
  } catch (e) {
    return true
  }
}

export default function MapWheelZoomOnClick() {
  const map = useMap()

  useEffect(() => {
    if (!isEmbeddedInPortal()) return

    const wheel = map.scrollWheelZoom
    const container = map.getContainer()
    const enable = () => { wheel.enable() }
    const disable = () => { wheel.disable() }

    disable()                                   // 双保险：MapContainer 已传 false
    map.on('click', enable)
    map.on('blur', disable)
    container.addEventListener('mouseleave', disable)

    return () => {
      map.off('click', enable)
      map.off('blur', disable)
      container.removeEventListener('mouseleave', disable)
      wheel.enable()                            // 卸载时还原 Leaflet 默认，不留副作用
    }
  }, [map])

  return null
}
