#!/usr/bin/env node
/**
 * 语言适配测试：提问语言判定 + 固定文案取用。
 *   node scripts/test-lang.mjs
 *
 * 为什么必须单测：
 *   · `detectLang` 的判定直接决定回复语种，判错的代价是「整条回复看不懂」；
 *   · 更隐蔽的是**不经过模型**的那几句固定回复（未命中 / 排队 / 故障 /
 *     TT 失败）—— 它们既不受 systemPrompt 约束，也不会被 LANG_HINT 影响，
 *     漏翻一处只有英文提问时才会暴露，且看起来像「偶尔冒中文」的玄学问题。
 *
 * 全部为纯函数 + 源码调用点检查，不联网、不读工单库，可离线跑。
 */
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { detectLang, pickText, DEFAULT_LANG } from '../src/lang.js';
import { buildMessages } from '../src/rag.js';
import { CONFIG } from '../src/config.js';

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

/* ------------------------------------------------------------------ */
console.log('\n[1] detectLang：中文 / 英文判定');

const cases = [
  // [输入, 期望, 说明]
  ['analyze TT202609110023', 'en', '纯英文句子'],
  ['Please analyze TT202609110023', 'en', '英文 + 单号'],
  ['分析下TT202609110023', 'zh', '纯中文'],
  ['TT202609110023', 'en', '只有单号（无语言信号 → 按英文）'],
  ['please 分析 TT202609110023', 'zh', '中英混排 → 含汉字即判中文'],
  ['什么是告警压缩？', 'zh', '中文 + 全角问号'],
  // ⚠️ 核心边界：有人用中文输入法打英文句子，结尾是全角 `？`。
  // 若把全角标点也算作中文信号，这句会被误判成中文。
  ['analyze TT202609110023？', 'en', '英文句子 + 全角问号 → 仍判英文'],
  ['analyze TT202609110023?', 'en', '英文句子 + 半角问号'],
  ['＃alarm', 'en', '全角井号不算中文信号'],
  ['〇', 'en', 'U+3007 不在汉字区间（不算中文信号）'],
  ['工', 'zh', '单个汉字'],
  // 明确的已知边界：CJK 扩展 B 区（U+20000+）不在判定范围内。
  // 真实语料不会出现这类字，但行为要写下来，免得日后当成 bug 排查。
  ['𠀀', 'en', '扩展 B 区汉字不在判定范围（已知边界，非缺陷）'],
];

for (const [input, want, why] of cases) {
  const got = detectLang(input);
  check(got === want, `detectLang(${JSON.stringify(input)}) === '${want}'（${why}）`,
    `实得 '${got}'`);
}

/* ------------------------------------------------------------------ */
console.log('\n[2] detectLang：空值 / 非法输入不抛异常');

// 空提问（只 @ 了机器人没写内容）没有语言信号 → 回退默认值。
// 若不特判，空串会因为「不含汉字」被判成英文，`@bot` 就会收到英文回复 ——
// 这是没人要求的行为变更。
for (const v of ['', '   ', '\n\t', null, undefined]) {
  const got = detectLang(v);
  check(got === DEFAULT_LANG,
    `detectLang(${JSON.stringify(v)}) → 回退 '${DEFAULT_LANG}'`, `实得 '${got}'`);
}

const weird = [0, 123, {}, [], true, NaN, Symbol('x')];
let weirdErr = '';
for (const v of weird) {
  try {
    const r = detectLang(v);
    if (r !== 'zh' && r !== 'en') weirdErr = `detectLang(${String(v)}) 返回 ${JSON.stringify(r)}`;
  } catch (e) {
    weirdErr = `detectLang(${String(v)}) 抛异常：${e.message}`;
  }
}
check(!weirdErr, '非字符串输入（数字 / 对象 / Symbol）不抛异常且返回合法语言', weirdErr);
check(DEFAULT_LANG === 'zh', "DEFAULT_LANG === 'zh'");

/* ------------------------------------------------------------------ */
console.log('\n[3] pickText：英文缺失必须回退中文，不能发出空消息');

check(pickText('zh', '中文', 'English') === '中文', "pickText('zh',...) 取中文");
check(pickText('en', '中文', 'English') === 'English', "pickText('en',...) 取英文");
check(pickText('en', '中文', undefined) === '中文', '英文缺失 → 回退中文');
check(pickText('en', '中文', '') === '中文', '英文为空串 → 回退中文');
check(pickText('en', '中文', null) === '中文', '英文为 null → 回退中文');
check(pickText('fr', '中文', 'English') === '中文', '未知语言 → 取中文');
check(pickText(undefined, '中文', 'English') === '中文', 'lang 未传 → 取中文');

/* ------------------------------------------------------------------ */
console.log('\n[4] 固定文案配置：每组都必须有英文版（漏配 = 英文提问收到中文）');

const fixedPairs = [
  ['notFoundText', 'notFoundTextEn', '知识库未命中'],
  ['errorText', 'errorTextEn', '程序故障兜底'],
  ['busyText', 'busyTextEn', '排队已满'],
];

