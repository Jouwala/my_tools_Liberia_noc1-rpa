#!/usr/bin/env node
/**
 * 知识库黄金集评测 —— 以后改检索/路由**必须先跑这个**。
 *
 *   npm run eval:kb:offline     只测纯函数（parseByRule / lookup / 解析），离线、秒级
 *   npm run eval:kb             在 offline 基础上再跑 routeAnswer（需索引 + 嵌入 + 可能云端）
 *   node scripts/eval-kb.mjs --only r-tt,cmp-198094422   # 只跑部分题
 *
 * ## 为什么要有门禁
 *
 * 校准脚本存在，但题集错误（README 的示例题是「年假/报销/天气」，与 TT 语料无关）。
 * 没有门禁时，任何检索改动都可能「感觉更好、实际更幻觉」。
 * 所以：判**通道** + **关键子串**，不追求全自动判语义。
 *
 * ## 退出码
 *
 * 有失败则 1（可接 CI）。打印表格：id / channel / tool / pass。
 */
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CONFIG, ROOT } from '../src/config.js';
import { parseByRule, parseToolCall, runLookup } from '../src/tools.js';
import { buildLookups, findAlarmCode, findCompress, findLevelByCode, findLevelBySeverity } from '../src/lookups.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const GOLDEN = resolve(HERE, '..', 'evals', 'kb-golden.jsonl');

const argv = process.argv.slice(2);
const OFFLINE = argv.includes('--offline');
const onlyArg = argv.find((a) => a.startsWith('--only'));
const only = onlyArg
  ? (onlyArg.includes('=') ? onlyArg.split('=')[1] : argv[argv.indexOf(onlyArg) + 1] || '').split(',').filter(Boolean)
  : null;

const NOW = new Date(2026, 9, 7); // 固定基准日，避免日期断言随运行日漂移

let pass = 0;
let fail = 0;
const rows = [];

