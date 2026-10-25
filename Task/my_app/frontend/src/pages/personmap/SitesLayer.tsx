/* 负责站点层（2026-10-24 从 PersonMapView 抽出，行数纪律）
 *
 * 画选中人员的**负责站点**圆点 + 悬停提示。站点集合口径
 * （2026-10-21 起 = `master_site_db.fme_name`，不再是「30 天窗口内 WO 涉及过的站」）
 * 由页面拉取后经 `sites` 传入，本组件只负责画。
 *
 * **三档取色由调用方以 `siteColor` 传入** —— 与「人员 → 站点」连线
 * （仍在 PersonMapView）共用同一个判定函数：2026-10-21 用户要求
 * 「连线颜色跟站点同色」，两处各写一套就会出现「线是绿的、点是蓝的」
 * 这种看着像 bug 的画面。优先级 红（实时告警）> 浅蓝（该人在此站有未关闭 WO）
 * > 绿（负责但当前没单）。
 * 「未清除」不再单独占一档颜色（用户的配色只有三色），改由**半径**表达：
 * 告警站 8px > 有未清除 7px > 其余 6px。
 */
import { CircleMarker, Tooltip as MapTooltip } from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import type { ManagedSite } from './types'

export function SitesLayer({
  sites, siteColor,
}: {
  sites: ManagedSite[]
  /** 站点 → 颜色（与选中连线共用同一个判定，见文件头） */
  siteColor: (s: ManagedSite) => string
}) {
  const { t } = useI18n()
  return (
    <>
      {sites.map(s => {
        const color = siteColor(s)
        return (
          <CircleMarker
            key={`site-${s.site_id}`}
            center={[s.lat, s.lng]}
            radius={s.has_alarm ? 8 : s.uncleared > 0 ? 7 : 6}
            color={color}
            fillColor={color}
            fillOpacity={0.75}
            weight={2}
          >
            <MapTooltip>
              <div style={{ minWidth: 160, fontSize: '0.75rem' }}>
                <div style={{ fontWeight: 700, marginBottom: 2 }}>{s.site_name || s.site_id}</div>
                <div>{t('person.siteId')}: {s.site_id}</div>
                <div>{t('person.county')}: {s.county || '—'}</div>
                <div>{t('person.colOpenWo')}: {s.wo_count}</div>
                <div>{t('person.colUncleared')}: {s.uncleared}</div>
                <div>{s.has_alarm ? t('person.siteHasAlarm') : t('person.siteNoAlarm')}</div>
              </div>
            </MapTooltip>
          </CircleMarker>
        )
      })}
    </>
  )
}
