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
import qrcode from 'qrcode-terminal';
import { existsSync, mkdirSync, appendFileSync, readFileSync, writeFileSync, renameSync, statSync } from 'node:fs';
import { join, dirname, extname, basename } from 'node:path';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { CONFIG, ROOT } from './config.js';
import { createQrWatcher, QR_STATE } from './qrLogin.js';

const logger = P({ level: 'silent' });

const CHECK_ONLY = process.argv.includes('--check');
const LIST_GROUPS = process.argv.includes('--groups');

/**
 * 本进程专用的凭据目录。
 *
 * ⚠️ **绝不能与 src/index.js 共用 `CONFIG.authDirAbs`（data/auth）。**
 *
 * 2026-10-03 事故：两个进程同读一份 creds.json，等于同一个 WhatsApp 号
 * 双端登录。服务端发现后不断把其中一方顶掉（close code=440 conflict），
 * 两边的重连逻辑又互相把对方顶回来 —— 表现为**无限互踢**：
 * 日志里「2 秒连一次、连上 3 秒又断」，且**两个进程都收不到消息**，
 * 机器人对外看起来就是"启动了但不回答"。
 *
 * 凭据分开后，每个进程各自持有一个独立的已关联设备，互不干扰。
 * 代价：notify.js 首次启用需要单独扫一次码（`npm run relogin:notify`）。
 *
 * 可用环境变量 NOTIFY_AUTH_DIR 覆盖（容器/换机时用）。
 */
const AUTH_DIR = process.env.NOTIFY_AUTH_DIR || join(ROOT, 'data', 'auth-notify');

/** Baileys 的设备标识。两个进程必须不同，否则手机端「已关联的设备」里会混淆。 */
const DEVICE_LABEL = process.env.NOTIFY_DEVICE_LABEL || 'P1-Notify';

/* --------------------------------- 单实例锁 --------------------------------- */

/** 锁文件路径。模块级：常驻模式启动时置一次，重连不再重复获取。 */
let lockFile = null;

/**
 * 单实例保护。
 *
 * 为什么必须有：告警**不可重复** —— 同一条 P1 发两遍会让值班群困惑，
 * 严重时会掩盖真实告警。而本进程有两个来源可能把它拉起来：
 *   * 计划任务 `WhatsAppKB_Notify_EnsureRunning` 每 5 分钟巡检；
 *   * 人工执行 `autostart-notify.ps1`，或直接跑 node。
 * 巡检脚本靠「扫命令行 + 读心跳」判重，但那是**尽力而为**：进程刚起、心跳还没写，
 * 或两次拉起几乎同时发生时，两个实例会同时存活并各自轮询同一个信箱，
 * 于是同一作业被消费两次、告警发两遍。
 *
 * 把判重交给操作系统才可靠。这里用带 pid 的锁文件 + 存活探测：
 * 文件在但持有者已死（上次被硬杀）则回收，不会永久卡死。
 */
function acquireLock() {
  const lf = join(ROOT, 'data', 'notify.lock');
  try {
    mkdirSync(dirname(lf), { recursive: true });
    let holder = null;
    try {
      holder = JSON.parse(readFileSync(lf, 'utf8'));
    } catch {
      /* 不存在或损坏 → 视作无持有者 */
    }
    if (holder && Number.isInteger(holder.pid) && holder.pid !== process.pid) {
      let alive = false;
      try {
        process.kill(holder.pid, 0);
        alive = true;
      } catch {
        alive = false;
      }
      if (alive) {
        log(`✗ 已有推送进程在运行（pid ${holder.pid}），本进程退出以避免重复发送告警。`);
        log('  需要重启请先： powershell -NoProfile -File autostart-notify.ps1 -Stop');
        process.exit(1);
      }
      log(`! 锁文件里的 pid ${holder.pid} 已不存在（上次被强杀），回收后继续。`);
    }
    // 注意：这里刻意不用 `wx` 独占创建 —— 若进程在写锁前崩溃会留下永久锁。
    // 用「读-判活-覆盖」的写法，配合上面的存活探测，硬杀后能自愈。
    writeFileSync(lf, JSON.stringify({ pid: process.pid, at: new Date().toISOString() }), 'utf8');
    return lf;
  } catch (err) {
    // 拿不到锁不阻断发送：单实例保护是尽力而为，不能反过来弄坏主功能。
    log(`! 单实例锁建立失败（忽略，继续启动）：${err.message}`);
    return null;
  }
}

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

