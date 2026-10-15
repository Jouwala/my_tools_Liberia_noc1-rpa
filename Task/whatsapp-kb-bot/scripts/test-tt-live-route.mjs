#!/usr/bin/env node
/**
 * 实时兜底编排测试（Node 侧）。
 *   node scripts/test-tt-live-route.mjs
 *
 * 只测**编排逻辑**，不碰真实 eFlow、不碰工单库 —— 靠改写
 * `TT_PYTHON` 指向一个桩「解释器」，让 `scripts/eflow-live-tt.py` 的探测与取数
 * 都由桩来回答。
 *
 * 覆盖的都是在真实环境里很难摆出来、但错了就是**误导用户**的分支：
 *
 *   ① 本地 miss → **必须先发垫话**再实时查。
 *      实时查询要登录 eFlow + 翻页扫描，比本地慢一个数量级，
 *      不垫这句用户看到的就是十几秒静默，以为机器人掉线。
 *   ② 实时命中 → 出报告，且**不能**再带「库里没有找到」。
 *   ③ 本地 miss + 实时也 miss → 保留原来那句「库里没有 + 库内最新单号」
 *      （用户靠它判断「我的单比库内最新还新多少」），但前面要加一句
 *      「实时也查过了」，否则用户以为我们没去查。
 *   ④ **实时通道不可用**（缺解释器/缺依赖）→ 绝不能因此让本地查询也失败；
 *      必须退回原来那句「库里没有」。
 *   ⑤ 超时等**故障**（不是 notFound）→ 走重试，**不该**去实时查。
 *      本地库其实有这一单，去 eFlow 是绕远路。
 */
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

/**
 * 每个用例一个独立的桩目录：
 *   <tmp>/python.exe   —— 假的「解释器」（其实是 node.exe 的拷贝）
 *   <tmp>/stub.mjs     —— 经 NODE_OPTIONS --import 预加载的桩逻辑
 *   <tmp>/mode.json    —— 决定这次跑要模拟哪种行为
 */
function makeStub(mode) {
  const dir = mkdtempSync(join(tmpdir(), 'ttlive-'));
  writeFileSync(join(dir, 'mode.json'), JSON.stringify(mode), 'utf8');

  // 桩「python」：以**被预加载模块**的身份拿到 process.argv ——
  // 那正是 tt.js 原本要传给 python 的参数 [script, ttNo, --lang, zh, ...]。
  const stubJs = join(dir, 'stub.mjs');
  writeFileSync(
    stubJs,
    `
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const mode = JSON.parse(readFileSync(join(dir, 'mode.json'), 'utf8'));

// 经 NODE_OPTIONS --import 预加载时，process.argv 里**没有** node 与脚本路径，
// 就是 tt.js 传给 python 的那串参数本身：
//   ['D:/.../tt-analyze.py', 'TT202609290052', '--lang', 'zh']
// 路径统一成正斜杠再判后缀 —— 反斜杠在这里要跨两层模板字符串转义，
// 极易写成非法正则（曾经写成 /\\/g 直接 SyntaxError），用 split/join 最稳。
const argv = process.argv.slice(1);
const script = String(argv[0] || '').split('\\\\').join('/');

function done(code, out) {
  if (out) process.stdout.write(out);
  process.exit(code);
}

// eflow-live-tt.py 的 --which 探测（解释器能否 import pandas/sqlalchemy）
if (script.endsWith('eflow-live-tt.py') && argv.includes('--which')) {
  if (mode.probe === 'ok') done(0, 'C:/fake/python.exe\\n');
  done(2);
}

// 实时查询桥接
if (script.endsWith('eflow-live-tt.py')) {
  if (mode.live === 'hit') {
    done(0, JSON.stringify({ tt_no: mode.tt || 'TT202609290052', site_name: 'Bokessa', status: 'WaitFOProcess' }));
  }
  if (mode.live === 'miss') done(1);
  if (mode.live === 'timeout') done(3);
  done(2);
}

// tt-analyze.py：本地查询 / 实时行渲染
if (script.endsWith('tt-analyze.py')) {
  if (argv.includes('--live-row')) {
    if (mode.live === 'hit') done(0, '⚡ 已实时查 eFlow\\nBokessa | live report');
    done(2);
  }
  if (mode.local === 'found') done(0, 'local report OK');
  if (mode.local === 'notfound') {
    // 必须按 --lang 给对应语言 —— 真实脚本就是这么做的（tt-analyze.py 的
    // _LABELS）。桩如果只会中文，测试就会把「桩不够真」误报成「产品漏中文」。
    const lang = argv[argv.indexOf('--lang') + 1] || 'zh';
    done(1, lang === 'en'
      ? 'Ticket TT202609290052 not found in the ticket database.\\nThe newest ticket in the database is TT202609290049.'
      : '工单库里没有找到单号 X。\\n库内最新单号是 TT202609290049。');
  }
  if (mode.local === 'timeout') done(1);   // stdout 为空 + 非零 → tt.js 判为超时/异常
  done(3);
}

done(3);
`,
    'utf8'
  );

  // 假「python.exe」：必须是一个**能直接被 execFile 启动的可执行文件**。
  // 不能写成 .cmd —— Node 24 的 execFile 拒绝 spawn .cmd/.bat（EINVAL）。
  // 所以抄一份 node.exe 本体，参数透传给预加载的桩。
  const cmd = join(dir, 'python.exe');
  copyFileSync(process.execPath, cmd);
  return { dir, cmd, stubJs };
}

