/* ============================================================================
 * VmaxCauseDetailModal —— CCA 根因详情弹窗
 * ============================================================================
 * 2026-11-07 从 VmaxUserCca.tsx 页内 JSX 抽出：区域 3 根因排行表（工作台）
 * 与证据抽屉里的 CCA 根因表都要打开同一份详情，两处各写一遍必然分叉。
 * 内容：置信度 / 对象 / 区域 / 劣化时段 + 上游 description / solution +
 * 逐时刻判定（app_info）。锚定点击位置（DraggableClickModal）。
 * ========================================================================== */

import { Descriptions, Table, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import type { CauseItem } from '../VmaxCcaCards'
import DraggableClickModal from '../DraggableClickModal'

const { Text } = Typography

const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

export default function VmaxCauseDetailModal({
  open, item, anchor, onClose,
}: {
  open: boolean
  item: CauseItem | null
  anchor: { x: number; y: number } | null
  onClose: () => void
}) {
  const { t } = useI18n()
  return (
    <DraggableClickModal
      open={open}
      title={item?.rule_name || t('vmaxq.causesCard')}
      anchor={anchor}
      onClose={onClose}
    >
      {item && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 380 }}>
          <Descriptions size="small" bordered column={1} items={[
            { key: 'conf', label: t('vmaxq.cause.confidence'),
              children: <Tag color={item.confidence >= 90 ? 'red' : 'orange'}>{item.confidence}%</Tag> },
            { key: 'obj', label: t('vmaxq.cause.object'),
              children: `${item.object_name}（${item.object_type}）` },
            { key: 'area', label: t('vmaxq.cause.area'),
              children: [item.province, item.city, item.vendor].filter(Boolean).join(' / ') || '—' },
            { key: 'poor', label: t('vmaxq.cause.poortime'),
              children: fmt(item.poortime) },
          ]} />
          <div>
            <Text strong>{t('vmaxq.cause.description')}</Text>
            <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{item.description}</div>
          </div>
          {item.solution && (
            <div>
              <Text strong>{t('vmaxq.cause.solution')}</Text>
              <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{item.solution}</div>
            </div>
          )}
          {!!item.app_info.length && (
            <div>
              <Text strong>{t('vmaxq.cause.timeline')}</Text>
              <Table
                style={{ marginTop: 4 }}
                rowKey={(r) => r.clttime + r.judge}
                columns={[
                  { title: t('vmaxq.cause.time'), dataIndex: 'clttime', width: 140 },
                  { title: t('vmaxq.cause.judge'), dataIndex: 'judge' },
                ]}
                dataSource={item.app_info}
                pagination={false}
                size="small"
              />
            </div>
          )}
        </div>
      )}
    </DraggableClickModal>
  )
}