for (const [zhKey, enKey, why] of fixedPairs) {
  const zh = CONFIG[zhKey];
  const en = CONFIG[enKey];
  check(typeof zh === 'string' && zh.trim() !== '', `${zhKey} 已配置（${why}）`);
  check(typeof en === 'string' && en.trim() !== '', `${enKey} 已配置（${why}）`);
  // 英文版里不能残留汉字 —— 配了但复制粘贴忘了改，等于没配
  const han = (en || '').match(/[\u4e00-\u9fff\u3400-\u4dbf]/g);
  check(!han, `${enKey} 不含汉字`, han ? `残留：${[...new Set(han)].join('')}` : '');
  check(zh !== en, `${zhKey} / ${enKey} 内容不同（没忘改）`);
}

/* ------------------------------------------------------------------ */
console.log('\n[5] systemPrompt：语言要求必须写明（知识库通道靠它 + LANG_HINT）');

check(/用与提问相同的语言回答/.test(CONFIG.systemPrompt),
  'systemPrompt 含「用与提问相同的语言回答」');
// 曾经写成 `**用与提问相同的语言回答**`，与第 5 条「不要输出 Markdown」自相矛盾
check(!CONFIG.systemPrompt.includes('**'),
  'systemPrompt 不含 Markdown 加粗（避免诱导模型输出 Markdown）');

/* ------------------------------------------------------------------ */
console.log('\n[6] buildMessages：语言提示要落在消息序列**最后**（离生成最近）');

const hits = [{ text: '资料内容 A', confident: true }, { text: '低置信 B', confident: false }];

const msgEn = buildMessages('analyze TT1', hits, 'en');
check(msgEn.length === 2, '组装出 system + user 两条消息');
check(msgEn[0].role === 'system' && msgEn[1].role === 'user', '角色顺序为 system → user');
check(/English/.test(msgEn[0].content), "lang='en' → system 含 English 语言要求");
check(msgEn[0].content.startsWith(CONFIG.systemPrompt),
  'systemPrompt 在前，语言提示**追加在末尾**（不是插到中间）');
check(msgEn[0].content.length > CONFIG.systemPrompt.length,
  '语言提示确实被追加（system 比原始 prompt 长）');

const msgZh = buildMessages('分析 TT1', hits, 'zh');
check(/中文/.test(msgZh[0].content), "lang='zh' → system 含中文语言要求");
check(!/English/.test(msgZh[0].content), "lang='zh' 时不残留英文语言要求");

// 未传 / 非法语言 → 回退中文，且不能出现 undefined 拼接
const msgDefault = buildMessages('q', hits);
const msgBad = buildMessages('q', hits, 'fr');
check(/中文/.test(msgDefault[0].content), '未传 lang → 默认中文提示');
check(!/undefined/.test(msgDefault[0].content), '未传 lang 时不出现 "undefined" 拼接');
check(msgBad[0].content === msgDefault[0].content, '非法语言 → 与默认中文完全一致');

// 只喂 confident 的条目
check(msgEn[1].content.includes('资料内容 A'), 'user 消息含高置信资料');
check(!msgEn[1].content.includes('低置信 B'), 'user 消息**不含**低置信资料（不能当依据）');
check(msgEn[1].content.includes('analyze TT1'), 'user 消息含原始问题');

/* ------------------------------------------------------------------ */
console.log('\n[7] 调用点检查：确认文案真的「按语言取」，而不是配了没用');

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => readFileSync(resolve(ROOT, rel), 'utf8');

const srcWhatsapp = read('src/whatsapp.js');
const srcRag = read('src/rag.js');
const srcTt = read('src/tt.js');
const srcIndex = read('src/index.js');
const srcAnswer = read('src/answer.js');
const srcTools = read('src/tools.js');

check(/pickText\(lang, CONFIG\.busyText, CONFIG\.busyTextEn\)/.test(srcWhatsapp),
  'whatsapp.js：busyText 按语言取');
check(/pickText\(lang, CONFIG\.errorText, CONFIG\.errorTextEn\)/.test(srcWhatsapp),
  'whatsapp.js：errorText 按语言取');
check(/put your question after the @mention/.test(srcWhatsapp),
  'whatsapp.js：「只 @ 没提问」的回复也有英文版');
check(/detectLang\(question\)/.test(srcWhatsapp),
  'whatsapp.js：在接入层判定提问语言（源头唯一）');
