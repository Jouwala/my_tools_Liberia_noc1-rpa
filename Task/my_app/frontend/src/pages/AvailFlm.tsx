/* ============================================================================
 * FLM 可用率（?page=avail_flm）
 * ----------------------------------------------------------------------------
 * 需求（图片：呈现内容 × 呈现形式 的表）：
 *   SN1 区域 × 制式        三个区域（Montserrado / North East / South West）× 2G/3G/4G
 *   SN2 区域 × 站点类型    三个区域 × Regular/Cool.i/ERA
 *   SN4 影响可用率的 TT 列表
 * 日 / 周 / 月 用页签切粒度（与 ?page=avail_ms 一致）。
 *
 * 数据源：后端 /api/avail-flm/*（读本机派生库 data/avail_recon.sqlite3，TT 读 eflow_tt）。
 * 口径与 avail_ms **同源同实现**（后端复用 avail_ms_service 的聚合），差别只在行列表头：
 *   avail_ms 行=ALL/三区域/UNMATCHED × 列=制式、制式×站点类型、站点类型×制式（三张表）
 *   本页     行=三个 FLM 区域（+未匹配末行）× 列=制式 / 站点类型（两张表）+ 页面级 TT 列表
 *
 * 两条已与用户确认的口径（2026-09-28，改前先看 backend/services/avail_flm_service.py 顶部）：
 *   ① 站点类型**不做范围限制**：需求表写的「NE 只有 Regular/Cool.i」与两个数据源都不符
 *      （站点主数据 NE 有 123 个 ERA 站点、派生库 NE 的 ERA 分母 6.5 万），故三个区域都显示三列；
 *   ② TT 列表列**本期全部工单**，不做「是否影响业务」判定（那会让含糊的定义看起来精确）。
 * 本页没有 ALL 行，故不适用 avail_ms 的「ALL ≠ 三区域相加」提示，改为「未匹配单列末行」。
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
// 曲线图组件与 avail_ms 页共用（多序列折线，点可下钻）
import AvailTrend from './AvailTrend'
import type { TrendSeries } from './AvailTrend'
import { exportReport } from '../utils/excelReport'
import type { ReportSheetSpec } from '../utils/excelReport'
import {
  getAvailFlmDrilldown, getAvailFlmMatrix, getAvailFlmOptions, getAvailFlmTrend, getAvailFlmTt,
} from '../api'

const { Text } = Typography

/* ---------------- 类型（与后端返回结构对齐） ---------------- */
type Gran = 'day' | 'week' | 'month'
/** 本页两张表的行都是区域，dim 只表示"列是哪一维" */
type Dim = 'region_tech' | 'region_site_type'
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
    threshold: number; regions: string[]; generated_at: string; elapsed_ms: number
    warnings: string[]; unknown_cell_groups?: string[]; error?: string
  }
  summary: {
    by_region: Record<string, Cell>
    by_tech: Record<string, Cell>
    all_regions: Cell | null
    unmatched_share: number | null
    rows_in_period: number
  }
  groups: MatrixGroup[]
}
interface Trend {
  meta: {
    period: Gran; value: string; start: string; end: string; points: number
    threshold: number; generated_at: string; warnings: string[]; error?: string
  }
  categories: string[]
  dims: { region: TrendSeries[]; site_type: TrendSeries[] }
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
  col_2g_down_site_count?: number | string
  col_3g_down_site_count?: number | string
  col_4g_down_site_count?: number | string
}
interface Tt {
  meta: {
    level?: DrillLevel; period: Gran; value: string; region: string; site_type?: string
    tech?: string; total?: number; returned?: number; truncated?: boolean
    unassigned?: number; start?: string; end?: string
    warnings: string[]; error?: string
  }
  rows: TtRow[]
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
/** 一个可下钻的目标：三个维度切片 + 弹窗标题用的可读标签 */
interface CellTarget { region: string; tech: string; site_type: string; label: string }

const GRANS: Gran[] = ['day', 'week', 'month']
/** 列标题键（间接引用，check:i18n 会列为未引用候选，**不要删**，删了界面显示键名） */
const DIM_TITLE_KEY: Record<Dim, string> = {
  region_tech: 'availFlm.dimRegionTech',
  region_site_type: 'availFlm.dimRegionSiteType',
}

/** 取不到数据一律 `—`，不得显示成 0 */
const fmtPct = (v: number | null | undefined, digits = 2) =>
  (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
const fmtNum = (v: number | string | null | undefined) => (v == null ? '—' : String(v))

/** 警告码 -> i18n 键。**刻意用显式 switch**：`t('availFlm.warn.' + code)` 会被
 *  `npm run check:i18n` 读成键名 `availFlm.warn.` 而报字典缺失（AGENTS.md 第三节 1b）。 */
function warnKey(code: string): string | null {
  switch (code) {
    case 'flm_unmatched_last_row': return 'availFlm.warn.unmatchedLastRow'
    case 'other_site_type_present': return 'availFlm.warn.otherSiteType'
    case 'unknown_cell_group': return 'availFlm.warn.unknownCellGroup'
    case 'no_data_for_period': return 'availFlm.warn.noDataForPeriod'
    case 'derived_db_missing': return 'availFlm.warn.derivedDbMissing'
    case 'combination_not_applicable': return 'availFlm.warn.combinationNotApplicable'
    case 'no_detail_for_cell': return 'availFlm.warn.noDetail'
    case 'unmatched_region_no_tt': return 'availFlm.warn.unmatchedNoTt'
    case 'tt_no_tech_filter': return 'availFlm.warn.ttNoTechFilter'
    case 'tt_truncated': return 'availFlm.warn.ttTruncated'
    case 'tt_fetch_capped': return 'availFlm.warn.ttFetchCapped'
    case 'tt_site_unassigned': return 'availFlm.warn.ttSiteUnassigned'
    case 'no_tt_in_period': return 'availFlm.warn.noTtInPeriod'
    case 'options_failed':
    case 'matrix_failed':
    case 'trend_failed': return 'availFlm.warn.loadFailed'
    case 'drilldown_failed':
    case 'tt_read_failed': return 'availFlm.warn.readFailed'
    default: return null
  }
}

/** 失败类警告用红色，其余为口径提示（黄色） */
const isErrorWarn = (code: string) =>
  ['derived_db_missing', 'options_failed', 'matrix_failed', 'trend_failed',
    'drilldown_failed', 'tt_read_failed'].includes(code)

export default function AvailFlm() {
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

  const reqValue = valueByGran[gran]
  const cacheKey = `${gran}|${reqValue || '__latest__'}|${thr}`
  const entry = cache[cacheKey]
  const matrix = entry?.matrix
  const trend = entry?.trend || null
  /** 当前实际在看的那一期：选择器停在"最新"时用后端解析出来的值，别显示空 */
  const currentValue = reqValue || matrix?.meta.value || options?.latest?.[gran] || ''

  /* ---- 页面级 TT 列表（本期全部工单，可按区域筛）---- */
  const [ttRegion, setTtRegion] = useState('')
  const [ttCache, setTtCache] = useState<Record<string, Tt>>({})
  const [ttLoadingKey, setTtLoadingKey] = useState('')
  const activeTtKey = `${gran}|${reqValue || '__latest__'}|${ttRegion || 'ALL'}`
  const activeTt = ttCache[activeTtKey]

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [target, setTarget] = useState<CellTarget | null>(null)
  const [drillValue, setDrillValue] = useState('')
  const [drill, setDrill] = useState<Drill | null>(null)
  const [drillTt, setDrillTt] = useState<Drill | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [modalTab, setModalTab] = useState<DrillLevel>('period')

  /* ---- 选项：失败不阻塞（页面主体仍可用） ---- */
  const loadOptions = useCallback(async () => {
    try {
      const r = await getAvailFlmOptions()
      setOptions((r.data || null) as Options | null)
    } catch {
      setOptions({ data_through: '', latest: {}, days: [], weeks: [], months: [],
        threshold: 0.9965, warnings: ['options_failed'] })
    }
  }, [])

  /** 矩阵与曲线**一起取**：各取各的会出现"表已刷新、图还是上一期"的错位 */
  const loadMatrix = useCallback(async (key: string) => {
    const [g, rawValue, rawThr] = key.split('|')
    const value = rawValue === '__latest__' ? '' : rawValue
    const threshold = Number(rawThr)
    setLoadingKey(key)
    const [mx, tr] = await Promise.allSettled([
      getAvailFlmMatrix({ period: g as Gran, value, threshold }),
      getAvailFlmTrend({ period: g as Gran, value, threshold }),
    ])
    let matrixData: Matrix
    if (mx.status === 'fulfilled') {
      matrixData = mx.value.data as Matrix
    } else {
      const e: any = mx.reason
      matrixData = {
        meta: { period: g as Gran, value: '', prev_value: '', data_through: '',
          threshold, regions: [], generated_at: '', elapsed_ms: 0,
          warnings: ['matrix_failed'], error: e?.message || String(e) },
        summary: { by_region: {}, by_tech: {}, all_regions: null, unmatched_share: null,
          rows_in_period: 0 },
        groups: [],
      }
    }
    let trendData: Trend | null = null
    if (tr.status === 'fulfilled') {
      trendData = tr.value.data as Trend
    } else {
      const e: any = tr.reason
      // 曲线单独失败不影响表格：只丢图
      trendData = {
        meta: { period: g as Gran, value: '', start: '', end: '', points: 0,
          threshold, generated_at: '', warnings: ['trend_failed'], error: e?.message || String(e) },
        categories: [], dims: { region: [], site_type: [] },
      }
    }
    setCache(prev => ({ ...prev, [key]: { matrix: matrixData, trend: trendData } }))
    setLoadingKey('')
  }, [])

  /** 页面级 TT 列表：只在**当前激活页签**按需取一次（月档可达 3600+ 条 / 1MB+，
   *  不能每次切页签都重取；取过的按 key 缓存，换区域筛选也是另一个 key）。 */
  const loadTt = useCallback(async (key: string) => {
    const [g, rawValue, region] = key.split('|')
    setTtLoadingKey(key)
    try {
      const r = await getAvailFlmTt({
        period: g as Gran,
        value: rawValue === '__latest__' ? '' : rawValue,
        region: region === 'ALL' ? '' : region,
      })
      setTtCache(prev => ({ ...prev, [key]: r.data as Tt }))
    } catch (e: any) {
      setTtCache(prev => ({ ...prev, [key]: {
        meta: { period: g as Gran, value: rawValue, region, warnings: ['tt_read_failed'],
          error: e?.message || String(e) },
        rows: [],
      } }))
    } finally {
      setTtLoadingKey('')
    }
  }, [])

  useEffect(() => { void loadOptions() }, [loadOptions])
  useEffect(() => {
    if (!matrix && loadingKey !== cacheKey) void loadMatrix(cacheKey)
  }, [cacheKey, matrix, loadingKey, loadMatrix])
  useEffect(() => {
    if (!activeTt && ttLoadingKey !== activeTtKey) void loadTt(activeTtKey)
  }, [activeTtKey, activeTt, ttLoadingKey, loadTt])

  /* ---- 下钻取数 ---- */
  const loadDrill = useCallback(async (
    level: DrillLevel, tg: { region: string; tech: string; site_type: string }, value: string,
  ) => {
    setDrillLoading(true)
    try {
      const r = await getAvailFlmDrilldown({
        level, period: gran, value: value || '', region: tg.region,
        tech: tg.tech, site_type: tg.site_type, threshold: thr,
      })
      if (level === 'tt') setDrillTt(r.data as Drill)
      else setDrill(r.data as Drill)
    } catch (e: any) {
      const failed: Drill = {
        meta: { level, period: gran, value, region: tg.region, tech: tg.tech,
          site_type: tg.site_type, warnings: ['drilldown_failed'], error: e?.message || String(e) },
        rows: [],
      }
      if (level === 'tt') setDrillTt(failed)
      else setDrill(failed)
    } finally {
      setDrillLoading(false)
    }
  }, [gran, thr])

  /** value 显式传入 = 从曲线上的某个点下钻（那个点属于历史某一期）；不传则用当前期 */
  const openDrill = useCallback((
    tg: CellTarget, at?: { x: number; y: number }, value?: string,
  ) => {
    const v = value || currentValue
    setDrillValue(v)
    setTarget(tg)
    setAnchor(at || null)
    setDrill(null)
    setDrillTt(null)
    setModalTab('period')
    setOpen(true)
    void loadDrill('period', tg, v)
  }, [loadDrill, currentValue])

  /** 弹窗内切到 TT 页签时才取工单（单月数千条，不做无谓预取） */
  const onModalTab = useCallback((k: string) => {
    const lv = (k === 'tt' ? 'tt' : 'period') as DrillLevel
    setModalTab(lv)
    if (!target) return
    if (lv === 'tt' && !drillTt) void loadDrill('tt', target, drillValue)
  }, [target, drillTt, drillValue, loadDrill])

  /* ---- 标签：区域名/制式是业务原值不翻译，未匹配桶与站点类型 Other 走 i18n ---- */
  const rowLabel = useCallback((key: string) => {
    if (key === 'UNMATCHED') return t('availFlm.regionUnmatched')
    if (key === 'ALL') return t('availFlm.regionAll')
    if (key === 'Other') return t('availFlm.siteTypeOther')
    return key
  }, [t])

  /* ---- 单元格：可点下钻，未达标染红，`—` = 口径上不存在或当期无数据 ---- */
  const renderCell = useCallback((cell: Cell | undefined, tg: CellTarget) => {
    if (!cell || cell.availability == null) return <Text type="secondary">—</Text>
    const color = cell.below ? WH.danger : WH.ok
    const delta = cell.delta_pp
    return (
      <Tooltip title={`${t('availFlm.colNum')} ${cell.numerator} / ${t('availFlm.colDen')} ${cell.denominator}`}>
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
      title: t('availFlm.colItem'), dataIndex: 'key', width: 180, fixed: 'left' as const,
      render: (k: string) => <Text strong>{rowLabel(k)}</Text>,
    },
    ...g.columns.map(c => ({
      title: c, key: c, align: 'right' as const, width: 165,
      render: (_: unknown, row: MatrixRow) => {
        // 两张表都是"区域行"：列不同 -> 下钻参数落在不同分量上
        const tg = g.dim === 'region_tech'
          ? { region: row.key, tech: c, site_type: '' }
          : { region: row.key, tech: '', site_type: c }
        return renderCell(row.cells[c],
          { ...tg, label: `${t(DIM_TITLE_KEY[g.dim])} ${rowLabel(row.key)} · ${c}` })
      },
    })),
  ]), [renderCell, rowLabel, t])

  /** 曲线上的点 -> 下钻目标 */
  const pointTarget = useCallback((dim: keyof Trend['dims'], key: string): CellTarget => ({
    region: dim === 'region' ? key : 'ALL',
    tech: '',
    site_type: dim === 'site_type' ? key : '',
    label: dim === 'region'
      ? `${t('availFlm.dimRegion')} ${rowLabel(key)}`
      : `${t('availFlm.dimSiteType')} ${rowLabel(key)}`,
  }), [rowLabel, t])

  /* ---- 区域 KPI 卡（每个区域一张，可点下钻） ---- */
  const statCards = useMemo(() => {
    const by = matrix?.summary?.by_region || {}
    const regions = matrix?.meta?.regions?.length ? matrix.meta.regions
      : options?.latest ? ['Montserrado', 'North East', 'South West'] : []
    return regions.map(rk => {
      const cell = by[rk]
      const v = cell?.availability ?? null
      const below = v != null && v < thr
      return (
        <Col xs={12} sm={12} md={8} key={rk}>
          <StatCard
            title={t('availFlm.kpiRegion', { region: rk })}
            value={v == null ? '—' : (v * 100).toFixed(2)}
            suffix={v == null ? '' : '%'}
            accentColor={v == null ? WH.textMuted : (below ? WH.danger : WH.ok)}
            subText={matrix ? `${t('availFlm.periodLabel')} ${matrix.meta.value}` : undefined}
            onClick={e => openDrill(
              { region: rk, tech: '', site_type: '', label: `${t('availFlm.dimRegion')} ${rk}` },
              { x: e.clientX, y: e.clientY })}
          />
        </Col>
      )
    })
  }, [matrix, options, thr, t, openDrill])

  /* ---- 页面级 TT 列表 ---- */
  const ttColumns: ColumnsType<TtRow> = useMemo(() => ([
    {
      title: t('availFlm.colTtNo'), dataIndex: 'tt_no', width: 150, fixed: 'left' as const,
      render: (v: string, r: TtRow) => (
        // 工单 -> 它所属「区域 × 站点类型」的可用率与同期全部工单（反向定位到格子）
        <Tooltip title={t('availFlm.ttRowHint')}>
          <span
            role="button"
            tabIndex={0}
            style={{ cursor: 'pointer', color: WH.blue, fontWeight: 600 }}
            onClick={e => openDrill({
              region: r.region || 'ALL', tech: '', site_type: r.site_type_norm || '',
              label: `${t('availFlm.dimRegion')} ${rowLabel(r.region || 'ALL')} · ${r.site_type_norm || '—'}`,
            }, { x: e.clientX, y: e.clientY })}
            onKeyDown={e => { if (e.key === 'Enter') openDrill({
              region: r.region || 'ALL', tech: '', site_type: r.site_type_norm || '',
              label: `${t('availFlm.dimRegion')} ${rowLabel(r.region || 'ALL')} · ${r.site_type_norm || '—'}`,
            }) }}
          >
            {v || '—'}
          </span>
        </Tooltip>
      ),
    },
    {
      title: t('availFlm.colTitle'), dataIndex: 'title', ellipsis: true,
      render: (v: string) => <Tooltip title={v}>{v || '—'}</Tooltip>,
    },
    { title: t('availFlm.colSeverity'), dataIndex: 'ticket_severity', width: 80 },
    {
      title: t('availFlm.colSite'), dataIndex: 'site_name', width: 160, ellipsis: true,
      render: (v: string, r: TtRow) => <Tooltip title={`${v || ''} ${r.site_id || ''}`}>{v || '—'}</Tooltip>,
    },
    { title: t('availFlm.colRegion'), dataIndex: 'region', width: 110, render: (v: string) => v || '—' },
    { title: t('availFlm.colSiteType'), dataIndex: 'site_type_norm', width: 90, render: (v: string) => v || '—' },
    {
      title: t('availFlm.colDownSites'), key: 'down', width: 130, align: 'right' as const,
      render: (_: unknown, r: TtRow) =>
        `${fmtNum(r.col_2g_down_site_count)}/${fmtNum(r.col_3g_down_site_count)}/${fmtNum(r.col_4g_down_site_count)}`,
    },
    {
      title: t('availFlm.colMttr'), dataIndex: 'mttr_minutes', align: 'right' as const, width: 100,
      render: (v: number | null) => fmtNum(v),
    },
    {
      title: t('availFlm.colOccur'), dataIndex: 'alarm_occur_time', width: 160,
      render: (v: string, r: TtRow) => v || r.created_time || '—',
    },
    { title: t('availFlm.colStatus'), dataIndex: 'status', width: 110, ellipsis: true },
    { title: t('availFlm.colHandler'), dataIndex: 'current_handler', width: 120, ellipsis: true },
  ]), [openDrill, rowLabel, t])

  const warnAlerts = (codes: string[], err?: string) => (
    <Space direction="vertical" style={{ width: '100%' }} size={4}>
      {codes.map((code, i) => {
        const k = warnKey(code)
        if (!k) return null
        return (
          <Alert key={`${code}-${i}`} type={isErrorWarn(code) ? 'error' : 'warning'} showIcon
            message={t(k)} description={isErrorWarn(code) && err ? err : undefined} />
        )
      })}
    </Space>
  )

  /* ---- 页签内容：按**页签自己的档位**渲染（不读激活档的共享状态） ---- */
  const renderTab = (g: Gran) => {
    const key = `${g}|${valueByGran[g] || '__latest__'}|${thr}`
    const data = cache[key]
    if (!data) return <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
    const mx = data.matrix
    const tr = data.trend
    const unmatched = mx.summary?.unmatched_share
    const ttKey = `${g}|${valueByGran[g] || '__latest__'}|${ttRegion || 'ALL'}`
    const tt = ttCache[ttKey]
    const ttLoading = ttLoadingKey === ttKey

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
        {mx.groups.map(grp => {
          // 区域维度的趋势线只画三个 FLM 区域（后端已收窄，这里不再过滤）；
          // 站点类型维度的线同理只含 Regular/Cooli/ERA
          const dimKey = grp.dim === 'region_tech' ? 'region' : 'site_type'
          const series = tr?.dims?.[dimKey] || []
          const hasChart = !!tr && (tr.categories?.length || 0) > 0 && series.length > 0
          return (
            <CardBase key={grp.dim} title={t(DIM_TITLE_KEY[grp.dim])}
              extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('availFlm.clickHint')}</Text>}>
              {hasChart && (
                <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('availFlm.trendCaption', {
                      n: tr!.meta.points, start: tr!.meta.start, end: tr!.meta.end,
                    })}
                  </Text>
                  <AvailTrend
                    categories={tr!.categories}
                    series={series}
                    thresholdPct={thresholdPct}
                    labelOf={rowLabel}
                    onPoint={(k, v) => openDrill(pointTarget(dimKey, k), undefined, v)}
                    emptyText={t('availFlm.empty')}
                    ariaText={t('availFlm.trendAria')}
                  />
                </div>
              )}
              <Table rowKey="key" size="small" pagination={false}
                columns={groupColumns(grp)} dataSource={grp.rows} scroll={{ x: 700 }} />
            </CardBase>
          )
        })}

        {/* SN4：影响可用率的 TT 列表（页面级，按区域筛；口径见文件头第②条） */}
        <CardBase
          title={t('availFlm.ttTitle')}
          extra={(
            <Space size={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {tt?.meta.total != null
                  ? t('availFlm.ttCount', { n: tt.meta.total })
                  : (ttLoading ? t('availFlm.ttLoading') : '')}
              </Text>
              <Select
                size="small" style={{ width: 150 }} value={ttRegion || 'ALL'}
                onChange={setTtRegion} aria-label={t('availFlm.ttRegionFilter')}
                options={[
                  { value: 'ALL', label: t('availFlm.ttAllRegions') },
                  ...(mx.meta.regions || []).map(r => ({ value: r, label: r })),
                ]}
              />
            </Space>
          )}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>{t('availFlm.ttNote')}</Text>
          {tt?.meta.warnings?.length ? (
            <div style={{ marginTop: 6 }}>{warnAlerts(tt.meta.warnings, tt.meta.error)}</div>
          ) : null}
          {ttLoading && !tt ? (
            <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}><Spin /></div>
          ) : (
            <Table rowKey="tt_no" size="small" style={{ marginTop: 6 }}
              loading={ttLoading} columns={ttColumns} dataSource={tt?.rows || []}
              pagination={{ pageSize: 50, showSizeChanger: true, showTotal: n => t('availFlm.ttCount', { n }) }}
              scroll={{ x: 1360 }} />
          )}
        </CardBase>
      </div>
    )
  }

  /* ---- 导出：Summary + 两张矩阵 + 两组趋势 + TT 列表 ---- */
  const exportPage = useCallback(async () => {
    if (!matrix) return
    const val = matrix.meta.value || 'latest'
    const sheets: ReportSheetSpec[] = [{
      name: 'Summary',
      title: t('availFlm.exportTitle'),
      subtitle: `${gran} | ${val} | ${t('availFlm.threshold')} ${thresholdPct}% | `
        + `${t('availFlm.dataThrough')} ${matrix.meta.data_through} | `
        + `${t('availFlm.generatedAt')} ${dayjs().format('YYYY-MM-DD HH:mm:ss')}`,
      header: [t('availFlm.colItem'), t('availFlm.colValue')],
      rows: [
        [t('availFlm.periodLabel'), matrix.meta.value],
        [t('availFlm.prevPeriod'), matrix.meta.prev_value || '—'],
        [t('availFlm.dataThrough'), matrix.meta.data_through],
        ...(matrix.meta.regions || []).map(rk => [
          t('availFlm.kpiRegion', { region: rk }),
          matrix.summary.by_region?.[rk]?.availability == null ? '—'
            : Number((matrix.summary.by_region[rk].availability * 100).toFixed(4)),
        ]),
        [t('availFlm.kpiAll'),
          matrix.summary.all_regions?.availability == null ? '—'
            : Number((matrix.summary.all_regions.availability * 100).toFixed(4))],
        [t('availFlm.unmatchedShare'),
          matrix.summary.unmatched_share == null ? '—'
            : Number((matrix.summary.unmatched_share * 100).toFixed(4))],
        [t('availFlm.warnTitle'),
          (matrix.meta.warnings || []).map(w => (warnKey(w) ? t(warnKey(w) as string) : w)).join(' / ')],
      ],
      numericCols: [1],
    }]
    for (const grp of matrix.groups) {
      sheets.push({
        name: t(DIM_TITLE_KEY[grp.dim]),
        title: `${t(DIM_TITLE_KEY[grp.dim])}（${val}）`,
        subtitle: `${t('availFlm.colItem')} × ${grp.columns.join(' / ')}`,
        header: [t('availFlm.colItem'), ...grp.columns],
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
    // 曲线数据也导出：周期为行、维度取值为列，与图同源
    const trendPairs: Array<[keyof Trend['dims'], string]> = [
      ['region', t('availFlm.dimRegion')], ['site_type', t('availFlm.dimSiteType')],
    ]
    if (trend && (trend.categories?.length || 0) > 0) {
      for (const [dk, label] of trendPairs) {
        const ts = trend.dims?.[dk] || []
        if (!ts.length) continue
        sheets.push({
          name: `${label}${t('availFlm.sheetTrend')}`,
          title: `${label} · ${t('availFlm.trendTitle')}`,
          subtitle: `${trend.meta.start} ~ ${trend.meta.end}（${trend.meta.points} ${t('availFlm.periodLabel')}）`
            + ` | ${t('common.trendFracHint')}`,
          header: [t('availFlm.periodLabel'), ...ts.map(s => rowLabel(s.key))],
          rows: trend.categories.map((cat, i) => [
            cat,
            ...ts.map(s => {
              const v = s.values[i]
              return v == null ? '—' : Number((v * 100).toFixed(4))
            }),
          ]),
          numericCols: ts.map((_, i) => i + 1),
        })
      }
    }
    // TT 列表：只在已加载时导出（未加载说明用户没等到它，导出里注明而不是给一张空表）
    const ttNow = ttCache[`${gran}|${reqValue || '__latest__'}|${ttRegion || 'ALL'}`]
    if (ttNow?.rows?.length) {
      sheets.push({
        name: t('availFlm.ttTitle'),
        title: `${val} · ${t('availFlm.ttTitle')}`,
        subtitle: `${ttNow.meta.start || ''} ~ ${ttNow.meta.end || ''} | `
          + `${t('availFlm.ttCount', { n: ttNow.meta.total || 0 })}`
          + `${ttNow.meta.truncated ? ` | ${t('availFlm.warn.ttTruncated')}` : ''}`,
        header: [t('availFlm.colTtNo'), t('availFlm.colTitle'), t('availFlm.colSeverity'),
          t('availFlm.colSite'), t('availFlm.colRegion'), t('availFlm.colSiteType'),
          t('availFlm.colDownSites'), t('availFlm.colMttr'), t('availFlm.colOccur'),
          t('availFlm.colStatus'), t('availFlm.colHandler')],
        rows: ttNow.rows.map(r => [
          r.tt_no, r.title, r.ticket_severity, r.site_name, r.region, r.site_type_norm,
          `${fmtNum(r.col_2g_down_site_count)}/${fmtNum(r.col_3g_down_site_count)}/${fmtNum(r.col_4g_down_site_count)}`,
          r.mttr_minutes, r.alarm_occur_time || r.created_time, r.status, r.current_handler,
        ]),
        numericCols: [7],
      })
    }
    await exportReport(sheets, `avail_flm_${gran}_${val}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [matrix, trend, ttCache, gran, reqValue, ttRegion, thresholdPct, rowLabel, t])

  const exportDrill = useCallback(async () => {
    if (!target) return
    const suffix = `${gran}_${drillValue}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`
    const sheets: ReportSheetSpec[] = []
    if (modalTab === 'period' && drill) {
      sheets.push({
        name: t('availFlm.detailSeries'),
        title: `${target.label} · ${t('availFlm.detailSeries')}`,
        subtitle: `${gran} ${drillValue} | ${t('availFlm.periodLabel')}`,
        header: [t('availFlm.colDate'), t('availFlm.colNum'), t('availFlm.colDen'), t('availFlm.colAvail')],
        rows: (drill.series || []).map(s => [s.key, s.numerator, s.denominator,
          s.availability == null ? '—' : Number((s.availability * 100).toFixed(4))]),
        numericCols: [1, 2, 3],
      })
      sheets.push({
        name: t('availFlm.detailBreakdown'),
        title: `${target.label} · ${t('availFlm.detailBreakdown')}`,
        subtitle: `${gran} ${drillValue}`,
        header: [t('availFlm.colCellGroup'), '2G/3G/4G', t('availFlm.colSiteType'),
          t('availFlm.colNum'), t('availFlm.colDen'), t('availFlm.colAvail')],
        rows: (drill.breakdown || []).map(b => [b.cell_group || b.key, b.tech || '—',
          b.site_type || '—', b.numerator, b.denominator,
          b.availability == null ? '—' : Number((b.availability * 100).toFixed(4))]),
        numericCols: [3, 4, 5],
      })
    }
    if (modalTab === 'tt' && drillTt) {
      sheets.push({
        name: 'TT',
        title: `${target.label} · ${t('availFlm.tabTt')}`,
        subtitle: `${drillTt.meta.start} ~ ${drillTt.meta.end} | ${t('availFlm.ttTotal')} ${drillTt.meta.total}`,
        header: [t('availFlm.colTtNo'), t('availFlm.colTitle'), t('availFlm.colSeverity'),
          t('availFlm.colSite'), t('availFlm.colRegion'), t('availFlm.colSiteType'),
          t('availFlm.colOccur'), t('availFlm.colMttr'), t('availFlm.colStatus')],
        rows: (drillTt.rows || []).map(r => [r.tt_no, r.title, r.ticket_severity, r.site_name,
          r.region, r.site_type_norm, r.alarm_occur_time || r.created_time,
          r.mttr_minutes, r.status]),
        numericCols: [7],
      })
    }
    if (sheets.length) await exportReport(sheets, `avail_flm_drill_${suffix}`)
  }, [target, modalTab, drill, drillTt, gran, drillValue, t])

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
          data: [{ yAxis: thresholdPct, name: t('availFlm.threshold') }],
          lineStyle: { color: palette.sev.Major, type: 'dashed' },
          // 默认标签画在线的右端外侧，会被 grid.right 裁成"99…"；挪到线内侧上方
          label: {
            position: 'insideEndTop', color: palette.sev.Major,
            formatter: `${thresholdPct}%`, fontSize: 10,
          },
        },
      }],
    }
  }, [drill, isDark, palette, thresholdPct, t])

  const detailColumns: ColumnsType<SeriesItem> = useMemo(() => ([
    { title: t('availFlm.colDate'), dataIndex: 'key', width: 130 },
    { title: t('availFlm.colNum'), dataIndex: 'numerator', align: 'right', width: 100 },
    { title: t('availFlm.colDen'), dataIndex: 'denominator', align: 'right', width: 100 },
    {
      title: t('availFlm.colAvail'), dataIndex: 'availability', align: 'right', width: 120,
      render: (v: number | null, r: SeriesItem) => (
        <Text style={{ color: v == null ? WH.textMuted : (r.below ? WH.danger : WH.ok) }}>
          {fmtPct(v)}
        </Text>
      ),
    },
  ]), [t])

  const breakdownColumns: ColumnsType<SeriesItem> = useMemo(() => ([
    { title: t('availFlm.colCellGroup'), dataIndex: 'cell_group', width: 150 },
    { title: t('availFlm.colTech'), dataIndex: 'tech', width: 80, render: (v: string) => v || '—' },
    { title: t('availFlm.colSiteType'), dataIndex: 'site_type', width: 100, render: (v: string) => v || '—' },
    { title: t('availFlm.colNum'), dataIndex: 'numerator', align: 'right', width: 100 },
    { title: t('availFlm.colDen'), dataIndex: 'denominator', align: 'right', width: 100 },
    {
      title: t('availFlm.colAvail'), dataIndex: 'availability', align: 'right', width: 120,
      render: (v: number | null, r: SeriesItem) => (
        <Text style={{ color: v == null ? WH.textMuted : (r.below ? WH.danger : WH.ok) }}>
          {fmtPct(v)}
        </Text>
      ),
    },
  ]), [t])

  const drillTtColumns: ColumnsType<TtRow> = useMemo(() => ([
    { title: t('availFlm.colTtNo'), dataIndex: 'tt_no', width: 140 },
    {
      title: t('availFlm.colTitle'), dataIndex: 'title', ellipsis: true,
      render: (v: string) => <Tooltip title={v}>{v || '—'}</Tooltip>,
    },
    { title: t('availFlm.colSeverity'), dataIndex: 'ticket_severity', width: 80 },
    { title: t('availFlm.colSite'), dataIndex: 'site_name', width: 150, ellipsis: true },
    { title: t('availFlm.colRegion'), dataIndex: 'region', width: 110 },
    { title: t('availFlm.colSiteType'), dataIndex: 'site_type_norm', width: 90 },
    { title: t('availFlm.colOccur'), dataIndex: 'alarm_occur_time', width: 160 },
    {
      title: t('availFlm.colMttr'), dataIndex: 'mttr_minutes', align: 'right', width: 90,
      render: (v: number | null) => fmtNum(v),
    },
    { title: t('availFlm.colStatus'), dataIndex: 'status', width: 100 },
  ]), [t])

  const valueOptions = useMemo(() => {
    const key = gran === 'day' ? 'days' : gran === 'week' ? 'weeks' : 'months'
    return (options?.[key] || []).map(v => ({ value: v, label: v }))
  }, [options, gran])

  const loadingPeriod = drillLoading && !drill
  const loadingTt = drillLoading && !drillTt

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
      {/* ① 筛选条 */}
      <CardBase>
        <Space wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('availFlm.periodLabel')}</Text>
          <Select
            size="small" style={{ width: 150 }}
            value={valueByGran[gran] || options?.latest?.[gran] || undefined}
            onChange={v => setValueByGran(prev => ({ ...prev, [gran]: v }))}
            options={valueOptions} showSearch aria-label={t('availFlm.periodLabel')}
          />
          <Tooltip title={t('availFlm.thresholdTip')}>
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('availFlm.threshold')}</Text>
              <InputNumber size="small" min={0} max={100} step={0.01} addonAfter="%" style={{ width: 108 }}
                value={thresholdPct} onChange={v => setThresholdPct(v ?? 99.65)} />
            </Space>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} loading={!!loadingKey}
            onClick={() => void loadMatrix(cacheKey)}>{t('availFlm.refresh')}</Button>
          <Button size="small" icon={<DownloadOutlined />} disabled={!matrix}
            onClick={() => void exportPage()}>{t('common.exportExcel')}</Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('availFlm.dataThrough')} {matrix?.meta.data_through || options?.data_through || '—'}
          </Text>
        </Space>
      </CardBase>

      {/* ② 口径警告 */}
      {matrix && (matrix.meta.warnings?.length || matrix.meta.error)
        ? warnAlerts(matrix.meta.warnings || [], matrix.meta.error)
        : null}

      {/* ③ 区域 KPI 卡（可点下钻） */}
      {!!statCards.length && <Row gutter={[12, 12]}>{statCards}</Row>}

      {/* ④ 日 / 周 / 月 页签 */}
      <Tabs
        size="small" activeKey={gran} onChange={k => setGran(k as Gran)}
        items={GRANS.map(g => ({
          key: g,
          label: g === 'day' ? t('availFlm.periodDay')
            : g === 'week' ? t('availFlm.periodWeek') : t('availFlm.periodMonth'),
          children: renderTab(g),
        }))}
      />

      {/* ⑤ 下钻弹窗：时间明细 / 相关 TT 工单 */}
      <DraggableClickModal
        open={open}
        title={`${t('availFlm.drillTitle')} · ${target?.label || ''}`}
        anchor={anchor}
        width={960}
        onClose={() => setOpen(false)}
      >
        <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {gran} {drillValue}
          </Text>
          {drill?.cell && (
            <>
              <Text strong style={{ color: drill.cell.below ? WH.danger : WH.ok }}>
                {fmtPct(drill.cell.availability)}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('availFlm.colNum')} {drill.cell.numerator} / {t('availFlm.colDen')} {drill.cell.denominator}
              </Text>
              {drill.cell.delta_pp != null && (
                <Text style={{ fontSize: 12, color: drill.cell.delta_pp < 0 ? WH.danger : WH.ok }}>
                  {t('availFlm.prevPeriod')} {fmtPct(drill.cell.prev_availability)}
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
          size="small" activeKey={modalTab} onChange={onModalTab}
          items={[
            {
              key: 'period',
              label: `${t('availFlm.tabDetail')}${drill?.series ? ` (${drill.series.length})` : ''}`,
              // 首次取数未回来时给 Loading 占位，不要先渲染「暂无数据」误导用户
              children: loadingPeriod ? (
                <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}><Spin /></div>
              ) : (
                <>
                  {drill?.meta.warnings?.length ? warnAlerts(drill.meta.warnings) : null}
                  <CardBase title={t('availFlm.historyChart')}>
                    {(drill?.history?.length || 0) > 1
                      ? <ReactECharts option={historyOption} style={{ height: 220 }} notMerge />
                      : <Empty description={t('availFlm.empty')} />}
                  </CardBase>
                  <CardBase title={t('availFlm.detailSeries')} style={{ marginTop: 'var(--wh-space-sm)' }}>
                    <Table rowKey="key" size="small" pagination={{ pageSize: 10 }}
                      columns={detailColumns} dataSource={drill?.series || []} scroll={{ x: 520 }} />
                  </CardBase>
                  <CardBase title={t('availFlm.detailBreakdown')} style={{ marginTop: 'var(--wh-space-sm)' }}>
                    <Table rowKey="key" size="small" pagination={false}
                      columns={breakdownColumns} dataSource={drill?.breakdown || []} scroll={{ x: 640 }} />
                  </CardBase>
                </>
              ),
            },
            {
              key: 'tt',
              label: `${t('availFlm.tabTt')}${drillTt?.meta.total != null ? ` (${drillTt.meta.total})` : ''}`,
              children: loadingTt ? (
                <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}>
                  <Spin tip={t('availFlm.ttLoading')}><div style={{ height: 80 }} /></Spin>
                </div>
              ) : (
                <>
                  {drillTt?.meta.warnings?.length
                    ? warnAlerts(drillTt.meta.warnings, drillTt.meta.error) : null}
                  {drillTt?.meta.start && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('availFlm.ttRange')} {drillTt.meta.start} ~ {drillTt.meta.end}
                      {drillTt.meta.unassigned
                        ? ` · ${t('availFlm.ttUnassigned', { n: drillTt.meta.unassigned })}` : ''}
                    </Text>
                  )}
                  <Table rowKey="tt_no" size="small" style={{ marginTop: 6 }}
                    columns={drillTtColumns} dataSource={drillTt?.rows || []}
                    pagination={{ pageSize: 10, showSizeChanger: true }} scroll={{ x: 1080 }} />
                </>
              ),
            },
          ]}
        />
      </DraggableClickModal>
    </div>
  )
}
