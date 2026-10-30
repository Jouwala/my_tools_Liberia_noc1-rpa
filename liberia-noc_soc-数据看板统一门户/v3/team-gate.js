/* ============================================================================
   team-gate.js —— 团队门户的**客户端闸门**（注入到 /v3/olbrportal/ 的首页）
   ----------------------------------------------------------------------------
   目的
   ----
   管理员把某个账号指派到某个团队后（users.team = fo/bo/flm/smc/cxo），
   这个账号登录 /v3/olbrportal/ 时应当**自动跳到**对应的团队门户：
       fo  → /v3/fo_portal/
       bo  → /v3/bo_portal/
       flm → /v3/flm_portal/
       smc → /v3/smc_portal/
       cxo → /v3/cxo_portal/

   为什么需要这一层（nginx 那层不够）
   ----------------------------------
   nginx 侧已有 `auth_request /uniplam/api/auth/team-landing`：
   **打开页面时**若浏览器已经带着 olbr_token Cookie，就会 302 到团队门户。
   但「首次登录」这条路走不到它 ——
     ① 用户打开 /v3/olbrportal/ 时还没 Cookie → nginx 放行（主门户是公开入口）；
     ② 用户在页面上填账号密码 → olbr.js 走 POST /uniplam/api/auth/login；
     ③ 此时页面**早已加载完毕**，nginx 那次请求早就结束了。
   所以「登录成功后自动跳转」只能在**浏览器里**做。

   为什么这个文件能注入到 /v3/olbrportal/ 里，而不用改它
   --------------------------------------------------
   上游 /v3/olbrportal/ 是别人的页面，一行都不许改。本文件由 nginx 用
   `sub_filter` 在**响应下发时**把一行 <script src="/v3/team-gate.js"> 注入
   </head> —— 磁盘上的 v3/olbrportal/index.html 一个字节都没动。
   注入点在 </head>，而 olbr.js 是 </body> 前的 <script>，所以本脚本
   **先于** olbr.js 执行，能赶在 olbr.js 发登录请求之前把 fetch 包起来。

   三条跳转触发路径
   ----------------
   ① 页面加载时本地已有 token（刷新页面 / 直接收藏夹进入）
      → GET /uniplam/api/auth/me 拿到 user.team → 跳
   ② 页面加载时本地**没有** token → 不跳（还没登录，主门户是公开入口）
   ③ 登录成功的那一刻（POST /uniplam/api/auth/login 返回 200）
      → 响应体里的 user.team → 跳

   ⚠️ 与服务端闸门的关系（两者不重复）
     · 服务端（nginx auth_request + /team-gate）负责「**能不能看**」——
       越权访问别人的团队门户在服务端就被 403 挡掉，内容根本不下发。
     · 本脚本负责「**登录后去哪**」—— 属于导航便利，不承担安全职责。
     所以本脚本被绕过（禁用 JS）不会造成越权：服务端闸门独立生效。

   ⚠️ 没有团队归属的账号一律不跳（停在 /v3/olbrportal/ 主门户）。
   ========================================================================== */
(function () {
  'use strict';

  /* 与 server/auth/types.ts 的 TEAM_PORTAL_PATHS 保持一致 —— 双份字面量，
     因为这是纯静态脚本、不能 import 后端模块。两处都由测试覆盖（见
     scripts/check_team_portal.mjs 的 URL 映射一致性断言）。 */
  var TEAM_PORTAL = {
    fo:  '/v3/fo_portal/',
    bo:  '/v3/bo_portal/',
    flm: '/v3/flm_portal/',
    smc: '/v3/smc_portal/',
    cxo: '/v3/cxo_portal/'
  };

  /* 门户会话 token 的 localStorage 键（与 v3/olbrportal/assets/olbr.js 的
     TOKEN_KEY 一致） */
  var TOKEN_KEY = 'liberia_noc_auth_v1';

  /* 单次页面生命周期内只跳一次：①③ 可能同时命中（登录成功后随即刷新） */
  var jumped = false;

  function teamPath(team) {
    var p = TEAM_PORTAL[String(team || '').toLowerCase()];
    return p || null;
  }

  function currentToken() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }

  /* 跳转到团队门户。用 replace 而非 assign：不留历史记录，
     用户按「后退」回到主门户会立刻再被跳走（体验上像是弹回来）。
     登录刚完成时 replace 也能把「登录页」从历史里清掉。 */
  function jumpTo(team) {
    var path = teamPath(team);
    if (!path || jumped) return;
    jumped = true;
    try { location.replace(path); } catch (e) { location.href = path; }
  }

  /* 路径①：本地已有 token → 问服务端「我属于哪个团队」 */
  function probeMe() {
    var tk = currentToken();
    if (!tk) return;
    fetch('/uniplam/api/auth/me', {
      credentials: 'same-origin',
      headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var u = d && d.user;
        if (u && u.team) jumpTo(u.team);
      })
      .catch(function () { /* 网络失败就留在主门户，不打扰用户 */ });
  }

  /* 路径③：包住 fetch，盯住登录请求的响应。
     ⚠️ clone() 在 **Response** 上，不在 Promise 上 ——
        rawFetch() 返回的是 Promise<Response>，clone 要等 Promise 兑现后才有。
        早先写成 `p.clone()`（p 是 Promise）→ clone is not a function → 静默失败，
        登录成功却不跳转。故这里用 .then() 取到 Response 再 clone。
     用 clone() 读一份副本，原响应原样交回 olbr.js —— 两边各自读一次 body。 */
  function patchFetch() {
    if (typeof window.fetch !== 'function') return;
    var rawFetch = window.fetch;
    window.fetch = function (input, init) {
      var p = rawFetch.call(this, input, init);
      try {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (method === 'POST' && /\/api\/auth\/login\b/.test(url) && p && p.then) {
          p.then(function (res) {
            if (!res || !res.clone) return;
            res.clone().json()
              .then(function (d) {
                if (d && d.user && d.user.team) jumpTo(d.user.team);
              })
              .catch(function () { /* 登录失败不该跳转，交给 olbr.js 显示错误 */ });
          }).catch(function () { /* 网络失败不该跳转 */ });
        }
      } catch (e) { /* 包 fetch 只是锦上添花，失败不能影响原流程 */ }
      return p;
    };
  }

  function boot() {
    patchFetch();
    probeMe();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
