import { useEffect, useState } from 'react'
import { Card, Row, Col, Table, Spin, Tag, Button, Space } from 'antd'
import { DatabaseOutlined, TableOutlined, FieldNumberOutlined, CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import StatCard from '../components/StatCard'
import { useTheme, WH, WH_COLORS, LIGHT_COLORS, cardStyle, pageWrap } from '../theme'
import { exportAoaReport } from '../utils/excelReport'

interface DbInfo {
  database: string
  total_tables: number
  total_rows: number
  tables: { name: string; rows: number }[]
}

export default function Overview() {
  const [info, setInfo] = useState<DbInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const { t } = useI18n()
  const { isDark } = useTheme()

  useEffect(() => {
    api.get('/db/info')
      .then(res => setInfo(res.data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: '6.25rem' }}>
      <Spin size="large" />
    </div>
  )

  if (!info) return <div style={{ ...pageWrap, color: WH.textMuted }}>{t('overview.loadError')}</div>

  const topTables = info.tables
    .filter(t => !t.name.startsWith('_') && t.name !== 'analysis_archive' && t.name !== 'uploaded_files')
    .sort((a, b) => b.rows - a.rows)
    .slice(0, 10)

  // 主题感知的图表色板（canvas 无法解析 CSS 变量，取具体色值）
  const cText = isDark ? '#f5f7ff' : '#16233b'
  const cTextMuted = isDark ? '#aebbd4' : '#3f5468'
  const cPalette = isDark ? WH_COLORS : LIGHT_COLORS
  const cAxisLine = isDark ? '#173158' : '#c8d8e8'
  const cSplit = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(13,148,136,0.12)'
  const cTooltip = {
    backgroundColor: isDark ? 'rgba(8, 18, 44,0.95)' : 'rgba(255,255,255,0.97)',
    borderColor: isDark ? '#00d9ff' : '#0d9488',
    textStyle: { color: isDark ? '#f5f7ff' : '#16233b' },
  }

  // ========== 导出 ==========
  /* 表格 dataSource 已过滤掉 `_` 前缀的内部表，导出与之保持一致；
     与页面表格不同，这里导出**全部**表（不是 Top 10），口径见下方副标题。 */
  const coreTables = info.tables
    .filter(t => !t.name.startsWith('_'))
    .slice()
    .sort((a, b) => b.rows - a.rows)

  const exportTables = () => {
    if (!coreTables.length) return
    void exportAoaReport({
      filename: `db_overview_${new Date().toISOString().slice(0, 10)}.xlsx`,
      sheetName: 'DB Overview',
      title: t('overview.allTables'),
      subtitle: `${t('overview.totalTables')}: ${info.total_tables}`
        + `    |    ${t('overview.totalRows')}: ${info.total_rows}`
        + `    |    DB: ${info.database}`,
      header: [t('overview.tableName'), t('overview.rowCount')],
      rows: coreTables.map(tb => [tb.name, tb.rows]),
      numericCols: [1],
      columnWidths: [42, 16],
      tabColor: '#2F5496',
    })
  }

  const barOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', ...cTooltip },
    xAxis: {
      type: 'category',
      data: topTables.map(t => t.name),
      axisLabel: { rotate: 30, fontSize: 11, color: cTextMuted },
      axisLine: { lineStyle: { color: cAxisLine } },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: cSplit } }, axisLabel: { color: cTextMuted } },
    series: [{
      type: 'bar',
      data: topTables.map((t, i) => ({ value: t.rows, itemStyle: { color: cPalette[i % cPalette.length], borderRadius: [4, 4, 0, 0] } })),
    }],
    grid: { left: 60, right: 20, bottom: 80, top: 20 },
  }

  const pieOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', ...cTooltip, formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: cTextMuted } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: topTables.map((t, i) => ({ name: t.name, value: t.rows, itemStyle: { color: cPalette[i % cPalette.length] } })),
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: isDark ? 'rgba(0, 217, 255,0.35)' : 'rgba(13,148,136,0.3)' } },
      label: { color: cText, formatter: '{b}\n{d}%' },
    }],
  }

  return (
    <div style={pageWrap}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<>{t('overview.totalTables')} <ExplainIcon text={t('overview.explain.totalTables')} /></>}
            value={info.total_tables}
            prefix={<TableOutlined />}
            accentColor={isDark ? '#00d9ff' : '#0d9488'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<>{t('overview.totalRows')} <ExplainIcon text={t('overview.explain.totalRows')} /></>}
            value={info.total_rows}
            prefix={<FieldNumberOutlined />}
            accentColor={isDark ? '#258cff' : '#0e7490'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<>{t('overview.coreTables')} <ExplainIcon text={t('overview.explain.coreTables')} /></>}
            value={info.tables.filter(t => !t.name.startsWith('_')).length}
            prefix={<DatabaseOutlined />}
            accentColor={isDark ? '#7c8ff0' : '#6366f1'}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title={<>{t('overview.status')}</>}
            value={t('overview.statusOk')}
            prefix={<CheckCircleOutlined />}
            accentColor={isDark ? '#0bc78c' : '#15803d'}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 'var(--wh-space-md)' }}>
        <Col xs={24} lg={14}>
          <Card title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.rankTitle')}</span>} style={cardStyle}>
            <ReactECharts option={barOption} style={{ height: 'clamp(16rem, 30vw, 22rem)' }} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.distTitle')}</span>} style={cardStyle}>
            <ReactECharts option={pieOption} style={{ height: 'clamp(16rem, 30vw, 22rem)' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 'var(--wh-space-md)' }}>
        <Col span={24}>
          <Card
            title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.allTables')}</span>}
            style={cardStyle}
            extra={
              <Space>
                <Button size="small" icon={<DownloadOutlined />} onClick={exportTables} disabled={!coreTables.length}>
                  {t('common.exportExcel')}
                </Button>
              </Space>
            }
          >
            <div className="wh-table-responsive">
              <Table
                dataSource={info.tables.filter(t => !t.name.startsWith('_'))}
                columns={[
                  { title: <span style={{ color: WH.textMuted }}>{t('overview.tableName')}</span>, dataIndex: 'name', key: 'name', render: (v: string) => <Tag color="cyan">{v}</Tag> },
                  { title: <span style={{ color: WH.textMuted }}>{t('overview.rowCount')}</span>, dataIndex: 'rows', key: 'rows', sorter: (a: any, b: any) => a.rows - b.rows },
                ]}
                pagination={false}
                size="small"
                rowKey="name"
                scroll={{ x: 'max-content' }}
              />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
