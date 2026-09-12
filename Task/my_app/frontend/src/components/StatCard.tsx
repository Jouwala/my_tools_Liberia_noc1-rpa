import React, { ReactNode } from 'react'
import { Statistic } from 'antd'
import { WH } from '../theme'

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
