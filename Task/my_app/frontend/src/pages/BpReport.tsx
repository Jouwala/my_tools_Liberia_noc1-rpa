/* ============================================================================
 * BP Report —— 劣化小区（Bad Performance）报告
 * ============================================================================
 *
 * 口径（umlaut 定义，唯一真相源在 backend/services/bp_caliber.py）：
 *   Daily:   Average DL Active User Number > 2.5
 *            AND [FDD]DL IP Throughput(Mbps) < 3
 *            AND [FDD]DL PRB Utilization Rate > 80%
 *   Weekly:  一周内 4/7 天为 BP
 *   Monthly: 一个月内 3/4 个完整周为 BP
 *
 * ⚠️ 本页**口径不完整**，页面顶部常驻告警，不要隐藏：
 *    `Average DL Active User Number` 在 RAN_UME 侧未采集（最接近的
 *    C373200029:Maximum Number of RRC Connection User 是**峰值**、不等价），
 *    因此每日判定实际只覆盖两个条件，重算结果必然低于 Excel 真值。
 *
 * 数据来源（后端 routers/bp_report.py）：
 *   - Excel `BP Report.xlsx` 一次性导入：提供 cell → Cluster/Layer 字典
 *     （RAN_UME 完全没有 Cluster1~6/Rural 这套分区维度）+ 汇总真值
 *   - `bp_report_sync` 任务每日从 RAN_UME 更新指标并重算
 *
 * 下钻一致性（AGENTS.md 第三节 1b）：
 *   本页每个数字都可点。`bp_cells` 可下钻且行数与卡片一致（后端同一 WHERE）；
 *   `total_cells` **不做下钻入口** —— 它是 Excel 的全网口径、未提供名单，
 *   明细表只覆盖 BP Cells List 里的小区，硬比会得到看着像 bug 的差异。
 *   后端在 `/overview` 的 `drilldown.total_cells.comparable=false` 里明确声明了这点。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Segmented, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { useTheme, axisLabel, axisLine, darkTooltip, splitLine, cardStyle, WH } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportAoaReport } from '../utils/excelReport'
import { getBpReportOverview, getBpReportRegional, getBpReportLayer, getBpReportCells, getBpReportMeta } from '../api'

const { Text } = Typography

/* ---- 类型（与后端返回结构对齐） ---- */
type TrendPoint = {
  period: string
  bp_cells: number
  total_cells: number
  bp_ratio: number | null
  traffic_tb: number | null
  bp_cells_excel: number | null
  source: string
  /** 明细侧（BP Cells List）该期的 BP 行数；0 表示该期无明细 */
  detail_cells?: number | null
  /** 明细与展示值的差异，非 0 即上游两张 sheet 不一致 */
  detail_diff?: number | null
  /** 该期能否下钻：2023/2024 早期明细缺失，置 false */
  drillable?: boolean
  bp_days?: number | null
  total_days?: number | null
  is_bp_week?: number | null
  bp_weeks?: number | null
  total_weeks?: number | null
  is_bp_month?: number | null
}
type CellRow = {
  day: string
  cell_name: string
  me_id: string | null
  cluster: string
  layer: string
  is_bp: number | null
  prb_dl: number | null
  thr_dl: number | null
  active_user: number | null
  dl_gb: number | null
  ul_gb: number | null
  source: string
  prb_ok: boolean
  thr_ok: boolean
  user_ok: boolean | null
}
type MetaInfo = {
  active_user?: { available: boolean; reason?: string; item?: string | null
                  threshold?: number; fallback_column?: string | null }
  warnings?: string[]
  last_sync_at?: string | null
  last_import_at?: string | null
  caliber?: Record<string, unknown>
  dirty?: Record<string, number>
  reconcile?: Record<string, unknown>
  counts?: Record<string, number>
}

/** 统一空值展示：— 而不是 0（AGENTS.md 原则 6）。三态字段尤其不能用 0 冒充。 */
const fmt = (v: unknown) => (v == null || v === '' ? '—' : String(v))
const fmtNum = (v: number | null | undefined, d = 2) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtPct = (v: number | null | undefined) =>
  v == null ? '—' : `${(v * 100).toFixed(2)}%`

