/* ============================================================================
 * PM 执行分析 —— 按 PM 计划 (pmp_no) 看预防性维护工单的完成与超期情况
 * ============================================================================
 *
 * 数据源：`eflow_pm`（eFlow 同步的动态建表，1632 行 @2026-09-25）。
 * 后端：`backend/routers/pm_analysis.py`，
 *       口径与「概览/下钻如何共用一份 WHERE」见
 *       `backend/services/pm_caliber.py` 的模块 docstring。
 *
 * ⚠️ **本表字段名有误导性**：实测 `last_accept_time` 100% 早于
 *    `last_process_time`，而 `last_flm_leader_approve_time` 最晚。
 *    页面上按**真实时序**展示流程漏斗（见 pmTypes.STEP_KEYS），
 *    不要按字段名字母序排。
 *
 * 本文件只负责**页面编排与取数**；配套模块在 `pages/pmAnalysis/` 下：
 *   - `pmTypes.ts`   —— 类型、常量、纯格式化与小计
 *   - `pmCharts.ts`  —— ECharts option 构造（纯函数）
 *   - `pmColumns.tsx` —— 表格列定义
 *   - `PmDrillModal.tsx` —— 明细弹窗（表格 + 导出）
 *
 * 页面结构：① 筛选条 → ② Workflow 里程碑（对齐 eFlow queryAllSteps 顺序）
 *          → ③ KPI 行 → ④ 三个比率卡 → ⑤ 图表 → ⑥ 月度趋势
 *          → ⑦ 流程漏斗 + 超期站点 → ⑧ 计划表 → ⑨ 下钻弹窗（含里程碑明细）
 *
 * ⚠️ 硬要求（AGENTS.md 第三节 1b）：「能下钻尽下钻」—— 页面上**每个数字都可点**，
 *    且下钻时 metric + 维度的组合必须与点击来源的卡片维度严格一致。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Select, Space, Table, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { useTheme } from '../theme'
import { CardBase } from '../components/cards'
import { exportAoaReport } from '../utils/excelReport'
import {
  getPmAnalysisFilters, getPmAnalysisOverview, getPmAnalysisDrilldown,
  getPmAnalysisWorkflow, getPmAnalysisWorkflowDrilldown,
} from '../api'
import PmDrillModal from './pmAnalysis/PmDrillModal'
import PmKpiCards from './pmAnalysis/PmKpiCards'
import PmMilestones, { milestoneLabelKey } from './pmAnalysis/PmMilestones'
import PmMilestoneDrillModal from './pmAnalysis/PmMilestoneDrillModal'
import {
  fmtRate, rateColorDesc, summarize, COUNT_FIELDS, STEP_KEYS,
  type DetailRow, type Filters, type Metric, type MilestoneDrillRow,
  type MilestoneKey, type Overview, type PmWorkflow,
} from './pmAnalysis/pmTypes'
import { planColumns, siteColumns } from './pmAnalysis/pmColumns'
import {
  chartColors, planChartOption, overdueChartOption, statusChartOption,
  monthChartOption, funnelChartOption, siteChartOption,
} from './pmAnalysis/pmCharts'

const { Text } = Typography

/** 下钻维度集合 */
type Dims = { pmp_no?: string; status?: string; site_name?: string; month?: string }

/** 里程碑下钻类型（与后端 drill_workflow 的 kind 同值） */
type MsKind = 'arrived' | 'current' | 'done'

/**
 * 概览的计划号筛选 → 后端 `pmp_no` 参数。
 *
 * 只有**恰好选中 1 个**计划号时才下推给后端：概览端点是按计划号精确过滤的，
 * 选多个时后端只能收一个值，前端筛完再算里程碑会与表格数字对不上。
 * 多选时里程碑按全部计划出数，并在界面上明确标注（见 `pm.ms.plansHint`），
 * 不让用户拿「里程碑数字」去对「表格小计」而以为是 bug。
 */
const workflowPmpOf = (plans: string[]) => (plans.length === 1 ? plans[0] : '')

