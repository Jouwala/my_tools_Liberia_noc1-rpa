/* Leaflet 声明式封装（原生 leaflet，取代 react-leaflet）
 *
 * 为什么不用 react-leaflet（2026-09-27 许可核查结论）：
 *   react-leaflet@5 与 @react-leaflet/core 的许可都是 **Hippocratic-2.1** —— 非 OSI
 *   认证，带「须遵守人权原则／人权法」的使用限制、海牙仲裁条款与赔偿（indemnity）
 *   义务。这属于企业采购规范常见的禁用项，法务上是不确定义务。
 *   注意：**降到 4.2.1 也没用**，4.x 同样是 Hippocratic-2.1，不存在干净的旧版本。
 *   底层 leaflet 本体是 BSD-2-Clause（干净），Hippocratic 只覆盖那层薄薄的 React 绑定。
 *
 * 因此这里用原生 leaflet 重新实现所需的那一层绑定，保持与原来一致的声明式写法，
 * 使页面 JSX 几乎不用改、地图行为完全不变。所需能力很少：
 *   MapContainer / TileLayer / Marker / CircleMarker / Polyline / Polygon / Popup / Tooltip / Pane
 *   （Marker 是 2026-10-14 为「县名标注动态避让」新增的不可见锚点，见该组件注释）
 *
 * 设计要点（都是原 react-leaflet 已经处理、我们必须自己保证的）：
 *   1. **图层生命周期**：子组件在「属于它的那层 map/父图层」就绪后再 addLayer，
 *      卸载时 removeLayer；否则会出现「地图没挂载就 new CircleMarker」的报错。
 *   2. **props 变更就地更新**：Leaflet 对象是命令式的，不能靠重渲染。坐标、半径、
 *      颜色、pathOptions 变化时必须调用 setLatLng/setRadius/setStyle 等，
 *      否则筛选/主题切换后地图不会重绘（这是最容易漏的一处）。
 *   3. **Popup/Tooltip 内容用 React 渲染**：Leaflet 只接受 HTMLElement|string，
 *      故内容挂到 createPortal 的容器里，保持 React 组件与 i18n 的写法不变。
 *   4. **不吞事件**：CircleMarker 的 click 交给 onClick 回调（GISMap 点站点开抽屉依赖它）。
 */
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

type LatLngTuple = [number, number]
/** 多边形/折线坐标：允许 [lat,lng][] 或嵌套的 [lat,lng][][]（counties 是多环） */
type LatLngInput = LatLngTuple | LatLngTuple[] | LatLngTuple[][] | any

/* ------------------------------------------------------------------ *
 * 上下文：把「最近的一层 Leaflet 容器」传给子组件
 * ------------------------------------------------------------------ */

const MapCtx = createContext<L.Map | null>(null)
/** 最近的父图层（CircleMarker / Polyline / Polygon 是 L.Path；
 *  Marker 是 L.Marker —— 两者唯一的共同点就是都能 addTo 与承载 Popup/Tooltip，
 *  故类型取 L.Layer。2026-10-14 放宽：此前写死 L.Path 是为了表达「只有 path
 *  类图层才当父节点」，但县名标注改成 Marker 承载后该前提不再成立。 */
const LayerCtx = createContext<L.Layer | null>(null)

/** 当前子树应该把图层加到哪儿：有父图层就加父图层，否则直接加 map */
function useLeafletParent(): { map: L.Map | null; parent: L.Layer | L.Map | null } {
  const map = useContext(MapCtx)
  const layer = useContext(LayerCtx)
  return { map, parent: layer ?? map }
}

/** map 是否已被销毁（Leaflet 的 remove() 会摘掉 _container 与 panes）。
 *  往这种 map 上 addLayer 会抛 `appendChild(undefined)`，且因为是 render/effect
 *  期间抛出，会连带把整个 React 树打崩（2026-09-28 白屏事故的最终表现）。
 *  故所有 addTo/addLayer 之前都先过这一道闸。
 *  2026-10-02 起导出：gismap/PmtilesLayer.tsx 加图层时同样需要这道闸。 */
export function isMapAlive(map: L.Map | null | undefined): map is L.Map {
  if (!map) return false
  const anyMap = map as any
  if (anyMap._container == null) return false
  if (anyMap._panes == null) return false
  return true
}

