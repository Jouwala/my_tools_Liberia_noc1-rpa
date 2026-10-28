#!/usr/bin/env node
/**
 * VMAX CCA 用户查询通道单测（**纯离线** —— 不联网、不查库、不调模型）。
 *   node scripts/test-vmaxcca.mjs
 *
 * 覆盖三层，每层都是曾经或容易踩的坑：
 *   [1] 号码归一  —— 现场写法五花八门（231 77 377 7115 / 77 377 7115 /
 *                    07737777115 / +231…），VMAX 只认 231 开头 12 位；
 *   [2] 意图识别  —— TEL 关键字 + 时间摘除（日期数字不能混进号码）、
 *                    查表/统计/单号通道不得被 CCA 抢走、CCA 也不得被抢；
 *   [3] 渲染      —— 需求方给的固定字段顺序、'--' 占位过滤、查无此号、
 *                    部分失败、小区/根因截断、中英成对。
 *
 * 真实数据形状取自 2026-10-25 对 /api/vmax-cca-query 的实测响应。
 */
import {
  normalizeLiberiaMsisdn,
  parseCcaEndtime,
  parseVmaxCcaIntent,
  renderCcaResult,
  extractCoverage,
  groupCausesByRule,
  fmtDateTime,
} from '../src/vmaxcca.js';
import { parseByRule } from '../src/tools.js';

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

// 固定"现在"，让时间断言不随运行时刻漂移（2026-10-25 14:03 本地时间）
const NOW = new Date(2026, 9, 25, 14, 3, 0);

console.log('='.repeat(50));
console.log('VMAX CCA 通道测试（离线）');
console.log('='.repeat(50));

/* ------------------------------ [1] 号码归一 ------------------------------ */

console.log('\n[1] 号码归一（VMAX 只认 231 开头 12 位）');
{
  check(normalizeLiberiaMsisdn('231 77 377 7115') === '231773777115', '带空格的完整号码', normalizeLiberiaMsisdn('231 77 377 7115'));
  check(normalizeLiberiaMsisdn('77 377 7115') === '231773777115', '本地 9 位 → 补 231', normalizeLiberiaMsisdn('77 377 7115'));
  check(normalizeLiberiaMsisdn('773777115') === '231773777115', '无分隔本地号 → 补 231', normalizeLiberiaMsisdn('773777115'));
  check(normalizeLiberiaMsisdn('+231773777115') === '231773777115', '+231 前缀', normalizeLiberiaMsisdn('+231773777115'));
  check(normalizeLiberiaMsisdn('0773777115') === '231773777115', '0 + 9 位 → 剥 0 补 231', normalizeLiberiaMsisdn('0773777115'));
  check(normalizeLiberiaMsisdn('00231773777115') === '231773777115', '国际冠码 00', normalizeLiberiaMsisdn('00231773777115'));
  check(normalizeLiberiaMsisdn('231773777115') === '231773777115', '已是完整格式原样', normalizeLiberiaMsisdn('231773777115'));
  check(normalizeLiberiaMsisdn('(231) 773-777-115') === '231773777115', '括号/横线混合', normalizeLiberiaMsisdn('(231) 773-777-115'));
  check(normalizeLiberiaMsisdn('12345') === '12345', '形状对不上原样透传（让上游如实说查不到）', normalizeLiberiaMsisdn('12345'));
  check(normalizeLiberiaMsisdn('') === '', '空串', normalizeLiberiaMsisdn(''));
}

/* ------------------------------ [2] 时间解析 ------------------------------ */

