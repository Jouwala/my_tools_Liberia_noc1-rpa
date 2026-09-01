// WhatsApp Image Sender - content script（仅运行在 https://web.whatsapp.com）
// 职责：在用户已登录的 WhatsApp Web 里，逐群逐图发送 background 传来的图片。
//
// 关键约束（针对“备注堆在输入框、图发不出去”的问题）：
//   1) 每张图发送前必须把上一次的备注/残留清空（清空后才允许输入）；
//   2) 发送后必须校验“真的发出去了”（出参消息条数增加，或预览/备注框消失）；
//   3) 校验失败就记错并清场，绝不让多条备注堆在输入框里；
//   4) 备注只写「发送媒体」预览里的备注框，绝不写 #main 的聊天输入框
//      （堆叠事故的根因就是选择器退化匹配到了聊天输入框）；
//   5) 图片进预览有四路尝试：文件选择 input → 粘贴 → 拖放 → 附件菜单。
//
// WhatsApp Web 的 class 名是混淆的，选择器收敛在 SELECTORS 中，优先使用
// data-testid / data-icon / aria / role 等稳定特征；与 whatsapp_service.py / @Me 扩展一致。

const SELECTORS = {
  searchBox: ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
  chatListItem: '#side [role="listitem"]',
  main: '#main',
  mainChatInput: ['#footer div[contenteditable="true"]', '#main footer div[contenteditable="true"]'],
  attach: [
    '[data-icon="plus"]',
    '[data-testid="attach-menu-plus"]',
    'span[data-icon="clip"]',
    'div[title*="Attach"]',
    'div[title*="附件"]',
    'span[data-icon="attach-menu-plus"]',
  ],
  photosMenuItem: [
    '[data-testid="attach-menu"] [data-testid*="photos"]',
    'div[role="menuitem"][aria-label*="Photos" i]',
    'div[role="menuitem"][aria-label*="照片"]',
    'span[data-icon="attach-menu-photos"]',
  ],
  fileInput: 'input[type="file"]',
  captionInput: [
    'div[aria-label="Add a caption"]',
    'div[aria-label="添加说明"]',
    'div[aria-label="添加小标题"]',
    'div[aria-label*="caption" i]',
    'div[aria-label*="说明"]',
    '[data-testid="media-composer"] [contenteditable="true"]',
    '[data-testid*="preview"] [contenteditable="true"]',
  ],
  sendButton: [
    '[data-testid="send"]',
    '[data-testid="send-btn"]',
    '[data-testid*="compose"][data-testid*="send"]',
    'button[aria-label="Send"]',
    'button[aria-label="发送"]',
    'button[aria-label*="Send" i]',
    '[data-icon="send"]',
    'span[data-icon="send"]',
    'button[data-icon="send"]',
  ],
};

// 等待经由 background SW 代等（wa:sleep）：SW 的定时器不受页面可见性节流影响，
// 这是「WhatsApp Web 标签页在后台也能按节奏发送」的关键。SW 不可达时退化为本地定时器。
function sleep(ms) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    try {
      chrome.runtime.sendMessage({ type: "wa:sleep", ms }, () => {
        void chrome.runtime.lastError; // 消费错误
        finish();
      });
    } catch (e) {
      setTimeout(finish, ms);
      return;
    }
    // 兜底：SW 长时间无响应时不至于永久挂起
    setTimeout(finish, ms + 3000);
  });
}

// ---------- 基础 ----------
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && el.offsetParent !== null;
}

function q(selectors, root) {
  const list = Array.isArray(selectors) ? selectors : [selectors];
  const scope = root || document;
  for (const sel of list) {
    try {
      const el = scope.querySelector(sel);
      if (el) return el;
    } catch (e) { /* 无效选择器跳过 */ }
  }
  return null;
}

function qVisible(selectors, root) {
  const list = Array.isArray(selectors) ? selectors : [selectors];
  const scope = root || document;
  for (const sel of list) {
    try {
      for (const el of scope.querySelectorAll(sel)) {
        if (visible(el)) return el;
      }
    } catch (e) { /* 跳过 */ }
  }
  return null;
}

async function waitFor(fn, timeout = 8000, step = 200) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const v = fn();
      if (v) return v;
    } catch (e) { /* 重试 */ }
    await sleep(step);
  }
  return null;
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function dispatchEnter(el) {
  for (const type of ["keydown", "keypress", "keyup"]) {
    el.dispatchEvent(new KeyboardEvent(type, {
      key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true,
    }));
  }
}

