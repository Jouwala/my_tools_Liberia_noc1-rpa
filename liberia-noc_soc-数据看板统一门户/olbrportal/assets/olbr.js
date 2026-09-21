/* ============================================================================
   olbr.js — OLR MS 门户「只读展示版」
   ----------------------------------------------------------------------------
   数据来源（全部只读，不写 MsPortal 的任何文件）：
     · /MsPortal/assets/data.js   → window.MS_PORTAL_DATA（51 个看板 / 9 分组 / QC 定义 / 升级机制）
     · /MsPortal/assets/access.js → window.MSPortalAccess.canSee（与门户、查看器同一套权限判定）
     · GET /api/portal-catalog    → 服务端全局目录（有则覆盖内置，无则用内置）
     · GET /api/portal-qc/*       → 六个实时指标与下钻明细
     · /MsPortal/viewer.html      → 看板查看器（打开动作整个交给它，本页不重复实现）
   本页不提供分组编辑 / 看板维护 / 用户管理 —— 那些仍归 /MsPortal/。

   与 MsPortal 刻意不同的四处（都是上一轮评审的结论）：
     1  搜索与筛选常驻、且**不持久化**。MsPortal 会把上次的筛选写进 localStorage，
        下次打开时 13 个面板里 7 个显示空态，用户以为系统坏了。
     2  筛选生效时**隐藏没有结果的分组面板**，而不是给每个面板摆一个空态框。
     3  升级机制默认收成一条值班带（52px），展开才出全表（原来常驻 583px）。
     4  卡片只有两种、强调色只有两个色相，图标砖不再按分组上实色。
   ========================================================================== */
