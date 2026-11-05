/* ============================================================================
   team-layout.js —— 团队门户可调布局 P1 MVP（2026-11-03 加；2026-11-04 重做）
   ----------------------------------------------------------------------------
   目标：每个组件/卡片可调 —— 拖动排序、边框手柄缩放、编辑态显隐开关。
     · 区块级：#main 下各大块（band/kpi/views6/maprow/qarow/esc/aux/arch）
       按 data-tl 标识排序 + 显隐 + 高度；
     · 卡片级：所有内部容器统一走 [data-tl-sort] 拖序 —
       #band .qc-grid（data-qc）/ #kpi 各 .qc-grid 内组（data-grp）/
       .qc-group-b 内卡（指纹键）/ #views6 .v6-grid 列（data-gid）/
       .v6-list 行（data-no）/ #ossSlot .oss-grid（href）/ .aux-g ul 行（href）；
     · 持久化：localStorage 主存（键按团队隔离），服务端 /team-layout 做
       团队默认（admin 可保存/重置），本地无值时回落服务端；
     · 只在团队门户生效：SCOPE 为 null 直接返回，上游一行不变；
       只读态零侵入：手柄/描边只在 <html data-team-layout="edit"> 下出现，
       入口收在头像下拉菜单（#userMenuPanel）里，不占页面位置。

   2026-11-04 重做原因（用户反馈“隐藏按钮被遮挡、里面拖不动”）：
     · 遮挡根因有二：① 旧手柄 top:-12px 探出区块外，被编辑态 resize 必需的
       overflow:auto 直接裁掉；② 兄弟区块按 DOM 顺序后 paint 会盖住前一个的
       手柄（z-index 同层）。新版：手柄改 sticky 收进块内右上（随块内滚动吸顶，
       不再被裁）、区块自建层叠上下文 + 悬停提 z-index、标题让位 padding。
       另：原生 resize 要求 overflow 非 visible —— 与“不裁手柄”天然互斥，
       故本版起**弃用原生 resize**，改用手柄上的 ↕ 高度拖柄（JS 改 minHeight），
       区块全程 overflow:visible，手柄永不被裁。
     · 拖不动根因：旧版只给 #band .qc-grid 接了拖拽，#kpi/#views6/#ossSlot/#aux
       全无 handlers，且 <a> 卡一点就跳走（拖后 click 照常触发导航）。
       新版所有内部容器统一走 makeSortable + 拖后 click 压制。

   加载顺序：在 olbr.js 之后（需等 SCOPE 就绪 + 首次 render 完成），故监听
   olbr:scope-ready 后再初始化；同时 DOMContentLoaded 时试一次（矩阵已就绪场景）。
   ========================================================================== */
