/* ============================================================================
 * availSumRatio.ts —— avail_ms 与 avail_flm **共用**的数字悬浮口径说明
 * ----------------------------------------------------------------------------
 * 为什么共用一个文件：两页读同一个派生库、同一套单元格口径
 * `SUM(Numerator)/SUM(Denominator)`（`backend/services/avail_ms_service.py` 顶部
 * 「口径（勿改）」；`avail_flm_service.py` 明确写「实现全部复用 avail_ms_service，
 * 本模块不重写任何聚合」）。同一口径若在两页各写一份文案，日后必然各改各的，
 * 变成两个真相源 —— 这里只写一份，两页都从这里取。
 *
 * 分子/分母的语义是**实测**确认的（2026-11-03，规则 AGENTS.md 三.3c 要求不得照抄手册）：
 *   日档 ALL 2G = 681/717，周档 W44 = 1363/1435 ≈ 日档 × 2（该周只同步到 2 天）
 *   → 分母按「站点-日」累加（每天每个有值站点计 1），分子是这些观测的可用率累加，
 *     比值 = **按站点-日加权**的平均可用率（`availability === numerator/denominator` 逐位相等）。
 * ========================================================================== */

type TFn = (key: string, params?: Record<string, string | number>) => string

/** 两页的矩阵单元格都至少有这几个字段（各自本地定义的 Cell 结构兼容此形状） */
export interface SumRatioCell {
  availability: number | null
  numerator: number
  denominator: number
  delta_pp?: number | null
}

/** 列头 / KPI 卡 ⓘ 的文案键（讲「这一列怎么算」，静态口径） */
export const SUM_RATIO_COL_KEY = 'availSum.explainCol'
/** 全网 KPI 卡 ⓘ 的文案键（讲「这张卡怎么算」） */
export const SUM_RATIO_KPI_KEY = 'availSum.explainKpi'
/** FLM 页区域 KPI 卡 ⓘ 的文案键（区域 = 全部制式合计，与按制式切的卡口径不同） */
export const SUM_RATIO_REGION_KPI_KEY = 'availSum.explainRegionKpi'
/** 未匹配占比卡 ⓘ 的文案键 */
export const SUM_RATIO_UNMATCHED_KEY = 'availSum.explainUnmatched'

/** 单元格气泡：这一格自己的构成（分子/分母语义 + 加权含义 + 环比） */
export function sumRatioCellText(cell: SumRatioCell, t: TFn): string {
  const delta = cell.delta_pp
  return [
    t('availSum.tip.ratio', { n: cell.numerator, d: cell.denominator }),
    t('availSum.tip.parts'),
    t('availSum.tip.weighted'),
    delta != null
      ? t('availSum.tip.delta', { delta: `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}` })
      : '',
    t('availSum.tip.drill'),
  ].filter(Boolean).join('\n')
}
