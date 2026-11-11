/* ============================================================================
 * 拓扑标签排版（纯函数，不碰 DOM）
 * ============================================================================
 * 为什么需要它：原先每个标签都画在节点正上方、居中、字号 11、最长 20 字符。
 * 接入层一行 26 个节点、间距约 27px，而一个标签实际宽 80~120px —— 必然 4~5 层
 * 叠字，整片糊成一团（2026-11-10 用户截图）。布局参数（K/ITER/种子）是实测扫
 * 出来的，不该为了标签去动；因此在这里做**渲染层的贪心排版**：
 *
 *   1. 短名 + 按层级给字号，先把标签本身变窄；
 *   2. 按重要度排序（聚焦节点 / 聚焦邻居 / 层级高 / 度数大 / 故障 / 名称短）；
 *   3. 每个标签依次尝试 上 / 下 / 上偏左 / 上偏右 四个候选位；
 *   4. 与「已放下的标签」+「分带标题区」做 AABB 碰撞检测，越界也判失败；
 *   5. 四个位置都放不下就**隐藏**，而不是硬画上去 —— 全名仍可悬停查看。
 *
 * 同一行节点会自然形成上下交错的标签排布：相邻两个的「上方」盒冲突时，第二个
 * 落到下方，第三个与第一个水平距离够了又能回到上方。实测这比统一置顶清晰得多。
 * ========================================================================== */
import { radiusOf } from './layouts'
import type { Pt, TopoBand, TopoNode } from './types'

export interface LabelBox {
  /** 节点在 nodes 里的下标 */
  i: number
  text: string
  /** text 的 x（textAnchor=middle）与 baseline y */
  x: number
  y: number
  fontSize: number
}

export interface LabelOptions {
  pos: Pt[]
  focus: number
  showAllLabels: boolean
  nbSet: Record<number, 1> | null
  bands: TopoBand[]
  W: number
  H: number
}

export interface LabelResult {
  labels: LabelBox[]
  /** 本该显示但因空间不足被隐藏的标签数（界面要显式告诉用户，不能悄悄丢） */
  hidden: number
}

interface Rect { x: number; y: number; w: number; h: number }

const CJK = /[\u2e80-\u9fff\uff00-\uffef]/

/** 估算 SVG 文本宽度：中文按一个字号，ASCII 按 0.56 个字号的近似字宽。 */
function textWidth(s: string, fs: number): number {
  let w = 0
  for (const ch of s) w += CJK.test(ch) ? fs : fs * 0.56
  return w
}

/** 接入层用后端清洗过的站点名；其余用设备名。长名一律截断，全名靠悬停看。 */
function shortName(v: TopoNode): string {
  const raw = (v.tier === 3 ? (v.site || v.name) : v.name) || ''
  const max = v.tier === 3 ? 10 : v.tier === 0 ? 12 : 14
  return raw.length > max ? `${raw.slice(0, max - 1)}…` : raw
}

/** 层级越高字越大，形成视觉主次；接入层刻意最小，因为它最密。 */
function fontSizeOf(tier: TopoNode['tier']): number {
  switch (tier) {
    case 1: return 11
    case 2: return 10
    case 0: return 9.5
    default: return 9
  }
}

function overlaps(a: Rect, b: Rect, pad = 2): boolean {
  return a.x < b.x + b.w + pad && a.x + a.w + pad > b.x &&
    a.y < b.y + b.h + pad && a.y + a.h + pad > b.y
}

function inBounds(r: Rect, W: number, H: number): boolean {
  return r.x >= 4 && r.x + r.w <= W - 4 && r.y >= 2 && r.y + r.h <= H - 2
}

/** 重要度：数值越大越优先占位。聚焦相关节点必须保住标签。 */
function priority(v: TopoNode, i: number, o: LabelOptions, nameLen: number): number {
  return (i === o.focus ? 10000 : 0)
    + (o.nbSet && o.nbSet[i] ? 2000 : 0)
    + (v.tier === 1 ? 400 : v.tier === 0 ? 300 : v.tier === 2 ? 200 : 0)
    + (!v.up ? 80 : 0)
    + (v.crit > 0 ? 40 : 0)
    + Math.min(v.deg, 30)
    + (20 - Math.min(nameLen, 20)) * 0.5
}

export function layoutLabels(nodes: TopoNode[], o: LabelOptions): LabelResult {
  const obstacles: Rect[] = []
  // 分带标题占位：避免标签压在 "upstream (7)" / "无坐标（16）" 这类说明上
  o.bands.forEach((b) => {
    obstacles.push({ x: 8, y: b.y - 26, w: 180, h: 15 })
  })

  const candidates: { i: number; name: string; fs: number; pri: number }[] = []
  nodes.forEach((v, i) => {
    let want = v.tier <= 2 || o.showAllLabels
    if (o.nbSet && !o.nbSet[i]) want = want && v.tier <= 1
    if (i === o.focus) want = true
    if (!want || !o.pos[i]) return
    const name = shortName(v)
    if (!name) return
    candidates.push({ i, name, fs: fontSizeOf(v.tier), pri: priority(v, i, o, name.length) })
  })
  candidates.sort((a, b) => b.pri - a.pri || a.i - b.i)

  const labels: LabelBox[] = []
  for (const c of candidates) {
    const p = o.pos[c.i]
    const r = radiusOf(nodes[c.i].tier)
    const w = textWidth(c.name, c.fs)
    const h = c.fs + 1
    // 上 / 下 / 上偏左 / 上偏右：前两个负责上下交错，后两个用来塞进剩余缝隙
    const spots = [
      { dx: 0, dy: -(r + 4) },
      { dx: 0, dy: r + 4 + h },
      { dx: -w * 0.28, dy: -(r + 4) },
      { dx: w * 0.28, dy: -(r + 4) },
    ]
    for (const s of spots) {
      const x = p.x + s.dx
      const y = p.y + s.dy
      const box: Rect = { x: x - w / 2, y: y - c.fs, w, h }
      if (!inBounds(box, o.W, o.H)) continue
      if (obstacles.some((q) => overlaps(box, q))) continue
      obstacles.push(box)
      labels.push({ i: c.i, text: c.name, x, y, fontSize: c.fs })
      break
    }
  }

  // 回到节点顺序渲染，避免 SVG 绘制顺序受优先级影响（视觉上无差，但便于调试）
  labels.sort((a, b) => a.i - b.i)
  return { labels, hidden: candidates.length - labels.length }
}