console.log('\n[2] 截止时间解析（窗口 = 截止时间往前 60 分钟）');
{
  const a = parseCcaEndtime('TEL 231773777115，2026-10-25 10:07', NOW);
  check(a && fmtDateTime(a.end) === '2026-10-25 10:07' && a.given, '标准「日期 时刻」', JSON.stringify(a));

  const b = parseCcaEndtime('2026-10-25 10:07:30', NOW);
  check(b && fmtDateTime(b.end) === '2026-10-25 10:07', '带秒的时刻（分钟级窗口）', JSON.stringify(b));

  const c = parseCcaEndtime('2026/10/25 10:07', NOW);
  check(c && fmtDateTime(c.end) === '2026-10-25 10:07', '斜杠日期', JSON.stringify(c));

  const d = parseCcaEndtime('2026年10月25日 10:07', NOW);
  check(d && fmtDateTime(d.end) === '2026-10-25 10:07', '中文年月日', JSON.stringify(d));

  const e = parseCcaEndtime('2026-10-25 10：07', NOW);
  check(e && fmtDateTime(e.end) === '2026-10-25 10:07', '全角冒号', JSON.stringify(e));

  const f = parseCcaEndtime('TEL 773777115 10:07', NOW);
  check(f && fmtDateTime(f.end) === '2026-10-25 10:07' && f.given, '仅时刻 → 当天', JSON.stringify(f));

  const g = parseCcaEndtime('TEL 773777115 2026-10-24', NOW);
  check(g && fmtDateTime(g.end) === '2026-10-24 23:59', '仅日期 → 当天 23:59（CCA 日界）', JSON.stringify(g));

  check(parseCcaEndtime('今天有p1的单子吗', NOW) === null, '无时间信号 → null');
  check(parseCcaEndtime('', NOW) === null, '空串 → null');
}

/* ------------------------------ [3] 意图识别 ------------------------------ */

console.log('\n[3] 意图识别（TEL 是约定信号；不能误伤别的通道）');
{
  const a = parseVmaxCcaIntent('TEL 231773777115，2026-10-25 10:07', NOW);
  check(a && a.msisdn === '231773777115' && a.endText === '2026-10-25 10:07', '需求原例：号码+截止时间', JSON.stringify(a));
  check(a && a.startText === '2026-10-25 09:07', '  窗口起点 = 截止时间 - 60 分钟', a?.startText);
  check(a && a.timeGiven === true, '  timeGiven=true（不是猜的）', String(a?.timeGiven));

  const b = parseVmaxCcaIntent('TEL 231 77 377 7115', NOW);
  check(b && b.msisdn === '231773777115' && b.timeGiven === false, '带空格的完整号码、无时间 → 按当前时刻', JSON.stringify(b));
  check(b && b.endText === '2026-10-25 14:03' && b.startText === '2026-10-25 13:03', '  默认窗口 = 当前时刻往前 60 分钟', `${b?.startText}~${b?.endText}`);

  const c = parseVmaxCcaIntent('TEL 77 377 7115', NOW);
  check(c && c.msisdn === '231773777115', '本地格式 → 归一成 231 开头 12 位', c?.msisdn);

  const d = parseVmaxCcaIntent('tel: 773777115 10:07', NOW);
  check(d && d.msisdn === '231773777115' && d.endText === '2026-10-25 10:07', '小写 tel: + 仅时刻', JSON.stringify(d));

  const e = parseVmaxCcaIntent('MSISDN 231773777115 2026-10-25 10:07', NOW);
  check(e && e.msisdn === '231773777115' && e.endText === '2026-10-25 10:07', 'MSISDN 关键字同权', JSON.stringify(e));

  const f = parseVmaxCcaIntent('TEL 231773777115 2026-10-25 10:07', NOW);
  check(f && f.msisdn === '231773777115', '空格分隔（日期数字不能混进号码）', f?.msisdn);

  check(parseVmaxCcaIntent('分析TT单TT202609150073', NOW) === null, 'TT 单号不是 CCA');
  check(parseVmaxCcaIntent('告警码 9920 是什么意思', NOW) === null, '查表问法不是 CCA');
  check(parseVmaxCcaIntent('今天有p1的单子吗', NOW) === null, '统计问法不是 CCA');
  check(parseVmaxCcaIntent('773777115 的根因是什么', NOW) === null, '无 TEL 关键字的裸号码不抢（交模型层判）');
  check(parseVmaxCcaIntent('TEL 123', NOW) === null, 'TEL + 位数不够 → 不触发（避免把短数字当号码）');
  check(parseVmaxCcaIntent('', NOW) === null, '空串 → null');
}

