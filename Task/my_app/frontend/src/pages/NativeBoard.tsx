import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, DatePicker, Empty, Row, Space, Spin, Statistic,
  Table, Tabs, Tag, Tooltip, Typography,
} from 'antd'
import {
  DownloadOutlined, InfoCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { exportNativeBoard, getNativeBoard } from '../api'
import { cachedGet, invalidateCache } from '../cache'
import { useI18n } from '../i18n'
import { WH_COLORS, LIGHT_COLORS, axisLabel, axisLine, cardStyle, darkTooltip, splitLine, useTheme } from '../theme'

const { Text, Title } = Typography
const { RangePicker } = DatePicker

/**
 * 浏览器端整页缓存 TTL。
 * 服务端已按小时缓存（源数据天粒度更新），这一层只为「切走再切回」免掉
 * 请求与上兆 JSON 的重复解析；点「刷新」会先失效本地缓存，不会看到旧数据。
 */
const NB_CLIENT_TTL_MS = 10 * 60 * 1000

/* ====================================================================
 * 原生看板（my-finebi 全部看板 → my_app 原生页，泛化版）
 * --------------------------------------------------------------------
 * 一套组件渲染 17 个看板 / 187 个图表，看板定义全部来自后端
 * backend/services/native_catalog.py（自动提取自 my-finebi）。
 * 本页**不依赖 my-finebi 进程**：数据经 /api/native-boards/{slug}
 * → 远端只读 SQL API。
 *
 * 支持的 5 种组件类型（与 FineBI 原版一致）：
 *   line / bar  折线、柱状（第 1 列类目，其余每列一条序列）
 *   kpi         单值卡片
 *   table       明细表格（可分页、可排序、可导出）
 *   text        标题栏（已剥离原版指向 FineBI 的外链）
 *
 * 新增能力（原 FineBI 版没有）：
 *   1. 时间窗口：自定义起止日期，后端在原 SQL 外包一层子查询过滤，
 *      不改写原口径；识别不出日期列时控件自动禁用。
 *   2. Excel 导出：整页数据导成一个 xlsx（每组件一个 sheet + 说明 sheet）。
 * ==================================================================== */

interface NBWidget {
  id: string
  title: string
  chart: 'line' | 'bar' | 'kpi' | 'table' | 'text'
  pivot: boolean
  pct: boolean
  db: string
  columns: string[]
  rows: (string | number | null)[][]
  error: string
  date_field: string
  windowed: boolean
  grain?: 'day' | 'month' | ''
  title_text?: string
}

interface NBResp {
  meta: {
    slug: string
    name: string
    category: string
    host: string
    count: number
    failed: number
    elapsed_ms: number
    cached: boolean
    start: string
    end: string
    window_supported: boolean
    dbs: string[]
    fetched_at: string
  }
  title: string
  widgets: NBWidget[]
}

/* --------------------------------------------------------------------
 * 逐页布局微调（只动排版，不动数据口径）
 * --------------------------------------------------------------------
 * 部分看板沿用了 FineBI 原版的摆法，在原生页上读起来别扭，这里按 slug 覆盖：
 *   hide       重复 / 无意义组件，不渲染
 *   headerKpi  额外指定「提到页头行内」的单值 KPI（Time 类已由默认规则覆盖）
 *   order      组件顺序（列出的排在最前，未列出的按原顺序跟在后面）
 *   fullWidth  图表整行独占（默认 1/3 宽，序列多了会挤成一团）
 * 匹配组件 id 或标题，任一命中即可（标题给人看、id 给机器看，改一处不影响另一处）。
 * -------------------------------------------------------------------- */
interface BoardLayout {
  hide?: string[]
  headerKpi?: string[]
  order?: string[]
  fullWidth?: string[]
  /**
   * 页签分组：把标题相同的组件按粒度拆成「日 / 周 / 月」多个页签。
   * 组件 id 用「<前缀>_<粒度>」命名（如 mttr_p1_day / mttr_p1_week / mttr_p1_month），
   * 前端按粒度归组；组内组件默认每行 2 个。
   */
  tabs?: {
    /** 组件 id 的后缀 → 页签，顺序即页签展示顺序 */
    grains: { key: string; labelKey: string }[]
    /** 每行几列（默认 2） */
    cols?: number
  }
}

/** 页签粒度：id 以 `_<key>` 结尾即归属该页签 */
function grainOf(w: NBWidget, t: NonNullable<BoardLayout['tabs']>): string {
  return t.grains.find((g) => w.id.endsWith(`_${g.key}`))?.key ?? ''
}

/**
 * 页头行内 KPI 的默认规则：FineBI 组各看板都带一个「最新数据日期」单值组件
 * （标题 `Time` / `TIme` 两种写法都有），统一提到页头标题右侧，与标题同一行，
 * 不再像普通 KPI 那样在标题下方单独占一行。其余 KPI（update / TT Quality 等）不受影响。
 */
const HEADER_KPI_RE = /^\s*ti+me\s*$/i

const BOARD_LAYOUT: Record<string, BoardLayout> = {
  // 3G / 4G Achievement Trend 各占一整行（2G 那条列多，本来就已经整行）
  availability_daily: { fullWidth: ['ach3g', 'ach4g'] },
  // 第一行固定 NW-Daily / NW-Weekly / NW-Monthly
  availability_tt: { order: ['nw_daily', 'nw_week', 'nw_month'] },
  // 原版有两个重复的 Time 组件（Time + TIme）：只留一个
  kpi_4g: { hide: ['time2', 'TIme'] },
  /* MTTR 看板（2026-09-27 改造）：原先 MTTR / MTTR Weekly 等组件平铺，
     现改为「日 / 周 / 月」三个页签，每档 P1-P4 四张分级图，每行 2 图。
     粒度由组件 id 后缀区分（mttr_p1_day/_week/_month），定义在 native_catalog。 */
  mttr: {
    tabs: {
      grains: [
        { key: 'day', labelKey: 'nb.granDay' },
        { key: 'week', labelKey: 'nb.granWeek' },
        { key: 'month', labelKey: 'nb.granMonth' },
      ],
      cols: 2,
    },
  },
}

const EMPTY_LAYOUT: BoardLayout = {}

/** 组件是否命中 id / 标题列表 */
function hits(w: NBWidget, keys?: string[]) {
  return !!keys?.length && (keys.includes(w.id) || keys.includes(w.title))
}

function toNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function fmtVal(v: number, pct?: boolean) {
  return pct ? `${v.toFixed(2)}%` : String(v)
}

/** 类目轴标签抽稀：日期类目动辄数百上千，不抽稀会糊成不可读的斜带 */
function xAxisLabel(n: number) {
  return {
    rotate: 0,
    hideOverlap: true,
    interval: n > 12 ? Math.ceil(n / 12) - 1 : ('auto' as const),
  }
}

/**
 * 极值标签：FineBI 的 `label.showWay = "extreme"` —— 只在每条序列的
 * 最大 / 最小点上标注数值（原版图上散落的彩色数字）。
 */
function extremeData(vals: (number | null)[], pct?: boolean) {
  const nums = vals.filter((v): v is number => v !== null && Number.isFinite(v))
  if (nums.length < 3) return vals
  const mx = Math.max(...nums)
  const mn = Math.min(...nums)
  if (mx === mn) return vals
  return vals.map((v) => ({
    value: v,
    label: {
      show: v !== null && Number.isFinite(v) && (v === mx || v === mn),
      formatter: v === null || !Number.isFinite(v) ? '' : fmtVal(v, pct),
    },
  }))
}

/** pivot：SQL 返回 [x, 系列名, 值] 三列 → 按系列名透视成多序列 */
function buildPivotOption(w: NBWidget, isDark: boolean, colors: string[]) {
  const cats: string[] = []
  const seriesNames: string[] = []
  const seen = new Set<string>()
  const lookup = new Map<string, number | null>()
  for (const r of w.rows) {
    const x = String(r[0])
    const s = String(r[1])
    // 分区列为 NULL 的行会变成名为 "null" 的伪序列，直接丢弃
    if (s === '' || s === 'null' || s === 'NULL' || s === 'undefined') continue
    if (!seen.has(x)) {
      seen.add(x)
      cats.push(x)
    }
    if (!seriesNames.includes(s)) seriesNames.push(s)
    const v = r[2]
    lookup.set(`${x}\u0000${s}`, v === null || v === undefined || v === '' ? null : toNumber(v))
  }
  const dense = cats.length > 120
  return {
    color: colors,
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const },
    legend: {
      bottom: 0,
      type: 'scroll' as const,
      show: seriesNames.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 56, right: 18, top: 28, bottom: 42, containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: cats,
      boundaryGap: false,
      axisLabel: { ...axisLabel(isDark), ...xAxisLabel(cats.length) },
      axisLine: axisLine(isDark),
    },
    yAxis: {
      type: 'value' as const,
      scale: true,
      splitLine: splitLine(isDark),
      axisLabel: {
        ...axisLabel(isDark),
        formatter: w.pct ? (v: number) => `${Number(v).toFixed(2)}%` : undefined,
      },
    },
    series: seriesNames.map((s) => ({
      name: s,
      type: 'line' as const,
      smooth: false,
      showSymbol: false,
      connectNulls: false,
      sampling: dense ? ('lttb' as const) : undefined,
      data: extremeData(cats.map((x) => lookup.get(`${x}\u0000${s}`) ?? null), w.pct),
      label: { show: true, position: 'top' as const, fontSize: 9 },
    })),
  }
}

