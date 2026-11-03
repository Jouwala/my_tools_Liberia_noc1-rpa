/* ============================================================================
 * availCountyTypes.ts —— 县维度可用率页面的类型定义与常量
 * ----------------------------------------------------------------------------
 * 与后端 backend/services/avail_county_service.py 的返回结构一一对应。
 * 单独成文件的原因：页面主体（AvailCounty.tsx）已接近单文件 500 行的上限
 * （工作区 AGENTS.md 第三节原则 2），类型定义挤在页面里会让它继续膨胀。
 * ========================================================================== */

/** 周期粒度：日 / 周 */
export type Gran = 'day' | 'week'

/** 下钻层级 */
export type DrillLevel = 'county_sites' | 'site_daily' | 'tt'

/** 矩阵单元格 */
export interface Cell {
  /** 本期可用率（0~1 比率），null = 无数据 */
  availability: number | null
  /** 有值站点数 */
  sites: number
  /** 站点-日样本数（分子：参与平均的观测点个数） */
  site_days: number
  /** 未达标站点数 */
  below_sites: number
  min: number | null
  max: number | null
  /** 上一期可用率（环比基期） */
  prev_availability: number | null
  /** 环比变化（百分点，正=变好） */
  delta_pp: number | null
  /** 是否低于阈值 */
  below: boolean | null
}

/** 矩阵行 = 一个县 */
export interface MatrixRow {
  /** 县名；未归属行是 '__UNMATCHED__' */
  county: string
  /** 所属大区 */
  region: string
  /** 该县站点总数（主数据口径） */
  site_total: number
  cells: Record<string, Cell>
}

export interface Matrix {
  meta: {
    month: string
    period: Gran
    /** 当前实际展示的周期值（后端解析后的规范值） */
    value: string
    start_day: string
    end_day: string
    /** 环比基期的日期列表 */
    prev_days: string[]
    days: string[]
    threshold: number
    counties: string[]
    techs: string[]
    /** 数据截至日 */
    data_through: string
    /** 本期有数据的日期 */
    covered_days: string[]
    /** 本月有数据的日期（让「本月只同步了 1 天」看得见） */
    month_covered_days: string[]
    month_covered_count: number
    month_day_count: number
    /** 该月最后一个有数据的日子 */
    latest_day: string
    generated_at: string
    elapsed_ms: number
    warnings: string[]
    has_unmatched: boolean
  }
  summary: {
    by_tech: Record<string, {
      availability: number | null
      counties_with_data: number
      counties_below: number
      min: number | null
      sites: number
    }>
    county_count: number
  }
  rows: MatrixRow[]
}

/** 趋势曲线的一条线 = 一个制式 */
export interface TrendSeries {
  key: string
  /** 每期的可用率（null = 该期无数据） */
  values: (number | null)[]
  /** 每期有值站点数 */
  numerators: number[]
  denominators: number[]
  overall: number | null
  below_periods: number
}

export interface Trend {
  meta: {
    month: string
    period: Gran
    county: string
    threshold: number
    points: number
    data_through: string
    generated_at: string
    warnings: string[]
  }
  categories: string[]
  series: TrendSeries[]
}

/** 下钻：站点明细行 */
export interface SiteRow {
  site_key: string
  site_id: string
  site_name: string
  county: string
  region: string
  site_type: string
  network_type: string
  availability: number
  days_with_data: number
  /** 逐日值 */
  daily: Record<string, number>
  below: boolean
}

/** 下钻：站点逐日明细行 */
export interface SiteDailyRow {
  day: string
  '2G'?: number | null
  '3G'?: number | null
  '4G'?: number | null
  /** 后端按**制式名**返回列，故允许按制式动态取值（`day` 是字符串列，见 `dailyValue`） */
  [tech: string]: string | number | null | undefined
}

/** 取某制式在逐日行里的值（非数字一律当「无数据」）。
 *  为什么要这个函数而不是 `row[tech]`：`day` 是字符串列，
 *  索引签名的类型是 `string | number | null | undefined`，直接用会拿到宽类型，
 *  必须收窄成 `number | null` 才能参与比较与格式化。 */
export function dailyValue(row: SiteDailyRow, tech: string): number | null {
  const v = row[tech]
  return typeof v === 'number' ? v : null
}

/** 下钻：TT 工单行 */
export interface TtRow {
  tt_no: string
  title: string
  status: string
  ticket_severity: string
  site_id: string
  site_name: string
  county?: string
  site_outage: string
  current_handler: string
  root_cause: string
  alarm_occur_time: string
  created_time: string
  fault_duration_time: string
  whether_impacted_service: string
  impacted_service: string
  col_2g_down_site_count: string | number | null
  col_3g_down_site_count: string | number | null
  col_4g_down_site_count: string | number | null
}

export interface Drill {
  meta: {
    level: DrillLevel
    period: Gran
    value: string
    county?: string
    tech?: string
    start_day?: string
    end_day?: string
    site_name?: string
    site_id?: string
    total?: number
    returned?: number
    /** 明细被截断 —— 必须显式暴露，不允许静默截断 */
    truncated?: boolean
    threshold?: number
    warnings: string[]
    error?: string
  }
  rows: SiteRow[] | SiteDailyRow[] | TtRow[]
}

export interface Options {
  months: string[]
  current_month: string
  counties: { county: string; site_count: number }[]
  techs: string[]
  threshold: number
  /** 数据截至日 */
  data_through: string
  /** 该月最后一个有数据的日子 */
  latest_day?: string
  warnings: string[]
  error?: string
}

/** 一个可下钻的目标：县 × 制式 */
export interface CellTarget {
  county: string
  tech: string
  label: string
}

/** 未归属行 key（后端常量，前端保持一致） */
export const UNMATCHED_KEY = '__UNMATCHED__'

/** 三种制式（与后端 TECHS 一致） */
export const TECHS = ['2G', '3G', '4G'] as const

/** 周期档位 */
export const GRANS: Gran[] = ['day', 'week']

/** 取不到数据一律 `—`，不得显示成 0 */
export const fmtPct = (v: number | null | undefined, digits = 2) =>
  (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)

export const fmtNum = (v: number | string | null | undefined) =>
  (v == null || v === '' ? '—' : String(v))
