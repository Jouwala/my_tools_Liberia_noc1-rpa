/* ============================================================================
   access.js — MsPortal 访问控制共享模块（2026-09-20 加）
   ----------------------------------------------------------------------------
   为什么单独一个文件、而不是留在 portal.js 里：
     「这个账号能不能看这张看板」需要两件事：
       ① 把 MsPortal 的卡片 URL 映射成**统一门户的看板 id**（DashboardItem.id）
          —— allowedCards 用的是那一套 id（用户在用户管理里勾的就是它）；
       ② 按 allowedGroups / allowedCards 判定放行。
     这两件事**门户首页（portal.js）和看板查看器（viewer.js）都要做**，而查看器
     原先完全没有做 —— 结果是一个真实的越权口子（2026-09-20 实测）：
       给账号只放行 1 张看板后，首页确实只剩 1 张，但在查看器里把 URL 的
       ?gid= 换成别的分组，左侧照旧列出该组全部看板，并且
       iframe 真的把被禁止的报告加载了出来（?page=vmaxCxoDashboard_90Days）。
     映射表有 30+ 条 my_app 页面键和 17 条 FineBI 链接，复制一份到 viewer.js
     必然漂移，所以抽到这里，两边共用同一份实现。

   用法：在 portal.js / viewer.js **之前**引入。
     window.MSPortalAccess.dashboardAccessId(item) -> 统一门户的看板 id
     window.MSPortalAccess.canSee(user, item)      -> 布尔（语义与 portal.js 原实现一致）
   ============================================================================ */
