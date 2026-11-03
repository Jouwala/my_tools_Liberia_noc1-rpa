/* ============================================================================
 * availCountyExport.ts —— 县维度可用率页面的 Excel 导出
 * ----------------------------------------------------------------------------
 * 抽出来的理由：导出逻辑是「把接口返回的数据翻译成多 sheet 报表」，
 * 与页面主体的 React 状态无关，单独成文件后可以独立读懂、独立改。
 *
 * 强制约束（AGENTS.md 第三节）：
 *   · 一律走 `utils/excelReport` 的 exportReport，**不得**直接用 xlsx；
 *   · 取不到数据的数字一律输出 `—`，**不得**输出 0（0 会被读成「可用率 0%」）。
 * ========================================================================== */
import dayjs from 'dayjs'

import { exportReport } from '../../utils/excelReport'
import type { ReportSheetSpec } from '../../utils/excelReport'
import {
  Drill, DrillLevel, Matrix, SiteDailyRow, SiteRow, TECHS, Trend, TtRow, dailyValue,
} from './availCountyTypes'

/** 翻译函数签名（与 useI18n().t 一致，这里只声明用到的形状） */
export type TFn = (key: string, params?: Record<string, string | number>) => string

/** 比率 -> 报表里的数值（百分数，保留 4 位）；无值返回 null（调用方写 `—`） */
function pctValue(v: number | null | undefined): number | null {
  return v == null ? null : Number((v * 100).toFixed(4))
}

