// 人员位置地图（`?page=person`）的数字悬浮说明。
// 与 availCounty/availCountyHelpers.tsx 同一取向：文案只排版本页**已有的接口字段**，
// 前端不重算口径（AGENTS.md 三.3c）。逐人 open/uncleared/closed/tt_total 由
// backend/routers/personnel.py 一次扫描算出，本页只做「按当前行求和」这一步。
import type { PersonRow, PersonStats } from './types'

type TFn = (key: string, params?: Record<string, string | number>) => string

const nf = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))

/** 「People with coordinates」卡：分子/分母都点名，并说清另一套全表口径为什么不用。 */
export function peopleCardExplain(stats: PersonStats | null, t: TFn, days: number): string {
  const c = stats?.coverage
  return [
    t('person.tip.peopleFe', {
      with: nf(c?.fe_with_coords),
      total: nf(c?.fe_total),
    }),
    t('person.tip.peopleAll', {
      wc: nf(c?.with_coords),
      ta: nf(c?.total_all),
    }),
    t('person.tip.peopleNoWindow', { days }),
  ].join('\n')
}

/** 未清除 / 未关闭 / 总数三张卡：说明「逐人接口字段 + 本页求和」与各自的判据。 */
export function sumCardExplain(
  field: 'uncleared' | 'open' | 'total',
  sumValue: number,
  rowCount: number,
  stats: PersonStats | null,
  t: TFn,
  days: number,
): string {
  const lines = [t('person.tip.sumRows', { n: rowCount, value: nf(sumValue), field })]
  if (field === 'uncleared') {
    lines.push(t('person.tip.unclearedCaliber'))
  } else if (field === 'open') {
    lines.push(t('person.tip.openCaliber', { days }))
  } else {
    lines.push(t('person.tip.totalCaliber', { days }))
  }
  const byStatus = stats?.by_status
  if (byStatus) lines.push(t('person.tip.byStatus', { open: nf(byStatus.open), closed: nf(byStatus.closed) }))
  return lines.join('\n')
}

/** 站点卡：只有选中个人时才有数字，未选中刻意显示 —。 */
export function siteCardExplain(
  selectedName: string | null,
  siteCount: number | null,
  alarmSites: number | null,
  t: TFn,
): string {
  if (!selectedName) return t('person.tip.sitesNoSel')
  return [
    t('person.tip.sitesSel', { name: selectedName, n: nf(siteCount) }),
    t('person.tip.sitesAlarm', { alarm: nf(alarmSites ?? 0) }),
  ].join('\n')
}

/** 表格里逐人数字的气泡：点名接口字段，顺带说明点击「查看工单」去哪。 */
export function personCellExplain(col: 'uncleared' | 'open' | 'closed' | 'tt_total', r: PersonRow, t: TFn, days: number): string {
  switch (col) {
    case 'uncleared':
      return [
        t('person.tip.cellUncleared', { name: r.name, v: nf(r.uncleared) }),
        t('person.tip.unclearedCaliber'),
        t('person.tip.cellDrill'),
      ].join('\n')
    case 'open':
      return [
        t('person.tip.cellOpen', { name: r.name, v: nf(r.open), days }),
        t('person.tip.openCaliber', { days }),
        t('person.tip.cellDrill'),
      ].join('\n')
    case 'closed':
      return t('person.tip.cellClosed', { name: r.name, v: nf(r.closed), days })
    case 'tt_total':
      return t('person.tip.cellTt', {
        name: r.name, v: nf(r.tt_total), open: nf(r.tt_open), closed: nf(r.tt_closed),
      })
  }
}
