#!/usr/bin/env node
/**
 * 网页问答服务 —— 把知识库问答能力以 HTTP 暴露给门户页面。
 *
 * ## 为什么单独一个进程
 *
 * 群里那条链路（src/index.js）里有一半是 Baileys 收发消息，与「回答一个问题」
 * 无关。网页版要的是后者，所以这里**只**复用答题侧：
 *
 *   routeAnswer()  ← 唯一入口（src/answer.js）
 *     ├─ tt          单号分析（实时查工单库）
 *     ├─ stats       工单聚合统计
 *     ├─ lookup      查表（告警码 / 压缩 / 级别规则）
 *     ├─ sitealarm   站点实时告警
 *     ├─ vmaxcca     VMAX CCA 用户查询
 *     └─ kb          知识库向量检索（RAG）
 *
 * ⚠️ **不新建第二套答题逻辑**：分流、查表、RAG 全在 routeAnswer 里，
 * 这里只做「HTTP 外壳 + 会话记忆 + 并发闸门」。改答案口径只改 routeAnswer，
 * 网页版与群里自动同步。
 *
 * ## 为什么用 node:http 而不是 express
 *
 * 本项目不引新依赖（见工作区 AGENTS.md 原则 7）。node:http 够用：
 * 一个 POST /ask、一个 GET /health，没有路由树需求。
 *
 * ## 会话记忆（多轮追问）
 *
 * 「那个单子未闭环」这类追问单看没有主语，必须有上一轮上下文才能落地
 * （见 src/rag.js 的 resolveFollowUp 与 src/tools.js 的 buildRouterPrompt）。
 * 群里靠 src/whatsapp.js 的 chatHistory；这里用同一套语义 —— 按
 * **会话 id**（网页端传一个稳定的 client id）记住最近几轮，问答时作为
 * `history` 传给 routeAnswer。
 *
 * ⚠️ 记忆只在内存里，进程重启即清空 —— 与群里一致（见 src/memory.js 的理由：
 * 落盘要处理跨天污染与隐私残留，收益很小）。
 *
 * ## 对话模型（网页版专属，**不跟** my_app 的 AI 设置走）
 *
 * 2026-10-28 统一：网页助手走 **`https://192.168.100.27:8443/api/v1`** 的
 * `mimo-v2.6-flash`（与群机器人同一个 OWU 实例、同一个模型）。
 * 之前是 `.27:3000` + `qwen2.5:7b-instruct`，那台已经不再向静态 key 暴露模型
 * （`/api/v1/models` 返回空列表、chat 回 400 Model not found），故整体迁移。
 *
 * ⚠️ base 是 `/api/v1` 而不是 `/v1`：`/v1/*` 会落到前端 SPA（POST 回 405）。
 * ⚠️ 8443 是内网私有 CA 签的证书 —— 信任链由 `src/config.js` 的 `applyChatCa()`
 *    统一装好（本文件 import 了 config.js，所以自动生效）。
 *
 * 为什么不像 src/index.js 那样 `loadRuntimeConfig()` 跟 my_app 设置走：
 * my_app 的 AI 设置页是**群机器人**的开关，改它会影响群里所有人；网页助手是另一条
 * 交付面，产品上要求「用哪个模型」可独立决定。所以这里只读自己的 QA_* 环境变量，
 * 与群链路解耦 —— 网页调模型不会因为别人改了设置页而静默换模型。
 *
 * ## OWU 不可用时的本地兜底
 *
 * 2026-10-27 实测：OWU 的静态 API Key 若权限不足（403 / Model not found），
 * 整条 RAG 就答不出来。为了「OWU 抽风时网页还能用」，这里加了一层兜底：
 * 改打 **.27 的 Ollama（OpenAI 兼容）**。仅在**通道级错误**
 * （401/403/404/Model not found/超时/连不上/证书）时触发，业务错误不兜底
 * （否则会把 bug 伪装成「模型没答上来」）。
 *
 * 2026-10-28 注意：兜底模型**不再是同一个模型名** —— `mimo-v2.6-flash` 是云端代理，
 * Ollama 上没有这份权重，拿它去问 Ollama 只会 model not found。所以兜底目标单列为
 * `QA_FALLBACK_MODEL`（默认 `qwen2.5:7b-instruct`）：**降质但可用**，这是刻意的取舍。
 * 兜底持续 QA_OWU_COOLDOWN_MS（默认 5 分钟）后再试 OWU，避免每问一次先白等一次 403。
 *
 * ## 启动
 *
 *   node --env-file-if-exists=.env src/http-server.js
 *
 * 端口：环境变量 QA_HTTP_PORT，默认 9269。
 * 只绑回环（127.0.0.1）—— 对外暴露由 nginx / my_app 后端中转，
 * 保持「服务本身不监听公网」这条边界。
 */
