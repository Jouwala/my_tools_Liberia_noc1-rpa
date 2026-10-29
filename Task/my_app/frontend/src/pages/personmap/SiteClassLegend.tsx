/* 地图左下角的「站点类别」图例浮层（2026-10-28，?page=person）
 *
 * **需求**（用户原话）：「添加图例，按照数据库的站点类型如 COOLI/ERA/NORMAL
 * 显示站点。默认不显示，当用户点击的时候在地图上显示。同样的，添加
 * vip_site/hub_site/trm_type」。
 *
 * **行为**：
 *   · 分组与取值**来自数据库**（后端扫库得出），界面不硬编码类别名；
 *     库里新增类别值时图例自动多一项。
 *   · **默认一项都不选** → 地图上一个类别站点都不画（需求原话）。
 *   · 点击某一项 → 切换该项的显示；组内多选取并集、组间取交集（口径见
 *     useSiteClasses.ts 文件头）。
 *   · 面板可折叠（标题栏点击），门户嵌入时地图较矮，能收起来只看标题。
 *
 * **位置选右上角、紧挨 LayerToggles 之下**（2026-10-28）：原本放在左下角，
 *   但门户嵌入（`?embed=1&mwembed=1`）下 `#main-content` 高度被钉在视口，
 *   地图容器实际被撑到 1122px（`minHeight: MAP_HEIGHT` + 右列卡片），
 *   底部超出视口约 320px —— 实测左下角按钮中心 y=982 而视口只有 805，
 *   图例整块落在屏幕外，既看不见也点不中。右上角不受容器溢出影响。
 *   样式与 LayerToggles 保持一致（同一套卡片外观）。
 */
