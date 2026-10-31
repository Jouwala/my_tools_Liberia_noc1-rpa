/* 负责站点层（2026-10-24 从 PersonMapView 抽出，行数纪律）
 *
 * 画选中人员的**负责站点**圆点 + 悬停提示。站点集合口径
 * （2026-10-21 起 = `master_site_db.fme_name`，不再是「30 天窗口内 WO 涉及过的站」）
 * 由页面拉取后经 `sites` 传入，本组件只负责画。
 *
 * **取色与半径全部由 `personmap/siteTone.ts` 决定**（2026-10-30 对齐改造）：
 *   · 色值取自 `gismap/types.ts` 的 `LEGEND_COLORS` —— 与 `?page=realtime_alarm`
 *     **同一份**真相源（深红超时 / 橙未超时 / 蓝 TT / 青 WO / 紫 VIP / 灰无状态）；
 *   · 分档判定在 `siteTone.ts::siteCategory`，与「人员 → 站点」连线
 *     （仍在 PersonMapView）**共用同一个函数** —— 用户 2026-10-21 要求
 *     「连线颜色跟站点同色」，两处各写一套就会出现「线是绿的、点是蓝的」
 *     这种看着像 bug 的画面。
 *
 * ⚠ 描边色**不再与填充同色**：改造前 `color={color}`（描边 = 填充），
 *   圆点在瓦片上糊成一团、没有轮廓。实时告警页的做法是按主题反着挑
 *   （浅色底用白边、深色底用近黑边），此处照搬 —— 描边的作用是把圆点
 *   从底图上「抠出来」，抠不出来就等于没有描边。
 *
 * ===== 与实时告警页的逐项对齐（2026-10-30）=====
 *   · pane 走 `sitePane`（z-index 650）—— 实时告警页的站点圆点也是这个 pane，
 *     目的是压在县块填充（overlay 400）之上。人员页原先用默认 overlayPane(400)，
 *     圆点与县块同层，谁后画谁在上 → 圆点可能被县块盖住。两页现已一致。
 *   · `fillOpacity` 改 1（原 0.85）—— 实时告警页是 1；半透明会让底图透过来，
 *     站点色与图例色对不上（AGENTS.md 三.1b：图例色必须等于点色）。
 *   · **超时告警档额外套一圈呼吸光环**（`gis-halo`，与实时告警页同一套 CSS
 *     动画）：实时告警页对 `rt_alarm_overdue` 档在圆点外再叠一圈只描边、
 *     不填充的圆，由 CSS 做 1.8s 呼吸动画。这是「最紧急档」独有的视觉信号，
 *     人员页原先完全没有 —— 用户报「没有用实时告警页的点显色样式」时，
 *     这一项也是差异之一。
 */
import { Fragment } from 'react'
import { CircleMarker, Tooltip as MapTooltip } from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import { siteColor, siteRadius, siteCategory } from './siteTone'
import { SITE_COLORS } from '../gismap/types'
import type { ManagedSite } from './types'

/** 站点圆点所在 pane。与 `GISMap.tsx` 的 sitePane 同名同层级（650），
 *  高于 overlayPane(400) 的县块填充。 */
export const PERSON_SITE_PANE = 'sitePane'

export function SitesLayer({
  sites, isDark,
}: {
  sites: ManagedSite[]
  /** 深浅主题（决定圆点描边色，理由见文件头） */
  isDark: boolean
}) {
  const { t } = useI18n()
  /* 描边色：浅色底 → 白边（凸起感）；深色底 → 近黑边（暗底上最清晰）。
     ⚠ 必须是 rgba 实值：这里最终传给 Leaflet 的 SVG CircleMarker，
     SVG 解析不了 CSS 变量（与 gismap/types.ts 的 SITE_COLORS 同一约束）。 */
  const markerStroke = isDark ? 'rgba(0,0,0,0.55)' : '#ffffff'
  return (
    <>
      {sites.map(s => {
        const color = siteColor(s)
        const radius = siteRadius(s)
        const isOverdue = siteCategory(s) === 'rt_alarm_overdue'
        return (
          <Fragment key={`site-${s.site_id}`}>
            {/* 超时档的呼吸光环（与实时告警页同一实现：`gis-halo` CSS 动画）。
                只对这一档开 —— 它是最高优先级（已超时 SLA）且数量最少；
                若对所有档都开，几十个 SVG 圆同时动画会拖垮地图。 */}
            {isOverdue && (
              <CircleMarker
                pane={PERSON_SITE_PANE}
                center={[s.lat, s.lng]}
                radius={radius + 4}
                fillColor="transparent"
                color={SITE_COLORS.rt_alarm_overdue}
                weight={2}
                opacity={1}
                fillOpacity={0}
                className="gis-halo"
              />
            )}
            <CircleMarker
              pane={PERSON_SITE_PANE}
              center={[s.lat, s.lng]}
              radius={radius}
              color={markerStroke}
              fillColor={color}
              fillOpacity={1}
              weight={1.5}
            >
              <MapTooltip>
                <div style={{ minWidth: 160, fontSize: '0.75rem' }}>
                  <div style={{ fontWeight: 700, marginBottom: 2 }}>{s.site_name || s.site_id}</div>
                  <div>{t('person.siteId')}: {s.site_id}</div>
                  <div>{t('person.county')}: {s.county || '—'}</div>
                  {/* 与实时告警页的站点弹窗对齐（2026-10-30）：同一个站点的
                      弹窗在两页应给出**同一组实时指标** —— 区域、类型/网络类型、
                      实时告警条数及其超时/未超时拆分、该站由告警关联到的 TT / WO。
                      之前人员页只有 WO 口径，
                      用户在两页看到同一个站却读到不同的数字。
                      文案复用 `gis.popup.*` 那套（两页同一种说法）。 */}
                  <div>{t('gis.popup.region')}: {s.region || '—'}</div>
                  <div>
                    {t('gis.popup.type')}: {s.site_type || '—'} | {s.network_type || '—'}
                  </div>
                  {(s.rt_alarm_count || 0) > 0 && (
                    <span style={{ fontWeight: 600 }}>
                      ⚠ {t('gis.popup.rtAlarm')}: {s.rt_alarm_count}
                      {(s.rt_alarm_overdue || 0) > 0 && (
                        <span style={{ color: SITE_COLORS.rt_alarm_overdue }}>
                          {' '}({t('gis.popup.overdue')}: {s.rt_alarm_overdue})
                        </span>
                      )}
                      {(s.rt_alarm_ontime || 0) > 0 && (
                        <span style={{ color: SITE_COLORS.rt_alarm_ontime }}>
                          {' '}({t('gis.popup.ontime')}: {s.rt_alarm_ontime})
                        </span>
                      )}
                    </span>
                  )}
                  {/* 该站**由实时告警关联到**的 TT / WO（与实时告警页同口径同字段） */}
                  <div>{t('gis.popup.tt')}: {s.rt_tt_count || 0}</div>
                  <div>{t('gis.popup.wo')}: {s.rt_wo_count || 0}</div>
                  {/* 人员页自有口径：该**人员**在此站的未关闭 / 未清除工单数 */}
                  <div>{t('person.colOpenWo')}: {s.wo_count}</div>
                  <div>{t('person.colUncleared')}: {s.uncleared}</div>
                </div>
              </MapTooltip>
            </CircleMarker>
          </Fragment>
        )
      })}
    </>
  )
}
