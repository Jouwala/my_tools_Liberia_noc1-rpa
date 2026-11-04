import React, { ReactNode } from 'react'
import { Statistic } from 'antd'
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
}: StatCardProps) {
  return (
    <div
      className="wh-stat-card spatial-stat-card"
      onClick={onClick}
      style={{
        '--wh-stat-accent': accentColor,
        cursor: onClick ? 'pointer' : undefined,
        ...style,
      } as React.CSSProperties}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '0.8125rem', color: WH.textMuted, marginBottom: '0.25rem' }}>
          {title}
        </div>
        <ExplainPopover text={explainText || ''} placement="bottom">
          <span style={{ display: 'block' }}>
            <Statistic
              value={value}
              suffix={suffix}
              valueStyle={{
                color: accentColor,
                fontWeight: 700,
                fontSize: '1.625rem',
                lineHeight: 1.2,
              }}
            />
          </span>
        </ExplainPopover>
        {subText && (
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
