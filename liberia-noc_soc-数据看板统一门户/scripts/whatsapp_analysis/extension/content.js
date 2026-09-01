// WhatsApp @Me Assistant - content script
// 合规边界：只读取用户已登录会话的页面 DOM，不发送任何消息、不修改页面内容。
// WhatsApp Web 的 class 名是混淆的，因此选择器收敛在 SELECTORS 配置对象中，
// 优先使用 data-testid / data-id / role / aria 等稳定特征；失效时输出诊断信息。

const SELECTORS = {
  chatListItem: '[role="listitem"]',
  mentionBadge: '[data-testid*="mention"], [aria-label*="mention" i]',
  messageContainer: '[data-testid="conversation-panel-messages"]',
  messageNode: 'div[data-id]',
  messageBody: 'span.copyable-text',
  mentionChip: 'span[data-testid="mention-at"]',
  conversationTitle:
    '#main header span[data-testid="conversation-info-header-chat-title"], #main header span[title], #main header div[role="heading"]',
  selfNameCandidates: [
    '[data-testid="menu-bar-title"]',
    '#side header span[title]',
  ],
};

const SELF_NAME_KEY = "wa_assistant_self_name";
const SCROLL_PAUSE_MS = 450;
const MAX_SCROLLS = 10;

// 截图提取：把 @我 上下文里出现的聊天截图（告警截图/TT 单号截图）带回给服务端做 AI 识别。
// blob: 同源可安全画到 canvas；跨源缩略图/未加载媒体画不出时静默跳过。
const IMAGE_MAX_DIM = 1280; // 降采样上限，保证 TT 号文字仍可辨认
const IMAGE_JPEG_QUALITY = 0.85;
const MAX_IMAGES_PER_CONTEXT = 2; // 每个 @我 上下文最多带几张图
const MAX_IMAGES_PER_SCAN = 8; // 单次扫描全局预算
const MIN_MEDIA_W = 200; // 过滤头像/表情等小图
const MIN_MEDIA_H = 120;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getSelfName() {
  const stored = await chrome.storage.local.get(SELF_NAME_KEY);
  if (stored[SELF_NAME_KEY]) return stored[SELF_NAME_KEY];
  for (const sel of SELECTORS.selfNameCandidates) {
    const el = document.querySelector(sel);
    const name = el && el.textContent ? el.textContent.trim() : "";
    if (name && name.length <= 60) {
      await chrome.storage.local.set({ [SELF_NAME_KEY]: name });
      return name;
    }
  }
  return "";
}

function parseMessageNode(node) {
  const id = node.getAttribute("data-id") || "";
  // WhatsApp 消息节点的 data-pre-plain-text 形如 "[2026-08-31 10:00:00] John:"，可稳定取到发送人和时间
  const pre = node.getAttribute("data-pre-plain-text") || "";
  let sender = "";
  let timestamp = "";
  const m = pre.match(/^\[(.+?)\]\s*(.*?):?\s*$/);
  if (m) {
    timestamp = m[1];
    sender = m[2];
  }
  // 频道/公告类消息没有 data-pre-plain-text：兜底读气泡内的时间元素（只有时间没有日期）
  if (!timestamp) {
    const dtEl = node.querySelector('[data-testid="message-datetime"], footer [data-testid="msg-meta"] span');
    const dtText = dtEl ? dtEl.textContent.trim() : "";
    if (/^\d{1,2}:\d{2}/.test(dtText)) timestamp = dtText;
  }
  const bodyEl = node.querySelector(SELECTORS.messageBody);
  const text = bodyEl ? bodyEl.innerText.trim() : node.innerText.trim();
  if (!text && !sender && !timestamp) return null; // 系统分隔条等非消息节点
  const mentionChips = [...node.querySelectorAll(SELECTORS.mentionChip)];
  const mentionedNames = mentionChips
    .map((c) => c.textContent.trim())
    .filter(Boolean);
  const isFromMe = id.startsWith("true_");
  return { id, sender, timestamp, text, mentionedNames, isFromMe };
}

function visibleMessageNodes() {
  const main = document.querySelector("#main");
  if (!main) return [];
  return [...main.querySelectorAll(SELECTORS.messageNode)];
}

function visibleMessages() {
  return visibleMessageNodes().map(parseMessageNode).filter(Boolean);
}

function currentGroupName() {
  const el = document.querySelector(SELECTORS.conversationTitle);
  const raw = el ? el.textContent.trim() : "(未知会话)";
  // 部分会话名带 Markdown 式星号包裹（如 *P1 OLR ...*）：剥掉首尾星号，避免群名带杂质
  return raw.replace(/^[\*＊]+|[\*＊]+$/g, "").trim() || raw;
}

