/* 人员页地图的**站点取色与分档**（2026-10-30，与实时告警页对齐）
 *
 * ===== 为什么有这个文件 =====
 * 改造前（2026-10-30 之前）人员页有**自己一套**站点配色：
 *   绿 = 负责但当前没单 / 浅蓝 = 该人在此站有未关闭 WO / 红 = 该站有实时告警
 * 而 `?page=realtime_alarm` 用的是另一套（深红超时 / 橙未超时 / 蓝 TT /
 * 青 WO / 紫 VIP / 灰无状态）。两页看的是**同一批站点、同一个
 * `realtime_alarm` 快照**，颜色却对不上 —— 用户报「人员页没有用实时告警页的
 * 点显色样式」。
 *
 * 现改为：**色值**取自 `gismap/types.ts` 的 `LEGEND_COLORS`（两页同一份，
 * 改一处两页同时生效）；**分档判定**在本文件（人员页有自己的 WO 语义，
 * 不能照抄实时告警页，见下方优先级说明）。
 *
 * ===== 分档优先级（2026-10-30 用户确认：WO 优先）=====
 *   1. 超时告警   深红  rt_alarm_overdue
 *   2. 该人有未关闭 WO 青  wo        ← 人员页自己的语义（实时告警页没有这档）
 *   3. 该站有告警 TT   蓝  tt
 *   4. 未超时告警     橙  rt_alarm_ontime
 *   5. VIP 站         紫  vip
 *   6. 无状态         灰  normal
 *
 * 与实时告警页的差别只有一处：实时告警页是
 *   超时 > 该站有告警WO > 该站有告警TT > 未超时 > VIP > 无状态
 * 即第 2 档用的是「**该站**由告警关联到的 WO 数」，人员页用的是
 * 「**该人员**在此站的未关闭 WO 数」。后者是「谁的手上有单」，
 * 人员页必须保留自己的语义（用户 2026-10-30 明确选择「用该人员在此站的
 * 未关闭 WO 数」）。两者都不改变「告警优先于工单」的大方向。
 *
 * ⚠ 值必须是**十六进制实值**：Leaflet 的 CircleMarker / Polyline 走 SVG
 *   呈现属性，解析不了 `var(--wh-*)`（与 ECharts 同一约束，AGENTS.md 三.3）。
 */
import { colorFor } from '../gismap/types'
import type { ManagedSite } from './types'

/** 站点分档键。与 `gismap/types.ts` 的 `LegendKey` 同名同义，
 *  便于图例直接复用 `gis.legend.*` 那套文案与色值。 */
export type PersonSiteCategory =
  | 'rt_alarm_overdue'
  | 'wo'
  | 'tt'
  | 'rt_alarm_ontime'
  | 'vip'
  | 'normal'

/** 该站是否算 VIP（与实时告警页同一判定：`vip_site` 列取值 Y / Yes）。 */
export function isVipSite(s: ManagedSite): boolean {
  return s.vip_site === 'Y' || s.vip_site === 'Yes'
}

/**
 * 站点 → 分档。**每站恰好一个档**，与地图上画出来的颜色严格一一对应
 * （图例数字必须等于图上点数，AGENTS.md 三.1b）。
 *
 * ⚠ 「该人有未关闭 WO」这一档刻意**排在告警超时之后、告警 TT 之前**：
 *   未超时告警档（橙）与 WO 档（青）在图例里属于不同语义族
 *   （告警族 vs 工单族），若 WO 排在未超时之前，则「有未超时告警但该人
 *   也有未关闭 WO」的站会被涂成青色 —— 告警被工单色盖住，正是实时告警页
 *   在 2026-10-17 修过的问题（「29 个有超时告警的站点全部同时带 TT，
 *   于是全被涂成蓝色，地图上一个红点也没有」）。故告警档（超时/未超时）
 *   整体优先于工单档，只是「超时」还额外压过人员页自己的 WO 档。
 */
export function siteCategory(s: ManagedSite): PersonSiteCategory {
  // ① 超时告警：SLA 已破，最高优先级
  if ((s.rt_alarm_overdue || 0) > 0) return 'rt_alarm_overdue'
  // ② 该人员在此站有未关闭 WO（人员页自己的语义）
  if ((s.wo_count || 0) > 0) return 'wo'
  // ③ 该站的实时告警关联到 TT
  if ((s.rt_tt_count || 0) > 0) return 'tt'
  // ④ 未超时告警
  if ((s.rt_alarm_count || 0) > 0) return 'rt_alarm_ontime'
  // ⑤ VIP 站
  if (isVipSite(s)) return 'vip'
  // ⑥ 无任何状态
  return 'normal'
}

/** 站点 → 颜色。与实时告警页同一份色表（`LEGEND_COLORS`）。 */
export function siteColor(s: ManagedSite): string {
  return colorFor(siteCategory(s))
}

/**
 * 站点 → 圆点半径。
 *
 * ⚠ 半径语义与实时告警页**一致**：数字越大 = 越紧急 / 越需要关注。
 * 实时告警页的口径是「按关联 TT / WO 的条数分档」
 * （`GISMap.tsx::getMarkerRadius` 的 realtime 分支：TT>5→9、TT>0→7、
 * WO>5→8、WO>0→6、有实时告警→10、其余→4）。
 * 人员页沿用**同一套数字与同一套字段**（`rt_tt_count` / `rt_wo_count` /
 * `rt_alarm_count`），这样两页的圆点大小可以直接横向比较。
 *
 * 旧人员页的 8/7/6 是「告警 > 有未清除 > 其余」的**另一套**语义
 * （且不反映条数），与实时告警页不可比，故一并改掉。
 *
 * 末尾多一档 `wo_count > 0 → 6`：这是**人员页独有**的量（该人自己手上有单），
 * 实时告警页没有对应概念（它的 WO 档是「该站由告警关联到的 WO」，
 * 已由上面的 `rt_wo_count` 覆盖）。取 6 = 与实时告警页「有 WO」同档。
 */
export function siteRadius(s: ManagedSite): number {
  const tt = s.rt_tt_count || 0
  const wo = s.rt_wo_count || 0
  if (tt > 5) return 9
  if (tt > 0) return 7
  if (wo > 5) return 8
  if (wo > 0) return 6
  if ((s.rt_alarm_count || 0) > 0) return 10
  if ((s.wo_count || 0) > 0) return 6
  return 4
}
