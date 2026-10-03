#!/usr/bin/env node
/**
 * 延迟基线测量 —— 用真实知识库问题跑**与群里完全一致**的答题链路。
 *
 * 目的：在考虑引入任何"更快的判定模型"之前，先拿到现状的**真实数字**。
 * 不看厂商 benchmark，只看这台机器上的实测。
 *
 *   npm run bench                 # 默认每问题 1 次
 *   npm run bench -- --repeat 3   # 每问题重复 3 次，取中位数（更能反映稳态）
 *   npm run bench -- --json out.json
 *
 * 注意：会真实调用配置里的对话模型（当前 = 云端 Agnes），消耗 API 额度。
 * 但**只读**，不写任何数据。用 --dry 可只看检索段耗时、不调模型。
 */
import { writeFileSync } from 'node:fs';
import { CONFIG } from '../src/config.js';
import { loadIndex } from '../src/rag.js';
import { routeAnswer } from '../src/answer.js';
import { providerInfo } from '../src/llm.js';

const argv = process.argv.slice(2);
const repeat = Number(argv[argv.indexOf('--repeat') + 1]) || 1;
const jsonOut = argv.includes('--json') ? argv[argv.indexOf('--json') + 1] : null;
const dry = argv.includes('--dry');
// 云端免费档有「每分钟请求数」限流，连打会 429。
// 默认每个请求之间隔一会儿，才能测出真实延迟而不是限流错误。
const paceMs = Number(argv[argv.indexOf('--pace') + 1]) || 0;

/**
 * 真实场景问题集。覆盖：
 *  - 概念/规则类（应命中知识库）
 *  - 排查/SOP 类（应命中）
 *  - 闲聊/超纲（应"未命中"，这条路径**不调模型**，所以最快）
 *  - 英文提问（验证语言分支）
 *  - 长问题（验证 token 增长的影响）
 */
const QUESTIONS = [
  { q: '告警是怎么变成 TT 单的？', tag: '链路', expect: 'hit' },
  { q: 'TT 级别是怎么定的？', tag: '规则', expect: 'hit' },
  { q: '告警衍生规则是什么', tag: '规则', expect: 'hit' },
  { q: '指派一致性校验是做什么的', tag: '规则', expect: 'hit' },
  { q: '告警压缩规则怎么配', tag: '规则', expect: 'hit' },
  { q: '级别缺失了怎么排查', tag: '排查', expect: 'hit' },
  { q: '配置巡检的 SOP 是什么', tag: '排查', expect: 'hit' },
  { q: 'iMind 里怎么创建一个 Function', tag: '操作', expect: 'hit' },
  { q: 'TT 指派和推单规则有什么区别', tag: '规则', expect: 'hit' },
  { q: '告警码字典里 1001 代表什么', tag: '字典', expect: 'hit' },
  { q: 'How does an alarm turn into a TT ticket?', tag: '英文', expect: 'hit' },
  { q: '今天天气怎么样？', tag: '超纲', expect: 'miss' },
  { q: '帮我写一首诗', tag: '超纲', expect: 'miss' },
];

const pct = (arr, p) => {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const i = Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1);
  return s[Math.max(0, i)];
};
const median = (arr) => pct(arr, 50);
const mean = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);

const info = providerInfo();
console.log('═'.repeat(74));
console.log('  延迟基线测量');
console.log('═'.repeat(74));
console.log(`  对话模型 : [${info.provider}] ${info.model}`);
console.log(`  嵌入模型 : ${CONFIG.embedModel} @ ${CONFIG.ollamaUrl}`);
console.log(`  重复次数 : ${repeat}${dry ? '   [DRY: 不调对话模型]' : ''}`);
console.log('═'.repeat(74) + '\n');

const index = loadIndex();
console.log(`索引：${index.meta.chunks} 块 / ${index.meta.files} 文件\n`);

