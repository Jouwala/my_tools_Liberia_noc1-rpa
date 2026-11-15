import { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import api from './api'

interface TaskStatusContextType {
  /** task_id -> 是否正在运行（来自后端真实状态） */
  runningMap: Record<string, boolean>
  isRunning: (taskId: string) => boolean
}

const TaskStatusContext = createContext<TaskStatusContextType>({
  runningMap: {},
  isRunning: () => false,
})

/**
 * 在应用顶层维护任务执行状态，轮询后端 /api/tasks 的 running 字段。
 * 由于 provider 位于路由切换（switch 渲染）之上，running 状态在切换页面后依然存活。
 *
 * 轮询频率（2026-11-15 降频，写法不变只调参数）：忙时 5s、空闲 15s，各带 ±15% 抖动。
 * 起因：每个打开的 SPA 页（含大量 embed 大屏）都挂着一个本 provider，
 * 旧的「忙 2s / 闲 8s」让 /api/tasks/running 占到全站请求量的 95%
 * （2026-11-15 nginx 日志实测：6 小时 17.2 万条 ≈ 8 次/秒，全是这一路）。
 * 降频后 running 徽标的最大滞后从 2s 变 5s，对「点执行后看它转起来」足够；
 * 抖动让各标签页的轮询相位错开，不再同一秒齐射。
 */
const POLL_BUSY_MS = 5000
const POLL_IDLE_MS = 15000
/** ±15% 抖动：多标签页/多块大屏的轮询相位错开，避免同一秒齐射打满单进程后端。 */
const withJitter = (base: number) => Math.round(base * (0.85 + Math.random() * 0.3))

export function TaskStatusProvider({ children }: { children: ReactNode }) {
  const [runningMap, setRunningMap] = useState<Record<string, boolean>>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      let map: Record<string, boolean> = {}
      try {
        // 只取运行状态（约 1KB）；/tasks 会带上最新执行记录/重试预测等，约 75KB，
        // 而这里只需要一个布尔值，且是每 15s（忙时 5s，±15% 抖动）轮询一次。
        const res = await api.get('/tasks/running')
        map = res.data.running || {}
        if (!cancelled) setRunningMap(map)
      } catch {
        // 轮询失败忽略，下次继续
      } finally {
        if (!cancelled) {
          const anyRunning = Object.values(map).some(Boolean)
          // 有任务运行时轮询更频繁（5s），空闲时降低频率（15s），均带抖动
          timerRef.current = setTimeout(poll, withJitter(anyRunning ? POLL_BUSY_MS : POLL_IDLE_MS))
        }
      }
    }
    poll()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const isRunning = (taskId: string) => !!runningMap[taskId]

  return (
    <TaskStatusContext.Provider value={{ runningMap, isRunning }}>
      {children}
    </TaskStatusContext.Provider>
  )
}

export function useTaskStatus() {
  return useContext(TaskStatusContext)
}
