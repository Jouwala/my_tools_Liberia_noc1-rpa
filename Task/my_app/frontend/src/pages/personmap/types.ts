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
  /** 负责的站点数 = `master_site_db.fme_name` 登记的站（`A / B` 双人共担两边都算）。
   *  与 `/managed-sites` 的 `site_count` 同口径 —— 两边都出自后端同一个
   *  `_fme_site_index`，2026-10-21 实测 24 人逐个对拍 0 处不一致。
   *  ⚠ 口径变更：旧口径是「30 天内未关闭 WO 涉及的站点」（人均 4.6 站、最多 16），
   *  改后人均 35 站、最多 98。改的直接动机是地图要分三档色（绿/浅蓝/红），
   *  而旧集合里每个站都必然有未关闭 WO，**绿色永远不可能出现**。
   *  ⚠ 有坐标的 24 人里有 6 人不是任何站的 FME（含未关闭单最多的
   *  Varfee Sarnor / Franklin Peter），他们的 `site_count` 恒为 0、
   *  点开了地图上没有点 —— 用户确认接受这个后果。 */
  site_count: number
  /** 以 `master_site_db.supervisor` 身份登记的站数。**只用于空态解释**，
   *  既不计入 `site_count` 也不画进地图 —— 实测 supervisor 只有 3 个取值，
   *  把全国 824 站三三分掉（Varfee Sarnor 353 / Franklin Peter 294 /
   *  Festus Emmanuel 177），语义是「大区主管」不是「单站负责」。
   *  有坐标的 24 人里 6 人 `site_count` 为 0：上面这 3 个 supervisor，
   *  加 3 个在 master_site_db 人员列里根本没出现的（此字段也为 0）。 */
  supervised_sites: number
  /** 当前未关闭的 PMT（预防性维护工单）数。`null` = 后端取不到 eflow_pm，
   *  界面必须显示 `—` 而不是 0（AGENTS.md 三.6）。
   *  ⚠ **不跟随页面的 30 天窗口** —— 它是「此刻还没关闭」的状态数。
   *  理由见后端 `personnel.py::_pmt_open_index`（已关闭的 PMT 在库里
   *  `current_handler` 为空，历史归属做不出来；套窗口会把 1715 砍到 826）。
   *  只挂在 `G:` 组池上的 PMT 不计入任何个人，总数在 `PersonStats.pmt.group_pool`。 */
  pmt_open: number | null
}

/** `/personnel/stats` 的响应 */
export interface PersonStats {
  by_person: PersonRow[]
  top_person: PersonRow[]
  by_county: Record<string, { open: number; closed: number; total: number }>
  by_status: { open: number; closed: number }
  /** 未关闭 PMT 的全局量，供 ⓘ 说明「为什么各人徽标加起来对不上总数」 */
  pmt: {
    /** 库里全部未关闭 PMT 张数 */
    open_total: number
    /** 其中只挂在组池（`G:ZTE_FE_MG` 这类）、归不到任何个人头上的张数 */
    group_pool: number
  }
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

/** WO 明细的一行（`/personnel/{key}/work-orders` 响应，字段见后端 `_WO_COLS`） */
export interface WoRow {
  wo_no: string
  tt_no?: string
  title?: string
  status?: string
  site_id?: string
  site_name?: string
  county?: string
  region?: string
  alarm_occur_time?: string
  alarm_clear_time?: string
  ticket_severity?: string
  alarm_severity?: string
  operation_step?: string
}

/** PMT 明细的一行（`/personnel/{key}/pmt` 响应，字段见后端 `_PMT_COLS`）。
 *  ⚠ `completed_items` / `total_items` 在库里是**文本**（后端原样下发），
 *  拼进度条前要 Number()。 */
export interface PmtRow {
  pmt_no: string
  status?: string
  title?: string
  pmp_no?: string
  pmt_overdue?: string
  site_name?: string
  template?: string
  completed_items?: string
  total_items?: string
  current_task_start_time?: string
  current_task_end_time?: string
  created_time?: string
  last_modified_time?: string
  current_handler?: string
}

/** `/personnel/{key}/pmt` 的响应 */
export interface PmtResp {
  name_key: string
  pmt_list: PmtRow[]
  pmt_count: number
  meta: {
    /** false = 后端取不到 eflow_pm（徽标那侧同样显示 —，两处表现一致） */
    available: boolean
    truncated: boolean
    limit: number
    overdue_count: number
  }
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
