// 通用「计算说明」备注组件
// 与 PacketLoss 看板一致的 "? " 悬停气泡（含复制按钮），供各 dashboard 的指标卡/标题复用，
// 保证全站备注说明视觉与交互统一。
// ExplainPopover 是底层（包住任意节点，含表格里的数字本身），
// ExplainIcon / ExplainCorner / ExplainLabel 是它的三种摆放方式。
import { useState, useCallback, type ReactNode } from 'react'
import { Popover, Button } from 'antd'
import { InfoCircleOutlined, QuestionCircleOutlined, CopyOutlined } from '@ant-design/icons'
import { WH } from '../theme'
import { useI18n } from '../i18n'
import { renderRich, stripBold } from '../utils/richText'

type Placement =
  | 'top' | 'bottom' | 'left' | 'right'
  | 'topLeft' | 'topRight' | 'bottomLeft' | 'bottomRight'

interface ExplainIconProps {
  text: string
  size?: number | string
  placement?: Placement
  /** 图标形状：默认 info（ⓘ，全站既有观感）；question = 圆圈问号（用户明确要「问号」时用） */
  icon?: 'info' | 'question'
}

interface ExplainPopoverProps {
  text: string
  placement?: Placement
  children: ReactNode
}

// 底层：把任意节点包成「悬停出气泡（带复制）」。图标版与「直接包住数字」的版本共用
// 同一套外观、复制行为与 i18n，避免每页自己写一遍 Popover。
export const ExplainPopover = ({ text, placement = 'top', children }: ExplainPopoverProps) => {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async () => {
    if (!text) return
    // 复制的应是「能直接读的文字」，不是带 ** 的源码 —— 星号只服务于界面强调
    const plain = stripBold(text)
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(plain)
      } else {
        const ta = document.createElement('textarea')
        ta.value = plain; ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
      }
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }, [text])
  if (!text) return <>{children}</>
  return (
    <Popover
      trigger="hover"
      placement={placement}
      mouseEnterDelay={0.1}
      content={
        <div style={{ maxWidth: 'min(80vw, 18.75rem)', fontSize: '0.75rem', lineHeight: 1.7 }}>
          <div style={{ color: WH.textMuted, whiteSpace: 'pre-line' }}>{renderRich(text)}</div>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={copy}
            style={{ paddingLeft: 0, marginTop: 'var(--wh-space-sm)', height: 'auto', color: WH.teal }}>
            {copied ? t('explain.copied') : t('explain.copy')}
          </Button>
        </div>
      }
    >
      {children}
    </Popover>
  )
}

// 核心：? 图标 + 悬停气泡（含复制）。不依赖外部 t，内部自行取 i18n。
// 图标本身吃掉 click：挂在可下钻的卡片标题上时，点 ⓘ 不该顺带打开下钻弹窗
// （与下方 ExplainCorner 的 stopPropagation 同一取向）。
export const ExplainIcon = ({ text, size = '0.8125rem', placement = 'top', icon = 'info' }: ExplainIconProps) => {
  if (!text) return null
  return (
    <ExplainPopover text={text} placement={placement}>
      <span
        style={{ cursor: 'help', color: WH.textDim, fontSize: size, lineHeight: 1 }}
        onClick={e => e.stopPropagation()}
      >
        {icon === 'question' ? <QuestionCircleOutlined /> : <InfoCircleOutlined />}
      </span>
    </ExplainPopover>
  )
}

// 卡片右上角绝对定位的 ? 说明（与 PacketLoss SummaryCard 一致；点击不触发卡片下钻）
export const ExplainCorner = ({ text, size, placement }: { text: string; size?: number; placement?: Placement }) => (
  <span
    style={{ position: 'absolute', top: 'var(--wh-space-xs)', right: 'var(--wh-space-sm)', zIndex: 2, cursor: 'help' }}
    onClick={e => e.stopPropagation()}
  >
    <ExplainIcon text={text} size={size} placement={placement} />
  </span>
)

// 文字标签 + 内联 ? 说明
export const ExplainLabel = ({ label, text, size, placement }: { label: ReactNode; text: string; size?: number; placement?: Placement }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--wh-space-xs)' }}>
    {label}
    <ExplainIcon text={text} size={size} placement={placement} />
  </span>
)
