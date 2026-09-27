/* ============================================================================
 * CR 变更分析 —— 下钻明细弹窗
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（AGENTS.md 第三节 2 的单文件 500 行上限）。
 * 负责：明细表格渲染、截断告警、本批明细导出。
 *
 * 取数与状态仍由页面持有（下钻参数要与卡片维度严格对应，放在页面上更清楚），
 * 本组件只接收结果并展示 —— 单一职责。
 * ========================================================================== */

import { useMemo } from 'react'
import { Alert, Button, Space, Table, Tag } from 'antd'
import { DownloadOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import DraggableClickModal from '../../components/DraggableClickModal'
import { cardStyle } from '../../theme'
import { exportAoaReport } from '../../utils/excelReport'
import { formatDateTime } from '../../datetime'
import { useI18n } from '../../i18n'
import { DETAIL_FIELDS, fmt, type DetailRow } from './crTypes'

interface Props {
  open: boolean
  /** 弹窗标题后半段：下钻的维度（如「已执行 · RAN · 2026-08」） */
  subtitle: string
  anchor: { x: number; y: number } | null
  onClose: () => void
  rows: DetailRow[]
  total: number
  truncated: boolean
  warn: string
  loading: boolean
  /** 导出文件名用的批次标识 */
  metric: string
}

export default function CrDrillModal({
  open, subtitle, anchor, onClose, rows, total, truncated, warn, loading, metric,
}: Props) {
  const { t } = useI18n()

  /** 表头顺序与 DETAIL_FIELDS 严格同序 —— 两者对不上会串列 */
  const headers = useMemo(() => ([
    t('cr.col.crId'), t('cr.col.title'), t('cr.col.status'),
    t('cr.col.category'), t('cr.col.subCategory'), t('cr.col.changeType'),
    t('cr.col.registered'), t('cr.col.plannedStart'), t('cr.col.plannedEnd'),
    t('cr.col.actualStart'), t('cr.col.actualEnd'), t('cr.col.closedTime'),
    t('cr.col.implementResult'), t('cr.col.creator'), t('cr.col.handler'),
    t('cr.col.implementer'), t('cr.col.vender'), t('cr.col.node'),
    t('cr.col.downtimeRequired'), t('cr.col.circle'),
  ]), [t])

  const columns = useMemo(() => DETAIL_FIELDS.map((f, i) => ({
    title: headers[i],
    dataIndex: f,
    ellipsis: true,
    width: f === 'cr_title' ? 260 : undefined,
    render: (v: unknown) => (
      // 时间字段统一走 datetime.ts 格式化，不在页面里自己 slice
      /_time$/.test(f) && v ? formatDateTime(v as string, { fallback: '—' }) : fmt(v)
    ),
  })), [headers])

  /** 只导出当前弹窗这一批明细 —— 与用户所见完全一致 */
  const exportDrill = () => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `CR_${metric || 'detail'}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'CR明细',
      title: subtitle,
      header: headers,
      rows: rows.map(r => DETAIL_FIELDS.map(f => fmt(r[f]))),
    })
  }

  return (
    <DraggableClickModal
      open={open}
      title={`${t('cr.drill.title')} · ${subtitle}`}
      anchor={anchor}
      onClose={onClose}
      width={1180}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Tag color="blue">{t('cr.drill.count', { n: total })}</Tag>
        <Tag>{t('cr.drill.shown', { n: rows.length })}</Tag>
        <Button size="small" icon={<DownloadOutlined />} onClick={exportDrill} disabled={!rows.length}>
          {t('common.exportExcel')}
        </Button>
      </Space>

      {/* 截断必须显式告警，不能让用户以为数据只有这些 */}
      {truncated && (
        <Alert
          type="warning" showIcon icon={<WarningOutlined />}
          style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={t('cr.drill.truncated', { total, shown: rows.length })}
        />
      )}
      {warn && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={warn} />
      )}

      {/* 弹窗内不再套一层卡片 —— 弹窗本身就是容器 */}
      <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
        <Table
          rowKey={(r, i) => `${r.change_request_id || 'row'}-${i}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 2200 }}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        />
      </div>
    </DraggableClickModal>
  )
}
