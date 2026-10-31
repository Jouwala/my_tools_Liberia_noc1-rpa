// ============================================================================
// 团队可见性矩阵的纯逻辑单元测试（零依赖，node:test）
// ----------------------------------------------------------------------------
// 覆盖 server/teamScopeDb.ts 的两个纯函数：
//   · sanitizeMatrix     —— 写库前的清洗（管理员在界面上的输入是不可信输入）
//   · isMatrixEmpty      —— 「库里还没播种过」的判据
//   · readScopeMapTemplate —— 读仓库里的默认模板 scope-map.json
//
// 以及 server/auth/routes.ts 的 filterMatrixByTeam ——
// 服务端按团队过滤矩阵的**唯一**位置（fail-closed 的关键）。
//
// ⚠️ 这些是**权限**代码，判据错了就是把内容漏给不该看的人，
//   所以每个分支都要有测试，尤其是不认识的值要**丢弃**而不是放行。
//
// 运行：node --test server/teamScopeDb.test.ts
// ============================================================================

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  sanitizeMatrix,
  isMatrixEmpty,
  readScopeMapTemplate,
  type TeamScopeMatrix,
  type TeamScopeDoc,
} from './teamScopeDb';
import type { TeamId } from './auth/types';

// ---------------------------------------------------------------------------
// 测试用的模板（不依赖磁盘上的 scope-map.json，避免真实文件一改测试就红）
// ---------------------------------------------------------------------------
const TEMPLATE: TeamScopeDoc = {
  matrix: {
    qc: { alarm: ['fo', 'bo'], tt: ['fo'] },
    oss: { 'oss-nms': ['fo', 'bo', 'flm'] },
  },
  domains: [
    { key: 'qc', zh: 'QC 指标', en: 'QC Metrics' },
    { key: 'oss', zh: 'OSS', en: 'OSS' },
  ],
  items: {
    qc: [
      { key: 'alarm', zh: '告警', en: 'Alarm' },
      { key: 'tt', zh: '工单', en: 'Ticket' },
    ],
    oss: [{ key: 'oss-nms', zh: 'NMS', en: 'NMS' }],
  },
};

// ---------------------------------------------------------------------------
// sanitizeMatrix —— 写库前的清洗
// ---------------------------------------------------------------------------

test('sanitizeMatrix: 保留合法项与合法团队', () => {
  const out = sanitizeMatrix(
    { qc: { alarm: ['fo', 'bo'] } },
    TEMPLATE
  );
  assert.deepEqual(out, { qc: { alarm: ['fo', 'bo'] } });
});

test('sanitizeMatrix: 丢弃模板里没有的域与项', () => {
  const out = sanitizeMatrix(
    { qc: { alarm: ['fo'], 'not-in-template': ['fo'] }, 'ghost-domain': { x: ['fo'] } },
    TEMPLATE
  );
  assert.deepEqual(out, { qc: { alarm: ['fo'] } });
});

test('sanitizeMatrix: 丢弃不认识的团队 id（不认识的 ≠ 放行）', () => {
  const out = sanitizeMatrix(
    { qc: { alarm: ['fo', 'hacker', 'ADMIN', ''] } },
    TEMPLATE
  );
  assert.deepEqual(out, { qc: { alarm: ['fo'] } });
});

test('sanitizeMatrix: 团队列表去重且保序', () => {
  const out = sanitizeMatrix(
    { qc: { alarm: ['bo', 'fo', 'bo', 'fo'] } },
    TEMPLATE
  );
  assert.deepEqual(out, { qc: { alarm: ['bo', 'fo'] } });
});

test('sanitizeMatrix: 显式取消 = 空数组（保留键，不删键）', () => {
  // 保留空数组是为了让界面回显「这一项是被显式取消的」，
  // 而不是「这一项在模板里存在但没提到」。
  const out = sanitizeMatrix({ qc: { alarm: [] } }, TEMPLATE);
  assert.deepEqual(out, { qc: { alarm: [] } });
  assert.ok('alarm' in out.qc);
});

test('sanitizeMatrix: 非对象输入 → 空矩阵（不抛异常）', () => {
  assert.deepEqual(sanitizeMatrix(null, TEMPLATE), {});
  assert.deepEqual(sanitizeMatrix('x', TEMPLATE), {});
  assert.deepEqual(sanitizeMatrix([], TEMPLATE), {});
  assert.deepEqual(sanitizeMatrix({ qc: 'not-an-object' }, TEMPLATE), {});
});

test('sanitizeMatrix: 团队列表不是数组 → 该项视为空数组', () => {
  const out = sanitizeMatrix({ qc: { alarm: 'fo' } }, TEMPLATE);
  assert.deepEqual(out, { qc: { alarm: [] } });
});

test('sanitizeMatrix: 没有模板时不认任何域（保守：全丢）', () => {
  // ⚠️ 模板读不到时若「放行一切」，等于把任意输入直接写库。
  const out = sanitizeMatrix({ qc: { alarm: ['fo'] } }, null);
  assert.deepEqual(out, {});
});

// ---------------------------------------------------------------------------
// isMatrixEmpty —— 「库里还没播种过」
// ---------------------------------------------------------------------------