/** 供自定义子组件拿到 map 实例（等价于原 react-leaflet 的 useMap） */
export function useMap(): L.Map {
  const map = useContext(MapCtx)
  if (!map) throw new Error('useMap 必须在 <MapContainer> 内使用')
  return map
}

/* ------------------------------------------------------------------ *
 * Popup / Tooltip：Leaflet 只吃 DOM，这里用 portal 渲染 React 内容
 * ------------------------------------------------------------------ */

type ContentLayerProps = {
  children?: ReactNode
  /** 常驻显示（Tooltip 用于县名标注） */
  permanent?: boolean
  direction?: L.Direction
  className?: string
  pane?: string
}

function makeContentLayer(
  kind: 'popup' | 'tooltip',
) {
  return function ContentLayer({ children, permanent, direction, className, pane }: ContentLayerProps) {
    const { map, parent } = useLeafletParent()
    // 稳定的 DOM 宿主：Leaflet 持有它，React 往里 portal
    const hostRef = useRef<HTMLDivElement | null>(null)
    if (!hostRef.current && typeof document !== 'undefined') {
      hostRef.current = document.createElement('div')
    }

    useEffect(() => {
      if (!parent) return
      const host = hostRef.current
      if (!host) return

      /* pane 一律用条件展开：Leaflet 的 setOptions 是直接覆盖，
       * 传 pane: undefined 会抹掉类默认值（popup→'popupPane'、
       * tooltip→'tooltipPane'），openOn/onAdd 里 getPane() 拿到
       * undefined 后 appendChild 直接抛异常。见 TileLayer 注释。 */
      const layer =
        kind === 'popup'
          ? L.popup(pane ? { pane } : {})
          : L.tooltip({
              permanent, direction, className,
              ...(pane ? { pane } : {}),
            })
      layer.setContent(host)

      // Popup/Tooltip 必须 bind 到一个 L.Layer（CircleMarker/Polyline/Polygon）上，
      // 直接 addTo(map) 只会变成「打开着一个游离弹窗」，点站点不会弹。
      const binder = parent as any
      if (kind === 'popup') {
        binder.bindPopup?.(layer)
      } else {
        binder.bindTooltip?.(layer)
      }

      return () => {
        try {
          if (kind === 'popup') binder.unbindPopup?.()
          else binder.unbindTooltip?.()
        } catch {
          /* 父图层已销毁时忽略 */
        }
      }
    }, [parent, permanent, direction, className, pane])

    if (!hostRef.current) return null
    return createPortal(children, hostRef.current)
  }
}

export const Popup = makeContentLayer('popup')
export const Tooltip = makeContentLayer('tooltip')

/* ------------------------------------------------------------------ *
 * Pane：自定义 pane（GISMap 用它把站点圆点压到县底块之上）
 * ------------------------------------------------------------------ */

export function Pane({ name, style }: { name: string; style?: React.CSSProperties }) {
  const map = useMap()

  /* 必须在**渲染期**同步建好 pane，不能放到 useEffect。
   * 原因：使用该 pane 的 CircleMarker 会在自己的 useMemo（渲染期）里
   * `L.circleMarker(..., { pane: 'sitePane' })`；若此刻 pane 还没建，
   * Leaflet 的 getPane() 返回 undefined，路径元素挂不进 DOM，
   * 结果就是这个 pane 上的圆点根本不显示（且不报错，很难查）。
   * 渲染期做副作用不优雅，但这里是幂等的 DOM 建节点，且顺序由 React
   * 的深度优先渲染保证（Pane 在 JSX 中先于使用它的图层）。
   * 前置条件：MapContainer 已保证「map ready 后才渲染 children」，
   * 故此处 map.getPanes() 必定已建好，createPane 是安全的。 */
  // 地图已销毁时不再建 pane（createPane 会往已摘除的 _panes 上挂，抛 appendChild 异常）
  if (!isMapAlive(map)) return null
  if (!map.getPane(name)) {
    const pane = map.createPane(name)
    Object.assign(pane.style, style || {})
  }
  return null
}

/* ------------------------------------------------------------------ *
 * TileLayer
 * ------------------------------------------------------------------ */

