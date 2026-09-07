import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode, type WheelEvent as ReactWheelEvent, type PointerEvent as ReactPointerEvent } from 'react'
import {
  Card, Button, Tag, Space, List, Spin, message, Modal, Select,
  Input, Switch, Tooltip, Badge, Progress, Row, Col, Typography, Collapse, Alert, Popconfirm,
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
  SoundOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { useTaskStatus } from '../TaskStatusContext'
import { cachedGet, invalidateCache } from '../cache'
import { speak, warmSpeech } from '../utils/speak'
import { WH, cardStyle, controlCardStyle, pageWrap } from '../theme'
import { firstLine, cronToHuman, CATEGORY_CONFIG, formatTime } from './datasync/helpers'
import { ScheduleEditor } from './datasync/ScheduleEditor'
import { TaskHistoryModal } from './datasync/TaskHistoryModal'
import { GlobalHistoryModal } from './datasync/GlobalHistoryModal'
import type { TaskInfo, TaskDetail, RunRecord, FailureCluster, FailureAgg } from './datasync/types'

const { Text, Title } = Typography

// 时间线点位使用稳定的高对比配色：同一个任务刷新后仍保持相同颜色。
const TASK_TIMELINE_COLORS = [
  '#4dabf7', '#51cf66', '#ffa94d', '#ff6b6b', '#cc5de8',
  '#22b8cf', '#f783ac', '#ffd43b', '#20c997', '#748ffc',
  '#e599f7', '#94d82d', '#ff922b', '#15aabf', '#fa5252',
]

function taskTimelineColor(taskId: string): string {
  let hash = 0
  for (let i = 0; i < taskId.length; i += 1) hash = (hash * 31 + taskId.charCodeAt(i)) | 0
  return TASK_TIMELINE_COLORS[Math.abs(hash) % TASK_TIMELINE_COLORS.length]
}

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
  // 时间线默认显示当天 00:00–24:00，也支持缩小到 12 小时或 6 小时查看密集任务。
  const [timelineHours, setTimelineHours] = useState(24)
  const [timelineStartTs, setTimelineStartTs] = useState<number | null>(null)
  const timelineDragRef = useRef<{ pointerId: number; startX: number; startTs: number } | null>(null)
  // 泳道分配按像素判断“同一时刻”，因此需要知道时间线容器的实际宽度
  const timelineBoxRef = useRef<HTMLDivElement | null>(null)
  const [timelineWidth, setTimelineWidth] = useState(800)
  const [selectedTimelineTaskId, setSelectedTimelineTaskId] = useState<string | null>(null)
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
  // 总历史记录弹窗：跨所有任务的执行历史查询
  const [ghOpen, setGhOpen] = useState(false)

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
              else {
                message.error(t('sync.runFailed', { name: id }))
                // 失败自动语音播报：用最新详情（含预测的 retry_info）播报失败内容与重试时间
                if (autoSpeakRef.current) {
                  const ok = speak(buildAnnounceText({
                    name: run.task_name || id,
                    recent_runs: res.data.recent_runs,
                    retry_info: res.data.retry_info,
                  }), locale)
                  if (!ok) message.warning(t('sync.speakUnsupported'))
                }
              }
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
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        message.error(t('sync.runForbidden'))
      } else {
        message.error(t('sync.runFailed', { name: taskId }))
      }
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

  // ===== 失败任务语音播报（Web Speech API） =====
  const [autoSpeak, setAutoSpeak] = useState<boolean>(() => {
    try { return localStorage.getItem('tm_auto_speak') === '1' } catch { return false }
  })
  const autoSpeakRef = useRef(autoSpeak)
  useEffect(() => { autoSpeakRef.current = autoSpeak }, [autoSpeak])
  const toggleAutoSpeak = (v: boolean) => {
    setAutoSpeak(v)
    try { localStorage.setItem('tm_auto_speak', v ? '1' : '0') } catch { /* noop */ }
    if (v) warmSpeech() // 用户手势内预热，提升首播成功率
  }

  // ===== 统一开关（一键启用/禁用全部任务） =====
  // pendingAllToggle 记录「待确认的目标状态」：Switch 点击时只记录意图，
  // 由 Popconfirm 确认后真正提交；取消则丢弃（Switch 受控于 allEnabled，自动回弹）
  const [pendingAllToggle, setPendingAllToggle] = useState<boolean | null>(null)
  const allEnabled = allTasks.length > 0 && allTasks.every(t => t.enabled)
  const handleToggleAll = async (enabled: boolean) => {
    try {
      const res = await api.post('/tasks/toggle-all', { enabled })
      if (res.data.success) {
        message.success(t(enabled ? 'sync.allEnabled' : 'sync.allDisabled', { count: res.data.changed }))
        loadTasks(true)
      } else {
        message.error(res.data.error || t('sync.toggleAllFailed'))
      }
    } catch {
      message.error(t('sync.toggleAllFailed'))
    } finally {
      setPendingAllToggle(null)
    }
  }

  /** 把 ISO 时间格式化为「月/日 时:分」，用于播报重试时间。 */
  const formatRetryTime = (iso: string): string => {
    try {
      const dt = new Date(iso)
      return dt.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      })
    } catch { return iso }
  }

  /** 构造失败播报文本：任务名 + 失败原因 + 预计重试时间（或无重试说明）。 */
  const buildAnnounceText = (task: { name: string; recent_runs?: RunRecord[]; retry_info?: any }): string => {
    const lastRun = task.recent_runs && task.recent_runs.length ? task.recent_runs[0] : null
    const err = firstLine(lastRun?.error || t('common.unknownError'))
    const ri = task.retry_info
    const name = task.name
    const retryPart = (() => {
      if (ri?.will_retry && ri.next_retry_at) {
        return ' ' + t('sync.speakWillRetry', { time: formatRetryTime(ri.next_retry_at) })
      }
      if (ri && (ri.attempts ?? 0) >= (ri.max_attempts ?? 2)) {
        return ' ' + t('sync.speakExhausted')
      }
      return ' ' + t('sync.speakNoRetry')
    })()
    return locale === 'zh'
      ? `${name} 执行失败。原因：${err}。${retryPart}`
      : `${name} failed. Reason: ${err}.${retryPart}`
  }

  const handleSpeak = (task: TaskInfo) => {
    warmSpeech()
    if (!speak(buildAnnounceText(task), locale)) message.warning(t('sync.speakUnsupported'))
  }

  const handleSpeakAll = () => {
    warmSpeech()
    const lines = failedTasks.map(tt => buildAnnounceText(tt))
    const text =
      (locale === 'zh' ? `共有 ${failedTasks.length} 个任务执行失败。` : `${failedTasks.length} tasks failed. `) +
      lines.join(' ')
    if (!speak(text, locale)) message.warning(t('sync.speakUnsupported'))
  }

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

  // 时间线默认以当天 00:00–24:00 展示；缩小后以当前时刻为中心，便于看清密集任务。
  const timeline = useMemo(() => {
    const dayStart = new Date(nowTs)
    dayStart.setHours(0, 0, 0, 0)
    const defaultStartTs = timelineHours === 24
      ? dayStart.getTime()
      : nowTs - (timelineHours * 60 * 60 * 1000) / 2
    const start = new Date(timelineStartTs ?? defaultStartTs)
    if (timelineStartTs === null && timelineHours !== 24) start.setMinutes(0, 0, 0)
    const end = new Date(start.getTime() + timelineHours * 60 * 60 * 1000)
    const startTs = start.getTime()
    const endTs = end.getTime()
    // 一个时间点 → 时间轴坐标。窗外仍保留 outside 标记，避免把边界误读为执行时间。
    const toPoint = (ts: number | null) =>
      ts === null || !Number.isFinite(ts)
        ? null
        : {
            ts,
            outside: ts < startTs || ts > endTs,
            percent: Math.max(0, Math.min(100, ((ts - startTs) / (endTs - startTs)) * 100)),
          }
    // 每个任务最多两个点：
    // last = 最近一次执行的实际开始时间（表达 运行中/失败/已执行）
    // next = 调度器的 next_run（表达 将要执行）
    // 单个点无法同时表达“已执行”和“将要执行”，因此拆成两点，避免被 next_run 恒为未来而全部染绿。
    const dated = allTasks
      .map((task, index) => {
        const nextTs = task.next_run ? new Date(task.next_run).getTime() : Number.NaN
        const latestRun = task.recent_runs?.[0]
        const startedTs = latestRun?.started_at ? new Date(latestRun.started_at).getTime() : Number.NaN
        return {
          task,
          index,
          parsed: Number.isFinite(nextTs) ? nextTs : null,
          last: toPoint(Number.isFinite(startedTs) ? startedTs : null),
          next: toPoint(Number.isFinite(nextTs) ? nextTs : null),
        }
      })
      .sort((a, b) => (a.parsed ?? Number.POSITIVE_INFINITY) - (b.parsed ?? Number.POSITIVE_INFINITY))

    // 同一时刻（间距小于一个点位直径）的点会互相遮挡，这里按像素冲突分配泳道，
    // 泳道以时间轴为基准上下交替展开，而不是把它们挤在同一行。
    const minGapPct = Math.max(0.4, (11 / Math.max(240, timelineWidth)) * 100)
    // 泳道数封顶，否则整点密集时容器会被撑得很高；超出后在最空的泳道里循环上下分布。
    const maxLanes = 7
    const laneFreeAt: number[] = []
    const laneOf = new Map<string, number>()
    dated
      .flatMap(item => (
        [
          { key: `${item.task.task_id}:last`, percent: item.last?.percent },
          { key: `${item.task.task_id}:next`, percent: item.next?.percent },
        ] as { key: string; percent: number | undefined }[]
      ))
      .filter(d => typeof d.percent === 'number')
      .sort((a, b) => (a.percent as number) - (b.percent as number))
      .forEach(d => {
        const percent = d.percent as number
        let lane = laneFreeAt.findIndex(free => percent >= free)
        if (lane === -1) {
          if (laneFreeAt.length < maxLanes) { lane = laneFreeAt.length; laneFreeAt.push(0) }
          else lane = laneFreeAt.reduce((best, free, i) => (free < laneFreeAt[best] ? i : best), 0)
        }
        laneFreeAt[lane] = Math.max(laneFreeAt[lane], percent) + minGapPct
        laneOf.set(d.key, lane)
      })

    return { start, end, dated, startTs, endTs, laneOf, laneCount: laneFreeAt.length }
  }, [allTasks, nowTs, timelineHours, timelineStartTs, timelineWidth])

  // 时间轴基线与容器高度随实际泳道数自适应：向上展开的泳道不能被裁掉。
  const laneGap = '0.42rem'
  const axisBox = useMemo(() => {
    const total = Math.max(1, timeline.laneCount)
    const up = Math.ceil((total - 1) / 2)
    const down = Math.floor((total - 1) / 2)
    return {
      axis: `calc(0.55rem + ${up} * ${laneGap})`,
      h: `calc(0.55rem + ${up + down} * ${laneGap} + 1.9rem)`,
    }
  }, [timeline.laneCount])

  // 泳道号 → 相对时间轴的垂直偏移：0 号压轴，其余以 ±1/±2/±3 交替上下展开。
  const laneOffset = (lane: number) => {
    const capped = Math.min(lane, 7)
    if (capped === 0) return 0
    return capped % 2 === 1 ? -Math.ceil(capped / 2) : Math.ceil(capped / 2)
  }

  // 容器宽度决定“同一时刻”的像素判定，跟随布局变化更新
  useEffect(() => {
    const el = timelineBoxRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect.width
      if (w) setTimelineWidth(prev => (Math.abs(prev - w) > 2 ? w : prev))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const handleTimelineWheel = (e: ReactWheelEvent<HTMLDivElement>) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const currentDuration = timeline.endTs - timeline.startTs
    const cursorTs = timeline.startTs + ratio * currentDuration
    const factor = e.deltaY < 0 ? 0.8 : 1.25
    const nextHours = Math.max(1, Math.min(168, timelineHours * factor))
    const nextDuration = nextHours * 60 * 60 * 1000
    setTimelineHours(nextHours)
    setTimelineStartTs(cursorTs - ratio * nextDuration)
  }

  const handleTimelinePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    timelineDragRef.current = { pointerId: e.pointerId, startX: e.clientX, startTs: timeline.startTs }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const handleTimelinePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = timelineDragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    const rect = e.currentTarget.getBoundingClientRect()
    const deltaTs = ((e.clientX - drag.startX) / rect.width) * (timeline.endTs - timeline.startTs)
    setTimelineStartTs(drag.startTs - deltaTs)
  }

  const handleTimelinePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (timelineDragRef.current?.pointerId !== e.pointerId) return
    timelineDragRef.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }

  const resetTimelineWindow = (hours: number) => {
    setTimelineHours(hours)
    setTimelineStartTs(null)
  }

  const selectedTimelineTask = selectedTimelineTaskId ? allTasks.find(task => task.task_id === selectedTimelineTaskId) : null

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
          styles={{ body: { padding: 'var(--wh-space-md) var(--wh-space-lg)' } }}
        >
          {/* Task header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--wh-space-sm)', gap: 'var(--wh-space-sm)' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <Space size={4} align="center" style={{ maxWidth: '100%' }}>
                <span style={{ fontSize: '1rem', color: catCfg.color }}>{catCfg.icon}</span>
                <Tooltip
                  placement="topLeft"
                  title={
                    <div style={{ maxWidth: 'min(80vw, 23.75rem)' }}>
                      <div style={{ fontWeight: 600, marginBottom: 'var(--wh-space-xs)', color: 'var(--wh-text)' }}>
                        {locale === 'zh' ? '脚本调用链' : 'Call Chain'}
                      </div>
                      {task.call_chain && task.call_chain.length > 0 ? (
                        <pre
                          style={{
                            margin: 0,
                            fontFamily: 'Consolas, Menlo, monospace',
                            fontSize: '0.75rem',
                            lineHeight: 1.6,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-all',
                            color: 'var(--wh-text-muted)',
                          }}
                        >
                          {`${task.name}\n` + task.call_chain.map(c => `  ${c}`).join('\n')}
                        </pre>
                      ) : (
                        <div style={{ fontSize: 12, color: 'var(--wh-text-dim)' }}>
                          {locale === 'zh' ? '无可用信息' : 'N/A'}
                        </div>
                      )}
                    </div>
                  }
                >
                  <Text strong style={{ fontSize: '0.9375rem', color: WH.text, cursor: 'help' }}>
                    {task.name}
                  </Text>
                </Tooltip>
              </Space>
              <div style={{ marginTop: 'var(--wh-space-xs)' }}>
                <Tag color={catCfg.color} style={{ fontSize: '0.6875rem' }}>{locale === 'zh' ? catCfg.label_zh : catCfg.label_en}</Tag>
                {task.enabled ? (
                  <Badge status="success" text={<Text style={{ fontSize: '0.6875rem', color: WH.textMuted }}>{locale === 'zh' ? '已启用' : 'Enabled'}</Text>} />
                ) : (
                  <Badge status="default" text={<Text style={{ fontSize: '0.6875rem', color: WH.textDim }}>{locale === 'zh' ? '已禁用' : 'Disabled'}</Text>} />
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
          <Text style={{ fontSize: '0.75rem', display: 'block', marginBottom: 'var(--wh-space-sm)', lineHeight: 1.5, color: WH.textMuted }}>
            {task.description}
          </Text>

          {/* Schedule info */}
          <div style={{
            background: 'var(--wh-subtle-bg)',
            borderRadius: 'var(--wh-radius-md)',
            padding: 'var(--wh-space-sm) var(--wh-space-md)',
            marginBottom: 'var(--wh-space-sm)',
            border: '1px solid var(--wh-subtle-border)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--wh-space-xs)', gap: 'var(--wh-space-xs)' }}>
              <Space size={4} style={{ minWidth: 0, flex: 1 }}>
                <ClockCircleOutlined style={{ color: WH.blue }} />
                <Text style={{ fontSize: '0.8125rem', color: WH.text }}>
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
            <div style={{ fontSize: '0.75rem', color: WH.textDim, display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-xs)', alignItems: 'center' }}>
              <Text code style={{ fontSize: '0.6875rem', color: WH.textMuted, background: 'var(--wh-input-bg)' }}>{task.current_cron}</Text>
              {task.next_run && (
                <span style={{ color: WH.textMuted }}>
                  ⏭ {locale === 'zh' ? '下次：' : 'Next: '}{getNextRunTime(task)}
                  <span style={{
                    marginLeft: 'var(--wh-space-xs)',
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
            <div style={{ marginBottom: 'var(--wh-space-sm)', fontSize: '0.75rem' }}>
              <Space size={8} wrap>
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
                        color: 'var(--wh-error-text)', fontSize: '0.6875rem', maxWidth: 'min(50vw, 15rem)',
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
          <Space wrap>
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
              style={isRunning ? { color: 'var(--wh-error-text)', borderColor: 'rgba(255,120,117,0.4)', background: 'rgba(255,120,117,0.08)' } : undefined}
            >
              {locale === 'zh' ? '停止执行' : 'Stop'}
            </Button>
            <Button
              size="small"
              icon={<HistoryOutlined />}
              onClick={() => handleOpenHistory(task.task_id)}
              style={{ color: WH.text, borderColor: 'var(--wh-subtle-border)', background: 'var(--wh-subtle-bg)' }}
            >
              {locale === 'zh' ? '历史' : 'History'}
            </Button>
            {lastRun && !lastRun.success && (
              <Button
                size="small"
                icon={<SoundOutlined />}
                onClick={() => handleSpeak(task)}
                style={{ color: 'var(--wh-error-text)', borderColor: 'rgba(255,120,117,0.4)', background: 'rgba(255,120,117,0.08)' }}
              >
                {t('sync.speak')}
              </Button>
            )}
          </Space>
        </Card>
      </Col>
    )
  }

  return (
    <div style={pageWrap}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--wh-space-md)', marginBottom: 'var(--wh-space-lg)' }}>
        <div>
          <Title level={4} style={{ margin: 0, color: WH.text }}>
            <ThunderboltOutlined style={{ marginRight: 'var(--wh-space-sm)', color: WH.blue }} />
            {t('sync.taskManager')}
          </Title>
          <Text style={{ color: WH.textMuted }}>{t('sync.taskManagerDesc')}</Text>
        </div>
        <Space size="small" align="center" wrap>
          <Tooltip title={locale === 'zh' ? '开启后，任务失败将自动语音播报失败内容与预计重试时间' : 'When on, task failures are auto-announced with the reason and next retry time'}>
            <Space size={6} align="center">
              <SoundOutlined style={{ color: autoSpeak ? WH.teal : WH.textDim }} />
              <Text style={{ fontSize: 12, color: WH.textMuted }}>{t('sync.autoSpeak')}</Text>
              <Switch size="small" checked={autoSpeak} onChange={toggleAutoSpeak} />
            </Space>
          </Tooltip>
          {/* 统一开关：一键启用/禁用全部任务 */}
          <Tooltip title={t('sync.toggleAllHint')}>
            <Space size={6} align="center">
              <Text style={{ fontSize: 12, color: WH.textMuted }}>{t('sync.toggleAll')}</Text>
              <Popconfirm
                title={pendingAllToggle === false ? t('sync.disableAllConfirm') : t('sync.enableAllConfirm')}
                onConfirm={() => { if (pendingAllToggle !== null) handleToggleAll(pendingAllToggle) }}
                onOpenChange={(open) => { if (!open) setPendingAllToggle(null) }}
              >
                <Switch
                  size="small"
                  checked={allEnabled}
                  disabled={allTasks.length === 0}
                  onChange={(v) => setPendingAllToggle(v)}
                />
              </Popconfirm>
            </Space>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => loadTasks(true)} loading={loading} style={{ color: WH.text, borderColor: 'var(--wh-subtle-border)', background: 'var(--wh-subtle-bg)' }}>
            {t('common.refresh')}
          </Button>
          {/* 总历史记录：跨所有任务的执行历史查询入口 */}
          <Button icon={<GlobalOutlined />} onClick={() => setGhOpen(true)} style={{ color: WH.text, borderColor: 'var(--wh-subtle-border)', background: 'var(--wh-subtle-bg)' }}>
            {t('sync.globalHistory')}
          </Button>
        </Space>
      </div>

      {/* 状态统计模块：任务时间线 + 各状态任务数量 + 点击筛选 */}
      <div style={{ marginBottom: 'var(--wh-space-md)' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 'var(--wh-space-sm)', gap: 'var(--wh-space-sm)', flexWrap: 'wrap',
        }}>
          <Text strong style={{ color: WH.text, fontSize: '0.875rem' }}>
            <ClockCircleOutlined style={{ marginRight: 'var(--wh-space-xs)', color: WH.blue }} />
            {locale === 'zh' ? '任务分布时间线' : 'Task Distribution Timeline'}
          </Text>
          <Space size={4} wrap>
            <Text style={{ color: WH.textDim, fontSize: '0.75rem', marginRight: 'var(--wh-space-xs)' }}>
              {locale === 'zh' ? '缩放：' : 'Zoom: '}
            </Text>
            {[6, 12, 24].map(hours => (
              <Button
                key={hours}
                size="small"
                type={timelineHours === hours ? 'primary' : 'default'}
                onClick={() => resetTimelineWindow(hours)}
                style={{ minWidth: '2.8rem', padding: '0 0.45rem' }}
              >
                {hours}h
              </Button>
            ))}
            <Text style={{ color: WH.textDim, fontSize: '0.75rem', marginLeft: 'var(--wh-space-xs)' }}>
              {locale === 'zh' ? '滚轮放大/缩小 · 拖动平移 · 悬浮查看 · 点击聚焦' : 'Scroll zoom · drag pan · hover details · click to focus'}
            </Text>
          </Space>
        </div>
        <div
          ref={timelineBoxRef}
          onWheel={handleTimelineWheel}
          onPointerDown={handleTimelinePointerDown}
          onPointerMove={handleTimelinePointerMove}
          onPointerUp={handleTimelinePointerUp}
          onPointerCancel={handleTimelinePointerUp}
          title={locale === 'zh' ? '滚轮缩放时间范围；按住左键拖动时间轴' : 'Scroll to zoom; drag with the left mouse button'}
          style={{
            position: 'relative', minHeight: axisBox.h, padding: '0.75rem 0.5rem 0.25rem',
            border: '1px solid var(--wh-subtle-border)', borderRadius: 'var(--wh-radius-lg)',
            background: 'var(--wh-subtle-bg)', overflow: 'hidden', touchAction: 'none', cursor: 'grab',
          }}>
          <div style={{ position: 'absolute', left: '0.75rem', right: '0.75rem', top: axisBox.axis, height: 2, background: 'var(--wh-subtle-border)' }} />
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{ position: 'absolute', left: `${i * 25}%`, top: `calc(${axisBox.axis} - 0.4rem)`, width: 1, height: '0.8rem', background: 'var(--wh-subtle-border)' }} />
          ))}
          {timeline.dated.map(({ task, index, parsed, last, next }) => {
            const isRunning = !!(runningMap[task.task_id] || localRunning.has(task.task_id))
            const latestRun = task.recent_runs?.[0]
            const failed = !isRunning && latestRun?.success === false
            // 最近执行点：实心，颜色只表达执行结果，不受 next_run 影响
            const lastColor = isRunning ? WH.blue : failed ? '#ff4d4f' : task.enabled ? '#8c8c8c' : '#000000'
            const lastLabel = isRunning ? (locale === 'zh' ? '运行中' : 'Running')
              : failed ? (locale === 'zh' ? '最近执行失败' : 'Last run failed')
              : !task.enabled ? (locale === 'zh' ? '已禁用' : 'Disabled')
              : (locale === 'zh' ? '已执行' : 'Executed')
            // 下次执行点：空心描边，表达“将要执行”
            const nextColor = !task.enabled ? '#000000' : isRunning ? WH.blue : '#b7eb8f'
            const nextLabel = !task.enabled ? (locale === 'zh' ? '已禁用（未排程）' : 'Disabled')
              : isRunning ? (locale === 'zh' ? '本次完成后再次执行' : 'Next run after this one')
              : (locale === 'zh' ? '将要执行' : 'Upcoming')
            const nextText = parsed === null
              ? (locale === 'zh' ? '未排程' : 'Not scheduled')
              : new Date(parsed).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
            const executedText = latestRun?.started_at
              ? new Date(latestRun.started_at).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
              : (locale === 'zh' ? '暂无执行记录' : 'No execution record')
            const fmt = (ts: number) => new Date(ts).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

            // 灰色（已执行）点数量最多，直径略小以免盖住时间轴与相邻点
            const sizeOf = (color: string, hollow: boolean) =>
              !hollow && color === '#8c8c8c' ? '0.5rem' : '0.7rem'
            const dots = [
              { kind: 'last', point: last, color: lastColor, label: lastLabel, hollow: false, size: sizeOf(lastColor, false) },
              { kind: 'next', point: next, color: nextColor, label: nextLabel, hollow: true, size: sizeOf(nextColor, true) },
            ].filter(d => d.point !== null) as {
              kind: string; point: { ts: number; percent: number; outside: boolean }; color: string; label: string; hollow: boolean; size: string
            }[]
            // 已禁用且没有 next_run：仍要在右端留下一个黑色点，避免任务在时间线上完全消失
            if (dots.length === 0) dots.push({ kind: 'unscheduled', point: { ts: 0, percent: 100, outside: false }, color: task.enabled ? taskTimelineColor(task.task_id) : '#000000', label: locale === 'zh' ? '未排程' : 'Not scheduled', hollow: true, size: '0.7rem' })

            return dots.map(d => (
              <Tooltip key={`${task.task_id}:${d.kind}`} placement="top" title={
                <div style={{ minWidth: '11rem' }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{task.name}</div>
                  <div style={{ color: d.color, marginBottom: 4 }}>{d.label}</div>
                  <div>{locale === 'zh' ? '最近执行：' : 'Last run: '}{executedText}</div>
                  <div>{locale === 'zh' ? '下次执行：' : 'Next run: '}{nextText}</div>
                  <div>{locale === 'zh' ? '设置：' : 'Schedule: '}{task.current_cron}</div>
                  {d.point.outside && <div style={{ color: '#ffd666' }}>{locale === 'zh' ? `该点位实际在时间窗外（${fmt(d.point.ts)}）` : `Actually outside window (${fmt(d.point.ts)})`}</div>}
                </div>
              }>
                <span
                  aria-label={`${task.name} · ${d.label}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedTimelineTaskId(prev => prev === task.task_id ? null : task.task_id)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedTimelineTaskId(prev => prev === task.task_id ? null : task.task_id) } }}
                  style={{
                    // 泳道 0 落在时间轴上，其余泳道围绕时间轴上下交替展开，
                    // 让同一时刻的多个任务分散开，而不是叠成一团。
                    position: 'absolute', left: `${d.point.percent}%`,
                    top: `calc(${axisBox.axis} + 1px + ${laneOffset((timeline.laneOf.get(`${task.task_id}:${d.kind}`) ?? 0))} * ${laneGap})`,
                    transform: 'translate(-50%, -50%)',
                    width: selectedTimelineTaskId === task.task_id ? '0.95rem' : d.size, height: selectedTimelineTaskId === task.task_id ? '0.95rem' : d.size,
                    borderRadius: '50%', boxSizing: 'border-box',
                    background: d.hollow ? 'transparent' : d.color,
                    border: d.hollow ? `2px dashed ${d.color}` : `2px solid ${WH.cardBg}`,
                    boxShadow: selectedTimelineTaskId === task.task_id ? `0 0 0 3px ${d.color}66, 0 0 14px ${d.color}` : isRunning ? `0 0 0 3px ${d.color}44, 0 0 10px ${d.color}` : `0 0 0 1px ${d.color}33`,
                    cursor: 'pointer', zIndex: 2, opacity: d.point.outside ? 0.4 : 1, filter: d.point.outside ? 'saturate(0.5)' : 'none', transition: 'all .15s ease',
                  }}
                />
              </Tooltip>
            ))
          })}
          {[0, 0.25, 0.5, 0.75, 1].map(ratio => {
            const tick = new Date(timeline.start.getTime() + ratio * (timeline.end.getTime() - timeline.start.getTime()))
            const tickLabel = tick.toLocaleTimeString(locale === 'zh' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
            return (
              <span key={ratio} style={{ position: 'absolute', left: `calc(${ratio * 100}% - ${ratio === 1 ? 1.6 : ratio === 0 ? 0 : 0.8}rem)`, bottom: '0.25rem', color: WH.textDim, fontSize: '0.6875rem' }}>
                {tickLabel}
              </span>
            )
          })}
        </div>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap',
          marginTop: 'var(--wh-space-xs)', color: WH.textDim, fontSize: '0.6875rem',
        }}>
          <span>{locale === 'zh' ? `${timeline.dated.length} 个任务` : `${timeline.dated.length} tasks`}</span>
          <Space size={10} wrap>
            <span><i style={{ display: 'inline-block', width: '0.5rem', height: '0.5rem', borderRadius: '50%', background: WH.blue, marginRight: 4 }} />{locale === 'zh' ? '运行中' : 'Running'}</span>
            <span><i style={{ display: 'inline-block', width: '0.5rem', height: '0.5rem', borderRadius: '50%', background: '#ff4d4f', marginRight: 4 }} />{locale === 'zh' ? '失败' : 'Failed'}</span>
            <span><i style={{ display: 'inline-block', width: '0.5rem', height: '0.5rem', borderRadius: '50%', background: '#8c8c8c', marginRight: 4 }} />{locale === 'zh' ? '已执行' : 'Executed'}</span>
            <span><i style={{ display: 'inline-block', width: '0.5rem', height: '0.5rem', borderRadius: '50%', border: '2px dashed #b7eb8f', marginRight: 4 }} />{locale === 'zh' ? '将要执行' : 'Upcoming'}</span>
            <span><i style={{ display: 'inline-block', width: '0.5rem', height: '0.5rem', borderRadius: '50%', background: '#000000', marginRight: 4 }} />{locale === 'zh' ? '已禁用' : 'Disabled'}</span>
            <span>{locale === 'zh' ? '实心=已发生 · 空心=计划' : 'Solid = happened · dashed = planned'}</span>
          </Space>
        </div>
        {selectedTimelineTask && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', flexWrap: 'wrap',
            padding: 'var(--wh-space-sm) var(--wh-space-md)', borderRadius: 'var(--wh-radius-md)',
            border: '1px solid rgba(77,171,247,0.45)', background: 'rgba(77,171,247,0.08)',
          }}>
            <Space size={6} wrap>
              <span style={{ width: '0.65rem', height: '0.65rem', borderRadius: '50%', background: taskTimelineColor(selectedTimelineTask.task_id), display: 'inline-block' }} />
              <Text strong style={{ color: WH.text }}>{selectedTimelineTask.name}</Text>
              <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{cronToHuman(selectedTimelineTask.current_cron, locale)}</Text>
            </Space>
            <Button size="small" onClick={() => handleOpenHistory(selectedTimelineTask.task_id)} icon={<HistoryOutlined />}>
              {locale === 'zh' ? '查看历史' : 'View history'}
            </Button>
          </div>
        )}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginTop: 'var(--wh-space-lg)', marginBottom: 'var(--wh-space-sm)', gap: 'var(--wh-space-sm)', flexWrap: 'wrap',
        }}>
          <Text strong style={{ color: WH.text, fontSize: '0.875rem' }}>
            <BarChartOutlined style={{ marginRight: 'var(--wh-space-xs)', color: WH.teal }} />
            {t('sync.statTitle')}
          </Text>
          <Text style={{ color: WH.textDim, fontSize: '0.75rem' }}>{t('sync.statHint')}</Text>
        </div>
        <div style={{ display: 'flex', gap: 'var(--wh-space-sm)', flexWrap: 'wrap' }}>
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
                  flex: '1 1 8.75rem',
                  minWidth: '7.5rem',
                  cursor: 'pointer',
                  background: active ? `${color}1f` : WH.cardBg,
                  border: `1px solid ${active ? color : 'var(--wh-subtle-border)'}`,
                  borderRadius: 'var(--wh-radius-lg)',
                  padding: 'var(--wh-space-sm) var(--wh-space-md)',
                  transition: 'all .15s ease',
                  boxShadow: active
                    ? `0 0 0 1px ${color}, 0 6px 18px rgba(0,0,0,0.35)`
                    : '0 4px 16px rgba(0,0,0,0.25)',
                  position: 'relative',
                  outline: 'none',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--wh-space-sm)' }}>
                  <span style={{ color, fontSize: '1.125rem' }}>{icon}</span>
                  {active && (
                    <Tag
                      color={color}
                      style={{ fontSize: '0.625rem', lineHeight: '1rem', margin: 0, padding: '0 var(--wh-space-xs)', borderRadius: 'var(--wh-radius-sm)' }}
                    >
                      {t('sync.statActive')}
                    </Tag>
                  )}
                </div>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: WH.text, lineHeight: 1 }}>
                  {count}
                </div>
                <div style={{ marginTop: 'var(--wh-space-xs)', fontSize: '0.75rem', color: WH.textMuted }}>
                  {statusLabel(key)}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 列表检索 / 筛选 / 排序 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: 'var(--wh-space-sm)', alignItems: 'center' }}>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: WH.textDim }} />}
          placeholder={locale === 'zh' ? '搜索任务名 / ID' : 'Search name / ID'}
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{ width: 'min(100%, 13.75rem)', background: 'var(--wh-input-bg)', color: WH.text, borderColor: 'var(--wh-input-border)' }}
        />
        <Select
          value={statusFilter}
          onChange={v => setStatusFilter(v)}
          style={{ width: 'min(100%, 7.5rem)' }}
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
          style={{ width: 'min(100%, 8.75rem)' }}
          options={[
            { value: 'all', label: locale === 'zh' ? '全部分类' : 'All Categories' },
            ...Object.keys(CATEGORY_CONFIG).map(c => ({ value: c, label: locale === 'zh' ? CATEGORY_CONFIG[c].label_zh : CATEGORY_CONFIG[c].label_en })),
          ]}
        />
        <Select
          value={sortKey}
          onChange={v => setSortKey(v)}
          style={{ width: 'min(100%, 8.125rem)' }}
          options={[
            { value: 'name', label: locale === 'zh' ? '按名称' : 'By Name' },
            { value: 'next_run', label: locale === 'zh' ? '按下次运行' : 'By Next Run' },
            { value: 'status', label: locale === 'zh' ? '按状态' : 'By Status' },
          ]}
        />
        <Text style={{ color: WH.textDim, fontSize: '0.75rem', marginLeft: 'auto' }}>
          {locale === 'zh' ? `共 ${tasks.length} / ${allTasks.length} 个` : `${tasks.length} / ${allTasks.length}`}
        </Text>
      </div>

      {/* 失败任务汇总横幅：一眼看到当前哪些任务在持续失败，点击错误可直达历史 */}
      {failedTasks.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 'var(--wh-space-lg)', borderColor: 'rgba(255,77,79,0.4)' }}
          action={
            <Space size="small" wrap>
              <Button size="small" onClick={handleSpeakAll}
                icon={<SoundOutlined />}
                style={{ color: 'var(--wh-error-text)', borderColor: 'rgba(255,77,79,0.35)' }}>
                {t('sync.speakAll')}
              </Button>
              <Button size="small" onClick={() => setAggOpen(true)}
                style={{ color: 'var(--wh-error-text)', borderColor: 'rgba(255,77,79,0.35)' }}>
                {locale === 'zh' ? '失败聚合' : 'Group Failures'}
              </Button>
            </Space>
          }
          message={
            <Text strong style={{ color: 'var(--wh-error-text)' }}>
              {locale === 'zh'
                ? `⚠️ ${failedTasks.length} 个任务执行失败`
                : `⚠️ ${failedTasks.length} task(s) failed`}
            </Text>
          }
          description={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)', marginTop: 'var(--wh-space-xs)' }}>
              {/* 循环变量命名为 task：用 t 会遮蔽 i18n 的 t()，导致此处无法翻译 */}
              {failedTasks.map(task => (
                <div key={task.task_id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)', flexWrap: 'wrap' }}>
                  <Text style={{ color: WH.text, fontSize: '0.75rem' }}>• {task.name}</Text>
                  <Text
                    code
                    onClick={() => handleOpenHistory(task.task_id)}
                    style={{
                      color: 'var(--wh-error-text)', fontSize: '0.6875rem', maxWidth: 'min(50vw, 22.5rem)', overflow: 'hidden',
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
          <div key={group.key} style={{ marginBottom: 'var(--wh-space-xl)' }}>
            {/* Group title */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              marginBottom: 'var(--wh-space-sm)',
              padding: 'var(--wh-space-xs) 0',
              borderBottom: '1px solid var(--wh-subtle-border)',
            }}>
              <div style={{
                width: '0.25rem',
                height: '1.125rem',
                borderRadius: 'var(--wh-radius-sm)',
                background: GATEWAY_COLORS[gi % GATEWAY_COLORS.length],
                marginRight: 'var(--wh-space-sm)',
              }} />
              <Text style={{ fontSize: '0.875rem', fontWeight: 600, color: WH.text }}>
                {gwLabel(group.key)}
              </Text>
              <Text style={{ fontSize: '0.75rem', color: WH.textMuted, marginLeft: 'var(--wh-space-sm)' }}>
                ({group.items.length})
              </Text>
            </div>
            <Row gutter={[{ xs: 8, sm: 12, md: 16 }, { xs: 8, sm: 12, md: 16 }]}>
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

      {/* 总历史记录 Modal（跨所有任务的执行历史查询） */}
      <GlobalHistoryModal
        open={ghOpen}
        tasks={allTasks}
        locale={locale}
        onClose={() => setGhOpen(false)}
      />

      {/* 失败聚合 Modal：按错误首行归并，一眼看出同一根因影响了哪些任务 */}
      <Modal
        open={aggOpen}
        onCancel={() => setAggOpen(false)}
        footer={null}
        width={'min(95vw, 47.5rem)' as any}
        title={
          <span style={{ color: WH.text }}>
            <WarningOutlined style={{ marginRight: 'var(--wh-space-sm)', color: 'var(--wh-error-text)' }} />
            {locale === 'zh' ? '失败聚合' : 'Failure Clusters'}
          </span>
        }
        styles={{
          root: { background: WH.bg },
          header: { background: 'var(--wh-page-bg)', borderBottom: '1px solid var(--wh-subtle-border)' },
          body: { background: WH.bg },
        }}
      >
        <Space style={{ marginBottom: 'var(--wh-space-sm)' }} size="small" wrap>
          <Text style={{ fontSize: '0.75rem', color: WH.textMuted }}>
            {locale === 'zh' ? '统计窗口' : 'Window'}
          </Text>
          <Select
            size="small"
            value={aggDays}
            onChange={setAggDays}
            style={{ width: 'min(100%, 6.875rem)' }}
            options={[1, 3, 7, 14].map(d => ({
              value: d, label: locale === 'zh' ? `近 ${d} 天` : `Last ${d}d`,
            }))}
          />
          {failureAgg && (
            <Text style={{ fontSize: '0.75rem', color: WH.textMuted }}>
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
                  background: 'rgba(255,77,79,0.06)', marginBottom: 'var(--wh-space-sm)', borderRadius: 'var(--wh-radius-md)',
                  padding: 'var(--wh-space-sm) var(--wh-space-md)', border: '1px solid rgba(255,77,79,0.18)',
                }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--wh-space-sm)' }}>
                      <Text style={{ color: 'var(--wh-error-text)', fontSize: '0.75rem', fontWeight: 600, wordBreak: 'break-word' }}>
                        {c.error_first_line}
                      </Text>
                      <Tag color="red" style={{ flexShrink: 0 }}>×{c.count}</Tag>
                    </div>
                    <div style={{ marginTop: 'var(--wh-space-xs)', display: 'flex', gap: 'var(--wh-space-xs)', flexWrap: 'wrap' }}>
                      {Object.entries(c.tasks).map(([tid, n]) => (
                        <Tag
                          key={tid}
                          style={{ cursor: 'pointer', fontSize: '0.6875rem' }}
                          onClick={() => { setAggOpen(false); handleOpenHistory(tid) }}
                        >
                          {tid} ×{n}
                        </Tag>
                      ))}
                    </div>
                    <Text style={{ fontSize: '0.6875rem', color: WH.textDim }}>
                      {locale === 'zh' ? '最近一次：' : 'Last: '}{c.last_seen}
                    </Text>
                  </div>
                </List.Item>
              )}
            />
          ) : (
            !aggLoading && (
              <div style={{ textAlign: 'center', color: WH.textMuted, padding: 'var(--wh-space-lg)' }}>
                {locale === 'zh' ? '该窗口内没有失败记录 🎉' : 'No failures in this window 🎉'}
              </div>
            )
          )}
        </Spin>
      </Modal>
    </div>
  )
}
