/* ============================================================================
 * IPT 站点电源查询（?page=ipt_power）—— 2026-11-03 新增，2026-11-04 重设计
 * ============================================================================
 * 数据链路（三段，口径见页内「数据口径说明」）：
 *   1. 采集：任务 ipt_power_collect 每 5 分钟直连 IPT Digital Platform（RMS 能源监控）：
 *      - filter-map 刷全站（~500 站）连接状态 → ipt_power_sites（不含电源数值）；
 *      - full_kpi：并发拉全站 /popup 轻量 KPI（501 站实测 60s）→ 每站每 5 分钟
 *        一条快照（负载/电池电压/SOC/太阳能/柴油/油机开关/活动告警）——全站 5 分钟
 *        分辨率由此实现（2026-11-04 前只有 3 个关注站有数据）；
 *      - full_shard：/diagram 完整明细分片轮采（并发 16，≤60 站/轮约 15s，约 20 分钟
 *        覆盖全站）→ ipt_power_snapshots 明细列 + ipt_power_site_detail 每站最新明细。
 *   2. 页面布局（2026-11-04）：左侧 3/5 为站点地图（Leaflet + 自托管 PMTiles 底图，
 *      与 GISMap 同一套组件）；右侧 2/5 为站点清单表。
 *      2026-11-06 地图加**县底色**图层（按该县有 SOC 快照站点的平均 SOC 分五档，
 *      开关在地图卡标题右侧）：计算在 ./iptPower/countySoc.ts，绘制在
 *      ./iptPower/CountySocLayer.tsx，圆点抬到 iptSitePane(650) 保证仍可点。
 *   3. 详情/曲线（2026-11-05 改为居中弹窗；2026-11-06 按用户要求改成**右侧通高抽屉**，
 *      形态对齐 ?page=mwRealTime 点链路的链路详情抽屉与 ?page=gis 的 SiteDrilldownDrawer）：
 *      点地图圆点或行内「详情」→ 从右侧滑入的抽屉（宽 min(95vw, 45rem) + 遮罩 +
 *      标题栏「立即刷新」/× + 内容区自身滚动），压住右列清单表，左列地图仍然可见。
 *      读单站快照序列（/api/ipt-power/site/{id}），含每站最新 diagram
 *      明细（发电机 R/S-T 相电压相电流/电池组容量与今日电压/油箱容量/主源状态）；
 *      「立即刷新」为实时直查 portal（/api/ipt-power/refresh），不依赖 5 分钟节拍。
 * 查询条件（keyword / hours / site）走 urlState，跨卸载恢复（AGENTS.md 约定）；
 * iptSite 同时也是「抽屉是否打开」的真相源——带该参数的深链会直接弹出对应站点详情。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Drawer, Empty, Input, Row, Select, Space, Spin, Switch, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import {
  WH, useTheme, cardStyle,
  axisLabel, axisLine, darkTooltip, splitLine,
} from '../theme'
import { CardBase, StatCard } from '../components/cards'
import CalcChainNote from '../components/CalcChainNote'
import { CountySocLayer } from './iptPower/CountySocLayer'
import {
  SOC_BAND_COLOR, SOC_BAND_ORDER, aggregateCountySoc, bandLabelKey,
} from './iptPower/countySoc'
import { exportAoaReport } from '../utils/excelReport'
import { readParam, writeParams } from '../urlState'
import {
  iptPowerRefresh, iptPowerSiteDetail, iptPowerSites, iptPowerStatus,
} from '../api'
import { MapContainer, CircleMarker, Pane } from '../components/LeafletMap'
import { PmtilesLayer } from './gismap/PmtilesLayer'
import { BASEMAP_PMTILES_URL, BASEMAP_MAX_ZOOM } from './gismap/basemap'

const { Text } = Typography

/** 统一空值展示 */
const fmt = (v: unknown) => (v == null || v === '' ? '-' : String(v))
const fmtNum = (v: unknown, digits = 1) =>
  (v == null || v === '' ? '-' : Number(v).toFixed(digits))
/** W → kW 展示（上游 loadPower/solarPower 单位是 W，RMS 门户按 kW 展示） */
const fmtKw = (v: unknown, digits = 1) =>
  (v == null ? '-' : `${(Number(v) / 1000).toFixed(digits)} kW`)

