#!/usr/bin/env node
/**
 * 单号分析「HTTP 优先」通道测试（Node 侧）。
 *   node scripts/test-tt-analysis-http.mjs
 *
 * 背景（2026-10-15）：单号分析原先只读本地 SQLite 副本，副本每 12 小时才刷一次，
 * 导致 PG 里已更新/恢复的数据机器人最坏要等 12 小时才看见。改造后 analyzeTt
 * **先请求 my_app 的 PG 实时接口**（/api/tt-wo-dashboard/tt/{tt_no} 与 /wo/{wo_no}），
 * 命中即用；失败/未配置则降级到本地库（本套件用不到那条，见 test-tt-live-route.mjs）。
 *
 * 本套件只测**这条新通道的编排**，桩法：
 *   · 起一个**真的本地 HTTP 服务**模拟 my_app 的两个接口（不起真后端）；
 *   · 同 test-tt-live-route.mjs，用桩「python.exe」模拟 tt-analyze.py 的渲染步骤，
 *     把经 stdin 收到的 live-row 信封回显出来，供断言检查。
 *
 * 覆盖：
 *   ① PG 命中 → 走信封注入，且**不碰本地副本**。
 *   ② PG found:false + 实时不可用 → 落到本地副本（带「可能滞后」语义）。
 *   ③ PG 连不上 + 实时不可用 → 落到本地副本。
 *   ④ ttAnalysisHttp=false → 直接本地副本，**不发 HTTP、也不先绕 eFlow**。
 *   ⑤ 信封形状正确（{"row":...,"wo":...}）且 WO 行随之注入。
 *   ⑥ **PG found:false → eFlow 实时命中**，且**不读本地副本**（2026-10-28 新顺序）。
 *   ⑦ **PG 连不上 → eFlow 实时命中**，同样不读副本。
 *   ⑧ PG found:false + eFlow 明确「没这单」→ 直接给结论，不读副本（省一次全表扫描）。
 *   ⑨ PG 连不上 + 实时不可用 → 落到副本，且**必须打 [stale] 标记**。
 */
import { createServer } from 'node:http';
import { mkdtempSync, writeFileSync, copyFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

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

const TT_NO = 'TT202609290052';
const WO_NO = 'WO202609290077';

/** 一条最小可用的 TT 行（桩体只需几个字段，渲染由桩 python 回显）。 */
function ttRow() {
  return { tt_no: TT_NO, wo_no: WO_NO, site_name: 'Stub Site', status: 'WaitConfirm' };
}
function woRow() {
  return { wo_no: WO_NO, status: 'WaitProcess', creator: 'stub_creator' };
}

/**
 * 起一个模拟 my_app 的 HTTP 服务。mode:
 *   'hit'   → TT 命中，返回 {found:true,row}；WO 也命中
 *   'miss'  → 两个接口都返回 {found:false,row:{}}
 *   'down'  → 立即关闭/拒绝（用不存在的端口模拟，见下）
 * 返回 {url, requests, close}。requests 记录收到的路径，供断言「有没有发 HTTP」。
 */
function startStub(mode) {
  const requests = [];
  const server = createServer((req, res) => {
    requests.push(req.url);
    res.setHeader('content-type', 'application/json');
    if (mode === 'miss') return res.end(JSON.stringify({ found: false, row: {} }));
    const m = req.url.match(/\/api\/tt-wo-dashboard\/(tt|wo)\/([^/?]+)/);
    if (!m) return res.end(JSON.stringify({ found: false, row: {} }));
    if (m[1] === 'tt') return res.end(JSON.stringify({ found: true, row: ttRow() }));
    return res.end(JSON.stringify({ found: true, row: woRow() }));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        requests,
        close: () => new Promise((r) => server.close(r)),
      });
    });
  });
}

