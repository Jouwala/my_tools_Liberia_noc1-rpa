/* ============================================================================
 * CR 变更分析 —— 类型、常量与纯格式化工具
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（该文件原本 897 行，超出 AGENTS.md 第三节 2
 * 的「单个文件不超过 500 行」上限）。这里只放**无 React 依赖**的东西：
 * 类型、列定义、纯函数 —— 便于单独读、单独测，也避免页面组件文件继续膨胀。
 *
 * 类型与后端 `backend/services/cr_analysis_service.py` 的返回结构一一对应；
 * 改后端返回结构时**必须**同步这里。
 * ========================================================================== */

import { WH } from '../../theme'

/* ---- 一个 change_category 的完整计数行 ---- */
export type CatRow = {
  category: string
  total: number
  planned: number
  executed: number
  unexecuted: number
  on_time: number
  delayed: number
  closed: number
  open: number
  canceled: number
  /** 比率；分母为 0 时后端返回 null，界面渲染 '—'（不是 0） */
  completion_rate: number | null
  on_time_rate: number | null
  closure_rate: number | null
}

export type StatusRow = { status: string; cnt: number }
export type MonthRow = { month: string; total: number; planned: number; executed: number; closed: number }
export type SubRow = { category: string; sub_category: string; total: number; executed: number }

export type Overview = {
  meta: { start: string; end: string; table: string; time_col: string; warnings: string[] }
  summary: Omit<CatRow, 'category'> & { categories: number }
  rows: CatRow[]
  status_rows: StatusRow[]
  months: MonthRow[]
  sub_categories: SubRow[]
}

export type Filters = {
  categories: string[]; sub_categories: string[]; statuses: string[]
  default_start: string; default_end: string
  min_time: string; max_time: string; row_count: number
  error?: string
}

/** 下钻明细行：后端 _DETAIL_COLUMNS 的字段，全部可能为 null（空值显示 '—'） */
export type DetailRow = Record<string, string | null>

/* ---- 下钻批次：与后端 DRILL_METRICS 一一对应 ---- */
export type Metric =
  | 'total' | 'planned' | 'executed' | 'unexecuted'
  | 'on_time' | 'delayed' | 'closed' | 'open' | 'canceled'

/** 计数类的字段名（算小计、做列定义时复用，避免各处手抄一份） */
export const COUNT_FIELDS = [
  'total', 'planned', 'executed', 'unexecuted', 'on_time',
  'delayed', 'closed', 'open', 'canceled',
] as const

/** 统一空值展示：'—' 而不是 undefined / null / '0'（AGENTS.md 第三节 6） */
export const fmt = (v: unknown) => (v == null || v === '' ? '—' : String(v))

/** 比率展示：null → '—'，有值 → '62.8%' */
export const fmtRate = (v: number | null | undefined) => (v == null ? '—' : `${v}%`)

/**
 * 比率按阈值染色。
 * 语义：越高越好。返回 CSS 变量（**仅供 DOM 层使用**；ECharts 必须用
 * DARK/LIGHT 实值，canvas 解析不了 CSS 变量）。
 * 阈值是**业务约定**而非统计结论，放在一处便于统一调整。
 */
export function rateColor(rate: number | null): string {
  if (rate == null) return WH.textDim
  if (rate >= 80) return WH.ok
  if (rate >= 50) return WH.warn
  return WH.danger
}

/** CardBase 的语义等级，与 rateColor 同一套阈值（保持配色与卡片边框一致） */
export function rateLevel(rate: number | null): 'default' | 'ok' | 'warn' | 'crit' {
  if (rate == null) return 'default'
  if (rate >= 80) return 'ok'
  if (rate >= 50) return 'warn'
  return 'crit'
}

/** 明细弹窗的字段顺序（与后端 _DETAIL_COLUMNS 同序） */
export const DETAIL_FIELDS = [
  'change_request_id', 'cr_title', 'status', 'change_category', 'sub_category',
  'change_type', 'request_registration_time', 'planned_start_time', 'planned_end_time',
  'actual_start_time', 'actual_end_time', 'closed_time', 'implement_result',
  'creator', 'current_handler', 'implementer', 'vender', 'ne_node_name',
  'downtime_required', 'operating_circle_sub_center',
] as const

/**
 * 汇总随类别过滤一起变化 —— 表格小计与 KPI 必须来自同一份行数据。
 * 比率一律由分子分母现算，**不用**后端 summary（那份是未过滤的）。
 */
export function summarize(rows: CatRow[]): Overview['summary'] {
  const out = {
    total: 0, planned: 0, executed: 0, unexecuted: 0, on_time: 0,
    delayed: 0, closed: 0, open: 0, canceled: 0, categories: rows.length,
    completion_rate: null as number | null,
    on_time_rate: null as number | null,
    closure_rate: null as number | null,
  }
  for (const r of rows) for (const k of COUNT_FIELDS) out[k] += r[k]
  const rate = (n: number, d: number) => (d ? Math.round((n / d) * 1000) / 10 : null)
  out.completion_rate = rate(out.executed, out.planned)
  out.on_time_rate = rate(out.on_time, out.executed)
  out.closure_rate = rate(out.closed, out.total)
  return out
}