/* ------------------- 文件作业（图片 + 文档）配置 ------------------- */
/**
 * 扩展通道文件作业信箱 —— `whatsapp_ext_service.create_pending_job` 写入。
 * 历史背景：早先本服务**唯一**文件作业来源是浏览器扩展（用户打开 WhatsApp Web
 * 标签页，扩展侧栏轮询同一信箱），故默认路径指 `whatsapp_ext_job.json`。
 * 兼容保留：扩展仍可能向 `whatsapp_ext_job.json` 投递作业（不直接发，
 * 由本进程统一代发——扩展本身无 sock）。
 *
 * 默认值指 my_app 在本仓库的相对位置（`whatsapp-kb-bot` 与 `my_app` 同级，
 * 与 `MY_APP_DIR` 推导一致）。可被环境变量覆盖，便于异机部署。
 */
const FILE_JOB_FILE = process.env.NOTIFY_FILE_JOB_FILE
  || join(ROOT, '..', 'my_app', 'backend', 'services', 'data', 'whatsapp_ext_job.json');

/**
 * Baileys 通道文件作业信箱 —— `whatsapp_send_baileys_service.create_pending_job` 写入。
 *
 * 2026-10-08 拆分背景：原设计让 Baileys 与扩展「抢同一份作业」
 * （见旧 commit 注释中「`claim_pending_job` 原子置 running」一节）。
 * 但 my_app 后端**已经为 Baileys 通道独立投递**到 `whatsapp_send_baileys_job.json`：
 *   - 物理隔离：扩展与 Baileys **不会**同时投递到同一份文件，
 *     也就不需要「谁先认领谁发」的争抢语义。
 *   - 排查独立：Baileys 作业失败时只看自己的 job 文件，不会和扩展的历史记录混在一起。
 *   - 配额独立：未来想给 Baileys 单独调 `maxImages` 不影响扩展。
 *
 * 故本进程每 tick **扫两份**信箱（先扩展，后 Baileys），一次 tick 仍只发一单
 * （避免长发送挡住下一轮）。两份信箱的 `claimFileJob` 各自原子写自己的文件，
 * 互不影响。
 *
 * 可被环境变量覆盖。扩展 / Baileys 任意一方**不投递**对应信箱时，
 * 扫到不存在的文件按"无作业"处理（见 `claimFileJob`）。
 */
const FILE_JOB_FILE_BAILEYS = process.env.NOTIFY_FILE_JOB_FILE_BAILEYS
  || join(ROOT, '..', 'my_app', 'backend', 'services', 'data', 'whatsapp_send_baileys_job.json');

/** 本进程当前已知的所有文件作业信箱（按优先级排列，先扫先发）。 */
const FILE_JOB_FILES = [FILE_JOB_FILE, FILE_JOB_FILE_BAILEYS];

/** 文件作业心跳（仅作"本进程活着"证据；与文本的 notify_heartbeat.json 是同一文件，复用即可）。 */

/**
 * 单作业防重：相同 `kind|path|file_name|mtime` 的 payload 在一次作业内**只发一次**。
 * 这道防线是**双保险**——主防线是「抢同一份作业后另一边看到 running 就放弃」，
 * 本防线治「my_app 侧被重投或内部重试导致同一 item 多次出现在作业里」。
 */
function payloadSignature(item) {
  const kind = String(item?.kind || 'image');
  const path = String(item?.path || item?.url || item?.name || '');
  const name = String(item?.file_name || item?.name || '');
  let mtime = '';
  try {
    if (path && existsSync(path)) mtime = String(statSync(path).mtimeMs | 0);
  } catch { /* 读不到 mtime 也照常处理 */ }
  const key = `${kind}|${path}|${name}|${mtime}`;
  return createHash('sha256').update(key).digest('hex').slice(0, 16);
}

/**
 * my_app 投递到作业文件里的 `items[].path` 形如 `C:\...\ALL.png`，
 * Baileys 进程要 `fs.readFileSync` 这条路径，所以必须**保持绝对路径**。
 * `whatsapp_ext_service.create_pending_job` 写入时已用绝对路径（来自 `SITE_OUTAGE_DIR`），
 * 这里不再做解析，避免与 my_app 侧的语义分叉。
 */

/**
 * MIME 探测：白名单兜底，缺省 `application/octet-stream`。
 * 不要引第三方 mime 库 —— 仅 5 类扩展，复制一份 5 行表比 `npm i mime-types` 划算。
 */
const _MIME_BY_EXT = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.pdf': 'application/pdf',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel',
  '.csv': 'text/csv',
  '.txt': 'text/plain',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};
function mimeFor(filePath) {
  return _MIME_BY_EXT[extname(String(filePath)).toLowerCase()] || 'application/octet-stream';
}

