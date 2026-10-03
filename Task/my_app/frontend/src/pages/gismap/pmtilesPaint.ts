/* 自托管 PMTiles 矢量底图的绘制规则（protomaps-leaflet 5.1.0）
 *
 * 为什么单独一个文件：这些规则与 basemap.ts 的配色是「一起改」的（图层名或配色
 * 变了，两边都要动），但内容较长且是纯数据+回调，混进 basemap.ts 会淹掉那里的方案说明。
 *
 * ⚠️ 本文件与瓦片 schema 强耦合。瓦片由 D:\tiles-work\config-basic.json 生成，
 *    图层名固定为：place / transportation / water / waterway / poi / building。
 *    **改瓦片配置必须同步改这里**，否则新图层不显示（且不会报错，只是空白）。
 *
 * ⚠️ 不要改成 protomaps 内置 flavor —— 那套是 OpenMapTiles schema，与本项目
 *    图层名只有 water 一个同名（实测 1/6 命中）。详见 basemap.ts 文件头。
 *
 * ---------------------------------------------------------------------------
 * 2026-10-02 实测的 API 事实（这一版是照着 index.d.ts 逐条核对后写的，
 * 第一版凭印象写错了三处，全部会被 tsc 或运行时拦下，列在这里免得后人重犯）：
 *
 *  1. **没有 `Symbolizer` 基类可继承**。只有具体类：PolygonSymbolizer /
 *     LineSymbolizer / CircleSymbolizer / CenteredTextSymbolizer /
 *     LineLabelSymbolizer 等。想自定义必须用这些类 + 它们的构造参数。
 *  2. **规则的缩放字段是小写 `minzoom` / `maxzoom`**（PaintRule、LabelRule 都是），
 *     不是 `minZoom`。写错了 tsc 会报未知属性（好在能拦住）。
 *     符号器本身**不接受**缩放参数，缩放只在规则层控制。
 *  3. **文字符号器没有 `label` 回调**。文字取自 `labelProps`（默认 `["name"]`，
 *     即按顺序找 props 里第一个字符串属性）。要换属性名传 `labelProps: ['名字']`。
 *     运行时实现见 dist/cjs/index.cjs 的 TextAttr：
 *       this.labelProps = e?.labelProps ?? ["name"]
 *  4. **`dash` 是 `number[]`**（LineSymbolizer 的选项），不是函数。
 * ---------------------------------------------------------------------------
 *
 * 2026-10-02 实测依据：同一套规则在无头 Chrome 下渲染通过 —— 浅色 z8/z13/z14
 * 颜色数 18→30、边缘像素比 0.066→0.123，深色主题 19 色，无 JS 运行时错误；
 * 并反查水域像素经纬度落在蒙罗维亚以西大西洋（平均经度 -10.834），地理正确。
 */
import {
  CenteredTextSymbolizer,
  CircleSymbolizer,
  LineLabelSymbolizer,
  LineSymbolizer,
  PolygonSymbolizer,
  type LabelRule,
  type PaintRule,
} from 'protomaps-leaflet'
import type { BasemapTheme } from './basemap'

/** Feature.props 是普通 JsonObject（不是 Map）。直接 `props[k]` 取值。 */
type AnyFeature = { props?: Record<string, unknown> }

function readProp(f: unknown, key: string): string {
  const v = (f as AnyFeature)?.props?.[key]
  return typeof v === 'string' ? v : ''
}

/** 道路/铁路分类。tilemaker 的 transportation 图层用 class 区分。 */
const MAJOR_ROADS = ['motorway', 'trunk', 'primary']
const MEDIUM_ROADS = ['secondary', 'tertiary']
const RAIL = ['rail', 'transit', 'light_rail', 'subway', 'tram']

/* 低缩放（z0~z4）时 transportation 图层还不存在（config-basic.json 里它 minzoom=4），
 * 全图只有 place 一个图层。所以**低缩放必须靠 place 撑住画面**，否则 z0~z3 是纯底色空白。
 * 2026-10-02 实测：z1/z3 曾渲染出 0 个非背景像素、颜色数 1，就是漏了这条。
 * place 的 class 取值很杂（hamlet 12607 个、isolated_dwelling 2590 个…），
 * 低缩放下只能挑「大地方」画，否则 1.7 万个要素堆在一起糊成一团。 */