(function () {
  'use strict';

  var D = window.MS_PORTAL_DATA || {};
  var ACC = window.MSPortalAccess || { canSee: function () { return true; } };
  var root = document.documentElement;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* --------------------------------------------------------------- i18n -- */
  var S = {
    zh: {
      'tagline': '更智能的运维 · 更高的效率 · 更好的网络',
      'mast.admin': '管理门户', 'mast.uni': '统一门户', 'mast.logout': '退出',
      'skip': '跳到主内容',
      'search.ph': '搜索看板名称、描述、责任人、标签…',
      'rail.all': '全部', 'rail.clear': '清除筛选',
      'count.all': '{n} 个看板 · {g} 个分组',
      'count.hit': '{n} / {t} 个看板命中',
      'qc.title': 'Quality Control 质量监控核心指标',
      'qc.sub': '未清除告警 / 工单 / 变更 / 维护 / 备件 · 30 天达标口径',
      'qc.sla': '30 天达标率', 'qc.of': '{p} / {q} 站点',
      'qc.when': '告警每 5 分钟 · 其余每小时 :06 · 更新于 {t}',
      'qc.err': '指标接口不可用：{e}', 'qc.retry': '重试',
      'qc.drill': '点击查看明细',
      'cxo.title': 'CXO View 决策战略层', 'cxo.sub': '统一总控与运营视窗',
      'map.title': '利比里亚网络拓扑全景', 'map.sub': 'Central Liberia Regional Topology',
      'map.gis': 'GIS 地图', 'map.mw': '微波实时', 'map.alarm': '实时告警', 'map.loss': '传输丢包',
      'map.open': '新窗口打开', 'map.reload': '重新加载', 'map.load': '加载中…',
      'esc.title': '升级机制 Escalation Matrix',
      'esc.sub': '值班升级联系人 · Orange / LONESTAR 双网号码',
      'esc.expand': '展开全部 {n} 条', 'esc.collapse': '收起',
      'esc.now': '当前值班', 'esc.copy': '复制本级号码', 'esc.copied': '已复制',
      'esc.lv': '职级', 'esc.pos': '岗位', 'esc.name': '姓名', 'esc.mail': '邮箱',
      'esc.count': '{n} 条 · {lv} 级', 'esc.src': '数据源：升级机制.xlsx',
      'v.open': '查看全部', 'v.empty': '该分组暂无看板',
      'v.emptyFilter': '当前筛选下没有看板', 'v.adjust': '调整关键词或清除筛选',
      'aux.qa': '知识库与技术支持', 'aux.friends': '生态协作入口', 'aux.admin': '系统与运维配置',
      'aux.reports': '任务报告文件', 'aux.tools': '本页相关',
      'aux.ms': '在 MsPortal 维护分组 / 看板 / 账号', 'aux.uni': '统一门户看板门户',
      'aux.more': '展开其余 {n} 项', 'aux.less': '收起',
      'foot.branch': '利比里亚办事处网络运营中心 (OLR MS)', 'foot.ok': '安全合规模式运行',
      'foot.src': '目录：{n} 个看板 · 生成于 {d}',
      'st.online': '在线', 'st.beta': '试用',
      'pf.myapp': '自研 my_app', 'pf.finebi': 'FineBI', 'pf.external': '外部系统',
      'gate.title': '登录统一门户', 'gate.sub': '与 /uniplam/、/MsPortal/ 共用同一套账号与权限。',
      'gate.user': '用户名', 'gate.pass': '密码', 'gate.go': '登录', 'gate.busy': '登录中…',
      'gate.bad': '用户名或密码错误', 'gate.locked': '尝试次数过多，稍后再试',
      'gate.net': '无法连接认证服务', 'gate.cancel': '取消',
      'dr.title': '明细', 'dr.rows': '{n} 条', 'dr.page': '{p} / {q}',
      'dr.load': '正在读取明细…', 'dr.empty': '没有匹配的记录', 'dr.err': '明细读取失败：{e}',
      'dr.none': '暂无数据'
    },
    en: {
      'tagline': 'Smarter Operations · Higher Efficiency · Better Network',
      'mast.admin': 'Admin portal', 'mast.uni': 'Unified portal', 'mast.logout': 'Sign out',
      'skip': 'Skip to main content',
      'search.ph': 'Search dashboards, owners, tags…',
      'rail.all': 'All', 'rail.clear': 'Clear filters',
      'count.all': '{n} dashboards · {g} groups',
      'count.hit': '{n} / {t} dashboards match',
      'qc.title': 'Quality Control — key indicators',
      'qc.sub': 'Active alarms / tickets / changes / PMT / spares · 30-day compliance',
      'qc.sla': '30-day compliance', 'qc.of': '{p} / {q} sites',
      'qc.when': 'alarms every 5 min · others hourly :06 · updated {t}',
      'qc.err': 'Indicator API unavailable: {e}', 'qc.retry': 'Retry',
      'qc.drill': 'Click for details',
      'cxo.title': 'CXO View', 'cxo.sub': 'Executive strategy & operation window',
      'map.title': 'Central Liberia Regional Topology', 'map.sub': 'Network panorama',
      'map.gis': 'GIS map', 'map.mw': 'MW real-time', 'map.alarm': 'Live alarms', 'map.loss': 'Packet loss',
      'map.open': 'Open in new tab', 'map.reload': 'Reload', 'map.load': 'Loading…',
      'esc.title': 'Escalation Matrix',
      'esc.sub': 'Duty contacts · Orange / LONESTAR numbers',
      'esc.expand': 'Expand all {n} rows', 'esc.collapse': 'Collapse',
      'esc.now': 'On duty', 'esc.copy': 'Copy this level', 'esc.copied': 'Copied',
      'esc.lv': 'Level', 'esc.pos': 'Position', 'esc.name': 'Name', 'esc.mail': 'E-mail',
      'esc.count': '{n} rows · {lv} levels', 'esc.src': 'Source: 升级机制.xlsx',
      'v.open': 'Full list', 'v.empty': 'No dashboard in this group',
      'v.emptyFilter': 'Nothing matches the current filters', 'v.adjust': 'Adjust keywords or clear filters',
      'aux.qa': 'Knowledge & support', 'aux.friends': 'Ecosystem entries', 'aux.admin': 'System & O&M',
      'aux.reports': 'Task report files', 'aux.tools': 'About this page',
      'aux.ms': 'Manage groups / dashboards / accounts in MsPortal', 'aux.uni': 'Unified dashboard portal',
      'aux.more': 'Show {n} more', 'aux.less': 'Show less',
      'foot.branch': 'Liberia Office · Network Operation Center (OLR MS)', 'foot.ok': 'Compliance mode',
      'foot.src': 'Catalog: {n} dashboards · built {d}',
      'st.online': 'online', 'st.beta': 'beta',
      'pf.myapp': 'my_app', 'pf.finebi': 'FineBI', 'pf.external': 'external',
      'gate.title': 'Sign in to the unified portal',
      'gate.sub': 'Same account and permissions as /uniplam/ and /MsPortal/.',
      'gate.user': 'Username', 'gate.pass': 'Password', 'gate.go': 'Sign in', 'gate.busy': 'Signing in…',
      'gate.bad': 'Wrong username or password', 'gate.locked': 'Too many attempts, try later',
      'gate.net': 'Cannot reach the auth service', 'gate.cancel': 'Cancel',
      'dr.title': 'Details', 'dr.rows': '{n} rows', 'dr.page': '{p} / {q}',
      'dr.load': 'Loading details…', 'dr.empty': 'No matching record', 'dr.err': 'Detail failed: {e}',
      'dr.none': 'No data'
    }
  };

  function t(k) { var a = S[state.lang] || S.zh; return a[k] != null ? a[k] : (S.zh[k] != null ? S.zh[k] : k); }
  function tf(k, m) { return String(t(k)).replace(/\{(\w+)\}/g, function (_, x) { return m && m[x] != null ? m[x] : ''; }); }

  /* ------------------------------------------------------------- helpers -- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function ls(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function ss(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  function fmtTime(ms) {
    var d = new Date(ms); if (isNaN(d)) return '';
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  var PH = {
    'chart-polar': 'ph-chart-polar', gauge: 'ph-gauge', bell: 'ph-bell', map: 'ph-map-trifold',
    ticket: 'ph-ticket', siren: 'ph-siren', clock: 'ph-clock', 'chart-line': 'ph-chart-line',
    link: 'ph-link', cpu: 'ph-cpu', broadcast: 'ph-broadcast', battery: 'ph-battery-charging',
    package: 'ph-package', wrench: 'ph-wrench', upload: 'ph-cloud-arrow-up', table: 'ph-table',
    archive: 'ph-archive', chat: 'ph-chat-circle-dots', book: 'ph-book-open-text', gear: 'ph-gear',
    dashboard: 'ph-squares-four', key: 'ph-lock-key', warning: 'ph-warning', briefcase: 'ph-briefcase',
    git: 'ph-git-pull-request', user: 'ph-user', flame: 'ph-fire', folder: 'ph-folder-open',
    'arrow-up-right': 'ph-arrow-up-right', 'shield': 'ph-shield-check', 'globe': 'ph-globe-hemisphere-west'
  };
  function ic(name) { return '<i class="ph ' + (PH[name] || PH.dashboard) + '" aria-hidden="true"></i>'; }

  /* ------------------------------------------------------------- layout -- */
  /* 三级层级的归属写在这里（数据里没有 tier 字段）。
     T0 = 左栏焦点区（CXO 用大卡、SP 用行式，两块叠在地图左边）；
     T1 = 主视图：一组一个页签，一次只展开一个面板，面板内是卡片流；
     T2 = 辅助：默认只显示 2 行。 */
  var T0 = ['CXO View', 'SP View'];
  var T1 = ['MS View', 'FLM View', 'FO View', 'BO View'];
  var T2 = ['Knowledge Q&A', 'Friends Link', 'System Admin'];
  var AUX_ROWS = 2;           /* 辅助分组默认露出的行数 */
  var OTHER = '__other';      /* 不属于任何已知分组的看板，在页签里单列一项 */
  var AUX_TITLES = {
    'Knowledge Q&A': 'aux.qa', 'Friends Link': 'aux.friends', 'System Admin': 'aux.admin'
  };
  var MAP_TABS = [
    { page: 'gis', key: 'map.gis', icon: 'map' },
    { page: 'mwRealTime', key: 'map.mw', icon: 'broadcast' },
    { page: 'realtime_alarm', key: 'map.alarm', icon: 'bell' },
    { page: 'packet_loss', key: 'map.loss', icon: 'link' }
  ];
  /* 与 MsPortal 同一份剥离样式：让同源 iframe 只留 Leaflet 画布，
     否则地图外面会套着该页面自己的筛选栏 / KPI 卡 / 侧栏。 */
  var MAP_STRIP_CSS = [
    'html,body{margin:0!important;padding:0!important;height:100%!important;overflow:hidden!important;background:transparent!important}',
    '#root,.ant-layout,.ant-layout-content{height:100%!important;min-height:0!important;margin:0!important;padding:0!important;background:transparent!important}',
    'main#main-content{height:100%!important;padding:0!important;margin:0!important;overflow:hidden!important}',
    'main#main-content > div{height:100%!important;padding:0!important;margin:0!important;display:block!important}',
    'main#main-content > div > *:not(:has(.leaflet-container)):not(:has(iframe)):not(iframe){display:none!important}',
    'main#main-content > div > iframe,main#main-content > div > *:has(iframe){width:100%!important;height:100%!important;border:0!important;display:block!important;margin:0!important;padding:0!important}',
    'main#main-content *:has(.leaflet-container){height:100%!important;min-height:0!important;max-height:none!important}',
    'main#main-content .ant-card:has(.leaflet-container){height:100%!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;background:transparent!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-head{display:none!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-body{height:100%!important;padding:0!important}',
    'main#main-content .ant-card-body:has(.leaflet-container){position:relative!important}',
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
    '.leaflet-container{height:100%!important;min-height:0!important;max-height:none!important;width:100%!important;border-radius:0!important}'
  ].join('');

  /* -------------------------------------------------------------- state -- */
  var state = {
    lang: ls('olbr.lang', 'zh') === 'en' ? 'en' : 'zh',
    theme: root.classList.contains('dark') ? 'dark' : 'light',
    q: '', group: 'all', status: 'all',
    user: null, authOk: false, booted: false,
    items: (D.items || []).slice(), groups: (D.groups || []).slice(), order: {},
    qc: { loading: true, err: '', at: 0, m: {} },
    escOpen: false, escLv: 'LEVEL1',
    auxOpen: {},
    mapTab: ls('olbr.maptab', 'gis'),
    viewTab: ls('olbr.viewtab', ''),
    drill: { metric: '', title: '', q: '', page: 1, size: 25, rows: [], columns: [], total: 0, loading: false, err: '' }
  };

  /* ---------------------------------------------------------- catalog -- */
  var ITEMS = [];
  function setCatalog(items) { ITEMS = items || []; }
  setCatalog(state.items);

  function inGroup(it, gid) { return (it.groups || []).indexOf(gid) !== -1; }
  function canSee(it) { try { return ACC.canSee(state.user, it); } catch (e) { return true; } }
  function allowed() { return ITEMS.filter(canSee); }

  function orderIdx(gid) { var a = state.order[gid]; return Array.isArray(a) ? a : null; }
  function sorter(gid) {
    var seq = orderIdx(gid);
    return function (a, b) {
      if (seq) {
        var ia = seq.indexOf(a.no), ib = seq.indexOf(b.no);
        if (ia !== -1 || ib !== -1) return ia === -1 ? 1 : ib === -1 ? -1 : ia - ib;
      }
      return (b.clicks || 0) - (a.clicks || 0) || (a.no || 0) - (b.no || 0);
    };
  }

  /* 搜索：多词 AND，命中集覆盖标题 / 描述 / 责任人 / 部门 / 标签 / 平台。 */
  function tokens() {
    return String(state.q || '').toLowerCase().split(/\s+/).filter(Boolean);
  }
  function hay(it) {
    return [it.titleZh, it.titleEn, it.descZh, it.descEn, it.owner, it.ownerEn, it.dept, it.deptEn,
      (it.tags || []).join(' '), it.platform, it.platformZh, it.status, it.freq]
      .filter(Boolean).join(' ').toLowerCase();
  }
  function match(it, tk) { if (!tk.length) return true; var h = hay(it); return tk.every(function (x) { return h.indexOf(x) !== -1; }); }
  function filtered(gid) {
    var tk = tokens();
    return allowed().filter(function (it) {
      if (gid && !inGroup(it, gid)) return false;
      if (state.group !== 'all' && !inGroup(it, state.group)) return false;
      if (state.status !== 'all' && it.status !== state.status) return false;
      return match(it, tk);
    }).sort(sorter(gid || ''));
  }
  function filtering() { return !!tokens().length || state.group !== 'all' || state.status !== 'all'; }
  function knownGids() {
    var seen = {}; state.groups.forEach(function (g) { seen[g.id] = 1; });
    T0.concat(T1, T2).forEach(function (g) { seen[g] = 1; });
    return Object.keys(seen);
  }
  function groupsOf(it) { return it.groups || []; }
  function primaryGroup(it) {
    var g = groupsOf(it); if (!g.length) return '';
    var all = T0.concat(T1, T2);
    for (var i = 0; i < all.length; i++) if (g.indexOf(all[i]) !== -1) return all[i];
    return g[0];
  }

  /* -------------------------------------------------------------- labels -- */
  function gName(id) {
    var g = state.groups.filter(function (x) { return x.id === id; })[0];
    if (g) return state.lang === 'en' ? (g.en || g.id) : (g.zh || g.id);
    return id;
  }
  function gSub(id) {
    var g = state.groups.filter(function (x) { return x.id === id; })[0];
    if (!g) return '';
    return state.lang === 'en' ? (g.subEn || '') : (g.subZh || '');
  }
  /* titleOf/descOf 返回**原文**，转义只发生在写进 HTML 的那一刻：
     这里再 esc() 会和 hl()/esc() 叠成 &amp;amp;，页面上就露出 &amp; 这种字面实体。 */
  function titleOf(it) { return (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) || '#' + it.no; }
  function descOf(it) { return state.lang === 'en' ? (it.descEn || it.descZh || '') : (it.descZh || it.descEn || ''); }
  function ownerOf(it) { return state.lang === 'en' ? (it.ownerEn || it.owner) : (it.owner || it.ownerEn); }
  function pfOf(it) { return t('pf.' + it.platform) || it.platform; }
  function stOf(it) { return it.status === 'beta' ? t('st.beta') : t('st.online'); }
  function vlink(it, gid) {
    return '/MsPortal/viewer.html?no=' + encodeURIComponent(it.no) +
      '&gid=' + encodeURIComponent(gid || primaryGroup(it) || '');
  }
  /* 高亮命中词。必须**单趟**扫描 + 分段转义，不能「先 esc 再逐词 replace」：
       · 逐词链式 replace 会让第 2 个词命中第 1 个词刚注入的 <span class="hit">
         （搜 "hit" 就把自己套进去，属性直接被打断）；
       · 反过来先 esc 再替换，命中的可能是 &amp; 里的 "amp" 这种实体残片。
     所以：在原文上用一个合并后的 alternation 正则走一遍，
     每段原文各自 esc()，注入的标签只在两个安全片段之间。 */
  function hl(s) {
    var raw = String(s == null ? '' : s);
    var tk = tokens();
    if (!tk.length) return esc(raw);
    var re = new RegExp('(' + tk.map(function (x) {
      return x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('|') + ')', 'ig');
    var out = '', last = 0, m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index === last && m[0] === '') { re.lastIndex++; continue; }
      out += esc(raw.slice(last, m.index)) + '<span class="hit">' + esc(m[0]) + '</span>';
      last = m.index + m[0].length;
    }
    return out + esc(raw.slice(last));
  }

  /* --------------------------------------------------------------- cards -- */
  function metaHtml(it) {
    var bits = [];
    bits.push('<span class="st st-' + (it.status === 'beta' ? 'beta' : 'online') + '">' + stOf(it) + '</span>');
    bits.push('<span class="pf">' + esc(pfOf(it)) + '</span>');
    if (it.freq) bits.push('<span>' + esc(it.freq) + '</span>');
    var ow = ownerOf(it); if (ow) bits.push('<span class="ow">' + esc(ow) + '</span>');
    return '<span class="meta">' + bits.join('<span class="dot">·</span>') + '</span>';
  }
  /* 条目卡：卡片流 —— 一行放得下几张就几张，排满自动折到下一行。
     说明在卡里最多两行，全文留在 title 提示里。 */
  function itemCard(it, gid) {
    return '<a class="card" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" ' +
      'title="' + esc(descOf(it)) + '" data-no="' + esc(it.no) + '">' +
      '<span class="c-ico">' + ic(it.icon) + '</span>' +
      '<span class="c-bd"><span class="c-t">' + hl(titleOf(it)) + '</span>' +
      '<span class="c-d">' + hl(descOf(it)) + '</span>' + metaHtml(it) + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }
  function focusCard(it, gid) {
    return '<a class="fcard" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" data-no="' + it.no + '">' +
      '<span class="ic-ico">' + ic(it.icon) + '</span>' +
      '<span class="ic-bd"><span class="ttl">' + hl(titleOf(it)) + '</span>' +
      '<span class="dsc">' + hl(descOf(it)) + '</span>' + metaHtml(it) + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }

  /* -------------------------------------------------------------- render -- */
  function panelHead(gid, extraTools) {
    var n = filtered(gid).length;
    return '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(gName(gid)) + '</span>' +
      '<span class="p-s">' + esc(gSub(gid)) + '</span></span>' +
      '<span class="cnt">' + n + '</span>' +
      (extraTools || '') +
      '<a class="p-x" href="/MsPortal/viewer.html?gid=' + encodeURIComponent(gid) +
      '" target="_blank" rel="noopener noreferrer">' + t('v.open') + ' <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a></div>';
  }

  function renderRail() {
    var all = allowed(), tk = tokens(), box = $('#chips');
    var mk = function (id, label, n, on) {
      return '<button type="button" class="chip" data-gid="' + esc(id) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
        esc(label) + '<small>' + n + '</small></button>';
    };
    var html = mk('all', t('rail.all'), all.filter(function (it) { return match(it, tk) && (state.status === 'all' || it.status === state.status); }).length, state.group === 'all');
    state.groups.forEach(function (g) {
      var n = filtered(g.id).length;
      if (!n && filtering()) return;                       /* 筛选中且不命中的分组直接从 chips 里退场 */
      html += mk(g.id, gName(g.id), n, state.group === g.id);
    });
    box.innerHTML = html;
    $$('.seg-b[data-status]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-status') === state.status ? 'true' : 'false');
    });
    var hit = all.filter(function (it) {
      return match(it, tk) && (state.status === 'all' || it.status === state.status) &&
        (state.group === 'all' || inGroup(it, state.group));
    }).length;
    $('#count').innerHTML = filtering()
      ? '<b>' + hit + '</b> / ' + all.length + ' ' + esc(state.lang === 'en' ? 'match' : '命中')
      : '<b>' + all.length + '</b> ' + esc(t('rail.all')) + ' · ' + state.groups.length + ' ' + esc(state.lang === 'en' ? 'groups' : '个分组');
    $('#clearBtn').hidden = !filtering();
    $('#rail').classList.toggle('is-filtered', filtering());
  }

  function renderBand() {
    var box = $('#band'), q = state.qc;
    if (q.loading) {
      box.innerHTML = '<div class="band-l"><span class="sk" style="width:96px;height:96px;border-radius:50%"></span>' +
        '<div class="band-txt" style="flex:1"><span class="sk" style="width:52%"></span>' +
        '<span class="sk s" style="width:72%"></span><span class="sk s" style="width:40%"></span></div></div>' +
        '<div class="metrics">' + (D.qc || []).map(function () {
          return '<div class="metric"><span class="sk" style="width:56%"></span><span class="sk v"></span><span class="sk s"></span></div>';
        }).join('') + '</div>';
      return;
    }
    if (q.err) {
      /* 上一版这里直接显示「—」，六个格子全是破折号，读起来像系统坏了 */
      box.innerHTML = '<div class="band-l"><div class="band-txt"><div class="band-k">' + esc(t('qc.title')) +
        '</div><p class="band-n" style="color:var(--crit)">' + esc(tf('qc.err', { e: q.err })) + '</p></div></div>' +
        '<div class="metrics" style="align-content:center"><button class="gb" data-act="qc-retry">' +
        esc(t('qc.retry')) + '</button></div>';
      return;
    }
    var m = q.m, sla = m.sla || {}, defs = D.qc || [];
    var pct = sla.value == null ? 0 : Math.max(0, Math.min(100, +sla.value));
    var tone = function (id, v) {
      if (id === 'alarm') return v > 0 ? 'crit' : 'ok';
      return '';
    };
    var sub = function (id) {
      var x = m[id] || {};
      if (id === 'alarm') return (x.sites != null ? x.sites + ' ' + esc(state.lang === 'en' ? 'sites down' : '断站站点') : '');
      if (id === 'pmt') return x.overdue != null ? (state.lang === 'en' ? 'overdue ' : '超期 ') + x.overdue : '';
      if (id === 'spms' && x.tables) return Object.keys(x.tables).map(function (k) { return k + ' ' + x.tables[k]; }).join(' · ');
      return '';
    };
    box.innerHTML =
      '<div class="band-l"><div class="ring" style="--v:' + pct + '"><b>' + (sla.value == null ? '—' : pct.toFixed(1) + '%') + '</b></div>' +
      '<div class="band-txt"><div class="band-k">' + esc(t('qc.sla')) + '</div>' +
      '<p class="band-n">' + esc(t('qc.title')) + ' · <em>' + (sla.pass || 0) + '</em> / <em>' + (sla.total || 0) + '</em></p>' +
      '<p class="band-when">' + esc(tf('qc.when', { t: q.at ? fmtTime(q.at).slice(11) : '--:--:--' })) + '</p></div></div>' +
      '<div class="metrics">' + defs.map(function (d) {
        var v = m[d.id] && m[d.id].value, err = m[d.id] && m[d.id].error;
        var tn = err ? 'err' : tone(d.id, v);
        return '<button type="button" class="metric" data-qc="' + esc(d.id) + '" data-tone="' + tn + '" ' +
          'title="' + esc(tf('qc.drill')) + ' · ' + esc(state.lang === 'en' ? d.subEn : d.subZh) + '">' +
          '<span class="metric-k">' + ic(d.icon) + esc(state.lang === 'en' ? d.en : d.zh) + '</span>' +
          '<span class="metric-v">' + (err ? esc(state.lang === 'en' ? 'n/a' : '不可用') : (v == null ? '—' : Number(v).toLocaleString('en-US'))) + '</span>' +
          '<span class="metric-s">' + (sub(d.id) || esc(state.lang === 'en' ? d.subEn : d.subZh)) + '</span>' +
          '<span class="metric-tick"></span></button>';
      }).join('') + '</div>';
  }

  function renderL0() {
    var box = $('#l0');
    var maps = mapItems();
    var cxo = filtered('CXO View'), sp = filtered('SP View');
    /* 左栏：CXO 焦点卡在上、SP View 行式清单在下（按需求放在 CXO 下面），
       两块一起和右边的地图并排；窄到 1240 以下时地图整宽换行。 */
    var side = '';
    if (cxo.length || !filtering()) {
      side += '<section class="panel" data-tier="0" data-gid="CXO View" aria-label="CXO View">' +
        panelHead('CXO View') +
        (cxo.length ? cxo.map(function (it) { return focusCard(it, 'CXO View'); }).join('')
          : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') + '</section>';
    }
    if (sp.length || !filtering()) {
      side += '<section class="panel" data-tier="0" data-gid="SP View" aria-label="SP View">' +
        panelHead('SP View') +
        (sp.length ? '<div class="cards">' + sp.map(function (it) { return itemCard(it, 'SP View'); }).join('') + '</div>'
          : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') + '</section>';
    }
    var html = side ? '<div class="l0-col">' + side + '</div>' : '';
    if (maps.length) {
      html += '<section class="panel map" data-tier="0" aria-label="Topology">' +
        '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(t('map.title')) + '</span>' +
        '<span class="p-s">' + esc(t('map.sub')) + '</span></span>' +
        '<div class="map-tabs"><div class="tabs" role="tablist">' + maps.map(function (m) {
          return '<button type="button" class="tab" role="tab" data-map="' + esc(m.page) + '" aria-selected="' +
            (m.page === state.mapTab ? 'true' : 'false') + '">' + ic(m.icon) + esc(t(m.key)) + '</button>';
        }).join('') + '</div>' +
        '<button type="button" class="gb gb--t" data-act="map-reload" title="' + esc(t('map.reload')) + '"><i class="ph ph-arrow-clockwise"></i><span>' + esc(t('map.reload')) + '</span></button>' +
        '<a class="gb gb--t" id="mapOpen" href="' + esc(curMap().src) + '" target="_blank" rel="noopener noreferrer" title="' + esc(t('map.open')) + '"><i class="ph ph-arrow-square-out"></i><span>' + esc(t('map.open')) + '</span></a>' +
        '</div></div>' +
        '<div class="canvas"><iframe id="mapFrame" title="' + esc(t('map.title')) + '" src="' + esc(curMap().src) + '"></iframe>' +
        '<div class="canvas-note"><span>' + esc(curMap().title) + '</span>' +
        '<span>/myapp/?page=' + esc(curMap().page) + '</span></div></div></section>';
    }
    box.innerHTML = html;
    wireMap();
  }

  function mapItems() {
    var all = allowed();
    return MAP_TABS.map(function (m) {
      var it = all.filter(function (x) { return String(x.url || '').indexOf('page=' + m.page) !== -1; })[0];
      return {
        page: m.page, key: m.key, icon: m.icon, item: it,
        title: it ? (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) : m.page,
        src: '/myapp/?page=' + m.page + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : '')
      };
    }).filter(function (m) { return !!m.item; });
  }
  function curMap() {
    var ms = mapItems();
    return ms.filter(function (m) { return m.page === state.mapTab; })[0] || ms[0] || { page: '', src: 'about:blank', title: '' };
  }

  /* L1 主视图改成页签：一次只展开一个分组。四个面板全叠着时，光 BO View 的 16 张卡
     就能把页面拖到三千多 px；页签条沿用顶部筛选 chip 的胶囊样式，但语义是 tab。
     空分组不进页签（没有可看内容的页签只是噪声），全空才出「无匹配」占位。 */
  function renderViews() {
    var box = $('#views');
    var tabs = T1.map(function (gid) { return { id: gid, label: gName(gid), list: filtered(gid) }; });
    var others = allowed().filter(function (it) {
      return !T0.concat(T1, T2).some(function (g) { return inGroup(it, g); }) &&
        (state.group === 'all' || inGroup(it, state.group)) && match(it, tokens()) &&
        (state.status === 'all' || it.status === state.status);
    });
    if (others.length) tabs.push({ id: OTHER, label: state.lang === 'en' ? 'Other dashboards' : '其他看板', list: others });
    tabs = tabs.filter(function (x) { return x.list.length; });
    if (!tabs.length) {
      box.innerHTML = '<div class="panel empty"><b>' + esc(t('v.emptyFilter')) + '</b> — ' + esc(t('v.adjust')) + '</div>';
      return;
    }
    var cur = tabs.some(function (x) { return x.id === state.viewTab; }) ? state.viewTab : tabs[0].id;
    state.viewTab = cur; ss('olbr.viewtab', cur);
    var act = tabs.filter(function (x) { return x.id === cur; })[0];
    /* 「其他看板」不是数据里真实存在的分组名，往下传会拼出 gid=__other 的死链接，
       传空串让 vlink 回退到条目自己的主分组。 */
    var gid = cur === OTHER ? '' : cur;
    var head = cur === OTHER
      ? '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(act.label) + '</span></span>' +
        '<span class="cnt">' + act.list.length + '</span></div>'
      : panelHead(cur);
    box.innerHTML =
      '<div class="view-1"><div class="tabs-v" role="tablist">' + tabs.map(function (x) {
        return '<button type="button" class="tabv" role="tab" data-view="' + esc(x.id) +
          '" aria-selected="' + (x.id === cur ? 'true' : 'false') + '">' + esc(x.label) +
          '<small>' + x.list.length + '</small></button>';
      }).join('') + '</div>' +
      '<section class="panel" data-tier="1" data-gid="' + esc(gid) + '" aria-label="' + esc(act.label) + '">' +
      head + '<div class="cards">' + act.list.map(function (it) { return itemCard(it, gid); }).join('') +
      '</div></section></div>';
  }

  /* 辅助区分组标题：默认只露 AUX_ROWS 行，多出来的靠「展开 / 收起」按钮。
     收缩用 CSS 隐藏第 3 条起的 li（而不是 max-height），避免半行被裁一半。 */
  function auxHead(key, label, n) {
    var open = !!state.auxOpen[key], cut = n > AUX_ROWS;
    return '<h3 class="aux-h"><span class="aux-n">' + esc(label) + '</span><span class="cnt">' + n + '</span>' +
      (cut ? '<button type="button" class="aux-x" data-act="aux-toggle" data-key="' + esc(key) +
        '" aria-expanded="' + (open ? 'true' : 'false') + '"><i class="ph ph-' + (open ? 'caret-up' : 'caret-down') +
        '" aria-hidden="true"></i><span>' + esc(open ? t('aux.less') : tf('aux.more', { n: n - AUX_ROWS })) +
        '</span></button>' : '') + '</h3>';
  }
  function auxRow(it, gid) {
    return '<li><a class="lrow" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer">' +
      ic(it.icon) + '<span>' + hl(titleOf(it)) + '</span>' +
      (it.status === 'beta' ? '<em>' + esc(stOf(it)) + '</em>' : '') +
      '<i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>';
  }
  function renderAux() {
    var box = $('#aux'), html = '';
    T2.forEach(function (gid) {
      var list = filtered(gid);
      if (!list.length && filtering()) return;
      html += '<div class="aux-g" data-key="' + esc(gid) + '" data-open="' + (state.auxOpen[gid] ? '1' : '0') + '">' +
        auxHead(gid, t(AUX_TITLES[gid] || gid), list.length) + '<ul>' +
        (list.length ? list.map(function (it) { return auxRow(it, gid); }).join('')
          : '<li><span class="lrow">' + esc(t('v.empty')) + '</span></li>') + '</ul></div>';
    });
    var tools = '<li><a class="lrow" href="/MsPortal/">' + ic('wrench') + '<span>' + esc(t('aux.ms')) + '</span><i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>' +
      '<li><a class="lrow" href="/uniplam/">' + ic('globe') + '<span>' + esc(t('aux.uni')) + '</span><i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>';
    html += '<div class="aux-g" data-key="_tools" data-open="1">' + auxHead('_tools', t('aux.tools'), 2) + '<ul>' + tools + '</ul></div>';
    box.innerHTML = html;
  }

  function renderEsc() {
    var box = $('#esc'), E = D.escalation || {}, rows = E.rows || [], lv = E.levels || [];
    if (!rows.length) { box.hidden = true; return; }
    var cnt = {}; rows.forEach(function (r) { cnt[r.level] = (cnt[r.level] || 0) + 1; });
    var html = '<div class="esc-bar"><span class="esc-t">' + esc(t('esc.title')) + '</span>' +
      '<span class="esc-s">' + esc(tf('esc.count', { n: rows.length, lv: lv.length })) + ' · ' + esc(t('esc.sub')) + '</span>' +
      '<span class="esc-lv">' + lv.map(function (l) {
        return '<button type="button" class="lvchip" data-lv="' + esc(l.id) + '" data-now="' + (l.id === state.escLv ? '1' : '0') + '">' +
          esc(l.id.replace('LEVEL', 'L')) + ' <b>' + (cnt[l.id] || 0) + '</b></button>';
      }).join('') +
      '<button type="button" class="gb" data-act="esc-toggle"><i class="ph ph-' + (state.escOpen ? 'caret-up' : 'caret-down') + '"></i>' +
      esc(state.escOpen ? t('esc.collapse') : tf('esc.expand', { n: rows.length })) + '</button></span></div>';
    if (state.escOpen) {
      var show = rows.filter(function (r) { return !state.escLv || r.level === state.escLv; });
      html += '<div class="esc-body"><div class="esc-scroll"><table class="grid"><thead><tr>' +
        '<th>' + esc(t('esc.lv')) + '</th><th>' + esc(t('esc.pos')) + '</th><th>' + esc(t('esc.name')) + '</th>' +
        '<th class="num">Orange</th><th class="num">LONESTAR</th><th>' + esc(t('esc.mail')) + '</th></tr></thead><tbody>' +
        show.map(function (r) {
          return '<tr><td class="lv">' + esc(String(r.level || '').replace('LEVEL', 'L')) + '</td>' +
            '<td>' + esc(r.position || '—') + '</td><td>' + esc(r.name || '—') + '</td>' +
            '<td class="num">' + esc(r.orange || '—') + '</td><td class="num">' + esc(r.lonestar || '—') + '</td>' +
            '<td>' + (r.email ? '<a href="mailto:' + esc(r.email) + '">' + esc(r.email) + '</a>' : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="esc-note">' + esc(t('esc.src')) + ' · ' + esc((lv.filter(function (l) { return l.id === state.escLv; })[0] || {}).zh || '') +
        ' <button type="button" class="gb" data-act="esc-copy" style="margin-left:8px"><i class="ph ph-copy"></i>' + esc(t('esc.copy')) + '</button></p></div>';
    }
    box.innerHTML = html;
  }

  function render() { renderRail(); renderBand(); renderL0(); renderEsc(); renderViews(); renderAux(); applyI18n(); }

  /* --------------------------------------------------------------- auth -- */
  /* 与 MsPortal 共用 PORTAL_TOKEN_KEY：新页面登录不会把 MsPortal 顶掉（同一份会话），
     而查看器 /MsPortal/viewer.html 又必须读得到这个键，所以不复用就会把打开动作搞挂。 */
  var TOKEN_KEY = 'liberia_noc_auth_v1';
  function tok() { return ls(TOKEN_KEY, null); }

  /* 两个端点返回的主体不一样，取用顺序照 MsPortal 的 probeSession()：
       · /uniplam/api/auth/me  —— 真正的门户账号，**带 role / allowedGroups / allowedCards**，
         权限判定只认这一份；
       · /api/auth/me          —— my_app 的会话身份（本机回环是占位的 {username:'local'}），
         没有权限字段，只用来认「登没登录」和显示用户名。
     两者都是 {user:{…}} 信封，必须剥 .user —— 早先直接存了信封，
     结果 #whoBadge 取 u.username 永远为空，徽标和退出按钮都不出现。 */
  function probe() {
    var unwrap = function (j) { return j && j.user ? j.user : null; };
    var p1 = fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; }).then(unwrap).catch(function () { return null; });
    var tk = tok();
    var p2 = tk ? fetch('/uniplam/api/auth/me', {
      credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
    }).then(function (r) { return r.ok ? r.json() : null; }).then(unwrap).catch(function () { return null; }) : Promise.resolve(null);
    return Promise.all([p1, p2]).then(function (a) {
      state.user = a[1] || a[0] || null;
      state.authOk = !!state.user;
      renderWho();
    });
  }
  function renderWho() {
    var b = $('#whoBadge'), o = $('#logoutBtn'), u = state.user;
    var n = u && (u.username || u.id || u.name);
    if (b) { b.hidden = !n; b.textContent = n || ''; }
    if (o) o.hidden = !state.authOk;
  }
  function renderGate() {
    var box = $('#gate');
    if (state.authOk) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<div class="gate"><div class="gate-c"><h2>' + esc(t('gate.title')) + '</h2>' +
      '<p>' + esc(t('gate.sub')) + '</p><form id="lf">' +
      '<label class="fld"><span>' + esc(t('gate.user')) + '</span><input id="lu" autocomplete="username" required></label>' +
      '<label class="fld"><span>' + esc(t('gate.pass')) + '</span><input id="lp" type="password" autocomplete="current-password" required></label>' +
      '<div class="gate-err" id="le" hidden></div>' +
      '<div class="gate-ft"><a class="btn" href="/MsPortal/">' + esc(t('mast.admin')) + '</a>' +
      '<button class="btn primary" type="submit" id="lgo">' + esc(t('gate.go')) + '</button></div></form></div></div>';
    mainLocked(true);
  }
  function mainLocked(on) {
    ['#band', '#l0', '#esc', '#views', '#aux'].forEach(function (s) { var e = $(s); if (e) e.hidden = on; });
    var r = $('#rail'); if (r) r.style.display = on ? 'none' : '';
  }
  function login(u, p) {
    return fetch('/uniplam/api/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok || !d.token || !d.user) { var e = new Error(d.detail || 'login failed'); e.code = r.status === 429 ? 'locked' : r.status === 401 ? 'bad' : 'net'; throw e; }
        ss(TOKEN_KEY, d.token);
        state.user = d.user; state.authOk = true;
        return fetch('/api/auth/portal-login', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ token: d.token })
        }).catch(function () {});
      });
    });
  }
  function logout() {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
    var tk = tok();
    if (tk) fetch('/uniplam/api/auth/logout', {
      method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tk }
    }).catch(function () {});
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    state.user = null; state.authOk = false; renderGate(); renderWho();
  }

  /* ---------------------------------------------------------------- QC -- */
  function api(u) {
    return fetch(u, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      if (!r.ok) throw new Error('HTTP ' + r.status);
      /* my_app 的 catch-all 会把未注册的 /api/* 也回成 SPA 的 index.html（200 + text/html） */
      if (ct.indexOf('json') === -1) throw new Error('non-JSON');
      return r.json();
    });
  }
  function loadQc() {
    api('/api/portal-qc/summary').then(function (d) {
      state.qc = { loading: false, err: '', at: d.generated_at ? new Date(d.generated_at).getTime() : Date.now(), m: d.metrics || {} };
      renderBand();
    }).catch(function (e) {
      state.qc = { loading: false, err: (e && e.message) || String(e), at: 0, m: {} };
      renderBand();
    });
  }
  function openDrill(id) {
    var def = (D.qc || []).filter(function (x) { return x.id === id; })[0];
    if (!def) return;
    state.drill = { metric: id, title: state.lang === 'en' ? def.en : def.zh, q: '', page: 1, size: 25, rows: [], columns: [], total: 0, loading: true, err: '' };
    var d = $('#drawer');
    d.hidden = false; $('#scrim').hidden = false;
    /* 用一次强制重排而不是 requestAnimationFrame 来做「unhide → 加类」的帧间隔：
       页面在后台时 rAF 根本不会回调，抽屉就永远停在关上的位置。 */
    void d.offsetWidth;
    d.classList.add('open');
    $('#drQ').value = '';
    fetchDrill();
  }
  function closeDrill() {
    $('.drawer').classList.remove('open');
    state.drill.metric = '';
    window.setTimeout(function () { $('#drawer').hidden = true; $('#scrim').hidden = true; }, 220);
  }
  var drillSeq = 0;
  function fetchDrill() {
    var d = state.drill; if (!d.metric) return;
    var seq = ++drillSeq;
    d.loading = true; d.err = ''; renderDrill();
    api('/api/portal-qc/detail?metric=' + encodeURIComponent(d.metric) + '&page=' + d.page + '&size=' + d.size +
      (d.q ? '&q=' + encodeURIComponent(d.q) : ''))
      .then(function (r) {
        if (seq !== drillSeq) return;
        d.loading = false; d.total = r.total || 0; d.rows = r.rows || []; d.columns = r.columns || [];
        renderDrill();
      })
      .catch(function (e) { if (seq !== drillSeq) return; d.loading = false; d.err = (e && e.message) || String(e); renderDrill(); });
  }
  function cell(k, v) {
    if (v == null || v === '') return '—';
    if (/^(raised|closed|update|created)/i.test(k) && typeof v === 'number') return esc(fmtTime(v).slice(5));
    if (typeof v === 'number') return esc(v % 1 ? v.toFixed(1) : v.toLocaleString('en-US'));
    return esc(v);
  }
  function renderDrill() {
    var d = state.drill, box = $('#drBody');
    $('#drTitle').textContent = d.title || t('dr.title');
    $('#drSub').textContent = t('qc.sub');
    $('#drCount').textContent = d.loading ? '…' : tf('dr.rows', { n: d.total });
    $('#drPage').textContent = tf('dr.page', { p: d.page, q: Math.max(1, Math.ceil(d.total / d.size)) });
    $('#drPrev').disabled = d.page <= 1; $('#drNext').disabled = d.page * d.size >= d.total;
    if (d.loading) { box.innerHTML = '<div class="dr-empty">' + esc(t('dr.load')) + '</div>'; return; }
    if (d.err) { box.innerHTML = '<div class="dr-empty" style="color:var(--crit)">' + esc(tf('dr.err', { e: d.err })) + '</div>'; return; }
    if (!d.rows.length) { box.innerHTML = '<div class="dr-empty">' + esc(t('dr.empty')) + '</div>'; return; }
    box.innerHTML = '<table class="grid"><thead><tr>' + d.columns.map(function (c) {
      return '<th' + (typeof d.rows[0][c.key] === 'number' ? ' class="num"' : '') + '>' + esc(c.label || c.key) + '</th>';
    }).join('') + '</tr></thead><tbody>' + d.rows.map(function (r) {
      return '<tr>' + d.columns.map(function (c) {
        return '<td' + (typeof r[c.key] === 'number' ? ' class="num"' : '') + '>' + cell(c.key, r[c.key]) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</tbody></table>';
  }

  /* ---------------------------------------------------------- map embed -- */
  /* 下面这一段（keepOnlyMap / invalidateLeaflet / refitLeaflet / stripFrame）
     是从 MsPortal/assets/portal.js 的同名实现**逐字搬过来**的，不是重写：
     地图页（尤其 mwRealTime）的内层结构不归本页面管，那套剥离 + 重算尺寸 +
     重新取景的时序是 MsPortal 实测踩出来的（容器高度从 88px 被 CSS 拉到 378px 后
     Leaflet 内部 _size 仍是旧值 → tile 按旧尺寸铺出去再被 overflow:hidden 裁掉，
     表现就是「地图只露一小块、还不在正中」）。
     不改成 import 共用是因为：那是 portal.js 的私有函数、没有导出，
     而 portal.js 一加载就会把整个 MsPortal 首页跑起来 —— 只读版不能引它。
     两份若要改动，请同时改，别只改一边。 */
  function wireMap() {
    var f = $('#mapFrame'); if (!f) return;
    var go = function () { tellEmbed(f, 0); stripFrame(f, 0); };
    f.addEventListener('load', go);
    go();
    window.setTimeout(go, 1400); window.setTimeout(go, 3400);
  }
  function tellEmbed(f, depth) {
    try {
      if (f.contentWindow) {
        f.contentWindow.postMessage({ __type: 'msportal-embed', theme: state.theme, depth: depth || 0 }, '*');
      }
    } catch (e) { /* 跨域静默 */ }
  }
  /* 内层纯静态页（mw_real_time.html）：从 Leaflet 画布逐层向上把兄弟节点整块藏掉。
     这里只能用内联样式 —— 它是静态页，没有 React 会重渲染把 style 覆盖回去。 */
  function keepOnlyMap(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var chain = [], node = lc;
    while (node && node !== doc.body && node.parentElement) {
      chain.push(node);
      var parent = node.parentElement;
      Array.prototype.forEach.call(parent.children, function (sib) {
        if (sib === node) return;
        var tag = sib.tagName;
        if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'LINK') return;
        sib.style.setProperty('display', 'none', 'important');
      });
      node = parent;
    }
    [doc.documentElement, doc.body].forEach(function (el) {
      if (!el) return;
      el.style.setProperty('margin', '0', 'important');
      el.style.setProperty('padding', '0', 'important');
      el.style.setProperty('height', '100%', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
    });
    chain.forEach(function (el) {
      ['height', 'width'].forEach(function (p) { el.style.setProperty(p, '100%', 'important'); });
      el.style.setProperty('min-height', '0', 'important');
      el.style.setProperty('max-height', 'none', 'important');
      el.style.setProperty('margin', '0', 'important');
      el.style.setProperty('padding', '0', 'important');
    });
    lc.style.setProperty('height', '100%', 'important');
    lc.style.setProperty('min-height', '0', 'important');
    lc.style.setProperty('width', '100%', 'important');
    try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e) { /* ignore */ }
    return true;
  }
  function invalidateLeaflet(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var map = null;
    ['_leaflet_map', '__leaflet_map', '_map', 'map'].forEach(function (k) {
      if (!map && lc[k] && typeof lc[k].invalidateSize === 'function') map = lc[k];
    });
    if (!map) {
      try {
        var fk = Object.keys(lc).filter(function (k) { return k.indexOf('__reactFiber') === 0; })[0];
        if (fk) {
          var seen = new Set(), stack = [lc[fk]], guard = 0;
          while (stack.length && guard++ < 4000) {
            var n = stack.pop();
            if (!n || seen.has(n)) continue;
            seen.add(n);
            if (n.stateNode && typeof n.stateNode.invalidateSize === 'function') { map = n.stateNode; break; }
            var mp = n.memoizedProps || n.pendingProps;
            if (mp) {
              for (var key in mp) {
                var v = mp[key];
                if (v && typeof v === 'object' && typeof v.invalidateSize === 'function') { map = v; break; }
              }
              if (map) break;
            }
            if (n.child) stack.push(n.child);
            if (n.sibling) stack.push(n.sibling);
          }
        }
      } catch (e) { /* ignore */ }
    }
    if (map) {
      try {
        map.invalidateSize(false);
        setTimeout(function () { try { map.invalidateSize(false); } catch (e) {} }, 300);
        return true;
      } catch (e) { /* 落到路 3 */ }
    }
    try {
      lc.style.setProperty('height', 'calc(100% - 1px)', 'important');
      doc.defaultView.requestAnimationFrame(function () {
        lc.style.setProperty('height', '100%', 'important');
        try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e) {}
      });
    } catch (e) {
      try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e2) {}
    }
    return false;
  }
  /* 只有暴露了 fitAllSites 的内层页（当前是 mw_real_time.html）需要重新取景：
     fitBounds 跑在容器还矮的时刻，zoom 会低一级。容器高度每落定一次就重跑一次，
     直到约 12s 的观察窗口结束 —— 中途存在「前 strip 的假稳态」，只做一次会被骗。 */
  function refitLeaflet(d) {
    var w = d.defaultView;
    if (!w || typeof w.fitAllSites !== 'function') return false;
    if (d.__olbrRefitState) return false;
    var st = d.__olbrRefitState = { lastH: -1, tries: 0, timer: null };
    var apply = function () {
      st.timer = null;
      var lc = d.querySelector('.leaflet-container');
      if (!lc) return;
      var h = Math.round(lc.getBoundingClientRect().height);
      if (h <= 0 || h !== st.lastH) return;
      try { w.fitAllSites(); } catch (e) { /* 内层页自己会兜底 */ }
    };
    (function tick() {
      var lc = d.querySelector('.leaflet-container');
      if (lc) {
        var h = Math.round(lc.getBoundingClientRect().height);
        if (h > 0 && h !== st.lastH) {
          st.lastH = h;
          if (st.timer) clearTimeout(st.timer);
          st.timer = setTimeout(apply, 500);
        }
      }
      if (st.tries++ < 40) setTimeout(tick, 300);
    })();
    return true;
  }
  function stripFrame(f, depth) {
    depth = depth || 0;
    try {
      var d = f.contentDocument;
      if (!d || !d.head) return;
      var s = d.getElementById('olbrStrip');
      if (!s) { s = d.createElement('style'); s.id = 'olbrStrip'; d.head.appendChild(s); }
      if (s.textContent !== MAP_STRIP_CSS) s.textContent = MAP_STRIP_CSS;

      if (d.querySelector('.leaflet-container')) {
        if (depth > 0) keepOnlyMap(d);
        invalidateLeaflet(d);
        refitLeaflet(d);
        setTimeout(function () { invalidateLeaflet(d); }, 400);
        setTimeout(function () { invalidateLeaflet(d); }, 1200);
        return;
      }
      if (depth >= 2) return;
      Array.prototype.forEach.call(d.querySelectorAll('iframe'), function (inner) {
        var go = function () {
          tellEmbed(inner, depth + 1);
          stripFrame(inner, depth + 1);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 1200);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 3200);
        };
        if (inner.dataset.olbrStripped === '1') { go(); return; }
        inner.dataset.olbrStripped = '1';
        inner.addEventListener('load', go);
        try {
          if (inner.contentDocument && inner.contentDocument.readyState === 'complete') go();
        } catch (e) { /* ignore */ }
      });
    } catch (e) { /* 跨域时静默跳过 */ }
  }

  /* ------------------------------------------------------------ chrome -- */
  function applyI18n() {
    root.setAttribute('lang', state.lang === 'en' ? 'en' : 'zh-CN');
    $$('[data-i18n]').forEach(function (e) { e.textContent = t(e.getAttribute('data-i18n')); });
    var q = $('#q'); if (q) q.setAttribute('placeholder', t('search.ph'));
    $$('.mast .seg-b[data-lang]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-lang') === state.lang ? 'true' : 'false');
    });
    $('#themeBtn').innerHTML = '<i class="ph ph-' + (state.theme === 'dark' ? 'sun' : 'moon') + '" aria-hidden="true"></i>';
    var src = D.meta || {};
    $('#footSrc').textContent = tf('foot.src', { n: (D.stats && D.stats.total) || ITEMS.length, d: src.generated || '' });
  }
  function setTheme(v) {
    state.theme = v; root.classList.toggle('dark', v === 'dark'); ss('olbr.theme', v);
    applyI18n();
    var f = $('#mapFrame'); if (f) { f.src = curMap().src; }
  }
  function setLang(v) { state.lang = v; ss('olbr.lang', v); render(); }
  function toast(msg) {
    var el = $('#toast'); el.textContent = msg; el.hidden = false;
    el.className = 'toast';
    window.setTimeout(function () { el.hidden = true; }, 2200);
  }
  function tick() { $('#clock').textContent = fmtTime(Date.now()); }

  /* --------------------------------------------------------- env badge -- */
  function envBadge() {
    var host = location.hostname;
    var local = host === 'localhost' || host === '127.0.0.1';
    $('#envLabel').textContent = local ? (state.lang === 'en' ? 'Local host' : '本机') : (state.lang === 'en' ? 'Liberia' : '利比里亚');
    api('/api/portal-qc/summary').then(function () { $('#envBadge').classList.remove('bad'); })
      .catch(function () { $('#envBadge').classList.add('bad'); });
  }

  /* ------------------------------------------------------------ events -- */
  function bind() {
    var qEl = $('#q'), deb;
    qEl.addEventListener('input', function () {
      window.clearTimeout(deb);
      deb = window.setTimeout(function () { state.q = qEl.value || ''; render(); }, 120);
    });
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); qEl.focus(); qEl.select(); }
      if (e.key === 'Escape') { if (state.drill.metric) closeDrill(); else if (qEl === document.activeElement) { qEl.value = ''; state.q = ''; render(); } }
    });
    $('#chips').addEventListener('click', function (e) {
      var c = e.target.closest('.chip'); if (!c) return;
      state.group = c.getAttribute('data-gid');
      /* 点分组 chip 时把主视图页签一起切过去：不然筛选条件变了、下面展示的却还是上一个分组，
         看起来像是筛选没生效。'all' 和辅助分组不动页签。 */
      if (T1.indexOf(state.group) !== -1) state.viewTab = state.group;
      render();
    });
    /* 直接绑在按钮上：index.html 里带 data-status 的是 .seg-b，容器 .seg 没有这个属性，
       原先写成 $$('.seg[data-status]') → 一个都选不到，状态筛选整条是死的。 */
    $$('.seg-b[data-status]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.status = b.getAttribute('data-status'); render();
      });
    });
    $('#clearBtn').addEventListener('click', function () {
      state.q = ''; state.group = 'all'; state.status = 'all'; qEl.value = ''; render();
    });
    $('#themeBtn').addEventListener('click', function () { setTheme(state.theme === 'dark' ? 'light' : 'dark'); });
    $$('.mast .seg-b[data-lang]').forEach(function (b) {
      b.addEventListener('click', function () { setLang(b.getAttribute('data-lang')); });
    });
    $('#logoutBtn').addEventListener('click', logout);

    $('#band').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="qc-retry"]')) { state.qc.loading = true; renderBand(); loadQc(); return; }
      var m = e.target.closest('.metric'); if (m && m.getAttribute('data-qc')) openDrill(m.getAttribute('data-qc'));
    });
    $('#l0').addEventListener('click', function (e) {
      var tb = e.target.closest('[data-map]');
      if (tb) {
        state.mapTab = tb.getAttribute('data-map'); ss('olbr.maptab', state.mapTab); renderL0(); return;
      }
      if (e.target.closest('[data-act="map-reload"]')) { var f = $('#mapFrame'); if (f) f.src = curMap().src; }
    });
    $('#views').addEventListener('click', function (e) {
      var tb = e.target.closest('[data-view]'); if (!tb) return;
      state.viewTab = tb.getAttribute('data-view');
      ss('olbr.viewtab', state.viewTab); renderViews();
    });
    $('#esc').addEventListener('click', function (e) {
      var lv = e.target.closest('[data-lv]');
      if (lv) { state.escLv = lv.getAttribute('data-lv'); if (!state.escOpen) state.escOpen = true; renderEsc(); return; }
      if (e.target.closest('[data-act="esc-toggle"]')) { state.escOpen = !state.escOpen; renderEsc(); return; }
      if (e.target.closest('[data-act="esc-copy"]')) { copyEsc(); return; }
    });
    $('#aux').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act="aux-toggle"]'); if (!b) return;
      var k = b.getAttribute('data-key');
      state.auxOpen[k] = !state.auxOpen[k]; renderAux();
    });
    $('#drClose').addEventListener('click', closeDrill);
    $('#scrim').addEventListener('click', closeDrill);
    $('#drReload').addEventListener('click', fetchDrill);
    $('#drPrev').addEventListener('click', function () { if (state.drill.page > 1) { state.drill.page--; fetchDrill(); } });
    $('#drNext').addEventListener('click', function () { state.drill.page++; fetchDrill(); });
    var dq = $('#drQ'), dd;
    dq.addEventListener('input', function () {
      window.clearTimeout(dd);
      dd = window.setTimeout(function () { state.drill.q = dq.value || ''; state.drill.page = 1; fetchDrill(); }, 220);
    });
    $('#gate').addEventListener('submit', function (e) {
      if (e.target.id !== 'lf') return;
      e.preventDefault();
      var err = $('#le'), go = $('#lgo'); go.disabled = true; go.textContent = t('gate.busy'); err.hidden = true;
      login($('#lu').value.trim(), $('#lp').value).then(function () {
        renderGate(); mainLocked(false); start();
      }).catch(function (x) {
        err.textContent = t('gate.' + (x.code || 'net')); err.hidden = false;
        go.disabled = false; go.textContent = t('gate.go');
      });
    });
  }
  function copyEsc() {
    var rows = (D.escalation || {}).rows || [];
    var txt = rows.filter(function (r) { return r.level === state.escLv; })
      .map(function (r) { return [r.position, r.name, r.orange, r.lonestar, r.email].filter(Boolean).join('\t'); }).join('\n');
    var done = function () { toast(t('esc.copied')); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, done);
    else done();
  }

  /* -------------------------------------------------------------- boot -- */
  function start() {
    loadQc();
    window.setInterval(loadQc, 300000);           /* 与「告警每 5 分钟」的口径对齐 */
    loadCatalog();
  }
  function loadCatalog() {
    api('/api/portal-catalog').then(function (d) {
      var c = d && d.catalog;
      if (c && Array.isArray(c.items) && c.items.length) {
        setCatalog(c.items);
        state.groups = Array.isArray(c.groups) && c.groups.length ? c.groups : state.groups;
        state.order = (c.order && typeof c.order === 'object' && !Array.isArray(c.order)) ? c.order : {};
      }
      render();
    }).catch(function () { /* 服务端没有目录就用内置 data.js，首屏已经渲染过了 */ });
  }

  function boot() {
    applyI18n();
    mainLocked(true);
    bind();
    tick(); window.setInterval(tick, 1000);
    envBadge();
    probe().then(function () {
      if (!state.authOk) { renderGate(); return; }
      renderGate(); mainLocked(false); start();
    });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
