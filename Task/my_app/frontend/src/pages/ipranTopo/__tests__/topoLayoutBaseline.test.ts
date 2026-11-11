/* ============================================================================
 * 拓扑布局 / 图索引基线测试（V2 Phase 0，vitest）
 * ============================================================================
 * 把任务书 §3.4 的七项指标变成**可重复**的回归基线，供 Phase 2 比较 Force
 * 布局优化前后的差异。只测纯函数：不挂 DOM、不发请求、不连 UME，CI 零环境依赖。
 *
 * 关于 42 / 221 / 390：那是 2026-11-10 在**真实** 141 条边上测得的边交叉数，
 * 当时没留下 fixture，也没记录统计算法（共端点算不算交叉等）。本文件用固定种子
 * 生成结构等价的合成图（100 节点 / 141 边 / tier 分布 7-4-11-78），给出可复现
 * 基线；要用真实数据重验时设 TOPO_GRAPH_FIXTURE=<graph.json 路径>，内容即
 * `/api/ipran-topo/graph` 的原始响应，指标会自动改用该图。
 *
 * 本文件的交叉口径：严格线段相交，共端点与共线不计。与原 42/221/390 的口径
 * 可能不同 —— 这正是 Phase 0 要先固定基线定义的原因，详见阶段报告风险清单。
 * ========================================================================== */
import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { buildIndex, LAYOUT_FNS, radiusOf, TOPO_H, TOPO_W } from '../layouts'
import { layoutLabels } from '../labels'
import type { LayoutKey, Pt, Tier, TopoEdge, TopoNode, TopoResp } from '../types'

const SEED = 20261110

function lcg(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    return s / 0x7fffffff
  }
}

const SITES = [
  'Chocolate City', 'Goodridge', 'Buchanan', '12th Street', '18th Street',
  'Botota', 'Kakata', 'Logatoto', 'Paynesville', 'Sinkor', 'Congo Town',
  'Ganta', 'Gbarnga', 'Harper', 'Zwedru', 'Voinjama', 'Bomi', 'Bong Mines',
  'Tubmanburg', 'Greenville',
]