/** line / bar：第 1 列为类目，其余每列一条序列 */
function buildAxisOption(w: NBWidget, isDark: boolean, colors: string[]) {
  const isBar = w.chart === 'bar'
  const cats = w.rows.map((r) => String(r[0]))
  const rest = w.columns.slice(1)
  const dense = cats.length > 120
  return {
    color: colors,
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const },
    legend: {
      bottom: 0,
      type: 'scroll' as const,
      show: rest.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 56, right: 18, top: 28, bottom: 42, containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: cats,
      boundaryGap: isBar,
      axisLabel: { ...axisLabel(isDark), ...xAxisLabel(cats.length) },
      axisLine: axisLine(isDark),
    },
    yAxis: {
      type: 'value' as const,
      scale: true,
      splitLine: splitLine(isDark),
      axisLabel: {
        ...axisLabel(isDark),
        formatter: w.pct ? (v: number) => `${Number(v).toFixed(2)}%` : undefined,
      },
    },
    series: rest.map((c, i) => {
      const vals = w.rows.map((r) => {
        const v = r[i + 1]
        return v === null || v === undefined || v === '' ? null : toNumber(v)
      })
      return {
        name: c,
        type: isBar ? ('bar' as const) : ('line' as const),
        smooth: false,
        showSymbol: false,
        barMaxWidth: 34,
        sampling: !isBar && dense ? ('lttb' as const) : undefined,
        // 柱状图不适合极值标签（柱子多了会叠字），折线才标
        data: isBar ? vals : extremeData(vals, w.pct),
        label: { show: true, position: 'top' as const, fontSize: 9 },
      }
    }),
  }
}

