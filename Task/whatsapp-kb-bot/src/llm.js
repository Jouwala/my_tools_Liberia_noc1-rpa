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
import { CONFIG, FALLBACK_CONFIG } from './config.js';
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
 *
 * 主 provider 失败时（模型不可用 / 超时 / 连不上），**自动改打兜底 provider**。
 * 这是 2026-10-16 故障的直接产物：OWU 侧一时不再暴露本地模型，主链路整体失败，
 * 而本机 WorkBuddy 代理一直可用 —— 若能自动回退，群里就不会只收到「something went wrong」。
 *
 * 只对「基础设施级」错误回退：网络不可达、超时、5xx、模型名/路径不认（404/400）。
 * **鉴权失败（401/403）与限流（429）不回退** —— 那是配置/额度问题，换个 provider 掩盖不了，
 * 反而会让用户以为主 provider 没问题。用 opts.noFallback 可显式关闭回退（测试/ping 用）。
 *
 * @param {Array<{role:string,content:string}>} messages
 * @param {object} opts { model, temperature, maxTokens, timeoutMs, noFallback, lenient }
 * @returns {Promise<{content:string, stats:object, fallback?:object}>}
 */
export async function chat(messages, opts = {}) {
  const primary = CONFIG.chatProvider === 'openai' ? openaiChat(messages, opts) : ollamaChat(messages, opts);

  const fb = fallbackTarget();
  if (opts.noFallback || !fb) return primary;

  try {
    return await primary;
  } catch (err) {
    if (!isFallbackEligible(err)) throw err;
    // 回退目标独立构造，不复用主链路的 CONFIG（此时已被覆盖）。
    console.warn(`[llm] 主模型失败（${String(err.message).split('\n')[0]}），自动回退到兜底 provider：${fb.chatModel} @ ${fb.chatBaseUrl}`);
    const r = fb.chatProvider === 'openai'
      ? await openaiChat(messages, { ...opts, __override: fb })
      : await ollamaChat(messages, opts);
    return { ...r, fallback: { from: CONFIG.chatModel, to: fb.chatModel, reason: String(err.message).split('\n')[0] } };
  }
}

/**
 * 判定错误是否值得回退。
 * 用错误信息文本匹配 —— openaiChat 抛出的都是人可读的中文短语（见下方各 throw），
 * 这里只认那些「换个 provider 可能就好」的类别。
 */
function isFallbackEligible(err) {
  const msg = String(err?.message || '');
  // 明确不该回退：密钥无效 / 限流额度 —— 换 provider 掩盖问题
  if (/API Key 无效|无权限|限流|额度/.test(msg)) return false;
  // 值得回退：网络不可达、超时、模型名/路径不认、5xx
  return (
    /连不上云端模型/.test(msg) ||
    /超时/.test(msg) ||
    /模型名或路径不对/.test(msg) ||
    /Model not found/i.test(msg) ||
    /返回 5\d\d/.test(msg)
  );
}

/**
 * 计算兜底目标。仅当「主 provider 与兜底 provider 确实不同源」时才返回，
 * 否则返回 null（同源回退无意义，还会把同一请求白打两遍）。
 * @returns {{chatProvider:string, chatModel:string, chatBaseUrl:string, chatApiKeyEnv:string, chatApiKey:string}|null}
 */
function fallbackTarget() {
  const f = FALLBACK_CONFIG;
  if (!f || f.chatProvider !== 'openai' || !f.chatBaseUrl) return null;
  const sameBase = String(f.chatBaseUrl).replace(/\/+$/, '') === String(CONFIG.chatBaseUrl || '').replace(/\/+$/, '');
  const sameModel = f.chatModel === CONFIG.chatModel;
  if (sameBase && sameModel) return null;
  // 兜底目标也得有 key 才可用
  const envName = f.chatApiKeyEnv;
  const fromEnv = envName && process.env[envName] ? String(process.env[envName]).trim() : '';
  const fromCfg = (f.chatApiKey || '').trim();
  if (!fromEnv && !fromCfg) return null;
  return f;
}

/* ------------------------- OpenAI 兼容 provider ------------------------- */

