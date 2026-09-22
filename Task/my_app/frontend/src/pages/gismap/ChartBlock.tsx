// 下钻抽屉内的图表容器：统一高度、空数据占位、口径提示。
//
// 注意：当前 echarts 版本下不能传 lazyUpdate，否则图会空白
// （见 MsSlaDashboard.tsx / NurDashboard.tsx 的同款注释）。
import ReactECharts from 'echarts-for-react'
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
        ? <ReactECharts option={option} style={{ height }} notMerge />
        : (
          <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: WH.textMuted }}>{t('gis.chart.noData')}</span>} />
          </div>
        )}
    </Card>
  )
}
