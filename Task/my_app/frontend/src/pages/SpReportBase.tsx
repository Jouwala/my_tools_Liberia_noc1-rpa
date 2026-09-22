import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Card, Col, Empty, Input, Row, Segmented, Select, Space, Spin, Table, Tag,
  Tooltip, Typography, message,
} from 'antd'
import {
  ReloadOutlined, DownloadOutlined, SearchOutlined, InfoCircleOutlined, CloseCircleOutlined,
  WarningOutlined, RiseOutlined, FallOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  getSpReportFilters, getSpReportRows, getSpReportSummary, type SpReportKind,
} from '../api'
import { useI18n, numLocale } from '../i18n'
import { useTheme, WH } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportReport, safeFileName, type CellValue } from '../utils/excelReport'

const { Text } = Typography

/**
 * SP 备件 / 耗材 汇总报表页面（page=sp_report / com_report）
 *
 * 数据源：任务 `sp_report_generate`（SP 备件报表生成，每天 05:15）产出的汇总
 * 工作簿 `data/sp_email/<前缀> <时间戳>.xlsx` —— 与邮件/WhatsApp 发出去的是
 * 同一份文件，页面不做二次加工；口径见 backend/services/sp_report_service.py。
 *
 * 两份报表（SpareParts / Consumables）结构完全一致，只是文件名前缀与明细列略有
 * 差异，因此本组件按 `kind` 参数化，由两个极薄的页面包装（见 SpReport.tsx /
 * ComReport.tsx），避免维护两份几乎相同的看板。
 *
 * 页面结构：统计卡片（汇总 KPI + 补库告警 + 分表）+ 每日入出库矩阵 + 明细表格。
 */

// ==================== 类型（与后端 service 返回结构对齐） ====================
interface CounterItem {
  value: string
  count: number
}
interface SheetStat {
  key: string
  records: number
  qty_column: string
  qty_total: number
  open_count: number
  warehouse_count: number
  domains: CounterItem[]
  columns: string[]
  latest_time: string
}
interface Overview {
  material_count: number
  inbound_qty: number
  outbound_qty: number
  inventory_qty: number
  difference: number
  avg_monthly: number
  safety_stock: number
  replenishment_qty: number
  alerts: CounterItem[]
  remarks: CounterItem[]
  urgent: number
  replenish: number
  excess: number
  failure_rate: number
  actual_consumption: number
}
interface SourceInfo {
  kind: string
  kind_label_en: string
  kind_label_zh: string
  file: string
  path: string
  generated_at: string
  size: number
}
interface MatrixRow {
  day: string
  inbound: number[]
  outbound: number[]
  inbound_total: number
  outbound_total: number
}
interface Matrix {
  label: string
  inbound_warehouses: string[]
  outbound_warehouses: string[]
  rows: MatrixRow[]
  inbound_total: number
  outbound_total: number
}
interface SummaryResp {
  kind: string
  kind_label_en: string
  kind_label_zh: string
  source: SourceInfo
  overview: Overview
  sheets: SheetStat[]
  matrix: Matrix | null
  notes: string[]
  warnings: string[]
  generated_at: string
}
type Row = Record<string, CellValue>
interface RowsResp {
  kind: string
  sheet: string
  columns: string[]
  numeric_columns: string[]
  rows: Row[]
  total: number
  page: number
  page_size: number
  qty_column: string
  qty_total: number
  filtered_qty_total: number
  notes: string[]
  warnings: string[]
}
interface FilterField {
  column: string
  label: string
  options: CounterItem[]
}

// ==================== 表格展示列（常用列；全列在行详情弹窗） ====================
// 按 sheet 声明「优先展示」的列名，实际存在的才会显示（两种报表列集略有差异）。
const DISPLAY_COLUMNS: Record<string, string[]> = {
  'Summary-Current': [
    'Material Name', 'Domain', 'Inbound Qty', 'Outbound Qty', 'Inventory Qty',
    'Difference', 'Avg Monthly Consumption', 'Safety Stock', 'Remark',
    'Replenishment Qty', 'Alert Level',
  ],
  Inbound: [
    'Inbound No.', 'Status', 'Inbound Type', 'Warehouse Name', 'Material No.', 'Serial No.',
    'Material Name', 'Domain', 'Inbound Qty', 'Unit', 'Location No.', 'Inbound Time',
  ],
  Outbound: [
    'Outbound No.', 'Status', 'Warehouse Name', 'Outbound Type', 'Recipient', 'Domain',
    'Related Ticket Type', 'Related Ticket No.', 'Serial No.', 'Material No.', 'Material Name',
    'Outbound Qty', 'Unit', 'Outbound Time', 'Borrow Duration',
  ],
  Inventory: [
    'Serial No.', 'Material No.', 'Material Name', 'Material Status', 'Warehouse Name',
    'Domain', 'Storage Age', 'Stock Qty', 'Unit', 'Location Name',
  ],
}