/**
 * 计划号过滤上限。概览只回全量计划行，选中过多会让前端循环开销失控
 * （超限时保留前 N 个并显式告警，不静默丢弃 —— 见 AGENTS.md 第三节 1b）。
 */
const MAX_ACTIVE_PLANS = 30

export default function PmExecutionAnalysis() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 筛选条件 ---- */
  const [start, setStart] = useState<Dayjs | null>(null)
  const [end, setEnd] = useState<Dayjs | null>(null)

  /* ---- 数据与状态 ---- */
  const [ov, setOv] = useState<Overview | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /** 计划号筛选（前端过滤，只影响展示与后续下钻，不下推给概览端点） */
  const [activePlans, setActivePlans] = useState<string[]>([])
  /** 计划号筛选超限告警：超限即显式提示，避免用户以为选全了 */
  const [planWarn, setPlanWarn] = useState('')

  /** 计划号下拉选项：后端按工单量倒序返回，这里保持原序不重排 */
  const planOptions = useMemo(
    () => (filters?.pmp_nos || []).map(p => ({ label: p, value: p })),
    [filters],
  )

  const onPlansChange = useCallback((vals: string[]) => {
    if (vals.length > MAX_ACTIVE_PLANS) {
      setActivePlans(vals.slice(0, MAX_ACTIVE_PLANS))
      setPlanWarn(t('pm.filter.planNoMax', { n: MAX_ACTIVE_PLANS }))
      return
    }
    setActivePlans(vals)
    setPlanWarn('')
  }, [t])

  /* ---- 里程碑（Workflow History 顺序）；与概览分开取，失败单独降级 ---- */
  const [workflow, setWorkflow] = useState<PmWorkflow | null>(null)
  /** 计划号 → 后端参数。只有恰好 1 个计划时才下推（见 workflowPmpOf） */
  const pmpForWorkflow = useMemo(() => workflowPmpOf(activePlans), [activePlans])

  /* ---- 里程碑下钻弹窗状态 ---- */
  const [msOpen, setMsOpen] = useState(false)
  const [msAnchor, setMsAnchor] = useState<{ x: number; y: number } | null>(null)
  const [msTitle, setMsTitle] = useState('')
  const [msRows, setMsRows] = useState<MilestoneDrillRow[]>([])
  const [msTotal, setMsTotal] = useState(0)
  const [msTruncated, setMsTruncated] = useState(false)
  const [msWarn, setMsWarn] = useState('')
  const [msLoading, setMsLoading] = useState(false)
  const [msFileKey, setMsFileKey] = useState('')

  /* ---- 下钻弹窗状态 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillRows, setDrillRows] = useState<DetailRow[]>([])
  const [drillTotal, setDrillTotal] = useState(0)
  const [drillTruncated, setDrillTruncated] = useState(false)
  const [drillWarn, setDrillWarn] = useState('')
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillTitle, setDrillTitle] = useState('')
  const [lastMetric, setLastMetric] = useState('')

  /* ---- 取数 ---- */
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const params: Record<string, string> = {}
    if (start) params.start = start.format('YYYY-MM-DD')
    if (end) params.end = end.format('YYYY-MM-DD')

    // 概览与里程碑**并行**取。里程碑失败不拖垮整页 —— 它是增强信息，
    // 单独 catch 降级成 null（里程碑条显示空态），不与概览共用 catch。
    const wfParams = { ...params, ...(pmpForWorkflow ? { pmp_no: pmpForWorkflow } : {}) }
    const wfPromise = getPmAnalysisWorkflow(wfParams)
      .then(r => setWorkflow(r.data as PmWorkflow))
      .catch(() => setWorkflow(null))

    try {
      const r = await getPmAnalysisOverview(params)
      setOv(r.data as Overview)
    } catch (e: any) {
      setError(e?.message || String(e))
      setOv(null)
    } finally {
      await wfPromise
      setLoading(false)
    }
  }, [start, end, pmpForWorkflow])

  /* 首次进页面：先拉筛选项拿到**全表实际时间范围**，再据此初始化窗口 ——
     顺序不能反，否则会先用「今天往前 N 天」查一次再被覆盖，白跑一次库。
     （实测 created_time 从 2025-11-29 起，比「今天往前 300 天」更早。） */
  useEffect(() => {
    let alive = true
    getPmAnalysisFilters()
      .then(r => {
        if (!alive) return
        const f = r.data as Filters
        setFilters(f)
        if (f?.error) setError(f.error)
        setStart(f?.default_start ? dayjs(f.default_start) : dayjs().subtract(300, 'day'))
        setEnd(f?.default_end ? dayjs(f.default_end) : dayjs())
      })
      .catch(() => {
        if (!alive) return
        setStart(dayjs().subtract(300, 'day'))
        setEnd(dayjs())
      })
    return () => { alive = false }
  }, [])

  useEffect(() => { void load() }, [load])

  const rows = useMemo(() => {
    const all = ov?.rows || []
    if (!activePlans.length) return all
    return all.filter(r => activePlans.includes(r.pmp_no))
  }, [ov, activePlans])

  const summary = useMemo(() => summarize(rows), [rows])
  const C = useMemo(() => chartColors(isDark), [isDark])

  /* ---- 图表 option ---- */
  const planOption = useMemo(() => planChartOption(rows, isDark, C, {
    closed: t('pm.legend.closed'), open: t('pm.legend.open'),
    total: t('pm.col.total'), overdueRate: t('pm.kpi.overdueRate'),
  }), [rows, isDark, C, t])

  const overdueOption = useMemo(() => overdueChartOption(
    summary.overdue, summary.on_time, summary.overdue_rate, isDark, C,
    rateColorDesc(summary.overdue_rate),
    { overdue: t('pm.legend.overdue'), onTime: t('pm.legend.onTime') },
  ), [summary, isDark, C, t])

  const statusOption = useMemo(
    () => statusChartOption(ov?.status_rows || [], isDark, C),
    [ov, isDark, C],
  )

  const monthOption = useMemo(() => monthChartOption(ov?.months || [], isDark, C, {
    total: t('pm.col.total'), closed: t('pm.col.closed'), overdue: t('pm.col.overdue'),
  }), [ov, isDark, C, t])

  /** 漏斗：按 STEP_KEYS 的真实时序给标签，不按后端返回顺序猜 */
  const funnelOption = useMemo(() => {
    const byStep = new Map((ov?.steps || []).map(s => [s.step, s.cnt]))
    const steps = STEP_KEYS.map(k => ({ label: t(k.labelKey), cnt: byStep.get(k.step) || 0 }))
    return funnelChartOption(steps, isDark, C, {
      created: t('pm.kpi.created'), shareOfCreated: t('pm.chart.funnel.shareOfCreated'),
    })
  }, [ov, isDark, C, t])

  const siteOption = useMemo(() => siteChartOption(ov?.sites || [], isDark, C, {
    overdue: t('pm.legend.overdue'), open: t('pm.col.open'),
  }), [ov, isDark, C, t])

  /* ---- 下钻 ---- */
  const openDrill = useCallback(async (
    metric: Metric, dims: Dims = {}, at?: { x: number; y: number },
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
    const parts = [t(`pm.metric.${metric}`)]
    if (dims.pmp_no) parts.push(dims.pmp_no)
    if (dims.status) parts.push(dims.status)
    if (dims.site_name) parts.push(dims.site_name)
    if (dims.month) parts.push(dims.month)
    setDrillTitle(parts.join(' · '))

    try {
      const params: any = { metric, ...dims }
      if (start) params.start = start.format('YYYY-MM-DD')
      if (end) params.end = end.format('YYYY-MM-DD')
      const r = await getPmAnalysisDrilldown(params)
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
  const chartDrill = useCallback((metric: Metric, dims: Dims, p: any) => {
    void openDrill(metric, dims, {
      x: p?.event?.event?.clientX, y: p?.event?.event?.clientY,
    })
  }, [openDrill])

  /**
   * 里程碑下钻：走过 / 当前停留在某节点 / 已关闭。
   * 窗口与计划号与里程碑条**同一个来源**，保证明细行数 == 条上的数字
   * （AGENTS.md 第三节 1b）。计划号只在恰好选中 1 个时下推，与 `load` 一致。
   */
  const openMsDrill = useCallback(async (
    key: MilestoneKey, kind: MsKind, at?: { x: number; y: number },
  ) => {
    setMsOpen(true)
    setMsAnchor(at || null)
    setMsLoading(true)
    setMsRows([])
    setMsTotal(0)
    setMsTruncated(false)
    setMsWarn('')
    setMsFileKey(`${key}_${kind}`)

    const kindKey = kind === 'current' ? 'pm.ms.kind.current'
      : (kind === 'done' ? 'pm.ms.kind.done' : 'pm.ms.kind.arrived')
    setMsTitle(`${t(milestoneLabelKey(key))} · ${t(kindKey)}`)

    const params: any = { key, kind }
    if (start) params.start = start.format('YYYY-MM-DD')
    if (end) params.end = end.format('YYYY-MM-DD')
    if (pmpForWorkflow) params.pmp_no = pmpForWorkflow

    try {
      const r = await getPmAnalysisWorkflowDrilldown(params)
      const d = r.data || {}
      setMsRows(d.rows || [])
      setMsTotal(d.total ?? (d.rows || []).length)
      setMsTruncated(!!d.truncated)
      setMsWarn((d.meta?.warnings || []).join('; '))
    } catch (e: any) {
      setMsWarn(e?.message || String(e))
    } finally {
      setMsLoading(false)
    }
  }, [start, end, pmpForWorkflow, t])

  /** 导出计划汇总（表格那一屏） */
  const exportSummary = useCallback(() => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `PM_plan_summary_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'PM Plan Summary',
      title: t('pm.table.planTitle'),
      header: [
        t('pm.col.pmpNo'), t('pm.col.total'), t('pm.col.closed'), t('pm.col.open'),
        t('pm.col.overdue'), t('pm.col.notStarted'), t('pm.col.sites'),
        t('pm.kpi.closureRate'), t('pm.kpi.overdueRate'),
      ],
      rows: rows.map(r => [
        r.pmp_no, r.total, r.closed, r.open, r.overdue, r.not_started, r.sites,
        fmtRate(r.closure_rate), fmtRate(r.overdue_rate),
      ]),
      numericCols: [1, 2, 3, 4, 5, 6],
    })
  }, [rows, t])

  /* ---- 表格列（定义在 pmColumns.tsx，每个数字都可点下钻）---- */
  const columns = useMemo(() => planColumns(t, openDrill, C), [t, openDrill, C])
  const sColumns = useMemo(() => siteColumns(t, openDrill, C), [t, openDrill, C])

  const warningText = (ov?.meta?.warnings || []).join('; ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Text type="secondary">{t('pm.filter.range')}</Text>
          <DatePicker value={start} onChange={setStart} allowClear={false} />
          <span>{t('pm.filter.to')}</span>
          <DatePicker value={end} onChange={setEnd} allowClear={false} />
          {filters?.min_time && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('pm.filter.dataRange', { min: filters.min_time, max: filters.max_time, n: filters.row_count })}
            </Text>
          )}
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            {t('pm.filter.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportSummary} disabled={!rows.length}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {error && <Alert type="error" showIcon message={error} />}
      {warningText && <Alert type="warning" showIcon message={warningText} />}
      {planWarn && <Alert type="warning" showIcon message={planWarn} closable onClose={() => setPlanWarn('')} />}
      {/* 空态要区分「窗口内没数据」与「窗口内有数据但被计划号筛没了」——
          两句话术不同，混用会让用户去放宽时间范围却依然看不到东西 */}
      {!loading && !error && summary.total === 0 && (
        <Alert
          type="info" showIcon
          message={ov?.rows?.length ? t('pm.empty.filtered', { n: activePlans.length }) : t('pm.empty')}
        />
      )}
      {/* 筛选生效时明确写出「表格 == 筛选后子集」，否则用户会把合计当成全量 */}
      {!loading && activePlans.length > 0 && rows.length > 0 && (
        <Alert type="info" showIcon message={t('pm.filter.activePlans', { n: activePlans.length })} />
      )}

      {/* ② Workflow 里程碑条：顺序严格对齐 eFlow 的 queryAllSteps Workflow History
          （Create → Schedule → Accept → Process → PM Manager Approve → FLM Leader
          Approve → Closed）。等待数 → 该节点滞留明细；已完成数 → 走过该节点的明细。
          多选计划号时里程碑不随之过滤（后端按单一 pmp_no 精确过滤），
          故显式提示，避免用户拿里程碑数字去对表格小计。 */}
      {activePlans.length > 1 && (
        <Alert type="info" showIcon message={t('pm.ms.plansHint', { n: activePlans.length })} />
      )}
      <PmMilestones
        milestones={workflow?.milestones || []}
        total={workflow?.total ?? summary.total}
        inFlight={workflow?.in_flight ?? summary.open}
        C={C}
        onWaiting={(key, at) => void openMsDrill(key, 'current', at)}
        onDone={(key, at) => void openMsDrill(key, 'arrived', at)}
        onClosed={at => void openMsDrill('closed', 'done', at)}
      />

      {/* ③④ KPI 计数卡 + 核心比率卡（每个数字可点下钻） */}
      <PmKpiCards
        t={t}
        C={C}
        counts={summary}
        plans={summary.plans}
        rates={{
          closure: summary.closure_rate,
          overdue: summary.overdue_rate,
          started: summary.start_rate,
        }}
        onDrill={(metric, at) => void openDrill(metric, {}, at)}
      />

      {/* ④ 图表并排 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={14}>
          <CardBase
            title={t('pm.chart.plan.title')}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('pm.chart.plan.hint')}</Text>}
          >
            {rows.length
              ? <ReactECharts
                option={planOption}
                style={{ height: 340 }}
                notMerge
                onEvents={{
                  // 计划号由 dataIndex 反查，保证与柱子严格对应（不靠系列名猜）
                  click: (p: any) => {
                    const plan = rows[p?.dataIndex ?? -1]
                    if (!plan) return
                    const metric: Metric =
                      p?.seriesName === t('pm.legend.open') ? 'open' : 'closed'
                    chartDrill(metric, { pmp_no: plan.pmp_no }, p)
                  },
                }}
              />
              : <Empty description={t('pm.empty')} />}
          </CardBase>
        </Col>
        <Col xs={24} sm={12} xl={5}>
          <CardBase
            title={t('pm.chart.overdue.title')}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('pm.chart.overdue.hint')}</Text>}
          >
            {summary.total
              ? <ReactECharts option={overdueOption} style={{ height: 340 }} notMerge
                onEvents={{
                  click: (p: any) => chartDrill(
                    p?.name === t('pm.legend.overdue') ? 'overdue' : 'on_time', {}, p),
                }} />
              : <Empty description={t('pm.empty')} />}
          </CardBase>
        </Col>
        <Col xs={24} sm={12} xl={5}>
          <CardBase
            title={t('pm.chart.status.title')}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('pm.chart.status.hint')}</Text>}
          >
            {ov?.status_rows?.length
              ? <ReactECharts option={statusOption} style={{ height: 340 }} notMerge
                onEvents={{
                  click: (p: any) => chartDrill('total', { status: p?.name }, p),
                }} />
              : <Empty description={t('pm.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑤ 月度趋势 */}
      <CardBase
        title={t('pm.chart.month.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('pm.chart.month.hint')}</Text>}
      >
        {ov?.months?.length
          ? <ReactECharts
            option={monthOption}
            style={{ height: 280 }}
            notMerge
            onEvents={{
              click: (p: any) => {
                const m = ov.months[p?.dataIndex ?? -1]?.month
                if (!m) return
                const metric: Metric = p?.seriesName === t('pm.col.overdue') ? 'overdue'
                  : (p?.seriesName === t('pm.col.closed') ? 'closed' : 'total')
                chartDrill(metric, { month: m }, p)
              },
            }}
          />
          : <Empty description={t('pm.empty')} />}
      </CardBase>

      {/* ⑥ 流程漏斗 + 超期站点：一个看流程卡在哪，一个看该抓哪些站 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={10}>
          <CardBase
            title={t('pm.chart.funnel.title')}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('pm.chart.funnel.hint')}</Text>}
          >
            {ov?.steps?.length
              ? <ReactECharts option={funnelOption} style={{ height: 300 }} notMerge />
              : <Empty description={t('pm.empty')} />}
          </CardBase>
        </Col>
        <Col xs={24} xl={14}>
          <CardBase
            title={t('pm.chart.site.title')}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('pm.chart.site.hint')}</Text>}
          >
            {ov?.sites?.length
              ? <ReactECharts
                option={siteOption}
                style={{ height: 300 }}
                notMerge
                onEvents={{
                  click: (p: any) => {
                    // 站点名直接从 ECharts 事件的 name 拿（y 轴 category 即站点名），
                    // 不用 dataIndex 反查：漏斗/站点图是逆序绘制的，反查容易错位。
                    const name = p?.name
                    if (!name) return
                    const metric: Metric = p?.seriesName === t('pm.legend.overdue') ? 'overdue' : 'open'
                    chartDrill(metric, { site_name: name }, p)
                  },
                }}
              />
              : <Empty description={t('pm.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑦ 计划明细表：全部数字可点 */}
      <CardBase
        title={t('pm.table.planTitle')}
        extra={
          <Space size="small" wrap>
            {/* 计划号筛选：可搜索多选下拉，取代原先「预置 8 个标签」的排列 ——
                标签只能点开列出的那几个，计划号有 27 个时其余无法筛到。 */}
            <Text type="secondary" style={{ fontSize: 12 }}>{t('pm.filter.planNo')}</Text>
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              maxTagCount="responsive"
              style={{ minWidth: 260, maxWidth: 460 }}
              placeholder={t('pm.filter.planNoPh')}
              value={activePlans}
              options={planOptions}
              onChange={onPlansChange}
            />
            {activePlans.length > 0 && (
              <Button type="link" size="small" onClick={() => { setActivePlans([]); setPlanWarn('') }}>
                {t('pm.filter.clear')}
              </Button>
            )}
          </Space>
        }
      >
        <Table
          rowKey="pmp_no"
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 1500 }}
          pagination={false}
          // 小计行：让「表格内的数字加起来 == 上面 KPI」一眼可见
          summary={() => (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ fontWeight: 700 }}>
                <Table.Summary.Cell index={0}>{t('pm.table.subtotal')}</Table.Summary.Cell>
                {COUNT_FIELDS.map((f, i) => (
                  <Table.Summary.Cell key={f} index={i + 1} align="right">
                    {summary[f]}
                  </Table.Summary.Cell>
                ))}
                <Table.Summary.Cell index={6} align="right">
                  {fmtRate(summary.total_items
                    ? Math.round((summary.completed_items / summary.total_items) * 1000) / 10
                    : null)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={7} align="right">—</Table.Summary.Cell>
                <Table.Summary.Cell index={8} align="right">{fmtRate(summary.closure_rate)}</Table.Summary.Cell>
                <Table.Summary.Cell index={9} align="right">{fmtRate(summary.overdue_rate)}</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      </CardBase>

      {/* ⑧ 超期最多的站点（表格形态，便于按站追踪） */}
      <CardBase
        title={t('pm.table.siteTitle')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('pm.table.siteHint', { n: ov?.sites?.length || 0 })}</Text>}
      >
        <Table
          rowKey="site_name"
          columns={sColumns}
          dataSource={ov?.sites || []}
          loading={loading}
          size="small"
          scroll={{ x: 640 }}
          pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] }}
        />
      </CardBase>

      {/* ⑨ 下钻弹窗：KPI/计划/站点明细 + 里程碑明细 */}
      <PmMilestoneDrillModal
        open={msOpen}
        subtitle={msTitle}
        anchor={msAnchor}
        onClose={() => setMsOpen(false)}
        rows={msRows}
        total={msTotal}
        truncated={msTruncated}
        warn={msWarn}
        loading={msLoading}
        fileKey={msFileKey}
      />

      <PmDrillModal
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
