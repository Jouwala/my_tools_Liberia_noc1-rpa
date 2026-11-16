/**
 * 页面级错误边界（2026-11-16 白屏事故的兜底）。
 *
 * 背景：这一天的 my_app 白屏事故里，`ECharts.tsx` 用 `echarts-for-react/lib/core`
 * 的默认导入被 rolldown 的 CJS 互操作解析成 module 对象，渲染时抛 React #130。
 * 由于 React 根部**没有错误边界**，一次渲染异常就把整棵树卸载 → 页面纯白、无任何
 * 文字、无任何重试入口，用户只能截图问「为什么空白」。控制台的唯一线索是一行
 * Minified React error #130。
 *
 * 本组件把「整页白」变成「一句人能看懂的话 + 刷新按钮 + 原始报错」，并且对
 * **构建产物重建导致的 chunk 加载失败**自动刷新一次（见 CHUNK_ERROR_RE）：
 * 每次 `npm run build` 后入口 HTML 的 hash 会换，停留在旧页面上的标签页再去加载
 * 已经不在的旧 chunk 就会失败；刷新一次即可拿到新入口，属于唯一正确的自愈动作。
 * 自动刷新带 20 秒窗口，避免构建真坏了时无限循环刷白。
 *
 * ⚠ 放的位置：包住 `renderPage()` 的输出，**在 Suspense 内部**。这样懒加载页面
 * 的 chunk 加载失败也能被接住（Suspense 之上的 failure 会直接冒到根）。
 * ⚠ 不要在这里吞掉错误：`componentDidCatch` 必须 `console.error` 打出原始
 * error + componentStack，排障时那是唯一证据。
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

/** 这些 message 表示「构建产物换了 / chunk 拉不下来」，刷新一次就能恢复。 */
const CHUNK_ERROR_RE =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Loading chunk \S+ failed|Unable to preload CSS/i

/** 自动刷新的去重时间窗（毫秒）：窗口内再失败就只展示错误，不再刷新。
 *  取值 5 分钟而不是几十秒，是为了「构建真坏了」时不至于每 20 秒刷一次白 ——
 *  一次刷新没救回来，就老老实实停在报错卡片上，让人看到原因并点按钮。 */
const AUTORELOAD_WINDOW_MS = 300_000
const AUTORELOAD_KEY = 'myapp-chunk-autoreload-at'

export interface PageErrorBoundaryProps {
  children: ReactNode
  /** 标题文案（由调用方传 t()，本组件不依赖 i18n 上下文） */
  title: string
  /** 说明文案，建议带「刷新重试 / 联系管理员」的指引 */
  desc: string
  /** 刷新按钮文案 */
  reloadLabel: string
}

interface PageErrorBoundaryState {
  error: Error | null
}

export default class PageErrorBoundary extends Component<
  PageErrorBoundaryProps,
  PageErrorBoundaryState
> {
  state: PageErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 唯一证据，别删：白屏时用户看到的是 UI，开发者只能从这里拿到组件栈。
    console.error('[PageErrorBoundary] 页面渲染失败：', error, info.componentStack)
    const msg = String(error?.message ?? '')
    if (!CHUNK_ERROR_RE.test(msg)) return
    try {
      const last = Number(sessionStorage.getItem(AUTORELOAD_KEY) || 0)
      if (Date.now() - last > AUTORELOAD_WINDOW_MS) {
        sessionStorage.setItem(AUTORELOAD_KEY, String(Date.now()))
        window.location.reload()
      }
    } catch {
      /* sessionStorage 不可用（隐私模式）时只是不自动刷新，不影响提示 */
    }
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    const detail = String(error.message || error.name || 'Unknown error')
    return (
      <div
        role="alert"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          maxWidth: 'min(92vw, 42rem)',
          margin: '12vh auto 0',
          padding: '1.75rem 1.5rem',
          borderRadius: 'var(--wh-radius-lg, 12px)',
          background: 'var(--wh-glass-panel, #122236)',
          border: '1px solid var(--wh-glass-border, #2a3f5a)',
          boxShadow: 'var(--wh-shadow-4, 0 10px 30px rgba(0, 0, 0, 0.35))',
        }}
      >
        <div style={{ fontSize: '1.15rem', fontWeight: 600 }}>{this.props.title}</div>
        <p style={{ margin: 0, color: 'var(--wh-text-secondary, #aab7c4)', lineHeight: 1.6 }}>
          {this.props.desc}
        </p>
        <pre
          style={{
            margin: 0,
            maxHeight: '9rem',
            overflow: 'auto',
            padding: '0.6rem 0.75rem',
            borderRadius: '6px',
            background: 'rgba(127, 127, 127, 0.12)',
            fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace',
            fontSize: '0.78rem',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {detail}
        </pre>
        <div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              cursor: 'pointer',
              padding: '0.45rem 1.1rem',
              borderRadius: '8px',
              border: '1px solid var(--wh-accent, #3b82f6)',
              background: 'var(--wh-accent, #3b82f6)',
              color: '#fff',
              fontSize: '0.9rem',
            }}
          >
            {this.props.reloadLabel}
          </button>
        </div>
      </div>
    )
  }
}