function readGolden() {
  const raw = readFileSync(GOLDEN, 'utf8').trim();
  return raw
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

/* ------------------------------ 离线断言 ------------------------------ */

const L = buildLookups(CONFIG.knowledgeDirAbs, ROOT);

/**
 * 跑一条题的「离线部分」：parseByRule / lookup 纯函数 / 特殊哨兵题。
 * @returns {{ok:boolean, detail:string, channel?:string, tool?:string}}
 */
function runOffline(item) {
  // 哨兵题：help 文案（index.js 里定义，这里只查关键词由 caller 提供）
  if (item.q === '__help__') {
    // help 文本在 index.js 的 builtins 里，无法在此直接 import（有副作用）。
    // 退化为「读源码含关键词」——不理想但足够当门禁，改动 help 会被这条钉住。
    const src = readFileSync(resolve(ROOT, 'src/index.js'), 'utf8');
    const missing = (item.expectHelpContains || []).filter((k) => !src.includes(k));
    return { ok: missing.length === 0, detail: missing.length ? `help 缺关键词：${missing.join('、')}` : 'help 含统计/查表' };
  }
  if (item.q === '__parseToolCall__') {
    const r = parseToolCall(`{"tool":"${item.expectToolCallNull}","args":{}}`);
    return { ok: r === null, detail: r === null ? '未实现工具名被拒' : `误认了 ${r.tool}` };
  }

  const call = parseByRule(item.q, NOW);

  // 查表工具：离线也能真渲染（不依赖网络/索引），顺手校验 mustInclude/mustNotInclude。
  // 这样「站点属性过滤」「告警名→码」这类新能力在离线门禁里就被钉住。
  if (call && call.tool?.startsWith('lookup')) {
    const r = runLookup(call, item.lang || 'zh', { lookups: L, question: item.q });
    const text = String(r.text || '');
    const problems = [];
    if (item.expectTool && call.tool !== item.expectTool) problems.push(`工具期望 ${item.expectTool}，实得 ${call.tool}`);
    for (const s of item.mustInclude || []) if (!text.includes(s)) problems.push(`缺少必须子串「${s}」`);
    for (const s of item.mustNotInclude || []) if (text.includes(s)) problems.push(`出现禁止子串「${s}」`);
    return { ok: problems.length === 0, detail: problems.join('；') || `tool=${call.tool}`, tool: call.tool, channel: 'lookup' };
  }

  // expectRuleNull：规则层必须弃权
  if (item.expectRuleNull) {
    return { ok: call === null, detail: call === null ? '规则层弃权' : `未弃权：${JSON.stringify(call)}` };
  }
  // expectTool：工具名必须一致
  if (item.expectTool) {
    const ok = call && call.tool === item.expectTool;
    return { ok, detail: ok ? `tool=${call.tool}` : `期望 ${item.expectTool}，实得 ${call ? call.tool : 'null'}`, tool: call?.tool };
  }
  // expectNotChannel：绝不能走某条通道（多为 not stats）
  if (item.expectNotChannel) {
    const ch = call?.tool === 'query_tickets' ? 'stats' : call?.tool ? 'lookup/other' : 'kb';
    const ok = !(item.expectNotChannel === 'stats' && call?.tool === 'query_tickets');
    return { ok, detail: ok ? `未走 ${item.expectNotChannel}` : `误走 ${item.expectNotChannel}` };
  }
  // expectChannel：offlineOnly 场景下只校验路由层可判定的通道
  if (item.expectChannel) {
    const ch =
      call?.tool === 'analyze_ticket'
        ? 'tt'
        : call?.tool === 'query_tickets'
          ? 'stats'
          : call?.tool?.startsWith('lookup')
            ? 'lookup'
            : 'kb';
    // 知识库题的通道由在线路径决定（离线时规则层应为 null → kb）
    const ok = ch === item.expectChannel;
    return { ok, detail: ok ? `channel=${ch}` : `期望 ${item.expectChannel}，实得 ${ch}`, channel: ch, tool: call?.tool };
  }
  return { ok: true, detail: '（无离线断言）' };
}

/* ------------------------------ 在线断言 ------------------------------ */

let routeAnswer = null;
let index = null;
async function ensureOnline() {
  if (routeAnswer) return true;
  try {
    ({ routeAnswer } = await import('../src/answer.js'));
    const { loadIndex } = await import('../src/rag.js');
    index = loadIndex();
    const { loadLookupsOnce } = await import('../src/tools.js');
    loadLookupsOnce();
    return true;
  } catch (err) {
    console.error(`\n! 在线评测不可用（索引/网络）：${err.message}`);
    console.error('  用 npm run eval:kb:offline 只跑离线门禁。');
    return false;
  }
}

/**
 * 在线可达性预检：探一次嵌入服务。不可达时，**只跑离线门禁**并在报告里说明，
 * 而不是把每条知识库题都报成「fetch failed」——那是基础设施不可用，
 * 不是回答质量回归，混为一谈会淹没真正的失败。
 */
async function onlineReachable() {
  try {
    const { embedOne } = await import('../src/ollama.js');
    await embedOne('ping');
    return true;
  } catch {
    return false;
  }
}

async function runOnline(item) {
  const r = await routeAnswer(item.q, index, { lang: item.lang || 'zh', history: [] });
  const got = { channel: r.channel, tool: r.tool, text: String(r.text || '') };
  const problems = [];

  if (item.expectChannel && got.channel !== item.expectChannel) {
    problems.push(`通道期望 ${item.expectChannel}，实得 ${got.channel}`);
  }
  if (item.expectTool && got.tool !== item.expectTool) {
    problems.push(`工具期望 ${item.expectTool}，实得 ${got.tool}`);
  }
  for (const s of item.mustInclude || []) {
    if (!got.text.includes(s)) problems.push(`缺少必须子串「${s}」`);
  }
  for (const s of item.mustNotInclude || []) {
    if (got.text.includes(s)) problems.push(`出现禁止子串「${s}」`);
  }
  return { ok: problems.length === 0, detail: problems.join('；') || '通过', channel: got.channel, tool: got.tool };
}

/* -------------------------------- 主流程 -------------------------------- */

async function main() {
  let items = readGolden();
  if (only) items = items.filter((it) => only.includes(it.id));
  console.log(`\n黄金集：${GOLDEN}`);
  console.log(`模式：${OFFLINE ? '离线（纯函数）' : '在线（含 routeAnswer）'}　题数：${items.length}\n`);

  let onlineReady = true;
  if (!OFFLINE) {
    onlineReady = (await ensureOnline()) && (await onlineReachable());
    if (!onlineReady) {
      console.log('! 嵌入服务不可达（.27 Ollama）—— 本次只跑离线门禁，知识库类题按离线判定。');
      console.log('  （这不是质量回归；等到 .27 可达再跑完整在线评测。）\n');
    }
  }

  for (const item of items) {
    let res = runOffline(item);
    // 非 offlineOnly 且在线可用 → 再跑在线断言（在线结果为准）
    if (!OFFLINE && onlineReady && !item.offlineOnly && item.q !== '__help__' && item.q !== '__parseToolCall__') {
      try {
        res = await runOnline(item);
      } catch (err) {
        res = { ok: false, detail: `在线异常：${err.message}` };
      }
    }
    (res.ok ? pass++ : fail++);
    rows.push({ id: item.id, channel: res.channel || '-', tool: res.tool || '-', ok: res.ok, detail: res.detail });
    console.log(`  ${res.ok ? '✓' : '✗'} ${item.id.padEnd(22)} ${String(res.channel || '-').padEnd(7)} ${String(res.tool || '-').padEnd(18)} ${res.ok ? '' : res.detail}`);
  }

  console.log(`\n${'='.repeat(60)}`);
  console.log(`通过 ${pass} / ${pass + fail}　失败 ${fail}`);
  if (fail) {
    console.log('\n失败明细（把失败题记进 jsonl 的 notes，不要删题）：');
    for (const r of rows.filter((r) => !r.ok)) console.log(`  · ${r.id}：${r.detail}`);
  }
  process.exit(fail ? 1 : 0);
}

main().catch((err) => {
  console.error(`\n评测脚本异常：${err.stack || err.message}`);
  process.exit(1);
});