/* ---- 类型（与后端 routers/ipt_power.py 返回对齐） ---- */
type AlarmInfo = { name?: string; criticality?: string; created?: string; category?: string }
type SiteRow = {
  site_id: string; name: string; internal_reference: string
  organization: string; cluster: string; priority: string; configuration: string
  connectivity: string; criticality: string; lat: number; lon: number
  connectivity_updated: string; updated_at: string
  snap_time: string; load_current: number; load_power: number
  battery_voltage: number; battery_soc: number; battery_charging_state: string
  solar_power: number; generator_on: number; fuel_ratio: number
  fuel_level: number; fuel_capacity: number; grid_on: number
  main_source_on: number; solar_available: number
  alarm_count: number; alarm_names: AlarmInfo[]; source: string
  watched: boolean
}
type HistoryRow = {
  snap_time: string; load_current: number; load_power: number
  battery_voltage: number; battery_current: number; battery_power: number
  battery_soc: number; battery_charging_state: string; battery_temp1: number
  generator_on: number; solar_power: number; solar_current: number
  fuel_level: number; fuel_ratio: number; grid_on: number; alarm_count: number
}
/** ipt_power_site_detail.detail：slim diagram（后端已剥设备凭据） */
type SlimItem = Record<string, any> & { events?: AlarmInfo[] }
type SiteDetail = {
  loads?: SlimItem[]; batterySets?: SlimItem[]; generators?: SlimItem[]
  rectifiers?: SlimItem[]; fuelTanks?: SlimItem[]; grids?: SlimItem[]
  gridBackups?: SlimItem[]; solarSets?: SlimItem[]
  environment?: Record<string, any>
  coreSiteConnectors?: { mainSourceOn?: boolean | null }
}
type StatusInfo = {
  last_run: null | {
    time: string; success: boolean; sites: number; snapshots: number
    snap_failed: number; kpi_ok?: number; kpi_failed?: number
    detail_ok?: number; detail_failed?: number
    watch: number; duration_s: number
    rows_ipt_power_sites?: number; rows_ipt_power_snapshots?: number
    rows_ipt_power_site_detail?: number
    last_snapshot?: string
  }
}

const HOURS_OPTIONS = [6, 24, 72, 168]
/** 利比里亚国土中心（与 GISMap 的 LB_CENTER 同源：bbox 3.9,-11.7 ~ 8.75,-7.3） */
const LB_CENTER: [number, number] = [6.325, -9.5]

/**
 * 详情抽屉宽度：`min(95vw, 45rem)`，与 GIS 下钻抽屉 `SiteDrilldownDrawer.tsx:265`
 * 同一表达式、同一根字号 → **两页像素级同宽**（桌面 810px）。
 *
 * ⚠ 「和 MW 微波实时对齐」只是**公式与位置**对齐，不是像素对齐：站内根字号是
 *   `html{font-size:clamp(14px,.55vw+12.2px,18px)}`（`index.css:680`），桌面取 18px
 *   → 45rem = 810px；`public/mw_real_time.html` 那份 legacy HTML 没设 html 字号，
 *   同一公式按默认 16px 算 = 720px。（该文件 :187 的注释写「45rem = 720px，与 GIS
 *   抽屉保持一致」，只对了前半句 —— GIS 那侧实际是 810px。）
 *
 * ⚠ 遮挡实测（headless Chrome 截图量得）：1920 宽屏地图卡右缘 ≈1109px、抽屉左缘
 *   = 1110px → **正好贴边，一像素不盖地图**；1600 宽屏地图卡右缘 ≈925px、抽屉左缘
 *   ≈790px → 盖掉地图右缘约 135px（抽屉比那一列表格宽出一截）。
 *   地图主体与刚点中的圆点始终可见 —— 这正是「像 MW 那样显示在右边」而不是挡正中。
 *   （`personmap/PersonDrilldownDrawer.tsx:42` 刻意用 24rem，因为那页要求一像素不挡
 *   地图；本页地图在左列，45rem 不冲突，所以跟 GIS 那一档。）
 *
 * **为什么是 antd Drawer 而不是项目统一的 `components/DraggableClickModal`**
 * （AGENTS.md 三.3 的下钻弹窗入口）：用户 2026-11-06 指定的参考实现就是 MW 页点链路
 * 后的**右侧通高抽屉**，而 DraggableClickModal 跟着点击锚点走（居中/置顶），
 * 做不出「贴右、通高、滑入」。先例同样是照参考页做抽屉的
 * `pages/personmap/PersonDrilldownDrawer.tsx:8`。抽屉本体是 antd 组件而不是自造骨架，
 * 所以并没有「各页写一套弹窗」。
 */
const DRAWER_WIDTH = 'min(95vw, 45rem)' as any

/** 详情小卡的键值行 */
function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8,
                  fontSize: 12.5, lineHeight: '22px' }}>
      <Text type="secondary" style={{ flexShrink: 0 }}>{k}</Text>
      <Text strong style={{ textAlign: 'right', wordBreak: 'break-all' }}>{v}</Text>
    </div>
  )
}

