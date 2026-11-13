/**
 * ECharts 按需入口（2026-11-12 首屏瘦身）。
 *
 * 背景：全站之前走 `echarts-for-react` 默认入口，它内部 `import * as echarts
 * from 'echarts'` 整包引入，echarts chunk 裸 1.16MB / gzip 390KB，且因多个
 * 懒加载页共用它而被收进首屏 vendor 闭包。这里改成 `echarts/core` 按需注册，
 * 只装全站实际用到的图与组件。
 *
 * 全站实际用量（2026-11-12 从 src 全量核实，新增图/组件时必须同步登记）：
 *   图：Bar / Line / Pie / Radar / Scatter / Heatmap / Graph
 *   组件：Title / Tooltip / Grid / Legend（含 type:'scroll' 的滚动图例）/
 *     DataZoom（slider + inside）/ MarkLine / MarkArea / VisualMap（Dashboard
 *     热力图的连续型）/ Graphic（crCharts / pmCharts 的 option.graphic 元素）/
 *     AxisPointer（axis 触发的 tooltip 指示线）/ Radar（雷达坐标系）
 *   渲染器：Canvas（CnKpi / CnKpi5mins / NativeBoard 显式 opts={{ renderer: 'canvas' }}）
 *
 * 未登记的不要用：Toolbox / Brush / Dataset / Geo / Map / Timeline / Calendar /
 * Polar / Gauge / Funnel / Treemap / Sankey / SVGRenderer 等均不在此列，
 * 用了会静默画不出图（不报错，只空白），加之前先在这里注册。
 *
 * 用法：页面一律 `import ReactECharts from '../components/ECharts'`（包装组件，
 * 内部把本实例传给 echarts-for-react 的 core 版）；需要直接调 echarts API
 * （如 TTWODashboard 的 echarts.connect）时 `import echarts from '../utils/echarts'`。
 *
 * 主题取色规矩不变（AGENTS.md 三.3）：ECharts 里不能用 CSS 变量 WH.xxx，
 * 必须用 theme.ts 里 DARK/LIGHT 的实值。
 */
import * as echarts from 'echarts/core'
import {
  BarChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
} from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  AxisPointerComponent,
  DataZoomComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

export default echarts
