#!/usr/bin/env node
/**
 * 站点属性渲染测试（**纯离线** —— 不联网、不查库）。
 *   node scripts/test-siteattr.mjs
 *
 * 背景（2026-11-03 实测故障）
 * --------------------------
 * 问「站点 lofa bridge 是 VIP 站点吗」，机器人答：
 *   「是 VIP 站点。依据：该站点的 assetType 为 vipSite，即 VIP 站（ticket_asset = 1）。」
 * 三重错误：
 *   · 结论错 —— 该站 vipsite 实为 No（三处独立数据源一致）；
 *   · 依据错 —— assetType 的合法取值只有 NORMAL/COOL/ERA，没有 vipSite；
 *   · 来源错 —— 引的是讲「级别怎么定」的规则文档，里面一个站点名都没有。
 *
 * 所以这里测的是**渲染层的三条纪律**：
 *   ① VIP 结论必须原样取自数据（is_vip），不得被改写成别的口径；
 *   ② 三处数据源打架时必须**如实报冲突**（不能挑一个顺眼的报）；
 *   ③ 走本地副本降级时必须标注口径（不能让用户以为看到的是实时值）。
 */
import { renderSiteAttribute } from '../src/siteattr.js';

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

console.log('='.repeat(50));
console.log('站点属性渲染测试（离线）');
console.log('='.repeat(50));

/* --------------------------- 非 VIP 站（Lofa Bridge） --------------------------- */

console.log('\n[1] 非 VIP 站：结论必须来自数据，不能反着说');
{
  // 这是 app.db 里 Lofa Bridge 的真实取值（2026-11-03 实测）
  const d = {
    site: 'Lofa Bridge',
    found: true,
    site_id: '4652',
    site_name: 'Lofa Bridge',
    is_vip: false,
    consistency: 'agree',
    vip_sources: { eflow_site: false, master_site_db: false, vip_site_list: null },
    site_type: 'NORMAL',
    site_sub_type: 'REGULAR',
    is_hub_site: true,
    region: 'South West',
    province: 'Grand Cape Mount',
    site_information: 'REGULAR',
    site_priority: 'P2',
    site_class: 'P2',
    is_ran_site: true,
    victims: 4,
    fme_name: 'Julius K. Johnson',
    source: 'http',
  };
  const zh = renderSiteAttribute(d, 'zh', false);

  check(zh.includes('不是 VIP 站点'), '明确说「不是 VIP 站点」', zh);
  // ⚠️ 不能直接查「是 VIP 站点」—— 它是「不是 VIP 站点」的子串，会误判。
  // 精确判定：去掉所有「不是 VIP 站点」后不得再出现「是 VIP 站点」。
  check(!zh.replace(/不是 VIP 站点/g, '').includes('是 VIP 站点'),
    '不能出现「是 VIP 站点」这种反向表述', zh);
  check(zh.includes('NORMAL'), '站点类型原样出现（NORMAL）', zh);
  check(zh.includes('REGULAR'), '站点子类型原样出现（REGULAR）', zh);
  check(zh.includes('枢纽站'), '枢纽站标记出现', zh);
  check(zh.includes('4652'), '站号出现', zh);
  check(zh.includes('实时'), 'HTTP 通道标注实时口径', zh);
  check(!zh.includes('本地站点库副本'), '实时通道不该标「本地副本」', zh);

  // ⚠️ 最关键的一条：不得出现「assetType = vipSite」这种编造依据
  check(!/assetType\s*=\s*vipSite/i.test(zh), '不得出现「assetType = vipSite」这种编造依据', zh);
  check(!/ticket_asset\s*=\s*1/i.test(zh), '不得出现「ticket_asset = 1」这种编造依据', zh);

  const en = renderSiteAttribute(d, 'en', false);
  check(en.includes('is not a VIP site'), '英文也明确说 not a VIP site', en);
  check(!en.includes('是 VIP'), '英文回复里不应混进中文', en);
}

/* ------------------------------- 真 VIP 站 ------------------------------- */

console.log('\n[2] 真 VIP 站：结论要正面且属性齐全');
{
  const d = {
    site: 'Palm Bay',
    found: true,
    site_id: '1234',
    site_name: 'Palm Bay',
    is_vip: true,
    consistency: 'agree',
    vip_sources: { eflow_site: true, master_site_db: true, vip_site_list: true },
    site_type: 'NORMAL',
    site_sub_type: 'ERA',
    is_hub_site: false,
    region: 'South West',
    province: 'Grand Cape Mount',
    victims: 120,
    source: 'http',
  };
  const zh = renderSiteAttribute(d, 'zh', false);
  check(zh.includes('是 VIP 站点'), '明确说「是 VIP 站点」', zh);
  check(!zh.includes('不是 VIP'), '不能同时出现否定表述', zh);
  check(zh.includes('ERA'), '子类型 ERA 出现', zh);
  check(zh.includes('120'), '影响用户数出现', zh);
  // ⚠️ 「非枢纽站」里含「枢纽站」子串 —— 先去掉否定形式再判定。
  check(!zh.replace(/非枢纽站/g, '').includes('枢纽站'),
    '非枢纽站不该出现「枢纽站」字样（去掉「非枢纽站」后判定）', zh);
}

