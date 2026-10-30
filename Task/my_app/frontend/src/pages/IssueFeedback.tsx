import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm,
  Row, Select, Space, Statistic, Table, Tag, Tooltip, Upload, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  BugOutlined, CheckCircleOutlined, DeleteOutlined, DownloadOutlined, EditOutlined,
  PaperClipOutlined, PlusOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH, cardStyle } from '../theme'
import { exportAoaReport } from '../utils/excelReport'

// 与后端 routers/feedback.py 的枚举白名单保持一致
type Category = 'bug' | 'data' | 'feature' | 'other'
type Priority = 'low' | 'medium' | 'high' | 'urgent'
type Status = 'open' | 'processing' | 'resolved' | 'rejected'

/** 附件元数据，与后端 issue_reports.attachments 的 JSON 结构一致 */
interface AttachmentMeta {
  name: string
  stored: string
  size: number
  content_type?: string
}

interface IssueItem {
  id: number
  reporter: string
  contact?: string | null
  category: Category
  priority: Priority
  page?: string | null
  title: string
  description: string
  attachments?: AttachmentMeta[] | null
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

// 附件限制（与后端 routers/feedback.py 的 _validate_attachments 保持一致）
const MAX_ATTACHMENTS = 5
const MAX_FILE_MB = 10
const DENIED_EXTS = new Set([
  '.exe', '.bat', '.cmd', '.com', '.scr', '.msi', '.dll',
  '.js', '.mjs', '.vbs', '.vbe', '.ps1', '.psm1', '.sh', '.jar', '.lnk', '.reg',
])

// 附件下载直链用的 API 基址（与 api 实例同源，兼容 ?api= 云端模式）
const API_BASE = (api.defaults.baseURL as string) || '/api'

/** antd Upload 受控值转换（valuePropName="fileList" 标准写法） */
function normFile(e: any): any[] {
  return Array.isArray(e) ? e : e?.fileList || []
}

/** 附件大小展示 */
function fmtSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`
  if (n >= 1024) return `${Math.round(n / 1024)}KB`
  return `${n}B`
}

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

  // 必填项 → 展示名映射：校验失败时用于汇总提示「哪些必填项没填」
  const requiredLabels: Record<string, string> = {
    reporter: t('fb.form.reporter'),
    contact: t('fb.form.contact'),
    category: t('fb.col.category'),
    priority: t('fb.col.priority'),
    page: t('fb.form.page'),
    title: t('fb.form.title'),
    description: t('fb.col.description'),
  }

  const submit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch (err: any) {
      // 字段级红字由 antd 同步展示；这里再弹一条汇总，一次性告诉用户缺了哪几项
      const missing = (err?.errorFields || [])
        .map((ef: any) => requiredLabels[ef.name?.[0]])
        .filter(Boolean)
      if (missing.length) message.warning(`${t('fb.form.missingPrefix')}：${missing.join('、')}`)
      return
    }
    setSubmitting(true)
    try {
      // 附件用 multipart 随表单一起发；后端全字段必填，这里做 trim 后原样提交
      const fd = new FormData()
      fd.append('reporter', values.reporter.trim())
      fd.append('contact', values.contact.trim())
      fd.append('category', values.category)
      fd.append('priority', values.priority)
      fd.append('page', values.page.trim())
      fd.append('title', values.title.trim())
      fd.append('description', values.description.trim())
      for (const f of (values.attachments || []) as any[]) {
        const raw = f?.originFileObj as File | undefined
        if (raw) fd.append('attachments', raw, raw.name)
      }
      await api.post('/feedback', fd)
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

  // 选附件时不自动上传，仅收集文件，提交时随 multipart 一起发；超量/超限/危险类型直接拒收
  const beforeUpload = (file: File) => {
    const list = (form.getFieldValue('attachments') || []) as any[]
    if (list.length >= MAX_ATTACHMENTS) {
      message.warning(t('fb.form.attachTooMany'))
      return Upload.LIST_IGNORE
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      message.warning(t('fb.form.attachTooLarge', { name: file.name }))
      return Upload.LIST_IGNORE
    }
    const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`
    if (DENIED_EXTS.has(ext)) {
      message.warning(t('fb.form.attachBadType', { name: file.name }))
      return Upload.LIST_IGNORE
    }
    return false
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
        <Descriptions.Item label={t('fb.col.attachments')} span={2}>
          {r.attachments?.length ? (
            <Space size={12} wrap>
              {r.attachments.map(a => (
                <a key={a.stored}
                  href={`${API_BASE}/feedback/${r.id}/attachments/${encodeURIComponent(a.stored)}`}
                  target="_blank" rel="noreferrer">
                  <PaperClipOutlined style={{ marginRight: 4 }} />{a.name}（{fmtSize(a.size)}）
                </a>
              ))}
            </Space>
          ) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label={t('fb.col.resolution')} span={2}>{r.resolution || '-'}</Descriptions.Item>
        <Descriptions.Item label={t('fb.col.updated')} span={2}>{r.updated_at}</Descriptions.Item>
      </Descriptions>
    ),
  }), [t])

  // ========== 导出 ==========
  /* 列表是服务端分页，导出**当前页**这 pageSize 条，并把页码范围与当前筛选条件
     写进副标题。展开行里的描述/联系方式/处理结论一并带入（界面上要点开才看得到）。 */
  const exportList = useCallback(() => {
    if (!items.length) return
    const header = [
      '#', t('fb.col.title'), t('fb.col.category'), t('fb.col.priority'), t('fb.col.status'),
      t('fb.col.reporter'), t('fb.col.handler'), t('fb.col.created'),
      t('fb.col.description'), t('fb.col.contact'), t('fb.col.page'),
      t('fb.col.resolution'), t('fb.col.updated'),
    ]
    const rows = items.map(r => [
      r.id, r.title, catLabel(r.category), priLabel(r.priority), stLabel(r.status),
      r.reporter, r.handler || '', r.created_at,
      r.description, r.contact || '', r.page || '', r.resolution || '', r.updated_at,
    ])
    const pageFrom = (page - 1) * pageSize + 1
    const filters = [
      `${t('fb.filter.status')}: ${fStatus ? stLabel(fStatus) : '-'}`,
      `${t('fb.filter.category')}: ${fCategory ? catLabel(fCategory) : '-'}`,
      `${t('fb.filter.keyword')}: ${fKeyword || '-'}`,
    ].join('    |    ')
    void exportAoaReport({
      filename: `issue_feedback_${new Date().toISOString().slice(0, 10)}.xlsx`,
      sheetName: 'Issue Feedback',
      title: t('fb.title'),
      subtitle: `${t('archive.exportRange', { from: pageFrom, to: pageFrom + items.length - 1, total })}    |    ${filters}`,
      header,
      rows,
      numericCols: [0],
      columnWidths: [6, 30, 12, 11, 12, 14, 12, 20, 46, 18, 16, 40, 20],
      tabColor: '#2F5496',
    })
  }, [items, page, pageSize, total, fStatus, fCategory, fKeyword, catLabel, priLabel, stLabel, t])

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      {/* 工具条：页面标题由 App 全局 Header 渲染（菜单名「使用反馈」），页内不再重复 */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center',
        justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem',
      }}>
        <div>
          <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>
            {t('fb.subtitle')}
          </div>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={exportList} disabled={!items.length}>
            {t('common.exportExcel')}
          </Button>
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
        <Form form={form} layout="vertical" initialValues={{ category: 'bug', priority: 'medium' }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="reporter" label={t('fb.form.reporter')} rules={[{ required: true, message: t('fb.form.reporterReq') }]}>
                <Input placeholder={t('fb.form.reporterPh')} maxLength={64} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact" label={t('fb.form.contact')} rules={[{ required: true, message: t('fb.form.contactReq') }]}>
                <Input placeholder={t('fb.form.contactPh')} maxLength={128} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="category" label={t('fb.col.category')} rules={[{ required: true, message: t('fb.form.categoryReq') }]}>
                <Select options={(Object.keys(CATEGORY_COLORS) as Category[]).map(c => ({ value: c, label: catLabel(c) }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label={t('fb.col.priority')} rules={[{ required: true, message: t('fb.form.priorityReq') }]}>
                <Select options={(Object.keys(PRIORITY_COLORS) as Priority[]).map(p => ({ value: p, label: priLabel(p) }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="page" label={t('fb.form.page')} rules={[{ required: true, message: t('fb.form.pageReq') }]}>
            <Input placeholder={t('fb.form.pagePh')} maxLength={64} />
          </Form.Item>
          <Form.Item name="title" label={t('fb.form.title')} rules={[{ required: true, message: t('fb.form.titleReq') }]}>
            <Input placeholder={t('fb.form.titlePh')} maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label={t('fb.col.description')} rules={[{ required: true, message: t('fb.form.descReq') }]}>
            <Input.TextArea rows={4} placeholder={t('fb.form.descPh')} maxLength={4000} showCount />
          </Form.Item>
          <Form.Item
            name="attachments" label={t('fb.form.attachments')}
            valuePropName="fileList" getValueFromEvent={normFile}
            extra={<span style={{ color: WH.textMuted }}>{t('fb.form.attachmentsHint')}</span>}
          >
            <Upload multiple beforeUpload={beforeUpload}>
              <Button icon={<PaperClipOutlined />}>{t('fb.form.attachmentsBtn')}</Button>
            </Upload>
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
