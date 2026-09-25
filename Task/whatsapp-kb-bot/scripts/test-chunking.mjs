#!/usr/bin/env node
/**
 * 分块器回归测试。
 *   node scripts/test-chunking.mjs
 *
 * 核心不变量：**任何输入下，每一块的长度都必须 ≤ chunkSize。**
 * 这条曾经被打破——无句末标点的长文本（长列表、代码块、无标点中文）
 * 会原样成块，实测 5000 字符变成一块，严重稀释检索精度。
 */
import { chunkText } from '../src/rag.js';

const SIZE = 420;
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

/** 不变量：所有块非空且不超过 SIZE */
function assertBounded(label, text, opts = {}) {
  const chunks = chunkText(text, { size: SIZE, overlap: 80, ...opts });
  const lens = chunks.map((c) => c.length);
  const max = lens.length ? Math.max(...lens) : 0;
  const empty = chunks.filter((c) => !c.trim()).length;
  console.log(`\n${label}`);
  console.log(`    块数 ${chunks.length}｜最大长度 ${max}｜长度分布 ${JSON.stringify(lens.slice(0, 12))}${lens.length > 12 ? '…' : ''}`);
  check(max <= SIZE, `所有块 ≤ ${SIZE}`, max > SIZE ? `最大块 ${max} 超限 ${max - SIZE}` : '');
  check(empty === 0, '无空块', empty ? `有 ${empty} 个空块` : '');
  return chunks;
}

console.log('='.repeat(50));
console.log(`分块器回归测试（chunkSize=${SIZE}）`);
console.log('='.repeat(50));

/* ------------------------------- 基本情形 ------------------------------- */

console.log('\n--- 基本情形 ---');
check(chunkText('').length === 0, '空字符串 → 0 块');
check(chunkText('   \n\n  \t ').length === 0, '纯空白 → 0 块');
check(chunkText('短句。').length === 1, '单个短句 → 1 块');
check(chunkText('短句。', { size: 420 })[0] === '短句。', '内容原样保留');

/* ---------------------------- 超长文本兜底 ---------------------------- */

assertBounded('[1] 5000 字无标点中文段落', '甲'.repeat(5000));
assertBounded('[2] 6000 字符英文无标点', 'word '.repeat(1200));
assertBounded('[3] 100 行单换行文本（无空行分隔）', Array.from({ length: 100 }, (_, i) => `第${i + 1}行内容`).join('\n'));
assertBounded('[4] 单行超长 JSON', JSON.stringify({ data: Array.from({ length: 400 }, (_, i) => ({ id: i, name: `item-${i}` })) }));
assertBounded('[5] 无空行代码块', Array.from({ length: 200 }, (_, i) => `const value${i} = compute(${i});`).join('\n'));
assertBounded('[6] 混合：短段 + 超长无标点段', `短段落一。\n\n${'乙'.repeat(2000)}\n\n短段落二。`);

/* ---------------------------- 正常语料回归 ---------------------------- */

const normal = `# 标题

## 年假与休假

员工每年享有带薪年假 15 天，入职满一年后开始计算，按自然年度使用，未休完的部分最多结转 5 天到次年 3 月 31 日。

病假需在当天上班前通过 OA 提交申请，连续 3 天以上的病假需附二级以上医院开具的证明。

## 报销流程

差旅报销需在出差结束后 15 个工作日内提交，逾期需附书面说明并由部门负责人签字。

报销单必须附发票原件扫描件；单张金额超过 5000 元的，需额外提供审批邮件截图。`;

const chunks = assertBounded('[7] 真实语料结构', normal);

/* ------------------------------ 覆盖率 ------------------------------ */

console.log('\n--- 覆盖率（overlap=0 时应无损）---');
const noOverlap = chunkText(normal, { size: SIZE, overlap: 0 });
const norm = (s) => s.replace(/\s+/g, '');
const joined = norm(noOverlap.join(''));
const original = norm(normal);
check(
  joined === original,
  'overlap=0 时拼接结果与原文一致（无内容丢失/重复）',
  joined === original ? '' : `原文 ${original.length} 字符，拼接 ${joined.length} 字符`
);

// overlap=0 的重叠 bug 回归：曾经 slice(-0) 返回整串，导致内容翻倍
check(
  joined.length <= original.length + 5,
  'overlap=0 不产生重复内容（slice(-0) 回归）',
  `拼接后 ${joined.length} vs 原文 ${original.length}`
);

/* ------------------------------ 重叠行为 ------------------------------ */

console.log('\n--- 重叠行为 ---');
const withOverlap = chunkText('丙'.repeat(1000), { size: 300, overlap: 60 });
check(withOverlap.length > 1, '长文本确实被切成多块');
check(
  withOverlap.every((c) => c.length <= 300),
  '带重叠时仍不超过 size'
);
const joinedOverlap = norm(withOverlap.join(''));
check(joinedOverlap.length >= 1000, '带重叠时内容只增不减（重叠生效）');

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
