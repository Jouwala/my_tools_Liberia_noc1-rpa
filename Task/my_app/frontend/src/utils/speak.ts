// 浏览器语音播报（Web Speech API）—— 任务失败时语音通报失败内容与预计重试时间。
// 无任何第三方依赖；不支持的浏览器静默降级（返回 false，由调用方兜底提示）。

let warmed = false

function pickVoice(lang: 'zh' | 'en'): SpeechSynthesisVoice | undefined {
  if (typeof window === 'undefined' || !window.speechSynthesis) return undefined
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return undefined
  const target = lang === 'zh' ? 'zh' : 'en'
  // 优先精确匹配语言前缀（zh-CN / en-US），其次宽松包含
  return (
    voices.find(v => v.lang?.toLowerCase().startsWith(target)) ||
    voices.find(v => v.lang?.toLowerCase().includes(target))
  )
}

export function isSpeechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

/** 预热语音引擎：在用户手势（点击/切换）内调用一次，提升首播成功率。 */
export function warmSpeech(): void {
  if (!isSpeechSupported()) return
  try {
    window.speechSynthesis.getVoices()
    warmed = true
  } catch {
    /* noop */
  }
}

/**
 * 播报一段文本。lang 决定发音语言（zh-CN / en-US）。
 * 返回 true 表示已触发语音；false 表示浏览器不支持（调用方应改用文字提示）。
 */
export function speak(text: string, lang: 'zh' | 'en' = 'zh'): boolean {
  if (!isSpeechSupported()) return false
  try {
    // 取消上一条，避免多次播报排队堆积
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = lang === 'zh' ? 'zh-CN' : 'en-US'
    const v = pickVoice(lang)
    if (v) u.voice = v
    u.rate = 1
    u.pitch = 1
    warmed = true
    window.speechSynthesis.speak(u)
    return true
  } catch {
    return false
  }
}
