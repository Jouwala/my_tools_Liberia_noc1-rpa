#!/usr/bin/env node
/**
 * 库房查询工具单测（**纯离线**，不联网不调模型）。
 *   node scripts/test-warehouse.mjs
 *
 * 覆盖库房通道的两条腿：
 *   ① **意图解析**：库房问法要被 parseByRule 认成 query_warehouse，
 *      且不能抢走工单/查表问法（回归保护）；
 *   ② **口径 vs 事实的分流**：问「有哪些类型/怎么算」走知识库（RAG），
 *      问「多少/状态」走实时工具 —— 这是 2026-10-27 实测踩出来的：
 *      口径问题被工具吃掉，答成「入库单 312 张」而不是「有哪些类型」。
 *
 * 需要真实库房数据库的用例（取数与渲染）会自动跳过并说明原因，
 * 不让「库没同步」变成一条看不懂的失败。
 */
import { CONFIG } from '../src/config.js';
import { parseByRule } from '../src/tools.js';
import { parseWarehouseIntent, extractMaterialKeyword, isWarehouseKnowledgeQuestion } from '../src/warehousetool.js';
import { extractSpTicketNos } from '../src/warehousesource.js';

const ORIG = CONFIG.toolsEnabled;
CONFIG.toolsEnabled = false;

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

const NOW = new Date(2026, 9, 27);

console.log('='.repeat(50));
console.log('库房查询工具测试（离线）');
console.log('='.repeat(50));

/* --------------------------- 1. 单号抽取 --------------------------- */

console.log('\n[1] 库房单号抽取（SPIB/SPOB）');
{
  check(
    extractSpTicketNos('SPIB202610220006 这个单怎么样').includes('SPIB202610220006'),
    '入库单号完整抽出（不截断前缀）',
    `实得：${JSON.stringify(extractSpTicketNos('SPIB202610220006 这个单怎么样'))}`
  );
  check(
    extractSpTicketNos('SPOB202609150003 状态').includes('SPOB202609150003'),
    '出库单号完整抽出'
  );
  check(extractSpTicketNos('今天有几个 P1').length === 0, '普通问法不误抽单号');
  // 告警码不是库房单号 —— 两者都长数字，极易混淆
  check(
    !extractSpTicketNos('告警码 198094422 会被压缩成什么').length,
    '告警码不会被当成库房单号'
  );
}

/* --------------------------- 2. 物料关键字 --------------------------- */

console.log('\n[2] 物料关键字抽取');
{
  check(extractMaterialKeyword('物料 033030100282 还有多少库存') === '033030100282', '「物料 XXX」');
  check(extractMaterialKeyword('material no 033030100282 stock') === '033030100282', '「material no XXX」');
  check(extractMaterialKeyword('备件 NWA-061137 库存') === 'NWA-061137', '「备件 XXX」');
  check(extractMaterialKeyword('SFP 在库多少') === 'SFP', '裸名称兜底「SFP」');
  // 库房话题词不能被当成物料名
  check(
    extractMaterialKeyword('warehouse stock status') === '',
    '库房话题词（warehouse）不会被当成物料名'
  );
  check(extractMaterialKeyword('库房现在什么情况') === '', '纯总览问法不抽物料');
}

/* --------------------------- 3. 意图解析 --------------------------- */

console.log('\n[3] 库房意图解析');
{
  const t = (q) => parseWarehouseIntent(q);

  check(t('库房现在什么情况')?.args.kind === 'overview', '总览问法 → overview');
  check(t('各仓库存还有多少')?.args.kind === 'overview', '库存数量问法 → overview');
  check(t('物料 033030100282 还有多少库存')?.args.kind === 'material', '物料问法 → material');
  check(
    t('物料 033030100282 还有多少库存')?.args.keyword === '033030100282',
    '物料问法带出 keyword'
  );
  check(t('SPIB202610220006 这个入库单什么状态')?.args.kind === 'ticket', '入库单号 → ticket');
  check(
    t('SPIB202610220006 这个入库单什么状态')?.args.ticket_no === 'SPIB202610220006',
    '入库单号带出完整单号'
  );
  // 单号本身就是强信号，句子里不需要出现「库房」
  check(t('SPOB202609150003 怎么样')?.args.kind === 'ticket', '只给单号也能认成 ticket');
  check(t('今天有几个 P1') === null, '工单问法不认成库房');
  check(t('告警码 9920 是什么意思') === null, '查表问法不认成库房');
}

