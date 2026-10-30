/* 地图右上角的图层开关浮层（2026-10-23 起；2026-10-24 随「人员」开关改为双行）
 *
 * · 人员（默认开）：人员针 + 常驻徽标 + 选中者的站点圆点/连线。
 * · 默认站点（默认关）：全国 FME 辖区连线 + 去重站点小圆点 + **每个辖区几何中心的
 *   人员标签**（2026-10-29 用户要求「跟 People 一样的标签」）；取数在
 *   useTerritory.ts，首次打开才拉 /fme-territories（~130KB，24 人 824 站）。
 *
 * 两个开关**独立但中心标签归辖区层**：关掉「人员」而留着「默认站点」，图上仍有
 * 24 个中心标签（无辖区连线的 supervisor 等 6 人此时不出现）；两个都关才是纯底图。
 * 「人员」关掉时只有在辖区也关的情况下才清除选中 —— 针还看得见就不该关抽屉。
 * 集合的三档推导见 PersonMapView 的 visiblePins 注释。
 *
 * **位置由调用方决定**（2026-10-28 改）：本组件只负责卡片外观，定位交给
 * PersonMapView 的「右上角浮层列」—— 它与站点类别图例纵向堆叠，避免各自
 * 绝对定位时互相压盖。
 */
import { Switch } from 'antd'
import { useI18n } from '../../i18n'

export function LayerToggles({
  peopleChecked, onPeopleChange,
  terrChecked, terrLoading, onTerrChange,
}: {
  peopleChecked: boolean
  onPeopleChange: (v: boolean) => void
  terrChecked: boolean
  terrLoading: boolean
  onTerrChange: (v: boolean) => void
}) {
  const { t } = useI18n()
  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', gap: 4,
        padding: '6px 10px',
        borderRadius: 'var(--wh-radius-sm, 4px)',
        background: 'var(--wh-card-bg, rgba(255,255,255,0.92))',
        border: '1px solid rgba(128,128,128,0.35)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
        fontSize: '0.75rem', userSelect: 'none',
      }}
    >
      <div title={t('person.peopleTip')}
           style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Switch size="small" checked={peopleChecked} onChange={onPeopleChange} />
        <span>{t('person.peopleToggle')}</span>
      </div>
      <div title={t('person.territoryTip')}
           style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Switch size="small" checked={terrChecked} loading={terrLoading}
          onChange={onTerrChange} />
        <span>{t('person.territoryToggle')}</span>
      </div>
    </div>
  )
}
