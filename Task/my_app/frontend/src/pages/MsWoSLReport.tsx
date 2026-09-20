/* ============================================================================
 * MS WOs SLA Achievements Daily Report（page=ms_wo_sla）
 *
 * 数据源：data/ms_sla/ZTE OLR MS WOs SLA Achievements Daily Report_<日期>.xlsx
 * —— 任务 kpi_ms_wo_sla（MS WOs SLA 日报邮件）读的**同一份文件**，页面不做二次加工；
 * 解析口径见 backend/services/ms_kpi_report_service.py 顶部 docstring。
 *
 * 页面结构：总览卡片（月工单/达标/达成率/未达标指标）→ 5 个 TTR 指标卡 →
 * 达成率日趋势（含各自目标线）→ 每日明细矩阵（与 Excel 版式一致，点击列头看趋势）。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Spin, Tag, Typography, message } from 'antd'
import { ReloadOutlined, DownloadOutlined, InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { getMsKpiReportSummary } from '../api'
import { useI18n, numLocale } from '../i18n'
import { useTheme, WH, WH_COLORS, LIGHT_COLORS, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import { exportReport, safeFileName, type CellValue } from '../utils/excelReport'
import {
  KpiMatrixTable, MetricCards, MetricTrendModal, StatCard, fmtValue,
  num, type Matrix, type Metric, type MsKpiSummary,
} from './MsKpiShared'

const { Text } = Typography

const WO_SHEET = 'WOs SLA achievement Report'

export default function MsWoSLReport() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const loc = numLocale(locale)

  const [summary, setSummary] = useState<MsKpiSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [pick, setPick] = useState<{ metric: Metric; x: number; y: number } | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    getMsKpiReportSummary('wo_sla')
      .then(res => {
        setSummary(res.data as MsKpiSummary)
        setError('')
      })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setError(String(err?.response?.data?.detail || err?.message || e))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const matrix: Matrix | null = useMemo(
    () => summary?.matrices?.[WO_SHEET] ?? Object.values(summary?.matrices ?? {})[0] ?? null,
    [summary],
  )
  const ov = summary?.overview

  // ---------- 达成率日趋势（每个指标一条线 + 各自目标虚线） ----------
  const trendOption = useMemo(() => {
    if (!matrix) return {}
    const colors = isDark ? WH_COLORS : LIGHT_COLORS
    const days = matrix.rows.map(r => r.label)
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
      legend: {
        top: 0,
        textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 11 },
        itemWidth: 18, itemHeight: 8,
      },
      grid: { left: 56, right: 24, top: 44, bottom: 64 },
      xAxis: {
        type: 'category' as const,
        data: days,
        axisLabel: { ...axisLabel(isDark), rotate: 45 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value' as const,
        scale: true,
        splitLine: splitLine(isDark),
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
      },
      series: matrix.metrics.map((m, i) => {
        const c = colors[i % colors.length]
        return {
          name: m.label,
          type: 'line' as const,
          smooth: true,
          symbolSize: 6,
          connectNulls: false,
          data: matrix.rows.map(r => {
            const v = r.values[m.value_key]
            return v === null || v === undefined ? null : Number((num(v) * 100).toFixed(3))
          }),
          itemStyle: { color: c },
          lineStyle: { width: 2, color: c },
          markLine: m.target === null ? undefined : {
            silent: true,
            symbol: 'none',
            data: [{
              yAxis: Number((num(m.target) * 100).toFixed(3)),
              lineStyle: { color: c, type: 'dashed' as const, width: 1, opacity: 0.55 },
              label: { show: false },
            }],
          },
        }
      }),
    }
  }, [matrix, isDark])

  // ---------- 导出（月行 + 日行，与 Excel 同版式） ----------
  const doExport = useCallback(async () => {
    if (!matrix) return
    setExporting(true)
    try {
      const header: string[] = [matrix.label_header]
      matrix.columns.forEach(c => {
        const parts = [c.category, c.group, c.label].filter(Boolean)
        const dedup: string[] = []
        parts.forEach(p => { if (!dedup.length || dedup[dedup.length - 1] !== p) dedup.push(p) })
        header.push(dedup.join(' / '))
      })
      const toRow = (label: string, values: Record<string, number | null>): CellValue[] =>
        [label, ...matrix.columns.map(c => {
          const v = values[c.key]
          return v === null || v === undefined ? null : num(v)
        })]
      const rows: CellValue[][] = []
      if (Object.keys(matrix.month).length) rows.push(toRow(matrix.month_label, matrix.month))
      matrix.rows.forEach(r => rows.push(toRow(r.label, r.values)))

      const numericCols = matrix.columns.map((_c, i) => i + 1)
      await exportReport([{
        name: matrix.sheet,
        title: summary?.source.kind_label_en || 'MS WOs SLA Achievements Daily Report',
        subtitle: `${t('msKpi.sourceFile')}: ${summary?.source.file || '-'}    |    `
          + `${t('msKpi.rows')}: ${matrix.rows.length}`,
        tabColor: '#2F5496',
        header,
        rows,
        numericCols,
      }], `${safeFileName(summary?.source.kind_label_en || 'MS WOs SLA Achievements Daily Report')}.xlsx`)
    } catch (e: unknown) {
      message.error(String((e as { message?: string })?.message || e))
    } finally {
      setExporting(false)
    }
  }, [matrix, summary, t])

  const cards = useMemo(() => {
    if (!ov || !matrix) return []
    const belowMetrics = matrix.metrics.filter(m => m.met === false)
    return [
      {
        key: 'days',
        label: t('msKpi.card.days'),
        value: (ov.days ?? matrix.rows.length).toLocaleString(loc),
        hint: `${ov.first_day || '-'} ~ ${ov.last_day || '-'}`,
      },
      {
        key: 'total',
        label: t('msKpi.card.woTotal'),
        value: num(ov.month_total).toLocaleString(loc),
        hint: t('msKpi.hint.woTotal'),
      },
      {
        key: 'within',
        label: t('msKpi.card.woWithin'),
        value: num(ov.month_within).toLocaleString(loc),
        hint: t('msKpi.hint.woWithin'),
      },
      {
        key: 'achieve',
        label: t('msKpi.card.woAchieve'),
        value: fmtValue(ov.month_achieve, 'percent', loc),
        hint: `${t('msKpi.target')}: ${fmtValue(matrix.metrics[0]?.target, 'percent', loc)}`,
        color: ov.month_achieve !== null && ov.month_achieve !== undefined
          && matrix.metrics[0]?.target !== null
          && num(ov.month_achieve) >= num(matrix.metrics[0]?.target)
          ? WH.ok : WH.danger,
        emphasis: true,
      },
      {
        key: 'met',
        label: t('msKpi.card.metMetrics'),
        value: `${ov.met_count ?? 0}/${ov.metric_count ?? matrix.metrics.length}`,
        hint: t('msKpi.hint.metMetrics'),
        color: (ov.met_count ?? 0) === (ov.metric_count ?? matrix.metrics.length) ? WH.ok : WH.warn,
      },
      {
        key: 'below',
        label: t('msKpi.card.belowMetrics'),
        value: String(ov.below_count ?? 0),
        hint: belowMetrics.length
          ? belowMetrics.map(m => m.label).join('、')
          : t('msKpi.hint.allMet'),
        color: (ov.below_count ?? 0) > 0 ? WH.danger : WH.ok,
        emphasis: (ov.below_count ?? 0) > 0,
      },
    ]
  }, [ov, matrix, t, loc])

  return (
    <div style={{ padding: 16, background: WH.bg, minHeight: '100%' }}>
      {/* ==================== 总览 ==================== */}
      <Card
        title={t('msKpi.woTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('msKpi.refresh')}
            </Button>
            <Button type="primary" icon={<DownloadOutlined />} onClick={doExport}
              loading={exporting} disabled={!matrix}>
              {t('msKpi.export')}
            </Button>
          </Space>
        )}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="cyan">{`${t('msKpi.sourceFile')}: ${summary?.source.file || '-'}`}</Tag>
          <Tag>{`${t('msKpi.dataTime')}: ${summary?.source.generated_at || '-'}`}</Tag>
          <Tag>{`${t('msKpi.task')}: ${summary?.source.task || '-'}`}</Tag>
          <Tag>{`${t('msKpi.queryTime')}: ${summary?.generated_at || '-'}`}</Tag>
        </Space>

        {error && (
          <Alert type="error" showIcon style={{ marginBottom: 12 }}
            message={t('msKpi.loadFailed')} description={error} />
        )}
        {!!summary?.warnings?.length && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('msKpi.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {summary.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>} />
        )}

        <Spin spinning={loading}>
          <Row gutter={[12, 12]}>
            {cards.map(c => (
              <Col key={c.key} xs={12} sm={8} lg={4}>
                <StatCard label={c.label} value={c.value} hint={c.hint}
                  color={c.color} emphasis={c.emphasis} />
              </Col>
            ))}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 指标卡（月达成） ==================== */}
      <Card
        title={t('msKpi.metricCardsTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={<Text style={{ color: WH.textDim, fontSize: 12 }}>{t('msKpi.metricCardsHint')}</Text>}
      >
        <Spin spinning={loading}>
          {matrix
            ? (
              <MetricCards
                matrix={matrix}
                loc={loc}
                t={t}
                onPick={(m) => setPick({ metric: m, x: window.innerWidth / 2, y: window.innerHeight / 3 })}
              />
            )
            : <Text type="secondary">{t('msKpi.empty')}</Text>}
        </Spin>
      </Card>

      {/* ==================== 达成率日趋势 ==================== */}
      <Card
        title={t('msKpi.trendCardTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={<Text style={{ color: WH.textDim, fontSize: 12 }}>{t('msKpi.trendCardHint')}</Text>}
      >
        <Spin spinning={loading}>
          {matrix && matrix.rows.length
            ? <ReactECharts option={trendOption} style={{ height: 380, width: '100%' }} notMerge />
            : <Text type="secondary">{t('msKpi.empty')}</Text>}
        </Spin>
      </Card>

      {/* ==================== 每日明细矩阵 ==================== */}
      <Card
        title={t('msKpi.matrixTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder }}
        extra={(
          <Space wrap>
            {matrix?.metrics.map(m => (
              <Tag key={m.key} color={m.met === true ? 'green' : m.met === false ? 'red' : 'default'}>
                {`${m.label} ${fmtValue(m.month_value, m.format, loc)}`}
              </Tag>
            ))}
          </Space>
        )}
      >
        <Spin spinning={loading}>
          {matrix
            ? (
              <>
                <Space wrap style={{ marginBottom: 10 }}>
                  <Tag color="cyan">{`${t('msKpi.target')}: ${matrix.metrics
                    .map(m => `${m.label} ${fmtValue(m.target, m.format, loc)}`).join(' | ')}`}</Tag>
                  <Tag>{`${t('msKpi.rows')}: ${matrix.rows.length}`}</Tag>
                  <Tag>{`${t('msKpi.columns')}: ${matrix.columns.length}`}</Tag>
                  {matrix.metrics.some(m => m.met === false) && (
                    <Tag color="red" icon={<WarningOutlined />}>
                      {`${t('msKpi.below')}: ${matrix.metrics.filter(m => m.met === false)
                        .map(m => m.label).join('、')}`}
                    </Tag>
                  )}
                </Space>
                <KpiMatrixTable
                  matrix={matrix}
                  loc={loc}
                  t={t}
                  onPickMetric={(m, anchor) => setPick({
                    metric: m,
                    x: anchor?.x ?? window.innerWidth / 2,
                    y: anchor?.y ?? window.innerHeight / 3,
                  })}
                />
                <div style={{ marginTop: 8, color: WH.textDim, fontSize: 11 }}>
                  {t('msKpi.matrixHint')}
                </div>
              </>
            )
            : <Text type="secondary">{t('msKpi.empty')}</Text>}
        </Spin>

        {/* 报表口径（原样透传标题 + 达标判定说明） */}
        <div style={{ marginTop: 16, color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
          <div style={{ marginBottom: 4, color: WH.text }}>
            <InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />
            {t('msKpi.docTitle')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {summary?.notes?.map((n, i) => <li key={i}>{n}</li>)}
            <li>{t('msKpi.doc.metRule')}</li>
            <li>{t('msKpi.doc.woScope')}</li>
          </ul>
        </div>
      </Card>

      {/* ==================== 指标趋势 ==================== */}
      <MetricTrendModal
        open={!!pick}
        metric={pick?.metric ?? null}
        matrix={matrix}
        anchor={pick ? { x: pick.x, y: pick.y } : null}
        onClose={() => setPick(null)}
        t={t}
      />
    </div>
  )
}
