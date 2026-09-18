/* viewer.js — MsPortal「看板查看器」外壳
 * 作用：从门户首页点击某个看板（如 MS View 下的报告）后，在新页面左侧提供
 *       「同组其他看板」导航（类似 my_app 的侧边栏），右侧内嵌当前看板。
 * 数据：直接读同目录 assets/data.js 里的 window.MS_PORTAL_DATA（与门户同源）。
 * 内嵌策略：
 *   · my_app 页面（URL 路径以 /myapp/ 开头，无 X-Frame-Options）→ 改写为**同源**
 *     /myapp/?page=xxx 后用 iframe 内嵌。my_app 深链带 ?page= 时自身进入 bare 模式
 *     （隐藏它自己的侧栏/Header），正好只留下本查看器的分组侧栏，不会出现双侧栏。
 *   · FineBI / 外部系统（跨域且返回 X-Frame-Options: SAMEORIGIN）→ 无法内嵌，
 *     点击时改为「在新窗口打开」，并在右侧显示引导面板。
 */
(function () {
  'use strict';

  var PH = {
    'chart-polar': 'ph-chart-polar', 'gauge': 'ph-gauge', 'bell': 'ph-bell', 'map': 'ph-map-trifold',
    'ticket': 'ph-ticket', 'siren': 'ph-siren', 'clock': 'ph-clock', 'chart-line': 'ph-chart-line',
    'link': 'ph-link', 'cpu': 'ph-cpu', 'broadcast': 'ph-broadcast', 'battery': 'ph-battery-charging',
    'package': 'ph-package', 'wrench': 'ph-wrench', 'upload': 'ph-cloud-arrow-up', 'table': 'ph-table',
    'archive': 'ph-archive', 'chat': 'ph-chat-circle-dots', 'book': 'ph-book-open-text', 'gear': 'ph-gear',
    'dashboard': 'ph-squares-four', 'key': 'ph-lock-key', 'warning': 'ph-warning', 'briefcase': 'ph-briefcase',
    'git': 'ph-git-pull-request', 'user': 'ph-user', 'eye': 'ph-eye', 'flame': 'ph-fire',
    'arrow': 'ph-arrow-right', 'arrow-up-right': 'ph-arrow-up-right', 'plus': 'ph-plus',
    'folder': 'ph-folder-open', 'buildings': 'ph-buildings', 'shield': 'ph-shield-check'
  };
  function ico(name, cls) { return '<i class="ph ' + (PH[name] || PH.dashboard) + (cls ? ' ' + cls : '') + '" aria-hidden="true"></i>'; }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var DATA = window.MS_PORTAL_DATA || { items: [], groups: [] };
  var LANG = 'zh';
  try { LANG = localStorage.getItem('msportal.lang.v1') === 'en' ? 'en' : 'zh'; } catch (e) {}

  var PLAT_LABEL = {
    myapp: LANG === 'en' ? 'my_app' : '自研 my_app',
    finebi: LANG === 'en' ? 'FineBI' : 'FineBI 报表',
    external: LANG === 'en' ? 'External' : '外部系统'
  };
  function titleOf(it) { return LANG === 'en' ? (it.titleEn || it.titleZh) : it.titleZh; }
  function descOf(it) { return LANG === 'en' ? (it.descEn || it.descZh) : it.descZh; }

  // ---- 解析入口参数：?no=<itemNo>&gid=<group>（gid 缺省时回退到该看板所属组） ----
  var qs = new URLSearchParams(location.search);
  var startNo = qs.get('no');
  var startGid = qs.get('gid');

  function findItem(no) {
    no = String(no);
    return (DATA.items || []).filter(function (it) { return String(it.no) === no; })[0] || null;
  }
  function groupsOf(it) { return it.groups || []; }
  function groupMeta(gid) {
    return (DATA.groups || []).filter(function (g) { return g.id === gid; })[0] || { id: gid, zh: gid, en: gid };
  }
  function siblingsOf(gid) {
    return (DATA.items || []).filter(function (it) { return groupsOf(it).indexOf(gid) !== -1; })
      .sort(function (a, b) { return (b.clicks || 0) - (a.clicks || 0); });
  }

  // ---- 可内嵌判定：仅 my_app 深链（同源、无 X-Frame-Options）可 iframe ----
  function parseUrl(raw) { try { return new URL(raw, location.href); } catch (e) { return null; } }
  function isEmbeddable(it) {
    var u = parseUrl(it.url);
    return !!(u && u.pathname.indexOf('/myapp/') === 0);
  }
  function embedSrc(it) {
    var u = parseUrl(it.url);
    if (!u) return null;
    // 用当前 origin 拼同源地址：无论门户从 localhost 还是 192.168.100.20 访问都自适应
    return location.origin + u.pathname + (u.search || '');
  }

  /* ---- 主题同步：让内嵌的 my_app 跟着门户的深浅色走（2026-09-18 补） ----
   * 为什么需要：本页只是外壳，右侧真正显示的是 iframe 里的 /myapp/?page=xxx ——
   * 那是**另一个应用**，主题状态与门户完全独立。实测（TMP/diag_viewer_dark.cjs）：
   * 门户切深色后外壳 body 已是 rgb(2,5,12)（vmax 深空蓝），
   * 但 iframe 内 my_app 的 <html data-theme="light">、html 底仍是 rgb(233,238,243)
   * —— 所以整页看起来还是浅色。
   *
   * my_app 的主题机制（读自 /myapp/assets/index-*.js 的打包产物）：
   *   var k = 'myapp-theme';                 // localStorage 键
   *   初始值：localStorage[k] 是 'dark'/'light' 就用它，否则跟随 prefers-color-scheme
   *   变更时：document.documentElement.setAttribute('data-theme', t)
   *          并向它自己的子 iframe postMessage({__type:'myapp-theme', mode:t})
   * 它**没有**监听来自父窗口的主题消息，也没有 URL 参数入口 ——
   * 唯一能从外部驱动的就是 localStorage['myapp-theme']。
   *
   * 门户与 my_app 同源（都在 http://localhost/ 或 http://192.168.100.20/），
   * 所以这里直接写这个键，iframe 下次加载就会以同一主题启动。
   * ⚠️ 这是**跨应用**副作用：写过之后直接打开 /myapp/ 也会是同一主题。
   *    不想要的话，删掉本段和它的 3 处调用即可。 */
  var EMBED_THEME_KEY = 'myapp-theme';
  function portalTheme() {
    try { return localStorage.getItem('msportal.theme.v1') === 'dark' ? 'dark' : 'light'; }
    catch (e) { return 'light'; }
  }
  function syncEmbedTheme() {
    var want = portalTheme();
    try { if (localStorage.getItem(EMBED_THEME_KEY) !== want) localStorage.setItem(EMBED_THEME_KEY, want); }
    catch (e) { /* ignore */ }
    return want;
  }

  // ---- 状态 ----
  var GID = startGid || (findItem(startNo) && groupsOf(findItem(startNo))[0]) || 'MS View';
  var LIST = siblingsOf(GID);
  var current = null;

  // DOM
  var elList = document.getElementById('sbList');
  var elGrpName = document.getElementById('grpName');
  var elGrpSub = document.getElementById('grpSub');
  var elGrpCnt = document.getElementById('grpCnt');
  var elCurTitle = document.getElementById('curTitle');
  var frame = document.getElementById('frame');
  var loading = document.getElementById('loading');
  var placeholder = document.getElementById('placeholder');
  var phTitle = document.getElementById('phTitle');
  var phDesc = document.getElementById('phDesc');
  var phBtn = document.getElementById('phBtn');
  var phBtnTxt = document.getElementById('phBtnTxt');

  var TXT = LANG === 'en'
    ? { back: 'Back to portal', cnt: 'dashboards', ext: 'This board is an external system (FineBI / 3rd party) and cannot be embedded here for security reasons (X-Frame-Options).', open: 'Open in new window', loading: 'Loading…' }
    : { back: '返回门户首页', cnt: '个看板', ext: '该看板属于外部系统（FineBI / 第三方），出于安全策略（X-Frame-Options）无法在本页内嵌显示。', open: '在新窗口打开', loading: '加载中…' };
  document.getElementById('backTxt').textContent = TXT.back;
  phBtnTxt.textContent = TXT.open;
  loading.innerHTML = '<i class="ph ph-circle-notch" aria-hidden="true" style="margin-right:8px"></i>' + esc(TXT.loading);

  function renderHead() {
    var m = groupMeta(GID);
    elGrpName.textContent = LANG === 'en' ? (m.en || m.id) : (m.zh || m.id);
    elGrpSub.textContent = LANG === 'en' ? (m.subEn || '') : (m.subZh || '');
    elGrpCnt.textContent = LIST.length + ' ' + TXT.cnt;
    document.title = (LANG === 'en' ? (m.en || m.id) : (m.zh || m.id)) + ' · MS Portal';
  }

  function renderList() {
    var curNo = current ? String(current.no) : '';
    elList.innerHTML = LIST.map(function (it) {
      var active = String(it.no) === curNo;
      var ext = isEmbeddable(it) ? '' : '<span class="ext">' + ico('arrow-up-right') + '</span>';
      return '<a class="sb-item' + (active ? ' active' : '') + '" data-no="' + esc(it.no) + '" href="#" title="' + esc(titleOf(it)) + '">' +
        '<span class="ic">' + ico(it.icon) + '</span>' +
        '<span class="tx"><span class="tt">' + esc(titleOf(it)) + '</span>' +
        '<span class="pl">' + esc(PLAT_LABEL[it.platform] || it.platform || '') + '</span></span>' +
        ext + '</a>';
    }).join('');
  }

  function showEmbed(it) {
    placeholder.classList.remove('show');
    loading.style.display = 'flex';
    frame.style.visibility = 'visible';
    syncEmbedTheme();   // 必须在赋 src 之前：my_app 只在启动时读一次 localStorage
    frame.src = embedSrc(it);
  }
  function showExternal(it) {
    frame.style.visibility = 'hidden';
    frame.src = 'about:blank';
    loading.style.display = 'none';
    phTitle.textContent = titleOf(it);
    phDesc.textContent = TXT.ext;
    phBtn.href = it.url;
    placeholder.classList.add('show');
  }

  function select(it, push) {
    if (!it) return;
    current = it;
    elCurTitle.textContent = titleOf(it);
    if (isEmbeddable(it)) showEmbed(it); else showExternal(it);
    renderList();
    if (push !== false) {
      try { history.replaceState({ no: it.no }, '', 'viewer.html?gid=' + encodeURIComponent(GID) + '&no=' + encodeURIComponent(it.no)); } catch (e) {}
    }
  }

  // ---- 事件 ----
  elList.addEventListener('click', function (e) {
    var a = e.target.closest('.sb-item');
    if (!a) return;
    e.preventDefault();
    var it = findItem(a.getAttribute('data-no'));
    if (!it) return;
    if (!isEmbeddable(it)) {
      // 外部系统：直接新窗口打开（用户手势，弹窗不被拦截），当前内嵌视图保持不变
      window.open(it.url, '_blank', 'noopener');
      current = it; elCurTitle.textContent = titleOf(it); renderList();
      return;
    }
    select(it);
  });

  frame.addEventListener('load', function () {
    if (frame.getAttribute('src') === 'about:blank') return;
    loading.style.display = 'none';
  });

  document.getElementById('toggleSb').addEventListener('click', function () {
    document.body.classList.toggle('sb-collapsed');
  });
  document.getElementById('reloadBtn').addEventListener('click', function () {
    if (current && isEmbeddable(current)) { loading.style.display = 'flex'; syncEmbedTheme(); try { frame.contentWindow.location.reload(); } catch (e) { frame.src = embedSrc(current); } }
    else if (current) { window.open(current.url, '_blank', 'noopener'); }
  });
  document.getElementById('openBtn').addEventListener('click', function () {
    if (current) window.open(current.url, '_blank', 'noopener');
  });

  /* 门户在**另一个标签页**切了主题 → 本页外壳和内嵌看板一起跟着切。
     （storage 事件只在「别的文档」改动 localStorage 时触发，所以不会自激。） */
  window.addEventListener('storage', function (e) {
    if (e.key !== 'msportal.theme.v1') return;
    var want = syncEmbedTheme();
    document.documentElement.classList.toggle('dark', want === 'dark');
    if (!current || !isEmbeddable(current)) return;
    loading.style.display = 'flex';
    try { frame.contentWindow.location.reload(); } catch (err) { frame.src = embedSrc(current); }
  });

  // ---- 初始化：定位当前看板（no 缺省或不属于本组时，取本组第一个） ----
  renderHead();
  var init = findItem(startNo);
  if (!init || groupsOf(init).indexOf(GID) === -1) init = LIST[0] || null;
  if (!init) {
    elCurTitle.textContent = '(no dashboards)';
  } else {
    select(init, false);
  }
})();
