/* ============================================================================
 * UME 四层拓扑画布（SVG，四层共用）
 * ============================================================================
 * 只负责「把算好的坐标画出来 + 悬停/点击交互」，布局算法在 ./layouts.ts，
 * 取数与口径在后端。这样布局能单独扫参数、单独回归，画布不用跟着改。
 *
 * 视觉约定（有实测依据，改之前先看 layouts.ts 顶部）：
 *   - 带宽只体现在**线宽**（100/25/10/其它四档），不用颜色 —— 颜色要留给故障态
 *   - 断链 = 红色虚线；有告警 = 橙色线；其余 = 中性灰且更淡（让故障自己跳出来）
 *   - critical 告警用**右下角小红点**而不是节点填色：80% 的网元都有 critical，
 *     填色等于全红（实测依据见后端 ipran_topo_service.py）
 *   - ×N 表示这对机框折叠了几条物理链路；「展开平行链路」时按扇面错开画
 * ========================================================================== */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { WH, useTheme } from '../../theme'
import type { ColorMode, LayoutResult, Pt, Sev, TopoEdge, TopoIndex, TopoNode } from './types'
import { radiusOf, widthOf } from './layouts'
import { layoutLabels } from './labels'
import { linkStateOf, parallelBreakdown, type LinkState } from './graphAlgorithms'

interface Props {
  nodes: TopoNode[]
  edges: TopoEdge[]
  idx: TopoIndex
  layout: LayoutResult
  colorMode: ColorMode
  focus: number
  showAllLabels: boolean
  foldParallel: boolean
  onToggleFocus: (i: number) => void
  /** true = 被搜索/过滤排除，聚焦邻居时仍保持可见 */
  dimmed?: boolean[] | null
  impacted?: ReadonlySet<number> | null
  selectedEdge?: number
  onSelectEdge?: (i: number) => void
  onBackgroundClick?: () => void
  viewCmd?: { seq: number; kind: 'in' | 'out' | 'fit' } | null
  /** 布局或层变化时把视口收回全图 */
  resetKey?: string
  markGeo?: boolean
  /** 门户 maponly：画布撑满父级，而不是按 760×540 的比例留高 */
  fill?: boolean
}

const W = 760
const H = 540

interface TipState {
  x: number
  y: number
  node?: number
  edge?: number
}

const SEV_VAR: Record<Sev, string> = {
  crit: WH.sev.Critical,
  major: WH.sev.Major,
  minor: WH.sev.Warning,
  warn: WH.sev.Info,
  ok: WH.ok,
}

interface ViewBox { x: number; y: number; w: number; h: number }
const HOME_VB: ViewBox = { x: 0, y: 0, w: W, h: H }

