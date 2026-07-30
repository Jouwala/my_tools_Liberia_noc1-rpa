import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Card, Button, Tag, Space, List, Spin, message, Modal, Select,
  Input, Switch, Tooltip, Badge, Progress, Row, Col, Typography,
} from 'antd'
import {
  ClockCircleOutlined,
  ThunderboltOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SettingOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  ScheduleOutlined,
  HistoryOutlined,
  EditOutlined,
  SyncOutlined,
  CloudServerOutlined,
  WifiOutlined,
  CameraOutlined,
  MessageOutlined,
  InfoCircleOutlined,
  BarChartOutlined,
  FundOutlined,
  AppstoreOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { useTaskStatus } from '../TaskStatusContext'
import { cachedGet, invalidateCache } from '../cache'
import { WH, cardStyle, controlCardStyle, pageWrap } from '../theme'

const { Text, Title } = Typography

// ===== Types =====
interface TaskInfo {
  task_id: string
  name: string
  description: string
  category: string
  enabled: boolean
  current_cron: string
  default_cron: string
  next_run: string | null
  registered_at: string
}

interface TaskDetail extends TaskInfo {
  recent_runs: RunRecord[]
}

interface RunRecord {
  task_id: string
  task_name: string
  category: string
  trigger: string
  success: boolean
  started_at: string
  completed_at: string
  elapsed_seconds: number
  error: string | null
}

// ===== Cron Helpers =====
const CRON_PRESETS: Record<string, { label_zh: string; label_en: string; cron: string }[]> = {
  hourly: [
    { label_zh: '每小时', label_en: 'Every Hour', cron: '0 * * * *' },
    { label_zh: '每小时第22分', label_en: 'Every Hour :22', cron: '22 * * * *' },
    { label_zh: '每2小时', label_en: 'Every 2 Hours', cron: '0 */2 * * *' },
    { label_zh: '每4小时', label_en: 'Every 4 Hours', cron: '0 */4 * * *' },
    { label_zh: '每6小时', label_en: 'Every 6 Hours', cron: '0 */6 * * *' },
    { label_zh: '每12小时', label_en: 'Every 12 Hours', cron: '0 */12 * * *' },
  ],
  daily: [
    { label_zh: '每天 00:00', label_en: 'Daily 00:00', cron: '0 0 * * *' },
    { label_zh: '每天 01:00', label_en: 'Daily 01:00', cron: '0 1 * * *' },
    { label_zh: '每天 02:00', label_en: 'Daily 02:00', cron: '0 2 * * *' },
    { label_zh: '每天 03:00', label_en: 'Daily 03:00', cron: '0 3 * * *' },
    { label_zh: '每天 06:00', label_en: 'Daily 06:00', cron: '0 6 * * *' },
    { label_zh: '每天 08:00', label_en: 'Daily 08:00', cron: '0 8 * * *' },
    { label_zh: '每天 12:00', label_en: 'Daily 12:00', cron: '0 12 * * *' },
    { label_zh: '每天 18:00', label_en: 'Daily 18:00', cron: '0 18 * * *' },
  ],
  weekly: [
    { label_zh: '周一 08:00', label_en: 'Mon 08:00', cron: '0 8 * * 1' },
    { label_zh: '周五 18:00', label_en: 'Fri 18:00', cron: '0 18 * * 5' },
    { label_zh: '工作日 08:00', label_en: 'Weekdays 08:00', cron: '0 8 * * 1-5' },
    { label_zh: '工作日 18:00', label_en: 'Weekdays 18:00', cron: '0 18 * * 1-5' },
  ],
}

function cronToHuman(cron: string, locale: 'zh' | 'en'): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hr, day, mon, dow] = parts

  // Every N hours
  if (hr.startsWith('*/')) {
    const n = hr.slice(2)
    return locale === 'zh' ? `每 ${n} 小时（第 ${min} 分钟）` : `Every ${n}h (at :${min})`
  }
  // Every hour
  if (hr === '*' && min !== '*') {
    return locale === 'zh' ? `每小时第 ${min} 分钟` : `Every hour at :${min}`
  }
  if (hr === '*' && min === '*') {
    return locale === 'zh' ? '每分钟' : 'Every minute'
  }
  // Specific time daily
  if (day === '*' && mon === '*' && dow === '*') {
    return locale === 'zh' ? `每天 ${hr.padStart(2, '0')}:${min.padStart(2, '0')}` : `Daily ${hr.padStart(2, '0')}:${min.padStart(2, '0')}`
  }
  // Day of week
  if (dow !== '*') {
    const dowMap: Record<string, string> = {
      '1': locale === 'zh' ? '周一' : 'Mon',
      '2': locale === 'zh' ? '周二' : 'Tue',
      '3': locale === 'zh' ? '周三' : 'Wed',
      '4': locale === 'zh' ? '周四' : 'Thu',
      '5': locale === 'zh' ? '周五' : 'Fri',
      '6': locale === 'zh' ? '周六' : 'Sat',
      '0': locale === 'zh' ? '周日' : 'Sun',
      '1-5': locale === 'zh' ? '工作日' : 'Weekdays',
    }
    const dowLabel = dowMap[dow] || dow
    return locale === 'zh' ? `${dowLabel} ${hr.padStart(2, '0')}:${min.padStart(2, '0')}` : `${dowLabel} ${hr.padStart(2, '0')}:${min.padStart(2, '0')}`
  }
  return cron
}