/**
 * 桩「python.exe」：经 NODE_OPTIONS --import 预加载（同 test-tt-live-route.mjs），
 * 按 tt.js 传给 python 的 argv 判定这次是哪种调用，并回显经 stdin 收到的信封。
 *
 * 为什么同步读 stdin：预加载模块在本进程启动阶段就跑，`stdin.on('end')` 那种
 * 异步写法会和 --import 的生命周期打架（实测报 `Node.js v24.16.0` 崩栈）。
 * 用 `readFileSync(0)`（fd 0）同步读完即可 —— tt.js 在启动子进程后立刻
 * `stdin.end(payload)`，数据已在管道里。
 *
 * argv 形如 [script, ttNo, --lang, zh, --live-row, -]。
 */
function makePyStub(dir, { foundLocal, live = 'off' }) {
  const stubJs = join(dir, 'pystub.mjs');
  writeFileSync(
    stubJs,
    `
import { readFileSync } from 'node:fs';
const argv = process.argv.slice(1);
const script = String(argv[0] || '').split('\\\\').join('/');

// ② eFlow 实时桥接（2026-10-28 起紧跟 PG）。
//   'hit'   → 吐一行 JSON（裸行，没有 row 信封）
//   'miss'  → 按脚本约定 exit 1（eFlow 也没有这一单）
//   'off'   → 模拟通道不可用（缺依赖 / 解释器探测失败）
if (script.endsWith('eflow-live-tt.py')) {
  if (argv.includes('--which')) {
    process.stdout.write('C:/fake/python.exe\\n');
    process.exit(0);
  }
  if (${JSON.stringify(live)} === 'hit') {
    process.stdout.write(JSON.stringify({ tt_no: 'TT202609290052', site_name: 'Live Site', status: 'WaitFOProcess' }));
    process.exit(0);
  }
  if (${JSON.stringify(live)} === 'miss') process.exit(1);
  process.exit(3);
}

if (!script.endsWith('tt-analyze.py')) process.exit(3);  // 本套件只桩这两个脚本

if (argv.includes('--live-row')) {
  let data = '';
  try { data = readFileSync(0, 'utf8'); } catch { data = ''; }
  process.stdout.write('LIVE_INJECTED|' + data.trim() + '\\n');
  process.exit(0);
}
// 无 live-row → 走的是**本地 SQLite 副本**。打 LOCAL_READ 标记，
// 供断言「该走实时的时候没有去读那份 12 小时前的副本」。
process.stdout.write('LOCAL_READ|');
process.stdout.write(${foundLocal ? "'LOCAL_FOUND\\n'" : "'Ticket not found in the ticket database.\\n'"});
process.exit(${foundLocal ? '0' : '1'});
`,
    'utf8'
  );
  const cmd = join(dir, 'python.exe');
  copyFileSync(process.execPath, cmd);
  return { cmd, stubJs };
}

async function loadTt(cmd, stubJs, apiBase, analysisHttp) {
  process.env.TT_PYTHON = cmd;
  process.env.TT_RETRY_DELAY_MS = '1';
  process.env.TT_TIMEOUT_MS = '5000';
  process.env.TT_LIVE_TIMEOUT_MS = '5000';
  process.env.MY_APP_API_BASE = apiBase;
  if (analysisHttp === '0') process.env.TT_ANALYSIS_HTTP = '0';
  else delete process.env.TT_ANALYSIS_HTTP;
  process.env.NODE_OPTIONS = `--import=${pathToFileURL(stubJs).href}`;
  const url = new URL('../src/tt.js', import.meta.url);
  url.searchParams.set('t', String(Date.now() + Math.random()));
  return import(url.href);
}

console.log('='.repeat(50));
console.log('单号分析 HTTP 优先通道测试（Node 侧）');
console.log('='.repeat(50));

