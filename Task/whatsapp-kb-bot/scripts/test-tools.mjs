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
import { formatRaised } from '../src/sitealarms.js';

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

  // 英文日期词（2026-10-08 实测缺口：「how many P1 Tickets for this month」
  // 因不认英文日期而落到模型层 2.9s；本应由规则层 60ms 出结果）
  const enM = parseDateRange('how many P1 Tickets for this month', NOW);
  check(enM && enM.start === '2026-10-01' && enM.end === '2026-10-06', 'this month → 本月至今', JSON.stringify(enM));
  const enY = parseDateRange('how many tickets yesterday', NOW);
  check(enY && enY.start === '2026-10-05', 'yesterday → 昨天', JSON.stringify(enY));
  const enT = parseDateRange('how many tickets today', NOW);
  check(enT && enT.start === '2026-10-06', 'today → 今天', JSON.stringify(enT));
  const enW = parseDateRange('this week tickets', NOW);
  check(enW && enW.start === '2026-10-05', 'this week → 本周（周一为 10-05）', JSON.stringify(enW));
  const enLm = parseDateRange('last month tickets', NOW);
  check(enLm && enLm.start === '2026-09-01' && enLm.end === '2026-09-30', 'last month → 上月整月', JSON.stringify(enLm));
  const enLd = parseDateRange('last 7 days tickets', NOW);
  check(enLd && enLd.start === '2026-09-30' && enLd.end === '2026-10-06', 'last 7 days → 近7天', JSON.stringify(enLd));
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

  // A4 之后：级别定义类问法走**查表**（lookup_level_rule），不再是纯知识库。
  // 关键是「不得当统计处理」—— 至于走查表还是知识库，记在下面的断言里。
  const q2 = parseByRule('P1 是什么级别', NOW);
  check(q2 === null || q2.tool === 'lookup_level_rule' || q2.tool === 'search_knowledge', '「P1 是什么级别」不当统计处理', JSON.stringify(q2));
  check(!(q2 && q2.tool === 'query_tickets'), '  「P1 是什么级别」**不是** query_tickets', JSON.stringify(q2));

  const q3 = parseByRule('P1 怎么判定的', NOW);
  check(q3 === null || q3.tool === 'lookup_level_rule' || q3.tool === 'search_knowledge', '「P1 怎么判定的」→ 级别/知识（非统计）', JSON.stringify(q3));

  const q4 = parseByRule('昨天有多少 P2 未闭环', NOW);
  check(q4 && q4.tool === 'query_tickets' && q4.args.status === 'open', '带闭环状态的统计', JSON.stringify(q4));

  const q5 = parseByRule('how many P1 tickets today', NOW);
  check(q5 && q5.tool === 'query_tickets', '英文统计问法 → query_tickets', JSON.stringify(q5));

  const q6 = parseByRule('TT202609150073', NOW);
  check(q6 && q6.tool === 'analyze_ticket', '单号 → analyze_ticket（最强信号，优先）', JSON.stringify(q6));

  const q7 = parseByRule('分析 TT202610060087 有几个 P1', NOW);
  check(q7 && q7.tool === 'analyze_ticket', '同时有单号和数量词时单号优先', JSON.stringify(q7));

  // A4 之后：告警码压缩问法走**查表**（lookup_compress），不是统计、也不是知识库。
  const q8 = parseByRule('告警码 198094422 会被压缩成什么', NOW);
  check(q8 === null || q8.tool === 'lookup_compress' || q8.tool === 'search_knowledge', '告警码压缩规则 → 查表（不是统计）', JSON.stringify(q8));
  check(!(q8 && q8.tool === 'query_tickets'), '  压缩问法**不是** query_tickets', JSON.stringify(q8));
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