// 传入的对象跨多行，且后续加入了 onRetry / history —— 用 [\s\S] 跨行匹配，
// 只断言「chatJid / sender / lang 都在这个对象里」这个实质，
// 不绑定换行与缩进（否则每次调整格式都要改测试）。
// 2026-10-07：加了 history 字段（带一段注释）后 200 字窗口不够用了，
// 放宽到 600 —— 窗口是防"匹配到别的对象"的，不是用来卡格式的。
check(/onQuestion\(question,\s*\{[\s\S]{0,600}?\blang\b[\s\S]{0,600}?\}\)/.test(srcWhatsapp) &&
  /onQuestion\(question,\s*\{[\s\S]{0,100}?\bchatJid\b/.test(srcWhatsapp),
  'whatsapp.js：把 lang 传给上层（避免重复判定 / 口径不一致）');

check(/pickText\(lang, cfg\.notFoundText, cfg\.notFoundTextEn\)/.test(srcRag),
  'rag.js：notFoundText 按语言取');

// 会话历史接线（2026-10-07）：
// 「那个单子未闭环」这类**追问单看没有主语**，没有历史就会被当成新问题猜，
// 实测答成了「今天全网 36 单」——答的是另一个问题且不报错。
check(/history:\s*getHistory\(chatJid\)/.test(srcWhatsapp),
  'whatsapp.js：把会话历史传给上层（追问才落得下来）');
check(/rememberTurn\(chatJid, question, text2\)/.test(srcWhatsapp),
  'whatsapp.js：回复后记入会话历史');
check(/if \(result\.answered\) rememberTurn/.test(srcWhatsapp),
  'whatsapp.js：答不上来的不进历史（否则把下一轮也带偏）');
check(/history/.test(srcAnswer),
  'answer.js：history 透传下去');
check(/opts\.history/.test(srcTools),
  'tools.js：路由时把历史喂给模型');

// ── 传参链的**每一环**都要断言 ──
// 2026-10-07 实测踩过：whatsapp.js 传了、answer.js 收了、tools.js 也用了，
// 但中间的 index.js 没转发给 routeAnswer —— 于是探针里追问能正确定位到
// TT202610020012，群里却走成知识库、32 秒后答无关内容。
// 断链的那一环单看「没问题」，只有端到端才暴露，所以逐环钉死。
check(/onQuestion:\s*async\s*\(question,\s*\{[^}]*\bhistory\b/.test(srcIndex),
  'index.js：从接入层**接收** history');
check(/routeAnswer\(question,\s*index,\s*\{[\s\S]{0,600}?\bhistory\b[\s\S]{0,200}?\}\)/.test(srcIndex),
  'index.js：把 history **转发**给 routeAnswer（这一环断过）');check(/^\s*en: '/m.test(srcRag), 'rag.js：LANG_HINT 提供英文版');

// TT 通道的失败文案：必须在 Node 侧按语言取
// （脚本没能正常返回时，只能由调用方兜底）
for (const key of ['timeout', 'error', 'empty', 'unknown']) {
  const n = (srcTt.match(new RegExp(`^\\s+${key}:`, 'gm')) || []).length;
  check(n >= 2, `tt.js：失败文案 '${key}' 同时提供 zh / en（实得 ${n} 处）`);
}
// 实时兜底（本地库 miss → 回 eFlow 实时查）的文案同样不能写死中文：
// 英文提问时收到「我去 eFlow 实时查一下」会显得很突兀，
// 而这几句是**不经过模型**的固定回复，改 prompt 管不到。
for (const key of ['goingLive', 'liveMiss', 'liveError']) {
  const n = (srcTt.match(new RegExp(`^\\s+${key}:`, 'gm')) || []).length;
  check(n >= 2, `tt.js：实时兜底文案 '${key}' 同时提供 zh / en（实得 ${n} 处）`);
}
// 垫话必须真的被发出去 —— 只配文案不发，等于用户还是干等十几秒。
check(/onLive\?\.\(F\.goingLive\(ttNo\)\)/.test(srcTt),
  'tt.js：实时查询前确实调用了 onLive（垫话有发出去）');
check(/onLive:/.test(srcWhatsapp), 'whatsapp.js：把 onLive 垫话接到 send');

check(/const F = FAIL_TEXT\[replyLang\]/.test(srcTt), 'tt.js：按 replyLang 取失败文案表');
check(!/text: `分析 \$\{ttNo\}/.test(srcTt), 'tt.js：已无写死中文的失败文案');

// 接入层把 lang 交给 onQuestion，index.js 必须**原样接收**（而不是丢掉再自己判一次）。
// 这里只锚定「解构里有 lang」，不锚定它后面跟哪个键 ——
// 后续接入 onLive 之类的回调时不该再改这条测试（曾经就是写死了 `lang, onRetry` 才误报）。
check(/onQuestion: async \(question, \{ lang\b/.test(srcIndex),
  'index.js：onQuestion 接收 lang');
check(/^\s*lang,\s*$/m.test(srcIndex), 'index.js：把 lang 转发给 routeAnswer');

// 全项目扫描：确认没有「直接发出中文、却没走 pickText」的群聊文案残留。
// 只查**会被 send 出去**的那几处，控制台日志不在此列。
const sentLiterals = [
  ['src/whatsapp.js', /send\(\s*chatJid,\s*'[^']*[\u4e00-\u9fff]/],
  ['src/rag.js', /text:\s*cfg\.[a-zA-Z]+Text(?!En)/],
];
let residual = '';
for (const [file, re] of sentLiterals) {
  const m = read(file).match(re);
  if (m) residual += `${file}: ${m[0].trim()}\n`;
}
check(!residual, '全项目无「直接发出中文」的群聊文案残留', residual);

/* ------------------------------------------------------------------ */
console.log('\n' + '='.repeat(50));
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
