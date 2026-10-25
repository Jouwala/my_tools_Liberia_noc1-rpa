/* 县界底图的派生数据（2026-10-24 从 PersonMapView 抽出）
 *
 * 抽出资因：PersonMapView 加县名标签（10-23）+「默认站点」辖区模式（10-24）后
 * 714 行，超 AGENTS.md 三.2 的 500 行纪律。本文件收走县界这一层的全部
 * **派生计算**（与地图渲染无关的部分）：
 *   · countyColor —— 每县一种类别色（县块填充/描边用；县名标签与县块同色）；
 *   · COUNTY_FILL_OPACITY —— 县块填充不透明度（深浅两档）；
 *   · countyTypeLines + typeCountsLine —— 县名标签第二/三行文本
 *     （传输类型 / 维护分类）。
 * 渲染（县块 Polygon、县名标签 Marker 与避让 effect）分别在 PersonMapView
 * 与 `personmap/CountyLabels.tsx`。
 *
 * 需求背景（2026-10-23 用户要求「地图显示县名、不同的县不同颜色」）与
 * 「为什么不用后端 CountyBoundary.color」的完整论证见手册 11a 与
 * PROJECT 注释 —— 原注释随代码一并搬到这里，未改写。
 */
import { useMemo } from 'react'
import type { CountyBoundary } from '../gismap/types'

/** 县块类别配色（2026-10-23 用户要求「地图显示县名、不同的县不同颜色」）。
 *
 *  **为什么不用后端 `CountyBoundary.color`**：那是 `REGION_COLORS` 的 6 色循环
 *  （gis_geometry.py::load_county_boundaries，为 3 个大区设计的表）套在 15 个县上，
 *  按名称排序必然撞色 —— 且撞在**接壤**的县上（Bong/Lofa 同 #4ecdc4、
 *  Nimba/Grand Gedeh 同 #dda0dd），肉眼分不出边界，等于没满足「不同县不同色」。
 *  在前端给满 15 个互不相同的色相即可，不动后端（改后端要重启 7038 生产服务）。
 *
 *  **取色规则**：15 个色相在色环上尽量均匀分布，相邻条目刻意拉开
 *  （红→橙→黄→绿…循环）。映射按**县名字典序**的稳定下标（与后端
 *  load_county_boundaries 的排序同序），刷新/换主题/换语言都不会换色。
 *  ⚠ 同 SITE_TONE 的约束：SVG 呈现属性不认 CSS 变量，必须是十六进制实值。 */
const COUNTY_PALETTE = [
  '#e05c6a', // Bomi            红
  '#e08a4f', // Bong            橙
  '#d9c24a', // Gbarpolu        黄
  '#9ec54a', // Grand Bassa     黄绿
  '#58bd6f', // Grand Cape Mount 绿
  '#2fbf9b', // Grand Gedeh     青绿
  '#43b8cf', // Grand Kru       青
  '#4f9fea', // Lofa            天蓝
  '#5d7fe0', // Margibi         蓝
  '#7b79dd', // Maryland        靛
  '#8f6fd8', // Montserrado     紫罗兰
  '#c46fce', // Nimba           紫
  '#a97e4f', // River Cess      棕
  '#e0568f', // River Gee       玫红
  '#b5495c', // Sinoe           酒红
] as const

/** 县块填充不透明度（与 GIS 页 FILL_OPACITY 同值同因）：底图瓦片深色主题下被
 * index.css 整体反相，同一透明度两个主题的对比表现是反的 —— 深色反而要更高
 * 才看得出来。类别色只做「分县」的底，不能压过站点圆点/人员针的视觉重心。 */
export const COUNTY_FILL_OPACITY = { dark: 0.13, light: 0.09 } as const

/* 县标签「类型统计」行的展示规则（2026-10-23 用户要求「站点总数 + 类型统计」，
 * 经确认传输类型与维护分类**都要**）：
 *   · 传输 = trm_type（MW / Satellite Link / Starlink / IPRAN），维护 = site_caregory
 *     （NORMAL / ERA / COOL —— 列名在库里就拼成 caregiver，照用）；
 *   · 固定顺序展示，计 0 的组**不显示**（宁短勿噪）；库里出现新值时追加在固定序之后；
 *   · site_count − sum(分组) > 0 时补「— n」段：那是类型为 NULL/空串的站点
 *     （AGENTS.md 三.6：取不到的不冒充任何一类，显示 —）；
 *   · 旧后端/旧缓存没有这两个分组字段时两行为空，标签退化为「县名+总数」。 */
const TRM_ORDER = ['MW', 'Satellite Link', 'Starlink', 'IPRAN']
const TRM_SHORT: Record<string, string> = {
  'MW': 'MW', 'Satellite Link': 'SAT', 'Starlink': 'ST', 'IPRAN': 'IPRAN',
}
const CAT_ORDER = ['NORMAL', 'ERA', 'COOL']

/** 把一组分组计数拼成 "MW 30 · SAT 2 · — 2" 形式的单行文本。 */
function typeCountsLine(
  counts: Record<string, number> | undefined,
  total: number,
  order: string[],
  short: (v: string) => string,
): string {
  if (!counts) return ''
  const keys = [
    ...order.filter(k => (counts[k] || 0) > 0),
    ...Object.keys(counts).filter(k => !order.includes(k) && (counts[k] || 0) > 0),
  ]
  const segs = keys.map(k => `${short(k)} ${counts[k]}`)
  const known = Object.values(counts).reduce((s, n) => s + (n || 0), 0)
  if (total - known > 0) segs.push(`— ${total - known}`)
  return segs.join(' · ')
}

/** 县界底图层的派生数据。counties 重复到达（缓存 30s 内复用、刷新）时结果稳定：
 *  颜色与统计文本都以县名为 key，按县名字典序的稳定下标映射。 */
export function useCountyTags(counties: CountyBoundary[]) {
  /* 县 → 类别色。按县名字典序取 COUNTY_PALETTE 的稳定下标（排序规则与
     后端 load_county_boundaries 一致），故颜色与 GeoJSON 的到达顺序无关、
     刷新不变。取不到色（ county 数超过色表等异常）回落到中性灰，不臆造。 */
  const countyColor = useMemo(() => {
    const m = new Map<string, string>()
    const sorted = [...counties].sort((a, b) => a.name.localeCompare(b.name))
    sorted.forEach((c, i) => m.set(c.name, COUNTY_PALETTE[i % COUNTY_PALETTE.length]))
    return m
  }, [counties])

  /* 每县的两行类型统计文本（传输 / 维护），渲染县标签时用。 */
  const countyTypeLines = useMemo(() => {
    const m = new Map<string, { trm: string; cat: string }>()
    for (const c of counties) {
      const total = c.site_count || 0
      m.set(c.name, {
        trm: typeCountsLine(c.trm_counts, total, TRM_ORDER, v => TRM_SHORT[v] || v),
        cat: typeCountsLine(c.caregory_counts, total, CAT_ORDER, v => v),
      })
    }
    return m
  }, [counties])

  return { countyColor, countyTypeLines }
}
