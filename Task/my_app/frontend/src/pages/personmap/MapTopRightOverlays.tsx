/* 地图右上角的浮层列（2026-10-28 从 PersonMapView 抽出，行数纪律 AGENTS.md 三.2）
 *
 * 本文件只负责「把两个浮层纵向排好 + 统一绝对定位」，两个浮层自身只管卡片外观：
 *   · `LayerToggles`    —— 人员 / 默认站点 双图层开关（默认 开 / 关）；
 *   · `SiteClassLegend` —— 站点类别图例（维护分类 / VIP / HUB / 传输类型），
 *     默认一项都不选 → 地图上一个类别站点都不画。
 *
 * **为什么两者都必须在右上角**（2026-10-28 实测）：图例首版放左下角，
 * 门户嵌入（`?embed=1&mwembed=1`）下 `#main-content` 高度被钉在视口、
 * 地图容器实际被撑到 1122px，底部超出视口约 320px ——
 * 实测图例按钮中心 y=982 而视口高 805，**整块落在屏幕外，看不见也点不中**。
 * 右上角从 `top:12` 往下排，不受容器溢出影响。
 * 左上角被搜索框与 Leaflet 缩放控件占着，右下是版权条，故仍取右上。
 */
import { LayerToggles } from './LayerToggles'
import { SiteClassLegend } from './SiteClassLegend'
import type { useSiteClasses } from './useSiteClasses'

/** 图例那一整套状态（取自 `useSiteClasses()`）。用 ReturnType 而不是再抄一遍
 *  字段清单 —— 加字段时不必两处改。 */
type SiteClassesState = ReturnType<typeof useSiteClasses>

export function MapTopRightOverlays({
  showPeople, onPeopleChange,
  showTerritory, terrLoading, onTerrChange,
  siteClasses,
}: {
  showPeople: boolean
  onPeopleChange: (v: boolean) => void
  showTerritory: boolean
  terrLoading: boolean
  onTerrChange: (v: boolean) => void
  siteClasses: SiteClassesState
}) {
  return (
    /* 整列**同宽**（2026-10-28 用户要求「图例宽度能和上面的 people 按钮组件一致」）：
       列宽写死 `LEGEND_PANEL_W`，两个浮层都是 `stretch`（flex 子项默认拉伸到列宽），
       所以「人员 / 默认站点」开关卡与图例卡**左右边缘对齐**，不再是上下两张宽度
       不齐的卡片。宽度值取图例最长项（如 `Satellite Link 92`）刚好不换行的量。 */
    <div style={{
      position: 'absolute', right: 12, top: 12, zIndex: 1000,
      width: 220, display: 'flex', flexDirection: 'column', gap: 8,
      maxHeight: 'calc(100% - 24px)',
    }}>
      <LayerToggles
        peopleChecked={showPeople}
        onPeopleChange={onPeopleChange}
        terrChecked={showTerritory}
        terrLoading={terrLoading}
        onTerrChange={onTerrChange}
      />
      <SiteClassLegend
        groups={siteClasses.groups}
        loading={siteClasses.loading}
        error={siteClasses.error}
        selected={siteClasses.selected}
        onToggle={siteClasses.toggle}
        onClear={siteClasses.clear}
        shown={siteClasses.visibleSites.length}
        total={siteClasses.total}
        nf={siteClasses.nf}
        labelOf={siteClasses.labelOf}
      />
    </div>
  )
}