/**
 * 三态 is_bp → 展示标签。
 * ⚠️ 不能用三元表达式拼 i18n key（check:i18n 会把动态拼接读成残缺键名），
 *    必须像这样用显式分支返回**字面量**键。
 */
function bpStateKey(v: number | null): string {
  if (v === 1) return 'bp.state.bp'
  if (v === 0) return 'bp.state.nonbp'
  return 'bp.state.undecidable'
}
function bpStateColor(v: number | null): string {
  if (v === 1) return 'red'
  if (v === 0) return 'default'
  return 'orange'
}
/** 周/月判定标签同样走显式分支（NULL = 不可判定，与「否」必须区分） */
function periodStateKey(v: number | null | undefined): string {
  if (v === 1) return 'bp.state.yes'
  if (v === 0) return 'bp.state.no'
  return 'bp.state.unknown'
}

export default function BpReport() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 筛选条件 ---- */
  const [grain, setGrain] = useState<'day' | 'week' | 'month'>('day')
  const [start, setStart] = useState<Dayjs | null>(dayjs().subtract(60, 'day'))
  const [end, setEnd] = useState<Dayjs | null>(dayjs())

  /* ---- 数据与状态：loading / error / data 三件套是页面标配 ---- */
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [summary, setSummary] = useState<Record<string, number | null>>({})
  const [drilldownInfo, setDrilldownInfo] = useState<Record<string, any>>({})
  const [regions, setRegions] = useState<Array<Record<string, any>>>([])
  const [layers, setLayers] = useState<Array<Record<string, any>>>([])
  const [meta, setMeta] = useState<MetaInfo>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [drillRows, setDrillRows] = useState<CellRow[]>([])
  const [drillInfo, setDrillInfo] = useState<{ title: string
                                               excel: number | null
                                               truncated: boolean; clicked: number | null }>(
    { title: '', excel: null, truncated: false, clicked: null })
  const [drillLoading, setDrillLoading] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  const rangeParams = useCallback(() => ({
    start: start ? start.format('YYYY-MM-DD') : '',
    end: end ? end.format('YYYY-MM-DD') : '',
  }), [start, end])

  /* ---- 取数：所有失败都要落到 error 上并渲染 <Alert>，不要静默 ---- */
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = rangeParams()
      const [ovRes, rgRes, lyRes, mtRes] = await Promise.all([
        getBpReportOverview({ ...p, granularity: grain }),
        getBpReportRegional(p),
        getBpReportLayer(p),
        getBpReportMeta(),
      ])
      const ov = ovRes.data || {}
      setTrend(ov.trend || [])
      setSummary(ov.summary || {})
      setDrilldownInfo(ov.drilldown || {})
      setRegions(rgRes.data?.regions || [])
      setLayers(lyRes.data?.layers || [])
      setMeta(mtRes.data || {})
      // 后端在 meta.warnings 里给出「口径不完整」「脏值」等硬告警，必须显式抛到界面
      if (ov.meta?.warnings?.length) setError(ov.meta.warnings.join(' / '))
    } catch (e: any) {
      setError(e?.message || String(e))
      setTrend([])
      setRegions([])
      setLayers([])
    } finally {
      setLoading(false)
    }
  }, [grain, rangeParams])

  useEffect(() => { void load() }, [load])

  /* ---- 最新一期与合计（卡片数字） ---- */
  const latest = useMemo(() => trend[trend.length - 1] || null, [trend])

  /* ---- 图表：BP 小区数趋势 + Excel 真值对照 ----
   * ⚠️ ECharts 取色必须用 isDark 实值，不能写 WH.xxx（canvas 解析不了 CSS 变量）。
   */
  const chartOption = useMemo(() => {
    const periods = trend.map(p => p.period)
    const bp = trend.map(p => p.bp_cells)
    // 只在日粒度下明细才有意义（周/月表结构不同）
    const excel = grain === 'day' ? trend.map(p => p.detail_cells ?? null) : []
    const ratio = trend.map(p => (p.bp_ratio == null ? null : +(p.bp_ratio * 100).toFixed(2)))
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
      legend: { data: [t('bp.series.bp'), t('bp.series.ratio')], textStyle: { color: isDark ? '#c9d1d9' : '#374151' } },
      grid: { left: 56, right: 56, top: 40, bottom: 56 },
      xAxis: {
        type: 'category',
        data: periods,
        axisLabel: { ...axisLabel(isDark), rotate: 35 },
        axisLine: axisLine(isDark),
      },
      yAxis: [
        { type: 'value', name: t('bp.axis.cells'), axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
        { type: 'value', name: '%', axisLabel: axisLabel(isDark), splitLine: { show: false } },
      ],
      series: [
        {
          name: t('bp.series.bp'), type: 'bar', data: bp,
          itemStyle: { color: isDark ? '#ff7875' : '#cf1322' },
        },
        ...(excel.length ? [{
          name: t('bp.series.detail'), type: 'line', data: excel,
          itemStyle: { color: isDark ? '#ffd666' : '#d48806' },
          lineStyle: { type: 'dashed' }, symbolSize: 4,
        }] : []),
        {
          name: t('bp.series.ratio'), type: 'line', yAxisIndex: 1, data: ratio,
          itemStyle: { color: isDark ? '#00d9ff' : '#0d9488' }, symbolSize: 4,
        },
      ],
    }
  }, [trend, grain, isDark, t])

  /* ---- 分区图 ---- */
  const regionOption = useMemo(() => ({
    tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
    grid: { left: 56, right: 24, top: 28, bottom: 64 },
    xAxis: {
      type: 'category',
      data: regions.map(r => r.region),
      axisLabel: { ...axisLabel(isDark), rotate: 35 },
      axisLine: axisLine(isDark),
    },
    yAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
    series: [{
      name: t('bp.series.bp'), type: 'bar',
      data: regions.map(r => r.bp_number),
      itemStyle: { color: isDark ? '#ff7875' : '#cf1322' },
    }],
  }), [regions, isDark, t])

  /* ---- 导出：一律走 excelReport ---- */
  const exportTrend = useCallback(() => {
    if (!trend.length) return
    void exportAoaReport({
      filename: `bp_report_${grain}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'BP',
      title: t('bp.title'),
      header: [t('bp.col.period'), t('bp.col.bp'), t('bp.col.total'),
               t('bp.col.ratio'), t('bp.col.traffic'), t('bp.col.detail')],
      // 最后一列导出 BP Cells List 的明细行数，便于在 Excel 里直接核对上游差异
      rows: trend.map(p => [p.period, p.bp_cells, p.total_cells,
                            p.bp_ratio, p.traffic_tb, p.detail_cells ?? null]),
      numericCols: [1, 2, 3, 4, 5],
    })
  }, [trend, grain, t])

  const exportRows = useCallback((list: CellRow[], name: string) => {
    if (!list.length) return
    void exportAoaReport({
      filename: `${name}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: name,
      title: name,
      header: [t('bp.col.day'), t('bp.col.cell'), t('bp.col.meId'), t('bp.col.cluster'),
               t('bp.col.layer'), t('bp.col.state'), t('bp.col.prb'), t('bp.col.thr'),
               t('bp.col.ratio'), t('bp.col.dl'), t('bp.col.ul')],
      rows: list.map(r => [r.day, r.cell_name, r.me_id, r.cluster, r.layer,
                           t(bpStateKey(r.is_bp)), r.prb_dl, r.thr_dl,
                           r.prb_ok, r.dl_gb, r.ul_gb]),
      numericCols: [6, 7, 10, 11],
    })
  }, [t])

  /* ---- 下钻：打开弹窗并取明细 ---- */
  const openDrill = useCallback(async (
    opts: { day?: string; start?: string; end?: string; region?: string; layer?: string
            scope?: string; title: string; clicked?: number | null },
    at?: { x: number; y: number },
  ) => {
    setOpen(true)
    setAnchor(at || null)
    setDrillLoading(true)
    setDrillInfo({ title: opts.title, excel: null, truncated: false,
                   clicked: opts.clicked ?? null })
    setDrillRows([])
    try {
      const r = await getBpReportCells({
        day: opts.day || '', start: opts.start || '', end: opts.end || '',
        region: opts.region || '', layer: opts.layer || '', scope: opts.scope || 'all',
      })
      const d = r.data || {}
      setDrillRows(d.rows || [])
      setDrillInfo({
        title: opts.title,
        excel: d.excel_cells ?? null, truncated: !!d.meta?.truncated,
        clicked: opts.clicked ?? null,
      })
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setDrillLoading(false)
    }
  }, [])

  /* ---- 表格列 ---- */
  const columns = useMemo(() => [
    { title: t('bp.col.period'), dataIndex: 'period', width: 130 },
    {
      title: t('bp.col.bp'), dataIndex: 'bp_cells', align: 'right' as const,
      // 数字可点：落到该期的 BP 小区明细。
      // ⚠️ 仅当后端标注该期可下钻（drillable）时才给入口 —— 2023 无明细、
      //    2024 部分缺天，点开只会是空弹窗，那是比「不给点」更糟的体验。
      // ⚠️ 仅当后端**明确**标注该期可下钻时才给入口 —— 2023 无明细、2024 部分缺天，
      //    点开只会是空弹窗，那是比「不给点」更糟的体验。
      //    守卫用 `!== true`（而不是 `=== false`）：后端一旦漏发该字段（2026-09-29 的
      //    周/月粒度就漏过），undefined 会被当"可下钻"，守卫形同虚设。
      render: (v: number, r: TrendPoint) => (
        r.drillable !== true
          ? (
            <Tooltip title={t('bp.tip.noDetail')}>
              <span style={{ cursor: 'help', opacity: 0.65 }}>{v ?? '—'}</span>
            </Tooltip>
          )
          : (
            <Button type="link" style={{ padding: 0 }}
              onClick={e => void openDrill(
                grain === 'day'
                  ? { day: r.period, scope: 'bp', title: `${t('bp.drill.bp')} · ${r.period}`,
                      clicked: r.bp_cells }
                  : { start: r.period, scope: 'bp', title: `${t('bp.drill.bp')} · ${r.period}`,
                      clicked: r.bp_cells },
                { x: e.clientX, y: e.clientY })}>
              {v ?? '—'}
            </Button>
          )
      ),
    },
    {
      title: t('bp.col.total'), dataIndex: 'total_cells', align: 'right' as const,
      // ⚠️ 刻意**不做**下钻：Excel 全网口径、无名单，与明细表分母不同
      render: (v: number) => (
        <Tooltip title={t('bp.tip.totalNoDrill')}>
          <span style={{ cursor: 'help' }}>{v ?? '—'}</span>
        </Tooltip>
      ),
    },
    { title: t('bp.col.ratio'), dataIndex: 'bp_ratio', align: 'right' as const,
      render: (v: number | null) => fmtPct(v) },
    { title: t('bp.col.traffic'), dataIndex: 'traffic_tb', align: 'right' as const,
      render: (v: number | null) => fmtNum(v, 1) },
    // 明细行数「并排」展示，而不是替换展示值：
    // 上游两张 sheet 本就不一致（2025/2026 明细偏多，2023/2024 明细偏少），
    // 差异非 0 时用颜色标出，鼠标悬停给出具体差额。
    // 三种粒度都有该列（后端已统一发放 detail_cells / drillable）。
    {
      title: t('bp.col.detail'), dataIndex: 'detail_cells', align: 'right' as const,
      render: (v: number | null, r: TrendPoint) => {
        if (r.drillable !== true) return <Text type="secondary">{t('bp.detail.none')}</Text>
        const d = r.detail_diff ?? 0
        // 周/月的差额主要来自 population 差异（Excel 只列 BP 小区，
        // RAN_UME 列出全部被评估小区），与日粒度「同一批小区两张 sheet 对不上」
        // 不是一回事，提示语要分开讲，否则用户会把量级差当成 bug。
        const tip = grain === 'day'
          ? t('bp.tip.excelDiff', { d })
          : t('bp.tip.excelDiffGrain', { d })
        return (
          <Tooltip title={tip}>
            <span style={{ cursor: 'help', color: d === 0 ? undefined : WH.warn }}>
              {fmt(v)}{d === 0 ? '' : ` (${d > 0 ? '+' : ''}${d})`}
            </span>
          </Tooltip>
        )
      },
    },
  ], [t, grain, openDrill])

  const drillColumns = useMemo(() => [
    { title: t('bp.col.day'), dataIndex: 'day', width: 100 },
    { title: t('bp.col.cell'), dataIndex: 'cell_name', width: 160 },
    { title: t('bp.col.cluster'), dataIndex: 'cluster', width: 96 },
    { title: t('bp.col.layer'), dataIndex: 'layer', width: 110 },
    {
      title: t('bp.col.state'), dataIndex: 'is_bp', width: 96,
      render: (v: number | null) => <Tag color={bpStateColor(v)}>{t(bpStateKey(v))}</Tag>,
    },
    { title: t('bp.col.prb'), dataIndex: 'prb_dl', align: 'right' as const,
      render: (v: number | null) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`) },
    { title: t('bp.col.thr'), dataIndex: 'thr_dl', align: 'right' as const,
      render: (v: number | null) => fmtNum(v) },
    { title: t('bp.col.dl'), dataIndex: 'dl_gb', align: 'right' as const,
      render: (v: number | null) => fmtNum(v, 1) },
  ], [t])

  const au = meta.active_user
  const latestIsBp = latest
    ? (grain === 'day' ? latest.is_bp_week : grain === 'week' ? latest.is_bp_week
       : latest.is_bp_month)
    : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 口径缺口告警：**常驻**，不是可选提示。
          缺 active-user 会直接让判定偏低，隐藏它等于给出误导性结论。 */}
      {au && !au.available && (
        <Alert
          type="warning" showIcon banner
          message={t('bp.banner.title')}
          description={au.reason || t('bp.banner.desc')}
        />
      )}

      {/* ② 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Segmented
            value={grain}
            onChange={v => setGrain(v as 'day' | 'week' | 'month')}
            options={[
              { label: t('bp.grain.day'), value: 'day' },
              { label: t('bp.grain.week'), value: 'week' },
              { label: t('bp.grain.month'), value: 'month' },
            ]}
          />
          <DatePicker value={start} onChange={setStart} />
          <span>{t('bp.to')}</span>
          <DatePicker value={end} onChange={setEnd} />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            {t('bp.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportTrend} disabled={!trend.length}>
            {t('common.exportExcel')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.syncAt', { v: fmt(meta.last_sync_at) })}
          </Text>
        </Space>
      </CardBase>

      {/* ③ 错误与警告 */}
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}

      {/* ④ 数字卡：每张都可点下钻（latest 为最新一期） */}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <div onClick={e => latest && void openDrill(
            { day: grain === 'day' ? latest.period : '', scope: 'bp',
              title: `${t('bp.drill.bp')} · ${latest.period}`, clicked: latest.bp_cells },
            { x: e.clientX, y: e.clientY })}
            style={{ cursor: latest ? 'pointer' : 'default' }}>
            <StatCard title={t('bp.kpi.latestBp')} value={latest?.bp_cells ?? 0}
              suffix={latest ? `(${latest.period})` : ''} />
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('bp.kpi.periods')} value={summary.periods ?? 0} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('bp.kpi.avgRatio')} value={fmtPct(summary.avg_ratio as number)} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          {/* 三态：不可判定显示「不可判定」而不是「否」 */}
          <CardBase level={latestIsBp === 1 ? 'crit' : 'ok'}
            title={t('bp.kpi.latestState')} as="div">
            <Text strong style={{ fontSize: 20 }}>
              {grain === 'day'
                ? t('bp.state.undecidable')
                : t(periodStateKey(latestIsBp))}
            </Text>
            {grain !== 'day' && latest && (
              <div style={{ fontSize: 12, color: WH.textMuted, marginTop: 4 }}>
                {grain === 'week'
                  ? t('bp.kpi.weekDetail', { a: fmt(latest.bp_days), b: fmt(latest.total_days) })
                  : t('bp.kpi.monthDetail', { a: fmt(latest.bp_weeks), b: fmt(latest.total_weeks) })}
              </div>
            )}
          </CardBase>
        </Col>
      </Row>

      {/* ⑤ 趋势图 */}
      <CardBase title={t('bp.chart.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('bp.chart.hint')}</Text>}>
        {trend.length
          ? <ReactECharts option={chartOption} style={{ height: 340 }} notMerge />
          : <Empty description={t('bp.empty')} />}
      </CardBase>

      {/* ⑥ 分区 + 分层 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <CardBase title={t('bp.region.title')}>
            {regions.length
              ? <ReactECharts option={regionOption} style={{ height: 300 }} notMerge />
              : <Empty description={t('bp.empty')} />}
          </CardBase>
        </Col>
        <Col xs={24} lg={12}>
          <CardBase title={t('bp.layer.title')}>
            {layers.length ? (
              <Table
                rowKey="layer" size="small" pagination={false}
                dataSource={layers}
                columns={[
                  { title: t('bp.col.layer'), dataIndex: 'layer' },
                  { title: t('bp.col.bp'), dataIndex: 'bp_number', align: 'right' as const,
                    render: (v: number, r: Record<string, any>) => (
                      <Button type="link" style={{ padding: 0 }}
                        onClick={e => void openDrill(
                          { ...rangeParams(), layer: r.layer, scope: 'bp',
                            title: `${t('bp.drill.bp')} · ${r.layer}`, clicked: v },
                          { x: e.clientX, y: e.clientY })}>{v}</Button>
                    ) },
                  { title: t('bp.col.total'), dataIndex: 'total_cell', align: 'right' as const },
                ]}
              />
            ) : <Empty description={t('bp.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑦ 明细表 */}
      <CardBase title={t('bp.table.title')} interactive={false}>
        <Table
          rowKey="period"
          columns={columns}
          dataSource={trend}
          loading={loading}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 800 }}
          size="small"
        />
      </CardBase>

      {/* ⑧ 口径与数据质量：把「为什么数字是这样」讲清楚 */}
      <CardBase title={t('bp.caliber.title')}>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {(meta.caliber as any)?.notes
            ? ((meta.caliber as any).notes as string[]).map((n, i) => (
                <Text key={i} type="secondary" style={{ fontSize: 12 }}>· {n}</Text>
              ))
            : null}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.daily')}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.weekly')}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.monthly')}
          </Text>
          {meta.dirty?.rows_unknown_cluster ? (
            <Text type="warning" style={{ fontSize: 12 }}>
              {t('bp.caliber.dirty', { n: meta.dirty.rows_unknown_cluster })}
            </Text>
          ) : null}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.importAt', { v: fmt(meta.last_import_at) })}
          </Text>
          {drilldownInfo?.total_cells?.comparable === false && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('bp.caliber.noDrill', { n: drilldownInfo.total_cells.detail_cells ?? 0 })}
            </Text>
          )}
        </Space>
      </CardBase>

      {/* ⑨ 下钻弹窗 */}
      <DraggableClickModal
        open={open}
        title={drillInfo.title || t('bp.drill.title')}
        anchor={anchor}
        onClose={() => setOpen(false)}
      >
        <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
          {/* 先摆「你点的是多少」，再摆「明细实际有几行」。
              两者不等是上游 Excel 两张 sheet 的口径差异（Overall 汇总 vs BP Cells List 明细），
              不是查询 bug —— 这里必须显式对照，不能让用户以为点 463 看到的就该是 463 行。 */}
          {drillInfo.clicked != null && (
            <Tag color="blue">{t('bp.drill.clicked', { n: drillInfo.clicked })}</Tag>
          )}
          <Tag color="red">{t('bp.drill.count', { n: drillRows.length })}</Tag>
          {drillInfo.excel != null && drillInfo.clicked != null && (
            <Tooltip title={t('bp.tip.excelDiff', { d: drillInfo.excel - drillInfo.clicked })}>
              <Tag color="gold">{t('bp.drill.excelCount', { n: drillInfo.excel })}</Tag>
            </Tooltip>
          )}
          {drillInfo.truncated && <Tag color="orange">{t('bp.drill.truncated')}</Tag>}
          <Button size="small" icon={<DownloadOutlined />}
            onClick={() => exportRows(drillRows, 'bp_cells')}>
            {t('common.exportExcel')}
          </Button>
        </Space>
        <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
          <Table
            rowKey={r => `${r.day}-${r.cell_name}`}
            columns={drillColumns}
            dataSource={drillRows}
            loading={drillLoading}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            size="small"
            scroll={{ x: 900 }}
          />
        </div>
      </DraggableClickModal>
    </div>
  )
}
