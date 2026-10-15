import { useEffect } from 'react'
import { useMap } from '../../components/LeafletMap'

/* 地图视图控制器：center/zoom 变化时同步 setView。
 *
 * 2026-10-13（用户要求：「能把利比里亚的地图向左移动一点，避免被右边的统计遮挡」）：
 * 在 setView 之后追加一次**按容器像素**的平移，让地图内容整体左移。
 *
 * 为什么用 panBy（像素）而不是改 center 的经度：
 *   · 遮挡地图的是右边缘那两条浮层（区域排名条 .gis-rank-overlay、
 *     图层面板 #gis-layers-panel），它们的宽高由内容与 CSS 决定，
 *     与地图画布尺寸无关。用户要的是「地图内容让开固定的像素条」，
 *     这天然是像素语义；换算成经度还要经过 zoom → 米/像素 → 度 的链路，
 *     zoom 一档变化就得重算一遍系数，容易在改档位时悄悄失效。
 *   · panBy 是 Leaflet 的原生平移，缩放级别不变，只是把可见区往东挪
 *     （内容因此相对左移），右侧被浮层压住的部分随之减少，
 *     而不会像 setView 改中心那样顺带改变留白或触发缩放。
 *
 * ⚠️ 与 center 的耦合：平移是**相对**当前 center 的，所以每次 center/zoom
 *   变化（切时间预设、筛选后站点重心移动、改档位）都必须重算一次，
 *   否则平移量会在下一次 setView 时被抹掉。故下面两个步骤写在同一 effect 里。
 *
 * ⚠️ 平移量取固定像素而非容器宽度比例：门户中列画布实测 730×571，
 *   右浮层占约 243px。按比例算会在画布变宽时把地图推得过远 ——
 *   而浮层宽度并不随画布变宽，比例换算反而失真。 */
export function MapController({
  center, zoom, shiftWestPx = 0, shiftSouthPx = 0,
}: {
  center: [number, number]; zoom: number
  shiftWestPx?: number; shiftSouthPx?: number
}) {
  const map = useMap()
  useEffect(() => {
    map.setView(center, zoom)
    /* 符号（2026-10-13 实测标定，别凭直觉猜）：
       panBy 的偏移是「**视图中心**移动的向量」，不是「内容移动的向量」，
       两者方向相反。故：
         传**正** x → 视图中心东移 → **内容左移**；
         传**负** x → 视图中心西移 → **内容右移**。
       屏幕坐标实测（画布 730 宽）：
         panBy([-175,0]) → 站点 214..564 变成 302..652（内容**右移**）
         panBy([+205,0]) → 站点 112..462（内容**左移**）
       y 轴同理（2026-10-15 加，用户要求「地图向上平移」）：
         传**正** y → 视图中心南移 → **内容上移**；
         传**负** y → 视图中心北移 → **内容下移**。
       故调用方 shiftSouthPx 正数 = 内容上移，与本函数传给 panBy 的 y 同号。
       ⚠️ 2026-10-15：浮层由右侧换到左侧后，调用方 SHIFT_WEST_PX 已由 +205
          改为 **-73**（要内容右移、让开贴左缘的面板），故现在传进来的是负值。
          本函数只做透视平移，不含方向判断 —— 方向由调用方给的符号决定。

       animate=false：默认的平移动画在**每次** effect 重跑时都会播一遍
       （切档位、切筛选都会），观感是地图在「抖」。这里要的是一次性对位。
       先 setView 再 panBy 的顺序不能反：panBy 是相对当前视图的增量，
       若先平移后 setView，setView 会把平移重置回 center 原点。 */
    if (shiftWestPx || shiftSouthPx) {
      map.panBy([shiftWestPx, shiftSouthPx], { animate: false })
    }
  }, [center, zoom, shiftWestPx, shiftSouthPx, map])
  return null
}
