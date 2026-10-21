/* 人员下钻抽屉（?page=person，2026-10-21 新增）
 *
 * **需求**（用户原话，2026-10-21）：「点击人员要再左边显示弹窗，里面可以看到详细的
 * 站点/WO/PMT列表，用页签的形式展示，参考项目中使用的方法如
 * ?page=realtime_alarm 页面点击站点下钻后的弹窗。」
 *   —— 同日追加：「弹窗要在右边卡片的位置，避免遮挡地图」。**方向以追加的为准**。
 *
 * **为什么是 antd Drawer 而不是 `components/DraggableClickModal`**：
 *   用户指定的参考实现 `pages/gismap/SiteDrilldownDrawer.tsx` 本身就是 Drawer
 *   （`SiteDrilldownDrawer.tsx:237`），照它做才叫「参考项目中使用的方法」。
 *   DraggableClickModal 是跟着点击锚点的小窗，装不下三张「可搜索 + 可导出」的表；
 *   AGENTS.md 三.3 禁的是「各页自写弹窗骨架」，这里复用的是同一个组件族
 *   （Drawer + `components/SearchableExportTable`），不是另起一套。
 *
 * **`placement="right"`**：首版按原话做成左滑，但本页**地图就在左列**
 *   （2026-10-21 同日做的分栏对调），左滑正好把地图整个盖住 —— 用户随即改口要右侧。
 *   现在抽屉压在**右列**（KPI 2×2 + 两张统计图）上，地图与刚点中的那个人始终可见，
 *   也就回到了参考页 `SiteDrilldownDrawer` 原本的方向。
 *
 * **数据全部由页面传入，本组件不发请求**：`sites` 就是地图画站点层在用的那一份，
 *   WO / PMT 由页面按选中人员拉取。同一个人在地图上看到的站点圆点数与
 *   「站点」页签的行数因此必然来自同一次响应（AGENTS.md 三.1b 同源）。
 */
import { useMemo, useState, type ReactNode } from 'react'
import { Alert, Drawer, Spin, Tabs, Tag } from 'antd'
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import { SearchableExportTable } from '../../components/SearchableExportTable'
import { filterBySearch, exportToExcel } from '../gismap/helpers'
import { NoSitesNote } from './NoSitesNote'
import type { ManagedSite, PersonRow, PmtResp, PmtRow, WoRow } from './types'

export type PersonDrillTab = 'sites' | 'wo' | 'pmt'

/** 抽屉宽度 = **卡片列的 `flex-basis`**（`PersonMap.tsx` 右列写 `flex: 0 0 24rem`），
 *  刻意不抄参考页的 `45rem`。
 *  用户 2026-10-21 的原话是「弹窗要在右边卡片的位置，避免遮挡地图」——
 *  45rem 在 1151px 视口下会盖住右列(432px) **再加半张地图**；先试 30rem 实测仍
 *  压住地图右缘 67px。收到 24rem 才是字面意义上的「卡片那一块」，地图一像素不挡。
 *  表列多到装不下时靠 `SearchableExportTable` 的 `scroll={{ x: 'max-content' }}`
 *  横向滚，不靠加宽抽屉。 */
const DRAWER_WIDTH = 'min(95vw, 24rem)' as any

/** 只导出「有 dataIndex 的列」。
 *  本抽屉有 3 个计算列（告警 / 任务窗口 / 条目进度）不对应单一字段，
 *  而 `helpers.exportToExcel` 是按 `row[dataIndex]` 取值的，硬塞会导出空列。
 *  参考页的 buildXxxColumns 每列都有 dataIndex，所以没碰到这个问题。 */
const exportCols = (cols: any[]) => cols.filter(c => typeof c.dataIndex === 'string')