/* --------------------------- [4] 路由集成（tools.js） --------------------------- */

console.log('\n[4] 路由集成（必须在查表意图之前截住，也不能抢别人的）');
{
  const a = parseByRule('TEL 231773777115，2026-10-25 10:07', NOW);
  check(a && a.tool === 'query_vmax_cca', '需求原例 → query_vmax_cca（不是 lookup_alarm_code）', JSON.stringify(a));
  check(a && a.args.msisdn === '231773777115', '  参数带归一后的号码', JSON.stringify(a?.args));

  const b = parseByRule('告警码 198094422 会被压缩成什么', NOW);
  check(b === null || b.tool === 'lookup_compress' || b.tool === 'search_knowledge', '压缩问法不受影响（仍走查表）', JSON.stringify(b));

  const c = parseByRule('今天有p1的单子吗', NOW);
  check(c && c.tool === 'query_tickets', '统计问法不受影响', JSON.stringify(c));

  const d = parseByRule('分析TT单TT202609150073', NOW);
  check(d && d.tool === 'analyze_ticket', '单号仍最优先', JSON.stringify(d));

  const e = parseByRule('Palm Bay check if this site is up or not', NOW);
  check(e && e.tool === 'query_site_alarms', '站点告警问法不受影响', JSON.stringify(e));
}

/* ------------------------------ [5] 渲染 ------------------------------ */

console.log('\n[5] 渲染（固定字段顺序 + 占位过滤 + 中英成对）');

// 形状取自 2026-10-25 实测响应（值已替换，只保留结构与占位形态）
const MOCK = {
  msisdn: '231773777115',
  found: true,
  user: { msisdn: '231773777115', imsi_arr: ['618070109668304'] },
  terminal: {
    imei_arr: ['350506404470501'], modelname_arr: ['--'], modelvendor_arr: ['--'],
    country_name: '--', network_arr: ['--'], flag_arr: [['--', '--']], msisdn: '--',
    modelos_arr: ['--'], operator: '--',
  },
  window: { starttime: '2026-10-24 10:07:00', endtime: '2026-10-24 11:07:00' },
  flow: { total_flux: '0.01MB', apps: [] },
  cells: {
    cells: [
      { cellname: 'Methodist Compound-X1', celllat: 6.29356, celllon: -10.78105 },
      { cellname: 'Methodist Compound-X2', celllat: 6.29401, celllon: -10.78217 },
    ],
    cell_kpi: {},
  },
  causes: [
    { rule_name: 'Downlink weak coverage(cell)', object_name: 'Methodist Compound-X1',
      confidence: 95, solution: '1.Adjusting a tilt of the Serving Cell;2.Check the feeder.' },
    { rule_name: 'Uplink interference(cell)', object_name: 'Methodist Compound-X2',
      confidence: 60, solution: '' },
  ],
  failures: [],
  msg: 'SUCCESS',
};

