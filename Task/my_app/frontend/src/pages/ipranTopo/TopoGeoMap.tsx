/* 地理视图底图。只画接口里真正带经纬度的点，模糊匹配与精确匹配用不同描边，缺坐标不落点。 */
import { Empty } from 'antd'

import { WH, useTheme } from '../../theme'
import { useI18n } from '../../i18n'
import { CardBase } from '../../components/cards'
import { CircleMarker, MapContainer, Popup } from '../../components/LeafletMap'
import { PmtilesLayer } from '../gismap/PmtilesLayer'
import { BASEMAP_MAX_ZOOM, BASEMAP_PMTILES_URL } from '../gismap/basemap'
import type { TopoNode } from './types'

interface Props {
  nodes: TopoNode[]
  impacted: ReadonlySet<number> | null
  onFocus: (i: number) => void
}

export default function TopoGeoMap({ nodes, impacted, onFocus }: Props) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const plotted = nodes.flatMap((n, i) => (
    n.lat != null && n.lon != null && n.geo !== 'miss' ? [{ n, i }] : []
  ))
  const missed = nodes.filter((n) => n.lat == null || n.lon == null || n.geo === 'miss').length
  if (!plotted.length) {
    return <CardBase title={t('ipranTopo.geo.mapTitle')}><Empty description={t('ipranTopo.geo.noPlot')} /></CardBase>
  }
  const lat = plotted.reduce((s, p) => s + (p.n.lat as number), 0) / plotted.length
  const lon = plotted.reduce((s, p) => s + (p.n.lon as number), 0) / plotted.length
  return (
    <CardBase title={t('ipranTopo.geo.mapTitle')}
      extra={<span style={{ color: WH.textDim, fontSize: 12 }}>{t('ipranTopo.geo.missNote', { n: missed })}</span>}>
      <div style={{ height: 360 }}>
        <MapContainer center={[lat, lon]} zoom={7} style={{ height: '100%', width: '100%' }} scrollWheelZoom>
          <PmtilesLayer url={BASEMAP_PMTILES_URL} isDark={isDark} maxZoom={BASEMAP_MAX_ZOOM} showLabels={false} showRoads={false} />
          {plotted.map(({ n, i }) => {
            const fuzzy = n.geo === 'fuzzy'
            const down = n.up !== 1
            const hit = impacted?.has(i)
            const color = down ? WH.danger : fuzzy ? WH.warn : WH.teal
            return (
              <CircleMarker key={n.id} center={[n.lat as number, n.lon as number]}
                radius={hit ? 9 : fuzzy ? 6 : 5}
                color={color} weight={fuzzy ? 2 : 1} fillColor={color}
                fillOpacity={fuzzy ? 0.2 : 0.85}
                onClick={() => onFocus(i)}>
                <Popup>
                  <div>
                    <b>{n.name}</b>
                    <div>{fuzzy ? t('ipranTopo.geo.fuzzy') : t('ipranTopo.geo.exact')}</div>
                    {n.geoName ? <div>{n.geoName}</div> : null}
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>
    </CardBase>
  )
}
