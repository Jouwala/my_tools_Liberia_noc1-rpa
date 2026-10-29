/* 人员针图层（2026-10-28 从 PersonMapView 抽出，行数纪律 AGENTS.md 三.2）
 *
 * 只做一件事：把 `pinPersons` 逐个画成 Marker。图标的颜色 / 尺寸 / 徽标 HTML /
 * iconKey 的推导仍在 `personPinHtml.ts`（那里有「悬停态绝不能进 iconKey」的
 * 完整论证 —— 悬停一旦进 iconKey，Leaflet 会在指针下重建图层，把 DOM 换掉，
 * mousedown/mouseup 落在不同元素上、click 不产生，表现为「点人没反应」）。
 *
 * `pane` 由调用方传入（PersonMapView 的 `personPane`，z-index 680）：
 * 人员针必须压在站点圆点与连线之上，且高于 tooltip pane。
 */
import { Marker } from '../../components/LeafletMap'
import { useI18n } from '../../i18n'
import { buildPersonPin } from './personPinHtml'
import type { PersonRow } from './types'

export function PersonPinsLayer({
  persons, selectedKey, isDark, pane, onSelect,
}: {
  persons: PersonRow[]
  selectedKey: string | null
  isDark: boolean
  /** 人员针所在的 Leaflet pane 名（调用方已用 `<Pane>` 显式声明过） */
  pane: string
  onSelect: (p: PersonRow) => void
}) {
  const { t } = useI18n()
  return (
    <>
      {persons.map(p => {
        const selected = p.name_key === selectedKey
        const pin = buildPersonPin(p, selected, isDark, t)
        return (
          <Marker
            key={p.name_key}
            position={[p.lat as number, p.lng as number]}
            pane={pane}
            html={pin.html}
            iconSize={pin.iconSize}
            iconAnchor={pin.iconAnchor}
            iconKey={pin.iconKey}
            zIndexOffset={selected ? 1000 : 0}
            className="gis-person-marker"
            onClick={() => onSelect(p)}
          />
        )
      })}
    </>
  )
}
