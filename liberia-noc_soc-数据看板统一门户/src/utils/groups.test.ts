// ============================================================================
// groups.ts 单元测试 —— 零依赖，用 Node 内置 node:test + node:assert
// ----------------------------------------------------------------------------
// 为什么零依赖：本仓库此前没有任何测试基建，node_modules 里也没装 vitest/jest；
// Node 22 自带 `node --test`（+ 内置 assert），无需新增依赖、无需联网安装，
// 在 .20 上 `npm test` 直接能跑。
//
// 覆盖重点（都是「改错会静默出问题」的不变量，不是凑数）：
//   1) 卡片与分组的关联只存 category —— 重命名/删除分组绝不能产生孤儿卡片；
//   2) 「全部」是伪分组，永不进入 groups；
//   3) 去重忽略大小写、名称归一化折叠空白；
//   4) 至少保留一个分组；删最后一个被拒。
//
// 运行：node --test src/utils/groups.test.ts
//      （由 package.json 的 "test" 脚本封装；tsx 负责把 .ts 直接喂给 node --test）
// ============================================================================

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  GROUP_ALL,
  FALLBACK_GROUP,
  MAX_GROUP_NAME_LENGTH,
  normalizeGroupName,
  sanitizeGroups,
  deriveGroups,
  sanitizeGroupLabels,
  setGroupLabel,
  renameGroupLabel,
  dropGroupLabel,
  groupDisplayName,
  countByGroup,
  reorderGroups,
  moveGroup,
  moveGroupToEdge,
  addGroup,
  renameGroup,
  deleteGroup,
  type GroupOpResult,
} from './groups';

/** 测试用卡片：只带 id 与 category，模拟 DashboardItem 的最小形状 */
interface Card {
  id: string;
  category?: string;
}

const card = (id: string, category?: string): Card => ({ id, category });

// ---------------------------------------------------------------------------
// normalizeGroupName —— 归一化
// ---------------------------------------------------------------------------
test('normalizeGroupName: 折叠连续空白并去首尾', () => {
  assert.equal(normalizeGroupName('  告警   监控  '), '告警 监控');
  assert.equal(normalizeGroupName('a\tb\nc'), 'a b c');
});

test('normalizeGroupName: 非字符串/空值安全返回空串', () => {
  assert.equal(normalizeGroupName(undefined), '');
  assert.equal(normalizeGroupName(null), '');
  assert.equal(normalizeGroupName(123), '123');
});

// ---------------------------------------------------------------------------
// sanitizeGroups —— 过滤服务端/导入数据
// ---------------------------------------------------------------------------
test('sanitizeGroups: 去空、去「全部」伪分组、忽略大小写去重、保序', () => {
  const out = sanitizeGroups(['告警', '', '  ', GROUP_ALL, '告警监控', '告警', 'ALARM', 'alarm']);
  assert.deepEqual(out, ['告警', '告警监控', 'ALARM']);
});

test('sanitizeGroups: 非数组输入返回空数组', () => {
  assert.deepEqual(sanitizeGroups(null), []);
  assert.deepEqual(sanitizeGroups('告警'), []);
  assert.deepEqual(sanitizeGroups({ a: 1 }), []);
});

// ---------------------------------------------------------------------------
// deriveGroups —— 从卡片推导（兼容旧格式）
// ---------------------------------------------------------------------------
test('deriveGroups: 保留 seeds 顺序，再追加卡片里出现过的新分组', () => {
  const cards = [card('a', '告警'), card('b', '性能'), card('c', '告警')];
  assert.deepEqual(deriveGroups(cards, ['网络']), ['网络', '告警', '性能']);
});

test('deriveGroups: 卡片 category 为空/为「全部」时跳过', () => {
  const cards = [card('a'), card('b', ''), card('c', GROUP_ALL), card('d', '有效')];
  assert.deepEqual(deriveGroups(cards, []), ['有效']);
});

// ---------------------------------------------------------------------------
// 标签表
// ---------------------------------------------------------------------------
test('sanitizeGroupLabels: 丢掉非现存分组、空值、非字符串', () => {
  const out = sanitizeGroupLabels(
    { 告警: 'Alarm', 不存在: 'Nope', 空: '   ', 数字: 42 },
    ['告警', '空', '数字']
  );
  assert.deepEqual(out, { 告警: 'Alarm' });
});