/**
 * 页头行内 KPI（Time 之类单值）：跟在页头标题右侧，与标题同一行，
 * 不再像普通 KPI 那样在标题下方单独占一行。
 */
function HeaderKpi({ w }: { w: NBWidget }) {
  const { isDark } = useTheme()
  if (w.error) return <Text type="danger" style={{ fontSize: 12 }}>{w.error}</Text>
  const v = w.rows[0]?.[0]
  const n = Number(v)
  const isNum = Number.isFinite(n) && v !== null && v !== ''
  return (
    <Space size={6} align="center">
      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{w.title}</Text>
      <Text strong style={{ fontSize: 16, color: isDark ? '#64ffda' : '#0d9488', whiteSpace: 'nowrap' }}>
        {isNum && !Number.isInteger(n) ? n.toFixed(2) : String(v ?? '-')}
      </Text>
    </Space>
  )
}

/** 单个看板组件卡片（含加载 / 错误 / 空态） */
function WidgetCard({ w, height, colors }: {
  w: NBWidget; height: number; colors: string[]
}) {
  const { isDark } = useTheme()
  const { t } = useI18n()

  const option = useMemo(() => {
    if (w.chart === 'kpi' || w.chart === 'text') return null
    return w.pivot ? buildPivotOption(w, isDark, colors) : buildAxisOption(w, isDark, colors)
  }, [w, isDark, colors])

  // KPI 卡片：单值
  if (w.chart === 'kpi') {
    const v = w.rows[0]?.[0]
    const n = Number(v)
    const isNum = Number.isFinite(n) && v !== null && v !== ''
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, height }}>
        {w.error ? (
          <Text type="danger" style={{ fontSize: 12 }}>{w.error}</Text>
        ) : (
          <>
            <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{w.title}</Text>
            <Statistic
              value={isNum ? n : String(v ?? '-')}
              precision={isNum && !Number.isInteger(n) ? 2 : 0}
              valueStyle={{ fontSize: 20, fontWeight: 600, color: isDark ? '#64ffda' : '#0d9488' }}
            />
          </>
        )}
      </div>
    )
  }

  return (
    <Card
      size="small"
      style={{ ...cardStyle, height }}
      styles={{ body: { height: '100%', padding: 8, display: 'flex', flexDirection: 'column' } }}
      title={<span style={{ fontSize: 13 }}>{w.title}</span>}
      extra={
        <Space size={4}>
          {w.pct && <Tag color="cyan" style={{ marginInlineEnd: 0 }}>%</Tag>}
          {w.windowed && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{t('nb.windowed')}</Tag>}
        </Space>
      }
    >
      {w.error ? (
        <Alert type="error" showIcon message={t('nb.queryFail')} description={w.error} style={{ fontSize: 12 }} />
      ) : !option || w.rows.length === 0 ? (
        <Empty description={t('nb.noData')} style={{ margin: 'auto' }} />
      ) : (
        <div style={{ flex: '1 1 auto', minHeight: 0 }}>
          <ReactECharts
            option={option}
            notMerge
            style={{ width: '100%', height: '100%' }}
            opts={{ renderer: 'canvas' }}
          />
        </div>
      )}
    </Card>
  )
}

