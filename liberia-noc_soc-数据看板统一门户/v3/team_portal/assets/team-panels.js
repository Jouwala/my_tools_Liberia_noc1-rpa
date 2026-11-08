/* ============================================================================
   team-panels.js —— 团队门户专属的两块面板（2026-10-29 加）
   ----------------------------------------------------------------------------
   门户的通用页面（v3/olbrportal/）里有两块内容，**不能**直接复用，团队门户
   另做了一份：

   ① Auto Report（#emailSlot）
      上游那块是内嵌 my_app 的 `?page=email_reports`，那个页面渲染的是**全部**
      报告源（后端 /api/email-reports/latest 有 14 个源），无法按 source_id 过滤。
      而《新看板设计.xlsx》的 Auto-report 域是**逐条**勾选了要哪几种报告 ——
      所以这里自己拉一次接口、按矩阵过滤、渲染成一张表。
      好处：不必改 my_app 那一侧（那是别人的页面），团队门户要的粒度也刚好够。

   ② Customer Complaint（#complaintSlot）
      上游页面里**没有**这一块（门户从未做过客户投诉入口），它对应 my_app 的
      /myapp/?page=vmax_user_query（VMAX CCA 投诉系统，按号码查用户与投诉根因）。
      Excel 里是一个独立的一行，故单独一块。

   两者都在 SCOPE 为 null（上游页面）时完全不动作 —— 上游那一份文件**一行未改**。

   依赖：window.OLBR_SCOPE（见 assets/team-scope.js）。
   ========================================================================== */
