/* ============================================================================
   team-login.js —— 团队门户「同页登录页」的驱动脚本（2026-11-04 加）
   ----------------------------------------------------------------------------
   背景（用户反馈：「https://192.168.100.20/v3/bo_portal/ 用户访问直接在这个
   页面登录就行，为什么要取其他地方登录呢。」）：
     五个团队门户的 nginx location 都带
       auth_request /uniplam/api/auth/team-gate/<team>;
     **内容下发前**就判定身份：未登录 → 401。此前 401 回的是一段内联 HTML，
     只有一个「去登录」外链（/uniplam/）—— 用户被赶去另一个页面登录。

     但团队门户页面**自己**就有完整的登录表单（olbr.js 的 renderGate() →
     POST /uniplam/api/auth/login），闸门在页面送达前就拦了，那个表单
     根本到不了浏览器。故把那个「到不了的表单」独立成一张静态页
     （v3/team-login.html），由 nginx 的 `error_page 401` 内部重定向到它。

   本脚本做什么
   ------------
     · 渲染登录表单并 POST /uniplam/api/auth/login（与门户页**同一个**接口、
       同一套账号 —— 不新增第二份账号体系）；
     · 登录成功 → 服务端种下 olbr_token Cookie（HttpOnly, Path=/）
       → location.reload() → 重新走 auth_request → 这次放行；
     · 首次登录强制改密（user.mustChangePassword）→ 换到改密表单，
       改完再 reload。

   ⚠️ 安全边界（与 nginx 闸门的关系，务必理解）：
     · 服务端闸门**原样保留** —— 团队内容从未在未登录时下发过；
       本页只解决「在哪登录」，不承担访问控制。
     · 本页**不**带 auth_request，必须在未登录时也能取到（这正是它存在的意义），
       它不含任何敏感信息 —— 只有一张空表单。
     · 登录失败的口径与门户页一致（同一套 detail 字符串映射）。

   ⚠️ 为什么是独立文件而不是塞进 team-gate.js：
     team-gate.js 是**注入到上游 /v3/olbrportal/ 首页**的（nginx sub_filter），
     职责是「登录成功后跳到本团队门户」；本页的职责是「在这里登录」，
     两者生命周期与触发条件都不同，合在一起会让那份注入脚本背上无关职责。
   ========================================================================== */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- 配置 --
     门户会话 token 的 localStorage 键。与下列各处必须一致（同一份凭据的多个载体）：
       · v3/team_portal/assets/olbr.js 的 TOKEN_KEY
       · v3/team-gate.js 的 TOKEN_KEY
       · Task/my_app/frontend/src/api.ts 的 PORTAL_TOKEN_KEY
     ⚠️ 本页**不依赖** localStorage —— 登录成功后靠的是服务端种下的
       HttpOnly Cookie（那是 nginx auth_request 唯一认的载体）。
       这里读 localStorage 只是为了「已经登着就别再让人登一次」。 */
  var TOKEN_KEY = 'liberia_noc_auth_v1';

  /** 登录 / 改密接口（与门户页同一个） */
  var LOGIN_URL = '/uniplam/api/auth/login';
  var CHANGE_PW_URL = '/uniplam/api/auth/change-password';

  /** 团队 id → 团队名（仅用于本页显示「你正在登录哪个团队的门」）。
     ⚠️ 这份映射与后端 server/auth/types.ts 的 TEAM_PORTAL_PATHS、
       v3/team-gate.js 的 TEAM_PORTAL 是**同一件事的三份字面量** ——
       纯静态脚本不能 import 后端模块，故只能各留一份。
       **改一处必须改其余各处。** */
  var TEAM_NAMES = {
    fo:  { zh: 'ZTE FO Team',  en: 'ZTE FO Team' },
    bo:  { zh: 'ZTE BO Team',  en: 'ZTE BO Team' },
    flm: { zh: 'ZTE FLM Team', en: 'ZTE FLM Team' },
    smc: { zh: 'Orange SMC',   en: 'Orange SMC' },
    cxo: { zh: 'Orange CXO',   en: 'Orange CXO' }
  };

  /* ------------------------------------------------------------- 文案 --
     与门户页 olbr-data.js 的 gate.* / ar.* 同一口径（同一件事不许说两套话），
     但**独立成一份** —— 本页不是门户页，不引 olbr-data.js（那份 1200+ 行，
     引它只是为了几行文案不值当）。改动时与 olbr-data.js 对齐。 */
  var I18N = {
    zh: {
      title: '团队门户 · 登录',
      sub: '团队门户需要登录后访问。请使用统一门户的账号登录。',
      team: '当前团队：',
      user: '用户名',
      pass: '密码',
      go: '登录',
      busy: '登录中…',
      newPw: '新密码（至少 8 位）',
      confirmPw: '再次输入新密码',
      submitPw: '提交新密码',
      submittingPw: '提交中…',
      request: '没有账号？申请一个',
      home: '返回统一门户',
      foot: '与 /uniplam/ 共用同一套账号与权限',
      bad: '用户名或密码错误',
      locked: '尝试次数过多，请稍后再试',
      net: '无法连接认证服务，请检查网络后重试',
      input: '用户名或密码格式不符合要求',
      server: '登录失败，请稍后重试',
      sessionOut: '检测到本机留有登录记录，但服务端会话已失效，请重新登录一次。',
      mustChange: '首次登录，请先设置新密码',
      pwMismatch: '两次输入的密码不一致',
      pwTooShort: '密码至少需要 8 个字符',
      pwDone: '密码已更新，正在进入…'
    },
    en: {
      title: 'Team Portal · Sign in',
      sub: 'The team portal requires a sign-in. Use your unified-portal account.',
      team: 'Team: ',
      user: 'Username',
      pass: 'Password',
      go: 'Sign in',
      busy: 'Signing in…',
      newPw: 'New password (min 8 chars)',
      confirmPw: 'Confirm new password',
      submitPw: 'Submit new password',
      submittingPw: 'Submitting…',
      request: 'No account? Request one',
      home: 'Back to unified portal',
      foot: 'Same account and permissions as /uniplam/',
      bad: 'Wrong username or password',
      locked: 'Too many attempts, try later',
      net: 'Cannot reach the auth service, please check your network',
      input: 'Invalid username or password format',
      server: 'Sign-in failed, please try again later',
      sessionOut: 'A previous sign-in was found on this browser, but the server session has expired. Please sign in again.',
      mustChange: 'First sign-in — please set a new password',
      pwMismatch: 'The two passwords do not match',
      pwTooShort: 'Password must be at least 8 characters',
      pwDone: 'Password updated, entering…'
    }
  };

  /* ---------------------------------------------------------------- 语言 --
     与门户页同一口径：用户显式选择优先（localStorage 'olbr.lang'），
     没有就按浏览器语言定默认（zh 前缀 → 中文）。 */
  function detectLang() {
    var v = null;
    try { v = localStorage.getItem('olbr.lang'); } catch (e) { /* ignore */ }
    if (v === 'en' || v === 'zh') return v;
    var nav = (navigator.language || navigator.userLanguage || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }

  var LANG = detectLang();
  var T = I18N[LANG] || I18N.zh;

  function $(id) { return document.getElementById(id); }

  /* ------------------------------------------------------------ 团队识别 --
     从 URL 前缀判定当前团队（/v3/bo_portal/ → bo）。
     ⚠️ 与 team-scope.js 的 detectTeam 同一套正则与口径 ——
       两者都靠 URL 前缀，不靠别处传来的参数（那会是可伪造的输入）。 */
  function detectTeam() {
    var m = /\/([a-z]+)_portal\//.exec(location.pathname || '');
    return (m && TEAM_NAMES[m[1]]) ? m[1] : '';
  }

  /* ---------------------------------------------------------------- 渲染 -- */
  function applyI18n() {
    document.documentElement.lang = LANG === 'en' ? 'en' : 'zh-CN';
    $('ttl').textContent = T.title;
    $('sub').textContent = T.sub;
    $('lblUser').textContent = T.user;
    $('lblPass').textContent = T.pass;
    $('lgo').textContent = T.go;
    $('lblNew').textContent = T.newPw;
    $('lblConfirm').textContent = T.confirmPw;
    $('pgo').textContent = T.submitPw;
    $('lnkReq').textContent = T.request;
    $('lnkHome').textContent = T.home;
    $('foot').textContent = T.foot;
    var team = detectTeam();
    if (team) {
      $('teamTag').classList.remove('hidden');
      $('teamTag').textContent = T.team + (TEAM_NAMES[team][LANG] || TEAM_NAMES[team].zh);
    }
  }

  function showErr(el, msg) {
    el.textContent = msg;
    el.classList.remove('hidden');
  }
  function hideErr(el) { el.classList.remove('hidden'); el.textContent = ''; el.classList.add('hidden'); }

  /* ------------------------------------------------------------ 登录 --
     detail（后端约定）→ 文案键。**必须覆盖后端会返回的所有 detail**，
     漏掉的那个会被当成网络故障报出去（门户页 olbr.js 踩过这个坑：
     2026-09-30 用户看到「无法连接鉴权服务」却其实是用户名格式不对）。
     口径与 olbr.js 的 login() 逐条对齐。 */
  function detailToMsg(detail, status) {
    if (status === 429) return T.locked;
    if (status === 401) return T.bad;
    if (detail === 'invalid_username' || detail === 'password_too_short' ||
        detail === 'invalid JSON payload') return T.input;
    return T.server;
  }

  function login(u, p) {
    return fetch(LOGIN_URL, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok || !d.token || !d.user) {
          var e = new Error(d.detail || 'login failed');
          e.msg = detailToMsg(d.detail, r.status);
          throw e;
        }
        return d;
      });
    }, function () {
      var e = new Error('network');
      e.msg = T.net;
      throw e;
    });
  }

  /* 改密（首次登录强制）。改完服务端会发**新** token 并作废旧会话 ——
     故这里必须把新 token 写回 localStorage，否则 reload 后前端那份是死的。
     ⚠️ 必须带 Authorization 头：改密端点在「未登录就 401」那道闸门**之后**，
       而闸门用的是 resolveCaller —— 它**只认 Authorization 头**（不读 Cookie）。
       所以本页改密时得像门户页那样把 Bearer 带上，否则回 401。 */
  function changePassword(cur, np, token) {
    return fetch(CHANGE_PW_URL, {
      method: 'POST', credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json', Accept: 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({ currentPassword: cur, newPassword: np })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var e = new Error(d.detail || 'change-password failed');
          e.msg = (d.detail === 'current password is incorrect') ? T.bad : T.server;
          throw e;
        }
        return d;
      });
    }, function () {
      var e = new Error('network');
      e.msg = T.net;
      throw e;
    });
  }

  /* ------------------------------------------------------------ 启动 --
     已经登着（localStorage 里有门户 token）就**先补一份 Cookie，再 reload** ——
     浏览器地址栏访问团队门户时，nginx 闸门只认 Cookie（olbr_token）；
     localStorage 那份是给页面的 JS 判「登没登录」用的。两份可能不同步
     （登出只清了一处、浏览器清了 Cookie 但没清 localStorage、改密作废了旧会话）。
     这时闸门会 401，用户被弹回本页。若不补，用户只能重新输密码 ——
     而他其实还有有效会话。
     ⚠️ 补 Cookie 走**登录接口**那一条路以外的办法：重新登录一次最简单，
       但那要用户再输一遍密码 —— 体验差。
       故这里用「带 token 的 /me 探测」：token 有效就说明会话还在，
       让页面**重新走一次登录**（用同一个凭据换一份新 Cookie）——
       ⚠️ 登录接口只认用户名 + 密码，不认 token，故此路不通。
       结论：这一档不做自动补 Cookie，改为**提示用户**：
       页面上直接给出「刷新仍失败？去统一门户登录一次」的出口。 */
  function boot() {
    applyI18n();
    var tk = null;
    try { tk = localStorage.getItem(TOKEN_KEY); } catch (e) { tk = null; }
    if (tk) {
      /* 有 token 却还是被闸门挡回来了 → 两份凭据不同步。
         提示一句，别让用户对着一个空表单发呆。 */
      showErr($('err'), T.sessionOut);
      $('lu').focus();
      return;
    }
    $('lu').focus();
  }

  /* ---------------------------------------------------------- 事件绑定 -- */
  function bind() {
    var lf = $('lf');
    lf.addEventListener('submit', function (e) {
      e.preventDefault();
      var err = $('err'), go = $('lgo');
      hideErr(err);
      var u = $('lu').value.trim(), p = $('lp').value;
      if (!u || !p) { showErr(err, T.input); return; }
      go.disabled = true; go.textContent = T.busy;
      login(u, p).then(function (d) {
        /* token 写回 localStorage —— 团队门户页（olbr.js）判「已登录」用的就是它。
           ⚠️ 服务端种下的 olbr_token Cookie 才是 nginx 闸门认的载体，
              localStorage 这份是给前端用的，两者同源同 token。 */
        try { localStorage.setItem(TOKEN_KEY, d.token); } catch (e) { /* ignore */ }
        /* 首次登录强制改密：服务端种下的 Cookie 是有效的，但前端要求先改密。
           改密会换发新 token（并作废旧会话），所以改完再 reload。 */
        if (d.user && d.user.mustChangePassword) {
          go.disabled = false; go.textContent = T.go;
          showErr($('ok'), T.mustChange);
          $('ok').classList.remove('hidden');
          lf.classList.add('hidden');
          $('pf').classList.remove('hidden');
          $('np').focus();
          return;
        }
        /* 正常登录：reload 让 nginx 闸门重新判定（Cookie 已就位 → 放行）。
           ⚠️ 用 reload 而不是 replace：地址栏要留在 /v3/<team>_portal/，
              用户刷新时才能继续站在这一页。 */
        location.reload();
      }).catch(function (x) {
        showErr(err, x.msg || T.net);
        go.disabled = false; go.textContent = T.go;
        $('lp').value = '';
        $('lp').focus();
      });
    });

    $('pf').addEventListener('submit', function (e) {
      e.preventDefault();
      var err = $('perr'), go = $('pgo');
      hideErr(err);
      var np = $('np').value, np2 = $('np2').value;
      if (np.length < 8) { showErr(err, T.pwTooShort); return; }
      if (np !== np2) { showErr(err, T.pwMismatch); return; }
      go.disabled = true; go.textContent = T.submittingPw;
      var cur = $('lp').value;
      var tk = null;
      try { tk = localStorage.getItem(TOKEN_KEY); } catch (e) { tk = null; }
      changePassword(cur, np, tk).then(function (d) {
        if (d && d.token) {
          try { localStorage.setItem(TOKEN_KEY, d.token); } catch (e) { /* ignore */ }
        }
        /* 改密作废了旧会话 → 旧 Cookie 随之失效 → 闸门会 401。
           ⚠️ 这里**不能**直接 reload（会回到本页重来一遍）。
           故明确提示：改密完成，请用新密码重新登录一次（Cookie 才会重新种下）。
           —— 这是服务端「改密即作废旧会话」的既定语义，不是本次引入的。 */
        $('ok').classList.remove('hidden');
        $('ok').textContent = T.pwDone;
        $('lf').classList.remove('hidden');
        $('pf').classList.add('hidden');
        $('lp').value = '';
        $('lu').focus();
      }).catch(function (x) {
        showErr(err, x.msg || T.server);
        go.disabled = false; go.textContent = T.submitPw;
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { applyI18n(); bind(); boot(); });
  } else {
    applyI18n(); bind(); boot();
  }
})();