import { createServer } from 'node:http';
import { statSync } from 'node:fs';

import { CONFIG, RUNTIME_CONFIG, FALLBACK_CONFIG } from './config.js';
import { loadIndex } from './rag.js';
import { routeAnswer, describeRoute } from './answer.js';
import { loadLookupsOnce } from './tools.js';
import { validateProvider, providerInfo } from './llm.js';
import { healthCheck } from './ollama.js';

const PORT = Number(process.env.QA_HTTP_PORT || 9269);
const HOST = process.env.QA_HTTP_HOST || '127.0.0.1';

/* ---------------------------- 对话模型通道 ---------------------------- */

/** OWU 的 OpenAI 兼容 base。注意是 `/api/v1`（静态 key 只认这条，见 config.js 的说明）。 */
const OWU_BASE = (process.env.QA_OWU_BASE || 'https://192.168.100.27:8443/api/v1').replace(/\/+$/, '');
const QA_MODEL = process.env.QA_CHAT_MODEL || 'mimo-v2.6-flash';
/**
 * 兜底模型 —— **必须与 QA_MODEL 分开**。
 *
 * 2026-10-28 统一到 8443 之后，OWU 上只有 `mimo-v2.6-flash`（云端代理，Ollama 上没有这个权重）。
 * 旧的兜底逻辑是「同一个模型名改打本地 Ollama」，那条前提已经不成立：拿 mimo 去问 Ollama
 * 只会得到 model not found，兜底等于没有。所以兜底目标单列，默认用 .27 Ollama 上确实存在的
 * `qwen2.5:7b-instruct` —— 质量不同，但「OWU 抽风时网页还能答」这个目标保住了。
 */
const FALLBACK_MODEL = process.env.QA_FALLBACK_MODEL || 'qwen2.5:7b-instruct';
/** OWU 失败后多久内直接走本地兜底（毫秒）。 */
const OWU_COOLDOWN_MS = Number(process.env.QA_OWU_COOLDOWN_MS || 5 * 60 * 1000);
/**
 * 单次模型调用超时。比群里宽：.27 同一时刻只常驻一个模型，
 * 7b 与嵌入模型来回换载一次要 7~28 秒（2026-10-27 实测）。
 */
const QA_CHAT_TIMEOUT_MS = Number(process.env.QA_CHAT_TIMEOUT_MS || 180000);

let owuDownUntil = 0;

function pinOwu() {
  RUNTIME_CONFIG.chatProvider = 'openai';
  RUNTIME_CONFIG.chatBaseUrl = OWU_BASE;
  RUNTIME_CONFIG.chatModel = QA_MODEL;
  RUNTIME_CONFIG.chatApiKeyEnv = 'OPENWEBUI_API_KEY';
  RUNTIME_CONFIG.chatTimeoutMs = QA_CHAT_TIMEOUT_MS;
  // 关掉 llm.js 自带的那层兜底：它指向 config.json 的 WorkBuddy 代理（2026-10-17 起
  // 账号被限，恒 403），留着只会在 OWU 400 时白打一次再报错，还会覆盖我们自己的通道判断。
  // 同源同模型 → fallbackTarget() 返回 null，见 src/llm.js。
  FALLBACK_CONFIG.chatProvider = 'openai';
  FALLBACK_CONFIG.chatBaseUrl = OWU_BASE;
  FALLBACK_CONFIG.chatModel = QA_MODEL;
}