(function () {
  'use strict';

  /* uniplam 的页面权限使用 DashboardItem.id；MsPortal 是独立的静态目录，
     所以按同一条看板 URL 做稳定映射。这样登录后 allowedCards / allowedGroups
     仍按统一门户的原语义生效，而不是只做一个「有 token 就能看全部」的门禁。 */
  var MYAPP_ACCESS_IDS = {
    sync: 'custom-task-manager', alarm: 'custom-alarm-dashboard', ttwo: 'custom-tt-wo-dashboard',
    nur: 'custom-nur-dashboard', ms_sla: 'custom-ms-sla-dashboard', cxoDashboard: 'custom-cxo-dashboard',
    gis: 'custom-gis-map', realtime_alarm: 'custom-realtime-alarm-map', alarmManagement: 'custom-alarm-management',
    packet_loss: 'custom-packet-loss', mwUmeTopology: 'custom-mw-ume-topology', mwRealTime: 'custom-mw-realtime',
    battery: 'custom-battery', ip_trace: 'custom-ip-trace', incident_overview: 'custom-incident-overview',
    warehouse: 'custom-warehouse', overview: 'custom-overview', tables: 'custom-table-browser',
    upload: 'custom-data-upload', archive: 'custom-archive', dashboard: 'custom-analysis-dashboard',
    settings: 'custom-settings', email_reports: 'custom-email-reports', portalLogin: 'custom-portal-login',
    eflow_qa: 'custom-eflow-qa', site_avail: 'custom-site-availability', help: 'custom-help',
    feedback: 'custom-issue-feedback', ran_cells_kpi: 'custom-ran-cells-kpi',
    vmaxCxoDashboard: 'custom-vmax-cxo-dashboard', sp_material: 'custom-sp-material',
    vmaxCxoDashboard_Daily: 'custom-vmax-cxo-dashboard-daily',
    vmaxCxoDashboard_90Days: 'custom-vmax-cxo-dashboard-90days', ume_in_kpi: 'custom-ume-in-kpi'
  };
  var FINEBI_ACCESS_IDS = {
    '/webroot/decision/link/qXUp': 'finebi-ms-contract-operation-kpis',
    '/webroot/decision/link/NGk1': 'finebi-ms-mttr-monthly-weekly',
    '/webroot/decision/link/B7E3': 'finebi-ms-nur-monthly-weekly',
    '/webroot/decision/link/AIfA': 'finebi-fo-availability-daily',
    '/webroot/decision/link/435X': 'finebi-fo-availability-tt-related',
    '/webroot/decision/link/3GnT': 'finebi-flm-cm-dashboard',
    '/webroot/decision/link/1neE': 'finebi-bo-daily-availability-kpi',
    '/webroot/decision/link/dXv0': 'finebi-bo-2g-daily-kpi',
    '/webroot/decision/link/51Le': 'finebi-bo-3g-daily-kpi',
    '/webroot/decision/link/wJmG': 'finebi-bo-4g-kpi-daily',
    '/webroot/decision/link/uq6f': 'finebi-bo-fw-daily-kpi',
    '/webroot/decision/link/iYiQ': 'finebi-bo-cn-kpi-v2',
    '/webroot/decision/link/k74G': 'finebi-bo-ip-ran-region-kpi',
    '/webroot/decision/link/Dv5z': 'finebi-bo-ip-ran-core-hq-odc',
    '/webroot/decision/link/PUVx': 'finebi-bo-ip-ran-metor-ring',
    '/webroot/decision/link/cCc5': 'finebi-bo-cn-monthly-kpi',
    '/webroot/decision/link/2XPO': 'finebi-fo-spare-management-audit'
  };
  var EXTERNAL_ACCESS_IDS = {
    'https://192.168.100.27:8443/': 'external-rag-knowledge-qa'
  };

  /* 2026-09-21 加：原来的 FineBI 卡片已改用 my_app 的 FINEBI Board 原生页
     （http://192.168.100.20/myapp/?page=finebi_<slug>，iYiQ 用 ?page=cn_kpi），
     URL 路径不再是 /webroot/decision/link/...，上面 FINEBI_ACCESS_IDS 就查不到了。
     这里按「新 URL 的 page 键 → 迁移前那个 id」再补一张表，保证 allowedCards 里
     那套 finebi-* id 继续命中 —— 否则受限用户会看不到这些卡（fail-closed，
     不是越权，但属于功能回归）。映射依据见 scripts/migrate_finebi_to_myapp.py。
     FINEBI_ACCESS_IDS 保留不动：本机 localStorage 里的旧目录 / 历史数据仍可能带旧 URL。 */
  var FINEBI_PAGE_ACCESS_IDS = {
    finebi_mttr: 'finebi-ms-mttr-monthly-weekly',
    finebi_availability_tt: 'finebi-fo-availability-tt-related',
    finebi_kpi_2g: 'finebi-bo-2g-daily-kpi',
    finebi_kpi_3g: 'finebi-bo-3g-daily-kpi',
    finebi_kpi_4g: 'finebi-bo-4g-kpi-daily',
    finebi_fw_daily: 'finebi-bo-fw-daily-kpi',
    cn_kpi: 'finebi-bo-cn-kpi-v2',
    finebi_cn_kpi_monthly: 'finebi-bo-cn-monthly-kpi',
    finebi_ipran_4region: 'finebi-bo-ip-ran-region-kpi',
    finebi_ipran_hq: 'finebi-bo-ip-ran-core-hq-odc',
    finebi_metro_ring: 'finebi-bo-ip-ran-metor-ring',
    /* 服务端目录已下架、但仍留在兜底目录 data.js 里的 4 张，一并映射 */
    finebi_availability_daily: 'finebi-fo-availability-daily',
    finebi_cm_dashboard: 'finebi-flm-cm-dashboard',
    finebi_daily_availability: 'finebi-bo-daily-availability-kpi',
    finebi_spare: 'finebi-fo-spare-management-audit'
  };

  /** 卡片 → 统一门户的看板 id。带 item.id 时直接用（服务端目录可能自带 id）。 */
  function dashboardAccessId(item) {
    if (item && item.id) return String(item.id);
    var raw = String(item && item.url || '');
    try {
      var u = new URL(raw, location.href);
      var page = u.searchParams.get('page');
      if (page && MYAPP_ACCESS_IDS[page]) return MYAPP_ACCESS_IDS[page];
      if (page && FINEBI_PAGE_ACCESS_IDS[page]) return FINEBI_PAGE_ACCESS_IDS[page];
      var path = u.pathname;
      if (FINEBI_ACCESS_IDS[path]) return FINEBI_ACCESS_IDS[path];
      var exact = u.origin + u.pathname;
      if (EXTERNAL_ACCESS_IDS[exact]) return EXTERNAL_ACCESS_IDS[exact];
    } catch (e) { /* malformed/custom URL: fall through to local ids */ }
    return item && item.id ? String(item.id) : String(item && item.no || '');
  }

  function groupsOf(item) { return (item && item.groups) || []; }

  /** 权限判定。语义与 portal.js 抽出前**逐字一致**：
        · 没有 user（会话还没探到 / 未登录）→ 放行，由调用方自己的登录门禁兜底；
          ⚠️ 查看器（viewer.js）不能依赖这一条 —— 它必须自己先确认已登录，
          否则「未登录 → 放行」就成了新的口子。那边用 allowed() 包了一层 fail-closed。
        · allowedGroups / allowedCards 都为 null → 未设限，全放行；
        · 命中任一 allowedGroups（MsPortal 的视图分组名）→ 放行；
        · 命中 allowedCards（统一门户看板 id，或历史数据里的卡片编号）→ 放行。 */
  function canSee(user, item) {
    if (!user) return true;
    var restricted = user.allowedGroups != null || user.allowedCards != null;
    if (!restricted) return true;
    var groups = Array.isArray(user.allowedGroups) ? user.allowedGroups : [];
    if (groups.some(function (g) { return groupsOf(item).indexOf(g) !== -1; })) return true;
    var cards = Array.isArray(user.allowedCards) ? user.allowedCards : [];
    var id = dashboardAccessId(item);
    return cards.indexOf(id) !== -1 || cards.indexOf(String(item && item.no)) !== -1;
  }

  window.MSPortalAccess = {
    dashboardAccessId: dashboardAccessId,
    groupsOf: groupsOf,
    canSee: canSee
  };
})();
