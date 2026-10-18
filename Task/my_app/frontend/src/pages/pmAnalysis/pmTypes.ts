/* ============================================================================
 * PM 执行分析 —— 类型、常量与纯格式化工具
 * ============================================================================
 *
 * 与 `crAnalysis/crTypes.ts` 同构（两个页面共用一套「类型/常量」「图表」
 * 「列定义」「弹窗」四件套），便于对照维护。
 *
 * 类型与后端 `backend/services/pm_analysis_service.py` 的返回结构一一对应；
 * 改后端返回结构时**必须**同步这里。
 * ========================================================================== */

import { WH } from '../../theme'

/* ---- 一个 PM 计划（pmp_no）的完整计数行 ---- */
export type PlanRow = {
  pmp_no: string
  total: number
  closed: number
  open: number
  overdue: number
  on_time: number
  not_started: number
  /** 已完成但超期：事后补录 / 迟交 */
  closed_overdue: number
  /** 未完成且超期：真正压着的 */
  open_overdue: number
  open_on_time: number
  /** 条目级进度合计（completed_items / total_items 的和） */
  completed_items: number
  total_items: number
  sites: number
  window_start: string
  window_end: string
  /** 比率；分母为 0 时后端返回 null，界面渲染 '—'（不是 0） */
  closure_rate: number | null
  overdue_rate: number | null
  item_rate: number | null
}

export type StatusRow = { status: string; cnt: number; overdue: number }
export type MonthRow = { month: string; total: number; closed: number; overdue: number }
export type SiteRow = { site_name: string; total: number; overdue: number; open: number }
/** 流程步骤漏斗。`step` 是后端定义的键，顺序即真实时序（见 pm_caliber docstring） */
export type StepRow = { step: string; cnt: number }

export type Overview = {
  meta: { start: string; end: string; table: string; time_col: string; warnings: string[] }
  summary: {
    total: number; closed: number; open: number; overdue: number; on_time: number
    not_started: number; closed_overdue: number; open_overdue: number; open_on_time: number
    completed_items: number; total_items: number
    closure_rate: number | null; overdue_rate: number | null; start_rate: number | null
    plans: number
  }
  rows: PlanRow[]
  status_rows: StatusRow[]
  months: MonthRow[]
  sites: SiteRow[]
  steps: StepRow[]
}

/* ---- 里程碑（backend/services/pm_workflow_service.py 的返回结构） ----
 *
 * 顺序**严格对齐 eFlow 的 Workflow History**（`queryAllSteps`，payload
 * `eflow-pm-task`）：
 *   Create → Schedule → Accept → Process → PMManagerApprove → FLMLeaderApprove → Closed
 * 与 `STEP_KEYS` 的区别：那个是源表时间字段的集合（漏斗用），这个是用户看到的
 * 流程节点（里程碑条用）。以 Workflow History 为准，两者顺序一致。
 */

/** 里程碑 key，与后端 `pm_workflow_service._MILESTONE_DEFS` 同序同值 */
export type MilestoneKey =
  | 'created' | 'scheduled' | 'accepted' | 'processed'
  | 'pm_approved' | 'flm_approved' | 'closed'

export type Milestone = {
  key: MilestoneKey
  /** 对应流程步骤；closed 为 '' */
  step: string
  /** 已完成该节点的工单数（含已离开的） */
  done: number
  /** 当前停在该节点、等下一环节的工单数 */
  waiting: number
  /** 滞留单里等得最久的天数；无人滞留为 null → 不显示 */
  waiting_max_days: number | null
  /** 已离开该节点的平均 / 最长停留天数；无样本为 null → 显示 '—' */
  avg_days: number | null
  max_days: number | null
}

export type PmWorkflow = {
  meta: { start: string; end: string; table: string; pmp_no: string; warnings: string[] }
  milestones: Milestone[]
  total: number
  closed: number
  in_flight: number
}

/** 里程碑下钻行（后端 `drill_workflow` 的 rows） */
export type MilestoneDrillRow = {
  pmt_no: string
  status: string
  milestone: MilestoneKey
  entered_at: string | null
  left_at: string | null
  /** 已等待 / 停留天数；缺进入时间为 null → 显示 '—' */
  days: number | null
  current: boolean
  closed: boolean
}

/** 天数展示：null → '—'（不是 0），保留一位小数 */
export const fmtDays = (v: number | null | undefined) =>
  (v == null ? '—' : `${v.toFixed(1)}d`)

export type Filters = {
  pmp_nos: string[]; statuses: string[]; sites: string[]; handlers: string[]
  default_start: string; default_end: string
  min_time: string; max_time: string; row_count: number
  error?: string
}

/** 下钻明细行：后端 DETAIL_COLUMNS 的字段，全部可能为 null（空值显示 '—'） */
export type DetailRow = Record<string, string | null>

/* ---- 下钻批次：与后端 pm_caliber._BUCKETS 一一对应 ---- */
export type Metric =
  | 'total' | 'closed' | 'open' | 'overdue' | 'on_time'
  | 'not_started' | 'closed_overdue' | 'open_overdue' | 'open_on_time'

/** 计数类的字段名（算小计、做列定义时复用，避免各处手抄一份） */
export const COUNT_FIELDS = [
  'total', 'closed', 'open', 'overdue', 'on_time',
  'not_started', 'closed_overdue', 'open_overdue', 'open_on_time',
] as const

