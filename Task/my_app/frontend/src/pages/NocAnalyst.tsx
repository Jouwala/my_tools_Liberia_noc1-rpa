/**
 * NOC 操作人分析页面 —— 参考 FmeRanking.tsx 的整体结构（概览 + 排名 + 下钻）。
 *
 * 数据来源（后端，全部只读）：
 *   - GET /api/eflow-qa/_tt_postmortem_noc           概览（按 alarm_occur_time 归属月份）
 *   - GET /api/eflow-qa/_tt_postmortem_noc_tt        NOC → TT 明细（切片）
 *   - GET /api/eflow-qa/_tt_postmortem_noc_sites     NOC → 异常站点聚合
 *   - GET /api/eflow-qa/_tt_postmortem_tt_detail     单 TT → 告警链路 + 根因一致性审计
 *   - GET /api/eflow-qa/_tt_postmortem_timeline/{t}  单 TT → 里程碑时间轴 + 偏离 + 时间归因
 *   - GET /api/eflow-qa/_tt_postmortem_noc_timeline  本月时间轴批量聚合（时间都花哪了）
 *
 * 「能下钻尽下钻」原则（2026-09-23 增强）—— 页面上每一个数字都可点：
 *   第 1 层  概览数字卡 / Top3·Bottom3 卡片 / ECharts 柱状图 / 排名表每一列 → 对应切片明细
 *   第 2 层  NOC 明细弹窗（Tab：TT 明细 / 异常站点），可切换 5 种切片
 *   第 3 层  站点行点击 → 该站点的 TT（弹窗内二次下钻）
 *   第 4 层  TT 行点击 → 单 TT 复盘报告（时间归因 + 里程碑时间轴 + 应做/实做 + 偏离 + 告警链路）
 *
 * 内容口径参考「TT 复盘报告生成（程序化版）」（backend/services/tt_postmortem）：
 *   本页的时间归因/里程碑/偏离/未派 WO 全部由 build_tt_timeline 逐单解析得出，
 *   与单张 TT 的复盘报告**同源同口径**，不另立一套结论。
 *
 * 口径：与后端一致，按 alarm_occur_time（告警发生时间）归属月份；
 *      夜班 = Accept 操作时间落在 22:00–06:00。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ReloadOutlined,
  SearchOutlined,
  WarningOutlined,
  FireOutlined,
  ClockCircleOutlined,
  SafetyOutlined,
  TrophyOutlined,
  DownloadOutlined,
  RightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
  FieldTimeOutlined,
  NodeIndexOutlined,
  ThunderboltOutlined,
  PieChartOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'

import {
  getNocAnalystReport, getNocTtDrilldown, getNocSiteDrilldown, getNocTtDetail,
  getTtTimeline, getNocTimelineAgg,
} from '../api'
import { useI18n, numLocale } from '../i18n'
import DraggableClickModal from '../components/DraggableClickModal'
import { CardBase, StatCard } from '../components/cards'
import { exportAoaReport } from '../utils/excelReport'
import { useTheme, WH, darkTooltip, axisLabel, axisLine, splitLine, pageWrap } from '../theme'

const { Text, Title } = Typography

type TtSample = {
  tt_no: string
  site_name?: string
  ticket_severity?: string
  root_cause?: string
  alarm_reason_type?: string
  sla_status?: string
}

type NocRow = {
  noc_name: string
  group: string
  total: number
  with_root_cause: number
  mismatch_count: number
  mismatch_power_trm: number
  mismatch_other: number
  mismatch_pct: number | null
  avg_duration_h: number | null
  night_total: number
  night_pct: number | null
  sla_pass: number
  sla_fail: number
  sla_total: number
  sla_pass_rate_pct: number | null
  sla_fail_pct: number | null
  tt_sample: TtSample[]
}

type Report = {
  meta: {
    month: string
    limit: number
    noc_filter?: string
    scanned: number
    time_field?: string
    night_window?: string
    generated_at: string
  }
  summary: {
    noc_count: number
    total_handled: number
    avg_mismatch_pct: number | null
    avg_duration_h: number | null
    overall_sla_pass_rate_pct: number | null
  }
  rows: NocRow[]
  red_flags: Array<{ noc_name: string; reasons: string[]; total: number; mismatch_pct: number | null }>
}

/* ==================== 里程碑时间轴聚合（复盘报告口径）==================== */

/** 一组秒数的统计块 */
type StatBlock = {
  count: number
  avg_s: number | null
  p50_s: number | null
  p90_s: number | null
  max_s: number | null
}

/** 里程碑一跳（stage_stats / timeline 共用语义） */
type StageStat = StatBlock & {
  key: string
  label: string
  actor: string
  expected: boolean
  threshold_s: number | null
}

/** 时间归因分段：时间花在谁手里 */
type SegmentStat = StatBlock & {
  key: string
  label: string
  sum_s: number
  pct: number | null
  over_threshold_count: number
  threshold_s: number | null
}

/** 阶段归并（NOC 手里 / 现场 / 系统 各占多久） */
type PhaseStat = StatBlock & {
  phase: string
  phase_label: string
  sum_s: number
  pct: number | null
}

/** WO 生命周期某两跳之间的间隔分布 */
type WoGapStat = StatBlock & {
  key: string
  label: string
  sum_s: number
}

/** 人工动作等待时长分布（NOC 及时性） */
type HumanActionStat = StatBlock & {
  key: string
  label: string
  threshold_s: number | null
  over_threshold_count: number
  over_threshold_pct: number
}

type DeviationStat = {
  code: string
  kind?: string
  severity?: string
  label?: string
  count: number
  sample_tts: string[]
}

type MissingStat = {
  key: string
  label?: string
  actor?: string
  count: number
  sample_tts: string[]
}

/** 应派未派的 WO 明细行 */
type NoWoRow = {
  tt_no: string
  noc_name: string
  site_name?: string
  site_id?: string
  alarm_code?: string
  ticket_severity?: string
  alarm_occur_time?: string
  alarm_clear_time?: string
  total_seconds?: number
  filed_root_cause?: string
  dispatch_category?: string
  bottleneck?: string
  bottleneck_seconds?: number
}

type NocAggRow = {
  noc_name: string
  total: number
  avg_total_seconds: number | null
  deviation_count: number
  critical_count: number
  no_wo_count: number
  missing_count: number
  worst_segment: string | null
  worst_segment_s: number
  avg_deviation: number | null
}

/** 逐单精简结果（可再下钻到单 TT 复盘） */
type TicketAggRow = {
  tt_no: string
  noc_name: string
  site_name?: string
  ticket_severity?: string
  alarm_occur_time?: string
  total_seconds?: number
  done_count?: number
  stage_count?: number
  missing_count: number
  deviation_count: number
  max_severity?: string | null
  has_wo: boolean
  should_wo: boolean
  bottleneck?: string
  bottleneck_seconds?: number
  bottleneck_owner?: string
  over_threshold_count?: number
}

type TimelineAgg = {
  meta: {
    month: string
    scanned: number
    parsed: number
    parse_failed: number
    total_in_month: number
    truncated: boolean
    limit: number
    stage_count: number
    expected_stage_count: number
    thresholds: Record<string, string>
    elapsed_s: number
    cache_hit: boolean
    generated_at: string
    note?: string
  }
  stage_stats: StageStat[]
  segment_stats: SegmentStat[]
  bottleneck_rank: SegmentStat[]
  deviation_stats: DeviationStat[]
  missing_stats: MissingStat[]
  wo_stats: {
    dispatched: number
    should_dispatch: number
    missing_dispatch: number
    dispatch_rate_pct: number | null
  }
  no_wo_tickets: NoWoRow[]
  noc_stats: NocAggRow[]
  tickets: TicketAggRow[]
  /** 现场处置及时性：WO 各跳间隔分布 */
  wo_gap_stats?: WoGapStat[]
  wo_stage_stats?: StageStat[]
  wo_with_timeline?: number
  /** NOC 人工动作及时性 */
  human_action_stats?: HumanActionStat[]
  /** 阶段归并（NOC 手里 / 现场 / 系统） */
  phase_stats?: PhaseStat[]
}

/** 单 TT 的里程碑节点（build_tt_timeline.timeline）
 *  注意：节点**没有** operator / gap_from_prev_s 字段（实测），操作人写在 detail 文本里；
 *  间隔要自己按上一跳时间算，见 tlMilestoneColumns 的 gap 计算。 */
type TimelineNode = {
  key: string
  label: string
  actor: string
  time: string | null
  time_present: boolean
  source?: string
  raw?: string
  detail?: string
  server_time?: string
}

/** 单 TT 时间归因分段
 *  2026-09-23 后端改为**事件驱动分段**：端点就是真实事件，不再是固定 4 段，
 *  因此多出 phase / phase_label（阶段归并），且**不再有 sub_segments**。 */
type TtSegment = {
  key: string
  /** 阶段键：detect/assign/dispatch/onsite_wait/onsite_work/clear/handle/close/other */
  phase?: string
  /** 阶段短名（后端给中文，前端按 phase 走 i18n 覆盖） */
  phase_label?: string
  label: string
  owner?: string
  owner_kind?: string
  seconds: number
  pct: number | null
  from?: string | null
  to?: string | null
  threshold_s?: number | null
  over_threshold?: boolean
  over_by_s?: number | null
}

/** 单 TT 的人工动作等待（NOC 及时性） */
type HumanAction = {
  key: string
  label: string
  from?: string | null
  to?: string | null
  wait_s: number
  threshold_s: number | null
  over_threshold: boolean
  note?: string
}

/** WO 生命周期（现场处置明细） */
type WoStage = {
  key: string
  label: string
  time: string | null
  time_present: boolean
  operator: string
  source: string
  gap_from_prev_s: number | null
}

type WoTimeline = {
  wo_no: string | null
  creator?: string | null
  status?: string | null
  current_handler?: string | null
  stages: WoStage[]
  gaps: Record<string, number | null>
  travel_declared_s?: number | null
  travel_mismatch?: boolean
  summary?: string | null
  desync?: string | null
  stage_present_count: number
}

/** 单 TT 的复盘报告（build_tt_timeline 原生结构） */
type TtTimelineReport = {
  tt_no: string
  found: boolean
  timeline: TimelineNode[]
  expected_actions: Array<{
    key: string; label: string; actor: string; required: boolean
    done: boolean; time?: string | null; operator?: string | null; detail?: string
  }>
  missing_actions: Array<{ key: string; label: string; actor: string; reason?: string }>
  deviations: Array<{
    code: string; kind: string; severity: string; label: string
    expected?: string; actual?: string; impact?: string
  }>
  time_spent: {
    total_seconds: number | null
    segments: TtSegment[]
    segments_sum_s: number
    unaccounted_s: number | null
    unaccounted_note?: string | null
    bottleneck?: TtSegment | null
    bottleneck_note?: string | null
    over_threshold_count?: number
    /** 人工动作等待（NOC 及时性） */
    human_actions?: HumanAction[]
    human_over_threshold_count?: number
  }
  /** WO 生命周期（现场处置）；无 WO 时为 null */
  wo_timeline?: WoTimeline | null
  sla?: Record<string, unknown>
  people?: Record<string, unknown>
  meta: {
    window?: { start?: string; end?: string }
    total_seconds?: number | null
    stage_count: number
    done_count: number
    expected_count: number
    missing_count: number
    deviation_count: number
    max_severity?: string | null
    thresholds?: Record<string, string>
    note?: string
  }
  site?: Record<string, unknown>
  ticket?: Record<string, unknown>
  /** 站点历史告警（后端 site_history，前端暂未展开） */
  site_history?: unknown[]
  /** 派单分析（后端 dispatch_analysis；WO 号在 dispatch_path.wo_no，不在 wo 块） */
  dispatch_analysis?: Record<string, unknown>
  /** 各段耗时明细（后端 durations） */
  durations?: Record<string, unknown>
  dispatch_path?: Record<string, unknown>
}

/** 下钻切片：与后端 build_noc_tt_drilldown 的 slice_ 参数一一对应 */
type Slice = 'all' | 'mismatch' | 'night' | 'sla_fail' | 'slow'

type TtDrillRow = {
  tt_no: string
  site_id?: string
  site_name?: string
  ticket_severity?: string
  alarm_code?: string
  alarm_occur_time?: string
  maintain_duration_h: number | null
  root_cause?: string
  sub_root_cause?: string
  system_reason_type?: string | null
  mismatch_type?: string | null
  accept_time?: string | null
  is_night: boolean
  sla_status?: string | null
  status?: string
}

type SiteDrillRow = {
  site_id?: string
  site_name?: string
  total: number
  mismatch_count: number
  sla_fail: number
  slow_count: number
  night_count: number
  avg_duration_h: number | null
  top_root_cause?: string
  last_occur?: string
  abnormal: boolean
}

type TtDetail = {
  tt_no: string
  found: boolean
  noc?: string
  site: { site_id?: string; site_name?: string }
  ticket: {
    ticket_severity?: string
    alarm_severity?: string
    alarm_code?: string
    status?: string
    sla_status?: string
    alarm_occur_time?: string
    alarm_clear_time?: string
    accept_time?: string | null
    is_night?: boolean
    maintain_duration_h?: number | null
    durations?: Record<string, number | null>
  }
  noc_filled: {
    root_cause?: string
    sub_root_cause?: string
    root_cause_description?: string
    filed_by?: string
    filed_at?: string
  }
  system_judged?: {
    fault_domain?: string
    basis?: string
    alarmcode?: string
    codename?: string
    reason_type?: string
    linkage?: string
    alarm_count?: number
    distinct_codes?: string[]
    distinct_names?: string[]
  } | null
  alarm_chain: Array<{
    alarmcode?: string
    codename?: string
    reason_type?: string
    alarm_source?: string
    fault_domain?: string
    basis?: string
    family?: string
  }>
  consistency: boolean | null
  mismatch_type?: string
  confidence?: string
  note?: string
}

const fmtPct = (v: number | null | undefined, digits = 1) =>
  v == null ? '-' : `${v.toFixed(digits)}%`

/**
 * 动态拼接的 i18n 键 —— 必须逐个写出 t() 调用，不能拼接字符串。
 * 原因：scripts/check-i18n.mjs 用正则静态扫描 t('...')，`t('noc.slice.' + s)`
 * 会被它当成键名 `noc.slice.` 而报「字典缺失」。写成映射表后：
 *   ① 守卫能正确校验每个键；② 键名与后端 slice 取值一一对应，漏一个立刻暴露。
 */
const SLICE_LABEL: Record<string, () => string> = {
  ...({} as Record<string, () => string>),
}
/** 切片 → 文案键（用 t 的显式调用，便于静态检查） */
const sliceLabelKey = (s: Slice): string => {
  switch (s) {
    case 'mismatch': return 'noc.slice.mismatch'
    case 'night': return 'noc.slice.night'
    case 'sla_fail': return 'noc.slice.sla_fail'
    case 'slow': return 'noc.slice.slow'
    default: return 'noc.slice.all'
  }
}
/** 告警链路关联方式 → 文案键（同样显式列出） */
const linkageLabelKey = (linkage?: string): string => {
  switch (linkage) {
    case 'exact': return 'noc.linkage.exact'
    case 'site_fallback': return 'noc.linkage.site_fallback'
    case 'site_reason_fallback': return 'noc.linkage.site_reason_fallback'
    case 'site_fallback_unrelated': return 'noc.linkage.site_fallback_unrelated'
    default: return 'noc.linkage.none'
  }
}

/** 秒 → 可读时长 */
const fmtSec = (v: number | null | undefined) => {
  if (v == null) return '-'
  if (v < 60) return `${v}s`
  if (v < 3600) return `${(v / 60).toFixed(1)}m`
  return `${(v / 3600).toFixed(1)}h`
}

/**
 * 里程碑时间轴上第 i 跳距"上一个有时间戳的节点"的秒数。
 * 后端 build_tt_timeline 的节点里没有 gap 字段（实测键为
 * key/label/actor/time/time_present/source/raw/detail/server_time），
 * 缺失节点也没有时间戳，所以必须在这里按时间戳现场算，否则整列都是空。
 */
