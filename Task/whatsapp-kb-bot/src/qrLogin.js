/**
 * 网页扫码登录 —— 二维码请求/状态**文件通道**（my_app 设置页 ↔ 本仓库的常驻 Node 进程）。
 *
 * ## 为什么需要它
 *
 * 两个常驻进程（`src/notify.js` = P1 告警推送，`src/index.js`/`whatsapp.js` = 知识库问答）
 * 目前**只在启动连接时**把二维码打到终端（notify.js 还要求前台 TTY，见 `notify.js` 的
 * `isTTY` 判定）。没有任何 HTTP/文件通道能让它们**按需**重新出码 —— 于是运维想换号
 * 只能去 bot 目录手动跑 `npm run notify` / `npm run relogin:notify` 并盯字符二维码。
 * 本模块补上这条缺口：让 my_app 后端能通过文件请求「请给 X 设备重新出一个二维码」，
 * 并读到二维码原始字符串，交给前端渲染成真正的二维码图片。
 *
 * ## 通道约定（与 job/heartbeat 同款文件信箱语义）
 *
 * - `data/qr_request.json`：**my_app 后端写**。按设备存下标：
 *     `{ "notify": { "nonce": "<uuid>", "requested_at": "<iso>" }, "bot": { ... } }`
 *   表示「请让该设备重新出码」。nonce 用于区分先后请求。
 * - `data/qr_status.json`：**本模块写**。同样按设备存下标：
 *     `{ "notify": { "nonce", "state", "qr", "at", "message" }, "bot": { ... } }`
 *   `state` ∈ `waiting`（已收到请求、正在出码）| `qr`（码已就绪，`qr` 为原始字符串）
 *   | `connected`（扫码成功已连上）| `error`（出错，`message` 说明）。
 *
 * ⚠️ **两个设备各写各的键**（不是两个进程抢同一个扁平对象）：读-改-写时只覆盖自己那个
 * 键，避免 notify 进程写状态时把 bot 进程刚写的状态冲掉。多处读改写的竞态用「重试」收敛。
 *
 * ## 出码流程（收到请求后）
 *
 * Baileys 只有在**没有可用凭据**连接时才会出码。所以「重新出码」=
 * 1) 把凭据目录整体改名备份（沿用 `scripts/relogin.mjs` 的 `auth.bak-<时间戳>` 命名，
 *    **只改名不删除**，换号失败可改回）；2) 建回空目录；3) 触发进程重连
 *    （此时无凭据 → 必然走 `connection.update` 的 `qr` 分支出码）。
 *
 * 这与 `relogin.mjs` 的差别：relogin 只清凭据并要求人工重启，本模块**顺带触发重启**。
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';

/** 状态键取值（供调用方与测试引用，避免字面量分散）。 */
export const QR_STATE = {
  WAITING: 'waiting',
  QR: 'qr',
  CONNECTED: 'connected',
  ERROR: 'error',
};

/** 合法设备标识。my_app 侧与两个进程必须用同一套字面量。 */
export const DEVICES = ['notify', 'bot'];

/** 请求文件轮询间隔（毫秒）。出码是人工交互触发的，3s 足够灵敏又不空转太凶。 */
const POLL_MS = Number(process.env.QR_LOGIN_POLL_MS || 3000);

/**
 * 原子写 JSON：先写同目录临时文件再 rename（rename 在同分区是原子替换）。
 * 与 `notify.js` 的 `writeJsonAtomic` 同款（这里独立实现，避免跨文件耦合）。
 */
