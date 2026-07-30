// Warehouse 暗色科技风设计令牌
// 所有页面统一引用，保证背景、卡片、文字、图表配色一致

export const WH = {
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

export const WH_COLORS = [
  '#64ffda', '#4fc3f7', '#7986cb', '#ffd43b', '#ff6b6b',
  '#51cf66', '#b197fc', '#ffa94d', '#63e6be', '#5c7cfa',
]

// ECharts 暗色主题辅助（工厂函数，避免多个图表共享同一对象被 ECharts 内部修改）
export const darkTooltip = () => ({
  backgroundColor: 'rgba(10,25,41,0.95)',
  borderColor: 'rgba(100,255,218,0.25)',
  borderWidth: 1,
  textStyle: { color: '#e6f4ff', fontSize: 12 },
  extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.4);',
})

export const axisLabel = () => ({ color: '#94a3b8', fontSize: 11 })
export const axisLine = () => ({ lineStyle: { color: '#22324d' } })
export const splitLine = () => ({ lineStyle: { type: 'dashed' as const, color: 'rgba(255,255,255,0.06)' } })

// antd Card 暗色通用样式
export const cardStyle: React.CSSProperties = {
  background: WH.cardBg,
  border: WH.cardBorder,
  borderRadius: 12,
  boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
}

export const controlCardStyle: React.CSSProperties = {
  ...cardStyle,
  marginBottom: 16,
}

// 页面包装器
export const pageWrap: React.CSSProperties = {
  background: WH.bg,
  borderRadius: 12,
  padding: 4,
  minHeight: 'calc(100vh - 110px)',
}
