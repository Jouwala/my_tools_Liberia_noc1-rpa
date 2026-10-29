/* 按类别筛选后画到地图上的站点层（2026-10-28，?page=person）
 *
 * 与 `SitesLayer.tsx` 的区别（两者都在图上，别混）：
 *   · `SitesLayer`    = **选中人员负责的站点**，按「告警 / 有未关闭 WO / 无单」
 *     三档着色，是人员下钻的附属信息；
 *   · `SiteClassLayer` = **按数据库类别（维护分类 / VIP / HUB / 传输类型）
 *     筛选出来的站点**，由左下角图例控制，默认一个都不画。
 *
 * **取色**：由调用方以 `colorOf` 传入（取第一个激活分组的类别色），保证
 * 同一批站点在同一次筛选下颜色一致 —— 见 `useSiteClasses.ts` 文件头。
 */
import { CircleMarker, Tooltip as MapTooltip } from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import type { SiteClassSite } from './types'

export function SiteClassLayer({
  sites, colorOf, labelOf, isDark,
}: {
  /** 已按图例选中项过滤好的站点集合（没选任何项时为空数组） */
  sites: SiteClassSite[]
  /** 站点 → 颜色（与图例色块同源） */
  colorOf: (s: SiteClassSite) => string
  /** 分组取值 → 展示文案 */
  labelOf: (group: string, value: string) => string
  isDark: boolean
}) {
  const { t } = useI18n()
  if (!sites.length) return null
  return (
    <>
      {sites.map(s => {
        const color = colorOf(s)
        const cls = s.classes || {}
        return (
          /* `person-class-site`：专属类，供自动化脚本统计「图例筛出来的点」
             （overlay-pane 里还混着县界多边形与负责站点圆点，靠 fill-opacity
             区分太脆弱）。 */
          <CircleMarker
            key={`cls-${s.site_id}`}
            center={[s.lat, s.lng]}
            className="person-class-site"
            radius={5}
            color={isDark ? '#ffffff' : '#334155'}
            weight={1}
            fillColor={color}
            fillOpacity={0.85}
          >
            <MapTooltip>
              <div style={{ minWidth: 170, fontSize: '0.75rem' }}>
                <div style={{ fontWeight: 700, marginBottom: 2 }}>{s.site_name || s.site_id}</div>
                <div>{t('person.siteId')}: {s.site_id}</div>
                <div>{t('person.county')}: {s.county || '—'}</div>
                <div>{t('person.legend.group.site_caregory')}: {labelOf('site_caregory', cls.site_caregory || '')}</div>
                <div>{t('person.legend.group.vip_site')}: {labelOf('vip_site', cls.vip_site || '')}</div>
                <div>{t('person.legend.group.hub_site')}: {labelOf('hub_site', cls.hub_site || '')}</div>
                <div>{t('person.legend.group.trm_type')}: {labelOf('trm_type', cls.trm_type || '')}</div>
              </div>
            </MapTooltip>
          </CircleMarker>
        )
      })}
    </>
  )
}