/** 统一空值展示：'—' 而不是 undefined / null / '0'（AGENTS.md 第三节 6） */
export const fmt = (v: unknown) => (v == null || v === '' ? '—' : String(v))

/** 比率展示：null → '—'，有值 → '45%' */
export const fmtRate = (v: number | null | undefined) => (v == null ? '—' : `${v}%`)

/** 整数千分位（条目数是 6 位数，不分组很难读） */
export const fmtNum = (v: number | null | undefined) =>
  (v == null ? '—' : v.toLocaleString('en-US'))

/**
 * 比率按阈值染色。语义：越高越好（关闭率 / 按时率 / 开始率）。
 * ⚠️ 超期率是「越低越好」，用 rateColorDesc()，不要用这个。
 * 返回 CSS 变量（**仅供 DOM 层使用**；ECharts 必须用 DARK/LIGHT 实值）。
 */
export function rateColor(rate: number | null): string {
  if (rate == null) return WH.textDim
  if (rate >= 80) return WH.ok
  if (rate >= 50) return WH.warn
  return WH.danger
}

/**
 * 「越低越好」的比率染色（用于超期率）。
 * 阈值与 rateColor 镜像：≤20% 好、≤50% 警告、其余危险。
 */
export function rateColorDesc(rate: number | null): string {
  if (rate == null) return WH.textDim
  if (rate <= 20) return WH.ok
  if (rate <= 50) return WH.warn
  return WH.danger
}

/** CardBase 的语义等级，与 rateColor 同一套阈值（保持配色与卡片边框一致） */
export function rateLevel(rate: number | null): 'default' | 'ok' | 'warn' | 'crit' {
  if (rate == null) return 'default'
  if (rate >= 80) return 'ok'
  if (rate >= 50) return 'warn'
  return 'crit'
}

/** 「越低越好」版本的等级（超期率卡片用） */
export function rateLevelDesc(rate: number | null): 'default' | 'ok' | 'warn' | 'crit' {
  if (rate == null) return 'default'
  if (rate <= 20) return 'ok'
  if (rate <= 50) return 'warn'
  return 'crit'
}

/** 明细弹窗的字段顺序（与后端 pm_caliber.DETAIL_COLUMNS 同序） */
export const DETAIL_FIELDS = [
  'pmt_no', 'status', 'title', 'pmp_no', 'pmt_overdue', 'site_name', 'asset_id',
  'template', 'completed_items', 'total_items',
  'current_task_start_time', 'current_task_end_time', 'created_time',
  'last_schedule_time', 'last_accept_time', 'last_pm_manager_approve_time',
  'last_process_time', 'last_flm_leader_approve_time', 'last_modified_time',
  'creator', 'current_handler', 'source',
] as const

/**
 * 流程步骤 → i18n key。
 * ⚠️ 必须是显式 switch 返回字面量（不能用 `t('pm.step.' + step)`）：
 * 动态拼 key 会被 `check:i18n` 读成键名 `pm.step.` 而报「字典缺失」
 * （AGENTS.md 第三节 1b 最后一条，`NocAnalyst.tsx` 是正确写法的参考）。
 *
 * 数组顺序即**Workflow History 顺序**（2026-10-17 以 `queryAllSteps` 校准）：
 * 创建 → 排期 → 受理 → 执行 → PM 经理审批 → FLM 领导审批。
 * ⚠️ `pm_caliber.STEP_COLUMNS` 的键仍按字段声明顺序，漏斗用 `STEP_KEYS` 重排，
 * 不要按字段名字母序排（`last_process_time` 早于 PM 经理审批时间）。
 */
export const STEP_KEYS: { step: string; labelKey: string }[] = [
  { step: 'created', labelKey: 'pm.step.created' },
  { step: 'scheduled', labelKey: 'pm.step.scheduled' },
  { step: 'accepted', labelKey: 'pm.step.accepted' },
  { step: 'processed', labelKey: 'pm.step.processed' },
  { step: 'pm_approved', labelKey: 'pm.step.pmApproved' },
  { step: 'flm_approved', labelKey: 'pm.step.flmApproved' },
]

/**
 * 汇总随计划过滤一起变化 —— 表格小计与 KPI 必须来自同一份行数据。
 * 比率一律由分子分母现算，**不用**后端 summary（那份是未过滤的）。
 */
export function summarize(rows: PlanRow[]): Overview['summary'] {
  const out = {
    total: 0, closed: 0, open: 0, overdue: 0, on_time: 0,
    not_started: 0, closed_overdue: 0, open_overdue: 0, open_on_time: 0,
    completed_items: 0, total_items: 0, plans: rows.length,
    closure_rate: null as number | null,
    overdue_rate: null as number | null,
    start_rate: null as number | null,
  }
  for (const r of rows) {
    for (const k of COUNT_FIELDS) out[k] += r[k]
    out.completed_items += r.completed_items
    out.total_items += r.total_items
  }
  const rate = (n: number, d: number) => (d ? Math.round((n / d) * 1000) / 10 : null)
  out.closure_rate = rate(out.closed, out.total)
  out.overdue_rate = rate(out.overdue, out.total)
  out.start_rate = rate(out.total - out.not_started, out.total)
  return out
}
