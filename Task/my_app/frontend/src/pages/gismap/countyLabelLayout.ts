/* 县名标注的动态避让（2026-10-14 新增；2026-10-23 两项修正见下）
 *
 * 背景（用户 2026-10-14）：「Label 重叠 ⚠️ 有 —— 需要动态避让」。
 *
 * 重叠的根因不在标签样式，而在**锚点**：本页用 Leaflet 的 permanent tooltip，
 * 它把每个标签钉在各自多边形的**质心**上，且**完全没有碰撞检测** ——
 * Leaflet 把画标的责任全交给调用方。利比里亚的县大小极不均衡
 * （贴海那几个县很小，内陆的 Nimba / Grand Gedeh 很大），质心之间经常
 * 只隔十几像素，于是 `MONTSERRADO ● 07` 与 `MARGIBI ● 03` 直接叠在一起。
 *
 * 方案：**在经纬度空间做一遍贪心错位，再交给 Leaflet 画**。
 *  1. 顺序按告警数降序 —— 最痛的县先占位，保证它拿到最正的质心位置；
 *     后面的县让路。这与「排名条」的排序同源，两处读到的优先级一致。
 *  2. 冲突判定在**屏幕像素**空间做，不是在经纬度空间：经度 1° ≈ 111km×cos(纬度)，
 *     而纬度 1° ≈ 111km，同一个度数在横竖两个方向的视觉宽度不同；
 *     用度数判冲突会让东西向的标签叠得更狠。
 *  3. 每个标签按固定的候选方向序列（质心 → 上 → 下 → 右 → 左 → 斜角…）
 *     逐圈外扩，取第一个与已放置标签不冲突的位置。
 *
 * 2026-10-23 修正一：**候选位必须落在本县多边形内**（用户报
 * 「标签没有在州里面显示」）。原先只顾躲开别的标签，不管是否还站在自己县里，
 * 于是零告警、最后占位的县（SINOE / MARYLAND）被推到邻县地盘上，与邻县标签
 * 竖着摞在一起。射线法点在多边形判定见 pointInPolygons。
 * 兜底链：县内且无冲突 → 县内（接受冲突，宁可在自己县里叠着也不漂出去）→
 * 质心原位（极端几何下的最后落点）。原「全部候选位冲突就丢弃标签」的规则
 * 随之作废 —— 用户此刻要的是「每个县的标签都在自己县里」，丢标签与之相悖。
 *
 * 2026-10-23 修正二：**投影空间必须与真实渲染一致**。调用方原先写死
 * 「门户中列 570×856 + 档位 zoom」，而实际内嵌画布 ~898px：zoom 8 下国土在
 * 投影里需要 ~800px，570 宽的假画布把东部各县的候选位全夹到右缘同一列，
 * 在假坐标里判出假冲突、把标签摞到假位置。现在 GISMap 通过 MapMetrics
 * （ResizeObserver + zoomend）实测容器尺寸与真实 zoom 喂进来，
 * 本模块的像素从此就是屏幕像素；顺带解决了「手动缩放后标签错位」的旧局限
 * （zoomend 会触发重算，下面的「固定取景算一次」段落只余历史意义）。
 */
import type { CountyBoundary } from './types'

/** 标签预估尺寸（像素）。用于碰撞检测的包围盒。
 *  取值依据：.gis-county-tag 是 0.625rem(10px) 字 + 5px 色点 + 两位数字，
 *  实测最长的 "GRAND CAPE MOUNT ● 03" 约 118px 宽、14px 高。
 *  宁可估大一点：估小会让本来能分开的标签被判为不冲突。
 *  2026-10-23 起无告警的县是「纯县名」标签，实际比该上界窄 ~30px ——
 *  继续用同一上界估，对它们只是判得保守（多让一点位），不会漏判重叠。 */
const LABEL_W = 124
const LABEL_H = 16

/** 人员页三行标签（县名+总数 / 传输分组 / 维护分组，2026-10-23）的包围盒。
 *  GIS 页单行标签继续用上面的默认值；本尺寸只由 placeCountyLabels 的
 *  可选参数 size 传入，不改变任何既有调用方的行为。
 *  宽按最坏类型行估："MW 88 · SAT 8 · ST 4 · IPRAN 3 · — 2" ≈ 165px；
 *  高 = 名行 16 + 两个 9px 小行 ≈ 44。沿用「宁可估大」：估大了只是多让位。 */
export const PERSON_LABEL_SIZE = { w: 170, h: 44 } as const

