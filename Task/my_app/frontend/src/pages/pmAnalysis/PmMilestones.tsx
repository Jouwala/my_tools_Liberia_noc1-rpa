/* ============================================================================
 * PM 执行分析 —— Workflow 里程碑条（页面 KPI 之上）
 * ============================================================================
 *
 * 顺序**严格对齐 eFlow 的 Workflow History**（`queryAllSteps`，payload
 * `eflow-pm-task`），由后端 `pm_workflow_service._MILESTONE_DEFS` 给出：
 *
 *   Create → Schedule → Accept → Process → PMManagerApprove
 *          → FLMLeaderApprove → Closed
 *
 * 为什么用里程碑而不是状态卡：源表的 6 个状态里有 Transfer 这种非流程节点，
 * 读起来要先去脑内翻译成「走到哪了」。里程碑直接按流程节点排，
 * 一眼看出积压在哪一环节。数字关系见后端 `_milestones()` 的 docstring。
 *
 * 每个里程碑显示：
 *   - 已完成数（`done`，灰）—— 走过该节点的工单
 *   - 当前等待数（`waiting`，红色高亮）—— 正卡在该节点、等下一环节
 *   - 最长等待天数（`waiting_max_days`）—— 瓶颈定位
 *
 * 点击：等待数 → 该节点滞留明细；已完成数 → 走过该节点的明细；
 * Closed 的已完成数 → 已关闭工单明细。**每个数字都可点**（AGENTS.md 第三节 1b）。
 * ========================================================================== */

import { Col, Empty, Row, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'

import { CardBase } from '../../components/cards'
import { useI18n } from '../../i18n'
import { fmtDays, type Milestone, type MilestoneKey } from './pmTypes'
import type { ChartColors } from './pmCharts'

const { Text } = Typography

/** 里程碑显示名 → i18n key。显式 switch（动态拼 key 会被 check:i18n 拦下） */
export function milestoneLabelKey(k: MilestoneKey): string {
  switch (k) {
    case 'created': return 'pm.ms.created'
    case 'scheduled': return 'pm.ms.scheduled'
    case 'accepted': return 'pm.ms.accepted'
    case 'processed': return 'pm.ms.processed'
    case 'pm_approved': return 'pm.ms.pmApproved'
    case 'flm_approved': return 'pm.ms.flmApproved'
    case 'closed': return 'pm.ms.closed'
  }
}

/** 下钻类型，与后端 `drill_workflow` 的 kind 同值 */
export type MsKind = 'arrived' | 'current' | 'done'

interface Props {
  milestones: Milestone[]
  total: number
  inFlight: number
  C: ChartColors
  /** 等待该节点下一环节的明细 */
  onWaiting: (key: MilestoneKey, at: { x: number; y: number }) => void
  /** 走到该节点的明细 */
  onDone: (key: MilestoneKey, at: { x: number; y: number }) => void
  /** Closed 节点的已完成数（kind=done） */
  onClosed: (at: { x: number; y: number }) => void
}

/** 一格可点的数字 */
function Cell({
  value, label, color, strong, onClick, suffix,
}: {
  value: number | string
  label: string
  color?: string
  strong?: boolean
  suffix?: string
  onClick?: (e: React.MouseEvent<HTMLElement>) => void
}) {
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={e => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) {
          onClick(e as unknown as React.MouseEvent<HTMLElement>)
        }
      }}
      style={{ cursor: onClick ? 'pointer' : undefined, minWidth: 0 }}
    >
      <div style={{
        fontSize: 24, fontWeight: 700, lineHeight: 1.15, color,
        textDecoration: onClick ? 'underline dotted' : undefined,
        textUnderlineOffset: 3,
      }}>
        {value}
        {suffix && <span style={{ fontSize: 12, fontWeight: 500, marginLeft: 3 }}>{suffix}</span>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--wh-text-dim)', marginTop: 2 }}>{label}</div>
      {strong && <div style={{ height: 2, background: color, marginTop: 4, borderRadius: 1 }} />}
    </div>
  )
}

