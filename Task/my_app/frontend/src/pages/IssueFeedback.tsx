import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm,
  Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  BugOutlined, CheckCircleOutlined, DeleteOutlined, EditOutlined,
  MessageOutlined, PlusOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH, cardStyle } from '../theme'

// 与后端 routers/feedback.py 的枚举白名单保持一致
type Category = 'bug' | 'data' | 'feature' | 'other'
type Priority = 'low' | 'medium' | 'high' | 'urgent'
type Status = 'open' | 'processing' | 'resolved' | 'rejected'

interface IssueItem {
  id: number
  reporter: string
  contact?: string | null
  category: Category
  priority: Priority
  page?: string | null
  title: string
  description: string
  status: Status
  handler?: string | null
  resolution?: string | null
  created_at: string
  updated_at: string
}

interface Stats {
  total: number
  by_status: Record<string, number>
  by_category: Record<string, number>
  by_priority: Record<string, number>
}

const CATEGORY_COLORS: Record<Category, string> = { bug: 'red', data: 'orange', feature: 'blue', other: 'default' }
const PRIORITY_COLORS: Record<Priority, string> = { low: 'default', medium: 'blue', high: 'orange', urgent: 'red' }
const STATUS_COLORS: Record<Status, string> = { open: 'volcano', processing: 'processing', resolved: 'success', rejected: 'default' }