/** 候选偏移序列，单位是**标签尺寸的倍数**（x = 横向，y = 纵向）。
 *  第 0 项 (0,0) 即质心原位。之后按「先上下、再左右、最后对角」的次序外扩 ——
 *  上下优先是因为本页标签默认横排，垂直方向挪动不会让标签盖住县界本身。 */
const OFFSETS: [number, number][] = [
  [0, 0],
  [0, -1.1], [0, 1.1],
  [1.05, 0], [-1.05, 0],
  [1.05, -1.1], [-1.05, -1.1], [1.05, 1.1], [-1.05, 1.1],
  [0, -2.2], [0, 2.2],
  [1.05, -2.2], [-1.05, -2.2], [1.05, 2.2], [-1.05, 2.2],
  [0, -3.3], [0, 3.3],
  [1.05, -3.3], [-1.05, -3.3], [1.05, 3.3], [-1.05, 3.3],
]

export interface PlacedLabel {
  /** 县名（保持原大小写，展示时由调用方 toUpperCase） */
  name: string
  /** 避让后的锚点 [lat, lng] */
  lat: number
  lng: number
  count: number
  /* 曾有一个 `color` 字段（分档色），用于渲染标签里的色点。
     2026-10-14 用户要求「去掉标签背景，只显示 BOMI.01」，色点随之去掉 ——
     色点表达的严重度在**县块填充色**上已经有了，同图重复编码两遍是冗余。
     字段与其入参 colorOf 一并删除（AGENTS.md 原则 10：删除优于兼容）。 */
}

/** 投影器：经纬度 ↔ 屏幕像素。由调用方按**当前地图 zoom** 构造。
 *  做成显式参数而不是模块级变量，是为了让 placeCountyLabels 保持纯函数 ——
 *  纯函数才能被安全地放进 useMemo，也才不会在两次调用之间互相串值。 */
export interface Projector {
  /** 经纬度 → [x, y] 像素 */
  to(lat: number, lng: number): [number, number]
  /** 每像素对应多少经度 / 纬度（用于把像素位移换算回经纬度） */
  degPerPx: { x: number; y: number }
  /** 画布尺寸（像素）。用于**把标签挡在地图可视范围内** ——
   *  2026-10-14 用户报「BOMI 跑到地图外面了」，根因就是当时的算法只顾
   *  躲开别的标签，完全不看自己是否被推出了画面。 */
  size: { width: number; height: number }
}

/** 多边形质心。用**面积加权**而不是顶点平均：
 *  顶点的疏密取决于 GeoJSON 的采样精度，顶点平均会被采样密的一侧拽偏
 *  （本页县界顶点分布很不均匀，直接平均会让标签偏出县外）。 */
function polygonCentroid(polygons: [number, number][][]): [number, number] | null {
  let best: { area: number; lat: number; lng: number } | null = null
  for (const ring of polygons) {
    if (!ring || ring.length < 3) continue
    let a = 0, cx = 0, cy = 0
    for (let i = 0, n = ring.length; i < n; i++) {
      const [y0, x0] = ring[i]
      const [y1, x1] = ring[(i + 1) % n]
      const cross = x0 * y1 - x1 * y0
      a += cross
      cx += (x0 + x1) * cross
      cy += (y0 + y1) * cross
    }
    a *= 0.5
    if (Math.abs(a) < 1e-12) continue
    const lat = cy / (6 * a)
    const lng = cx / (6 * a)
    // 取**面积最大**的一环作为主岛：MultiPolygon 里的小岛屿不该当锚点
    if (!best || Math.abs(a) > best.area) best = { area: Math.abs(a), lat, lng }
  }
  if (!best) return null
  return [best.lat, best.lng]
}

/** 避让候选位的落点：投影像素坐标（x, y，供冲突判定与占用记录）
 *  加反投影回的经纬度（lat, lng，供县内判定与最终锚点）。 */
type Candidate = { x: number; y: number; lat: number; lng: number }

/** 射线法（PNPOLY）：点是否落在任一环内。环的坐标是 [lat, lng]（Leaflet 约定）。
 *  用途：约束避让候选位必须站在**本县**地盘上 —— 县与县不重叠，
 *  「在本县内」这一条就把「标签漂到邻县」从几何上排除了。 */
function pointInPolygons(lat: number, lng: number, polygons: [number, number][][]): boolean {
  for (const ring of polygons) {
    if (!ring || ring.length < 3) continue
    let inside = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [yi, xi] = ring[i]
      const [yj, xj] = ring[j]
      if ((yi > lat) !== (yj > lat) &&
        lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
        inside = !inside
      }
    }
    if (inside) return true
  }
  return false
}