function writeJsonAtomic(p, data) {
  try {
    mkdirSync(dirname(p), { recursive: true });
    const tmp = `${p}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
    renameSync(tmp, p);
  } catch {
    /* 状态写失败不该影响主流程 */
  }
}

function readJsonSafe(p) {
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * 备份凭据目录（改名，不删除）。
 * @returns {{ok: boolean, backup?: string, error?: string}}
 */
function backupAuthDir(authDir) {
  if (!existsSync(authDir)) return { ok: true, backup: null };
  let hasCreds = false;
  try {
    hasCreds = readdirSync(authDir).some((f) => f === 'creds.json');
  } catch {
    /* 读不到目录内容按「无凭据」处理 */
  }
  // 空目录（首次登录尚未扫码）无需备份，直接复用 —— 否则会攒一堆空 backup。
  if (!hasCreds) return { ok: true, backup: null };
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const backup = join(dirname(authDir), `auth.bak-${stamp}`);
  try {
    renameSync(authDir, backup);
    return { ok: true, backup };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

/**
 * 创建一个「扫码登录」watcher。
 *
 * @param {object} opts
 * @param {'notify'|'bot'} opts.device 本进程负责的设备标识。
 * @param {string} opts.authDir 本进程的凭据目录（notify= data/auth-notify，bot= data/auth）。
 * @param {string} opts.root bot 项目根目录（用于定位 data/ 下的通道文件）。
 * @param {() => (void|Promise<void>)} opts.onRestart 触发重连的回调（断开旧 socket 并重新连接）。
 * @param {(line: string) => void} [opts.log] 日志函数（默认 console.log）。
 * @returns {{ dispose: () => void, setState: Function, publishQr: Function, isLoginRequested: () => boolean }}
 */
export function createQrWatcher({ device, authDir, root, onRestart, log = console.log }) {
  if (!DEVICES.includes(device)) {
    throw new Error(`createQrWatcher: 未知 device=${device}（应为 ${DEVICES.join(' / ')}）`);
  }
  const REQUEST_FILE = join(root, 'data', 'qr_request.json');
  const STATUS_FILE = join(root, 'data', 'qr_status.json');

  /** 本进程已处理过的 nonce；重复读到同 nonce 不再触发重启。 */
  let handledNonce = null;
  /** 当前激活请求的 nonce，用于回写状态时带上（前端据此确认是本次请求的结果）。 */
  let activeNonce = null;
  /** 是否有未完成（尚未 connected/error）的激活请求。用于放宽 notify.js 的 TTY 出码门槛。 */
  let pendingRequest = false;

  const dataDir = join(root, 'data');

  /** 写本设备的状态分片（读-改-写，只覆盖自己的键）。 */
  function setState(state, { qr = null, message = null, nonce = activeNonce } = {}) {
    const cur = readJsonSafe(STATUS_FILE) || {};
    cur[device] = {
      nonce: nonce ?? null,
      state,
      qr,
      at: new Date().toISOString(),
      message,
    };
    writeJsonAtomic(STATUS_FILE, cur);
    if (state === QR_STATE.CONNECTED || state === QR_STATE.ERROR) {
      pendingRequest = false;
    }
  }

  /** 收到 Baileys 的 qr 事件时调用：把原始二维码字符串暴露到状态文件。 */
  function publishQr(qr) {
    setState(QR_STATE.QR, { qr });
  }

  const isLoginRequested = () => pendingRequest;

  async function handleRequest(req, nonce) {
    handledNonce = nonce;
    activeNonce = nonce;
    pendingRequest = true;
    log(`[扫码登录] 收到 ${device} 设备出码请求（nonce=${nonce}），准备清凭据并重连…`);

    const bak = backupAuthDir(authDir);
    if (!bak.ok) {
      setState(QR_STATE.ERROR, { message: `备份凭据失败：${bak.error}` });
      log(`[扫码登录] ✗ 备份凭据失败：${bak.error}`);
      return;
    }
    if (bak.backup) log(`[扫码登录] 旧凭据已备份到 ${bak.backup}`);
    try {
      mkdirSync(authDir, { recursive: true });
    } catch (err) {
      setState(QR_STATE.ERROR, { message: `重建凭据目录失败：${err.message}` });
      return;
    }

    setState(QR_STATE.WAITING, { message: '已清除旧凭据，正在生成二维码…' });
    try {
      await onRestart();
    } catch (err) {
      setState(QR_STATE.ERROR, { message: `重连失败：${err.message}` });
      log(`[扫码登录] ✗ 重连失败：${err.message}`);
    }
  }

  function tick() {
    const reqAll = readJsonSafe(REQUEST_FILE);
    if (!reqAll || typeof reqAll !== 'object') return;
    const req = reqAll[device];
    if (!req || !req.nonce || req.nonce === handledNonce) return;
    // 不 await：定时器回调里 fire-and-forget，内部自行 try/catch 并回写状态。
    handleRequest(req, req.nonce).catch((err) => {
      log(`[扫码登录] ✗ 处理请求异常：${err.message}`);
      setState(QR_STATE.ERROR, { message: `处理请求异常：${err.message}` });
    });
  }

  mkdirSync(dataDir, { recursive: true });
  const timer = setInterval(tick, POLL_MS);
  // 不阻止进程退出（与 whatsapp.js 的心跳定时器同款处理）。
  if (typeof timer.unref === 'function') timer.unref();
  log(`[扫码登录] ${device} 设备通道已就绪（轮询 ${basename(REQUEST_FILE)} 每 ${POLL_MS / 1000}s）`);

  return {
    dispose: () => clearInterval(timer),
    setState,
    publishQr,
    isLoginRequested,
  };
}
