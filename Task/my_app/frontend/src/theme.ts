// 主题设计令牌（深浅两套）
//  - WH（DOM 层）：值是 CSS 变量引用（var(--wh-*)），随 <html data-theme> 自动切换，
//    页面内联样式无需感知主题、无需重渲染。
//  - DARK / LIGHT（ECharts 层）：canvas 无法解析 CSS 变量，图表必须取具体色值，
//    由 useTheme() 按当前主题返回。
import { createContext, useContext, useEffect, useState, useCallback, ReactNode, createElement } from 'react'

export type ThemeMode = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'myapp-theme'

// ---------- 具体色值（ECharts / 程序化场景使用） ----------
export const DARK = {
  bg: 'linear-gradient(180deg, #0a1929 0%, #0d2138 100%)',
  cardBg: 'linear-gradient(145deg, #141f33 0%, #112540 100%)',
  cardBorder: '1px solid rgba(100,255,218,0.18)',
  cardBorderHover: '1px solid rgba(100,255,218,0.55)',
  teal: '#64ffda',
  blue: '#4fc3f7',
  indigo: '#7986cb',
  text: '#e6f4ff',
  textMuted: '#94a3b8',
  textDim: '#64748b',
  accentGrad: 'linear-gradient(135deg, #64ffda, #4fc3f7)',
  sev: { Critical: '#ff4757', Major: '#ff922b', Warning: '#ffd43b', Info: '#4fc3f7' } as Record<string, string>,
}

export const LIGHT = {
  bg: 'linear-gradient(180deg, #f2f7fc 0%, #e8f0f8 100%)',
  cardBg: 'linear-gradient(145deg, #ffffff 0%, #f4f9fd 100%)',
  cardBorder: '1px solid rgba(13,148,136,0.28)',
  cardBorderHover: '1px solid rgba(13,148,136,0.65)',
  teal: '#0d9488',
  blue: '#0e7490',
  indigo: '#6366f1',
  text: '#16233b',
  textMuted: '#3f5468',
  textDim: '#5b7288',
  accentGrad: 'linear-gradient(135deg, #0d9488, #0e7490)',
  sev: { Critical: '#d92d20', Major: '#ea580c', Warning: '#b45309', Info: '#0369a1' } as Record<string, string>,
}

// 系列色（图表、强调背景）：深色主题用亮色系，浅色主题用深色系保证对比度
export const WH_COLORS = [
  '#64ffda', '#4fc3f7', '#7986cb', '#ffd43b', '#ff6b6b',
  '#51cf66', '#b197fc', '#ffa94d', '#63e6be', '#5c7cfa',
]
export const LIGHT_COLORS = [
  '#0d9488', '#0e7490', '#6366f1', '#b45309', '#d92d20',
  '#15803d', '#7c3aed', '#ea580c', '#0f766e', '#1d4ed8',
]

// ---------- DOM 层：CSS 变量引用（随 data-theme 自动切换） ----------
export const WH = {
  bg: 'var(--wh-bg)',
  cardBg: 'var(--wh-card-bg)',
  cardBorder: 'var(--wh-card-border)',
  cardBorderHover: 'var(--wh-card-border-hover)',
  teal: 'var(--wh-teal)',
  blue: 'var(--wh-blue)',
  indigo: 'var(--wh-indigo)',
  text: 'var(--wh-text)',
  textMuted: 'var(--wh-text-muted)',
  textDim: 'var(--wh-text-dim)',
  accentGrad: 'var(--wh-accent-grad)',
  sev: {
    Critical: 'var(--wh-sev-critical)',
    Major: 'var(--wh-sev-major)',
    Warning: 'var(--wh-sev-warning)',
    Info: 'var(--wh-sev-info)',
  } as Record<string, string>,
  // teal 的 alpha 变体（字符串插值场景：textShadow / boxShadow 用）
  teal20: 'var(--wh-teal-20)',
  teal27: 'var(--wh-teal-27)',
  teal40: 'var(--wh-teal-40)',
  teal53: 'var(--wh-teal-53)',
}

