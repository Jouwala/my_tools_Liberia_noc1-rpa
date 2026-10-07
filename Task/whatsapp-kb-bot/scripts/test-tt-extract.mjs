#!/usr/bin/env node
/**
 * 工单号抽取与多单路由回归测试（纯函数，不需要 Python / 工单库）。
 *   node scripts/test-tt-extract.mjs
 *
 * 覆盖两类真实事故：
 *   1. **WO 单号被漏抽** —— 曾经正则只认 TT，用户问
 *      `WO202609220055 Please analyze this Work Order.` 时单号抽不出来，
 *      落到知识库通道，模型把 `WO` 当成 PCT 专利文献号，
 *      编出「资料里没有该专利的技术内容」这种跨领域的错误答案。
 *   2. **多单只答第一个** —— 用户贴两个单号，旧实现只回第一个，
 *      后面的一个字不提，用户无从知道被漏了。
 */
import { extractTtNo, extractTtNos, MAX_TICKETS_PER_QUESTION } from '../src/tt.js';
import { routeAnswer, describeRoute } from '../src/answer.js';

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

const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log('='.repeat(50));
console.log('工单号抽取与多单路由测试');
console.log('='.repeat(50));

/* ---------------------------- 单号抽取：TT ---------------------------- */

console.log('\n[1] TT 单号（原有行为，不能回归）');
check(extractTtNo('分析TT单TT202609150077') === 'TT202609150077', '中文前缀 + 单号');
check(extractTtNo('please analysis TT202609160068') === 'TT202609160068', '英文前缀 + 单号');
check(extractTtNo('TT202609230055请分析下') === 'TT202609230055', '单号紧贴中文（无空格）');
check(extractTtNo('please analysis:TT202609040052') === 'TT202609040052', '冒号分隔');
check(extractTtNo('tt202609150077') === 'TT202609150077', '小写单号 → 统一大写');

/* ---------------------------- 单号抽取：WO ---------------------------- */

console.log('\n[2] WO 单号（本次修复的核心）');
check(
  extractTtNo('WO202609220055 Please analyze this Work Order.') === 'WO202609220055',
  'WO 单号能被抽出（曾经为 null → 误入知识库通道）'
);
check(extractTtNo('分析 WO202609220055') === 'WO202609220055', '中文语境下的 WO 单号');
check(extractTtNo('wo202609220055') === 'WO202609220055', '小写 wo → 统一大写');
check(extractTtNos('WO202609220055 and TT202609220113').length === 2, 'WO 与 TT 混用都能抽到');

/* ------------------------------ 边界与误判 ------------------------------ */

console.log('\n[3] 边界：不能把非单号文本误判成单号');
check(extractTtNo('my concern is why there is no Severity on these sites alarms') === null, '规则类提问 → 不入工单通道');
check(extractTtNo('请问告警200201001会被压缩成什么样的告警') === null, '纯告警码（无 TT/WO 前缀）→ 不入工单通道');
check(extractTtNo('请输出告警的端到端链路') === null, '链路类提问 → 不入工单通道');
check(extractTtNo('') === null, '空字符串');
check(extractTtNo(null) === null, 'null');
check(extractTtNo(undefined) === null, 'undefined');
check(extractTtNos('TT12345') === undefined || extractTtNos('TT12345').length === 0, '位数不足（<6 位）不算单号');
check(extractTtNos('TT202609150077').length === 1, '单个单号 → 长度 1');

// 词边界：避免把 "ATT202609150077" 这类粘连词误判
check(extractTtNos('ATT202609150077').length === 0, '前接字母的粘连串不误判（词边界生效）');

/* -------------------------------- 多单 -------------------------------- */

console.log('\n[4] 多单抽取（真实提问形态）');
{
  const q = 'check these TTs TT202609140078, TT202609140077 these are the two TTs i need you to check';
  const nos = extractTtNos(q);
  check(nos.length === 2, `抽出 2 个单号（实际 ${nos.length}）`, JSON.stringify(nos));
  check(eq(nos, ['TT202609140078', 'TT202609140077']), '顺序与原文一致', JSON.stringify(nos));
  check(extractTtNo(q) === 'TT202609140078', 'extractTtNo 仍返回首个（兼容旧接口）');
}
{
  const nos = extractTtNos('TT202609140078 TT202609140078 TT202609140077');
  check(nos.length === 2, '重复单号去重', JSON.stringify(nos));
}
{
  const nos = extractTtNos('WO202609220055/WO202609220056');
  check(nos.length === 2, '斜杠分隔也能抽出');
}

/* ---------------------------- 路由分流（不查库） ---------------------------- */

console.log('\n[5] 路由分流：单号问题走工单通道，其余走知识库');
{
  // 用一个空索引 + 桩，只验证"分流方向"，不触发真实查库/嵌入
  const idx = { chunks: [], vectors: [], meta: { chunks: 0, files: 0 } };
  const routes = [];

  // 通过 onRoute 观察分流；rag 通道因为没有索引会走未命中分支
  const probe = async (q) => {
    routes.length = 0;
    try {
      await routeAnswer(q, idx, {
        onRoute: (r) => routes.push(r.channel),
        lang: 'zh',
      });
    } catch {
      /* 知识库通道在空索引下可能抛错，不影响分流判定 */
    }
    return routes[0];
  };

  check((await probe('TT202609150073')) === 'tt', 'TT 单号 → tt 通道');
  check((await probe('WO202609220055')) === 'tt', 'WO 单号 → tt 通道');
  // 非单号问题**不得**被误判进工单通道。离线环境下知识库通道会因为
  // 嵌入/模型不可达而抛错、onRoute 来不及触发（channel=undefined），
  // 所以这里断言的是「不是 tt」，而不是「恰好是 kb」——
  // 后者会把这个纯路由测试变成需要联网的测试。
  {
    const ch = await probe('请输出告警的端到端链路');
    check(ch !== 'tt', '规则提问 → 不进 tt 通道（应走知识库）', `channel=${ch}`);
  }
}

/* ---------------------------- describeRoute ---------------------------- */

console.log('\n[6] 路由描述（日志可读性）');
{
  const one = describeRoute({ channel: 'tt', stats: { totalMs: 1500, count: 1 } });
  check(one.includes('TT单') && one.includes('1500ms'), '单号描述含耗时', one);
  check(!one.includes('2 个单'), '单号时不说"N 个单"', one);

  const many = describeRoute({ channel: 'tt', stats: { totalMs: 3000, count: 2 } });
  check(many.includes('2 个单'), '多单时标出数量', many);

  const kb = describeRoute({ channel: 'kb' });
  check(kb.includes('知识库'), '知识库描述', kb);
}

/* ---------------------------- MAX 上限 ---------------------------- */

console.log('\n[7] 单次分析上限');
check(typeof MAX_TICKETS_PER_QUESTION === 'number' && MAX_TICKETS_PER_QUESTION >= 2, '上限是 ≥2 的数字', String(MAX_TICKETS_PER_QUESTION));
check(MAX_TICKETS_PER_QUESTION <= 5, '上限不超过 5（避免回复过长）', String(MAX_TICKETS_PER_QUESTION));

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
