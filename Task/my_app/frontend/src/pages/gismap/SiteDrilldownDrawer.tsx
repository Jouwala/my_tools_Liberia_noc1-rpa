import { useMemo, useState } from 'react'
import { Card, Row, Col, Drawer, Descriptions, Tag, Statistic, Tabs, Spin } from 'antd'
import { AlertOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useI18n } from '../../i18n'
import { WH, cardStyle } from '../../theme'
import { SearchableExportTable } from '../../components/SearchableExportTable'
import type { DrilldownData } from './types'
import { filterBySearch, exportToExcel, buildAlarmColumns, buildTTColumns, buildWOColumns } from './helpers'

interface SiteDrilldownDrawerProps {
  open: boolean
  onClose: () => void
  loading: boolean
  drilldown: DrilldownData | null
  selectedSite: string
  mode: 'all' | 'realtime'
}

// 站点下钻抽屉：基本信息 + 统计卡片 + RT/His Alarm、TT、WO 明细表格
export function SiteDrilldownDrawer({ open, onClose, loading, drilldown, selectedSite, mode }: SiteDrilldownDrawerProps) {
  const { t } = useI18n()
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

  return (
    <Drawer
      title={
        <span style={{ color: WH.text }}>
          {t('gis.drilldown.title')} - {drilldown?.site_info?.site_name || selectedSite}
          {drilldown?.site_info?.vip_site === 'Yes' && <Tag color="purple" style={{ marginLeft: 8 }}>VIP</Tag>}
        </span>
      }
      styles={{
        wrapper: { width: 720 },
        body: { background: WH.bg },
        header: { background: '#0a1929', borderBottom: '1px solid rgba(100,255,218,0.15)' },
      }}
      open={open}
      onClose={onClose}
    >
      {loading ? (
        <Spin style={{ display: 'block', margin: '50px auto' }} />
      ) : drilldown ? (
        <div>
          <Card size="small" title={<span style={{ color: WH.text }}>{t('gis.drilldown.basicInfo')}</span>} style={{ ...cardStyle, marginBottom: 16 }}>
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
                {drilldown.site_info.vip_site === 'Yes' || drilldown.site_info.vip_site === 'Y'
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

          <Row gutter={8} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.totalTT')}</span>} value={drilldown.tt_count} valueStyle={{ color: WH.teal, fontWeight: 700 }} /></Card>
            </Col>
            <Col span={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.totalWO')}</span>} value={drilldown.wo_count} valueStyle={{ color: WH.blue, fontWeight: 700 }} /></Card>
            </Col>
            <Col span={6}>
              <Card size="small" style={cardStyle}><Statistic title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.rtAlarm')}</span>} value={drilldown.rt_alarm_count} valueStyle={{ color: drilldown.rt_alarm_count > 0 ? '#ff6b6b' : WH.text, fontWeight: 700 }} /></Card>
            </Col>
            <Col span={6}>
              <Card size="small" style={cardStyle}>
                <Statistic
                  title={<span style={{ color: WH.textMuted }}>{t('gis.drilldown.slaAchievement')}</span>}
                  value={
                    drilldown.sla_stats.total_tt > 0
                      ? Math.round((drilldown.sla_stats.sla_met || 0) / drilldown.sla_stats.total_tt * 100)
                      : 0
                  }
                  suffix="%"
                  valueStyle={{ color: WH.teal, fontWeight: 700 }}
                />
              </Card>
            </Col>
          </Row>

          <Tabs
            items={[
              {
                key: 'rt_alarm',
                label: <span style={{ color: WH.text }}><ThunderboltOutlined style={{ color: '#ff6b6b' }} /> {t('gis.drilldown.rtAlarmTab')} ({drilldown.rt_alarm_count})</span>,
                children: (
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
                ),
              },
              ...(mode === 'all' ? [{
                key: 'his_alarm',
                label: <span style={{ color: WH.text }}><AlertOutlined style={{ color: '#ffa94d' }} /> {t('gis.drilldown.hisAlarmTab')} ({drilldown.his_alarm_count})</span>,
                children: (
                  <SearchableExportTable
                    data={filteredHisAlarm}
                    columns={hisAlarmColumns}
                    search={hisAlarmSearch}
                    onSearchChange={setHisAlarmSearch}
                    onExport={() => exportToExcel(filteredHisAlarm, `His_Alarm_${drilldown.site_info?.site_name || selectedSite}`, hisAlarmColumns)}
                    exportText={t('gis.exportHIS')}
                    rowKey={(r: any, i?: number) => `his-${r.alarmraisedtime}-${i}`}
                    ariaLabel={t('gis.drilldown.hisAlarmTab')}
                  />
                ),
              }] : []),
              {
                key: 'tt',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.ttTab')} ({drilldown.tt_count})</span>,
                children: (
                  <SearchableExportTable
                    data={filteredTT}
                    columns={ttColumns}
                    search={ttSearch}
                    onSearchChange={setTtSearch}
                    onExport={() => exportToExcel(filteredTT, `TT_${drilldown.site_info?.site_name || selectedSite}`, ttColumns)}
                    exportText={t('gis.exportTT')}
                    rowKey={(r: any, i?: number) => `${r.title}-${i}`}
                    ariaLabel={t('gis.drilldown.ttTab')}
                  />
                ),
              },
              {
                key: 'wo',
                label: <span style={{ color: WH.text }}>{t('gis.drilldown.woTab')} ({drilldown.wo_count})</span>,
                children: (
                  <SearchableExportTable
                    data={filteredWO}
                    columns={woColumns}
                    search={woSearch}
                    onSearchChange={setWoSearch}
                    onExport={() => exportToExcel(filteredWO, `WO_${drilldown.site_info?.site_name || selectedSite}`, woColumns)}
                    exportText={t('gis.exportWO')}
                    rowKey={(r: any, i?: number) => `${r.wo_no}-${i}`}
                    ariaLabel={t('gis.drilldown.woTab')}
                  />
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
