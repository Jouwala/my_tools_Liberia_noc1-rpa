#!/usr/bin/env node
/**
 * start-wa-service.mjs - make `npm run dev` self-sufficient.
 *
 * Wired as the "predev" script in package.json, so it runs automatically before
 * `vite --port=9267`. It makes sure the WhatsApp local analysis service
 * (scripts/whatsapp_analysis, port 9268) is up, because the portal page calls it
 * directly from the browser and shows "cannot connect to the local analysis
 * service" whenever it is down.
 *
 * Design notes:
 *  - always exits 0 and never waits, so `npm run dev` can never be blocked;
 *  - if 9268 is already listening it does nothing (no duplicate instance);
 *  - the service is spawned detached + unref'd so it survives the npm process:
 *    Ctrl+C on `npm run dev` leaves it running, and stop.bat kills it by port;
 *  - deliberately uses the local tsx CLI instead of "npm start": spawning npm
 *    from inside npm on Windows needs a shell and is easy to get wrong.
 */
import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const portalRoot = path.resolve(here, '..');
const waDir = path.join(portalRoot, 'scripts', 'whatsapp_analysis');
const logDir = path.join(portalRoot, 'log');
const port = Number(process.env.WA_PORT || 9268);

/** Resolves true when something is already accepting connections on 127.0.0.1:port. */
function isListening(p) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: '127.0.0.1', port: p });
    const done = (v) => {
      socket.destroy();
      resolve(v);
    };
    socket.setTimeout(800);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

if (await isListening(port)) {
  console.log(`[predev] WhatsApp analysis service already listening on ${port}.`);
  process.exit(0);
}

if (!fs.existsSync(waDir)) {
  console.warn(`[predev] ${waDir} not found - skipping WhatsApp analysis service.`);
  process.exit(0);
}

const tsxCli = path.join(waDir, 'node_modules', 'tsx', 'dist', 'cli.mjs');
if (!fs.existsSync(tsxCli)) {
  console.warn(`[predev] tsx not installed in scripts/whatsapp_analysis - run "npm install" there. Skipping.`);
  process.exit(0);
}

fs.mkdirSync(logDir, { recursive: true });
const outFd = fs.openSync(path.join(logDir, 'whatsapp_analysis.log'), 'a');
const errFd = fs.openSync(path.join(logDir, 'whatsapp_analysis.log.err'), 'a');

const child = spawn(process.execPath, [tsxCli, 'server/index.ts'], {
  cwd: waDir,
  detached: true,
  stdio: ['ignore', outFd, errFd],
  windowsHide: true,
});
child.unref();

console.log(
  `[predev] WhatsApp analysis service starting on ${port} (pid ${child.pid}), log: log/whatsapp_analysis.log`,
);
process.exit(0);
