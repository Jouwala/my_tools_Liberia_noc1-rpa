/* ============================================================================
 * Meta 基准报告（ORANGE vs MTN 速率 PK + FDD 网络侧 KPI）—— `?page=bm_meta`
 * ----------------------------------------------------------------------------
 * 数据源：`meta_data`（Meta_20260923.xlsx 导入，612 行，2025-01-18 ~ 2026-09-23）。
 * 口径的唯一真相源是 `backend/services/bm_meta_caliber.py`，本页**不含任何业务口径**。
 *
 * ⚠️ 与 `bm_speedtest` 是**两张不同的表、两套口径**，不要合并：
 *   · speedtest_data —— 实测网速，有 provider 列，靠 LIKE 归一成两家；
 *   · meta_data      —— Meta 口径竞对基准，两家各占一个固定列（orange_liberia /
 *                       mtn_liberia），且**同时含 7 个网络侧 KPI**。
 *
 * 页面分两个层次（这是本页与 bm_speedtest 最大的结构差异）：
 *   ① 两家 PK 层：只有「速率」一个指标——综合评分、汇总卡、双线趋势、逐日胜负、
 *      月度对比、逐日明细表。**只有这一层有胜负概念**。
 *   ② 网络侧 KPI 层：bp / FDD 下行吞吐 / DL·UL PRB 利用率 / 流量 / RRC 用户数，
 *      只做汇总卡与趋势曲线。它们**不属于任何一家**，因此不参与 PK、不打分
 *      —— 把「Orange 比 MTN 快多少」和「全网 PRB 利用率多高」混进同一个评分
 *      会得出假结论（口径模块 docstring 有完整理由）。
 *
 * 本页遵循 AGENTS.md 第三节 1b「能下钻尽下钻」：**每个数字都可点**并落到明细。
 * 下钻口径与概览完全一致（后端共用同一份 WHERE），故「卡片上的 314 天」
 * 与「点开后 314 行」严格相等。
 *
 * ⚠️ 图表取色分两层：DOM 用 WH（CSS 变量），ECharts 用 useTheme() 的 DARK/LIGHT 实值
 * （canvas 解析不了 CSS 变量）。本文件里的 `#ff922b` / `#0d9488` 等均为**图表实值**。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Segmented, Select, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, TrophyFilled } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { WH, useTheme, cardStyle, axisLabel, axisLine, darkTooltip, splitLine } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportReport } from '../utils/excelReport'
import type { CellValue } from '../utils/excelReport'
import { getBmMetaOverview, getBmMetaTrend, getBmMetaDrilldown } from '../api'

const { Text } = Typography

/* ---- 类型（与后端返回结构对齐） ---- */

type BrandKey = 'ORANGE' | 'MTN'
type GroupKey = 'brand' | 'network'
/** 全部可下钻指标的 key（后端 all_metrics() 的键集，顺序与筛选器一致） */
type MetricKey =
  | 'speed' | 'bp' | 'dl_throughput' | 'dl_prb' | 'ul_prb' | 'traffic' | 'rrc_users'

interface KpiCell { value: number | null; min: number | null; max: number | null }

interface DailyRow {
  day: string
  orange_speed: number | null; mtn_speed: number | null
  winner: BrandKey | null
  bp: number | null; dl_throughput: number | null
  dl_prb: number | null; ul_prb: number | null
  traffic: number | null; rrc_users: number | null
}

interface MonthRow extends Omit<DailyRow, 'day' | 'winner'> {
  ym: string; days: number
  orange_wins: number; mtn_wins: number
  winner: BrandKey | null
}

interface BrandSummary {
  brand: BrandKey; label: string; days: number
  speed: number | null; speed_min: number | null; speed_max: number | null
}

interface WinStats {
  total_days: number; paired_days: number; ties: number
  orange_wins: number; mtn_wins: number
  orange_win_rate: number | null; mtn_win_rate: number | null
}

interface Overview {
  meta: {
    start: string; end: string; brands: BrandKey[]; row_count: number
    data_min_date: string | null; data_max_date: string | null
    daily_total: number; daily_returned: number; daily_truncated: boolean
    warnings: string[]
  }
  filters: {
    min_date: string | null; max_date: string | null; row_count: number
    brands: { key: BrandKey; label: string }[]
    metrics: { key: MetricKey; kind: 'higher' | 'lower'; unit: string; group: GroupKey }[]
  }
  summary: Record<BrandKey, BrandSummary> & { network: { days: number } & Record<string, any> }
  scores: Record<BrandKey, { score: number | null; parts: Record<string, number> }>
  score_weights: Record<string, number>
  daily: DailyRow[]
  monthly: MonthRow[]
  wins: WinStats
}

interface TrendPoint {
  day: string
  orange: number | null; mtn: number | null
  orange_ma: number | null; mtn_ma: number | null
  value: number | null; value_ma: number | null
  winner: BrandKey | null
}

interface DetailRow {
  day: string
  orange_speed: number | null; mtn_speed: number | null
  winner: BrandKey | null; winner_label: string | null; gap: number | null
  bp: number | null; dl_throughput: number | null
  dl_prb: number | null; ul_prb: number | null
  traffic: number | null; rrc_users: number | null
  source_file: string; source_sheet: string; import_time: string
}

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 第六节第 6 条：取不到显示 —，不得显示 0） */
const fmt = (v: unknown) => (v == null || v === '' ? '—' : String(v))

