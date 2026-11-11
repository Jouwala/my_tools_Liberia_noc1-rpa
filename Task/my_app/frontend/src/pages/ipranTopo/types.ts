/** UME 拓扑页的数据与布局类型（与 /api/ipran-topo/graph 的返回结构对齐）。 */

/** 四张 UME 逻辑拓扑层；与后端 layers.LAYERS 的 key 一一对应，非法值后端会 400。 */
export type LayerKey = 'ipran' | 'ipcore' | 'metro' | 'dwdm'

/** 0 层外上游 / 1 核心 / 2 汇聚 / 3 接入（层级名称按层翻译，见 layerDefs.ts） */
export type Tier = 0 | 1 | 2 | 3

export type Sev = 'crit' | 'major' | 'minor' | 'warn' | 'ok'

/** 站点坐标匹配结果：exact 精确 / fuzzy 近似（需人工确认）/ miss 库内无坐标 / ext 层外设备 */
export type GeoHow = 'exact' | 'fuzzy' | 'miss' | 'ext'

export interface TopoNode {
  id: string
  name: string
  site: string
  tier: Tier
  model: string
  ip: string
  /** 1 = connectionState 正常 */
  up: number
  crit: number
  major: number
  minor: number
  warn: number
  sev: Sev
  lat: number | null
  lon: number | null
  geo: GeoHow
  geoName: string
  /** 端口级度数（折叠前） */
  deg: number
}

export interface TopoEdge {
  /** 端点 node id */
  s: string
  t: string
  /** 这对机框折叠了几条物理链路 */
  n: number
  /** 组内最小端口速率（GB）；解析不出为 null */
  gb: number | null
  /** 组内 down 的链路条数 */
  down: number
  crit: number
  major: number
  /** 最多 12 条链路名，供悬停明细 */
  ports: string[]
  /**
   * 接收/发送利用率（%）。当前 graph 接口不返回这两项，缺省即界面显示 N/A。
   * 禁止用端口速率 gb 去填。
   */
  rxUtil?: number | null
  txUtil?: number | null
}

export interface TopoMeta {
  /** 后端回填的层 key / 层名，用于核对响应与当前页签是否一致 */
  layer?: string
  layerName?: string
  fetchedAt?: string
  elapsedSec?: number
  cached?: boolean
  /** 上游取数失败、当前为上次成功数据 */
  stale?: boolean
  ne: number
  ext: number
  rawLinks: number
  foldedLinks: number
  tierCounts: Record<string, number>
  geo: Record<string, number>
  geoMissSites: string[]
  geoFuzzyPairs: { site: string; matched: string }[]
  critNe: number
  warnings: string[]
}

export interface TopoResp {
  nodes: TopoNode[]
  edges: TopoEdge[]
  meta: TopoMeta
}

export interface Pt { x: number; y: number }

/** 分层视图的分带标注；labelKey 由页面翻成文案，count 用于「接入 78 个 · 3 行」这类补充 */
export interface TopoBand {
  y: number
  labelKey: string
  count?: number
  rows?: number
}

export interface LayoutResult {
  pos: Pt[]
  bands: TopoBand[]
  /** 地理视图：有坐标的节点数 / 画布上方的地图区高度 */
  geoMatched?: number
  geoBoxH?: number
}

export type LayoutKey = 'force' | 'geo' | 'tier'
export type ColorMode = 'tier' | 'up' | 'sev'

/** 邻接索引：adj[i] = [{ n: 邻居下标, e: 边下标 }] */
export interface TopoIndex {
  adj: { n: number; e: number }[][]
  /** 接入点的主归属汇聚下标（-1 表示无）。仅用于布局排序，不代表唯一上游 */
  parent: number[]
  /** 每个节点的全部上游邻居（去重）：双归属设备会同时保留两个上游 */
  upstream: number[][]
  /** 核心+汇聚节点，按「层级 → 度数」排序 */
  hubs: number[]
  hubOrder: Record<number, number>
  byId: Record<string, number>
}
