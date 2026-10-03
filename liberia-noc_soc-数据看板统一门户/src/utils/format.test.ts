// ============================================================================
// format.ts 单元测试 —— 锁死「数字绝不撒谎」这一核心价值
// ----------------------------------------------------------------------------
// 这组测试守的是评估里"数据口径严谨 93 分"那条的命根子：
//   取不到 → "—"；真的有值（含 0）→ 显示真值。二者绝不能混。
// 运行：node --test src/utils/format.test.ts（经 npm test 封装）
// ============================================================================

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMetric, formatCount, formatText, NO_DATA } from './format';

test('formatMetric: 取不到（null/undefined/NaN/Infinity）一律显示 —，绝不显示 0', () => {
  assert.equal(formatMetric(null), NO_DATA);
  assert.equal(formatMetric(undefined), NO_DATA);
  assert.equal(formatMetric(NaN), NO_DATA);
  assert.equal(formatMetric(Infinity), NO_DATA);
  assert.equal(formatMetric(-Infinity), NO_DATA);
  // 关键：这些都不等于字符串 '0'
  assert.notEqual(formatMetric(null), '0');
});

test('formatMetric: 有值（含真的 0）显示真值', () => {
  assert.equal(formatMetric(0), '0'); // 真的 0 必须能显示出来
  assert.equal(formatMetric(123), '123');
  assert.equal(formatMetric(12.34, { digits: 1 }), '12.3');
  assert.equal(formatMetric(20, { suffix: 's' }), '20s');
  assert.equal(formatMetric(3.14159, { digits: 2, suffix: 's' }), '3.14s');
});

test('formatCount: 0 是合法计数，只有取不到才显示 —', () => {
  assert.equal(formatCount(0), '0');
  assert.equal(formatCount(5), '5');
  assert.equal(formatCount(null), NO_DATA);
  assert.equal(formatCount(undefined), NO_DATA);
  assert.equal(formatCount(NaN), NO_DATA);
});

test('formatText: 空/空白/null → —，其余原样（去首尾空白）', () => {
  assert.equal(formatText(''), NO_DATA);
  assert.equal(formatText('   '), NO_DATA);
  assert.equal(formatText(null), NO_DATA);
  assert.equal(formatText(undefined), NO_DATA);
  assert.equal(formatText('  加纳站点  '), '加纳站点');
});

test('不变量：只要是"取不到"的输入，输出永远是这个唯一占位符', () => {
  const missing = [null, undefined, NaN];
  for (const v of missing) {
    assert.equal(formatMetric(v), NO_DATA);
    assert.equal(formatCount(v), NO_DATA);
  }
});
