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
 *   · `.gis-legend-overlay` —— **地图图例浮层**（`gismap/MapLegendOverlay`；
 *     人员页也复用它，见 `personmap/PersonMapView.tsx`）。图例是地图上的**控件**，
 *     点它的每一行 = 「切换该档的显隐」，属于地图内部的正常操作，
 *     不该被当成「点了地图之外」。⚠ 图例浮层渲染在 MapContainer 的**子层**
 *     里（是 Leaflet 容器 `inner` 的兄弟节点，不在 `.leaflet-container` 之内），
 *     所以它同时会被 Leaflet 的 `map.on('click')` 与本监听同时看到 ——
 *     实测 2026-10-30：人员页点图例某一行会立刻把选中的人清掉、图例跟着消失。
 *
 * **两类必须放过的事件**（2026-10-21 实测，缺一个就是「抽屉闪一下就消失」）：
 *   · **目标已脱离文档**（`!el.isConnected`）—— 选中人员会把该人员的地图针**重建**，
 *     也就是把 mousedown 命中的那个 `<path>` 元素从 DOM 里摘掉。同一次 click
 *     继续冒泡到 document 时 `e.target` 已是游离节点，`closest()` 找不到任何祖先，
 *     会被当成「点在别处」→ 刚打开的抽屉立刻被关掉。
 *   · **本轮点击自身**—— 监听是在选中生效后的 passive effect 里挂上的，
 *     而 React 会在微任务里补跑 effect，此时同一次 click 还没冒泡到 document。
 *     故监听延到下一个宏任务再挂（见下方 `setTimeout`）。
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
  '.gis-legend-overlay',
]

export function useClearOnOutsideClick(active: boolean, clear: () => void) {
  useEffect(() => {
    if (!active) return
    const onDocClick = (ev: MouseEvent) => {
      const el = ev.target as HTMLElement | null
      if (!el || typeof el.closest !== 'function') return
      // 目标已被 React 从文档里摘掉（选中会重建人员针）→ 无从判断「点在哪」，
      // 一律视为点在地图内放过，否则刚打开的抽屉会被同一次点击关掉。
      if (!el.isConnected) return
      if (KEEP_SELECTORS.some(sel => el.closest(sel))) return
      clear()
    }
    /* 延到下一个宏任务再挂：选中生效后 React 会在**微任务**里补跑本 effect，
       而此时触发选中的那次 click 仍在向 document 冒泡 —— 立刻挂上就会被
       自己这一下打到。宏任务一定晚于整轮事件派发。 */
    const timer = window.setTimeout(() => {
      document.addEventListener('click', onDocClick)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('click', onDocClick)
    }
  }, [active, clear])
}
