import { useState } from 'react'
import { Spin } from 'antd'
import { useTheme } from '../theme'
import { useI18n } from '../i18n'

/**
 * 原版工具嵌入容器（Legacy Tool Frame）
 *
 * 背景：IP 链路探测 / 事件总览 这两个工具原本是独立的 Flask 应用，页面由一份
 * 自带 Tailwind + Leaflet + 大量定制 CSS 的单文件 HTML 渲染（各 148KB / 344KB）。
 * 用 React 重写无法还原其视觉与交互，因此沿用仓库既有做法（见 WarehouseDashboard）：
 * 把原版 HTML 原样放进 public/，用同源 iframe 加载，从而 100% 保留原始效果。
 *
 * 高度策略：两份原版 HTML 都是「整页应用」布局
 *   - ip-trace.html      : <div class="flex flex-col h-screen overflow-hidden">，强依赖视口高度
 *   - incident-overview  : <body class="min-h-screen">，内容驱动但同样按整页设计
 * 因此统一让 iframe 填满 Content 可用区域，由页面内部自己滚动 —— 这与在浏览器里
 * 直接打开原版工具的观感一致，也避免了外层再套一层滚动条。
 *
 * 可用高度由 CSS 变量统一计算，避免 Header/margin/padding 改动后这里硬编码失效。
 */
const CHROME_OFFSET = 'calc(var(--wh-header-height) + var(--wh-content-margin) * 2 + var(--wh-content-padding) * 2)'

interface Props {
  /** public/ 下的 HTML 文件名，例如 'ip-trace.html' */
  file: string
  /** iframe 的无障碍标题 */
  title: string
}

export default function LegacyToolFrame({ file, title }: Props) {
  const [loading, setLoading] = useState(true)
  // 反连缓存：每次挂载都给 legacy HTML 加一个随挂载变化的查询戳，
  // 避免浏览器 / SPA 切换页面时复用旧的（可能含旧逻辑的）iframe 文档。
  // 典型症状：cxo_dashboard.html 修复后用户仍看到旧行为 —— 因为同 src 的
  // iframe 在 SPA 内导航时不会重新拉取，只有整页刷新才会。加戳后每次挂载必刷新。
  const [cacheBust] = useState(() => Date.now())
  const { isDark } = useTheme()
  const { locale } = useI18n()

  // 主题同步兜底：父页面 ThemeProvider 在 mount 时会向所有 iframe postMessage 当前主题，
  // 但 LegacyToolFrame 的挂载晚于 ThemeProvider 的 mount effect（iframe 元素此刻还不存在），
  // 导致 legacy HTML 第一次加载时错过这条 postMessage，于是只能用 localStorage / matchMedia 兜底，
  // 在某些场景下（localStorage 为空 + 系统偏好与父页面不一致）iframe 主题与父页面脱钩。
  // 在 iframe onLoad 后重发一次当前主题与语言，保证 legacy HTML 的 data-theme / 语言跟随父页面。
  const handleIframeLoad = () => {
    setLoading(false)
    const mode = isDark ? 'dark' : 'light'
    document.querySelectorAll('iframe').forEach((f) => {
      try {
        f.contentWindow?.postMessage({ __type: 'myapp-theme', mode }, '*')
        f.contentWindow?.postMessage({ __type: 'myapp-locale', locale }, '*')
      } catch (e) { /* ignore */ }
    })
  }

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: `calc(100vh - ${CHROME_OFFSET})`,
        borderRadius: 'var(--wh-radius-md)',
        overflow: 'hidden',
        background: 'var(--wh-page-bg)',
      }}
    >
      {loading && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--wh-page-bg)',
            zIndex: 1,
          }}
        >
          <Spin size="large" />
        </div>
      )}
      <iframe
        // BASE_URL 为 '/myapp/'，与 nginx 的 location /myapp/ 反代对齐；
        // iframe 内的相对请求（favicon.ico、lr-all.geo.json）会自动落到同一 base 下。
        // allowFullScreen：允许内嵌 legacy 页面（如 mw_ume_topology.html）调用
        // requestFullscreen() 进入浏览器全屏（NOC 看板的全屏按钮依赖此许可）。
        src={`${import.meta.env.BASE_URL}${file}?_=${cacheBust}`}
        title={title}
        onLoad={handleIframeLoad}
        allowFullScreen
        style={{
          width: '100%',
          height: '100%',
          border: 'none',
          display: 'block',
        }}
      />
    </div>
  )
}
