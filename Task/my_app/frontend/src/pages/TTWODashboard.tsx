// TT&WO Dashboard 前端页面 - Warehouse 暗色科技风
import { useEffect, useState, useMemo, useCallback } from 'react'
import { cachedGet } from '../cache'
import { Card, Row, Col, Select, Segmented, DatePicker, Space, Tag, Tooltip, Statistic, Empty, Spin, Alert, Table, Input, Button, Badge, Tabs } from 'antd'
import {
  ThunderboltOutlined, FileTextOutlined, NumberOutlined, ClockCircleOutlined,
  AlertOutlined, TagsOutlined, BarChartOutlined,
  PieChartOutlined, EnvironmentOutlined, TeamOutlined,
  DownloadOutlined, SearchOutlined, FilterOutlined
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { exportAoaReport, exportReport, type ReportSheetSpec } from '../utils/excelReport'
import dayjs from 'dayjs'
import api from '../api'
import { useI18n, numLocale } from '../i18n'
import { useDataTimestamps } from '../useDataTimestamps'
import DraggableClickModal from '../components/DraggableClickModal'
// 统计数字卡片走项目统一卡片组件（AGENTS.md 第三节第 3 条：卡片必须用 components/cards，
// 不要在页面里自造卡片样式）
import { CardBase } from '../components/cards'
import { ExplainIcon } from '../components/MetricExplain'
import { WH, WH_COLORS, LIGHT_COLORS, DARK, LIGHT, useTheme, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, controlCardStyle, pageWrap } from '../theme'

const { RangePicker } = DatePicker

// 统一 tooltip 样式（组件内按主题生成）
// 严重等级语义色（适配暗底）
const SEVERITY_COLORS = {
  critical: '#ff6b6b',
  major: '#ff922b',
  medium: '#ffd43b',
  minor: '#51cf66',
  info: '#258cff',
}
const SEVERITY_COLORS_LIGHT = {
  critical: '#dc2626',
  major: '#ea580c',
  medium: '#ca8a04',
  minor: '#15803d',
  info: '#0284c7',
}

// 卡片标题样式
const cardTitleStyle = { fontSize: '0.875rem', fontWeight: 600, color: WH.text } as const

/* ---------- MTTR 趋势的时间粒度（页签：日 / 周 / 月）----------
 * 顺序即页签展示顺序；与后端 _MTTR_GRANULARITIES 一一对应。
 * 三档一次请求全拿到（后端 mttr_series），切页签不重新请求。 */
const MTTR_GRANULARITIES = ['day', 'week', 'month'] as const
type MttrGran = typeof MTTR_GRANULARITIES[number]

/** 粒度的 i18n 键。显式 switch 返回字面量键 —— 动态拼 `t('ttwo.gran.'+g)`
 *  会被 check:i18n 读成键名 `ttwo.gran.` 而报「字典缺失」。 */
const mttrGranLabelKey = (g: MttrGran): string => {
  switch (g) {
    case 'day': return 'ttwo.gran.day'
    case 'week': return 'ttwo.gran.week'
    case 'month': return 'ttwo.gran.month'
  }
}

/** 四张 MTTR 图的 echarts group 名：同组图表 tooltip 与 dataZoom 联动，
 *  拖任一张图缩放，另外三张一起动（日粒度 300 个点时尤其需要）。 */
const MTTR_CHART_GROUP = 'ttwo-mttr-trend'

// 分区标题样式
const SectionTitle = ({ icon, title, explain }: { icon: React.ReactNode; title: string; explain?: string }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)',
    margin: '1rem 0 0.625rem', padding: '0 0 0.5rem',
    borderBottom: '1px solid rgba(0, 217, 255,0.18)',
  }}>
    <span style={{
      width: 28, height: 28, borderRadius: 'var(--wh-radius-sm)',
      background: WH.accentGrad,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#06222e', fontSize: '0.875rem',
    }}>{icon}</span>
    <span style={{ fontSize: '1rem', fontWeight: 700, color: WH.text, letterSpacing: '-0.3px' }}>{title}</span>
    {explain && <ExplainIcon text={explain} size={14} />}
  </div>
)

// 通用排序器
const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

// 生成列filter
const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

// Ticket Severity / SLA 状态的 Unknown（及历史误拼写 unkonw）均表示「无有效取值」，
// 不应出现在统计卡或导出中。后端已按同一口径排除，此处是前端侧的兜底 ——
// 后端与前端独立部署，存在「前端已新、后端未重启」的窗口期。
const isExcludedStatValue = (value: unknown): boolean => {
  const normalized = String(value ?? '').trim().toLowerCase()
  return normalized === 'unknown' || normalized === 'unkonw'
}

const visibleStats = (stats: Record<string, number> | undefined): Record<string, number> =>
  Object.fromEntries(Object.entries(stats || {}).filter(([key]) => !isExcludedStatValue(key)))

/**
 * 高级过滤列的 i18n 键映射。
 *
 * 必须是显式 switch 返回字面量键 —— 动态拼 `t('ttwo.adv.' + col)` 会被
 * `npm run check:i18n` 读成键名 `ttwo.adv.` 而报「字典缺失」（见 AGENTS.md
 * 第三节第 1b 条）。未知列回落到后端列名本身，至少不会显示成 i18n key。
 */
const advFilterLabelKey = (col: string): string => {
  switch (col) {
    case 'region': return 'ttwo.adv.region'
    case 'province_county': return 'ttwo.adv.provinceCounty'
    case 'network_type': return 'ttwo.adv.networkType'
    case 'site_type': return 'ttwo.adv.siteType'
    case 'vip_site': return 'ttwo.adv.vipSite'
    case 'trm_type': return 'ttwo.adv.trmType'
    case 'supervisor': return 'ttwo.adv.supervisor'
    case 'fme_name': return 'ttwo.adv.fmeName'
    case 'power_sources': return 'ttwo.adv.powerSources'
    case 'power_vendor': return 'ttwo.adv.powerVendor'
    case 'site_caregory': return 'ttwo.adv.siteCategory'
    default: return col
  }
}

/** 本组件支持的切片档位（决定**出哪些区块**，与数据源正交）：
 *  - 'summary' 只到 MTTR 趋势为止，供 page=v1_ttwo；
 *  - 'tt'      只出 TT 侧，供 page=tt；
 *  - 'wo'      只出 WO 侧，供 page=wo（配合 source='wo' 读 eflow_wo）。
 */
export type TTWOOnly = 'summary' | 'tt' | 'wo'

/**
 * 数据源开关（决定**数据取自哪张表**，与切片正交）：
 *  - `'tt'` = `eflow_tt`（默认）：page=ttwo / v1_ttwo / tt，读 /tt-wo-dashboard/overview；
 *  - `'wo'` = `eflow_wo`：page=wo，读 /wo-dashboard/overview。
 *
 * WO 页要求版式与 TT 页一样，只是数据源换成 eflow_wo，所以走同一套渲染路径，
 * 靠这个开关切换端点与字段名 —— 不复制一份页面（复制必然分叉）。
 */
export type TTWOSource = 'tt' | 'wo'

/**
 * TT&WO 看板主体（page=ttwo：汇总卡 + 统计 + MTTR 趋势 + 领域/根因 + WO + 站点信息）。
 *
 * `only` / `source` 两个开关正交，用于派生直链页面（同一份实现切片，避免复制走样）：
 *   - only='summary' → 只渲染到 MTTR 趋势为止，即 page=v1_ttwo；
 *   - only='tt'      → 只出 TT 侧，汇总卡只留 TT 总数，对应 page=tt；
 *   - only='wo'      → 只出 WO 侧，配合 source='wo' 对应 page=wo；
 *   - 缺省           → 全量，page=ttwo 行为与改造前完全一致。
 *
 * 三档切片 page=v1_ttwo / tt / wo 的**版式相同：都只到 MTTR 趋势为止**；
 * 其下的下半部分（领域与根因分析、工单分析、站点信息）只属完整页 page=ttwo。
 * 需求（2026-09-27）明确「page=wo 要跟 page=tt 一样」，故三档用同一个 isSlicePage 开关。
 *
 * 筛选条（时间档位/自定义区间/区域/高级过滤）、下钻弹窗与 Excel 导出在各直链上同样具备，
 * 且共用同一套端点口径，因此同源页面的数字必然一致。
 */
