/**
 * 数据域工具（电源 / 历史告警 / WO / 可用率）的黄金用例。
 *
 * 覆盖三层：
 *   ① 规则层路由 —— 该走哪个工具、走哪个参数；
 *   ② 渲染层 —— 输出格式、空结果、0/1 字段的口径；
 *   ③ 不误伤 —— 既有通道（TT 统计 / 实时告警 / 站点属性 / 查表）不被新意图抢走。
 *
 * 跑法：node scripts/test-datadomains.mjs
 */
import { parseByRule } from '../src/tools.js';
import { renderDataDomain } from '../src/datadomains.js';
import { renderDataQuery } from '../src/dataquery.js';

let pass = 0;
let fail = 0;

function check(cond, label, detail) {
  if (cond) {
    pass++;
  } else {
    fail++;
    console.log(`  ✗ ${label}`);
    if (detail !== undefined) {
      console.log(`      ${String(detail).slice(0, 300).replace(/\n/g, ' | ')}`);
    }
  }
}

console.log('\n[数据域] 规则层路由（四个精确域 + NL2SQL 兜底）');

// —— 电源 ——
const p1 = parseByRule('Wood Camp 电源状态怎么样');
check(p1?.tool === 'query_power', '「电源状态怎么样」→ query_power', JSON.stringify(p1));
check(p1?.args?.site === 'Wood Camp', '电源：站名抽对', JSON.stringify(p1?.args));

check(parseByRule('Wood Camp 电量还剩多少')?.tool === 'query_power',
  '「电量还剩多少」→ query_power');
check(parseByRule('Wood Camp 发电机启动了吗')?.tool === 'query_power',
  '「发电机启动了吗」→ query_power');
check(parseByRule('what is the power status of Wood Camp')?.tool === 'query_power',
  '英文「power status」→ query_power');

// —— 历史告警（必须与实时告警分开）——
const h1 = parseByRule('Wood Camp 最近有什么告警');
check(h1?.tool === 'query_alarm_history', '「最近有什么告警」→ query_alarm_history', JSON.stringify(h1));
check(h1?.args?.days === 7, '历史告警：默认回看 7 天', JSON.stringify(h1?.args));

const h2 = parseByRule('Wood Camp 最近30天有什么告警');
check(h2?.args?.days === 30, '「最近30天」→ days=30', JSON.stringify(h2?.args));

const h3 = parseByRule('Wood Camp 上周有什么告警');
check(h3?.tool === 'query_alarm_history', '「上周有什么告警」→ query_alarm_history', JSON.stringify(h3));

// ⚠️ 最容易错的一条：「现在有没有告警」是**实时**，不能走历史表。
const a1 = parseByRule('Wood Camp 现在有没有告警');
check(a1?.tool === 'query_site_alarms',
  '「现在有没有告警」→ 实时告警通道（不是历史）', JSON.stringify(a1));

// —— WO ——
check(parseByRule('Wood Camp 未闭环的工单有哪些')?.tool === 'query_wo',
  '「未闭环的工单有哪些」→ query_wo');
check(parseByRule('Wood Camp 有几个WO')?.tool === 'query_wo',
  '「有几个WO」→ query_wo');
const w1 = parseByRule('WO202610120018 什么状态');
check(w1?.tool === 'query_wo', 'WO 单号 → query_wo（不是 analyze_ticket）', JSON.stringify(w1));
check(w1?.args?.wo_no === 'WO202610120018', 'WO：单号抽对', JSON.stringify(w1?.args));

// —— 可用率 ——
const av1 = parseByRule('Wood Camp 这个月可用率多少');
check(av1?.tool === 'query_site_availability', '「可用率多少」→ query_site_availability', JSON.stringify(av1));
const av2 = parseByRule('Lofa Bridge 10月的可用率');
check(av2?.args?.month === '2026-10', '「10月」→ month=2026-10', JSON.stringify(av2?.args));

// —— 任务管理（my_app 自身定时任务）——
//
// ⚠️ 这组用例守的是 2026-11-04 的真实故障：
// 「my_app的task manager现在又多少任务成功，多少失败」原本走 NL2SQL，
// 模型把 "my_app" 当成要过滤的字面量（task_name ILIKE '%my_app%'），
// 而任务名是中文的 → 命中 0 行 → 答「没有匹配到任何记录」。
// 库里明明有 83 个任务。**答错而不报错**，是最危险的一类。
const tm1 = parseByRule('my_app的task manager现在又多少任务成功，多少失败');
check(tm1?.tool === 'query_task_stats',
  '「my_app的task manager有多少任务成功失败」→ query_task_stats（不是 query_data）', JSON.stringify(tm1));

