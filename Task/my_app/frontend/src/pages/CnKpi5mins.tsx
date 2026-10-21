/* ============================================================================
 * CN KPI 5 分钟看板（?page=cn_kpi_5mins）
 * ----------------------------------------------------------------------------
 * 数据源：后端 /api/cn-kpi-5mins/overview
 *   → services/cn_kpi_5mins_service.py（读远端 db_ps_cs_cn 的 5mins_* 表）
 *   → 由任务 cnn_kpi_sync_5mins 每 15 分钟写入（gr=300，窗口昨天 00:00 → 现在）。
 *
 * 核心展示：每个组件画 **Day0（今天）/ Day1（昨天）/ Day7（7 天前，同一星期几）
 * 曲线**，x 轴为 HH:MM。
 * 后端 SQL 已输出三列 [HH:MM, 'Day0'|'Day1'|'Day7', 值]，本页复用 pivot 机制
 * （按第 2 列透视成多序列），不需要前端再拆日。序列条数不固定：某个日子在库里
 * 还没有数据时后端就不会返回那一类标签，本页少画一条线，并在页头说明。
 *
 * Day7 的数据从哪来：采集任务的窗口只取「昨天 00:00 → 现在」，但写库是 upsert
 * 且没有清理，所以每个日子在其次日被采到之后就永久留在表里 —— 库里攒够 8 天
 * 才画得出 Day7。攒不够的那些天需要回补，见后端服务文件头的实测说明。
 *
 * 空态：上游 xGW License / xGW CPU / 3G FDD 三个模板**没有 5 分钟粒度**
 * （实测恒 0 行，详见后端服务文件头）。它们仍列出卡片，但显示业务原因，
 * 而不是红色报错 —— 这是刻意的：「空的不报错」。
 *
 * 约定（AGENTS.md 第三节第 3 条）：卡片走 components/cards，导出走 utils/excelReport，
 * ECharts 用 DARK/LIGHT 实值（canvas 解析不了 WH.* CSS 变量），文案走 t()。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Empty, Row, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { CardBase } from '../components/cards'
import { exportReport, type ReportSheetSpec } from '../utils/excelReport'
import { getCnKpi5minsOverview } from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { axisLabel, axisLine, darkTooltip, useTheme } from '../theme'

const { Text } = Typography

// ---------------- 类型（与后端 cn_kpi_5mins_service 对齐） ----------------
interface CnWidget5 {
  id: string
  title: string
  chart: 'line' | 'kpi' | 'text' | 'bar' | 'table'
  pivot: boolean
  pct: boolean
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  error: string
  /** 上游无 5 分钟数据 / 窗口内无数据（业务空态，不是故障） */
  empty: boolean
  /** 空态原因（展示给用户，讲清为什么没有数据） */
  empty_reason: string
}
interface OverviewResp5 {
  meta: {
    db: string
    count: number
    failed: number
    empty: number
    elapsed_ms: number
    cached: boolean
  }
  title: string
  widgets: CnWidget5[]
}

function toNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 类目轴标签抽稀（一天 288 个 5 分钟点，不抽稀会糊成斜带） */
function xAxisLabel(n: number) {
  return {
    rotate: 0,
    hideOverlap: true,
    interval: n > 24 ? Math.ceil(n / 24) - 1 : ('auto' as const),
  }
}

/**
 * pivot：SQL 返回 [HH:MM, 'Day0'|'Day1'|'Day7', 值] → 按第 2 列透视成多条序列。
 * 与 CnKpi.tsx 的 buildPivotOption 同构，只是这里把 Day0/Day1/Day7 的顺序固定下来，
 * 并给每条线固定配色，保证「今天」永远是同一种颜色。
 */
// 配色：Day0 绿 / Day1 蓝 / Day7 青（运维侧指定这三色，与门户参考图
// vmax_cxo_dashboard.html 的 day-7 亮黄不同 —— 本页按「最近→最远」排色）。
// Day0/Day1 沿用本页既有实值；Day7 的青取自 theme.ts 的 DARK.teal（#00d9ff）。
// 必须是实值：canvas 解析不了 CSS 变量（AGENTS.md 第三节第 3 条的取色表）。
const DAY_COLOR: Record<string, string> = {
  Day0: '#08bd83',
  Day1: '#2b8cff',
  Day7: '#00d9ff',
}

