import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Input, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import { exportAoaReport } from '../utils/excelReport'
import ReactECharts from 'echarts-for-react'
import { getRepeatSiteDownDayDrilldown, getRepeatSiteDownEventDetail, getRepeatSiteDownFilters, getRepeatSiteDownOverview, getRepeatSiteDownSiteDrilldown } from '../api'
import { useI18n } from '../i18n'
import DraggableClickModal from '../components/DraggableClickModal'
// 数字悬浮口径说明（AGENTS.md 三.3c）：ⓘ 讲这一项怎么算，气泡讲这个数怎么来。
// 本页原先只有 counting_rule 的原生 Tooltip（不可复制、不受主题管），已整体换掉。
import CalcChainNote from '../components/CalcChainNote'
import { ExplainIcon, ExplainLabel, ExplainPopover } from '../components/MetricExplain'
import { CardBase, StatCard } from '../components/cards'
import { WH } from '../theme'

const { Text } = Typography
type EventRow = Record<string, any> & { day: string; site_id: string; site_name: string; region: string; tt_no: string; alarm_occur_time: string }
type SiteRow = { site_id: string; site_name: string; region: string; outage_count: number; repeat_days?: number; daily?: { day: string; outage_count: number }[] }
// meta.schema 是后端 _detect_schema() 的原样下发（真正命中的列名），气泡用它回答「按哪一列判的」
type Meta = {
  generated_at: string; warnings?: string[]; counting_rule?: string
  source_rows?: number; malformed_time_rows?: number
  schema?: { occur?: string | null; outage?: string | null; tt_id?: string | null; tt_name?: string | null }
}
type Overview = { filters: { start: string; end: string }; meta: Meta; summary: { outage_events: number; affected_sites: number; repeat_sites: number; peak_day: string; peak_day_count: number }; daily: { day: string; outage_count: number; affected_sites: number }[]; sites: SiteRow[]; events: EventRow[] }
const fmt = (v: unknown) => v == null || v === '' ? '-' : String(v)
// 取不到数据显示 —，不显示成 0
const dash = (v: number | undefined | null) => v == null ? '—' : v

