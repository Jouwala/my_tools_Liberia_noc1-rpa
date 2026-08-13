import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Row, Col, Select, Spin, Button, Input, message, Tag, Space, Tooltip } from 'antd'
import { FilterOutlined, FilterFilled } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n, numLocale } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import { useDataTimestamps } from '../useDataTimestamps'
import { WH, WH_COLORS, LIGHT_COLORS, useTheme, darkTooltip, axisLabel, axisLine, splitLine, cardStyle, controlCardStyle, pageWrap } from '../theme'

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
  const { t, locale } = useI18n()
  const { lastSync, latestData, isSynced } = useDataTimestamps()
  const { isDark } = useTheme()

  useEffect(() => {
    api.get('/tables').then(res => {
      const tbls = res.data.tables.filter((t: any) => !t.name.startsWith('_') && t.row_count > 10)
      setTables(tbls)
      if (tbls.length > 0) {
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

    // 主题感知的图表色板（canvas 无法解析 CSS 变量）
    const cText = isDark ? '#e6f4ff' : '#16233b'
    const cTextMuted = isDark ? '#94a3b8' : '#3f5468'
    const cTeal = isDark ? '#64ffda' : '#0d9488'
    const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
    const cGrid = isDark ? 'rgba(100,255,218,0.15)' : 'rgba(13,148,136,0.25)'
    const cGridSoft = isDark ? 'rgba(100,255,218,0.1)' : 'rgba(13,148,136,0.18)'
    const cSplit = isDark ? ['rgba(100,255,218,0.03)', 'rgba(100,255,218,0.06)'] : ['rgba(13,148,136,0.04)', 'rgba(13,148,136,0.08)']

    const onEvents: Record<string, Function> = {}
    if (chart.type === 'pie' || chart.type === 'bar') {
      onEvents['click'] = (params: any) => handleChartClick(chart, params)
    }

    switch (chart.type) {
      case 'pie':
        option = {
          backgroundColor: 'transparent',
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14, color: cText } },
          tooltip: { ...darkTooltip(isDark), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
          legend: { bottom: 0, type: 'scroll', textStyle: { color: cTextMuted } },
          series: [{
            type: 'pie',
            radius: ['30%', '60%'],
            center: ['50%', '45%'],
            data: chart.data.map((d: any, i: number) => ({ ...d, itemStyle: { color: cPalette[i % cPalette.length] } })),
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.3)' } },
            label: { color: cText, formatter: '{b}\n{d}%' },
          }],
        }
        break

      case 'bar':
        option = {
          backgroundColor: 'transparent',
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14, color: cText } },
          tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
          xAxis: {
            type: 'category',
            data: chart.data.map((d: any) => d.name),
            axisLabel: { ...axisLabel(isDark), rotate: 30 },
            axisLine: axisLine(isDark),
          },
          yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
          series: [{
            type: 'bar',
            data: chart.data.map((d: any, i: number) => ({ value: d.value, itemStyle: { color: cPalette[i % cPalette.length], borderRadius: [4, 4, 0, 0] } })),
          }],
          grid: { left: 60, right: 20, bottom: 80, top: 50 },
        }
        break

      case 'line':
        option = {
          backgroundColor: 'transparent',
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14, color: cText } },
          tooltip: { ...darkTooltip(isDark), trigger: 'axis' },
          xAxis: {
            type: 'category',
            data: chart.data.map((d: any) => d.date),
            axisLabel: { ...axisLabel(isDark), rotate: 30 },
            axisLine: axisLine(isDark),
          },
          yAxis: { type: 'value', splitLine: splitLine(isDark), axisLabel: axisLabel(isDark) },
          series: [{
            type: 'line',
            data: chart.data.map((d: any) => d.count),
            smooth: true,
            areaStyle: { opacity: 0.3, color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.25)' }, { offset: 1, color: 'rgba(100,255,218,0.02)' }] } },
            lineStyle: { width: 2, color: cTeal },
            itemStyle: { color: cTeal },
          }],
          grid: { left: 60, right: 20, bottom: 80, top: 50 },
          dataZoom: [{ type: 'slider', textStyle: { color: cTextMuted } }],
        }
        break

      case 'radar':
        option = {
          backgroundColor: 'transparent',
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14, color: cText } },
          tooltip: { ...darkTooltip(isDark) },
          radar: {
            indicator: chart.data.map((d: any) => ({ name: d.name, max: 100 })),
            radius: '60%',
            axisName: { color: cTextMuted },
            splitArea: { areaStyle: { color: cSplit } },
            axisLine: { lineStyle: { color: cGrid } },
            splitLine: { lineStyle: { color: cGridSoft } },
          },
          series: [{
            type: 'radar',
            data: [{ value: chart.data.map((d: any) => d.score), name: t('dashboard.qualityScore'), areaStyle: { opacity: 0.3, color: cTeal }, lineStyle: { color: cTeal } }],
          }],
        }
        break

      case 'heatmap':
        const xLabels = chart.x_labels || []
        const yLabels = chart.y_labels || []
        const maxVal = Math.max(...chart.data.map((d: any) => d[2]), 1)
        option = {
          backgroundColor: 'transparent',
          title: { text: displayTitle, left: 'center', textStyle: { fontSize: 14, color: cText } },
          tooltip: {
            ...darkTooltip(isDark),
            position: 'top',
            formatter: (p: any) => `${yLabels[p.data[1]]} × ${xLabels[p.data[0]]}: ${p.data[2]}`,
          },
          xAxis: {
            type: 'category',
            data: xLabels,
            splitArea: { show: true, areaStyle: { color: cSplit } },
            axisLabel: { ...axisLabel(isDark), rotate: 30 },
            axisLine: axisLine(isDark),
          },
          yAxis: {
            type: 'category',
            data: yLabels,
            splitArea: { show: true, areaStyle: { color: cSplit } },
            axisLabel: { ...axisLabel(isDark), color: cText },
            axisLine: axisLine(isDark),
          },
          visualMap: {
            min: 0,
            max: maxVal,
            calculable: true,
            orient: 'horizontal',
            left: 'center',
            bottom: 0,
            textStyle: { color: cTextMuted },
            inRange: { color: isDark ? ['#0d2138', '#4fc3f7', '#64ffda'] : ['#dcebf5', '#0284c7', '#0d9488'] },
          },
          series: [{
            type: 'heatmap',
            data: chart.data,
            label: { show: true, fontSize: 10, color: cText },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.3)' } },
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
          style={{ ...cardStyle, borderColor: highlighted ? WH.teal : WH.cardBorder, boxShadow: highlighted ? `0 0 16px var(--wh-teal-27)` : cardStyle.boxShadow }}
          title={
            highlighted && linkedFilter
              ? <span style={{ color: WH.teal, fontSize: 14, fontWeight: 600 }}>{displayTitle} <Tag color="cyan">{t('dashboard.filter')}: {linkedFilter.value}</Tag></span>
              : <span style={{ fontSize: 14, fontWeight: 600, color: WH.text }}>{displayTitle}</span>
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
    <div style={pageWrap}>
      <Card style={controlCardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <Space size="middle" wrap>
            <span style={{ fontWeight: 500, color: WH.text }}>{t('dashboard.selectTable')}</span>
            <Select
              value={selectedTable}
              onChange={setSelectedTable}
              style={{ width: 300 }}
              showSearch
              options={tables.map(tbl => ({ value: tbl.name, label: `${tbl.name} (${tbl.row_count.toLocaleString(numLocale(locale))} ${t('common.rows')})` }))}
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
              <Tag closable onClose={() => setLinkedFilter(null)} color="cyan">
                {t('dashboard.currentFilter')}: {linkedFilter.column} = {linkedFilter.value}
              </Tag>
            )}
            <ExplainIcon text={t('dashboard.explain.note')} size={14} />
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
        <Card style={cardStyle}>
          <div style={{ textAlign: 'center', padding: 50, color: WH.textMuted }}>
            {t('dashboard.emptyPrompt')}
          </div>
        </Card>
      )}
    </div>
  )
}
