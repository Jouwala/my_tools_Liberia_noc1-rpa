import { useEffect, useState } from 'react'
import { Card, Table, Input, Button, Tag, Modal, Descriptions, Space, Popconfirm, message, List, Collapse } from 'antd'
import { SearchOutlined, EyeOutlined, DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import api from '../api'
import { formatDateTime } from '../datetime'
import { useI18n } from '../i18n'
import { exportAoaReport } from '../utils/excelReport'

interface Analysis {
  id: number
  name: string
  description: string | null
  table_name: string
  chart_config: any
  conclusions: string[]
  snapshot_data: any
  created_at: string
  updated_at: string
}

export default function ArchiveList() {
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [detailVisible, setDetailVisible] = useState(false)
  const [detail, setDetail] = useState<Analysis | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const { t } = useI18n()

  const translateChartTitle = (chart: any): string => {
    const key = chart.chart_key
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

  useEffect(() => {
    loadList()
  }, [page, search])

  const loadList = () => {
    setLoading(true)
    api.get('/analysis', { params: { search: search || undefined, page, page_size: 20 } })
      .then(res => {
        setAnalyses(res.data.analyses || [])
        setTotal(res.data.total || 0)
      })
      .finally(() => setLoading(false))
  }

  const viewDetail = (id: number) => {
    setDetailLoading(true)
    setDetailVisible(true)
    api.get(`/analysis/${id}`)
      .then(res => setDetail(res.data))
      .finally(() => setDetailLoading(false))
  }

  const deleteAnalysis = (id: number) => {
    api.delete(`/analysis/${id}`)
      .then(() => {
        message.success(t('archive.deleted'))
        loadList()
      })
      .catch(() => message.error(t('archive.deleteFailed')))
  }

  const columns = [
    {
      title: t('archive.colId'),
      dataIndex: 'id',
      key: 'id',
      minWidth: 60,
    },
    {
      title: t('archive.colName'),
      dataIndex: 'name',
      key: 'name',
      render: (v: string) => <strong>{v}</strong>,
    },
    {
      title: t('archive.colTable'),
      dataIndex: 'table_name',
      key: 'table_name',
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: t('archive.colDesc'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: t('archive.colCreated'),
      dataIndex: 'created_at',
      key: 'created_at',
      minWidth: 180,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: t('archive.colAction'),
      key: 'action',
      minWidth: 150,
      render: (_: any, record: Analysis) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(record.id)}>
            {t('common.view')}
          </Button>
          <Popconfirm title={t('common.confirm')} onConfirm={() => deleteAnalysis(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const renderCharts = (chartConfig: any) => {
    if (!chartConfig?.charts) return null

    return chartConfig.charts.map((chart: any, idx: number) => {
      let option: any = {}

      switch (chart.type) {
        case 'pie':
          option = {
            title: { text: translateChartTitle(chart), left: 'center', textStyle: { fontSize: 13 } },
            tooltip: { trigger: 'item' },
            series: [{ type: 'pie', radius: '60%', data: chart.data }],
          }
          break
        case 'bar':
          option = {
            title: { text: translateChartTitle(chart), left: 'center', textStyle: { fontSize: 13 } },
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'category', data: chart.data.map((d: any) => d.name), axisLabel: { rotate: 30 } },
            yAxis: { type: 'value' },
            series: [{ type: 'bar', data: chart.data.map((d: any) => d.value) }],
            grid: { left: 50, right: 10, bottom: 60, top: 40 },
          }
          break
        case 'line':
          option = {
            title: { text: translateChartTitle(chart), left: 'center', textStyle: { fontSize: 13 } },
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'category', data: chart.data.map((d: any) => d.date), axisLabel: { rotate: 30 } },
            yAxis: { type: 'value' },
            series: [{ type: 'line', data: chart.data.map((d: any) => d.count), smooth: true }],
            grid: { left: 50, right: 10, bottom: 60, top: 40 },
          }
          break
        case 'radar':
          option = {
            title: { text: translateChartTitle(chart), left: 'center', textStyle: { fontSize: 13 } },
            radar: { indicator: chart.data.map((d: any) => ({ name: d.name, max: 100 })) },
            series: [{ type: 'radar', data: [{ value: chart.data.map((d: any) => d.score) }] }],
          }
          break
      }

      return (
        <div key={idx} style={{ flex: '1 1 calc(50% - var(--wh-space-sm))', minWidth: '16rem' }}>
          <ReactECharts option={option} style={{ height: '17.5rem' }} />
        </div>
      )
    })
  }

  // ========== 导出 ==========
  /* 列表是服务端分页（每页 20 条），所以导出的是**当前页**这 20 条，
     并把「当前页 / 总数」写进副标题，避免用户误以为拿到的是全部归档。
     想导全部请先缩小搜索范围或用分页逐页导出。 */
  const exportList = () => {
    if (!analyses.length) return
    const header = [
      t('archive.colId'), t('archive.colName'), t('archive.colTable'),
      t('archive.colDesc'), t('archive.colCreated'),
    ]
    const body = analyses.map(a => [
      a.id, a.name, a.table_name, a.description || '', formatDateTime(a.created_at),
    ])
    const pageFrom = (page - 1) * 20 + 1
    void exportAoaReport({
      filename: `analysis_archive_${new Date().toISOString().slice(0, 10)}.xlsx`,
      sheetName: 'Analysis Archive',
      title: t('archive.title'),
      subtitle: `${t('archive.exportRange', { from: pageFrom, to: pageFrom + analyses.length - 1, total })}`
        + `    |    ${t('archive.searchPlaceholder')}: ${search || '-'}`,
      header,
      rows: body,
      numericCols: [0],
      columnWidths: [8, 30, 24, 46, 20],
    })
  }

  return (
    <div>
      <Card style={{ marginBottom: 'var(--wh-space-md)' }}>
        <Space>
          <Input.Search
            placeholder={t('archive.searchPlaceholder')}
            onSearch={(v) => { setSearch(v); setPage(1) }}
            style={{ width: 'min(100%, 21.875rem)' }}
            allowClear
          />
          <Button onClick={loadList}>{t('common.refresh')}</Button>
          <Button icon={<DownloadOutlined />} onClick={exportList} disabled={!analyses.length}>
            {t('common.exportExcel')}
          </Button>
          <Tag>{t('archive.totalRecords', { n: total })}</Tag>
        </Space>
      </Card>

      <Card>
        <div className="wh-table-responsive">
          <Table
            dataSource={analyses}
            columns={columns}
            loading={loading}
            rowKey="id"
            scroll={{ x: 'max-content' }}
            pagination={{
              current: page,
              total,
              pageSize: 20,
              onChange: setPage,
              showTotal: (total) => t('archive.totalRecords', { n: total }),
            }}
          />
        </div>
      </Card>

      <Modal
        title={detail?.name || t('archive.detail')}
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={'min(95vw, 62.5rem)' as any}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: '3.125rem' }}>{t('common.loading')}</div>
        ) : detail ? (
          <div>
            <Descriptions column={3} size="small" bordered style={{ marginBottom: 'var(--wh-space-md)' }}>
              <Descriptions.Item label={t('archive.colTable')}><Tag color="blue">{detail.table_name}</Tag></Descriptions.Item>
              <Descriptions.Item label={t('archive.colCreated')}>{formatDateTime(detail.created_at)}</Descriptions.Item>
              <Descriptions.Item label={t('archive.colUpdated')}>{formatDateTime(detail.updated_at)}</Descriptions.Item>
            </Descriptions>

            {detail.conclusions && detail.conclusions.length > 0 && (
              <Card size="small" title={t('archive.conclusions')} style={{ marginBottom: 'var(--wh-space-md)' }}>
                <List
                  size="small"
                  dataSource={detail.conclusions}
                  renderItem={(item: string) => (
                    <List.Item style={{ padding: 'var(--wh-space-xs) 0' }}>• {item}</List.Item>
                  )}
                />
              </Card>
            )}

            {detail.chart_config && (
              <Card size="small" title={t('archive.chartSnapshot')}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
                  {renderCharts(detail.chart_config)}
                </div>
              </Card>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
