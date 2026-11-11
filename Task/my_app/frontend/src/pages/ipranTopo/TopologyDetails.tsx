/* 设备 / 链路详情。告警名、发生时间、流量利用率接口没给时显示 N/A，不编造。 */
import { useMemo } from 'react'
import { Empty, Table, Tabs } from 'antd'

import { WH } from '../../theme'
import { useI18n } from '../../i18n'
import { analyzeNode, type GraphFault } from './faultAnalysis'
import { linkStateOf } from './graphAlgorithms'
import type { TopoEdge, TopoIndex, TopoNode, Tier } from './types'

interface Props {
  nodes: TopoNode[]
  edges: TopoEdge[]
  idx: TopoIndex
  focus: number
  selectedEdge: number
  fault: GraphFault
  onFocus: (i: number) => void
}

function trafficText(v: number | null | undefined, na: string): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v}%` : na
}

export default function TopologyDetails({
  nodes, edges, idx, focus, selectedEdge, fault, onFocus,
}: Props) {
  const { t } = useI18n()
  const na = t('ipranTopo.detail.na')
  const tierName = (tier: Tier) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }
  const linkText = (e: TopoEdge) => {
    const s = linkStateOf(e)
    if (s === 'failed') return t('ipranTopo.link.state.failed')
    if (s === 'partial') return t('ipranTopo.link.state.partial')
    return t('ipranTopo.link.state.normal')
  }
  const node = focus >= 0 ? nodes[focus] : null
  const edge = selectedEdge >= 0 ? edges[selectedEdge] : null
  const impact = useMemo(
    () => (node ? analyzeNode(idx, nodes, edges, focus, fault) : null),
    [node, idx, nodes, edges, focus, fault],
  )

  if (!node && !edge) return null

  const ifaceRows = node
    ? (idx.adj[focus] || []).map((a) => ({
      key: `${a.e}-${a.n}`,
      peer: nodes[a.n]?.name ?? '—',
      peerIndex: a.n,
      gb: edges[a.e]?.gb,
      state: edges[a.e] ? linkText(edges[a.e]) : na,
      ports: edges[a.e]?.ports?.[0] || na,
      util: trafficText(edges[a.e]?.rxUtil, na),
    }))
    : []

  const reasonText = (reasons: string[]) => reasons.map((r) => {
    if (r === 'deviceDown') return t('ipranTopo.impact.reasonDown')
    if (r === 'upstreamMost') return t('ipranTopo.impact.reasonUpstream')
    return t('ipranTopo.impact.reasonNoTime')
  }).join(' · ')

  return (
    <>
      {edge && (
        <div style={{ fontSize: 12, color: WH.textMuted, marginBottom: 8, lineHeight: 1.8 }}>
          <div>{nodes[idx.byId[edge.s]]?.name} ↔ {nodes[idx.byId[edge.t]]?.name}</div>
          <div>{linkText(edge)} · {t('ipranTopo.tip.edgeBreakdown', {
            up: Math.max(0, edge.n - edge.down), down: edge.down, total: edge.n,
          })}</div>
          <div>{t('ipranTopo.detail.capacity', { gb: edge.gb == null ? na : `${edge.gb}G` })}</div>
          <div>{t('ipranTopo.detail.util', { rx: trafficText(edge.rxUtil, na), tx: trafficText(edge.txUtil, na) })}</div>
          <div style={{ whiteSpace: 'pre-line', color: WH.textDim }}>{edge.ports.slice(0, 6).join('\n') || na}</div>
        </div>
      )}
      {node && impact && (
        <Tabs size="small" items={[
          {
            key: 'overview',
            label: t('ipranTopo.detail.overview'),
            children: (
              <div style={{ fontSize: 12, color: WH.textMuted, lineHeight: 1.8 }}>
                <div>{node.name}</div>
                <div>{tierName(node.tier)} · {node.model || na} · IP {node.ip || na}</div>
                <div style={{ color: node.up ? WH.ok : WH.danger }}>
                  {node.up ? t('ipranTopo.tip.up') : t('ipranTopo.tip.down')}
                </div>
                <div>{t('ipranTopo.focus.alarms', {
                  crit: node.crit, major: node.major, minor: node.minor, warn: node.warn,
                })}</div>
                {node.tier === 3 && idx.parent[focus] >= 0 && (
                  <div>{t('ipranTopo.focus.parent', { name: nodes[idx.parent[focus]].name })}</div>
                )}
              </div>
            ),
          },
          {
            key: 'if',
            label: t('ipranTopo.detail.interfaces'),
            children: (
              <Table size="small" pagination={false} scroll={{ y: 240 }} dataSource={ifaceRows} columns={[
                { title: t('ipranTopo.col.peer'), dataIndex: 'peer',
                  render: (v: string, r) => <a onClick={() => onFocus(r.peerIndex)}>{v}</a> },
                { title: t('ipranTopo.col.gb'), dataIndex: 'gb', width: 80,
                  render: (v: number | null) => (v == null ? na : `${v}G`) },
                { title: t('ipranTopo.col.status'), dataIndex: 'state', width: 120 },
                { title: t('ipranTopo.detail.utilCol'), dataIndex: 'util', width: 90 },
                { title: t('ipranTopo.col.ports'), dataIndex: 'ports', ellipsis: true },
              ]} />
            ),
          },
          {
            key: 'alarms',
            label: t('ipranTopo.detail.alarms'),
            children: (
              <div style={{ fontSize: 12, color: WH.textMuted, lineHeight: 1.8 }}>
                <div>{t('ipranTopo.focus.alarms', {
                  crit: node.crit, major: node.major, minor: node.minor, warn: node.warn,
                })}</div>
                <div>{t('ipranTopo.detail.alarmName')}：{na}</div>
                <div>{t('ipranTopo.detail.alarmTime')}：{na}</div>
                <div style={{ color: WH.textDim }}>{t('ipranTopo.detail.alarmHint')}</div>
              </div>
            ),
          },
          {
            key: 'impact',
            label: t('ipranTopo.detail.impact'),
            children: (
              <div style={{ fontSize: 12, color: WH.textMuted, lineHeight: 1.8 }}>
                <div style={{ color: WH.warn }}>{t('ipranTopo.impact.disclaimer')}</div>
                <div>{t('ipranTopo.impact.graph', {
                  n: fault.candidates.length,
                  state: fault.evidence === 'candidate'
                    ? t('ipranTopo.impact.candidate') : t('ipranTopo.impact.insufficient'),
                })}</div>
                {fault.candidates.slice(0, 8).map((c) => (
                  <div key={c.index}>
                    <a onClick={() => onFocus(c.index)}>{nodes[c.index]?.name}</a>
                    <span> · {reasonText(c.reasons)}</span>
                  </div>
                ))}
                <div>{t('ipranTopo.impact.altPaths', {
                  n: impact.alternatePaths == null ? na : String(impact.alternatePaths),
                })}</div>
                <div>{impact.ringIntact ? t('ipranTopo.impact.ringYes') : t('ipranTopo.impact.ringNo')}</div>
                <div>{t('ipranTopo.impact.upstream', {
                  names: impact.upstream.map((i) => nodes[i]?.name).join(', ') || na,
                })}</div>
                <div>{t('ipranTopo.impact.impacted', { n: impact.impacted.length })}</div>
                {impact.impacted.length === 0
                  ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('ipranTopo.impact.none')} />
                  : impact.impacted.slice(0, 12).map((i) => (
                    <div key={i}><a onClick={() => onFocus(i)}>{nodes[i]?.name}</a></div>
                  ))}
              </div>
            ),
          },
        ]} />
      )}
    </>
  )
}
