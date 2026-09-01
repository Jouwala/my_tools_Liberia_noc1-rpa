// WhatsApp @Me Assistant - background service worker
// 职责：消息中转（content <-> sidepanel <-> 本地服务）、chrome.alarms 保活。
// 合规边界：只读取用户已登录的 WhatsApp Web 会话，不自动发送任何消息；
// 消息数据唯一外发路径是用户自行配置的本地服务中的 AI API。

const SERVER_URL_KEY = "wa_assistant_server_url";
const DEFAULT_SERVER_URL = "http://localhost:9268";
const KEEPALIVE_ALARM = "wa-assistant-keepalive";

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("[wa-assistant] setPanelBehavior failed", e));

chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEPALIVE_ALARM) {
    chrome.runtime.getPlatformInfo(() => {});
  }
});

async function getServerUrl() {
  const data = await chrome.storage.local.get(SERVER_URL_KEY);
  return data[SERVER_URL_KEY] || DEFAULT_SERVER_URL;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return false;

  switch (msg.type) {
    case "sidepanel:analyze": {
      // sidepanel -> background -> content（注入到 WhatsApp Web 的标签页）
      // 扫描数据直接回给 sidepanel，由 sidepanel 自己请求本地服务做 AI 分析
      forwardToWhatsAppTab({ type: "content:scan", mode: msg.mode }, sendResponse);
      return true;
    }
    case "sidepanel:serverUrl:get": {
      getServerUrl().then((url) => sendResponse({ url }));
      return true;
    }
    case "sidepanel:serverUrl:set": {
      chrome.storage.local
        .set({ [SERVER_URL_KEY]: msg.url })
        .then(() => sendResponse({ ok: true }));
      return true;
    }
    default:
      return false;
  }
});

async function forwardToWhatsAppTab(message, sendResponse) {
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  if (!tabs.length) {
    sendResponse({ ok: false, error: "未找到打开的 WhatsApp Web 标签页" });
    return;
  }
  try {
    const res = await chrome.tabs.sendMessage(tabs[0].id, message);
    sendResponse(res || { ok: true });
  } catch (e) {
    sendResponse({ ok: false, error: "无法与 WhatsApp Web 页面通信，请刷新页面后重试" });
  }
}
