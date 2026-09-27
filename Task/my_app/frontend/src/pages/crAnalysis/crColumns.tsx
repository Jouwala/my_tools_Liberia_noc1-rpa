/* ============================================================================
 * CR 变更分析 —— 类别表格 / 子类别表格的列定义
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（AGENTS.md 第三节 2 的单文件 500 行上限）。
 *
 * 这里的列定义**每个数字都可点击下钻**（AGENTS.md 第三节 1b 的硬要求），
 * 点击时把 metric + 维度交给页面提供的 `onDrill` 回调 —— 列定义本身不取数。
 * ========================================================================== */

import type { ColumnsType } from 'antd/es/table'
import { Typography } from 'antd'

import { fmtRate, rateColor, COUNT_FIELDS, type CatRow, type Metric, type SubRow } from './crTypes'
import type { ChartColors } from './crCharts'

const { Text } = Typography

/** 点击下钻的签名：metric + 类别 + 子类别 + 月份 + 鼠标坐标（用于弹窗定位） */
export type OnDrill = (
  metric: Metric, category: string, sub: string, month: string,
  at?: { x: number; y: number },
) => void

/** 可点击的数字单元：整格可点，光标 + 悬停虚线下划线提示可交互 */
export function DrillNum({ value, onClick, color, strong }: {
  value: number | string
  onClick: (e: React.MouseEvent<HTMLElement>) => void
  color?: string
  strong?: boolean
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
      title="点击查看明细"
    >
      {value}
    </span>
  )
}

/**
 * 类别明细表的列定义。
 * 计数列直接落到同名 metric；**比率列落到它的分子**（达成率→已执行、
 * 按时率→按时、关闭率→已关闭），这样点开明细的行数与比率的分母口径自洽。
 */
export function categoryColumns(
  t: (k: string) => string, onDrill: OnDrill, C: ChartColors,
): ColumnsType<CatRow> {
  const numCol = (titleKey: string, field: typeof COUNT_FIELDS[number], color?: string) => ({
    title: t(titleKey),
    dataIndex: field,
    align: 'right' as const,
    sorter: (a: CatRow, b: CatRow) => a[field] - b[field],
    render: (v: number, r: CatRow) => (
      <DrillNum
        value={v} color={color}
        onClick={e => onDrill(field, r.category, '', '', { x: e.clientX, y: e.clientY })}
      />
    ),
  })

  const rateCol = (
    titleKey: string, field: 'completion_rate' | 'on_time_rate' | 'closure_rate', metric: Metric,
  ) => ({
    title: t(titleKey),
    dataIndex: field,
    align: 'right' as const,
    width: 110,
    sorter: (a: CatRow, b: CatRow) => (a[field] ?? -1) - (b[field] ?? -1),
    render: (v: number | null, r: CatRow) => (
      <DrillNum
        value={fmtRate(v)} color={rateColor(v)} strong
        onClick={e => onDrill(metric, r.category, '', '', { x: e.clientX, y: e.clientY })}
      />
    ),
  })

  return [
    {
      title: t('cr.col.category'), dataIndex: 'category', fixed: 'left' as const, width: 150,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    numCol('cr.col.total', 'total', C.total),
    numCol('cr.col.planned', 'planned', C.planned),
    numCol('cr.col.executed', 'executed', C.executed),
    numCol('cr.col.unexecuted', 'unexecuted', C.unexecuted),
    numCol('cr.col.onTime', 'on_time', C.onTime),
    numCol('cr.col.delayed', 'delayed', C.delayed),
    numCol('cr.col.closed', 'closed', C.closed),
    numCol('cr.col.open', 'open', C.open),
    rateCol('cr.kpi.completionRate', 'completion_rate', 'executed'),
    rateCol('cr.kpi.onTimeRate', 'on_time_rate', 'on_time'),
    rateCol('cr.kpi.closureRate', 'closure_rate', 'closed'),
  ]
}

/** 子类别（设备类型）表的列定义 —— 第二层维度 */
export function subCategoryColumns(
  t: (k: string) => string, onDrill: OnDrill, C: ChartColors,
): ColumnsType<SubRow> {
  return [
    { title: t('cr.col.category'), dataIndex: 'category', width: 150 },
    {
      title: t('cr.col.subCategory'), dataIndex: 'sub_category',
      render: (v: string, r: SubRow) => (
        <DrillNum value={v} onClick={e => onDrill('total', r.category, v, '', { x: e.clientX, y: e.clientY })} />
      ),
    },
    {
      title: t('cr.col.total'), dataIndex: 'total', align: 'right' as const, width: 100,
      sorter: (a: SubRow, b: SubRow) => a.total - b.total,
      render: (v: number, r: SubRow) => (
        <DrillNum value={v}
          onClick={e => onDrill('total', r.category, r.sub_category, '', { x: e.clientX, y: e.clientY })} />
      ),
    },
    {
      title: t('cr.col.executed'), dataIndex: 'executed', align: 'right' as const, width: 100,
      sorter: (a: SubRow, b: SubRow) => a.executed - b.executed,
      render: (v: number, r: SubRow) => (
        <DrillNum value={v} color={C.executed}
          onClick={e => onDrill('executed', r.category, r.sub_category, '', { x: e.clientX, y: e.clientY })} />
      ),
    },
  ]
}