console.log('\n[3f] 具体星期几（2026-10-18：旧实现把「本周五」当整周）');
{
  // 事故形态：旧实现里 `/本周/` 先命中，返回**整周**区间。
  // 问「本周五有几个单」拿到周一到今天的合计 —— 数字偏大但不报错。
  // 这里以 NOW=周二 10-06 为基准，本周一 = 10-05。
  const cases = {
    '本周五有多少单': '2026-10-09',
    '本周三有多少单': '2026-10-07',
    '本周二有多少单': '2026-10-06',
    '本周日有多少单': '2026-10-11',
    '周五有多少单': '2026-10-09',      // 裸「周X」= 本周那一天（不再回溯到上周）
    '星期三有几个单': '2026-10-07',
    '礼拜三有几个单': '2026-10-07',    // 「礼拜」归一成「星期」
    '星期天有几个单': '2026-10-11',
    '上周六有几个P2': '2026-10-03',
    '上周一有多少单': '2026-09-28',
    '上礼拜五有多少单': '2026-10-02',
    '下周一有多少单': '2026-10-12',
    '上上周日有多少单': '2026-09-27',
    '上上个礼拜一有多少单': '2026-09-21',
  };
  for (const [q, expect] of Object.entries(cases)) {
    const r = parseDateRange(q, NOW);
    check(r?.start === expect && r?.end === expect, `  ${q} → ${expect}`, JSON.stringify(r));
  }
  // 反向：整周问法不能被星期几分支吃掉
  const wk = parseDateRange('本周有多少单', NOW);
  check(wk?.start === '2026-10-05' && wk?.end === '2026-10-06', '  反向：「本周」仍是整周区间', JSON.stringify(wk));
  // 反向：含星期字的普通词不能误判（如「周期的单」）
  check(parseDateRange('告警码 99933 是什么', NOW) === null, '  反向：无日期问法仍返回 null');
}

console.log('\n[3g] 中文数字的「近N天 / N天前」（2026-10-18 实测 start 为空）');
{
  // 旧实现 `(\\d{1,3})` 不认「三」，`/最近/` 分支空转后没有兜底，
  // 最终带空日期查库 —— 而 queryTickets 缺省会"不过滤"，等于拉全库。
  const cases = {
    '最近三天有多少单': ['2026-10-04', '2026-10-06'],
    '近七天有多少单': ['2026-09-30', '2026-10-06'],
    '过去十天有多少单': ['2026-09-27', '2026-10-06'],
    '最近三十天有多少单': ['2026-09-07', '2026-10-06'],
    '最近2天有多少单': ['2026-10-05', '2026-10-06'], // 阿拉伯数字仍可用
    '三天前有多少单': ['2026-10-03', '2026-10-03'],
  };
  for (const [q, [s, e]] of Object.entries(cases)) {
    const r = parseDateRange(q, NOW);
    check(r?.start === s && r?.end === e, `  ${q} → ${s}~${e}`, JSON.stringify(r));
  }
  check(parseDateRange('最近发生的告警规则是什么', NOW) === null, '  反向：不含数量的「最近…」不误判');
}

console.log('\n[3d] 「故障单」等同义说法不能被当成专名（2026-10-16 qa_log 实测）');
{
  // 事故形态：群里问「本周多少故障单」，`leftoverTerms` 只剥掉「单」,剩下「故障」，
  // 被判成"解释不了的专名" → 规则层弃权 → 走模型层。实测 7 条提问全部如此，
  // 每条 4.4~4.9s（最长 35.7s），而且模型还擅自把 status 猜成 open。
  const zh = ['本周多少故障单', '本月多少故障单', '本周的故障单有多少', '上个月有多少工单'];
  for (const q of zh) {
    check(leftoverTerms(q).length === 0, `  残余为空：${q}`, JSON.stringify(leftoverTerms(q)));
    check(parseByRule(q, NOW)?.tool === 'query_tickets', `  规则层命中：${q}`, JSON.stringify(parseByRule(q, NOW)));
  }
  const en = ['today how many fault tickets', 'how many P1 incidents today'];
  for (const q of en) {
    check(leftoverTerms(q).length === 0, `  英文残余为空：${q}`, JSON.stringify(leftoverTerms(q)));
    check(parseByRule(q, NOW)?.tool === 'query_tickets', `  英文规则层命中：${q}`, JSON.stringify(parseByRule(q, NOW)));
  }

  // 「incidents」曾被裸 `ID` 正则切成 inc|ents（/i 大小写不敏感）。
  check(!leftoverTerms('how many P1 incidents today').join('').includes('inc'), '  ID 不再切碎 incidents');
  // 反向：中文站名仍必须弃权（这条是 [3c] 的核心，不能被本次改动破坏）。
  check(leftoverTerms('蒙塞拉多昨天有多少单').join('|').includes('蒙塞拉多'), '  反向：中文站名仍被认出');
}