/** 表格组件：列多行多，独立成卡（自带分页/排序） */
function TableCard({ w, height }: { w: NBWidget; height: number }) {
  const { t } = useI18n()

  const columns: ColumnsType<Record<string, unknown>> = useMemo(
    () => w.columns.map((c) => {
      // 数值列右对齐并参与排序；文本列左对齐
      const sample = w.rows.find((r) => r[w.columns.indexOf(c)] !== null
        && r[w.columns.indexOf(c)] !== undefined)?.[w.columns.indexOf(c)]
      const numeric = sample !== undefined && sample !== null && sample !== ''
        && Number.isFinite(Number(sample))
      const idx = w.columns.indexOf(c)
      return {
        title: c,
        dataIndex: c,
        key: `${c}-${idx}`,
        align: numeric ? ('right' as const) : ('left' as const),
        ellipsis: true,
        sorter: numeric
          ? (a: Record<string, unknown>, b: Record<string, unknown>) =>
              toNumber(a[c]) - toNumber(b[c])
          : (a: Record<string, unknown>, b: Record<string, unknown>) =>
              String(a[c] ?? '').localeCompare(String(b[c] ?? '')),
        render: (v: unknown) => (v === null || v === undefined || v === ''
          ? <Text type="secondary">-</Text>
          : String(v)),
      }
    }),
    [w],
  )

  const data = useMemo(
    () => w.rows.map((r, i) => {
      const o: Record<string, unknown> = { __k: i }
      w.columns.forEach((c, ci) => { o[c] = r[ci] })
      return o
    }),
    [w],
  )

  return (
    <Card
      size="small"
      style={{ ...cardStyle, height }}
      styles={{ body: { height: '100%', padding: 6, display: 'flex', flexDirection: 'column' } }}
      title={<span style={{ fontSize: 13 }}>{w.title}</span>}
      extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('nb.rows', { n: w.rows.length })}</Text>}
    >
      {w.error ? (
        <Alert type="error" showIcon message={t('nb.queryFail')} description={w.error} style={{ fontSize: 12 }} />
      ) : w.rows.length === 0 ? (
        <Empty description={t('nb.noData')} style={{ margin: 'auto' }} />
      ) : (
        <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'auto' }}>
          <Table
            size="small"
            rowKey="__k"
            columns={columns}
            dataSource={data}
            pagination={{ pageSize: 20, size: 'small', showSizeChanger: false, showTotal: (n) => `${n}` }}
            scroll={{ x: 'max-content' }}
            sticky
          />
        </div>
      )}
    </Card>
  )
}