{
  const zh = renderCcaResult(MOCK, 'zh', {
    msisdn: '231773777115', timeGiven: true, nowText: '', win: { start: '2026-10-24 10:07', end: '2026-10-24 11:07' },
  });
  check(zh.answered === true, '命中 → answered=true');
  const labels = ['XDR CCA：', 'MSISDN: ', 'IMSI: ', 'IMEI: ', 'Model: ', 'Total traffic: ',
    'Track Cells: ', 'Cell Name: ', 'Lat, Lon: ', 'Coverage KPI', 'Root Cause Analysis'];
  let order = -1;
  let okOrder = true;
  for (const lb of labels) {
    const i = zh.text.indexOf(lb);
    if (i < 0 || i < order) { okOrder = false; break; }
    order = i;
  }
  check(okOrder, '字段齐全且按需求模板顺序出现', zh.text);
  check(zh.text.includes('IMSI: 618070109668304'), 'IMSI 取值');
  check(zh.text.includes('IMEI: 350506404470501'), 'IMEI 取值');
  check(zh.text.includes('Model: —'), '终端占位 -- 显示为 —（不是 --）', zh.text.match(/Model:.*/)?.[0]);
  check(zh.text.includes('Total traffic: 0.01MB'), '流量取值');
  check(zh.text.includes('Track Cells: 2'), '小区计数');
  check(zh.text.includes('Methodist Compound-X1'), 'Cell Name 列出');
  check(zh.text.includes('(6.29356, -10.78105)'), 'Lat, Lon 坐标');
  check(zh.text.includes('[95%] Downlink weak coverage(cell) — Methodist Compound-X1'), '根因：置信度+规则+对象');
  check(zh.text.includes('建议：1.Adjusting a tilt'), '首条根因带处理建议');
  check(!zh.text.includes('（未给截止时间'), '用户给了时间就不出现兜底说明');
  check(zh.text.includes('来源：VMAX CCA'), '带来源行');
  check(zh.text.includes('Coverage KPI: —'), '无覆盖 KPI → 空态（不是 0）', zh.text.match(/Coverage KPI.*/)?.[0]);

  // 未给时间：必须说清是按当前时刻算的（猜的日期不能装成用户给的）
  const zh2 = renderCcaResult(MOCK, 'zh', {
    msisdn: '231773777115', timeGiven: false, nowText: '2026-10-25 14:03',
    win: { start: '2026-10-25 13:03', end: '2026-10-25 14:03' },
  });
  check(zh2.text.includes('（未给截止时间，按 2026-10-25 14:03 往前 60 分钟查询）'), '未给时间 → 附兜底说明', zh2.text);

  // 英文：界面说明句必须是英文（字段标签是领域标识符，两种语言一致）
  const en = renderCcaResult(MOCK, 'en', {
    msisdn: '231773777115', timeGiven: true, nowText: '', win: { start: '2026-10-24 10:07', end: '2026-10-24 11:07' },
  });
  check(en.answered === true && en.text.includes('XDR CCA: 231773777115'), '英文抬头');
  check(en.text.includes('(no cause records in this window)') === false, '有根因时不出空态文案');
  check(en.text.includes('Source: VMAX CCA'), '英文来源行');
}

console.log('\n[5b] 渲染：空态与部分失败');
{
  // 查无此号：是明确结论（answered=true 才能进会话历史供追问）
  const nf = renderCcaResult({ found: false, msg: 'IMSI is not found', msisdn: '231773777115' }, 'zh', { msisdn: '231773777115' });
  check(nf.answered === true && nf.text.includes('查不到号码 231773777115'), '查无此号 → 明确结论');
  check(nf.text.includes('IMSI is not found'), '  带上游说明');
  const nfEn = renderCcaResult({ found: false, msg: 'IMSI is not found' }, 'en', { msisdn: '231773777115' });
  check(nfEn.text.includes('was not found in VMAX CCA'), '  英文版成对');

  // flow/cells/causes 全空（业务正常）+ causes 子查询失败
  const empty = { ...MOCK, flow: null, cells: null, causes: null, failures: ['causes: HTTP timeout'] };
  const r = renderCcaResult(empty, 'zh', { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } });
  check(r.text.includes('Total traffic: —'), '无流量 → —');
  check(r.text.includes('Track Cells: —'), '无小区数据 → —（不显示 0）', r.text.match(/Track Cells.*/)?.[0]);
  check(r.text.includes('Cell Name: —') && r.text.includes('Lat, Lon: —'), '  小区名/坐标同步空态');
  check(r.text.includes('根因子查询失败'), 'causes 失败 → 如实说明（不是「无记录」）', r.text.match(/Root Cause Analysis.*/)?.[0]);
  check(r.text.includes('⚠ 部分子查询失败'), '  failures 单独成行');

  const noCause = { ...MOCK, causes: null, failures: [] };
  const r2 = renderCcaResult(noCause, 'zh', { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } });
  check(r2.text.includes('该窗口无根因记录'), '无根因记录 → 空态文案（与失败分开）');

  // 小区超上限截断（实测一天 41 个小区，全列会刷屏）
  const many = { ...MOCK, cells: { cells: Array.from({ length: 12 }, (_, i) => ({ cellname: `Cell-${i}` })), cell_kpi: {} } };
  const r3 = renderCcaResult(many, 'zh', { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } });
  check((r3.text.match(/Cell-/g) || []).length === 8, '小区列表封顶 8 个', String((r3.text.match(/Cell-/g) || []).length));
  check(r3.text.includes('还有 4 个小区未列出'), '  截断计数如实告知');
}