const BIG_PLACES = ['country', 'state', 'region', 'city', 'town']

const isRail = (_z: number, f: unknown) => RAIL.includes(readProp(f, 'class'))
const isNotRail = (z: number, f: unknown) => !isRail(z, f)
const isMajor = (_z: number, f: unknown) => MAJOR_ROADS.includes(readProp(f, 'class'))
const isMedium = (_z: number, f: unknown) => MEDIUM_ROADS.includes(readProp(f, 'class'))
const isBigPlace = (_z: number, f: unknown) => BIG_PLACES.includes(readProp(f, 'class'))

/**
 * 生成某个主题的绘制规则。数组顺序即绘制顺序（先描边后路面）。
 * @param t 主题配色（basemap.ts 的 LIGHT_THEME / DARK_THEME）
 * @param showRoads 是否绘制道路/铁路（transportation 图层）。默认 true。
 *   关闭时**整段交通规则不生成** —— 与 showLabels 的「传空数组」同理但更直接：
 *   规则压根不构造，protomaps 便不会为该图层分配绘制资源。
 *   （2026-10-03 用户要求「隐藏底图路线」做成开关。）
 */
export function buildPaintRules(t: BasemapTheme, showRoads = true): PaintRule[] {
  return [
    /* ---- 低缩放的城市点：z0~z7 ----
     * 这段区间 transportation 还不存在（minzoom=4）或很稀疏，画面主要靠城市点撑着。
     * z8 起交给标注文字（buildLabelRules），故这里 maxzoom=7 收住，避免和大字重叠。 */
    {
      dataLayer: 'place',
      symbolizer: new CircleSymbolizer({
        radius: 3.5, fill: t.poi, stroke: t.textHalo, width: 1,
      }),
      maxzoom: 7,
      filter: isBigPlace,
    },

    /* ---- 水体面：z6 起（config-basic.json 的 water 层 minzoom=6）----
     * 底色（海陆未覆盖处）由 leafletLayer 的 backgroundColor 铺，见 PmtilesLayer.tsx。 */
    {
      dataLayer: 'water',
      symbolizer: new PolygonSymbolizer({ fill: t.water, opacity: 1 }),
      minzoom: 6,
    },

    // ---- 水系线：z8 起 ----
    {
      dataLayer: 'waterway',
      symbolizer: new LineSymbolizer({ color: t.waterway, width: 1.2 }),
      minzoom: 8,
    },

    // ---- 建筑：z14 起（config-basic.json 的 building 层 minzoom=14）----
    {
      dataLayer: 'building',
      symbolizer: new PolygonSymbolizer({ fill: t.building, opacity: 1 }),
      minzoom: 14,
    },
    {
      dataLayer: 'building',
      symbolizer: new LineSymbolizer({ color: t.buildingOutline, width: 0.5 }),
      minzoom: 14,
    },

    /* ---- 道路/铁路：由 showRoads 开关控制（见 buildRoadRules）----
     * 展开成独立函数是为了让「关闭道路」只有一个删点，而不是在这里散落 6 处判断。
     * 数组顺序即绘制顺序：道路必须在建筑之后（后画的压在上面）。 */
    ...(showRoads ? buildRoadRules(t) : []),
  ]
}

/**
 * 道路/铁路绘制规则（transportation 图层）。先描边（casing）后路面，形成立体感。
 * 单独抽出，供 buildPaintRules 按 showRoads 开关决定是否展开。
 */
function buildRoadRules(t: BasemapTheme): PaintRule[] {
  return [
    // 次级路（z4 起）
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMinorCasing, width: 3 }),
      minzoom: 4,
      filter: isNotRail,
    },
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMinor, width: 1.8 }),
      minzoom: 4,
      filter: isNotRail,
    },
    // 中等道路（z8 起加粗）
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMajorCasing, width: 4.5 }),
      minzoom: 8,
      filter: isMedium,
    },
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMajor, width: 3 }),
      minzoom: 8,
      filter: isMedium,
    },
    // 主干道（z6 起）
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMajorCasing, width: 6 }),
      minzoom: 6,
      filter: isMajor,
    },
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.roadMajor, width: 4.2 }),
      minzoom: 6,
      filter: isMajor,
    },
    // 铁路（虚线）
    {
      dataLayer: 'transportation',
      symbolizer: new LineSymbolizer({ color: t.rail, width: 1.4, dash: [4, 3] }),
      minzoom: 8,
      filter: isRail,
    },
  ]
}

