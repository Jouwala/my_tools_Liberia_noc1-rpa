// 总历史记录弹窗（跨所有任务的执行历史查询）—— P3 增强
// 数据源：GET /api/tasks/history（支持 task_id / success / trigger / keyword / 时间范围过滤 + 分页）
import { useState, useEffect, useMemo, useCallback } from 'react'
import { Button, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  GlobalOutlined,
  DownloadOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import api from '../../api'
import { WH } from '../../theme'
import { formatDateTime } from '../../datetime'
import { useI18n } from '../../i18n'
import type { TaskInfo, RunRecord } from './types'

const { Text } = Typography

const PAGE_SIZE = 20

function triggerLabel(trigger: string | undefined, locale: 'zh' | 'en'): { icon: string; text: string } {
  if (trigger === 'manual') return { icon: '🔧', text: locale === 'zh' ? '手动' : 'Manual' }
  if (trigger === 'scheduled') return { icon: '⏰', text: locale === 'zh' ? '定时' : 'Scheduled' }
  if (trigger === 'manual_stop') return { icon: '✋', text: locale === 'zh' ? '手动停止' : 'Stopped' }
  return { icon: '⏰', text: trigger || (locale === 'zh' ? '定时' : 'Scheduled') }
}

export function GlobalHistoryModal({
  open, tasks, onClose,
}: {
  open: boolean
  tasks: TaskInfo[]
  locale: 'zh' | 'en'
  onClose: () => void
}) {
  const { t, locale } = useI18n()
  const [rows, setRows] = useState<RunRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  // 筛选状态
  const [filterTask, setFilterTask] = useState<string>('')
  const [filterStatus, setFilterStatus] = useState<'all' | 'success' | 'failed'>('all')
  const [filterKeyword, setFilterKeyword] = useState('')
  const [filterRange, setFilterRange] = useState<number>(0) // 0=全部, 1=今天, 7, 30(天)

  // task_id -> 显示名（历史行的 task_name 可能为空，回退用）
  const taskNameMap = useMemo(() => {
    const m = new Map<string, string>()
    tasks.forEach(tt => m.set(tt.task_id, tt.name))
    return m
  }, [tasks])

  const taskOptions = useMemo(
    () => tasks
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(tt => ({ value: tt.task_id, label: `${tt.name} (${tt.task_id})` })),
    [tasks],
  )

  const buildParams = useCallback((targetPage: number, exportAll = false) => {
    const p = new URLSearchParams()
    if (exportAll) {
      p.set('limit', '10000')
      p.set('offset', '0')
    } else {
      p.set('limit', String(PAGE_SIZE))
      p.set('offset', String((targetPage - 1) * PAGE_SIZE))
    }
    if (filterTask) p.set('task_id', filterTask)
    if (filterStatus === 'success') p.set('success', '1')
    else if (filterStatus === 'failed') p.set('success', '0')
    if (filterKeyword.trim()) p.set('keyword', filterKeyword.trim())
    if (filterRange > 0) {
      p.set('start', new Date(Date.now() - filterRange * 86400000).toISOString())
    }
    return p.toString()
  }, [filterTask, filterStatus, filterKeyword, filterRange])

  const load = useCallback(async (targetPage = 1) => {
    setLoading(true)
    try {
      const res = await api.get(`/tasks/history?${buildParams(targetPage)}`)
      setRows(res.data.history || [])
      setTotal(res.data.total || 0)
      setPage(targetPage)
    } catch {
      message.error(t('sync.loadError'))
      setRows([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [buildParams, t])

  // 打开即加载；关闭时复位筛选
  useEffect(() => {
    if (open) load(1)
    else {
      setRows([]); setTotal(0); setPage(1)
      setFilterTask(''); setFilterStatus('all'); setFilterKeyword(''); setFilterRange(0)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // 筛选变更（任务/状态/时间范围）立即重新加载第 1 页；关键字做轻量防抖
  const reloadWithFilters = useCallback(() => { load(1) }, [load])
  useEffect(() => {
    if (!open) return
    const tm = setTimeout(reloadWithFilters, 350)
    return () => clearTimeout(tm)
  }, [filterTask, filterStatus, filterRange, filterKeyword, open, reloadWithFilters])

  const exportCsv = async () => {
    try {
      const res = await api.get(`/tasks/history?${buildParams(1, true)}`)
      const data: RunRecord[] = res.data.history || []
      if (!data.length) return
      const header = ['started_at', 'task_id', 'task_name', 'success', 'trigger', 'elapsed_seconds', 'error']
      const lines = [header.join(',')]
      data.forEach(r => {
        lines.push([
          r.started_at, r.task_id, r.task_name,
          r.success ? '1' : '0', r.trigger, r.elapsed_seconds,
          `"${(r.error || '').replace(/"/g, '""').replace(/\n/g, ' ')}"`,
        ].join(','))
      })
      const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `global_task_history_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error(t('sync.toggleAllFailed'))
    }
  }

  const columns = [
    {
      title: t('sync.ghTime'),
      dataIndex: 'started_at',
      key: 'started_at',
      minWidth: 160,
      render: (v: string) => <Text style={{ fontSize: '0.75rem', color: WH.textMuted }}>{formatDateTime(v)}</Text>,
    },
    {
      title: t('sync.ghTask'),
      dataIndex: 'task_name',
      key: 'task_name',
      minWidth: 160,
      render: (v: string | null, rec: RunRecord) => (
        <div>
          <div style={{ fontSize: '0.8125rem', color: WH.text }}>{v || taskNameMap.get(rec.task_id) || rec.task_id}</div>
          <Text style={{ fontSize: '0.6875rem', color: WH.textDim }}>{rec.task_id}</Text>
        </div>
      ),
    },
    {
      title: t('sync.ghResult'),
      dataIndex: 'success',
      key: 'success',
      minWidth: 90,
      render: (ok: boolean) => ok
        ? <Tag color="green" style={{ fontSize: '0.6875rem' }}>{t('sync.ghSuccess')}</Tag>
        : <Tag color="red" style={{ fontSize: '0.6875rem' }}>{t('sync.ghFailed')}</Tag>,
    },
    {
      title: t('sync.ghTrigger'),
      dataIndex: 'trigger',
      key: 'trigger',
      minWidth: 100,
      render: (tr: string) => {
        const { icon, text } = triggerLabel(tr, locale)
        return <Text style={{ fontSize: '0.75rem', color: WH.textMuted }}>{icon} {text}</Text>
      },
    },
    {
      title: t('sync.ghElapsed'),
      dataIndex: 'elapsed_seconds',
      key: 'elapsed_seconds',
      minWidth: 90,
      render: (v: number) => <Text style={{ fontSize: '0.75rem', color: WH.textDim }}>{(v ?? 0).toFixed(1)}s</Text>,
    },
    {
      title: t('sync.ghError'),
      dataIndex: 'error',
      key: 'error',
      minWidth: 200,
      ellipsis: true,
      render: (v: string | null) => v
        ? <Tooltip title={v}><Text code style={{
            fontSize: '0.6875rem', color: 'var(--wh-error-text)', maxWidth: 'min(50vw, 16.25rem)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block',
            background: 'rgba(255,77,79,0.08)', borderColor: 'rgba(255,77,79,0.2)',
          }}>❌ {(v || '').split('\n')[0].slice(0, 80)}</Text></Tooltip>
        : <Text style={{ fontSize: '0.75rem', color: WH.textDim }}>—</Text>,
    },
  ]

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={'min(98vw, 57.5rem)' as any}
      title={
        <span style={{ color: WH.text }}>
          <GlobalOutlined style={{ marginRight: 'var(--wh-space-sm)', color: WH.teal }} />
          {t('sync.globalHistory')}
        </span>
      }
      styles={{
        root: { background: WH.bg },
        header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid var(--wh-subtle-border)' },
        body: { background: WH.bg },
      }}
    >
      {/* 筛选工具栏 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-xs)', marginBottom: 'var(--wh-space-sm)', alignItems: 'center' }}>
        <Select
          allowClear
          showSearch
          value={filterTask || undefined}
          onChange={v => setFilterTask(v || '')}
          placeholder={t('sync.ghTask')}
          style={{ width: 'min(100%, 13.75rem)' }}
          options={taskOptions}
          filterOption={(input, opt) => (opt?.label || '').toLowerCase().includes(input.toLowerCase())}
        />
        <Select
          value={filterStatus}
          onChange={setFilterStatus}
          style={{ width: 'min(100%, 6.875rem)' }}
          options={[
            { value: 'all', label: t('sync.ghAllStatus') },
            { value: 'success', label: t('sync.ghSuccess') },
            { value: 'failed', label: t('sync.ghFailed') },
          ]}
        />
        <Select
          value={filterRange}
          onChange={setFilterRange}
          style={{ width: 'min(100%, 7.5rem)' }}
          options={[
            { value: 0, label: t('sync.ghRangeAll') },
            { value: 1, label: t('sync.ghRangeToday') },
            { value: 7, label: t('sync.ghRange7d') },
            { value: 30, label: t('sync.ghRange30d') },
          ]}
        />
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: WH.textDim }} />}
          placeholder={t('sync.ghKeyword')}
          value={filterKeyword}
          onChange={e => setFilterKeyword(e.target.value)}
          style={{ width: 'min(100%, 12.5rem)', background: 'var(--wh-input-bg)', color: WH.text, borderColor: 'var(--wh-input-border)' }}
        />
        <Text style={{ color: WH.textDim, fontSize: '0.75rem', marginLeft: 'auto' }}>
          {t('sync.ghTotal').replace('{n}', String(total))}
        </Text>
      </div>

      <div className="wh-table-responsive">
        <Table<RunRecord>
          size="small"
          rowKey={(r, i) => `${r.task_id}-${r.started_at}-${i}`}
          loading={loading}
          columns={columns as any}
          dataSource={rows}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showSizeChanger: false,
            onChange: (p) => load(p),
          }}
          locale={{ emptyText: <div style={{ color: WH.textMuted, padding: 'var(--wh-space-xl)' }}>{t('sync.ghNoData')}</div> }}
          scroll={{ x: 'max-content' }}
        />
      </div>

      <div style={{ textAlign: 'right', marginTop: 'var(--wh-space-sm)' }}>
        <Button size="small" icon={<DownloadOutlined />} onClick={exportCsv} disabled={!rows.length}
          style={{ color: WH.text, borderColor: 'rgba(0, 217, 255,0.25)' }}>
          {t('sync.ghExport')}
        </Button>
      </div>
    </Modal>
  )
}
