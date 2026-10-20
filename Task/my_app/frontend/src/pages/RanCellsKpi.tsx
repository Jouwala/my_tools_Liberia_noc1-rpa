import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Card, Button, Space, Alert, Typography, DatePicker, InputNumber,
  Tooltip, Empty, Spin, Segmented, Table, Tag, Input, Popover,
} from 'antd'
import { ReloadOutlined, DownloadOutlined, InfoCircleOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import { exportAoaReport, exportReport, type ReportSheetSpec } from '../utils/excelReport'
import { fmtWarning, fmtWarnings } from '../utils/warnCodes'
import { getRanCellsKpiOverview, getRanCellsKpiCells } from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH } from '../theme'
import StatCard from '../components/StatCard'
import DraggableClickModal from '../components/DraggableClickModal'

const { Text } = Typography

// ==================== 类型（与后端 ran_cells_kpi_service 对齐） ====================
interface DayStat {
  total: number
  meeting: number
  below: number
  blank: number
  pct_meeting: number | null
  pct_below: number | null
  availability: number | null
}
interface TechBlock {
  tech: string
  label: string
  desc: string
  /** 英文说明（后端 desc_en；缺失时退回中文） */
  desc_en?: string
  roster_cells: number
  days: Record<string, DayStat>
  month: {
    availability: number | null
    days_with_data: number
    total: number
    meeting: number
    below: number
    pct_meeting: number | null
    pct_below: number | null
  }
}
interface OverviewResp {
  meta: {
    month: string
    threshold: number
    days: string[]
    source: string
    generated_at: string
    elapsed_seconds: number
    warnings: string[]
  }
  techs: TechBlock[]
}

/** 小区级明细行（下钻弹窗）—— 身份字段按制式可用性返回，可能缺失 */
interface DrillRow {
  cell: string
  cell_id?: string
  site_id?: string
  site_name?: string
  ne?: string          // 网元：BSC / RNC / eNodeB
  subnet?: string
  band?: string
  ratio: number | null
  days_with_data: number
  days_meeting?: number  // 仅整月下钻
  days_below?: number    // 仅整月下钻
  status: 'meeting' | 'below' | 'blank'
}
interface DrillCellsResp {
  tech: string
  label: string
  desc: string
  month: string
  day: string
  threshold: number
  scope: string
  roster_cells: number
  total: number
  meeting: number
  below: number
  blank: number
  rows: DrillRow[]
  warnings?: string[]
}

/** 下钻上下文（记录点击的是哪个制式 / 哪天 / 哪个指标） */
interface DrillCtx {
  tech: string
  label: string
  day: string
  metric: keyof DayStat
  metricKey: string
}

const DEFAULT_THRESHOLD_PCT = 99.65 // 99.65%，与后端 DEFAULT_THRESHOLD 一致

/** 指标行定义（顺序与参考报表一致） */
const METRICS: Array<{
  key: keyof DayStat
  labelKey: string
  fmt: 'int' | 'pct'
  highlight?: boolean
}> = [
  { key: 'total', labelKey: 'rck.m.total', fmt: 'int' },
  { key: 'meeting', labelKey: 'rck.m.meeting', fmt: 'int' },
  { key: 'below', labelKey: 'rck.m.below', fmt: 'int' },
  { key: 'blank', labelKey: 'rck.m.blank', fmt: 'int' },
  { key: 'pct_meeting', labelKey: 'rck.m.pctMeeting', fmt: 'pct' },
  { key: 'pct_below', labelKey: 'rck.m.pctBelow', fmt: 'pct' },
  { key: 'availability', labelKey: 'rck.m.availability', fmt: 'pct', highlight: true },
]

/** 指标 → i18n 标签 key */
const METRIC_LABEL_KEY = Object.fromEntries(
  METRICS.map(m => [m.key, m.labelKey]),
) as Record<keyof DayStat, string>

/** 指标 → 下钻过滤范围（与后端 CELL_SCOPES 对齐） */
const SCOPE_BY_METRIC: Record<keyof DayStat, 'all' | 'meeting' | 'below' | 'blank'> = {
  total: 'all',
  meeting: 'meeting',
  below: 'below',
  blank: 'blank',
  pct_meeting: 'meeting',
  pct_below: 'below',
  availability: 'all',
}