/** 筛选字段 label -> i18n 文案键 */
const FILTER_LABEL_KEY: Record<string, string> = {
  status: 'spRep.f.status',
  warehouse: 'spRep.f.warehouse',
  domain: 'spRep.f.domain',
  inboundType: 'spRep.f.inboundType',
  outboundType: 'spRep.f.outboundType',
  ticketType: 'spRep.f.ticketType',
  materialStatus: 'spRep.f.materialStatus',
  remark: 'spRep.f.remark',
  alertLevel: 'spRep.f.alertLevel',
}

/** sheet -> i18n 文案键 */
const SHEET_LABEL_KEY: Record<string, string> = {
  'Summary-Current': 'spRep.sheet.summary',
  'Summary-Changed': 'spRep.sheet.daily',
  Inbound: 'spRep.sheet.inbound',
  Outbound: 'spRep.sheet.outbound',
  Inventory: 'spRep.sheet.inventory',
}

/** 告警级别 -> 颜色（与主题 sev 语义对齐） */
const ALERT_COLOR: Record<string, string> = {
  'Urgent Replenish': WH.sev.Critical,
  Replenish: WH.sev.Warning,
  Excess: WH.teal,
}

const EXPORT_MAX_ROWS = 5000
const SEARCH_DEBOUNCE_MS = 350

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

function cellText(v: CellValue, isNum: boolean, loc: string): React.ReactNode {
  if (v === null || v === undefined || v === '') return <Text type="secondary">-</Text>
  if (isNum) return num(v).toLocaleString(loc, { maximumFractionDigits: 2 })
  return String(v)
}

