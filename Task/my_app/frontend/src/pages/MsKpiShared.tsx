/* ============================================================================
 * MS Contract KPIs / WOs SLA 报表 —— 两个页面（?page=ms_wo_sla / ?page=ms_contract_kpi）
 * 共用的类型、格式化与 KPI 矩阵渲染件。
 *
 * 数据源与口径见 backend/services/ms_kpi_report_service.py 顶部 docstring：
 * 页面读的是任务产出的工作簿本体（多层合并表头 + 目标行 + Month 行），
 * 所有数字原样来自 Excel，不做二次加工；达标判定用「月值 vs 目标值 + 方向」。
 * ========================================================================== */
import { useMemo, useState } from 'react'
import { Empty, Segmented, Space, Tag, Typography } from 'antd'
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
      /* 卡片皮肤交给 CSS 层（.wh-stat-card / .wh-card-interactive），与其余页面的
         antd Card 走同一套浅色档描边+内发光+悬停上浮，不再在这里内联背景/描边/圆角
         —— 内联值会盖过统一层，正是这个组件此前游离在统一风格之外的原因。
         emphasis 仍保留：它只把描边提到实色，表达「该指标被强调」。 */
      className="wh-stat-card wh-card-interactive"
      style={{
        border: emphasis ? `1px solid ${color || WH.teal}` : undefined,
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
/** PerSite 分类名（与生成端一致：值是「达标站点占比」，目标 90%） */
const PERSITE_CATEGORY = 'PerSite KPIs'

/**
 * 按 KPIs Category（Operation / Network / PerSite）把指标分组。
 * 只在这里分组，不动后端结构 —— category 本来就随每个 Metric 返回。
 * 组顺序沿用矩阵里的出现顺序（与工作簿列序一致），组内也保持原序。
 */
export interface MetricGroup {
  category: string
  metrics: Metric[]
  met: number
  below: number
  unknown: number
  /** 分组是否为 PerSite 口径（值是「达标站点占比」，目标 90%） */
  persite: boolean
}

export function groupMetricsByCategory(metrics: Metric[]): MetricGroup[] {
  const order: string[] = []
  const bucket = new Map<string, Metric[]>()
  metrics.forEach(m => {
    const cat = m.category || '-'
    if (!bucket.has(cat)) { bucket.set(cat, []); order.push(cat) }
    bucket.get(cat)!.push(m)
  })
  return order.map(cat => {
    const list = bucket.get(cat)!
    return {
      category: cat,
      metrics: list,
      met: list.filter(m => m.met === true).length,
      below: list.filter(m => m.met === false).length,
      unknown: list.filter(m => m.met === null || m.met === undefined).length,
      persite: cat === PERSITE_CATEGORY,
    }
  })
}

/**
 * 给矩阵「列分类筛选」用的两张表：列 key -> 分类、分类 -> 出现顺序。
 * 分类顺序沿用工作簿列序（与 groupMetricsByCategory 的口径一致）。
 * 只统计**有分类名**的列；WOs SLA 那张表没有分类行，返回空 map，
 * 调用方据此不渲染任何筛选控件（保持该页原样）。
 */
export function matrixCategoryMaps(matrix: Matrix): {
  byCol: Record<string, string>
  order: string[]
} {
  const byCol: Record<string, string> = {}
  const order: string[] = []
  matrix.columns.forEach(c => {
    const cat = (c.category || '').trim()
    if (!cat) return
    byCol[c.key] = cat
    if (!order.includes(cat)) order.push(cat)
  })
  return { byCol, order }
}

/**
 * 列分类的**顺序记忆**：跨矩阵/跨刷新保持「分类首次出现的顺序」。
 *
 * 为什么需要它：日数据按天滚动，某一天某个分类的值全为空时，Excel 里那一整组
 * 列会不存在 —— 若顺序直接取自矩阵，"PerSite 是否在第一列"会随日期漂移，
 * 用户点开的「第一列」第二天可能换成别的分类。这里按 日期 维护一份累积集合，
 * 分类一旦出现过就固定在原来的位置，后面的新分类追加到末尾。
 */
const CATEGORY_LATCH_KEY = 'msKpi.catOrder.v1'

export function latchCategoryOrder(periodKeys: string[], now: string[]): string[] {
  if (!now.length) return []
  let store: Record<string, string[]> = {}
  try {
    const raw = localStorage.getItem(CATEGORY_LATCH_KEY)
    store = raw ? (JSON.parse(raw) as Record<string, string[]>) : {}
  } catch { store = {} }
  const merged: string[] = []
  const push = (c: string) => { if (c && !merged.includes(c)) merged.push(c) }
  periodKeys.forEach(k => (store[k] || []).forEach(push))
  now.forEach(push)
  // 回写：只保留 periodKeys 覆盖的日期 + 新补的，避免 localStorage 无限增长
  const next: Record<string, string[]> = {}
  periodKeys.forEach(k => { next[k] = merged })
  try {
    localStorage.setItem(CATEGORY_LATCH_KEY, JSON.stringify(next))
  } catch { /* 隐私模式下写入失败：仅退化为按当前矩阵顺序，不影响功能 */ }
  return merged
}

/** 指标卡单卡（分组页签里的卡） */
function MetricCard(props: {
  m: Metric
  matrix: Matrix
  loc: string
  t: (k: string) => string
  onPick?: (m: Metric) => void
  compact?: boolean
}) {
  const { m, matrix, loc, t, onPick, compact } = props
  const color = metColor(m.met)
  return (
    <div
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
}

/** 一组卡片（含组标题行） */
function MetricCardGroup(props: {
  group: MetricGroup
  matrix: Matrix
  loc: string
  t: (k: string) => string
  onPick?: (m: Metric) => void
  compact?: boolean
}) {
  const { group, matrix, loc, t, onPick, compact } = props
  return (
    <div style={{ marginBottom: 14 }}>
      <Space size={6} wrap style={{ marginBottom: 8 }}>
        <Text style={{ color: WH.text, fontSize: 13, fontWeight: 600 }}>{group.category}</Text>
        <Tag color="green" style={{ marginInlineEnd: 0 }}>{`${t('msKpi.met')}: ${group.met}`}</Tag>
        {group.below > 0 && (
          <Tag color="red" style={{ marginInlineEnd: 0 }}>{`${t('msKpi.below')}: ${group.below}`}</Tag>
        )}
        {group.unknown > 0 && (
          <Tag style={{ marginInlineEnd: 0 }}>{`${t('msKpi.noData')}: ${group.unknown}`}</Tag>
        )}
        <Text style={{ color: WH.textDim, fontSize: 11 }}>
          {`${group.metrics.length} ${t('msKpi.kpiCount')}`}
        </Text>
        {group.persite && (
          <Text style={{ color: WH.textDim, fontSize: 11 }}>{t('msKpi.persiteTarget')}</Text>
        )}
      </Space>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {group.metrics.map(m => (
          <MetricCard key={`${m.category}|${m.group}|${m.key}`} m={m} matrix={matrix}
            loc={loc} t={t} onPick={onPick} compact={compact} />
        ))}
      </div>
    </div>
  )
}

/**
 * 合同 KPI 卡组。
 * - 不分组（默认）：平铺，WOs SLA 页面沿用这个行为；
 * - `groupByCategory`：按 Operation / Network / PerSite 三个页签分类展示，
 *   页签标签由调用方通过 `categoryLabels` 注入，避免动态拼 i18n key。
 */
export function MetricCards(props: {
  matrix: Matrix
  loc: string
  t: (k: string) => string
  onPick?: (m: Metric) => void
  compact?: boolean
  groupByCategory?: boolean
  categoryLabels?: Record<string, string>
}) {
  const { matrix, loc, t, onPick, compact, groupByCategory, categoryLabels } = props
  const groups = useMemo(
    () => (groupByCategory ? groupMetricsByCategory(matrix.metrics) : []),
    [matrix, groupByCategory],
  )
  const [activeCat, setActiveCat] = useState('')
  // 数据刷新后分类可能变化，取不到就回落到第一组
  const current = groups.find(g => g.category === activeCat) ?? groups[0]

  if (!groupByCategory) {
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {matrix.metrics.map(m => (
          <MetricCard key={`${m.category}|${m.group}|${m.key}`} m={m} matrix={matrix}
            loc={loc} t={t} onPick={onPick} compact={compact} />
        ))}
      </div>
    )
  }

  if (!current) return <Empty description={t('msKpi.empty')} />

  return (
    <>
      <Space wrap style={{ marginBottom: 14 }}>
        <Segmented
          className="wh-seg"
          value={current.category}
          onChange={(v) => setActiveCat(String(v))}
          options={groups.map(g => {
            const label = categoryLabels?.[g.category] ?? g.category
            const below = g.below > 0 ? ` · ${g.below} ${t('msKpi.below')}` : ''
            return {
              value: g.category,
              label: `${label} (${g.met}/${g.metrics.length}${below})`,
            }
          })}
        />
      </Space>
      <MetricCardGroup group={current} matrix={matrix} loc={loc} t={t}
        onPick={onPick} compact={compact} />
    </>
  )
}

/** `KpiMatrixTable` 的列分类显隐控制（受控，状态由调用方持有） */
export interface MatrixColumnFilter {
  /** 默认展示的分类；空数组 = 全部展示 */
  defaultCats: string[]
  /** 用户主动打开的分类（优先级最高） */
  shownCats: string[]
  /** 用户主动关闭的分类 */
  hiddenCats: string[]
  setShownCats: (v: string[]) => void
  setHiddenCats: (v: string[]) => void
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
  /**
   * 列分类显隐（可选）。不传 = 全部列常显（WOs SLA 页沿用原行为）。
   * `defaultCats` 未给出时默认全部显示；`shownCats` / `hiddenCats` 记录用户手动切换。
   */
  columnFilter?: MatrixColumnFilter
}) {
  const { matrix, loc, t, onPickMetric, maxHeight = 620 } = props

  // 列 key -> 指标（值列才有指标；Total/Within SLA 这类角色列没有）
  const metricByCol = useMemo(() => {
    const map: Record<string, Metric> = {}
    matrix.metrics.forEach(m => { map[m.value_key] = m })
    return map
  }, [matrix])

  /* ---------- 列分类显隐（2026-10-18：PerSite 默认隐藏，点开才看）----------
     用户诉求：Report detail 里 PerSite KPIs 那一大组列太宽，默认收起。
     用**运行时筛选**而不是默认值：默认值只在首次打开生效，用户点一次「显示」
     后就会被 effect 改回去，等于点了没用。副作用是筛选状态不落盘，
     刷新页面回到默认收起 —— 对"默认隐藏"来说正是期望行为。 */
  const colFilter = props.columnFilter
  const { byCol: colCat, order: colCatOrder } = useMemo(() => matrixCategoryMaps(matrix), [matrix])
  /** 没有任何列分类的矩阵（如 WOs SLA）不渲染筛选控件，行为与改动前一致。 */
  const filterable = !!colFilter && colCatOrder.length > 0
  // 分类顺序按日期记忆，避免日数据缺组时「第一列」漂移
  const periodKeys = useMemo(() => matrix.rows.map(r => r.label), [matrix])
  const orderedCats = useMemo(
    () => (filterable ? latchCategoryOrder(periodKeys, colCatOrder) : []),
    // periodKeys 是 matrix.rows 的派生值，跟随 matrix 即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filterable, colCatOrder, matrix],
  )
  /** 默认展示的分类：未配置默认值 → 全部（沿用原行为）；配置了但全部不可见 → 全部。 */
  const defaultCats = useMemo(() => {
    const want = colFilter?.defaultCats ?? []
    return want.length ? want : orderedCats
  }, [colFilter, orderedCats])
  const isColVisible = (key: string): boolean => {
    if (!filterable) return true
    const cat = colCat[key] ?? ''
    if (!cat) return true // 无分类的列（首列日期已单独渲染）始终保留
    const hidden = colFilter?.hiddenCats ?? []
    const shown = colFilter?.shownCats ?? []
    if (shown.includes(cat)) return true
    if (hidden.includes(cat)) return false
    return defaultCats.includes(cat)
  }
  // 依赖用原始值（array 序列化成串），因为调用方每次渲染都会新建 columnFilter 对象
  const shownKey = (colFilter?.shownCats ?? []).join('|')
  const hiddenKey = (colFilter?.hiddenCats ?? []).join('|')
  const visCols = useMemo(
    () => matrix.columns.filter(c => isColVisible(c.key)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [matrix, filterable, shownKey, hiddenKey, defaultCats],
  )
  const isCatVisible = (cat: string): boolean => {
    if (!filterable) return true
    if (colFilter!.shownCats.includes(cat)) return true
    if (colFilter!.hiddenCats.includes(cat)) return false
    return defaultCats.includes(cat)
  }
  const toggleCat = (cat: string) => {
    if (!colFilter) return
    const on = isCatVisible(cat)
    const nextShown = new Set(colFilter.shownCats)
    const nextHidden = new Set(colFilter.hiddenCats)
    if (on) { nextShown.delete(cat); nextHidden.add(cat) } else { nextHidden.delete(cat); nextShown.add(cat) }
    colFilter.setShownCats(Array.from(nextShown))
    colFilter.setHiddenCats(Array.from(nextHidden))
  }

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

  /* ---------- 表头按可见列重排 ----------
     叶子层可以直接按可见列序重建（每个叶子占 1 列）；分组/分类层要按
     「同一可见分类下、同名连续列」重新合并 span，否则收起 PerSite 后
     Operation / Network 的 colSpan 仍按原始列数算，表头会整体错位。 */
  const leafIdx = matrix.header_rows.length - 1
  const visibleIdx = new Set(visCols.map(c => c.index))
  const headerForRender: HeaderCell[][] = matrix.header_rows.map((cells, li) => {
    if (li === leafIdx) {
      return visCols.map(col => ({ text: col.label, colSpan: 1, level: cells[0]?.level ?? 'column' }))
    }
    const level = cells[0]?.level ?? ''
    // 分类层（第 0 层，仅有分类行的矩阵）取 column.category；
    // 其余非叶子层（WOs SLA 的分组层）该表本身没有分类，不会走到这里
    const isCatLevel = li === 0 && matrix.columns.some(c => !!c.category)
    const out: HeaderCell[] = []
    visCols.forEach(col => {
      const text = isCatLevel ? col.category : col.group
      if (!text) return
      const last = out[out.length - 1]
      if (last && last.text === text) last.colSpan += 1
      else out.push({ text, colSpan: 1, level })
    })
    return out
  })

  return (
    <div>
      {/* 列分类开关：默认只展示非 PerSite 的分类，PerSite 需手动点开 */}
      {filterable && (
        <Space size={6} wrap style={{ marginBottom: 8 }}>
          <Text style={{ color: WH.textDim, fontSize: 12 }}>{t('msKpi.colFilter')}</Text>
          {orderedCats.map(cat => (
            <Tag.CheckableTag
              key={cat}
              checked={isCatVisible(cat)}
              onChange={() => toggleCat(cat)}
            >
              {cat}
            </Tag.CheckableTag>
          ))}
        </Space>
      )}
      <div style={{ overflow: 'auto', maxHeight }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 12, width: '100%' }}>
          <thead>
            {headerForRender.map((cells, li) => (
              <tr key={li}>
                {li === 0 && (
                  <th
                    rowSpan={headerForRender.length}
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
                  const leaf = li === headerForRender.length - 1
                  const col = leaf ? visCols[ci] : undefined
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
                {visCols.map(col => renderCell(col, matrix.month[col.key] ?? null, true))}
              </tr>
            )}
            {matrix.rows.map(r => (
              <tr key={r.label}>
                <td style={{ ...cellStyle, ...stickyCol, color: WH.text }}>{r.label}</td>
                {visCols.map(col => renderCell(col, r.values[col.key] ?? null, false))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
