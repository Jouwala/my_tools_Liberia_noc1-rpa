import { useEffect, useState } from 'react'
import { Card, Table, Select, Input, Tag, Spin, Tabs, Row, Col, Statistic, Progress, Descriptions, Badge, Button, Dropdown, message, Modal, Checkbox, Divider } from 'antd'
import { DownloadOutlined, SettingOutlined, SearchOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { useI18n, numLocale } from '../i18n'

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

interface ViewTemplate {
  table_name: string
  name: string
  columns: string[]
  created_at: string
  updated_at: string
}

export default function TableBrowser() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [tableData, setTableData] = useState<any[]>([])
  const [tableColumns, setTableColumns] = useState<any[]>([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [profileData, setProfileData] = useState<ProfileResult | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [visibleCols, setVisibleCols] = useState<string[] | null>(null)
  const [colModalOpen, setColModalOpen] = useState(false)
  const [draftCols, setDraftCols] = useState<string[]>([])
  const [templates, setTemplates] = useState<ViewTemplate[]>([])
  const [tplName, setTplName] = useState('')
  const [colFilter, setColFilter] = useState('')
  const { t, locale } = useI18n()

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
    setVisibleCols(null)
    setTplName('')
    loadTableData(1)
    loadTemplates()
  }, [selectedTable])

  // 载入当前表已保存的列模板
  const loadTemplates = () => {
    api.get('/tables/view-templates', { params: { table_name: selectedTable } })
      .then(res => setTemplates(res.data.templates || []))
      .catch(() => setTemplates([]))
  }

  const loadTableData = (page: number) => {
    setLoading(true)
    const params: any = { page, page_size: 20 }
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

  // 导出整表（服务端生成 xlsx/csv，大表不压前端内存；携带当前搜索条件与自定义显示列）
  const exportTable = (format: 'xlsx' | 'csv') => {
    if (!selectedTable) return
    const params = new URLSearchParams({ format })
    if (searchText) params.set('search', searchText)
    if (visibleCols && visibleCols.length) params.set('columns', visibleCols.join(','))
    message.info(t('table.exportStart'))
    window.open(`/api/tables/${encodeURIComponent(selectedTable)}/export?${params.toString()}`, '_blank')
  }

  // ---- 自定义列 / 模板 ----
  const openColModal = () => {
    setDraftCols(visibleCols ?? [...tableColumns])
    setColFilter('')
    setColModalOpen(true)
  }

  const applyCols = () => {
    setVisibleCols(draftCols.length >= tableColumns.length ? null : [...draftCols])
    setColModalOpen(false)
  }

  const resetCols = () => {
    setVisibleCols(null)
    setDraftCols([...tableColumns])
    setColModalOpen(false)
  }

  const applyTemplate = (tp: ViewTemplate) => {
    // 过滤掉表结构变更后已不存在的列
    setDraftCols(tp.columns.filter(c => tableColumns.includes(c)))
  }

  const saveTemplate = () => {
    const name = tplName.trim()
    if (!name) { message.warning(t('table.tplNameRequired')); return }
    if (!draftCols.length) { message.warning(t('table.noColSelected')); return }
    api.post('/tables/view-templates', {
      table_name: selectedTable, name, columns: draftCols,
    })
      .then(() => {
        message.success(t('table.templateSaved'))
        setTplName('')
        loadTemplates()
      })
      .catch(() => message.error(t('table.templateSaveFailed')))
  }

  const deleteTemplate = (name: string) => {
    api.delete('/tables/view-templates', { params: { table_name: selectedTable, name } })
      .then(() => {
        message.success(t('table.templateDeleted'))
        loadTemplates()
      })
  }

  // 列名模糊过滤（不区分大小写、子串匹配）；仅过滤显示，勾选状态不受影响
  const filterKw = colFilter.trim().toLowerCase()
  const filteredCols = filterKw
    ? tableColumns.filter((c: string) => c.toLowerCase().includes(filterKw))
    : tableColumns

  const tableInfo = tables.find(t => t.name === selectedTable)

  // 自定义显示列：按所选顺序过滤（null 表示全部列）
  const shownCols = visibleCols
    ? visibleCols.filter(c => tableColumns.includes(c))
    : tableColumns

  const dataColumns = shownCols.map((col: string) => ({
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
              <Tag color="blue">{tableInfo.row_count.toLocaleString(numLocale(locale))} {t('common.rows')}</Tag>
              <Tag color="green">{tableInfo.col_count} {t('common.cols')}</Tag>
            </Col>
          )}
          <Col>
            <Dropdown
              menu={{
                items: [
                  { key: 'xlsx', label: 'Excel (.xlsx)' },
                  { key: 'csv', label: 'CSV (.csv)' },
                ],
                onClick: ({ key }) => exportTable(key as 'xlsx' | 'csv'),
              }}
            >
              <Button icon={<DownloadOutlined />} disabled={!selectedTable}>
                {t('table.export')}
              </Button>
            </Dropdown>
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} disabled={!selectedTable} onClick={openColModal}>
              {t('table.customizeCols')}
            </Button>
          </Col>
          {visibleCols && (
            <Col>
              <Tag color="orange">{t('table.visibleColsTag', { n: shownCols.length, m: tableColumns.length })}</Tag>
            </Col>
          )}
        </Row>
      </Card>

      <Modal
        title={t('table.colModalTitle')}
        open={colModalOpen}
        onCancel={() => setColModalOpen(false)}
        width={640}
        footer={[
          <Button key="reset" onClick={resetCols}>{t('table.resetCols')}</Button>,
          <Button key="cancel" onClick={() => setColModalOpen(false)}>{t('table.cancel')}</Button>,
          <Button key="ok" type="primary" onClick={applyCols}>{t('table.apply')}</Button>,
        ]}
      >
        <div style={{ marginBottom: 8 }}>
          <Button size="small" onClick={() => setDraftCols([...tableColumns])}>{t('table.selectAll')}</Button>
          <Button size="small" style={{ marginLeft: 8 }} onClick={() => setDraftCols([])}>{t('table.clearAll')}</Button>
          <span style={{ marginLeft: 12, color: '#888' }}>{draftCols.length} / {tableColumns.length}</span>
        </div>
        <Input
          prefix={<SearchOutlined style={{ color: '#bbb' }} />}
          value={colFilter}
          onChange={e => setColFilter(e.target.value)}
          placeholder={t('table.filterColsPh')}
          allowClear
          style={{ marginBottom: 8 }}
        />
        <div style={{ maxHeight: 280, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
          {filteredCols.length === 0 ? (
            <div style={{ color: '#999', textAlign: 'center', padding: 12 }}>{t('table.noMatchCols')}</div>
          ) : (
            <Checkbox.Group value={draftCols} onChange={v => setDraftCols(v as string[])} style={{ width: '100%' }}>
              <Row>
                {filteredCols.map((c: string) => (
                  <Col span={8} key={c} style={{ marginBottom: 4 }}>
                    <Checkbox value={c}>{c}</Checkbox>
                  </Col>
                ))}
              </Row>
            </Checkbox.Group>
          )}
        </div>
        <Divider style={{ margin: '12px 0' }}>{t('table.templates')}</Divider>
        {templates.length === 0 ? (
          <div style={{ color: '#999', marginBottom: 8 }}>{t('table.noTemplates')}</div>
        ) : (
          <div style={{ maxHeight: 140, overflow: 'auto', marginBottom: 8 }}>
            {templates.map(tp => (
              <div key={tp.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ flex: 1 }}>{tp.name} <span style={{ color: '#999' }}>({tp.columns.length} {t('common.cols')})</span></span>
                <Button size="small" onClick={() => applyTemplate(tp)}>{t('table.loadTemplate')}</Button>
                <Button size="small" danger onClick={() => deleteTemplate(tp.name)}>{t('common.delete')}</Button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            value={tplName}
            onChange={e => setTplName(e.target.value)}
            placeholder={t('table.templateNamePh')}
            onPressEnter={saveTemplate}
            maxLength={50}
          />
          <Button type="primary" onClick={saveTemplate}>{t('table.saveTemplate')}</Button>
        </div>
      </Modal>

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