async function collectWithScrollUp(maxScrolls) {
  const container =
    document.querySelector(SELECTORS.messageContainer) ||
    document.querySelector("#main");
  const collected = new Map();
  // 虚拟列表：滚走后消息节点会被卸载，必须趁滚动停在某个位置时立刻把可见截图抓下来，
  // 事后再按 id 找 DOM 大概率找不到（此前截图几乎抓不到的根因）
  const imageStash = new Map(); // data-id -> {mime, dataBase64}
  const addAll = () => {
    for (const msg of visibleMessages()) {
      if (!collected.has(msg.id)) collected.set(msg.id, msg);
    }
  };
  const snapshotMedia = () => {
    for (const node of visibleMessageNodes()) {
      const id = node.getAttribute("data-id");
      if (!id || imageStash.has(id) || imageStash.size >= 24) continue;
      const el = pickMediaEl(node);
      if (!el) continue;
      const dataBase64 = elToJpegBase64(el);
      if (dataBase64) imageStash.set(id, { mime: "image/jpeg", dataBase64 });
    }
  };
  addAll();
  snapshotMedia();
  if (container) {
    for (let i = 0; i < maxScrolls; i++) {
      if (container.scrollTop <= 10) break;
      container.scrollTop = 0;
      await sleep(SCROLL_PAUSE_MS);
      const before = collected.size;
      addAll();
      snapshotMedia();
      if (collected.size === before && i > 2) break; // 已到会话顶部（连续几屏无新增）
    }
    container.scrollTop = container.scrollHeight; // 恢复到底部
  }
  // 按时间字符串排序（WhatsApp data-pre-plain-text 的时间格式可按字典序近似排序，再兜底用原始顺序）
  return { messages: [...collected.values()], imageStash };
}

function isMentionForMe(msg, name) {
  if (!name) return false;
  const n = name.toLowerCase().trim();
  const tokens = n.split(/[\s_\-().,]+/).filter((t) => t.length >= 2);
  const chipHit = msg.mentionedNames.some((raw) => {
    const c = raw.toLowerCase().replace(/^@/, "").trim();
    if (!c) return false;
    if (c === n || n.includes(c) || c.includes(n)) return true;
    return tokens.some((t) => c === t);
  });
  if (chipHit) return true;
  const text = msg.text.toLowerCase();
  return text.includes("@" + n) || tokens.some((t) => text.includes("@" + t));
}

function buildContextWindows(messages, selfName, before = 10, after = 5) {
  const mentionHits = [];
  messages.forEach((msg, idx) => {
    if (isMentionForMe(msg, selfName) && !msg.isFromMe) mentionHits.push(idx);
  });
  return mentionHits.map((idx) => {
    const start = Math.max(0, idx - before);
    const end = Math.min(messages.length, idx + after + 1);
    return {
      mentionIndex: idx - start,
      messages: messages.slice(start, end).map((m) => ({
        id: m.id,
        sender: m.sender,
        timestamp: m.timestamp,
        text: m.text,
        isFromMe: m.isFromMe,
      })),
    };
  });
}

// ---------- 截图提取 ----------
function domNodeForMessage(id) {
  if (!id) return null;
  try {
    return document.querySelector(`div[data-id="${CSS.escape(id)}"]`);
  } catch (e) {
    return null;
  }
}

// 消息节点里最像"内容截图"的媒体元素：跳过头像、表情等小图，取面积最大者。
// 严格要求已解码的真实像素（img 看 naturalWidth、video 看 readyState），
// 否则未加载完的占位图会画出空白画布被当成截图
function pickMediaEl(node) {
  if (!node) return null;
  let best = null;
  for (const el of node.querySelectorAll("img, canvas, video")) {
    let w = 0;
    let h = 0;
    if (el.tagName === "IMG") {
      w = el.naturalWidth || 0;
      h = el.naturalHeight || 0;
    } else if (el.tagName === "VIDEO") {
      if ((el.readyState || 0) < 2) continue; // 还没解出帧
      w = el.videoWidth || 0;
      h = el.videoHeight || 0;
    } else {
      // canvas 自带尺寸
      w = el.width || 0;
      h = el.height || 0;
    }
    if (w < MIN_MEDIA_W || h < MIN_MEDIA_H) continue;
    const area = w * h;
    if (!best || area > best.area) best = { el, area };
  }
  return best ? best.el : null;
}

