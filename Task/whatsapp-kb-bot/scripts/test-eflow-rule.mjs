#!/usr/bin/env node
/**
 * eFlow 规则配置查询单测（压缩 / 自动建单）。
 *   node scripts/test-eflow-rule.mjs
 *
 * 覆盖 2026-10-28 的故障形态：
 *   群里问「How will Alarm Code 200201001 be compressed, and will a service ticket be
 *   automatically generated?」，机器人只回「知识库压缩规则表里没有 200201001」，
 *   后半句「会不会自动建单」被整段丢掉。
 *
 * 两组用例：
 *   A. 离线渲染（不碰 Python、不读规则表）—— 覆盖「没配 / 子告警 / 父告警 /
 *      只有停用规则」四种结论的措辞，以及**通道不可用时绝不说「没配」**这条硬规则。
 *   B. 联机（规则表在才跑）—— 用真实 eFlow 导出验证 200201001 判为「没配」、
 *      9970 判为「压进 99933」、99933 判为「本身是父告警」。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseLookupIntent } from '../src/tools.js';
import {
  lookupEflowRules,
  renderEflowRuleAnswer,
  renderEflowRuleUnavailable,
} from '../src/eflowRules.js';

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

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RULES_DIR =
  process.env.EFLOW_RULES_DIR ||
  path.resolve(HERE, '..', '..', 'my_app', 'backend', 'services', 'eflow_rules');

/* ------------------------- A. 离线渲染 ------------------------- */

function fake(over = {}) {
  return {
    ok: true,
    code: '200201001',
    sources: {
      alarmRules: { file: 'eflow_alarm_rules.xlsx', mtime: '2026-10-25 23:59', total: 14, enabled: 12, correlationEnabled: 10 },
      pushRules: { file: 'eflow_push_rules.xlsx', mtime: '2026-10-28 05:15', total: 141 },
    },
    compression: { asChild: [], asParent: [], neTypesCovered: ['zte.ran.enodeb'], ratsCovered: ['2G', '3G', '4G'] },
    tt: {
      levelRules: [],
      dispatchRules: [],
      pushRules: [],
      catchAll: { id: '230', name: 'TT-lowest severity', severity: 'P4', condition: "AND eflow_ticket_ticket_asset.vipSite in '0, 1' (enums)" },
      // 真实规则表里的 #164：ttDispatchRule / step=autoDispatch / 条件为空 → 对任何码生效
      catchAllDispatch: { id: '164', name: 'TT单直接派FO accept', status: 'ACTIVE', priority: '3', step: 'autoDispatch', condition: '' },
      stopped: [],
      parentRules: [],
    },
    ...over,
  };
}

/** 没有无条件兜底派发的场景（用来验证「确实没有建单路径」的措辞）。 */
function noDispatch(over = {}) {
  const base = fake();
  return { ...base, tt: { ...base.tt, catchAllDispatch: null }, ...over };
}

console.log('A. 渲染（离线）:');

// A1 没配专门规则：压缩与建单是两条链路，结论必须分开下。
// 「没配压缩规则」≠「不建单」—— #164 无条件兜底会把任何码派进 FO 线。
const none = renderEflowRuleAnswer(fake(), 'en', 'both');
check(none.includes('Compression: none'), 'EN 未配置 → 明说 no compression', none);
check(none.includes('#164'), 'EN 未配置 → 建单问题答出兜底派发 #164（旧实现整段丢）', none);
check(/Ticket: yes/i.test(none), 'EN 未配置 → 建单结论是「会建 TT」而不是「不支持」', none);
check(none.includes('Conclusion (compression)') && /not compressed/.test(none), 'EN 未配置 → 压缩结论=不压缩', none);
check(
  /"not configured" here means "no dedicated routing", not "no ticket"/.test(none),
  'EN 未配置 → 明确区分「没专门路径」与「不建单」',
  none
);
check(none.includes('10 enabled alarm-correlation rules'), 'EN 结论带「核对了多少条规则」', none);
check(!none.includes('eflow_ticket_ticket_'), 'EN 兜底条件已压成人话（不吐字段全名）', none);
check(/masking\/filter rules are not in the export/.test(none), 'EN 给出边界：屏蔽规则不在导出范围', none);

