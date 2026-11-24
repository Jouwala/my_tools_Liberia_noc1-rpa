/* ============================================================================
 * CN 小时 KPI 看板（?page=cn_hourly_kpi）
 * ----------------------------------------------------------------------------
 * 数据源：后端 /api/cn-hourly-kpi/overview
 *   → services/cn_kpl/cn_hourly_kpi_service.py（读远端 db_ps_cs_cn 的 <模板名>_UME 表）
 *   → 由任务 cn_hourly_kpi_sync 每天 06:20 写入（gr=3600，2 天增量窗口；
 *     首月回补由 python -m backend.services.cn_kpl.cn_hourly_kpi_service --days 31 完成）。
 *   模板来自 UME「KPI 模板管理」导出件 KPI Template.xlsx（用户 2026-11-18 定口径：
 *   Utilization/Capacity 两族重复只留 Utilization；Object Scope=ALL 覆盖全部 NE）。
 *
 * 页面结构：日期区间选择（默认最近 7 天，上限 31 天）+ 7 个组件卡
 * （xGW 会话/吞吐的用量与占用率 + MGW/MRFP 的 TONE/TC/RTP 利用率），
 * 每卡 x=小时、线=网元（或全 NE 合并的占用率单线）。
 *
 * 约定（AGENTS.md 第三节第 3 条）：卡片走 components/cards，导出走 utils/excelReport，
 * ECharts 用实值配色（canvas 解析不了 CSS 变量），口径说明默认收起（CalcChainNote），
 * 卡头挂 ExplainLabel（口径按 i18n 双语维护，内容与后端 WIDGETS SQL 逐条对过）。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Row, Space, Spin, Tag, Typography } from 'antd'
import { DownloadOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import ReactECharts from '../components/ECharts'
import { CardBase } from '../components/cards'
import CalcChainNote from '../components/CalcChainNote'
import { ExplainLabel, ExplainPopover } from '../components/MetricExplain'
import { exportReport, type ReportSheetSpec } from '../utils/excelReport'
import { getCnHourlyKpiOverview } from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { axisLabel, axisLine, darkTooltip, useTheme } from '../theme'

const { Text } = Typography
const { RangePicker } = DatePicker

// ---------------- 类型（与后端 cn_hourly_kpi_service 对齐） ----------------
interface HourlyWidget {
  id: string
  title: string
  chart: 'line' | 'kpi' | 'text' | 'bar' | 'table'
  pivot: boolean
  pct: boolean
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  error: string
  empty: boolean
  empty_reason: string
}
interface OverviewResp {
  meta: {
    db: string
    start: string
    end: string
    count: number
    failed: number
    empty: number
    elapsed_ms: number
    cached: boolean
  }
  widgets: HourlyWidget[]
}

function toNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 小时标签 "2026-11-17 09:00" → "11-17 09时"（短标签，168 个点也不糊） */
function hourTick(v: string, t: (k: string) => string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):00$/.exec(v)
  if (!m) return v
  return `${m[2]}-${m[3]} ${m[4]}${t('cnhourly.hourSuffix')}`
}

// 网元序列配色（实值：canvas 解析不了 CSS 变量；深浅各一套，与 CnKpi5mins 同做法）
const SERIES_COLOR_DARK = ['#08bd83', '#2b8cff', '#00d9ff', '#f6cf00', '#ff5c6c', '#9254de', '#fa8c16']
const SERIES_COLOR_LIGHT = ['#0e9f6e', '#2563eb', '#0e7490', '#d97706', '#dc2626', '#7c3aed', '#ea580c']

function seriesColor(name: string, names: string[], isDark: boolean): string {
  const palette = isDark ? SERIES_COLOR_DARK : SERIES_COLOR_LIGHT
  const idx = names.indexOf(name)
  return palette[idx % palette.length] || '#8b95a7'
}

/** 全 NE 合并线（占用率）的固定色与名称（Series 列为 'ALL'） */
const ALL_COLOR_DARK = '#00d9ff'
const ALL_COLOR_LIGHT = '#0e7490'

/** 类目轴标签抽稀（7 天 = 168 个小时点，不抽稀会糊成斜带） */
function xAxisLabel(n: number) {
  return {
    rotate: 0,
    hideOverlap: true,
    interval: n > 24 ? Math.ceil(n / 24) - 1 : ('auto' as const),
  }
}

/**
 * pivot：SQL 返回 [Hour, Series, Value] → 按第 2 列透视成多条线。
 * 与 CnKpi5mins 的 buildDayOption 同构；序列名来自 NE 列（xGWU22/MGW_91…），
 * 或全 NE 合并的 'ALL' 单线。
 */