// 空格变体：2026-11-04 那次失败的正是**带空格**的形态
const tm2 = parseByRule('my_app 的 task manager 现在有多少任务成功，多少失败');
check(tm2?.tool === 'query_task_stats',
  '带空格变体同样 → query_task_stats（NL2SQL 路径已被规则层截断）', JSON.stringify(tm2));

check(parseByRule('my_app task manager 哪些任务失败了')?.tool === 'query_task_stats',
  '「哪些任务失败了」→ query_task_stats');
check(parseByRule('任务管理现在有多少任务失败')?.tool === 'query_task_stats',
  '中文「任务管理」→ query_task_stats');
const tm3 = parseByRule('定时任务最近30天有多少失败');
check(tm3?.tool === 'query_task_stats', '「定时任务」→ query_task_stats', JSON.stringify(tm3));
check(tm3?.args?.days === 30, '任务管理：「最近30天」→ days=30', JSON.stringify(tm3?.args));

// ⚠️ 不能被统计通道抢走：含「多少」却一条工单都不是
check(tm1?.tool !== 'query_tickets',
  '任务管理不被工单统计通道抢走（否则答「0 单」）', JSON.stringify(tm1));

// —— 不误伤：既有通道必须保持原样 ——
const tt = parseByRule('TT202609150073 什么状态');
check(tt?.tool === 'analyze_ticket', 'TT 单号仍走 analyze_ticket（没被 WO 抢走）', JSON.stringify(tt));

const attr = parseByRule('站点 lofa bridge 是 VIP 站点吗');
check(attr?.tool === 'query_site_attribute', '站点属性仍走 query_site_attribute', JSON.stringify(attr));

const lvl = parseByRule('VIP 站点是什么级别');
check(lvl === null || lvl.tool !== 'query_site_attribute',
  '「VIP 站点是什么级别」是规则题，不被属性通道抢走', JSON.stringify(lvl));

// 电源问法里带「告警」时，不该被电源通道抢（那是问告警）
const mixed = parseByRule('Wood Camp 电源告警是什么');
check(mixed === null || mixed.tool !== 'query_power',
  '「电源告警」含告警语义，不走电源通道', JSON.stringify(mixed));

console.log('\n[数据域] 渲染层');

// 电源：0/1 字段要转成「是/否」，空值跳过
const pw = renderDataDomain('power', {
  ok: true,
  rows: [{
    name: 'Wood Camp', connectivity: 'On Grid', load_current: 12.5,
    battery_soc: 87.0, generator_on: '0', grid_on: '1', snap_time: '2026-11-03 10:00:00',
  }],
}, 'zh', 'Wood Camp');
check(pw.includes('Wood Camp'), '电源：标题含站名', pw);
check(pw.includes('供电状态：On Grid'), '电源：显示供电状态', pw);
check(pw.includes('发电机：否'), '电源：0/1 转成「否」', pw);
check(pw.includes('市电：是'), '电源：0/1 转成「是」', pw);
check(pw.includes('实时'), '电源：标注来源为实时', pw);

// 历史告警
const al = renderDataDomain('alarm-history', {
  ok: true,
  rows: [{
    site_name: 'Wood camp', raised: '2026-11-02 06:29:40', severity_name: 'Critical',
    alarmcode: '99933', alarm_title: 'SITE OUTAGE DUE TO POWER OFF', tt_id: 'TT2026...',
  }],
}, 'zh', 'Wood Camp');
check(al.includes('Critical'), '历史告警：显示级别', al);
check(al.includes('99933'), '历史告警：显示告警码', al);
check(al.includes('2026-11-02'), '历史告警：显示时间', al);

// WO
const wo = renderDataDomain('wo', {
  ok: true,
  rows: [{
    wo_no: 'WO202610120018', tt_no: 'TT202610120035', status: 'Closed',
    severity: 'P4', title: '3G CELL DOWN', created_time: '2026-10-12 10:19:59',
  }],
}, 'zh', 'Wood Camp');
check(wo.includes('WO202610120018'), 'WO：显示 WO 号', wo);
check(wo.includes('Closed'), 'WO：显示状态', wo);

// 可用率：百分比要算对
const av = renderDataDomain('site-availability', {
  ok: true, found: true, month: '2026-10',
  avg_by_tech: { G: 0.940494, L: 0.993313 },
  by_tech: { G: 30, L: 30 },
  days: { '2026-10-01': { G: 0.95, L: 0.99 } },
}, 'zh', 'Wood Camp');
check(av.includes('94.05%'), '可用率：2G 百分比正确', av);
check(av.includes('99.33%'), '可用率：4G 百分比正确', av);
check(av.includes('2026-10-01'), '可用率：逐日明细', av);

