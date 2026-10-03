/* ==========================================================================
   OlrPortal — OLR MS Management Platform 运营工作台首页
   --------------------------------------------------------------------------
   设计定位：Enterprise Operations Workspace，不是 NOC 大屏。
   这一页只回答三个问题：现在整体怎么样 / 我进哪些业务 / 哪里需要我处理。

   数据来源（全部只读引用，不改写 /MsPortal/ 目录下任何文件）：
     · window.MS_PORTAL_DATA    ← /MsPortal/assets/data.js（51 个看板 + QC 定义 + 升级机制）
     · GET /api/portal-catalog  ← 服务端全局目录；在 MsPortal 里编辑过就以它为准
     · GET /api/portal-qc/*     ← Quality Control 实时数字与下钻明细
     · /MsPortal/assets/access.js ← 与统一门户一致的 allowedGroups / allowedCards 判定
     · 看板跳转复用 /MsPortal/viewer.html（同查看器、同权限口径）
   本文件只写 olrportal.* 这一组 localStorage 键，与 msportal.* 完全隔离，
   切主题/语言/地图页签都不会影响 /MsPortal/ 的显示状态。
   ========================================================================== */
(function () {
  'use strict';

  var DATA = window.MS_PORTAL_DATA || { groups: [], qc: [], items: [], escalation: { levels: [], rows: [] } };

  /* ------------------------------------------------------------ 常量 ---- */
  var LS = {
    theme: 'olrportal.theme.v1',
    lang: 'olrportal.lang.v1',
    mapTab: 'olrportal.maptab.v1',
    recent: 'olrportal.recent.v1'
  };
  /* 统一门户的会话 token 键（与 /MsPortal/、/uniplam/ 同一份）：
     只读它 —— 任何一处登录过，打开本页就是已登录；这里不会另存一份。 */
  var PORTAL_TOKEN_KEY = 'liberia_noc_auth_v1';
  var REQUIRE_LOGIN = true;
  var DRILL_SIZE = 100;

  /* 图标名沿用 data.js 的字段，映射到 /MsPortal/assets/icons/phosphor.css */
  var PH = {
    'chart-polar': 'ph-chart-polar', gauge: 'ph-gauge', bell: 'ph-bell', map: 'ph-map-trifold',
    ticket: 'ph-ticket', siren: 'ph-siren', clock: 'ph-clock', 'chart-line': 'ph-chart-line',
    link: 'ph-link', cpu: 'ph-cpu', broadcast: 'ph-broadcast', battery: 'ph-battery-charging',
    package: 'ph-package', wrench: 'ph-wrench', upload: 'ph-cloud-arrow-up', table: 'ph-table',
    archive: 'ph-archive', chat: 'ph-chat-circle-dots', book: 'ph-book-open-text', gear: 'ph-gear',
    dashboard: 'ph-squares-four', key: 'ph-lock-key', warning: 'ph-warning', briefcase: 'ph-briefcase',
    git: 'ph-git-pull-request', user: 'ph-user', shield: 'ph-shield-check', arrow: 'ph-arrow-right',
    search: 'ph-magnifying-glass', 'map-pin': 'ph-map-pin', external: 'ph-arrow-square-out',
    refresh: 'ph-arrow-clockwise', 'arrow-up-right': 'ph-arrow-up-right'
  };

  /* 四个一级业务域：域 = 容器，看板 = 域内的列表行（不做卡片墙）。
     clusters 里的 nos 只是「人工归过类」的专题；新加或改过归属的看板会自动
     落到该域末尾的「其他」里 —— 手写表不会把内容弄丢。 */
  var DOMAINS = [
    {
      key: 'MS', no: '01', gids: ['MS View'],
      clusters: [
        { zh: 'SLA 与合同绩效', en: 'SLA & contract performance', nos: [2, 7] },
        { zh: '网络可用率', en: 'Network availability', nos: [1, 9, 15] },
        { zh: '运营总览与事件', en: 'Operations & incidents', nos: [43, 14, 37] }
      ]
    },
    {
      key: 'FLM', no: '02', gids: ['FLM View', 'SP View'],
      clusters: [
        { zh: '告警处理', en: 'Alarm handling', nos: [12, 11] },
        { zh: '工单与抢修', en: 'Tickets & repair', nos: [13, 17] },
        { zh: '站点与动力', en: 'Site & power', nos: [5, 18, 36] },
        { zh: '地理视图', en: 'Geographic view', nos: [4] },
        { zh: '备品备件', en: 'Spare parts (SP)', nos: [33, 34, 35] }
      ]
    },
    {
      key: 'BO', no: '03', gids: ['BO View'],
      clusters: [
        { zh: '无线接入网', en: 'Radio access network', nos: [19, 20, 21, 22] },
        { zh: '核心网与业务', en: 'Core network & service', nos: [24, 25, 51] },
        { zh: 'IP 承载网', en: 'IP transport', nos: [30, 31, 32, 29, 26] },
        { zh: '微波', en: 'Microwave', nos: [27, 28] },
        { zh: '安全与可用率', en: 'Security & availability', nos: [23, 18] }
      ]
    },
    {
      key: 'FO', no: '04', gids: ['FO View'],
      clusters: [
        { zh: '告警监控', en: 'Alarm monitoring', nos: [10, 11, 12] },
        { zh: '工单与修复时长', en: 'Tickets & MTTR', nos: [8, 13, 16] },
        { zh: '网络状态', en: 'Network status', nos: [18, 36] }
      ]
    }
  ];

  /* 辅助入口：不是日常操作主路径，但必须找得到 —— 收在页面最底部的紧凑三栏 */
  var SUPPORT = [
    { gids: ['CXO View'], zh: '决策层视图', en: 'Executive view' },
    { gids: ['System Admin'], zh: '系统与配置', en: 'System & configuration' },
    { gids: ['Knowledge Q&A', 'Friends Link'], zh: '知识与生态', en: 'Knowledge & ecosystem' }
  ];

  /* 地图页签：与 /MsPortal/ 中列同一批 my_app 页面；mwembed=1 让嵌入页只留地图本体 */
  var MAP_TABS = [
    { page: 'gis', zh: 'GIS', en: 'GIS', icon: 'map' },
    { page: 'mwRealTime', zh: '微波', en: 'MW', icon: 'broadcast' },
    { page: 'realtime_alarm', zh: '告警', en: 'Alarm', icon: 'bell' },
    { page: 'packet_loss', zh: '丢包', en: 'Loss', icon: 'link' }
  ];

  /* QC 六项按类别分组：网络 / 业务 / 维护 */
  var QC_CAT = { alarm: 'network', tt: 'service', wo: 'service', cr: 'service', pmt: 'maint', spms: 'maint' };

  /* ---------------------------------------------------------- 文案 ------ */
  var STR = {
    'brand.sub': { zh: '运营工作台 · Operations Workspace', en: 'Operations Workspace' },
    'search.ph': { zh: '搜索看板名称、描述、责任人、标签…', en: 'Search dashboards, reports, sites…' },
    'theme.tip': { zh: '深色 / 浅色', en: 'Dark / light' },
    'ops.title': { zh: 'Operations · 业务域', en: 'Operations' },
    'ops.note': { zh: '按业务域进入 · 每个域下面是它自己的看板清单', en: 'Enter by business domain · each domain lists its own dashboards' },
    'qc.title': { zh: 'Quality Control · 质量指标', en: 'Quality Control' },
    'qc.updated': { zh: '更新于', en: 'Updated' },
    'qc.compliance': { zh: '达标率', en: 'Compliance' },
    'qc.esc': { zh: '升级机制', en: 'Escalation matrix' },
    'qc.tip': { zh: '点击任一数字看明细', en: 'Click a number for the row detail' },
    'cat.network': { zh: '网络', en: 'Network' },
    'cat.service': { zh: '业务', en: 'Service' },
    'cat.maint': { zh: '维护', en: 'Maintenance' },
    'net.title': { zh: 'Network Overview · 网络概览', en: 'Network Overview' },
    'net.sub': { zh: '利比里亚 · 区域拓扑', en: 'Liberia · regional topology' },
    'net.alarms': { zh: '活动告警', en: 'Active alarms' },
    'net.down': { zh: '退服站点', en: 'Sites down' },
    'net.full': { zh: '全屏打开', en: 'Open full view' },
    'net.loading': { zh: '地图加载中…', en: 'Loading map…' },
    'work.title': { zh: 'My Work · 待处理', en: 'My work' },
    'work.open': { zh: '点开看明细', en: 'Click for detail' },
    'recent.title': { zh: 'Recently Opened · 最近打开', en: 'Recently opened' },
    'recent.empty': { zh: '从这里打开过的看板会列在这里。', en: 'Dashboards you open from here show up here.' },
    'more.title': { zh: 'Supporting Entries · 辅助入口', en: 'Supporting entries' },
    'more.note': { zh: '不常进、但必须找得到 · 想要卡片式全目录请打开 /MsPortal/', en: 'Rarely used but always reachable · the card catalogue is at /MsPortal/' },
    'more.catalogue': { zh: '卡片式全目录 /MsPortal/', en: 'Card catalogue /MsPortal/' },
    'count.of': { zh: '共 {n} 个看板', en: '{n} dashboards' },
    'count.hit': { zh: '匹配 {m} / {n}', en: '{m} of {n}' },
    'dash.n': { zh: '个看板', en: 'dashboards' },
    'other': { zh: '其他', en: 'More' },
    'jump.all': { zh: '全部', en: 'All' },
    'jump.support': { zh: '辅助入口', en: 'Support' },
    'empty': { zh: '没有匹配的看板 —— 换个关键词，或点「全部」', en: 'No dashboard matches — try another word, or pick All' },
    'beta.tip': { zh: '试运行，未正式日报化', en: 'Pilot, not yet a daily report' },
    'beta': { zh: '试运行', en: 'Beta' },
    'new': { zh: '新增', en: 'New' },
    'gate.title': { zh: '登录后即可查看看板目录', en: 'Sign in to see the dashboard catalogue' },
    'gate.note': { zh: '使用统一门户同一套账号与权限。', en: 'Same account and permissions as the unified portal.' },
    'gate.btn': { zh: '登录', en: 'Sign in' },
    'menu.appearance': { zh: '深色 / 浅色主题', en: 'Toggle dark theme' },
    'menu.portal': { zh: '数据看板门户 /uniplam/', en: 'Data dashboard portal /uniplam/' },
    'menu.catalogue': { zh: '卡片式全目录 /MsPortal/', en: 'Card catalogue /MsPortal/' },
    'menu.usermgmt': { zh: '用户管理（统一门户）', en: 'User management (unified portal)' },
    'menu.logout': { zh: '退出登录', en: 'Sign out' },
    'user.signed': { zh: '已登录', en: 'Signed in' },
    'user.local': { zh: '本机访客', en: 'Local session' },
    'role.admin': { zh: '管理员', en: 'Admin' },
    'role.viewer': { zh: '只读', en: 'Viewer' },
    'btn.reload': { zh: '刷新', en: 'Refresh' },
    'qc.search': { zh: '筛选明细…', en: 'Filter rows…' },
    'qc.page': { zh: '第 {p} / {t} 页', en: 'Page {p} / {t}' },
    'qc.rows': { zh: '{n} 行', en: '{n} rows' },
    'qc.loading': { zh: '加载中…', en: 'Loading…' },
    'qc.err': { zh: '明细暂时取不到（后端未启动或该指标未配置）', en: 'Detail unavailable (backend down or metric not configured)' },
    'esc.title': { zh: '升级机制 (Escalation Matrix)', en: 'Escalation Matrix' },
    'esc.head': { zh: '档位,岗位,姓名,Orange,Lonestar,邮箱', en: 'Level,Position,Name,Orange,Lonestar,E-mail' },
    'login.title': { zh: '登录统一门户', en: 'Sign in to the unified portal' },
    'login.user': { zh: '用户名', en: 'Username' },
    'login.pass': { zh: '密码', en: 'Password' },
    'login.note': { zh: '使用统一门户同一套账号、密码和权限。', en: 'Same account, password and permissions as /uniplam/.' },
    'login.cancel': { zh: '取消', en: 'Cancel' },
    'login.submit': { zh: '登录', en: 'Sign in' },
    'login.logging': { zh: '登录中…', en: 'Signing in…' },
    'login.bad': { zh: '用户名或密码不正确', en: 'Wrong username or password' },
    'login.locked': { zh: '尝试次数过多，稍后再试', en: 'Too many attempts, try again later' },
    'login.net': { zh: '网络异常，连不上登录服务', en: 'Cannot reach the sign-in service' },
    'foot.branch': { zh: '利比里亚办事处网络运营中心 (OLR MS)', en: 'Liberia OLR Network Operations Centre' },
    'foot.source': { zh: '目录来源：统一看板目录（与 /MsPortal/ 同一份）', en: 'Catalogue: the shared dashboard catalogue (same as /MsPortal/)' },
    'work.sites': { zh: '站点退服', en: 'Sites down' },
    'work.sites.d': { zh: '按站点聚合，点开看告警明细', en: 'Aggregated by site — click for alarm detail' },
    'work.alarm': { zh: '活动告警', en: 'Active alarms' },
    'work.alarm.d': { zh: '未消除告警总量', en: 'Uncleared alarms' },
    'work.overdue': { zh: '超期预防性维护', en: 'Overdue PM tasks' },
    'work.overdue.d': { zh: 'PMT 中已过计划完成时间', en: 'PMT past its planned finish' },
    'work.miss': { zh: '达标缺口（30 天）', en: 'SLA misses (30 days)' },
    'work.miss.d': { zh: '30 天内未达标的工单数', en: 'Tickets below target in the last 30 days' },
    'work.outband': { zh: '带外备件单据', en: 'Out-of-band documents' },
    'work.outband.d': { zh: 'SPMS 带外流程单据', en: 'SPMS out-of-band documents' },
    'justnow': { zh: '刚刚', en: 'just now' }
  };

  /* ---------------------------------------------------------- state ----- */
  function readLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function writeLS(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function dropLS(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function readJSON(k, d) { try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : d; } catch (e) { return d; } }
  function writeJSON(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  var state = {
    lang: readLS(LS.lang) === 'en' ? 'en' : 'zh',
    theme: readLS(LS.theme) === 'dark' ? 'dark' : 'light',
    q: '',
    domain: 'all',
    items: DATA.items || [],
    qc: null,
    authUser: null,
    authOk: null,              /* null = 还没探完；false = 未登录 */
    mapTab: readLS(LS.mapTab) || 'gis',
    mapBooted: false,
    recent: readJSON(LS.recent, []),
    drill: null,
    probeBusy: false
  };

  /* ------------------------------------------------------------ utils --- */
  function $(id) { return document.getElementById(id); }
  var ENT = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ENT[c]; }); }
  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function t(k) { var s = STR[k]; return s ? (s[state.lang] || s.zh || k) : k; }
  function tf(k, map) { return t(k).replace(/\{(\w+)\}/g, function (_, n) { return map && map[n] != null ? map[n] : ''; }); }
  function pick(en, zh) { return state.lang === 'en' ? (en || zh || '') : (zh || en || ''); }
  function nfo(n) { return (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('en-US'); }
  function ico(name, cls) { return '<i class="ph ' + (PH[name] || PH.dashboard) + (cls ? ' ' + cls : '') + '" aria-hidden="true"></i>'; }
  function norm(s) { return String(s || '').toLowerCase(); }
  function hhmmss(d) { return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2); }

  function toast(msg) {
    var el = $('toast'); if (!el) return;
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.hidden = true; }, 2800);
  }
  function ago(ts) {
    var s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return t('justnow');
    if (s < 3600) return state.lang === 'en' ? s + ' min ago' : s + ' 分钟前';
    if (s < 86400) return state.lang === 'en' ? Math.floor(s / 3600) + ' h ago' : Math.floor(s / 3600) + ' 小时前';
    if (s < 604800) return state.lang === 'en' ? Math.floor(s / 86400) + ' d ago' : Math.floor(s / 86400) + ' 天前';
    var d = new Date(ts);
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }

  /* 顶栏 sticky，右栏 sticky 的 top 必须等于它的真实高度；语言/字号/换行都会改它，
     所以实测而不是在 CSS 里写死。 */
  function syncMastH() {
    var m = document.querySelector('.olr-mast');
    if (m) document.documentElement.style.setProperty('--mast-h', Math.round(m.getBoundingClientRect().height) + 'px');
  }

  /* --------------------------------------------------- 目录与权限 ------- */
  function canSee(item) {
    var A = window.MSPortalAccess;
    return A ? A.canSee(state.authUser, item) : true;
  }
  function visibleItems() { return state.items.filter(canSee); }
  function inGids(item, gids) {
    var gs = item.groups || [];
    return gids.some(function (g) { return gs.indexOf(g) !== -1; });
  }
  function pageKeyOf(item) {
    try { return new URL(String(item.url || ''), location.href).searchParams.get('page') || ''; } catch (e) { return ''; }
  }
  function domainItems(d) { return visibleItems().filter(function (it) { return inGids(it, d.gids); }); }
  function supportItems(sec) {
    return visibleItems().filter(function (it) {
      if (DOMAINS.some(function (d) { return inGids(it, d.gids); })) return false;  /* 业务域收走的不重复 */
      return inGids(it, sec.gids);
    });
  }
  /* 被新自定义分组（既不在四个域、也不在辅助区）收留的看板，兜底列出，绝不静默丢失 */
  function orphanItems() {
    var all = [];
    DOMAINS.forEach(function (d) { all = all.concat(d.gids); });
    SUPPORT.forEach(function (s) { all = all.concat(s.gids); });
    return visibleItems().filter(function (it) { return !inGids(it, all); });
  }
  function matches(item, q) {
    if (!q) return true;
    var hay = norm([item.titleEn, item.titleZh, item.descEn, item.descZh,
      (item.tags || []).join(' '), item.owner, item.ownerEn, item.dept, item.deptEn, item.freq].join(' '));
    return q.split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; });
  }
  function groupSub(gid) {
    var g = (DATA.groups || []).filter(function (x) { return x.id === gid; })[0];
    return g ? pick(g.subEn, g.subZh) : '';
  }

  /* 关键词高亮：在**原始文本**上切段再逐段转义，绝不对已转义的 HTML 做正则 */
  function hit(text, q) {
    var s = String(text == null ? '' : text);
    if (!q) return esc(s);
    var words = q.split(/\s+/).filter(Boolean).map(reEsc);
    if (!words.length) return esc(s);
    var re = new RegExp('(' + words.join('|') + ')', 'ig');
    var out = '', last = 0, m;
    while ((m = re.exec(s)) !== null) {
      if (!m[0]) { re.lastIndex++; continue; }
      if (m.index > last) out += esc(s.slice(last, m.index));
      out += '<mark>' + esc(m[0]) + '</mark>';
      last = m.index + m[0].length;
    }
    return out + esc(s.slice(last));
  }

  /* ------------------------------------------------------- 看板行 ------- */
  function viewerHref(item) {
    var gid = (item.groups && item.groups[0]) || '';
    return '/MsPortal/viewer.html?no=' + encodeURIComponent(item.no) + (gid ? '&gid=' + encodeURIComponent(gid) : '');
  }
  function isDirectLink(item) { return inGids(item, ['Friends Link']); }
  function hrefOf(item) { return isDirectLink(item) ? item.url : viewerHref(item); }

  function rowHtml(item) {
    var q = state.q;
    var direct = isDirectLink(item);
    var title = pick(item.titleEn, item.titleZh) || item.titleZh || ('#' + item.no);
    var desc = pick(item.descEn, item.descZh) || '';
    var pf = item.platform === 'myapp' ? 'my_app' : item.platform === 'finebi' ? 'FineBI' : item.platform === 'external' ? 'External' : '';
    var chips = '';
    if (item.status === 'beta') chips += '<span class="tag tag--beta" title="' + esc(t('beta.tip')) + '">' + esc(t('beta')) + '</span>';
    if (item.isNew) chips += '<span class="tag tag--new">' + esc(t('new')) + '</span>';
    if (pf) chips += '<span class="tag tag--pf">' + esc(pf) + '</span>';
    var who = pick(item.deptEn, item.dept) || pick(item.ownerEn, item.owner) || '';
    var tip = title + (desc ? '\n' + desc : '') + (who ? '\n' + who : '') + (item.freq ? '\n' + item.freq : '');
    return '<a class="olr-row" href="' + esc(hrefOf(item)) + '"' +
      (direct ? ' target="_blank" rel="noopener noreferrer"' : '') +
      ' data-no="' + esc(item.no) + '" title="' + esc(tip) + '">' +
      '<span class="olr-row-ic">' + ico(item.icon) + '</span>' +
      '<span class="olr-row-tx">' +
        '<span class="olr-row-t">' + hit(title, q) + '</span>' +
        (desc ? '<span class="olr-row-d">' + hit(desc, q) + '</span>' : '') +
      '</span>' +
      '<span class="olr-row-meta">' + chips + '</span>' +
      '<span class="olr-row-go ph ' + (direct ? 'ph-arrow-up-right' : 'ph-caret-right') + '" aria-hidden="true"></span>' +
    '</a>';
  }
  function rowsHtml(list) { return '<div class="olr-rows">' + list.map(rowHtml).join('') + '</div>'; }

  /* --------------------------------------------------- 业务域区块 ------- */
  function domainHtml(d) {
    var all = domainItems(d);
    if (!all.length) return '';
    var used = {}, groups = [];
    d.clusters.forEach(function (c) {
      var list = all.filter(function (it) { return c.nos.indexOf(it.no) !== -1 && matches(it, state.q); });
      list.forEach(function (it) { used[it.no + '|' + d.key] = 1; });
      if (list.length) groups.push({ c: c, list: list });
    });
    var rest = all.filter(function (it) { return !used[it.no + '|' + d.key] && matches(it, state.q); });
    if (rest.length) groups.push({ c: { zh: t('other'), en: t('other') }, list: rest });
    var shown = groups.reduce(function (n, g) { return n + g.list.length; }, 0);
    if (!shown) return '';

    var body = groups.map(function (g) {
      var solo = groups.length === 1;
      return '<div class="olr-cluster' + (solo ? ' is-solo' : '') + '">' +
        (solo ? '' : '<span class="eyebrow">' + esc(pick(g.c.en, g.c.zh)) + '</span>') +
        rowsHtml(g.list) +
      '</div>';
    }).join('');

    var word = state.lang === 'en' ? 'dashboards' : '个看板';
    return '<section class="olr-domain" id="dom-' + d.key + '" data-domain="' + d.key + '" aria-label="' + esc(d.key) + ' view">' +
      '<header class="olr-domain-head">' +
        '<span class="olr-domain-no">' + d.no + '</span>' +
        '<div class="olr-domain-tt">' +
          '<h3>' + esc(d.key) + ' <em>' + esc(state.lang === 'en' ? 'Management' : '管理') + '</em></h3>' +
          '<p>' + esc(groupSub(d.gids[0])) + '</p>' +
        '</div>' +
        '<span class="olr-domain-n"><a href="' + esc('/MsPortal/viewer.html?gid=' + encodeURIComponent(d.gids[0])) +
          '" target="_blank" rel="noopener noreferrer" title="' + esc(t('more.catalogue')) + '">' + shown + ' ' + word + '</a></span>' +
      '</header>' + body +
    '</section>';
  }

  /* --------------------------------------------- Quality Control 状态条 -- */
  function metric(id) {
    var m = state.qc && state.qc.metrics && state.qc.metrics[id];
    return m || null;
  }
  function qcMetricHtml(def) {
    var m = metric(def.id);
    var num = m && m.value != null ? nfo(m.value) : '<span class="skel">000</span>';
    var extra = '';
    if (def.id === 'pmt' && m && m.overdue) {
      extra = '<span class="olr-qc-m-u is-warn">· ' + nfo(m.overdue) + ' ' + esc(state.lang === 'en' ? 'overdue' : '超期') + '</span>';
    }
    var title = pick(def.en, def.zh) + ' — ' + t('qc.tip') + (m && m.error ? '\n' + m.error : '');
    return '<button type="button" class="olr-qc-m" data-qc="' + esc(def.id) + '" title="' + esc(title) + '">' +
      '<span class="olr-qc-m-l">' + esc(pick(def.en, def.zh)) + '</span>' +
      '<span class="olr-qc-m-n">' + num + '</span>' + extra +
    '</button>';
  }
  function renderQc() {
    var el = $('qc');
    if (!el) return;
    var cats = { network: [], service: [], maint: [] };
    (DATA.qc || []).forEach(function (m) { (cats[QC_CAT[m.id]] || cats.service).push(m); });
    var sla = metric('sla');
    var slaCls = !sla ? '' : sla.value >= 95 ? 'is-ok' : sla.value >= 85 ? 'is-warn' : 'is-bad';
    var slaTip = sla ? tf('work.miss.d', {}) + ' · ' + nfo(sla.pass) + '/' + nfo(sla.total) + ' · ' + sla.days + 'd' : '';
    var at = state.qc && state.qc.generated_at ? new Date(state.qc.generated_at) : null;

    el.innerHTML =
      '<div class="olr-qc-head">' +
        '<span class="eyebrow">' + esc(t('qc.title')) + '</span>' +
        '<span class="olr-qc-head-r">' +
          '<span>' + esc(t('qc.updated')) + ' <span class="mono" id="qcAt">' + esc(at && !isNaN(at) ? hhmmss(at) : '—') + '</span></span>' +
          '<span class="olr-qc-sla ' + slaCls + '" title="' + esc(slaTip) + '">' + esc(t('qc.compliance')) +
            ' <b>' + (sla ? esc(sla.value) + '%' : '—') + '</b></span>' +
          '<button type="button" class="olr-link" data-act="esc">' + esc(t('qc.esc')) + '</button>' +
        '</span>' +
      '</div>' +
      '<div class="olr-qc-body">' +
        ['network', 'service', 'maint'].map(function (c) {
          return '<div class="olr-qc-cat">' +
            '<span class="olr-qc-cat-name">' + esc(t('cat.' + c)) + '</span>' +
            cats[c].map(qcMetricHtml).join('') + '</div>';
        }).join('') +
      '</div>';
  }

  /* ------------------------------------------------- 右栏：网络概览 ------ */
  /* 关键约定：面板骨架只建一次。地图 iframe 重新加载要几十秒，
     任何一次「换语言 / 刷新 QC 数字」都不能重播 el.innerHTML。 */
  function mapItems() {
    var vis = visibleItems();
    return MAP_TABS.map(function (m) {
      var item = vis.filter(function (it) { return pageKeyOf(it) === m.page; })[0];
      return item ? { page: m.page, zh: m.zh, en: m.en, icon: m.icon, item: item } : null;
    }).filter(Boolean);
  }
  function renderNet() {
    var el = $('net');
    if (!el) return;
    var tabs = mapItems();
    if (!tabs.length) { el.hidden = true; return; }
    el.hidden = false;
    if (!mapItems().some(function (m) { return m.page === state.mapTab; })) state.mapTab = tabs[0].page;

    if (!$('mapHost')) {
      el.innerHTML =
        '<div class="olr-panel-head"><div>' +
          '<span class="eyebrow">' + esc(t('net.title')) + '</span>' +
          '<p class="olr-panel-sub">' + esc(t('net.sub')) + '</p>' +
        '</div><span class="olr-panel-sub" id="netCur"></span></div>' +
        '<div class="olr-map-tabs" id="mapTabs" role="tablist" aria-label="Topology maps"></div>' +
        '<div class="olr-map-frame" id="mapHost"></div>' +
        '<div class="olr-map-foot olr-panel-bd" id="mapFoot"></div>';
    }
    $('mapTabs').innerHTML = tabs.map(function (m) {
      return '<button type="button" class="olr-map-tab" role="tab" data-page="' + esc(m.page) + '" ' +
        'aria-selected="' + (m.page === state.mapTab) + '">' + ico(m.icon) +
        '<span>' + esc(pick(m.en, m.zh)) + '</span></button>';
    }).join('');
    var cur = tabs.filter(function (m) { return m.page === state.mapTab; })[0];
    $('netCur').textContent = cur ? pick(cur.item.titleEn, cur.item.titleZh) : '';
    $('mapFoot').innerHTML = (function () {
      var a = metric('alarm');
      var bad = a && a.value ? ' is-bad' : '';
      return '<span class="' + (a && a.value ? 'is-bad' : '') + '">' + esc(t('net.alarms')) + ' <b>' + (a ? nfo(a.value) : '—') + '</b></span>' +
        '<span' + bad + '>' + esc(t('net.down')) + ' <b>' + (a ? nfo(a.sites) : '—') + '</b></span>' +
        '<a class="olr-link" href="' + esc(cur ? viewerHref(cur.item) : '/MsPortal/') +
          '" target="_blank" rel="noopener noreferrer">' + esc(t('net.full')) + ' ↗</a>';
    })();
    ensureFrame(state.mapTab);
  }
  function ensureFrame(page) {
    var host = $('mapHost');
    if (!host) return;
    if (!state.mapBooted) {
      var note = document.createElement('div');
      note.className = 'olr-map-note';
      note.id = 'mapNote';
      note.innerHTML = '<span>' + esc(t('net.loading')) + '</span>';
      host.appendChild(note);
      state.mapBooted = true;
    }
    var id = 'fr-' + page;
    if (!$(id)) {
      var f = document.createElement('iframe');
      f.id = id;
      f.setAttribute('title', page);
      f.setAttribute('src', '/myapp/?page=' + encodeURIComponent(page) + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : ''));
      f.addEventListener('load', function () { var n = $('mapNote'); if (n) n.hidden = true; });
      f.addEventListener('error', function () { var n = $('mapNote'); if (n) n.hidden = true; });
      host.appendChild(f);
    }
    var n2 = $('mapNote');
    if (n2) n2.hidden = true;
    Array.prototype.forEach.call(host.querySelectorAll('iframe'), function (x) {
      x.classList.toggle('is-on', x.id === id);
    });
  }
  function relaunchFrames() {
    /* 主题切换要重开地图（my_app 的嵌入页按 URL 参数决定配色），
       但保留「已建过哪些页签」这件事，避免把没看过的页签也拉起来。 */
    var host = $('mapHost');
    if (!host) return;
    Array.prototype.forEach.call(host.querySelectorAll('iframe'), function (f) {
      var page = f.id.replace(/^fr-/, '');
      f.setAttribute('src', '/myapp/?page=' + encodeURIComponent(page) + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : ''));
    });
  }

  /* ---------------------------------------------- 右栏：待处理 / 最近 ---- */
  function workRows() {
    if (!state.qc) return null;
    var m = state.qc.metrics || {}, out = [];
    function add(label, note, val, cls, metric) {
      if (val == null || isNaN(val)) return;
      out.push({ label: label, note: note, val: val, cls: cls, metric: metric });
    }
    if (m.alarm) {
      add(t('work.sites'), t('work.sites.d'), m.alarm.sites, m.alarm.sites > 0 ? 'is-bad' : 'is-ok', 'alarm');
      add(t('work.alarm'), t('work.alarm.d'), m.alarm.value, m.alarm.value > 0 ? 'is-warn' : 'is-ok', 'alarm');
    }
    if (m.pmt) add(t('work.overdue'), t('work.overdue.d'), m.pmt.overdue, m.pmt.overdue > 0 ? 'is-bad' : 'is-ok', 'pmt');
    if (m.sla && m.sla.total) add(t('work.miss'), t('work.miss.d'), Math.max(0, m.sla.total - m.sla.pass), 'is-warn', null);
    if (m.spms && m.spms.tables) add(t('work.outband'), t('work.outband.d'), m.spms.tables.outband_details,
      m.spms.tables.outband_details > 0 ? 'is-warn' : 'is-ok', 'spms');
    return out;
  }
  function renderWork() {
    var el = $('work');
    if (!el) return;
    var rows = workRows();
    var body = rows && rows.length
      ? rows.map(function (r) {
          return '<button type="button" class="olr-li"' + (r.metric ? ' data-qc="' + esc(r.metric) + '"' : ' disabled') + '>' +
            '<span class="olr-li-t">' + esc(r.label) + '<span class="olr-li-d">' + esc(r.note) + '</span></span>' +
            '<span class="olr-li-n ' + r.cls + '">' + nfo(r.val) + '</span>' +
            (r.metric ? '<span class="olr-li-go ph ph-caret-right"></span>' : '') +
          '</button>';
        }).join('')
      : '<p class="olr-hint"><span class="skel">·········</span></p>';
    el.innerHTML =
      '<div class="olr-panel-head"><span class="eyebrow">' + esc(t('work.title')) + '</span>' +
        '<span class="olr-panel-sub">' + esc(t('work.open')) + '</span></div>' +
      '<div class="olr-list">' + body + '</div>';
  }
  function renderRecent() {
    var el = $('recent');
    if (!el) return;
    var byNo = {};
    state.items.forEach(function (it) { byNo[it.no] = it; });
    var list = (state.recent || []).map(function (r) {
      var it = byNo[r.no];
      return it && canSee(it) ? { it: it, at: r.at } : null;
    }).filter(Boolean).slice(0, 6);
    el.innerHTML =
      '<div class="olr-panel-head"><span class="eyebrow">' + esc(t('recent.title')) + '</span></div>' +
      '<div class="olr-list">' + (list.length
        ? list.map(function (r) {
            return '<a class="olr-recent" href="' + esc(hrefOf(r.it)) + '"' +
              (isDirectLink(r.it) ? ' target="_blank" rel="noopener noreferrer"' : '') +
              ' data-no="' + esc(r.it.no) + '">' +
              '<span class="olr-recent-t">' + esc(pick(r.it.titleEn, r.it.titleZh)) + '</span>' +
              '<span class="olr-recent-m">' + esc(ago(r.at)) + '</span></a>';
          }).join('')
        : '<p class="olr-hint">' + esc(t('recent.empty')) + '</p>') +
      '</div>';
  }

  /* ------------------------------------------------- 底部：辅助入口 ------ */
  function renderMore() {
    var el = $('more');
    if (!el) return;
    var secs = SUPPORT.map(function (s) {
      var list = supportItems(s).filter(function (it) { return matches(it, state.q); });
      if (!list.length) return '';
      return '<div class="olr-more-sec">' +
        '<h4>' + esc(pick(s.en, s.zh)) + '</h4>' +
        '<p>' + esc(s.gids.map(function (g) { return groupSub(g); }).filter(Boolean).join(' · ')) + '</p>' +
        rowsHtml(list) + '</div>';
    }).join('');
    var orph = orphanItems().filter(function (it) { return matches(it, state.q); });
    if (orph.length) secs += '<div class="olr-more-sec"><h4>' + esc(t('other')) + '</h4>' + rowsHtml(orph) + '</div>';
    if (!secs.replace(/\s/g, '')) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML =
      '<div class="olr-more-head">' +
        '<div><span class="eyebrow">' + esc(t('more.title')) + '</span><p>' + esc(t('more.note')) + '</p></div>' +
        '<a class="olr-link" href="/MsPortal/" target="_blank" rel="noopener noreferrer">' + esc(t('more.catalogue')) + ' ↗</a>' +
      '</div>' +
      '<div class="olr-more-grid">' + secs + '</div>';
  }

  /* ----------------------------------------------------- 检索 / 汇总 ----- */
  function domainCounts() {
    var vis = visibleItems();
    var out = { all: vis.filter(function (it) { return matches(it, state.q); }).length, byKey: {}, support: 0 };
    DOMAINS.forEach(function (d) {
      out.byKey[d.key] = vis.filter(function (it) { return inGids(it, d.gids) && matches(it, state.q); }).length;
    });
    SUPPORT.forEach(function (s) {
      out.support += supportItems(s).filter(function (it) { return matches(it, state.q); }).length;
    });
    out.support += orphanItems().filter(function (it) { return matches(it, state.q); }).length;
    return out;
  }
  function renderJump() {
    var el = $('jump');
    if (!el) return;
    var c = domainCounts();
    var btns = [{ k: 'all', label: t('jump.all'), n: c.all }];
    DOMAINS.forEach(function (d) { if (c.byKey[d.key]) btns.push({ k: d.key, label: d.key, n: c.byKey[d.key] }); });
    if (c.support) btns.push({ k: 'support', label: t('jump.support'), n: c.support });
    el.innerHTML = btns.map(function (b) {
      return '<button type="button" class="olr-jump-btn" data-jump="' + esc(b.k) + '" aria-pressed="' + (state.domain === b.k) + '">' +
        esc(b.label) + '<span>' + b.n + '</span></button>';
    }).join('');
    var total = visibleItems().length;
    var cnt = $('count');
    if (cnt) cnt.textContent = state.q ? tf('count.hit', { m: c.all, n: total }) : tf('count.of', { n: total });
  }
  function applyDomainFilter() {
    var f = state.domain;
    Array.prototype.forEach.call(document.querySelectorAll('.olr-domain[data-domain]'), function (b) {
      b.classList.toggle('is-off', !(f === 'all' || f === b.getAttribute('data-domain')));
    });
    var more = $('more');
    if (more) more.classList.toggle('is-off', !(f === 'all' || f === 'support'));
    /* 只看某一个域时，其余域与辅助区整块隐藏；如果目标域正好被筛空了要给提示 */
    var vis = document.querySelector('.olr-domain:not(.is-off)') ||
      (more && !more.classList.contains('is-off') && !more.hidden ? more : null);
    var nm = $('noMatch');
    if (nm) nm.hidden = !!vis;
  }

  function renderCatalog() {
    var host = $('domains');
    var nm = $('noMatch');
    if (REQUIRE_LOGIN && state.authOk !== true) {
      host.innerHTML =
        '<section class="olr-domain" style="border-top:0">' +
          '<header class="olr-domain-head"><span class="olr-domain-no">--</span>' +
            '<div class="olr-domain-tt"><h3>' + esc(t('gate.title')) + '</h3>' +
            '<p>' + esc(t('gate.note')) + '</p></div></header>' +
          '<p style="margin:14px 0 0 32px"><button type="button" class="olr-btn primary" data-act="login">' + esc(t('gate.btn')) + '</button></p>' +
        '</section>';
      $('more').hidden = true;
      if (nm) nm.hidden = true;
      renderJump();
      return;
    }
    var html = DOMAINS.map(domainHtml).join('');
    host.innerHTML = html;
    var none = !html.replace(/\s/g, '');
    if (nm) { nm.hidden = !none; if (none) nm.innerHTML = '<b>' + esc(t('empty')) + '</b>'; }
    renderMore();
    renderJump();
    applyDomainFilter();
  }

  function renderStatic() {
    document.documentElement.setAttribute('lang', state.lang === 'en' ? 'en' : 'zh-CN');
    Array.prototype.forEach.call(document.querySelectorAll('[data-i18n]'), function (n) {
      n.textContent = t(n.getAttribute('data-i18n'));
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-i18n-attr]'), function (n) {
      n.getAttribute('data-i18n-attr').split(';').forEach(function (pair) {
        var kv = pair.split(':');
        if (kv.length === 2) n.setAttribute(kv[0].trim(), t(kv[1].trim()));
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-lang]'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-lang') === state.lang));
    });
    var tb = $('themeBtn');
    if (tb) tb.innerHTML = '<i class="ph ' + (state.theme === 'dark' ? 'ph-sun' : 'ph-moon') + '" aria-hidden="true"></i>';
  }

  function renderAll() {
    renderStatic();
    renderUser();
    renderQc();
    renderCatalog();
    renderNet();
    renderWork();
    renderRecent();
    syncMastH();
  }

  /* --------------------------------------------------------- 顶栏用户 ---- */
  function userMenuHtml() {
    var u = state.authUser;
    var who = (u && (u.username || u.name || u.id)) || t('user.local');
    var role = u && u.role === 'admin' ? t('role.admin') : u && u.role ? t('role.viewer') : '';
    var out = '<div class="olr-user-hd"><b>' + esc(who) + '</b><span>' +
        esc((state.authOk === false ? t('gate.note') : t('user.signed') + (role ? ' · ' + role : ''))) +
      '</span></div>' +
      '<button type="button" class="olr-menu-item" data-act="theme"><i class="ph ' + (state.theme === 'dark' ? 'ph-sun' : 'ph-moon') + '"></i>' + esc(t('menu.appearance')) + '</button>' +
      '<a class="olr-menu-item" href="/uniplam/" target="_blank" rel="noopener noreferrer"><i class="ph ph-graph"></i>' + esc(t('menu.portal')) + '</a>' +
      '<a class="olr-menu-item" href="/MsPortal/" target="_blank" rel="noopener noreferrer"><i class="ph ph-squares-four"></i>' + esc(t('menu.catalogue')) + '</a>';
    if (u && u.role === 'admin') {
      out += '<a class="olr-menu-item" href="/uniplam/" target="_blank" rel="noopener noreferrer"><i class="ph ph-users-four"></i>' + esc(t('menu.usermgmt')) + '</a>';
    }
    out += '<div class="olr-menu-sep"></div>' +
      (state.authOk === false
        ? '<button type="button" class="olr-menu-item" data-act="login"><i class="ph ph-user"></i>' + esc(t('gate.btn')) + '</button>'
        : '<button type="button" class="olr-menu-item danger" data-act="logout"><i class="ph ph-sign-out"></i>' + esc(t('menu.logout')) + '</button>');
    return out;
  }
  function renderUser() {
    var u = state.authUser;
    var name = $('userName');
    if (name) name.textContent = (u && (u.username || u.name || u.id)) || (state.authOk === false ? t('gate.btn') : t('user.local'));
  }
  function openUserMenu(on) {
    var list = $('userMenuList'), btn = $('userBtn');
    if (!list || !btn) return;
    var show = on === undefined ? list.hidden : !!on;
    if (show) list.innerHTML = userMenuHtml();
    list.hidden = !show;
    btn.setAttribute('aria-expanded', String(show));
  }

  /* ------------------------------------------------------ 鉴权与会话 ----- */
  function token() { return readLS(PORTAL_TOKEN_KEY); }
  function apiMe() {
    return fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.user ? d.user : null; })
      .catch(function () { return null; });
  }
  function apiPortalMe(tk) {
    return fetch('/uniplam/api/auth/me', { credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.user ? d.user : null; })
      .catch(function () { return null; });
  }
  function swapToken(tk) {
    return fetch('/api/auth/portal-login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tk })
    }).then(function (r) { return r.ok; }).catch(function () { return false; });
  }

  /** my_app 会话 + 统一门户 token 一起探：拿到门户身份就用它判权限（口径与 /MsPortal/ 一致）。 */
  function probe() {
    if (state.probeBusy) return;
    state.probeBusy = true;
    var tk = token();
    apiMe().then(function (me) {
      if (me && !tk) { state.authOk = true; state.authUser = me; return null; }
      if (!me && !tk) { state.authOk = false; return null; }
      return apiPortalMe(tk).then(function (pu) {
        if (pu) { state.authOk = true; state.authUser = pu; return null; }
        if (me) { state.authOk = true; state.authUser = me; return null; }
        return swapToken(tk).then(function (ok) {
          if (!ok) { state.authOk = false; return null; }
          return apiMe().then(function (next) { state.authOk = !!next; if (next) state.authUser = next; });
        });
      });
    }).catch(function () { state.authOk = false; })
      .then(function () {
        state.probeBusy = false;
        renderAll();
        if (state.authOk === true) fetchQc();
      });
  }

  function login(user, pass) {
    return fetch('/uniplam/api/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: user, password: pass })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok || !d.token || !d.user) {
          var e = new Error(d.detail || 'login failed');
          e.code = r.status === 429 ? 'locked' : r.status === 401 ? 'bad' : 'net';
          throw e;
        }
        writeLS(PORTAL_TOKEN_KEY, d.token);
        if (d.user.mustChangePassword) { window.location.href = '/uniplam/'; return 'redirect'; }
        return swapToken(d.token);
      });
    });
  }
  function logout() {
    var tk = token();
    var reqs = [fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {})];
    if (tk) {
      reqs.push(fetch('/uniplam/api/auth/logout', {
        method: 'POST', credentials: 'same-origin',
        headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
      }).catch(function () {}));
    }
    Promise.all(reqs).then(function () {
      dropLS(PORTAL_TOKEN_KEY);
      state.authUser = null;
      state.authOk = null;
      openUserMenu(false);
      probe();
    });
  }

  /* ------------------------------------------------------ QC 明细弹窗 ---- */
  function openDrill(id) {
    if (!id) return;
    var def = (DATA.qc || []).filter(function (m) { return m.id === id; })[0];
    state.drill = { metric: id, page: 1, q: '', rows: [], columns: [], total: 0, err: '' };
    $('qcTitle').textContent = def ? pick(def.en, def.zh) : id;
    var s = $('qcSearch');
    s.value = ''; s.placeholder = t('qc.search');
    $('qcMask').hidden = false;
    loadDrill();
  }
  function closeDrill() { $('qcMask').hidden = true; state.drill = null; }

  function loadDrill() {
    var req = state.drill;
    if (!req) return;
    $('qcThead').innerHTML = '';
    $('qcTbody').innerHTML = '<tr><td class="mut">' + esc(t('qc.loading')) + '</td></tr>';
    $('qcCount').textContent = ''; $('qcPage').textContent = '';
    var url = '/api/portal-qc/detail?metric=' + encodeURIComponent(req.metric) +
      '&page=' + req.page + '&size=' + DRILL_SIZE + '&q=' + encodeURIComponent(req.q);
    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) {
        var d = state.drill;
        if (!d || d !== req) return;
        d.rows = j.rows || []; d.columns = j.columns || []; d.total = j.total || 0; d.err = '';
        paintDrill();
      })
      .catch(function () {
        var d = state.drill;
        if (!d || d !== req) return;
        d.err = t('qc.err'); d.rows = []; d.columns = [];
        paintDrill();
      });
  }
  function cellHtml(v) {
    if (v == null || v === '') return '<span class="esc-dash">—</span>';
    if (typeof v === 'number' && v > 1e11) {
      return '<span class="n">' + esc(new Date(v).toLocaleString(state.lang === 'en' ? 'en-GB' : 'zh-CN')) + '</span>';
    }
    return esc(String(v));
  }
  function paintDrill() {
    var d = state.drill;
    if (!d) return;
    if (d.err) {
      $('qcTbody').innerHTML = '<tr><td class="mut">' + esc(d.err) + '</td></tr>';
      return;
    }
    $('qcThead').innerHTML = '<tr>' + d.columns.map(function (c) { return '<th>' + esc(c.label) + '</th>'; }).join('') + '</tr>';
    $('qcTbody').innerHTML = d.rows.map(function (r) {
      return '<tr>' + d.columns.map(function (c) {
        if (c.key === 'severity' && r[c.key]) return '<td><span class="sev">' + esc(String(r[c.key])) + '</span></td>';
        var cls = /(no|id|code|time|qty)$/i.test(c.key) ? ' class="n"' : '';
        return '<td' + cls + '>' + cellHtml(r[c.key]) + '</td>';
      }).join('') + '</tr>';
    }).join('') || '<tr><td class="mut">—</td></tr>';
    var pages = Math.max(1, Math.ceil(d.total / DRILL_SIZE));
    $('qcCount').textContent = tf('qc.rows', { n: nfo(d.total) });
    $('qcPage').textContent = tf('qc.page', { p: d.page, t: pages });
    $('qcPrev').disabled = d.page <= 1;
    $('qcNext').disabled = d.page >= pages;
  }

  /* ------------------------------------------------------ 升级机制弹窗 ---- */
  function openEsc() {
    var E = DATA.escalation || { levels: [], rows: [] };
    var LV = { LEVEL1: 'esc-lv-1', LEVEL2: 'esc-lv-2', LEVEL3: 'esc-lv-3', LEVEL4: 'esc-lv-4' };
    var span = {}, cur = null;
    E.rows.forEach(function (r, i) {
      if (i === 0 || E.rows[i - 1].level !== r.level) { span[i] = 1; cur = i; }
      else span[cur]++;
    });
    var head = t('esc.head').split(',');
    var body = E.rows.map(function (r, i) {
      var lv = '';
      if (span[i]) {
        var def = E.levels.filter(function (l) { return l.id === r.level; })[0];
        lv = '<td class="esc-lv ' + (LV[r.level] || 'esc-lv-1') + '" rowspan="' + span[i] + '" title="' +
          esc(def ? pick(def.en, def.zh) : r.level) + '"><span class="esc-lv-badge">' + esc(r.level) + '</span></td>';
      }
      var mail = r.email
        ? '<a class="olr-link" href="mailto:' + esc(r.email) + '">' + esc(r.email) + '</a>'
        : '<span class="esc-dash">—</span>';
      var orange = r.orange ? esc(r.orange).replace(/\//g, '/<wbr>') : '<span class="esc-dash">—</span>';
      return '<tr class="' + (LV[r.level] || 'esc-lv-1') + '">' + lv +
        '<td>' + esc(r.position || '') + '</td><td>' + esc(r.name || '') + '</td>' +
        '<td class="n">' + orange + '</td><td class="n">' + (r.lonestar ? esc(r.lonestar) : '<span class="esc-dash">—</span>') + '</td>' +
        '<td>' + mail + '</td></tr>';
    }).join('');
    $('escBody').innerHTML = '<div class="esc-scroll"><table class="esc-table"><thead><tr>' +
      head.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + body + '</tbody></table></div>';
    $('escMask').hidden = false;
  }

  /* ---------------------------------------------------------- 数据加载 --- */
  function fetchQc() {
    fetch('/api/portal-qc/summary', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) { state.qc = j; renderQc(); renderWork(); renderNet(); })
      .catch(function () { renderQc(); renderWork(); });
  }
  /* 服务端全局目录优先：在 MsPortal 里编辑过看板，刷新本页就是最新的。 */
  function fetchCatalog() {
    fetch('/api/portal-catalog', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok || ct.indexOf('json') === -1) return null;
        return r.json();
      })
      .then(function (j) {
        if (j && j.catalog && j.catalog.items && j.catalog.items.length) state.items = j.catalog.items;
      })
      .catch(function () {})
      .then(function () { renderCatalog(); renderNet(); renderRecent(); });
  }

  /* ---------------------------------------------------------- 事件 ------- */
  function setTheme(next) {
    state.theme = next;
    writeLS(LS.theme, next);
    document.documentElement.setAttribute('data-theme', next === 'dark' ? 'dark' : 'light');
    renderStatic();
    relaunchFrames();
  }
  function setLang(next) {
    state.lang = next;
    writeLS(LS.lang, next);
    renderAll();
  }
  function rememberOpen(no) {
    if (!no) return;
    state.recent = [{ no: no, at: Date.now() }]
      .concat((state.recent || []).filter(function (r) { return Number(r.no) !== no; }))
      .slice(0, 12);
    writeJSON(LS.recent, state.recent);
    renderRecent();
  }

  var qTimer, dqTimer;
  function bind() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-lang]'), function (b) {
      b.addEventListener('click', function () { setLang(b.getAttribute('data-lang') === 'en' ? 'en' : 'zh'); });
    });
    $('themeBtn').addEventListener('click', function () { setTheme(state.theme === 'dark' ? 'light' : 'dark'); });

    $('userBtn').addEventListener('click', function (e) { e.stopPropagation(); openUserMenu(); });
    $('userMenuList').addEventListener('click', function (e) {
      var it = e.target.closest('[data-act]');
      if (!it) return;
      openUserMenu(false);
      var a = it.getAttribute('data-act');
      if (a === 'theme') setTheme(state.theme === 'dark' ? 'light' : 'dark');
      else if (a === 'logout') logout();
      else if (a === 'login') $('loginMask').hidden = false;
    });

    /* 一处委托搞定所有动态按钮：QC 指标、下钻、升级机制、地图页签、门禁登录 */
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#userMenu')) openUserMenu(false);

      var qc = e.target.closest('[data-qc]');
      if (qc && qc.getAttribute('data-qc')) { e.preventDefault(); openDrill(qc.getAttribute('data-qc')); return; }

      var esc2 = e.target.closest('[data-act="esc"]');
      if (esc2) { e.preventDefault(); openEsc(); return; }

      var lg = e.target.closest('[data-act="login"]');
      if (lg) { $('loginMask').hidden = false; return; }

      var tab = e.target.closest('.olr-map-tab');
      if (tab) {
        state.mapTab = tab.getAttribute('data-page');
        writeLS(LS.mapTab, state.mapTab);
        renderNet();
        return;
      }

      var jump = e.target.closest('[data-jump]');
      if (jump) {
        var k = jump.getAttribute('data-jump');
        state.domain = state.domain === k ? 'all' : k;
        applyDomainFilter();
        renderJump();
        var target = state.domain === 'support' ? $('more') : $('dom-' + state.domain);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }

      var a = e.target.closest('a[data-no]');
      if (a) rememberOpen(Number(a.getAttribute('data-no')));
    });

    var qi = $('q');
    qi.addEventListener('input', function () {
      clearTimeout(qTimer);
      var v = qi.value;
      qTimer = setTimeout(function () {
        state.q = norm(v).trim();
        $('qClear').hidden = !state.q;
        renderCatalog();
        syncMastH();
      }, 130);
    });
    $('qClear').addEventListener('click', function () {
      qi.value = ''; state.q = ''; $('qClear').hidden = true; renderCatalog(); qi.focus();
    });

    $('qcClose').addEventListener('click', closeDrill);
    $('qcMask').addEventListener('click', function (e) { if (e.target === $('qcMask')) closeDrill(); });
    $('qcReload').addEventListener('click', function () { fetchQc(); if (state.drill) loadDrill(); });
    $('qcSearch').addEventListener('input', function () {
      clearTimeout(dqTimer);
      var v = $('qcSearch').value;
      dqTimer = setTimeout(function () {
        if (!state.drill) return;
        state.drill.q = v; state.drill.page = 1; loadDrill();
      }, 280);
    });
    $('qcPrev').addEventListener('click', function () { if (state.drill && state.drill.page > 1) { state.drill.page--; loadDrill(); } });
    $('qcNext').addEventListener('click', function () { if (state.drill) { state.drill.page++; loadDrill(); } });
    $('escClose').addEventListener('click', function () { $('escMask').hidden = true; });
    $('escMask').addEventListener('click', function (e) { if (e.target === $('escMask')) $('escMask').hidden = true; });

    $('loginClose').addEventListener('click', function () { $('loginMask').hidden = true; });
    $('loginCancel').addEventListener('click', function () { $('loginMask').hidden = true; });
    $('loginMask').addEventListener('click', function (e) { if (e.target === $('loginMask')) $('loginMask').hidden = true; });
    $('loginForm').addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = $('loginSubmit'), err = $('loginErr');
      btn.disabled = true; btn.textContent = t('login.logging'); err.hidden = true;
      login($('loginUser').value.trim(), $('loginPass').value).then(function () {
        $('loginMask').hidden = true;
        $('loginPass').value = '';
        state.authOk = null;
        probe();
      }).catch(function (er) {
        err.textContent = er.code === 'locked' ? t('login.locked') : er.code === 'net' ? t('login.net') : t('login.bad');
        err.hidden = false;
        state.authOk = null;
        renderAll();
      }).finally(function () {
        btn.disabled = false; btn.textContent = t('login.submit');
      });
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (!$('qcMask').hidden) closeDrill();
        else if (!$('escMask').hidden) $('escMask').hidden = true;
        else if (!$('loginMask').hidden) $('loginMask').hidden = true;
        else openUserMenu(false);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault(); $('q').focus(); $('q').select();
      }
    });

    window.addEventListener('resize', syncMastH);
    /* 从看板页签切回来时刷新一次数字：工作台的价值就在「现在怎么样」 */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && state.authOk === true) fetchQc();
    });
  }

  /* ---------------------------------------------------------- boot ------- */
  function boot() {
    if (state.theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    renderAll();
    bind();
    syncMastH();
    probe();
    fetchCatalog();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
