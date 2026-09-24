// ColumnPicker —— 通用「表格列显示控制」弹窗
//
// 用途：让用户自己勾选要显示哪些列（默认全选 / 或页面给的默认子集），
// 弹窗内支持关键字过滤、全选、清空、恢复默认。
//
// 为什么抽成组件（而不是各页各写一遍）：
//   SP 备件页（?page=sp_report）与耗材页（?page=com_report）共用 SpReportBase，
//   5 个 sheet 各有一套列集，逐个 sheet 复制一份勾选弹窗会明显重复；
//   且后续再有页面需要「用户自定义显示列」时可直接复用，避免第二份实现。
//
// 惯例对齐：与 `TableBrowser.tsx` 的列自定义弹窗保持同一套交互与 i18n 键前缀
// （`table.*`），使两处文案无需重复维护。保存与持久化由调用方负责 ——
// 本组件只产出「用户选中的列名数组」。
import { useEffect, useMemo, useState } from 'react'
import { Button, Checkbox, Col, Divider, Input, Modal, Row, Space, Typography } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

import { useI18n } from '../i18n'
import { WH } from '../theme'

const { Text } = Typography

export interface ColumnPickerProps {
  open: boolean
  /** 当前 sheet / 表格的全部可选列（真实存在的列名） */
  columns: string[]
  /** 已选中的列（打开弹窗时的初值） */
  value: string[]
  onApply: (cols: string[]) => void
  onCancel: () => void
  /** 恢复默认列（通常是页面声明的「优先展示列」） */
  onResetDefault?: () => void
  /** 弹窗标题；缺省用统一文案 */
  title?: string
}

export default function ColumnPicker({
  open,
  columns,
  value,
  onApply,
  onCancel,
  onResetDefault,
  title,
}: ColumnPickerProps) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<string[]>(value)
  const [kw, setKw] = useState('')

  // 只在「打开」这一个时刻把外部当前值灌进草稿。
  // ⚠️ 不能把 value 放进依赖：调用方的 value 多为 useMemo 派生数组，引用每次渲染都可能变，
  //    那样会在用户勾选过程中不断把草稿重置回原值（勾不上）。
  //    故本 effect 有意只依赖 open —— 需要时由调用方用 key 强制重挂载来重置。
  /* eslint-disable-next-line react-hooks/exhaustive-deps */
  useEffect(() => {
    if (open) {
      setDraft(value)
      setKw('')
    }
  }, [open])

  const shown = useMemo(() => {
    const q = kw.trim().toLowerCase()
    return q ? columns.filter(c => c.toLowerCase().includes(q)) : columns
  }, [columns, kw])

  // 「全选 / 清空」只作用于当前过滤结果，避免用户搜完子集后误清掉其他列
  const allShownChecked = shown.length > 0 && shown.every(c => draft.includes(c))

  const toggleAllShown = (checked: boolean) => {
    setDraft(prev => {
      const set = new Set(prev)
      for (const c of shown) {
        if (checked) set.add(c)
        else set.delete(c)
      }
      // 保持表格原始列序，而不是勾选顺序 —— 列顺序突变会让用户认不出表
      return columns.filter(c => set.has(c))
    })
  }

  return (
    <Modal
      open={open}
      title={title ?? t('table.colModalTitle')}
      onCancel={onCancel}
      width={'min(90vw, 40rem)' as unknown as number}
      footer={[
        onResetDefault && (
          <Button key="reset" onClick={onResetDefault}>{t('spRep.cols.resetDefault')}</Button>
        ),
        <Button key="cancel" onClick={onCancel}>{t('table.cancel')}</Button>,
        <Button key="ok" type="primary" onClick={() => onApply(draft)}>{t('table.apply')}</Button>,
      ].filter(Boolean)}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Checkbox
          checked={allShownChecked}
          indeterminate={!allShownChecked && shown.some(c => draft.includes(c))}
          onChange={e => toggleAllShown(e.target.checked)}
        >
          {t('table.selectAll')}
        </Checkbox>
        <Button size="small" onClick={() => setDraft([])}>{t('table.clearAll')}</Button>
        <Text type="secondary">{`${draft.length} / ${columns.length}`}</Text>
      </Space>

      <Input
        allowClear
        prefix={<SearchOutlined style={{ color: WH.textDim }} />}
        value={kw}
        onChange={e => setKw(e.target.value)}
        placeholder={t('table.filterColsPh')}
        style={{ marginBottom: 'var(--wh-space-sm)' }}
      />

      <div style={{
        maxHeight: '17.5rem', overflow: 'auto', border: WH.cardBorder,
        borderRadius: 'var(--wh-radius-sm)', padding: 'var(--wh-space-sm)',
      }}>
        {shown.length === 0 ? (
          <div style={{ color: WH.textDim, textAlign: 'center', padding: 'var(--wh-space-sm)' }}>
            {t('table.noMatchCols')}
          </div>
        ) : (
          <Checkbox.Group
            value={draft}
            onChange={v => setDraft(columns.filter(c => (v as string[]).includes(c)))}
            style={{ width: '100%' }}
          >
            <Row>
              {shown.map(c => (
                <Col xs={24} sm={12} lg={8} key={c} style={{ marginBottom: 'var(--wh-space-xs)' }}>
                  <Checkbox value={c}>
                    <span title={c} style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>{c}</span>
                  </Checkbox>
                </Col>
              ))}
            </Row>
          </Checkbox.Group>
        )}
      </div>

      <Divider style={{ margin: 'var(--wh-space-sm) 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>{t('spRep.cols.hint')}</Text>
    </Modal>
  )
}