/**
 * 剥离模型混进正文的思维链与工具调用标记。
 *
 * 为什么必须做：mimo-v2.6-flash 实测约 1/4 的请求会把「决定调用工具」这一轮
 * 原样写进 `content`，群里收到的是
 *   `I'll check the available tools…<tool_call><function=search_knowledge>…`
 * —— 既不是答案，还暴露了内部工具名。旧代码只防了「content 为空」和
 * 「只有 reasoning_content」两种，对「content 非空但全是标记」毫无防备，
 * 于是这类垃圾被当成正常回答发了出去（answered 还是 true）。
 *
 * @param {string} raw 原始 content
 * @returns {{text:string, think:boolean, toolCall:boolean}}
 *   text      净化后的正文（可能为空串）
 *   think     出现过 think 标记（剥掉后正文仍可用）
 *   toolCall  出现过工具调用标记（**整轮不可信**，调用方应重试或弃权）
 */
export function stripModelMarkup(raw) {
  let s = String(raw ?? '');
  if (!s.trim()) return { text: '', think: false, toolCall: false };

  const think = /<think(?:ing)?\b|<\/think(?:ing)?>/i.test(s);
  // `<function=x>` 这种不带右尖括号的开标签也要认（实测就是这个形态）
  const toolCall = /<tool_call\b|<\/tool_call>|<function\s*=|<parameter\s*=|<\|tool[_▁]?calls?[_▁]?(?:begin|end)\|>/i.test(s);

  if (think) {
    // 完整块（含 <thinking> 变体）
    s = s.replace(/<think(?:ing)?\b[^>]*>[\s\S]*?<\/think(?:ing)?>/gi, '');
    // 未闭合块：被 max_tokens 截断时只剩开头，一直吃到结尾
    s = s.replace(/<think(?:ing)?\b[^>]*>[\s\S]*$/gi, '');
    // 开标签连 '>' 都被截掉了
    s = s.replace(/<think(?:ing)?\b[\s\S]*$/gi, '');
    // 只剩闭合标签：**它前面的文字就是思考内容**。
    // 实测 mimo 把思维链塞进 content，却只漏出闭合标签（reasoning 已拆到
    // reasoning_content 字段），于是正文前面挂着一句「Wait — the question is…」。
    s = s.replace(/^[\s\S]*<\/think(?:ing)?>/gi, '');
  }

  if (toolCall) {
    s = s.replace(/<tool_call\b[^>]*>[\s\S]*?<\/tool_call>/gi, '');
    s = s.replace(/<tool_call\b[^>]*>[\s\S]*$/gi, ''); // 未闭合
    s = s.replace(/<\/?tool_call\b[^>]*>/gi, '');
    s = s.replace(/<function\s*=[^>]*>[\s\S]*?<\/function>/gi, '');
    s = s.replace(/<parameter\s*=[^>]*>[\s\S]*?<\/parameter>/gi, '');
    s = s.replace(/<\/?(?:function|parameter)\b[^>]*>/gi, '');
    s = s.replace(/<\|?tool[_▁]?calls?[_▁]?begin\|?>[\s\S]*?<\|?tool[_▁]?calls?[_▁]?end\|?>/gi, '');
  }

  return { text: s.replace(/\n{3,}/g, '\n\n').trim(), think, toolCall };
}

/** 发一次 chat/completions，返回 {data, text}；传输层与 HTTP 错误在此翻译成可读信息 */
async function postCompletion({ url, body, key, timeoutMs }) {
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
  return { data, text };
}