console.log('\n[3e] 「要单号」的中文说法（发下 / 号码）');
{
  // 2026-10-16 实测：「给我发下本周的P1故障单」list=false，只回了「P1 单 1 个」；
  // 「…的号码」更糟 —— 模型把"号码"当工单号去调 analyze_ticket，答了个空。
  for (const q of ['给我发下本周的P1故障单', '给我发下本周的P1故障单的号码', '给我发下本周的P1故障单的ID']) {
    check(parseListIntent(q) === true, `  要名单：${q}`);
    const r = parseByRule(q, NOW);
    check(r?.tool === 'query_tickets' && r.args.list === true, `  规则层带 list=true：${q}`, JSON.stringify(r));
  }
  // 反向：只要个数时不能误判成要名单（否则白白走昂贵的 drilldown）。
  check(parseListIntent('本周多少故障单') === false, '  反向：「本周多少故障单」不要名单');
  check(parseByRule('本周多少故障单', NOW)?.args.list === false, '  反向：规则层 list=false');
}

console.log('\n[3c] 中文专名不能被吃掉（A6：中文站名/区域名不带「站」字）');
{
  // 旧实现「纯中文只保留匹配 SITE_WORD 的」会把「蒙塞拉多」扔掉，
  // 于是规则层带 site:'' 答成全网 —— 答错而不报错。
  check(leftoverTerms('蒙塞拉多昨天有多少单').length > 0, '残余能认出中文站名「蒙塞拉多」', JSON.stringify(leftoverTerms('蒙塞拉多昨天有多少单')));
  check(parseByRule('蒙塞拉多昨天有多少单', NOW) === null, '  带中文站名 → 规则层弃权交模型');
  check(leftoverTerms('昨天一共有多少单').length === 0, '  反向：纯通用问法仍为空（不误伤）');
  check(parseByRule('昨天一共有多少单', NOW)?.tool === 'query_tickets', '  反向：纯通用问法仍走规则短路');
}

// 把正则常量提到块前 —— 模块顶层 ESM 的 const 在初始化前引用会抛 ReferenceError。
// 注意：跟 src/tools.js 的 COUNT_INTENT 必须严格同款（字符类用 `[a-z]*` 而不是
// `\w*`），避免测试"绿了"、线上却仍误伤 `created_by` 这种含下划线的字串。
const COUNT_INTENT_CREAT = /\bcreat[a-z]*\b/i;

console.log('\n[3b2] 拼写容错：create 的近似动词（2026-10-14 实测「creat today」落到模型层 13s）');
{
  // 14:20 那条「how many TT creat today?」实测走了模型层（13077ms）才出来——
  // 因为 COUNT_INTENT 没有 creat，而 today 单字命中要走完整规则链；
  // 加 `\bcreat\w*\b` 之后这种拼写直接归到 query_tickets，省一次模型调用。
  const c1 = parseByRule('how many TT creat today?', NOW);
  check(c1?.tool === 'query_tickets', '  「creat today」走 query_tickets（不再规则弃权）', JSON.stringify(c1));
  check(c1?.args?.severity === '', '  不携带具体级别', JSON.stringify(c1?.args));
  check(c1?.args?.start === '2026-10-06', '  日期 = today（按 NOW）', JSON.stringify(c1?.args));

  check(COUNT_INTENT_CREAT.test('creat today'), '  creat 单字命中');
  check(COUNT_INTENT_CREAT.test('how many tickets created today'), '  created 命中');
  check(!COUNT_INTENT_CREAT.test('created_by'), '  created_by 词边界不命中（防误伤）');
}

