/* ============================================================================
 * 可用率多维矩阵（?page=avail_ms）
 * ----------------------------------------------------------------------------
 * 需求（见 11-feature-guide.md 新增小节）：把可用率按「区域 / 制式 / 站点类型」
 * 三个维度呈现，并支持 日 / 周 / 月 三档周期页签切换。
 *
 * 数据源：后端 /api/avail-ms/*（读本机派生库 data/avail_recon.sqlite3）。
 * 口径：可用率 = SUM(Numerator)/SUM(Denominator)，三个维度与三档周期共用同一份
 *       数据，因此**所有数字都可下钻**（单元格 -> 时间明细 + 构成分解 + 趋势 -> TT 工单）。
 *
 * 三条必须显示给用户的口径说明（后端用警告码返回，这里映射成文案，见 warnKey）：
 *   ① 区域 ALL 含未匹配主数据的站点，因此 ALL ≠ 三区域相加
 *   ② 4G 的 NERA 脏值在站点类型维度单列 Other
 *   ③ TT 工单按站点主数据分类、且不按制式过滤（TT 表没有制式字段）
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Col, Empty, InputNumber, Row, Select, Space, Spin, Table, Tabs,
  Tooltip, Typography,
} from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import type { ColumnsType } from 'antd/es/table'

import { useI18n } from '../i18n'
import { WH, useTheme, axisLabel, axisLine, darkTooltip, splitLine } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
// 三个维度的曲线图（多序列折线，点可下钻）；与下钻弹窗里的单序列小图是两个组件，原因见其文件头
import AvailMsTrend from './AvailMsTrend'
import type { TrendSeries } from './AvailMsTrend'
import { exportReport } from '../utils/excelReport'
import type { ReportSheetSpec } from '../utils/excelReport'
import { getAvailMsDrilldown, getAvailMsMatrix, getAvailMsOptions, getAvailMsTrend } from '../api'

const { Text } = Typography

/* ---------------- 类型（与后端返回结构对齐） ---------------- */
type Gran = 'day' | 'week' | 'month'
type Dim = 'region' | 'tech' | 'site_type'
type DrillLevel = 'period' | 'tt'

interface Cell {
  availability: number | null
  numerator: number
  denominator: number
  below: boolean | null
  prev_availability: number | null
  delta_pp: number | null
}
interface MatrixRow { key: string; cells: Record<string, Cell> }
interface MatrixGroup { dim: Dim; columns: string[]; rows: MatrixRow[] }
interface Matrix {
  meta: {
    period: Gran; value: string; prev_value: string; data_through: string
    threshold: number; generated_at: string; elapsed_ms: number
    warnings: string[]; unknown_cell_groups?: string[]; error?: string
  }
  summary: {
    by_tech: Record<string, number | null>
    unmatched_share: number | null
    regions: string[]
    rows_in_period: number
  }
  groups: MatrixGroup[]
}
interface SeriesItem {
  key: string; numerator: number; denominator: number
  availability: number | null; below: boolean | null
  cell_group?: string; tech?: string; site_type?: string
}
interface TtRow {
  tt_no: string; title: string; status: string; ticket_severity: string
  site_id: string; site_name: string; region: string; site_type_norm: string
  site_outage: string; current_handler: string; root_cause: string
  alarm_occur_time: string; created_time: string; mttr_minutes: number | null
}
interface Drill {
  meta: {
    level: DrillLevel; period: Gran; value: string; region: string; tech: string
    site_type: string; warnings: string[]; error?: string
    total?: number; returned?: number; truncated?: boolean
    start?: string; end?: string; unassigned?: number
  }
  rows?: TtRow[]
  series?: SeriesItem[]
  breakdown?: SeriesItem[]
  history?: SeriesItem[]
  cell?: Cell | null
}
interface Options {
  data_through: string
  latest: Partial<Record<Gran, string>>
  days: string[]; weeks: string[]; months: string[]
  threshold: number; warnings: string[]; error?: string
}
interface Trend {
  meta: {
    period: Gran; value: string; start: string; end: string; points: number
    threshold: number; generated_at: string; warnings: string[]; error?: string
  }
  categories: string[]
  dims: Record<Dim, TrendSeries[]>
}
/** 一个可下钻的目标：三个维度切片 + 弹窗标题用的可读标签 */
interface CellTarget { region: string; tech: string; site_type: string; label: string }

const GRANS: Gran[] = ['day', 'week', 'month']
/** 维度标题键。⚠️ 这些键是**间接引用**（经 DIM_TITLE_KEY 取值再传给 t()），
 *  `npm run check:i18n` 会把它们列进「字典里存在但代码未引用」的清理候选清单 ——
 *  **不要删**：删了界面就会显示键名。同一原因，warnKey() 返回的那批键也一样。 */
