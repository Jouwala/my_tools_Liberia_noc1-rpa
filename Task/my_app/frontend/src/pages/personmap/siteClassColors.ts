/* 站点类别图例的配色（2026-10-28）
 *
 * **为什么单独一个文件**：图例的取色是「界面表达」，与取数（useSiteClasses）
 * 和渲染（SiteClassLayer）都不该混在一起；单独放，改颜色不用碰逻辑。
 *
 * **取色规则**：
 *   · 已知取值 → 固定色（下表）。同一个类别在任何筛选组合下都是同一个颜色，
 *     否则用户会以为「ERA 换色了 = 数据变了」。
 *   · 未知取值（库里后来新增的类别）→ 按取值的稳定散列取备用色，
 *     保证**同一个值始终同一个色**，而不是随机跳。
 *   · 未填（空串）→ 中性灰。它不是一个类别（AGENTS.md 三.6：取不到的
 *     不冒充任何一类），故不与任何类别同色。
 *
 * ⚠ 必须是**十六进制实值**：Leaflet 的 CircleMarker 走 SVG 呈现属性，
 *   解析不了 `var(--wh-*)`（与 ECharts 同一约束，AGENTS.md 三.3 取色表）。
 */
const FIXED: Record<string, Record<string, string>> = {
  // 维护分类（site_caregory）：NORMAL / ERA / COOL —— 库里的实际取值
  site_caregory: {
    NORMAL: '#7c8da6', // 灰蓝 —— 量最大，作底色不抢眼
    ERA: '#f59e0b',    // 琥珀
    COOL: '#22d3ee',   // 青
  },
  // VIP / HUB：Y 给高亮色，N 给中性色（"不是"不需要颜色）
  vip_site: { Y: '#f5c542', N: '#6b7a90' },
  hub_site: { Y: '#a855f7', N: '#6b7a90' },
  // 传输类型（trm_type）
  trm_type: {
    MW: '#3b82f6',
    'Satellite Link': '#8b5cf6',
    Starlink: '#10b981',
    IPRAN: '#f97316',
  },
}

/** 未知取值（或库里新增类别）的备用色板 */
const SPARE = [
  '#ef4444', '#14b8a6', '#eab308', '#ec4899', '#0ea5e9',
  '#84cc16', '#f97316', '#6366f1', '#d946ef', '#64748b',
] as const

/** 未填（NULL / 空串）专用色 —— 不与任何类别撞色 */
export const SITE_CLASS_EMPTY_COLOR = '#8b93a1'

/**
 * 某个分组下某个取值的展示色。
 * 同一 (group, value) 组合**永远返回同一个颜色**（纯函数、无随机）。
 */
export function siteClassColor(group: string, value: string): string {
  if (!value) return SITE_CLASS_EMPTY_COLOR
  const fixed = FIXED[group]
  if (fixed && fixed[value]) return fixed[value]
  let h = 0
  for (let i = 0; i < value.length; i += 1) h = (h * 31 + value.charCodeAt(i)) % 100003
  return SPARE[h % SPARE.length]
}
