/* ============================================================================
 * CR 变更分析 —— 按 change_category 看变更计划的排期与执行情况
 * ============================================================================
 *
 * 数据源：`eflow_cr`（eFlow 同步的动态建表）。
 * 后端：`backend/routers/cr_analysis.py`，
 *       口径与「概览/下钻如何共用一份 WHERE」见
 *       `backend/services/cr_analysis_service.py` 的模块 docstring。
 *
 * 本文件（`pages/CrChangeAnalysis.tsx`）只负责**页面编排与取数**；配套模块在
 * `pages/crAnalysis/` 下，各管一摊：
 *   - `crTypes.ts`   —— 类型、常量、纯格式化与小计
 *   - `crCharts.ts`  —— ECharts option 构造（纯函数）
 *   - `CrDrillModal.tsx` —— 明细弹窗（表格 + 导出）
 * （拆分原因：单文件曾达 897 行，超出 AGENTS.md 第三节 2 的 500 行上限。）
 *
 * 页面结构：① 筛选条 → ② KPI 行 → ③ 三个比率卡 → ④ 图表
 *          → ⑤ 月度趋势 → ⑥ 类别明细表 → ⑦ 子类别表 → ⑧ 下钻弹窗
 *
 * ⚠️ 硬要求（AGENTS.md 第三节 1b）：「能下钻尽下钻」—— 页面上**每个数字都可点**，
 *    且下钻时 metric + category/sub_category/month 的组合必须与点击来源的卡片
 *    维度严格一致，否则明细行数与卡片数字对不上。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { WH, useTheme } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import { exportAoaReport } from '../utils/excelReport'
import { getCrAnalysisFilters, getCrAnalysisOverview, getCrAnalysisDrilldown } from '../api'
import CrDrillModal from './crAnalysis/CrDrillModal'
import {
  fmtRate, rateColor, rateLevel, summarize, COUNT_FIELDS,
  type DetailRow, type Filters, type Metric, type Overview,
} from './crAnalysis/crTypes'
import { categoryColumns, subCategoryColumns } from './crAnalysis/crColumns'
import {
  chartColors, planChartOption, onTimeChartOption, statusChartOption, monthChartOption,
} from './crAnalysis/crCharts'

const { Text } = Typography

export default function CrChangeAnalysis() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 筛选条件 ---- */
  const [start, setStart] = useState<Dayjs | null>(null)
  const [end, setEnd] = useState<Dayjs | null>(null)

  /* ---- 数据与状态：loading / error / data 三件套是页面标配 ---- */
  const [ov, setOv] = useState<Overview | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /* ---- 筛选条上的类别前端过滤（只影响展示，不影响下钻口径） ---- */
  const [activeCats, setActiveCats] = useState<string[]>([])

  /* ---- 下钻弹窗状态 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillTitle, setDrillTitle] = useState('')
  const [drillRows, setDrillRows] = useState<DetailRow[]>([])
  const [drillTotal, setDrillTotal] = useState(0)
  const [drillTruncated, setDrillTruncated] = useState(false)
  const [drillWarn, setDrillWarn] = useState('')
  const [drillLoading, setDrillLoading] = useState(false)
  const [lastMetric, setLastMetric] = useState('')

  /* ---- 取数 ---- */
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {}
      if (start) params.start = start.format('YYYY-MM-DD')
      if (end) params.end = end.format('YYYY-MM-DD')
      const r = await getCrAnalysisOverview(params)
      setOv(r.data as Overview)
    } catch (e: any) {
      setError(e?.message || String(e))
      setOv(null)
    } finally {
      setLoading(false)
    }
  }, [start, end])

  /* 首次进页面：先拉筛选项拿到**全表实际时间范围**，再据此初始化窗口 ——
     顺序不能反，否则会先用「今天往前 N 天」查一次再被覆盖，白跑一次库。
     （实测全表仅 247 行、跨度约 8 个月，默认 30 天窗口会几乎空白。） */
  useEffect(() => {
    let alive = true
    getCrAnalysisFilters()
      .then(r => {
        if (!alive) return
        const f = r.data as Filters
        setFilters(f)
        if (f?.error) setError(f.error)
        setStart(f?.default_start ? dayjs(f.default_start) : dayjs().subtract(240, 'day'))
        setEnd(f?.default_end ? dayjs(f.default_end) : dayjs())
      })
      .catch(() => {
        if (!alive) return
        setStart(dayjs().subtract(240, 'day'))
        setEnd(dayjs())
      })
    return () => { alive = false }
  }, [])

  useEffect(() => { void load() }, [load])

  const rows = useMemo(() => {
    const all = ov?.rows || []
    if (!activeCats.length) return all
    return all.filter(r => activeCats.includes(r.category))
  }, [ov, activeCats])

  const summary = useMemo(() => summarize(rows), [rows])
  const C = useMemo(() => chartColors(isDark), [isDark])

  /* ---- 图表 option（纯函数在 crCharts.ts 里）---- */
  const planOption = useMemo(() => planChartOption(rows, isDark, C, {
    executed: t('cr.legend.executed'), unexecuted: t('cr.legend.unexecuted'),
    total: t('cr.col.total'), rate: t('cr.kpi.completionRate'),
  }), [rows, isDark, C, t])

  const onTimeOption = useMemo(() => onTimeChartOption(
    summary.on_time, summary.delayed, summary.on_time_rate, isDark, C,
    rateColor(summary.on_time_rate),
    { onTime: t('cr.legend.onTime'), delayed: t('cr.legend.delayed') },
  ), [summary, isDark, C, t])

  const statusOption = useMemo(
    () => statusChartOption(ov?.status_rows || [], isDark, C),
    [ov, isDark, C],
  )

  const monthOption = useMemo(() => monthChartOption(ov?.months || [], isDark, C, {
    total: t('cr.col.total'), executed: t('cr.col.executed'), closed: t('cr.col.closed'),
  }), [ov, isDark, C, t])

  /* ---- 下钻 ---- */
  const openDrill = useCallback(async (
    metric: Metric, category = '', sub = '', month = '',
    at?: { x: number; y: number },
  ) => {
    setOpen(true)
    setAnchor(at || null)
    setDrillLoading(true)
    setDrillRows([])
    setDrillTotal(0)
    setDrillTruncated(false)
    setDrillWarn('')
    setLastMetric(metric)

    // 标题把下钻维度写清楚，用户才知道这一屏到底是什么
    const parts = [t(`cr.metric.${metric}`)]
    if (category) parts.push(category)
    if (sub) parts.push(sub)
    if (month) parts.push(month)
    setDrillTitle(parts.join(' · '))

    try {
      const params: any = { metric }
      if (start) params.start = start.format('YYYY-MM-DD')
      if (end) params.end = end.format('YYYY-MM-DD')
      if (category) params.category = category
      if (sub) params.sub_category = sub
      if (month) params.month = month
      const r = await getCrAnalysisDrilldown(params)
      const d = r.data || {}
      setDrillRows(d.rows || [])
      setDrillTotal(d.total ?? (d.rows || []).length)
      setDrillTruncated(!!d.truncated)
      setDrillWarn((d.meta?.warnings || []).join('; '))
    } catch (e: any) {
      setDrillWarn(e?.message || String(e))
    } finally {
      setDrillLoading(false)
    }
  }, [start, end, t])

  /** 图表点击的公共处理：把坐标从 ECharts 事件里取出并下钻 */
  const chartDrill = useCallback((
    metric: Metric, category: string, month: string, p: any,
  ) => {
    void openDrill(metric, category, '', month, {
      x: p?.event?.event?.clientX, y: p?.event?.event?.clientY,
    })
  }, [openDrill])

  /** 导出类别汇总（表格那一屏） */
  const exportSummary = useCallback(() => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `CR_category_summary_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'CR类别汇总',
      title: t('cr.table.title'),
      header: [
        t('cr.col.category'), t('cr.col.total'), t('cr.col.planned'), t('cr.col.executed'),
        t('cr.col.unexecuted'), t('cr.col.onTime'), t('cr.col.delayed'), t('cr.col.closed'),
        t('cr.col.open'), t('cr.kpi.completionRate'), t('cr.kpi.onTimeRate'), t('cr.kpi.closureRate'),
      ],
      rows: rows.map(r => [
        r.category, r.total, r.planned, r.executed, r.unexecuted, r.on_time,
        r.delayed, r.closed, r.open,
        fmtRate(r.completion_rate), fmtRate(r.on_time_rate), fmtRate(r.closure_rate),
      ]),
      numericCols: [1, 2, 3, 4, 5, 6, 7, 8],
    })
  }, [rows, t])

  /* ---- 表格列（定义在 crColumns.tsx，每个数字都可点下钻）---- */
  const columns = useMemo(() => categoryColumns(t, openDrill, C), [t, openDrill, C])
  const subColumns = useMemo(() => subCategoryColumns(t, openDrill, C), [t, openDrill, C])

  const warningText = (ov?.meta?.warnings || []).join('; ')

  /** KPI 卡定义集中一处：键、取值、配色、下钻 metric 一眼对齐，避免 8 张卡手抄 8 遍 */
  const kpis = useMemo(() => ([
    { key: 'cr.col.total', value: summary.total, color: C.total, metric: 'total' as Metric },
    { key: 'cr.col.planned', value: summary.planned, color: C.planned, metric: 'planned' as Metric },
    { key: 'cr.col.executed', value: summary.executed, color: C.executed, metric: 'executed' as Metric },
    { key: 'cr.col.unexecuted', value: summary.unexecuted, color: C.unexecuted, metric: 'unexecuted' as Metric },
    { key: 'cr.col.onTime', value: summary.on_time, color: C.onTime, metric: 'on_time' as Metric },
    { key: 'cr.col.delayed', value: summary.delayed, color: C.delayed, metric: 'delayed' as Metric },
    { key: 'cr.col.closed', value: summary.closed, color: C.closed, metric: 'closed' as Metric },
    { key: 'cr.col.open', value: summary.open, color: C.open, metric: 'open' as Metric },
  ]), [summary, C])

  /** 三个比率卡：每个都写明分母（分母为 0 时显示 '—'，不是 0） */
  const rateCards = useMemo(() => ([
    {
      key: 'cr.kpi.completionRate', rate: summary.completion_rate,
      hint: t('cr.kpi.completionRateHint', { executed: summary.executed, planned: summary.planned }),
      metric: 'executed' as Metric,
    },
    {
      key: 'cr.kpi.onTimeRate', rate: summary.on_time_rate,
      hint: t('cr.kpi.onTimeRateHint', { onTime: summary.on_time, executed: summary.executed }),
      metric: 'on_time' as Metric,
    },
    {
      key: 'cr.kpi.closureRate', rate: summary.closure_rate,
      hint: t('cr.kpi.closureRateHint', { closed: summary.closed, total: summary.total }),
      metric: 'closed' as Metric,
    },
  ]), [summary, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Text type="secondary">{t('cr.filter.range')}</Text>
          <DatePicker value={start} onChange={setStart} allowClear={false} />
          <span>{t('cr.filter.to')}</span>
          <DatePicker value={end} onChange={setEnd} allowClear={false} />
          {filters?.min_time && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('cr.filter.dataRange', { min: filters.min_time, max: filters.max_time, n: filters.row_count })}
            </Text>
          )}
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            {t('cr.filter.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportSummary} disabled={!rows.length}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {error && <Alert type="error" showIcon message={error} />}
      {warningText && <Alert type="warning" showIcon message={warningText} />}
      {!loading && !error && summary.total === 0 && (
        <Alert type="info" showIcon message={t('cr.empty')} />
      )}

      {/* ② KPI 行：每个数字可点下钻 */}
      <Row gutter={[12, 12]}>
        {kpis.map((k, i) => (
          <Col key={k.metric} xs={12} sm={8} lg={6} xl={3}>
            <StatCard
              title={t(k.key)} value={k.value} accentColor={k.color}
              subText={i === 0 ? t('cr.kpi.categories', { n: summary.categories }) : undefined}
              onClick={e => void openDrill(k.metric, '', '', '', { x: e.clientX, y: e.clientY })}
            />
          </Col>
        ))}
      </Row>

      {/* ③ 三个核心比率：分母写在数字下方，避免「100%」在小样本下被误读 */}
      <Row gutter={[12, 12]}>
        {rateCards.map(c => (
          <Col key={c.key} xs={24} md={8}>
            <CardBase
              level={rateLevel(c.rate)}
              interactive
              onClick={e => void openDrill(c.metric, '', '', '', { x: e.clientX, y: e.clientY })}
            >
              <div style={{ fontSize: 13, color: WH.textMuted }}>{t(c.key)}</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: rateColor(c.rate), margin: '4px 0' }}>
                {fmtRate(c.rate)}
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>{c.hint}</Text>
            </CardBase>
          </Col>
        ))}
      </Row>

      {/* ④ 图表并排 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={14}>
          <CardBase
            title={t('cr.chart.plan.title')}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('cr.chart.plan.hint')}</Text>}
          >
            {rows.length
              ? <ReactECharts
                option={planOption}
                style={{ height: 340 }}
                notMerge
                onEvents={{
                  // category 由 dataIndex 反查，保证与柱子严格对应（不靠系列名猜）
                  click: (p: any) => {
                    const cat = rows[p?.dataIndex ?? -1]?.category
                    if (!cat) return
                    const metric: Metric = p?.seriesName === t('cr.legend.unexecuted') ? 'unexecuted' : 'executed'
                    chartDrill(metric, cat, '', p)
                  },
                }}
              />
              : <Empty description={t('cr.empty')} />}
          </CardBase>
        </Col>
        <Col xs={24} sm={12} xl={5}>
          <CardBase title={t('cr.chart.onTime.title')}>
            {summary.executed
              ? <ReactECharts option={onTimeOption} style={{ height: 340 }} notMerge
                onEvents={{
                  click: (p: any) => chartDrill(
                    p?.name === t('cr.legend.onTime') ? 'on_time' : 'delayed', '', '', p),
                }} />
              : <Empty description={t('cr.chart.onTime.noData')} />}
          </CardBase>
        </Col>
        <Col xs={24} sm={12} xl={5}>
          <CardBase
            title={t('cr.chart.status.title')}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('cr.chart.status.hint')}</Text>}
          >
            {ov?.status_rows?.length
              ? <ReactECharts option={statusOption} style={{ height: 340 }} notMerge />
              : <Empty description={t('cr.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑤ 月度趋势 */}
      <CardBase
        title={t('cr.chart.month.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('cr.chart.month.hint')}</Text>}
      >
        {ov?.months?.length
          ? <ReactECharts
            option={monthOption}
            style={{ height: 280 }}
            notMerge
            onEvents={{
              click: (p: any) => {
                const m = ov.months[p?.dataIndex ?? -1]?.month
                if (m) chartDrill('total', '', m, p)
              },
            }}
          />
          : <Empty description={t('cr.empty')} />}
      </CardBase>

      {/* ⑥ 类别明细表：全部数字可点 */}
      <CardBase
        title={t('cr.table.title')}
        extra={
          <Space size="small" wrap>
            {/* 类别前端过滤：快速聚焦某几个专业域 */}
            {(filters?.categories || []).map(c => (
              <Tag.CheckableTag
                key={c}
                checked={activeCats.includes(c)}
                onChange={checked => setActiveCats(prev => (
                  checked ? [...prev, c] : prev.filter(x => x !== c)
                ))}
              >
                {c}
              </Tag.CheckableTag>
            ))}
            {activeCats.length > 0 && (
              <Button type="link" size="small" onClick={() => setActiveCats([])}>
                {t('cr.filter.clear')}
              </Button>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>{t('cr.table.hint')}</Text>
          </Space>
        }
      >
        <Table
          rowKey="category"
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 1280 }}
          pagination={false}
          // 小计行：让「表格内的数字加起来 == 上面 KPI」一眼可见
          summary={() => (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ fontWeight: 700 }}>
                <Table.Summary.Cell index={0}>{t('cr.table.subtotal')}</Table.Summary.Cell>
                {COUNT_FIELDS.map((f, i) => (
                  <Table.Summary.Cell key={f} index={i + 1} align="right">{summary[f]}</Table.Summary.Cell>
                ))}
                <Table.Summary.Cell index={10} align="right">{fmtRate(summary.completion_rate)}</Table.Summary.Cell>
                <Table.Summary.Cell index={11} align="right">{fmtRate(summary.on_time_rate)}</Table.Summary.Cell>
                <Table.Summary.Cell index={12} align="right">{fmtRate(summary.closure_rate)}</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      </CardBase>

      {/* ⑦ 子类别（设备类型）第二层维度 */}
      <CardBase
        title={t('cr.sub.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('cr.sub.hint')}</Text>}
      >
        <Table
          rowKey={r => `${r.category}||${r.sub_category}`}
          columns={subColumns}
          dataSource={ov?.sub_categories || []}
          loading={loading}
          size="small"
          scroll={{ x: 640 }}
          pagination={{ pageSize: 12, showSizeChanger: true, pageSizeOptions: ['12', '25', '50'] }}
        />
      </CardBase>

      {/* ⑧ 下钻弹窗 */}
      <CrDrillModal
        open={open}
        subtitle={drillTitle}
        anchor={anchor}
        onClose={() => setOpen(false)}
        rows={drillRows}
        total={drillTotal}
        truncated={drillTruncated}
        warn={drillWarn}
        loading={drillLoading}
        metric={lastMetric}
      />
    </div>
  )
}
