/* 人员针的图标 HTML 与图标键（2026-10-24 从 PersonMapView 抽出）
 *
 * 抽出资因：PersonMapView 加县名标签（10-23）+「默认站点」辖区模式（10-24）后
 * 714 行，超 AGENTS.md 三.2 的 500 行纪律。本文件只负责「一个人员针长什么样」：
 * 颜色/尺寸推导、常驻徽标 HTML、iconKey。Marker 的挂载、pane 与点击事件
 * 仍在 PersonMapView。
 *
 * ⚠⚠ 悬停态**绝不能**进图标（2026-10-21 实测，勿改回去）：
 *     以前 `hovered` 被拼进 `iconKey` / `html` / 尺寸，于是鼠标一进针，
 *     `Marker` 的 `useMemo([parent, iconKey])` 就**重建整个 L.Marker 图层**、
 *     把针的 DOM 元素换掉。无头浏览器抓到的真实时间线：
 *         13880 mousedown <path>            （按下，命中人员针）
 *         13883 mouseout   <path>           （悬停态复位 → 触发重建）
 *         13896 DEL / ADD marker-icon       （DOM 元素被换掉）
 *         13987 mouseup <DIV .leaflet-container>
 *     mousedown 与 mouseup 落在不同元素上，浏览器**根本不产生 click 事件**，
 *     Leaflet 收不到 marker click —— 这就是「点人没反应 / 抽屉闪一下就没」
 *     的直接原因。悬停现在纯 CSS 实现（`.gis-person-marker:hover`），
 *     不动 DOM；`selected` 才重建，而它只在一次点击**完成之后**变化。
 */
import { escapeHtml, personIconSvg } from '../gismap/personIcon'
import { SITE_COLORS } from '../gismap/types'
import type { PersonRow } from './types'

/** i18n 的 `t`（只用 person.* 键）。签名与 i18n.tsx 的 I18nContextType.t 一致。 */
type TFunc = (key: string, params?: Record<string, string | number>) => string

/** 一个人员针的图标三件套（PersonMapView 原样透传给 Marker）。 */
export interface PersonPinIcon {
  html: string
  iconSize: [number, number]
  iconAnchor: [number, number]
  /** ⚠ 不含 hover —— 见文件头。含 selected 是安全的：它只在点击完成后变化。 */
  iconKey: string
}

export function buildPersonPin(
  p: PersonRow, selected: boolean, isDark: boolean, t: TFunc,
): PersonPinIcon {
  /* 统计取不到（辖区人员不在 /personnel/stats 里，实测仅 1 人）：
     徽标数字显示 — 、针用中性灰 —— 不能拿 0 冒充（AGENTS.md 三.6）。 */
  const unknown = !!p.stats_unknown
  /* 颜色（2026-10-19 用户要求「WO 为 0 的人显示深绿以区别」）：
     选中红 > 统计未知灰 > 未关闭 WO 为 0 深绿 > 其余蓝。
     深绿只用于**未选中**的大多数人 —— 选中必须仍是红，
     否则用户点了一个「没单的人」时看不出选中态。 */
  const color = selected ? SITE_COLORS.rt_alarm_overdue
    : unknown ? '#8c93a8'
    : (p.open || 0) === 0 ? '#1a7f37'
    : (isDark ? '#4fc3f7' : '#1890ff')
  const size = selected ? 32 : 26
  const iconH = size * 1.5
  const phone = (p.phone || '').trim()
  // 常驻徽标已含姓名+电话，悬停气泡不再重复渲染同样的内容 ——
  // 只在常驻徽标之外没有信息时（即无）保留为空，避免两层气泡叠在一起。
  const tip = ''
  const openCnt = p.open || 0
  const sitesCnt = p.site_count || 0
  const pmtCnt = p.pmt_open
  // null = 后端取不到 eflow_pm → 显示 —（不得显示 0，AGENTS.md 三.6）
  const pmtText = pmtCnt == null ? '—' : String(pmtCnt)
  const openText = unknown ? '—' : String(openCnt)
  const unclearedCnt = p.uncleared || 0
  // 有未清除告警 → 红；否则灰。文字与边框共用同一个色，见 .gis-person-badge
  const badgeColor = unclearedCnt > 0 ? '#ff4d4f' : '#8c8c8c'
  const html =
    `<div class="gis-person-anchor">` +
      tip +
      personIconSvg(color, size, selected) +
      /* 常驻徽标（2026-10-19 用户要求，2026-10-21 加 PMT 一项）：
           第一行 = 姓名 + 电话；
           第二行 = 负责站点数 | 未关闭 WO 数 | 未关闭 PMT 数。
         三项的顺序是用户 2026-10-21 指定的。
         ⚠ PMT 那一项**不跟随页面 30 天窗口**（是「此刻还没关闭」的状态数），
         与旁边两项口径不同 —— 后端 personnel.py::_pmt_open_index 有完整理由，
         页面 ⓘ 说明里也必须讲清楚，否则用户会拿它跟 WO 那列做加减。
         徽标内容全部来自后端，拼进 html 前必须 escapeHtml（AGENTS.md 三.4）。 */
      `<span class="gis-person-badge" style="border-color:${badgeColor}" ` +
        `title="${escapeHtml(t('person.badgeHint', {
          name: p.name, phone: phone || '-',
          sites: sitesCnt, open: openText, pmt: pmtText, uncleared: unclearedCnt,
        }))}">` +
        `<span class="gis-person-badge-name">${escapeHtml(p.name)}` +
          (phone ? `<i>${escapeHtml(phone)}</i>` : '') +
        `</span>` +
        `<span class="gis-person-badge-stats" style="color:${badgeColor}">` +
          `<b>${sitesCnt}</b>${escapeHtml(t('person.badgeSitesShort'))}` +
          `<em>|</em>` +
          `<b>${openText}</b>${escapeHtml(t('person.badgeOpenShort'))}` +
          `<em>|</em>` +
          `<b>${pmtText}</b>${escapeHtml(t('person.badgePmtShort'))}` +
        `</span>` +
      `</span>` +
    `</div>`
  const iconKey = `${selected}-${size}-${unclearedCnt}-${openText}-${sitesCnt}-${pmtText}-${p.name}-${phone}-${p.lat},${p.lng}`
  return { html, iconSize: [size, iconH], iconAnchor: [size / 2, iconH], iconKey }
}
