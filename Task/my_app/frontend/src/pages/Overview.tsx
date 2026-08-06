import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Spin, Tag } from 'antd'
import { DatabaseOutlined, TableOutlined, FieldNumberOutlined, CheckCircleOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n } from '../i18n'
import { ExplainIcon } from '../components/MetricExplain'
import { WH, WH_COLORS, cardStyle, pageWrap } from '../theme'

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

  useEffect(() => {
    api.get('/db/info')
      .then(res => setInfo(res.data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div style={{ ...pageWrap, textAlign: 'center', padding: 100 }}>
      <Spin size="large" />
    </div>
  )

  if (!info) return <div style={{ ...pageWrap, color: WH.textMuted }}>{t('overview.loadError')}</div>

  const topTables = info.tables
    .filter(t => !t.name.startsWith('_') && t.name !== 'analysis_archive' && t.name !== 'uploaded_files')
    .sort((a, b) => b.rows - a.rows)
    .slice(0, 10)

  const barOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(10,25,41,0.95)', borderColor: '#64ffda', textStyle: { color: '#e6f4ff' } },
    xAxis: {
      type: 'category',
      data: topTables.map(t => t.name),
      axisLabel: { rotate: 30, fontSize: 11, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#22324d' } },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: 'rgba(255,255,255,0.06)' } }, axisLabel: { color: '#94a3b8' } },
    series: [{
      type: 'bar',
      data: topTables.map((t, i) => ({ value: t.rows, itemStyle: { color: WH_COLORS[i % WH_COLORS.length], borderRadius: [4, 4, 0, 0] } })),
    }],
    grid: { left: 60, right: 20, bottom: 80, top: 20 },
  }

  const pieOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', backgroundColor: 'rgba(10,25,41,0.95)', borderColor: '#64ffda', textStyle: { color: '#e6f4ff' }, formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: '#94a3b8' } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: topTables.map((t, i) => ({ name: t.name, value: t.rows, itemStyle: { color: WH_COLORS[i % WH_COLORS.length] } })),
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(100,255,218,0.35)' } },
      label: { color: '#e6f4ff', formatter: '{b}\n{d}%' },
    }],
  }

  return (
    <div style={pageWrap}>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card style={cardStyle}>
            <Statistic
              title={<span style={{ color: WH.textMuted }}>{t('overview.totalTables')} <ExplainIcon text={t('overview.explain.totalTables')} /></span>}
              value={info.total_tables}
              prefix={<TableOutlined style={{ color: WH.teal }} />}
              valueStyle={{ color: WH.teal, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle}>
            <Statistic
              title={<span style={{ color: WH.textMuted }}>{t('overview.totalRows')} <ExplainIcon text={t('overview.explain.totalRows')} /></span>}
              value={info.total_rows}
              prefix={<FieldNumberOutlined style={{ color: WH.blue }} />}
              valueStyle={{ color: WH.blue, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle}>
            <Statistic
              title={<span style={{ color: WH.textMuted }}>{t('overview.coreTables')} <ExplainIcon text={t('overview.explain.coreTables')} /></span>}
              value={info.tables.filter(t => !t.name.startsWith('_')).length}
              prefix={<DatabaseOutlined style={{ color: WH.indigo }} />}
              valueStyle={{ color: WH.indigo, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle}>
            <Statistic
              title={<span style={{ color: WH.textMuted }}>{t('overview.status')}</span>}
              value={t('overview.statusOk')}
              prefix={<CheckCircleOutlined style={{ color: '#51cf66' }} />}
              valueStyle={{ color: '#51cf66', fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={14}>
          <Card title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.rankTitle')}</span>} style={cardStyle}>
            <ReactECharts option={barOption} style={{ height: 350 }} />
          </Card>
        </Col>
        <Col span={10}>
          <Card title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.distTitle')}</span>} style={cardStyle}>
            <ReactECharts option={pieOption} style={{ height: 350 }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title={<span style={{ color: WH.text, fontWeight: 600 }}>{t('overview.allTables')}</span>} style={cardStyle}>
            <Table
              dataSource={info.tables.filter(t => !t.name.startsWith('_'))}
              columns={[
                { title: <span style={{ color: WH.textMuted }}>{t('overview.tableName')}</span>, dataIndex: 'name', key: 'name', render: (v: string) => <Tag color="cyan">{v}</Tag> },
                { title: <span style={{ color: WH.textMuted }}>{t('overview.rowCount')}</span>, dataIndex: 'rows', key: 'rows', sorter: (a: any, b: any) => a.rows - b.rows },
              ]}
              pagination={false}
              size="small"
              rowKey="name"
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
