/**
 * 无浏览器验证 vmax_cxo_dashboard_daily.html（页签版）：
 *   ① 页签结构：Summary / Network(5 子) / Service(9 子)，默认 Summary，子页签条按需显隐
 *   ② 切页签/子页签：图表数量、旧图释放、表格列都跟着当前页签走
 *   ③ i18n：页签名/子页签名/表格/图例跟随外壳语言，英文下不允许出现任何中文
 *   ④ 顶部说明默认收起、点击展开/再收起
 *   ⑤ 后端不给 tabs（或只给 groups）时的兜底降级
 * 用 vm 沙箱隔离每轮，桩掉 document/window/localStorage/fetch/echarts/timers。
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const HTML = fs.readFileSync(path.join('frontend', 'public', 'vmax_cxo_dashboard_daily.html'), 'utf8');
const blocks = [...HTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.trim());
const JS = blocks.sort((a, b) => b.length - a.length)[0];
if (!JS) { console.error('FAIL: 未找到内联脚本'); process.exit(1); }

const NEW_GRID = JSON.parse(fs.readFileSync('_tmp_grid_new.json', 'utf8'));
const NEW_DAYS = JSON.parse(fs.readFileSync('_tmp_days_new.json', 'utf8'));
// 模拟线上旧后端：6 个两位 id、没有 tabs/groups/group/note
const OLD_GRID = JSON.parse(JSON.stringify(NEW_GRID));
OLD_GRID.kpis = OLD_GRID.kpis.filter(k => String(k.id).length <= 2).map(k => { const c = { ...k }; delete c.group; delete c.note; return c; });
delete OLD_GRID.groups; delete OLD_GRID.tabs;
// 中间态：只有 groups、没有 tabs
const GROUP_GRID = JSON.parse(JSON.stringify(NEW_GRID));
delete GROUP_GRID.tabs;

const CJK = /[\u3400-\u4dbf\u4e00-\u9fff]/;
let pass = 0, fail = 0;
function ok(cond, label, extra) {
  if (cond) { pass++; console.log('  PASS  ' + label); }
  else { fail++; console.log('  FAIL  ' + label + (extra !== undefined ? '  -> ' + extra : '')); }
}
const flush = () => new Promise(r => setImmediate(r));
const count = (s, re) => (String(s).match(re) || []).length;

function runPage({ grid, days, locale, tab, search }) {
  const ids = ['appTitle', 'appSub', 'notesToggle', 'notesLabel', 'cover', 'sections',
    'tblTitle', 'tbl', 'status', 'tabBar', 'subBar', 'carouselBtn', 'carouselStep'];
  const els = {};
  const make = id => ({
    id, textContent: '', innerHTML: '', className: '', style: {}, _attrs: {}, _listeners: {}, title: '',
    classList: { _s: new Set(), toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    setAttribute(k, v) { this._attrs[k] = String(v); },
    getAttribute(k) { return this._attrs[k]; },
    removeAttribute(k) { delete this._attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); },
    addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
  });
  ids.forEach(id => { els[id] = make(id); });
  if (/id="cover"[^>]*\shidden/.test(HTML)) els.cover._attrs.hidden = '';
  if (/id="carouselStep"[^>]*\shidden/.test(HTML)) els.carouselStep._attrs.hidden = '';

  const options = {}, stats = { init: 0, dispose: 0, setOption: 0 };
  const intervals = [], docL = {}, winL = {}, store = {};
  if (locale) store['app-locale'] = locale;
  if (tab) store['vmax-daily-tab'] = tab;

  const sandbox = {
    console,
    document: {
      documentElement: { dataset: {}, lang: '' },
      getElementById: id => els[id] || (els[id] = make(id)),
      addEventListener: (t, f) => { (docL[t] = docL[t] || []).push(f); },
    },
    window: { addEventListener: (t, f) => { (winL[t] = winL[t] || []).push(f); }, matchMedia: () => ({ matches: false }) },
    location: { search: search || '' },
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    URLSearchParams,
    fetch: url => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(String(url).includes('/days') ? days : grid) }),
    echarts: {
      init: el => {
        stats.init++;
        return {
          setOption(o) { stats.setOption++; options[el.id] = o; },
          dispose() { stats.dispose++; delete options[el.id]; },
          resize() { },
        };
      },
    },
    setTimeout: f => { try { if (typeof f === 'function') f(); } catch (e) { } return 0; },
    clearTimeout: () => { },
    setInterval: (f, ms) => { intervals.push({ f, ms, cleared: false }); return intervals.length; },
    clearInterval: h => { if (intervals[h - 1]) intervals[h - 1].cleared = true; },
  };
  sandbox.matchMedia = sandbox.window.matchMedia;
  sandbox.window.echarts = sandbox.echarts;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(JS, sandbox);
  return { els, options, stats, winL, docL, store, intervals };
}
/** 触发指定周期的定时器（页面用 setInterval 驱动轮播时钟与推进） */
const fireIntervals = (ctx, ms) => ctx.intervals.filter(x => x.ms === ms && !x.cleared).forEach(x => x.f());
const stepText = ctx => ctx.els.carouselStep.textContent;
const btnText = ctx => ctx.els.carouselBtn.textContent;
const post = (ctx, data) => { (ctx.winL.message || []).forEach(f => f({ data })); };
/** 触发页签/子页签的委托点击（真实 DOM 里 e.target.closest([data-x]) 命中按钮） */
function clickAttr(ctx, containerId, attr, value) {
  const el = ctx.els[containerId];
  const btn = { getAttribute: k => (k === attr ? value : null) };
  const ev = { target: { closest: sel => (sel === '[' + attr + ']' ? btn : null) } };
  (el._listeners.click || []).forEach(f => f.call(el, ev));
}
const series = (ctx, id) => { const o = ctx.options[id]; return o && o.series ? o.series.map(s => s.name) : null; };
const chartIds = ctx => Object.keys(ctx.options);
const tabsIn = ctx => (ctx.els.tabBar.innerHTML.match(/data-tab="([^"]+)"/g) || []).map(s => s.split('"')[1]);
const activeTabIn = ctx => { const m = ctx.els.tabBar.innerHTML.match(/class="active" data-tab="([^"]+)"/); return m ? m[1] : (ctx.els.tabBar.innerHTML.match(/data-tab="([^"]+)"[^>]*>/) ? null : null); };
const subsIn = ctx => (ctx.els.subBar.innerHTML.match(/data-sub="([^"]+)"/g) || []).map(s => s.split('"')[1]);
const activeSubIn = ctx => { const m = ctx.els.subBar.innerHTML.match(/class="active" data-sub="([^"]+)"/); return m ? m[1] : null; };
const thCount = ctx => count(ctx.els.tbl.innerHTML, /<th[ >]/g);

