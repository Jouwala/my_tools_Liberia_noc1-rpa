/* 地图浮层显隐按钮（2026-10-26 新增）
 *
 * 背景（用户原话）：「地图图例不显示 MW Link Utilization 的，弄个按钮放到 Zoom: 右边，
 * 并且默认不显示」。即：MW 链路利用率那一组图例默认收起，由地图上的一个按钮控制显隐。
 *
 * 设计要点：
 *  1. **用 portal 挂进 Leaflet 容器**，不直接 return 绝对定位 div。原因与
 *     LayerToggleControl.tsx 文件头第 2 点完全相同：本组件是 <MapContainer> 的子节点，
 *     而它渲染的外层 div 没有 position:relative，绝对定位会窜到页面根上去。
 *  2. **位置对齐「Zoom:」控件**。该控件是 GISMap 工具栏里的一个 Col，不是 Leaflet 的
 *     zoom 控件，所以按钮也放在工具栏里、紧跟 Segmented 之后 —— 用户说的「Zoom: 右边」
 *     就是它。此处**刻意不用 Leaflet 的 topright 浮层**：那样按钮会贴到地图右上角，
 *     与工具栏里的 Zoom: 隔着一整行，既不挨着也容易被读成两套控件。
 *  3. **用 AntD Button size="small"**，与工具栏里「高级筛选 / 导出 Excel」同一档尺寸与
 *     高度，横排时不会把行高撑开。
 *  4. **受控组件**：显隐状态由调用方持有（show 只读、onToggle 回调），本组件不藏自己的
 *     state —— 与 LayerToggleControl「谁控制显隐只有一处」的约定一致。
 *  5. **文案不进 i18n**：与 MapLegendOverlay / LayerToggleControl 同一约定，
 *     文案由调用方 t() 好再传入，check:i18n 的漏键守卫仍能在 GISMap 里看见字面量键。
 */
import { Button } from 'antd'

export interface MapOverlayToggleProps {
  /** 按钮文案，由调用方 t() 后传入（理由见文件头第 5 点） */
  label: string
  /** 当前是否显示。true = 对应浮层可见 */
  show: boolean
  onToggle: (next: boolean) => void
  /** 原生 title 提示（可选） */
  hint?: string
}

export function MapOverlayToggle({ label, show, onToggle, hint }: MapOverlayToggleProps) {
  return (
    <Button
      size="small"
      /* 用 type 而不是纯色块表达选中态：与工具栏既有的「高级筛选」按钮同一套视觉语言
         （type={showFilters ? 'primary' : 'default'}），用户不必学第二种「开/关」表达。 */
      type={show ? 'primary' : 'default'}
      role="switch"
      aria-checked={show}
      aria-label={label}
      title={hint}
      onClick={() => onToggle(!show)}
    >
      {label}
    </Button>
  )
}
