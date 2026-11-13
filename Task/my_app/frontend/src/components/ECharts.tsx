/**
 * 全站统一的 ECharts React 包装（2026-11-12 首屏瘦身）。
 *
 * `echarts-for-react` 的默认入口内部 `import * as echarts from 'echarts'`，
 * 整包 1.16MB 会跟进每一个用图的页面 chunk；改用它的 core 版
 * `echarts-for-react/esm/core`（必须是 esm/，原因见下方 import 处注释）
 * + `../utils/echarts` 的按需实例，props 与
 * 默认入口完全一致（option / notMerge / opts / onEvents / onChartReady 等
 * 全部透传），各页只改 import 行、JSX 不用动。
 *
 * ref 会透传给 core 实例（Dashboard.tsx 用 ref 存图表实例，与改前一致）。
 *
 * ⚠ 不要改回 `from 'echarts-for-react'`：那会立刻把整包 echarts 拖回来。
 * 新增图/组件时去 `../utils/echarts` 登记，不要在这里另起实例。
 */
import { forwardRef } from 'react'
/* ⚠️ 必须走包的 **ESM** 目录 `esm/core`，不要用 `lib/core`（2026-11-13 实测修复）。
 *
 * 原因：`echarts-for-react` 的 `lib/` 是 tsc 产出的 CJS，文件头带
 * `Object.defineProperty(exports, "__esModule", { value: true })`。
 * Vite 8（rolldown）的 CJS→ESM 互操作对这种「自带 __esModule 的 CJS」会把
 * 整个 exports 对象当作 `default` 导出，于是
 *   `import Core from 'echarts-for-react/lib/core'` 拿到的是
 *   `{ __esModule: true, default: Core }` 这个**对象**，而不是组件本身。
 * 把它当 JSX 用 → React 抛
 *   "Element type is invalid ... but got: object. Check the render method of
 *    `ForwardRef(_c)`."（生产是 minified error #130）
 * 后果是**所有会渲染图表的页面整页白屏**（2026-11-13 用户报障：BP Cells Report
 * 等 23 个页面全空，后端数据接口 200 正常）。`esm/` 是原生 ESM
 * （文件尾 `export default EChartsReactCore`），不经 CJS 互操作，dev 与 build
 * 都直接拿到组件；类型声明 `esm/core.d.ts` 与 `lib/core.d.ts` 同名同形。
 *
 * 验证方式：dev 下 `typeof (await import('/myapp/src/components/ECharts.tsx')).default`
 * 必须是 `object` 且 `$$typeof` 为 `Symbol(react.forward_ref)`；若拿到的是
 * `{ default: ... }`（无 $$typeof）说明又退回 CJS 入口了。 */
import EChartsReactCore from 'echarts-for-react/esm/core'
import type { EChartsReactProps } from 'echarts-for-react/lib/types'
import echarts from '../utils/echarts'

export type { EChartsReactProps }

const ReactECharts = forwardRef<EChartsReactCore, Omit<EChartsReactProps, 'echarts'>>(
  (props, ref) => <EChartsReactCore ref={ref} echarts={echarts} {...props} />,
)

export default ReactECharts
