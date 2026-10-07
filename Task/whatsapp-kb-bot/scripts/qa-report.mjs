#!/usr/bin/env node
/**
 * 问答记录查看/分析 —— 读 data/qa.sqlite。
 *
 * 用法：
 *   node scripts/qa-report.mjs                 # 概览：总量、命中率、通道分布
 *   node scripts/qa-report.mjs --miss          # 只看没答上的（**优化从这里入手**）
 *   node scripts/qa-report.mjs --slow          # 只看慢的（>5s）
 *   node scripts/qa-report.mjs --search 单号    # 按关键词找历史提问
 *   node scripts/qa-report.mjs --days 3        # 只看最近 3 天
 *   node scripts/qa-report.mjs --sql "..."     # 自定义 SQL（只读）
 *
 * ## 为什么单独一个脚本，而不是让人直接开 sqlite3
 *
 * 这份记录的用途是**优化**，优化的第一步是看清"哪类问题在失败"。
 * 每次都手写 GROUP BY 既慢又容易口径不一致（比如漏掉 answered=0 那批），
 * 所以把常用视角固定下来，口径只有一份。
 *
 * ## 为什么默认只读
 *
 * 记录是**证据**，被随手 UPDATE/DELETE 掉就失去了复盘价值。
 * `--sql` 只放行 SELECT / WITH，其余一律拒绝。
 */
