/* 地图搜索框（?page=person，2026-10-19 新增）
 *
 * **需求**（用户原话）：「地图要添加搜索站点和人员的功能」。
 * 用户选定的交互：浮在地图左上角；同时搜人员与站点；选中站点时
 * **定位并选中该站点的负责人**（若该站点有负责人）。
 *
 * **数据来源分两路**（用户确认「两者都要（分场景）」）：
 *   · 人员 —— 直接用页面已加载的 `people`（不必再请求后端）；
 *   · 站点 —— 调 `/gis/sites/search` 搜全量 824 个站点。
 *     有选中人员时，其名下站点也并入结果且排在前面（相关性更高），
 *     「分场景」即体现在这里：不限制搜索范围，只影响排序与标注。
 *
 * **为什么单独成文件**：PersonMapView 已负责地图图层渲染，把搜索 UI 与
 * 防抖/请求逻辑塞进去会偏离「一个文件一件事」的约定（AGENTS.md 三.2）。
 * 本组件只产出「用户选了谁/哪个站点」这个事件，不碰地图实例 ——
 * 飞行定位由调用方（PersonMapView）用 MapController 完成。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { AutoComplete, Input, Tag } from 'antd'
import { SearchOutlined, UserOutlined, EnvironmentOutlined } from '@ant-design/icons'
import api from '../../api'
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import type { PersonRow, ManagedSite } from './types'

/** 搜索结果（统一样式）。`kind` 决定点击后走哪条路径。 */
export type SearchHit =
  | { kind: 'person'; key: string; label: string; sub: string; person: PersonRow }
  | { kind: 'site'; key: string; label: string; sub: string; site: ManagedSite; ownerKeys: string[] }

/** 搜索关键字防抖（毫秒）。太短会在每次击键都打后端，太长显得卡。 */
const DEBOUNCE_MS = 250

interface SiteSearchResp {
  sites: (ManagedSite & { owner_count: number })[]
  total: number
}

