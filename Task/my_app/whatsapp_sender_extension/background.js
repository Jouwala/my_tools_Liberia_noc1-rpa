// WhatsApp Image Sender - background service worker
//
// 定时发送的时间设置与 my_app sync 页面（/myapp/?page=sync）的任务调度格式一致：
// 5 段式 cron 表达式（分 时 日 月 周），例如 "0 8 * * *" = 每天 8 点。
//
// 运行模型：
//   1) chrome.alarms 每 1 分钟 tick 一次；
//   2) 当前时刻匹配配置的 cron 时触发「定时发送」：
//      - 若后端恰有待发作业（任务 whatsapp_send_ext 投递）则认领并发送、回报结果；
//      - 否则直接从 outbox 拉图发送（2 分钟内刚成功发送过则跳过，防双发）；
//   3) 其余分钟仍会认领后端的待发作业，保证后端任务手动/定时触发都能及时送达。
//
// 跨域取数只能在 SW 完成（content script 受 CORS 限制；SW 凭 host_permissions 绕过）。
// 合规边界：仅操作用户已登录的 WhatsApp Web 会话；图片来源是用户本机 my_app 后端。

const DEFAULTS = {
  server_url: "http://localhost",
  cron: "0 3 * * *", // 与后端任务 whatsapp_send_ext 的 default_cron 一致
  enabled: true,
};
const CFG_KEY = "wa_sender_config";
const LAST_RUN_KEY = "wa_sender_last_run";
const LAST_FIRE_KEY = "wa_sender_last_fire";
const TICK_ALARM = "wa-ext-tick";
const KEEPALIVE_ALARM = "wa-ext-keepalive";
// 定时触发前的去重窗口：窗口内已有成功发送则跳过直发（避免与作业认领双发）
const DEDUP_WINDOW_MS = 120 * 1000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 工具 ----------
function bufToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function normalizeBaseUrl(url) {
  return String(url || DEFAULTS.server_url).replace(/\/+$/, "");
}

async function getConfig() {
  const data = await chrome.storage.local.get(CFG_KEY);
  const cfg = { ...DEFAULTS, ...(data[CFG_KEY] || {}) };
  if (!cfg.cron || !String(cfg.cron).trim()) cfg.cron = DEFAULTS.cron;
  return cfg;
}

async function saveConfig(cfg) {
  await chrome.storage.local.set({ [CFG_KEY]: cfg });
  await syncAlarms(cfg);
}

function broadcast(payload) {
  chrome.runtime.sendMessage(payload).catch(() => {});
}

async function setBadge(text, color) {
  try {
    await chrome.action.setBadgeText({ text });
    if (color) await chrome.action.setBadgeBackgroundColor({ color });
  } catch (e) { /* action 不可用时忽略 */ }
}

async function writeLastRun(run) {
  const runWithFinish = { ...run, finished_at: new Date().toISOString() };
  await chrome.storage.local.set({ [LAST_RUN_KEY]: runWithFinish });
  broadcast({ type: "sidepanel:lastRun", data: runWithFinish });
}

async function apiFetch(cfg, path, opts) {
  const res = await fetch(normalizeBaseUrl(cfg.server_url) + path, opts);
  return res;
}

