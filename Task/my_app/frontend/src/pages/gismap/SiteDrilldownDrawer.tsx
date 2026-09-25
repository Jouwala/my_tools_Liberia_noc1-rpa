import { useMemo, useState } from 'react'
import { Card, Row, Col, Drawer, Descriptions, Tag, Statistic, Tabs, Spin, Table, Segmented, Tooltip, Alert } from 'antd'
import { AlertOutlined, ThunderboltOutlined, BarChartOutlined, TableOutlined } from '@ant-design/icons'
import { useI18n } from '../../i18n'
import { WH, cardStyle, useTheme } from '../../theme'
import { SearchableExportTable } from '../../components/SearchableExportTable'
import type { DrilldownData, DrilldownAnalytics } from './types'
import { SITE_COLORS } from './types'
import { filterBySearch, exportToExcel, buildAlarmColumns, buildTTColumns, buildWOColumns } from './helpers'
import { ChartBlock } from './ChartBlock'
import { RatKpiTab } from './RatKpiTab'
import {
  buildAvailabilityOption, buildPacketLossOption,
  buildMicrowaveOption, buildMicrowaveCurrentOption,
  buildPieOption, buildBarOption, buildStackedDailyOption,
  hasData,
} from './chartOptions'

interface SiteDrilldownDrawerProps {
  open: boolean
  onClose: () => void
  loading: boolean
  drilldown: DrilldownData | null
  selectedSite: string
  mode: 'all' | 'realtime'
  /** 图表用全量聚合统计（不受明细 LIMIT 截断） */
  analytics?: DrilldownAnalytics | null
  analyticsLoading?: boolean
  /** 统计窗口天数 */
  rangeDays?: number
  onRangeDaysChange?: (days: number) => void
}

const RANGE_OPTIONS = [30, 60, 90, 180]
const DEFAULT_THRESHOLD = 0.9965 // 与 SiteAvailability 页面 / 后端一致

