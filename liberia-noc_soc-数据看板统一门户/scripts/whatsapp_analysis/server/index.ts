import "dotenv/config";
import express from "express";
import { createReadStream, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createAdapter } from "./ai/adapter";
import { analyze } from "./analyzer";
import { generateDailyReport } from "./reports";
import { startScheduler } from "./scheduler";
import {
  ATTACH_DIR,
  addAttachment,
  deleteAttachment,
  getAttachment,
  getTask,
  latestReport,
  listAttachments,
  listTasks,
  setTaskStatus,
  updateTaskResult,
} from "./storage";

const PORT = Number(process.env.PORT || 9268);
const adapter = createAdapter();

const app = express();
// 40mb：文本 + 随附聊天截图（base64，扩展端已降采样，单图约 100-400KB）
app.use(express.json({ limit: "40mb" }));

// CORS：本地分析服务，允许 Chrome 扩展与门户页面（可能部署在其它主机）访问
app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", req.headers.origin || "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

const ENDPOINTS = [
  "GET   /api/health",
  "POST  /api/analyze",
  "GET   /api/tasks",
  "PATCH /api/tasks/:id",
  "POST  /api/tasks/:id/attachments",
  "GET   /api/attachments/:id",
  "DELETE /api/attachments/:id",
  "POST  /api/report/generate",
  "GET   /api/reports/latest",
];

app.get("/", (req, res) => {
  if ((req.headers.accept || "").includes("text/html")) {
    const aiState = adapter.configured ? "已配置" : "未配置（规则降级模式）";
    return res.type("html").send(`<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>WhatsApp @Me Assistant</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:48px 16px}
  .box{max-width:640px;margin:0 auto;background:#1e293b;border:1px solid #334155;border-radius:12px;padding:28px 32px}
  h1{font-size:20px;margin:0 0 4px}
  .ok{color:#4ade80}
  h2{font-size:14px;color:#94a3b8;margin:24px 0 8px}
  li{margin:4px 0;line-height:1.6}
  code{background:#0f172a;border:1px solid #334155;border-radius:4px;padding:1px 6px;font-size:12px}
  p{line-height:1.7}
</style>
</head>
<body>
<div class="box">
  <h1>WhatsApp @Me Assistant <span class="ok">● 运行中</span></h1>
  <p>本地分析服务正常。这是<b>后端 API 服务</b>，没有独立页面界面；待办界面在：</p>
  <ul>
    <li>数据看板门户 → 视图切换按钮「WhatsApp @我 待办」</li>
    <li>Chrome 扩展 → WhatsApp Web 侧边栏面板</li>
  </ul>
  <h2>状态</h2>
  <ul>
    <li>AI 适配器：<code>${adapter.name}</code>（${aiState}）</li>
    <li>数据仅存本地，唯一外发路径为 .env 配置的 AI API</li>
  </ul>
  <h2>API 端点</h2>
  <ul>${ENDPOINTS.map((e) => `<li><code>${e}</code></li>`).join("")}</ul>
</div>
</body>
</html>`);
  }
  res.json({
    service: "WhatsApp @Me Assistant 本地分析服务",
    ok: true,
    ai: adapter.name,
    aiConfigured: adapter.configured,
    endpoints: ENDPOINTS,
  });
});

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, ai: adapter.name, aiConfigured: adapter.configured });
});

