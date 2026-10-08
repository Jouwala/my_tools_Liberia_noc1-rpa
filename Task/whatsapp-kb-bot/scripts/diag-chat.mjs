#!/usr/bin/env node
/**
 * 云端对话模型诊断 —— 用来定位「返回空内容（finish_reason=stop）」这类问题。
 *
 *   npm run diag
 *
 * 设计思路：单次请求失败说明不了什么，必须做对照实验。
 * 用同一把 key 跑一组变量受控的请求，把「模型名」「thinking 开关」「token 预算」
 * 三个维度分别隔离出来，看哪个变量一改就恢复正常。
 *
 * 输出里不会出现密钥本身，只有长度和前缀。
 */
import { CONFIG } from '../src/config.js';
import { resolveApiKey } from '../src/llm.js';

const { key, source } = resolveApiKey();
const BASE = (CONFIG.chatBaseUrl || '').replace(/\/+$/, '');
const MODEL = CONFIG.chatModel;
const ALT_MODEL = 'glm-5.3-flash'; // 对照模型，从 WorkBuddy model-catalog 中取 x0.06 credits 的快模型

if (!key) {
  console.error('✗ 未读到 API Key。');
  console.error(`  期望来源：环境变量 ${CONFIG.chatApiKeyEnv} 或 config.json 的 chatApiKey`);
  console.error(`  当前 .env 里的 ${CONFIG.chatApiKeyEnv} 是空的。`);
  process.exit(1);
}

console.log('=== 云端对话模型诊断 ===');
console.log(`  端点      : ${BASE}/chat/completions`);
console.log(`  主模型    : ${MODEL}`);
console.log(`  对照模型  : ${ALT_MODEL}`);
console.log(`  密钥来源  : ${source}（${key.length} 字符，前缀 ${key.slice(0, 4)}***）`);
console.log(`  thinking  : ${CONFIG.enableThinking === null ? '未指定（用服务端默认）' : CONFIG.enableThinking}`);
console.log();

const results = [];

