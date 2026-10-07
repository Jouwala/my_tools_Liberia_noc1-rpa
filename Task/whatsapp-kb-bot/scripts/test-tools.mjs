#!/usr/bin/env node
/**
 * 工具路由回归测试（**纯离线** —— 不联网、不查库、不调模型）。
 *   node scripts/test-tools.mjs
 *
 * 覆盖这次改造要解决的核心故障：
 *   「今天有 P1 的单子吗」原本被整句塞进知识库向量检索，模型只能答
 *   「资料里没有实际工单数据」—— 答案在数据里，不在语料里，路由错了。
 *
 * 所以这里最要紧的不是"能不能查"，而是**分流判断对不对**：
 *   · 「P1 是什么级别」  → search_knowledge（知识）
 *   · 「今天有几个 P1」  → query_tickets（数据）
 *   这两句只差几个字，判反了就完全答错，且看起来都"跑通了"。
 */
import { CONFIG } from '../src/config.js';
import {
  parseDateRange, parseSeverity, parseStatus, renderStats, fmtDate, shiftDate, parseListIntent,
} from '../src/ttquery.js';
import { parseByRule, parseToolCall, leftoverTerms } from '../src/tools.js';

// 本测的是纯函数，关掉工具路由不影响这里，但能避免误触发真实查询
CONFIG.toolsEnabled = false;

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

// 固定"今天"，让日期断言不随运行日期漂移
const NOW = new Date(2026, 9, 6); // 2026-10-06（月份从 0 起）

console.log('='.repeat(50));
console.log('工具路由测试（离线）');
console.log('='.repeat(50));

/* ------------------------------ 日期解析 ------------------------------ */

console.log('\n[1] 日期解析（模型不知道今天几号，必须规则算）');
{
  const t = parseDateRange('今天有p1的单子吗', NOW);
  check(t && t.start === '2026-10-06' && t.end === '2026-10-06', '今天 → 2026-10-06', JSON.stringify(t));

  const y = parseDateRange('昨天有多少 P2', NOW);
  check(y && y.start === '2026-10-05', '昨天 → 2026-10-05', JSON.stringify(y));

  const d2 = parseDateRange('前天的单', NOW);
  check(d2 && d2.start === '2026-10-04', '前天 → 2026-10-04', JSON.stringify(d2));

  const ex = parseDateRange('2026-10-02 有几个 P1', NOW);
  check(ex && ex.start === '2026-10-02' && ex.end === '2026-10-02', '显式日期', JSON.stringify(ex));

  const slash = parseDateRange('2026/9/30 的单', NOW);
  check(slash && slash.start === '2026-09-30', '斜杠日期也认', JSON.stringify(slash));

  const rg = parseDateRange('2026-10-01 到 2026-10-05 的工单', NOW);
  check(rg && rg.start === '2026-10-01' && rg.end === '2026-10-05', '日期范围', JSON.stringify(rg));

  const days = parseDateRange('近7天有多少单', NOW);
  check(days && days.start === '2026-09-30' && days.end === '2026-10-06', '近7天 → 含今天共 7 天', JSON.stringify(days));

  check(parseDateRange('P1 是什么级别', NOW) === null, '纯知识问法不产出日期');
  check(fmtDate(NOW) === '2026-10-06', 'fmtDate 按本地时区（不受 UTC 影响）', fmtDate(NOW));
  check(shiftDate(NOW, -1) === '2026-10-05', 'shiftDate 减一天', shiftDate(NOW, -1));
}

/* ------------------------------ 级别与状态 ------------------------------ */

console.log('\n[2] 级别与闭环状态');
check(parseSeverity('今天有p1的单子吗') === 'P1', '小写 p1 → P1');
check(parseSeverity('how many P2 today') === 'P2', 'P2');
check(parseSeverity('P 3 数量') === 'P3', '带空格也能认');
check(parseSeverity('P5 有几个') === null, 'P5 不是合法级别');
check(parseSeverity('P1 是什么') === 'P1', '级别能被抽出（是否走统计由意图判断管）');
check(parseStatus('未闭环的有几个') === 'open', '未闭环 → open');
check(parseStatus('已关闭多少单') === 'closed', '已关闭 → closed');
check(parseStatus('今天有几个 P1') === 'all', '没说闭环 → all');

/* ------------------------- 分流：知识 vs 数据 ------------------------- */