const nodeGapSeconds = (nodes: TimelineNode[], i: number): number | null => {
  const cur = nodes[i]
  if (!cur?.time_present || !cur.time) return null
  for (let j = i - 1; j >= 0; j--) {
    const prev = nodes[j]
    if (prev?.time_present && prev.time) {
      const a = dayjs(prev.time)
      const b = dayjs(cur.time)
      if (!a.isValid() || !b.isValid()) return null
      return b.diff(a, 'second')
    }
  }
  return null
}

/* ---- 偏离严重度 / 类型的显式 i18n 键映射 ----
 * 必须显式 switch 返回字面量键：动态拼 `t('noc.sev.' + x)` 会被
 * scripts/check-i18n.mjs 静态扫描读成键名 `noc.sev.`，误报"字典缺失"。 */
type Sev = 'critical' | 'major' | 'minor'

const sevKey = (s?: string): string => {
  switch (s) {
    case 'critical': return 'noc.sevCritical'
    case 'major': return 'noc.sevMajor'
    case 'minor': return 'noc.sevMinor'
    default: return 'noc.sevMinor'
  }
}
/** 严重度排序权重：数值越小越严重 */
const sevRank = (s?: string): number => {
  switch (s) {
    case 'critical': return 0
    case 'major': return 1
    case 'minor': return 2
    default: return 3
  }
}
const sevColor = (s?: string): string => {
  switch (s) {
    case 'critical': return 'red'
    case 'major': return 'orange'
    case 'minor': return 'gold'
    default: return 'default'
  }
}

type DevKind = 'missing' | 'late' | 'out_of_order' | 'data_conflict'

const devKindKey = (k?: string): string => {
  switch (k) {
    case 'missing': return 'noc.kindMissing'
    case 'late': return 'noc.kindLate'
    case 'out_of_order': return 'noc.kindOutOfOrder'
    case 'data_conflict': return 'noc.kindDataConflict'
    default: return 'noc.kindMissing'
  }
}
// DevKind 仅用于类型约束，避免上面 switch 的分支被误删
const _DEV_KINDS: DevKind[] = ['missing', 'late', 'out_of_order', 'data_conflict']
void _DEV_KINDS
const _SEVS: Sev[] = ['critical', 'major', 'minor']
void _SEVS

/**
 * 下钻响应校验（2026-09-23 新增，防"静默空表"）。
 *
 * 背景：生产后端未重启、仍跑旧代码时，新加的下钻路由不存在，
 * 后端的 SPA 兜底会把 index.html 以 **HTTP 200 + text/html** 返回。
 * axios 不会把它当错误，`data.rows` 于是是 undefined —— 界面只显示
 * "暂无数据"，看起来像"这个切片本来就没数据"，极难排查（实测踩过）。
 *
 * 因此这里显式识别"响应不是下钻 JSON"，抛出可读错误。
 */
type TFunc = (key: string, params?: Record<string, string | number>) => string

/** 下钻响应的 meta：各端点字段不完全一致，故用可选宽松结构 */
type DrillMeta = {
  matched?: number
  noc_total_in_month?: number
  site_count?: number
  truncated?: boolean
  [k: string]: unknown
}

/**
 * 校验下钻响应形状，并把类型收敛为 { rows: T[]; meta?: DrillMeta }。
 * 泛型 T 保留调用方原有的行类型，避免断言把 rows 变成 unknown[]。
 */
function assertDrillPayload<T>(
  data: unknown, what: string, t: TFunc,
): asserts data is { rows: T[]; meta?: DrillMeta } {
  const d = data as Record<string, unknown> | null
  if (!d || typeof d !== 'object' || !Array.isArray(d.rows)) {
    // 后端返回 HTML（路由不存在 / 被 SPA 兜底）或结构不符
    throw new Error(t('noc.drillBadPayload', { what }))
  }
}

