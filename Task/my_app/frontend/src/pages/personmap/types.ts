/* 人员位置地图（?page=person）的类型定义
 *
 * 与后端 `backend/routers/personnel.py` 的 `/personnel/stats` 与
 * `/personnel/{key}/managed-sites` 响应结构一一对应。
 * 改后端响应时必须同步改这里（两处都写注释互相指认）。
 */

/** 一个人的聚合行。`by_person` / `top_person` 的元素。
 *  注意 `has_coords=false` 的人是「名下有 WO 但 person 表没有坐标」，
 *  页面要列出来（否则统计总和对不上），但不画在地图上。 */
export interface PersonRow {
  name: string
  name_key: string
  has_coords: boolean
  lat: number | null
  lng: number | null
  phone: string
  /** person 表原值（县名，';' 分隔）—— 仅文本展示，不用于地图 */
  managed_regions: string
  /** 未关闭 WO */
  open: number
  /** 已关闭 WO */
  closed: number
  /** 全部 WO */
  total: number
  /** 未清除告警的 WO（与 GIS 人员图层同口径） */
  uncleared: number
  /** 带 tt_no 的 WO 行数（按行计，非独立 TT 去重） */
  tt_open: number
  tt_closed: number
  tt_total: number
  /** 由 WO 站点反推的县名（不是 managed_regions） */
  counties: string[]
  /** 未关闭 WO 涉及的站点数（去重）——地图徽标显示。
   *  与 `/managed-sites` 的 `site_count` 同口径（都只计未关闭 WO 的站点）。 */
  site_count: number
}

/** `/personnel/stats` 的响应 */
export interface PersonStats {
  by_person: PersonRow[]
  top_person: PersonRow[]
  by_county: Record<string, { open: number; closed: number; total: number }>
  by_status: { open: number; closed: number }
  coverage: {
    with_coords: number
    total_all: number
    location_is_realtime: boolean
  }
}

/** 该人员 WO 涉及过的一个站点。`/personnel/{key}/managed-sites` 的元素 */
export interface ManagedSite {
  site_id: string
  site_name: string
  region: string
  county: string
  lat: number
  lng: number
  /** 该人员在窗口内此站的未关闭 WO 数 */
  wo_count: number
  /** 其中未清除告警的 WO 数 */
  uncleared: number
  /** 该站点当前是否有实时告警 */
  has_alarm: boolean
  /** 仅 `/sites/search` 返回：未关闭 WO 的负责人数（含无坐标者） */
  owner_count?: number
  /** 仅 `/sites/search` 返回：其中**有坐标、可在图上选中**的负责人键。
   *  搜站点后前端据此选中负责人（见 PersonMapView 的 handlePickSite）。 */
  owner_keys?: string[]
}

/** `/personnel/{key}/managed-sites` 的响应 */
export interface ManagedSitesResp {
  name_key: string
  sites: ManagedSite[]
  site_count: number
  alarm_site_count: number
  uncleared_total: number
  open_total: number
  skipped_no_coord: number
}
