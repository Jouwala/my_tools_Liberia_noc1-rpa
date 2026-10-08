#!/usr/bin/env node
/**
 * 对话 provider 分发层测试。
 *   node scripts/test-llm.mjs
 *
 * 不需要真实 API Key —— 通过替换 globalThis.fetch 验证：
 *   请求是否构造正确（URL / 认证头 / 模型名 / 参数）
 *   错误是否被翻译成人能看懂的话
 *   两个 provider 是否正确分发
 */
import { CONFIG } from '../src/config.js';
import { chat, resolveApiKey, providerInfo, validateProvider, pingProvider } from '../src/llm.js';

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

const realFetch = globalThis.fetch;
const ENV_NAME = CONFIG.chatApiKeyEnv;

/** 安装一个假的 fetch，记录调用参数 */
function mockFetch(responder) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return responder(String(url), init);
  };
  return calls;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/* ------------------------------ 密钥解析 ------------------------------ */

console.log('\n[1] API Key 解析优先级');

delete process.env[ENV_NAME];
CONFIG.chatApiKey = '';
const noKey = resolveApiKey();
check(noKey.key === '' && noKey.source === null, '都未配置时 → 空值且 source 为 null');

CONFIG.chatApiKey = 'from-config';
const cfgKey = resolveApiKey();
check(cfgKey.key === 'from-config' && cfgKey.source === 'config.json', '仅配置文件 → 取配置文件的值');

process.env[ENV_NAME] = 'from-env';
const envKey = resolveApiKey();
check(
  envKey.key === 'from-env' && envKey.source === `环境变量 ${ENV_NAME}`,
  '环境变量优先于配置文件（避免密钥被写进可能提交的文件）'
);

process.env[ENV_NAME] = '   ';
CONFIG.chatApiKey = 'from-config';
check(resolveApiKey().key === 'from-config', '环境变量为空白字符时回退到配置文件');

CONFIG.chatApiKey = '';
delete process.env[ENV_NAME];

/* ------------------------------ 配置校验 ------------------------------ */

console.log('\n[2] 启动自检');
CONFIG.chatProvider = 'openai';
const bad = validateProvider();
check(!bad.ok, 'openai 但无密钥 → 校验失败');
check(/AGNES_API_KEY/.test(bad.message || ''), '错误信息里点明了该设置哪个环境变量', bad.message);
check(/export|env:/.test(bad.message || ''), '错误信息给出了具体设置命令');

process.env[ENV_NAME] = 'test-key-123';
check(validateProvider().ok, '设置密钥后 → 校验通过');

CONFIG.chatProvider = 'ollama';
check(validateProvider().ok, 'ollama provider 不需要密钥');
CONFIG.chatProvider = 'openai';

CONFIG.chatProvider = 'bogus';
const unknown = validateProvider();
check(!unknown.ok && /未知/.test(unknown.message || ''), '未知 provider 名 → 明确报错');
CONFIG.chatProvider = 'openai';

/* ---------------------------- provider 信息 ---------------------------- */

console.log('\n[3] provider 信息');
const info = providerInfo();
check(info.provider === 'openai', 'provider 正确');
// ⚠️ 断言**取自 config 的值**，而不是硬编码某个部署的模型名 ——
// config.json 的 chatModel/chatBaseUrl 是部署时可切换的（本项目实测在
// agnes 云端 与 本地代理 deepseek 之间切过）。硬编码会让「换个 provider 就测试红」，
// 而那是配置变更、不是代码回归。这里要验的是「provider 层如实回读 config」。
check(info.model === CONFIG.chatModel, `模型名取自 config（${info.model}）`);
check(info.baseUrl === CONFIG.chatBaseUrl, `baseUrl 取自 config（${info.baseUrl}）`);
check(info.keySource === `环境变量 ${ENV_NAME}`, '密钥来源可追溯');

/* ---------------------------- OpenAI 兼容调用 ---------------------------- */

