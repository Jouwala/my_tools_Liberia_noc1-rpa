/* ============================================================================
 * Phase 1 · 数据模型与链路状态测试（vitest，纯函数）
 * ============================================================================
 * 覆盖任务书 Phase 1 的六类场景：多归属 / 孤立 / 全部断链 / 部分断链 /
 * 缺失节点引用 / 重复链路，外加 §3.1 主归属三条排序规则。
 * 不挂 DOM、不发请求；所有连接关系以「不丢失」为第一断言。
 * ========================================================================== */
import { describe, expect, it } from 'vitest'

import { buildIndex } from '../layouts'
import {
  allConnections, bfs, downstreamNeighbors, linkStateOf, parallelBreakdown, upstreamNeighbors,
} from '../graphAlgorithms'
import type { Tier, TopoEdge, TopoNode } from '../types'

function node(id: string, tier: Tier, deg = 0): TopoNode {
  return {
    id, name: id, site: id, tier, model: '', ip: '', up: 1,
    crit: 0, major: 0, minor: 0, warn: 0, sev: 'ok',
    lat: null, lon: null, geo: 'miss', geoName: '', deg,
  }
}

function edge(s: string, t: string, n = 1, down = 0): TopoEdge {
  return { s, t, n, gb: 10, down, crit: 0, major: 0, ports: [`${s}-${t}:10GE:`] }
}

describe('Phase 1 · 平行链路三态（§3.2）', () => {
  it('down=0 正常 / 0<down<n 部分 / down=n 全部', () => {
    expect(linkStateOf({ n: 3, down: 0 })).toBe('normal')
    expect(linkStateOf({ n: 3, down: 1 })).toBe('partial')
    expect(linkStateOf({ n: 3, down: 2 })).toBe('partial')
    expect(linkStateOf({ n: 3, down: 3 })).toBe('failed')
  })

  it('边界与脏数据不崩溃：n=0、down 越界、NaN、负数一律夹到合法区间', () => {
    expect(linkStateOf({ n: 0, down: 0 })).toBe('normal')
    expect(linkStateOf({ n: 2, down: 99 })).toBe('failed')
    expect(linkStateOf({ n: -1, down: -1 })).toBe('normal')
    expect(linkStateOf({ n: Number.NaN, down: Number.NaN })).toBe('normal')
    expect(parallelBreakdown({ n: 4, down: 1 })).toEqual({
      total: 4, up: 3, down: 1, state: 'partial',
    })
    expect(parallelBreakdown({ n: 2, down: 9 }).up).toBe(0)
  })

  it('展开状态下仍能逐条区分：n / down / up 三个数同时可用', () => {
    const b = parallelBreakdown({ n: 10, down: 3 })
    expect(b).toMatchObject({ total: 10, down: 3, up: 7, state: 'partial' })
  })
})

describe('Phase 1 · 图索引健壮性（§3.1）', () => {
  it('多归属：全部真实连接保留，primary parent 只有一个', () => {
    const nodes = [
      node('core', 1, 9), node('aggA', 2, 8), node('aggB', 2, 6), node('access', 3, 3),
    ]
    const edges = [
      edge('access', 'aggA'), edge('access', 'aggB'), edge('access', 'core'),
      edge('aggA', 'core'), edge('aggB', 'core'),
    ]
    const idx = buildIndex(nodes, edges)
    const i = idx.byId['access']
    expect(allConnections(idx, i)).toHaveLength(3)
    expect(upstreamNeighbors(idx, nodes, i).map((k) => nodes[k].id)).toEqual(['core', 'aggA', 'aggB'])
    expect(idx.upstream[i]).toHaveLength(3)
    expect(idx.parent[i]).toBeGreaterThanOrEqual(0)
    // 布局只取主归属，绘图仍用全量 edges
    expect(edges).toHaveLength(5)
  })

  it('孤立设备：adj / upstream 为空，parent = -1，不产生幽灵连接', () => {
    const nodes = [node('core', 1), node('lonely', 3)]
    const idx = buildIndex(nodes, [])
    expect(idx.adj[1]).toEqual([])
    expect(idx.upstream[1]).toEqual([])
    expect(idx.parent[1]).toBe(-1)
    expect(downstreamNeighbors(idx, nodes, 0)).toEqual([])
    expect(bfs(idx, 1)).toEqual([])
  })

  it('缺失节点引用：跳过该边，不崩溃、不产生越界邻接', () => {
    const nodes = [node('a', 1), node('b', 2)]
    const edges = [edge('a', 'b'), edge('a', 'ghost'), edge('phantom', 'b')]
    const idx = buildIndex(nodes, edges)
    expect(idx.adj[0]).toHaveLength(1)
    expect(idx.adj[1]).toHaveLength(1)
    expect(idx.adj.every((list) => list.every((x) => x.n >= 0 && x.n < nodes.length))).toBe(true)
  })

  it('重复链路：同一对节点的两条边都保留（不因去重丢连接）', () => {
    const nodes = [node('a', 1), node('b', 2)]
    const edges = [edge('a', 'b', 3), edge('a', 'b', 2, 1)]
    const idx = buildIndex(nodes, edges)
    expect(allConnections(idx, 0)).toHaveLength(2)
    expect(idx.adj[0].map((x) => x.e)).toEqual([0, 1])
    expect(upstreamNeighbors(idx, nodes, 1)).toEqual([0])
  })

  it('bfs 支持 blockedEdge，用于 Phase 4 排除故障链路', () => {
    const nodes = [node('a', 1), node('b', 2), node('c', 3)]
    const edges = [edge('a', 'b'), edge('b', 'c')]
    const idx = buildIndex(nodes, edges)
    expect(bfs(idx, 0).map((x) => x.node)).toEqual([1, 2])
    expect(bfs(idx, 0, { blockedEdge: (e) => e === 0 }).map((x) => x.node)).toEqual([])
  })
})

describe('Phase 1 · 主归属三条排序规则（§3.1）', () => {
  const acc = () => node('access', 3, 1)

  it('① 层级更靠上的邻居优先，即使它度数更小', () => {
    const nodes = [acc(), node('zCore', 1, 1), node('aAgg', 2, 99)]
    const idx = buildIndex(nodes, [edge('access', 'aAgg'), edge('access', 'zCore')])
    expect(nodes[idx.parent[0]].id).toBe('zCore')
  })

  it('② 同层时度数更大的优先', () => {
    const nodes = [acc(), node('small', 2, 2), node('big', 2, 20)]
    const idx = buildIndex(nodes, [edge('access', 'small'), edge('access', 'big')])
    expect(nodes[idx.parent[0]].id).toBe('big')
  })

  it('③ 层级与度数都相同时按设备 id 稳定排序，且与边的顺序无关', () => {
    const nodes = [acc(), node('bAgg', 2, 5), node('aAgg', 2, 5)]
    const forward = buildIndex(nodes, [edge('access', 'bAgg'), edge('access', 'aAgg')])
    const reverse = buildIndex(nodes, [edge('access', 'aAgg'), edge('access', 'bAgg')])
    expect(nodes[forward.parent[0]].id).toBe('aAgg')
    expect(nodes[reverse.parent[0]].id).toBe('aAgg')
  })
})
