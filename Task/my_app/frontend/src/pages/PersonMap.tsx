/* 人员位置地图（?page=person，2026-10-19 新增）
 *
 * **需求**（用户原话）：「里面有地图，显示站点和人员的位置。该人员负责的站点在地图分布，
 * 还有 WO/TT 的统计。参考 https://localhost/myapp/?page=realtime_alarm 页面。」
 *
 * **页面结构**（沿用 realtime_alarm / AlarmDashboard 的分区节奏）：
 *   ① 筛选条：时间窗口（固定最近 30 天，见下方常量）+ 搜索 + 刷新 + 导出
 *   ② 非实时说明横幅（必须显示：坐标是静态登记值，28/136 人有坐标）
 *   ③ KPI：有坐标人员 / 负责站点数 / 未清除 WO / 未关闭 WO / 有告警站点
 *   ④ 地图（人员针 + 其 WO 站点 + 连线）
 *   ⑤ 统计：WO/TT 按人员排行（堆叠柱）+ 按县分布（柱状）
 *   ⑥ 人员总表（可点行选中、可搜索、可排序；含无坐标人员，保证合计对得上）
 *   ⑦ 下钻弹窗（DraggableClickModal）：选中人员的站点明细 / WO 明细
 *
 * **两个口径决定**（2026-10-19 经用户确认，勿擅自改回）：
 *   1. 「负责站点」= 该人员 **WO 实际处理过**的站点，不是 `person.managed_regions`。
 *      原因见 backend/routers/personnel.py 的 /managed-sites 头注释。
 *   2. 时间窗口固定**最近 30 天**（不跟随 GIS 页的时间控件）。
 *
 * 后端：`GET /api/gis/personnel/stats` 与 `GET /api/gis/personnel/{key}/managed-sites`
 * 与 `GET /api/gis/personnel/{key}/work-orders`（复用现有端点做 WO 下钻）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Empty, Input, Row, Table, Tag, Tooltip } from 'antd'
import {
  DownloadOutlined, EnvironmentOutlined, ReloadOutlined, SearchOutlined,
  TeamOutlined, WarningOutlined, CloseCircleOutlined, FileDoneOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'

import api from '../api'
import { useI18n, numLocale } from '../i18n'
import {
  WH, useTheme, pageWrap, controlCardStyle,
  axisLabel, axisLine, splitLine, darkTooltip, WH_COLORS, LIGHT_COLORS,
} from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportAoaReport } from '../utils/excelReport'
import { MapContainer } from '../components/LeafletMap'
import { PersonMapView } from './personmap/PersonMapView'
import type { PersonRow, PersonStats, ManagedSite, ManagedSitesResp } from './personmap/types'

/** 固定时间窗口（天）。用户 2026-10-19 确认：页面固定最近 30 天，
 *  不跟随 GIS 页的时间控件（避免两页口径漂移）。 */
const WINDOW_DAYS = 30

/** 地图画布高度：与 GIS 页同量级，门户中列可放下 */
const MAP_HEIGHT = 560

/** 空值统一展示 —（AGENTS.md 三.6：取不到显示 —，不得显示 0） */
const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))

/** 「只显示地图」模式（`?maponly=1`）。
 *
 * **需求**（用户原话，2026-10-19）：「要设计成跟其他页签一样，只显示地图」——
 * v3 门户 GIS Map 栏的 Person 页签要和 Alarm / MW 两页同样只留 Leaflet 画布，
 * 而本页默认是「筛选条 + 说明横幅 + KPI + 图表 + 地图 + 人员表」的完整看板。
 *
 * **为什么在 my_app 侧做、而不是让门户去剥**：
 *   Alarm 页靠 gis 页自己输出「只有地图」的形态（门户的 MAP_STRIP_CSS 只兜底），
 *   走同一条路才是「跟其他页签一样」。门户侧注入的剥离 CSS 改不到 React 的
 *   行内 display 与 DOM 结构，本页的分栏布局它剥不干净。
 *
 * **刻意不用的开关**：`embed=1` / `mwembed=1` 只隐藏外壳（Header/侧栏），
 *   页面本体仍整页渲染；且它们是所有门户壳共用的参数，改它们的语义会牵连
 *   报告文件中心等其它内嵌点。故单起一个只有本页认的参数。
 * 照搬 `?page=mwRealTime` 的 `mwembed=1` 命名习惯，用 `maponly` 表明只是版式开关。 */
