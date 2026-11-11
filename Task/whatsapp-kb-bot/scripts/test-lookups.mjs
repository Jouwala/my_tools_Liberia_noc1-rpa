#!/usr/bin/env node
/**
 * 查表工具单测（**纯离线**，读仓库内 knowledge md，不联网不调模型）。
 *   node scripts/test-lookups.mjs
 *
 * 覆盖这次改造的**最大杠杆**：告警码含义 / 压缩结果 / 级别规则三类问法
 * 必须走脚本查表、模板渲染、带出处，**不经 LLM 自由生成**。
 *
 * 最要紧的几条：
 *   ① 解析器能从真实 md 抽出码表 / 压缩 / 级别规则；
 *   ② parseByRule 把「会被压缩成什么」判成 lookup，不是统计、不是知识库；
 *   ③ 渲染带来源文件名、不含 Markdown 标题 `#`；
 *   ④ 未收录的码 → 固定文案拒答，不猜。
 */
import { CONFIG } from '../src/config.js';
import {
  buildLookups, findAlarmCode, findCompress, findLevelByCode, findLevelBySeverity,
  resolveCodeByName, buildAliases, parseSiteAttrs, filterLevelRulesByAttrs, stripKnownAttrLabels,
  renderAlarmCode, renderCompress, renderLevelRules, renderNotFound,
} from '../src/lookups.js';
import { parseByRule, parseLookupIntent, runLookup } from '../src/tools.js';

// 关掉工具路由的副作用（本测只测纯函数）；不影响 parseByRule 本身的返回值。
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

const NOW = new Date(2026, 9, 6);

console.log('='.repeat(50));
console.log('查表工具测试（离线）');
console.log('='.repeat(50));

const L = buildLookups(CONFIG.knowledgeDirAbs, process.cwd());

/* ------------------------------ 解析 ------------------------------ */

console.log('\n[1] 解析真实 knowledge/*.md');
{
  check(L.alarmCodes.size > 0, `告警码字典解析出 ${L.alarmCodes.size} 条`, `size=${L.alarmCodes.size}`);
  check(L.compress.length > 0, `压缩规则解析出 ${L.compress.length} 条`);
  check(L.levelRules.length > 0, `级别规则解析出 ${L.levelRules.length} 条`);

  const c99933 = findAlarmCode(L, '99933');
  check(c99933 && /SITE DOWN|POWER/.test(c99933.name), '99933 → 名称含 SITE DOWN / POWER', JSON.stringify(c99933));
  check(c99933 && c99933.source.includes('告警码字典'), '  带出处文件名', JSON.stringify(c99933?.source));

  const comp = findCompress(L, '198094422');
  check(comp.length > 0 && comp[0].parentCode === '9970', '198094422 → 父码 9970', JSON.stringify(comp.map((r) => [r.ruleId, r.parentCode, r.status])));
  check(comp[0].status === 'ENABLED', '  ENABLED 规则排在最前', comp[0]?.status);
}

/* ------------------------------ 意图识别 ------------------------------ */

console.log('\n[2] parseByRule 分流（查表 vs 统计 vs 知识）');
{
  const c1 = parseByRule('告警码 198094422 会被压缩成什么', NOW);
  check(c1 && c1.tool === 'lookup_compress', '「会被压缩成什么」→ lookup_compress', JSON.stringify(c1));
  check(c1 && c1.args.code === '198094422', '  码解析正确', JSON.stringify(c1?.args));

  const c2 = parseByRule('99933 是什么意思', NOW);
  check(c2 && c2.tool === 'lookup_alarm_code', '「是什么意思」→ lookup_alarm_code', JSON.stringify(c2));

  const c3 = parseByRule('what is alarm code 9920', NOW);
  check(c3 && c3.tool === 'lookup_alarm_code' && c3.args.code === '9920', '英文含义问法', JSON.stringify(c3));

  const c4 = parseByRule('告警码 9990 NORMAL 非 VIP 是几级', NOW);
  check(c4 && c4.tool === 'lookup_level_rule', '「是几级」→ lookup_level_rule', JSON.stringify(c4));

  const c5 = parseByRule('P1 是什么级别', NOW);
  check(c5 && c5.tool === 'lookup_level_rule', '「P1 是什么级别」→ lookup_level_rule', JSON.stringify(c5));
  check(c5 && !c5.args.code, '  无码走 severity 分支', JSON.stringify(c5?.args));
  check(c5 && c5.args.severity === 'P1', '  severity=P1', JSON.stringify(c5?.args));

  // 关键：不得被当成统计（test-tools.mjs [3] q8 同样要求）
  check(!(c1 && c1.tool === 'query_tickets'), '压缩问法**不是**统计');

  // 有数量词时仍走统计（不能被查表抢走）
  const stat = parseByRule('今天有p1的单子吗', NOW);
  check(stat && stat.tool === 'query_tickets', '统计意图不被查表误伤', JSON.stringify(stat));

  // 单号最优先
  const tt = parseByRule('分析 TT202609150073', NOW);
  check(tt && tt.tool === 'analyze_ticket', '单号仍最优先', JSON.stringify(tt));
}

