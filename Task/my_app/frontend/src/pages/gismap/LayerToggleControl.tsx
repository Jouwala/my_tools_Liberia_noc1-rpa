/* 地图图层控制（2026-10-02 新增）
 *
 * 背景：换成自托管 PMTiles 矢量底图后，瓦片里带 1.7 万个地名（hamlet 12607 +
 * isolated_dwelling 2590）。标注全开时「密密麻麻，什么都看不清」—— 这是用户
 * 的原话。故**默认关闭全部注记**，由本控件按需打开。
 *
 * 设计要点：
 *  1. **不改 PmtilesLayer 内部状态**，只把 showLabels 提上去由本控件驱动。
 *     这样「谁控制显隐」只有一处，不让图层自己藏一个开关。
 *  2. **用 React 绝对定位浮层，而不是 Leaflet 的 L.control**。
 *     试过 L.control + React 混合渲染：L.control 的 onAdd 要求返回裸 HTMLElement，
 *     而 React 需要自己拥有 DOM 子树，两者争同一个节点时卸载顺序很难保证正确
 *     （与 LeafletMap.tsx:362-373 记录的「容器身份必须和 React 挂载周期对齐」
 *     是同一类坑）。本项目的 MapLegendOverlay 也是纯 React 浮层，保持一致。
 *  3. **位置避开右上角的 zoom 控件**：Leaflet 的 zoom 在 topright，宽约 30px、
 *     高约 80px，故这里 right 留 56px、top 留 10px，不与之重叠。
 *  4. **层级取 1000**：与 MapLegendOverlay 同层（理由见该文件头部第 3 条），
 *     np 页面里本控件与图例分处右上/左下，不会互相遮挡。
 *  5. **文案不进 i18n**：与 MapLegendOverlay 同一约定（该文件头部第 41-43 行），
 *     文案由调用方 t() 好再传入，check:i18n 的漏键守卫仍能在 GISMap 里看见
 *     字面量键；此处若写 t('gis.layer.' + x) 拼接，守卫看不见、拼错只显示键名。
 *  6. 配色走 WH / --wh-* 令牌（AGENTS.md 三.3），深浅自动跟随。但**面板底色
 *     必须给不透明档**：它压在瓦片上，而低不透明度正是 MapLegendOverlay 那条
 *     历史教训（透明面板 + 小字在花底上读不清）。故这里用卡片底色而非透明。
 */
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useMap, isMapAlive } from '../../components/LeafletMap'
import { WH } from '../../theme'

/** 面板里的一个开关项。文案由调用方 t() 后传入（理由见文件头第 5 点）。 */
export interface LayerToggleItem {
  /** React 列表 key，同时用于区分每一项 */
  key: string
  /** 复选框旁的文案 */
  label: string
  checked: boolean
  onChange: (next: boolean) => void
  /** 单项的原生 title 提示（可选） */
  hint?: string
}

export interface LayerToggleControlProps {
  /** 控件标题，由调用方 t() 后传入（理由见文件头第 5 点） */
  title: string
  /** 开关项列表。**用数组而不是固定几个 props**：将来再加开关时只改调用方，
   *  本组件与排版不用动。2026-10-03 从单开关（仅地名）扩展为多开关（+道路）。 */
  items: LayerToggleItem[]
  /** 整个面板的原生 title 提示（可选，鼠标悬停面板时显示） */
  hint?: string
}

export function LayerToggleControl({
  title, items, hint,
}: LayerToggleControlProps) {
  const map = useMap()
  /* 挂载点：Leaflet 的地图容器。
   *
   * 为什么要 portal 而不是直接 return 一个绝对定位 div：
   * 本组件是 <MapContainer> 的**子节点**，而 MapContainer 渲染的外层 div
   * （LeafletMap.tsx:412）没有 position:relative —— 绝对定位会一路窜到
   * 页面根上去，浮层跑到地图外面。故把它 portal 进 Leaflet 自己管理的
   * 容器（该容器本身就是 position:relative），定位才落在地图上。 */
  const [host, setHost] = useState<HTMLElement | null>(null)
  const mapRef = useRef(map)

  useEffect(() => { mapRef.current = map }, [map])

  useEffect(() => {
    if (!isMapAlive(map)) return
    // getContainer() 返回 Leaflet 的地图容器（position:relative），见上面说明
    setHost(map.getContainer())
  }, [map])

  if (!host) return null

  return createPortal(
    <Box title={title} items={items} hint={hint} />,
    host,
  )
}

/** 纯展示体，抽出来是为了让 portal 与样式分离，便于单测与复用 */
function Box({ title, items, hint }: LayerToggleControlProps) {
  if (!title) return null

  const box: CSSProperties = {
    position: 'absolute',
    // 避开右上角 zoom 控件（约 30px 宽 + 10px 外边距），见文件头第 3 点
    top: 10,
    right: 56,
    zIndex: 1000,
    minWidth: 132,
    padding: '7px 9px',
    borderRadius: 8,
    /* 不透明卡片底 + 描边：压在瓦片上的文字必须有自己的底（文件头第 6 点）。
     * 注意 WH.cardBg 是**渐变**（theme.ts:15/40/73），只能给 background 不能给
     * backgroundColor；WH.cardBorder 则自带 "1px solid ..." 整串，故不能再拼宽度。 */
    background: WH.cardBg,
    border: WH.cardBorder,
    boxShadow: '0 2px 8px rgba(0,0,0,0.16)',
    color: WH.text,
    fontSize: 11,
    lineHeight: 1.5,
    userSelect: 'none',
  }

  const head: CSSProperties = {
    fontWeight: 600,
    fontSize: 10,
    letterSpacing: 0.4,
    textTransform: 'uppercase',
    color: WH.textDim,
    marginBottom: 4,
  }

  const row: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
  }

  return (
    <div
      /* id 供 RegionRankingOverlay 实测本面板高度，从而把自己摆到正下方
         （2026-10-14 用户要求「MAINTENANCE ALERTS 放到 LAYERS 下面」）。
         改这里要同步 gismap/RegionRankingOverlay.tsx 的 LAYERS_PANEL_ID。 */
      id="gis-layers-panel"
      style={box}
      title={hint}
      /* 阻止冒泡到地图：否则点复选框会顺手拖动/缩放大图 */
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
    >
      <div style={head}>{title}</div>
      {/* 每个开关一项：用 label 包住 input，点文字也能切换，且天然获得键盘可达性 */}
      {items.map((it) => (
        <label key={it.key} style={row} title={it.hint}>
          <input
            type="checkbox"
            checked={it.checked}
            onChange={(e) => it.onChange(e.target.checked)}
            style={{ margin: 0, cursor: 'pointer' }}
          />
          <span>{it.label}</span>
        </label>
      ))}
    </div>
  )
}