console.log('\n[3] 分流（本次的核心：别把统计问题送进向量检索）');
{
  const q1 = parseByRule('今天有p1的单子吗', NOW);
  check(q1 && q1.tool === 'query_tickets', '「今天有p1的单子吗」→ query_tickets', JSON.stringify(q1));
  check(q1 && q1.args.severity === 'P1', '  级别参数抽到 P1', JSON.stringify(q1?.args));
  check(q1 && q1.args.start === '2026-10-06', '  日期参数 = 今天', JSON.stringify(q1?.args));

  const q2 = parseByRule('P1 是什么级别', NOW);
  check(q2 === null || q2.tool === 'search_knowledge', '「P1 是什么级别」不当统计处理', JSON.stringify(q2));

  const q3 = parseByRule('P1 怎么判定的', NOW);
  check(q3 === null || q3.tool === 'search_knowledge', '「P1 怎么判定的」→ 知识', JSON.stringify(q3));

  const q4 = parseByRule('昨天有多少 P2 未闭环', NOW);
  check(q4 && q4.tool === 'query_tickets' && q4.args.status === 'open', '带闭环状态的统计', JSON.stringify(q4));

  const q5 = parseByRule('how many P1 tickets today', NOW);
  check(q5 && q5.tool === 'query_tickets', '英文统计问法 → query_tickets', JSON.stringify(q5));

  const q6 = parseByRule('TT202609150073', NOW);
  check(q6 && q6.tool === 'analyze_ticket', '单号 → analyze_ticket（最强信号，优先）', JSON.stringify(q6));

  const q7 = parseByRule('分析 TT202610060087 有几个 P1', NOW);
  check(q7 && q7.tool === 'analyze_ticket', '同时有单号和数量词时单号优先', JSON.stringify(q7));

  const q8 = parseByRule('告警码 198094422 会被压缩成什么', NOW);
  check(q8 === null || q8.tool === 'search_knowledge', '告警码压缩规则 → 知识（不是统计）', JSON.stringify(q8));
}

console.log('\n[3b] 站点问题必须转交模型层（2026-10-07 实测踩坑）');
{
  // 曾经的错误行为：规则层被「有几个」触发、带 site:'' 直接出结果，
  // 于是「Wood camp 这个站昨天有几个单」答成了**全网 94 单**。
  // 答错而不报错 —— 这类必须靠"规则层主动弃权"来堵。
  const s1 = parseByRule('Wood camp 这个站昨天有几个单', NOW);
  check(s1 === null, '带站点的问题规则层弃权 → 交模型抽站名', JSON.stringify(s1));

  const s2 = parseByRule('Qcell R.I.A 有几个 P1', NOW);
  check(s2 === null, '站名 + 级别也弃权', JSON.stringify(s2));

  const s3 = parseByRule('这个站昨天有多少单', NOW);
  check(s3 === null, '「这个站」同样弃权', JSON.stringify(s3));

  // 反向：没有站点信号时规则层照常短路（不能因噎废食，把延迟又还回去）
  const s4 = parseByRule('昨天一共有多少单', NOW);
  check(s4 && s4.tool === 'query_tickets' && s4.args.site === '', '无站点信号仍走规则短路', JSON.stringify(s4));

  const s5 = parseByRule('how many P1 tickets today', NOW);
  check(s5 && s5.tool === 'query_tickets', '英文通用问法不误弃权（停用词表生效）', JSON.stringify(s5));

  // 残余判据本身
  check(leftoverTerms('Wood camp 这个站昨天有几个单').join('|').includes('Wood'), '残余能认出 Wood camp');
  check(leftoverTerms('Qcell R.I.A 有几个 P1').length > 0, '残余能认出 Qcell R.I.A');
  check(leftoverTerms('昨天一共有多少单').length === 0, '纯通用问法残余为空', JSON.stringify(leftoverTerms('昨天一共有多少单')));
  check(leftoverTerms('how many P1 tickets today').length === 0, '英文通用问法残余为空', JSON.stringify(leftoverTerms('how many P1 tickets today')));
}

/* --------------------------- 模型输出解析 --------------------------- */

console.log('\n[4] 模型工具调用的解析（宽容但不能乱认）');
{
  check(parseToolCall('{"tool":"query_tickets","args":{"severity":"P1"}}')?.tool === 'query_tickets', '标准 JSON');
  check(parseToolCall('好的：{"tool":"search_knowledge","args":{}}')?.tool === 'search_knowledge', '前后带废话');
  check(
    parseToolCall('```json\n{"tool":"analyze_ticket","args":{"tt_no":"TT1"}}\n```')?.tool === 'analyze_ticket',
    '带代码块围栏'
  );
  check(parseToolCall('{"tool":"query_alarms","args":{}}') === null, '未实现的工具名 → null（不能瞎调）');
  check(parseToolCall('我不知道') === null, '没有 JSON → null');
  check(parseToolCall('') === null, '空串 → null');
  check(parseToolCall(null) === null, 'null → null');
  check(parseToolCall('{"tool":"search_knowledge"}')?.args !== undefined, '缺 args 字段也能过（补空对象）');
}

