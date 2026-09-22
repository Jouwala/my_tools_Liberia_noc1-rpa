import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, SearchOutlined, TrophyOutlined } from '@ant-design/icons'
import * as XLSX from 'xlsx'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { getFmeRankingFilters, getFmeRankingOverview } from '../api'
import { useI18n, numLocale } from '../i18n'
import { useTheme, WH, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, pageWrap } from '../theme'

const { Text, Title } = Typography

type FmeRow = {
  fme_name: string
  supervisors: string[]
  site_count: number
  sites_with_availability: number
  availability: number | null
  sites_below_threshold: number
  wo_total: number
  wo_open: number
  wo_closed: number
  availability_rank: number
  wo_rank: number
}
type Overview = {
  meta: { month: string; tech: string; threshold: number; generated_at?: string; elapsed_seconds?: number; warnings?: string[]; wo?: { source_rows: number; matched_rows: number; unmatched_rows: number; time_field: string } }
  summary: { fme_count: number; site_count: number; sites_with_availability: number; wo_total: number; wo_open: number; wo_closed: number }
  rows: FmeRow[]
}
type Filters = { months?: string[]; supervisors?: string[]; fmes?: string[] }

const TECHS = [{ value: 'G', label: '2G' }, { value: 'U', label: '3G' }, { value: 'L', label: '4G' }, { value: 'Tdd', label: 'TDD' }]

const fmt = (value: unknown) => value == null || value === '' ? '-' : String(value)