const DIM_TITLE_KEY: Record<Dim, string> = {
  region: 'availMs.dimRegion',
  tech: 'availMs.dimTech',
  site_type: 'availMs.dimSiteType',
}

/** 空值统一显示 `—`：取不到数据不得显示成 0 */
const fmtPct = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : `${(v * 100).toFixed(digits)}%`

/** 逾期天数/条数等：null 一律 `—` */
const fmtNum = (v: number | null | undefined) => (v == null ? '—' : String(v))

/** 警告码 -> i18n 键。**刻意用显式 switch**：`t('availMs.warn.' + code)` 会被
 *  `npm run check:i18n` 读成键名 `availMs.warn.` 而报缺失（见 AGENTS.md 第三节 1b）。 */
function warnKey(code: string): string | null {
  switch (code) {
    case 'region_all_includes_unmatched': return 'availMs.warn.regionAllIncludesUnmatched'
    case 'other_site_type_present': return 'availMs.warn.otherSiteType'
    case 'unknown_cell_group': return 'availMs.warn.unknownCellGroup'
    case 'no_data_for_period': return 'availMs.warn.noDataForPeriod'
    case 'derived_db_missing': return 'availMs.warn.derivedDbMissing'
    case 'combination_not_applicable': return 'availMs.warn.combinationNotApplicable'
    case 'no_detail_for_cell': return 'availMs.warn.noDetail'
    case 'unmatched_region_no_tt': return 'availMs.warn.unmatchedNoTt'
    case 'tt_no_tech_filter': return 'availMs.warn.ttNoTechFilter'
    case 'tt_truncated': return 'availMs.warn.ttTruncated'
    case 'tt_fetch_capped': return 'availMs.warn.ttFetchCapped'
    case 'tt_site_unassigned': return 'availMs.warn.ttSiteUnassigned'
    case 'no_tt_in_period': return 'availMs.warn.noTtInPeriod'
    case 'options_failed': return 'availMs.warn.loadFailed'
    case 'matrix_failed': return 'availMs.warn.loadFailed'
    case 'trend_failed': return 'availMs.warn.loadFailed'
    case 'drilldown_failed': return 'availMs.warn.loadFailed'
    case 'tt_read_failed': return 'availMs.warn.ttReadFailed'
    default: return null
  }
}

/** 失败类警告用红色，其余为口径提示（黄色） */
const isErrorWarn = (code: string) =>
  ['derived_db_missing', 'options_failed', 'matrix_failed', 'trend_failed',
    'drilldown_failed', 'tt_read_failed'].includes(code)

