import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Card, Col, Empty, Input, Row, Segmented, Select, Space, Spin, Table, Tag,
  Tooltip, Typography, message,
} from 'antd'
import {
  ReloadOutlined, DownloadOutlined, SearchOutlined, InfoCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { getSpDetailsFilters, getSpDetailsRows, getSpDetailsSummary } from '../api'
import { useI18n, numLocale } from '../i18n'
import { useTheme, WH } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportReport, safeFileName, type CellValue } from '../utils/excelReport'

const { Text } = Typography

/**
 * SP 备件明细报表（page=sp_details）
 *
 * 数据源：任务 `sp_email_details`（SP Spare Parts Details Report Email）每天
 * 生成的合并工作簿 `data/sp_email/data/SP Details Report <时间戳>.xlsx`
 * （sheet：Inventory / Inbound / Outbound / Transfer）—— 页面上看到的就是邮件
 * 附件那份文件，逐行一致；口径见 backend/services/sp_details_service.py。
 *
 * 页面结构：统计卡片（总览 KPI + 分表卡片）+ 明细表格（服务端筛选/排序/分页）。
 * 表格只展示每张表最常用的列，点击任意一行弹出行详情（该 sheet 的全部列）。
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
  qty_rows: number
  open_count: number
  statuses: CounterItem[]
  warehouses: CounterItem[]
  warehouse_count: number
  material_types: CounterItem[]
  domains: CounterItem[]
  types: CounterItem[]
  type_column: string
  distinct_materials: number
  distinct_serials: number
  latest_time: string
  columns: string[]
}
interface Overview {
  total_records: number
  sheet_count: number
  warehouses: number
  distinct_materials: number
  open_tickets: number
  stock_qty: number
  inbound_qty: number
  outbound_qty: number
  transfer_qty: number
}
interface SourceInfo {
  mode: string
  file: string
  path: string
  generated_at: string
  size: number
}
interface SummaryResp {
  source: SourceInfo
  overview: Overview
  sheets: SheetStat[]
  warnings: string[]
  generated_at: string
}
type Row = Record<string, CellValue>
interface RowsResp {
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
  warnings: string[]
}
interface FilterField {
  column: string
  label: string
  options: CounterItem[]
}

// ==================== 表格展示列（每张表最常用的列；全列在行详情里看） ====================
const DISPLAY_COLUMNS: Record<string, string[]> = {
  Inventory: [
    'Serial No.', 'Material No.', 'Material Name', 'Material Type', 'Material Status',
    'Warehouse Name', 'Domain', 'Stock Qty', 'Unit', 'Storage Age', 'Location Name',
    'OwnerShip', 'Reserve Qty', 'Reserve Ticket No.',
  ],
  Inbound: [
    'Inbound No.', 'Status', 'Inbound Type', 'Warehouse Name', 'Material No.', 'Serial No.',
    'Material Name', 'Material Type', 'Inbound Qty', 'Unit', 'Domain', 'Location Name',
    'Material Status', 'Create Time', 'Inbound Time', 'Closed Time',
  ],
  Outbound: [
    'Outbound No.', 'Status', 'Outbound Type', 'Warehouse Name', 'Material No.', 'Serial No.',
    'Material Name', 'Material Type', 'Outbound Qty', 'Unit', 'Domain', 'Related Ticket Type',
    'Related Ticket No.', 'Recipient', 'Create Time', 'Outbound Time', 'Closed Time',
    'Borrow Duration',
  ],
  Transfer: [
    'Warehouse Transfer No.', 'Status', 'Original Warehouse Name', 'Target Warehouse Name',
    'Material No.', 'Material Name', 'Serial No.', 'Material Type', 'Transfer Qty',
    'Stock Qty', 'Remaining Qty', 'Source Location Name', 'Target Location Name',
    'Station Level', 'Create Time', 'Outbound Time', 'Inbound Time',
  ],
}

/** 每张表的 Excel 标签页颜色（与项目 UNIFIED_EXCEL_V1 的 SHEET_TAB_COLORS 同源） */
const SHEET_TAB_COLOR: Record<string, string> = {
  Inventory: '#843C0C',
  Inbound: '#548235',
  Outbound: '#BF8F00',
  Transfer: '#2F5496',
}

/** sheet -> i18n 文案键 */
const SHEET_LABEL_KEY: Record<string, string> = {
  Inventory: 'spDet.sheet.inventory',
  Inbound: 'spDet.sheet.inbound',
  Outbound: 'spDet.sheet.outbound',
  Transfer: 'spDet.sheet.transfer',
  'Transfer Return': 'spDet.sheet.transferReturn',
}