console.log('\n[3d] 站点告警意图 → query_site_alarms（2026-10-08：治「Palm Bay 有没有告警」被答成 tickets:0）');
{
  // 核心：站点是否 up / 有没有告警，是**告警事实**，不是工单数量。
  // 改造前这类问题被「有没有」拐进 query_tickets，回 tickets:0 —— 把「0 张工单」
  // 误读成「站点没告警」，答非所问且自信。
  const a1 = parseByRule('*Palm Bay* check if this site is up or not? and if have TT?', NOW);
  check(a1?.tool === 'query_site_alarms', '  *Palm Bay* up or not → query_site_alarms', JSON.stringify(a1));
  check(a1?.args?.site === 'Palm Bay', '  站名抽对 = Palm Bay', JSON.stringify(a1?.args));

  const a2 = parseByRule('check alarm for site name Palm Bay form eflow', NOW);
  check(a2?.tool === 'query_site_alarms', '  site name Palm Bay form eflow → query_site_alarms', JSON.stringify(a2));
  check(a2?.args?.site === 'Palm Bay', '  站名抽对 = Palm Bay', JSON.stringify(a2?.args));

  const a3 = parseByRule('Gbonebu site down?', NOW);
  check(a3?.tool === 'query_site_alarms' && a3?.args?.site === 'Gbonebu',
    '  Gbonebu site down? → query_site_alarms(Gbonebu)（不能把 down 当站名）', JSON.stringify(a3));

  const a4 = parseByRule('Palm Bay 有没有告警', NOW);
  check(a4?.tool === 'query_site_alarms', '  「Palm Bay 有没有告警」→ query_site_alarms（没被「有没有」拐去统计）', JSON.stringify(a4));

  // ②2026-10-24：**带告警码**的站点告警问法。
  //
  // 群里真实提问：
  //   site name :Grand Cess(3629），Alarm: 9920(Critical)，Alarm occurred 2026-10-24 10:50:29
  // 改造前这句被判给 lookup_alarm_code，只回「9920 是 Complete site down」，
  // 站名、站号、发生时间全丢 —— 用户要的是「这个站这条告警现在什么情况」。
  const b1 = parseByRule(
    'site name :Grand Cess(3629），Alarm: 9920(Critical)，Alarm occurred  2026-10-24 10:50:29', NOW);
  check(b1?.tool === 'query_site_alarms', '  带告警码的站点告警 → query_site_alarms（不再被查表抢走）',
    JSON.stringify(b1));
  check(b1?.args?.site === 'Grand Cess', '  站名抽对 = Grand Cess（不吃进 3629 与全角括号）',
    JSON.stringify(b1?.args));

  const b2 = parseByRule('Grand Cess(3629) 告警', NOW);
  check(b2?.tool === 'query_site_alarms' && b2?.args?.site === 'Grand Cess',
    '  站名后紧跟站号括号 → 站名只取 Grand Cess', JSON.stringify(b2));

  // 反向：不能误伤
  check(parseByRule('Wood camp 这个站昨天有几个单', NOW)?.tool !== 'query_site_alarms',
    '  反向：「XX站昨天有几个单」不得走告警通道');
  check(parseByRule('how many P1 tickets this month', NOW)?.tool !== 'query_site_alarms',
    '  反向：纯统计问法不得走告警通道');
  check(parseByRule('check TT202610080063', NOW)?.tool === 'analyze_ticket',
    '  反向：带单号 → analyze_ticket（告警通道让位）');
  check(parseByRule('what is alarm code 9920', NOW)?.tool === 'lookup_alarm_code',
    '  反向：**无站名**的告警码含义 → lookup_alarm_code（不是站点告警）');
}

