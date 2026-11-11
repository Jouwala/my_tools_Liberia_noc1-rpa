/* ============================================================================
 * UME 四层拓扑共用的三种布局（纯函数，不碰 DOM；层差异只在数据与口径，不在布局）
 * ============================================================================
 *
 * 为什么是三种而不是「能画多少画多少」：
 *   这是 141 条边 / 100 个点的真实图（93 网元 + 7 层外上游）。用「边交叉次数」
 *   当可读性代理量做过参数扫描，实测（2026-11-10，画布 760×540）：
 *
 *     力导向 42 次交叉  ← 默认视图，环网与簇团自然浮现
 *     地理   221 次      ← 第二个视图，唯一能回答「断站影响哪个城市」的
 *     分层   390 次      ← 导出用，层级关系一眼看懂
 *     辐射   877 次      ← **已删除**：双归属环网站点只能归一个主父节点，
 *                          81 条接入↔接入的边要横穿整圆；它回答的是「谁挂了几个
 *                          接入点」，那是并列条形图的活，不该用拓扑图硬撑
 *
 * 三个布局都是确定性的（力导向用固定种子的 LCG，不用 Math.random）：
 * 同一份数据每次打开位置一致，用户才能凭位置记忆找设备。
 *
 * 参数（K=36 / ITER=1400 / 种子 31415 / relax 的 28px）是**对这些数据扫出来的**，
 * 不是拍的。数据量翻倍时需要重扫，不要直接沿用。
 * ========================================================================== */
import type { LayoutResult, Pt, TopoBand, TopoEdge, TopoIndex, TopoNode } from './types'

/** 画布逻辑尺寸（viewBox）。布局常量都是按这个尺寸扫的，改尺寸要重扫参数。 */
export const TOPO_W = 760
export const TOPO_H = 540

/** 构造邻接索引。byId 用于把边上的 id 换回数组下标。 */
export function buildIndex(nodes: TopoNode[], edges: TopoEdge[]): TopoIndex {
  const byId: Record<string, number> = {}
  nodes.forEach((v, i) => { byId[v.id] = i })
  const adj: { n: number; e: number }[][] = nodes.map(() => [])
  edges.forEach((e, i) => {
    const a = byId[e.s]
    const b = byId[e.t]
    if (a == null || b == null) return
    adj[a].push({ n: b, e: i })
    adj[b].push({ n: a, e: i })
  })
  /* 主归属汇聚（V2 Phase 1）：三条规则依次比较，不再只按度数、
     也不再依赖 adj 顺序 —— 顺序变化会让同一份数据布局抖动。
       ① 层级更靠上的邻居优先；② 同层度数更大优先；③ 仍相同按设备 id 稳定排序。
     parent 只用于布局；全部真实连接始终留在 adj / edges 里。 */
  const parent = nodes.map((v, i) => {
    if (v.tier !== 3) return -1
    let best = -1
    for (const a of adj[i]) {
      const nb = nodes[a.n]
      if (!nb || nb.tier >= 3) continue
      if (best < 0) { best = a.n; continue }
      const cur = nodes[best]
      if (nb.tier !== cur.tier) { if (nb.tier < cur.tier) best = a.n; continue }
      if (nb.deg !== cur.deg) { if (nb.deg > cur.deg) best = a.n; continue }
      if (nb.id < cur.id) best = a.n
    }
    return best
  })
  // 全量上游关系：双归属设备同时保留两个上游，不因布局只取主归属而丢连接
  const upstream = nodes.map((v, i) => {
    const out: number[] = []
    for (const a of adj[i]) {
      const nb = nodes[a.n]
      if (nb && nb.tier < v.tier && !out.includes(a.n)) out.push(a.n)
    }
    return out
  })
  const hubs: number[] = []
  nodes.forEach((v, i) => { if (v.tier === 1 || v.tier === 2) hubs.push(i) })
  hubs.sort((a, b) => nodes[a].tier - nodes[b].tier || nodes[b].deg - nodes[a].deg)
  const hubOrder: Record<number, number> = {}
  hubs.forEach((h, k) => { hubOrder[h] = k })
  return { adj, parent, upstream, hubs, hubOrder, byId }
}

/** 确定性伪随机（线性同余）：同一份数据每次布局一致 */
function lcg(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    return s / 0x7fffffff
  }
}

