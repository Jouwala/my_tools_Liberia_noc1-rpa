import React, { ReactNode } from 'react'
import { Popover, Statistic } from 'antd'
import { WH } from '../theme'
import { ExplainPopover } from './MetricExplain'

interface StatCardProps {
  title: ReactNode
  value: number | string
  prefix?: ReactNode
  suffix?: string
  accentColor?: string
  iconBg?: string
  subText?: ReactNode
  style?: React.CSSProperties
  /** 可选：传入后卡片整体可点击（用于下钻等交互），并自动切换手型光标 */
  onClick?: (e: React.MouseEvent<HTMLDivElement>) => void
  /** 可选：悬浮在**大数字本身**上时显示的计算说明（AGENTS.md 三.3c）。
   *  与 title 里的 ExplainIcon 分工：ⓘ 讲「这一张卡怎么算」，这里讲「这个数怎么来的」。
   *  只包数字、不包标题 —— 否则标题的 ⓘ 会和外层气泡同时炸开两个。 */
  explainText?: string
  /** 紧凑卡：给窄栏里横排多张用。默认仍是大数字卡。 */
  dense?: boolean
  /** subText 默认常驻在数字下方。click = 不占高度，点数字才弹出，且不冒泡到卡片 onClick。 */
  subTextTrigger?: 'always' | 'click'
}

export default function StatCard({
  title,
  value,
  prefix,
  suffix,
  accentColor = 'var(--wh-teal)',
  iconBg,
  subText,
  style,
  onClick,
  explainText,
  dense = false,
  subTextTrigger = 'always',
}: StatCardProps) {
  const number = (
    <ExplainPopover text={explainText || ''} placement="bottom">
      <span style={{ display: 'block' }}>
        <Statistic
          value={value}
          suffix={suffix}
          valueStyle={{
            color: accentColor,
            fontWeight: 700,
            fontSize: dense ? '1rem' : '1.625rem',
            lineHeight: 1.2,
          }}
        />
      </span>
    </ExplainPopover>
  )
  const showSubOnClick = !!subText && subTextTrigger === 'click'
  const titleNode = (
    <div title={typeof title === 'string' ? title : undefined} style={{
      fontSize: dense ? '0.6875rem' : '0.8125rem',
      color: WH.textMuted,
      marginTop: dense ? '0.2rem' : undefined,
      marginBottom: dense ? 0 : '0.25rem',
      lineHeight: dense ? 1.2 : undefined,
      textAlign: dense ? 'center' : undefined,
      overflow: 'hidden',
      display: dense ? '-webkit-box' : undefined,
      WebkitLineClamp: dense ? 2 : undefined,
      WebkitBoxOrient: dense ? 'vertical' : undefined,
    } as React.CSSProperties}>
      {title}
    </div>
  )
  const valueNode = showSubOnClick ? (
    <Popover
      trigger="click"
      placement="bottom"
      content={
        <div style={{ maxWidth: 'min(80vw, 16rem)', fontSize: '0.75rem', lineHeight: 1.6, color: WH.textMuted }}>
          {subText}
        </div>
      }
    >
      <span
        style={{ display: 'block', cursor: 'pointer' }}
        onClick={(e) => e.stopPropagation()}
      >
        {number}
      </span>
    </Popover>
  ) : number
  return (
    <div
      className="wh-stat-card spatial-stat-card"
      onClick={onClick}
      style={{
        '--wh-stat-accent': accentColor,
        cursor: onClick ? 'pointer' : undefined,
        ...(dense ? { padding: '0.4rem 0.3rem', alignItems: 'stretch' } : {}),
        ...style,
      } as React.CSSProperties}
    >
      <div style={{ flex: 1, minWidth: 0, display: dense ? 'flex' : undefined, flexDirection: dense ? 'column' : undefined }}>
        {dense ? (
          <>
            {/* 数字固定一行高，六张卡的数字才能落在同一条水平线上，标题在下面换行不影响对齐 */}
            <div style={{ height: '1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {valueNode}
            </div>
            {titleNode}
          </>
        ) : (
          <>
            {titleNode}
            {valueNode}
          </>
        )}
        {subText && subTextTrigger === 'always' && (
          <div style={{ fontSize: '0.75rem', color: WH.textDim, marginTop: '0.25rem' }}>
            {subText}
          </div>
        )}
      </div>
      {prefix && (
        <div
          className="wh-stat-icon-wrapper"
          style={{
            '--wh-stat-icon-bg': iconBg || `color-mix(in srgb, ${accentColor} 15%, transparent)`,
            '--wh-stat-icon-color': accentColor,
          } as React.CSSProperties}
        >
          {prefix}
        </div>
      )}
    </div>
  )
}
