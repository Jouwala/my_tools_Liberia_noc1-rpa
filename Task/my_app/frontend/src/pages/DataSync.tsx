import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode } from 'react'
import {
  Card, Button, Tag, Space, List, Spin, message, Modal, Select,
  Input, Switch, Tooltip, Badge, Progress, Row, Col, Typography, Collapse, Alert,
} from 'antd'
import {
  ClockCircleOutlined,
  ThunderboltOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SettingOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  StopOutlined,
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
  MailOutlined,
  SearchOutlined,
  DownloadOutlined,
  SortAscendingOutlined,
  UnorderedListOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { useTaskStatus } from '../TaskStatusContext'
import { cachedGet, invalidateCache } from '../cache'
import { WH, cardStyle, controlCardStyle, pageWrap } from '../theme'
import { firstLine, cronToHuman, CATEGORY_CONFIG, formatTime } from './datasync/helpers'
import { ScheduleEditor } from './datasync/ScheduleEditor'
import { TaskHistoryModal } from './datasync/TaskHistoryModal'
import type { TaskInfo, TaskDetail, RunRecord, FailureCluster, FailureAgg } from './datasync/types'

const { Text, Title } = Typography

// 任务状态分类：统计模块与筛选共用同一判定，保证“数字”与“筛选结果”严格一致
export type TaskStatusKey = 'all' | 'running' | 'success' | 'failed' | 'disabled' | 'unknown'

function classifyTaskStatus(task: TaskInfo, isRunning: boolean): Exclude<TaskStatusKey, 'all'> {
  if (isRunning) return 'running'
  if (!task.enabled) return 'disabled'
  const last = task.recent_runs && task.recent_runs.length > 0 ? task.recent_runs[0] : null
  if (!last) return 'unknown'
  return last.success ? 'success' : 'failed'
}

// ===== Main Component =====
export default function DataSync() {
  const { t, locale } = useI18n()
  const { runningMap } = useTaskStatus()
  const [tasks, setTasks] = useState<TaskInfo[]>([])
  const [allTasks, setAllTasks] = useState<TaskInfo[]>([])
  const [taskDetails, setTaskDetails] = useState<Record<string, TaskDetail>>({})
  const [loading, setLoading] = useState(false)
  // 列表检索/筛选/排序/视图状态
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'failed' | 'success' | 'running' | 'disabled'>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<'name' | 'next_run' | 'status'>('name')
  // 每 30s 走一次的时钟，仅用于"下次运行"倒计时的相对时间刷新
  const [nowTs, setNowTs] = useState(Date.now())
  // 本地乐观状态：仅用于点击后到后端轮询确认"运行中"之间的过渡，最终以后端 runningMap 为准
  const [localRunning, setLocalRunning] = useState<Set<string>>(new Set())
  const startedRef = useRef<Set<string>>(new Set())
  const prevRunningRef = useRef<Record<string, boolean>>({})
  // 拉取防抖（single-flight）：上一次 /api/tasks 请求未完成时，跳过新的触发
  // （轮询 / 手动刷新 / 完成回调），避免多用户同时打开时请求堆叠
  const loadInFlightRef = useRef(false)

  // Modal states
  const [editTask, setEditTask] = useState<TaskInfo | null>(null)
  const [historyTask, setHistoryTask] = useState<TaskDetail | null>(null)
  // 失败聚合弹窗：按错误首行归并近 N 天失败，快速识别"同一根因影响多个任务"
  const [aggOpen, setAggOpen] = useState(false)
  const [aggDays, setAggDays] = useState(3)
  const [failureAgg, setFailureAgg] = useState<FailureAgg | null>(null)
  const [aggLoading, setAggLoading] = useState(false)

  // 根据搜索/筛选/排序计算展示列表
  const applyFilters = (src: TaskInfo[]): TaskInfo[] => {
    let out = src
    const kw = searchText.trim().toLowerCase()
    if (kw) {
      out = out.filter(t =>
        t.name.toLowerCase().includes(kw) ||
        (t.name_zh || '').toLowerCase().includes(kw) ||
        (t.name_en || '').toLowerCase().includes(kw) ||
        t.task_id.toLowerCase().includes(kw) ||
        (t.description || '').toLowerCase().includes(kw)
      )
    }
    if (statusFilter !== 'all') {
      out = out.filter(t => {
        const isRunning = !!(runningMap[t.task_id] || localRunning.has(t.task_id))
        return classifyTaskStatus(t, isRunning) === statusFilter
      })
    }
    if (categoryFilter !== 'all') out = out.filter(t => t.category === categoryFilter)
    const sorted = [...out]
    if (sortKey === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name))
    else if (sortKey === 'next_run') sorted.sort((a, b) => (a.next_run || '~').localeCompare(b.next_run || '~'))
    else if (sortKey === 'status') sorted.sort((a, b) => {
      const sa = (a.recent_runs?.[0]?.success ?? true) ? 1 : 0
      const sb = (b.recent_runs?.[0]?.success ?? true) ? 1 : 0
      return sa - sb
    })
    return sorted
  }

  // 筛选/排序/运行状态变化时重算展示列表
  useEffect(() => {
    setTasks(applyFilters(allTasks))
  }, [searchText, statusFilter, categoryFilter, sortKey, allTasks, runningMap, localRunning])

  const loadTasks = useCallback(async (force = false) => {
    // 防抖（single-flight）：同一时刻只允许一个在途请求，其余触发直接跳过
    if (loadInFlightRef.current) return
    loadInFlightRef.current = true
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
      setAllTasks(list)
      setTasks(applyFilters(list))
      // 由列表响应直接构建详情（recent_runs 已含最新 1 条，足够卡片展示）
      const details: Record<string, TaskDetail> = {}
      list.forEach(task => { details[task.task_id] = task as TaskDetail })
      setTaskDetails(details)
    } catch {
      message.error(t('sync.loadError'))
    } finally {
      setLoading(false)
      loadInFlightRef.current = false
    }
  }, [t, locale])

  useEffect(() => { loadTasks() }, [loadTasks])

  // 倒计时时钟：每 30s tick 一次，仅驱动"下次运行"相对时间重算，不发请求
  useEffect(() => {
    const timer = window.setInterval(() => setNowTs(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  // 实时刷新：每 60s 强制重新拉取任务列表，使失败横幅与状态卡片反映最新执行结果
  // （页面原仅在挂载/手动刷新/任务完成时拉数，长时间打开会停留在旧快照，表现为"不是实时的"）
  // 配合 loadTasks 的 single-flight 防抖，多用户同时打开也不会堆叠 /api/tasks 请求
  useEffect(() => {
    const timer = window.setInterval(() => { loadTasks(true) }, 60_000)
    return () => window.clearInterval(timer)
  }, [loadTasks])

  // 失败聚合：仅在弹窗打开时拉取，避免常驻轮询
  useEffect(() => {
    if (!aggOpen) return
    setAggLoading(true)
    api.get(`/tasks/failures?days=${aggDays}`)
      .then(res => setFailureAgg(res.data))
      .catch(() => setFailureAgg(null))
      .finally(() => setAggLoading(false))
  }, [aggOpen, aggDays])

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

  const handleStop = async (taskId: string) => {
    // 乐观清除运行标记，真实状态由后端轮询接管
    setLocalRunning(prev => { const s = new Set(prev); s.delete(taskId); return s })
    startedRef.current.delete(taskId)
    try {
      const res = await api.post(`/tasks/${taskId}/stop`)
      if (res.data.success) {
        message.success(t('sync.stopSuccess', { name: tasks.find(t2 => t2.task_id === taskId)?.name || taskId }))
        loadTasks(true)
      } else if (res.data.error) {
        message.error(res.data.error)
        // 停止失败（如任务已不在运行）时恢复乐观标记，交由轮询修正
        if (!res.data.stopped) {
          setLocalRunning(prev => new Set(prev).add(taskId))
          startedRef.current.add(taskId)
        }
      }
    } catch {
      message.error(t('sync.stopFailed', { name: taskId }))
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

  /** 距离下次运行的相对时间，如 "约 2 小时 15 分后"；解析失败返回空串。 */
  const getNextRunEta = (task: TaskInfo): string => {
    if (!task.next_run) return ''
    const ts = new Date(task.next_run).getTime()
    if (Number.isNaN(ts)) return ''
    const diffMin = Math.round((ts - nowTs) / 60000)
    if (diffMin <= 0) return locale === 'zh' ? '即将执行' : 'due now'
    if (diffMin < 60) return locale === 'zh' ? `约 ${diffMin} 分钟后` : `in ~${diffMin}m`
    const h = Math.floor(diffMin / 60)
    const m = diffMin % 60
    if (h < 24) {
      return locale === 'zh'
        ? `约 ${h} 小时${m ? ` ${m} 分` : ''}后`
        : `in ~${h}h${m ? ` ${m}m` : ''}`
    }
    const d = Math.floor(h / 24)
    return locale === 'zh' ? `约 ${d} 天后` : `in ~${d}d`
  }

  /** 5 分钟内即将执行 → 高亮提示 */
  const isImminent = (task: TaskInfo): boolean => {
    if (!task.next_run) return false
    const ts = new Date(task.next_run).getTime()
    return !Number.isNaN(ts) && ts - nowTs <= 5 * 60 * 1000
  }

  // 网关分组：按「获取数据的外部系统」动态分组（数据来自后端 task.gateway，不再硬编码 ROW_GROUPS）
  const GATEWAY_ORDER = [
    'eflow_api', 'ran_ume', 'cnn_ume', 'ipran_ume',
    'sp_sftp', 'dp_umc', 'battery_ume',
    'email', 'whatsapp', 'system',
  ]
  const GATEWAY_LABELS: Record<string, { zh: string; en: string }> = {
    eflow_api: { zh: 'ZTE eFlow API', en: 'ZTE eFlow API' },
    ran_ume: { zh: 'RAN UME', en: 'RAN UME' },
    cnn_ume: { zh: 'CNN UME', en: 'CNN UME' },
    ipran_ume: { zh: 'iPRAN UME', en: 'iPRAN UME' },
    sp_sftp: { zh: 'SP SFTP 备件', en: 'SP SFTP Spare' },
    dp_umc: { zh: 'DPtech UMC (FW)', en: 'DPtech UMC (FW)' },
    battery_ume: { zh: 'Battery UME', en: 'Battery UME' },
    email: { zh: '邮件 Email (EWS/OWA)', en: 'Email (EWS/OWA)' },
    whatsapp: { zh: 'WhatsApp', en: 'WhatsApp' },
    system: { zh: '系统 / 内部', en: 'System / Internal' },
  }
  const GATEWAY_COLORS = ['#4dabf7', '#51cf66', '#ffa94d', '#ff6b6b', '#cc5de8', '#22b8cf', '#f783ac', '#ffd43b', '#20c997', '#868e96']
  const gwLabel = (key: string): string => {
    const l = GATEWAY_LABELS[key]
    if (l) return locale === 'zh' ? l.zh : l.en
    return key
  }

  // 基于已筛选的 tasks 按 gateway 聚合（随搜索/状态/分类筛选实时联动），顺序遵循 GATEWAY_ORDER
  const groupedByGateway = useMemo(() => {
    const buckets = new Map<string, TaskInfo[]>()
    for (const t of tasks) {
      const g = t.gateway || 'system'
      if (!buckets.has(g)) buckets.set(g, [])
      buckets.get(g)!.push(t)
    }
    const ordered = GATEWAY_ORDER
      .filter(g => buckets.has(g))
      .map(g => ({ key: g, items: buckets.get(g)! }))
    const rest = [...buckets.keys()]
      .filter(g => !GATEWAY_ORDER.includes(g))
      .map(g => ({ key: g, items: buckets.get(g)! }))
    return [...ordered, ...rest]
  }, [tasks])

  // 根据 task_id 快速查找任务
  const taskMap = new Map(tasks.map(t => [t.task_id, t]))

  // 顶部汇总横幅：当前处于失败状态的任务（取各任务最新一条执行记录判断）。
  // 排除"正在运行"的任务——其可能正在重跑，既避免与"进行中"卡片重复计数，也更贴近实时。
  const failedTasks = allTasks.filter(t => {
    const isRunning = !!(runningMap[t.task_id] || localRunning.has(t.task_id))
    if (isRunning) return false
    return !!(t.recent_runs && t.recent_runs.length > 0 && !t.recent_runs[0].success)
  })

  // 各状态任务计数：统计模块与筛选共用 classifyTaskStatus，数字与筛选结果严格一致
  const statusCounts = useMemo(() => {
    const counts: Record<Exclude<TaskStatusKey, 'all'>, number> = {
      running: 0, success: 0, failed: 0, disabled: 0, unknown: 0,
    }
    allTasks.forEach(t => {
      const isRunning = !!(runningMap[t.task_id] || localRunning.has(t.task_id))
      counts[classifyTaskStatus(t, isRunning)]++
    })
    return counts
  }, [allTasks, runningMap, localRunning])

  // 状态统计卡配置：颜色 / 图标 / 文案 / 对应筛选值
  const statusMeta: {
    key: Exclude<TaskStatusKey, 'unknown'>
    color: string
    icon: ReactNode
  }[] = [
    { key: 'all', color: WH.teal, icon: <AppstoreOutlined /> },
    { key: 'running', color: WH.blue, icon: <SyncOutlined spin /> },
    { key: 'success', color: '#51cf66', icon: <CheckCircleFilled /> },
    { key: 'failed', color: '#ff6b6b', icon: <CloseCircleFilled /> },
    { key: 'disabled', color: WH.textDim, icon: <PauseCircleOutlined /> },
  ]

  const statusLabel = (key: Exclude<TaskStatusKey, 'unknown'>) => {
    if (key === 'all') return t('sync.statAll')
    if (key === 'running') return t('sync.statRunning')
    if (key === 'success') return t('sync.statSuccess')
    if (key === 'failed') return t('sync.statFailed')
    return t('sync.statDisabled')
  }

  const toggleStatusFilter = (key: Exclude<TaskStatusKey, 'unknown'>) => {
    if (key === 'all') { setStatusFilter('all'); return }
    setStatusFilter(prev => (prev === key ? 'all' : key))
  }

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
                <Tooltip
                  placement="topLeft"
                  title={
                    <div style={{ maxWidth: 380 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6, color: '#fff' }}>
                        {locale === 'zh' ? '脚本调用链' : 'Call Chain'}
                      </div>
                      {task.call_chain && task.call_chain.length > 0 ? (
                        <pre
                          style={{
                            margin: 0,
                            fontFamily: 'Consolas, Menlo, monospace',
                            fontSize: 12,
                            lineHeight: 1.6,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-all',
                            color: '#e6e6e6',
                          }}
                        >
                          {`${task.name}\n` + task.call_chain.map(c => `  ${c}`).join('\n')}
                        </pre>
                      ) : (
                        <div style={{ fontSize: 12, color: '#aaa' }}>
                          {locale === 'zh' ? '无可用信息' : 'N/A'}
                        </div>
                      )}
                    </div>
                  }
                >
                  <Text strong style={{ fontSize: 15, color: WH.text, cursor: 'help' }}>
                    {task.name}
                  </Text>
                </Tooltip>
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
                  <span style={{
                    marginLeft: 6,
                    color: isImminent(task) ? '#ffa940' : WH.textDim,
                    fontWeight: isImminent(task) ? 600 : 400,
                  }}>
                    {locale === 'zh' ? `（${getNextRunEta(task)}）` : `(${getNextRunEta(task)})`}
                  </span>
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
                {lastRun.error && (
                  <Tooltip title={lastRun.error_trace || lastRun.error}>
                    <Text
                      code
                      onClick={() => handleOpenHistory(task.task_id)}
                      style={{
                        color: '#ff8788', fontSize: 11, maxWidth: 240,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        cursor: 'pointer', background: 'rgba(255,77,79,0.1)',
                        borderColor: 'rgba(255,77,79,0.25)',
                      }}
                    >
                      ❌ {firstLine(lastRun.error)}
                    </Text>
                  </Tooltip>
                )}
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
              danger
              size="small"
              icon={<StopOutlined />}
              disabled={!isRunning}
              onClick={() => handleStop(task.task_id)}
              style={isRunning ? { color: '#ff7875', borderColor: 'rgba(255,120,117,0.4)', background: 'rgba(255,120,117,0.08)' } : undefined}
            >
              {locale === 'zh' ? '停止执行' : 'Stop'}
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

      {/* 状态统计模块：各状态任务数量 + 点击筛选 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 10, gap: 12, flexWrap: 'wrap',
        }}>
          <Text strong style={{ color: WH.text, fontSize: 14 }}>
            <BarChartOutlined style={{ marginRight: 6, color: WH.teal }} />
            {t('sync.statTitle')}
          </Text>
          <Text style={{ color: WH.textDim, fontSize: 12 }}>{t('sync.statHint')}</Text>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {statusMeta.map(({ key, color, icon }) => {
            const count = key === 'all' ? allTasks.length : statusCounts[key]
            const active = statusFilter === key
            return (
              <div
                key={key}
                role="button"
                tabIndex={0}
                onClick={() => toggleStatusFilter(key)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleStatusFilter(key) } }}
                style={{
                  flex: '1 1 140px',
                  minWidth: 120,
                  cursor: 'pointer',
                  background: active ? `${color}1f` : WH.cardBg,
                  border: `1px solid ${active ? color : 'rgba(100,255,218,0.18)'}`,
                  borderRadius: 12,
                  padding: '14px 16px',
                  transition: 'all .15s ease',
                  boxShadow: active
                    ? `0 0 0 1px ${color}, 0 6px 18px rgba(0,0,0,0.35)`
                    : '0 4px 16px rgba(0,0,0,0.25)',
                  position: 'relative',
                  outline: 'none',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ color, fontSize: 18 }}>{icon}</span>
                  {active && (
                    <Tag
                      color={color}
                      style={{ fontSize: 10, lineHeight: '16px', margin: 0, padding: '0 6px', borderRadius: 4 }}
                    >
                      {t('sync.statActive')}
                    </Tag>
                  )}
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: WH.text, lineHeight: 1 }}>
                  {count}
                </div>
                <div style={{ marginTop: 6, fontSize: 12, color: WH.textMuted }}>
                  {statusLabel(key)}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 列表检索 / 筛选 / 排序 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: WH.textDim }} />}
          placeholder={locale === 'zh' ? '搜索任务名 / ID' : 'Search name / ID'}
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{ width: 220, background: 'rgba(255,255,255,0.05)', color: WH.text, borderColor: 'rgba(100,255,218,0.18)' }}
        />
        <Select
          value={statusFilter}
          onChange={v => setStatusFilter(v)}
          style={{ width: 120 }}
          options={[
            { value: 'all', label: locale === 'zh' ? '全部状态' : 'All Status' },
            { value: 'failed', label: locale === 'zh' ? '失败' : 'Failed' },
            { value: 'success', label: locale === 'zh' ? '成功' : 'Success' },
            { value: 'running', label: locale === 'zh' ? '运行中' : 'Running' },
            { value: 'disabled', label: locale === 'zh' ? '已禁用' : 'Disabled' },
          ]}
        />
        <Select
          value={categoryFilter}
          onChange={v => setCategoryFilter(v)}
          style={{ width: 140 }}
          options={[
            { value: 'all', label: locale === 'zh' ? '全部分类' : 'All Categories' },
            ...Object.keys(CATEGORY_CONFIG).map(c => ({ value: c, label: locale === 'zh' ? CATEGORY_CONFIG[c].label_zh : CATEGORY_CONFIG[c].label_en })),
          ]}
        />
        <Select
          value={sortKey}
          onChange={v => setSortKey(v)}
          style={{ width: 130 }}
          options={[
            { value: 'name', label: locale === 'zh' ? '按名称' : 'By Name' },
            { value: 'next_run', label: locale === 'zh' ? '按下次运行' : 'By Next Run' },
            { value: 'status', label: locale === 'zh' ? '按状态' : 'By Status' },
          ]}
        />
        <Text style={{ color: WH.textDim, fontSize: 12, marginLeft: 'auto' }}>
          {locale === 'zh' ? `共 ${tasks.length} / ${allTasks.length} 个` : `${tasks.length} / ${allTasks.length}`}
        </Text>
      </div>

      {/* 失败任务汇总横幅：一眼看到当前哪些任务在持续失败，点击错误可直达历史 */}
      {failedTasks.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 20, borderColor: 'rgba(255,77,79,0.4)' }}
          action={
            <Button size="small" onClick={() => setAggOpen(true)}
              style={{ color: '#ff9c9c', borderColor: 'rgba(255,77,79,0.35)' }}>
              {locale === 'zh' ? '失败聚合' : 'Group Failures'}
            </Button>
          }
          message={
            <Text strong style={{ color: '#ff7875' }}>
              {locale === 'zh'
                ? `⚠️ ${failedTasks.length} 个任务执行失败`
                : `⚠️ ${failedTasks.length} task(s) failed`}
            </Text>
          }
          description={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
              {/* 循环变量命名为 task：用 t 会遮蔽 i18n 的 t()，导致此处无法翻译 */}
              {failedTasks.map(task => (
                <div key={task.task_id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Text style={{ color: WH.text, fontSize: 12 }}>• {task.name}</Text>
                  <Text
                    code
                    onClick={() => handleOpenHistory(task.task_id)}
                    style={{
                      color: '#ff8788', fontSize: 11, maxWidth: 360, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer',
                      background: 'rgba(255,77,79,0.1)', borderColor: 'rgba(255,77,79,0.25)',
                    }}
                  >
                    {firstLine(task.recent_runs?.[0]?.error || t('common.unknownError'))}
                  </Text>
                </div>
              ))}
            </div>
          }
        />
      )}

      {/* Task Cards - Grouped by Data Gateway */}
      <Spin spinning={loading}>
        {groupedByGateway.map((group, gi) => (
          <div key={group.key} style={{ marginBottom: 24 }}>
            {/* Group title */}
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
                background: GATEWAY_COLORS[gi % GATEWAY_COLORS.length],
                marginRight: 10,
              }} />
              <Text style={{ fontSize: 14, fontWeight: 600, color: WH.text }}>
                {gwLabel(group.key)}
              </Text>
              <Text style={{ fontSize: 12, color: WH.textMuted, marginLeft: 8 }}>
                ({group.items.length})
              </Text>
            </div>
            <Row gutter={[16, 16]}>
              {group.items.map(t => renderTaskCard(t.task_id))}
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

      {/* 失败聚合 Modal：按错误首行归并，一眼看出同一根因影响了哪些任务 */}
      <Modal
        open={aggOpen}
        onCancel={() => setAggOpen(false)}
        footer={null}
        width={760}
        title={
          <span style={{ color: WH.text }}>
            <WarningOutlined style={{ marginRight: 8, color: '#ff7875' }} />
            {locale === 'zh' ? '失败聚合' : 'Failure Clusters'}
          </span>
        }
        styles={{
          root: { background: WH.bg },
          header: { background: '#0a1929', borderBottom: '1px solid rgba(100,255,218,0.15)' },
          body: { background: WH.bg },
        }}
      >
        <Space style={{ marginBottom: 12 }} size={12}>
          <Text style={{ fontSize: 12, color: WH.textMuted }}>
            {locale === 'zh' ? '统计窗口' : 'Window'}
          </Text>
          <Select
            size="small"
            value={aggDays}
            onChange={setAggDays}
            style={{ width: 110 }}
            options={[1, 3, 7, 14].map(d => ({
              value: d, label: locale === 'zh' ? `近 ${d} 天` : `Last ${d}d`,
            }))}
          />
          {failureAgg && (
            <Text style={{ fontSize: 12, color: WH.textMuted }}>
              {locale === 'zh'
                ? `共 ${failureAgg.total_failures} 次失败 / ${failureAgg.clusters.length} 类根因`
                : `${failureAgg.total_failures} failures / ${failureAgg.clusters.length} clusters`}
            </Text>
          )}
        </Space>
        <Spin spinning={aggLoading}>
          {failureAgg && failureAgg.clusters.length > 0 ? (
            <List
              size="small"
              dataSource={failureAgg.clusters}
              renderItem={(c: FailureCluster) => (
                <List.Item style={{
                  background: 'rgba(255,77,79,0.06)', marginBottom: 8, borderRadius: 8,
                  padding: '10px 12px', border: '1px solid rgba(255,77,79,0.18)',
                }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <Text style={{ color: '#ff9c9c', fontSize: 12, fontWeight: 600, wordBreak: 'break-word' }}>
                        {c.error_first_line}
                      </Text>
                      <Tag color="red" style={{ flexShrink: 0 }}>×{c.count}</Tag>
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {Object.entries(c.tasks).map(([tid, n]) => (
                        <Tag
                          key={tid}
                          style={{ cursor: 'pointer', fontSize: 11 }}
                          onClick={() => { setAggOpen(false); handleOpenHistory(tid) }}
                        >
                          {tid} ×{n}
                        </Tag>
                      ))}
                    </div>
                    <Text style={{ fontSize: 11, color: WH.textDim }}>
                      {locale === 'zh' ? '最近一次：' : 'Last: '}{c.last_seen}
                    </Text>
                  </div>
                </List.Item>
              )}
            />
          ) : (
            !aggLoading && (
              <div style={{ textAlign: 'center', color: WH.textMuted, padding: 24 }}>
                {locale === 'zh' ? '该窗口内没有失败记录 🎉' : 'No failures in this window 🎉'}
              </div>
            )
          )}
        </Spin>
      </Modal>
    </div>
  )
}
