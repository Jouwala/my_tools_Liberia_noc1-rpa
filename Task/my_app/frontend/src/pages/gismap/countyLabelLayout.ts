/* 县名标注的动态避让（2026-10-14 新增）
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
 *     逐圈外扩，取第一个与已放置标签不冲突的位置。最多试 MAX_TRIES 轮，
 *     都失败就**放弃该标签**（宁可不显示，也不要叠成一团糊字）。
 *
 * 为什么不做成每帧重算（真·动态跟随缩放）：
 *   Leaflet 的 tooltip 位置由它自己在 setLatLng 时算，React 这边改不了
 *   （Tooltip 组件只暴露 permanent/direction/className，见 LeafletMap.tsx:73-80）。
 *   要真正跟随缩放，得拿到 map 实例、监听 zoomend 再把新坐标 setLatLng 回去 ——
 *   那需要在 LeafletMap 里新开一条命令式通道，改动面远大于本次收益。
 *   本页默认取景是**固定的全国视角**（LB_FIT_ZOOM=7，用户可手动缩放），
 *   故按「初始取景」算一次即可覆盖常态；缩放后可能重新出现少量重叠，
 *   但那时用户是在主动看局部，标签疏密本就不同。
 *   ⚠️ 这是**已知的、被接受的**局限，不要在没读完上面这段的情况下改成"每帧重算"。
 */
import type { CountyBoundary } from './types'

/** 标签预估尺寸（像素）。用于碰撞检测的包围盒。
 *  取值依据：.gis-county-tag 是 0.625rem(10px) 字 + 5px 色点 + 两位数字，
 *  实测最长的 "GRAND CAPE MOUNT ● 03" 约 118px 宽、14px 高。
 *  宁可估大一点：估小会让本来能分开的标签被判为不冲突。 */
const LABEL_W = 124
const LABEL_H = 16

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

/**
 * 计算所有要显示的县名标签的最终锚点。
 *
 * @param counties 全部县（含几何与告警数）
 * @param countOf  取告警数的函数（与地图填充、排名条同源）
 * @param proj     投影器（经纬度 ↔ 像素），由调用方按当前 zoom 构造
 * @returns 每个县一个标签，已错位；重叠无法解决的不返回
 */
export function placeCountyLabels(
  counties: CountyBoundary[],
  countOf: (c: CountyBoundary) => number,
  proj: Projector,
): PlacedLabel[] {
  // 只给「有告警」的县排标签 —— 与渲染条件保持一致，别给不画的县白占位
  const wanted = counties
    .map(c => ({ c, count: countOf(c), latlng: polygonCentroid(c.polygons) }))
    .filter(x => x.count > 0 && x.latlng)
    // 告警多的先占位（同数按名称，保证结果稳定可复现）
    .sort((a, b) => (b.count - a.count) || a.c.name.localeCompare(b.c.name))

  const placed: PlacedLabel[] = []
  const boxes: { x: number; y: number }[] = []   // 已占用的屏幕中心点

  /* 可视范围（像素）。标签**中心**必须落在这个区间内，才保证整个标签都在画面里：
     左右各留半个标签宽，上下各留半个标签高 —— 只夹中心点而不算半宽，
     标签仍会有一半骑在边界外，等于没夹。 */
  const minX = LABEL_W / 2
  const maxX = proj.size.width - LABEL_W / 2
  const minY = LABEL_H / 2
  const maxY = proj.size.height - LABEL_H / 2

  for (const item of wanted) {
    const [lat0, lng0] = item.latlng!
    const [px0, py0] = proj.to(lat0, lng0)

    for (const [ox, oy] of OFFSETS) {
      /* 先夹到画面内，再判冲突。
         顺序很关键：若先判冲突后夹取，夹取会把标签推回一个**已被占用**的位置，
         于是「不冲突」的结论失效。夹取在前，判的就是它真正落脚的位置。
         夹取本身可能让两个标签重叠（都被压到同一条边界上），
         所以夹完仍要走下面的冲突判定，冲突就换下一个候选位。 */
      const x = Math.min(maxX, Math.max(minX, px0 + ox * LABEL_W))
      const y = Math.min(maxY, Math.max(minY, py0 + oy * LABEL_H))
      // 与所有已放置标签做 AABB 相交判定（半宽 / 半高）
      const clash = boxes.some(b =>
        Math.abs(b.x - x) < LABEL_W * 0.92 && Math.abs(b.y - y) < LABEL_H * 1.05)
      if (clash) continue

      /* 屏幕像素 → 经纬度反投影，用等距近似（像素增量 × 度/像素）。
         本页取景跨度小（全国 ~4.4° 经 × 4.85° 纬），等距近似的误差远小于
         标签本身的尺寸，而这里只需要「挪开一点点」的精度。 */
      placed.push({
        name: item.c.name,
        lat: lat0 + (y - py0) * proj.degPerPx.y,
        lng: lng0 + (x - px0) * proj.degPerPx.x,
        count: item.count,
      })
      boxes.push({ x, y })
      break
    }
    /* 所有候选位都冲突 → 丢弃该标签（循环自然结束，不 push）。
       这是刻意的：用户要的是「不要重叠」，那么「少显示一个」优于「叠着显示两个」。
       15 个县里只有 11 个有标签，候选位足够，实测不会走到这里。 */
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
 * @param zoom     Leaflet 缩放级别（本页默认 LB_FIT_ZOOM=7）
 * @param width    画布宽度（像素）
 * @param latitude 取景中心纬度，用于经度方向的 cos 收缩
 */
export function makeProjector(
  zoom: number,
  width: number,
  latitude: number,
  height = 856,
): Projector {
  /* Web Mercator 在给定 zoom 下，世界像素宽 = 256 * 2^zoom，覆盖 360° 经度。
     纬度方向另乘 1/cos(lat) 才是对应度数（高纬度处同样的像素代表更多经度）。 */
  const worldPx = 256 * Math.pow(2, zoom)
  const degPerPxX = 360 / worldPx
  const degPerPxY = degPerPxX * Math.cos((latitude * Math.PI) / 180)

  return {
    // 原点取画布中线，避免大数值相减带来的浮点精度损失（这里只比相对距离）
    to: (lat, lng) => [
      width / 2 + (lng - LB_REF_LNG) / degPerPxX,
      height / 2 - (lat - latitude) / degPerPxY,
    ],
    degPerPx: { x: degPerPxX, y: degPerPxY },
    size: { width, height },
  }
}