// 媒体元素 → 降采样 JPEG base64；跨源污染/未解码时返回 null
function elToJpegBase64(el) {
  const w = el.naturalWidth || el.videoWidth || el.offsetWidth || 0;
  const h = el.naturalHeight || el.videoHeight || el.offsetHeight || 0;
  if (!w || !h) return null;
  const scale = Math.min(1, IMAGE_MAX_DIM / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * scale));
  c.height = Math.max(1, Math.round(h * scale));
  try {
    c.getContext("2d").drawImage(el, 0, 0, c.width, c.height);
    const dataUrl = c.toDataURL("image/jpeg", IMAGE_JPEG_QUALITY);
    return dataUrl.split(",")[1] || null;
  } catch (e) {
    return null; // 画布被跨源污染（如未解密的 mmg 缩略图）：跳过该图
  }
}

// 给每个 @我 上下文附带截图：滚动采集时已快照过（imageStash），
// 只对仍在 DOM 里的消息做 DOM 兜底；按「离 @我 消息的距离」从近到远取，内容指纹去重
function attachContextImages(contexts, imageStash) {
  let budget = MAX_IMAGES_PER_SCAN;
  const usedFingerprints = new Set();
  for (const ctx of contexts) {
    ctx.images = [];
    const ordered = ctx.messages
      .map((m, i) => ({ id: m.id, dist: Math.abs(i - ctx.mentionIndex) }))
      .sort((a, b) => a.dist - b.dist);
    for (const { id } of ordered) {
      if (ctx.images.length >= MAX_IMAGES_PER_CONTEXT || budget <= 0) break;
      let img = imageStash.get(id) || null;
      if (!img) {
        const el = pickMediaEl(domNodeForMessage(id));
        if (el) {
          const dataBase64 = elToJpegBase64(el);
          if (dataBase64) img = { mime: "image/jpeg", dataBase64 };
        }
      }
      if (!img) continue;
      // 同一张图在不同滚动位置的快照内容一致：用 base64 尾部指纹去重
      const fingerprint = img.dataBase64.slice(-64);
      if (usedFingerprints.has(fingerprint)) continue;
      usedFingerprints.add(fingerprint);
      ctx.images.push(img);
      budget--;
    }
  }
  return contexts;
}

async function scanCurrentConversation(selfName) {
  const groupName = currentGroupName();
  const { messages, imageStash } = await collectWithScrollUp(MAX_SCROLLS);
  const contexts = buildContextWindows(messages, selfName);
  attachContextImages(contexts, imageStash);
  return {
    groupName,
    messageCount: messages.length,
    mentionContexts: contexts,
    allMessages: messages.map((m) => ({
      sender: m.sender,
      timestamp: m.timestamp,
      text: m.text,
      mentionedNames: m.mentionedNames,
      isFromMe: m.isFromMe,
    })),
  };
}

function chatListItemsWithMentions() {
  const items = [...document.querySelectorAll(SELECTORS.chatListItem)];
  return items.filter((item) => {
    const badge = item.querySelector(SELECTORS.mentionBadge);
    if (badge) return true;
    const label = (item.getAttribute("aria-label") || "").toLowerCase();
    return label.includes("mention") || label.includes("提及");
  });
}

async function scanAllMentionedChats(selfName) {
  const conversations = [];
  const targets = chatListItemsWithMentions();
  for (const item of targets) {
    item.click();
    await sleep(900); // 等待会话加载
    conversations.push(await scanCurrentConversation(selfName));
  }
  return conversations;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "content:scan") return false;
  (async () => {
    try {
      const selfName = await getSelfName();
      const mode = msg.mode === "mentions" ? "mentions" : "current";
      const conversations =
        mode === "mentions"
          ? await scanAllMentionedChats(selfName)
          : [await scanCurrentConversation(selfName)];
      sendResponse({
        ok: true,
        data: {
          selfName,
          mode,
          scannedAt: new Date().toISOString(),
          conversations,
          diagnostics: {
            hasMainPanel: !!document.querySelector("#main"),
            chatListSize: document.querySelectorAll(SELECTORS.chatListItem).length,
            selfName,
            mentionHits: conversations.reduce(
              (s, c) => s + c.mentionContexts.length,
              0
            ),
            imagesCaptured: conversations.reduce(
              (s, c) =>
                s +
                c.mentionContexts.reduce(
                  (n, ctx) => n + ((ctx.images || []).length),
                  0
                ),
              0
            ),
          },
        },
      });
    } catch (e) {
      sendResponse({
        ok: false,
        error: `抓取失败：${e && e.message ? e.message : String(e)}（WhatsApp Web DOM 可能已变更）`,
      });
    }
  })();
  return true;
});