/** 在给定的桩环境下 import 一份全新的 tt.js（PYTHON 是模块级常量）。 */
async function loadTt(cmd, stubJs) {
  process.env.TT_PYTHON = cmd;
  process.env.TT_RETRY_DELAY_MS = '1';
  process.env.TT_TIMEOUT_MS = '5000';
  process.env.TT_LIVE_TIMEOUT_MS = '5000';
  // 关掉「单号分析 HTTP 优先」通道（2026-10-15 新增）：
  // 本套件测的是**本地库 + eFlow 实时兜底**的编排，桩只拦 Python 子进程，
  // 不拦 HTTP。若不关，analyzeTt 会先真去连 myAppApiBase（真实后端），
  // 编排分支就不会按桩的预期走 —— 那测的就不是本套件要测的东西了。
  // HTTP 通道由 scripts/test-tt-analysis-http.mjs 单独覆盖。
  process.env.TT_ANALYSIS_HTTP = '0';
  process.env.NODE_OPTIONS = `--import=${pathToFileURL(stubJs).href}`;
  const url = new URL('../src/tt.js', import.meta.url);
  url.searchParams.set('t', String(Date.now() + Math.random()));
  return import(url.href);
}

console.log('='.repeat(50));
console.log('实时兜底编排测试（Node 侧，用桩解释器）');
console.log('='.repeat(50));

// 每个用例都改了进程级 env（TT_PYTHON / NODE_OPTIONS），**必须串行**。
async function scenario(label, mode, body) {
  console.log(`\n${label}`);
  const { dir, cmd, stubJs } = makeStub(mode);
  try {
    await body(await loadTt(cmd, stubJs));
  } finally {
    delete process.env.NODE_OPTIONS;
    rmSync(dir, { recursive: true, force: true });
  }
}

/* ------------------------- ① 本地 miss → 实时命中 ------------------------- */

await scenario('[1] 本地 miss → 实时命中', { local: 'notfound', live: 'hit', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: (t) => liveMsgs.push(t) });
  check(r.ok === true, '返回 ok=true（实时拿到了数据）');
  check(/Bokessa/.test(r.text), '报告来自实时行');
  check(!/工单库里没有找到/.test(r.text), '**不再**出现「工单库里没有找到」');
  check(liveMsgs.length === 1, '发了 1 条垫话', JSON.stringify(liveMsgs));
  check(/eFlow/.test(liveMsgs[0] || ''), '垫话里说明「去 eFlow 实时查」', liveMsgs[0]);
  check(/稍等/.test(liveMsgs[0] || ''), '垫话里让用户稍等', liveMsgs[0]);
});

/* ----------------------- ② 本地 miss → 实时也 miss ----------------------- */

await scenario('[2] 本地 miss → 实时也 miss', { local: 'notfound', live: 'miss', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: (t) => liveMsgs.push(t) });
  check(r.ok === false, '返回 ok=false');
  check(/eFlow/.test(r.text), '说明「实时也查过了」', r.text);
  check(/TT202609290049/.test(r.text), '保留「库内最新单号」这个有用信息', r.text);
  check(liveMsgs.length === 1, '仍然先发了垫话');
});

/* --------------------- ③ 实时通道不可用 → 优雅降级 --------------------- */

await scenario('[3] 实时通道不可用（缺依赖）', { local: 'notfound', live: 'unavailable', probe: 'fail' }, async (tt) => {
  const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: () => {} });
  check(r.ok === false, '返回 ok=false（不崩、不抛）');
  check(/工单库里没有找到/.test(r.text), '保留原来那句「库里没有找到」');
  check(/TT202609290049/.test(r.text), '保留「库内最新单号」');
  check(/eFlow/.test(r.text), '告知「实时没查成」（不假装已实时确认）', r.text);
});

