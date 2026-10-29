/* 「站点类别图例」的取数与派生（2026-10-28，?page=person）
 *
 * **需求**（用户原话）：「添加图例，按照数据库的站点类型如 COOLI/ERA/NORMAL
 * 显示站点。默认不显示，当用户点击的时候在地图上显示。同样的，添加
 * vip_site/hub_site/trm_type」。
 *
 * **本文件只管数据**：取数（/gis/personnel/site-classes）+ 选中态 +
 * 「按选中项过滤出要显示的站点」。渲染在图例面板（SiteClassLegend.tsx）
 * 与地图图层（SiteClassLayer.tsx）。
 *
 * **默认不显示**：`selected` 初值是空对象 —— 一项都没选中时 `visibleSites`
 * 为空数组，地图上一个类别站点都不画（与用户需求一致）。
 *
 * **过滤语义**（与 GIS 页多列筛选 `_build_filter_where` 同思路）：
 *   · 同一分组内多选 = **并集**（OR）；
 *   · 不同分组之间 = **交集**（AND）。
 * 例：选了 COOL + ERA（同组）→ 显示这两类的 265 站；再选 VIP=Y（另一组）
 *     → 只显示「(COOL 或 ERA) 且是 VIP」的站。
 *
 * **着色**：取**第一个**激活分组的类别色。`activeGroups` 的次序由
 * `_SITE_CLASS_GROUPS` 的固定分组顺序决定（与选中先后无关），
 * 故同一批站点的配色不会因为点击顺序不同而变。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../../api'
import { cachedGet } from '../../cache'
import { numLocale, useI18n } from '../../i18n'
import { siteClassColor } from './siteClassColors'
import type { SiteClassGroup, SiteClassSite, SiteClassesResp } from './types'

/** 缓存键 —— 与 GIS 页其它 personnel 端点同风格（前缀 `gis:personnel:`） */
const CACHE_KEY = 'gis:personnel:site-classes'

export function useSiteClasses() {
  const { t, locale } = useI18n()
  const [groups, setGroups] = useState<SiteClassGroup[]>([])
  const [sites, setSites] = useState<SiteClassSite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  /** 选中项：分组键 → 值集合。默认**不显示任何站点**（用户需求）。 */
  const [selected, setSelected] = useState<Record<string, string[]>>({})

  /* 挂载即拉：图例上要显示每类的站点数（「COOL 64」），没有数据就只能空着。
     824 行精简字段约 100KB，cachedGet 缓存 30s，切页签回来不会重复下载。 */
  useEffect(() => {
    let alive = true
    setLoading(true)
    cachedGet<SiteClassesResp>(CACHE_KEY, () => api.get('/gis/personnel/site-classes'))
      .then(res => {
        if (!alive) return
        setGroups(res.data?.groups || [])
        setSites(res.data?.sites || [])
        setError('')
      })
      .catch(err => {
        console.error('[useSiteClasses] failed:', err?.response?.status, err?.response?.data || err)
        if (!alive) return
        setGroups([])
        setSites([])
        setError(err?.response?.data?.detail || err?.message || String(err))
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  /** 点击某个类别 → 切换选中。整组清空时把分组键一起删掉，
   *  免得留下 `{ trm_type: [] }` 这种"有分组但没选值"的僵尸状态。 */
  const toggle = useCallback((group: string, value: string) => {
    setSelected(prev => {
      const cur = prev[group] || []
      const next = cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value]
      const out = { ...prev }
      if (next.length) out[group] = next
      else delete out[group]
      return out
    })
  }, [])

  const clear = useCallback(() => setSelected({}), [])

  /** 至少选中一项的分组（按 `groups` 的顺序，保证着色稳定） */
  const activeGroups = useMemo(() => {
    const order = groups.map(g => g.key)
    return order.filter(k => (selected[k] || []).length > 0)
  }, [groups, selected])

  /** 组内 OR、组间 AND → 要画在地图上的站点。没选任何项 = 空（默认不显示）。 */
  const visibleSites = useMemo(() => {
    if (!activeGroups.length) return []
    return sites.filter(s => activeGroups.every(g => {
      const picked = selected[g] || []
      return picked.includes(s.classes?.[g] ?? '')
    }))
  }, [sites, selected, activeGroups])

  /** 站点圆点的颜色：取第一个激活分组的类别色。 */
  const colorOf = useCallback((s: SiteClassSite) => {
    const g = activeGroups[0]
    return g ? siteClassColor(g, s.classes?.[g] ?? '') : '#8b93a1'
  }, [activeGroups])

  /* 值的展示文案：Y/N 译成本地化的是/否，空串译「未填」，
     其余（COOL / ERA / NORMAL / MW / …）用数据库原值 ——
     这些是业务编码，翻译了反而对不上上游系统。 */
  const labelOf = useCallback((group: string, value: string) => {
    if (!value) return t('person.legend.unknown')
    if (group === 'vip_site' || group === 'hub_site') {
      return value === 'Y' ? t('common.yes') : t('common.no')
    }
    return value
  }, [t])

  const nf = (n: number) => n.toLocaleString(numLocale(locale))

  return {
    groups, loading, error,
    selected, toggle, clear,
    activeGroups, visibleSites, colorOf, labelOf, total: sites.length, nf,
  }
}
