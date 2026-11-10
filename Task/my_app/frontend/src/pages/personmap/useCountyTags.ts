/* 县界底图的派生数据（2026-10-24 从 PersonMapView 抽出）
 *
 * 抽出资因：PersonMapView 加县名标签（10-23）+「默认站点」辖区模式（10-24）后
 * 714 行，超 AGENTS.md 三.2 的 500 行纪律。本文件收走县界这一层的全部
 * **派生计算**（与地图渲染无关的部分）：
 *   · countyColor —— 每县一种类别色（色表已迁 `gismap/countyPalette.ts`，
 *     2026-11-09 起人员页与 ipt_power 页共用同一份）；
 *   · COUNTY_FILL_OPACITY —— 县块填充不透明度（同一份共享常量的别名）；
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
import {
  COUNTY_CATEGORY_OPACITY, countyCategoryColors,
} from '../gismap/countyPalette'

/** 色表 / 填充透明度 / 县→色的稳定映射已抽到 `gismap/countyPalette.ts`
 *  （2026-11-09，IPT 电源页要「按县上色、参考人员页」时共用同一份真相源）。
 *  本文件只保留渲染派生（县名标签的两行统计文本），人员页观感逐像素不变。
 *  原注释里的取色理由（为什么不用后端 color、为什么必须十六进制实值、0.8 的
 *  来历与回退建议）随代码一并搬到新模块，未改写。 */
export const COUNTY_FILL_OPACITY = COUNTY_CATEGORY_OPACITY

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
  /* 县 → 类别色：共享模块按县名字典序取 COUNTY_PALETTE 的稳定下标，
     故颜色与 GeoJSON 的到达顺序无关、刷新不变、且与 ipt_power 页逐县同色。 */
  const countyColor = useMemo(() => countyCategoryColors(counties), [counties])

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
