// WhatsApp Image Sender - sidepanel 逻辑
// 与 background.js 的消息协议对齐：
//   config:get / config:set / send:now / poll:now / status:get
//   广播：sidepanel:progress / sidepanel:lastRun
//
// 定时发送的时间设置与 my_app sync 页面（/myapp/?page=sync）的调度编辑器一致：
// 5 段式 cron（分 时 日 月 周）+ 快捷预设 + 人性化预览。
// 预设与文案取自 frontend/src/pages/datasync/helpers.tsx 的 CRON_PRESETS / cronToHuman。

const $ = (id) => document.getElementById(id);

const CRON_PRESETS = [
  { label: "每小时", cron: "0 * * * *" },
  { label: "每2小时", cron: "0 */2 * * *" },
  { label: "每4小时", cron: "0 */4 * * *" },
  { label: "每6小时", cron: "0 */6 * * *" },
  { label: "每天 03:00", cron: "0 3 * * *" },
  { label: "每天 06:00", cron: "0 6 * * *" },
  { label: "每天 08:00", cron: "0 8 * * *" },
  { label: "每天 12:00", cron: "0 12 * * *" },
  { label: "每天 18:00", cron: "0 18 * * *" },
  { label: "工作日 08:00", cron: "0 8 * * 1-5" },
  { label: "工作日 18:00", cron: "0 18 * * 1-5" },
];

function cronToHuman(cron) {
  const parts = String(cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return "无效的 cron 表达式";
  const [min, hr, day, mon, dow] = parts;
  const pad = (s) => String(s).padStart(2, "0");
  if (hr.startsWith("*/")) {
    return `每 ${hr.slice(2)} 小时（第 ${min} 分钟）`;
  }
  if (hr === "*" && min !== "*") return `每小时第 ${min} 分钟`;
  if (hr === "*" && min === "*") return "每分钟";
  if (day === "*" && mon === "*" && dow === "*") return `每天 ${pad(hr)}:${pad(min)}`;
  if (dow !== "*") {
    const dowMap = { "1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "0": "周日", "1-5": "工作日" };
    return `${dowMap[dow] || dow} ${pad(hr)}:${pad(min)}`;
  }
  return cron;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeBaseUrl(url) {
  return String(url || "").trim().replace(/\/+$/, "") || "http://localhost";
}

function send(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      void chrome.runtime.lastError; // 消费错误，避免 SW 无监听时抛未处理异常
      resolve(resp || null);
    });
  });
}

// ---------- 配置 ----------
let savedCron = "";

function renderCronPresets(current) {
  const box = $("cron-presets");
  box.innerHTML = "";
  for (const p of CRON_PRESETS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "preset" + (p.cron === current ? " preset-active" : "");
    b.textContent = p.label;
    b.addEventListener("click", () => {
      $("inp-cron").value = p.cron;
      renderCronPreview();
      renderCronPresets(p.cron);
    });
    box.appendChild(b);
  }
}

function renderCronPreview() {
  const v = $("inp-cron").value.trim();
  const box = $("cron-preview");
  if (!v) { box.innerHTML = ""; return; }
  box.innerHTML = `预览：<span class="chip chip-ok">${escapeHtml(cronToHuman(v))}</span>`;
}

async function loadConfig() {
  const resp = await send({ type: "config:get" });
  const cfg = (resp && resp.cfg) || {};
  $("inp-server").value = cfg.server_url || "http://localhost";
  savedCron = cfg.cron || "0 3 * * *";
  $("inp-cron").value = savedCron;
  $("chk-enabled").checked = cfg.enabled !== false;
  $("cron-current").innerHTML =
    `当前调度：<span class="chip chip-info">${escapeHtml(cronToHuman(savedCron))}</span> ` +
    `<code class="mono-code">${escapeHtml(savedCron)}</code>`;
  renderCronPresets(savedCron);
  renderCronPreview();
}

async function saveConfig() {
  const cron = $("inp-cron").value.trim();
  if (!cron || cron.split(/\s+/).length !== 5) {
    $("save-hint").textContent = "cron 需为 5 段：分 时 日 月 周";
    return;
  }
  const cfg = {
    server_url: normalizeBaseUrl($("inp-server").value),
    cron,
    enabled: $("chk-enabled").checked,
  };
  const resp = await send({ type: "config:set", cfg });
  $("save-hint").textContent = resp && resp.ok ? "已保存" : "保存失败";
  setTimeout(() => { $("save-hint").textContent = ""; }, 2000);
  if (resp && resp.cfg) {
    savedCron = resp.cfg.cron;
    $("inp-server").value = resp.cfg.server_url;
    $("inp-cron").value = resp.cfg.cron;
    $("chk-enabled").checked = resp.cfg.enabled !== false;
    $("cron-current").innerHTML =
      `当前调度：<span class="chip chip-info">${escapeHtml(cronToHuman(savedCron))}</span> ` +
      `<code class="mono-code">${escapeHtml(savedCron)}</code>`;
    renderCronPresets(savedCron);
  }
  checkConnection();
}