export function TileLayer({
  url,
  attribution,
  pane,
  maxZoom,
}: {
  url: string
  attribution?: string
  pane?: string
  /** 瓦片最大层级。不传走 Leaflet 默认 18；OSM 标准瓦片支持到 19。 */
  maxZoom?: number
}) {
  const { map } = useLeafletParent()
  useEffect(() => {
    // 见 isMapAlive 注释：地图已销毁时 addTo 会 appendChild(undefined) 打崩整页
    if (!isMapAlive(map)) return
    /* 必须**只在 pane 有值时才把 pane 放进 options**。
     * Leaflet 的 setOptions 是直接覆盖：传 { pane: undefined } 会把
     * GridLayer 类默认的 'tilePane' 抹成 undefined，随后 onAdd 里
     * getPane() → map.getPane(undefined) → _panes[undefined] → undefined，
     * 执行 undefined.appendChild(...) 直接抛异常，整个地图页白屏。
     * 这个坑 tsc 与 vite build 都发现不了，只有真正跑起来才暴露。
     * maxZoom 同理用条件展开，避免显式传 undefined 覆盖类默认值。 */
    const opts: L.TileLayerOptions = { attribution }
    if (pane) opts.pane = pane
    if (maxZoom != null) opts.maxZoom = maxZoom
    const layer = L.tileLayer(url, opts)
    layer.addTo(map)
    return () => {
      layer.remove()
    }
  }, [map, url, attribution, pane, maxZoom])
  return null
}

/* ------------------------------------------------------------------ *
 * Marker —— 不可见的锚点，专供「需要任意定位的常驻 Tooltip」使用
 * ------------------------------------------------------------------ */

type MarkerProps = {
  position: LatLngTuple
  /** 是否响应鼠标事件。默认 true（Leaflet 默认）；
      县名标注传 false —— 它只负责承载 tooltip，不该拦截地图拖拽与站点点击。 */
  interactive?: boolean
  children?: ReactNode
}

/**
 * 一个**零视觉**的 Marker，仅作为 Popup/Tooltip 的挂载锚点。
 *
 * 为什么需要它（2026-10-14 县名避让）：
 *   Leaflet 的 Tooltip 必须 bind 到一个 L.Layer，且**只能显示在该图层自己的
 *   坐标上**。原先县名 tooltip 绑在 Polygon 上，锚点就被钉死为多边形质心，
 *   无法避让重叠。改挂到 Marker 后，锚点变成可任意指定的坐标 ——
 *   这是「动态避让」得以实现的结构前提。
 *
 * 为什么用 divIcon 画一个空 div，而不是把 Marker 设成 opacity:0：
 *   L.Marker 的默认图标是**一张图片**（marker-icon.png），本项目改用自研
 *   LeafletMap 的原因之一就是不引入额外的图片资源与版权问题（见文件头）。
 *   传一个空 divIcon 既能避免加载图片，又能保证「零尺寸、零视觉」，
 *   不会像默认图标那样在避让后的位置上留下一个可见的图钉。
 */
export function Marker({ position, interactive = true, children }: MarkerProps) {
  const { map, parent } = useLeafletParent()

  const layer = useMemo(() => {
    if (!parent) return null
    return L.marker(position, {
      interactive,
      // 空 divIcon：零尺寸、无图片请求（理由见上方注释）
      icon: L.divIcon({ className: 'leaflet-empty-anchor', html: '', iconSize: [0, 0] }),
    })
    // 刻意只依赖 parent：初值即可，position 变更走下方 setter
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parent])

  useEffect(() => {
    if (!layer || !parent) return
    // 父图层或地图已销毁时不再 addTo（见 isMapAlive 注释）
    if (parent instanceof L.Map ? !isMapAlive(parent) : !(parent as any)._map) return
    layer.addTo(parent as any)
    return () => {
      layer.remove()
    }
  }, [layer, parent])

  useEffect(() => {
    if (!layer) return
    layer.setLatLng(position)
  }, [layer, position])

  if (!layer) return null
  return <LayerCtx.Provider value={layer}>{children}</LayerCtx.Provider>
}

/* ------------------------------------------------------------------ *
 * CircleMarker
 * ------------------------------------------------------------------ */

