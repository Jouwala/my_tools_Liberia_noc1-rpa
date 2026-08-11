// DataSync 页面共享类型定义（P3#10 拆分自 DataSync.tsx）

export interface TaskInfo {
  task_id: string
  name: string
  name_zh?: string
  name_en?: string
  description: string
  category: string
  enabled: boolean
  current_cron: string
  default_cron: string
  next_run: string | null
  registered_at: string
  call_chain?: string[]
  recent_runs?: RunRecord[]
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