console.log('\n[2b] parseLookupIntent 边界');
{
  check(parseLookupIntent('198094422 会被压缩成什么')?.tool === 'lookup_compress', '长码 + 压缩');
  check(parseLookupIntent('这个告警码代表什么') === null, '无码 → null（交模型/知识库）');
  check(parseLookupIntent('P1 规则有哪些')?.tool === 'lookup_level_rule', 'P1 规则 → 级别');
  check(parseLookupIntent('今天有几个单') === null, '纯统计 → null');
  // 短数字不该被误当告警码
  check(parseLookupIntent('3G 小区退服是什么') === null, '「3G」短数字不误判', JSON.stringify(parseLookupIntent('3G 小区退服是什么')));
}

/* ------------------------------ 渲染 ------------------------------ */

console.log('\n[3] 渲染：带出处、无 Markdown 标题');
{
  const zh = renderAlarmCode(findAlarmCode(L, '99933'), 'zh');
  check(zh.includes('99933') && zh.includes('来源：'), '告警码渲染带「来源：」', JSON.stringify(zh));
  check(!/^#/m.test(zh), '  不含 Markdown 标题 #');

  const cmp = renderCompress(findCompress(L, '198094422'), '198094422', 'zh');
  check(cmp.includes('9970') && cmp.includes('来源：'), '压缩渲染含 9970 与来源', JSON.stringify(cmp));
  check(cmp.includes('ENABLED'), '  含规则状态');
  check(!/^#/m.test(cmp), '  不含 Markdown 标题 #');

  const lvl = renderLevelRules(findLevelByCode(L, '9990'), 'zh', { code: '9990' });
  check(lvl.includes('来源：'), '级别渲染带来源');
  check(lvl.includes('未做完整规则引擎匹配'), '  如实注明「未做完整匹配」', JSON.stringify(lvl.slice(0, 200)));
  check(!/^#/m.test(lvl), '  不含 Markdown 标题 #');

  // 英文渲染（界面文案无中文；**数据字段/出处文件名保留原文**，
  // 与 TT 通道「数据行不翻译」一致 —— 见 README 回复语言节）
  const en = renderAlarmCode(findAlarmCode(L, '99933'), 'en');
  check(en.includes('Source:'), '英文渲染带 Source:', JSON.stringify(en));
  const enBody = en.split('\n').filter((l) => !l.startsWith('Source:')).join('\n');
  check(!/[一-龥]/.test(enBody), '  英文界面文案不含中文（出处文件名除外）', JSON.stringify(enBody));
}

console.log('\n[4] 未收录 → 固定文案拒答，不猜');
{
  const zh = renderNotFound('alarm', '12345', 'zh');
  check(zh.includes('12345') && /不会.*猜|没有/.test(zh), '中文拒答文案', JSON.stringify(zh));
  const en = renderNotFound('compress', '12345', 'en');
  check(en.includes('12345') && /won't guess/i.test(en), '英文拒答文案', JSON.stringify(en));
  check(findAlarmCode(L, '99999999') === null, '未收录码返回 null');
  check(findCompress(L, '1').length === 0, '未收录压缩码返回空');
}

console.log('\n[5] 级别规则列表（P1 给规则清单，不编定义）');
{
  const p1 = findLevelBySeverity(L, 'P1');
  check(p1.length > 0, `P1 规则 ${p1.length} 条`, JSON.stringify(p1.map((r) => r.id)));
  // 规则表已换成现行规则集（266~277）：P1 两条是 #266 HUB site P1 / #267 VIP site P1。
  check(p1.some((r) => r.id === '266' || r.id === '267'), '含规则 266/267');
  check(p1.every((r) => r.severity === 'P1'), '全部是 P1');
}

CONFIG.toolsEnabled = ORIG;

/* --------------------- 风险处理：无码问法 + 属性过滤 --------------------- */

console.log('\n[6] 告警名/缩写 → 码（无数字码也能查表）');
{
  // 手册 §3.3：「CSD 定几级」没有长数字，向量会召回错行
  check(resolveCodeByName(L, 'CSD 定几级') === '9920', 'CSD → 9920', resolveCodeByName(L, 'CSD 定几级'));
  check(resolveCodeByName(L, '4G site down 是什么级别') === '9970', '4G site down → 9970');
  check(resolveCodeByName(L, 'MW LINK DOWN 是几级') === '9995', 'MW LINK DOWN → 9995');
  check(resolveCodeByName(L, 'Fiber Break 是什么告警') === '4758', 'Fiber Break → 4758（X/Y 型名称分段）');
  check(resolveCodeByName(L, '完全无关的一句话') === '', '无匹配 → 空串');

  const c1 = parseLookupIntent('CSD 定几级', L);
  check(c1 && c1.tool === 'lookup_level_rule' && c1.args.code === '9920', '「CSD 定几级」→ lookup_level_rule(9920)', JSON.stringify(c1));
  const c2 = parseLookupIntent('Fiber Break 是什么告警', L);
  check(c2 && c2.tool === 'lookup_alarm_code' && c2.args.code === '4758', '「Fiber Break 是什么告警」→ 码 4758', JSON.stringify(c2));
  // 无意图词的普通叙述不能误触发
  check(parseLookupIntent('CSD 是什么意思呢', L)?.tool === 'lookup_alarm_code', 'CSD + 含义 → 含义');
  check(parseLookupIntent('今天天气怎么样', L) === null, '无关句 → null');
}

console.log('\n[7] 站点属性过滤（只过滤条件写明的冲突行）');
{
  const a = parseSiteAttrs('告警码 9990 NORMAL 非 VIP 是几级');
  check(a.assetType === 'NORMAL' && a.vipSite === '0', 'NORMAL + 非VIP 解析', JSON.stringify(a));
  const b = parseSiteAttrs('告警码 9990 COOL 是几级');
  check(b.assetType === 'COOL' && b.vipSite === undefined, 'COOL（未提 VIP）', JSON.stringify(b));
  const c = parseSiteAttrs('告警码 9990 ERA 是几级');
  check(c.siteSubType === 'ERA', 'ERA 解析', JSON.stringify(c));
  check(Object.keys(parseSiteAttrs('告警码 9990 是几级')).length === 0, '无属性 → 空对象（不过滤）');

  const all9990 = findLevelByCode(L, '9990');
  const normal = filterLevelRulesByAttrs(all9990, { assetType: 'NORMAL', vipSite: '0' });
  check(!normal.some((r) => r.id === '270'), 'NORMAL 过滤掉 #270(COOL)', JSON.stringify(normal.map((r) => r.id)));
  check(normal.some((r) => r.id === '269'), '  保留 #269(NORMAL)');
  const cool = filterLevelRulesByAttrs(all9990, { assetType: 'COOL', vipSite: '0' });
  check(cool.some((r) => r.id === '270') && !cool.some((r) => r.id === '269'), 'COOL 保留 #270、过滤 #269', JSON.stringify(cool.map((r) => r.id)));
  check(filterLevelRulesByAttrs(all9990, {}).length === all9990.length, '无属性 → 不过滤', `${filterLevelRulesByAttrs(all9990, {}).length}/${all9990.length}`);

  // 端到端：runLookup 用 opts.question 做过滤（staticOnly 跳过 B5 子进程）
  const r = await runLookup({ tool: 'lookup_level_rule', args: { code: '9990' } }, 'zh', { lookups: L, question: '告警码 9990 COOL 非VIP 是几级', staticOnly: true });
  check(r.text.includes('#270') && !r.text.includes('#269'), 'runLookup 按属性过滤', JSON.stringify(r.text.match(/#\d+/g)));
}

console.log('\n[8] 标签式属性抽取（eFlow 列名照抄 + 中文疑问写法）');
{
  // ① eFlow 界面列名（值班员原样粘贴）
  const e = parseSiteAttrs('RAN Site Type：REGULAR；Site VIP Level：YES；Hub Site Flag：YES；Downstream Site Count：7');
  check(e.siteSubType === 'REGULAR', '列名 RAN Site Type → siteSubType', JSON.stringify(e));
  check(e.vipSite === '1', '列名 Site VIP Level → vipSite=1', JSON.stringify(e));
  check(e.hubSite === '1', '列名 Hub Site Flag → hubSite=1', JSON.stringify(e));
  check(e.downSiteCount === '7', '列名 Downstream Site Count → downSiteCount=7', JSON.stringify(e));
  check(e.downstreamSites === undefined, '列名 Downstream Site Count **不**算 downstreamSites（两个字段不能混）', JSON.stringify(e));

  // ② 中文疑问写法（2026-11-10 线上验证踩到：漏 hubSite → #266/#268/#277 全判不出）
  const z = parseSiteAttrs('RAN站点类型：REGULAR；是否VIP站：是；是否枢纽站：是；Downstream Site Count：7');
  check(z.siteSubType === 'REGULAR', '「RAN站点类型：REGULAR」→ siteSubType', JSON.stringify(z));
  check(z.vipSite === '1', '「是否VIP站：是」→ vipSite=1', JSON.stringify(z));
  check(z.hubSite === '1', '「是否枢纽站：是」→ hubSite=1', JSON.stringify(z));

  // ③ 疑问写法的「否」不能被裸值兜底翻成 1（否则级别直接算高）
  const neg = parseSiteAttrs('是否VIP站：否');
  check(neg.vipSite === '0', '「是否VIP站：否」→ vipSite=0（不是裸值兜底的 1）', JSON.stringify(neg));
  const negHub = parseSiteAttrs('是否枢纽站：否');
  check(negHub.hubSite === '0', '「是否枢纽站：否」→ hubSite=0', JSON.stringify(negHub));

  // ④ 下属站点数与断站数仍是两个字段
  const ds = parseSiteAttrs('下属站点总数：6；断站数：7');
  check(ds.downstreamSites === '6' && ds.downSiteCount === '7', '下属站点总数 ≠ 断站数', JSON.stringify(ds));

  // ⑤ 剥标签：eFlow 列名要剥掉（"Downstream Site Count" 含 Count，会被统计通道抢走），
  //    但 "alarm code" 不在标签表里，必须保留。
  const stripped = stripKnownAttrLabels('…；Downstream Site Count：7，alarm code:9995. which kind of TT?');
  check(!stripped.includes('Downstream Site Count'), '剥掉 Downstream Site Count', stripped);
  check(stripped.includes('alarm code:9995'), '保留 alarm code:9995', stripped);
}

console.log('\n[9] 「会建什么 TT」答案（2026-11-10 重写：结论式 + 口径提示 + 属性过滤）');
{
  const { filterRulesByAttrs } = await import('../src/eflowRules.js');
  const rules = [
    { id: '200', name: 'Regular电源故障推送TT到IPT', target: '3rd_Power(group)', condition: "AND eflow_ticket_ticket_asset.siteSubType = 'REGULAR' (enums); AND eflow_ticket_ticket_wo.reasonType in 'POWER' (string)" },
    { id: '201', name: 'Regular断站故障手动到FO', target: 'ZTE_FE_FE(group); ZTE_NOC_FO(group)', condition: "AND eflow_ticket_ticket_asset.siteSubType = 'REGULAR' (enums); AND eflow_ticket_ticket_wo.reasonType not in 'POWER' (string)" },
    { id: '203', name: 'ERA断站推单到ZTE WO', target: 'ZTE_NOC_FO(group)', condition: "AND eflow_ticket_ticket_asset.siteSubType = 'ERA' (string);" },
  ];

  // ① 只排除「条件里写明冲突取值」的规则；条件没提该字段的一律保留
  const reg = filterRulesByAttrs(rules, { siteSubType: 'REGULAR' });
  check(reg.kept.map((r) => r.id).join(',') === '200,201', 'REGULAR 站排除 ERA 专用 #203', `保留=${reg.kept.map((r) => r.id)}`);
  check(reg.dropped.map((r) => r.id).join(',') === '203', '  被排除的规则能报出 id（渲染时会写原因）');
  const era = filterRulesByAttrs(rules, { siteSubType: 'ERA' });
  check(era.kept.map((r) => r.id).join(',') === '203', 'ERA 站只保留 #203');
  check(filterRulesByAttrs(rules, {}).kept.length === 3, '没给属性 → 不过滤（吃不准就不排除）');

  // ② `not in` 的语义要反过来：条件写 not in 'ERA'，用户给 ERA → 冲突
  const neg = [{ id: 'x', condition: "AND eflow_ticket_ticket_asset.siteSubType not in 'ERA' (enum)" }];
  check(filterRulesByAttrs(neg, { siteSubType: 'ERA' }).dropped.length === 1, 'not in：给了禁用值 → 排除');
  check(filterRulesByAttrs(neg, { siteSubType: 'REGULAR' }).kept.length === 1, 'not in：给了允许值 → 保留');

  // ③ 路由：群里那句原始问法必须进级别规则通道（不是统计/站点属性）
  const Q =
    'Site Type：REGULAR；Site VIP Level：YES；Hub Site Flag：YES；Downstream Site Count：7，alarm code:9995. which kind of TT will be creadted?';
  const routed = parseByRule(Q, NOW);
  check(
    routed?.tool === 'lookup_level_rule' && routed?.args?.code === '9995',
    '原句 → lookup_level_rule(9995)',
    JSON.stringify(routed)
  );

  // ④ 端到端答案：级别用条件式结论、不把断站数当下属站点数、按属性过滤推单规则
  //    需要 python 规则引擎 + eFlow 规则导出；两者不可用时跳过（环境问题，不算失败）。
  const res = await runLookup({ tool: 'lookup_level_rule', args: { code: '9995' } }, 'en', { lookups: L, question: Q });
  const t = res.text || '';
  const envMissing = /rule engine is unavailable|eFlow rule config is unreadable/.test(t);
  if (envMissing) {
    console.log('  · SKIP 端到端答案：python 规则引擎或 eFlow 规则导出不可用（环境问题）');
  } else {
    check(/a TT is created/.test(t), '开头先答「会建 TT」', t.slice(0, 120));
    check(/downstreamSites ≥ 5 → P1/.test(t), 'P1 条件写成「若 downstreamSites ≥ 5」');
    check(/2 ≤ downstreamSites ≤ 4 → P2/.test(t), 'P2 区间方向正确（2 ≤ x ≤ 4，不是 2 ≥ x ≤ 4）');
    check(!/2 ≥ downstreamSites/.test(t), '  区间没有写反');
    check(/otherwise → P4/.test(t), '兜底 P4 也给出');
    check(/hubSite=1/.test(t) && /downSiteCount 7 ≥ 5/.test(t), '用户给过的条件标成「已满足」');
    check(/not downstreamSites/.test(t), '点明「Downstream Site Count 不是 downstreamSites」');
    check(/reasonType ∉ \{POWER\}/.test(t), '推单条件解析出 not in（reasonType ∉ POWER）');
    check(/#203 ERA断站推单到ZTE WO excluded/.test(t), '#203 标为「已排除」并说明原因（REGULAR）');
    check(!/#203[^\n]*→/.test(t), '  已排除的 #203 不出现在适用规则里');
    check(/Source: eflow_push_rules\.xlsx/.test(t), '带规则表导出时间');
  }

  // ⑤ 中文答案：口径提示与「会建 TT」结论都要在，且不夹英文句式
  const resZh = await runLookup({ tool: 'lookup_level_rule', args: { code: '9995' } }, 'zh', { lookups: L, question: Q });
  const tz = resZh.text || '';
  if (!/规则引擎暂时不可用|eFlow 规则配置暂时读不到/.test(tz)) {
    check(/^告警码 9995（MW LINK DOWN）：会建 TT/.test(tz), '中文：先答「会建 TT」', tz.slice(0, 80));
    check(/级别：还定不了 —— 缺 downstreamSites/.test(tz), '中文：级别给条件式结论');
    check(/不是 downstreamSites/.test(tz), '中文：点明字段口径');
    check(/已排除/.test(tz) && /#203/.test(tz), '中文：排除的规则与原因都写了');
  }
}

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