const CATEGORY_CONFIG: Record<string, { color: string; icon: React.ReactNode; label_zh: string; label_en: string }> = {
  eflow: { color: '#1677ff', icon: <CloudServerOutlined />, label_zh: 'eFlow 数据', label_en: 'eFlow Data' },
  ran_ume: { color: '#52c41a', icon: <WifiOutlined />, label_zh: 'RAN UME', label_en: 'RAN UME' },
  site_outage: { color: '#fa8c16', icon: <CameraOutlined />, label_zh: 'Site Outage', label_en: 'Site Outage' },
  whatsapp: { color: '#25D366', icon: <MessageOutlined />, label_zh: 'WhatsApp', label_en: 'WhatsApp' },
  ms_sla: { color: '#722ed1', icon: <BarChartOutlined />, label_zh: 'MS SLA/NUR', label_en: 'MS SLA/NUR' },
  main_kpi: { color: '#13c2c2', icon: <FundOutlined />, label_zh: 'Main KPI', label_en: 'Main KPI' },
  network_kpi: { color: '#eb2f96', icon: <BarChartOutlined />, label_zh: 'Network KPI', label_en: 'Network KPI' },
  cnn_kpi: { color: '#fa541c', icon: <CloudServerOutlined />, label_zh: 'CNN UME', label_en: 'CNN UME' },
  general: { color: '#8c8c8c', icon: <SettingOutlined />, label_zh: '通用', label_en: 'General' },
  sp: { color: '#faad14', icon: <AppstoreOutlined />, label_zh: 'SP 备件', label_en: 'SP Spare' },
  ipran_kpi: { color: '#2f54eb', icon: <GlobalOutlined />, label_zh: 'iPRAN UME', label_en: 'iPRAN UME' },
}

function formatTime(isoStr: string | null): string {
  if (!isoStr) return '-'
  return isoStr.replace('T', ' ').substring(0, 19)
}

