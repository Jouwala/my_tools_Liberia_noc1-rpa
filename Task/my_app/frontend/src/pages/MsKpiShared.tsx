/* ============================================================================
 * MS Contract KPIs / WOs SLA 报表 —— 两个页面（?page=ms_wo_sla / ?page=ms_contract_kpi）
 * 共用的类型、格式化与 KPI 矩阵渲染件。
 *
 * 数据源与口径见 backend/services/ms_kpi_report_service.py 顶部 docstring：
 * 页面读的是任务产出的工作簿本体（多层合并表头 + 目标行 + Month 行），
 * 所有数字原样来自 Excel，不做二次加工；达标判定用「月值 vs 目标值 + 方向」。
 * ========================================================================== */
import { useMemo } from 'react'
import { Empty, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import ReactECharts from 'echarts-for-react'
import { useTheme, WH, darkTooltip, axisLabel, axisLine, splitLine } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import { numLocale, useI18n } from '../i18n'

const { Text } = Typography

// ==================== 类型（与后端 service 返回结构对齐） ====================
export type MetricRole = 'total' | 'within' | 'achieve' | 'value'
export type ValueFormat = 'percent' | 'number'

export interface MatrixColumn {
  key: string
  index: number
  label: string
  group: string
  category: string
  role: MetricRole
  lower_is_better: boolean
  target: number | null
  target_source: 'target_row' | 'persite_ratio'
  format: ValueFormat
}
export interface HeaderCell {
  text: string
  colSpan: number
  level: string
}
export interface MatrixRow {
  label: string
  values: Record<string, number | null>
}
export interface Metric {
  key: string
  label: string
  label_full: string
  category: string
  group: string
  target: number | null
  target_source: 'target_row' | 'persite_ratio'
  format: ValueFormat
  lower_is_better: boolean
  value_key: string
  total_key: string | null
  within_key: string | null
  month_value: number | null
  month_total: number | null
  month_within: number | null
  met: boolean | null
  day_count: number
  met_days: number
  below_days: number
  min: number | null
  max: number | null
  avg: number | null
  gap?: number
}
export interface MatrixOverview {
  kpi_count: number
  met_count: number
  below_count: number
  unknown_count: number
  days: number
  first_day: string
  last_day: string
  worst: Metric[]
  best: Metric[]
}
export interface Matrix {
  sheet: string
  label_key: string
  title: string
  label_header: string
  header_rows: HeaderCell[][]
  columns: MatrixColumn[]
  rows: MatrixRow[]
  month: Record<string, number | null>
  month_label: string
  metrics: Metric[]
  overview: MatrixOverview
}
export interface SourceInfo {
  kind: string
  kind_label_en: string
  kind_label_zh: string
  task: string
  file: string
  path: string
  generated_at: string
  size: number
}
export interface SheetMeta {
  key: string
  label_key: string
  layout: 'kpi_matrix' | 'flat'
  records: number
  columns: number
  metrics: number
  days: number
}
export interface MsKpiSummary {
  kind: 'wo_sla' | 'contract_kpi'
  kind_label_en: string
  kind_label_zh: string
  source: SourceInfo
  overview: {
    kpi_count?: number
    met_count?: number
    below_count?: number
    unknown_count?: number
    days?: number
    first_day?: string
    last_day?: string
    worst?: Metric[]
    best?: Metric[]
    categories?: { category: string; count: number; met_count: number; below_count: number }[]
    month_total?: number | null
    month_within?: number | null
    month_achieve?: number | null
    metric_count?: number
    wo_sla?: MatrixOverview
    flat_counts?: Record<string, number>
  }
  matrices: Record<string, Matrix>
  sheets: SheetMeta[]
  notes: string[]
  warnings: string[]
  generated_at: string
}

// ==================== 格式化 ====================
export const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 目标值/指标值统一格式化：percent 口径 ×100 后带 % */
export function fmtValue(v: number | null | undefined, format: ValueFormat, loc: string): string {
  if (v === null || v === undefined) return '-'
  if (format === 'percent') return `${(num(v) * 100).toLocaleString(loc, { maximumFractionDigits: 2 })}%`
  return num(v).toLocaleString(loc, { maximumFractionDigits: 2 })
}

/** 达标 -> 绿 / 未达标 -> 红 / 无数据 -> 灰 */
export function metColor(met: boolean | null | undefined): string {
  if (met === true) return WH.ok
  if (met === false) return WH.danger
  return WH.textDim
}

export function metLabel(met: boolean | null | undefined, t: (k: string) => string): string {
  if (met === true) return t('msKpi.met')
  if (met === false) return t('msKpi.below')
  return t('msKpi.noData')
}

/** 目标方向文案（越大越好 / 越小越好） */
export function directionText(m: { lower_is_better: boolean }, t: (k: string) => string): string {
  return t(m.lower_is_better ? 'msKpi.lowerBetter' : 'msKpi.higherBetter')
}

export function StatCard(props: {
  label: string
  value: number | string
  unit?: string
  hint?: React.ReactNode
  color?: string
  emphasis?: boolean
  onClick?: () => void
}) {
  const { label, value, unit, hint, color, emphasis, onClick } = props
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick
        ? (e) => { if (e.key === 'Enter') (e.target as HTMLElement).click() }
        : undefined}
      style={{
        background: WH.cardBg,
        border: emphasis ? `1px solid ${color || WH.teal}` : WH.cardBorder,
        borderRadius: 8,
        padding: '12px 14px',
        height: '100%',
        boxSizing: 'border-box',
        cursor: onClick ? 'pointer' : undefined,
      }}
    >
      <div style={{ color: WH.textMuted, fontSize: 12, marginBottom: 6, whiteSpace: 'nowrap' }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ color: color || WH.teal, fontSize: 24, fontWeight: 700, lineHeight: 1.15 }}>
          {value}
        </span>
        {unit && <span style={{ color: WH.textDim, fontSize: 12 }}>{unit}</span>}
      </div>
      {hint && (
        <div style={{ color: WH.textDim, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>{hint}</div>
      )}
    </div>
  )
}

