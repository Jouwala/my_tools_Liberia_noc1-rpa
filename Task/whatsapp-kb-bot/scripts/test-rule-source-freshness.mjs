#!/usr/bin/env node
/**
 * 规则源新鲜度单测（**纯离线**，不读真实规则、不联网）。
 *   node scripts/test-rule-source-freshness.mjs
 *
 * 覆盖 2026-10-23 的故障形态：eFlow 规则表更新了，但知识库的 md 还是上一版
 * 导出的 —— 磁盘 md 与索引完全一致，`isStale` 与 `freshnessWarning` 都报
 * 「正常」，bot 却在按旧规则回答。这是第三种「看起来在跑、其实用旧资料」。
 *
 * 不变量：
 *   ① 规则源比同步时间新 → 必须告警（否则故障无法被发现）；
 *   ② 规则源不新于同步时间 → 不告警（避免误报吓人）；
 *   ③ 任一信息缺失 → 不告警、**不抛异常**（旁路质量问题不能连累 ping）。
 */
import { ruleSourceWarning, checkRuleSourceFreshness } from '../src/ruleSourceFreshness.js';

let pass = 0;
let fail = 0;
function check(ok, name, extra = '') {
  if (ok) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.error(`  ✗ ${name}${extra ? ` — ${extra}` : ''}`);
  }
}

const NOW = 1_700_000_000_000;
const HOUR = 3_600_000;

console.log('ruleSourceFreshness:');

// ② 已同步：源文件比同步时间旧或相等 → 不告警
check(
  ruleSourceWarning({ sourceMtimeMs: NOW - 1000, syncedAtMs: NOW }) === null,
  '源比同步时间旧 → 不告警'
);
check(
  ruleSourceWarning({ sourceMtimeMs: NOW, syncedAtMs: NOW }) === null,
  '源与同步时间相同 → 不告警'
);

// ① 规则更新了但知识库没跟 → 必须告警，且提示里带「落后」
const w1 = ruleSourceWarning({ sourceMtimeMs: NOW, syncedAtMs: NOW - 3 * HOUR });
check(typeof w1 === 'string' && w1.includes('规则表比知识库新'), '规则新 3 小时 → 告警');
check(w1.includes('3 小时'), '告警文案带具体落后时长', w1);

const w2 = ruleSourceWarning({ sourceMtimeMs: NOW, syncedAtMs: NOW - 20 * 60_000 });
check(typeof w2 === 'string' && w2.includes('不到 1 小时'), '规则新 20 分钟 → 告警且文案区分', w2);

// 宽限：抖动（1ms 差）不该触发
check(
  ruleSourceWarning({ sourceMtimeMs: NOW + 1, syncedAtMs: NOW, graceMs: 5000 }) === null,
  '宽限期内不计为落后'
);

// ③ 缺信息 / 非法值 → 静默不抛
check(ruleSourceWarning({ sourceMtimeMs: null, syncedAtMs: NOW }) === null, '源 mtime 缺失 → 不告警');
check(ruleSourceWarning({ sourceMtimeMs: NOW, syncedAtMs: null }) === null, '同步时间缺失 → 不告警');
check(ruleSourceWarning({ sourceMtimeMs: NaN, syncedAtMs: NOW }) === null, 'NaN → 不告警');

// checkRuleSourceFreshness：读盘失败不能抛
check(checkRuleSourceFreshness(() => null, NOW) === null, '读不到同步状态 → 不告警');
check(
  checkRuleSourceFreshness(() => {
    throw new Error('disk on fire');
  }, NOW) === null,
  '读盘抛异常 → 吞掉并返回 null（不连累 ping）'
);
const w3 = checkRuleSourceFreshness(() => new Date(NOW - 5 * HOUR), NOW);
check(typeof w3 === 'string', '包装函数能把 Date 正确传给判据');

console.log(`\n${fail === 0 ? '✓ 全部通过' : '✗ 有失败'}：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
