/* ============================================================================
 * IP RAN 拓扑的下钻弹窗：统计卡点进来后看「构成这个数的那些行」
 * ============================================================================
 * 卡片与弹窗的口径必须一致（AGENTS.md 三.1b）：网元卡→全部层内网元、
 * 失联卡→up=0 的网元、告警卡→crit>0 的网元、链路卡→折叠后的全部边。
 * 这里的筛选条件与页面统计卡**同一来源**（同一个 nodes / edges 数组），
 * 不做任何额外过滤，避免「卡上 74、点开只有 30」这种对不上的观感。
 * ========================================================================== */
import { useMemo } from 'react'
import { Table, Tag } from 'antd'
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import DraggableClickModal from '../../components/DraggableClickModal'
import type { TopoEdge, TopoIndex, TopoNode } from './types'

export type DrillKind = 'ne' | 'down' | 'crit' | 'links'

const TITLE_KEY: Record<DrillKind, string> = {
  ne: 'ipranTopo.drill.ne',
  down: 'ipranTopo.drill.down',
  crit: 'ipranTopo.drill.crit',
  links: 'ipranTopo.drill.links',
}

interface Props {
  kind: DrillKind | null
  anchor: { x: number; y: number } | null
  nodes: TopoNode[]
  edges: TopoEdge[]
  idx: TopoIndex
  onClose: () => void
  onFocus: (i: number) => void
}

export default function TopoDrillModal({ kind, anchor, nodes, edges, idx, onClose, onFocus }: Props) {
  const { t } = useI18n()

  const tierName = (tier: TopoNode['tier']) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }

  const nodeRows = useMemo(() => {
    const ne = nodes.filter((v) => v.tier > 0)
    if (kind === 'down') return ne.filter((v) => !v.up)
    if (kind === 'crit') return ne.filter((v) => v.crit > 0).sort((a, b) => b.crit - a.crit || b.major - a.major)
    return ne
  }, [kind, nodes])

  const nodeCols = useMemo(() => [
    {
      title: t('ipranTopo.col.name'), dataIndex: 'name', key: 'name', width: 230, fixed: 'left' as const,
      render: (v: string, r: TopoNode) => (
        <a onClick={() => { onFocus(idx.byId[r.id]); onClose() }}>{v}</a>
      ),
    },
    { title: t('ipranTopo.col.tier'), dataIndex: 'tier', key: 'tier', width: 110, render: (v: TopoNode['tier']) => tierName(v) },
    { title: t('ipranTopo.col.site'), dataIndex: 'site', key: 'site', width: 170 },
    { title: t('ipranTopo.col.ip'), dataIndex: 'ip', key: 'ip', width: 130 },
    {
      title: t('ipranTopo.col.status'), dataIndex: 'up', key: 'up', width: 90,
      render: (v: number) => (v
        ? <Tag color="green">{t('ipranTopo.status.up')}</Tag>
        : <Tag color="red">{t('ipranTopo.status.down')}</Tag>),
    },
    { title: t('ipranTopo.col.crit'), dataIndex: 'crit', key: 'crit', width: 80, sorter: (a: TopoNode, b: TopoNode) => a.crit - b.crit },
    { title: t('ipranTopo.col.major'), dataIndex: 'major', key: 'major', width: 80, sorter: (a: TopoNode, b: TopoNode) => a.major - b.major },
    { title: t('ipranTopo.col.minor'), dataIndex: 'minor', key: 'minor', width: 80 },
    { title: t('ipranTopo.col.warn'), dataIndex: 'warn', key: 'warn', width: 80 },
    { title: t('ipranTopo.col.deg'), dataIndex: 'deg', key: 'deg', width: 90, sorter: (a: TopoNode, b: TopoNode) => a.deg - b.deg },
  ], [t, idx, onClose, onFocus])

  const linkCols = useMemo(() => [
    {
      title: t('ipranTopo.col.peerA'), key: 'a', width: 250, fixed: 'left' as const,
      render: (_: unknown, e: TopoEdge) => nodes[idx.byId[e.s]]?.name ?? e.s,
    },
    {
      title: t('ipranTopo.col.peerB'), key: 'b', width: 250,
      render: (_: unknown, e: TopoEdge) => nodes[idx.byId[e.t]]?.name ?? e.t,
    },
    { title: t('ipranTopo.col.physLinks'), dataIndex: 'n', key: 'n', width: 110, sorter: (a: TopoEdge, b: TopoEdge) => a.n - b.n },
    {
      title: t('ipranTopo.col.gb'), dataIndex: 'gb', key: 'gb', width: 100,
      render: (v: number | null) => (v == null ? '-' : `${v}G`),
      sorter: (a: TopoEdge, b: TopoEdge) => (a.gb ?? 0) - (b.gb ?? 0),
    },
    {
      title: t('ipranTopo.col.downLinks'), dataIndex: 'down', key: 'down', width: 100,
      render: (v: number) => (v > 0 ? <span style={{ color: WH.danger }}>{v}</span> : '0'),
    },
    { title: t('ipranTopo.col.crit'), dataIndex: 'crit', key: 'crit', width: 80 },
    { title: t('ipranTopo.col.major'), dataIndex: 'major', key: 'major', width: 80 },
    {
      title: t('ipranTopo.col.ports'), dataIndex: 'ports', key: 'ports', width: 360,
      render: (v: string[]) => <span style={{ color: WH.textMuted, fontSize: 12 }}>{v.join(' | ') || '-'}</span>,
    },
  ], [t, nodes, idx])

  const isLinks = kind === 'links'

  return (
    <DraggableClickModal
      open={kind != null}
      title={kind ? `${t(TITLE_KEY[kind])} · ${isLinks ? edges.length : nodeRows.length}` : ''}
      anchor={anchor}
      onClose={onClose}
      width="92%"
      maxWidth="80rem"
    >
      {/* 弹窗内不再套卡片（弹窗本身即容器，见 _TemplatePage ⑥） */}
      {isLinks ? (
        <Table
          rowKey={(e) => `${e.s}-${e.t}`}
          size="small"
          columns={linkCols}
          dataSource={edges}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 1400 }}
        />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={nodeCols}
          dataSource={nodeRows}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 1200 }}
        />
      )}
    </DraggableClickModal>
  )
}