/* ① HTTP 命中 → 信封注入，不碰本地库 */
{
  console.log('\n[1] HTTP 命中 → 走 --live-row 信封，不读本地库');
  const stub = await startStub('hit');
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: false });
  try {
    const tt = await loadTt(cmd, stubJs, stub.url, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en' });
    check(r.ok === true, '返回 ok=true', JSON.stringify(r));
    check(/LIVE_INJECTED/.test(r.text), '渲染走的是 --live-row 注入（桩回显）', r.text);
    const envRaw = (r.text.match(/LIVE_INJECTED\|(\{.*\})/) || [])[1] || '';
    let env = {};
    try { env = JSON.parse(envRaw); } catch { /* 下面断言会失败并给出原文 */ }
    check(env.row && env.row.tt_no === TT_NO, '信封含 row=TT 行', envRaw.slice(0, 120));
    check(env.wo && env.wo.wo_no === WO_NO, '信封含 wo=WO 行（时间轴两跳要用）', envRaw.slice(0, 120));
    check(stub.requests.some((u) => u.includes(`/tt/${TT_NO}`)), '请求了 /tt/{tt_no}');
    check(stub.requests.some((u) => u.includes(`/wo/${WO_NO}`)), '请求了 /wo/{wo_no}');
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
    await stub.close();
  }
}

/* ② PG found:false + 实时不可用 → 落到本地副本 */
{
  console.log('\n[2] PG found:false + 实时不可用 → 落到本地副本');
  const stub = await startStub('miss');
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: false, live: 'off' });
  try {
    const tt = await loadTt(cmd, stubJs, stub.url, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en' });
    check(!/LIVE_INJECTED/.test(r.text), '没有走 live 注入（本地路径）', r.text);
    check(/LOCAL_READ/.test(r.text), '确实读了本地副本', r.text);
    check(/not found in the ticket database/i.test(r.text) || r.ok === false,
      '给出本地副本「查无此单」结论', r.text);
    check(/eFlow/.test(r.text), '同时说明「实时没查成」（不假装实时确认过）', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
    await stub.close();
  }
}

/* ③ PG 连不上 + 实时不可用 → 落到本地副本 */
{
  console.log('\n[3] PG 连不上 + 实时不可用 → 落到本地副本');
  const stub = await startStub('hit');
  const deadUrl = stub.url;
  await stub.close(); // 端口关闭，模拟 my_app 没起
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: false, live: 'off' });
  try {
    const tt = await loadTt(cmd, stubJs, deadUrl, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en' });
    check(!/LIVE_INJECTED/.test(r.text), '没有走 live 注入（降级成功）', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
  }
}

/* ④ ttAnalysisHttp=false → 直接本地库，不发 HTTP */
{
  console.log('\n[4] ttAnalysisHttp=false → 不发 HTTP，直接本地库');
  const stub = await startStub('hit');
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true });
  try {
    const tt = await loadTt(cmd, stubJs, stub.url, '0');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en' });
    check(stub.requests.length === 0, '一个 HTTP 请求都没发', JSON.stringify(stub.requests));
    check(!/LIVE_INJECTED/.test(r.text), '没走 live 注入');
    check(/LOCAL_READ/.test(r.text), '直接读本地副本（老顺序）', r.text);
    check(!/\[stale\]/.test(r.text), '副本作为主路径时**不**打 [stale] 标记', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
    await stub.close();
  }
}

/* ⑤ PG found:false → eFlow 实时命中（副本不再插队） */
{
  console.log('\n[5] PG found:false → eFlow 实时命中，且不读本地副本');
  const stub = await startStub('miss');
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  // ⚠️ 副本里**有**这一单：若顺序回退成「副本优先」，这里会返回 LOCAL_FOUND，
  // 断言就会挂 —— 这是本条用例的关键设计，不是随手写的 true。
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true, live: 'hit' });
  try {
    const tt = await loadTt(cmd, stubJs, stub.url, 'on');
    const liveMsgs = [];
    const r = await tt.analyzeTt(TT_NO, { lang: 'en', onLive: (t) => liveMsgs.push(t) });
    check(r.ok === true, '返回 ok=true（实时拿到了数据）', r.text);
    check(/LIVE_INJECTED/.test(r.text), '走的是实时行注入', r.text);
    check(!/LOCAL_READ/.test(r.text), '**没有**读本地副本（旧数据不该插队）', r.text);
    const envRaw = (r.text.match(/LIVE_INJECTED\|(\{.*\})/) || [])[1] || '';
    let row = {};
    try { row = JSON.parse(envRaw); } catch { /* 下面的断言会给出原文 */ }
    check(row.tt_no === TT_NO && !row.row,
      '注入的是 eFlow 裸行（不是 PG 的 {"row":..} 信封）', envRaw.slice(0, 140));
    check(liveMsgs.length === 1 && /eFlow/.test(liveMsgs[0] || ''),
      '先垫了「去 eFlow 实时查」那句', JSON.stringify(liveMsgs));
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
    await stub.close();
  }
}

