/**
 * TT 复盘报告生成面板 —— 嵌入 EflowQa 页面。
 *
 * 功能：输入 TT 单号 → 调用 /api/eflow-qa/_tt_postmortem/{tt_no} → 展示
 *   - SLA 超期告警条（is_breached / 超期多久 / 超期归因）
 *   - TT 单信息（含 建单人 / FO 接单人 / FO 填报人 / 关单人 等**责任人**）
 *   - ⏱ 时间都花哪了（分段耗时 + 占比 + 责任方 + 瓶颈定位）
 *   - ① 里程碑时间轴（每跳的 时间 / 执行方 / 操作人 / 数据来源；缺失标红、未证实标金）
 *   - ② 该做的动作 · 实际做的动作（契约必需 vs 实际执行，三态：已执行/未证实/未执行）
 *   - ③ 偏离清单（missing 缺失 / late 超时 / out_of_order 越序 / data_conflict 字段冲突）
 *   - ④ 系统判定根因 vs NOC 填写根因（+ 同站历史告警指纹）
 *   - ⑤ WO 派单机制真相（auto_dispatched / rule_stopped / rule_vacuum / no_rule_or_p4）
 *   - ⑥ 阶段时长 + ⑦ 改进建议
 *   - "下载 Markdown 报告"按钮（POST /_tt_postmortem_export_md/{tt_no} → Blob 下载）
 *
 * 不修改 EflowQa 任何已有代码 —— 仅通过 props 传入 onClose（由父级控制显隐）。
 */
