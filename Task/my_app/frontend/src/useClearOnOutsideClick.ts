/* 点击「地图 / 抽屉 / 弹窗之外」取消选中 —— 带地图的看板页共用
 *
 * **为什么需要它**（2026-10-21，`?page=person` 用户报的问题）：
 *   地图页的选中态一直只由 Leaflet 自己的 `map.on('click')` 清理 —— 也就是
 *   **只有点在地图上**才算「点别处」。点右侧卡片、下方表格、筛选条、页面背景
 *   都不会取消，选中的人一直高亮着、站点圈和连线一直画着。用户的直觉是
 *   「我点了别的地方就该取消」。
 *
 * **四类点击必须放行，否则这个监听会自己打断自己的 handler**：
 *   · `.leaflet-container` —— 地图内部的取消归 Leaflet 的 `map.on('click')` 管
 *     （它还要区分「点人 / 点站点圆点 / 点空白」，两套逻辑并存会打架）；
 *   · `.ant-drawer` —— 下钻抽屉里搜索、翻页、切页签、导出都是正常操作，
 *     不能算「点了别处」（person 页的抽屉是 `mask={false}`，本来就靠外部点击
 *     关不掉，这里再明确排除一次）；
 *   · `.ant-table-row` —— 表格行本身就是「选中另一个人」的入口。React 的
 *     onClick 在 root 容器上、document 监听在它之后跑，不排除就会刚选中又被清掉；
 *   · `.dcm-overlay` —— 项目统一的下钻弹窗 `components/DraggableClickModal`
 *     的遮罩层（它刻意「点遮罩不关闭，避免误触」，见该文件第 5 行注释）。
 *
 * `clear` 必须是稳定引用（`useCallback` 包一层），否则每次渲染都会重挂监听。
 */
import { useEffect } from 'react'

/** 这些容器内部的点击**不**算「点了别处」 */
const KEEP_SELECTORS = [
  '.leaflet-container',
  '.ant-drawer',
  '.ant-table-row',
  '.dcm-overlay',
]

export function useClearOnOutsideClick(active: boolean, clear: () => void) {
  useEffect(() => {
    if (!active) return
    const onDocClick = (ev: MouseEvent) => {
      const el = ev.target as HTMLElement | null
      if (!el || typeof el.closest !== 'function') return
      if (KEEP_SELECTORS.some(sel => el.closest(sel))) return
      clear()
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [active, clear])
}
