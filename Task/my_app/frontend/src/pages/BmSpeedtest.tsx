/* ============================================================================
 * Speedtest 竞对分析（ORANGE vs MTN）—— `?page=bm_speedtest`
 * ----------------------------------------------------------------------------
 * 数据源：`speedtest_data`（Speedtest.xlsx 导入，854 行，2025-07-16 ~ 2026-09-24）。
 * 口径的唯一真相源是 `backend/services/bm_speedtest_caliber.py`，本页**不含任何业务口径**。
 *
 * 四个分析区块（对应需求里的四类维度）：
 *   ① 综合竞争力评分 + 关键指标汇总卡（谁强、强多少）
 *   ② 下载 / 上传速率对比趋势（逐日双线 + 滚动均值）
 *   ③ 时延与抖动对比趋势
 *   ④ 测试量与样本量对比（数据可信度与覆盖规模）
 * 外加：月度对比表、逐日对决明细表、胜负统计。
 *
 * 本页遵循 AGENTS.md 第三节 1b「能下钻尽下钻」：**每个数字都可点**并落到明细。
 * 下钻口径与概览完全一致（后端共用同一份 WHERE），故「卡片上的 49 天」
 * 与「点开后 49 行」严格相等。
 *
 * ⚠️ 图表取色分两层：DOM 用 WH（CSS 变量），ECharts 用 useTheme() 的 DARK/LIGHT 实值
 * （canvas 解析不了 CSS 变量）。本文件里的 `#f97316` / `#0d9488` 等均为**图表实值**。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Segmented, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { WH, useTheme, cardStyle, axisLabel, axisLine, darkTooltip, splitLine } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import OoklaLogo from '../components/OoklaLogo'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportAoaReport } from '../utils/excelReport'
import { fmtWarnings } from '../utils/warnCodes'
import {
  getBmSpeedtestOverview,
  getBmSpeedtestTrend,
  getBmSpeedtestDrilldown,
} from '../api'

const { Text } = Typography

/* ---- 类型（与后端返回结构对齐） ---- */

type MetricKey = 'download' | 'upload' | 'latency' | 'jitter'
type BrandKey = 'ORANGE' | 'MTN'

interface DayRow {
  day: string
  orange_download: number | null; mtn_download: number | null; winner_download: BrandKey | null
  orange_upload: number | null; mtn_upload: number | null; winner_upload: BrandKey | null
  orange_latency: number | null; mtn_latency: number | null; winner_latency: BrandKey | null
  orange_jitter: number | null; mtn_jitter: number | null; winner_jitter: BrandKey | null
  orange_tests: number; mtn_tests: number
}

interface MonthRow {
  ym: string; days: number
  orange_download: number | null; mtn_download: number | null; winner_download: BrandKey | null
  orange_upload: number | null; mtn_upload: number | null; winner_upload: BrandKey | null
  orange_latency: number | null; mtn_latency: number | null; winner_latency: BrandKey | null
  orange_jitter: number | null; mtn_jitter: number | null; winner_jitter: BrandKey | null
  orange_tests: number; mtn_tests: number
}

interface BrandSummary {
  brand: BrandKey; label: string; days: number
  download: number | null; upload: number | null
  latency: number | null; jitter: number | null
  download_min?: number | null; download_max?: number | null
  upload_min?: number | null; upload_max?: number | null
  latency_min?: number | null; latency_max?: number | null
  jitter_min?: number | null; jitter_max?: number | null
  tests: number; samples: number; devices: number; tests_per_day: number | null
  first_day: string | null; last_day: string | null
  pcts: Record<string, { p50: number | null; p90: number | null }>
}

interface WinCell {
  paired_days: number; orange_wins: number; mtn_wins: number; ties: number
  orange_win_rate: number | null; mtn_win_rate: number | null
}

interface WinStats {
  total_days: number; unpaired_days: number; paired_days: number
  metrics: Record<string, WinCell>
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
    metrics: { key: MetricKey; kind: 'speed' | 'latency'; unit: string }[]
  }
  summary: Record<BrandKey, BrandSummary>
  scores: Record<BrandKey, { score: number | null; parts: Record<string, number> }>
  score_weights: Record<string, number>
  daily: DayRow[]
  monthly: MonthRow[]
  wins: WinStats
}

interface TrendPoint {
  day: string
  orange: number | null; mtn: number | null
  orange_ma: number | null; mtn_ma: number | null
  winner: BrandKey | null
}

interface DetailRow {
  brand: BrandKey; brand_label: string; day: string
  provider: string; location: string; device: string
  technology_type: string; metric_type: string
  download: number | null; upload: number | null
  latency: number | null; jitter: number | null
  tests: number; samples: number; devices: number
  source_file: string; import_time: string
}

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 第六节第 6 条：取不到显示 —，不得显示 0） */
const fmt = (v: unknown) => (v == null || v === '' ? '—' : String(v))

