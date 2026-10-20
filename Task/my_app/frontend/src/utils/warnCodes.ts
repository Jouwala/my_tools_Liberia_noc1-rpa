/* ==================== 后端 meta.warnings 的码表 ====================
 * 约定：后端只发「稳定 ASCII 码[: 技术详情]」，给人看的句子由前端按当前语言出。
 * 与 AvailFlm.tsx / AvailMs.tsx 里的 warnKey() 同一套路（那两处是页面私有码表）。
 * 未收录的串原样透出 —— 那部分是异常原文、表名、列名，任何语言都不该翻译。
 * =============================================================== */

const WARN_KEYS: Record<string, string> = {
  load_failed: 'common.warn.loadFailed',
  invalid_tech: 'common.warn.invalidTech',
  // ---- GIS 地图降级提示（backend/routers/gis.py）----
  avail_no_data_days: 'gis.warn.availNoDataDays',
  avail_unavailable: 'gis.warn.availUnavailable',
  loss_source_missing: 'gis.warn.lossSourceMissing',
  loss_unavailable: 'gis.warn.lossUnavailable',
  mw_util_unavailable: 'gis.warn.mwUtilUnavailable',
  tt_summary_failed: 'gis.warn.ttSummaryFailed',
  tt_dist_failed: 'gis.warn.ttDistFailed',
  wo_stats_failed: 'gis.warn.woStatsFailed',
  site_join_unknown: 'gis.warn.siteJoinUnknown',
  alarm_no_parseable_id: 'gis.warn.alarmNoParseableId',
  alarm_capped: 'gis.warn.alarmCapped',
  alarm_skipped: 'gis.warn.alarmSkipped',
}

/** 单条：`码` 或 `码: 技术详情`。命中码表则出当前语言的句子，否则原样返回。
 *  详情若落在句子中间（文案里写了 {n}），插进 {n}；否则追加在句尾。 */
export function fmtWarning(raw: string, t: (k: string) => string): string {
  const colon = raw.indexOf(':')
  const code = (colon < 0 ? raw : raw.slice(0, colon)).trim()
  const key = WARN_KEYS[code]
  if (!key) return raw
  const detail = colon < 0 ? '' : raw.slice(colon + 1).trim()
  const text = t(key)
  if (detail && text.includes('{n}')) return text.replace('{n}', detail)
  return detail ? `${text}: ${detail}` : text
}

export const fmtWarnings = (
  list: string[] | undefined | null,
  t: (k: string) => string,
  sep = '; ',
): string => (list || []).map((w) => fmtWarning(w, t)).join(sep)