export default function RepeatSiteDown() {
  const { t } = useI18n()
  const [start, setStart] = useState<Dayjs | null>(dayjs().subtract(30, 'day')); const [end, setEnd] = useState<Dayjs | null>(dayjs()); const [region, setRegion] = useState(''); const [site, setSite] = useState(''); const [regions, setRegions] = useState<string[]>([])
  const [data, setData] = useState<Overview | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('')
  const [modal, setModal] = useState<'day' | 'site' | 'event' | null>(null); const [modalTitle, setModalTitle] = useState(''); const [modalLoading, setModalLoading] = useState(false); const [modalAnchor, setModalAnchor] = useState<{ x: number; y: number } | null>(null)
  const [dayData, setDayData] = useState<any>(null); const [siteData, setSiteData] = useState<any>(null); const [eventData, setEventData] = useState<EventRow | null>(null)

  const load = useCallback(async () => { if (!start || !end) return; setLoading(true); setError(''); try { const r = await getRepeatSiteDownOverview({ start: start.format('YYYY-MM-DD'), end: end.format('YYYY-MM-DD'), region, site }); setData(r.data); if (r.data?.error) setError(r.data.error) } catch (e: any) { setError(e?.message || String(e)); setData(null) } finally { setLoading(false) } }, [start, end, region, site])
  useEffect(() => { getRepeatSiteDownFilters().then(r => setRegions(r.data?.regions || [])).catch(() => undefined) }, [])
  useEffect(() => { load() }, [load])
  const common = () => ({ start: data?.filters.start || start?.format('YYYY-MM-DD') || '', end: data?.filters.end || end?.format('YYYY-MM-DD') || '', region, site })

  const openDay = async (day: string, anchor?: { x: number; y: number }) => { setModal('day'); setModalTitle(t('rsd.dayDrill', { day })); setModalAnchor(anchor || null); setModalLoading(true); try { setDayData((await getRepeatSiteDownDayDrilldown({ ...common(), day })).data) } catch { setDayData(null) } finally { setModalLoading(false) } }
  const openSite = async (row: SiteRow, anchor?: { x: number; y: number }) => { setModal('site'); setModalTitle(t('rsd.siteDrill', { site: row.site_name })); setModalAnchor(anchor || null); setModalLoading(true); try { setSiteData((await getRepeatSiteDownSiteDrilldown({ ...common(), site_id: row.site_id, site_name: row.site_name })).data) } catch { setSiteData(null) } finally { setModalLoading(false) } }
  const openEvent = async (row: EventRow, anchor?: { x: number; y: number }) => { setModal('event'); setModalTitle(t('rsd.ttDetail', { tt: row.tt_no || row.alarm_occur_time })); setModalAnchor(anchor || null); setModalLoading(true); try { setEventData((await getRepeatSiteDownEventDetail({ ...common(), tt_no: row.tt_no || '', alarm_occur_time: row.alarm_occur_time || '', site_id: row.site_id, site_name: row.site_name })).data?.event || null) } catch { setEventData(null) } finally { setModalLoading(false) } }

  /* ---- 数字悬浮说明（AGENTS.md 三.3c）----
   * 气泡字段一律取接口下发值（summary / daily / meta.schema），前端不重算任何口径。
   * 后端算法见 backend/services/repeat_site_down/repeat_site_down_service.py。 */
  const win = { start: data?.filters.start || start?.format('YYYY-MM-DD') || '—', end: data?.filters.end || end?.format('YYYY-MM-DD') || '—' }
  const occurCol = data?.meta?.schema?.occur || '—'
  const outageCol = data?.meta?.schema?.outage || '—'
  const peakRow = useMemo(() => (data?.daily || []).find(d => d.day === data?.summary?.peak_day), [data])

  const chart = useMemo(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 50, right: 24, top: 28, bottom: 48 }, xAxis: { type: 'category', data: (data?.daily || []).map(x => x.day.slice(5)), axisLabel: { rotate: 35 } }, yAxis: [{ type: 'value', name: t('rsd.axis.occurrences') }, { type: 'value', name: t('rsd.axis.sites') }], series: [{ name: t('rsd.series.occurrences'), type: 'bar', data: (data?.daily || []).map(x => x.outage_count), itemStyle: { color: '#ff7875' } }, { name: t('rsd.series.sites'), type: 'line', yAxisIndex: 1, data: (data?.daily || []).map(x => x.affected_sites), smooth: true, itemStyle: { color: '#1677ff' } }] }), [data, t])
  const onChartEvents = { click: (p: any) => { const day = data?.daily?.[p.dataIndex]?.day; if (day) openDay(day, { x: p.event?.event?.clientX || 0, y: p.event?.event?.clientY || 0 }) } }
  // 已迁统一格式 UNIFIED_EXCEL_V1：样式与邮件报表同源，见 docs/EXCEL_EXPORT_STANDARD.md
