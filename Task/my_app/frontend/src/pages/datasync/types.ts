// DataSync 页面共享类型定义（P3#10 拆分自 DataSync.tsx）

export interface RetryInfo {
  will_retry: boolean
  reason: string
  next_retry_at: string | null
  attempts: number
  max_attempts: number
  attempts_left: number
  last_retry_at: string | null
  failed_at: string | null
}

export interface TaskInfo {
  task_id: string
  name: string
  name_zh?: string
  name_en?: string
  description: string
  category: string
  gateway: string
  enabled: boolean
  /** 主开关豁免：按业务长期关闭的任务，不参与「一键全部启用/禁用」与主开关状态判定
   *  （后端真相源见 backend/task_registry.py 的 MASTER_SWITCH_EXEMPT_IDS） */
  master_switch_exempt?: boolean
  /** 用户手动关闭过：主开关再次启用时会跳过它。
   *  与 enabled=false 的区别是「为什么关着」——被主开关关掉的会在主开关关闭时清零标记，
   *  而手动关的一直保留（后端真相源见 task_schedule_config.manually_stopped） */
  manually_stopped?: boolean
  current_cron: string
  default_cron: string
  next_run: string | null
  registered_at: string
  call_chain?: string[]
  recent_runs?: RunRecord[]
  retry_info?: RetryInfo
}

export interface TaskDetail extends TaskInfo {
  recent_runs: RunRecord[]
}

export interface RunRecord {
  task_id: string
  task_name: string
  category: string
  trigger: string
  success: boolean
  started_at: string
  completed_at: string
  elapsed_seconds: number
  result_json?: string | null
  error: string | null
  error_trace?: string | null
}

// 失败聚合（GET /api/tasks/failures）：按错误首行归并，识别跨任务的同一根因
export interface FailureCluster {
  error_first_line: string
  count: number
  tasks: Record<string, number>
  last_seen: string
}

export interface FailureAgg {
  days: number
  total_failures: number
  clusters: FailureCluster[]
}
