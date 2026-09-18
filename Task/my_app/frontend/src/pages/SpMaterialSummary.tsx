import {
  useCallback, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent,
} from 'react'
import {
  Alert, Button, Card, DatePicker, Empty, Space, Spin, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import {
  ReloadOutlined, DownloadOutlined, InfoCircleOutlined, SearchOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { getSpMaterialDetail, getSpMaterialSummary } from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportReport, safeFileName, type CellValue, type HeaderCell } from '../utils/excelReport'

const { Text } = Typography

/**
 * SP 物料库存与消耗统计汇总（WH/DOP 报表）
 *
 * 数据源：db/app.db -> inventory_details（每日全量快照，由 SP 数据同步任务写入）
 * 口径：见 backend/services/sp_material_summary_service.py 顶部 docstring
 *   - 期初 / 当前 两列 = SUM(Stock Qty)，Spare Part 只算 Material Status != 'damage'
 *   - Need Repair       = 当前快照 Material Status = 'damage' 的合计
 *   - Total Consumption = 期初合计 − 当前合计（三个窗口：锚点日 / 本月 / 本周）
 *
 * 表头刻意保持英文原词（与报表模板逐列对应），界面文案走 i18n。
 */

// ==================== 类型（与后端 service 返回结构对齐） ====================
interface WarehouseRef {
  warehouse_id: string
  warehouse_name: string
}
interface RowGroup {
  key: string
  label: string
  warehouses: WarehouseRef[]
}
interface SummaryRow {
  key: string
  label: string
  is_total?: boolean
  anchor_spare_good: number
  anchor_consumables: number
  current_spare_good: number
  current_consumables: number
  need_repair: number
  /** 当月 1 号 00:00:00 → 现在，outband_details 里 Repair Outbound 的出库件数 */
  repair_outbound: number
  // 三个消耗窗口 × 两个物料大类（拆分后相加 = 下面的整列合计）
  consumption_from_anchor_spare: number
  consumption_from_anchor_cons: number
  consumption_month_spare: number
  consumption_month_cons: number
  consumption_week_spare: number
  consumption_week_cons: number
  // 整列合计（保留，与拆分列互为校验）
  consumption_from_anchor: number
  consumption_month: number
  consumption_week: number
  anchor_total: number
  current_total: number
}
interface SummaryResp {
  anchor_date: string
  anchor_date_requested?: string
  current_date: string
  month_start: string
  week_start: string
  latest_snapshot?: string
  /** Repair Outbound 列的统计窗口（当月 1 号 00:00:00 → 现在） */
  repair_outbound_start?: string
  repair_outbound_end?: string
  row_groups: RowGroup[]
  rows: SummaryRow[]
  warnings: string[]
  generated_at: string
}

/** 可下钻的格子：scope 与后端 _SCOPES / _CONSUMPTION_SCOPES / repair_outbound 对齐 */
type Scope =
  | 'anchor_spare_good' | 'anchor_consumables'
  | 'current_spare_good' | 'current_consumables'
  | 'need_repair'
  | 'repair_outbound'
  | 'consumption_from_anchor_spare' | 'consumption_from_anchor_cons'
  | 'consumption_month_spare' | 'consumption_month_cons'
  | 'consumption_week_spare' | 'consumption_week_cons'

// 表头文案键（英文原词，与报表模板一致；仍走 t() 便于将来统一改词）
const K_WH = 'spMat.whDop'
const K_SPARE = 'spMat.spareGood'
const K_CONS = 'spMat.consumables'
const K_REPAIR = 'spMat.needRepair'
const K_OB = 'spMat.repairOutbound'
const K_SPARE_PLAIN = 'spMat.sparePart'
const K_FROM = 'spMat.consFrom'
const K_MONTH = 'spMat.consMonth'
const K_WEEK = 'spMat.consWeek'

// 下钻弹窗标题用：scope -> 列文案键
const SCOPE_LABEL: Record<Scope, string> = {
  anchor_spare_good: K_SPARE,
  anchor_consumables: K_CONS,
  current_spare_good: K_SPARE,
  current_consumables: K_CONS,
  need_repair: K_REPAIR,
  repair_outbound: K_OB,
  consumption_from_anchor_spare: K_SPARE_PLAIN,
  consumption_from_anchor_cons: K_CONS,
  consumption_month_spare: K_SPARE_PLAIN,
  consumption_month_cons: K_CONS,
  consumption_week_spare: K_SPARE_PLAIN,
  consumption_week_cons: K_CONS,
}

// 合计行底色（深浅主题各自生效）
const TOTAL_ROW_CSS = `
.sp-mat-total-row > td { background: var(--wh-teal-20) !important; font-weight: 600; }
`

/**
 * 兼容两种响应形态，避免后端包装层变化把整页打成空白：
 *  - 平铺对象（项目主流惯例：site_availability / ran_cells_kpi 直接返回业务对象）
 *  - {status:'success', data:{...}} 旧包装
 * 判定依据：外层有 data 对象、且自身没有业务字段（rows / columns）时才剥壳。
 */
function unwrapPayload<T extends object>(payload: unknown): T {
  const p = payload as Record<string, unknown> | null | undefined
  if (
    p && typeof p === 'object'
    && p.data && typeof p.data === 'object'
    && !('rows' in p) && !('columns' in p)
  ) {
    return p.data as T
  }
  return payload as T
}

export default function SpMaterialSummary() {
  const { t, locale } = useI18n()
  // 后端按 lang 组装 warnings 文案（'en' 走英文），切语言时需重新拉取
  const lang = locale === 'en' ? 'en' : 'zh'
  const { isDark } = useTheme()

  const [data, setData] = useState<SummaryResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // 用户显式选择的锚点日；空串 = 用后端默认（当前快照所在自然月 1 号）
  const [anchorInput, setAnchorInput] = useState('')

  // ---- 下钻弹窗 ----
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillTitle, setDrillTitle] = useState('')
  const [drillRows, setDrillRows] = useState<Record<string, unknown>[]>([])
  const [drillCols, setDrillCols] = useState<string[]>([])
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillWarn, setDrillWarn] = useState<string[]>([])
  const [drillSearch, setDrillSearch] = useState('')
  const [anchorPos, setAnchorPos] = useState<{ x: number; y: number } | null>(null)

  // 合计行样式注入一次
  useEffect(() => {
    if (document.getElementById('sp-mat-style')) return
    const style = document.createElement('style')
    style.id = 'sp-mat-style'
    style.textContent = TOTAL_ROW_CSS
    document.head.appendChild(style)
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params: Record<string, string> = { lang }
      if (anchorInput) params.anchor_date = anchorInput
      const r = await getSpMaterialSummary(params)
      setData(unwrapPayload<SummaryResp>(r.data))
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err?.response?.data?.detail || err?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [anchorInput, lang])

  useEffect(() => { load() }, [load])

  const anchorDate = data?.anchor_date || ''
  const currentDate = data?.current_date || ''

  // ---- 单元格下钻 ----
  const openDrill = useCallback(async (
    rowKey: string, rowLabel: string, scope: Scope, e: ReactMouseEvent,
  ) => {
    setAnchorPos({ x: e.clientX, y: e.clientY })
    setDrillOpen(true)
    setDrillLoading(true)
    setDrillRows([]); setDrillCols([]); setDrillWarn([]); setDrillSearch('')
    setDrillTitle(`${rowLabel} · ${t(SCOPE_LABEL[scope])}`)
    try {
      const params: Record<string, string> = { row_key: rowKey, scope, lang }
      if (anchorInput) params.anchor_date = anchorInput
      const r = await getSpMaterialDetail(params)
      const d = unwrapPayload<{
        title?: string; data?: unknown[]; columns?: string[]; warnings?: string[]
      }>(r.data)
      setDrillTitle(d?.title || rowLabel)
      setDrillRows((d?.data || []) as Record<string, unknown>[])
      setDrillCols((d?.columns || []) as string[])
      setDrillWarn((d?.warnings || []) as string[])
    } catch {
      setDrillWarn([t('spMat.detailFailed')])
    } finally {
      setDrillLoading(false)
    }
  }, [anchorInput, t, lang])

  // ---- 下钻明细：客户端跨字段搜索 ----
  const filteredDrill = useMemo(() => {
    const kw = drillSearch.trim().toLowerCase()
    if (!kw) return drillRows
    return drillRows.filter(r =>
      drillCols.some(c => String(r[c] ?? '').toLowerCase().includes(kw)))
  }, [drillRows, drillCols, drillSearch])

  const drillColumns: ColumnsType<Record<string, unknown>> = useMemo(
    () => drillCols.map(c => ({
      title: c, dataIndex: c, key: c, ellipsis: true, width: 160,
      render: (v: unknown) => (v == null || v === '' ? <Text type="secondary">-</Text> : String(v)),
    })),
    [drillCols],
  )

  // 数字渲染（可下钻 / 负数告警色）
  const renderNum = useCallback((
    v: number, row: SummaryRow, scope: Scope,
  ) => {
    const val = Number(v ?? 0)
    return (
      <Tooltip title={t('spMat.clickHint')}>
        <span
          onClick={(e) => openDrill(row.key, row.label, scope, e)}
          style={{
            cursor: 'pointer',
            color: val ? WH.teal : WH.textDim,
            fontWeight: val ? 600 : 400,
            borderBottom: `1px dotted ${val ? WH.teal : WH.textDim}`,
            paddingBottom: 1,
          }}
        >
          {val}
        </span>
      </Tooltip>
    )
  }, [openDrill, t])

  // 消耗数字：可下钻（期初 vs 期末逐物料对比），负值用告警色
  const renderConsumption = useCallback((v: number, row: SummaryRow, scope: Scope) => {
    const val = Number(v ?? 0)
    const color = val < 0 ? WH.sev.Warning : (val ? WH.text : WH.textDim)
    return (
      <Tooltip title={t('spMat.clickHint')}>
        <span
          onClick={(e) => openDrill(row.key, row.label, scope, e)}
          style={{
            cursor: 'pointer',
            color,
            fontWeight: val ? 600 : 400,
            borderBottom: `1px dotted ${val ? color : WH.textDim}`,
            paddingBottom: 1,
          }}
        >
          {val}
        </span>
      </Tooltip>
    )
  }, [openDrill, t])

  // ---- 导出 Excel ----
  // 采用项目统一格式 UNIFIED_EXCEL_V1（见 utils/excelReport.ts）：
  //   第 1 行标题 / 第 2 行灰字生成信息 / 两行合并表头（深蓝 #2F5496）/
  //   隔行底纹 / Total 行浅蓝底 / 冻结表头 / 自动筛选 / 列宽自适应
  // 与邮件报表 backend/services/sp_report_gen/gernarate_sp_report.py 同一套视觉规范。
  const exportExcel = useCallback(() => {
    if (!data?.rows?.length) return
    // 13 列：WH/DOP | 期初(2) | 当前(2) | Need Repair | Repair Outbound | 3 个消耗窗口 × (2)
    const head: HeaderCell[][] = [
      [
        { text: t(K_WH), rowSpan: 2 },
        { text: anchorDate, colSpan: 2 },
        { text: t('spMat.currentDate'), colSpan: 2 },
        { text: t(K_REPAIR), rowSpan: 2 },
        { text: t(K_OB), rowSpan: 2 },
        { text: `${t(K_FROM)} ${anchorDate}`, colSpan: 2 },
        { text: t(K_MONTH), colSpan: 2 },
        { text: t(K_WEEK), colSpan: 2 },
      ],
      [
        { text: t(K_SPARE) }, { text: t(K_CONS) },
        { text: t(K_SPARE) }, { text: t(K_CONS) },
        { text: t(K_SPARE_PLAIN) }, { text: t(K_CONS) },
        { text: t(K_SPARE_PLAIN) }, { text: t(K_CONS) },
        { text: t(K_SPARE_PLAIN) }, { text: t(K_CONS) },
      ],
    ]
    const toRow = (r: SummaryRow): CellValue[] => [
      r.is_total ? t('spMat.total') : r.label,
      r.anchor_spare_good, r.anchor_consumables,
      r.current_spare_good, r.current_consumables,
      r.need_repair, r.repair_outbound,
      r.consumption_from_anchor_spare, r.consumption_from_anchor_cons,
      r.consumption_month_spare, r.consumption_month_cons,
      r.consumption_week_spare, r.consumption_week_cons,
    ]
    const totalRowData = data.rows.find(r => r.is_total)
    const bodyRows = data.rows.filter(r => !r.is_total).map(toRow)
    // 除首列外全部为数字列；消耗列（下标 7~12）套用 0 灰 / 正绿 / 负红
    const numericCols = Array.from({ length: 12 }, (_, i) => i + 1)
    const sheetName = 'SP Material Summary'
    const subtitle = `Generated: ${dayjs().format('YYYY-MM-DD HH:mm:ss')}    |    Sheet: ${sheetName}`
      + `    |    Current Date: ${currentDate || '-'}    |    Baseline: ${anchorDate || '-'}`
      + `    |    Need Repair / Repair Outbound window: ${data.repair_outbound_start || '-'} ~ ${data.repair_outbound_end || '-'}`

    exportReport(
      [{
        name: sheetName,
        title: 'Spare Parts Inbound & Outbound & Inventory Summary',
        subtitle,
        tabColor: '#2F5496',
        header: head,
        rows: bodyRows,
        totalRow: totalRowData ? toRow(totalRowData) : undefined,
        numericCols,
        valueColors: [7, 8, 9, 10, 11, 12],
      }],
      `SP_Material_Summary_${currentDate || dayjs().format('YYYY-MM-DD')}.xlsx`,
    ).catch((e: unknown) => {
      const err = e as { message?: string }
      message.error(`${t('spMat.export')} - ${err?.message || String(e)}`)
    })
  }, [data, anchorDate, currentDate, t])

  const columns: ColumnsType<SummaryRow> = useMemo(() => [
    {
      title: t(K_WH), dataIndex: 'label', key: 'label',
      fixed: 'left', width: 150,
      render: (v: string, r) => {
        const node = r.is_total ? <Text strong>{t('spMat.total')}</Text> : <Text>{v}</Text>
        const grp = data?.row_groups?.find(g => g.key === r.key)
        if (!grp?.warehouses?.length) return node
        return (
          <Tooltip title={grp.warehouses.map(w => w.warehouse_name || w.warehouse_id).join(' + ')}>
            <span style={{ borderBottom: `1px dotted ${WH.textDim}`, cursor: 'help' }}>{node}</span>
          </Tooltip>
        )
      },
    },
    {
      title: anchorDate, key: 'anchor',
      children: [
        {
          title: t(K_SPARE), dataIndex: 'anchor_spare_good', key: 'anchor_spare_good',
          align: 'right', width: 130,
          render: (v: number, r) => renderNum(v, r, 'anchor_spare_good'),
        },
        {
          title: t(K_CONS), dataIndex: 'anchor_consumables', key: 'anchor_consumables',
          align: 'right', width: 120,
          render: (v: number, r) => renderNum(v, r, 'anchor_consumables'),
        },
      ],
    },
    {
      title: t('spMat.currentDate'), key: 'current',
      children: [
        {
          title: t(K_SPARE), dataIndex: 'current_spare_good', key: 'current_spare_good',
          align: 'right', width: 130,
          render: (v: number, r) => renderNum(v, r, 'current_spare_good'),
        },
        {
          title: t(K_CONS), dataIndex: 'current_consumables', key: 'current_consumables',
          align: 'right', width: 120,
          render: (v: number, r) => renderNum(v, r, 'current_consumables'),
        },
      ],
    },
    {
      title: t(K_REPAIR), dataIndex: 'need_repair', key: 'need_repair',
      align: 'right', width: 110,
      render: (v: number, r) => (v ? (
        <span
          onClick={(e) => openDrill(r.key, r.label, 'need_repair', e)}
          style={{
            cursor: 'pointer', color: WH.sev.Warning, fontWeight: 600,
            borderBottom: `1px dotted ${WH.sev.Warning}`, paddingBottom: 1,
          }}
        >{v}</span>
      ) : <Text type="secondary">0</Text>),
    },
    {
      title: (
        <Tooltip
          title={`${t('spMat.obWindow')}: ${data?.repair_outbound_start || '-'} ~ ${data?.repair_outbound_end || '-'}`}
        >
          <span style={{ borderBottom: `1px dotted ${WH.textDim}`, cursor: 'help' }}>
            {t(K_OB)}
          </span>
        </Tooltip>
      ),
      dataIndex: 'repair_outbound', key: 'repair_outbound',
      align: 'right', width: 130,
      render: (v: number, r) => renderNum(v, r, 'repair_outbound'),
    },
    {
      title: `${t(K_FROM)} ${anchorDate}`, key: 'cons_anchor',
      children: [
        {
          title: t(K_SPARE_PLAIN), dataIndex: 'consumption_from_anchor_spare',
          key: 'consumption_from_anchor_spare', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_from_anchor_spare'),
        },
        {
          title: t(K_CONS), dataIndex: 'consumption_from_anchor_cons',
          key: 'consumption_from_anchor_cons', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_from_anchor_cons'),
        },
      ],
    },
    {
      title: t(K_MONTH), key: 'cons_month',
      children: [
        {
          title: t(K_SPARE_PLAIN), dataIndex: 'consumption_month_spare',
          key: 'consumption_month_spare', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_month_spare'),
        },
        {
          title: t(K_CONS), dataIndex: 'consumption_month_cons',
          key: 'consumption_month_cons', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_month_cons'),
        },
      ],
    },
    {
      title: t(K_WEEK), key: 'cons_week',
      children: [
        {
          title: t(K_SPARE_PLAIN), dataIndex: 'consumption_week_spare',
          key: 'consumption_week_spare', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_week_spare'),
        },
        {
          title: t(K_CONS), dataIndex: 'consumption_week_cons',
          key: 'consumption_week_cons', align: 'right', width: 110,
          render: (v: number, r) => renderConsumption(v, r, 'consumption_week_cons'),
        },
      ],
    },
  ], [data, anchorDate, t, renderNum, renderConsumption, openDrill])

  const docLines = useMemo(
    () => [t('spMat.doc1'), t('spMat.doc2'), t('spMat.doc3'), t('spMat.doc4'), t('spMat.doc5')],
    [t],
  )

  return (
    <div style={{ padding: 16, background: WH.bg, minHeight: '100%' }}>
      <Card
        title={t('spMat.title')}
        style={{ background: WH.cardBg, border: WH.cardBorder }}
        extra={
          <Space wrap>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('spMat.anchorDate')}</Text>
            <DatePicker
              value={anchorDate ? dayjs(anchorDate) : null}
              onChange={(d) => setAnchorInput(d ? d.format('YYYY-MM-DD') : '')}
              allowClear
              placeholder={t('spMat.anchorPlaceholder')}
            />
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('spMat.refresh')}
            </Button>
            <Button
              type="primary" icon={<DownloadOutlined />}
              onClick={exportExcel} disabled={!data?.rows?.length}
            >
              {t('spMat.export')}
            </Button>
          </Space>
        }
      >
        {/* 数据新鲜度 */}
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="cyan">{`${t('spMat.currentDate')}: ${currentDate || '-'}`}</Tag>
          <Tag>{`${t('spMat.anchorDate')}: ${anchorDate || '-'}`}</Tag>
          <Tag>{`${t('spMat.latestSnapshot')}: ${data?.latest_snapshot || '-'}`}</Tag>
          <Tag>{`${t('spMat.monthStart')}: ${data?.month_start || '-'}`}</Tag>
          <Tag>{`${t('spMat.weekStart')}: ${data?.week_start || '-'}`}</Tag>
          <Tag color="orange">
            {`${t('spMat.obWindow')}: ${data?.repair_outbound_start || '-'} ~ ${data?.repair_outbound_end || '-'}`}
          </Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('spMat.generatedAt')}: {data?.generated_at || '-'}
          </Text>
        </Space>

        {error && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message={t('spMat.loadFailed')} description={error}
          />
        )}

        {/* 后端未重启时不会返回新字段，那几列会是一片 0 —— 明确提示，别让人以为数据坏了 */}
        {!!data?.rows?.length && data.repair_outbound_start === undefined && (
          <Alert
            type="info" showIcon style={{ marginBottom: 12 }}
            message={t('spMat.staleBackend')}
          />
        )}

        {!!data?.warnings?.length && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('spMat.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {data.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}
          />
        )}

        <Spin spinning={loading}>
          {data?.rows?.length ? (
            <Table<SummaryRow>
              rowKey="key"
              size="small"
              columns={columns}
              dataSource={data.rows}
              pagination={false}
              scroll={{ x: 1560 }}
              rowClassName={(r) => (r.is_total ? 'sp-mat-total-row' : '')}
            />
          ) : (!loading && <Empty description={error ? t('spMat.loadFailed') : t('spMat.empty')} />)}
        </Spin>

        {/* 口径说明 */}
        <div style={{ marginTop: 16, color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
          <div style={{ marginBottom: 4, color: WH.text }}>
            <InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />
            {t('spMat.docTitle')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {docLines.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      </Card>

      {/* ==================== 明细下钻弹窗 ==================== */}
      <DraggableClickModal
        open={drillOpen}
        title={<Space><span>{drillTitle}</span>
          <Tag color="cyan">{filteredDrill.length} {t('spMat.rows')}</Tag></Space>}
        anchor={anchorPos}
        onClose={() => setDrillOpen(false)}
        width="94%"
      >
        <Space wrap style={{ marginBottom: 8 }}>
          <Tag>{t('spMat.totalQty')}: {
            (() => {
              // 快照明细看 Stock Qty、消耗对比看 Consumption Qty、报修出库看 Outbound Qty
              const key = ['Stock Qty', 'Consumption Qty', 'Outbound Qty']
                .find(k => drillCols.includes(k))
              if (!key) return 0
              return filteredDrill.reduce((s, r) => s + Number(r[key] ?? 0), 0)
            })()
          }</Tag>
          <Button
            size="small" icon={<DownloadOutlined />}
            onClick={() => {
              if (!filteredDrill.length) return
              // 明细导出同样走项目统一格式（标题行 + 深蓝表头 + 隔行底纹 + Total 行 + 冻结表头）
              const cols = drillCols.length ? drillCols : Object.keys(filteredDrill[0] || {})
              // 纯数字串转 number，保证 Excel 里可排序 / 可求和 / 千分位显示
              const toCell = (v: unknown): CellValue => {
                if (v === null || v === undefined || v === '') return null
                if (typeof v === 'number' || typeof v === 'boolean' || v instanceof Date) return v
                const s = String(v).trim()
                if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s)
                return String(v)
              }
              const rows = filteredDrill.map(r => cols.map(c => toCell(r[c])))
              // 数字列判定：该列所有非空值都是 number
              const numericCols: number[] = []
              cols.forEach((_, i) => {
                let seen = false; let allNum = true
                for (const row of rows) {
                  const v = row[i]
                  if (v === null || v === undefined || v === '') continue
                  seen = true
                  if (typeof v !== 'number') { allNum = false; break }
                }
                if (seen && allNum) numericCols.push(i)
              })
              const totalRow: CellValue[] = cols.map((_, i) => {
                if (i === 0) return t('spMat.total')
                if (!numericCols.includes(i)) return null
                return rows.reduce((s, row) => s + Number(row[i] ?? 0), 0)
              })
              exportReport([{
                name: 'Detail',
                title: drillTitle || 'Detail',
                tabColor: '#2F5496',
                header: cols,
                rows,
                totalRow,
                numericCols,
              }], `${safeFileName(drillTitle || 'detail')}.xlsx`).catch((e: unknown) => {
                const err = e as { message?: string }
                message.error(String(err?.message || e))
              })
            }}
          >
            {t('spMat.export')}
          </Button>
          <input
            className="ant-input"
            style={{
              width: 240, padding: '4px 8px', borderRadius: 6,
              background: isDark ? 'rgba(8, 18, 44,0.6)' : '#fff',
              color: isDark ? '#f5f7ff' : '#16233b',
              border: WH.cardBorder,
            }}
            placeholder={t('spMat.search')}
            value={drillSearch}
            onChange={e => setDrillSearch(e.target.value)}
          />
          <SearchOutlined style={{ color: WH.textDim }} />
        </Space>

        {!!drillWarn.length && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 8 }}
            message={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {drillWarn.map((w, i) => <li key={i}>{w}</li>)}
            </ul>}
          />
        )}

        <Table
          size="small"
          rowKey={(_, i) => String(i)}
          columns={drillColumns}
          dataSource={filteredDrill}
          loading={drillLoading}
          pagination={{
            pageSize: 20, size: 'small', showSizeChanger: false,
            showTotal: (n) => `${n} ${t('spMat.rows')}`,
          }}
          scroll={{ x: 'max-content' }}
        />
      </DraggableClickModal>
    </div>
  )
}