export function MapSearch({
  people, selectedKey, sites, onPickPerson, onPickSite,
}: {
  people: PersonRow[]
  selectedKey: string | null
  /** 当前选中人员的站点（并入搜索结果，排前） */
  sites: ManagedSite[]
  onPickPerson: (nameKey: string) => void
  onPickSite: (site: ManagedSite) => void
}) {
  const { t } = useI18n()
  const [kw, setKw] = useState('')
  const [remote, setRemote] = useState<(ManagedSite & { owner_count: number })[]>([])
  const [loading, setLoading] = useState(false)
  /* 请求序号：只接受**最后一次**请求的响应。
     快速输入时先发的请求可能后到，不加守卫会把旧结果盖在新关键字上
     （与 PersonnelLayer 的 hoverKey 守卫同一类问题）。 */
  const seqRef = useRef(0)

  // 站点搜索（防抖）
  useEffect(() => {
    const q = kw.trim()
    if (!q) { setRemote([]); setLoading(false); return }
    const my = ++seqRef.current
    setLoading(true)
    const timer = setTimeout(() => {
      api.get('/gis/sites/search', { params: { q, limit: 20 } })
        .then(res => {
          if (seqRef.current !== my) return          // 陈旧响应，丢弃
          setRemote((res.data as SiteSearchResp).sites || [])
        })
        .catch(err => {
          console.error('[MapSearch] sites search failed:', err?.response?.status, err?.response?.data || err)
          if (seqRef.current === my) setRemote([])
        })
        .finally(() => { if (seqRef.current === my) setLoading(false) })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [kw])

  /* 合并结果：人员在本地过滤（26 条，无需请求）；站点先用后端结果，
     再把「当前选中人员的站点」里命中的项提到前面去重。 */
  const options = useMemo(() => {
    const q = kw.trim().toLowerCase()
    if (!q) return []

    const personHits: SearchHit[] = people
      .filter(p => p.name.toLowerCase().includes(q) || (p.phone || '').includes(q))
      .slice(0, 8)
      .map(p => ({
        kind: 'person' as const,
        key: `p:${p.name_key}`,
        label: p.name,
        sub: t('person.searchPersonSub', { open: p.open, sites: p.site_count }),
        person: p,
      }))

    // 选中人员名下的站点，命中的放最前
    const ownedHits: SearchHit[] = sites
      .filter(s => s.site_id.includes(q) || s.site_name.toLowerCase().includes(q))
      .slice(0, 8)
      .map(s => ({
        kind: 'site' as const,
        key: `s:${s.site_id}`,
        label: `${s.site_name || s.site_id}`,
        sub: t('person.searchSiteOwned', { id: s.site_id, county: s.county || '-' }),
        site: s,
        ownerKeys: selectedKey ? [selectedKey] : [],
      }))

    const seen = new Set(ownedHits.map(h => (h as any).site.site_id))
    const siteHits: SearchHit[] = remote
      .filter(s => !seen.has(s.site_id))
      .slice(0, 12)
      .map(s => ({
        kind: 'site' as const,
        key: `s:${s.site_id}`,
        label: `${s.site_name || s.site_id}`,
        sub: s.owner_count > 0
          ? t('person.searchSiteWithOwner', { id: s.site_id, county: s.county || '-', n: s.owner_count })
          : t('person.searchSiteNoOwner', { id: s.site_id, county: s.county || '-' }),
        site: s,
        // 后端只给「有几位负责人」的计数，不给具体是谁；前端在已加载的
        // people 里无法可靠反查，故 ownerKeys 留空 —— 见 onSelect 的降级说明。
        ownerKeys: [] as string[],
      }))

    return [...personHits, ...ownedHits, ...siteHits]
  }, [kw, people, remote, sites, selectedKey, t])

  const handleSelect = (_: string, opt: any) => {
    const hit = opt.hit as SearchHit
    if (hit.kind === 'person') onPickPerson(hit.person.name_key)
    else onPickSite(hit.site)
    // 选完清空输入，避免悬浮框继续遮住地图
    setKw('')
  }

  return (
    <div style={{
      /* left 56 而不是 12：Leaflet 默认缩放条在**同一个左上角**（容器相对 x 10..44、
         y 10..74，实测 34×64px），原先 left:12/top:12 的搜索框正好压在「+」上
         （两个元素的 y 区间 123..147 完全重叠）—— 用户报「搜索窗挡住了地图+号」。
         留 12px 间隙取 56；宽度同步扣掉左侧多占的 44px，右侧仍留 12px 不贴边。
         不动缩放条位置：`zoomControl: true` 在 components/LeafletMap.tsx 的共享
         MapContainer 上，改它会波及全站所有地图，而搜索框只有本页在用。 */
      position: 'absolute', left: 56, top: 12, zIndex: 1000,
      width: 'min(320px, calc(100% - 68px))',
    }}>
      <AutoComplete
        value={kw}
        onChange={setKw}
        onSelect={handleSelect}
        options={options.map(h => ({
          value: h.key,
          label: (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              {h.kind === 'person'
                ? <UserOutlined style={{ color: WH.teal, flexShrink: 0 }} />
                : <EnvironmentOutlined style={{ color: WH.blue, flexShrink: 0 }} />}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {h.label}
              </span>
              <Tag style={{ marginLeft: 'auto', fontSize: '0.625rem', flexShrink: 0 }}>{h.sub}</Tag>
            </div>
          ),
          hit: h,
        }))}
        style={{ width: '100%' }}
        notFoundContent={kw.trim() && !loading ? t('person.searchNoResult') : null}
      >
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('person.searchPlaceholder2')}
          allowClear
          size="small"
          style={{ background: 'var(--wh-card-bg)', backdropFilter: 'blur(6px)' }}
        />
      </AutoComplete>
    </div>
  )
}