// ===== Schedule Editor Modal =====
function ScheduleEditor({
  open, task, locale, onClose, onSave,
}: {
  open: boolean
  task: TaskInfo | null
  locale: 'zh' | 'en'
  onClose: () => void
  onSave: (taskId: string, cron: string) => Promise<void>
}) {
  const { t } = useI18n()
  const [cronInput, setCronInput] = useState('')
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (task) {
      setCronInput(task.current_cron)
      setSelectedPreset(null)
    }
  }, [task])

  const handlePreset = (cron: string) => {
    setCronInput(cron)
    setSelectedPreset(cron)
  }

  const handleSave = async () => {
    if (!task || !cronInput.trim()) return
    setSaving(true)
    try {
      await onSave(task.task_id, cronInput.trim())
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const presets = [...CRON_PRESETS.hourly, ...CRON_PRESETS.daily, ...CRON_PRESETS.weekly]

  return (
    <Modal
      title={
        <span style={{ color: WH.text }}>
          <ScheduleOutlined style={{ marginRight: 8, color: WH.teal }} />
          {locale === 'zh' ? `编辑调度 - ${task?.name}` : `Edit Schedule - ${task?.name}`}
        </span>
      }
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving}
      okText={locale === 'zh' ? '保存' : 'Save'}
      cancelText={locale === 'zh' ? '取消' : 'Cancel'}
      width={640}
      styles={{
        root: { background: WH.bg },
        header: { background: '#0a1929', borderBottom: '1px solid rgba(100,255,218,0.15)' },
        body: { background: WH.bg },
      }}
    >
      {task && (
        <div>
          {/* Current schedule */}
          <div style={{ marginBottom: 16 }}>
            <Text style={{ color: WH.textMuted }}>{locale === 'zh' ? '当前调度：' : 'Current: '}</Text>
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {cronToHuman(task.current_cron, locale)}
            </Tag>
            <Text code style={{ marginLeft: 8, color: WH.textMuted, background: 'rgba(255,255,255,0.06)' }}>{task.current_cron}</Text>
          </div>

          {/* Presets */}
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ display: 'block', marginBottom: 8, color: WH.text }}>
              {locale === 'zh' ? '⏰ 快捷预设' : '⏰ Quick Presets'}
            </Text>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {presets.map(p => (
                <Button
                  key={p.cron}
                  size="small"
                  type={selectedPreset === p.cron ? 'primary' : 'default'}
                  onClick={() => handlePreset(p.cron)}
                  style={selectedPreset !== p.cron ? { color: WH.text, borderColor: 'rgba(100,255,218,0.25)', background: 'rgba(100,255,218,0.06)' } : undefined}
                >
                  {locale === 'zh' ? p.label_zh : p.label_en}
                </Button>
              ))}
            </div>
          </div>

          {/* Custom cron */}
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ display: 'block', marginBottom: 8, color: WH.text }}>
              {locale === 'zh' ? '✏️ 自定义 Cron 表达式' : '✏️ Custom Cron Expression'}
            </Text>
            <Input
              value={cronInput}
              onChange={e => { setCronInput(e.target.value); setSelectedPreset(null) }}
              placeholder={t('sync.cronPlaceholder')}
              style={{ fontFamily: 'monospace', fontSize: 14, background: 'rgba(255,255,255,0.05)', color: WH.text, borderColor: 'rgba(100,255,218,0.18)' }}
            />
            <div style={{ marginTop: 8, color: WH.textDim, fontSize: 12 }}>
              {locale === 'zh'
                ? '格式: 分 时 日 月 周  示例: 0 8 * * * = 每天8点 | 0 */4 * * * = 每4小时 | 30 7 * * 1-5 = 工作日7:30'
                : 'Format: min hr day mon dow  e.g.: 0 8 * * * = Daily 8am | 0 */4 * * * = Every 4h | 30 7 * * 1-5 = Weekdays 7:30'
              }
            </div>
            {cronInput && (
              <div style={{ marginTop: 8 }}>
                <Text style={{ color: WH.textMuted }}>{locale === 'zh' ? '预览：' : 'Preview: '}</Text>
                <Tag color="green" style={{ marginLeft: 8 }}>
                  {cronToHuman(cronInput, locale)}
                </Tag>
              </div>
            )}
          </div>

          {/* Default cron */}
          <div>
            <Text style={{ color: WH.textMuted }}>
              {locale === 'zh' ? '默认值：' : 'Default: '}
            </Text>
            <Button
              size="small"
              type="link"
              onClick={() => handlePreset(task.default_cron)}
              style={{ color: WH.teal }}
            >
              {cronToHuman(task.default_cron, locale)} ({task.default_cron})
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ===== Task History Modal =====
function TaskHistoryModal({
  open, task, locale, onClose,
}: {
  open: boolean
  task: TaskDetail | null
  locale: 'zh' | 'en'
  onClose: () => void
}) {
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
        header: { background: '#0a1929', borderBottom: '1px solid rgba(100,255,218,0.15)' },
        body: { background: WH.bg },
      }}
    >
      {task?.recent_runs && task.recent_runs.length > 0 ? (
        <List
          size="small"
          dataSource={task.recent_runs}
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
                      <Text style={{ fontSize: 12, marginLeft: 12, color: '#ff6b6b' }}>
                        ❌ {run.error}
                      </Text>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      ) : (
        <div style={{ textAlign: 'center', color: WH.textMuted, padding: 24 }}>
          {locale === 'zh' ? '暂无执行记录' : 'No run history'}
        </div>
      )}
    </Modal>
  )
}

