#!/usr/bin/env node
/**
 * 运行时健壮性测试：重连退避、消息 id 集合上限、关闭安全性。
 *   node scripts/test-runtime.mjs
 *
 * 这几项都是「跑一周才会暴露、暴露时已经出事」的问题，
 * 所以必须靠单测覆盖，不能等线上验证。
 */
import { reconnectDelay, createBoundedIdSet, stopWhatsApp } from '../src/whatsapp.js';
import {
  codeMtime,
  fmtTime,
  isStale,
  isStaleCode,
  uptimeText,
  LOADED_MTIME,
  PROCESS_STARTED_AT,
} from '../src/buildinfo.js';

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

/* ------------------------------ 重连退避 ------------------------------ */

console.log('\n[1] 重连退避（必须单调递增，且封顶 60s）');
const expected = [2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000];
const actual = [1, 2, 3, 4, 5, 6, 7, 8].map(reconnectDelay);
console.log(`    实际序列(秒): ${actual.map((d) => d / 1000).join(' → ')}`);
check(
  JSON.stringify(actual) === JSON.stringify(expected),
  '退避序列符合 2/4/8/16/32/60/60/60 秒',
  `期望 ${expected.join(',')}，实际 ${actual.join(',')}`
);
check(reconnectDelay(1) === 2000, '首次重连等待 2 秒（不立即重试，避免触发风控）');
check(
  actual.every((d, i) => i === 0 || d >= actual[i - 1]),
  '退避单调不减（不会越重试越快）'
);
check(Math.max(...actual) <= 60000, '退避封顶 60 秒（不会无限增长）');
check(reconnectDelay(0) === 2000 && reconnectDelay(-5) === 2000, '非法入参（0/负数）安全降级为 2 秒');

/* ---------------------------- 消息 id 集合 ---------------------------- */

console.log('\n[2] 消息 id 集合上限（防止长期运行内存泄漏）');
const ids = createBoundedIdSet(5);
for (let i = 1; i <= 20; i++) ids.add(`msg-${i}`);
check(ids.size === 5, '超出上限后集合大小稳定在 5', `实际 ${ids.size}`);
check(ids.has('msg-20'), '最新 id 被保留');
check(!ids.has('msg-1'), '最旧 id 被淘汰（FIFO）');
check(ids.has('msg-16') && !ids.has('msg-15'), '淘汰边界正确：保留最近 5 个');

const ids2 = createBoundedIdSet(3);
ids2.add('a');
ids2.add('a');
ids2.add('a');
check(ids2.size === 1, '重复添加同一 id 不重复计数');
ids2.add('');
ids2.add(null);
ids2.add(undefined);
check(ids2.size === 1, '空值/未定义被忽略，不污染集合');
check(ids2.has('a') && !ids2.has('') && !ids2.has(null), 'has() 对空值返回 false');

/* ---------------------------- 关闭安全性 ---------------------------- */

console.log('\n[3] 关闭安全性（未登录时收到 Ctrl+C 不应崩溃）');
let threw = false;
try {
  await stopWhatsApp('测试：无活动连接');
} catch (err) {
  threw = true;
  console.log(`      ${err.message}`);
}
check(!threw, '无活动 socket 时调用 stopWhatsApp 不抛异常');

threw = false;
try {
  await stopWhatsApp('测试：重复关闭');
} catch {
  threw = true;
}
check(!threw, '重复调用 stopWhatsApp 幂等，不抛异常');

/* ---------------------------- 代码新鲜度 ---------------------------- */

console.log('\n[4] 代码新鲜度（「改了没生效」的自证机制）');
check(
  isStaleCode(1000, 2000) === true,
  '磁盘代码比进程新 → 判定为「跑的是旧代码」'
);
check(isStaleCode(2000, 1000) === false, '进程比磁盘代码新 → 不算旧代码');
check(isStaleCode(1000, 1000) === false, '同一时刻（刚启动）→ 不算旧代码');
check(isStaleCode(1000, 0) === false, '扫不到源文件（mtime=0）→ 不误报');

check(PROCESS_STARTED_AT <= Date.now(), '进程启动时刻不晚于当前时间');
check(LOADED_MTIME > 0, `能扫到源文件指纹（${fmtTime(LOADED_MTIME)}）`);
check(
  isStale() === false,
  '刚加载完就检查 → 不是旧代码（避免启动即误报）'
);
check(fmtTime(0) === '未知', 'fmtTime(0) → 未知（不输出 1970）');
check(
  fmtTime(new Date(2026, 8, 16, 9, 19, 22).getTime()) === '2026-09-16 09:19:22',
  'fmtTime 补零正确',
  fmtTime(new Date(2026, 8, 16, 9, 19, 22).getTime())
);
check(typeof uptimeText() === 'string' && uptimeText().includes('分钟'), 'uptimeText 可读');

// 关键：codeMtime() 必须是**每次重新扫盘**，不能是启动时冻结的值 ——
// 冻结的话 isStale() 永远返回 false，整个机制形同虚设。
const m1 = codeMtime();
check(m1 === LOADED_MTIME, '刚启动时，实时指纹与加载时指纹一致');
check(codeMtime() > 0, 'codeMtime() 每次调用都重新扫盘（非冻结值）');

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