// 完整鼠标事件序列点击（比裸 el.click() 更容易触发 React 的 onClick）
function robustClick(el) {
  const target = (el.closest && el.closest('button, [role="button"], div[role="button"]')) || el;
  const opts = { bubbles: true, cancelable: true, view: window, button: 0 };
  try {
    target.dispatchEvent(new PointerEvent("pointerdown", opts));
    target.dispatchEvent(new MouseEvent("mousedown", opts));
    target.dispatchEvent(new PointerEvent("pointerup", opts));
    target.dispatchEvent(new MouseEvent("mouseup", opts));
    target.dispatchEvent(new MouseEvent("click", opts));
  } catch (e) {
    try { target.click(); } catch (e2) { /* 忽略 */ }
  }
  return target;
}

function textOf(el) {
  return el ? (el.innerText || el.textContent || "").trim() : "";
}

// ---------- 备注框识别（必须是“发送媒体”预览里的，绝不能是聊天输入框） ----------
// 历史事故：选择器退化匹配到 #main 里的聊天输入框，备注全部打进聊天框、堆成
// *REGULAR**ERA**ALL*…；预览其实从未弹出。现在 #main 内的元素一律跳过，
// 除非它的 aria 明确写着 caption/说明/标题（兼容预览渲染在 #main 内的版本）。
function isInsideMain(el) {
  return !!(el && el.closest && el.closest("#main"));
}

function hasCaptionAria(el) {
  const a = `${el.getAttribute("aria-label") || ""} ${el.getAttribute("data-testid") || ""}`;
  return /caption|说明|小标题|标题|media-composer/i.test(a);
}

function captionComposer() {
  for (const sel of SELECTORS.captionInput) {
    try {
      for (const el of document.querySelectorAll(sel)) {
        if (!visible(el)) continue;
        if (isInsideMain(el) && !hasCaptionAria(el)) continue;
        return el;
      }
    } catch (e) { /* 跳过 */ }
  }
  return null;
}

// ---------- 备注输入框：清空 / 写入 ----------
async function clearComposer(el) {
  for (let i = 0; i < 5 && textOf(el); i++) {
    try { el.click(); } catch (e) {}
    el.focus();
    try { document.execCommand("selectAll", false, null); } catch (e) {}
    try { document.execCommand("delete", false, null); } catch (e) {}
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "a", code: "KeyA", ctrlKey: true, bubbles: true, cancelable: true }));
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", code: "Backspace", bubbles: true, cancelable: true }));
    try { document.execCommand("insertText", false, ""); } catch (e) {}
    el.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(150);
  }
  return !textOf(el);
}