function pinLocalFallback() {
  // 换成 Ollama 直连（绕过 OWU）。模型必须用 FALLBACK_MODEL：
  // QA_MODEL 是 OWU 上的云端代理模型，Ollama 那边没有这个权重。
  RUNTIME_CONFIG.chatProvider = 'ollama';
  RUNTIME_CONFIG.chatModel = FALLBACK_MODEL;
  RUNTIME_CONFIG.chatTimeoutMs = QA_CHAT_TIMEOUT_MS;
  // provider 不同源时 llm.js 才回退；置成 ollama 即彻底关闭它（我们的兜底已在上层）。
  FALLBACK_CONFIG.chatProvider = 'ollama';
}

function activeChannel() {
  return RUNTIME_CONFIG.chatProvider === 'ollama' ? 'ollama' : 'openwebui';
}

/**
 * 下一次请求会**先**走哪条通道：冷却期内直接本地兜底，否则先试 OWU。
 *
 * health 必须报这个而不是 activeChannel()：兜底后 RUNTIME_CONFIG 会一直停在
 * ollama，冷却结束后下一次 runAnswer 又会重新 pin 回 OWU，直接报 provider
 * 会让探测方看到「永远在兜底」的假象。
 */
function nextChannel() {
  return Date.now() < owuDownUntil ? 'ollama' : 'openwebui';
}

/**
 * 是否属于「换条通道可能就好」的错误。
 *
 * 与 src/llm.js 的 isFallbackEligible 刻意不同：那边**不**认 403/401，
 * 因为群里换个通道只会掩盖密钥过期。网页版这里要的是可用性 ——
 * OWU 的 key 权限不足时，同一台 Ollama 明明能答，不该让用户看到报错。
 * 但只兜底通道问题，**不兜底**业务异常。
 */
function isChannelError(err) {
  const msg = String(err?.message || '');
  return (
    /云端模型返回 (401|403|404)/.test(msg) ||
    /API Key 无效/.test(msg) ||
    /Model not found/i.test(msg) ||
    /模型名或路径不对/.test(msg) ||
    /连不上云端模型/.test(msg) ||
    /超时/.test(msg) ||
    // 8443 是自签证书；CA 没装好时 fetch 抛 SELF_SIGNED_CERT_IN_CHAIN。
    // 这同样是「换条通道就好」—— 本地 Ollama 是 http，不涉及证书。
    /SELF_SIGNED_CERT|CERT_HAS_EXPIRED|UNABLE_TO_VERIFY|self-signed certificate/i.test(msg) ||
    /ECONNREFUSED|ENOTFOUND|ETIMEDOUT|EAI_AGAIN/.test(msg)
  );
}

/* ------------------------------ 会话记忆 ------------------------------ */

/** 每会话保留最近几轮（与 src/whatsapp.js 的 HISTORY_TURNS 同量级）。 */
const HISTORY_TURNS = 5;
/** 会话文本上限：答案再长也不值得整段留在上下文里（与 src/memory.js 同口径）。 */
const TURN_TEXT_CAP = 400;

/** clientId -> { turns: [{q,a}], updatedAt } */
const sessions = new Map();
/** 会话总数上限：网页端可能被多人同时用，不能让这张表无限长。 */
const MAX_SESSIONS = 500;

function getTurns(clientId) {
  const rec = sessions.get(clientId);
  if (!rec) return [];
  return rec.turns.slice();
}

