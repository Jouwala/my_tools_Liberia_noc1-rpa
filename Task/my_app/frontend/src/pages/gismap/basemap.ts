/* 底图（basemap）单一真相源
 *
 * ============ 2026-10-02 方案变更：改为自托管 PMTiles 矢量瓦片 ============
 *
 * 现状：底图用**内网自托管**的 PMTiles 文件（利比里亚全境，tilemaker 生成），
 * 经 nginx `/tiles/` 以 HTTP Range 分发，前端用 protomaps-leaflet 在 Leaflet
 * 1.9.4 上渲染矢量瓦片。**公网瓦片依赖已彻底移除**。
 *
 * 变更原因（这是整个改动的动机，勿删）：
 *   1. OSM 公共瓦片服务器的 usage policy 不鼓励 NOC 看板这种高频/长期使用；
 *   2. 深色主题原先靠 CSS invert 滤镜硬凑，副作用是 OSM 的深色公路/注记被反成
 *      亮白块，正是图例「深色下白底白字」问题的根因；
 *   3. 矢量瓦片可以**按主题给两套配色**，深色是真配色而非滤镜，问题 2 自然消失。
 *
 * 关键约束（改动本文件前必读）：
 *   - **URL 必须走 https://**。nginx 的 80 口 default_server 会 301 跳到 https
 *     （nginx.conf:109-114），用 http 会让每个瓦片多一次往返 —— 而 PMTiles 的
 *     瓦片是按 Range 分片取的，往返次数远多于栅格瓦片，代价被放大。
 *   - **不能用 protomaps 内置 flavor**（`flavor: 'light'` / `namedFlavor('dark')`）。
 *     内置 flavor 是按 OpenMapTiles/Protomaps schema 写的，引用 earth / roads_major /
 *     places_locality 等源图层名；而本项目 config-basic.json 产出的图层是
 *     place / transportation / water / waterway / poi / building，**实测仅 water 同名命中**
 *     （1/6）。用内置 flavor 会渲染出近乎空白的地图。故此处手写 paintRules/labelRules，
 *     配色与图层名一一对应自有 schema（见下方 LIGHT_THEME / DARK_THEME）。
 *   - **Feature.props 是普通对象，不是 Map**。写 `f.props.get('class')` 会抛
 *     "f.props.get is not a function"（只在运行时炸，tsc 与构建都发现不了），
 *     必须写 `f.props['class']`。统一走下面的 readProp()。
 *
 * 数据侧对应关系（改瓦片配置时需同步这里）：
 *   瓦片来源 D:\tiles-work\config-basic.json（tilemaker v2.4.0，z0–z14）
 *   服务位置 D:\01_RPA\nginx-1.28.0\html\tiles\liberia.pmtiles（nginx location ^~ /tiles/）
 *   注：z14 占 13786/19802 瓦片，故 MAX_ZOOM 取 14（不是 13）。
 */

/** PMTiles 归档地址。**必须 https**（理由见文件头「关键约束」）。 */
export const BASEMAP_PMTILES_URL = 'https://192.168.100.20/tiles/liberia.pmtiles'

/** 瓦片数据来源署名。数据是 OpenStreetMap 的，tilemaker 只做转换，署名义务不变。 */
export const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/** 自有瓦片的最大层级。由 config-basic.json 的 maxzoom 决定（z14 含 13786 个瓦片）。 */
export const BASEMAP_MAX_ZOOM = 14

/** 自有瓦片的最小层级 */
export const BASEMAP_MIN_ZOOM = 0

/* ------------------------------------------------------------------ *
 * 主题配色
 * ------------------------------------------------------------------ */

/** 单套主题的所有配色。字段即语义，勿在渲染逻辑里写死颜色。
 *
 *  ⚠️ `earth` / `park` / `boundary` 三个字段**当前没有被任何绘制规则使用** ——
 *  自由瓦片里没有对应的图层（config-basic.json 只有 place / transportation /
 *  water / waterway / poi / building）。保留它们是为了将来补这几层时不必改类型；
 *  但**不要**误以为改了它们界面会变。真正生效的字段见 pmtilesPaint.ts。 */
export type BasemapTheme = {
  background: string
  earth: string
  water: string
  waterway: string
  park: string
  building: string
  buildingOutline: string
  roadMajor: string
  roadMajorCasing: string
  roadMinor: string
  roadMinorCasing: string
  rail: string
  text: string
  textHalo: string
  poi: string
  boundary: string
}

/** 浅色主题（对齐项目既有浅色底图观感） */
export const LIGHT_THEME: BasemapTheme = {
  background: '#e8e4dc',
  earth: '#f4f1ea',
  water: '#a5c8e1',
  waterway: '#a5c8e1',
  park: '#d6e8cf',
  building: '#ddd6cc',
  buildingOutline: '#cfc6ba',
  roadMajor: '#ffffff',
  roadMajorCasing: '#d9d2c8',
  roadMinor: '#ffffff',
  roadMinorCasing: '#e2dcd2',
  rail: '#b8b0a4',
  text: '#333333',
  textHalo: '#ffffff',
  poi: '#6b7a8f',
  boundary: '#9aa4b2',
}

/** 深色主题。**这套是真配色，不是把浅色滤镜反相** —— 故不存在
 *  「深色公路被反成亮白」的老问题（旧 invert 方案的根因）。 */
export const DARK_THEME: BasemapTheme = {
  background: '#0a1428',
  earth: '#101d33',
  water: '#0b2036',
  waterway: '#123048',
  park: '#122a24',
  building: '#1a2740',
  buildingOutline: '#22314e',
  roadMajor: '#3d5680',
  roadMajorCasing: '#1c2b45',
  roadMinor: '#2b3d5c',
  roadMinorCasing: '#16233a',
  rail: '#3a4a66',
  text: '#c8d6ea',
  textHalo: '#0a1428',
  poi: '#8fa4c2',
  boundary: '#3f5478',
}

/** 取主题配色对象 */
export function basemapTheme(isDark?: boolean): BasemapTheme {
  return isDark ? DARK_THEME : LIGHT_THEME
}
