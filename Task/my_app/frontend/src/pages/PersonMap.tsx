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
 *   ⑦ 下钻抽屉（PersonDrilldownDrawer，右侧滑出、压在卡片列上）：站点 / WO / PMT 三页签
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
import { useClearOnOutsideClick } from '../useClearOnOutsideClick'
import { useI18n, numLocale } from '../i18n'
import {
  WH, useTheme, pageWrap, controlCardStyle,
  axisLabel, axisLine, splitLine, darkTooltip, WH_COLORS, LIGHT_COLORS,
} from '../theme'
import { CardBase, StatCard } from '../components/cards'
import { exportAoaReport } from '../utils/excelReport'
import { MapContainer } from '../components/LeafletMap'
import { PersonMapView } from './personmap/PersonMapView'
import { PersonDrilldownDrawer, type PersonDrillTab } from './personmap/PersonDrilldownDrawer'
import type {
  PersonRow, PersonStats, ManagedSite, ManagedSitesResp, WoRow, PmtRow, PmtResp,
} from './personmap/types'

/** 固定时间窗口（天）。用户 2026-10-19 确认：页面固定最近 30 天，
 *  不跟随 GIS 页的时间控件（避免两页口径漂移）。 */
const WINDOW_DAYS = 30

/** 地图画布高度：与 GIS 页同量级，门户中列可放下 */
const MAP_HEIGHT = 560

/** 「PMT 取不到」的档位：徽标侧显示 `—`，页签里显示告警条。
 *
 *  **为什么必须有它**：nginx 的 SPA 兜底会把**未知 API 路径**返回成
 *  `200 + index.html`（实测 `/myapp/api/gis/personnel/x/pmt` 打在旧后端上就是这样），
 *  axios 因此**不会 reject**，`.catch` 根本不跑。只认 `available===false` 的话，
 *  后端没重启时页签会安静地显示「Open PMT (0)」—— 把「取不到」装成「确实 0 张」，
 *  正是 AGENTS.md 三.6 禁止的那种误导。所以判定写成「响应里没有 meta」。 */