/** 导出主页面（汇总 + 县矩阵 + 走势） */
export async function exportAvailCountyPage(
  matrix: Matrix,
  trend: Trend | null,
  opts: {
    trendCounty: string
    techLabels: Record<string, string>
    thresholdPct: number
    rowLabel: (c: string) => string
    t: TFn
  },
): Promise<void> {
  const { trendCounty, techLabels, thresholdPct, rowLabel, t } = opts
  const val = matrix.meta.value || 'latest'
  const techs = matrix.meta.techs || [...TECHS]

  const sheets: ReportSheetSpec[] = [{
    name: 'Summary',
    title: t('availCounty.exportTitle'),
    subtitle: `${matrix.meta.month} | ${matrix.meta.period} ${val} | `
      + `${t('availCounty.threshold')} ${thresholdPct}% | `
      + `${t('availCounty.dataThrough')} ${matrix.meta.data_through}`,
    header: [t('availCounty.colItem'), t('availCounty.colValue')],
    rows: [
      [t('availCounty.colMonth'), matrix.meta.month],
      [t('availCounty.colPeriod'), `${matrix.meta.period} ${val}`],
      [t('availCounty.dataThrough'), matrix.meta.data_through || '—'],
      [t('availCounty.coveredDays'),
        `${matrix.meta.month_covered_count} / ${matrix.meta.month_day_count}`],
      ...techs.map(tech => [
        t('availCounty.kpiTech', { tech }),
        pctValue(matrix.summary.by_tech?.[tech]?.availability) ?? '—',
      ]),
    ],
    numericCols: [1],
  }, {
    name: t('availCounty.sheetCounties'),
    title: `${t('availCounty.sheetCounties')}（${val}）`,
    subtitle: `${t('availCounty.caliberNote')}`,
    header: [t('availCounty.colCounty'), t('availCounty.colRegion'),
      ...techs.flatMap(tech => [
        `${techLabels[tech] || tech} ${t('availCounty.colAvail')}`,
        `${techLabels[tech] || tech} ${t('availCounty.colSites')}`,
      ])],
    rows: matrix.rows.map(r => [
      rowLabel(r.county), r.region || '—',
      ...techs.flatMap(tech => {
        const c = r.cells?.[tech]
        return [pctValue(c?.availability) ?? '—', c?.sites ?? 0]
      }),
    ]),
    numericCols: techs.flatMap((_, i) => [i + 2, i + 3]),
  }]

  if (trend && trend.categories?.length) {
    sheets.push({
      name: t('availCounty.sheetTrend'),
      title: `${rowLabel(trendCounty || '__all__')} · ${t('availCounty.trendTitle')}`,
      subtitle: `${trend.meta.month} | ${trend.meta.points} ${t('availCounty.colPeriod')}`,
      header: [t('availCounty.colPeriod'), ...techs.map(tech => techLabels[tech] || tech)],
      rows: trend.categories.map((cat, i) => [
        cat,
        ...techs.map(tech => {
          const s = trend.series.find(x => x.key === tech)
          return pctValue(s?.values?.[i]) ?? '—'
        }),
      ]),
      numericCols: techs.map((_, i) => i + 1),
    })
  }

  await exportReport(
    sheets,
    `avail_county_${matrix.meta.month}_${val}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
  )
}

/** 导出下钻明细（站点 / 逐日 / TT 三种形态各一个 sheet） */
export async function exportAvailCountyDrill(
  drill: Drill,
  target: { tech: string; label: string } | null,
  opts: {
    modalTab: DrillLevel
    drillValue: string
    thresholdPct: number
    techLabels: Record<string, string>
    t: TFn
  },
): Promise<void> {
  if (!target) return
  const { modalTab, drillValue, thresholdPct, techLabels, t } = opts
  const sheets: ReportSheetSpec[] = []

  if (modalTab === 'county_sites') {
    const rows = drill.rows as SiteRow[]
    sheets.push({
      name: t('availCounty.tabSites'),
      title: `${target.label} · ${t('availCounty.tabSites')}`,
      subtitle: `${drill.meta.value} | ${t('availCounty.threshold')} ${thresholdPct}%`,
      header: [t('availCounty.colSite'), t('availCounty.colSiteId'),
        t('availCounty.colRegion'), t('availCounty.colSiteType'),
        t('availCounty.colAvail'), t('availCounty.colDays')],
      rows: rows.map(r => [r.site_name, r.site_id, r.region || '—', r.site_type || '—',
        pctValue(r.availability) ?? '—', r.days_with_data]),
      numericCols: [4, 5],
    })
  } else if (modalTab === 'site_daily') {
    const rows = drill.rows as SiteDailyRow[]
    sheets.push({
      name: t('availCounty.tabDaily'),
      title: `${target.label} · ${t('availCounty.tabDaily')}`,
      subtitle: `${drill.meta.start_day} ~ ${drill.meta.end_day}`,
      header: [t('availCounty.colDay'), ...TECHS.map(tech => techLabels[tech] || tech)],
      rows: rows.map(r => [
        r.day,
        ...TECHS.map(tech => pctValue(dailyValue(r, tech)) ?? '—'),
      ]),
      numericCols: TECHS.map((_, i) => i + 1),
    })
  } else {
    const rows = drill.rows as TtRow[]
    sheets.push({
      name: 'TT',
      title: `${target.label} · ${t('availCounty.tabTt')}`,
      subtitle: `${drill.meta.start_day} ~ ${drill.meta.end_day} | `
        + `${t('availCounty.ttCount', { n: drill.meta.total || 0 })}`,
      header: [t('availCounty.colTtNo'), t('availCounty.colTitle'),
        t('availCounty.colSeverity'), t('availCounty.colSite'),
        t('availCounty.colStatus'), t('availCounty.colOccur'),
        t('availCounty.colHandler'), t('availCounty.colDownSites'),
        t('availCounty.colRootCause')],
      rows: rows.map(r => [r.tt_no, r.title, r.ticket_severity, r.site_name || r.site_id,
        r.status, r.alarm_occur_time || r.created_time, r.current_handler,
        `${fmtCount(r.col_2g_down_site_count)}/${fmtCount(r.col_3g_down_site_count)}`
        + `/${fmtCount(r.col_4g_down_site_count)}`,
        r.root_cause]),
      numericCols: [7],
    })
  }

  if (sheets.length) {
    await exportReport(
      sheets,
      `avail_county_drill_${target.tech}_${drillValue}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
    )
  }
}

/** 断站数：无值写 `—`，不写 0 */
function fmtCount(x: string | number | null | undefined): string {
  return x == null || x === '' ? '—' : String(x)
}