function StatCard(props: {
  label: string
  value: number | string
  unit?: string
  hint?: React.ReactNode
  color?: string
  emphasis?: boolean
}) {
  const { label, value, unit, hint, color, emphasis } = props
  return (
    <div
      /* 卡片皮肤交给 CSS 层（.wh-stat-card），与其余页面的 antd Card 统一走浅色档
         描边+内发光；此前内联的 background/border/borderRadius 会盖过统一层，
         是该组件游离在统一风格之外的根因。emphasis 保留描边强调语义。 */
      className="wh-stat-card"
      style={{
        border: emphasis ? `1px solid ${color || WH.teal}` : undefined,
        padding: '12px 14px',
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ color: WH.textMuted, fontSize: 12, marginBottom: 6, whiteSpace: 'nowrap' }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ color: color || WH.teal, fontSize: 24, fontWeight: 700, lineHeight: 1.15 }}>
          {value}
        </span>
        {unit && <span style={{ color: WH.textDim, fontSize: 12 }}>{unit}</span>}
      </div>
      {hint && (
        <div style={{ color: WH.textDim, fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>{hint}</div>
      )}
    </div>
  )
}

export default function SpReportBase({ kind }: { kind: SpReportKind }) {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const loc = numLocale(locale)

  const [summary, setSummary] = useState<SummaryResp | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState('')

  const [activeSheet, setActiveSheet] = useState('')
  const [rowsResp, setRowsResp] = useState<RowsResp | null>(null)
  const [rowsLoading, setRowsLoading] = useState(false)
  const [rowsError, setRowsError] = useState('')

  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string[]>>({})
  const [filterFields, setFilterFields] = useState<FilterField[]>([])
  const [sort, setSort] = useState('')
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [reloadTick, setReloadTick] = useState(0)

  const [drill, setDrill] = useState<{ row: Row; x: number; y: number } | null>(null)
  const [exporting, setExporting] = useState(false)

  const title = t(kind === 'consumables' ? 'spRep.titleConsumables' : 'spRep.titleSpareParts')

  const sheets = useMemo(() => summary?.sheets ?? [], [summary])
  const activeStat = useMemo(
    () => sheets.find(s => s.key === activeSheet) ?? sheets[0],
    [sheets, activeSheet],
  )

  // ---------- 概览 + 分表元信息 ----------
  const loadSummary = useCallback(() => {
    setSummaryLoading(true)
    getSpReportSummary(kind)
      .then(res => {
        const data = res.data as SummaryResp
        setSummary(data)
        setSummaryError('')
        setActiveSheet(prev => (prev && data.sheets.some(s => s.key === prev)
          ? prev
          : (data.sheets[0]?.key ?? '')))
      })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setSummaryError(String(err?.response?.data?.detail || err?.message || e))
      })
      .finally(() => setSummaryLoading(false))
  }, [kind])

  useEffect(() => { loadSummary() }, [loadSummary])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [search])

  const filtersKey = useMemo(() => JSON.stringify(filters), [filters])
  const prevKey = useRef('')
  useEffect(() => {
    const key = `${activeSheet}|${debouncedSearch}|${filtersKey}`
    if (prevKey.current !== key) {
      prevKey.current = key
      setPage(1)
    }
  }, [activeSheet, debouncedSearch, filtersKey])

  // ---------- 明细数据 ----------
  useEffect(() => {
    if (!activeSheet || activeSheet === 'Summary-Changed') return
    let alive = true
    setRowsLoading(true)
    getSpReportRows({
      kind,
      sheet: activeSheet,
      page,
      page_size: pageSize,
      q: debouncedSearch,
      sort,
      order,
      filters: filtersKey === '{}' ? '' : filtersKey,
    })
      .then(res => {
        if (!alive) return
        const data = res.data as RowsResp
        setRowsResp(data)
        setRowsError(data.warnings?.length ? data.warnings.join('；') : '')
      })
      .catch((e: unknown) => {
        if (!alive) return
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setRowsError(String(err?.response?.data?.detail || err?.message || e))
      })
      .finally(() => { if (alive) setRowsLoading(false) })
    return () => { alive = false }
  }, [kind, activeSheet, page, pageSize, debouncedSearch, sort, order, filtersKey, reloadTick])

  // ---------- 筛选下拉 ----------
  useEffect(() => {
    if (!activeSheet || activeSheet === 'Summary-Changed') {
      setFilterFields([])
      return
    }
    let alive = true
    getSpReportFilters(kind, activeSheet)
      .then(res => {
        if (!alive) return
        const data = res.data as { fields?: FilterField[] }
        setFilterFields(data.fields ?? [])
        setFilters(prev => {
          const cols = new Set((data.fields ?? []).map(f => f.column))
          const next: Record<string, string[]> = {}
          let changed = false
          for (const [k, v] of Object.entries(prev)) {
            if (cols.has(k)) next[k] = v
            else changed = true
          }
          return changed ? next : prev
        })
      })
      .catch(() => { if (alive) setFilterFields([]) })
    return () => { alive = false }
  }, [kind, activeSheet])

  const refreshAll = useCallback(() => {
    loadSummary()
    setReloadTick(x => x + 1)
  }, [loadSummary])

  // ---------- 表格列 ----------
  const numericSet = useMemo(() => new Set(rowsResp?.numeric_columns ?? []), [rowsResp])
  const displayColumns = useMemo(() => {
    const preferred = DISPLAY_COLUMNS[activeSheet] ?? []
    const available = rowsResp?.columns ?? []
    const kept = preferred.filter(c => available.includes(c))
    // 偏好列一个都没命中（例如列名变了）时退回全列，避免表格空白
    return kept.length ? kept : available
  }, [activeSheet, rowsResp])

  const columns = useMemo<ColumnsType<Row>>(() => displayColumns.map(name => ({
    title: name,
    dataIndex: name,
    key: name,
    ellipsis: true,
    align: numericSet.has(name) ? ('right' as const) : undefined,
    sorter: true,
    sortOrder: sort === name ? (order === 'desc' ? ('descend' as const) : ('ascend' as const)) : null,
    render: (v: CellValue) => {
      // Alert Level 用颜色区分补库紧迫度，是这张表最该被一眼看到的信息
      if (name === 'Alert Level' && v) {
        const c = ALERT_COLOR[String(v)] || WH.textMuted
        return <span style={{ color: c, fontWeight: 600 }}>{String(v)}</span>
      }
      return cellText(v, numericSet.has(name), loc)
    },
  })), [displayColumns, numericSet, sort, order, loc])

  // ---------- 导出 ----------
  const exportCurrent = useCallback(async () => {
    if (!activeSheet || !activeStat || activeSheet === 'Summary-Changed') return
    setExporting(true)
    try {
      const total = rowsResp?.total ?? activeStat.records
      const size = Math.max(1, Math.min(total, EXPORT_MAX_ROWS))
      const res = await getSpReportRows({
        kind, sheet: activeSheet, page: 1, page_size: size,
        q: debouncedSearch, sort, order,
        filters: filtersKey === '{}' ? '' : filtersKey,
      })
      const data = res.data as RowsResp
      const cols = displayColumns
      const numericCols: number[] = []
      cols.forEach((c, i) => { if (numericSet.has(c)) numericCols.push(i) })

      const rows: CellValue[][] = data.rows.map(r => cols.map(c => {
        const v = r[c]
        if (v === null || v === undefined) return null
        if (numericSet.has(c)) return num(v)
        return String(v)
      }))
      const totalRow: CellValue[] = cols.map((_c, i) => {
        if (i === 0) return t('spRep.total')
        if (!numericCols.includes(i)) return null
        return rows.reduce((s, row) => s + num(row[i]), 0)
      })

      const kindLabel = kind === 'consumables' ? 'Consumables' : 'SpareParts'
      await exportReport([{
        name: activeSheet,
        title: `${kindLabel} Inbound & Outbound & Inventory - ${t(SHEET_LABEL_KEY[activeSheet] || activeSheet)}`,
        subtitle: `${t('spRep.sourceFile')}: ${summary?.source.file || '-'}    |    `
          + `${t('spRep.filteredRows')}: ${data.total}`,
        tabColor: activeSheet === 'Inventory' ? '#843C0C'
          : activeSheet === 'Inbound' ? '#548235'
            : activeSheet === 'Outbound' ? '#BF8F00' : '#2F5496',
        header: cols,
        rows,
        totalRow,
        numericCols,
      }], `${safeFileName(`${kindLabel} ${activeSheet} Report`)}.xlsx`)
    } catch (e: unknown) {
      const err = e as { message?: string }
      message.error(String(err?.message || e))
    } finally {
      setExporting(false)
    }
  }, [
    kind, activeSheet, activeStat, rowsResp, debouncedSearch, sort, order, filtersKey,
    displayColumns, numericSet, t, summary,
  ])

  // ---------- 卡片 ----------
  const ov = summary?.overview
  const cards = useMemo(() => {
    if (!ov) return []
    return [
      { key: 'materials', label: t('spRep.card.materials'), value: (ov.material_count ?? 0).toLocaleString(loc), hint: t('spRep.hint.materials') },
      { key: 'inbound', label: t('spRep.card.inbound'), value: (ov.inbound_qty ?? 0).toLocaleString(loc), hint: t('spRep.hint.inbound') },
      { key: 'outbound', label: t('spRep.card.outbound'), value: (ov.outbound_qty ?? 0).toLocaleString(loc), hint: t('spRep.hint.outbound') },
      { key: 'inventory', label: t('spRep.card.inventory'), value: (ov.inventory_qty ?? 0).toLocaleString(loc), hint: t('spRep.hint.inventory') },
      {
        key: 'difference',
        label: t('spRep.card.difference'),
        value: (ov.difference ?? 0).toLocaleString(loc),
        hint: t('spRep.hint.difference'),
        color: (ov.difference ?? 0) < 0 ? WH.sev.Critical : WH.teal,
      },
      { key: 'safety', label: t('spRep.card.safetyStock'), value: (ov.safety_stock ?? 0).toLocaleString(loc, { maximumFractionDigits: 2 }), hint: t('spRep.hint.safetyStock') },
      { key: 'replenish', label: t('spRep.card.replenishment'), value: (ov.replenishment_qty ?? 0).toLocaleString(loc), hint: t('spRep.hint.replenishment') },
      {
        key: 'urgent', label: t('spRep.card.urgent'), value: (ov.urgent ?? 0).toLocaleString(loc),
        hint: t('spRep.hint.urgent'),
        color: (ov.urgent ?? 0) > 0 ? WH.sev.Critical : WH.teal,
        emphasis: (ov.urgent ?? 0) > 0,
      },
    ]
  }, [ov, t, loc])

  const drillEntries = useMemo(() => {
    if (!drill) return []
    const cols = rowsResp?.columns ?? Object.keys(drill.row)
    return cols.map(c => [c, drill.row[c]] as [string, CellValue])
  }, [drill, rowsResp])

  const searchInputStyle: React.CSSProperties = {
    background: isDark ? 'rgba(8, 18, 44,0.6)' : '#fff',
    color: isDark ? '#f5f7ff' : '#16233b',
  }

  const matrix = summary?.matrix
  const matrixTotal = (matrix?.inbound_total ?? 0) + (matrix?.outbound_total ?? 0)

  // 每日矩阵（天 × 仓库）—— 它是「明细数据」卡片里 Daily 这个页签的内容，
  // 所以只渲染表格本体，不再单独占一张卡片（见下方明细卡片的 Daily 分支）。
  const matrixNode = useMemo(() => {
    if (!matrix) return <Empty description={t('spRep.dailyPick')} />
    return (
      <>
        <Space wrap style={{ marginBottom: 10 }}>
          <Tag color="cyan">{`Inbound ${matrix.inbound_total.toLocaleString(loc)}`}</Tag>
          <Tag color="orange">{`Outbound ${matrix.outbound_total.toLocaleString(loc)}`}</Tag>
          <Tag>{`${t('spRep.matrixTotal')}: ${matrixTotal.toLocaleString(loc)}`}</Tag>
          <Tag>{`${t('spRep.warehouses')}: ${matrix.inbound_warehouses.length}`}</Tag>
        </Space>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%', minWidth: 720 }}>
            <thead>
              <tr>
                <th rowSpan={2} style={{
                  padding: '6px 8px', color: WH.textMuted, borderBottom: `1px solid ${WH.cardBorder}`,
                  textAlign: 'left', position: 'sticky', left: 0, background: WH.cardBg,
                }}>
                  {matrix.label}
                </th>
                <th colSpan={matrix.inbound_warehouses.length + 1} style={{
                  padding: '4px 8px', color: WH.teal, borderBottom: `1px solid ${WH.cardBorder}`,
                  textAlign: 'center',
                }}>
                  Inbound
                </th>
                <th colSpan={matrix.outbound_warehouses.length + 1} style={{
                  padding: '4px 8px', color: WH.sev.Warning, borderBottom: `1px solid ${WH.cardBorder}`,
                  textAlign: 'center',
                }}>
                  Outbound
                </th>
              </tr>
              <tr>
                {matrix.inbound_warehouses.map(w => (
                  <th key={`ih-${w}`} title={w} style={{
                    padding: '4px 6px', color: WH.textDim, fontSize: 11, fontWeight: 500,
                    borderBottom: `1px solid ${WH.cardBorder}`, maxWidth: 110,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {w}
                  </th>
                ))}
                <th style={{ padding: '4px 6px', color: WH.teal, fontSize: 11, borderBottom: `1px solid ${WH.cardBorder}` }}>
                  {t('spRep.total')}
                </th>
                {matrix.outbound_warehouses.map(w => (
                  <th key={`oh-${w}`} title={w} style={{
                    padding: '4px 6px', color: WH.textDim, fontSize: 11, fontWeight: 500,
                    borderBottom: `1px solid ${WH.cardBorder}`, maxWidth: 110,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {w}
                  </th>
                ))}
                <th style={{ padding: '4px 6px', color: WH.sev.Warning, fontSize: 11, borderBottom: `1px solid ${WH.cardBorder}` }}>
                  {t('spRep.total')}
                </th>
              </tr>
            </thead>
            <tbody>
              {matrix.rows.map(r => {
                const hot = r.inbound_total > 0 || r.outbound_total > 0
                return (
                  <tr key={r.day} style={{ background: hot ? 'var(--wh-teal-20)' : undefined }}>
                    <td style={{
                      padding: '4px 8px', color: WH.text, borderBottom: `1px solid ${WH.cardBorder}`,
                      position: 'sticky', left: 0, background: WH.cardBg,
                    }}>
                      {r.day}
                    </td>
                    {r.inbound.map((v, i) => (
                      <td key={`i-${i}`} style={{
                        padding: '4px 6px', textAlign: 'right', borderBottom: `1px solid ${WH.cardBorder}`,
                        color: v ? WH.text : WH.textDim,
                      }}>
                        {v ? v.toLocaleString(loc) : '0'}
                      </td>
                    ))}
                    <td style={{
                      padding: '4px 6px', textAlign: 'right', borderBottom: `1px solid ${WH.cardBorder}`,
                      color: r.inbound_total ? WH.teal : WH.textDim, fontWeight: 600,
                    }}>
                      {r.inbound_total.toLocaleString(loc)}
                    </td>
                    {r.outbound.map((v, i) => (
                      <td key={`o-${i}`} style={{
                        padding: '4px 6px', textAlign: 'right', borderBottom: `1px solid ${WH.cardBorder}`,
                        color: v ? WH.text : WH.textDim,
                      }}>
                        {v ? v.toLocaleString(loc) : '0'}
                      </td>
                    ))}
                    <td style={{
                      padding: '4px 6px', textAlign: 'right', borderBottom: `1px solid ${WH.cardBorder}`,
                      color: r.outbound_total ? WH.sev.Warning : WH.textDim, fontWeight: 600,
                    }}>
                      {r.outbound_total.toLocaleString(loc)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 8, color: WH.textDim, fontSize: 11 }}>
          {t('spRep.matrixHint')}
        </div>
      </>
    )
  }, [matrix, matrixTotal, loc, t])

  return (
    <div style={{ padding: 16, background: WH.bg, minHeight: '100%' }}>
      {/* ==================== 总览卡片 ==================== */}
      <Card
        title={title}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={refreshAll} loading={summaryLoading}>
              {t('spRep.refresh')}
            </Button>
            <Button
              type="primary" icon={<DownloadOutlined />} onClick={exportCurrent}
              loading={exporting}
              disabled={!activeSheet || activeSheet === 'Summary-Changed' || !(rowsResp?.total)}
            >
              {t('spRep.export')}
            </Button>
          </Space>
        }
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="cyan">{`${t('spRep.sourceFile')}: ${summary?.source.file || '-'}`}</Tag>
          <Tag>{`${t('spRep.dataTime')}: ${summary?.source.generated_at || '-'}`}</Tag>
          <Tag>{`${t('spRep.queryTime')}: ${summary?.generated_at || '-'}`}</Tag>
        </Space>

        {summaryError && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message={t('spRep.loadFailed')} description={summaryError}
          />
        )}
        {!!summary?.warnings?.length && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('spRep.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {summary.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}
          />
        )}

        <Spin spinning={summaryLoading}>
          <Row gutter={[12, 12]}>
            {cards.map(c => (
              <Col key={c.key} xs={12} sm={8} lg={6} xl={3}>
                <StatCard label={c.label} value={c.value} hint={c.hint}
                  color={c.color} emphasis={c.emphasis} />
              </Col>
            ))}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 补库告警 + 分表 ==================== */}
      <Card
        title={t('spRep.alertTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
      >
        <Spin spinning={summaryLoading}>
          <Row gutter={[12, 12]}>
            {([
              { key: 'urgent', label: t('spRep.alert.urgent'), value: ov?.urgent ?? 0, color: WH.sev.Critical, icon: <WarningOutlined /> },
              { key: 'replenish', label: t('spRep.alert.replenish'), value: ov?.replenish ?? 0, color: WH.sev.Warning, icon: <RiseOutlined /> },
              { key: 'excess', label: t('spRep.alert.excess'), value: ov?.excess ?? 0, color: WH.teal, icon: <FallOutlined /> },
              { key: 'failure', label: t('spRep.alert.failureRate'), value: ov?.failure_rate ?? 0, color: WH.textMuted, icon: <InfoCircleOutlined /> },
              { key: 'actual', label: t('spRep.alert.actualConsumption'), value: ov?.actual_consumption ?? 0, color: WH.textMuted, icon: <InfoCircleOutlined /> },
            ]).map(a => (
              <Col key={a.key} xs={12} sm={8} xl={4}>
                <div
                  onClick={() => {
                    // 点击告警卡片 → 切到汇总表并加对应筛选，形成「卡片即筛选入口」
                    const col = a.key === 'failure' || a.key === 'actual' ? 'Remark' : 'Alert Level'
                    const val = a.key === 'urgent' ? 'Urgent Replenish'
                      : a.key === 'replenish' ? 'Replenish'
                        : a.key === 'excess' ? 'Excess'
                          : a.key === 'failure' ? 'Failure Rate' : 'Actual Consumption'
                    setActiveSheet('Summary-Current')
                    setFilters({ [col]: [val] })
                    setSearch('')
                  }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLElement).click() }}
                  style={{
                    background: WH.cardBg, border: WH.cardBorder, borderRadius: 8,
                    padding: '10px 14px', cursor: 'pointer', height: '100%',
                    boxSizing: 'border-box',
                  }}
                >
                  <div style={{ color: WH.textMuted, fontSize: 12, marginBottom: 4 }}>
                    {a.icon} {a.label}
                  </div>
                  <div style={{ color: a.color, fontSize: 20, fontWeight: 700 }}>
                    {a.value.toLocaleString(loc)}
                  </div>
                </div>
              </Col>
            ))}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 分表卡片 ==================== */}
      <Card
        title={t('spRep.sheetCards')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
      >
        <Spin spinning={summaryLoading}>
          <Row gutter={[12, 12]}>
            {sheets.map(s => {
              const active = s.key === activeSheet
              return (
                <Col key={s.key} xs={24} sm={12} xl={6}>
                  <div
                    onClick={() => setActiveSheet(s.key)}
                    role="button" tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setActiveSheet(s.key) }}
                    style={{
                      cursor: 'pointer',
                      background: active ? 'var(--wh-teal-20)' : WH.cardBg,
                      border: active ? `1px solid ${WH.teal}` : WH.cardBorder,
                      borderRadius: 8, padding: '12px 14px', height: '100%',
                      boxSizing: 'border-box',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ color: active ? WH.teal : WH.text, fontWeight: 600 }}>
                        {t(SHEET_LABEL_KEY[s.key] || s.key)}
                      </span>
                      <Tag>{s.records.toLocaleString(loc)}</Tag>
                    </div>
                    {s.qty_column ? (
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                        <span style={{ color: WH.teal, fontSize: 22, fontWeight: 700 }}>
                          {s.qty_total.toLocaleString(loc, { maximumFractionDigits: 2 })}
                        </span>
                        <span style={{ color: WH.textDim, fontSize: 12 }}>{s.qty_column}</span>
                      </div>
                    ) : (
                      <div style={{ color: WH.textDim, fontSize: 12, marginBottom: 6 }}>
                        {t('spRep.dailyHint')}
                      </div>
                    )}
                    <Space size={4} wrap style={{ marginBottom: 6 }}>
                      {s.open_count > 0 && (
                        <Tag color="orange">{`${t('spRep.openCount')} ${s.open_count}`}</Tag>
                      )}
                      {s.domains.slice(0, 3).map(d => (
                        <Tag key={d.value} style={{ marginInlineEnd: 0 }}>
                          {`${d.value} ${d.count}`}
                        </Tag>
                      ))}
                    </Space>
                    <div style={{ color: WH.textDim, fontSize: 11, lineHeight: 1.7 }}>
                      {s.warehouse_count > 0 && (
                        <div>{`${t('spRep.warehouses')}: ${s.warehouse_count}`}</div>
                      )}
                      {s.latest_time && <div>{`${t('spRep.latestTime')}: ${s.latest_time}`}</div>}
                    </div>
                  </div>
                </Col>
              )
            })}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 明细表格（Daily 页签内含每日矩阵） ==================== */}
      <Card title={t('spRep.tableTitle')} style={{ background: WH.cardBg, border: WH.cardBorder }}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Segmented
            value={activeSheet}
            onChange={(v) => setActiveSheet(String(v))}
            options={sheets.map(s => ({
              value: s.key,
              label: `${t(SHEET_LABEL_KEY[s.key] || s.key)} (${s.records.toLocaleString(loc)})`,
            }))}
          />
        </Space>

        {activeSheet === 'Summary-Changed' ? (
          matrixNode
        ) : (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Input
                allowClear
                style={{ width: 260, ...searchInputStyle }}
                prefix={<SearchOutlined style={{ color: WH.textDim }} />}
                placeholder={t('spRep.searchPh')}
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              {filterFields.map(f => (
                <Select
                  key={f.column}
                  mode="multiple"
                  allowClear
                  maxTagCount="responsive"
                  style={{ minWidth: 190, maxWidth: 300 }}
                  placeholder={t(FILTER_LABEL_KEY[f.label] || f.column)}
                  value={filters[f.column] ?? []}
                  onChange={(vals: string[]) => {
                    setFilters(prev => {
                      const next = { ...prev }
                      if (vals && vals.length) next[f.column] = vals
                      else delete next[f.column]
                      return next
                    })
                  }}
                  options={f.options.map(o => ({
                    value: o.value,
                    label: `${o.value} (${o.count.toLocaleString(loc)})`,
                  }))}
                />
              ))}
              {(Object.keys(filters).length > 0 || search) && (
                <Button icon={<CloseCircleOutlined />} onClick={() => { setFilters({}); setSearch('') }}>
                  {t('spRep.reset')}
                </Button>
              )}
              {activeStat?.qty_column && (
                <Tooltip title={t('spRep.qtyTip')}>
                  <Tag color="cyan" style={{ marginInlineStart: 0 }}>
                    {`${activeStat.qty_column}: ${(rowsResp?.filtered_qty_total ?? 0).toLocaleString(loc, { maximumFractionDigits: 2 })}`
                      + (rowsResp && rowsResp.filtered_qty_total !== activeStat.qty_total
                        ? ` / ${activeStat.qty_total.toLocaleString(loc, { maximumFractionDigits: 2 })}` : '')}
                  </Tag>
                </Tooltip>
              )}
              <Tag>
                {`${t('spRep.filteredRows')}: ${(rowsResp?.total ?? 0).toLocaleString(loc)}`
                  + ` / ${(activeStat?.records ?? 0).toLocaleString(loc)}`}
              </Tag>
            </Space>

            {rowsError && (
              <Alert type="error" showIcon style={{ marginBottom: 12 }}
                message={t('spRep.loadFailed')} description={rowsError} />
            )}

            {rowsResp?.rows?.length ? (
              <Table<Row>
                size="small"
                rowKey={(_r, i) => String(i)}
                columns={columns}
                dataSource={rowsResp.rows}
                loading={rowsLoading}
                scroll={{ x: 'max-content' }}
                onRow={(record) => ({
                  onClick: (e) => setDrill({ row: record, x: e.clientX, y: e.clientY }),
                  style: { cursor: 'pointer' },
                })}
                onChange={(_p, _f, sorter) => {
                  const s = Array.isArray(sorter) ? sorter[0] : sorter
                  if (s && s.order && s.columnKey) {
                    setSort(String(s.columnKey))
                    setOrder(s.order === 'descend' ? 'desc' : 'asc')
                  } else {
                    setSort('')
                    setOrder('asc')
                  }
                }}
                pagination={{
                  current: rowsResp.page,
                  pageSize: rowsResp.page_size,
                  total: rowsResp.total,
                  size: 'small',
                  showSizeChanger: true,
                  pageSizeOptions: ['20', '50', '100', '200'],
                  showTotal: (n) => `${n.toLocaleString(loc)} ${t('spRep.rows')}`,
                  onChange: (p, ps) => { setPage(p); setPageSize(ps) },
                }}
              />
            ) : (
              !rowsLoading && (
                <Empty description={rowsError ? t('spRep.loadFailed') : t('spRep.empty')} />
              )
            )}
          </>
        )}

        {/* 报表自带口径说明（原样透传，保证页面与 Excel 一致） */}
        {!!summary?.notes?.length && (
          <div style={{ marginTop: 16, color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
            <div style={{ marginBottom: 4, color: WH.text }}>
              <InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />
              {t('spRep.docTitle')}
            </div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {summary.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </div>
        )}
      </Card>

      {/* ==================== 行详情 ==================== */}
      <DraggableClickModal
        open={!!drill}
        title={(
          <Space wrap>
            <span>{t('spRep.detailTitle')}</span>
            <Tag color="cyan">{activeStat ? t(SHEET_LABEL_KEY[activeStat.key] || activeStat.key) : ''}</Tag>
            <Tag>{`${drillEntries.length} ${t('spRep.columns')}`}</Tag>
          </Space>
        )}
        anchor={drill ? { x: drill.x, y: drill.y } : null}
        onClose={() => setDrill(null)}
        width="92%"
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <tbody>
            {drillEntries.map(([k, v]) => (
              <tr key={k}>
                <td style={{
                  padding: '6px 10px', color: WH.textMuted, whiteSpace: 'nowrap',
                  verticalAlign: 'top', borderBottom: `1px solid ${WH.cardBorder}`, width: 220,
                }}>
                  {k}
                </td>
                <td style={{
                  padding: '6px 10px', color: WH.text, wordBreak: 'break-word',
                  borderBottom: `1px solid ${WH.cardBorder}`,
                }}>
                  {v === null || v === undefined || v === ''
                    ? <Text type="secondary">-</Text> : String(v)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DraggableClickModal>
    </div>
  )
}
