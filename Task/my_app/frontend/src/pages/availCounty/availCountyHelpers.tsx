/* ============================================================================
 * availCountyHelpers.ts —— 县维度可用率页面的纯函数与列定义
 * ----------------------------------------------------------------------------
 * 抽出来的理由：页面主体（AvailCounty.tsx）已接近 500 行上限，
 * 而列定义/格式化/导出这类「不依赖 React 状态」的逻辑单独成文件更好维护。
 * ========================================================================== */
import { Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { WH } from '../../theme'
import {
  Cell, Gran, MatrixRow, SiteDailyRow, SiteRow, TtRow, UNMATCHED_KEY, dailyValue,
} from './availCountyTypes'

const { Text } = Typography

/** 警告码 -> i18n 键。**刻意用显式 switch**：`t('availCounty.warn.' + code)`
 *  会被 check:i18n 读成键名 `availCounty.warn.` 而报字典缺失（AGENTS.md 第三节 1b）。 */
export function warnKey(code: string): string | null {
  switch (code) {
    case 'kpi_tables_missing': return 'availCounty.warn.kpiTablesMissing'
    case 'unmatched_sites': return 'availCounty.warn.unmatchedSites'
    case 'limited_coverage': return 'availCounty.warn.limitedCoverage'
    case 'no_data_for_period': return 'availCounty.warn.noDataForPeriod'
    case 'site_not_found': return 'availCounty.warn.siteNotFound'
    case 'unknown_level': return 'availCounty.warn.unknownLevel'
    case 'options_failed': return 'availCounty.warn.loadFailed'
    case 'matrix_failed': return 'availCounty.warn.loadFailed'
    case 'trend_failed': return 'availCounty.warn.loadFailed'
    case 'drilldown_failed': return 'availCounty.warn.readFailed'
    default: return null
  }
}

/** 失败类警告用红色，其余为口径提示（黄色） */
export const isErrorWarn = (code: string) =>
  ['kpi_tables_missing', 'options_failed', 'matrix_failed', 'trend_failed',
    'drilldown_failed'].includes(code)

/** 档位 -> 页签文案键。**刻意用显式 switch**：模板串拼键
 *  会被 check:i18n 读成字面量键名而报字典缺失（AGENTS.md 第三节 1b）。 */
export function granLabelKey(gran: Gran): string {
  switch (gran) {
    case 'day': return 'availCounty.tabDay'
    case 'week': return 'availCounty.tabWeek'
    default: return 'availCounty.tabDay'
  }
}

/** 单元格着色：未达标红、达标绿、无数据显示灰 */
export function cellColor(cell: Cell | undefined): string {
  if (!cell || cell.availability == null) return WH.textMuted
  return cell.below ? WH.danger : WH.ok
}

/** 环比箭头（百分点，正=变好；pp 后缀避免被误读成“0.05%”） */
export function deltaNode(delta: number | null | undefined) {
  if (delta == null) return null
  return (
    <span style={{ marginLeft: 4, fontSize: 11, color: delta < 0 ? WH.danger : WH.ok }}>
      {delta < 0 ? '▼' : '▲'}{Math.abs(delta).toFixed(2)}pp
    </span>
  )
}

/** 县名 -> 展示名：未归属行走 i18n，其余保持业务原值不翻译 */
export function countyLabel(county: string, unmatchedText: string): string {
  return county === UNMATCHED_KEY ? unmatchedText : county
}

/** 县矩阵的列定义（行=县，列=2G/3G/4G） */
export function buildCountyColumns(
  techs: string[],
  onCell: (row: MatrixRow, tech: string) => void,
  labels: {
    county: string; region: string; sites: string; avail: string
    unmatched: string; threshold: string
  },
  techLabels: Record<string, string>,
): ColumnsType<MatrixRow> {
  return [
    {
      title: labels.county,
      dataIndex: 'county',
      width: 170,
      fixed: 'left' as const,
      render: (v: string, r) => (
        <span>
          <Text strong>{countyLabel(v, labels.unmatched)}</Text>
          {r.region ? (
            <span style={{ marginLeft: 6, fontSize: 11, color: WH.textMuted }}>{r.region}</span>
          ) : null}
        </span>
      ),
    },
    ...techs.map((tech) => ({
      title: techLabels[tech] || tech,
      key: tech,
      align: 'right' as const,
      width: 158,
      // 无数据行沉底（-1），避免“—”排在最前误导
      sorter: (a: MatrixRow, b: MatrixRow) =>
        (a.cells?.[tech]?.availability ?? -1) - (b.cells?.[tech]?.availability ?? -1),
      render: (_: unknown, r: MatrixRow) => {
        const cell = r.cells?.[tech]
        if (!cell || cell.availability == null) return <Text type="secondary">—</Text>
        return (
          <span
            role="button"
            tabIndex={0}
            style={{ cursor: 'pointer', color: cellColor(cell), fontWeight: 600 }}
            onClick={() => onCell(r, tech)}
            onKeyDown={(e) => { if (e.key === 'Enter') onCell(r, tech) }}
          >
            {(cell.availability * 100).toFixed(2)}%
            {deltaNode(cell.delta_pp)}
            <span style={{ marginLeft: 6, fontSize: 11, color: WH.textMuted }}>
              {cell.sites}
            </span>
          </span>
        )
      },
    })),
  ]
}

/** 下钻：站点明细列 */
export function siteColumns(
  tech: string,
  labels: {
    site: string; siteId: string; region: string; type: string; avail: string; days: string
  },
  onSite: (row: SiteRow) => void,
  threshold = 0.9965,
): ColumnsType<SiteRow> {
  return [
    {
      title: labels.site,
      dataIndex: 'site_name',
      width: 200,
      fixed: 'left' as const,
      render: (v: string, r) => (
        <span
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer', color: WH.blue, fontWeight: 600 }}
          onClick={() => onSite(r)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSite(r) }}
        >
          {v || '—'}
        </span>
      ),
    },
    { title: labels.siteId, dataIndex: 'site_id', width: 90, render: (v) => v || '—' },
    { title: labels.region, dataIndex: 'region', width: 120, render: (v) => v || '—' },
    { title: labels.type, dataIndex: 'site_type', width: 100, render: (v) => v || '—' },
    {
      title: labels.avail,
      dataIndex: 'availability',
      align: 'right' as const,
      width: 110,
      sorter: (a: SiteRow, b: SiteRow) => a.availability - b.availability,
      render: (v: number) => (
        <Text strong style={{ color: v < threshold ? WH.danger : WH.ok }}>
          {(v * 100).toFixed(2)}%
        </Text>
      ),
    },
    { title: labels.days, dataIndex: 'days_with_data', align: 'right' as const, width: 90 },
  ]
}

