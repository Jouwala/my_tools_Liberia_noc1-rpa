/* ============================================================================
   team-layout.js —— 团队门户可调布局 P1 MVP（2026-11-03 加）
   ----------------------------------------------------------------------------
   目标：每个组件/卡片可调 —— 拖动排序、边框手柄缩放、编辑态显隐开关。
     · 区块级：#main 下各大块（band/kpi/views6/maprow/qarow/esc/aux/arch）
       按 data-tl 标识排序 + 显隐 + 高度；
     · 卡片级：#band .qc-grid 内 QC 卡拖序（按 data-qc），MutationObserver 在
       重渲染后重排；
     · 持久化：localStorage 主存（键按团队隔离），服务端 /team-layout 做
       团队默认（admin 可保存/重置），本地无值时回落服务端；
     · 只在团队门户生效：SCOPE 为 null 直接返回，上游一行不变；
       只读态零侵入：手柄/描边/工具条只在 <html data-team-layout="edit"> 下出现。

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
  function blankLayout() { return { order: [], hidden: {}, heights: {}, qcOrder: [] }; }

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
    /* 1) 排序：按 order 数组把区块依次 append（不在数组里的保持原相对顺序缀后）。 */
    if (Array.isArray(d.order) && d.order.length) {
      d.order.forEach(function (id) {
        var el = blockEl(id);
        if (el && el.parentNode === main) main.appendChild(el);
      });
    }
    /* 2) 显隐：用户级隐藏走 style.display，不碰 hidden（那是矩阵的语义）。 */
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (!el) return;
      if (d.hidden && d.hidden[id]) el.style.display = 'none';
      else el.style.display = '';
    });
    /* 3) 高度：纵向缩放持久化，吃掉 resize 手柄的成果。 */
    if (d.heights) {
      Object.keys(d.heights).forEach(function (id) {
        var el = blockEl(id);
        var h = parseInt(d.heights[id], 10);
        if (el && h >= 80 && h <= 3000) el.style.minHeight = h + 'px';
      });
    }
    /* 4) QC 卡序：MutationObserver 会在每次重渲染后重排，这里先排一次。 */
    applyQcOrder(d.qcOrder);
  }

  function currentLayout() {
    var d = readLocal() || blankLayout();
    return d;
  }
  function saveLayout(d) {
    writeLocal(d);
    /* 本地为主；服务端默认由管理员显式“设为团队默认”时才写（见工具条）。 */
  }

  /* QC 卡序：按 data-qc 重排 #band .qc-grid 的子节点。 */
  function applyQcOrder(order) {
    if (!Array.isArray(order) || !order.length) return;
    var grid = document.querySelector('#band .qc-grid');
    if (!grid) return;
    var byId = {};
    Array.prototype.forEach.call(grid.children, function (c) {
      var id = c.getAttribute && c.getAttribute('data-qc');
      if (id) byId[id] = c;
    });
    order.forEach(function (id) {
      if (byId[id]) grid.appendChild(byId[id]);
    });
  }
  function collectQcOrder() {
    var grid = document.querySelector('#band .qc-grid');
    if (!grid) return [];
    var out = [];
    Array.prototype.forEach.call(grid.children, function (c) {
      var id = c.getAttribute && c.getAttribute('data-qc');
      if (id) out.push(id);
    });
    return out;
  }

  /* ------------------------------------------------------------ 编辑态 ---- */
  function isEdit() { return document.documentElement.getAttribute(EDIT_ATTR) === 'edit'; }
  function setEdit(on) {
    if (on) document.documentElement.setAttribute(EDIT_ATTR, 'edit');
    else document.documentElement.removeAttribute(EDIT_ATTR);
    var btn = document.getElementById('tlEditBtn');
    if (btn) btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function ensureHandles() {
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (!el || el.querySelector(':scope > .tl-handle')) return;
      el.setAttribute('data-tl', id);
      var h = document.createElement('div');
      h.className = 'tl-handle';
      h.innerHTML = '<span class="tl-grip" title="拖动排序">⠿</span>' +
        '<span class="tl-name">' + id + '</span>' +
        '<button type="button" data-tl-hide="' + id + '" title="显示 / 隐藏">显隐</button>';
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
    });
    wireQcCards();
  }

  function clearDropMarks() {
    BLOCKS.forEach(function (id) {
      var el = blockEl(id);
      if (el) { el.classList.remove('is-tl-before'); el.classList.remove('is-tl-after'); }
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

  /* QC 卡拖序（编辑态）：卡片 draggable，重排后存 qcOrder。 */
  function wireQcCards() {
    var grid = document.querySelector('#band .qc-grid');
    if (!grid || grid.getAttribute('data-tl-qc') === '1') return;
    grid.setAttribute('data-tl-qc', '1');
    grid.addEventListener('dragstart', function (e) {
      if (!isEdit()) return;
      var card = e.target && e.target.closest ? e.target.closest('.qc-card') : null;
      if (!card || !grid.contains(card)) return;
      card.classList.add('is-tl-drag');
      try { e.dataTransfer.setData('text/tl-qc', card.getAttribute('data-qc') || ''); } catch (x) { /* ignore */ }
    });
    grid.addEventListener('dragend', function (e) {
      var card = e.target && e.target.closest ? e.target.closest('.qc-card') : null;
      if (card) card.classList.remove('is-tl-drag');
    });
    grid.addEventListener('dragover', function (e) {
      if (!isEdit()) return;
      e.preventDefault();
    });
    grid.addEventListener('drop', function (e) {
      if (!isEdit()) return;
      e.preventDefault();
      var srcId = null;
      try { srcId = e.dataTransfer.getData('text/tl-qc'); } catch (x) { srcId = null; }
      var src = srcId && grid.querySelector('.qc-card[data-qc="' + srcId + '"]');
      var tgt = e.target && e.target.closest ? e.target.closest('.qc-card') : null;
      if (!src || !tgt || src === tgt) return;
      var r = tgt.getBoundingClientRect();
      var before = (e.clientX - r.left) < r.width / 2;
      if (before) grid.insertBefore(src, tgt);
      else grid.insertBefore(src, tgt.nextSibling);
      var d = currentLayout();
      d.qcOrder = collectQcOrder();
      saveLayout(d);
    });
    /* 编辑态进入时给卡片挂 draggable（只读态不挂，避免误拖）。 */
    new MutationObserver(function () {
      if (!isEdit()) return;
      Array.prototype.forEach.call(grid.querySelectorAll('.qc-card'), function (c) {
        c.setAttribute('draggable', 'true');
      });
      var d = readLocal();
      if (d && d.qcOrder) applyQcOrder(d.qcOrder);
    }).observe(grid, { childList: true });
  }

  /* 高度持久化：resize 是原生手柄，mouseup 时记录 minHeight。 */
  function wireResizePersist() {
    document.addEventListener('mouseup', function () {
      if (!isEdit()) return;
      var d = currentLayout();
      d.heights = d.heights || {};
      var changed = false;
      BLOCKS.forEach(function (id) {
        var el = blockEl(id);
        if (!el) return;
        var h = el.getBoundingClientRect().height;
        /* 只记用户明显改过高度的（与 CSS 默认差 40px 以上才算数，避免滚轮误存）。 */
        var cur = parseInt(el.style.minHeight, 10) || 0;
        if (cur >= 80) { d.heights[id] = Math.round(h); changed = true; }
      });
      if (changed) saveLayout(d);
    });
  }

  /* ------------------------------------------------------------ 工具条 ---- */
  function ensureBar() {
    if (document.getElementById('teamLayoutBar')) return;
    var bar = document.createElement('div');
    bar.id = 'teamLayoutBar';
    bar.innerHTML = '<button type="button" id="tlEditBtn" aria-pressed="false">调整布局</button>' +
      '<button type="button" id="tlSaveBtn" title="把当前布局设为本团队默认（仅管理员）">设为团队默认</button>' +
      '<button type="button" id="tlResetBtn" title="清除本机自定义，回到团队默认">重置</button>';
    document.body.appendChild(bar);
    document.getElementById('tlEditBtn').addEventListener('click', function () {
      var on = !isEdit();
      setEdit(on);
      if (on) {
        ensureHandles();
        Array.prototype.forEach.call(
          document.querySelectorAll('#band .qc-grid .qc-card'), function (c) {
            c.setAttribute('draggable', 'true');
          });
      } else {
        Array.prototype.forEach.call(
          document.querySelectorAll('#band .qc-grid .qc-card'), function (c) {
            c.removeAttribute('draggable');
          });
      }
    });
    document.getElementById('tlResetBtn').addEventListener('click', function () {
      try { localStorage.removeItem(LS_KEY); } catch (e) { /* ignore */ }
      fetchServerDefault().then(function (srv) {
        BLOCKS.forEach(function (id) {
          var el = blockEl(id);
          if (el) { el.style.display = ''; el.style.minHeight = ''; }
        });
        if (srv) applyLayout(srv);
        location.reload();
      });
    });
    document.getElementById('tlSaveBtn').addEventListener('click', function () {
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
          var btn = document.getElementById('tlSaveBtn');
          if (btn) {
            btn.textContent = (j && (j.ok || j.saved)) ? '已保存' : '保存失败（需管理员）';
            setTimeout(function () { btn.textContent = '设为团队默认'; }, 2000);
          }
        }).catch(function () { /* ignore */ });
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
    saveLayout(d);
    return d;
  }

  /* ------------------------------------------------------------ 启动 ---- */
  function boot() {
    ensureBar();
    wireResizePersist();
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
    }, 0);
  });
})();
