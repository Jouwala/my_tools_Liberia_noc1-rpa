import { useEffect } from 'react'
import { useMap } from '../../components/LeafletMap'

/* 地图画布**实测参数**回报（2026-10-23 新增）。
 *
 * 用途只有一个：给县名标签避让（countyLabelLayout.ts 的 makeProjector）提供
 * 真实的画布尺寸与当前 zoom。原先这些值写死为「门户中列 570×856 + zoomLevel 档位」，
 * 但 v2 门户各壳的内嵌画布远不止这个宽（实测 ~898px），投影空间与真实渲染
 * 对不上：zoom=8 下国土在投影里需要 ~800px，570 宽的假画布把东部各县的候选位
 * 全部「夹」到右缘同一列 → 假冲突 → 标签被竖着摞到邻县地盘上
 * （实测 SINOE 叠进 RIVER GEE、MARYLAND 叠在 GRAND KRU 上）。
 *
 * 回报时机：
 *   · 挂载后立即一次（Leaflet 容器此时已完成布局）；
 *   · ResizeObserver：窗口/版式变化导致容器尺寸变化时；
 *   · zoomend：地图缩放（档位下拉或滚轮）后，zoom 是投影换算 degPerPx 的关键输入。
 *
 * 为什么回报 zoom 而不复用 zoomLevel state：zoomLevel 只是「档位下拉的请求值」，
 * 用户滚轮缩放后地图真实 zoom 会偏离档位值，而 react-leaflet 不会把滚轮结果
 * 写回受控 prop —— 避让必须跟真实 zoom 走。父侧对等值做了 bail-out，
 * 这里不需要关心重渲次数。
 */
export function MapMetrics({
  onMetrics,
}: {
  onMetrics: (m: { width: number; height: number; zoom: number }) => void
}) {
  const map = useMap()
  useEffect(() => {
    const container = map.getContainer()
    const report = () => {
      onMetrics({
        width: container.clientWidth,
        height: container.clientHeight,
        zoom: map.getZoom(),
      })
    }
    report()
    const ro = new ResizeObserver(report)
    ro.observe(container)
    map.on('zoomend', report)
    return () => {
      ro.disconnect()
      map.off('zoomend', report)
    }
  }, [map, onMetrics])
  return null
}