export default function TTWODashboard({ only, source }: { only?: TTWOOnly; source?: TTWOSource } = {}) {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  /* ---------- 本组件的两套开关（正交，别混在一起想）----------
   * `only`   —— 决定**出哪些区块**（切片）。缺省 = 完整页 page=ttwo。
   * `source` —— 决定**数据取自哪张表**。缺省 'tt' = eflow_tt。
   */
  const summaryOnly = only === 'summary'  // page=v1_ttwo：上半部分切片
  const ttOnly = only === 'tt'            // page=tt：数据源 eflow_tt
  const woOnly = only === 'wo'            // page=wo：数据源 eflow_wo
  // 三档切片的版式相同（都只到 MTTR 趋势为止），用一个开关统一表达，
  // 避免各区块各写一串条件、彼此对不齐 —— 此前站点信息那处漏了数据源判断，
  // 才让 page=wo 多出两个区块。
  const isSlicePage = summaryOnly || ttOnly || woOnly
  // 数据源：'tt' = eflow_tt（TT&WO 看板 / TT 看板 / v1 切片），
  // 'wo' = eflow_wo（WO 看板）。见 pages/WODashboard.tsx 的说明。
  const isWoSource = source === 'wo'
  // 统计与 MTTR 趋势渲染的就是「本页数据源」的口径：page=wo 上是 eflow_wo 的
  // 严重度/SLA/状态与 WO 时长，所以三档切片都出，此开关只为可读性保留。
  const showTtSections = true
  // 汇总卡：TT 总数算的是 eflow_tt 的行数，WO 数据源页放它没有意义（page=tt 保留）。
  const showTtTotalCard = !woOnly && !isWoSource
  // WO 侧汇总卡（WO 总数 / WO 编号(唯一)）：page=tt 不出。
  const showWoSummaryCards = !ttOnly
  // 「WO 编号(唯一)」在 WO 数据源页与「WO 总数」语义重叠（本页每行本身就是一个
  // WO），只留总数一张，避免同屏出现两个一模一样的数字。
  const showWoNoCard = !ttOnly && !isWoSource
  const { lastSync, isSynced } = useDataTimestamps()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  // 默认时间窗「近 30 天」：7 天对周/月粒度只有 1~2 个桶，看不出趋势；
  // 30 天在日粒度约 30 个点、周粒度 5 个点、月粒度 2 个点，三档都够看
  const [timePreset, setTimePreset] = useState<string>('last30')
  const [customRange, setCustomRange] = useState<any>(null)
  const [selectedRegion, setSelectedRegion] = useState<string | undefined>(undefined)
  // ZTE / 3rd 归属过滤：wo_no 非空 = ZTE 自派单，为空 = 3rd 第三方单（后端同口径）
  const [selectedOwner, setSelectedOwner] = useState<string | undefined>(undefined)
  // 高级过滤（参照 GISMap 的 FILTER_CONFIG）：{站点列名: 精确值}。
  // 列名白名单与候选值都由后端 filters.filter_fields / filter_options 给出，
  // 前端不硬编码列名 —— 换库（my_app / MTN_Comsal）时自动跟着变。
  const [advFilters, setAdvFilters] = useState<Record<string, string | undefined>>({})
  const [showAdvFilters, setShowAdvFilters] = useState(false)
  // MTTR 趋势当前页签粒度。默认「周」保持改造前（MTTR Weekly Trend）的呈现，
  // 日/月是新增的另两档视角。
  const [mttrGran, setMttrGran] = useState<MttrGran>('week')

  // 下钻状态
  const [drillVisible, setDrillVisible] = useState(false)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillData, setDrillData] = useState<any[]>([])
  const [drillTitle, setDrillTitle] = useState('')
  const [drillSearch, setDrillSearch] = useState('')
  const [drillDimension, setDrillDimension] = useState('')
  const [drillValue, setDrillValue] = useState('')
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)

  // 时间范围计算
  const timeRange = useMemo(() => {
    if (timePreset === 'all') return null
    if (timePreset === 'custom' && customRange) {
      return {
        start: customRange[0].format('YYYY-MM-DD'),
        end: customRange[1].format('YYYY-MM-DD'),
      }
    }
    const end = new Date()
    const start = new Date()
    const days: Record<string, number> = { last7: 7, last30: 30, last90: 90, last180: 180 }
    start.setDate(start.getDate() - (days[timePreset] || 7))
    return {
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
    }
  }, [timePreset, customRange])

  // 高级过滤的有效项（去掉空值），序列化成后端要的 JSON 字符串
  const activeAdv = useMemo(() => {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(advFilters)) {
      if (v != null && String(v).trim() !== '') out[k] = String(v)
    }
    return out
  }, [advFilters])
  const advParam = useMemo(() => (Object.keys(activeAdv).length ? JSON.stringify(activeAdv) : ''), [activeAdv])
  const activeFilterCount = Object.keys(activeAdv).length

  // 加载数据
  useEffect(() => {
    setLoading(true)
    setError(null)
    const params: Record<string, string> = {}
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }
    if (selectedRegion) params.region = selectedRegion
    // ZTE/3rd 归属的定义是「TT 的 wo_no 是否非空」，WO 数据源页（每行本身就是一个
    // WO）没有这个概念，既不发该参数也不显示该下拉 —— 发了会被后端忽略，
    // 但留着控件会让用户以为筛选生效了。
    if (selectedOwner && !isWoSource) params.owner = selectedOwner
    if (advParam) params.adv = advParam
    // 两个数据源的缓存键必须分开：键里带 source，否则先开 TT 页再开 WO 页会命中
    // 同一份缓存，页面显示另一张表的数据。
    const cacheKey = `ttwo:${source || 'tt'}:overview:${timeRange?.start || ''}:${timeRange?.end || ''}:${selectedRegion || ''}:${isWoSource ? '' : selectedOwner || ''}:${advParam}`
    const endpoint = isWoSource ? '/wo-dashboard/overview' : '/tt-wo-dashboard/overview'
    cachedGet(cacheKey, () => api.get(endpoint, { params }))
      .then(res => {
        setData(res.data)
        setError(null)
      })
      .catch(err => {
        console.error('TT&WO Dashboard API error:', err)
        setError(err.message || 'API request failed')
      })
      .finally(() => setLoading(false))
  }, [timeRange, selectedRegion, selectedOwner, advParam, source, isWoSource])

  const fmt = (n: number) => n?.toLocaleString(numLocale(locale)) || '0'

  // 下钻功能
  // severity：MTTR 趋势图按 Ticket Severity 拆成 4 张图，柱高/点值是「**该级别**该桶的单数」。
  // 概览按 sv 分桶（tt_wo_dashboard.py:415-418），下钻若不带上它就会返回「该桶全部级别」，
  // 于是 P2 与 P4 点同一个月会下钻出同一个数（2026-10-06 实测 5086/5086）。
  const openDrilldown = useCallback((e?: React.MouseEvent | null, dimension?: string, value?: string, severity?: string) => {
    if (e && typeof e.clientX === 'number') setDrillAnchor({ x: e.clientX, y: e.clientY })
    else setDrillAnchor(null)
    setDrillVisible(true)
    setDrillLoading(true)
    setDrillData([])
    setDrillSearch('')
    setDrillDimension(dimension || '')
    setDrillValue(value || '')
    const params: Record<string, string> = { dimension: dimension || '' }
    if (value) params.value = value
    // 与概览同源的级别过滤 —— 只有 MTTR 趋势图会传
    if (severity) params.severity = severity
    if (timeRange) {
      params.time_start = timeRange.start
      params.time_end = timeRange.end
    }
    if (selectedRegion) params.region = selectedRegion
    // 下钻必须带上与概览**完全相同**的过滤条件，否则表格里的数字与下钻行数对不上。
    // owner 与概览一致地跳过（WO 数据源页没有该概念）。
    if (selectedOwner && !isWoSource) params.owner = selectedOwner
    if (advParam) params.adv = advParam
    // 端点随数据源切换；/wo-dashboard/drilldown 的维度名与 TT 侧一一对应
    // （ticket_severity / sla_status / status / domain / rc_main / rc_sub / all_wo / day|week|month / 站点列）
    api.get(isWoSource ? '/wo-dashboard/drilldown' : '/tt-wo-dashboard/drilldown', { params })
      .then(res => {
        setDrillData(res.data.data || [])
        setDrillTitle(res.data.title || 'Drilldown')
      })
      .catch(() => {
        setDrillTitle('Failed to load data')
      })
      .finally(() => setDrillLoading(false))
  }, [timeRange, selectedRegion, selectedOwner, advParam, isWoSource])

  // 模糊搜索
  const filteredDrillData = useMemo(() => {
    if (!drillSearch.trim()) return drillData
    const lower = drillSearch.toLowerCase()
    return drillData.filter(row =>
      Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
    )
  }, [drillData, drillSearch])

  // 导出Excel
  const exportToExcel = useCallback(() => {
    if (!filteredDrillData.length) return
    const keys = Object.keys(filteredDrillData[0])
    const header = keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
    const rows = filteredDrillData.map(row => keys.map(k => row[k] == null ? '' : String(row[k])))
    const fname = `TTWO_${drillDimension}_${drillValue || 'all'}_${dayjs().format('YYYYMMDD_HHmmss')}`
    // 统一走 excelReport；sheet 名由模块做非法字符清洗与去重，这里不再自行截断
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: 'TTWO',
      title: 'TTWO Drill-down',
      header,
      rows,
      numericCols: [],
    })
  }, [filteredDrillData, drillDimension, drillValue])

  // 下钻表格列定义
  const drillColumns = useMemo(() => {
    if (!drillData.length) return []
    const keys = Object.keys(drillData[0])
    return keys.map(k => ({
      title: k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      dataIndex: k,
      key: k,
      minWidth: k.includes('time') || k.includes('date') ? 150 : 120,
      ellipsis: true,
      sorter: (a: any, b: any) => strSorter(a, b, k),
      filters: getUniqueFilters(drillData, k),
      onFilter: (v: any, r: any) => String(r[k]) === v,
      defaultSortOrder: k === 'alarm_occur_time' ? 'descend' as const : undefined,
    }))
  }, [drillData])

  // 图表配置
  const CHART_HEIGHT = 264

  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const tooltipStyle = darkTooltip(isDark)
  const cText = isDark ? '#f5f7ff' : '#16233b'
  const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
  const sevColors = isDark ? SEVERITY_COLORS : SEVERITY_COLORS_LIGHT
  // MTTR 双轴图的固定语义色（canvas 解析不了 CSS 变量，必须取实值）。
  // 柱 = 中兴蓝 #0072BC、线 = 橙，是业务明确要求的配色，**不随严重级别变化**：
  // P1~P4 已经拆成四张独立的图，级别身份由图承担；再让颜色随级别变，
  // 会把「柱是量、线是时长」这个更关键的对照关系冲淡。
  const cZteBlue = (isDark ? DARK : LIGHT).zteBlue
  const cZteBlueLight = (isDark ? DARK : LIGHT).zteBlueLight
  const cZteOrange = (isDark ? DARK : LIGHT).zteOrange

  // MTTR 趋势 —— 按 Ticket Severity 拆成 4 个独立图（P1/P2/P3/P4），
  // 每张图再支持 日 / 周 / 月 三档粒度（用页签切换）。
  // 数据来自后端 mttr_series[粒度][级别]；某级别在某桶没有单就不画那个点
  // （connectNulls 关闭），因此曲线是断点而非掉到 0 —— 「没有单」≠「MTTR=0」。
  const MTTR_SEVERITIES = ['P1', 'P2', 'P3', 'P4']

  // 后端是否提供了新的多粒度字段。前端与后端同仓但**各自独立部署**（静态产物
  // 落 _fe_dist，后端是常驻进程），因此存在「前端已新、后端未重启」的窗口期。
  // 这段窗口里日/月页签没数据，必须与「真的没有工单」区分开，否则会误导值班。
  const mttrHasSeriesApi = !!data?.mttr_series

  // 三档粒度一次请求全拿到，切页签**不重新请求**（纯前端切换，瞬时响应）
  const mttrSeriesByGran = useMemo<Record<MttrGran, Record<string, any[]>>>(() => {
    const out = {} as Record<MttrGran, Record<string, any[]>>
    for (const g of MTTR_GRANULARITIES) {
      const fromApi = data?.mttr_series?.[g]
      if (fromApi) { out[g] = fromApi; continue }
      // 旧后端兜底：只有周序列（键名为 week），其余粒度落到空
      out[g] = g === 'week' ? (data?.mttr_weekly_by_severity || {}) : {}
    }
    return out
  }, [data])

  // 统计三维（严重度 / SLA 状态 / 状态）。两个数据源返回的键名一致
  // （tt_stats 与 wo_stats_dims 同构），所以卡片渲染器与导出都不需要分支。
  // 声明在 exportOverview 之前：导出要用同一份对象，避免两处各取一次走样。
  const sStats = useMemo(
    () => (isWoSource ? (data?.wo_stats_dims || {}) : (data?.tt_stats || {})),
    [isWoSource, data],
  )

  /* ---------- 页面级导出（2026-09-27 新增）----------
   * 此前本组件唯一的导出按钮在**下钻弹窗**里（导的是下钻明细行），
   * 页面上没有任何导出入口 —— `?page=ttwo` 与 `?page=v1_ttwo` 都因此看不到按钮。
   * 这里补的是**页面级**导出：导当前筛选条件下的全部汇总数据，
   * 与页面上显示的数字一一对应（同一次 /overview 响应，不另发请求）。
   *
   * 多 sheet 结构，空块自动跳过：Summary / TT Stats / WO Stats / MTTR / Domain / Root Cause / Site。
   * only='summary'（v1_ttwo）时下游区块本就不渲染，其数据也不导出（见 summaryOnly 判断），
   * 保证「导出内容 = 页面所见」。 */
  const exportOverview = useCallback(() => {
    if (!data) return
    const sheets: ReportSheetSpec[] = []
    const filterNote = [
      timePreset === 'all' ? t('ttwo.allTime') : `${timeRange?.start || ''} ~ ${timeRange?.end || ''}`,
      selectedRegion ? `${t('gis.regionLabel')}: ${selectedRegion}` : '',
      selectedOwner ? `Owner: ${selectedOwner}` : '',
      activeFilterCount ? `${t('ttwo.advancedFilter')}: ${activeFilterCount}` : '',
    ].filter(Boolean).join('    |    ')

    // ① 汇总卡
    // 各卡在页面上是**有条件下发**的（见上方汇总卡片 Row），所以导出也要跟着隐藏
    // —— 否则会出现「页面没这张卡、导出里却有」的错位。
    const sum = data.summary || {}
    const sumTitle = isWoSource ? t('nav.wo') : t('ttwo.ttStatistics')
    const summaryRows: (string | number)[][] = []
    if (showTtTotalCard) summaryRows.push([sumTitle, t('ttwo.ttTotal'), sum.tt_total ?? ''])
    if (showWoSummaryCards && (sum.wo_total ?? 0) > 0) {
      summaryRows.push([sumTitle, t('ttwo.woTotal'), sum.wo_total ?? ''])
      // 「WO 编号(唯一)」卡在 WO 数据源页不渲染（与 WO 总数语义重叠），导出同步隐藏
      if (showWoNoCard) summaryRows.push([sumTitle, t('ttwo.woNoUnique'), sum.wo_no_count ?? ''])
    }
    if (summaryRows.length) {
      sheets.push({
        name: 'Summary',
        title: sumTitle,
        subtitle: filterNote,
        tabColor: '#2F5496',
        header: [t('ttwo.dimension'), t('ttwo.value'), t('common.total')],
        rows: summaryRows,
        numericCols: [2],
      })
    }

    // ② 各维度统计（严重度 / 工单严重度 / SLA / 状态）。
    // WO 数据源页写的是 eflow_wo 的同一批维度（SLA 取自关联 TT），
    // sheet 名跟着数据源走，避免下载下来分不清是哪张表的数。
    const ttDims: Array<[string, Record<string, number>]> = showTtSections ? [
      [t('ttwo.alarmSeverity'), sStats?.severity || {}],
      [t('ttwo.ticketSeverity'), visibleStats(sStats?.ticket_severity)],
      [t('ttwo.slaStatus'), visibleStats(sStats?.sla_status)],
      [t('ttwo.status'), sStats?.status || {}],
    ] : []
    const ttRows: (string | number)[][] = []
    for (const [dim, stats] of ttDims) {
      for (const [k, v] of Object.entries(stats || {})) ttRows.push([dim, k, v])
    }
    if (ttRows.length) {
      sheets.push({
        name: isWoSource ? 'WO Stats' : 'TT Stats',
        title: isWoSource ? t('nav.wo') : t('ttwo.ttStatistics'),
        subtitle: filterNote,
        tabColor: '#0d9488',
        header: [t('ttwo.dimension'), t('ttwo.value'), t('common.count')],
        rows: ttRows,
        numericCols: [2],
      })
    }

    // ③ WO 各维度统计（来源 / 状态）—— 只属完整页。WO 数据源页不出（该页统计卡片
    // 就是 eflow_wo 口径，该区块本身不渲染），导出必须跟着不出。
    if (!isSlicePage && !isWoSource) {
      const woRows: (string | number)[][] = []
      for (const [k, v] of Object.entries(data.wo_stats?.source || {})) woRows.push([t('ttwo.woBySource'), k, v as number])
      for (const [k, v] of Object.entries(data.wo_stats?.status || {})) woRows.push([t('ttwo.woByStatus'), k, v as number])
      if (woRows.length) {
        sheets.push({
          name: 'WO Stats',
          title: t('ttwo.woAnalytics'),
          subtitle: filterNote,
          tabColor: '#7c3aed',
          header: [t('ttwo.dimension'), t('ttwo.value'), t('common.count')],
          rows: woRows,
          numericCols: [2],
        })
      }
    }

    // ④ MTTR 趋势：三档粒度一次请求全拿到，每档按 P1~P4 摊平
    const mttrRows: (string | number)[][] = []
    for (const g of MTTR_GRANULARITIES) {
      const bySev = mttrSeriesByGran[g] || {}
      for (const sv of MTTR_SEVERITIES) {
        for (const it of (bySev[sv] || [])) {
          // 某桶没有单时 mttr 为 null —— 导出成空串而不是 0，与页面「断点≠0」口径一致
          mttrRows.push([`${t(mttrGranLabelKey(g))} · ${sv}`, it?.period ?? it?.week ?? '', it?.count ?? '', it?.mttr ?? ''])
        }
      }
    }
    if (mttrRows.length) {
      sheets.push({
        name: 'MTTR',
        title: t('ttwo.mttrTrend'),
        subtitle: filterNote,
        tabColor: '#ea580c',
        header: [t('ttwo.granSev'), t('ttwo.period'), t('common.count'), t('ttwo.seriesMTTR')],
        rows: mttrRows,
        numericCols: [2, 3],
      })
    }

    // ⑤ 领域与根因、⑥ 站点信息 —— 同属 MTTR 趋势之下的下半部分，只属完整页。
    // 三档切片（v1_ttwo / tt / wo）页面都不渲染，导出必须跟着不出，
    // 否则会出现「页面没有、导出却有这个 sheet」的错位。
    if (!isSlicePage) {
      const domRows: (string | number)[][] = [
        ...Object.entries(data.domain_stats || {}).map(e => [t('ttwo.ttByDomain'), e[0], e[1] as number]),
        ...Object.entries(data.root_cause?.main || {}).map(e => [t('ttwo.rootCauseMain'), e[0], e[1] as number]),
        ...Object.entries(data.root_cause?.sub || {}).map(e => [t('ttwo.rootCauseSub'), e[0], e[1] as number]),
      ] as (string | number)[][]
      if (domRows.length) {
        sheets.push({
          name: 'Domain-RootCause',
          title: t('ttwo.domainRootCause'),
          subtitle: filterNote,
          tabColor: '#0284c7',
          header: [t('ttwo.dimension'), t('ttwo.value'), t('common.count')],
          rows: domRows,
          numericCols: [2],
        })
      }

      // 分组名与页面卡标题同款处理（下划线转空格 + 首字母大写），保证导出与界面一致
      const prettyGroup = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
      const siteRows: (string | number)[][] = []
      for (const [k, v] of Object.entries(data.site_stats?.power_sources || {})) siteRows.push([prettyGroup('power_sources'), k, v as number])
      for (const [k, v] of Object.entries(data.site_stats?.power_vendor || {})) siteRows.push([prettyGroup('power_vendor'), k, v as number])
      for (const [k, v] of Object.entries(data.site_stats?.maintenance_team || {})) siteRows.push([prettyGroup('maintenance_team'), k, v as number])
      for (const [grp, stats] of Object.entries(data.site_stats || {})) {
        // power_sources / power_vendor / maintenance_team 已在上方摊平，避免重复
        if (['power_sources', 'power_vendor', 'maintenance_team'].includes(grp)) continue
        if (!stats || typeof stats !== 'object') continue
        for (const [k, v] of Object.entries(stats as Record<string, number>)) siteRows.push([prettyGroup(grp), k, v])
      }
      if (siteRows.length) {
        sheets.push({
          name: 'Site Stats',
          title: t('ttwo.siteInfo'),
          subtitle: filterNote,
          tabColor: '#15803d',
          header: [t('ttwo.dimension'), t('ttwo.value'), t('common.count')],
          rows: siteRows,
          numericCols: [2],
        })
      }
    }

    if (!sheets.length) return
    // 文件名前缀按切片/数据源走，几档导出的文件一眼能分辨（tt / wo / v1 / full）
    const scope = ttOnly ? 'tt' : (woOnly || isWoSource) ? 'wo' : summaryOnly ? 'v1' : 'full'
    void exportReport(sheets, `TTWO_${scope}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [data, timePreset, timeRange, selectedRegion, selectedOwner, activeFilterCount,
      summaryOnly, ttOnly, woOnly, isSlicePage, isWoSource, showTtTotalCard,
      showWoSummaryCards, showWoNoCard, showTtSections, sStats, mttrSeriesByGran, t])


  /**
   * 某粒度下、四个级别共用的 x 轴。
   * 取所有级别出现过的桶并集，保证四张图横轴严格对齐，可以直接上下对比同一时段。
   * 兼容两种键名：新字段用 period，旧兜底字段用 week。
   */
  const mttrPeriodsFor = useCallback((gran: MttrGran): string[] => {
    const bySev = mttrSeriesByGran[gran] || {}
    const set = new Set<string>()
    for (const sv of MTTR_SEVERITIES) {
      for (const it of (bySev[sv] || [])) {
        const p = it?.period ?? it?.week
        if (p) set.add(p)
      }
    }
    // 后端增量返回/老后端：mttr_weekly 仍是全量周口径，用作周页签的兜底
    if (set.size === 0 && gran === 'week') {
      for (const it of (data?.mttr_weekly || [])) if (it?.week) set.add(it.week)
    }
    return Array.from(set).sort()
  }, [mttrSeriesByGran, data?.mttr_weekly])

  const makeMttrSevOption = useCallback((sev: string, gran: MttrGran) => {
    const periods = mttrPeriodsFor(gran)
    if (!periods.length) return {}
    const items = mttrSeriesByGran[gran]?.[sev] || []
    const byPeriod = new Map<string, any>(
      items.map((it: any) => [it.period ?? it.week, it])
    )
    // 缺桶填 null：ECharts 遇 null 断线，不会误画成 0
    const mttrs = periods.map(p => (byPeriod.has(p) ? byPeriod.get(p)!.mttr : null))
    // 柱 = 该桶该级别的总 TT 单数（total）。老后端没有 total 时退回 count（样本数），
    // 保证兼容窗口里柱状图仍有值可画。
    const totals = periods.map(p => {
      const it = byPeriod.get(p)
      if (!it) return null
      return it.total ?? it.count ?? null
    })
    // 计入 MTTR 均值的样本数，仅在与总量不等时于 tooltip 里补一句，说明差额来源
    const counts = periods.map(p => (byPeriod.has(p) ? byPeriod.get(p)!.count : null))
    // 柱 = 中兴蓝 #0072BC、线 = 橙（业务明确要求，见 11-feature-guide.md 第 4 节），
    // 四张图一致，**与严重级别无关**。
    // 此前是反的：柱用淡蓝半透明渐变、线取严重度色（P1 红 / P2 橙 / P3 蓝 / P4 绿），
    // 结果是「同一个量在四张图上颜色不同，而真正该区分的柱/线反而同色」——
    // 与要求的配色正好相反，2026-09-28 按需求改正。
    // 柱子自上而下由提亮蓝渐变到品牌蓝，保留体积感，色相锁定中兴蓝。
    const barColor = {
      type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [
        { offset: 0, color: cZteBlueLight },
        { offset: 1, color: cZteBlue },
      ],
    }
    // 日粒度在「全部时间」下有近 300 个点，横轴会糊成一片：
    // 点数多时开启缩放（滚轮 + 底部滑杆）。四张图同属一个 echarts group，
    // 缩放与 tooltip 联动，因此拖任一张图四张一起动。
    const needZoom = periods.length > 60
    const nameCount = t('ttwo.seriesTTCount')
    const nameMttr = t('ttwo.seriesMTTR')
    return {
      // 双轴：左轴 = 单数（柱），右轴 = 分钟（线）。图例把两个量显式说清，
      // 否则双轴图很容易被误读成「同一量纲的两种画法」
      legend: { data: [nameCount, nameMttr], top: 0, right: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 10, color: cTextMuted } },
      tooltip: {
        ...tooltipStyle, trigger: 'axis',
        // 悬停时同时给出该时段该级别的单量与 MTTR：只有时长没有样本量会让人
        // 把一个「只算了 1 单」的均值当成趋势
        formatter: (ps: any[]) => {
          const p = ps?.[0]
          if (!p) return ''
          const i = p.dataIndex
          const tot = i != null ? totals[i] : null
          const n = i != null ? counts[i] : null
          const m = i != null ? mttrs[i] : null
          const head = `<strong>${p.axisValue}</strong>`
          if ((tot == null || tot === 0) && m == null) return `${head}<br/>${t('ttwo.noTicketsThisPeriod')}`
          const lines = [head]
          if (tot != null) lines.push(`${nameCount}: <strong>${tot}</strong>`)
          if (m != null) {
            // total 与 count 不等时把差额说清：差额是「有时段没关单时间/时长越界」的单
            const extra = (n != null && tot != null && n !== tot) ? ` ${t('ttwo.mttrSampleNote', { n })}` : ''
            // nameMttr 自带单位（'MTTR (分钟)' / 'MTTR (min)'），这里不再补 ' min'，免得读成两个单位
            lines.push(`${nameMttr}: <strong>${m}</strong>${extra}`)
          } else {
            lines.push(t('ttwo.mttrNoSample'))
          }
          return lines.join('<br/>')
        },
      },
      grid: { left: 48, right: 46, top: 36, bottom: needZoom ? 62 : 44 },
      dataZoom: needZoom
        ? [
            { type: 'inside', throttle: 60 },
            { type: 'slider', height: 16, bottom: 8, borderColor: 'transparent', textStyle: { fontSize: 10, color: cTextMuted } },
          ]
        : undefined,
      xAxis: {
        type: 'category', data: periods,
        // 点多时标签抽稀，否则 300 个日期会叠成黑块
        axisLabel: { ...axisLabel(isDark), rotate: 45, fontSize: 10, hideOverlap: true, interval: needZoom ? 'auto' : 0 },
        axisLine: axisLine(isDark),
      },
      yAxis: [
        // 左轴：TT 单数（整数）
        {
          type: 'value', position: 'left', minInterval: 1,
          axisLabel: { color: cTextMuted, fontSize: 10 },
          splitLine: splitLine(isDark),
        },
        // 右轴：MTTR 分钟。不画网格线，避免与左轴网格重叠成一团
        {
          type: 'value', position: 'right', name: 'min',
          nameTextStyle: { color: cTextMuted, fontSize: 10 },
          axisLabel: { color: cTextMuted, fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          // 柱 = 单量，中兴蓝
          name: nameCount, type: 'bar', yAxisIndex: 0, data: totals,
          barMaxWidth: 16, itemStyle: { color: barColor, borderRadius: [3, 3, 0, 0] },
        },
        {
          // 线 = MTTR 均值，橙色。connectNulls: false 保证「没有单」时断线而不是掉到 0
          name: nameMttr, type: 'line', yAxisIndex: 1, data: mttrs, smooth: true, connectNulls: false,
          itemStyle: { color: cZteOrange }, lineStyle: { width: 2.5, color: cZteOrange },
          symbol: periods.length > 60 ? 'none' : 'circle', symbolSize: 6,
          // 数据点描一圈本色底：橙点压在蓝柱上时边界会糊，描边能把点从柱子里摘出来
          symbolBorderColor: isDark ? '#050d22' : '#ffffff', symbolBorderWidth: 1.5,
          z: 3,
        },
      ],
    }
  }, [mttrPeriodsFor, mttrSeriesByGran, cZteBlue, cZteBlueLight, cZteOrange, cTextMuted, isDark, tooltipStyle, t])

  // Domain分布
  const domainOption = useMemo(() => {
    if (!data?.domain_stats) return {}
    const entries = Object.entries(data.domain_stats).sort((a: any, b: any) => a[1] - b[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 90, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any, i: number) => ({
          value: e[1],
          itemStyle: {
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: cPalette[i % cPalette.length] }, { offset: 1, color: cPalette[(i + 3) % cPalette.length] }] },
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.domain_stats, isDark, tooltipStyle, cText, cTextMuted, cPalette, locale])

  // 通用饼图配置
  const makePieOption = useCallback((entries: [string, any][], hasLegend = true) => ({
    tooltip: { ...tooltipStyle, trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
    legend: hasLegend ? { orient: 'vertical' as const, right: 0, top: 'center', textStyle: { fontSize: 10, color: cTextMuted }, itemWidth: 10, itemHeight: 10 } : undefined,
    series: [{
      type: 'pie', radius: ['35%', '65%'], center: ['35%', '50%'],
      data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
      label: { fontSize: 10, color: cText, formatter: '{b}\n{d}%' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 2, shadowColor: isDark ? 'rgba(0, 217, 255,0.35)' : 'rgba(13,148,136,0.3)' } },
    }],
  }), [tooltipStyle, cText, cTextMuted, cPalette, isDark])

  const rcMainOption = useMemo(() => {
    if (!data?.root_cause?.main) return {}
    const entries = Object.entries(data.root_cause.main).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.main, makePieOption])

  const rcSubOption = useMemo(() => {
    if (!data?.root_cause?.sub) return {}
    const entries = Object.entries(data.root_cause.sub).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return makePieOption(entries)
  }, [data?.root_cause?.sub, makePieOption])

  // WO Source 柱状图
  const woSourceOption = useMemo(() => {
    if (!data?.wo_stats?.source) return {}
    const entries = Object.entries(data.wo_stats.source).sort((a: any, b: any) => b[1] - a[1])
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 80, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#0bc78c' : '#15803d' }, { offset: 1, color: isDark ? '#94d82d' : '#4d7c0f' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.wo_stats?.source, isDark, tooltipStyle, cText, cTextMuted, locale])

  // WO Status 柱状图
  const woStatusOption = useMemo(() => {
    if (!data?.wo_stats?.status) return {}
    const entries = Object.entries(data.wo_stats.status).sort((a: any, b: any) => b[1] - a[1])
    const statusColors: Record<string, string[]> = isDark
      ? {
          Closed: ['#51cf66', '#94d82d'], Open: ['#258cff', '#74c0fc'], 'In Progress': ['#ffd43b', '#fcc419'],
          Pending: ['#ffa94d', '#ff922b'], Cancelled: ['#adb5bd', '#dee2e6'],
        }
      : {
          Closed: ['#15803d', '#4d7c0f'], Open: ['#0284c7', '#0ea5e9'], 'In Progress': ['#ca8a04', '#a16207'],
          Pending: ['#ea580c', '#c2410c'], Cancelled: ['#64748b', '#94a3b8'],
        }
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 140, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 10, color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: entries.map((e: any) => {
          const colors = statusColors[e[0]] || statusColors['In Progress']
          return {
            value: e[1],
            itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: colors[0] }, { offset: 1, color: colors[1] }] }, borderRadius: [0, 4, 4, 0] },
          }
        }),
        label: { show: true, position: 'right', fontSize: 10, color: cTextMuted, formatter: (p: any) => p.value.toLocaleString(numLocale(locale)) },
      }],
    }
  }, [data?.wo_stats?.status, isDark, tooltipStyle, cText, cTextMuted, locale])

  // Power Sources 饼图
  const powerSourceOption = useMemo(() => {
    if (!data?.site_stats?.power_sources) return {}
    const entries = Object.entries(data.site_stats.power_sources).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 9, color: cTextMuted }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: 'pie', radius: ['35%', '60%'], center: ['35%', '50%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
        label: { fontSize: 9, color: cText, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(0, 217, 255,0.35)' : 'rgba(13,148,136,0.3)' } },
      }],
    }
  }, [data?.site_stats?.power_sources, isDark, tooltipStyle, cText, cTextMuted, cPalette])

  // Maintenance Team 柱状图
  const fmeOption = useMemo(() => {
    if (!data?.site_stats?.maintenance_team) return {}
    const entries = Object.entries(data.site_stats.maintenance_team).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10)
    return {
      tooltip: { ...tooltipStyle, trigger: 'axis' },
      grid: { left: 130, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      yAxis: { type: 'category', data: entries.map((e: any) => e[0]), axisLabel: { fontSize: 9, color: cText } },
      series: [{
        type: 'bar', barMaxWidth: 18,
        data: entries.map((e: any) => ({
          value: e[1],
          itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: isDark ? '#a99cff' : '#7c3aed' }, { offset: 1, color: isDark ? '#d0bfff' : '#a78bfa' }] }, borderRadius: [0, 4, 4, 0] },
        })),
        label: { show: true, position: 'right', fontSize: 9, color: cTextMuted },
      }],
    }
  }, [data?.site_stats?.maintenance_team, isDark, tooltipStyle, cText, cTextMuted])

  // Power Vendor 饼图
  const powerVendorOption = useMemo(() => {
    if (!data?.site_stats?.power_vendor) return {}
    const entries = Object.entries(data.site_stats.power_vendor)
    return {
      tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['35%', '65%'],
        data: entries.map((e: any, i: number) => ({ name: e[0], value: e[1], itemStyle: { color: cPalette[i % cPalette.length] } })),
        label: { fontSize: 11, color: cText, formatter: '{b}\n{d}%' },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(0, 217, 255,0.35)' : 'rgba(13,148,136,0.3)' } },
      }],
    }
  }, [data?.site_stats?.power_vendor, isDark, tooltipStyle, cText, cPalette])

  // 统计卡片颜色映射
  // 注：Alarm Severity 维度已于 2026-09-26 按业务要求从 TT 统计中移除，
  // 其色表（sevColor）随之删除；sevColors 现由 Ticket Severity 卡片与 WO 来源图复用
  // （MTTR 四图自 2026-09-28 起改用固定的中兴蓝柱 / 橙线，不再按级别取色）。
  const ticketColor: Record<string, string> = {
    P1: sevColors.critical, P2: sevColors.major, P3: sevColors.info, P4: sevColors.minor,
    'Critical(4H)': sevColors.critical, 'Major(24H)': sevColors.major, 'Warning': sevColors.medium, 'Minor(72H)': sevColors.minor,
    Unknown: isDark ? '#adb5bd' : '#64748b'
  }
  const slaColor: Record<string, string> = {
    Pass: isDark ? '#0bc78c' : '#15803d',
    Failed: isDark ? '#ff5c6c' : '#dc2626',
    'Within SLA': isDark ? '#258cff' : '#0284c7',
    Unknown: isDark ? '#adb5bd' : '#64748b',
  }
  const autoPalette = cPalette
  const autoColorCache: Record<string, string> = {}
  const getAutoColor = (key: string, idx: number) => {
    if (!autoColorCache[key]) autoColorCache[key] = autoPalette[idx % autoPalette.length]
    return autoColorCache[key]
  }

  /**
   * 统计维度的小标题（卡片网格之上）。替代原来「外加大卡、标题写在卡头」的做法：
   * 大卡套小卡会让层级变糊、两层边框压掉内边距，且同一行放不下两个维度的卡片网格。
   */
  const StatDimTitle = ({ label, explain }: { label: string; explain?: string }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 'var(--wh-space-sm) 0 0.375rem', fontSize: '0.8125rem', fontWeight: 600, color: WH.textMuted }}>
      {label}
      {explain && <ExplainIcon text={explain} />}
    </div>
  )

  /**
   * 通用统计数字卡片：每个取值一张卡（左色条 + 名称 + 大数字 + 占比），点卡下钻该取值明细。
   *
   * 三个维度（工单严重度 Ticket Severity / SLA 状态 / 工单状态）共用同一个渲染器，
   * 只是换色表与下钻维度。原先是 Tag 胶囊块：取值一多就换行成一团、数字也不突出；
   * 卡片在值班大屏上更易扫读，且数字层级更清楚。
   *
   * 卡片用项目统一组件 CardBase（AGENTS.md 第三节第 3 条）。
   * 占比的分母是该维度自身的合计（只看这一个维度内部的构成），不是 TT 总数。
   * 取不到值显示 —，不显示成 0（第三节原则 6）。
   */
  const renderStatCards = (
    stats: Record<string, number>,
    colorOf: (k: string, idx: number) => string,
    dimension: string,
    labelOf: (k: string) => string = (k) => k,
  ) => {
    const sorted = Object.entries(stats || {}).sort((a, b) => (b[1] as number) - (a[1] as number))
    if (!sorted.length) {
      return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('common.noData')} />
    }
    const total = sorted.reduce((acc, [, n]) => acc + (n as number), 0)
    // 卡片宽度按取值个数自适应：4~5 个取值时一行正好铺满，比固定 6 列匀称
    const span = Math.max(4, Math.floor(24 / sorted.length))
    return (
      <Row gutter={[12, 12]}>
        {sorted.map(([k, v], idx) => {
          const color = colorOf(k, idx)
          const pct = total > 0 ? ((v as number) / total) * 100 : 0
          return (
            <Col xs={12} sm={8} md={6} lg={span} key={k}>
              <CardBase
                interactive
                style={{ borderLeft: `4px solid ${color}` }}
                bodyStyle={{ padding: 'var(--wh-space-sm)' }}
                onClick={(e) => openDrilldown(e, dimension, k)}
              >
                <Tooltip title={k}>
                  <div style={{ fontSize: '0.75rem', color: WH.textMuted, marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {labelOf(k)}
                  </div>
                </Tooltip>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color, lineHeight: 1.2 }}>
                  {v == null ? '—' : fmt(v as number)}
                </div>
                <div style={{ fontSize: '0.6875rem', color: WH.textMuted, marginTop: 2 }}>{pct.toFixed(1)}%</div>
              </CardBase>
            </Col>
          )
        })}
      </Row>
    )
  }

  // Status 颜色编码（随主题适配：深色主题用亮色，浅色主题用饱和暗色保证对比度）
  const getStatusColor = (key: string): string => {
    const lower = key.toLowerCase()
    if (lower.includes('closed') || lower.includes('complete')) return isDark ? '#0bc78c' : '#15803d'
    if (lower.includes('open') || lower.includes('in progress')) return isDark ? '#258cff' : '#0284c7'
    if (lower.includes('waiting') || lower.includes('pending')) return isDark ? '#ff922b' : '#ea580c'
    if (lower.includes('cancel') || lower.includes('reject')) return isDark ? '#adb5bd' : '#64748b'
    return isDark ? '#00d9ff' : '#0d9488'
  }

  const shortenLabel = (key: string): string => {
    const map: Record<string, string> = {
      'Waiting for FO Process(WO RCA to FO Confirm)': 'Wait FO (RCA Confirm)',
      'Waiting for FO Process(WO Reject to FO Confirm)': 'Wait FO (Reject Confirm)',
      'Waiting for FO Process': 'Wait FO Process',
      'Waiting for Third Accept': 'Wait Third Accept',
      'Waiting for Customer Confirm': 'Wait Customer Confirm',
    }
    return map[key] || key
  }

  /**
   * 某个粒度下的四张 MTTR 图（P1/P2/P3/P4）。
   *
   * 空态按「该级别在该粒度下有没有数据」逐图判定，而不是整页有没有数据：
   * 例如 P4 本季度无单时，只让 P4 那张显示空态，其余三张照常出图。
   */
  const renderMttrCharts = (gran: MttrGran) => {
    const bySev = mttrSeriesByGran[gran] || {}
    const hasAny = MTTR_SEVERITIES.some(sv => (bySev[sv]?.length ?? 0) > 0)
    if (!hasAny) {
      // 区分「后端版本旧、没返回该粒度」与「确实没有工单」：
      // 前者要在界面上说清楚，否则值班会以为数据真的空了
      const unavailable = !mttrHasSeriesApi && gran !== 'week'
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={unavailable ? t('ttwo.mttrGranUnavailable') : t('ttwo.noTicketsInRangeAll')}
          style={{ padding: 'var(--wh-space-lg) 0' }}
        />
      )
    }
    return (
      <Row gutter={[12, 12]}>
        {MTTR_SEVERITIES.map(sev => {
          const has = (bySev[sev]?.length ?? 0) > 0
          return (
            <Col xs={24} lg={12} key={sev}>
              <Card
                size="small"
                title={<span style={cardTitleStyle}>{t('ttwo.mttrBySeverity', { sev })} <ExplainIcon text={t('ttwo.explain.mttrBySeverity')} /></span>}
                style={cardStyle}
              >
                {has ? (
                  <div role="img" aria-label={`MTTR ${gran} ${sev} chart`}>
                    <ReactECharts
                      option={makeMttrSevOption(sev, gran)}
                      style={{ height: CHART_HEIGHT }}
                      // notMerge：切页签时彻底换掉 series/xAxis，避免上一档的
                      // dataZoom 窗口与点位残留造成「日图看着像周图」
                      notMerge
                      onChartReady={onMttrChartReady}
                      onEvents={onChartClick(gran, sev)}
                    />
                  </div>
                ) : (
                  <div style={{ height: CHART_HEIGHT, display: 'flex', alignItems: 'center', justifyContent: 'center', color: WH.textMuted, fontSize: '0.8125rem' }}>
                    {t('ttwo.noTicketsInRange', { sev })}
                  </div>
                )}
              </Card>
            </Col>
          )
        })}
      </Row>
    )
  }

  // 图表点击事件
  // severity 仅在 MTTR 趋势图上给出（每张图固定一个级别），其余图不传 → 下钻不带该过滤。
  const onChartClick = (dimension: string, severity?: string) => ({
    click: (params: any) => {
      const name = params.name || params.data?.name
      if (name) openDrilldown(null, dimension, name, severity)
    }
  })

  /**
   * 四张 MTTR 图加入同一个 echarts group，使 tooltip 与 dataZoom 联动：
   * 悬停/缩放任意一张，另外三张同步 —— 日粒度下近 300 个点时，
   * 四个级别要看的是「同一时间窗」，各自为政的缩放会让人对不齐。
   * echarts.connect 对已连接的 group 重复调用是幂等的。
   */
  const onMttrChartReady = useCallback((inst: any) => {
    if (!inst) return
    inst.group = MTTR_CHART_GROUP
    echarts.connect(MTTR_CHART_GROUP)
  }, [])

  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '6.25rem' }}>
      <Spin size="large" />
      <div style={{ marginTop: 'var(--wh-space-md)', color: WH.textMuted }}>{t('ttwo.loading')}</div>
    </div>
  )

  if (error) return (
    <div style={{ ...pageWrap, padding: 'var(--wh-space-lg)' }}>
      <Alert type="error" message={t('ttwo.loadFailed')} description={error} showIcon />
    </div>
  )

  if (!data) return <Empty description={t('ttwo.noData')} />

  const regions = data.filters?.regions || []
  // 统计三维与页面级导出共用同一份（见上面的 sStats），此处只做别名，避免两处取数走样
  const s = sStats
  // 高级过滤：列名白名单与候选值都由后端给（见 filters.filter_fields / filter_options）
  const filterFields: string[] = data.filters?.filter_fields || []
  const filterOptions: Record<string, string[]> = data.filters?.filter_options || {}

  // 暗色汇总卡片生成器
  const SummaryCard = ({ color, icon, value, label, onClick, explain }: { color: string; icon: React.ReactNode; value: number; label: string; onClick?: (e: React.MouseEvent) => void; explain?: string }) => (
    <Card size="small" hoverable className="wh-card-interactive" style={{ ...cardStyle, position: 'relative', cursor: onClick ? 'pointer' : 'default', borderLeft: `4px solid ${color}` }}
      onClick={onClick}>
      {explain && (
        <span style={{ position: 'absolute', top: 6, right: 8, zIndex: 2, cursor: 'help' }} onClick={e => e.stopPropagation()}>
          <ExplainIcon text={explain} />
        </span>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Statistic title={<span style={{ color: WH.textMuted }}>{label}</span>} value={value} valueStyle={{ fontSize: '2rem', fontWeight: 800, color, textShadow: `0 0 14px ${color}55` }} />
        <span style={{ fontSize: '2.5rem', opacity: 0.15, color }}>{icon}</span>
      </div>
    </Card>
  )

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
      {/* 筛选栏 */}
      <Card size="small" style={{ ...controlCardStyle, background: WH.cardBg }}>
        <Space wrap align="center" size="middle">
          <Segmented
            options={[
              { label: <span style={{ color: timePreset === 'all' ? WH.teal : WH.text }}>{t('ttwo.allTime')}</span>, value: 'all' },
              { label: <span style={{ color: timePreset === 'last7' ? WH.teal : WH.text }}>{t('ttwo.last7Days')}</span>, value: 'last7' },
              { label: <span style={{ color: timePreset === 'last30' ? WH.teal : WH.text }}>{t('ttwo.last30Days')}</span>, value: 'last30' },
              { label: <span style={{ color: timePreset === 'last90' ? WH.teal : WH.text }}>{t('ttwo.last3Months')}</span>, value: 'last90' },
              { label: <span style={{ color: timePreset === 'last180' ? WH.teal : WH.text }}>{t('ttwo.last6Months')}</span>, value: 'last180' },
              { label: <span style={{ color: timePreset === 'custom' ? WH.teal : WH.text }}>{t('ttwo.custom')}</span>, value: 'custom' },
            ]}
            value={timePreset}
            onChange={setTimePreset}
            style={{ background: 'var(--wh-seg-bg)' }}
          />
          {timePreset === 'custom' && (
            <RangePicker value={customRange} onChange={setCustomRange} />
          )}
          <Select
            value={selectedRegion}
            onChange={setSelectedRegion}
            style={{ width: 'min(100%, 11.25rem)' }}
            allowClear
            placeholder={t('ttwo.allRegions')}
            options={regions.map((r: string) => ({ value: r, label: r }))}
          />
          {/* ZTE / 3rd 归属：wo_no 非空 = ZTE 自派单，为空 = 3rd 第三方单。
              WO 数据源页不显示 —— 该归属的定义建立在「TT 的 wo_no」上，
              WO 表每行本身就是一个 WO，没有对应概念（后端也不接收该参数）。 */}
          {!isWoSource && <Select
            value={selectedOwner}
            onChange={setSelectedOwner}
            style={{ width: 'min(100%, 9.375rem)' }}
            allowClear
            placeholder={t('ttwo.allOwners')}
            options={[
              { value: 'zte', label: t('ttwo.ownerZte') },
              { value: '3rd', label: t('ttwo.ownerThird') },
            ]}
          />}
          {/* 高级过滤开关（参照 GISMap 的「高级筛选」） */}
          <Button
            size="small"
            type={showAdvFilters ? 'primary' : 'default'}
            icon={<FilterOutlined />}
            onClick={() => setShowAdvFilters(v => !v)}
          >
            {t('ttwo.advancedFilter')}
            {activeFilterCount > 0 && <Badge count={activeFilterCount} size="small" style={{ marginLeft: 'var(--wh-space-xs)' }} />}
          </Button>
          {activeFilterCount > 0 && (
            <Button size="small" type="link" onClick={() => setAdvFilters({})} style={{ color: WH.teal }}>
              {t('ttwo.clearFilters')}
            </Button>
          )}
          {/* 页面级导出：导当前筛选条件下的全部汇总数据（下钻弹窗内另有明细导出） */}
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={exportOverview}
          >
            {t('common.exportExcel')}
          </Button>
          <Tag
            icon={<ClockCircleOutlined />}
            color={isSynced ? 'green' : 'red'}
            style={{ marginLeft: 'auto', borderRadius: 'var(--wh-radius-lg)', padding: '0.125rem 0.75rem' }}
          >
            {isSynced ? t('ttwo.synced', { time: lastSync ?? '' }) : t('ttwo.notSynced')}
          </Tag>
        </Space>
        {/* 高级过滤：站点维度的精确匹配下拉。列名与候选值都来自后端，
            所以换库（my_app / MTN_Comsal）时这里自动跟着变，不需要改前端。 */}
        {showAdvFilters && (
          <Row gutter={[8, 8]} style={{ marginTop: 'var(--wh-space-sm)' }}>
            {filterFields.map(col => {
              const opts = filterOptions[col] || []
              if (opts.length === 0) return null
              return (
                <Col key={col}>
                  <Select
                    size="small"
                    style={{ width: 'min(100%, 11.25rem)' }}
                    allowClear
                    showSearch
                    placeholder={t(advFilterLabelKey(col))}
                    value={advFilters[col]}
                    onChange={(v) => setAdvFilters(prev => ({ ...prev, [col]: v }))}
                    options={opts.map(v => ({ value: v, label: v }))}
                    filterOption={(input, option) =>
                      String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                  />
                </Col>
              )
            })}
          </Row>
        )}
      </Card>

      {/* 汇总卡片
          按切片/数据源下发：page=tt 不出两张 WO 卡；WO 数据源页只留「WO 总数」一张
          （本页每行就是一个 WO，TT 总数算的是 eflow_tt 的行数，放这里没有意义；
          「WO 编号(唯一)」与「WO 总数」在 WO 表上语义重叠，同屏出现两个一模一样的
          数字只会让人以为是 bug）。
          WO 卡仍保留原有的 wo_total > 0 条件 —— 没有 WO 表/没有 WO 数据时
          显示「WO 编号(唯一) 0」比显示 0 更容易被误读成「真的一个都没有」。 */}
      {((showTtTotalCard ? 1 : 0) + (showWoSummaryCards && data.summary.wo_total > 0 ? 1 : 0)) > 0 && (
      <Row gutter={12}>
        {showTtTotalCard && <Col xs={24} sm={12} md={(showWoSummaryCards && data.summary.wo_total > 0) ? (showWoNoCard ? 8 : 12) : 24}>
          <SummaryCard color="#258cff" icon={<ThunderboltOutlined />} value={data.summary.tt_total} label={t('ttwo.ttTotal')} explain={t('ttwo.explain.ttTotal')} onClick={(e) => openDrilldown(e, 'all_tt')} />
        </Col>}
        {showWoSummaryCards && data.summary.wo_total > 0 && <Col xs={24} sm={12} md={showTtTotalCard ? (showWoNoCard ? 8 : 12) : (showWoNoCard ? 12 : 24)}>
          <SummaryCard color="#51cf66" icon={<FileTextOutlined />} value={data.summary.wo_total} label={t('ttwo.woTotal')} explain={t('ttwo.explain.woTotal')} onClick={(e) => openDrilldown(e, 'all_wo')} />
        </Col>}
        {showWoNoCard && data.summary.wo_total > 0 && <Col xs={24} sm={12} md={8}>
          <SummaryCard color="#a99cff" icon={<NumberOutlined />} value={data.summary.wo_no_count} label={t('ttwo.woNoUnique')} explain={t('ttwo.explain.woNo')} onClick={(e) => openDrilldown(e, 'all_wo')} />
        </Col>}
      </Row>
      )}

      {/* TT 统计（不含 Alarm Severity：该维度与 Ticket Severity 重复且噪声大，2026-09-26 按业务要求移除）
          维度都改为数字卡片：原来的 Tag 胶囊块取值一多就换行成一团、数字不突出。
          这里用「维度小标题 + 卡片网格」的分组方式，而不是「大卡里套小卡」——
          嵌套卡片会让层级变糊，两个边框叠在一起也压布局。
          工单严重度与 SLA 状态取值都少（各 4~5 个），左右各占半行并排；
          工单状态取值多且名字长（Waiting for FO Process(...)），仍单独占整行。
          本块属「上半部分」：三档切片都出，渲染的就是本页数据源（page=wo 时是
          eflow_wo 的严重度 / 关联 TT 的 SLA / WO 状态）。 */}
      {showTtSections && <>
      <SectionTitle icon={<AlertOutlined />} title={t('ttwo.ttStatistics')} />
      <Row gutter={[16, 4]}>
        <Col xs={24} lg={12}>
          <StatDimTitle label={t('ttwo.ticketSeverity')} explain={t('ttwo.explain.ticketSeverity')} />
          {renderStatCards(visibleStats(s.ticket_severity), (k, i) => ticketColor[k] || getAutoColor(k, i), 'ticket_severity')}
        </Col>
        <Col xs={24} lg={12}>
          <StatDimTitle label={t('ttwo.slaStatus')} explain={t('ttwo.explain.sla')} />
          {renderStatCards(visibleStats(s.sla_status), (k, i) => slaColor[k] || getAutoColor(k, i), 'sla_status')}
        </Col>
      </Row>
      <StatDimTitle label={t('ttwo.status')} explain={t('ttwo.explain.status')} />
      {renderStatCards(s.status || {}, (k) => getStatusColor(k), 'status', shortenLabel)}

      {/* MTTR 趋势 —— 页签切 日/周/月，每个粒度下按 Ticket Severity 分 P1/P2/P3/P4 四张图 */}
      <SectionTitle icon={<BarChartOutlined />} title={t('ttwo.mttrTrend')} explain={t('ttwo.explain.mttr')} />
      <Tabs
        size="small"
        activeKey={mttrGran}
        onChange={(k) => setMttrGran(k as MttrGran)}
        // 每个页签的内容 = 该粒度下的四张图。用 renderMttrCharts(g) 显式按页签自身
        // 的粒度取数，不依赖 mttrGran 状态，避免「切页签瞬间四张图仍读上一档」的错位。
        items={MTTR_GRANULARITIES.map(g => ({
          key: g,
          label: t(mttrGranLabelKey(g)),
          children: renderMttrCharts(g),
        }))}
      />
      </>}

      {/* Domain + Root Cause：**只属完整页**（page=ttwo）—— 它既不是纯 TT 统计也不是
          WO 分析，v1_ttwo / tt / wo 三档切片都不出（需求：WO 页与 TT 页版式逐块一致，
          即都只到 MTTR 趋势为止）。 */}
      {!isSlicePage && <>
      <SectionTitle icon={<PieChartOutlined />} title={t('ttwo.domainRootCause')} />
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={10}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.ttByDomain')}</span>} size="small" style={cardStyle}>
            <div role="img" aria-label="TT by Domain chart">
              <ReactECharts option={domainOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('domain')} />
            </div>
          </Card>
        </Col>
        <Col xs={24} md={12} lg={7}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.rootCauseMain')} <ExplainIcon text={t('ttwo.explain.rootCause')} /></span>} size="small" style={cardStyle}>
            <div role="img" aria-label="Root Cause Main chart">
              <ReactECharts option={rcMainOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('rc_main')} />
            </div>
          </Card>
        </Col>
        <Col xs={24} md={12} lg={7}>
          <Card title={<span style={cardTitleStyle}>{t('ttwo.rootCauseSub')} <ExplainIcon text={t('ttwo.explain.rootCause')} /></span>} size="small" style={cardStyle}>
            <div role="img" aria-label="Root Cause Sub chart">
              <ReactECharts option={rcSubOption} style={{ height: CHART_HEIGHT }}
                onEvents={onChartClick('rc_sub')} />
            </div>
          </Card>
        </Col>
      </Row>
      </>}

      {/* WO Source + Status —— 属完整页（page=ttwo）的区块：那里它是「WO 侧画像」，
          与上面的 TT 统计并列。**三档切片都不出** —— page=wo 上统计卡片已经就是
          eflow_wo 口径，再放两张同含义的图会让人以为是两个指标。
          wo_total > 0 的条件保留：没有 WO 数据时画两张空图不如不出。 */}
      {!isSlicePage && data.summary.wo_total > 0 && <>
        <SectionTitle icon={<TagsOutlined />} title={t('ttwo.woAnalytics')} />
        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}>
            <Card title={<span style={cardTitleStyle}>{t('ttwo.woBySource')}</span>} size="small" style={cardStyle}>
              <div role="img" aria-label="WO by Source chart">
                <ReactECharts option={woSourceOption} style={{ height: CHART_HEIGHT }}
                  onEvents={onChartClick('wo_source')} />
              </div>
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card title={<span style={cardTitleStyle}>{t('ttwo.woByStatus')}</span>} size="small" style={cardStyle}>
              <div role="img" aria-label="WO by Status chart">
                <ReactECharts option={woStatusOption} style={{ height: CHART_HEIGHT }}
                  onEvents={onChartClick('wo_status')} />
              </div>
            </Card>
          </Col>
        </Row>
      </>}

      {/* 站点信息 —— **只属完整页**（page=ttwo）：与「领域与根因分析」同属 MTTR 趋势
          之下的下半部分，v1_ttwo / tt / wo 三档切片都不出。
          需求（2026-09-27）：WO 页与 TT 页版式逐块一致，都只到 MTTR 趋势为止。 */}
      {!isSlicePage && <>
      <SectionTitle icon={<EnvironmentOutlined />} title={t('ttwo.siteInfo')} />
      <Row gutter={[12, 12]}>
        {Object.entries(data.site_stats || {}).filter(([, v]) => v && Object.keys(v as any).length > 0).map(([key, stats]) => (
          <Col xs={24} sm={12} lg={8} key={key}>
            <Card title={<span style={cardTitleStyle}>{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>} size="small" style={cardStyle}>
              <ReactECharts option={{
                tooltip: { ...tooltipStyle, trigger: 'axis' },
                grid: { left: 100, right: 30, top: 10, bottom: 10 },
                xAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
                yAxis: { type: 'category', data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map(e => e[0]), axisLabel: { ...axisLabel(isDark), color: cText } },
                series: [{ type: 'bar', barMaxWidth: 18, data: Object.entries(stats as Record<string, number>).sort((a: any, b: any) => b[1] - a[1]).slice(0, 10).map((e: any, i: number) => ({ value: e[1], itemStyle: { color: cPalette[i % cPalette.length], borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: 'right', fontSize: 9, color: cTextMuted } }],
              }} style={{ height: CHART_HEIGHT }} onEvents={onChartClick(key)} />
            </Card>
          </Col>
        ))}
      </Row>
      </>}

      {/* 下钻 Modal */}
      <DraggableClickModal
        open={drillVisible}
        anchor={drillAnchor}
        onClose={() => setDrillVisible(false)}
        title={<span style={{ color: WH.text }}>{drillTitle} <Tag color="cyan">{t('common.records', { n: filteredDrillData.length })}</Tag></span>}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('common.searchAllFields')}
            allowClear
            size="middle"
            style={{ width: 'min(100%, 21.875rem)' }}
            value={drillSearch}
            onChange={e => setDrillSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={exportToExcel}
            disabled={!filteredDrillData.length}
          >
            {t('common.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table
              dataSource={filteredDrillData}
              columns={drillColumns}
              size="small"
              rowKey={(r: any, i?: number) => `${Object.values(r).slice(0, 3).join('-')}-${i}`}
              pagination={{ pageSize: 15, size: 'small', showTotal: (total: number) => t('common.itemsTotal', { n: total }) }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </DraggableClickModal>
    </div>
  )
}