export default function PmMilestones({
  milestones, total, inFlight, C, onWaiting, onDone, onClosed,
}: Props) {
  const { t } = useI18n()
  // 当前滞留最多的环节高亮边框，一眼定位瓶颈（多个并列时都高亮）
  const worst = Math.max(0, ...milestones.map(m => m.waiting))

  return (
    <CardBase
      title={t('pm.ms.title')}
      extra={
        <Space size="middle" wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('pm.ms.summary', { n: total, inFlight })}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('pm.ms.hint')}</Text>
        </Space>
      }
    >
      {milestones.length ? (
        <Row gutter={[8, 8]} align="stretch" wrap={false} style={{ overflowX: 'auto' }}>
          {milestones.map((m, i) => {
            const isClosed = m.key === 'closed'
            const isLast = i === milestones.length - 1
            const isBottleneck = m.waiting > 0 && m.waiting === worst
            return (
              <Col key={m.key} flex="1 1 0" style={{ minWidth: 124 }}>
                <div
                  style={{
                    height: '100%',
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: `1px solid ${isBottleneck ? C.overdue : 'var(--wh-border)'}`,
                    background: isBottleneck
                      ? 'color-mix(in srgb, var(--wh-danger) 8%, transparent)'
                      : 'var(--wh-bg-subtle, transparent)',
                  }}
                >
                  {/* 节点序号 + 名称（序号即 Workflow History 顺序） */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 20, height: 20, borderRadius: '50%', flex: '0 0 20px',
                      fontSize: 11, fontWeight: 700,
                      background: isClosed ? C.closed : C.total,
                      color: '#fff',
                    }}>
                      {isClosed ? '✓' : i + 1}
                    </span>
                    <Text strong style={{ fontSize: 13, lineHeight: 1.2 }}>
                      {t(milestoneLabelKey(m.key))}
                    </Text>
                    {isBottleneck && (
                      <Tag color="red" style={{ marginInlineEnd: 0, lineHeight: '16px', fontSize: 10 }}>
                        {t('pm.ms.bottleneck')}
                      </Tag>
                    )}
                    {!isLast && (
                      <ArrowRightOutlined
                        style={{ marginLeft: 'auto', color: 'var(--wh-text-dim)', fontSize: 11 }}
                      />
                    )}
                  </div>

                  {isClosed ? (
                    <Cell
                      value={m.done}
                      label={t('pm.ms.done')}
                      color={C.closed}
                      onClick={e => onClosed({ x: e.clientX, y: e.clientY })}
                    />
                  ) : (
                    <Space size={16} align="start">
                      <Cell
                        value={m.done}
                        label={t('pm.ms.done')}
                        color="var(--wh-text-dim)"
                        onClick={e => onDone(m.key, { x: e.clientX, y: e.clientY })}
                      />
                      <Cell
                        value={m.waiting}
                        label={t('pm.ms.waiting')}
                        color={m.waiting ? C.overdue : 'var(--wh-text-dim)'}
                        strong={isBottleneck}
                        onClick={m.waiting
                          ? e => onWaiting(m.key, { x: e.clientX, y: e.clientY })
                          : undefined}
                      />
                    </Space>
                  )}

                  {/* 最长等待：只有真有人卡着才显示；已离开环节给平均停留作参照 */}
                  <div style={{ fontSize: 11, marginTop: 6, minHeight: 16 }}>
                    {m.waiting_max_days != null ? (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('pm.ms.longest', { d: fmtDays(m.waiting_max_days) })}
                      </Text>
                    ) : m.avg_days != null ? (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('pm.ms.avg', { d: fmtDays(m.avg_days) })}
                      </Text>
                    ) : null}
                  </div>
                </div>
              </Col>
            )
          })}
        </Row>
      ) : <Empty description={t('pm.ms.empty')} />}
    </CardBase>
  )
}