export default function IssueFeedback() {
  const { t } = useI18n()

  const catLabel = useCallback((v: Category) => t(`fb.cat.${v}`), [t])
  const priLabel = useCallback((v: Priority) => t(`fb.pri.${v}`), [t])
  const stLabel = useCallback((v: Status) => t(`fb.st.${v}`), [t])

  const [items, setItems] = useState<IssueItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  // 筛选条件
  const [fStatus, setFStatus] = useState<Status | undefined>()
  const [fCategory, setFCategory] = useState<Category | undefined>()
  const [fKeyword, setFKeyword] = useState('')

  // 提交表单
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  // 处理弹窗
  const [handleItem, setHandleItem] = useState<IssueItem | null>(null)
  const [handling, setHandling] = useState(false)
  const [hForm] = Form.useForm()

  const load = useCallback(async (p = page, ps = pageSize) => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { limit: ps, offset: (p - 1) * ps }
      if (fStatus) params.status = fStatus
      if (fCategory) params.category = fCategory
      if (fKeyword.trim()) params.keyword = fKeyword.trim()
      const [listRes, statsRes] = await Promise.all([
        api.get('/feedback', { params }),
        api.get('/feedback/stats'),
      ])
      setItems(listRes.data?.items || [])
      setTotal(listRes.data?.total || 0)
      setStats(statsRes.data || null)
    } catch (e: any) {
      message.error(t('fb.loadFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, fStatus, fCategory, fKeyword, t])

  useEffect(() => {
    load(1, pageSize)
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fStatus, fCategory])

  const refresh = () => load(page, pageSize)

  const submit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch { return }
    setSubmitting(true)
    try {
      await api.post('/feedback', values)
      message.success(t('fb.submitOk'))
      setSubmitOpen(false)
      form.resetFields()
      setPage(1)
      load(1, pageSize)
    } catch (e: any) {
      message.error(t('fb.submitFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setSubmitting(false)
    }
  }

  const openHandle = (it: IssueItem) => {
    setHandleItem(it)
    hForm.setFieldsValue({ status: it.status, handler: it.handler || '', resolution: it.resolution || '' })
  }

  const saveHandle = async () => {
    if (!handleItem) return
    let values: any
    try {
      values = await hForm.validateFields()
    } catch { return }
    setHandling(true)
    try {
      await api.put(`/feedback/${handleItem.id}`, values)
      message.success(t('fb.handleOk'))
      setHandleItem(null)
      load(page, pageSize)
    } catch (e: any) {
      message.error(t('fb.handleFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setHandling(false)
    }
  }

  const remove = async (id: number) => {
    try {
      await api.delete(`/feedback/${id}`)
      message.success(t('fb.deleteOk'))
      load(page, pageSize)
    } catch (e: any) {
      message.error(t('fb.deleteFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    }
  }

  const columns: ColumnsType<IssueItem> = useMemo(() => [
    { title: '#', dataIndex: 'id', width: 60 },
    {
      title: t('fb.col.title'), dataIndex: 'title', ellipsis: true,
      render: (v: string, r) => (
        <Tooltip title={r.description.length > 120 ? r.description : undefined}>
          <span style={{ color: WH.text }}>{v}</span>
        </Tooltip>
      ),
    },
    {
      title: t('fb.col.category'), dataIndex: 'category', width: 100,
      render: (v: Category) => <Tag color={CATEGORY_COLORS[v]}>{catLabel(v)}</Tag>,
    },
    {
      title: t('fb.col.priority'), dataIndex: 'priority', width: 90,
      render: (v: Priority) => <Tag color={PRIORITY_COLORS[v]}>{priLabel(v)}</Tag>,
    },
    {
      title: t('fb.col.status'), dataIndex: 'status', width: 100,
      render: (v: Status) => <Tag color={STATUS_COLORS[v]}>{stLabel(v)}</Tag>,
    },
    { title: t('fb.col.reporter'), dataIndex: 'reporter', width: 110, ellipsis: true },
    {
      title: t('fb.col.handler'), dataIndex: 'handler', width: 100, ellipsis: true,
      render: (v?: string | null) => v || <span style={{ color: WH.textMuted }}>-</span>,
    },
    { title: t('fb.col.created'), dataIndex: 'created_at', width: 150 },
    {
      title: t('fb.col.actions'), key: 'actions', width: 130, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openHandle(r)}>
            {t('fb.handle')}
          </Button>
          <Popconfirm title={t('fb.deleteConfirm')} onConfirm={() => remove(r.id)} okText={t('fb.ok')} cancelText={t('fb.cancel')}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t, catLabel, priLabel, stLabel, page, pageSize])

  const expandable = useMemo(() => ({
    expandedRowRender: (r: IssueItem) => (
      <Descriptions size="small" column={isMobileLike() ? 1 : 2}
        labelStyle={{ color: WH.textMuted }} contentStyle={{ color: WH.text }}>
        <Descriptions.Item label={t('fb.col.description')} span={2}>{r.description}</Descriptions.Item>
        <Descriptions.Item label={t('fb.col.contact')}>{r.contact || '-'}</Descriptions.Item>
        <Descriptions.Item label={t('fb.col.page')}>{r.page || '-'}</Descriptions.Item>
        <Descriptions.Item label={t('fb.col.resolution')} span={2}>{r.resolution || '-'}</Descriptions.Item>
        <Descriptions.Item label={t('fb.col.updated')} span={2}>{r.updated_at}</Descriptions.Item>
      </Descriptions>
    ),
  }), [t])

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      {/* 标题栏 */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center',
        justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem',
      }}>
        <div>
          <Typography.Title level={4} style={{ color: WH.text, margin: 0 }}>
            <MessageOutlined style={{ color: WH.teal, marginRight: 'var(--wh-space-sm)' }} />
            {t('fb.title')}
          </Typography.Title>
          <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginTop: 'var(--wh-space-xs)' }}>
            {t('fb.subtitle')}
          </div>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>{t('fb.refresh')}</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setSubmitOpen(true)}>
            {t('fb.newIssue')}
          </Button>
        </Space>
      </div>

      {/* 统计卡 */}
      {stats && (
        <Row gutter={[12, 12]} style={{ marginBottom: '0.75rem' }}>
          <Col xs={12} sm={6}>
            <Card size="small" style={cardStyle}>
              <Statistic title={<span style={{ color: WH.textMuted }}>{t('fb.stat.total')}</span>}
                value={stats.total} valueStyle={{ color: WH.teal }} />
            </Card>
          </Col>
          {(['open', 'processing', 'resolved'] as Status[]).map(s => (
            <Col xs={12} sm={6} key={s}>
              <Card size="small" style={cardStyle}>
                <Statistic title={<span style={{ color: WH.textMuted }}>{stLabel(s)}</span>}
                  value={stats.by_status[s] || 0}
                  valueStyle={{ color: s === 'open' ? '#fa541c' : s === 'processing' ? '#1677ff' : '#52c41a' }} />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 筛选栏 */}
      <Card size="small" style={{ ...cardStyle, marginBottom: '0.75rem' }}>
        <Space wrap>
          <Select
            allowClear placeholder={t('fb.filter.status')} style={{ width: 140 }}
            value={fStatus} onChange={v => setFStatus(v)}
            options={(Object.keys(STATUS_COLORS) as Status[]).map(s => ({ value: s, label: stLabel(s) }))}
          />
          <Select
            allowClear placeholder={t('fb.filter.category')} style={{ width: 140 }}
            value={fCategory} onChange={v => setFCategory(v)}
            options={(Object.keys(CATEGORY_COLORS) as Category[]).map(c => ({ value: c, label: catLabel(c) }))}
          />
          <Input
            allowClear style={{ width: 220 }} placeholder={t('fb.filter.keyword')}
            prefix={<SearchOutlined style={{ color: WH.textMuted }} />}
            value={fKeyword} onChange={e => setFKeyword(e.target.value)}
            onPressEnter={() => { setPage(1); load(1, pageSize) }}
          />
          <Button icon={<SearchOutlined />} onClick={() => { setPage(1); load(1, pageSize) }}>{t('fb.search')}</Button>
        </Space>
      </Card>

      {/* 列表 */}
      <Card size="small" style={cardStyle}>
        <Table<IssueItem>
          rowKey="id" size="small" loading={loading}
          columns={columns} dataSource={items} expandable={expandable}
          scroll={{ x: 960 }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (n) => `${t('fb.totalPrefix')} ${n} ${t('fb.totalSuffix')}`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); load(p, ps) },
          }}
        />
      </Card>

      {/* 提交问题弹窗 */}
      <Modal
        title={<span><BugOutlined style={{ color: WH.teal, marginRight: 8 }} />{t('fb.newIssue')}</span>}
        open={submitOpen} onOk={submit} onCancel={() => setSubmitOpen(false)}
        confirmLoading={submitting} okText={t('fb.submit')} cancelText={t('fb.cancel')}
        destroyOnClose
      >
        <Form form={form} layout="vertical" requiredMark={false} initialValues={{ category: 'bug', priority: 'medium' }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="reporter" label={t('fb.form.reporter')} rules={[{ required: true, message: t('fb.form.reporterReq') }]}>
                <Input placeholder={t('fb.form.reporterPh')} maxLength={64} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact" label={t('fb.form.contact')}>
                <Input placeholder={t('fb.form.contactPh')} maxLength={128} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="category" label={t('fb.col.category')}>
                <Select options={(Object.keys(CATEGORY_COLORS) as Category[]).map(c => ({ value: c, label: catLabel(c) }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label={t('fb.col.priority')}>
                <Select options={(Object.keys(PRIORITY_COLORS) as Priority[]).map(p => ({ value: p, label: priLabel(p) }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="page" label={t('fb.form.page')}>
            <Input placeholder={t('fb.form.pagePh')} maxLength={64} />
          </Form.Item>
          <Form.Item name="title" label={t('fb.form.title')} rules={[{ required: true, message: t('fb.form.titleReq') }]}>
            <Input placeholder={t('fb.form.titlePh')} maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label={t('fb.col.description')} rules={[{ required: true, message: t('fb.form.descReq') }]}>
            <Input.TextArea rows={4} placeholder={t('fb.form.descPh')} maxLength={4000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* 处理弹窗 */}
      <Modal
        title={<span><CheckCircleOutlined style={{ color: WH.teal, marginRight: 8 }} />{t('fb.handle')} #{handleItem?.id}</span>}
        open={!!handleItem} onOk={saveHandle} onCancel={() => setHandleItem(null)}
        confirmLoading={handling} okText={t('fb.save')} cancelText={t('fb.cancel')}
        destroyOnClose
      >
        <Form form={hForm} layout="vertical" requiredMark={false}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="status" label={t('fb.col.status')}>
                <Select options={(Object.keys(STATUS_COLORS) as Status[]).map(s => ({ value: s, label: stLabel(s) }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="handler" label={t('fb.col.handler')}>
                <Input placeholder={t('fb.form.handlerPh')} maxLength={64} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="resolution" label={t('fb.col.resolution')}>
            <Input.TextArea rows={3} placeholder={t('fb.form.resolutionPh')} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

/** 表格展开行的窄屏判定（仅用于 Descriptions 列数，避免整页 hook 依赖） */
function isMobileLike(): boolean {
  return window.innerWidth < 768
}
