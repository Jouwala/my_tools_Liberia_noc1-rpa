/* viewer.js — MsPortal「看板查看器」外壳
 * 作用：从门户首页点击某个看板（如 MS View 下的报告）后，在新页面左侧提供
 *       「同组其他看板」导航（类似 my_app 的侧边栏），右侧内嵌当前看板。
 * 数据：目录真相源与门户首页（portal.js）**完全一致**的三层优先级 ——
 *        服务端全局目录 /api/portal-catalog > 本机 localStorage 兜底 > assets/data.js 内置。
 *        （2026-09-19 修：此前只读 assets/data.js，于是「门户里改了、查看器左侧不变」——
 *          门户首页拉的是服务端目录，本文件却停在出厂内置值，两边长期不一致。
 *          实测：服务端 MS View 只剩 no=1/2，viewer 左侧仍列 8 条。）
 * 内嵌策略：
 *   · my_app 页面（URL 路径以 /myapp/ 开头，无 X-Frame-Options）→ 改写为**同源**
 *     /myapp/?page=xxx 后用 iframe 内嵌。my_app 深链带 ?page= 时自身进入 bare 模式
 *     （隐藏它自己的侧栏/Header），正好只留下本查看器的分组侧栏，不会出现双侧栏。
 *   · FineBI / 外部系统（跨域且返回 X-Frame-Options: SAMEORIGIN）→ 无法内嵌，
 *     点击时改为「在新窗口打开」，并在右侧显示引导面板。
 */
