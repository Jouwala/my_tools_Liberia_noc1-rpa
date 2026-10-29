/* 地图右上角的图层开关浮层（2026-10-23 起；2026-10-24 随「人员」开关改为双行）
 *
 * · 人员（默认开）：人员针 + 常驻徽标 + 选中者的站点圆点/连线。关掉时
 *   PersonMapView 会同时清除选中态 —— 留着选中会出现「抽屉开着、地图上
 *   一片空」的自相矛盾画面（与点空白取消选中同一语义）。
 * · 默认站点（默认关）：全国 FME 辖区连线 + 去重站点小圆点；取数在
 *   useTerritory.ts，首次打开才拉 /fme-territories（~130KB，24 人 824 站）。
 *
 * 两个开关是**独立图层**：辖区线可以单独显示（纯辖区总览、不被针和徽标
 * 挡住），人员针也可以单独显示。前身 TerritoryToggle.tsx 只装一个开关，
 * 第二个真实开关出现即更名（AGENTS.md 三.10 删除优于兼容）。
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
