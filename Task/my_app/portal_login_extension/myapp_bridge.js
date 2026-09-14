/* global chrome */

// 该 bridge 是网页与扩展之间唯一通道：网页只能交给扩展短票据，拿不到会话 Cookie。
// detail 使用 JSON 字符串而不是对象，以避免 isolated world 与页面 world 的对象包装差异。
const READY_ATTR = 'data-myapp-portal-login-extension'
const REQUEST_EVENT = 'myapp:portal-client-login'
const RESULT_EVENT = 'myapp:portal-client-login-result'

document.documentElement.setAttribute(READY_ATTR, 'ready')

function publish(result) {
  window.dispatchEvent(new CustomEvent(RESULT_EVENT, { detail: JSON.stringify(result) }))
}

window.addEventListener(REQUEST_EVENT, (event) => {
  let request
  try {
    request = JSON.parse(event.detail)
  } catch {
    publish({ ok: false, message: '门户登录请求格式无效' })
    return
  }
  chrome.runtime.sendMessage({ type: 'myapp-portal-start', request }, (result) => {
    if (chrome.runtime.lastError) {
      publish({ system: request?.system, ok: false, message: '门户登录扩展未响应，请重新加载扩展' })
      return
    }
    publish({ system: request?.system, ...(result || { ok: false, message: '门户登录扩展未返回结果' }) })
  })
})