// ==================== 指标卡片（一行一个 KPI） ====================
export function MetricCards(props: {
  matrix: Matrix
  loc: string
  t: (k: string) => string
  onPick?: (m: Metric) => void
  compact?: boolean
}) {
  const { matrix, loc, t, onPick, compact } = props
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
      {matrix.metrics.map(m => {
        const color = metColor(m.met)
        return (
          <div
            key={`${m.category}|${m.group}|${m.key}`}
            onClick={onPick ? () => onPick(m) : undefined}
            role={onPick ? 'button' : undefined}
            tabIndex={onPick ? 0 : undefined}
            onKeyDown={onPick
              ? (e) => { if (e.key === 'Enter') (e.target as HTMLElement).click() }
              : undefined}
            style={{
              background: WH.cardBg,
              border: m.met === false ? `1px solid ${WH.danger}` : WH.cardBorder,
              borderRadius: 8,
              padding: compact ? '8px 10px' : '10px 12px',
              cursor: onPick ? 'pointer' : undefined,
              boxSizing: 'border-box',
              flex: `1 1 ${compact ? 168 : 208}px`,
              maxWidth: compact ? 300 : 380,
              minWidth: compact ? 148 : 186,
            }}
            title={m.label_full}
          >
            <div style={{
              color: WH.textMuted, fontSize: 11, marginBottom: 6, lineHeight: 1.4,
              minHeight: compact ? 16 : 30, overflow: 'hidden', textOverflow: 'ellipsis',
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
            }}>
              {m.label}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
              <span style={{ color, fontSize: compact ? 18 : 22, fontWeight: 700, lineHeight: 1.1 }}>
                {fmtValue(m.month_value, m.format, loc)}
              </span>
              <span style={{ color: WH.textDim, fontSize: 11 }}>
                {`/ ${fmtValue(m.target, m.format, loc)}`}
              </span>
            </div>
            <Space size={4} wrap>
              <Tag color={m.met === true ? 'green' : m.met === false ? 'red' : 'default'}
                style={{ marginInlineEnd: 0 }}>
                {metLabel(m.met, t)}
              </Tag>
              <Tag style={{ marginInlineEnd: 0 }}>
                {`${m.met_days}/${matrix.rows.length}${t('msKpi.daysMetSuffix')}`}
              </Tag>
            </Space>
            {m.month_total !== null && m.month_total !== undefined && (
              <div style={{ color: WH.textDim, fontSize: 11, marginTop: 6 }}>
                {`${num(m.month_within).toLocaleString(loc)} / ${num(m.month_total).toLocaleString(loc)}`}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ==================== KPI 矩阵表（Excel 版式） ====================
/**
 * 多层合并表头 + 目标行 + Month 汇总行 + 日行，与工作簿里的版式一致。
 * - 首列与表头吸附，方便横向滚动时定位；
 * - Achieve / 值列按「月值 vs 目标」着色（绿=达标、红=未达标），其余列中性；
 * - 点击列头或单元格 -> 打开该指标的日趋势弹窗。
 */
export function KpiMatrixTable(props: {
  matrix: Matrix
  loc: string
  t: (k: string) => string
  onPickMetric?: (m: Metric, anchor?: { x: number; y: number }) => void
  maxHeight?: number
}) {
  const { matrix, loc, t, onPickMetric, maxHeight = 620 } = props

  // 列 key -> 指标（值列才有指标；Total/Within SLA 这类角色列没有）
  const metricByCol = useMemo(() => {
    const map: Record<string, Metric> = {}
    matrix.metrics.forEach(m => { map[m.value_key] = m })
    return map
  }, [matrix])

  const cellStyle: React.CSSProperties = {
    padding: '4px 8px',
    borderBottom: `1px solid ${WH.cardBorder}`,
    borderRight: `1px solid ${WH.cardBorder}`,
    whiteSpace: 'nowrap',
    fontSize: 12,
  }
  const headStyle: React.CSSProperties = {
    padding: '4px 8px',
    color: WH.textMuted,
    borderBottom: `1px solid ${WH.cardBorder}`,
    borderRight: `1px solid ${WH.cardBorder}`,
    fontSize: 11,
    fontWeight: 500,
    whiteSpace: 'nowrap',
    background: WH.cardBg,
    position: 'sticky',
    top: 0,
    zIndex: 2,
  }
  const stickyCol: React.CSSProperties = {
    position: 'sticky',
    left: 0,
    background: WH.cardBg,
    zIndex: 1,
  }

  const renderCell = (col: MatrixColumn, value: number | null, isMonth: boolean) => {
    const metric = metricByCol[col.key]
    const hasTarget = !!metric && metric.target !== null
    const met = hasTarget ? metric!.met : null
    // Month 行整体按达标着色；日行只把「未达标」标红，避免一片绿反而看不出问题
    const color = !hasTarget ? WH.text
      : isMonth ? (met === true ? WH.ok : met === false ? WH.danger : WH.text)
        : (met === false ? WH.danger : WH.text)
    const weight = isMonth || (hasTarget && met === false) ? 600 : 400
    return (
      <td
        key={col.key}
        style={{
          ...cellStyle,
          textAlign: 'right',
          color,
          fontWeight: weight,
        }}
      >
        {value === null || value === undefined
          ? <Text type="secondary">-</Text>
          : fmtValue(value, col.format, loc)}
      </td>
    )
  }

  return (
    <div style={{ overflow: 'auto', maxHeight }}>
      <table style={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 12, width: '100%' }}>
        <thead>
          {matrix.header_rows.map((cells, li) => (
            <tr key={li}>
              {li === 0 && (
                <th
                  rowSpan={matrix.header_rows.length}
                  style={{
                    ...headStyle,
                    ...stickyCol,
                    left: 0,
                    top: 0,
                    zIndex: 3,
                    textAlign: 'left',
                    verticalAlign: 'bottom',
                  }}
                >
                  {matrix.label_header}
                </th>
              )}
              {cells.map((c, ci) => {
                // 叶子层：若该列有指标（值列）则可点击查看趋势
                const leaf = li === matrix.header_rows.length - 1
                const col = leaf ? matrix.columns[ci] : undefined
                const metric = col ? metricByCol[col.key] : undefined
                const clickable = !!metric && !!onPickMetric
                return (
                  <th
                    key={`${li}-${ci}-${c.text}`}
                    colSpan={c.colSpan}
                    onClick={clickable
                      ? (e) => onPickMetric!(metric!, { x: e.clientX, y: e.clientY })
                      : undefined}
                    title={clickable ? `${metric!.label_full} — ${t('msKpi.trendHint')}` : undefined}
                    style={{
                      ...headStyle,
                      textAlign: 'center',
                      cursor: clickable ? 'pointer' : undefined,
                      // 值列（有目标的指标）列头直接用状态色标出达标/未达标，
                      // 比在表头上加一条横线更不容易被误读成分组名的下划线
                      color: metric ? metColor(metric.met) : WH.textMuted,
                      fontWeight: metric ? 600 : 500,
                      textDecoration: clickable ? 'underline dotted' : undefined,
                    }}
                  >
                    {c.text}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {/* Month 汇总行 —— Excel 里就在日行上方，这里保持同样的顺序 */}
          {Object.keys(matrix.month).length > 0 && (
            <tr style={{ background: 'var(--wh-teal-20)' }}>
              <td style={{ ...cellStyle, ...stickyCol, fontWeight: 700, color: WH.teal }}>
                {matrix.month_label}
              </td>
              {matrix.columns.map(col => renderCell(col, matrix.month[col.key] ?? null, true))}
            </tr>
          )}
          {matrix.rows.map(r => (
            <tr key={r.label}>
              <td style={{ ...cellStyle, ...stickyCol, color: WH.text }}>{r.label}</td>
              {matrix.columns.map(col => renderCell(col, r.values[col.key] ?? null, false))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ==================== 指标日趋势弹窗 ====================
export function MetricTrendModal(props: {
  open: boolean
  metric: Metric | null
  matrix: Matrix | null
  anchor?: { x: number; y: number } | null
  onClose: () => void
  t: (k: string) => string
}) {
  const { open, metric, matrix, anchor, onClose, t } = props
  const { isDark } = useTheme()
  const { locale } = useI18n()
  const loc = numLocale(locale)

  const option = useMemo(() => {
    if (!metric || !matrix) return {}
    const percent = metric.format === 'percent'
    const days = matrix.rows.map(r => r.label)
    const values = matrix.rows.map(r => {
      const v = r.values[metric.value_key]
      if (v === null || v === undefined) return null
      return percent ? Number((num(v) * 100).toFixed(4)) : num(v)
    })
    const target = metric.target === null ? null : (percent ? num(metric.target) * 100 : num(metric.target))
    const color = metColor(metric.met)
    return {
      tooltip: {
        ...darkTooltip(isDark),
        trigger: 'axis',
        valueFormatter: (v: number | null) => (v === null || v === undefined
          ? '-' : `${num(v).toLocaleString(loc, { maximumFractionDigits: 2 })}${percent ? '%' : ''}`),
      },
      grid: { left: 60, right: 24, top: 40, bottom: 56 },
      xAxis: {
        type: 'category' as const,
        data: days,
        axisLabel: { ...axisLabel(isDark), rotate: 45 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value' as const,
        splitLine: splitLine(isDark),
        axisLabel: { ...axisLabel(isDark), formatter: percent ? '{value}%' : '{value}' },
        scale: true,
      },
      series: [{
        type: 'line' as const,
        name: metric.label,
        data: values,
        smooth: true,
        symbolSize: 7,
        connectNulls: false,
        itemStyle: { color },
        lineStyle: { width: 2.5, color },
        areaStyle: { opacity: 0.10, color },
        markLine: target === null ? undefined : {
          silent: true,
          symbol: 'none',
          data: [{
            yAxis: Number(target.toFixed(4)),
            lineStyle: { color: WH.sev.Warning, type: 'dashed' as const, width: 1.6 },
            label: {
              formatter: `${t('msKpi.target')} ${target.toLocaleString(loc, { maximumFractionDigits: 2 })}${percent ? '%' : ''}`,
              color: WH.sev.Warning,
              position: 'insideEndTop' as const,
            },
          }],
        },
      }],
    }
  }, [metric, matrix, isDark, loc, t])

  if (!metric || !matrix) return null

  return (
    <DraggableClickModal
      open={open}
      title={(
        <Space wrap>
          <span>{t('msKpi.trendTitle')}</span>
          <Tag color="cyan">{metric.label_full}</Tag>
          <Tag color={metric.met === true ? 'green' : metric.met === false ? 'red' : 'default'}>
            {metLabel(metric.met, t)}
          </Tag>
          <Tag>{`${t('msKpi.target')}: ${fmtValue(metric.target, metric.format, loc)}`}</Tag>
          <Tag>{directionText(metric, t)}</Tag>
          {metric.target_source === 'persite_ratio' && <Tag color="orange">{t('msKpi.persiteTarget')}</Tag>}
        </Space>
      )}
      anchor={anchor ?? null}
      onClose={onClose}
      width="88%"
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 8 }}>
        {([
          ['msKpi.stat.month', fmtValue(metric.month_value, metric.format, loc), metColor(metric.met)],
          ['msKpi.stat.metDays', `${metric.met_days}/${matrix.rows.length}`, WH.text],
          ['msKpi.stat.belowDays', String(metric.below_days), metric.below_days > 0 ? WH.danger : WH.text],
          ['msKpi.stat.min', fmtValue(metric.min, metric.format, loc), WH.text],
          ['msKpi.stat.max', fmtValue(metric.max, metric.format, loc), WH.text],
          ['msKpi.stat.avg', fmtValue(metric.avg, metric.format, loc), WH.text],
        ] as [string, string, string][]).map(([labelKey, value, color]) => (
          <div key={labelKey} style={{ minWidth: 110 }}>
            <div style={{ color: WH.textMuted, fontSize: 11 }}>{t(labelKey)}</div>
            <div style={{ color, fontSize: 18, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>
      {matrix.rows.length
        ? <ReactECharts option={option} style={{ height: 360, width: '100%' }} notMerge />
        : <Empty description={t('msKpi.empty')} />}
      {metric.month_total !== null && metric.month_total !== undefined && (
        <div style={{ marginTop: 8, color: WH.textMuted, fontSize: 12 }}>
          {`${t('msKpi.stat.woMonth')}: ${num(metric.month_within).toLocaleString(loc)} / ${num(metric.month_total).toLocaleString(loc)}`}
        </div>
      )}
    </DraggableClickModal>
  )
}

// ==================== 通用扁平表（FineBI 规划 / 自动化报表清单） ====================
export function FlatTable(props: {
  columns: string[]
  numericColumns: string[]
  rows: Record<string, string | number | null>[]
  loading?: boolean
  loc: string
  t: (k: string) => string
  onRowClick?: (row: Record<string, string | number | null>, e: React.MouseEvent) => void
  pagination?: false | {
    current: number
    pageSize: number
    total: number
    onChange: (page: number, pageSize: number) => void
  }
}) {
  const { columns, numericColumns, rows, loading, loc, t, onRowClick, pagination } = props
  const numericSet = useMemo(() => new Set(numericColumns), [numericColumns])

  const cols = useMemo<ColumnsType<Record<string, string | number | null>>>(() => columns.map(name => ({
    title: name,
    dataIndex: name,
    key: name,
    ellipsis: true,
    align: numericSet.has(name) ? ('right' as const) : undefined,
    render: (v: string | number | null) => {
      if (v === null || v === undefined || v === '') return <Text type="secondary">-</Text>
      if (numericSet.has(name)) return num(v).toLocaleString(loc, { maximumFractionDigits: 2 })
      return <span style={{ whiteSpace: 'pre-wrap' }}>{String(v)}</span>
    },
  })), [columns, numericSet, loc])

  return (
    <Table<Record<string, string | number | null>>
      size="small"
      rowKey={(_r, i) => String(i)}
      columns={cols}
      dataSource={rows}
      loading={loading}
      scroll={{ x: 'max-content' }}
      onRow={onRowClick ? (record => ({
        onClick: (e) => onRowClick(record, e),
        style: { cursor: 'pointer' },
      })) : undefined}
      pagination={pagination === false || !pagination ? false : {
        current: pagination.current,
        pageSize: pagination.pageSize,
        total: pagination.total,
        size: 'small',
        showSizeChanger: true,
        pageSizeOptions: ['20', '50', '100', '200'],
        showTotal: (n) => `${n.toLocaleString(loc)} ${t('msKpi.rows')}`,
        onChange: pagination.onChange,
      }}
    />
  )
}

// ==================== 行详情弹窗（扁平表的原始值） ====================
export function RowDetailModal(props: {
  open: boolean
  row: Record<string, string | number | null> | null
  anchor?: { x: number; y: number } | null
  onClose: () => void
  t: (k: string) => string
  title?: string
}) {
  const { open, row, anchor, onClose, t, title } = props
  if (!row) return null
  const entries = Object.entries(row)
  return (
    <DraggableClickModal
      open={open}
      title={<Space wrap><span>{title || t('msKpi.detailTitle')}</span><Tag>{`${entries.length} ${t('msKpi.columns')}`}</Tag></Space>}
      anchor={anchor ?? null}
      onClose={onClose}
      width="76%"
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td style={{
                padding: '6px 10px', color: WH.textMuted, whiteSpace: 'nowrap',
                verticalAlign: 'top', borderBottom: `1px solid ${WH.cardBorder}`, width: 240,
              }}>
                {k}
              </td>
              <td style={{
                padding: '6px 10px', color: WH.text, wordBreak: 'break-word',
                whiteSpace: 'pre-wrap', borderBottom: `1px solid ${WH.cardBorder}`,
              }}>
                {v === null || v === undefined || v === ''
                  ? <Text type="secondary">-</Text> : String(v)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </DraggableClickModal>
  )
}
