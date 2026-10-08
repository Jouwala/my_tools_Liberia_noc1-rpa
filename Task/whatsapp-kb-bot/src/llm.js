/**
 * 对话模型 provider 分发层。
 *
 * 支持两类 provider：
 *   - "ollama"  本地 Ollama（默认，全离线）
 *   - "openai"  任意 OpenAI 兼容接口（如 Agnes AI、各类云厂商）
 *
 * 嵌入始终走本地 Ollama —— 这是刻意的：把资料向量化留在本机，
 * 只有「问题 + 命中的片段」会离开这台机器。
 */
import { CONFIG } from './config.js';
import { ollamaChat } from './ollama.js';

/**
 * 解析 API Key：环境变量优先于配置文件（避免把密钥写进可能被提交的文件）。
 * 注意：先 trim 再判空。否则 `export KEY="   "` 这种纯空白值会被当成"已配置"，
 * 结果是 key 为空串但 source 显示来自环境变量 —— 用户以为配好了，实际报"找不到 Key"。
 */
export function resolveApiKey() {
  const envName = CONFIG.chatApiKeyEnv;
  const rawEnv = envName ? process.env[envName] : undefined;
  const fromEnv = rawEnv ? String(rawEnv).trim() : '';
  const fromConfig = (CONFIG.chatApiKey || '').trim();

  if (fromEnv) return { key: fromEnv, source: `环境变量 ${envName}` };
  if (fromConfig) return { key: fromConfig, source: 'config.json' };
  return { key: '', source: null };
}

/** 当前 provider 的展示信息，用于启动日志与 ping */
export function providerInfo() {
  const { source } = resolveApiKey();
  return {
    provider: CONFIG.chatProvider,
    model: CONFIG.chatModel,
    baseUrl: CONFIG.chatProvider === 'ollama' ? CONFIG.ollamaUrl : CONFIG.chatBaseUrl,
    keySource: source,
  };
}

/** 启动自检：配置是否完整 */
export function validateProvider() {
  if (CONFIG.chatProvider === 'ollama') return { ok: true };
  if (CONFIG.chatProvider !== 'openai') {
    return { ok: false, message: `未知的 chatProvider：${CONFIG.chatProvider}（应为 ollama 或 openai）` };
  }
  if (!CONFIG.chatBaseUrl) {
    return { ok: false, message: 'chatProvider=openai 但 chatBaseUrl 为空' };
  }
  const { key } = resolveApiKey();
  if (!key) {
    return {
      ok: false,
      message:
        `chatProvider=openai 但找不到 API Key。\n` +
        `  请设置环境变量 ${CONFIG.chatApiKeyEnv || 'OPENAI_API_KEY'}，或填写 config.json 的 chatApiKey。\n` +
        `  PowerShell:  $env:${CONFIG.chatApiKeyEnv || 'OPENAI_API_KEY'}="你的key"\n` +
        `  Bash:        export ${CONFIG.chatApiKeyEnv || 'OPENAI_API_KEY'}="你的key"`,
    };
  }
  return { ok: true };
}

/**
 * 统一对话入口。
 * @param {Array<{role:string,content:string}>} messages
 * @param {object} opts { model, temperature, maxTokens, timeoutMs }
 * @returns {Promise<{content:string, stats:object}>}
 */
export async function chat(messages, opts = {}) {
  return CONFIG.chatProvider === 'openai' ? openaiChat(messages, opts) : ollamaChat(messages, opts);
}

/* ------------------------- OpenAI 兼容 provider ------------------------- */