export default function TopoCanvas({
  nodes, edges, idx, layout, colorMode, focus, showAllLabels, foldParallel, onToggleFocus,
  dimmed, impacted, selectedEdge = -1, onSelectEdge, onBackgroundClick, viewCmd, resetKey, markGeo,
  fill,
}: Props) {
  const { t } = useI18n()
  const { colors } = useTheme()
  const [tip, setTip] = useState<TipState | null>(null)
  const [vb, setVb] = useState<ViewBox>(HOME_VB)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{ sx: number; sy: number; vb: ViewBox; moved: boolean } | null>(null)
  const skipClick = useRef(false)
  const { pos, bands } = layout

  useEffect(() => { setVb(HOME_VB) }, [resetKey])

  const seenView = useRef(0)
  useEffect(() => {
    if (!viewCmd || viewCmd.seq === seenView.current) return
    seenView.current = viewCmd.seq
    setVb((prev) => {
      if (viewCmd.kind === 'fit') return HOME_VB
      const factor = viewCmd.kind === 'in' ? 0.8 : 1.25
      const cx = prev.x + prev.w / 2
      const cy = prev.y + prev.h / 2
      const w = Math.min(W * 4, Math.max(W * 0.25, prev.w * factor))
      const h = Math.min(H * 4, Math.max(H * 0.25, prev.h * factor))
      return { x: cx - w / 2, y: cy - h / 2, w, h }
    })
  }, [viewCmd])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault()
      const svg = svgRef.current
      if (!svg) return
      const rect = svg.getBoundingClientRect()
      setVb((prev) => {
        const factor = ev.deltaY > 0 ? 1.12 : 0.88
        const w = Math.min(W * 4, Math.max(W * 0.25, prev.w * factor))
        const h = Math.min(H * 4, Math.max(H * 0.25, prev.h * factor))
        const px = rect.width ? (ev.clientX - rect.left) / rect.width : 0.5
        const py = rect.height ? (ev.clientY - rect.top) / rect.height : 0.5
        const ax = prev.x + prev.w * px
        const ay = prev.y + prev.h * py
        return { x: ax - w * px, y: ay - h * py, w, h }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const tierColors = useMemo(
    () => [WH.textDim, colors[0], colors[1], colors[2]],
    [colors],
  )

  const nbSet = useMemo(() => {
    if (focus < 0) return null
    const s: Record<number, 1> = { [focus]: 1 }
    idx.adj[focus]?.forEach((a) => { s[a.n] = 1 })
    return s
  }, [focus, idx])

  /* 标签贪心排版：放不下的显式隐藏而不是硬画上去（见 labels.ts） */
  const { labels, hidden } = useMemo(
    () => layoutLabels(nodes, { pos, focus, showAllLabels, nbSet, bands, W, H }),
    [nodes, pos, focus, showAllLabels, nbSet, bands],
  )

  const colorOf = (v: TopoNode) => {
    if (v.tier === 0) return WH.textDim
    if (colorMode === 'up') return v.up ? WH.ok : WH.danger
    if (colorMode === 'sev') return SEV_VAR[v.sev]
    return tierColors[v.tier]
  }

  // 显式 switch 而非拼字符串：动态 key 会被 check:i18n 当成 `ipranTopo.tier.` 报缺键
  const tierName = (tier: TopoNode['tier']) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }

  // 平行链路三态（V2 Phase 1）：同样用显式 switch 守住 i18n 静态键
  const linkStateText = (s: LinkState) => {
    switch (s) {
      case 'failed': return t('ipranTopo.link.state.failed')
      case 'partial': return t('ipranTopo.link.state.partial')
      default: return t('ipranTopo.link.state.normal')
    }
  }

  const showTip = (e: React.MouseEvent, patch: Omit<TipState, 'x' | 'y'>) => {
    const box = ((e.currentTarget as SVGElement).ownerSVGElement as SVGSVGElement).getBoundingClientRect()
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, ...patch })
  }

  const tipNode = tip?.node != null ? nodes[tip.node] : null
  const tipEdge = tip?.edge != null ? edges[tip.edge] : null
  const tipEdgeBreakdown = tipEdge ? parallelBreakdown(tipEdge) : null

  return (
    <div ref={wrapRef} style={{ position: 'relative', width: '100%', height: fill ? '100%' : undefined, touchAction: 'none' }}>
      <svg ref={svgRef} viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        style={{ width: '100%', height: fill ? '100%' : 'auto', display: 'block', cursor: 'grab' }}
        onPointerDown={(ev) => {
          if (ev.button !== 0) return
          const svg = ev.currentTarget
          svg.setPointerCapture(ev.pointerId)
          dragRef.current = { sx: ev.clientX, sy: ev.clientY, vb: { ...vb }, moved: false }
        }}
        onPointerMove={(ev) => {
          const drag = dragRef.current
          if (!drag) return
          const dx = ev.clientX - drag.sx
          const dy = ev.clientY - drag.sy
          if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true
          const rect = svgRef.current?.getBoundingClientRect()
          if (!rect?.width || !rect.height) return
          setVb({
            x: drag.vb.x - dx * (drag.vb.w / rect.width),
            y: drag.vb.y - dy * (drag.vb.h / rect.height),
            w: drag.vb.w, h: drag.vb.h,
          })
        }}
        onPointerUp={() => {
          if (dragRef.current?.moved) skipClick.current = true
          dragRef.current = null
        }}
        onClick={() => {
          if (skipClick.current) { skipClick.current = false; return }
          onBackgroundClick?.()
        }}>
        {/* 分带标注 */}
        <g>
          {bands.map((b) => (
            <g key={`${b.labelKey}-${b.y}`}>
              <text x={12} y={b.y - 14} fontSize={11} fill={WH.textMuted}
                stroke={WH.cardBg} strokeWidth={3} strokeLinejoin="round" paintOrder="stroke">
                {t(b.labelKey, b.count != null ? { n: b.count } : undefined)}
                {b.rows ? ` · ${t('ipranTopo.band.rows', { n: b.rows })}` : ''}
              </text>
              <line x1={12} y1={b.y - 8} x2={W - 12} y2={b.y - 8}
                stroke={WH.textDim} strokeOpacity={0.35} strokeWidth={1} />
            </g>
          ))}
        </g>

        {/* 边：先画真实曲线，再叠一条透明宽路径接住鼠标 */}
        <g>
          {edges.map((e, i) => {
            const a = pos[idx.byId[e.s]]
            const b = pos[idx.byId[e.t]]
            if (!a || !b) return null
            const copies = !foldParallel && e.n > 1 ? Math.min(e.n, 6) : 1
            const sIdx = idx.byId[e.s]
            const tIdx = idx.byId[e.t]
            const endsDim = !!dimmed?.[sIdx] && !!dimmed?.[tIdx]
            const active = nbSet ? !!(nbSet[sIdx] && nbSet[tIdx]) : !endsDim
            const picked = i === selectedEdge
            const linkState = linkStateOf(e)
            // Phase 1：部分故障既不能画成全断、也不能画成正常，用独立颜色与虚线节奏
            const stroke = linkState === 'failed' ? WH.danger
              : linkState === 'partial' ? WH.warn
                : e.crit ? WH.sev.Major : WH.textDim
            const mx = (a.x + b.x) / 2
            const my = (a.y + b.y) / 2
            const dx = b.x - a.x
            const dy = b.y - a.y
            const len = Math.sqrt(dx * dx + dy * dy) || 1
            /* 控制点取两端中点时二次贝塞尔退化成直线，长横线会横穿全图。
               给一个上限 9px 的轻微弧度，奇偶交替弯向，让相邻边不贴在一起。 */
            const bend = Math.min(len * 0.045, 9) * (i % 2 ? 1 : -1)
            const bx = (-dy / len) * bend
            const by = (dx / len) * bend
            const list = []
            for (let m = 0; m < copies; m++) {
              const off = copies > 1 ? (m - (copies - 1) / 2) * 5 : 0
              const nx = (-dy / len) * off
              const ny = (dx / len) * off
              const d = `M${a.x},${a.y} Q${mx + bx + nx},${my + by + ny} ${b.x},${b.y}`
              list.push(
                <path key={`e${i}-${m}`} d={d} fill="none" stroke={stroke}
                  strokeWidth={picked ? widthOf(e.gb) + 1.2 : widthOf(e.gb)}
                  strokeOpacity={active ? (linkState !== 'normal' || e.crit || picked ? 0.95 : 0.3) : 0.07}
                  strokeDasharray={linkState === 'failed' ? '4 3' : linkState === 'partial' ? '9 3' : undefined} />,
              )
            }
            list.push(
              <path key={`hit${i}`} d={`M${a.x},${a.y} Q${mx + bx},${my + by} ${b.x},${b.y}`} fill="none"
                stroke="transparent" strokeWidth={9} style={{ cursor: 'pointer' }}
                onPointerDown={(ev) => ev.stopPropagation()}
                onMouseEnter={(ev) => showTip(ev, { edge: i })}
                onMouseMove={(ev) => showTip(ev, { edge: i })}
                onMouseLeave={() => setTip(null)}
                onClick={(ev) => { ev.stopPropagation(); onSelectEdge?.(i) }} />,
            )
            if (foldParallel && e.n > 1 && active) {
              list.push(
                <text key={`n${i}`} x={mx + bx / 2} y={my + by / 2 - 2} fontSize={10}
                  textAnchor="middle" fill={linkState === 'partial' ? WH.warn : WH.textMuted} pointerEvents="none"
                  stroke={WH.cardBg} strokeWidth={2.4} strokeLinejoin="round" paintOrder="stroke">
                  ×{e.n}{linkState === 'partial' ? ` · ${e.down}/${e.n}` : ''}
                </text>,
              )
            }
            return <g key={i}>{list}</g>
          })}
        </g>

        {/* 节点 */}
        <g>
          {nodes.map((v, i) => {
            const p: Pt = pos[i]
            const r = radiusOf(v.tier)
            const dim = nbSet ? (nbSet[i] ? 1 : 0.16) : (dimmed?.[i] ? 0.14 : 1)
            const up = v.up === 1
            return (
              <g key={v.id} opacity={dim} style={{ cursor: 'pointer' }}
                onPointerDown={(ev) => ev.stopPropagation()}
                onMouseEnter={(ev) => showTip(ev, { node: i })}
                onMouseMove={(ev) => showTip(ev, { node: i })}
                onMouseLeave={() => setTip(null)}
                onClick={(ev) => { ev.stopPropagation(); onToggleFocus(i) }}>
                {v.tier === 0
                  ? <rect x={p.x - r} y={p.y - r} width={r * 2} height={r * 2} rx={1}
                      fill={colorOf(v)} stroke={WH.textDim} strokeWidth={1} />
                  : <circle cx={p.x} cy={p.y} r={r} fill={colorOf(v)}
                      stroke={up ? WH.cardBg : WH.danger}
                      strokeWidth={!up ? 2.5 : 1.6} />}
                {markGeo && v.geo === 'fuzzy' && (
                  <circle cx={p.x} cy={p.y} r={r + 3.5} fill="none"
                    stroke={WH.warn} strokeWidth={1} strokeDasharray="2 2" />
                )}
                {markGeo && v.geo === 'miss' && (
                  <circle cx={p.x} cy={p.y} r={r + 3.5} fill="none"
                    stroke={WH.textDim} strokeWidth={1} strokeDasharray="1 2" />
                )}
                {i === focus && (
                  <circle cx={p.x} cy={p.y} r={r + 4} fill="none"
                    stroke={WH.teal} strokeWidth={2} />
                )}
                {impacted?.has(i) && i !== focus && (
                  <circle cx={p.x} cy={p.y} r={r + 6} fill="none"
                    stroke={WH.sev.Major} strokeWidth={1.4} />
                )}
                {v.tier > 0 && v.crit > 0 && colorMode !== 'sev' && (
                  <circle cx={p.x + r * 0.95} cy={p.y - r * 0.95} r={2.6}
                    fill={WH.sev.Critical} stroke={WH.cardBg} strokeWidth={0.8} />
                )}
                {/* 透明大圆：小节点也有可点的命中区 */}
                <circle cx={p.x} cy={p.y} r={Math.max(r + 5, 9)} fill="transparent" />
              </g>
            )
          })}
        </g>

        {/* 标签：贪心防重叠排版（见 labels.ts）；描边底衬让文字压在连线上仍清晰 */}
        <g pointerEvents="none">
          {labels.map((L) => {
            const v = nodes[L.i]
            const isFocus = L.i === focus
            const fill = isFocus ? WH.teal
              : v.tier === 1 ? WH.text
                : v.tier === 0 ? WH.textDim : WH.textMuted
            return (
              <text key={v.id} x={L.x} y={L.y} fontSize={L.fontSize}
                textAnchor="middle" fill={fill}
                fontWeight={isFocus || v.tier === 1 ? 500 : 400}
                opacity={nbSet && !nbSet[L.i] ? 0.16 : 1}
                stroke={WH.cardBg} strokeWidth={2.6} strokeLinejoin="round"
                paintOrder="stroke">{L.text}</text>
            )
          })}
          {hidden > 0 && (
            <text x={W - 12} y={16} fontSize={10} textAnchor="end"
              fill={WH.textDim} stroke={WH.cardBg} strokeWidth={2.4}
              strokeLinejoin="round" paintOrder="stroke">
              {t('ipranTopo.canvas.labelsHidden', { n: hidden })}
            </text>
          )}
        </g>
      </svg>

      {/* 悬停明细 */}
      {tip && (tipNode || tipEdge) && (
        <div style={{
          position: 'absolute',
          left: Math.min(tip.x + 14, 520),
          top: Math.max(8, tip.y - 10),
          pointerEvents: 'none', zIndex: 5,
          background: WH.cardBg, border: WH.cardBorder, borderRadius: 'var(--wh-radius-sm)',
          padding: 'var(--wh-space-sm) var(--wh-space-md)', fontSize: 12,
          color: WH.text, boxShadow: 'var(--wh-card-shadow)', maxWidth: 380, lineHeight: 1.7,
        }}>
          {tipNode && (
            <>
              <div style={{ fontWeight: 600 }}>{tipNode.name}</div>
              <div style={{ color: WH.textMuted }}>
                {tierName(tipNode.tier)} · {tipNode.model || '-'}
              </div>
              {tipNode.ip && <div style={{ color: WH.textMuted }}>IP {tipNode.ip}</div>}
              <div style={{ color: WH.textMuted }}>
                {t('ipranTopo.tip.links', { n: tipNode.deg, k: idx.adj[tip.node as number].length })}
              </div>
              <div style={{ color: tipNode.up ? WH.ok : WH.danger }}>
                {tipNode.up ? t('ipranTopo.tip.up') : t('ipranTopo.tip.down')}
              </div>
              {tipNode.tier > 0 && (
                <div style={{ color: WH.textMuted }}>
                  {t('ipranTopo.tip.alarms', {
                    crit: tipNode.crit, major: tipNode.major,
                    minor: tipNode.minor, warn: tipNode.warn,
                  })}
                </div>
              )}
              {tipNode.tier === 3 && idx.parent[tip.node as number] >= 0 && (
                <div style={{ color: WH.textMuted }}>
                  {t('ipranTopo.tip.parent', { name: nodes[idx.parent[tip.node as number]].name })}
                </div>
              )}
              {tipNode.geo === 'miss' && (
                <div style={{ color: WH.warn }}>{t('ipranTopo.tip.noGeo')}</div>
              )}
              {tipNode.geo === 'fuzzy' && (
                <div style={{ color: WH.warn }}>
                  {t('ipranTopo.tip.fuzzyGeo', { name: tipNode.geoName })}
                </div>
              )}
            </>
          )}
          {tipEdge && (
            <>
              <div style={{ fontWeight: 600 }}>
                {nodes[idx.byId[tipEdge.s]].name} ↔ {nodes[idx.byId[tipEdge.t]].name}
              </div>
              <div style={{ color: WH.textMuted }}>
                {t('ipranTopo.tip.edgeMeta', { n: tipEdge.n, gb: tipEdge.gb ?? '-' })}
              </div>
              {tipEdgeBreakdown && (
                <>
                  <div style={{ color: tipEdgeBreakdown.state === 'normal' ? WH.ok
                    : tipEdgeBreakdown.state === 'partial' ? WH.warn : WH.danger }}>
                    {linkStateText(tipEdgeBreakdown.state)}
                  </div>
                  <div style={{ color: WH.textMuted }}>
                    {t('ipranTopo.tip.edgeBreakdown', {
                      up: tipEdgeBreakdown.up,
                      down: tipEdgeBreakdown.down,
                      total: tipEdgeBreakdown.total,
                    })}
                  </div>
                </>
              )}
              {tipEdge.down > 0 && (
                <div style={{ color: WH.danger }}>{t('ipranTopo.tip.edgeDown', { n: tipEdge.down })}</div>
              )}
              <div style={{ color: WH.textMuted }}>
                {t('ipranTopo.detail.util', {
                  rx: typeof tipEdge.rxUtil === 'number' ? `${tipEdge.rxUtil}%` : t('ipranTopo.detail.na'),
                  tx: typeof tipEdge.txUtil === 'number' ? `${tipEdge.txUtil}%` : t('ipranTopo.detail.na'),
                })}
              </div>
              {(tipEdge.crit > 0 || tipEdge.major > 0) && (
                <div style={{ color: WH.sev.Major }}>
                  {t('ipranTopo.tip.edgeAlarms', { crit: tipEdge.crit, major: tipEdge.major })}
                </div>
              )}
              <div style={{ color: WH.textDim, fontSize: 11, whiteSpace: 'pre-line' }}>
                {tipEdge.ports.slice(0, 4).join('\n')}
                {tipEdge.ports.length > 4 ? `\n… ${t('ipranTopo.tip.more', { n: tipEdge.ports.length - 4 })}` : ''}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