// Day7 的青在浅色主题换成深青（theme.ts 的 LIGHT.blue #0e7490）：#00d9ff 是为深色底
// 设计的霓虹青，1.5px 画在白卡上会发飘、几乎看不见。深浅各一套实值是本项目既有做法。
const DAY_COLOR_LIGHT: Record<string, string> = {
  Day7: '#0e7490',
}

function dayColor(name: string, isDark: boolean) {
  return (!isDark && DAY_COLOR_LIGHT[name]) || DAY_COLOR[name] || '#8b95a7'
}

// 图例与导出列的固定顺序（后端只会产出这三个标签）
const DAY_ORDER = ['Day0', 'Day1', 'Day7']

/**
 * 图例文案的 i18n key。必须写成显式 switch 返回字面量：动态拼 key
 * （`t('cnkpi5.day.' + d)`）会被 `check:i18n` 守卫读成 `cnkpi5.day.` 并报字典缺失，
 * 见 AGENTS.md 第三节 1b 的第三条铁律。
 */
function dayLabelKey(day: string) {
  switch (day) {
    case 'Day0': return 'cnkpi5.day0'
    case 'Day1': return 'cnkpi5.day1'
    case 'Day7': return 'cnkpi5.day7'
    default: return ''
  }
}

/** 日子标签的界面文案（图例与导出表头共用，避免两边说法不一致） */
function dayLabel(t: (key: string) => string, day: string) {
  const key = dayLabelKey(day)
  return key ? t(key) : day
}

function fadeColor(hex: string, alpha: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}

function buildDayOption(w: CnWidget5, isDark: boolean) {
  const cats: string[] = []
  const seen = new Set<string>()
  const lookup = new Map<string, number | null>()
  const names: string[] = []
  for (const r of w.rows) {
    const x = String(r[0])
    const day = String(r[1])
    if (!day || day === 'null' || day === 'NULL' || day === 'undefined') continue
    if (!seen.has(x)) { seen.add(x); cats.push(x) }
    if (!names.includes(day)) names.push(day)
    const v = r[2]
    lookup.set(`${x}\u0000${day}`, v === null || v === undefined || v === '' ? null : toNumber(v))
  }
  // Day0 永远排在前面（图例顺序稳定）
  names.sort((a, b) => (a === 'Day0' ? -1 : b === 'Day0' ? 1 : a.localeCompare(b)))
  const dense = cats.length > 120
  const isPct = w.pct
  // tooltip 数值千分位 + 最多两位小数，与参考图的白卡数值形态一致；空值显示 —
  const fmtValue = (v: unknown) => {
    if (v === null || v === undefined || v === '') return '—'
    const n = Number(v)
    if (!Number.isFinite(n)) return String(v)
    return isPct ? `${n.toFixed(2)}%` : n.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }
  return {
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const, valueFormatter: fmtValue },
    legend: {
      top: 2,
      type: 'scroll' as const,
      icon: 'roundRect' as const,
      show: names.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
      itemWidth: 14,
      itemHeight: 8,
      itemGap: 10,
      data: names,
    },
    grid: { left: 12, right: 16, top: 34, bottom: 24, containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: cats,
      boundaryGap: false,
      axisLabel: { ...axisLabel(isDark), ...xAxisLabel(cats.length) },
      axisLine: axisLine(isDark),
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      scale: true,
      splitLine: { show: false },
      axisLabel: {
        ...axisLabel(isDark),
        formatter: isPct ? (v: number) => `${Number(v).toFixed(2)}%` : undefined,
      },
    },
    series: names.map((n) => {
      const c = dayColor(n, isDark)
      return {
        name: n,
        type: 'line' as const,
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        sampling: dense ? ('lttb' as const) : undefined,
        color: c,
        lineStyle: { width: 1.5 },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: fadeColor(c, 0.25) },
              { offset: 1, color: fadeColor(c, 0.02) },
            ],
          },
        },
        data: cats.map((x) => lookup.get(`${x}\u0000${n}`) ?? null),
      }
    }),
  }
}

