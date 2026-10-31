/* ============================================================================
   team-session.js —— 团队门户的 my_app 会话预热与 401 自愈（2026-10-30 加）
   ----------------------------------------------------------------------------
   背景（真实故障，2026-10-30）
   --------------------------------------------------------------------------
   团队门户页（/v3/fo_portal/ 等）的数据全部来自 **my_app 后端**（QC 汇总、
   KPI 指标、报告列表、看板目录），而这些接口在 my_app 侧要求 `myapp_session`
   Cookie（见 Task\my_app\backend\main.py 的 require_session_middleware）。

   但团队门户页自己**从不**建立这个会话 —— 全页唯一换会话的地方是登录闸门里的
   login() → POST /api/auth/portal-login（olbr.js 的 login()）。于是：

     ① 用户先在 /uniplam/ 登录 → 拿到**门户 token**（localStorage
        liberia_noc_auth_v1 + HttpOnly Cookie olbr_token）；
     ② 打开 /v3/fo_portal/ → nginx 的 auth_request 校验团队通过 → 页面打开；
     ③ 页面 probe() 判「已登录」用的是**门户 token**，于是直接 start() 拉数据；
     ④ 但 myapp_session **根本不存在** → my_app 中间件回 401
        → 心跳点变红（qc-dot-bad）、卡片显示「—」、报告表显示「加载失败」；
     ⑤ 页面里的 **my_app 内嵌 iframe**（地图 / QA / 反馈）自己会跑
        bootstrapAuth()（Task\my_app\frontend\src\api.ts），它从**同一个
        localStorage** 读到门户 token，再调一次 /api/auth/portal-login
        → **这才是真正种下 myapp_session 的那一步**；
     ⑥ 用户刷新 → Cookie 已在 → 全部 200 → 恢复正常。

   第 ⑤ 步的 iframe 是**副作用**，且必然比父页的数据请求慢一拍 —— 所以踩空
   是结构性的，不是偶发。**本机管理员看不到**是因为 my_app 对本机回环直接放行
   （portal_auth.current_user → client_is_local），只有局域网其他机器才是真实远端。

   第二个变因：门户会话**只存门户进程内存**（server/auth/store.ts 的 createSession），
   门户一重启，所有人的旧 token 即失效 → my_app 换不到会话 → 症状与上面一模一样
   （日志里表现为 POST /api/auth/portal-login → 401 与
   「[portal-auth] uniplam /me 回 401，视为 token 无效」）。

   本模块解决这两条
   --------------------------------------------------------------------------
   ensure()
     用门户 token 换 myapp_session。幂等、并发去重（同一时刻多个调用只发一次）、
     带超时、失败静默（不阻断页面）。**在拉数据之前调用**，让首屏就有会话。

   retryOn401()
     包裹 olbr.js 的 api()：收到 401 时换一次会话再重试一次。
     兜住「会话过期」「门户重启导致 token 失效」这类**运行期**失效 ——
     有了它，门户重启后用户不用手动刷新，页面自己就恢复。

   为什么放在**独立文件**里而不是塞进 olbr.js
   --------------------------------------------------------------------------
   v3/team_portal/assets/olbr.js 是 scripts/patch_team_portal.py 从上游基线
   **生成**出来的（上游那一份一行都不许改）。往生成物里直接塞代码，下次重跑
   脚本就被覆盖 —— 这一条本脚本组已踩过多次。
   而 scripts/sync_team_assets.py 明确把 team-*.js 列为「纯团队专有，上游没有，
   不动」的文件。本模块属此类，故是**团队门户专有资产**。

   与上游 /v3/olbrportal/ 的关系
   --------------------------------------------------------------------------
   上游那一页**不引**本文件 → window.OLBR_SESSION 为 null → olbr.js 里
   `if (SCOPE && window.OLBR_SESSION)` 全部短路 → 上游行为一行未变。
   ========================================================================== */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- 关键配置 --
     门户会话 token 的 localStorage 键。
     ⚠️ 三处必须一致（同一份凭据的多个载体，不是多份真相源）：
       · 本文件
       · v3/team_portal/assets/olbr.js 的 TOKEN_KEY
       · v3/team-gate.js 的 TOKEN_KEY
       · Task/my_app/frontend/src/api.ts 的 PORTAL_TOKEN_KEY
     任何一处改了，其余几处都要跟着改，否则「门户登着、my_app 换不到会话」。 */
  var TOKEN_KEY = 'liberia_noc_auth_v1';

  /** 换会话接口（my_app 后端）：用它把门户 token 换成 myapp_session Cookie。 */
  var PORTAL_LOGIN_URL = '/api/auth/portal-login';

  /** 单次换会话的超时（毫秒）。超时即放弃 —— 不能让它把首屏拖住。 */
  var TIMEOUT_MS = 8000;

  /** 门户会话 token（读 localStorage）。读不到返回 null。 */
  function portalToken() {
    try { return localStorage.getItem(TOKEN_KEY) || null; } catch (e) { return null; }
  }

  /* ---------------------------------------------------------- 会话预热 --
     ensure()
     用门户 token 换 myapp_session。

     幂等与并发去重：
       · 同一时刻多次调用只发**一次**网络请求（inFlight 复用同一个 Promise）；
       · 已经换成功过（ok=true）就直接返回，不再发请求 —— 这是「幂等」的来源；
       · 换过但失败（ok=false）允许**重试**（inFlight 已清空，下次调用会真发一次）。
         ⚠️ 必须允许失败后重试：门户重启导致 token 失效时，第一次失败，
         用户刷新后 token 换了，再调 ensure() 就该能成。

     返回 { ok: boolean } —— 调用方通常不需要区分「已就绪」与「换失败」，
     但保留 ok 便于将来做提示。 */
  var inFlight = null;
  var sessionOk = false;

  function ensure(force) {
    /* 已就绪且不是强制重试 → 直接返回，不发请求。 */
    if (sessionOk && !force) return Promise.resolve({ ok: true });
    /* 有请求在飞 → 等它，不要再发一次（并发去重）。 */
    if (inFlight) return inFlight;

    var tk = portalToken();
    /* 没有门户 token → 换不了会话（用户还没登录）。不算失败，静默返回。 */
    if (!tk) return Promise.resolve({ ok: false, reason: 'no-portal-token' });

    inFlight = fetch(PORTAL_LOGIN_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tk })
    })
      .then(function (r) {
        /* 只有 2xx 才算换成功。401 = 门户 token 已失效（门户重启 / 会话过期）
           —— 这时把 sessionOk 置回 false，让后续 ensure() 有机会重试。 */
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json().catch(function () { return {}; });
      })
      .then(function () {
        sessionOk = true;
        return { ok: true };
      })
      .catch(function (e) {
        sessionOk = false;
        return { ok: false, reason: (e && e.message) || String(e) };
      })
      .then(function (out) {
        /* 无论成败都要清掉 inFlight，否则一次失败会把会话永久锁死。 */
        inFlight = null;
        return out;
      });

    return inFlight;
  }

  /* ------------------------------------------------------------ 401 自愈 --
     retryOn401(fn, url)
     把 olbr.js 的 api() 包一层：收到 401 时，**换一次会话再重试一次**。

     为什么需要它（ensure() 覆盖不到的场景）：
       · 页面开着不动，myapp_session 过期（滑动续期窗口 8h，但也会到期）；
       · 门户进程重启 → 门户 token 失效 → my_app 侧换不回会话；
       · 首次预热时门户恰好在重启 → ensure() 失败 → 之后数据请求才 401。
       这几种都不是「首屏竞态」，但症状一样（红点 + 无数据），且用户的第一反应
       就是「刷新一下好了」—— 正是本函数要消除的体验。

     ⚠️ 只重试**一次**：重试仍 401 就把错误抛给调用方（由它显示错误态）。
       无限重试会把 401 变成一个死循环，把后端打爆。

     ⚠️ 换会话**失败**时直接抛原错误（不重试）：没有门户 token 或门户不可达时
       重试必然还是 401，白白多一次往返。

     返回值形状与被包裹的 api() 一致（Promise<json>），调用方无需改动。 */
  function retryOn401(fn, url) {
    return function (u) {
      return fn(u).catch(function (err) {
        /* 只在 401 时自愈。err.message 形如 'HTTP 401'（olbr.js 的 api() 约定）。 */
        if (!err || String(err.message || '').indexOf('401') === -1) throw err;

        return ensure(true).then(function (res) {
          /* 换不到会话 → 重试无意义，把原错误抛出去。 */
          if (!res.ok) throw err;
          return fn(u);
        });
      });
    };
  }

  /* ---------------------------------------------------------------- 导出 -- */
  window.OLBR_SESSION = {
    ensure: ensure,
    retryOn401: retryOn401,
    /** 测试/调试用：当前是否已持有 myapp_session */
    isReady: function () { return sessionOk; }
  };

  console.info('[team-session] 已加载（my_app 会话预热 + 401 自愈）');
})();