/* ------------------- [6] 覆盖 KPI（RSRP/SINR/RSRQ） ------------------- */
// 2026-10-27 需求：返图信息里补上覆盖类读数。
// 形状取自 2026-10-26 对真号 231773777115 的实测响应（cellKpi 的 ppc/ppb 码
// 已由 my_app 侧映射成英文名，这里保留映射后的名字）。
console.log('\n[6] 覆盖 KPI 提取与渲染');

const COV_CELLS = {
  cells: [
    { cellname: 'Methodist Compound-X1', cell: '461807001031977', cellkey: '4031_41', rat: 6 },
    { cellname: 'Methodist Compound-S1', cell: '461807001031937', cellkey: '4031_1', rat: 6 },
    // 2G 小区：只有信令类 KPI（无 RSRP/SINR/RSRQ），不该进覆盖段
    { cellname: 'Methodist Compound-S2', cell: '3618071000630312', cellkey: '103_30312', rat: 1 },
  ],
  cell_kpi: {
    // 按小区 ID 形态
    '461807001031977': [
      { code: 'ppc1208204003_42', name: 'Average RSRP(dBm)', value: -92.31 },
      { code: 'ppc1208204008_42', name: 'Average Uplink SINR(LTE)(dB)', value: 19.27 },
      { code: 'ppc1208204036_42', name: 'Average RSRQ(dB)', value: -13.25 },
      { code: 'ppc1208204005_42', name: 'Downlink weak coverage ratio(LTE)(%)', value: 6.48 },
      { code: 'prb_dl_avail_rate_42', name: 'prb_dl_avail_rate_42', value: 14.01 },
    ],
    // 按 cellkey 形态（实测上游两种键混用）
    '4031_1': [
      { code: 'ppc1208204003_42', name: 'Average RSRP(dBm)', value: -92.26 },
      { code: 'ppc1208204008_42', name: 'Average Uplink SINR(LTE)(dB)', value: 20.42 },
      { code: 'ppc1208204036_42', name: 'Average RSRQ(dB)', value: -13.38 },
    ],
    // 2G 小区：信令类，无覆盖指标
    '3618071000630312': [
      { code: 'ppc300101005_23', name: 'PDP Creation Successful Rate(%)', value: 87.61 },
    ],
  },
};

