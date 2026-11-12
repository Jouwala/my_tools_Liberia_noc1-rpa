/* ============================================================================
 * UME 四层拓扑（?page=ipranTopo&layer=ipran|ipcore|metro|dwdm）
 * ============================================================================
 * 数据源：UME（ZTE NetNumen）四张逻辑拓扑层，端点序列相同、只有 lid 与口径不同。
 * 8 次上游调用由后端 services/ipran_topo 聚合成一次响应并**按层**缓存 120s
 * （层清单与口径见后端 layers.py、前端 ipranTopo/layerDefs.ts）。
 * 本页只负责「怎么画得好看、点得动」：
 *
 *   布局 3 种（力导向默认且带主归属聚类 / 地理 / 分层），原力导向留在 layoutForceClassic。
 *   着色 3 种：按层级（默认）/ 按在线状态 / 按最高告警级 —— 告警色**不是默认**：
 *     实测 80% 网元都带紧急告警，按告警级填色会全红、失去区分度（后端 warnings 也会说明）。
 *   告警只做节点右上角小红点；带宽只做线宽；断链红色虚线。颜色全部服务于故障态。
 *
 * 交互：点节点聚焦（其余变暗、只显示一跳邻居），详情从右侧滑出；
 * 右栏（约 25%，与微波实时页同一套分栏）从上到下是统计卡、紧急告警榜，
 * 两者同宽；左栏画布吃掉工具条之下剩余的全部高度。
 * 点边看物理链路明细；
 * 统计卡点开是「构成这个数的那些行」（TopoDrillModal），与卡上数字同一份数据。
 * 切页签会清空旧层数据与聚焦态，并用请求序号丢弃「切走后迟到的旧层响应」；
 * 自动刷新：已登记 AR_INPLACE_REFRESH_PAGES，监听 myapp-refresh 只静默重取当前层。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react'
import { Alert, Drawer, Empty, Spin } from 'antd'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { WH } from '../theme'
import { CardBase } from '../components/cards'
import { ExplainIcon, ExplainPopover } from '../components/MetricExplain'
import CalcChainNote, { type CalcChainSection } from '../components/CalcChainNote'
import { exportReport } from '../utils/excelReport'
import { formatDateTime } from '../datetime'
import { getIpranTopoGraph } from '../api'
import TopoCanvas from './ipranTopo/TopoCanvas'
import TopoDrillModal, { type DrillKind } from './ipranTopo/TopoDrillModal'
import TopoGeoMap from './ipranTopo/TopoGeoMap'
import TopologyControls, { type StatusFilter, type TierFilter } from './ipranTopo/TopologyControls'
import TopologyDetails from './ipranTopo/TopologyDetails'
import TopologyLegend from './ipranTopo/TopologyLegend'
import TopologyMetrics from './ipranTopo/TopologyMetrics'
import { buildIndex } from './ipranTopo/layouts'
import { cachedLayout } from './ipranTopo/layoutCache'
import { analyzeGraph } from './ipranTopo/faultAnalysis'
import { LAYER_LABEL_KEY, calcSectionKeys, explainKeys, isLayerKey } from './ipranTopo/layerDefs'
import type { ColorMode, LayerKey, LayoutKey, Tier, TopoNode, TopoResp } from './ipranTopo/types'

type Drill = { kind: DrillKind; anchor: { x: number; y: number } }
type ViewCmd = { seq: number; kind: 'in' | 'out' | 'fit' }

/** 门户 GIS Map 的 IP 页签（`?maponly=1`）只留网络拓扑画布。
 *  与 Person 页的 maponly 同一约定：embed 只藏外壳，这个参数才藏页面自己的
 *  工具条 / KPI / 告警榜。Open Link 会剥掉它，新窗口仍是完整页。 */
function readMapOnlyMode(): boolean {
  try {
    const sp = new URLSearchParams(window.location.search)
    return sp.get('maponly') === '1' || sp.get('maponly') === 'true'
  } catch { return false }
}