type CircleMarkerProps = {
  center: LatLngTuple
  radius: number
  fillColor?: string
  color?: string
  weight?: number
  opacity?: number
  fillOpacity?: number
  pane?: string
  /** 附加到 Leaflet SVG path 上的 class（Leaflet Path 的 className 选项）。
      2026-10-02 新增，供 GIS 超时告警圆点的 CSS 呼吸动画选中（.gis-halo）。
      CSS 动画只能作用在 DOM 元素上，而 CircleMarker 的 props 走的是 SVG 属性，
      没有 className 就无从在 CSS 里选到它 —— 故这里透传一层。 */
  className?: string
  onClick?: () => void
  children?: ReactNode
}

export function CircleMarker({
  center, radius, fillColor, color, weight, opacity, fillOpacity, pane, className, onClick, children,
}: CircleMarkerProps) {
  const { map, parent } = useLeafletParent()

  // 只在 parent 就绪时创建一次；后续变更走 setter（见下）
  const layer = useMemo(() => {
    if (!parent) return null
    // 兜底：pane 尚未建好时先补建，避免 JSX 里 Pane 写在图层之后导致圆点不渲染
    if (pane && map && !map.getPane(pane)) map.createPane(pane)
    /* pane 用条件展开：传 pane: undefined 会把 Path 默认的 'overlayPane'
     * 覆盖成 undefined，onAdd 时 getPane() 拿到 undefined 直接崩。
     * 与 TileLayer 同一类坑（见该组件注释）。 */
    return L.circleMarker(center, {
      radius, fillColor, color, weight, opacity, fillOpacity,
      ...(className ? { className } : {}),
      ...(pane ? { pane } : {}),
    })
    // 刻意只依赖 parent：初值即可，变更由下面的 effect 处理
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parent])

  useEffect(() => {
    if (!layer || !parent) return
    // 父图层或地图已销毁时不再 addTo（见 isMapAlive 注释）
    if (parent instanceof L.Map ? !isMapAlive(parent) : !(parent as any)._map) return
    layer.addTo(parent as any)
    return () => {
      layer.remove()
    }
  }, [layer, parent])

  // props 变更就地更新 —— 缺失这段会导致筛选/主题切换后圆点不刷新
  useEffect(() => {
    if (!layer) return
    layer.setLatLng(center)
    layer.setRadius(radius)
    layer.setStyle({ fillColor, color, weight, opacity, fillOpacity })
  }, [layer, center, radius, fillColor, color, weight, opacity, fillOpacity])

  // 点击回调：用 ref 存最新闭包，避免每次 render 都 off/on
  const clickRef = useRef(onClick)
  clickRef.current = onClick
  useEffect(() => {
    if (!layer) return
    const handler = () => clickRef.current?.()
    layer.on('click', handler)
    return () => {
      layer.off('click', handler)
    }
  }, [layer])

  if (!layer) return null
  // 用 Provider 把该图层作为 Popup/Tooltip 的父节点
  return <LayerCtx.Provider value={layer}>{children}</LayerCtx.Provider>
}

/* ------------------------------------------------------------------ *
 * Polyline / Polygon —— 结构相同，仅构造函数与坐标形态不同
 * ------------------------------------------------------------------ */

type PathProps = {
  positions: LatLngInput
  pathOptions?: L.PathOptions
  onClick?: () => void
  children?: ReactNode
}