/** 数值格式化：保留位数由调用方给，空值仍是 — */
function num(v: unknown, nd = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(nd) : '—'
}

/** 大数字带千分位（流量 GB / 用户数），空值仍是 — */
function numGrouped(v: unknown, nd = 0): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: nd, maximumFractionDigits: nd })
}

/** 按后端给的 unit 决定展示形式：ratio 已是百分数、count/GB 带千分位、其余保留 2 位 */
function fmtByUnit(v: number | null | undefined, unit: string, nd = 2): string {
  if (v == null) return '—'
  if (unit === 'ratio') return `${num(v, nd)}%`
  if (unit === 'Mbps') return `${num(v, nd)} Mbps`
  if (unit === 'GB') return `${numGrouped(v, 0)} GB`
  if (unit === 'count') return numGrouped(v, 0)
  return num(v, nd)
}

/** 两家 PK 指标只有 speed —— 显式 switch，不拼字符串（拼键会被 check:i18n 拦下） */
function metricLabelKey(m: MetricKey): string {
  switch (m) {
    case 'speed': return 'bmm.metric.speed'
    case 'bp': return 'bmm.metric.bp'
    case 'dl_throughput': return 'bmm.metric.dlThroughput'
    case 'dl_prb': return 'bmm.metric.dlPrb'
    case 'ul_prb': return 'bmm.metric.ulPrb'
    case 'traffic': return 'bmm.metric.traffic'
    case 'rrc_users': return 'bmm.metric.rrcUsers'
  }
}

/** 指标说明键（鼠标悬停看口径），与上面的 label 一一对应 */
function metricHintKey(m: MetricKey): string {
  switch (m) {
    case 'speed': return 'bmm.hint.speed'
    case 'bp': return 'bmm.hint.bp'
    case 'dl_throughput': return 'bmm.hint.dlThroughput'
    case 'dl_prb': return 'bmm.hint.dlPrb'
    case 'ul_prb': return 'bmm.hint.ulPrb'
    case 'traffic': return 'bmm.hint.traffic'
    case 'rrc_users': return 'bmm.hint.rrcUsers'
  }
}

/** 品牌 i18n 键：同样显式 switch */
function brandLabelKey(b: BrandKey): string {
  switch (b) {
    case 'ORANGE': return 'bmm.brand.orange'
    case 'MTN': return 'bmm.brand.mtn'
  }
}

/** 品牌固定色（图表实值）：ORANGE 用橙、MTN 用青蓝，深浅主题各一套保证对比度 */
function brandColor(b: BrandKey, isDark: boolean): string {
  if (b === 'ORANGE') return isDark ? '#ff922b' : '#ea580c'
  return isDark ? '#00d9ff' : '#0d9488'
}

/** 网络侧 KPI 只有一条线，用中性色，避免被误读成"第三家运营商" */
function networkColor(isDark: boolean): string {
  return isDark ? '#7dd3fc' : '#0369a1'
}

/** 网络侧 KPI 的 key 子集 —— 与 MetricKey 区分开，才能安全地索引 DailyRow/MonthRow */
type NetworkKey = Exclude<MetricKey, 'speed'>

/** 网络侧 KPI 的展示顺序（与后端 NETWORK_METRICS 一致） */
const NETWORK_KEYS: NetworkKey[] = ['bp', 'dl_throughput', 'dl_prb', 'ul_prb', 'traffic', 'rrc_users']