export default function AvailMs() {
  const { t } = useI18n()
  const { isDark, palette } = useTheme()

  /* ---- 筛选项 ---- */
  const [options, setOptions] = useState<Options | null>(null)
  const [thresholdPct, setThresholdPct] = useState(99.65)
  const thr = useMemo(() => Math.round(thresholdPct * 100) / 10000, [thresholdPct])

  /* ---- 页签 + 每档周期各记一个「选中期」（互不干扰）---- */
  const [gran, setGran] = useState<Gran>('day')
  const [valueByGran, setValueByGran] = useState<Record<Gran, string>>({ day: '', week: '', month: '' })
  const [cache, setCache] = useState<Record<string, { matrix: Matrix; trend: Trend | null }>>({})
  const [loadingKey, setLoadingKey] = useState('')

  /** 缓存键 = 档位|周期值|阈值。切回已看过的页签**不重新请求**，也避免
   *  「切页签瞬间仍读上一档数据」的错位（TTWODashboard.tsx:1227 的教训）。
   *  周期值留空时后端按「库里最新一期」解析，选择器用 options.latest 显示同一期，
   *  因此这里**不回填**状态 —— 回填会让缓存键变一次、白跑一次请求。 */
  const reqValue = valueByGran[gran]
  const cacheKey = `${gran}|${reqValue || '__latest__'}|${thr}`
  const entry = cache[cacheKey]
  const matrix = entry?.matrix
  const trend = entry?.trend || null
  /** 当前实际在看的那一期：选择器停在"最新"时用后端解析出来的值，别显示空 */
  const currentValue = reqValue || matrix?.meta.value || options?.latest?.[gran] || ''

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [target, setTarget] = useState<CellTarget | null>(null)
  const [drillValue, setDrillValue] = useState('')
  const [drill, setDrill] = useState<Drill | null>(null)
  const [tt, setTt] = useState<Drill | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [modalTab, setModalTab] = useState<DrillLevel>('period')

  /* ---- 选项：失败不阻塞（页面主体仍可用） ---- */
  const loadOptions = useCallback(async () => {
    try {
      const r = await getAvailMsOptions()
      setOptions((r.data || null) as Options | null)
    } catch {
      setOptions({ data_through: '', latest: {}, days: [], weeks: [], months: [],
        threshold: 0.9965, warnings: ['options_failed'] })
    }
  }, [])

  /** 矩阵与曲线**一起取**：两张表和一个图如果各取各的，会出现"表已刷新、图还是上一期"
   *  的错位（同一个缓存键必须对应同一期的数据）。两个请求并行发，总耗时按慢的那个算。 */
  const loadMatrix = useCallback(async (key: string) => {
    const [g, rawValue, rawThr] = key.split('|')
    const value = rawValue === '__latest__' ? '' : rawValue
    const threshold = Number(rawThr)
    setLoadingKey(key)
    const [mx, tr] = await Promise.allSettled([
      getAvailMsMatrix({ period: g as Gran, value, threshold }),
      getAvailMsTrend({ period: g as Gran, value, threshold }),
    ])
    let matrixData: Matrix
    if (mx.status === 'fulfilled') {
      matrixData = mx.value.data as Matrix
    } else {
      const e: any = mx.reason
      matrixData = {
        meta: { period: g as Gran, value: '', prev_value: '', data_through: '',
          threshold, generated_at: '', elapsed_ms: 0,
          warnings: ['matrix_failed'], error: e?.message || String(e) },
        summary: { by_tech: {}, unmatched_share: null, regions: [], rows_in_period: 0 },
        groups: [],
      }
    }
    let trendData: Trend | null = null
    if (tr.status === 'fulfilled') {
      trendData = tr.value.data as Trend
    } else {
      // 曲线单独失败不影响表格可用：只丢图，表照常渲染
      const e: any = tr.reason
      trendData = {
        meta: { period: g as Gran, value: '', start: '', end: '', points: 0,
          threshold, generated_at: '', warnings: ['trend_failed'],
          error: e?.message || String(e) },
        categories: [], dims: { region: [], tech: [], site_type: [] },
      }
    }
    setCache(prev => ({ ...prev, [key]: { matrix: matrixData, trend: trendData } }))
    setLoadingKey('')
  }, [])

  useEffect(() => { void loadOptions() }, [loadOptions])
  useEffect(() => {
    if (!matrix && loadingKey !== cacheKey) void loadMatrix(cacheKey)
  }, [cacheKey, matrix, loadingKey, loadMatrix])

  /* ---- 下钻取数 ---- */
  const loadDrill = useCallback(async (
    level: DrillLevel, tg: { region: string; tech: string; site_type: string }, value: string,
  ) => {
    setDrillLoading(true)
    try {
      const r = await getAvailMsDrilldown({
        level, period: gran, value: value || '', region: tg.region,
        tech: tg.tech, site_type: tg.site_type, threshold: thr,
      })
      if (level === 'tt') setTt(r.data as Drill)
      else setDrill(r.data as Drill)
    } catch (e: any) {
      const failed: Drill = {
        meta: { level, period: gran, value, region: tg.region, tech: tg.tech,
          site_type: tg.site_type, warnings: ['drilldown_failed'],
          error: e?.message || String(e) },
        rows: [],
      }
      if (level === 'tt') setTt(failed)
      else setDrill(failed)
    } finally {
      setDrillLoading(false)
    }
  }, [gran, thr])

  const openDrill = useCallback((
    tg: CellTarget, at?: { x: number; y: number }, value?: string,
  ) => {
    // value 显式传入 = 从曲线上的某个点下钻（那个点属于历史某一期，不是当前期）；
    // 不传则用当前正在看的那一期。
    const v = value || currentValue
    setDrillValue(v)
    setTarget(tg)
    setAnchor(at || null)
    setDrill(null)
    setTt(null)
    setModalTab('period')
    setOpen(true)
    void loadDrill('period', tg, v)
  }, [loadDrill, currentValue])

  /** 弹窗内切到 TT 页签时才取工单（单月可达数千条，不做无谓预取） */
  const onModalTab = useCallback((k: string) => {
    const lv = (k === 'tt' ? 'tt' : 'period') as DrillLevel
    setModalTab(lv)
    if (!target) return
    if (lv === 'tt' && !tt) void loadDrill('tt', target, drillValue)
  }, [target, tt, drillValue, loadDrill])

  /* ---- 行/列标签：区域名、制式、站点类型都是业务原值，不翻译 ---- */
  const rowLabel = useCallback((key: string) => {
    if (key === 'ALL') return t('availMs.regionAll')
    if (key === 'UNMATCHED') return t('availMs.regionUnmatched')
    if (key === 'Other') return t('availMs.siteTypeOther')
    return key
  }, [t])

  /* ---- 单元格：数字可点下钻，未达标染红，`—` 表示口径上不存在或当期无数据 ---- */
  const renderCell = useCallback((cell: Cell | undefined, tg: CellTarget) => {
    if (!cell || cell.availability == null) {
      return <Text type="secondary">—</Text>
    }
    const color = cell.below ? WH.danger : WH.ok
    const delta = cell.delta_pp
    return (
      <Tooltip title={`${t('availMs.colNum')} ${cell.numerator} / ${t('availMs.colDen')} ${cell.denominator}`}>
        <span
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer', color, fontWeight: 600 }}
          onClick={e => openDrill(tg, { x: e.clientX, y: e.clientY })}
          onKeyDown={e => { if (e.key === 'Enter') openDrill(tg) }}
        >
          {fmtPct(cell.availability)}
          {delta != null && (
            <span style={{ marginLeft: 4, fontSize: 11, color: delta < 0 ? WH.danger : WH.ok }}>
              {delta < 0 ? '▼' : '▲'}{Math.abs(delta).toFixed(2)}
            </span>
          )}
        </span>
      </Tooltip>
    )
  }, [openDrill, t])

  const groupColumns = useCallback((g: MatrixGroup): ColumnsType<MatrixRow> => ([
    {
      title: t('availMs.colItem'), dataIndex: 'key', width: 150, fixed: 'left',
      render: (k: string) => <Text strong>{rowLabel(k)}</Text>,
    },
    ...g.columns.map(c => ({
      title: c, key: c, align: 'right' as const, width: 165,
      render: (_: unknown, row: MatrixRow) => {
        // 维度不同 -> 下钻参数落在不同分量上：区域表按行取区域，其余两表区域恒为 ALL
        const tg = g.dim === 'region'
          ? { region: row.key, tech: c, site_type: '' }
          : g.dim === 'tech'
            ? { region: 'ALL', tech: row.key, site_type: c }
            : { region: 'ALL', tech: c, site_type: row.key }
        return renderCell(row.cells[c],
          { ...tg, label: `${t(DIM_TITLE_KEY[g.dim])} ${rowLabel(row.key)} · ${c}` })
      },
    })),
  ]), [renderCell, rowLabel, t])

  /** 曲线上的点 -> 下钻目标（与表格单元格同一套映射，保证"点线"与"点数字"落到同一处） */
  const pointTarget = useCallback((dim: Dim, key: string): CellTarget => ({
    region: dim === 'region' ? key : 'ALL',
    tech: dim === 'tech' ? key : '',
    site_type: dim === 'site_type' ? key : '',
    label: `${t(DIM_TITLE_KEY[dim])} ${rowLabel(key)}`,
  }), [rowLabel, t])

  /* ---- 页签内容：按**页签自己的档位**渲染，不读当前激活档的共享状态 ---- */
  const renderGroups = (g: Gran) => {
    const key = `${g}|${valueByGran[g] || '__latest__'}|${thr}`
    const data = cache[key]
    if (!data) return <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
    if (!data.matrix.groups.length) return <Empty description={t('availMs.empty')} />

    const tr = data.trend
    const unmatched = data.matrix.summary.unmatched_share
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
        {data.matrix.groups.map(grp => {
          // 区域维度：UNMATCHED 那条线不进图（量级 78% 会把 88%~100% 的纵轴压扁），
          // 改在图表下方用一行字说明并指向表格末行 —— 图与表口径仍然一致，只是不画它。
          const all = tr?.dims?.[grp.dim] || []
          const series = grp.dim === 'region'
            ? all.filter(s => s.key !== 'UNMATCHED')
            : all
          const hasChart = !!tr && (tr.categories?.length || 0) > 1 && series.length > 0
          return (
            <CardBase
              key={grp.dim}
              title={t(DIM_TITLE_KEY[grp.dim])}
              extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('availMs.clickHint')}</Text>}
            >
              {hasChart && (
                <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('availMs.trendCaption', {
                      n: tr!.meta.points, start: tr!.meta.start, end: tr!.meta.end,
                    })}
                  </Text>
                  <AvailMsTrend
                    categories={tr!.categories}
                    series={series}
                    thresholdPct={thresholdPct}
                    labelOf={rowLabel}
                    onPoint={(k, v) => openDrill(pointTarget(grp.dim, k), undefined, v)}
                  />
                  {grp.dim === 'region' && unmatched != null && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('availMs.trendNoteUnmatched', { v: (unmatched * 100).toFixed(2) })}
                    </Text>
                  )}
                </div>
              )}
              <Table
                rowKey="key"
                size="small"
                pagination={false}
                columns={groupColumns(grp)}
                dataSource={grp.rows}
                scroll={{ x: 720 }}
              />
            </CardBase>
          )
        })}
      </div>
    )
  }

  /* ---- 汇总卡：点卡片也能下钻（全网 × 制式） ---- */
  const summary = matrix?.summary
  const statCards = summary
    ? ['2G', '3G', '4G'].map(tk => {
      const v = summary.by_tech?.[tk]
      const below = v != null && v < thr
      return (
        <Col xs={12} sm={12} md={6} key={tk}>
          <StatCard
            title={t('availMs.kpiTech', { tech: tk })}
            value={v == null ? '—' : (v * 100).toFixed(2)}
            suffix={v == null ? '' : '%'}
            accentColor={v == null ? WH.textMuted : (below ? WH.danger : WH.ok)}
            subText={matrix ? `${t('availMs.periodLabel')} ${matrix.meta.value}` : undefined}
            onClick={e => openDrill({ region: 'ALL', tech: tk, site_type: '',
              label: `${t(DIM_TITLE_KEY.region)} ${rowLabel('ALL')} · ${tk}` },
              { x: e.clientX, y: e.clientY })}
          />
        </Col>
      )
    })
    : []

  /* ---- 导出：多 sheet（Summary + 三个维度），百分比写数值便于在 Excel 里算 ---- */
  const exportPage = useCallback(async () => {
    if (!matrix) return
    const val = matrix.meta.value || 'latest'
    const sheets: ReportSheetSpec[] = [{
      name: 'Summary',
      title: t('availMs.exportTitle'),
      subtitle: `${gran} | ${val} | ${t('availMs.threshold')} ${thresholdPct}% | `
        + `${t('availMs.dataThrough')} ${matrix.meta.data_through} | `
        + `${t('availMs.generatedAt')} ${dayjs().format('YYYY-MM-DD HH:mm:ss')}`,
      header: [t('availMs.colItem'), t('availMs.colValue')],
      rows: [
        [t('availMs.periodLabel'), matrix.meta.value],
        [t('availMs.prevPeriod'), matrix.meta.prev_value || '—'],
        [t('availMs.dataThrough'), matrix.meta.data_through],
        ['2G', matrix.summary.by_tech?.['2G'] == null ? '—' : Number((matrix.summary.by_tech['2G'] * 100).toFixed(4))],
        ['3G', matrix.summary.by_tech?.['3G'] == null ? '—' : Number((matrix.summary.by_tech['3G'] * 100).toFixed(4))],
        ['4G', matrix.summary.by_tech?.['4G'] == null ? '—' : Number((matrix.summary.by_tech['4G'] * 100).toFixed(4))],
        [t('availMs.unmatchedShare'),
          matrix.summary.unmatched_share == null ? '—' : Number((matrix.summary.unmatched_share * 100).toFixed(4))],
        [t('availMs.warnTitle'),
          (matrix.meta.warnings || []).map(w => (warnKey(w) ? t(warnKey(w) as string) : w)).join(' / ')],
      ],
      numericCols: [1],
    }]
    for (const grp of matrix.groups) {
      sheets.push({
        name: t(DIM_TITLE_KEY[grp.dim]),
        title: `${t(DIM_TITLE_KEY[grp.dim])}（${val}）`,
        subtitle: `${t('availMs.colItem')} × ${grp.columns.join(' / ')}`,
        header: [t('availMs.colItem'), ...grp.columns],
        rows: grp.rows.map(r => [
          rowLabel(r.key),
          ...grp.columns.map(c => {
            const cell = r.cells[c]
            return cell?.availability == null ? '—' : Number((cell.availability * 100).toFixed(4))
          }),
        ]),
        numericCols: grp.columns.map((_, i) => i + 1),
      })
    }
    // 曲线上的数据也导出：周期为行、维度取值为列，与图严格同源同口径
    if (trend && (trend.categories?.length || 0) > 0) {
      for (const grp of matrix.groups) {
        const series = trend.dims?.[grp.dim] || []
        if (!series.length) continue
        sheets.push({
          name: `${t(DIM_TITLE_KEY[grp.dim])}${t('availMs.sheetTrend')}`,
          title: `${t(DIM_TITLE_KEY[grp.dim])} · ${t('availMs.historyChart')}`,
          subtitle: `${trend.meta.start} ~ ${trend.meta.end}（${trend.meta.points} ${t('availMs.periodLabel')}）`
            + ` | ${t('availMs.trendFracHint')}`,
          header: [t('availMs.periodLabel'), ...series.map(s => rowLabel(s.key))],
          rows: trend.categories.map((cat, i) => [
            cat,
            ...series.map(s => {
              const v = s.values[i]
              return v == null ? '—' : Number((v * 100).toFixed(4))
            }),
          ]),
          numericCols: series.map((_, i) => i + 1),
        })
      }
    }
    await exportReport(sheets, `avail_ms_${gran}_${val}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [matrix, trend, gran, thresholdPct, rowLabel, t])

  const exportDrill = useCallback(async () => {
    if (!target) return
    const suffix = `${gran}_${drillValue}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`
    const sheets: ReportSheetSpec[] = []
    if (modalTab === 'period' && drill) {
      sheets.push({
        name: t('availMs.detailSeries'),
        title: `${target.label} · ${t('availMs.detailSeries')}`,
        subtitle: `${gran} ${drillValue} | ${t('availMs.periodLabel')}`,
        header: [t('availMs.colDate'), t('availMs.colNum'), t('availMs.colDen'), t('availMs.colAvail')],
        rows: (drill.series || []).map(s => [s.key, s.numerator, s.denominator,
          s.availability == null ? '—' : Number((s.availability * 100).toFixed(4))]),
        numericCols: [1, 2, 3],
      })
      sheets.push({
        name: t('availMs.detailBreakdown'),
        title: `${target.label} · ${t('availMs.detailBreakdown')}`,
        subtitle: `${gran} ${drillValue}`,
        header: [t('availMs.colCellGroup'), '2G/3G/4G', t('availMs.colSiteType'),
          t('availMs.colNum'), t('availMs.colDen'), t('availMs.colAvail')],
        rows: (drill.breakdown || []).map(b => [b.cell_group || b.key, b.tech || '—',
          b.site_type || '—', b.numerator, b.denominator,
          b.availability == null ? '—' : Number((b.availability * 100).toFixed(4))]),
        numericCols: [3, 4, 5],
      })
    }
    if (modalTab === 'tt' && tt) {
      sheets.push({
        name: 'TT',
        title: `${target.label} · ${t('availMs.tabTt')}`,
        subtitle: `${tt.meta.start} ~ ${tt.meta.end} | ${t('availMs.ttTotal')} ${tt.meta.total}`,
        header: [t('availMs.colTtNo'), t('availMs.colTitle'), t('availMs.colSeverity'),
          t('availMs.colSite'), t('availMs.colRegion'), t('availMs.colSiteType'),
          t('availMs.colOccur'), t('availMs.colMttr'), t('availMs.colStatus')],
        rows: (tt.rows || []).map(r => [r.tt_no, r.title, r.ticket_severity, r.site_name,
          r.region, r.site_type_norm, r.alarm_occur_time || r.created_time,
          r.mttr_minutes, r.status]),
        numericCols: [7],
      })
    }
    if (sheets.length) await exportReport(sheets, `avail_ms_drill_${suffix}`)
  }, [target, modalTab, drill, tt, gran, drillValue, t])

  /* ---- 弹窗内趋势图（近 30 期，ECharts 用主题实值） ---- */
  const historyOption = useMemo(() => {
    const hist = drill?.history || []
    const keys = hist.map(h => h.key)
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
      grid: { left: 56, right: 20, top: 24, bottom: 44 },
      xAxis: {
        type: 'category', data: keys,
        axisLabel: { ...axisLabel(isDark), rotate: keys.length > 12 ? 35 : 0 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value', min: (v: any) => Math.max(0, Math.floor(v.min - 1)),
        max: (v: any) => Math.min(100, Math.ceil(v.max + 1)),
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
        splitLine: splitLine(isDark),
      },
      series: [{
        type: 'line', smooth: true, showSymbol: keys.length <= 12,
        data: hist.map(h => (h.availability == null ? null : Number((h.availability * 100).toFixed(3)))),
        itemStyle: { color: palette.teal },
        lineStyle: { color: palette.teal, width: 2 },
        markLine: {
          silent: true, symbol: 'none',
          data: [{ yAxis: thresholdPct, name: t('availMs.threshold') }],
          lineStyle: { color: palette.sev.Major, type: 'dashed' },
          label: { color: palette.sev.Major, formatter: `${thresholdPct}%` },
        },
      }],
    }
  }, [drill, isDark, palette, thresholdPct, t])

  const detailColumns: ColumnsType<SeriesItem> = useMemo(() => ([
    { title: t('availMs.colDate'), dataIndex: 'key', width: 130 },
    { title: t('availMs.colNum'), dataIndex: 'numerator', align: 'right', width: 100 },
    { title: t('availMs.colDen'), dataIndex: 'denominator', align: 'right', width: 100 },
    {
      title: t('availMs.colAvail'), dataIndex: 'availability', align: 'right', width: 120,
      render: (v: number | null, r: SeriesItem) => (
        <Text style={{ color: v == null ? WH.textMuted : (r.below ? WH.danger : WH.ok) }}>
          {fmtPct(v)}
        </Text>
      ),
    },
  ]), [t])

  const breakdownColumns: ColumnsType<SeriesItem> = useMemo(() => ([
    { title: t('availMs.colCellGroup'), dataIndex: 'cell_group', width: 150 },
    { title: t('availMs.colTech'), dataIndex: 'tech', width: 80, render: (v: string) => v || '—' },
    { title: t('availMs.colSiteType'), dataIndex: 'site_type', width: 100, render: (v: string) => v || '—' },
    { title: t('availMs.colNum'), dataIndex: 'numerator', align: 'right', width: 100 },
    { title: t('availMs.colDen'), dataIndex: 'denominator', align: 'right', width: 100 },
    {
      title: t('availMs.colAvail'), dataIndex: 'availability', align: 'right', width: 120,
      render: (v: number | null, r: SeriesItem) => (
        <Text style={{ color: v == null ? WH.textMuted : (r.below ? WH.danger : WH.ok) }}>
          {fmtPct(v)}
        </Text>
      ),
    },
  ]), [t])

  const ttColumns: ColumnsType<TtRow> = useMemo(() => ([
    { title: t('availMs.colTtNo'), dataIndex: 'tt_no', width: 140 },
    {
      title: t('availMs.colTitle'), dataIndex: 'title', ellipsis: true,
      render: (v: string) => <Tooltip title={v}>{v || '—'}</Tooltip>,
    },
    { title: t('availMs.colSeverity'), dataIndex: 'ticket_severity', width: 80 },
    { title: t('availMs.colSite'), dataIndex: 'site_name', width: 150, ellipsis: true },
    { title: t('availMs.colRegion'), dataIndex: 'region', width: 110 },
    { title: t('availMs.colSiteType'), dataIndex: 'site_type_norm', width: 90 },
    { title: t('availMs.colOccur'), dataIndex: 'alarm_occur_time', width: 160 },
    {
      title: t('availMs.colMttr'), dataIndex: 'mttr_minutes', align: 'right', width: 90,
      render: (v: number | null) => fmtNum(v),
    },
    { title: t('availMs.colStatus'), dataIndex: 'status', width: 100 },
  ]), [t])

  /* ---- 警告条：口径说明与失败都必须在页面上可见 ---- */
  const warnAlerts = (codes: string[], err?: string) => (
    <Space direction="vertical" style={{ width: '100%' }} size={4}>
      {codes.map((code, i) => {
        const k = warnKey(code)
        if (!k) return null
        return (
          <Alert
            key={`${code}-${i}`}
            type={isErrorWarn(code) ? 'error' : 'warning'}
            showIcon
            message={t(k)}
            description={isErrorWarn(code) && err ? err : undefined}
          />
        )
      })}
    </Space>
  )

  const valueOptions = useMemo(() => {
    const list = gran === 'day' ? options?.days : gran === 'week' ? options?.weeks : options?.months
    return (list || []).map(v => ({ value: v, label: v }))
  }, [gran, options])

  // 「正在取第一次数」与「取回来是空的」是两回事，界面必须分开表达
  const loadingPeriod = drillLoading && !drill
  const loadingTt = drillLoading && !tt

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap align="center">
          <Text type="secondary" style={{ fontSize: 12 }}>{t('availMs.periodLabel')}</Text>
          <Select
            size="small"
            style={{ width: 150 }}
            value={valueByGran[gran] || options?.latest?.[gran] || undefined}
            onChange={v => setValueByGran(prev => ({ ...prev, [gran]: v }))}
            options={valueOptions}
            showSearch
            aria-label={t('availMs.periodLabel')}
          />
          <Tooltip title={t('availMs.thresholdTip')}>
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('availMs.threshold')}</Text>
              <InputNumber
                size="small" min={0} max={100} step={0.01} addonAfter="%"
                style={{ width: 108 }}
                value={thresholdPct}
                onChange={v => setThresholdPct(v ?? 99.65)}
              />
            </Space>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} loading={!!loadingKey}
            onClick={() => void loadMatrix(cacheKey)}>{t('availMs.refresh')}</Button>
          <Button size="small" icon={<DownloadOutlined />} disabled={!matrix}
            onClick={() => void exportPage()}>{t('common.exportExcel')}</Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('availMs.dataThrough')} {matrix?.meta.data_through || options?.data_through || '—'}
          </Text>
        </Space>
      </CardBase>

      {/* ② 口径警告 */}
      {matrix && (matrix.meta.warnings?.length || matrix.meta.error)
        ? warnAlerts(matrix.meta.warnings || [], matrix.meta.error)
        : null}

      {/* ③ 汇总卡（可点下钻） */}
      {!!statCards.length && (
        <Row gutter={[12, 12]}>
          {statCards}
          <Col xs={12} sm={12} md={6}>
            <StatCard
              title={t('availMs.unmatchedShare')}
              value={summary?.unmatched_share == null ? '—'
                : (summary.unmatched_share * 100).toFixed(2)}
              suffix={summary?.unmatched_share == null ? '' : '%'}
              accentColor={WH.warn}
              subText={t('availMs.unmatchedTip')}
            />
          </Col>
        </Row>
      )}

      {/* ④ 日 / 周 / 月 页签 */}
      <Tabs
        size="small"
        activeKey={gran}
        onChange={k => setGran(k as Gran)}
        items={GRANS.map(g => ({
          key: g,
          label: g === 'day' ? t('availMs.periodDay')
            : g === 'week' ? t('availMs.periodWeek') : t('availMs.periodMonth'),
          children: renderGroups(g),
        }))}
      />

      {/* ⑤ 下钻弹窗：时间明细 / 相关 TT 工单 */}
      <DraggableClickModal
        open={open}
        title={`${t('availMs.drillTitle')} · ${target?.label || ''}`}
        anchor={anchor}
        width={960}
        onClose={() => setOpen(false)}
      >
        <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {/* 用 drillValue（可能来自曲线上的历史点），不是当前页签选中期 */}
            {gran} {drillValue}
          </Text>
          {drill?.cell && (
            <>
              <Text strong style={{ color: drill.cell.below ? WH.danger : WH.ok }}>
                {fmtPct(drill.cell.availability)}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('availMs.colNum')} {drill.cell.numerator} / {t('availMs.colDen')} {drill.cell.denominator}
              </Text>
              {drill.cell.delta_pp != null && (
                <Text style={{ fontSize: 12, color: drill.cell.delta_pp < 0 ? WH.danger : WH.ok }}>
                  {t('availMs.prevPeriod')} {fmtPct(drill.cell.prev_availability)}
                  （{drill.cell.delta_pp < 0 ? '▼' : '▲'}{Math.abs(drill.cell.delta_pp).toFixed(2)}pp）
                </Text>
              )}
            </>
          )}
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void exportDrill()}>
            {t('common.exportExcel')}
          </Button>
        </Space>

        <Tabs
          size="small"
          activeKey={modalTab}
          onChange={onModalTab}
          items={[
            {
              key: 'period',
              label: `${t('availMs.tabDetail')}${drill?.series ? ` (${drill.series.length})` : ''}`,
              // 首次取数未回来时给一个 Loading 占位，**不要**先渲染三块「暂无数据」——
              // 那会让人误判成"这个组合没数据"（2026-09-28 实测发现）。
              children: loadingPeriod ? (
                <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}><Spin /></div>
              ) : (
                <>
                  {drill?.meta.warnings?.length ? warnAlerts(drill.meta.warnings) : null}
                  <CardBase title={t('availMs.historyChart')}>
                    {(drill?.history?.length || 0) > 1
                      ? <ReactECharts option={historyOption} style={{ height: 220 }} notMerge />
                      : <Empty description={t('availMs.empty')} />}
                  </CardBase>
                  <CardBase title={t('availMs.detailSeries')} style={{ marginTop: 'var(--wh-space-sm)' }}>
                    <Table rowKey="key" size="small" pagination={{ pageSize: 10 }}
                      columns={detailColumns} dataSource={drill?.series || []}
                      scroll={{ x: 520 }} />
                  </CardBase>
                  <CardBase title={t('availMs.detailBreakdown')} style={{ marginTop: 'var(--wh-space-sm)' }}>
                    <Table rowKey="key" size="small" pagination={false}
                      columns={breakdownColumns} dataSource={drill?.breakdown || []}
                      scroll={{ x: 640 }} />
                  </CardBase>
                </>
              ),
            },
            {
              key: 'tt',
              label: `${t('availMs.tabTt')}${tt?.meta.total != null ? ` (${tt.meta.total})` : ''}`,
              children: loadingTt ? (
                <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}>
                  <Spin tip={t('availMs.ttLoading')}><div style={{ height: 80 }} /></Spin>
                </div>
              ) : (
                <>
                  {tt?.meta.warnings?.length ? warnAlerts(tt.meta.warnings, tt.meta.error) : null}
                  {tt?.meta.start && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('availMs.ttRange')} {tt.meta.start} ~ {tt.meta.end}
                      {tt.meta.unassigned ? ` · ${t('availMs.ttUnassigned', { n: tt.meta.unassigned })}` : ''}
                    </Text>
                  )}
                  <Table rowKey="tt_no" size="small" style={{ marginTop: 6 }}
                    columns={ttColumns} dataSource={tt?.rows || []}
                    pagination={{ pageSize: 10, showSizeChanger: true }}
                    scroll={{ x: 1080 }} />
                </>
              ),
            },
          ]}
        />
      </DraggableClickModal>
    </div>
  )
}