/** 筛选字段 label -> i18n 文案键 */
const FILTER_LABEL_KEY: Record<string, string> = {
  status: 'spDet.f.status',
  warehouse: 'spDet.f.warehouse',
  materialType: 'spDet.f.materialType',
  type: 'spDet.f.type',
  domain: 'spDet.f.domain',
  materialStatus: 'spDet.f.materialStatus',
}

const EXPORT_MAX_ROWS = 5000
const SEARCH_DEBOUNCE_MS = 350

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 数字列右对齐 + 千分位；空值显示灰色占位 */
function cellText(v: CellValue, isNum: boolean, loc: string): React.ReactNode {
  if (v === null || v === undefined || v === '') {
    return <Text type="secondary">-</Text>
  }
  if (isNum) return num(v).toLocaleString(loc)
  return String(v)
}

/** 卡片：标签 + 大数字 + 单位/提示 */
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
      style={{
        background: WH.cardBg,
        border: emphasis ? `1px solid ${color || WH.teal}` : WH.cardBorder,
        borderRadius: 8,
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

export default function SpDetailsReport() {
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

  const sheets = useMemo(() => summary?.sheets ?? [], [summary])
  const activeStat = useMemo(
    () => sheets.find(s => s.key === activeSheet) ?? sheets[0],
    [sheets, activeSheet],
  )

  // ---------- 概览 + 分表元信息 ----------
  const loadSummary = useCallback(() => {
    setSummaryLoading(true)
    getSpDetailsSummary()
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
  }, [])

  useEffect(() => { loadSummary() }, [loadSummary])

  // ---------- 搜索防抖 ----------
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [search])

  // 切换 sheet / 搜索 / 筛选 → 回到第 1 页
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
    if (!activeSheet) return
    let alive = true
    setRowsLoading(true)
    getSpDetailsRows({
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
  }, [activeSheet, page, pageSize, debouncedSearch, sort, order, filtersKey, reloadTick])

  // ---------- 筛选下拉候选值 ----------
  useEffect(() => {
    if (!activeSheet) return
    let alive = true
    getSpDetailsFilters(activeSheet)
      .then(res => {
        if (!alive) return
        const data = res.data as { fields?: FilterField[] }
        setFilterFields(data.fields ?? [])
        // 切表时清掉不属于当前表的筛选条件
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
  }, [activeSheet])

  const refreshAll = useCallback(() => {
    loadSummary()
    setReloadTick(x => x + 1)
  }, [loadSummary])

  // ---------- 表格列 ----------
  const numericSet = useMemo(
    () => new Set(rowsResp?.numeric_columns ?? []),
    [rowsResp],
  )
  const displayColumns = useMemo(
    () => DISPLAY_COLUMNS[activeSheet] ?? rowsResp?.columns ?? [],
    [activeSheet, rowsResp],
  )

  const columns = useMemo<ColumnsType<Row>>(() => {
    return displayColumns.map(name => ({
      title: name,
      dataIndex: name,
      key: name,
      ellipsis: true,
      align: numericSet.has(name) ? ('right' as const) : undefined,
      sorter: true,
      sortOrder: sort === name ? (order === 'desc' ? ('descend' as const) : ('ascend' as const)) : null,
      render: (v: CellValue) => cellText(v, numericSet.has(name), loc),
    }))
  }, [displayColumns, numericSet, sort, order, loc])

  // ---------- 导出当前筛选结果 ----------
  const exportCurrent = useCallback(async () => {
    if (!activeSheet || !activeStat) return
    setExporting(true)
    try {
      const total = rowsResp?.total ?? activeStat.records
      const size = Math.max(1, Math.min(total, EXPORT_MAX_ROWS))
      const res = await getSpDetailsRows({
        sheet: activeSheet,
        page: 1,
        page_size: size,
        q: debouncedSearch,
        sort,
        order,
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

      const qtyIdx = cols.indexOf(activeStat.qty_column)
      const totalRow: CellValue[] = cols.map((_c, i) => {
        if (i === 0) return t('spDet.total')
        if (!numericCols.includes(i)) return null
        return rows.reduce((s, row) => s + num(row[i]), 0)
      })
      if (qtyIdx < 0) totalRow[0] = t('spDet.total')

      const sheetLabel = t(SHEET_LABEL_KEY[activeSheet] || activeSheet)
      await exportReport([{
        name: activeSheet,
        title: `SP Spare Parts Details Report - ${sheetLabel}`,
        subtitle: `${t('spDet.sourceFile')}: ${summary?.source.file || '-'}    |    `
          + `${t('spDet.filteredRows')}: ${data.total}`,
        tabColor: SHEET_TAB_COLOR[activeSheet] || '#2F5496',
        header: cols,
        rows,
        totalRow,
        numericCols,
      }], `${safeFileName(`SP Details Report ${activeSheet}`)}.xlsx`)
    } catch (e: unknown) {
      const err = e as { message?: string }
      message.error(String(err?.message || e))
    } finally {
      setExporting(false)
    }
  }, [
    activeSheet, activeStat, rowsResp, debouncedSearch, sort, order, filtersKey,
    displayColumns, numericSet, t, summary,
  ])

  // ---------- 卡片数据 ----------
  const ov = summary?.overview
  const cards = useMemo(() => ([
    { key: 'records', label: t('spDet.card.records'), value: (ov?.total_records ?? 0).toLocaleString(loc), hint: `${ov?.sheet_count ?? 0} ${t('spDet.sheets')}` },
    { key: 'stock', label: t('spDet.card.stockQty'), value: (ov?.stock_qty ?? 0).toLocaleString(loc), hint: t('spDet.hint.stock') },
    { key: 'inbound', label: t('spDet.card.inboundQty'), value: (ov?.inbound_qty ?? 0).toLocaleString(loc), hint: t('spDet.hint.inbound') },
    { key: 'outbound', label: t('spDet.card.outboundQty'), value: (ov?.outbound_qty ?? 0).toLocaleString(loc), hint: t('spDet.hint.outbound') },
    { key: 'transfer', label: t('spDet.card.transferQty'), value: (ov?.transfer_qty ?? 0).toLocaleString(loc), hint: t('spDet.hint.transfer') },
    { key: 'warehouses', label: t('spDet.card.warehouses'), value: ov?.warehouses ?? 0, hint: t('spDet.hint.warehouses') },
    { key: 'materials', label: t('spDet.card.materials'), value: (ov?.distinct_materials ?? 0).toLocaleString(loc), hint: t('spDet.hint.materials') },
    {
      key: 'open', label: t('spDet.card.openTickets'), value: ov?.open_tickets ?? 0,
      hint: t('spDet.hint.openTickets'), color: (ov?.open_tickets ?? 0) > 0 ? WH.sev.Warning : WH.teal,
      emphasis: (ov?.open_tickets ?? 0) > 0,
    },
  ]), [ov, t, loc])

  const drillEntries = useMemo(() => {
    if (!drill) return []
    const cols = rowsResp?.columns ?? Object.keys(drill.row)
    return cols.map(c => [c, drill.row[c]] as [string, CellValue])
  }, [drill, rowsResp])

  const searchInputStyle: React.CSSProperties = {
    background: isDark ? 'rgba(8, 18, 44,0.6)' : '#fff',
    color: isDark ? '#f5f7ff' : '#16233b',
  }

  return (
    <div style={{ padding: 16, background: WH.bg, minHeight: '100%' }}>
      {/* ==================== 总览统计卡片 ==================== */}
      <Card
        title={t('spDet.title')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={refreshAll} loading={summaryLoading}>
              {t('spDet.refresh')}
            </Button>
            <Button
              type="primary" icon={<DownloadOutlined />}
              onClick={exportCurrent}
              loading={exporting}
              disabled={!activeSheet || !(rowsResp?.total)}
            >
              {t('spDet.export')}
            </Button>
          </Space>
        }
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="cyan">{`${t('spDet.sourceFile')}: ${summary?.source.file || '-'}`}</Tag>
          <Tag>{`${t('spDet.dataTime')}: ${summary?.source.generated_at || '-'}`}</Tag>
          <Tag color={summary?.source.mode === 'merged' ? 'green' : 'orange'}>
            {t(`spDet.mode.${summary?.source.mode || 'merged'}`)}
          </Tag>
          <Tag>{`${t('spDet.queryTime')}: ${summary?.generated_at || '-'}`}</Tag>
        </Space>

        {summaryError && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message={t('spDet.loadFailed')} description={summaryError}
          />
        )}

        {!!summary?.warnings?.length && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('spDet.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {summary.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}
          />
        )}

        <Spin spinning={summaryLoading}>
          <Row gutter={[12, 12]}>
            {cards.map(c => (
              <Col key={c.key} xs={12} sm={8} lg={6} xl={3}>
                <StatCard
                  label={c.label} value={c.value} hint={c.hint}
                  color={c.color} emphasis={c.emphasis}
                />
              </Col>
            ))}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 分表统计卡片（点击切表） ==================== */}
      <Card
        title={t('spDet.sheetCards')}
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
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setActiveSheet(s.key) }}
                    style={{
                      cursor: 'pointer',
                      background: active ? 'var(--wh-teal-20)' : WH.cardBg,
                      border: active ? `1px solid ${WH.teal}` : WH.cardBorder,
                      borderRadius: 8,
                      padding: '12px 14px',
                      height: '100%',
                      boxSizing: 'border-box',
                    }}
                  >
                    <div style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      marginBottom: 8,
                    }}>
                      <span style={{ color: active ? WH.teal : WH.text, fontWeight: 600 }}>
                        {t(SHEET_LABEL_KEY[s.key] || s.key)}
                      </span>
                      <Tag color={SHEET_TAB_COLOR[s.key] ? undefined : 'default'}
                        style={{ borderColor: SHEET_TAB_COLOR[s.key], color: SHEET_TAB_COLOR[s.key], background: 'transparent' }}>
                        {s.records.toLocaleString(loc)}
                      </Tag>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                      <span style={{ color: WH.teal, fontSize: 22, fontWeight: 700 }}>
                        {s.qty_total.toLocaleString(loc)}
                      </span>
                      <span style={{ color: WH.textDim, fontSize: 12 }}>{s.qty_column}</span>
                    </div>

                    <Space size={4} wrap style={{ marginBottom: 6 }}>
                      {s.open_count > 0 && (
                        <Tag color="orange">{`${t('spDet.openCount')} ${s.open_count}`}</Tag>
                      )}
                      {s.material_types.map(m => (
                        <Tag key={m.value} style={{ marginInlineEnd: 0 }}>
                          {`${m.value} ${m.count}`}
                        </Tag>
                      ))}
                    </Space>

                    <div style={{ color: WH.textDim, fontSize: 11, lineHeight: 1.7 }}>
                      <div>{`${t('spDet.warehouses')}: ${s.warehouse_count} · ${t('spDet.materials')}: ${s.distinct_materials}`}</div>
                      {s.latest_time && <div>{`${t('spDet.latestTime')}: ${s.latest_time}`}</div>}
                    </div>
                  </div>
                </Col>
              )
            })}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 明细表格 ==================== */}
      <Card
        title={t('spDet.tableTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder }}
      >
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

        <Space wrap style={{ marginBottom: 12 }}>
          <Input
            allowClear
            style={{ width: 260, ...searchInputStyle }}
            prefix={<SearchOutlined style={{ color: WH.textDim }} />}
            placeholder={t('spDet.searchPh')}
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
            <Button
              icon={<CloseCircleOutlined />}
              onClick={() => { setFilters({}); setSearch('') }}
            >
              {t('spDet.reset')}
            </Button>
          )}
          <Tooltip title={t('spDet.qtyTip')}>
            <Tag color="cyan" style={{ marginInlineStart: 0 }}>
              {`${activeStat?.qty_column || t('spDet.qty')}: `
                + `${(rowsResp?.filtered_qty_total ?? 0).toLocaleString(loc)}`
                + (rowsResp && rowsResp.filtered_qty_total !== activeStat?.qty_total
                  ? ` / ${(activeStat?.qty_total ?? 0).toLocaleString(loc)}` : '')}
            </Tag>
          </Tooltip>
          <Tag>
            {`${t('spDet.filteredRows')}: ${(rowsResp?.total ?? 0).toLocaleString(loc)}`
              + ` / ${(activeStat?.records ?? 0).toLocaleString(loc)}`}
          </Tag>
        </Space>

        {rowsError && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message={t('spDet.loadFailed')} description={rowsError}
          />
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
              showTotal: (n) => `${n.toLocaleString(loc)} ${t('spDet.rows')}`,
              onChange: (p, ps) => { setPage(p); setPageSize(ps) },
            }}
          />
        ) : (
          !rowsLoading && (
            <Empty description={rowsError ? t('spDet.loadFailed') : t('spDet.empty')} />
          )
        )}

        <div style={{ marginTop: 16, color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
          <div style={{ marginBottom: 4, color: WH.text }}>
            <InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />
            {t('spDet.docTitle')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li>{t('spDet.doc1')}</li>
            <li>{t('spDet.doc2')}</li>
            <li>{t('spDet.doc3')}</li>
            <li>{t('spDet.doc4')}</li>
          </ul>
        </div>
      </Card>

      {/* ==================== 行详情（该 sheet 的全部列） ==================== */}
      <DraggableClickModal
        open={!!drill}
        title={(
          <Space wrap>
            <span>{t('spDet.detailTitle')}</span>
            <Tag color="cyan">{activeStat ? t(SHEET_LABEL_KEY[activeStat.key] || activeStat.key) : ''}</Tag>
            <Tag>{`${drillEntries.length} ${t('spDet.columns')}`}</Tag>
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
                  verticalAlign: 'top', borderBottom: `1px solid ${WH.cardBorder}`,
                  width: 220,
                }}>
                  {k}
                </td>
                <td style={{
                  padding: '6px 10px', color: WH.text, wordBreak: 'break-word',
                  borderBottom: `1px solid ${WH.cardBorder}`,
                }}>
                  {v === null || v === undefined || v === ''
                    ? <Text type="secondary">-</Text>
                    : String(v)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DraggableClickModal>
    </div>
  )
}
