/* ============================================================================
   team-scope.js —— 团队门户的可见性作用域引擎
   ----------------------------------------------------------------------------
   作用：把「某团队勾了哪些内容」这件事，变成 olbr.js 渲染时能逐项取用的判据。

   设计要点
   ----------------------------------------------------------------------------
   ① **矩阵来自生成文件，不写死在本文件里。**
      window.OLBR_TEAM_MATRIX 由 scripts/gen_team_matrix.py 从
      v3/team_portal/scope-map.json 生成（见 assets/team-matrix.js 头部说明）。
      本文件只负责「怎么用」。

   ② **本文件不改动 olbr.js 一行。**
      它在 olbr.js 加载**之后**运行，通过覆盖 window 上的一小组钩子来生效：
      olbr.js 的每个渲染函数都调用 window.OLBR_SCOPE.* 这类查询，
      而这些查询由本文件提供实现。olbr.js 里只增加「调用点」，
      每个调用点都是一行 `if (!SCOPE.ok('qc','alarm')) return '';` 这种形态。

      为什么不 fork olbr.js：那 37 万字符的脚本 fork 一次就是两份真相源，
      后续每次上游改动都要手工合并一遍，必然漂移。改成「薄适配层」后，
      上游 olbr.js 的修复能直接被五个团队门户继承。

   ③ **五个团队门户共用这一份资产**（v3/team_portal/），
      靠 URL 前缀判断当前是哪个团队：
        /v3/fo_portal/  → fo
        /v3/bo_portal/  → bo
        /v3/flm_portal/ → flm
        /v3/smc_portal/ → smc
        /v3/cxo_portal/ → cxo
      nginx 侧五个 location 全部 alias 到同一个目录。

   ④ **矩阵缺项 = 不显示**，矩阵多项 = 照单显示。
      没有「默认全显」的兜底：矩阵是需求文档的机器可读形式，
      缺一行就意味着那行没勾，不显示是唯一正确的行为。

   ⑤ **运行时以服务端的矩阵为准**（2026-10-30 加）。
      管理员可以在门户的「团队可见性」界面里直接勾选，勾选结果落进服务端数据库。
      本文件启动时向 /api/auth/team-scope 取矩阵；取不到才退回
      window.OLBR_TEAM_MATRIX（仓库里的静态生成物，即 scope-map.json 的快照）。

      ⚠️ 取不到时的行为是**「什么都不显示」**，不是「回退到静态矩阵」。
      理由：静态矩阵可能已经过期（管理员改过了但静态文件没重新生成），
      拿它兜底 = 把旧权限又放出来一次 —— 那正是权限事故。
      故静态矩阵只作为「**首次访问、还没登录**」时的极短过渡，
      且过渡期间同样不显示任何内容（见下方 matrix 的选择逻辑）。
   ========================================================================== */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- 团队 --
     从 URL 前缀判定当前团队。取 pathname 的第一段有歧义（/v3/xxx_portal/），
     故按「含 _portal 且前面是已知团队缩写」来认。 */
  var TEAMS = {
    fo:  { id: 'fo',  zh: 'ZTE FO Team',  en: 'ZTE FO Team' },
    bo:  { id: 'bo',  zh: 'ZTE BO Team',  en: 'ZTE BO Team' },
    flm: { id: 'flm', zh: 'ZTE FLM Team', en: 'ZTE FLM Team' },
    smc: { id: 'smc', zh: 'Orange SMC',   en: 'Orange SMC' },
    cxo: { id: 'cxo', zh: 'Orange CXO',   en: 'Orange CXO' }
  };

  function detectTeam() {
    var m = /\/([a-z]+)_portal\//.exec(location.pathname || '');
    return (m && TEAMS[m[1]]) ? m[1] : '';
  }

  var TEAM_ID = detectTeam();
  var MATRIX = window.OLBR_TEAM_MATRIX || {};

  /* ---------------------------------------------------------- 鉴权接口地址 --
     团队门户有两种访问方式，两者的鉴权接口路径不同：
       · 经 nginx 走 /uniplam/ 前缀 → /uniplam/api/auth/team-scope
       · 直连 vite dev（:9267）      → /api/auth/team-scope
     门户后端两条路径都挂了（见 vite.config.ts 的 portalAuthPlugin），
     所以这里按「页面上是否带着 /uniplam/ 前缀」来挑，取不到就两个都试。
     ⚠️ 不能硬编码 /uniplam/ —— 本机调试时那路径是 404，
     结果是矩阵永远取不到 → fail-closed → 页面什么都不显示（看起来像功能坏了）。 */
  function scopeApiPaths() {
    var p = location.pathname || '';
    var m = /^(.*?)\/v3\//.exec(p);
    var prefix = m ? m[1] : '';
    var paths = [];
    if (prefix) paths.push(prefix + '/api/auth/team-scope');
    paths.push('/uniplam/api/auth/team-scope');
    paths.push('/api/auth/team-scope');
    return paths;
  }

  /* 依次试各候选路径，第一个拿到 2xx 的就用它。
     ⚠️ 必须真的试而不是猜 —— 门户后端两条路径都挂着（vite.config.ts 的
     portalAuthPlugin），但线上由 nginx 决定走哪条，页面自己不一定知道。 */
  function fetchScopeJson(tk) {
    var paths = scopeApiPaths();
    var i = 0;
    function attempt() {
      if (i >= paths.length) return Promise.resolve(null);
      var url = paths[i++];
      return fetch(url, {
        credentials: 'same-origin',
        headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { return d && d.matrix ? d : attempt(); })
        .catch(function () { return attempt(); });
    }
    return attempt();
  }

  /* ------------------------------------------------------------ 作用域映射 --
     **生成物**：由 scripts/gen_team_matrix.py 从 v3/team_portal/scope-map.json
     一并产出（与 team-matrix.js 同源）。

     结构：{ 域键: { 子键: { urlPatterns: [...] } } }
     目前只有 OSS 域用到 urlPatterns（槽位 → 门户目录条目的匹配依据）。
     把它从本文件挪到生成物里，是为了消掉「同一份映射在两个文件各维护一半」：
     此前 DETAIL_MAP（Excel 文案 → 子键）在 Python 侧、OSS_SLOTS（子键 → url
     片段）在 JS 侧，加一行内容要改两个文件、漏一个就静默失效。

     ⚠️ 上游 /v3/olbrportal/ 不引这个文件 → SCOPE_MAP 为 null，
       但那一侧 SCOPE 也是 null，整段逻辑短路，行为不变。 */
  var SCOPE_MAP = window.OLBR_SCOPE_MAP || null;

  /* ------------------------------------------------------------ 运行时矩阵 --
     矩阵的来源有两层：
       ① window.OLBR_TEAM_MATRIX —— 仓库里的静态生成物（scope-map.json 的快照）
       ② 服务端 /uniplam/api/auth/team-scope —— **运行时的真相源**（管理员可编辑）

     优先级：② 覆盖 ①。
     ⚠️ 但 ② 取不到时**不能**静默退回 ① 并继续显示内容 ——
       静态矩阵可能已经过期（管理员改过了但静态文件没重新生成），
       拿它兜底 = 把旧权限又放出来一次，那正是权限事故。
       故：② 取不到 → 矩阵置空 → 什么都不显示（fail-closed）。

     为什么服务端返回的是**已经按团队过滤好**的矩阵：
       门户不该知道别的团队勾了什么（信息泄露），前端也只需要
       「我能不能看这一项」这一个比特。服务端过滤是唯一正确的位置。
       过滤后每项的团队列表是 [当前团队]，故下面的 indexOf(TEAM_ID) 仍然成立。 */
  var MATRIX = window.OLBR_TEAM_MATRIX || {};
  var matrixLoaded = false;

  /** 取运行时的矩阵（按当前团队过滤后的）。 */
  function fetchRuntimeMatrix() {
    var tk = null;
    try { tk = localStorage.getItem('liberia_noc_auth_v1'); } catch (e) { tk = null; }
    if (!tk) {
      /* 没登录 → 没有团队身份 → 什么都不显示。
         ⚠️ 不退回静态矩阵：静态矩阵里写着五个团队的勾选，
           拿它兜底会让「未登录」也能看到内容。 */
      MATRIX = {};
      matrixLoaded = true;
      return Promise.resolve(null);
    }
    return fetchScopeJson(tk)
      .then(function (d) {
        if (d && d.matrix && typeof d.matrix === 'object') {
          MATRIX = d.matrix;
          matrixLoaded = true;
          return d;
        }
        /* 服务端没给矩阵（出错/未登录）→ fail-closed：置空，不显示任何内容。 */
        MATRIX = {};
        matrixLoaded = true;
        return null;
      });
  }

  /* OSS 槽位 → 目录条目 url 片段。
     Excel 的「OSS Portal Login」域列了 10 个条目，门户目录里的 Friends Link
     分组有 11 条 —— 两者不是一一对应：
       · 「ZTE UME NMSCCN」= 目录里的「ZTE UME NMS」+「CCN UME NMS」两条
       · 目录里的「Portal Login」是**网管门户一键登录页**（my_app 的 portalLogin），
         与 Excel 的「Portal Login (NMS Portal One-click Login)」指的是同一件事
       · Excel 里有「UME iMonitor Screen」，目录里对应「UME iMonitor 大屏」与
         「OCS iMonitor Screen」两条
     匹配用 url 里的 page= / 主机名片段，不匹配标题 —— 标题可编辑，url 稳定。 */
  function ossPatterns(slot) {
    if (!SCOPE_MAP || !SCOPE_MAP.oss) return [];
    var item = SCOPE_MAP.oss[slot];
    return (item && item.urlPatterns) || [];
  }

  /* ---------------------------------------------------------------- 查询 --
     ok(domain, sub)：该团队是否勾了这一项。
     sub 省略时判「这个域至少勾了一项」。

     ⚠️ matrixLoaded 为 false（运行时矩阵还没取回来）时一律返回 false ——
       那一小段时间里页面什么都不显示。取回来后由 refresh() 重画。
       这比「先用静态矩阵画一遍、再换成运行时矩阵重画」好：
       后者会让用户先看到一版可能**已经过期**的权限内容再消失。 */
  function ok(domain, sub) {
    if (!TEAM_ID) return false;          /* 不是团队门户 → 什么都不显示 */
    if (!matrixLoaded) return false;      /* 矩阵未就绪 → fail-closed */
    var d = MATRIX[domain];
    if (!d) return false;
    if (sub == null) {
      for (var k in d) {
        if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
        if (d[k].indexOf(TEAM_ID) !== -1) return true;
      }
      return false;
    }
    var list = d[sub];
    return !!(list && list.indexOf(TEAM_ID) !== -1);
  }

  /* 域内被勾中的子键清单（保持矩阵里的顺序 = Excel 里的顺序）。 */
  function subs(domain) {
    var d = MATRIX[domain] || {};
    var out = [];
    for (var k in d) {
      if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
      if (d[k].indexOf(TEAM_ID) !== -1) out.push(k);
    }
    return out;
  }

  /* ============================================================ OSS 槽位 ==
     目录条目 → OSS 槽位。url 含任一片段即归入该槽位。 */
  function ossSlotOf(item) {
    var u = String((item && item.url) || '');
    for (var slot in SCOPE_MAP.oss) {
      if (!Object.prototype.hasOwnProperty.call(SCOPE_MAP.oss, slot)) continue;
      var pats = ossPatterns(slot);
      for (var i = 0; i < pats.length; i++) {
        if (u.indexOf(pats[i]) !== -1) return slot;
      }
    }
    return '';
  }

  /* 本团队勾中的 OSS 槽位。 */
  function ossSlots() {
    return subs('oss');
  }

  /* ========================================================== 视图分组 ==
     Excel 的 Domain Dashboard 域右值已经是门户目录的分组 id
     （见 scope-map.json），故这里直接用。
     仍然把它导出成一份，是为了让 olbr.js 的调用点只认一个入口。 */
  function viewGroups() {
    return subs('view');
  }

  /* ============================================================ 地图页签 ==
     Excel 的 GIS MAP 域 → DATA.MAP_TABS 的 page（gis / person / mwRealTime）。 */
  function mapPages() {
    return subs('map');
  }

  /* ========================================================== 问答页签 ==
     · eflow  = 「TT/Alarm Analysis」（eFlow 知识库）
     · rag    = 「Knowledge O&A」（本地知识问答）
     · assistant = 「Quick Q&A」（右下角悬浮问答助手） */
  function qaTabs() {
    return subs('qa');
  }

  /* ========================================================== 报告清单 ==
     Excel 的 Auto-report 域 → /api/email-reports/latest 的 source_id。 */
  function reportIds() {
    return subs('report');
  }

  /* ============================================================ 其它单值域 == */
  function hasComplaint() { return ok('complaint', 'vmax'); }
  function hasEscalation() { return ok('escalation', 'esc'); }
  function hasFeedback() { return ok('feedback', 'fb'); }

  /* ================================================================ 导出 == */
  window.OLBR_SCOPE = {
    teamId: TEAM_ID,
    team: TEAMS[TEAM_ID] || null,
    isTeamPortal: !!TEAM_ID,
    matrix: MATRIX,
    ok: ok,
    subs: subs,
    ossSlotOf: ossSlotOf,
    ossSlots: ossSlots,
    viewGroups: viewGroups,
    mapPages: mapPages,
    qaTabs: qaTabs,
    reportIds: reportIds,
    hasComplaint: hasComplaint,
    hasEscalation: hasEscalation,
    hasFeedback: hasFeedback,
    /**
     * 取回运行时矩阵后重画整页。
     *
     * 为什么要单独提供这个钩子：olbr.js 的 boot() 是在 DOMContentLoaded 时
     * 同步跑完的，而矩阵是**异步**取回来的。若不重画，页面就停在
     * 「矩阵未就绪 → 什么都不显示」的状态。
     *
     * ⚠️ 这里不能自己调 olbr.js 的 render() —— 那是 IIFE 里的私有函数，
     *   拿不到。故改为派发一个**自定义事件**，由 olbr.js 监听后自己重画
     *   （见 scripts/patch_team_portal.py 的 scope-refresh 钩子）。
     *   事件名带 'olbr' 前缀，避免与页面上的其它事件撞名。
     */
    refresh: function () {
      document.dispatchEvent(new CustomEvent('olbr:scope-ready'));
    }
  };

  /* ---------------------------------------------------------------- 启动 --
     取运行时矩阵；取回后派发事件让页面重画。 */
  function boot() {
    if (!TEAM_ID) {
      /* 不是团队门户：本文件不该被引入。真被引入了也不做任何过滤。 */
      matrixLoaded = true;
      return;
    }
    fetchRuntimeMatrix().then(function () {
      window.OLBR_SCOPE.refresh();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  /* 让调试时能一眼看到当前团队：控制台打印一行矩阵摘要。 */
  if (TEAM_ID) {
    var summary = {};
    for (var dom in MATRIX) {
      if (!Object.prototype.hasOwnProperty.call(MATRIX, dom)) continue;
      var picked = subs(dom);
      if (picked.length) summary[dom] = picked;
    }
    console.info('[team-scope] 团队门户：%s（%s）', TEAMS[TEAM_ID].zh, TEAM_ID);
    console.info('[team-scope] 静态矩阵摘要（运行时会用服务端矩阵覆盖）：', summary);
  }
})();