console.log('\n[4b] 单号列表意图（2026-10-07 实测漏判：要 ID 只给了个数）');
{
  const q = '本月有几个P1的单子，请输出TT单的ID给我';
  check(parseListIntent(q) === true, '「请输出TT单的ID给我」→ 要名单');
  check(parseListIntent('本月有几个P1的单子') === false, '只问个数 → 不要名单');
  check(parseListIntent('列出未闭环的单') === true, '「列出」→ 要名单');
  check(parseListIntent('有哪些 P2 单') === true, '「有哪些」→ 要名单');
  check(parseListIntent('list P1 tickets') === true, '英文 list → 要名单');
  check(parseListIntent('本月 P1 一共几个') === false, '纯计数 → 不要名单');

  // 规则层要把 list 带下去
  const r = parseByRule(q, NOW);
  check(r && r.tool === 'query_tickets', '该问题走统计通道', JSON.stringify(r));
  check(r && r.args.list === true, '  且带 list=true', JSON.stringify(r?.args));
  check(r && r.args.severity === 'P1', '  级别 P1', JSON.stringify(r?.args));
}

/* ------------------------------ 渲染 ------------------------------ */
console.log('\n[5] 统计结果渲染（数字必须原样，不能由模型加工）');
{
  const zero = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: 'P1', total: 0, open: 0, by_severity: {} },
    'zh'
  );
  check(zero.includes('0') && zero.includes('P1'), '零结果也要说清是 P1 = 0', JSON.stringify(zero));

  const some = renderStats(
    {
      start: '2026-10-06', end: '2026-10-06', severity: null, total: 94, open: 67,
      by_severity: { P2: 47, P3: 37, P4: 10 },
      samples: [{ tt_no: 'TT202610060087', site_name: 'Wood camp' }],
    },
    'zh'
  );
  check(some.includes('94'), '总数原样出现', JSON.stringify(some));
  check(some.includes('P2 47'), '级别分布原样出现', JSON.stringify(some));
  check(some.includes('TT202610060087'), '样例单号出现', JSON.stringify(some));

  const en = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: 'P1', total: 3, open: 1, by_severity: { P1: 3 } },
    'en'
  );
  check(en.includes('P1') && !/没有/.test(en), '英文渲染不含中文', JSON.stringify(en));

  const degraded = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: null, total: 82, open: 56, by_severity: { P2: 47 } },
    'zh',
    true
  );
  check(degraded.includes('本地副本'), '降级时必须标注口径', JSON.stringify(degraded));

  const noDegrade = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: null, total: 82, open: 56, by_severity: {} },
    'zh',
    false
  );
  check(!noDegrade.includes('本地副本'), '非降级不标注', JSON.stringify(noDegrade));

  // 已按单级别过滤时，再列一次「级别分布」是废话
  const single = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: 'P1', total: 2, open: 2, by_severity: { P1: 2 } },
    'zh'
  );
  check(!single.includes('级别分布'), '单级别过滤时不重复列分布', JSON.stringify(single));

  // 用户点名要单号：标签换成「单号」，且要给出截断提示
  const listed = renderStats(
    {
      start: '2026-10-01', end: '2026-10-07', severity: 'P1', status: 'all', total: 6,
      open: 2, closed: 4, detail_total: 6,
      samples: [
        { tt_no: 'TT202610020060', site_name: 'LBS' },
        { tt_no: 'TT202610020035', site_name: 'LBS' },
      ],
    },
    'zh',
    false,
    true
  );
  check(listed.includes('单号：'), '要名单时用「单号」标签', JSON.stringify(listed));
  check(listed.includes('TT202610020060'), '名单里有真实单号', JSON.stringify(listed));
  check(listed.includes('还有 4 单未列出'), '截断时提示剩余条数', JSON.stringify(listed));

  // 不要名单时不该出现「单号：」标签和截断提示
  const notListed = renderStats(
    {
      start: '2026-10-01', end: '2026-10-07', severity: 'P1', status: 'all', total: 6,
      open: 2, samples: [{ tt_no: 'TT202610020060', site_name: 'LBS' }],
    },
    'zh',
    false,
    false
  );
  check(notListed.includes('最近几单'), '不要名单时用「最近几单」标签', JSON.stringify(notListed));
  check(!notListed.includes('未列出'), '不要名单时不提截断', JSON.stringify(notListed));

  // 要名单但一条明细都没取到时，必须说清楚，不能让用户对着数字发懵
  const noDetail = renderStats(
    { start: '2026-10-01', end: '2026-10-07', severity: 'P1', total: 6, open: 2, samples: [] },
    'zh',
    false,
    true
  );
  check(noDetail.includes('没能取到单号明细'), '取不到明细要如实说明', JSON.stringify(noDetail));
}

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
