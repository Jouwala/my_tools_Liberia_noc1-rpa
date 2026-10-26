#!/usr/bin/env node
/**
 * 问答记录（src/qalog.js）离线测试 —— 用临时库，不碰真实数据。
 *
 * 重点验证三件事：
 *   ① 记录写进去了、能查出来（否则这份资产等于不存在）；
 *   ② **答不上的也要记** —— 库里只剩正确答案的话，优化就无从下手；
 *   ③ 库坏了/写不进去时，**不能把回复本身拖垮**（记录是旁路）。
 */
import { DatabaseSync } from 'node:sqlite';
import { existsSync, rmSync, chmodSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TMP = join(ROOT, 'TMP');
const DB = join(TMP, '_test_qalog.sqlite');

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

/** 每次用全新库，避免上次残留影响断言。 */
function freshDb() {
  for (const f of [DB, `${DB}-wal`, `${DB}-shm`]) {
    if (existsSync(f)) rmSync(f, { force: true });
  }
  return DB;
}

const { openQaLog, recordQa, closeQaLog, qaLogState } = await import('../src/qalog.js');

console.log('\n[1] 建库与写入');
freshDb();
check(openQaLog(DB) === true, '打开成功');
check(qaLogState().ready === true, '状态为可用');

const okWrite = recordQa({
  ts: '2026-10-07T10:52:06.000Z',
  chatJid: '120363428304591700@g.us',
  sender: '112176710811648',
  question: '本月有几个P1的单子，请输出TT单的ID给我',
  answer: '2026-10-01 ~ 2026-10-07 P1 单 6 个\n单号：TT202610020012（LBS）［未闭环］',
  answered: true,
  channel: 'stats',
  tool: 'query_tickets',
  via: 'rule',
  ms: 241,
  lang: 'zh',
});
check(okWrite === true, '写入成功');

console.log('\n[2] 内容完整（回答正文必须落盘）');
closeQaLog();
{
  const db = new DatabaseSync(DB, { readOnly: true });
  const r = db.prepare('SELECT * FROM qa_log ORDER BY id LIMIT 1').get();
  check(r?.question?.includes('本月有几个P1'), '提问原文完整');
  // 这条是本次改动的**核心**：以前只记「命中=true」，答了什么完全没留
  check(r?.answer?.includes('TT202610020012'), '**回答正文已落盘**', JSON.stringify(r?.answer));
  check(r?.answered === 1, '命中标记正确');
  check(r?.channel === 'stats' && r?.tool === 'query_tickets', '通道/工具已记');
  check(r?.via === 'rule', '路由来源已记');
  check(r?.ms === 241, '耗时已记');
  check(r?.sender === '112176710811648', '按约定存真实号码');
  db.close();
}

console.log('\n[3] 答不上的也要记（优化样本）');
freshDb();
openQaLog(DB);
recordQa({
  ts: '2026-10-07T10:40:10.000Z',
  chatJid: 'g@g.us',
  sender: '231',
  question: '那个单子未闭环',
  answer: '资料未包含未解决工单终止验证…',
  answered: false,
  channel: 'kb',
  via: 'model',
  ms: 32560,
  lang: 'zh',
});
closeQaLog();
{
  const db = new DatabaseSync(DB, { readOnly: true });
  const n = db.prepare('SELECT COUNT(*) n FROM qa_log WHERE answered = 0').get().n;
  check(n === 1, '未命中的记录保留在库里');
  // 聚合口径：正是当时排查最需要、却拿不到的那个视图
  const byChannel = db
    .prepare('SELECT channel, COUNT(*) n, SUM(answered) ok FROM qa_log GROUP BY channel')
    .all();
  check(byChannel.length === 1 && byChannel[0].channel === 'kb', '可按通道聚合', JSON.stringify(byChannel));
  db.close();
}

console.log('\n[4] 记录是旁路：写不进去也不能拖垮回复');
freshDb();
openQaLog(DB);
closeQaLog();
// 关库之后再写 —— 模拟记录不可用
let threw = false;
let wrote = true;
try {
  wrote = recordQa({ question: 'x', answer: 'y' });
} catch {
  threw = true;
}
check(threw === false, '**写不进去也不抛异常**（不能连累回复）');
check(wrote === false, '  返回 false 如实告知没写成');

console.log('\n[4b] 旧库兼容：ALTER 补列（库已在线上跑过，不能重建）');
{
  // 造一个**旧 SCHEMA**的库：只有 12 列，没有 top_base/gap/hit_source/route_args。
  freshDb();
  {
    const legacy = new DatabaseSync(DB);
    legacy.exec(`CREATE TABLE qa_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL, chat_jid TEXT NOT NULL, sender TEXT NOT NULL,
      question TEXT NOT NULL, answer TEXT NOT NULL, answered INTEGER NOT NULL,
      channel TEXT, tool TEXT, via TEXT, ms INTEGER, lang TEXT, degraded INTEGER
    );`);
    legacy.prepare(
      `INSERT INTO qa_log (ts,chat_jid,sender,question,answer,answered,channel)
       VALUES ('2026-10-06T00:00:00.000Z','g@g.us','1','旧记录','旧答案',1,'kb')`
    ).run();
    legacy.close();
  }

  // 打开时应自动补列，且**不丢旧记录**
  const ok = openQaLog(DB);
  check(ok === true, '旧库能打开');
  {
    const probe = new DatabaseSync(DB, { readOnly: true });
    const cols = probe.prepare('PRAGMA table_info(qa_log)').all().map((c) => c.name);
    check(
      ['top_base', 'gap', 'hit_source', 'route_args', 'ack'].every((c) => cols.includes(c)),
      '缺列已补齐',
      JSON.stringify(cols)
    );
    check(probe.prepare('SELECT COUNT(*) n FROM qa_log').get().n === 1, '**旧记录没被清空**');
    probe.close();
  }

  // 迁移后写入带新字段的记录，能读回来
  const wrote = recordQa({
    ts: '2026-10-07T10:52:06.000Z',
    chatJid: 'g@g.us',
    sender: '1',
    question: '为什么TT没有级别',
    answer: '级别来自 ttLevelRule…',
    answered: true,
    channel: 'kb',
    tool: 'search_knowledge',
    via: 'model',
    ms: 1200,
    lang: 'zh',
    topBase: 0.5123,
    gap: 0.1611,
    hitSource: 'knowledge/08_级别缺失与排查.md|knowledge/03_TT级别规则.md',
    routeArgs: '{"severity":"P1"}',
  });
  check(wrote === true, '迁移后写入成功');
  closeQaLog();
  {
    const probe = new DatabaseSync(DB, { readOnly: true });
    const r = probe.prepare('SELECT * FROM qa_log ORDER BY id DESC LIMIT 1').get();
    check(Math.abs(r.top_base - 0.5123) < 1e-9, 'top_base 落盘正确', `${r.top_base}`);
    check(Math.abs(r.gap - 0.1611) < 1e-9, 'gap 落盘正确', `${r.gap}`);
    check(r.hit_source.includes('08_'), 'hit_source 落盘正确', JSON.stringify(r.hit_source));
    check(r.route_args === '{"severity":"P1"}', 'route_args 落盘正确', JSON.stringify(r.route_args));
    probe.close();
  }

  // 缺新字段时写 null，不能因缺字段而写失败
  freshDb();
  openQaLog(DB);
  const wroteMin = recordQa({ question: 'q', answer: 'a', answered: false, channel: 'kb' });
  check(wroteMin === true, '缺新字段也能写（当 null）');
  closeQaLog();
  {
    const probe = new DatabaseSync(DB, { readOnly: true });
    const r = probe.prepare('SELECT top_base, gap, hit_source, route_args, ack FROM qa_log ORDER BY id DESC LIMIT 1').get();
    check(r.top_base === null && r.gap === null && r.hit_source === null && r.route_args === null && r.ack === null, '  新列全为 null', JSON.stringify(r));
    probe.close();
  }
}

console.log('\n[4c] 送达状态：undelivered 可与正常回答区分（2026-10-26 事故）');
{
  freshDb();
  openQaLog(DB);
  // 模拟「查询成功但没送达」：answered=1，但 ack='undelivered'
  recordQa({
    ts: '2026-10-26T10:50:56.000Z',
    chatJid: 'olr@g.us',
    sender: '1',
    question: 'TEL 231773777115',
    answer: 'XDR CCA: …',
    answered: true,
    channel: 'vmaxcca',
    tool: 'query_vmax_cca',
    via: 'rule',
    ms: 4141,
    lang: 'en',
    ack: 'undelivered',
  });
  recordQa({
    ts: '2026-10-26T11:35:34.000Z',
    chatJid: 'olr@g.us',
    sender: '1',
    question: 'TEL 231773777115',
    answer: 'XDR CCA: …',
    answered: true,
    channel: 'vmaxcca',
    tool: 'query_vmax_cca',
    via: 'rule',
    ms: 5101,
    lang: 'en',
    ack: 'delivered',
  });
  closeQaLog();
  {
    const probe = new DatabaseSync(DB, { readOnly: true });
    const und = probe.prepare("SELECT COUNT(*) n FROM qa_log WHERE ack='undelivered'").get().n;
    const del = probe.prepare("SELECT COUNT(*) n FROM qa_log WHERE ack='delivered'").get().n;
    check(und === 1, '未送达记录可单独筛出', `undelivered=${und}`);
    check(del === 1, '已送达记录可单独筛出', `delivered=${del}`);
    // 关键：两条 answered 都是 1（查询确实成功了），靠 ack 列区分送达与否
    const both = probe.prepare('SELECT COUNT(*) n FROM qa_log WHERE answered=1').get().n;
    check(both === 2, '查询成功与否与送达与否是两个独立维度', `answered=1 共 ${both}`);
    probe.close();
  }
}

console.log('\n[5] 库路径不可用时不影响启动');
const bad = await (async () => {
  // 指向一个不可能建成的路径（把文件当目录用）
  const p = join(DB, 'nested', 'x.sqlite');
  return openQaLog(p);
})();
check(bad === false, '打不开时返回 false，不抛');
check(qaLogState().broken === true, '  标记为 broken，不再每轮重试');

// 清理
for (const f of [DB, `${DB}-wal`, `${DB}-shm`]) {
  if (existsSync(f)) rmSync(f, { force: true });
}

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
