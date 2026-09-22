// GISMap 页面类型定义

export interface Site {
  site_id: string
  site_name: string
  lat: number
  lng: number
  region: string
  province_county: string
  network_type: string
  site_type: string
  vip_site: string
  hub_site: string
  tt_count: number
  open_tt: number
  closed_tt: number
  wo_count: number
  rt_alarm_count: number
  his_alarm_count: number
  rt_alarm_overdue?: number
  rt_alarm_ontime?: number
  rt_tt_count?: number
  rt_wo_count?: number
  trm_type?: string
  area?: string
  hubsite?: string
  site_information?: string
  supervisor?: string
  updated_fme_name_new?: string
}

// ========== 图表数据结构（与 backend/routers/gis.py 聚合接口对齐）==========

/** 名称/计数对，用于饼图、柱状图 */
export interface NameValue {
  name: string
  value: number
}

/** 微波链路逐日历史点 */
export interface MwHistoryPoint {
  day: string
  tx_util?: number | null
  rx_util?: number | null
  max_util?: number | null
}

/** 单个制式的站点级 KPI 序列（2G/3G/4G 页签） */
export interface RatKpiSeries {
  matched_by?: 'site_id' | 'site_name' | null
  site_name?: string | null
  metrics: { key: string; label: string; is_rate: boolean | null }[]
  daily: (Record<string, any> & { day: string })[]
  days: number
  error?: string
}

/**
 * /gis/drilldown/{id}/analytics 的返回。
 * 与明细列表不同：这里是站点全量聚合，不受 LIMIT 50/100 截断影响。
 */
export interface DrilldownAnalytics {
  site_id?: string
  site_name?: string
  range?: { start: string; end: string; days: number }
  tt?: {
    total?: number
    closed?: number
    open?: number
    sla_met?: number
    sla_violated?: number
    sla_rate?: number | null
    first_time?: string | null
    last_time?: string | null
    daily?: { day: string; total: number; closed: number }[]
    by_status?: NameValue[]
    by_severity?: NameValue[]
    by_sla?: NameValue[]
    by_root_cause?: NameValue[]
    duration_buckets?: NameValue[]
    duration_parsed?: number
    duration_total?: number
  }
  wo?: {
    total?: number
    daily?: { day: string; total: number }[]
    by_status?: NameValue[]
    by_source?: NameValue[]
    by_root_cause?: NameValue[]
    by_severity?: NameValue[]
  }
  his?: {
    total?: number
    daily?: { day: string; total: number }[]
    by_severity?: NameValue[]
    by_title?: NameValue[]
  }
  warnings?: string[]
}

export interface DrilldownData {
  site_info: Record<string, any>
  tt_list: any[]
  tt_count: number
  wo_list: any[]
  wo_count: number
  rt_alarm_list: any[]
  rt_alarm_count: number
  his_alarm_list: any[]
  his_alarm_count: number
  sla_stats: {
    total_tt: number
    closed_tt: number
    sla_met: number
    sla_violated: number
  }
  /** 明细列表实际使用的时间窗口 */
  range?: { start: string; end: string; days: number }
  kpis?: {
    availability?: { tech: string; day: string; availability: number }[]
    packet_loss?: { day: string; max_packet_loss: number; avg_packet_loss: number; samples: number }[]
    microwave?: {
      source: string; target: string
      tx_utilization: number; rx_utilization: number
      capacity_mbps: number; level?: string; begin_time?: string
      max_util?: number
      /** 逐日利用率历史，用于趋势折线（后端 mw_ume_topology 提供） */
      history?: MwHistoryPoint[]
    }[]
    /** 分制式站点级 KPI 序列：{ '2G': {...}, '3G': {...}, '4G': {...} } */
    kpi_series?: Record<string, RatKpiSeries>
    warnings?: string[]
  }
}

export interface TopologyLink {
  site_a_id: string
  site_a_name: string
  site_b_id: string
  site_b_name: string
  hop_count: number
  is_hub_link: boolean
  lat_a: number
  lng_a: number
  lat_b: number
  lng_b: number
}

export type LegendKey = 'tt' | 'wo' | 'vip' | 'normal' | 'rt_alarm' | 'rt_alarm_overdue' | 'rt_alarm_ontime' | 'his_alarm'
export type LayerKey = 'rt_alarm' | 'his_alarm' | 'tt' | 'wo'
export type TimePreset = 'all' | '7d' | '30d' | '90d' | '180d' | 'custom'

// i18n 翻译函数类型
export type TFn = (key: string, params?: Record<string, string | number>) => string
