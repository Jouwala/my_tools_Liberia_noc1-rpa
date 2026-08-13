// 调度编辑器弹窗（P3#10 拆分自 DataSync.tsx）
import { useState, useEffect } from 'react'
import { Button, Input, Modal, Tag, Typography } from 'antd'
import { ScheduleOutlined } from '@ant-design/icons'
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import { CRON_PRESETS, cronToHuman } from './helpers'
import type { TaskInfo } from './types'

const { Text } = Typography

export function ScheduleEditor({
  open, task, locale, onClose, onSave,
}: {
  open: boolean
  task: TaskInfo | null
  locale: 'zh' | 'en'
  onClose: () => void
  onSave: (taskId: string, cron: string) => Promise<void>
}) {
  const { t } = useI18n()
  const [cronInput, setCronInput] = useState('')
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (task) {
      setCronInput(task.current_cron)
      setSelectedPreset(null)
    }
  }, [task])

  const handlePreset = (cron: string) => {
    setCronInput(cron)
    setSelectedPreset(cron)
  }

  const handleSave = async () => {
    if (!task || !cronInput.trim()) return
    setSaving(true)
    try {
      await onSave(task.task_id, cronInput.trim())
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const presets = [...CRON_PRESETS.hourly, ...CRON_PRESETS.daily, ...CRON_PRESETS.weekly]

  return (
    <Modal
      title={
        <span style={{ color: WH.text }}>
          <ScheduleOutlined style={{ marginRight: 8, color: WH.teal }} />
          {locale === 'zh' ? `编辑调度 - ${task?.name}` : `Edit Schedule - ${task?.name}`}
        </span>
      }
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving}
      okText={locale === 'zh' ? '保存' : 'Save'}
      cancelText={locale === 'zh' ? '取消' : 'Cancel'}
      width={640}
      styles={{
        root: { background: WH.bg },
        header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid var(--wh-subtle-border)' },
        body: { background: WH.bg },
      }}
    >
      {task && (
        <div>
          {/* Current schedule */}
          <div style={{ marginBottom: 16 }}>
            <Text style={{ color: WH.textMuted }}>{locale === 'zh' ? '当前调度：' : 'Current: '}</Text>
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {cronToHuman(task.current_cron, locale)}
            </Tag>
            <Text code style={{ marginLeft: 8, color: WH.textMuted, background: 'var(--wh-input-bg)' }}>{task.current_cron}</Text>
          </div>

          {/* Presets */}
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ display: 'block', marginBottom: 8, color: WH.text }}>
              {locale === 'zh' ? '⏰ 快捷预设' : '⏰ Quick Presets'}
            </Text>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {presets.map(p => (
                <Button
                  key={p.cron}
                  size="small"
                  type={selectedPreset === p.cron ? 'primary' : 'default'}
                  onClick={() => handlePreset(p.cron)}
                  style={selectedPreset !== p.cron ? { color: WH.text, borderColor: 'var(--wh-subtle-border)', background: 'var(--wh-subtle-bg)' } : undefined}
                >
                  {locale === 'zh' ? p.label_zh : p.label_en}
                </Button>
              ))}
            </div>
          </div>

          {/* Custom cron */}
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ display: 'block', marginBottom: 8, color: WH.text }}>
              {locale === 'zh' ? '✏️ 自定义 Cron 表达式' : '✏️ Custom Cron Expression'}
            </Text>
            <Input
              value={cronInput}
              onChange={e => { setCronInput(e.target.value); setSelectedPreset(null) }}
              placeholder={t('sync.cronPlaceholder')}
              style={{ fontFamily: 'monospace', fontSize: 14, background: 'var(--wh-input-bg)', color: WH.text, borderColor: 'var(--wh-input-border)' }}
            />
            <div style={{ marginTop: 8, color: WH.textDim, fontSize: 12 }}>
              {locale === 'zh'
                ? '格式: 分 时 日 月 周  示例: 0 8 * * * = 每天8点 | 0 */4 * * * = 每4小时 | 30 7 * * 1-5 = 工作日7:30'
                : 'Format: min hr day mon dow  e.g.: 0 8 * * * = Daily 8am | 0 */4 * * * = Every 4h | 30 7 * * 1-5 = Weekdays 7:30'
              }
            </div>
            {cronInput && (
              <div style={{ marginTop: 8 }}>
                <Text style={{ color: WH.textMuted }}>{locale === 'zh' ? '预览：' : 'Preview: '}</Text>
                <Tag color="green" style={{ marginLeft: 8 }}>
                  {cronToHuman(cronInput, locale)}
                </Tag>
              </div>
            )}
          </div>

          {/* Default cron */}
          <div>
            <Text style={{ color: WH.textMuted }}>
              {locale === 'zh' ? '默认值：' : 'Default: '}
            </Text>
            <Button
              size="small"
              type="link"
              onClick={() => handlePreset(task.default_cron)}
              style={{ color: WH.teal }}
            >
              {cronToHuman(task.default_cron, locale)} ({task.default_cron})
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