/** 单个组件卡片（图表 / 空态 / 错误三种状态） */
function WidgetCard({ w, height }: { w: CnWidget5; height: number }) {
  const { isDark } = useTheme()
  const { t } = useI18n()

  const option = useMemo(() => {
    if (w.empty || w.error) return null
    return buildDayOption(w, isDark)
  }, [w, isDark])

  return (
    <CardBase
      size="small"
      style={{ height }}
      bodyStyle={{ height: '100%', padding: 8, display: 'flex', flexDirection: 'column' }}
      title={<span style={{ fontSize: 13 }}>{w.title}</span>}
      extra={
        <Space size={4}>
          {w.empty && <Tag color="default" style={{ marginInlineEnd: 0 }}>{t('cnkpi5.noGranularity')}</Tag>}
          {w.pct && <Tag color="cyan" style={{ marginInlineEnd: 0 }}>%</Tag>}
        </Space>
      }
    >
      {w.error ? (
        <Alert type="error" showIcon message={t('cnkpi5.queryFail')} description={w.error} style={{ fontSize: 12 }} />
      ) : w.empty ? (
        // 业务空态：讲清为什么没有，而不是空白的 Empty
        <div style={{ margin: 'auto', maxWidth: 320, textAlign: 'center' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={
            <span style={{ fontSize: 12 }}>{w.empty_reason || t('cnkpi5.noData')}</span>
          } />
        </div>
      ) : !option || w.rows.length === 0 ? (
        <Empty description={t('cnkpi5.noData')} style={{ margin: 'auto' }} />
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
    </CardBase>
  )
}

export default function CnKpi5mins() {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [data, setData] = useState<OverviewResp5 | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(async (force = false) => {
    setLoading(true)
    setErr('')
    try {
      const res = await getCnKpi5minsOverview({ force })
      setData(res.data)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const widgets = data?.widgets ?? []
  const chartWidgets = widgets.filter((w) => w.chart !== 'kpi' && w.chart !== 'text')
  const chartHeight = 320

  /**
   * 页头图例只列**库里真有数据**的那几天。Day7 需要历史攒够 8 天（或做过回补）
   * 才会出现，缺的时候明说一句，而不是画三条色块却只出两条线。
   */
  const presentDays = useMemo(() => {
    const found = new Set<string>()
    for (const w of chartWidgets) {
      for (const r of w.rows) {
        const d = String(r[1])
        if (d && d !== 'null' && d !== 'NULL' && d !== 'undefined') found.add(d)
      }
    }
    return DAY_ORDER.filter((d) => found.has(d))
  }, [chartWidgets])

  /** 有数据的组件数，用于页头统计 */
  const withData = widgets.filter((w) => !w.empty && !w.error).length

  /**
   * 导出 Excel：每个组件一张工作表（含 Day0/Day1 两列宽表）。
   * 表头写明数据口径，便于事后复核。
   */
  const exportExcel = useCallback(() => {
    if (!data) return
    const stamp = dayjs().format('YYYYMMDD_HHmmss')
    const sheets: ReportSheetSpec[] = [{
      name: 'Overview',
      title: 'CCN_KPI_5mins',
      subtitle: `${t('cnkpi5.exportSource')}: ${data.meta.db}`,
      header: ['', ''],
      rows: [
        [t('cnkpi5.exportSource'), data.meta.db],
        [t('cnkpi5.exportGenerated'), formatDateTime(new Date(), { zone: true })],
        [],
        ...widgets.map((w) => [
          w.title,
          w.empty ? t('cnkpi5.noGranularity') : `${w.rows.length} ${t('cnkpi5.rows')}`,
        ]),
      ] as (string | number)[][],
      columnWidths: [26, 46],
    }]

    for (const w of chartWidgets) {
      if (w.empty || w.error || w.rows.length === 0) continue
      // 宽表：每行 [HH:MM, Day0, Day1, Day7]，便于对账。
      // 列只取本组件实际有数据的日子，与图上画出的线一一对应。
      const days = DAY_ORDER.filter((d) => w.rows.some((r) => String(r[1]) === d))
      const byTime = new Map<string, Record<string, number | null>>()
      const times: string[] = []
      for (const r of w.rows) {
        const tt = String(r[0])
        const d = String(r[1])
        if (!byTime.has(tt)) { byTime.set(tt, {}); times.push(tt) }
        byTime.get(tt)![d] = r[2] === null || r[2] === undefined || r[2] === '' ? null : toNumber(r[2])
      }
      const hdr = [t('cnkpi5.time'), ...days.map((d) => `${dayLabel(t, d)} (${t('cnkpi5.value')})`)]
      const body = times.map((tt) => [tt, ...days.map((d) => byTime.get(tt)?.[d] ?? null)])
      sheets.push({
        name: w.id,
        title: w.title,
        subtitle: `${t('cnkpi5.exportSource')}: ${data.meta.db}`,
        header: hdr,
        rows: body as (string | number | null)[][],
        columnWidths: [12, ...days.map(() => 20)],
      })
    }

    void exportReport(sheets, `CN_KPI_5mins_${stamp}.xlsx`)
  }, [data, widgets, chartWidgets, t])

  return (
    <div style={{ padding: 4 }}>
      {/* 工具条：全局 Header 已显示页面标题（菜单名），页内不再重复画大标题，
          只保留统计/图例/操作一行，避免同一页出现两个 header */}
      <CardBase size="small" style={{ marginBottom: 12 }} bodyStyle={{ padding: '8px 12px' }}>
        <Row align="middle" justify="space-between" gutter={[12, 8]}>
          <Col>
            <Space size={10} wrap>
              <Tooltip title={t('cnkpi5.legendHint')}>
                <Tag icon={<InfoCircleOutlined />} color="blue">
                  {t('cnkpi5.summary', { ok: withData, total: widgets.length })}
                </Tag>
              </Tooltip>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi5.barHint')}</Text>
              {data?.meta && (
                <Tag>{data.meta.elapsed_ms}ms{data.meta.cached ? ` · ${t('cnkpi.cached')}` : ''}</Tag>
              )}
              {data?.meta && data.meta.failed > 0 && (
                <Tag color="error">{t('cnkpi.failed', { n: data.meta.failed })}</Tag>
              )}
              {/* 图例：按**实际取到的日子**渲染。Day7 要等库里攒够 8 天（或做过回补）
                  才会出现，缺的时候直接说明，而不是留着一条永远不出来的色块。 */}
              <Space size={6} align="center" wrap>
                {presentDays.map((d) => (
                  <Space key={d} size={4} align="center">
                    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: dayColor(d, isDark) }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>{dayLabel(t, d)}</Text>
                  </Space>
                ))}
                {!presentDays.includes('Day7') && (
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi5.day7Absent')}</Text>
                )}
              </Space>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} onClick={() => load(true)} loading={loading} size="small">
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
          message={t('cnkpi5.loadFail')}
          description={
            <Space direction="vertical" size={2}>
              <Text>{err}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi.hint')}</Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 空态说明条：把「哪些卡片没有数据」一次讲清，避免被当成故障 */}
      {(data?.meta?.empty ?? 0) > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('cnkpi5.emptyBanner', { n: data?.meta?.empty ?? 0 })}
          description={<Text style={{ fontSize: 12 }}>{t('cnkpi5.emptyWhy')}</Text>}
        />
      )}

      {/* 混合粒度说明条：本页同时存在 5 分钟与 15 分钟两种粒度，必须显式告知，
          否则 15 分钟组件的稀疏点会被误读成「数据缺失」。 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={t('cnkpi5.mixedGranularity')}
        description={<Text style={{ fontSize: 12 }}>{t('cnkpi5.mixedGranularityHint')}</Text>}
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
