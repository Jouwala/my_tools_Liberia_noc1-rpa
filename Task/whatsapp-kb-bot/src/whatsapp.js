/**
 * WhatsApp 接入层 —— 连接、收发、触发判定、冷却、会话历史、问答记录。
 *
 * ## ⚠️ 本文件已超出仓库的 500 行上限（660 行，2026-10-07）
 *
 * `AGENTS.md` 第三节第 2 条要求新增文件不超过 500 行，存量超限文件
 * 「改到它们时不得继续无度膨胀」。本文件属于**存量超限**：
 * 573 行（原始）→ 622（加会话历史）→ 660（加问答记录）。
 *
 * 已把能拆的都拆出去了（问答记录 → `qalog.js`），剩下的这几块
 * **互相耦合较紧**，值得拆但需要一次专门的整理，不该顺手塞进
 * 一个业务改动里。**下次要动这个文件时，先做这次拆分**：
 *
 *   · 连接与重连（startWhatsApp / reconnectDelay / 心跳）→ `connection.js`
 *   · 消息处理（handleMessage / 触发 / 冷却 / 队列）→ `handler.js`
 *   · 本文件只保留两者之间的编排
 *
 * 拆分前先确认 `scripts/test-runtime.mjs` 与 `test-lang.mjs` 里那些
 * 按源码文本断言的正则（如 `onQuestion\(question,\s*\{`）是否需要同步更新。
 *
 * 职责：登录 / 重连 / 群内 @提及识别 / 文本抽取 / 发送回复。
 * 不包含任何 RAG 逻辑 —— 通过 onQuestion 回调把问题交给上层（Baileys）。
 */
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidGroup,
  Browsers,
  WAMessageStatus,
} from 'baileys';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import { existsSync, mkdirSync, appendFileSync, writeFileSync, renameSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { CONFIG, ROOT } from './config.js';
import { createQrWatcher, QR_STATE } from './qrLogin.js';
import { detectLang, pickText } from './lang.js';
import { selfIdentifiers, extractText, detectTrigger, stripMentions, isAllowedChat } from './mentions.js';
import { openQaLog, recordQa, closeQaLog } from './qalog.js';

const logger = P({ level: 'silent' });

/* -------------------------------- 心跳文件 -------------------------------- */

/**
 * 心跳文件：机器可读的「本进程还活着、且是否已连接」。
 *
 * 为什么不能只靠 bot.pid 或扫命令行（2026-10-06）：
 *   `autostart.ps1` 原先用 `CommandLine -match 'src[\\/]index\.js'` 判活，
 *   只要**任何**进程的命令行里出现过这个字符串就会被当成机器人（实测把
 *   agent 的 shell 自己认成了 bot，还写进 bot.pid），而且进程活着 ≠ 已连接：
 *   掉线后进程仍在，看门狗却以为一切正常。
 *
 *   `src/notify.js` 早就用同样思路解决了这个问题（data/notify_heartbeat.json），
 *   这里对齐它的做法：原子写，且把 `connected` 一并写进去，让看门狗能区分
 *   「进程没了」和「进程在但掉线了」——后者同样需要重启。
 */
const HEARTBEAT_FILE = join(CONFIG.authDirAbs, '..', 'bot_heartbeat.json');

/** 原子写：先写临时文件再 rename，避免读到写了一半的 JSON。 */
function writeJsonAtomic(p, data) {
  mkdirSync(dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  renameSync(tmp, p);
}

let heartbeatConnected = false;

/**
 * 最近一次**成功处理完**消息的时刻（ISO 字符串），以及累计处理条数。
 *
 * 为什么需要它（2026-10-06 事故的直接教训）：
 *   `connected` + `at` 新鲜**只能证明连接在**，不能证明消息进得来。
 *   当时机器人陷入 408/428 重连循环，每次重连成功都把 `connected` 写回 true，
 *   心跳一直新鲜 —— 看门狗据此判定「健康」，于是永不重启，
 *   故障从下午持续到人工发现。而同期日志里 `[提问]` 一条都没有。
 *
 *   `lastMessageAt` 才是「真的在工作」的正据：它是**业务层**的活性，
 *   而不是**传输层**的活性。两者会背离，且背离时说不上话的那一方才是真相。
 *
 * 刻意记录在**处理完之后**（见 handleMessage 末尾），不是收到就算：
 * 收到但抛异常说明链路仍是坏的，不该让计数器好看。
 */
let lastMessageAt = null;
let messagesHandled = 0;

function heartbeat(extra = {}) {
  try {
    writeJsonAtomic(HEARTBEAT_FILE, {
      at: new Date().toISOString(),
      connected: heartbeatConnected,
      pid: process.pid,
      // 从没处理过消息时是 null，而不是伪造一个当前时间 ——
      // 看门狗必须能区分「刚启动还没人说话」与「一直在正常工作」。
      lastMessageAt,
      messagesHandled,
      ...extra,
    });
  } catch {
    /* 心跳失败不影响收发消息 */
  }
}

/** 供 index.js 优雅退出时把心跳标成已断开（可选，让状态更即时）。 */
export function markDisconnected() {
  heartbeatConnected = false;
  heartbeat({ event: 'stopped' });
}

/* --------------------------------- 日志 --------------------------------- */

let logFile = null;
function log(line) {
  const ts = new Date().toISOString();
  const msg = `[${ts}] ${line}`;
  console.log(msg);
  try {
    if (!logFile) {
      mkdirSync(CONFIG.logDirAbs, { recursive: true });
      logFile = join(CONFIG.logDirAbs, `bot-${new Date().toISOString().slice(0, 10)}.log`);
    }
    appendFileSync(logFile, msg + '\n', 'utf8');
  } catch {
    /* 日志失败不影响主流程 */
  }
}

/**
 * 把失效的凭据目录整体改名隔离（**只改名，不删除**，可人工改回）。
 *
 * 与 `qrLogin.js` 的 `backupAuthDir()` 同款约定：同名备份会攒，所以带时间戳；
 * 不同之处是本函数用于「检测到登出、自动恢复」这条路径，而那边是「用户主动
 * 点扫码」。两者都只 rename，绝不 rm —— 凭据含真实账号信息，误删不可逆。
 *
 * @param {string} authDir 凭据目录绝对路径
 * @returns {{ok: boolean, backup?: string|null, error?: string}}
 */
function quarantineAuthDir(authDir) {
  if (!existsSync(authDir)) return { ok: true, backup: null };
  // 空目录无需隔离（首次登录尚未扫码）——否则会攒一堆空备份。
  let hasCreds = false;
  try {
    hasCreds = readdirSync(authDir).includes('creds.json');
  } catch {
    /* 读不到目录内容按「无凭据」处理 */
  }
  if (!hasCreds) return { ok: true, backup: null };
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const backup = join(dirname(authDir), `auth.bak-${stamp}-loggedout`);
  try {
    renameSync(authDir, backup);
    return { ok: true, backup };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

/**
 * 重连退避：2s → 4s → 8s → 16s → 32s → 60s（封顶）。
 * 抽成纯函数以便单测 —— 之前的实现在函数内声明计数变量，
 * 每次重连都从 0 开始，退避永远停在 2 秒，等于没有退避。
 * @param {number} attempt 第几次重连（从 1 开始）
 */
export function reconnectDelay(attempt) {
  return Math.min(60000, 2000 * 2 ** Math.min(Math.max(attempt, 1) - 1, 5));
}

/* --------------------------------- 主体 --------------------------------- */

// 模块级状态：必须活过单次 startWhatsApp 调用，否则重连时会被重置。
// （曾把 reconnectAttempts 放在函数内，导致每次重连都从 0 开始，
//   指数退避永远停在第一步 —— 断网时会以 2 秒间隔无限重试。）
let activeSock = null;
let reconnectAttempts = 0;
let shuttingDown = false;

/** 本进程内连续「已被登出」的次数。见 connection=close 里的 loggedOut 分支。 */
let loggedOutCount = 0;

/**
 * 连续「已被登出」的自动恢复上限。超过就停机报警，不再无限循环。
 * 取 2：第一次隔离通常就能出码；若隔离后立刻又被登出，说明是设备位被
 * 持续清掉（手机端残留设备 / 设备数上限），自动重试解决不了。
 */
const MAX_LOGOUT_QUARANTINE = 2;

/** 网页扫码登录 watcher（模块级：重连会再次进入 startWhatsApp，只能建一次）。见 src/qrLogin.js。 */
let qrWatcher = null;
/** 是否处于「网页扫码」发起的主动重启中（抑制旧 socket 的 close 分支再排一次重连）。 */
let restarting = false;

/* ------------------- 跨重连保持的业务状态（模块级，见下方说明） ------------------- */

/** 机器人自身的多种标识形式。每次连接 open 时按新 socket 重算。 */
let selfIds = new Set();

/** 机器人自己发出的消息 id，用于识别「引用回复机器人」。有上限，防内存泄漏。 */
const botMessageIds = createBoundedIdSet(500);

/** chatJid → 上次回复时间，用于冷却。 */
const lastReplyAt = new Map();

/**
 * 已发出但**尚未收到服务端回执**的消息：id → { chatJid, at, timer, sample }。
 *
 * ## 为什么需要它（2026-10-26 实测事故）
 *
 * 用户报告「OLR Eflow Issues 群里 10:50 那次没收到回答」。查库发现 qa_log
 * 里躺着一条 1179 字符的完整答案、`[回复]` 日志也打了、**零条 `[发送失败]`**
 * ——看起来一切正常。但同一群同一号码在 11:35 重试就能收到，说明消息确实
 * 没到。根因是：`sock.sendMessage()` 只是把消息**放进加密队列**就返回
 * message id，真正的服务端受理是异步 `messages.update` 事件。本项目原先
 * 根本没监听它，所以「发出去了」和「对方收到了」从来没有被区分过。
 *
 * 现在的处理：发出时登记，收到 `SERVER_ACK`/`DELIVERY_ACK`/`READ` 即移除；
 * 超过 `ACK_TIMEOUT_MS` 仍无回执则打 `[未送达]` 日志。注意这只是**观测**，
 * 不改发送行为 —— 回执缺失既可能是真没送到，也可能是回执本身丢了。
 */
const pendingAcks = new Map();

/** 发出后多久还没回执就报「未送达」。WhatsApp 正常回执在 1~3 秒内。 */
const ACK_TIMEOUT_MS = 30000;

/** 未送达日志里附的正文片段长度（够判别是哪条，又不刷屏）。 */
const ACK_SAMPLE_CHARS = 60;

/**
 * 最近一次连接 open 的时刻。用于**登录预热期限速发送**。
 *
 * 2026-10-26 事故的另一半：10:46:20 扫码登录完成，10:50:52 那条回答就没到。
 * 中间只成功发出过 2 条消息（10:49:04 ping、10:49:15 首次提问）—— 紧接着的
 * 第 3 条落进了 session/信号会话尚未完全建立的窗口，服务端不报错但也没投递。
 * `sendMessage` 照样返回 message id，所以日志上完全看不出来。
 *
 * 处理方式：open 之后的 WARMUP_MS 内，每条消息前等 WARMUP_SEND_GAP_MS，
 * 把连发摊开，给信号会话留出建立时间。这只是**延长间隔**，不丢弃消息。
 */
let connectedAt = 0;
const WARMUP_MS = 30000;
const WARMUP_SEND_GAP_MS = 2000;

/** 预热期内让出一条时间片；预热期外立即返回。 */
async function warmupGate() {
  if (!connectedAt) return;
  const elapsed = Date.now() - connectedAt;
  if (elapsed >= WARMUP_MS) return;
  await new Promise((r) => setTimeout(r, WARMUP_SEND_GAP_MS));
}

/** 已送达的状态值。低于这些的一律算「还没确认」。 */
const ACK_DONE = new Set([
  WAMessageStatus.SERVER_ACK,
  WAMessageStatus.DELIVERY_ACK,
  WAMessageStatus.READ,
  WAMessageStatus.PLAYED,
]);

/** 登记一条待回执消息（send() 调用）。 */
function trackAck(id, jid, text) {
  if (!id) return;
  const timer = setTimeout(() => {
    const rec = pendingAcks.get(id);
    if (!rec) return;
    pendingAcks.delete(id);
    log(
      `[未送达] ${rec.chatJid}：发出 ${Math.round(ACK_TIMEOUT_MS / 1000)}s 无服务端回执` +
        `（msgId=${id}｜${rec.sample}）`
    );
  }, ACK_TIMEOUT_MS);
  // 定时器不该拖住进程退出
  timer.unref?.();
  pendingAcks.set(id, { chatJid: jid, at: Date.now(), timer, sample: String(text).slice(0, ACK_SAMPLE_CHARS) });
  // 防泄漏：正常情况下回执很快到，这里是万一回执永远不来的兜底
  if (pendingAcks.size > 500) {
    const oldest = pendingAcks.keys().next().value;
    clearTimeout(pendingAcks.get(oldest)?.timer);
    pendingAcks.delete(oldest);
  }
}

/** 收到回执：确认送达并从待确认表移除。 */
function resolveAck(id) {
  const rec = pendingAcks.get(id);
  if (!rec) return;
  clearTimeout(rec.timer);
  pendingAcks.delete(id);
}

/**
 * chatJid → 最近几轮问答（时间正序），用于**追问**。
 *
 * ## 为什么需要它
 *
 * 2026-10-07 实测：机器人回了「P1 单 6 个 / 其中未闭环 1 个 / 单号：…」，
 * 用户紧接着问「那个单子未闭环」——这句话**单看没有主语**，
 * 不含日期、不含级别，规则层和模型层都只能猜，
 * 结果答成了「今天全网 36 单」。**答的是一个完全不同的问题，且不报错。**
 *
 * 有上下文后，「那个单子」＝上一轮那批 P1，问题才落得下来。
 *
 * ## 为什么放在接入层
 *
 * 历史是**会话的属性**，不是某个通道的属性 —— 统计通道、知识库通道、
 * 单票通道都要用同一份。放在这里天然按 chatJid 隔离，
 * 且不需要给每个通道各写一套。
 *
 * 只留最近 HISTORY_TURNS 轮：再久的话，用户早就换了话题，
 * 旧问答留在 prompt 里只会干扰判断。
 */
const HISTORY_TURNS = 5;
const chatHistory = new Map();

/** 记一轮问答（answer 为空表示这轮没答上来，不记）。 */
export function rememberTurn(chatJid, q, a) {
  if (!chatJid || !q || !a) return;
  const list = chatHistory.get(chatJid) || [];
  list.push({ q: String(q).slice(0, 300), a: String(a).slice(0, 500) });
  while (list.length > HISTORY_TURNS) list.shift();
  chatHistory.set(chatJid, list);
  // 与 lastReplyAt 同样防内存泄漏：群很多时不能让这张表无限长
  if (chatHistory.size > 1000) {
    const oldest = chatHistory.keys().next().value;
    chatHistory.delete(oldest);
  }
}

/** 取某个会话的最近几轮问答（时间正序）。 */
export function getHistory(chatJid) {
  return chatHistory.get(chatJid) || [];
}

/** 串行队列：避免并发把本地模型压垮。跨重连保持，保证同一时刻只有一个提问在处理。 */
let chain = Promise.resolve();

/** 当前排队中的提问数。 */
let queued = 0;

/** 累计因断连而错过的消息数（可观测性，见 handleMessage 里的说明）。 */
let missedWhileDown = 0;

/** 是否处于「刚断过、还没重连成功」的状态，以及断开起始时间。 */
let wasDisconnected = false;
let downSince = 0;

/**
 * 有上限的 id 集合。用于记录机器人自己发出的消息 id。
 * 直接用 Set 会随运行时间无限增长（内存泄漏），这里做 FIFO 淘汰。
 * 导出以便单测。
 */
export function createBoundedIdSet(limit = 500) {
  const set = new Set();
  const order = [];
  return {
    add(id) {
      if (!id || set.has(id)) return;
      set.add(id);
      order.push(id);
      if (order.length > limit) set.delete(order.shift());
    },
    has(id) {
      return set.has(id);
    },
    get size() {
      return set.size;
    },
  };
}

/** 优雅关闭：让 Baileys 正常结束会话，避免凭据写坏 */
export async function stopWhatsApp(reason = '收到停止信号') {
  shuttingDown = true;
  log(`正在关闭（${reason}）…`);
  try {
    await activeSock?.end(undefined);
  } catch {
    /* 已断开则忽略 */
  }
  try {
    activeSock?.ws?.close();
  } catch {
    /* 忽略 */
  }
  log('已关闭。');
  // 关库让 WAL 落盘；不关的话最近几条记录还留在 -wal 里，
  // 用别的工具打开这个库会看不到。
  closeQaLog();
}

export async function startWhatsApp({ onQuestion, builtins = null }) {
  if (!existsSync(CONFIG.authDirAbs)) mkdirSync(CONFIG.authDirAbs, { recursive: true });

  // 网页扫码登录 watcher：模块级 + 判重，保证重连不重复创建。
  // 收到请求时清空 data/auth 并触发重连（此时无凭据 → Baileys 走 qr 分支出码）。
  if (!qrWatcher) {
    qrWatcher = createQrWatcher({
      device: 'bot',
      authDir: CONFIG.authDirAbs,
      root: ROOT,
      log,
      onRestart: async () => {
        restarting = true;
        try {
          activeSock?.ev?.removeAllListeners('messages.upsert');
          activeSock?.ev?.removeAllListeners('messages.update');
          activeSock?.ev?.removeAllListeners('connection.update');
          activeSock?.ev?.removeAllListeners('creds.update');
          activeSock?.ws?.close();
        } catch {
          /* 忽略 */
        }
        try {
          await startWhatsApp({ onQuestion, builtins });
        } finally {
          restarting = false;
        }
      },
    });
  }

  // 问答记录：开一次，失败也不影响启动（记录是旁路，见 qalog.js）。
  if (CONFIG.qaLogEnabled) {
    const ok = openQaLog(CONFIG.qaLogPath);
    log(ok ? `问答记录：${CONFIG.qaLogPath}` : '问答记录不可用（不影响回复）');
  } else {
    log('问答记录：已按配置关闭（QA_LOG_ENABLED=0）');
  }

  const { state, saveCreds } = await useMultiFileAuthState(CONFIG.authDirAbs);
  let { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  // 这些状态**刻意放在模块级**，必须活过重连。
  //
  // 原先它们是 startWhatsApp 的局部变量，而重连是递归调用 startWhatsApp —— 每断
  // 一次就全部清零重建。后果（2026-10-06 实测）：
  //   · botMessageIds 清空 → 用户「引用回复机器人」时认不出被引用的是自己，不响应；
  //   · lastReplyAt 清空 → 冷却失效，重连瞬间的连发会被全部处理；
  //   · chain/queued 归零 → 上一个 socket 里**还在跑**的提问与新一轮并发，
  //     既可能重复回答，也让串行保护形同虚设。
  // 模块级后，重连只换 socket，业务状态连续。
  // （notify.js 的 groupIndex/sockRef 早就是模块级，同样理由。）
  // selfIds 每次 open 时按新 socket 重算，这里保留最后一次结果即可。

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: Browsers.appropriate('Chrome'),
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
    // 保活与超时。Baileys 默认 keepAliveIntervalMs=30000，本身就会定时发 ping；
    // 这里**显式写出来**是为了让「它到底多久探活一次」在代码里可见 ——
    // 2026-10-06 排查时只能去翻 node_modules 才确认到这点。
    // 注意：调到比默认更短并不会更稳，反而增加被服务端限流的风险；
    // 所以保持 30s，只调大「多久算断」的判定窗口，减少把慢网络误判成掉线。
    keepAliveIntervalMs: 30_000,
    connectTimeoutMs: 60_000,
  });
  activeSock = sock;

  /* ------------------------------ 事件绑定 ------------------------------ */

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log('\n=== 请用 WhatsApp 扫码登录 ===');
      console.log('手机 WhatsApp → 设置 → 已关联的设备 → 关联设备\n');
      qrcode.generate(qr, { small: true });
      console.log('\n（首次登录后凭据会保存在 data/auth/，之后免扫码）\n');
      // 同时把原始字符串写进状态文件，供 my_app 设置页渲染（见 src/qrLogin.js）。
      qrWatcher?.publishQr(qr);
    }

    if (connection === 'open') {
      reconnectAttempts = 0;
      // 记下 open 时刻，供 warmupGate() 判断是否还在登录预热期（见其注释）。
      connectedAt = Date.now();
      // 连上就清掉「连续登出」计数：下一次再被登出应从 0 重新数，
      // 否则长时间运行后偶发的登出会累积、过早触发停机保护。
      loggedOutCount = 0;
      selfIds = selfIdentifiers(sock, state.creds?.me);
      log(`✓ 已连接。机器人标识：${[...selfIds].join(' / ')}`);
      log(`  回复模式：${CONFIG.replyMode}｜群白名单：${CONFIG.allowGroups.join(', ')}`);
      // 断连期间错过的消息在这里报出来。WhatsApp 不会补投断连窗口内别人发的消息
      // （离线补投只保证最近一小段，实测不可依赖），所以这段时间里的 @ 就是丢了。
      // 之前这件事**完全不可见**：日志只有「已连接」，看起来一切正常，用户却说
      // 机器人不理人 —— 2026-10-06 排查时正是卡在这个盲区上。
      if (wasDisconnected) {
        wasDisconnected = false;
        const downSec = downSince ? Math.round((Date.now() - downSince) / 1000) : null;
        downSince = 0;
        log(
          `  ⚠️ 本次断连约 ${downSec ?? '?'}s` +
            (missedWhileDown ? `，期间有 ${missedWhileDown} 条回复因连接已断未能发出` : '') +
            '；断连窗口内别人发的消息不会补投。'
        );
        missedWhileDown = 0;
      }
      heartbeatConnected = true;
      heartbeat({ event: 'connected' });
      // 扫码成功（或本就有有效凭据）：若本次是网页扫码请求触发的，回写 connected。
      qrWatcher?.setState(QR_STATE.CONNECTED, { message: '已连接' });
    }

    if (connection === 'close') {
      wasDisconnected = true;
      if (!downSince) downSince = Date.now();
      heartbeatConnected = false;
      heartbeat({ event: 'closed' });
      if (shuttingDown) return;
      // 主动重启（网页扫码登录）触发的关闭：新连接已由 onRestart 的 startWhatsApp 接手，
      // 这里不再排重连，否则两个 socket 并存、出两份码。
      if (restarting) return;

      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      if (loggedOut && !qrWatcher?.isLoginRequested()) {
        // 401 = loggedOut：手机端移除了该设备，或服务端把这台设备登出。
        //
        // 关键事实（2026-10-14 实测）：登出后 `data/auth/creds.json` 里的
        // `registered` 会变成 false —— **凭据文件还在，但已是废凭据**。此时
        // Baileys 拿着它去连，服务端回 401 而**不是** qr 挑战，所以无论重启
        // 多少次都不会出码。过去的写法是直接 `process.exit(1)` 并把状态写成
        // ERROR，于是：看门狗每 5 分钟拉起 → 秒退 → 循环，而网页「扫码登录」
        // 按钮只是个写请求文件的空动作（没有活进程去读它）——**死锁**。
        //
        // 现在改成自愈：确认是废凭据就把凭据目录改名隔离，然后重连；目录
        // 一空，Baileys 自然走 qr 分支出码。全程不需要人工删目录、不需要改
        // 命令行，网页按钮点一下即可。
        //
        // 注意 `isLoginRequested()` 那个前置判断：若本次关闭本来就是「网页
        // 扫码」发起的（onRestart 已备份并重建了空目录），这里再隔离一次就是
        // 多余动作，且会把刚建好的空目录改名走 —— 交给扫码流程自己走完。
        loggedOutCount++;
        log(`✗ 已被登出（第 ${loggedOutCount} 次）：凭据已失效，手机端可能移除了该设备。`);
        if (loggedOutCount > MAX_LOGOUT_QUARANTINE) {
          // 隔离过 MAX 次仍被登出：不是凭据陈旧，而是这个号码的设备位被
          // 服务端/手机端持续清掉（例如被别人反复踢、或设备数已满）。
          // 再自动重试只会无限循环刷日志，停机并留一条明确的状态给值班人。
          log(`  已连续隔离 ${MAX_LOGOUT_QUARANTINE} 次仍被登出，停止自动重试。`);
          log('  请到手机 WhatsApp → 设置 → 已关联的设备 检查是否有残留设备，再点网页「扫码登录」。');
          qrWatcher?.setState(QR_STATE.ERROR, {
            message: `已被登出且自动恢复 ${MAX_LOGOUT_QUARANTINE} 次未成功；请在手机上清理残留的已关联设备后重新扫码`,
          });
          process.exit(1);
        }
        const bak = quarantineAuthDir(CONFIG.authDirAbs);
        if (!bak.ok) {
          log(`  ✗ 隔离废凭据失败：${bak.error}`);
          qrWatcher?.setState(QR_STATE.ERROR, { message: `已被登出，且隔离凭据失败：${bak.error}` });
          process.exit(1);
        }
        if (bak.backup) log(`  废凭据已隔离到 ${bak.backup}`);
        log('  正在重连以生成二维码…（无需手动删目录）');
        qrWatcher?.setState(QR_STATE.WAITING, { message: '凭据已失效，正在重新生成二维码…' });
        try {
          mkdirSync(CONFIG.authDirAbs, { recursive: true });
        } catch (err) {
          qrWatcher?.setState(QR_STATE.ERROR, { message: `重建凭据目录失败：${err.message}` });
          process.exit(1);
        }
        // 走与「网页扫码」同一个重启入口：它负责关掉旧 socket 并重新 startWhatsApp。
        // restarting 标志会让本次 close 的后续重连逻辑短路，避免两个 socket 并存。
        try {
          restarting = true;
          await startWhatsApp({ onQuestion, builtins });
        } catch (err) {
          log(`  ✗ 重连失败：${err.message}`);
          qrWatcher?.setState(QR_STATE.ERROR, { message: `重连失败：${err.message}` });
          process.exit(1);
        } finally {
          restarting = false;
        }
        return;
      }
      if (loggedOut) {
        // 走到这里说明本次关闭是「网页扫码」主动发起的（onRestart 已清空凭据），
        // 由扫码流程自己接管出码，这里不干预、不退出。
        log('✗ 连接已关闭（登出态），本次由扫码登录流程接管，等待二维码…');
        return;
      }

      // 440 = connectionReplaced：同一个 WhatsApp 账号的**另一个会话**把本连接顶掉了。
      // 这不是网络抖动，重连只会把对方顶掉、对方再顶回来 —— 两个进程无限互踢，
      // 日志表现为「2 秒连一次、连上 3 秒又断」，且**两个进程都收不到消息**。
      //
      // ⚠️ 成因订正（2026-10-06）：此处原先写「notify.js 与 index.js 共用 data/auth
      // 同一份凭据，两者只能留一个」——**该说法已过时且是错的**。凭据早已拆开：
      //     · src/index.js  → data/auth        （config.js:48，AUTH_DIR 可覆盖）
      //     · src/notify.js → data/auth-notify （notify.js:75，NOTIFY_AUTH_DIR 可覆盖）
      // 拆分的原因写在 notify.js 的注释里（同号双开会被互相顶掉），这里只是没同步。
      // 实测佐证：最后一批 440 出现在 2026-10-03，而拆分之后机器人一直正常连接
      // （10-04 ~ 10-06 日志里连上十几次），两者并不互斥。
      //
      // 所以 440 的真实来源收窄为「同一份凭据被第二个会话使用」，常见的是手动
      // 多开了 `npm start` / `relogin.mjs` 没退出，或另一台机器用了同一账号。
      //
      // 440 仍然刻意**不重连**：继续重连既救不活自己，又会让对方也收不到消息。
      // 直接退出，把问题暴露给看门狗/值班人，而不是伪装成"一直在重连"的正常状态。
      //
      // 注意枚举名：本仓库装的 baileys 6.7.24 里叫 `connectionReplaced`，
      // 没有 `conflict` 这个成员（写 conflict 会得到 undefined，判断永远不成立）。
      if (code === DisconnectReason.connectionReplaced || code === 440) {
        log('✗ 连接被同账号的另一个会话顶掉（code=440 connectionReplaced）。');
        log('  通常是有第二个进程在用同一份凭据（本机 data/auth，或另一台机器）。');
        log('  已知来源：手动多开了 npm start / relogin.mjs 没退出。');
        log('  （注意 notify.js 用的是 data/auth-notify，与本进程不冲突。）');
        log('  排查： Get-CimInstance Win32_Process -Filter "Name=\'node.exe\'" |');
        log("          Where-Object { $_.CommandLine -match 'whatsapp-kb-bot' } |");
        log('          Select-Object ProcessId,CommandLine');
        log('  本进程不再重连（继续重连只会与对方互相顶号）。');
        qrWatcher?.setState(QR_STATE.ERROR, { message: '连接被同账号的另一个会话顶掉（code=440）' });
        process.exit(2);
      }

      // 清理旧 socket，否则其事件监听器会一直挂在内存里
      try {
        sock.ev.removeAllListeners('messages.upsert');
        sock.ev.removeAllListeners('messages.update');
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
        if (shuttingDown) return;
        startWhatsApp({ onQuestion, builtins }).catch((e) => log(`重连失败：${e.message}`));
      }, delay);
    }
  });

  // 定时刷新心跳：连接正常但长时间没人提问时，也要让看门狗看到「还活着」。
  // 周期取 30s —— 远小于看门狗的 STALE 阈值（300s），同时开销可忽略。
  // unref() 让这个定时器**不阻止进程退出**，否则 Ctrl+C / 停止脚本会挂住。
  const hbTimer = setInterval(() => heartbeat(), 30_000);
  if (typeof hbTimer.unref === 'function') hbTimer.unref();
  heartbeat();

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;

    for (const msg of messages) {
      try {
        await handleMessage(msg);
      } catch (err) {
        log(`处理消息出错：${err.stack || err.message}`);
      }
    }
  });

  // 送达回执：只用来确认「我们发出的消息服务端是否受理」，故只关心 fromMe 的
  // 那些 update。见 pendingAcks 的注释（2026-10-26 未送达事故）。
  sock.ev.on('messages.update', (updates) => {
    for (const u of updates || []) {
      const id = u?.key?.id;
      if (!id || !u.key?.fromMe) continue;
      const status = u.update?.status;
      if (status != null && ACK_DONE.has(status)) resolveAck(id);
    }
  });

  async function handleMessage(msg) {
    const chatJid = msg.key?.remoteJid;
    if (!chatJid || chatJid === 'status@broadcast') return;

    // 记录自己发出的消息 id
    if (msg.key.fromMe) {
      if (msg.key.id) botMessageIds.add(msg.key.id);
      return;
    }

    const isGroup = isJidGroup(chatJid);
    if (!isAllowedChat({ chatJid, isGroup, allowGroups: CONFIG.allowGroups, replyMode: CONFIG.replyMode })) {
      return;
    }

    const text = extractText(msg.message);
    if (!text) return;

    // 实时计算自身标识，不用连接时缓存的快照。
    // 原因有二：
    //   1. LID 往往在连接之后才由服务端下发，缓存会永久漏掉它；
    //   2. sock.user 上的字段不总是可靠 —— 实测换号后 sock.user.lid 为空，
    //      但 state.creds.me.lid 有值。两个来源都传进去，代价可忽略。
    const ids = selfIdentifiers(sock, state.creds?.me);
    if (ids.size !== selfIds.size) {
      selfIds = ids;
      log(`↻ 机器人标识已更新：${[...ids].join(' / ')}`);
    }

    const { triggered, via } = detectTrigger(msg.message, ids, botMessageIds);
    if (!triggered) {
      // 诊断：群里有人 @了某人，但没匹配到机器人。
      // 这是最隐蔽的故障形态——机器人静默不响应，日志里什么都看不到。
      const mentioned =
        msg.message?.extendedTextMessage?.contextInfo?.mentionedJid ||
        msg.message?.imageMessage?.contextInfo?.mentionedJid ||
        [];
      if (mentioned.length) {
        log(`[未匹配] 群 ${chatJid} 中有人 @了 ${mentioned.join(', ')}`);
        log(`         机器人标识：${[...ids].join(' / ')}`);
        log(`         若这条本该是 @机器人，说明提及 JID 形态没被识别。`);
      }
      return;
    }

    const question = stripMentions(text);
    const sender = msg.key.participant || chatJid;
    const who = String(sender).split('@')[0];
    // 提问语言：后面所有**不经过模型**的固定回复都按它取文案
    //（未命中 / 排队已满 / 故障兜底）。
    const lang = detectLang(question);

    if (!question) {
      await send(
        chatJid,
        pickText(
          lang,
          '在的～直接把你想问的写在 @我 后面就行。',
          "Here — just put your question after the @mention and I'll take a look."
        ),
        msg
      );
      return;
    }

    // 内置命令：不查知识库。用于确认「@到了机器人 + 能回消息」这条链路是通的。
    // 排查时先测 ping —— 如果 ping 有回应而提问没回应，问题一定在检索侧。
    const cmd = question.toLowerCase();
    if (builtins && Object.hasOwn(builtins, cmd)) {
      try {
        const reply = await builtins[cmd]({ chatJid, sender });
        if (reply) await send(chatJid, reply, CONFIG.replyQuote ? msg : undefined);
        log(`[内置命令] ${who}：${cmd}`);
      } catch (err) {
        log(`[内置命令出错] ${err.message}`);
      }
      return;
    }

    // 冷却：同一会话内的提问间隔
    const now = Date.now();
    const last = lastReplyAt.get(chatJid) || 0;
    if (now - last < CONFIG.cooldownMs) {
      log(`[跳过] ${chatJid} 处于冷却期（${Math.ceil((CONFIG.cooldownMs - (now - last)) / 1000)}s）`);
      return;
    }
    lastReplyAt.set(chatJid, now);
    // 会话数很多时避免这个 Map 无限增长
    if (lastReplyAt.size > 1000) {
      const oldest = lastReplyAt.keys().next().value;
      lastReplyAt.delete(oldest);
    }

    // 队列保护：串行处理意味着排队等待时间会累加。
    // 单次回答约 1~10 秒，队列过长时后面的人要等几分钟，不如直接告知稍后再试。
    const MAX_QUEUE = CONFIG.maxQueue ?? 3;
    if (queued >= MAX_QUEUE) {
      log(`[跳过] 队列已满（${queued}/${MAX_QUEUE}），丢弃 ${who} 的提问`);
      await send(
        chatJid,
        pickText(lang, CONFIG.busyText, CONFIG.busyTextEn),
        CONFIG.replyQuote ? msg : undefined
      ).catch(() => {});
      return;
    }

    log(`[提问] ${who} @ ${isGroup ? chatJid : '私聊'}（${via}）：${question}`);

    // 串行处理，避免并发把本地模型压垮
    queued++;
    chain = chain.then(async () => {
      const t0 = Date.now();

      // 慢查询垫话：超过 pendingAfterMs 还没答出，先发一句「正在查」。
      // TT 通道首次查询要重建单号索引，实测最坏 100 秒 —— 干等像机器人掉线了。
      // 回复一发出就取消定时器；3 秒内答完则用户只会看到一条回复。
      const waitMs = Math.max(0, Number(CONFIG.pendingAfterMs ?? 0));
      let pendingTimer = null;
      if (waitMs > 0 && CONFIG.pendingText) {
        pendingTimer = setTimeout(() => {
          pendingTimer = null;
          send(
            chatJid,
            pickText(lang, CONFIG.pendingText, CONFIG.pendingTextEn),
            CONFIG.replyQuote ? msg : undefined
          ).catch(() => {});
        }, waitMs);
      }

      try {
        await liveSock().sendPresenceUpdate('composing', chatJid).catch(() => {});
        const result = await onQuestion(question, {
          chatJid,
          sender,
          lang,
          // 最近几轮问答，供「那个单子未闭环」这类**追问**落地。
          // 没有它，追问只能被当成一个全新的、缺主语的问题去猜。
          history: getHistory(chatJid),
          // 工单通道失败即将自动重试 → 先把垫话发出去，别让用户干等
          onRetry: (text) =>
            send(chatJid, text, CONFIG.replyQuote ? msg : undefined).catch(() => {}),
          // 本地工单库查不到、即将回 eFlow 实时查 → 同样先垫一句。
          // 实时查询要登录 eFlow + 翻页扫描，比本地慢得多，不垫话就是十几秒静默。
          onLive: (text) =>
            send(chatJid, text, CONFIG.replyQuote ? msg : undefined).catch(() => {}),
        });
        const text2 = truncate(result.text, CONFIG.maxReplyChars);
        if (pendingTimer) {
          clearTimeout(pendingTimer);
          pendingTimer = null;
        }
        await send(chatJid, text2, CONFIG.replyQuote ? msg : undefined);
        // 记进会话历史，供下一句追问用。答不上来的（answered=false）不记 ——
        // 「资料里没有」进历史，只会把下一轮也带偏。
        if (result.answered) rememberTurn(chatJid, question, text2);
        // 问答记录落盘：**记的是实际发出去的那一条**（text2，已截断），
        // 不是 result.text —— 分析"用户实际看到了什么"时，截断后的才是真相。
        recordQa({
          ts: new Date().toISOString(),
          chatJid,
          sender,
          question,
          answer: text2,
          answered: result.answered,
          channel: result.channel,
          tool: result.tool,
          via: result.via,
          ms: Date.now() - t0,
          lang,
          degraded: result.stats?.degraded,
          // —— 诊断列：事后能从库里回答「为什么这条走错了通道」——
          // 检索分：知识库通道才有；其他通道留 null。
          topBase: result.retrieval?.topBase,
          gap: result.retrieval?.gap,
          // top1 命中的文件名。检索里按分数排序，取前 3 个 confident 的来源，
          // 多个用 | 拼 —— 「topK 是不是被同一个文件占满」看这一列最直接。
          hitSource: formatHitSource(result.retrieval),
          // 路由/工具参数 JSON（统计/查表用）。**只存参数，不塞完整工单正文** ——
          // 那是另一条通道的事实，进了 qa 库既占空间又混口径。
          routeArgs: formatRouteArgs(result),
        });
        log(
          `[回复] ${Date.now() - t0}ms｜命中=${result.answered}` +
            // 记录回复语言：语言类问题（英文提问收到中文回答）必须能事后审计，
            // 否则只能靠群里截图定位 —— 这次排查就卡在这里。
            `｜lang=${lang}` +
            // 多单提问：记录「成功几个/共几个」，否则事后无法判断
            // 用户贴了 3 个单是不是只回了 1 个。
            (result.stats?.count > 1 ? `｜单=${result.stats.okCount}/${result.stats.count}` : '') +
            (result.retrieval
              ? `｜gap=${result.retrieval.gap.toFixed(3)} top=${result.retrieval.topBase.toFixed(3)} base=${result.retrieval.baseline.toFixed(3)}`
              : '')
        );
        // 业务层活性打点：**处理完之后**才记，不是收到就记。
        // 写进心跳，让看门狗能区分「连着但没人说话」与「连着但消息进不来」
        // —— 2026-10-06 那次故障里，前者是正常的，后者才是病，而当时
        // 心跳对这两种情况给出的信号完全一样（都是 connected: true）。
        lastMessageAt = new Date().toISOString();
        messagesHandled++;
        heartbeat();
      } catch (err) {
        if (pendingTimer) {
          clearTimeout(pendingTimer);
          pendingTimer = null;
        }
        log(`[错误] ${err.stack || err.message}`);
        const errText = pickText(lang, CONFIG.errorText, CONFIG.errorTextEn);
        // 出错也要记：**答不上的那些才最该被复盘**，
        // 只记成功的话，库里剩下的全是对的，优化就无从下手。
        recordQa({
          ts: new Date().toISOString(),
          chatJid,
          sender,
          question,
          answer: errText,
          answered: false,
          channel: 'error',
          ms: Date.now() - t0,
          lang,
        });
        await send(chatJid, errText, CONFIG.replyQuote ? msg : undefined).catch(() => {});
      } finally {
        await liveSock().sendPresenceUpdate('paused', chatJid).catch(() => {});
        queued--;
      }
    });
  }

  /**
   * 取得**当前有效**的 socket。
   *
   * 为什么不能直接用闭包里的 `sock`：重连会递归调用 startWhatsApp()，创建新的
   * sock 并覆盖 activeSock，而串行队列 chain、垫话定时器 pendingTimer 这些异步
   * 回调是在**旧的** startWhatsApp 调用里创建的，闭包捕获的是旧 sock —— 它已经
   * 被 close 分支里的 sock.ws.close() 杀掉了，拿它发包就抛 "Connection Closed"。
   *
   * 这与 notify.js 在 9ccfed0f 修的完全是同一个 bug（那里是轮询定时器拿着死
   * sock）。当时只改了 notify.js，whatsapp.js 漏了，2026-10-06 补齐。
   */
  const liveSock = () => activeSock || sock;

  async function send(jid, text, quotedMsg) {
    if (!text) return;
    const s = liveSock();
    try {
      await warmupGate();
      const sent = await s.sendMessage(jid, { text }, quotedMsg ? { quoted: quotedMsg } : undefined);
      if (sent?.key?.id) {
        botMessageIds.add(sent.key.id);
        // 只拿到 message id 不代表送达 —— 登记后由 messages.update 回执确认。
        trackAck(sent.key.id, jid, text);
      }
      return sent;
    } catch (err) {
      // 记录「本该发出但没发出去」的条数。这是用户能直接感知的症状（问了没回应），
      // 但原先连一行日志都没有 —— 失败被 .catch(()=>{}) 吞掉了。
      missedWhileDown++;
      log(`[发送失败] ${jid}：${err.message}（本次断连期间累计 ${missedWhileDown} 条）`);
      throw err;
    }
  }

  return sock;
}