/* ------------------- ④ 超时（故障，不是 notFound）→ 重试，不实时 ------------------- */

await scenario('[4] 本地超时（故障）→ 重试，且**不**走实时', { local: 'timeout', live: 'hit', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  const retryMsgs = [];
  const r = await tt.analyzeTt('TT202609290052', {
    lang: 'zh',
    onLive: (t) => liveMsgs.push(t),
    onRetry: (t) => retryMsgs.push(t),
  });
  check(r.ok === false, '返回 ok=false');
  check(retryMsgs.length === 1, '发了「正在重试」垫话', JSON.stringify(retryMsgs));
  check(liveMsgs.length === 0, '**没有**去实时查（本地库其实有这一单）', JSON.stringify(liveMsgs));
  check(/超时|出错/.test(r.text), '文案说明是超时/出错，而不是「查无此单」', r.text);
});

/* ------------------------- ⑤ 本地命中 → 不做任何兜底 ------------------------- */

await scenario('[5] 本地命中 → 直接返回', { local: 'found', live: 'hit', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: (t) => liveMsgs.push(t) });
  check(r.ok === true, '返回 ok=true');
  check(/local report OK/.test(r.text), '用的是本地结果');
  check(liveMsgs.length === 0, '没有多余垫话', JSON.stringify(liveMsgs));
});

/* --------------------------- ⑥ 英文提问走英文垫话 --------------------------- */

await scenario('[6] 英文提问 → 英文垫话（不发中文）', { local: 'notfound', live: 'hit', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  await tt.analyzeTt('TT202609290052', { lang: 'en', onLive: (t) => liveMsgs.push(t) });
  check(liveMsgs.length === 1, '发了 1 条垫话');
  check(!/[\u4e00-\u9fff]/.test(liveMsgs[0] || ''), '垫话无中文残留', liveMsgs[0]);
  check(/eFlow|live/i.test(liveMsgs[0] || ''), '垫话提到 eFlow/live', liveMsgs[0]);
});

/* --------------------- ⑦ 英文：实时也不可用时的文案 --------------------- */

await scenario('[7] 英文 + 实时不可用', { local: 'notfound', live: 'unavailable', probe: 'fail' }, async (tt) => {
  const r = await tt.analyzeTt('TT202609290052', { lang: 'en', onLive: () => {} });
  check(r.ok === false, '返回 ok=false');
  check(/eFlow|live/i.test(r.text), '英文文案提到 eFlow/live', r.text);
  // 这条是真实漏出去过的 bug：detail 参数来自 Python 脚本的 stderr，
  // 内容是中文诊断。英文回复一旦拼上它，用户看到的就是中英混排。
  check(!/[\u4e00-\u9fff]/.test(r.text), '英文回复**零中文残留**（含实时诊断细节）', r.text);
  check(!/pandas|sqlalchemy|解释器/.test(r.text), '不把内部依赖细节抖给用户', r.text);
});

/* ------------- ⑧ 中文：实时不可用时**应该**保留诊断细节 ------------- */

await scenario('[8] 中文 + 实时不可用 → 保留可诊断的细节', { local: 'notfound', live: 'unavailable', probe: 'fail' }, async (tt) => {
  const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: () => {} });
  check(/eFlow/.test(r.text), '中文文案提到 eFlow', r.text);
  check(/工单库里没有找到/.test(r.text), '仍保留本地那句结论');
});

/* ------------------- ⑨ 实时通道被关掉 → 完全不走实时 ------------------- */

await scenario('[9] ttLiveFallback=false → 退回改造前行为', { local: 'notfound', live: 'hit', probe: 'ok' }, async (tt) => {
  const liveMsgs = [];
  const prev = process.env.TT_LIVE_FALLBACK;
  process.env.TT_LIVE_FALLBACK = '0';
  try {
    const r = await tt.analyzeTt('TT202609290052', { lang: 'zh', onLive: (t) => liveMsgs.push(t) });
    check(r.ok === false, '返回 ok=false');
    check(liveMsgs.length === 0, '不发垫话', JSON.stringify(liveMsgs));
    check(/工单库里没有找到/.test(r.text), '直接回「库里没有找到」', r.text);
  } finally {
    if (prev === undefined) delete process.env.TT_LIVE_FALLBACK;
    else process.env.TT_LIVE_FALLBACK = prev;
  }
});

delete process.env.TT_PYTHON;
console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
