#!/usr/env node
// start-app.mjs -- orchestrate one or more my_app realtime proxies + the Vite frontend (7090).
// Reusable template for website-integrate-myapp. Extend PROXIES when a dashboard targets a
// DIFFERENT upstream host than the existing proxy (each host needs its own port + script).
//
// Usage:  node start-app.mjs            # preview (serves dist/)
//         node start-app.mjs --dev      # dev (serves public/ source)

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import http from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");              // my_app root
const TOOLS = path.join(ROOT, "tools");                  // 代理脚本源码（随 git 走）
const RUNTIME = path.join(ROOT, "scripts");              // venv 解释器 + 运行目录
const FRONTEND = path.join(ROOT, "frontend");
const PY = path.join(RUNTIME, "python.exe");             // bundled/venv python
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
  // 脚本在 tools/，解释器与 cwd 在 scripts/（venv）。会话文件由脚本按
  // dirname(__file__) 决定，随脚本落在 tools/。
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
  if (!existsSync(PY)) { console.error("python not found at", PY); process.exit(1); }
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
