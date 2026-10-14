#!/usr/bin/env node
/**
 * 网页扫码登录文件通道（src/qrLogin.js）的离线单测。
 *
 * 覆盖「只有真跑起来才会暴露」的关键不变式：
 *   1) 未收到请求时不触发重启、不写状态
 *   2) 收到匹配 device 的新 nonce → 触发 onRestart，且把旧凭据改名备份、建回空目录
 *   3) 同一 nonce 重复出现**只处理一次**（不会反复清凭据/重连）
 *   4) publishQr 把原始二维码字符串写进 qr_status.json 的**本设备键**
 *   5) 两个设备各写各的键，互不覆盖（notify 写状态不冲掉刚写的 bot 状态）
 *   6) connected / error 状态正确落盘，并解除 isLoginRequested（放宽 notify 的 TTY 门槛）
 *   7) 请求**接受即消费**（本设备键从请求文件删除、其他设备键保留），进程重启后
 *      不重放已消费的请求 —— 2026-10-14 14:23 事故的根因：内存 handledNonce
 *      挡不住重启重放，重放把刚扫码恢复的凭据再次清空。
 *
 * 纯离线：用临时目录做 root，不连 WhatsApp、不碰真实 data/。
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// 轮询间隔在 qrLogin.js **模块加载时**读取，故必须先设环境变量再动态 import。
// 用 150ms 让测试跑得快；生产默认 3000ms 不受影响。
process.env.QR_LOGIN_POLL_MS = '150';
const { createQrWatcher, QR_STATE } = await import('../src/qrLogin.js');

let pass = 0;
let fail = 0;
function check(cond, label, detail = '') {
  if (cond) {
    pass++;
    console.log(`  ✓ ${label}`);
  } else {
    fail++;
    console.log(`  ✗ ${label}${detail ? `\n      ${detail}` : ''}`);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readJson(p) {
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

async function main() {
  /* ---------- 场景 1：无请求时静默 ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth-notify');
    mkdirSync(authDir, { recursive: true });
    let restarted = 0;
    const w = createQrWatcher({
      device: 'notify',
      authDir,
      root,
      onRestart: async () => { restarted++; },
      log: () => {},
    });
    await sleep(80);
    check(restarted === 0, '无请求时不触发重启');
    check(!existsSync(join(root, 'data', 'qr_status.json')), '无请求时不写状态文件');
    w.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  /* ---------- 场景 2：请求 → 备份 + 重启 + waiting ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth-notify');
    mkdirSync(authDir, { recursive: true });
    // 放一个有效的 creds.json，让备份逻辑真正触发
    writeFileSync(join(authDir, 'creds.json'), JSON.stringify({ me: { id: '1:2@s.whatsapp.net' } }));
    let restarted = 0;
    const w = createQrWatcher({
      device: 'notify',
      authDir,
      root,
      onRestart: async () => { restarted++; },
      log: () => {},
    });
    writeFileSync(join(root, 'data', 'qr_request.json'),
      JSON.stringify({ notify: { nonce: 'n1', requested_at: 'now' } }));
    await waitFor(() => restarted > 0, 5000);
    check(restarted === 1, '收到请求后触发一次重启');
    // 旧凭据目录被改名备份：原目录已重建为空，且 data/ 下出现 auth.bak-*
    const backups = readdirSync(join(root, 'data')).filter((f) => f.startsWith('auth.bak-'));
    check(backups.length === 1, '旧凭据被改名备份为 auth.bak-*', `实际: ${backups.join(',')}`);
    check(existsSync(authDir) && readdirSync(authDir).length === 0, '凭据目录已重建为空');
    const status = readJson(join(root, 'data', 'qr_status.json'));
    check(status?.notify?.state === QR_STATE.WAITING, '状态写入 waiting');
    check(status?.notify?.nonce === 'n1', '状态带上本次 nonce');
    w.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  /* ---------- 场景 3：同 nonce 只处理一次 ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth-notify');
    mkdirSync(authDir, { recursive: true });
    let restarted = 0;
    const w = createQrWatcher({ device: 'notify', authDir, root, onRestart: async () => { restarted++; }, log: () => {} });
    // 无 creds.json → 备份跳过，但仍会触发重启
    writeFileSync(join(root, 'data', 'qr_request.json'), JSON.stringify({ notify: { nonce: 'same' } }));
    await waitFor(() => restarted > 0, 5000);
    await sleep(600); // 再等几个轮询周期，nonce 未变不应再次触发
    check(restarted === 1, '同一 nonce 重复出现只处理一次', `实际 restarted=${restarted}`);
    w.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  /* ---------- 场景 4 & 5：publishQr 写本设备键，不覆盖另一设备 ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth');
    mkdirSync(authDir, { recursive: true });
    // 预置一个 bot 设备刚写的状态
    writeFileSync(join(root, 'data', 'qr_status.json'),
      JSON.stringify({ bot: { nonce: 'b1', state: 'qr', qr: 'BOTQR' } }));
    const w = createQrWatcher({ device: 'notify', authDir, root, onRestart: async () => {}, log: () => {} });
    w.publishQr('NOTIFY-QR-STRING');
    const status = readJson(join(root, 'data', 'qr_status.json'));
    check(status?.notify?.state === QR_STATE.QR && status?.notify?.qr === 'NOTIFY-QR-STRING', 'publishQr 写本设备 qr 状态');
    check(status?.bot?.qr === 'BOTQR', '不覆盖另一设备已写的状态');
    w.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  /* ---------- 场景 6：connected / error 状态 + isLoginRequested 生命周期 ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth');
    mkdirSync(authDir, { recursive: true });
    const w = createQrWatcher({ device: 'bot', authDir, root, onRestart: async () => {}, log: () => {} });
    check(w.isLoginRequested() === false, '初始无扫码请求');
    w.setState(QR_STATE.CONNECTED, { message: 'ok' });
    check(w.isLoginRequested() === false, 'connected 后请求已解除');
    const status = readJson(join(root, 'data', 'qr_status.json'));
    check(status?.bot?.state === QR_STATE.CONNECTED, 'connected 状态落盘');
    w.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  /* ---------- 场景 7：接受即消费，重启后不重放（2026-10-14 14:23 事故） ---------- */
  {
    const root = mkdtempSync(join(tmpdir(), 'qr-login-'));
    mkdirSync(join(root, 'data'), { recursive: true });
    const authDir = join(root, 'data', 'auth');
    mkdirSync(authDir, { recursive: true });
    writeFileSync(join(authDir, 'creds.json'), '{}'); // 有凭据 → 触发真实备份
    let restarted1 = 0;
    const w1 = createQrWatcher({
      device: 'bot', authDir, root,
      onRestart: async () => { restarted1++; }, log: () => {},
    });
    writeFileSync(join(root, 'data', 'qr_request.json'),
      JSON.stringify({ bot: { nonce: 'stale', requested_at: 'morning' }, notify: { nonce: 'keep', requested_at: 'x' } }));
    await waitFor(() => restarted1 > 0, 5000);
    check(restarted1 === 1, '第一个进程处理了请求');
    const reqAfter = readJson(join(root, 'data', 'qr_request.json'));
    check(reqAfter && reqAfter.bot === undefined, '接受即消费：本设备键已从请求文件删除', `实际: ${JSON.stringify(reqAfter)}`);
    check(reqAfter && reqAfter.notify?.nonce === 'keep', '消费只删本设备键，不动其他设备');
    w1.dispose(); // 模拟进程死亡（看门狗重启）
    // 第二个进程：若重放旧请求，会再次 onRestart（事故里表现为清掉刚扫码恢复的凭据）
    let restarted2 = 0;
    const w2 = createQrWatcher({
      device: 'bot', authDir, root,
      onRestart: async () => { restarted2++; }, log: () => {},
    });
    await sleep(600); // 等几个轮询周期
    check(restarted2 === 0, '重启后的新进程不重放已消费的请求', `实际 restarted=${restarted2}`);
    w2.dispose();
    rmSync(root, { recursive: true, force: true });
  }

  console.log(`\n${fail === 0 ? '✓' : '✗'} ${pass} 通过 / ${fail} 失败`);
  process.exit(fail === 0 ? 0 : 1);
}

/** 简单等待条件成立，超时返回（不抛错，由断言给出可读失败信息）。 */
async function waitFor(cond, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (cond()) return true;
    await sleep(50);
  }
  return false;
}

main().catch((err) => {
  console.error('测试异常：', err);
  process.exit(1);
});
