#!/usr/env node
// start-app.mjs -- orchestrate one or more my_app realtime proxies + the Vite frontend (7090).
// Reusable template for website-integrate-myapp. Extend PROXIES when a dashboard targets a
// DIFFERENT upstream host than the existing proxy (each host needs its own port + script).
//
// Usage:  node start-app.mjs            # preview (serves dist/)
//         node start-app.mjs --dev      # dev (serves public/ source)

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import http from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");              // my_app root
const TOOLS = path.join(ROOT, "tools");                  // 代理脚本源码（随 git 走）
const RUNTIME = path.join(ROOT, "scripts");              // venv 解释器 + spawn 的 cwd（运行目录）
const FRONTEND = path.join(ROOT, "frontend");

// ---- 代理解释器：必须与 backend/services/realtime_proxy_ctl.py::_find_python 保持一致 ----
// 2026-10-10 把系统 Python312 排到仓库 venv 之前。原因不是"venv 坏了"，而是 venv 的
// python.exe 是**重定向器**：它派生基础解释器作为真正执行代码的子进程，实测在听的两个代理
// （PID 50996 / 46704）镜像路径都是 C:\Users\ZTEEMS\.workbuddy\binaries\python\versions\
// 3.13.12\python.exe —— 于是这两个代理在进程谱系上算 WorkBuddy 的，任何按镜像路径清理
// WorkBuddy python 的动作会把 8787/8790 **成对**带走（完整经过见 realtime_proxy_ctl.py
// 里 2026-10-10 的注释，以及 stop.bat:55-58 那条 2026-09-04 的同类事故记录）。
// 代理只需要 stdlib + cryptography，Python312 完全够用（那个 venv 反倒缺 requests/urllib3）。
// 判定用 import 探测，不用"文件存在"：后者会拉起一个"能启动、一跑就 ImportError"的进程，
// 端口永远不起来，只在 console.log 里留一行，排障时最容易被误判成上游问题。
const PY_PROBE = "import cryptography, ssl, http.server, urllib.request";
function resolveProxyPython() {
  const cands = [
    (process.env.MY_APP_PROXY_PY || "").trim(),
    "C:\\Users\\ZTEEMS\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
    path.join(RUNTIME, "python.exe"),
    "python.exe",
  ].filter(Boolean);
  for (const exe of cands) {
    if (exe !== "python.exe" && !existsSync(exe)) continue;
    const r = spawnSync(exe, ["-c", PY_PROBE], { timeout: 15000, windowsHide: true });
    if (r.status === 0) return exe;
    console.warn(`[proxy] interpreter unusable (import probe failed): ${exe}`);
  }
  console.warn("[proxy] no verified interpreter, falling back to PATH python.exe");
  return "python.exe";
}
const PY = resolveProxyPython();
const VITE_PORT = 7090;
const isDev = process.argv.includes("--dev");

// One entry PER upstream host. The existing FMS proxy (8787) must NOT be reused for a
// different portal (e.g. VMAX) -- add a new entry with its own port + script instead.
const PROXIES = [
  { port: 8787, script: "realtime_proxy.py",      label: "FMS",  requireAuth: false },
  { port: 8790, script: "realtime_proxy_vmax.py", label: "VMAX", requireAuth: true  },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Free a port on Windows. `netstat -ano` prints the PID AFTER "LISTENING"
// (e.g. "... LISTENING       12356"), so the regex must be /LISTENING\s+(\d+)/i.
function killPort(port) {
  return new Promise((resolve) => {
    const cmd = spawn("cmd", ["/c",
      `for /f "tokens=5" %a in ('netstat -ano ^| findstr ":${port}" ^| findstr "LISTENING"') do taskkill /PID %a /F`],
      { shell: true, stdio: "ignore" });
    cmd.on("exit", () => resolve());
  });
}

function healthCheck(port, requireAuth = false) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port, path: "/health", timeout: 1500 }, (res) => {
      let b = ""; res.on("data", (c) => (b += c));
      res.on("end", () => {
        try {
          const j = JSON.parse(b);
          if (j.status !== "ok" || j.proxy !== "ready") return resolve(false);
          // For session-gated portals the proxy self-reports auth so we don't accidentally
          // reuse a half-dead instance whose upstream session has expired.
          return resolve(requireAuth ? j.auth === true : true);
        } catch { resolve(false); }
      });
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
}

const procs = [];
async function ensureProxy(cfg) {
  if (await healthCheck(cfg.port, cfg.requireAuth)) {
    console.log(`[proxy:${cfg.label}] reuse existing healthy instance on ${cfg.port}`);
    return;
  }
  await killPort(cfg.port);                 // clear zombie if port held but unhealthy
  await sleep(800);
  if (!existsSync(path.join(TOOLS, cfg.script))) {
    console.warn(`[proxy:${cfg.label}] script ${cfg.script} missing -- SKIP (dashboard on ${cfg.port} will be offline)`);
    return;
  }
  // 脚本在 tools/（随 git 走）；cwd 仍是 scripts/（运行目录，会话文件由脚本按
  // dirname(__file__) 决定，落在 tools/，与 cwd 无关）。解释器由 resolveProxyPython()
  // 探测选出，不再固定是 scripts/ 的 venv —— 见该函数上方 2026-10-10 的注释。
  const p = spawn(PY, [path.join(TOOLS, cfg.script)], { cwd: RUNTIME, shell: true, stdio: ["ignore", "ignore", "ignore"] });
  procs.push(p);
  for (let i = 0; i < 15; i++) {
    if (await healthCheck(cfg.port, cfg.requireAuth)) {
      console.log(`[proxy:${cfg.label}] started & healthy on ${cfg.port}`);
      return;
    }
    await sleep(1000);
  }
  console.error(`[proxy:${cfg.label}] did not become healthy -- check tools/ + scripts/venv + log`);
}

function startVite() {
  const script = isDev ? "dev" : "preview";
  return spawn("npx", ["vite", script], { cwd: FRONTEND, shell: true, stdio: "inherit" });
}

async function main() {
  // PY 可能是裸 "python.exe"（PATH 兜底，此时 existsSync 必然为 false），
  // 所以只在"给了具体路径却不存在"时硬失败。
  console.log(`[proxy] interpreter: ${PY}`);
  if (PY.includes("\\") || PY.includes("/")) {
    if (!existsSync(PY)) { console.error("python not found at", PY); process.exit(1); }
  }
  for (const cfg of PROXIES) await ensureProxy(cfg);
  const viteProc = startVite();
  const shutdown = () => {
    console.log("\n[stop] shutting down...");
    for (const p of procs) p.kill("SIGTERM");
    if (viteProc) viteProc.kill("SIGTERM");
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main();
