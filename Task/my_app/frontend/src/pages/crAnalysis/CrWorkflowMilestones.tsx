/* ============================================================================
 * CR 变更分析 —— Workflow 里程碑条（页面顶部）
 * ============================================================================
 *
 * 取代原先的「当前状态分布」卡片行。顺序**严格对齐 eFlow 的 Workflow History**
 * （`/api/eflow-asset/v1/flow/runtime/queryAllSteps`，payload `eflow-cr`）：
 *
 *   Create → BO/FO Head Approval → Domain TD Approval → CM Head Approval
 *          → Start to Implement → Result Feedback → Closed
 *
 * 为什么改成里程碑而不是状态卡：状态是**技术状态**（7 个值，含 update 这种
 * 非流程节点），读起来要先去脑内翻译成「走到哪了」。里程碑直接按流程节点排，
 * 一眼看出积压在哪一环节。两者的数字关系见后端 `_milestones()` 的 docstring。
 *
 * 每个里程碑显示：
 *   - 已完成数（`done`，灰）—— 走过该节点的 CR
 *   - 当前等待数（`waiting`，高亮）—— 正卡在该节点、等下一环节
 *   - 最长等待天数（`waiting_max_days`）—— 超过 30 天标红
 *
 * 点击：等待数 → 该节点滞留明细；已完成数 → 走过该节点的明细。
 * ========================================================================== */

import { Col, Empty, Row, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'

import { CardBase } from '../../components/cards'
import { useI18n } from '../../i18n'
import { fmtDays, type Milestone, type StepKey } from './crTypes'
import type { ChartColors } from './crCharts'

const { Text } = Typography

/** 里程碑显示名 → i18n key。显式 switch（动态拼 key 会被 check:i18n 拦下） */
function milestoneLabelKey(k: Milestone['key']): string {
  switch (k) {
    case 'created': return 'cr.ms.created'
    case 'bo_fo': return 'cr.ms.bo_fo'
    case 'td': return 'cr.ms.td'
    case 'cm': return 'cr.ms.cm'
    case 'implement': return 'cr.ms.implement'
    case 'feedback': return 'cr.ms.feedback'
    case 'closed': return 'cr.ms.closed'
  }
}

interface Props {
  milestones: Milestone[]
  total: number
  inFlight: number
  C: ChartColors
  /** 等待该里程碑下一环节的明细（step 为本节点，「等待数」那一格） */
  onWaiting: (step: StepKey, at: { x: number; y: number }) => void
  /** 走到该里程碑的明细（「已完成数」那一格） */
  onDone: (step: StepKey, at: { x: number; y: number }) => void
  /** Closed 里程碑：走状态下钻（终态不在步骤表里） */
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

export default function CrWorkflowMilestones({
  milestones, total, inFlight, C, onWaiting, onDone, onClosed,
}: Props) {
  const { t } = useI18n()

  return (
    <CardBase
      title={t('cr.ms.title')}
      extra={
        <Space size="middle" wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('cr.ms.summary', { total, open: inFlight })}
          </Text>
        </Space>
      }
    >
      {milestones.length ? (
        <Row gutter={[8, 8]} align="stretch" wrap={false} style={{ overflowX: 'auto' }}>
          {milestones.map((m, i) => {
            const isClosed = m.key === 'closed'
            const isLast = i === milestones.length - 1
            // 当前停滞最多的环节高亮边框，一眼定位瓶颈
            const worst = Math.max(...milestones.map(x => x.waiting))
            const isBottleneck = m.waiting > 0 && m.waiting === worst
            return (
              <Col key={m.key} flex="1 1 0" style={{ minWidth: 124 }}>
                <div
                  style={{
                    height: '100%',
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: `1px solid ${isBottleneck ? C.delayed : 'var(--wh-border)'}`,
                    background: isBottleneck
                      ? 'color-mix(in srgb, var(--wh-danger) 8%, transparent)'
                      : 'var(--wh-bg-subtle, transparent)',
                  }}
                >
                  {/* 节点序号 + 名称 */}
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
                        {t('cr.ms.bottleneck')}
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
                      label={t('cr.ms.done')}
                      color={C.closed}
                      onClick={e => onClosed({ x: e.clientX, y: e.clientY })}
                    />
                  ) : (
                    <Space size={16} align="start">
                      <Cell
                        value={m.done}
                        label={t('cr.ms.done')}
                        color="var(--wh-text-dim)"
                        onClick={e => onDone(m.step as StepKey, { x: e.clientX, y: e.clientY })}
                      />
                      <Cell
                        value={m.waiting}
                        label={t('cr.ms.waiting')}
                        color={m.waiting ? C.delayed : 'var(--wh-text-dim)'}
                        strong={isBottleneck}
                        onClick={m.waiting
                          ? e => onWaiting(m.step as StepKey, { x: e.clientX, y: e.clientY })
                          : undefined}
                      />
                    </Space>
                  )}

                  {/* 最长等待：只有有人真卡着才显示，否则留空 */}
                  <div style={{ fontSize: 11, marginTop: 6, minHeight: 16 }}>
                    {m.waiting_max_days != null && (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('cr.ms.longest', { d: fmtDays(m.waiting_max_days) })}
                      </Text>
                    )}
                  </div>
                </div>
              </Col>
            )
          })}
        </Row>
      ) : <Empty description={t('cr.flow.empty')} />}
    </CardBase>
  )
}