console.log('\n[3e] sitealarms 渲染：发生时间 / 告警码 / 站号 / 派单字段（2026-10-24）');
{
  // 时间格式化：必须按**本机时区**给出可读时间。
  // 用户拿它对照「Alarm occurred 2026-10-24 10:50:29」，给 UTC 会让人误判查错了告警。
  const ts = 1792839029000;
  const d = new Date(ts);
  const pad = (x) => String(x).padStart(2, '0');
  const expect = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
                 `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  check(formatRaised(ts) === expect, '  时间戳按本地时区格式化', formatRaised(ts));
  check(formatRaised('') === '' && formatRaised(null) === '', '  缺时间返回空串（不显示 1970）');
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

  // 2026-10-08 实测：英文自然说法不触发 list，用户要名单却只拿到 3 个样例单号
  check(parseListIntent('give me the ticket IDs for P1 this month') === true, 'give me the ticket IDs → 要名单');
  check(parseListIntent('show me the tickets') === true, 'show me the tickets → 要名单');
  check(parseListIntent('which tickets are P1 this month') === true, 'which tickets → 要名单');
  check(parseListIntent('what are the P1 tickets this month') === true, 'what are the P1 tickets → 要名单');
  check(parseListIntent('list P1 tickets for this month') === true, 'list P1 tickets → 要名单');
  // 反向：纯数量问法不能误判成要名单
  check(parseListIntent('how many P1 Tickets for this month') === false, '纯 how many → 不要名单（给样例即可）');
  check(parseListIntent('how many P1 tickets today') === false, '  how many today 同理');

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

  // 2026-10-14 实测：当天只有 P2/P3/P4 三档有量、P1=0，
  // 旧渲染只列「实际非零」档，于是群里看不到「P1 0」—— 被人误读为「P1 缺一张没统计」。
  // 新规则：全量查询时永远列 P1~P4、缺的补 0，顺序固定。
  check(some.includes('P1 0,P2 47,P3 37,P4 10') || some.includes('P1 0、P'),
    '  缺档补 0、固定顺序 P1→P4', JSON.stringify(some));

  const en = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: 'P1', total: 3, open: 1, by_severity: { P1: 3 } },
    'en'
  );
  check(en.includes('P1') && !/没有/.test(en), '英文渲染不含中文', JSON.stringify(en));

  // 英文侧同样要把 P1~P4 全列出来
  const enAll = renderStats(
    { start: '2026-10-06', end: '2026-10-06', severity: '', total: 41, open: 40,
      by_severity: { P2: 11, P3: 24, P4: 6 } },
    'en'
  );
  check(enAll.includes('P1 0') && enAll.includes('P2 11') && enAll.includes('P3 24') && enAll.includes('P4 6'),
    '  英文全量也补零 + 顺序固定', JSON.stringify(enAll));

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

  // 状态混合时必须逐条标出哪个未闭环
  // 2026-10-07 实测：只说了「其中未闭环 1 个」，用户只能追问「那个单子未闭环」
  const mixed = renderStats(
    {
      start: '2026-10-01', end: '2026-10-07', severity: 'P1', status: 'all', total: 3,
      open: 1, closed: 2,
      samples: [
        { tt_no: 'TT001', site_name: 'A', status: 'Closed' },
        { tt_no: 'TT002', site_name: 'B', status: 'Waiting for FO Process' },
        { tt_no: 'TT003', site_name: 'C', status: 'Closed' },
      ],
    },
    'zh',
    false,
    true
  );
  check(mixed.includes('TT002（B）［未闭环］'), '混合状态时标出哪个未闭环', JSON.stringify(mixed));
  check(!mixed.includes('TT001（A）［未闭环］'), '  已闭环的不加标记', JSON.stringify(mixed));
  check(!mixed.includes('TT003（C）［未闭环］'), '  已闭环的不加标记（第 3 条）', JSON.stringify(mixed));

  // 全部未闭环时不该逐条标 —— 上面那句「其中未闭环 N 个」已经说尽了
  const allOpen = renderStats(
    {
      start: '2026-10-06', end: '2026-10-06', severity: 'P2', status: 'all', total: 2,
      open: 2, closed: 0,
      samples: [
        { tt_no: 'TT001', site_name: 'A', status: 'Waiting for FO Process' },
        { tt_no: 'TT002', site_name: 'B', status: 'Waiting for FO Accept' },
      ],
    },
    'zh',
    false,
    true
  );
  check(!allOpen.includes('未闭环］'), '全部未闭环时不逐条标记', JSON.stringify(allOpen));

  // 日期是兜底猜的（追问没给日期）→ 必须说明口径
  const guessed = renderStats(
    { start: '2026-10-07', end: '2026-10-07', severity: 'P1', total: 1, open: 0,
      samples: [{ tt_no: 'TT001', site_name: 'A', status: 'Closed' }] },
    'zh',
    false,
    true,
    true
  );
  check(guessed.includes('按今天算的'), '日期靠猜时要标注口径', JSON.stringify(guessed));
}

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
