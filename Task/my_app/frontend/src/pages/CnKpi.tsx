import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, DatePicker, Empty, Row, Space, Spin, Statistic, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import * as XLSX from 'xlsx'
import ReactECharts from 'echarts-for-react'
import { getCnKpiOverview } from '../api'
import { useI18n } from '../i18n'
import { WH, axisLabel, axisLine, cardStyle, darkTooltip, splitLine, useTheme } from '../theme'

const { RangePicker } = DatePicker
const { Text, Title } = Typography

/* ====================================================================
 * CN KPI 看板（原 my-finebi「CN KPI」看板原生重建）
 * --------------------------------------------------------------------
 * 数据源：后端 /api/cn-kpi/overview → 远端只读 SQL API（db_ps_cs_cn.sqlite3）。
 * 18 个组件的 SQL 与图表类型逐条对齐 FineBI 原看板（公开链接 iYiQ）。
 * 本页**不依赖 my-finebi 进程**。
 *
 * 时间区间：默认近 31 天（与原版一致），可用 RangePicker 自定义起止日期；
 * 区间由后端把 SQL 里的 {{LO}}/{{HI}} 占位符替换为已校验的日期字面量。
 * 导出 Excel：每个组件一张工作表，含实际执行口径与数据。
 *
 * 与原版的差异（刻意为之）：
 *   - 原版用 2321×2395 绝对定位画布；这里改用 my_app 的响应式栅格，
 *     与其它看板观感一致，也避免 0 高度初始化问题。
 *   - 原版标题栏含指向 FineBI 的外链（已随 FineBI 退役去掉），只留标题文本。
 * ==================================================================== */

// ---------------- 类型（与后端 cn_kpi_service 对齐） ----------------
interface CnWidget {
  id: string
  title: string
  chart: 'line' | 'kpi' | 'text' | 'bar' | 'table'
  pivot: boolean
  pct: boolean
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  error: string
}
interface OverviewResp {
  meta: {
    db: string
    host: string
    count: number
    failed: number
    elapsed_ms: number
    cached: boolean
    start: string | null
    end: string | null
  }
  title: string
  title_html: string
  widgets: CnWidget[]
}

/**
 * 页头行内 KPI 的默认规则：本看板带一个「最新数据日期」单值组件（标题 `TIme`），
 * 统一提到页头标题右侧、与标题同一行，不再像普通 KPI 那样在标题下方单独占一行。
 * 与 NativeBoard（FineBI 组各看板）保持同一套观感。
 */
const HEADER_KPI_RE = /^\s*ti+me\s*$/i

function toNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function fmtVal(v: number, pct?: boolean) {
  return pct ? `${v.toFixed(2)}%` : String(v)
}

/** 类目轴标签抽稀：日期类目动辄 200+，不抽稀会糊成不可读的斜带（FineBI 同样只显示少量刻度） */
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

/** 普通折线：第 1 列为类目，其余每列一条序列 */
function buildAxisOption(w: CnWidget, isDark: boolean) {
  const cats = w.rows.map((r) => String(r[0]))
  const rest = w.columns.slice(1)
  const dense = cats.length > 120
  return {
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const },
    legend: {
      bottom: 0,
      type: 'scroll' as const,
      show: rest.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: '0.625rem' },
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 62, right: 20, top: 30, bottom: 46, containLabel: true },
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
    series: rest.map((c, i) => ({
      name: c,
      type: 'line' as const,
      smooth: false,
      showSymbol: false,
      sampling: dense ? ('lttb' as const) : undefined,
      data: extremeData(
        w.rows.map((r) => {
          const v = r[i + 1]
          return v === null || v === undefined || v === '' ? null : toNumber(v)
        }),
        w.pct,
      ),
      label: { show: true, position: 'top' as const, fontSize: 10 },
    })),
  }
}

/** pivot：SQL 返回 [x, 系列名, 值] 三列 → 按系列名透视成多序列（FineBI 的「颜色/分区」维度） */
function buildPivotOption(w: CnWidget, isDark: boolean) {
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
    tooltip: { ...darkTooltip(isDark), trigger: 'axis' as const },
    legend: {
      bottom: 0,
      type: 'scroll' as const,
      show: seriesNames.length > 0,
      textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: '0.625rem' },
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 62, right: 20, top: 30, bottom: 46, containLabel: true },
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
      label: { show: true, position: 'top' as const, fontSize: 10 },
    })),
  }
}