test('setGroupLabel: 写入 / 传空清除', () => {
  assert.deepEqual(setGroupLabel({}, '告警', 'Alarm'), { 告警: 'Alarm' });
  assert.deepEqual(setGroupLabel({ 告警: 'Alarm' }, '告警', ''), {});
});

test('renameGroupLabel: 旧键删除、新键写入', () => {
  const out = renameGroupLabel({ 告警: 'Alarm' }, '告警', '告警监控', 'Alarm & Monitor');
  assert.deepEqual(out, { 告警监控: 'Alarm & Monitor' });
});

test('dropGroupLabel: 删除指定分组标签', () => {
  assert.deepEqual(dropGroupLabel({ 告警: 'Alarm', 性能: 'Perf' }, '告警'), { 性能: 'Perf' });
});

test('groupDisplayName: zh 原样；en 先查标签表再看兜底', () => {
  assert.equal(groupDisplayName('告警', 'zh', {}, undefined), '告警');
  assert.equal(groupDisplayName('告警', 'en', { 告警: 'Alarm' }, undefined), 'Alarm');
  assert.equal(groupDisplayName('告警', 'en', {}, (n) => `T:${n}`), 'T:告警');
  assert.equal(groupDisplayName('告警', 'en', {}, undefined), '告警'); // 无标签无兜底 → 原样
});

// ---------------------------------------------------------------------------
// countByGroup
// ---------------------------------------------------------------------------
test('countByGroup: 按归一化组名计数，空 category 跳过', () => {
  const cards = [card('a', '告警'), card('b', '告警'), card('c', ' 性能 '), card('d')];
  assert.deepEqual(countByGroup(cards), { 告警: 2, 性能: 1 });
});

// ---------------------------------------------------------------------------
// 排序
// ---------------------------------------------------------------------------
test('reorderGroups: 移动第 0 个到第 2 位，其余相对顺序不变', () => {
  const r = reorderGroups(['A', 'B', 'C', 'D'], 0, 2);
  assert.equal(r.ok, true);
  assert.deepEqual(r.groups, ['B', 'C', 'A', 'D']);
});

test('reorderGroups: from === to 视为无变化且 ok', () => {
  const r = reorderGroups(['A', 'B'], 1, 1);
  assert.equal(r.ok, true);
  assert.deepEqual(r.groups, ['A', 'B']);
});

test('reorderGroups: 空列表返回 not_found', () => {
  const r = reorderGroups([], 0, 1);
  assert.equal(r.ok, false);
  assert.equal(r.error, 'not_found');
});

test('moveGroup: 上移/下移；已到边界顺序不变', () => {
  assert.deepEqual(moveGroup(['A', 'B', 'C'], 'B', -1).groups, ['B', 'A', 'C']);
  assert.deepEqual(moveGroup(['A', 'B', 'C'], 'A', -1).groups, ['A', 'B', 'C']);
});

test('moveGroupToEdge: 移到最前/最后', () => {
  assert.deepEqual(moveGroupToEdge(['A', 'B', 'C'], 'C', 'first').groups, ['C', 'A', 'B']);
  assert.deepEqual(moveGroupToEdge(['A', 'B', 'C'], 'A', 'last').groups, ['B', 'C', 'A']);
});

// ---------------------------------------------------------------------------
// addGroup —— 校验
// ---------------------------------------------------------------------------
test('addGroup: 正常新增（允许空分组）', () => {
  const r = addGroup(['A'], '新组');
  assert.equal(r.ok, true);
  assert.deepEqual(r.groups, ['A', '新组']);
  assert.equal(r.moved, 0);
});

test('addGroup: 拒绝空名 / 超长 / 保留名 / 重名（忽略大小写）', () => {
  assert.equal(addGroup(['A'], '   ').error, 'empty');
  assert.equal(addGroup(['A'], 'x'.repeat(MAX_GROUP_NAME_LENGTH + 1)).error, 'too_long');
  assert.equal(addGroup(['A'], GROUP_ALL).error, 'reserved');
  assert.equal(addGroup(['Alarm'], 'alarm').error, 'duplicate');
});

