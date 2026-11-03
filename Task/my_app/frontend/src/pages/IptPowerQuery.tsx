/* ============================================================================
 * IPT 站点电源查询（?page=ipt_power）—— 2026-11-03 新增
 * ============================================================================
 * 数据链路（三段，口径见页内「数据口径说明」）：
 *   1. 采集：任务 ipt_power_collect 每 2 分钟直连 IPT Digital Platform（RMS 能源监控），
 *      filter-map 刷全站（~498 站）连接状态 → ipt_power_sites；
 *      按 watch_sites.json 关注清单逐站拉 diagram 电源全景 → ipt_power_snapshots。
 *   2. 本页主表：读 ipt_power_sites + 最新快照（/api/ipt-power/sites）。
 *   3. 详情/曲线：读单站快照序列（/api/ipt-power/site/{id}）；「立即刷新」为实时
 *      直查 portal（/api/ipt-power/refresh），不依赖 2 分钟节拍。
 * 查询条件（keyword / hours / site）走 urlState，跨卸载恢复（AGENTS.md 约定）。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, Empty, Input, Row, Select, Space, Spin, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import {
  WH, useTheme, cardStyle,
  axisLabel, axisLine, darkTooltip, splitLine,
} from '../theme'
import { CardBase, StatCard } from '../components/cards'
import CalcChainNote from '../components/CalcChainNote'
import { exportAoaReport } from '../utils/excelReport'
import { readParam, writeParams } from '../urlState'
import {
  iptPowerRefresh, iptPowerSiteDetail, iptPowerSites, iptPowerStatus,
} from '../api'

const { Text } = Typography

/** 统一空值展示 */
const fmt = (v: unknown) => (v == null || v === '' ? '-' : String(v))
const fmtNum = (v: unknown, digits = 1) =>
  (v == null || v === '' ? '-' : Number(v).toFixed(digits))

/* ---- 类型（与后端 routers/ipt_power.py 返回对齐） ---- */
type SiteRow = {
  site_id: string; name: string; internal_reference: string
  organization: string; cluster: string; priority: string; configuration: string
  connectivity: string; criticality: string; lat: number; lon: number
  connectivity_updated: string; updated_at: string
  snap_time: string; load_current: number; load_power: number
  battery_voltage: number; battery_soc: number; battery_charging_state: string
  solar_power: number; generator_on: number; fuel_ratio: number
  watched: boolean
}
type HistoryRow = {
  snap_time: string; load_current: number; load_power: number
  battery_voltage: number; battery_current: number; battery_power: number
  battery_soc: number; battery_charging_state: string; battery_temp1: number
  generator_on: number; solar_power: number; solar_current: number
  fuel_level: number; fuel_ratio: number; grid_on: number
}
type StatusInfo = {
  last_run: null | {
    time: string; success: boolean; sites: number; snapshots: number
    snap_failed: number; watch: number; duration_s: number
    rows_ipt_power_sites?: number; rows_ipt_power_snapshots?: number
    last_snapshot?: string
  }
}

const HOURS_OPTIONS = [6, 24, 72, 168]