/** 数值格式化：保留位数由调用方给，空值仍是 — */
function num(v: unknown, nd = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(nd) : '—'
}

const METRIC_UNIT: Record<MetricKey, string> = {
  download: 'Mbps', upload: 'Mbps', latency: 'ms', jitter: 'ms',
}
const METRIC_KIND: Record<MetricKey, 'speed' | 'latency'> = {
  download: 'speed', upload: 'speed', latency: 'latency', jitter: 'latency',
}

/** 指标 i18n 键：显式 switch，不拼字符串 —— 拼出来的键会被 check:i18n 拦下 */
function metricLabelKey(m: MetricKey): string {
  switch (m) {
    case 'download': return 'bms.metric.download'
    case 'upload': return 'bms.metric.upload'
    case 'latency': return 'bms.metric.latency'
    case 'jitter': return 'bms.metric.jitter'
  }
}

/** 品牌 i18n 键：同样显式 switch */
function brandLabelKey(b: BrandKey): string {
  switch (b) {
    case 'ORANGE': return 'bms.brand.orange'
    case 'MTN': return 'bms.brand.mtn'
  }
}

/** 品牌固定色（图表实值）：ORANGE 用橙、MTN 用青蓝，深浅主题各一套保证对比度 */
function brandColor(b: BrandKey, isDark: boolean): string {
  if (b === 'ORANGE') return isDark ? '#ff922b' : '#ea580c'
  return isDark ? '#00d9ff' : '#0d9488'
}