import { useState } from 'react'
import { Button, Spin, Tooltip } from 'antd'
import { AppstoreOutlined, ClearOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'
import { WH } from '../../theme'
import { useI18n } from '../../i18n'
import { siteClassColor } from './siteClassColors'
import type { SiteClassGroup } from './types'

/* 分组标题的 i18n 键。
 *
 * ⚠ 刻意**不**写成 `t(\`person.legend.group.${g.key}\`)`：check-i18n 的模板分支会把
 *   静态前缀整体收录，任一同族键在两份字典里缺一个就拦构建（AGENTS.md 三.1b
 *   记的坑）。这里显式把键列全，与 `NocAnalyst.tsx::sliceLabelKey()` 同写法。
 *   键来自后端 `_SITE_CLASS_GROUPS`（库里缺列时该组不出现），故这里也要覆盖全。 */
function groupLabelKey(group: string): string {
  switch (group) {
    case 'site_caregory': return 'person.legend.group.site_caregory'
    case 'vip_site': return 'person.legend.group.vip_site'
    case 'hub_site': return 'person.legend.group.hub_site'
    case 'trm_type': return 'person.legend.group.trm_type'
    default: return ''
  }
}

export function SiteClassLegend({
  groups, loading, error, selected, onToggle, onClear, shown, total, nf, labelOf,
}: {
  groups: SiteClassGroup[]
  loading: boolean
  /** 取数失败时显示的原因（不静默空白，AGENTS.md 三.6） */
  error: string
  /** 当前选中：分组键 → 值集合 */
  selected: Record<string, string[]>
  onToggle: (group: string, value: string) => void
  onClear: () => void
  /** 当前地图上画出的类别站点数 */
  shown: number
  /** 库里坐标有效的站点总数 */
  total: number
  nf: (n: number) => string
  labelOf: (group: string, value: string) => string
}) {
  const { t } = useI18n()
  /** 折叠态默认展开 —— 图例不展开就没人知道可以点（需求要的是"点击时显示站点"，
   *  不是"点击时才出现图例"）。嫌占地方可点标题栏收起。 */
  const [open, setOpen] = useState(true)

  const anySelected = Object.keys(selected).length > 0

  return (
    /* `person-legend`：与 `person-map-canvas` 同理，给本浮层一个专属类，
       便于 index.css 限定样式与自动化脚本定位。
       定位由调用方（右上角浮层列）负责，这里只管自身外观。

       **单列排版**（2026-10-28 用户要求「图例一列就行，现在 3 列太宽了」）：
       原先每个分组内的取值是 `flexWrap: wrap` 横排，三四项就折成 2~3 列、
       面板被迫撑到 320px，在门户嵌入的窄地图里横着占掉一大条。改为每组
       纵向单列后宽度收到 220px（仍装得下最长项 `Satellite Link 92`）。
       ⚠ `maxHeight` 用 `100vh` 而不是父容器百分比：门户嵌入下父容器
       （地图）被撑到 1122px，按它算等于不限制，高度仍可能顶出视口。 */
    <div
      className="person-legend"
      style={{
        /* 宽度由外层浮层列给定（`width: '100%'`，见 MapTopRightOverlays.tsx
           的同宽说明），这里撑满即可 —— 与上方「人员 / 默认站点」开关卡同宽。 */
        width: '100%', maxHeight: 'calc(100vh - 120px)', overflow: 'auto',
        padding: '6px 8px',
        borderRadius: 'var(--wh-radius-sm, 4px)',
        background: 'var(--wh-card-bg, rgba(255,255,255,0.92))',
        border: '1px solid rgba(128,128,128,0.35)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
        fontSize: '0.75rem', userSelect: 'none',
      }}
    >
      {/* 标题栏：图标 + 标题 + 计数 + 折叠 */}
      <div
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          fontWeight: 600, color: WH.text,
        }}
        role="button"
        aria-expanded={open}
        title={t('person.legend.toggleTip')}
      >
        <AppstoreOutlined />
        <span>{t('person.legend.title')}</span>
        {anySelected && (
          <span style={{ fontWeight: 400, color: WH.textDim }}>
            {t('person.legend.shown', { n: nf(shown), total: nf(total) })}
          </span>
        )}
        <span style={{ marginLeft: 'auto', color: WH.textDim }}>
          {open ? <DownOutlined /> : <UpOutlined />}
        </span>
      </div>

      {open && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: WH.textDim }}>
              <Spin size="small" />
              <span>{t('person.legend.loading')}</span>
            </div>
          )}

          {!loading && error && (
            <div style={{ color: WH.sev.Critical }}>
              {t('person.legend.failed')}: {error}
            </div>
          )}

          {!loading && !error && !groups.length && (
            <div style={{ color: WH.textDim }}>{t('person.noData')}</div>
          )}

          {!loading && !error && groups.map(g => {
            const lk = groupLabelKey(g.key)
            return (
            <div key={g.key}>
              <div style={{ color: WH.textDim, marginBottom: 3 }}>
                {lk ? t(lk) : g.key}
              </div>
              {/* 单列（见容器上的说明）：名称靠左、计数靠右对齐 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {g.values.map(v => {
                  const picked = (selected[g.key] || []).includes(v.value)
                  const color = siteClassColor(g.key, v.value)
                  return (
                    <button
                      key={v.value}
                      type="button"
                      data-class-group={g.key}
                      data-class-value={v.value}
                      onClick={() => onToggle(g.key, v.value)}
                      aria-pressed={picked}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        width: '100%',
                        padding: '0 6px', cursor: 'pointer',
                        fontSize: '0.75rem', lineHeight: 1.7,
                        color: picked ? WH.text : WH.textDim,
                        background: picked ? `${color}22` : 'transparent',
                        border: `1px solid ${picked ? color : 'rgba(128,128,128,0.4)'}`,
                        borderRadius: 3,
                        fontWeight: picked ? 600 : 400,
                      }}
                    >
                      <span style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: color, display: 'inline-block', flexShrink: 0,
                      }} />
                      <span>{labelOf(g.key, v.value)}</span>
                      <span style={{ marginLeft: 'auto', color: WH.textDim }}>{nf(v.count)}</span>
                    </button>
                  )
                })}
              </div>
            </div>
            )
          })}

          {/* 口径说明：无选中时提示可点；跨组多选时说明是交集 */}
          {!loading && !error && (
            <div style={{ color: WH.textDim, borderTop: '1px solid rgba(128,128,128,0.25)', paddingTop: 4 }}>
              {!anySelected
                ? t('person.legend.hint')
                : t('person.legend.combine')}
            </div>
          )}

          {anySelected && (
            <div style={{ display: 'flex' }}>
              <Tooltip title={t('person.legend.clearTip')}>
                <Button size="small" type="text" icon={<ClearOutlined />} onClick={onClear}>
                  {t('person.legend.clear')}
                </Button>
              </Tooltip>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
