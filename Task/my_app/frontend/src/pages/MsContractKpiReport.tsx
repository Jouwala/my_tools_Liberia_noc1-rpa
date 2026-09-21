/* ============================================================================
 * MS Contract KPIs & WOs Achievement Auto-Reports（page=ms_contract_kpi）
 *
 * 数据源：data/ms_sla/ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx
 * —— 任务 ms_sla_full（MS SLA 完整同步，每天 05:00）就地更新的**自动化报表工作簿本体**，
 * 含 4 张 sheet：
 *   Contract KPIs Report (New)     27 个合同 KPI（Operation / Network / PerSite 三层）
 *   WOs SLA achievement Report     与 ?page=ms_wo_sla 那份逐字同构
 *   FineBI Dashboard Planing       FineBI 看板建设规划清单
 *   利比里亚自动化报表              自动化报表清单（优先级/频率/团队/推动方式）
 * 解析口径见 backend/services/ms_kpi_report_service.py 顶部 docstring。
 *
 * 页面结构：总览卡片 → 分类达标 → 27 个 KPI 卡（点击看日趋势）→ 4 个页签
 * （KPI 矩阵 / WO SLA 矩阵 / FineBI 规划 / 自动化报表清单，后两个支持搜索+筛选+分页）。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Empty, Input, Row, Segmented, Select, Space, Spin, Table, Tag,
  Typography, message,
} from 'antd'
import {
  ReloadOutlined, DownloadOutlined, SearchOutlined, InfoCircleOutlined, CloseCircleOutlined,
  WarningOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { getMsKpiReportFilters, getMsKpiReportRows, getMsKpiReportSummary } from '../api'
import { useI18n, numLocale } from '../i18n'
import { useTheme, WH } from '../theme'
import { exportReport, safeFileName, type CellValue } from '../utils/excelReport'
import {
  KpiMatrixTable, MetricCards, MetricTrendModal, RowDetailModal, StatCard,
  fmtValue, num, type Matrix, type Metric, type MsKpiSummary,
} from './MsKpiShared'

const { Text } = Typography

const CONTRACT_SHEET = 'Contract KPIs Report (New)'
const WO_SHEET = 'WOs SLA achievement Report'
const FINEBI_SHEET = 'FineBI Dashboard Planing'
const AUTOMATION_SHEET = '利比里亚自动化报表'

const FLAT_SHEETS = [FINEBI_SHEET, AUTOMATION_SHEET]
const EXPORT_MAX_ROWS = 5000
const SEARCH_DEBOUNCE_MS = 350

type FlatRow = Record<string, string | number | null>

interface RowsResp {
  kind: string
  sheet: string
  columns: string[]
  numeric_columns: string[]
  rows: FlatRow[]
  total: number
  page: number
  page_size: number
  warnings: string[]
}
interface FilterField {
  column: string
  label: string
  options: { value: string; count: number }[]
}

/** 筛选字段 label -> i18n 文案键 */
const FILTER_LABEL_KEY: Record<string, string> = {
  domain: 'msKpi.f.domain',
  priority: 'msKpi.f.priority',
  frequency: 'msKpi.f.frequency',
  team: 'msKpi.f.team',
  dataSource: 'msKpi.f.dataSource',
  type: 'msKpi.f.type',
  autoType: 'msKpi.f.autoType',
  pushMode: 'msKpi.f.pushMode',
}

