/* ============================================================================
 * Phase 2 · 聚类力导向与布局缓存
 * ========================================================================== */
import { describe, expect, it } from 'vitest'

import { buildIndex, layoutForce, layoutForceClassic } from '../layouts'
import { cachedLayout, clearLayoutCache, layoutSignature } from '../layoutCache'
import type { Tier, TopoEdge, TopoNode } from '../types'

function node(id: string, tier: Tier): TopoNode {
  return {
    id, name: id, site: id, tier, model: '', ip: '', up: 1,
    crit: 0, major: 0, minor: 0, warn: 0, sev: 'ok',
    lat: null, lon: null, geo: 'miss', geoName: '', deg: 2,
  }
}
function edge(s: string, t: string): TopoEdge {
  return { s, t, n: 1, gb: 10, down: 0, crit: 0, major: 0, ports: [] }
}

function sample() {
  const nodes = [
    node('core', 1), node('agg', 2),
    node('a1', 3), node('a2', 3), node('a3', 3),
  ]
  const edges = [edge('agg', 'core'), edge('a1', 'agg'), edge('a2', 'agg'), edge('a3', 'agg'), edge('a1', 'core')]
  return { nodes, edges, idx: buildIndex(nodes, edges) }
}

describe('Phase 2 · 力导向聚类不丢连接', () => {
  it('经典与聚类都确定性，且节点一个不少', () => {
    const { nodes, edges, idx } = sample()
    const classic = layoutForceClassic(nodes, idx, edges)
    const clustered = layoutForce(nodes, idx, edges, { cluster: true })
    expect(layoutForceClassic(nodes, idx, edges).pos).toEqual(classic.pos)
    expect(layoutForce(nodes, idx, edges, { cluster: true }).pos).toEqual(clustered.pos)
    expect(classic.pos).toHaveLength(nodes.length)
    expect(clustered.pos).toHaveLength(nodes.length)
    clustered.pos.forEach((p) => {
      expect(Number.isFinite(p.x)).toBe(true)
      expect(Number.isFinite(p.y)).toBe(true)
    })
  })

  it('聚类后接入点到主归属的平均水平距离不大于经典算法', () => {
    const { nodes, edges, idx } = sample()
    const meanDx = (pos: { x: number }[]) => {
      let sum = 0
      let n = 0
      nodes.forEach((v, i) => {
        if (v.tier !== 3 || idx.parent[i] < 0) return
        sum += Math.abs(pos[i].x - pos[idx.parent[i]].x)
        n++
      })
      return sum / n
    }
    const classic = meanDx(layoutForceClassic(nodes, idx, edges).pos)
    const clustered = meanDx(layoutForce(nodes, idx, edges, { cluster: true }).pos)
    expect(clustered).toBeLessThanOrEqual(classic + 0.01)
  })
})

describe('Phase 2 · 布局缓存', () => {
  it('相同拓扑签名命中同一对象；边集变化或清空后重算', () => {
    clearLayoutCache()
    const { nodes, edges, idx } = sample()
    const a = cachedLayout('tier', nodes, idx, edges)
    const b = cachedLayout('tier', nodes, idx, edges)
    expect(b).toBe(a)
    const shorter = edges.slice(0, -1)
    const c = cachedLayout('tier', nodes, buildIndex(nodes, shorter), shorter)
    expect(c).not.toBe(a)
    expect(layoutSignature('tier', nodes, edges)).not.toBe(layoutSignature('tier', nodes, shorter))
    clearLayoutCache()
    const d = cachedLayout('tier', nodes, idx, edges)
    expect(d).not.toBe(a)
  })

  it('告警计数变化不改变签名', () => {
    const { nodes, edges } = sample()
    const alarmed = nodes.map((n) => ({ ...n, crit: 9 }))
    expect(layoutSignature('force', nodes, edges)).toBe(layoutSignature('force', alarmed, edges))
  })
})