// 原用 json_to_sheet（列头取对象键），此处显式取键，保持列头与列序不变。
const exportRows = (rows: any[], name: string) => {
  if (!rows.length) return
  const keys = Object.keys(rows[0])
  void exportAoaReport({
    filename: `${name}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
    sheetName: 'Drilldown',
    title: name,
    header: keys,
    rows: rows.map(r => keys.map(k => (r[k] == null ? '' : r[k]))),
  })
}
  const siteColumns = [
    { title: t('rsd.col.site'), key: 'site', render: (_: unknown, r: SiteRow) => <><Text strong>{fmt(r.site_name)}</Text><br /><Text type="secondary">ID: {fmt(r.site_id)}</Text></> },
    { title: t('rsd.col.region'), dataIndex: 'region', render: fmt },
    {
      title: <ExplainLabel label={t('rsd.col.occurrences')} text={t('rsd.explainCol.occurrences', { occur: occurCol })} />,
      dataIndex: 'outage_count',
      sorter: (a: SiteRow, b: SiteRow) => a.outage_count - b.outage_count,
      render: (v: number, r: SiteRow) => (
        <ExplainPopover placement="left" text={t('rsd.tip.rowOccurrences', { n: v, days: r.repeat_days ?? 0 })}>
          <span style={{ fontWeight: 600 }}>{v}</span>
        </ExplainPopover>
      ),
    },
    {
      title: <ExplainLabel label={t('rsd.col.repeatDays')} text={t('rsd.explainCol.repeatDays')} />,
      dataIndex: 'repeat_days',
      render: (v: number) => (
        <ExplainPopover placement="left" text={t('rsd.tip.rowRepeatDays', { d: v })}>
          {v > 1 ? <Tag color="red">{v}</Tag> : <span>{fmt(v)}</span>}
        </ExplainPopover>
      ),
    },
    { title: t('rsd.col.action'), key: 'action', render: (_: unknown, r: SiteRow) => <Button type="link" onClick={(e) => openSite(r, { x: e.clientX, y: e.clientY })}>{t('rsd.btn.view')}</Button> },
  ]
  const eventColumns = [
    { title: t('rsd.col.day'), dataIndex: 'day' },
    { title: t('rsd.col.ttNo'), dataIndex: 'tt_no', render: fmt },
    { title: t('rsd.col.occurred'), dataIndex: 'alarm_occur_time', render: fmt },
    { title: t('rsd.col.titleField'), dataIndex: 'title', render: fmt },
    { title: t('rsd.col.status'), dataIndex: 'status', render: fmt },
    { title: t('rsd.col.detail'), key: 'detail', render: (_: unknown, r: EventRow) => <Button type="link" onClick={(e) => openEvent(r, { x: e.clientX, y: e.clientY })}>{t('rsd.btn.fullFields')}</Button> },
  ]
  const modalBody = modal === 'day' ? <><Space wrap><ExplainPopover text={t('rsd.tip.drillDay', { n: dayData?.summary?.outage_events ?? 0, sites: dayData?.summary?.affected_sites ?? 0 })}><Tag color="red">{t('rsd.tag.events', { n: dayData?.summary?.outage_events ?? 0 })}</Tag></ExplainPopover><ExplainPopover text={t('rsd.tip.drillSites', { n: dayData?.summary?.affected_sites ?? 0 })}><Tag color="blue">{t('rsd.tag.sites', { n: dayData?.summary?.affected_sites ?? 0 })}</Tag></ExplainPopover><Button size="small" icon={<DownloadOutlined />} onClick={() => exportRows(dayData?.sites || [], 'repeat_site_down_day')}>{t('rsd.btn.export')}</Button></Space><Table rowKey={(r: SiteRow) => `${r.site_id}-${r.site_name}`} dataSource={dayData?.sites || []} columns={siteColumns} loading={modalLoading} pagination={{ pageSize: 12 }} /></> : modal === 'site' ? <><Space wrap><ExplainPopover text={t('rsd.tip.drillSite', { n: siteData?.summary?.outage_events ?? 0, days: siteData?.summary?.repeat_days ?? 0 })}><Tag color="red">{t('rsd.tag.events', { n: siteData?.summary?.outage_events ?? 0 })}</Tag></ExplainPopover><ExplainPopover text={t('rsd.tip.drillRepeatDays', { d: siteData?.summary?.repeat_days ?? 0 })}><Tag color="orange">{t('rsd.tag.repeatDays', { n: siteData?.summary?.repeat_days ?? 0 })}</Tag></ExplainPopover><Button size="small" icon={<DownloadOutlined />} onClick={() => exportRows(siteData?.events || [], 'repeat_site_down_events')}>{t('rsd.btn.export')}</Button></Space><Table rowKey={(r: EventRow, i) => `${r.tt_no}-${i}`} dataSource={siteData?.events || []} columns={eventColumns} loading={modalLoading} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} /></> : <>{eventData ? <Table showHeader={false} pagination={false} dataSource={Object.entries(eventData).map(([key, value]) => ({ key, value }))} rowKey="key" columns={[{ title: t('rsd.col.field'), dataIndex: 'key', width: 260 }, { title: t('rsd.col.value'), dataIndex: 'value', render: fmt }]} /> : <Empty description={t('rsd.empty.ttDetail')} />}</>

  const s = data?.summary
  const malformed = data?.meta?.malformed_time_rows ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <CardBase>
        <Space wrap>
          <DatePicker value={start} onChange={setStart} />
          <span>{t('rsd.to')}</span>
          <DatePicker value={end} onChange={setEnd} />
          <Select allowClear placeholder={t('rsd.ph.region')} value={region || undefined} onChange={v => setRegion(v || '')} options={regions.map(v => ({ value: v, label: v }))} style={{ width: 180 }} showSearch />
          <Input allowClear placeholder={t('rsd.ph.site')} value={site} onChange={e => setSite(e.target.value)} style={{ width: 180 }} />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('rsd.btn.refresh')}</Button>
          <Button icon={<DownloadOutlined />} onClick={() => exportRows(data?.sites || [], 'repeat_site_down_sites')} disabled={!data?.sites?.length}>{t('rsd.btn.export')}</Button>
        </Space>
      </CardBase>

      {error && <Alert type="error" showIcon message={error} />}
      {data?.meta?.warnings?.map(w => <Alert key={w} type="warning" showIcon message={w} />)}
      {/* 时间格式不对的行被后端丢掉 → 卡片数字会比库里少，属「这次算不全」，必须常驻可见 */}
      {malformed > 0 && <Alert type="warning" showIcon message={t('rsd.warn.malformed', { n: malformed })} />}

      <CalcChainNote
        title={t('rsd.calcNote.title')}
        sections={[
          { title: t('rsd.calcNote.secSource'), lines: [t('rsd.calcNote.src1'), t('rsd.calcNote.src2', { occur: occurCol, outage: outageCol })] },
          { title: t('rsd.calcNote.secWindow'), lines: [t('rsd.calcNote.window1', win), t('rsd.calcNote.window2')] },
          { title: t('rsd.calcNote.secDedupe'), lines: [t('rsd.calcNote.dedupe1'), t('rsd.calcNote.dedupe2')] },
          { title: t('rsd.calcNote.secRule'), lines: [data?.meta?.counting_rule ? t('rsd.calcNote.rule', { rule: data.meta.counting_rule }) : t('rsd.calcNote.ruleMissing')] },
        ]}
      />

      <Row gutter={12}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<ExplainLabel label={t('rsd.card.occurrences')} text={data ? t('rsd.explain.occurrences', { occur: occurCol, outage: outageCol }) : ''} />}
            value={dash(s?.outage_events)}
            subText={t('rsd.sub.window', win)}
            explainText={s ? t('rsd.tip.occurrences', { n: s.outage_events, start: win.start, end: win.end, malformed }) : ''}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<ExplainLabel label={t('rsd.card.sites')} text={data ? t('rsd.explain.sites') : ''} />}
            value={dash(s?.affected_sites)}
            subText={t('rsd.sub.rows', { n: s?.outage_events ?? '—' })}
            explainText={s ? t('rsd.tip.sites', { affected: s.affected_sites, events: s.outage_events }) : ''}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<ExplainLabel label={t('rsd.card.repeat')} text={data ? t('rsd.explain.repeat') : ''} />}
            value={dash(s?.repeat_sites)}
            accentColor={(s?.repeat_sites ?? 0) > 0 ? WH.danger : WH.textMuted}
            subText={t('rsd.sub.ofSites', { n: s?.affected_sites ?? '—' })}
            explainText={s ? t('rsd.tip.repeat', { repeat: s.repeat_sites, affected: s.affected_sites }) : ''}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<ExplainLabel label={t('rsd.card.peak')} text={data ? t('rsd.explain.peak') : ''} />}
            value={s?.peak_day || '—'}
            suffix={s?.peak_day_count ? ` (${s.peak_day_count})` : ''}
            explainText={s?.peak_day
              ? t('rsd.tip.peak', { day: s.peak_day, count: s.peak_day_count, sites: peakRow?.affected_sites ?? '—', days: data?.daily?.length ?? 0 })
              : t('rsd.tip.peakEmpty', win)}
          />
        </Col>
      </Row>

      <CardBase
        title={<ExplainLabel label={t('rsd.chart.title')} text={data ? t('rsd.explain.chart', { occur: occurCol }) : ''} />}
        extra={<Text type="secondary">{t('rsd.hint.clickDay')}</Text>}
      >
        {data?.daily?.length
          ? <ReactECharts option={chart} onEvents={onChartEvents} style={{ height: 340 }} notMerge />
          : <Empty description={t('rsd.empty.outage')} />}
      </CardBase>

      <CardBase
        title={(
          <span>
            {t('rsd.rank.title')}
            <span style={{ marginLeft: 6 }}><ExplainIcon text={data ? t('rsd.explain.rank') : ''} /></span>
          </span>
        )}
      >
        <Table rowKey={(r) => `${r.site_id}-${r.site_name}`} columns={siteColumns} dataSource={data?.sites || []} loading={loading} pagination={{ pageSize: 20 }} scroll={{ x: 800 }} />
      </CardBase>

      <DraggableClickModal open={!!modal} title={modalTitle} anchor={modalAnchor} onClose={() => setModal(null)} width={1150}>{modalBody}</DraggableClickModal>
    </div>
  )
}