export default function IptPowerQuery() {
  const { t } = useI18n()
  const { isDark } = useTheme()

  /* ---- 查询条件（URL 是唯一真相源） ---- */
  const [keyword, setKeyword] = useState(() => readParam('iptKw'))
  const [hours, setHours] = useState<number>(() => {
    const v = Number(readParam('iptHrs'))
    return HOURS_OPTIONS.includes(v) ? v : 24
  })
  const [watchOnly, setWatchOnly] = useState(false)
  const [siteId, setSiteId] = useState(() => readParam('iptSite'))

  useEffect(() => { writeParams({ iptKw: keyword, iptSite: siteId, iptHrs: String(hours) }) },
    [keyword, siteId, hours])

  /* ---- 数据三件套 ---- */
  const [rows, setRows] = useState<SiteRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusInfo, setStatusInfo] = useState<StatusInfo>({ last_run: null })

  /* ---- 选中站点详情 ---- */
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailSite, setDetailSite] = useState<SiteRow | null>(null)
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')

  const loadSites = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await iptPowerSites({ keyword: keyword || undefined, limit: 1000 })
      setRows(r.data?.sites || [])
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [keyword])

  const loadStatus = useCallback(async () => {
    try {
      const r = await iptPowerStatus()
      setStatusInfo({ last_run: r.data?.last_run || null })
    } catch { /* 状态条失败不阻塞主数据 */ }
  }, [])

  const loadDetail = useCallback(async (sid: string) => {
    setDetailLoading(true)
    try {
      const r = await iptPowerSiteDetail(sid, hours)
      setDetailSite(r.data?.site || null)
      setHistory(r.data?.history || [])
    } catch (e: any) {
      setRefreshMsg(e?.response?.data?.detail || e?.message || String(e))
      setHistory([])
    } finally {
      setDetailLoading(false)
    }
  }, [hours])

  useEffect(() => { void loadSites(); void loadStatus() }, [loadSites, loadStatus])
  useEffect(() => {
    if (siteId) void loadDetail(siteId)
    else { setDetailSite(null); setHistory([]) }
  }, [siteId, loadDetail])

  /* ---- 立即刷新：实时直查 portal（按站点名，后端自动落一条快照） ---- */
  const doRefresh = useCallback(async () => {
    if (!detailSite) return
    setRefreshing(true)
    setRefreshMsg('')
    try {
      await iptPowerRefresh(detailSite.name)
      await loadDetail(detailSite.site_id)
      await loadSites()
      await loadStatus()
    } catch (e: any) {
      setRefreshMsg(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setRefreshing(false)
    }
  }, [detailSite, loadDetail, loadSites, loadStatus])

  /* ---- 汇总 ---- */
  const stats = useMemo(() => ({
    total: rows.length,
    online: rows.filter(r => r.connectivity === 'online').length,
    offline: rows.filter(r => r.connectivity === 'offline').length,
    watched: rows.filter(r => r.watched).length,
  }), [rows])

  /* ---- 曲线：左轴功率（W），右轴 SOC（%）与电压（V/10 → 用同一 % 轴不合适，电压放独立系列右轴）----
   * 简化为双 y 轴：左 = load_power / solar_power（W），右 = battery_soc（%，0-1 → ×100）。
   * 电压/温度走详情数字卡，不进曲线（量纲太多互相压扁）。 */
  const chartOption = useMemo(() => {
    const xs = history.map(h => (h.snap_time || '').slice(5, 16))
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
      legend: { textStyle: { color: isDark ? '#d0d7de' : '#444' }, top: 0 },
      grid: { left: 56, right: 56, top: 36, bottom: 56 },
      xAxis: {
        type: 'category', data: xs,
        axisLabel: { ...axisLabel(isDark), rotate: 35 },
        axisLine: axisLine(isDark),
      },
      yAxis: [
        { type: 'value', name: 'W', axisLabel: axisLabel(isDark), splitLine: splitLine(isDark) },
        { type: 'value', name: '%', min: 0, max: 100, position: 'right',
          axisLabel: axisLabel(isDark), splitLine: { show: false } },
      ],
      series: [
        { name: t('ipt.series.load'), type: 'line', showSymbol: false, smooth: true,
          data: history.map(h => h.load_power), itemStyle: { color: isDark ? '#00d9ff' : '#0d9488' } },
        { name: t('ipt.series.solar'), type: 'line', showSymbol: false, smooth: true,
          data: history.map(h => h.solar_power), itemStyle: { color: isDark ? '#ffd666' : '#d48806' } },
        { name: t('ipt.series.soc'), type: 'line', yAxisIndex: 1, showSymbol: false, smooth: true,
          data: history.map(h => (h.battery_soc == null ? null : Number(h.battery_soc) * 100)),
          itemStyle: { color: isDark ? '#ff7a45' : '#d4380d' } },
      ],
    }
  }, [history, isDark, t])

  const exportRows = useCallback(() => {
    if (!rows.length) return
    void exportAoaReport({
      filename: `ipt_power_sites_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: 'IPT Power Sites',
      title: 'IPT Power Sites',
      header: [
        t('ipt.col.name'), t('ipt.col.ref'), t('ipt.col.org'), t('ipt.col.cluster'),
        t('ipt.col.priority'), t('ipt.col.config'), t('ipt.col.connectivity'),
        'SOC %', t('ipt.col.load'), t('ipt.col.solar'), t('ipt.col.snapTime'),
      ],
      rows: rows.map(r => [
        r.name, r.internal_reference, r.organization, r.cluster, r.priority,
        r.configuration, r.connectivity,
        r.battery_soc == null ? '' : Number(r.battery_soc) * 100,
        r.load_power, r.solar_power, r.snap_time,
      ]),
      numericCols: [7, 8, 9],
    })
  }, [rows, t])

  const columns = useMemo(() => [
    { title: t('ipt.col.name'), dataIndex: 'name',
      render: (v: string, r: SiteRow) => (
        <Space size={4}>
          {r.watched && <ThunderboltOutlined style={{ color: WH.warn }} />}
          <Text strong style={{ color: WH.text }}>{v}</Text>
        </Space>
      ) },
    { title: t('ipt.col.ref'), dataIndex: 'internal_reference', width: 80, render: fmt },
    { title: t('ipt.col.org'), dataIndex: 'organization', width: 120, render: fmt },
    { title: t('ipt.col.priority'), dataIndex: 'priority', width: 70, render: fmt },
    { title: t('ipt.col.config'), dataIndex: 'configuration', width: 90, render: fmt },
    { title: t('ipt.col.connectivity'), dataIndex: 'connectivity', width: 90,
      render: (v: string) => v === 'online'
        ? <Tag color="green">online</Tag>
        : <Tag color="red">{fmt(v)}</Tag> },
    { title: 'SOC', dataIndex: 'battery_soc', width: 80,
      sorter: (a: SiteRow, b: SiteRow) => (a.battery_soc || 0) - (b.battery_soc || 0),
      render: (v: number) => v == null ? '-' : `${(v * 100).toFixed(0)}%` },
    { title: t('ipt.col.load'), dataIndex: 'load_power', width: 100,
      sorter: (a: SiteRow, b: SiteRow) => (a.load_power || 0) - (b.load_power || 0),
      render: (v: number) => v == null ? '-' : `${fmtNum(v, 0)} W` },
    { title: t('ipt.col.solar'), dataIndex: 'solar_power', width: 100,
      render: (v: number) => v == null ? '-' : `${fmtNum(v, 0)} W` },
    { title: t('ipt.col.snapTime'), dataIndex: 'snap_time', width: 150, render: fmt },
    {
      title: t('ipt.col.action'), key: 'action', width: 90,
      render: (_: unknown, r: SiteRow) => (
        <Button type="link" size="small" onClick={() => setSiteId(r.site_id)}>
          {t('ipt.detail')}
        </Button>
      ),
    },
  ], [t])

  const latest = history.length ? history[history.length - 1] : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder={t('ipt.search')}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={() => void loadSites()}
            style={{ width: 240 }}
          />
          <Select
            value={hours}
            onChange={setHours}
            options={HOURS_OPTIONS.map(h => ({ value: h, label: t('ipt.hours', { n: h }) }))}
            style={{ width: 120 }}
          />
          <Button
            type={watchOnly ? 'primary' : 'default'}
            icon={<ThunderboltOutlined />}
            onClick={() => setWatchOnly(v => !v)}
          >
            {t('ipt.watchOnly')}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void loadSites()} loading={loading}>
            {t('common.refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {/* ② 采集状态：异常（任务没跑过/失败）常驻可见；正常收进口径说明 */}
      {error && <Alert type="error" showIcon message={error} />}
      {statusInfo.last_run && !statusInfo.last_run.success && (
        <Alert type="warning" showIcon
          message={t('ipt.statusFailed', { time: statusInfo.last_run.time })} />
      )}
      {!statusInfo.last_run && (
        <Alert type="warning" showIcon message={t('ipt.statusNever')} />
      )}

      {/* ③ 数字卡 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('ipt.kpi.total')} value={stats.total} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('ipt.kpi.online')} value={stats.online} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <CardBase level={stats.offline > 0 ? 'warn' : 'ok'} title={t('ipt.kpi.offline')} as="div">
            <Text strong style={{ fontSize: 24, color: stats.offline > 0 ? WH.danger : WH.ok }}>
              {stats.offline}
            </Text>
          </CardBase>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('ipt.kpi.watched')} value={stats.watched} />
        </Col>
      </Row>

      {/* ④ 站点表 */}
      <CardBase title={t('ipt.table.title')} interactive={false}>
        <Table
          rowKey="site_id"
          columns={columns}
          dataSource={watchOnly ? rows.filter(r => r.watched) : rows}
          loading={loading}
          pagination={{ pageSize: 15, showSizeChanger: true }}
          scroll={{ x: 1100 }}
          size="small"
        />
      </CardBase>

      {/* ⑤ 详情：最新快照 + 曲线（口径说明默认收起） */}
      <CardBase
        title={detailSite
          ? t('ipt.detailTitle', { name: detailSite.name })
          : t('ipt.detailTitleEmpty')}
        extra={detailSite && (
          <Space size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('ipt.refLabel')}: {fmt(detailSite.internal_reference)}
              {detailSite.connectivity_updated
                ? ` · ${t('ipt.connUpdated')}: ${detailSite.connectivity_updated}` : ''}
            </Text>
            <Button size="small" icon={<ReloadOutlined />}
              onClick={() => void doRefresh()} loading={refreshing}>
              {t('ipt.refreshNow')}
            </Button>
          </Space>
        )}
      >
        <CalcChainNote
          title={t('ipt.note.title')}
          sections={[
            { title: t('ipt.note.source'), lines: [t('ipt.note.sourceBody')] },
            { title: t('ipt.note.watch'), lines: [t('ipt.note.watchBody')] },
            { title: t('ipt.note.retention'), lines: [t('ipt.note.retentionBody')] },
          ]}
        />
        {refreshMsg && <Alert type="error" showIcon message={refreshMsg}
          style={{ marginTop: 'var(--wh-space-sm)' }} closable />}
        {!detailSite && !detailLoading && (
          <Empty description={t('ipt.pickSite')} style={{ margin: '32px 0' }} />
        )}
        {detailSite && (
          <Spin spinning={detailLoading}>
            <Row gutter={[12, 12]} style={{ marginTop: 'var(--wh-space-sm)' }}>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title="SOC" value={latest?.battery_soc == null ? '-' : `${(Number(latest.battery_soc) * 100).toFixed(0)}%`} />
              </Col>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title={t('ipt.card.battV')} value={latest?.battery_voltage == null ? '-' : `${fmtNum(latest.battery_voltage)} V`} />
              </Col>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title={t('ipt.card.charging')} value={fmt(latest?.battery_charging_state)} />
              </Col>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title={t('ipt.card.load')} value={latest?.load_power == null ? '-' : `${fmtNum(latest.load_power, 0)} W`} />
              </Col>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title={t('ipt.card.solar')} value={latest?.solar_power == null ? '-' : `${fmtNum(latest.solar_power, 0)} W`} />
              </Col>
              <Col xs={12} sm={8} lg={4}>
                <StatCard title={t('ipt.card.generator')} value={latest == null
                  ? '-' : (latest.generator_on ? t('ipt.genOn') : t('ipt.genOff'))} />
              </Col>
            </Row>
            {history.length
              ? <ReactECharts option={chartOption} style={{ height: 320 }} notMerge />
              : <Empty description={t('ipt.noHistory')} style={{ margin: '24px 0' }} />}
          </Spin>
        )}
      </CardBase>
    </div>
  )
}

/* cardStyle 引用保留（避免 lint 未使用告警的写法）：表格行内不套卡，详情页由 CardBase 承载 */
void cardStyle