function buildHourOption(w: HourlyWidget, isDark: boolean, t: (k: string) => string) {
  const cats: string[] = []
  const seen = new Set<string>()
  const names: string[] = []
  const lookup = new Map<string, number | null>()
  for (const r of w.rows) {
    const rawHour = String(r[0])
    const hour = hourTick(rawHour, t)
    const series = String(r[1] ?? '')
    if (!series || series === 'null' || series === 'undefined') continue
    if (!seen.has(hour)) { seen.add(hour); cats.push(hour) }
    if (!names.includes(series)) names.push(series)
    const v = r[2]
    lookup.set(`${hour}\u0000${series}`, v === null || v === undefined || v === '' ? null : toNumber(v))
  }
  const dense = cats.length > 120
  const isPct = w.pct
  const fmtValue = (v: unknown) => {
    if (v === null || v === undefined || v === '') return '—'
    const n = Number(v)
    if (!Number.isFinite(n)) return String(v)
    return isPct ? `${n.toFixed(2)}%` : n.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }
  const colorOf = (n: string) => (n === 'ALL'
    ? (isDark ? ALL_COLOR_DARK : ALL_COLOR_LIGHT)
    : seriesColor(n, names, isDark))
  return {
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const, valueFormatter: fmtValue },
    legend: {
      top: 2, type: 'scroll' as const, icon: 'roundRect' as const,
      show: names.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
      itemWidth: 14, itemHeight: 8, itemGap: 10, data: names,
    },
    grid: { left: 12, right: 16, top: 34, bottom: 24, containLabel: true },
    xAxis: {
      type: 'category' as const, data: cats, boundaryGap: false,
      axisLabel: { ...axisLabel(isDark), ...xAxisLabel(cats.length) },
      axisLine: axisLine(isDark), axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const, scale: true, splitLine: { show: false },
      axisLabel: {
        ...axisLabel(isDark),
        formatter: isPct ? (v: number) => `${Number(v).toFixed(2)}%` : undefined,
      },
    },
    series: names.map((n) => {
      const c = colorOf(n)
      return {
        name: n, type: 'line' as const, smooth: true, showSymbol: false,
        connectNulls: false, sampling: dense ? ('lttb' as const) : undefined, color: c,
        lineStyle: { width: 1.5 },
        areaStyle: {
          color: {
            type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: c + (isDark ? '40' : '26') },
              { offset: 1, color: c + '05' },
            ],
          },
        },
        data: cats.map((x) => lookup.get(`${x}\u0000${n}`) ?? null),
      }
    }),
  }
}

/** 组件 → 该卡「这个数怎么算」的文案键。
 *  ⚠ **逐条写字面量**：动态拼 key 会被 check:i18n 拦下（AGENTS.md 第三节 1b）。
 *  内容与 cn_hourly_kpi_service._widgets 的 SQL 逐条对过，改 SQL 必须同步改这里。 */
function widgetExplainKey(id: string): string {
  switch (id) {
    case 'xgw_session_used': return 'cnhourly.explain.xgwSessionUsed'
    case 'xgw_session_pct': return 'cnhourly.explain.xgwSessionPct'
    case 'xgw_tp_used': return 'cnhourly.explain.xgwTpUsed'
    case 'xgw_tp_pct': return 'cnhourly.explain.xgwTpPct'
    case 'mgw_tone': return 'cnhourly.explain.mgwTone'
    case 'mgw_tc': return 'cnhourly.explain.mgwTc'
    case 'mgw_rtp': return 'cnhourly.explain.mgwRtp'
    default: return ''
  }
}