/**
 * 页头行内 KPI（数据最新日期）：跟在页头标题右侧，与标题同一行，
 * 不再像普通 KPI 那样在标题下方单独占一行。
 */
function HeaderKpi({ w }: { w: CnWidget }) {
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
function WidgetCard({ w, height }: { w: CnWidget; height: number }) {
  const { isDark } = useTheme()
  const { t } = useI18n()

  const option = useMemo(() => {
    if (w.chart === 'kpi' || w.chart === 'text') return null
    return w.pivot ? buildPivotOption(w, isDark) : buildAxisOption(w, isDark)
  }, [w, isDark])

  // KPI 卡片：单值（CN KPI 里是数据最新日期）
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
            <Text type="secondary" style={{ fontSize: 12 }}>{w.title}</Text>
            <Statistic
              value={isNum ? n : String(v ?? '-')}
              precision={isNum ? undefined : 0}
              valueStyle={{ fontSize: 22, fontWeight: 600, color: isDark ? '#64ffda' : '#0d9488' }}
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
      extra={w.pct ? <Tag color="cyan" style={{ marginInlineEnd: 0 }}>%</Tag> : null}
    >
      {w.error ? (
        <Alert type="error" showIcon message={t('cnkpi.queryFail')} description={w.error} style={{ fontSize: 12 }} />
      ) : !option || w.rows.length === 0 ? (
        <Empty description={t('cnkpi.noData')} style={{ margin: 'auto' }} />
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

export default function CnKpi() {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  // 默认近 31 天（与原版 FineBI 口径一致）；null = 未自定义，交给后端默认
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)

  const load = useCallback(async (force = false, r: [Dayjs, Dayjs] | null = range) => {
    setLoading(true)
    setErr('')
    try {
      const res = await getCnKpiOverview({
        start: r?.[0]?.format('YYYY-MM-DD'),
        end: r?.[1]?.format('YYYY-MM-DD'),
        force,
      })
      setData(res.data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setErr(msg)
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 组件布局：KPI 单值置顶，其余按 2 列栅格（宽屏 3 列）
  const widgets = data?.widgets ?? []
  const kpiWidgets = widgets.filter((w) => w.chart === 'kpi')
  // Time/TIme 单值提到页头标题右侧行内显示；其余 KPI 仍在标题下方一行
  const isHeaderKpi = (w: CnWidget) => w.chart === 'kpi' && HEADER_KPI_RE.test(w.title)
  const headerKpis = kpiWidgets.filter(isHeaderKpi)
  const rowKpis = kpiWidgets.filter((w) => !isHeaderKpi(w))
  const chartWidgets = widgets.filter((w) => w.chart !== 'kpi')
  const chartHeight = 320

  /** 区间文案：优先用后端回传的实际生效区间，便于导出时写明口径 */
  const rangeLabel = useMemo(() => {
    if (!data) return ''
    const s = data.meta.start
    const e = data.meta.end
    if (s && e) return `${s} ~ ${e}`
    return t('cnkpi.rangeDefault')
  }, [data, t])

  /**
   * 导出 Excel：每个组件一张工作表（KPI 单值并入总览表）。
   * 表头写入实际生效的时间区间与执行口径（SQL），便于事后复核数字来源。
   */
  const exportExcel = useCallback(() => {
    if (!data) return
    const wb = XLSX.utils.book_new()
    const stamp = dayjs().format('YYYYMMDD_HHmmss')

    // 总览表：元信息 + KPI 单值
    const ov: (string | number)[][] = [
      ['CN KPI (CCN_Daily_KPI)'],
      [t('cnkpi.exportRange'), rangeLabel],
      [t('cnkpi.exportSource'), `${data.meta.db} @ ${data.meta.host}`],
      [t('cnkpi.exportGenerated'), dayjs().format('YYYY-MM-DD HH:mm:ss')],
      [],
    ]
    for (const w of kpiWidgets) {
      ov.push([w.title, w.rows[0]?.[0] ?? ''])
    }
    const wsOv = XLSX.utils.aoa_to_sheet(ov)
    wsOv['!cols'] = [{ wch: 22 }, { wch: 46 }]
    XLSX.utils.book_append_sheet(wb, wsOv, 'Overview')

    // 每个组件一张表：口径 + 数据
    const used = new Set<string>(['Overview'])
    for (const w of widgets) {
      if (w.chart === 'kpi' || w.chart === 'text') continue
      const aoa: (string | number | null)[][] = [
        [w.title],
        [t('cnkpi.exportRange'), rangeLabel],
        [t('cnkpi.exportSQL'), w.sql],
        [],
        w.columns,
        ...w.rows,
      ]
      if (w.error) aoa.splice(4, 0, [t('cnkpi.queryFail'), w.error])
      const ws = XLSX.utils.aoa_to_sheet(aoa)
      ws['!cols'] = w.columns.map((c, i) => ({ wch: i === 0 ? 20 : Math.max(12, String(c).length + 2) }))
      // sheet 名需唯一且 <=31 字符，并去掉 Excel 禁用字符
      let name = w.id.replace(/[:\\/?*[\]]/g, '_').substring(0, 28)
      let n = 1
      while (used.has(name)) name = `${w.id}_${++n}`.substring(0, 28)
      used.add(name)
      XLSX.utils.book_append_sheet(wb, ws, name)
    }

    const rng = (data.meta.start || data.meta.end)
      ? `_${(data.meta.start || 'start')}_${(data.meta.end || 'end')}`
      : '_last31d'
    XLSX.writeFile(wb, `CN_KPI${rng}_${stamp}.xlsx`)
  }, [data, kpiWidgets, widgets, rangeLabel, t])

  return (
    <div style={{ padding: 4 }}>
      {/* 标题栏（原版 CCN_Daily_KPI 文本组件；已去掉指向 FineBI 的外链） */}
      <Card size="small" style={{ ...cardStyle, marginBottom: 12 }} styles={{ body: { padding: '8px 12px' } }}>
        <Row align="middle" justify="space-between" gutter={[12, 8]}>
          <Col>
            <Space size={10} wrap>
              <Title level={4} style={{ margin: 0, color: isDark ? '#64ffda' : '#0d9488' }}>
                ❯❯❯ {data?.title || 'CCN_Daily_KPI'} ❮❮❮
              </Title>
              {/* 数据最新日期跟着标题排在同一行右侧 */}
              {headerKpis.map((w) => <HeaderKpi key={w.id} w={w} />)}
              {data?.meta && (
                <Tooltip title={`${data.meta.db} @ ${data.meta.host}`}>
                  <Tag color="blue" icon={<InfoCircleOutlined />}>
                    {t('cnkpi.widgets', { n: data.meta.count })} · {data.meta.elapsed_ms}ms
                    {data.meta.cached ? ` · ${t('cnkpi.cached')}` : ''}
                  </Tag>
                </Tooltip>
              )}
              {data?.meta && data.meta.failed > 0 && (
                <Tag color="error">{t('cnkpi.failed', { n: data.meta.failed })}</Tag>
              )}
            </Space>
          </Col>
          <Col>
            <Space wrap>
              {/* 时间区间：默认近 31 天（与原版一致），可自定义起止日期 */}
              <Text style={{ color: WH.textMuted, fontSize: 12 }}>{t('cnkpi.range')}</Text>
              <RangePicker
                value={range as never}
                allowClear
                placeholder={[t('cnkpi.start'), t('cnkpi.end')]}
                onChange={(v) => {
                  const next = (v && v[0] && v[1]) ? [v[0], v[1]] as [Dayjs, Dayjs] : null
                  setRange(next)
                  load(false, next)
                }}
              />
              <Button icon={<ReloadOutlined />} onClick={() => load(true)} loading={loading} size="small">
                {t('cnkpi.refresh')}
              </Button>
              <Button
                icon={<DownloadOutlined />}
                onClick={exportExcel}
                disabled={!data || loading}
                size="small"
              >
                {t('cnkpi.export')}
              </Button>
            </Space>
          </Col>
        </Row>
        {rowKpis.length > 0 && (
          <div style={{ marginTop: 8, borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.08)' : 'rgba(13,148,136,0.12)'}`, paddingTop: 4 }}>
            {rowKpis.map((w) => <WidgetCard key={w.id} w={w} height={48} />)}
          </div>
        )}
      </Card>

      {err && (
        <Alert
          type="error"
          showIcon
          message={t('cnkpi.loadFail')}
          description={
            <Space direction="vertical" size={2}>
              <Text>{err}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('cnkpi.hint')}</Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
        />
      )}

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

      {data?.meta && (
        <Text type="secondary" style={{ display: 'block', marginTop: 10, fontSize: 12 }}>
          {t('cnkpi.footer', { db: data.meta.db, host: data.meta.host })} · {t('cnkpi.rangeLabel')}: {rangeLabel}
        </Text>
      )}
    </div>
  )
}
