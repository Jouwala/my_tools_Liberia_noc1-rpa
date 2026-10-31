/* ============================================================================
 * ApCenter —— AP（Action Plan）工作台
 * ----------------------------------------------------------------------------
 * 一个页面三个页签（不拆多页，减少登记成本，也避免用户来回切菜单）：
 *   My AP      我负责的 / 我创建的 —— 确认接收、更新进度、提交审核
 *   Review     待我审核 —— 通过 / 退回
 *   All AP     管理员或 AP_MANAGER 才能看到全量，可新建与下发
 *
 * 组织架构来自 **Escalation Matrix**（升级机制，21 人 / 4 级），见
 * backend/services/ap_manager/org.py。选人时按"姓名 · 岗位"展示，落库的是姓名；
 * 后端用「账号 + 组织姓名 + 显示名」三套别名互认，所以执行人用门户账号登录
 * 也能看到派给自己（英文姓名）的 AP。
 *
 * 视觉与交互遵循项目约定：卡片走 components/cards，按钮只在后端允许时出现
 * （allowed 由详情接口返回，**仅用于展示**，真正的鉴权在服务端）。
 * ========================================================================== */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Col, DatePicker, Drawer, Form, Input, Modal, Progress, Row, Select,
  Space, Table, Tabs, Tag, Timeline, Tooltip, Upload, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckCircleOutlined, ClockCircleOutlined, CloudUploadOutlined, ExclamationCircleOutlined,
  PlusOutlined, ReloadOutlined, SendOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH } from '../theme'
import { CardBase, StatCard } from '../components/cards'

type ApStatus =
  | 'DRAFT' | 'ASSIGNED' | 'ACKNOWLEDGED' | 'IN_PROGRESS'
  | 'PENDING_REVIEW' | 'COMPLETED' | 'REJECTED' | 'CANCELLED'

interface OrgPerson {
  id: number
  level: string
  position?: string | null
  name: string
  email?: string | null
  username?: string | null
}

interface ApMeta {
  user: {
    username: string
    display_name: string
    email: string
    position: string
    level: string
    portal_role: string
    ap_role: string
    can_manage: boolean
  }
  org: OrgPerson[]
  statuses: ApStatus[]
  priorities: string[]
  categories: string[]
  default_groups: string[]
}

interface ApAttachment { name: string; stored: string; size: number; content_type?: string }

interface ApItem {
  id: number
  ap_no: string
  title: string
  category?: string | null
  description?: string | null
  priority: string
  status: ApStatus
  target_position?: string | null
  owner_username: string
  reviewer_username?: string | null
  progress?: number | null
  due_at?: string | null
  notify_groups?: string | null
  related_ticket_id?: string | null
  site_id?: string | null
  region?: string | null
  completion_note?: string | null
  reject_reason?: string | null
  attachments?: ApAttachment[]
  created_by: string
  created_at: string
  updated_at: string
  submitted_at?: string | null
  completed_at?: string | null
  is_overdue?: boolean
  allowed?: string[]
  updates?: { id: number; username: string; progress?: number | null; note?: string | null; created_at: string }[]
  reviews?: { id: number; reviewer_username: string; decision: string; comments?: string | null; created_at: string }[]
  timeline?: { id: number; actor?: string; action: string; from_status?: string; to_status?: string; created_at: string }[]
}

interface ApStats {
  total: number
  open: number
  overdue: number
  pending_review: number
  in_progress: number
  completed: number
}

const STATUS_COLOR: Record<string, string> = {
  DRAFT: 'default',
  ASSIGNED: 'blue',
  ACKNOWLEDGED: 'cyan',
  IN_PROGRESS: 'purple',
  PENDING_REVIEW: 'orange',
  COMPLETED: 'green',
  REJECTED: 'red',
  CANCELLED: 'default',
}

const PRIORITY_COLOR: Record<string, string> = {
  LOW: 'default', MEDIUM: 'blue', HIGH: 'orange', CRITICAL: 'red',
}