import { DatabaseSync } from 'node:sqlite';
import { existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DB = process.env.QA_LOG_PATH || resolve(ROOT, 'data/qa.sqlite');

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const val = (f, d) => {
  const i = argv.indexOf(f);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
};

if (!existsSync(DB)) {
  console.error(`还没有问答记录：${DB}`);
  console.error('机器人跑起来并回答过问题后会自动创建。');
  process.exit(1);
}

const db = new DatabaseSync(DB, { readOnly: true });

/** 最近 N 天的过滤片段（默认全部）。 */
const days = Number(val('--days', 0));
const since = days > 0 ? new Date(Date.now() - days * 86400_000).toISOString() : null;
const where = since ? `WHERE ts >= '${since}'` : '';

const pct = (a, b) => (b ? `${((a / b) * 100).toFixed(1)}%` : '—');
const bar = (n, total, width = 20) =>
  '█'.repeat(total ? Math.max(1, Math.round((n / total) * width)) : 0);

/** 列宽自适应（中文按 2 宽算，否则表格会错位）。 */
const w = (s) => [...String(s ?? '')].reduce((a, c) => a + (/[\u4e00-\u9fff]/.test(c) ? 2 : 1), 0);
const pad = (s, n) => String(s ?? '') + ' '.repeat(Math.max(0, n - w(s)));

if (has('--sql')) {
  const sql = val('--sql', '');
  // 只读护栏：记录是证据，不允许被这个脚本改写
  if (!/^\s*(select|with)\b/i.test(sql)) {
    console.error('只允许 SELECT / WITH 查询。');
    process.exit(1);
  }
  for (const r of db.prepare(sql).all()) console.log(JSON.stringify(r, null, 2));
  process.exit(0);
}

if (has('--miss')) {
  const rows = db
    .prepare(
      `SELECT ts, question, answer, channel, tool, via, ms, top_base, gap, hit_source, route_args
       FROM qa_log
       ${where ? where + ' AND' : 'WHERE'} answered = 0
       ORDER BY ts DESC LIMIT 50`
    )
    .all();
  console.log(`\n没答上的（最近 ${rows.length} 条）—— **优化从这批入手**\n`);
  if (!rows.length) console.log('  没有。');
  for (const r of rows) {
    // 用 | 拼「通道/工具/路由」——一行看清它**实际**走的是哪条路，
    // 这是回答「为什么这条答错了」的第一步（以前只有 channel 一列）。
    const route = [r.channel || '(无通道)', r.tool || '-', r.via ? `路由=${r.via}` : '']
      .filter(Boolean)
      .join(' | ');
    console.log(`  ${r.ts.slice(0, 19).replace('T', ' ')}  ${route}  ${r.ms ?? '?'}ms`);
    console.log(`    问：${String(r.question).slice(0, 120)}`);
    console.log(`    答：${String(r.answer).replace(/\n/g, ' ').slice(0, 120)}`);
    // 检索诊断：分数与 top1 命中来源（统计/查表通道这两列为空，属正常）
    if (r.top_base != null || r.hit_source || r.gap != null) {
      const score = [
        r.top_base != null ? `top=${Number(r.top_base).toFixed(3)}` : '',
        r.gap != null ? `gap=${Number(r.gap).toFixed(3)}` : '',
      ]
        .filter(Boolean)
        .join(' ');
      console.log(`    检索：${score || '-'}${r.hit_source ? `  命中来源：${r.hit_source}` : ''}`);
    }
    if (r.route_args) console.log(`    参数：${String(r.route_args).slice(0, 160)}`);
    console.log('');
  }
  process.exit(0);
}

if (has('--slow')) {
  const rows = db
    .prepare(
      `SELECT ts, question, channel, tool, via, ms FROM qa_log
       ${where ? where + ' AND' : 'WHERE'} ms > 5000
       ORDER BY ms DESC LIMIT 30`
    )
    .all();
  console.log(`\n慢查询（>5s，最近 ${rows.length} 条）\n`);
  if (!rows.length) console.log('  没有。');
  for (const r of rows) {
    console.log(
      `  ${String(r.ms).padStart(6)}ms  ${pad(r.channel || '-', 8)}${pad(r.tool || '-', 18)}${pad(r.via || '-', 7)}` +
        String(r.question).slice(0, 60)
    );
  }
  console.log('');
  process.exit(0);
}

if (has('--search')) {
  const kw = `%${val('--search', '')}%`;
  const rows = db
    .prepare(
      `SELECT ts, question, answer, answered, channel, tool, ms FROM qa_log
       WHERE (question LIKE ? OR answer LIKE ?)
       ORDER BY ts DESC LIMIT 30`
    )
    .all(kw, kw);
  console.log(`\n匹配「${val('--search', '')}」的 ${rows.length} 条\n`);
  for (const r of rows) {
    console.log(`  ${r.ts.slice(0, 19).replace('T', ' ')}  ${r.answered ? '✓' : '✗'}  ${r.channel || '-'}  ${r.ms ?? '?'}ms`);
    console.log(`    问：${String(r.question).slice(0, 120)}`);
    console.log(`    答：${String(r.answer).replace(/\n/g, ' ').slice(0, 120)}`);
    console.log('');
  }
  process.exit(0);
}

/* ------------------------------ 默认概览 ------------------------------ */

const total = db.prepare(`SELECT COUNT(*) n, SUM(answered) ok FROM qa_log ${where}`).get();
console.log(`\n问答记录概览${days ? `（最近 ${days} 天）` : '（全部）'}`);
console.log(`  库：${DB}`);
if (total.n) {
  const first = db.prepare(`SELECT MIN(ts) a, MAX(ts) b FROM qa_log ${where}`).get();
  console.log(`  区间：${first.a?.slice(0, 19)} ~ ${first.b?.slice(0, 19)}`);
}
console.log(`\n  总数 ${total.n ?? 0}｜答上 ${total.ok ?? 0}｜命中率 ${pct(total.ok ?? 0, total.n ?? 1)}\n`);

for (const r of db
  .prepare(
    `SELECT channel, COUNT(*) n, SUM(answered) ok, AVG(ms) avg_ms
     FROM qa_log ${where} GROUP BY channel ORDER BY n DESC`
  )
  .all()) {
  console.log(
    `  ${pad(r.channel || '(无)', 10)}${bar(r.n, total.n)} ${String(r.n).padStart(5)} 条  ` +
      `命中 ${pct(r.ok ?? 0, r.n)}  平均 ${Math.round(r.avg_ms ?? 0)}ms`
  );
}

const via = db
  .prepare(`SELECT via, COUNT(*) n, SUM(answered) ok FROM qa_log ${where} GROUP BY via`)
  .all();
if (via.length) {
  console.log('');
  for (const r of via) {
    console.log(`  路由=${pad(r.via || '(无)', 8)}${String(r.n).padStart(5)} 条  命中 ${pct(r.ok ?? 0, r.n)}`);
  }
}

console.log(`\n  看没答上的：node scripts/qa-report.mjs --miss`);
console.log(`  看慢的：    node scripts/qa-report.mjs --slow\n`);