/** 结构等价合成图：7 层外 / 4 核心 / 11 汇聚 / 78 接入，141 条折叠边。 */
function makeFixture(): { nodes: TopoNode[]; edges: TopoEdge[] } {
  const rnd = lcg(SEED)
  const tiers: Tier[] = [
    ...Array<Tier>(7).fill(0),
    ...Array<Tier>(4).fill(1),
    ...Array<Tier>(11).fill(2),
    ...Array<Tier>(78).fill(3),
  ]
  const nodes: TopoNode[] = tiers.map((tier, i) => {
    const hasGeo = rnd() < 0.77
    return {
      id: `n${String(i).padStart(3, '0')}`,
      name: `${tier === 0 ? 'HQ-EXT' : tier === 1 ? 'ODC_SPE' : tier === 2 ? 'M6K_2S16_AGG' : 'M6K_2S16'}_${SITES[i % SITES.length].replace(/\s/g, '_')}_${i}`,
      site: SITES[i % SITES.length],
      tier,
      model: tier === 1 ? '9000-8EA' : tier === 2 ? 'M6000-2S16' : tier === 3 ? '6120H-S' : 'EXT',
      ip: `10.16.${tier}.${i}`,
      up: rnd() < 0.98 ? 1 : 0,
      crit: rnd() < 0.8 ? 1 + Math.floor(rnd() * 5) : 0,
      major: Math.floor(rnd() * 3),
      minor: 0, warn: 0,
      sev: 'crit',
      lat: hasGeo ? 4.5 + rnd() * 4 : null,
      lon: hasGeo ? -11.5 + rnd() * 4 : null,
      geo: hasGeo ? (rnd() < 0.96 ? 'exact' : 'fuzzy') : 'miss',
      geoName: '',
      deg: 0,
    }
  })
  const ext = [0, 1, 2, 3, 4, 5, 6]
  const core = [7, 8, 9, 10]
  const agg = Array.from({ length: 11 }, (_, k) => 11 + k)
  const acc = Array.from({ length: 78 }, (_, k) => 22 + k)

  const edges: TopoEdge[] = []
  const addEdge = (a: number, b: number) => {
    const n = 1 + Math.floor(rnd() * 3)
    const down = rnd() < 0.08 ? Math.min(n, 1 + Math.floor(rnd() * n)) : 0
    edges.push({
      s: nodes[a].id, t: nodes[b].id, n,
      gb: [10, 25, 100][Math.floor(rnd() * 3)],
      down,
      crit: rnd() < 0.2 ? 1 : 0,
      major: 0,
      ports: [`${nodes[a].name}-1/1:10GE:--${nodes[b].name}-1/1:100GE:`],
    })
    nodes[a].deg += n
    nodes[b].deg += n
  }

  // 层外 → 核心（含 89MW02 这类高度数上游）
  ext.forEach((e, k) => { addEdge(e, core[k % core.length]); if (k < 3) addEdge(e, core[(k + 1) % core.length]) })
  // 核心全互联
  for (let i = 0; i < core.length; i++) for (let j = i + 1; j < core.length; j++) addEdge(core[i], core[j])
  // 汇聚 → 主归属核心 + 双归属第二核心
  agg.forEach((a, k) => {
    addEdge(a, core[k % core.length])
    if (k % 2 === 0) addEdge(a, core[(k + 1) % core.length])
  })
  // 78 个接入点各挂一个汇聚；其中 12 个是双归属
  acc.forEach((a, k) => {
    addEdge(a, agg[k % agg.length])
    if (k % 6 === 0) addEdge(a, agg[(k + 3) % agg.length])
  })
  // 接入环网相邻连接
  for (let k = 0; k < acc.length - 1 && edges.length < 141; k += 7) addEdge(acc[k], acc[k + 1])
  // 补到 141 条：汇聚间横向链路（确定性，不引入随机分支）
  let cursor = 0
  while (edges.length < 141) {
    addEdge(agg[cursor % agg.length], agg[(cursor + 5) % agg.length])
    cursor++
  }
  return { nodes, edges: edges.slice(0, 141) }
}

const fixture = makeFixture()

/** 严格线段相交：共端点 / 共线不计。 */
function segmentsCross(a: Pt, b: Pt, c: Pt, d: Pt): boolean {
  const orient = (p: Pt, q: Pt, r: Pt) =>
    Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x))
  const o1 = orient(a, b, c)
  const o2 = orient(a, b, d)
  const o3 = orient(c, d, a)
  const o4 = orient(c, d, b)
  return o1 !== o2 && o3 !== o4 && o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0
}

const CJK = /[\u2e80-\u9fff\uff00-\uffef]/
/** 与 labels.ts 的宽度估算公式一致；改动 labels.ts 时这里要同步。 */
function textWidth(s: string, fs: number): number {
  let w = 0
  for (const ch of s) w += CJK.test(ch) ? fs : fs * 0.56
  return w
}

function boxHit(a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number }) {
  return a.x < b.x + b.w + 2 && a.x + a.w + 2 > b.x &&
    a.y < b.y + b.h + 2 && a.y + a.h + 2 > b.y
}

export interface TopoMetrics {
  layout: LayoutKey
  executionMs: number
  edgeCrossings: number
  nodeOverlaps: number
  avgEdgeLength: number
  maxEdgeLength: number
  labelOverlaps: number
  labelsShown: number
  labelsHidden: number
  layerSeparation: number
}