import { useCallback, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Input,
  Space,
  Spin,
  Table,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CloseCircleOutlined,
  CloseOutlined,
  DownloadOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'

import { exportTtPostmortemMd, getTtPostmortem } from '../api'
import { useI18n } from '../i18n'
import { evText, nodeTextFromZh, ownerTextFromZh, devTextFromZh } from '../utils/ttVocab'

const { Text, Title } = Typography

type Milestone = {
  key: string
  label: string
  // unknown = 未证实：库中取不到该动作的证据，但也不能断定没做
  actor: 'system' | 'human' | 'unknown'
  time: string | null
  time_present: boolean
  source: string
  raw?: string
  detail?: string
  ok?: boolean
  operator?: string | null
  gap_from_prev_s?: number | null
  // none = 无现场动作证据；wo_steps = 有出发/到场/离场明细
  evidence?: 'none' | 'wo_steps' | null
  wo_steps?: { label: string; operator: string | null; time: string | null; source: string }[]
  wo_creator_kind?: string | null
}

type ExpectedAction = {
  key: string
  label: string
  actor: string
  required: boolean
  done: boolean
  // done=已执行 / unproven=未证实 / missing=未执行
  status?: 'done' | 'unproven' | 'missing'
  evidence?: string | null
  time: string | null
  operator?: string | null
  detail?: string
}

type Deviation = {
  code: string
  kind: 'missing' | 'late' | 'out_of_order' | 'data_conflict'
  severity: 'critical' | 'major' | 'minor'
  label: string
  expected: string
  actual: string
  impact: string
}

type SiteHistoryRow = {
  tt_no: string
  alarmcode: string
  codename: string
  reason_type: string
  raised: string | null
  cleared: string | null
  is_self: boolean
}

type TimeSegment = {
  key: string
  label: string
  // 阶段短名：现场响应等待 / 建单时延 / 接单等待 / 告警清除 …
  phase?: string
  phase_label?: string
  owner: string
  owner_kind: string
  seconds: number
  pct: number | null
  from: string | null
  to: string | null
  threshold_s: number | null
  over_threshold: boolean
  over_by_s: number | null
}

type Sla = {
  status: string | null
  is_breached: boolean
  total_s: number | null
  total_text: string | null
  deadline: string | null
  finished_at: string | null
  over_seconds: number | null
  over_source: string | null
  over_text: string | null
  wait_in_hand_s: number | null
  cause: string
}

type People = {
  creator?: string | null
  creator_kind?: string | null
  fo_acceptor?: string | null
  fo_processer?: string | null
  confirmer?: string | null
  last_processer?: string | null
  last_processer_group?: string | null
  wo_no?: string | null
  wo_creator?: string | null
  wo_current_handler?: string | null
  wo_people?: { step: string; operator: string | null; time: string | null; source: string }[]
  by_action?: { action: string; operator: string | null; time: string | null; actor: string; done: boolean }[]
}

type DispatchRuleEval = {
  rule_name: string | null
  status: string | null
  priority: number | null
  description: string | null
  update_time: string | null
  wants_keys: string[]
  miss_keys: string[]
  target: string
  verdict: 'matched' | 'blocked_by_status' | 'not_applicable' | 'unknown_scope'
  why: string
}

type DispatchAnalysis = {
  trigger_step: string
  step_meaning: string
  signature: Record<string, boolean>
  site_subtype: string | null
  alarm_name: string | null
  alarm_code: string | null
  has_wo: boolean
  rules_at_step: DispatchRuleEval[]
  candidate_rules: (string | null)[]
  blocked_rules: {
    rule_name: string | null; status: string | null
    description: string | null; update_time: string | null; priority: number | null
  }[]
  active_candidate_rules: (string | null)[]
  wo_active_rules: (string | null)[]
  other_active_rules: { rule_name: string | null; target: string }[]
  manual_by_design: boolean
  manual_rules: { rule_name: string | null; status: string | null; description: string | null }[]
  wo_capable_active_rules: { rule_name: string | null; wants_keys: string[]; applies: boolean }[]
  fallback_rules: {
    rule_name: string | null; priority: number | null
    status: string | null; description: string | null
  }[]
  overall: string
  conclusion: string
  caveat: string
}

type Report = {
  tt_no: string
  found: boolean
  message?: string
  site?: {
    site_id: string; site_name: string; site_subtype: string | null
    site_class?: string | null; vip_site?: string | null; hub_site?: string | null
    region?: string | null; ne_name?: string | null; moc?: string | null
    site_outage?: string | null
  }
  ticket?: {
    title?: string | null; ticket_type?: string | null
    ticket_severity?: string | null; alarm_severity?: string | null
    alarm_code?: string | null; alarm_name?: string | null
    status?: string | null; domain?: string | null; tt_source?: string | null
    sla_status?: string | null; sla_deadline?: string | null
    fault_duration_time?: string | null; impacted_service?: string | null
    alarm_occur_time?: string | null; alarm_clear_time?: string | null
    created_time?: string | null; last_modified_time?: string | null
    wo_no?: string | null
  }
  people?: People
  sla?: Sla
  time_spent?: {
    total_seconds: number | null
    // 统计窗口：终点取所有已知活动的最晚时间（含现场动作）
    window?: { start?: string | null; end?: string | null }
    segments: TimeSegment[]
    segments_sum_s: number | null
    unaccounted_s: number | null
    unaccounted_note?: string | null
    bottleneck?: TimeSegment | null
    bottleneck_note?: string
    over_threshold_count?: number
  }
  noc_filled?: any
  system_judged?: any
  consistency?: boolean | null
  mismatch_type?: string
  confidence?: 'high' | 'medium' | 'low'
  note?: string
  history_match?: string
  timeline?: Milestone[]
  expected_actions?: ExpectedAction[]
  missing_actions?: { key: string; label: string; actor: string; reason: string }[]
  deviations?: Deviation[]
  site_history?: SiteHistoryRow[]
  timeline_meta?: {
    window?: { start?: string; end?: string }
    total_seconds?: number | null
    stage_count?: number
    done_count?: number
    deviation_count?: number
    max_severity?: string | null
  }
  dispatch_path?: {
    category: string
    explanation: string
    wo_no?: string
    wo_creator?: string
    fo_assign_to?: string
  }
  dispatch_analysis?: DispatchAnalysis
  /** 承接方：IPT（第三方，按设计不建 WO）/ ZTE（自维） */
  dispatch_owner?: string
  /** 归属判定的依据（悬浮说明"为什么判成 IPT/ZTE"） */
  owner_detail?: {
    owner?: string
    owner_label?: string
    is_third_party?: boolean
    evidence?: string[]
  }
  /** 告警码 + 告警名（告警 ID 看不出是什么告警，悬浮/并列显示名字） */
  alarm_code?: string | null
  alarm_name?: string | null
  assignment?: {
    channel?: string | null
    channel_rules?: { rule_name: string | null; priority: number | null }[]
    channel_note?: string
    // 建单环节（TT 层）
    tt_create_assign_to?: string | null
    tt_create_assignee_group?: string | null
    tt_create_operator_group?: string | null
    tt_next_status?: string | null
    tt_current_handler?: string | null
    create_unassigned?: boolean
    create_note?: string | null
    // 工单层（WO）—— 真正落到人的地方
    wo_no?: string | null
    wo_current_handler?: string | null
    wo_create_assign_to?: string | null
    wo_assignee_group?: string | null
    // 结论
    assigned_persons?: string[]
    assigned_groups?: string[]
    effective_scope?: 'person' | 'group' | 'none'
    conclusion?: string
    unassigned?: boolean
    group_pools?: {
      stage: string; rule_name: string | null; priority: number | null
      handler_name: string | null; handler_id: string | null; description: string | null
    }[]
  }
  rules_snapshot?: {
    down_alarm_codes_active: string[]
    down_alarm_codes_stopped: string[]
    active_rule_count: number
    stopped_rule_count: number
  }
  durations?: {
    create_to_accept_seconds?: number | null
    accept_to_process_seconds?: number | null
    process_to_confirm_seconds?: number | null
    total_seconds?: number | null
  }
  suggested_actions?: string[]
}

const CATEGORY_COLOR: Record<string, string> = {
  auto_dispatched: 'green',
  rule_stopped: 'red',
  rule_vacuum: 'orange',
  no_rule_or_p4: 'default',
}

/** 派单分类 → 文案键。显式列出而非用前缀拼键：动态拼键会被
 *  check:i18n 读成截断的键名，且键不存在时 t() 原样返回、界面露出键名。
    返回空串表示这个词后端没枚举过，调用方回落原始值。 */
const categoryLabelKey = (v?: string): string => {
  switch (v) {
    case 'auto_dispatched': return 'ttPm.cat.auto_dispatched'
    case 'rule_stopped': return 'ttPm.cat.rule_stopped'
    case 'rule_vacuum': return 'ttPm.cat.rule_vacuum'
    case 'no_rule_or_p4': return 'ttPm.cat.no_rule_or_p4'
    default: return ''
  }
}

// 派单归因结论（dispatch_analysis.overall）→ 颜色 / 文案
const DISPATCH_OVERALL_COLOR: Record<string, string> = {
  auto_dispatched: 'green',
  manual_by_design: 'blue',
  no_wo_by_design_multi: 'blue',
  routed_to_other_system: 'cyan',
  rule_should_have_fired: 'red',
  no_active_rule_matched: 'orange',
  rule_vacuum: 'orange',
  ambiguous: 'gold',
}

const dispatchOverallLabelKey = (v?: string): string => {
  switch (v) {
    case 'auto_dispatched': return 'ttPm.overall.auto_dispatched'
    case 'manual_by_design': return 'ttPm.overall.manual_by_design'
    case 'no_wo_by_design_multi': return 'ttPm.overall.no_wo_by_design_multi'
    case 'routed_to_other_system': return 'ttPm.overall.routed_to_other_system'
    case 'rule_should_have_fired': return 'ttPm.overall.rule_should_have_fired'
    case 'no_active_rule_matched': return 'ttPm.overall.no_active_rule_matched'
    case 'rule_vacuum': return 'ttPm.overall.rule_vacuum'
    case 'ambiguous': return 'ttPm.overall.ambiguous'
    default: return ''
  }
}

// 单条规则的适用性判定 → 颜色 / 文案
const VERDICT_COLOR: Record<string, string> = {
  matched: 'green',
  blocked_by_status: 'red',
  not_applicable: 'default',
  unknown_scope: 'gold',
}

const verdictLabelKey = (v?: string): string => {
  switch (v) {
    case 'matched': return 'ttPm.verdict.matched'
    case 'blocked_by_status': return 'ttPm.verdict.blocked_by_status'
    case 'not_applicable': return 'ttPm.verdict.not_applicable'
    case 'unknown_scope': return 'ttPm.verdict.unknown_scope'
    default: return ''
  }
}

// 偏离严重度 → antd Tag 颜色（critical 红 / major 橙 / minor 金）
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  major: 'orange',
  minor: 'gold',
}

const kindLabelKey = (v?: string): string => {
  switch (v) {
    case 'missing': return 'ttPm.kind.missing'
    case 'late': return 'ttPm.kind.late'
    case 'out_of_order': return 'ttPm.kind.out_of_order'
    case 'data_conflict': return 'ttPm.kind.data_conflict'
    default: return ''
  }
}

/** 置信度枚举（后端只发 high / medium / low 三值） */
const confLabelKey = (v?: string): string => {
  switch (v) {
    case 'high': return 'ttPm.conf.high'
    case 'medium': return 'ttPm.conf.medium'
    case 'low': return 'ttPm.conf.low'
    default: return ''
  }
}

