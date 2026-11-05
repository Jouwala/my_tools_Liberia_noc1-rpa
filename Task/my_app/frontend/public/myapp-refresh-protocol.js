/* ============================================================================
 * myapp 自动刷新协议（共享脚本，2026-10-10 新增；2026-11-03 默认关闭改造）
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
 * ⭐ 默认关闭 + 每页独立设置（2026-11-03 用户定「默认是关闭刷新的」；2026-11-04 用户
 *   定「参考 noc_analyst 的刷新配置，给每个页面做设置」）：
 *   · 自动刷新由用户在 my_app 顶栏**按页开启**（「开启刷新」按钮 + 间隔下拉，
 *     持久化 localStorage['myapp_auto_refresh_pages']，一张 {page: 秒} 表）；
 *   · 2026-11-04 起**所有页面一视同仁**：不再有「只有看板页能刷」的白名单，
 *     配置 / 操作 / 工具类页面同样可以按页开启，本协议不再读看板标记；
 *   · 未开启的页（含全屏挂机）一律不刷新 —— 本协议不再有 defaultSec 兜底，
 *     也不再「全屏时忽略关闭」（默认已是关闭，全屏擅自刷新恰恰违背「用户决定」）；
 *   · 旧版全局键 myapp_auto_refresh_sec / 逐页键 _ar_page_* / 看板标记键
 *     myapp_auto_refresh_is_board 已由 App 外壳挂载时清除，这里读取时一并忽略
 *     （防直开页缓存了旧脚本时读到残留值）。
 *
 * 间隔与开关（每轮重新读取，顶栏改动即时生效）：
 *   sec = localStorage['myapp_auto_refresh_effective']  0/缺省=关闭
 *   · sec>0 → 按该间隔自调度兜底；
 *   · sec 为 0/缺省 → 不排下一轮（默认关闭，尊重用户选择）。
 *
 * 用法：
 *   MyAppRefresh.install({
 *     onRefresh: function(){ ... },    // 收到广播 / 到点时调用的「重取数」入口
 *     hiddenGuard: true,               // 默认 true：本页不可见且非全屏时跳过本轮
 *   });
 * ========================================================================== */
(function (global) {
  'use strict';

  var EFFECTIVE_KEY = 'myapp_auto_refresh_effective';
  // 旧版键：仅用于「读到了也当没读到」（清理由 App 外壳负责，这里双保险）。
  // myapp_auto_refresh_is_board 是白名单时代的看板标记，2026-11-04 起所有页面一视同仁。
  var LEGACY_KEYS = ['myapp_auto_refresh_sec', 'myapp_auto_refresh_is_board'];

  function readSec() {
    try {
      var raw = global.localStorage.getItem(EFFECTIVE_KEY);
      if (raw == null) return null;
      var v = parseInt(raw, 10);
      return isNaN(v) ? null : v;
    } catch (e) { return null; }
  }

  function effectiveSec() {
    var sec = readSec();
    // 2026-11-03 起没有 defaultSec 兜底、没有「全屏忽略关闭」；2026-11-04 起没有看板白名单：
    // 未开启（0/缺省/旧残留键）一律不刷，是否刷新完全由用户在顶栏按页决定。
    if (sec == null || sec <= 0) return 0;
    return sec;
  }

  function install(opts) {
    opts = opts || {};
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
      var sec = effectiveSec();
      if (!sec) return;                                      // 未开启：不排下一轮
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

    // 顶栏改动（开启/停止/换间隔）会改写 EFFECTIVE_KEY；storage 事件只在本页
    // 之外的标签页改动时触发（同页 setItem 不触发），所以这里主要覆盖
    // 「另一个标签页里的 my_app 顶栏改了设置」的场景，顺带重排本页兜底。
    function onStorage(e) {
      try {
        if (e && e.key && e.key !== EFFECTIVE_KEY && LEGACY_KEYS.indexOf(e.key) < 0) return;
      } catch (err) { /* ignore */ }
      arm();
    }

    try { global.addEventListener('message', onMessage); } catch (e) {}
    try { global.addEventListener('storage', onStorage); } catch (e) {}
    try { arm(); } catch (e) {}

    return {
      arm: arm,
      refreshNow: runNow,
      effectiveSec: function () { return effectiveSec(); },
    };
  }

  global.MyAppRefresh = {
    install: install,
    readSec: readSec,
    effectiveSec: effectiveSec,
  };
})(window);
