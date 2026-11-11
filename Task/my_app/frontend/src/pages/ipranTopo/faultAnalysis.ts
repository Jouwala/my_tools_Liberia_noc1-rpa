/* ============================================================================
 * 故障分析（V2 Phase 4）—— 只产出「候选」，绝不写成已确认根因
 * ============================================================================
 * 后端节点没有告警发生时间，也没有逐条告警名。缺这些证据时：
 *   - 在线设备即使 critical 很高，也不进候选；
 *   - 失联设备里，只有「上游没有更失联的设备」才标成 Root Cause Candidate；
 *   - 界面必须同时展示 noAlarmTime，不能把候选说成根因。
 *
 * 断链口径与 Phase 1 一致：只有 down === n（全部物理链路故障）才阻断通路，
 * 部分故障仍算一条活路。
 * ========================================================================== */
import { allConnections, linkStateOf, upstreamNeighbors } from './graphAlgorithms'
import type { TopoEdge, TopoIndex, TopoNode } from './types'

export interface RootCandidate {
  index: number
  reasons: Array<'deviceDown' | 'upstreamMost' | 'noAlarmTime'>
}

export interface GraphFault {
  candidates: RootCandidate[]
  /** 去掉全断链路、且不穿行失联设备后，到不了任何在线核心/层外的节点 */
  isolated: number[]
  evidence: 'candidate' | 'insufficient'
}

export interface NodeImpact {
  upstream: number[]
  downstream: number[]
  /** 到在线核心的边不相交活路径条数；本节点自己就是核心时为 null（问题不适用） */
  alternatePaths: number | null
  ringIntact: boolean
  /** 下游里失联、或已被判定与核心失联的设备 */
  impacted: number[]
}

function failedEdge(edges: TopoEdge[], e: number): boolean {
  const edge = edges[e]
  return !!edge && linkStateOf(edge) === 'failed'
}

function isLiveCore(nodes: TopoNode[], i: number): boolean {
  const n = nodes[i]
  return !!n && n.tier <= 1 && n.up === 1
}

/** 全图：哪些设备已经没有活路回到在线核心。 */
export function isolatedNodes(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[]): number[] {
  const out: number[] = []
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].tier <= 1) continue
    if (reachesLiveCore(idx, nodes, edges, i)) continue
    out.push(i)
  }
  return out
}

function reachesLiveCore(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], start: number): boolean {
  const seen = new Set<number>([start])
  const queue = [start]
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    for (const a of allConnections(idx, cur)) {
      if (failedEdge(edges, a.e)) continue
      const nb = nodes[a.n]
      if (!nb) continue
      if (nb.up === 0) continue
      if (isLiveCore(nodes, a.n)) return true
      if (seen.has(a.n)) continue
      seen.add(a.n)
      queue.push(a.n)
    }
  }
  return false
}

export function analyzeGraph(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[]): GraphFault {
  const isolated = isolatedNodes(idx, nodes, edges)
  const down: number[] = []
  nodes.forEach((n, i) => { if (n.tier > 0 && n.up === 0) down.push(i) })
  if (down.length === 0) return { candidates: [], isolated, evidence: 'insufficient' }
  const downSet = new Set(down)
  const candidates: RootCandidate[] = down
    .filter((i) => upstreamNeighbors(idx, nodes, i).every((u) => !downSet.has(u)))
    .map((index) => ({ index, reasons: ['deviceDown', 'upstreamMost', 'noAlarmTime'] }))
  return { candidates, isolated, evidence: candidates.length ? 'candidate' : 'insufficient' }
}

function sameTierPeers(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], i: number): number[] {
  const tier = nodes[i]?.tier
  const out: number[] = []
  for (const a of allConnections(idx, i)) {
    const nb = nodes[a.n]
    if (!nb || nb.tier !== tier || failedEdge(edges, a.e)) continue
    if (!out.includes(a.n)) out.push(a.n)
  }
  return out
}

/** 同层环是否还通：两个同层邻居之间存在一条不经过本节点、且不含全断链路的同层通路。 */
export function ringIntact(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], i: number): boolean {
  const peers = sameTierPeers(idx, nodes, edges, i)
  if (peers.length < 2) return false
  const goal = new Set(peers.slice(1))
  const tier = nodes[i].tier
  const seen = new Set<number>([peers[0]])
  const queue = [peers[0]]
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    for (const a of allConnections(idx, cur)) {
      if (a.n === i || failedEdge(edges, a.e)) continue
      const nb = nodes[a.n]
      if (!nb || nb.tier !== tier || seen.has(a.n)) continue
      if (goal.has(a.n)) return true
      seen.add(a.n)
      queue.push(a.n)
    }
  }
  return false
}

function countAlternatePaths(idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], start: number): number | null {
  if (!nodes[start] || nodes[start].tier <= 1) return null
  const blocked = new Set<number>()
  let count = 0
  for (let k = 0; k < 3; k++) {
    const path = oneLivePath(idx, nodes, edges, start, blocked)
    if (!path) break
    path.forEach((e) => blocked.add(e))
    count++
  }
  return count
}

/** 一条到在线核心的活路径，返回经过的边下标；blocked 中的边不用。 */
function oneLivePath(
  idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], start: number, blocked: Set<number>,
): number[] | null {
  const prev = new Map<number, { node: number; edge: number }>()
  const seen = new Set<number>([start])
  const queue = [start]
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    for (const a of allConnections(idx, cur)) {
      if (blocked.has(a.e) || failedEdge(edges, a.e)) continue
      const nb = nodes[a.n]
      if (!nb || seen.has(a.n)) continue
      if (nb.up === 0) continue
      seen.add(a.n)
      prev.set(a.n, { node: cur, edge: a.e })
      if (isLiveCore(nodes, a.n)) {
        const path: number[] = []
        let x = a.n
        while (x !== start) {
          const step = prev.get(x)
          if (!step) break
          path.push(step.edge)
          x = step.node
        }
        return path
      }
      queue.push(a.n)
    }
  }
  return null
}

function downstreamAll(idx: TopoIndex, nodes: TopoNode[], i: number): number[] {
  const out: number[] = []
  const seen = new Set<number>([i])
  const queue = [i]
  const tier = nodes[i]?.tier ?? 0
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    for (const a of allConnections(idx, cur)) {
      const nb = nodes[a.n]
      if (!nb || nb.tier <= tier || seen.has(a.n)) continue
      seen.add(a.n)
      out.push(a.n)
      queue.push(a.n)
    }
  }
  return out
}

export function analyzeNode(
  idx: TopoIndex, nodes: TopoNode[], edges: TopoEdge[], i: number, fault?: GraphFault,
): NodeImpact {
  const empty: NodeImpact = {
    upstream: [], downstream: [], alternatePaths: null, ringIntact: false, impacted: [],
  }
  if (!nodes[i]) return empty
  const graph = fault ?? analyzeGraph(idx, nodes, edges)
  const isolated = new Set(graph.isolated)
  const downstream = downstreamAll(idx, nodes, i)
  return {
    upstream: upstreamNeighbors(idx, nodes, i),
    downstream,
    alternatePaths: countAlternatePaths(idx, nodes, edges, i),
    ringIntact: ringIntact(idx, nodes, edges, i),
    impacted: downstream.filter((k) => isolated.has(k) || nodes[k].up === 0),
  }
}
