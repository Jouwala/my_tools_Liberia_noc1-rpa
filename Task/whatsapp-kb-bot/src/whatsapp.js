/**
 * WhatsApp 接入层（Baileys）。
 *
 * 职责：登录 / 重连 / 群内 @提及识别 / 文本抽取 / 发送回复。
 * 不包含任何 RAG 逻辑 —— 通过 onQuestion 回调把问题交给上层。
 */
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidGroup,
  Browsers,
} from 'baileys';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import { existsSync, mkdirSync, appendFileSync, writeFileSync, renameSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { CONFIG } from './config.js';
import { detectLang, pickText } from './lang.js';
import { selfIdentifiers, extractText, detectTrigger, stripMentions, isAllowedChat } from './mentions.js';

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

function heartbeat(extra = {}) {
  try {
    writeJsonAtomic(HEARTBEAT_FILE, {
      at: new Date().toISOString(),
      connected: heartbeatConnected,
      pid: process.pid,
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

/* ------------------- 跨重连保持的业务状态（模块级，见下方说明） ------------------- */

/** 机器人自身的多种标识形式。每次连接 open 时按新 socket 重算。 */
let selfIds = new Set();

/** 机器人自己发出的消息 id，用于识别「引用回复机器人」。有上限，防内存泄漏。 */
const botMessageIds = createBoundedIdSet(500);

/** chatJid → 上次回复时间，用于冷却。 */
const lastReplyAt = new Map();

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
}

export async function startWhatsApp({ onQuestion, builtins = null }) {
  if (!existsSync(CONFIG.authDirAbs)) mkdirSync(CONFIG.authDirAbs, { recursive: true });

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
    }

    if (connection === 'open') {
      reconnectAttempts = 0;
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
    }

    if (connection === 'close') {
      wasDisconnected = true;
      if (!downSince) downSince = Date.now();
      heartbeatConnected = false;
      heartbeat({ event: 'closed' });
      if (shuttingDown) return;

      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      if (loggedOut) {
        log('✗ 已被登出（可能手机端移除了设备）。删除 data/auth/ 后重新运行以再次扫码。');
        process.exit(1);
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
        process.exit(2);
      }

      // 清理旧 socket，否则其事件监听器会一直挂在内存里
      try {
        sock.ev.removeAllListeners('messages.upsert');
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
      } catch (err) {
        if (pendingTimer) {
          clearTimeout(pendingTimer);
          pendingTimer = null;
        }
        log(`[错误] ${err.stack || err.message}`);
        await send(
          chatJid,
          pickText(lang, CONFIG.errorText, CONFIG.errorTextEn),
          CONFIG.replyQuote ? msg : undefined
        ).catch(() => {});
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
      const sent = await s.sendMessage(jid, { text }, quotedMsg ? { quoted: quotedMsg } : undefined);
      if (sent?.key?.id) botMessageIds.add(sent.key.id);
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