/* 告警链路关联方式与 NOC 看板同一套后端取值，直接复用 noc.linkage.* 词条，
   不再造一份键，免得两处译名日后走偏。 */
const linkageLabelKey = (v?: string): string => {
  switch (v) {
    case 'exact': return 'noc.linkage.exact'
    case 'site_fallback': return 'noc.linkage.site_fallback'
    case 'site_reason_fallback': return 'noc.linkage.site_reason_fallback'
    case 'site_fallback_unrelated': return 'noc.linkage.site_fallback_unrelated'
    default: return ''
  }
}

/** 秒 → 人读时长；缺失返回 '-'（不要用 0 冒充"瞬时"）。
    单位走 i18n，所以 t 由调用方注入；组件内用同名 fmtGap 包装，调用点不用改。 */
type TFn = (key: string, params?: Record<string, string | number>) => string
function fmtGapT(t: TFn, sec?: number | null): string {
  if (sec == null) return '-'
  if (sec < 60) return t('ttPm.durSec', { n: sec })
  if (sec < 3600) return t('ttPm.durMin', { n: Math.round(sec / 60) })
  if (sec < 86400) return t('ttPm.durHour', { n: (sec / 3600).toFixed(2) })
  return t('ttPm.durDay', { n: (sec / 86400).toFixed(2) })
}

/** 阶段（_PHASE_LABEL 的 9 个 key）→ 文案键 */
const phaseLabelKey = (v?: string): string => {
  switch (v) {
    case 'detect': return 'ttPm.phase.detect'
    case 'assign': return 'ttPm.phase.assign'
    case 'dispatch': return 'ttPm.phase.dispatch'
    case 'onsite_wait': return 'ttPm.phase.onsite_wait'
    case 'onsite_work': return 'ttPm.phase.onsite_work'
    case 'clear': return 'ttPm.phase.clear'
    case 'handle': return 'ttPm.phase.handle'
    case 'close': return 'ttPm.phase.close'
    case 'other': return 'ttPm.phase.other'
    default: return ''
  }
}

/* 里程碑全名 / 分段短名 / 责任方的中文词表已抽到 utils/ttVocab.ts ——
   noc_analyst 的概览与下钻显示的是同一批后端中文，两边各写一份必然漂移。 */

