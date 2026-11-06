/* 县底色图层（?page=ipt_power，2026-11-06 新增）
 *
 * 画 15 个县的**平均 SOC 分档底色**。县界数据与 GIS 页/人员页共用同一份
 * `/gis/county-boundaries`（静态 GeoJSON，后端 1 小时缓存 + 前端 `cachedGet` 30s），
 * 同一个缓存键意味着用户只要进过那两页，本页这次取数就是免费的。
 *
 * 为什么单独成文件：`IptPowerQuery.tsx` 已经 670+ 行（AGENTS.md 三.2 的 500 行纪律，
 * 存量超限的文件改到时只能收不能胀），图层与档位计算各自拆出，页面只留「开关 + 图例」。
 *
 * ⚠ 县块画在**默认 overlayPane(400)**，站点圆点被调用方抬到 `iptSitePane(650)`
 *   （见 `IptPowerQuery.tsx` 里 `<Pane name="iptSitePane">`，同 `GISMap.tsx:2808`）。
 *   这样「点圆点开抽屉」不会被整面县块截走 —— 靠层级决定，不靠 JSX 加入顺序。
 *   本组件仍应在圆点**之前**渲染，顺序只影响默认 pane 内部的叠放，不是命中保证。
 * ⚠ `interactive` 保持默认 true：县块要响应 hover 出 tooltip。本页地图自身没有
 *   click/hover 行为，所以县块吃掉空白处的点击可以接受；若将来给地图加点击事件，
 *   这里必须改成 interactive:false 并另找 tooltip 载体。
 */
import { useEffect, useMemo, useState } from 'react'
import { Polygon, Tooltip } from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import api from '../../api'
import { cachedGet } from '../../cache'
import type { CountyBoundary } from '../gismap/types'
import {
  COUNTY_FILL_OPACITY, SOC_BAND_COLOR, bandLabelKey, type CountySoc, type SocBand,
} from './countySoc'

export function CountySocLayer({
  stats, isDark,
}: {
  /** 县名 → 平均 SOC 档位；由页面按**当前地图上的站点**算出，本组件不取数 */
  stats: Map<string, CountySoc>
  isDark: boolean
}) {
  const { t } = useI18n()
  const [counties, setCounties] = useState<CountyBoundary[]>([])

  useEffect(() => {
    let alive = true
    cachedGet('gis:county-boundaries', () => api.get('/gis/county-boundaries'))
      .then(res => { if (alive) setCounties(res.data?.counties || []) })
      .catch(err => {
        // 不静默：县界拉不到时底色图层整层不画，但控制台要留下原因
        // （GISMap.tsx:762 同一处理 —— 静默失败会让人以为「这个县就是没颜色」）
        console.error('[ipt_power] county boundaries failed:',
          err?.response?.status, err?.response?.data || err)
        if (alive) setCounties([])
      })
    return () => { alive = false }
  }, [])

  const opacity = isDark ? COUNTY_FILL_OPACITY.dark : COUNTY_FILL_OPACITY.light

  const shapes = useMemo(
    () => counties.map(c => {
      const stat = stats.get(c.name)
      const sites = stat?.sites ?? 0
      const band: SocBand = stat?.band ?? 'few'
      const color = SOC_BAND_COLOR[band]
      return { c, stat, sites, band, color }
    }),
    [counties, stats],
  )

  return (
    <>
      {shapes.map(({ c, stat, sites, band, color }) => (
        <Polygon
          key={`ipt-county-${c.name}`}
          positions={c.polygons as any}
          pathOptions={{
            color,
            fillColor: color,
            /* 当前站点集合里一个站都没有的县 → 只描边不填充：
               填成灰色会和「样本不足」那档混起来，读者分不清是哪种空 */
            fillOpacity: sites > 0 ? opacity : 0,
            weight: 1.5,
            opacity: 0.85,
            dashArray: '4 3',
          }}
        >
          {/* 非永久 tooltip：鼠标停到县块上才出（`components/LeafletMap.tsx` 的
              Tooltip 只透传 permanent/direction/className/pane，没有 sticky） */}
          <Tooltip direction="center">
            {sites > 0 && stat
              ? t('ipt.county.tip', {
                name: c.name,
                soc: `${((stat.avg ?? 0) * 100).toFixed(1)}%`,
                samples: stat.samples,
                sites,
                band: t(bandLabelKey(band)),
              })
              : t('ipt.county.tipEmpty', { name: c.name })}
          </Tooltip>
        </Polygon>
      ))}
    </>
  )
}