async function setComposerText(el, text) {
  const cleared = await clearComposer(el);
  if (!cleared && textOf(el)) {
    // 仍清不掉，直接置空（兜底，避免旧备注残留叠加）
    try { el.textContent = ""; } catch (e) {}
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  el.focus();
  try { document.execCommand("insertText", false, text); } catch (e) { el.textContent = text; }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  await sleep(200);
  // 校验写入成功；没写进去再兜底一次
  const probe = text.replace(/[*_~]/g, "").slice(0, 6);
  if (text && probe && !textOf(el).includes(probe)) {
    try { document.execCommand("insertText", false, text); } catch (e) {}
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  return true;
}

// ---------- 出参消息计数（校验“真的发出去了”） ----------
function countOutgoing() {
  const main = document.querySelector(SELECTORS.main);
  if (!main) return 0;
  return main.querySelectorAll('div[data-id^="true_"]').length;
}

// ---------- 打开会话 ----------
// 新版 WhatsApp Web：搜索框里按回车会弹出「选择聊天」对话框（通话/转发流程），
// 绝不使用回车。过滤出目标条目后直接点击，并通过会话标题校验确实进入了正确的会话
// （此前 #main 一直可见导致“上一个会话”被误判为已进入）。
async function openChat(name) {
  const search = q(SELECTORS.searchBox);
  if (!search) throw new Error("找不到左侧搜索框（#side 未就绪）");
  search.click();
  search.focus();
  try { document.execCommand("selectAll", false, null); } catch (e) {}
  try { document.execCommand("delete", false, null); } catch (e) {}
  try { document.execCommand("insertText", false, name); } catch (e) {}
  await sleep(1200);

  const item = await waitFor(() => {
    const items = [...document.querySelectorAll(SELECTORS.chatListItem)];
    return items.find((it) => visible(it) && (it.textContent || "").includes(name)) || null;
  }, 4000);
  if (!item) throw new Error(`过滤结果中找不到会话「${name}」`);
  item.click();

  const ok = await waitFor(() => {
    const main = document.querySelector(SELECTORS.main);
    if (!visible(main)) return null;
    return (main.textContent || "").slice(0, 800).includes(name) ? true : null;
  }, 6000);
  if (!ok) throw new Error(`进入会话「${name}」未获确认`);
  await sleep(600);
  return true;
}

// ---------- 选择文件并注入 ----------
function pickFileInput() {
  const inputs = [...document.querySelectorAll(SELECTORS.fileInput)];
  if (!inputs.length) return null;
  return (
    inputs.find((i) => (i.getAttribute("accept") || "").toLowerCase().includes("image")) ||
    inputs[inputs.length - 1]
  );
}

function injectFile(img) {
  const input = pickFileInput();
  if (!input) return false;
  try {
    const bytes = base64ToBytes(img.dataBase64);
    const file = new File([bytes], img.name, { type: img.mime || "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  } catch (e) {
    return false;
  }
}

function fileOf(img) {
  const bytes = base64ToBytes(img.dataBase64);
  return new File([bytes], img.name, { type: img.mime || "image/png" });
}

// 等效于在聊天框里 Ctrl+V 粘贴一张图片
function pasteFile(img) {
  const el = qVisible(SELECTORS.mainChatInput);
  if (!el) return false;
  try {
    const dt = new DataTransfer();
    dt.items.add(fileOf(img));
    el.focus();
    el.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: dt }));
    return true;
  } catch (e) {
    return false;
  }
}

// 等效于把图片拖放进聊天区域
function dropFile(img) {
  const target = document.querySelector("#main") || document.querySelector("#app");
  if (!target) return false;
  try {
    const dt = new DataTransfer();
    dt.items.add(fileOf(img));
    for (const type of ["dragenter", "dragover"]) {
      target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
    }
    target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    return true;
  } catch (e) {
    return false;
  }
}

// 把图片送进「发送媒体」预览；成功 = 出现预览备注框。依次尝试：
// 文件选择 input → 粘贴 → 拖放 → 附件菜单打开后再走文件选择
async function stageImage(img) {
  if (injectFile(img)) {
    const c = await waitFor(() => captionComposer(), 5000, 250);
    if (c) return c;
  }
  if (pasteFile(img)) {
    const c = await waitFor(() => captionComposer(), 5000, 250);
    if (c) return c;
  }
  if (dropFile(img)) {
    const c = await waitFor(() => captionComposer(), 5000, 250);
    if (c) return c;
  }
  const attach = qVisible(SELECTORS.attach);
  if (attach) {
    attach.click();
    await sleep(400);
    const photos = qVisible(SELECTORS.photosMenuItem);
    if (photos) { photos.click(); await sleep(400); }
    if (injectFile(img)) {
      const c = await waitFor(() => captionComposer(), 6000, 250);
      if (c) return c;
    }
  }
  return null;
}

// ---------- 发送当前带图预览 ----------
async function sendStaged() {
  const before = countOutgoing();
  const composer = captionComposer();
  const sendBtn = qVisible(SELECTORS.sendButton);

  if (sendBtn) {
    robustClick(sendBtn);
  } else if (composer) {
    composer.focus();
    dispatchEnter(composer);
  } else {
    throw new Error("找不到发送按钮/备注框");
  }

  // 校验：出参消息增加，或带图预览/备注框消失
  const sent = await waitFor(() => {
    if (countOutgoing() > before) return true;
    if (!captionComposer()) return true;
    return null;
  }, 6000, 250);

  if (!sent && composer) {
    // 兜底：用回车再试一次
    composer.focus();
    dispatchEnter(composer);
    await waitFor(() => countOutgoing() > before || !captionComposer(), 4000, 250);
  }
  return countOutgoing() > before || !captionComposer();
}

// ---------- 发送单张图片 ----------
async function sendOneImage(img) {
  // 0) 若已有残留的带图预览，先清掉其备注（避免叠加）
  const preComposer = captionComposer();
  if (preComposer) await clearComposer(preComposer);

  // 1) 把图片送进「发送媒体」预览（文件选择 → 粘贴 → 拖放 → 附件菜单）
  const composer = await stageImage(img);
  if (!composer) {
    throw new Error(
      `图片未进入发送预览（页面 file input ${document.querySelectorAll(SELECTORS.fileInput).length} 个，` +
      `已尝试 文件选择/粘贴/拖放/附件菜单）。请确认该群聊允许发送图片。`
    );
  }

  // 2) 清空后写备注（严格写入预览备注框，绝不写聊天输入框）
  if (img.caption) {
    await sleep(250);
    await setComposerText(composer, img.caption);
    await sleep(250);
  }

  // 3) 发送并校验
  const ok = await sendStaged();
  if (!ok) {
    // 发送未确认：清场，避免备注残留
    const c = captionComposer();
    if (c) await clearComposer(c);
    throw new Error("点击发送后未确认送达");
  }
  await sleep(700);
  return true;
}

// ---------- 清场（侧栏“清空输入框”） ----------
async function clearStuck() {
  try {
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", keyCode: 27, bubbles: true }));
  } catch (e) {}
  let cleared = 0;
  for (const sel of [SELECTORS.captionInput, SELECTORS.mainChatInput]) {
    const el = qVisible(sel) || q(sel);
    if (el && textOf(el)) {
      if (await clearComposer(el)) cleared++;
    }
  }
  return { ok: true, cleared };
}

// ---------- 主流程 ----------
async function handleSend(groups, images) {
  const result = { ok: false, groups_sent: [], errors: [], diagnostics: {} };
  result.diagnostics.hasMain = !!document.querySelector(SELECTORS.main);

  for (const group of groups) {
    try {
      await openChat(group);
      let sentCount = 0;
      for (const img of images) {
        try {
          await sendOneImage(img);
          sentCount++;
          await sleep(500);
        } catch (e) {
          result.errors.push(`[${group}] 图片 ${img.name} 发送失败: ${e.message}`);
        }
      }
      if (sentCount > 0) result.groups_sent.push(group);
      if (sentCount === 0) result.errors.push(`[${group}] 没有任何图片发送成功`);
    } catch (e) {
      result.errors.push(`[${group}] ${e.message}`);
    }
    await sleep(700);
  }

  result.ok = result.errors.length === 0 && result.groups_sent.length > 0;
  result.diagnostics.fileInputs = document.querySelectorAll(SELECTORS.fileInput).length;
  return result;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return false;

  if (msg.type === "wa:ping") {
    sendResponse({ pong: true });
    return false;
  }

  if (msg.type === "wa:open-chat") {
    openChat(msg.group)
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;
  }

  if (msg.type === "wa:diagnose") {
    try {
      const inputs = [...document.querySelectorAll("input[type='file']")].map((i) => ({
        accept: i.getAttribute("accept") || "",
        visible: visible(i),
        size: `${Math.round(i.getBoundingClientRect().width)}x${Math.round(i.getBoundingClientRect().height)}`,
        parent: i.parentElement ? `${i.parentElement.tagName}.${(i.parentElement.className || "").toString().slice(0, 30)}` : "",
      }));
      const editables = [...document.querySelectorAll("[contenteditable='true']")].map((e) => ({
        aria: e.getAttribute("aria-label") || "",
        inMain: isInsideMain(e),
        visible: visible(e),
        text: textOf(e).slice(0, 30),
      }));
      const searchBox = (() => {
        const cands = ['#side input[type="search"]', '#side input', '#side div[contenteditable="true"]', '#side [role="textbox"]'];
        for (const sel of cands) {
          const el = document.querySelector(sel);
          if (!el) continue;
          return {
            sel,
            tag: el.tagName,
            type: el.getAttribute("type") || "",
            role: el.getAttribute("role") || "",
            aria: el.getAttribute("aria-label") || "",
            placeholder: el.getAttribute("placeholder") || "",
            visible: visible(el),
            text: ((el.tagName === "INPUT" ? el.value : textOf(el)) || "").slice(0, 30),
          };
        }
        return null;
      })();
      sendResponse({
        ok: true,
        hasMain: !!document.querySelector("#main"),
        fileInputs: inputs,
        editables,
        searchBox,
        attachBtn: !!qVisible(SELECTORS.attach),
        sendBtn: !!qVisible(SELECTORS.sendButton),
        captionComposer: !!captionComposer(),
      });
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message || e) });
    }
    return false;
  }

  if (msg.type === "wa:clear") {
    clearStuck().then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg.type !== "wa:send") return false;
  (async () => {
    const startedAt = Date.now();
    let res;
    try {
      res = await handleSend(msg.groups || [], msg.images || []);
    } catch (e) {
      res = {
        ok: false, groups_sent: [],
        errors: [`发送失败：${e && e.message ? e.message : String(e)}（WhatsApp Web DOM 可能已变更）`],
      };
    }
    res.elapsed_seconds = Math.round((Date.now() - startedAt) / 1000);
    // 直报作业结果：即便发起发送的 SW 实例已被回收，这条消息仍能唤醒新实例完成回报
    if (msg.jobId) {
      try {
        chrome.runtime.sendMessage({ type: "wa:job-result", jobId: msg.jobId, result: res }, () => {
          void chrome.runtime.lastError;
        });
      } catch (e) { /* 忽略 */ }
    }
    sendResponse(res);
  })();
  return true; // 保持消息通道以支持异步 sendResponse
});