async function openaiChat(messages, opts = {}) {
  // __override：回退链路专用，用兜底 provider 的 base/model/key 替换被覆盖的 CONFIG。
  const ov = opts.__override;
  const key = ov
    ? ((ov.chatApiKeyEnv && process.env[ov.chatApiKeyEnv] ? String(process.env[ov.chatApiKeyEnv]).trim() : '') ||
       (ov.chatApiKey || '').trim())
    : resolveApiKey().key;
  if (!key) throw new Error('缺少 API Key，无法调用云端对话模型');

  const base = (ov ? ov.chatBaseUrl : CONFIG.chatBaseUrl).replace(/\/+$/, '');
  const url = `${base}/chat/completions`;
  const timeoutMs = opts.timeoutMs ?? CONFIG.chatTimeoutMs;
  // 计时从进入函数开始算：发生重试时 totalMs 要如实反映「用户等了多久」，
  // 只算最后一次会让人以为回答很快。
  const startedAt = Date.now();

  const body = {
    model: opts.model ?? (ov ? ov.chatModel : CONFIG.chatModel),
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

  // 一轮「只有标记、没有正文」的回复不值得直接甩给用户，但它确实是偶发的：
  // 原样再打一次几乎总能拿到正常正文。只重试一次，避免把 5s 的回答拖成 30s。
  const maxAttempts = Math.max(1, Number(opts.maxAttempts ?? 2));
  let failure = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const { data, text } = await postCompletion({ url, body, key, timeoutMs });

    const choice = data.choices?.[0];
    const msg = choice?.message;
    const raw = (msg?.content ?? '').trim();
    const reasoning = msg?.reasoning_content;
    const { text: content, think, toolCall } = stripModelMarkup(raw);
    const stats = {
      promptTokens: data.usage?.prompt_tokens ?? 0,
      outputTokens: data.usage?.completion_tokens ?? 0,
      totalMs: Date.now() - startedAt,
    };
    if (attempt > 1) stats.attempts = attempt;

    // 正文可用、且这一轮没被工具调用标记污染 → 正常返回。
    // think 标记只剥掉不弃用：正文本身是好的，只是前面多了一段思考。
    if (content && !toolCall) {
      return think ? { content, degraded: 'think_stripped', stats } : { content, stats };
    }

    // lenient 模式（ping 专用）：只要模型返回了任何非空文本，就说明
    // 密钥有效、模型存在、链路通畅 —— 这已经足够回答"能不能连上"。
    // 至于 content 为空本身，交给运行时正常报错，不在探测阶段拦截。
    if (opts.lenient && (raw || (reasoning && String(reasoning).trim()))) {
      const onlyReasoning = !raw && reasoning && String(reasoning).trim();
      return {
        content: '',
        degraded: onlyReasoning ? 'reasoning_only' : 'markup_only',
        reasoningChars: String(reasoning || '').length,
        stats,
      };
    }

    // 空内容有很多种成因，必须把结构打出来，否则无从排查。
    const reason = choice?.finish_reason;
    const fields = msg ? Object.keys(msg).join(', ') : '（没有 message 字段）';
    const notes = [];

    if (toolCall) {
      notes.push(
        `content 里只有工具调用标记（<tool_call>/<function>），没有正文 —— ` +
          `模型把「决定调用工具」这一轮当成了回答。这是间歇行为，重打一次通常就恢复。`
      );
    }
    if (reasoning) {
      notes.push(
        `但返回了 reasoning_content（${String(reasoning).length} 字符）—— 说明模型把预算花在思考上，` +
          `content 为空。应关闭 thinking（config.json 的 enableThinking: false）或调大 maxTokens。`
      );
    }
    if (reason === 'length') {
      notes.push(`finish_reason=length 表示被 max_tokens(${body.max_tokens}) 截断，请调大 maxTokens。`);
    }
    if (!toolCall && !reasoning && reason !== 'length') {
      notes.push(
        `未发现 reasoning_content。finish_reason=${reason} 表示模型正常结束但没输出正文 —— ` +
          `请运行 npm run diag 对比不同模型名与参数，确认是模型权限问题还是参数问题。`
      );
    }

    failure = new Error(
      `云端模型返回空内容（finish_reason=${reason}；message 字段=[${fields}]；max_tokens=${body.max_tokens}）\n` +
        notes.map((n) => `  · ${n}`).join('\n') +
        `\n  原始响应：${text.slice(0, 400)}`
    );

    // 只有「标记泄漏」值得重试 —— 那是模型的偶发行为。
    // 纯粹的 content 为空（思考烧光预算 / 被截断）重试也是同样结果，只会白等一轮。
    if (!(toolCall || think) || attempt >= maxAttempts) break;
    console.warn(
      `[llm] ${body.model} 第 ${attempt} 次只返回了${toolCall ? '工具调用标记' : '思维链标记'}、没有正文，重试一次`
    );
  }

  throw failure;
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

    if (r.degraded === 'reasoning_only' || r.degraded === 'markup_only') {
      // 能连上，但模型没吐正文（只吐思维链 / 只吐工具调用标记）。
      // 启动不该被这个拦住 —— 但要如实告知，否则用户会以为一切正常，
      // 到群里问才发现没回答。
      const why =
        r.degraded === 'markup_only'
          ? 'content 里只有工具调用标记、没有正文'
          : `content 为空、只返回了 ${r.reasoningChars} 字符的 reasoning_content`;
      return {
        ok: true,
        warning: true,
        message:
          `${CONFIG.chatModel} 可达（${ms}ms），但${why}。\n` +
          `    实际问答很可能也返回空。请运行 npm run diag 定位（对比模型名/参数）。`,
      };
    }

    return { ok: true, message: `${CONFIG.chatModel} 响应正常（${ms}ms）：${r.content.slice(0, 40)}` };
  } catch (err) {
    return { ok: false, message: err.message };
  }
}
