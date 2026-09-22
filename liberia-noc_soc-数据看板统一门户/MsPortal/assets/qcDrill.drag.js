/* ============================================================================
   qcDrill.drag.js —— QC 下钻弹窗的「拖动 + 以点击位置为中心弹出」
   ----------------------------------------------------------------------------
   2026-09-23 新增，两边共用（/MsPortal/ 与 /olbrportal/ 各引一次这个文件）。

   为什么要有这个文件：
     第一版统一只统一了「长相」，交互仍与 /myapp/?page=alarm 的弹窗不一致 ——
     实际用起来立刻能感觉到：门户的弹窗不能拖、点遮罩会关、也不跟着点击位置弹。
     本文件把 myapp 的行为**逐条搬过来**，源码见
     Task/my_app/frontend/src/components/DraggableClickModal.tsx：

       1. 以「点击位置」为中心弹出，越界自动 clamp 到视口内（pad = 8px）
       2. 按住标题栏可自由拖动，同样 clamp 在视口内
       3. 点遮罩**不关闭**（避免误触）；只认右上角 × 与 Esc
       4. 拖动时把 left/top 写成内联样式 —— 这是能拖的前提

   与 myapp 的差异只有一处，是刻意的：
     myapp 用 React 的 onMouseDown + useLayoutEffect 管生命周期；门户是原生 JS，
     所以改成「打开时调用一次 qcDrillPosition()」+「一直挂在标题栏上的
     mousedown/mousemove/mouseup」。三条行为本身逐条对齐，没有做减法。

   依赖：页面需存在 #qcMask（遮罩）与其内的 .qc-modal / .qc-head。
   ========================================================================== */
(function () {
  'use strict';

  /* 越界留白，与 myapp 的 pad 一致（弹窗贴边会看不见圆角与边框） */
  var PAD = 8;

  var modal = null;   /* 当前拖动的弹窗（.qc-modal） */
  var drag = { active: false, dx: 0, dy: 0 };

  function q(sel) { return document.querySelector(sel); }

  /** 把 (left, top) 夹在视口内 —— 与 myapp onMouseMove / useLayoutEffect 同式 */
  function clampTo(left, top, w, h) {
    return {
      left: Math.max(PAD, Math.min(left, window.innerWidth - w - PAD)),
      top: Math.max(PAD, Math.min(top, window.innerHeight - h - PAD)),
    };
  }

  function apply(el, left, top) {
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    /* 必须显式清掉 transform：遮罩用了 flex 居中做无 JS 兜底，
       若样式表里还有 transform 参与定位，拖动的 left/top 会被它抵消。 */
    el.style.transform = 'none';
  }

  /**
   * 打开弹窗后调用：把弹窗放到「点击位置」中心，越界则夹回视口。
   * @param {{x:number,y:number}|null} anchor 触发打开时的鼠标坐标；为空则居中于屏幕
   */
  function position(anchor) {
    var el = q('#qcMask .qc-modal');
    if (!el) return;
    modal = el;
    var w = el.offsetWidth;
    var h = el.offsetHeight;
    var cx = anchor ? anchor.x : window.innerWidth / 2;
    var cy = anchor ? anchor.y : window.innerHeight / 2;
    var p = clampTo(cx - w / 2, cy - h / 2, w, h);
    apply(el, p.left, p.top);
  }

  /** 窗口尺寸变化后重新夹一次，避免弹窗被挤到视口外（myapp 未处理，这里补上） */
  function reclamp() {
    var el = q('#qcMask .qc-modal');
    if (!el || el.hidden || !el.offsetWidth) return;
    var r = el.getBoundingClientRect();
    var p = clampTo(r.left, r.top, el.offsetWidth, el.offsetHeight);
    apply(el, p.left, p.top);
  }

  function onMouseMove(e) {
    if (!drag.active || !modal) return;
    var w = modal.offsetWidth;
    var h = modal.offsetHeight;
    var p = clampTo(e.clientX - drag.dx, e.clientY - drag.dy, w, h);
    apply(modal, p.left, p.top);
  }

  function stopDrag() {
    drag.active = false;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', stopDrag);
  }

  function onMouseDown(e) {
    var el = q('#qcMask .qc-modal');
    if (!el || el.hidden) return;
    var head = el.querySelector('.qc-head');
    if (!head || !head.contains(e.target)) return;         /* 只能从标题栏拖 */
    var closeBtn = el.querySelector('.qc-x');
    /* 点 × 不能起拖：否则会「拖了一下又顺手关掉」，或反过来把关闭吞掉 */
    if (closeBtn && closeBtn.contains(e.target)) return;

    modal = el;
    drag.active = true;
    var rect = el.getBoundingClientRect();
    drag.dx = e.clientX - rect.left;
    drag.dy = e.clientY - rect.top;
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', stopDrag);
    e.preventDefault();     /* 阻止拖动时选中标题文字 */
  }

  /* 事件委托挂在 document 上：弹窗骨架虽然一直在 DOM 里，
     但用委托可以让两个门户都只调一次 bind()，不必各自记着绑在哪。 */
  function bind() {
    document.addEventListener('mousedown', onMouseDown);
    window.addEventListener('resize', reclamp);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }

  window.QcDrill = { position: position, bind: bind, reclamp: reclamp };
})();
