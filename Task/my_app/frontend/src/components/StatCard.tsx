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
}: StatCardProps) {
  return (
    <div
      className="wh-stat-card"
      style={{
        '--wh-stat-accent': accentColor,
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