export function computeMetrics(
  layoutKey: LayoutKey,
  nodes: TopoNode[],
  edges: TopoEdge[],
  showAllLabels = true,
): TopoMetrics {
  const idx = buildIndex(nodes, edges)
  // 预热一次再计时 3 次取中位数：首次运行含 JIT，单次测量抖动太大，
  // 不能作为 Phase 2 布局优化的性能对比依据
  let layout = LAYOUT_FNS[layoutKey](nodes, idx, edges)
  const times: number[] = []
  for (let k = 0; k < 3; k++) {
    const t0 = performance.now()
    layout = LAYOUT_FNS[layoutKey](nodes, idx, edges)
    times.push(performance.now() - t0)
  }
  times.sort((a, b) => a - b)
  const executionMs = times[1]
  const { pos, bands } = layout

  const segs = edges
    .map((e) => [pos[idx.byId[e.s]], pos[idx.byId[e.t]]] as const)
    .filter((s): s is readonly [Pt, Pt] => !!s[0] && !!s[1])

  let edgeCrossings = 0
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      if (segmentsCross(segs[i][0], segs[i][1], segs[j][0], segs[j][1])) edgeCrossings++
    }
  }

  let nodeOverlaps = 0
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = pos[i].x - pos[j].x
      const dy = pos[i].y - pos[j].y
      if (Math.hypot(dx, dy) < radiusOf(nodes[i].tier) + radiusOf(nodes[j].tier)) nodeOverlaps++
    }
  }

  const lengths = segs.map(([a, b]) => Math.hypot(a.x - b.x, a.y - b.y))
  const avgEdgeLength = lengths.length ? lengths.reduce((s, v) => s + v, 0) / lengths.length : 0
  const maxEdgeLength = lengths.length ? Math.max(...lengths) : 0

  const { labels, hidden } = layoutLabels(nodes, {
    pos, focus: -1, showAllLabels, nbSet: null, bands, W: TOPO_W, H: TOPO_H,
  })
  const boxes = labels.map((L) => ({
    x: L.x - textWidth(L.text, L.fontSize) / 2,
    y: L.y - L.fontSize,
    w: textWidth(L.text, L.fontSize),
    h: L.fontSize + 1,
  }))
  let labelOverlaps = 0
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) if (boxHit(boxes[i], boxes[j])) labelOverlaps++
  }

  // 层级分离度：相邻 tier 平均 y 的间距之和（越大越不糊层）
  const sumY: Record<number, { sum: number; n: number }> = {}
  nodes.forEach((v, i) => {
    sumY[v.tier] ??= { sum: 0, n: 0 }
    sumY[v.tier].sum += pos[i].y
    sumY[v.tier].n++
  })
  const avgY = (t: number) => sumY[t] ? sumY[t].sum / sumY[t].n : 0
  const layerSeparation = Math.abs(avgY(1) - avgY(2)) + Math.abs(avgY(2) - avgY(3))

  return {
    layout: layoutKey,
    executionMs: Math.round(executionMs * 100) / 100,
    edgeCrossings, nodeOverlaps,
    avgEdgeLength: Math.round(avgEdgeLength * 10) / 10,
    maxEdgeLength: Math.round(maxEdgeLength * 10) / 10,
    labelOverlaps, labelsShown: labels.length, labelsHidden: hidden,
    layerSeparation: Math.round(layerSeparation * 10) / 10,
  }
}

/** 真实数据可选注入：文件内容 = /api/ipran-topo/graph 原始响应。 */
function activeGraph(): { nodes: TopoNode[]; edges: TopoEdge[]; source: string } {
  const p = process.env.TOPO_GRAPH_FIXTURE
  if (p && existsSync(p)) {
    const resp = JSON.parse(readFileSync(p, 'utf8')) as TopoResp
    return { nodes: resp.nodes, edges: resp.edges, source: `真实数据 ${p}` }
  }
  return { nodes: fixture.nodes, edges: fixture.edges, source: '合成 fixture（种子 20261110）' }
}