/**
 * 僵尸作业判定阈值（毫秒）：作业处于 `running` 超过此时长仍未回报，
 * 视为僵尸并允许重新认领（见 `claimJob`）。
 *
 * 取 10 分钟 —— 必须**远大于**正常发送耗时（`sendMessage` 是秒级，
 * 多群多单最坏也就几十秒），否则会把**正在发送中**的作业当僵尸抢走，
 * 又变回重复发送。这与 `tt_alarm_job.STALE_RUNNING_SECONDS`（1 小时）
 * 是同一道防线，取值更短是因为 Baileys 不需要等浏览器渲染。
 * 需要更快恢复时可调环境变量 `NOTIFY_STALE_RUNNING_MS`。
 */
const STALE_RUNNING_MS = Number(process.env.NOTIFY_STALE_RUNNING_MS || 600000);

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
 * 网页扫码登录 watcher（模块级：重连会再次进入 start()，只能建一次）。
 * 见 `src/qrLogin.js`。仅常驻模式创建；`--check` / `--groups` 是一次性自检，不需要。
 */
let qrWatcher = null;

/**
 * 是否正处于「网页扫码」发起的主动重启中。
 * 主动重启会关掉旧 socket，旧 socket 的 close 回调若照常重连会与新连接撞车，
 * 故用它抑制旧回调自己排的那次重连（见 connection.update 的 close 分支）。
 */
let restarting = false;

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

/**
 * 认领待发作业（有则返回，无则 null）。
 *
 * ## 为什么认领时必须就地把状态推进到 `running`（2026-10-05 修复）
 *
 * 早先这里只判 `pending` 就返回，**不改状态** —— 当时认为「本进程单实例，
 * 不存在多实例重复认领的问题」（见 `wa_notify_service.py` 的模块 docstring）。
 * 那个推理只覆盖了「多实例」，**漏掉了「单实例重入」**：
 *
 * 轮询是 `setInterval(async () => { await runJob(...) })`（见文件末尾），
 * 而 **`setInterval` 不会等待上一次 async 回调结束**。`runJob` 里每条消息
 * 都要 `await sock.sendMessage()` 走网络往返（秒级），这段时间作业文件**始终是
 * `pending`**（终态要等 `finishJob` 才写）。于是**每一个 tick 都会重新认领同一单、
 * 再发一遍**，发送次数 = 网络往返时长 ÷ `POLL_MS`。
 *
 * 实测仿真（`POLL_MS=5000`、往返 1s 时约 2~3 遍；`WAIT_SECONDS=120`，
 * 极端情况可叠到二十几遍）：同一条 P1 告警在值班群里重复出现。
 *
 * 这正是旧扩展通道**本来就有的**防护 —— `tt_alarm_job.py` 与
 * `whatsapp_ext_service.py` 的 `claim_pending_job` 都是「认领即置 `running`」，
 * 注释写明是为了「避免多个扩展实例重复发送同一作业」（`tt_alarm_job.py:11,142`）。
 * 换通道时不该把它丢掉。
 *
 * 故这里恢复该语义：**读到 `pending` 就立刻原子写回 `running` + `claimed_at`**。
 * 这样第二轮 tick 读到的是 `running`，直接不认领。同时它与「僵尸回收」天然兼容——
 * 进程若在发送中途被杀，作业停在 `running`，重启后由 `claimJob` 的
 * `STALE_RUNNING_MS` 判定允许重新认领（否则一次崩溃会把信箱永久堵死，
 * 那正是 `tt_alarm_job.py:14-24` 记录的 2026-10-01 事故形态）。
 */
