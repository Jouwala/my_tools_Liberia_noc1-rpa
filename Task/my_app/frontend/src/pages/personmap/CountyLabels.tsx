/* 县名标签层（2026-10-23 用户要求「地图显示县名」；2026-10-24 随
 * PersonMapView 拆分从该文件抽出，含避让 effect 与渲染）
 *
 * 三行内容：① 县名 + 站点总数；② 传输类型分组；③ 维护分类分组
 * （用户确认两类都要，展示规则见 useCountyTags.ts 的 TRM_ORDER 处注释）。
 *
 * 结构：零尺寸 Marker + permanent tooltip —— 照搬 GIS 页（挂 Polygon 上只能
 * 钉质心、无法避让，必须用可指定坐标的锚点，见 GISMap.tsx 同段落的说明）。
 * 样式复用 .gis-county-label（主题分档描边字，pointer-events:none 不拦
 * 地图点击）+ 本页专属 .person-county-tag（纵向排、小字号，见 index.css）。
 *
 * 避让：复用 GIS 页的 placeCountyLabels 算法（质心 + 屏幕像素贪心错位 +
 * 夹在画布内 + 锚点必须落在本县多边形内），不在本页另写一套。投影按
 * **初始全国取景**算一次，与 GIS 页同一取舍：选中人后地图会飞走，标签
 * 跟着县走（挂在经纬度上），不随缩放重排 —— 已知且接受，详见
 * countyLabelLayout.ts 文件头。
 *
 * 本组件是 MapContainer 的子组件，effect 执行时 map 已挂载，可直接
 * getSize()；不像 GIS 页那样喂固定常量（那边渲染期取不到 map，见
 * countyLabelLayout.ts 的说明，本页没有该时序约束，不沿用其近似值）。
 * countOf 取 site_count：站点多的县先占最正的质心位（GIS 页按告警数，
 * 本页没有那个口径）；包围盒用三行标签的 PERSON_LABEL_SIZE。
 */
import { useEffect, useState } from 'react'
import {
  Marker, Tooltip as MapTooltip, useMap, isMapAlive, Pane,
} from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import {
  placeCountyLabels, makeProjector, PERSON_LABEL_SIZE, type PlacedLabel,
} from '../gismap/countyLabelLayout'
import type { CountyBoundary } from '../gismap/types'

export function CountyLabels({
  counties, typeLines, center, zoom,
}: {
  counties: CountyBoundary[]
  /** 县名 → 两行统计文本（useCountyTags 的产出） */
  typeLines: Map<string, { trm: string; cat: string }>
  /** 初始全国取景：投影按它算一次。**必须是模块级常量**（引用相等性），
   *  理由见 PersonMapView 的 LB_CENTER 处注释。 */
  center: [number, number]
  zoom: number
}) {
  const { t } = useI18n()
  const map = useMap()
  const [labels, setLabels] = useState<PlacedLabel[]>([])

  /* counties 到位后按**真实画布尺寸**算一次避让。 */
  useEffect(() => {
    if (!isMapAlive(map) || !counties.length) return
    const size = map.getSize()
    const proj = makeProjector(zoom, size.x, center[0], size.y, 0)
    setLabels(placeCountyLabels(counties, c => c.site_count || 0, proj, PERSON_LABEL_SIZE))
  }, [map, counties, center, zoom])

  return (
    <>
      {/* 县名标签的 pane（z-index 670，与 GIS 页同一层级链：
          overlay 400 < tooltip 650 < countyLabel 670 < personPane 680 < popup 700）——
          标签要压住县块填充，但不能压人员针；**必须显式声明**：若让 Tooltip 的
          兜底 createPane 建，pane 拿不到 z-index，会掉到 overlay 之下
          （2026-10-21 实测教训，详见 PersonMapView 的 `<Pane>` 处注释）。 */}
      <Pane name="countyLabelPane" style={{ zIndex: 670 }} />

      {labels.map(lb => {
        const lines = typeLines.get(lb.name)
        return (
          <Marker
            key={`county-lb-${lb.name}`}
            position={[lb.lat, lb.lng]}
            interactive={false}
          >
            <MapTooltip permanent direction="center" className="gis-county-label"
                        pane="countyLabelPane">
              <span className="gis-county-tag person-county-tag"
                    title={t('person.countyTagTip', { name: lb.name, total: lb.count })}>
                <span className="person-county-tag__head">
                  <span className="gis-county-tag__name">{lb.name.toUpperCase()}</span>
                  <span className="gis-county-tag__num">{lb.count}</span>
                </span>
                {lines?.trm && <span className="person-county-tag__row">{lines.trm}</span>}
                {lines?.cat && <span className="person-county-tag__row">{lines.cat}</span>}
              </span>
            </MapTooltip>
          </Marker>
        )
      })}
    </>
  )
}
