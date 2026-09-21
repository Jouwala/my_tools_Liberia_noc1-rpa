/* ==========================================================================
   OlrPortal — 运营工作台首页
   --------------------------------------------------------------------------
   数据来源（全部只读引用，不改写 /MsPortal/ 的任何文件）：
     · window.MS_PORTAL_DATA   ← /MsPortal/assets/data.js（51 个看板 + QC 定义 + 升级机制）
     · /api/portal-catalog     ← 服务端全局目录，编辑过就以它为准，覆盖内置目录
     · /api/portal-qc/*        ← Quality Control 实时数字与下钻明细
     · /MsPortal/assets/access.js ← 与门户一致的 allowedGroups / allowedCards 判定
   写入范围只有 olrportal.* 这一组 localStorage 键（主题 / 语言 / 最近打开 / 地图页签），
   与 msportal.* 完全隔离，两边互不影响。
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
  /* 统一门户的会话 token 键：与 /MsPortal/、/uniplam/ 共用同一份，
     所以在任一处登录过，打开本页就是已登录状态（这里只读它，不另存一份）。 */
  var PORTAL_TOKEN_KEY = 'liberia_noc_auth_v1';
  var REQUIRE_LOGIN = true;
  var QC_MAX_PAGE = 100;

  /* 图标名沿用 data.js 里的字段，映射到 /MsPortal/assets/icons/phosphor.css 的类 */
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
     专题里列的是**稳定标识**（看板的 my_app page 键 / FineBI 短链 / 外链 origin+path，
     见 rowKey），不是卡片编号 —— /api/portal-catalog 是可被在线编辑覆盖的全局目录，
     2026-09-21 那次保存就把编号整体重排过（data.js 里的 51 条只剩 49 条，
     #64 SLA Achievements / #53 Spare Parts Report 等是新号），按 no 写死会错班；
     一个 no 还可能被复用到别的分组（改过目录后 #19 从 MS 变成了 FO 的 RAN Cells KPI）。
     没被专题认领的看板仍然留在该域末尾的「其他」里，不凭空少一张。 */
  var DOMAINS = [
    {
      key: 'MS', no: '01', zh: 'MS 管理', en: 'MS Management',
      gids: ['MS View'],
      clusters: [
        { zh: 'SLA 与合同绩效', en: 'SLA & contract performance', keys: ['page:ms_wo_sla', 'page:ms_contract_kpi', 'page:ms_sla', 'link:qXUp'] },
        { zh: '网络不可用率', en: 'Network availability', keys: ['page:nur', 'link:B7E3', 'page:finebi_availability_daily'] },
        { zh: '运营总览与重大事件', en: 'Operations & incidents', keys: ['page:overview', 'page:incident_overview'] }
      ]
    },
    {
      key: 'FLM', no: '02', zh: 'FLM 管理', en: 'FLM Management',
      gids: ['FLM View', 'SP View'],
      clusters: [
        { zh: '告警处理', en: 'Alarm handling', keys: ['page:alarmManagement', 'page:realtime_alarm', 'page:alarm'] },
        { zh: '工单与现场抢修', en: 'Tickets & repair', keys: ['page:ttwo', 'page:finebi_cm_dashboard'] },
        { zh: '站点可用率', en: 'Site availability', keys: ['page:site_avail', 'page:finebi_daily_availability'] },
        { zh: '地理视图', en: 'Geographic view', keys: ['page:gis'] },
        { zh: '备品备件', en: 'Spare parts (SP)', keys: ['page:sp_material', 'page:sp_report', 'page:com_report', 'page:warehouse', 'page:finebi_spare'] }
      ]
    },
    {
      key: 'BO', no: '03', zh: 'BO 管理', en: 'BO Management',
      gids: ['BO View'],
      clusters: [
        { zh: '无线接入网', en: 'Radio access network', keys: ['page:finebi_kpi_2g', 'page:finebi_kpi_3g', 'page:finebi_kpi_4g'] },
        { zh: '核心网与客户业务', en: 'Core network & service', keys: ['page:cn_kpi', 'page:finebi_cn_kpi_monthly', 'page:ume_in_kpi'] },
        { zh: 'IP 承载网', en: 'IP transport', keys: ['page:finebi_ipran_4region', 'page:finebi_ipran_hq', 'page:finebi_metro_ring', 'page:ip_trace', 'page:packet_loss'] },
        { zh: '微波', en: 'Microwave', keys: ['page:mwUmeTopology', 'page:mwRealTime'] },
        { zh: '安全与动力', en: 'Security & power', keys: ['page:finebi_fw_daily', 'page:battery'] },
        { zh: '厂商大屏内嵌', en: 'Vendor screens', keys: ['page:imonitor'] }
      ]
    },
    {
      key: 'FO', no: '04', zh: 'FO 管理', en: 'FO Management',
      gids: ['FO View'],
      clusters: [
        { zh: '告警监控', en: 'Alarm monitoring', keys: ['page:realtime_alarm', 'page:alarmManagement', 'page:alarm'] },
        { zh: '工单与修复时长', en: 'Tickets & MTTR', keys: ['page:ttwo', 'page:finebi_mttr', 'page:finebi_availability_tt'] },
        { zh: '网络与小区状态', en: 'Network status', keys: ['page:repeat_site_down', 'page:ran_cells_kpi', 'page:finebi_daily_availability'] }
      ]
    }
  ];

  /* 次级入口：不属于日常操作主路径的分区，收在页面最下方的紧凑三栏里 */
  var SUPPORT = [
    { gids: ['CXO View'], zh: '决策层视图', en: 'Executive view' },
    { gids: ['System Admin'], zh: '系统与配置', en: 'System & configuration' },
    { gids: ['Knowledge Q&A', 'Friends Link'], zh: '知识与生态', en: 'Knowledge & ecosystem' }
  ];

  /* 地图页签：与 /MsPortal/ 中列同一批 my_app 页面，mwembed=1 只留地图本体 */
  var MAP_TABS = [
    { page: 'gis', zh: 'GIS', en: 'GIS', icon: 'map' },
    { page: 'mwRealTime', zh: '微波', en: 'MW', icon: 'broadcast' },
    { page: 'realtime_alarm', zh: '告警', en: 'Alarm', icon: 'bell' },
    { page: 'packet_loss', zh: '丢包', en: 'Loss', icon: 'link' }
  ];

  /* ---------------------------------------------------------- 文案 ------ */
  var STR = {
    'brand.sub': { zh: '运营工作台 · Operations Workspace', en: 'Operations Workspace' },
    'search.ph': { zh: '搜索看板名称、描述、责任人、标签…', en: 'Search dashboards, reports, sites…' },
    'theme.tip': { zh: '深色 / 浅色', en: 'Dark / light' },
    'ops.title': { zh: 'Operations', en: 'Operations' },
    'ops.note': { zh: '按业务域进入 · 每个域下面是它自己的看板清单', en: 'Enter by business domain · each domain lists its own dashboards' },
    'qc.title': { zh: 'Quality Control · 质量指标', en: 'Quality Control' },
    'qc.updated': { zh: '更新于', en: 'Updated' },
    'qc.compliance': { zh: '达标率', en: 'Compliance' },
    'qc.esc': { zh: '升级机制', en: 'Escalation matrix' },
    'cat.network': { zh: '网络', en: 'Network' },
    'cat.service': { zh: '业务', en: 'Service' },
    'cat.maint': { zh: '维护', en: 'Maintenance' },
    'net.title': { zh: 'Network Overview · 网络概览', en: 'Network Overview' },
    'net.sub': { zh: '利比里亚 · 区域拓扑（辅助上下文，不是主视图）', en: 'Liberia · regional topology (context, not the centrepiece)' },
    'net.alarms': { zh: '活动告警', en: 'Active alarms' },
    'net.down': { zh: '退服站点', en: 'Sites down' },
    'net.full': { zh: '全屏打开', en: 'Open full view' },
    'net.loading': { zh: '地图加载中…', en: 'Loading map…' },
    'work.title': { zh: 'My Work · 待处理', en: 'My work' },
    'work.sub': { zh: '只列需要动作的那一项', en: 'Only what needs an action' },
    'work.open': { zh: '点开看明细', en: 'Click for detail' },
    'recent.title': { zh: 'Recently Opened · 最近打开', en: 'Recently opened' },
    'recent.empty': { zh: '从这里打开过看板之后，会列在这里。', en: 'Dashboards you open from here will show up here.' },
    'more.title': { zh: 'Supporting Entries · 辅助入口', en: 'Supporting entries' },
    'more.note': { zh: '不常进、但必须找得到 · 想要卡片式全目录，打开 /MsPortal/', en: 'Rarely used but always reachable · card catalogue lives at /MsPortal/' },
    'more.catalogue': { zh: '打开卡片式全目录 /MsPortal/', en: 'Open the card catalogue /MsPortal/' },
    'count.of': { zh: '共 {n} 个看板', en: '{n} dashboards' },
    'count.hit': { zh: '匹配 {m} / {n} 个看板', en: '{m} of {n} dashboards' },
    'dash.n': { zh: '{n} 个看板', en: '{n} dashboards' },
    'other': { zh: '其他', en: 'More' },
    'jump.all': { zh: '全部', en: 'All' },
    'jump.support': { zh: '辅助入口', en: 'Support' },
    'empty': { zh: '没有匹配的看板 —— 换个关键词，或点「全部」', en: 'No dashboard matches — try another word, or pick All' },
    'beta': { zh: '试运行', en: 'Beta' },
    'new': { zh: '新增', en: 'New' },
    'ext.tip': { zh: '外链：新标签页打开', en: 'External link: opens in a new tab' },
    'gate.title': { zh: '登录后即可查看看板目录', en: 'Sign in to see the dashboard catalogue' },
    'gate.note': { zh: '使用统一门户同一套账号与权限。', en: 'Same account and permissions as the unified portal.' },
    'gate.btn': { zh: '登录', en: 'Sign in' },
    'menu.appearance': { zh: '深色主题', en: 'Dark theme' },
    'menu.portal': { zh: '数据看板门户 /uniplam/', en: 'Data dashboard portal /uniplam/' },
    'menu.catalogue': { zh: '卡片式全目录 /MsPortal/', en: 'Card catalogue /MsPortal/' },
    'menu.usermgmt': { zh: '用户管理', en: 'User management' },
    'menu.logout': { zh: '退出登录', en: 'Sign out' },
    'user.signed': { zh: '已登录 · 角色', en: 'Signed in · role' },
    'user.local': { zh: '本机访客', en: 'Local session' },
    'role.admin': { zh: '管理员', en: 'Admin' },
    'role.viewer': { zh: '只读', en: 'Viewer' },
    'btn.reload': { zh: '刷新', en: 'Refresh' },
    'btn.close': { zh: '关闭', en: 'Close' },
    'btn.prev': { zh: '上一页', en: 'Previous' },
    'btn.next': { zh: '下一页', en: 'Next' },
    'qc.search': { zh: '搜索明细…', en: 'Filter rows…' },
    'qc.page': { zh: '第 {p} / {t} 页', en: 'Page {p} / {t}' },
    'qc.rows': { zh: '{n} 行', en: '{n} rows' },
    'qc.loading': { zh: '加载中…', en: 'Loading…' },
    'qc.err': { zh: '明细暂时取不到（后端未启动或指标未配置）', en: 'Detail unavailable (backend down or metric not configured)' },
    'esc.title': { zh: '升级机制 (Escalation Matrix)', en: 'Escalation Matrix' },
    'login.title': { zh: '登录统一门户', en: 'Sign in to the unified portal' },
    'login.user': { zh: '用户名', en: 'Username' },
    'login.pass': { zh: '密码', en: 'Password' },
    'login.note': { zh: '使用统一门户同一套账号、密码和权限。', en: 'Same account, password and permissions as /uniplam/.' },
    'login.cancel': { zh: '取消', en: 'Cancel' },
    'login.submit': { zh: '登录', en: 'Sign in' },
    'login.logging': { zh: '登录中…', en: 'Signing in…' },
    'login.bad': { zh: '用户名或密码不正确', en: 'Wrong username or password' },
    'login.locked': { zh: '尝试次数过多，稍后再试', en: 'Too many attempts, try later' },
    'login.net': { zh: '网络异常，无法连接登录服务', en: 'Cannot reach the sign-in service' },
    'foot.branch': { zh: '利比里亚办事处网络运营中心 (OLR MS)', en: 'Liberia OLR Network Operations Centre' },
    'foot.source': { zh: '目录来源：统一看板目录（与 /MsPortal/ 同一份）', en: 'Catalogue: the shared dashboard catalogue (same as /MsPortal/)' },
    'pf.myapp': { zh: 'my_app', en: 'my_app' },
    'pf.finebi': { zh: 'FineBI', en: 'FineBI' },
    'pf.external': { zh: '外链', en: 'External' },
    'work.sites': { zh: '站点退服', en: 'Sites down' },
    'work.overdue': { zh: '超期预防性维护', en: 'Overdue PM tasks' },
    'work.miss': { zh: '达标缺口（30 天）', en: 'SLA misses (30 days)' },
    'work.alarm': { zh: '活动告警', en: 'Active alarms' },
    'work.outband': { zh: '带外备件单据', en: 'Out-of-band documents' },
    'work.note.sites': { zh: '按站点聚合，点进去看告警明细', en: 'Aggregated by site — click for the alarm detail' },
    'work.note.overdue': { zh: 'PMT 中已过计划完成时间', en: 'PMT past its planned finish' },
    'work.note.miss': { zh: '30 天内未达标的工单数', en: 'Tickets below target in the last 30 days' },
    'work.note.alarm': { zh: '未消除告警总量', en: 'Uncleared alarms' },
    'work.note.outband': { zh: 'SPMS 带外流程单据', en: 'SPMS out-of-band documents' }
  };

  /* ---------------------------------------------------------- state ----- */
  function readLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function writeLS(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function readJSON(k, d) { try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : d; } catch (e) { return d; } }
  function writeJSON(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  var state = {
    lang: readLS(LS.lang) === 'en' ? 'en' : 'zh',
    theme: readLS(LS.theme) === 'dark' ? 'dark' : 'light',
    q: '',
    domain: 'all',
    items: DATA.items || [],
    qc: null,
    qcAt: '',
    authUser: null,
    authOk: null,           /* null = 还没探完 */
    mapTab: readLS(LS.mapTab) || 'gis',
    recent: readJSON(LS.recent, []),
    drill: null,
    busy: false,
    catalogFrom: 'builtin'
  };

  /* ------------------------------------------------------------ utils --- */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function t(k) { var s = STR[k]; return s ? (s[state.lang] || s.zh || k) : k; }
  function tf(k, map) {
    return t(k).replace(/\{(\w+)\}/g, function (_, n) { return map && map[n] != null ? map[n] : ''; });
  }
  function nfo(n) { return (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('en-US'); }
  function ico(name, cls) { return '<i class="ph ' + (PH[name] || PH.dashboard) + (cls ? ' ' + cls : '') + '" aria-hidden="true"></i>'; }
  function pick(en, zh) { return state.lang === 'en' ? (en || zh || '') : (zh || en || ''); }
  function norm(s) { return String(s || '').toLowerCase().normalize('NFKD'); }
  function toast(msg) {
    var el = $('toast'); if (!el) return;
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.hidden = true; }, 2600);
  }
  function ago(ts) {
    var d = new Date(ts), now = Date.now(), s = Math.floor((now - ts) / 1000);
    if (s < 60) return state.lang === 'en' ? 'just now' : '刚刚';
    if (s < 3600) return (state.lang === 'en' ? s + ' min ago' : s + ' 分钟前');
    if (s < 86400) return (state.lang === 'en' ? Math.floor(s / 3600) + ' h ago' : Math.floor(s / 3600) + ' 小时前');
    if (s < 86400 * 7) return (state.lang === 'en' ? Math.floor(s / 86400) + ' d ago' : Math.floor(s / 86400) + ' 天前');
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }
  function hhmmss(d) {
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2);
  }

  /* 顶栏是 sticky 的，右栏 sticky 的 top 必须等于它的真实高度；
     字号/断点/换语言都会改这个高度，所以实测而不是写死。 */
  function syncMastH() {
    var m = document.querySelector('.olr-mast');
    if (!m) return;
    document.documentElement.style.setProperty('--mast-h', Math.round(m.getBoundingClientRect().height) + 'px');
  }

  /* --------------------------------------------------- 目录与权限 ------- */
  function canSee(item) {
    var A = window.MSPortalAccess;
    return A ? A.canSee(state.authUser, item) : true;
  }
  function itemPageKey(item) {
    try { return new URL(String(item.url || ''), location.href).searchParams.get('page') || ''; } catch (e) { return ''; }
  }
  /** 看板的稳定标识：目录被在线编辑重排编号后仍能对上（专题分组表用它，不用 no） */
  function rowKey(item) {
    var raw = String(item.url || '');
    try {
      var u = new URL(raw, location.href);
      var page = u.searchParams.get('page');
      if (page) return 'page:' + page;
      if (/^\/webroot\/decision\/link\//.test(u.pathname)) return 'link:' + u.pathname.split('/').pop();
      return 'url:' + u.origin + u.pathname;
    } catch (e) { return 'url:' + raw; }
  }
  function visibleItems() {
    return state.items.filter(canSee);
  }
  /** 该看板是否属于某个业务域 / 辅助分区（按分组，不靠手写的编号表） */
  function inGids(item, gids) {
    var gs = item.groups || [];
    return gids.some(function (g) { return gs.indexOf(g) !== -1; });
  }
  function domainItems(d) {
    return visibleItems().filter(function (it) { return inGids(it, d.gids); });
  }
  function supportItems(sec) {
    return visibleItems().filter(function (it) {
      /* 已被四个业务域收走的，不在辅助区重复出现 */
      if (DOMAINS.some(function (d) { return inGids(it, d.gids); })) return false;
      return inGids(it, sec.gids);
    });
  }
  /** 全部可见看板的并集是否都被收纳了；没收进来的（例如新加的自定义分组）兜底展示 */
  function orphanItems() {
    var all = DOMAINS.reduce(function (a, d) { return a.concat(d.gids); }, []);
    SUPPORT.forEach(function (s) { all = all.concat(s.gids); });
    return visibleItems().filter(function (it) { return !inGids(it, all); });
  }

  function matches(item, q) {
    if (!q) return true;
    var hay = norm([
      item.titleEn, item.titleZh, item.descEn, item.descZh,
      (item.tags || []).join(' '), item.owner, item.ownerEn, item.dept, item.deptEn, item.freq
    ].join(' '));
    return q.split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; });
  }

  /* -------------------------------------------------------- 看板行 ------ */
  function hitMark(text, q) {
    var safe = esc(text);
    if (!q) return safe;
    var words = q.split(/\s+/).filter(Boolean).map(function (w) {
      return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    });
    if (!words.length) return safe;
    var re = new RegExp('(' + words.join('|') + ')', 'ig');
    return safe.replace(/(&[a-z]+;|#39;)/gi, '\u0000$1\u0000')
      .replace(re, function (m) { return '<mark>' + m + '</mark>'; })
      .replace(/\u0000/g, '');
  }

  function viewerHref(item) {
    var gid = (item.groups && item.groups[0]) || '';
    return '/MsPortal/viewer.html?no=' + encodeURIComponent(item.no) +
      (gid ? '&gid=' + encodeURIComponent(gid) : '');
  }

  function rowHtml(item) {
    var q = state.q;
    var href = viewerHref(item);
    var ext = item.platform === 'external' || item.groups === 'Friends Link';
    var isFriends = inGids(item, ['Friends Link']);
    if (isFriends) href = item.url;
    var title = pick(item.titleEn, item.titleZh) || item.titleZh || ('#' + item.no);
    var desc = pick(item.descEn, item.descZh) || '';
    var pf = item.platform === 'myapp' ? 'my_app' : item.platform === 'finebi' ? 'FineBI' : item.platform === 'external' ? 'External' : '';
    var chips = '';
    if (item.status === 'beta') chips += '<span class="tag tag--beta" title="' + esc(state.lang === 'en' ? 'Pilot, not yet a daily report' : '试运行，未正式日报化') + '">' + t('beta') + '</span>';
    if (item.isNew) chips += '<span class="tag tag--new">' + t('new') + '</span>';
    if (pf) chips += '<span class="tag tag--pf' + (pf === 'External' ? ' tag--ext' : '') + '">' + esc(pf) + '</span>';
    var who = pick(item.deptEn, item.dept) || pick(item.ownerEn, item.owner) || '';
    var tip = title + (desc ? '\n' + desc : '') + (who ? '\n' + who : '') + (item.freq ? '\n' + item.freq : '');
    return '<a class="olr-row" href="' + esc(href) + '"' +
      (isFriends ? ' target="_blank" rel="noopener noreferrer"' : '') +
      ' data-no="' + esc(item.no) + '" title="' + esc(tip) + '">' +
      '<span class="olr-row-ic">' + ico(item.icon) + '</span>' +
      '<span class="olr-row-tx">' +
        '<span class="olr-row-t">' + hitMark(title, q) + '</span>' +
        (desc ? '<span class="olr-row-d">' + hitMark(desc, q) + '</span>' : '') +
      '</span>' +
      '<span class="olr-row-meta">' + chips + '</span>' +
      '<span class="olr-row-go ph ' + (isFriends ? 'ph-arrow-up-right' : 'ph-caret-right') + '" aria-hidden="true"></span>' +
    '</a>';
  }

  function rowsHtml(list) {
    return '<div class="olr-rows">' + list.map(rowHtml).join('') + '</div>';
  }

  /* -------------------------------------------------- 业务域区块 -------- */
  function domainHtml(d) {
    var all = domainItems(d);
    if (!all.length) return '';
    var byKey = {};
    all.forEach(function (it) { var k = rowKey(it); if (!byKey[k]) byKey[k] = it; });
    var taken = {}, kept = [];
    d.clusters.forEach(function (c) {
      var list = [];
      /* 按专题里写好的顺序排（把最能代表该域的看板放前面），顺序即优先级 */
      c.keys.forEach(function (k) {
        var it = byKey[k];
        if (it && !taken[k] && matches(it, state.q)) list.push(it);
      });
      list.forEach(function (it) { taken[rowKey(it)] = 1; });
      if (list.length) kept.push({ c: c, list: list });
    });
    /* 没被专题认领的（新看板、被改过归属的看板）留在域末尾，不丢 */
    var rest = all.filter(function (it) { return !taken[rowKey(it)] && matches(it, state.q); });
    if (rest.length) kept.push({ c: { zh: t('other'), en: t('other') }, list: rest });
    var shown = kept.reduce(function (n, k) { return n + k.list.length; }, 0);
    if (!shown) return '';

    var body = kept.map(function (k) {
      var solo = kept.length === 1;
      return '<div class="olr-cluster' + (solo ? ' is-solo' : '') + '">' +
        (solo ? '' : '<span class="eyebrow">' + esc(pick(k.c.en, k.c.zh)) + '</span>') +
        rowsHtml(k.list) +
      '</div>';
    }).join('');

    return '<section class="olr-domain" id="dom-' + d.key + '" data-dom="' + d.key + '" aria-label="' + esc(d.key) + ' view">' +
      '<header class="olr-domain-head">' +
        '<span class="olr-domain-no">' + d.no + '</span>' +
        '<div class="olr-domain-tt">' +
          '<h3>' + esc(d.key) + ' <em>' + esc(pick('Management', state.lang === 'en' ? 'Management' : d.key === 'MS' ? '管理' : d.key === 'FLM' ? '管理' : '管理')) + '</em></h3>' +
          '<p>' + esc(groupSub(d.gids[0])) + '</p>' +
        '</div>' +
        '<span class="olr-domain-n"><a href="' + esc('/MsPortal/viewer.html?gid=' + encodeURIComponent(d.gids[0])) + '" title="' + esc(t('more.catalogue')) + '">' + nfo(shown) + ' ' + esc(pick('dashboards', '个看板')) + '</a></span>' +
      '</header>' +
      body +
    '</section>';
  }

  function groupSub(gid) {
    var g = (DATA.groups || []).filter(function (x) { return x.id === gid; })[0];
    return g ? pick(g.subEn, g.subZh) : '';
  }

  /* ----------------------------------------------- Quality Control ------ */
  var QC_CAT = { alarm: 'network', tt: 'service', wo: 'service', cr: 'service', pmt: 'maint', spms: 'maint' };

  function qcVal(id) {
    var m = state.qc && state.qc.metrics && state.qc.metrics[id];
    return m || null;
  }

  function qcMetricHtml(m) {
    var v = qcVal(m.id);
    var num = v ? v.value : null;
    var cls = '';
    if (m.id === 'pmt' && v && v.overdue > 0) cls = '';
    return '<button type="button" class="olr-qc-m' + (cls ? ' ' + cls : '') + '" data-qc="' + m.id + '">' +
      '<span class="olr-qc-m-l">' + esc(pick(m.en, m.zh)) + '</span>' +
      '<span class="olr-qc-m-n">' + (num == null ? '<span class="skel">—</span>' : nfo(num)) + '</span>' +
      (m.id === 'pmt' && v && v.overdue ? '<span class="olr-qc-m-u is-bad" style="color:var(--bad)">· ' + nfo(v.overdue) + '</span>' : '') +
    '</button>';
  }

  function renderQc() {
    var el = $('qc');
    if (!el) return;
    var defs = (DATA.qc || []);
    var cats = { network: [], service: [], maint: [] };
    defs.forEach(function (m) { (cats[QC_CAT[m.id]] || cats.service).push(m); });
    var sla = qcVal('sla');
    var slaCls = !sla ? '' : sla.value >= 95 ? 'is-ok' : sla.value >= 85 ? 'is-warn' : 'is-bad';

    el.innerHTML =
      '<div class="olr-qc-head">' +
        '<span class="eyebrow">' + esc(t('qc.title')) + '</span>' +
        '<span class="olr-qc-head-r">' +
          '<span>' + esc(t('qc.updated')) + ' <span class="mono" id="qcAt">' + esc(state.qcAt || '—') + '</span></span>' +
          '<span class="olr-qc-sla ' + slaCls + '" title="' + esc(sla ? (state.lang === 'en'
              ? sla.pass + ' of ' + sla.total + ' tickets met target in the last ' + sla.days + ' days'
              : sla.days + ' 天内 ' + sla.total + ' 单中 ' + sla.pass + ' 单达标') : '') + '">' +
            esc(t('qc.compliance')) + ' <b>' + (sla ? sla.value + '%' : '—') + '</b></span>' +
          '<button type="button" class="olr-link" id="qcEsc">' + esc(t('qc.esc')) + '</button>' +
        '</span>' +
      '</div>' +
      '<div class="olr-qc-body">' +
        ['network', 'service', 'maint'].map(function (c) {
          return '<div class="olr-qc-cat">' +
            '<span class="olr-qc-cat-name">' + esc(t('cat.' + c)) + '</span>' +
            cats[c].map(qcMetricHtml).join('') +
          '</div>';
        }).join('') +
      '</div>';
  }

  /* ------------------------------------------------ 右侧：网络概览 ------ */
  function mapItems() {
    return MAP_TABS.map(function (m) {
      var item = visibleItems().filter(function (it) { return itemPageKey(it) === m.page; })[0];
      return item ? { page: m.page, zh: m.zh, en: m.en, icon: m.icon, item: item } : null;
    }).filter(Boolean);
  }

  /* 面板骨架只建一次：地图 iframe 重新加载要几十秒，所以刷新 QC 数字、切换语言、
     换页签都只重画 tabs / foot 这些小块，绝不再碰 #mapHost 里已有的 iframe。 */
  function netSkeleton() {
    $('net').innerHTML =
      '<div class="olr-panel-head">' +
        '<div><span class="eyebrow" id="netTitle"></span><p class="olr-panel-sub" id="netSub"></p></div>' +
      '</div>' +
      '<div class="olr-map-tabs" id="mapTabs" role="tablist"></div>' +
      '<div class="olr-map-frame" id="mapHost">' +
        '<div class="olr-map-note" id="mapNote" hidden><span id="netLoading"></span></div>' +
      '</div>' +
      '<div class="olr-map-foot olr-panel-bd" id="mapFoot"></div>';
  }

  function renderNet() {
    var el = $('net');
    if (!el) return;
    var tabs = mapItems();
    if (!tabs.length) { el.hidden = true; return; }
    el.hidden = false;
    if (!$('mapHost')) netSkeleton();
    if (!tabs.some(function (m) { return m.page === state.mapTab; })) state.mapTab = tabs[0].page;
    var cur = tabs.filter(function (m) { return m.page === state.mapTab; })[0] || tabs[0];
    $('netTitle').textContent = t('net.title');
    $('netSub').textContent = t('net.sub');
    $('netLoading').textContent = t('net.loading');
    $('mapNote').hidden = !!state.mapBooted;
    $('mapTabs').innerHTML = tabs.map(function (m) {
      return '<button type="button" class="olr-map-tab" role="tab" data-page="' + esc(m.page) + '" ' +
        'aria-selected="' + (m.page === cur.page) + '">' + ico(m.icon) + '<span>' + esc(pick(m.en, m.zh)) + '</span></button>';
    }).join('');
    var a = qcVal('alarm');
    $('mapFoot').innerHTML =
      '<span class="' + (a && a.value ? 'is-bad' : '') + '">' + esc(t('net.alarms')) + ' <b>' + (a ? nfo(a.value) : '—') + '</b></span>' +
      '<span class="' + (a && a.sites ? 'is-bad' : '') + '">' + esc(t('net.down')) + ' <b>' + (a ? nfo(a.sites) : '—') + '</b></span>' +
      '<a class="olr-link" href="' + esc(viewerHref(cur.item)) + '" target="_blank" rel="noopener noreferrer">' + esc(t('net.full')) + ' ↗</a>';
    ensureFrame(cur.page);
  }

  /* 把「内嵌 + 当前主题」告诉地图 iframe —— 走 my_app 自己那套 postMessage 协议，
     坚决不改 iframe.src：地图首帧要几十秒，改 src 等于重新加载一遍。
     为什么要发两条（同一套做法见 MsPortal/assets/portal.js 的 tellEmbed 注释）：
       · msportal-embed → /myapp/?page=mwRealTime 这层 React 外壳会原样转发给里层的
         mw_real_time.html。内层 src 由 LegacyToolFrame 写死，URL 上的 ?mwembed/?theme
         到那里就断了，只能靠消息。
       · myapp-theme   → 纯 React 页签（CxoDashboard / AlarmManagement 那一类）认这条。
     两条都只让对方面向父页面切色，不写 localStorage，所以不会把 my_app 自己的主题带偏。
     重试是因为外壳里的内层 iframe 挂载比这条消息晚，1.2s / 3.2s 各补一次。 */
  function tellEmbed(f, depth) {
    depth = depth || 0;
    if (f && f.contentWindow) {
      try {
        f.contentWindow.postMessage({ __type: 'msportal-embed', theme: state.theme, depth: depth }, '*');
        f.contentWindow.postMessage({ __type: 'myapp-theme', mode: state.theme }, '*');
      } catch (e) { /* 忽略 */ }
    }
    if (depth >= 2) return;
    /* 本页与 /myapp/ 经 nginx 同在 80 端口 → 同源，所以能自己钻到里层直接投；
       外壳那条转发（LegacyToolFrame）留着当兜底，谁先到都行，接收方是幂等的。 */
    try {
      var d = f && f.contentDocument;
      if (!d) return;
      Array.prototype.forEach.call(d.querySelectorAll('iframe'), function (inner) {
        tellEmbed(inner, depth + 1);
      });
    } catch (e) { /* 跨域时静默跳过 */ }
  }

  function tellEmbedAll(withRetry) {
    Array.prototype.forEach.call(document.querySelectorAll('#mapHost iframe'), function (f) {
      tellEmbed(f);
      if (!withRetry) return;
      setTimeout(function () { tellEmbed(f); }, 1200);
      setTimeout(function () { tellEmbed(f); }, 3200);
    });
  }

  function ensureFrame(page) {
    var host = $('mapHost');
    if (!host) return;
    var note = $('mapNote');
    var id = 'fr-' + page;
    var f = $(id);
    if (!f) {
      f = document.createElement('iframe');
      f.id = id;
      f.setAttribute('title', page);
      f.setAttribute('referrerpolicy', 'no-referrer-when-downgrade');
      f.setAttribute('src', '/myapp/?page=' + encodeURIComponent(page) + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : ''));
      f.addEventListener('load', function () {
        state.mapBooted = true;
        var n = $('mapNote');
        if (n) n.hidden = true;
        tellEmbed(f);
      });
      host.appendChild(f);
      tellEmbed(f);
      setTimeout(function () { tellEmbed(f); }, 1200);
      setTimeout(function () { tellEmbed(f); }, 3200);
    }
    Array.prototype.forEach.call(host.querySelectorAll('iframe'), function (x) {
      x.classList.toggle('is-on', x.id === id);
    });
    if (note && state.mapBooted) note.hidden = true;
  }

  /* ------------------------------------------- 右侧：待处理 / 最近 ------ */
  function workRows() {
    if (!state.qc) return null;
    var m = state.qc.metrics || {};
    var rows = [];
    function add(key, label, note, val, cls, metric) {
      if (val == null || isNaN(val)) return;
      rows.push({ key: key, label: label, note: note, val: val, cls: cls, metric: metric });
    }
    if (m.alarm) {
      add('sites', t('work.sites'), t('work.note.sites'), m.alarm.sites, m.alarm.sites > 0 ? 'is-bad' : 'is-ok', 'alarm');
      add('alarm', t('work.alarm'), t('work.note.alarm'), m.alarm.value, m.alarm.value > 0 ? 'is-warn' : 'is-ok', 'alarm');
    }
    if (m.pmt) add('overdue', t('work.overdue'), t('work.note.overdue'), m.pmt.overdue, m.pmt.overdue > 0 ? 'is-bad' : 'is-ok', 'pmt');
    if (m.sla && m.sla.total) add('miss', t('work.miss'), t('work.note.miss'), Math.max(0, m.sla.total - m.sla.pass), 'is-warn', null);
    if (m.spms && m.spms.tables) add('outband', t('work.outband'), t('work.note.outband'), m.spms.tables.outband_details, m.spms.tables.outband_details > 0 ? 'is-warn' : 'is-ok', 'spms');
    return rows;
  }

  function renderWork() {
    var el = $('work');
    if (!el) return;
    var rows = workRows();
    var body = rows && rows.length
      ? rows.map(function (r) {
          return '<button type="button" class="olr-li" data-qc="' + esc(r.metric || '') + '">' +
            '<span class="olr-li-t">' + esc(r.label) + '<span class="olr-li-d">' + esc(r.note) + '</span></span>' +
            '<span class="olr-li-n ' + r.cls + '">' + nfo(r.val) + '</span>' +
            '<span class="olr-li-go ph ph-caret-right"></span>' +
          '</button>';
        }).join('')
      : '<p class="olr-hint"><span class="skel">····</span></p>';
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
      '<div class="olr-list">' +
        (list.length
          ? list.map(function (r) {
              return '<a class="olr-recent" href="' + esc(viewerHref(r.it)) + '" data-no="' + esc(r.it.no) + '">' +
                '<span class="olr-recent-t">' + esc(pick(r.it.titleEn, r.it.titleZh)) + '</span>' +
                '<span class="olr-recent-m">' + esc(ago(r.at)) + ' · ' + esc(pick(r.it.platform, r.it.platform)) + '</span>' +
              '</a>';
            }).join('')
          : '<p class="olr-hint">' + esc(t('recent.empty')) + '</p>') +
      '</div>';
  }

  /* ------------------------------------------------- 底部：辅助入口 ---- */
  function renderMore() {
    var el = $('more');
    if (!el) return;
    var secs = SUPPORT.map(function (s) {
      var list = supportItems(s).filter(function (it) { return matches(it, state.q); });
      if (!list.length) return '';
      return '<div class="olr-more-sec">' +
        '<h4>' + esc(pick(s.en, s.zh)) + '</h4>' +
        '<p>' + esc(s.gids.map(function (g) {
          var def = (DATA.groups || []).filter(function (x) { return x.id === g; })[0];
          return def ? pick(def.subEn, def.subZh) : g;
        }).join(' · ')) + '</p>' +
        rowsHtml(list) +
      '</div>';
    }).join('');
    var orph = orphanItems().filter(function (it) { return matches(it, state.q); });
    if (orph.length) {
      secs += '<div class="olr-more-sec"><h4>' + esc(t('other')) + '</h4>' + rowsHtml(orph) + '</div>';
    }
    if (!secs.replace(/\s/g, '')) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML =
      '<div class="olr-more-head">' +
        '<div><span class="eyebrow">' + esc(t('more.title')) + '</span><p>' + esc(t('more.note')) + '</p></div>' +
        '<a class="olr-link" href="/MsPortal/" target="_blank" rel="noopener noreferrer">' + esc(t('more.catalogue')) + ' ↗</a>' +
      '</div>' +
      '<div class="olr-more-grid">' + secs + '</div>';
  }

  /* ------------------------------------------------------- 检索行 ------- */
  function renderJump() {
    var el = $('jump');
    if (!el) return;
    var total = visibleItems().length;
    var hits = visibleItems().filter(function (it) { return matches(it, state.q); }).length;
    var btns = [{ k: 'all', label: t('jump.all'), n: hits }];
    DOMAINS.forEach(function (d) {
      var n = domainItems(d).filter(function (it) { return matches(it, state.q); }).length;
      if (n) btns.push({ k: d.key, label: d.key, n: n });
    });
    var sup = SUPPORT.reduce(function (a, s) { return a + supportItems(s).filter(function (it) { return matches(it, state.q); }).length; }, 0) + orphanItems().filter(function (it) { return matches(it, state.q); }).length;
    if (sup) btns.push({ k: 'support', label: t('jump.support'), n: sup });
    el.innerHTML = btns.map(function (b) {
      return '<button type="button" class="olr-jump-btn" data-dom="' + esc(b.k) + '" aria-pressed="' + (state.domain === b.k) + '">' +
        esc(b.label) + '<span>' + b.n + '</span></button>';
    }).join('');
    var c = $('count');
    if (c) c.textContent = state.q ? tf('count.hit', { m: hits, n: total }) : tf('count.of', { n: total });
  }

  function renderCatalog() {
    var gate = REQUIRE_LOGIN && state.authOk !== true;
    var host = $('domains');
    if (gate) {
      host.innerHTML =
        '<section class="olr-domain" style="border:0">' +
          '<header class="olr-domain-head"><span class="olr-domain-no">—</span>' +
            '<div class="olr-domain-tt"><h3>' + esc(t('gate.title')) + '</h3>' +
            '<p>' + esc(t('gate.note')) + '</p></div></header>' +
          '<div class="olr-rows"><button type="button" class="olr-btn primary" id="gateLogin" style="margin:12px 0 0 8px">' + esc(t('gate.btn')) + '</button></div>' +
        '</section>';
      $('more').hidden = true;
      renderJump();
      return;
    }
    var html = DOMAINS.map(domainHtml).join('');
    var shown = host.parentNode.querySelectorAll('.olr-domain').length;
    host.innerHTML = html;
    var none = !html.replace(/\s/g, '');
    var nm = $('noMatch');
    nm.hidden = !none;
    if (none) nm.innerHTML = '<b>' + esc(t('empty')) + '</b>';
    applyDomainFilter();
    renderMore();
    renderJump();
    void shown;
  }

  function applyDomainFilter() {
    var f = state.domain;
    Array.prototype.forEach.call(document.querySelectorAll('[data-dom]'), function (b) {
      if (b.tagName !== 'SECTION') return;
      var k = b.getAttribute('data-dom');
      b.classList.toggle('is-off', !(f === 'all' || f === k));
    });
    var more = $('more');
    if (more && !more.hidden && f !== 'all' && f !== 'support') more.style.display = 'none';
    else if (more) more.style.display = '';
  }

  function renderAll() {
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
    renderUser();
    renderQc();
    renderCatalog();
    renderNet();
    renderWork();
    renderRecent();
    syncMastH();
  }

  /* -------------------------------------------------------- 顶栏用户 ---- */
  function renderUser() {
    var name = $('userName');
    var u = state.authUser;
    if (name) name.textContent = (u && (u.username || u.name || u.id)) || (state.authOk === false ? t('gate.btn') : t('user.local'));
    var list = $('userMenuList');
    if (!list || list.hidden && !list.dataset.build) return;
    list.innerHTML = userMenuHtml();
  }

  function userMenuHtml() {
    var u = state.authUser;
    var role = u && u.role === 'admin' ? t('role.admin') : u && u.role ? t('role.viewer') : '';
    var out = '<div class="olr-user-hd"><b>' + esc((u && (u.username || u.id)) || t('user.local')) + '</b>' +
      '<span>' + esc(state.authOk === false ? t('gate.note') : (t('user.signed') + ' · ' + (role || t('role.viewer')))) + '</span></div>' +
      '<button type="button" class="olr-menu-item" data-act="theme"><i class="ph ' + (state.theme === 'dark' ? 'ph-sun' : 'ph-moon') + '"></i>' + esc(t('menu.appearance')) + '</button>' +
      '<a class="olr-menu-item" href="/uniplam/" target="_blank" rel="noopener noreferrer"><i class="ph ph-graph"></i>' + esc(t('menu.portal')) + '</a>' +
      '<a class="olr-menu-item" href="/MsPortal/" target="_blank" rel="noopener noreferrer"><i class="ph ph-squares-four"></i>' + esc(t('menu.catalogue')) + '</a>';
    if (u && u.role === 'admin') {
      out += '<a class="olr-menu-item" href="/uniplam/" target="_blank" rel="noopener noreferrer"><i class="ph ph-users-four"></i>' + esc(t('menu.usermgmt')) + '</a>';
    }
    out += '<div class="olr-menu-sep"></div>';
    out += state.authOk === false
      ? '<button type="button" class="olr-menu-item" data-act="login"><i class="ph ph-user"></i>' + esc(t('gate.btn')) + '</button>'
      : '<button type="button" class="olr-menu-item danger" data-act="logout"><i class="ph ph-sign-out"></i>' + esc(t('menu.logout')) + '</button>';
    return out;
  }

  function openUserMenu(on) {
    var list = $('userMenuList'), btn = $('userBtn');
    if (!list || !btn) return;
    var show = on === undefined ? list.hidden : !!on;
    if (show) list.innerHTML = userMenuHtml();
    list.hidden = !show;
    btn.setAttribute('aria-expanded', String(show));
  }

  /* ---------------------------------------------------- 鉴权与会话 ------ */
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

  function probe() {
    if (state.busy) return;
    state.busy = true;
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
      .then(function () { state.busy = false; renderAll(); if (state.authOk === true) fetchQc(); });
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
        return swapToken(d.token);
      });
    });
  }

  function logout() {
    var tk = token();
    var reqs = [fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function() {})];
    if (tk) reqs.push(fetch('/uniplam/api/auth/logout', {
      method: 'POST', credentials: 'same-origin',
      headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
    }).catch(function () {}));
    Promise.all(reqs).then(function () {
      try { localStorage.removeItem(PORTAL_TOKEN_KEY); } catch (e) {}
      state.authUser = null;
      state.authOk = null;
      openUserMenu(false);
      probe();
    });
  }

  /* --------------------------------------------------- QC 明细弹窗 ------ */
  function openDrill(metric) {
    if (!metric) return;
    var def = (DATA.qc || []).filter(function (m) { return m.id === metric; })[0];
    state.drill = { metric: metric, page: 1, size: QC_MAX_PAGE, q: '', rows: null, columns: [], total: 0, err: '' };
    $('qcTitle').textContent = def ? pick(def.en, def.zh) : metric;
    $('qcSearch').value = '';
    $('qcMask').hidden = false;
    loadDrill();
  }
  function closeDrill() { $('qcMask').hidden = true; state.drill = null; }

  function loadDrill() {
    var d = state.drill;
    if (!d) return;
    $('qcThead').innerHTML = '';
    $('qcTbody').innerHTML = '<tr><td class="mut">' + esc(t('qc.loading')) + '</td></tr>';
    var url = '/api/portal-qc/detail?metric=' + encodeURIComponent(d.metric) +
      '&page=' + d.page + '&size=' + d.size + '&q=' + encodeURIComponent(d.q);
    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (j) {
        var dd = state.drill;
        if (!dd || dd.metric !== d.metric) return;
        dd.rows = j.rows || []; dd.columns = j.columns || []; dd.total = j.total || 0; dd.err = '';
        paintDrill();
      })
      .catch(function () {
        var dd = state.drill;
        if (!dd || dd.metric !== d.metric) return;
        dd.err = t('qc.err'); dd.rows = []; dd.columns = [];
        paintDrill();
      });
  }

  function cellText(v) {
    if (v == null || v === '') return '<span class="esc-dash">—</span>';
    if (typeof v === 'number' && v > 1e11) return esc(new Date(v).toLocaleString(state.lang === 'en' ? 'en-GB' : 'zh-CN'));
    return esc(String(v));
  }

  function paintDrill() {
    var d = state.drill;
    if (!d) return;
    if (d.err) {
      $('qcThead').innerHTML = '';
      $('qcTbody').innerHTML = '<tr><td class="mut">' + esc(d.err) + '</td></tr>';
      $('qcCount').textContent = ''; $('qcPage').textContent = '';
      return;
    }
    $('qcThead').innerHTML = '<tr>' + d.columns.map(function (c) { return '<th>' + esc(c.label) + '</th>'; }).join('') + '</tr>';
    $('qcTbody').innerHTML = (d.rows || []).map(function (r) {
      return '<tr>' + d.columns.map(function (c) {
        var v = r[c.key];
        var cls = /no|id|code|time|qty|number/.test(c.key) ? ' class="n"' : '';
        if (c.key === 'severity' && v) return '<td><span class="sev">' + esc(String(v)) + '</span></td>';
        return '<td' + cls + '>' + cellText(v) + '</td>';
      }).join('') + '</tr>';
    }).join('') || '<tr><td class="mut">—</td></tr>';
    var pages = Math.max(1, Math.ceil(d.total / d.size));
    $('qcCount').textContent = tf('qc.rows', { n: nfo(d.total) });
    $('qcPage').textContent = tf('qc.page', { p: d.page, t: pages });
    $('qcPrev').disabled = d.page <= 1;
    $('qcNext').disabled = d.page >= pages;
  }

  /* -------------------------------------------------- 升级机制弹窗 ------ */
  function openEsc() {
    var E = DATA.escalation || { levels: [], rows: [] };
    var LV = { LEVEL1: 'esc-lv-1', LEVEL2: 'esc-lv-2', LEVEL3: 'esc-lv-3', LEVEL4: 'esc-lv-4' };
    var starts = {}, cur = null;
    E.rows.forEach(function (r, i) {
      if (i === 0 || E.rows[i - 1].level !== r.level) { starts[i] = 1; cur = i; } else starts[cur]++;
    });
    var head = ['Level', 'Position', 'Name', 'Orange', 'Lonestar', 'E-mail'];
    if (state.lang !== 'en') head = ['档位', '岗位', '姓名', 'Orange', 'Lonestar', '邮箱'];
    var body = E.rows.map(function (r, i) {
      var lvCell = '';
      if (starts[i]) {
        var def = E.levels.filter(function (l) { return l.id === r.level; })[0];
        lvCell = '<td class="esc-lv ' + (LV[r.level] || 'esc-lv-1') + '" rowspan="' + starts[i] + '" title="' + esc(def ? pick(def.en, def.zh) : r.level) + '">' +
          '<span class="esc-lv-badge">' + esc(r.level) + '</span></td>';
      }
      var mail = r.email ? '<a class="olr-link" href="mailto:' + esc(r.email) + '">' + esc(r.email) + '</a>' : '<span class="esc-dash">—</span>';
      return '<tr class="' + (LV[r.level] || 'esc-lv-1') + '">' + lvCell +
        '<td>' + esc(r.position || '') + '</td><td>' + esc(r.name || '') + '</td>' +
        '<td class="n">' + (r.orange ? esc(r.orange).replace(/\//g, '/<wbr>') : '<span class="esc-dash">—</span>') + '</td>' +
        '<td class="n">' + esc(r.lonestar || '') + '</td><td>' + mail + '</td></tr>';
    }).join('');
    $('escBody').innerHTML = '<div class="esc-scroll"><table class="esc-table"><thead><tr>' +
      head.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + body + '</tbody></table></div>';
    $('escMask').hidden = false;
  }

  /* -------------------------------------------------------- 事件 -------- */
  function bind() {
    /* 语言 / 主题 */
    Array.prototype.forEach.call(document.querySelectorAll('[data-lang]'), function (b) {
      b.addEventListener('click', function () {
        state.lang = b.getAttribute('data-lang') === 'en' ? 'en' : 'zh';
        writeLS(LS.lang, state.lang);
        renderAll();
      });
    });
    function setTheme(next) {
      state.theme = next;
      writeLS(LS.theme, next);
      document.documentElement.setAttribute('data-theme', next === 'dark' ? 'dark' : 'light');
      /* 已经加载好的地图 iframe 不动：改 src 等于把每张图重新加载一遍（实测要几十秒，
         而且是全部同时空白）。主题用 postMessage 原地告诉它们（见 tellEmbed）。 */
      renderAll();
      tellEmbedAll(false);
    }
    $('themeBtn').addEventListener('click', function () { setTheme(state.theme === 'dark' ? 'light' : 'dark'); });

    /* 用户菜单 */
    $('userBtn').addEventListener('click', function (e) { e.stopPropagation(); openUserMenu(); });
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#userMenu')) openUserMenu(false);
    });
    $('userMenuList').addEventListener('click', function (e) {
      var it = e.target.closest('[data-act]');
      if (!it) return;
      e.preventDefault();
      var a = it.getAttribute('data-act');
      openUserMenu(false);
      if (a === 'theme') setTheme(state.theme === 'dark' ? 'light' : 'dark');
      else if (a === 'logout') logout();
      else if (a === 'login') $('loginMask').hidden = false;
    });

    /* 检索 */
    var deb;
    $('q').addEventListener('input', function (e) {
      clearTimeout(deb);
      deb = setTimeout(function () {
        state.q = norm(e.target.value).trim();
        $('qClear').hidden = !state.q;
        renderCatalog();
        syncMastH();
      }, 120);
    });
    $('qClear').addEventListener('click', function () {
      $('q').value = ''; state.q = ''; $('qClear').hidden = true; renderCatalog(); $('q').focus();
    });
    $('jump').addEventListener('click', function (e) {
      var b = e.target.closest('[data-dom]');
      if (!b) return;
      var k = b.getAttribute('data-dom');
      state.domain = (state.domain === k) ? 'all' : k;
      if (state.domain === 'support') {
        var m = $('more'); if (m) m.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else if (state.domain !== 'all') {
        var sec = $('dom-' + state.domain); if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      renderJump();
      applyDomainFilter();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (!$('qcMask').hidden) closeDrill();
        else if (!$('escMask').hidden) $('escMask').hidden = true;
        else if (!$('loginMask').hidden) $('loginMask').hidden = true;
        else openUserMenu(false);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); $('q').focus(); $('q').select(); }
    });

    /* 看板行：记一次「最近打开」（真实行为，不造数） */
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-no]');
      if (!a) return;
      var no = Number(a.getAttribute('data-no'));
      if (!no) return;
      state.recent = [{ no: no, at: Date.now() }]
        .concat((state.recent || []).filter(function (r) { return Number(r.no) !== no; }))
        .slice(0, 12);
      writeJSON(LS.recent, state.recent);
      renderRecent();
    });

    /* QC 状态条 + 待处理 */
    document.addEventListener('click', function (e) {
      var m = e.target.closest('[data-qc]');
      if (!m) return;
      var id = m.getAttribute('data-qc');
      if (id) { e.preventDefault(); openDrill(id); }
    });
    /* #qcEsc 由 renderQc() 每次重建（刷新数字 / 换语言都会重画这一条），
       所以绑在静态宿主 #qc 上做事件委托 —— 绑在按钮本身会在第一次刷新后失效。 */
    $('qc').addEventListener('click', function (e) {
      if (e.target.closest('#qcEsc')) openEsc();
    });
    $('qcClose').addEventListener('click', closeDrill);
    $('qcMask').addEventListener('click', function (e) { if (e.target === $('qcMask')) closeDrill(); });
    $('qcReload').addEventListener('click', function () { fetchQc(); if (state.drill) loadDrill(); });
    var qd;
    $('qcSearch').addEventListener('input', function (e) {
      clearTimeout(qd);
      var v = e.target.value;
      qd = setTimeout(function () {
        if (!state.drill) return;
        state.drill.q = v; state.drill.page = 1; loadDrill();
      }, 260);
    });
    $('qcPrev').addEventListener('click', function () { if (state.drill && state.drill.page > 1) { state.drill.page--; loadDrill(); } });
    $('qcNext').addEventListener('click', function () { if (state.drill) { state.drill.page++; loadDrill(); } });
    $('escClose').addEventListener('click', function () { $('escMask').hidden = true; });
    $('escMask').addEventListener('click', function (e) { if (e.target === $('escMask')) $('escMask').hidden = true; });

    /* 地图页签 */
    $('net').addEventListener('click', function (e) {
      var b = e.target.closest('.olr-map-tab');
      if (!b) return;
      state.mapTab = b.getAttribute('data-page');
      writeLS(LS.mapTab, state.mapTab);
      renderNet();
    });

    /* 登录 */
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
      }).finally(function () {
        btn.disabled = false; btn.textContent = t('login.submit');
      });
    });
    /* 门禁按钮 */
    document.addEventListener('click', function (e) {
      if (e.target && e.target.id === 'gateLogin') $('loginMask').hidden = false;
    });

    window.addEventListener('resize', syncMastH);
  }

  /* ------------------------------------------------------- 数据加载 ----- */
  function fetchQc() {
    fetch('/api/portal-qc/summary', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) {
        state.qc = j;
        var d = j.generated_at ? new Date(j.generated_at) : new Date();
        state.qcAt = hhmmss(isNaN(d) ? new Date() : d);
        renderQc(); renderWork();
        var net = $('net'); if (net && !net.hidden) { /* 页脚两个数字跟着刷新 */ renderNet(); }
      })
      .catch(function () { renderQc(); renderWork(); });
  }

  /* 服务端全局目录优先：MsPortal 里编辑过看板，这里刷新就是最新的。 */
  function fetchCatalog() {
    fetch('/api/portal-catalog', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok || ct.indexOf('json') === -1) return null;
        return r.json();
      })
      .then(function (j) {
        if (j && j.catalog && j.catalog.items && j.catalog.items.length) {
          state.items = j.catalog.items;
          state.catalogFrom = 'server';
        }
      })
      .catch(function () {})
      .then(function () { renderCatalog(); renderNet(); renderRecent(); renderJump(); });
  }

  /* ------------------------------------------------------------ boot ---- */
  function boot() {
    if (state.theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    renderAll();
    bind();
    syncMastH();
    probe();
    fetchCatalog();
    setInterval(function () {
      var el = $('qcAt');
      if (!el || !state.qc) return;
      /* 状态条上的「更新于」是数据的真实新鲜度，不做假动画 */
      var d = state.qc.generated_at ? new Date(state.qc.generated_at) : null;
      if (d && !isNaN(d)) el.textContent = hhmmss(d);
    }, 1000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