export default function TtPostmortemPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const fmtGap = (sec?: number | null) => fmtGapT(t, sec)
  /** 里程碑名：后端给的是中文硬编码。只有原文正好是标准里程碑名才替换成当前语言，
      「现场·出发」这类带子类型的标签保持原样（替换会丢信息）。 */
  const nodeLabel = (raw?: string | null) => nodeTextFromZh(t, raw)
  const phaseLabel = (phase?: string | null, raw?: string | null) => {
    const k = phaseLabelKey(phase || undefined)
    return k ? t(k) : raw || ''
  }
  const ownerLabel = (v?: string | null) => ownerTextFromZh(t, v)
  const confLabel = (v?: string | null) => {
    const k = confLabelKey(v || undefined)
    return k ? t(k) : v || '-'
  }
  const lnkLabel = (v?: string | null) => {
    const k = linkageLabelKey(v || undefined)
    return k ? t(k) : v || '-'
  }
  /** 分段名按 key 用当前语言重建。后端 key 形如 "{phase}:{目标事件}"，
   *  起点 = 时间上紧邻的前一段的目标事件（首段起点固定为告警发生）。
   *  注意：表格里段是按耗时排序展示的，数组相邻 ≠ 时间相邻，必须按 from 重排。 */
  const segLabel = (r: TimeSegment) => {
    const segs = report?.time_spent?.segments ?? []
    const chrono = [...segs].sort((a, b) => String(a.from || '').localeCompare(String(b.from || '')))
    const idx = chrono.findIndex(s => s.key === r.key && s.from === r.from)
    const parts = r.key.split(':')
    const toKey = parts[1] || ''
    const fromKey = idx <= 0 ? 'alarm_occur' : (chrono[idx - 1]?.key.split(':')[1] || '')
    /* 任何一端认不出来就返回空串，让调用方回落到后端给的原文标签，
       免得拼出「A → 」这种半截文案。 */
    if (idx < 0 || !toKey || !fromKey) return ''
    const fromText = evText(t, fromKey, 'short')
    const toText = toKey === 'tail' ? t('ttPm.short.tail') : evText(t, toKey, 'short')
    if (!fromText || !toText) return ''
    return `${fromText} → ${toText}`
  }
  const [ttNo, setTtNo] = useState('')
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')

  const run = useCallback(async () => {
    const clean = ttNo.trim().toUpperCase()
    if (!clean) return
    setLoading(true)
    setError('')
    try {
      const r = await getTtPostmortem(clean)
      setReport(r.data as Report)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || t('ttPm.queryFailed'))
      setReport(null)
    } finally {
      setLoading(false)
    }
  }, [ttNo])

  const exportMd = useCallback(async () => {
    if (!report?.found) return
    setExporting(true)
    try {
      const r = await exportTtPostmortemMd(report.tt_no)
      const blob = new Blob([r.data.content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = r.data.filename
      a.click()
      URL.revokeObjectURL(url)
      message.success(t('ttPm.downloaded', { f: r.data.filename }))
    } catch (e: any) {
      message.error(t('ttPm.downloadFailed', { msg: e?.response?.data?.detail || e?.message }))
    } finally {
      setExporting(false)
    }
  }, [report, t])

  /* ⑥ 阶段时长用的格式化与 fmtGap 差一处：分钟保留 1 位小数。
     保持原样输出，避免借 i18n 之名悄悄改了中文模式的数字。 */
  const fmtSec = (s?: number | null) => {
    if (s == null) return '-'
    if (s < 60) return t('ttPm.durSec', { n: s })
    if (s < 3600) return t('ttPm.durMin', { n: (s / 60).toFixed(1) })
    return t('ttPm.durHour', { n: (s / 3600).toFixed(2) })
  }

  /* 「Handled by」这一格要同时回答两件事：承接方分类（ZTE 自维 / IPT 第三方）
     与工单实际落到了谁手里。只有分类标签时，有 WO 的单看起来像"没人接"。
     两个值都只读后端已解析好的字段，前端不另做归属判断：
       - wo_no   → `ticket.wo_no`（build_tt_postmortem 的 ticket 块）
       - 处理人  → WO 层解析出的 `assignment.assigned_persons`（已去重、带工号）；
                   时间轴子视图构建失败时退回 `eflow_wo.current_handler` 原文 */
  const woNo = report?.ticket?.wo_no || null
  const woWho = (report?.assignment?.assigned_persons || []).join(', ')
    || report?.people?.wo_current_handler || ''

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#722ed1' }} />
          <span>{t('ttPm.title')}</span>
        </Space>
      }
      width={Math.min(960, typeof window !== 'undefined' ? window.innerWidth - 40 : 960)}
      destroyOnClose
      extra={
        <Button icon={<CloseOutlined />} onClick={onClose} type="text" />
      }
    >
      <Space.Compact style={{ width: '100%' }}>
        <Input
          placeholder={t('ttPm.placeholder')}
          value={ttNo}
          onChange={e => setTtNo(e.target.value)}
          onPressEnter={run}
          allowClear
          size="large"
        />
        <Button type="primary" size="large" icon={<ThunderboltOutlined />} loading={loading} onClick={run}>
          {t('ttPm.generate')}
        </Button>
      </Space.Compact>

      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} />}

      <Spin spinning={loading} style={{ marginTop: 12 }}>
        {report && !report.found && (
          <Empty description={report.message || t('ttPm.notFound')} />
        )}

        {report && report.found && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* SLA 超期告警条：最重要的复盘结论之一，放在最上面 */}
            {report.sla && (
              <Alert
                type={report.sla.is_breached ? 'error' : 'success'}
                showIcon
                icon={report.sla.is_breached ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
                message={
                  <Space size={8} wrap>
                    <Text strong>SLA {report.sla.status || '-'}</Text>
                    {report.sla.is_breached
                      ? <Tag color="red">{t('ttPm.slaBreached', { d: fmtGap(report.sla.over_seconds) })}</Tag>
                      : <Tag color="green">{t('ttPm.slaOnTime')}</Tag>}
                    {report.sla.total_text && <Tag>{t('ttPm.slaDuration')} {report.sla.total_text}</Tag>}
                    {report.sla.deadline && <Tag>{t('ttPm.slaDeadline')} {report.sla.deadline}</Tag>}
                    {report.sla.over_text && <Text type="secondary">{t('ttPm.slaMargin')} {report.sla.over_text}</Text>}
                  </Space>
                }
                description={report.sla.cause}
              />
            )}

            {/* TT 单信息（含责任人） */}
            <Card size="small" title={
              <Space>
                <Text strong>{report.tt_no}</Text>
                <Tag color="blue">{report.ticket?.ticket_severity}</Tag>
                <Tag>{report.ticket?.status}</Tag>
                <Text type="secondary">{report.site?.site_name}</Text>
                {report.site?.site_subtype && <Tag color="cyan">{report.site.site_subtype}</Tag>}
                {report.site?.vip_site === 'Yes' && <Tag color="gold">VIP</Tag>}
                {report.site?.hub_site === 'Yes' && <Tag color="purple">Hub</Tag>}
              </Space>
            }
              extra={
                <Button icon={<DownloadOutlined />} onClick={exportMd} loading={exporting} size="small">
                  {t('ttPm.downloadMd')}
                </Button>
              }
            >
              {report.ticket?.title && (
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">{t('ttPm.fieldTitle')}</Text><Text strong>{report.ticket.title.trim()}</Text>
                </div>
              )}
              <Descriptions size="small" column={3} bordered>
                <Descriptions.Item label={t('ttPm.fAlarmCode')}>{report.ticket?.alarm_code} {report.ticket?.alarm_name ? `(${report.ticket.alarm_name})` : ''}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fAlarmSeverity')}>{report.ticket?.alarm_severity || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fReasonType')}>{report.system_judged?.reason_type || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fAlarmOccur')}>{report.ticket?.alarm_occur_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fAlarmClear')}>{report.ticket?.alarm_clear_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fFaultDuration')}>{report.ticket?.fault_duration_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fCreated')}>{report.ticket?.created_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fLastModified')}>{report.ticket?.last_modified_time || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fImpactedService')}>{report.ticket?.impacted_service || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fSiteClass')}>{report.site?.site_class || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fRegion')}>{report.site?.region || '-'}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fWoNo')}>{report.ticket?.wo_no || <Text type="danger">{t('ttPm.none')}</Text>}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.fOwner')} span={2}>
                  <Space size={6} wrap>
                    <Tag color={report.dispatch_owner === 'IPT' ? 'purple' : 'blue'}>
                      {report.dispatch_owner === 'IPT' ? t('ttPm.ownerIpt') : t('ttPm.ownerZte')}
                    </Tag>
                    {/* 有 WO：直接说清落到谁手里（这一格叫 Handled by，光有分类看不出有人在做） */}
                    {woNo ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {woWho
                          ? t('ttPm.ownerWoDispatched', { no: woNo, who: woWho })
                          : t('ttPm.ownerWoUnassigned', { no: woNo })}
                      </Text>
                    ) : report.dispatch_owner === 'IPT' ? (
                      /* IPT 单按设计不建 WO，说明清楚，避免被误读成"漏派单" */
                      <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.ownerIptNoWo')}</Text>
                    ) : (
                      <Text type="danger" style={{ fontSize: 12 }}>{t('ttPm.ownerZteNoWo')}</Text>
                    )}
                    {(report.owner_detail?.evidence?.length ?? 0) > 0 && (
                      <Tooltip title={
                        <div>
                          {t('ttPm.ownerWhy')}
                          <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                            {report.owner_detail!.evidence!.map((e, i) => <li key={i}>{e}</li>)}
                          </ul>
                        </div>
                      }>
                        <QuestionCircleOutlined style={{ cursor: 'help', opacity: 0.65 }} />
                      </Tooltip>
                    )}
                  </Space>
                </Descriptions.Item>
              </Descriptions>

              {/* 责任人：谁建的 / 谁接的 / 谁处理的 / 谁关的 */}
              {report.people && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.owners')}</Text>
                  <Descriptions size="small" column={3} bordered style={{ marginTop: 4 }}>
                    <Descriptions.Item label={t('ttPm.pCreator')}>
                      {report.people.creator || '-'}
                      <Tag style={{ marginLeft: 4 }} color={report.people.creator_kind === '系统自动' ? 'default' : 'blue'}>
                        {report.people.creator_kind === '系统自动'
                          ? t('ttPm.auto')
                          : report.people.creator_kind === '人工'
                            ? t('ttPm.actor.human')
                            : report.people.creator_kind}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pFoAcceptor')}>{report.people.fo_acceptor || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pFoProcesser')}>{report.people.fo_processer || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pConfirmer')}>{report.people.confirmer || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pLastHandler')}>{report.people.last_processer || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pHandlerGroup')}>{report.people.last_processer_group || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pWoCreator')}>{report.people.wo_creator || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.pWoHandler')}>{report.people.wo_current_handler || '-'}</Descriptions.Item>
                  </Descriptions>
                </div>
              )}

              {/* WO 现场动作责任人（有 WO 才有） */}
              {report.people?.wo_people && report.people.wo_people.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.pOnsiteOwners')}</Text>
                  <Table
                    size="small"
                    rowKey={(r) => `${r.step}-${r.time}-${r.operator}`}
                    style={{ marginTop: 4 }}
                    pagination={false}
                    dataSource={report.people.wo_people}
                    columns={[
                      { title: t('ttPm.colStep'), dataIndex: 'step', width: 110 },
                      { title: t('ttPm.colTime'), dataIndex: 'time', width: 175, render: (v: string | null) => v || '-' },
                      { title: t('ttPm.colOperator'), dataIndex: 'operator', render: (v: string | null) => v || '-' },
                      { title: t('ttPm.colSource'), dataIndex: 'source', width: 200, render: (v: string) => <Text type="secondary" style={{ fontSize: 11 }}>{v}</Text> },
                    ]}
                  />
                </div>
              )}
            </Card>

            {/* 时间都花哪了 —— 复盘重点 */}
            {report.time_spent?.segments && report.time_spent.segments.length > 0 && (
              <Card size="small" title={
                <Space>
                  <Text strong>{t('ttPm.segTitle')}</Text>
                  <Tag color="blue">{t('ttPm.totalElapsed')} {fmtGap(report.time_spent.total_seconds)}</Tag>
                  {(report.time_spent.over_threshold_count ?? 0) > 0 && (
                    <Tag color="red">{t('ttPm.overThrCount', { n: report.time_spent.over_threshold_count ?? 0 })}</Tag>
                  )}
                </Space>
              }>
                <Table
                  size="small"
                  rowKey="key"
                  pagination={false}
                  dataSource={report.time_spent.segments}
                  columns={[
                    {
                      title: t('ttPm.colPhase'), dataIndex: 'label',
                      render: (v: string, r: TimeSegment) => (
                        <Space size={4} wrap>
                          {r.key === report.time_spent?.bottleneck?.key && <Tag color="red">{t('ttPm.bottleneck')}</Tag>}
                          {r.phase_label && <Tag color="geekblue">{phaseLabel(r.phase, r.phase_label)}</Tag>}
                          <Text strong={r.key === report.time_spent?.bottleneck?.key}>{segLabel(r) || v}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: t('ttPm.colElapsed'), dataIndex: 'seconds', width: 120,
                      defaultSortOrder: 'descend',
                      sorter: (a: TimeSegment, b: TimeSegment) => a.seconds - b.seconds,
                      render: (v: number) => <Text strong>{fmtGap(v)}</Text>,
                    },
                    {
                      title: t('ttPm.colPct'), dataIndex: 'pct', width: 150,
                      render: (v: number | null) => (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <div style={{
                            height: 8, borderRadius: 4, background: '#1677ff',
                            width: `${Math.max(2, Math.min(100, v ?? 0))}%`, maxWidth: 80,
                          }} />
                          <Text type="secondary" style={{ fontSize: 12 }}>{v ?? 0}%</Text>
                        </div>
                      ),
                    },
                    {
                      title: t('ttPm.colOwner'), dataIndex: 'owner', width: 200,
                      render: (v: string) => v ? <Tag color={v === '系统/流程' ? 'default' : 'blue'}>{ownerLabel(v)}</Tag> : '-',
                    },
                    {
                      title: t('ttPm.colOverThr'), dataIndex: 'over_threshold', width: 150,
                      render: (v: boolean, r: TimeSegment) => (
                        v
                          ? <Tag color="red">{t('ttPm.overBy', { d: fmtGap(r.over_by_s) })}</Tag>
                          : (r.threshold_s ? <Tag color="green">{t('ttPm.normal')}</Tag> : <Text type="secondary">—</Text>)
                      ),
                    },
                  ]}
                />
                {report.time_spent.window?.start && (
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
                    {t('ttPm.statWindow', { a: report.time_spent.window?.start || '-', b: report.time_spent.window?.end || '-' })}
                  </Text>
                )}
                {report.time_spent.bottleneck_note && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="warning"
                    showIcon
                    message={t('ttPm.bottleneckNote')}
                    description={report.time_spent.bottleneck_note}
                  />
                )}
                {report.time_spent.unaccounted_note && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="info"
                    showIcon
                    message={report.time_spent.unaccounted_note}
                  />
                )}
              </Card>
            )}

            {/* 里程碑时间轴 */}
            {report.timeline && report.timeline.length > 0 && (
              <Card size="small" title={t('ttPm.tlTitle', { d: report.timeline_meta?.done_count ?? 0, s: report.timeline_meta?.stage_count ?? 0 })}>
                <Timeline
                  items={report.timeline.map(m => {
                    const missing = !m.time_present
                    // 未证实（unknown）用金色问号，区别于"缺失"（红）与"有证据"（蓝/绿）
                    const unproven = m.actor === 'unknown'
                    return {
                      color: missing ? (unproven ? 'gold' : 'red') : m.actor === 'human' ? 'blue' : 'green',
                      dot: missing
                        ? (unproven ? <QuestionCircleOutlined /> : <CloseCircleOutlined />)
                        : undefined,
                      children: (
                        <div style={{ opacity: missing ? 0.85 : 1 }}>
                          <Space size={6} wrap>
                            <Text strong={!missing} delete={missing}>{nodeLabel(m.label)}</Text>
                            <Tag color={m.actor === 'human' ? 'blue' : unproven ? 'gold' : 'green'}>
                              {m.actor === 'human' ? t('ttPm.actor.human') : unproven ? t('ttPm.actor.unknown') : t('ttPm.actor.system')}
                            </Tag>
                            <Text code style={{ fontSize: 12 }}>{m.time || t('ttPm.missingParen')}</Text>
                            {m.gap_from_prev_s != null && (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {t('ttPm.gapFromPrev', { d: fmtGap(m.gap_from_prev_s) })}
                              </Text>
                            )}
                            {m.operator && <Tag>{m.operator}</Tag>}
                          </Space>
                          {m.detail && (
                            <div style={{ fontSize: 12, color: 'var(--wh-text-2, #666)', marginTop: 2 }}>
                              {m.detail}
                            </div>
                          )}
                          {!missing && (
                            <div style={{ fontSize: 11, color: 'var(--wh-text-3, #999)' }}>
                              {t('ttPm.sourceOf')}{m.source}
                              {m.raw && (
                                <Tooltip title={<pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxWidth: 520 }}>{m.raw}</pre>}>
                                  <Text type="secondary" style={{ fontSize: 11, marginLeft: 6, cursor: 'help' }}>
                                    {t('ttPm.raw')}
                                  </Text>
                                </Tooltip>
                              )}
                            </div>
                          )}
                        </div>
                      ),
                    }
                  })}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('ttPm.tlWindow', { a: report.timeline_meta?.window?.start || '-', b: report.timeline_meta?.window?.end || '-', c: fmtGap(report.timeline_meta?.total_seconds) })}
                </Text>
              </Card>
            )}

            {/* 应做 vs 实做 */}
            {report.expected_actions && report.expected_actions.length > 0 && (
              <Card size="small" title={t('ttPm.actTitle')}>
                <Table
                  size="small"
                  rowKey="key"
                  pagination={false}
                  dataSource={report.expected_actions}
                  columns={[
                    { title: t('ttPm.colMilestone'), dataIndex: 'label', width: 130, render: (v: string) => nodeLabel(v) },
                    {
                      title: t('ttPm.colContract'), dataIndex: 'required', width: 70,
                      render: (v: boolean) => <Tag color={v ? 'purple' : 'default'}>{v ? t('ttPm.required') : t('ttPm.conditional')}</Tag>,
                    },
                    {
                      title: t('ttPm.colShould'), dataIndex: 'key', width: 80,
                      render: () => <Tag color="blue">{t('ttPm.shouldRun')}</Tag>,
                    },
                    {
                      title: t('ttPm.colActual'), dataIndex: 'status', width: 104,
                      render: (v: ExpectedAction['status'], r: ExpectedAction) => {
                        const st = v || (r.done ? 'done' : 'missing')
                        if (st === 'done') return <Tag color="green" icon={<CheckCircleOutlined />}>{t('ttPm.done')}</Tag>
                        if (st === 'unproven') {
                          return (
                            <Tooltip title={t('ttPm.unprovenTip')}>
                              <Tag color="gold" icon={<QuestionCircleOutlined />}>{t('ttPm.unproven')}</Tag>
                            </Tooltip>
                          )
                        }
                        return <Tag color="red" icon={<CloseCircleOutlined />}>{t('ttPm.notDone')}</Tag>
                      },
                    },
                    { title: t('ttPm.colTime'), dataIndex: 'time', width: 165, render: (v: string | null) => v || <Text type="danger">-</Text> },
                    { title: t('ttPm.colOperator'), dataIndex: 'operator', width: 170, render: (v: string | null) => v || '-' },
                  ]}
                />
                {report.expected_actions?.some(a => (a.status || (a.done ? 'done' : 'missing')) === 'unproven') && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="warning"
                    showIcon
                    message={t('ttPm.unprovenAlert')}
                    description={
                      <Text style={{ fontSize: 12 }}>
                        {t('ttPm.unprovenDesc')} <Text code>fe_robot</Text>
                        {t('ttPm.unprovenDesc2')}<Text strong>{t('ttPm.unprovenDesc3')}</Text>。
                      </Text>
                    }
                  />
                )}
                {report.missing_actions && report.missing_actions.length > 0 && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="error"
                    showIcon
                    message={t('ttPm.missingCount', { n: report.missing_actions.length })}
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {report.missing_actions.map(m => (
                          <li key={m.key}><Text strong>{nodeLabel(m.label)}</Text>：{m.reason}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </Card>
            )}

            {/* 偏离清单 */}
            <Card size="small" title={
              <Space>
                <Text strong>{t('ttPm.devTitle')}</Text>
                {report.deviations && report.deviations.length > 0 && (
                  <Tag color="red">{t('ttPm.devItems', { n: report.deviations.length })}</Tag>
                )}
              </Space>
            }>
              {report.deviations && report.deviations.length > 0 ? (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  {report.deviations.map(d => (
                    <div key={d.code} style={{
                      borderLeft: `3px solid ${d.severity === 'critical' ? '#ff4d4f' : d.severity === 'major' ? '#fa8c16' : '#faad14'}`,
                      paddingLeft: 8,
                    }}>
                      <Space size={6} wrap>
                        <Tag color={SEVERITY_COLOR[d.severity]}>{d.severity.toUpperCase()}</Tag>
                        <Tag>{kindLabelKey(d.kind) ? t(kindLabelKey(d.kind)) : d.kind}</Tag>
                        <Text strong>{devTextFromZh(t, d.label)}</Text>
                      </Space>
                      <div style={{ fontSize: 12, marginTop: 2 }}>
                        <Text type="secondary">{t('ttPm.devExpected')}</Text>{d.expected}
                      </div>
                      <div style={{ fontSize: 12 }}>
                        <Text type="secondary">{t('ttPm.devActual')}</Text><Text type="danger">{d.actual}</Text>
                      </div>
                      <div style={{ fontSize: 12 }}>
                        <Text type="secondary">{t('ttPm.devImpact')}</Text>{d.impact}
                      </div>
                    </div>
                  ))}
                </Space>
              ) : (
                <Alert type="success" showIcon message={t('ttPm.devNone')} />
              )}
            </Card>

            {/* 一致性判定 */}
            <Card size="small" title={
              <Space>
                <Text strong>{t('ttPm.consTitle')}</Text>
                {report.consistency === false && (
                  <Tooltip title={report.note}>
                    <Tag color="red" icon={<ExclamationCircleOutlined />}>{report.mismatch_type}</Tag>
                  </Tooltip>
                )}
                {report.consistency === true && (
                  <Tag color="green" icon={<CheckCircleOutlined />}>{t('ttPm.consistent')}</Tag>
                )}
                {report.consistency == null && <Tag color="default">{t('ttPm.needReview')}</Tag>}
                <Tag>{t('ttPm.confidence', { c: confLabel(report.confidence) })}</Tag>
              </Space>
            }>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label={t('ttPm.nocFilled')}>{report.noc_filled?.root_cause} / {report.noc_filled?.sub_root_cause}</Descriptions.Item>
                {/* 旧写法把插值放在字符串属性里，花括号不展开、界面会显示字面量；改为 JSX 表达式。 */}
                <Descriptions.Item label={t('ttPm.sysJudged', { linkage: lnkLabel(report.system_judged?.linkage) })}>
                  {report.system_judged?.fault_domain}{t('ttPm.sysBasis', { b: report.system_judged?.basis || '-' })}
                </Descriptions.Item>
                {report.history_match && (
                  <Descriptions.Item label={t('ttPm.historyMatch')}>{report.history_match}</Descriptions.Item>
                )}
              </Descriptions>

              {/* 同站历史告警指纹：判定「反复同源故障」的关键佐证 */}
              {report.site_history && report.site_history.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('ttPm.siteHistTitle')}
                  </Text>
                  <Table
                    size="small"
                    rowKey={(r) => `${r.tt_no}-${r.alarmcode}-${r.raised}`}
                    style={{ marginTop: 6 }}
                    pagination={false}
                    dataSource={report.site_history}
                    columns={[
                      {
                        title: 'TT', dataIndex: 'tt_no', width: 165,
                        render: (v: string, r: SiteHistoryRow) => (
                          <Space size={4}>
                            <Text code style={{ fontSize: 12 }}>{v}</Text>
                            {r.is_self && <Tag color="blue">{t('ttPm.thisTicket')}</Tag>}
                          </Space>
                        ),
                      },
                      { title: t('ttPm.fAlarmCode'), dataIndex: 'alarmcode', width: 80 },
                      { title: 'codename', dataIndex: 'codename', width: 150 },
                      {
                        title: 'reason_type', dataIndex: 'reason_type', width: 100,
                        render: (v: string) => <Tag color={v === 'TRM' ? 'orange' : 'default'}>{v}</Tag>,
                      },
                      { title: t('ttPm.colRaised'), dataIndex: 'raised', width: 165 },
                      { title: t('ttPm.colCleared'), dataIndex: 'cleared', width: 165 },
                    ]}
                  />
                </div>
              )}
            </Card>

            {/* 派单机制真相 */}
            <Card size="small" title={t('ttPm.dispatchTitle')}>
              <Space direction="vertical" style={{ width: '100%' }} size={6}>
                <Space>
                  <Text>{t('ttPm.category')}</Text>
                  <Tag color={CATEGORY_COLOR[report.dispatch_path?.category || 'default']}>
                    {(() => { const k = categoryLabelKey(report.dispatch_path?.category); return k ? t(k) : report.dispatch_path?.category })()}
                  </Tag>
                  {report.dispatch_path?.wo_no && (
                    <Text type="secondary">WO: <Text code>{report.dispatch_path.wo_no}</Text></Text>
                  )}
                  {report.dispatch_path?.wo_creator && (
                    <Tag>{report.dispatch_path.wo_creator}</Tag>
                  )}
                  {report.dispatch_path?.fo_assign_to && (
                    <Text type="secondary">FO Assign To: <Text code>{report.dispatch_path.fo_assign_to}</Text></Text>
                  )}
                </Space>
                <Alert type="info" showIcon message={report.dispatch_path?.explanation} />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('ttPm.ruleCoverage', { a: report.rules_snapshot?.down_alarm_codes_active?.join(', ') || t('ttPm.emptyParen'), b: report.rules_snapshot?.down_alarm_codes_stopped?.join(', ') || t('ttPm.emptyParen') })}
                </Text>
              </Space>
            </Card>

            {/* 为什么走人工派单 —— TT Push Order Rule 逐条比对 */}
            {report.dispatch_analysis?.rules_at_step && report.dispatch_analysis.rules_at_step.length > 0 && (
              <Card size="small" title={
                <Space>
                  <Text strong>{t('ttPm.whyManualTitle')}</Text>
                  <Tag color={DISPATCH_OVERALL_COLOR[report.dispatch_analysis.overall] || 'default'}>
                    {(() => { const k = dispatchOverallLabelKey(report.dispatch_analysis.overall); return k ? t(k) : report.dispatch_analysis.overall })()}
                  </Tag>
                </Space>
              }>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('ttPm.triggerStep')} <Text code>{report.dispatch_analysis.trigger_step}</Text>
                    （{report.dispatch_analysis.step_meaning}）
                  </Text>
                  <Space size={6} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.ticketSig')}</Text>
                    <Tag color="blue">siteSubType={report.dispatch_analysis.site_subtype || '-'}</Tag>
                    <Tag>{report.dispatch_analysis.alarm_name || '-'}</Tag>
                    {Object.entries(report.dispatch_analysis.signature || {})
                      .filter(([, v]) => v)
                      .map(([k]) => <Tag key={k} color="geekblue">{k}</Tag>)}
                  </Space>

                  <Table
                    size="small"
                    rowKey={(r) => `${r.rule_name}-${r.verdict}`}
                    pagination={false}
                    dataSource={report.dispatch_analysis.rules_at_step}
                    columns={[
                      { title: t('ttPm.colRuleName'), dataIndex: 'rule_name', width: 190 },
                      {
                        title: t('ttPm.colStatus'), dataIndex: 'status', width: 80,
                        render: (v: string | null) => (
                          <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{v || '-'}</Tag>
                        ),
                      },
                      {
                        title: t('ttPm.colTarget'), dataIndex: 'target', width: 80,
                        render: (v: string) => (
                          <Tag color={v === 'WO' ? 'purple' : v === 'MANUAL' ? 'orange' : 'default'}>{v}</Tag>
                        ),
                      },
                      {
                        title: t('ttPm.colWants'), dataIndex: 'wants_keys', width: 150,
                        render: (v: string[]) => v?.length
                          ? v.map(k => <Tag key={k} style={{ marginBottom: 2 }}>{k}</Tag>)
                          : <Text type="secondary">-</Text>,
                      },
                      {
                        title: t('ttPm.colVerdict'), dataIndex: 'verdict', width: 150,
                        render: (v: DispatchRuleEval['verdict']) => {
                          const k = verdictLabelKey(v)
                          return <Tag color={VERDICT_COLOR[v]}>{k ? t(k) : v}</Tag>
                        },
                      },
                      {
                        title: t('ttPm.colWhy'), dataIndex: 'why',
                        render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
                      },
                    ]}
                  />

                  {report.dispatch_analysis.blocked_rules?.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      message={t('ttPm.blockedTitle')}
                      description={
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {report.dispatch_analysis.blocked_rules.map((b, i) => (
                            <li key={i}>
                              <Text strong>{b.rule_name}</Text>
                              <Tag style={{ marginLeft: 6 }}>{b.status}</Tag>
                              <Text type="secondary">
                                {t('ttPm.blockedItem', { p: b.priority ?? '-', d: b.description || t('ttPm.none'), u: b.update_time || '-' })}
                              </Text>
                            </li>
                          ))}
                        </ul>
                      }
                    />
                  )}

                  {report.dispatch_analysis.fallback_rules?.length > 0 && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.fallbackTitle')}</Text>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                        {report.dispatch_analysis.fallback_rules.map((f, i) => (
                          <li key={i}>
                            <Text code>{f.rule_name}</Text>
                            <Tag style={{ marginLeft: 6 }}>{t('ttPm.priorityN', { p: f.priority ?? '-' })}</Tag>
                            <Tag color={f.status === 'ACTIVE' ? 'green' : 'default'}>{f.status}</Tag>
                            <Text type="secondary">{f.description || ''}</Text>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <Alert
                    type={report.dispatch_analysis.overall === 'rule_should_have_fired' ? 'error' : 'info'}
                    showIcon
                    message={t('ttPm.conclusion')}
                    description={<Text>{report.dispatch_analysis.conclusion}</Text>}
                  />
                  {report.dispatch_analysis.caveat && (
                    <Text type="secondary" style={{ fontSize: 11 }}>⚠ {report.dispatch_analysis.caveat}</Text>
                  )}
                </Space>
              </Card>
            )}

            {/* 这单指派给谁了 */}
            {report.assignment && (
              <Card size="small" title={
                <Space>
                  <Text strong>{t('ttPm.assignTitle')}</Text>
                  {report.assignment.effective_scope === 'person' && <Tag color="green">{t('ttPm.scopePerson')}</Tag>}
                  {report.assignment.effective_scope === 'group' && <Tag color="orange">{t('ttPm.scopeGroup')}</Tag>}
                  {report.assignment.effective_scope === 'none' && <Tag color="red">{t('ttPm.scopeNone')}</Tag>}
                </Space>
              }>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Alert
                    type={report.assignment.effective_scope === 'none' ? 'error'
                      : report.assignment.effective_scope === 'group' ? 'warning' : 'success'}
                    showIcon
                    message={report.assignment.conclusion}
                  />
                  <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label={t('ttPm.channel')}>{report.assignment.channel || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.assignedPersons')}>
                      {report.assignment.assigned_persons && report.assignment.assigned_persons.length > 0
                        ? <Space size={4} wrap>
                            {report.assignment.assigned_persons.map(p => <Tag key={p} color="blue">{p}</Tag>)}
                          </Space>
                        : <Text type="warning">{t('ttPm.emptyParen')}</Text>}
                    </Descriptions.Item>
                  </Descriptions>

                  <Divider style={{ margin: '2px 0' }} plain>
                    <Text type="secondary" style={{ fontSize: 12 }}>{t('ttPm.ttLayer')}</Text>
                  </Divider>
                  <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label={t('ttPm.ttAssignTo')}>
                      {report.assignment.tt_create_assign_to
                        ? <Text code>{report.assignment.tt_create_assign_to}</Text>
                        : <Text type="warning">{t('ttPm.emptyVal')}</Text>}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.ttAssigneeGroup')}>
                      {report.assignment.tt_create_assignee_group
                        ? <Text code>{report.assignment.tt_create_assignee_group}</Text>
                        : <Text type="warning">{t('ttPm.emptyVal')}</Text>}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.ttNextStatus')}>{report.assignment.tt_next_status || '-'}</Descriptions.Item>
                    <Descriptions.Item label={t('ttPm.ttCurrentHandler')}>
                      {report.assignment.tt_current_handler
                        ? <Text code>{report.assignment.tt_current_handler}</Text>
                        : <Text type="warning">{t('ttPm.emptyVal')}</Text>}
                    </Descriptions.Item>
                  </Descriptions>

                  {report.assignment.wo_no && (
                    <>
                      <Divider style={{ margin: '2px 0' }} plain>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {t('ttPm.woLayer', { no: report.assignment.wo_no })}
                        </Text>
                      </Divider>
                      <Descriptions size="small" column={2} bordered>
                        <Descriptions.Item label={t('ttPm.woAssignTo')}>
                          {report.assignment.wo_create_assign_to
                            ? <Text code>{report.assignment.wo_create_assign_to}</Text>
                            : <Text type="warning">{t('ttPm.emptyVal')}</Text>}
                        </Descriptions.Item>
                        <Descriptions.Item label={t('ttPm.pWoHandler')}>
                          {report.assignment.wo_current_handler
                            ? <Text code>{report.assignment.wo_current_handler}</Text>
                            : <Text type="warning">{t('ttPm.emptyVal')}</Text>}
                        </Descriptions.Item>
                      </Descriptions>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('ttPm.pfxIntro')}<Text code>P:</Text>{t('ttPm.pfxPerson')}<Text code>G:</Text>{t('ttPm.pfxGroup')}
                        {t('ttPm.pfxNote')}<b>{t('ttPm.pfxBold')}</b>{t('ttPm.pfxEnd')}
                      </Text>
                    </>
                  )}

                  {report.assignment.create_note && (
                    <Alert type="info" showIcon message={t('ttPm.createNote')}
                           description={<Text style={{ fontSize: 12 }}>{report.assignment.create_note}</Text>} />
                  )}

                  {report.assignment.channel_note && (
                    <Text type="secondary" style={{ fontSize: 12 }}>ℹ {report.assignment.channel_note}</Text>
                  )}

                  {report.assignment.group_pools && report.assignment.group_pools.length > 0 && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {t('ttPm.groupPoolTitle')}
                      </Text>
                      <Table
                        size="small"
                        style={{ marginTop: 4 }}
                        rowKey={(r) => `${r.stage}-${r.rule_name}`}
                        pagination={false}
                        dataSource={report.assignment.group_pools}
                        columns={[
                          { title: t('ttPm.colStage'), dataIndex: 'stage', width: 130 },
                          { title: t('ttPm.colRuleName'), dataIndex: 'rule_name', width: 220 },
                          { title: t('ttPm.colPriority'), dataIndex: 'priority', width: 70 },
                          {
                            title: t('ttPm.colCandidates'), dataIndex: 'handler_name',
                            render: (v: string | null) => (
                              <Tooltip title={v || ''}>
                                <Text style={{ fontSize: 12 }}>{v ? v.slice(0, 70) + (v.length > 70 ? '…' : '') : '-'}</Text>
                              </Tooltip>
                            ),
                          },
                        ]}
                      />
                    </div>
                  )}
                </Space>
              </Card>
            )}

            {/* 阶段时长 */}
            <Card size="small" title={t('ttPm.durTitle')}>
              <Descriptions size="small" column={2} bordered>
                <Descriptions.Item label={t('ttPm.dCreateAccept')}>{fmtSec(report.durations?.create_to_accept_seconds)}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.dAcceptProcess')}>{fmtSec(report.durations?.accept_to_process_seconds)}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.dProcessConfirm')}>{fmtSec(report.durations?.process_to_confirm_seconds)}</Descriptions.Item>
                <Descriptions.Item label={t('ttPm.dTotal')}>{fmtSec(report.durations?.total_seconds)}</Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 建议 */}
            {report.suggested_actions && report.suggested_actions.length > 0 && (
              <Card size="small" title={t('ttPm.suggTitle')}>
                <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                  {report.suggested_actions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </Card>
            )}

            <Space>
              <Button icon={<ReloadOutlined />} onClick={run}>{t('ttPm.regenerate')}</Button>
            </Space>
          </div>
        )}
      </Spin>
    </Drawer>
  )
}
