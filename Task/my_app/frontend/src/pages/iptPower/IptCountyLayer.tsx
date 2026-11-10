/* IPT 电源页的县底色 + 县名标签图层（?page=ipt_power）
 *
 * **需求**（2026-11-09 用户原话）：「里面的地图按照州添加颜色，参考 ?page=person」。
 * 人员页的地图是 **15 个县各一种类别色、80% 实心填充 + 县名标签**；本页此前默认
 * 只有一张素底图 + 圆点（原「平均 SOC 分档底色」开关 2026-11-08 起默认关），
 * 两种观感差距很大。故本图层提供两种互斥的着色口径：
 *   · `category`（**默认**）：逐县类别色，色表与人员页**共用同一份**
 *     `gismap/countyPalette.ts`（不是抄一份），并按同一套避让算法标县名 + 站点数；
 *   · `soc`（原功能）：该县有 SOC 快照站点的算术平均分档色（≥80 绿 / 60~80 黄 /
 *     <60 红 / 样本不足灰），透明度与 tooltip 沿用 2026-11-06 那版口径；
 *   · `none`：调用方**不挂载**本组件，回到完全的素底图。
 *
 * **为什么两种模式共用一个 Polygon 层**：县块是整面可 hover 的 SVG，画两层会
 * 互相盖住并抢 tooltip；用 `pathOptions` 就地换色（LeafletMap 的 setStyle）就够了，
 * 切模式不会重建图层、地图不闪、标签避让结果也不跟着重算。
 *
 * ⚠ 层级链（照人员页 / GIS 页同一套，别省 `<Pane>`）：
 *   县块 overlayPane(400) < 站点圆点 iptSitePane(650) < 县名标签 iptCountyLabelPane(670)。
 *   标签虽在圆点之上，但 `.gis-county-label` 有 `pointer-events:none`、承载它的
 *   `Marker` 是 `interactive={false}`，点圆点开抽屉不会被标签截走（人员页 2026-10-21
 *   踩过「县界多边形成片拦掉命中」的坑，这里从一开始就不给它命中能力）。
 *
 * ⚠ 县界数据与 GIS 页 / 人员页共用同一份 `/gis/county-boundaries`（静态 GeoJSON，
 *   后端 1 小时缓存 + 前端 `cachedGet` 30s），同一个缓存键意味着进过那两页的用户
 *   本页这次取数免费。本组件全页只取数一次，多边形与标签共用，别再拆成两个组件。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Marker, Pane, Polygon, Tooltip, Tooltip as MapTooltip, useMap, isMapAlive,
} from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import api from '../../api'
import { cachedGet } from '../../cache'
import type { CountyBoundary } from '../gismap/types'
import {
  COUNTY_CATEGORY_OPACITY, countyCategoryColors,
} from '../gismap/countyPalette'
import {
  placeCountyLabels, makeProjector, type PlacedLabel,
} from '../gismap/countyLabelLayout'
import {
  COUNTY_FILL_OPACITY, SOC_BAND_COLOR, bandLabelKey, type CountySoc, type SocBand,
} from './countySoc'

export type IptCountyMode = 'category' | 'soc'

const LABEL_PANE = 'iptCountyLabelPane'
const LABEL_PANE_Z = 670
/** 取不到类别色（异常：县数超色表）时的中性灰，与人员页 `CountyLayer` 同值 */
const FALLBACK_COLOR = '#9aa5b5'