function pushTurn(clientId, q, a) {
  if (!clientId || !q || !a) return;
  const cap = (s) => String(s || '').trim().slice(0, TURN_TEXT_CAP);
  const rec = sessions.get(clientId) || { turns: [], updatedAt: 0 };
  rec.turns.push({ q: cap(q), a: cap(a) });
  while (rec.turns.length > HISTORY_TURNS) rec.turns.shift();
  rec.updatedAt = Date.now();
  sessions.set(clientId, rec);
  if (sessions.size > MAX_SESSIONS) {
    // 淘汰最久没用的
    let oldestKey = null;
    let oldest = Infinity;
    for (const [k, v] of sessions) {
      if (v.updatedAt < oldest) { oldest = v.updatedAt; oldestKey = k; }
    }
    if (oldestKey) sessions.delete(oldestKey);
  }
}

function clearSession(clientId) {
  if (clientId) return sessions.delete(clientId);
  sessions.clear();
  return true;
}

/* ------------------------------ 并发闸门 ------------------------------ */

/**
 * 同一时刻只跑 N 个问答。
 *
 * 为什么要有上限：每条问答可能触发 1~3 次模型调用 + 1 次嵌入，
 * 多人同时点「发送」会把本地模型/云端代理压垮，且延迟会叠加到不可用。
 * 上限取 4 是权衡：够两个人正常提问，又不至于把上游打爆。
 *
 * 超出上限时**排队**而不是报错 —— 用户看到的是「稍等」，而不是失败。
 */
const MAX_CONCURRENT = Number(process.env.QA_HTTP_CONCURRENCY || 4);
let running = 0;
const waiters = [];

function acquire() {
  if (running < MAX_CONCURRENT) {
    running++;
    return Promise.resolve();
  }
  return new Promise((resolve) => waiters.push(resolve));
}

function release() {
  const next = waiters.shift();
  if (next) next();           // 交棒给等待者，running 保持不变
  else running--;
}

/* -------------------------------- 工具 -------------------------------- */

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

