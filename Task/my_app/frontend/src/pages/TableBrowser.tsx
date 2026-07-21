import { useEffect, useState } from 'react'
import { Card, Table, Select, Input, Tag, Spin, Tabs, Row, Col, Statistic, Progress, Descriptions, Badge } from 'antd'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n } from '../i18n'

interface TableInfo {
  name: string
  row_count: number
  col_count: number
  columns: { name: string; type: string; notnull: number; pk: number }[]
}

interface ProfileColumn {
  name: string
  dtype: string
  type_category: string
  total: number
  non_null: number
  null_count: number
  null_rate: number
  unique_count: number
  unique_rate: number
  duplicate_rate: number
  issues: any[]
  issue_count: number
  stats: any
  top_values: { value: string; count: number; rate: number }[]
  outlier_count?: number
  outlier_rate?: number
  is_candidate_key?: boolean
}

interface ProfileResult {
  table_name: string
  profile: {
    total_rows: number
    total_cols: number
    columns: ProfileColumn[]
    quality_score: number
    issues_summary: any[]
  }
  conclusions: string[]
}

export default function TableBrowser() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [tableData, setTableData] = useState<any[]>([])
  const [tableColumns, setTableColumns] = useState<any[]>([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 50, total: 0 })
  const [loading, setLoading] = useState(false)
  const [profileData, setProfileData] = useState<ProfileResult | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const { t } = useI18n()

  useEffect(() => {
    api.get('/tables').then(res => {
      const tbls = res.data.tables.filter((t: TableInfo) => !t.name.startsWith('_'))
      setTables(tbls)
      if (tbls.length > 0) {
        setSelectedTable(tbls[0].name)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedTable) return
    loadTableData(1)
  }, [selectedTable])

  const loadTableData = (page: number) => {
    setLoading(true)
    const params: any = { page, page_size: 50 }
    if (searchText) params.search = searchText

    api.get(`/tables/${selectedTable}/data`, { params })
      .then(res => {
        setTableData(res.data.data.map((r: any, i: number) => ({ ...r, __row_index: `${page}-${i}` })))
        setTableColumns(res.data.columns)
        setPagination({
          current: res.data.page,
          pageSize: res.data.page_size,
          total: res.data.total,
        })
      })
      .finally(() => setLoading(false))
  }

  const loadProfile = () => {
    setProfileLoading(true)
    api.get(`/tables/${selectedTable}/profile`)
      .then(res => setProfileData(res.data))
      .finally(() => setProfileLoading(false))
  }

  const tableInfo = tables.find(t => t.name === selectedTable)

  const dataColumns = tableColumns.map((col: string) => ({
    title: col,
    dataIndex: col,
    key: col,
    width: 150,
    ellipsis: true,
    render: (v: any) => v === null || v === undefined ? <Tag>NULL</Tag> : String(v),
  }))

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Select
              value={selectedTable}
              onChange={setSelectedTable}
              style={{ width: 300 }}
              showSearch
              placeholder={t('table.selectTable')}
              options={tables.map(tbl => ({ value: tbl.name, label: `${tbl.name} (${tbl.row_count} ${t('common.rows')})` }))}
            />
          </Col>
          <Col>
            <Input.Search
              placeholder={t('table.searchPlaceholder')}
              onSearch={(v) => { setSearchText(v); loadTableData(1) }}
              style={{ width: 250 }}
              allowClear
            />
          </Col>
          {tableInfo && (
            <Col>
              <Tag color="blue">{tableInfo.row_count.toLocaleString()} {t('common.rows')}</Tag>
              <Tag color="green">{tableInfo.col_count} {t('common.cols')}</Tag>
            </Col>
          )}
        </Row>
      </Card>

      <Tabs
        items={[
          {
            key: 'data',
            label: t('table.browseTab'),
            children: (
              <Card>
                <Table
                  dataSource={tableData}
                  columns={dataColumns}
                  loading={loading}
                  scroll={{ x: 'max-content' }}
                  size="small"
                  rowKey={(record: any) => record.__row_index ?? JSON.stringify(record).slice(0, 50)}
                  pagination={{
                    ...pagination,
                    showSizeChanger: false,
                    showTotal: (total) => t('table.totalRecords', { n: total }),
                    onChange: (p) => loadTableData(p),
                  }}
                />
              </Card>
            ),
          },
          {
            key: 'profile',
            label: t('table.profileTab'),
            children: profileLoading ? (
              <Spin style={{ display: 'block', margin: '50px auto' }} />
            ) : profileData ? (
              <ProfilePanel profile={profileData} onLoad={loadProfile} />
            ) : (
              <Card>
                <div style={{ textAlign: 'center', padding: 50 }}>
                  <p>{t('table.profilePrompt')}</p>
                  <a onClick={loadProfile} style={{ fontSize: 16 }}>{t('table.startAnalysis')}</a>
                </div>
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}

function ProfilePanel({ profile, onLoad }: { profile: ProfileResult; onLoad: () => void }) {
  const { profile: p, conclusions } = profile
  const { t } = useI18n()

  const nullRateOption = {
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: p.columns.map((c: ProfileColumn) => c.name),
      axisLabel: { rotate: 60, fontSize: 9 },
    },
    yAxis: { type: 'value' as const, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: p.columns.map((c: ProfileColumn) => ({
        value: c.null_rate,
        itemStyle: { color: c.null_rate > 50 ? '#ff4d4f' : c.null_rate > 20 ? '#faad14' : '#52c41a' },
      })),
    }],
    grid: { left: 50, right: 20, bottom: 100, top: 20 },
    dataZoom: [{ type: 'slider' }],
  }

  const typeGroups: Record<string, number> = {}
  p.columns.forEach((c: ProfileColumn) => {
    typeGroups[c.type_category] = (typeGroups[c.type_category] || 0) + 1
  })
  const typePieOption = {
    tooltip: { trigger: 'item' as const },
    series: [{
      type: 'pie',
      radius: '65%',
      data: Object.entries(typeGroups).map(([name, value]) => ({ name, value })),
    }],
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card><Statistic title={t('table.qualityScore')} value={p.quality_score} suffix={t('table.scoreUnit')} valueStyle={{ color: p.quality_score >= 80 ? '#52c41a' : '#faad14' }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title={t('table.totalRowsLabel')} value={p.total_rows} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title={t('table.totalColsLabel')} value={p.total_cols} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title={t('table.qualityIssues')} value={p.issues_summary.length} valueStyle={{ color: p.issues_summary.length > 0 ? '#ff4d4f' : '#52c41a' }} /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={16}>
          <Card title={t('table.nullRateDist')}>
            <ReactECharts option={nullRateOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title={t('table.typeDist')}>
            <ReactECharts option={typePieOption} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title={t('table.conclusions')}>
            {conclusions.map((c, i) => (
              <div key={i} style={{ marginBottom: 8, padding: '8px 12px', background: '#f6f8fa', borderRadius: 4 }}>
                {c}
              </div>
            ))}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title={t('table.fieldDetails')}>
            <Table
              dataSource={p.columns}
              columns={[
                { title: t('table.fieldName'), dataIndex: 'name', key: 'name', width: 150 },
                { title: t('table.fieldType'), dataIndex: 'type_category', key: 'type_category', width: 120, render: (v: string) => <Tag>{v}</Tag> },
                { title: t('table.nullRate'), dataIndex: 'null_rate', key: 'null_rate', width: 100, render: (v: number) => <Progress percent={v} size="small" strokeColor={v > 50 ? '#ff4d4f' : v > 20 ? '#faad14' : '#52c41a'} /> },
                { title: t('table.uniqueCount'), dataIndex: 'unique_count', key: 'unique_count', width: 80 },
                { title: t('table.issueCount'), dataIndex: 'issue_count', key: 'issue_count', width: 80, render: (v: number) => v > 0 ? <Badge count={v} /> : '-' },
                { title: t('table.candidateKey'), key: 'pk', width: 80, render: (_: any, r: ProfileColumn) => r.is_candidate_key ? <Tag color="gold">{t('table.isKey')}</Tag> : '-' },
              ]}
              size="small"
              rowKey="name"
              pagination={{ pageSize: 20 }}
              scroll={{ y: 400 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