/**
 * 计算所有要显示的县名标签的最终锚点。
 *
 * @param counties 全部县（含几何与告警数）
 * @param countOf  取告警数的函数（与地图填充、排名条同源）
 * @param proj     投影器（经纬度 ↔ 像素），由调用方按**真实画布**当前 zoom 构造
 * @param size     标签包围盒（像素）。缺省 = GIS 页单行标签的 LABEL_W/H；
 *                 人员页三行标签传 PERSON_LABEL_SIZE
 *                 （2026-10-23 加，是本模块第二个真实用例，故参数化尺寸而非复制算法）
 * @returns 每个县一个标签，已错位且锚点在本县多边形内
 */
export function placeCountyLabels(
  counties: CountyBoundary[],
  countOf: (c: CountyBoundary) => number,
  proj: Projector,
  size: { w: number; h: number } = { w: LABEL_W, h: LABEL_H },
): PlacedLabel[] {
  const labelW = size.w
  const labelH = size.h
  // 全部县都排标签（2026-10-23 用户要求「标签默认显示县名」）：无告警的县
  // 也要有「只有名字」的标签位，数字是否拼接由渲染端按 count>0 决定。
  // 排序仍按告警数降序 —— 最痛的县先占最正的质心位，无告警的县最后落位、
  // 只能拿被挑剩的偏移位（同数按名称，保证结果稳定可复现）。
  const wanted = counties
    .map(c => ({ c, count: countOf(c), latlng: polygonCentroid(c.polygons) }))
    .filter(x => x.latlng)
    .sort((a, b) => (b.count - a.count) || a.c.name.localeCompare(b.c.name))

  const placed: PlacedLabel[] = []
  const boxes: { x: number; y: number }[] = []   // 已占用的屏幕中心点

  /* 可视范围（像素）。标签**中心**必须落在这个区间内，才保证整个标签都在画面里：
     左右各留半个标签宽，上下各留半个标签高 —— 只夹中心点而不算半宽，
     标签仍会有一半骑在边界外，等于没夹。 */
  const minX = labelW / 2
  const maxX = proj.size.width - labelW / 2
  const minY = labelH / 2
  const maxY = proj.size.height - labelH / 2

  for (const item of wanted) {
    const [lat0, lng0] = item.latlng!
    const [px0, py0] = proj.to(lat0, lng0)

    // chosen：县内且无冲突；insideFallback：县内但冲突（兜底，宁在本县叠着也不漂走）
    let chosen: Candidate | null = null
    let insideFallback: Candidate | null = null

    for (const [ox, oy] of OFFSETS) {
      /* 先夹到画面内，再判「在本县内」与冲突。
         顺序很关键：若先判冲突后夹取，夹取会把标签推回一个**已被占用**的位置，
         于是「不冲突」的结论失效。夹取在前，判的就是它真正落脚的位置。 */
      const x = Math.min(maxX, Math.max(minX, px0 + ox * labelW))
      const y = Math.min(maxY, Math.max(minY, py0 + oy * labelH))
      /* 屏幕像素 → 经纬度反投影，用等距近似（像素增量 × 度/像素）。
         本页取景跨度小（全国 ~4.4° 经 × 4.85° 纬），等距近似的误差远小于
         标签本身的尺寸，而这里只需要「挪开一点点」的精度。 */
      const lat = lat0 + (y - py0) * proj.degPerPx.y
      const lng = lng0 + (x - px0) * proj.degPerPx.x

      /* 2026-10-23 用户要求「标签要显示在州里面」：候选位必须在本县多边形内。
         放在冲突判定**之前** —— 漂到邻县的候选位再「空」也不能要。 */
      if (!pointInPolygons(lat, lng, item.c.polygons)) continue

      // 与所有已放置标签做 AABB 相交判定（半宽 / 半高）
      const clash = boxes.some(b =>
        Math.abs(b.x - x) < labelW * 0.92 && Math.abs(b.y - y) < labelH * 1.05)
      if (!clash) {
        chosen = { x, y, lat, lng }
        break
      }
      if (!insideFallback) insideFallback = { x, y, lat, lng }
    }

    if (chosen || insideFallback) {
      const p = (chosen ?? insideFallback)!
      placed.push({ name: item.c.name, lat: p.lat, lng: p.lng, count: item.count })
      boxes.push({ x: p.x, y: p.y })
      continue
    }

    /* 所有候选位都在本县外（多边形太碎、质心本身出界等极端几何）：
       退回质心原位。标签总得有个落点 —— 可见性优先于几何完美；
       与修正一的兜底链同理，「丢弃标签」的旧规则已按用户要求作废。 */
    placed.push({ name: item.c.name, lat: lat0, lng: lng0, count: item.count })
    boxes.push({ x: px0, y: py0 })
  }

  return placed
}