export function PersonDrilldownDrawer({
  open, onClose, person, activeTab, onTabChange,
  sites, sitesLoading, woRows, woLoading, pmtRows, pmtLoading, pmtMeta,
}: {
  open: boolean
  onClose: () => void
  /** 当前选中的人员；null 时抽屉内容区不渲染（正常不会发生，防御关闭动画期间的空态） */
  person: PersonRow | null
  activeTab: PersonDrillTab
  onTabChange: (tab: PersonDrillTab) => void
  sites: ManagedSite[]
  sitesLoading: boolean
  woRows: WoRow[]
  woLoading: boolean
  pmtRows: PmtRow[]
  pmtLoading: boolean
  pmtMeta: PmtResp['meta'] | null
}) {
  const { t } = useI18n()
  const [siteSearch, setSiteSearch] = useState('')
  const [woSearch, setWoSearch] = useState('')
  const [pmtSearch, setPmtSearch] = useState('')

  const filteredSites = useMemo(() => filterBySearch(sites, siteSearch), [sites, siteSearch])
  const filteredWo = useMemo(() => filterBySearch(woRows, woSearch), [woRows, woSearch])
  const filteredPmt = useMemo(() => filterBySearch(pmtRows, pmtSearch), [pmtRows, pmtSearch])

  /* ---------- 列 ---------- */
  const siteColumns = useMemo(() => [
    { title: t('person.colSite'), dataIndex: 'site_name', key: 'site_name', width: 170,
      render: (v: string, r: ManagedSite) => v || r.site_id || '—' },
    { title: t('person.siteId'), dataIndex: 'site_id', key: 'site_id', width: 120 },
    { title: t('person.county'), dataIndex: 'county', key: 'county', width: 140,
      render: (v: string) => v || '—' },
    { title: t('person.colOpenWo'), dataIndex: 'wo_count', key: 'wo_count', width: 100 },
    { title: t('person.colUncleared'), dataIndex: 'uncleared', key: 'uncleared', width: 90,
      render: (v: number) => (
        <span style={{ color: v > 0 ? WH.sev.Critical : undefined, fontWeight: v > 0 ? 700 : 400 }}>{v}</span>
      ) },
    { title: t('person.colAlarm'), key: 'alarm', width: 130,
      render: (_: unknown, r: ManagedSite) => r.has_alarm
        ? <Tag color="red">{t('person.siteHasAlarm')}</Tag>
        : <span style={{ color: WH.textDim }}>{t('person.siteNoAlarm')}</span> },
  ], [t])

  /* WO 页签的列 —— 原先在 PersonMap.tsx 里为「查看WO」小弹窗定义，
     那个弹窗已被本抽屉的 WO 页签取代，列定义随之搬进来（不留第二份）。 */
  const woColumns = useMemo(() => [
    { title: t('person.colWoNo'), dataIndex: 'wo_no', key: 'wo_no', width: 150 },
    { title: t('person.colTtNo'), dataIndex: 'tt_no', key: 'tt_no', width: 150 },
    { title: t('person.colSite'), key: 'site', width: 150,
      render: (_: unknown, r: WoRow) => r.site_name || r.site_id || '—' },
    { title: t('person.colStatus'), dataIndex: 'status', key: 'status', width: 130 },
    { title: t('person.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 160 },
    { title: t('person.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 160,
      render: (v: string) => (v == null || v === '' ? '—' : String(v)) },
    { title: t('person.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true },
  ], [t])

  const pmtColumns = useMemo(() => [
    { title: t('person.colPmtNo'), dataIndex: 'pmt_no', key: 'pmt_no', width: 150 },
    { title: t('person.colStatus'), dataIndex: 'status', key: 'status', width: 150 },
    { title: t('person.colSite'), dataIndex: 'site_name', key: 'site_name', width: 150,
      render: (v: string) => v || '—' },
    { title: t('person.colOverdue'), dataIndex: 'pmt_overdue', key: 'pmt_overdue', width: 90,
      render: (v: string) => String(v || '').trim().toUpperCase() === 'YES'
        ? <Tag color="red">{t('common.yes')}</Tag>
        : <span style={{ color: WH.textDim }}>{t('common.no')}</span> },
    { title: t('person.colTaskWindow'), key: 'window', width: 250,
      render: (_: unknown, r: PmtRow) =>
        `${r.current_task_start_time || '—'} ~ ${r.current_task_end_time || '—'}` },
    { title: t('person.colProgress'), key: 'progress', width: 90,
      render: (_: unknown, r: PmtRow) =>
        `${Number(r.completed_items || 0)}/${Number(r.total_items || 0)}` },
    { title: t('person.colTitle'), dataIndex: 'title', key: 'title', width: 180, ellipsis: true },
    { title: t('person.colTemplate'), dataIndex: 'template', key: 'template', width: 200, ellipsis: true },
  ], [t])

  /* ---------- 三个页签的表体 ---------- */
  const sitesTable = (
    <>
      {/* 0 个负责站点时先说原因，再留空表 —— 只有一张空表会被当成「没加载出来」。
          与地图上那条说明同源（`NoSitesNote`）。 */}
      {!sitesLoading && sites.length === 0 && (
        <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <NoSitesNote person={person} />
        </div>
      )}
      <SearchableExportTable
        data={filteredSites}
        columns={siteColumns}
        search={siteSearch}
        onSearchChange={setSiteSearch}
        onExport={() => exportToExcel(filteredSites, `Person_Sites_${person?.name || ''}`, exportCols(siteColumns))}
        exportText={t('common.exportExcel')}
        rowKey={(r: any) => r.site_id}
        ariaLabel={t('person.tabSites')}
      />
    </>
  )

  const woTable = (
    <SearchableExportTable
      data={filteredWo}
      columns={woColumns}
      search={woSearch}
      onSearchChange={setWoSearch}
      onExport={() => exportToExcel(filteredWo, `Person_WO_${person?.name || ''}`, exportCols(woColumns))}
      exportText={t('common.exportExcel')}
      rowKey={(r: any, i?: number) => `${r.wo_no}-${i}`}
      ariaLabel={t('person.tabWo')}
    />
  )

  const pmtTable = (
    <>
      {pmtMeta && !pmtMeta.available && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={<span style={{ fontSize: 12 }}>{t('person.pmtUnavailable')}</span>} />
      )}
      {pmtMeta?.truncated && (
        <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={<span style={{ fontSize: 12 }}>{t('person.pmtTruncated')}</span>} />
      )}
      <SearchableExportTable
        data={filteredPmt}
        columns={pmtColumns}
        search={pmtSearch}
        onSearchChange={setPmtSearch}
        onExport={() => exportToExcel(filteredPmt, `Person_PMT_${person?.name || ''}`, exportCols(pmtColumns))}
        exportText={t('common.exportExcel')}
        rowKey={(r: any) => r.pmt_no}
        ariaLabel={t('person.tabPmt')}
      />
    </>
  )

  const tab = (loading: boolean, node: ReactNode) => (
    loading ? <Spin style={{ display: 'block', margin: '2rem auto' }} /> : node
  )

  return (
    <Drawer
      placement="right"
      /* 不带遮罩。参考页那套全屏半透明 mask 会**把地图整片压暗**，与用户
         「避免遮挡地图」的原话直接冲突；去掉后抽屉开着也能继续点地图上的人，
         点中另一个 → 抽屉内容直接换人，不必先关再点。
         代价：点抽屉外部不再自动关闭 —— 关闭有三条路（右上角 ×、
         再点一次同一个人、地图卡片右上角「取消选中」）。 */
      mask={false}
      title={
        <span style={{ color: WH.text }}>
          {t('person.drillTitle', { name: person?.name || '—' })}
          {person?.phone ? (
            <span style={{ marginLeft: 'var(--wh-space-sm)', fontSize: '0.75rem', fontWeight: 400, color: WH.textDim }}>
              {person.phone}
            </span>
          ) : null}
        </span>
      }
      width={DRAWER_WIDTH}
      styles={{
        body: { background: WH.bg },
        header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid rgba(0, 217, 255,0.15)' },
      }}
      open={open}
      onClose={onClose}
    >
      <Tabs
        activeKey={activeTab}
        onChange={k => onTabChange(k as PersonDrillTab)}
        items={[
          {
            key: 'sites',
            label: <span style={{ color: WH.text }}>{t('person.tabSites')} ({sites.length})</span>,
            children: tab(sitesLoading, sitesTable),
          },
          {
            key: 'wo',
            label: <span style={{ color: WH.text }}>{t('person.tabWo')} ({woRows.length})</span>,
            children: tab(woLoading, woTable),
          },
          {
            key: 'pmt',
            label: (
              <span style={{ color: WH.text }}>
                {t('person.tabPmt')} ({pmtMeta && !pmtMeta.available ? '—' : pmtRows.length})
                {pmtMeta && pmtMeta.overdue_count > 0 ? ` · ${pmtMeta.overdue_count} ${t('person.colOverdueShort')}` : ''}
              </span>
            ),
            children: tab(pmtLoading, pmtTable),
          },
        ]}
      />
    </Drawer>
  )
}
