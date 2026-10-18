/* ============================================================================
 * CR 变更分析 —— 按 change_category 看变更计划的排期与执行情况
 * ============================================================================
 *
 * 数据源：`eflow_cr`（eFlow 同步的动态建表）。后端 `backend/routers/cr_analysis.py`，
 * 口径与「概览/下钻如何共用一份 WHERE」见 `cr_analysis_service.py` 的模块 docstring。
 *
 * 本文件只负责**页面编排与取数**；配套模块在 `pages/crAnalysis/` 下各管一摊：
 * `crTypes` 类型与格式、`crCharts` ECharts 纯函数、`crColumns` 表格列、
 * `CrWorkflowMilestones` 里程碑条、`CrWorkflowPanel` 流程面板、
 * `CrDrillModal` / `CrWorkflowDrillModal` 两套明细弹窗、`useCrDrills` 两套下钻 hook。
 * （拆分原因：单文件曾达 897 行，超出 AGENTS.md 第三节 2 的 500 行上限。）
 *
 * 页面结构：① 筛选条 → ② Workflow 里程碑（对齐 eFlow queryAllSteps 顺序）
 *          → ③ KPI → ④ 比率卡 → ⑤ 图表（计划/按时/状态环形）
 *          → ⑥ 流程耗时表+滞留图 → ⑦ 月度趋势 → ⑧ 类别表 → ⑨ 子类别表 → ⑩ 弹窗
 *
 * 里程碑放 KPI 之上：第一诉求是「现在卡在哪个审批口」（当下），
 * 计划达成率是历史统计。⚠️ AGENTS.md 第三节 1b：每个数字可点，
 * 且下钻维度必须与点击来源的卡片严格一致，否则行数对不上。
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
import { getCrAnalysisFilters, getCrAnalysisOverview, getCrAnalysisWorkflow } from '../api'
import CrDrillModal from './crAnalysis/CrDrillModal'
import CrWorkflowDrillModal from './crAnalysis/CrWorkflowDrillModal'
import CrWorkflowMilestones from './crAnalysis/CrWorkflowMilestones'
import CrWorkflowPanel, { orderSteps, stepLabelKey } from './crAnalysis/CrWorkflowPanel'
import {
  useCrStatusDrill, useCrFlowDrill, windowOf,
} from './crAnalysis/useCrDrills'
import {
  fmtRate, rateColor, rateLevel, summarize, COUNT_FIELDS,
  type Filters, type Metric, type Overview, type Workflow,
} from './crAnalysis/crTypes'
import { categoryColumns, subCategoryColumns } from './crAnalysis/crColumns'
import {
  chartColors, planChartOption, onTimeChartOption, statusChartOption, monthChartOption,
  workflowChartOption,
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

  /* ---- 审批流程（步骤耗时 / 滞留量），与概览分开取：它要解析文本列，略慢 ---- */
  const [workflow, setWorkflow] = useState<Workflow | null>(null)

  /* ---- 筛选条上的类别前端过滤（只影响展示，不影响下钻口径） ---- */
  const [activeCats, setActiveCats] = useState<string[]>([])

  /* ---- 取数 ---- */
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const params: Record<string, string> = {}
    if (start) params.start = start.format('YYYY-MM-DD')
    if (end) params.end = end.format('YYYY-MM-DD')
    // 概览与流程**并行**取：流程要全表扫一遍解析文本，串行会让页面白屏更久。
    // 流程失败不该拖垮整页 —— 它是增强信息，用 catch 单独降级：
    //   Promise.all 里任一失败会连带概览一起进 catch，故这里用 allSettled 的意图
    //   写成「主查询 try / 副查询 catch」，语义更直白。
    const wfPromise = getCrAnalysisWorkflow(params)
      .then(r => setWorkflow(r.data as Workflow))
      .catch(() => setWorkflow(null))
    try {
      const r = await getCrAnalysisOverview(params)
      setOv(r.data as Overview)
    } catch (e: any) {
      setError(e?.message || String(e))
      setOv(null)
    } finally {
      await wfPromise
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

  /* ---- 审批流程：步骤顺序取 STEP_KEYS（后端 WORKFLOW_STEPS 的真实时序）---- */
  const flowSteps = useMemo(() => orderSteps(workflow?.steps || []), [workflow])

  const flowOption = useMemo(() => workflowChartOption(
    flowSteps.map(s => ({
      label: t(stepLabelKey(s.step)),
      arrived: s.arrived,
      current: s.current,
    })),
    isDark, C,
    { arrived: t('cr.flow.legend.arrived'), current: t('cr.flow.legend.current') },
  ), [flowSteps, isDark, C, t])

  /* ---- 下钻：两套弹窗的状态与取数在 crAnalysis/useCrDrills.ts ---- */
  const win = useMemo(() => windowOf(start, end), [start, end])
  const statusDrill = useCrStatusDrill(win)
  const flowDrill = useCrFlowDrill(win)
  const openDrill = statusDrill.openDrill
  const openWfDrill = flowDrill.openDrill
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

      {/* ② Workflow 里程碑条：顺序对齐 eFlow 的 queryAllSteps Workflow History。
          等待数 → 该节点滞留明细；已完成数 → 走过该节点的明细。 */}
      <CrWorkflowMilestones
        milestones={workflow?.milestones || []}
        total={workflow?.total ?? summary.total}
        inFlight={workflow?.in_flight ?? 0}
        C={C}
        onWaiting={(step, at) => void openWfDrill(step, 'current', at)}
        onDone={(step, at) => void openWfDrill(step, 'arrived', at)}
        onClosed={at => {
          // Closed 是终态，不在步骤表里 —— 走状态下钻（status_key 后端已归一）
          const row = (ov?.status_rows || []).find(r => r.status_key === 'CLOSED')
          if (row) void openDrill('status', '', '', '', at, row.status_key, row.status)
        }}
      />

      {/* ③ KPI 行：每个数字可点下钻 */}
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

      {/* ④ 三个核心比率：分母写在数字下方，避免「100%」在小样本下被误读 */}
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

      {/* ⑤ 图表并排 */}
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
              ? <ReactECharts
                option={statusOption}
                style={{ height: 340 }}
                notMerge
                onEvents={{
                  // 扇区顺序与 status_rows 严格同序（option 里 data 就是它 map 出来的），
                  // 故用 dataIndex 回查，和计划柱图同一个做法，不靠名字猜
                  click: (p: any) => {
                    const s = ov?.status_rows?.[p?.dataIndex ?? -1]
                    if (!s) return
                    void openDrill('status', '', '', '',
                      { x: p?.event?.event?.clientX, y: p?.event?.event?.clientY },
                      s.status_key, s.status)
                  },
                }}
              />
              : <Empty description={t('cr.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑥ 审批流程：耗时表（左）+ 滞留量图（右）。
          数据来自 8 个 *_detail 文本列解析，概览接口不返回 —— 单独取、单独降级。
          展示与点击在 crAnalysis/CrWorkflowPanel.tsx，这里只传数据与回调。 */}
      <CrWorkflowPanel steps={flowSteps} C={C} option={flowOption} onPick={openWfDrill} />

      {/* ⑦ 月度趋势（编号见文件头） */}
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

      {/* ⑧ 类别明细表：全部数字可点 */}
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

      {/* ⑨ 子类别（设备类型）第二层维度 */}
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

      {/* ⑩ 下钻弹窗：类别/状态明细 + 审批步骤明细 */}
      <CrDrillModal
        open={statusDrill.open}
        subtitle={statusDrill.title}
        anchor={statusDrill.anchor}
        onClose={statusDrill.close}
        rows={statusDrill.rows}
        total={statusDrill.total}
        truncated={statusDrill.truncated}
        warn={statusDrill.warn}
        loading={statusDrill.loading}
        metric={statusDrill.metric}
      />

      <CrWorkflowDrillModal
        open={flowDrill.open}
        subtitle={flowDrill.title}
        anchor={flowDrill.anchor}
        onClose={flowDrill.close}
        rows={flowDrill.rows}
        total={flowDrill.total}
        truncated={flowDrill.truncated}
        warn={flowDrill.warn}
        loading={flowDrill.loading}
        fileKey={flowDrill.fileKey}
      />
    </div>
  )
}
