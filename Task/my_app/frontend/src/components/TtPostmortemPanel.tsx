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
  assignment?: {
    channel?: string | null
    channel_rules?: { rule_name: string | null; priority: number | null }[]
    channel_note?: string
    create_assign_to?: string | null
    create_assignee_group?: string | null
    create_operator_group?: string | null
    next_status?: string | null
    current_handler?: string | null
    current_handler_is_group?: boolean
    current_handler_person?: string | null
    group_pools?: {
      stage: string; rule_name: string | null; priority: number | null
      handler_name: string | null; handler_id: string | null; description: string | null
    }[]
    conclusion?: string
    unassigned?: boolean
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

const CATEGORY_LABEL: Record<string, string> = {
  auto_dispatched: '系统自动派单',
  rule_stopped: '规则已停用',
  rule_vacuum: '规则真空',
  no_rule_or_p4: '无需现场/P4 自愈',
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

const DISPATCH_OVERALL_LABEL: Record<string, string> = {
  auto_dispatched: '已自动派单',
  manual_by_design: '人工派单·设计如此',
  no_wo_by_design_multi: '无 WO·规则设计如此',
  routed_to_other_system: '规则推往其它系统',
  rule_should_have_fired: '⚠ 规则应生效却未建 WO',
  no_active_rule_matched: '无 ACTIVE 规则命中',
  rule_vacuum: '规则真空',
  ambiguous: '需人工确认',
}

// 单条规则的适用性判定 → 颜色 / 文案
const VERDICT_COLOR: Record<string, string> = {
  matched: 'green',
  blocked_by_status: 'red',
  not_applicable: 'default',
  unknown_scope: 'gold',
}

const VERDICT_LABEL: Record<string, string> = {
  matched: '✅ 命中',
  blocked_by_status: '⛔ 本应命中但已停用',
  not_applicable: '➖ 不适用',
  unknown_scope: '❓ 范围未知',
}

// 偏离严重度 → antd Tag 颜色（critical 红 / major 橙 / minor 金）
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  major: 'orange',
  minor: 'gold',
}

// 偏离类型 → 文案 + 图标色调
const KIND_LABEL: Record<string, string> = {
  missing: '应有动作缺失',
  late: '动作超时',
  out_of_order: '动作越序',
  data_conflict: '字段冲突',
}

/** 秒 → 人读时长；缺失返回 '-'（不要用 0 冒充"瞬时"） */
function fmtGap(sec?: number | null): string {
  if (sec == null) return '-'
  if (sec < 60) return `${sec} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  if (sec < 86400) return `${(sec / 3600).toFixed(2)} 小时`
  return `${(sec / 86400).toFixed(2)} 天`
}

export default function TtPostmortemPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
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
      setError(e?.response?.data?.detail || e?.message || '查询失败')
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
      message.success(`已下载 ${r.data.filename}`)
    } catch (e: any) {
      message.error(`下载失败: ${e?.response?.data?.detail || e?.message}`)
    } finally {
      setExporting(false)
    }
  }, [report])

  const fmtSec = (s?: number | null) => {
    if (s == null) return '-'
    if (s < 60) return `${s} 秒`
    if (s < 3600) return `${(s / 60).toFixed(1)} 分钟`
    return `${(s / 3600).toFixed(2)} 小时`
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#722ed1' }} />
          <span>TT 复盘报告生成（程序化版）</span>
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
          placeholder="输入 TT 单号（例 TT202609210140）"
          value={ttNo}
          onChange={e => setTtNo(e.target.value)}
          onPressEnter={run}
          allowClear
          size="large"
        />
        <Button type="primary" size="large" icon={<ThunderboltOutlined />} loading={loading} onClick={run}>
          生成复盘报告
        </Button>
      </Space.Compact>

      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} />}

      <Spin spinning={loading} style={{ marginTop: 12 }}>
        {report && !report.found && (
          <Empty description={report.message || '未找到该工单'} />
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
                      ? <Tag color="red">已超期 {fmtGap(report.sla.over_seconds)}</Tag>
                      : <Tag color="green">未超期</Tag>}
                    {report.sla.total_text && <Tag>SLA 时长 {report.sla.total_text}</Tag>}
                    {report.sla.deadline && <Tag>期限 {report.sla.deadline}</Tag>}
                    {report.sla.over_text && <Text type="secondary">系统结余 {report.sla.over_text}</Text>}
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
                  下载 Markdown
                </Button>
              }
            >
              {report.ticket?.title && (
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">标题：</Text><Text strong>{report.ticket.title.trim()}</Text>
                </div>
              )}
              <Descriptions size="small" column={3} bordered>
                <Descriptions.Item label="告警码">{report.ticket?.alarm_code} {report.ticket?.alarm_name ? `(${report.ticket.alarm_name})` : ''}</Descriptions.Item>
                <Descriptions.Item label="告警级别">{report.ticket?.alarm_severity || '-'}</Descriptions.Item>
                <Descriptions.Item label="故障域 reason_type">{report.system_judged?.reason_type || '-'}</Descriptions.Item>
                <Descriptions.Item label="告警发生">{report.ticket?.alarm_occur_time || '-'}</Descriptions.Item>
                <Descriptions.Item label="告警清除">{report.ticket?.alarm_clear_time || '-'}</Descriptions.Item>
                <Descriptions.Item label="故障持续">{report.ticket?.fault_duration_time || '-'}</Descriptions.Item>
                <Descriptions.Item label="TT 建单">{report.ticket?.created_time || '-'}</Descriptions.Item>
                <Descriptions.Item label="末次修改">{report.ticket?.last_modified_time || '-'}</Descriptions.Item>
                <Descriptions.Item label="影响业务">{report.ticket?.impacted_service || '-'}</Descriptions.Item>
                <Descriptions.Item label="站点等级">{report.site?.site_class || '-'}</Descriptions.Item>
                <Descriptions.Item label="区域">{report.site?.region || '-'}</Descriptions.Item>
                <Descriptions.Item label="WO 编号">{report.ticket?.wo_no || <Text type="danger">无</Text>}</Descriptions.Item>
              </Descriptions>

              {/* 责任人：谁建的 / 谁接的 / 谁处理的 / 谁关的 */}
              {report.people && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>责任人</Text>
                  <Descriptions size="small" column={3} bordered style={{ marginTop: 4 }}>
                    <Descriptions.Item label="建单人">
                      {report.people.creator || '-'}
                      <Tag style={{ marginLeft: 4 }} color={report.people.creator_kind === '系统自动' ? 'default' : 'blue'}>
                        {report.people.creator_kind}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="FO 接单人">{report.people.fo_acceptor || '-'}</Descriptions.Item>
                    <Descriptions.Item label="FO 填报人">{report.people.fo_processer || '-'}</Descriptions.Item>
                    <Descriptions.Item label="关单人">{report.people.confirmer || '-'}</Descriptions.Item>
                    <Descriptions.Item label="最后处理人">{report.people.last_processer || '-'}</Descriptions.Item>
                    <Descriptions.Item label="处理组">{report.people.last_processer_group || '-'}</Descriptions.Item>
                    <Descriptions.Item label="WO 建单人">{report.people.wo_creator || '-'}</Descriptions.Item>
                    <Descriptions.Item label="WO 当前处理人">{report.people.wo_current_handler || '-'}</Descriptions.Item>
                  </Descriptions>
                </div>
              )}

              {/* WO 现场动作责任人（有 WO 才有） */}
              {report.people?.wo_people && report.people.wo_people.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>现场动作责任人（来自 eflow_wo）</Text>
                  <Table
                    size="small"
                    rowKey={(r) => `${r.step}-${r.time}-${r.operator}`}
                    style={{ marginTop: 4 }}
                    pagination={false}
                    dataSource={report.people.wo_people}
                    columns={[
                      { title: '步骤', dataIndex: 'step', width: 110 },
                      { title: '时间', dataIndex: 'time', width: 175, render: (v: string | null) => v || '-' },
                      { title: '操作人', dataIndex: 'operator', render: (v: string | null) => v || '-' },
                      { title: '来源', dataIndex: 'source', width: 200, render: (v: string) => <Text type="secondary" style={{ fontSize: 11 }}>{v}</Text> },
                    ]}
                  />
                </div>
              )}
            </Card>

            {/* 时间都花哪了 —— 复盘重点 */}
            {report.time_spent?.segments && report.time_spent.segments.length > 0 && (
              <Card size="small" title={
                <Space>
                  <Text strong>⏱ 时间都花哪了</Text>
                  <Tag color="blue">总历时 {fmtGap(report.time_spent.total_seconds)}</Tag>
                  {(report.time_spent.over_threshold_count ?? 0) > 0 && (
                    <Tag color="red">{report.time_spent.over_threshold_count} 个阶段超阈值</Tag>
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
                      title: '阶段', dataIndex: 'label',
                      render: (v: string, r: TimeSegment) => (
                        <Space size={4} wrap>
                          {r.key === report.time_spent?.bottleneck?.key && <Tag color="red">瓶颈</Tag>}
                          {r.phase_label && <Tag color="geekblue">{r.phase_label}</Tag>}
                          <Text strong={r.key === report.time_spent?.bottleneck?.key}>{v}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: '耗时', dataIndex: 'seconds', width: 120,
                      defaultSortOrder: 'descend',
                      sorter: (a: TimeSegment, b: TimeSegment) => a.seconds - b.seconds,
                      render: (v: number) => <Text strong>{fmtGap(v)}</Text>,
                    },
                    {
                      title: '占比', dataIndex: 'pct', width: 150,
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
                      title: '责任方', dataIndex: 'owner', width: 200,
                      render: (v: string) => v ? <Tag color={v === '系统/流程' ? 'default' : 'blue'}>{v}</Tag> : '-',
                    },
                    {
                      title: '是否超阈值', dataIndex: 'over_threshold', width: 150,
                      render: (v: boolean, r: TimeSegment) => (
                        v
                          ? <Tag color="red">超 {fmtGap(r.over_by_s)}</Tag>
                          : (r.threshold_s ? <Tag color="green">正常</Tag> : <Text type="secondary">—</Text>)
                      ),
                    },
                  ]}
                />
                {report.time_spent.window?.start && (
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
                    统计窗口：{report.time_spent.window.start} → {report.time_spent.window.end}
                    （终点取所有已知活动的最晚时间，含现场动作）
                  </Text>
                )}
                {report.time_spent.bottleneck_note && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="warning"
                    showIcon
                    message="瓶颈定位"
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
              <Card size="small" title={`① 里程碑时间轴（${report.timeline_meta?.done_count ?? 0}/${report.timeline_meta?.stage_count ?? 0} 跳有确凿时间戳）`}>
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
                            <Text strong={!missing} delete={missing}>{m.label}</Text>
                            <Tag color={m.actor === 'human' ? 'blue' : unproven ? 'gold' : 'green'}>
                              {m.actor === 'human' ? '人工' : unproven ? '未证实' : '系统'}
                            </Tag>
                            <Text code style={{ fontSize: 12 }}>{m.time || '（缺失）'}</Text>
                            {m.gap_from_prev_s != null && (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                距上一跳 {fmtGap(m.gap_from_prev_s)}
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
                              来源：{m.source}
                              {m.raw && (
                                <Tooltip title={<pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxWidth: 520 }}>{m.raw}</pre>}>
                                  <Text type="secondary" style={{ fontSize: 11, marginLeft: 6, cursor: 'help' }}>
                                    [原文]
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
                  窗口 {report.timeline_meta?.window?.start} → {report.timeline_meta?.window?.end}，
                  总历时 {fmtGap(report.timeline_meta?.total_seconds)}
                </Text>
              </Card>
            )}

            {/* 应做 vs 实做 */}
            {report.expected_actions && report.expected_actions.length > 0 && (
              <Card size="small" title="② 该做的动作 · 实际做的动作">
                <Table
                  size="small"
                  rowKey="key"
                  pagination={false}
                  dataSource={report.expected_actions}
                  columns={[
                    { title: '里程碑', dataIndex: 'label', width: 130 },
                    {
                      title: '契约', dataIndex: 'required', width: 70,
                      render: (v: boolean) => <Tag color={v ? 'purple' : 'default'}>{v ? '必需' : '条件'}</Tag>,
                    },
                    {
                      title: '应做', dataIndex: 'key', width: 80,
                      render: () => <Tag color="blue">应执行</Tag>,
                    },
                    {
                      title: '实际', dataIndex: 'status', width: 104,
                      render: (v: ExpectedAction['status'], r: ExpectedAction) => {
                        const st = v || (r.done ? 'done' : 'missing')
                        if (st === 'done') return <Tag color="green" icon={<CheckCircleOutlined />}>已执行</Tag>
                        if (st === 'unproven') {
                          return (
                            <Tooltip title="库中取不到该动作的证据，但也不能据此断定没做（如「有 WO 却无出发/到场明细」，WO 还可能是 fe_robot 自动建的）">
                              <Tag color="gold" icon={<QuestionCircleOutlined />}>未证实</Tag>
                            </Tooltip>
                          )
                        }
                        return <Tag color="red" icon={<CloseCircleOutlined />}>未执行</Tag>
                      },
                    },
                    { title: '时间', dataIndex: 'time', width: 165, render: (v: string | null) => v || <Text type="danger">-</Text> },
                    { title: '操作人', dataIndex: 'operator', width: 170, render: (v: string | null) => v || '-' },
                  ]}
                />
                {report.expected_actions?.some(a => (a.status || (a.done ? 'done' : 'missing')) === 'unproven') && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="warning"
                    showIcon
                    message="存在「未证实」的动作"
                    description={
                      <Text style={{ fontSize: 12 }}>
                        库中取不到这些动作的证据，但**也不能据此断定没做**。典型是「有 WO 却无出发/到场/离场明细」——
                        eflow_tt 本就没有独立到场字段，而 WO 的创建者若为 <Text code>fe_robot</Text>
                        （系统自动），只能说明系统自动生成了工单，<Text strong>不能作为现场有人的证据</Text>。
                      </Text>
                    }
                  />
                )}
                {report.missing_actions && report.missing_actions.length > 0 && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="error"
                    showIcon
                    message={`存在 ${report.missing_actions.length} 个缺失动作`}
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {report.missing_actions.map(m => (
                          <li key={m.key}><Text strong>{m.label}</Text>：{m.reason}</li>
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
                <Text strong>③ 偏离清单（应做 vs 实做）</Text>
                {report.deviations && report.deviations.length > 0 && (
                  <Tag color="red">{report.deviations.length} 处</Tag>
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
                        <Tag>{KIND_LABEL[d.kind] || d.kind}</Tag>
                        <Text strong>{d.label}</Text>
                      </Space>
                      <div style={{ fontSize: 12, marginTop: 2 }}>
                        <Text type="secondary">应有：</Text>{d.expected}
                      </div>
                      <div style={{ fontSize: 12 }}>
                        <Text type="secondary">实际：</Text><Text type="danger">{d.actual}</Text>
                      </div>
                      <div style={{ fontSize: 12 }}>
                        <Text type="secondary">影响：</Text>{d.impact}
                      </div>
                    </div>
                  ))}
                </Space>
              ) : (
                <Alert type="success" showIcon message="未检出偏离：契约要求的动作全部按时执行，且未发现字段间冲突。" />
              )}
            </Card>

            {/* 一致性判定 */}
            <Card size="small" title={
              <Space>
                <Text strong>④ 系统判定根因 vs NOC 填写根因</Text>
                {report.consistency === false && (
                  <Tooltip title={report.note}>
                    <Tag color="red" icon={<ExclamationCircleOutlined />}>{report.mismatch_type}</Tag>
                  </Tooltip>
                )}
                {report.consistency === true && (
                  <Tag color="green" icon={<CheckCircleOutlined />}>一致</Tag>
                )}
                {report.consistency == null && <Tag color="default">待人工复核</Tag>}
                <Tag>置信度: {report.confidence}</Tag>
              </Space>
            }>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="NOC 填写">{report.noc_filled?.root_cause} / {report.noc_filled?.sub_root_cause}</Descriptions.Item>
                <Descriptions.Item label="系统判定（{report.system_judged?.linkage}）">
                  {report.system_judged?.fault_domain} （依据：{report.system_judged?.basis}）
                </Descriptions.Item>
                {report.history_match && (
                  <Descriptions.Item label="历史匹配">{report.history_match}</Descriptions.Item>
                )}
              </Descriptions>

              {/* 同站历史告警指纹：判定「反复同源故障」的关键佐证 */}
              {report.site_history && report.site_history.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    该站历史告警指纹（同站历史是判定「反复同源故障」的关键佐证）
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
                            {r.is_self && <Tag color="blue">本单</Tag>}
                          </Space>
                        ),
                      },
                      { title: '告警码', dataIndex: 'alarmcode', width: 80 },
                      { title: 'codename', dataIndex: 'codename', width: 150 },
                      {
                        title: 'reason_type', dataIndex: 'reason_type', width: 100,
                        render: (v: string) => <Tag color={v === 'TRM' ? 'orange' : 'default'}>{v}</Tag>,
                      },
                      { title: '发生', dataIndex: 'raised', width: 165 },
                      { title: '清除', dataIndex: 'cleared', width: 165 },
                    ]}
                  />
                </div>
              )}
            </Card>

            {/* 派单机制真相 */}
            <Card size="small" title="⑤ WO 派单机制真相">
              <Space direction="vertical" style={{ width: '100%' }} size={6}>
                <Space>
                  <Text>分类：</Text>
                  <Tag color={CATEGORY_COLOR[report.dispatch_path?.category || 'default']}>
                    {CATEGORY_LABEL[report.dispatch_path?.category || ''] || report.dispatch_path?.category}
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
                  断站类告警码 ACTIVE 规则覆盖：{report.rules_snapshot?.down_alarm_codes_active?.join(', ') || '（无）'}；
                  STOP 覆盖：{report.rules_snapshot?.down_alarm_codes_stopped?.join(', ') || '（无）'}
                </Text>
              </Space>
            </Card>

            {/* 为什么走人工派单 —— TT Push Order Rule 逐条比对 */}
            {report.dispatch_analysis?.rules_at_step && report.dispatch_analysis.rules_at_step.length > 0 && (
              <Card size="small" title={
                <Space>
                  <Text strong>⑤b 为什么走人工派单 · TT Push Order Rule 逐条比对</Text>
                  <Tag color={DISPATCH_OVERALL_COLOR[report.dispatch_analysis.overall] || 'default'}>
                    {DISPATCH_OVERALL_LABEL[report.dispatch_analysis.overall] || report.dispatch_analysis.overall}
                  </Tag>
                </Space>
              }>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    判定阶段 <Text code>{report.dispatch_analysis.trigger_step}</Text>
                    （{report.dispatch_analysis.step_meaning}）
                  </Text>
                  <Space size={6} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>本单特征：</Text>
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
                      { title: '规则名', dataIndex: 'rule_name', width: 190 },
                      {
                        title: '状态', dataIndex: 'status', width: 80,
                        render: (v: string | null) => (
                          <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{v || '-'}</Tag>
                        ),
                      },
                      {
                        title: '目标', dataIndex: 'target', width: 80,
                        render: (v: string) => (
                          <Tag color={v === 'WO' ? 'purple' : v === 'MANUAL' ? 'orange' : 'default'}>{v}</Tag>
                        ),
                      },
                      {
                        title: '规则要求', dataIndex: 'wants_keys', width: 150,
                        render: (v: string[]) => v?.length
                          ? v.map(k => <Tag key={k} style={{ marginBottom: 2 }}>{k}</Tag>)
                          : <Text type="secondary">-</Text>,
                      },
                      {
                        title: '本单是否适用', dataIndex: 'verdict', width: 150,
                        render: (v: DispatchRuleEval['verdict']) => (
                          <Tag color={VERDICT_COLOR[v]}>{VERDICT_LABEL[v] || v}</Tag>
                        ),
                      },
                      {
                        title: '判定依据', dataIndex: 'why',
                        render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
                      },
                    ]}
                  />

                  {report.dispatch_analysis.blocked_rules?.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      message="本应命中但已停用的规则"
                      description={
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {report.dispatch_analysis.blocked_rules.map((b, i) => (
                            <li key={i}>
                              <Text strong>{b.rule_name}</Text>
                              <Tag style={{ marginLeft: 6 }}>{b.status}</Tag>
                              <Text type="secondary">
                                优先级 {b.priority}，描述：{b.description || '无'}，最后更新 {b.update_time || '-'}
                              </Text>
                            </li>
                          ))}
                        </ul>
                      }
                    />
                  )}

                  {report.dispatch_analysis.fallback_rules?.length > 0 && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>兜底派单规则（ttDispatchRule）</Text>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                        {report.dispatch_analysis.fallback_rules.map((f, i) => (
                          <li key={i}>
                            <Text code>{f.rule_name}</Text>
                            <Tag style={{ marginLeft: 6 }}>优先级 {f.priority}</Tag>
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
                    message="结论"
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
                  <Text strong>⑤c 这单指派给谁了</Text>
                  {report.assignment.unassigned && <Tag color="orange">未指派到人</Tag>}
                </Space>
              }>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Alert
                    type={report.assignment.unassigned ? 'warning' : 'info'}
                    showIcon
                    message={report.assignment.conclusion}
                  />
                  <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label="通道">{report.assignment.channel || '-'}</Descriptions.Item>
                    <Descriptions.Item label="建单后状态">{report.assignment.next_status || '-'}</Descriptions.Item>
                    <Descriptions.Item label="指派到人（Assign To）">
                      {report.assignment.create_assign_to
                        ? <Text code>{report.assignment.create_assign_to}</Text>
                        : <Text type="warning">（空 · 未指派到人）</Text>}
                    </Descriptions.Item>
                    <Descriptions.Item label="指派到群组（Assignee Group）">
                      {report.assignment.create_assignee_group
                        ? <Text code>{report.assignment.create_assignee_group}</Text>
                        : <Text type="warning">（空）</Text>}
                    </Descriptions.Item>
                    <Descriptions.Item label="当前处理人" span={2}>
                      {report.assignment.current_handler
                        ? <Space size={6}>
                            <Text code>{report.assignment.current_handler}</Text>
                            {report.assignment.current_handler_is_group && <Tag>群组，非个人</Tag>}
                          </Space>
                        : <Text type="warning">（空）</Text>}
                    </Descriptions.Item>
                  </Descriptions>

                  {report.assignment.channel_note && (
                    <Text type="secondary" style={{ fontSize: 12 }}>ℹ {report.assignment.channel_note}</Text>
                  )}

                  {report.assignment.group_pools && report.assignment.group_pools.length > 0 && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        群组池规则（决定候选人范围，不指定个人）
                      </Text>
                      <Table
                        size="small"
                        style={{ marginTop: 4 }}
                        rowKey={(r) => `${r.stage}-${r.rule_name}`}
                        pagination={false}
                        dataSource={report.assignment.group_pools}
                        columns={[
                          { title: '环节', dataIndex: 'stage', width: 130 },
                          { title: '规则名', dataIndex: 'rule_name', width: 220 },
                          { title: '优先级', dataIndex: 'priority', width: 70 },
                          {
                            title: '候选处理人（节选）', dataIndex: 'handler_name',
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
            <Card size="small" title="⑥ 阶段时长">
              <Descriptions size="small" column={2} bordered>
                <Descriptions.Item label="建单 → FO Accept">{fmtSec(report.durations?.create_to_accept_seconds)}</Descriptions.Item>
                <Descriptions.Item label="FO Accept → FO Process">{fmtSec(report.durations?.accept_to_process_seconds)}</Descriptions.Item>
                <Descriptions.Item label="FO Process → Confirm">{fmtSec(report.durations?.process_to_confirm_seconds)}</Descriptions.Item>
                <Descriptions.Item label="全流程">{fmtSec(report.durations?.total_seconds)}</Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 建议 */}
            {report.suggested_actions && report.suggested_actions.length > 0 && (
              <Card size="small" title="⑦ 改进建议">
                <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                  {report.suggested_actions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </Card>
            )}

            <Space>
              <Button icon={<ReloadOutlined />} onClick={run}>重新生成</Button>
            </Space>
          </div>
        )}
      </Spin>
    </Drawer>
  )
}