{
  const cov = extractCoverage(COV_CELLS);
  check(cov.length === 2, '只有无线小区进覆盖段（2G 小区被排除）', String(cov.length));
  const x1 = cov.find((c) => c.cellname === 'Methodist Compound-X1');
  check(!!x1, '按小区 ID 取到 KPI 的小区在列表里');
  check(x1?.kpis.find((k) => k.key === 'rsrp')?.value === '-92.31', 'RSRP 取值', JSON.stringify(x1?.kpis));
  check(x1?.kpis.find((k) => k.key === 'sinr')?.value === '19.27', 'SINR 取值');
  check(x1?.kpis.find((k) => k.key === 'rsrq')?.value === '-13.25', 'RSRQ 取值');
  check(x1?.kpis.find((k) => k.key === 'dlCov')?.value === '6.48', '下行弱覆盖占比取值');
  const s1 = cov.find((c) => c.cellname === 'Methodist Compound-S1');
  check(s1?.kpis.find((k) => k.key === 'rsrp')?.value === '-92.26', '按 cellkey 取到 KPI（两种键混用）');

  // 缺值必须是 null（缺 ≠ 0）：上游用 '--' 占位
  const missing = extractCoverage({
    cells: [{ cellname: 'C1', cell: 'x1', cellkey: 'k1' }],
    cell_kpi: { x1: [{ code: 'c1', name: 'Average RSRP(dBm)', value: '--' }] },
  });
  check(missing.length === 0, "KPI 值为 '--' → 该小区不进覆盖段（不当成 0）", JSON.stringify(missing));

  // 渲染层：覆盖段要出现在回复里，且在 Lat/Lon 之后、根因之前
  const withCov = renderCcaResult(
    { ...MOCK, cells: COV_CELLS },
    'zh',
    { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } }
  );
  check(withCov.text.includes('Coverage KPI（RSRP/SINR/RSRQ）：'), '覆盖段标题');
  check(withCov.text.includes('RSRP -92.31dBm'), '覆盖段列出 RSRP 读数', withCov.text.match(/Coverage KPI[\s\S]{0,200}/)?.[0]);
  check(withCov.text.includes('SINR 19.27dB'), '  SINR 读数');
  check(withCov.text.includes('RSRQ -13.25dB'), '  RSRQ 读数');
  const covIdx = withCov.text.indexOf('Coverage KPI');
  const causeIdx = withCov.text.indexOf('Root Cause Analysis');
  check(covIdx > 0 && covIdx < causeIdx, '覆盖段在根因段之前');
}

/* ------------------- [7] Cause Rule 归并全列 ------------------- */
// 2026-10-27 需求：根因改为「按 Cause Rule 都显示」。
// 实测一天 58 条明细 → 23 条规则；原先只取前 3 条。
console.log('\n[7] Cause Rule 归并（全部列出，不再只取前 3 条）');

{
  const many = Array.from({ length: 12 }, (_, i) => ({
    rule_name: i < 6 ? 'High RSRQ interference(cell)' : `Rule-${i}`,
    object_name: i < 6 ? `Cell-${i}` : `Cell-${i}`,
    confidence: i < 6 ? 90 : 50,
    solution: i === 0 ? 'Downlink interference troubleshooting' : '',
  }));
  const groups = groupCausesByRule(many);
  check(groups.length === 7, '12 条明细归并成 7 条规则', String(groups.length));
  const rq = groups.find((g) => g.rule === 'High RSRQ interference(cell)');
  check(rq?.count === 6, '  命中条数累计', String(rq?.count));
  check(rq?.objectCount === 6, '  命中对象去重计数', String(rq?.objectCount));
  check(rq?.confidence === 90, '  置信度取组内最高');

  // 渲染：全部规则都列出（不再只前 3 条）
  const r = renderCcaResult(
    { ...MOCK, causes: many },
    'zh',
    { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } }
  );
  check(r.text.includes('Root Cause Analysis（按 Cause Rule 归并）：'), '根因段标题说明按规则归并');
  check(r.text.includes('Rule-11'), '第 12 条规则也列出（不是只取前 3 条）', r.text);
  check((r.text.match(/^\d+\. \[/gm) || []).length === 7, '  列出 7 条规则', String((r.text.match(/^\d+\. \[/gm) || []).length));
  check(r.text.includes('建议：Downlink interference troubleshooting'), '  首条规则带处理建议');
  check(r.text.includes('my_app「VMAX 用户查询」页'), '  指向 my_app 看其余规则的完整明细');

  // 英文版成对
  const rEn = renderCcaResult(
    { ...MOCK, causes: many },
    'en',
    { msisdn: '231773777115', timeGiven: true, win: { start: 'a', end: 'b' } }
  );
  check(rEn.text.includes('Root Cause Analysis (grouped by Cause Rule):'), '英文根因段标题');
  check(rEn.text.includes('Rule-11'), '  英文版同样全列');
  check(rEn.text.includes('my_app "VMAX User Query" page'), '  英文版指向 my_app');
}

/* ------------------------------- 收尾 ------------------------------- */

console.log('\n' + '='.repeat(50));
console.log(`结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