const rows = [];
for (const { q, tag, expect } of QUESTIONS) {
  if (paceMs && rows.length) await new Promise((r) => setTimeout(r, paceMs));
  if (dry) {
    // 只测检索段（嵌入 + 打分），不调对话模型。
    // retrieve() 是同步的、且要预先算好 queryVec，所以这里手动分两段计时。
    try {
      const { retrieve } = await import('../src/rag.js');
      const { embedOne } = await import('../src/ollama.js');
      const t0 = Date.now();
      const queryVec = await embedOne(q);
      const embedMs = Date.now() - t0;
      const t1 = Date.now();
      const hits = retrieve({ queryVec, queryText: q, index });
      const rankMs = Date.now() - t1;
      const ms = Date.now() - t0;
      rows.push({ q, tag, expect, totalMs: ms, embedMs, rankMs, hit: hits.length > 0, outTok: null, err: null });
      console.log(`  ${String(ms).padStart(6)}ms  [${tag}] ${q}   (嵌入 ${embedMs}ms / 打分 ${rankMs}ms)`);
    } catch (e) {
      rows.push({ q, tag, expect, totalMs: null, hit: null, outTok: null, err: e.message });
      console.log(`  ${'-'.padStart(6)}ms ✗  [${tag}] ${q}\n           错误：${e.message}`);
    }
    continue;
  }

  const times = [];
  let last = null, err = null;
  for (let i = 0; i < repeat; i++) {
    if (i > 0 && paceMs) await new Promise((r) => setTimeout(r, paceMs));
    const t0 = Date.now();
    try {
      last = await routeAnswer(q, index, {});
      times.push(Date.now() - t0);
    } catch (e) {
      err = e.message;
      break;
    }
  }
  const med = median(times);
  rows.push({
    q, tag, expect,
    totalMs: med,
    times,
    hit: last?.answered ?? null,
    channel: last?.channel,
    outTok: last?.stats?.outputTokens ?? null,
    genMs: last?.stats?.genMs ?? null,
    err,
  });
  const flag = err ? '✗' : last?.answered ? '✓' : '·';
  console.log(
    `  ${String(med ?? '-').padStart(6)}ms ${flag}  [${tag}] ${q}` +
    (err ? `\n           错误：${err}` : '')
  );
}

// ── 汇总 ────────────────────────────────────────────────────────────
const ok = rows.filter((r) => !r.err);
const hitRows = ok.filter((r) => r.hit);

console.log('\n' + '═'.repeat(74));
console.log('  汇总');
console.log('═'.repeat(74));
console.log(`  样本          : ${ok.length}/${rows.length} 成功${ok.length < rows.length ? `，${rows.length - ok.length} 失败` : ''}`);

if (!dry) {
  const all = ok.map((r) => r.totalMs);
  console.log(`  端到端 (全部) : 中位 ${median(all)}ms  均值 ${Math.round(mean(all))}ms  p95 ${pct(all, 95)}ms  最快 ${Math.min(...all)}ms  最慢 ${Math.max(...all)}ms`);

  const hits = hitRows.map((r) => r.totalMs);
  const miss = ok.filter((r) => !r.hit).map((r) => r.totalMs);
  if (hits.length) console.log(`  命中知识库    : 中位 ${median(hits)}ms  (n=${hits.length})  ← 真正花钱的路径`);
  if (miss.length) console.log(`  未命中/超纲   : 中位 ${median(miss)}ms  (n=${miss.length})  ← 不调模型`);

  const toks = hitRows.map((r) => r.outTok).filter((t) => t != null);
  if (toks.length) console.log(`  输出 token    : 中位 ${median(toks)}  范围 ${Math.min(...toks)}-${Math.max(...toks)}`);
  const gens = hitRows.map((r) => r.genMs).filter((t) => t != null);
  if (gens.length) console.log(`  其中生成段    : 中位 ${median(gens)}ms  → 占端到端 ${Math.round((median(gens) / median(hits)) * 100)}%`);

  console.log('\n  按类别：');
  for (const tag of [...new Set(rows.map((r) => r.tag))]) {
    const g = ok.filter((r) => r.tag === tag).map((r) => r.totalMs);
    if (g.length) console.log(`    ${tag.padEnd(6)} 中位 ${String(median(g)).padStart(6)}ms  (n=${g.length})`);
  }
}
console.log('═'.repeat(74));

if (jsonOut) {
  writeFileSync(jsonOut, JSON.stringify({ at: new Date().toISOString(), provider: info, config: {
    chatModel: CONFIG.chatModel, embedModel: CONFIG.embedModel, topK: CONFIG.topK, maxTokens: CONFIG.maxTokens,
  }, dry, rows }, null, 2));
  console.log(`\n已写入 ${jsonOut}`);
}