export default function NocAnalyst() {
  const { t, locale } = useI18n()
  const { isDark, palette } = useTheme()
  const nf = useMemo(() => numLocale(locale), [locale])

  const [month, setMonth] = useState<string>(dayjs().format('YYYY-MM'))
  const [nocFilter, setNocFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Report | null>(null)
  const [error, setError] = useState<string>('')

  // ========== 下钻状态 ==========
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  const [drillNoc, setDrillNoc] = useState('')
  const [drillNocRow, setDrillNocRow] = useState<NocRow | null>(null)
  const [drillSlice, setDrillSlice] = useState<Slice>('all')
  const [drillTab, setDrillTab] = useState<'tt' | 'site'>('tt')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState('')

  // 第 2 层：TT 明细
  const [ttRows, setTtRows] = useState<TtDrillRow[]>([])
  const [ttMeta, setTtMeta] = useState<{ matched: number; total: number; truncated?: boolean }>({ matched: 0, total: 0 })
  // 第 3 层：站点聚合
  const [siteRows, setSiteRows] = useState<SiteDrillRow[]>([])
  const [siteMeta, setSiteMeta] = useState<{ siteCount: number; truncated?: boolean }>({ siteCount: 0 })
  const [siteAll, setSiteAll] = useState(false)  // 是否显示全部站点（含无异常）
  // 站点 → 该站点 TT 的二次下钻
  const [siteDrill, setSiteDrill] = useState<{ siteName: string; rows: TtDrillRow[] } | null>(null)

  // 第 4 层：单 TT 详情
  const [ttDetailOpen, setTtDetailOpen] = useState(false)
  const [ttDetail, setTtDetail] = useState<TtDetail | null>(null)
  const [ttDetailLoading, setTtDetailLoading] = useState(false)

  // ========== 里程碑时间轴聚合（“时间都花哪了”，复盘报告口径）==========
  // 与概览并行加载；首次后端要逐单解析约 2300 张单（~150s），之后走磁盘缓存毫秒级。
  const [agg, setAgg] = useState<TimelineAgg | null>(null)
  const [aggLoading, setAggLoading] = useState(false)
  const [aggError, setAggError] = useState('')
  // 逐单清单弹窗（卡片点击入口：看全部纳入复盘的单子）
  const [aggDetailOpen, setAggDetailOpen] = useState(false)

  // 第 4 层（复盘视图）：单 TT 的里程碑时间轴 + 应做/实做 + 偏离 + 时间归因
  const [tlOpen, setTlOpen] = useState(false)
  const [tlReport, setTlReport] = useState<TtTimelineReport | null>(null)
  const [tlLoading, setTlLoading] = useState(false)
  const [tlError, setTlError] = useState('')
  const [tlTab, setTlTab] = useState<'time' | 'milestone' | 'actions' | 'deviation' | 'chain'>('time')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { month, limit: 10000 }
      if (nocFilter.trim()) params.noc = nocFilter.trim()
      const r = await getNocAnalystReport(params)
      setData(r.data as Report)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || t('noc.noData'))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [month, nocFilter, t])

  useEffect(() => { load() }, [load])

  /**
   * 加载本月的时间轴聚合（“时间都花哪了”）。
   * 独立于概览：首次可能较慢（后端要逐单复盘全月工单），失败也不应拖垮整页，
   * 因此单独 try/catch 并把错误放在自己的告警条里。
   */
  const loadAgg = useCallback(async (refresh = false) => {
    setAggLoading(true)
    setAggError('')
    try {
      const r = await getNocTimelineAgg({ month, limit: 20000, refresh })
      const d = r.data as TimelineAgg
      if (!d || !Array.isArray(d.tickets)) {
        throw new Error(t('noc.drillBadPayload', { what: t('noc.aggTitle') }))
      }
      setAgg(d)
    } catch (e: any) {
      setAggError(e?.response?.data?.detail || e?.message || t('noc.aggLoadFailed'))
      setAgg(null)
    } finally {
      setAggLoading(false)
    }
  }, [month, t])

  useEffect(() => { loadAgg() }, [loadAgg])

  const monthOptions = useMemo(() => {
    const arr: string[] = []
    for (let i = 0; i < 6; i++) arr.push(dayjs().subtract(i, 'month').format('YYYY-MM'))
    return arr
  }, [])

  // ========== 第 1 层：下钻入口统一收口 ==========
  /** 打开某个 NOC 的下钻弹窗；slice 决定看哪一片，tab 决定落在哪个页签 */
  const openNocDrill = useCallback((
    trigger: any,
    row: NocRow,
    slice: Slice = 'all',
    tab: 'tt' | 'site' = 'tt',
  ) => {
    let anchor: { x: number; y: number } | null = null
    if (trigger && typeof trigger.clientX === 'number') anchor = { x: trigger.clientX, y: trigger.clientY }
    else if (trigger?.event?.event && typeof trigger.event.event.clientX === 'number') {
      anchor = { x: trigger.event.event.clientX, y: trigger.event.event.clientY }
    }
    setDrillAnchor(anchor)
    setDrillOpen(true)
    setDrillNoc(row.noc_name)
    setDrillNocRow(row)
    setDrillSlice(slice)
    setDrillTab(tab)
    setDrillSearch('')
    setDrillError('')
    setSiteDrill(null)
    setSiteAll(false)
    setTtRows([]); setSiteRows([])
    setDrillLoading(true)

    Promise.all([
      getNocTtDrilldown({ noc: row.noc_name, month, slice }),
      getNocSiteDrilldown({ noc: row.noc_name, month, only_abnormal: true }),
    ]).then(([ttRes, siteRes]) => {
      assertDrillPayload<TtDrillRow>(ttRes.data, t('noc.drillTabTt'), t)
      assertDrillPayload<SiteDrillRow>(siteRes.data, t('noc.drillTabSite'), t)
      const tm = ttRes.data?.meta || {}
      setTtRows(ttRes.data?.rows || [])
      setTtMeta({ matched: tm.matched || 0, total: tm.noc_total_in_month || 0, truncated: tm.truncated })
      const sm = siteRes.data?.meta || {}
      setSiteRows(siteRes.data?.rows || [])
      setSiteMeta({ siteCount: sm.site_count || 0, truncated: sm.truncated })
    }).catch(err => {
      console.error('NOC drilldown error:', err)
      setDrillError(err?.response?.data?.detail || err?.message || t('noc.drillLoadFailed'))
    }).finally(() => setDrillLoading(false))
  }, [month, t])

  /** 切换切片时只重查 TT 明细，站点数据不动 */
  const changeSlice = useCallback((slice: Slice) => {
    setDrillSlice(slice)
    setSiteDrill(null)
    setDrillLoading(true)
    setDrillError('')
    getNocTtDrilldown({ noc: drillNoc, month, slice })
      .then(res => {
        assertDrillPayload<TtDrillRow>(res.data, t('noc.drillTabTt'), t)
        const tm = res.data?.meta || {}
        setTtRows(res.data?.rows || [])
        setTtMeta({ matched: tm.matched || 0, total: tm.noc_total_in_month || 0, truncated: tm.truncated })
      })
      .catch(err => setDrillError(err?.response?.data?.detail || err?.message || t('noc.drillLoadFailed')))
      .finally(() => setDrillLoading(false))
  }, [drillNoc, month, t])

  /** 站点显示范围切换（仅异常 / 全部） */
  const toggleSiteScope = useCallback((all: boolean) => {
    if (!drillNoc) return
    setSiteAll(all)
    setDrillLoading(true)
    getNocSiteDrilldown({ noc: drillNoc, month, only_abnormal: !all })
      .then(res => {
        assertDrillPayload<SiteDrillRow>(res.data, t('noc.drillTabSite'), t)
        const sm = res.data?.meta || {}
        setSiteRows(res.data?.rows || [])
        setSiteMeta({ siteCount: sm.site_count || 0, truncated: sm.truncated })
      })
      .catch(err => setDrillError(err?.response?.data?.detail || err?.message || t('noc.drillLoadFailed')))
      .finally(() => setDrillLoading(false))
  }, [drillNoc, month, t])

  // ========== 第 3 层：站点 → 该站点 TT ==========
  const openSiteTts = useCallback((site: SiteDrillRow) => {
    // 拉该 NOC 的全量 TT 后在本地按站点过滤，避免新增一个接口
    setDrillLoading(true)
    getNocTtDrilldown({ noc: drillNoc, month, slice: 'all' })
      .then(res => {
        assertDrillPayload<TtDrillRow>(res.data, t('noc.drillTabTt'), t)
        const sid = String(site.site_id ?? '').trim()
        const sname = String(site.site_name ?? '').trim().toLowerCase()
        const matched = (res.data?.rows || []).filter((r: TtDrillRow) =>
          (sid && String(r.site_id ?? '').trim() === sid) ||
          (!sid && String(r.site_name ?? '').trim().toLowerCase() === sname))
        setSiteDrill({ siteName: String(site.site_name ?? site.site_id ?? ''), rows: matched })
      })
      .catch(err => setDrillError(err?.response?.data?.detail || err?.message || t('noc.drillLoadFailed')))
      .finally(() => setDrillLoading(false))
  }, [drillNoc, month, t])

  // ========== 第 4 层：单 TT 详情 ==========
  const openTtDetail = useCallback((ttNo: string) => {
    setTtDetailOpen(true)
    setTtDetailLoading(true)
    setTtDetail(null)
    getNocTtDetail({ tt_no: ttNo, noc: drillNoc })
      .then(res => setTtDetail(res.data as TtDetail))
      .catch(err => {
        console.error('TT detail error:', err)
        setTtDetail(null)
      })
      .finally(() => setTtDetailLoading(false))
  }, [drillNoc])

  /**
   * 第 4 层（复盘报告视图）：打开单张 TT 的「里程碑时间轴 + 应做/实做 + 偏离 + 时间归因」。
   * 与 openTtDetail（根因一致性）互补：那个回答“根因填得对不对”，
   * 这个回答“时间花在哪个动作上、该做的动作有没有做”。
   */
  const openTtTimeline = useCallback((ttNo: string, tab: typeof tlTab = 'time') => {
    setTlOpen(true)
    setTlTab(tab)
    setTlLoading(true)
    setTlReport(null)
    setTlError('')
    getTtTimeline(ttNo)
      .then(res => {
        const d = res.data as TtTimelineReport
        if (!d || !Array.isArray(d.timeline)) {
          throw new Error(t('noc.drillBadPayload', { what: t('noc.tlTitle') }))
        }
        setTlReport(d)
      })
      .catch(err => {
        console.error('TT timeline error:', err)
        setTlError(err?.response?.data?.detail || err?.message || t('noc.tlLoadFailed'))
      })
      .finally(() => setTlLoading(false))
  }, [t])

  /** 从聚合的“应派未派”清单点进来：直接落在偏离页签，方便看判定依据 */
  const openNoWoDetail = useCallback((ttNo: string) => {
    openTtTimeline(ttNo, 'deviation')
  }, [openTtTimeline])

  // ========== 模糊过滤 ==========
  const filterRows = useCallback(<T extends object>(list: T[]) => {
    if (!drillSearch.trim()) return list
    const lower = drillSearch.toLowerCase()
    return list.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower)))
  }, [drillSearch])

  const visibleTtRows = useMemo(
    () => siteDrill ? filterRows(siteDrill.rows) : filterRows(ttRows),
    [siteDrill, ttRows, filterRows],
  )
  const visibleSiteRows = useMemo(() => filterRows(siteRows), [siteRows, filterRows])

  // ========== Top3 / Bottom3 ==========
  // 错位率：只对"有填报根因"的人排名，避免 0/0 的人霸榜
  const mismatchRanked = useMemo(
    () => (data?.rows || []).filter(r => r.with_root_cause > 0 && r.mismatch_pct != null)
      .slice().sort((a, b) => (b.mismatch_pct as number) - (a.mismatch_pct as number) || b.mismatch_count - a.mismatch_count),
    [data])
  // SLA：只对"有 SLA 样本"的人排名
  const slaRanked = useMemo(
    () => (data?.rows || []).filter(r => r.sla_total > 0 && r.sla_pass_rate_pct != null)
      .slice().sort((a, b) => (a.sla_pass_rate_pct as number) - (b.sla_pass_rate_pct as number) || b.sla_total - a.sla_total),
    [data])
  const topMismatch = useMemo(() => mismatchRanked.slice(0, 3), [mismatchRanked])
  const bottomSla = useMemo(() => slaRanked.slice(0, 3), [slaRanked])

  // ========== 时间归因（“时间都花哪了”）派生值 ==========
  /** 全月平均总历时（秒）：用各分段合计估算，避免再取一次 meta */
  const aggAvgTotalS = useMemo(() => {
    const tks = agg?.tickets || []
    const vals = tks.map(x => x.total_seconds).filter((v): v is number => typeof v === 'number' && v >= 0)
    if (!vals.length) return null
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
  }, [agg])

  /** 最大瓶颈环节（占时最长的那一段） */
  const aggTopSegment = useMemo(() => agg?.segment_stats?.[0] || null, [agg])

  // 注意：wo_stats.should_dispatch 与 missing_dispatch 由同一条判定（偏离 4）构造，
  // 二者恒等，"未派占比"必然恒为 100%，没有展示价值；
  // 对外只用 dispatch_rate_pct（派单覆盖率）= dispatched / 全月单量。

  /** 超阈值分段总数 */
  const overThrTotal = useMemo(
    () => (agg?.segment_stats || []).reduce((a, s) => a + (s.over_threshold_count || 0), 0),
    [agg],
  )

  /** 各环节占时比例（环形图）：用 sum_s 而非均值，回答“时间总量花在哪” */
  const segChartOption = useMemo(() => {
    const segs = (agg?.segment_stats || []).filter(s => (s.sum_s || 0) > 0)
    if (!segs.length) return null
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'item',
        formatter: (p: any) =>
          `${p.name}<br/>${t('noc.segSum')}: <strong>${fmtSec(p.value)}</strong><br/>`
          + `${t('noc.chartPct')}: <strong>${p.percent}%</strong>`,
      },
      legend: {
        orient: 'vertical', right: 6, top: 'middle',
        textStyle: { color: isDark ? '#c9d4e3' : '#33475b', fontSize: 11 },
      },
      series: [{
        type: 'pie', radius: ['42%', '68%'], center: ['34%', '50%'],
        avoidLabelOverlap: true,
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } },
        data: segs.map(s => ({ name: s.label, value: s.sum_s })),
      }],
    }
  }, [agg, isDark, t])

  /** 偏离类型分布（按 kind 汇总的横向柱状图） */
  const devChartOption = useMemo(() => {
    const stats = agg?.deviation_stats || []
    if (!stats.length) return null
    const byKind = new Map<string, number>()
    for (const d of stats) {
      const k = d.kind || 'other'
      byKind.set(k, (byKind.get(k) || 0) + d.count)
    }
    const entries = [...byKind.entries()].sort((a, b) => a[1] - b[1])
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 96, right: 40, top: 12, bottom: 26 },
      xAxis: { type: 'value', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
      yAxis: {
        type: 'category',
        data: entries.map(([k]) => t(devKindKey(k))),
        axisLabel: axisLabel(isDark),
        axisLine: axisLine(isDark),
      },
      series: [{
        type: 'bar', barWidth: '52%',
        // ECharts 是 canvas，解析不了 CSS 变量，必须用 palette 实值
        itemStyle: { color: palette.sev.Critical, borderRadius: [0, 4, 4, 0] },
        data: entries.map(([, v]) => v),
        label: { show: true, position: 'right', color: WH.text, fontSize: 11 },
      }],
    }
  }, [agg, isDark, t, palette])

  /** 分段表 */
  const segColumns = useMemo(() => [
    {
      title: t('noc.segName'), dataIndex: 'label', key: 'label',
      render: (v: string, r: SegmentStat) => (
        <Space size={6}>
          <span style={{ color: WH.text }}>{v}</span>
          {r.pct != null && <Tag color="blue">{r.pct}%</Tag>}
        </Space>
      ),
    },
    {
      title: t('noc.segSum'), dataIndex: 'sum_s', key: 'sum_s', align: 'right' as const,
      sorter: (a: SegmentStat, b: SegmentStat) => (a.sum_s || 0) - (b.sum_s || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number) => <Text strong>{fmtSec(v)}</Text>,
    },
    {
      title: t('noc.segAvg'), dataIndex: 'avg_s', key: 'avg_s', align: 'right' as const,
      sorter: (a: SegmentStat, b: SegmentStat) => (a.avg_s || 0) - (b.avg_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.segP90'), dataIndex: 'p90_s', key: 'p90_s', align: 'right' as const,
      sorter: (a: SegmentStat, b: SegmentStat) => (a.p90_s || 0) - (b.p90_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.segMax'), dataIndex: 'max_s', key: 'max_s', align: 'right' as const,
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.segOverThr'), dataIndex: 'over_threshold_count', key: 'over_threshold_count',
      align: 'right' as const,
      sorter: (a: SegmentStat, b: SegmentStat) =>
        (a.over_threshold_count || 0) - (b.over_threshold_count || 0),
      render: (v: number, r: SegmentStat) => (
        v > 0
          ? <Tag color="red">{v} / {r.count}</Tag>
          : <Text type="secondary">-</Text>
      ),
    },
  ], [t])

  /** 里程碑表 */
  const stageColumns = useMemo(() => [
    {
      title: t('noc.stageLabel'), dataIndex: 'label', key: 'label',
      render: (v: string, r: StageStat) => (
        <Space size={6}>
          <span style={{ color: WH.text }}>{v}</span>
          <Tag color={r.expected ? 'geekblue' : 'default'}>
            {r.expected ? t('noc.stageRequired') : t('noc.stageConditional')}
          </Tag>
        </Space>
      ),
    },
    {
      title: t('noc.stageActor'), dataIndex: 'actor', key: 'actor', width: 90,
      render: (v: string) => (v === 'system' ? t('noc.stageActorSystem') : t('noc.stageActorHuman')),
    },
    {
      title: t('noc.segCount'), dataIndex: 'count', key: 'count', align: 'right' as const,
      sorter: (a: StageStat, b: StageStat) => a.count - b.count,
    },
    {
      title: t('noc.segP50'), dataIndex: 'p50_s', key: 'p50_s', align: 'right' as const,
      sorter: (a: StageStat, b: StageStat) => (a.p50_s || 0) - (b.p50_s || 0),
      render: (v: number | null, r: StageStat) => {
        // 超过契约时限的常态（P50 就超）用红色标出，这是最该治的
        const over = v != null && r.threshold_s != null && v > r.threshold_s
        return <Text style={{ color: over ? WH.danger : undefined }}>{fmtSec(v)}</Text>
      },
    },
    {
      title: t('noc.segP90'), dataIndex: 'p90_s', key: 'p90_s', align: 'right' as const,
      sorter: (a: StageStat, b: StageStat) => (a.p90_s || 0) - (b.p90_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.segMax'), dataIndex: 'max_s', key: 'max_s', align: 'right' as const,
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.stageThreshold'), dataIndex: 'threshold_s', key: 'threshold_s', align: 'right' as const,
      render: (v: number | null) => (v != null ? fmtSec(v) : <Text type="secondary">-</Text>),
    },
  ], [t])

  /** 偏离表：点样本单可下钻到单 TT 复盘 */
  const devColumns = useMemo(() => [
    {
      title: t('noc.devSeverity'), dataIndex: 'severity', key: 'severity', width: 90,
      sorter: (a: DeviationStat, b: DeviationStat) => sevRank(a.severity) - sevRank(b.severity),
      defaultSortOrder: 'ascend' as const,
      render: (v: string) => <Tag color={sevColor(v)}>{t(sevKey(v))}</Tag>,
    },
    {
      title: t('noc.devKind'), dataIndex: 'kind', key: 'kind', width: 100,
      render: (v: string) => <Text type="secondary">{t(devKindKey(v))}</Text>,
    },
    { title: t('noc.devLabel'), dataIndex: 'label', key: 'label', render: (v: string) => v },
    {
      title: t('noc.devCount'), dataIndex: 'count', key: 'count', align: 'right' as const, width: 90,
      sorter: (a: DeviationStat, b: DeviationStat) => a.count - b.count,
      render: (v: number) => <Text strong style={{ color: WH.danger }}>{v}</Text>,
    },
    {
      title: t('noc.devSamples'), dataIndex: 'sample_tts', key: 'sample_tts',
      render: (v: string[]) => (
        <Space size={4} wrap>
          {(v || []).map(tt => (
            <a key={tt} onClick={() => openTtTimeline(tt, 'deviation')}>{tt}</a>
          ))}
        </Space>
      ),
    },
  ], [t, openTtTimeline])

  /** 应派未派 WO 表：每行可点进单 TT 复盘 */
  const noWoColumns = useMemo(() => [
    {
      title: t('noc.woTtNo'), dataIndex: 'tt_no', key: 'tt_no',
      render: (v: string, r: NoWoRow) => (
        <Tooltip title={t('noc.woViewReport')}>
          <a onClick={() => openNoWoDetail(v)}>{v}</a>
        </Tooltip>
      ),
    },
    { title: t('noc.woSite'), dataIndex: 'site_name', key: 'site_name', render: (v: string) => v || '-' },
    {
      title: t('noc.woSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 80,
      render: (v: string) => (v ? <Tag color={v === 'P1' ? 'red' : 'orange'}>{v}</Tag> : '-'),
    },
    {
      title: t('noc.woOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 165,
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.woTotal'), dataIndex: 'total_seconds', key: 'total_seconds',
      align: 'right' as const,
      sorter: (a: NoWoRow, b: NoWoRow) => (a.total_seconds || 0) - (b.total_seconds || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number) => <Text strong style={{ color: WH.danger }}>{fmtSec(v)}</Text>,
    },
    {
      title: t('noc.woBottleneck'), dataIndex: 'bottleneck', key: 'bottleneck',
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.woCategory'), dataIndex: 'dispatch_category', key: 'dispatch_category',
      render: (v: string) => (v ? <Tag>{v}</Tag> : '-'),
    },
  ], [t, openNoWoDetail])

  /** 按 NOC 归因表：行可点开该 NOC 的下钻明细 */
  const aggNocColumns = useMemo(() => [
    {
      title: t('noc.aggNocName'), dataIndex: 'noc_name', key: 'noc_name',
      render: (v: string) => {
        const row = data?.rows.find(r => r.noc_name === v)
        return row
          ? <Tooltip title={t('noc.drillHint')}><a onClick={e => openNocDrill(e, row, 'all')}>{v}</a></Tooltip>
          : v
      },
    },
    {
      title: t('noc.aggNocTotal'), dataIndex: 'total', key: 'total', align: 'right' as const,
      sorter: (a: NocAggRow, b: NocAggRow) => a.total - b.total,
      defaultSortOrder: 'descend' as const,
    },
    {
      title: t('noc.aggNocAvg'), dataIndex: 'avg_total_seconds', key: 'avg_total_seconds',
      align: 'right' as const,
      sorter: (a: NocAggRow, b: NocAggRow) => (a.avg_total_seconds || 0) - (b.avg_total_seconds || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.aggNocNoWo'), dataIndex: 'no_wo_count', key: 'no_wo_count',
      align: 'right' as const,
      sorter: (a: NocAggRow, b: NocAggRow) => a.no_wo_count - b.no_wo_count,
      render: (v: number) => (v > 0 ? <Text strong style={{ color: WH.danger }}>{v}</Text> : '-'),
    },
    {
      title: t('noc.aggNocDev'), dataIndex: 'deviation_count', key: 'deviation_count',
      align: 'right' as const,
      sorter: (a: NocAggRow, b: NocAggRow) => a.deviation_count - b.deviation_count,
    },
    {
      title: t('noc.aggNocCritical'), dataIndex: 'critical_count', key: 'critical_count',
      align: 'right' as const,
      sorter: (a: NocAggRow, b: NocAggRow) => a.critical_count - b.critical_count,
      render: (v: number) => (v > 0 ? <Tag color="red">{v}</Tag> : '-'),
    },
    {
      title: t('noc.aggNocWorst'), dataIndex: 'worst_segment', key: 'worst_segment',
      render: (v: string | null, r: NocAggRow) =>
        v ? <Space size={4}><span>{v}</span><Text type="secondary">{fmtSec(r.worst_segment_s)}</Text></Space> : '-',
    },
  ], [t, data, openNocDrill])

  /**
   * 后端给的 `label` 是**中文硬编码**（后端不感知前端语言），
   * 直接显示会让英文界面出现中文。所以按稳定的 `key` 走 i18n，
   * 查不到才回落到后端 label（新增 key 时不至于显示空白）。
   * ⚠ 不能用 `t('noc.woGw.' + key)` 动态拼键 —— check:i18n 会拦下。
   */
  const woGapLabelKey = useCallback((key: string): string => {
    switch (key) {
      case 'accept_wait_s': return 'noc.woGwAcceptWait'
      case 'start_trip_s': return 'noc.woGwStartTrip'
      case 'travel_s': return 'noc.woGwTravel'
      case 'onsite_s': return 'noc.woGwOnsite'
      case 'close_s': return 'noc.woGwClose'
      case 'total_s': return 'noc.woGwTotal'
      default: return ''
    }
  }, [])

  const humanActLabelKey = useCallback((key: string): string => {
    switch (key) {
      case 'accept': return 'noc.actAccept'
      case 'process': return 'noc.actProcess'
      case 'onsite': return 'noc.actOnsite'
      case 'wo_accept_wait': return 'noc.actWoAccept'
      default: return ''
    }
  }, [])

  /** 取本地化标签：i18n 命中则用 i18n，否则回落后端 label */
  const locLabel = useCallback((key: string, fallback: string | undefined, k: string) => {
    return k ? t(k) : (fallback || key)
  }, [t])

  /**
   * 全月 WO 各跳耗时分布（现场处置及时性）。
   * 按后端给的业务顺序展示，不排序 —— 读的人要顺着流程看哪一跳卡住。
   */
  const woGapColumns = useMemo(() => [
    {
      title: t('noc.woGwLabel'), dataIndex: 'label', key: 'label',
      render: (v: string, r: WoGapStat) => (
        <span style={{ color: WH.text }}>{locLabel(r.key, v, woGapLabelKey(r.key))}</span>
      ),
    },
    {
      title: t('noc.woGwCount'), dataIndex: 'count', key: 'count', align: 'right' as const,
      sorter: (a: WoGapStat, b: WoGapStat) => a.count - b.count,
      render: (v: number) => v.toLocaleString(nf),
    },
    {
      title: t('noc.actAvg'), dataIndex: 'avg_s', key: 'avg_s', align: 'right' as const,
      sorter: (a: WoGapStat, b: WoGapStat) => (a.avg_s || 0) - (b.avg_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.actP50'), dataIndex: 'p50_s', key: 'p50_s', align: 'right' as const,
      sorter: (a: WoGapStat, b: WoGapStat) => (a.p50_s || 0) - (b.p50_s || 0),
      // 中位数超过 4h 的跳标红：说明"常态就很慢"，不是长尾问题
      render: (v: number | null) => (
        <Text strong style={{ color: (v || 0) >= 4 * 3600 ? WH.danger : undefined }}>{fmtSec(v)}</Text>
      ),
    },
    {
      title: t('noc.actP90'), dataIndex: 'p90_s', key: 'p90_s', align: 'right' as const,
      sorter: (a: WoGapStat, b: WoGapStat) => (a.p90_s || 0) - (b.p90_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.segMax'), dataIndex: 'max_s', key: 'max_s', align: 'right' as const,
      render: (v: number | null) => fmtSec(v),
    },
  ], [t, nf])

  /**
   * 阶段名的本地化。后端 `phase_label` 是中文硬编码，英文界面要用 i18n 覆盖。
   * ⚠ 不能用 `t('noc.phase.' + phase)` 动态拼键 —— check:i18n 会拦下。
   * ⚠ 必须定义在 phaseColumns 之前（useMemo 依赖它）。
   */
  const phaseLabelKey = useCallback((phase: string): string => {
    switch (phase) {
      case 'detect': return 'noc.phaseDetect'
      case 'assign': return 'noc.phaseAssign'
      case 'dispatch': return 'noc.phaseDispatch'
      case 'onsite_wait': return 'noc.phaseOnsiteWait'
      case 'onsite_work': return 'noc.phaseOnsiteWork'
      case 'clear': return 'noc.phaseClear'
      case 'handle': return 'noc.phaseHandle'
      case 'close': return 'noc.phaseClose'
      default: return 'noc.phaseOther'
    }
  }, [])

  /** 阶段归并表：NOC 手里 / 现场 / 系统 各占多久 */
  const phaseColumns = useMemo(() => [
    {
      title: t('noc.tlPhase'), dataIndex: 'phase', key: 'phase',
      render: (v: string, r: PhaseStat) => (
        <span style={{ color: WH.text }}>{t(phaseLabelKey(v))}</span>
      ),
    },
    {
      title: t('noc.woGwCount'), dataIndex: 'count', key: 'count', align: 'right' as const,
      sorter: (a: PhaseStat, b: PhaseStat) => a.count - b.count,
      render: (v: number) => v.toLocaleString(nf),
    },
    {
      title: t('noc.segSum'), dataIndex: 'sum_s', key: 'sum_s', align: 'right' as const,
      sorter: (a: PhaseStat, b: PhaseStat) => (a.sum_s || 0) - (b.sum_s || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.subPct'), dataIndex: 'pct', key: 'pct', align: 'right' as const,
      render: (v: number | null) => (v != null ? `${v}%` : '-'),
    },
    {
      title: t('noc.actP50'), dataIndex: 'p50_s', key: 'p50_s', align: 'right' as const,
      sorter: (a: PhaseStat, b: PhaseStat) => (a.p50_s || 0) - (b.p50_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.actP90'), dataIndex: 'p90_s', key: 'p90_s', align: 'right' as const,
      render: (v: number | null) => fmtSec(v),
    },
  ], [t, nf, phaseLabelKey])

  /** NOC / 人工动作及时性：超时限占比是关键列 */
  const humanActColumns = useMemo(() => [
    {
      title: t('noc.actName'), dataIndex: 'label', key: 'label',
      render: (v: string, r: HumanActionStat) => (
        <span style={{ color: WH.text }}>{locLabel(r.key, v, humanActLabelKey(r.key))}</span>
      ),
    },
    {
      title: t('noc.woGwCount'), dataIndex: 'count', key: 'count', align: 'right' as const,
      sorter: (a: HumanActionStat, b: HumanActionStat) => a.count - b.count,
      render: (v: number) => v.toLocaleString(nf),
    },
    {
      title: t('noc.actAvg'), dataIndex: 'avg_s', key: 'avg_s', align: 'right' as const,
      sorter: (a: HumanActionStat, b: HumanActionStat) => (a.avg_s || 0) - (b.avg_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.actP50'), dataIndex: 'p50_s', key: 'p50_s', align: 'right' as const,
      sorter: (a: HumanActionStat, b: HumanActionStat) => (a.p50_s || 0) - (b.p50_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.actP90'), dataIndex: 'p90_s', key: 'p90_s', align: 'right' as const,
      sorter: (a: HumanActionStat, b: HumanActionStat) => (a.p90_s || 0) - (b.p90_s || 0),
      render: (v: number | null) => fmtSec(v),
    },
    {
      title: t('noc.actLimit'), dataIndex: 'threshold_s', key: 'threshold_s', align: 'right' as const,
      render: (v: number | null) =>
        v != null ? fmtSec(v) : <Text type="secondary">{t('noc.actNoLimit')}</Text>,
    },
    {
      title: t('noc.actOver'), dataIndex: 'over_threshold_count', key: 'over_threshold_count',
      align: 'right' as const,
      sorter: (a: HumanActionStat, b: HumanActionStat) =>
        a.over_threshold_count - b.over_threshold_count,
      render: (v: number, r: HumanActionStat) => (
        r.threshold_s == null
          ? <Text type="secondary">-</Text>
          : (v > 0
            ? <Space size={4}><Tag color="red">{v.toLocaleString(nf)}</Tag>
                <Text type="secondary">{r.over_threshold_pct}%</Text></Space>
            : <Tag color="green">0</Tag>)
      ),
    },
  ], [t, nf])

  /** 逐单清单表（聚合弹窗）：点 TT 号直接进单 TT 复盘 */
  const aggTicketColumns = useMemo(() => [
    {
      title: t('noc.woTtNo'), dataIndex: 'tt_no', key: 'tt_no',
      render: (v: string) => (
        <Tooltip title={t('noc.woViewReport')}>
          <a onClick={() => openTtTimeline(v, 'time')}>{v}</a>
        </Tooltip>
      ),
    },
    { title: t('noc.woSite'), dataIndex: 'site_name', key: 'site_name', render: (v: string) => v || '-' },
    { title: t('noc.aggNocName'), dataIndex: 'noc_name', key: 'noc_name' },
    {
      title: t('noc.woSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 80,
      render: (v: string) => (v ? <Tag color={v === 'P1' ? 'red' : 'orange'}>{v}</Tag> : '-'),
    },
    {
      title: t('noc.woOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 165,
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.woTotal'), dataIndex: 'total_seconds', key: 'total_seconds',
      align: 'right' as const,
      sorter: (a: TicketAggRow, b: TicketAggRow) => (a.total_seconds || 0) - (b.total_seconds || 0),
      defaultSortOrder: 'descend' as const,
      render: (v: number) => fmtSec(v),
    },
    {
      title: t('noc.woBottleneck'), dataIndex: 'bottleneck', key: 'bottleneck',
      render: (v: string, r: TicketAggRow) =>
        v ? <Space size={4}><span>{v}</span><Text type="secondary">{fmtSec(r.bottleneck_seconds)}</Text></Space> : '-',
    },
    {
      title: t('noc.tlTabMilestone'), dataIndex: 'done_count', key: 'done_count',
      align: 'right' as const,
      render: (v: number, r: TicketAggRow) => (
        <Text style={{ color: (v || 0) < (r.stage_count || 0) ? WH.sev.Major : undefined }}>
          {v ?? '-'}/{r.stage_count ?? '-'}
        </Text>
      ),
    },
    {
      title: t('noc.missAction'), dataIndex: 'missing_count', key: 'missing_count',
      align: 'right' as const,
      sorter: (a: TicketAggRow, b: TicketAggRow) => a.missing_count - b.missing_count,
      render: (v: number) => (v > 0 ? <Tag color="red">{v}</Tag> : '-'),
    },
    {
      title: t('noc.devCount'), dataIndex: 'deviation_count', key: 'deviation_count',
      align: 'right' as const,
      sorter: (a: TicketAggRow, b: TicketAggRow) => a.deviation_count - b.deviation_count,
      render: (v: number, r: TicketAggRow) => (
        <Space size={4}>
          <span>{v}</span>
          {r.max_severity && <Tag color={sevColor(r.max_severity)}>{t(sevKey(r.max_severity))}</Tag>}
        </Space>
      ),
    },
    {
      title: t('noc.woDispatched'), dataIndex: 'has_wo', key: 'has_wo', width: 110,
      filters: [
        { text: t('noc.woDispatched'), value: true },
        { text: t('noc.woMissing'), value: false },
      ],
      onFilter: (val: any, r: TicketAggRow) => r.has_wo === val,
      render: (v: boolean, r: TicketAggRow) => (
        r.should_wo && !v
          ? <Tag color="red">{t('noc.woMissing')}</Tag>
          : (v ? <Tag color="green">WO</Tag> : <Text type="secondary">-</Text>)
      ),
    },
  ], [t, openTtTimeline])

  /* ---- 单 TT 复盘视图的列 ---- */
  /** 单 TT 的人工动作等待（NOC 及时性）：超过契约时限标红 */
  const tlHumanColumns = useMemo(() => [
    {
      title: t('noc.actName'), dataIndex: 'label', key: 'label',
      render: (v: string, r: HumanAction) => {
        // 后端 label 是中文硬编码，英文界面要用 i18n 覆盖
        const k = humanActLabelKey(r.key)
        return (
          <Space size={6}>
            <span style={{ color: WH.text }}>{k ? t(k) : v}</span>
            {r.over_threshold && <Tag color="red">{t('noc.actOver')}</Tag>}
          </Space>
        )
      },
    },
    {
      title: t('noc.actWait'), dataIndex: 'wait_s', key: 'wait_s', align: 'right' as const,
      sorter: (a: HumanAction, b: HumanAction) => a.wait_s - b.wait_s,
      defaultSortOrder: 'descend' as const,
      render: (v: number, r: HumanAction) => (
        <Text strong style={{ color: r.over_threshold ? WH.danger : undefined }}>{fmtSec(v)}</Text>
      ),
    },
    {
      title: t('noc.actLimit'), dataIndex: 'threshold_s', key: 'threshold_s', align: 'right' as const,
      render: (v: number | null) =>
        v != null ? fmtSec(v) : <Text type="secondary">{t('noc.actNoLimit')}</Text>,
    },
    {
      title: t('noc.tlFrom'), dataIndex: 'from', key: 'from', width: 165,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('noc.tlTo'), dataIndex: 'to', key: 'to', width: 165,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('noc.tlDetail'), dataIndex: 'note', key: 'note',
      render: (v: string) => (v ? <Text type="secondary" style={{ fontSize: '0.75rem' }}>{v}</Text> : '-'),
    },
  ], [t])

  /** WO 生命周期逐跳 */
  const tlWoStageColumns = useMemo(() => [
    {
      title: t('noc.woLifeStage'), dataIndex: 'label', key: 'label',
      render: (v: string) => <span style={{ color: WH.text }}>{v}</span>,
    },
    {
      title: t('noc.woLifeTime'), dataIndex: 'time', key: 'time', width: 170,
      render: (v: string | null, r: WoStage) =>
        r.time_present ? <span style={{ color: WH.text }}>{v}</span>
          : <Text type="secondary">{t('noc.tlMissingNode')}</Text>,
    },
    {
      title: t('noc.woLifeGap'), dataIndex: 'gap_from_prev_s', key: 'gap_from_prev_s',
      align: 'right' as const,
      // 距上一跳偏大（≥4h）标红：这就是"卡住"的那一跳
      render: (v: number | null) =>
        v == null
          ? <Text type="secondary">-</Text>
          : <Text strong style={{ color: v >= 4 * 3600 ? WH.danger : undefined }}>{fmtSec(v)}</Text>,
    },
    {
      title: t('noc.woLifeOperator'), dataIndex: 'operator', key: 'operator',
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.tlSource'), dataIndex: 'source', key: 'source',
      render: (v: string) => (v ? <Text code style={{ fontSize: '0.6875rem' }}>{v}</Text> : '-'),
    },
  ], [t])

  const tlTlSegColumns = useMemo(() => [
    {
      title: t('noc.tlPhase'), dataIndex: 'phase', key: 'phase', width: 120,
      // 阶段归并名：把相邻同类分段归到一处，便于一眼看出"时间压在哪一类"
      render: (v: string, r: TtSegment) =>
        v ? <Tag>{t(phaseLabelKey(v))}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: t('noc.tlStep'), dataIndex: 'label', key: 'label',
      render: (v: string, r: TtSegment) => (
        <Space size={6}>
          <span style={{ color: WH.text }}>{v}</span>
          {r.over_threshold && <Tag color="red">{t('noc.sevCritical')}</Tag>}
        </Space>
      ),
    },
    {
      title: t('noc.tlOwner'), dataIndex: 'owner', key: 'owner',
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.segSum'), dataIndex: 'seconds', key: 'seconds', align: 'right' as const,
      sorter: (a: TtSegment, b: TtSegment) => a.seconds - b.seconds,
      defaultSortOrder: 'descend' as const,
      render: (v: number, r: TtSegment) => (
        <Text strong style={{ color: r.over_threshold ? WH.danger : undefined }}>{fmtSec(v)}</Text>
      ),
    },
    {
      title: t('noc.segPct'), dataIndex: 'pct', key: 'pct', align: 'right' as const,
      render: (v: number | null) => (v != null ? `${v}%` : '-'),
    },
    {
      title: t('noc.tlFrom'), dataIndex: 'from', key: 'from', width: 165,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('noc.tlTo'), dataIndex: 'to', key: 'to', width: 165,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('noc.stageThreshold'), dataIndex: 'threshold_s', key: 'threshold_s', align: 'right' as const,
      render: (v: number | null, r: TtSegment) =>
        v != null
          ? <Text style={{ color: r.over_threshold ? WH.danger : undefined }}>{fmtSec(v)}</Text>
          : <Text type="secondary">-</Text>,
    },
  ], [t])

  const tlMilestoneColumns = useMemo(() => [
    {
      title: t('noc.tlSeq'), key: 'seq', width: 50,
      render: (_: unknown, __: TimelineNode, i: number) => i + 1,
    },
    {
      title: t('noc.tlTime'), dataIndex: 'time', key: 'time', width: 170,
      render: (v: string | null, r: TimelineNode) =>
        r.time_present
          ? <span style={{ color: WH.text }}>{v}</span>
          : <Text type="secondary">{t('noc.tlMissingNode')}</Text>,
    },
    {
      title: t('noc.tlMilestone'), dataIndex: 'label', key: 'label',
      render: (v: string, r: TimelineNode) => (
        <Space size={6}>
          <span style={{ color: WH.text }}>{v}</span>
          <Tag color={r.actor === 'system' ? 'default' : 'geekblue'}>
            {r.actor === 'system' ? t('noc.stageActorSystem') : t('noc.stageActorHuman')}
          </Tag>
        </Space>
      ),
    },
    {
      // 后端节点没有 gap 字段，按"上一个有时间戳的节点"现场计算
      title: t('noc.tlGap'), key: 'gap', align: 'right' as const,
      render: (_: unknown, r: TimelineNode, i: number) => {
        const gap = nodeGapSeconds(tlReport?.timeline || [], i)
        if (gap == null) return <Text type="secondary">-</Text>
        return <Text style={{ color: gap < 0 ? WH.danger : undefined }}>{fmtSec(gap)}</Text>
      },
    },
    {
      title: t('noc.tlDetail'), dataIndex: 'detail', key: 'detail',
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.tlSource'), dataIndex: 'source', key: 'source',
      render: (v: string) => (v ? <Text code style={{ fontSize: '0.6875rem' }}>{v}</Text> : '-'),
    },
  ], [t, tlReport])

  const tlActionColumns = useMemo(() => [
    {
      title: t('noc.tlMilestone'), dataIndex: 'label', key: 'label',
      render: (v: string, r: TtTimelineReport['expected_actions'][number]) => (
        <Space size={6}>
          <span style={{ color: WH.text }}>{v}</span>
          <Tag color={r.actor === 'system' ? 'default' : 'geekblue'}>
            {r.actor === 'system' ? t('noc.stageActorSystem') : t('noc.stageActorHuman')}
          </Tag>
        </Space>
      ),
    },
    {
      title: t('noc.tlExpected'), dataIndex: 'required', key: 'required', width: 100,
      // 「契约要求」列表达的是该动作是否必须做，不是执行结果
      render: (v: boolean) => (
        <Tag color={v ? 'geekblue' : 'default'}>
          {v ? t('noc.tlRequired') : t('noc.stageConditional')}
        </Tag>
      ),
    },
    {
      title: t('noc.tlActual'), dataIndex: 'done', key: 'done', width: 120,
      render: (v: boolean) => (
        v
          ? <Space size={4}><CheckCircleOutlined style={{ color: WH.ok }} /><Text>{t('noc.tlDoneYes')}</Text></Space>
          : <Space size={4}><CloseCircleOutlined style={{ color: WH.danger }} /><Text strong style={{ color: WH.danger }}>{t('noc.tlDoneNo')}</Text></Space>
      ),
    },
    {
      title: t('noc.tlTime'), dataIndex: 'time', key: 'time', width: 170,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('noc.tlOperator'), dataIndex: 'operator', key: 'operator',
      render: (v: string | null) => v || '-',
    },
    {
      // 后端字段名是 detail（不是 reason），之前写成 reason 导致整列恒为 "-"
      title: t('noc.tlDetail'), dataIndex: 'detail', key: 'detail',
      render: (v: string) => v || '-',
    },
  ], [t])

  // ========== 图表 ==========
  const chartOption = useMemo(() => {
    if (!data?.rows?.length) return null
    const top = data.rows.slice(0, 12)
    const names = top.map(r => r.noc_name)
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const row = top[ps[0]?.dataIndex ?? 0]
          if (!row) return ''
          return [
            `<div style="font-weight:600;margin-bottom:4px">${row.noc_name}</div>`,
            `${t('noc.th.mismatchPct')}: <strong>${fmtPct(row.mismatch_pct)}</strong> (${row.mismatch_count}/${row.with_root_cause})`,
            `${t('noc.th.total')}: <strong>${row.total}</strong>`,
            `${t('noc.th.nightPct')}: <strong>${fmtPct(row.night_pct)}</strong>`,
            `${t('noc.th.slaPass')}: <strong>${fmtPct(row.sla_pass_rate_pct)}</strong>`,
          ].join('<br/>')
        },
      },
      grid: { left: 100, right: 50, top: 20, bottom: 34 },
      xAxis: [
        {
          type: 'value', name: '%', max: 100,
          axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
          splitLine: splitLine(isDark),
        },
      ],
      yAxis: {
        type: 'category',
        data: names.slice().reverse(),
        axisLabel: { ...axisLabel(isDark), fontSize: 11 },
        axisLine: axisLine(isDark),
      },
      series: [
        {
          name: t('noc.th.mismatchPct'),
          type: 'bar',
          data: top.map(r => r.mismatch_pct ?? 0).reverse(),
          barWidth: 11,
          cursor: 'pointer',
          itemStyle: {
            // palette 只有 sev/bg/text 等键，ok/danger 是 WH 令牌；
            // ECharts canvas 解析不了 CSS 变量，故这里用 palette.sev 的实值。
            color: (p: any) => {
              const v = Number(p.value) || 0
              return v >= 30 ? palette.sev.Critical : v >= 15 ? palette.sev.Major : palette.sev.Info
            },
            borderRadius: [0, 4, 4, 0],
          },
          label: {
            show: true, position: 'right', formatter: '{c}%',
            color: isDark ? '#f5f7ff' : '#1f1f1f', fontSize: 10,
          },
        },
      ],
    }
  }, [data, isDark, palette, t])

  // ========== 排名表列（每个数字都可下钻） ==========
  const columns = useMemo(() => {
    /** 生成一个可点击下钻的单元格 */
    const drillable = (content: React.ReactNode, row: NocRow, slice: Slice, tip: string) => (
      <Tooltip title={tip}>
        <a
          style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}
          onClick={e => { e.stopPropagation(); openNocDrill(e, row, slice) }}
        >{content}</a>
      </Tooltip>
    )

    return [
      {
        title: t('noc.th.name'),
        dataIndex: 'noc_name',
        key: 'noc_name',
        width: 230,
        fixed: 'left' as const,
        sorter: (a: NocRow, b: NocRow) => a.noc_name.localeCompare(b.noc_name),
        render: (v: string, r: NocRow) => (
          <Space direction="vertical" size={0}>
            <Tooltip title={t('noc.drillHint')}>
              <a style={{ fontWeight: 600 }} onClick={e => { e.stopPropagation(); openNocDrill(e, r, 'all') }}>{v}</a>
            </Tooltip>
            {r.group && <Text type="secondary" style={{ fontSize: 12 }}>{r.group}</Text>}
          </Space>
        ),
      },
      {
        title: t('noc.th.total'),
        dataIndex: 'total',
        key: 'total',
        width: 100,
        sorter: (a: NocRow, b: NocRow) => a.total - b.total,
        defaultSortOrder: 'descend' as const,
        render: (v: number, r: NocRow) => drillable(v.toLocaleString(nf), r, 'all', t('noc.slice.all')),
      },
      {
        title: t('noc.th.mismatchPct'),
        dataIndex: 'mismatch_pct',
        key: 'mismatch_pct',
        width: 150,
        sorter: (a: NocRow, b: NocRow) => (a.mismatch_pct ?? -1) - (b.mismatch_pct ?? -1),
        render: (v: number | null, r: NocRow) => {
          const color = (v ?? 0) >= 30 ? 'red' : (v ?? 0) >= 15 ? 'orange' : 'green'
          return (
            <Tooltip title={`${r.mismatch_count} / ${r.with_root_cause} · ${t('noc.slice.mismatch')}`}>
              <a onClick={e => { e.stopPropagation(); openNocDrill(e, r, 'mismatch') }}>
                <Tag color={color} style={{ margin: 0, fontWeight: 500, cursor: 'pointer' }}>
                  {fmtPct(v)} ({r.mismatch_count}/{r.with_root_cause})
                </Tag>
              </a>
            </Tooltip>
          )
        },
      },
      {
        title: t('noc.th.mismatchDetail'),
        key: 'mismatch_detail',
        width: 190,
        render: (_: unknown, r: NocRow) => (
          <Space size={4}>
            {r.mismatch_power_trm > 0 && (
              <Tooltip title={`${t('noc.slice.mismatch')} · POWER←TRM`}>
                <Tag
                  color="red" style={{ margin: 0, cursor: 'pointer' }}
                  onClick={e => { e.stopPropagation(); openNocDrill(e as any, r, 'mismatch') }}
                >POWER←TRM: {r.mismatch_power_trm}</Tag>
              </Tooltip>
            )}
            {r.mismatch_other > 0 && (
              <Tooltip title={`${t('noc.slice.mismatch')} · 其它`}>
                <Tag
                  style={{ margin: 0, cursor: 'pointer' }}
                  onClick={e => { e.stopPropagation(); openNocDrill(e as any, r, 'mismatch') }}
                >其它: {r.mismatch_other}</Tag>
              </Tooltip>
            )}
            {r.mismatch_count === 0 && <Text type="secondary">—</Text>}
          </Space>
        ),
      },
      {
        title: t('noc.th.avgDur'),
        dataIndex: 'avg_duration_h',
        key: 'avg_duration_h',
        width: 130,
        sorter: (a: NocRow, b: NocRow) => (a.avg_duration_h ?? -1) - (b.avg_duration_h ?? -1),
        render: (v: number | null, r: NocRow) => {
          const color = (v ?? 0) >= 12 ? 'red' : (v ?? 0) >= 6 ? 'orange' : 'green'
          return (
            <Tooltip title={t('noc.slice.slow')}>
              <a onClick={e => { e.stopPropagation(); openNocDrill(e, r, 'slow') }}>
                <Tag color={color} style={{ margin: 0, cursor: 'pointer' }}>{v == null ? '-' : `${v}h`}</Tag>
              </a>
            </Tooltip>
          )
        },
      },
      {
        title: t('noc.th.nightPct'),
        dataIndex: 'night_pct',
        key: 'night_pct',
        width: 130,
        sorter: (a: NocRow, b: NocRow) => (a.night_pct ?? -1) - (b.night_pct ?? -1),
        render: (v: number | null, r: NocRow) => drillable(
          `${fmtPct(v)} (${r.night_total})`, r, 'night', t('noc.slice.night'),
        ),
      },
      {
        title: t('noc.th.slaPass'),
        dataIndex: 'sla_pass_rate_pct',
        key: 'sla_pass',
        width: 140,
        sorter: (a: NocRow, b: NocRow) => (a.sla_pass_rate_pct ?? -1) - (b.sla_pass_rate_pct ?? -1),
        render: (v: number | null, r: NocRow) => {
          const color = (v ?? 0) >= 90 ? 'green' : (v ?? 0) >= 70 ? 'orange' : 'red'
          return (
            <Tooltip title={`Pass ${r.sla_pass} / Fail ${r.sla_fail} / Total ${r.sla_total}`}>
              <a onClick={e => { e.stopPropagation(); openNocDrill(e, r, 'all') }}>
                <Tag color={color} style={{ margin: 0, cursor: 'pointer' }}>{fmtPct(v)}</Tag>
              </a>
            </Tooltip>
          )
        },
      },
      {
        title: t('noc.th.slaFail'),
        dataIndex: 'sla_fail',
        key: 'sla_fail',
        width: 110,
        sorter: (a: NocRow, b: NocRow) => a.sla_fail - b.sla_fail,
        render: (v: number, r: NocRow) => v
          ? drillable(<Tag color="red" style={{ margin: 0 }}>{v}</Tag>, r, 'sla_fail', t('noc.slice.sla_fail'))
          : <Text type="secondary">0</Text>,
      },
      {
        title: t('noc.drillSample'),
        key: 'tt_sample',
        width: 270,
        render: (_: unknown, r: NocRow) => (
          <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
            {(r.tt_sample || []).slice(0, 3).map(s => (
              <Tooltip key={s.tt_no} title={t('noc.drillTtDetail', { v: s.tt_no })}>
                <span style={{ cursor: 'pointer' }} onClick={() => openTtDetail(s.tt_no)}>
                  <Text code style={{ fontSize: 11 }}>{s.tt_no}</Text>
                  {s.site_name && <Text type="secondary" style={{ marginLeft: 4 }}>{s.site_name}</Text>}
                  {s.ticket_severity && (
                    <Tag style={{ marginLeft: 4, fontSize: 10, padding: '0 4px' }}>{s.ticket_severity}</Tag>
                  )}
                  {s.root_cause && (
                    <Tag color="orange" style={{ marginLeft: 4, fontSize: 10, padding: '0 4px' }}>{s.root_cause}</Tag>
                  )}
                </span>
              </Tooltip>
            ))}
            {!r.tt_sample?.length && <Text type="secondary">-</Text>}
          </Space>
        ),
      },
    ]
  }, [t, openNocDrill, openTtDetail, nf])

  // ========== 第 2 层：TT 明细列 ==========
  const ttColumns = useMemo(() => [
    {
      title: t('noc.tt.ttNo'),
      dataIndex: 'tt_no',
      key: 'tt_no',
      width: 160,
      fixed: 'left' as const,
      sorter: (a: TtDrillRow, b: TtDrillRow) => String(a.tt_no).localeCompare(String(b.tt_no)),
      render: (v: string) => (
        <Tooltip title={t('noc.drillTtDetail', { v })}>
          <a style={{ fontWeight: 600 }} onClick={e => { e.stopPropagation(); openTtDetail(v) }}>{v}</a>
        </Tooltip>
      ),
    },
    {
      title: t('noc.tt.siteName'),
      dataIndex: 'site_name',
      key: 'site_name',
      width: 190,
      ellipsis: true,
      sorter: (a: TtDrillRow, b: TtDrillRow) => String(a.site_name ?? '').localeCompare(String(b.site_name ?? '')),
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.tt.severity'),
      dataIndex: 'ticket_severity',
      key: 'ticket_severity',
      width: 90,
      filters: Array.from(new Set(ttRows.map(r => r.ticket_severity).filter(Boolean) as string[]))
        .slice(0, 20).map(v => ({ text: v, value: v })),
      onFilter: (v: any, r: TtDrillRow) => r.ticket_severity === v,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
    },
    {
      title: t('noc.tt.occurTime'),
      dataIndex: 'alarm_occur_time',
      key: 'alarm_occur_time',
      width: 165,
      sorter: (a: TtDrillRow, b: TtDrillRow) => String(a.alarm_occur_time ?? '').localeCompare(String(b.alarm_occur_time ?? '')),
      render: (v: string) => v || '-',
    },
    {
      title: t('noc.tt.acceptTime'),
      dataIndex: 'accept_time',
      key: 'accept_time',
      width: 165,
      render: (v: string | null, r: TtDrillRow) => (
        <Space size={4}>
          <span>{v || '-'}</span>
          {r.is_night && <Tag color="purple" style={{ margin: 0, fontSize: 10, padding: '0 4px' }}>{t('noc.tt.yes')}</Tag>}
        </Space>
      ),
    },
    {
      title: t('noc.tt.duration'),
      dataIndex: 'maintain_duration_h',
      key: 'maintain_duration_h',
      width: 115,
      sorter: (a: TtDrillRow, b: TtDrillRow) => (a.maintain_duration_h ?? -1) - (b.maintain_duration_h ?? -1),
      render: (v: number | null) => {
        if (v == null) return <Text type="secondary">-</Text>
        const color = v >= 12 ? 'red' : v >= 6 ? 'orange' : 'green'
        return <Tag color={color} style={{ margin: 0 }}>{v}h</Tag>
      },
    },
    {
      title: t('noc.tt.rootCause'),
      dataIndex: 'root_cause',
      key: 'root_cause',
      width: 150,
      ellipsis: true,
      filters: Array.from(new Set(ttRows.map(r => r.root_cause).filter(Boolean) as string[]))
        .slice(0, 40).map(v => ({ text: v, value: v })),
      onFilter: (v: any, r: TtDrillRow) => (r.root_cause ?? '') === v,
      render: (v: string) => v ? <Tag color="orange">{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: t('noc.tt.sysReason'),
      dataIndex: 'system_reason_type',
      key: 'system_reason_type',
      width: 120,
      filters: Array.from(new Set(ttRows.map(r => r.system_reason_type).filter(Boolean) as string[]))
        .slice(0, 20).map(v => ({ text: String(v), value: String(v) })),
      onFilter: (v: any, r: TtDrillRow) => (r.system_reason_type ?? '') === v,
      render: (v: string | null) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: t('noc.tt.mismatchType'),
      dataIndex: 'mismatch_type',
      key: 'mismatch_type',
      width: 130,
      filters: Array.from(new Set(ttRows.map(r => r.mismatch_type).filter(Boolean) as string[]))
        .map(v => ({ text: String(v), value: String(v) })),
      onFilter: (v: any, r: TtDrillRow) => (r.mismatch_type ?? '') === v,
      render: (v: string | null) => v
        ? <Tag color="red" style={{ margin: 0 }}>{v}</Tag>
        : <Text type="secondary">—</Text>,
    },
    {
      title: t('noc.tt.slaStatus'),
      dataIndex: 'sla_status',
      key: 'sla_status',
      width: 100,
      filters: [{ text: 'Pass', value: 'Pass' }, { text: 'Failed', value: 'Failed' }],
      onFilter: (v: any, r: TtDrillRow) => r.sla_status === v,
      render: (v: string | null) => {
        if (!v) return <Text type="secondary">-</Text>
        return <Tag color={v === 'Pass' ? 'green' : 'red'} style={{ margin: 0 }}>{v}</Tag>
      },
    },
    {
      title: t('noc.tt.status'),
      dataIndex: 'status',
      key: 'status',
      width: 120,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
  ], [t, ttRows, openTtDetail])

  // ========== 第 3 层：站点聚合列 ==========
  const openSiteTtsCb = useCallback(openSiteTts, [openSiteTts])
  const siteColumns = useMemo(() => [
    {
      title: t('noc.site.siteName'),
      dataIndex: 'site_name',
      key: 'site_name',
      width: 220,
      fixed: 'left' as const,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => String(a.site_name ?? '').localeCompare(String(b.site_name ?? '')),
      render: (v: string, r: SiteDrillRow) => (
        <Tooltip title={t('noc.drillHint')}>
          <a style={{ fontWeight: 600 }} onClick={() => openSiteTtsCb(r)}>{v || r.site_id || '-'}</a>
        </Tooltip>
      ),
    },
    {
      title: t('noc.site.total'),
      dataIndex: 'total',
      key: 'total',
      width: 100,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => a.total - b.total,
      defaultSortOrder: 'descend' as const,
      render: (v: number, r: SiteDrillRow) => (
        <a style={{ fontVariantNumeric: 'tabular-nums' }} onClick={() => openSiteTtsCb(r)}>{v}</a>
      ),
    },
    {
      title: t('noc.site.mismatch'),
      dataIndex: 'mismatch_count',
      key: 'mismatch_count',
      width: 110,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => a.mismatch_count - b.mismatch_count,
      render: (v: number) => v ? <Tag color="red" style={{ margin: 0 }}>{v}</Tag> : <Text type="secondary">0</Text>,
    },
    {
      title: t('noc.site.slaFail'),
      dataIndex: 'sla_fail',
      key: 'sla_fail',
      width: 105,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => a.sla_fail - b.sla_fail,
      render: (v: number) => v ? <Tag color="red" style={{ margin: 0 }}>{v}</Tag> : <Text type="secondary">0</Text>,
    },
    {
      title: t('noc.site.slow'),
      dataIndex: 'slow_count',
      key: 'slow_count',
      width: 95,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => a.slow_count - b.slow_count,
      render: (v: number) => v ? <Tag color="orange" style={{ margin: 0 }}>{v}</Tag> : <Text type="secondary">0</Text>,
    },
    {
      title: t('noc.site.night'),
      dataIndex: 'night_count',
      key: 'night_count',
      width: 95,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => a.night_count - b.night_count,
    },
    {
      title: t('noc.site.avgDur'),
      dataIndex: 'avg_duration_h',
      key: 'avg_duration_h',
      width: 115,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => (a.avg_duration_h ?? -1) - (b.avg_duration_h ?? -1),
      render: (v: number | null) => v == null ? '-' : `${v}h`,
    },
    {
      title: t('noc.site.topRootCause'),
      dataIndex: 'top_root_cause',
      key: 'top_root_cause',
      width: 150,
      render: (v: string) => v ? <Tag color="orange">{v}</Tag> : '-',
    },
    {
      title: t('noc.site.lastOccur'),
      dataIndex: 'last_occur',
      key: 'last_occur',
      width: 165,
      sorter: (a: SiteDrillRow, b: SiteDrillRow) => String(a.last_occur ?? '').localeCompare(String(b.last_occur ?? '')),
      render: (v: string) => v || '-',
    },
  ], [t, openSiteTtsCb])

  // ========== 导出 ==========
  const exportOverview = useCallback(() => {
    if (!data?.rows?.length) return
    const header = [
      t('noc.th.name'), t('noc.th.group'), t('noc.th.total'),
      t('noc.th.mismatchPct'), t('noc.th.mismatchDetail'), t('noc.th.avgDur'),
      t('noc.th.nightPct'), t('noc.th.slaPass'), t('noc.th.slaFail'),
    ]
    const body = data.rows.map(r => [
      r.noc_name, r.group, r.total,
      fmtPct(r.mismatch_pct),
      `POWER<-TRM:${r.mismatch_power_trm} / other:${r.mismatch_other}`,
      r.avg_duration_h == null ? '' : `${r.avg_duration_h}h`,
      `${fmtPct(r.night_pct)} (${r.night_total})`,
      `${fmtPct(r.sla_pass_rate_pct)} (${r.sla_pass}/${r.sla_total})`,
      r.sla_fail,
    ])
    void exportAoaReport({
      filename: `NOC_Analyst_${month}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'NOC Analyst',
      title: `NOC Analyst ${month}`,
      header,
      rows: body,
      columnWidths: header.map((_, i) => (i === 0 ? 26 : 18)),
    })
  }, [data, month, t])

  const exportDrill = useCallback(() => {
    const isSite = drillTab === 'site' && !siteDrill
    const list: any[] = isSite ? visibleSiteRows : visibleTtRows
    if (!list.length) return
    const header = isSite
      ? [t('noc.site.siteName'), t('noc.site.total'), t('noc.site.mismatch'), t('noc.site.slaFail'),
         t('noc.site.slow'), t('noc.site.night'), t('noc.site.avgDur'), t('noc.site.topRootCause'), t('noc.site.lastOccur')]
      : [t('noc.tt.ttNo'), t('noc.tt.siteName'), t('noc.tt.severity'), t('noc.tt.occurTime'),
         t('noc.tt.acceptTime'), t('noc.tt.duration'), t('noc.tt.rootCause'), t('noc.tt.sysReason'),
         t('noc.tt.mismatchType'), t('noc.tt.slaStatus'), t('noc.tt.status')]
    const body = list.map(r => isSite
      ? [r.site_name, r.total, r.mismatch_count, r.sla_fail, r.slow_count, r.night_count,
         r.avg_duration_h == null ? '' : `${r.avg_duration_h}h`, r.top_root_cause, r.last_occur]
      : [r.tt_no, r.site_name, r.ticket_severity, r.alarm_occur_time, r.accept_time,
         r.maintain_duration_h == null ? '' : `${r.maintain_duration_h}h`,
         r.root_cause, r.system_reason_type, r.mismatch_type, r.sla_status, r.status])
    void exportAoaReport({
      filename: `NOC_${drillNoc.replace(/[^\w]+/g, '_')}_${isSite ? 'sites' : drillSlice}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: isSite ? 'Sites' : 'TT',
      title: `NOC ${drillNoc} · ${isSite ? 'Sites' : drillSlice}`,
      header,
      rows: body,
      columnWidths: header.map(() => 18),
    })
  }, [drillTab, siteDrill, visibleSiteRows, visibleTtRows, drillNoc, drillSlice, t])

  const redFlagNames = useMemo(
    () => new Set((data?.red_flags || []).map(r => r.noc_name)),
    [data],
  )

  // ========== Top3 / Bottom3 卡片 ==========
  const renderRankCard = (
    row: NocRow, rank: number, kind: 'mismatch' | 'sla', accent: string,
    icon: React.ReactNode, explain: string, divider = false,
  ) => (
    <Col
      xs={24} sm={12} lg={8}
      key={`${kind}-${row.noc_name}`}
      style={{
        marginBottom: 'var(--wh-space-sm)',
        borderLeft: divider ? '1px solid rgba(0, 217, 255, 0.25)' : undefined,
        paddingLeft: divider ? 'calc(var(--wh-space-sm) + 4px)' : undefined,
      }}
    >
      <CardBase
        interactive
        style={{ height: '100%', position: 'relative', overflow: 'hidden' }}
        onClick={e => openNocDrill(e, row, kind === 'sla' ? 'sla_fail' : 'mismatch')}
      >
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: WH.accentGrad, opacity: 0.9 }} />
        <Tooltip title={explain}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--wh-space-sm)' }}>
            <span style={{
              display: 'grid', placeItems: 'center', width: 32, height: 32, flexShrink: 0,
              borderRadius: 'var(--wh-radius-sm)', background: WH.teal20, color: accent, fontSize: '1rem',
            }}>{icon}</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-xs)' }}>
                <span style={{
                  font: '700 0.625rem/1 var(--wh-font-mono, monospace)', letterSpacing: '.08em',
                  padding: '3px 6px', borderRadius: 4, flexShrink: 0, color: accent, background: WH.teal20,
                }}>#{rank}</span>
                <span style={{
                  fontSize: '0.8125rem', fontWeight: 600, color: WH.text,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{row.noc_name}</span>
              </div>
              {row.group && (
                <div style={{ fontSize: '0.6875rem', color: WH.textDim, marginTop: 3 }}>{row.group}</div>
              )}
            </div>
          </div>
        </Tooltip>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap',
          marginTop: 'var(--wh-space-sm)', fontVariantNumeric: 'tabular-nums',
          fontSize: '0.6875rem', color: WH.textMuted,
        }}>
          {(kind === 'mismatch'
            ? [
                { label: t('noc.th.mismatchPct'), value: fmtPct(row.mismatch_pct), color: accent },
                { label: t('noc.th.total'), value: String(row.total) },
                { label: t('noc.th.slaPass'), value: fmtPct(row.sla_pass_rate_pct) },
              ]
            : [
                { label: t('noc.th.slaPass'), value: fmtPct(row.sla_pass_rate_pct), color: accent },
                { label: t('noc.th.slaFail'), value: String(row.sla_fail), color: row.sla_fail ? WH.danger : undefined },
                { label: t('noc.th.total'), value: String(row.total) },
              ]
          ).map((m, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              {i > 0 && <span style={{ opacity: 0.45 }}>·</span>}
              <span style={{ color: m.color || WH.textMuted, fontWeight: m.color ? 700 : 500 }}>{m.value}</span>
              <span>{m.label}</span>
            </span>
          ))}
        </div>
        <div style={{
          textAlign: 'right', fontSize: '0.625rem', color: WH.teal, fontWeight: 600,
          marginTop: 6, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2,
        }}>
          {t('noc.cardHint')} <RightOutlined style={{ fontSize: '0.5625rem' }} />
        </div>
      </CardBase>
    </Col>
  )

  return (
    <div style={pageWrap}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {/* ====== 工具栏 ====== */}
        <CardBase>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <Title level={5} style={{ margin: 0, color: WH.text }}>
                <TrophyOutlined style={{ marginRight: 8 }} />{t('noc.navLabel')}
              </Title>
              <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.tip')}</Text>
            </div>
            <Space wrap>
              <Select
                value={month}
                onChange={setMonth}
                options={monthOptions.map(m => ({ value: m, label: m }))}
                style={{ width: 120 }}
                aria-label={t('noc.month')}
              />
              <Input
                placeholder={t('noc.searchPh')}
                allowClear
                prefix={<SearchOutlined />}
                value={nocFilter}
                onChange={e => setNocFilter(e.target.value)}
                onPressEnter={load}
                style={{ width: 220 }}
              />
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('noc.refresh')}</Button>
              <Button icon={<DownloadOutlined />} onClick={exportOverview} disabled={!data?.rows?.length}>
                {t('common.exportExcel')}
              </Button>
            </Space>
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.timeFieldNote')}</Text>
            {data?.meta?.night_window && (
              <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                {t('noc.nightWindow', { v: data.meta.night_window })}
              </Text>
            )}
            <Text style={{ fontSize: '0.6875rem', color: WH.teal }}>{t('noc.drillHint')}</Text>
          </div>
        </CardBase>

        {error && <Alert type="error" showIcon message={error} />}

        <Spin spinning={loading}>
          {data && data.rows.length > 0 && (
            <>
              {/* ====== 概览数字卡 ====== */}
              <Row gutter={[12, 12]}>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.stat.nocCount')} value={data.summary.noc_count || 0}
                    accentColor={WH.teal} prefix={<TrophyOutlined />}
                  />
                </Col>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.th.total')} value={data.summary.total_handled || 0}
                    accentColor={palette.blue} prefix={<ClockCircleOutlined />}
                  />
                </Col>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.th.mismatchPct')}
                    value={data.summary.avg_mismatch_pct ?? 0}
                    suffix="%" accentColor={(data.summary.avg_mismatch_pct ?? 0) >= 30 ? WH.danger : WH.ok}
                    prefix={<WarningOutlined />}
                  />
                </Col>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.th.avgDur')}
                    value={data.summary.avg_duration_h ?? 0}
                    suffix="h" accentColor={(data.summary.avg_duration_h ?? 0) >= 12 ? WH.danger : WH.ok}
                  />
                </Col>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.th.slaPass')}
                    value={data.summary.overall_sla_pass_rate_pct ?? 0}
                    suffix="%" accentColor={(data.summary.overall_sla_pass_rate_pct ?? 0) >= 90 ? WH.ok : WH.sev.Major}
                    prefix={<SafetyOutlined />}
                  />
                </Col>
                <Col xs={12} sm={8} lg={4}>
                  <StatCard
                    title={t('noc.stat.redFlag')} value={data.red_flags?.length || 0}
                    accentColor={data.red_flags?.length ? WH.danger : WH.ok}
                    prefix={<FireOutlined />}
                  />
                </Col>
              </Row>

              {/* ====== 红旗告警（每人可点进明细） ====== */}
              {data.red_flags && data.red_flags.length > 0 && (
                <Alert
                  type="error"
                  showIcon
                  message={
                    <Space>
                      <FireOutlined />
                      <Text strong>{t('noc.redFlag')} ({data.red_flags.length})</Text>
                      <Text type="secondary">{t('noc.redFlagHint')}</Text>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={4} style={{ marginTop: 4 }}>
                      {data.red_flags.map(rf => {
                        const row = data.rows.find(r => r.noc_name === rf.noc_name)
                        return (
                          <div key={rf.noc_name}>
                            <Tooltip title={t('noc.drillHint')}>
                              <a
                                style={{ fontWeight: 700, color: WH.danger }}
                                onClick={e => row && openNocDrill(e, row, 'mismatch')}
                              >{rf.noc_name}</a>
                            </Tooltip>
                            <Text type="secondary"> · {rf.total} · {t('noc.th.mismatchPct')} {fmtPct(rf.mismatch_pct)}</Text>
                            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                              {rf.reasons.map((rs, i) => <li key={i}>{rs}</li>)}
                            </ul>
                          </div>
                        )
                      })}
                    </Space>
                  }
                />
              )}

              {/* ====== 时间归因与流程偏离（参考「TT 复盘报告」，2026-09-23 新增）====== */}
              <CardBase style={{ marginTop: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <Title level={5} style={{ margin: 0, color: WH.text }}>
                      <FieldTimeOutlined style={{ marginRight: 8 }} />{t('noc.aggTitle')}
                    </Title>
                    <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggSub')}</Text>
                  </div>
                  <Space wrap size={8}>
                    {agg?.meta && (
                      <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                        {agg.meta.cache_hit
                          ? t('noc.aggCacheHit')
                          : t('noc.aggElapsed', { s: agg.meta.elapsed_s })}
                        {' · '}
                        {t('noc.aggGeneratedAt', { t: agg.meta.generated_at })}
                      </Text>
                    )}
                    <Button
                      size="small" icon={<ReloadOutlined />}
                      loading={aggLoading}
                      onClick={() => loadAgg(true)}
                    >
                      {aggLoading ? t('noc.aggRefreshing') : t('noc.aggRefresh')}
                    </Button>
                  </Space>
                </div>

                {aggError && (
                  <Alert type="error" showIcon style={{ marginTop: 8 }} message={aggError} />
                )}

                {aggLoading && !agg && (
                  <div style={{ padding: '18px 0', textAlign: 'center' }}>
                    <Spin />
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: '0.75rem' }}>{t('noc.aggLoading')}</Text>
                    </div>
                  </div>
                )}

                {!aggLoading && !agg && !aggError && (
                  <Alert
                    type="warning" showIcon style={{ marginTop: 8 }}
                    message={t('noc.aggUnavailable')}
                  />
                )}

                {agg && (
                  <>
                    {agg.meta.truncated && (
                      <Alert
                        type="warning" showIcon style={{ marginTop: 8 }}
                        message={t('noc.aggTruncated', { n: agg.meta.scanned })}
                      />
                    )}

                    {/* ---- 数字卡：每一个都可点下钻 ---- */}
                    <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardTotalSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardTotal')}</Text>
                            <div style={{ font: '700 1.35rem/1.2 var(--wh-font-mono, monospace)', color: WH.text, marginTop: 4 }}>
                              {(agg.meta.parsed || 0).toLocaleString(nf)}
                            </div>
                          </CardBase>
                        </Tooltip>
                      </Col>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardAvgTotalSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardAvgTotal')}</Text>
                            <div style={{ font: '700 1.35rem/1.2 var(--wh-font-mono, monospace)', color: WH.text, marginTop: 4 }}>
                              {fmtSec(aggAvgTotalS)}
                            </div>
                          </CardBase>
                        </Tooltip>
                      </Col>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardBottleneckSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardBottleneck')}</Text>
                            <div style={{ font: '700 0.9375rem/1.4 var(--wh-font-mono, monospace)', color: WH.sev.Major, marginTop: 6 }}>
                              {aggTopSegment?.label || '-'}
                            </div>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                              {aggTopSegment?.pct != null ? `${aggTopSegment.pct}%` : ''}
                            </Text>
                          </CardBase>
                        </Tooltip>
                      </Col>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardNoWoSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardNoWo')}</Text>
                            <div style={{
                              font: '700 1.35rem/1.2 var(--wh-font-mono, monospace)', marginTop: 4,
                              color: (agg.wo_stats.missing_dispatch || 0) > 0 ? WH.danger : WH.ok,
                            }}>
                              {(agg.wo_stats.missing_dispatch || 0).toLocaleString(nf)}
                            </div>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                              {/* 这里必须显示"派单覆盖率"，不能显示 missing/should —— 后者恒为 100% */}
                              {agg.wo_stats.dispatch_rate_pct != null
                                ? `${t('noc.woRate')} ${agg.wo_stats.dispatch_rate_pct}%`
                                : ''}
                            </Text>
                          </CardBase>
                        </Tooltip>
                      </Col>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardDeviationSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardDeviation')}</Text>
                            <div style={{
                              font: '700 1.35rem/1.2 var(--wh-font-mono, monospace)', marginTop: 4, color: WH.danger,
                            }}>
                              {(agg.deviation_stats || []).reduce((a, d) => a + d.count, 0).toLocaleString(nf)}
                            </div>
                          </CardBase>
                        </Tooltip>
                      </Col>
                      <Col xs={12} sm={8} lg={4}>
                        <Tooltip title={t('noc.aggCardMissingSub')}>
                          <CardBase interactive onClick={() => setAggDetailOpen(true)}>
                            <Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.aggCardMissing')}</Text>
                            <div style={{ font: '700 1.35rem/1.2 var(--wh-font-mono, monospace)', color: WH.text, marginTop: 4 }}>
                              {(agg.missing_stats || []).reduce((a, m) => a + m.count, 0).toLocaleString(nf)}
                            </div>
                          </CardBase>
                        </Tooltip>
                      </Col>
                    </Row>

                    {/* ---- 图表：占时比例 + 偏离分布 ---- */}
                    <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
                      <Col xs={24} xl={12}>
                        <CardBase>
                          <Text strong style={{ color: WH.text }}>{t('noc.chartSegTitle')}</Text>
                          {segChartOption
                            ? <ReactECharts option={segChartOption} style={{ height: 240 }} notMerge lazyUpdate />
                            : <Empty description={t('noc.segNoData')} />}
                        </CardBase>
                      </Col>
                      <Col xs={24} xl={12}>
                        <CardBase>
                          <Text strong style={{ color: WH.text }}>{t('noc.chartDevTitle')}</Text>
                          {devChartOption
                            ? <ReactECharts option={devChartOption} style={{ height: 240 }} notMerge lazyUpdate />
                            : <Empty description={t('noc.devNone')} />}
                        </CardBase>
                      </Col>
                    </Row>

                    {/* ---- 分段表：时间都花哪了 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>{t('noc.segTitle')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.segSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.segment_stats}
                        columns={segColumns}
                        rowKey="key"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                      />
                    </div>

                    {/* ---- 里程碑耗时分布 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>{t('noc.stageTitle')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.stageSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.stage_stats}
                        columns={stageColumns}
                        rowKey="key"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                      />
                    </div>

                    {/* ---- 应派未派 WO（本次重点）---- */}
                    <div style={{ marginTop: 16 }}>
                      <Space size={8} wrap>
                        <Text strong style={{ color: WH.danger }}>
                          <ThunderboltOutlined style={{ marginRight: 4 }} />{t('noc.woTitle')}
                        </Text>
                        <Text type="secondary" style={{ fontSize: '0.75rem' }}>{t('noc.woSub')}</Text>
                        <Tag color="blue">{t('noc.woDispatched')}: {agg.wo_stats.dispatched}</Tag>
                        <Tag color="red">{t('noc.woMissing')}: {agg.wo_stats.missing_dispatch}</Tag>
                        {agg.wo_stats.dispatch_rate_pct != null && (
                          <Tag color={agg.wo_stats.dispatch_rate_pct >= 90 ? 'green' : 'orange'}>
                            {t('noc.woRate')}: {agg.wo_stats.dispatch_rate_pct}%
                          </Tag>
                        )}
                      </Space>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.no_wo_tickets}
                        columns={noWoColumns}
                        rowKey="tt_no"
                        size="small"
                        pagination={{ pageSize: 10, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                        scroll={{ x: 'max-content' }}
                        locale={{ emptyText: <Empty description={t('noc.woNone')} /> }}
                      />
                    </div>

                    {/* ---- 偏离清单 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>{t('noc.devTitle')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.devSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.deviation_stats}
                        columns={devColumns}
                        rowKey="code"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                        locale={{ emptyText: <Empty description={t('noc.devNone')} /> }}
                      />
                    </div>

                    {/* ---- 阶段归并：NOC 手里 / 现场 / 系统 各占多久 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>
                        <PieChartOutlined style={{ marginRight: 4 }} />{t('noc.phaseTitle')}
                      </Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.phaseSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.phase_stats || []}
                        columns={phaseColumns}
                        rowKey="phase"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                      />
                    </div>

                    {/* ---- 现场处置及时性：WO 各跳耗时分布 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Space size={8} wrap>
                        <Text strong style={{ color: WH.text }}>
                          <ThunderboltOutlined style={{ marginRight: 4 }} />{t('noc.woGwTitle')}
                        </Text>
                        <Text type="secondary" style={{ fontSize: '0.75rem' }}>{t('noc.woGwSub')}</Text>
                        <Tag color="blue">{t('noc.woGwCount')}: {agg.wo_with_timeline ?? 0}</Tag>
                      </Space>
                      {(agg.wo_gap_stats || []).length === 0 ? (
                        <Alert type="warning" showIcon style={{ marginTop: 8 }} message={t('noc.woGwNone')} />
                      ) : (
                        <Table
                          style={{ marginTop: 8 }}
                          dataSource={agg.wo_gap_stats}
                          columns={woGapColumns}
                          rowKey="key"
                          size="small"
                          pagination={false}
                          scroll={{ x: 'max-content' }}
                        />
                      )}
                    </div>

                    {/* ---- NOC / 人工动作及时性 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>
                        <ClockCircleOutlined style={{ marginRight: 4 }} />{t('noc.actTitle')}
                      </Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.actSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.human_action_stats || []}
                        columns={humanActColumns}
                        rowKey="key"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                        locale={{ emptyText: <Empty description={t('noc.actNone')} /> }}
                      />
                    </div>

                    {/* ---- 缺失必需动作 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>{t('noc.missTitle')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.missSub')}</Text>
                      {(agg.missing_stats || []).length === 0 ? (
                        <Alert type="success" showIcon style={{ marginTop: 8 }} message={t('noc.missNone')} />
                      ) : (
                        <Space direction="vertical" size={4} style={{ marginTop: 8, width: '100%' }}>
                          {agg.missing_stats.map(m => (
                            <Space key={m.key} size={8} wrap>
                              <Tag color="red">{m.count}</Tag>
                              <Text strong style={{ color: WH.text }}>{m.label || m.key}</Text>
                              <Space size={4} wrap>
                                {(m.sample_tts || []).map(tt => (
                                  <a key={tt} onClick={() => openTtTimeline(tt, 'actions')}>{tt}</a>
                                ))}
                              </Space>
                            </Space>
                          ))}
                        </Space>
                      )}
                    </div>

                    {/* ---- 按 NOC 归因 ---- */}
                    <div style={{ marginTop: 16 }}>
                      <Text strong style={{ color: WH.text }}>{t('noc.aggNocTitle')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.aggNocSub')}</Text>
                      <Table
                        style={{ marginTop: 8 }}
                        dataSource={agg.noc_stats}
                        columns={aggNocColumns}
                        rowKey="noc_name"
                        size="small"
                        pagination={{ pageSize: 10, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                        scroll={{ x: 'max-content' }}
                      />
                    </div>
                  </>
                )}
              </CardBase>

              {/* ====== Top3 / Bottom3 卡片 ====== */}
              {!!topMismatch.length && (
                <>
                  <Row gutter={[12, 12]}>
                    <Col xs={24} xl={12}>
                      <Text strong style={{ color: WH.text }}>{t('noc.topNoc')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.topNocSub')}</Text>
                    </Col>
                    <Col xs={24} xl={12}>
                      <Text strong style={{ color: WH.text }}>{t('noc.bottomSlaNoc')}</Text>
                      <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>{t('noc.bottomSlaNocSub')}</Text>
                    </Col>
                  </Row>
                  <Row gutter={[12, 12]} align="stretch">
                    {topMismatch.map((row, i) =>
                      renderRankCard(row, i + 1, 'mismatch', WH.sev.Critical, <WarningOutlined />, t('noc.explain.topNoc')))}
                    {bottomSla.map((row, i) =>
                      renderRankCard(row, i + 1, 'sla', WH.sev.Major, <SafetyOutlined />, t('noc.explain.bottomSla'), i === 0))}
                  </Row>
                </>
              )}

              {/* ====== 指标对比图（点柱子下钻） ====== */}
              {chartOption && (
                <CardBase
                  title={t('noc.chartTitle')}
                  extra={<Text type="secondary" style={{ fontSize: '0.6875rem' }}>{t('noc.chartHint')}</Text>}
                >
                  <ReactECharts
                    option={chartOption}
                    style={{ height: 400 }}
                    notMerge
                    lazyUpdate
                    onEvents={{
                      click: (p: any) => {
                        if (!p?.name) return
                        const row = data.rows.find(r => r.noc_name === String(p.name))
                        if (row) openNocDrill(p, row, 'mismatch')
                      },
                    }}
                  />
                </CardBase>
              )}

              {/* ====== 排名表（每列可下钻） ====== */}
              <CardBase
                title={t('noc.navLabel')}
                extra={<Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                  {t('noc.summary', {
                    n: data.summary.noc_count,
                    total: data.summary.total_handled,
                    mis: fmtPct(data.summary.avg_mismatch_pct),
                    dur: data.summary.avg_duration_h ?? '-',
                    sla: fmtPct(data.summary.overall_sla_pass_rate_pct),
                  })}
                </Text>}
                bodyStyle={{ padding: 0 }}
              >
                <Table<NocRow>
                  rowKey="noc_name"
                  loading={loading}
                  dataSource={data.rows}
                  columns={columns}
                  pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100] }}
                  scroll={{ x: 1380 }}
                  size="small"
                  rowClassName={(r) => redFlagNames.has(r.noc_name) ? 'noc-row-red' : ''}
                />
              </CardBase>
            </>
          )}

          {data && data.rows.length === 0 && (
            <Empty description={t('noc.noData')} style={{ marginTop: 40 }} />
          )}
        </Spin>
      </Space>

      {/* ================================================================
          第 2/3 层：NOC 下钻弹窗（Tab：TT 明细 / 异常站点）
          ================================================================ */}
      <DraggableClickModal
        open={drillOpen}
        anchor={drillAnchor}
        onClose={() => setDrillOpen(false)}
        width="94%"
        title={
          <span style={{ color: WH.text }}>
            {siteDrill
              ? t('noc.drillSite', { v: siteDrill.siteName })
              : t('noc.drillNoc', { v: drillNoc })}
            <Tag color="cyan" style={{ borderRadius: 10, marginLeft: 8 }}>
              {siteDrill
                ? t('common.records', { n: visibleTtRows.length })
                : drillTab === 'tt'
                  ? t('noc.drillCount', { n: ttMeta.matched, total: ttMeta.total || ttMeta.matched })
                  : t('common.records', { n: visibleSiteRows.length })}
            </Tag>
            {drillNocRow && !siteDrill && (
              <Tag color="orange" style={{ borderRadius: 10, marginLeft: 4 }}>
                {t(sliceLabelKey(drillSlice))}
              </Tag>
            )}
          </span>
        }
      >
        {/* 工具栏 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem',
        }}>
          <Space wrap>
            <Input
              prefix={<SearchOutlined />}
              placeholder={t('common.searchAllFields')}
              allowClear
              style={{ width: 'min(100%, 21.875rem)' }}
              value={drillSearch}
              onChange={e => setDrillSearch(e.target.value)}
            />
            {/* 切片切换：只在没进站点二次下钻时显示 */}
            {!siteDrill && drillTab === 'tt' && (
              <Select
                value={drillSlice}
                onChange={v => changeSlice(v as Slice)}
                style={{ width: 170 }}
                options={(['all', 'mismatch', 'night', 'sla_fail', 'slow'] as Slice[]).map(s => ({
                  value: s, label: t(sliceLabelKey(s)),
                }))}
              />
            )}
            {!siteDrill && drillTab === 'site' && (
              <Select
                value={siteAll ? 'all' : 'abnormal'}
                onChange={v => toggleSiteScope(v === 'all')}
                style={{ width: 170 }}
                options={[
                  { value: 'abnormal', label: t('noc.drillOnlyAbnormal') },
                  { value: 'all', label: t('noc.drillAllSites') },
                ]}
              />
            )}
          </Space>
          <Space>
            {siteDrill && (
              <Button onClick={() => { setSiteDrill(null); setDrillSearch('') }}>
                {t('noc.drillBack')}
              </Button>
            )}
            <Button
              type="primary" icon={<DownloadOutlined />} onClick={exportDrill}
              disabled={!(siteDrill ? visibleTtRows.length : drillTab === 'site' ? visibleSiteRows.length : visibleTtRows.length)}
            >
              {t('common.exportExcel')}
            </Button>
          </Space>
        </div>

        {drillError && <Alert type="error" showIcon message={drillError} style={{ marginBottom: 8 }} />}
        {ttMeta.truncated && (
          <Alert type="warning" showIcon style={{ marginBottom: 8 }}
            message={t('noc.drillTruncated', { n: ttMeta.matched })} />
        )}

        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : siteDrill ? (
          /* ---- 站点二次下钻：该站点的 TT ---- */
          <Table
            dataSource={visibleTtRows}
            columns={ttColumns}
            size="small"
            rowKey={(r: TtDrillRow) => r.tt_no}
            pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: <Empty description={t('noc.drillEmpty')} /> }}
          />
        ) : (
          <Tabs
            activeKey={drillTab}
            onChange={k => setDrillTab(k as 'tt' | 'site')}
            items={[
              {
                key: 'tt',
                label: `${t('noc.drillTabTt')} (${ttMeta.matched})`,
                children: (
                  <Table
                    dataSource={visibleTtRows}
                    columns={ttColumns}
                    size="small"
                    rowKey={(r: TtDrillRow) => r.tt_no}
                    pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: <Empty description={t('noc.drillEmpty')} /> }}
                  />
                ),
              },
              {
                key: 'site',
                label: `${t('noc.drillTabSite')} (${siteMeta.siteCount})`,
                children: (
                  <Table
                    dataSource={visibleSiteRows}
                    columns={siteColumns}
                    size="small"
                    rowKey={(r: SiteDrillRow) => String(r.site_id ?? r.site_name ?? '')}
                    pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: <Empty description={t('noc.drillSiteEmpty')} /> }}
                  />
                ),
              },
            ]}
          />
        )}
      </DraggableClickModal>

      {/* ================================================================
          第 4 层：单 TT 详情（告警链路 + 根因一致性审计）
          ================================================================ */}
      <DraggableClickModal
        open={ttDetailOpen}
        onClose={() => setTtDetailOpen(false)}
        width="86%"
        title={<span style={{ color: WH.text }}>{t('noc.drillTtDetail', { v: ttDetail?.tt_no || '' })}</span>}
      >
        {ttDetailLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : !ttDetail?.found ? (
          <Empty description={t('noc.drillEmpty')} />
        ) : (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* 一致性结论：最醒目的一条 */}
            <Alert
              type={ttDetail.consistency === false ? 'error' : ttDetail.consistency === true ? 'success' : 'warning'}
              showIcon
              icon={
                ttDetail.consistency === false ? <CloseCircleOutlined />
                  : ttDetail.consistency === true ? <CheckCircleOutlined />
                    : <QuestionCircleOutlined />
              }
              message={
                <Space>
                  <Text strong>
                    {t('noc.ttDetail.consistency')}：
                    {ttDetail.consistency === false ? t('noc.ttDetail.inconsistent')
                      : ttDetail.consistency === true ? t('noc.ttDetail.consistent')
                        : t('noc.ttDetail.unknown')}
                  </Text>
                  {ttDetail.mismatch_type && <Tag color="red">{ttDetail.mismatch_type}</Tag>}
                  {ttDetail.confidence && (
                    <Text type="secondary">{t('noc.ttDetail.confidence')}: {ttDetail.confidence}</Text>
                  )}
                </Space>
              }
              description={<Text>{ttDetail.note}</Text>}
            />

            {/* 工单信息 */}
            <CardBase title={t('noc.ttDetail.ticket')}>
              <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} bordered>
                <Descriptions.Item label={t('noc.tt.siteName')}>{ttDetail.site?.site_name || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.severity')}>{ttDetail.ticket.ticket_severity || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.status')}>{ttDetail.ticket.status || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.occurTime')}>{ttDetail.ticket.alarm_occur_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.acceptTime')}>
                  <Space size={4}>
                    {ttDetail.ticket.accept_time || '-'}
                    {ttDetail.ticket.is_night && <Tag color="purple">{t('noc.tt.yes')}</Tag>}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.duration')}>
                  {ttDetail.ticket.maintain_duration_h == null ? '-' : `${ttDetail.ticket.maintain_duration_h}h`}
                </Descriptions.Item>
                <Descriptions.Item label={t('noc.tt.slaStatus')}>
                  {ttDetail.ticket.sla_status
                    ? <Tag color={ttDetail.ticket.sla_status === 'Pass' ? 'green' : 'red'}>{ttDetail.ticket.sla_status}</Tag>
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label={t('noc.ttDetail.chainCol.code')}>{ttDetail.ticket.alarm_code || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('noc.ttDetail.linkage')}>
                  <Tag color="cyan">{t(linkageLabelKey(ttDetail.system_judged?.linkage))}</Tag>
                </Descriptions.Item>
              </Descriptions>
            </CardBase>

            {/* 阶段时长 */}
            {ttDetail.ticket.durations && (
              <CardBase title={t('noc.ttDetail.stageDurations')}>
                <Descriptions size="small" column={{ xs: 2, sm: 4 }} bordered>
                  <Descriptions.Item label={t('noc.ttDetail.createToAccept')}>
                    {fmtSec(ttDetail.ticket.durations.create_to_accept_seconds)}
                  </Descriptions.Item>
                  <Descriptions.Item label={t('noc.ttDetail.acceptToProcess')}>
                    {fmtSec(ttDetail.ticket.durations.accept_to_process_seconds)}
                  </Descriptions.Item>
                  <Descriptions.Item label={t('noc.ttDetail.processToConfirm')}>
                    {fmtSec(ttDetail.ticket.durations.process_to_confirm_seconds)}
                  </Descriptions.Item>
                  <Descriptions.Item label={t('noc.ttDetail.totalDuration')}>
                    <Text strong>{fmtSec(ttDetail.ticket.durations.total_seconds)}</Text>
                  </Descriptions.Item>
                </Descriptions>
              </CardBase>
            )}

            {/* NOC 填报层 vs 系统判定层 */}
            <Row gutter={[12, 12]}>
              <Col xs={24} lg={12}>
                <CardBase title={t('noc.ttDetail.nocFilled')} style={{ height: '100%' }}>
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label={t('noc.tt.rootCause')}>
                      {ttDetail.noc_filled.root_cause || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('noc.ttDetail.filedBy')}>
                      {ttDetail.noc_filled.filed_by || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('noc.ttDetail.filedAt')}>
                      {ttDetail.noc_filled.filed_at || '-'}
                    </Descriptions.Item>
                    {ttDetail.noc_filled.root_cause_description && (
                      <Descriptions.Item label={t('noc.tt.rootCause') + ' desc'}>
                        {ttDetail.noc_filled.root_cause_description}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </CardBase>
              </Col>
              <Col xs={24} lg={12}>
                <CardBase title={t('noc.ttDetail.systemJudged')} style={{ height: '100%' }}>
                  {ttDetail.system_judged ? (
                    <Descriptions size="small" column={1} bordered>
                      <Descriptions.Item label={t('noc.ttDetail.faultDomain')}>
                        <Tag color="blue">{ttDetail.system_judged.fault_domain || '-'}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label={t('noc.ttDetail.chainCol.name')}>
                        {ttDetail.system_judged.codename || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('noc.ttDetail.chainCol.reasonType')}>
                        {ttDetail.system_judged.reason_type || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('noc.ttDetail.basis')}>
                        {ttDetail.system_judged.basis || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('noc.ttDetail.alarmChain')}>
                        {t('common.records', { n: ttDetail.system_judged.alarm_count || 0 })}
                      </Descriptions.Item>
                    </Descriptions>
                  ) : <Empty description={t('noc.ttDetail.noChain')} />}
                </CardBase>
              </Col>
            </Row>

            {/* 告警链路明细 */}
            <CardBase title={t('noc.ttDetail.alarmChain')}>
              {ttDetail.alarm_chain?.length ? (
                <Table
                  dataSource={ttDetail.alarm_chain}
                  size="small"
                  rowKey={(r, i) => `${r.alarmcode ?? ''}-${i}`}
                  pagination={{ pageSize: 10, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
                  scroll={{ x: 'max-content' }}
                  columns={[
                    { title: t('noc.ttDetail.chainCol.code'), dataIndex: 'alarmcode', width: 110 },
                    { title: t('noc.ttDetail.chainCol.name'), dataIndex: 'codename', ellipsis: true },
                    {
                      title: t('noc.ttDetail.chainCol.reasonType'), dataIndex: 'reason_type', width: 110,
                      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-',
                    },
                    {
                      title: t('noc.ttDetail.chainCol.family'), dataIndex: 'family', width: 120,
                      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
                    },
                    {
                      title: t('noc.ttDetail.chainCol.domain'), dataIndex: 'fault_domain', width: 110,
                      render: (v: string) => v ? <Tag color="geekblue">{v}</Tag> : '-',
                    },
                    {
                      title: t('noc.ttDetail.chainCol.source'), dataIndex: 'alarm_source', width: 130,
                      render: (v: string) => v || '-',
                    },
                  ]}
                />
              ) : (
                <Empty description={t('noc.ttDetail.noChain')} />
              )}
            </CardBase>
          </Space>
        )}
      </DraggableClickModal>

      {/* ================================================================
          逐单清单：时间轴聚合覆盖到的全部工单（卡片入口）
          ================================================================ */}
      <DraggableClickModal
        open={aggDetailOpen}
        onClose={() => setAggDetailOpen(false)}
        width="90%"
        title={<span style={{ color: WH.text }}>{t('noc.aggTitle')} · {agg?.meta.month || month}</span>}
      >
        {!agg ? (
          <Empty description={t('noc.aggUnavailable')} />
        ) : (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space wrap size={8}>
              <Tag color="blue">{t('noc.aggCardTotal')}: {agg.meta.parsed}</Tag>
              <Tag color="orange">{t('noc.aggCardAvgTotal')}: {fmtSec(aggAvgTotalS)}</Tag>
              {agg.wo_stats.missing_dispatch > 0 && (
                <Tag color="red">{t('noc.woMissing')}: {agg.wo_stats.missing_dispatch}</Tag>
              )}
              <Text type="secondary" style={{ fontSize: '0.6875rem' }}>
                {t('noc.aggElapsed', { s: agg.meta.elapsed_s })}
              </Text>
            </Space>
            <Table
              dataSource={agg.tickets}
              columns={aggTicketColumns}
              rowKey="tt_no"
              size="small"
              pagination={{ pageSize: 15, size: 'small', showTotal: (n: number) => t('common.itemsTotal', { n }) }}
              scroll={{ x: 'max-content' }}
              locale={{ emptyText: <Empty description={t('noc.drillEmpty')} /> }}
            />
          </Space>
        )}
      </DraggableClickModal>

      {/* ================================================================
          单 TT 复盘报告视图（里程碑时间轴 / 应做·实做 / 偏离 / 时间归因）
          参考「TT 复盘报告生成（程序化版）」的章节顺序
          ================================================================ */}
      <DraggableClickModal
        open={tlOpen}
        onClose={() => setTlOpen(false)}
        width="90%"
        title={
          <span style={{ color: WH.text }}>
            {t('noc.tlTitle')} · {tlReport?.tt_no || ''}
          </span>
        }
      >
        {tlLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : tlError ? (
          <Alert type="error" showIcon message={tlError} />
        ) : !tlReport?.found ? (
          <Empty description={t('noc.drillEmpty')} />
        ) : (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* 结论条：瓶颈 + 偏离数 */}
            <Alert
              type={
                tlReport.meta.deviation_count > 0
                  ? (tlReport.meta.max_severity === 'critical' ? 'error' : 'warning')
                  : 'success'
              }
              showIcon
              icon={tlReport.meta.deviation_count > 0 ? <WarningOutlined /> : <CheckCircleOutlined />}
              message={
                <Space wrap size={8}>
                  <Text strong>
                    {t('noc.tlTotal')}: {fmtSec(tlReport.time_spent.total_seconds ?? tlReport.meta.total_seconds)}
                  </Text>
                  <Tag color="blue">
                    {t('noc.tlDone')}: {tlReport.meta.done_count}/{tlReport.meta.stage_count}
                  </Tag>
                  <Tag color={tlReport.meta.deviation_count > 0 ? 'red' : 'green'}>
                    {t('noc.devTitle')}: {tlReport.meta.deviation_count}
                  </Tag>
                </Space>
              }
              description={
                <Space direction="vertical" size={4} style={{ marginTop: 4 }}>
                  {tlReport.time_spent.bottleneck_note && (
                    <Text style={{ color: WH.text }}>{tlReport.time_spent.bottleneck_note}</Text>
                  )}
                  {tlReport.time_spent.unaccounted_note && (
                    <Text type="secondary">{tlReport.time_spent.unaccounted_note}</Text>
                  )}
                </Space>
              }
            />

            <Tabs
              activeKey={tlTab}
              onChange={k => setTlTab(k as typeof tlTab)}
              items={[
                {
                  key: 'time',
                  label: t('noc.tlTabTime'),
                  children: (
                    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                      <Table
                        dataSource={tlReport.time_spent.segments}
                        columns={tlTlSegColumns}
                        rowKey="key"
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                        locale={{ emptyText: <Empty description={t('noc.segNoData')} /> }}
                      />

                      {/* NOC / 人工动作及时性 —— 直接回答"人及不及时" */}
                      <div>
                        <Text strong style={{ color: WH.text }}>
                          <ClockCircleOutlined style={{ marginRight: 4 }} />{t('noc.actTitle')}
                        </Text>
                        <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>
                          {t('noc.actSub')}
                        </Text>
                        <Table
                          style={{ marginTop: 8 }}
                          dataSource={tlReport.time_spent.human_actions || []}
                          columns={tlHumanColumns}
                          rowKey="key"
                          size="small"
                          pagination={false}
                          scroll={{ x: 'max-content' }}
                          locale={{ emptyText: <Empty description={t('noc.actNone')} /> }}
                        />
                      </div>

                      {/* 现场处置时间轴（WO 生命周期） */}
                      <div>
                        <Text strong style={{ color: WH.text }}>
                          <ThunderboltOutlined style={{ marginRight: 4 }} />{t('noc.woLifeTitle')}
                        </Text>
                        <Text type="secondary" style={{ fontSize: '0.75rem', marginLeft: 6 }}>
                          {t('noc.woLifeSub')}
                        </Text>
                        {!tlReport.wo_timeline ? (
                          <Alert
                            type="info" showIcon style={{ marginTop: 8 }}
                            message={t('noc.woLifeNone')}
                          />
                        ) : (
                          <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 8 }}>
                            <Space wrap size={8}>
                              <Tag color="blue">{t('noc.woLifeWoNo')}: {tlReport.wo_timeline.wo_no || '-'}</Tag>
                              {tlReport.wo_timeline.creator && (
                                <Tag>{t('noc.tlOperator')}: {tlReport.wo_timeline.creator}</Tag>
                              )}
                              {tlReport.wo_timeline.status && <Tag>{tlReport.wo_timeline.status}</Tag>}
                            </Space>
                            {tlReport.wo_timeline.summary && (
                              <Text style={{ color: WH.text }}>
                                {t('noc.woLifeSummary')}: {tlReport.wo_timeline.summary}
                              </Text>
                            )}
                            {tlReport.wo_timeline.desync && (
                              <Alert type="warning" showIcon message={tlReport.wo_timeline.desync} />
                            )}
                            {tlReport.wo_timeline.travel_mismatch && (
                              <Alert type="warning" showIcon message={t('noc.woLifeTravelMismatch')} />
                            )}
                            <Table
                              dataSource={tlReport.wo_timeline.stages}
                              columns={tlWoStageColumns}
                              rowKey="key"
                              size="small"
                              pagination={false}
                              scroll={{ x: 'max-content' }}
                            />
                          </Space>
                        )}
                      </div>
                    </Space>
                  ),
                },
                {
                  key: 'milestone',
                  label: `${t('noc.tlTabMilestone')} (${tlReport.timeline.filter(n => n.time_present).length}/${tlReport.timeline.length})`,
                  children: (
                    <Table
                      dataSource={tlReport.timeline}
                      columns={tlMilestoneColumns}
                      rowKey="key"
                      size="small"
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                    />
                  ),
                },
                {
                  key: 'actions',
                  label: t('noc.tlTabActions'),
                  children: (
                    <Table
                      dataSource={tlReport.expected_actions}
                      columns={tlActionColumns}
                      rowKey="key"
                      size="small"
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                    />
                  ),
                },
                {
                  key: 'deviation',
                  label: `${t('noc.tlTabDeviation')} (${tlReport.deviations.length})`,
                  children: tlReport.deviations.length === 0 ? (
                    <Alert type="success" showIcon message={t('noc.tlNoDeviations')} />
                  ) : (
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      {tlReport.deviations.map((d, i) => (
                        <CardBase key={`${d.code}-${i}`}>
                          <Space wrap size={8} style={{ marginBottom: 4 }}>
                            <Tag color={sevColor(d.severity)}>{t(sevKey(d.severity))}</Tag>
                            <Text type="secondary">{t(devKindKey(d.kind))}</Text>
                            <Text strong style={{ color: WH.text }}>{d.label}</Text>
                          </Space>
                          <Descriptions size="small" column={1} bordered style={{ marginTop: 4 }}>
                            {d.expected && (
                              <Descriptions.Item label={t('noc.tlDevExpected')}>{d.expected}</Descriptions.Item>
                            )}
                            {d.actual && (
                              <Descriptions.Item label={t('noc.tlDevActual')}>{d.actual}</Descriptions.Item>
                            )}
                            {d.impact && (
                              <Descriptions.Item label={t('noc.tlDevImpact')}>{d.impact}</Descriptions.Item>
                            )}
                          </Descriptions>
                        </CardBase>
                      ))}
                    </Space>
                  ),
                },
                {
                  key: 'chain',
                  label: t('noc.tlTabChain'),
                  children: (
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Button
                        size="small" icon={<NodeIndexOutlined />}
                        onClick={() => openTtDetail(tlReport.tt_no)}
                      >
                        {t('noc.tlViewChain')}
                      </Button>
                      <Text type="secondary" style={{ fontSize: '0.75rem' }}>
                        {t('noc.tlTabChain')}
                      </Text>
                    </Space>
                  ),
                },
              ]}
            />
          </Space>
        )}
      </DraggableClickModal>

      <style>{`
        .noc-row-red { background: rgba(163,45,45,0.06) !important; }
      `}</style>
    </div>
  )
}
