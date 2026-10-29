#!/usr/bin/env node
/**
 * 检索来源策略单测（**纯离线**，用假 index，不接触 Ollama）。
 *   node scripts/test-retrieve-policy.mjs
 *
 * 覆盖这次改造要解决的核心故障：
 *   `07_iMind-eFlow-Function-Operation-Guide.md` 占索引 52% 的块，
 *   中文问「级别/压缩」时向量容易漂到通用操作段落、topK 被同一文件占满
 *   （合规上：命中块还会随 search_knowledge 上传云端）。
 *
 * 要守住的三条：
 *   ① 领域规则题 → 不含 07_；
 *   ② 明确问操作手册（界面/菜单/用户组）→ 含 07_；
 *   ③ kbExcludeSources 为空时行为与改造前一致（可关）。
 */
import { retrieve, manualIntent, ungroundedIds, groundExcerpt, buildMessages } from '../src/rag.js';
import { tokenize, buildBm25Stats, bm25Score, normalizeBm25 } from '../src/rag.js';
import { CONFIG } from '../src/config.js';

let pass = 0;
let fail = 0;
function check(ok, name, extra = '') {
  if (ok) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.log(`  ✗ ${name}${extra ? `\n      ${extra}` : ''}`);
  }
}

console.log('='.repeat(50));
console.log('检索来源策略测试（离线）');
console.log('='.repeat(50));

// 假 index：2 个块，一个 03_（领域规则），一个 07_（操作手册）。
// 向量构造得让 07_ 语义更接近规则题（复现"漂到通用操作段落"）——
// 排除生效时它根本不该进候选。
const idx = {
  chunks: [
    { text: 'P1 级别规则：alarmCode=9995 且 downSiteCount>=5 时为 P1', source: 'knowledge/03_TT级别规则.md', title: '级别规则', seq: 0 },
    { text: 'Creating A User Group: click the menu, then Roles…', source: 'knowledge/07_iMind-eFlow-Function-Operation-Guide.md', title: 'Manual', seq: 0 },
  ],
  vectors: [
    [1, 0, 0],
    [0.9, 0.1, 0], // 与规则题方向接近 —— 不排除时会被召回
  ],
};

const CFG = {
  semanticWeight: 1,
  lexicalWeight: 0,
  idBonus: 0,
  topK: 6,
  minAbs: 0.2,
  minGap: 0,
  kbExcludeSources: ['knowledge/07_iMind-eFlow-Function-Operation-Guide.md'],
  kbManualIntent: '(用户组|角色|菜单|界面|如何创建|怎么创建|user group|how to (create|open|configure))',
};

const q = [1, 0, 0]; // 领域规则题的问句向量

console.log('\n[1] 默认排除 07_（领域规则题）');
{
  const r = retrieve({ queryVec: q, queryText: 'P1 怎么判定', index: idx, cfg: CFG });
  const srcs = r.hits.map((h) => h.source);
  check(!srcs.some((s) => s.includes('07_')), 'topK 不含 07_', JSON.stringify(srcs));
  check(r.excluded === 1, 'excluded 计数为 1', `excluded=${r.excluded}`);
  check(r.hits.length >= 1 && r.hits[0].source.includes('03_'), '规则块被召回');
  check(r.total === 1, '参与打分的块数 = 1（排除后的存活数）', `total=${r.total}`);
}

console.log('\n[2] 问法命中手册意图 → 放回 07_');
{
  const r = manualIntent('how to create a user group', CFG);
  check(r === true, 'manualIntent 命中 how to create a user group');

  const r2 = retrieve({ queryVec: q, queryText: 'how to create a user group', index: idx, cfg: CFG });
  const srcs = r2.hits.map((h) => h.source);
  check(srcs.some((s) => s.includes('07_')), '手册块出现在候选里', JSON.stringify(srcs));
  check(r2.excluded === 0, 'excluded 为 0（没排除任何块）', `excluded=${r2.excluded}`);

  const r3 = retrieve({ queryVec: q, queryText: '怎么创建一个用户组', index: idx, cfg: CFG });
  check(r3.hits.some((h) => h.source.includes('07_')), '中文「怎么创建一个用户组」也放回');
}

console.log('\n[3] kbExcludeSources 为空 → 行为与改造前一致');
{
  const cfgOff = { ...CFG, kbExcludeSources: [] };
  const r = retrieve({ queryVec: q, queryText: 'P1 怎么判定', index: idx, cfg: cfgOff });
  const srcs = r.hits.map((h) => h.source);
  check(srcs.some((s) => s.includes('07_')), '不排除时 07_ 照常进候选（可回退）', JSON.stringify(srcs));
  check(r.excluded === 0, 'excluded 为 0', `excluded=${r.excluded}`);
  check(r.total === 2, '两块都参与打分', `total=${r.total}`);
}