export default function IpranTopo() {
  const { t } = useI18n()

  /* 层：URL 的 &layer= 可深链到单层，非法值回落到 ipran（与后端白名单一致） */
  const [mapOnly] = useState(readMapOnlyMode)
  const [layer, setLayer] = useState<LayerKey>(() => {
    const v = new URLSearchParams(window.location.search).get('layer')
    return isLayerKey(v) ? v : 'ipran'
  })
  const [resp, setResp] = useState<TopoResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [layoutKey, setLayoutKey] = useState<LayoutKey>('force')
  const [colorMode, setColorMode] = useState<ColorMode>('tier')
  const [showAllLabels, setShowAllLabels] = useState(false)
  const [foldParallel, setFoldParallel] = useState(true)
  const [focus, setFocus] = useState(-1)
  const [selectedEdge, setSelectedEdge] = useState(-1)
  const [query, setQuery] = useState('')
  const [tierFilter, setTierFilter] = useState<TierFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [viewCmd, setViewCmd] = useState<ViewCmd | null>(null)
  const [drill, setDrill] = useState<Drill | null>(null)
  // 快速连切页签时先发的请求可能后返回，只认最后一次请求的响应
  const reqSeq = useRef(0)

  /* 取数：silent 供原地自动刷新（不清 loading、失败保留旧数据），force 绕过后端 120s 缓存 */
  const load = useCallback(async (opts?: { silent?: boolean; force?: boolean }) => {
    const seq = ++reqSeq.current
    const silent = !!opts?.silent
    if (!silent) { setLoading(true); setError('') }
    try {
      const r = await getIpranTopoGraph(layer, opts?.force ? 1 : 0)
      if (seq !== reqSeq.current) return
      setResp(r.data as TopoResp)
      if (!silent) setError('')
    } catch (e: any) {
      if (seq !== reqSeq.current) return
      setError(e?.message || String(e))
    } finally {
      if (seq === reqSeq.current && !silent) setLoading(false)
    }
  }, [layer])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const onInplaceRefresh = () => { void load({ silent: true }) }
    document.addEventListener('myapp-refresh', onInplaceRefresh)
    return () => document.removeEventListener('myapp-refresh', onInplaceRefresh)
  }, [load])
  /* 地址栏保留当前层，便于分享单层链接；replaceState 不产生多余历史，App.tsx 的
     page 同步用 set('page')，不会丢掉 layer 参数 */
  useEffect(() => {
    const url = new URL(window.location.href)
    url.searchParams.set('layer', layer)
    window.history.replaceState(window.history.state, '', url)
  }, [layer])

  const changeLayer = (k: LayerKey) => {
    if (k === layer) return
    // 旧层数据/聚焦/下钻不能带到新层：先清空，load 因 layer 变化会自动取新层
    setLayer(k)
    setResp(null)
    setError('')
    setLoading(true)
    setFocus(-1)
    setSelectedEdge(-1)
    setDrill(null)
  }
  const explain = explainKeys(layer)

  const nodes = useMemo(() => resp?.nodes ?? [], [resp])
  const edges = useMemo(() => resp?.edges ?? [], [resp])
  const idx = useMemo(() => buildIndex(nodes, edges), [nodes, edges])
  const layout = useMemo(
    () => cachedLayout(layoutKey, nodes, idx, edges),
    [layoutKey, nodes, idx, edges],
  )
  const focusSafe = focus >= 0 && focus < nodes.length ? focus : -1

  /* ---- 统计（卡片与下钻弹窗取同一份数组，口径不会对不上） ---- */
  const meta = resp?.meta
  const ne = meta?.ne ?? 0
  const ext = meta?.ext ?? 0
  const rawLinks = meta?.rawLinks ?? 0
  const folded = meta?.foldedLinks ?? 0
  const critNe = meta?.critNe ?? 0
  const critPct = ne ? Math.round((critNe * 100) / ne) : 0
  const downNe = useMemo(() => nodes.filter((v) => v.tier > 0 && !v.up).length, [nodes])

  /* 告警按页面已知的口径就地重建成中英双语；后端未知前缀（如 load_failed）原样显示，不吞。
     取数降级（stale）留在工具条下，用户正在看的不是本次结果。
     告警饱和 / 缺坐标 / 近似匹配是说明，不是本次取数失败，放到页底，避免把画布顶下去。 */
  const { topWarns, footWarns } = useMemo(() => {
    const top: string[] = []
    const foot: string[] = []
    if (!meta) return { topWarns: top, footWarns: foot }
    if (meta.stale) top.push(t('ipranTopo.warn.stale'))
    if (ne && critNe / ne > 0.5) {
      foot.push(t('ipranTopo.warn.alarmSaturated', { crit: critNe, ne, pct: critPct }))
    }
    const miss = meta.geo?.miss ?? 0
    if (miss) foot.push(t('ipranTopo.warn.geoMiss', { n: miss }))
    const fuzzy = meta.geo?.fuzzy ?? 0
    if (fuzzy) foot.push(t('ipranTopo.warn.geoFuzzy', { n: fuzzy }))
    for (const w of meta.warnings || []) {
      if (!/^(alarm_saturated|geo_miss|geo_fuzzy|upstream_unreachable):/.test(w)) foot.push(w)
    }
    return { topWarns: top, footWarns: foot }
  }, [meta, ne, critNe, critPct, t])

  const tierName = (tier: Tier) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }

  const filtering = tierFilter !== 'all' || statusFilter !== 'all' || query.trim().length > 0
  const dimmed = useMemo(() => {
    if (!filtering) return null
    const q = query.trim().toLowerCase()
    return nodes.map((v) => {
      if (tierFilter !== 'all' && v.tier !== tierFilter) return true
      if (statusFilter === 'up' && !v.up) return true
      if (statusFilter === 'down' && !!v.up) return true
      if (statusFilter === 'alarm' && !(v.crit || v.major || v.minor || v.warn)) return true
      if (q && !`${v.name} ${v.site} ${v.ip}`.toLowerCase().includes(q)) return true
      return false
    })
  }, [filtering, nodes, tierFilter, statusFilter, query])

  const fault = useMemo(() => analyzeGraph(idx, nodes, edges), [idx, nodes, edges])
  const showImpact = focusSafe >= 0 && (nodes[focusSafe]?.up === 0
    || fault.candidates.some((c) => c.index === focusSafe))
  const impacted = useMemo(() => {
    if (!showImpact || focusSafe < 0) return null
    const downStream = new Set<number>()
    const tier = nodes[focusSafe].tier
    const seen = new Set<number>([focusSafe])
    const queue = [focusSafe]
    const isolated = new Set(fault.isolated)
    for (let head = 0; head < queue.length; head++) {
      for (const a of idx.adj[queue[head]] || []) {
        const nb = nodes[a.n]
        if (!nb || nb.tier <= tier || seen.has(a.n)) continue
        seen.add(a.n)
        if (isolated.has(a.n) || nb.up === 0) {
          downStream.add(a.n)
          queue.push(a.n)
        }
      }
    }
    return downStream
  }, [showImpact, focusSafe, nodes, idx, fault])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      setFocus(-1)
      setSelectedEdge(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const locate = () => {
    const q = query.trim().toLowerCase()
    if (!q) return
    const hit = nodes.findIndex((v) => `${v.name} ${v.site} ${v.ip}`.toLowerCase().includes(q))
    if (hit >= 0) { setFocus(hit); setSelectedEdge(-1) }
  }

  const bumpView = (kind: ViewCmd['kind']) => setViewCmd((prev) => ({ seq: (prev?.seq ?? 0) + 1, kind }))

  /* ---- 告警 Top 10：点网元名聚焦到画布 ---- */
  const topRows = useMemo(
    () => nodes
      .filter((v) => v.tier > 0 && (v.crit > 0 || v.major > 0))
      .sort((a, b) => b.crit - a.crit || b.major - a.major)
      .slice(0, 10),
    [nodes],
  )

  /* 右栏大约 340px，七列表格会把「网元」列压成 0 宽，名字逐字竖排，一行能到 600px。
     这里跟微波实时页的风险榜一样：固定 3rem 一行，名字省略，紧急数贴右。
     层级 / 站点 / 其余告警级放在第二行，悬停数字仍是原来的分项说明。 */

  const inLayer = useMemo(() => nodes.filter((v) => v.tier > 0).length, [nodes])

  /* ---- 导出：网元 + 链路两张 sheet（统一走 excelReport） ---- */
  const doExport = useCallback(() => {
    if (!resp) return
    // 导出标题/文件名带层名：四层表格落到磁盘后还能分清是哪一层
    const exportTitle = `${t('ipranTopo.export.title')} · ${t(LAYER_LABEL_KEY[layer])}`
    const nodeRows = resp.nodes.map((v) => [
      v.name, tierName(v.tier), v.site, v.model, v.ip,
      v.up ? t('ipranTopo.status.up') : t('ipranTopo.status.down'),
      v.crit, v.major, v.minor, v.warn, v.deg,
      v.lat ?? '', v.lon ?? '', v.geo,
    ])
    const linkRows = resp.edges.map((e) => [
      resp.nodes[idx.byId[e.s]]?.name ?? e.s,
      resp.nodes[idx.byId[e.t]]?.name ?? e.t,
      e.n, e.gb ?? '', e.down, e.crit, e.major, e.ports.join(' | '),
    ])
    void exportReport([
      {
        name: t('ipranTopo.export.nodes'), title: exportTitle,
        header: [
          t('ipranTopo.col.name'), t('ipranTopo.col.tier'), t('ipranTopo.col.site'), t('ipranTopo.col.model'),
          t('ipranTopo.col.ip'), t('ipranTopo.col.status'), t('ipranTopo.col.crit'), t('ipranTopo.col.major'),
          t('ipranTopo.col.minor'), t('ipranTopo.col.warn'), t('ipranTopo.col.deg'),
          t('ipranTopo.col.lat'), t('ipranTopo.col.lon'), t('ipranTopo.col.geo'),
        ],
        rows: nodeRows, numericCols: [6, 7, 8, 9, 10],
      },
      {
        name: t('ipranTopo.export.links'), title: exportTitle,
        header: [
          t('ipranTopo.col.peerA'), t('ipranTopo.col.peerB'), t('ipranTopo.col.physLinks'),
          t('ipranTopo.col.gb'), t('ipranTopo.col.downLinks'), t('ipranTopo.col.crit'),
          t('ipranTopo.col.major'), t('ipranTopo.col.ports'),
        ],
        rows: linkRows, numericCols: [2, 3, 4, 5, 6], autoWidth: false,
        columnWidths: [28, 28, 12, 12, 12, 10, 10, 60],
      },
    ], `UME_Topo_${layer}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [resp, idx, t, layer])

  /* 口径说明按层切换：ipran 用实测版，其余三层用通用版（不套用 93/167 这类实测数字） */
  const calcSections = useMemo<CalcChainSection[]>(
    () => calcSectionKeys(layer).map((s) => ({
      title: t(s.title), lines: s.lines.map((k) => t(k)),
    })),
    [layer, t],
  )

  const openDrill = (kind: DrillKind) => (e: ReactMouseEvent<HTMLDivElement>) =>
    setDrill({ kind, anchor: { x: e.clientX, y: e.clientY } })

  /* 门户 IP 页签：只留网络拓扑。工具条、KPI、口径、告警榜都不画。
     缩放钮留在画布上，因为门户默认锁住滚轮（跟 Person 的 Leaflet +/- 一样）。
     点节点/链路仍开右侧详情，那是画布自己的交互，不是页面上的另一块。 */
  if (mapOnly) {
    const zoomBtn: CSSProperties = {
      width: 30, height: 30, padding: 0, cursor: 'pointer',
      border: `1px solid ${WH.cardBorder}`, borderRadius: 4,
      background: WH.cardBg, color: WH.text, fontSize: 16, lineHeight: '28px',
    }
    return (
      <div style={{ flex: '1 1 auto', height: '100%', minHeight: 0, position: 'relative', overflow: 'hidden' }}>
        {error && <Alert type="error" showIcon message={error} style={{ margin: 8 }} />}
        {meta?.stale && !error && (
          <Alert type="warning" showIcon message={t('ipranTopo.warn.stale')} style={{ margin: 8 }} />
        )}
        {loading && !resp ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
        ) : nodes.length === 0 ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty description={t('ipranTopo.empty')} />
          </div>
        ) : (
          <TopoCanvas
            fill
            nodes={nodes} edges={edges} idx={idx} layout={layout}
            colorMode={colorMode} focus={focusSafe}
            showAllLabels={showAllLabels} foldParallel={foldParallel}
            dimmed={dimmed} impacted={impacted} selectedEdge={selectedEdge}
            viewCmd={viewCmd} resetKey={`${layer}:${layoutKey}`}
            markGeo={layoutKey === 'geo'}
            onToggleFocus={(i) => { setFocus((prev) => (prev === i ? -1 : i)); setSelectedEdge(-1) }}
            onSelectEdge={(i) => { setSelectedEdge(i); setFocus(-1) }}
            onBackgroundClick={() => { setFocus(-1); setSelectedEdge(-1) }}
          />
        )}
        <div style={{ position: 'absolute', left: 12, right: 56, bottom: 8, zIndex: 2, pointerEvents: 'none' }}>
          <TopologyLegend colorMode={colorMode} tierCounts={meta?.tierCounts} />
        </div>
        <div style={{ position: 'absolute', top: 12, right: 12, display: 'flex', flexDirection: 'column', gap: 4, zIndex: 2 }}>
          <button type="button" style={zoomBtn} title={t('ipranTopo.btn.zoomIn')} onClick={() => bumpView('in')}>+</button>
          <button type="button" style={zoomBtn} title={t('ipranTopo.btn.zoomOut')} onClick={() => bumpView('out')}>−</button>
          <button type="button" style={zoomBtn} title={t('ipranTopo.btn.fit')} onClick={() => bumpView('fit')}>⛶</button>
        </div>
        <Drawer
          placement="right"
          width="min(95vw, 45rem)"
          open={focusSafe >= 0 || selectedEdge >= 0}
          onClose={() => { setFocus(-1); setSelectedEdge(-1) }}
          title={focusSafe >= 0
            ? t('ipranTopo.focus.title', { name: nodes[focusSafe]?.name ?? '' })
            : t('ipranTopo.detail.linkTitle')}
          destroyOnClose
        >
          {(focusSafe >= 0 || selectedEdge >= 0) && (
            <TopologyDetails
              nodes={nodes} edges={edges} idx={idx} fault={fault}
              focus={focusSafe} selectedEdge={selectedEdge}
              onFocus={(i) => { setFocus(i); setSelectedEdge(-1) }}
            />
          )}
        </Drawer>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)',
      /* flex:1 认领内容区剩余高度，下面的画布行才能把「工具条之下」吃满。
         父级 #main-content 是 flex 列，不写这个只按内容高度排，地图底下会空一截。 */
      flex: 1, minHeight: 0,
    }}>

      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <TopologyControls
        layer={layer} onLayer={changeLayer}
        layoutKey={layoutKey} onLayout={setLayoutKey}
        colorMode={colorMode} onColor={setColorMode}
        showAllLabels={showAllLabels} onAllLabels={setShowAllLabels}
        foldParallel={foldParallel} onFold={setFoldParallel}
        loading={loading} onRefresh={() => void load({ force: true })}
        onExport={doExport} canExport={!!resp?.nodes.length}
        metaLine={meta ? t('ipranTopo.meta.line', {
          sec: (meta.elapsedSec ?? 0).toFixed(2),
          at: formatDateTime(meta.fetchedAt),
          cached: meta.cached ? t('ipranTopo.meta.cached') : '',
        }) : null}
        query={query} onQuery={setQuery} onLocate={locate}
        tierFilter={tierFilter} onTier={setTierFilter}
        statusFilter={statusFilter} onStatus={setStatusFilter}
        onZoomIn={() => bumpView('in')} onZoomOut={() => bumpView('out')} onFit={() => bumpView('fit')}
      />

      {/* 取数失败 / 降级留在工具条下：用户正在看的数可能不是本次结果。 */}
      {error && <Alert type="error" showIcon message={error} />}
      {topWarns.length > 0 && (
        <Alert type="warning" showIcon message={
          <div>{topWarns.map((w, i) => <div key={i}>{w}</div>)}</div>
        } />
      )}
      </div>

      {/* ⑤ 画布左 75% + 右栏 25%。右栏先排统计卡，再排告警榜，两块同宽。
          画布行 flex:1 吃掉工具条之下、页底说明之上的高度。
          窄屏（两栏 basis 加起来放不下）自动换行，右栏落到画布下面。 */}
      <div style={{
        display: 'flex', gap: 12, alignItems: 'stretch', flexWrap: 'wrap',
        flex: 1, minHeight: 0,
      }}>
        <div style={{
          flex: '3 1 640px', minWidth: 0, minHeight: 0,
          display: 'flex', flexDirection: 'column',
        }}>
          <CardBase title={t('ipranTopo.canvas.title')}
            extra={<ExplainIcon text={t('ipranTopo.canvas.hint')} placement="bottomLeft" icon="question" />}
            style={{
              flex: 1, minHeight: 360, minWidth: 0,
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}
            bodyStyle={{
              flex: '1 1 0%', minHeight: 0, height: 'auto',
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}>
            {loading && !resp ? <Spin /> : nodes.length === 0 ? <Empty description={t('ipranTopo.empty')} /> : (
              <>
                {/* 绝对定位铺满卡片剩余高度。不能靠 svg 的 height:100%：
                    flex 分到的高度对百分比是不确定的，画布会塌成 0。 */}
                <div style={{ flex: '1 1 0%', minHeight: 0, position: 'relative' }}>
                  <div style={{ position: 'absolute', inset: 0 }}>
                    <TopoCanvas
                      fill
                      nodes={nodes} edges={edges} idx={idx} layout={layout}
                      colorMode={colorMode} focus={focusSafe}
                      showAllLabels={showAllLabels} foldParallel={foldParallel}
                      dimmed={dimmed} impacted={impacted} selectedEdge={selectedEdge}
                      markGeo={layoutKey === 'geo'}
                      viewCmd={viewCmd} resetKey={`${layer}:${layoutKey}`}
                      onToggleFocus={(i) => { setFocus((prev) => (prev === i ? -1 : i)); setSelectedEdge(-1) }}
                      onSelectEdge={(i) => { setSelectedEdge(i); setFocus(-1) }}
                      onBackgroundClick={() => { setFocus(-1); setSelectedEdge(-1) }}
                    />
                  </div>
                </div>
                <div style={{ flexShrink: 0 }}>
                  <TopologyLegend colorMode={colorMode} tierCounts={meta?.tierCounts} />
                </div>
              </>
            )}
          </CardBase>
          {layoutKey === 'geo' && nodes.length > 0 && (
            <div style={{ marginTop: 12, flexShrink: 0 }}>
              <TopoGeoMap nodes={nodes} impacted={impacted}
                onFocus={(i) => { setFocus(i); setSelectedEdge(-1) }} />
            </div>
          )}
        </div>
        <div style={{
          flex: '1 1 260px', minWidth: 260, maxWidth: '100%',
          minHeight: 0, alignSelf: 'stretch', overflow: 'hidden',
          display: 'flex', flexDirection: 'column', gap: 12,
        }}>
          <TopologyMetrics
            ne={ne} ext={ext} folded={folded} rawLinks={rawLinks}
            downNe={downNe} critNe={critNe} critPct={critPct}
            inLayer={inLayer} edges={edges} explain={explain} onDrill={openDrill}
          />
          {/* flex:1 把告警榜接到统计卡下面，两块加起来正好等于左侧地图的高度。
              名单超出时只在这张卡里滚动，不把地图顶高。 */}
          <CardBase
            style={{
              flex: '1 1 0%', minHeight: 0,
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}
            bodyStyle={{ flex: '1 1 0%', minHeight: 0, height: 'auto', overflow: 'auto' }}
            title={
            <span style={{ whiteSpace: 'normal', lineHeight: 1.35 }}>{t('ipranTopo.alarmTitle')}</span>
          }>
            {topRows.length
              ? (
                <>
                  <div style={{ fontSize: 12, color: WH.textDim, marginBottom: 6 }}>
                    {t('ipranTopo.alarmHint')}
                  </div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    fontSize: 12, color: WH.textDim, padding: '0 4px 4px',
                  }}>
                    <span style={{ flex: 1, minWidth: 0 }}>{t('ipranTopo.col.name')}</span>
                    <span>{t('ipranTopo.col.crit')} <ExplainIcon text={t('ipranTopo.critExplain')} /></span>
                  </div>
                  {topRows.map((r) => {
                    const sub = `${tierName(r.tier)} · ${r.site || '—'} · ${t('ipranTopo.col.major')} ${r.major} · ${t('ipranTopo.col.minor')} ${r.minor} · ${t('ipranTopo.col.warn')} ${r.warn}`
                    return (
                      <div key={r.id} style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        height: '3rem', padding: '0 4px', overflow: 'hidden',
                        borderTop: 'var(--wh-card-border)',
                      }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <a
                            title={r.name}
                            onClick={() => setFocus(idx.byId[r.id])}
                            style={{
                              display: 'block', fontWeight: 600, fontSize: 12, lineHeight: '1.1rem',
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                            }}
                          >{r.name}</a>
                          <div title={sub} style={{
                            color: WH.textDim, fontSize: 11, lineHeight: '1rem',
                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          }}>{sub}</div>
                        </div>
                        <ExplainPopover text={t('ipranTopo.critTip', {
                          name: r.name, crit: r.crit, major: r.major, minor: r.minor, warn: r.warn,
                        })}>
                          <b style={{
                            fontVariantNumeric: 'tabular-nums', fontSize: 16, lineHeight: 1,
                            color: r.crit > 0 ? WH.sev.Critical : WH.textMuted,
                          }}>{r.crit}</b>
                        </ExplainPopover>
                      </div>
                    )
                  })}
                </>
              )
              : <Empty description={t('ipranTopo.alarmEmpty')} />}
          </CardBase>
        </div>
      </div>

      {/* 缺坐标、近似匹配、告警饱和和口径说明都是解释，不是本次取数失败。
          放在画布下面，避免占掉工具条和地图之间的高度。内容仍常驻，不收进折叠区。 */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {footWarns.length > 0 && (
          <Alert type="warning" showIcon style={{ padding: '4px 12px' }} message={
            <div style={{ fontSize: 12, lineHeight: 1.45 }}>
              {footWarns.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          } />
        )}
        <CalcChainNote title={t('ipranTopo.calc.title')} sections={calcSections} />
      </div>

      {/* 点节点 / 点链路后从右侧滑出，不占分栏。宽度与微波实时页、GIS 下钻抽屉一致。 */}
      <Drawer
        placement="right"
        width="min(95vw, 45rem)"
        open={focusSafe >= 0 || selectedEdge >= 0}
        onClose={() => { setFocus(-1); setSelectedEdge(-1) }}
        title={focusSafe >= 0
          ? t('ipranTopo.focus.title', { name: nodes[focusSafe]?.name ?? '' })
          : t('ipranTopo.detail.linkTitle')}
        destroyOnClose
      >
        {(focusSafe >= 0 || selectedEdge >= 0) && (
          <TopologyDetails
            nodes={nodes} edges={edges} idx={idx} fault={fault}
            focus={focusSafe} selectedEdge={selectedEdge}
            onFocus={(i) => { setFocus(i); setSelectedEdge(-1) }}
          />
        )}
      </Drawer>

      <TopoDrillModal
        kind={drill?.kind ?? null}
        anchor={drill?.anchor ?? null}
        nodes={nodes} edges={edges} idx={idx}
        onClose={() => setDrill(null)}
        onFocus={(i) => setFocus(i)}
      />
    </div>
  )
}