export default function FmeRanking() {
  const { t, locale } = useI18n()
  const { isDark, palette } = useTheme()
  const [filters, setFilters] = useState<Filters>({})
  const [month, setMonth] = useState(() => dayjs().format('YYYY-MM'))
  const [tech, setTech] = useState('L')
  const [supervisor, setSupervisor] = useState('')
  const [fme, setFme] = useState('')
  const [search, setSearch] = useState('')
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getFmeRankingFilters().then(res => {
      const next = res.data || {}
      setFilters(next)
      if (next.months?.length && !next.months.includes(month)) setMonth(next.months[next.months.length - 1])
    }).catch(() => undefined)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await getFmeRankingOverview({ month, tech, supervisor, fme })
      setData(res.data)
      if (res.data?.error) setError(res.data.error)
    } catch (err: any) {
      setData(null); setError(err?.message || String(err))
    } finally { setLoading(false) }
  }, [month, tech, supervisor, fme])
  useEffect(() => { load() }, [load])

  const rows = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return data?.rows || []
    return (data?.rows || []).filter(row => row.fme_name.toLowerCase().includes(keyword) || row.supervisors.join(' ').toLowerCase().includes(keyword))
  }, [data, search])

  const fmtPct = (value: number | null) => value == null ? '-' : `${(value * 100).toFixed(3)}%`
  const valueColor = (value: number | null) => value != null && value < (data?.meta.threshold ?? 0.9965) ? WH.danger : WH.ok

  const exportRows = useCallback(() => {
    if (!rows.length) return
    const header = [t('fme.col.rank'), t('fme.col.fme'), t('fme.col.supervisor'), t('fme.col.sites'), t('fme.col.availability'), t('fme.col.below'), t('fme.col.wo'), t('fme.col.open'), t('fme.col.closed'), t('fme.col.woRank')]
    const body = rows.map(row => [row.availability_rank, row.fme_name, row.supervisors.join(', '), row.site_count, fmtPct(row.availability), row.sites_below_threshold, row.wo_total, row.wo_open, row.wo_closed, row.wo_rank])
    const ws = XLSX.utils.aoa_to_sheet([header, ...body]); ws['!cols'] = header.map((_, i) => ({ wch: i === 1 ? 24 : 16 }))
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, 'FME Ranking')
    XLSX.writeFile(wb, `FME_Ranking_${month}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
  }, [rows, month, t])

  const chart = useMemo(() => {
    const chartRows = rows.slice(0, 15)
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0, textStyle: { color: isDark ? '#aebbd4' : '#3f5468' } },
      grid: { left: 54, right: 56, top: 20, bottom: 58 },
      xAxis: { type: 'category', data: chartRows.map(row => row.fme_name), axisLabel: { ...axisLabel(isDark), rotate: 35, interval: 0 }, axisLine: axisLine(isDark) },
      yAxis: [{ type: 'value', name: t('fme.axis.availability'), min: 95, max: 100, axisLabel: { ...axisLabel(isDark), formatter: '{value}%' }, splitLine: splitLine(isDark) }, { type: 'value', name: t('fme.axis.wo'), axisLabel: axisLabel(isDark), splitLine: { show: false } }],
      series: [
        { name: t('fme.availability'), type: 'bar', data: chartRows.map(row => row.availability == null ? null : +(row.availability * 100).toFixed(3)), itemStyle: { color: palette.teal, borderRadius: [4, 4, 0, 0] } },
        { name: t('fme.wo'), type: 'line', yAxisIndex: 1, data: chartRows.map(row => row.wo_total), smooth: true, symbol: 'circle', itemStyle: { color: palette.blue }, lineStyle: { width: 2 } },
      ],
    }
  }, [rows, isDark, palette, t])

  const columns = [
    { title: t('fme.col.rank'), dataIndex: 'availability_rank', width: 72, sorter: (a: FmeRow, b: FmeRow) => a.availability_rank - b.availability_rank, render: (v: number) => v <= 3 ? <Tag color={v === 1 ? 'gold' : v === 2 ? 'blue' : 'purple'} icon={<TrophyOutlined />}>{v}</Tag> : v },
    { title: t('fme.col.fme'), dataIndex: 'fme_name', fixed: 'left' as const, width: 190, sorter: (a: FmeRow, b: FmeRow) => a.fme_name.localeCompare(b.fme_name), render: (v: string) => <Text strong>{fmt(v)}</Text> },
    { title: t('fme.col.supervisor'), dataIndex: 'supervisors', width: 150, render: (v: string[]) => fmt(v?.join(', ')) },
    { title: t('fme.col.sites'), dataIndex: 'site_count', width: 95, sorter: (a: FmeRow, b: FmeRow) => a.site_count - b.site_count, render: (v: number, row: FmeRow) => <Tooltip title={`${row.sites_with_availability} ${t('fme.withData')}`}>{v}</Tooltip> },
    { title: t('fme.col.availability'), dataIndex: 'availability', width: 130, sorter: (a: FmeRow, b: FmeRow) => (a.availability ?? -1) - (b.availability ?? -1), render: (v: number | null) => <span style={{ color: valueColor(v), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(v)}</span> },
    { title: t('fme.col.below'), dataIndex: 'sites_below_threshold', width: 110, sorter: (a: FmeRow, b: FmeRow) => a.sites_below_threshold - b.sites_below_threshold },
    { title: t('fme.col.wo'), dataIndex: 'wo_total', width: 100, sorter: (a: FmeRow, b: FmeRow) => a.wo_total - b.wo_total, render: (v: number) => <Text strong>{v.toLocaleString(numLocale(locale))}</Text> },
    { title: t('fme.col.open'), dataIndex: 'wo_open', width: 95, render: (v: number) => v ? <Tag color="red">{v}</Tag> : 0 },
    { title: t('fme.col.closed'), dataIndex: 'wo_closed', width: 95 },
    { title: t('fme.col.woRank'), dataIndex: 'wo_rank', width: 100, sorter: (a: FmeRow, b: FmeRow) => a.wo_rank - b.wo_rank, render: (v: number) => <Tag color="cyan">{v}</Tag> },
  ]

  return <div style={pageWrap}>
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" style={cardStyle}>
        <Space wrap>
          <Select value={month} onChange={setMonth} options={(filters.months || [month]).map(v => ({ value: v, label: v }))} style={{ width: 130 }} aria-label={t('fme.month')} />
          <Select value={tech} onChange={setTech} options={TECHS.map(item => ({ ...item, label: t(`fme.tech.${item.value}`) }))} style={{ width: 120 }} aria-label={t('fme.tech')} />
          <Select allowClear showSearch value={supervisor || undefined} onChange={v => setSupervisor(v || '')} options={(filters.supervisors || []).map(v => ({ value: v, label: v }))} placeholder={t('fme.supervisor')} style={{ width: 170 }} />
          <Select allowClear showSearch value={fme || undefined} onChange={v => setFme(v || '')} options={(filters.fmes || []).map(v => ({ value: v, label: v }))} placeholder={t('fme.fme')} style={{ width: 170 }} />
          <Input allowClear prefix={<SearchOutlined />} value={search} onChange={e => setSearch(e.target.value)} placeholder={t('fme.search')} style={{ width: 190 }} />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('fme.refresh')}</Button>
          <Button icon={<DownloadOutlined />} onClick={exportRows} disabled={!rows.length}>{t('fme.export')}</Button>
        </Space>
      </Card>
      {error && <Alert type="error" showIcon message={error} />}
      {data?.meta.warnings?.map(w => <Alert key={w} type="warning" showIcon message={w} />)}
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={6}><Card style={cardStyle}><Statistic title={t('fme.stat.fme')} value={data?.summary.fme_count || 0} /></Card></Col>
        <Col xs={12} sm={6}><Card style={cardStyle}><Statistic title={t('fme.stat.sites')} value={data?.summary.site_count || 0} /></Card></Col>
        <Col xs={12} sm={6}><Card style={cardStyle}><Statistic title={t('fme.stat.wo')} value={data?.summary.wo_total || 0} valueStyle={{ color: palette.blue }} /></Card></Col>
        <Col xs={12} sm={6}><Card style={cardStyle}><Statistic title={t('fme.stat.open')} value={data?.summary.wo_open || 0} valueStyle={{ color: data?.summary.wo_open ? WH.danger : WH.ok }} /></Card></Col>
      </Row>
      <Card title={<Title level={5} style={{ margin: 0, color: WH.text }}>{t('fme.chartTitle')}</Title>} style={cardStyle}>
        {rows.length ? <ReactECharts option={chart} style={{ height: 330 }} notMerge /> : <Empty description={t('fme.noData')} />}
      </Card>
      <Card title={t('fme.tableTitle')} extra={<Text type="secondary">{t('fme.generated', { v: data?.meta.generated_at || '-' })}</Text>} style={cardStyle}>
        <Table rowKey="fme_name" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 20, showSizeChanger: true }} scroll={{ x: 1180 }} size="small" />
      </Card>
      {data?.meta.wo && <Text type="secondary">{t('fme.woMeta', { source: data.meta.wo.source_rows, matched: data.meta.wo.matched_rows, unmatched: data.meta.wo.unmatched_rows, field: data.meta.wo.time_field || '-' })}</Text>}
    </Space>
  </div>
}
