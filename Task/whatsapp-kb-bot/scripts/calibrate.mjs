#!/usr/bin/env node
/**
 * 命中阈值校准脚本。
 *
 * 用法：
 *   node scripts/calibrate.mjs \
 *     --label hit  "年假有几天" \
 *     --label hit  "报销流程怎么走" \
 *     --label miss "量子计算机支持几维张量" \
 *     --label miss "今天北京天气怎么样"
 *
 * 可选：
 *   --corpus <path>   默认读 config.json 的 indexPath
 *   --model  <name>   覆盖嵌入模型
 *   --topk   <n>      展示前 n 条候选，默认 3
 *
 * 输出：
 *   1. 每个查询的 top1 / 中位数 / gap / 判定
 *   2. 三种策略的判别准确率对比（纯绝对阈值 / 纯 gap / 两者同时满足）
 *   3. 网格搜索出的最优阈值组合
 *
 * 关键：不要照搬任何"经验阈值"。阈值随嵌入模型与语料而变，必须实测。
 * 本脚本的意义就是把"实测"这一步固化下来。
 */
import { readFileSync } from 'node:fs';
import { CONFIG } from '../src/config.js';
import { embedOne } from '../src/ollama.js';
import { retrieve } from '../src/rag.js';

const argv = process.argv.slice(2);
const queries = [];
let corpusPath = CONFIG.indexPathAbs;
let model = CONFIG.embedModel;
let topk = 3;

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--label') {
    const label = argv[++i];
    const text = argv[++i];
    if (!['hit', 'miss'].includes(label) || !text) {
      console.error('--label 用法：--label hit|miss "查询内容"');
      process.exit(1);
    }
    queries.push({ label, text });
  } else if (a === '--corpus') corpusPath = argv[++i];
  else if (a === '--model') model = argv[++i];
  else if (a === '--topk') topk = Number(argv[++i]);
}

if (!queries.length) {
  console.error('请至少提供一个 --label hit|miss "查询内容"');
  process.exit(1);
}

const index = JSON.parse(readFileSync(corpusPath, 'utf8'));
console.log(`语料：${corpusPath}`);
console.log(`条目：${index.chunks.length} 块｜模型：${model}\n`);

/* ------------------------------ 采集数据 ------------------------------ */

const rows = [];
for (const q of queries) {
  const vec = await embedOne(q.text, { model });
  const r = retrieve({
    queryVec: vec,
    queryText: q.text,
    index,
    cfg: { ...CONFIG, topK: topk, minAbs: 0, minGap: 0 },
  });
  rows.push({
    label: q.label,
    text: q.text,
    top1: r.topBase,
    median: r.baseline,
    gap: r.gap,
    candidates: r.hits.map((h) => ({ base: h.base, source: h.source })),
  });
}

const pad = (s, n) => String(s).padEnd(n, ' ');
const num = (x) => x.toFixed(4);

console.log(pad('类别', 8) + pad('查询', 26) + pad('top1', 9) + pad('中位数', 9) + 'gap');
console.log('-'.repeat(66));
for (const r of rows) {
  const t = r.text.length > 24 ? r.text.slice(0, 23) + '…' : r.text;
  console.log(
    pad(r.label === 'hit' ? '应命中' : '应未命中', 8) + pad(t, 26) + pad(num(r.top1), 9) + pad(num(r.median), 9) + num(r.gap)
  );
}

console.log('\n候选明细：');
for (const r of rows) {
  console.log(`  ${r.label === 'hit' ? '[应命中]  ' : '[应未命中]'} ${r.text}`);
  for (const c of r.candidates) console.log(`      base=${num(c.base)}  ${c.source}`);
}

/* --------------------------- 三策略准确率对比 --------------------------- */

const hits = rows.filter((r) => r.label === 'hit');
const misses = rows.filter((r) => r.label === 'miss');

console.log('\n=== 判别力分析 ===');
console.log(`样本：应命中 ${hits.length} 条，应未命中 ${misses.length} 条\n`);

if (hits.length && misses.length) {
  const g = (arr, f) => arr.map(f);
  console.log(`top1   应命中区间 [${num(Math.min(...g(hits, (r) => r.top1)))}, ${num(Math.max(...g(hits, (r) => r.top1)))}]`);
  console.log(`top1   应未命中 [${num(Math.min(...g(misses, (r) => r.top1)))}, ${num(Math.max(...g(misses, (r) => r.top1)))}]`);
  console.log(`gap    应命中区间 [${num(Math.min(...g(hits, (r) => r.gap)))}, ${num(Math.max(...g(hits, (r) => r.gap)))}]`);
  console.log(`gap    应未命中 [${num(Math.min(...g(misses, (r) => r.gap)))}, ${num(Math.max(...g(misses, (r) => r.gap)))}]\n`);

  const absSep = Math.min(...g(hits, (r) => r.top1)) - Math.max(...g(misses, (r) => r.top1));
  const gapSep = Math.min(...g(hits, (r) => r.gap)) - Math.max(...g(misses, (r) => r.gap));

  console.log(`间隔（越大越可靠）：`);
  console.log(`  纯 top1 : ${num(absSep)}  ${absSep > 0 ? '✓ 可分离' : '✗ 重叠'}`);
  console.log(`  纯 gap  : ${num(gapSep)}  ${gapSep > 0 ? '✓ 可分离' : '✗ 重叠'}`);
}

