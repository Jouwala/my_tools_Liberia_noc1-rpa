import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Row, Col, Select, Spin, Button, Input, message, Tag, Space, Tooltip } from 'antd'
import { FilterOutlined, FilterFilled } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n } from '../i18n'
import { useDataTimestamps } from '../useDataTimestamps'

interface ChartData {
  type: string
  title: string
  column?: string
  x_column?: string
  y_column?: string
  x_labels?: string[]
  y_labels?: string[]
  data: any[]
}

// 统一卡片样式
const chartCardStyle = { borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.04)', border: '1px solid #f0f0f0' }
const controlBarStyle = { borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.04)', border: '1px solid #f0f0f0', marginBottom: 16 }

export default function Dashboard() {
  const [tables, setTables] = useState<{ name: string; row_count: number }[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [charts, setCharts] = useState<ChartData[]>([])
  const [loading, setLoading] = useState(false)
  const [analysisName, setAnalysisName] = useState('')
  const [saving, setSaving] = useState(false)
  const [linkedFilter, setLinkedFilter] = useState<{ column: string; value: string } | null>(null)
  const [linkedEnabled, setLinkedEnabled] = useState(true)
  const chartRefs = useRef<any[]>([])
  const { t } = useI18n()
  const { lastSync, latestData, isSynced } = useDataTimestamps()

  useEffect(() => {
    api.get('/tables').then(res => {
      const tbls = res.data.tables.filter((t: any) => !t.name.startsWith('_') && t.row_count > 10)
      setTables(tbls)
      if (tbls.length > 0) {
        // 默认选中 eflow_tt，否则选第一个
        const ttTable = tbls.find((t: any) => t.name === 'eflow_tt')
        setSelectedTable(ttTable ? ttTable.name : tbls[0].name)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedTable) return
    generateAnalysis()
  }, [selectedTable])

  const generateAnalysis = async () => {
    setLoading(true)
    setLinkedFilter(null)
    try {
      const res = await api.post('/analysis', {
        name: `${t('dashboard.analysisPrefix')}${selectedTable}`,
        table_name: selectedTable,
      })
      setCharts(res.data.chart_config?.charts || [])
      setAnalysisName(res.data.name)
    } catch (err: any) {
      message.error(t('dashboard.generateFailed') + (err.response?.data?.detail || err.message))
    } finally {
      setLoading(false)
    }
  }

  const saveArchive = async () => {
    setSaving(true)
    try {
      await api.post('/analysis', {
        name: analysisName || `${t('dashboard.analysisPrefix')}${selectedTable}`,
        table_name: selectedTable,
      })
      message.success(t('dashboard.archived'))
    } catch {
      message.error(t('dashboard.archiveFailed'))
    } finally {
      setSaving(false)
    }
  }

  const handleChartClick = useCallback((chart: ChartData, params: any) => {
    if (!linkedEnabled) return
    if (chart.type === 'pie' || chart.type === 'bar') {
      const val = params.name || params.data?.name
      if (val) {
        setLinkedFilter(prev =>
          prev?.value === val ? null : { column: chart.column || chart.x_column || '', value: val }
        )
      }
    }
  }, [linkedEnabled])

  const isChartHighlighted = (chart: ChartData) => {
    if (!linkedFilter) return false
    return (chart.column === linkedFilter.column || chart.x_column === linkedFilter.column)
  }

  // 根据chart_key翻译图表标题
  const translateChartTitle = (chart: ChartData): string => {
    const key = (chart as any).chart_key
    if (!key) return chart.title
    const col = chart.column || chart.x_column || chart.y_column || ''
    const col2 = chart.y_column || chart.x_column || ''
    const map: Record<string, string> = {
      distribution: t('dashboard.chart.distribution'),
      mean_comparison: t('dashboard.chart.meanComparison'),
      trend: t('dashboard.chart.trend'),
      quality_radar: t('dashboard.chart.qualityRadar'),
      sla_heatmap: t('dashboard.chart.slaHeatmap'),
      status_heatmap: t('dashboard.chart.statusHeatmap'),
    }
    const tmpl = map[key]
    if (!tmpl) return chart.title
    return tmpl.replace('{col}', col).replace('{col2}', col2)
  }

  const renderChart = (chart: ChartData, idx: number) => {
    let option: any = {}
    const highlighted = isChartHighlighted(chart)
    const displayTitle = translateChartTitle(chart)

    const onEvents: Record<string, Function> = {}
    if (chart.type === 'pie' || chart.type === 'bar') {
      onEvents['click'] = (params: any) => handleChartClick(chart, params)
    }

    switch (chart.type) {
      case 'pie':
        option = {
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
          legend: { bottom: 0, type: 'scroll' },
          series: [{
            type: 'pie',
            radius: ['30%', '60%'],
            center: ['50%', '45%'],
            data: chart.data,
            emphasis: { itemStyle: { shadowBlur: 10 } },
            label: { formatter: '{b}\n{d}%' },
          }],
        }
        break

      case 'bar':
        option = {
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'axis' },
          xAxis: {
            type: 'category',
            data: chart.data.map((d: any) => d.name),
            axisLabel: { rotate: 30, fontSize: 10 },
          },
          yAxis: { type: 'value' },
          series: [{
            type: 'bar',
            data: chart.data.map((d: any) => d.value),
            itemStyle: { color: '#1677ff', borderRadius: [4, 4, 0, 0] },
          }],
          grid: { left: 60, right: 20, bottom: 80, top: 50 },
        }
        break

      case 'line':
        option = {
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'axis' },
          xAxis: {
            type: 'category',
            data: chart.data.map((d: any) => d.date),
            axisLabel: { rotate: 30, fontSize: 10 },
          },
          yAxis: { type: 'value' },
          series: [{
            type: 'line',
            data: chart.data.map((d: any) => d.count),
            smooth: true,
            areaStyle: { opacity: 0.3 },
            lineStyle: { width: 2 },
          }],
          grid: { left: 60, right: 20, bottom: 80, top: 50 },
          dataZoom: [{ type: 'slider' }],
        }
        break

      case 'radar':
        option = {
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14 } },
          tooltip: {},
          radar: {
            indicator: chart.data.map((d: any) => ({ name: d.name, max: 100 })),
            radius: '60%',
          },
          series: [{
            type: 'radar',
            data: [{ value: chart.data.map((d: any) => d.score), name: t('dashboard.qualityScore') }],
            areaStyle: { opacity: 0.3 },
          }],
        }
        break

      case 'heatmap':
        const xLabels = chart.x_labels || []
        const yLabels = chart.y_labels || []
        const maxVal = Math.max(...chart.data.map((d: any) => d[2]), 1)
        option = {
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14 } },
          tooltip: {
            position: 'top',
            formatter: (p: any) => `${yLabels[p.data[1]]} × ${xLabels[p.data[0]]}: ${p.data[2]}`,
          },
          xAxis: {
            type: 'category',
            data: xLabels,
            splitArea: { show: true },
            axisLabel: { rotate: 30, fontSize: 10 },
          },
          yAxis: {
            type: 'category',
            data: yLabels,
            splitArea: { show: true },
            axisLabel: { fontSize: 10 },
          },
          visualMap: {
            min: 0,
            max: maxVal,
            calculable: true,
            orient: 'horizontal',
            left: 'center',
            bottom: 0,
            inRange: { color: ['#e0f3f8', '#045a8d'] },
          },
          series: [{
            type: 'heatmap',
            data: chart.data,
            label: { show: true, fontSize: 10 },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
          }],
          grid: { left: 80, right: 20, bottom: 60, top: 50 },
        }
        break

      default:
        return null
    }

    return (
      <Col span={12} key={idx}>
        <Card
          size="small"
          style={{ ...chartCardStyle, borderColor: highlighted ? '#1677ff' : '#f0f0f0' }}
          title={
            highlighted && linkedFilter
              ? <span style={{ color: '#1677ff', fontSize: 14, fontWeight: 600 }}>{displayTitle} <Tag color="blue">{t('dashboard.filter')}: {linkedFilter.value}</Tag></span>
              : <span style={{ fontSize: 14, fontWeight: 600, color: '#374151' }}>{displayTitle}</span>
          }
        >
          <ReactECharts
            ref={(e: any) => { chartRefs.current[idx] = e }}
            option={option}
            style={{ height: 300 }}
            onEvents={onEvents}
          />
        </Card>
      </Col>
    )
  }

  return (
    <div>
      <Card style={controlBarStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <Space size="middle" wrap>
            <span style={{ fontWeight: 500, color: '#374151' }}>{t('dashboard.selectTable')}</span>
            <Select
              value={selectedTable}
              onChange={setSelectedTable}
              style={{ width: 300 }}
              showSearch
              options={tables.map(tbl => ({ value: tbl.name, label: `${tbl.name} (${tbl.row_count.toLocaleString()} ${t('common.rows')})` }))}
            />
            <Input
              value={analysisName}
              onChange={e => setAnalysisName(e.target.value)}
              placeholder={t('dashboard.analysisName')}
              style={{ width: 200 }}
            />
          </Space>
          <Space size="middle" wrap>
            <Button type="primary" onClick={generateAnalysis} loading={loading}>
              {t('dashboard.generate')}
            </Button>
            <Button onClick={saveArchive} loading={saving} icon={<span>📁</span>}>
              {t('dashboard.archive')}
            </Button>
            <Button
              type={linkedEnabled ? 'primary' : 'default'}
              icon={linkedEnabled ? <FilterFilled /> : <FilterOutlined />}
              onClick={() => { setLinkedEnabled(!linkedEnabled); if (linkedEnabled) setLinkedFilter(null) }}
            >
              {t('dashboard.linkedFilter')} {linkedEnabled ? 'ON' : 'OFF'}
            </Button>
            {linkedFilter && (
              <Tag closable onClose={() => setLinkedFilter(null)} color="blue">
                {t('dashboard.currentFilter')}: {linkedFilter.column} = {linkedFilter.value}
              </Tag>
            )}
            <Tooltip title={t('datasource.lastSync')}>
              <Tag color={isSynced ? 'green' : 'red'} style={{ borderRadius: 12, padding: '2px 12px' }}>
                {isSynced ? t('datasource.synced') : t('datasource.notSynced')}
                {isSynced && lastSync && `: ${lastSync}`}
              </Tag>
            </Tooltip>
            <Tooltip title={t('datasource.latestData')}>
              <Tag color="geekblue" style={{ borderRadius: 12, padding: '2px 12px' }}>{t('datasource.latestData')}: {latestData}</Tag>
            </Tooltip>
          </Space>
        </div>
      </Card>

      {loading ? (
        <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
      ) : charts.length > 0 ? (
        <Row gutter={[16, 16]}>
          {charts.map((chart, idx) => renderChart(chart, idx))}
        </Row>
      ) : (
        <Card style={chartCardStyle}>
          <div style={{ textAlign: 'center', padding: 50, color: '#999' }}>
            {t('dashboard.emptyPrompt')}
          </div>
        </Card>
      )}
    </div>
  )
}