// ECharts 主题辅助（工厂函数，避免多个图表共享同一对象被 ECharts 内部修改）
export const darkTooltip = (isDark: boolean = true) => isDark
  ? {
      backgroundColor: 'rgba(10,25,41,0.95)',
      borderColor: 'rgba(100,255,218,0.25)',
      borderWidth: 1,
      textStyle: { color: '#e6f4ff', fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.4);',
    }
  : {
      backgroundColor: 'rgba(255,255,255,0.97)',
      borderColor: 'rgba(13,148,136,0.35)',
      borderWidth: 1,
      textStyle: { color: '#16233b', fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.12);',
    }

export const axisLabel = (isDark: boolean = true) => ({ color: isDark ? '#94a3b8' : '#3f5468', fontSize: 11 })
export const axisLine = (isDark: boolean = true) => ({ lineStyle: { color: isDark ? '#22324d' : '#c8d8e8' } })
export const splitLine = (isDark: boolean = true) => ({ lineStyle: { type: 'dashed' as const, color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(13,148,136,0.12)' } })

// antd Card 通用样式（DOM 层：CSS 变量）
// 阴影取统一令牌 --wh-shadow-1，深浅主题各自定义，不再在 JS 里按主题硬编码 rgba
export const cardStyle: React.CSSProperties = {
  background: WH.cardBg,
  border: WH.cardBorder,
  borderRadius: 'var(--wh-radius-lg)',
  boxShadow: 'var(--wh-shadow-1)',
  transition: 'transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.25s ease',
}

export const controlCardStyle: React.CSSProperties = {
  ...cardStyle,
  marginBottom: 'var(--wh-space-md)',
}

// 页面包装器
export const pageWrap: React.CSSProperties = {
  background: WH.bg,
  borderRadius: 'var(--wh-radius-lg)',
  padding: 'var(--wh-space-xs)',
  minHeight: 'var(--wh-page-min-height)',
}

// ---------- 响应式辅助 ----------
// CSS 媒体查询无法写在行内 style 中，以下 hooks 供组件按断点动态调整布局
export const BREAKPOINTS = {
  xs: 0,
  sm: 576,
  md: 768,
  lg: 992,
  xl: 1200,
  xxl: 1400,
}

export type Breakpoint = keyof typeof BREAKPOINTS

/** 返回当前视口宽度（SSR 安全：默认 0） */
export function useViewportWidth(): number {
  const [width, setWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 0)
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return width
}

/** 判断当前是否小于指定断点 */
export function useBelow(bp: Breakpoint): boolean {
  const width = useViewportWidth()
  return width < BREAKPOINTS[bp]
}

/** 判断当前是否大于等于指定断点 */
export function useAbove(bp: Breakpoint): boolean {
  const width = useViewportWidth()
  return width >= BREAKPOINTS[bp]
}

/** 简化的移动端检测 */
export function useIsMobile(): boolean {
  return useBelow('md')
}

// ---------- 主题状态（Context） ----------
interface ThemeContextType {
  isDark: boolean
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextType>({ isDark: true, toggle: () => {} })

/** 跟随系统偏好（无用户显式选择时） */
function detectMode(): ThemeMode {
  const saved = localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(detectMode)
  const isDark = mode === 'dark'

  // 无用户显式选择时，跟随系统主题变化
  useEffect(() => {
    if (localStorage.getItem(THEME_STORAGE_KEY)) return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setMode(e.matches ? 'dark' : 'light')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 同步到 <html data-theme>（驱动全部 CSS 变量）
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
    // 同步主题给嵌入的 legacy HTML 工具（同源 iframe，如 Alarm Management 看板）
    try {
      document.querySelectorAll('iframe').forEach((f) => {
        f.contentWindow?.postMessage({ __type: 'myapp-theme', mode }, '*')
      })
    } catch (e) { /* ignore */ }
  }, [mode])

  const toggle = useCallback(() => {
    setMode(prev => {
      const next: ThemeMode = prev === 'dark' ? 'light' : 'dark'
      localStorage.setItem(THEME_STORAGE_KEY, next)
      return next
    })
  }, [])

  return createElement(ThemeContext.Provider, { value: { isDark, toggle } }, children)
}

export function useTheme(): { isDark: boolean; toggle: () => void; palette: typeof DARK; colors: string[] } {
  const { isDark, toggle } = useContext(ThemeContext)
  return { isDark, toggle, palette: isDark ? DARK : LIGHT, colors: isDark ? WH_COLORS : LIGHT_COLORS }
}
