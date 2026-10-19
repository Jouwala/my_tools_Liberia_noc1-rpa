/* ============================================================================
 * CN KPI 5 分钟看板（?page=cn_kpi_5mins）
 * ----------------------------------------------------------------------------
 * 数据源：后端 /api/cn-kpi-5mins/overview
 *   → services/cn_kpi_5mins_service.py（读远端 db_ps_cs_cn 的 5mins_* 表）
 *   → 由任务 cnn_kpi_sync_5mins 每 15 分钟写入（gr=300，窗口昨天 00:00 → 现在）。
 *
 * 核心展示：每个组件画 **Day0（今天）/ Day1（昨天）两条曲线**，x 轴为 HH:MM。
 * 后端 SQL 已输出三列 [HH:MM, 'Day0'|'Day1', 值]，本页复用 pivot 机制
 * （按第 2 列透视成多序列），不需要前端再拆日。
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
import { WH, axisLabel, axisLine, darkTooltip, splitLine, useTheme } from '../theme'

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
 * pivot：SQL 返回 [HH:MM, 'Day0'|'Day1', 值] → 按第 2 列透视成 Day0 / Day1 两条序列。
 * 与 CnKpi.tsx 的 buildPivotOption 同构，只是这里把 Day0/Day1 的顺序固定下来，
 * 并给两条线固定配色，保证「今天」永远是同一种颜色。
 */
const DAY_COLOR: Record<string, string> = {
  Day0: '#0d9488',
  Day1: '#8b95a7',
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
  return {
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const },
    legend: {
      bottom: 0,
      type: 'scroll' as const,
      show: names.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: '0.625rem' },
      itemWidth: 12,
      itemHeight: 8,
      data: names,
    },
    grid: { left: 62, right: 20, top: 24, bottom: 46, containLabel: true },
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
        formatter: isPct ? (v: number) => `${Number(v).toFixed(2)}%` : undefined,
      },
    },
    series: names.map((n) => ({
      name: n,
      type: 'line' as const,
      smooth: false,
      showSymbol: false,
      connectNulls: false,
      sampling: dense ? ('lttb' as const) : undefined,
      color: DAY_COLOR[n],
      data: cats.map((x) => lookup.get(`${x}\u0000${n}`) ?? null),
    })),
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
      // 宽表：每行 [HH:MM, Day0, Day1]，便于对账
      const days = ['Day0', 'Day1']
      const byTime = new Map<string, Record<string, number | null>>()
      const times: string[] = []
      for (const r of w.rows) {
        const tt = String(r[0])
        const d = String(r[1])
        if (!byTime.has(tt)) { byTime.set(tt, {}); times.push(tt) }
        byTime.get(tt)![d] = r[2] === null || r[2] === undefined || r[2] === '' ? null : toNumber(r[2])
      }
      const hdr = [t('cnkpi5.time'), ...days.map((d) => `${d} (${t('cnkpi5.value')})`)]
      const body = times.map((tt) => [tt, ...days.map((d) => byTime.get(tt)?.[d] ?? null)])
      sheets.push({
        name: w.id,
        title: w.title,
        subtitle: `${t('cnkpi5.exportSource')}: ${data.meta.db}`,
        header: hdr,
        rows: body as (string | number | null)[][],
        columnWidths: [12, 18, 18],
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
              {/* 图例：Day0=今天，Day1=昨天 */}
              <Space size={6} align="center" style={{ fontSize: 12 }}>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: DAY_COLOR.Day0 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi5.day0')}</Text>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: DAY_COLOR.Day1 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi5.day1')}</Text>
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