const noneZh = renderEflowRuleAnswer(fake(), 'zh', 'both');
check(noneZh.includes('压缩：没有') && noneZh.includes('建单：会'), 'ZH 未配置 → 压缩=没有、建单=会', noneZh);
check(noneZh.includes('#164'), 'ZH 未配置 → 指出兜底派发 #164', noneZh);
check(
  /「没配置」指\*\*没有专门处理路径\*\*，不等于「不建单」/.test(noneZh),
  'ZH 未配置 → 明确区分「没专门路径」与「不建单」',
  noneZh
);
check(renderEflowRuleAnswer(noDispatch(), 'zh', 'tt').includes('vipSite = 0 or 1'), 'ZH 兜底条件渲染成 vipSite = 0 or 1');

// A1b 没有无条件兜底派发时，才可以说「没有建单路径」
const noDp = renderEflowRuleAnswer(noDispatch(), 'en', 'both');
check(/no auto-ticket path found/i.test(noDp), 'EN 无兜底派发 → 结论=没有建单路径', noDp);

// A2 子告警：压进父告警，TT 建在父告警上
const child = fake({
  compression: {
    asChild: [{ ruleId: 'r1', ruleName: 'zte-4g-siteoutage', status: 'ENABLED', role: 'site_child', parentCode: '9970', parentName: '4G site down' }],
    asParent: [],
    neTypesCovered: [],
    ratsCovered: ['4G'],
  },
  tt: { ...fake().tt, parentRules: [{ code: '9970', levelRules: [{ id: '227', severity: 'P2' }], dispatchRules: [], pushRules: [] }] },
});
const childTxt = renderEflowRuleAnswer(child, 'en', 'both');
check(childTxt.includes('folded into parent alarm 9970'), 'EN 子告警 → 压进父告警 9970', childTxt);
check(childTxt.includes('#227'), 'EN 子告警 → 定级取父告警的规则', childTxt);
check(!/not supported/i.test(childTxt), 'EN 子告警 → 不能给「不支持」这种一刀切结论', childTxt);

// A3 父告警本身
const parent = fake({
  compression: { asChild: [], asParent: [{ ruleName: 'mpf-outage', status: 'ENABLED' }], neTypesCovered: [], ratsCovered: [] },
  tt: { ...fake().tt, levelRules: [{ id: '227', severity: 'P2' }] },
});
const parentTxt = renderEflowRuleAnswer(parent, 'en', 'both');
check(parentTxt.includes('derived parent alarm'), 'EN 父告警 → 说明「本身是衍生父告警」', parentTxt);

// A4 只有停用规则
const disabledOnly = fake({
  compression: { asChild: [{ ruleName: 'zte-4g-outage-new', status: 'DISABLED', role: 'site_child', parentCode: '9970' }], asParent: [], neTypesCovered: [], ratsCovered: [] },
});
check(
  renderEflowRuleAnswer(disabledOnly, 'en', 'compress').includes('DISABLED rule'),
  'EN 只有停用规则 → 说明停用=不生效',
  renderEflowRuleAnswer(disabledOnly, 'en', 'compress')
);

// A5 只问压缩时不该答建单
check(!renderEflowRuleAnswer(fake(), 'en', 'compress').includes('Ticket:'), 'parts=compress → 不答建单');

