#!/usr/bin/env node
/**
 * 索引去重回归测试。
 *   node scripts/test-dedupe.mjs
 *
 * 背景：实测线上索引 816 块里有 73 块是纯重复（9%），最多的一段
 * 样板文字被切成了 34 份。危害不是占空间，而是**吃掉 topK 名额** ——
 * 6 个名额全命中同一段重复文本时，模型实际只拿到 1 条信息。
 *
 * 核心不变量：
 *   1. 归一化后相同的文本只保留一份；
 *   2. 不同的文本**一个都不能合并**（误合并比漏合并严重得多）；
 *   3. 去重后顺序稳定（首个出现的位置胜出）。
 */
import { dedupeChunks } from '../src/ingest.js';
import { chunkText } from '../src/rag.js';

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

const C = (text, source = 'a.md', seq = 0) => ({ text, source, title: 'T', seq });

console.log('='.repeat(50));
console.log('索引去重回归测试');
console.log('='.repeat(50));

/* ------------------------------ 基本去重 ------------------------------ */

console.log('\n[1] 基本去重');
{
  const r = dedupeChunks([C('甲'), C('乙'), C('甲')]);
  check(r.chunks.length === 2, '重复项只保留一份', `实际 ${r.chunks.length}`);
  check(r.removed === 1, 'removed 计数正确', `实际 ${r.removed}`);
  check(r.chunks[0].text === '甲' && r.chunks[1].text === '乙', '顺序稳定（首个出现位置胜出）');
}

console.log('\n[2] 空白差异视为同一块');
{
  const r = dedupeChunks([C('系统部署成功'), C('  系统部署成功  '), C('系统\n部署成功')]);
  check(r.chunks.length === 1, '仅空白/换行不同 → 合并为一块', `实际 ${r.chunks.length}`);
  check(r.removed === 2, 'removed=2', `实际 ${r.removed}`);
}

console.log('\n[3] 不同内容绝不能合并（误合并是重罪）');
{
  const r = dedupeChunks([
    C('规则 227：无线断站级别重定义 → P2'),
    C('规则 227：无线断站级别重定义 → P3'),
    C('规则 228：无线断站级别重定义 → P2'),
  ]);
  check(r.chunks.length === 3, '一字之差视为不同块，全部保留', `实际 ${r.chunks.length}`);
  check(r.removed === 0, 'removed=0');
}

console.log('\n[4] 空/极短块不被误删');
{
  const r = dedupeChunks([C('甲'), C(''), C('甲')]);
  check(r.chunks.length === 2, '空串自成一块且不与他块合并', `实际 ${r.chunks.length}`);
  const r2 = dedupeChunks([C('x'), C('x'), C('y')]);
  check(r2.chunks.length === 2, '极短块同样按内容去重', `实际 ${r2.chunks.length}`);
}

console.log('\n[5] 边界');
{
  check(dedupeChunks([]).chunks.length === 0, '空输入 → 空输出');
  check(dedupeChunks([]).removed === 0, '空输入 removed=0');
  const all = [C('同'), C('同'), C('同'), C('同')];
  const r = dedupeChunks(all);
  check(r.chunks.length === 1 && r.removed === 3, '全重复 → 只剩 1 块', `${r.chunks.length}/${r.removed}`);
}

console.log('\n[6] 跨文档重复：保留首现，并记录 alsoIn');
{
  const r = dedupeChunks([C('同一段样板', 'x.md'), C('同一段样板', 'y.md')]);
  check(r.chunks.length === 1, '跨文档重复也合并', `实际 ${r.chunks.length}`);
  check(
    Array.isArray(r.chunks[0].alsoIn) && r.chunks[0].alsoIn.includes('y.md'),
    'alsoIn 记录了被合并的出处',
    JSON.stringify(r.chunks[0].alsoIn)
  );
  check(r.chunks[0].source === 'x.md', '保留的是首个出现的 source');
}

/* ---------------------------- 真实语料形态 ---------------------------- */

console.log('\n[7] 真实语料：线上索引里确实存在纯重复块');
{
  // 直接用线上索引（若存在）验证：重复块必须被消除。
  // 这不是人造 fixture —— 它是问题被发现时的真实数据形态。
  const { readFileSync, existsSync } = await import('node:fs');
  const { resolve } = await import('node:path');
  const p = resolve(process.cwd(), 'data', 'index.json');
  if (!existsSync(p)) {
    console.log('    （跳过：data/index.json 不存在）');
  } else {
    const ix = JSON.parse(readFileSync(p, 'utf8'));
    const r = dedupeChunks(ix.chunks);
    console.log(`    线上索引 ${ix.chunks.length} 块 → 去重后 ${r.chunks.length}（移除 ${r.removed}）`);
    check(r.chunks.length <= ix.chunks.length, '去重后块数不增加');
    const keys = r.chunks.map((c) => c.text.replace(/\s+/g, ''));
    check(new Set(keys).size === keys.length, '去重后确实无任何重复块');
  }
}

console.log('\n[7b] 同一段文本原样重复（去重的下限保证）');
{
  const boiler = 'Prerequisite - The system is deployed successfully.- You can log in to the system properly.';
  const parts = [boiler, boiler, boiler, '另一段不同的内容。'];
  const r = dedupeChunks(parts.map((t, i) => C(t, 'guide.md', i)));
  check(r.chunks.length === 2, '3 份完全相同 → 只留 1 份 + 另 1 段', `实际 ${r.chunks.length}`);
  check(r.removed === 2, 'removed=2', `实际 ${r.removed}`);
}

console.log('\n[8] 去重不损失"不同规则的并列条目"');
{
  // 规则表里大量「告警码 X → 父告警码 Y」结构高度相似，但都是独立知识
  const rows = Array.from({ length: 20 }, (_, i) => `告警码 ${1000 + i} 会被压缩成父告警码 ${9000 + i}`);
  const r = dedupeChunks(rows.map((t, i) => C(t, 'rules.md', i)));
  check(r.chunks.length === 20, '20 条不同规则一条不少', `实际 ${r.chunks.length}`);
  check(r.removed === 0, '相似但不同的规则不被误合并');
}

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