function claimJob() {
  const job = readJsonSafe(JOB_FILE);
  if (!job || typeof job !== 'object') return null;

  const status = String(job.status || '');
  if (status === 'running') {
    // 僵尸回收：认领后迟迟不回写（进程被杀 / 崩溃）时允许重新认领。
    // 阈值必须**远大于**正常发送耗时（秒级），否则正常发送中的作业会被当僵尸抢走，
    // 又变回重复发送。
    const claimedAt = Date.parse(job.claimed_at || '');
    const age = Number.isFinite(claimedAt) ? Date.now() - claimedAt : Infinity;
    if (age < STALE_RUNNING_MS) return null;
    log(`! 作业 ${job.job_id || '(无 id)'} 自认领后 ${Math.round(age / 1000)}s 未回报，`
      + `判定为僵尸并重新认领（阈值 ${STALE_RUNNING_MS / 1000}s）`);
  } else if (status !== 'pending') {
    return null;
  }

  // 认领即置 running：这是防重入的**关键一步**，不能省。
  // 写失败则**不认领**（宁可这一轮不发，也不能在状态未推进的情况下发出去 ——
  // 那等于退回到"每 tick 重发一遍"）。
  const claimed = { ...job, status: 'running', claimed_at: new Date().toISOString() };
  try {
    writeJsonAtomic(JOB_FILE, claimed);
  } catch (err) {
    log(`! 认领作业写回失败（本轮不发送，避免重复）：${err.message}`);
    return null;
  }
  return claimed;
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

/* -------------------- 文件作业：认领 / 处理 / 完成 -------------------- */

/**
 * 文件作业状态机（与文本通道同构：`pending` → `running` → `done`/`failed`）：
 *  - 同一文件被两个**不同认领方**（浏览器扩展 / 本进程）读时，靠文件级 `running` 字段互斥；
 *  - 认领方抢到 `running` 后**马上把 items 写回**（my_app 投递时 items 为空，
 *    真正的清单要等认领方在写 `running` 那一瞬 `build_outbox_payload()` 重新扫盘），
 *    这点与文本通道（投递时就带 messages）不同。
 *
 * 因此本函数不复用 `claimJob` 的「读 → 改状态 → 写回」三段，而是直接读
 * `whatsapp_ext_service.claim_pending_job` 一样的语义（认领即置 running + items 写回），
 * 再加 zombie 回收（`STALE_RUNNING_MS` 同值）。
 */
/**
 * 从指定信箱认领文件作业。文件不存在 / 损坏 / 已处于 done|failed 状态
 * 均返回 `null`（不抛异常，调用方当"无作业"处理）。
 *
 * 设计要点（与 `claimJob` 文本通道同源，但拆出参数让多信箱可共用）：
 *  - 认领即原子置 `running` + 写回，防 `setInterval` 重入（见 `runFileJob` 注释）。
 *  - items 必须**已在文件里** —— 那是 my_app 侧投递时一次性写好的
 *    （`create_pending_job` 已经把磁盘绝对路径写进 `items[].path`），
 *    本进程不重新扫盘，避免与 my_app 侧分叉。
 *  - zombie 回收：超过 `STALE_RUNNING_MS` 未回报的 running 作业可重新认领。
 *
 * @param {string} filePath - 信箱文件绝对路径
 * @returns {object|null} 认领成功返回作业对象（含 status='running'）；否则 null
 */
function claimFileJob(filePath) {
  let job;
  try {
    job = JSON.parse(readFileSync(filePath, 'utf8'));
  } catch {
    return null;   // 文件不存在 / 损坏 → 当作"无作业"
  }
  if (!job || typeof job !== 'object') return null;

  const status = String(job.status || '');
  if (status === 'running') {
    const claimedAt = Date.parse(job.claimed_at || '');
    const age = Number.isFinite(claimedAt) ? Date.now() - claimedAt : Infinity;
    if (age < STALE_RUNNING_MS) return null;
    log(`! 文件作业 ${job.job_id || '(无 id)'} 自认领后 ${Math.round(age / 1000)}s 未回报，`
      + `判定为僵尸并重新认领（阈值 ${STALE_RUNNING_MS / 1000}s，file=${path.basename(filePath)}）`);
  } else if (status !== 'pending') {
    return null;
  }

  if (!Array.isArray(job.items) || job.items.length === 0) {
    // 状态是 running 但没 items：多半是另一方（my_app 进程内、扩展）刚置 running
    // 还没来得及写回 items —— 不抢，否则会拿到一个空作业。
    return null;
  }

  const claimed = {
    ...job,
    status: 'running',
    claimed_at: new Date().toISOString(),
    claimed_by: 'baileys',
  };
  try {
    writeJsonAtomic(filePath, claimed);
  } catch (err) {
    log(`! 文件作业认领写回失败（本轮不发送，避免重复）：${err.message}`);
    return null;
  }
  return claimed;
}

/**
 * 回写文件作业结果到指定信箱。
 * @param {string} filePath - 信箱文件绝对路径
 */
function finishFileJob(filePath, job, ok, groupsSent, errors) {
  writeJsonAtomic(filePath, {
    ...job,
    status: ok ? 'done' : 'failed',
    completed_at: new Date().toISOString(),
    result: { ok, groups_sent: groupsSent, errors },
  });
}

/**
 * 处理一个文件作业：每条 item × 每个 group 走一次 `sendMessage`。
 *
 * 三条铁律（与文本通道同源，参见 runJob 的注释）：
 *  1. 服务端回执 (`res.key.id`) 才是送达判据；缺 id 一律视为失败；
 *  2. 单条失败不重试到群里 —— 避免重复；统一由 my_app 的 `auto_retry_failed` 决定；
 *  3. 同 `payloadSignature` 在一次作业内只发一次（双保险，主防线是抢 running）。
 */
async function runFileJob(sock, job) {
  const items = Array.isArray(job.items) ? job.items : [];
  const groups = Array.isArray(job.groups) ? job.groups : [];
  const seen = new Set();
  const groupsSent = [];
  const errors = [];
  const intervals = (CONFIG.notify && CONFIG.notify.fileSend) || {};

  const perItemMs = Math.max(0, Number(intervals.sendIntervalMs ?? 2000));
  const perGroupMs = Math.max(0, Number(intervals.perGroupDelayMs ?? 8000));
  const maxItems = Math.max(1, Number(intervals.maxImages ?? 6));
  const maxDocs = Math.max(1, Number(intervals.maxDocuments ?? 1));

  if (!items.length) {
    finishFileJob(job._filePath, job, false, [], ['作业里没有 items']);
    return;
  }
  if (!groups.length) {
    finishFileJob(job._filePath, job, false, [], ['作业里没有 groups']);
    return;
  }

  // 群解析：任一解析不了**整个作业失败**（与文本通道同语义；告警/截图任务都是
  // 「这条必须到群里」，少发一个群就是漏发）。
  const jids = [];
  for (const g of groups) {
    const jid = resolveGroup(g);
    if (!jid) {
      finishFileJob(job._filePath, job, false, [], [
        `找不到群「${g}」对应的 JID（当前已知 ${groupIndex.size} 个群）。`
        + `请确认机器人账号已加入该群，或用 --groups 查看可用群名。`,
      ]);
      return;
    }
    jids.push(jid);
  }

  // 作业级配额：图片与文档分开计（业务上图片多、文档少）。超出部分**跳过**不报错
  // —— 配额是软上限，目的是「单次突增防风控」而不是「必须发齐」。
  let imageBudget = maxItems;
  let docBudget = maxDocs;
  const skippedByBudget = [];

  for (let idx = 0; idx < items.length; idx++) {
    const item = items[idx] || {};
    const sig = payloadSignature(item);
    if (seen.has(sig)) {
      log(`! 跳过重复 payload（去重）：${sig}`);
      continue;
    }
    seen.add(sig);

    // 判断类型：扩展通道与 my_app 侧已经按 `kind` 区分（`whatsapp_job_claim`），
    // 但 my_app 的 `whatsapp_ext_service` **没有**显式设 kind —— items 默认为 image。
    // 这里按 mime 与扩展名再判断一次（双重保险，宁可把 xlsx 错当 image 也不漏发）。
    const itemPath = String(item.path || item.url || item.name || '');
    const itemName = String(item.file_name || item.name || (itemPath ? itemPath.split(/[\\/]/).pop() : 'file'));
    const ext = extname(itemName).toLowerCase();
    const isDoc = !!item.kind
      ? item.kind === 'document'
      : !!ext && ext !== '.png' && ext !== '.jpg' && ext !== '.jpeg'
        && ext !== '.gif' && ext !== '.webp';

    if (isDoc) {
      if (docBudget <= 0) { skippedByBudget.push(`doc:${itemName}`); continue; }
      docBudget--;
    } else {
      if (imageBudget <= 0) { skippedByBudget.push(`image:${itemName}`); continue; }
      imageBudget--;
    }

    // 读盘：必须在 send 前读完，避免「读盘失败」算「发送失败」的语义混淆。
    // `image` 类型在 Baileys 里也接受 `Buffer`（即 `Uint8Array` 的 Buffer 实例），
    // `document` 同理；不要用 `data:` URL。
    let payload;
    try {
      const buf = readFileSync(itemPath);
      payload = { buf, size: buf.length };
    } catch (err) {
      errors.push(`${itemName}：读盘失败：${err.message}`);
      log(`✗ 读盘失败 ${itemPath}：${err.message}`);
      continue;
    }
    if (!payload.buf || payload.buf.length === 0) {
      errors.push(`${itemName}：文件为空（0 字节）`);
      log(`! 跳过空文件：${itemPath}`);
      continue;
    }
    const mimetype = mimeFor(itemName);
    const caption = String(item.caption || '').trim();

    for (let gi = 0; gi < jids.length; gi++) {
      const jid = jids[gi];
      // 群间延时：仅**非首群**且**上一图/文档真发出**时等；失败不延时（避免问题被掩盖）
      if (gi > 0 && perGroupMs > 0) {
        await sleep(perGroupMs);
      }
      // 护栏：每发一条前先确认连接还活着。`sockRef` 是模块级（见 start() 末尾的
      // sockRef = sock），重连后旧 sock 已被 sock.ws.close() 杀掉 —— 但如果在
      // 重连前最后那几百毫秒的轮询里跑进来，旧 sock 拿到的会是 "Connection Closed"。
      // 显式 connected 校验可让单条失败快速回错，而不是让一次 8s 群间 sleep 之后
      // 才发现整个连接已死，浪费单作业的 600s 窗口。
      if (!connected || !sockRef) {
        errors.push(`${itemName} → ${jid}：连接已断开（abort 后续）`);
        log(`✗ ${itemName} → ${jid}：连接断开，本作业终止`);
        finishFileJob(job._filePath, job, false, groupsSent, errors);
        return;
      }
      try {
        let res;
        if (isDoc) {
          // document：只发文件，不带 caption（WhatsApp 文档消息不支持 caption，
          // 与 `whatsapp_ext_service` 走发送的语义一致）。
          res = await sock.sendMessage(jid, {
            document: payload.buf,
            fileName: itemName,
            mimetype,
          });
        } else {
          // image：caption 走 `caption` 字段，长度 1024 以内（WhatsApp 限制）。
          const safeCaption = caption.length > 1024 ? caption.slice(0, 1020) + '…' : caption;
          res = await sock.sendMessage(jid, {
            image: payload.buf,
            caption: safeCaption || undefined,
            mimetype,
          });
        }
        if (res?.key?.id) {
          log(`✓ 已发送 ${itemName} → ${jid}（msg id ${res.key.id}，${(payload.size / 1024).toFixed(1)}KB）`);
          if (!groupsSent.includes(jid)) groupsSent.push(jid);
          heartbeat({ lastSendKind: isDoc ? 'document' : 'image' });
        } else {
          errors.push(`${itemName} → ${jid}：sendMessage 未返回 message id，无法确认`);
          log(`! ${itemName} → ${jid}：未返回 message id`);
          heartbeat({ lastSendError: `no_message_id:${itemName}` });
        }
      } catch (err) {
        errors.push(`${itemName} → ${jid}：${err.message}`);
        log(`✗ 发送失败 ${itemName} → ${jid}：${err.message}`);
        heartbeat({ lastSendError: `${itemName}:${err.message}` });
      }
      // 单条之间的速率控制：仅在**还有下一条**时等。
      if (idx < items.length - 1 && perItemMs > 0) {
        await sleep(perItemMs);
      }
    }
  }

  if (skippedByBudget.length) {
    log(`! 因单作业配额跳过：${skippedByBudget.join(', ')}`);
    // 2026-10-11：配额跳过必须进 errors，否则 my_app 侧看不到截断 ——
    // `ok = groupsSent.length > 0` 只要求「有一个群收到东西」，一份附件被
    // 静默丢掉时仍会报 ok=true（SP Online 报表的 Outbound.xlsx 就这么丢过）。
    // 进 errors 后 my_app 的 dispatch_items 会判失败并回退 Playwright，不再静默丢文件。
    for (const s of skippedByBudget) {
      errors.push(`因单作业配额被跳过：${s}`);
    }
  }

  const ok = groupsSent.length > 0;
  finishFileJob(job._filePath, job, ok, groupsSent, errors);
  log(`[文件作业完成] ${job.job_id || '(无 id)'} 成功群 ${groupsSent.length} / 错误 ${errors.length}`
    + (skippedByBudget.length ? ` / 配额跳过 ${skippedByBudget.length}` : ''));
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
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
  // 单实例保护只在**常驻模式**生效。--check / --groups 是一次性自检，
  // 与常驻进程并存是正常用法（排查时正需要它），不该被锁挡住。
  if (!CHECK_ONLY && !LIST_GROUPS && !lockFile) {
    lockFile = acquireLock();
  }

  // 网页扫码登录 watcher：只在常驻模式创建（自检命令 --check / --groups 是一次性退出，
  // 不需要，也不该在它们退出前留下出码状态）。模块级 + 判重保证重连不会重复创建。
  if (!CHECK_ONLY && !LIST_GROUPS && !qrWatcher) {
    qrWatcher = createQrWatcher({
      device: 'notify',
      authDir: AUTH_DIR,
      root: ROOT,
      log,
      // 触发重连：断开当前 socket（若在），再跑一次 start()。
      // 此时凭据已由 watcher 清空，Baileys 无凭据连接 → 必然走 qr 分支重新出码。
      onRestart: async () => {
        // 置位让旧 socket 的 close 回调知道这是主动重启 —— 否则它会再排一次 start()，
        // 与这里的那次重连撞车（多出一个 socket / 多一轮出码）。旧回调见下述 close 分支。
        restarting = true;
        try {
          sockRef?.ev?.removeAllListeners('connection.update');
          sockRef?.ev?.removeAllListeners('creds.update');
          sockRef?.ws?.close();
        } catch {
          /* 忽略："断开旧连接" 失败不应阻断重启 */
        }
        try {
          await start();
        } finally {
          restarting = false;
        }
      },
    });
  }

  // 凭据目录**不存在不算错误** —— 首次部署就是这样，此时应当逐个出二维码让用户扫码。
  //
  // 早先这里直接 exit(1) 并提示「请执行 npm run relogin:notify」，而 relogin.mjs
  // 发现目录不存在时又回一句「直接运行 npm run notify 即可」——
  // **两个脚本互相指向对方，用户被卡死在中间**（2026-10-03 实测踩到）。
  //
  // 根因是把职责搞混了：`relogin` 的职责是**清掉旧凭据**，它并不产生新凭据；
  // 新凭据是 Baileys 连接时通过二维码生成的。所以「首次登录」必须由本进程自己
  // 承担 —— 目录不存在就建一个空的，让 useMultiFileAuthState 正常出二维码。
  if (!existsSync(AUTH_DIR)) {
    log(`! 凭据目录不存在，按首次登录处理：${AUTH_DIR}`);
    mkdirSync(AUTH_DIR, { recursive: true });
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    // 设备名区分两个进程，否则手机端「已关联的设备」里两个都叫同一个名字，
    // 排查 440 时根本分不清该踢哪一个。
    browser: [DEVICE_LABEL, 'Desktop', '1.0.0'],
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
    // 与 src/whatsapp.js 保持一致，理由见那里的注释：Baileys 默认就是 30s 探活，
    // 显式写出仅为让「多久探活一次」在代码里可见（排查时不必翻 node_modules）。
    // 不调更短：更频繁的 ping 不会更稳，反而更可能被服务端限流。
    keepAliveIntervalMs: 30_000,
    connectTimeoutMs: 60_000,
  });
  sockRef = sock;

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      // 二维码该不该打出来，取决于**有没有人看得见**，而不是取决于它是哪个进程。
      //
      // 早先这里无条件 exit(1)，理由是「推送进程隐藏运行，二维码没人看得见」。
      // 那个理由只在**由计划任务以隐藏窗口拉起**时成立；用户手动在前台跑
      // `npm run notify` 时窗口是可见的，二维码完全应该正常显示 ——
      // 否则首次登录永远没有出路（见上面 AUTH_DIR 那段注释里的死循环）。
      //
      // 优先把二维码原始字符串写进状态文件，供 my_app 设置页渲染（见 src/qrLogin.js）。
      // 这一步是「网页扫码」链路的关键：把只在终端可见的码变成文件里可被后端读到的码。
      qrWatcher?.publishQr(qr);

      // 判据用 stderr 是否为 TTY：前台跑 → TTY，可以扫码；
      // 计划任务/重定向 → 非 TTY，打出来只会污染日志，此时才拒绝并说明怎么办。
      //
      // ⚠️ 例外（2026-10-12）：若本次出码是**网页扫码登录**请求触发的
      // （qrWatcher.isLoginRequested()），即使隐藏运行也**不 exit(1)** ——
      // 因为二维码已经通过状态文件给了前端，用户正在浏览器里扫，不需要终端。
      // 否则隐藏窗口场景下从网页发起的扫码永远走不通。
      if (process.stderr.isTTY) {
        console.log('\n=== 请用 WhatsApp 扫码登录（P1 告警推送通道）===');
        console.log('手机 WhatsApp → 设置 → 已关联的设备 → 关联设备\n');
        qrcode.generate(qr, { small: true });
        console.log(`\n（扫码后凭据会保存在 ${AUTH_DIR}，之后免扫码）`);
        console.log('（这是与知识库机器人**相互独立**的一个设备，两边各扫各的）\n');
        return; // 继续等下一次 connection.update，扫完就会 open
      }
      if (qrWatcher?.isLoginRequested()) {
        log('二维码已写入状态文件，请在 my_app 设置页扫码（隐藏运行，不在此终止进程）。');
        return; // 继续等扫码后的 connection.update
      }
      log('✗ 需要扫码登录，但当前是隐藏运行（无人可见二维码）。');
      log('  请在可见的终端里手动执行：npm run notify');
      log('  扫码成功后 Ctrl+C 退出，再由计划任务托管常驻。');
      process.exit(1);
    }

    if (connection === 'open') {
      reconnectAttempts = 0;
      connected = true;
      log(`✓ 已连接。凭据目录：${AUTH_DIR}`);
      // 扫码成功（或本来就有有效凭据）：若本次是网页扫码请求触发的，回写 connected。
      qrWatcher?.setState(QR_STATE.CONNECTED, { message: '已连接' });
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
      // 主动重启（网页扫码登录）触发的关闭：新连接已由 onRestart 里的 start() 接手，
      // 这里不再排重连，否则两个 socket 并存、出两份码。
      if (restarting) return;

      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log('✗ 已被登出（手机端可能移除了该设备）。');
        log('  请执行 npm run relogin:notify 重新扫码后重启本进程。');
        qrWatcher?.setState(QR_STATE.ERROR, { message: '已被登出（手机端可能移除了该设备）' });
        process.exit(1);
      }

      // 440 = connectionReplaced：同账号的另一个会话把本连接顶掉了。重连只会互相顶号，
      // 两个进程都收不到消息 —— 详见 src/whatsapp.js 里同一处判断的说明。
      // 本进程已改用独立凭据目录（AUTH_DIR），正常情况下不该再出现 440；
      // 一旦出现，说明仍有第二个进程在用 data/auth-notify，或凭据又被共用。
      // （枚举名是 connectionReplaced；baileys 6.7.24 没有 `conflict` 成员。）
      if (code === DisconnectReason.connectionReplaced || code === 440) {
        log('✗ 连接被同账号的另一个会话顶掉（code=440 conflict）。');
        log(`  检查是否有第二个进程在用凭据目录 ${AUTH_DIR}。`);
        log('  本进程不再重连（继续重连只会与对方互相顶号）。');
        qrWatcher?.setState(QR_STATE.ERROR, { message: '连接被同账号的另一个会话顶掉（code=440）' });
        process.exit(2);
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
      // 必须用全局 sockRef，且重连后必须真的 open 才投递。
      // ⚠️ 这里不能用闭包里的局部 `sock`：重连会递归调用 start() 创建新 sock，
      // 但 pollTimer 只在第一次 start() 建一次（上面的 if(!pollTimer)），
      // 若不改用全局 sockRef，轮询会一直拿着已被 sock.ws.close() 杀掉的旧 sock 发包，
      // 连接恰好在边缘时就会拿到 "Connection Closed" 而失败（2026-10-01 实测命中）。
      if (!connected || !sockRef) return;

      // 先扫文本告警信箱（保持原行为，避免影响 P1 告警文本通道）
      const textJob = claimJob();
      if (textJob) {
        try {
          await runJob(sockRef, textJob);
        } catch (err) {
          log(`✗ 处理文本作业异常：${err.stack || err.message}`);
          try {
            finishJob(textJob, false, [], [`推送进程内部异常：${err.message}`]);
          } catch {
            /* 回写都失败时只能靠心跳暴露 */
          }
        }
        heartbeat();
        return;   // 一次 tick 只发一单，避免长发送挡住下一轮
      }

      // 再扫文件作业信箱 —— 2026-10-08 起扫两份（扩展 + Baileys），按 FILE_JOB_FILES 顺序。
      // 一次 tick 仍只发一单（避免长发送挡住下一轮）；第一份信箱没作业时立刻扫第二份。
      // 详见模块顶部 `FILE_JOB_FILE` / `FILE_JOB_FILE_BAILEYS` 的注释。
      let fileJob = null;
      let fileJobPath = null;
      for (const fp of FILE_JOB_FILES) {
        const claimed = claimFileJob(fp);
        if (claimed) {
          // 把信箱路径挂到作业对象上，runFileJob 内部的 finishFileJob 调用据此回写。
          // _filePath 是约定的私有字段，不写入作业文件（writeJsonAtomic 时一并持久化
          // 也无副作用：my_app 侧 job_staleness 读 .status / .claimed_at 等公共字段，
          // 不会因为多一个 _filePath 字段而误判）。
          claimed._filePath = fp;
          fileJob = claimed;
          fileJobPath = fp;
          break;
        }
      }
      if (fileJob) {
        try {
          await runFileJob(sockRef, fileJob);
        } catch (err) {
          log(`✗ 处理文件作业异常（${path.basename(fileJobPath)}）：${err.stack || err.message}`);
          try {
            finishFileJob(fileJobPath, fileJob, false, [], [`推送进程内部异常：${err.message}`]);
          } catch {
            /* 同上 */
          }
        }
        heartbeat();
        return;
      }

      heartbeat();
    }, POLL_MS);
    log(`✓ 信箱轮询已启动（每 ${POLL_MS / 1000}s）：${JOB_FILE}`);
    log(`✓ 文件作业轮询已启动（同 tick，按优先级）：${FILE_JOB_FILES.map(f => path.basename(f)).join(' → ')}`);
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
