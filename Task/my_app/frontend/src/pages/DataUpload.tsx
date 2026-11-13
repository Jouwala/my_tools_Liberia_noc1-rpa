import { useState } from 'react'
import { Card, Upload, Button, message, Table, Tag, List, Spin, Result, Descriptions, Collapse } from 'antd'
import { InboxOutlined, FileExcelOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons'
import ReactECharts from '../components/ECharts'
import api from '../api'
import { useI18n, numLocale } from '../i18n'
import { ExplainIcon, ExplainPopover } from '../components/MetricExplain'

const { Dragger } = Upload

interface UploadResult {
  filename: string
  tables: {
    sheet_name: string
    table_name: string
    row_count: number
    col_count: number
    profile_summary: {
      quality_score: number
      issue_count: number
      issues: { column: string; type: string; severity: string; description: string }[]
    }
    conclusions: string[]
  }[]
  elapsed_seconds: number
}

export default function DataUpload() {
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [history, setHistory] = useState<any[]>([])
  const { t, locale } = useI18n()

  const loadHistory = () => {
    api.get('/upload/history').then(res => setHistory(res.data.uploads || [])).catch(console.error)
  }

  const uploadProps = {
    name: 'file',
    multiple: false,
    accept: '.xlsx,.xls,.csv',
    customRequest: async (options: any) => {
      const { file } = options
      setUploading(true)
      setResult(null)

      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await api.post('/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 120000,
        })
        setResult(res.data)
        message.success(t('upload.success', { n: res.data.elapsed_seconds }))
        loadHistory()
      } catch (err: any) {
        message.error(t('upload.failed', { msg: err.response?.data?.detail || err.message }))
      } finally {
        setUploading(false)
      }
    },
    showUploadList: false,
  }

  return (
    <div>
      <Card title={t('upload.title')} style={{ marginBottom: 'var(--wh-space-md)' }}>
        <Dragger {...uploadProps} disabled={uploading}>
          <p className="ant-upload-drag-icon">
            {uploading ? <Spin size="large" /> : <InboxOutlined />}
          </p>
          <p className="ant-upload-text">{t('upload.dragText')}</p>
          <p className="ant-upload-hint">{t('upload.dragHint')}</p>
        </Dragger>
      </Card>

      {result && (
        <div>
          <Card
            title={<span><CheckCircleOutlined style={{ color: '#52c41a' }} /> {t('upload.resultTitle')} - {result.filename}</span>}
            extra={<ExplainPopover text={t('upload.explain.elapsed')}><Tag color="blue">{t('upload.elapsed')} {result.elapsed_seconds}s</Tag></ExplainPopover>}
            style={{ marginBottom: 'var(--wh-space-md)' }}
          >
            {result.tables.map((tbl, i) => (
              <Card
                key={i}
                size="small"
                title={<span><FileExcelOutlined /> {tbl.sheet_name} → {tbl.table_name}</span>}
                extra={
                  <span>
                    <ExplainPopover text={t('upload.explain.rows')}>
                      <Tag color="blue">{tbl.row_count.toLocaleString(numLocale(locale))} {t('common.rows')}</Tag>
                    </ExplainPopover>
                    <ExplainPopover text={t('upload.explain.cols')}>
                      <Tag color="green">{tbl.col_count} {t('common.cols')}</Tag>
                    </ExplainPopover>
                    <ExplainPopover text={t('upload.explain.quality')}>
                      <Tag color={tbl.profile_summary.quality_score >= 80 ? 'green' : 'orange'}>
                        {t('upload.quality')} {t('upload.qualityScore', { n: tbl.profile_summary.quality_score })}
                      </Tag>
                    </ExplainPopover>
                  </span>
                }
                style={{ marginBottom: 'var(--wh-space-sm)' }}
              >
                <Collapse
                  items={[
                    {
                      key: 'issues',
                      label: (
                        <span>
                          <WarningOutlined /> {t('upload.qualityIssues', { n: tbl.profile_summary.issue_count })}
                          <span style={{ marginLeft: 4 }}><ExplainIcon text={t('upload.explain.issues')} /></span>
                        </span>
                      ),
                      children: tbl.profile_summary.issues.length > 0 ? (
                        <div>
                          {/* 接口按 issues[:10] 下发，条数多时清单短于括号里的总数 —— 截断必须常驻可见 */}
                          {tbl.profile_summary.issue_count > tbl.profile_summary.issues.length && (
                            <div style={{ color: 'var(--wh-warning, #fa8c16)', fontSize: '0.75rem', marginBottom: 'var(--wh-space-sm)' }}>
                              {t('upload.issuesTruncated', {
                                shown: tbl.profile_summary.issues.length,
                                total: tbl.profile_summary.issue_count,
                              })}
                            </div>
                          )}
                          <List
                            size="small"
                            dataSource={tbl.profile_summary.issues}
                            renderItem={(item: any) => (
                              <List.Item>
                                <Tag color={item.severity === 'error' ? 'red' : item.severity === 'warning' ? 'orange' : 'blue'}>
                                  {item.severity}
                                </Tag>
                                <Tag>{item.column}</Tag>
                                {item.description}
                              </List.Item>
                            )}
                          />
                        </div>
                      ) : <div style={{ color: '#52c41a' }}>{t('upload.noIssues')}</div>,
                    },
                    {
                      key: 'conclusions',
                      label: t('upload.analysisConclusions'),
                      children: (
                        <List
                          size="small"
                          dataSource={tbl.conclusions}
                          renderItem={(item: string) => (
                            <List.Item style={{ padding: 'var(--wh-space-xs) 0' }}>• {item}</List.Item>
                          )}
                        />
                      ),
                    },
                  ]}
                />
              </Card>
            ))}
          </Card>
        </div>
      )}

      <Card title={t('upload.history')}>
        <Button onClick={loadHistory} style={{ marginBottom: 'calc(var(--wh-space-xs) + var(--wh-space-sm))' }}>{t('upload.refreshHistory')}</Button>
        <div className="wh-table-responsive">
          <Table
            dataSource={history}
            columns={[
              { title: t('upload.fileName'), dataIndex: 'original_name', key: 'original_name' },
              { title: t('upload.tableName'), dataIndex: 'table_name', key: 'table_name', render: (v: string) => <Tag color="blue">{v}</Tag> },
              { title: <span>{t('upload.rowCount')} <ExplainIcon text={t('upload.explain.rows')} /></span>, dataIndex: 'row_count', key: 'row_count' },
              { title: <span>{t('upload.colCount')} <ExplainIcon text={t('upload.explain.cols')} /></span>, dataIndex: 'col_count', key: 'col_count' },
              { title: t('upload.uploadTime'), dataIndex: 'uploaded_at', key: 'uploaded_at' },
            ]}
            size="small"
            rowKey="id"
            pagination={{ pageSize: 10 }}
            scroll={{ x: 'max-content' }}
          />
        </div>
      </Card>
    </div>
  )
}