(function () {
  'use strict';

  var SCOPE = window.OLBR_SCOPE || null;
  if (!SCOPE) return;

  /* ---------------------------------------------------------------- 文案 --
     刻意**不**放进 olbr-data.js 的两份字典：那份字典是上游 olbrportal 逐字共享的，
     在团队门户这一侧加键会造成「同一份文件两边内容不同」，将来上游更新覆盖时
     这里会莫名其妙地少几条。故团队门户自备一份小字典。 */
  var I18N = {
    zh: {
      reportsTitle: 'Auto Report',
      reportsSub: '按团队权限过滤的邮件报告附件',
      colTask: '报告类型',
      colFile: '文件',
      colSize: '大小',
      colTime: '生成时间',
      colDownload: '下载',
      refresh: '刷新报告列表',
      loading: '正在加载报告…',
      needLogin: '登录后显示报告文件',
      loadFailed: '报告列表加载失败',
      empty: '暂无报告',
      complaintTitle: 'Customer Complaint',
      complaintSub: 'VMAX CCA 投诉系统 · 按号码查询用户信息与投诉根因',
      complaintOpen: '打开 VMAX 用户查询',
      complaintNote: '本块对应 VMAX 用户查询页（投诉系统）。'
    },
    en: {
      reportsTitle: 'Auto Report',
      reportsSub: 'Email report attachments filtered by team scope',
      colTask: 'Report Type',
      colFile: 'File',
      colSize: 'Size',
      colTime: 'Generated',
      colDownload: 'Download',
      refresh: 'Refresh report list',
      loading: 'Loading reports…',
      needLogin: 'Sign in to view the report files',
      loadFailed: 'Failed to load report list',
      empty: 'No report yet',
      complaintTitle: 'Customer Complaint',
      complaintSub: 'VMAX CCA complaint system · subscriber info and complaint root causes by number',
      complaintOpen: 'Open VMAX User Query',
      complaintNote: 'This block maps to the VMAX user query page (complaint system).'
    }
  };
  /* ⚠️ 与 olbr.js 的 state.lang / detectLang() 同源：setLang() 会先写
     localStorage 'olbr.lang' 再 render()，所以这里读到的永远是最新选择。 */
  function lang() {
    var v = null;
    try { v = localStorage.getItem('olbr.lang'); } catch (e) { /* 隐私模式 */ }
    if (v === 'en' || v === 'zh') return v;
    var nav = (navigator.language || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }
  function t(k) {
    var d = I18N[lang()] || I18N.zh;
    return d[k] != null ? d[k] : (I18N.zh[k] != null ? I18N.zh[k] : k);
  }
  /* ---------------------------------------------------- 报告接口的语言头 --
     ⚠️ 2026-11-06（用户报「Auto Report 里 Report Type 没做好国际化」）根因：
       Report Type 列的 task_name / label **不是前端文案**，是 my_app 后端
       /api/email-reports/latest 返回的字段。那个接口的 _req_lang() 只读
       **Accept-Language 请求头**（`startswith('en')` → en，其余 zh），
       不读 `?lang=`（实测带 ?lang=en 返回的仍是中文）。
       浏览器裸 fetch 自动带的 Accept-Language 是**浏览器系统语言**，
       与门户里用户点 EN / 中文 选的语言无关 —— 于是英文界面下这一列
       整列中文（"电池 KPI 邮件 / Site Down 8H 报告"），而表头是英文。

       修法：显式把门户当前语言写进请求头，让后端按语言返回已经维护好的
       zh/en 报告名（_SOURCES 的 label/label_en、TASK_SPECS 的 name/name_en）。
       ⚠️ **不要在前端再造一份报告名译文表**：后端 _SOURCES 是唯一真相源，
       新增报告源时只改后端一处；前端再存一份必然漂移，且要对账 13 个键。 */
  function reportHeaders() {
    return { Accept: 'application/json', 'Accept-Language': lang() === 'en' ? 'en' : 'zh' };
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function fmtSize(n) {
    if (n == null) return '—';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }
  function fmtTime(ts) {
    if (!ts) return '—';
    var d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return '—';
    var p = function (x) { return (x < 10 ? '0' : '') + x; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  /* ========================================================== Auto Report ==
     表体。列与 my_app 的 email_reports 精简模式一致（任务 / 类型 / 文件 / 大小 /
     生成时间 / 下载），但只列本团队勾了的报告源。

     ⚠️ 为什么不用 iframe 内嵌 my_app：那个页面拿不到「只显示哪几个源」的参数，
       而 Excel 的勾选粒度正是「哪几个源」。另做一张表是最小代价。

     数据源：/api/email-reports/latest?limit=1（与 my_app 同一接口、同源，
     登录态由 Cookie 携带，故受门户登录门保护 —— 与上游那块的行为一致）。 */
  /* lang 记录**这批 rows 是用哪门语言取回来的**。报告名由后端按语言返回，
     所以语言一换旧数据就作废，必须重拉（见 render() 里的 shellLang 判据）。 */
  var reportState = { rows: [], loading: false, err: '', loaded: false, lang: null };

  function downloadUrl(sourceId, name) {
    return '/api/email-reports/download/' + encodeURIComponent(sourceId) + '/' + encodeURIComponent(name);
  }

  function loadReports(force) {
    if (reportState.loading) return;
    var wantLang = lang();
    if (reportState.loaded && !force && reportState.lang === wantLang) { renderReportsTable(); return; }
    reportState.loading = true;
    reportState.err = '';
    reportState.lang = wantLang;
    /* 2026-10-30：走**会话自愈**的取数通道，与 olbr.js 的 api() 同一套。
       为什么必须这样：本文件是团队门户**专有**资产，自带一个裸 fetch ——
       它不走 olbr.js 的 api()，故拿不到「401 → 换会话 → 重试」的自愈。
       实测 /api/email-reports/latest 在远端无会话时回 401，症状是
       Auto Report 表整块显示「加载失败」—— 与本次修复的 QC 红点是同一个病根。
       ⚠️ window.OLBR_SESSION 不存在时（理论上不会：本文件只在团队门户里被引，
         而 team-session.js 与它同在 assets/）退回裸 fetch，行为与改动前一致。
       2026-11-06：两条分支合并成一个 fetchJson，确保「带 Accept-Language」这条
       规则只有一处、401 重试时也不会丢头。 */
    function fetchJson(u) {
      return fetch(u, { credentials: 'same-origin', headers: reportHeaders() })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        });
    }
    var SESSION = window.OLBR_SESSION || null;
    var doFetch = SESSION ? SESSION.retryOn401(fetchJson) : fetchJson;
    doFetch('/api/email-reports/latest?limit=1').then(function (d) {
      /* 请求在途时用户切了语言 → 这份是旧语言的数据，直接丢弃；
         末尾的收尾逻辑会按新语言重拉一次。 */
      if (lang() !== wantLang) return;
      var allow = SCOPE.reportIds();
      var rows = [];
      (d && d.reports ? d.reports : []).forEach(function (src) {
        if (allow.indexOf(src.source_id) === -1) return;   /* 本团队没勾这一项 */
        (src.files || []).forEach(function (f) {
          rows.push({
            source_id: src.source_id,
            task_name: src.task_name || src.label || src.source_id,
            label: src.label || '',
            name: f.name,
            size: f.size,
            mtime: f.mtime
          });
        });
      });
      rows.sort(function (a, b) { return (b.mtime || 0) - (a.mtime || 0); });
      reportState.rows = rows;
      reportState.loaded = true;
    }).catch(function (e) {
      reportState.err = String((e && e.message) || e);
    }).then(function () {
      reportState.loading = false;
      /* 语言在请求途中变了：这次结果已作废，立刻按当前语言重拉。
         loadReports(true) 会把 reportState.lang 更新成新语言，故不会循环。 */
      if (lang() !== reportState.lang) {
        reportState.loaded = false;
        reportState.rows = [];
        reportState.err = '';
        loadReports(true);
        return;
      }
      renderReportsTable();
    });
  }

  function reportRowsHtml() {
    if (reportState.err) {
      return '<tr><td colspan="5" class="tr-empty">' + esc(t('loadFailed')) + '</td></tr>';
    }
    /* 还没取到数据（首屏 / 切语言重拉中）时表体留空，
       由骨架里的 .embed-boot 显示「正在加载报告…」，不要抢先显示「暂无报告」。 */
    if (!reportState.loaded || reportState.loading) return '';
    if (!reportState.rows.length) {
      return '<tr><td colspan="5" class="tr-empty">' + esc(t('empty')) + '</td></tr>';
    }
    return reportState.rows.map(function (r) {
      return '<tr>' +
        '<td>' + esc(r.task_name) + (r.label ? ' <span class="tr-sub">' + esc(r.label) + '</span>' : '') + '</td>' +
        '<td class="tr-file">' + esc(r.name) + '</td>' +
        '<td class="tr-num">' + esc(fmtSize(r.size)) + '</td>' +
        '<td class="tr-num">' + esc(fmtTime(r.mtime)) + '</td>' +
        '<td><a class="tr-dl" href="' + esc(downloadUrl(r.source_id, r.name)) +
          '" download title="' + esc(r.name) + '">' + esc(t('colDownload')) + '</a></td>' +
        '</tr>';
    }).join('');
  }

  function renderReportsTable() {
    var host = document.getElementById('teamReportHost');
    if (!host) return;
    var body = document.getElementById('teamReportBody');
    if (body) body.innerHTML = reportRowsHtml();
    var cnt = document.getElementById('teamReportCount');
    if (cnt) cnt.textContent = String(reportState.rows.length);
    var boot = document.getElementById('teamReportBoot');
    /* 取数中 / 尚未取到（含切语言后作废重拉）时保留加载提示，
       加载完成或出错才收起。原先是无条件 hidden=true，切语言时会闪一下空表。 */
    if (boot) boot.hidden = !(reportState.loading || !reportState.loaded) || !!reportState.err;
  }

  /* 面板外壳。结构与上游的 emailSectionHtml() 同款（.p-head + .canvas），
     以便 .qarow / .email-slot 的 CSS 直接适用。 */
  function reportsShellHtml() {
    return '<div class="p-head"><span class="p-hd"><span class="p-t t-orange">' +
        esc(t('reportsTitle')) + '</span></span>' +
      '<div class="map-tools"><span class="cnt" id="teamReportCount">0</span>' +
      '<button type="button" class="gb gb--t" id="teamReportReload" title="' + esc(t('refresh')) + '">' +
        '<i class="ph ph-arrow-clockwise" aria-hidden="true"></i></button></div></div>' +
      '<div class="canvas" id="teamReportHost">' +
        '<table class="tr-table"><thead><tr>' +
          '<th>' + esc(t('colTask')) + '</th>' +
          '<th>' + esc(t('colFile')) + '</th>' +
          '<th>' + esc(t('colSize')) + '</th>' +
          '<th>' + esc(t('colTime')) + '</th>' +
          '<th>' + esc(t('colDownload')) + '</th>' +
        '</tr></thead><tbody id="teamReportBody"></tbody></table>' +
        '<div class="embed-boot" id="teamReportBoot"><i class="embed-ring" aria-hidden="true"></i>' +
        '<span>' + esc(t('loading')) + '</span></div>' +
      '</div>';
  }

  /* ⚠️ 2026-11-06（同一个 bug 的第二半）：外壳的表头 / 提示是**一次性生成的
     静态 HTML**，原判据只看「#teamReportHost 在不在」。点 EN/中文 后 olbr.js 的
     render() 会再次调用本函数，外壳却原地不动 —— 实测 en→zh 后表头仍是
     "Report Type"、下载列仍是 "Download"，只有投诉面板跟着变（它每次重建）。
     现在按 shellLang 判据：语言变了就重建外壳，并作废属于旧语言的 rows 重拉。 */
  var shellLang = null;
  function render(el) {
    if (!el) return;
    var L = lang();
    var changed = (shellLang !== L);
    if (!el.querySelector('#teamReportHost') || changed) {
      el.innerHTML = reportsShellHtml();
      shellLang = L;
      var btn = document.getElementById('teamReportReload');
      if (btn) btn.addEventListener('click', function () { loadReports(true); });
    }
    if (changed) {
      /* 报告名由后端按语言返回，旧 rows 属于上一门语言，不能留着显示。 */
      reportState.loaded = false;
      reportState.rows = [];
      reportState.err = '';
    }
    loadReports(false);
    renderReportsTable();
  }

  /* ==================================================== Customer Complaint ==
     一块卡片式入口：点开跳 my_app 的 VMAX 用户查询页（投诉系统）。
     用「卡片」而不是 iframe 的理由与 OSS 那一块一致 —— 那是个需要输入号码的
     查询页，嵌进来只会得到一个空表单，看不出能干什么。 */
  function complaintShellHtml() {
    var href = '/myapp/?page=vmax_user_query&embed=1&lang=' + (lang() === 'en' ? 'en' : 'zh');
    return '<div class="p-head"><span class="p-hd"><span class="p-t t-orange">' +
        esc(t('complaintTitle')) + '</span></span>' +
      '<div class="map-tools"><span class="cnt">1</span></div></div>' +
      '<div class="oss-grid is-single">' +
        '<a class="oss-card" href="' + esc(href) + '" target="_blank" rel="noopener noreferrer" ' +
          'title="' + esc(t('complaintSub')) + '">' +
          '<span class="oss-card-ico"><i class="ph ph-user-focus" aria-hidden="true"></i></span>' +
          '<span class="oss-card-t">' + esc(t('complaintOpen')) + '</span></a>' +
      '</div>';
  }

  function renderComplaint(el) {
    if (!el) return;
    el.innerHTML = complaintShellHtml();
  }

  /* ------------------------------------------------------------ 导出 ---- */
  window.OLBR_TEAM_REPORTS = {
    render: render,
    renderComplaint: renderComplaint,
    loadReports: loadReports
  };
})();