const PMT_UNAVAILABLE = { available: false, truncated: false, limit: 0, overdue_count: 0 }

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

  /* ---- 下钻抽屉（站点 / WO / PMT 三页签，2026-10-21 用户要求）----
     取代原先只装 WO 明细的 DraggableClickModal：那个弹窗的列定义已搬进抽屉的
     WO 页签，不留第二份（AGENTS.md 三.10 删除优于兼容）。 */
  const [drillOpen, setDrillOpen] = useState(false)
  const [drillTab, setDrillTab] = useState<PersonDrillTab>('sites')
  const [woLoading, setWoLoading] = useState(false)
  const [woRows, setWoRows] = useState<WoRow[]>([])
  const [pmtLoading, setPmtLoading] = useState(false)
  const [pmtRows, setPmtRows] = useState<PmtRow[]>([])
  const [pmtMeta, setPmtMeta] = useState<PmtResp['meta'] | null>(null)

  /* ---------- 取数 ----------
     silent=true 供**原地自动刷新**用（App.tsx 的 AR_INPLACE_REFRESH_PAGES → 派发
     document 事件 'myapp-refresh'）。三条差异缺一不可，否则「静默」就是空话：
       · 不 setLoading(true) —— loading 会渲染盖住地图的 <Spin> 遮罩，那正是用户
         反馈「刷新太刺眼」的观感来源（重挂载式刷新还会连带重建 Leaflet 地图）；
       · 失败时**保留旧 stats**、不清 error 条 —— 拿不到新数据就继续显示上一次的结果，
         而不是把整张地图清空（AGENTS.md 三.6：取不到显示 —，但这里连"—"都不该出现，
         旧值仍是已知的正确值）；
       · 不动 selectedKey / 取景 —— 只换数据。 */
  const load = useCallback((silent = false) => {
    if (!silent) { setLoading(true); setError('') }
    api.get('/gis/personnel/stats', { params: { days: WINDOW_DAYS } })
      .then(res => setStats(res.data))
      .catch(err => {
        console.error('[PersonMap] stats failed:', err?.response?.status, err?.response?.data || err)
        if (!silent) {
          setStats(null)
          setError(err?.response?.data?.detail || err?.message || String(err))
        }
      })
      .finally(() => { if (!silent) setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  /* 自动刷新到点时**原地重拉**，不重挂载整页（画面不闪、地图不重建、不飞回全国视角）。
     只重拉 stats：县界与站点类别是慢变量、各自走 cachedGet；选中人的站点由下方
     selectedKey 的 effect 管，不该被定时器打断。 */
  useEffect(() => {
    const onInplaceRefresh = () => { load(true) }
    document.addEventListener('myapp-refresh', onInplaceRefresh)
    return () => document.removeEventListener('myapp-refresh', onInplaceRefresh)
  }, [load])

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

  /* ---------- 下钻抽屉 ---------- */
  /** 选中某人并打开抽屉。表格「查看工单」按钮走这里并直接停在 WO 页签 ——
   *  它同时是**无坐标人员**唯一的下钻入口（那些人点不到地图针，也点不了表格行，
   *  见下方 Table 的 onRow：只有 has_coords 的行可点）。 */
  const openDrill = useCallback((nameKey: string, tab: PersonDrillTab = 'sites') => {
    setSelectedKey(nameKey)
    setDrillTab(tab)
    setDrillOpen(true)
  }, [])

  /** 地图针 / 表格行选中：选中即开抽屉；`null`（再点同一个人、或点地图空白）**同时**
   *  清掉选中与抽屉 —— 只关抽屉不清选中的话，会留下「人还高亮着、抽屉没了、
   *  地图上一片空」这种自相矛盾的状态（2026-10-21 实测出现过）。 */
  const selectPerson = useCallback((nameKey: string | null) => {
    if (!nameKey) {
      setSelectedKey(null)
      setDrillOpen(false)
      return
    }
    setSelectedKey(nameKey)
    setDrillTab('sites')
    setDrillOpen(true)
  }, [])

  /* 关抽屉**不清选中**：用户关掉明细后仍要在地图上看那个人的站点圈，
     清除选中另有两条路（再点一次针 / 点地图空白 / 卡片右上角「取消选中」）。
     ⚠ 这里必须**直接**返回 `setDrillOpen(false)` 的调用结果，不能写成
        `() => () => setDrillOpen(false)` —— 多包一层后 `onClose()` 只是"返回了
        一个函数"而没执行它，抽屉右上角的 × 会完全没反应（2026-10-21 实测）。 */
  const closeDrill = useCallback(() => setDrillOpen(false), [])

  /* 抽屉打开时拉 WO + PMT 明细。
     刻意挂在 `drillOpen` 上而不是 `selectedKey`：`?maponly=1` 的门户页签里点人
     只为高亮和画站点，不该顺手多发两个请求（两端各要扫一次 eflow_wo / eflow_pm）。 */
  useEffect(() => {
    if (!drillOpen || !selectedKey) return
    const q = encodeURIComponent(selectedKey)
    let alive = true

    setWoLoading(true)
    // only_uncleared=false：看「该人员 30 天内全部未关闭 WO」，与徽标/表格的 open 列同口径
    api.get(`/gis/personnel/${q}/work-orders`,
      { params: { days: WINDOW_DAYS, only_uncleared: false, limit: 2000 } })
      .then(res => { if (alive) setWoRows(res.data?.wo_list || []) })
      .catch(err => {
        console.error('[PersonMap] work-orders failed:', err?.response?.status, err?.response?.data || err)
        if (alive) setWoRows([])
      })
      .finally(() => { if (alive) setWoLoading(false) })

    // **不传 days** —— PMT 的徽标计数本来就不套时间窗口（后端 _pmt_open_index），
    // 这里传了就会「徽标 298、页签 132」，正是 AGENTS.md 三.1b 禁止的那类漂移。
    setPmtLoading(true)
    api.get(`/gis/personnel/${q}/pmt`)
      .then(res => {
        if (!alive) return
        const meta = res.data?.meta
        if (!meta) {
          // 200 + 没有 meta = SPA 兜底把未知路径回成了 index.html（后端还没这个端点）
          console.error('[PersonMap] pmt: 响应里没有 meta，按「取不到」处理')
          setPmtRows([])
          setPmtMeta(PMT_UNAVAILABLE)
          return
        }
        setPmtRows(Array.isArray(res.data.pmt_list) ? res.data.pmt_list : [])
        setPmtMeta({
          available: meta.available !== false,
          truncated: !!meta.truncated,
          limit: typeof meta.limit === 'number' ? meta.limit : 0,
          overdue_count: meta.overdue_count || 0,
        })
      })
      .catch(err => {
        console.error('[PersonMap] pmt failed:', err?.response?.status, err?.response?.data || err)
        if (alive) { setPmtRows([]); setPmtMeta(PMT_UNAVAILABLE) }
      })
      .finally(() => { if (alive) setPmtLoading(false) })

    return () => { alive = false }
  }, [drillOpen, selectedKey])

  /* 点「其他任意地方」取消选中（2026-10-21 用户要求：此前只有点在地图上才取消，
     点右侧卡片 / 下方表格 / 筛选条 / 页面背景都取消不掉）。
     地图内部的取消仍归 `PersonMapView` 的 `map.on('click')`（它要区分点人/点站点/点空白），
     这里补的是**地图之外**；四类必须放行的点击见 `useClearOnOutsideClick.ts`。 */
  const clearSelection = useCallback(() => {
    setSelectedKey(null)
    setDrillOpen(false)
  }, [])
  useClearOnOutsideClick(!!selectedKey, clearSelection)

  /* ---------- 派生数据 ---------- */
  const rows = useMemo<PersonRow[]>(() => {
    const all = stats?.by_person || []
    if (!keyword.trim()) return all
    const q = keyword.toLowerCase()
    return all.filter(r => Object.values(r).some(v =>
      v != null && String(v).toLowerCase().includes(q)))
  }, [stats, keyword])

  const withCoords = useMemo(() => rows.filter(r => r.has_coords), [rows])

  /* 抽屉标题要的那个人。从 **未过滤** 的 `stats.by_person` 里找，不用 `rows`
     （rows 被搜索框过滤过）—— 否则搜出一个人、点开抽屉、再把搜索框清空，
     标题会连带变成「—」。也不能用 `withCoords`：无坐标的人同样要能下钻。 */
  const selectedPerson = useMemo(
    () => (selectedKey
      ? (stats?.by_person || []).find(r => r.name_key === selectedKey) || null
      : null),
    [stats, selectedKey],
  )

  const kpi = useMemo(() => {
    const sum = (k: 'open' | 'uncleared' | 'total') => rows.reduce((s, r) => s + (r[k] || 0), 0)
    return {
      // KPI 走 FE 人群口径（`person.isfe = Yes`）：分母 = FE 人数，
      // 分子 = 其中经纬度有效的人数。2026-10-29 用户确认。
      // 不用 with_coords/total_all —— 那一对是全表口径（地图针数/表行数），
      // 拿来当分母会把「有坐标但不属于 FE 的 3 人」算进分子，比率不成立。
      peopleWithCoords: stats?.coverage.fe_with_coords ?? 0,
      totalAll: stats?.coverage.fe_total ?? 0,
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
        <Button size="small" onClick={() => openDrill(r.name_key, 'wo')}>
          {t('person.viewWo')}
        </Button>
      ),
    },
  ], [t, openDrill])

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
          className="person-map-canvas" style={{ height: '100%', width: '100%' }}>
          <PersonMapView
            people={withCoords}
            allPeople={stats?.by_person || []}
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
        {/* 必须包一层：`onClick={load}` 会把 MouseEvent 当成 `silent` 传进去
            （事件对象恒为真值）→ 手动刷新反而不再显示 loading、失败也不弹错误条。 */}
        <Button icon={<ReloadOutlined />} onClick={() => load()}>{t('person.refresh')}</Button>
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
              {/* 徽标第三项 PMT 的口径（2026-10-21 加）。必须说：它与前两项**不同窗**
                  （不跟 30 天），且组池单不计任何个人 —— 否则用户拿各人徽标求和
                  去对全量必然对不上（同页 RCA 那次「31 vs 3」是同一类质疑）。 */}
              {stats?.pmt && stats.pmt.open_total > 0 && (
                <div style={{ marginTop: 6 }}>
                  {t('person.pmtCaliberNote', {
                    groupPool: stats.pmt.group_pool,
                    openTotal: stats.pmt.open_total,
                  })}
                </div>
              )}
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

      {/* ③④ 左右分栏：左 = 地图，右 = KPI 2×2 + 两张统计图。
          （2026-10-19 参照 ?page=realtime_alarm 做成左右分栏，
            2026-10-21 用户要求把地图挪到左边、卡片列挪到右边。）
          两列等高（行内默认 align-items:stretch），地图 card → body → 容器
          三级 flex 链吃满左列高度，底部不会在「人员清单」前留空白。

          ⚠️ `flexShrink: 0` 不可去掉（2026-10-24 实测）：本页根节点是
          `display:flex/column`（见 pageWrap），本行与下方人员表都是它的 flex 子项，
          子项默认 `flex-shrink:1` 且 `min-height:auto`。embed 模式（门户 iframe，
          `?embed=1&mwembed=1`）下 `#main-content` 高度被钉在视口高度（800px），
          而本行内容（地图 minHeight 560 + 右列 KPI/图表）实测 1122px ——
          超出的 322px 只能由可收缩的子项承担。人员表卡片是普通 antd Card，
          没有内在最小高度、且 `.ant-card` 自带 `overflow:hidden`，于是被压成
          **2px**（实测 1591×2px），整个「人员清单」被裁成看不见。
          这与 theme.ts::controlCardStyle 里记录的是同一个失效模式（那边是
          筛选条被压成 2px），修法也一致：给会被压缩的块显式 `flexShrink: 0`，
          让它保持内容高度、由外层 `overflow:auto` 滚动。 */}
      <div style={{ display: 'flex', flexDirection: 'row', gap: '0.75rem', flexShrink: 0 }}>
        {/* 左列：地图 */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex' }}>
          <CardBase
            title={t('person.mapTitle')}
            extra={selectedKey
              ? <Button size="small" icon={<CloseCircleOutlined />} onClick={() => selectPerson(null)}>
                  {t('person.clearSelection')}
                </Button>
              : <span style={{ fontSize: '0.75rem', color: WH.textDim }}>{t('person.mapHint')}</span>}
            bodyStyle={{ padding: 0, display: 'flex', flex: 1, minHeight: 0 }}
            style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}
          >
            <div style={{ flex: 1, width: '100%', minHeight: MAP_HEIGHT, position: 'relative' }}>
              {/* `person-map-canvas`：给本页地图容器一个专属类，供 index.css
                  把「悬停放大」限定在本页（GIS 页的人员图层另有自己的悬停实现）。 */}
              <MapContainer center={[(3.9 + 8.75) / 2, (-11.7 + -7.3) / 2]} zoom={7.5}
                className="person-map-canvas" style={{ height: '100%', width: '100%' }}>
                <PersonMapView
                  people={withCoords}
                  allPeople={stats?.by_person || []}
                  loading={false}
                  selectedKey={selectedKey}
                  onSelect={selectPerson}
                  sites={sites}
                  sitesLoading={sitesLoading}
                />
              </MapContainer>
            </div>
          </CardBase>
        </div>

        {/* 右列：KPI + 统计图 */}
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
      </div>

      {/* ⑥ 人员总表
          `flexShrink: 0` 见上方分栏处的说明：不加这张卡片会被 flex 压成 2px。 */}
      <CardBase title={t('person.tableTitle')} style={{ flexShrink: 0 }}>
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
            /* 行点击只对**有坐标**的人生效（与地图选中同一套 toggle 语义）。
               无坐标的人不在地图上，行点击不做选中；他们的下钻入口是「查看工单」
               按钮 —— 那个按钮对所有人都可用。 */
            onClick: () => {
              if (!r.has_coords) return
              selectPerson(r.name_key === selectedKey ? null : r.name_key)
            },
            style: { cursor: r.has_coords ? 'pointer' : 'default' },
          })}
        />
      </CardBase>

      {/* ⑦ 下钻抽屉（右侧滑出，压在右列卡片上、不遮地图；站点 / WO / PMT 三页签） */}
      <PersonDrilldownDrawer
        open={drillOpen}
        onClose={closeDrill}
        person={selectedPerson}
        activeTab={drillTab}
        onTabChange={setDrillTab}
        sites={sites}
        sitesLoading={sitesLoading}
        woRows={woRows}
        woLoading={woLoading}
        pmtRows={pmtRows}
        pmtLoading={pmtLoading}
        pmtMeta={pmtMeta}
      />
    </div>
  )
}