describe('Phase 0 · 图索引与布局回归', () => {
  it('fixture 结构符合真实层分布：100 节点 / 141 边 / 7-4-11-78', () => {
    expect(fixture.nodes).toHaveLength(100)
    expect(fixture.edges).toHaveLength(141)
    const counts: Record<number, number> = {}
    fixture.nodes.forEach((v) => { counts[v.tier] = (counts[v.tier] ?? 0) + 1 })
    expect(counts).toEqual({ 0: 7, 1: 4, 2: 11, 3: 78 })
  })

  it('三种布局都返回有限、在画布内的坐标', () => {
    const idx = buildIndex(fixture.nodes, fixture.edges)
    ;(['force', 'tier', 'geo'] as LayoutKey[]).forEach((key) => {
      const { pos } = LAYOUT_FNS[key](fixture.nodes, idx, fixture.edges)
      expect(pos).toHaveLength(fixture.nodes.length)
      pos.forEach((p) => {
        expect(Number.isFinite(p.x)).toBe(true)
        expect(Number.isFinite(p.y)).toBe(true)
        expect(p.x).toBeGreaterThanOrEqual(0)
        expect(p.x).toBeLessThanOrEqual(TOPO_W)
        expect(p.y).toBeGreaterThanOrEqual(0)
        expect(p.y).toBeLessThanOrEqual(TOPO_H)
      })
    })
  })

  it('布局确定性：同一输入连跑两次逐点一致（Phase 2 不得破坏）', () => {
    const idx = buildIndex(fixture.nodes, fixture.edges)
    ;(['force', 'tier', 'geo'] as LayoutKey[]).forEach((key) => {
      const a = LAYOUT_FNS[key](fixture.nodes, idx, fixture.edges).pos
      const b = LAYOUT_FNS[key](fixture.nodes, idx, fixture.edges).pos
      expect(a).toEqual(b)
    })
  })

  it('双归属：adj 保留全部真实连接，parent 只给一个主归属', () => {
    const idx = buildIndex(fixture.nodes, fixture.edges)
    const dual = fixture.nodes.findIndex((v, i) => v.tier === 3 &&
      idx.adj[i].filter((a) => fixture.nodes[a.n].tier < 3).length >= 2)
    expect(dual).toBeGreaterThanOrEqual(0)
    expect(idx.adj[dual].filter((a) => fixture.nodes[a.n].tier < 3).length).toBeGreaterThanOrEqual(2)
    expect(idx.parent[dual]).toBeGreaterThanOrEqual(0)
    // 绘图用的是 edges 全量，不是 parent —— 双归属链路不会被布局吃掉
    expect(fixture.edges.filter((e) => e.s === fixture.nodes[dual].id || e.t === fixture.nodes[dual].id).length)
      .toBeGreaterThanOrEqual(2)
  })

  it('图索引健壮性：缺失节点引用不崩溃、不产生幽灵邻接', () => {
    const broken: TopoEdge = { ...fixture.edges[0], s: 'not-exist', t: 'also-missing' }
    const idx = buildIndex(fixture.nodes, [...fixture.edges, broken])
    expect(idx.adj).toHaveLength(fixture.nodes.length)
    expect(idx.adj.every((a) => a.every((x) => x.n >= 0 && x.n < fixture.nodes.length))).toBe(true)
  })

  it('平行链路三态所需的 n / down 字段完整（Phase 1 展示层待实现）', () => {
    expect(fixture.edges.every((e) => e.n >= 1 && e.down >= 0 && e.down <= e.n)).toBe(true)
    expect(fixture.edges.some((e) => e.down === 0)).toBe(true)
    expect(fixture.edges.some((e) => e.down > 0 && e.down < e.n)).toBe(true)
    expect(fixture.edges.some((e) => e.down === e.n && e.n > 0)).toBe(true)
  })
})

describe('Phase 0 · 七项布局基线指标', () => {
  it('输出可重复基线并断言标签零重叠、无 NaN', () => {
    const { nodes, edges, source } = activeGraph()
    const rows = (['force', 'tier', 'geo'] as LayoutKey[]).map((k) => computeMetrics(k, nodes, edges))
    // eslint-disable-next-line no-console
    console.log(`\n[拓扑布局基线] ${source}\n` + JSON.stringify(rows, null, 2))
    rows.forEach((r) => {
      expect(Number.isFinite(r.executionMs)).toBe(true)
      expect(Number.isFinite(r.edgeCrossings)).toBe(true)
      expect(Number.isFinite(r.avgEdgeLength)).toBe(true)
      expect(r.labelOverlaps).toBe(0)
      expect(r.labelsShown + r.labelsHidden).toBeGreaterThan(0)
    })
  })
})