// A6 通道不可用：绝不能出现「没配 / not configured」
const unavailable = renderEflowRuleUnavailable('en', 'rules_missing');
check(!/not configured|not supported/i.test(unavailable), 'EN 通道不可用 → 不得说「没配/不支持」', unavailable);
check(/can'?t confirm|cannot confirm/i.test(unavailable), 'EN 通道不可用 → 明说「分不清没配还是没查到」', unavailable);
check(!/没有配|不支持/.test(renderEflowRuleUnavailable('zh', 'timeout')), 'ZH 通道不可用 → 不得说「没配/不支持」');

/* ------------------------- 路由（离线） ------------------------- */

console.log('\n路由:');
const Q = 'How will Alarm Code 200201001 be compressed, and will a service ticket be automatically generated?';
const r1 = parseLookupIntent(Q, { alarmCodes: new Map(), compress: [], levelRules: [], aliases: {} });
check(r1?.tool === 'lookup_eflow_rule' && r1.args.parts === 'both', '压缩+建单复合问法 → lookup_eflow_rule(parts=both)', JSON.stringify(r1));

const r2 = parseLookupIntent('Will alarm 99933 create a ticket automatically?', { alarmCodes: new Map(), compress: [], levelRules: [], aliases: {} });
check(r2?.tool === 'lookup_eflow_rule' && r2.args.parts === 'tt', '只问自动建单 → lookup_eflow_rule(parts=tt)（旧实现会当成「含义」）', JSON.stringify(r2));

const r3 = parseLookupIntent('198094422 会被压缩成什么', { alarmCodes: new Map(), compress: [], levelRules: [], aliases: {} });
check(r3?.tool === 'lookup_compress', '只问压缩 → 仍走 lookup_compress（本地快照快）', JSON.stringify(r3));

const r4 = parseLookupIntent('今天有几个 P1 的 ticket', { alarmCodes: new Map(), compress: [], levelRules: [], aliases: {} });
check(r4?.tool !== 'lookup_eflow_rule', '无告警码的 ticket 统计问法 → 不误判成规则查询', JSON.stringify(r4));

/* ------------------------- B. 联机（规则表在才跑） ------------------------- */

const hasRules =
  fs.existsSync(path.join(RULES_DIR, 'eflow_alarm_rules.xlsx')) &&
  fs.existsSync(path.join(RULES_DIR, 'eflow_push_rules.xlsx'));

if (!hasRules) {
  console.log(`\nB. 联机：跳过（规则表不在 ${RULES_DIR}）`);
} else {
  console.log('\nB. 联机（真实 eFlow 规则导出）:');

  const a = await lookupEflowRules('200201001');
  check(a.ok, '200201001 → 脚本可读规则表', JSON.stringify(a).slice(0, 200));
  if (a.ok) {
    check(a.data.compression.asChild.length === 0, '200201001 不在任何压缩规则的子告警清单里');
    check(a.data.tt.levelRules.length === 0, '200201001 没有 ACTIVE 定级规则引用');
    check(
      a.data.tt.catchAllDispatch && a.data.tt.catchAllDispatch.id === '164',
      '200201001 → 识别出无条件兜底派发 #164（否则会把「会建单」答成「不支持」）',
      JSON.stringify(a.data.tt.catchAllDispatch)
    );
    const txt = renderEflowRuleAnswer(a.data, 'en', 'both');
    check(/not compressed/.test(txt), '200201001 → 结论：不压缩', txt);
    check(/Ticket: yes/i.test(txt) && txt.includes('#164'), '200201001 → 结论：会建 TT，走兜底派发 #164', txt);
    check(!/not supported/i.test(txt), '200201001 → 不得给「不支持」这种一刀切结论', txt);
  }

  const b = await lookupEflowRules('9970');
  if (b.ok) {
    const parents = b.data.compression.asChild.filter((h) => h.status === 'ENABLED').map((h) => h.parentCode);
    check(parents.includes('99933'), '9970 → 会压进 99933（电源断站）', parents.join(','));
    check(b.data.compression.asParent.some((h) => h.status === 'ENABLED'), '9970 → 同时识别为父告警');
  }

  const c = await lookupEflowRules('199087342');
  if (c.ok) {
    const lv = c.data.tt.levelRules.map((r) => `${r.id}/${r.severity}`);
    check(lv.some((x) => x.startsWith('199/')), '199087342 → 定级规则 #199 命中', lv.join(','));
    check(!c.data.tt.stopped.some((r) => r.status === 'ACTIVE'), '停用规则不会混进 ACTIVE 结论');
  }
}

console.log(`\n${fail === 0 ? '✓ 全部通过' : '✗ 有失败'}：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