function truncate(text, max) {
  const t = String(text || '').trim();
  if (t.length <= max) return t;
  return t.slice(0, max - 1).trimEnd() + '…';
}

/**
 * 把检索 top 命中来源压成一行，供 qa_log.hit_source 落盘。
 * 取前 3 个 **confident** 来源（未命中的块不算「召回了什么」），用 | 拼。
 * 没有检索（统计/查表通道）时返回 null。
 */
export function formatHitSource(retrieval) {
  const hits = retrieval?.hits;
  if (!Array.isArray(hits) || !hits.length) return null;
  const srcs = hits
    .filter((h) => h.confident)
    .map((h) => h.source)
    .filter(Boolean)
    .slice(0, 3);
  return srcs.length ? srcs.join('|') : null;
}

/**
 * 把路由/工具参数压成一段 JSON，供 qa_log.route_args 落盘。
 * 只看 `result.routeArgs`（由 tools.js 传入），**不塞完整工单正文** ——
 * 那是另一条通道的事实，进了 qa 库既占空间又混口径。
 */
export function formatRouteArgs(result) {
  const args = result?.routeArgs;
  if (!args || typeof args !== 'object') return null;
  try {
    const s = JSON.stringify(args);
    // 护栏：异常大的参数（不该有，但防手滑塞正文）截断，避免污染库
    return s.length > 500 ? `${s.slice(0, 500)}…` : s;
  } catch {
    return null;
  }
}