/* --------------------------- 4. 口径 vs 事实 --------------------------- */

console.log('\n[4] 口径问题走知识库，事实问题走工具（2026-10-27 实测的坑）');
{
  const knowledgeQs = [
    '库房有哪些单据类型',
    '库房库存表怎么对账 Gap 怎么算',
    '出库类型有哪些',
    '物料管理方式 Instance 和 Category 区别',
    '库房单据编号规则是什么',
    'what are the warehouse ticket types',
  ];
  for (const q of knowledgeQs) {
    check(
      parseWarehouseIntent(q) === null,
      `口径问法不抢工具：「${q}」`
    );
    check(isWarehouseKnowledgeQuestion(q), `口径问法被识别为知识问法：「${q}」`);
  }

  const factQs = [
    '库房现在什么情况',
    '各仓库存还有多少',
    '物料 033030100282 还有多少库存',
    'SPIB202610220006 这个入库单什么状态',
  ];
  for (const q of factQs) {
    check(
      parseWarehouseIntent(q) !== null,
      `事实问法仍走工具：「${q}」`
    );
    check(!isWarehouseKnowledgeQuestion(q), `事实问法不被误判为知识问法：「${q}」`);
  }

  // 单号查询不受知识护栏影响 —— 它永远是事实查询
  check(
    parseWarehouseIntent('SPIB202610220006 是什么类型')?.args.kind === 'ticket',
    '带单号的问法即使含「是什么」也走工具（单号优先）'
  );

  // 护栏不能误伤工单/查表问法 —— 它们与库房无关（2026-10-27 加 WAREHOUSE_TOPIC 的原因）
  const notWarehouse = ['P1 是什么级别', '告警码 9920 是什么意思', '报销流程怎么走'];
  for (const q of notWarehouse) {
    check(!isWarehouseKnowledgeQuestion(q), `非库房问法不被误判：「${q}」`);
  }
  // 库房口径题可能不带「库房」「库存」字样，仍要认出来
  check(
    isWarehouseKnowledgeQuestion('物料管理方式 Instance 和 Category 区别'),
    '库房口径题不带强事实词也能识别'
  );
}

/* --------------------------- 5. parseByRule 集成 --------------------------- */

console.log('\n[5] parseByRule 集成（不抢工单与查表通道）');
{
  check(parseByRule('库房现在什么情况', NOW)?.tool === 'query_warehouse', '库房总览 → query_warehouse');
  check(
    parseByRule('物料 033030100282 还有多少库存', NOW)?.tool === 'query_warehouse',
    '库房物料 → query_warehouse（不被 COUNT_INTENT 抢走）'
  );
  check(
    parseByRule('SPIB202610220006 这个入库单什么状态', NOW)?.tool === 'query_warehouse',
    '库房单号 → query_warehouse（不被 extractAlarmCode 抢走）'
  );
  // 回归保护：既有通道不能被库房意图误伤
  check(parseByRule('今天有几个 P1', NOW)?.tool === 'query_tickets', '工单统计未被抢走');
  check(parseByRule('告警码 9920 是什么意思', NOW)?.tool === 'lookup_alarm_code', '查表未被抢走');
  check(parseByRule('how many P1 tickets today', NOW)?.tool === 'query_tickets', '英文工单统计未被抢走');
  check(parseByRule('P1 是什么级别', NOW)?.tool === 'lookup_level_rule', '级别规则未被抢走');
}

console.log('\n' + '='.repeat(50));
console.log(`结果：${pass} 通过 / ${fail} 失败`);
console.log('='.repeat(50));

CONFIG.toolsEnabled = ORIG;
process.exit(fail ? 1 : 0);
