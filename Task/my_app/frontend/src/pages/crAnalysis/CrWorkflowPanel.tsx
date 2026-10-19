/* ============================================================================
 * CR 变更分析 —— 审批流程面板（耗时表 + 滞留量图）
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（页面 731 行，超出 AGENTS.md 第三节 2 的
 * 单文件 500 行上限）。
 *
 * 数据来自 `cr_workflow_service.py`：它解析源表 8 个 `*_detail` 文本列得到
 * 每张 CR 的步骤时间线。这里只负责展示与点击回调，取数在页面。
 *
 * 「平均停留 / 最长停留」两列**刻意不做点击下钻**：它们的分子来自「已离开
 * 该步」的单，而「到达数」的明细也包含未离开的单，两者行数天然不等；
 * 给它们加下钻会让用户拿「35 条明细」去对「20.6 天」这个数字，反而更困惑。
 * 想看清哪些单慢，从「到达数」或「当前滞留」进去按天数排序即可。
 * ========================================================================== */

import { Col, Empty, Row, Table, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'

import { CardBase } from '../../components/cards'
import { useI18n } from '../../i18n'
import { DrillNum } from './crColumns'
import type { ChartColors } from './crCharts'
import { fmtDays, STEP_KEYS, type StepKey, type StepRow } from './crTypes'

const { Text } = Typography

/**
 * 步骤显示名 → i18n key。显式 switch 而非 `` `cr.flow.step.${k}` ``：
 * 动态拼 key 会被 `check:i18n` 读成字面量而报「字典缺失」（AGENTS.md 第三节 1b）。
 */
export function stepLabelKey(k: StepKey): string {
  switch (k) {
    case 'created': return 'cr.flow.step.created'
    case 'update': return 'cr.flow.step.update'
    case 'bo_fo': return 'cr.flow.step.bo_fo'
    case 'td': return 'cr.flow.step.td'
    case 'cm': return 'cr.flow.step.cm'
    case 'implement': return 'cr.flow.step.implement'
    case 'feedback': return 'cr.flow.step.feedback'
  }
}

export type FlowKind = 'arrived' | 'current'

interface Props {
  steps: StepRow[]
  C: ChartColors
  option: Record<string, unknown>
  onPick: (
    step: StepKey, kind: FlowKind, at?: { x: number; y: number },
  ) => void
}

/** 按 `STEP_KEYS` 的**真实时序**重排（后端返回顺序不作保证，不要依赖它） */
export function orderSteps(rows: StepRow[]): StepRow[] {
  const byKey = new Map(rows.map(s => [s.step, s]))
  return STEP_KEYS
    .map(k => byKey.get(k))
    .filter((s): s is StepRow => !!s)
}

export default function CrWorkflowPanel({ steps, C, option, onPick }: Props) {
  const { t } = useI18n()

  return (
    <CardBase
      title={t('cr.flow.title')}
      extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('cr.flow.hint')}</Text>}
    >
      {steps.length ? (
        <Row gutter={[12, 12]}>
          <Col xs={24} xl={13}>
            <Table
              rowKey="step"
              size="small"
              pagination={false}
              dataSource={steps}
              scroll={{ x: 680 }}
              columns={[
                {
                  title: t('cr.flow.col.step'), dataIndex: 'step', width: 170,
                  render: (k: StepKey) => <Text strong>{t(stepLabelKey(k))}</Text>,
                },
                {
                  title: t('cr.flow.col.arrived'), dataIndex: 'arrived', align: 'right' as const, width: 110,
                  render: (v: number, r: StepRow) => (
                    <DrillNum
                      value={v} color={C.total} hint={t('cr.drill.clickHint')}
                      onClick={e => onPick(r.step, 'arrived', { x: e.clientX, y: e.clientY })}
                    />
                  ),
                },
                {
                  title: t('cr.flow.col.avgDays'), dataIndex: 'avg_days',
                  align: 'right' as const, width: 110,
                  render: (v: number | null) => fmtDays(v),
                },
                {
                  title: t('cr.flow.col.maxDays'), dataIndex: 'max_days',
                  align: 'right' as const, width: 110,
                  render: (v: number | null) => fmtDays(v),
                },
                {
                  title: t('cr.flow.col.current'), dataIndex: 'current',
                  align: 'right' as const, width: 110,
                  render: (v: number, r: StepRow) => (
                    <DrillNum
                      value={v} color={v ? C.open : undefined} strong={!!v} hint={t('cr.drill.clickHint')}
                      onClick={e => onPick(r.step, 'current', { x: e.clientX, y: e.clientY })}
                    />
                  ),
                },
                {
                  title: t('cr.flow.col.currentMax'), dataIndex: 'current_max_days',
                  align: 'right' as const, width: 130,
                  // 超过 30 天标红：这是「卡得该有人管了」的业务阈值，
                  // 与 rateColor 的阈值分属两套语义，故单独写在这里。
                  render: (v: number | null) => (
                    <span style={{ color: v != null && v > 30 ? C.delayed : undefined }}>
                      {fmtDays(v)}
                    </span>
                  ),
                },
              ]}
            />
          </Col>
          <Col xs={24} xl={11}>
            <ReactECharts
              option={option}
              style={{ height: 280 }}
              notMerge
              onEvents={{
                click: (p: any) => {
                  const s = steps[p?.dataIndex ?? -1]
                  if (!s) return
                  const kind: FlowKind =
                    p?.seriesName === t('cr.flow.legend.current') ? 'current' : 'arrived'
                  onPick(s.step, kind, {
                    x: p?.event?.event?.clientX, y: p?.event?.event?.clientY,
                  })
                },
              }}
            />
          </Col>
        </Row>
      ) : <Empty description={t('cr.flow.empty')} />}
    </CardBase>
  )
}