export default function ApCenter() {
  const { t } = useI18n()
  const [meta, setMeta] = useState<ApMeta | null>(null)
  const [scope, setScope] = useState<'mine' | 'review' | 'all'>('mine')
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [items, setItems] = useState<ApItem[]>([])
  const [stats, setStats] = useState<ApStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<ApItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const [acting, setActing] = useState(false)

  const loadMeta = useCallback(async () => {
    try {
      const r = await api.get('/ap/meta')
      setMeta(r.data)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('ap.loadFailed'))
    }
  }, [t])

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const [list, st] = await Promise.all([
        api.get('/ap', {
          params: {
            scope,
            status: status || undefined,
            keyword: keyword || undefined,
            overdue: overdueOnly || undefined,
            page: 1,
            page_size: 100,
          },
        }),
        api.get('/ap/stats'),
      ])
      setItems(list.data.items || [])
      setStats(st.data)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('ap.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [scope, status, keyword, overdueOnly, t])

  useEffect(() => { loadMeta() }, [loadMeta])
  useEffect(() => { loadList() }, [loadList])

  const openDetail = useCallback(async (id: number) => {
    setDetailLoading(true)
    try {
      const r = await api.get(`/ap/${id}`)
      setDetail(r.data)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('ap.loadFailed'))
    } finally {
      setDetailLoading(false)
    }
  }, [t])

  /** 统一动作调用：成功后刷新详情与列表；失败把后端 detail 原样弹出来。 */
  const act = useCallback(async (id: number, path: string, body?: any) => {
    setActing(true)
    try {
      await api.post(`/ap/${id}/${path}`, body || {})
      message.success(t('ap.actionDone'))
      await Promise.all([openDetail(id), loadList()])
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('ap.actionFailed'))
    } finally {
      setActing(false)
    }
  }, [openDetail, loadList, t])

  const submitCreate = useCallback(async (dispatch: boolean) => {
    try {
      const v = await form.validateFields()
      const body = {
        title: v.title,
        description: v.description,
        category: v.category,
        priority: v.priority,
        owner_username: v.owner,
        reviewer_username: v.reviewer || null,
        target_position: v.position || null,
        due_at: v.due ? v.due.format('YYYY-MM-DD HH:mm') : null,
        notify_groups: v.groups,
        related_ticket_id: v.ticket || null,
        site_id: v.site || null,
        region: v.region || null,
        dispatch,
      }
      await api.post('/ap', body)
      message.success(dispatch ? t('ap.createdAndDispatched') : t('ap.created'))
      setCreateOpen(false)
      form.resetFields()
      await loadList()
    } catch (e: any) {
      if (e?.errorFields) return   // 表单校验失败，antd 自己会标红
      message.error(e?.response?.data?.detail || t('ap.actionFailed'))
    }
  }, [form, loadList, t])

  const orgOptions = useMemo(() => {
    const list = meta?.org || []
    return list.map((p) => ({
      value: p.name,
      label: p.position ? `${p.name} · ${p.position}` : p.name,
      email: p.email || '',
      level: p.level,
    }))
  }, [meta])

  const mineKeys = useMemo(() => {
    const u = meta?.user
    if (!u) return new Set<string>()
    return new Set([u.username, u.display_name].filter(Boolean).map((x) => x.toLowerCase()))
  }, [meta])

  const isMine = (row: ApItem) =>
    mineKeys.has(String(row.owner_username || '').toLowerCase())
  const isMyReview = (row: ApItem) =>
    mineKeys.has(String(row.reviewer_username || '').toLowerCase())

  /** 行内快捷动作（仅展示用；后端逐动作校验，越权会 403）。 */
  const quickActions = (row: ApItem) => {
    const btns: { key: string; label: string; onClick: () => void }[] = []
    const mine = isMine(row)
    if (mine && row.status === 'ASSIGNED') {
      btns.push({ key: 'accept', label: t('ap.act.accept'), onClick: () => act(row.id, 'accept') })
    }
    if (mine && (row.status === 'ACKNOWLEDGED' || row.status === 'REJECTED')) {
      btns.push({ key: 'start', label: t('ap.act.start'), onClick: () => act(row.id, 'start') })
    }
    if (mine && (row.status === 'IN_PROGRESS' || row.status === 'ACKNOWLEDGED')) {
      btns.push({ key: 'submit', label: t('ap.act.submit'), onClick: () => openDetail(row.id) })
    }
    if (isMyReview(row) && row.status === 'PENDING_REVIEW') {
      btns.push({ key: 'review', label: t('ap.act.review'), onClick: () => openDetail(row.id) })
    }
    return btns
  }

  const columns: ColumnsType<ApItem> = [
    {
      title: t('ap.col.no'), dataIndex: 'ap_no', width: 150,
      render: (v: string, row) => (
        <a onClick={() => openDetail(row.id)} style={{ fontFamily: 'monospace' }}>{v}</a>
      ),
    },
    {
      title: t('ap.col.title'), dataIndex: 'title', ellipsis: true,
      render: (v: string, row) => (
        <Space size={4} direction="vertical" style={{ lineHeight: 1.3 }}>
          <a onClick={() => openDetail(row.id)}>{v}</a>
          <span style={{ fontSize: '0.75rem', color: WH.textDim }}>
            {row.target_position || row.category || '-'}
            {row.site_id ? ` · ${row.site_id}` : ''}
          </span>
        </Space>
      ),
    },
    {
      title: t('ap.col.priority'), dataIndex: 'priority', width: 96,
      render: (v: string) => <Tag color={PRIORITY_COLOR[v] || 'default'}>{t(`ap.pri.${v}`)}</Tag>,
    },
    {
      title: t('ap.col.status'), dataIndex: 'status', width: 150,
      render: (v: ApStatus, row) => (
        <Space size={4} wrap>
          <Tag color={STATUS_COLOR[v] || 'default'}>{t(`ap.st.${v}`)}</Tag>
          {row.is_overdue && (
            <Tooltip title={t('ap.overdueHint')}>
              <Tag color="red">{t('ap.overdue')}</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: t('ap.col.progress'), dataIndex: 'progress', width: 130,
      render: (v: number) => <Progress percent={Number(v) || 0} size="small" />,
    },
    {
      title: t('ap.col.owner'), dataIndex: 'owner_username', width: 140, ellipsis: true,
    },
    {
      title: t('ap.col.due'), dataIndex: 'due_at', width: 140,
      render: (v: string, row) => (
        <span style={{ color: row.is_overdue ? '#c0392b' : WH.textMuted }}>{v || '-'}</span>
      ),
    },
    {
      title: t('ap.col.action'), key: 'action', width: 170, fixed: 'right',
      render: (_: unknown, row) => {
        const btns = quickActions(row)
        return (
          <Space size={4} wrap>
            <Button size="small" type="link" onClick={() => openDetail(row.id)}>{t('ap.act.detail')}</Button>
            {btns.map((b) => (
              <Button key={b.key} size="small" type="primary" ghost onClick={b.onClick}>{b.label}</Button>
            ))}
          </Space>
        )
      },
    },
  ]

  const tabs = [
    { key: 'mine', label: t('ap.tab.mine') },
    { key: 'review', label: t('ap.tab.review') },
    ...(meta?.user.can_manage ? [{ key: 'all', label: t('ap.tab.all') }] : []),
  ]

  return (
    <div style={{ padding: '0.25rem' }}>
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <StatCard
            title={t('ap.stat.open')}
            value={stats?.open ?? 0}
            accentColor="var(--wh-teal)"
            subText={t('ap.stat.openHint')}
            onClick={() => { setOverdueOnly(false); setStatus(undefined) }}
          />
        </Col>
        <Col xs={12} md={6}>
          <StatCard
            title={t('ap.stat.inProgress')}
            value={stats?.in_progress ?? 0}
            accentColor="#7b5cd6"
            onClick={() => { setOverdueOnly(false); setStatus('IN_PROGRESS') }}
          />
        </Col>
        <Col xs={12} md={6}>
          <StatCard
            title={t('ap.stat.pendingReview')}
            value={stats?.pending_review ?? 0}
            accentColor="#d98324"
            onClick={() => { setOverdueOnly(false); setStatus('PENDING_REVIEW') }}
          />
        </Col>
        <Col xs={12} md={6}>
          <StatCard
            title={t('ap.stat.overdue')}
            value={stats?.overdue ?? 0}
            accentColor="#c0392b"
            subText={t('ap.stat.overdueHint')}
            onClick={() => { setStatus(undefined); setOverdueOnly(true) }}
          />
        </Col>
      </Row>

      <CardBase
        title={t('ap.pageTitle')}
        extra={
          <Space>
            <Input
              allowClear
              size="small"
              placeholder={t('ap.searchPlaceholder')}
              style={{ width: 200 }}
              onChange={(e) => setKeyword(e.target.value)}
            />
            <Select
              allowClear
              size="small"
              placeholder={t('ap.filterStatus')}
              style={{ width: 150 }}
              value={status}
              onChange={(v) => setStatus(v)}
              options={(meta?.statuses || []).map((s) => ({ value: s, label: t(`ap.st.${s}`) }))}
            />
            <Tooltip title={t('ap.act.refresh')}>
              <Button size="small" icon={<ReloadOutlined />} onClick={loadList} />
            </Tooltip>
            {meta?.user.can_manage && (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                {t('ap.create')}
              </Button>
            )}
          </Space>
        }
        style={{ marginTop: 12 }}
      >
        <Tabs
          size="small"
          activeKey={scope}
          onChange={(k) => setScope(k as 'mine' | 'review' | 'all')}
          items={tabs.map((x) => ({
            key: x.key,
            label: x.label,
            children: (
              <Table<ApItem>
                rowKey="id"
                size="small"
                loading={loading}
                columns={columns}
                dataSource={items}
                scroll={{ x: 1100 }}
                pagination={{ pageSize: 20, showSizeChanger: false }}
                locale={{ emptyText: t('ap.empty') }}
              />
            ),
          }))}
        />
      </CardBase>

      {/* ===== 新建 ===== */}
      <Modal
        open={createOpen}
        title={t('ap.createTitle')}
        width={720}
        onCancel={() => setCreateOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setCreateOpen(false)}>{t('ap.act.cancel')}</Button>,
          <Button key="draft" onClick={() => submitCreate(false)}>{t('ap.saveDraft')}</Button>,
          <Button key="dispatch" type="primary" icon={<SendOutlined />} onClick={() => submitCreate(true)}>
            {t('ap.dispatch')}
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" size="small"
              initialValues={{ priority: 'MEDIUM', category: 'OTHER', groups: (meta?.default_groups || ['lbr_assistant']).join(',') }}>
          <Form.Item name="title" label={t('ap.f.title')} rules={[{ required: true, message: t('ap.f.required') }]}>
            <Input maxLength={200} placeholder={t('ap.f.titlePh')} />
          </Form.Item>
          <Form.Item name="description" label={t('ap.f.desc')}>
            <Input.TextArea rows={3} placeholder={t('ap.f.descPh')} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="priority" label={t('ap.f.priority')}>
                <Select options={(meta?.priorities || []).map((p) => ({ value: p, label: t(`ap.pri.${p}`) }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="category" label={t('ap.f.category')}>
                <Select options={(meta?.categories || []).map((c) => ({ value: c, label: t(`ap.cat.${c}`) }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="due" label={t('ap.f.due')}>
                <DatePicker showTime style={{ width: '100%' }} format="YYYY-MM-DD HH:mm" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="owner" label={t('ap.f.owner')} rules={[{ required: true, message: t('ap.f.required') }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder={t('ap.f.ownerPh')}
                  options={orgOptions}
                  onChange={(name: string) => {
                    const hit = orgOptions.find((o) => o.value === name)
                    form.setFieldValue('position', hit?.level ? `${hit.label}` : undefined)
                  }}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="reviewer" label={t('ap.f.reviewer')}>
                <Select showSearch allowClear optionFilterProp="label"
                        placeholder={t('ap.f.reviewerPh')} options={orgOptions} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="position" hidden><Input /></Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="ticket" label={t('ap.f.ticket')}>
                <Input placeholder="TT-2026-00125" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="site" label={t('ap.f.site')}>
                <Input placeholder="LBR-MON-001" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="region" label={t('ap.f.region')}>
                <Input placeholder="MON" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="groups" label={t('ap.f.groups')} extra={t('ap.f.groupsHint')}>
            <Input placeholder="lbr_assistant" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ===== 详情 ===== */}
      <Drawer
        open={!!detail}
        onClose={() => setDetail(null)}
        width={760}
        title={detail ? `${detail.ap_no} · ${detail.title}` : ''}
        loading={detailLoading}
      >
        {detail && (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Space wrap>
              <Tag color={STATUS_COLOR[detail.status]}>{t(`ap.st.${detail.status}`)}</Tag>
              <Tag color={PRIORITY_COLOR[detail.priority]}>{t(`ap.pri.${detail.priority}`)}</Tag>
              {detail.is_overdue && <Tag color="red">{t('ap.overdue')}</Tag>}
              {detail.target_position && <Tag>{detail.target_position}</Tag>}
              <span style={{ color: WH.textMuted, fontSize: '0.8125rem' }}>
                {t('ap.col.owner')}: {detail.owner_username}
                {detail.reviewer_username ? ` · ${t('ap.col.reviewer')}: ${detail.reviewer_username}` : ''}
                {detail.due_at ? ` · ${t('ap.col.due')}: ${detail.due_at}` : ''}
              </span>
            </Space>

            {detail.description && (
              <div style={{ whiteSpace: 'pre-wrap', background: WH.bg, padding: 10, borderRadius: 6 }}>
                {detail.description}
              </div>
            )}

            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('ap.col.progress')}</div>
              <Progress percent={Number(detail.progress) || 0} />
            </div>

            {detail.reject_reason && (
              <div style={{ color: '#c0392b' }}>
                <ExclamationCircleOutlined /> {t('ap.returnReason')}: {detail.reject_reason}
              </div>
            )}
            {detail.completion_note && (
              <div>
                <div style={{ fontWeight: 600 }}>{t('ap.completionNote')}</div>
                <div style={{ whiteSpace: 'pre-wrap', color: WH.textMuted }}>{detail.completion_note}</div>
              </div>
            )}

            {/* 动作区：allowed 由后端按当前用户算，前端只是渲染 */}
            <Space wrap>
              {(detail.allowed || []).includes('dispatch') && (
                <Button type="primary" icon={<SendOutlined />} loading={acting}
                        onClick={() => act(detail.id, 'dispatch')}>{t('ap.act.dispatch')}</Button>
              )}
              {(detail.allowed || []).includes('accept') && (
                <Button type="primary" loading={acting}
                        onClick={() => act(detail.id, 'accept')}>{t('ap.act.accept')}</Button>
              )}
              {(detail.allowed || []).includes('start') && (
                <Button type="primary" loading={acting}
                        onClick={() => act(detail.id, 'start')}>{t('ap.act.start')}</Button>
              )}
              {(detail.allowed || []).includes('submit') && (
                <Button type="primary" icon={<CloudUploadOutlined />} loading={acting}
                        onClick={() => {
                          Modal.confirm({
                            title: t('ap.submitTitle'),
                            content: (
                              <Input.TextArea id="ap-submit-note" rows={3}
                                              placeholder={t('ap.completionNotePh')} />
                            ),
                            onOk: () => {
                              const el = document.getElementById('ap-submit-note') as HTMLTextAreaElement | null
                              return act(detail.id, 'submit', {
                                progress: 100,
                                completion_note: el?.value || '',
                              })
                            },
                          })
                        }}>{t('ap.act.submit')}</Button>
              )}
              {(detail.allowed || []).includes('approve') && (
                <Button type="primary" icon={<CheckCircleOutlined />} loading={acting}
                        onClick={() => act(detail.id, 'approve', { comments: t('ap.approvedDefault') })}>
                  {t('ap.act.approve')}
                </Button>
              )}
              {(detail.allowed || []).includes('reject') && (
                <Button danger loading={acting} onClick={() => {
                  Modal.confirm({
                    title: t('ap.rejectTitle'),
                    content: <Input.TextArea id="ap-reject-note" rows={3} placeholder={t('ap.rejectPh')} />,
                    onOk: () => {
                      const el = document.getElementById('ap-reject-note') as HTMLTextAreaElement | null
                      return act(detail.id, 'reject', { comments: el?.value || '' })
                    },
                  })
                }}>{t('ap.act.reject')}</Button>
              )}
              {(detail.allowed || []).includes('cancel') && (
                <Button danger loading={acting}
                        onClick={() => act(detail.id, 'cancel', { comments: '' })}>{t('ap.act.cancelAp')}</Button>
              )}
            </Space>

            {/* 凭证 */}
            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('ap.attachments')}</div>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                {(detail.attachments || []).map((a) => (
                  <a key={a.stored} href={`/api/ap/${detail.id}/attachments/${a.stored}`} target="_blank" rel="noreferrer">
                    {a.name} ({Math.round((a.size || 0) / 1024)} KB)
                  </a>
                ))}
                {(detail.allowed || []).includes('attach') && (
                  <Upload
                    multiple
                    showUploadList={false}
                    customRequest={async (opt) => {
                      const fd = new FormData()
                      fd.append('files', opt.file as File)
                      try {
                        await api.post(`/ap/${detail.id}/attachments`, fd)
                        message.success(t('ap.uploaded'))
                        openDetail(detail.id)
                      } catch (e: any) {
                        message.error(e?.response?.data?.detail || t('ap.actionFailed'))
                      }
                    }}
                  >
                    <Button size="small" icon={<CloudUploadOutlined />}>{t('ap.uploadEvidence')}</Button>
                  </Upload>
                )}
              </Space>
            </div>

            {/* 进度记录 */}
            {(detail.updates || []).length > 0 && (
              <div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('ap.updates')}</div>
                <Timeline
                  items={(detail.updates || []).map((u) => ({
                    color: 'blue',
                    children: (
                      <div>
                        <span style={{ color: WH.textMuted }}>{u.created_at} · {u.username}</span>
                        <span style={{ marginLeft: 8 }}>{u.progress}%</span>
                        {u.note && <div>{u.note}</div>}
                      </div>
                    ),
                  }))}
                />
              </div>
            )}

            {/* 审核记录 */}
            {(detail.reviews || []).length > 0 && (
              <div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('ap.reviews')}</div>
                <Timeline
                  items={(detail.reviews || []).map((r) => ({
                    color: r.decision === 'APPROVED' ? 'green' : 'red',
                    children: (
                      <div>
                        <span style={{ color: WH.textMuted }}>{r.created_at} · {r.reviewer_username}</span>
                        <Tag style={{ marginLeft: 8 }} color={r.decision === 'APPROVED' ? 'green' : 'red'}>
                          {r.decision === 'APPROVED' ? t('ap.act.approve') : t('ap.act.reject')}
                        </Tag>
                        {r.comments && <div>{r.comments}</div>}
                      </div>
                    ),
                  }))}
                />
              </div>
            )}

            {/* 操作时间线 */}
            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('ap.timeline')}</div>
              <Timeline
                items={(detail.timeline || []).map((h) => ({
                  color: 'gray',
                  children: (
                    <span style={{ fontSize: '0.8125rem' }}>
                      {h.created_at} · {h.actor || '-'} · {h.action}
                      {h.from_status && h.to_status && h.from_status !== h.to_status
                        ? ` (${h.from_status} → ${h.to_status})` : ''}
                    </span>
                  ),
                }))}
              />
            </div>

            <div style={{ color: WH.textDim, fontSize: '0.75rem' }}>
              <ClockCircleOutlined /> {t('ap.createdBy')} {detail.created_by} · {detail.created_at}
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}
