// 分制式站点级 KPI 页签（2G / 3G / 4G）。
//
// 数据源：后端 ms_sla_*_SITE 站点级日表（约 96 天）。
// 关联口径：4G 走 site_id 命中；2G/3G 的 ID 属另一套编号，后端回退站点名匹配。
//
// 拆成两张图：**网络质量**（比率，共用一根 % 轴）与**业务量**（Erl / GB / Mbps / users，
// 按量纲各一根轴）。合在一张图里时 67 GB 与 285 Erl 挤同一根轴，小量纲的曲线直接贴地；
// 而且业务量过去只躺在「选择指标」下拉里，不主动点就永远看不到 —— 现在默认就画出来。
import { useMemo, useState } from 'react'
import { Card, Col, Empty, Row, Select, Table, Tag } from 'antd'
import { WH, cardStyle, useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import { ExplainIcon, ExplainPopover } from '../../components/MetricExplain'
import { ChartBlock } from './ChartBlock'
import { buildRatKpiOption, buildVolumeOption, fmtRate, isPct, volumeSeriesName } from './chartOptions'
import type { RatKpiMetric, RatKpiSeries } from './types'

interface RatKpiTabProps {
  series?: RatKpiSeries
  rat: string
}

/** 后端还没下发 group 时（未重启到带量纲的版本）一律归到网络质量，与改造前行为一致 */
const groupOf = (m: RatKpiMetric): 'quality' | 'volume' => (m.group === 'volume' ? 'volume' : 'quality')

/** 质量图默认预选：关键比率（is_rate）优先，最多 3 条避免图太乱 */
const pickQuality = (metrics: RatKpiMetric[]): string[] => {
  const quality = metrics.filter(m => groupOf(m) === 'quality')
  const head = quality.filter(m => m.is_rate).map(m => m.key)
  const rest = quality.filter(m => !m.is_rate).map(m => m.key)
  return [...head, ...rest].slice(0, 3)
}

/** 业务量图默认预选：后端把最想先看的列排在 volume 组前面，取前 3 条 */
const pickVolume = (metrics: RatKpiMetric[]): string[] =>
  metrics.filter(m => groupOf(m) === 'volume').slice(0, 3).map(m => m.key)

/** 选中的键在当前制式里仍然存在才沿用，否则（换站点 / 还没选）回落到默认预选 */
const withFallback = (keys: string[], pool: RatKpiMetric[], fallback: string[]): string[] =>
  (keys.length && keys.every(k => pool.some(m => m.key === k)) ? keys : fallback)

export function RatKpiTab({ series, rat }: RatKpiTabProps) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const metrics = series?.metrics || []
  const daily = series?.daily || []
  const quality = useMemo(() => metrics.filter(m => groupOf(m) === 'quality'), [metrics])
  const volume = useMemo(() => metrics.filter(m => groupOf(m) === 'volume'), [metrics])

  // series 变化（切换站点）时预选自动回落，不需要手动同步 state
  const defaultQuality = useMemo(() => pickQuality(metrics), [metrics])
  const defaultVolume = useMemo(() => pickVolume(metrics), [metrics])
  const [pickedQuality, setPickedQuality] = useState<string[]>([])
  const [pickedVolume, setPickedVolume] = useState<string[]>([])
  const selQuality = withFallback(pickedQuality, quality, defaultQuality)
  const selVolume = withFallback(pickedVolume, volume, defaultVolume)

  const qualityOption = useMemo(
    () => (daily.length && selQuality.length
      ? buildRatKpiOption(series as RatKpiSeries, selQuality, { isDark, t }) : null),
    [series, selQuality, daily.length, isDark, t],
  )
  const volumeOption = useMemo(
    () => (daily.length && selVolume.length
      ? buildVolumeOption(series as RatKpiSeries, selVolume, { isDark, t }) : null),
    [series, selVolume, daily.length, isDark, t],
  )

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

  const aggText = (m: RatKpiMetric) =>
    (groupOf(m) === 'volume' ? t('gis.kpi.aggVolume') : t('gis.kpi.aggQuality'))

  // 日明细表：两张图各自选中的列并排展示，质量在前
  const tableMetrics = [
    ...quality.filter(m => selQuality.includes(m.key)),
    ...volume.filter(m => selVolume.includes(m.key)),
  ]
  const columns = [
    { title: t('gis.drilldown.colDay'), dataIndex: 'day', key: 'day', width: 100, fixed: 'left' as const },
    ...tableMetrics.map(m => ({
      title: (
        <span style={{ fontSize: 11 }}>
          {m.label.length > 26 ? `${m.label.slice(0, 26)}…` : m.label}
          <ExplainIcon
            size="0.7rem"
            text={t('gis.kpi.explainCol', { label: m.label, unit: m.unit || '-', agg: aggText(m) })}
          />
        </span>
      ),
      dataIndex: m.key,
      key: m.key,
      width: 150,
      align: 'right' as const,
      // 数字本身悬浮出「哪一列 / 什么量纲 / 怎么折叠到站点」，口径一律取接口既有字段
      render: (v: number | null, row: Record<string, any>) => (
        <ExplainPopover
          text={t('gis.kpi.explainCell', {
            day: String(row.day ?? '-'), label: m.label, unit: m.unit || '-', agg: aggText(m),
          })}
        >
          <span>
            {v == null
              ? <span style={{ color: WH.textMuted }}>-</span>
              : (isPct(m)
                ? fmtRate(v)
                : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))}
          </span>
        </ExplainPopover>
      ),
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
              value={selQuality}
              onChange={setPickedQuality}
              maxTagCount="responsive"
              placeholder={t('gis.kpi.selectMetrics')}
              options={quality.map(m => ({ label: m.label, value: m.key }))}
            />
          </Col>
        </Row>
      </Card>

      <ChartBlock
        title={`${rat} — ${t('gis.chart.kpiSeries')}`}
        option={qualityOption}
        height={280}
        explain={t('gis.kpi.explainQuality')}
      />

      {/* 业务量单独一张：量纲从 Erl 到 GB 到 users 跨三个数量级，与比率同轴会互相压平。
          该制式日表里没有业务量列时（旧后端未下发 group）整块不渲染，不留空图框。 */}
      {volume.length > 0 && (
        <ChartBlock
          title={`${rat} — ${t('gis.kpi.volumeChart')}`}
          option={volumeOption}
          height={280}
          explain={t('gis.kpi.explainVolume')}
          extra={(
            <Select
              mode="multiple"
              size="small"
              style={{ minWidth: 200, maxWidth: 340 }}
              value={selVolume}
              onChange={setPickedVolume}
              maxTagCount="responsive"
              placeholder={t('gis.kpi.selectVolume')}
              options={volume.map(m => ({ label: volumeSeriesName(m), value: m.key }))}
            />
          )}
        />
      )}

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