console.log('\n[4] OpenAI 兼容请求构造');
let calls = mockFetch(() =>
  jsonResponse({
    id: 'chatcmpl_x',
    model: CONFIG.chatModel,
    choices: [{ index: 0, message: { role: 'assistant', content: '年假15天。' }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 120, completion_tokens: 8, total_tokens: 128 },
  })
);

const r = await chat([
  { role: 'system', content: '只依据资料回答' },
  { role: 'user', content: '年假有几天？' },
]);

// URL 由 config 的 chatBaseUrl 拼出（同样不硬编码具体部署的地址）
const expectUrl = `${CONFIG.chatBaseUrl.replace(/\/$/, '')}/chat/completions`;
check(calls.length === 1, '发起了 1 次请求');
check(calls[0].url === expectUrl, `URL 由 baseUrl 拼出（${calls[0].url}）`);
check(calls[0].init.method === 'POST', 'method 为 POST');
check(
  calls[0].init.headers.Authorization === 'Bearer test-key-123',
  '认证头为 Bearer <key>'
);
check(calls[0].init.headers['Content-Type'] === 'application/json', 'Content-Type 正确');

const sent = JSON.parse(calls[0].init.body);
check(sent.model === CONFIG.chatModel, `请求体 model 取自 config（${sent.model}）`);
check(sent.messages.length === 2, 'messages 完整传递');
check(sent.messages[0].role === 'system', 'system 消息保留');
check(sent.max_tokens === CONFIG.maxTokens, `max_tokens 取自配置（${sent.max_tokens}）`);
check(sent.temperature === CONFIG.temperature, `temperature 取自配置（${sent.temperature}）`);
check(sent.stream === false, '非流式');

check(r.content === '年假15天。', '正确解析 choices[0].message.content');
check(r.stats.promptTokens === 120 && r.stats.outputTokens === 8, '正确解析 usage');

/* --------------------- Thinking 参数与空内容处理 --------------------- */

console.log('\n[5] Thinking 开关与空内容处理');

const okBody = () => jsonResponse({ choices: [{ message: { role: 'assistant', content: 'ok' }, finish_reason: 'stop' }] });

async function sentBody() {
  calls = mockFetch(okBody);
  await chat([{ role: 'user', content: 'hi' }]);
  return JSON.parse(calls[0].init.body);
}

const savedThinking = CONFIG.enableThinking;

CONFIG.enableThinking = false;
let b = await sentBody();
check(b.chat_template_kwargs?.enable_thinking === false, 'enableThinking=false → 显式关闭 thinking');

CONFIG.enableThinking = true;
b = await sentBody();
check(b.chat_template_kwargs?.enable_thinking === true, 'enableThinking=true → 显式开启 thinking');

CONFIG.enableThinking = null;
b = await sentBody();
check(b.chat_template_kwargs === undefined, 'enableThinking=null → 不传该字段，用服务端默认');

CONFIG.enableThinking = savedThinking;

// lenient 模式（ping 专用）：只要模型吐出任何文本就算连通，不因 content 为空而判定失败。
// 这条很关键 —— 否则一个「只返回思维链」的模型会让启动自检直接失败，把用户挡在门外。
const reasoningOnly = () =>
  jsonResponse({
    choices: [{ message: { role: 'assistant', content: '', reasoning_content: '让我想想……' }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
  });

mockFetch(reasoningOnly);
const lenientR = await chat([{ role: 'user', content: 'hi' }], { lenient: true });
check(lenientR.degraded === 'reasoning_only', 'lenient 模式：只有 reasoning_content 时返回 degraded 标记而非抛错');
check(lenientR.content === '', 'lenient 模式：content 保持空串，不伪造内容');
check(lenientR.reasoningChars > 0, `lenient 模式：记录 reasoning 字符数（${lenientR.reasoningChars}）`);

mockFetch(reasoningOnly);
try {
  await chat([{ role: 'user', content: 'hi' }]);
  check(false, '非 lenient 模式：只有 reasoning_content 时抛错', '未抛异常');
} catch (err) {
  check(
    /reasoning_content/.test(err.message) && /enableThinking/.test(err.message),
    '非 lenient 模式：抛错并点明「思考吃掉了预算」这一成因'
  );
}

// 启动自检路径：这一条直接对应「ping 失败即终止启动」那个被修掉的坑。
// 模型可达但 content 为空时，必须判为「可继续启动」，只是附加警告。
CONFIG.chatProvider = 'openai';
mockFetch(reasoningOnly);
const pingR = await pingProvider();
check(pingR.ok === true, 'ping：模型只返回 reasoning_content 时仍判为可达（不阻断启动）');
check(pingR.warning === true, 'ping：同时带 warning 标记，提示实际问答可能返回空');
check(/diag/.test(pingR.message || ''), 'ping：警告里给出下一步排查命令');

mockFetch(() => jsonResponse({ error: { message: 'Invalid token' } }, 401));
const pingBad = await pingProvider();
check(pingBad.ok === false, 'ping：真正的鉴权失败仍判为不可用');

/* ------------------------------ 错误翻译 ------------------------------ */

console.log('\n[6] 错误信息翻译');

async function expectError(responder, matcher, label) {
  mockFetch(responder);
  try {
    await chat([{ role: 'user', content: 'hi' }]);
    check(false, label, '未抛异常');
  } catch (err) {
    check(matcher.test(err.message), label, `实际信息：${err.message.slice(0, 160)}`);
  }
}

await expectError(() => jsonResponse({ error: { message: 'Invalid token' } }, 401), /API Key 无效/, '401 → 提示密钥无效');
await expectError(() => jsonResponse({ error: { message: 'not found' } }, 404), /模型名或路径不对/, '404 → 提示模型名/路径问题');
await expectError(() => jsonResponse({ error: { message: 'rate limited' } }, 429), /限流|额度/, '429 → 提示限流或额度');
await expectError(
  () => jsonResponse({ choices: [{ message: { content: '' }, finish_reason: 'length' }] }),
  /空内容.*length|finish_reason=length/,
  '空内容 → 报出 finish_reason 便于定位（如被 max_tokens 截断）'
);
await expectError(() => new Response('not json at all', { status: 200 }), /不是 JSON/, '非 JSON 响应 → 明确报错');

mockFetch(() => {
  throw Object.assign(new Error('connect ECONNREFUSED'), { cause: { code: 'ECONNREFUSED' } });
});
try {
  await chat([{ role: 'user', content: 'hi' }]);
  check(false, '网络不可达 → 抛出可读错误', '未抛异常');
} catch (err) {
  check(/连不上云端模型/.test(err.message), '网络不可达 → 抛出可读错误', err.message.slice(0, 160));
}

/* ---------------------------- Ollama 分发 ---------------------------- */

console.log('\n[7] provider 分发（切回 ollama 应打本地接口）');
CONFIG.chatProvider = 'ollama';
calls = mockFetch(() =>
  jsonResponse({
    message: { role: 'assistant', content: '本地回答' },
    prompt_eval_count: 10,
    eval_count: 5,
    total_duration: 1e9,
  })
);
const local = await chat([{ role: 'user', content: 'hi' }]);
check(calls[0].url.endsWith('/api/chat'), `打到 Ollama 的 /api/chat（${calls[0].url}）`);
check(local.content === '本地回答', '正确解析 Ollama 响应格式');
check(!calls[0].init.headers.Authorization, 'Ollama 请求不带 Authorization 头');

CONFIG.chatProvider = 'openai';

/* -------------------------------- 收尾 -------------------------------- */

globalThis.fetch = realFetch;
process.env[ENV_NAME] = '';
delete process.env[ENV_NAME];
CONFIG.chatApiKey = '';

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
