/* ============================================================================
 * PM 执行分析 —— KPI 数字区（8 个计数卡 + 3 个比率卡）
 * ============================================================================
 *
 * 从 `PmExecutionAnalysis.tsx` 拆出来的**纯展示**组件：只接收已经算好的
 * 汇总值与回调，不取数、不持有状态。拆分的直接原因是页面文件超过
 * `AGENTS.md` 第三节 2 的「单文件不超过 500 行」。
 *
 * ⚠️ 每个数字都可点（AGENTS.md 第三节 1b）：计数卡与比率卡都透传 `onDrill`，
 *    比率卡把分母写在数字下方，避免「100%」在小样本下被误读。
 * ========================================================================== */

import { Col, Row, Typography } from 'antd'

import { CardBase, StatCard } from '../../components/cards'
import { WH } from '../../theme'
import { fmtRate, rateColor, rateColorDesc, rateLevel, rateLevelDesc, type Metric } from './pmTypes'
import type { ChartColors } from './pmCharts'

const { Text } = Typography

/** 点击下钻回调：metric + 鼠标坐标（用于弹窗定位） */
export type OnKpiDrill = (metric: Metric, at: { x: number; y: number }) => void

/** 带插值的翻译签名（`t()` 第二参数是插值参数对象，见 i18n.tsx:5728） */
type TFn = (key: string, params?: Record<string, string | number>) => string

export interface KpiCardsProps {
  t: TFn
  C: ChartColors
  /** 8 个计数卡的值，键与 metric 同名 */
  counts: {
    total: number; closed: number; open: number; overdue: number; on_time: number
    not_started: number; closed_overdue: number; open_overdue: number
  }
  plans: number
  /** 3 个比率卡 */
  rates: { closure: number | null; overdue: number | null; started: number | null }
  onDrill: OnKpiDrill
}

export default function PmKpiCards({ t, C, counts, plans, rates, onDrill }: KpiCardsProps) {
  /** 计数卡定义集中一处：键、取值、配色、下钻 metric 一眼对齐 */
  const kpis: { key: string; value: number; color: string; metric: Metric }[] = [
    { key: 'pm.col.total', value: counts.total, color: C.total, metric: 'total' },
    { key: 'pm.col.closed', value: counts.closed, color: C.closed, metric: 'closed' },
    { key: 'pm.col.open', value: counts.open, color: C.open, metric: 'open' },
    { key: 'pm.col.overdue', value: counts.overdue, color: C.overdue, metric: 'overdue' },
    { key: 'pm.col.onTime', value: counts.on_time, color: C.onTime, metric: 'on_time' },
    { key: 'pm.col.notStarted', value: counts.not_started, color: C.notStarted, metric: 'not_started' },
    { key: 'pm.col.closedOverdue', value: counts.closed_overdue, color: C.overdue, metric: 'closed_overdue' },
    { key: 'pm.col.openOverdue', value: counts.open_overdue, color: C.overdue, metric: 'open_overdue' },
  ]

  /** 比率卡：分母写在数字下方；超期率是「越低越好」，用 desc 版染色 */
  const rateCards: {
    key: string; rate: number | null; desc: boolean; hint: string; metric: Metric
  }[] = [
    {
      key: 'pm.kpi.closureRate', rate: rates.closure, desc: false,
      hint: t('pm.kpi.closureRateHint', { closed: counts.closed, total: counts.total }),
      metric: 'closed',
    },
    {
      key: 'pm.kpi.overdueRate', rate: rates.overdue, desc: true,
      hint: t('pm.kpi.overdueRateHint', { overdue: counts.overdue, total: counts.total }),
      metric: 'overdue',
    },
    {
      key: 'pm.kpi.startRate', rate: rates.started, desc: false,
      hint: t('pm.kpi.startRateHint', {
        started: counts.total - counts.not_started, total: counts.total,
      }),
      metric: 'not_started',
    },
  ]

  return (
    <>
      {/* 计数卡行 */}
      <Row gutter={[12, 12]}>
        {kpis.map((k, i) => (
          <Col key={k.metric} xs={12} sm={8} lg={6} xl={3}>
            <StatCard
              title={t(k.key)} value={k.value} accentColor={k.color}
              subText={i === 0 ? t('pm.kpi.plans', { n: plans }) : undefined}
              onClick={e => onDrill(k.metric, { x: e.clientX, y: e.clientY })}
            />
          </Col>
        ))}
      </Row>

      {/* 比率卡行 */}
      <Row gutter={[12, 12]} style={{ marginTop: 'var(--wh-space-md)' }}>
        {rateCards.map(c => (
          <Col key={c.key} xs={24} md={8}>
            <CardBase
              level={c.desc ? rateLevelDesc(c.rate) : rateLevel(c.rate)}
              interactive
              onClick={e => onDrill(c.metric, { x: e.clientX, y: e.clientY })}
            >
              <div style={{ fontSize: 13, color: WH.textMuted }}>{t(c.key)}</div>
              <div style={{
                fontSize: 28, fontWeight: 700, margin: '4px 0',
                color: c.desc ? rateColorDesc(c.rate) : rateColor(c.rate),
              }}>
                {fmtRate(c.rate)}
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>{c.hint}</Text>
            </CardBase>
          </Col>
        ))}
      </Row>
    </>
  )
}