export default function IptPowerQuery() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 查询条件（URL 是唯一真相源） ---- */
  const [keyword, setKeyword] = useState(() => readParam('iptKw'))
  const [hours, setHours] = useState<number>(() => {
    const v = Number(readParam('iptHrs'))
    return HOURS_OPTIONS.includes(v) ? v : 24
  })
  const [watchOnly, setWatchOnly] = useState(false)
  /* 县底色图层开关：默认开（用户 2026-11-06 要的就是这个效果）。
     刻意不写进 URL —— 与 GIS 页同一约定：图层状态不持久化，刷新回默认。 */
  const [showCountyBg, setShowCountyBg] = useState(true)
  const [siteId, setSiteId] = useState(() => readParam('iptSite'))

  useEffect(() => { writeParams({ iptKw: keyword, iptSite: siteId, iptHrs: String(hours) }) },
    [keyword, siteId, hours])

  /* ---- 数据三件套 ---- */
  const [rows, setRows] = useState<SiteRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusInfo, setStatusInfo] = useState<StatusInfo>({ last_run: null })

  /* ---- 选中站点详情 ---- */
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailSite, setDetailSite] = useState<SiteRow | null>(null)
  const [detailInfo, setDetailInfo] = useState<{ detail: SiteDetail; updated_at: string } | null>(null)
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')

  const loadSites = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await iptPowerSites({ keyword: keyword || undefined, limit: 1000 })
      setRows(r.data?.sites || [])
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [keyword])

  const loadStatus = useCallback(async () => {
    try {
      const r = await iptPowerStatus()
      setStatusInfo({ last_run: r.data?.last_run || null })
    } catch { /* 状态条失败不阻塞主数据 */ }
  }, [])

  const loadDetail = useCallback(async (sid: string) => {
    setDetailLoading(true)
    try {
      const r = await iptPowerSiteDetail(sid, hours)
      setDetailSite(r.data?.site || null)
      setDetailInfo(r.data?.detail || null)
      setHistory(r.data?.history || [])
    } catch (e: any) {
      // 换站失败时不要留着上一个站的详情，否则抽屉里会出现「标题 A、内容 B」
      setDetailSite(null)
      setDetailInfo(null)
      setHistory([])
      setRefreshMsg(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setDetailLoading(false)
    }
  }, [hours])

  /* ---- 抽屉开关：iptSite 是唯一真相源（关闭即清 URL 参数） ---- */
  const openDetail = useCallback((sid: string) => {
    setRefreshMsg('')
    setSiteId(sid)
  }, [])
  const closeDetail = useCallback(() => {
    setSiteId('')
    setRefreshMsg('')
  }, [])

  useEffect(() => { void loadSites(); void loadStatus() }, [loadSites, loadStatus])
  useEffect(() => {
    if (siteId) void loadDetail(siteId)
    else { setDetailSite(null); setDetailInfo(null); setHistory([]) }
  }, [siteId, loadDetail])

  /* ---- 立即刷新：实时直查 portal（按站点名，后端自动落一条快照+明细） ---- */
  const doRefresh = useCallback(async () => {
    if (!detailSite) return
    setRefreshing(true)
    setRefreshMsg('')
    try {
      await iptPowerRefresh(detailSite.name)
      await loadDetail(detailSite.site_id)
      await loadSites()
      await loadStatus()
    } catch (e: any) {
      setRefreshMsg(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setRefreshing(false)
    }
  }, [detailSite, loadDetail, loadSites, loadStatus])

  /* ---- 汇总 ---- */
  const stats = useMemo(() => ({
    total: rows.length,
    online: rows.filter(r => r.connectivity === 'online').length,
    offline: rows.filter(r => r.connectivity === 'offline').length,
    alarms: rows.filter(r => (r.alarm_count || 0) > 0).length,
  }), [rows])

  /* ---- 地图标记颜色：离线红 / 有活动告警橙 / 正常绿 ---- */
  const markerColor = useCallback((r: SiteRow) => {
    if (r.connectivity !== 'online') return isDark ? '#ff7875' : '#ff4d4f'
    if ((r.alarm_count || 0) > 0) return isDark ? '#ffc53d' : '#faad14'
    return isDark ? '#95de64' : '#389e0d'
  }, [isDark])

  const mapSites = useMemo(() => rows.filter(r => r.lat != null && r.lon != null), [rows])

  /* 县底色 = 该县**有 SOC 快照的站点**的算术平均，输入就是地图上这批点（mapSites），
     所以搜索词一改底色跟着改；「只看关注」只过滤表格、不动地图，因此也不动底色。
     口径全文见下方 CalcChainNote 的第 4 段。 */
  const countySoc = useMemo(() => aggregateCountySoc(mapSites), [mapSites])

  /** 油机/状态保持时长（如「Turned Off since 5 hours」） */
  const sinceLabel = useCallback((iso?: string | null) => {
    if (!iso) return '-'
    const h = dayjs().diff(dayjs(iso), 'hour', true)
    if (!Number.isFinite(h) || h < 0) return '-'
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`
    if (h < 48) return `${h.toFixed(1)} h`
    return `${(h / 24).toFixed(1)} d`
  }, [])

  /* ---- 曲线：左轴功率（W），右轴 SOC（%）----
   * 简化为双 y 轴：左 = load_power / solar_power（W），右 = battery_soc（%，0-1 → ×100）。
   * 电压/温度走详情数字卡，不进曲线（量纲太多互相压扁）。 */
  const chartOption = useMemo(() => {
    const xs = history.map(h => (h.snap_time || '').slice(5, 16))
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
      legend: { textStyle: { color: isDark ? '#d0d7de' : '#444' }, top: 0 },
      grid: { left: 56, right: 56, top: 36, bottom: 56 },
      xAxis: {
        type: 'category', data: xs,
        axisLabel: { ...axisLabel(isDark), rotate: 35 },
        axisLine: axisLine(isDark),
      },
      yAxis: [
        { type: 'value', name: 'W', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
        { type: 'value', name: '%', min: 0, max: 100, position: 'right',
          axisLabel: axisLabel(isDark), splitLine: { show: false } },
      ],
      series: [
        { name: t('ipt.series.load'), type: 'line', showSymbol: false, smooth: true,
          data: history.map(h => h.load_power), itemStyle: { color: isDark ? '#00d9ff' : '#0d9488' } },
        { name: t('ipt.series.solar'), type: 'line', showSymbol: false, smooth: true,
          data: history.map(h => h.solar_power), itemStyle: { color: isDark ? '#ffd666' : '#d48806' } },
        { name: t('ipt.series.soc'), type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true,
          data: history.map(h => (h.battery_soc == null ? null : Number(h.battery_soc) * 100)),
          itemStyle: { color: isDark ? '#ff7a45' : '#d4380d' } },
      ],
    }
  }, [history, isDark, t])

  const exportRows = useCallback(() => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `ipt_power_sites_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'IPT Power Sites',
      title: 'IPT Power Sites',
      header: [
        t('ipt.col.name'), t('ipt.col.ref'), t('ipt.col.org'), t('ipt.col.cluster'),
        t('ipt.col.priority'), t('ipt.col.config'), t('ipt.col.connectivity'),
        'SOC %', t('ipt.col.load'), t('ipt.col.solar'), t('ipt.col.fuel'),
        t('ipt.col.alarms'), t('ipt.col.snapTime'),
      ],
      rows: rows.map(r => [
        r.name, r.internal_reference, r.organization, r.cluster, r.priority,
        r.configuration, r.connectivity,
        r.battery_soc == null ? '' : Number(r.battery_soc) * 100,
        r.load_power,
        r.solar_available === 0 ? '' : r.solar_power,
        r.fuel_level, r.alarm_count, r.snap_time,
      ]),
      numericCols: [7, 8, 9, 10, 11],
    })
  }, [rows, t])

  /* ---- 右侧站点表（2/5 宽，故列收窄：区域/优先级/配置进弹窗与详情） ---- */
  const columns = useMemo(() => [
    { title: t('ipt.col.name'), dataIndex: 'name',
      render: (v: string, r: SiteRow) => (
        <Space size={4}>
          {r.watched && <ThunderboltOutlined style={{ color: WH.warn }} />}
          <Text strong style={{ color: WH.text }}>{v}</Text>
        </Space>
      ) },
    { title: t('ipt.col.ref'), dataIndex: 'internal_reference', width: 70, render: fmt },
    { title: t('ipt.col.connectivity'), dataIndex: 'connectivity', width: 88,
      render: (v: string) => v === 'online'
        ? <Tag color="green">online</Tag>
        : <Tag color="red">{fmt(v)}</Tag> },
    { title: 'SOC', dataIndex: 'battery_soc', width: 66,
      sorter: (a: SiteRow, b: SiteRow) => (a.battery_soc || 0) - (b.battery_soc || 0),
      render: (v: number) => v == null ? '-' : `${(v * 100).toFixed(0)}%` },
    { title: t('ipt.col.load'), dataIndex: 'load_power', width: 92,
      sorter: (a: SiteRow, b: SiteRow) => (a.load_power || 0) - (b.load_power || 0),
      render: (v: number) => v == null ? '-' : fmtKw(v) },
    { title: t('ipt.col.solar'), dataIndex: 'solar_power', width: 92,
      sorter: (a: SiteRow, b: SiteRow) => (a.solar_power || 0) - (b.solar_power || 0),
      render: (v: number, r: SiteRow) => (r.solar_available === 0 ? '-' : fmtKw(v)) },
    { title: t('ipt.col.fuel'), dataIndex: 'fuel_level', width: 84,
      sorter: (a: SiteRow, b: SiteRow) => (a.fuel_level || 0) - (b.fuel_level || 0),
      render: (v: number) => (v == null ? '-' : `${fmtNum(v, 0)} L`) },
    { title: t('ipt.col.alarms'), dataIndex: 'alarm_count', width: 70,
      sorter: (a: SiteRow, b: SiteRow) => (a.alarm_count || 0) - (b.alarm_count || 0),
      render: (v: number, r: SiteRow) => (v == null ? '-'
        : v > 0
          ? <Tag color="orange" title={(r.alarm_names || []).map(a => a.name).join('; ')}>
              {`⚠ ${v}`}
            </Tag>
          : <Tag color="green">0</Tag>) },
    { title: t('ipt.col.snapTime'), dataIndex: 'snap_time', width: 145, render: fmt },
    {
      title: t('ipt.col.action'), key: 'action', width: 76,
      render: (_: unknown, r: SiteRow) => (
        <Button type="link" size="small" onClick={() => openDetail(r.site_id)}>
          {t('ipt.detail')}
        </Button>
      ),
    },
  ], [t, openDetail])

  const latest = history.length ? history[history.length - 1] : null
  const gen = detailInfo?.detail?.generators?.[0]
  const batt = detailInfo?.detail?.batterySets?.[0]
  const tank = detailInfo?.detail?.fuelTanks?.[0]
  const rect = detailInfo?.detail?.rectifiers?.[0]
  const grid = detailInfo?.detail?.grids?.[0]
  const latestAlarms: AlarmInfo[] = (detailSite as any)?.alarm_names || []
  /* 详情搬进浮层（2026-11-05 居中弹窗 → 2026-11-06 右侧抽屉）后，页面下半屏不再被
     详情卡占着，地图可以吃掉这部分高度。仍是 clamp 兜底：小窗不低于 440px，大窗封顶
     820px，避免超高屏拉出巨型地图。抽屉打开时压住的是右列表格那一列：1920 宽屏正好
     贴边、不盖地图，1600 宽实测盖掉地图右缘约 135px（细节见 DRAWER_WIDTH 注释）。 */
  const mapCardHeight = 'clamp(440px, calc(100vh - 280px), 820px)'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder={t('ipt.search')}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={() => void loadSites()}
            style={{ width: 240 }}
          />
          <Select
            value={hours}
            onChange={setHours}
            options={HOURS_OPTIONS.map(h => ({ value: h, label: t('ipt.hours', { n: h }) }))}
            style={{ width: 120 }}
          />
          <Button
            type={watchOnly ? 'primary' : 'default'}
            icon={<ThunderboltOutlined />}
            onClick={() => setWatchOnly(v => !v)}
          >
            {t('ipt.watchOnly')}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void loadSites()} loading={loading}>
            {t('common.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {/* ② 采集状态：异常（任务没跑过/失败）常驻可见；正常收进口径说明 */}
      {error && <Alert type="error" showIcon message={error} />}
      {statusInfo.last_run && !statusInfo.last_run.success && (
        <Alert type="warning" showIcon
          message={t('ipt.statusFailed', { time: statusInfo.last_run.time })} />
      )}
      {!statusInfo.last_run && (
        <Alert type="warning" showIcon message={t('ipt.statusNever')} />
      )}

      {/* ③ 全页数据口径说明：默认收起（AGENTS.md 3b）。放在页面而不是弹窗里，
          这样没打开任何站点详情时也能查口径；说「这次采集失败」的异常横幅仍常驻。 */}
      <CalcChainNote
        title={t('ipt.note.title')}
        sections={[
          { title: t('ipt.note.source'), lines: [t('ipt.note.sourceBody')] },
          { title: t('ipt.note.watch'), lines: [t('ipt.note.watchBody')] },
          { title: t('ipt.note.retention'), lines: [t('ipt.note.retentionBody')] },
          { title: t('ipt.note.county'), lines: [t('ipt.note.countyBody')] },
        ]}
      />

      {/* ④ 数字卡 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('ipt.kpi.total')} value={stats.total} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('ipt.kpi.online')} value={stats.online} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <CardBase level={stats.offline > 0 ? 'warn' : 'ok'} title={t('ipt.kpi.offline')} as="div">
            <Text strong style={{ fontSize: 24, color: stats.offline > 0 ? WH.danger : WH.ok }}>
              {stats.offline}
            </Text>
          </CardBase>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <CardBase level={stats.alarms > 0 ? 'warn' : 'ok'} title={t('ipt.kpi.alarms')} as="div">
            <Text strong style={{ fontSize: 24, color: stats.alarms > 0 ? WH.warn : WH.ok }}>
              {stats.alarms}
            </Text>
          </CardBase>
        </Col>
      </Row>

      {/* ⑤ 左 3/5 站点地图（点击圆点开右侧详情抽屉） + 右 2/5 站点清单表 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={14} style={{ minWidth: 0 }}>
          <CardBase
            title={t('ipt.map.title')}
            bodyStyle={{ padding: 8 }}
            extra={
              <Space size={10} wrap style={{ fontSize: 12 }}>
                <Space size={4}><span style={{ width: 8, height: 8, borderRadius: '50%',
                  background: markerColor({ connectivity: 'online', alarm_count: 0 } as SiteRow),
                  display: 'inline-block' }} /><Text type="secondary">{t('ipt.map.legend.online')}</Text></Space>
                <Space size={4}><span style={{ width: 8, height: 8, borderRadius: '50%',
                  background: markerColor({ connectivity: 'online', alarm_count: 1 } as SiteRow),
                  display: 'inline-block' }} /><Text type="secondary">{t('ipt.map.legend.alarm')}</Text></Space>
                <Space size={4}><span style={{ width: 8, height: 8, borderRadius: '50%',
                  background: markerColor({ connectivity: 'offline', alarm_count: 0 } as SiteRow),
                  display: 'inline-block' }} /><Text type="secondary">{t('ipt.map.legend.offline')}</Text></Space>
                {/* 县底色：开关 + 五档图例（方角色块，和圆点图例区分开）。
                    关掉图层时只留开关，避免卡片头被撑到三行。 */}
                <Space size={6} wrap>
                  <Switch size="small" checked={showCountyBg} onChange={setShowCountyBg}
                    aria-label={t('ipt.county.layer')} />
                  <Text type="secondary">{t('ipt.county.layer')}</Text>
                  {showCountyBg && SOC_BAND_ORDER.map(b => (
                    <Space key={b} size={4}>
                      <span style={{ width: 10, height: 10, borderRadius: 2,
                        background: SOC_BAND_COLOR[b], display: 'inline-block' }} />
                      <Text type="secondary">{t(bandLabelKey(b))}</Text>
                    </Space>
                  ))}
                </Space>
              </Space>
            }
          >
            <MapContainer
              center={LB_CENTER}
              zoom={8}
              style={{ height: mapCardHeight, width: '100%', background: 'var(--wh-page-bg)' }}
            >
              <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} maxZoom={BASEMAP_MAX_ZOOM} />
              {/* 站点圆点专用 pane（照 GISMap.tsx:2808 同一做法）：县底色是**可 hover 的
                  整面多边形**，和圆点同在默认 overlayPane(400) 时，命中只靠「谁后加入谁在上」
                  —— 那是 DOM 顺序，不保证。抬到 650 后，圆点在县块之上是层级决定的，
                  点圆点开抽屉不会被县块截走。（取 650 = 与 Leaflet tooltipPane 同档、
                  低于 popupPane 700，与 GIS 页同一档。） */}
              <Pane name="iptSitePane" style={{ zIndex: 650 }} />
              {showCountyBg && <CountySocLayer stats={countySoc} isDark={isDark} />}
              {mapSites.map(r => (
                /* 单击圆点直接开「电源详情」抽屉（与 mwRealTime 点链路开右侧抽屉一致）——
                   抽屉贴右通高，左列地图不被挡，刚点中的那个圆点仍看得见。
                   原先叠加的 Leaflet 小 Popup 已移除：两层浮层会互相遮挡；
                   小 Popup 里的站点属性改为抽屉顶部的紧凑信息条承载。 */
                <CircleMarker
                  key={r.site_id}
                  pane="iptSitePane"
                  center={[r.lat, r.lon]}
                  radius={r.watched ? 7 : 5}
                  fillColor={markerColor(r)}
                  color={isDark ? '#0a1428' : '#ffffff'}
                  weight={1.5}
                  opacity={1}
                  fillOpacity={1}
                  onClick={() => openDetail(r.site_id)}
                />
              ))}
            </MapContainer>
          </CardBase>
        </Col>
        <Col xs={24} xl={10} style={{ minWidth: 0 }}>
          <CardBase title={t('ipt.table.title')} interactive={false} bodyStyle={{ padding: 8 }}>
            <Table
              rowKey="site_id"
              columns={columns}
              dataSource={watchOnly ? rows.filter(r => r.watched) : rows}
              loading={loading}
              pagination={{ pageSize: 15, showSizeChanger: true, size: 'small' }}
              scroll={{ x: 860, y: `calc(${mapCardHeight} - 96px)` }}
              size="small"
            />
          </CardBase>
        </Col>
      </Row>

      {/* ⑥ 电源详情抽屉（形态照 ?page=mwRealTime 点链路的右侧抽屉）：
          右侧通高滑入 + 遮罩 + 标题栏（站点名 / 立即刷新 / ×）+ 内容区自身滚动；
          open 由 URL 参数 iptSite 决定，关闭即清参数（带该参数的深链仍会直接弹出）；
          内容沿用原来的六张数字卡 + 设备明细卡 + 活动告警 + 近 N 小时曲线。
          ⚠ 栅格按抽屉那一栏重排：数字卡一行 3 张、设备卡一行 2 张 —— 原来的
          lg=4 / lg=6 是照 1100px 宽弹窗排的，在 810px 抽屉里会变成一行 6 格 / 4 格，
          每格只剩 120~200px，数字卡标题被挤成竖排。断点是**视口**的而不是容器的，
          所以这里不写 lg 档。
          ⚠ 参考号 / 连接状态更新从标题栏搬进内容区的站点属性条：抽屉 header 塞不下
          「标题 + meta + 按钮」三段（站点名长时会把「立即刷新」挤没），信息一条没少。 */}
      <Drawer
        placement="right"
        width={DRAWER_WIDTH}
        open={Boolean(siteId)}
        onClose={closeDetail}
        title={t('ipt.detailTitle', {
          name: detailSite?.name || rows.find(r => r.site_id === siteId)?.name || siteId,
        })}
        extra={(
          <Button size="small" icon={<ReloadOutlined />}
            disabled={!detailSite} onClick={() => void doRefresh()} loading={refreshing}>
            {t('ipt.refreshNow')}
          </Button>
        )}
      >
        {refreshMsg && <Alert type="error" showIcon message={refreshMsg}
          style={{ marginBottom: 'var(--wh-space-sm)' }} closable />}
        {!detailSite ? (
          <div style={{ minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spin spinning={detailLoading}>
              <Text type="secondary">{t('common.loading')}</Text>
            </Spin>
          </div>
        ) : (
          <Spin spinning={detailLoading}>
            {/* 紧凑站点属性条：承载原先 Leaflet 小 Popup 里的身份信息 */}
            <div style={{
              display: 'flex', flexWrap: 'wrap', gap: '4px 18px', fontSize: 12.5,
              padding: '2px 0 10px',
              borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,.10)' : '#f0f0f0'}`,
            }}>
              <span><Text type="secondary">{t('ipt.col.ref')}: </Text><Text strong>{fmt(detailSite.internal_reference)}</Text></span>
              <span><Text type="secondary">{t('ipt.col.org')}: </Text><Text strong>{fmt(detailSite.organization)}</Text></span>
              <span><Text type="secondary">{t('ipt.col.cluster')}: </Text><Text strong>{fmt(detailSite.cluster)}</Text></span>
              <span><Text type="secondary">{t('ipt.col.priority')}: </Text><Text strong>{fmt(detailSite.priority)}</Text></span>
              <span><Text type="secondary">{t('ipt.col.config')}: </Text><Text strong>{fmt(detailSite.configuration)}</Text></span>
              <span><Text type="secondary">{t('ipt.col.connectivity')}: </Text>
                <Tag color={detailSite.connectivity === 'online' ? 'green' : 'red'}>
                  {fmt(detailSite.connectivity)}
                </Tag></span>
              <span><Text type="secondary">{t('ipt.col.snapTime')}: </Text><Text strong>{fmt(detailSite.snap_time)}</Text></span>
              {/* 原弹窗标题栏上的「连接状态更新」：抽屉 header 只留标题 + 刷新按钮，
                  meta 统一收到这条属性栏里（信息不减，header 不换行） */}
              {detailSite.connectivity_updated && (
                <span><Text type="secondary">{t('ipt.connUpdated')}: </Text>
                  <Text strong>{fmt(detailSite.connectivity_updated)}</Text></span>
              )}
            </div>

            <Row gutter={[12, 12]} style={{ marginTop: 'var(--wh-space-sm)' }}>
              <Col xs={12} sm={8}>
                <StatCard title="SOC" value={latest?.battery_soc == null ? '-' : `${(Number(latest.battery_soc) * 100).toFixed(0)}%`} />
              </Col>
              <Col xs={12} sm={8}>
                <StatCard title={t('ipt.card.battV')} value={latest?.battery_voltage == null ? '-' : `${fmtNum(latest.battery_voltage)} V`} />
              </Col>
              <Col xs={12} sm={8}>
                <StatCard title={t('ipt.card.charging')} value={fmt(latest?.battery_charging_state)} />
              </Col>
              <Col xs={12} sm={8}>
                <StatCard title={t('ipt.card.load')} value={latest?.load_power == null ? '-' : fmtKw(latest.load_power)} />
              </Col>
              <Col xs={12} sm={8}>
                <StatCard title={t('ipt.card.solar')}
                  value={detailSite.solar_available === 0 ? '-' : (latest?.solar_power == null ? '-' : fmtKw(latest.solar_power))} />
              </Col>
              <Col xs={12} sm={8}>
                <StatCard title={t('ipt.card.generator')} value={latest == null
                  ? '-' : (latest.generator_on ? t('ipt.genOn') : t('ipt.genOff'))} />
              </Col>
            </Row>

            {/* 设备明细（来源 ipt_power_site_detail 的 slim diagram；popup KPI 层无这些字段） */}
            {detailInfo?.detail ? (
              <Row gutter={[12, 12]} style={{ marginTop: 'var(--wh-space-sm)' }}>
                <Col xs={24} md={12}>
                  <CardBase title={t('ipt.gen.card')} as="div" bodyStyle={{ padding: 12 }}>
                    <KV k={t('ipt.col.name')} v={fmt(gen?.name)} />
                    <KV k={t('ipt.gen.state')} v={gen?.generatorOn == null ? '-'
                      : (gen.generatorOn ? t('ipt.genOn') : `${t('ipt.genOff')} · ${sinceLabel(gen.generatorOnChanged)}`)} />
                    <KV k={t('ipt.gen.mode')} v={fmt(gen?.generatorOperatingMode)} />
                    <KV k={t('ipt.gen.capacity')} v={gen?.capacity == null ? '-' : `${fmtNum(gen.capacity, 1)} kW`} />
                    <KV k={t('ipt.gen.voltage')}
                        v={`${fmtNum(gen?.generatorVoltagePhase1, 0)} / ${fmtNum(gen?.generatorVoltagePhase2, 0)} / ${fmtNum(gen?.generatorVoltagePhase3, 0)} V`} />
                    <KV k={t('ipt.gen.current')}
                        v={`${fmtNum(gen?.generatorCurrentPhase1, 1)} / ${fmtNum(gen?.generatorCurrentPhase2, 1)} / ${fmtNum(gen?.generatorCurrentPhase3, 1)} A`} />
                  </CardBase>
                </Col>
                <Col xs={24} md={12}>
                  <CardBase title={t('ipt.batt.card')} as="div" bodyStyle={{ padding: 12 }}>
                    <KV k={t('ipt.col.name')} v={fmt(batt?.name)} />
                    <KV k={t('ipt.batt.capacity')} v={batt?.totalCapacity == null ? '-' : `${fmtNum(batt.totalCapacity, 0)} Ah`} />
                    <KV k={t('ipt.batt.systemV')} v={batt?.batteryVoltage == null ? '-' : `${fmtNum(batt.batteryVoltage)} V`} />
                    <KV k={t('ipt.batt.level')} v={batt?.batteryStateOfCharge == null ? '-' : `${(batt.batteryStateOfCharge * 100).toFixed(0)}%`} />
                    <KV k={t('ipt.batt.vToday')}
                        v={`${t('ipt.batt.min')} ${fmtNum(batt?.batteryMinVoltageToday)} ~ ${t('ipt.batt.max')} ${fmtNum(batt?.batteryMaxVoltageToday)} V`} />
                    <KV k={t('ipt.batt.temp')}
                        v={`${fmt(batt?.batteryTemperature1)} / ${fmt(batt?.batteryTemperature2)} ℃`} />
                  </CardBase>
                </Col>
                <Col xs={24} md={12}>
                  <CardBase title={t('ipt.fuel.card')} as="div" bodyStyle={{ padding: 12 }}>
                    <KV k={t('ipt.col.name')} v={fmt(tank?.name)} />
                    <KV k={t('ipt.fuel.level')} v={tank?.fuelLevel == null ? '-'
                      : `${fmtNum(tank.fuelLevel, 0)} / ${fmtNum(tank?.capacity, 0)} L`} />
                    <KV k={t('ipt.fuel.ratio')} v={tank?.fuelRatio == null ? '-' : `${(tank.fuelRatio * 100).toFixed(0)}%`} />
                    <KV k={t('ipt.fuel.updated')} v={fmt((tank?.fuelLevelLastUpdated || '').toString().replace('T', ' ').slice(0, 19))} />
                  </CardBase>
                </Col>
                <Col xs={24} md={12}>
                  <CardBase title={t('ipt.ac.card')} as="div" bodyStyle={{ padding: 12 }}>
                    <KV k={t('ipt.ac.main')} v={rect?.mainSourceOn == null ? '-'
                      : (rect.mainSourceOn ? <Tag color="green">{t('ipt.ac.on')}</Tag>
                                           : <Tag color="red">{t('ipt.ac.off')}</Tag>)} />
                    <KV k={t('ipt.ac.power')} v={rect?.mainSourcePower == null ? '-' : fmtKw(rect.mainSourcePower)} />
                    <KV k={t('ipt.ac.rectI')} v={rect?.rectifierCurrent == null ? '-' : `${fmtNum(rect.rectifierCurrent)} A`} />
                    <KV k={t('ipt.ac.gridV')} v={grid?.gridVoltagePhase1 == null ? '-' : `${fmtNum(grid.gridVoltagePhase1)} V`} />
                  </CardBase>
                </Col>
                <Col xs={24}>
                  <CardBase title={t('ipt.alarms.card')} as="div" bodyStyle={{ padding: 12 }}>
                    {(latestAlarms.length || (detailSite.alarm_count || 0) > 0) ? (
                      <Space size={6} wrap>
                        {latestAlarms.map((a, i) => (
                          <Tag key={i} color={(a.criticality || '').toLowerCase() === 'critical'
                            ? 'red' : (a.criticality || '').toLowerCase() === 'major' ? 'orange' : 'gold'}>
                            {a.name}{a.created ? ` · ${a.created.slice(0, 16).replace('T', ' ')}` : ''}
                          </Tag>
                        ))}
                      </Space>
                    ) : <Text type="secondary">{t('ipt.noAlarms')}</Text>}
                  </CardBase>
                </Col>
              </Row>
            ) : (
              <Alert type="info" showIcon style={{ marginTop: 'var(--wh-space-sm)' }}
                message={t('ipt.detail.noDetail')} />
            )}

            {history.length
              ? <ReactECharts option={chartOption} style={{ height: 320 }} notMerge />
              : <Empty description={t('ipt.noHistory')} style={{ margin: '24px 0' }} />}
          </Spin>
        )}
      </Drawer>
    </div>
  )
}

/* cardStyle 引用保留（避免 lint 未使用告警的写法）：表格行内不套卡，详情抽屉内的小卡由 CardBase 承载 */
void cardStyle