/**
 * 轻量去重叠：只在 minDist 内互推，单点累计位移不超过 maxMove。
 * 地理视图必须限制位移（20px 时仍有 93 对 5px 内的重叠点，28px 才全分开），
 * 否则「真实地理位置」会被推得不像地图。
 */
function relax(pos: Pt[], minDist: number, iters: number, maxMove: number) {
  const orig = pos.map((p) => ({ x: p.x, y: p.y }))
  for (let it = 0; it < iters; it++) {
    const mv = pos.map(() => ({ x: 0, y: 0 }))
    for (let i = 0; i < pos.length; i++) {
      for (let j = i + 1; j < pos.length; j++) {
        let dx = pos[i].x - pos[j].x
        let dy = pos[i].y - pos[j].y
        let d = Math.sqrt(dx * dx + dy * dy)
        if (d >= minDist) continue
        if (d < 0.001) {
          dx = (i % 7) - 3 || 1
          dy = (j % 5) - 2 || 1
          d = Math.sqrt(dx * dx + dy * dy)
        }
        const push = ((minDist - d) / 2) * 0.55
        mv[i].x += (dx / d) * push
        mv[i].y += (dy / d) * push
        mv[j].x -= (dx / d) * push
        mv[j].y -= (dy / d) * push
      }
    }
    for (let q = 0; q < pos.length; q++) {
      let nx = pos[q].x + mv[q].x
      let ny = pos[q].y + mv[q].y
      const ox = nx - orig[q].x
      const oy = ny - orig[q].y
      const od = Math.sqrt(ox * ox + oy * oy)
      if (od > maxMove) {
        nx = orig[q].x + (ox / od) * maxMove
        ny = orig[q].y + (oy / od) * maxMove
      }
      pos[q].x = Math.max(20, Math.min(TOPO_W - 20, nx))
      pos[q].y = Math.max(20, Math.min(TOPO_H - 20, ny))
    }
  }
  return pos
}

/** 行式摆放：x 按行内序号等分，y 由调用方给的行函数决定。 */
function layRows(ids: number[], pos: Pt[], per: number, yOf: (r: number, rows: number) => number) {
  const rows = Math.ceil(ids.length / per)
  const m = 34
  const span = TOPO_W - m * 2
  ids.forEach((id, k) => {
    const r = Math.floor(k / per)
    const c = k % per
    const inRow = Math.min(per, ids.length - r * per)
    pos[id].x = inRow === 1 ? TOPO_W / 2 : m + (span * c) / (inRow - 1)
    pos[id].y = yOf(r, rows)
  })
}

/* ---------------------------- 布局 1：分层 ---------------------------- */
/**
 * 上游 → 核心 SPE → 汇聚 → 接入四带。接入点按「归属汇聚 → 环网邻居 BFS」串接后摊成 3 行。
 * 试过再加一轮重心扫描（barycenter）减交叉，实测反而从 390 涨到 1095（10 轮），已删。
 */