/** 下钻：站点逐日明细列 */
export function siteDailyColumns(
  techs: string[],
  labels: { day: string; avail: string },
  techLabels: Record<string, string>,
  threshold = 0.9965,
): ColumnsType<SiteDailyRow> {
  return [
    { title: labels.day, dataIndex: 'day', width: 130 },
    ...techs.map((tech) => ({
      title: techLabels[tech] || tech,
      key: tech,
      align: 'right' as const,
      width: 130,
      render: (_: unknown, r: SiteDailyRow) => {
        const v = dailyValue(r, tech)
        if (v == null) return <Text type="secondary">—</Text>
        return (
          <Text strong style={{ color: v < threshold ? WH.danger : WH.ok }}>
            {(v * 100).toFixed(2)}%
          </Text>
        )
      },
    })),
  ]
}

/** 下钻：TT 工单列 */
export function ttColumns(
  labels: {
    ttNo: string; title: string; severity: string; site: string; status: string
    occur: string; handler: string; downSites: string; rootCause: string
  },
): ColumnsType<TtRow> {
  return [
    { title: labels.ttNo, dataIndex: 'tt_no', width: 160, fixed: 'left' as const },
    {
      title: labels.title, dataIndex: 'title', ellipsis: true,
      render: (v: string) => v || '—',
    },
    { title: labels.severity, dataIndex: 'ticket_severity', width: 80 },
    {
      title: labels.site, dataIndex: 'site_name', width: 170, ellipsis: true,
      render: (v: string, r) => v || r.site_id || '—',
    },
    { title: labels.status, dataIndex: 'status', width: 150, ellipsis: true },
    {
      title: labels.occur, dataIndex: 'alarm_occur_time', width: 160,
      render: (v: string, r) => v || r.created_time || '—',
    },
    { title: labels.handler, dataIndex: 'current_handler', width: 130, ellipsis: true },
    {
      title: labels.downSites, key: 'down', width: 140, align: 'right' as const,
      render: (_: unknown, r: TtRow) => {
        const f = (x: string | number | null) => (x == null || x === '' ? '—' : String(x))
        return `${f(r.col_2g_down_site_count)}/${f(r.col_3g_down_site_count)}`
          + `/${f(r.col_4g_down_site_count)}`
      },
    },
    { title: labels.rootCause, dataIndex: 'root_cause', width: 160, ellipsis: true },
  ]
}
