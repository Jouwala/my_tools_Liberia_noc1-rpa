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