// ===== Main Component =====
export default function DataSync() {
  const { t, locale } = useI18n()
  const { runningMap } = useTaskStatus()
  const [tasks, setTasks] = useState<TaskInfo[]>([])
  const [taskDetails, setTaskDetails] = useState<Record<string, TaskDetail>>({})
  const [loading, setLoading] = useState(false)
  // 本地乐观状态：仅用于点击后到后端轮询确认"运行中"之间的过渡，最终以后端 runningMap 为准
  const [localRunning, setLocalRunning] = useState<Set<string>>(new Set())
  const startedRef = useRef<Set<string>>(new Set())
  const prevRunningRef = useRef<Record<string, boolean>>({})

  // Modal states
  const [editTask, setEditTask] = useState<TaskInfo | null>(null)
  const [historyTask, setHistoryTask] = useState<TaskDetail | null>(null)

  const loadTasks = useCallback(async (force = false) => {
    if (force) invalidateCache('sync:')
    setLoading(true)
    try {
      // 单次请求即返回全部任务 + 最新执行记录（后端已合并，不再 N+1）
      // 缓存键与请求头均带 locale，保证中/英切换后立即拉取对应语言的任务名
      const res = await cachedGet(
        `sync:tasks:${locale}`,
        () => api.get('/tasks', { headers: { 'Accept-Language': locale === 'en' ? 'en' : 'zh-CN' } }),
        15000,
      )
      const list: TaskInfo[] = res.data.tasks || []
      setTasks(list)
      // 由列表响应直接构建详情（recent_runs 已含最新 1 条，足够卡片展示）
      const details: Record<string, TaskDetail> = {}
      list.forEach(task => { details[task.task_id] = task as TaskDetail })
      setTaskDetails(details)
    } catch {
      message.error(t('sync.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t, locale])

  useEffect(() => { loadTasks() }, [loadTasks])

  // 监听后端 running 状态：完成（running true->false）时刷新卡片并提示结果
  useEffect(() => {
    const prev = prevRunningRef.current
    Object.keys(runningMap).forEach(id => {
      const wasRunning = !!prev[id]
      const nowRunning = !!runningMap[id]
      // 后端已确认运行中 -> 交还给后端指标，移除本地乐观标记
      if (nowRunning && localRunning.has(id)) {
        setLocalRunning(s => { const n = new Set(s); n.delete(id); return n })
      }
      // 检测到执行完成
      if (wasRunning && !nowRunning) {
        loadTasks(true)
        if (startedRef.current.has(id)) {
          startedRef.current.delete(id)
          api.get(`/tasks/${id}`).then(res => {
            const run = res.data.recent_runs?.[0]
            if (run) {
              if (run.success) message.success(t('sync.runSuccess', { name: run.task_name || id }))
              else message.error(t('sync.runFailed', { name: id }))
            }
          }).catch(() => {})
        }
      }
    })
    prevRunningRef.current = { ...runningMap }
  }, [runningMap, loadTasks])

  const handleRun = async (taskId: string) => {
    // 乐观标记，立即反馈；真实状态由后端轮询接管
    setLocalRunning(prev => new Set(prev).add(taskId))
    startedRef.current.add(taskId)
    try {
      const res = await api.post(`/tasks/${taskId}/run`)
      if (res.data.accepted) {
        message.success(t('sync.runStarted', { name: tasks.find(t2 => t2.task_id === taskId)?.name || taskId }))
      } else if (res.data.error) {
        // 未真正启动（如已在运行/已禁用）
        message.error(res.data.error)
        setLocalRunning(prev => { const s = new Set(prev); s.delete(taskId); return s })
        startedRef.current.delete(taskId)
      }
    } catch {
      message.error(t('sync.runFailed', { name: taskId }))
      setLocalRunning(prev => { const s = new Set(prev); s.delete(taskId); return s })
      startedRef.current.delete(taskId)
    }
  }

  const handleSaveSchedule = async (taskId: string, cron: string) => {
    try {
      const res = await api.post(`/tasks/${taskId}/schedule`, { cron })
      if (res.data.success) {
        message.success(t('sync.scheduleUpdated'))
        loadTasks(true)
      } else {
        message.error(res.data.error || t('sync.scheduleUpdateFailed'))
      }
    } catch {
      message.error(t('sync.scheduleUpdateFailed'))
    }
  }

  const handleToggle = async (taskId: string, enabled: boolean) => {
    try {
      const res = await api.post(`/tasks/${taskId}/toggle`, { enabled })
      if (res.data.success) {
        message.success(enabled ? t('sync.taskEnabled') : t('sync.taskDisabled'))
        loadTasks(true)
      }
    } catch {
      message.error(t('sync.toggleFailed'))
    }
  }

  // 历史弹窗：打开时按需拉取该任务完整执行记录（10 条），避免首屏 N+1
  const handleOpenHistory = async (taskId: string) => {
    try {
      const res = await api.get(`/tasks/${taskId}`)
      setHistoryTask(res.data)
    } catch {
      message.error(t('sync.loadError'))
    }
  }

  const getCategoryConfig = (cat: string) => CATEGORY_CONFIG[cat] || CATEGORY_CONFIG.general

  const getLastRun = (taskId: string): RunRecord | null => {
    const detail = taskDetails[taskId]
    if (!detail?.recent_runs?.length) return null
    return detail.recent_runs[0]
  }

  const getNextRunTime = (task: TaskInfo): string => {
    if (!task.next_run) return '-'
    // Parse ISO datetime
    try {
      const dt = new Date(task.next_run)
      return dt.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
    } catch {
      return task.next_run
    }
  }

  // 定义行分组（按 task_id）
  const ROW_GROUPS: { label_zh: string; label_en: string; task_ids: string[] }[] = [
    {
      label_zh: 'eFlow 数据同步',
      label_en: 'eFlow Data Sync',
      task_ids: ['eflow_sync', 'eflow_history_alarm', 'eflow_active_alarm'],
    },
    {
      label_zh: 'RAN UME 数据同步',
      label_en: 'RAN UME Data Sync',
      task_ids: ['ran_ume_daily', 'main_kpi_sync', 'network_kpi_sync'],
    },
    {
      label_zh: '其他任务',
      label_en: 'Other Tasks',
      task_ids: ['site_outage_screenshot', 'whatsapp_send', 'ms_sla_full'],
    },
    {
      label_zh: 'SP 备件数据同步',
      label_en: 'SP Spare Data Sync',
      task_ids: ['sp_data_sync'],
    },
    {
      label_zh: 'CNN UME 数据同步',
      label_en: 'CNN UME Data Sync',
      task_ids: ['cnn_kpi_sync'],
    },
    {
      label_zh: 'iPRAN UME 数据同步',
      label_en: 'iPRAN UME Data Sync',
      task_ids: ['ipran_kpi_sync'],
    },
  ]

  // 根据 task_id 快速查找任务
  const taskMap = new Map(tasks.map(t => [t.task_id, t]))

  const renderTaskCard = (taskId: string) => {
    const task = taskMap.get(taskId)
    if (!task) return null

    const catCfg = getCategoryConfig(task.category)
    const lastRun = getLastRun(task.task_id)
    const isRunning = runningMap[task.task_id] || localRunning.has(task.task_id)

    return (
      <Col key={task.task_id} xs={24} sm={24} md={8} lg={8} xl={8}>
        <Card
          size="small"
          style={{
            ...cardStyle,
            borderLeft: `4px solid ${task.enabled ? catCfg.color : '#64748b'}`,
            opacity: task.enabled ? 1 : 0.65,
            height: '100%',
          }}
          styles={{ body: { padding: '16px 20px' } }}
        >
          {/* Task header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
            <div>
              <Space size={4} align="center">
                <span style={{ fontSize: 16, color: catCfg.color }}>{catCfg.icon}</span>
                <Text strong style={{ fontSize: 15, color: WH.text }}>{task.name}</Text>
              </Space>
              <div style={{ marginTop: 4 }}>
                <Tag color={catCfg.color} style={{ fontSize: 11 }}>{locale === 'zh' ? catCfg.label_zh : catCfg.label_en}</Tag>
                {task.enabled ? (
                  <Badge status="success" text={<Text style={{ fontSize: 11, color: WH.textMuted }}>{locale === 'zh' ? '已启用' : 'Enabled'}</Text>} />
                ) : (
                  <Badge status="default" text={<Text style={{ fontSize: 11, color: WH.textDim }}>{locale === 'zh' ? '已禁用' : 'Disabled'}</Text>} />
                )}
              </div>
            </div>
            <Switch
              size="small"
              checked={task.enabled}
              onChange={(checked) => handleToggle(task.task_id, checked)}
            />
          </div>

          {/* Description */}
          <Text style={{ fontSize: 12, display: 'block', marginBottom: 12, lineHeight: 1.5, color: WH.textMuted }}>
            {task.description}
          </Text>

          {/* Schedule info */}
          <div style={{
            background: 'rgba(255,255,255,0.05)',
            borderRadius: 8,
            padding: '10px 14px',
            marginBottom: 12,
            border: '1px solid rgba(100,255,218,0.1)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <Space size={4}>
                <ClockCircleOutlined style={{ color: WH.blue }} />
                <Text style={{ fontSize: 13, color: WH.text }}>
                  {cronToHuman(task.current_cron, locale)}
                </Text>
              </Space>
              <Tooltip title={locale === 'zh' ? '编辑调度' : 'Edit Schedule'}>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined style={{ color: WH.teal }} />}
                  onClick={() => setEditTask(task)}
                  style={{ color: WH.teal }}
                />
              </Tooltip>
            </div>
            <div style={{ fontSize: 12, color: WH.textDim }}>
              <Text code style={{ fontSize: 11, color: WH.textMuted, background: 'rgba(255,255,255,0.06)' }}>{task.current_cron}</Text>
              {task.next_run && (
                <span style={{ marginLeft: 12, color: WH.textMuted }}>
                  ⏭ {locale === 'zh' ? '下次：' : 'Next: '}{getNextRunTime(task)}
                </span>
              )}
            </div>
          </div>

          {/* Last run */}
          {lastRun && (
            <div style={{ marginBottom: 12, fontSize: 12 }}>
              <Space size={8}>
                {lastRun.success
                  ? <CheckCircleFilled style={{ color: '#51cf66' }} />
                  : <CloseCircleFilled style={{ color: '#ff6b6b' }} />
                }
                <Text style={{ color: WH.textMuted }}>
                  {locale === 'zh' ? '上次：' : 'Last: '}
                  {formatTime(lastRun.started_at)}
                </Text>
                <Text style={{ color: WH.textDim }}>⏱ {(lastRun.elapsed_seconds ?? 0).toFixed(1)}s</Text>
                {lastRun.error && <Text style={{ color: '#ff6b6b' }}>❌</Text>}
              </Space>
            </div>
          )}

          {/* Actions */}
          <Space>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              loading={isRunning}
              onClick={() => handleRun(task.task_id)}
              disabled={!task.enabled}
            >
              {isRunning ? (locale === 'zh' ? '执行中...' : 'Running...') : (locale === 'zh' ? '立即执行' : 'Run Now')}
            </Button>
            <Button
              size="small"
              icon={<HistoryOutlined />}
              onClick={() => handleOpenHistory(task.task_id)}
              style={{ color: WH.text, borderColor: 'rgba(100,255,218,0.25)', background: 'rgba(100,255,218,0.06)' }}
            >
              {locale === 'zh' ? '历史' : 'History'}
            </Button>
          </Space>
        </Card>
      </Col>
    )
  }

  return (
    <div style={pageWrap}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0, color: WH.text }}>
            <ThunderboltOutlined style={{ marginRight: 8, color: WH.blue }} />
            {t('sync.taskManager')}
          </Title>
          <Text style={{ color: WH.textMuted }}>{t('sync.taskManagerDesc')}</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => loadTasks(true)} loading={loading} style={{ color: WH.text, borderColor: 'rgba(100,255,218,0.35)', background: 'rgba(100,255,218,0.08)' }}>
          {t('common.refresh')}
        </Button>
      </div>

      {/* Task Cards - Grouped by Rows */}
      <Spin spinning={loading}>
        {ROW_GROUPS.map((group, gi) => (
          <div key={gi} style={{ marginBottom: 24 }}>
            {/* Row title */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              marginBottom: 12,
              padding: '4px 0',
              borderBottom: '1px solid rgba(100,255,218,0.18)',
            }}>
              <div style={{
                width: 4,
                height: 18,
                borderRadius: 2,
                background: gi === 0 ? WH.blue : gi === 1 ? '#51cf66' : gi === 2 ? '#ffa94d' : '#ff6b6b',
                marginRight: 10,
              }} />
              <Text style={{ fontSize: 14, fontWeight: 600, color: WH.text }}>
                {locale === 'zh' ? group.label_zh : group.label_en}
              </Text>
            </div>
            <Row gutter={[16, 16]}>
              {group.task_ids.map(taskId => renderTaskCard(taskId))}
            </Row>
          </div>
        ))}
      </Spin>

      {/* Schedule Editor Modal */}
      <ScheduleEditor
        open={!!editTask}
        task={editTask}
        locale={locale}
        onClose={() => setEditTask(null)}
        onSave={handleSaveSchedule}
      />

      {/* History Modal */}
      <TaskHistoryModal
        open={!!historyTask}
        task={historyTask}
        locale={locale}
        onClose={() => setHistoryTask(null)}
      />
    </div>
  )
}