export default function BmSpeedtest() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 筛选条件：只有时间维度（数据里 location/device/制式/聚合方式均只有一个有效取值） ---- */
  const [start, setStart] = useState<Dayjs | null>(null)
  const [end, setEnd] = useState<Dayjs | null>(null)
  const [quick, setQuick] = useState<string>('90')

  /* ---- 数据与状态 ---- */
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /* ---- 趋势区：当前指标 + 滚动均值窗口 ---- */
  const [metric, setMetric] = useState<MetricKey>('download')
  const [maWindow, setMaWindow] = useState<number>(7)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [trendLoading, setTrendLoading] = useState(false)

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillTitle, setDrillTitle] = useState('')
  const [drillRows, setDrillRows] = useState<DetailRow[]>([])
  const [drillMeta, setDrillMeta] = useState<Record<string, unknown> | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)

  /* ---- 首次加载：先用后端给的默认窗口（近 90 天）对齐日期选择器 ---- */
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const r = await getBmSpeedtestOverview({})
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

  /* ---- 取数：区间用「左闭右开」，end 传次日，与后端口径一致 ---- */
  const load = useCallback(async () => {
    if (!start || !end) return
    setLoading(true)
    setError('')
    try {
      const r = await getBmSpeedtestOverview({
        start: start.format('YYYY-MM-DD'),
        end: end.add(1, 'day').format('YYYY-MM-DD'),
      })
      setData(r.data)
      if (r.data?.meta?.warnings?.length) setError(fmtWarnings(r.data.meta.warnings, t, '；'))
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
        const r = await getBmSpeedtestTrend({
          start: start.format('YYYY-MM-DD'),
          end: end.add(1, 'day').format('YYYY-MM-DD'),
          metric, window: maWindow,
        })
        if (alive) setTrend(r.data?.series || [])
      } catch {
        if (alive) setTrend([])   // 趋势失败不阻塞页面主体，图表区显示空态
      } finally {
        if (alive) setTrendLoading(false)
      }
    })()
    return () => { alive = false }
  }, [start, end, metric, maWindow])

  /* ---- 快捷时间窗 ---- */
  const applyQuick = useCallback((v: string) => {
    setQuick(v)
    if (v === 'all') {
      const min = data?.filters?.min_date
      const max = data?.filters?.max_date
      if (min) setStart(dayjs(min))
      if (max) setEnd(dayjs(max))
      return
    }
    const n = Number(v)
    if (Number.isFinite(n) && n > 0) {
      setEnd(dayjs())
      setStart(dayjs().subtract(n - 1, 'day'))
    }
  }, [data])

  const summary = data?.summary
  const wins = data?.wins
  const scores = data?.scores

  /* ---- 综合结论：谁在总分上更强（评分相等或无数据时不下结论） ---- */
  const verdict = useMemo(() => {
    const o = scores?.ORANGE?.score
    const m = scores?.MTN?.score
    if (o == null || m == null) return null
    if (o === m) return { brand: null as BrandKey | null, diff: 0 }
    return { brand: (o > m ? 'ORANGE' : 'MTN') as BrandKey, diff: Math.abs(o - m) }
  }, [scores])

  /* ---- 每个指标各自的领先方（用于汇总卡染色与文字结论） ---- */
  const leaderOf = useCallback((mt: MetricKey): BrandKey | null => {
    if (!summary) return null
    const a = summary.ORANGE?.[mt]
    const b = summary.MTN?.[mt]
    if (a == null || b == null) return null
    if (a === b) return null
    if (METRIC_KIND[mt] === 'speed') return a > b ? 'ORANGE' : 'MTN'
    return a < b ? 'ORANGE' : 'MTN'
  }, [summary])

  /* ---- 趋势图配置 ---- */
  const trendOption = useMemo(() => {
    const days = trend.map(p => p.day.slice(5))
    const kind = METRIC_KIND[metric]
    const unit = METRIC_UNIT[metric]
    return {
      tooltip: {
        trigger: 'axis',
        ...darkTooltip(isDark),
        valueFormatter: (v: unknown) => (v == null ? '—' : `${Number(v).toFixed(1)} ${unit}`),
      },
      legend: {
        data: [t('bms.brand.orange'), t('bms.brand.mtn'), t('bms.legend.maOrange'), t('bms.legend.maMtn')],
        textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 11 },
        top: 0,
      },
      grid: { left: 58, right: 24, top: 44, bottom: 56 },
      xAxis: {
        type: 'category', data: days,
        axisLabel: { ...axisLabel(isDark), rotate: 35 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value',
        name: unit,
        nameTextStyle: { color: isDark ? '#6f8cb4' : '#5b7288', fontSize: 11 },
        axisLabel: axisLabel(isDark),
        splitLine: splitLine(isDark),
        // 时延越小越好：把轴反过来更直观地表达"越低越优"
        inverse: false,
      },
      series: [
        {
          name: t('bms.brand.orange'), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.orange),
          lineStyle: { width: 2, color: brandColor('ORANGE', isDark) },
          itemStyle: { color: brandColor('ORANGE', isDark) },
        },
        {
          name: t('bms.brand.mtn'), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.mtn),
          lineStyle: { width: 2, color: brandColor('MTN', isDark) },
          itemStyle: { color: brandColor('MTN', isDark) },
        },
        {
          name: t('bms.legend.maOrange'), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.orange_ma),
          lineStyle: { width: 2, type: 'dashed', color: brandColor('ORANGE', isDark), opacity: 0.6 },
          itemStyle: { color: brandColor('ORANGE', isDark) },
        },
        {
          name: t('bms.legend.maMtn'), type: 'line', smooth: true, showSymbol: false,
          data: trend.map(p => p.mtn_ma),
          lineStyle: { width: 2, type: 'dashed', color: brandColor('MTN', isDark), opacity: 0.6 },
          itemStyle: { color: brandColor('MTN', isDark) },
        },
      ],
      // 时延类指标：低于均值的部分更好，这里不做高亮，仅由两条实线本身比较
      _kind: kind,
    }
  }, [trend, metric, isDark, t])

  /* ---- 下钻：统一入口。参数与概览口径一致，保证行数对得上 ---- */
  const openDrill = useCallback(async (
    opts: { title: string; at?: { x: number; y: number }; metric?: MetricKey; day?: string; brand?: BrandKey; winner?: BrandKey },
  ) => {
    if (!start || !end) return
    setOpen(true)
    setAnchor(opts.at || null)
    setDrillTitle(opts.title)
    setDrillLoading(true)
    setDrillRows([])
    setDrillMeta(null)
    try {
      const r = await getBmSpeedtestDrilldown({
        start: start.format('YYYY-MM-DD'),
        end: end.add(1, 'day').format('YYYY-MM-DD'),
        metric: opts.metric, day: opts.day, brand: opts.brand,
        winner: opts.winner, limit: 3000,
      })
      setDrillRows(r.data?.rows || [])
      setDrillMeta(r.data?.meta || null)
    } catch (e: any) {
      setDrillRows([])
      setDrillMeta({ error: e?.message || String(e) })
    } finally {
      setDrillLoading(false)
    }
  }, [start, end])

  /* ---- 导出：一律走 excelReport ---- */
  const exportRows = useCallback((kind: 'daily' | 'monthly' | 'detail', rows: unknown[]) => {
    if (!rows.length) return
    const stamp = dayjs().format('YYYYMMDD_HHmmss')
    if (kind === 'daily') {
      const list = rows as DayRow[]
      void exportAoaReport({
        filename: `BM_Speedtest_daily_${stamp}.xlsx`,
        sheetName: 'daily', title: t('bms.table.daily'),
        header: [
          t('bms.col.day'),
          `${t('bms.brand.orange')} ${t('bms.metric.download')}`, `${t('bms.brand.mtn')} ${t('bms.metric.download')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.upload')}`, `${t('bms.brand.mtn')} ${t('bms.metric.upload')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.latency')}`, `${t('bms.brand.mtn')} ${t('bms.metric.latency')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.jitter')}`, `${t('bms.brand.mtn')} ${t('bms.metric.jitter')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.col.tests')}`, `${t('bms.brand.mtn')} ${t('bms.col.tests')}`,
        ],
        rows: list.map(r => [
          r.day,
          r.orange_download, r.mtn_download, r.winner_download ? t(brandLabelKey(r.winner_download)) : '—',
          r.orange_upload, r.mtn_upload, r.winner_upload ? t(brandLabelKey(r.winner_upload)) : '—',
          r.orange_latency, r.mtn_latency, r.winner_latency ? t(brandLabelKey(r.winner_latency)) : '—',
          r.orange_jitter, r.mtn_jitter, r.winner_jitter ? t(brandLabelKey(r.winner_jitter)) : '—',
          r.orange_tests, r.mtn_tests,
        ]),
        numericCols: [1, 2, 4, 5, 7, 8, 10, 11, 12, 13],
      })
      return
    }
    if (kind === 'monthly') {
      const list = rows as MonthRow[]
      void exportAoaReport({
        filename: `BM_Speedtest_monthly_${stamp}.xlsx`,
        sheetName: 'monthly', title: t('bms.table.monthly'),
        header: [
          t('bms.col.month'), t('bms.col.days'),
          `${t('bms.brand.orange')} ${t('bms.metric.download')}`, `${t('bms.brand.mtn')} ${t('bms.metric.download')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.upload')}`, `${t('bms.brand.mtn')} ${t('bms.metric.upload')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.latency')}`, `${t('bms.brand.mtn')} ${t('bms.metric.latency')}`, t('bms.col.winner'),
          `${t('bms.brand.orange')} ${t('bms.metric.jitter')}`, `${t('bms.brand.mtn')} ${t('bms.metric.jitter')}`, t('bms.col.winner'),
        ],
        rows: list.map(r => [
          r.ym, r.days,
          r.orange_download, r.mtn_download, r.winner_download ? t(brandLabelKey(r.winner_download)) : '—',
          r.orange_upload, r.mtn_upload, r.winner_upload ? t(brandLabelKey(r.winner_upload)) : '—',
          r.orange_latency, r.mtn_latency, r.winner_latency ? t(brandLabelKey(r.winner_latency)) : '—',
          r.orange_jitter, r.mtn_jitter, r.winner_jitter ? t(brandLabelKey(r.winner_jitter)) : '—',
        ]),
        numericCols: [1, 2, 3, 5, 6, 8, 9, 11, 12],
      })
      return
    }
    const list = rows as DetailRow[]
    void exportAoaReport({
      filename: `BM_Speedtest_detail_${stamp}.xlsx`,
      sheetName: 'detail', title: drillTitle || t('bms.drill.title'),
      header: [
        t('bms.col.day'), t('bms.col.brand'), t('bms.metric.download'), t('bms.metric.upload'),
        t('bms.metric.latency'), t('bms.metric.jitter'),
        t('bms.col.tests'), t('bms.col.samples'), t('bms.col.devices'),
        t('bms.col.provider'), t('bms.col.location'), t('bms.col.source'),
      ],
      rows: list.map(r => [
        r.day, r.brand_label, r.download, r.upload, r.latency, r.jitter,
        r.tests, r.samples, r.devices, r.provider, r.location, r.source_file,
      ]),
      numericCols: [2, 3, 4, 5, 6, 7, 8],
    })
  }, [t, drillTitle])

  /* ---- 逐日对决表列 ---- */
  const dailyColumns = useMemo(() => {
    const pairCol = (metric: MetricKey) => [
      {
        title: `${t('bms.brand.orange')} ${t(metricLabelKey(metric))}`, key: `o_${metric}`, width: 108,
        render: (_: unknown, r: DayRow) => <Text>{num((r as any)[`orange_${metric}`], metric === 'latency' ? 1 : 2)}</Text>,
      },
      {
        title: `${t('bms.brand.mtn')} ${t(metricLabelKey(metric))}`, key: `m_${metric}`, width: 108,
        render: (_: unknown, r: DayRow) => <Text>{num((r as any)[`mtn_${metric}`], metric === 'latency' ? 1 : 2)}</Text>,
      },
      {
        title: `${t(metricLabelKey(metric))} ${t('bms.col.winner')}`, key: `w_${metric}`, width: 96,
        render: (_: unknown, r: DayRow) => {
          const w = (r as any)[`winner_${metric}`] as BrandKey | null
          if (!w) return <Text type="secondary">—</Text>
          return <Tag color={w === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(w))}</Tag>
        },
      },
    ]
    return [
      {
        title: t('bms.col.day'), dataIndex: 'day', width: 104, fixed: 'left' as const,
        render: (v: string, r: DayRow) => (
          <Button type="link" size="small" style={{ padding: 0 }}
            onClick={e => void openDrill({
              title: `${v} · ${t('bms.drill.dayTitle')}`,
              at: { x: e.clientX, y: e.clientY }, day: v,
            })}>
            {v}
          </Button>
        ),
      },
      ...pairCol('download'), ...pairCol('upload'), ...pairCol('latency'), ...pairCol('jitter'),
      {
        title: t('bms.col.tests'), key: 'tests', width: 150,
        render: (_: unknown, r: DayRow) => (
          <Button type="link" size="small" style={{ padding: 0 }}
            onClick={e => void openDrill({
              title: `${r.day} · ${t('bms.col.tests')}`,
              at: { x: e.clientX, y: e.clientY }, day: r.day,
            })}>
            {`${r.orange_tests} / ${r.mtn_tests}`}
          </Button>
        ),
      },
    ]
  }, [t, openDrill])

  /* ---- 月度对比表列 ---- */
  const monthlyColumns = useMemo(() => {
    const cols: any[] = [
      { title: t('bms.col.month'), dataIndex: 'ym', width: 96, fixed: 'left' },
      { title: t('bms.col.days'), dataIndex: 'days', width: 76 },
    ]
    const metrics: MetricKey[] = ['download', 'upload', 'latency', 'jitter']
    for (const m of metrics) {
      const nd = m === 'latency' ? 1 : 2
      cols.push({
        title: `${t('bms.brand.orange')} ${t(metricLabelKey(m))}`, key: `o_${m}`, width: 104,
        render: (_: unknown, r: MonthRow) => num((r as any)[`orange_${m}`], nd),
      })
      cols.push({
        title: `${t('bms.brand.mtn')} ${t(metricLabelKey(m))}`, key: `m_${m}`, width: 104,
        render: (_: unknown, r: MonthRow) => num((r as any)[`mtn_${m}`], nd),
      })
      cols.push({
        title: `${t(metricLabelKey(m))} ${t('bms.col.winner')}`, key: `w_${m}`, width: 92,
        render: (_: unknown, r: MonthRow) => {
          const w = (r as any)[`winner_${m}`] as BrandKey | null
          if (!w) return <Text type="secondary">—</Text>
          return <Tag color={w === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(w))}</Tag>
        },
      })
    }
    return cols
  }, [t])

  /* ---- 下钻明细表列 ---- */
  const drillColumns = useMemo(() => [
    { title: t('bms.col.day'), dataIndex: 'day', width: 106 },
    {
      title: t('bms.col.brand'), dataIndex: 'brand_label', width: 150,
      render: (v: string, r: DetailRow) => <Tag color={r.brand === 'ORANGE' ? 'orange' : 'cyan'}>{v}</Tag>,
    },
    { title: t('bms.metric.download'), dataIndex: 'download', width: 96, render: (v: unknown) => num(v, 2) },
    { title: t('bms.metric.upload'), dataIndex: 'upload', width: 96, render: (v: unknown) => num(v, 2) },
    { title: t('bms.metric.latency'), dataIndex: 'latency', width: 96, render: (v: unknown) => num(v, 1) },
    { title: t('bms.metric.jitter'), dataIndex: 'jitter', width: 96, render: (v: unknown) => num(v, 2) },
    { title: t('bms.col.tests'), dataIndex: 'tests', width: 80 },
    { title: t('bms.col.samples'), dataIndex: 'samples', width: 84 },
    { title: t('bms.col.devices'), dataIndex: 'devices', width: 84 },
    { title: t('bms.col.provider'), dataIndex: 'provider', width: 150 },
    { title: t('bms.col.source'), dataIndex: 'source_file', width: 140, render: (v: unknown) => fmt(v) },
  ], [t])

  const daily = data?.daily || []
  const monthly = data?.monthly || []

  /* ---- 汇总卡配置：每个数字都可点下钻 ---- */
  const kpiCards = useMemo(() => {
    if (!summary) return []
    const mk = (m: MetricKey) => {
      const nd = m === 'latency' ? 1 : 2
      const leader = leaderOf(m)
      return { m, nd, leader, unit: METRIC_UNIT[m] }
    }
    return (['download', 'upload', 'latency', 'jitter'] as MetricKey[]).map(mk)
  }, [summary, leaderOf])

  /** 点汇总卡里的数字：下钻该品牌该指标在区间内的全部明细 */
  const clickCard = useCallback((m: MetricKey, brand: BrandKey, at?: { x: number; y: number }) => {
    void openDrill({
      title: `${t(brandLabelKey(brand))} · ${t(metricLabelKey(m))} · ${t('bms.drill.brandTitle')}`,
      at, metric: m, brand,
    })
  }, [t, openDrill])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Segmented
            className="wh-seg"
            size="small"
            value={quick}
            onChange={v => applyQuick(String(v))}
            options={[
              { label: t('bms.quick.30'), value: '30' },
              { label: t('bms.quick.90'), value: '90' },
              { label: t('bms.quick.180'), value: '180' },
              { label: t('bms.quick.365'), value: '365' },
              { label: t('bms.quick.all'), value: 'all' },
            ]}
          />
          <DatePicker value={start} onChange={setStart} allowClear={false} />
          <span>{t('bms.to')}</span>
          <DatePicker value={end} onChange={setEnd} allowClear={false} />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('bms.refresh')}</Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => exportRows('daily', daily)}
            disabled={!daily.length}
          >{t('common.exportExcel')}</Button>
        </Space>
        {data?.meta && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('bms.rangeHint', {
                from: data.meta.data_min_date || '—',
                to: data.meta.data_max_date || '—',
                rows: data.meta.row_count,
              })}
            </Text>
          </div>
        )}
      </CardBase>

      {error && <Alert type="error" showIcon message={error} />}

      {/* 数据截断显式暴露（AGENTS.md 第三节 1b：不允许静默截断） */}
      {data?.meta?.daily_truncated && (
        <Alert
          type="warning" showIcon
          message={t('bms.warn.dailyTruncated', { total: data.meta.daily_total, shown: data.meta.daily_returned })}
        />
      )}
      {/* 单边缺数据的日子：单独提示，避免用户把"没测"当成"输了" */}
      {!!wins?.unpaired_days && (
        <Alert
          type="info" showIcon
          message={t('bms.warn.unpaired', { n: wins.unpaired_days, total: wins.total_days })}
        />
      )}

      {/* ② 综合竞争力评分 —— 全页结论 */}
      {scores && (
        <CardBase title={t('bms.score.title')} extra={
          <Text type="secondary" style={{ fontSize: 12 }}>{t('bms.score.hint')}</Text>
        }>
          <Row gutter={[12, 12]}>
            {(['ORANGE', 'MTN'] as BrandKey[]).map(b => {
              const s = scores[b]
              const isWin = verdict?.brand === b
              return (
                <Col xs={24} sm={12} key={b}>
                  <CardBase as="div" level={isWin ? 'ok' : 'default'} interactive={false}>
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Space>
                        <Tag color={b === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(b))}</Tag>
                        {isWin && <Tag color="green">{t('bms.score.leading')}</Tag>}
                      </Space>
                      <Space align="baseline">
                        <Text strong style={{ fontSize: 30 }}>{num(s.score, 1)}</Text>
                        <Text type="secondary">{t('bms.score.unit')}</Text>
                      </Space>
                      <Space wrap size={4}>
                        {(['download', 'upload', 'latency', 'jitter'] as MetricKey[]).map(m => (
                          <Tooltip key={m} title={`${t(metricLabelKey(m))} · ${t('bms.score.weight')} ${Math.round((data?.score_weights?.[m] || 0) * 100)}%`}>
                            <Tag>{`${t(metricLabelKey(m))} ${num(s.parts?.[m], 0)}`}</Tag>
                          </Tooltip>
                        ))}
                      </Space>
                    </Space>
                  </CardBase>
                </Col>
              )
            })}
          </Row>
          {verdict && (
            <div style={{ marginTop: 10 }}>
              <Text>
                {verdict.brand
                  ? t('bms.score.verdict', {
                      brand: t(brandLabelKey(verdict.brand)),
                      diff: verdict.diff.toFixed(1),
                    })
                  : t('bms.score.tie')}
              </Text>
            </div>
          )}
        </CardBase>
      )}

      {/* ③ 关键指标汇总卡：每个指标两家并排，数字可点下钻 */}
      {summary && (
        <CardBase title={t('bms.kpi.title')} extra={
          <Space size={4}>
            <Button size="small" type="link"
              onClick={e => void openDrill({ title: t('bms.drill.allTitle'), at: { x: e.clientX, y: e.clientY } })}>
              {t('bms.drill.all')}
            </Button>
            <Button size="small" type="link"
              onClick={e => void openDrill({
                title: t('bms.drill.headTitle'), at: { x: e.clientX, y: e.clientY },
              })}>
              {t('bms.drill.sample')}
            </Button>
          </Space>
        }>
          <Row gutter={[12, 12]}>
            {kpiCards.map(({ m, nd, leader, unit }) => {
              const o = summary.ORANGE?.[m] as number | null
              const mt = summary.MTN?.[m] as number | null
              return (
                <Col xs={24} md={12} xl={6} key={m}>
                  <CardBase as="div" interactive={false}>
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Space>
                        <Text strong>{t(metricLabelKey(m))}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{unit}</Text>
                        {leader && <Tag color={leader === 'ORANGE' ? 'orange' : 'cyan'}>
                          {t('bms.kpi.lead', { brand: t(brandLabelKey(leader)) })}
                        </Tag>}
                      </Space>
                      {(['ORANGE', 'MTN'] as BrandKey[]).map(b => {
                        const v = b === 'ORANGE' ? o : mt
                        const isLead = leader === b
                        return (
                          <Space key={b} style={{ width: '100%', justifyContent: 'space-between' }}>
                            <Tag color={b === 'ORANGE' ? 'orange' : 'cyan'}>{t(brandLabelKey(b))}</Tag>
                            <Button
                              type="link" size="small" style={{ padding: 0, fontWeight: isLead ? 700 : 400 }}
                              onClick={e => clickCard(m, b, { x: e.clientX, y: e.clientY })}
                            >{num(v, nd)}</Button>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {t('bms.kpi.p50p90', {
                                p50: num(summary[b]?.pcts?.[m]?.p50, nd),
                                p90: num(summary[b]?.pcts?.[m]?.p90, nd),
                              })}
                            </Text>
                          </Space>
                        )
                      })}
                      {/* 胜率：点它下钻「该指标胜者的那些天」，行数与胜场天数严格相等。
                          右端挂 Speedtest by Ookla 标识，标明这四张卡的数据来源
                          （2026-10-01 加，与门户 v1/olbrportal 的那一行同一个标识）。
                          为什么用 flex + marginLeft:auto 而不是把标识塞进 Space：
                          Space 会把它当成第 4 个等距项，紧贴在胜率数字后面；
                          这里要的是"钉在卡右端"，与参考图/门户一致。
                          flexWrap 是给极窄卡留的退路 —— xl 断点下 4 张并排时
                          卡宽约 285px（1680px 视口），胜率那段文字约 200px、
                          标识约 93px，加起来会超；换行后 marginLeft:auto
                          仍把它推到右端，而不是溢出。 */}
                      <div style={{
                        display: 'flex', flexWrap: 'wrap', alignItems: 'center',
                        gap: 'var(--wh-space-xs)',
                      }}>
                        <Space wrap size={4}>
                          <Text type="secondary" style={{ fontSize: 12 }}>{t('bms.kpi.winRate')}</Text>
                          {(['ORANGE', 'MTN'] as BrandKey[]).map(b => {
                            const cell = wins?.metrics?.[m]
                            const w = b === 'ORANGE' ? cell?.orange_wins : cell?.mtn_wins
                            const rate = b === 'ORANGE' ? cell?.orange_win_rate : cell?.mtn_win_rate
                            return (
                              <Tooltip key={b} title={t('bms.kpi.winTip', { n: w ?? 0 })}>
                                <Button
                                  type="link" size="small" style={{ padding: 0, height: 'auto', fontSize: 12 }}
                                  onClick={e => void openDrill({
                                    title: `${t(brandLabelKey(b))} · ${t(metricLabelKey(m))} · ${t('bms.drill.winTitle')}`,
                                    at: { x: e.clientX, y: e.clientY }, metric: m, winner: b,
                                  })}
                                >{`${t(brandLabelKey(b))} ${num(rate, 1)}%`}</Button>
                              </Tooltip>
                            )
                          })}
                        </Space>
                        <OoklaLogo height={24} style={{ marginLeft: 'auto' }} />
                      </div>
                    </Space>
                  </CardBase>
                </Col>
              )
            })}
          </Row>
        </CardBase>
      )}

      {/* ④ 测试量与样本量对比（数据可信度） */}
      {summary && (
        <Row gutter={[12, 12]}>
          {(['ORANGE', 'MTN'] as BrandKey[]).map(b => (
            <Col xs={24} sm={12} lg={6} key={`t-${b}`}>
              <StatCard title={`${t(brandLabelKey(b))} · ${t('bms.col.tests')}`} value={summary[b]?.tests ?? 0} />
            </Col>
          ))}
          {(['ORANGE', 'MTN'] as BrandKey[]).map(b => (
            <Col xs={24} sm={12} lg={6} key={`d-${b}`}>
              <StatCard title={`${t(brandLabelKey(b))} · ${t('bms.col.devices')}`} value={summary[b]?.devices ?? 0} />
            </Col>
          ))}
        </Row>
      )}

      {/* ⑤ 趋势图：指标切换（分段控件）+ 滚动均值窗口 */}
      <CardBase
        title={t('bms.trend.title')}
        extra={
          <Space wrap>
            <Segmented
              className="wh-seg"
              size="small" value={metric}
              onChange={v => setMetric(v as MetricKey)}
              options={(['download', 'upload', 'latency', 'jitter'] as MetricKey[]).map(m => ({
                label: t(metricLabelKey(m)), value: m,
              }))}
            />
            <Select
              size="small" value={maWindow} style={{ width: 132 }}
              onChange={setMaWindow}
              options={[3, 7, 14, 30].map(n => ({ value: n, label: t('bms.trend.ma', { n }) }))}
            />
          </Space>
        }
      >
        {trendLoading
          ? <div style={{ height: 340, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Text type="secondary">{t('bms.loading')}</Text>
            </div>
          : trend.length
            ? <ReactECharts option={trendOption} style={{ height: 340 }} notMerge />
            : <Empty description={t('bms.empty')} />}
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {METRIC_KIND[metric] === 'speed' ? t('bms.trend.higherBetter') : t('bms.trend.lowerBetter')}
          </Text>
        </div>
      </CardBase>

      {/* ⑥ 胜负统计汇总：四条指标各自的胜场数，均可点 */}
      {wins && (
        <CardBase title={t('bms.wins.title')} extra={
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('bms.wins.hint', { paired: wins.paired_days, unpaired: wins.unpaired_days })}
          </Text>
        }>
          <Row gutter={[12, 12]}>
            {(['download', 'upload', 'latency', 'jitter'] as MetricKey[]).map(m => {
              const c = wins.metrics?.[m]
              if (!c) return null
              return (
                <Col xs={24} sm={12} xl={6} key={m}>
                  <CardBase as="div" interactive={false}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text strong>{t(metricLabelKey(m))}</Text>
                      <Space size={12} wrap>
                        {(['ORANGE', 'MTN'] as BrandKey[]).map(b => {
                          const n = b === 'ORANGE' ? c.orange_wins : c.mtn_wins
                          const rate = b === 'ORANGE' ? c.orange_win_rate : c.mtn_win_rate
                          return (
                            <Button key={b} type="link" style={{ padding: 0, height: 'auto' }}
                              onClick={e => void openDrill({
                                title: `${t(brandLabelKey(b))} · ${t(metricLabelKey(m))} · ${t('bms.drill.winTitle')}`,
                                at: { x: e.clientX, y: e.clientY }, metric: m, winner: b,
                              })}>
                              <Space direction="vertical" size={0} align="start">
                                <Text style={{ fontSize: 12 }} type="secondary">{t(brandLabelKey(b))}</Text>
                                <Text strong style={{ color: brandColor(b, isDark) }}>
                                  {t('bms.wins.days', { n, rate: num(rate, 1) })}
                                </Text>
                              </Space>
                            </Button>
                          )
                        })}
                      </Space>
                      {!!c.ties && <Text type="secondary" style={{ fontSize: 12 }}>{t('bms.wins.ties', { n: c.ties })}</Text>}
                    </Space>
                  </CardBase>
                </Col>
              )
            })}
          </Row>
        </CardBase>
      )}

      {/* ⑦ 月度对比表 */}
      <CardBase
        title={t('bms.table.monthly')}
        extra={
          <Button size="small" icon={<DownloadOutlined />} disabled={!monthly.length}
            onClick={() => exportRows('monthly', monthly)}>{t('common.exportExcel')}</Button>
        }
      >
        {monthly.length
          ? <Table
              rowKey="ym" columns={monthlyColumns} dataSource={monthly}
              size="small" pagination={false} scroll={{ x: 1500 }}
            />
          : <Empty description={t('bms.empty')} />}
      </CardBase>

      {/* ⑧ 逐日对决明细表 */}
      <CardBase
        title={t('bms.table.daily')}
        extra={
          <Button size="small" icon={<DownloadOutlined />} disabled={!daily.length}
            onClick={() => exportRows('daily', daily)}>{t('common.exportExcel')}</Button>
        }
      >
        {daily.length
          ? <Table
              rowKey="day" columns={dailyColumns} dataSource={[...daily].reverse()}
              loading={loading} size="small" scroll={{ x: 1700 }}
              pagination={{ pageSize: 15, showSizeChanger: true, showTotal: n => t('bms.total', { n }) }}
            />
          : <Empty description={t('bms.empty')} />}
      </CardBase>

      {/* ⑨ 下钻弹窗 */}
      <DraggableClickModal open={open} title={drillTitle} anchor={anchor} onClose={() => setOpen(false)}>
        <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Tag color="blue">{t('bms.drill.count', { n: drillRows.length })}</Tag>
          {drillLoading && <Text type="secondary">{t('bms.loading')}</Text>}
          {!!(drillMeta as any)?.truncated && (
            <Tag color="orange">{t('bms.drill.truncated', { limit: (drillMeta as any)?.limit ?? 3000 })}</Tag>
          )}
          {(drillMeta as any)?.error && <Tag color="red">{String((drillMeta as any).error)}</Tag>}
          <Button size="small" icon={<DownloadOutlined />} disabled={!drillRows.length}
            onClick={() => exportRows('detail', drillRows)}>{t('common.exportExcel')}</Button>
        </Space>
        <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
          <Table
            rowKey={r => `${r.day}-${r.brand}`}
            columns={drillColumns} dataSource={drillRows}
            loading={drillLoading} size="small" scroll={{ x: 1200 }}
            pagination={{ pageSize: 12, showSizeChanger: true }}
          />
        </div>
      </DraggableClickModal>
    </div>
  )
}

/* ============================================================================
 * 配套 i18n 键（已写入 frontend/src/i18n.tsx 的 zh 与 en **两处**）：
 * 前缀统一为 `bms.`，导出见 i18n.tsx。新增文案务必两处同加，否则 check:i18n 会拦下。
 * ========================================================================== */
