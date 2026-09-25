/**
 * Ollama HTTP 封装。
 * 刻意不引入 ollama SDK —— 只用原生 fetch，零额外依赖。
 */
import { CONFIG } from './config.js';

async function request(path, { method = 'POST', body, timeoutMs = 180000 } = {}) {
  const base = CONFIG.ollamaUrl.replace(/\/+$/, '');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    if (!res.ok) {
      throw new Error(`Ollama ${path} 返回 ${res.status}：${text.slice(0, 300)}`);
    }
    return JSON.parse(text);
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(`Ollama ${path} 超时（${timeoutMs}ms）`);
    }
    if (err.cause?.code === 'ECONNREFUSED') {
      throw new Error(`连不上 Ollama（${base}）。请确认 ollama serve 正在运行。`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** 列出本地已安装的模型 */
export async function listModels() {
  const data = await request('/api/tags', { method: 'GET', timeoutMs: 10000 });
  return (data.models || []).map((m) => m.name);
}

/**
 * 批量嵌入。自动分批，避免单请求过大。
 * keep_alive 必须显式传：否则默认 5 分钟后卸载，
 * 与对话模型来回抢占内存，导致每次提问都重载模型（实测 +3~5s）。
 * @returns {Promise<number[][]>} 与入参等长的向量数组
 */
export async function embed(texts, { model = CONFIG.embedModel, batchSize = 16, keepAlive = CONFIG.keepAlive } = {}) {
  if (!texts.length) return [];
  const out = [];
  for (let i = 0; i < texts.length; i += batchSize) {
    const slice = texts.slice(i, i + batchSize);
    const data = await request('/api/embed', { body: { model, input: slice, keep_alive: keepAlive } });
    if (!Array.isArray(data.embeddings)) {
      throw new Error('嵌入返回格式异常：缺少 embeddings 字段');
    }
    out.push(...data.embeddings);
  }
  return out;
}

/** 单条嵌入，用于检索时的查询向量 */
export async function embedOne(text, opts) {
  const [vec] = await embed([text], opts);
  if (!vec) throw new Error('嵌入返回空向量');
  return vec;
}

/**
 * Ollama 对话补全（provider = ollama 时由 llm.js 调用）。
 * 注意：对外统一入口是 llm.js 的 chat()，不要直接用它。
 * @returns {Promise<{content: string, stats: object}>}
 */
export async function ollamaChat(messages, opts = {}) {
  const data = await request('/api/chat', {
    body: {
      model: opts.model ?? CONFIG.chatModel,
      stream: false,
      messages,
      options: {
        temperature: opts.temperature ?? CONFIG.temperature,
        num_predict: opts.maxTokens ?? CONFIG.maxTokens,
      },
      keep_alive: opts.keepAlive ?? CONFIG.keepAlive,
    },
    timeoutMs: opts.timeoutMs,
  });
  return {
    content: (data.message?.content ?? '').trim(),
    stats: {
      promptTokens: data.prompt_eval_count ?? 0,
      outputTokens: data.eval_count ?? 0,
      promptMs: Math.round((data.prompt_eval_duration ?? 0) / 1e6),
      genMs: Math.round((data.eval_duration ?? 0) / 1e6),
      totalMs: Math.round((data.total_duration ?? 0) / 1e6),
    },
  };
}

/** 探活 + 校验所需模型是否就位（对话走云端时不检查本地对话模型） */
export async function healthCheck({
  embedModel = CONFIG.embedModel,
  chatModel = CONFIG.chatModel,
  chatLocal = CONFIG.chatProvider === 'ollama',
} = {}) {
  const models = await listModels();
  const has = (name) => models.some((m) => m === name || m === `${name}:latest` || m.split(':')[0] === name.split(':')[0]);
  return {
    ok: true,
    models,
    embedModelPresent: has(embedModel),
    chatModelPresent: chatLocal ? has(chatModel) : true,
    chatLocal,
  };
}

/** 当前常驻内存的模型列表 */
export async function loadedModels() {
  const data = await request('/api/ps', { method: 'GET', timeoutMs: 10000 });
  return (data.models || []).map((m) => ({
    name: m.name,
    vramBytes: m.size_vram ?? 0,
    totalBytes: m.size ?? 0,
    expiresAt: m.expires_at,
  }));
}

/**
 * 预热本地模型，并检查它们能否同时常驻。
 *
 * 为什么重要：Ollama 默认 OLLAMA_MAX_LOADED_MODELS=1，
 * 只能常驻一个模型。此时每次提问都会「嵌入模型加载 → 被对话模型挤掉 →
 * 下次提问再加载嵌入模型」，实测每次多花 3~5 秒。
 * 本机实测：qwen3:4b-instruct(3.25GB) + bge-m3(1.16GB) ≈ 4.4GB，
 * 只要内存放得下，把上限调到 2 即可彻底消除这个开销。
 *
 * 若对话走云端 provider（chatLocal=false），本地只剩嵌入模型，
 * 不存在互相挤占的问题，此时 bothResident 恒为 true。
 */
export async function warmup({
  embedModel = CONFIG.embedModel,
  chatModel = CONFIG.chatModel,
  chatLocal = CONFIG.chatProvider === 'ollama',
} = {}) {
  const short = (n) => String(n).split(':')[0];

  await embed(['预热'], { model: embedModel }).catch(() => {});
  if (chatLocal) {
    await ollamaChat([{ role: 'user', content: 'hi' }], { model: chatModel, maxTokens: 1 }).catch(() => {});
  }

  const loaded = await loadedModels();
  const names = loaded.map((m) => short(m.name));
  const hasEmbed = names.includes(short(embedModel));
  const hasChat = chatLocal ? names.includes(short(chatModel)) : true;

  return {
    loaded,
    hasEmbed,
    hasChat,
    chatLocal,
    bothResident: hasEmbed && hasChat,
    residentBytes: loaded.reduce((s, m) => s + m.totalBytes, 0),
  };
}