/**
 * 生成某个主题的标注规则。
 * 文字属性统一用 labelProps: ['name']（瓦片里地名/路名都存在 name）。
 *
 * @param t 主题配色
 * @param showRoads 是否绘制道路名。与 buildPaintRules 的 showRoads 保持一致：
 *   道路被隐藏时若仍画路名，会出现「名字浮在空白上」的怪象。默认 true。
 * @returns 标注规则数组；**调用方可用空数组表示「关闭注记」**（见 PmtilesLayer 的 showLabels）
 *
 * ⚠️ 2026-10-02 用户反馈「打开显示密密麻麻的地理名字，什么都看不清」。
 *    根因：下面 place 的规则**没有任何过滤**，把瓦片里 1.7 万个地名全标了出来
 *    （其中 hamlet 小村落 12607 个、isolated_dwelling 2590 个）—— 必然糊成一片。
 *    处置：默认**整个注记层关闭**（PmtilesLayer 的 showLabels 默认 false），
 *    由用户在右上角「图层」按钮里按需打开。这里保留全部规则，
 *    打开时即可用，不做删减。
 */
export function buildLabelRules(t: BasemapTheme, showRoads = true): LabelRule[] {
  const NAME_PROP = { labelProps: ['name'] }
  return [
    /* 地名：**z0 起**。
     * 2026-10-02 实测修正：原先写 minzoom:5，导致 z0~z4 完全没有文字 ——
     * 而这几级里 place 是唯一的图层，于是整屏空白（z1/z3 曾 0 个非背景像素）。
     * 低缩放只标大地方（isBigPlace），否则 1.7 万个 hamlet 会糊成一片。 */
    {
      dataLayer: 'place',
      symbolizer: new CenteredTextSymbolizer({
        ...NAME_PROP,
        fill: t.text,
        stroke: t.textHalo,
        width: 2,
        font: '500 12px sans-serif',
      }),
      maxzoom: 7,
      filter: isBigPlace,
    },
    /* 中小地名：z8 起。
     * ⚠️ 这条**没有过滤**，会把 place 图层全部要素都标出来（z8 有 1.4 万个，
     *    其中 hamlet 1.1 万）。这正是「密密麻麻什么都看不清」的直接来源。
     *    处置不在本文件 —— 见 PmtilesLayer 的 showLabels：**整层默认关闭**，
     *    用户从右上角「图层」按钮打开。若将来想让"打开时也不那么密"，
     *    应在这里补 filter（按 class 分级），而不是再去动默认开关。 */
    {
      dataLayer: 'place',
      symbolizer: new CenteredTextSymbolizer({
        ...NAME_PROP,
        fill: t.text,
        stroke: t.textHalo,
        width: 2,
        font: '500 11px sans-serif',
      }),
      minzoom: 8,
    },
    // 道路名：z12 起才显示，否则低层级下文字糊成一片。
    // showRoads=false 时一并隐藏：道路都不画了，路名浮在空白上会显得莫名。
    ...(showRoads ? [{
      dataLayer: 'transportation',
      symbolizer: new LineLabelSymbolizer({
        ...NAME_PROP,
        fill: t.text,
        stroke: t.textHalo,
        width: 2,
        font: '400 11px sans-serif',
      }),
      minzoom: 12,
    } as LabelRule] : []),
    // POI：z12 起画点
    {
      dataLayer: 'poi',
      symbolizer: new CircleSymbolizer({
        radius: 2.5,
        fill: t.poi,
        stroke: t.textHalo,
        width: 0.5,
      }),
      minzoom: 12,
    },
    // POI 名：z14 起
    {
      dataLayer: 'poi',
      symbolizer: new CenteredTextSymbolizer({
        ...NAME_PROP,
        fill: t.poi,
        stroke: t.textHalo,
        width: 2,
        font: '400 10px sans-serif',
      }),
      minzoom: 14,
    },
  ]
}

export const _internals = { readProp }
