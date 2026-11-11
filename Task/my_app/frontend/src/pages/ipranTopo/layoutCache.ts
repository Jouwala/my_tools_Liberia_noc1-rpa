/* ============================================================================
 * 布局缓存（V2 Phase 2）
 * ============================================================================
 * 告警计数刷新不应重跑 1400 步力导向。签名只含「会改变坐标」的字段：
 * 布局种类、节点 id / 层级 / 经纬度、边的两端。告警、在线状态、端口名不进签名。
 * 缓存上限 12 条（四层 × 三种布局，再留一点切换余量），超出删最旧的一条。
 * ========================================================================== */
import { LAYOUT_FNS } from './layouts'
import type { LayoutKey, LayoutResult, TopoEdge, TopoIndex, TopoNode } from './types'

const MAX = 12
const cache = new Map<string, LayoutResult>()

export function layoutSignature(key: LayoutKey, nodes: TopoNode[], edges: TopoEdge[]): string {
  let s = `${key}|${nodes.length}|${edges.length}`
  for (const n of nodes) s += `|${n.id},${n.tier},${n.lat ?? ''},${n.lon ?? ''}`
  for (const e of edges) s += `|${e.s}>${e.t}`
  return s
}

export function cachedLayout(
  key: LayoutKey, nodes: TopoNode[], idx: TopoIndex, edges: TopoEdge[],
): LayoutResult {
  const sig = layoutSignature(key, nodes, edges)
  const hit = cache.get(sig)
  if (hit) return hit
  const result = LAYOUT_FNS[key](nodes, idx, edges)
  cache.set(sig, result)
  if (cache.size > MAX) {
    const oldest = cache.keys().next().value
    if (oldest) cache.delete(oldest)
  }
  return result
}

export function clearLayoutCache() {
  cache.clear()
}
