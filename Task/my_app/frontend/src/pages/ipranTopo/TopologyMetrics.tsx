/* 右侧指标条。放在「紧急告警最多的网元」上方，整组宽度与下面那张榜同宽，
 * 六张卡排成一行：数字在上且同一行对齐，标题在数字下面。
 * 构成说明默认不占位，点数字才弹出。
 * 健康度与链路可用率都由接口已有的 up / n / down 算出，没有流量字段。 */
import type { MouseEvent as ReactMouseEvent } from 'react'

import { WH, useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import { StatCard } from '../../components/cards'
import type { TopoEdge } from './types'

interface Props {
  ne: number
  ext: number
  folded: number
  rawLinks: number
  downNe: number
  critNe: number
  critPct: number
  inLayer: number
  edges: TopoEdge[]
  explain: { ne: string; links: string; down: string; crit: string }
  onDrill: (kind: 'ne' | 'links' | 'down' | 'crit') => (e: ReactMouseEvent<HTMLDivElement>) => void
}

function linkAvailability(edges: TopoEdge[]): { pct: string; up: number; total: number } {
  let total = 0
  let up = 0
  for (const e of edges) {
    const n = Math.max(0, Math.trunc(e.n) || 0)
    const down = Math.max(0, Math.min(Math.trunc(e.down) || 0, n))
    total += n
    up += n - down
  }
  if (!total) return { pct: '—', up: 0, total: 0 }
  return { pct: `${Math.round((up * 1000) / total) / 10}%`, up, total }
}

export default function TopologyMetrics(p: Props) {
  const { t } = useI18n()
  const { colors } = useTheme()
  const health = p.inLayer
    ? `${Math.round(((p.inLayer - p.downNe) * 1000) / p.inLayer) / 10}%`
    : '—'
  const avail = linkAvailability(p.edges)
  /* 同一行里标题行数不同，用网格把每张卡拉到这一行最高的那张。 */
  const cell = { height: '100%', minWidth: 0 }
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(6, minmax(0, 1fr))',
      gap: 6,
      flexShrink: 0,
      alignItems: 'stretch',
    }}>
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.health')} value={health} accentColor={WH.teal}
        subText={p.inLayer ? t('ipranTopo.kpi.healthSub', { up: p.inLayer - p.downNe, n: p.inLayer }) : '—'}
        explainText={t('ipranTopo.kpi.explain.health')} />
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.ne')} value={p.ne} accentColor={WH.teal}
        subText={t('ipranTopo.kpi.neSub', { n: p.ext })}
        explainText={t(p.explain.ne)} onClick={p.onDrill('ne')} />
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.down')} value={p.downNe}
        accentColor={p.downNe ? WH.danger : WH.ok}
        subText={t('ipranTopo.kpi.downSub')}
        explainText={t(p.explain.down)} onClick={p.onDrill('down')} />
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.crit')} value={p.critNe} accentColor={WH.sev.Major}
        subText={t('ipranTopo.kpi.critSub', { pct: p.critPct })}
        explainText={t(p.explain.crit)} onClick={p.onDrill('crit')} />
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.links')} value={p.folded} accentColor={colors[1]}
        subText={t('ipranTopo.kpi.linksSub', { n: p.rawLinks })}
        explainText={t(p.explain.links)} onClick={p.onDrill('links')} />
      <StatCard dense subTextTrigger="click" style={cell}
        title={t('ipranTopo.kpi.avail')} value={avail.pct} accentColor={colors[2]}
        subText={avail.total ? t('ipranTopo.kpi.availSub', { up: avail.up, n: avail.total }) : '—'}
        explainText={t('ipranTopo.kpi.explain.avail')} onClick={p.onDrill('links')} />
    </div>
  )
}
