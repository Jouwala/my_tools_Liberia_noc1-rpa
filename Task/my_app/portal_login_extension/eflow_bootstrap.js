/* global chrome */

// eFlow 的前端不会因“仅有 Cookie”自动创建 csrftoken；该键必须是 JSON 字符串。
// 此脚本只在 eFlow 文档开始加载时运行，拿到 token 后立即从扩展 session storage 清除。
chrome.runtime.sendMessage({ type: 'myapp-eflow-bootstrap' }, (result) => {
  if (chrome.runtime.lastError || !result?.ok || typeof result.csrfToken !== 'string') return
  try {
    localStorage.setItem('csrftoken', JSON.stringify(result.csrfToken))
  } catch {
    return
  }
  chrome.runtime.sendMessage({ type: 'myapp-eflow-bootstrap-complete' })
})