// 站点下钻抽屉：基本信息 + 统计卡片 + 各 Tab「上图表 / 下表格」
export function SiteDrilldownDrawer({
  open, onClose, loading, drilldown, selectedSite, mode,
  analytics, analyticsLoading, rangeDays = 60, onRangeDaysChange,
}: SiteDrilldownDrawerProps) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [ttSearch, setTtSearch] = useState('')
  const [woSearch, setWoSearch] = useState('')
  const [rtAlarmSearch, setRtAlarmSearch] = useState('')
  const [hisAlarmSearch, setHisAlarmSearch] = useState('')

  const filteredTT = useMemo(() => {
    if (!drilldown?.tt_list) return []
    return filterBySearch(drilldown.tt_list, ttSearch)
  }, [drilldown?.tt_list, ttSearch])

  const filteredWO = useMemo(() => {
    if (!drilldown?.wo_list) return []
    return filterBySearch(drilldown.wo_list, woSearch)
  }, [drilldown?.wo_list, woSearch])

  const filteredRtAlarm = useMemo(() => {
    if (!drilldown?.rt_alarm_list) return []
    return filterBySearch(drilldown.rt_alarm_list, rtAlarmSearch)
  }, [drilldown?.rt_alarm_list, rtAlarmSearch])

  const filteredHisAlarm = useMemo(() => {
    if (!drilldown?.his_alarm_list) return []
    return filterBySearch(drilldown.his_alarm_list, hisAlarmSearch)
  }, [drilldown?.his_alarm_list, hisAlarmSearch])

  const ttColumns = useMemo(() => buildTTColumns(t, drilldown?.tt_list || []), [drilldown?.tt_list, t])
  const woColumns = useMemo(() => buildWOColumns(t, drilldown?.wo_list || []), [drilldown?.wo_list, t])
  const rtAlarmColumns = useMemo(() => buildAlarmColumns(t, drilldown?.rt_alarm_list || []), [drilldown?.rt_alarm_list, t])
  const hisAlarmColumns = useMemo(() => buildAlarmColumns(t, drilldown?.his_alarm_list || []), [drilldown?.his_alarm_list, t])

  const kpis = drilldown?.kpis
  const avail = kpis?.availability || []
  const pl = kpis?.packet_loss || []
  const mw = kpis?.microwave || []
  const series = kpis?.kpi_series || {}

  // ---- 图表 option（懒计算，仅在有数据时构建） ----
  const availOption = useMemo(() => (hasData(avail)
    ? buildAvailabilityOption(avail, { isDark, threshold: DEFAULT_THRESHOLD, t })
    : null), [avail, isDark, t])

  const plOption = useMemo(() => (hasData(pl)
    ? buildPacketLossOption(pl, { isDark, t })
    : null), [pl, isDark, t])

  const mwHasHistory = useMemo(() => mw.some(l => hasData(l.history)), [mw])
  const mwOption = useMemo(() => {
    if (!hasData(mw)) return null
    return mwHasHistory
      ? buildMicrowaveOption(mw, { isDark, t })
      : buildMicrowaveCurrentOption(mw, { isDark, t })
  }, [mw, mwHasHistory, isDark, t])

  const tt = analytics?.tt
  const wo = analytics?.wo
  const his = analytics?.his

  const ttDailyOption = useMemo(() => (hasData(tt?.daily)
    ? buildStackedDailyOption(tt!.daily as any, { isDark, t }) : null), [tt?.daily, isDark, t])
  const ttStatusOption = useMemo(() => (hasData(tt?.by_status)
    ? buildPieOption(tt!.by_status!, { isDark, t }) : null), [tt?.by_status, isDark, t])
  const ttSlaOption = useMemo(() => (hasData(tt?.by_sla)
    ? buildPieOption(tt!.by_sla!, { isDark, t }) : null), [tt?.by_sla, isDark, t])
  const ttSeverityOption = useMemo(() => (hasData(tt?.by_severity)
    ? buildPieOption(tt!.by_severity!, { isDark, t }) : null), [tt?.by_severity, isDark, t])
  const ttRootCauseOption = useMemo(() => (hasData(tt?.by_root_cause)
    ? buildBarOption(tt!.by_root_cause!, { isDark, t, horizontal: true }) : null), [tt?.by_root_cause, isDark, t])
  const ttDurationOption = useMemo(() => (hasData(tt?.duration_buckets)
    ? buildBarOption(tt!.duration_buckets!, { isDark, t }) : null), [tt?.duration_buckets, isDark, t])

  const woDailyOption = useMemo(() => (hasData(wo?.daily)
    ? buildStackedDailyOption(wo!.daily as any, { isDark, t }) : null), [wo?.daily, isDark, t])
  const woStatusOption = useMemo(() => (hasData(wo?.by_status)
    ? buildPieOption(wo!.by_status!, { isDark, t }) : null), [wo?.by_status, isDark, t])
  const woSourceOption = useMemo(() => (hasData(wo?.by_source)
    ? buildPieOption(wo!.by_source!, { isDark, t }) : null), [wo?.by_source, isDark, t])
  const woRootCauseOption = useMemo(() => (hasData(wo?.by_root_cause)
    ? buildBarOption(wo!.by_root_cause!, { isDark, t, horizontal: true }) : null), [wo?.by_root_cause, isDark, t])

  const hisDailyOption = useMemo(() => (hasData(his?.daily)
    ? buildStackedDailyOption((his!.daily || []).map(d => ({ day: d.day, total: d.total, closed: d.total })), { isDark, t })
    : null), [his?.daily, isDark, t])
  const hisSeverityOption = useMemo(() => (hasData(his?.by_severity)
    ? buildPieOption(his!.by_severity!, { isDark, t }) : null), [his?.by_severity, isDark, t])
  const hisTitleOption = useMemo(() => (hasData(his?.by_title)
    ? buildBarOption(his!.by_title!, { isDark, t, horizontal: true }) : null), [his?.by_title, isDark, t])

  // 明细表下方的原始表格（保留原有实现）
  const ttTable = (
    <SearchableExportTable
      data={filteredTT}
      columns={ttColumns}
      search={ttSearch}
      onSearchChange={setTtSearch}
      onExport={() => exportToExcel(filteredTT, `TT_${drilldown?.site_info?.site_name || selectedSite}`, ttColumns)}
      exportText={t('gis.exportTT')}
      rowKey={(r: any, i?: number) => `${r.title}-${i}`}
      ariaLabel={t('gis.drilldown.ttTab')}
    />
  )
  const woTable = (
    <SearchableExportTable
      data={filteredWO}
      columns={woColumns}
      search={woSearch}
      onSearchChange={setWoSearch}
      onExport={() => exportToExcel(filteredWO, `WO_${drilldown?.site_info?.site_name || selectedSite}`, woColumns)}
      exportText={t('gis.exportWO')}
      rowKey={(r: any, i?: number) => `${r.wo_no}-${i}`}
      ariaLabel={t('gis.drilldown.woTab')}
    />
  )
  const hisTable = (
    <SearchableExportTable
      data={filteredHisAlarm}
      columns={hisAlarmColumns}
      search={hisAlarmSearch}
      onSearchChange={setHisAlarmSearch}
      onExport={() => exportToExcel(filteredHisAlarm, `His_Alarm_${drilldown?.site_info?.site_name || selectedSite}`, hisAlarmColumns)}
      exportText={t('gis.exportHIS')}
      rowKey={(r: any, i?: number) => `his-${r.alarmraisedtime}-${i}`}
      ariaLabel={t('gis.drilldown.hisAlarmTab')}
    />
  )

  const rangeNode = (
    <Segmented
      size="small"
      value={rangeDays}
      onChange={(v) => onRangeDaysChange?.(Number(v))}
      options={RANGE_OPTIONS.map(d => ({ label: t(`gis.range.d${d}`), value: d }))}
    />
  )

  return (
    <Drawer
      title={
        <span style={{ color: WH.text }}>
          {t('gis.drilldown.title')} - {drilldown?.site_info?.site_name || selectedSite}
          {drilldown?.site_info?.vip_site === 'Yes' && <Tag color="purple" style={{ marginLeft: 'var(--wh-space-sm)' }}>VIP</Tag>}
        </span>
      }
      width={'min(95vw, 45rem)' as any}
      styles={{
        body: { background: WH.bg },
        header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid rgba(0, 217, 255,0.15)' },
      }}
      open={open}
      onClose={onClose}
    >
      {loading ? (
        <Spin style={{ display: 'block', margin: 'var(--wh-space-2xl) auto' }} />
      ) : drilldown ? (
        <div>
          <Card size="small" title={<span style={{ color: WH.text }}>{t('gis.drilldown.basicInfo')}</span>} style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteId')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.site_id}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteName')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.site_name}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.region')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.region}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.province')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.province_county}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.networkType')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.network_type}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteType')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.site_type}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.vipSite')}</span>}>
                {drilldown.site_info.vip_site === 'Yes'
                  ? <Tag color="purple">{t('common.yes')}</Tag>
                  : <Tag>{t('common.no')}</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteCategory')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.site_class || '-'}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.coords')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.latitude?.toFixed(4)}, {drilldown.site_info.longitude?.toFixed(4)}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.powerSource')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.power_sources}</span>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 统计范围：同时作用于图表聚合与明细列表 */}
          <Card size="small" style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}>
            <Row align="middle" justify="space-between" gutter={[8, 8]}>
              <Col>
                <Tooltip title={t('gis.range.tip')}>
                  <span style={{ color: WH.textMuted, fontSize: 12, marginRight: 8 }}>
                    <BarChartOutlined /> {t('gis.range.label')}
                  </span>
                </Tooltip>
                {rangeNode}
              </Col>
              <Col>
                <span style={{ color: WH.textMuted, fontSize: 12 }}>
                  {drilldown.range
                    ? t('gis.range.applied', { start: drilldown.range.start, end: drilldown.range.end })
                    : ''}
                </span>
              </Col>
            </Row>
          </Card>

          <Row gutter={8} style={{ marginBottom: 'var(--wh-space-md)' }}>
            <Col xs={12} sm={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.totalTT')}</span>} value={tt?.total ?? drilldown.tt_count} valueStyle={{ color: WH.teal, fontWeight: 700 }} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.totalWO')}</span>} value={wo?.total ?? drilldown.wo_count} valueStyle={{ color: WH.blue, fontWeight: 700 }} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.rtAlarm')}</span>} value={drilldown.rt_alarm_count} valueStyle={{ color: drilldown.rt_alarm_count > 0 ? SITE_COLORS.rt_alarm : WH.text, fontWeight: 700 }} /></Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={cardStyle}>
                <Statistic
                  title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.slaAchievement')}</span>}
                  value={tt?.sla_rate != null ? Math.round(tt.sla_rate) : (
                    drilldown.sla_stats.total_tt > 0
                      ? Math.round((drilldown.sla_stats.sla_met || 0) / drilldown.sla_stats.total_tt * 100)
                      : 0
                  )}
                  suffix="%"
                  valueStyle={{ color: WH.teal, fontWeight: 700 }}
                />
              </Card>
            </Col>
          </Row>

          {analyticsLoading && <Spin style={{ display: 'block', margin: '0 auto var(--wh-space-md)' }} size="small" />}

          <Tabs
            items={[
              {
                key: 'availability',
                label: <span style={{ color: WH.text }}><BarChartOutlined /> {t('gis.drilldown.availTab')} ({avail.length})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.trend')} option={availOption} height={260} />
                    <Table
                      size="small"
                      pagination={{ pageSize: 10 }}
                      rowKey={(r: any) => `${r.tech}-${r.day}`}
                      dataSource={avail}
                      columns={[
                        { title: t('gis.drilldown.colTech'), dataIndex: 'tech', key: 'tech' },
                        { title: t('gis.drilldown.colDay'), dataIndex: 'day', key: 'day' },
                        { title: t('gis.drilldown.colAvailability'), dataIndex: 'availability', key: 'availability', render: (v: number) => `${(Number(v) <= 1 ? Number(v) * 100 : Number(v)).toFixed(2)}%` },
                      ]}
                    />
                  </>
                ),
              },
              {
                key: 'packet_loss',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.lossTab')} ({pl.length})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.trend')} option={plOption} height={260} />
                    <Table
                      size="small"
                      pagination={{ pageSize: 10 }}
                      rowKey={(r: any) => r.day}
                      dataSource={pl}
                      columns={[
                        { title: t('gis.drilldown.colDay'), dataIndex: 'day', key: 'day' },
                        { title: t('gis.drilldown.colMaxLoss'), dataIndex: 'max_packet_loss', key: 'max_packet_loss', render: (v: number) => `${Number(v || 0).toFixed(2)}%` },
                        { title: t('gis.drilldown.colAvgLoss'), dataIndex: 'avg_packet_loss', key: 'avg_packet_loss', render: (v: number) => `${Number(v || 0).toFixed(2)}%` },
                        { title: t('gis.drilldown.colSamples'), dataIndex: 'samples', key: 'samples' },
                      ]}
                    />
                  </>
                ),
              },
              {
                key: 'microwave',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.mwTab')} ({mw.length})</span>,
                children: (
                  <>
                    <ChartBlock title={mwHasHistory ? t('gis.chart.mwTrend') : t('gis.chart.mwCurrent')} option={mwOption} height={260} />
                    <Table
                      size="small"
                      pagination={{ pageSize: 10 }}
                      rowKey={(r: any, i?: number) => `${r.source}-${r.target}-${i}`}
                      dataSource={mw}
                      columns={[
                        { title: t('gis.drilldown.colMwSource'), dataIndex: 'source', key: 'source' },
                        { title: t('gis.drilldown.colMwTarget'), dataIndex: 'target', key: 'target' },
                        { title: t('gis.drilldown.colTxUtil'), dataIndex: 'tx_utilization', key: 'tx_utilization', render: (v: number) => v == null ? '-' : `${Number(v).toFixed(2)}%` },
                        { title: t('gis.drilldown.colRxUtil'), dataIndex: 'rx_utilization', key: 'rx_utilization', render: (v: number) => v == null ? '-' : `${Number(v).toFixed(2)}%` },
                        { title: t('gis.drilldown.colCapacity'), dataIndex: 'capacity_mbps', key: 'capacity_mbps' },
                        { title: t('gis.drilldown.colLevel'), dataIndex: 'level', key: 'level' },
                      ]}
                    />
                  </>
                ),
              },
              // ===== 分制式 KPI 页签（2G / 3G / 4G）=====
              ...(['2G', '3G', '4G'].map((rat) => ({
                key: `kpi_${rat}`,
                label: <span style={{ color: WH.text }}>{t(`gis.kpi.tab${rat.toLowerCase()}`)} ({series[rat]?.days || 0})</span>,
                children: <RatKpiTab series={series[rat]} rat={rat} />,
              }))),
              {
                key: 'tt',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.ttTab')} ({tt?.total ?? drilldown.tt_count})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.dailyTt')} option={ttDailyOption} height={240} fullScope />
                    <Row gutter={[8, 8]}>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.byStatus')} option={ttStatusOption} height={220} fullScope />
                      </Col>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.bySeverity')} option={ttSeverityOption} height={220} fullScope />
                      </Col>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.bySla')} option={ttSlaOption} height={220} fullScope />
                      </Col>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.durationDist')} option={ttDurationOption} height={220} fullScope />
                      </Col>
                      <Col xs={24}>
                        <ChartBlock title={t('gis.chart.byRootCause')} option={ttRootCauseOption} height={240} fullScope />
                      </Col>
                    </Row>
                    {ttTable}
                  </>
                ),
              },
              {
                key: 'wo',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.woTab')} ({wo?.total ?? drilldown.wo_count})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.dailyWo')} option={woDailyOption} height={240} fullScope />
                    <Row gutter={[8, 8]}>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.byStatus')} option={woStatusOption} height={220} fullScope />
                      </Col>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.bySource')} option={woSourceOption} height={220} fullScope />
                      </Col>
                      <Col xs={24}>
                        <ChartBlock title={t('gis.chart.byRootCause')} option={woRootCauseOption} height={240} fullScope />
                      </Col>
                    </Row>
                    {woTable}
                  </>
                ),
              },
              ...(mode === 'all' ? [{
                key: 'his_alarm',
                label: <span style={{ color: WH.text }}><AlertOutlined style={{ color: SITE_COLORS.his_alarm }} /> {t('gis.drilldown.hisAlarmTab')} ({his?.total ?? drilldown.his_alarm_count})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.dailyHis')} option={hisDailyOption} height={240} fullScope />
                    <Row gutter={[8, 8]}>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.bySeverity')} option={hisSeverityOption} height={220} fullScope />
                      </Col>
                      <Col xs={24} md={12}>
                        <ChartBlock title={t('gis.chart.byTitle')} option={hisTitleOption} height={220} fullScope />
                      </Col>
                    </Row>
                    {hisTable}
                  </>
                ),
              }] : []),
              {
                key: 'rt_alarm',
                label: <span style={{ color: WH.text }}><ThunderboltOutlined style={{ color: SITE_COLORS.rt_alarm }} /> {t('gis.drilldown.rtAlarmTab')} ({drilldown.rt_alarm_count})</span>,
                children: (
                  <>
                    {/* 实时告警是当前快照、单站点通常 0~2 行，数据量不足以出图 —— 明确说明而非画空图 */}
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 'var(--wh-space-md)' }}
                      message={<span style={{ fontSize: 12 }}>{t('gis.chart.rtNoChart')}</span>}
                    />
                    <SearchableExportTable
                      data={filteredRtAlarm}
                      columns={rtAlarmColumns}
                      search={rtAlarmSearch}
                      onSearchChange={setRtAlarmSearch}
                      onExport={() => exportToExcel(filteredRtAlarm, `RT_Alarm_${drilldown.site_info?.site_name || selectedSite}`, rtAlarmColumns)}
                      exportText={t('gis.exportRT')}
                      rowKey={(r: any, i?: number) => `rt-${r.alarmraisedtime}-${i}`}
                      ariaLabel={t('gis.drilldown.rtAlarmTab')}
                    />
                  </>
                ),
              },
            ]}
          />
        </div>
      ) : (
        <div style={{ color: WH.textMuted }}>{t('gis.drilldown.loadError')}</div>
      )}
    </Drawer>
  )
}