/** 下钻状态 → Tag 颜色 */
const STATUS_COLOR: Record<DrillRow['status'], string> = {
  meeting: 'green',
  below: 'red',
  blank: 'default',
}

/** 下钻弹窗搜索框参与匹配的字段（小区 / 站点 / 网元 / 子网 / 频段 / ID） */
const DRILL_SEARCH_FIELDS: Array<keyof DrillRow> = [
  'cell', 'cell_id', 'site_id', 'site_name', 'ne', 'subnet', 'band',
]

const fmtInt = (v: number | null | undefined) =>
  v == null ? '-' : Number(v).toLocaleString('en-US')
const fmtPct = (v: number | null | undefined) =>
  v == null ? '-' : `${(Number(v) * 100).toFixed(2)}%`
const fmtCell = (v: number | null | undefined, fmt: 'int' | 'pct') =>
  fmt === 'int' ? fmtInt(v) : fmtPct(v)

/** 表头日期：2026-09-01 → 1-Sep-2026（与参考报表一致） */
const fmtDay = (d: string) => dayjs(d).format('D-MMM-YYYY')

// ==================== 页面 ====================
export default function RanCellsKpi() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()

  const [month, setMonth] = useState<Dayjs>(() => dayjs())
  const [thresholdPct, setThresholdPct] = useState<number>(DEFAULT_THRESHOLD_PCT)
  const [tech, setTech] = useState<string>('all')
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ---- 小区级明细下钻弹窗（可拖动 + 可导出，格式对齐 SiteAvailability） ----
  const [drill, setDrill] = useState<DrillCtx | null>(null)
  const [drillData, setDrillData] = useState<DrillCellsResp | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillError, setDrillError] = useState('')
  const [drillQuery, setDrillQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const r = await getRanCellsKpiOverview({
        month: month.format('YYYY-MM'),
        threshold: thresholdPct / 100,
        prefer_db: 1,
      })
      // 结构校验：接口若不可用（如被 Web 服务器的 SPA 回退页顶替），会返回 HTML 字符串，
      // 此时 r.data.techs 为 undefined。若不拦住，页面会静默显示「暂无数据」，
      // 把「后端路由缺失」误报成「没跑同步任务」，非常容易误导排查方向。
      if (!r.data || !Array.isArray(r.data.techs)) {
        throw new Error(t('rck.badResponse'))
      }
      setData(r.data)
    } catch (e: any) {
      setError(e?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [month, thresholdPct, t])

  useEffect(() => { load() }, [load])

  const threshold = thresholdPct / 100

  // 打开下钻：day 为空表示整月汇总（月度卡片入口）
  const openDrill = useCallback(async (
    e: React.MouseEvent,
    tb: TechBlock,
    day: string,
    metric: keyof DayStat,
  ) => {
    setDrill({ tech: tb.tech, label: tb.label, day, metric, metricKey: METRIC_LABEL_KEY[metric] })
    setDrillAnchor({ x: e.clientX, y: e.clientY })
    setDrillData(null); setDrillError(''); setDrillLoading(true); setDrillQuery('')
    try {
      const r = await getRanCellsKpiCells({
        month: month.format('YYYY-MM'),
        tech: tb.tech,
        day,
        threshold: thresholdPct / 100,
        scope: SCOPE_BY_METRIC[metric] || 'all',
      })
      if (!r.data || !Array.isArray(r.data.rows)) {
        throw new Error(t('rck.badResponse'))
      }
      setDrillData(r.data)
      const w = r.data?.warnings
      if (Array.isArray(w) && w.length) setDrillError(fmtWarnings(w, t, '；'))
    } catch (err: any) {
      setDrillError(err?.message || String(err))
      setDrillData(null)
    } finally {
      setDrillLoading(false)
    }
  }, [month, thresholdPct, t])

  const drillAll = useMemo(() => drillData?.rows || [], [drillData])

  // 客户端过滤：整月下钻可能上万行，靠滚动找小区不现实，给一个跨字段搜索框
  const drillRows = useMemo(() => {
    const q = drillQuery.trim().toLowerCase()
    if (!q) return drillAll
    return drillAll.filter(r =>
      DRILL_SEARCH_FIELDS.some(k => {
        const v = r[k]
        return v != null && String(v).toLowerCase().includes(q)
      }),
    )
  }, [drillAll, drillQuery])

  // 下钻明细导出 Excel（表头随界面语言；导出「当前筛选后」的行）
  // 已迁统一格式 UNIFIED_EXCEL_V1：样式与邮件报表同源，见 docs/EXCEL_EXPORT_STANDARD.md
  const exportDrill = useCallback(() => {
    if (!drill || !drillRows.length) return
    const cols: Array<{ h: string; get: (r: DrillRow) => any; w?: number }> = [
      { h: t('rck.drill.cell'), get: r => r.cell, w: 34 },
      { h: t('rck.drill.cellId'), get: r => r.cell_id ?? '', w: 10 },
      { h: t('rck.drill.siteId'), get: r => r.site_id ?? '', w: 10 },
      { h: t('rck.drill.siteName'), get: r => r.site_name ?? '', w: 26 },
      { h: t('rck.drill.ne'), get: r => r.ne ?? '', w: 22 },
      { h: t('rck.drill.subnet'), get: r => r.subnet ?? '', w: 18 },
      { h: t('rck.drill.band'), get: r => r.band ?? '', w: 18 },
      { h: t('rck.drill.ratio'), get: r => (r.ratio == null ? '' : (r.ratio * 100).toFixed(2)), w: 12 },
      { h: t('rck.drill.status'), get: r => t(`rck.drill.${r.status}`), w: 12 },
      ...(drill.day ? [] : [
        { h: t('rck.drill.daysWithData'), get: (r: DrillRow) => r.days_with_data, w: 12 },
        { h: t('rck.drill.daysMeeting'), get: (r: DrillRow) => r.days_meeting ?? 0, w: 12 },
        { h: t('rck.drill.daysBelow'), get: (r: DrillRow) => r.days_below ?? 0, w: 12 },
      ]),
    ]
    const fname = `Cells_${drill.tech}_${drill.day || 'month'}_${dayjs().format('YYYYMMDD_HHmmss')}`
      .replace(/[\\/:*?"<>|]/g, '_')
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `${drill.tech}_Cells`,
      title: `${drill.tech} Cells`,
      header: cols.map(c => c.h),
      rows: drillRows.map(r => cols.map(c => c.get(r))),
      columnWidths: cols.map(c => c.w ?? 16),
    })
  }, [drill, drillRows, t])

  // 只展示「已有数据」的日期列（当月未来日期不展开）
  const activeDays = useMemo(() => {
    const all = data?.meta?.days || []
    return all.filter(d => (data?.techs || []).some(tb => (tb.days?.[d]?.total || 0) > 0))
  }, [data])

  const shownTechs = useMemo(
    () => (data?.techs || []).filter(tb => tech === 'all' || tb.tech === tech),
    [data, tech],
  )

  // 当前筛选条件文本（导出副标题用，便于对账「这份文件是哪个口径下导出的」）
  // 月份 / 达标值 / 制式三者都是页面工具栏上的筛选条件，必须写进 subtitle
  const filterText = useMemo(() => [
    `${t('rck.month')}: ${month.format('YYYY-MM')}`,
    `${t('rck.threshold')}: ${thresholdPct.toFixed(2)}%`,
    `${t('rck.tech')}: ${tech === 'all' ? t('rck.all') : tech}`,
  ].join('    |    '), [month, thresholdPct, tech, t])

  // 页面级导出：把「当前筛选后」的汇总卡片 + 逐日 KPI 主表整份导出。
  // 与旧的 exportExcel 的区别：
  //   - 旧的在 Sheet1 只写逐日矩阵，月度汇总卡片（月均可用率 / 小区名册 / 有数据天数）完全没进去；
  //   - 旧的文件名与副标题里没有达标值 / 制式筛选，拿到文件后无法判断是什么口径。
  // 这里改为多 sheet：Sheet1 = 汇总、其后每制式一张，两块都带上完整筛选条件。
  // Sheet1 不复用 exportExcel 的 `{tech}_Cells_KPI` 命名，避免与逐日 sheet 撞名后
  // 被 excelReport 的 uniqueSheetName() 改写成 `..._2`（见 utils/excelReport.ts）。
  const exportSummary = useCallback(() => {
    if (!data || !shownTechs.length) return
    const sheets: ReportSheetSpec[] = []
    // ---------- Sheet1：月度汇总（页面上那排 StatCard + 名册口径） ----------
    sheets.push({
      name: 'Summary',
      title: t('rck.exportSummaryTitle'),
      subtitle: filterText,
      tabColor: 'FF2F5496',
      header: [
        t('rck.tech'), t('rck.export.thAvailability'), t('rck.roster'),
        t('rck.daysWithData'), t('rck.m.total'), t('rck.m.meeting'), t('rck.m.below'),
        t('rck.m.pctMeeting'), t('rck.m.pctBelow'),
      ],
      rows: shownTechs.map(tb => [
        // 取不到数据显示 ——，不能显示成 0（未达标数 / 占比为 0 是真实值，照常显示）
        tb.label,
        tb.month.availability == null ? '—' : Number((tb.month.availability * 100).toFixed(2)),
        tb.roster_cells,
        tb.month.days_with_data,
        tb.month.total,
        tb.month.meeting,
        tb.month.below,
        tb.month.pct_meeting == null ? '—' : Number((tb.month.pct_meeting * 100).toFixed(2)),
        tb.month.pct_below == null ? '—' : Number((tb.month.pct_below * 100).toFixed(2)),
      ]),
      columnWidths: [34, 16, 14, 14, 14, 14, 16, 14, 16],
    })
    // ---------- 其后每个制式一张：逐日 KPI 矩阵（指标为行、日期为列，与页面明细表同布局） ----------
    for (const tb of shownTechs) {
      sheets.push({
        name: `${tb.tech}_Cells_KPI`,
        title: tb.label,
        subtitle: filterText,
        header: [t('rck.metric'), ...activeDays.map(fmtDay)],
        rows: METRICS.map(m => [
          t(m.labelKey),
          ...activeDays.map(d => {
            const v = tb.days?.[d]?.[m.key] as number | null | undefined
            return v == null ? '—' : (m.fmt === 'int' ? Number(v) : Number((v * 100).toFixed(2)))
          }),
        ]),
        columnWidths: [30, ...activeDays.map(() => 12)],
      })
    }
    const fname = `RAN_Cells_KPI_${data.meta.month}_${dayjs().format('YYYYMMDD_HHmmss')}`
    void exportReport(sheets, `${fname}.xlsx`)
  }, [data, shownTechs, activeDays, filterText, t])

  // ---------- 主题相关样式（深浅自适应） ----------
  const border = `1px solid color-mix(in srgb, ${WH.teal} 16%, transparent)`
  const headBg = `color-mix(in srgb, ${WH.teal} 14%, ${WH.cardBg})`
  const availBg = `color-mix(in srgb, ${WH.teal} 12%, transparent)`
  const mutedBg = isDark ? 'rgba(255,255,255,0.02)' : 'rgba(13,148,136,0.03)'

  const cellBase: React.CSSProperties = {
    padding: '0.375rem 0.75rem',
    border,
    fontSize: '0.8125rem',
    whiteSpace: 'nowrap',
  }
  const headCell: React.CSSProperties = {
    ...cellBase,
    background: headBg,
    color: WH.teal,
    fontWeight: 700,
    textAlign: 'center',
    position: 'sticky',
    top: 0,
  }
  const metricCell: React.CSSProperties = {
    ...cellBase,
    textAlign: 'left',
    color: WH.text,
    fontWeight: 600,
    minWidth: '13rem',
    position: 'sticky',
    left: 0,
    background: WH.cardBg,
    zIndex: 1,
  }
  const numCell: React.CSSProperties = {
    ...cellBase,
    textAlign: 'right',
    color: WH.text,
    fontVariantNumeric: 'tabular-nums',
  }

  return (
    <div style={{ padding: 'var(--wh-space-sm)' }}>
      {/* ---------- 工具栏 ---------- */}
      <Card
        style={{ marginBottom: 'var(--wh-space-md)' }}
        styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}
      >
        <Space wrap size="middle" align="center">
          {/* 页面标题由 App 全局 Header 渲染（菜单名「RAN 小区 KPI」），页内不再重复 */}
          <Text type="secondary" style={{ fontSize: '0.8125rem' }}>{t('rck.subtitle')}</Text>
        </Space>
        <div style={{ marginTop: 'var(--wh-space-sm)' }}>
          <Space wrap size="middle" align="center">
            <Space size={4}>
              <Text style={{ color: WH.textMuted }}>{t('rck.month')}</Text>
              <DatePicker
                picker="month"
                allowClear={false}
                value={month}
                onChange={v => v && setMonth(v)}
              />
            </Space>
            <Space size={4}>
              <Text style={{ color: WH.textMuted }}>{t('rck.threshold')}</Text>
              <InputNumber
                min={0} max={100} step={0.01} precision={2}
                value={thresholdPct}
                onChange={v => setThresholdPct(typeof v === 'number' ? v : DEFAULT_THRESHOLD_PCT)}
                addonAfter="%"
                style={{ width: 130 }}
              />
            </Space>
            <Segmented
              className="wh-seg"
              value={tech}
              onChange={v => setTech(String(v))}
              options={[
                { label: t('rck.all'), value: 'all' },
                { label: '2G', value: '2G' },
                { label: '3G', value: '3G' },
                { label: '4G', value: '4G' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('rck.refresh')}
            </Button>
            <Button icon={<DownloadOutlined />} onClick={exportSummary} disabled={!data || !shownTechs.length}>
              {t('common.exportExcel')}
            </Button>
          </Space>
        </div>
      </Card>

      {/* ---------- 数据源说明：默认只留一行，鼠标悬浮才展开全文 ----------
          用 div 包一层再交给 Popover 定位：Alert 是函数组件，不保证转发 ref，
          直接作为 trigger 会导致浮层定位异常（"Function components cannot be given refs"）。 */}
      <Popover
        trigger="hover"
        placement="bottomLeft"
        mouseEnterDelay={0.15}
        mouseLeaveDelay={0.1}
        title={t('rck.sourceTitle')}
        content={
          <div style={{ maxWidth: 640, fontSize: '0.8125rem', lineHeight: 1.7 }}>
            <div>{t('rck.sourceDesc', { threshold: thresholdPct.toFixed(2) })}</div>
            <div style={{ color: WH.teal, marginTop: 6 }}>{t('rck.drillHint')}</div>
            <div style={{ color: WH.textDim, marginTop: 6 }}>
              {data?.meta?.source || ''}
              {data?.meta?.generated_at ? ` · ${t('rck.generated')}: ${data.meta.generated_at}` : ''}
            </div>
          </div>
        }
      >
        <div style={{ cursor: 'help' }}>
          <Alert
            type="info"
            showIcon
            icon={<InfoCircleOutlined />}
            style={{ marginBottom: 'var(--wh-space-md)', paddingTop: 6, paddingBottom: 6 }}
            message={
              <span>
                {t('rck.sourceTitle')}
                <Text type="secondary" style={{ marginLeft: 8, fontWeight: 400 }}>
                  {t('rck.sourceHover')}
                </Text>
              </span>
            }
          />
        </div>
      </Popover>

      {error && (
        <Alert type="error" showIcon style={{ marginBottom: 'var(--wh-space-md)' }}
          message={t('rck.loadFailed')} description={error} />
      )}
      {(data?.meta?.warnings || []).map((w, i) => (
        <Alert key={i} type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={fmtWarning(w, t)} />
      ))}

      {/* ---------- 月度汇总卡片 ---------- */}
      <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', flexWrap: 'wrap', marginBottom: 'var(--wh-space-md)' }}>
        {shownTechs.map(tb => (
          <StatCard
            key={tb.tech}
            title={`${tb.label} · ${t('rck.monthAvailability')}`}
            value={tb.month.availability == null ? '-' : (tb.month.availability * 100).toFixed(2)}
            suffix="%"
            accentColor={tb.month.availability != null && tb.month.availability >= threshold ? WH.teal : 'var(--wh-sev-major)'}
            subText={`${t('rck.roster')}: ${tb.roster_cells.toLocaleString('en-US')} · ${t('rck.daysWithData')}: ${tb.month.days_with_data}`}
            style={{ minWidth: 260, flex: '1 1 260px' }}
            onClick={(e) => openDrill(e, tb, '', 'availability')}
          />
        ))}
      </div>

      {/* ---------- 明细表（按制式分块，布局对齐参考报表） ---------- */}
      <Spin spinning={loading}>
        {/* 有错误时不显示「暂无数据（请先执行同步任务）」——那会把「后端路由缺失/接口不可用」
            误报成「没跑任务」，误导排查方向。 */}
        {!shownTechs.length && !loading && !error ? (
          <Card><Empty description={t('rck.noData')} /></Card>
        ) : (
          shownTechs.map(tb => (
            <Card
              key={tb.tech}
              style={{ marginBottom: 'var(--wh-space-md)' }}
              styles={{ body: { padding: 0, overflowX: 'auto' } }}
              title={
                <Space size="small">
                  <span style={{ color: WH.teal, fontWeight: 700 }}>{tb.label}</span>
                  <Tooltip title={locale === 'en' ? (tb.desc_en || tb.desc) : tb.desc}>
                    <Text type="secondary" style={{ fontSize: '0.75rem', fontWeight: 400 }}>
                      {locale === 'en' ? (tb.desc_en || tb.desc) : tb.desc}
                    </Text>
                  </Tooltip>
                </Space>
              }
            >
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr>
                    <th style={{ ...headCell, textAlign: 'left', minWidth: '13rem', position: 'sticky', left: 0, zIndex: 2 }}>
                      {t('rck.metric')}
                    </th>
                    {activeDays.map(d => (
                      <th key={d} style={headCell}>{fmtDay(d)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map((m, ri) => (
                    <tr
                      key={m.key}
                      style={{ background: m.highlight ? availBg : (ri % 2 ? mutedBg : undefined) }}
                    >
                      <td style={{ ...metricCell, background: m.highlight ? availBg : WH.cardBg }}>
                        {t(m.labelKey)}
                      </td>
                      {activeDays.map(d => {
                        const v = tb.days?.[d]?.[m.key] as number | null | undefined
                        const isAvail = m.key === 'availability'
                        const warn = isAvail && v != null && v < threshold
                        const clickable = v != null
                        return (
                          <td
                            key={d}
                            onClick={clickable ? (e) => openDrill(e, tb, d, m.key) : undefined}
                            title={clickable ? t('rck.drillHint') : undefined}
                            style={{
                              ...numCell,
                              fontWeight: m.highlight ? 700 : 400,
                              color: warn ? 'var(--wh-sev-major)' : (m.highlight ? WH.teal : WH.text),
                              cursor: clickable ? 'pointer' : 'default',
                            }}
                          >
                            {fmtCell(v, m.fmt)}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))
        )}
      </Spin>

      {/* ==================== 小区级明细下钻弹窗（可拖动 + 可搜索 + 可导出） ==================== */}
      <DraggableClickModal
        open={!!drill}
        anchor={drillAnchor}
        onClose={() => { setDrill(null); setDrillData(null); setDrillError(''); setDrillQuery('') }}
        width={1400}
        title={
          <span>
            {drill
              ? t('rck.drill.title', {
                label: drill.label,
                day: drill.day ? fmtDay(drill.day) : t('rck.drill.monthSuffix'),
                metric: t(drill.metricKey),
              })
              : ''}
            <Tag color="cyan" style={{ marginLeft: 8 }}>
              {drillQuery.trim()
                ? `${drillRows.length} / ${drillAll.length}`
                : t('common.records', { n: drillRows.length })}
            </Tag>
          </span>
        }
      >
        {drill && (
          <>
            <div style={{
              display: 'flex', flexWrap: 'wrap', alignItems: 'center',
              justifyContent: 'space-between', gap: 10, marginBottom: 10,
            }}>
              <Space size={12} wrap>
                <Tag color="blue">{t('rck.drill.cellsWithData')} {drillData?.total ?? 0}</Tag>
                <Tag color="green">{t('rck.drill.meeting')} {drillData?.meeting ?? 0}</Tag>
                <Tag color="red">{t('rck.drill.below')} {drillData?.below ?? 0}</Tag>
                <Tag>{t('rck.drill.blank')} {drillData?.blank ?? 0}</Tag>
                <Text type="secondary">
                  {t('rck.roster')}: {drillData?.roster_cells ?? 0}
                  　{t('rck.threshold')}: {((drillData?.threshold ?? threshold) * 100).toFixed(2)}%
                </Text>
              </Space>
              <Space size={8} wrap>
                <Input.Search
                  allowClear
                  size="small"
                  style={{ width: 260 }}
                  placeholder={t('rck.drill.search')}
                  value={drillQuery}
                  onChange={e => setDrillQuery(e.target.value)}
                />
                <Button size="small" icon={<DownloadOutlined />}
                  disabled={!drillRows.length} onClick={exportDrill}>
                  {t('common.exportExcel')}
                </Button>
              </Space>
            </div>
            {drillError && (
              <Alert type="error" showIcon style={{ marginBottom: 10 }}
                message={t('rck.drill.loadFailed')} description={drillError} />
            )}
            <Table<DrillRow>
              size="small"
              rowKey="cell"
              loading={drillLoading}
              dataSource={drillRows}
              locale={{ emptyText: <Empty description={t('rck.drill.empty')} /> }}
              pagination={{
                pageSize: 20, showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                showTotal: n => t('common.records', { n }),
              }}
              scroll={{ x: 1620 }}
              columns={[
                {
                  title: t('rck.drill.cell'), dataIndex: 'cell',
                  width: 230, fixed: 'left' as const, ellipsis: true,
                },
                {
                  title: t('rck.drill.cellId'), dataIndex: 'cell_id',
                  width: 90, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.siteId'), dataIndex: 'site_id',
                  width: 100, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.siteName'), dataIndex: 'site_name',
                  width: 190, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.ne'), dataIndex: 'ne',
                  width: 170, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.subnet'), dataIndex: 'subnet',
                  width: 150, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.band'), dataIndex: 'band',
                  width: 150, ellipsis: true,
                  render: (v?: string) => v || <Text type="secondary">-</Text>,
                },
                {
                  title: t('rck.drill.ratio'), dataIndex: 'ratio', width: 110,
                  align: 'right' as const,
                  render: (v: number | null) => v == null
                    ? <Text type="secondary">-</Text>
                    : (
                      <span style={{
                        fontWeight: 600,
                        fontVariantNumeric: 'tabular-nums',
                        color: v >= (drillData?.threshold ?? threshold) ? WH.teal : 'var(--wh-sev-major)',
                      }}>
                        {(v * 100).toFixed(2)}%
                      </span>
                    ),
                },
                {
                  title: t('rck.drill.status'), dataIndex: 'status', width: 100,
                  render: (v: DrillRow['status']) => (
                    <Tag color={STATUS_COLOR[v]}>{t(`rck.drill.${v}`)}</Tag>
                  ),
                },
                ...(drill.day ? [] : [
                  {
                    title: t('rck.drill.daysWithData'), dataIndex: 'days_with_data',
                    width: 110, align: 'right' as const,
                  },
                  {
                    title: t('rck.drill.daysMeeting'), dataIndex: 'days_meeting',
                    width: 110, align: 'right' as const,
                    render: (v?: number) => v == null
                      ? <Text type="secondary">-</Text>
                      : <span style={{ color: WH.teal }}>{v}</span>,
                  },
                  {
                    title: t('rck.drill.daysBelow'), dataIndex: 'days_below',
                    width: 110, align: 'right' as const,
                    render: (v?: number) => v == null
                      ? <Text type="secondary">-</Text>
                      : <span style={{ color: v > 0 ? 'var(--wh-sev-major)' : undefined }}>{v}</span>,
                  },
                ]),
              ]}
            />
          </>
        )}
      </DraggableClickModal>
    </div>
  )
}
