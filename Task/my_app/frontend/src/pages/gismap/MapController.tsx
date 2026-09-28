import { useEffect } from 'react'
import { useMap } from '../../components/LeafletMap'

// 地图视图控制器：center/zoom 变化时同步 setView
export function MapController({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap()
  useEffect(() => {
    map.setView(center, zoom)
  }, [center, zoom, map])
  return null
}
