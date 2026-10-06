import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Empty, Row, Segmented, Space, Spin, Table, Tag, Tooltip, Typography } from 'antd'
import { ReloadOutlined, DownloadOutlined, InfoCircleOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { getSpReportRows, getSpReportSummary, type SpReportKind } from '../api'
import { useI18n, numLocale } from '../i18n'
import { WH } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportReport, safeFileName, type CellValue } from '../utils/excelReport'

const { Text } = Typography

/**
 * 仓库汇总报表（page=warehouse_summary）
 *
 * 版式对齐 `Task/WarehouseSummaryReport.xlsx`：**页签 = 该文件的两个 sheet**
 * （`Spars Parts` / `Consumables`），每个页签内两段表：
 *
 *   ① WH/DOP 汇总      WH/DOP | Current Inventory | Total Consumption
 *                      | This month Consumption | This week Consumption
 *   ② 高频消耗物料      Domain | Material Name | Consumption Qty
 *                      | Inventory Qty | Alert Level
 *
 * 数据**全部来自已有接口** `/api/sp-report/summary`（`?page=sp_report` /
 * `?page=com_report` 背后的同一份工作簿），不新增数据源、不做二次加工：
 *   - `warehouse_summary`      段①的仓库行 + Total 行（后端口径）
 *   - `frequent_materials`     段②的 Top N + Total 行（后端口径）
 * 口径见 backend/services/sp_report_service.py 顶部 docstring。
 *
 * 下钻：段①的消耗单元格 → Outbound 明细（按仓库 + 时间窗筛）；
 *       段②的物料行   → Summary-Current 明细（按物料名筛）。
 *       下钻端点的筛选字段与概览口径一致（同一 warehouse / material_name），
 *       否则「表格里的数字」与「下钻的行」对不上（AGENTS.md 硬要求）。
 */

// ==================== 类型（与后端 /summary 新增块对齐） ====================
interface WarehouseRow {
  warehouse: string
  current_inventory: number
  total_consumption: number
  month_consumption: number
  week_consumption: number
}
interface FrequentRow {
  domain: string
  material_name: string
  consumption_qty: number
  inventory_qty: number
  alert_level: string
}
interface FrequentBlock {
  rows: FrequentRow[]
  total: { material_name: string; consumption_qty: number; inventory_qty: number } | null
  top_n: number
  consumption_column: string
  material_count: number
}
/** 段① month/week 两列的时间窗起点（后端下发，与概览同一时刻的口径） */
interface PeriodStarts {
  week: string
  month: string
  outbound_time_column: string
}
interface SummaryResp {
  kind: string
  kind_label_en: string
  source: { file: string; generated_at: string }
  warehouse_summary: WarehouseRow[]
  frequent_materials: FrequentBlock
  period_starts: PeriodStarts
  notes: string[]
  warnings: string[]
  generated_at: string
}

type Row = Record<string, CellValue>
interface RowsResp {
  columns: string[]
  rows: Row[]
  total: number
  /** 按当前筛选合计的数量列（用于与概览单元格对账） */
  qty_column?: string
  filtered_qty_total?: number
}

/** 页签（= Excel 的两个 sheet），顺序与 Excel 一致 */
const TABS: { kind: SpReportKind; label: string }[] = [
  { kind: 'spareparts', label: 'Spars Parts' },
  { kind: 'consumables', label: 'Consumables' },
]

/** Alert Level -> 颜色（与 SpReportBase 的语义色一致） */
const ALERT_COLOR: Record<string, string> = {
  'Urgent Replenish': WH.sev.Critical,
  Replenish: WH.sev.Warning,
  Excess: WH.teal,
}

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 空值统一显示 —（不显示成 0，AGENTS.md 原则 6） */
function cellNum(v: unknown, loc: string): React.ReactNode {
  if (v === null || v === undefined || v === '') return <Text type="secondary">—</Text>
  return num(v).toLocaleString(loc, { maximumFractionDigits: 2 })
}