console.log('\n[4] manualIntent 健壮性');
{
  check(manualIntent('随便问问', { kbManualIntent: '' }) === false, '空正则 → false（不误开手册）');
  check(manualIntent('x', { kbManualIntent: '([' }) === false, '坏正则 → false（不抛，安全方向）');
  check(manualIntent(null, CFG) === false, 'null 提问 → false');
}

console.log('\n[5] 排除后块数不足时 useGap 退化（不误判）');
{
  // 排除到只剩 1 块 → useGap 应为 false（中位数不可靠）
  const r = retrieve({ queryVec: q, queryText: 'P1 怎么判定', index: idx, cfg: CFG });
  check(r.useGap === false, '存活块 < 4 → useGap=false', `total=${r.total} useGap=${r.useGap}`);
}

/* --------------------- A5：出处前缀 + 数字忠实度护栏 --------------------- */

console.log('\n[6] buildMessages 带出处处名');
{
  const hits = [
    { text: 'P1 规则…', source: 'knowledge/03_TT级别规则.md', title: 'TT 级别规则', confident: true },
  ];
  const msgs = buildMessages('P1 是什么', hits, 'zh');
  const userMsg = msgs.find((m) => m.role === 'user')?.content || '';
  check(userMsg.includes('knowledge/03_TT级别规则.md'), '上下文里带文件名', JSON.stringify(userMsg.slice(0, 80)));
  check(userMsg.includes('TT 级别规则'), '  带标题');
  check(/【1｜/.test(userMsg), '  用【i｜文件｜标题】格式', JSON.stringify(userMsg.slice(0, 40)));
  // 非 confident 的块不应进上下文
  const msgs2 = buildMessages('q', [{ text: 'x', source: 's', title: 't', confident: false }], 'zh');
  const u2 = msgs2.find((m) => m.role === 'user')?.content || '';
  check(!u2.includes('s'), '  非 confident 块不进上下文', JSON.stringify(u2.slice(0, 60)));
  // systemPrompt 里有出处新规则
  check(/来源：文件名/.test(CONFIG.systemPrompt), 'systemPrompt 含「来源：文件名」硬规则');
  check(/12 行/.test(CONFIG.systemPrompt), 'systemPrompt 放宽到 12 行（规则题不被剪条件）');
  check(!/5 行以内/.test(CONFIG.systemPrompt), '  去掉了「5 行以内」的硬限制');
}

console.log('\n[7] ungroundedIds：数字忠实度护栏');
{
  const hits = [{ text: '告警码 198094422 会被压缩成父告警 9970', confident: true }];
  // 假输出含资料里没有的 12345678 → 判编造
  check(ungroundedIds('压缩成 12345678 了', hits).includes('12345678'), '资料外数字 → ungrounded');
  // 资料里有的 9970 → 通过
  check(ungroundedIds('压缩成父告警 9970', hits).length === 0, '资料内数字 → 通过');
  // 短数字不算（0/1/2 常见）
  check(ungroundedIds('有 2 个', hits).length === 0, '短数字不误杀');
  // 没数字 → 通过
  check(ungroundedIds('资料里没有', hits).length === 0, '无长数字 → 通过');
  // 部分有部分没有 → 报没有的那个
  const mixed = ungroundedIds('9970 和 55555', hits);
  check(mixed.includes('55555') && !mixed.includes('9970'), '只报未落地的那个', JSON.stringify(mixed));
  // 非 confident 块不算依据
  const nh = [{ text: '9970', confident: false }];
  check(ungroundedIds('9970', nh).includes('9970'), '非 confident 块不能为数字背书');

  const ex = groundExcerpt(hits, 'zh');
  check(ex.includes('9970') && ex.includes('来源：'), '摘录式兜底含原文与来源', JSON.stringify(ex));
  check(groundExcerpt([], 'zh') === '', '无可用块时摘录为空（交给 notFoundText）');
}

/* --------------------------- B2：词级 BM25 --------------------------- */

