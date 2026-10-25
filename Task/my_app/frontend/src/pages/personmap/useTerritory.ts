/* 「默认站点」辖区模式的状态与派生数据（2026-10-23，?page=person）
 *
 * 从 PersonMapView 抽出（该文件加县标签+辖区模式后逼近 800 行，超
 * AGENTS.md 三.2 的 500 行纪律）：本文件只管辖区模式的**数据侧** ——
 * 取数（/fme-territories）、配色分配、站点归属索引、站点悬停提示、
 * 以及「辖区模式下实际画针的人员集合」（pinPersons）。
 * 地图渲染（TerritoryLayer、人员针、开关浮层）仍在 PersonMapView。
 *
 * 需求背景见 PersonMapView「默认站点」段与手册 11a：用户要求
 * 「显示 master_site_db 里不同 person 的默认站点，person 放到这些站点
 * 的中间并连线；默认不显示，打开开关才显示」。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../../api'
import { cachedGet } from '../../cache'
import { useI18n } from '../../i18n'
import { escapeHtml } from '../gismap/personIcon'
import type { PersonRow, TerritoryPerson, TerritorySite, TerritoriesResp } from './types'

/** 辖区人员配色：24 人循环取色。
 *  ⚠ 刻意与 PersonMapView 的 COUNTY_PALETTE（县块色）**不同值** ——
 *  两套色在同一张图上（县块淡填充 + 辖区连线），共用色值会让人把
 *  「某人的辖区」读成「某个县」。 */
const TERRITORY_PALETTE = [
  '#3b82f6', '#f97316', '#10b981', '#ef4444', '#8b5cf6', '#b45309',
  '#ec4899', '#06b6d4', '#84cc16', '#64748b', '#6366f1', '#a16207',
] as const

export function useTerritory({ people, allPeople }: {
  /** 有登记坐标的人员（关着开关时的针集合） */
  people: PersonRow[]
  /** /personnel/stats 的全量人员行（辖区人员的 WO/PMT 统计从这里联合） */
  allPeople: PersonRow[]
}) {
  const { t } = useI18n()

  const [showTerritory, setShowTerritory] = useState(false)
  const [territory, setTerritory] = useState<TerritoryPerson[] | null>(null)
  const [terrLoading, setTerrLoading] = useState(false)

  /* 首次打开开关才拉（~130KB，24 人 824 站）；cachedGet 30s 内复用。 */
  useEffect(() => {
    if (!showTerritory || territory || terrLoading) return
    setTerrLoading(true)
    cachedGet('gis:personnel:fme-territories', () => api.get('/gis/personnel/fme-territories'))
      .then(res => setTerritory((res.data as TerritoriesResp).persons || []))
      .catch(err => {
        console.error('[useTerritory] fme-territories failed:', err?.response?.status, err?.response?.data || err)
        setTerritory([])
      })
      .finally(() => setTerrLoading(false))
  }, [showTerritory, territory, terrLoading])

  /** 人 → 辖区色：按 name_key 排序稳定分配（刷新/重开开关不变色）。 */
  const terrColorOf = useMemo(() => {
    const m = new Map<string, string>()
    const keys = (territory || []).map(tp => tp.name_key).sort()
    keys.forEach((k, i) => m.set(k, TERRITORY_PALETTE[i % TERRITORY_PALETTE.length]))
    return (key: string) => m.get(key) || '#7a8ba3'
  }, [territory])

  /** site_id → 负责人名列表（A/B 双人共担两个都列），站点悬停提示用。 */
  const terrSiteOwners = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const tp of territory || []) {
      for (const s of tp.sites) {
        const cur = m.get(s.site_id)
        if (cur) { if (!cur.includes(tp.name)) cur.push(tp.name) }
        else m.set(s.site_id, [tp.name])
      }
    }
    return m
  }, [territory])

  /** 站点悬停提示（HTML 字符串，拼前逐段 escapeHtml —— 值来自数据库）。 */
  const territorySiteTip = useCallback((s: TerritorySite, owners: string[]) => {
    return `<div style="min-width:150px;font-size:0.75rem">` +
      `<div style="font-weight:700;margin-bottom:2px">${escapeHtml(s.site_name || s.site_id)}</div>` +
      `<div>${escapeHtml(t('person.siteId'))}: ${escapeHtml(s.site_id)}</div>` +
      `<div>${escapeHtml(t('person.county'))}: ${escapeHtml(s.county || '—')}</div>` +
      (owners.length
        ? `<div>${escapeHtml(t('person.territoryOwners'))}: ${owners.map(escapeHtml).join(', ')}</div>`
        : '') +
      `</div>`
  }, [t])

  /* 实际画针的人员集合：
     · 关（默认）= `people`（person 表登记坐标）；
     · 开 = 辖区人员（针在质心，含**无登记坐标**的人 —— 这类人平时根本不上图）
       + 有登记坐标但不在 fme_name 里的人（supervisor 等，保留原位、无连线）。
     统计（WO/PMT）从 `allPeople` 按 name_key 联合；联合不到的标 stats_unknown，
     徽标显示 `—`（不冒充 0，AGENTS.md 三.6）。 */
  const pinPersons = useMemo<PersonRow[]>(() => {
    if (!showTerritory || !territory?.length) return people
    const terrKeys = new Set(territory.map(tp => tp.name_key))
    const merged: PersonRow[] = territory.map(tp => {
      const row = allPeople.find(r => r.name_key === tp.name_key)
      if (row) {
        return {
          ...row,
          lat: tp.centroid.lat,
          lng: tp.centroid.lng,
          phone: tp.phone || row.phone,
          site_count: tp.sites.length,
        }
      }
      return {
        name: tp.name, name_key: tp.name_key, has_coords: false,
        lat: tp.centroid.lat, lng: tp.centroid.lng, phone: tp.phone,
        managed_regions: '', open: 0, closed: 0, total: 0, uncleared: 0,
        tt_open: 0, tt_closed: 0, tt_total: 0, counties: [],
        site_count: tp.sites.length, supervised_sites: 0, pmt_open: null,
        stats_unknown: true,
      }
    })
    merged.push(...people.filter(p => !terrKeys.has(p.name_key)))
    return merged
  }, [showTerritory, territory, people, allPeople])

  return {
    showTerritory, setShowTerritory, territory, terrLoading,
    terrColorOf, terrSiteOwners, territorySiteTip, pinPersons,
  }
}