async function openaiChat(messages, opts = {}) {
  const { key } = resolveApiKey();
  if (!key) throw new Error('缺少 API Key，无法调用云端对话模型');

  const base = CONFIG.chatBaseUrl.replace(/\/+$/, '');
  const url = `${base}/chat/completions`;
  const timeoutMs = opts.timeoutMs ?? CONFIG.chatTimeoutMs;
  const t0 = Date.now();

  const body = {
    model: opts.model ?? CONFIG.chatModel,
    messages,
    temperature: opts.temperature ?? CONFIG.temperature,
    max_tokens: opts.maxTokens ?? CONFIG.maxTokens,
    stream: false,
  };

  // Thinking 模式控制。
  // 知识库问答不需要思维链——只会白白消耗 token 预算，还可能把预算烧光
  // 导致 content 返回空串（实测 Agnes 3.0 Flash 上就是这个现象）。
  // 有些 provider 默认开启 thinking，必须显式关闭。
  const wantThinking = opts.enableThinking ?? CONFIG.enableThinking;
  if (wantThinking === false) {
    body.chat_template_kwargs = { enable_thinking: false };
  } else if (wantThinking === true) {
    body.chat_template_kwargs = { enable_thinking: true };
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`云端模型超时（${timeoutMs}ms）：${url}`);
    throw new Error(`连不上云端模型：${err.cause?.code || err.message}（${url}）`);
  } finally {
    clearTimeout(timer);
  }

  const text = await res.text();
  if (!res.ok) {
    // 把常见的鉴权/额度错误翻译成人能看懂的话
    let hint = '';
    if (res.status === 401 || res.status === 403) hint = '  → API Key 无效或无权限';
    else if (res.status === 404) hint = `  → 模型名或路径不对，当前 model=${body.model}`;
    else if (res.status === 429) hint = '  → 触发限流或额度用尽';
    throw new Error(`云端模型返回 ${res.status}${hint}\n  ${text.slice(0, 300)}`);
  }

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`云端模型返回的不是 JSON：${text.slice(0, 200)}`);
  }

  const choice = data.choices?.[0];
  const msg = choice?.message;
  const content = (msg?.content ?? '').trim();
  const reasoning = msg?.reasoning_content;

  if (!content) {
    // lenient 模式（ping 专用）：只要模型返回了任何非空文本，就说明
    // 密钥有效、模型存在、链路通畅 —— 这已经足够回答"能不能连上"。
    // 至于 content 为空本身，交给运行时正常报错，不在探测阶段拦截。
    if (opts.lenient && reasoning && String(reasoning).trim()) {
      return {
        content: '',
        degraded: 'reasoning_only',
        reasoningChars: String(reasoning).length,
        stats: {
          promptTokens: data.usage?.prompt_tokens ?? 0,
          outputTokens: data.usage?.completion_tokens ?? 0,
          totalMs: Date.now() - t0,
        },
      };
    }

    // 空内容有很多种成因，必须把结构打出来，否则无从排查。
    const reason = choice?.finish_reason;
    const fields = msg ? Object.keys(msg).join(', ') : '（没有 message 字段）';
    const notes = [];

    if (reasoning) {
      notes.push(
        `但返回了 reasoning_content（${String(reasoning).length} 字符）—— 说明模型把预算花在思考上，` +
          `content 为空。应关闭 thinking（config.json 的 enableThinking: false）或调大 maxTokens。`
      );
    }
    if (reason === 'length') {
      notes.push(`finish_reason=length 表示被 max_tokens(${body.max_tokens}) 截断，请调大 maxTokens。`);
    }
    if (!reasoning && reason !== 'length') {
      notes.push(
        `未发现 reasoning_content。finish_reason=${reason} 表示模型正常结束但没输出正文 —— ` +
          `请运行 npm run diag 对比不同模型名与参数，确认是模型权限问题还是参数问题。`
      );
    }

    throw new Error(
      `云端模型返回空内容（finish_reason=${reason}；message 字段=[${fields}]；max_tokens=${body.max_tokens}）\n` +
        notes.map((n) => `  · ${n}`).join('\n') +
        `\n  原始响应：${text.slice(0, 400)}`
    );
  }

  return {
    content,
    stats: {
      promptTokens: data.usage?.prompt_tokens ?? 0,
      outputTokens: data.usage?.completion_tokens ?? 0,
      totalMs: Date.now() - t0,
    },
  };
}

/** 云端 provider 的连通性探测（用极小请求验证 key 与模型名） */
export async function pingProvider() {
  if (CONFIG.chatProvider === 'ollama') return { ok: true, message: '本地 Ollama' };
  const t0 = Date.now();
  try {
    // 预算不能太小：若模型带 thinking，小预算会被思考过程吃光，
    // content 返回空串，看起来像"密钥或模型有问题"，其实是预算不够。
    // 官方文档的基础示例用 max_tokens=1024，这里取 256 —— 探测够用又不拖慢启动。
    // WorkBuddy 代理（8788）要求首条消息为 system，否则返回 11128；加一条短 system 兼容两类 provider。
    const r = await openaiChat([
      { role: 'system', content: 'Reply briefly.' },
      { role: 'user', content: '只回复两个字：正常' },
    ], {
      maxTokens: 256,
      timeoutMs: 30000,
      lenient: true,
    });
    const ms = Date.now() - t0;

    if (r.degraded === 'reasoning_only') {
      // 能连上，但模型只吐思维链、没吐正文。启动不该被这个拦住 ——
      // 但要如实告知，否则用户会以为一切正常，到群里问才发现没回答。
      return {
        ok: true,
        warning: true,
        message:
          `${CONFIG.chatModel} 可达（${ms}ms），但 content 为空、只返回了 ${r.reasoningChars} 字符的 ` +
          `reasoning_content。\n` +
          `    实际问答很可能也返回空。请运行 npm run diag 定位（对比模型名/参数）。`,
      };
    }

    return { ok: true, message: `${CONFIG.chatModel} 响应正常（${ms}ms）：${r.content.slice(0, 40)}` };
  } catch (err) {
    return { ok: false, message: err.message };
  }
}