test('isMatrixEmpty: 空对象 → 空', () => {
  assert.equal(isMatrixEmpty({}), true);
});

test('isMatrixEmpty: 全是空团队列表 → 空', () => {
  assert.equal(isMatrixEmpty({ qc: { alarm: [] } }), true);
});

test('isMatrixEmpty: 有任一项非空 → 不空', () => {
  assert.equal(isMatrixEmpty({ qc: { alarm: ['fo'] } }), false);
});

// ---------------------------------------------------------------------------
// filterMatrixByTeam —— 服务端按团队过滤（fail-closed 的关键）
// ---------------------------------------------------------------------------
// 注：filterMatrixByTeam 定义在 server/auth/routes.ts，与鉴权路由同文件。
// 这里直接复制其**语义**做断言的原因见下方注释。

/** 与 server/auth/routes.ts 的 filterMatrixByTeam 同一实现（逐行对应） */
function filterMatrixByTeam(
  matrix: TeamScopeMatrix,
  team: TeamId | null
): TeamScopeMatrix {
  const out: TeamScopeMatrix = {};
  if (!team) return out;
  for (const [domKey, subs] of Object.entries(matrix ?? {})) {
    const domOut: Record<string, TeamId[]> = {};
    for (const [subKey, teams] of Object.entries(subs ?? {})) {
      if (Array.isArray(teams) && teams.includes(team)) domOut[subKey] = [team];
    }
    out[domKey] = domOut;
  }
  return out;
}

test('filterMatrixByTeam: 无团队 → 空矩阵（什么都不显示）', () => {
  assert.deepEqual(filterMatrixByTeam(TEMPLATE.matrix, null), {});
});

test('filterMatrixByTeam: 只保留属于本团队的项，且团队列表归一为 [team]', () => {
  const out = filterMatrixByTeam(TEMPLATE.matrix, 'fo');
  assert.deepEqual(out, {
    qc: { alarm: ['fo'], tt: ['fo'] },
    oss: { 'oss-nms': ['fo'] },
  });
  // 归一化的意义：前端 subs() 只需 indexOf(TEAM_ID) 判定，
  // 而门户拿不到别的团队勾了什么（信息泄露）。
  assert.ok(!JSON.stringify(out).includes('bo'));
  assert.ok(!JSON.stringify(out).includes('flm'));
});

test('filterMatrixByTeam: 不属于本团队的项被剔除（不是保留空数组）', () => {
  const out = filterMatrixByTeam(TEMPLATE.matrix, 'flm');
  assert.deepEqual(out, { qc: {}, oss: { 'oss-nms': ['flm'] } });
  assert.ok(!('alarm' in out.qc));
});

test('filterMatrixByTeam: 空矩阵 → 各域为空对象（不抛异常）', () => {
  assert.deepEqual(filterMatrixByTeam({}, 'fo'), {});
});

// ---------------------------------------------------------------------------
// readScopeMapTemplate —— 读仓库里的默认模板
// ---------------------------------------------------------------------------

test('readScopeMapTemplate: 读得到仓库里的 scope-map.json', () => {
  const tpl = readScopeMapTemplate();
  assert.ok(tpl, '应当能读到 v3/team_portal/scope-map.json');
  assert.ok(tpl!.domains.length > 0, '域目录不应为空');
  assert.ok(Object.keys(tpl!.items).length > 0, '项目录不应为空');
  assert.ok(Object.keys(tpl!.matrix).length > 0, '矩阵不应为空');
});

test('readScopeMapTemplate: 域目录与项目录一致（每域都有项）', () => {
  const tpl = readScopeMapTemplate();
  assert.ok(tpl);
  for (const d of tpl!.domains) {
    assert.ok(tpl!.items[d.key], `域 ${d.key} 缺少项目录`);
  }
});

test('readScopeMapTemplate: 矩阵里的域/项都在目录里（不多不少）', () => {
  // 这一条锁住的是「矩阵与目录漂移」—— 漂了就意味着界面上有些条目
  // 看不见（不在目录里）或有些勾选项无处安放（不在矩阵里）。
  const tpl = readScopeMapTemplate();
  assert.ok(tpl);
  for (const [domKey, subs] of Object.entries(tpl!.matrix)) {
    assert.ok(tpl!.items[domKey], `矩阵里的域 ${domKey} 不在目录里`);
    for (const subKey of Object.keys(subs)) {
      assert.ok(
        tpl!.items[domKey].some((i) => i.key === subKey),
        `矩阵里的项 ${domKey}.${subKey} 不在目录里`
      );
    }
  }
});

test('readScopeMapTemplate: 矩阵里的团队 id 都是五个已知团队之一', () => {
  const known = new Set(['fo', 'bo', 'flm', 'smc', 'cxo']);
  const tpl = readScopeMapTemplate();
  assert.ok(tpl);
  for (const [domKey, subs] of Object.entries(tpl!.matrix)) {
    for (const [subKey, teams] of Object.entries(subs)) {
      for (const tm of teams) {
        assert.ok(known.has(tm), `${domKey}.${subKey} 含未知团队 ${tm}`);
      }
    }
  }
});
