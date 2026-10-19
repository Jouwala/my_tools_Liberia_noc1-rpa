import { useMemo, useState } from 'react'
import { Card, Row, Col, Drawer, Descriptions, Tag, Statistic, Tabs, Spin, Table, Collapse, Tooltip, Alert } from 'antd'
import { AlertOutlined, ThunderboltOutlined, BarChartOutlined } from '@ant-design/icons'
import { useI18n } from '../../i18n'
import { WH, cardStyle, useTheme } from '../../theme'
import { SearchableExportTable } from '../../components/SearchableExportTable'
import type { DrilldownData, DrilldownAnalytics } from './types'
import { SITE_COLORS } from './types'
import { filterBySearch, exportToExcel, buildAlarmColumns, buildAlarmExportColumns, buildTTColumns, buildWOColumns } from './helpers'
import { ChartBlock } from './ChartBlock'
import { RatKpiTab } from './RatKpiTab'
import { AlarmSuggestionPanel } from './AlarmSuggestionPanel'
import './SiteDrilldownDrawer.css'
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
  /** 统计窗口天数。抽屉**自带的独立选择器**，默认 7 天（与地图初始时间窗口一致），
      用户可改成 30/60/90/180。它不跟随地图时间窗口 —— 见 GISMap.tsx 的 drillRangeDays */
  rangeDays?: number
  onRangeDaysChange?: (days: number) => void
}

/* 可选档位。**7 天是有意加上的**：地图初始时间窗口就是「近7天」，
   抽屉默认值要与之一致，若这里没有 7 档，选择器会一个都不高亮，
   用户看不出「当前就是 7 天」这个事实（改造前只有 30/60/90/180 就踩过这个坑）。
   后端 days 参数接受任意正整数（gis.py::_resolve_window 只做 max(1,int(days)) 保护），
   加 7 档不需要动后端 —— 已实测 days=7 返回的区间恰好 7 天。 */
const RANGE_OPTIONS = [7, 30, 60, 90, 180]
const DEFAULT_RANGE_DAYS = 7
const DEFAULT_THRESHOLD = 0.9965 // 与 SiteAvailability 页面 / 后端一致

