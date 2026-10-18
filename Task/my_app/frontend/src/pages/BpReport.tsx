/* ============================================================================
 * BP Report —— 劣化小区（Bad Performance）报告
 * ============================================================================
 *
 * 口径（umlaut 定义，唯一真相源在 backend/services/bp_caliber.py）：
 *   Daily:   Average DL Active User Number > 2.5
 *            AND [FDD]DL IP Throughput(Mbps) < 3
 *            AND [FDD]DL PRB Utilization Rate > 80% *   Weekly:  一周内 4/7 天为 BP
 *   Monthly: 一个月内 3/4 个完整周为 BP
 *
 * ⚠️ 三条件的**日值都是忙时值**（AU 最大小时那一小时的 PRB/Thr/AU），
 *    不是全天平均 —— 与直觉不同，页面顶部有可展开的口径说明条。该口径经标定
 *    与 umlaut Excel 的 BP 名单逐小区一致（09-21：607 vs 607，Jaccard=1.00）；
 *    日均值口径会漏判约 97% 的 BP 小区。
 *
 * 数据来源（后端 routers/bp_report.py）：
 *   - Excel `BP Report.xlsx` 一次性导入：提供 cell → Cluster/Layer 字典
 *     （RAN_UME 完全没有 Cluster1~6/Rural 这套分区维度）+ 历史汇总真值
 *   - `bp_report_sync` 任务每日从 RAN_UME 取**忙时三值**并重算
 *
 * 下钻一致性（AGENTS.md 第三节 1b「能下钻尽下钻」）：
 *   本页能下钻的数字都做了入口，且行数与展示数字由**同一 WHERE** 保证：
 *   `bp_cells` / `total_cells` / `regional.bp_number` / `layer.bp_number` /
 *   `undecidable` 均可下钻。唯一例外是 `total_cells` 中 **excel 来源**的期
 *   —— 那是 Excel 全网口径、未提供名单（`trend[].total_drillable=false`），
 *   点开必然对不上，故置灰并给出 tooltip 说明。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Segmented, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, DownOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'
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
  /**
   * 该期的 `total_cells` 能否下钻 —— **逐期不同**，不是一个全局常量：
   * ume 来源的期，分母就是明细表在该期的行数，`scope=all` 行数恰好相等；
   * excel 来源的期，total_cells 是 Excel 全网口径、未提供名单，点开必然对不上。
   */
  total_drillable?: boolean
  /** 该期 `is_bp IS NULL` 的小区数（当日/当期判不出来的行数），可下钻 */
  undecidable?: number
  bp_days?: number | null
  total_days?: number | null
  is_bp_week?: number | null
  bp_weeks?: number | null
  total_weeks?: number | null
  is_bp_month?: number | null
  /**
   * 判定为「不可判定」时的**成因**，界面必须据此给出不同的解释：
   * `incomplete` 周期未过完（等时间走完自然有结论）/
   * `insufficient_weeks` 完整周数不足（如 2026-09 只有 3 个完整周 < 口径要求的 4 个，
   * 这个月**永远**判不出来，是口径与日历错配，不是数据缺失）/ `no_data` 无数据。
   */
  verdict_reason?: string
}
type CellRow = {
  day: string
  cell_name: string
  me_id: string | null
  /* 站点名：后端按 me_id 关联主库 app.cm_cell_data 得到（实测命中 98.4%）。
   * 未命中或主库不可达时为 null —— 界面显示 —，不显示 0。 */
  site_name: string | null
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

/**
 * 「不可判定」的**成因** → 文案键。
 *
 * ⚠️ 这是这一次修复的核心：原先这个卡片对日粒度**硬编码**返回「不可判定」，
 *    对周/月则只显示一句没有信息量的「不可判定」——用户无从知道是
 *    「本周还没过完，等等就有结论」还是「这个月只有 3 个完整周，永远判不出来」。
 *    两者性质完全不同，必须分开讲（成因由后端 `trend[].verdict_reason` 给出）。
 *
 * 同样不能动态拼 key（check:i18n 会拦），一律显式分支返回字面量。
 */
function verdictReasonKey(reason: string | undefined): string {
  switch (reason) {
    case 'incomplete': return 'bp.verdict.reason.incomplete'
    case 'insufficient_weeks': return 'bp.verdict.reason.insufficientWeeks'
    case 'no_data': return 'bp.verdict.reason.noData'
    default: return 'bp.verdict.reason.generic'
  }
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
  /** 口径说明条默认**收起**（用户要求）—— 常驻会挤占首屏，收起后只留一行入口 */
  const [caliberOpen, setCaliberOpen] = useState(false)

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [drillRows, setDrillRows] = useState<CellRow[]>([])
  const [drillInfo, setDrillInfo] = useState<{ title: string
                                               excel: number | null
                                               truncated: boolean
                                               clicked: number | null
                                               scope: string }>(
    { title: '', excel: null, truncated: false, clicked: null, scope: 'bp' })
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
  /** 导出用的判定文本：界面上的判定是 Tag/Tooltip，落进 Excel 必须是可读文字。
   *  不可判定时**连同成因一起导出** —— 否则 Excel 里只剩一个「不可判定」，
   *  与用户抱怨的那句没有信息量的文案一模一样。 */
  const exportVerdict = useCallback((p: TrendPoint) => {
    if (grain === 'day') {
      const n = p.undecidable ?? 0
      return n ? t('bp.verdict.undecidableN', { n }) : t('bp.verdict.decided')
    }
    const st = grain === 'week' ? p.is_bp_week : p.is_bp_month
    if (st != null) return t(bpStateKey(st))
    const why = t(verdictReasonKey(p.verdict_reason), {
      have: fmt(grain === 'week' ? p.total_days : p.total_weeks),
      need: fmt(grain === 'week' ? 7 : 4),
    })
    return `${t('bp.state.unknown')}（${why}）`
  }, [grain, t])

  const exportTrend = useCallback(() => {
    if (!trend.length) return
    void exportAoaReport({
      filename: `bp_report_${grain}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'BP',
      title: t('bp.title'),
      header: [t('bp.col.period'), t('bp.col.bp'), t('bp.col.total'),
               t('bp.col.ratio'), t('bp.col.traffic'), t('bp.col.detail'),
               t('bp.col.state'), t('bp.col.undecidable')],
      // 最后一列导出 BP Cells List 的明细行数，便于在 Excel 里直接核对上游差异；
      // 判定列一并导出 —— 判定成因（incomplete / insufficient_weeks）在界面上
      // 是 Tooltip，导出后没有悬停，故这里落成可读文本。
      rows: trend.map(p => [
        p.period, p.bp_cells, p.total_cells, p.bp_ratio, p.traffic_tb,
        p.detail_cells ?? null, exportVerdict(p), p.undecidable ?? 0,
      ]),
      numericCols: [1, 2, 3, 4, 5, 7],
    })
  }, [trend, grain, t])

  const exportRows = useCallback((list: CellRow[], name: string) => {
    if (!list.length) return
    void exportAoaReport({
      filename: `${name}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: name,
      title: name,
      header: [t('bp.col.day'), t('bp.col.siteId'), t('bp.col.siteName'),
               t('bp.col.cell'), t('bp.col.meId'), t('bp.col.cluster'),
               t('bp.col.layer'), t('bp.col.state'), t('bp.col.prb'), t('bp.col.thr'),
               t('bp.col.au'),
               t('bp.col.ratio'), t('bp.col.dl'), t('bp.col.ul')],
      rows: list.map(r => [r.day, r.me_id, r.site_name || '', r.cell_name, r.me_id,
                           r.cluster, r.layer,
                           t(bpStateKey(r.is_bp)), r.prb_dl, r.thr_dl, r.active_user,
                           r.prb_ok, r.dl_gb, r.ul_gb]),
      // 数值列下标随新增两列后移：prb(8) thr(9) au(10) dl(13) ul(14)
      numericCols: [8, 9, 10, 13, 14],
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
                   clicked: opts.clicked ?? null, scope: opts.scope || 'all' })
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
        clicked: opts.clicked ?? null, scope: opts.scope || 'all',
      })
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setDrillLoading(false)
    }
  }, [])

  /* ---- 图表点击下钻（AGENTS.md 1b：能下钻尽下钻）----
   *
   * 图表上的柱子同样是「数字」，必须能点。ECharts 不提供 DOM 事件，走 onEvents。
   * ⚠️ 三个坑：
   *   ① 回调里的 `params.name` 是 x 轴**类目名**（周期标签），不是行索引 ——
   *      必须用它去 trend/regions 里**查**出对应记录；用 `dataIndex` 当下标取值
   *      会随 series 顺序变化而错位（ratio 系列与 trend 就不同步）。
   *   ② 同一张图上柱子与折线都会触发 click —— 只处理 `seriesType === 'bar'`，
   *      否则点折线也弹窗，「你点的是哪个数字」会含混。
   *   ③ 原生 MouseEvent 在 `params.event.event`（zrender 封装了一层），
   *      弹窗要它的 clientX/clientY 定位；拿不到时给个兜底坐标，不要抛异常。
   * 注意：本块必须放在 `openDrill` 之后 —— 它在依赖数组里，提前引用会 TDZ 报错。
   */
  const chartAnchor = (params: any) => {
    const ev = params?.event?.event
    return ev && typeof ev.clientX === 'number'
      ? { x: ev.clientX, y: ev.clientY }
      : { x: 120, y: 160 }
  }

  /** 趋势图柱子 → 该期 BP 明细（与数字卡、表格同一 WHERE） */
  const onTrendClick = useCallback((params: any) => {
    if (params?.seriesType !== 'bar' || !params?.name) return
    const pt = trend.find(p => p.period === params.name)
    if (!pt) return
    void openDrill(
      grain === 'day'
        ? { day: pt.period, scope: 'bp',
            title: `${t('bp.drill.bp')} · ${pt.period}`, clicked: pt.bp_cells }
        : { start: pt.period, end: pt.period, scope: 'bp',
            title: `${t('bp.drill.bp')} · ${pt.period}`, clicked: pt.bp_cells },
      chartAnchor(params))
  }, [trend, grain, openDrill, t])

  /** 分区图柱子 → 该分区在**当前筛选区间**内的 BP 明细。
   *  后端 `/cells` 支持 region 过滤，且与 `/regional` 用同一段时间谓词，
   *  因此下钻行数与该柱子的值一致（下钻一致性）。 */
  const onRegionClick = useCallback((params: any) => {
    if (params?.seriesType !== 'bar' || !params?.name) return
    const r = regions.find(x => x.region === params.name)
    if (!r) return
    void openDrill(
      { ...rangeParams(), region: String(params.name), scope: 'bp',
        title: `${t('bp.drill.region')} · ${params.name}`, clicked: r.bp_number },
      chartAnchor(params))
  }, [regions, openDrill, rangeParams, t])

  /* ---- 表格列 ---- */
  const columns = useMemo(() => [
    { title: t('bp.col.period'), dataIndex: 'period', width: 130 },
    {
      title: t('bp.col.bp'), dataIndex: 'bp_cells', align: 'right' as const,
      // 数字可点：落到该期的 BP 小区明细。
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
                  : { start: r.period, end: r.period, scope: 'bp',
                      title: `${t('bp.drill.bp')} · ${r.period}`,
                      clicked: r.bp_cells },
                { x: e.clientX, y: e.clientY })}>
              {v ?? '—'}
            </Button>
          )
      ),
    },
    {
      // 该期判定（周/月 是/否；日粒度给判定完成度）。
      // 加这一列是为了让**表格自己解释自己** —— 否则 W40 那行 `bp_cells=0`
      // 只能靠读者去点数字卡才知道「是还没判，不是零」。
      // 不可判定时把成因直接写在单元格里（incomplete / insufficient_weeks），
      // 而不是留给用户猜。
      title: t('bp.col.state'), dataIndex: 'is_bp_week', width: 150,
      render: (_: unknown, r: TrendPoint) => {
        if (grain === 'day') {
          const n = r.undecidable ?? 0
          return n
            ? <Tag color="warning">{t('bp.verdict.undecidableN', { n })}</Tag>
            : <Tag color="success">{t('bp.verdict.decided')}</Tag>
        }
        const st = grain === 'week' ? r.is_bp_week : r.is_bp_month
        if (st != null) return <Tag color={bpStateColor(st)}>{t(bpStateKey(st))}</Tag>
        return (
          <Tooltip title={t(verdictReasonKey(r.verdict_reason), {
            have: fmt(grain === 'week' ? r.total_days : r.total_weeks),
            need: fmt(grain === 'week' ? 7 : 4),
          })}>
            <Tag color="default" style={{ cursor: 'help' }}>
              {t('bp.state.unknown')}
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      // 不可判定小区数：日粒度是新列（周/月为区间内累加）。
      // **必须可见**：判定完成度是 BP 数字可信度的前提 —— 一个「441 个 BP」旁边
      // 若有 25 个小区判不出来，读者必须能立刻看到，而不是去猜。
      // 0 显示为「0」而不是「—」：0 在这里是有意义的确定值（全部都判出来了）。
      title: t('bp.col.undecidable'), dataIndex: 'undecidable', align: 'right' as const,
      width: 110,
      render: (v: number | undefined, r: TrendPoint) => {
        const n = v ?? 0
        if (!n) return <Text type="secondary">0</Text>
        return (
          <Button type="link" style={{ padding: 0, color: WH.warn }}
            onClick={e => void openDrill(
              grain === 'day'
                ? { day: r.period, scope: 'undecidable',
                    title: `${t('bp.drill.undecidable')} · ${r.period}`, clicked: n }
                : { start: r.period, end: r.period, scope: 'undecidable',
                    title: `${t('bp.drill.undecidable')} · ${r.period}`, clicked: n },
              { x: e.clientX, y: e.clientY })}>
            {n}
          </Button>
        )
      },
    },
    {
      title: t('bp.col.total'), dataIndex: 'total_cells', align: 'right' as const,
      // 分母**逐期**判断能否下钻（`total_drillable`，后端按 source 标注）：
      //   - ume 来源的期：分母就是明细表在该期的行数，`scope=all` 行数**恰好相等**；
      //   - excel 来源的期：total_cells 是 Excel 全网口径、未提供名单，点开必然
      //     对不上（如 09-21 展示 6093、明细只有 607 行）。
      // 原先一律不给入口，是把它当成了全局常量；实际只有 excel 期不可下钻。
      render: (v: number, r: TrendPoint) => (
        r.total_drillable === true
          ? (
            <Button type="link" style={{ padding: 0 }}
              onClick={e => void openDrill(
                grain === 'day'
                  ? { day: r.period, scope: 'all',
                      title: `${t('bp.drill.all')} · ${r.period}`, clicked: v }
                  : { start: r.period, end: r.period, scope: 'all',
                      title: `${t('bp.drill.all')} · ${r.period}`, clicked: v },
                { x: e.clientX, y: e.clientY })}>
              {v ?? '—'}
            </Button>
          )
          : (
            <Tooltip title={t('bp.tip.totalNoDrill')}>
              <span style={{ cursor: 'help', color: WH.textMuted }}>{v ?? '—'}</span>
            </Tooltip>
          )
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
    // 该数**可下钻**：后端契约里 `scope=bp` 的行数 == `detail_cells`（同一 WHERE），
    // 所以点它和点左边的 bp_cells 会得到同一批行 —— 这不是冗余，而是让
    // 「明细行数与展示值差多少」这件事本身可以点开核实。
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
            <Button type="link" style={{ padding: 0, color: d === 0 ? undefined : WH.warn }}
              onClick={e => void openDrill(
                grain === 'day'
                  ? { day: r.period, scope: 'bp',
                      title: `${t('bp.drill.bp')} · ${r.period}`, clicked: v }
                  : { start: r.period, end: r.period, scope: 'bp',
                      title: `${t('bp.drill.bp')} · ${r.period}`, clicked: v },
                { x: e.clientX, y: e.clientY })}>
              {fmt(v)}{d === 0 ? '' : ` (${d > 0 ? '+' : ''}${d})`}
            </Button>
          </Tooltip>
        )
      },
    },
  ], [t, grain, openDrill])

  const drillColumns = useMemo(() => [
    { title: t('bp.col.day'), dataIndex: 'day', width: 100 },
    // Site ID = ManagedElement ID（`me_id`）。放在小区名**之前**：站点是小区名的前缀，
    // 先站点后小区更好读；也让「同站多扇区」在视觉上连成一组。
    { title: t('bp.col.siteId'), dataIndex: 'me_id', width: 92 },
    // 站点名按 me_id 关联主库 app.cm_cell_data 得到（后端 _attach_site_names()）。
    // 实测命中 98.4%；未命中/主库不可达时为 null，按 AGENTS.md 三.6 显示 —，不显示 0。
    { title: t('bp.col.siteName'), dataIndex: 'site_name', width: 180,
      render: (v: string | null) => v || '—' },
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
    // AU 是 BP 的第三个条件，明细里必须能看到它 —— 否则用户无法核对
    // 「为什么这个小区是/不是 BP」。三态：null 显示 —，绝不显示 0。
    { title: t('bp.col.au'), dataIndex: 'active_user', align: 'right' as const,
      render: (v: number | null) => fmtNum(v) },
    { title: t('bp.col.dl'), dataIndex: 'dl_gb', align: 'right' as const,
      render: (v: number | null) => fmtNum(v, 1) },
  ], [t])

  const au = meta.active_user
  /* 周期判定值：**按粒度取对应字段**，且日粒度必须为 null。
   *
   * ⚠️ 原实现写的是 `grain === 'day' ? latest.is_bp_week : ...` —— 分支两侧都是
   *    `is_bp_week`，日粒度取的是一个**后端根本不发的字段**（实测日粒度响应里
   *    没有 `is_bp_week`，只有周/月才有）。结果是 `undefined` 而非 null，
   *    经 periodStateKey 兜底后渲染成「不可判定」——正是用户报的那个现象的另一半成因。
   *    日粒度确实没有「这一天是不是 BP 日」这种口径（BP 是小区级属性，日粒度只有计数），
   *    所以这里**就该**是 null，由 verdictValue 走「判定完成度」分支，不套是/否。
   */
  const latestIsBp = latest && grain !== 'day'
    ? (grain === 'week' ? latest.is_bp_week : latest.is_bp_month)
    : null
  /* 该期的周期判定尚未成立（周没过完 / 完整周数不足）→ `bp_cells` 后端给 0，
   * 但语义是「还没判」而不是「BP 为零」。日粒度不参与（它没有周期判定）。 */
  const latestUndecided = grain !== 'day' && latest != null && latestIsBp == null

  /* ---- 最新一期判定：三种粒度各自有**可计算**的结论，不再一律「不可判定」 ----
   *
   * ⚠️ 这里修的是一个真实的展示缺陷（2026-09-30 用户反馈「最新一期判定：不可判定，
   *    如何解决」）：原实现对 `grain === 'day'` **硬编码**返回 `bp.state.undecidable`，
   *    而日粒度恰是页面默认视图 —— 也就是说用户在默认视图下**永远**只能看到
   *    「不可判定」，无论数据多完整。
   *
   * 三种粒度各自的正确语义：
   *   day   —— umlaut 口径里**没有**「这一天是不是 BP 日」这种东西（BP 是小区级属性，
   *            日粒度只有计数）。所以硬套一个是/否是编造口径。这里改用**可计算的**
   *            判定完成度：该日有多少小区判不出来（`is_bp IS NULL`）。0 → 已判定；
   *            有 → 不可判定 N 个，且**可下钻**到那 N 行看是哪几个小区、缺什么条件。
   *   week  —— `is_bp_week`（一周 4/7 天为 BP）。NULL 时区分成因：
   *            天数不足（本周没过完，etc.）还是根本没有数据。
   *   month —— `is_bp_month`（一月 3/4 个完整周为 BP）。NULL 时区分成因：
   *            **完整周数结构性不足**（如 2026-09 只有 3 个完整周 < 口径要求的 4 个
   *            —— 这个月永远判不出来，是口径与日历错配，不是数据缺失）。
   */
  const dayUndecidable = latest?.undecidable ?? 0
  /* 日粒度**不套是/否**（没有「这一天是不是 BP 日」这种口径），只报判定完成度。
   *
   * 2026-09-30 按用户要求调整：全部判得出来时**不再显示「已判定」这个大标题**，
   * 保持「标题 + BP x / 评估 y 个小区」两行即可 —— 没有判不出来的小区时，
   * 「已判定」既无信息量又占了本行数字的位置。有判不出来的小区时仍要显式告警
   * （「不可判定 N 个」是**异常态**，必须让人一眼看到）。
   */
  const verdictValue = (() => {
    if (!latest) return t('bp.state.unknown')
    if (grain === 'day') {
      return dayUndecidable > 0
        ? t('bp.verdict.undecidableN', { n: dayUndecidable })
        : ''
    }
    return t(periodStateKey(latestIsBp))
  })()
  // 卡片配色：日粒度「全部判出来」为 ok、「有判不出来的」为 warn；
  // 周/月沿用「是该周期 → crit」的原语义。
  const verdictLevel = (() => {
    if (!latest) return 'ok' as const
    if (grain === 'day') return dayUndecidable > 0 ? 'warn' as const : 'ok' as const
    return latestIsBp === 1 ? 'crit' as const : 'ok' as const
  })()
  // 判定依据的第二行：周/月给「x/y 天」「x/y 完整周」，日给 BP/评估总数
  const verdictSub = (() => {
    if (!latest) return ''
    if (grain === 'week') {
      return t('bp.kpi.weekDetail', { a: fmt(latest.bp_days), b: fmt(latest.total_days) })
    }
    if (grain === 'month') {
      return t('bp.kpi.monthDetail', { a: fmt(latest.bp_weeks), b: fmt(latest.total_weeks) })
    }
    return t('bp.kpi.dayDetail', { a: fmt(latest.bp_cells), b: fmt(latest.total_cells) })
  })()
  // 不可判定时**必须**给出成因，否则用户只看到一句没有信息量的「不可判定」
  const verdictWhy = (() => {
    if (!latest || grain === 'day') return ''
    if (latestIsBp != null) return ''
    return t(verdictReasonKey(latest.verdict_reason), {
      have: fmt(grain === 'week' ? latest.total_days : latest.total_weeks),
      need: fmt(grain === 'week' ? 7 : 4),
    })
  })()
  // 判定卡的下钻：日粒度落到「判不出来的那 N 个小区」；周/月落到该期 BP 明细
  const openVerdictDrill = useCallback((e: React.MouseEvent) => {
    if (!latest) return
    const at = { x: e.clientX, y: e.clientY }
    if (grain === 'day') {
      if (dayUndecidable > 0) {
        void openDrill({ day: latest.period, scope: 'undecidable',
                         title: `${t('bp.drill.undecidable')} · ${latest.period}`,
                         clicked: dayUndecidable }, at)
      } else {
        // 全部判出来了：下钻到该日**全部被评估小区**（scope=all 行数 == total_cells），
        // 让用户能核对「确实每一行都有结论」，而不是给一个点不动的数字。
        void openDrill({ day: latest.period, scope: 'all',
                         title: `${t('bp.drill.all')} · ${latest.period}`,
                         clicked: latest.total_cells }, at)
      }
      return
    }
    void openDrill({ start: latest.period, end: latest.period, scope: 'bp',
                     title: `${t('bp.drill.bp')} · ${latest.period}`,
                     clicked: latest.bp_cells }, at)
  }, [latest, grain, dayUndecidable, openDrill, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 口径说明
           - 口径**不可用**时（active-user 未采集）：常驻 warning，**不允许收起** ——
             此时所有判定都偏低、结论不可比，藏起来等于让用户自己猜口径。
           - 口径**可用**时：默认**收起**，只留一行可点入口，点开展开完整说明。
             三条件按忙时值判定这件事与直觉（"日均值"）不同，需要时可查，但不必常驻占屏。 */}
      {au && !au.available && (
        <Alert
          type="warning" showIcon banner
          message={t('bp.banner.title')}
          description={au.reason || t('bp.banner.desc')}
        />
      )}
      {au && au.available && (
        caliberOpen ? (
          <Alert
            type="info" showIcon banner closable
            onClose={() => setCaliberOpen(false)}
            message={<Space size={8}>
              <span>{t('bp.banner.auOk')}</span>
              <Button type="link" size="small" style={{ padding: 0 }}
                onClick={() => setCaliberOpen(false)}>
                {t('bp.banner.collapse')}
              </Button>
            </Space>}
            description={t('bp.banner.auOkDesc', {
              thr: String(au.threshold ?? ''),
              thr2: '80%', thr3: '3' })}
          />
        ) : (
          <div>
            <Button type="link" size="small" style={{ padding: 0 }}
              icon={<InfoCircleOutlined />}
              onClick={() => setCaliberOpen(true)}>
              {t('bp.banner.auOk')}
              <DownOutlined style={{ fontSize: 10, marginLeft: 4 }} />
            </Button>
          </div>
        )
      )}

      {/* ② 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Segmented
            className="wh-seg"
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

      {/* ④ 数字卡：能下钻尽下钻（AGENTS.md 第三节 1b）—— 四张卡全部可点 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          {/* 最新一期 BP 小区数 → 该期 BP 明细（scope=bp，行数 == bp_cells）
              ⚠️ 判定未出的期（如本周还没过完的 W40）`bp_cells` 后端给 0，
                 但那是「尚未判定」而不是「BP 小区为零」—— 直接显示 0 会被读成故障。
                 AGENTS.md 第三节 6：取不到值必须显示 `—`，不得显示成 0。
                 故这里显式区分：`is_bp_week/month` 为 NULL 的期显示 `—` +
                 该期实际已有的明细行数，点进去仍是真实数据。
              2026-09-30 按用户要求改版：卡片上**不再挂日期**，改为「数值 + 占比」两行。
                 日期本就由趋势表与下钻弹窗标题给出，挂在数字旁既挤位又让卡片宽度跳动。 */}
          <div onClick={e => latest && void openDrill(
            { day: grain === 'day' ? latest.period : '',
              start: grain === 'day' ? '' : latest.period,
              end: grain === 'day' ? '' : latest.period, scope: 'bp',
              title: `${t('bp.drill.bp')} · ${latest.period}`, clicked: latest.bp_cells },
            { x: e.clientX, y: e.clientY })}
            style={{ cursor: latest ? 'pointer' : 'default' }}>
            <StatCard title={t('bp.kpi.latestBp')}
              value={latestUndecided ? '—' : (latest?.bp_cells ?? '—')} />
            {latestUndecided ? (
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('bp.kpi.pendingPeriod', { n: fmt(latest?.detail_cells) })}
              </Text>
            ) : latest && (
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('bp.kpi.latestBpRatio', { p: fmtPct(latest.bp_ratio as number) })}
              </Text>
            )}
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          {/* 期数：数字本身就是「本区间有几个周期」，下钻落到**趋势明细表**——
              它不是小区级指标，没有对应的 cell 行；点开后滚动到明细表并高亮，
              比给一个点不动的数字有信息量。 */}
          <div onClick={() => {
            const el = document.getElementById('bp-trend-table')
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }} style={{ cursor: 'pointer' }}>
            <StatCard title={t('bp.kpi.periods')} value={summary.periods ?? 0} />
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          {/* 平均 BP 占比 → 本区间**全部** BP 小区的明细（scope=bp），
              行数与趋势表各期 detail_cells 之和一致（同一 WHERE，后端已声明）。 */}
          <div onClick={e => void openDrill(
            { ...rangeParams(), scope: 'bp',
              title: `${t('bp.drill.bpRange')} · ${summary.periods ?? 0}`,
              clicked: summary.bp_cells ?? null },
            { x: e.clientX, y: e.clientY })}
            style={{ cursor: 'pointer' }}>
            <StatCard title={t('bp.kpi.avgRatio')} value={fmtPct(summary.avg_ratio as number)} />
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          {/* 最新一期判定 —— **可点下钻**，且三种粒度各有可计算的结论（见上面的推导）。
              三态原则：不可判定与「否」必须区分（AGENTS.md 原则 6）。
              不可判定时**必须给出成因**（本周没过完 / 完整周数结构性不足），
              否则用户只看到一句没有信息量的「不可判定」—— 这正是本次修复的起因。
              日粒度且全部判得出来时 `verdictValue` 为空串，此时**整行大标题不渲染**，
              卡片保持「标题 + BP x / 评估 y 个小区」两行（2026-09-30 按用户要求）。 */}
          <div onClick={openVerdictDrill}
            style={{ cursor: latest ? 'pointer' : 'default' }}>
            <CardBase level={verdictLevel}
              title={t('bp.kpi.latestState')} as="div">
              {verdictValue !== '' && (
                <Text strong style={{ fontSize: 20 }}>{verdictValue}</Text>
              )}
              {latest && (
                <div style={{
                  fontSize: verdictValue === '' ? 20 : 12,
                  fontWeight: verdictValue === '' ? 600 : undefined,
                  color: verdictValue === '' ? WH.text : WH.textMuted,
                  marginTop: verdictValue === '' ? 0 : 4,
                }}>
                  {verdictSub}
                </div>
              )}
              {verdictWhy && (
                <div style={{ fontSize: 12, color: WH.warn, marginTop: 2 }}>
                  {verdictWhy}
                </div>
              )}
            </CardBase>
          </div>
        </Col>
      </Row>

      {/* ⑤ 趋势图：柱子可点 → 该期 BP 明细（与数字卡、表格同一 WHERE） */}
      <CardBase title={t('bp.chart.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('bp.chart.hint')}</Text>}>
        {trend.length
          ? <ReactECharts option={chartOption} style={{ height: 340 }} notMerge
              onEvents={{ click: onTrendClick }} />
          : <Empty description={t('bp.empty')} />}
      </CardBase>

      {/* ⑥ 分区 + 分层 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <CardBase title={t('bp.region.title')}>
            {regions.length
              ? <ReactECharts option={regionOption} style={{ height: 300 }} notMerge
                  onEvents={{ click: onRegionClick }} />
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
                  // 分母**不做**下钻 —— 实测该数与本页下钻端点在混合区间下对不上：
                  // `bp_layer_daily.total_cell` 是「按天 × 层 × 区」的累加，而 Excel
                  // 来源的天（2026-09-21 及更早）在明细表里**只有 BP 小区**，
                  // 两者的 population 不同。实测（09-20..09-29，含 2 个 excel 天）：
                  // 6 个层里只有 2 个能对上；改为仅 ume 天（09-22..09-29）则 6/6 全对。
                  // 结论：该列在混合区间下不可下钻，与其给一个点开必然对不上的入口，
                  // 不如置灰并说明（AGENTS.md 1b：下钻 WHERE 必须与概览一致）。
                  { title: t('bp.col.total'), dataIndex: 'total_cell', align: 'right' as const,
                    render: (v: number) => (
                      <Tooltip title={t('bp.tip.layerTotalNoDrill')}>
                        <span style={{ cursor: 'help', color: WH.textMuted }}>{v}</span>
                      </Tooltip>
                    ) },
                ]}
              />
            ) : <Empty description={t('bp.empty')} />}
          </CardBase>
        </Col>
      </Row>

      {/* ⑦ 明细表 —— id 供「期数」卡片滚动定位（它不是小区级指标，没有下钻行） */}
      <CardBase title={t('bp.table.title')} interactive={false}>
        <div id="bp-trend-table">
          <Table
            rowKey="period"
            columns={columns}
            dataSource={trend}
            loading={loading}
            pagination={{ pageSize: 12, showSizeChanger: true }}
            scroll={{ x: 860 }}
            size="small"
          />
        </div>
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
            {t('bp.caliber.verdictRule')}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.drillRule')}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bp.caliber.importAt', { v: fmt(meta.last_import_at) })}
          </Text>
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
              不是查询 bug —— 这里必须显式对照，不能让用户以为点 463 看到的就该是 463 行。
              ⚠️ 但「你点的是」的**口径后缀**只在 Excel 汇总口径下才成立：
                 - scope=bp   → 展示值取自 Excel Overall 汇总，确实可能 ≠ 明细行数；
                 - scope=all  → 分母就是明细行数（ume 来源的期），两者**必须相等**，
                                写「Excel Overall 汇总口径」会误导；
                 - scope=undecidable → 本来就是明细行数，同理。 */}
          {drillInfo.clicked != null && (
            <Tag color="blue">
              {drillInfo.scope === 'bp'
                ? t('bp.drill.clicked', { n: drillInfo.clicked })
                : t('bp.drill.clickedScope', { n: drillInfo.clicked })}
            </Tag>
          )}
          <Tag color="red">{t('bp.drill.count', { n: drillRows.length })}</Tag>
          {drillInfo.excel != null && drillInfo.clicked != null
            && drillInfo.scope === 'bp' && (
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
