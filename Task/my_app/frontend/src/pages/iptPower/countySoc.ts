/* 县维度 SOC 底色（?page=ipt_power，2026-11-06 新增）
 *
 * 用户问「地图能不能按照州添加背景颜色」，选定口径 = **该县电源快照的平均 SOC**。
 * 本文件只做纯计算与档位定义，不碰 React，方便单独核对数字。
 *
 * 为什么在前端算而不是后端加一个 county 聚合接口：与 GIS 页同一个结论
 * （`GISMap.tsx:1089`，2026-10-21 起县告警数不再用后端静态值）—— 底色必须与
 * **地图上此刻画出来的那批站点**同源。IPT 页的站点集合受搜索词影响，后端算好的
 * 全量平均会和画面打架；而这里吃的就是 `iptPowerSites` 已经返回的 501 行，零额外请求。
 *
 * 档位阈值不是拍的：2026-11-06 实测 15 县的县均值落在 59.3%（Grand Kru）~ 84.5%
 * （Grand Bassa），站级 SOC 的 p25=61% / p50=82%。取 80 / 70 / 60 三刀把 15 县切成
 * 7 / 6 / 1 / 1，既能拉开颜色又不会让大半地图同色。
 *
 * ⚠ 色值必须是**十六进制实值**：它们喂给 Leaflet 的 SVG `fillColor`，
 *   canvas/SVG 解析不了 `var(--wh-*)`（AGENTS.md 三.3 主题取色）。
 *   五色沿用 GIS 页 `COUNTY_BAND_COLORS` 的同一组红橙黄绿灰，跨页观感一致。
 */
/** 五档：四档 SOC + 一档「样本不足不参与分档」 */
export type SocBand = 'good' | 'fair' | 'poor' | 'critical' | 'few'

/** 参与分档所需的最少有快照站数：少于这个数，平均值会被单站噪声拉飞，直接归灰档 */
export const MIN_SOC_SAMPLES = 3

export type CountySoc = {
  /** 该县「有 SOC 快照的站点」的算术平均值，0~1；无样本为 null */
  avg: number | null
  /** 参与平均的站点数（分母） */
  samples: number
  /** 该县在当前站点集合里的总数（tooltip 里做对照） */
  sites: number
  band: SocBand
}

/** IPT 上游的 organization 写法 → GeoJSON 县名（`/gis/county-boundaries` 的 `name`）
 *  实测 2026-11-06：IPT 501 站的 organization 去重后 16 个值，除下面三条外
 *  与 GeoJSON 的 15 个县名逐字相同。 */
const ORG_ALIAS: Record<string, string> = {
  'grand bassa': 'Grand Bassa',   // IPT 小写 bassa，GeoJSON 是 Grand Bassa
  'river cess': 'Rivercess',      // GeoJSON 的 name 连写（db_name 才分开写）
  'bopolu': 'Gbarpolu',           // Bopolu 不是县，是 Gbarpolu 县的首府/第 15 区
}

/** 归一化：小写 + 压掉多余空格；匹配不到返回 null（该站不进任何县，底色忽略它） */
export function countyOfOrg(org?: string | null): string | null {
  const key = (org || '').trim().toLowerCase().replace(/\s+/g, ' ')
  if (!key) return null
  if (ORG_ALIAS[key]) return ORG_ALIAS[key]
  // GeoJSON 侧的规范名首字母大写，其余原样；这里按大小写不敏感再兜一次
  const canon = CANON_COUNTIES.find(c => c.toLowerCase() === key)
  return canon || null
}

/** `/gis/county-boundaries` 的 15 个县名（2026-11-06 实测该接口的 name 列） */
export const CANON_COUNTIES = [
  'Bomi', 'Bong', 'Gbarpolu', 'Grand Bassa', 'Grand Cape Mount', 'Grand Gedeh',
  'Grand Kru', 'Lofa', 'Margibi', 'Maryland', 'Montserrado', 'Nimba',
  'River Gee', 'Rivercess', 'Sinoe',
]

/**
 * 按 organization 分组求平均 SOC。
 * 只统计 `battery_soc` 非空的站（离线/未采到的站没有该字段，不能当 0 算 —— 那会把
 * 整县颜色直接压成红色，且与表格里显示的「-」自相矛盾）。
 */
export function aggregateCountySoc(
  rows: { organization?: string | null; battery_soc?: number | null }[],
): Map<string, CountySoc> {
  const acc = new Map<string, { sum: number; samples: number; sites: number }>()
  rows.forEach(r => {
    const county = countyOfOrg(r.organization)
    if (!county) return
    const cur = acc.get(county) || { sum: 0, samples: 0, sites: 0 }
    cur.sites += 1
    const soc = r.battery_soc
    if (typeof soc === 'number' && Number.isFinite(soc)) {
      cur.sum += soc
      cur.samples += 1
    }
    acc.set(county, cur)
  })

  const out = new Map<string, CountySoc>()
  acc.forEach((v, county) => {
    const avg = v.samples ? v.sum / v.samples : null
    out.set(county, { avg, samples: v.samples, sites: v.sites, band: socBand(avg, v.samples) })
  })
  return out
}

/** 分档：先判样本充足性，再按阈值落档 */
export function socBand(avg: number | null, samples: number): SocBand {
  if (avg == null || samples < MIN_SOC_SAMPLES) return 'few'
  if (avg >= 0.80) return 'good'
  if (avg >= 0.70) return 'fair'
  if (avg >= 0.60) return 'poor'
  return 'critical'
}

export const SOC_BAND_COLOR: Record<SocBand, string> = {
  good: '#52c41a',       // ≥80%
  fair: '#f6cf00',       // 70~80%
  poor: '#ff922b',       // 60~70%
  critical: '#ff4d4f',   // <60%
  few: '#9aa5b5',        // 样本不足，不参与分档
}

/** 图例顺序（自上而下 = 由好到差，最后一格是「样本不足」） */
export const SOC_BAND_ORDER: SocBand[] = ['good', 'fair', 'poor', 'critical', 'few']

/**
 * 档位 → 文案键。刻意用 switch 返回**字面量键**而不是 `'ipt.band.' + band`：
 * 动态拼键会被 `scripts/check-i18n.mjs` 读成 `ipt.band.` 并报「字典缺失」
 * （同 AGENTS.md 三.1b 里 `NocAnalyst.sliceLabelKey()` 的理由）。
 */
export function bandLabelKey(band: SocBand): string {
  switch (band) {
    case 'good': return 'ipt.band.good'
    case 'fair': return 'ipt.band.fair'
    case 'poor': return 'ipt.band.poor'
    case 'critical': return 'ipt.band.critical'
    case 'few': return 'ipt.band.few'
    default: return 'ipt.band.few'
  }
}

/** 底色透明度：比 GIS 页的 0.13/0.09 高一档 */
export const COUNTY_FILL_OPACITY = { dark: 0.24, light: 0.18 } as const
