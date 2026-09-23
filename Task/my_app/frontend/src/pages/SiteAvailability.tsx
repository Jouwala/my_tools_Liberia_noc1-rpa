import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Card, Table, Segmented, Button, Space, Alert, Tag, Typography, Input,
  Select, InputNumber, Checkbox, Statistic, Tooltip, Collapse, Empty,
} from 'antd'
import {
  ReloadOutlined, SearchOutlined, ProfileOutlined, InfoCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { exportAoaReport } from '../utils/excelReport'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { getSiteAvailabilityFilters, getSiteAvailabilityOverview, getSiteAvailabilityTickets } from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH, darkTooltip } from '../theme'
import DraggableClickModal from '../components/DraggableClickModal'

const { Text } = Typography

// ==================== 类型（与后端 site_availability_service 对齐） ====================
interface TechStat {
  month_avg: number | null
  min: number | null
  min_day?: string
  days_below: number
  days_with_data: number
  daily: Record<string, number>   // 'YYYY-MM-DD' -> 0~1
  weekly: Record<string, number>  // 'YYYY-Www' -> 0~1
}
interface SiteRow {
  site_id: string
  site_name: string
  region: string
  province_county: string
  network_type: string
  fme_name: string
  supervisor: string
  vip_site: string | number | boolean | null
  site_type: string
  techs: Record<string, TechStat>
  tickets: { total: number; open: number; closed: number }
}
interface WeekMeta { key: string; label: string; range: string; days: string[] }
interface OverviewResp {
  meta: {
    month: string; days: string[]; weeks: WeekMeta[]; tech: string
    threshold: number; generated_at: string; elapsed_seconds: number
    warnings: string[]
    sources: Record<string, { source: string; field: string; derived: boolean }>
  }
  summary: {
    site_count: number
    by_tech: Record<string, { avg: number | null; sites_with_data: number; sites_below: number; min: number | null }>
    ticket_total: number; ticket_open: number; ticket_closed: number
  }
  sites: SiteRow[]
}
interface FiltersResp {
  supervisors: string[]; fmes: string[]; months: string[]; site_count: number
}
interface TicketRow {
  tt_no: string; title: string; status: string; created_time: string
  alarm_occur_time: string; ticket_severity: string; alarm_category: string
  current_handler: string; sla_status: string; site_name: string; site_id: string
  site_outage: string; fault_duration_time: string; root_cause: string
  last_modified_time: string; open: boolean
}

const TECHS = ['G', 'U', 'L', 'Tdd'] as const
type Tech = typeof TECHS[number]
const TECH_LABEL: Record<string, string> = { G: '2G', U: '3G', L: '4G', Tdd: 'TDD' }
const DEFAULT_THRESHOLD = 0.9965 // 99.65%，与后端口径一致

const strSorter = (a: SiteRow, b: SiteRow, key: keyof SiteRow) =>
  String(a[key] ?? '').localeCompare(String(b[key] ?? ''))

