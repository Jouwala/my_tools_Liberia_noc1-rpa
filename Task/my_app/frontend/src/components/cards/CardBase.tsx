/* ============================================================================
 * CardBase —— 项目统一卡片外壳
 * ----------------------------------------------------------------------------
 * 这是「项目默认卡片」的皮肤层：所有卡片的外壳都应走它，而不是直接 <Card> 或裸 <div>。
 *
 * 它只负责**皮肤**（背景 / 描边 / 圆角 / 阴影 / 内发光 / 悬停），不负责信息结构
 * ——「图标+徽章+大数字+趋势线」那套居中堆叠是 StatCard 的职责，两者刻意分开：
 * 图表卡、表格卡、表单卡也需要同一张皮，但不该被塞进数字卡的结构里。
 *
 * 皮肤来源：olbrportal/assets/olbr.css 的 .qc-card 一档（描边 + 内发光 + 悬停上浮）。
 * 令牌与类名定义在 index.css，本文件只是「带正确 className 的薄封装」，
 * 真正的样式值一律不在这里写死 —— 否则又会变成改不动的行内层（见下）。
 *
 * ⚠️ 为什么不再各处直接写 style={cardStyle}：
 * cardStyle 是**行内样式**，优先级高于 index.css 里所有类选择器。任何写进 cardStyle
 * 的具体值都会永久锁死该属性，CSS 层再也改不动它 —— 上一版卡片无法统一下发皮肤，
 * 根因就是 cardStyle.boxShadow 写死了 var(--wh-shadow-1)。现在 cardStyle 里只剩
 * var(--wh-*) 间接引用，但**新代码仍应优先用本组件**，把「卡片长什么样」这件事
 * 收敛到单一入口。
 *
 * 用法：
 *   <CardBase title="标题">内容</CardBase>                       // 图表/表格/任意内容
 *   <CardBase title="标题" level="crit">需要标红的卡片</CardBase>  // 按告警等级染色
 *   <CardBase as="div" interactive>裸容器也要同一张皮</CardBase>
 * ========================================================================== */
import React, { ReactNode } from 'react'
import { Card } from 'antd'
import { cardStyle, WH } from '../../theme'

/** 卡片语义等级：驱动描边与内发光的 accent 色（对应 index.css 的 .wh-card-lv-*） */
export type CardLevel = 'default' | 'ok' | 'warn' | 'crit'

const LEVEL_CLASS: Record<CardLevel, string> = {
  default: '',
  ok: 'wh-card-lv-ok',
  warn: 'wh-card-lv-warn',
  crit: 'wh-card-lv-crit',
}

export interface CardBaseProps {
  children?: ReactNode
  /** 卡头标题。传字符串时自动套用项目统一的卡头排版，无需再写内联 span。 */
  title?: ReactNode
  /** 卡头右侧操作区（按钮、说明图标、时间戳等） */
  extra?: ReactNode
  /** 语义等级：按阈值染 accent 色。默认不染色。 */
  level?: CardLevel
  /** 是否可点击（加悬停上浮 + 手型光标）。 */
  interactive?: boolean
  onClick?: (e: React.MouseEvent<HTMLElement>) => void
  className?: string
  style?: React.CSSProperties
  /** body 的内边距等局部微调；只传需要覆盖的部分，其余仍由皮肤层决定。 */
  bodyStyle?: React.CSSProperties
  loading?: boolean
  bordered?: boolean
  size?: 'default' | 'small'
  /** 用 antd Card（默认）还是裸 div。纯布局容器用 div 可少一层 DOM 与默认内边距。 */
  as?: 'card' | 'div'
}

/** 项目统一的卡头文字排版：此前在 12 处各写一份内联 span，收敛到这里 */
export function CardTitle({ children }: { children: ReactNode }) {
  return (
    <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: WH.text }}>{children}</span>
  )
}

export default function CardBase({
  children,
  title,
  extra,
  level = 'default',
  interactive = false,
  onClick,
  className,
  style,
  bodyStyle,
  loading,
  bordered,
  size = 'small',
  as = 'card',
}: CardBaseProps) {
  const classes = [
    'wh-card',
    interactive ? 'wh-card-interactive' : '',
    LEVEL_CLASS[level],
    className || '',
  ].filter(Boolean).join(' ')

  // 传字符串标题时自动套统一排版；传 ReactNode（已自带 ExplainIcon 等）则原样保留，
  // 避免把调用方刻意构造的复杂卡头再包一层。
  const head = typeof title === 'string' ? <CardTitle>{title}</CardTitle> : title

  const merged = {
    ...cardStyle,
    cursor: interactive || onClick ? 'pointer' : undefined,
    ...style,
  } as React.CSSProperties

  if (as === 'div') {
    return (
      <div className={classes} style={merged} onClick={onClick}>
        {head && (
          <div className="wh-card-head">
            <CardTitle>{head}</CardTitle>
            {extra && <span style={{ marginLeft: 'auto' }}>{extra}</span>}
          </div>
        )}
        {children}
      </div>
    )
  }

  return (
    <Card
      size={size}
      title={head}
      extra={extra}
      loading={loading}
      bordered={bordered}
      hoverable={interactive}
      onClick={onClick}
      className={classes}
      style={merged}
      styles={bodyStyle ? { body: bodyStyle } : undefined}
    >
      {children}
    </Card>
  )
}