// ---------------------------------------------------------------------------
// renameGroup —— 关键不变量：不产生孤儿卡片
// ---------------------------------------------------------------------------
test('renameGroup: 同步改写卡片 category，moved 计数正确', () => {
  const cards = [card('1', '旧'), card('2', '旧'), card('3', '别的')];
  const r = renameGroup(['旧', '别的'], cards, '旧', '新');
  assert.equal(r.ok, true);
  assert.deepEqual(r.groups, ['新', '别的']);
  assert.equal(r.moved, 2);
  assert.deepEqual(
    r.dashboards.map((d) => d.category),
    ['新', '新', '别的']
  );
  // 不变量：没有任何卡片挂在已不存在的旧组名上
  assert.equal(r.dashboards.some((d) => d.category === '旧'), false);
});

test('renameGroup: 目标组不存在 → not_found，卡片原样', () => {
  const cards = [card('1', 'A')];
  const r = renameGroup(['A'], cards, '不在的', 'B');
  assert.equal(r.ok, false);
  assert.equal(r.error, 'not_found');
  assert.deepEqual(r.dashboards, cards);
});

test('renameGroup: 改成同名 → ok 且 moved 0', () => {
  const r = renameGroup(['A'], [card('1', 'A')], 'A', 'A');
  assert.equal(r.ok, true);
  assert.equal(r.moved, 0);
});

test('renameGroup: 重名（另一个已存在）→ duplicate', () => {
  const r = renameGroup(['A', 'B'], [], 'A', 'B');
  assert.equal(r.error, 'duplicate');
});

// ---------------------------------------------------------------------------
// deleteGroup —— 关键不变量：卡片迁移到兜底分组，不消失
// ---------------------------------------------------------------------------
test('deleteGroup: 卡片迁移到兜底分组「其他」', () => {
  const cards = [card('1', '待删'), card('2', '待删'), card('3', '保留')];
  const r = deleteGroup(['待删', '保留', '其他'], cards, '待删');
  assert.equal(r.ok, true);
  assert.equal(r.moved, 2);
  assert.equal(r.fallback, '其他');
  assert.equal(r.groups.includes('待删'), false);
  // 不变量：没有孤儿卡片
  assert.deepEqual(
    r.dashboards.map((d) => d.category),
    ['其他', '其他', '保留']
  );
});

test('deleteGroup: 无「其他」时回落到剩余第一个分组', () => {
  const r = deleteGroup(['待删', 'A', 'B'], [card('1', '待删')], '待删');
  assert.equal(r.fallback, 'A');
  assert.equal(r.dashboards[0].category, 'A');
});

test('deleteGroup: 删最后一个分组被拒（last_group）', () => {
  const r = deleteGroup(['唯一'], [card('1', '唯一')], '唯一');
  assert.equal(r.ok, false);
  assert.equal(r.error, 'last_group');
});

test('deleteGroup: 目标不存在 → not_found', () => {
  const r = deleteGroup(['A', 'B'], [], '不存在');
  assert.equal(r.error, 'not_found');
});

// ---------------------------------------------------------------------------
// 组合：任何分组操作的输出都应保持「无孤儿卡片」这一全局不变量
// ---------------------------------------------------------------------------
test('不变量：rename → delete 一连串操作后，卡片 category 全部落在现存分组内', () => {
  let groups = ['告警', '性能', '其他'];
  let cards: Card[] = [card('1', '告警'), card('2', '告警'), card('3', '性能')];

  const r1 = renameGroup(groups, cards, '告警', '告警监控');
  const r2 = deleteGroup(r1.groups, r1.dashboards, '性能');

  groups = r2.groups;
  cards = r2.dashboards;

  const orphans = cards.filter((c) => c.category && !groups.includes(c.category));
  assert.equal(orphans.length, 0, `存在孤儿卡片: ${JSON.stringify(orphans)}`);
});

// ---------------------------------------------------------------------------
// 类型层面的辅助（防止 GroupOpResult 泛型被误用）——仅编译期
// ---------------------------------------------------------------------------
test('GroupOpResult 泛型对卡片类型透明', () => {
  const r: GroupOpResult<Card> = addGroup<Card>(['A'], 'B', []);
  assert.equal(r.dashboards.length, 0);
});
