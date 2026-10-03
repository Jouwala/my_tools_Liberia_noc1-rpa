// ============================================================================
// server/portalDefault.ts 单元测试 —— 接口层纯逻辑（零依赖，node:test）
// ----------------------------------------------------------------------------
// 覆盖「dev 与 prod 共用」的 portal-default 逻辑。这些函数此前在
// vite.config.ts 与 server/index.ts 各有一份副本，2026-10-01 收敛到本模块，
// 因此这组测试同时锁死了**两个入口**的行为。
//
// 运行：node --test server/portalDefault.test.ts
// ============================================================================

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  APP_BASE,
  sanitizeGroupNames,
  sanitizeGroupLabels,
  parsePortalDefaultPayload,
  isLocalhostSaveRequest,
} from './portalDefault';

test('APP_BASE 与端口前缀约定一致', () => {
  assert.equal(APP_BASE, '/uniplam/');
});

// ---------------------------------------------------------------------------
// sanitizeGroupNames —— 与前端 src/utils/groups.ts 的 sanitizeGroups 同规则
// ---------------------------------------------------------------------------
test('sanitizeGroupNames: 去空、去「全部」、忽略大小写去重、保序', () => {
  assert.deepEqual(
    sanitizeGroupNames(['告警', '', '  ', '全部', '告警监控', '告警', 'ALARM', 'alarm']),
    ['告警', '告警监控', 'ALARM']
  );
});

test('sanitizeGroupNames: 折叠空白并去首尾', () => {
  assert.deepEqual(sanitizeGroupNames(['  告警   监控  ']), ['告警 监控']);
});

test('sanitizeGroupNames: 非数组 / 含非字符串项安全处理', () => {
  assert.deepEqual(sanitizeGroupNames(null), []);
  assert.deepEqual(sanitizeGroupNames('告警'), []);
  assert.deepEqual(sanitizeGroupNames([1, true, {}, '有效']), ['有效']);
});

// ---------------------------------------------------------------------------
// sanitizeGroupLabels
// ---------------------------------------------------------------------------
test('sanitizeGroupLabels: 丢掉非现存分组、空值、非字符串', () => {
  assert.deepEqual(
    sanitizeGroupLabels({ 告警: 'Alarm', 不存在: 'Nope', 空: '   ', 数字: 42 }, [
      '告警',
      '空',
      '数字',
    ]),
    { 告警: 'Alarm' }
  );
});

test('sanitizeGroupLabels: 非对象输入返回空表', () => {
  assert.deepEqual(sanitizeGroupLabels(null, ['A']), {});
  assert.deepEqual(sanitizeGroupLabels(['A'], ['A']), {});
});

// ---------------------------------------------------------------------------
// parsePortalDefaultPayload —— POST 载荷解析（v2 与旧数组格式）
// ---------------------------------------------------------------------------
test('parsePortalDefaultPayload: v2 对象 → 落盘 v2，带 groups/groupLabels', () => {
  const body = JSON.stringify({
    groups: ['告警', '性能'],
    groupLabels: { 告警: 'Alarm', 幽灵: 'X' }, // 幽灵应被丢掉（不在 groups）
    dashboards: [{ id: 'a' }, { id: 'b' }],
  });
  const r = parsePortalDefaultPayload(body, '2026-10-01T00:00:00.000Z');
  assert.ok(r);
  assert.equal(r.count, 2);
  assert.equal(r.groupCount, 2);
  assert.deepEqual(r.payload, {
    version: 2,
    savedAt: '2026-10-01T00:00:00.000Z',
    groups: ['告警', '性能'],
    groupLabels: { 告警: 'Alarm' },
    dashboards: [{ id: 'a' }, { id: 'b' }],
  });
});

test('parsePortalDefaultPayload: 旧数组格式 → 原样写数组（兼容）', () => {
  const body = JSON.stringify([{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
  const r = parsePortalDefaultPayload(body, 'X');
  assert.ok(r);
  assert.deepEqual(r.payload, [{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
  assert.equal(r.count, 3);
  assert.equal(r.groupCount, 0);
});

test('parsePortalDefaultPayload: 非法 JSON / 空数组 / 缺 dashboards → null', () => {
  assert.equal(parsePortalDefaultPayload('{not json', 'X'), null);
  assert.equal(parsePortalDefaultPayload(JSON.stringify([]), 'X'), null);
  assert.equal(parsePortalDefaultPayload(JSON.stringify({ groups: [] }), 'X'), null);
  assert.equal(parsePortalDefaultPayload(JSON.stringify({ dashboards: [] }), 'X'), null);
});

// ---------------------------------------------------------------------------
// isLocalhostSaveRequest —— 「只有本机可保存」的唯一判据
// ---------------------------------------------------------------------------
const req = (remote: string, host: string) => ({
  socket: { remoteAddress: remote },
  headers: { host } as Record<string, string | string[] | undefined>,
});

test('isLocalhostSaveRequest: 回环 IP + localhost/127.0.0.1 Host 才放行', () => {
  assert.equal(isLocalhostSaveRequest(req('127.0.0.1', 'localhost')), true);
  assert.equal(isLocalhostSaveRequest(req('127.0.0.1', '127.0.0.1')), true);
  assert.equal(isLocalhostSaveRequest(req('::1', 'localhost')), true);
  assert.equal(isLocalhostSaveRequest(req('127.0.0.1', 'localhost:9267')), true); // 端口不限
});

test('isLocalhostSaveRequest: 局域网 IP / 伪造 Host / IPv4-mapped 之外一律拒绝', () => {
  assert.equal(isLocalhostSaveRequest(req('192.168.100.20', 'localhost')), false);
  assert.equal(isLocalhostSaveRequest(req('127.0.0.1', '192.168.100.20')), false);
  assert.equal(isLocalhostSaveRequest(req('192.168.100.20', 'evil.example')), false);
});