/** 单个组件卡片（图表 / 空态 / 错误三种状态） */
function WidgetCard({ w, height }: { w: HourlyWidget; height: number }) {
  const { isDark } = useTheme()
  const { t } = useI18n()
  const option = useMemo(() => {
    if (w.empty || w.error) return null
    return buildHourOption(w, isDark, t)
  }, [w, isDark, t])
  return (
    <CardBase
      size="small"
      // 与 CnKpi5mins 同款：flex 列 + body flex:1，否则 canvas 底部被卡片裁掉
      style={{ height, display: 'flex', flexDirection: 'column' }}
      bodyStyle={{ flex: 1, minHeight: 0, padding: 8, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      title={(
        <ExplainLabel
          label={<span style={{ fontSize: 13 }}>{w.title}</span>}
          text={[
            w.empty ? (w.empty_reason || t('cnhourly.noData')) : '',
            widgetExplainKey(w.id) ? t(widgetExplainKey(w.id)) : '',
            t('cnhourly.explain.common'),
          ].filter(Boolean).join('\n')}
        />
      )}
      extra={w.pct ? <Tag color="cyan" style={{ marginInlineEnd: 0 }}>%</Tag> : null}
    >
      {w.error ? (
        <Alert type="error" showIcon message={t('cnhourly.queryFail')} description={w.error} style={{ fontSize: 12 }} />
      ) : w.empty ? (
        <div style={{ margin: 'auto', maxWidth: 320, textAlign: 'center' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={
            <span style={{ fontSize: 12 }}>{w.empty_reason || t('cnhourly.noData')}</span>
          } />
        </div>
      ) : !option || w.rows.length === 0 ? (
        <Empty description={t('cnhourly.noData')} style={{ margin: 'auto' }} />
      ) : (
        <div style={{ flex: '1 1 auto', minHeight: 0 }}>
          <ReactECharts option={option} notMerge style={{ width: '100%', height: '100%' }} opts={{ renderer: 'canvas' }} />
        </div>
      )}
    </CardBase>
  )
}

export default function CnHourlyKpi() {
  const { t } = useI18n()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(6, 'day'), dayjs()])
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  // 只认最后一次请求：改日期比响应快时，先发出的响应不许盖掉后发出的。
  const reqSeq = useRef(0)
  const inflight = useRef(false)
  const dataRef = useRef<OverviewResp | null>(null)
  // 载入请求的区间（silent 刷新沿用上一次的区间，而不是 state 的当前值）
  const rangeRef = useRef(range)
  rangeRef.current = range

  /**
   * silent=true 供原地自动刷新（AR_INPLACE_REFRESH_PAGES → myapp-refresh）：
   * 不 setLoading、失败保留上一帧（与 CnKpi5mins 同一套约定）。
   * ⚠ 按钮 onClick 必须 `() => load(...)`，写成 `onClick={load}` 会把 MouseEvent 当参数。
   */
  const load = useCallback(async (opts?: { silent?: boolean; force?: boolean; range?: [Dayjs, Dayjs] }) => {
    const silent = !!opts?.silent
    const r = opts?.range ?? rangeRef.current
    if (silent && !dataRef.current && inflight.current) return
    const seq = ++reqSeq.current
    inflight.current = true
    if (!silent) { setLoading(true); setErr('') }
    try {
      const res = await getCnHourlyKpiOverview({
        start: r[0].format('YYYY-MM-DD'),
        end: r[1].format('YYYY-MM-DD'),
        force: !!opts?.force,
      })
      if (seq !== reqSeq.current) return
      dataRef.current = res.data
      setData(res.data)
      setErr('')
    } catch (e: unknown) {
      if (seq !== reqSeq.current) return
      if (!silent) setErr(e instanceof Error ? e.message : String(e))
    } finally {
      if (seq === reqSeq.current) {
        inflight.current = false
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => { void load() }, [load])
  // 顶栏自动刷新：原地静默重取，不重挂载（重挂载会把 data 清掉、7 张图集体闪白）
  useEffect(() => {
    const onInplaceRefresh = () => { void load({ silent: true }) }
    document.addEventListener('myapp-refresh', onInplaceRefresh)
    return () => document.removeEventListener('myapp-refresh', onInplaceRefresh)
  }, [load])

  const onRangeChange = useCallback((vals: unknown) => {
    const v = vals as [Dayjs, Dayjs] | null
    if (!v || !v[0] || !v[1]) return
    const next: [Dayjs, Dayjs] = [v[0].startOf('day'), v[1].startOf('day')]
    setRange(next)
    void load({ range: next })
  }, [])

  const widgets = data?.widgets ?? []
  const chartWidgets = widgets.filter((w) => w.chart !== 'kpi' && w.chart !== 'text')
  const withData = widgets.filter((w) => !w.empty && !w.error).length
  const chartHeight = 320

  /** 导出 Excel：每个组件一张工作表（Hour × 各序列 宽表） */
  const exportExcel = useCallback(() => {
    if (!data) return
    const stamp = dayjs().format('YYYYMMDD_HHmmss')
    const sheets: ReportSheetSpec[] = [{
      name: 'Overview',
      title: 'CN_Hourly_KPI',
      subtitle: `${t('cnhourly.exportSource')}: ${data.meta.db}`,
      header: ['', ''],
      rows: [
        [t('cnhourly.exportRange'), `${data.meta.start} ~ ${data.meta.end}`],
        [t('cnhourly.exportGenerated'), formatDateTime(new Date(), { zone: true })],
        [],
        ...widgets.map((w) => [
          w.title,
          w.empty ? (w.empty_reason || t('cnhourly.noData')) : `${w.rows.length} ${t('cnhourly.rows')}`,
        ]),
      ] as (string | number)[][],
      columnWidths: [26, 46],
    }]
    for (const w of chartWidgets) {
      if (w.empty || w.error || w.rows.length === 0) continue
      // 宽表：每行 [Hour, 序列1, 序列2, ...]，列只取本组件实际出现的序列
      const names: string[] = []
      const byHour = new Map<string, Record<string, number | null>>()
      const hours: string[] = []
      for (const r of w.rows) {
        const h = hourTick(String(r[0]), t)
        const s = String(r[1] ?? '')
        if (!s || s === 'null' || s === 'undefined') continue
        if (!names.includes(s)) names.push(s)
        if (!byHour.has(h)) { byHour.set(h, {}); hours.push(h) }
        byHour.get(h)![s] = r[2] === null || r[2] === undefined || r[2] === '' ? null : toNumber(r[2])
      }
      const hdr = [t('cnhourly.time'), ...names]
      const body = hours.map((h) => [h, ...names.map((n) => byHour.get(h)?.[n] ?? null)])
      sheets.push({
        name: w.id, title: w.title,
        subtitle: `${t('cnhourly.exportSource')}: ${data.meta.db}`,
        header: hdr, rows: body as (string | number | null)[][],
        columnWidths: [18, ...names.map(() => 18)],
      })
    }
    void exportReport(sheets, `CN_Hourly_KPI_${stamp}.xlsx`)
  }, [data, widgets, chartWidgets, t])

  return (
    <div style={{ padding: 4 }}>
      {/* 工具条：全局 Header 已有页面标题，页内只放日期区间 / 统计 / 操作一行 */}
      <CardBase size="small" style={{ marginBottom: 12 }} bodyStyle={{ padding: '8px 12px' }}>
        <Row align="middle" justify="space-between" gutter={[12, 8]}>
          <Col>
            <Space size={10} wrap>
              <RangePicker
                value={range}
                onChange={onRangeChange}
                allowClear={false}
                disabledDate={(d) => d.isAfter(dayjs(), 'day')}
                presets={[
                  { label: t('cnhourly.range7'), value: [dayjs().subtract(6, 'day'), dayjs()] },
                  { label: t('cnhourly.range14'), value: [dayjs().subtract(13, 'day'), dayjs()] },
                  { label: t('cnhourly.range31'), value: [dayjs().subtract(30, 'day'), dayjs()] },
                ]}
                size="small"
              />
              <ExplainPopover placement="bottom" text={t('cnhourly.rangeHint')}>
                <Tag icon={<InfoCircleOutlined />} color="blue" style={{ cursor: 'help' }}>
                  {t('cnhourly.summary', { ok: withData, total: widgets.length })}
                </Tag>
              </ExplainPopover>
              {data?.meta && (
                <ExplainPopover placement="bottom" text={t('cnhourly.tip.elapsed', {
                  ms: data.meta.elapsed_ms,
                  cached: data.meta.cached ? t('cnkpi5.tip.cachedYes') : t('cnkpi5.tip.cachedNo'),
                })}>
                  <Tag style={{ cursor: 'help' }}>{data.meta.start} ~ {data.meta.end}</Tag>
                </ExplainPopover>
              )}
              {data?.meta && data.meta.failed > 0 && (
                <Tag color="error">{t('cnkpi.failed', { n: data.meta.failed })}</Tag>
              )}
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} onClick={() => load({ force: true })} loading={loading} size="small">
                {t('cnkpi.refresh')}
              </Button>
              <Button icon={<DownloadOutlined />} onClick={exportExcel} disabled={!data || loading} size="small">
                {t('cnkpi.export')}
              </Button>
            </Space>
          </Col>
        </Row>
      </CardBase>

      {err && (
        <Alert
          type="error"
          showIcon
          message={t('cnhourly.loadFail')}
          description={
            <Space direction="vertical" size={2}>
              <Text>{err}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi.hint')}</Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 口径说明：默认收起（AGENTS.md 三.3 全站约定）；异常仍走常驻错误条 */}
      <CalcChainNote
        title={t('cnhourly.note.title')}
        style={{ marginBottom: 12 }}
        sections={[
          {
            title: t('cnhourly.note.sec.source'),
            lines: [t('cnhourly.note.source1'), t('cnhourly.note.source2')],
          },
          {
            title: t('cnhourly.note.sec.scope'),
            lines: [t('cnhourly.note.scope1'), t('cnhourly.note.scope2')],
          },
        ]}
      />

      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : (
        <Row gutter={[12, 12]}>
          {chartWidgets.map((w) => (
            <Col key={w.id} xs={24} md={12} xl={8}>
              <WidgetCard w={w} height={chartHeight} />
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
