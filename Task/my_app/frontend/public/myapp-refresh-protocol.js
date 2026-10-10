/* ============================================================================
 * myapp 自动刷新协议（共享脚本，2026-10-10 新增）
 * ----------------------------------------------------------------------------
 * 被各 legacy 单页 HTML（mw_ume_topology / mw_real_time / vmax_cxo_dashboard* /
 * cxo_dashboard / warehouse-dashboard / incident-overview / alarm-management 等）
 * 在 <script src="./myapp-refresh-protocol.js"></script> 引入，统一实现：
 *
 *   1) 监听父外壳（App.tsx）广播的 postMessage({__type:'myapp-refresh'})，
 *      收到即「原地重拉」（提前触发）；
 *   2) 常开一条「自调度兜底」定时器：父外壳广播被挡（全屏 Kiosk / 全屏窗口
 *      未聚焦 / 副屏常使父窗口 document.hidden=true）时仍能按时刷新，
 *      大屏挂机永不静默。
 *
 * 背景：此前各页兜底定时器带 `window.top === window.self` 或 `embedded()` 守卫，
 * 嵌入 ?page=xxx 时不生效，完全依赖父外壳广播 —— 全屏/后台时则彻底不刷新。
 *
 * 间隔与开关（每轮重新读取，顶栏改动即时生效）：
 *   sec  = localStorage['myapp_auto_refresh_effective']  0=关闭 / 缺省=本页默认
 *   board= localStorage['myapp_auto_refresh_is_board']    '1'=看板 / '0'=非看板 / 缺省=直开
 *   · 非看板页（board==='0'）→ 不启用兜底（全屏也不刷）；
 *   · 看板页 && sec===0 && 全屏 → 按本页默认兜底（大屏挂机忽略「关闭」）；
 *   · 看板页 && sec===0 && 非全屏 → 不排下一轮（尊重用户关闭）；
 *   · 直开（board 缺省）→ 按本页默认兜底。
 *
 * 用法：
 *   MyAppRefresh.install({
 *     defaultSec: 900,                 // 本页默认间隔（秒），与 App.tsx 的
 *                                      // AR_PAGE_DEFAULTS / AR_PAGE_DEFAULT_SEC 对齐
 *     onRefresh: function(){ ... },    // 收到广播 / 到点时调用的「重取数」入口
 *     hiddenGuard: true,               // 默认 true：本页不可见且非全屏时跳过本轮
 *   });
 * ========================================================================== */
(function (global) {
  'use strict';

  var EFFECTIVE_KEY = 'myapp_auto_refresh_effective';
  var OVERRIDE_KEY = 'myapp_auto_refresh_sec';
  var BOARD_KEY = 'myapp_auto_refresh_is_board';

  function readSec() {
    try {
      var raw = global.localStorage.getItem(EFFECTIVE_KEY);
      if (raw == null) raw = global.localStorage.getItem(OVERRIDE_KEY);
      if (raw == null) return null;
      var v = parseInt(raw, 10);
      return isNaN(v) ? null : v;
    } catch (e) { return null; }
  }

  // 返回 true=看板 / false=非看板 / null=未知（直开或父页尚未写入）
  function readIsBoard() {
    try {
      var raw = global.localStorage.getItem(BOARD_KEY);
      return raw == null ? null : (raw === '1');
    } catch (e) { return null; }
  }

  function effectiveSec(defaultSec) {
    // 非看板页：不自动刷新（含全屏）
    if (readIsBoard() === false) return 0;
    var sec = readSec();
    if (sec == null) sec = defaultSec;                       // 直开 / 未写入 → 本页默认
    if (sec === 0 && global.document && global.document.fullscreenElement) {
      sec = defaultSec;                                      // 看板页全屏忽略「关闭」
    }
    return sec;
  }

  function install(opts) {
    opts = opts || {};
    var defaultSec = opts.defaultSec || 300;
    var onRefresh = opts.onRefresh || function () {};
    var hiddenGuard = opts.hiddenGuard !== false;
    var timer = null;

    function shouldSkipTick() {
      if (!hiddenGuard) return false;
      try {
        return !!(global.document && global.document.hidden && !global.document.fullscreenElement);
      } catch (e) { return false; }
    }

    function runNow() {
      try { onRefresh(); } catch (e) { /* 数据未就绪时忽略 */ }
    }

    function arm() {
      if (timer) { clearTimeout(timer); timer = null; }
      var sec = effectiveSec(defaultSec);
      if (!sec) return;                                      // 关闭且非全屏 / 非看板页：不排下一轮
      timer = setTimeout(function () {
        if (!shouldSkipTick()) runNow();                     // 不可见且非全屏时跳过，但仍续排
        arm();
      }, sec * 1000);
    }

    // 父外壳广播 = 提前触发：立即刷新并重置倒计时（避免与兜底定时器双跑）
    function onMessage(e) {
      var d = e && e.data;
      if (!d || typeof d !== 'object' || d.__type !== 'myapp-refresh') return;
      runNow();
      arm();
    }

    try { global.addEventListener('message', onMessage); } catch (e) {}
    try { arm(); } catch (e) {}

    return {
      arm: arm,
      refreshNow: runNow,
      effectiveSec: function () { return effectiveSec(defaultSec); },
    };
  }

  global.MyAppRefresh = {
    install: install,
    readSec: readSec,
    readIsBoard: readIsBoard,
    effectiveSec: effectiveSec,
  };
})(window);
