/* 15 个县的「类别色」真相源（2026-10-23 人员页首创，2026-11-09 抽成共享模块）
 *
 * **为什么单独存在**：原先这 15 个色值埋在 `personmap/useCountyTags.ts` 里，
 * 只有 ?page=person 的县块用它。IPT 电源页（?page=ipt_power）要「按县上色，
 * 参考人员页」时，若在那边再抄一份色表，两页很快就会分叉 —— 同一块国土在
 * 两个页面里颜色不同，是最容易被当成 bug 的那种不一致（AGENTS.md 三.10：
 * 删除优于兼容，一份真相源优于两份拷贝）。故抽到 gismap 下供两页共用。
 *
 * **为什么不用后端 `CountyBoundary.color`**：那是 `REGION_COLORS` 的 6 色循环
 * （gis_geometry.py::load_county_boundaries，为 3 个大区设计的表）套在 15 个县上，
 * 按名称排序必然撞色，且撞在**接壤**的县上（Bong/Lofa 同 #4ecdc4、
 * Nimba/Grand Gedeh 同 #dda0dd），肉眼分不出边界。前端给满 15 个互不相同的
 * 色相即可，不动后端（改后端要重启 7038 生产服务）。
 *
 * ⚠ 色值必须是**十六进制实值**：它们喂给 Leaflet 的 SVG `fillColor`，
 *   SVG 呈现属性解析不了 `var(--wh-*)`（AGENTS.md 三.3 主题取色）。
 *
 * ⚠ 映射按**县名字典序**的稳定下标（与后端 load_county_boundaries 的排序同序），
 *   与 GeoJSON 到达顺序无关，刷新 / 换主题 / 换语言都不会换色。
 */
import type { CountyBoundary } from './types'

export const COUNTY_PALETTE = [
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

/** 县块类别色的填充不透明度。
 *
 *  2026-10-29 用户要求「颜色的不透明度改成 80%」→ 深浅两档统一 0.8。
 *  ⚠ 这是一次**有意的反转**：原值 dark 0.13 / light 0.09（与 GIS 页 FILL_OPACITY
 *     同值），理由是「类别色只做分县的底，不能压过站点圆点/人员针的视觉重心」。
 *     0.8 之下县块成为画面主体、底图细节基本不可见 —— 这是用户直接指定的值。
 *     若后续反馈「点/针看不清」，先回到 0.13 / 0.09 试。
 *  两页共用同一档，保证「参考人员页」不是近似而是逐像素同色同浓度。 */
export const COUNTY_CATEGORY_OPACITY = { dark: 0.8, light: 0.8 } as const

/** 县名 → 类别色。取不到色（县数超色表等异常）由调用方回落中性灰，不臆造。 */
export function countyCategoryColors(counties: CountyBoundary[]): Map<string, string> {
  const m = new Map<string, string>()
  const sorted = [...counties].sort((a, b) => a.name.localeCompare(b.name))
  sorted.forEach((c, i) => m.set(c.name, COUNTY_PALETTE[i % COUNTY_PALETTE.length]))
  return m
}