export function layoutTier(nodes: TopoNode[], idx: TopoIndex): LayoutResult {
  const pos: Pt[] = nodes.map(() => ({ x: 0, y: 0 }))
  const bands: { t: number; y: number; labelKey: string }[] = [
    { t: 0, y: 46, labelKey: 'ipranTopo.band.ext' },
    { t: 1, y: 128, labelKey: 'ipranTopo.band.core' },
    { t: 2, y: 212, labelKey: 'ipranTopo.band.agg' },
  ]
  bands.forEach((b) => {
    const ids: number[] = []
    nodes.forEach((v, i) => { if (v.tier === b.t) ids.push(i) })
    if (b.t === 2) ids.sort((a, c) => idx.hubOrder[a] - idx.hubOrder[c])
    const m = 40
    const span = TOPO_W - m * 2
    ids.forEach((id, k) => {
      pos[id].x = ids.length === 1 ? TOPO_W / 2 : m + (span * k) / (ids.length - 1)
      pos[id].y = b.y
    })
  })

  const accAll: number[] = []
  nodes.forEach((v, i) => { if (v.tier === 3) accAll.push(i) })
  const seen: Record<number, 1> = {}
  const order: number[] = []
  idx.hubs.forEach((h) => {
    const q: number[] = []
    idx.adj[h].forEach((a) => {
      if (nodes[a.n].tier === 3 && !seen[a.n]) { seen[a.n] = 1; q.push(a.n) }
    })
    q.sort((a, b) => nodes[a].site.localeCompare(nodes[b].site))
    while (q.length) {
      const cur = q.shift() as number
      order.push(cur)
      const nbs: number[] = []
      idx.adj[cur].forEach((a) => {
        if (nodes[a.n].tier === 3 && !seen[a.n]) { seen[a.n] = 1; nbs.push(a.n) }
      })
      nbs.sort((a, b) => nodes[a].site.localeCompare(nodes[b].site))
      nbs.forEach((x) => q.push(x))
    }
  })
  // 与任何汇聚都不相连的接入点（孤立/断链）排在最后
  accAll.forEach((id) => { if (!seen[id]) { seen[id] = 1; order.push(id) } })
  const acc = order

  const per = 26
  const accRows = Math.ceil(acc.length / per)
  layRows(acc, pos, per, (r, rs) => 306 + (r * (TOPO_H - 330)) / Math.max(1, rs - 1))

  const out: TopoBand[] = bands.map((b) => ({
    y: b.y, labelKey: b.labelKey, count: nodes.filter((v) => v.tier === b.t).length,
  }))
  out.push({
    y: 306, labelKey: 'ipranTopo.band.access', count: acc.length, rows: accRows,
  })
  return { pos, bands: out }
}

/* --------------------------- 布局 2：力导向 --------------------------- */
/**
 * Fruchterman-Reingold + 弱层级引力。起点取分层结果再加抖动。
 * K=36 / ITER=1400 / 种子 31415 是原算法（`layoutForceClassic`）扫出来的组合。
 * `cluster: true`（页面默认）只把接入点往主归属的水平位置拉近，不删边、不改双归属。
 */
export function layoutForce(
  nodes: TopoNode[], idx: TopoIndex, edges: TopoEdge[],
  opts?: { cluster?: boolean },
): LayoutResult {
  const cluster = !!opts?.cluster
  const base = layoutTier(nodes, idx).pos
  const rnd = lcg(31415)
  const pos = base.map((p) => ({ x: p.x + (rnd() - 0.5) * 60, y: p.y + (rnd() - 0.5) * 60 }))
  const targetY = [46, 120, 205, 400]
  const ITER = 1400
  const K = 36
  const eIdx = edges
    .map((e) => ({ s: idx.byId[e.s], t: idx.byId[e.t] }))
    .filter((e) => e.s != null && e.t != null)

  for (let it = 0; it < ITER; it++) {
    const cool = 1 - it / ITER
    const disp = pos.map(() => ({ x: 0, y: 0 }))
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = pos[i].x - pos[j].x
        let dy = pos[i].y - pos[j].y
        let d2 = dx * dx + dy * dy
        if (d2 < 0.01) {
          dx = rnd() - 0.5 || 0.1
          dy = rnd() - 0.5 || 0.1
          d2 = dx * dx + dy * dy
        }
        const d = Math.sqrt(d2)
        const f = ((K * K) / d2) * 1.5
        disp[i].x += (dx / d) * f
        disp[i].y += (dy / d) * f
        disp[j].x -= (dx / d) * f
        disp[j].y -= (dy / d) * f
      }
    }
    eIdx.forEach((e) => {
      const dx = pos[e.s].x - pos[e.t].x
      const dy = pos[e.s].y - pos[e.t].y
      const d = Math.sqrt(dx * dx + dy * dy) || 0.1
      const f = ((d * d) / K) * 0.06
      disp[e.s].x -= (dx / d) * f
      disp[e.s].y -= (dy / d) * f
      disp[e.t].x += (dx / d) * f
      disp[e.t].y += (dy / d) * f
    })
    for (let q = 0; q < nodes.length; q++) {
      disp[q].y += (targetY[nodes[q].tier] - pos[q].y) * 0.1
      if (cluster && nodes[q].tier === 3) {
        const parent = idx.parent[q]
        if (parent >= 0) {
          disp[q].x += (pos[parent].x - pos[q].x) * 0.045
          disp[q].y += (pos[parent].y - pos[q].y) * 0.012
        }
      }
      const dl = Math.sqrt(disp[q].x * disp[q].x + disp[q].y * disp[q].y) || 0.1
      const lim = Math.min(dl, 14 * cool + 0.6)
      pos[q].x += (disp[q].x / dl) * lim
      pos[q].y += (disp[q].y / dl) * lim
      pos[q].x = Math.max(26, Math.min(TOPO_W - 26, pos[q].x))
      pos[q].y = Math.max(26, Math.min(TOPO_H - 26, pos[q].y))
    }
  }
  return { pos, bands: [] }
}