// ============================================================================
// 扁平表页签（FineBI 规划 / 自动化报表清单）：搜索 + 多选筛选 + 服务端分页 + 导出
// ============================================================================
function FlatSheetPanel(props: {
  sheet: string
  title: string
  t: (k: string) => string
  loc: string
}) {
  const { sheet, title, t, loc } = props
  const { isDark } = useTheme()

  const [resp, setResp] = useState<RowsResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [filters, setFilters] = useState<Record<string, string[]>>({})
  const [fields, setFields] = useState<FilterField[]>([])
  const [sort, setSort] = useState('')
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [drill, setDrill] = useState<{ row: FlatRow; x: number; y: number } | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [search])

  const filtersKey = useMemo(() => JSON.stringify(filters), [filters])

  useEffect(() => {
    let alive = true
    setLoading(true)
    getMsKpiReportRows({
      kind: 'contract_kpi', sheet, page, page_size: pageSize,
      q: debounced, sort, order, filters: filtersKey === '{}' ? '' : filtersKey,
    })
      .then(res => {
        if (!alive) return
        const data = res.data as RowsResp
        setResp(data)
        setError(data.warnings?.length ? data.warnings.join('；') : '')
      })
      .catch((e: unknown) => {
        if (!alive) return
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setError(String(err?.response?.data?.detail || err?.message || e))
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [sheet, page, pageSize, debounced, sort, order, filtersKey])

  useEffect(() => {
    let alive = true
    getMsKpiReportFilters('contract_kpi', sheet)
      .then(res => {
        if (!alive) return
        const data = res.data as { fields?: FilterField[] }
        setFields(data.fields ?? [])
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
      .catch(() => { if (alive) setFields([]) })
    return () => { alive = false }
  }, [sheet])

  const doExport = useCallback(async () => {
    setExporting(true)
    try {
      const total = resp?.total ?? 0
      const size = Math.max(1, Math.min(total, EXPORT_MAX_ROWS))
      const res = await getMsKpiReportRows({
        kind: 'contract_kpi', sheet, page: 1, page_size: size,
        q: debounced, sort, order, filters: filtersKey === '{}' ? '' : filtersKey,
      })
      const data = res.data as RowsResp
      const cols = data.columns
      const numericSet = new Set(data.numeric_columns)
      const numericCols: number[] = []
      cols.forEach((c, i) => { if (numericSet.has(c)) numericCols.push(i) })
      const rows: CellValue[][] = data.rows.map(r => cols.map(c => {
        const v = r[c]
        if (v === null || v === undefined) return null
        return numericSet.has(c) ? num(v) : String(v)
      }))
      await exportReport([{
        name: sheet,
        title,
        subtitle: `${t('msKpi.sourceFile')}: ${'ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx'}    |    `
          + `${t('msKpi.rows')}: ${data.total}`,
        tabColor: sheet === FINEBI_SHEET ? '#2F5496' : '#BF8F00',
        header: cols,
        rows,
        numericCols,
      }], `${safeFileName(title)}.xlsx`)
    } catch (e: unknown) {
      message.error(String((e as { message?: string })?.message || e))
    } finally {
      setExporting(false)
    }
  }, [sheet, title, resp, debounced, sort, order, filtersKey, t])

  const searchInputStyle: React.CSSProperties = {
    background: isDark ? 'rgba(8, 18, 44,0.6)' : '#fff',
    color: isDark ? '#f5f7ff' : '#16233b',
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          style={{ width: 260, ...searchInputStyle }}
          prefix={<SearchOutlined style={{ color: WH.textDim }} />}
          placeholder={t('msKpi.searchPh')}
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        {fields.map(f => (
          <Select
            key={f.column}
            mode="multiple"
            allowClear
            maxTagCount="responsive"
            style={{ minWidth: 180, maxWidth: 300 }}
            placeholder={t(FILTER_LABEL_KEY[f.label] || f.column)}
            value={filters[f.column] ?? []}
            onChange={(vals: string[]) => {
              setFilters(prev => {
                const next = { ...prev }
                if (vals && vals.length) next[f.column] = vals
                else delete next[f.column]
                return next
              })
              setPage(1)
            }}
            options={f.options.map(o => ({
              value: o.value,
              label: `${o.value} (${o.count.toLocaleString(loc)})`,
            }))}
          />
        ))}
        {(Object.keys(filters).length > 0 || search) && (
          <Button icon={<CloseCircleOutlined />} onClick={() => { setFilters({}); setSearch(''); setPage(1) }}>
            {t('msKpi.reset')}
          </Button>
        )}
        <Tag>{`${t('msKpi.filteredRows')}: ${(resp?.total ?? 0).toLocaleString(loc)}`}</Tag>
        <Button icon={<DownloadOutlined />} onClick={doExport} loading={exporting}
          disabled={!resp?.total}>
          {t('msKpi.export')}
        </Button>
      </Space>

      {error && (
        <Alert type="error" showIcon style={{ marginBottom: 12 }}
          message={t('msKpi.loadFailed')} description={error} />
      )}

      {resp?.rows?.length ? (
        <Table<FlatRow>
          size="small"
          rowKey={(_r, i) => String(i)}
          dataSource={resp.rows}
          loading={loading}
          scroll={{ x: 'max-content' }}
          columns={resp.columns.map(name => ({
            title: name,
            dataIndex: name,
            key: name,
            ellipsis: true,
            align: resp.numeric_columns.includes(name) ? ('right' as const) : undefined,
            sorter: true,
            sortOrder: sort === name ? (order === 'desc' ? ('descend' as const) : ('ascend' as const)) : null,
            render: (v: string | number | null) => {
              if (v === null || v === undefined || v === '') return <Text type="secondary">-</Text>
              if (resp.numeric_columns.includes(name)) {
                return num(v).toLocaleString(loc, { maximumFractionDigits: 2 })
              }
              return <span style={{ whiteSpace: 'pre-wrap' }}>{String(v)}</span>
            },
          })) as ColumnsType<FlatRow>}
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
            current: resp.page,
            pageSize: resp.page_size,
            total: resp.total,
            size: 'small',
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100', '200'],
            showTotal: (n) => `${n.toLocaleString(loc)} ${t('msKpi.rows')}`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      ) : (
        !loading && <Empty description={error ? t('msKpi.loadFailed') : t('msKpi.empty')} />
      )}

      <RowDetailModal
        open={!!drill}
        row={drill?.row ?? null}
        anchor={drill ? { x: drill.x, y: drill.y } : null}
        onClose={() => setDrill(null)}
        t={t}
        title={title}
      />
    </>
  )
}

// ============================================================================
// 页面
// ============================================================================
export default function MsContractKpiReport() {
  const { t, locale } = useI18n()
  const loc = numLocale(locale)

  const [summary, setSummary] = useState<MsKpiSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState(CONTRACT_SHEET)
  // 弹窗要带上「指标来自哪个矩阵」——两张矩阵的列 key 都是 c1..cN，单看 key 会串台
  const [pick, setPick] = useState<{ metric: Metric; matrix: Matrix; x: number; y: number } | null>(null)
  const [exporting, setExporting] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    getMsKpiReportSummary('contract_kpi')
      .then(res => {
        setSummary(res.data as MsKpiSummary)
        setError('')
      })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setError(String(err?.response?.data?.detail || err?.message || e))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const matrices = summary?.matrices ?? {}
  const contract = matrices[CONTRACT_SHEET] ?? null
  const wo = matrices[WO_SHEET] ?? null
  const ov = summary?.overview

  const activeMatrix: Matrix | null = tab === CONTRACT_SHEET ? contract
    : tab === WO_SHEET ? wo : null

  const pickMatrix: Matrix | null = pick?.matrix ?? activeMatrix

  // ---------- 概览卡片 ----------
  const cards = useMemo(() => {
    if (!ov) return []
    const worst = ov.worst ?? []
    return [
      {
        key: 'kpi', label: t('msKpi.card.kpiCount'), value: (ov.kpi_count ?? 0).toLocaleString(loc),
        hint: t('msKpi.hint.kpiCount'),
      },
      {
        key: 'met', label: t('msKpi.card.metKpi'), value: (ov.met_count ?? 0).toLocaleString(loc),
        hint: t('msKpi.hint.metKpi'), color: WH.ok,
      },
      {
        key: 'below', label: t('msKpi.card.belowKpi'), value: (ov.below_count ?? 0).toLocaleString(loc),
        hint: t('msKpi.hint.belowKpi'),
        color: (ov.below_count ?? 0) > 0 ? WH.danger : WH.ok,
        emphasis: (ov.below_count ?? 0) > 0,
      },
      {
        key: 'unknown', label: t('msKpi.card.unknownKpi'),
        value: (ov.unknown_count ?? 0).toLocaleString(loc),
        hint: t('msKpi.hint.unknownKpi'), color: WH.textMuted,
      },
      {
        key: 'days', label: t('msKpi.card.days'), value: (ov.days ?? 0).toLocaleString(loc),
        hint: `${ov.first_day || '-'} ~ ${ov.last_day || '-'}`,
      },
      {
        key: 'worst', label: t('msKpi.card.worst'), value: worst.length ? worst[0].label : '-',
        hint: worst.length
          ? `${t('msKpi.monthValue')}: ${fmtValue(worst[0].month_value, worst[0].format, loc)}`
            + ` / ${t('msKpi.target')}: ${fmtValue(worst[0].target, worst[0].format, loc)}`
          : t('msKpi.hint.allMet'),
        color: worst.length ? WH.danger : WH.ok,
        emphasis: worst.length > 0,
      },
    ]
  }, [ov, t, loc])

  // ---------- 分类达标 ----------
  const catCards = useMemo(() => {
    const cats = ov?.categories ?? []
    const woOv = ov?.wo_sla
    return [
      ...cats.map(c => ({
        key: c.category,
        label: c.category,
        value: `${c.met_count}/${c.count}`,
        hint: `${t('msKpi.below')}: ${c.below_count}`,
        color: c.below_count > 0 ? WH.warn : WH.ok,
      })),
      ...(woOv ? [{
        key: '__wo__',
        label: t('msKpi.cat.woSla'),
        value: `${woOv.met_count}/${woOv.kpi_count}`,
        hint: `${t('msKpi.below')}: ${woOv.below_count}`,
        color: woOv.below_count > 0 ? WH.warn : WH.ok,
      }] : []),
    ]
  }, [ov, t])

  // ---------- 导出当前矩阵页签 ----------
  const exportMatrix = useCallback(async (matrix: Matrix, label: string) => {
    setExporting(true)
    try {
      const header: string[] = [matrix.label_header]
      matrix.columns.forEach(c => {
        const parts = [c.category, c.group, c.label].filter(Boolean)
        const dedup: string[] = []
        parts.forEach(p => { if (!dedup.length || dedup[dedup.length - 1] !== p) dedup.push(p) })
        header.push(dedup.join(' / '))
      })
      const toRow = (lbl: string, values: Record<string, number | null>): CellValue[] =>
        [lbl, ...matrix.columns.map(c => {
          const v = values[c.key]
          return v === null || v === undefined ? null : num(v)
        })]
      const rows: CellValue[][] = []
      if (Object.keys(matrix.month).length) rows.push(toRow(matrix.month_label, matrix.month))
      matrix.rows.forEach(r => rows.push(toRow(r.label, r.values)))
      await exportReport([{
        name: matrix.sheet,
        title: matrix.title || label,
        subtitle: `${t('msKpi.sourceFile')}: ${summary?.source.file || '-'}    |    `
          + `${t('msKpi.rows')}: ${matrix.rows.length}`,
        tabColor: matrix.sheet === CONTRACT_SHEET ? '#2F5496' : '#548235',
        header,
        rows,
        numericCols: matrix.columns.map((_c, i) => i + 1),
      }], `${safeFileName(matrix.title || label)}.xlsx`)
    } catch (e: unknown) {
      message.error(String((e as { message?: string })?.message || e))
    } finally {
      setExporting(false)
    }
  }, [summary, t])

  const tabOptions = useMemo(() => {
    const opts = (summary?.sheets ?? []).map(s => {
      const label = s.key === FINEBI_SHEET ? t('msKpi.sheet.finebi')
        : s.key === AUTOMATION_SHEET ? t('msKpi.sheet.automation')
          : s.key === WO_SHEET ? t('msKpi.sheet.woSla')
            : t('msKpi.sheet.contract')
      return { value: s.key, label: `${label} (${s.records.toLocaleString(loc)})` }
    })
    return opts.length ? opts : [{ value: CONTRACT_SHEET, label: CONTRACT_SHEET }]
  }, [summary, t, loc])

  return (
    <div style={{ padding: 16, background: WH.bg, minHeight: '100%' }}>
      {/* ==================== 总览 ==================== */}
      <Card
        title={t('msKpi.contractTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              {t('msKpi.refresh')}
            </Button>
            {/* 扁平表页签（FineBI / 自动化清单）由面板自己带搜索+筛选+导出，
                这里不再重复给一个 disabled 的按钮，避免两个「导出 Excel」。 */}
            {activeMatrix && (
              <Button type="primary" icon={<DownloadOutlined />} loading={exporting}
                onClick={() => exportMatrix(activeMatrix, tab)}>
                {t('msKpi.export')}
              </Button>
            )}
          </Space>
        )}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="cyan">{`${t('msKpi.sourceFile')}: ${summary?.source.file || '-'}`}</Tag>
          <Tag>{`${t('msKpi.dataTime')}: ${summary?.source.generated_at || '-'}`}</Tag>
          <Tag>{`${t('msKpi.task')}: ${summary?.source.task || '-'}`}</Tag>
          <Tag>{`${t('msKpi.queryTime')}: ${summary?.generated_at || '-'}`}</Tag>
        </Space>

        {error && (
          <Alert type="error" showIcon style={{ marginBottom: 12 }}
            message={t('msKpi.loadFailed')} description={error} />
        )}
        {!!summary?.warnings?.length && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message={t('msKpi.warnTitle')}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {summary.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>} />
        )}

        <Spin spinning={loading}>
          <Row gutter={[12, 12]}>
            {cards.map(c => (
              <Col key={c.key} xs={12} sm={8} lg={4}>
                <StatCard label={c.label} value={c.value} hint={c.hint}
                  color={c.color} emphasis={c.emphasis} />
              </Col>
            ))}
          </Row>
        </Spin>
      </Card>

      {/* ==================== 分类达标 ==================== */}
      <Card
        title={t('msKpi.catTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={<Text style={{ color: WH.textDim, fontSize: 12 }}>{t('msKpi.catHint')}</Text>}
      >
        <Spin spinning={loading}>
          <Row gutter={[12, 12]}>
            {catCards.map(c => (
              <Col key={c.key} xs={12} sm={8} lg={4}>
                <StatCard label={c.label} value={c.value} hint={c.hint} color={c.color}
                  emphasis={c.color === WH.warn} />
              </Col>
            ))}
          </Row>
          {!!ov?.worst?.length && (
            <div style={{ marginTop: 14 }}>
              <Space wrap>
                <Text style={{ color: WH.textMuted, fontSize: 12 }}>
                  <WarningOutlined style={{ color: WH.danger, marginRight: 6 }} />
                  {t('msKpi.worstTitle')}
                </Text>
                {ov.worst.map(w => (
                  <Tag key={`${w.category}|${w.group}|${w.key}`} color="red">
                    {`${w.label} ${fmtValue(w.month_value, w.format, loc)} / ${fmtValue(w.target, w.format, loc)}`}
                  </Tag>
                ))}
              </Space>
            </div>
          )}
          {!!ov?.best?.length && (
            <div style={{ marginTop: 8 }}>
              <Space wrap>
                <Text style={{ color: WH.textMuted, fontSize: 12 }}>
                  <CheckCircleOutlined style={{ color: WH.ok, marginRight: 6 }} />
                  {t('msKpi.bestTitle')}
                </Text>
                {ov.best.map(w => (
                  <Tag key={`${w.category}|${w.group}|${w.key}`} color="green">
                    {`${w.label} ${fmtValue(w.month_value, w.format, loc)} / ${fmtValue(w.target, w.format, loc)}`}
                  </Tag>
                ))}
              </Space>
            </div>
          )}
        </Spin>
      </Card>

      {/* ==================== 27 个 KPI 卡（点击看日趋势） ==================== */}
      <Card
        title={t('msKpi.kpiCardsTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder, marginBottom: 12 }}
        extra={<Text style={{ color: WH.textDim, fontSize: 12 }}>{t('msKpi.kpiCardsHint')}</Text>}
      >
        <Spin spinning={loading}>
          {contract
            ? (
              <MetricCards
                matrix={contract}
                loc={loc}
                t={t}
                compact
                onPick={(m) => setPick({
                  metric: m, matrix: contract,
                  x: window.innerWidth / 2, y: window.innerHeight / 3,
                })}
              />
            )
            : <Text type="secondary">{t('msKpi.empty')}</Text>}
        </Spin>
      </Card>

      {/* ==================== 4 个页签 ==================== */}
      <Card
        title={t('msKpi.tabsTitle')}
        style={{ background: WH.cardBg, border: WH.cardBorder }}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Segmented value={tab} onChange={(v) => setTab(String(v))} options={tabOptions} />
        </Space>

        <Spin spinning={loading}>
          {tab === CONTRACT_SHEET && contract && (
            <>
              <Space wrap style={{ marginBottom: 10 }}>
                <Tag color="cyan">{`${t('msKpi.kpiCount')}: ${contract.metrics.length}`}</Tag>
                <Tag color="green">{`${t('msKpi.met')}: ${contract.overview.met_count}`}</Tag>
                <Tag color="red">{`${t('msKpi.below')}: ${contract.overview.below_count}`}</Tag>
                <Tag>{`${t('msKpi.rows')}: ${contract.rows.length}`}</Tag>
              </Space>
              <KpiMatrixTable
                matrix={contract}
                loc={loc}
                t={t}
                maxHeight={560}
                onPickMetric={(m, anchor) => setPick({
                  metric: m, matrix: contract,
                  x: anchor?.x ?? window.innerWidth / 2,
                  y: anchor?.y ?? window.innerHeight / 3,
                })}
              />
              <div style={{ marginTop: 8, color: WH.textDim, fontSize: 11 }}>
                {t('msKpi.matrixHint')}
              </div>
            </>
          )}

          {tab === WO_SHEET && wo && (
            <>
              <Space wrap style={{ marginBottom: 10 }}>
                {wo.metrics.map(m => (
                  <Tag key={m.key} color={m.met === true ? 'green' : m.met === false ? 'red' : 'default'}>
                    {`${m.label} ${fmtValue(m.month_value, m.format, loc)}`}
                  </Tag>
                ))}
                <Tag>{`${t('msKpi.rows')}: ${wo.rows.length}`}</Tag>
              </Space>
              <KpiMatrixTable
                matrix={wo}
                loc={loc}
                t={t}
                maxHeight={560}
                onPickMetric={(m, anchor) => setPick({
                  metric: m, matrix: wo,
                  x: anchor?.x ?? window.innerWidth / 2,
                  y: anchor?.y ?? window.innerHeight / 3,
                })}
              />
              <div style={{ marginTop: 8, color: WH.textDim, fontSize: 11 }}>
                {t('msKpi.woSameAsPage')}
              </div>
            </>
          )}

          {FLAT_SHEETS.includes(tab) && (
            <FlatSheetPanel
              key={tab}
              sheet={tab}
              title={tab === FINEBI_SHEET ? t('msKpi.sheet.finebi') : t('msKpi.sheet.automation')}
              t={t}
              loc={loc}
            />
          )}

          {!contract && !wo && !FLAT_SHEETS.includes(tab) && (
            <Empty description={t('msKpi.empty')} />
          )}
        </Spin>

        {/* 报表口径（原样透传标题 + 达标判定说明） */}
        <div style={{ marginTop: 16, color: WH.textMuted, fontSize: 12, lineHeight: 1.9 }}>
          <div style={{ marginBottom: 4, color: WH.text }}>
            <InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />
            {t('msKpi.docTitle')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {summary?.notes?.map((n, i) => <li key={i}>{n}</li>)}
            <li>{t('msKpi.doc.metRule')}</li>
            <li>{t('msKpi.doc.persite')}</li>
            <li>{t('msKpi.doc.woScope')}</li>
          </ul>
        </div>
      </Card>

      {/* ==================== 指标趋势 ==================== */}
      <MetricTrendModal
        open={!!pick}
        metric={pick?.metric ?? null}
        matrix={pickMatrix}
        anchor={pick ? { x: pick.x, y: pick.y } : null}
        onClose={() => setPick(null)}
        t={t}
      />
    </div>
  )
}