export default function NativeBoard({ slug }: { slug: string }) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const colors = isDark ? WH_COLORS : LIGHT_COLORS

  const [data, setData] = useState<NBResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [exporting, setExporting] = useState(false)
  // 时间窗口：null = 全量（沿用各组件原口径）
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  // 页签粒度（仅 layout.tabs 的看板用；默认取第一个页签）
  const [tab, setTab] = useState('')
  // 切看板时重置状态（同一路由复用组件）
  const [lastSlug, setLastSlug] = useState(slug)

  const load = useCallback(async (force = false, r: [Dayjs, Dayjs] | null = range) => {
    setLoading(true)
    setErr('')
    try {
      const start = r ? r[0].format('YYYY-MM-DD') : ''
      const end = r ? r[1].format('YYYY-MM-DD') : ''
      // 本地缓存按「看板 + 时间窗口」区分；刷新时先失效，保证拿到的是新数据
      const key = `nb:${slug}:${start}:${end}`
      if (force) invalidateCache(key)
      const res = await cachedGet(
        key,
        () => getNativeBoard(slug, { start, end, force }),
        NB_CLIENT_TTL_MS,
      )
      setData(res.data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setErr(msg)
    } finally {
      setLoading(false)
    }
  }, [slug, range])

  useEffect(() => {
    if (slug !== lastSlug) {
      setLastSlug(slug)
      setRange(null)
      setData(null)
      void load(false, null)
      return
    }
    void load(false, range)
    // 仅在 slug 变化或窗口提交时取数（range 通过 onChange 直接触发）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const onExport = useCallback(async () => {
    setExporting(true)
    try {
      await exportNativeBoard(slug, range
        ? { start: range[0].format('YYYY-MM-DD'), end: range[1].format('YYYY-MM-DD') }
        : undefined)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setErr(msg)
    } finally {
      setExporting(false)
    }
  }, [slug, range])

  // 逐页布局微调：先剔掉重复组件，再按 order 把指定组件提到最前
  const layout = BOARD_LAYOUT[slug] ?? EMPTY_LAYOUT
  const allWidgets = (data?.widgets ?? []).filter((w) => !hits(w, layout.hide))
  const widgets = (() => {
    if (!layout.order?.length) return allWidgets
    const head: NBWidget[] = []
    for (const k of layout.order) {
      // 同一组件被两个 key 命中时只取一次（includes 按对象引用比较）
      const w = allWidgets.find((x) => (x.id === k || x.title === k) && !head.includes(x))
      if (w) head.push(w)
    }
    return [...head, ...allWidgets.filter((w) => !head.includes(w))]
  })()
  const titleWidget = widgets.find((w) => w.chart === 'text')
  const kpiWidgets = widgets.filter((w) => w.chart === 'kpi')
  // 提到页头行内显示的 KPI：Time/TIme 默认走页头，另可用 headerKpi 显式追加
  const isHeaderKpi = (w: NBWidget) =>
    hits(w, layout.headerKpi) || (w.chart === 'kpi' && HEADER_KPI_RE.test(w.title))
  const headerKpis = kpiWidgets.filter(isHeaderKpi)
  // 其余 KPI（update / TT Quality 等）仍在标题下方一行展示
  const rowKpis = kpiWidgets.filter((w) => !isHeaderKpi(w))
  const tableWidgets = widgets.filter((w) => w.chart === 'table')
  const chartWidgets = widgets.filter((w) => w.chart === 'line' || w.chart === 'bar')
  const chartHeight = 320
  const tableHeight = 420

  /* 页签分组（layout.tabs）：按 id 后缀把图表拆到各粒度页签。
     非页签看板走原路径（tabs 为空 → tabChartWidgets 即 chartWidgets）。 */
  const tabs = layout.tabs
  // 当前页签：未选或选中项已失效时回落到第一个页签
  const activeTab = tabs?.grains.some((g) => g.key === tab) ? tab : (tabs?.grains[0]?.key ?? '')
  const tabChartWidgets = tabs
    ? chartWidgets.filter((w) => grainOf(w, tabs) === activeTab)
    : chartWidgets

  // 宽表（列数多）的图表给整行，避免挤在 1/3 宽里看不清
  const isWide = (w: NBWidget) =>
    hits(w, layout.fullWidth) || w.columns.length > 4 || w.rows.length > 1500

  /** 每行栅格宽度：页签看板用 layout.tabs.cols（默认 2），否则沿用原 1/3 规则 */
  const colSpan = (w: NBWidget) => {
    if (tabs) return Math.floor(24 / (tabs.cols || 2))
    return isWide(w) ? 24 : 8
  }

  return (
    <div style={{ padding: 4 }}>
      <Card size="small" style={{ ...cardStyle, marginBottom: 12 }} styles={{ body: { padding: '8px 12px' } }}>
        {/* 看板标题独占一行并居中（页头第二行才是 KPI / 徽标与右侧操作区） */}
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <Title level={4} style={{ margin: 0, color: isDark ? '#64ffda' : '#0d9488' }}>
            ❯❯❯ {titleWidget?.title_text || data?.title || slug} ❮❮❮
          </Title>
        </div>
        <Row align="middle" justify="space-between" gutter={[12, 8]}>
          <Col flex="auto">
            <Space size={10} wrap>
              {/* 单值 KPI（Time 之类）跟着标题排在同一行右侧 */}
              {headerKpis.map((w) => <HeaderKpi key={w.id} w={w} />)}
              {data?.meta && (
                <Tooltip title={`${data.meta.dbs.join(', ')} @ ${data.meta.host} · ${data.meta.fetched_at}`}>
                  <Tag color="blue" icon={<InfoCircleOutlined />}>
                    {t('nb.widgets', { n: widgets.length })} · {data.meta.elapsed_ms}ms
                    {data.meta.cached ? ` · ${t('nb.cached')}` : ''}
                  </Tag>
                </Tooltip>
              )}
              {data?.meta && data.meta.failed > 0 && (
                <Tag color="error">{t('nb.failed', { n: data.meta.failed })}</Tag>
              )}
              {data?.meta && !data.meta.window_supported && (
                <Tag>{t('nb.noWindow')}</Tag>
              )}
            </Space>
          </Col>
          <Col>
            <Space size={8} wrap>
              {/* 时间窗口：留空 = 沿用各组件原口径（多数看板是近 31 天） */}
              <RangePicker
                size="small"
                value={range}
                allowClear
                disabled={data ? !data.meta.window_supported : false}
                presets={[
                  { label: t('nb.last7'), value: [dayjs().add(-7, 'day'), dayjs()] },
                  { label: t('nb.last31'), value: [dayjs().add(-31, 'day'), dayjs()] },
                  { label: t('nb.last90'), value: [dayjs().add(-90, 'day'), dayjs()] },
                  { label: t('nb.thisYear'), value: [dayjs().startOf('year'), dayjs()] },
                ]}
                onChange={(v) => {
                  const r = v && v[0] && v[1] ? [v[0], v[1]] as [Dayjs, Dayjs] : null
                  setRange(r)
                  void load(false, r)
                }}
                placeholder={[t('nb.start'), t('nb.end')]}
              />
              <Button
                icon={<DownloadOutlined />}
                size="small"
                loading={exporting}
                disabled={!data || data.widgets.every((w) => w.chart === 'text')}
                onClick={onExport}
              >
                {t('nb.export')}
              </Button>
              <Button icon={<ReloadOutlined />} onClick={() => load(true)} loading={loading} size="small">
                {t('nb.refresh')}
              </Button>
            </Space>
          </Col>
        </Row>
        {rowKpis.length > 0 && (
          <div style={{
            marginTop: 8,
            borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(13,148,136,0.12)'}`,
            paddingTop: 4,
          }}>
            {rowKpis.map((w) => <WidgetCard key={w.id} w={w} height={48} colors={colors} />)}
          </div>
        )}
      </Card>

      {err && (
        <Alert
          type="error"
          showIcon
          message={t('nb.loadFail')}
          description={
            <Space direction="vertical" size={2}>
              <Text>{err}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('nb.hint')}</Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : (
        <>
          {tabs && chartWidgets.length > 0 ? (
            <Tabs
              size="small"
              activeKey={activeTab}
              onChange={setTab}
              items={tabs.grains.map((g) => ({
                key: g.key,
                label: t(g.labelKey),
                children: (
                  <Row gutter={[12, 12]}>
                    {chartWidgets
                      .filter((w) => grainOf(w, tabs) === g.key)
                      .map((w) => (
                        <Col key={w.id} xs={24} md={12} xl={colSpan(w)}>
                          <WidgetCard w={w} height={chartHeight} colors={colors} />
                        </Col>
                      ))}
                  </Row>
                ),
              }))}
            />
          ) : (
            chartWidgets.length > 0 && (
              <Row gutter={[12, 12]}>
                {chartWidgets.map((w) => (
                  <Col key={w.id} xs={24} md={isWide(w) ? 24 : 12} xl={isWide(w) ? 24 : 8}>
                    <WidgetCard w={w} height={chartHeight} colors={colors} />
                  </Col>
                ))}
              </Row>
            )
          )}
          {tableWidgets.length > 0 && (
            <Row gutter={[12, 12]} style={{ marginTop: tabChartWidgets.length ? 12 : 0 }}>
              {tableWidgets.map((w) => (
                <Col key={w.id} xs={24} xl={isWide(w) ? 24 : 12}>
                  <TableCard w={w} height={tableHeight} />
                </Col>
              ))}
            </Row>
          )}
        </>
      )}

      {data?.meta && (
        <Text type="secondary" style={{ display: 'block', marginTop: 10, fontSize: 12 }}>
          {t('nb.footer', { dbs: data.meta.dbs.join(', '), host: data.meta.host })}
        </Text>
      )}
    </div>
  )
}