// 任务管理：口径与页面一致，失败明细与根因聚类都要出来
const ts = renderDataDomain('task-stats', {
  ok: true, total: 83,
  counts: { running: 3, success: 76, failed: 2, disabled: 4, unknown: 0 },
  failed_now: [
    { task_id: 'eflow_sync', name: 'eFlow 数据同步', status: 'failed',
      last_error: 'timeout: 连接超时\n堆栈...', last_started_at: '2026-11-04T10:00:00',
      will_retry: true, next_retry_at: '2026-11-04T11:00:00' },
  ],
  failed_now_total: 2,
  failure_clusters: [
    { status: 'active', count: 12, error_first_line: 'timeout: Command ...', task_ids: ['a'] },
  ],
  source: 'live',
}, 'zh');
check(ts.includes('注册任务总数：83'), '任务管理：显示注册任务总数', ts);
check(ts.includes('成功：76'), '任务管理：显示成功数', ts);
check(ts.includes('失败：2'), '任务管理：显示失败数', ts);
check(ts.includes('运行中：3'), '任务管理：显示运行中数', ts);
check(ts.includes('已停用：4'), '任务管理：显示已停用数', ts);
check(ts.includes('eFlow 数据同步'), '任务管理：列出失败任务名', ts);
check(ts.includes('timeout: 连接超时'), '任务管理：失败原因取 error 首行', ts);
check(ts.includes('将自动重试'), '任务管理：标注会自动重试', ts);
check(ts.includes('近期失败根因聚类'), '任务管理：显示失败根因聚类', ts);

// 没有失败任务时如实说，而不是留空
const tsNone = renderDataDomain('task-stats', {
  ok: true, total: 83,
  counts: { running: 0, success: 79, failed: 0, disabled: 4, unknown: 0 },
  failed_now: [], failed_now_total: 0, failure_clusters: [],
}, 'zh');
check(tsNone.includes('当前没有失败的任务'), '任务管理：无失败时如实说明', tsNone);
check(tsNone.includes('失败：0'), '任务管理：无失败时失败数为 0', tsNone);

// 英文渲染
const tsEn = renderDataDomain('task-stats', {
  ok: true, total: 83,
  counts: { running: 0, success: 79, failed: 0, disabled: 4, unknown: 0 },
  failed_now: [], failed_now_total: 0, failure_clusters: [],
}, 'en');
check(tsEn.includes('succeeded'), '任务管理：英文渲染', tsEn);

// 空结果：要说「没有记录」，而不是报错
const empty = renderDataDomain('alarm-history', { ok: true, count: 0, rows: [] }, 'zh', 'ZZZ');
check(empty.includes('没有记录') || empty.includes('查不到'),
  '空结果：如实说没有记录', empty);

// 接口错误：要说出错在哪
const err = renderDataDomain('power', { ok: false, message: '表不存在' }, 'zh', 'X');
check(err.includes('表不存在'), '接口错误：把原因带出来', err);

console.log('\n[数据域] NL2SQL 渲染');

// 有结果：列名要美化 + 附 SQL
const dq = renderDataQuery({
  sql: 'SELECT 1', executed_sql: 'SELECT count(*) FROM history_alarm',
  columns: ['alarm_count'], rows: [{ alarm_count: 42 }], row_count: 1,
}, 'zh', 'OWU');
check(dq.includes('42'), 'NL2SQL：结果值正确', dq);
check(dq.includes('Alarm Count'), 'NL2SQL：列名美化', dq);
check(dq.includes('SELECT count(*)'), 'NL2SQL：附上实际执行的 SQL', dq);
check(dq.includes('OWU'), 'NL2SQL：标注取数通道', dq);

// 空结果
const dqEmpty = renderDataQuery({
  sql: 'SELECT 1', executed_sql: 'SELECT ...', columns: ['a'], rows: [], row_count: 0,
}, 'zh', 'OWU');
check(dqEmpty.includes('没有匹配') || dqEmpty.includes('没有'),
  'NL2SQL：空结果如实说', dqEmpty);
// ⚠️ 空结果**不等于**「没有这条数据」——也可能是过滤条件写窄了。
// 2026-11-04 真实故障：模型拿系统名 my_app 当数据值过滤，3 万多行被自己滤成 0 行，
// 机器人却回答「没有匹配到任何记录」——把「查错了」包装成了「确定没有」。
check(/过窄|换.*条件/.test(dqEmpty),
  'NL2SQL：空结果提示「过滤条件可能过窄」，不把查错说成确定没有', dqEmpty);

// 报错
const dqErr = renderDataQuery({ detail: '缺少 API key' }, 'zh', '');
check(dqErr.includes('缺少 API key'), 'NL2SQL：把服务端错误带出来', dqErr);

console.log(`\n通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