function readMapOnlyMode(): boolean {
  try {
    const sp = new URLSearchParams(window.location.search)
    return sp.get('maponly') === '1' || sp.get('maponly') === 'true'
  } catch { return false }
}

/** WO 明细的一行（/work-orders 响应，字段见后端 _WO_COLS） */
interface WoRow {
  wo_no: string
  tt_no?: string
  title?: string
  status?: string
  site_id?: string
  site_name?: string
  county?: string
  region?: string
  alarm_occur_time?: string
  alarm_clear_time?: string
  ticket_severity?: string
  alarm_severity?: string
  operation_step?: string
}

export default function PersonMap() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const nf = (n?: number | null) => (n == null ? '—' : n.toLocaleString(numLocale(locale)))

  /* 只显示地图（门户内嵌）：URL 首次加载求值即可 —— 门户切页签会整块重建 iframe，
     不存在"运行中从完整页切到地图页"的路径，故不做联动重算。 */
  const [mapOnly] = useState<boolean>(readMapOnlyMode)

  const [stats, setStats] = useState<PersonStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [keyword, setKeyword] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [sites, setSites] = useState<ManagedSite[]>([])
  const [sitesLoading, setSitesLoading] = useState(false)

  /* ---- 下钻弹窗：WO 明细 ---- */
  const [woOpen, setWoOpen] = useState(false)
  const [woLoading, setWoLoading] = useState(false)
  const [woRows, setWoRows] = useState<WoRow[]>([])
  const [woAnchor, setWoAnchor] = useState<{ x: number; y: number } | null>(null)

  /* ---------- 取数 ---------- */
  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api.get('/gis/personnel/stats', { params: { days: WINDOW_DAYS } })
      .then(res => setStats(res.data))
      .catch(err => {
        console.error('[PersonMap] stats failed:', err?.response?.status, err?.response?.data || err)
        setStats(null)
        setError(err?.response?.data?.detail || err?.message || String(err))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  /* 选中人员 → 拉其站点。
     ⚠️ 2026-10-19 修：**mapOnly 下同样要拉**。mapOnly 只是隐藏页面外围（筛选条 /
     KPI / 图表 / 人员表），地图本身仍要画「该人员的 WO 站点圆点 + 连线」——
     那是本页地图的主内容。此前写成「mapOnly 下不拉」是误判：以为没人读 sites
     （当时只想到左栏 KPI「负责站点」会消失），结果门户 Person 页签里点人后
     一个站点都不显示。sites 的消费方是 PersonMapView，与 mapOnly 无关。 */
  useEffect(() => {
    if (!selectedKey) { setSites([]); return }
    setSitesLoading(true)
    api.get(`/gis/personnel/${encodeURIComponent(selectedKey)}/managed-sites`,
      { params: { days: WINDOW_DAYS } })
      .then(res => setSites((res.data as ManagedSitesResp).sites || []))
      .catch(err => {
        console.error('[PersonMap] managed-sites failed:', err?.response?.status, err?.response?.data || err)
        setSites([])
      })
      .finally(() => setSitesLoading(false))
  }, [selectedKey])

  const openWoDrill = useCallback((row: PersonRow, ev: React.MouseEvent) => {
    setWoAnchor({ x: ev.clientX, y: ev.clientY })
    setWoOpen(true)
    setWoLoading(true)
    setWoRows([])
    // only_uncleared=false：这里看的是「该人员 30 天内全部未关闭 WO」，
    // 与表格的 open 列同口径；未清除数单独有列。
    api.get(`/gis/personnel/${encodeURIComponent(row.name_key)}/work-orders`,
      { params: { days: WINDOW_DAYS, only_uncleared: false, limit: 2000 } })
      .then(res => setWoRows(res.data?.wo_list || []))
      .catch(err => {
        console.error('[PersonMap] work-orders failed:', err?.response?.status, err?.response?.data || err)
        setWoRows([])
      })
      .finally(() => setWoLoading(false))
  }, [])

  /* ---------- 派生数据 ---------- */
  const rows = useMemo<PersonRow[]>(() => {
    const all = stats?.by_person || []
    if (!keyword.trim()) return all
    const q = keyword.toLowerCase()
    return all.filter(r => Object.values(r).some(v =>
      v != null && String(v).toLowerCase().includes(q)))
  }, [stats, keyword])

  const withCoords = useMemo(() => rows.filter(r => r.has_coords), [rows])

  const kpi = useMemo(() => {
    const sum = (k: 'open' | 'uncleared' | 'total') => rows.reduce((s, r) => s + (r[k] || 0), 0)
    return {
      peopleWithCoords: stats?.coverage.with_coords ?? 0,
      totalAll: stats?.coverage.total_all ?? 0,
      // 站点数：选中时用其站点数，否则用全量人员涉及站点去重（由 stats 的 by_county 无此口径，
      // 故这里用选中态站点数或「—」—— 不臆造数字）
      siteCount: selectedKey ? sites.length : null,
      alarmSites: selectedKey ? sites.filter(s => s.has_alarm).length : null,
      uncleared: sum('uncleared'),
      open: sum('open'),
      total: sum('total'),
    }
  }, [rows, stats, selectedKey, sites])

  /* ---------- 图表 ---------- */
  const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS

  // 按人员排行（堆叠柱：未清除 / 其余未关闭 / 已关闭）
  const personChartOption = useMemo(() => {
    const top = (stats?.top_person || []).slice(0, 10)
    if (!top.length) return {}
    const names = top.map(r => r.name.length > 18 ? r.name.slice(0, 16) + '..' : r.name)
    const uncleared = top.map(r => r.uncleared)
    const openRest = top.map(r => Math.max(0, r.open - r.uncleared))
    const closed = top.map(r => r.closed)
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const i = ps[0].dataIndex
          const r = top[i]
          return `<div style="font-weight:600;margin-bottom:4px">${r.name}</div>` +
            `${t('person.colUncleared')}: <strong>${r.uncleared}</strong><br/>` +
            `${t('person.colOpenWo')}: <strong>${r.open}</strong><br/>` +
            `${t('person.colClosedWo')}: <strong>${r.closed}</strong><br/>` +
            `${t('person.colTt')}: <strong>${r.tt_total}</strong>`
        },
      },
      legend: {
        data: [t('person.colUncleared'), t('person.openOther'), t('person.colClosedWo')],
        bottom: 0, textStyle: { fontSize: 11, color: cTextMuted },
      },
      grid: { left: 46, right: 16, top: 16, bottom: 56 },
      xAxis: {
        type: 'category', data: names,
        axisLabel: { ...axisLabel(isDark), rotate: 38, fontSize: 10 },
        axisLine: axisLine(isDark),
      },
      yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [
        {
          name: t('person.colUncleared'), type: 'bar', stack: 'wo', barMaxWidth: 26,
          data: uncleared, itemStyle: { color: WH.sev.Critical, borderRadius: [0, 0, 0, 0] },
        },
        {
          name: t('person.openOther'), type: 'bar', stack: 'wo',
          data: openRest, itemStyle: { color: cPalette[1] || '#258cff' },
        },
        {
          name: t('person.colClosedWo'), type: 'bar', stack: 'wo',
          data: closed, itemStyle: { color: isDark ? '#4b5b73' : '#94a3b8', borderRadius: [4, 4, 0, 0] },
        },
      ],
    }
  }, [stats, t, isDark, cPalette, cTextMuted])

  // 按县分布（WO 数）
  const countyChartOption = useMemo(() => {
    const entries = Object.entries(stats?.by_county || {})
      .sort((a, b) => b[1].total - a[1].total)
      .slice(0, 15)
    if (!entries.length) return {}
    return {
      tooltip: {
        ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: any[]) => {
          const i = ps[0].dataIndex
          const [, v] = entries[i]
          return `<div style="font-weight:600;margin-bottom:4px">${entries[i][0]}</div>` +
            `${t('person.colOpenWo')}: <strong>${v.open}</strong><br/>` +
            `${t('person.colClosedWo')}: <strong>${v.closed}</strong>`
        },
      },
      legend: {
        data: [t('person.colOpenWo'), t('person.colClosedWo')],
        bottom: 0, textStyle: { fontSize: 11, color: cTextMuted },
      },
      grid: { left: 46, right: 16, top: 16, bottom: 56 },
      xAxis: {
        type: 'category', data: entries.map(([k]) => k),
        axisLabel: { ...axisLabel(isDark), rotate: 38, fontSize: 10 },
        axisLine: axisLine(isDark),
      },
      yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
      series: [
        {
          name: t('person.colOpenWo'), type: 'bar', stack: 'c', barMaxWidth: 26,
          data: entries.map(([, v]) => v.open), itemStyle: { color: WH.sev.Critical },
        },
        {
          name: t('person.colClosedWo'), type: 'bar', stack: 'c',
          data: entries.map(([, v]) => v.closed),
          itemStyle: { color: isDark ? '#4b5b73' : '#94a3b8', borderRadius: [4, 4, 0, 0] },
        },
      ],
    }
  }, [stats, t, isDark, cTextMuted])

  /* ---------- 表格列 ---------- */
  const columns = useMemo(() => [
    {
      title: t('person.colName'), dataIndex: 'name', key: 'name', width: 180, fixed: 'left' as const,
      render: (v: string, r: PersonRow) => (
        <span>
          {r.has_coords && <EnvironmentOutlined style={{ color: WH.teal, marginRight: 4 }} />}
          {v}
        </span>
      ),
    },
    {
      title: t('person.colCounties'), dataIndex: 'counties', key: 'counties', width: 200,
      render: (v: string[]) => (v && v.length ? v.join(', ') : '—'),
    },
    {
      title: t('person.colUncleared'), dataIndex: 'uncleared', key: 'uncleared', width: 110,
      sorter: (a: PersonRow, b: PersonRow) => a.uncleared - b.uncleared,
      render: (v: number) => <span style={{ color: v > 0 ? WH.sev.Critical : undefined, fontWeight: v > 0 ? 700 : 400 }}>{v}</span>,
    },
    {
      title: t('person.colOpenWo'), dataIndex: 'open', key: 'open', width: 110,
      sorter: (a: PersonRow, b: PersonRow) => a.open - b.open,
    },
    {
      title: t('person.colClosedWo'), dataIndex: 'closed', key: 'closed', width: 110,
      sorter: (a: PersonRow, b: PersonRow) => a.closed - b.closed,
    },
    {
      title: t('person.colTt'), dataIndex: 'tt_total', key: 'tt_total', width: 90,
      sorter: (a: PersonRow, b: PersonRow) => a.tt_total - b.tt_total,
    },
    {
      title: t('person.colAction'), key: 'action', width: 130,
      render: (_: unknown, r: PersonRow) => (
        <Button size="small" onClick={(e) => openWoDrill(r, e)}>
          {t('person.viewWo')}
        </Button>
      ),
    },
  ], [t, openWoDrill])

  /* ---------- 导出（本页汇总口径，与下钻明细是两件事） ---------- */
  const exportAll = useCallback(() => {
    if (!rows.length) return
    const header = [
      t('person.colName'), t('person.colCounties'), t('person.hasCoords'),
      t('person.colUncleared'), t('person.colOpenWo'), t('person.colClosedWo'),
      t('person.colTt'), t('person.colRegions'),
    ]
    const data = rows.map(r => [
      r.name, r.counties.join(', '), r.has_coords ? t('common.yes') : t('common.no'),
      r.uncleared, r.open, r.closed, r.tt_total, r.managed_regions,
    ])
    void exportAoaReport({
      filename: `Person_Location_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'Person',
      title: t('person.title'),
      subtitle: t('person.exportSubtitle', { days: WINDOW_DAYS }),
      header,
      rows: data,
      columnWidths: [24, 34, 10, 12, 12, 12, 10, 40],
    })
  }, [rows, t])

  const woColumns = useMemo(() => [
    { title: t('person.colWoNo'), dataIndex: 'wo_no', key: 'wo_no', width: 150 },
    { title: t('person.colTtNo'), dataIndex: 'tt_no', key: 'tt_no', width: 150 },
    { title: t('person.colSite'), key: 'site', width: 150,
      render: (_: unknown, r: WoRow) => r.site_name || r.site_id || '—' },
    { title: t('person.colStatus'), dataIndex: 'status', key: 'status', width: 130 },
    { title: t('person.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 160 },
    { title: t('person.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 160,
      render: (v: string) => dash(v) },
    { title: t('person.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true },
  ], [t])

  /* ---------- 渲染 ---------- */
  if (mapOnly) {
    /* ⑦ mapOnly（门户 Person 页签，2026-10-19 加）：只留地图，与 Alarm / MW 两页同一形态。
       刻意**不渲染**筛选条、说明横幅、KPI、两张统计图、人员表、WO 下钻弹窗。
       · 加载 / 错误态也单独给：完整页那两套（CardBase 骨架、整块错误卡）在门户栏里
         会把 iframe 撑成大块白板；
       · 内层地图对外**不能**再套卡片（CardBase 会带来白底与内边距）；
       · 尺寸用 100vh 而不是 MAP_HEIGHT：门户给的 iframe 高度由 --maprow-h 决定，
         内层写死高度会让地图比容器矮、下方留白；
       · 人员选择仍可用（点人 / 点空白清除）；selectedKey 在 mapOnly 下只驱动高亮，
         不拉站点（见上方 useEffect 的说明）。 */
    if (loading || error) {
      return (
        <div style={{
          width: '100%', height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: WH.textDim, fontSize: '0.875rem', background: 'transparent', padding: 24, textAlign: 'center',
        }}>
          {error ? `${t('person.loadFailed')}: ${error}` : t('person.title')}
        </div>
      )
    }
    return (
      <div style={{ width: '100%', height: '100vh', margin: 0, padding: 0, overflow: 'hidden', position: 'relative' }}>
        <MapContainer center={[(3.9 + 8.75) / 2, (-11.7 + -7.3) / 2]} zoom={7.5}
          style={{ height: '100%', width: '100%' }}>
          <PersonMapView
            people={withCoords}
            loading={false}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
            sites={sites}
            sitesLoading={sitesLoading}
          />
        </MapContainer>
      </div>
    )
  }
  if (loading) {
    return (
      <div style={{ ...pageWrap }}>
        <CardBase title={t('person.title')} loading />
      </div>
    )
  }
  if (error) {
    return (
      <div style={{ ...pageWrap }}>
        <Alert type="error" showIcon message={t('person.loadFailed')} description={error} />
      </div>
    )
  }

  return (
    <div style={{ ...pageWrap, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
      {/* ① 筛选条 */}
      <div style={{ ...controlCardStyle, display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', alignItems: 'center' }}>
        <Tag color="cyan">{t('person.windowFixed', { days: WINDOW_DAYS })}</Tag>
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('person.searchPlaceholder')}
          allowClear
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{ width: 240 }}
        />
        <Button icon={<ReloadOutlined />} onClick={load}>{t('person.refresh')}</Button>
        <Button icon={<DownloadOutlined />} onClick={exportAll} disabled={!rows.length}>
          {t('common.exportExcel')}
        </Button>
        {/* ② 坐标口径说明（2026-10-19 用户要求「隐藏顶部黄条，点击显示」）。
            原为一条黄色 Alert 横幅，常驻占掉约 80px 首屏高度。现收进**筛选条内的
            一个问号图标**，悬停显示全文（用户选定 Tooltip 方式）。
            ⚠️ 这段说明**必须保留可读入口**：坐标是静态登记值、不是 GPS，
               26/136 人有坐标，人员↔WO 按姓名匹配 —— 这些不说明就会被当成实时定位
               （见 backend/routers/personnel.py 头注释）。 */}
        <Tooltip
          title={
            <div style={{ maxWidth: 420, whiteSpace: 'normal', lineHeight: 1.5 }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>{t('person.notRealtimeTitle')}</div>
              <div>{t('person.notRealtimeDesc', {
                withCoords: stats?.coverage.with_coords ?? 0,
                total: stats?.coverage.total_all ?? 0,
              })}</div>
            </div>
          }
          placement="bottomLeft"
        >
          <Button type="text" size="small" icon={<WarningOutlined />}
            aria-label={t('person.notRealtimeTitle')} />
        </Tooltip>
        {stats && (
          <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: WH.textDim }}>
            {t('person.generatedAt')}: {dayjs().format('YYYY-MM-DD HH:mm')}
          </span>
        )}
      </div>

      {/* ③④ 左右分栏（2026-10-19 用户要求，参照 ?page=realtime_alarm 的布局）：
          左 = KPI 2×2 + 两张统计图，右 = 地图。
          两列等高（行内默认 align-items:stretch），地图 card → body → 容器
          三级 flex 链吃满右列高度，底部不会在「人员清单」前留空白。 */}
      <div style={{ display: 'flex', flexDirection: 'row', gap: '0.75rem' }}>
        {/* 左列 */}
        <div style={{
          flex: '0 0 24rem', minWidth: '18rem', maxWidth: '30rem',
          display: 'flex', flexDirection: 'column', gap: '0.75rem',
        }}>
          <Row gutter={[8, 8]}>
            <Col span={12}>
              <StatCard
                title={t('person.kpiPeople')}
                value={kpi.peopleWithCoords}
                suffix={`/ ${kpi.totalAll}`}
                accentColor={WH.teal}
                prefix={<TeamOutlined />}
                subText={t('person.kpiPeopleSub')}
              />
            </Col>
            <Col span={12}>
              <StatCard
                title={t('person.kpiUncleared')}
                value={kpi.uncleared}
                accentColor={WH.sev.Critical}
                prefix={<WarningOutlined />}
                subText={t('person.kpiUnclearedSub')}
              />
            </Col>
            <Col span={12}>
              <StatCard
                title={t('person.kpiOpen')}
                value={kpi.open}
                accentColor={WH.blue}
                prefix={<FileDoneOutlined />}
                subText={t('person.kpiOpenSub', { total: kpi.total })}
              />
            </Col>
            <Col span={12}>
              <StatCard
                title={t('person.kpiSites')}
                value={selectedKey ? (kpi.siteCount ?? '—') : '—'}
                accentColor={WH.indigo}
                prefix={<EnvironmentOutlined />}
                subText={
                  selectedKey
                    ? t('person.kpiSitesSub', { alarm: kpi.alarmSites ?? 0 })
                    : t('person.kpiSitesHint')
                }
              />
            </Col>
          </Row>
          <CardBase title={t('person.chartByPerson')}>
            {personChartOption && Object.keys(personChartOption).length
              ? <ReactECharts option={personChartOption} style={{ height: 300 }} />
              : <Empty description={t('person.noData')} />}
          </CardBase>
          <CardBase title={t('person.chartByCounty')}>
            {countyChartOption && Object.keys(countyChartOption).length
              ? <ReactECharts option={countyChartOption} style={{ height: 300 }} />
              : <Empty description={t('person.noData')} />}
          </CardBase>
        </div>

        {/* 右列：地图 */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex' }}>
          <CardBase
            title={t('person.mapTitle')}
            extra={selectedKey
              ? <Button size="small" icon={<CloseCircleOutlined />} onClick={() => setSelectedKey(null)}>
                  {t('person.clearSelection')}
                </Button>
              : <span style={{ fontSize: '0.75rem', color: WH.textDim }}>{t('person.mapHint')}</span>}
            bodyStyle={{ padding: 0, display: 'flex', flex: 1, minHeight: 0 }}
            style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}
          >
            <div style={{ flex: 1, width: '100%', minHeight: MAP_HEIGHT, position: 'relative' }}>
              <MapContainer center={[(3.9 + 8.75) / 2, (-11.7 + -7.3) / 2]} zoom={7.5}
                style={{ height: '100%', width: '100%' }}>
                <PersonMapView
                  people={withCoords}
                  loading={false}
                  selectedKey={selectedKey}
                  onSelect={setSelectedKey}
                  sites={sites}
                  sitesLoading={sitesLoading}
                />
              </MapContainer>
            </div>
          </CardBase>
        </div>
      </div>

      {/* ⑥ 人员总表 */}
      <CardBase title={t('person.tableTitle')}>
        <Table<PersonRow>
          dataSource={rows}
          columns={columns}
          rowKey="name_key"
          size="small"
          loading={loading}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 15, showTotal: (n: number) => t('common.itemsTotal', { n }) }}
          rowClassName={(r) => (r.name_key === selectedKey ? 'person-row-selected' : '')}
          onRow={(r) => ({
            onClick: () => setSelectedKey(r.has_coords
              ? (r.name_key === selectedKey ? null : r.name_key)
              : null),
            style: { cursor: r.has_coords ? 'pointer' : 'default' },
          })}
        />
      </CardBase>

      {/* ⑦ WO 下钻 */}
      <DraggableClickModal
        open={woOpen}
        anchor={woAnchor}
        onClose={() => setWoOpen(false)}
        title={t('person.woTitle')}
      >
        <Table<WoRow>
          dataSource={woRows}
          columns={woColumns}
          rowKey="wo_no"
          size="small"
          loading={woLoading}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 15, showTotal: (n: number) => t('common.itemsTotal', { n }) }}
          locale={{ emptyText: <Empty description={t('person.noWo')} /> }}
        />
      </DraggableClickModal>
    </div>
  )
}
