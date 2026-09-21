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
 */
export function TaskStatusProvider({ children }: { children: ReactNode }) {
  const [runningMap, setRunningMap] = useState<Record<string, boolean>>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      let map: Record<string, boolean> = {}
      try {
        // 只取运行状态（约 1KB）；/tasks 会带上最新执行记录/重试预测等，约 75KB，
        // 而这里只需要一个布尔值，且是每 8s（忙时 2s）轮询一次。
        const res = await api.get('/tasks/running')
        map = res.data.running || {}
        if (!cancelled) setRunningMap(map)
      } catch {
        // 轮询失败忽略，下次继续
      } finally {
        if (!cancelled) {
          const anyRunning = Object.values(map).some(Boolean)
          // 有任务运行时轮询更频繁（2s），空闲时降低频率（8s）
          timerRef.current = setTimeout(poll, anyRunning ? 2000 : 8000)
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