export function IptCountyLayer({
  stats, mode, isDark, center, zoom,
}: {
  /** 县名 → 该县在当前站点集合里的 SOC 统计；由页面按**当前地图上的站点**算出 */
  stats: Map<string, CountySoc>
  mode: IptCountyMode
  isDark: boolean
  /** 初始全国取景，标签避让按它算一次。**必须是模块级常量**（引用相等性），
   *  理由见 `PersonMapView.tsx` 的 LB_CENTER 注释。 */
  center: [number, number]
  zoom: number
}) {
  const { t } = useI18n()
  const map = useMap()
  const [counties, setCounties] = useState<CountyBoundary[]>([])
  const [labels, setLabels] = useState<PlacedLabel[]>([])

  useEffect(() => {
    let alive = true
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => { if (alive) setCounties(res.data?.counties || []) })
      .catch(err => {
        // 不静默：县界拉不到时底色整层不画，但控制台要留下原因
        // （静默失败会让人以为「这个县就是没颜色」）
        console.error('[ipt_power] county boundaries failed:',
          err?.response?.status, err?.response?.data || err)
        if (alive) setCounties([])
      })
    return () => { alive = false }
  }, [])

  /* 县 → 类别色：与 ?page=person 逐县同色（同一份色表 + 同一排序规则）。 */
  const categoryColor = useMemo(() => countyCategoryColors(counties), [counties])

  /* 县名标签避让：复用 GIS 页 `placeCountyLabels`，按**初始全国取景**算一次。
     · 优先级用 GeoJSON 自带的 `site_count`（静态值），不用当前筛选后的站点数 ——
       否则搜索框每改一个字，标签的排布就重排一次，视觉上会跳；
     · 投影按真实画布尺寸算（map.getSize()），不写死「门户中列 570×856」那套近似值
       （countyLabelLayout.ts 文件头记着写死值导致的错位事故）；
     · 与人员页一致：手动缩放后标签跟着县走，不随缩放重排。 */
  useEffect(() => {
    if (!isMapAlive(map) || !counties.length) return
    const size = map.getSize()
    const proj = makeProjector(zoom, size.x, center[0], size.y, 0)
    setLabels(placeCountyLabels(counties, c => c.site_count || 0, proj))
  }, [map, counties, center, zoom])

  const categoryOpacity = isDark ? COUNTY_CATEGORY_OPACITY.dark : COUNTY_CATEGORY_OPACITY.light
  const socOpacity = isDark ? COUNTY_FILL_OPACITY.dark : COUNTY_FILL_OPACITY.light

  const shapes = useMemo(
    () => counties.map(c => {
      const stat = stats.get(c.name)
      const sites = stat?.sites ?? 0
      const band: SocBand = stat?.band ?? 'few'
      const color = mode === 'category'
        ? (categoryColor.get(c.name) || FALLBACK_COLOR)
        : SOC_BAND_COLOR[band]
      return {
        c, stat, sites, band, color,
        /* 分类模式：15 个县一律实心，哪怕当前筛选下该县一个站都没有（人员页同口径）；
           SOC 模式：无站点只描边不填色，避免灰填充和「样本不足」档混淆。 */
        fillOpacity: mode === 'category' ? categoryOpacity : (sites > 0 ? socOpacity : 0),
      }
    }),
    [counties, stats, mode, categoryColor, categoryOpacity, socOpacity],
  )

  return (
    <>
      {/* 标签 pane 必须显式声明并给 z-index：Leaflet 的兜底 createPane 不设 z-index，
          新建 pane 会掉到 overlayPane 之下，标签被县块整片盖住（人员页 2026-10-21 实测）。 */}
      <Pane name={LABEL_PANE} style={{ zIndex: LABEL_PANE_Z }} />

      {shapes.map(({ c, stat, sites, band, color, fillOpacity }) => (
        <Polygon
          key={`ipt-county-${c.name}`}
          positions={c.polygons as any}
          pathOptions={{
            color, fillColor: color, fillOpacity,
            weight: 1.5, opacity: 0.85, dashArray: '4 3',
          }}
        >
          {/* 非永久 tooltip：鼠标停到县块上才出。两种模式给不同的文案 ——
              分类模式下颜色表达「这是哪个县」，再去讲分档名会让人误读色义。 */}
          <Tooltip direction="center">
            {sites === 0
              ? t('ipt.county.tipEmpty', { name: c.name })
              : mode === 'category'
                ? t('ipt.county.tipByCounty', {
                  name: c.name,
                  sites,
                  soc: stat?.avg == null ? '-' : `${(stat.avg * 100).toFixed(1)}%`,
                })
                : t('ipt.county.tip', {
                  name: c.name,
                  soc: `${((stat?.avg ?? 0) * 100).toFixed(1)}%`,
                  samples: stat?.samples ?? 0,
                  sites,
                  band: t(bandLabelKey(band)),
                })}
          </Tooltip>
        </Polygon>
      ))}

      {labels.map(lb => (
        <Marker key={`ipt-county-lb-${lb.name}`} position={[lb.lat, lb.lng]} interactive={false}>
          <MapTooltip permanent direction="center"
            className="gis-county-label ipt-county-label" pane={LABEL_PANE}>
            {/* 单行「县名 + 当前筛选下的站点数」，和人员页的标签同一结构、同一 CSS 族。
                数字用 `stats`（动态）而不是 `lb.count`（GeoJSON 静态站点数）：
                本页县的站点数就是 IPT 站点数，搜索词一改要跟着变才与画面一致。 */}
            <span className="gis-county-tag ipt-county-tag">
              <span className="gis-county-tag__name">{lb.name.toUpperCase()}</span>
              <span className="gis-county-tag__num">{stats.get(lb.name)?.sites ?? 0}</span>
            </span>
          </MapTooltip>
        </Marker>
      ))}
    </>
  )
}
