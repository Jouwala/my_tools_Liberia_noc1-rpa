/* global chrome */

// 这些 origin 是扩展权限和服务端计划的双重白名单。不要把网页传来的 URL
// 直接用于 fetch / tabs.create，否则桥接脚本会变成任意站点的 Cookie 写入器。
// ⚠️ 新增直连门户时，这里与 manifest.json 的 host_permissions 必须同步加，
//    否则前端会走到扩展但被 validRequest/validPlan 判为白名单外而失败。
const TARGETS = Object.freeze({
  eflow: 'https://10.100.20.8:28001',
  rais: 'https://10.100.20.9:8766',
  battery_ume: 'https://192.168.170.2:443',
})
const MYAPP_ORIGINS = new Set([
  'http://192.168.100.20',
  'https://192.168.100.20',
])
const RUN_KEY_PREFIX = 'portal-login-run:'

function fail(message) {
  throw new Error(message)
}

function validRequest(request) {
  return request &&
    typeof request.ticket === 'string' && request.ticket.length >= 32 &&
    typeof request.system === 'string' && Object.hasOwn(TARGETS, request.system) &&
    typeof request.apiOrigin === 'string' && MYAPP_ORIGINS.has(request.apiOrigin)
}

function validPlan(plan, requestedSystem) {
  if (!plan || plan.system !== requestedSystem || !Object.hasOwn(TARGETS, plan.system)) {
    return false
  }
  if (plan.origin !== TARGETS[plan.system] ||
      typeof plan.target_url !== 'string' || !plan.target_url.startsWith(`${plan.origin}/`) ||
      !Array.isArray(plan.cookies) || plan.cookies.length === 0) {
    return false
  }
  return plan.cookies.every((cookie) =>
    cookie && typeof cookie.name === 'string' && cookie.name.length > 0 &&
    typeof cookie.value === 'string' && typeof cookie.httpOnly === 'boolean')
}

async function consumeTicket(request) {
  const response = await fetch(`${request.apiOrigin}/api/portals/client-login/consume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket: request.ticket }),
    // 身份由一次性票据证明；不把 my_app 的浏览器 Cookie 交给门户页面。
    credentials: 'omit',
    cache: 'no-store',
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) fail(payload.detail || `会话服务返回 HTTP ${response.status}`)
  if (!validPlan(payload.plan, request.system)) fail('会话服务返回了不符合白名单的登录计划')
  return payload.plan
}

async function seedCookies(plan) {
  const requests = plan.cookies.map((cookie) => chrome.cookies.set({
    url: plan.origin,
    name: cookie.name,
    value: cookie.value,
    path: '/',
    secure: true,
    httpOnly: cookie.httpOnly,
  }))
  const results = await Promise.all(requests)
  if (results.some((result) => !result)) fail('Chrome 拒绝写入门户会话 Cookie')
}

async function startLogin(request) {
  if (!validRequest(request)) fail('浏览器扩展请求参数无效或 my_app 地址未在白名单中')
  const plan = await consumeTicket(request)
  await seedCookies(plan)

  // 先建立 about:blank 标签并保存本次 eFlow 的 CSRF 引导材料，再导航到门户。
  // storage.session 仅在本次 Chrome 运行期间保留，且默认不能被网页读取。
  const tab = await chrome.tabs.create({ url: 'about:blank', active: true })
  if (typeof tab.id !== 'number') fail('Chrome 未返回新建门户标签页')
  if (plan.system === 'eflow' && typeof plan.eflow_csrf_token === 'string') {
    await chrome.storage.session.set({
      [`${RUN_KEY_PREFIX}${tab.id}`]: { csrfToken: plan.eflow_csrf_token },
    })
  }
  await chrome.tabs.update(tab.id, { url: plan.target_url })
  return { system: plan.system, message: '已在本浏览器打开并登录门户' }
}

function storageRunKey(tabId) {
  return `${RUN_KEY_PREFIX}${tabId}`
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'myapp-portal-start') {
    startLogin(message.request)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, message: error instanceof Error ? error.message : '门户登录失败' }))
    return true
  }

  if (message?.type === 'myapp-eflow-bootstrap') {
    const tabId = sender.tab?.id
    if (typeof tabId !== 'number') {
      sendResponse({ ok: false })
      return undefined
    }
    chrome.storage.session.get(storageRunKey(tabId))
      .then((items) => {
        const run = items[storageRunKey(tabId)]
        sendResponse(typeof run?.csrfToken === 'string'
          ? { ok: true, csrfToken: run.csrfToken }
          : { ok: false })
      })
      .catch(() => sendResponse({ ok: false }))
    return true
  }

  if (message?.type === 'myapp-eflow-bootstrap-complete') {
    const tabId = sender.tab?.id
    if (typeof tabId === 'number') chrome.storage.session.remove(storageRunKey(tabId))
  }
  return undefined
})

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(storageRunKey(tabId))
})
