/* 图例。着色模式切换时跟着变，线宽/三态链路的说明常驻一行。 */
import { useMemo } from 'react'

import { WH, useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import type { ColorMode, Tier } from './types'

interface Props {
  colorMode: ColorMode
  tierCounts?: Record<string, number>
}

export default function TopologyLegend({ colorMode, tierCounts }: Props) {
  const { t } = useI18n()
  const { colors } = useTheme()
  const tierName = (tier: Tier) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }
  const items = useMemo(() => {
    const out: { c: string; label: string }[] = []
    const tierColor = [WH.textDim, colors[0], colors[1], colors[2]]
    if (colorMode === 'up') {
      out.push({ c: WH.ok, label: t('ipranTopo.legend.upOn') })
      out.push({ c: WH.danger, label: t('ipranTopo.legend.upOff') })
      out.push({ c: WH.textDim, label: tierName(0) })
    } else if (colorMode === 'sev') {
      out.push({ c: WH.sev.Critical, label: t('ipranTopo.sev.crit') })
      out.push({ c: WH.sev.Major, label: t('ipranTopo.sev.major') })
      out.push({ c: WH.sev.Warning, label: t('ipranTopo.sev.minor') })
      out.push({ c: WH.sev.Info, label: t('ipranTopo.sev.warn') })
      out.push({ c: WH.ok, label: t('ipranTopo.sev.ok') })
    } else {
      ;([0, 1, 2, 3] as Tier[]).forEach((k) => {
        const n = tierCounts?.[String(k)] ?? 0
        out.push({ c: tierColor[k], label: `${tierName(k)}（${n}）` })
      })
    }
    return out
  }, [colorMode, colors, tierCounts, t])

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center',
      marginTop: 'var(--wh-space-sm)', fontSize: 12, color: WH.textMuted }}>
      {items.map((it, i) => (
        <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 10, height: 10, borderRadius: 5, background: it.c,
            border: `1px solid ${WH.cardBorder}`, display: 'inline-block' }} />
          {it.label}
        </span>
      ))}
      <span style={{ color: WH.textDim }}>{t('ipranTopo.legend.line')}</span>
    </div>
  )
}