// 站点下钻抽屉：基本信息 + 统计卡片 + 各 Tab 图表
// （明细表格已移除，仅 Realtime Alarm 页签因无法出图而保留表格）
export function SiteDrilldownDrawer({
  open, onClose, loading, drilldown, selectedSite, mode,
  analytics, analyticsLoading, rangeDays = DEFAULT_RANGE_DAYS, onRangeDaysChange,
}: SiteDrilldownDrawerProps) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  /* 明细表默认折叠：抽屉一打开只呈现图表，表格要用户点一下才展开。
     Realtime Alarm 页签没有图表（单站点通常 0~2 行），它的表格不做折叠、直接显示。 */
  const [rtAlarmSearch, setRtAlarmSearch] = useState('')
  const [ttSearch, setTtSearch] = useState('')
  const [woSearch, setWoSearch] = useState('')
  const [hisAlarmSearch, setHisAlarmSearch] = useState('')

  const filteredRtAlarm = useMemo(() => {
    if (!drilldown?.rt_alarm_list) return []
    return filterBySearch(drilldown.rt_alarm_list, rtAlarmSearch)
  }, [drilldown?.rt_alarm_list, rtAlarmSearch])

  const filteredTT = useMemo(() => {
    if (!drilldown?.tt_list) return []
    return filterBySearch(drilldown.tt_list, ttSearch)
  }, [drilldown?.tt_list, ttSearch])

  const filteredWO = useMemo(() => {
    if (!drilldown?.wo_list) return []
    return filterBySearch(drilldown.wo_list, woSearch)
  }, [drilldown?.wo_list, woSearch])

  const filteredHisAlarm = useMemo(() => {
    if (!drilldown?.his_alarm_list) return []
    return filterBySearch(drilldown.his_alarm_list, hisAlarmSearch)
  }, [drilldown?.his_alarm_list, hisAlarmSearch])

  /* 告警表的**展示**列走白名单 + 隐藏空列（见 helpers.ALARM_DISPLAY_KEYS），
     而**导出**列仍保留后端返回的全部字段 —— 屏幕精简、导出完整。 */
  const rtAlarmColumns = useMemo(() => buildAlarmColumns(t, drilldown?.rt_alarm_list || []), [drilldown?.rt_alarm_list, t])
  const ttColumns = useMemo(() => buildTTColumns(t, drilldown?.tt_list || []), [drilldown?.tt_list, t])
  const woColumns = useMemo(() => buildWOColumns(t, drilldown?.wo_list || []), [drilldown?.wo_list, t])
  const hisAlarmColumns = useMemo(() => buildAlarmColumns(t, drilldown?.his_alarm_list || []), [drilldown?.his_alarm_list, t])
  const rtAlarmExportColumns = useMemo(() => buildAlarmExportColumns(drilldown?.rt_alarm_list || []), [drilldown?.rt_alarm_list])
  const hisAlarmExportColumns = useMemo(() => buildAlarmExportColumns(drilldown?.his_alarm_list || []), [drilldown?.his_alarm_list])

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

  // 明细表节点（与表格自身实现解耦，便于统一包进折叠面板）
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
      onExport={() => exportToExcel(filteredHisAlarm, `His_Alarm_${drilldown?.site_info?.site_name || selectedSite}`, hisAlarmExportColumns)}
      exportText={t('gis.exportHIS')}
      rowKey={(r: any, i?: number) => `his-${r.alarmraisedtime}-${i}`}
      ariaLabel={t('gis.drilldown.hisAlarmTab')}
    />
  )

  /* 折叠式明细表容器。4 个页签（可用率/丢包/微波/TT/WO/历史告警）共用同一形态：
     面板头显示行数，默认全部收起（items[].key 不在 defaultActiveKey 里），
     点击才展开表格。各表搜索状态互相独立，收起后仍保留用户输入。 */
  const collapsibleTable = (key: string, count: number, node: React.ReactNode) => (
    <Collapse
      ghost
      size="small"
      className="gis-drilldown-table-collapse"
      items={[{
        key,
        label: <span style={{ color: WH.textMuted, fontSize: 12 }}>{t('gis.drilldown.tableToggle')} ({count})</span>,
        children: node,
      }]}
    />
  )

  /* 统计范围选择器。用自绘按钮组替代 Segmented：
     Segmented 的选中态由 antd 内部样式决定，无法按主题色强调；
     这里按「统一主题青」上色 —— 选中 = 实心青底 + 深色字，未选 = 青描边 + 20% 淡青底。
     RANGE_OPTIONS 保持 [7,30,60,90,180] 不变（顺序即渲染顺序）。 */
  const rangeNode = (
    <span role="group" aria-label={t('gis.range.label')} style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
      {RANGE_OPTIONS.map((d) => {
        const selected = Number(rangeDays) === d
        return (
          <button
            key={d}
            type="button"
            aria-pressed={selected}
            onClick={() => onRangeDaysChange?.(d)}
            style={{
              cursor: 'pointer',
              padding: '3px 14px',
              fontSize: 12,
              fontWeight: selected ? 700 : 500,
              lineHeight: '20px',
              borderRadius: 'var(--wh-radius-lg)',
              transition: 'background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
              background: selected ? WH.teal : WH.teal20,
              color: selected ? WH.bg : WH.teal,
              border: `1px solid ${selected ? WH.teal : WH.teal40}`,
              boxShadow: selected ? `0 0 12px ${WH.teal40}` : 'none',
            }}
          >
            {t(`gis.range.d${d}`)}
          </button>
        )
      })}
    </span>
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
              {/* TX Category 取 master_site_db.trm_type 列（传输承载类型，如 Starlink）。
                  注意与 site_caregory（站点等级 ERA/COOL/NORMAL）是两个不同维度，
                  也与 site_type（Outdoor/Indoor 机房形态）无关，不要互换。 */}
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteType')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.trm_type}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.vipSite')}</span>}>
                {drilldown.site_info.vip_site === 'Yes'
                  ? <Tag color="purple">{t('common.yes')}</Tag>
                  : <Tag>{t('common.no')}</Tag>}
              </Descriptions.Item>
              {/* Site Category 取 master_site_db.site_caregory 列（站点等级 ERA / COOL / NORMAL）。
                  注意既不是 site_type（机房形态），也不是 victims_list（受影响清单）。
                  site_caregory 已由后端 _attach_filter_cols 归一化，这里不再处理。 */}
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.siteCategory')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.site_caregory}</span>
              </Descriptions.Item>
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.coords')}</span>}>
                <span style={{ color: WH.text }}>{drilldown.site_info.latitude?.toFixed(4)}, {drilldown.site_info.longitude?.toFixed(4)}</span>
              </Descriptions.Item>
              {/* FME 名称与联系电话合并成一格：fme_name / fme_contact_1，
                  如「Patrick Monday / 775496534」。两列本来就是同一个工程师的
                  姓名与电话，拆成两格只会白占一个位置。
                  标签历史上叫 Power Source，与实际内容不符，已按实际列名改正。 */}
              <Descriptions.Item label={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.powerSource')}</span>}>
                <span style={{ color: WH.text }}>
                  {[drilldown.site_info.fme_name, drilldown.site_info.fme_contact_1]
                    .filter(v => v != null && String(v).trim() !== '')
                    .join(' / ') || '—'}
                </span>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 统计范围：抽屉自带的独立选择器，默认 7 天。默认值与地图初始时间窗口
              （近7天）一致，所以刚打开时两边口径相同；但二者**互相独立**：
              改地图时间窗口不动这里，改这里也不动地图。 */}
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
            className="gis-drilldown-tabs"
            items={[
              {
                key: 'availability',
                label: <span style={{ color: WH.text }}><BarChartOutlined /> {t('gis.drilldown.availTab')} ({avail.length})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.trend')} option={availOption} height={260} />
                    {collapsibleTable('avail', avail.length, (
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
                    ))}
                  </>
                ),
              },
              {
                key: 'packet_loss',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.lossTab')} ({pl.length})</span>,
                children: (
                  <>
                    <ChartBlock title={t('gis.chart.trend')} option={plOption} height={260} />
                    {collapsibleTable('pl', pl.length, (
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
                    ))}
                  </>
                ),
              },
              {
                key: 'microwave',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.mwTab')} ({mw.length})</span>,
                children: (
                  <>
                    <ChartBlock title={mwHasHistory ? t('gis.chart.mwTrend') : t('gis.chart.mwCurrent')} option={mwOption} height={260} />
                    {collapsibleTable('mw', mw.length, (
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
                    ))}
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
                    {/* 2026-10-19：Fault Tickets 页签直接展示单子明细（用户需求）。
                       此前包在 collapsibleTable 里需要点击「Detail Data (n)」才展开，
                       与站点下钻的「点开后想立刻看到对应单子」这个场景不符——尤其单数极少
                       时（最常见 1 单），二级折叠把仅有的信息再藏一次。
                       **实时模式（mode='realtime'）**：本抽屉的入口是实时告警，
                       单子通常 1 单，图表无意义，按 Realtime Alarm 页签同款只出表 + 提示；
                       **全量模式（mode='all'）**：保留原图表（按状态/级别/SLA/时长/根因
                       的聚合对历史数据仍有用），只把明细表提到外面。 */}
                    {mode === 'realtime' ? (
                      <>
                        <Alert
                          type="info"
                          showIcon
                          style={{ marginBottom: 'var(--wh-space-md)' }}
                          message={<span style={{ fontSize: 12 }}>{t('gis.chart.rtNoChart')}</span>}
                        />
                        {ttTable}
                      </>
                    ) : (
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
                    )}
                  </>
                ),
              },
              {
                key: 'wo',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.woTab')} ({wo?.total ?? drilldown.wo_count})</span>,
                children: (
                  <>
                    {/* 2026-10-19：实时模式下 WO 页签也只出表 + 提示条，理由同上（Fault Tickets 注释）。 */}
                    {mode === 'realtime' ? (
                      <>
                        <Alert
                          type="info"
                          showIcon
                          style={{ marginBottom: 'var(--wh-space-md)' }}
                          message={<span style={{ fontSize: 12 }}>{t('gis.chart.rtNoChart')}</span>}
                        />
                        {woTable}
                      </>
                    ) : (
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
                    )}
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
                    {collapsibleTable('his', filteredHisAlarm.length, hisTable)}
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
                      onExport={() => exportToExcel(filteredRtAlarm, `RT_Alarm_${drilldown.site_info?.site_name || selectedSite}`, rtAlarmExportColumns)}
                      exportText={t('gis.exportRT')}
                      rowKey={(r: any, i?: number) => `rt-${r.alarmraisedtime}-${i}`}
                      ariaLabel={t('gis.drilldown.rtAlarmTab')}
                    />
                  </>
                ),
              },
            ]}
          />
          {/* 站点告警处理建议面板（2026-10-16 新增）
              抽屉底部独立组件，**与各页签解耦**：
              · 实时模式不取建议（实时告警单站通常 0~2 行，去 UME 命中率低、噪声大）；
              · 历史/全量模式按当前 rangeDays 取最近告警的处理建议。
              数据来源与 eFlow QA → TT Quick Analysis 完全同源（后端复用 lookup_alarm）。 */}
          <AlarmSuggestionPanel
            siteId={selectedSite}
            days={Number(rangeDays) || DEFAULT_RANGE_DAYS}
            limit={20}
            enabled={mode === 'all'}
          />
        </div>
      ) : (
        <div style={{ color: WH.textMuted }}>{t('gis.drilldown.loadError')}</div>
      )}
    </Drawer>
  )
}