app.post("/api/analyze", async (req, res) => {
  try {
    const scan = req.body;
    if (!scan || !Array.isArray(scan.conversations)) {
      return res.status(400).json({ error: "请求体必须包含 conversations 数组" });
    }
    const t0 = Date.now();
    const imageCount = ((scan.conversations || []) as unknown[]).reduce(
      (n: number, c) =>
        n +
        (((c as { mentionContexts?: { images?: unknown[] }[] })
          .mentionContexts || []) as unknown[]).reduce(
          (m: number, ctx) =>
            m + (((ctx as { images?: unknown[] }).images || []).length),
          0
        ),
      0
    );
    console.log(
      `[analyze] 收到扫描：${scan.conversations.length} 个会话，mode=${scan.mode || "?"}，随附截图=${imageCount} 张`
    );
    const out = await analyze(scan, adapter);
    console.log(
      `[analyze] 完成，耗时 ${((Date.now() - t0) / 1000).toFixed(1)}s，tasks=${out.tasks.length}，degraded=${!!out.degraded}`
    );
    res.json(out.degraded && !out.tasks.length
      ? { degraded: true, reason: out.reason, scanResult: scan }
      : out.degraded
        ? { degraded: true, reason: out.reason, tasks: out.tasks }
        : { degraded: false, tasks: out.tasks });
  } catch (e) {
    console.error("[analyze] failed:", e);
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/tasks", (req, res) => {
  const { status, since, limit } = req.query as Record<string, string | undefined>;
  const tasks = listTasks({ status, since, limit: limit ? Number(limit) : undefined });
  res.json({
    tasks: tasks.map((t) => ({ ...t, attachments: listAttachments(t.id) })),
  });
});

app.patch("/api/tasks/:id", (req, res) => {
  const id = Number(req.params.id);
  const { status, my_result } = (req.body || {}) as {
    status?: string;
    my_result?: string;
  };
  if (status && !["pending", "done", "dismissed"].includes(status)) {
    return res.status(400).json({ error: "status 必须是 pending/done/dismissed" });
  }
  if (!status && typeof my_result !== "string") {
    return res.status(400).json({ error: "需要 status 或 my_result" });
  }
  let task = getTask(id);
  if (!task) return res.status(404).json({ error: "任务不存在" });
  if (typeof my_result === "string") task = updateTaskResult(id, my_result);
  if (status) task = setTaskStatus(id, status as "pending" | "done" | "dismissed");
  res.json({ task });
});

app.post("/api/tasks/:id/attachments", (req, res) => {
  const id = Number(req.params.id);
  if (!getTask(id)) return res.status(404).json({ error: "任务不存在" });
  const { filename, mime, dataBase64 } = (req.body || {}) as {
    filename?: string;
    mime?: string;
    dataBase64?: string;
  };
  if (!filename || typeof dataBase64 !== "string") {
    return res.status(400).json({ error: "需要 filename 和 dataBase64" });
  }
  const buf = Buffer.from(dataBase64, "base64");
  if (!buf.length) return res.status(400).json({ error: "文件为空" });
  if (buf.length > 16 * 1024 * 1024) {
    return res.status(400).json({ error: "单个文件不能超过 16MB" });
  }
  const safe =
    path
      .basename(filename)
      .replace(/[^\w.\-()（）\u4e00-\u9fa5]+/g, "_")
      .slice(0, 80) || "file";
  const storedName = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}_${safe}`;
  writeFileSync(path.join(ATTACH_DIR, storedName), buf);
  const attachment = addAttachment(
    id,
    path.basename(filename),
    mime || "application/octet-stream",
    buf.length,
    storedName
  );
  res.json({ attachment });
});

app.get("/api/attachments/:id", (req, res) => {
  const att = getAttachment(Number(req.params.id));
  if (!att) return res.status(404).json({ error: "附件不存在" });
  res.setHeader("Content-Type", att.mime);
  res.setHeader(
    "Content-Disposition",
    `inline; filename*=UTF-8''${encodeURIComponent(att.filename)}`
  );
  createReadStream(path.join(ATTACH_DIR, att.stored_name)).pipe(res);
});

app.delete("/api/attachments/:id", (req, res) => {
  const att = getAttachment(Number(req.params.id));
  if (!att) return res.status(404).json({ error: "附件不存在" });
  deleteAttachment(att.id);
  try {
    unlinkSync(path.join(ATTACH_DIR, att.stored_name));
  } catch {
    // 磁盘文件缺失不影响删除记录
  }
  res.json({ ok: true });
});

app.post("/api/report/generate", async (_req, res) => {
  try {
    const report = generateDailyReport();
    res.json({ ok: true, report_date: report.report_date, markdown: report.markdown });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/reports/latest", (_req, res) => {
  const report = latestReport();
  if (!report) return res.json({ report: null });
  res.json({ report });
});

app.listen(PORT, () => {
  console.log(`[wa-assistant] server listening on http://localhost:${PORT}`);
  console.log(`[wa-assistant] AI adapter: ${adapter.name} (configured=${adapter.configured})`);
  startScheduler(() => generateDailyReport());
});

// 供 CLI/测试复用
export { getTask };
