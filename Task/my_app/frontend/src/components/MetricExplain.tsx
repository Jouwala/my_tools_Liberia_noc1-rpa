// 通用「计算说明」备注组件
// 与 PacketLoss 看板一致的 "? " 悬停气泡（含复制按钮），供各 dashboard 的指标卡/标题复用，
// 保证全站备注说明视觉与交互统一。
import { useState, useCallback, type ReactNode } from 'react'
import { Popover, Button } from 'antd'
import { InfoCircleOutlined, CopyOutlined } from '@ant-design/icons'
import { WH } from '../theme'
import { useI18n } from '../i18n'

type Placement =
  | 'top' | 'bottom' | 'left' | 'right'
  | 'topLeft' | 'topRight' | 'bottomLeft' | 'bottomRight'

interface ExplainIconProps {
  text: string
  size?: number
  placement?: Placement
}

// 核心：? 图标 + 悬停气泡（含复制）。不依赖外部 t，内部自行取 i18n。
export const ExplainIcon = ({ text, size = 13, placement = 'top' }: ExplainIconProps) => {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async () => {
    if (!text) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
      }
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }, [text])
  if (!text) return null
  return (
    <Popover
      trigger="hover"
      placement={placement}
      mouseEnterDelay={0.1}
      content={
        <div style={{ maxWidth: 300, fontSize: 12, lineHeight: 1.7 }}>
          <div style={{ color: WH.textMuted, whiteSpace: 'pre-line' }}>{text}</div>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={copy}
            style={{ paddingLeft: 0, marginTop: 8, height: 'auto', color: WH.teal }}>
            {copied ? t('explain.copied') : t('explain.copy')}
          </Button>
        </div>
      }
    >
      <span style={{ cursor: 'help', color: WH.textDim, fontSize: size, lineHeight: 1 }}>
        <InfoCircleOutlined />
      </span>
    </Popover>
  )
}

// 卡片右上角绝对定位的 ? 说明（与 PacketLoss SummaryCard 一致；点击不触发卡片下钻）
export const ExplainCorner = ({ text, size, placement }: { text: string; size?: number; placement?: Placement }) => (
  <span
    style={{ position: 'absolute', top: 6, right: 8, zIndex: 2, cursor: 'help' }}
    onClick={e => e.stopPropagation()}
  >
    <ExplainIcon text={text} size={size} placement={placement} />
  </span>
)

// 文字标签 + 内联 ? 说明
export const ExplainLabel = ({ label, text, size, placement }: { label: ReactNode; text: string; size?: number; placement?: Placement }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
    {label}
    <ExplainIcon text={text} size={size} placement={placement} />
  </span>
)
