#!/usr/bin/env node
/**
 * 索引新鲜度检测单测（**纯离线**，不读真实索引、不联网）。
 *   node scripts/test-index-freshness.mjs
 *
 * 覆盖这次改造要解决的核心故障：
 *   `knowledge/08_级别缺失与排查.md` 已在磁盘，但索引 meta.sources 里没有它
 *   —— 于是现场高频问「为什么没有级别」一直答「资料没有」。
 *   检索调参救不了没有的内容，必须让「磁盘知识 ≠ 内存索引」这件事**可见**。
 *
 * 最要紧的两条不变量：
 *   ① 缺文件 → ok=false 且 missingInIndex 点名该文件；
 *   ② 过期**不抛异常**（索引过期是质量问题，不该让进程起不来 / ping 挂掉）。
 */
import { scanKnowledge, diffIndex, freshnessWarning } from '../src/indexFreshness.js';
import { existsSync, mkdirSync, writeFileSync, rmSync, utimesSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TMP = join(ROOT, 'TMP', '_test_freshness');

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
console.log('索引新鲜度测试（离线）');
console.log('='.repeat(50));

/* ------------------------------ 真实目录扫描 ------------------------------ */

console.log('\n[1] scanKnowledge 扫描真实 knowledge/');
{
  const scan = scanKnowledge(join(ROOT, 'knowledge'), ROOT);
  check(Array.isArray(scan) && scan.length >= 1, '扫到至少一个知识文件', `n=${scan.length}`);
  check(scan.every((f) => typeof f.rel === 'string' && f.rel.startsWith('knowledge/')), '相对路径以 knowledge/ 开头');
  check(scan.every((f) => Number.isFinite(f.size) && Number.isFinite(f.mtimeMs)), '都带 size 与 mtimeMs');
  const has08 = scan.some((f) => f.rel.includes('08_'));
  check(has08, '磁盘上确实有 08_（现场「为什么没级别」问的就是它）');
  check(scanKnowledge(join(ROOT, 'no-such-dir'), ROOT).length === 0, '目录不存在返回空数组（不抛）');
}

/* ------------------------------ 构造假 meta ------------------------------ */

console.log('\n[2] diffIndex：集合对比');
{
  const scan = [
    { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
    { rel: 'knowledge/b.md', size: 200, mtimeMs: 2000 },
  ];

  // 集合完全一致、且磁盘 mtime 都不晚于索引记录
  const metaOk = {
    builtAt: '2026-10-07T00:00:00.000Z',
    knowledgeFiles: [
      { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
      { rel: 'knowledge/b.md', size: 200, mtimeMs: 2000 },
    ],
  };
  const okDiff = diffIndex(metaOk, scan);
  check(okDiff.ok === true, '一致 → ok=true', JSON.stringify(okDiff));
  check(freshnessWarning(okDiff) === null, '  新鲜时不产生警告');

  // 磁盘多一个文件（正是 08_ 场景）
  const metaMissing = {
    builtAt: '2026-10-07T00:00:00.000Z',
    knowledgeFiles: [{ rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 }],
  };
  const missDiff = diffIndex(metaMissing, scan);
  check(missDiff.ok === false, '缺文件 → ok=false');
  check(missDiff.missingInIndex.includes('knowledge/b.md'), '  missingInIndex 点名缺的文件', JSON.stringify(missDiff));
  check(/b\.md/.test(freshnessWarning(missDiff) || ''), '  警告里带文件名');

  // 索引有、磁盘没有（文件被删/改名）
  const metaExtra = {
    builtAt: '2026-10-07T00:00:00.000Z',
    knowledgeFiles: [
      { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
      { rel: 'knowledge/b.md', size: 200, mtimeMs: 2000 },
      { rel: 'knowledge/gone.md', size: 5, mtimeMs: 500 },
    ],
  };
  const extraDiff = diffIndex(metaExtra, scan);
  check(extraDiff.ok === false && extraDiff.extraInIndex.includes('knowledge/gone.md'), '索引有磁盘没有 → extraInIndex', JSON.stringify(extraDiff));

  // 同名文件被改过（mtime 更新）
  const metaStale = {
    builtAt: '2026-10-07T00:00:00.000Z',
    knowledgeFiles: [
      { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
      { rel: 'knowledge/b.md', size: 200, mtimeMs: 2000 },
    ],
  };
  const modified = [
    { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
    { rel: 'knowledge/b.md', size: 999, mtimeMs: 9000 },
  ];
  const mDiff = diffIndex(metaStale, modified);
  check(mDiff.ok === false && mDiff.newerOnDisk.includes('knowledge/b.md'), '文件被改过 → newerOnDisk', JSON.stringify(mDiff));
}

console.log('\n[3] 兼容旧索引（只有 sources，没有 knowledgeFiles）');
{
  const scan = [
    { rel: 'knowledge/a.md', size: 100, mtimeMs: 1000 },
    { rel: 'knowledge/b.md', size: 200, mtimeMs: 2000 },
  ];
  // 老索引没有 mtime，只能比集合：缺文件仍能发现
  const oldMeta = { builtAt: '2026-10-07T00:00:00.000Z', sources: ['knowledge/a.md', 'knowledge/b.md'] };
  const d1 = diffIndex(oldMeta, scan);
  check(d1.ok === true, '集合一致 → ok=true（无法判断内容是否变过）', JSON.stringify(d1));
  check(d1.unknownMtime === true, '  标记 unknownMtime');

  const oldMissing = { builtAt: '2026-10-07T00:00:00.000Z', sources: ['knowledge/a.md'] };
  const d2 = diffIndex(oldMissing, scan);
  check(d2.ok === false && d2.missingInIndex.includes('knowledge/b.md'), '旧索引仍能发现缺文件', JSON.stringify(d2));
}

console.log('\n[4] 过期不抛异常（与 Ollama 自检同一取舍）');
{
  let threw = false;
  let r;
  try {
    r = diffIndex(undefined, []);
    freshnessWarning(r);
    diffIndex({ builtAt: 'x' }, undefined);
    diffIndex(null, null);
    freshnessWarning(null);
    freshnessWarning(undefined);
  } catch (e) {
    threw = true;
    console.log(`      异常：${e.message}`);
  }
  check(threw === false, '**meta/scan 各种空值都不抛**');
  check(r && r.ok === true, '全空 → ok=true（没有可抱怨的）');
}

console.log('\n[5] scanKnowledge 用临时目录（真实 stat）');
{
  const cleanup = (dir) => {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      /* 网络盘上偶发 EPERM；测试结束不影响，下次会覆盖 */
    }
  };
  cleanup(TMP);
  mkdirSync(TMP, { recursive: true });
  writeFileSync(join(TMP, 'a.md'), '# A\nhello', 'utf8');
  writeFileSync(join(TMP, 'b.txt'), 'world', 'utf8');
  writeFileSync(join(TMP, 'skip.bin'), 'x', 'utf8');
  mkdirSync(join(TMP, '.hidden'), { recursive: true });
  writeFileSync(join(TMP, '.hidden', 'c.md'), 'x', 'utf8');

  const scan = scanKnowledge(TMP, TMP);
  const rels = scan.map((f) => f.rel).sort();
  check(rels.includes('a.md') && rels.includes('b.txt'), '扫到 .md 与 .txt', JSON.stringify(rels));
  check(!rels.includes('skip.bin'), '过滤掉非文档扩展名');
  check(!rels.some((r) => r.includes('.hidden')), '跳过点开头的目录');
  check(scan.find((f) => f.rel === 'a.md').size > 0, 'size 为正', `${scan.find((f) => f.rel === 'a.md')?.size}`);

  // 改 mtime 后能发现
  const later = Math.floor(Date.now() / 1000) + 100;
  utimesSync(join(TMP, 'a.md'), later, later);
  const scan2 = scanKnowledge(TMP, TMP);
  const meta = { builtAt: new Date().toISOString(), knowledgeFiles: scan.map((f) => ({ ...f })) };
  const d = diffIndex(meta, scan2);
  check(d.ok === false && d.newerOnDisk.includes('a.md'), '改 mtime 后 diff 能发现', JSON.stringify(d));

  cleanup(TMP);
}

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