// ---------- cron（与 sync 页面同格式：分 时 日 月 周） ----------
function parseCronField(field, min, max) {
  const allowed = new Set();
  for (const raw of String(field).split(",")) {
    const part = raw.trim();
    if (!part) return null;
    const [rangeStr, stepStr] = part.split("/");
    const step = stepStr === undefined ? 1 : Number(stepStr);
    if (!Number.isFinite(step) || step < 1) return null;
    let lo, hi;
    if (rangeStr === "*") {
      lo = min; hi = max;
    } else if (rangeStr.includes("-")) {
      const [a, b] = rangeStr.split("-");
      lo = Number(a); hi = Number(b);
    } else {
      lo = hi = Number(rangeStr);
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
    for (let v = lo; v <= hi; v += step) {
      if (v >= min && v <= max) allowed.add(v);
    }
  }
  return allowed.size ? allowed : null;
}

function cronMatchesNow(expr, now) {
  const parts = String(expr || "").trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const [minF, hrF, dayF, monF, dowF] = parts;
  const minSet = parseCronField(minF, 0, 59);
  const hrSet = parseCronField(hrF, 0, 23);
  const daySet = parseCronField(dayF, 1, 31);
  const monSet = parseCronField(monF, 1, 12);
  const dowSet = parseCronField(dowF, 0, 7); // cron 中 0/7 均为周日
  if (!minSet || !hrSet || !daySet || !monSet || !dowSet) return false;
  if (dowSet.has(7)) dowSet.add(0);
  const d = now || new Date();
  return minSet.has(d.getMinutes())
    && hrSet.has(d.getHours())
    && daySet.has(d.getDate())
    && monSet.has(d.getMonth() + 1)
    && dowSet.has(d.getDay());
}

function minuteKey(now) {
  const d = now || new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}`;
}

// ---------- 定时器 ----------
// 幂等：已存在的 alarm 不重建。SW 每分钟都会被 KEEPALIVE 唤醒并执行顶层
// syncAlarms，若每次都 create 会把下一次触发不断往后推 1 分钟，tick 精度受损。
async function syncAlarms(cfg) {
  const existing = new Set((await chrome.alarms.getAll()).map((a) => a.name));
  if (!existing.has(KEEPALIVE_ALARM)) {
    await chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 1 });
  }
  if (cfg.enabled) {
    if (!existing.has(TICK_ALARM)) {
      await chrome.alarms.create(TICK_ALARM, { periodInMinutes: 1 });
    }
  } else {
    await chrome.alarms.clear(TICK_ALARM);
  }
}

// 必须 async + await：MV3 中 listener 返回的 Promise 才算「事件未结束」，
// 否则 Chrome 认为 alarm 事件已处理完，~30s 后杀掉 SW，发送中途失联、
// 结果回报丢失（2026-08-31 实测：认领作业后 300s 无回执）。
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === KEEPALIVE_ALARM) {
    chrome.runtime.getPlatformInfo(() => {});
    return;
  }
  if (alarm.name === TICK_ALARM) {
    try {
      await tick();
    } catch (e) {
      console.warn("[wa-sender] tick failed", e);
    }
  }
});

// 每分钟：命中 cron 触发定时发送；未命中时仍认领后端作业（如有）
async function tick() {
  const cfg = await getConfig();
  if (!cfg.enabled) return;
  if (running) return;

  if (cronMatchesNow(cfg.cron, new Date())) {
    const data = await chrome.storage.local.get(LAST_FIRE_KEY);
    const key = minuteKey();
    if (data[LAST_FIRE_KEY] === key) return; // 同一分钟只触发一次（alarm 可能重复唤醒）
    await chrome.storage.local.set({ [LAST_FIRE_KEY]: key });
    await runScheduled(cfg);
    return;
  }
  await claimAndRunJob(cfg, "job");
}

// ---------- 发送核心 ----------
let running = false;

async function fetchImageBytes(cfg, item) {
  const res = await apiFetch(cfg, item.url);
  if (!res.ok) throw new Error(`图片 ${item.name} 返回 ${res.status}`);
  return bufToBase64(await res.arrayBuffer());
}

async function findWhatsAppTab() {
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  return tabs.length ? tabs[0] : null;
}

// 发送前保证存在 WhatsApp Web 标签页；仅发送流程使用，诊断/清理操作仍保持只读。
async function ensureWhatsAppTab() {
  const existing = await findWhatsAppTab();
  if (existing) return { tab: existing, created: false };
  // 没有现成页面时始终使用独立窗口，避免把用户当前窗口切换到 WhatsApp。
  // 浏览器完全没有窗口时，windows.create 同样会启动一个新窗口。
  const win = await chrome.windows.create({
    url: "https://web.whatsapp.com/",
    type: "popup",
    focused: true,
    state: "normal",
    width: 1100,
    height: 850,
  });
  const tab = win && win.tabs && win.tabs[0];
  if (!tab || tab.id === undefined) throw new Error("无法打开 WhatsApp Web 标签页");
  // 等待文档完成加载，再交给发送引擎等待 WhatsApp 自身 UI 出现。
  for (let i = 0; i < 60; i++) {
    try {
      const current = await chrome.tabs.get(tab.id);
      if (current.status === "complete") return { tab: current, created: true };
    } catch (e) { /* 标签页仍在创建 */ }
    await sleep(500);
  }
  return { tab, created: true };
}

async function restoreAfterSend(ctx) {
  if (!ctx) return;
  try {
    if (ctx.created) {
      // 自动创建的 WhatsApp 窗口保留登录状态，但发送结束后最小化。
      await chrome.windows.update(ctx.windowId, { state: "minimized" });
    } else {
      if (ctx.activeTabId !== undefined) {
        await chrome.tabs.update(ctx.activeTabId, { active: true });
      }
      await chrome.windows.update(ctx.windowId, { state: ctx.windowState });
    }
    if (ctx.previousFocusedWindowId !== undefined && !ctx.previousFocusedWindowIsWhatsApp) {
      await chrome.windows.update(ctx.previousFocusedWindowId, { focused: true });
    }
  } catch (e) { /* 恢复窗口失败不影响发送结果 */ }
}

// groups + items → 逐群逐图发送；返回 { ok, groups_sent, errors, elapsed_seconds }
// jobId：后端作业号（直发 outbox 时为 null），随消息传给 content，
// content 完成后可凭它直接向 SW 回报（兜底本 SW 中途被杀的场景）
async function performSend(cfg, groups, items, label, jobId) {
  const startedAt = Date.now();
  const out = { ok: false, groups_sent: [], errors: [], elapsed_seconds: 0 };
  await setBadge("…", "#888888");
  broadcast({ type: "sidepanel:progress", phase: "fetch-images", label, count: items.length });

  if (!groups.length) out.errors.push("未配置群组");
  if (!items.length) out.errors.push("无可发送图片");
  if (!groups.length || !items.length) return finish(out, startedAt);

  // 没有打开 WhatsApp Web 时自动新建标签页；图片下载仍在确认页面后进行。
  let tab;
  let windowCtx;
  try {
    const windowsBefore = await chrome.windows.getAll();
    const previousFocused = windowsBefore.find((w) => w.focused);
    const ensured = await ensureWhatsAppTab();
    tab = ensured.tab;
    const currentWindow = await chrome.windows.get(tab.windowId);
    const activeTabs = await chrome.tabs.query({ windowId: tab.windowId, active: true });
    windowCtx = {
      created: ensured.created,
      windowId: tab.windowId,
      windowState: currentWindow.state || "normal",
      activeTabId: activeTabs[0] && activeTabs[0].id,
      previousFocusedWindowId: previousFocused && previousFocused.id,
      previousFocusedWindowIsWhatsApp: !!(previousFocused && previousFocused.id === tab.windowId),
    };
  } catch (e) {
    out.errors.push(`无法打开 WhatsApp Web：${e.message || e}`);
    return finish(out, startedAt);
  }

  const images = [];
  for (const item of items) {
    try {
      images.push({
        name: item.name, mime: item.mime, caption: item.caption,
        dataBase64: await fetchImageBytes(cfg, item),
      });
    } catch (e) {
      out.errors.push(`取图失败 ${item.name}: ${e.message}`);
    }
  }
  if (!images.length) {
    await restoreAfterSend(windowCtx);
    return finish(out, startedAt);
  }

  // 标签页后台/被丢弃时的可靠性：发送前主动激活页签。
  // - 普通后台页签：激活后不再受隐藏节流影响，行为与前台一致；
  // - 被内存节省器丢弃（discarded）的页签：激活即重新加载页面，
  //   需要等脚本注入与 WhatsApp Web 自身加载完成，用 wa:ping 探活。
  // 注意：这只是「尽力而为」的优化，不是发送前提——content 侧的等待已改为
  // 经由本 SW 代等（见 wa:sleep），即使激活失败（锁屏/遮挡/最小化）也能照常发送。
  if (tab.discarded || !tab.active) {
    try { await chrome.tabs.update(tab.id, { active: true }); } catch (e) { /* 窗口状态异常时忽略 */ }
    await sleep(1500);
  }
  // 仅激活页签不够：窗口最小化/失焦时文档仍是 hidden，execCommand 输入会失效。
  // 把窗口恢复为 normal 并聚焦，保证页面真正可见可输入（定时发送时短暂抢占焦点是预期行为）。
  // 同样只是优化而非前提：失败的兜底在 content 侧（execCommand 空转时退化为
  // textContent + input 事件），且等待不再依赖页面定时器。
  try {
    const win = await chrome.windows.get(tab.windowId);
    if (win.state === "minimized") {
      await chrome.windows.update(tab.windowId, { state: "normal" });
      await sleep(800);
    }
    if (!win.focused || win.state === "minimized") {
      await chrome.windows.update(tab.windowId, { focused: true });
      await sleep(500);
    }
  } catch (e) { /* 窗口 API 异常不阻断发送，探活步骤仍会兜底 */ }
  try {
    broadcast({ type: "sidepanel:progress", phase: "sending", groups, images: images.length });

    // 唯一发送路径：debugger/CDP 可信事件（现版 WhatsApp Web 无视 content 合成事件）。
    let resp = null;
    try {
      resp = await simpleSendViaDebugger(tab.id, groups, images);
    } catch (e) {
      out.errors.push(`无法安全控制 WhatsApp 页面：${e.message || e}。请关闭该标签页 DevTools 后重试`);
      return finish(out, startedAt);
    }

    if (resp && resp.ok !== undefined) {
      out.ok = !!resp.ok;
      out.groups_sent = resp.groups_sent || [];
      out.errors.push(...(resp.errors || []));
    } else {
      out.errors.push((resp && resp.error) || "发送失败（无回执）");
    }
    return finish(out, startedAt);
  } finally {
    await restoreAfterSend(windowCtx);
  }
}

async function finish(out, startedAt) {
  out.elapsed_seconds = Math.round((Date.now() - startedAt) / 1000);
  await setBadge(out.ok ? "✓" : "!", out.ok ? "#2e7d32" : "#c62828");
  return out;
}

// ---------- Debugger (CDP) 发送：与 Playwright 等价的可信事件 ----------
// 实测结论（2026-09-01）：现版 WhatsApp Web 无视 content script 的合成事件
// （change/paste/drop 四路全灭），只有「可信事件」能触发其处理逻辑。
// 因此发送主路径改为 chrome.debugger 连到标签页执行 CDP。
// DOM 实测（页面诊断）：合成器 footer 里恰好有 1 个隐藏的
// input[type="file"][accept="image/*"]，聊天输入框 aria 内嵌群名。据此定序：
//   1) 临时文件下载 + DOM.setFileInputFiles 直接注入该 input（= Playwright set_input_files）
//   2) 兜底：图片写入系统剪贴板 + 可信 Ctrl+V
//   3) 粘贴备注、仅在预览备注框上发送可信 Enter
// 预览是否弹出用「可编辑框注入前后差异」判定，不再猜 aria 文案。
// debugger 不可用时（DevTools 占用 / 策略限制）直接报错，不执行旧 content 路径。
function dbgCommand(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params || {}, (result) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message)); else resolve(result || {});
    });
  });
}

function dbgAttach(tabId) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message)); else resolve();
    });
  });
}

function dbgDetach(tabId) {
  return new Promise((resolve) => {
    try {
      chrome.debugger.detach({ tabId }, () => { void chrome.runtime.lastError; resolve(); });
    } catch (e) { resolve(); }
  });
}

async function dbgEval(tabId, expression, awaitPromise = false) {
  const res = await dbgCommand(tabId, "Runtime.evaluate", { expression, returnByValue: true, awaitPromise });
  if (res.exceptionDetails) {
    const d = res.exceptionDetails.exception && res.exceptionDetails.exception.description;
    throw new Error(d || res.exceptionDetails.text || "页面内求值失败");
  }
  return res.result ? res.result.value : undefined;
}

const CDP_HELPERS = `(() => {
  const visible = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && el.offsetParent !== null; };
  const SEND_SELS = [
    '[data-testid="send"]', '[data-testid="send-btn"]', 'button[aria-label="Send"]',
    'button[aria-label="发送"]', 'button[aria-label*="Send" i]', '[data-icon="send"]',
    'span[data-icon="send"]', 'button[data-icon="send"]'
  ];
  const CHAT_COMPOSER_ARIA = /输入(?:要向|消息)|Type a message|send a message/i;
  const CAPTION_ARIA = /caption|说明|小标题|描述|media-composer|media editor/i;
  const firstVisible = (sels) => { for (const sel of sels) { try { for (const el of document.querySelectorAll(sel)) { if (visible(el)) return el; } } catch (e) {} } return null; };
  const center = (el) => { const b = el.getBoundingClientRect(); return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) }; };
  const editables = () => [...document.querySelectorAll('[contenteditable="true"]')];
  const ariaOf = (el) => el.getAttribute('aria-label') || '';
  // 中心坐标安全校验：先 elementFromPoint 确认该点确实命中元素本身（或其子元素）
  // 才返回坐标。防止匹配到错误元素/被浮层遮挡时，可信点击落头部通话按钮等位置。
  const safeCenter = (el) => {
    const c = center(el);
    let at = null;
    try { at = document.elementFromPoint(c.x, c.y); } catch (e) { return null; }
    return at && (at === el || el.contains(at)) ? c : null;
  };
  window.__waExt = {
    // 聊天输入框：只接受 aria 明确指向消息输入的元素；不再使用宽泛的
    // #main div[contenteditable]，避免把页内搜索/头部可编辑元素当成聊天输入框。
    chatComposer() {
      for (const el of editables()) {
        if (!visible(el)) continue;
        const inFooter = !!el.closest('#main footer, #footer');
        if (!inFooter && !CHAT_COMPOSER_ARIA.test(ariaOf(el))) continue;
        if (el.getBoundingClientRect().top < window.innerHeight * 0.35) continue;
        return el;
      }
      return null;
    },
    // 聚焦聊天输入框：eval focus + activeElement 校验，全程零鼠标事件。
    focusChatComposer() {
      const el = this.chatComposer();
      if (!el) return false;
      el.focus();
      return document.activeElement === el;
    },
    countOutgoing() { const m = document.querySelector('#main'); return m ? m.querySelectorAll('div[data-id^="true_"]').length : 0; },
    fileInputPick() {
      const list = [...document.querySelectorAll('input[type="file"]')];
      if (!list.length) return null;
      return list.find((i) => (i.getAttribute('accept') || '').toLowerCase().includes('image')) || list[list.length - 1];
    },
    searchBox() {
      const sels = ['#side input[type="search"]', '#side input[role="textbox"]', '#side input', '#side div[contenteditable="true"]', '#side [role="textbox"]'];
      for (const sel of sels) {
        let el = null;
        try { el = document.querySelector(sel); } catch (e) { continue; }
        if (el && visible(el)) return el;
      }
      return null;
    },
    // 聚焦搜索框：eval focus + activeElement 校验（不点击）
    focusSearch() {
      const el = this.searchBox();
      if (!el) return false;
      el.focus();
      return document.activeElement === el;
    },
    searchFocused() {
      const el = this.searchBox();
      return !!(el && document.activeElement === el);
    },
    // 仅当 elementFromPoint 验证命中时才给出可点击坐标（focus() 无效时的兜底）
    searchFocusSafeXY() { const el = this.searchBox(); return el ? safeCenter(el) : null; },
    searchText() {
      const el = this.searchBox();
      if (!el) return '';
      return el.tagName === 'INPUT' ? (el.value || '') : (el.textContent || '');
    },
    // 搜索结果：只有验证命中的条目坐标才返回，防误点别处
    searchResultXY(name) {
      const roots = ['#pane-side', '#side'];
      const search = this.searchBox();
      const isSearch = (el) => !!(search && (el === search || search.contains(el)));
      const sels = [
        '[role="listitem"]', '[role="option"]', '[role="row"]', 'li',
        '[data-testid*="cell"]', '[data-testid*="conversation"]',
        '[data-testid*="list-item"]', '[tabindex="-1"]'
      ];
      const seen = new Set();
      const candidates = [];
      const exact = [];
      for (const root of roots) {
        for (const el of [...document.querySelectorAll(root + ' *')]) {
          if (!isSearch(el) && visible(el) && (el.textContent || '').trim() === name) exact.push(el);
        }
        for (const sel of sels) {
          let cands = [];
          try { cands = [...document.querySelectorAll(root + ' ' + sel)]; } catch (e) { continue; }
          for (const el of cands) {
            if (seen.has(el) || isSearch(el) || !visible(el) || !(el.textContent || '').includes(name)) continue;
            seen.add(el);
            candidates.push(el);
          }
        }
      }
      exact.sort((a, b) => {
        const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
        return (ar.width * ar.height) - (br.width * br.height);
      });
      for (const el of exact) {
        const c = safeCenter(el);
        if (c) return c;
      }
      // Prefer the smallest matching row; clicking a large panel/container can
      // hit an unrelated header control when WhatsApp's layout changes.
      candidates.sort((a, b) => (a.textContent || '').trim().length - (b.textContent || '').trim().length);
      for (const el of candidates) {
        const c = safeCenter(el);
        if (c) return c;
      }
      // 某些版本不给筛选结果行设置稳定 role/testid，退化到紧凑的可点击祖先。
      const loose = [];
      for (const root of roots) {
        for (const el of [...document.querySelectorAll(root + ' *')]) {
          if (isSearch(el) || !visible(el) || !(el.textContent || '').trim().includes(name)) continue;
          const clickable = el.closest('[role="button"], [role="listitem"], [role="option"], [role="row"], li, [tabindex="-1"], [data-testid*="cell"]');
          if (!clickable || !visible(clickable) || (clickable.textContent || '').trim().length > 500) continue;
          loose.push(clickable);
        }
      }
      loose.sort((a, b) => (a.textContent || '').trim().length - (b.textContent || '').trim().length);
      for (const el of loose) {
        const c = safeCenter(el);
        if (c) return c;
      }
      // 最后使用结果名称本身的可见节点。部分新版只给头像/文字容器绑定事件，
      // 没有 role、tabindex 或 data-testid；点击文字节点仍属于明确的结果命中。
      const textNodes = [];
      for (const root of roots) {
        for (const el of [...document.querySelectorAll(root + ' *')]) {
          const text = (el.textContent || '').trim();
          if (isSearch(el) || !visible(el) || !text.includes(name) || text.length > 160) continue;
          const r = el.getBoundingClientRect();
          if (r.width > 420 || r.height > 100) continue;
          textNodes.push(el);
        }
      }
      textNodes.sort((a, b) => (a.textContent || '').trim().length - (b.textContent || '').trim().length);
      for (const el of textNodes) {
        const c = safeCenter(el);
        if (c) return c;
      }
      return null;
    },
    // 直接调用已确认结果节点的 click()，避免 CDP 坐标换算/浮层遮挡时误点通话按钮。
    // click 事件会冒泡到 WhatsApp 的结果行，但不会触发鼠标坐标事件。
    clickSearchResult(name) {
      const roots = ['#pane-side', '#side'];
      const search = this.searchBox();
      const isSearch = (el) => !!(search && (el === search || search.contains(el)));
      const exact = [];
      for (const root of roots) {
        for (const el of [...document.querySelectorAll(root + ' *')]) {
          if (!isSearch(el) && visible(el) && (el.textContent || '').trim() === name) exact.push(el);
        }
      }
      exact.sort((a, b) => {
        const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
        return (ar.width * ar.height) - (br.width * br.height);
      });
      // 只点击精确群名节点。不要把包含群名的父容器、搜索框或其它按钮
      // 当成结果；模糊点击曾导致页面落入“选择聊天/通话”界面。
      for (const el of exact) {
        try { el.click(); return true; } catch (e) {}
      }
      return false;
    },
    // 注入图片前所有可编辑框 aria 的计数快照（基线）
    snapshotEditables() {
      const m = {};
      for (const el of editables()) { const a = ariaOf(el); m[a] = (m[a] || 0) + 1; }
      return m;
    },
    // 预览备注框：先认显式 caption aria；否则取相对基线新出现的可编辑框（排除聊天输入框）
    previewComposer(baseline) {
      const seen = baseline || {};
      const counts = {};
      let fresh = null;
      for (const el of editables()) {
        const a = ariaOf(el);
        counts[a] = (counts[a] || 0) + 1;
        if (!visible(el) || CHAT_COMPOSER_ARIA.test(a)) continue;
        if (CAPTION_ARIA.test(a)) return el;
        if (!fresh && counts[a] > (seen[a] || 0)) fresh = el;
      }
      return fresh;
    },
    previewFound(baseline) { return !!this.previewComposer(baseline); },
    // 聚焦预览备注框：focus 后校验 activeElement，校验不过就如实返回 false
    focusPreview(baseline) {
      const el = this.previewComposer(baseline);
      if (!el) return false;
      el.focus();
      return document.activeElement === el;
    },
    previewText(baseline) { const el = this.previewComposer(baseline); return el ? (el.textContent || '') : ''; },
    // 会话核验：聊天输入框 aria 内嵌群名（实测「输入要向群组"X"发送的消息」），兜底 #main 头部文本
    chatMatches(name) {
      for (const el of editables()) {
        const a = ariaOf(el);
        if (CHAT_COMPOSER_ARIA.test(a) && a.includes(name)) return true;
      }
      const m = document.querySelector('#main');
      return !!(m && (m.textContent || '').slice(0, 800).includes(name));
    },
    chatReady(name) {
      return this.chatMatches(name) && !!this.chatComposer();
    }
  };
  return true;
})()`;

async function cdpKey(tabId, opts) {
  await dbgCommand(tabId, "Input.dispatchKeyEvent", opts);
}

async function cdpPasteKey(tabId) {
  const base = { key: "v", code: "KeyV", windowsVirtualKeyCode: 86, nativeVirtualKeyCode: 86, modifiers: 2 };
  await cdpKey(tabId, { type: "keyDown", ...base });
  await cdpKey(tabId, { type: "keyUp", ...base });
}

async function cdpEnterKey(tabId) {
  const base = { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await cdpKey(tabId, { type: "keyDown", ...base });
  await cdpKey(tabId, { type: "keyUp", ...base });
}

async function cdpEscapeKey(tabId) {
  const base = { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 };
  await cdpKey(tabId, { type: "keyDown", ...base });
  await cdpKey(tabId, { type: "keyUp", ...base });
}

async function cdpSelectAllDelete(tabId) {
  const a = { key: "a", code: "KeyA", windowsVirtualKeyCode: 65, nativeVirtualKeyCode: 65, modifiers: 2 };
  await cdpKey(tabId, { type: "keyDown", ...a });
  await cdpKey(tabId, { type: "keyUp", ...a });
  const b = { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8, nativeVirtualKeyCode: 8 };
  await cdpKey(tabId, { type: "keyDown", ...b });
  await cdpKey(tabId, { type: "keyUp", ...b });
}

// 可信事件搜索并进入会话（取代 content 合成路径的 wa:open-chat）。
// 新版 WhatsApp Web 中，搜索框的 Enter 可能打开「选择聊天」/新建聊天流程，
// 甚至把焦点带到通话界面。因此搜索过程只点击已确认的匹配结果，绝不发送 Enter。
async function cdpOpenChat(tabId, name) {
  const nameJ = JSON.stringify(name);
  const resultExpr = `window.__waExt.searchResultXY(${nameJ})`;
  const matchExpr = `window.__waExt.chatReady(${nameJ})`;
  const focused = await dbgEval(tabId, "window.__waExt.focusSearch()");
  if (!focused) throw new Error("搜索框无法安全聚焦（找不到明确的搜索输入框），已中止");
  await sleep(300);
  await cdpSelectAllDelete(tabId);
  if (!(await dbgEval(tabId, "window.__waExt.searchFocused()"))) {
    throw new Error("清空操作后焦点已离开搜索框，已中止以免误操作");
  }
  const cleared = String((await dbgEval(tabId, "window.__waExt.searchText()")) || "");
  if (cleared) throw new Error(`搜索框清空失败（当前内容「${cleared}」），已中止`);
  await dbgCommand(tabId, "Input.insertText", { text: name });
  await sleep(1000); // 人工节奏：输入群名后等 1 秒再查找结果
  const typed = String((await dbgEval(tabId, "window.__waExt.searchText()")) || "");
  if (!typed.includes(name)) throw new Error(`搜索框输入未生效（当前内容「${typed}」），已中止`);
  if (!(await cdpWait(tabId, resultExpr, 6000))) {
    throw new Error(`搜索结果中找不到会话「${name}」`);
  }
  const clicked = await dbgEval(tabId, `window.__waExt.clickSearchResult(${nameJ})`);
  if (!clicked) throw new Error(`搜索结果点击失败，会话「${name}」未打开`);
  if (!(await cdpWait(tabId, matchExpr, 6000))) {
    await cdpEscapeKey(tabId);
    throw new Error(`点击后未确认进入会话「${name}」`);
  }
}

// base64 → 页面内写入系统剪贴板（需标签页处于激活/聚焦状态，performSend 已保证）
async function cdpClipboardImage(tabId, img) {
  const expr = `(async () => {
    const b64 = ${JSON.stringify(img.dataBase64)};
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: ${JSON.stringify(img.mime || "image/png")} });
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
    return true;
  })()`;
  return dbgEval(tabId, expr, true);
}

// 文本 → 系统剪贴板（粘贴备注用，等效人工 Ctrl+C/Ctrl+V）
async function cdpClipboardText(tabId, text) {
  const expr = `(async () => {
    await navigator.clipboard.writeText(${JSON.stringify(text)});
    return true;
  })()`;
  return dbgEval(tabId, expr, true);
}

// base64 → 下载到本地临时目录，返回绝对路径（供 DOM.setFileInputFiles 使用）
async function downloadToTemp(img) {
  const url = `data:${img.mime || "image/png"};base64,${img.dataBase64}`;
  const dlId = await new Promise((resolve, reject) => {
    chrome.downloads.download(
      { url, filename: "wa_ext_tmp/" + img.name, conflictAction: "overwrite", saveAs: false },
      (id) => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message)); else resolve(id);
      }
    );
  });
  for (let i = 0; i < 60; i++) {
    const items = await new Promise((resolve) => chrome.downloads.search({ id: dlId }, resolve));
    const it = items && items[0];
    if (it && it.filename && it.state === "complete") return it.filename;
    if (it && it.state === "interrupted") throw new Error("临时下载中断: " + (it.error || ""));
    await sleep(250);
  }
  throw new Error("临时下载超时");
}

async function cdpSetFileInput(tabId, path) {
  const res = await dbgCommand(tabId, "Runtime.evaluate", { expression: "window.__waExt.fileInputPick()", returnByValue: false });
  const obj = res.result;
  if (!obj || !obj.objectId) return false;
  await dbgCommand(tabId, "DOM.setFileInputFiles", { files: [path], objectId: obj.objectId });
  return true;
}

// 发送结束后的临时图片清理：删除 wa_ext_tmp 下的下载文件并清掉对应下载记录。
// 尽力而为：任一步失败都不影响发送结果（下次发送同名文件会 overwrite）。
async function cleanupTempDownloads() {
  const searchOnce = (q) => new Promise((r) => chrome.downloads.search(q, (its) => r(its || [])));
  const eraseOnce = (q) => new Promise((r) => chrome.downloads.erase(q, () => { void chrome.runtime.lastError; r(); }));
  const removeFileOnce = (id) => new Promise((r) => {
    try {
      chrome.downloads.removeFile(id, () => { void chrome.runtime.lastError; r(); });
    } catch (e) { r(); }
  });
  try {
    const items = await searchOnce({ filenameRegex: "wa_ext_tmp", state: "complete" });
    for (const it of items) await removeFileOnce(it.id);
    await eraseOnce({ filenameRegex: "wa_ext_tmp" });
  } catch (e) { /* 忽略 */ }
}

// 通用等待：轮询页内表达式直到为真或超时
async function cdpWait(tabId, expr, timeout = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      if (await dbgEval(tabId, expr)) return true;
    } catch (e) { /* 重试 */ }
    await sleep(300);
  }
  return false;
}

// 预览弹出后：只在已确认的预览备注框上发送 Enter。
// 不再点击任何坐标，避免误触通话/其它头部按钮。
async function cdpSendAndVerify(tabId, baseline) {
  const bl = JSON.stringify(baseline);
  const before = await dbgEval(tabId, "window.__waExt.countOutgoing()");
  const focused = await dbgEval(tabId, `window.__waExt.focusPreview(${bl})`);
  if (!focused) throw new Error("预览备注框无法安全聚焦，本图未发送");
  await cdpEnterKey(tabId);
  const start = Date.now();
  while (Date.now() - start < 8000) {
    const done = await dbgEval(tabId, `window.__waExt.countOutgoing() > ${before} || !window.__waExt.previewFound(${bl})`);
    if (done) return true;
    await sleep(300);
  }
  return false;
}

// 发送单张图片 —— 完全复刻人工成功定序：
//   点聊天输入框 → 系统剪贴板 + 可信 Ctrl+V 粘图 → 等预览（约1s 节奏轮询）→
//   粘贴备注（可信文本）→ 真实回车发送 → 校验出参+1/预览消失。
// 文件注入（downloadToTemp + DOM.setFileInputFiles）降为兜底：人工粘贴
// 每次都成功，主路径改为与之完全一致，不再先试文件注入打乱节奏。
async function cdpSendOneImage(tabId, img) {
  await cdpEscapeKey(tabId); // 关闭可能残留的预览/菜单/弹窗
  await sleep(300);
  const baseline = (await dbgEval(tabId, "window.__waExt.snapshotEditables()")) || {};
  const previewExpr = `window.__waExt.previewFound(${JSON.stringify(baseline)})`;

  // 主路径：系统剪贴板 + 可信 Ctrl+V（人工同款）。聚焦输入框用 eval focus
  // （绝无鼠标事件——0.1.2 的盲点点击曾落在头部语音/视频通话按钮上）。
  let preview = false;
  try {
    const focusedOk = await dbgEval(tabId, "window.__waExt.focusChatComposer()");
    if (!focusedOk) throw new Error("聊天输入框无法聚焦（可能有浮层遮挡）");
    await cdpClipboardImage(tabId, img);
    await cdpPasteKey(tabId);
    // 人工节奏：粘贴后等约 1 秒看预览，再继续
    preview = await cdpWait(tabId, previewExpr, 2000);
    if (!preview) preview = await cdpWait(tabId, previewExpr, 6000); // 大图解码慢时多等
  } catch (e) { /* 走兜底 */ }

  // 兜底：临时文件下载 + DOM.setFileInputFiles（Playwright 同款，仅主路径失败时）
  if (!preview) {
    try {
      const tmpPath = await downloadToTemp(img);
      await cdpSetFileInput(tabId, tmpPath);
      preview = await cdpWait(tabId, previewExpr, 8000);
    } catch (e) { /* 两条路径都失败 */ }
  }
  if (!preview) throw new Error("图片未进入发送预览（Ctrl+V 粘贴与文件注入均失败）");

  // 备注只写预览备注框：等效人工「点进预览备注框、粘贴文字」（绝不写聊天输入框）
  if (img.caption) {
    const bl = JSON.stringify(baseline);
    const focused = await dbgEval(tabId, `window.__waExt.focusPreview(${bl})`);
    if (focused) {
      await cdpClipboardText(tabId, img.caption);
      await cdpPasteKey(tabId);
      await sleep(1000); // 人工节奏：粘贴备注后等 1 秒
      const got = String((await dbgEval(tabId, `window.__waExt.previewText(${bl})`)) || "");
      if (!got.includes(img.caption.replace(/[*_~]/g, "").slice(0, 6))) {
        // 粘贴没生效时退回可信文本插入（InsertText），仍只写预览备注框
        await dbgEval(tabId, `window.__waExt.focusPreview(${bl})`);
        await dbgCommand(tabId, "Input.insertText", { text: img.caption });
        await sleep(300);
      }
    } else {
      // 找不到预览备注框：绝不 insertText（焦点多半还在聊天输入框，会把备注
      // 打进聊天框——历史事故根因）。宁可这张图缺备注，直接发送。
    }
  }

  // 发送：优先点发送按钮（人工同款）；按钮没找到时在预览备注框回车
  const ok = await cdpSendAndVerify(tabId, baseline);
  if (!ok) {
    await cdpEscapeKey(tabId);
    throw new Error("点击发送后未确认送达");
  }
  await sleep(700);
}

// 调试器主发送流程；返回与 wa:send 相同形状的结果。attach 失败则交由调用方报错。
async function sendViaDebugger(tabId, groups, images) {
  await dbgAttach(tabId);
  const out = { ok: false, groups_sent: [], errors: [] };
  try {
    await dbgEval(tabId, CDP_HELPERS);
    for (const group of groups) {
      // 先关可能残留的弹窗（如「选择聊天」对话框），避免它吃掉后续输入
      try { await cdpEscapeKey(tabId); await sleep(300); } catch (e) { /* 忽略 */ }
      let openOk = true;
      try {
        await cdpOpenChat(tabId, group);
      } catch (e) {
        openOk = false;
        out.errors.push(`[${group}] ${e.message || "无法进入会话"}`);
        try { await cdpEscapeKey(tabId); await sleep(300); } catch (e2) { /* 忽略 */ }
      }
      if (!openOk) continue;
      let sentCount = 0;
      for (const img of images) {
        try {
          await cdpSendOneImage(tabId, img);
          sentCount++;
          await sleep(500);
        } catch (e) {
          out.errors.push(`[${group}] 图片 ${img.name} 发送失败: ${e.message}`);
        }
      }
      if (sentCount > 0) out.groups_sent.push(group);
      if (sentCount === 0) out.errors.push(`[${group}] 没有任何图片发送成功`);
      await sleep(700);
    }
    out.ok = out.errors.length === 0 && out.groups_sent.length > 0;
    return out;
  } finally {
    await dbgDetach(tabId);
    await cleanupTempDownloads();
  }
}

// ---------- 简化发送引擎 v2 ----------
// 唯一业务顺序：搜索并进入群组 → 粘贴图片 → 等 1s → 粘贴备注 → 等 1s → Enter。
// 这里不使用搜索框 Enter、不清理未知输入框，也不做发送降级；进群只对精确群名
// 文字节点发送一次可信点击，发送图片仍只用聚焦 + Ctrl+V + 备注框 Enter。
const SIMPLE_HELPERS = `(() => {
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.offsetParent !== null;
  };
  const editables = () => [...document.querySelectorAll('[contenteditable="true"]')];
  const text = (el) => (el && (el.innerText || el.textContent || '')).trim();
  const aria = (el) => el ? ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-testid') || '')) : '';
  const searchBox = () => {
    const sels = [
      '#side input[type="search"]', '#side input', '#side [role="textbox"]',
      '#side div[contenteditable="true"]', '#pane-side input[type="search"]',
      '#pane-side [role="textbox"]'
    ];
    for (const sel of sels) {
      for (const el of document.querySelectorAll(sel)) if (visible(el)) return el;
    }
    return null;
  };
  const chatInput = () => {
    const all = editables().filter((el) => {
      if (!visible(el)) return false;
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight * 0.45) return false;
      if (/caption|说明|小标题|media|preview/i.test(aria(el))) return false;
      return !!el.closest('#main');
    });
    const footer = all.find((el) => el.closest('#main footer, #footer'));
    return footer || all[all.length - 1] || null;
  };
  const resultNode = (name) => {
    const search = searchBox();
    const roots = ['#pane-side', '#side'];
    const exact = [];
    for (const root of roots) {
      for (const el of document.querySelectorAll(root + ' *')) {
        if (el === search || (search && search.contains(el))) continue;
        if (visible(el) && text(el) === name) exact.push(el);
      }
    }
    exact.sort((a, b) => {
      const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
      return ar.width * ar.height - br.width * br.height;
    });
    return exact[0] || null;
  };
  const resultPoint = (name) => {
    const el = resultNode(name);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const x = Math.round(r.left + r.width / 2);
    const y = Math.round(r.top + r.height / 2);
    const at = document.elementFromPoint(x, y);
    if (!at || !(at === el || el.contains(at) || at.contains(el))) return null;
    return { x, y };
  };
  const previewInput = (baselineCount) => {
    const explicit = editables().find((el) => visible(el) &&
      /caption|说明|小标题|media-composer|media editor/i.test(aria(el)));
    if (explicit) return explicit;
    const candidates = editables().filter((el) => {
      if (!visible(el) || el === chatInput()) return false;
      if (/caption|说明|小标题|media|preview/i.test(aria(el))) return true;
      return text(el).length === 0;
    });
    return editables().length > baselineCount ? (candidates[candidates.length - 1] || null) : null;
  };
  window.__waSimple = {
    focusSearch() { const el = searchBox(); if (!el) return false; el.focus(); return document.activeElement === el; },
    searchFocused() { const el = searchBox(); return !!(el && document.activeElement === el); },
    searchText() { const el = searchBox(); return el ? (el.tagName === 'INPUT' ? el.value : text(el)) : ''; },
    resultFound(name) { return !!resultPoint(name); },
    resultPoint(name) { return resultPoint(name); },
    chatReady(name) {
      const main = document.querySelector('#main');
      const input = chatInput();
      return !!(main && input && (main.innerText || main.textContent || '').includes(name));
    },
    focusChat() { const el = chatInput(); if (!el) return false; el.focus(); return document.activeElement === el; },
    snapshotCount() { return editables().length; },
    previewFound(base) { return !!previewInput(base); },
    focusPreview(base) { const el = previewInput(base); if (!el) return false; el.focus(); return document.activeElement === el; },
    previewText(base) { const el = previewInput(base); return text(el); },
    outgoingCount() { const m = document.querySelector('#main'); return m ? m.querySelectorAll('div[data-id^="true_"]').length : 0; }
  };
  return true;
})()`;

async function simpleOpenChat(tabId, name) {
  const n = JSON.stringify(name);
  // 仅关闭上一次残留的弹窗；不点击页面，也不清理未知输入框。
  await cdpEscapeKey(tabId);
  await sleep(300);
  if (!(await dbgEval(tabId, "window.__waSimple.focusSearch()"))) {
    throw new Error("找不到可用的 WhatsApp 搜索框");
  }
  await cdpSelectAllDelete(tabId);
  if (!(await dbgEval(tabId, "window.__waSimple.searchFocused()"))) {
    throw new Error("清空后焦点不在搜索框，已停止");
  }
  if (String(await dbgEval(tabId, "window.__waSimple.searchText()") || "")) {
    throw new Error("搜索框未能清空，已停止");
  }
  await dbgCommand(tabId, "Input.insertText", { text: name });
  await sleep(1000);
  if (String(await dbgEval(tabId, "window.__waSimple.searchText()") || "") !== name) {
    throw new Error("群名输入校验失败，已停止");
  }
  if (!(await cdpWait(tabId, `window.__waSimple.resultFound(${n})`, 6000))) {
    throw new Error(`搜索结果中找不到「${name}」`);
  }
  const point = await dbgEval(tabId, `window.__waSimple.resultPoint(${n})`);
  if (!point || typeof point.x !== "number" || typeof point.y !== "number") {
    throw new Error(`无法安全定位群组「${name}」`);
  }
  // 只有精确群名文字节点的中心坐标才允许产生可信点击。
  await dbgCommand(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1,
  });
  await dbgCommand(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1,
  });
  if (!(await cdpWait(tabId, `window.__waSimple.chatReady(${n})`, 6000))) {
    throw new Error(`点击后未进入群会话「${name}」`);
  }
}

async function simpleSendOne(tabId, img) {
  const base = Number(await dbgEval(tabId, "window.__waSimple.snapshotCount()")) || 0;
  if (!(await dbgEval(tabId, "window.__waSimple.focusChat()"))) {
    throw new Error("群会话输入框未就绪");
  }
  await cdpClipboardImage(tabId, img);
  await cdpPasteKey(tabId);
  await sleep(1000);
  if (!(await cdpWait(tabId, `window.__waSimple.previewFound(${base})`, 6000))) {
    throw new Error("图片粘贴后未出现发送预览");
  }
  if (!(await dbgEval(tabId, `window.__waSimple.focusPreview(${base})`))) {
    throw new Error("发送预览备注框未就绪");
  }
  if (img.caption) {
    await cdpClipboardText(tabId, img.caption);
    await cdpPasteKey(tabId);
  }
  await sleep(1000);
  if (!(await dbgEval(tabId, `window.__waSimple.focusPreview(${base})`))) {
    throw new Error("回车前备注框焦点丢失，已停止");
  }
  const before = Number(await dbgEval(tabId, "window.__waSimple.outgoingCount()")) || 0;
  await cdpEnterKey(tabId);
  if (!(await cdpWait(tabId, `window.__waSimple.outgoingCount() > ${before} || !window.__waSimple.previewFound(${base})`, 8000))) {
    throw new Error("回车后未确认图片发送");
  }
}

async function simpleSendViaDebugger(tabId, groups, images) {
  await dbgAttach(tabId);
  const out = { ok: false, groups_sent: [], errors: [] };
  try {
    await dbgEval(tabId, SIMPLE_HELPERS);
    for (const group of groups) {
      try {
        await simpleOpenChat(tabId, group);
        let count = 0;
        for (const img of images) {
          try { await simpleSendOne(tabId, img); count++; } catch (e) {
            out.errors.push(`[${group}] 图片 ${img.name} 发送失败: ${e.message || e}`);
          }
        }
        if (count) out.groups_sent.push(group);
        if (!count) out.errors.push(`[${group}] 没有图片发送成功`);
      } catch (e) {
        out.errors.push(`[${group}] ${e.message || e}`);
      }
    }
    out.ok = out.errors.length === 0 && out.groups_sent.length > 0;
    return out;
  } finally {
    await dbgDetach(tabId);
  }
}

// ---------- 后端作业（认领 / 回报） ----------
async function tryClaimJob(cfg) {
  try {
    const res = await apiFetch(cfg, "/api/whatsapp/ext/job");
    if (!res.ok) return null;
    const job = await res.json();
    return job && job.pending === true ? job : null;
  } catch (e) {
    return null; // 后端未启动等，静默
  }
}

async function reportJobResult(cfg, jobId, result) {
  try {
    await apiFetch(cfg, "/api/whatsapp/ext/job/result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, ...result }),
    });
  } catch (e) {
    result.errors.push(`结果回报失败: ${e.message}`);
  }
}

// 认领后端作业并发送；无作业返回 false
async function claimAndRunJob(cfg, trigger) {
  // 必须先查 running 再认领：认领会把后端作业置为 running，
  // 若认领后才因「发送进行中」放弃，作业会被空占直到超时判失败（消息漏发）。
  if (running) return false;
  const job = await tryClaimJob(cfg);
  if (!job) return false;
  running = true;
  try {
    const result = await performSend(cfg, job.groups || [], job.items || [], `作业 ${job.job_id}`, job.job_id);
    await reportJobResult(cfg, job.job_id, result);
    const run = {
      trigger, job_id: job.job_id,
      started_at: new Date().toISOString(),
      ...result,
    };
    await writeLastRun(run);
    broadcast({ type: "sidepanel:progress", phase: "done", run });
    return true;
  } finally {
    running = false;
  }
}

// 定时触发：优先认领作业（与后端任务同刻触发时避免双发），否则直发 outbox
async function runScheduled(cfg) {
  if (await claimAndRunJob(cfg, "schedule")) return;
  // 刚成功发送过则跳过直发（防双发）。按 finished_at（完成时刻）判定：
  // 若按 started_at 算，长发送（>2 分钟）+ 相邻分钟命中 cron 时窗口早已过期。
  const d = await chrome.storage.local.get(LAST_RUN_KEY);
  const last = d[LAST_RUN_KEY];
  const lastAt = last && (last.finished_at || last.started_at);
  if (last && last.ok && lastAt
      && Date.now() - Date.parse(lastAt) < DEDUP_WINDOW_MS) {
    return;
  }
  await sendOutboxDirect(cfg, "schedule");
}

// 直接从 outbox 拉图发送（手动 / 定时）
async function sendOutboxDirect(cfg, trigger) {
  if (running) return { ok: false, errors: ["上一次发送仍在进行"] };
  running = true;
  const startedAt = Date.now();
  try {
    let outbox;
    try {
      const res = await apiFetch(cfg, "/api/whatsapp/outbox");
      if (!res.ok) throw new Error(`outbox 返回 ${res.status}`);
      outbox = await res.json();
    } catch (e) {
      const run = {
        trigger, started_at: new Date(startedAt).toISOString(),
        ok: false, groups_sent: [],
        errors: [`后端不可达（${normalizeBaseUrl(cfg.server_url)}）：${e.message}`],
        elapsed_seconds: 0,
      };
      await writeLastRun(run);
      return run;
    }
    const result = await performSend(cfg, outbox.groups || [], outbox.items || [],
      trigger === "manual" ? "手动发送" : "定时发送");
    const run = { trigger, started_at: new Date(startedAt).toISOString(), ...result };
    await writeLastRun(run);
    broadcast({ type: "sidepanel:progress", phase: "done", run });
    return run;
  } finally {
    running = false;
  }
}

// 确保标签页里 content script 存活（页面可能早于扩展加载/扩展刚重载过）：
// 先探活，无接收端则补注入再探活一次。侧栏「清空输入框/页面诊断」与发送共用。
async function ensureContentAlive(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "wa:ping" });
    if (pong && pong.pong) return true;
  } catch (e) { /* 无接收端 */ }
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    await sleep(300);
    const pong = await chrome.tabs.sendMessage(tabId, { type: "wa:ping" });
    return !!(pong && pong.pong);
  } catch (e) {
    return false;
  }
}

// ---------- sidepanel 消息 ----------
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return false;
  switch (msg.type) {
    case "config:get":
      getConfig().then((cfg) => sendResponse({ cfg }));
      return true;
    case "config:set":
      saveConfig(msg.cfg || {}).then(() => getConfig()).then((cfg) => sendResponse({ ok: true, cfg }));
      return true;
    case "send:now":
      getConfig().then((cfg) => sendOutboxDirect(cfg, "manual")).then((run) => sendResponse(run));
      return true;
    case "poll:now":
      getConfig()
        .then((cfg) => claimAndRunJob(cfg, "job"))
        .then((claimed) => sendResponse({ ok: true, claimed }));
      return true;
    case "clear:now":
      (async () => {
        try {
          const tab = await findWhatsAppTab();
          if (!tab) return sendResponse({ ok: false, error: "未找到打开的 WhatsApp Web 标签页" });
          if (!(await ensureContentAlive(tab.id))) {
            return sendResponse({ ok: false, error: "页面无响应（content script 注入失败），请刷新 WhatsApp Web 后重试" });
          }
          const r = await chrome.tabs.sendMessage(tab.id, { type: "wa:clear" });
          sendResponse(r || { ok: false, error: "页面无回执" });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message || e) });
        }
      })();
      return true;
    case "diagnose:now":
      (async () => {
        try {
          const tab = await findWhatsAppTab();
          if (!tab) return sendResponse({ ok: false, error: "未找到打开的 WhatsApp Web 标签页" });
          if (!(await ensureContentAlive(tab.id))) {
            return sendResponse({ ok: false, error: "页面无响应（content script 注入失败），请刷新 WhatsApp Web 后重试" });
          }
          const r = await chrome.tabs.sendMessage(tab.id, { type: "wa:diagnose" });
          sendResponse(r || { ok: false, error: "页面无回执" });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message || e) });
        }
      })();
      return true;
    case "wa:sleep": {
      // content 侧的等待经由本 SW 代等：SW 定时器不受页面可见性节流影响，
      // 这是「WhatsApp Web 页面不需要保持前台显示」的关键。SW 侧 sleep 为
      // Promise 定时器，期间事件循环保持存活。
      const ms = Math.max(0, Math.min(Number(msg.ms) || 0, 120_000));
      sleep(ms).then(() => sendResponse({ slept: ms }));
      return true;
    }
    case "wa:job-result": {
      // content 直报的作业结果：即便发起发送的 SW 实例已被 Chrome 回收，
      // 这条消息仍会唤醒新实例完成回报（后端按 job 状态幂等去重）。
      const jobId = msg.jobId;
      const result = msg.result || { ok: false, groups_sent: [], errors: ["无结果回执"], elapsed_seconds: 0 };
      getConfig()
        .then((cfg) => reportJobResult(cfg, jobId, result))
        .then(() => writeLastRun({ trigger: "job", job_id: jobId, started_at: new Date().toISOString(), ...result }))
        .then(() => sendResponse({ ok: true }))
        .catch((e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    }
    case "status:get":
      chrome.storage.local.get(LAST_RUN_KEY).then((d) => sendResponse({ lastRun: d[LAST_RUN_KEY] || null }));
      return true;
    default:
      return false;
  }
});

// ---------- 生命周期 ----------
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("[wa-sender] setPanelBehavior failed", e));

chrome.runtime.onInstalled.addListener(async () => { await syncAlarms(await getConfig()); });
chrome.runtime.onStartup.addListener(async () => { await syncAlarms(await getConfig()); });
// 顶层兜底：SW 每次被唤醒（含 keepalive）都恢复闹钟。必须用已保存配置——
// 若传 DEFAULTS，用户停用定时后闹钟每分钟都会被重新建回来，开关形同虚设。
getConfig().then(syncAlarms).catch(() => {});