export default function BmMeta() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 筛选条件：只有时间维度（本表没有运营商/区域等可取值的维度列） ---- */
  const [start, setStart] = useState<Dayjs | null>(null)
  const [end, setEnd] = useState<Dayjs | null>(null)
  const [quick, setQuick] = useState<string>('365')

  /* ---- 数据与状态 ---- */
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /* ---- 趋势区：当前指标 + 滚动均值窗口 ---- */
  const [metric, setMetric] = useState<MetricKey>('speed')
  const [maWindow, setMaWindow] = useState<number>(7)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [trendLoading, setTrendLoading] = useState(false)

  /* ---- 口径说明默认收起：这段是解释性文字，占屏高，首次进入不展开 ---- */
  const [scopeOpen, setScopeOpen] = useState(false)

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillTitle, setDrillTitle] = useState('')
  const [drillRows, setDrillRows] = useState<DetailRow[]>([])
  const [drillMeta, setDrillMeta] = useState<Record<string, unknown> | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)

  /* ---- 首次加载：先用后端给的默认窗口（近 365 天）对齐日期选择器 ---- */
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const r = await getBmMetaOverview({})
        if (!alive) return
        const m = r.data?.meta
        if (m?.start) setStart(dayjs(m.start))
        // 后端 end 是"次日"（左闭右开），界面展示成闭区间要减一天
        if (m?.end) setEnd(dayjs(m.end).subtract(1, 'day'))
        setData(r.data)
      } catch (e: any) {
        if (alive) setError(e?.message || String(e))
      }
    })()
    return () => { alive = false }
  }, [])

  /* ---- 取数：区间用「左闭右开」，end 传次日，与后端口径一致 ----
   *
   * ⚠️ 这里是「所有区块跟着时间范围一起变」的**唯一入口**。
   * 概览接口一次返回 summary / scores / daily / monthly / wins / network，
   * 所以只要本函数被触发，页面上每个区块都会同步换数。
   * 触发它的只有 `start` / `end` 两个状态（见下面的 load 依赖），
   * 因此**任何改变时间范围的交互都只能通过 setStart/setEnd**，
   * 不要另建一套「重新取数」的旁路，否则必然出现「改了日期但部分区块没变」。
   */
  const load = useCallback(async () => {
    if (!start || !end) return
    setLoading(true)
    setError('')
    try {
      const r = await getBmMetaOverview({
        start: start.format('YYYY-MM-DD'),
        end: end.add(1, 'day').format('YYYY-MM-DD'),
      })
      setData(r.data)
      if (r.data?.meta?.warnings?.length) setError(r.data.meta.warnings.join('；'))
    } catch (e: any) {
      setError(e?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [start, end])

  useEffect(() => { void load() }, [load])

  /* ---- 趋势：指标或窗口变化时单独取（与概览解耦，切指标不重拉整页） ---- */
  useEffect(() => {
    if (!start || !end) return
    let alive = true
    setTrendLoading(true)
    void (async () => {
      try {
        const r = await getBmMetaTrend({
          start: start.format('YYYY-MM-DD'),
          end: end.add(1, 'day').format('YYYY-MM-DD'),
          metric, window: maWindow,
        })
        if (alive) setTrend(r.data?.points || [])
      } catch {
        if (alive) setTrend([])   // 趋势失败不阻塞页面主体，图表区显示空态
      } finally {
        if (alive) setTrendLoading(false)
      }
    })()
    return () => { alive = false }
  }, [start, end, metric, maWindow])

  /* ---- 快捷时间窗 ----
   *
   * ⚠️ 右边界取**数据实际最大日期**，不是 `dayjs()`（今天）。
   * 本表最新只到 2026-09-23，若用今天做右边界，三种快捷窗的右端会完全相同、
   * 只有左端在动，用户会觉得「点了 90 天和 180 天没区别」。
   * 快照日与数据日之间只要有一天滞后，这个偏差就会一直存在。
   */
  const applyQuick = useCallback((v: string) => {
    setQuick(v)
    // 数据实际最大日期（后端 filters.max_date）；还没取到数据时退回今天
    const anchor = data?.filters?.max_date ? dayjs(data.filters.max_date) : dayjs()
    if (v === 'all') {
      if (data?.filters?.min_date) setStart(dayjs(data.filters.min_date))
      setEnd(anchor)
      return
    }
    const n = Number(v)
    if (Number.isFinite(n) && n > 0) {
      setEnd(anchor)
      setStart(anchor.subtract(n - 1, 'day'))
    }
  }, [data])

  /* ---- 手动改日期时清掉快捷窗高亮 ----
   * 否则用户手改了日期，分段控件仍高亮「近 365 天」，与实际窗口不一致。
   * 传 null 是「改为自定义」；只有真正与某个快捷窗重合时才由 applyQuick 设值。
   */
  const onPickStart = useCallback((v: Dayjs | null) => {
    setQuick('custom')
    setStart(v)
  }, [])
  const onPickEnd = useCallback((v: Dayjs | null) => {
    setQuick('custom')
    setEnd(v)
  }, [])

  const summary = data?.summary
  const wins = data?.wins
  const scores = data?.scores

  /** 当前指标的元信息（小组 / 单位 / 方向），驱动图例与格式化的分支 */
  const metricMeta = useMemo(() => {
    const m = data?.filters?.metrics?.find(x => x.key === metric)
    return m || { key: metric, kind: 'higher' as const, unit: 'Mbps', group: 'brand' as GroupKey }
  }, [data, metric])
  const isBrandMetric = metricMeta.group === 'brand'

  /* ---- 综合结论：谁在总分上更强（评分相等或无数据时不下结论） ---- */
  const verdict = useMemo(() => {
    const o = scores?.ORANGE?.score
    const m = scores?.MTN?.score
    if (o == null || m == null) return null
    if (o === m) return { brand: null as BrandKey | null, diff: 0 }
    return { brand: (o > m ? 'ORANGE' : 'MTN') as BrandKey, diff: Math.abs(o - m) }
  }, [scores])

  /* ---- 速率领先方（汇总卡染色与文字结论） ---- */
  const speedLeader = useMemo<BrandKey | null>(() => {
    const a = summary?.ORANGE?.speed
    const b = summary?.MTN?.speed
    if (a == null || b == null || a === b) return null
    return a > b ? 'ORANGE' : 'MTN'
  }, [summary])

  /* ---- 下钻统一入口：所有可点数字都走它 ---- */
  const openDrill = useCallback(async (
    o: { metric?: MetricKey; day?: string; winner?: BrandKey | '' },
    title: string,
    ev?: { clientX: number; clientY: number },
  ) => {
    setAnchor(ev ? { x: ev.clientX, y: ev.clientY } : null)
    setDrillTitle(title)
    setOpen(true)
    setDrillLoading(true)
    setDrillRows([])
    try {
      const r = await getBmMetaDrilldown({
        metric: o.metric || 'speed',
        day: o.day || '',
        winner: o.winner || '',
        limit: 3000,
        ...(start && end ? {
          start: start.format('YYYY-MM-DD'),
          end: end.add(1, 'day').format('YYYY-MM-DD'),
        } : {}),
      })
      setDrillRows(r.data?.rows || [])
      setDrillMeta(r.data?.meta || null)
    } catch (e: any) {
      setDrillMeta({ warnings: [e?.message || String(e)] })
    } finally {
      setDrillLoading(false)
    }
  }, [start, end])

  /* ---- 趋势图配置 ---- */
  const trendOption = useMemo(() => {
    const days = trend.map(p => p.day.slice(5))
    const unit = metricMeta.unit
    const fmtV = (v: unknown) => (v == null ? '—' : fmtByUnit(Number(v), unit, 1))

    if (isBrandMetric) {
      return {
        tooltip: { trigger: 'axis', ...darkTooltip(isDark), valueFormatter: fmtV },
        legend: {
          data: [t('bmm.brand.orange'), t('bmm.brand.mtn'), t('bmm.legend.maOrange'), t('bmm.legend.maMtn')],
          textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 11 },
          top: 0,
        },
        grid: { left: 52, right: 20, top: 34, bottom: 42 },
        xAxis: { type: 'category', data: days, ...axisLabel(isDark), ...axisLine(isDark) },
        yAxis: {
          type: 'value', name: unit, ...axisLabel(isDark), ...axisLine(isDark),
          splitLine: splitLine(isDark),
        },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 6 }],
        series: [
          {
            name: t('bmm.brand.orange'), type: 'line', smooth: true, showSymbol: false,
            data: trend.map(p => p.orange),
            lineStyle: { width: 2, color: brandColor('ORANGE', isDark) },
            itemStyle: { color: brandColor('ORANGE', isDark) },
          },
          {
            name: t('bmm.brand.mtn'), type: 'line', smooth: true, showSymbol: false,
            data: trend.map(p => p.mtn),
            lineStyle: { width: 2, color: brandColor('MTN', isDark) },
            itemStyle: { color: brandColor('MTN', isDark) },
          },
          {
            name: t('bmm.legend.maOrange'), type: 'line', smooth: true, showSymbol: false,
            data: trend.map(p => p.orange_ma),
            lineStyle: { width: 1.5, type: 'dashed', color: brandColor('ORANGE', isDark), opacity: 0.7 },
            itemStyle: { color: brandColor('ORANGE', isDark) },
          },
          {
            name: t('bmm.legend.maMtn'), type: 'line', smooth: true, showSymbol: false,
            data: trend.map(p => p.mtn_ma),
            lineStyle: { width: 1.5, type: 'dashed', color: brandColor('MTN', isDark), opacity: 0.7 },
            itemStyle: { color: brandColor('MTN', isDark) },
          },
        ],
      }
    }

    // 网络侧 KPI：单线 + 滚动均值，**没有胜者**，所以图例也不出现运营商名
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark), valueFormatter: fmtV },
      legend: {
        data: [t(metricLabelKey(metric)), t('bmm.legend.ma')],
        textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 11 },
        top: 0,
      },
      grid: { left: 62, right: 20, top: 34, bottom: 42 },
      xAxis: { type: 'category', data: days, ...axisLabel(isDark), ...axisLine(isDark) },
      yAxis: {
        type: 'value', name: unit, ...axisLabel(isDark), ...axisLine(isDark),
        splitLine: splitLine(isDark),
      },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 6 }],
      series: [
        {
          name: t(metricLabelKey(metric)), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.value),
          lineStyle: { width: 2, color: networkColor(isDark) },
          itemStyle: { color: networkColor(isDark) },
        },
        {
          name: t('bmm.legend.ma'), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.value_ma),
          lineStyle: { width: 1.5, type: 'dashed', color: networkColor(isDark), opacity: 0.7 },
          itemStyle: { color: networkColor(isDark) },
        },
      ],
    }
  }, [trend, isDark, t, metric, metricMeta])

  /* ---- 导出：汇总 + 月度 + 逐日，三张 sheet 一次导出（统一走 utils/excelReport） ---- */
  const exportAll = useCallback(() => {
    if (!data) return
    const net = data.summary.network
    const unitOf = (k: MetricKey) => data.filters.metrics.find(x => x.key === k)?.unit || ''
    const netCols = NETWORK_KEYS.map(k => t(metricLabelKey(k)))

    // sheet 1：汇总（两家 PK + 网络侧 KPI 两组分开列，避免被读成同一件事）
    const summaryHeader = [t('bmm.col.item'), t('bmm.col.avg'), t('bmm.col.min'), t('bmm.col.max'), t('bmm.col.leader')]
    const summaryRows: CellValue[][] = [
      [`【${t('bmm.sec.pk')}】`, '', '', '', ''],
      [t('bmm.metric.speed'),
        num(data.summary.ORANGE?.speed), num(data.summary.ORANGE?.speed_min), num(data.summary.ORANGE?.speed_max),
        t('bmm.brand.orange')],
      [t('bmm.metric.speed'),
        num(data.summary.MTN?.speed), num(data.summary.MTN?.speed_min), num(data.summary.MTN?.speed_max),
        t('bmm.brand.mtn')],
      [t('bmm.col.winDays'), '', '', '', ''],
      [t('bmm.brand.orange'), data.wins.orange_wins, '', '', `${num(data.wins.orange_win_rate, 1)}%`],
      [t('bmm.brand.mtn'), data.wins.mtn_wins, '', '', `${num(data.wins.mtn_win_rate, 1)}%`],
      [t('bmm.col.ties'), data.wins.ties, '', '', ''],
      [`【${t('bmm.sec.network')}】`, '', '', '', ''],
      ...NETWORK_KEYS.map(k => [
        t(metricLabelKey(k)),
        fmtByUnit(net[k], unitOf(k)), fmtByUnit(net[`${k}_min`], unitOf(k)),
        fmtByUnit(net[`${k}_max`], unitOf(k)),
        t(metricHintKey(k)),
      ]),
    ]

    const monthRows: CellValue[][] = data.monthly.map(m => [
      m.ym, num(m.orange_speed), num(m.mtn_speed),
      m.winner ? t(brandLabelKey(m.winner)) : t('bmm.col.tie'),
      m.days, m.orange_wins, m.mtn_wins,
      ...NETWORK_KEYS.map(k => fmtByUnit(m[k] as number | null, unitOf(k))),
    ])

    const dailyRows: CellValue[][] = data.daily.map(d => [
      d.day, num(d.orange_speed), num(d.mtn_speed),
      d.winner ? t(brandLabelKey(d.winner)) : t('bmm.col.tie'),
      ...NETWORK_KEYS.map(k => fmtByUnit(d[k] as number | null, unitOf(k))),
    ])

    void exportReport([
      {
        name: t('bmm.sheet.summary'), title: t('bmm.export.title'),
        subtitle: `${data.meta.start} ~ ${dayjs(data.meta.end).subtract(1, 'day').format('YYYY-MM-DD')}`,
        header: summaryHeader, rows: summaryRows, numericCols: [1, 2, 3],
      },
      {
        name: t('bmm.sheet.monthly'), title: t('bmm.card.monthly'),
        header: [t('bmm.col.month'), t('bmm.brand.orange'), t('bmm.brand.mtn'), t('bmm.col.leader'),
          t('bmm.col.days'), t('bmm.col.winsO'), t('bmm.col.winsM'), ...netCols],
        rows: monthRows, numericCols: [1, 2, 4, 5, 6],
      },
      {
        name: t('bmm.sheet.daily'), title: t('bmm.card.daily'),
        header: [t('bmm.col.day'), t('bmm.brand.orange'), t('bmm.brand.mtn'), t('bmm.col.leader'), ...netCols],
        rows: dailyRows, numericCols: [1, 2],
      },
    ], `Meta_Benchmark_Report_${data.meta.start}_${data.meta.end}`)
  }, [data, t])

  /* ---- 下钻表格列（明细行的每个字段都可读；数值按单位格式化） ---- */
  const drillColumns = useMemo(() => {
    const unitOf = (k: MetricKey) => data?.filters.metrics.find(x => x.key === k)?.unit || ''
    return [
      { title: t('bmm.col.day'), dataIndex: 'day', key: 'day', width: 108, fixed: 'left' as const },
      {
        title: t('bmm.brand.orange'), dataIndex: 'orange_speed', key: 'orange_speed', width: 108,
        render: (v: number) => num(v),
      },
      {
        title: t('bmm.brand.mtn'), dataIndex: 'mtn_speed', key: 'mtn_speed', width: 108,
        render: (v: number) => num(v),
      },
      {
        title: t('bmm.col.gap'), dataIndex: 'gap', key: 'gap', width: 96,
        render: (v: number) => (v == null ? '—' : `${v > 0 ? '+' : ''}${num(v)}`),
      },
      {
        title: t('bmm.col.leader'), dataIndex: 'winner', key: 'winner', width: 96,
        render: (v: BrandKey | null) => (v
          ? <Tag color={v === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(v))}</Tag>
          : <Text type="secondary">{t('bmm.col.tie')}</Text>),
      },
      ...NETWORK_KEYS.map(k => ({
        title: t(metricLabelKey(k)), dataIndex: k, key: k, width: 116,
        render: (v: number) => fmtByUnit(v, unitOf(k)),
      })),
      { title: t('bmm.col.source'), dataIndex: 'source_sheet', key: 'source_sheet', width: 200, ellipsis: true },
    ]
  }, [t, data])

  /* ---- 主表格列：逐日（两家 + 网络侧 KPI），每格可点下钻 ---- */
  const dailyColumns = useMemo(() => {
    const unitOf = (k: MetricKey) => data?.filters.metrics.find(x => x.key === k)?.unit || ''
    const click = (metricKey: MetricKey, day: string, e: React.MouseEvent) =>
      void openDrill({ metric: metricKey, day }, `${t(metricLabelKey(metricKey))} · ${day}`, e)
    return [
      { title: t('bmm.col.day'), dataIndex: 'day', key: 'day', width: 104, fixed: 'left' as const },
      {
        title: t('bmm.metric.speed'), key: 'speed', width: 190,
        render: (_: unknown, r: DailyRow) => (
          <Space size={4}>
            <a onClick={(e) => click('speed', r.day, e)}>{num(r.orange_speed)}</a>
            <Text type="secondary">/</Text>
            <a onClick={(e) => click('speed', r.day, e)}>{num(r.mtn_speed)}</a>
          </Space>
        ),
      },
      {
        title: t('bmm.col.leader'), dataIndex: 'winner', key: 'winner', width: 96,
        render: (v: BrandKey | null) => (v
          ? <Tag color={v === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(v))}</Tag>
          : <Text type="secondary">{t('bmm.col.tie')}</Text>),
      },
      ...NETWORK_KEYS.map(k => ({
        title: t(metricLabelKey(k)), dataIndex: k, key: k, width: 120,
        render: (v: number, r: DailyRow) => (
          <a onClick={(e) => click(k, r.day, e)}>{fmtByUnit(v, unitOf(k))}</a>
        ),
      })),
    ]
  }, [t, data, openDrill])

  const monthColumns = useMemo(() => {
    const unitOf = (k: MetricKey) => data?.filters.metrics.find(x => x.key === k)?.unit || ''
    return [
      { title: t('bmm.col.month'), dataIndex: 'ym', key: 'ym', width: 100, fixed: 'left' as const },
      {
        title: t('bmm.metric.speed'), key: 'speed', width: 190,
        render: (_: unknown, r: MonthRow) => (
          <Space size={4}>
            <a onClick={(e) => void openDrill({ metric: 'speed' }, `${r.ym} · ${t('bmm.metric.speed')}`, e)}>
              {num(r.orange_speed)}
            </a>
            <Text type="secondary">/</Text>
            <a onClick={(e) => void openDrill({ metric: 'speed' }, `${r.ym} · ${t('bmm.metric.speed')}`, e)}>
              {num(r.mtn_speed)}
            </a>
          </Space>
        ),
      },
      {
        title: t('bmm.col.leader'), dataIndex: 'winner', key: 'winner', width: 96,
        render: (v: BrandKey | null) => (v
          ? <Tag color={v === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(v))}</Tag>
          : <Text type="secondary">{t('bmm.col.tie')}</Text>),
      },
      {
        title: t('bmm.col.winsDetail'), key: 'wins', width: 150,
        render: (_: unknown, r: MonthRow) => (
          <Text>
            <span style={{ color: brandColor('ORANGE', isDark) }}>{r.orange_wins}</span>
            <Text type="secondary"> / </Text>
            <span style={{ color: brandColor('MTN', isDark) }}>{r.mtn_wins}</span>
          </Text>
        ),
      },
      ...NETWORK_KEYS.map(k => ({
        title: t(metricLabelKey(k)), dataIndex: k, key: k, width: 120,
        render: (v: number) => (
          <a onClick={(e) => void openDrill({ metric: k }, `${t(metricLabelKey(k))}`, e)}>
            {fmtByUnit(v, unitOf(k))}
          </a>
        ),
      })),
    ]
  }, [t, data, openDrill, isDark])

  return (
    <div style={{ padding: 16 }}>
      {/* 口径提示：本表同时含两家 PK 与网络侧 KPI，两组含义不同，必须说清。
          默认**收起**（只留一行标题可点），避免每次进页面先占掉一整屏；
          内容仍然可查，点标题展开。 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={
          <span
            onClick={() => setScopeOpen(v => !v)}
            style={{ cursor: 'pointer', userSelect: 'none' }}
          >
            {t('bmm.banner.title')}
            <a style={{ marginLeft: 8, fontSize: 12 }}>
              {scopeOpen ? t('bmm.banner.collapse') : t('bmm.banner.expand')}
            </a>
          </span>
        }
        description={scopeOpen ? (
          <div style={{ fontSize: 12, lineHeight: 1.7 }}>
            <div>{t('bmm.banner.pk')}</div>
            <div>{t('bmm.banner.network')}</div>
            <div>{t('bmm.banner.relative')}</div>
          </div>
        ) : null}
      />

      {error && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={error}
          closable onClose={() => setError('')} />
      )}

      {/* 筛选条：只有时间维度 */}
      <CardBase level="default" style={{ marginBottom: 12 }}>
        <Space wrap size={12} align="center">
          <Text strong>{t('bmm.filter.range')}</Text>
          <DatePicker value={start} onChange={onPickStart} allowClear={false} />
          <Text type="secondary">~</Text>
          <DatePicker value={end} onChange={onPickEnd} allowClear={false} />
          <Segmented
            value={quick}
            onChange={(v) => applyQuick(String(v))}
            options={[
              { label: t('bmm.quick.30'), value: '30' },
              { label: t('bmm.quick.90'), value: '90' },
              { label: t('bmm.quick.180'), value: '180' },
              { label: t('bmm.quick.365'), value: '365' },
              { label: t('bmm.quick.all'), value: 'all' },
              // 手改日期后落到这一档，避免仍高亮某个快捷窗造成误解
              { label: t('bmm.quick.custom'), value: 'custom' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            {t('bmm.btn.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportAll} disabled={!data}>
            {t('bmm.btn.export')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bmm.filter.dataRange')}: {fmt(data?.meta.data_min_date)} ~ {fmt(data?.meta.data_max_date)}
            {' · '}{t('bmm.filter.rows')} {fmt(data?.meta.row_count)}
          </Text>
        </Space>
      </CardBase>

      {/* ①② 两家 PK：结论 / 评分 / 速率均值 / 速率区间 —— 合并成**一行 6 张卡**。
          此前是两行（结论+评分一行、四张速率卡一行），每张卡只有一两个数字，
          纵向叠起来后整块很高、卡内大片留白，所以并成一行。
          列宽：结论卡内容最多（含奖杯与三行文字）给 xl=8，其余五张各 xl=4（8+4×4=24）。
          align="stretch" + Col 撑高 + 卡片 width:100%：三者缺一不可，否则同排不等高。 */}
      <Row gutter={[12, 12]} align="stretch" style={{ marginBottom: 12 }}>
        <Col xs={24} lg={12} xl={8} style={{ display: 'flex' }}>
          <CardBase title={t('bmm.card.verdict')} level={verdict?.brand ? 'ok' : 'default'}
            style={{ width: '100%' }}>
            {verdict?.brand ? (
              /* 结论卡：奖杯徽章 + 领先方 + 分差 + 胜场胜率（可下钻），
                 用真实数据填满纵向空间，避免只有一行文字时显得空旷。 */
              <Row align="middle" gutter={16} style={{ height: '100%' }}>
                <Col flex="none">
                  <div
                    style={{
                      width: 64, height: 64, borderRadius: 16,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 34, lineHeight: 1,
                      color: brandColor(verdict.brand, isDark),
                      background: `color-mix(in srgb, ${brandColor(verdict.brand, isDark)} 16%, transparent)`,
                      boxShadow: `inset 0 0 18px color-mix(in srgb, ${brandColor(verdict.brand, isDark)} 22%, transparent)`,
                    }}
                  >
                    <TrophyFilled />
                  </div>
                </Col>
                <Col flex="auto" style={{ minWidth: 0 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('bmm.verdict.winnerLabel')}
                  </Text>
                  <div style={{
                    fontSize: 24, fontWeight: 700, lineHeight: 1.2,
                    color: brandColor(verdict.brand, isDark),
                  }}>
                    {t(brandLabelKey(verdict.brand))}
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('bmm.verdict.lead', { n: num(verdict.diff, 1) })}
                  </Text>
                  {/* 赢在哪：胜场对比，数字可点下钻，与其它区块口径一致 */}
                  <div style={{ marginTop: 4, fontSize: 12 }}>
                    <a
                      onClick={(e) => void openDrill(
                        { metric: 'speed', winner: verdict.brand as BrandKey },
                        `${t(brandLabelKey(verdict.brand as BrandKey))} · ${t('bmm.drill.winDays')}`,
                        e,
                      )}
                    >
                      {t('bmm.verdict.winDays', {
                        w: String(verdict.brand === 'ORANGE' ? wins?.orange_wins ?? 0 : wins?.mtn_wins ?? 0),
                        d: String(wins?.paired_days ?? 0),
                        r: num((verdict.brand === 'ORANGE' ? wins?.orange_win_rate : wins?.mtn_win_rate) ?? 0, 1),
                      })}
                    </a>
                  </div>
                </Col>
              </Row>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('bmm.empty')} />
            )}
          </CardBase>
        </Col>

        {/* 综合评分（两家并排），窄列下由上下双栏改为紧凑纵排以免挤压 */}
        <Col xs={24} lg={12} xl={4} style={{ display: 'flex' }}>
          <CardBase title={t('bmm.card.scores')} style={{ width: '100%' }}>
            <Row gutter={8} align="stretch" style={{ height: '100%' }}>
              {(['ORANGE', 'MTN'] as BrandKey[]).map(b => (
                <Col span={12} key={b} style={{ display: 'flex' }}>
                  <div
                    onClick={(e) => void openDrill(
                      { metric: 'speed', winner: b },
                      `${t(brandLabelKey(b))} · ${t('bmm.drill.winDays')}`,
                      e,
                    )}
                    style={{
                      cursor: 'pointer', textAlign: 'center', width: '100%',
                      display: 'flex', flexDirection: 'column', justifyContent: 'center',
                    }}
                  >
                    <div style={{ color: brandColor(b, isDark), fontWeight: 600, fontSize: 12 }}>
                      {t(brandLabelKey(b))}
                    </div>
                    <div style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.2 }}>
                      {num(scores?.[b]?.score, 1)}
                    </div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {t('bmm.card.winDaysShort', {
                        w: String(b === 'ORANGE' ? wins?.orange_wins ?? 0 : wins?.mtn_wins ?? 0),
                      })}
                    </Text>
                  </div>
                </Col>
              ))}
            </Row>
          </CardBase>
        </Col>

        {/* 速率均值 + 区间：四张卡并排 */}
        {(['ORANGE', 'MTN'] as BrandKey[]).map(b => {
          const s = summary?.[b]
          const isLeader = speedLeader === b
          const winCount = b === 'ORANGE' ? wins?.orange_wins ?? 0 : wins?.mtn_wins ?? 0
          return (
            <Col xs={24} sm={12} md={12} xl={4} key={`avg-${b}`} style={{ display: 'flex' }}>
              <StatCard
                title={`${t(brandLabelKey(b))} · ${t('bmm.metric.speed')}`}
                value={num(s?.speed)}
                suffix="Mbps"
                accentColor={brandColor(b, isDark)}
                iconBg={brandColor(b, isDark)}
                style={{ width: '100%' }}
                subText={isLeader
                  ? `${t('bmm.card.leaderTag')} · ${t('bmm.card.winDaysShort', { w: String(winCount) })}`
                  : t('bmm.card.winDaysShort', { w: String(winCount) })}
                onClick={(e) => void openDrill(
                  { metric: 'speed', winner: b },
                  `${t(brandLabelKey(b))} · ${t('bmm.drill.winDays')}`,
                  e,
                )}
              />
            </Col>
          )
        })}
        {(['ORANGE', 'MTN'] as BrandKey[]).map(b => (
          <Col xs={24} sm={12} md={12} xl={4} key={`range-${b}`} style={{ display: 'flex' }}>
            <StatCard
              title={`${t('bmm.card.rangeLabel')} (${t(brandLabelKey(b))})`}
              value={`${num(summary?.[b]?.speed_min, 1)} ~ ${num(summary?.[b]?.speed_max, 1)}`}
              accentColor={brandColor(b, isDark)}
              iconBg={brandColor(b, isDark)}
              style={{ width: '100%' }}
              onClick={(e) => void openDrill({ metric: 'speed' }, `${t(brandLabelKey(b))} · ${t('bmm.metric.speed')}`, e)}
            />
          </Col>
        ))}
      </Row>

      {/* ③ 网络侧 KPI 汇总卡（不属于任何一家，单独一组） */}
      <CardBase title={t('bmm.sec.network')} extra={
        <Text type="secondary" style={{ fontSize: 12 }}>{t('bmm.sec.networkHint')}</Text>
      } style={{ marginBottom: 12 }}>
        <Row gutter={[12, 12]} align="stretch">
          {NETWORK_KEYS.map(k => {
            const u = data?.filters.metrics.find(x => x.key === k)?.unit || ''
            const v = data?.summary.network?.[k]
            return (
              <Col xs={12} sm={8} lg={4} key={k} style={{ display: 'flex' }}>
                <div
                  onClick={(e) => void openDrill({ metric: k }, `${t(metricLabelKey(k))}`, e)}
                  style={{
                    cursor: 'pointer', padding: '6px 4px', borderRadius: 8, width: '100%',
                    // 等高：用 flex 纵向排列并让数值块占满剩余高度，指标名换行时也齐平
                    display: 'flex', flexDirection: 'column',
                  }}
                  title={t(metricHintKey(k))}
                >
                  <Text type="secondary" style={{ fontSize: 12 }}>{t(metricLabelKey(k))}</Text>
                  <div style={{ fontSize: 18, fontWeight: 600, marginTop: 'auto', paddingTop: 2 }}>
                    {fmtByUnit(v, u)}
                  </div>
                </div>
              </Col>
            )
          })}
        </Row>
      </CardBase>

      {/* ④ 趋势图：切指标（两家 PK / 网络侧 KPI）与滚动均值窗口 */}
      <CardBase
        title={t('bmm.card.trend')}
        style={{ marginBottom: 12 }}
        extra={
          <Space wrap size={8}>
            <Segmented
              value={metric}
              onChange={(v) => setMetric(String(v) as MetricKey)}
              options={[
                { label: t('bmm.metric.speed'), value: 'speed' },
                { label: t('bmm.metric.bp'), value: 'bp' },
                { label: t('bmm.metric.dlThroughput'), value: 'dl_throughput' },
                { label: t('bmm.metric.dlPrb'), value: 'dl_prb' },
                { label: t('bmm.metric.ulPrb'), value: 'ul_prb' },
                { label: t('bmm.metric.traffic'), value: 'traffic' },
                { label: t('bmm.metric.rrcUsers'), value: 'rrc_users' },
              ]}
            />
            <Select
              value={maWindow}
              onChange={(v) => setMaWindow(v)}
              style={{ width: 132 }}
              options={[3, 7, 14, 30, 60].map(n => ({ value: n, label: t('bmm.ma.fmt', { n: String(n) }) }))}
            />
          </Space>
        }
      >
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          {t(metricHintKey(metric))}
        </Text>
        {trend.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={trendLoading ? t('bmm.loading') : t('bmm.empty')} />
        ) : (
          <ReactECharts
            option={trendOption}
            style={{ height: 340 }}
            notMerge
            showLoading={trendLoading}
          />
        )}
      </CardBase>

      {/* ⑤ 月度对比表（按月聚合，逐日派生） */}
      <CardBase title={t('bmm.card.monthly')} style={{ marginBottom: 12 }}>
        <Table<MonthRow>
          size="small"
          rowKey="ym"
          loading={loading}
          dataSource={data?.monthly || []}
          columns={monthColumns}
          scroll={{ x: 'max-content' }}
          pagination={false}
        />
      </CardBase>

      {/* ⑥ 逐日对决明细表（每格可点下钻） */}
      <CardBase
        title={t('bmm.card.daily')}
        extra={
          <Space size={8}>
            {data?.meta.daily_truncated && (
              <Tag color="orange">
                {t('bmm.truncated', { n: String(data.meta.daily_returned), t: String(data.meta.daily_total) })}
              </Tag>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('bmm.card.dailyHint')}
            </Text>
          </Space>
        }
      >
        <Table<DailyRow>
          size="small"
          rowKey="day"
          loading={loading}
          dataSource={data?.daily || []}
          columns={dailyColumns}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: ['30', '60', '120'] }}
        />
      </CardBase>

      {/* 下钻弹窗：复用统一组件 */}
      <DraggableClickModal
        open={open}
        title={`${drillTitle}${drillRows.length ? ` (${drillRows.length})` : ''}`}
        anchor={anchor}
        onClose={() => setOpen(false)}
      >
        {drillMeta?.truncated ? (
          <Alert
            type="warning" showIcon style={{ marginBottom: 8 }}
            message={t('bmm.drill.truncated', { n: String(drillMeta.limit) })}
          />
        ) : null}
        <Table<DetailRow>
          size="small"
          rowKey={(r) => `${r.day}-${r.winner ?? 'tie'}`}
          loading={drillLoading}
          dataSource={drillRows}
          columns={drillColumns}
          scroll={{ x: 'max-content', y: 420 }}
          pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['50', '100', '200'] }}
        />
      </DraggableClickModal>
    </div>
  )
}
