/* 选中了人、但他一个负责站点都没有时的说明条（2026-10-21）
 *
 * **为什么需要**：站点集合按用户确认只认 `master_site_db.fme_name`，而 24 个有坐标的
 * 人里有 6 个 `site_count` 为 0 —— 其中 3 个恰好是在手单最多的
 * （Varfee Sarnor 91 WO/298 PMT、Franklin Peter 24/215、Festus Emmanuel 10/133）。
 * 点他们地图上一片空白，实测就被当成「连线没画出来」的 bug 报过一次。
 * 口径本身是对的（supervisor 是把全国 824 站按大区三三分，不是单站负责），
 * 缺的只是把原因说出来。
 *
 * 地图与下钻抽屉**共用这一处文案**（地图那条多一层底部居中的定位外壳，
 * 见下方 `MapNoSitesNote`），两处必须一致，否则同一件事两种说法。
 */
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import type { PersonRow } from './types'

/** 地图版说明条：底部居中浮层（2026-10-24 从 PersonMapView 抽出）。
 *
 *  与下钻抽屉**共用文案**（裸 `NoSitesNote`）但容器不同：抽屉里那条直接
 *  排在「站点」页签下，地图这条要浮在地图上，故包一层绝对定位外壳。
 *  `pointerEvents:none` —— 说明条不能拦地图点击，否则点它就取消不了选中。
 *  放**底部居中**：左上是 Leaflet 缩放控件与本层的搜索框，右下是 attribution，
 *  底部居中三样都避得开。 */
export function MapNoSitesNote({ person }: { person: PersonRow | null }) {
  if (!person) return null
  return (
    <div style={{
      position: 'absolute', bottom: 28, left: '50%', transform: 'translateX(-50%)',
      maxWidth: 420, zIndex: 1000, pointerEvents: 'none',
      padding: 'var(--wh-space-xs, 4px) var(--wh-space-sm, 8px)',
      borderRadius: 'var(--wh-radius-sm, 4px)',
      background: 'var(--wh-card-bg, rgba(255, 255, 255, 0.9))',
      border: '1px solid rgba(128,128,128,0.35)',
      boxShadow: '0 1px 4px rgba(0, 0, 0, 0.25)',
    }}>
      <NoSitesNote person={person} />
    </div>
  )
}

export function NoSitesNote({ person }: { person: PersonRow | null }) {
  const { t } = useI18n()
  if (!person) return null
  /* `undefined` = 后端还没这个字段（旧进程，重启窗口内会这样）。
     这时**只说基础事实，不猜原因** —— 说成「人员列里没有他」对那 3 个 supervisor
     是错的，而把 supervisor 的 353 站说成 0 也错。缺信息就少说一句。 */
  const supervised = person.supervised_sites
  return (
    <div style={{ fontSize: '0.75rem', lineHeight: 1.5, color: WH.textDim }}>
      <div>{t('person.noFmeSites')}</div>
      {supervised != null && (
        <div style={{ marginTop: 2 }}>
          {supervised > 0
            ? t('person.noFmeSitesSupervisor', { n: supervised })
            : t('person.noFmeSitesNone')}
        </div>
      )}
    </div>
  )
}
