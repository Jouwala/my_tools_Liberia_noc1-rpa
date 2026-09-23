/* global chrome */

// eFlow 的前端不会因“仅有 Cookie”自动创建 csrftoken；该键必须是 JSON 字符串。
// 此脚本只在 eFlow 文档开始加载时运行，拿到 token 后立即从扩展 session storage 清除。
chrome.runtime.sendMessage({ type: 'myapp-eflow-bootstrap' }, (result) => {
  if (chrome.runtime.lastError || !result?.ok || typeof result.csrfToken !== 'string') return
  try {
    // 两类读取方要的格式不同，必须都写：
    //   csrftoken      —— JSON 串（框架 store() 与 angularFm 的 CometD 都按 JSON.parse 读）
    //   forgerydefense —— 裸值（uportal 的告警语音 WebSocket 与 getCsrfValue 的 SM 场景直接取用）
    // 缺 forgerydefense 时，「当前告警」(#/_ngict-fm-currentAlarm) 会拿到 null 而整页空白，
    // 纯 REST 的工单页 (#/_troubleticket) 则不受影响。
    localStorage.setItem('csrftoken', JSON.stringify(result.csrfToken))
    localStorage.setItem('forgerydefense', result.csrfToken)
  } catch {
    return
  }
  chrome.runtime.sendMessage({ type: 'myapp-eflow-bootstrap-complete' })
})
