/* ============================================================================
 * PM 执行分析 —— 里程碑下钻弹窗（「谁卡在这一环节、卡了多久」）
 * ============================================================================
 *
 * 与 `PmDrillModal`（按 KPI / 计划 / 站点看工单明细）分开的原因：这里的行是
 * 「一次里程碑停留」记录（进入时间、离开时间、已等待天数），列集合与排序
 * 语义（按等待天数倒序）都不同。合成一个组件会让两边都塞满 if 分支
 * （AGENTS.md 第三节 2）。
 *
 * 取数与状态由页面持有；本组件只接收结果并展示。
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
import { fmt, type MilestoneDrillRow } from './pmTypes'

interface Props {
  open: boolean
  /** 弹窗标题后半段，如「PM 经理审批 · 当前滞留」 */
  subtitle: string
  anchor: { x: number; y: number } | null
  onClose: () => void
  rows: MilestoneDrillRow[]
  total: number
  truncated: boolean
  warn: string
  loading: boolean
  /** 导出文件名用：key + kind */
  fileKey: string
}

export default function PmMilestoneDrillModal({
  open, subtitle, anchor, onClose, rows, total, truncated, warn, loading, fileKey,
}: Props) {
  const { t } = useI18n()

  const columns = useMemo(() => [
    { key: 'pmt_no', title: t('pm.col.pmtNo'), dataIndex: 'pmt_no', width: 160 },
    { key: 'status', title: t('pm.col.status'), dataIndex: 'status', width: 175 },
    {
      key: 'days', title: t('pm.ms.col.days'), dataIndex: 'days',
      align: 'right' as const, width: 100,
      sorter: (a: MilestoneDrillRow, b: MilestoneDrillRow) => (a.days ?? -1) - (b.days ?? -1),
      // 缺进入时间的行（导出不全）没有天数，显示 '—' 而不是 0
      render: (v: number | null) => (v == null ? '—' : <b>{v.toFixed(1)}</b>),
    },
    {
      key: 'entered_at', title: t('pm.ms.col.entered'), dataIndex: 'entered_at', width: 160,
      render: (v: string | null) => (v ? formatDateTime(v, { fallback: '—' }) : '—'),
    },
    {
      key: 'left_at', title: t('pm.ms.col.left'), dataIndex: 'left_at', width: 160,
      render: (v: string | null, r: MilestoneDrillRow) => (
        r.current
          // 当前滞留的单没有离开时间 —— 写明「仍在等待」，不要留空让人以为是缺数据
          ? <Tag color="orange">{t('pm.ms.stillWaiting')}</Tag>
          : (v ? formatDateTime(v, { fallback: '—' }) : '—')
      ),
    },
  ], [t])

  const exportRows = () => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `PM_milestone_${fileKey || 'step'}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'PM里程碑明细',
      title: subtitle,
      header: columns.map(c => String(c.title)),
      rows: rows.map(r => [
        r.pmt_no, r.status, r.days ?? '', r.entered_at || '',
        r.current ? t('pm.ms.stillWaiting') : (r.left_at || '—'),
      ]),
      numericCols: [2],
    })
  }

  return (
    <DraggableClickModal
      open={open}
      title={`${t('pm.ms.drill.title')} · ${subtitle}`}
      anchor={anchor}
      onClose={onClose}
      width={860}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Tag color="blue">{t('pm.drill.count', { n: total })}</Tag>
        <Tag>{t('pm.drill.shown', { n: rows.length })}</Tag>
        <Button size="small" icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>
          {t('common.exportExcel')}
        </Button>
      </Space>

      {truncated && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={t('pm.drill.truncated', { total, shown: rows.length })}
        />
      )}
      {warn && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={warn} />
      )}

      <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
        <Table
          rowKey={(r, i) => `${r.pmt_no}-${r.milestone}-${i}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="small"
          scroll={{ x: 760 }}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        />
      </div>
    </DraggableClickModal>
  )
}
