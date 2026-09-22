/* ==========================================================================
   MsPortal — 顶栏 / 工具条交互   [新增文件，portal.js 一行不改]
   --------------------------------------------------------------------------
   为什么独立成文件：2026-09-18 有另一个会话在同时改 portal.js / portal.css，
   两边写同一个文件会互相覆盖（当天已因两会话同写 portal.js 白屏过一次）。
   本文件只**新增**，并且不依赖 portal.js 的任何内部变量 —— 需要门户状态时一律
   走 DOM（点它的按钮、写它的 input 并派发事件），这样两边可以各自迭代。

   负责三件事：
     1. 语言：顶栏新文案自带小词典（data-mp-i18n），跟着 <html lang> 走。
     2. 环境徽标：绿点 + 环境名。**真实取值** —— 环境名由 hostname 决定
        （localhost / 127.0.0.1 → 本机，其余 → 生产），绿点由
        /api/portal-qc/summary 的真实探活结果决定（失败变红且停跳）。
        2026-09-18 曾按需求删掉写死的「生产运行」绿点，这里不把它加回来：
        点必须反映真实状态。
     3. 工具条两个按钮：
        · Filter dashboards in this view → 展开搜索筛选行并聚焦搜索框
        · Full catalog → 清空搜索词 + 把筛选切回「全部」，回到完整目录

   2026-09-19：删掉原第 3 件事「工具条达标率」。
   它取 /api/portal-qc/summary 的 sla 指标，与 Quality Control 面板标题栏的
   「达标率」同源同字段 —— 同一屏上重复展示同一个数；而工具条这行管的是
   「筛选当前视图」，一个全站 SLA 口径的数字放这里语义也对不上。
   指标本身没删：QC 面板的徽标仍在（取不到变 —、带 30 天口径 tooltip）。
   探活（第 2 件事）**继续复用同一个接口**，所以这里的 fetch 一行没少。

   时钟（#clock）仍由 portal.js 每秒写入；只有当 portal.js 没跑起来时本文件才接管。
   ========================================================================== */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ i18n --
     刻意不用 data-i18n：portal.js 的 render() 会把所有 [data-i18n] 元素按它自己的
     字典重写，字典里没有的 key 会被写成 key 本身（t() 兜底 return key），文案就没了。
     这里用 data-mp-i18n / data-mp-i18n-attr，自己维护，互不干扰。 */
  var DICT = {
    zh: {
      'tagline': '更智能的运维 · 更高的效率 · 更好的网络',
      'env.local': '本机',
      'env.prod': '生产',
      'site.local': '本机站点',
      'site.prod': '利比里亚',
      'site.tip': '返回 uniplam 数据看板门户（同一台主机）',
      'filterView': '筛选当前视图看板',
      'filterView.tip': '展开搜索与筛选行，并聚焦搜索框',
      'fullCatalog': '完整目录',
      'fullCatalog.tip': '清除搜索词与筛选条件，回到完整看板目录',
      'health.up': '正常',
      'health.down': '不可达',
      'health.tip': '门户数据接口探活：{state} · 最近 {at}',
      'health.wait': '探测中',
      'theme.tip': '深色 / 浅色'
    },
    en: {
      'tagline': 'Smarter Operations · Higher Efficiency · Better Network',
      'env.local': 'Local',
      'env.prod': 'Production',
      'site.local': 'Local site',
      'site.prod': 'Liberia',
      'site.tip': 'Back to the uniplam dashboard portal (same host)',
      'filterView': 'Filter dashboards in this view',
      'filterView.tip': 'Expand the search & filter row and focus the search box',
      'fullCatalog': 'Full catalog',
      'fullCatalog.tip': 'Clear the search term and filters to show the full catalog',
      'health.up': 'reachable',
      'health.down': 'unreachable',
      'health.tip': 'Portal data API health: {state} · last {at}',
      'health.wait': 'probing',
      'theme.tip': 'Dark / Light'
    }
  };

  var QC_URL = '/api/portal-qc/summary';
  var PROBE_MS = 60000;

  function $(id) { return document.getElementById(id); }
  function lang() { return document.documentElement.getAttribute('lang') === 'en' ? 'en' : 'zh'; }
  function t(key, vars) {
    var d = DICT[lang()] || DICT.zh;
    var s = d[key] != null ? d[key] : (DICT.zh[key] != null ? DICT.zh[key] : key);
    if (vars) {
      Object.keys(vars).forEach(function (k) { s = s.split('{' + k + '}').join(String(vars[k])); });
    }
    return s;
  }

  /* 已取到的实时值，切语言时要按新语言重刷（数值本身不重取）。
     2026-09-19：sla 字段随「工具条达标率」一起删掉 —— 探活只用 up / at。 */
  var last = { at: '', up: null };

  function paintI18n() {
    var nodes = document.querySelectorAll('[data-mp-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute('data-mp-i18n'));
    }
    var attrs = document.querySelectorAll('[data-mp-i18n-attr]');
    for (var j = 0; j < attrs.length; j++) {
      attrs[j].getAttribute('data-mp-i18n-attr').split(',').forEach(function (pair) {
        var kv = pair.split(':');
        if (kv.length === 2) attrs[j].setAttribute(kv[0].trim(), t(kv[1].trim()));
      });
    }
    paintEnv();
    paintHealth();
  }

  /* --------------------------------------------------------------- 环境徽标 --
     环境名 = 真实 hostname 判定，不是写死的。 */
  function isLocalHost() {
    var h = (location.hostname || '').toLowerCase();
    return h === '' || h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]';
  }
  function paintEnv() {
    var env = $('envLabel');
    if (env) env.textContent = isLocalHost() ? t('env.local') : t('env.prod');
    var site = $('siteLabel');
    if (site) site.textContent = isLocalHost() ? t('site.local') : t('site.prod');
  }

  /* 绿点 = /api/portal-qc/summary 的真实探活结果（不是装饰动画） */
  function paintHealth() {
    var box = $('envBadge');
    if (!box) return;
    var down = last.up === false;
    box.classList.toggle('is-down', down);
    var state = last.up === null ? t('health.wait') : (down ? t('health.down') : t('health.up'));
    box.setAttribute('title', t('health.tip', { state: state, at: last.at || '—' }));
  }

  function probe() {
    fetch(QC_URL, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        last.up = true;
        last.at = (data && data.generated_at) ? String(data.generated_at).slice(11, 19) : '';
        paintHealth();
      })
      .catch(function () {
        last.up = false;
        last.at = '';
        paintHealth();
      });
  }

  /* ------------------------------------------------------------- 工具条按钮 --
     「Filter dashboards in this view」= 展开搜索筛选行 + 聚焦搜索框。
     展开必须走门户自己的 #controlToggle（点它），不能直接改 class ——
     portal.js 的 state.barOpen 与 aria-expanded 都挂在那个按钮的回调里，
     绕过它会出现「看着展开了、内部状态还是收起」。 */
  function bindBar() {
    var filterBtn = $('barFilterBtn');
    if (filterBtn) {
      filterBtn.addEventListener('click', function () {
        var bar = $('controlBar');
        var toggle = $('controlToggle');
        if (bar && bar.classList.contains('is-collapsed') && toggle) toggle.click();
        var si = $('searchInput');
        if (si) {
          try { si.focus(); si.select(); } catch (e) { /* ignore */ }
        }
      });
    }

    /* 「Full catalog」= 清空搜索词 + 筛选切回「全部」。
       两个动作都通过门户自己的输入框 / chip 触发，保证 state 同步。 */
    var full = $('barFullCatalog');
    if (full) {
      full.addEventListener('click', function () {
        var si = $('searchInput');
        if (si && si.value) {
          si.value = '';
          si.dispatchEvent(new Event('input', { bubbles: true }));
        }
        var all = document.querySelector('#filterChips [data-act="filter"][data-filter="all"]');
        if (all) all.click();
      });
    }
  }

  /* ------------------------------------------------------------------ 时钟 --
     #clock 平时由 portal.js 的 tick() 每秒写入；若门户脚本没起来（接口挂 / 脚本报错），
     这里 2.5s 后接管，免得顶栏永远停在 --:--:--。 */
  function clockFallback() {
    var el = $('clock');
    if (!el) return;
    setTimeout(function () {
      if (el.textContent && el.textContent !== '--:--:--') return; // portal.js 在跑
      var pad = function (v) { return String(v).padStart(2, '0'); };
      var tick = function () {
        var n = new Date();
        el.textContent = n.getFullYear() + '-' + pad(n.getMonth() + 1) + '-' + pad(n.getDate()) +
          ' ' + pad(n.getHours()) + ':' + pad(n.getMinutes()) + ':' + pad(n.getSeconds());
      };
      tick();
      setInterval(tick, 1000);
    }, 2500);
  }

  function init() {
    paintI18n();
    bindBar();
    probe();
    setInterval(probe, PROBE_MS);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) probe();
    });
    /* 语言由 portal.js 的按钮切换（它只改 <html lang> 与 .seg-btn.is-active），
       这里监听属性变化，把顶栏自有文案跟着刷一遍。 */
    new MutationObserver(function () { paintI18n(); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    clockFallback();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
