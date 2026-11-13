/**
 * 全站统一的 ECharts React 包装（2026-11-12 首屏瘦身）。
 *
 * `echarts-for-react` 的默认入口内部 `import * as echarts from 'echarts'`，
 * 整包 1.16MB 会跟进每一个用图的页面 chunk；改用它的 core 版
 * `echarts-for-react/lib/core` + `../utils/echarts` 的按需实例，props 与
 * 默认入口完全一致（option / notMerge / opts / onEvents / onChartReady 等
 * 全部透传），各页只改 import 行、JSX 不用动。
 *
 * ref 会透传给 core 实例（Dashboard.tsx 用 ref 存图表实例，与改前一致）。
 *
 * ⚠ 不要改回 `from 'echarts-for-react'`：那会立刻把整包 echarts 拖回来。
 * 新增图/组件时去 `../utils/echarts` 登记，不要在这里另起实例。
 */
import { forwardRef } from 'react'
import EChartsReactCore from 'echarts-for-react/lib/core'
import type { EChartsReactProps } from 'echarts-for-react/lib/types'
import echarts from '../utils/echarts'

export type { EChartsReactProps }

const ReactECharts = forwardRef<EChartsReactCore, Omit<EChartsReactProps, 'echarts'>>(
  (props, ref) => <EChartsReactCore ref={ref} echarts={echarts} {...props} />,
)

export default ReactECharts