/** 下钻弹窗要查的明细（sheet + 后端 filters 的 JSON + 用于对账的数量口径） */
interface Drill {
  title: string
  sheet: string
  filters: Record<string, string>
  /** 本次下钻对应的时间窗说明（仅 month/week 有；显示在标题里便于核对范围） */
  windowLabel?: string
  /**
   * 该行概览单元格的数字，用于弹窗顶部「合计 vs 概览」对账。
   * ``expectedColumn`` 是它对应的数量列 —— **只有与下钻返回的 `qty_column`
   * 同名时才比较**。段② 的单元格是「消耗量」而 `Summary-Current` 的数量列是
   * `Inventory Qty`，两者本就不是一个口径，硬比会一直亮红（假告警）。
   */
  expected?: number
  expectedColumn?: string
  row: Row | null
  x: number
  y: number
}

export default function WarehouseSummary() {
  const { t, locale } = useI18n()
  const loc = numLocale(locale)

  const [kind, setKind] = useState<SpReportKind>('spareparts')
  const [data, setData] = useState<SummaryResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [drill, setDrill] = useState<Drill | null>(null)
  // 段② 的当前页码：受控，切页签时重置为第 1 页
  // （否则在 spareparts 翻到第 15 页再切 consumables，会直接落在「不足一页」的末页上，
  //   用户会以为新页签只有几行数据）
  const [freqPage, setFreqPage] = useState(1)
  const [drillRows, setDrillRows] = useState<Row[]>([])
  const [drillCols, setDrillCols] = useState<string[]>([])
  /** 下钻结果按当前筛选合计的数量（用于与概览单元格对账），null = 该 sheet 无数量列 */
  const [drillQty, setDrillQty] = useState<{ column: string; total: number } | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState('')
  const [exporting, setExporting] = useState(false)

  // ---------- 取数（页签切换即重新取 /summary） ----------
  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    getSpReportSummary(kind)
      .then(res => {
        if (!alive) return
        setData(res.data as SummaryResp)
        setError('')
      })
      .catch((e: unknown) => {
        if (!alive) return
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setError(String(err?.response?.data?.detail || err?.message || e))
        setData(null)
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [kind])

  useEffect(() => load(), [load])

  // ---------- 下钻：拉明细 ----------
  useEffect(() => {
    if (!drill) return
    let alive = true
    setDrillLoading(true)
    setDrillError('')
    getSpReportRows({
      kind,
      sheet: drill.sheet,
      page: 1,
      page_size: 200,
      filters: JSON.stringify(drill.filters),
    })
      .then(res => {
        if (!alive) return
        const d = res.data as RowsResp & { warnings?: string[] }
        setDrillRows(d.rows ?? [])
        setDrillCols(d.columns ?? [])
        setDrillQty(d.qty_column
          ? { column: d.qty_column, total: d.filtered_qty_total ?? 0 }
          : null)
        setDrillError(d.warnings?.length ? d.warnings.join('；') : '')
      })
      .catch((e: unknown) => {
        if (!alive) return
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setDrillError(String(err?.response?.data?.detail || err?.message || e))
        setDrillRows([])
        setDrillQty(null)
      })
      .finally(() => { if (alive) setDrillLoading(false) })
    return () => { alive = false }
  }, [drill, kind])

  const warehouses = data?.warehouse_summary ?? []
  // 后端已把 Total 行放在首位；显式再确认一次，避免上游结构调整时把合计行当仓库渲染
  const totalRow = useMemo(
    () => warehouses.find(w => w.warehouse.toLowerCase() === 'total') ?? null,
    [warehouses],
  )
  const warehouseRows = useMemo(
    () => warehouses.filter(w => w.warehouse.toLowerCase() !== 'total'),
    [warehouses],
  )
  const frequent = data?.frequent_materials

  // ---------- 段①：WH/DOP 汇总 ----------
  const openDrill = useCallback((d: Omit<Drill, 'x' | 'y'> & { x?: number; y?: number }) => {
    setDrill({ ...d, x: d.x ?? window.innerWidth / 2, y: d.y ?? 120 })
  }, [])

  const warehouseColumns = useMemo<ColumnsType<WarehouseRow>>(() => {
    // 消耗列点得动：落到 Outbound 明细，按仓库 + 对应时间窗筛。
    //
    // ⚠️ 时间窗条件必须与概览**同一时刻**的口径：起点由后端 `period_starts` 下发
    //    （`month/week` 两列的合计就是用它算的），前端不复算 —— 前端自己取
    //    「本周一 00:00」会在跨零点/跨周的两次请求间错位，下钻行数就与单元格对不上。
    //    下钻端点按 `Outbound Time@gte` 走与概览一致的「Outbound Time → Create Time」
    //    回落取值，因此三方（单元格 / 概览口径 / 下钻行）逐条同源（AGENTS.md 三.1b 下钻铁律）。
    const starts = data?.period_starts
    const timeCol = starts?.outbound_time_column || 'Outbound Time'

    const qtyCol = (
      title: string, key: keyof WarehouseRow, window?: 'week' | 'month',
    ): ColumnsType<WarehouseRow>[number] => ({
      title,
      dataIndex: key as string,
      key: key as string,
      align: 'right',
      render: (v: number, r: WarehouseRow) => {
        const buildFilters = (): Record<string, string> => {
          const f: Record<string, string> = { 'Warehouse Name': r.warehouse }
          // Total 列不带时间窗（口径＝该仓全部出库，与单元格精确相等）
          const start = window ? starts?.[window] : ''
          if (start) f[`${timeCol}@gte`] = start
          return f
        }
        const label = window === 'week'
          ? t('whSum.window.week')
          : window === 'month' ? t('whSum.window.month') : ''
        const open = (x?: number, y?: number) => openDrill({
          title: `${r.warehouse} · ${title}`,
          sheet: 'Outbound',
          filters: buildFilters(),
          windowLabel: label ? `${label}: ${starts?.[window!] ?? '-'}` : undefined,
          expected: num(v),
          expectedColumn: 'Outbound Qty',
          row: null, x, y,
        })
        return (
          <Tooltip title={t('whSum.drill.hint')}>
            <span
              role="button"
              tabIndex={0}
              style={{ cursor: 'pointer', color: WH.teal, fontWeight: 600 }}
              onClick={e => open(e.clientX, e.clientY)}
              onKeyDown={(e) => { if (e.key === 'Enter') open() }}
            >
              {cellNum(v, loc)}
            </span>
          </Tooltip>
        )
      },
    })

    return [
      {
        title: 'WH/DOP',
        dataIndex: 'warehouse',
        key: 'warehouse',
        ellipsis: true,
        render: (v: string, r: WarehouseRow) => (
          <span
            role="button"
            tabIndex={0}
            style={{ cursor: 'pointer', color: WH.text }}
            onClick={e => openDrill({
              title: `${v} · ${t('whSum.col.inventory')}`,
              sheet: 'Inventory',
              filters: { 'Warehouse Name': r.warehouse },
              expected: num(r.current_inventory),
              expectedColumn: 'Stock Qty',
              row: null,
              x: e.clientX, y: e.clientY,
            })}
          >
            {v || '—'}
          </span>
        ),
      },
      {
        title: t('whSum.col.inventory'),
        dataIndex: 'current_inventory',
        key: 'current_inventory',
        align: 'right' as const,
        render: (v: number, r: WarehouseRow) => (
          <span
            role="button" tabIndex={0}
            style={{ cursor: 'pointer', color: WH.teal, fontWeight: 600 }}
            onClick={e => openDrill({
              title: `${r.warehouse} · ${t('whSum.col.inventory')}`,
              sheet: 'Inventory',
              filters: { 'Warehouse Name': r.warehouse },
              expected: num(v),
              expectedColumn: 'Stock Qty',
              row: null, x: e.clientX, y: e.clientY,
            })}
          >
            {cellNum(v, loc)}
          </span>
        ),
      },
      qtyCol(t('whSum.col.totalConsumption'), 'total_consumption'),
      qtyCol(t('whSum.col.monthConsumption'), 'month_consumption', 'month'),
      qtyCol(t('whSum.col.weekConsumption'), 'week_consumption', 'week'),
    ]
  }, [t, loc, openDrill, data?.period_starts])

  // ---------- 段②：高频消耗物料 ----------
  const frequentColumns = useMemo<ColumnsType<FrequentRow>>(() => [
    { title: t('whSum.col.domain'), dataIndex: 'domain', key: 'domain', width: 110,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    {
      title: t('whSum.col.materialName'), dataIndex: 'material_name', key: 'material_name',
      ellipsis: true,
      render: (v: string, r: FrequentRow) => (
        <span
          role="button" tabIndex={0}
          style={{ cursor: 'pointer', color: WH.text }}
          onClick={e => openDrill({
            title: r.material_name,
            sheet: 'Summary-Current',
            filters: { 'Material Name': r.material_name },
            // 不做「合计 vs 概览」对账：这里的单元格是**消耗量**（Outbound Site Qty），
            // 而 Summary-Current 的数量列是 Inventory Qty，两者不同口径。
            row: null, x: e.clientX, y: e.clientY,
          })}
        >
          {v || '—'}
        </span>
      ),
    },
    { title: t('whSum.col.consumptionQty'), dataIndex: 'consumption_qty', key: 'consumption_qty',
      align: 'right' as const,
      render: (v: number) => <span style={{ color: WH.teal, fontWeight: 600 }}>{cellNum(v, loc)}</span> },
    { title: t('whSum.col.inventoryQty'), dataIndex: 'inventory_qty', key: 'inventory_qty',
      align: 'right' as const, render: (v: number) => cellNum(v, loc) },
    {
      title: t('whSum.col.alertLevel'), dataIndex: 'alert_level', key: 'alert_level', width: 150,
      render: (v: string) => (v
        ? <span style={{ color: ALERT_COLOR[v] || WH.textMuted, fontWeight: 600 }}>{v}</span>
        : <Text type="secondary">—</Text>),
    },
  ], [t, loc, openDrill])

  // ---------- 导出 ----------
  const exportAll = useCallback(async () => {
    if (!data) return
    setExporting(true)
    try {
      const whRows: CellValue[][] = [
        ...(totalRow ? [[
          totalRow.warehouse, totalRow.current_inventory, totalRow.total_consumption,
          totalRow.month_consumption, totalRow.week_consumption,
        ]] : []),
        ...warehouseRows.map(r => [
          r.warehouse, r.current_inventory, r.total_consumption,
          r.month_consumption, r.week_consumption,
        ]),
      ]
      const fqRows: CellValue[][] = [
        ...(frequent?.total ? [[
          '', frequent.total.material_name, frequent.total.consumption_qty,
          frequent.total.inventory_qty, '',
        ]] : []),
        ...(frequent?.rows ?? []).map(r => [
          r.domain, r.material_name, r.consumption_qty, r.inventory_qty, r.alert_level,
        ]),
      ]
      const kindLabel = TABS.find(x => x.kind === kind)?.label ?? kind

      await exportReport([
        {
          name: kindLabel,
          title: `${kindLabel} Inventory Consumption Summary Report`,
          subtitle: `${t('whSum.sourceFile')}: ${data.source.file || '-'}    |    `
            + `${t('whSum.queryTime')}: ${data.generated_at}`,
          tabColor: kind === 'consumables' ? '#843C0C' : '#2F5496',
          header: [
            'WH/DOP', t('whSum.col.inventory'), t('whSum.col.totalConsumption'),
            t('whSum.col.monthConsumption'), t('whSum.col.weekConsumption'),
          ],
          rows: whRows,
          numericCols: [1, 2, 3, 4],
        },
        {
          name: `${kindLabel} - Frequent`,
          title: `Frequency Used ${kindLabel}`,
          subtitle: `${t('whSum.sourceFile')}: ${data.source.file || '-'}`,
          tabColor: '#548235',
          header: [
            t('whSum.col.domain'), t('whSum.col.materialName'), t('whSum.col.consumptionQty'),
            t('whSum.col.inventoryQty'), t('whSum.col.alertLevel'),
          ],
          rows: fqRows,
          numericCols: [2, 3],
        },
      ], `${safeFileName(`Warehouse Summary ${kindLabel}`)}.xlsx`)
    } finally {
      setExporting(false)
    }
  }, [data, totalRow, warehouseRows, frequent, kind, t])

  const drillColumns = useMemo<ColumnsType<Row>>(
    () => drillCols.map(c => ({
      title: c, dataIndex: c, key: c, ellipsis: true,
      render: (v: CellValue) => (v === null || v === undefined || v === ''
        ? <Text type="secondary">—</Text> : String(v)),
    })),
    [drillCols],
  )

  const kpis = useMemo(() => ([
    { key: 'inv', label: t('whSum.kpi.inventory'), value: totalRow?.current_inventory ?? null },
    { key: 'total', label: t('whSum.kpi.totalConsumption'), value: totalRow?.total_consumption ?? null },
    { key: 'month', label: t('whSum.kpi.monthConsumption'), value: totalRow?.month_consumption ?? null },
    { key: 'week', label: t('whSum.kpi.weekConsumption'), value: totalRow?.week_consumption ?? null },
    { key: 'materials', label: t('whSum.kpi.materials'), value: frequent?.material_count ?? null },
    { key: 'urgent', label: t('whSum.kpi.urgent'),
      value: (frequent?.rows ?? []).filter(r => r.alert_level === 'Urgent Replenish').length },
  ]), [totalRow, frequent, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ==================== 页签 + 数据源 ==================== */}
      <CardBase
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('whSum.refresh')}
            </Button>
            <Button type="primary" icon={<DownloadOutlined />} onClick={exportAll}
              loading={exporting} disabled={!data}>
              {t('whSum.export')}
            </Button>
          </Space>
        }
      >
        {/* 页签 = Excel 的两个 sheet；名称保持报表原值不翻译。
            加粗居中：与 Excel sheet 标签的视觉权重一致（用户明确要求）。
            数据来源/生成时间/查询时间三个 Tag 已按用户要求移除，
            同样的信息仍在「导出 Excel」的表头与页面口径说明里。 */}
        <div style={{ textAlign: 'center', marginBottom: 12 }}>
          <Segmented
            className="wh-sum-tabs"
            value={kind}
            onChange={v => {
              setKind(v as SpReportKind)
              setFreqPage(1)   // 段② 回到第 1 页
              setDrill(null)   // 关掉属于旧 kind 的下钻弹窗，避免明细与页签不符
            }}
            options={TABS.map(x => ({ value: x.kind, label: x.label }))}
          />
        </div>

        {error && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message={t('whSum.loadFailed')}
            description={
              <>
                {error}
                <div style={{ marginTop: 6, fontSize: 12 }}>{t('whSum.taskHint')}</div>
              </>
            }
          />
        )}
        {!!data?.warnings?.length && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('whSum.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {data.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}
          />
        )}

        <Spin spinning={loading}>
          <Row gutter={[12, 12]}>
            {kpis.map(k => (
              <Col key={k.key} xs={12} sm={8} xl={4}>
                <StatCard title={k.label} value={k.value === null ? '—' : k.value} />
              </Col>
            ))}
          </Row>
        </Spin>
      </CardBase>

      {/* ==================== 段① WH/DOP 汇总 ==================== */}
      <CardBase title={t('whSum.whTitle')} extra={
        <Text type="secondary" style={{ fontSize: 12 }}>{t('whSum.whHint')}</Text>
      }>
        <Spin spinning={loading}>
          {warehouseRows.length || totalRow ? (
            <Table<WarehouseRow>
              size="small"
              rowKey={r => r.warehouse}
              columns={warehouseColumns}
              dataSource={warehouseRows}
              pagination={false}
              scroll={{ x: 'max-content' }}
              summary={() => (totalRow ? (
                <Table.Summary.Row style={{ fontWeight: 700, background: 'var(--wh-teal-20)' }}>
                  <Table.Summary.Cell index={0}>
                    <span style={{ color: WH.text, fontWeight: 700 }}>{totalRow.warehouse}</span>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={1} align="right">
                    <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(totalRow.current_inventory, loc)}</span>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={2} align="right">
                    <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(totalRow.total_consumption, loc)}</span>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={3} align="right">
                    <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(totalRow.month_consumption, loc)}</span>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={4} align="right">
                    <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(totalRow.week_consumption, loc)}</span>
                  </Table.Summary.Cell>
                </Table.Summary.Row>
              ) : null)}
            />
          ) : (!loading && <Empty description={error ? t('whSum.loadFailed') : t('whSum.empty')} />)}
        </Spin>
      </CardBase>

      {/* ==================== 段② 高频消耗物料 ==================== */}
      <CardBase
        title={`${t('whSum.freqTitle')} · ${TABS.find(x => x.kind === kind)?.label ?? ''}`}
        extra={
          <Space wrap size={4}>
            <Tag color="cyan">{`${t('whSum.consumptionBy')}: ${frequent?.consumption_column || '-'}`}</Tag>
            <Tooltip title={t('whSum.freqHint')}>
              <Tag icon={<InfoCircleOutlined />}>
                {`${frequent?.rows.length ?? 0} / ${frequent?.material_count ?? 0}`}
              </Tag>
            </Tooltip>
          </Space>
        }
      >
        <Spin spinning={loading}>
          {frequent?.rows?.length ? (
            <>
              <Table<FrequentRow>
                size="small"
                rowKey={r => `${r.domain}|${r.material_name}`}
                columns={frequentColumns}
                dataSource={frequent.rows}
                pagination={{
                  // 每 10 行一页，显示全部物料（后端已返回全量 rows）
                  current: freqPage,
                  onChange: (p) => setFreqPage(p),
                  pageSize: 10,
                  size: 'small',
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  showTotal: (total, range) =>
                    `${range[0]}-${range[1]} / ${total}`,
                }}
                scroll={{ x: 'max-content' }}
                summary={() => (frequent.total ? (
                  <Table.Summary.Row style={{ fontWeight: 700, background: 'var(--wh-teal-20)' }}>
                    <Table.Summary.Cell index={0} />
                    <Table.Summary.Cell index={1}>
                      <span style={{ color: WH.text, fontWeight: 700 }}>{frequent.total.material_name}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={2} align="right">
                      <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(frequent.total.consumption_qty, loc)}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={3} align="right">
                      <span style={{ color: WH.text, fontWeight: 700 }}>{cellNum(frequent.total.inventory_qty, loc)}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={4} />
                  </Table.Summary.Row>
                ) : null)}
              />
              <div style={{ marginTop: 8, color: WH.textDim, fontSize: 11, lineHeight: 1.7 }}>
                {t('whSum.freqTotalNote', { m: frequent.material_count })}
              </div>
            </>
          ) : (!loading && <Empty description={error ? t('whSum.loadFailed') : t('whSum.empty')} />)}
        </Spin>
      </CardBase>

      {/* ==================== 报表口径说明（原样透传） ==================== */}
      {!!data?.notes?.length && (
        <CardBase title={t('whSum.docTitle')}>
          <div style={{ color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {data.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </div>
        </CardBase>
      )}

      {/* ==================== 下钻弹窗 ==================== */}
      <DraggableClickModal
        open={!!drill}
        title={(
          <Space wrap>
            <span>{drill?.title}</span>
            {drill && <Tag color="cyan">{drill.sheet}</Tag>}
            <Tag>{`${drillRows.length} ${t('whSum.rows')}`}</Tag>
            {/* 合计与概览对账：**仅当数量列同名时**才比较（口径不同比了就是假告警）；
                相等亮绿、不等亮红，避免"看起来对、其实错" */}
            {drillQty && (() => {
              const sameCaliber = !!drill?.expectedColumn
                && drill.expectedColumn === drillQty.column
                && drill?.expected !== undefined
              const matched = !sameCaliber || Math.abs(drillQty.total - drill!.expected!) < 0.01
              const fmt = (n: number) => n.toLocaleString(loc, { maximumFractionDigits: 2 })
              return (
                <Tag color={matched ? (sameCaliber ? 'green' : 'default') : 'red'}>
                  {`${drillQty.column} ${t('whSum.drill.total')} ${fmt(drillQty.total)}`}
                  {sameCaliber && ` / ${t('whSum.drill.cell')} ${fmt(drill!.expected!)}`}
                </Tag>
              )
            })()}
          </Space>
        )}
        anchor={drill ? { x: drill.x, y: drill.y } : null}
        onClose={() => setDrill(null)}
        width="92%"
      >
        {drillError && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('whSum.drillWarn')} description={drillError} />
        )}
        {/* 时间窗说明：让"这个数字是哪一段时间的"一眼可见 */}
        {drill?.windowLabel && (
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message={`${t('whSum.drill.window')}: ${drill.windowLabel}`} />
        )}
        <Table<Row>
          size="small"
          rowKey={(_r, i) => String(i)}
          columns={drillColumns}
          dataSource={drillRows}
          loading={drillLoading}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, size: 'small', showSizeChanger: true }}
        />
        {!drillLoading && !drillRows.length && (
          <Empty description={t('whSum.empty')} />
        )}
      </DraggableClickModal>
    </div>
  )
}