/** 读请求体（限长 64KB —— 提问不可能这么大）。 */
function readBody(req, limit = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(new Error('请求体过大'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

/* ------------------------------- 状态索引 ------------------------------- */

/**
 * 知识库索引。**按 mtime 懒加载**：只在第一次提问时读，读完缓存在内存。
 *
 * 为什么不是启动即加载：index.json 有 12MB，启动就 parse 会拖慢进程起来，
 * 而且没人提问时那份内存纯属浪费。但**必须能感知重建** —— 知识库同步
 * （scripts/sync-kb.mjs）会重建索引，此时旧的内存索引就是过期数据。
 * 每次提问前比对 mtime，变了就重载，这样「重建索引后网页版也能答对」，
 * 不需要重启进程。
 */
let indexCache = null;
let indexMtimeMs = 0;

function ensureIndex() {
  const path = CONFIG.indexPathAbs;
  const st = statSync(path);
  if (!indexCache || st.mtimeMs !== indexMtimeMs) {
    indexCache = loadIndex(path);
    indexMtimeMs = st.mtimeMs;
  }
  return indexCache;
}

/* -------------------------------- 路由 -------------------------------- */

/**
 * 跑一次问答，必要时在 OWU ↔ 本地 Ollama 之间切换通道。
 *
 * 只重试一次：第一次用 OWU（除非还在冷却期），出现通道级错误就切本地重跑。
 * 重跑的是整个 routeAnswer —— 它是只读链路（查库 / 检索 / 生成），可以安全重放。
 *
 * @returns {Promise<{result:object, via:string, fallbackReason?:string}>}
 */
async function runAnswer(question, index, opts) {
  const useLocalFirst = Date.now() < owuDownUntil;
  if (useLocalFirst) {
    pinLocalFallback();
  } else {
    pinOwu();
  }

  try {
    const result = await routeAnswer(question, index, opts);
    return { result, via: activeChannel() };
  } catch (e) {
    if (activeChannel() !== 'openwebui' || !isChannelError(e)) throw e;
    const reason = String(e.message).split('\n')[0];
    owuDownUntil = Date.now() + OWU_COOLDOWN_MS;
    console.warn(`[qa-http] OWU 通道失败（${reason}），切换本地 Ollama 兜底 ${FALLBACK_MODEL}，${Math.round(OWU_COOLDOWN_MS / 1000)}s 内不再试 OWU`);
    pinLocalFallback();
    const result = await routeAnswer(question, index, opts);
    return { result, via: 'ollama-fallback', fallbackReason: reason };
  }
}

const server = createServer(async (req, res) => {
  // 只服务本机：这是内网服务，对外由 nginx / my_app 中转并做鉴权。
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    const h = await healthCheck().catch(() => null);
    sendJson(res, 200, {
      ok: true,
      service: 'whatsapp-kb-bot 问答服务',
      indexChunks: indexCache ? indexCache.meta.chunks : null,
      indexFiles: indexCache ? indexCache.meta.files : null,
      embedModel: CONFIG.embedModel,
      // 对话通道：正常是 OWU，冷却期内是本地兜底（见文件头「OWU 不可用时的本地兜底」）
      provider: nextChannel() === 'ollama' ? 'ollama' : 'openai',
      channel: nextChannel(),
      // model 报「下一次提问实际会用的那个」—— 两条通道的模型名已经不同了，
      // 只报 QA_MODEL 会让兜底期间的健康检查看起来在说谎。
      model: nextChannel() === 'ollama' ? FALLBACK_MODEL : QA_MODEL,
      primaryModel: QA_MODEL,
      fallbackModel: FALLBACK_MODEL,
      owuBase: OWU_BASE,
      owuCooldownMs: Math.max(0, owuDownUntil - Date.now()),
      ollama: h ? { ok: h.embedModelPresent } : { ok: false },
      running,
      queued: waiters.length,
    });
    return;
  }

  if (req.method === 'POST' && url.pathname === '/ask') {
    let payload;
    try {
      payload = JSON.parse(await readBody(req) || '{}');
    } catch (e) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${e.message}` });
      return;
    }

    const question = String(payload.question || '').trim();
    if (!question) {
      sendJson(res, 400, { ok: false, error: '问题不能为空' });
      return;
    }
    // 语言：调用方显式传就用它的（网页有语言切换）；不传则按提问语言自动判定
    // （src/answer.js 的 detectLang，与群里同一套口径）。
    const lang = payload.lang === 'en' ? 'en' : payload.lang === 'zh' ? 'zh' : undefined;
    const clientId = String(payload.clientId || '').trim() || 'anonymous';

    await acquire();
    const t0 = Date.now();
    try {
      const index = ensureIndex();
      const { result, via, fallbackReason } = await runAnswer(question, index, {
        lang,
        history: getTurns(clientId),
        // 查不到时那句「去网页版问」是给群里的人看的；在这个网页挂件里说「去网页版」
        // 只会让人困惑（而且它指的是另一套 Open WebUI）。
        webHint: false,
        onLive: (text) => {
          // 「本地库没有、正在回 eFlow 实时查」的垫话。网页端不流式，
          // 这里只记日志，垫话本身由调用方在结果里看到（text 已含说明）。
          console.log(`[qa-http] 实时兜底中: ${String(text).slice(0, 60)}`);
        },
        onRetry: (text) => {
          console.log(`[qa-http] 工单通道重试: ${String(text).slice(0, 60)}`);
        },
      });

      // 只记**答上来了**的轮次：把兜底文案进上下文只会教模型说「查不到」
      // （与 src/memory.js 的同一条纪律）。
      if (result.answered && result.text) {
        pushTurn(clientId, question, result.text);
      }

      console.log(`[qa-http] client=${clientId} channel=${via} tool=${result.tool || '-'} ${Date.now() - t0}ms`);

      sendJson(res, 200, {
        ok: true,
        answer: result.text || '',
        answered: !!result.answered,
        channel: result.channel || 'kb',
        tool: result.tool || null,
        via: result.via || via,
        model: via === 'ollama-fallback' ? FALLBACK_MODEL : QA_MODEL,
        fallbackReason: fallbackReason || null,
        ms: Date.now() - t0,
      });
    } catch (e) {
      console.error(`[qa-http] 问答失败: ${e?.stack || e}`);
      sendJson(res, 500, {
        ok: false,
        error: `问答服务出错：${e?.message || String(e)}`,
        ms: Date.now() - t0,
      });
    } finally {
      release();
    }
    return;
  }

  if (req.method === 'POST' && url.pathname === '/session/clear') {
    let payload = {};
    try {
      payload = JSON.parse(await readBody(req) || '{}');
    } catch { /* 忽略：清空会话不依赖请求体 */ }
    clearSession(String(payload.clientId || '').trim());
    sendJson(res, 200, { ok: true });
    return;
  }

  sendJson(res, 404, { ok: false, error: '未知路径' });
});

/* -------------------------------- 启动 -------------------------------- */

async function main() {
  console.log('=== 网页问答服务（whatsapp-kb-bot）===\n');

  // 先把通道钉死，后面的自检与提问都按这个来（见文件头「对话模型」一节）。
  pinOwu();

  // provider 自检：缺 key 就明说，但**不退出** —— 与 src/index.js 同取舍：
  // 问答不可用不该让进程起不来，health 会如实报状态。
  const v = validateProvider();
  if (!v.ok) {
    console.error(`✗ ${v.message}`);
    console.error(`  （RAG 会回退到本地 Ollama ${QA_MODEL} @ ${CONFIG.ollamaUrl}）`);
  } else {
    const info = providerInfo();
    console.log(`✓ 对话 provider：[${info.provider}] ${info.model} @ ${info.baseUrl}（key 来源：${info.keySource}）`);
    console.log(`  兜底通道：本地 Ollama ${QA_MODEL} @ ${CONFIG.ollamaUrl}（OWU 通道级失败时启用，冷却 ${Math.round(OWU_COOLDOWN_MS / 1000)}s）`);
  }

  // Ollama 自检：同样只标记、不退出。
  try {
    const h = await healthCheck();
    if (!h.embedModelPresent) {
      console.error(`! Ollama（${CONFIG.ollamaUrl}）缺嵌入模型 ${CONFIG.embedModel}`);
    } else {
      console.log(`✓ Ollama 就绪（${CONFIG.ollamaUrl}，嵌入模型 ${CONFIG.embedModel}）`);
    }
  } catch (err) {
    console.error(`! Ollama 连接失败（${CONFIG.ollamaUrl}）：${err.message}`);
  }

  // 查表数据：缺失时查表工具会如实回「未构建」，不退回 RAG 装懂。
  const lookups = loadLookupsOnce();
  if (lookups) {
    console.log(
      `✓ 查表就绪：告警码 ${lookups.alarmCodes.size} 条 / 压缩规则 ${lookups.compress.length} 条 / 级别规则 ${lookups.levelRules.length} 条`
    );
  } else {
    console.warn('! 查表数据缺失（data/lookups.json）—— 告警码/压缩/级别问法会提示「未构建」');
  }

  // 索引：这里**不预载**（见 ensureIndex 的注释），但先探一次好让启动日志
  // 立刻显示知识库规模，也顺带验证文件可读。
  try {
    const idx = ensureIndex();
    console.log(`✓ 索引就绪：${idx.meta.chunks} 块 / ${idx.meta.files} 个文件`);
  } catch (e) {
    console.error(`✗ 索引不可用（${e.message}）—— 提问会失败，请先跑 npm run ingest`);
  }

  server.listen(PORT, HOST, () => {
    console.log(`\n问答服务已启动：http://${HOST}:${PORT}`);
    console.log(`  POST /ask           提问（{question, lang?, clientId?}）`);
    console.log(`  POST /session/clear 清空某会话的记忆`);
    console.log(`  GET  /health        存活与依赖状态`);
    console.log(`  并发上限：${MAX_CONCURRENT}\n`);
  });
}

main().catch((err) => {
  console.error(`启动失败：${err.message}`);
  process.exit(1);
});