/* --------------------------- 三处数据源冲突 --------------------------- */

console.log('\n[3] 数据源冲突：必须如实报出分歧');
{
  const d = {
    site: 'Some Site',
    found: true,
    site_id: '999',
    site_name: 'Some Site',
    is_vip: false,
    consistency: 'conflict',
    vip_sources: { eflow_site: false, master_site_db: false, vip_site_list: true },
    site_type: 'NORMAL',
    source: 'http',
  };
  const zh = renderSiteAttribute(d, 'zh', false);
  check(zh.includes('不一致'), '冲突要明说「不一致」', zh);
  check(zh.includes('VIP 名单'), '冲突说明里要提到 VIP 名单', zh);
  check(zh.includes('以 eFlow 站点属性（主口径）为准'), '冲突要说明以哪个口径为准', zh);
}

/* ------------------------------- 查无此站 ------------------------------- */

console.log('\n[4] 查无此站：不能说「不是 VIP」（那是把「未知」说成「否定」）');
{
  const d = {
    site: 'ZZZ不存在的站',
    found: false,
    is_vip: null,
    consistency: 'unknown',
    vip_sources: {},
    candidates: ['Lofa Bridge', 'Lofa Bridge Camp'],
    source: 'http',
  };
  const zh = renderSiteAttribute(d, 'zh', false);
  check(zh.includes('查不到'), '明确说查不到', zh);
  check(!zh.includes('不是 VIP'), '查无此站不能被说成「不是 VIP」', zh);
  check(!zh.includes('是 VIP'), '查无此站不能被说成「是 VIP」', zh);
  check(zh.includes('Lofa Bridge'), '给出相近站名供核对', zh);
}

/* ------------------------------- 降级口径 ------------------------------- */

console.log('\n[5] 降级：必须标注「本地副本」，不能让用户以为是实时值');
{
  const d = {
    site: 'Lofa Bridge',
    found: true,
    site_id: '4652',
    site_name: 'Lofa Bridge',
    is_vip: false,
    consistency: 'agree',
    vip_sources: { eflow_site: false, master_site_db: false, vip_site_list: null },
    site_type: 'NORMAL',
    site_sub_type: 'REGULAR',
    is_hub_site: true,
    source: 'sqlite',
  };
  const zh = renderSiteAttribute(d, 'zh', true);
  check(zh.includes('本地站点库副本'), '降级时标注本地副本', zh);
  check(zh.includes('延迟'), '降级时说明可能有延迟', zh);
  // 用「（实时）」这个带括号的整串来判定 —— 降级口径写的是「非实时」，
  // 若直接查「实时」会命中「非实时」里的子串，断言就废了。
  check(!zh.includes('（实时）'), '降级时不得出现「（实时）」口径', zh);
  check(zh.includes('不是 VIP 站点'), '降级时结论本身仍然正确', zh);

  // ⚠️ 口径判定的**双保险**：即使调用方忘了传 degraded=true，
  // 只要数据里 source='sqlite'，也必须标成本地副本。
  // 2026-11-03 实测过一次：正文标「实时」而日志标「本地副本」。
  const zh2 = renderSiteAttribute(d, 'zh', false); // degraded 传 false，但 source 是 sqlite
  check(zh2.includes('本地站点库副本'), 'source=sqlite 时即便 degraded=false 也标副本', zh2);
  check(!zh2.includes('（实时）'), 'source=sqlite 时不得出现「（实时）」', zh2);
}

/* ------------------------------- VIP 未知 ------------------------------- */

console.log('\n[6] VIP 属性未知：不能猜');
{
  const d = {
    site: 'X',
    found: true,
    site_name: 'X',
    is_vip: null,
    consistency: 'unknown',
    vip_sources: { eflow_site: null, master_site_db: null, vip_site_list: null },
    source: 'http',
  };
  const zh = renderSiteAttribute(d, 'zh', false);
  check(zh.includes('未知'), '未知就说未知', zh);
  check(!zh.includes('不是 VIP'), '未知不能渲染成「不是 VIP」', zh);
  check(!zh.includes('是 VIP 站点'), '未知不能渲染成「是 VIP 站点」', zh);
}

/* -------------------------------- 结果 -------------------------------- */

console.log(`\n${'='.repeat(50)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