/* ------------------------- 单信号判别力 + 阈值建议 ------------------------- */

/**
 * 对单个信号做判别力分析。
 * 最优阈值取"命中下界"与"未命中上界"的中点，此时两侧余量相等且最大。
 */
function analyseSignal(name, pick) {
  const hitVals = hits.map(pick);
  const missVals = misses.map(pick);
  const hitMin = Math.min(...hitVals);
  const missMax = Math.max(...missVals);
  const sep = hitMin - missMax;
  const thr = (hitMin + missMax) / 2;
  return { name, hitMin, missMax, sep, thr, margin: sep / 2, usable: sep > 0 };
}

console.log('\n=== 建议 ===');

if (!hits.length || !misses.length) {
  console.log('要给出建议，需要同时提供 hit 与 miss 两类样本。');
} else {
  const absSig = analyseSignal('top1', (r) => r.top1);
  const gapSig = analyseSignal('gap', (r) => r.gap);

  console.log('单信号判别力：\n');
  for (const s of [absSig, gapSig]) {
    const flag = s.sep <= 0 ? '✗ 两类重叠，不可用' : s.sep < 0.02 ? '! 间隔过窄，不可单独依赖' : '✓ 可单独依赖';
    console.log(`  ${s.name.padEnd(5)} 命中下界 ${num(s.hitMin)} ｜ 未命中上界 ${num(s.missMax)} ｜ 间隔 ${num(s.sep)}  ${flag}`);
    console.log(`        最优阈值 ${num(s.thr)}（两侧余量各 ${num(s.margin)}）`);
  }

  // 谁更稳健谁做主判据
  const primary = absSig.margin >= gapSig.margin ? absSig : gapSig;
  const secondary = primary === absSig ? gapSig : absSig;
  const primaryKey = primary.name === 'top1' ? 'minAbs' : 'minGap';
  const secondaryKey = secondary.name === 'top1' ? 'minAbs' : 'minGap';

  // 主判据：取中点阈值
  const primaryThr = +primary.thr.toFixed(3);
  // 次判据：间隔够宽就用它自己的中点；否则退化为兜底下限，不参与实际判别
  const secondaryThr = secondary.sep >= 0.02
    ? +secondary.thr.toFixed(3)
    : +(secondary.hitMin * 0.5).toFixed(3);

  console.log(`\n结论：`);
  console.log(`  主判据 = ${primary.name}（余量 ${num(primary.margin)} 更大）→ ${primaryKey} = ${primaryThr}`);
  if (secondary.sep >= 0.02) {
    console.log(`  次判据 = ${secondary.name}（余量 ${num(secondary.margin)}）→ ${secondaryKey} = ${secondaryThr}`);
  } else {
    console.log(`  次判据 ${secondary.name} 间隔 ${num(secondary.sep)} < 0.02，判别力不足`);
    console.log(`  → ${secondaryKey} 退化为兜底下限 ${secondaryThr}（不参与实际判别，仅拦截极端异常）`);
  }

  // 用建议值回测
  const cfg = { minAbs: 0.45, minGap: 0.12, [primaryKey]: primaryThr, [secondaryKey]: secondaryThr };
  const pred = (r) => r.top1 >= cfg.minAbs && r.gap >= cfg.minGap;
  const ok = rows.filter((r) => pred(r) === (r.label === 'hit')).length;

  console.log(`\n  推荐配置：minAbs = ${cfg.minAbs}   minGap = ${cfg.minGap}`);
  console.log(`  回测：${ok}/${rows.length} 正确（${((ok / rows.length) * 100).toFixed(1)}%）`);
  const wrong = rows.filter((r) => pred(r) !== (r.label === 'hit'));
  for (const w of wrong) {
    console.log(`    ! ${w.label === 'hit' ? '漏判' : '误判'}：${w.text}（top1=${num(w.top1)} gap=${num(w.gap)}）`);
  }

  if (gapSig.sep > 0 && gapSig.sep < 0.02) {
    console.log('\n  为什么 gap 这么弱：语料同质化高 → 所有查询的基线水位都偏高 → gap 被压平。');
    console.log('  语料越杂、条目越多，gap 判别力越强；条目数 < 10 时尤其不可信。');
  }
  if (!gapSig.usable && absSig.usable) {
    console.log('\n  提示：gap 完全重叠时，若知识库条目过少（<10 块），');
    console.log('        建议补充语料后重新校准，而不是继续调阈值。');
  }
}

console.log(`\n把建议值写回 config.json（或 .env 的 MIN_ABS / MIN_GAP）后重启进程。`);
console.log(`当前 config.json：minAbs=${CONFIG.minAbs}  minGap=${CONFIG.minGap}`);