(function () {
  'use strict';

  var SCOPE = window.OLBR_SCOPE || null;
  if (!SCOPE) return;
  var TEAM = SCOPE.teamId || 'unknown';

  var LS_KEY = 'olbr_team_layout_' + TEAM;
  var EDIT_ATTR = 'data-team-layout';

  /* 区块清单：与 index.html #main 下容器一一对应（complaintSlot 已下线，不纳入）。 */
  var BLOCKS = ['band', 'kpi', 'views6', 'maprow', 'qarow', 'esc', 'aux', 'arch'];

  function mainEl() { return document.getElementById('main'); }

  function blockEl(id) {
    if (id === 'maprow') return document.querySelector('#main > .maprow');
    if (id === 'qarow') return document.querySelector('#main > .qarow');
    return document.getElementById(id);
  }

  /* ------------------------------------------------------------ 存取 ---- */
  function readLocal() {
    try {
      var raw = localStorage.getItem(LS_KEY);
      if (!raw) return null;
      var d = JSON.parse(raw);
      if (!d || typeof d !== 'object') return null;
      return d;
    } catch (e) { return null; }
  }
  function writeLocal(d) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(d)); } catch (e) { /* ignore */ }
  }
  function blankLayout() {
    return {
      order: [], hidden: {}, heights: {},
      qcOrder: [], v6Order: [], v6ItemOrder: {},
      kpiGroupOrder: [], kpiItemOrder: {},
      ossOrder: [], auxOrder: {}
    };
  }

  /* 团队默认的服务端地址：与 team-scope.js 同一规则（见其 scopeApiPaths）。
     团队门户两种访问方式路径前缀不同，直连 vite 是 /api/auth，直经 nginx 是
     /uniplam/api/auth —— 按页面前缀挑，取不到就两条都试。 */
  function layoutApiPaths(team) {
    var p = location.pathname || '';
    var m = /^(.*?)\/v3\//.exec(p);
    var prefix = m ? m[1] : '';
    var paths = [];
    var q = '?team=' + encodeURIComponent(team);
    if (prefix) paths.push(prefix + '/api/auth/team-layout' + q);
    paths.push('/uniplam/api/auth/team-layout' + q);
    paths.push('/api/auth/team-layout' + q);
    return paths;
  }
  function authHeaders() {
    var tk = null;
    try { tk = localStorage.getItem('liberia_noc_auth_v1'); } catch (e) { tk = null; }
    var h = { Accept: 'application/json' };
    if (tk) h.Authorization = 'Bearer ' + tk;
    return h;
  }
  function fetchServerDefault() {
    /* 逐条试候选路径：第一份 2xx 且带 layout 的即用；401/404/网络错就试下一条。
       无 SQLite / 未登录 / 没存过默认 → 全部回 null，前端回落本地（不算错）。 */
    var paths = layoutApiPaths(TEAM);
    var i = 0;
    function attempt() {
      if (i >= paths.length) return Promise.resolve(null);
      var url = paths[i++];
      return fetch(url, { credentials: 'same-origin', headers: authHeaders() })
        .then(function (r) { return r.ok ? r.json().catch(function () { return null; }) : null; })
        .catch(function () { return null; })
        .then(function (d) {
          if (d && d.layout && typeof d.layout === 'object') return d.layout;
          return attempt();
        });
    }
    return attempt();
  }
  /* POST 地址与 GET 同源：优先当前页前缀，其次两条兜底（直连 dev 时第一条即中）。 */
  function layoutPostPaths() {
    var p = location.pathname || '';
    var m = /^(.*?)\/v3\//.exec(p);
    var prefix = m ? m[1] : '';
    var paths = [];
    if (prefix) paths.push(prefix + '/api/auth/team-layout');
    paths.push('/uniplam/api/auth/team-layout');
    paths.push('/api/auth/team-layout');
    return paths;
  }

  /* ------------------------------------------------------------ 应用 ---- */
  function applyLayout(d) {
    if (!d) return;
    var main = mainEl();
    if (!main) return;
    /* 1) 排序：按 order 数组把区块依次 append（不在数组里的保持原相对顺序缀后）。
       ⚠️ 用 placeChildren（幂等）而不是无条件 appendChild：
       无条件 append 每次都改 DOM → 触发 #main 的 MutationObserver →
       观察器回调又调 applyLayout → 死循环式重排；
       拖拽期间更致命：节点被移走 → 浏览器取消拖拽（用户报「拖动也无效」）。 */
    if (Array.isArray(d.order) && d.order.length) {
      var kids = Array.prototype.slice.call(main.children);
      var byId = {}, out = [], used = {};
      kids.forEach(function (c) {
        var id = c.getAttribute && c.getAttribute('data-tl');
        if (id && BLOCKS.indexOf(id) !== -1 && !byId[id]) byId[id] = c;
      });
      d.order.forEach(function (id) {
        if (byId[id] && !used[id]) { used[id] = 1; out.push(byId[id]); }
      });
      kids.forEach(function (c) { if (out.indexOf(c) === -1) out.push(c); });
      placeChildren(main, out);
    }
    /* 2) 显隐：用户级隐藏走 style.display，不碰 hidden（那是矩阵的语义）。
       另挂 data-tl-off 供 CSS 的对侧铺满判断 —— 矩阵隐藏走 [hidden] 属性，
       布局隐藏走 display:none，CSS 的 :has([hidden]) 看不见后者，
       否则用户藏掉一侧后另一侧不会拉满（2026-11-03 复查抓到）。 */
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (!el) return;
      if (d.hidden && d.hidden[id]) { el.style.display = 'none'; el.setAttribute('data-tl-off', '1'); }
      else { el.style.display = ''; el.removeAttribute('data-tl-off'); }
    });
    /* 3) 高度：纵向缩放持久化（本版起由 ↕ 拖柄写 minHeight）。 */
    if (d.heights) {
      Object.keys(d.heights).forEach(function (id) {
        var el = blockEl(id);
        var h = parseInt(d.heights[id], 10);
        if (el && h >= 80 && h <= 3000) el.style.minHeight = h + 'px';
      });
    }
    /* 4) 内部条目排序：各 apply 自带“容器/条目缺失就跳过”，重渲染后由
       MutationObserver 再次重排（见 wireMainObserver），这里先排一次。 */
    applyQcOrder(d.qcOrder);
    applyV6Order(d.v6Order);
    applyV6ItemOrder(d.v6ItemOrder);
    applyKpiGroupOrder(d.kpiGroupOrder);
    applyKpiItemOrder(d.kpiItemOrder);
    applyOssOrder(d.ossOrder);
    applyAuxOrder(d.auxOrder);
  }

  function currentLayout() {
    var d = readLocal() || blankLayout();
    if (!Array.isArray(d.order)) d.order = [];
    if (!d.hidden || typeof d.hidden !== 'object') d.hidden = {};
    if (!d.heights || typeof d.heights !== 'object') d.heights = {};
    if (!Array.isArray(d.qcOrder)) d.qcOrder = [];
    if (!Array.isArray(d.v6Order)) d.v6Order = [];
    if (!d.v6ItemOrder || typeof d.v6ItemOrder !== 'object') d.v6ItemOrder = {};
    if (!Array.isArray(d.kpiGroupOrder)) d.kpiGroupOrder = [];
    if (!d.kpiItemOrder || typeof d.kpiItemOrder !== 'object') d.kpiItemOrder = {};
    if (!Array.isArray(d.ossOrder)) d.ossOrder = [];
    if (!d.auxOrder || typeof d.auxOrder !== 'object') d.auxOrder = {};
    return d;
  }
  function saveLayout(d) {
    writeLocal(d);
    /* 本地为主；服务端默认由管理员显式“设为团队默认”时才写（见工具条）。 */
  }

  /* ---- 通用：按 key 数组重排容器子节点 ----
     ⚠️ placeChildren 是**幂等**的：只有顺序真的不对时才动 DOM。
     这不是洁癖 —— #main 上挂了 MutationObserver（重排 DOM 会触发它），
     若每次都无条件 appendChild，DOM 永远在变 → 观察器永远在触发 →
     每 80ms 重排一次 → 用户拖到一半节点被移走，浏览器直接取消这次拖拽。
     「拖不动」的第二根因就在这里。 */
  function placeChildren(parent, els) {
    if (!parent || !els || !els.length) return;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var cur = parent.children[i];
      if (cur !== el) parent.insertBefore(el, cur || null);
    }
  }
  function reorderByKeys(container, keys, keyOf) {
    if (!container || !Array.isArray(keys) || !keys.length) return;
    var kids = Array.prototype.slice.call(container.children);
    var byId = {};
    kids.forEach(function (c) {
      var k = keyOf(c);
      if (k) byId[k] = c;
    });
    /* 目标序列 = keys 命中的（去重保序）+ 没命中的按原相对顺序缀后。 */
    var out = [], used = {};
    keys.forEach(function (k) {
      if (byId[k] && !used[k]) { used[k] = 1; out.push(byId[k]); }
    });
    kids.forEach(function (c) { if (out.indexOf(c) === -1) out.push(c); });
    placeChildren(container, out);
  }
  function collectKeys(container, keyOf) {
    var out = [];
    if (!container) return out;
    Array.prototype.forEach.call(container.children, function (c) {
      var k = keyOf(c);
      if (k) out.push(k);
    });
    return out;
  }
  function attrKey(attr) {
    return function (el) {
      if (!el || !el.getAttribute) return null;
      return el.getAttribute(attr) || null;
    };
  }

  /* ---- #band QC 卡（键 data-qc，稳定 id） ---- */
  function applyQcOrder(order) {
    reorderByKeys(document.querySelector('#band .qc-grid'), order, attrKey('data-qc'));
  }
  function collectQcOrder() {
    return collectKeys(document.querySelector('#band .qc-grid'), attrKey('data-qc'));
  }

  /* ---- #views6 列（键 data-gid，如 "FO View"，含空格故不做字符集限制） ---- */
  function v6GridEl() { return document.querySelector('#views6 .v6-grid'); }
  function applyV6Order(order) {
    reorderByKeys(v6GridEl(), order, attrKey('data-gid'));
  }
  function collectV6Order() {
    return collectKeys(v6GridEl(), attrKey('data-gid'));
  }
  /* ---- #views6 列内行（键 data-no，按列分组存） ---- */
  function v6ColEl(gid) {
    var grid = v6GridEl();
    if (!grid) return null;
    return grid.querySelector('.v6[data-gid="' + gid + '"]');
  }
  function applyV6ItemOrder(dict) {
    if (!dict || typeof dict !== 'object') return;
    Object.keys(dict).forEach(function (gid) {
      var col = null;
      try { col = v6GridEl().querySelector('.v6[data-gid="' + CSS.escape(gid) + '"]'); }
      catch (e) {
        /* CSS.escape 在极老内核缺失时退回遍历比对。 */
        Array.prototype.forEach.call((v6GridEl() || { children: [] }).children, function (c) {
          if (c.getAttribute && c.getAttribute('data-gid') === gid) col = c;
        });
      }
      if (!col) return;
      var list = col.querySelector('.v6-list');
      reorderByKeys(list, dict[gid], attrKey('data-no'));
    });
  }
  function collectV6ItemOrder() {
    var out = {};
    var grid = v6GridEl();
    if (!grid) return out;
    Array.prototype.forEach.call(grid.querySelectorAll('.v6[data-gid]'), function (col) {
      var gid = col.getAttribute('data-gid');
      var list = col.querySelector('.v6-list');
      if (!gid || !list) return;
      out[gid] = collectKeys(list, attrKey('data-no'));
    });
    return out;
  }

  /* ---- #kpi 组（键 data-grp；有两个 .qc-grid，各排各的，共用一份全局顺序） ---- */
  function kpiGrids() {
    return document.querySelectorAll('#kpi .qc-grid');
  }
  function applyKpiGroupOrder(order) {
    if (!Array.isArray(order) || !order.length) return;
    Array.prototype.forEach.call(kpiGrids(), function (grid) {
      reorderByKeys(grid, order, attrKey('data-grp'));
    });
  }
  function collectKpiGroupOrder() {
    var out = [], seen = {};
    Array.prototype.forEach.call(kpiGrids(), function (grid) {
      Array.prototype.forEach.call(grid.children, function (c) {
        var k = c.getAttribute && c.getAttribute('data-grp');
        if (k && !seen[k]) { seen[k] = 1; out.push(k); }
      });
    });
    return out;
  }
  /* ---- #kpi 组内卡：无稳定 id，用“href + 卡名”指纹做键 ----
     富卡片/可用率/benchmark 卡渲染成 <a>/<div> 均无 data-* id，
     唯一稳定的是“去哪 + 是哪张卡”。href 区分页面，卡名区分同组内。
     文本取卡名节点（.qc-ttl b / .bf-hd b / .qc-name），归一化空白后截断。 */
  function kpiCardKey(card) {
    if (!card) return null;
    var href = card.getAttribute ? (card.getAttribute('href') || '') : '';
    var nm = '';
    var n = card.querySelector ? card.querySelector('.qc-ttl b, .bf-hd b, .qc-name') : null;
    nm = n ? (n.textContent || '') : (card.getAttribute('title') || card.textContent || '');
    nm = String(nm).replace(/\s+/g, ' ').trim().slice(0, 60);
    var key = (href ? href + '#' : 't#') + nm;
    return key.slice(0, 300) || null;
  }
  function applyKpiItemOrder(dict) {
    if (!dict || typeof dict !== 'object') return;
    Array.prototype.forEach.call(
      document.querySelectorAll('#kpi .qc-group[data-grp]'), function (grp) {
        var gid = grp.getAttribute('data-grp');
        var order = dict[gid];
        if (!gid || !Array.isArray(order) || !order.length) return;
        var body = grp.querySelector('.qc-group-b');
        reorderByKeys(body, order, kpiCardKey);
      });
  }
  function collectKpiItemOrder() {
    var out = {};
    Array.prototype.forEach.call(
      document.querySelectorAll('#kpi .qc-group[data-grp]'), function (grp) {
        var gid = grp.getAttribute('data-grp');
        var body = grp.querySelector('.qc-group-b');
        if (!gid || !body) return;
        out[gid] = collectKeys(body, kpiCardKey);
      });
    return out;
  }

  /* ---- OSS 卡（键 href） ---- */
  function ossGridEl() { return document.querySelector('#ossSlot .oss-grid'); }
  function ossKey(el) {
    if (!el) return null;
    if (el.getAttribute) {
      var h = el.getAttribute('href');
      if (h) return h.slice(0, 500);
    }
    return null;
  }
  function applyOssOrder(order) {
    reorderByKeys(ossGridEl(), order, ossKey);
  }
  function collectOssOrder() {
    return collectKeys(ossGridEl(), ossKey);
  }

  /* ---- 辅助/归档行（键：行内 <a> 的 href；容器按 .aux-g[data-key] 分组） ---- */
  function auxRowKey(li) {
    if (!li) return null;
    var a = li.querySelector ? li.querySelector('a[href]') : null;
    if (!a) return null;
    var h = a.getAttribute('href') || '';
    var t = (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    var key = h ? h.slice(0, 500) : ('t#' + t);
    return key || null;
  }
  function applyAuxOrder(dict) {
    if (!dict || typeof dict !== 'object') return;
    Array.prototype.forEach.call(document.querySelectorAll('.aux-g[data-key]'), function (g) {
      var k = g.getAttribute('data-key');
      var order = dict[k];
      if (!k || !Array.isArray(order) || !order.length) return;
      var ul = g.querySelector('ul');
      reorderByKeys(ul, order, auxRowKey);
    });
  }
  function collectAuxOrder() {
    var out = {};
    Array.prototype.forEach.call(document.querySelectorAll('.aux-g[data-key]'), function (g) {
      var k = g.getAttribute('data-key');
      var ul = g.querySelector('ul');
      if (!k || !ul) return;
      out[k] = collectKeys(ul, auxRowKey);
    });
    return out;
  }

  /* ------------------------------------------------------------ 编辑态 ---- */
  function isEdit() { return document.documentElement.getAttribute(EDIT_ATTR) === 'edit'; }
  function langIsEn() {
    var v = null;
    try { v = localStorage.getItem('olbr.lang'); } catch (e) { v = null; }
    if (v === 'en' || v === 'zh') return v === 'en';
    var nav = (navigator.language || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') !== 0;
  }
  function paintMenuText() {
    var en = langIsEn();
    var edit = document.getElementById('tlEditBtn');
    if (edit) {
      var s = edit.querySelector('span');
      if (s) s.textContent = isEdit() ? (en ? 'Done' : '完成布局') : (en ? 'Customize layout' : '调整布局');
      edit.title = en ? 'Drag to reorder, resize, show/hide blocks' : '拖动排序、缩放、显隐区块';
    }
    var save = document.getElementById('tlSaveBtn');
    if (save) {
      var ss = save.querySelector('span') || save;
      if (ss !== save) ss.textContent = en ? 'Set as team default' : '设为团队默认';
      else save.textContent = en ? 'Set as team default' : '设为团队默认';
    }
    var reset = document.getElementById('tlResetBtn');
    if (reset) {
      var rs = reset.querySelector('span') || reset;
      if (rs !== reset) rs.textContent = en ? 'Reset layout' : '重置布局';
      else reset.textContent = en ? 'Reset layout' : '重置布局';
    }
  }
  function closeViaOlbr() {
    /* olbr.js 的菜单开合态记在它闭包里的 state.userMenuOpen，直接改 DOM 会
       与它失配（下次点头像要连点两下）。这里伪造一次“点到菜单外面”的
       mousedown，走它自己的 document 监听去关，状态与 DOM 一次对齐。 */
    try {
      var ev = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
      document.dispatchEvent(ev);
    } catch (e) {
      closeUserMenuFallback();
    }
  }
  function closeUserMenuFallback() {
    var panel = document.getElementById('userMenuPanel');
    var menu = document.getElementById('userMenu');
    var trig = document.getElementById('userMenuBtn');
    if (panel) panel.hidden = true;
    if (trig) trig.setAttribute('aria-expanded', 'false');
    if (menu) menu.classList.remove('is-open');
  }

  /* 拖后 click 压制：HTML5 DnD 拖完 <a> 会照常触发 click → 新标签跳走。
     dragend 后 350ms 内，捕获阶段拦掉 [data-tl-sort] 内的 <a> 点击。 */
  var suppressClickUntil = 0;
  document.addEventListener('click', function (e) {
    if (Date.now() > suppressClickUntil) return;
    var a = e.target && e.target.closest ? e.target.closest('[data-tl-sort] a[href]') : null;
    if (a) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  function setDraggableForItems(on) {
    var sels = [
      '#band .qc-grid .qc-card',
      '#kpi .qc-grid > .qc-group',
      '#kpi .qc-group-b > .qc-card',
      '#views6 .v6-grid > .v6',
      '#views6 .v6-list > .v6-row',
      '#ossSlot .oss-grid > .oss-card',
      '.aux-g ul > li'
    ];
    sels.forEach(function (sel) {
      Array.prototype.forEach.call(document.querySelectorAll(sel), function (el) {
        if (on) el.setAttribute('draggable', 'true');
        else el.removeAttribute('draggable');
      });
    });
  }
  function applyEditSideEffects(on) {
    if (on) {
      ensureHandles();
      wireNewSortables();
      setDraggableForItems(true);
    } else {
      setDraggableForItems(false);
      clearAllDropMarks();
    }
  }
  function setEdit(on) {
    if (on) document.documentElement.setAttribute(EDIT_ATTR, 'edit');
    else document.documentElement.removeAttribute(EDIT_ATTR);
    var btn = document.getElementById('tlEditBtn');
    if (btn) btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    applyEditSideEffects(on);
    syncEditVisibility();
    paintMenuText();
  }

  /* ------------------------------------------------------------ 区块手柄 ---- */
  function ensureHandles() {
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (!el || el.querySelector(':scope > .tl-handle')) return;
      el.setAttribute('data-tl', id);
      var h = document.createElement('div');
      h.className = 'tl-handle';
      h.innerHTML = '<span class="tl-grip" title="拖动排序">⠿</span>' +
        '<span class="tl-name">' + id + '</span>' +
        '<button type="button" data-tl-hide="' + id + '" title="显示 / 隐藏">显隐</button>' +
        '<span class="tl-size" title="拖动调整高度">↕</span>';
      /* ⚠️ 手柄必须**绝对定位**，不能当普通流内子节点：
         .maprow / .qarow / .aux 都是 display:grid，手柄若留在流里，
         它就是栅格的第 3 个 grid item —— 整行被撑成三列，页面全乱
         （2026-11-04 用户报「编辑模式下页面全乱」）。
         绝对定位后它脱流，不再参与栅格/弹性布局，只浮在块内右上角。 */
      el.insertBefore(h, el.firstChild);
      /* 区块拖拽：手柄 draggable，整块为落点。 */
      var grip = h.querySelector('.tl-grip');
      grip.setAttribute('draggable', 'true');
      grip.addEventListener('dragstart', function (e) {
        el.classList.add('is-tl-drag');
        try { e.dataTransfer.setData('text/tl-block', id); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* ignore */ }
      });
      grip.addEventListener('dragend', function () {
        el.classList.remove('is-tl-drag');
        clearDropMarks();
      });
      el.addEventListener('dragover', function (e) {
        if (!isEdit()) return;
        var dt = e.dataTransfer && e.dataTransfer.types;
        var ok = false;
        try { ok = dt && Array.prototype.indexOf.call(dt, 'text/tl-block') !== -1; } catch (x) { ok = true; }
        if (!ok) return;
        e.preventDefault();
        var r = el.getBoundingClientRect();
        var before = (e.clientY - r.top) < r.height / 2;
        el.classList.toggle('is-tl-before', before);
        el.classList.toggle('is-tl-after', !before);
      });
      el.addEventListener('dragleave', function () {
        el.classList.remove('is-tl-before'); el.classList.remove('is-tl-after');
      });
      el.addEventListener('drop', function (e) {
        if (!isEdit()) return;
        var src = null;
        try { src = e.dataTransfer.getData('text/tl-block'); } catch (x) { src = null; }
        if (!src) return;
        e.preventDefault();
        var srcEl = blockEl(src);
        if (!srcEl || srcEl === el) return;
        var r = el.getBoundingClientRect();
        var before = (e.clientY - r.top) < r.height / 2;
        if (before) el.parentNode.insertBefore(srcEl, el);
        else el.parentNode.insertBefore(srcEl, el.nextSibling);
        clearDropMarks();
        persistOrder();
      });
      var hideBtn = h.querySelector('[data-tl-hide]');
      hideBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var d = currentLayout();
        d.hidden = d.hidden || {};
        d.hidden[id] = !d.hidden[id];
        if (!d.hidden[id]) delete d.hidden[id];
        saveLayout(d);
        applyLayout(d);
      });
      wireSizeGrip(h.querySelector('.tl-size'), el, id);
    });
    wireNewSortables();
  }

  /* 高度拖柄：mousedown 起算，mousemove 改 minHeight，mouseup 落盘。
     取代原生 resize —— 原生要求 overflow 非 visible，会把手柄裁掉。 */
  function wireSizeGrip(grip, el, id) {
    if (!grip || grip.getAttribute('data-tl-size') === '1') return;
    grip.setAttribute('data-tl-size', '1');
    grip.addEventListener('mousedown', function (e) {
      if (!isEdit()) return;
      e.preventDefault();
      e.stopPropagation();
      var startY = e.clientY;
      var startH = el.getBoundingClientRect().height;
      function mv(ev) {
        var h = Math.round(startH + (ev.clientY - startY));
        if (h < 80) h = 80;
        if (h > 3000) h = 3000;
        el.style.minHeight = h + 'px';
      }
      function up() {
        document.removeEventListener('mousemove', mv);
        document.removeEventListener('mouseup', up);
        var d = currentLayout();
        d.heights = d.heights || {};
        var h = Math.round(el.getBoundingClientRect().height);
        if (h >= 80 && h <= 3000) { d.heights[id] = h; saveLayout(d); }
      }
      document.addEventListener('mousemove', mv);
      document.addEventListener('mouseup', up);
    });
  }

  function clearDropMarks() {
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (el) { el.classList.remove('is-tl-before'); el.classList.remove('is-tl-after'); }
    });
  }
  function clearAllDropMarks() {
    clearDropMarks();
    Array.prototype.forEach.call(document.querySelectorAll('.is-tl-before-x,.is-tl-after-x,.is-tl-before-y,.is-tl-after-y'), function (el) {
      el.classList.remove('is-tl-before-x'); el.classList.remove('is-tl-after-x');
      el.classList.remove('is-tl-before-y'); el.classList.remove('is-tl-after-y');
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-tl-sort].is-tl-sorting'), function (el) {
      el.classList.remove('is-tl-sorting');
    });
    Array.prototype.forEach.call(document.querySelectorAll('.is-tl-drag'), function (el) {
      el.classList.remove('is-tl-drag');
    });
  }

  function persistOrder() {
    var main = mainEl();
    if (!main) return;
    var order = [];
    Array.prototype.forEach.call(main.children, function (c) {
      var id = c.getAttribute && c.getAttribute('data-tl');
      if (id && BLOCKS.indexOf(id) !== -1) order.push(id);
    });
    var d = currentLayout();
    d.order = order;
    saveLayout(d);
  }

  /* ------------------------------------------------------------ 通用条目拖序 ----
     makeSortable(container, cfg):
       cfg = { axis: 'x'|'y', items: '<selector>', key: fn(el)->string|null,
               onChange: fn() } —— onChange 负责重收全量并 saveLayout。
     同一类多容器（如 #kpi 两个 .qc-grid、多个 .qc-group-b）各自接 handlers，
     onChange 里重收**全部同类**，避免“只存了动的那一个容器”。 */
  function makeSortable(container, cfg) {
    if (!container || container.getAttribute('data-tl-sort') === '1') return;
    container.setAttribute('data-tl-sort', '1');
    container.setAttribute('data-tl-axis', cfg.axis === 'y' ? 'y' : 'x');
    var itemSel = cfg.items, keyFn = cfg.key, onChange = cfg.onChange;
    function itemOf(t) {
      if (!t || !t.closest) return null;
      var it = t.closest(itemSel);
      if (!it || !container.contains(it)) return null;
      return it;
    }
    /* ⚠️ 嵌套容器必须**只认自己这一层**（2026-11-04 用户报「拖动也无效」的根因③）：
       .qc-group（组）套 .qc-group-b（组内卡），.v6（列）套 .v6-list（列内行）。
       若不判定「最近的可拖祖先」，拖组时事件会冒泡到 .qc-group-b，
       内层抢走 drop、把组里的卡重排 —— 用户表现为「怎么拖都不动」。
       办法：找出事件目标最近的、已挂 data-tl-sort 的祖先，若不是自己就放弃
       （让更内层的那层去处理），若是自己（或自己就是最近的）才动手。 */
    function isNearestSortable(t) {
      if (!t || !t.closest) return true;
      var node = t.closest('[data-tl-sort]');
      if (!node) return true;
      return node === container;
    }
    function clearItemMarks() {
      Array.prototype.forEach.call(container.querySelectorAll('.is-tl-before-x,.is-tl-after-x,.is-tl-before-y,.is-tl-after-y'), function (el) {
        el.classList.remove('is-tl-before-x'); el.classList.remove('is-tl-after-x');
        el.classList.remove('is-tl-before-y'); el.classList.remove('is-tl-after-y');
      });
    }
    container.addEventListener('dragstart', function (e) {
      if (!isEdit()) return;
      var it = itemOf(e.target);
      if (!it) return;
      /* 拖的是**内层**条目时，本层不接管（内层自己会 setData）。 */
      if (!isNearestSortable(e.target)) return;
      var k = keyFn(it);
      if (!k) return;
      it.classList.add('is-tl-drag');
      container.classList.add('is-tl-sorting');
      try {
        e.dataTransfer.setData('text/tl-item', k);
        e.dataTransfer.effectAllowed = 'move';
      } catch (x) { /* ignore */ }
      /* 同一容器内拖动时，Firefox 要求 dragover 必须 preventDefault，
         这里先占位，真正逻辑在 dragover。 */
    });
    container.addEventListener('dragend', function (e) {
      var it = itemOf(e.target);
      if (it) it.classList.remove('is-tl-drag');
      container.classList.remove('is-tl-sorting');
      clearItemMarks();
      suppressClickUntil = Date.now() + 350;
    });
    container.addEventListener('dragover', function (e) {
      if (!isEdit()) return;
      /* 区块级拖拽（text/tl-block）路过内部容器时不拦截，交还给区块落点。 */
      var dt = e.dataTransfer && e.dataTransfer.types;
      var isBlock = false;
      try { isBlock = dt && Array.prototype.indexOf.call(dt, 'text/tl-block') !== -1; } catch (x) { isBlock = false; }
      if (isBlock) return;
      /* 非最近层不拦截（否则内层容器的 dragover 不触发，拖拽被吞）。 */
      if (!isNearestSortable(e.target)) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = 'move'; } catch (x) { /* ignore */ }
      var tgt = itemOf(e.target);
      /* 落到容器空白处（尾部）：清掉旧标记，等 drop 时直接 append。 */
      if (!tgt) { clearItemMarks(); return; }
      var drag = container.querySelector('.is-tl-drag');
      if (drag === tgt) return;
      var r = tgt.getBoundingClientRect();
      var before;
      if (cfg.axis === 'y') before = (e.clientY - r.top) < r.height / 2;
      else before = (e.clientX - r.left) < r.width / 2;
      tgt.classList.toggle(cfg.axis === 'y' ? 'is-tl-before-y' : 'is-tl-before-x', before);
      tgt.classList.toggle(cfg.axis === 'y' ? 'is-tl-after-y' : 'is-tl-after-x', !before);
    });
    container.addEventListener('dragleave', function (e) {
      if (!isEdit()) return;
      /* 离开容器才清（子元素间移动不闪）。 */
      if (e.relatedTarget && container.contains(e.relatedTarget)) return;
      clearItemMarks();
    });
    container.addEventListener('drop', function (e) {
      if (!isEdit()) return;
      var dt = e.dataTransfer && e.dataTransfer.types;
      var isBlock = false;
      try { isBlock = dt && Array.prototype.indexOf.call(dt, 'text/tl-block') !== -1; } catch (x) { isBlock = false; }
      if (isBlock) return;
      /* 非最近层不接管 drop（内层容器先处理，见 isNearestSortable 的说明）。 */
      if (!isNearestSortable(e.target)) return;
      e.preventDefault();
      var srcKey = null;
      try { srcKey = e.dataTransfer.getData('text/tl-item'); } catch (x) { srcKey = null; }
      var tgt = itemOf(e.target);
      /* ⚠️ 落点方向必须**在清标记之前**读出来（2026-11-04 修）：
         标记类（is-tl-before-x / is-tl-after-x）是 dragover 阶段落下的提示，
         原代码先 clearItemMarks() 再去读这个类 → 永远读不到 → 每次都退回
         坐标判定；坐标在部分内核不可靠，于是「拖到哪都不动」。
         现在先取出方向，再清标记。 */
      var markBefore = null;
      if (tgt) {
        if (tgt.classList.contains('is-tl-before-x') || tgt.classList.contains('is-tl-before-y')) markBefore = true;
        else if (tgt.classList.contains('is-tl-after-x') || tgt.classList.contains('is-tl-after-y')) markBefore = false;
      }
      clearItemMarks();
      container.classList.remove('is-tl-sorting');
      suppressClickUntil = Date.now() + 350;
      if (!srcKey) return;
      /* 按 key 找回源节点（拖出容器再拖回也能认）。 */
      var src = null;
      Array.prototype.forEach.call(container.querySelectorAll(itemSel), function (c) {
        if (!src && keyFn(c) === srcKey) src = c;
      });
      if (!src) return;
      if (!tgt) { container.appendChild(src); }
      else {
        if (src === tgt) return;
        var r = tgt.getBoundingClientRect();
        var before;
        /* 优先用 dragover 阶段落下的标记类；没有才退回坐标判定。 */
        if (markBefore !== null) before = markBefore;
        else if (cfg.axis === 'y') before = (e.clientY - r.top) < r.height / 2;
        else before = (e.clientX - r.left) < r.width / 2;
        if (before) container.insertBefore(src, tgt);
        else container.insertBefore(src, tgt.nextSibling);
      }
      try { onChange(); } catch (x) { /* ignore */ }
    });
  }

  function saveAllItemOrders() {
    var d = currentLayout();
    d.qcOrder = collectQcOrder();
    d.v6Order = collectV6Order();
    d.v6ItemOrder = collectV6ItemOrder();
    d.kpiGroupOrder = collectKpiGroupOrder();
    d.kpiItemOrder = collectKpiItemOrder();
    d.ossOrder = collectOssOrder();
    d.auxOrder = collectAuxOrder();
    saveLayout(d);
  }

  /* 扫描所有内部容器，未接线的接上（渲染重建后新节点自动接入）。 */
  function wireNewSortables() {
    var band = document.querySelector('#band .qc-grid');
    if (band) makeSortable(band, {
      axis: 'x', items: '.qc-card', key: attrKey('data-qc'),
      onChange: function () { var d = currentLayout(); d.qcOrder = collectQcOrder(); saveLayout(d); }
    });
    Array.prototype.forEach.call(document.querySelectorAll('#kpi .qc-grid'), function (grid) {
      makeSortable(grid, {
        axis: 'x', items: '.qc-group', key: attrKey('data-grp'),
        onChange: function () { var d = currentLayout(); d.kpiGroupOrder = collectKpiGroupOrder(); saveLayout(d); }
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('#kpi .qc-group-b'), function (body) {
      makeSortable(body, {
        axis: 'x', items: '.qc-card', key: kpiCardKey,
        onChange: function () { var d = currentLayout(); d.kpiItemOrder = collectKpiItemOrder(); saveLayout(d); }
      });
    });
    var vg = v6GridEl();
    if (vg) makeSortable(vg, {
      axis: 'x', items: '.v6', key: attrKey('data-gid'),
      onChange: function () { var d = currentLayout(); d.v6Order = collectV6Order(); saveLayout(d); }
    });
    Array.prototype.forEach.call(document.querySelectorAll('#views6 .v6-list'), function (list) {
      makeSortable(list, {
        axis: 'y', items: '.v6-row', key: attrKey('data-no'),
        onChange: function () { var d = currentLayout(); d.v6ItemOrder = collectV6ItemOrder(); saveLayout(d); }
      });
    });
    var og = ossGridEl();
    if (og) makeSortable(og, {
      axis: 'x', items: '.oss-card', key: ossKey,
      onChange: function () { var d = currentLayout(); d.ossOrder = collectOssOrder(); saveLayout(d); }
    });
    Array.prototype.forEach.call(document.querySelectorAll('.aux-g ul'), function (ul) {
      makeSortable(ul, {
        axis: 'y', items: 'li', key: auxRowKey,
        onChange: function () { var d = currentLayout(); d.auxOrder = collectAuxOrder(); saveLayout(d); }
      });
    });
  }

  /* 主观察器：olbr.js 每次 render 会重建内部 DOM（innerHTML），接线与顺序同丢。
     这里防抖重接 + 重排；编辑态下顺手补 draggable，只读态下只重排（不挂 draggable）。

     ⚠️ **拖拽期间必须完全停手**（2026-11-04 用户报「拖动也无效」）：
     拖拽过程中若重排 DOM，节点被移走 → 浏览器判定拖拽目标失效 → 直接取消，
     用户表现为「怎么拖都拖不动」。观察器照常触发，但回调里看到
     isDragging 为真就**什么都不做**（连 draggable 都不补），拖完再统一补。 */
  var mainObsTimer = 0;
  var isDragging = false;
  function wireMainObserver() {
    var main = mainEl();
    if (!main || main.getAttribute('data-tl-obs') === '1') return;
    main.setAttribute('data-tl-obs', '1');
    try {
      new MutationObserver(function () {
        if (isDragging) return;            /* 拖拽中不动 DOM（见上） */
        if (mainObsTimer) return;
        mainObsTimer = setTimeout(function () {
          mainObsTimer = 0;
          if (isDragging) return;
          wireNewSortables();
          var d = readLocal();
          if (d) applyLayout(d);
          if (isEdit()) setDraggableForItems(true);
        }, 120);
      }).observe(main, { childList: true, subtree: true });
    } catch (e) { /* ignore */ }
  }
  /* 拖拽起止标志：拖动中禁止一切 DOM 重排。 */
  document.addEventListener('dragstart', function () {
    isDragging = true;
  }, true);
  document.addEventListener('dragend', function () {
    isDragging = false;
    /* 拖完立刻把顺序收进 localStorage（拖拽期间观察器停了，落盘得手动做）。 */
    try { saveAllItemOrders(); } catch (e) { /* ignore */ }
    /* 拖完再补一次 draggable 与重排（拖拽期间欠下的）。 */
    setTimeout(function () {
      wireNewSortables();
      var d = readLocal();
      if (d) applyLayout(d);
      if (isEdit()) setDraggableForItems(true);
    }, 60);
  }, true);

  /* ------------------------------------------------------------ 头像菜单入口 ---- */
  /* 调整布局入口放在头像下拉菜单里（2026-11-03 改）：右下角悬浮条常年占位、
     与问答助手/回顶按钮抢右下角，且与「编辑分组」同类（都是改页面结构的操作），
     就该跟它待在一起。菜单内共三项：调整布局/完成（常驻）＋ 设为团队默认 /
     重置（仅编辑态可见）。 */
  function ensureMenuItems() {
    var old = document.getElementById('teamLayoutBar');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    if (document.getElementById('tlEditBtn')) { syncEditVisibility(); paintMenuText(); return true; }
    var panel = document.getElementById('userMenuPanel');
    if (!panel) return false;
    var anchor = panel.querySelector('.mp-user-divider') || document.getElementById('logoutBtn');
    function mkBtn(id, icon, act) {
      var b = document.createElement('button');
      b.type = 'button';
      b.id = id;
      b.className = 'btn-ghost mp-user-action';
      b.setAttribute('role', 'menuitem');
      b.setAttribute('data-act', act);
      b.innerHTML = '<i class="ph ' + icon + '" aria-hidden="true"></i><span></span>';
      return b;
    }
    var edit = mkBtn('tlEditBtn', 'ph-sliders-horizontal', 'tl-edit');
    var save = mkBtn('tlSaveBtn', 'ph-users-three', 'tl-save');
    var reset = mkBtn('tlResetBtn', 'ph-arrow-counter-clockwise', 'tl-reset');
    save.hidden = true;
    reset.hidden = true;
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(edit, anchor);
    else panel.appendChild(edit);
    panel.insertBefore(save, edit.nextSibling);
    panel.insertBefore(reset, save.nextSibling);
    edit.addEventListener('click', function () {
      var on = !isEdit();
      setEdit(on);
      closeViaOlbr();
    });
    save.addEventListener('click', function (ev) {
      ev.stopPropagation();
      saveAsTeamDefault(save);
    });
    reset.addEventListener('click', function (ev) {
      ev.stopPropagation();
      resetToTeamDefault();
    });
    syncEditVisibility();
    paintMenuText();
    return true;
  }
  function syncEditVisibility() {
    var on = isEdit();
    var save = document.getElementById('tlSaveBtn');
    var reset = document.getElementById('tlResetBtn');
    if (save) save.hidden = !on;
    if (reset) reset.hidden = !on;
  }
  function saveAsTeamDefault(btn) {
    var d = currentLayout();
    /* 把当前 DOM 顺序/显隐/高度一次性收敛进要保存的布局。 */
    persistOrderInto(d);
    var posts = layoutPostPaths();
    var pi = 0;
    var body = JSON.stringify({ team: TEAM, layout: d });
    var postHeaders = authHeaders();
    postHeaders['Content-Type'] = 'application/json';
    function postAttempt() {
      if (pi >= posts.length) return Promise.resolve({ ok: false });
      var u = posts[pi++];
      return fetch(u, {
        method: 'POST', credentials: 'same-origin',
        headers: postHeaders,
        body: body
      }).then(function (r) {
        /* 404 = 路径前缀不对 → 试下一条；401/403 = 鉴权问题 → 直接交回（重试无意义）。 */
        if (r.status === 404) return postAttempt();
        return r.json().catch(function () { return { ok: r.ok }; });
      }).catch(function () { return postAttempt(); });
    }
    postAttempt()
      .then(function (j) {
        var en = langIsEn();
        var label = (j && (j.ok || j.saved))
          ? (en ? 'Saved' : '已保存')
          : (en ? 'Save failed (admin only)' : '保存失败（需管理员）');
        flashBtnText(btn, label, 2000);
      }).catch(function () { /* ignore */ });
  }
  function flashBtnText(btn, text, ms) {
    if (!btn) return;
    var s = btn.querySelector('span') || btn;
    var prev = s.textContent;
    s.textContent = text;
    setTimeout(function () { paintMenuText(); if ((s.textContent || '') === text) s.textContent = prev; }, ms || 2000);
  }
  function resetToTeamDefault() {
    try { localStorage.removeItem(LS_KEY); } catch (e) { /* ignore */ }
    fetchServerDefault().then(function (srv) {
      BLOCKS.forEach(function (id) {
        var el = blockEl(id);
        if (el) { el.style.display = ''; el.style.minHeight = ''; el.removeAttribute('data-tl-off'); }
      });
      if (srv) applyLayout(srv);
      location.reload();
    });
  }

  function persistOrderInto(d) {
    var main = mainEl();
    if (main) {
      var order = [];
      Array.prototype.forEach.call(main.children, function (c) {
        var id = c.getAttribute && c.getAttribute('data-tl');
        if (id && BLOCKS.indexOf(id) !== -1) order.push(id);
      });
      if (order.length) d.order = order;
    }
    d.hidden = d.hidden || {};
    d.heights = d.heights || {};
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (!el) return;
      if (el.style.display === 'none') d.hidden[id] = true;
      var h = parseInt(el.style.minHeight, 10) || 0;
      if (h >= 80) d.heights[id] = h;
    });
    d.qcOrder = collectQcOrder();
    d.v6Order = collectV6Order();
    d.v6ItemOrder = collectV6ItemOrder();
    d.kpiGroupOrder = collectKpiGroupOrder();
    d.kpiItemOrder = collectKpiItemOrder();
    d.ossOrder = collectOssOrder();
    d.auxOrder = collectAuxOrder();
    saveLayout(d);
    return d;
  }

  /* ------------------------------------------------------------ 启动 ---- */
  function boot() {
    /* 头像菜单挂载可能晚于本脚本（olbr.js render 后才有面板内容），
       挂不上就隔 500ms 再试，最多 10 次；挂上后顺带跟随语言切换重绘文案。 */
    var tries = 0;
    function tryMount() {
      if (ensureMenuItems()) return;
      if (++tries < 10) setTimeout(tryMount, 500);
    }
    tryMount();
    wireMainObserver();
    wireNewSortables();
    try {
      new MutationObserver(function () { paintMenuText(); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    } catch (e) { /* ignore */ }
    var local = readLocal();
    if (local) { applyLayout(local); return; }
    fetchServerDefault().then(function (srv) {
      if (srv) { applyLayout(srv); writeLocal(srv); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  /* 矩阵就绪 → 重画后布局重应用（render 会重建 .qc-grid，需重排卡序）。 */
  document.addEventListener('olbr:scope-ready', function () {
    setTimeout(function () {
      var d = readLocal();
      if (d) applyLayout(d);
      ensureHandles();
      wireMainObserver();
      wireNewSortables();
      if (isEdit()) setDraggableForItems(true);
    }, 0);
  });
})();