// ---------- 后端连接检测 ----------
async function checkConnection() {
  const chip = $("conn-chip");
  const detail = $("conn-detail");
  chip.className = "chip chip-unknown";
  chip.textContent = "检测中…";
  detail.textContent = "";

  const resp = await send({ type: "config:get" });
  const base = normalizeBaseUrl((resp && resp.cfg && resp.cfg.server_url) || "");
  try {
    const res = await fetch(base + "/api/whatsapp/outbox");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    chip.className = "chip chip-ok";
    chip.textContent = "可连接";
    detail.textContent =
      `${base} · 群组 ${(data.groups || []).length} 个 · 图片 ${(data.items || []).length} 张`;
  } catch (e) {
    chip.className = "chip chip-bad";
    chip.textContent = "不可达";
    detail.textContent =
      `${base} 无法访问：${e.message}。请确认 my_app 后端已启动（与 /myapp 门户同一后端）。`;
  }
}

// ---------- 最近一次执行渲染 ----------
function renderLastRun(run) {
  const box = $("lastrun");
  if (!run) {
    box.innerHTML = '<div class="muted">尚无记录</div>';
    return;
  }
  const okAll = run.ok;
  const groupsSent = run.groups_sent || [];
  const errors = run.errors || [];
  const triggerText = run.trigger === "job"
    ? `后端作业 ${escapeHtml(run.job_id || "")}`
    : run.trigger === "schedule" ? "定时发送" : "手动发送";

  const rows = [];
  rows.push(`<div class="row"><span class="label">触发方式</span><span>${triggerText}</span></div>`);
  rows.push(`<div class="row"><span class="label">开始时间</span><span>${escapeHtml((run.started_at || "").replace("T", " ").slice(0, 19))}</span></div>`);
  rows.push(`<div class="row"><span class="label">结果</span><span class="${okAll ? "good" : "bad"}">${okAll ? "成功" : "失败/部分失败"}</span></div>`);
  if (groupsSent.length) {
    rows.push(`<div class="row"><span class="label">成功群组</span><span class="good">${groupsSent.map(escapeHtml).join(", ")}</span></div>`);
  }
  if (errors.length) {
    rows.push(
      `<div class="err-list">` +
      errors.map((e) => `<div class="err-item">· ${escapeHtml(e)}</div>`).join("") +
      `</div>`
    );
  }
  if (run.elapsed_seconds !== undefined && run.elapsed_seconds !== null) {
    rows.push(`<div class="row"><span class="label">耗时</span><span>${run.elapsed_seconds}s</span></div>`);
  }
  box.innerHTML = rows.join("");
}

async function refreshLastRun() {
  const resp = await send({ type: "status:get" });
  renderLastRun(resp && resp.lastRun);
}

// ---------- 操作 ----------
function setBusy(busy) {
  $("btn-send").disabled = busy;
  $("btn-poll").disabled = busy;
  $("btn-clear").disabled = busy;
  $("btn-diagnose").disabled = busy;
}

async function onSendNow() {
  setBusy(true);
  $("progress").textContent = "正在发送…";
  const run = await send({ type: "send:now" });
  $("progress").textContent = "";
  setBusy(false);
  renderLastRun(run);
}

async function onPollNow() {
  setBusy(true);
  $("progress").textContent = "正在向后端请求作业…";
  const resp = await send({ type: "poll:now" });
  $("progress").textContent = resp && resp.claimed ? "" : "当前没有待发作业";
  setBusy(false);
  await refreshLastRun();
  if (!(resp && resp.claimed)) {
    setTimeout(() => { $("progress").textContent = ""; }, 2500);
  }
}

async function onClearNow() {
  setBusy(true);
  $("progress").textContent = "正在清空 WhatsApp 输入框…";
  const resp = await send({ type: "clear:now" });
  setBusy(false);
  if (resp && resp.ok) {
    $("progress").textContent = `已清空（清理 ${resp.cleared || 0} 个输入框）`;
  } else {
    $("progress").textContent = `清空失败：${(resp && resp.error) || "无响应"}`;
  }
  setTimeout(() => { $("progress").textContent = ""; }, 3000);
}

async function onDiagnose() {
  setBusy(true);
  $("progress").textContent = "正在诊断 WhatsApp 页面…";
  const resp = await send({ type: "diagnose:now" });
  setBusy(false);
  $("progress").textContent = "";
  const box = $("diag-box");
  box.hidden = false;
  box.textContent = JSON.stringify(resp, null, 2);
}

// ---------- 广播 ----------
chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || typeof msg.type !== "string") return;
  if (msg.type === "sidepanel:lastRun") {
    renderLastRun(msg.data);
  } else if (msg.type === "sidepanel:progress") {
    const p = $("progress");
    if (msg.phase === "fetch-images") {
      p.textContent = `正在拉取 ${msg.count} 张图片…`;
    } else if (msg.phase === "sending") {
      p.textContent = `正在向 ${(msg.groups || []).length} 个群组发送 ${msg.images} 张图片…`;
    } else if (msg.phase === "done") {
      p.textContent = "";
      renderLastRun(msg.run);
    }
  }
});

// ---------- 初始化 ----------
document.addEventListener("DOMContentLoaded", () => {
  $("btn-save").addEventListener("click", saveConfig);
  $("btn-send").addEventListener("click", onSendNow);
  $("btn-poll").addEventListener("click", onPollNow);
  $("btn-clear").addEventListener("click", onClearNow);
  $("btn-diagnose").addEventListener("click", onDiagnose);
  $("btn-recheck").addEventListener("click", checkConnection);
  $("inp-cron").addEventListener("input", () => {
    renderCronPreview();
    renderCronPresets($("inp-cron").value.trim());
  });
  loadConfig();
  checkConnection();
  refreshLastRun();
});
