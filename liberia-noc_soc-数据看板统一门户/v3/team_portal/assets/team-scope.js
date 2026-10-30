/* ============================================================================
   team-scope.js —— 团队门户的可见性作用域引擎
   ----------------------------------------------------------------------------
   作用：把《新看板设计.xlsx》里「某团队勾了哪些内容」这件事，变成
   olbr.js 渲染时能逐项取用的判据。

   设计要点
   ----------------------------------------------------------------------------
   ① **矩阵来自生成文件，不写死在本文件里。**
      window.OLBR_TEAM_MATRIX 由 scripts/gen_team_matrix.py 从 Excel 生成
      （见 assets/team-matrix.js 头部的说明）。本文件只负责「怎么用」。

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

   ⑤ **目录条目与 Excel 的对应关系走「子键 → 目录条目」映射表**
      （OSS_SLOTS / VIEW_GROUPS 等），不靠标题字符串模糊匹配 ——
      标题会被人改（目录是可编辑的），模糊匹配会突然失效。
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

  /* ---------------------------------------------------------------- 查询 --
     ok(domain, sub)：该团队是否勾了这一项。
     sub 省略时判「这个域至少勾了一项」。 */
  function ok(domain, sub) {
    if (!TEAM_ID) return false;          /* 不是团队门户 → 什么都不显示 */
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
     Excel 的「OSS Portal Login」域列了 10 个条目，门户目录里的 Friends Link
     分组有 11 条 —— 两者不是一一对应：
       · 「ZTE UME NMSCCN」= 目录里的「ZTE UME NMS」+「CCN UME NMS」两条
       · 目录里的「Portal Login」是**网管门户一键登录页**（my_app 的 portalLogin），
         与 Excel 的「Portal Login (NMS Portal One-click Login)」指的是同一件事
       · Excel 里有「UME iMonitor Screen」，目录里对应「UME iMonitor 大屏」与
         「OCS iMonitor Screen」两条
     故这里显式列出「槽位 → 目录条目 url 片段」的对应表。
     匹配用 url 里的 page= / 主机名片段，不匹配标题 —— 标题可编辑，url 稳定。 */
  var OSS_SLOTS = {
    portalLogin: ['page=portalLogin'],
    nmsccn:      ['192.168.100.19', '10.100.28.27', '10.121.1.2'],
    ipran:       ['10.100.2.99'],
    mw:          ['192.168.169.247'],
    fwumc:       ['10.100.2.101'],
    vmaxcxo:     ['10.123.255.12'],
    imonitor:    ['172.17.208.1', 'page=imonitor'],
    eflow:       ['10.100.20.8'],
    rais:        ['10.100.20.9'],
    dcserver:    ['10.121.8.2']
  };

  /* 目录条目 → OSS 槽位。url 含任一片段即归入该槽位。 */
  function ossSlotOf(item) {
    var u = String((item && item.url) || '');
    for (var slot in OSS_SLOTS) {
      if (!Object.prototype.hasOwnProperty.call(OSS_SLOTS, slot)) continue;
      var pats = OSS_SLOTS[slot];
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
     （见 gen_team_matrix.py 的 DETAIL_BY_DOMAIN），故这里直接用。
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

  /* ========================================================== 其它单值域 == */
  function hasComplaint() { return ok('complaint', 'vmax'); }
  function hasEscalation() { return ok('escalation', 'esc'); }
  function hasFeedback() { return ok('feedback', 'fb'); }

  /* ============================================================ 导出 == */
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
    hasFeedback: hasFeedback
  };

  /* 让调试时能一眼看到当前团队：控制台打印一行矩阵摘要。 */
  if (TEAM_ID) {
    var summary = {};
    for (var dom in MATRIX) {
      if (!Object.prototype.hasOwnProperty.call(MATRIX, dom)) continue;
      var picked = subs(dom);
      if (picked.length) summary[dom] = picked;
    }
    console.info('[team-scope] 团队门户：%s（%s）', TEAMS[TEAM_ID].zh, TEAM_ID);
    console.info('[team-scope] 可见范围：', summary);
  }
})();
