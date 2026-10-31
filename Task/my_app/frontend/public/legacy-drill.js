/* ==========================================================================
   legacy-drill.js —— legacy 静态页的统一「下钻明细」弹窗
   --------------------------------------------------------------------------
   为什么存在：AGENTS.md 第三节 1b「能下钻尽下钻」要求页面上每个数字都能落到
   明细，且规定下钻弹窗用 frontend/src/components/DraggableClickModal。该组件是
   React 的，public/ 下的 legacy 页（iframe 嵌入，见 LegacyToolFrame.tsx:115）
   运行时里没有 React —— 这是既成的偏离，不是偷懒：弹窗的外观与交互统一由
   legacy-glass-baseline.css 的 .whx 提供，行为由本文件提供，四页共用一份，
   不再各画各的 modal。样式类名（.whx / .wh-drill / .wh-drill-card / .wh-nodrill）
   必须与那边一起看，改样式不要改这里。

   三条硬口径（写在 API 约束里，页面不要绕过）：
     1) 只有「明细与概览同源」才允许下钻 —— rows 必须取自渲染那个数字的同一份
        payload。映射不确定时显式声明不可下钻（用 wh-nodrill + note），
        不要猜一个对应关系去凑，否则「点出来的行数」和「卡面上的数字」会对不上。
     2) 取不到值一律显示 —（em dash），不得显示 0：本文件在 setCell 里强制。
     3) 截断必须显式：传 truncated:true 时告警条常驻，不靠用户自己发现。

   用法（页面侧只需两步）：
     <script src="./legacy-drill.js"></script>
     WhDrill.bind(cardEl, () => ({ title, sub, cols, rows, note, truncated }))
   或手动 WhDrill.open(cfg) / WhDrill.close()。
   数字的格式化交回页面自己做完再传字符串 —— 各页单位与精度不同（GB/TB/%/kbps），
   在这里再造一份格式化就是第二个真相源。
   ========================================================================== */
(function (global) {
  'use strict';

  var MISSING = '\u2014'; // —  取不到值的统一显示，绝不写 0
  var current = null;     // 同一时刻只开一个弹窗，避免叠层

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function cellText(v) {
    // null / undefined / '' 一律成 —；0 是真实值，必须原样显示，两者不能混
    if (v === null || v === undefined || v === '') return MISSING;
    return String(v);
  }

  function deltaClass(row) {
    var d = row && row.delta;
    if (typeof d !== 'number' || !isFinite(d) || d === 0) return '';
    return d > 0 ? 'pos' : 'neg';
  }

  function build(cfg) {
    var labels = cfg.labels || {};
    var cols = cfg.cols || [];
    var rows = cfg.rows || [];

    var mask = el('div', 'whx-mask');
    var box = el('div', 'whx');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', cfg.title || '');

    var head = el('div', 'whx-head');
    var titleWrap = el('div');
    titleWrap.appendChild(el('span', 'whx-title', cellText(cfg.title)));
    if (cfg.sub) titleWrap.appendChild(el('span', 'whx-sub', cfg.sub));
    head.appendChild(titleWrap);

    var closeBtn = el('button', 'whx-close', labels.close || '×');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', labels.closeAria || '关闭');
    closeBtn.addEventListener('click', api.close);
    head.appendChild(closeBtn);
    box.appendChild(head);

    var body = el('div', 'whx-body');

    if (!rows.length) {
      // 空明细要说清为什么空，不能只给一张空表 —— 与「取不到数据显示 —」同源的原则
      body.appendChild(el('div', 'whx-empty', labels.empty || cellText(cfg.emptyText)));
    } else {
      var tbl = el('table');
      var thead = el('thead');
      var hr = el('tr');
      cols.forEach(function (c) { hr.appendChild(el('th', null, cellText(c))); });
      thead.appendChild(hr);
      tbl.appendChild(thead);

      var tb = el('tbody');
      rows.forEach(function (r) {
        var tr = el('tr');
        var cells = r.cells || [];
        // 涨跌着色只作用在「值」列：页面可指定 deltaCol，默认第 2 列（索引 1）
        var dcol = typeof r.deltaCol === 'number' ? r.deltaCol : 1;
        cells.forEach(function (v, i) {
          var missing = (v === null || v === undefined || v === '');
          var cls = missing ? 'miss' : (i === dcol ? deltaClass(r) : '');
          tr.appendChild(el('td', cls, cellText(v)));
        });
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      body.appendChild(tbl);
    }

    if (cfg.truncated) {
      var warn = el('div', 'whx-note warn');
      warn.textContent = (labels.truncated || '明细已截断：仅显示前') + ' ' +
        cellText(cfg.shown) + ' ' + (labels.rowsUnit || '行') + ' / ' +
        cellText(cfg.total);
      body.appendChild(warn);
    }
    if (cfg.note) body.appendChild(el('div', 'whx-note', cfg.note));

    box.appendChild(body);
    mask.appendChild(box);

    // 遮罩点击关闭；弹窗内部点击不冒泡到遮罩，否则表格选字会误关
    mask.addEventListener('click', function (e) { if (e.target === mask) api.close(); });
    return { mask: mask, box: box, closeBtn: closeBtn };
  }

  var api = {
    /* open(cfg) cfg:
       { title, sub, cols: string[], rows: [{cells:[...], delta?:number, deltaCol?:number}],
         note, truncated, shown, total, emptyText, labels:{close,closeAria,empty,truncated,rowsUnit} } */
    open: function (cfg) {
      cfg = cfg || {};
      api.close();
      var built = build(cfg);
      current = built;
      document.body.appendChild(built.mask);
      document.addEventListener('keydown', onKey);
      built.closeBtn.focus();
    },
    close: function () {
      if (!current) return;
      document.removeEventListener('keydown', onKey);
      if (current.mask.parentNode) current.mask.parentNode.removeChild(current.mask);
      current = null;
    },
    isOpen: function () { return !!current; },

    /* bind(node, provider, opts)：把任意元素变成「可下钻」入口。
       opts.as='number'|'card' 决定挂 .wh-drill 还是 .wh-drill-card；
       opts.skip=true 时改成 .wh-nodrill（口径做不到同源的情形，显式声明而非静默不可点）。 */
    bind: function (node, provider, opts) {
      if (!node) return;
      opts = opts || {};
      if (opts.skip) {
        node.classList.add('wh-nodrill');
        if (opts.title) node.title = opts.title;
        return;
      }
      node.classList.add(opts.as === 'card' ? 'wh-drill-card' : 'wh-drill');
      node.setAttribute('role', 'button');
      node.setAttribute('tabindex', '0');
      if (opts.hint) node.setAttribute('aria-label', opts.hint);
      var fire = function (e) {
        e.preventDefault();
        var cfg = provider();
        if (cfg) api.open(cfg);
      };
      node.addEventListener('click', fire);
      node.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') fire(e);
      });
    }
  };

  function onKey(e) { if (e.key === 'Escape') api.close(); }

  global.WhDrill = api;
})(window);
