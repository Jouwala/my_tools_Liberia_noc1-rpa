/* ============================================================================
 * PM 执行分析 —— 计划表 / 站点表的列定义
 * ============================================================================
 *
 * 与 `crAnalysis/crColumns.tsx` 同构。这里的列定义**每个数字都可点击下钻**
 * （AGENTS.md 第三节 1b 的硬要求），点击时把 metric + 维度交给页面提供的
 * `onDrill` 回调 —— 列定义本身不取数。
 * ========================================================================== */

import type { ColumnsType } from 'antd/es/table'
import { Progress, Typography } from 'antd'

import {
  fmtNum, fmtRate, rateColor, rateColorDesc, COUNT_FIELDS,
  type Metric, type PlanRow, type SiteRow,
} from './pmTypes'
import type { ChartColors } from './pmCharts'

const { Text } = Typography

/** 点击下钻的签名：metric + 各维度 + 鼠标坐标（用于弹窗定位） */
export type OnDrill = (
  metric: Metric, dims: { pmp_no?: string; status?: string; site_name?: string; month?: string },
  at?: { x: number; y: number },
) => void

/** 可点击的数字单元：整格可点，光标 + 悬停虚线下划线提示可交互 */
export function DrillNum({ value, onClick, color, strong, hint }: {
  value: number | string
  onClick: (e: React.MouseEvent<HTMLElement>) => void
  color?: string
  strong?: boolean
  /** 悬停提示（可访问性 + 可发现性）。由调用方传入已翻译文案，本组件不取 i18n */
  hint: string
}) {
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') onClick(e as unknown as React.MouseEvent<HTMLElement>)
      }}
      style={{
        cursor: 'pointer', color, fontWeight: strong ? 700 : undefined,
        textDecoration: 'underline dotted', textUnderlineOffset: 3,
      }}
      title={hint}
    >
      {value}
    </span>
  )
}

/**
 * PM 计划表的列定义。
 * 计数列落到同名 metric；**比率列落到它的分子**
 * （关闭率→已关闭、超期率→超期、开始率→未开始的反面即 total 减去未开始，
 * 用 not_started 更直接指向「问题工单」）。
 */
export function planColumns(
  t: (k: string) => string, onDrill: OnDrill, C: ChartColors,
): ColumnsType<PlanRow> {
  const numCol = (titleKey: string, field: typeof COUNT_FIELDS[number], color?: string) => ({
    title: t(titleKey),
    dataIndex: field,
    align: 'right' as const,
    width: 88,
    sorter: (a: PlanRow, b: PlanRow) => a[field] - b[field],
    render: (v: number, r: PlanRow) => (
      <DrillNum
        value={v} color={color} hint={t('pm.drill.clickHint')}
        onClick={e => onDrill(field, { pmp_no: r.pmp_no }, { x: e.clientX, y: e.clientY })}
      />
    ),
  })

  const rateCol = (
    titleKey: string, field: 'closure_rate' | 'overdue_rate' | 'item_rate',
    metric: Metric, desc = false,
  ) => ({
    title: t(titleKey),
    dataIndex: field,
    align: 'right' as const,
    width: 100,
    sorter: (a: PlanRow, b: PlanRow) => (a[field] ?? -1) - (b[field] ?? -1),
    render: (v: number | null, r: PlanRow) => (
      <DrillNum
        value={fmtRate(v)} color={desc ? rateColorDesc(v) : rateColor(v)} strong
        hint={t('pm.drill.clickHint')}
        onClick={e => onDrill(metric, { pmp_no: r.pmp_no }, { x: e.clientX, y: e.clientY })}
      />
    ),
  })

  return [
    {
      title: t('pm.col.pmpNo'), dataIndex: 'pmp_no', fixed: 'left' as const, width: 160,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    numCol('pm.col.total', 'total', C.total),
    numCol('pm.col.closed', 'closed', C.closed),
    numCol('pm.col.open', 'open', C.open),
    numCol('pm.col.overdue', 'overdue', C.overdue),
    numCol('pm.col.notStarted', 'not_started', C.notStarted),
    // 条目进度：completed/total 的合计，用进度条比两个裸数字直观
    {
      title: t('pm.col.items'), dataIndex: 'item_rate', width: 150,
      sorter: (a: PlanRow, b: PlanRow) => (a.item_rate ?? -1) - (b.item_rate ?? -1),
      render: (_: unknown, r: PlanRow) => {
        const pct = r.item_rate == null ? 0 : Math.min(100, r.item_rate)
        return (
          <div title={`${fmtNum(r.completed_items)} / ${fmtNum(r.total_items)}`}>
            <Progress
              percent={pct} size="small" showInfo={false}
              strokeColor={rateColor(r.item_rate)}
            />
            <Text type="secondary" style={{ fontSize: 11 }}>
              {fmtNum(r.completed_items)}/{fmtNum(r.total_items)}
            </Text>
          </div>
        )
      },
    },
    {
      title: t('pm.col.sites'), dataIndex: 'sites', align: 'right' as const, width: 80,
      sorter: (a: PlanRow, b: PlanRow) => a.sites - b.sites,
    },
    rateCol('pm.kpi.closureRate', 'closure_rate', 'closed'),
    rateCol('pm.kpi.overdueRate', 'overdue_rate', 'overdue', true),
  ]
}

/** 站点表的列定义 —— 运维抓手维度 */
export function siteColumns(
  t: (k: string) => string, onDrill: OnDrill, C: ChartColors,
): ColumnsType<SiteRow> {
  const numCell = (
    field: 'total' | 'overdue' | 'open', metric: Metric, color?: string,
  ) => ({
    title: t(`pm.col.${field === 'open' ? 'open' : field}`),
    dataIndex: field,
    align: 'right' as const,
    width: 96,
    sorter: (a: SiteRow, b: SiteRow) => a[field] - b[field],
    render: (v: number, r: SiteRow) => (
      <DrillNum
        value={v} color={color} hint={t('pm.drill.clickHint')}
        onClick={e => onDrill(metric, { site_name: r.site_name }, { x: e.clientX, y: e.clientY })}
      />
    ),
  })

  return [
    {
      title: t('pm.col.site'), dataIndex: 'site_name',
      render: (v: string, r: SiteRow) => (
        <DrillNum value={v} hint={t('pm.drill.clickHint')}
          onClick={e => onDrill('total', { site_name: r.site_name }, { x: e.clientX, y: e.clientY })} />
      ),
    },
    numCell('total', 'total', C.total),
    numCell('overdue', 'overdue', C.overdue),
    numCell('open', 'open', C.open),
  ]
}