/** 利比里亚国土经度中心，仅作投影原点的参考值（与 GISMap 的 LB_CENTER 同源）。
 *  它不影响任何**相对**距离的判定 —— 像素坐标在这里只用于比较远近。 */
const LB_REF_LNG = -9.5

/**
 * 按 Web Mercator + 给定 zoom 构造投影器。
 *
 * 之所以不直接用 Leaflet 的 map.latLngToContainerPoint：
 *   那需要拿到 map 实例，而本函数的调用点在渲染期（useMemo），
 *   此时地图未必已挂载完成（LeafletMap 的容器身份与 React 挂载周期对齐，
 *   见 LeafletMap.tsx:362-373 的记载）。自己算 mercator 既没有该时序问题，
 *   也便于单测 —— 这里只需要「相对距离」，不需要与 Leaflet 逐像素一致。
 *
 * @param zoom     Leaflet 缩放级别（由调用方传**地图真实 zoom**，见 MapMetrics）
 * @param width    画布宽度（像素）——调用方传**实测容器宽**，写死值会让夹取失真
 * @param latitude 取景中心纬度，用于经度方向的 cos 收缩
 * @param height   画布高度（像素）——同 width，传实测值
 * @param shiftWestPx 地图**西移量**（2026-10-13 新增）：正值 = 内容整体左移了这么多像素
 *                （对应 GISMap 的 SHIFT_WEST_PX + MapController 的 panBy）。
 *
 *   ⚠️ 为什么投影器必须知道这个平移量：
 *   投影器的「画布中线」假设地图中心 = `latitude` 所在的点。但本页为了避开
 *   右侧浮层，会在 setView 之后 panBy 把内容往左推 —— 此时画面中心已经不是
 *   这个点了，而**标签锚点若仍按「未平移」算 lat/lng**，落地后会整体偏离，
 *   与站点圆点脱节（站点与标签是两条独立链路：站点由 Leaflet 自己按平移摆放，
 *   标签由本模块先算好 lat/lng 再交给 Leaflet）。
 *   把平移量喂进来，`to()` 才会算出「平移之后」的真实像素位置，
 *   「夹在可视范围内」的判定也才成立。
 *
 *   约定：**正值 = 内容左移**，所以像素 x 要**减去**平移量 ——
 *   即「未平移时在 px 的东西，平移后出现在 px - shiftWestPx」。
 */
export function makeProjector(
  zoom: number,
  width: number,
  latitude: number,
  height = 856,
  shiftWestPx = 0,
  shiftSouthPx = 0,
): Projector {
  /* Web Mercator 在给定 zoom 下，世界像素宽 = 256 * 2^zoom，覆盖 360° 经度。
     纬度方向另乘 1/cos(lat) 才是对应度数（高纬度处同样的像素代表更多经度）。 */
  const worldPx = 256 * Math.pow(2, zoom)
  const degPerPxX = 360 / worldPx
  const degPerPxY = degPerPxX * Math.cos((latitude * Math.PI) / 180)

  return {
    // 原点取画布中线，避免大数值相减带来的浮点精度损失（这里只比相对距离）
    to: (lat, lng) => [
      // 西移 = 内容左移 = x 变小，故减
      width / 2 + (lng - LB_REF_LNG) / degPerPxX - shiftWestPx,
      // 南移量语义与 shiftWestPx 对称（2026-10-23 补）：调用方 shiftSouthPx
      // 正数 = 内容上移 = y 变小，故同样减。原先漏了这一维，v2 内嵌
      // （SHIFT_SOUTH_PX=-26）时夹取范围整体偏了 26px。
      height / 2 - (lat - latitude) / degPerPxY - shiftSouthPx,
    ],
    degPerPx: { x: degPerPxX, y: degPerPxY },
    /* size 是**平移之后**的真实可视范围：内容左移后，原来贴右缘的东西
       还在画布内（只是位置变了），而画布**左缘**相对内容向右收进了 shiftWestPx。
       即：内容坐标 x 的有效区间是 [shiftWestPx, shiftWestPx + width]。
       这里把 size 的 width 保持原值即可 —— placeCountyLabels 只用它夹
       [半宽, width-半宽]，而 to() 已经减掉了 shiftWestPx，两者配合起来
       等价于「内容坐标下夹在 [半宽+shift, width-半宽+shift]」，
       正是平移后的正确可视区间。 */
    size: { width, height },
  }
}