/** 发一次请求，打印完整结构 */
async function probe(label, { model = MODEL, maxTokens, thinking, messages, note = '' }) {
  const body = {
    model,
    messages,
    temperature: CONFIG.temperature,
    stream: false,
  };
  if (maxTokens != null) body.max_tokens = maxTokens;
  if (thinking === true || thinking === false) {
    body.chat_template_kwargs = { enable_thinking: thinking };
  }

  const brief = {
    model: body.model,
    max_tokens: body.max_tokens ?? '(未传)',
    enable_thinking: thinking === undefined ? '(未传)' : thinking,
    messages: messages.map((m) => `${m.role}:${String(m.content).slice(0, 18)}`).join(' | '),
  };

  console.log('─'.repeat(70));
  console.log(`【${label}】${note ? '  ' + note : ''}`);
  console.log(`  请求: ${JSON.stringify(brief)}`);

  const t0 = Date.now();
  let res, txt;
  try {
    res = await fetch(`${BASE}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(60000),
    });
    txt = await res.text();
  } catch (e) {
    console.log(`  ✗ 网络错误 ${e.name}: ${e.message}`);
    results.push({ label, ok: false, why: `网络错误 ${e.name}` });
    console.log();
    return;
  }

  const ms = Date.now() - t0;
  console.log(`  响应: HTTP ${res.status} | ${ms}ms`);

  if (!res.ok) {
    console.log(`  正文: ${txt.slice(0, 300)}`);
    results.push({ label, ok: false, why: `HTTP ${res.status}` });
    console.log();
    return;
  }

  let d;
  try {
    d = JSON.parse(txt);
  } catch {
    console.log(`  ✗ 响应不是 JSON: ${txt.slice(0, 200)}`);
    results.push({ label, ok: false, why: '非 JSON 响应' });
    console.log();
    return;
  }

  const ch = d.choices?.[0];
  const msg = ch?.message || {};
  const content = (msg.content ?? '').trim();
  const reasoning = msg.reasoning_content;

  console.log(`  finish_reason : ${ch?.finish_reason}`);
  console.log(`  message 字段  : [${Object.keys(msg).join(', ')}]`);
  console.log(`  content       : ${content ? JSON.stringify(content.slice(0, 120)) : '（空）'}`);
  if (reasoning) {
    console.log(`  reasoning     : ${JSON.stringify(String(reasoning).slice(0, 120))}  (${String(reasoning).length} 字符)`);
  }
  console.log(`  usage         : ${JSON.stringify(d.usage)}`);
  if (!content) console.log(`  完整响应      : ${txt.slice(0, 500)}`);

  results.push({
    label,
    ok: !!content,
    why: content ? `正常（${content.length} 字符）` : reasoning ? '只有 reasoning_content' : `空 content (finish=${ch?.finish_reason})`,
    model: body.model,
  });
  console.log();
}

const MSG_MIN = [
  { role: 'system', content: 'Reply briefly.' },
  { role: 'user', content: '只回复两个字：正常' },
];
const MSG_SYS = [
  { role: 'system', content: '你是一个只依据资料回答的助手，用中文，简短。' },
  { role: 'user', content: '资料：年假15天。\n\n问题：年假有几天？' },
];

/* 1) 复现启动时那次失败：极小预算 */
await probe('A. 复现失败现场', {
  maxTokens: 8,
  messages: MSG_MIN,
  note: '（旧版启动自检用的就是 max_tokens=8）',
});

/* 2) 官方文档的基础示例：给足预算，不指定 thinking */
await probe('B. 官方基础示例等价', {
  maxTokens: 1024,
  messages: MSG_MIN,
  note: '（文档基础请求用的就是 max_tokens=1024）',
});

/* 3) 显式关闭 thinking */
await probe('C. 显式关闭 thinking', {
  maxTokens: 1024,
  thinking: false,
  messages: MSG_MIN,
});

/* 4) 显式开启 thinking —— 用来确认这个参数服务端到底认不认 */
await probe('D. 显式开启 thinking', {
  maxTokens: 1024,
  thinking: true,
  messages: MSG_MIN,
});

/* 5) 换对照模型 —— 如果这个有内容而主模型没有，就是模型可用性/权限问题 */
await probe('E. 对照模型', {
  model: ALT_MODEL,
  maxTokens: 1024,
  messages: MSG_MIN,
});

/* 6) 真实场景：带 system prompt */
await probe('F. 真实问答场景', {
  maxTokens: 512,
  thinking: false,
  messages: MSG_SYS,
});

/* ------------------------------- 结论 ------------------------------- */
console.log('='.repeat(70));
console.log('结论：\n');

const ok = results.filter((r) => r.ok);
const mainOk = results.filter((r) => r.ok && r.model === MODEL);

if (mainOk.length === 0) {
  const altOk = results.find((r) => r.ok && r.model === ALT_MODEL);
  if (altOk) {
    console.log(`  ✗ 主模型 ${MODEL} 全部失败，但对照模型 ${ALT_MODEL} 正常。`);
    console.log(`    → 问题在模型本身：WorkBuddy 账号可能没有 ${MODEL} 的访问权限，或该模型未对你开放。`);
    console.log(`      在 WorkBuddy 代理启动脚本确认模型列表，或暂时改用 ${ALT_MODEL}。`);
  } else if (results.some((r) => r.why === '只有 reasoning_content')) {
    console.log('  ✗ 所有请求都只返回 reasoning_content、content 为空。');
    console.log('    → 模型把输出全放进了思维链。优先尝试调大 maxTokens（1024 以上），');
    console.log('      或改用 /v1/messages（Anthropic 兼容）端点，其 thinking 用 budget_tokens 单独控制。');
  } else {
    console.log('  ✗ 全部失败，且没有 reasoning_content。');
    console.log('    → 检查 base URL、模型名、以及账户额度。详细原因见上方各项的响应正文。');
  }
} else {
  // 找出让主模型恢复正常的变量
  const withThinkingOff = results.find((r) => r.label.startsWith('C.') && r.ok);
  const withBigBudget = results.find((r) => r.label.startsWith('B.') && r.ok);
  const tiny = results.find((r) => r.label.startsWith('A.'));
  const real = results.find((r) => r.label.startsWith('F.'));

  console.log(`  ✓ 主模型 ${MODEL} 可以正常返回内容（${mainOk.length}/${results.filter((r) => r.model === MODEL).length} 项成功）。`);

  if (tiny && !tiny.ok && withBigBudget) {
    console.log('  · 根因一：token 预算太小。max_tokens=8 失败，1024 成功。');
    console.log('    → config.json 的 maxTokens 保持 512 即可，启动自检已提到 256。');
  }
  if (!withThinkingOff && withBigBudget) {
    console.log('  · 根因二：服务端不接受 enable_thinking=false（该项失败），但不传该参数时正常。');
    console.log('    → 把 config.json 的 "enableThinking" 删掉，让服务端用默认值。');
  }
  if (withThinkingOff && withBigBudget) {
    console.log('  · thinking 开关被服务端接受，关闭后仍正常。当前配置可用。');
  }
  if (real && !real.ok) {
    console.log('  · 注意：带 system prompt 的真实场景失败了 —— 问题出在消息格式，不是模型本身。');
  } else if (real && real.ok) {
    console.log('  ✓ 带 system prompt 的真实问答场景通过，机器人应可正常工作。');
  }
}

console.log();
console.log(`（共 ${results.length} 项：成功 ${ok.length}，失败 ${results.length - ok.length}）`);
console.log('把以上完整输出发回即可定位。');
