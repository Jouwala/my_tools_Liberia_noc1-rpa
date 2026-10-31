/* ============================================================================
 * VmaxOverrideModal —— 人工覆写诊断结论
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.5；评审意见 4：「允许人工覆写」】
 *
 * 设计取舍（每一条都有理由，改之前先读）：
 *
 * ① **原始结论永不覆盖**。覆写是叠加：页面上同时有「系统判定」与「人工判定」，
 *    人工的置顶并标「人工」。理由：系统判定是可复现的证据链，覆盖掉它就
 *    等于毁掉这条投诉的取证基础，日后追责时说不清「当时为什么这么判」。
 *
 * ② **理由必填 ≥ 10 字**。理由会原样进导出文件。低于 10 字的理由基本等于
 *    没写（"没问题"/"已处理"），起不到留痕作用。
 *
 * ③ **按用户隔离**。同 `vmax_xdr_saved_record`：别人的覆写看不到，
 *    避免同一条投诉被多人互相改写。
 *
 * ④ 用 antd Modal 而非 DraggableClickModal：这里要**阻断**（必须做选择），
 *    可拖拽的浮层会被误认为可以拖走不管。项目里下钻一律用
 *    DraggableClickModal（不影响原页面），表单确认用 Modal —— 两者职责不同。
 * ========================================================================== */

import { useEffect, useState } from 'react'
import { Alert, Button, Descriptions, Input, Modal, Space, Typography } from 'antd'

import { useI18n } from '../i18n'
import { WH } from '../theme'
import type { OverrideInfo } from './VmaxDiagnosisCard'

const { TextArea } = Input
const { Text } = Typography

const MIN_REASON = 10

export default function VmaxOverrideModal({
  open,
  autoVerdict,
  existing,
  saving,
  onCancel,
  onSubmit,
  onRevoke,
}: {
  open: boolean
  /** 系统判定（只读展示，永不被改写） */
  autoVerdict: string
  /** 已有的覆写（编辑模式） */
  existing: OverrideInfo | null
  saving?: boolean
  onCancel: () => void
  onSubmit: (verdict: string, reason: string) => void
  onRevoke: () => void
}) {
  const { t } = useI18n()
  const [verdict, setVerdict] = useState('')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')

  // 每次打开都用最新值重置：残留上一次的输入比清空更危险（会误提交别人的结论）
  useEffect(() => {
    if (!open) return
    setVerdict(existing?.verdict_manual || '')
    setReason(existing?.reason || '')
    setErr('')
  }, [open, existing])

  const submit = () => {
    const v = verdict.trim()
    const r = reason.trim()
    if (!v) { setErr(t('vmaxq.override.manualRequired')); return }
    if (r.length < MIN_REASON) { setErr(t('vmaxq.override.reasonTooShort')); return }
    setErr('')
    onSubmit(v, r)
  }

  return (
    <Modal
      open={open}
      title={t('vmaxq.override.title')}
      onCancel={onCancel}
      width={640}
      destroyOnClose
      footer={(
        <Space>
          {existing && (
            <Button danger onClick={onRevoke} loading={saving}>
              {t('vmaxq.override.revoke')}
            </Button>
          )}
          <Button onClick={onCancel}>{t('vmaxq.override.cancel')}</Button>
          <Button type="primary" onClick={submit} loading={saving}>
            {t('vmaxq.override.submit')}
          </Button>
        </Space>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Alert
          type="info"
          showIcon
          message={t('vmaxq.override.note')}
          style={{ padding: '6px 12px' }}
        />

        <Descriptions
          size="small"
          bordered
          column={1}
          items={[{
            key: 'auto',
            label: t('vmaxq.override.auto'),
            children: <Text>{autoVerdict || '—'}</Text>,
          }]}
        />

        <div>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 12 }}>{t('vmaxq.override.manual')}</Text>
          </div>
          <TextArea
            value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            placeholder={t('vmaxq.override.manualPlaceholder')}
            autoSize={{ minRows: 2, maxRows: 4 }}
            maxLength={300}
            showCount
          />
        </div>

        <div>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 12 }}>{t('vmaxq.override.reason')}</Text>
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
              {reason.trim().length}/{MIN_REASON}
            </Text>
          </div>
          <TextArea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('vmaxq.override.reasonPlaceholder')}
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={500}
            showCount
          />
        </div>

        {!!err && (
          <Text style={{ fontSize: 12, color: WH.danger }}>{err}</Text>
        )}
      </div>
    </Modal>
  )
}