(function () {
  'use strict';

  var PH = {
    'chart-polar': 'ph-chart-polar', 'gauge': 'ph-gauge', 'bell': 'ph-bell', 'map': 'ph-map-trifold',
    'ticket': 'ph-ticket', 'siren': 'ph-siren', 'clock': 'ph-clock', 'chart-line': 'ph-chart-line',
    'link': 'ph-link', 'cpu': 'ph-cpu', 'broadcast': 'ph-broadcast', 'battery': 'ph-battery-charging',
    'package': 'ph-package', 'wrench': 'ph-wrench', 'upload': 'ph-cloud-arrow-up', 'table': 'ph-table',
    'archive': 'ph-archive', 'chat': 'ph-chat-circle-dots', 'book': 'ph-book-open-text', 'gear': 'ph-gear',
    'dashboard': 'ph-squares-four', 'key': 'ph-lock-key', 'warning': 'ph-warning', 'briefcase': 'ph-briefcase',
    'git': 'ph-git-pull-request', 'user': 'ph-user', 'eye': 'ph-eye', 'flame': 'ph-fire',
    'arrow': 'ph-arrow-right', 'arrow-up-right': 'ph-arrow-up-right', 'plus': 'ph-plus',
    'folder': 'ph-folder-open', 'buildings': 'ph-buildings', 'shield': 'ph-shield-check'
  };
  function ico(name, cls) { return '<i class="ph ' + (PH[name] || PH.dashboard) + (cls ? ' ' + cls : '') + '" aria-hidden="true"></i>'; }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var DATA = window.MS_PORTAL_DATA || { items: [], groups: [] };
  var LANG = (function () {
    try {
      var v = localStorage.getItem('msportal.lang.v1');
      if (v === 'en' || v === 'zh') return v;
    } catch (e) { /* ignore */ }
    /* 没切过语言时跟随浏览器 —— 与 viewer.html 首屏脚本同一口径，
       否则首帧 <html lang> 是 en、下面 JS 却按 zh 画。 */
    var nav = (navigator.language || navigator.userLanguage || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  })();

  /* ---- 看板目录：与门户首页同一条真相源（2026-09-19 修） ----
     背景：门户首页（portal.js）的目录优先级是「服务端全局目录 > 本机 localStorage
     兜底 > data.js 内置」；本查看器原来**只**读 data.js，于是门户里做的增删改
     （全部落在服务端 /api/portal-catalog）在首页立刻生效，点进查看器后左侧却还是
     出厂那 51 条 —— 同一套门户两个答案。

     这里补齐同一套优先级，实现刻意保持"外壳先渲染、不白屏"：
       1) 同步先用内置 data.js 渲染（首屏立刻有内容）；
       2) 再依次尝试服务端目录 → 本机兜底目录，拿到就替换 DATA.items 并重绘。
     注意：DATA 整体替换，不做 items/groups 局部赋值 —— 服务端目录只带 items，
     groups 的显示名仍用 data.js 内置的（服务端没存分组元数据，与 portal.js 一致）。 */
  var LS_CATALOG = 'msportal.catalog.v1';
  function readCatalogLS() {
    try {
      var raw = localStorage.getItem(LS_CATALOG);
      var v = raw ? JSON.parse(raw) : null;
      return (v && v.length) ? v : null;
    } catch (e) { return null; }
  }
  /* 服务端目录与 data.js 的 items 字段并非逐字相同（服务端会补 platform/status 默认值、
     截断长文本），这里只挑渲染真正用到的键做浅合并，避免 undefined 把内置值覆盖掉。
     ⚠️ 2026-09-28：加入 'subOf' 与 'boSub'（用户要求「左边的目录也要按照 BO View
     卡片的页签进行分类」）。这两个键是**子分组归属**，正是左侧分组的依据；
     原来不在这里，于是服务端目录灌进来时归属被丢掉、左侧永远只能平铺
     （下面 refreshSubGroups 的注释里有完整说明）。 */
  var CATALOG_KEYS = ['no', 'groups', 'titleZh', 'titleEn', 'descZh', 'descEn', 'platform', 'url', 'icon', 'clicks',
    'subOf', 'boSub'];
  /* subGroupsOf() 需要 gid 参数，但 applyCatalog 拿到的 items 是数组、
     这里只关心"服务端有没有给过子分组元数据"，所以按调用方传进来的第二参收。
     调用点见 loadCatalog()（它读的是 data.catalog.subGroups）。 */
  function applyCatalog(items, subGroups) {
    if (!items || !items.length) return false;
    DATA = {
      items: items.map(function (src) {
        var out = {}, i;
        for (i = 0; i < CATALOG_KEYS.length; i++) {
          if (src[CATALOG_KEYS[i]] !== undefined) out[CATALOG_KEYS[i]] = src[CATALOG_KEYS[i]];
        }
        return out;
      }),
      groups: DATA.groups || [],
      /* 服务端子分组元数据（可空）。⚠️ 只在它**真有值**时覆盖：
         本机兜底目录这条路径不带 subGroups，若在这里无条件写 undefined，
         会把上一次从服务端拿到的好数据清掉（先服务端、后兜底的顺序下
         反而是兜底把服务端顶掉）。所以用"有值才换"的写法。 */
      subGroups: (subGroups && Object.keys(subGroups).length) ? subGroups : DATA.subGroups
    };
    /* ⚠️ 必须重算 LIST：它是一次性算好的数组，换了目录不重算的话
       renderList() 画的还是旧目录（实测：接口请求成功、界面纹丝不动）。 */
    recomputeList();
    return true;
  }
  /* ---- 子分组（BO View 的 RAN/IP/MW/CN/OCS 页签）----
     为什么单独抽一个变量、而不是直接从 DATA 上读：
     applyCatalog() 是**整体替换 DATA** 的，而服务端目录只带 items + subGroups，
     不带 groups 元数据（沿用文件头那套"分组名仍用内置"的口径）。子分组名同理 ——
     服务端的 subGroups 里有 zh/en，是有值的，所以这里优先用服务端那份，
     拿不到时回落到内置 SUB_BUILTIN。**不能**直接读 DATA.subGroups：
     本机兜底目录（localStorage）与内置目录都没有这个字段，
     直接读会让"服务端没保存过子分组"的机器上左侧又变回平铺。 */
  var SUB_BUILTIN = {
    'BO View': [
      { id: 'ran', zh: 'RAN 无线接入网', en: 'RAN · Radio Access Network' },
      { id: 'ip', zh: 'IP 承载网', en: 'IP · Bearer Network' },
      { id: 'mw', zh: 'MW 微波传输', en: 'MW · Microwave Transmission' },
      { id: 'cn', zh: 'CN 核心网', en: 'CN · Core Network' },
      { id: 'ocs', zh: 'OCS 在线计费', en: 'OCS · Online Charging System' }
    ]
  };
  /* 与 olbrportal 的 SUB_KEEP_REMAP 同一份口径：旧子分组 id → 新专业域 id。
     两边必须一致，否则同一张卡在门户首页归到「CN」、在查看器左侧归到别处。
     （20/21/22 wireless→ran、24/25 core→cn、29~32 ip→ip 属于桶名直译，
      不需要列在这里；名单越短越不容易漂移。） */
  var SUB_KEEP_REMAP = { '23': 'cn', '26': 'ip', '27': 'mw', '28': 'mw', '36': 'ran', '51': 'ocs', '66': 'ocs' };

  function subGroupsOf(gid) {
    var m = DATA.subGroups;
    if (m && Object.prototype.hasOwnProperty.call(m, gid)) {
      var arr = Array.isArray(m[gid]) ? m[gid] : [];
      var out = arr.filter(function (s) { return s && s.id; });
      if (out.length) return out;
    }
    return SUB_BUILTIN[gid] || [];
  }
  function subName(s) { return LANG === 'en' ? (s.en || s.zh || s.id) : (s.zh || s.en || s.id); }
  /* 页签上的短标签：只取专业域缩写（RAN / IP / MW / CN / OCS），全称留给 title。
     口径与 olbrportal 的 subChipLabel 一致 —— 取名字里第一段全大写/数字字母（2-4 位）；
     取不到（子分组被改名成纯中文）就退回整名，宁可长一点也不截成看不懂的碎片。 */
  function subChipLabel(s) {
    var full = subName(s);
    var m = /^\s*([A-Z][A-Z0-9]{1,3})(?=[\s·\-–—]|$)/.exec(full);
    return m ? m[1] : full;
  }
  /* 这张卡在 gid 下属于哪个子分组。返回 '' 表示没归属。
     ⚠️ 必须按分组取值：一个看板可以同挂多个分组（实测 no=11/12/13/18/36 同时在
     FO + FLM），拿单个 boSub 直接套用会把 A 分组的归属串到 B 分组。
     口径与 olbrportal 的 subOfItem 逐条对齐，只保留 BO View 这一处迁移
     （查看器只对 BO View 建页签，别的分组没有子分组概念）。 */
  function subOfItem(it, gid) {
    var m = it && it.subOf, has = m && typeof m === 'object' && !Array.isArray(m);
    if (has) {
      var sid = String(m[gid] || '');
      if (!sid) return '';
      return gid === 'BO View' ? migrateBoSubOf(sid, String(it.no)) : sid;
    }
    var legacy = it && it.boSub ? String(it.boSub) : '';
    if (!legacy) return '';
    var cand = gid === 'BO View' ? migrateBoSubOf(legacy, String(it.no)) : legacy;
    return subGroupsOf(gid).some(function (s) { return s.id === cand; }) ? cand : '';
  }
  /* 旧 id → 新专业域 id。只做映射，**不校验合法性** ——
     校验交给调用方（subOfItem 用 subGroupsOf 对结果做一次存在性检查），
     这样"服务端自定义了第 6 个子分组"这类情况不会被这里静默丢掉。 */
  function migrateBoSubOf(sid, no) {
    return SUB_KEEP_REMAP[String(no)] || sid;
  }
  function reloadCatalog() {
    if (!LIST.length) { elGrpCnt.textContent = '0 ' + TXT.cnt; return; }
    /* 先按 URL 的 startNo 重定位（2026-09-19 补）。
       背景：首屏是拿**内置 data.js** 定位的（外壳先渲染、不白屏），而门户里新增的看板
       只存在于服务端目录里 —— 那时 findItem(startNo) 必然落空，初始化会回落到 LIST[0]；
       等目录对齐后，下面的逻辑只认 current.no（= 回落的那条），于是 URL 明明写着
       ?no=53，页面却一直显示 no=35 的内容（实测：点门户新加的卡片进查看器，标题/内嵌
       全是另一张看板）。这里在目录对齐后补一次按 startNo 的定位；
       startNo 不在新目录、或不属于本组时，保持下面原有的回落逻辑。 */
    var want = startNo ? findItem(startNo) : null;
    if (want && groupsOf(want).indexOf(GID) !== -1) {
      renderHead();
      select(want, false);
      return;
    }
    /* current 指向的是**旧目录**里的那个对象（applyCatalog 整体换掉了 DATA.items），
       必须按 no 到新目录里重新解析一次 —— 否则 groupsOf(keep) 读到的还是旧 groups，
       看板明明已被移出本组也判不出来（实测：no=7 在服务端已被移出 MS View，
       左侧却仍把它当本组成员保留、且没有任何条目高亮）。 */
    var keep = current ? findItem(current.no) : null;
    current = null;
    if (!keep || groupsOf(keep).indexOf(GID) === -1) { select(LIST[0], false); return; }
    renderHead();
    elCurTitle.textContent = titleOf(keep);
    current = keep;
    if (isEmbeddable(keep)) showEmbed(keep); else showExternal(keep);
    renderList();
  }
  /* 服务端目录只拉一次：它是全局的，不会因为本机操作而变化（口径同 portal.js）。
     401 / 接口未注册（my_app 的 SPA 兜底会把未知 /api/xxx 回成 HTML）都当作
     「没有服务端目录」，继续用本机兜底 / 内置，绝不因为拉取失败而空列表。 */
  function loadCatalog() {
    fetch('/api/portal-catalog', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok) throw new Error('HTTP ' + r.status);
        if (ct.indexOf('json') === -1) throw new Error('non-JSON');
        return r.json();
      })
      .then(function (data) {
        var items = data && data.catalog && data.catalog.items;
        if (items && items.length) {
          /* 2026-09-28：一并把 catalog.subGroups 传下去（BO View 的页签分组）。
             它和 items 同在一次响应里，不需要额外请求。 */
          if (applyCatalog(items, data.catalog.subGroups)) reloadCatalog();
          try { localStorage.removeItem(LS_CATALOG); } catch (e) { /* ignore */ }
          return;
        }
        // 服务端从未保存过（catalog=null）→ 本机兜底目录，再没有就用内置
        var local = readCatalogLS();
        if (local && applyCatalog(local)) reloadCatalog();
      })
      .catch(function () {
        var local = readCatalogLS();
        if (local && applyCatalog(local)) reloadCatalog();
      });
  }

  var PLAT_LABEL = {
    myapp: LANG === 'en' ? 'my_app' : '自研 my_app',
    finebi: LANG === 'en' ? 'FineBI' : 'FineBI 报表',
    external: LANG === 'en' ? 'External' : '外部系统'
  };
  function titleOf(it) { return LANG === 'en' ? (it.titleEn || it.titleZh) : it.titleZh; }
  function descOf(it) { return LANG === 'en' ? (it.descEn || it.descZh) : it.descZh; }

  // ---- 解析入口参数：?no=<itemNo>&gid=<group>（gid 缺省时回退到该看板所属组） ----
  var qs = new URLSearchParams(location.search);
  var startNo = qs.get('no');
  var startGid = qs.get('gid');

  function findItem(no) {
    no = String(no);
    return (DATA.items || []).filter(function (it) { return String(it.no) === no; })[0] || null;
  }
  function groupsOf(it) { return it.groups || []; }
  function groupMeta(gid) {
    return (DATA.groups || []).filter(function (g) { return g.id === gid; })[0] || { id: gid, zh: gid, en: gid };
  }
  function siblingsOf(gid) {
    return (DATA.items || []).filter(function (it) { return groupsOf(it).indexOf(gid) !== -1; })
      .sort(function (a, b) { return (b.clicks || 0) - (a.clicks || 0); });
  }

  // ---- 可内嵌判定：仅 my_app 深链（同源、无 X-Frame-Options）可 iframe ----
  function parseUrl(raw) { try { return new URL(raw, location.href); } catch (e) { return null; } }
  function isEmbeddable(it) {
    var u = parseUrl(it.url);
    return !!(u && u.pathname.indexOf('/myapp/') === 0);
  }
  function embedSrc(it) {
    var u = parseUrl(it.url);
    if (!u) return null;
    // 用当前 origin 拼同源地址：无论门户从 localhost 还是 192.168.100.20 访问都自适应
    return location.origin + u.pathname + (u.search || '');
  }

  /* ---- 主题同步：让内嵌的 my_app 跟着门户的深浅色走（2026-09-18 补） ----
   * 为什么需要：本页只是外壳，右侧真正显示的是 iframe 里的 /myapp/?page=xxx ——
   * 那是**另一个应用**，主题状态与门户完全独立。实测（TMP/diag_viewer_dark.cjs）：
   * 门户切深色后外壳 body 已是 rgb(2,5,12)（vmax 深空蓝），
   * 但 iframe 内 my_app 的 <html data-theme="light">、html 底仍是 rgb(233,238,243)
   * —— 所以整页看起来还是浅色。
   *
   * my_app 的主题机制（读自 /myapp/assets/index-*.js 的打包产物）：
   *   var k = 'myapp-theme';                 // localStorage 键
   *   初始值：localStorage[k] 是 'dark'/'light' 就用它，否则跟随 prefers-color-scheme
   *   变更时：document.documentElement.setAttribute('data-theme', t)
   *          并向它自己的子 iframe postMessage({__type:'myapp-theme', mode:t})
   * 它**没有**监听来自父窗口的主题消息，也没有 URL 参数入口 ——
   * 唯一能从外部驱动的就是 localStorage['myapp-theme']。
   *
   * 门户与 my_app 同源（都在 http://localhost/ 或 http://192.168.100.20/），
   * 所以这里直接写这个键，iframe 下次加载就会以同一主题启动。
   * ⚠️ 这是**跨应用**副作用：写过之后直接打开 /myapp/ 也会是同一主题。
   *    不想要的话，删掉本段和它的 3 处调用即可。 */
  var EMBED_THEME_KEY = 'myapp-theme';
  /* ---- 谁是「当前主题」（2026-09-23 加：支持 olbrportal 入口） ----
   * 本页有两个门户入口，主题键不同：
   *   · /MsPortal/   → 'msportal.theme.v1'
   *   · /olbrportal/ → 'olbr.theme'（该页刻意不复用 msportal.* 那几个键，
   *                    见 olbr.js 顶部「绝不写 msportal.*」那条约定）
   * 两边的「打开看板」都指到本页，所以本页必须认得两个键，
   * 否则从 olbrportal 深色主题点进来，外壳仍是浅色（用户反馈的现象）。
   *
   * 两个键都可能有值且冲突（用户先在某边切深、又在另一边切浅），
   * 所以不能「非空即认」，要看**最后被设置的那个** —— 依据是各页写入的价值同时
   * 记一个时间戳（'<key>.t'，毫秒 epoch）。这个时间戳由两个门户的 setTheme /
   * 切换动作负责写；缺失时按 0 处理，等价于「比不过另一边的任何一次显式设置」。
   * ⚠️ viewer.html 首屏那段防闪烁脚本用的是**同一套判据**，必须一起改，
   *    否则首帧与挂载后会闪一下另一种主题。 */
  var THEME_KEY_MS = 'msportal.theme.v1';
  var THEME_KEY_OLBR = 'olbr.theme';
  function lastWriteAt(key) {
    try { return parseInt(localStorage.getItem(key + '.t') || '0', 10) || 0; }
    catch (e) { return 0; }
  }
  function themeOf(key) {
    try {
      var v = localStorage.getItem(key);
      return (v === 'dark' || v === 'light') ? v : null;
    } catch (e) { return null; }
  }
  function portalTheme() {
    var m = themeOf(THEME_KEY_MS), o = themeOf(THEME_KEY_OLBR);
    if (m && o) return lastWriteAt(THEME_KEY_OLBR) >= lastWriteAt(THEME_KEY_MS) ? o : m;
    return o || m || 'light';
  }
  function syncEmbedTheme() {
    var want = portalTheme();
    try { if (localStorage.getItem(EMBED_THEME_KEY) !== want) localStorage.setItem(EMBED_THEME_KEY, want); }
    catch (e) { /* ignore */ }
    return want;
  }

  /* ---- 访问控制（2026-09-20 加） ----
     背景（实测出来的越权口子）：本页是**真正把报告 iframe 加载出来**的地方，
     但原先既没有登录判定、也没有 allowedGroups/allowedCards 判定 ——
     给账号只放行 1 张看板后，首页确实只剩 1 张，可只要把地址栏的
     ?gid= 换成别的分组，左侧照旧列出该组全部看板，并且
     ?page=vmaxCxoDashboard_90Days 会被真的加载进 iframe。
     修法：先解析门户登录态 → 再按与首页同一份实现（assets/access.js）过滤
     左侧清单 → 选中项无权时**不赋 src**（连请求都不发），只显示无权限提示。

     身份口径必须与门户首页 probeSession() **完全一致**，否则会出现
     「首页看得到、点进去却被挡」这种自相矛盾：
       · 先问 my_app /api/auth/me —— 本机回环会被 my_app 放行（占位 admin，
         不带白名单），所以「在自己机器上直接打开」照旧全放行，与首页一致；
       · 手里有门户 token 时以门户用户为准（只有它带 allowedGroups/allowedCards）；
       · my_app 不认但手里有门户 token（缺 myapp_session Cookie）→ 先换一次会话再问。
     真正的越权场景（局域网上的受限账号、以及完全匿名的访问）都会被挡住：
     前者拿到的是带白名单的门户身份，后者 my_app 直接 401。

     ⚠️ allowed() 与 access.js 的 canSee() 有一处刻意的差别：canSee 在「没有 user」
     时放行（首页靠自己的登录门禁兜底），而本页必须 fail-closed ——
     没解析出身份就当作无权，绝不能"没登录 = 全放行"。 */
  var PORTAL_TOKEN_KEY = 'liberia_noc_auth_v1';
  var portalUser = null;
  var authReady = false;

  function readPortalToken() {
    try { return localStorage.getItem(PORTAL_TOKEN_KEY) || null; } catch (e) { return null; }
  }
  /** my_app 会话（本机回环会被放行；远端无 Cookie 则 401 → null） */
  function askMyApp() {
    return fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.user ? d.user : null; })
      .catch(function () { return null; });
  }
  /** 门户用户（带 allowedGroups/allowedCards 的那个身份） */
  function askPortal(token) {
    if (!token) return Promise.resolve(null);
    return fetch('/uniplam/api/auth/me', {
      credentials: 'same-origin',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' }
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.user ? d.user : null; })
      .catch(function () { return null; });
  }
  /** 用门户 token 换 myapp 会话 Cookie（与门户首页 exchangePortalToken 同一个接口） */
  function exchangePortalToken(token) {
    return fetch('/api/auth/portal-login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: token })
    }).then(function (r) { return r.ok; }).catch(function () { return false; });
  }
  /** 返回 { authed, user }；authed=false 才整页挡住 */
  function resolveIdentity() {
    var token = readPortalToken();
    return askMyApp().then(function (me) {
      if (me) return askPortal(token).then(function (pu) { return { authed: true, user: pu || me }; });
      if (!token) return { authed: false, user: null };
      return exchangePortalToken(token).then(function (ok) {
        if (!ok) return { authed: false, user: null };
        return askMyApp().then(function (next) { return { authed: !!next, user: next || null }; });
      });
    });
  }
  function allowed(it) {
    if (!authReady || !portalUser) return false;
    var A = window.MSPortalAccess;
    return !!(A && A.canSee(portalUser, it));
  }

  // ---- 状态 ----
  /* 分组归属可能因目录切换（内置 → 服务端）而变化：startNo 指向的看板在新目录里
     可能不属于 startGid 了（实测：服务端目录把 no=7 从 MS View 移走）。
     所以 GID 固定在入口参数上（gid 优先，其次该看板在**当前**目录里的第一个组），
     每次换目录后只重算 LIST，不跟着看板漂移 —— 否则左侧会从「MS View」跳到别的组。 */
  var GID = startGid || (findItem(startNo) && groupsOf(findItem(startNo))[0]) || 'MS View';
  var LIST = [];
  var current = null;
  /** 左侧清单 = 本组看板 ∩ 当前账号有权看的。未登录时恒为空（fail-closed）。 */
  function recomputeList() { LIST = siblingsOf(GID).filter(allowed); }
  recomputeList();

  // DOM
  var elList = document.getElementById('sbList');
  var elGrpName = document.getElementById('grpName');
  var elGrpSub = document.getElementById('grpSub');
  var elGrpCnt = document.getElementById('grpCnt');
  var elCurTitle = document.getElementById('curTitle');
  var frame = document.getElementById('frame');
  var loading = document.getElementById('loading');
  var placeholder = document.getElementById('placeholder');
  var phTitle = document.getElementById('phTitle');
  var phDesc = document.getElementById('phDesc');
  var phBtn = document.getElementById('phBtn');
  var phBtnTxt = document.getElementById('phBtnTxt');

  var TXT = LANG === 'en'
    ? {
      back: 'Back to portal', cnt: 'dashboards', ext: 'This board is an external system (FineBI / 3rd party) and cannot be embedded here for security reasons (X-Frame-Options).', open: 'Open in new window', loading: 'Loading…',
      needLogin: 'Sign-in required', needLoginDesc: 'This page embeds report content, so it needs a unified-portal sign-in. Please sign in on the portal home page first.', goLogin: 'Go to sign in',
      denied: 'No access to this dashboard', deniedDesc: 'This dashboard is not in your page permissions. Ask an administrator to tick it under User Management → Page configuration.', backPortal: 'Back to portal home',
      sb: 'Collapse / expand sidebar', reload: 'Reload'
    }
    : {
      back: '返回门户首页', cnt: '个看板', ext: '该看板属于外部系统（FineBI / 第三方），出于安全策略（X-Frame-Options）无法在本页内嵌显示。', open: '在新窗口打开', loading: '加载中…',
      needLogin: '需要登录', needLoginDesc: '本页用于内嵌查看报告内容，需要统一门户账号登录。请先在门户首页登录。', goLogin: '去登录',
      denied: '无权查看该看板', deniedDesc: '当前账号的页面权限里没有这张看板。如需开通，请联系管理员在「用户管理 → 页面配置」里勾选。', backPortal: '返回门户首页',
      sb: '收起/展开侧栏', reload: '重新加载'
    };
  /* 工具条图标按钮的 title 之前只写在 viewer.html 里（中文），英文模式下是残留。 */
  [['toggleSb', 'sb'], ['reloadBtn', 'reload'], ['openBtn', 'open']].forEach(function (p) {
    var el = document.getElementById(p[0]);
    if (el) el.setAttribute('title', TXT[p[1]]);
  });
  document.getElementById('backTxt').textContent = TXT.back;
  phBtnTxt.textContent = TXT.open;
  loading.innerHTML = '<i class="ph ph-circle-notch" aria-hidden="true" style="margin-right:8px"></i>' + esc(TXT.loading);

  function renderHead() {
    var m = groupMeta(GID);
    elGrpName.textContent = LANG === 'en' ? (m.en || m.id) : (m.zh || m.id);
    elGrpSub.textContent = LANG === 'en' ? (m.subEn || '') : (m.subZh || '');
    elGrpCnt.textContent = LIST.length + ' ' + TXT.cnt;
    document.title = (LANG === 'en' ? (m.en || m.id) : (m.zh || m.id)) + (LANG === 'en' ? ' · MS Portal' : ' · 看板查看器');
  }

  /* ⚠️ 2026-09-28 改（用户要求「http://192.168.100.20/MsPortal/viewer.html?no=22&gid=BO%20View
     左边的目录也要按照 BO View 卡片的页签进行分类」）：
     原来这里是把 LIST 平铺成一串 .sb-item。现在若当前分组有子分组
     （目前只有 BO View 有 RAN/IP/MW/CN/OCS），就按子分组分段渲染，
     每段一个可折叠的小标题；没有子分组的分组（MS View / FO View 等）
     **完全走原来的平铺路径**，外观与行为一个像素都不变 —— 这是刻意的：
     给所有分组都套一层"分组头"会让本来就不长的清单平白多出几行噪声。

     为什么保留"未归类"段而不是把漏网的卡丢掉：
     服务端历史数据里可能还有归属为空 / 指向已删子分组的看板（子分组是可编辑的）。
     丢掉它们等于"门户里有、查看器里没有"，用户会以为权限出问题。
     只在真有这种卡时才渲染这一段（见 SUB_NONE 分支），没有就不显示空标题。

     折叠状态存在 state.subOpen 里、**不进 localStorage**：
     它是"我这次翻到哪了"的临时视图状态，下次打开应当回到全展开，
     否则用户会碰上"点进来看不到任何条目，因为上次把域都折起来了"。 */
  var state = { subOpen: {} };
  function subSectionHtml(sid, label, full, items, curNo) {
    var open = state.subOpen[sid] !== false;   // 默认展开
    var head = '<button type="button" class="sb-sub' + (open ? '' : ' closed') + '" data-sub="' + esc(sid) + '"' +
      ' aria-expanded="' + (open ? 'true' : 'false') + '" title="' + esc(full || label) + '">' +
      '<i class="ph ph-caret-down" aria-hidden="true"></i>' +
      '<span class="sb-sub-t">' + esc(label) + '</span>' +
      '<span class="sb-sub-n">' + items.length + '</span></button>';
    return head + (open ? items.map(function (it) { return itemHtml(it, curNo); }).join('') : '');
  }
  function itemHtml(it, curNo) {
    var active = String(it.no) === curNo;
    var ext = isEmbeddable(it) ? '' : '<span class="ext">' + ico('arrow-up-right') + '</span>';
    return '<a class="sb-item' + (active ? ' active' : '') + '" data-no="' + esc(it.no) + '" href="#" title="' + esc(titleOf(it)) + '">' +
      '<span class="ic">' + ico(it.icon) + '</span>' +
      '<span class="tx"><span class="tt">' + esc(titleOf(it)) + '</span>' +
      '<span class="pl">' + esc(PLAT_LABEL[it.platform] || it.platform || '') + '</span></span>' +
      ext + '</a>';
  }
  function renderList() {
    var curNo = current ? String(current.no) : '';
    var subs = subGroupsOf(GID);
    /* 没有子分组概念的分组：保持原样平铺。 */
    if (!subs.length) { elList.innerHTML = LIST.map(function (it) { return itemHtml(it, curNo); }).join(''); return; }
    var buckets = subs.map(function (s) {
      return {
        id: s.id, label: subChipLabel(s), full: subName(s),
        items: LIST.filter(function (it) { return subOfItem(it, GID) === s.id; })
      };
    });
    /* 未归类兜底：归属为空、或指向已删子分组（subGroups 被改过）的看板。 */
    var rest = LIST.filter(function (it) {
      return !subs.some(function (s) { return s.id === subOfItem(it, GID); });
    });
    var html = buckets.map(function (b) { return subSectionHtml(b.id, b.label, b.full, b.items, curNo); }).join('');
    if (rest.length) {
      html += subSectionHtml('__none', LANG === 'en' ? 'Unassigned' : '未归类',
        LANG === 'en' ? 'Dashboards with no technology domain assigned' : '未指定专业域的看板', rest, curNo);
    }
    elList.innerHTML = html;
  }

  function showEmbed(it) {
    placeholder.classList.remove('show');
    loading.style.display = 'flex';
    frame.style.visibility = 'visible';
    syncEmbedTheme();   // 必须在赋 src 之前：my_app 只在启动时读一次 localStorage
    frame.src = embedSrc(it);
  }
  function showExternal(it) {
    frame.style.visibility = 'hidden';
    frame.src = 'about:blank';
    loading.style.display = 'none';
    phTitle.textContent = titleOf(it);
    phDesc.textContent = TXT.ext;
    phBtn.href = it.url;
    placeholder.classList.add('show');
  }

  /** 未登录：清空左侧、不加载任何报告，只给一个去登录的引导。
      必须把 frame 置回 about:blank —— 否则上一轮的报告会留在 iframe 里。 */
  function showAuthGate() {
    current = null;
    LIST = [];
    elList.innerHTML = '';
    elGrpCnt.textContent = '0 ' + TXT.cnt;
    elCurTitle.textContent = TXT.needLogin;
    frame.style.visibility = 'hidden';
    frame.src = 'about:blank';
    loading.style.display = 'none';
    phTitle.textContent = TXT.needLogin;
    phDesc.textContent = TXT.needLoginDesc;
    phBtn.href = 'index.html';
    phBtnTxt.textContent = TXT.goLogin;
    placeholder.classList.add('show');
  }

  /** 已登录但当前看板不在白名单里：不赋 src（连请求都不发），只显示提示。
      左侧仍保留他有权看的其他看板，方便直接切过去。 */
  function showDenied(it) {
    current = null;
    elCurTitle.textContent = titleOf(it);
    frame.style.visibility = 'hidden';
    frame.src = 'about:blank';
    loading.style.display = 'none';
    phTitle.textContent = TXT.denied;
    phDesc.textContent = TXT.deniedDesc;
    phBtn.href = 'index.html';
    phBtnTxt.textContent = TXT.backPortal;
    placeholder.classList.add('show');
    renderList();
  }

  function select(it, push) {
    if (!it) return;
    /* 权限判定放在最前面：无权就不进 showEmbed/showExternal，避免报告被加载 */
    if (!allowed(it)) { showDenied(it); return; }
    current = it;
    elCurTitle.textContent = titleOf(it);
    if (isEmbeddable(it)) showEmbed(it); else showExternal(it);
    renderList();
    if (push !== false) {
      try { history.replaceState({ no: it.no }, '', 'viewer.html?gid=' + encodeURIComponent(GID) + '&no=' + encodeURIComponent(it.no)); } catch (e) {}
    }
  }

  // ---- 事件 ----
  elList.addEventListener('click', function (e) {
    /* 子分组标题（BO View 的 RAN/IP/MW/CN/OCS）：只翻转折叠状态，不切换看板。
       必须**先**判它、且在判 .sb-item 之前 return：
       标题是 <button>、条目是 <a>，两者不嵌套，理论上不会同时命中，
       但顺序写死能防住将来有人把标题改回 <a> 时"点标题顺手也打开一个看板"。 */
    var sb = e.target.closest('.sb-sub');
    if (sb) {
      e.preventDefault();
      var sid = sb.getAttribute('data-sub');
      state.subOpen[sid] = state.subOpen[sid] === false;   // 与 subSectionHtml 的 !== false 互为反义
      renderList();
      return;
    }
    var a = e.target.closest('.sb-item');
    if (!a) return;
    e.preventDefault();
    var it = findItem(a.getAttribute('data-no'));
    if (!it) return;
    /* 清单本身已按权限过滤，这里再判一次：外链分支是 window.open(真实报告地址)，
       一旦漏进来就是直接把越权报告开在用户面前，不能只靠清单过滤。 */
    if (!allowed(it)) { showDenied(it); return; }
    if (!isEmbeddable(it)) {
      // 外部系统：直接新窗口打开（用户手势，弹窗不被拦截），当前内嵌视图保持不变
      window.open(it.url, '_blank', 'noopener');
      current = it; elCurTitle.textContent = titleOf(it); renderList();
      return;
    }
    select(it);
  });

  frame.addEventListener('load', function () {
    if (frame.getAttribute('src') === 'about:blank') return;
    loading.style.display = 'none';
  });

  document.getElementById('toggleSb').addEventListener('click', function () {
    document.body.classList.toggle('sb-collapsed');
  });
  document.getElementById('reloadBtn').addEventListener('click', function () {
    if (current && isEmbeddable(current)) { loading.style.display = 'flex'; syncEmbedTheme(); try { frame.contentWindow.location.reload(); } catch (e) { frame.src = embedSrc(current); } }
    else if (current) { window.open(current.url, '_blank', 'noopener'); }
  });
  document.getElementById('openBtn').addEventListener('click', function () {
    if (current) window.open(current.url, '_blank', 'noopener');
  });

  /* 门户在**另一个标签页**切了主题 → 本页外壳和内嵌看板一起跟着切。
     （storage 事件只在「别的文档」改动 localStorage 时触发，所以不会自激。）
     2026-09-23：两个入口的主题键都要听 —— 从 /olbrportal/ 切主题时写的是
     'olbr.theme'，只听 'msportal.theme.v1' 会漏掉它。时间戳键（'*.t'）
     由门户紧接着写入，本页只关心值键，所以不必额外处理。 */
  window.addEventListener('storage', function (e) {
    if (e.key !== THEME_KEY_MS && e.key !== THEME_KEY_OLBR) return;
    var want = syncEmbedTheme();
    document.documentElement.classList.toggle('dark', want === 'dark');
    if (!current || !isEmbeddable(current)) return;
    loading.style.display = 'flex';
    try { frame.contentWindow.location.reload(); } catch (err) { frame.src = embedSrc(current); }
  });

  // ---- 初始化：**先鉴权、再渲染** ----
  /* ⚠️ 顺序很重要：不能像原来那样先用内置目录把左侧画出来、再异步补权限 ——
     那样受限用户会先看到（并且 iframe 已经加载了）被禁止的报告。所以这里
     先解析门户登录态，拿到结果之后才决定渲染什么。 */
  renderHead();
  elCurTitle.textContent = TXT.loading;
  resolveIdentity().then(function (idn) {
    authReady = true;
    portalUser = idn.authed ? idn.user : null;

    if (!idn.authed) { showAuthGate(); return; }

    recomputeList();
    renderHead();
    var init = findItem(startNo);
    /* 入口指定的看板在「本组 ∩ 有权看」里找不到时，退到第一张有权看的；
       都为空说明该分组下没有任何他有权看的看板 —— 直接给无权限提示，
       不渲染清单也不加载报告。 */
    if (!init || groupsOf(init).indexOf(GID) === -1 || !allowed(init)) init = LIST[0] || null;
    if (!init) {
      var want = findItem(startNo);
      if (want) { showDenied(want); } else { elCurTitle.textContent = '(no dashboards)'; }
      return;
    }
    select(init, false);
    // 首屏就绪后再异步对齐服务端目录（口径同门户首页）
    loadCatalog();
  });
})();