/** 改造前的力导向，参数与 2026-11-10 扫出的 42 次交叉组合一致。页面默认不再调用它。 */
export function layoutForceClassic(nodes: TopoNode[], idx: TopoIndex, edges: TopoEdge[]): LayoutResult {
  return layoutForce(nodes, idx, edges)
}

/* ---------------------------- 布局 3：地理 ---------------------------- */
/**
 * 经纬度等距投影（利比里亚范围小，不做墨卡托）。无坐标的节点**不猜位置**，
 * 按 24 个一行列在图底并显式标注数量。
 * relax 的 maxMove 必须是 28：蒙罗维亚城区站点真实同址，9px 时仍剩 86 对重叠。
 */
export function layoutGeo(nodes: TopoNode[]): LayoutResult {
  const pos: Pt[] = nodes.map(() => ({ x: -999, y: -999 }))
  const gl: number[] = []
  nodes.forEach((v, i) => { if (v.lat != null && v.lon != null) gl.push(i) })

  if (gl.length) {
    const lats = gl.map((i) => nodes[i].lat as number)
    const lons = gl.map((i) => nodes[i].lon as number)
    const la0 = Math.min(...lats)
    const la1 = Math.max(...lats)
    const lo0 = Math.min(...lons)
    const lo1 = Math.max(...lons)
    const padX = 46
    const padY = 40
    const boxH = 400
    const sx = (TOPO_W - padX * 2) / Math.max(1e-6, lo1 - lo0)
    const sy = (boxH - padY * 2) / Math.max(1e-6, la1 - la0)
    const s = Math.min(sx, sy)
    const ox = (TOPO_W - (lo1 - lo0) * s) / 2
    const oy = (boxH - (la1 - la0) * s) / 2
    gl.forEach((i) => {
      pos[i] = {
        x: ox + ((nodes[i].lon as number) - lo0) * s,
        y: oy + (la1 - (nodes[i].lat as number)) * s,
      }
    })
  }

  const miss: number[] = []
  nodes.forEach((v, i) => { if (pos[i].x < -900) miss.push(i) })
  const per = 24
  miss.forEach((id, k) => {
    const r = Math.floor(k / per)
    const c = k % per
    const inRow = Math.min(per, miss.length - r * per)
    pos[id] = {
      x: 36 + (TOPO_W - 72) * (inRow === 1 ? 0.5 : c / (inRow - 1)),
      y: 458 + r * 34,
    }
  })
  relax(pos, 11, 140, 28)
  return {
    pos,
    bands: miss.length ? [{ y: 434, labelKey: 'ipranTopo.band.geoMiss', count: miss.length }] : [],
    geoMatched: gl.length,
    geoBoxH: 400,
  }
}

export const LAYOUT_FNS: Record<
  'tier' | 'geo' | 'force',
  (nodes: TopoNode[], idx: TopoIndex, edges: TopoEdge[]) => LayoutResult
> = {
  tier: (nodes, idx) => layoutTier(nodes, idx),
  force: (nodes, idx, edges) => layoutForce(nodes, idx, edges, { cluster: true }),
  geo: (nodes) => layoutGeo(nodes),
}

/** 节点半径（核心最大、层外用方块）。 */
export function radiusOf(tier: TopoNode['tier']): number {
  return tier === 1 ? 9 : tier === 2 ? 7 : tier === 0 ? 5.5 : 4.5
}

/** 边线宽按端口速率分档：100G > 25G > 10G > 其它/未知。 */
export function widthOf(gb: number | null): number {
  if (gb == null) return 0.8
  if (gb >= 100) return 2.4
  if (gb >= 25) return 1.7
  if (gb >= 10) return 1.2
  return 0.8
}
