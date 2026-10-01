/**
 * P1 告警推送守护进程（Baileys，无浏览器、无 Ollama、无 RAG）。
 *
 * ## 为什么单独一个入口，而不并进 index.js
 *
 * `src/index.js` 是「知识库问答机器人」的入口，它的启动路径上有三道硬门槛，
 * 任一不过就 `process.exit(1)`：
 *
 *   1. `validateProvider()` —— 云端对话 provider 的 key
 *   2. `healthCheck()`      —— **本地 Ollama 必须在跑**，且 `bge-m3` 已拉取
 *   3. `loadIndex()`        —— 知识库索引文件
 *
 * 而**推送一条文本告警，这三样一个都不需要** —— `sock.sendMessage()` 只走
 * WhatsApp 的 WebSocket 协议，不碰模型、不碰索引。
 *
 * 2026-10-01 实测：Ollama 没在跑，于是 `index.js` 直接退出，整个机器人（连带
 * 本该能用的发送能力）一起没了。若把 P1 告警接在那种入口上，**Ollama 一挂就等于
 * 告警通道全断** —— 用一个无关依赖的可用性，去赌告警的可用性，这是不能接受的。
 *
 * 故本文件**只 import 凭据与连接**（`baileys` + `config.js`），刻意不 import
 * `rag.js` / `llm.js` / `ollama.js` / `answer.js`。启动路径只有：
 *
 *   读 creds.json → 连接 → 轮询信箱 → sendMessage → 回写结果
 *
 * ## 与 Chrome 扩展通道的关系
 *
 * 2026-10-01 起，P1 告警的发送通道**由扩展切换为本进程**。切换原因：
 * 扩展要操作 WhatsApp Web 页面，因而依赖「浏览器开着 + 页面聚焦 + 每 2~3 周人工扫码」，
 * 且发送确认只能靠数 DOM 气泡去猜（WhatsApp 是虚拟列表，气泡会回收，实测会误判
 * 成失败并重发，2026-09-29 出过重复告警事故）。
 *
 * 本进程的发送确认是 `sendMessage()` 的**返回值**，带服务端 message id —— 真实回执，
 * 不是猜的。扩展侧那套「清空输入框 / 双信号确认 / 超时三分支」的防重复防线，
 * 在这里**全部不需要**。
 *
 * ## 运行
 *
 *   node --env-file-if-exists=.env src/notify.js            # 常驻
 *   node --env-file-if-exists=.env src/notify.js --check    # 只连一次，自检后退出
 *   node --env-file-if-exists=.env src/notify.js --groups   # 列出所有群名 → JID
 */
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidGroup,
} from 'baileys';
import P from 'pino';
import { existsSync, mkdirSync, appendFileSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { CONFIG, ROOT } from './config.js';

const logger = P({ level: 'silent' });

const CHECK_ONLY = process.argv.includes('--check');
const LIST_GROUPS = process.argv.includes('--groups');

/* --------------------------------- 日志 --------------------------------- */

let logFile = null;
function log(line) {
  const msg = `[${new Date().toISOString()}] ${line}`;
  console.log(msg);
  try {
    if (!logFile) {
      mkdirSync(CONFIG.logDirAbs, { recursive: true });
      logFile = join(CONFIG.logDirAbs, `notify-${new Date().toISOString().slice(0, 10)}.log`);
    }
    appendFileSync(logFile, msg + '\n', 'utf8');
  } catch {
    /* 日志失败不影响主流程 */
  }
}

/* ------------------------------- 作业信箱 ------------------------------- */

/**
 * 信箱文件：my_app 投递 → 本进程消费 → 回写结果。
 *
 * 刻意与 `index.js` 的问答通道**共用同一个凭据目录**（`data/auth`），
 * 但用**独立的进程**。原因见文件头。
 */
const JOB_FILE = process.env.NOTIFY_JOB_FILE
  ? process.env.NOTIFY_JOB_FILE
  : join(ROOT, 'data', 'notify_job.json');

/** 心跳文件：my_app 侧据此判断「推送通道是否在线」（对应 ext_liveness.py）。 */
const HEARTBEAT_FILE = join(ROOT, 'data', 'notify_heartbeat.json');

/** 轮询间隔（毫秒）。告警是分钟级业务，5 秒足够，又不至于空转太凶。 */
const POLL_MS = Number(process.env.NOTIFY_POLL_MS || 5000);

function readJsonSafe(p) {
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/** 原子写：先写临时文件再 rename，避免读到写了一半的 JSON。 */
function writeJsonAtomic(p, data) {
  mkdirSync(dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  renameSync(tmp, p);
}

/* --------------------------------- 主体 --------------------------------- */

let sockRef = null;
let connected = false;
/** 群名 → JID 缓存。首次收到群列表后填充。 */
const groupIndex = new Map();

/**
 * 从 socket 拉取「已参与的群」并建 name → jid 索引。
 *
 * 为什么要这一步：my_app 侧配置的是**群名**（如 `OLR Eflow Issues`），
 * 而 `sendMessage` 要的是 **JID**（`1203...@g.us`）。凭据目录里的
 * `sender-key-*.json` 只能证明"发过消息"，既不保证仍在群里，也不含群名。
 * 唯一可靠的映射只能从服务端拿。
 */
async function refreshGroups(sock) {
  try {
    const all = await sock.groupFetchAllParticipating();
    groupIndex.clear();
    for (const [jid, meta] of Object.entries(all || {})) {
      const name = (meta?.subject || '').trim();
      if (!name) continue;
      // 同名群理论上可能存在，保留先到的并在日志里提示，不静默覆盖
      if (groupIndex.has(name)) {
        log(`! 群名重复：「${name}」同时对应 ${groupIndex.get(name)} 与 ${jid}，将用先到的`);
        continue;
      }
      groupIndex.set(name, jid);
    }
    log(`✓ 群索引就绪：${groupIndex.size} 个群`);
    return true;
  } catch (err) {
    log(`! 拉取群列表失败（名称寻址暂不可用，仍可用 JID 直发）：${err.message}`);
    return false;
  }
}

/**
 * 群名 → JID。已是 JID（含 `@`）则原样返回，便于配置里直接写 JID 绕过名称解析。
 * @returns {string|null} null = 找不到，调用方应记失败而**不是**随便挑个群发
 */
function resolveGroup(nameOrJid) {
  const s = String(nameOrJid || '').trim();
  if (!s) return null;
  if (s.includes('@')) return s;
  return groupIndex.get(s) || null;
}

function heartbeat(extra = {}) {
  try {
    writeJsonAtomic(HEARTBEAT_FILE, {
      at: new Date().toISOString(),
      connected,
      groups: groupIndex.size,
      pid: process.pid,
      ...extra,
    });
  } catch {
    /* 心跳失败不影响发送 */
  }
}

/** 认领待发作业（有则返回，无则 null）。 */
function claimJob() {
  const job = readJsonSafe(JOB_FILE);
  if (!job || typeof job !== 'object') return null;
  if (job.status !== 'pending') return null;
  return job;
}

/** 回写作业结果。`sent` 里的 message id 是服务端回执，my_app 据此置 'Y'。 */
function finishJob(job, ok, sent, errors) {
  writeJsonAtomic(JOB_FILE, {
    ...job,
    status: ok ? 'done' : 'failed',
    completed_at: new Date().toISOString(),
    result: { ok, sent, errors },
  });
}

/**
 * 处理一个作业：逐条发送，逐条记录结果。
 *
 * **局部失败不整体放弃**：3 条消息里挂了 1 条，另 2 条已经真发出去了，
 * 报整体失败会让 my_app 认为全没发、下一轮全部重发 → 群里出现重复告警。
 * 故逐条回报，由 my_app 按 tt_no 精确落库。
 */
async function runJob(sock, job) {
  const messages = Array.isArray(job.messages) ? job.messages : [];
  const targets = Array.isArray(job.groups) ? job.groups : [];
  const sent = [];
  const errors = [];

  if (!messages.length) {
    finishJob(job, false, [], ['作业里没有 messages']);
    return;
  }
  if (!targets.length) {
    finishJob(job, false, [], ['作业里没有 groups']);
    return;
  }

  // 解析目标群：任一解析不了就**整个作业失败**，不做部分发送。
  // 理由：告警的语义是"这条消息必须到达值班群"，静默少发一个群等于漏告警。
  const jids = [];
  for (const t of targets) {
    const jid = resolveGroup(t);
    if (!jid) {
      finishJob(job, false, [], [
        `找不到群「${t}」对应的 JID（当前已知 ${groupIndex.size} 个群）。` +
        `请确认机器人账号已加入该群，或用 --groups 查看可用群名。`,
      ]);
      return;
    }
    jids.push(jid);
  }

  for (const m of messages) {
    const text = String(m?.text || '');
    const ttNo = String(m?.tt_no || '');
    if (!text) {
      errors.push(`${ttNo || '(无单号)'}：文本为空，跳过`);
      continue;
    }
    for (const jid of jids) {
      try {
        const res = await sock.sendMessage(jid, { text });
        // **服务端回执**：有 id 才算发出。这是与扩展通道最本质的区别。
        if (res?.key?.id) {
          sent.push({ tt_no: ttNo, jid, message_id: res.key.id });
          log(`✓ 已发送 ${ttNo} → ${jid}（msg id ${res.key.id}）`);
        } else {
          errors.push(`${ttNo} → ${jid}：sendMessage 未返回 message id，无法确认`);
          log(`! ${ttNo} → ${jid}：未返回 message id`);
        }
      } catch (err) {
        errors.push(`${ttNo} → ${jid}：${err.message}`);
        log(`✗ 发送失败 ${ttNo} → ${jid}：${err.message}`);
      }
    }
  }

  const ok = sent.length > 0;
  finishJob(job, ok, sent, errors);
  log(`[作业完成] ${job.job_id || '(无 id)'} 成功 ${sent.length} / 失败 ${errors.length}`);
}

/* ------------------------------- 连接与轮询 ------------------------------- */

export function reconnectDelay(attempt) {
  return Math.min(60000, 2000 * 2 ** Math.min(Math.max(attempt, 1) - 1, 5));
}

let reconnectAttempts = 0;
let shuttingDown = false;
/** 轮询定时器句柄。模块级，保证重连后不会重复起定时器（否则每重连一次多一个）。 */
let pollTimer = null;

async function start() {
  if (!existsSync(CONFIG.authDirAbs)) {
    log(`✗ 凭据目录不存在：${CONFIG.authDirAbs}`);
    log('  请先在 whatsapp-kb-bot 目录执行 npm run relogin 扫码登录。');
    process.exit(1);
  }
  if (!existsSync(join(CONFIG.authDirAbs, 'creds.json'))) {
    log(`✗ 缺 creds.json：${CONFIG.authDirAbs}`);
    log('  请先执行 npm run relogin 扫码登录。');
    process.exit(1);
  }

  const { state, saveCreds } = await useMultiFileAuthState(CONFIG.authDirAbs);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: ['Chrome (Linux)', '', ''],
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
  });
  sockRef = sock;

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      // 推送进程是隐藏运行的，二维码打出来也没人看得见 —— 直接说清怎么办。
      log('✗ 需要重新扫码登录（凭据已失效）。');
      log('  请停止本进程，改为在 whatsapp-kb-bot 目录执行：npm run relogin');
      process.exit(1);
    }

    if (connection === 'open') {
      reconnectAttempts = 0;
      connected = true;
      log(`✓ 已连接。凭据目录：${CONFIG.authDirAbs}`);
      await refreshGroups(sock);
      heartbeat({ event: 'connected' });
      if (CHECK_ONLY) {
        log('✓ --check 通过：凭据可用且连接成功，发送能力正常。');
        shuttingDown = true;   // 先置位，否则 sock.end() 触发的 close 会被当成掉线而打印"准备重连"
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        await sock.end(undefined);
        process.exit(0);
      }
      if (LIST_GROUPS) {
        log('--- 机器人当前参与的群 ---');
        for (const [name, jid] of [...groupIndex.entries()].sort()) log(`  ${name}  →  ${jid}`);
        log('--------------------------');
        shuttingDown = true;
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        await sock.end(undefined);
        process.exit(0);
      }
    }

    if (connection === 'close') {
      connected = false;
      heartbeat({ event: 'closed' });
      if (shuttingDown) return;

      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log('✗ 已被登出（手机端可能移除了该设备）。');
        log('  请执行 npm run relogin 重新扫码后重启本进程。');
        process.exit(1);
      }

      try {
        sock.ev.removeAllListeners('connection.update');
        sock.ev.removeAllListeners('creds.update');
        sock.ws?.close();
      } catch {
        /* 忽略 */
      }

      reconnectAttempts++;
      const delay = reconnectDelay(reconnectAttempts);
      log(`! 连接断开（code=${code}），${(delay / 1000).toFixed(0)}s 后第 ${reconnectAttempts} 次重连…`);
      setTimeout(() => {
        if (!shuttingDown) start().catch((e) => log(`重连失败：${e.message}`));
      }, delay);
    }
  });

  // 轮询信箱。用模块级句柄保证只起一个 —— 重连会再次进入 start()，
  // 若不判重，每重连一次就多一个定时器，同一条告警会被发多次。
  if (!pollTimer) {
    pollTimer = setInterval(async () => {
      if (!connected) return;
      const job = claimJob();
      if (!job) {
        heartbeat();
        return;
      }
      try {
        await runJob(sock, job);
      } catch (err) {
        log(`✗ 处理作业异常：${err.stack || err.message}`);
        try {
          finishJob(job, false, [], [`推送进程内部异常：${err.message}`]);
        } catch {
          /* 回写都失败时只能靠心跳暴露 */
        }
      }
    }, POLL_MS);
    log(`✓ 信箱轮询已启动（每 ${POLL_MS / 1000}s）：${JOB_FILE}`);
  }
}

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    shuttingDown = true;
    log(`收到 ${sig}，正在关闭…`);
    try {
      await sockRef?.end(undefined);
    } catch {
      /* 已断开则忽略 */
    }
    process.exit(0);
  });
}

process.on('unhandledRejection', (err) => log(`[未处理的 Promise 异常] ${err?.stack || err}`));
process.on('uncaughtException', (err) => log(`[未捕获异常] ${err?.stack || err}`));

start().catch((err) => {
  log(`✗ 启动失败：${err.message}`);
  process.exit(1);
});
