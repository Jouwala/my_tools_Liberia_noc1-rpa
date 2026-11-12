/* ============================================================================
 * 拓扑图算法与链路状态（V2 Phase 1）
 * ============================================================================
 * 任务书 §3.1 / §3.2 要求把三种关系分清楚，这里只做纯函数、不改数据结构：
 *
 *   Full Adjacency   = idx.adj[i]（{n: 邻居下标, e: 边下标}[]，含重复边）
 *   All Connections  = allConnections(idx, i)（同上，语义化命名，含双归属全部边）
 *   Primary Parent   = idx.parent[i]（仅用于布局排序，绝不代表唯一上游）
 *
 * 后端 down 口径（services/ipran_topo/ipran_topo_service.py::_aggregate）：
 *   n    = 一对机框折叠后的物理链路总数
 *   down = 组内 connectionState != 1 的条数
 * 因此 0 / (0,n) / n 分别是 正常 / 部分故障 / 全部故障。
 * 注意：后端在 links_attr 缺行时会把该链路误计为 down，这里只如实呈现数值，
 * 不擅自"修正"业务口径（见 Phase 0 风险 3）。
 * ========================================================================== */
import type { TopoEdge, TopoIndex, TopoNode } from './types'

export type LinkState = 'normal' | 'partial' | 'failed'

/** 平行链路三态。非法数值一律夹到合法区间，避免上游脏数据把整页画崩。 */
export function linkStateOf(e: Pick<TopoEdge, 'n' | 'down'>): LinkState {
  const total = Math.max(0, Math.trunc(e.n) || 0)
  const down = Math.max(0, Math.min(Math.trunc(e.down) || 0, total))
  if (total === 0 || down === 0) return 'normal'
  return down >= total ? 'failed' : 'partial'
}

export interface ParallelBreakdown {
  total: number
  up: number
  down: number
  state: LinkState
}

export function parallelBreakdown(e: Pick<TopoEdge, 'n' | 'down'>): ParallelBreakdown {
  const total = Math.max(0, Math.trunc(e.n) || 0)
  const down = Math.max(0, Math.min(Math.trunc(e.down) || 0, total))
  return { total, up: total - down, down, state: linkStateOf({ n: total, down }) }
}

/** 全量真实连接（含双归属、平行链路造成的重复项）—— 绘图与故障分析都用它。 */
export function allConnections(idx: TopoIndex, i: number): { n: number; e: number }[] {
  return idx.adj[i] ?? []
}

/** 去重后的上游邻居下标（层级严格更小的邻居），用于上游追踪展示。 */
export function upstreamNeighbors(idx: TopoIndex, nodes: TopoNode[], i: number): number[] {
  const here = nodes[i]
  if (!here) return []
  const out: number[] = []
  for (const a of allConnections(idx, i)) {
    const nb = nodes[a.n]
    if (nb && nb.tier < here.tier && !out.includes(a.n)) out.push(a.n)
  }
  return out.sort((x, y) => nodes[x].tier - nodes[y].tier || nodes[x].id.localeCompare(nodes[y].id))
}

/** 去重后的下游邻居下标（层级严格更大的邻居）。 */
export function downstreamNeighbors(idx: TopoIndex, nodes: TopoNode[], i: number): number[] {
  const here = nodes[i]
  if (!here) return []
  const out: number[] = []
  for (const a of allConnections(idx, i)) {
    const nb = nodes[a.n]
    if (nb && nb.tier > here.tier && !out.includes(a.n)) out.push(a.n)
  }
  return out
}

/**
 * 广度优先遍历，可传 blocked 谓词排除故障节点/链路。
 * 返回 { node: 到达的节点下标, depth: 跳数, via: 上一跳节点下标 }[]。
 * Phase 4 的上下游影响与多路径分析都基于它，这里先提供通用实现。
 */
export function bfs(
  idx: TopoIndex,
  start: number,
  opts: { maxHops?: number; blockedNode?: (i: number) => boolean; blockedEdge?: (e: number) => boolean } = {},
): { node: number; depth: number; via: number }[] {
  if (!idx.adj[start]) return []
  const maxHops = opts.maxHops ?? Number.POSITIVE_INFINITY
  const seen = new Set<number>([start])
  const queue = [{ node: start, depth: 0, via: -1 }]
  const out: { node: number; depth: number; via: number }[] = []
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    if (cur.depth >= maxHops) continue
    for (const a of allConnections(idx, cur.node)) {
      if (opts.blockedEdge?.(a.e)) continue
      if (opts.blockedNode?.(a.n)) continue
      if (seen.has(a.n)) continue
      seen.add(a.n)
      const next = { node: a.n, depth: cur.depth + 1, via: cur.node }
      queue.push(next)
      out.push(next)
    }
  }
  return out
}