// ==================== 页面 ====================
export default function SiteAvailability() {
  const { t } = useI18n()
  const { isDark, palette } = useTheme()

  // ---- 筛选器 ----
  const [filters, setFilters] = useState<FiltersResp | null>(null)
  const [month, setMonth] = useState<string>(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [supervisor, setSupervisor] = useState<string>('')
  const [fme, setFme] = useState<string>('')
  const [tech, setTech] = useState<Tech>('L')
  const [viewMode, setViewMode] = useState<'week' | 'day'>('week')
  const [thresholdPct, setThresholdPct] = useState<number>(DEFAULT_THRESHOLD * 100)
  const [onlyWithData, setOnlyWithData] = useState(false)
  const [search, setSearch] = useState('')

  // ---- 数据 ----
  const [overview, setOverview] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ---- 工单明细弹窗（可拖动 + 可导出） ----
  const [ticketSite, setTicketSite] = useState<SiteRow | null>(null)
  const [ticketRows, setTicketRows] = useState<TicketRow[]>([])
  const [ticketLoading, setTicketLoading] = useState(false)
  const [ticketAnchor, setTicketAnchor] = useState<{ x: number; y: number } | null>(null)

  const threshold = thresholdPct / 100

  useEffect(() => {
    getSiteAvailabilityFilters().then(r => {
      setFilters(r.data)
      if (r.data?.months?.length && !r.data.months.includes(month)) setMonth(r.data.months[r.data.months.length - 1])
    }).catch(() => { /* 筛选器失败不阻塞，overview 自带错误兜底 */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadOverview = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const r = await getSiteAvailabilityOverview({
        month, supervisor, fme, only_with_data: onlyWithData ? 1 : 0,
      })
      setOverview(r.data)
    } catch (e: any) {
      setError(e?.message || String(e))
      setOverview(null)
    } finally {
      setLoading(false)
    }
  }, [month, supervisor, fme, onlyWithData])

  useEffect(() => { loadOverview() }, [loadOverview])

  const openTickets = useCallback(async (s: SiteRow, anchor?: { x: number; y: number } | null) => {
    setTicketSite(s); setTicketLoading(true); setTicketRows([])
    setTicketAnchor(anchor ?? null)
    try {
      const r = await getSiteAvailabilityTickets({
        month, site_id: String(s.site_id ?? ''), site_name: String(s.site_name ?? ''),
      })
      setTicketRows(r.data?.rows || [])
    } catch { setTicketRows([]) } finally { setTicketLoading(false) }
  }, [month])

  // 工单明细导出 Excel（表头随界面语言）
  const exportTickets = useCallback(() => {
    if (!ticketSite || !ticketRows.length) return
    const cols: Array<{ h: string; get: (r: TicketRow) => any }> = [
      { h: t('siteAvail.ttNo'), get: r => r.tt_no },
      { h: t('siteAvail.titleCol'), get: r => r.title },
      { h: t('siteAvail.status'), get: r => r.status },
      { h: t('siteAvail.severity'), get: r => r.ticket_severity },
      { h: t('siteAvail.siteId'), get: r => r.site_id },
      { h: t('siteAvail.site'), get: r => r.site_name },
      { h: t('siteAvail.createdTime'), get: r => r.created_time },
      { h: t('siteAvail.alarmTime'), get: r => r.alarm_occur_time },
      { h: t('siteAvail.duration'), get: r => r.fault_duration_time },
      { h: t('siteAvail.outage'), get: r => r.site_outage },
      { h: 'SLA', get: r => r.sla_status },
      { h: t('siteAvail.handler'), get: r => r.current_handler },
      { h: t('siteAvail.rootCause'), get: r => r.root_cause },
      { h: t('siteAvail.lastModified'), get: r => r.last_modified_time },
    ]
    const header = cols.map(c => c.h)
    const rows = ticketRows.map(r => cols.map(c => {
      const v = c.get(r)
      return v == null ? '' : String(v)
    }))
    const safeName = String(ticketSite.site_name || 'site').replace(/[\\/:*?"<>|]/g, '_')
    const fname = `TT_${safeName}_${month}_${dayjs().format('YYYYMMDD_HHmmss')}`
    // 统一走 excelReport；站点名可能含非法字符，sheet 名由模块统一清洗
    void exportAoaReport({
      filename: `${fname}.xlsx`,
      sheetName: `TT_${safeName}`,
      title: 'Site Availability Tickets',
      header,
      rows,
      numericCols: [],
    })
  }, [ticketSite, ticketRows, month, t])

  // ---- 前端搜索过滤（站点名 / 站点 ID / Supervisor / FME） ----
  const sites = useMemo(() => {
    const all = overview?.sites || []
    if (!search.trim()) return all
    const kw = search.trim().toLowerCase()
    return all.filter(s =>
      String(s.site_name || '').toLowerCase().includes(kw) ||
      String(s.site_id || '').toLowerCase().includes(kw) ||
      String(s.supervisor || '').toLowerCase().includes(kw) ||
      String(s.fme_name || '').toLowerCase().includes(kw))
  }, [overview, search])

  const thresholdCmp = useCallback((v: number | null | undefined) =>
    v != null && v < threshold, [threshold])

  // 前端按当前制式重算未达标站点数（阈值可调，不必等后端）
  const belowSites = useMemo(() =>
    sites.filter(s => thresholdCmp(s.techs?.[tech]?.month_avg)).length,
    [sites, tech, thresholdCmp])
  const withDataSites = useMemo(() =>
    sites.filter(s => s.techs?.[tech]?.month_avg != null).length, [sites, tech])
  const avgOfTech = useMemo(() => {
    const vals = sites.map(s => s.techs?.[tech]?.month_avg).filter((v): v is number => v != null)
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  }, [sites, tech])

  // ---- 格式化 ----
  const fmtPct = (v: number | null | undefined, digits = 3) =>
    v == null || Number.isNaN(v) ? '-' : `${(v * 100).toFixed(digits)}%`

  // 单元格通用样式：低于阈值红、达标绿
  const valCell = (v: number | null | undefined, digits = 3) => {
    if (v == null || Number.isNaN(v)) return <Text type="secondary">-</Text>
    const bad = v < threshold
    return (
      <span style={{
        color: bad ? '#cf1322' : '#237804',
        background: bad ? 'rgba(207,19,34,0.10)' : 'rgba(35,120,4,0.08)',
        padding: '1px 6px', borderRadius: 4, fontWeight: 600,
        display: 'inline-block', minWidth: 72, textAlign: 'right',
        fontVariantNumeric: 'tabular-nums',
      }}>{(v * 100).toFixed(digits)}%</span>
    )
  }

  // ---- 展开行：所选制式日值趋势图 ----
  const trendOption = useCallback((s: SiteRow) => {
    const st = s.techs?.[tech]
    if (!st || !Object.keys(st.daily).length) return null
    const days = Object.keys(st.daily).sort()
    const vals = days.map(d => +(st.daily[d] * 100).toFixed(3))
    const weeks = overview?.meta.weeks || []
    // 周分隔背景（交替浅色带）
    const areas: any[] = []
    weeks.forEach((w, i) => {
      if (i % 2 === 1) {
        const first = w.days.find(d => (d in st.daily)) || w.days[0]
        const last = [...w.days].reverse().find(d => (d in st.daily)) || w.days[w.days.length - 1]
        areas.push([
          { xAxis: first }, { xAxis: last },
        ])
      }
    })
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', ...darkTooltip(isDark),
        valueFormatter: (v: number) => `${v}%` },
      grid: { left: 56, right: 20, top: 30, bottom: 56 },
      xAxis: {
        type: 'category', data: days.map(d => d.slice(5)),
        axisLabel: { color: isDark ? '#9fb3c8' : '#556', fontSize: 10, rotate: 45 },
        axisLine: { lineStyle: { color: isDark ? '#334' : '#ccc' } },
      },
      yAxis: {
        type: 'value', min: (v: { min: number }) => Math.max(0, Math.floor((v.min - 1) / 2) * 2),
        axisLabel: { color: isDark ? '#9fb3c8' : '#556', formatter: '{value}%' },
        splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)' } },
      },
      series: [{
        name: t('siteAvail.availSeries', { v: TECH_LABEL[tech] }),
        type: 'line', data: vals, smooth: false, symbol: 'circle', symbolSize: 5,
        lineStyle: { color: palette.teal, width: 2 },
        itemStyle: {
          color: (p: any) => (p.value / 100 < threshold ? '#cf1322' : palette.teal),
        },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: '#cf1322', type: 'dashed' },
          label: { formatter: `${t('siteAvail.threshold')} ${thresholdPct.toFixed(2)}%`, color: '#cf1322' },
          data: [{ yAxis: +thresholdPct.toFixed(3) }],
        },
        markArea: areas.length ? { silent: true, itemStyle: { color: isDark ? 'rgba(0, 217, 255,0.05)' : 'rgba(19,194,194,0.06)' }, data: areas } : undefined,
      }],
    }
  }, [tech, overview, threshold, thresholdPct, isDark, palette, t])

  // ---- 表格列 ----
  const columns = useMemo(() => {
    const cols: any[] = [
      {
        title: t('siteAvail.site'), key: 'site', fixed: 'left' as const, width: 220, sorter: strSorter as any,
        render: (_: any, s: SiteRow) => (
          <div>
            <div style={{ fontWeight: 600 }}>
              {s.site_name}
              {(s.vip_site === 1 || s.vip_site === true || String(s.vip_site).toLowerCase() === 'yes') && (
                <Tag color="gold" style={{ marginLeft: 6, marginRight: 0 }}>VIP</Tag>
              )}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>ID: {s.site_id || '-'}</Text>
          </div>
        ),
      },
      { title: 'Supervisor', dataIndex: 'supervisor', width: 140, sorter: strSorter as any,
        render: (v: string) => v || '-' },
      { title: 'FME', dataIndex: 'fme_name', width: 180, ellipsis: true, sorter: strSorter as any,
        render: (v: string) => v || '-' },
      { title: t('siteAvail.region'), dataIndex: 'region', width: 90, sorter: strSorter as any,
        render: (v: string) => v || '-' },
    ]
    // 四制式月均（始终展示，便于横向对比）
    for (const tk of TECHS) {
      cols.push({
        title: <Tooltip title={t('siteAvail.monthAvgTip', { v: TECH_LABEL[tk] })}>{t('siteAvail.monthAvg', { v: TECH_LABEL[tk] })}</Tooltip>,
        key: `avg_${tk}`, width: 108, align: 'right' as const,
        sorter: (a: SiteRow, b: SiteRow) => (a.techs?.[tk]?.month_avg ?? -1) - (b.techs?.[tk]?.month_avg ?? -1),
        render: (_: any, s: SiteRow) => valCell(s.techs?.[tk]?.month_avg),
      })
    }
    // 当前制式：最低值 / 未达标天
    cols.push({
      title: <Tooltip title={t('siteAvail.minTip', { v: TECH_LABEL[tech] })}>{t('siteAvail.min', { v: TECH_LABEL[tech] })}</Tooltip>,
      key: 'min', width: 100, align: 'right' as const,
      sorter: (a: SiteRow, b: SiteRow) => (a.techs?.[tech]?.min ?? -1) - (b.techs?.[tech]?.min ?? -1),
      render: (_: any, s: SiteRow) => {
        const st = s.techs?.[tech]
        if (!st || st.min == null) return <Text type="secondary">-</Text>
        return <Tooltip title={t('siteAvail.minDayTip', { v: st.min_day || '-' })}><span>{fmtPct(st.min)}</span></Tooltip>
      },
    }, {
      title: <Tooltip title={t('siteAvail.daysBelowTip', { v: thresholdPct.toFixed(2) })}>{t('siteAvail.daysBelow')}</Tooltip>,
      key: 'days_below', width: 90, align: 'right' as const,
      sorter: (a: SiteRow, b: SiteRow) => (a.techs?.[tech]?.days_below ?? 0) - (b.techs?.[tech]?.days_below ?? 0),
      render: (_: any, s: SiteRow) => {
        const st = s.techs?.[tech]
        if (!st || !st.days_with_data) return <Text type="secondary">-</Text>
        // 阈值前端可调：前端重算
        const n = Object.values(st.daily).filter(v => v < threshold).length
        return <Tag color={n > 0 ? 'red' : 'green'} style={{ marginInlineEnd: 0 }}>{n} / {st.days_with_data}{t('siteAvail.dayUnit')}</Tag>
      },
    })
    // 时间维度动态列：按周（自然周，首尾周裁剪到本月）/ 按天
    if (viewMode === 'week') {
      for (const w of (overview?.meta.weeks || [])) {
        cols.push({
          title: <Tooltip title={t('siteAvail.weekTip', { label: w.label, range: w.range })}>{w.label}<br /><Text type="secondary" style={{ fontSize: 11 }}>{w.range}</Text></Tooltip>,
          key: `w_${w.key}`, width: 104, align: 'right' as const,
          render: (_: any, s: SiteRow) => valCell(s.techs?.[tech]?.weekly?.[w.key]),
        })
      }
    } else {
      for (const d of (overview?.meta.days || [])) {
        cols.push({
          title: d.slice(8), // 只显示“日”
          key: `d_${d}`, width: 84, align: 'right' as const,
          onHeaderCell: () => ({ title: d }),
          render: (_: any, s: SiteRow) => valCell(s.techs?.[tech]?.daily?.[d]),
        })
      }
    }
    // 工单
    cols.push({
      title: t('siteAvail.ticketsCol'), key: 'tickets', fixed: 'right' as const, width: 130, align: 'center' as const,
      defaultSortOrder: 'descend' as const,
      sorter: (a: SiteRow, b: SiteRow) => a.tickets.total - b.tickets.total,
      render: (_: any, s: SiteRow) => (
        <Space size={4}>
          <span>
            <Text strong style={{ fontVariantNumeric: 'tabular-nums' }}>{s.tickets.total}</Text>
            {s.tickets.open > 0 && <Tag color="orange" style={{ marginLeft: 4, marginRight: 0 }}>{t('siteAvail.open')} {s.tickets.open}</Tag>}
          </span>
          <Button size="small" type="link" icon={<ProfileOutlined />}
            disabled={!s.tickets.total}
            onClick={(e) => openTickets(s, { x: e.clientX, y: e.clientY })} />
        </Space>
      ),
    })
    return cols
  }, [overview, tech, viewMode, threshold, thresholdPct, openTickets, valCell, t])

  const scrollX = useMemo(() => {
    const dyn = viewMode === 'week'
      ? (overview?.meta.weeks?.length || 0) * 104
      : (overview?.meta.days?.length || 0) * 84
    return 220 + 140 + 180 + 90 + 4 * 108 + 100 + 90 + dyn + 130
  }, [overview, viewMode])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* ==================== 筛选栏 ==================== */}
      <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
        <Space size={10} wrap align="center">
          <Select
            value={month} onChange={setMonth}
            options={(filters?.months || [month]).map(m => ({ value: m, label: m }))}
            style={{ width: 110 }} size="small" aria-label={t('siteAvail.month')}
          />
          <Select
            allowClear placeholder="Supervisor"
            value={supervisor || undefined}
            onChange={(v) => setSupervisor(v || '')}
            options={(filters?.supervisors || []).map(s => ({ value: s, label: s }))}
            style={{ minWidth: 180 }} size="small"
            popupMatchSelectWidth={false}
          />
          <Select
            allowClear placeholder="FME"
            value={fme || undefined}
            onChange={(v) => setFme(v || '')}
            options={(filters?.fmes || []).map(f => ({ value: f, label: f }))}
            style={{ minWidth: 200 }} size="small"
            popupMatchSelectWidth={false}
            showSearch optionFilterProp="label"
          />
          <Segmented
            size="small"
            value={tech}
            onChange={(v) => setTech(v as Tech)}
            options={TECHS.map(tk => ({ value: tk, label: TECH_LABEL[tk] }))}
          />
          <Segmented
            size="small"
            value={viewMode}
            onChange={(v) => setViewMode(v as 'week' | 'day')}
            options={[{ value: 'week', label: t('siteAvail.week') }, { value: 'day', label: t('siteAvail.day') }]}
          />
          <Tooltip title={t('siteAvail.daysBelowTip', { v: DEFAULT_THRESHOLD * 100 })}>
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('siteAvail.threshold')}</Text>
              <InputNumber size="small" min={0} max={100} step={0.01}
                value={thresholdPct} onChange={(v) => setThresholdPct(v ?? DEFAULT_THRESHOLD * 100)}
                addonAfter="%" style={{ width: 110 }} />
            </Space>
          </Tooltip>
          <Checkbox checked={onlyWithData}
            onChange={(e) => setOnlyWithData(e.target.checked)}>{t('siteAvail.onlyData')}</Checkbox>
          <Input size="small" allowClear prefix={<SearchOutlined />}
            placeholder={t('siteAvail.search')} value={search}
            onChange={(e) => setSearch(e.target.value)} style={{ width: 180 }} />
          <Button size="small" icon={<ReloadOutlined />} onClick={loadOverview}
            loading={loading}>{t('msSla.refresh')}</Button>
        </Space>
      </Card>

      {/* ==================== 汇总卡片 ==================== */}
      <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
        <Space size={36} wrap>
          <Statistic title={t('siteAvail.sites')} value={sites.length} suffix={`/ ${overview?.summary?.site_count ?? 0}`} />
          <Statistic title={t('siteAvail.monthAvg', { v: TECH_LABEL[tech] })}
            value={avgOfTech == null ? '-' : (avgOfTech * 100).toFixed(3)}
            suffix={avgOfTech == null ? '' : '%'}
            valueStyle={{ color: thresholdCmp(avgOfTech) ? '#cf1322' : '#237804' }} />
          <Statistic title={t('siteAvail.withData', { v: TECH_LABEL[tech] })} value={withDataSites} />
          <Statistic title={t('siteAvail.below', { v: TECH_LABEL[tech] })} value={belowSites}
            valueStyle={{ color: belowSites > 0 ? '#cf1322' : '#237804' }} />
          <Statistic title={t('siteAvail.monthTickets')} value={overview?.summary?.ticket_total ?? 0}
            suffix={<span style={{ fontSize: 13, color: '#fa8c16' }}>{t('siteAvail.open')} {overview?.summary?.ticket_open ?? 0}</span>} />
          <Statistic title={t('siteAvail.generatedAt')} value={overview?.meta?.generated_at || '-'}
            valueStyle={{ fontSize: 14 }} />
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={`${t('siteAvail.loadFailed')}${error}`} />}
      {(overview?.meta?.warnings || []).length > 0 && (
        <Alert type="warning" showIcon icon={<InfoCircleOutlined />}
          message={overview!.meta.warnings.join('；')} />
      )}

      {/* ==================== 站点主表 ==================== */}
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<SiteRow>
          size="small"
          rowKey={(s) => `${s.site_id}|${s.site_name}`}
          loading={loading}
          columns={columns}
          dataSource={sites}
          scroll={{ x: scrollX }}
          pagination={{
            pageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200],
            showTotal: (n) => t('siteAvail.totalSites', { v: n }),
          }}
          expandable={{
            expandedRowRender: (s) => {
              const opt = trendOption(s)
              return opt
                ? <ReactECharts option={opt} style={{ height: 260 }} notMerge />
                : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t('siteAvail.noDailyData', { v: TECH_LABEL[tech] })} />
            },
            rowExpandable: (s) => !!Object.keys(s.techs?.[tech]?.daily || {}).length,
          }}
        />
      </Card>

      {/* ==================== 数据说明（口径/字段/查询条件/时间范围） ==================== */}
      <Collapse
        size="small"
        items={[{
          key: 'doc',
          label: <><InfoCircleOutlined style={{ color: WH.teal, marginRight: 6 }} />{t('siteAvail.docTitle')}</>,
          children: (
            <div style={{ fontSize: 13, lineHeight: 1.9 }}>
              <p style={{ margin: 0 }}>{t('siteAvail.doc1')}</p>
              <p style={{ margin: 0 }}>{t('siteAvail.doc2')}</p>
              <p style={{ margin: 0 }}>{t('siteAvail.doc3')}</p>
              <p style={{ margin: 0 }}>{t('siteAvail.doc4')}</p>
              <p style={{ margin: 0 }}>{t('siteAvail.doc5')}</p>
            </div>
          ),
        }]}
      />

      {/* ==================== 工单明细弹窗（可拖动 + 可导出） ==================== */}
      <DraggableClickModal
        open={!!ticketSite}
        anchor={ticketAnchor}
        onClose={() => setTicketSite(null)}
        width={1100}
        title={
          <span>
            {ticketSite ? t('siteAvail.modalTitle', { v: ticketSite.site_name, m: month }) : ''}
            <Tag color="cyan" style={{ marginLeft: 8 }}>{t('common.records', { n: ticketRows.length })}</Tag>
          </span>
        }
      >
        {ticketSite && (
          <>
            <div style={{
              display: 'flex', flexWrap: 'wrap', alignItems: 'center',
              justifyContent: 'space-between', gap: 10, marginBottom: 10,
            }}>
              <Space size={12} wrap>
                <Tag color="orange">{t('siteAvail.open')} {ticketSite.tickets.open}</Tag>
                <Tag color="green">{t('siteAvail.closed')} {ticketSite.tickets.closed}</Tag>
                <Text type="secondary">Supervisor: {ticketSite.supervisor || '-'}　FME: {ticketSite.fme_name || '-'}</Text>
              </Space>
              <Button size="small" icon={<DownloadOutlined />}
                disabled={!ticketRows.length} onClick={exportTickets}>
                {t('common.exportExcel')}
              </Button>
            </div>
            <Table<TicketRow>
              size="small"
              rowKey="tt_no"
              loading={ticketLoading}
              dataSource={ticketRows}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              scroll={{ x: 1100 }}
              columns={[
                { title: t('siteAvail.ttNo'), dataIndex: 'tt_no', width: 150, fixed: 'left' as const },
                { title: t('siteAvail.titleCol'), dataIndex: 'title', ellipsis: true },
                { title: t('siteAvail.status'), dataIndex: 'status', width: 160,
                  render: (v: string, r: TicketRow) => <Tag color={r.open ? 'orange' : 'green'}>{v}</Tag> },
                { title: t('siteAvail.severity'), dataIndex: 'ticket_severity', width: 76 },
                { title: t('siteAvail.createdTime'), dataIndex: 'created_time', width: 150 },
                { title: t('siteAvail.duration'), dataIndex: 'fault_duration_time', width: 100 },
                { title: 'SLA', dataIndex: 'sla_status', width: 70,
                  render: (v: string) => v === 'Pass' ? <Tag color="green">Pass</Tag> : <Tag color="red">{v || '-'}</Tag> },
                { title: t('siteAvail.handler'), dataIndex: 'current_handler', width: 130, ellipsis: true },
                { title: t('siteAvail.outage'), dataIndex: 'site_outage', width: 90,
                  render: (v: string) => v === 'Yes' ? <Tag color="red">Yes</Tag> : <Tag>{v || '-'}</Tag> },
              ]}
            />
          </>
        )}
      </DraggableClickModal>
    </div>
  )
}
