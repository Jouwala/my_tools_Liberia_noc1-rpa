// 分制式站点级 KPI 页签（2G / 3G / 4G）。
//
// 数据源：后端 ms_sla_*_SITE 站点级日表（约 96 天）。
// 关联口径：4G 走 site_id 命中；2G/3G 的 ID 属另一套编号，后端回退站点名匹配。
import { useMemo, useState } from 'react'
import { Card, Col, Empty, Row, Select, Table, Tag, Tooltip } from 'antd'
import { WH, cardStyle, useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import { ChartBlock } from './ChartBlock'
import { buildRatKpiOption, fmtRate } from './chartOptions'
import type { RatKpiSeries } from './types'

interface RatKpiTabProps {
  series?: RatKpiSeries
  rat: string
}

/** 比率类默认优先展示（通常业务最关心），最多预选 3 条避免图太乱 */
const pickDefault = (series?: RatKpiSeries): string[] => {
  const metrics = series?.metrics || []
  if (!metrics.length) return []
  const rates = metrics.filter(m => m.is_rate).map(m => m.key)
  const rest = metrics.filter(m => !m.is_rate).map(m => m.key)
  return [...rates, ...rest].slice(0, 3)
}

export function RatKpiTab({ series, rat }: RatKpiTabProps) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [selected, setSelected] = useState<string[]>(() => pickDefault(series))

  const metrics = series?.metrics || []
  const daily = series?.daily || []

  // series 变化（切换站点）时同步刷新预选指标
  const defaultKeys = useMemo(() => pickDefault(series), [series])
  const effective = selected.length && selected.every(k => metrics.some(m => m.key === k))
    ? selected
    : defaultKeys

  const option = useMemo(() => {
    if (!daily.length || !effective.length) return null
    return buildRatKpiOption(series as RatKpiSeries, effective, { isDark, t })
  }, [series, daily.length, effective, isDark, t])

  if (!series || !metrics.length || !daily.length) {
    return (
      <Card size="small" style={cardStyle}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span style={{ color: WH.textMuted }}>{series?.error || t('gis.kpi.noData')}</span>}
        />
      </Card>
    )
  }

  const selectedMetrics = metrics.filter(m => effective.includes(m.key))
  // 表格列：日期 + 已选指标
  const columns = [
    { title: t('gis.drilldown.colDay'), dataIndex: 'day', key: 'day', width: 100, fixed: 'left' as const },
    ...selectedMetrics.map(m => ({
      title: (
        <Tooltip title={m.label}>
          <span style={{ fontSize: 11 }}>{m.label.length > 26 ? `${m.label.slice(0, 26)}…` : m.label}</span>
        </Tooltip>
      ),
      dataIndex: m.key,
      key: m.key,
      width: 130,
      align: 'right' as const,
      render: (v: number | null) => (v == null
        ? <span style={{ color: WH.textMuted }}>-</span>
        : (m.is_rate ? fmtRate(v) : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))),
    })),
  ]

  const matchedTip = series.matched_by === 'site_id'
    ? t('gis.chart.matchedBySiteId')
    : series.matched_by === 'site_name' ? t('gis.chart.matchedByName') : ''

  return (
    <div>
      <Card size="small" style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}>
        <Row gutter={[12, 8]} align="middle">
          <Col>
            <Tag color="blue">{rat}</Tag>
          </Col>
          <Col flex="auto">
            <span style={{ color: WH.textMuted, fontSize: 12 }}>
              {t('gis.kpi.site')}: <span style={{ color: WH.text }}>{series.site_name || '-'}</span>
              {matchedTip && <Tag style={{ marginLeft: 6 }}>{matchedTip}</Tag>}
              <span style={{ marginLeft: 10 }}>
                {t('gis.kpi.days')}: <span style={{ color: WH.text }}>{series.days}</span>
              </span>
            </span>
          </Col>
          <Col>
            <Select
              mode="multiple"
              size="small"
              style={{ minWidth: 260, maxWidth: 420 }}
              value={effective}
              onChange={setSelected}
              maxTagCount="responsive"
              placeholder={t('gis.kpi.selectMetrics')}
              options={metrics.map(m => ({ label: m.label, value: m.key }))}
            />
          </Col>
        </Row>
      </Card>

      <ChartBlock title={`${rat} — ${t('gis.chart.kpiSeries')}`} option={option} height={280} />

      <Card
        size="small"
        style={cardStyle}
        title={<span style={{ color: WH.text, fontSize: 13 }}>{t('gis.kpi.dailyDetail')}</span>}
      >
        <Table
          size="small"
          rowKey="day"
          dataSource={[...daily].reverse()}
          columns={columns}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 'max-content' }}
        />
      </Card>
    </div>
  )
}
