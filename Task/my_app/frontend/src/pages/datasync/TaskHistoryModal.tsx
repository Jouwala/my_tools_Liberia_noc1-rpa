// 任务执行历史弹窗（P3#10 拆分自 DataSync.tsx）
import { useState, useEffect } from 'react'
import { Button, Collapse, List, Modal, Space, Tag, Typography, message } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  HistoryOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import api from '../../api'
import { WH } from '../../theme'
import { formatTime } from './helpers'
import type { TaskDetail, RunRecord } from './types'

const { Text } = Typography

export function TaskHistoryModal({
  open, task, locale, onClose,
}: {
  open: boolean
  task: TaskDetail | null
  locale: 'zh' | 'en'
  onClose: () => void
}) {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [stats, setStats] = useState<{ success_rate: number | null; avg_elapsed: number | null; max_elapsed: number | null; total_runs: number } | null>(null)
  const [visible, setVisible] = useState(20)

  useEffect(() => {
    if (open && task) {
      api.get(`/tasks/${task.task_id}/history?limit=200`)
        .then(res => setRuns(res.data.history || []))
        .catch(() => setRuns([]))
      api.get(`/tasks/${task.task_id}/stats`)
        .then(res => setStats(res.data))
        .catch(() => setStats(null))
    } else {
      setRuns([])
      setStats(null)
      setVisible(20)
    }
  }, [open, task?.task_id])

  const exportCsv = () => {
    if (!runs.length) return
    const header = ['task_id', 'task_name', 'success', 'trigger', 'started_at', 'completed_at', 'elapsed_seconds', 'error']
    const lines = [header.join(',')]
    runs.forEach(r => {
      lines.push([
        r.task_id, r.task_name, r.success ? '1' : '0', r.trigger,
        r.started_at, r.completed_at, r.elapsed_seconds,
        `"${(r.error || '').replace(/"/g, '""').replace(/\n/g, ' ')}"`,
      ].join(','))
    })
    const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `task_history_${task?.task_id || 'all'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Modal
      title={
        <span style={{ color: WH.text }}>
          <HistoryOutlined style={{ marginRight: 8, color: WH.teal }} />
          {locale === 'zh' ? `执行历史 - ${task?.name}` : `Run History - ${task?.name}`}
        </span>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
      styles={{
        root: { background: WH.bg },
        header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid rgba(100,255,218,0.15)' },
        body: { background: WH.bg },
      }}
    >
      {stats && stats.total_runs > 0 && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
          <Text style={{ fontSize: 12, color: WH.textMuted }}>
            {locale === 'zh' ? '总运行' : 'Total'}: <b style={{ color: WH.text }}>{stats.total_runs}</b>
          </Text>
          <Text style={{ fontSize: 12, color: WH.textMuted }}>
            {locale === 'zh' ? '成功率' : 'Success'}:{' '}
            <b style={{ color: stats.success_rate != null && stats.success_rate >= 0.8 ? '#52c41a' : '#ff6b6b' }}>
              {stats.success_rate != null ? `${(stats.success_rate * 100).toFixed(1)}%` : '-'}
            </b>
          </Text>
          <Text style={{ fontSize: 12, color: WH.textMuted }}>
            {locale === 'zh' ? '平均耗时' : 'Avg'}: <b style={{ color: WH.text }}>{stats.avg_elapsed != null ? `${stats.avg_elapsed}s` : '-'}</b>
          </Text>
          <Text style={{ fontSize: 12, color: WH.textMuted }}>
            {locale === 'zh' ? '最大耗时' : 'Max'}: <b style={{ color: WH.text }}>{stats.max_elapsed != null ? `${stats.max_elapsed}s` : '-'}</b>
          </Text>
        </div>
      )}
      {runs.length > 0 ? (
        <>
        <List
          size="small"
          dataSource={runs.slice(0, visible)}
          renderItem={(run: RunRecord) => (
            <List.Item style={{
              background: run.success ? 'rgba(82, 196, 26, 0.05)' : 'rgba(255, 77, 79, 0.05)',
              borderRadius: 8,
              padding: '10px 14px',
              marginBottom: 6,
              border: `1px solid ${run.success ? 'rgba(82, 196, 26, 0.2)' : 'rgba(255, 77, 79, 0.2)'}`,
            }}>
              <List.Item.Meta
                avatar={run.success
                  ? <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />
                  : <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 18 }} />
                }
                title={
                  <Space>
                    <Tag color={run.success ? 'green' : 'red'}>
                      {run.success ? (locale === 'zh' ? '成功' : 'Success') : (locale === 'zh' ? '失败' : 'Failed')}
                    </Tag>
                    <Text style={{ fontSize: 12, color: WH.textMuted }}>
                      {run.trigger === 'manual' ? '🔧' : '⏰'} {formatTime(run.started_at)}
                    </Text>
                  </Space>
                }
                description={
                  <div>
                    <Text style={{ fontSize: 12, color: WH.textDim }}>⏱ {(run.elapsed_seconds ?? 0).toFixed(2)}s</Text>
                    {run.error && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <Text style={{ fontSize: 12, color: '#ff6b6b', fontWeight: 600 }}>
                            ❌ {locale === 'zh' ? '错误信息' : 'Error'}
                          </Text>
                          <Button
                            type="link"
                            size="small"
                            style={{ fontSize: 11, padding: 0, height: 'auto', color: WH.teal }}
                            onClick={() => {
                              navigator.clipboard?.writeText(run.error || '')
                                .then(() => message.success(locale === 'zh' ? '已复制错误' : 'Copied'))
                                .catch(() => {})
                            }}
                          >
                            {locale === 'zh' ? '复制' : 'Copy'}
                          </Button>
                        </div>
                        <pre style={{
                          margin: '4px 0 0', padding: '8px 10px', fontSize: 11, lineHeight: 1.5,
                          color: '#ffb3b3', background: 'rgba(255,77,79,0.08)', borderRadius: 6,
                          border: '1px solid rgba(255,77,79,0.2)', whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word', maxHeight: 160, overflow: 'auto',
                        }}>
                          {run.error}
                        </pre>
                        {run.error_trace && (
                          <Collapse
                            ghost
                            size="small"
                            style={{ marginTop: 6 }}
                            items={[{
                              key: 'trace',
                              label: <Text style={{ fontSize: 11, color: WH.textMuted }}>{locale === 'zh' ? '堆栈 / 详情' : 'Stack Trace'}</Text>,
                              children: (
                                <pre style={{
                                  margin: 0, padding: '8px 10px', fontSize: 10.5, lineHeight: 1.45,
                                  color: WH.textDim, background: 'rgba(0,0,0,0.25)', borderRadius: 6,
                                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 240, overflow: 'auto',
                                }}>
                                  {run.error_trace}
                                </pre>
                              ),
                            }]}
                          />
                        )}
                      </div>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
        {runs.length > visible && (
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <Button size="small" onClick={() => setVisible(v => v + 20)} style={{ color: WH.text }}>
              {locale === 'zh' ? `加载更多（已显示 ${visible}/${runs.length}）` : `Load More (${visible}/${runs.length})`}
            </Button>
          </div>
        )}
        <div style={{ textAlign: 'right', marginTop: 8 }}>
          <Button size="small" icon={<DownloadOutlined />} onClick={exportCsv} disabled={!runs.length}
            style={{ color: WH.text, borderColor: 'rgba(100,255,218,0.25)' }}>
            {locale === 'zh' ? '导出 CSV' : 'Export CSV'}
          </Button>
        </div>
        </>
      ) : (
        <div style={{ textAlign: 'center', color: WH.textMuted, padding: 24 }}>
          {locale === 'zh' ? '暂无执行记录' : 'No run history'}
        </div>
      )}
    </Modal>
  )
}
