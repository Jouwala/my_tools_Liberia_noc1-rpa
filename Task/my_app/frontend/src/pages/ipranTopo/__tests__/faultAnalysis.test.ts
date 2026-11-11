/* ============================================================================
 * Phase 4 · 故障候选、环网、双归属与部分断链
 * 断言口径：候选不是确认根因；部分故障不切断活路；告警本身不产生候选。
 * ========================================================================== */
import { describe, expect, it } from 'vitest'

import { analyzeGraph, analyzeNode, ringIntact } from '../faultAnalysis'
import { buildIndex } from '../layouts'
import type { Tier, TopoEdge, TopoNode } from '../types'

function node(id: string, tier: Tier, up = 1): TopoNode {
  return {
    id, name: id, site: id, tier, model: '', ip: '', up,
    crit: 0, major: 0, minor: 0, warn: 0, sev: up ? 'ok' : 'crit',
    lat: null, lon: null, geo: 'miss', geoName: '', deg: 1,
  }
}
function edge(s: string, t: string, n = 1, down = 0): TopoEdge {
  return { s, t, n, gb: 10, down, crit: 0, major: 0, ports: [] }
}

describe('Phase 4 · 根因只到候选', () => {
  it('只有告警、设备在线：证据不足，不产生候选', () => {
    const nodes = [node('core', 1), node('acc', 3)]
    nodes[1].crit = 8
    const edges = [edge('acc', 'core')]
    const fault = analyzeGraph(buildIndex(nodes, edges), nodes, edges)
    expect(fault.candidates).toEqual([])
    expect(fault.evidence).toBe('insufficient')
  })

  it('失联接入挂在在线汇聚下：接入是候选，且理由含「没有告警时间」', () => {
    const nodes = [node('core', 1), node('agg', 2), node('acc', 3, 0)]
    const edges = [edge('agg', 'core'), edge('acc', 'agg')]
    const fault = analyzeGraph(buildIndex(nodes, edges), nodes, edges)
    expect(fault.candidates.map((c) => nodes[c.index].id)).toEqual(['acc'])
    expect(fault.candidates[0].reasons).toContain('noAlarmTime')
    expect(fault.evidence).toBe('candidate')
  })

  it('上游也失联时，只把更靠上的失联设备列为候选', () => {
    const nodes = [node('core', 1), node('agg', 2, 0), node('acc', 3, 0)]
    const edges = [edge('agg', 'core'), edge('acc', 'agg')]
    const fault = analyzeGraph(buildIndex(nodes, edges), nodes, edges)
    expect(fault.candidates.map((c) => nodes[c.index].id)).toEqual(['agg'])
  })
})

describe('Phase 4 · 部分断链与双归属', () => {
  it('部分故障仍有活路，接入点不算与核心失联', () => {
    const nodes = [node('core', 1), node('agg', 2), node('acc', 3)]
    const edges = [edge('agg', 'core'), edge('acc', 'agg', 3, 1)]
    const idx = buildIndex(nodes, edges)
    const fault = analyzeGraph(idx, nodes, edges)
    expect(fault.isolated).not.toContain(idx.byId.acc)
    const impact = analyzeNode(idx, nodes, edges, idx.byId.acc, fault)
    expect(impact.alternatePaths).toBeGreaterThanOrEqual(1)
  })

  it('一条归属全断、另一条还通：双归属设备仍能回到核心', () => {
    const nodes = [node('core', 1), node('aggA', 2), node('aggB', 2), node('acc', 3)]
    const edges = [
      edge('aggA', 'core'), edge('aggB', 'core'),
      edge('acc', 'aggA', 1, 1), edge('acc', 'aggB', 2, 0),
    ]
    const idx = buildIndex(nodes, edges)
    expect(analyzeGraph(idx, nodes, edges).isolated).not.toContain(idx.byId.acc)
    expect(analyzeNode(idx, nodes, edges, idx.byId.acc).alternatePaths).toBeGreaterThanOrEqual(1)
  })

  it('全部归属都全断：设备被算作失联于核心', () => {
    const nodes = [node('core', 1), node('agg', 2), node('acc', 3)]
    const edges = [edge('agg', 'core'), edge('acc', 'agg', 2, 2)]
    const idx = buildIndex(nodes, edges)
    expect(analyzeGraph(idx, nodes, edges).isolated).toContain(idx.byId.acc)
    expect(analyzeNode(idx, nodes, edges, idx.byId.acc).alternatePaths).toBe(0)
  })
})

describe('Phase 4 · 环网', () => {
  it('三角环全通；拆掉旁路后环不再成立', () => {
    const nodes = [node('a', 2), node('b', 2), node('c', 2)]
    const open = [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')]
    const idxOpen = buildIndex(nodes, open)
    expect(ringIntact(idxOpen, nodes, open, 0)).toBe(true)
    const broken = [edge('a', 'b'), edge('b', 'c', 1, 1), edge('c', 'a', 1, 1)]
    const idxBroken = buildIndex(nodes, broken)
    expect(ringIntact(idxBroken, nodes, broken, 0)).toBe(false)
  })
})
