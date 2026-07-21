import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Spin, Tag } from 'antd'
import { DatabaseOutlined, TableOutlined, FieldNumberOutlined, CheckCircleOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n } from '../i18n'

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

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  if (!info) return <div>{t('overview.loadError')}</div>

  const topTables = info.tables
    .filter(t => !t.name.startsWith('_') && t.name !== 'analysis_archive' && t.name !== 'uploaded_files')
    .sort((a, b) => b.rows - a.rows)
    .slice(0, 10)

  const barOption = {
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: topTables.map(t => t.name),
      axisLabel: { rotate: 30, fontSize: 10 },
    },
    yAxis: { type: 'value' as const },
    series: [{
      type: 'bar',
      data: topTables.map(t => t.rows),
      itemStyle: { color: '#1677ff', borderRadius: [4, 4, 0, 0] },
    }],
    grid: { left: 60, right: 20, bottom: 80, top: 20 },
  }

  const pieOption = {
    tooltip: { trigger: 'item' as const },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: topTables.map(t => ({ name: t.name, value: t.rows })),
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
    }],
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('overview.totalTables')}
              value={info.total_tables}
              prefix={<TableOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('overview.totalRows')}
              value={info.total_rows}
              prefix={<FieldNumberOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('overview.coreTables')}
              value={info.tables.filter(t => !t.name.startsWith('_')).length}
              prefix={<DatabaseOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('overview.status')}
              value={t('overview.statusOk')}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={14}>
          <Card title={t('overview.rankTitle')}>
            <ReactECharts option={barOption} style={{ height: 350 }} />
          </Card>
        </Col>
        <Col span={10}>
          <Card title={t('overview.distTitle')}>
            <ReactECharts option={pieOption} style={{ height: 350 }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title={t('overview.allTables')}>
            <Table
              dataSource={info.tables.filter(t => !t.name.startsWith('_'))}
              columns={[
                { title: t('overview.tableName'), dataIndex: 'name', key: 'name', render: (v: string) => <Tag color="blue">{v}</Tag> },
                { title: t('overview.rowCount'), dataIndex: 'rows', key: 'rows', sorter: (a: any, b: any) => a.rows - b.rows },
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