/* ⑥ PG 连不上 → eFlow 实时命中 */
{
  console.log('\n[6] PG 连不上 → eFlow 实时命中，不读本地副本');
  const stub = await startStub('hit');
  const deadUrl = stub.url;
  await stub.close();
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true, live: 'hit' });
  try {
    const tt = await loadTt(cmd, stubJs, deadUrl, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en', onLive: () => {} });
    check(r.ok === true, '返回 ok=true', r.text);
    check(/LIVE_INJECTED/.test(r.text), '走的是实时行注入', r.text);
    check(!/LOCAL_READ/.test(r.text), '**没有**读本地副本', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
  }
}

/* ⑦ PG found:false + eFlow 明确「没这单」→ 直接给结论 */
{
  console.log('\n[7] PG found:false + eFlow 明确「没这单」→ 直接给结论');
  const stub = await startStub('miss');
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true, live: 'miss' });
  try {
    const tt = await loadTt(cmd, stubJs, stub.url, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en', onLive: () => {} });
    check(r.ok === false, '返回 ok=false');
    check(/Neither the live database nor a live eFlow lookup/.test(r.text),
      '结论说的是「实时库 + eFlow 都没有」（不是「本地库」）', r.text);
    check(!/LOCAL_READ/.test(r.text),
      '**不读副本**：副本比 eFlow 更旧，再扫一遍不可能有新结果', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
    await stub.close();
  }
}

/* ⑧ PG 连不上 + 实时不可用 → 落到副本，必须标 [stale] */
{
  console.log('\n[8] PG 连不上 + 实时不可用 → 落到副本，标 [stale]');
  const stub = await startStub('hit');
  const deadUrl = stub.url;
  await stub.close();
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true, live: 'off' });
  try {
    const tt = await loadTt(cmd, stubJs, deadUrl, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'en', onLive: () => {} });
    check(r.ok === true, '返回 ok=true（副本里有这一单）', r.text);
    check(/LOCAL_READ/.test(r.text), '落到本地副本', r.text);
    check(/\[stale\]/.test(r.text), '**打了 [stale] 标记**（最坏落后 12 小时）', r.text);
    check(!/[\u4e00-\u9fff]/.test(r.text), '英文回复零中文残留', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
  }
}

/* ⑨ 中文侧：同样的降级要出中文标记 */
{
  console.log('\n[9] 中文 + 落副本 → 中文 [stale] 文案');
  const stub = await startStub('hit');
  const deadUrl = stub.url;
  await stub.close();
  const dir = mkdtempSync(join(tmpdir(), 'tthttp-'));
  const { cmd, stubJs } = makePyStub(dir, { foundLocal: true, live: 'off' });
  try {
    const tt = await loadTt(cmd, stubJs, deadUrl, 'on');
    const r = await tt.analyzeTt(TT_NO, { lang: 'zh', onLive: () => {} });
    check(r.ok === true, '返回 ok=true');
    check(/可能滞后/.test(r.text), '中文标记里说清「可能滞后」', r.text);
    check(!/\[stale\]/.test(r.text), '中文回复里不混英文标记', r.text);
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
  }
}

delete process.env.TT_PYTHON;
delete process.env.MY_APP_API_BASE;
delete process.env.TT_ANALYSIS_HTTP;
console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
