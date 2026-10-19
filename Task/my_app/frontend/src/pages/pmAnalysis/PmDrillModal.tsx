/* ============================================================================
 * PM 执行分析 —— 下钻明细弹窗
 * ============================================================================
 *
 * 与 `crAnalysis/CrDrillModal.tsx` 同构。负责：明细表格渲染、截断告警、
 * 本批明细导出。取数与状态由页面持有（下钻参数要与卡片维度严格对应）。
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
import { DETAIL_FIELDS, fmt, type DetailRow } from './pmTypes'

interface Props {
  open: boolean
  /** 弹窗标题后半段：下钻的维度 */
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

export default function PmDrillModal({
  open, subtitle, anchor, onClose, rows, total, truncated, warn, loading, metric,
}: Props) {
  const { t } = useI18n()

  /** 表头顺序与 DETAIL_FIELDS 严格同序 —— 两者对不上会串列 */
  const headers = useMemo(() => ([
    t('pm.col.pmtNo'), t('pm.col.status'), t('pm.col.title'), t('pm.col.pmpNo'),
    t('pm.col.overdueFlag'), t('pm.col.site'), t('pm.col.assetId'), t('pm.col.template'),
    t('pm.col.completedItems'), t('pm.col.totalItems'),
    t('pm.col.taskStart'), t('pm.col.taskEnd'), t('pm.col.created'),
    t('pm.col.scheduledAt'), t('pm.col.acceptedAt'), t('pm.col.pmApprovedAt'),
    t('pm.col.processedAt'), t('pm.col.flmApprovedAt'), t('pm.col.modifiedAt'),
    t('pm.col.creator'), t('pm.col.handler'), t('pm.col.source'),
  ]), [t])

  const columns = useMemo(() => DETAIL_FIELDS.map((f, i) => ({
    title: headers[i],
    dataIndex: f,
    ellipsis: true,
    width: f === 'title' ? 220 : (f === 'template' ? 200 : undefined),
    render: (v: unknown) => {
      // 时间字段统一走 datetime.ts 格式化，不在页面里自己 slice
      if (/_time$/.test(f) && v) return formatDateTime(v as string, { fallback: '—' })
      // 超期标记上色，一眼看出问题工单
      if (f === 'pmt_overdue' && v) {
        return v === 'Yes'
          ? <Tag color="red">{fmt(v)}</Tag>
          : <Tag color="green">{fmt(v)}</Tag>
      }
      return fmt(v)
    },
  })), [headers])

  /** 只导出当前弹窗这一批明细 —— 与用户所见完全一致 */
  const exportDrill = () => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `PM_${metric || 'detail'}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'PM Detail',
      title: subtitle,
      header: headers,
      rows: rows.map(r => DETAIL_FIELDS.map(f => fmt(r[f]))),
    })
  }

  return (
    <DraggableClickModal
      open={open}
      title={`${t('pm.drill.title')} · ${subtitle}`}
      anchor={anchor}
      onClose={onClose}
      width={1320}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Tag color="blue">{t('pm.drill.count', { n: total })}</Tag>
        <Tag>{t('pm.drill.shown', { n: rows.length })}</Tag>
        <Button size="small" icon={<DownloadOutlined />} onClick={exportDrill} disabled={!rows.length}>
          {t('common.exportExcel')}
        </Button>
      </Space>

      {/* 截断必须显式告警，不能让用户以为数据只有这些 */}
      {truncated && (
        <Alert
          type="warning" showIcon icon={<WarningOutlined />}
          style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={t('pm.drill.truncated', { total, shown: rows.length })}
        />
      )}
      {warn && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={warn} />
      )}

      {/* 弹窗内不再套一层卡片 —— 弹窗本身就是容器 */}
      <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
        <Table
          rowKey={(r, i) => `${r.pmt_no || 'row'}-${i}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 2600 }}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        />
      </div>
    </DraggableClickModal>
  )
}