function makePath(kind: 'polyline' | 'polygon') {
  return function Path({ positions, pathOptions, onClick, children }: PathProps) {
    const { parent } = useLeafletParent()

    const layer = useMemo(() => {
      if (!parent) return null
      return kind === 'polyline'
        ? L.polyline(positions as any, pathOptions)
        : L.polygon(positions as any, pathOptions)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [parent])

    useEffect(() => {
      if (!layer || !parent) return
      layer.addTo(parent as any)
      return () => {
        layer.remove()
      }
    }, [layer, parent])

    // 坐标或样式变更就地更新（拓扑线随筛选开关变化）
    useEffect(() => {
      if (!layer) return
      layer.setLatLngs(positions as any)
      if (pathOptions) layer.setStyle(pathOptions)
    }, [layer, positions, pathOptions])

    const clickRef = useRef(onClick)
    clickRef.current = onClick
    useEffect(() => {
      if (!layer) return
      const handler = () => clickRef.current?.()
      layer.on('click', handler)
      return () => {
        layer.off('click', handler)
      }
    }, [layer])

    if (!layer) return null
    return <LayerCtx.Provider value={layer}>{children}</LayerCtx.Provider>
  }
}

export const Polyline = makePath('polyline')
export const Polygon = makePath('polygon')

/* ------------------------------------------------------------------ *
 * MapContainer：真正创建地图
 * ------------------------------------------------------------------ */

type MapContainerProps = {
  center: LatLngTuple
  zoom: number
  className?: string
  style?: React.CSSProperties
  scrollWheelZoom?: boolean
  children?: ReactNode
}

export function MapContainer({
  center, zoom, className, style, scrollWheelZoom = true, children,
}: MapContainerProps) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const [map, setMap] = useState<L.Map | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    /* 关键：每次 effect 执行都新建一个「内层容器」div 交给 Leaflet。
     * 为什么不能直接对 hostRef 建图：React 19 StrictMode 会
     * mount → cleanup → mount 跑两遍。若两次都拿同一个 div 建图，
     * 第一次 remove() 会删掉该 div 的 _leaflet_id 并摘掉内部的
     * pane 节点，第二次 L.map(同一个 div) 复用这个已被破坏的容器，
     * Leaflet 内部的 getPane() 便拿不到 pane → onAdd/_initContainer
     * 里 appendChild(undefined) 直接抛异常，整页白屏。
     * 每次建全新 div，等于把「容器身份」和 React 的挂载周期对齐。 */
    const inner = document.createElement('div')
    inner.style.width = '100%'
    inner.style.height = '100%'
    host.appendChild(inner)

    const m = L.map(inner, {
      center,
      zoom,
      scrollWheelZoom,
      // 与 react-leaflet 默认一致：右上角只有 zoom 控件
      zoomControl: true,
      /* zoomSnap: 0.5 —— 允许 zoom 取 7.5 / 8.5 这类**半级**档位。
       *
       * Leaflet 默认 zoomSnap=1，会把传入的 zoom **吸附到整数**：
       * 传 7.5 进去，地图实际渲染在 8 —— 也就是说没有这行，
       * 「加一个 7.5 档」在界面上不会报错，但会静默地表现成 8，
       * 是个查起来很费劲的坑。
       *
       * 选 0.5 而不是更细的 0.1：0.5 正好覆盖调用方要的三档（7.5 / 8 / 8.5），
       * 也让滚轮与 +/- 按钮的每一格步进是半级 —— 步进太小（0.1）时
       * 用户要滚十几次才明显变化，观感是「滚不动」。
       * 该值同时对初始 zoom、setView、zoomIn/zoomOut 生效（Leaflet 内部统一走
       * _limitZoom 吸附），故本页传小数 zoom 时不必再各自处理。 */
      zoomSnap: 0.5,
    })
    mapRef.current = m
    // L.map() 内部同步完成 _initLayout/_initPanes，
    // 且传了 center+zoom，_loaded 已为 true，故可直接挂子图层。
    setMap(m)

    /* 卸载时**不要** setMap(null)。
     *
     * 2026-09-28 实测崩溃修复（整页白屏，?page=gis 必现）：
     * 原实现在这里 setMap(null)，导致「先销毁地图、再重渲染子树」的错序 ——
     * cleanup 里 m.remove() 已摘掉 panes，紧接着 setMap(null) 触发一次重渲染，
     * React 用**仍然持有旧 map 的 context** 去重跑子图层 effect，TileLayer 的
     * `L.tileLayer(...).addTo(map)` 便落到一个 _container 已被清空的 map 上：
     *   t._initContainer → onAdd → appendChild(undefined)
     * 异常抛出时 React 正在卸载整棵树，于是连 #root 一起被清空（不是只坏地图）。
     * 浏览器实测：#root innerHTML 长度 0、16 个同类报错，且 tsc / vite build 都查不出。
     *
     * 正确做法：cleanup 只负责销毁 Leaflet 实例；map state 保持原值不再变更，
     * 子树的卸载由 React 本身驱动（其 cleanup 顺序是「子先父后」，子图层先 remove，
     * 此时 map 仍存活，是安全的）。组件重挂载时会走一次全新的 effect，setMap(m) 覆盖。
     */
    return () => {
      m.remove()
      mapRef.current = null
      if (inner.parentNode === host) host.removeChild(inner)
    }
    // 刻意只在挂载时创建一次：center/zoom 后续变化由 MapController 负责
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div ref={hostRef} className={className} style={style}>
      {map ? <MapCtx.Provider value={map}>{children}</MapCtx.Provider> : null}
    </div>
  )
}
