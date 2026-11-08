/* ============================================================================
 * VmaxCrossCheckKpiTable —— 小区级 KPI 并列对照表（P3-2 交叉验证卡的一部分）
 * ============================================================================
 * 从 VmaxCrossCheck.tsx 拆出（AGENTS.md 三.2：组件单文件保持小）：这里只做
 * 「CCA 小区 KPI 原值」与「RAN(32) 同小区均值」的并排列出，**不做阈值判定**，
 * 也不参与结论（阈值唯一出处 THRESHOLDS，结论唯一出处 buildVerdict）。
 * 列头 ⓘ 讲这一列的算法，数字悬浮讲这一格的构成（AGENTS.md 三.3c）。
 * ========================================================================== */

import { Space, Table, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { ExplainIcon, ExplainPopover } from '../MetricExplain'
import {
  CROSS_KPI_COL_KEY, type CrossCellKpi, type KpiCompareRow,
} from '../../lib/vmaxCellCrossCheck'

const { Text } = Typography

type KpiTableRow = {
  key: string
  cell: string
  isPrimary: boolean
  row: KpiCompareRow
}

/** 数值 + 单位；null 显示 —（无采样不是 0，AGENTS.md 三.6） */
const fmtNum = (v: number | null, unit: string): string =>
  v === null ? '—' : `${v}${unit ? ` ${unit}` : ''}`

export default function VmaxCrossCheckKpiTable({ cellKpis }: { cellKpis: CrossCellKpi[] }) {
  const { t } = useI18n()

  const rows: KpiTableRow[] = cellKpis.flatMap((entry) =>
    entry.rows.map((row) => ({
      key: `${entry.cell}-${row.id}`, cell: entry.cell, isPrimary: entry.isRanPrimary, row,
    })))
  if (!rows.length) return null

  const columns = [
    {
      title: t(CROSS_KPI_COL_KEY.cell), dataIndex: 'cell', width: 230, ellipsis: true,
      render: (cell: string, r: KpiTableRow) => (
        <Space size={4}>
          <span>{cell}</span>
          {r.isPrimary && <Tag color="blue">{t(CROSS_KPI_COL_KEY.primaryTag)}</Tag>}
        </Space>
      ),
    },
    {
      title: t(CROSS_KPI_COL_KEY.metric), width: 90,
      render: (_: unknown, r: KpiTableRow) => <Text strong>{r.row.id.toUpperCase()}</Text>,
    },
    {
      // 列头 ⓘ：讲这一列是「32 侧该小区全部有效采样的算术平均」，并声明不判阈值
      title: (
        <Space size={4}>
          <span>{t(CROSS_KPI_COL_KEY.ran)}</span>
          <ExplainIcon text={t('vmaxq.ws.cross.kpi.explain')} />
        </Space>
      ),
      width: 160,
      render: (_: unknown, r: KpiTableRow) => {
        const { row } = r
        const tip = row.ranAvg === null
          ? t('vmaxq.ws.cross.kpi.noSample', { cell: r.cell })
          : t('vmaxq.ws.cross.kpi.cellTip', { cell: r.cell, n: row.ranSamples })
        return (
          <ExplainPopover text={tip}>
            <span style={{ fontWeight: r.isPrimary ? 600 : 400 }}>
              {fmtNum(row.ranAvg, row.unit)}
            </span>
          </ExplainPopover>
        )
      },
    },
    {
      title: t(CROSS_KPI_COL_KEY.cca), width: 260,
      render: (_: unknown, r: KpiTableRow) => (
        r.row.cca.length ? (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {r.row.cca.map((it) => (
              <span key={it.code}>
                {it.name}：{it.value ?? '—'}
              </span>
            ))}
          </div>
        ) : <Text type="secondary">—</Text>
      ),
    },
  ]

  return (
    <>
      <Text strong style={{ fontSize: 12, display: 'block', margin: '12px 0 4px' }}>
        {t('vmaxq.ws.cross.kpi.title')}
      </Text>
      <Table
        size="small" rowKey="key" pagination={false}
        columns={columns} dataSource={rows} scroll={{ x: 740 }}
      />
    </>
  )
}
