// 下钻抽屉内的图表容器：统一高度、空数据占位、口径提示。
//
// 注意：当前 echarts 版本下不能传 lazyUpdate，否则图会空白
// （见 MsSlaDashboard.tsx / NurDashboard.tsx 的同款注释）。
//
// ⚠ 2026-10-29 首屏提速：echarts 改为 **动态 import**，不要再改回静态 import。
//   原本 `import ReactECharts from 'echarts-for-react'` 是静态的，于是 echarts
//   被打进 GISMap chunk 的依赖闭包 —— 进 ?page=realtime_alarm（甚至不画任何图的
//   地图首屏）也要先下载 echarts chunk（裸 1.16MB / gzip 387KB，占首屏传输的 21%），
//   实测 FCP 被它拖到 1.9s。本组件只在两个地方用到，且都是**点了才出现**的内容：
//     · SiteDrilldownDrawer（站点下钻抽屉）
//     · RatKpiTab（RAT KPI 页签）
//   改成 lazy 后，echarts 只在真正要画图时才加载，地图首屏不再等它。
import { lazy, Suspense } from 'react'
import { Card, Empty, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { WH, cardStyle } from '../../theme'
import { useI18n } from '../../i18n'

interface ChartBlockProps {
  title: string
  /** null 表示无数据 */
  option: Record<string, any> | null
  height?: number
  /** 是否展示「口径为全量、非采样」提示 */
  fullScope?: boolean
  extra?: React.ReactNode
}

/* echarts 只在「真的要画图」时被拉取（见文件头注释）。
   包了 Suspense + 等高占位块：加载中不会把下方内容顶动。 */
const ReactECharts = lazy(() => import('echarts-for-react'))

export function ChartBlock({ title, option, height = 240, fullScope, extra }: ChartBlockProps) {
  const { t } = useI18n()
  const hasOption = option != null
  return (
    <Card
      size="small"
      style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}
      title={
        <span style={{ color: WH.text, fontSize: 13 }}>
          {title}
          {fullScope && (
            <Tooltip title={t('gis.chart.fullScopeTip')}>
              <InfoCircleOutlined style={{ marginLeft: 6, color: WH.textMuted, fontSize: 12 }} />
            </Tooltip>
          )}
        </span>
      }
      extra={extra}
    >
      {hasOption
        ? (
          <Suspense fallback={<div style={{ height }} />}>
            <ReactECharts option={option} style={{ height }} notMerge />
          </Suspense>
        )
        : (
          <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: WH.textMuted }}>{t('gis.chart.noData')}</span>} />
          </div>
        )}
    </Card>
  )
}