(async () => {
  console.log('=== A) 默认中文 + 50 指标 / 3 页签 ===');
  const A = runPage({ grid: NEW_GRID, days: NEW_DAYS });
  await flush(); await flush(); await flush(); await flush();
  const a = A.els;
  ok(a.appTitle.textContent === 'CXO 天粒度看板', '标题中文', a.appTitle.textContent);
  ok(a.cover.hasAttribute('hidden') === true, '【需求②】说明条默认收起');
  ok(tabsIn(A).join(',') === 'summary,network,service', '顶层 3 页签', tabsIn(A).join(','));
  ok(/汇总/.test(a.tabBar.innerHTML) && /网络/.test(a.tabBar.innerHTML) && /服务/.test(a.tabBar.innerHTML), '页签名中文化', a.tabBar.innerHTML.slice(0, 120));
  ok(a.subBar.innerHTML === '' && a.subBar.style.display === 'none', '汇总页无子页签（子页签条隐藏）');
  ok(count(a.sections.innerHTML, /class="chart"/g) === 6, '汇总页渲染 6 张图', count(a.sections.innerHTML, /class="chart"/g));
  ok(chartIds(A).length === 6, 'live 图表 = 6', chartIds(A).join(','));
  ok(JSON.stringify(series(A, 'c_91')) === JSON.stringify(['本周', '前一周', '前两周']), '图例周名中文');
  ok(thCount(A) === 6 + 3, '表格列 = 当前页签 6 指标（+日期/星期/状态）', thCount(A));
  ok(/当前页签：汇总（6 个指标）/.test(a.tblTitle.innerHTML), '表格标题写明当前页签与指标数', a.tblTitle.innerHTML);
  ok(count(a.sections.innerHTML, /cell future/g) > 0, '未来日画灰空格子');
  ok(/尚未到来/.test(a.sections.innerHTML), '灰格 tooltip 中文原因（前端派生）');
  ok(a.status.textContent.includes('实时数据'), '状态条中文', a.status.textContent);
  ok(!/-> 永久不可回补/.test(a.sections.innerHTML), '未原样注入后端 reason');

  console.log('=== B) 【需求②】说明条点击展开 / 再收起 ===');
  a.notesToggle._listeners.click.forEach(f => f.call(a.notesToggle, {}));
  ok(a.cover.hasAttribute('hidden') === false && a.notesToggle.getAttribute('aria-expanded') === 'true', '展开且 aria-expanded=true');
  ok(CJK.test(a.cover.innerHTML) === true, '展开后是中文说明');
  ok(/共 50 个指标 · 3 个页签/.test(a.cover.innerHTML), '说明条给出指标数/页签数');
  a.notesToggle._listeners.click.forEach(f => f.call(a.notesToggle, {}));
  ok(a.cover.hasAttribute('hidden') === true && a.notesToggle.getAttribute('aria-expanded') === 'false', '可再次收起');

  console.log('=== C) 切到「网络」页签：子页签出现，图表/表格跟随 ===');
  clickAttr(A, 'tabBar', 'data-tab', 'network');
  await flush();
  ok(activeTabIn(A) === 'network', 'network 成为激活页签', activeTabIn(A));
  ok(a.subBar.style.display === 'flex' && subsIn(A).join(',') === 'Mobility,Service Request,Accessibility,Retainability,InterWorking', '5 个子页签按参考看板顺序', subsIn(A).join(','));
  ok(/移动性/.test(a.subBar.innerHTML) && /服务请求/.test(a.subBar.innerHTML), '子页签名中文化');
  ok(activeSubIn(A) === 'Mobility', '默认选第一个子页签');
  ok(count(a.sections.innerHTML, /class="chart"/g) === 3, 'Mobility 子页签 3 张图', count(a.sections.innerHTML, /class="chart"/g));
  ok(chartIds(A).length === 3 && !chartIds(A).includes('c_91'), '切页签时旧图已释放（汇总的 c_91 不在）', chartIds(A).join(','));
  ok(A.stats.dispose >= 6, 'dispose 被调用（释放 6 张汇总图）', A.stats.dispose);
  ok(thCount(A) === 3 + 3, '表格跟随当前子页签 3 指标', thCount(A));
  ok(/当前页签：网络 \/ 移动性（3 个指标）/.test(a.tblTitle.innerHTML), '表格标题=网络/移动性', a.tblTitle.innerHTML);
  ok(A.store['vmax-daily-tab'] === 'network', '页签选择写入 localStorage');

  console.log('=== D) 切换子页签 ===');
  clickAttr(A, 'subBar', 'data-sub', 'Service Request');
  await flush();
  ok(activeSubIn(A) === 'Service Request', '子页签切换', activeSubIn(A));
  ok(count(a.sections.innerHTML, /class="chart"/g) === 4, 'Service Request 4 张图', count(a.sections.innerHTML, /class="chart"/g));
  ok(/当前页签：网络 \/ 服务请求（4 个指标）/.test(a.tblTitle.innerHTML), '表格标题跟随子页签');

  console.log('=== E) 切到「服务」页签：9 个子页签，OTTVoice 11 张图（最大页签）===');
  clickAttr(A, 'tabBar', 'data-tab', 'service');
  await flush();
  ok(subsIn(A).join(',') === 'Mobility,Voice,Data,Video,SMS,Web Browse,Game,OTTVoice,OTTVideo', '9 个子页签按参考看板顺序', subsIn(A).join(','));
  clickAttr(A, 'subBar', 'data-sub', 'OTTVoice');
  await flush();
  ok(count(a.sections.innerHTML, /class="chart"/g) === 11, 'OTTVoice 11 张图', count(a.sections.innerHTML, /class="chart"/g));
  ok(/OTT语音/.test(a.subBar.innerHTML), 'OTTVoice 中文名 OTT语音');
  clickAttr(A, 'subBar', 'data-sub', 'SMS');
  await flush();
  ok(count(a.sections.innerHTML, /class="chart"/g) === 6, 'SMS 6 张图', count(a.sections.innerHTML, /class="chart"/g));

  console.log('=== F) 【需求①】外壳切英文 ===');
  post(A, { __type: 'myapp-locale', locale: 'en' });
  await flush(); await flush();
  ok(a.appTitle.textContent === 'CXO Daily View', '标题英文', a.appTitle.textContent);
  ok(/Summary/.test(a.tabBar.innerHTML) && /Network/.test(a.tabBar.innerHTML) && /Service/.test(a.tabBar.innerHTML), '页签名英文');
  ok(/SMS/.test(a.subBar.innerHTML), '子页签名英文（保留原名）');
  ok(!CJK.test(a.tabBar.innerHTML) && !CJK.test(a.subBar.innerHTML), '页签/子页签条无中文');
  ok(!CJK.test(a.sections.innerHTML), '英文下图表区无中文', (a.sections.innerHTML.match(CJK) || [])[0]);
  ok(!CJK.test(a.tbl.innerHTML) && !CJK.test(a.tblTitle.innerHTML), '英文下表格无中文', (a.tbl.innerHTML.match(CJK) || [])[0]);
  ok(!CJK.test(a.cover.innerHTML), '英文下说明条无中文', (a.cover.innerHTML.match(CJK) || [])[0]);
  ok(JSON.stringify(series(A, 'c_202')) === JSON.stringify(['This Week', 'Last Week', 'Week Before Last']), '图例英文', JSON.stringify(series(A, 'c_202')));
  ok(/Current tab: Service \/ SMS \(6 indicators\)/.test(a.tblTitle.innerHTML), '表格标题英文', a.tblTitle.innerHTML);
  ok(A.store['app-locale'] === 'en', '语言写入 localStorage');
  post(A, { __type: 'myapp-locale', locale: 'zh' });
  await flush();
  ok(a.appTitle.textContent === 'CXO 天粒度看板' && CJK.test(a.tabBar.innerHTML) && CJK.test(a.sections.innerHTML), '切回中文整体重渲染');

  console.log('=== G) 旧后端（仅 6 指标、无 tabs/groups）兜底 ===');
  const G = runPage({ grid: OLD_GRID, days: NEW_DAYS, locale: 'en' });
  await flush(); await flush(); await flush();
  ok(tabsIn(G).length === 1, '兜底只出 1 个页签', tabsIn(G).join(','));
  ok(count(G.els.sections.innerHTML, /class="chart"/g) === 6, '兜底渲染 6 张图', count(G.els.sections.innerHTML, /class="chart"/g));
  ok(G.els.subBar.innerHTML === '', '兜底无子页签');
  ok(!CJK.test(G.els.sections.innerHTML) && !CJK.test(G.els.tabBar.innerHTML), '兜底下英文仍无中文');

  console.log('=== H) 中间态后端（只有 groups、没有 tabs）也能出页签 ===');
  const H = runPage({ grid: GROUP_GRID, days: NEW_DAYS, locale: 'zh' });
  await flush(); await flush(); await flush();
  ok(tabsIn(H).join(',') === 'summary,network,service', 'groups 兜底成 3 个页签', tabsIn(H).join(','));
  ok(count(H.els.sections.innerHTML, /class="chart"/g) === 6, '兜底默认页签 6 张图', count(H.els.sections.innerHTML, /class="chart"/g));
  clickAttr(H, 'tabBar', 'data-tab', 'network');
  await flush();
  ok(count(H.els.sections.innerHTML, /class="chart"/g) === 14, '切到 network 组 14 张图', count(H.els.sections.innerHTML, /class="chart"/g));
  clickAttr(H, 'tabBar', 'data-tab', 'service');
  await flush();
  ok(count(H.els.sections.innerHTML, /class="chart"/g) === 30, '切到 service 组 30 张图', count(H.els.sections.innerHTML, /class="chart"/g));

  console.log('=== I) 页签记忆（localStorage vmax-daily-tab）===');
  const I = runPage({ grid: NEW_GRID, days: NEW_DAYS, locale: 'zh', tab: 'service' });
  await flush(); await flush(); await flush();
  ok(activeTabIn(I) === 'service', '上次停留的页签被恢复', activeTabIn(I));
  ok(count(I.els.sections.innerHTML, /class="chart"/g) === 3, '恢复的页签渲染其子页签指标', count(I.els.sections.innerHTML, /class="chart"/g));

  console.log('=== J) 掐掉载荷里的 reason，仍能给本地化原因（不依赖后端中文）===');
  const NR = JSON.parse(JSON.stringify(NEW_GRID));
  NR.weeks.forEach(w => w.days.forEach(d => { delete d.reason; }));
  const J = runPage({ grid: NR, days: NEW_DAYS, locale: 'en' });
  await flush(); await flush(); await flush();
  ok(/Not yet/.test(J.els.sections.innerHTML), '无 reason 时英文 tooltip 仍本地化出原因');
  ok(!CJK.test(J.els.sections.innerHTML), '无 reason 时英文 sections 干净');

  console.log('=== K) 指标自身缺数必须落灰格（不能因为当天别的指标有数就变绿）===');
  const GAP = JSON.parse(JSON.stringify(NEW_GRID));
  delete GAP.weeks[0].days[0].values['111'];      // 本周一：网络指标 111 缺数
  const K = runPage({ grid: GAP, days: NEW_DAYS, locale: 'zh', tab: 'network' });
  await flush(); await flush(); await flush();
  const kk = K.els;
  const p111 = kk.sections.innerHTML.split('id="c_111"')[1].split('id="c_112"')[0];
  const p103 = kk.sections.innerHTML.split('id="c_103"')[1].split('id="c_111"')[0];
  ok(/class="cell missing"/.test(p111), '111 缺数那天是灰格', (p111.match(/class="cell \w+"/g) || []).slice(0, 3).join(','));
  ok(!/class="cell missing"/.test(p103), '103 同期有数 -> 非灰格', (p103.match(/class="cell \w+"/g) || []).slice(0, 3).join(','));
  ok(/class="cell future"/.test(p111), '未来日仍为 future 格');

  console.log('=== L) 大屏轮播：逐步轮播到每个页签下的子页签 ===');
  ok(/id="carouselBtn"/.test(HTML), '静态 HTML 里就有轮播按钮');
  const L = runPage({ grid: NEW_GRID, days: NEW_DAYS, locale: 'zh' });
  await flush(); await flush(); await flush();
  const l = L.els;
  ok(btnText(L) === '⛶ 大屏轮播', '按钮默认文案', btnText(L));
  ok(l.carouselBtn.getAttribute('aria-pressed') === 'false', 'aria-pressed=false');
  ok(l.carouselStep.hasAttribute('hidden') === true, '未轮播时步骤提示隐藏');
  l.carouselBtn._listeners.click.forEach(f => f.call(l.carouselBtn, {}));
  await flush();
  ok(l.carouselBtn.classList.contains('on') && l.carouselBtn.getAttribute('aria-pressed') === 'true', '点击进入轮播态');
  ok(/停止轮播 · 15s/.test(btnText(L)), '按钮显示倒计时 15s', btnText(L));
  ok(l.carouselStep.hasAttribute('hidden') === false && stepText(L) === '1/15 · 汇总', '步骤提示 = 1/15 · 汇总', stepText(L));
  fireIntervals(L, 1000);
  ok(/停止轮播 · 14s/.test(btnText(L)), '1 秒后倒计时变 14s', btnText(L));

  const seen = [], counts = [];
  for (let i = 0; i < 16; i++) {
    fireIntervals(L, 15000);
    await flush();
    seen.push(activeTabIn(L) + (subsIn(L).length ? '/' + activeSubIn(L) : ''));
    counts.push(count(l.sections.innerHTML, /class="chart"/g));
  }
  const expect = ['network/Mobility', 'network/Service Request', 'network/Accessibility',
    'network/Retainability', 'network/InterWorking', 'service/Mobility', 'service/Voice',
    'service/Data', 'service/Video', 'service/SMS', 'service/Web Browse', 'service/Game',
    'service/OTTVoice', 'service/OTTVideo', 'summary'];
  ok(JSON.stringify(seen.slice(0, 15)) === JSON.stringify(expect),
    '【核心】15 步恰好走遍每个页签下的每个子页签', seen.slice(0, 15).join(' > '));
  ok(seen[15] === 'network/Mobility', '第 16 步回到序列开头（循环）', seen[15]);
  ok(counts[9] === 6 && counts[12] === 11 && counts[14] === 6,
    '每一步都渲染该页签自己的图（SMS 6 / OTTVoice 11 / 汇总 6）', JSON.stringify([counts[9], counts[12], counts[14]]));
  ok(L.store['vmax-daily-tab'] === activeTabIn(L), '轮播也同步记住页签', L.store['vmax-daily-tab'] + ' vs ' + activeTabIn(L));

  console.log('--- 手动接管即停 ---');
  clickAttr(L, 'tabBar', 'data-tab', 'service');
  await flush();
  ok(l.carouselBtn.classList.contains('on') === false && /大屏轮播/.test(btnText(L)), '点页签后退出轮播态');
  ok(l.carouselStep.hasAttribute('hidden') === true, '步骤提示重新隐藏');
  ok(L.intervals.filter(x => x.ms === 1000 || x.ms === 15000).every(x => x.cleared), '轮播的两个定时器都已清空');
  const before = activeTabIn(L) + '/' + activeSubIn(L);
  fireIntervals(L, 15000);
  await flush();
  ok(activeTabIn(L) + '/' + activeSubIn(L) === before, '停表后不再自动推进', activeTabIn(L));

  console.log('--- 停止轮播按钮 + 本地化 + 步长可配 ---');
  l.carouselBtn._listeners.click.forEach(f => f.call(l.carouselBtn, {}));
  await flush();
  ok(l.carouselBtn.classList.contains('on') === true, '可再次启动');
  l.carouselBtn._listeners.click.forEach(f => f.call(l.carouselBtn, {}));
  await flush();
  ok(l.carouselBtn.classList.contains('on') === false, '再点一次即停止');
  l.carouselBtn._listeners.click.forEach(f => f.call(l.carouselBtn, {}));
  await flush();
  post(L, { __type: 'myapp-locale', locale: 'en' });
  await flush();
  ok(/Big-screen|Stop/.test(btnText(L)) && !CJK.test(btnText(L)), '英文下按钮文案本地化', btnText(L));
  const L8 = runPage({ grid: NEW_GRID, days: NEW_DAYS, locale: 'zh', search: '?carousel=8' });
  await flush(); await flush(); await flush();
  L8.els.carouselBtn._listeners.click.forEach(f => f.call(L8.els.carouselBtn, {}));
  await flush();
  ok(/停止轮播 · 8s/.test(btnText(L8)) && L8.intervals.some(x => x.ms === 8000),
    '?carousel=8 可覆盖步长', btnText(L8));

  console.log('\n==== ' + pass + ' passed, ' + fail + ' failed ====');
  process.exit(fail ? 1 : 0);
})();
