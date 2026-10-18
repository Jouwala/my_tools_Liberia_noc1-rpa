/* ============================================================================
 * CR 变更分析 —— 审批步骤下钻弹窗（「谁卡在这一步、卡了多久」）
 * ============================================================================
 *
 * 与 `CrDrillModal`（按类别/状态看 CR 明细）分开的原因：两者的行类型不同 ——
 * 这里每一行是**一次步骤停留**而非一张 CR（同一张 CR 可能被驳回重走多步），
 * 列集合与排序语义（按等待天数倒序）也完全不同。合成一个组件会让两边都
 * 塞满 if 分支（AGENTS.md 第三节 2）。
 *
 * 取数与状态仍由页面持有；本组件只接收结果并展示。
 * ========================================================================== */

import { useMemo } from 'react'
import { Alert, Button, Space, Table, Tag } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import DraggableClickModal from '../../components/DraggableClickModal'
import { cardStyle } from '../../theme'
import { exportAoaReport } from '../../utils/excelReport'
import { formatDateTime } from '../../datetime'
import { useI18n } from '../../i18n'
import { fmt, type StepDrillRow } from './crTypes'

interface Props {
  open: boolean
  /** 弹窗标题后半段，如「CM Head Approval · 当前滞留」 */
  subtitle: string
  anchor: { x: number; y: number } | null
  onClose: () => void
  rows: StepDrillRow[]
  total: number
  truncated: boolean
  warn: string
  loading: boolean
  /** 导出文件名用：step + kind */
  fileKey: string
}

export default function CrWorkflowDrillModal({
  open, subtitle, anchor, onClose, rows, total, truncated, warn, loading, fileKey,
}: Props) {
  const { t } = useI18n()

  const columns = useMemo(() => {
    const cols = [
      { key: 'change_request_id', title: t('cr.flow.col.crId'), dataIndex: 'change_request_id', width: 165 },
      { key: 'status', title: t('cr.flow.col.status'), dataIndex: 'status', width: 175 },
      {
        key: 'days', title: t('cr.flow.col.days'), dataIndex: 'days', align: 'right' as const, width: 90,
        sorter: (a: StepDrillRow, b: StepDrillRow) => a.days - b.days,
        render: (v: number) => <b>{v.toFixed(1)}</b>,
      },
      {
        key: 'entered_at', title: t('cr.flow.col.entered'), dataIndex: 'entered_at', width: 160,
        render: (v: string | null) => (v ? formatDateTime(v, { fallback: '—' }) : '—'),
      },
      {
        key: 'left_at', title: t('cr.flow.col.left'), dataIndex: 'left_at', width: 160,
        render: (v: string | null, r: StepDrillRow) => (
          r.current
            // 当前滞留的单没有离开时间 —— 写明「仍在等待」，不要留空让人以为是缺数据
            ? <Tag color="orange">{t('cr.flow.stillWaiting')}</Tag>
            : (v ? formatDateTime(v, { fallback: '—' }) : '—')
        ),
      },
      { key: 'operator', title: t('cr.flow.col.operator'), dataIndex: 'operator', ellipsis: true, width: 210,
        render: (v: string | null) => fmt(v) },
      { key: 'result', title: t('cr.flow.col.result'), dataIndex: 'result', width: 110,
        render: (v: string | null) => fmt(v) },
      { key: 'next_status', title: t('cr.flow.col.next'), dataIndex: 'next_status', ellipsis: true, width: 190,
        render: (v: string | null) => fmt(v) },
      { key: 'change_category', title: t('cr.col.category'), dataIndex: 'change_category', width: 150,
        render: (v: string) => fmt(v) },
    ]
    return cols
  }, [t])

  const exportRows = () => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `CR_workflow_${fileKey || 'step'}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'CR流程明细',
      title: subtitle,
      header: columns.map(c => String(c.title)),
      rows: rows.map(r => [
        r.change_request_id, r.status, r.days, r.entered_at,
        r.current ? t('cr.flow.stillWaiting') : (r.left_at || '—'),
        fmt(r.operator), fmt(r.result), fmt(r.next_status), fmt(r.change_category),
      ]),
      numericCols: [2],
    })
  }

  return (
    <DraggableClickModal
      open={open}
      title={`${t('cr.flow.drill.title')} · ${subtitle}`}
      anchor={anchor}
      onClose={onClose}
      width={1180}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Tag color="blue">{t('cr.drill.count', { n: total })}</Tag>
        <Tag>{t('cr.drill.shown', { n: rows.length })}</Tag>
        <Button size="small" icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>
          {t('common.exportExcel')}
        </Button>
      </Space>

      {truncated && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={t('cr.drill.truncated', { total, shown: rows.length })}
        />
      )}
      {warn && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={warn} />
      )}

      <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
        <Table
          rowKey={(r, i) => `${r.change_request_id}-${r.step}-${i}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 1420 }}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        />
      </div>
    </DraggableClickModal>
  )
}
