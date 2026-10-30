/* 县名标签层（2026-10-23 用户要求「地图显示县名」；2026-10-24 随
 * PersonMapView 拆分从该文件抽出，含避让 effect 与渲染）
 *
 * 常驻**单行**：县名 + 站点总数。传输类型 / 维护分类两行统计收进**悬停展开**
 * （2026-10-29 用户在实测重叠数据后选定；两类内容本身仍都要，展示规则见
 * useCountyTags.ts 的 TRM_ORDER 处注释）。
 *
 * 结构：零尺寸 Marker + permanent tooltip —— 照搬 GIS 页（挂 Polygon 上只能
 * 钉质心、无法避让，必须用可指定坐标的锚点，见 GISMap.tsx 同段落的说明）。
 * 样式复用 .gis-county-label（pointer-events:none 不拦地图点击）+ 本页专属
 * .person-county-label（深蓝无描边）与 .person-county-tag，见 index.css。
 *
 * ⚠ 悬停展开要求标签本身可命中：`.person-county-tag` 显式 `pointer-events: auto`
 *   把外层 tooltip 的 none 关掉（子元素可反向开启）。命中区只有文字那一小条，
 *   且人员针在 personPane(680) 高于 countyLabelPane(670) —— 针压在标签上时
 *   仍是针先收到点击，不会像 2026-10-21 县界多边形那样成片拦掉命中。
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
 * 本页没有那个口径）；包围盒用 countyLabelLayout 的默认 LABEL_W/LABEL_H
 * （本页已改单行，与 GIS 页同档）。
 */
import { useEffect, useState } from 'react'
import {
  Marker, Tooltip as MapTooltip, useMap, isMapAlive, Pane,
} from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import {
  placeCountyLabels, makeProjector, type PlacedLabel,
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
    /* 不传 size → 用模块默认的 LABEL_W/LABEL_H：2026-10-29 起本页也是**单行**标签
       （统计收进悬停），尺寸档与 GIS 页一致，没必要再维护第二套包围盒。 */
    setLabels(placeCountyLabels(counties, c => c.site_count || 0, proj))
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
        const hasDetail = !!(lines?.trm || lines?.cat)
        return (
          <Marker
            key={`county-lb-${lb.name}`}
            position={[lb.lat, lb.lng]}
            interactive={false}
          >
            {/* `person-county-label`（2026-10-29 用户指定「深蓝文字」，并二次反馈
                「不要白色阴影」）：本页县块是 80% 实心填充，标签恒压在饱和县色上，
                故深蓝可深浅主题同一套、且无描边无阴影。GIS 页填充仍 0.13、底图随主题
                反相，那边保留描边分档。取舍与**必须写两条选择器**的特异性坑见 index.css。 */}
            <MapTooltip permanent direction="center" className="gis-county-label person-county-label"
                        pane="countyLabelPane">
              {/* 常驻**只有单行**「县名 + 总数」（2026-10-29 用户在重叠实测数据前选定）。
                  两行统计收进悬停才展开的 `.person-county-tag__detail`：常驻三行时
                  包围盒 190×51，西海岸三县实测 8 对重叠（最严重 113×51 = 整块压住）；
                  单行 190×22 与 GIS 页同档，那边同字号实测 0 重叠。
                  aria-label 保留可访问性说明（不用 title —— 会与原生气泡打架）。 */}
              <span className="gis-county-tag person-county-tag"
                    aria-label={t('person.countyTagTip', { name: lb.name, total: lb.count })}>
                <span className="person-county-tag__head">
                  <span className="gis-county-tag__name">{lb.name.toUpperCase()}</span>
                  <span className="gis-county-tag__num">{lb.count}</span>
                </span>
                {hasDetail && (
                  <span className="person-county-tag__detail">
                    {lines?.trm && <span className="person-county-tag__row">{lines.trm}</span>}
                    {lines?.cat && <span className="person-county-tag__row">{lines.cat}</span>}
                  </span>
                )}
              </span>
            </MapTooltip>
          </Marker>
        )
      })}
    </>
  )
}
