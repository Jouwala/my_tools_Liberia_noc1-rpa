const $ = (sel) => document.querySelector(sel);

const PRIORITY_META = {
  urgent: { label: "🔴 紧急", cls: "urgent" },
  followup: { label: "🟡 待跟进", cls: "followup" },
  fyi: { label: "🟢 FYI", cls: "fyi" },
};

function setStatus(text) {
  $("#status").textContent = text || "";
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderTasks(payload) {
  const root = $("#results");
  if (payload.degraded) {
    const convs = (payload.scanResult && payload.scanResult.conversations) || [];
    root.innerHTML =
      `<div class="warn">⚠ ${escapeHtml(payload.reason)}</div>` +
      convs
        .map((c) => renderRawConversation(c))
        .join("");
    return;
  }
  const tasks = payload.tasks || [];
  if (!tasks.length) {
    root.innerHTML = `<div class="empty">未发现 @我 的待办事项</div>`;
    return;
  }
  const groups = ["urgent", "followup", "fyi"];
  root.innerHTML = groups
    .map((g) => {
      const list = tasks.filter((t) => (t.priority || "fyi") === g);
      if (!list.length) return "";
      return (
        `<div class="section-title">${PRIORITY_META[g].label}（${list.length}）</div>` +
        list.map(renderTaskCard).join("")
      );
    })
    .join("");
  bindCardActions();
}

// 固定输出格式：9 个字段、顺序不变；未找到的照常显示标签、值留空
const FIXED_FIELDS = [
  ["Requester", (t) => t.requester],
  ["MessageTime", (t) => t.message_time],
  ["SiteID", (t) => t.site_id],
  ["SiteName", (t) => t.site_name],
  ["TT_ID", (t) => t.tt_id],
  ["Alarm_Name", (t) => t.alarm_name],
  ["Group", (t) => t.group_name],
  ["Issue", (t) => t.issue],
  ["Deadline", (t) => t.deadline],
];

function renderTaskCard(t) {
  const meta = PRIORITY_META[t.priority] || PRIORITY_META.fyi;
  const done = t.status === "done";
  const head = [t.site_name, t.site_id].filter(Boolean).join(" / ") || "任务";
  const rows = FIXED_FIELDS.map(
    ([label, get]) =>
      `<div class="row"><b>${label}:</b>${escapeHtml(get(t) || "")}</div>`
  ).join("");
  return `
    <div class="card ${done ? "done" : ""}" data-task-id="${t.id}">
      <div class="head">
        <span class="site">${escapeHtml(head)}</span>
        <span class="badge ${meta.cls}">${meta.label}</span>
      </div>
      ${rows}
      ${
        done
          ? ""
          : `<div class="actions">
              <button data-action="done">标记完成</button>
              <button data-action="dismiss" class="secondary">忽略</button>
            </div>`
      }
    </div>`;
}

function renderRawConversation(c) {
  const hits = (c.mentionContexts || []).length;
  const lines = (c.allMessages || [])
    .slice(-30)
    .map((m) => `[${m.timestamp || ""}] ${m.sender || "?"}: ${m.text}`)
    .join("\n");
  return `
    <div class="section-title">${escapeHtml(c.groupName)}（${c.messageCount} 条，@我 ${hits} 处）</div>
    <div class="raw">${escapeHtml(lines) || "(空)"}</div>`;
}

let serverUrl = "http://localhost:9268";
let waitTimer = null;

function startWaitTimer(prefix) {
  stopWaitTimer();
  const t0 = Date.now();
  const head = prefix ? prefix + " · " : "";
  waitTimer = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    setStatus(
      head +
        `AI 分析中… 已等待 ${s} 秒` +
        (s > 120 ? "（时间较长，若持续无结果请查看服务终端日志）" : "")
    );
  }, 1000);
}

function stopWaitTimer() {
  if (waitTimer) {
    clearInterval(waitTimer);
    waitTimer = null;
  }
}

function loadServerUrl() {
  chrome.runtime.sendMessage({ type: "sidepanel:serverUrl:get" }, (res) => {
    if (res && res.url) serverUrl = res.url;
  });
}

const SELF_NAME_KEY = "wa_assistant_self_name";

function loadSelfName() {
  chrome.storage.local.get(SELF_NAME_KEY, (data) => {
    const input = $("#self-name");
    if (input) input.value = data[SELF_NAME_KEY] || "";
  });
}

function bindSettings() {
  $("#btn-save-name").addEventListener("click", () => {
    const value = ($("#self-name").value || "").trim();
    if (value) {
      chrome.storage.local.set({ [SELF_NAME_KEY]: value }, () =>
        setStatus(`已保存我的名字：${value}`)
      );
    } else {
      chrome.storage.local.remove(SELF_NAME_KEY, () =>
        setStatus("已清除名字，下次扫描将自动检测")
      );
    }
  });
}

async function patchTask(id, status) {
  const res = await fetch(serverUrl + "/api/tasks/" + id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error("更新失败: " + res.status);
}

function bindCardActions() {
  document.querySelectorAll(".card button[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const id = card.dataset.taskId;
      const status = btn.dataset.action === "done" ? "done" : "dismissed";
      try {
        await patchTask(id, status);
        if (status === "done") {
          card.classList.add("done");
          btn.closest(".actions").remove();
        } else {
          card.remove();
        }
      } catch (e) {
        setStatus("本地服务不可达，无法更新任务状态");
      }
    });
  });
}

async function analyze(mode) {
  setStatus("正在扫描 WhatsApp Web…");
  $("#results").innerHTML = `<div class="empty">扫描中…</div>`;
  chrome.runtime.sendMessage({ type: "sidepanel:analyze", mode }, async (res) => {
    if (chrome.runtime.lastError) {
      stopWaitTimer();
      setStatus("通信失败：" + chrome.runtime.lastError.message);
      return;
    }
    if (res && res.ok === false) {
      stopWaitTimer();
      setStatus(res.error || "扫描失败");
      $("#results").innerHTML = `<div class="empty">${escapeHtml(res.error || "扫描失败")}</div>`;
      return;
    }
    const d = (res.data && res.data.diagnostics) || {};
    const imgInfo = d.imagesCaptured ? `，截图 ${d.imagesCaptured} 张` : "，未捕获截图";
    const info = `扫描完成：我的名字=${d.selfName || "(未检测)"}，@我 ${d.mentionHits ?? 0} 处${imgInfo}`;
    setStatus(info + "，AI 分析中…");
    startWaitTimer(info);
    if (!res.data.selfName) {
      stopWaitTimer();
      renderTasks({
        degraded: true,
        reason:
          "未检测到“我的名字”，无法匹配 @提及。请在上方设置中填写你在 WhatsApp 里的名字后重新扫描。",
        scanResult: res.data,
      });
      return;
    }
    try {
      const r = await fetch(serverUrl + "/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(res.data),
      });
      const data = await r.json();
      stopWaitTimer();
      setStatus(info + ` · 分析完成 ${new Date().toLocaleTimeString()}`);
      renderTasks(data);
    } catch (e) {
      stopWaitTimer();
      renderTasks({
        degraded: true,
        reason: `本地分析服务不可达（${serverUrl}）。请先启动 server，以下为原始抓取结果。`,
        scanResult: res.data,
      });
    }
  });
}

$("#btn-current").addEventListener("click", () => analyze("current"));
$("#btn-mentions").addEventListener("click", () => analyze("mentions"));

loadServerUrl();
loadSelfName();
bindSettings();