console.log('\n[8] B2 分词 / BM25');
{
  const t1 = tokenize('告警码 198094422 会被压缩成什么');
  check(t1.includes('198094422'), '分词含数字 198094422', JSON.stringify(t1));
  check(t1.includes('压缩'), '中文 bigram 含「压缩」');
  const t2 = tokenize('Complete site down CSD');
  check(t2.includes('complete') && t2.includes('csd'), '英文按 token 小写化', JSON.stringify(t2));

  const chunks = [
    { text: '告警码 198094422 会被压缩成父告警 9970' },
    { text: '完全无关的天气说明文字' },
    { text: '198094422 是一个 4G 站点断站码' },
  ];
  const st = buildBm25Stats(chunks);
  const q = tokenize('198094422 压缩成什么');
  const raw = chunks.map((c, i) => bm25Score(q, st.tf[i], st));
  check(raw[0] > raw[1], '含目标码+压缩词的块分更高', JSON.stringify(raw.map((x) => +x.toFixed(3))));
  check(raw[1] === 0, '完全无关块 BM25=0');
  const norm = normalizeBm25(raw);
  check(norm[0] === 1 && norm[1] === 0, '归一化到 [0,1]，最高为 1', JSON.stringify(norm.map((x) => +x.toFixed(3))));
  check(normalizeBm25([0, 0, 0]).every((x) => x === 0), '全 0 时归一化仍全 0（纯语义题不受影响）');

  // ── 2026-10-28：双门槛（见 rag.js normalizeBm25 的注释）──
  // 语料涨到 5884 块后，纯 max 归一化会让**任何**查询都有一个 1.0，
  // 「今天天气怎么样」因此被判命中（top1 0.62）。下面钉住两个门槛的行为。
  const noisy = [10.48, 7.17, 8.24, 0]; // 实测的「天气 / 报销 / 食堂 / 无重叠」原始分
  check(
    normalizeBm25(noisy, { minRaw: 12, relMin: 0.35 }).every((x) => x === 0),
    '绝对门槛：单字噪声（原始分 <12）全部记 0',
    JSON.stringify(normalizeBm25(noisy, { minRaw: 12, relMin: 0.35 }))
  );
  const mixed = [52.48, 15.69, 15.62, 34.5]; // 实测：真命中 52.5 与同场的 15.7
  const gated = normalizeBm25(mixed, { minRaw: 12, relMin: 0.35 });
  check(
    gated[0] === 1 && gated[1] === 0 && gated[2] === 0,
    '相对门槛：52.5 同场时 15.7/15.6 归 0（不白送 +0.3）',
    JSON.stringify(gated.map((x) => +x.toFixed(3)))
  );
  check(gated[3] > 0 && gated[3] < 1, '  过了门槛的次优块仍保留比例分', String(+gated[3].toFixed(3)));
  check(
    normalizeBm25([52.48, 34.5], { minRaw: 0, relMin: 0 })[0] === 1,
    '不传门槛时保持旧的纯 max 归一（向后兼容）'
  );
}

console.log('\n[9] B2 融合：BM25 把字面精确的块顶上来');
{
  // 构造假 index：语义上 B 更高，但 A 字面精确（含目标码）。
  // 融合后 A 应能反超（这正是 idBonus 之外的额外保险）。
  const idx2 = {
    chunks: [
      { text: '规则速览：198094422 → 9970（4G site down）', source: 'k/cmp.md', title: 'cmp', seq: 0 },
      { text: '这是一段与告警压缩无关的操作说明', source: 'k/other.md', title: 'o', seq: 0 },
    ],
    vectors: [
      [0.8, 0.2], // A 语义略低
      [1.0, 0.0], // B 语义略高
    ],
  };
  const cfgNoBm = { semanticWeight: 1, lexicalWeight: 0, idBonus: 0, bm25Weight: 0, topK: 2, minAbs: 0, minGap: 0, kbExcludeSources: [], kbManualIntent: '' };
  const cfgBm = { ...cfgNoBm, bm25Weight: 0.6 };
  const qv = [1, 0];
  const noBm = retrieve({ queryVec: qv, queryText: '198094422 压缩成什么', index: idx2, cfg: cfgNoBm });
  const withBm = retrieve({ queryVec: qv, queryText: '198094422 压缩成什么', index: idx2, cfg: cfgBm });
  check(noBm.hits[0].source === 'k/other.md', '不开 BM25：语义高的块排第一（基线）', noBm.hits[0].source);
  check(withBm.hits[0].source === 'k/cmp.md', '开 BM25：字面精确的块反超排第一', withBm.hits[0].source);
}

console.log('\n[10] B4 MMR：同一来源限流');
{
  const chunks = [];
  const vecs = [];
  for (let i = 0; i < 6; i++) {
    chunks.push({ text: '块' + i, source: i < 5 ? 'k/same.md' : 'k/other.md', title: 't', seq: i });
    vecs.push([1 - i * 0.05, i * 0.01]);
  }
  const cfg = { semanticWeight: 1, lexicalWeight: 0, idBonus: 0, bm25Weight: 0, topK: 6, minAbs: 0, minGap: 0, kbExcludeSources: [], kbManualIntent: '', mmrMaxPerSource: 3 };
  const res = retrieve({ queryVec: [1, 0], queryText: 'x', index: { chunks, vectors: vecs }, cfg });
  const same = res.hits.filter((h) => h.source === 'k/same.md').length;
  check(same <= 3, '6 候选 5 个同 source → 截断后该 source ≤ 3', `same=${same}`);
  check(res.hits.some((h) => h.source === 'k/other.md'), '名额回填给其他来源');
  // 关闭时不限流
  const off = retrieve({ queryVec: [1, 0], queryText: 'x', index: { chunks, vectors: vecs }, cfg: { ...cfg, mmrMaxPerSource: 0 } });
  check(off.hits.filter((h) => h.source === 'k/same.md').length === 5, 'mmrMaxPerSource=0 → 不限流（可回退）');
}

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
