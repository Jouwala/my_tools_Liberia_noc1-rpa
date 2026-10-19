/* ============================================================================
   olbr.js — OLR MS 门户「只读展示版」
   ----------------------------------------------------------------------------
   数据来源：
     · /MsPortal/assets/data.js   → window.MS_PORTAL_DATA（51 个看板 / 9 分组 / QC 定义 / 升级机制）
     · /MsPortal/assets/access.js → window.MSPortalAccess.canSee（与门户、查看器同一套权限判定）
     · GET/PUT /api/portal-catalog → 服务端全局目录（有则覆盖内置，无则用内置；编辑态可写）
     · GET /api/portal-qc/*       → 六个实时指标与下钻明细
     · /MsPortal/viewer.html      → 看板查看器（打开动作整个交给它，本页不重复实现）
     · /uniplam/api/auth/*        → 用户管理读写**共用**那一份账号库（SQLite，见下）
   本页提供「分组 / 子分组 + 排序」的编辑（2026-09-22 加）；看板维护仍归 /MsPortal/。
   编辑态只在服务端 GET 回 `editable:true` 时出现（= 服务器
   本机或持 X-API-Token），局域网访客看到的仍是纯只读页。改动走 PUT 落到**全局共享**的
   目录，与 MsPortal 同一份文档、同一套语义（subGroups / order / item.subOf），
   所以这边一存，MsPortal 刷新后就是同一个结果；反之 MsPortal 的改动这里也能读到。
   用户管理（2026-09-22 加）是 /uniplam/ 那个弹窗的移植：只走 HTTP 打 /uniplam/api/auth/*，
   不新增 localStorage 键、不新增后端，三个门户改的是同一行记录；入口仅 admin 登录后可见。
   ⚠️ 三条不能碰的红线：
     1  绝不写 `msportal.*` 那几个 localStorage 键（那是 MsPortal 的**个人层**：
        order / assign / groups / renames，跟着写会把别人的界面悄悄改掉）；
        本页自己的持久化只有 `olbr.*`，且只有主题 / 语言 / 页签 / 地图缩放锁，不含目录。
        唯一的例外是 `myapp-theme`：my_app 只认这一个键（theme.ts 的 detectMode 在启动时
        读一次），要把内嵌的报告文件中心染成同一个主题就必须先写它再重设 src —— 与
        MsPortal 的同名内嵌卡是同一件事，副作用也一样（之后直接打开 /myapp/ 也是这个主题）。
     2  PUT 是**整份文档替换**（后端 `_normalize_catalog` 重建字典，没带的键等于删掉），
        所以每次写都要把 items + subGroups + order 三份发全，且 items 用服务端原样那份
        （ITEMS 全量），不是屏幕上的筛选子集 —— 少发一条，全站就少一条看板。
     3  后端**没有版本号 / ETag**，谁最后 PUT 谁赢。因此保存中禁用重复提交（state.saving），
        且一次只改一个字段就立刻落盘，不攒批量改动放大覆盖窗口。

   与 MsPortal 刻意不同的四处（都是上一轮评审的结论）：
     1  搜索与筛选默认收起成一条（2026-09-22 改），且**不持久化**。MsPortal 会把上次的
        筛选写进 localStorage，下次打开时 13 个面板里 7 个显示空态，用户以为系统坏了；
        收起态那条上永远写着命中数和「按什么筛的」，不清空筛选也能收起这一条。
     2  筛选生效时**隐藏没有结果的分组面板**，而不是给每个面板摆一个空态框。
     3  升级机制默认收成一条值班带（52px），展开才出全表（原来常驻 583px）。
     4  卡片只有两种、强调色只有两个色相，图标砖不再按分组上实色。
   ========================================================================== */
// @ts-check —— 显式开启类型守卫（npm run lint:shells → v1/olbrportal/tsconfig.json）。
// 双重保险 + 文档意图：即使 tsconfig 的 checkJs 被关，这一行也能单文件开启检查；
// 读文件的人一眼知道这文件被 lint:shells 覆盖，改它请顺手跑一遍。
(function () {
  'use strict';

  var D = window.MS_PORTAL_DATA || {};
  var ACC = window.MSPortalAccess || { canSee: function () { return true; } };
  var root = document.documentElement;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* 纯数据（i18n 字典 / 图标 / layout 常量 / QC 阈值 / KPI 规格）已外移到
     assets/olbr-data.js，挂 window.OLBR_DATA，本文件只读不写。改文案改阈值
     不用碰这里。加载顺序：index.html 里 olbr-data.js 必须在本文件之前。 */
  var DATA = window.OLBR_DATA || {};
  var S = DATA.S || {};

  function t(k) { var a = S[state.lang] || S.zh; return a[k] != null ? a[k] : (S.zh[k] != null ? S.zh[k] : k); }
  /* 取**指定语言**的文案，与当前 state.lang 无关。
     ⚠️ 改名浮层必须用它，不能用 t()：浮层同时给出 zh / en 两个输入框，
     用 t() 取回落值会把**当前语言**的值同时填进两个框 —— 中文界面下
     英文框里填的是中文，用户一点保存就把英文名覆盖成中文（实测到过：
     两个框都是「全球地图」）。t() 只适合"按当前语言显示一处文案"的场景。 */
  function tIn(lang, k) {
    var a = S[lang] || S.zh;
    if (a[k] != null) return a[k];
    return S.zh[k] != null ? S.zh[k] : k;
  }
  function tf(k, m) { return String(t(k)).replace(/\{(\w+)\}/g, function (_, x) { return m && m[x] != null ? m[x] : ''; }); }

  /* ------------------------------------------------------------- helpers -- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function ls(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function ss(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  /** @param {number} ms 毫秒时间戳 */
  function fmtTime(ms) {
    var d = new Date(ms); if (isNaN(d.getTime())) return '';
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  /* 数据层里 freq / owner 只有中文没有 *En 字段，映射表放在
     /MsPortal/assets/terms.js（刻意不放 data.js —— 那份由 xlsx 重新生成，写进去会被冲掉）。
     英文模式下查不到对应词条时原样返回中文，至少不会显示成空白。 */
  function term(kind, zh) {
    return typeof window.msPortalTerm === 'function' ? window.msPortalTerm(kind, zh) : (zh || '');
  }
  /* 目录里还有 *En 被填成中文原值的脏数据（ownerEn="IP 传输工程师"），
     所以取英文字段走这里：含汉字就当作没有，回查映射表。 */
  function enOf(en, kind, zh) {
    return typeof window.msPortalEnOf === 'function' ? window.msPortalEnOf(en, kind, zh) : (en || term(kind, zh));
  }
  function ic(name) { return '<i class="ph ' + (DATA.PH[name] || DATA.PH.dashboard) + '" aria-hidden="true"></i>'; }

  /* -------------------------------------------------------------- state -- */
  /* 默认语言跟随浏览器（与 index.html 首帧脚本的 guessLang 同一口径，
     两边不一致会闪一下另一种语言）。有用户选择时永远以选择为准。
     ⚠️ 2026-09-30 交叉引用：那个首帧脚本在 index.html 的 <head> 里
        （`(function(){ function guessLang(){...} })()`，L38 起），
        本函数是它的「运行期孪生」。**改判定规则（如默认语言、zh 前缀口径）
        必须两处同改** —— 只改一处会让首帧与挂载后语言不同，表现为闪一下另一种。
        另一处同源点：index.html 里那段脚本还会在首帧前写 html[lang] 与
        html.dark；本函数的 state.theme 则读 root.classList —— 二者也须同口径。 */
  function detectLang() {
    var v = ls('olbr.lang', '');
    if (v === 'en' || v === 'zh') return v;
    var nav = (navigator.language || // @ts-expect-error navigator.userLanguage 是 IE 遗留，标准 lib 未声明，运行时降级到 'zh'
      navigator.userLanguage || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }
  /* 主题判定（2026-09-30 加），与 index.html 首帧脚本**同一套规则**：
     用户显式选择（localStorage 'olbr.theme'）优先；未选择时跟随系统
     prefers-color-scheme。首帧脚本已经据此把 .dark 类落到 <html> 上，
     所以这里正常情况直接读类即可；下面这个函数只在「类没落上」时兜底
     （例如首帧脚本被内容安全策略/异常挡掉），返回值与首帧脚本保持一致。
     ⚠️ 改这里必须同改 index.html <head> 里那段（两边不一致会闪一下另一种主题）。 */
  function hasThemeChoice() {
    var v = null;
    try { v = ls('olbr.theme', null); } catch (e) { /* ignore */ }
    return v === 'dark' || v === 'light';
  }
  function detectTheme() {
    if (root.classList.contains('dark')) return 'dark';
    if (hasThemeChoice()) return ls('olbr.theme', 'light') === 'dark' ? 'dark' : 'light';
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }
  var state = {
    lang: detectLang(),
    theme: detectTheme(),
    user: null, authOk: false, booted: false, userMenuOpen: false, sysMenuOpen: false,
    /* 登录闸门的两态（2026-09-25 加）：
       · gateMode —— 'login' 登录 / 'request' 自助注册申请，与 /uniplam/ 的
         LoginView 同一套两态切换；
       · gateOpen —— 「本页已是免登录身份，但用户主动要进门户」时强制唤起闸门。
       为什么需要它：/api/auth/me 在本机回环下回的是 my_app 的占位身份
       （username:'local'、role:'admin'、**没有 id**），于是 state.authOk 为真、
       闸门被藏起来 —— 后果是顶栏「用户管理」按钮不显示，页面上也再没有任何
       入口能登录门户账号，形成一个走不出去的闭环。 */
    gateMode: 'login', gateOpen: false, umAfterLogin: false,
    items: (D.items || []).slice(), groups: (D.groups || []).slice(), order: {},
    qc: { loading: true, err: '', at: 0, m: {} },
    /* 断站告警单独一档（每 5 分钟），其余五项 + 达标率一小时一档：
       六项里只有告警的源表高频变化，用全量轮询追它等于每小时白跑十一次。 */
    qcAlarm: null, qcFullAt: '', qcAlarmAt: '', qcTrend: {},
    /* 存量趋势（2026-09-25 加）：{ cr: [{h,v}…], pmt: […], sla: […] }。
       与 qcTrend（新增量）**分开存**：两种口径来自不同接口、量纲也不同，
       混在一个对象里迟早会被某个渲染分支当成同一种东西用。
       ⚠️ 拿不到时保留旧值、绝不补 0 —— 断档是真实信息（见 qcStockSeries）。 */
    qcHistory: null,
    /* ---- v1 新增：CXO 每日经营指标 + 月可用率（见 renderKpi）----
       kpi 与 qc 两套数据**分开存**：它们来自不同接口、刷新节奏也不同
       （kpi 是日粒度，上游一天才动一次），混在一份 state 里会让任一边的
       失败把另一边也置成错误态。
       2026-09-24：新增 olib 一路（90 天经营看板）。它**不是** vmax 的替代品 ——
       vmax 给的是「当日进行中」的实时值，olib 给的是「昨日完整值 + 90 天极值 +
       周/月同比 + 迷你走势」。上面四张富卡片要的是后者，所以两路都留着。 */
    /* speed  = Ookla 竞对（bm_speedtest）/ meta = Meta 基准报告（bm_meta）：
       Benchmark 行两组卡的数**分开存**。它们来自两个接口、两份数据
       （一份是测试库、一份是 Excel 导入的快照），混在一份 state 里
       任一边失败都会把另一边的卡擦成 —。 */
    kpi: { loading: true, err: '', at: '', avail: null, olib: null, speed: null, meta: null },
    /* v1 新增：六个视图入口卡里「展开其余 N 项」的开合态。
       与 auxOpen 同一套语义（键 = 视图分组 id），但**分开存** ——
       上面的 L2 辅助区与这里的入口卡是两处独立的 UI，
       共用一份状态会让「在入口卡展开 BO View」把下面的辅助区也一起展开。 */
    v6Open: {},
    /* 六个视图入口卡里「子分组页签」的选中态（2026-09-27 加），键 = 分组 id。
       与 v6Open / auxOpen 同一套「按分组分开存」的理由：共用一份状态会让
       「在 BO View 选了 MW」顺带把 SP View 也筛成 MW。
       刻意**不持久化**：与搜索/筛选同一口径，每次进来都是完整的一列，
       否则用户会看到一个被上次会话筛掉一半、又找不到原因的列表。 */
    v6Sub: {},
    /* 「全部」视图下每个专业域分段的折叠态（2026-10-12 加），键 = 子分组 id。
       与 viewer.js 的 state.subOpen 同一取舍：默认展开、**不持久化** ——
       它是「我这次翻到哪了」的临时视图状态，下次进来应回到全展开，
       否则用户会碰上「点开看不见条目，因为上次把域都折起来了」。 */
    v6SubFold: {},
    escOpen: true,
    /* 「展开全部」是否已把 21 行全放出来。
       ⚠️ 必须与 escOpen 分开，两个是正交的维度：
         · escOpen = 这张表整体是摊开还是收成一条值班带；
         · escAll  = 摊开时显示 4 行还是全部 21 行。
       曾经只用一个 escOpen 表达这两件事，结果点「展开全部」只翻转了箭头、
       行数仍被 slice(0,4) 卡死在 4 行 —— 按钮上写着"展开全部"却纹丝不动，
       用户看到的正是"点了没实现显示全部，而是缩回去了"。 */
    escAll: false,
    auxOpen: {},
    /* 2026-09-29（用户要求）：归档区**默认隐藏** —— 开关就是 state.recall。
       它只由"用户当场做了归档这个动作"打开（dropItemFromGroup 与分组浮层的 setGroups），
       刷新即丢。为什么不能用"本会话渲染过归档区"当判据，见 renderArchive() 的注释。 */
    recall: false,
    /* 当前选中的地图页签（gis / person / mwRealTime）。跨会话记住上次看的那一页。
       2026-09-29：本栏恢复成两个页签后它重新有了消费方（curMap / mapHeadHtml /
       mapClick）；2026-10-19 起三页签（多一个 person）。
       默认 'gis' 与 DATA.MAP_TABS 的第一项一致。 */
    mapTab: ls('olbr.maptab', 'gis'),
    /* 知识问答栏当前选中的页签（'rag' / 'eflow'，2026-10-12 加）。
       与 mapTab 同一口径：持久化到 localStorage，跨会话记住上次看的那一个。
       默认 'eflow' 与 qaItems() 返回的第一项（eFlow，2026-10-12 起排在前面）一致。 */
    qaTab: ls('olbr.qatab', 'eflow'),
    /* 地图滚轮缩放锁（2026-10-22 加）：true = 锁定，鼠标在地图上滚动**滚页面**，
       滚轮不会缩放地图；false = 解锁，滚轮直接缩放地图。
       ⚠️ 默认 true 是这次改动的**全部意义**所在 —— 见 applyMapWheelLock 上方那段
       需求记录（用户报「鼠标下滑时容易滚进地图里」）。
       与 mapTab 同一口径持久化到 localStorage（键在文件头 L20 那张清单里）：
       用户在整页里滚上滚下的习惯是稳定的，每次打开都要重新点一次锁等于没解决。
       ⚠️ 存的是布尔不是字符串：ls() 只在**键不存在**时给默认值，一旦有人写入
       'false' 这个字符串，'false' 是 truthy —— 故读的时候显式比 '1'。 */
    mapWheelLock: ls('olbr.mapwheellock', '1') === '1',
    /* 默认落在 BO View：16 张卡、五个子分组，是这块最能说明「门户里到底有什么」的一组 */
    viewTab: ls('olbr.viewtab', 'BO View'),
    viewSub: '',                          /* 当前分组下的二级子页签，不跨分组记 */
    subGroups: null,                      /* catalog.subGroups 归一化后的定义，null = 用内置 */
    /* 拓扑地图 4 个页签的显示名覆盖（2026-09-23 加），来自服务端 catalog.tabLabels：
       { 'gis': {zh:'…', en:'…'}, … }。未加载/未配置时为 null → 用 i18n 字典的内置文案。
       搬上服务端的理由与 subGroups/groups 当初一样：写死在代码里就只能改代码 + 强刷，
       而且 MsPortal 与 olbrportal 各有一份字典、容易改歪。 */
    tabLabels: null,
    /* ---- 编辑态（2026-09-22 加）---- */
    /* catalogEditable 只认服务端 GET 回的 `editable`（= 服务器本机 / 持 X-API-Token），
       不写死、也不从本地推断 —— 猜错的表现是「点了保存才 403」。 */
    catalogEditable: false, editing: false, saving: false,
    subEdit: '',                          /* 正在改名的子分组 id（同时只开一个） */
    grpFor: null,                         /* 分组归属浮层当前挂在看板编号上 */
    popForm: null,                        /* 改名类浮层：{kind:'grp'|'grpadd'|'title'|'maptab'|'itemadd', id} */
    /* 新增看板的「选模板」两步态（2026-09-26 加）：
       tplPick 非空 = 第一步浮层正开着；tplBtn 是触发那颗按钮（浮层要贴着它定位）；
       tplCarry 是「换一个模板」带回第一步的已填值，避免重选一次就白填一遍；
       addGid 是这次新增要落到哪一列 —— 必须独立于 tplPick 存，
       因为 openForm 里的 closeGrp() 会把 tplPick 清掉。 */
    tplPick: null, tplBtn: null, tplCarry: null, addGid: '',
    dragKind: '', dragNo: null, dragGid: '', dragEl: null, dragBefore: false,
    /* ---- 用户管理弹窗（2026-09-22 加）----
       只放界面态，账号数据一律现取现用（state.um.users 是 /uniplam/api/auth/users
       的返回，不落本地）：同一份库有三个操作界面，缓存下来必然读到旧数据。 */
    um: {
      open: false, loading: false, users: [], requests: [], storage: null,
      portalGroups: null, portalGroupLabels: null, portalDashboards: null, portalGroupsErr: false,
      nu: '', np: '', nr: 'viewer',
      resetId: '', resetPwd: '', approveRoles: {},
      profileId: '', pv: '', pc: '', restricted: false, groups: [], cards: [],
      saving: false, busy: '', error: '', success: ''
    },
    drill: { metric: '', q: '', page: 1, size: 50, sort: '', dir: 'desc', rows: [], columns: [], total: 0, loading: false, err: '' }
  };

  /* ---------------------------------------------------------- catalog -- */
  var ITEMS = [];
  function setCatalog(items) { ITEMS = items || []; }
  setCatalog(state.items);

  function inGroup(it, gid) { return (it.groups || []).indexOf(gid) !== -1; }
  function canSee(it) { try { return ACC.canSee(state.user, it); } catch (e) { return true; } }
  function allowed() { return ITEMS.filter(canSee); }

  function orderIdx(gid) { var a = state.order[gid]; return Array.isArray(a) ? a : null; }
  function sorter(gid) {
    var seq = orderIdx(gid);
    return function (a, b) {
      if (seq) {
        var ia = seq.indexOf(a.no), ib = seq.indexOf(b.no);
        if (ia !== -1 || ib !== -1) return ia === -1 ? 1 : ib === -1 ? -1 : ia - ib;
      }
      return (b.clicks || 0) - (a.clicks || 0) || (a.no || 0) - (b.no || 0);
    };
  }

  /* 2026-10-16：检索轨（Search & filters，Ctrl K）按用户要求整块移除 ——
     入口按钮、搜索框、分组 chips、状态筛选、命中计数与快捷键全部删除。
     随之成为死代码的 tokens() / hay() / match() / filtering() 与按词高亮的 hl()
     一并删除（历史上它们只服务检索轨；要恢复这段功能回 git 历史取本提交的
     上一版即可）。目录结构与「归档」等分组语义不受影响。 */
  /* 某分组下的全部可见条目：权限过滤 + 点击排序。检索轨还在时这里是
     filtered()（额外吃搜索词 / 全局分组 / 状态三路筛选），轨删掉后那三路
     失去入口，只剩「组内清单」这一件事还有消费方 —— panelHead 计数、
     #aux 辅助区、OSS Portal Login、System Management 菜单四处共用。 */
  function groupItems(gid) {
    return allowed().filter(function (it) { return !gid || inGroup(it, gid); }).sort(sorter(gid));
  }
  function knownGids() {
    var seen = {}; state.groups.forEach(function (g) { seen[g.id] = 1; });
    DATA.T0.concat(DATA.T1, DATA.T2).forEach(function (g) { seen[g] = 1; });
    return Object.keys(seen);
  }
  function groupsOf(it) { return it.groups || []; }
  /* ============================================================================
     归档分组（2026-09-28 加）
     ----------------------------------------------------------------------------
     解决的问题：「移出本列」原先在只剩一个分组时直接拒绝（edit.itemLastGrp），
     理由是目录里不存在"零归属看板"这种状态 —— 零归属的条目在页签、入口卡、
     MsPortal 的区块里全都渲染不出来，移出等于弄丢。想"收起来"就只能用
     不可逆的「删除看板」，代价太大。

     归档把它变成一个有家可归、且**可逆**的动作：条目只是换到一个真实分组里。
     为此必须同时满足三件事，缺一个就会退化成"换个地方弄丢"：

       ① 归档必须是一个**真实分组**（进 state.groups、随目录落盘），
          否则 commit() 的 PUT 里 groups 不含它，下次加载 sanitize 时条目归属
          会指向一个不存在的分组 —— 又回到"看不见"的老问题；
       ② 归档区必须**真的渲染出来**（renderAux，默认折叠），
          否则用户点完「移出本列」看到的是"卡没了"；
       ③ 必须给一条**回去的路**（归档行的「取消归档」+ 保留「分组」浮层）。

     ⚠️ 为什么归档不进 T1/T2、也不单独占一列：
     它是"收起来"的去处，不是常驻版面。作为自定义分组它会自动出现在 L1 页签条
     （tabGids 会把 state.groups 里 T0/T1/T2 之外的分组追加进去），
     这是刻意的：页签是可排序的，管理员可以把它拖到任意位置，
     而不是被代码钉死在某一列。
     ============================================================================ */
  function isArchiveGid(gid) { return gid === DATA.ARCHIVE; }
  /* 归档分组的显示名：目录里没有定义时回落 i18n 的 arch.title，
     这样"还没建过归档组"的目录也能正确显示名字（gName 对未知 id 是原样返回 id）。 */
  function archiveName() { return gName(DATA.ARCHIVE) === DATA.ARCHIVE ? t('arch.title') : gName(DATA.ARCHIVE); }
  /* 按需创建归档分组。只在真的归档了第一张看板时调用 ——
     不在 boot 时预建：绝大多数会话不会用到它，凭空多一个分组定义会让
     "分组"浮层和页签条上多出一项没人要的东西。 */
  function ensureArchiveGroup() {
    if (state.groups.some(function (g) { return g.id === DATA.ARCHIVE; })) return;
    state.groups = state.groups.concat([{
      id: DATA.ARCHIVE, zh: t('arch.title'), en: 'Archived',
      subZh: '', subEn: '', style: 'card'
    }]);
  }
  /* 页签条上的分组 = 固定四个 + 服务端新增的分组（按 groups 数组顺序排在后面）。
     新增分组没有专门的 tier 字段，一律落到 L1 页签：它是「用户自己造的一级分组」，
     出现在最显眼的那一排最不容易让人找不到。 */
  function tabGids() {
    var out = DATA.T1.slice(), seen = {};
    DATA.T0.concat(DATA.T1, DATA.T2).forEach(function (g) { seen[g] = 1; });
    state.groups.forEach(function (g) { if (g && g.id && !seen[g.id]) { seen[g.id] = 1; out.push(g.id); } });
    return out;
  }
  /* 已经被版面安置的分组：左栏 + 页签 + 辅助区。用于「其他看板」兜底与主分组判定。 */
  function placedGids() { return DATA.T0.concat(tabGids(), DATA.T2); }
  function primaryGroup(it) {
    var g = groupsOf(it); if (!g.length) return '';
    var all = placedGids();
    for (var i = 0; i < all.length; i++) if (g.indexOf(all[i]) !== -1) return all[i];
    return g[0];
  }

  /* -------------------------------------------------------------- labels -- */
  function gName(id) {
    var g = state.groups.filter(function (x) { return x.id === id; })[0];
    if (g) return state.lang === 'en' ? (g.en || g.id) : (g.zh || g.id);
    return id;
  }
  function gSub(id) {
    var g = state.groups.filter(function (x) { return x.id === id; })[0];
    if (!g) return '';
    return state.lang === 'en' ? (g.subEn || '') : (g.subZh || '');
  }
  /* titleOf/descOf 返回**原文**，转义只发生在写进 HTML 的那一刻：
     这里再 esc() 会叠成 &amp;amp;，页面上就露出 &amp; 这种字面实体。 */
  function titleOf(it) { return (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) || '#' + it.no; }
  function descOf(it) { return state.lang === 'en' ? (it.descEn || it.descZh || '') : (it.descZh || it.descEn || ''); }
  function ownerOf(it) { return state.lang === 'en' ? enOf(it.ownerEn, 'owner', it.owner) : it.owner; }
  function freqOf(it) { return state.lang === 'en' ? term('freq', it.freq) : it.freq; }
  function pfOf(it) { return t('pf.' + it.platform) || it.platform; }
  function stOf(it) { return it.status === 'beta' ? t('st.beta') : t('st.online'); }
  /* 跨壳语言传递（2026-09-30 加）：本页把用户的选择存在 'olbr.lang'，而点进去的
     下级页各有各的键 —— /MsPortal/ 与 viewer.html 只认 'msportal.lang.v1'，
     /myapp/ 只认 'app-locale'，三个键互不相通。于是下一层的判定链退化成
     「本站没存过 → 按浏览器语言」，中文 Windows 上就是"门户选了英文、点进去满屏中文"。
     （主题当年没这个问题：门户给 my_app 带 &theme= 并共用 myapp-theme，见 mapItems/emailSrc。）
     所以出链统一带 &lang=，把当前选择显式交给下一层；接收侧的优先级是
     ?lang= > 本站点键 > olbr.lang > 浏览器语言。 */
  function langVal() { return state.lang === 'en' ? 'en' : 'zh'; }
  function langQs() {
    return '&lang=' + encodeURIComponent(langVal());
  }
  function vlink(it, gid) {
    return '/MsPortal/viewer.html?no=' + encodeURIComponent(it.no) +
      '&gid=' + encodeURIComponent(gid || primaryGroup(it) || '') + langQs();
  }
  /* 高亮命中词的 hl() 已随检索轨（2026-10-16）整块移除：它唯一的输入是搜索词
     tokens()，轨删了之后永远等价于 esc()，卡片标题/描述的转义直接用 esc()。 */

  /* --------------------------------------------------------------- cards -- */
  function metaHtml(it) {
    var bits = [];
    bits.push('<span class="st st-' + (it.status === 'beta' ? 'beta' : 'online') + '">' + stOf(it) + '</span>');
    bits.push('<span class="pf">' + esc(pfOf(it)) + '</span>');
    if (it.freq) bits.push('<span>' + esc(freqOf(it)) + '</span>');
    var ow = ownerOf(it); if (ow) bits.push('<span class="ow">' + esc(ow) + '</span>');
    return '<span class="meta">' + bits.join('<span class="dot">·</span>') + '</span>';
  }
  /* 编辑态卡片底部那排小按钮。分组归属只对「在某个真分组里看这张卡」时有意义，
     所以 L0 的 CXO 焦点卡只给改标题；页签/SP 清单两张都给。

     2026-09-26 起末尾再加两颗（只在有 gid 时给，即「在某列里看这张卡」）：
       · 移出本列 —— 摘掉一个分组归属，可逆
       · 删除看板 —— 从共享目录移除，不可逆
     两者视觉上要能分开：删除那颗用 .ct--del 上危险色（见 olbr.css），
     不然一排同款灰按钮里点错代价很大。 */
  function edBtns(it, gid, withGrp) {
    var b = '';
    if (withGrp && gid) {
      b += '<button type="button" class="ct" data-act="grp" data-no="' + esc(it.no) +
        '" title="' + esc(t('edit.groupsTip')) + '"><i class="ph ph-folders" aria-hidden="true"></i>' +
        esc(t('edit.groups')) + '</button>';
    }
    b += '<button type="button" class="ct" data-act="title" data-no="' + esc(it.no) +
      '" title="' + esc(t('edit.titleTip')) + '"><i class="ph ph-text-format" aria-hidden="true"></i>' +
      esc(t('edit.title')) + '</button>';
    if (withGrp && gid) {
      b += '<button type="button" class="ct" data-act="item-drop" data-no="' + esc(it.no) +
        '" data-gid="' + esc(gid) + '" title="' + esc(t('edit.itemDropTip')) + '">' +
        '<i class="ph ph-minus-circle" aria-hidden="true"></i>' + esc(t('edit.itemDrop')) + '</button>' +
        '<button type="button" class="ct ct--del" data-act="item-del" data-no="' + esc(it.no) +
        '" title="' + esc(t('edit.itemDelTip')) + '">' +
        '<i class="ph ph-trash" aria-hidden="true"></i>' + esc(t('edit.itemDel')) + '</button>';
    }
    return '<span class="c-ed">' + b + '</span>';
  }
  /* 条目卡：卡片流 —— 一行放得下几张就几张，排满自动折到下一行。
     说明在卡里最多两行，全文留在 title 提示里。 */
  function itemCard(it, gid) {
    var ed = canEdit() && gid;
    /* 编辑态给卡片加 draggable + data-gid：拖拽只认「同一分组内」的落点（见 bindDrag），
       data-no 一直都在（查看器链接靠它）。分组按钮必须 preventDefault —— 它在 <a> 里面，
       不拦就会顺手把查看器开一个新标签。 */
    return '<a class="card' + (ed ? ' is-ed' : '') + '" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" ' +
      'title="' + esc(descOf(it)) + '" data-no="' + esc(it.no) + '"' +
      (ed ? ' draggable="true" data-gid="' + esc(gid) + '"' : '') + '>' +
      '<span class="c-ico">' + ic(it.icon) + '</span>' +
      '<span class="c-bd"><span class="c-t">' + esc(titleOf(it)) + '</span>' +
      '<span class="c-d">' + esc(descOf(it)) + '</span>' + metaHtml(it) +
      (ed ? edBtns(it, gid, true) : '') + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }
  function focusCard(it, gid) {
    var ed = canEdit();
    return '<a class="fcard' + (ed ? ' is-ed' : '') + '" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" data-no="' + it.no + '">' +
      '<span class="ic-ico">' + ic(it.icon) + '</span>' +
      '<span class="ic-bd"><span class="ttl">' + esc(titleOf(it)) + '</span>' +
      '<span class="dsc">' + esc(descOf(it)) + '</span>' + metaHtml(it) +
      (ed ? edBtns(it, gid, false) : '') + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }

  /* -------------------------------------------------------------- render -- */
  function panelHead(gid, extraTools, nArg) {
    var n = nArg == null ? groupItems(gid).length : nArg;
    /* 「重置顺序」只在该分组真有自定义顺序时才出现 —— 没有顺序还给按钮就是噪声。
       落盘写的是 order[gid] = []（显式空数组），不是删键：两者对前端的含义不同。 */
    var rst = canEdit() && (state.order[gid] || []).length
      ? '<button type="button" class="ct ct--rst" data-act="rst-order" data-gid="' + esc(gid) +
        '" title="' + esc(t('edit.resetTip')) + '"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>' +
        esc(t('edit.reset')) + '</button>' : '';
    var gt = '';
    if (canEdit() && gid && gid !== DATA.OTHER) {
      /* 分组改名/新增的入口挂在面板头上，而不是页签上：页签里再塞一颗按钮就是
         button 套 button（非法 HTML），而且一次只有一页是展开的，页签上改不到别的组。 */
      gt = '<button type="button" class="ct" data-act="grp-edit" data-gid="' + esc(gid) +
        '" title="' + esc(t('edit.grpEditTip')) + '"><i class="ph ph-tag" aria-hidden="true"></i>' +
        esc(t('edit.grpEdit')) + '</button>' +
        '<button type="button" class="ct" data-act="grp-add" title="' + esc(t('edit.grpAddTip')) +
        '"><i class="ph ph-folder-plus" aria-hidden="true"></i>' + esc(t('edit.grpAdd')) + '</button>';
    }
    return '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(gName(gid)) + '</span>' +
      '<span class="p-s">' + esc(gSub(gid)) + '</span></span>' +
      '<span class="cnt">' + n + '</span>' + rst + gt +
      (extraTools || '') +
      '<a class="p-x" href="/MsPortal/viewer.html?gid=' + encodeURIComponent(gid) + langQs() +
      '" target="_blank" rel="noopener noreferrer">' + t('v.open') + ' <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a></div>';
  }

  /* =============== QC 指标卡（与 MsPortal 的 Quality Control 同一套口径）===============
     阈值 / 趋势分桶 / 两档刷新节奏照抄 MsPortal/assets/portal.js 的 2026-09-22 改版实现，
     连文案都沿用同一份 —— 同一个数字在两个门户上给出不同的红黄判定，比样式不一致更糟。
     ⚠️ DATA.QC_TARGETS 是**首版默认值**（依据只有实测量级 + NOC 常识），不是业务方给的目标值；
        正式目标到位后只改 assets/olbr-data.js 的 DATA.QC_TARGETS，并且记得同步 MsPortal 那份。 */
  function fmt(n) { return n == null || isNaN(Number(n)) ? '—' : Number(n).toLocaleString('en-US'); }
  /* 分级只看数值：无值 / 非数字 / 没配阈值一律 'na'，绝不当成 0、也绝不当成正常。
     达标率必须走 dir='down'，否则 95% 这种好值会被判进最严重一档 —— 分级一旦出现
     这种反向误报，运维就会整体忽略它。 */
  function qcLevel(id, v) {
    var tg = DATA.QC_TARGETS[id];
    if (!tg || v == null || isNaN(Number(v))) return 'na';
    var n = Number(v);
    if (tg.dir === 'down') return n < tg.warn ? 'crit' : (n < tg.crit ? 'warn' : 'ok');
    return n >= tg.crit ? 'crit' : (n >= tg.warn ? 'warn' : 'ok');
  }
  /* 告警优先用 5 分钟那一档：它比全量新，且失败时会被置成 error 态，
     不会把一小时前的旧数字留在屏幕上冒充实时值。 */
  function qcMetric(id) {
    if (id === 'alarm' && state.qcAlarm) return state.qcAlarm;
    return (state.qc.m && state.qc.m[id]) || null;
  }
  /* 后端 generated_at 写死 +08:00，页面时钟用浏览器本地时区：直接切字符串会出现
     「时钟 18:07 / 更新于 02:07」，看着像 8 小时前的旧数据（MsPortal 踩过这个坑）。 */
  function qcClock(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso || '').slice(11, 19);
    function p(v) { return String(v).padStart(2, '0'); }
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function qcAgo(iso) {
    if (!iso) return '';
    var ms = new Date(iso).getTime();
    if (isNaN(ms)) return '';
    var s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 90) return t('qc.ago.now');
    if (s < 3600) return tf('qc.ago.min', { n: Math.round(s / 60) });
    if (s < 86400) return tf('qc.ago.hour', { n: Math.round(s / 3600) });
    return tf('qc.ago.day', { n: Math.round(s / 86400) });
  }
  function qcMetricAt(id) { return id === 'alarm' ? (state.qcAlarmAt || '') : (state.qcFullAt || ''); }
  function qcLatestStamp() {
    var a = state.qcAlarmAt, f = state.qcFullAt;
    if (a && f) {
      var da = new Date(a).getTime(), df = new Date(f).getTime();
      if (!isNaN(da) && !isNaN(df)) return da >= df ? a : f;
    }
    return a || f || '';
  }
  /* 下一格还有多少毫秒：按**墙上的钟**算，不用 interval 累加 —— interval 从进页面那刻
     起算，:07 进页面时 :06 刚同步好的数据就要再等 59 分钟才上屏。
     网格原点取本地当天 0 点（不是 epoch），+05:30 这类半小时时区才不会整体偏 30 分钟。 */
  function qcNextDelay(stepMin, offsetSec, now) {
    var n = now || new Date();
    var step = stepMin * 60000;
    var dayStart = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    var target = dayStart + Math.floor((n.getTime() - dayStart) / step) * step + offsetSec * 1000;
    if (target <= n.getTime()) target += step;
    return target - n.getTime();
  }
  function qcCountdown() {
    var left = Math.max(0, Math.round(Math.min(
      qcNextDelay(DATA.QC_FULL_MIN, DATA.QC_FULL_OFFSET),
      qcNextDelay(DATA.QC_ALARM_MIN, DATA.QC_ALARM_OFFSET)) / 1000));
    function p(v) { return String(v).padStart(2, '0'); }
    return p(Math.floor(left / 60)) + ':' + p(left % 60);
  }

  /* ---- 新增量趋势（GET /api/portal-qc/trend）：粒度和窗口由后端按指标定，前端不猜 ---- */
  function qcTrendSeries(id) {
    var tr = state.qcTrend && state.qcTrend[id];
    if (!tr || !tr.points || !tr.points.length) return null;
    var grain = tr.grain === 'day' ? 'day' : 'hour';
    var map = {};
    tr.points.forEach(function (p) { map[p.t] = (map[p.t] || 0) + Number(p.v || 0); });
    var keys = Object.keys(map).sort();
    if (keys.length < 2) return null;
    function parseKey(k) {
      var m = grain === 'day' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(k)
                              : /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2})/.exec(k);
      if (!m) return null;
      return new Date(+m[1], +m[2] - 1, +m[3], grain === 'day' ? 0 : +m[4], 0, 0);
    }
    function fmtKey(d) {
      var p = function (n) { return (n < 10 ? '0' : '') + n; };
      var s = d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
      return grain === 'day' ? s : s + ' ' + p(d.getHours()) + ':00';
    }
    var start = parseKey(keys[0]), end = parseKey(keys[keys.length - 1]);
    if (!start || !end) return null;
    /* 连续时间轴逐格推进、缺桶补 0：按点数等距排开会把「中间断了 8 小时」画成
       「连续 8 小时」，等于在横轴上撒谎。格子数超上限时从尾部收窄窗口，
       始终保证连续（近 30 天按小时是 720 格，上一版在这里静默降级过）。 */
    var stepMs = grain === 'day' ? 86400000 : 3600000, MAX_SLOTS = 200;
    if (Math.round((end.getTime() - start.getTime()) / stepMs) + 1 > MAX_SLOTS) {
      start = new Date(end.getTime() - (MAX_SLOTS - 1) * stepMs);
    }
    if (grain === 'hour' && tr.window === 'today') {
      /* 「今天」要铺满 00:00→23:00：凌晨那条空白本身就是要看的信息，
         而且横轴恒为 24 格，刷新时卡片宽度才不会一会儿宽一会儿窄。 */
      start = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 0, 0, 0);
      end = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 23, 0, 0);
    } else if (grain === 'day') {
      var span = Math.max(2, tr.days || 30) - 1, now = new Date();
      end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      start = new Date(end.getTime() - span * 86400000);
    }
    var vals = [], labels = [];
    for (var tk = start.getTime(); tk <= end.getTime(); tk += stepMs) {
      var k = fmtKey(new Date(tk));
      vals.push(map[k] || 0);
      labels.push(k);
    }
    return { grain: grain, vals: vals, labels: labels, window: tr.window || 'days',
      days: tr.days || null, total: vals.reduce(function (a, b) { return a + b; }, 0) };
  }
  /* 迷你趋势线：内联 SVG，零依赖（门户要求零 CDN、断网可用）。点 < 2 返回 ''。
     preserveAspectRatio=none 让它随卡宽拉伸，所以刻意不画端点圆点（会被拉成椭圆）。

     ⚠️ 2026-09-25：本函数由「新增量专用」改为**两条口径共用**，方法体抽到
     qcSparkSvg(vals)。区别只有一处，但很关键：**接受 null 并在此处断开折线**。
     新增量的空档是真 0（那段时间确实没有新增），存量的空档是「没采到」
     （快照只在门户开着的小时写入）—— 后者若也补 0，就会画出一个
     「积压突然清零」的假谷底。所以补 0 的决定权留在各自的 *Series 里，
     这里只负责「遇到 null 就断」。 */
  function qcSparkSvg(vals) {
    if (!vals || vals.length < 2) return '';
    var W = 300, H = 26, PAD = 4;
    /* min/max 只在**真实点**上取：把 null 当 0 参与极值计算会把整条线压扁。 */
    var real = vals.filter(function (n) { return n != null; });
    if (real.length < 2) return '';
    var min = Math.min.apply(null, real), max = Math.max.apply(null, real);
    var span = (max - min) || 1, step = W / (vals.length - 1);
    var seq = [], curArea = [], segs = [];
    vals.forEach(function (n, i) {
      if (n == null) {
        /* 断档：收掉当前段，下一点用 M 重新起笔（而不是 L 连过去）。
           视觉上是一条断开的线 —— 如实表达「这段时间没有样本」。 */
        if (curArea.length > 1) segs.push({ line: curArea.slice(), area: curArea.slice() });
        curArea = [];
        return;
      }
      var p = [i * step, PAD + (H - PAD * 2) * (1 - (n - min) / span)];
      curArea.push(p);
    });
    if (curArea.length > 1) segs.push({ line: curArea.slice(), area: curArea.slice() });
    if (!segs.length) return '';
    var d2 = function (pts) {
      return pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    };
    /* 面积逐段闭合：整条线共用一个面积路径时，断档两侧会被一条横跨缺口的
       底线连起来，看起来像"那段有数据且为最小值"。 */
    var line = segs.map(function (s) { return d2(s.line); }).join(' ');
    var area = segs.map(function (s) {
      var first = s.area[0], last = s.area[s.area.length - 1];
      return d2(s.area) + ' L' + last[0].toFixed(1) + ' ' + H + ' L' + first[0].toFixed(1) + ' ' + H + ' Z';
    }).join(' ');
    return '<span class="qc-spark" aria-hidden="true"><svg viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none"><path class="sp-area" d="' + area + '"/><path class="sp-line" d="' + line +
      '" vector-effect="non-scaling-stroke"/></svg></span>';
  }
  /* 迷你柱状图：与 qcSparkSvg **同一份输入、同一套尺寸**，只换画法
     （2026-09-28 用户要求「当前的曲线换成柱状，数字不变」）。

     为什么用 <path> 逐根画柱子、而不是 N 个 <rect>：
       svg 上挂着 preserveAspectRatio="none"（随卡宽横向拉伸，这样才能填满
       240px 左右的卡宽而不留边），矩形一旦被横向拉伸，**描边会被拉成
       不成比例的粗边**、圆角也会被拉成椭圆。整根柱子写成一个闭合路径、
       再把描边一起交给同一个 transform，与折线用的是同一条既有约定
       （qcSparkSvg 也正是为此不画端点圆点）。所以这里同样只输出路径。

     为什么保留 preserveAspectRatio="none"：卡片宽度是网格给的（约 242px），
     若改成等比，SVG 会按 300×26 的比例算高、横向留一圈空白。
     柱子被横向拉伸在视觉上只是「变宽」，不像折线那样会改变斜率含义。

     空档（null）**不画柱子**，也不补 0 —— 与折线同一条口径：
     补 0 会画出一根「积压清零」的假柱子，那比缺一根严重得多。
     柱子基线固定在 H（底部），高度按**0 到 max** 归零，
     而不是像折线那样按 min~max 拉伸：折线的 min/max 归一只是为了看清起伏，
     但柱子的高度是「量」，从 0 起算才对得上「谁比谁多」。 */
  function qcBarsSvg(vals) {
    if (!vals || vals.length < 2) return '';
    var W = 300, H = 26;
    var real = vals.filter(function (n) { return n != null; });
    if (real.length < 2) return '';
    var max = Math.max.apply(null, real);
    /* 全 0（例如某指标这些天确实一次新增都没有）：画一条贴底的细线，
       而不是返回空串 —— 空串会让卡片挂上 is-nospark 并把内容垂直居中，
       看起来像「这个指标没有趋势」，而事实是「趋势就是恒为 0」。 */
    if (!(max > 0)) max = 1;
    var n = vals.length;
    /* 每根柱占一格，柱与柱之间留 2px 视觉缝（按槽宽比例给，随卡宽等比缩放）。
       槽宽低于 2px 时不再留缝（否则柱子会被缝隙吃光），此时 svg 已经很密，
       间距本来也分辨不出来。 */
    var slot = W / n;
    var gap = slot > 2 ? Math.min(slot * 0.34, 1.6) : 0;
    var bw = Math.max(slot - gap, slot * 0.34);
    var paths = [];
    vals.forEach(function (v, i) {
      if (v == null) return;                 // 空档：不画，也不补 0
      var h = (H - 1) * (Number(v) / max);
      if (!(h > 0)) h = 0.6;                 // 真 0 也给一丝可见的高度，否则那格看着像空档
      var x = i * slot + (slot - bw) / 2;
      paths.push('M' + x.toFixed(2) + ' ' + H +
        ' L' + x.toFixed(2) + ' ' + (H - h).toFixed(2) +
        ' L' + (x + bw).toFixed(2) + ' ' + (H - h).toFixed(2) +
        ' L' + (x + bw).toFixed(2) + ' ' + H + ' Z');
    });
    if (!paths.length) return '';
    return '<span class="qc-spark" aria-hidden="true"><svg viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none"><path class="sp-bar" d="' + paths.join(' ') +
      '" vector-effect="non-scaling-stroke"/></svg></span>';
  }
  function qcBars(id) {
    var s = qcTrendSeries(id);
    if (!s || s.vals.length < 2) return '';
    return qcBarsSvg(s.vals);
  }
  /* ⚠️ 2026-09-28：折线版 qcSpark() 目前**没有调用点**
     （告警带两个插槽都改走 qcBars / qcBarsSvg，可用率卡直接调 qcSparkSvg）。
     刻意保留而不是删：它与 qcBars 是同一组口径的两种画法，
     将来若要切回折线，接回 qcSparkSlot / qcStockSlot 即可。
     ⚠️ 别据此以为"全页都是柱子"—— KPI 那三张可用率卡画的**就是折线**
     （见 availSpark），那是本函数之外独立的一处。 */
  function qcSpark(id) {
    var s = qcTrendSeries(id);
    if (!s || s.vals.length < 2) return '';
    return qcSparkSvg(s.vals);
  }

  /* 存量序列（2026-09-25 加）：把每小时快照对齐到**连续小时轴**上。
     与 qcTrendSeries 的关键差异：缺格推 null 而不是 0，并统计 gaps。
     为什么必须连续轴：按点数等距排开，会把「中间断了 20 小时」画成
     「连续 20 小时」—— 等于在横轴上撒谎（本文件 qcTrendSeries 已有同样教训）。 */
  function qcStockSeries(id) {
    var all = state.qcHistory && state.qcHistory[id];
    if (!all || !all.length) return null;
    var pts = all.filter(function (p) {
      /* ⚠️ 必须先挡 null / '' 再 Number()：Number(null) === 0 是**有限数**，
         会被当成「那一刻积压是 0」收进来，画出假的清零谷底。
         后端对接口失败的小时给的就是 v: null（见 portal_qc.py 的 series 构造）。 */
      return p && p.h && p.v != null && p.v !== '' && isFinite(Number(p.v));
    }).map(function (p) { return { h: p.h, v: Number(p.v) }; })
      .sort(function (a, b) { return a.h < b.h ? -1 : (a.h > b.h ? 1 : 0); });
    if (pts.length < 2) return null;
    var map = {};
    pts.forEach(function (p) { map[p.h] = p.v; });
    function parseKey(k) {
      var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2})/.exec(k);
      return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], 0, 0) : null;
    }
    function fmtKey(d) {
      var p = function (n) { return (n < 10 ? '0' : '') + n; };
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
        ' ' + p(d.getHours()) + ':00';
    }
    var start = parseKey(pts[0].h), end = parseKey(pts[pts.length - 1].h);
    if (!start || !end) return null;
    var MAX_SLOTS = 400;   // 约 16 天小时轴；超了从尾部收窄，保证轴始终连续
    /* 相减用 .getTime() 而**不是** (end - start)：两个 Date 相减在运行时靠
       valueOf 能算出毫秒数，但 tsc --noEmit 会报 TS2362/TS2363
       （左/右操作数不是 number）。本文件被 tsconfig 收录，所以这里必须写全。 */
    if (Math.round((end.getTime() - start.getTime()) / 3600000) + 1 > MAX_SLOTS) {
      start = new Date(end.getTime() - (MAX_SLOTS - 1) * 3600000);
    }
    var vals = [], labels = [], gaps = 0;
    for (var t = start.getTime(); t <= end.getTime(); t += 3600000) {
      var k = fmtKey(new Date(t));
      if (Object.prototype.hasOwnProperty.call(map, k)) vals.push(map[k]);
      else { vals.push(null); gaps++; }   // 断档：不补 0
      labels.push(k);
    }
    var filled = vals.filter(function (v) { return v != null; }).length;
    return { vals: vals, labels: labels, filled: filled, gaps: gaps,
      hours: labels.length, last: pts[pts.length - 1].v, first: pts[0].v };
  }

  /* 存量趋势插槽。三种状态分清（同 qcSparkSlot）：
       点够 → 画线 + 说明；接口通但点不够 → 只给说明；完全没有 → 不占位。
     < 2 点时返回空串，卡片会挂上 is-nospark 垂直居中（沿用既有降级）。 */
  function qcStockSlot(id) {
    var s = qcStockSeries(id);
    /* 说明文字按指标取不同措辞：PMT 画的是「超期数」而不是总存量，
       用同一句「存量」会让人以为它等于卡片上那个大数字。
       ⚠️ 2026-09-28：kCap 已随图下方的说明行一起去掉（用户「其他备注都不要」），
       只剩 kTip 挂在 title 上 —— 所以这里不再取 kCap，不留无用的键。 */
    var kTip = id === 'pmt' ? 'qc.stock.tipPmt' : 'qc.stock.tip';
    if (!s) {
      /* 有数据但点不够：给一句说明，别让卡片空着像坏了；
         完全没有数据：不占位（此时卡片本来就没有这一行，挂说明反而是噪音）。 */
      var raw = state.qcHistory && state.qcHistory[id];
      if (raw && raw.length) {
        return '<span class="qc-spark-empty">' + esc(t('qc.stock.starving')) + '</span>';
      }
      return '';
    }
    /* ⚠️ 2026-09-28：与 qcSparkSlot 同步改为柱状（用户要求「曲线换成柱状」）。
       存量序列里的 null（没采到的那一小时）qcBarsSvg 同样不画柱子，
       于是断档处是一段**空缺**，与折线版的"断开"表达同一件事。 */
    var bars = qcBarsSvg(s.vals);
    if (!bars) return '<span class="qc-spark-empty">' + esc(t('qc.stock.starving')) + '</span>';
    var v = { n: s.hours };
    return '<span class="qc-spark-wrap" title="' + esc(tf(kTip, v)) + '">' + bars + '</span>';
  }

  /* 卡片趋势位的**唯一入口**（2026-09-25 加）：口径按指标定，卡片不判断。
       QC_TREND_METRICS（alarm/tt/wo/spms）→ 新增量；拿不到则退存量
       其余（cr/pmt）                       → 存量
     「先试新增量、再退存量」的兜底有意义：某指标 trend 接口临时挂掉时，
     只要快照还在，卡片仍有一张**真实的**图，而不是空一块。 */
  function qcTrendSlot(id) {
    if (DATA.QC_TREND_METRICS.indexOf(id) !== -1) {
      var inc = qcSparkSlot(id);
      if (inc) return inc;
    }
    return qcStockSlot(id);
  }
  /* 三种状态要分清，否则首屏三行「趋势积累中」看着像报错：
       有趋势且点够 → 画图 + 说明；接口通了但点不够 → 只给说明；无趋势 → 不占位。
     说明文字带「窗口 + 每格时长」：图是流量（新增量）、大数字是存量（积压），
     不说清单位就没法把两者对上。

     ⚠️ 2026-09-28：用户要求「当前的曲线换成柱状，数字不变」——
     所以这里把 qcSpark（折线）换成 qcBars（柱状）。**只换画法**，
     数据窗口、分桶、说明文字、三种状态的判定全部原样保留。 */
  function qcSparkSlot(id) {
    var s = qcTrendSeries(id), bars = qcBars(id);
    if (!bars) return s ? '<span class="qc-spark-empty">' + esc(t('qc.trend.starving')) + '</span>' : '';
    var v = { total: fmt(s.total), unit: t(s.grain === 'day' ? 'qc.trend.days' : 'qc.trend.hours'),
      n: s.days || s.labels.length };
    /* 只剩 tip 这一个键要取：说明行已去掉（见下），上面 v 里的 total/unit/n
       仍然有用 —— 它们填进 title 里那句完整口径。 */
    var tipKey = s.window === 'today' ? 'qc.trend.tipToday' : 'qc.trend.tip';
    /* ⚠️ 2026-09-28：图下方那行 .qc-spark-cap（「近 30 天新增 47 次（每格 1 天）」）
       已按要求去掉 —— 用户说「图表下面只保留」那六行文案、「其他备注都不要」。
       口径说明没有丢：它仍挂在**外层 .qc-spark-wrap 的 title 上**，
       hover 就能看到，与 kpi.sub 收进 .band-k 的 title 是同一套做法
       （界面上少一行，信息不消失）。 */
    return '<span class="qc-spark-wrap" title="' + esc(tf(tipKey, v)) + '">' + bars + '</span>';
  }

  function qcCardHtml(d) {
    var m = qcMetric(d.id);
    /* 失败分两种：整体取不到（全量都没回来）与单项失败（后端逐项容错）。
       两种都按「不可用」呈现，绝不能留上一次的旧数字冒充实时值。 */
    var failed = !!(m && m.error) || (!!state.qc.err && !state.qc.at);
    var errMsg = (m && m.error) || state.qc.err || '';
    var v = m && m.value != null ? m.value : null;
    /* 2026-09-25 删：原来是 `var big = QC_PRIMARY_ORDER.indexOf(d.id) !== -1`，
       只用来决定「这张卡给不给走势位」（主卡必给，次卡要判断）。改成统一走
       qcTrendSlot 后就没有调用点了 —— 直接删掉，不留一个无用的变量。 */
    var def = t(DATA.QC_SUB_KEY[d.id]) || (state.lang === 'en' ? d.subEn : d.subZh);
    /* ⚠️ 2026-09-28（用户要求「图表下面只保留：alarm → 75 Cells/ Sites Outage，
       其余五项各自改成 Ongoing TTs / Ongoing WOs / Unclosed CRs / Unclosed PMTs /
       Unclosed SPMS，其他备注都不要」）：
       这里原来对 pmt / spms 两项做了**动态改写**（pmt 写「超期 472」、
       spms 写「入库 32 · 出库 62」），本次一并去掉 —— 用户点名只要那六行文案，
       动态备注属于"其他备注"。六张卡现在都直接取 DATA.QC_SUB_KEY 的字典值。
       ⚠️ 2026-10-08 取消的例外：alarm 原先还要在前面拼上断站站点数
       （qc.sites 已改成 'Cells/ Sites Outage' 纯文案，数字由这里给），否则
       「75 Cells/ Sites Outage」这个用户点名的形态就少了数字。现按用户要求
       只留纯文案 —— 数字没有丢，卡片正中那个大数字（.qc-num）本来就是同一个断站数。
       msg.overdue / msg.tables 仍在接口里返回，只是本页不再渲染
       （要恢复见 olbr.js.bak_20260928_柱状图与顶栏调整前）。 */
    var sub;
    if (failed) sub = t('qc.err') + (errMsg ? ': ' + errMsg : '');
    else sub = def;
    /* tooltip 只留口径与点击提示。
       v1 改：阈值那两行**去掉了** —— 等级分档整个不显示了，再把
       「关注 ≥ 30 / 严重 ≥ 80」挂在悬浮里，等于让用户按一个屏幕上不存在的规则去读数字。
       要看阈值请回 /olbrportal/（那边卡片带分档徽章，两者配套）。 */
    var tips = [def];
    if (!failed) tips.push(t('qc.drill'));
    /* 走势插槽**先生成再判断**：qcTrendSlot 对一个"本该有走势"的指标也可能
       返回空串（趋势接口没数据），所以不能只看 d.id 在不在 DATA.QC_TREND_METRICS 里。
       真正空的时候才挂 is-nospark，让 CSS 把内容垂直居中 ——
       否则这张卡会比同排带走势的卡矮 50px 上下，差额全堆在底部。

       2026-09-25 改：由 `(big || 在 QC_TREND_METRICS)` 改为统一走 qcTrendSlot()。
       改版前 CRs / PMT 直接不生成插槽 —— 它们的新增量画不出趋势（源表时间列
       近 30 天无数据）。现在它们走**存量快照**，六张卡就都有走势了。
       口径判断收进 qcTrendSlot 一处，卡片这边不再自己算。 */
    var spark = qcTrendSlot(d.id);
    /* 数字没取到一律 —，绝不显示 0：统计里的 0 是「真的一个都没有」，
       与「没取到」必须能分辨，否则会被误读成「已清空」。 */
    return '<button type="button" class="qc-card' + (failed ? ' is-failed' : '') +
      (spark ? '' : ' is-nospark') +
      '" data-qc="' + esc(d.id) + '" title="' + esc(tips.join('\n')) + '">' +
      /* 2026-09-25 改：卡名前的图标（.qc-ico）去掉。它只是装饰，卡名本身已经说明
         这张卡是什么，而图标占掉的 26px 让六张卡并排时卡名更容易被省略号截断。
         注意**只去掉告警带这六张卡的**：下面的 CXO 富卡片（.qc-ttl 那一行）仍保留图标，
         两处不是同一条规则，别顺手一起改。 */
      '<span class="qc-hd">' +
        '<span class="qc-name">' + esc(state.lang === 'en' ? d.en : d.zh) + '</span></span>' +
      /* v1 改：这里原来是等级徽章 .qc-lvchip（正常 / 关注 / 严重 / 不可用）。
         按要求去掉「Critical 等信息」，整块不再渲染 —— 不用 display:none 隐藏，
         隐藏会留出一行空白占位。伴随的 .qc-lv-* 配色类也一并去掉，卡片退回单一品牌色。 */
      '<span class="qc-numrow"><span class="qc-num' + (v == null ? ' is-na' : '') + '">' +
        esc(v == null ? '—' : fmt(v)) + '</span></span>' +
      spark +
      '<span class="qc-sub" title="' + esc(sub) + '">' + esc(sub) + '</span>' +
      /* ⚠️ 2026-09-28 删（用户要求「图表下面只保留」那六行文案，「其他备注都不要」）：
         这里原本还有一行 .qc-age「数据 08:39:34（刚刚）」。
         它属于"其他备注"，与趋势图下方的「近 30 天新增 …」说明一起被去掉。
         at 变量（qcMetricAt）随之失去唯一调用点，一并删掉；
         ⚠️ 但**不能**为此删 qcMetricAt / qcClock / qcAgo ——
         它们仍被标题行的 qc.live 心跳（renderBand）与下钻弹窗使用。
         要恢复这一行见 olbr.js.bak_20260928_柱状图与顶栏调整前。 */
      '</button>';
  }

  function renderBand() {
    var box = $('#band'), q = state.qc;
    var has = q.m && Object.keys(q.m).length;
    if (q.loading && !has) {
      box.innerHTML = '<div class="band-h"><span class="sk" style="width:84px;height:84px;border-radius:50%"></span>' +
        '<div class="band-txt" style="flex:1"><span class="sk" style="width:52%"></span>' +
        '<span class="sk s" style="width:72%"></span></div></div>' +
        '<div class="qc-grid">' + (D.qc || []).map(function () {
          return '<div class="qc-card"><span class="sk" style="width:56%"></span>' +
            '<span class="sk v"></span><span class="sk s"></span></div>';
        }).join('') + '</div>';
      return;
    }
    if (!has && q.err) {
      box.innerHTML = '<div class="band-h"><div class="band-txt"><div class="band-k">' +
        esc(t('qc.title')) + '</div><p class="band-n" style="color:var(--crit)">' +
        esc(t('qc.err') + (q.err ? ': ' + q.err : '')) + '</p></div>' +
        '<button type="button" class="gb" data-act="qc-reload">' + ic('refresh') +
        esc(t('qc.retry')) + '</button></div>';
      return;
    }
    var byId = {};
    (D.qc || []).forEach(function (d) { byId[d.id] = d; });
    var cards = DATA.QC_PRIMARY_ORDER.concat(DATA.QC_SECONDARY_ORDER).map(function (id) {
      return byId[id] ? qcCardHtml(byId[id]) : '';
    }).join('');
    /* 2026-09-25 改：标题行**整块**去掉「30 天达标率」—— 圆环 + 标题 + 「通过 / 分母」
       连同它派生的 sla 口径全部删除（用户要求：去掉 30-day compliance 和圆环图）。
       同时删掉的还有三处只为它存在的东西，避免留下点不动的死入口：
         · qc.slaTip / qc.slaDrillTip / qc.slaPending 三条文案（已从 olbr-data.js 移除）
         · .ring / .ring-btn / .band-pend 样式（已从 olbr.css 移除）
         · 环上那条 <button data-qc="sla"> 下钻入口
       后端 /api/portal-qc/detail?metric=sla 与 qcMetric('sla') 读到的数据**没有删** ——
       接口是两门户共用的契约，本页只是不再渲染它（要恢复见
       assets/olbr.js.bak_20260925_去30天达标率与ALARM图标前）。

       留下的标题行现在只剩「心跳 + 下次刷新」与「刷新」两件东西。
       它们原来靠 .band-txt 的 flex:1 1 200px 顶到右侧，那块一走就没有东西撑开间距了，
       所以这里补一个 .band-sp（flex:1）占位，否则心跳会贴着刷新按钮挤成一团。 */
    var stamp = qcLatestStamp();
    /* 心跳点：取不到数据时变红且不脉冲 —— 绿色脉冲 = 这块面板确实在自动刷新。
       秒必须精确到秒：只到分钟时，轮询 + 后端 60s 缓存叠起来会出现「一分钟没变」的错觉。 */
    var live = '<span class="qc-live" title="' +
      esc(tf('qc.cadenceTip', { a: state.qcAlarmAt ? qcClock(state.qcAlarmAt) : '—',
        f: state.qcFullAt ? qcClock(state.qcFullAt) : '—' })) + '">' +
      '<span class="' + (q.err && !has ? 'qc-dot qc-dot-bad' : 'qc-dot') + '" aria-hidden="true"></span>' +
      '<span class="qc-when">' + esc(stamp ? t('qc.updated') + ' ' + qcClock(stamp) : t('qc.loading')) + '</span>' +
      '<span class="qc-sep">·</span><span id="qcNextIn">' + esc(tf('qc.next', { t: qcCountdown() })) + '</span></span>';
    /* 2026-09-28（用户要求「时间范围根据统计数字的数据所包含的时间范围显示」）：
       标题下方补一行数据区间，取**真实数据**的首末格（qcDataRange），不是"近 30 天"这种
       按请求参数写的固定话术 —— 实测 alarm 是当天 00:00→16:00 的 14 格小时轴、
       tt 是 08-30→09-28 的 16 格天轴，两者区间完全不同，写死"近 30 天"至少对 alarm 是错的。
       取不到区间时**整行不渲染**（不显示 "— ~ —"）：这行是"补充说明"，
       没有数据支撑时留白比给一个空壳更诚实，与卡片数字缺值显示 — 是两回事。

       ⚠️ 2026-09-28 同日三改（用户要求「改成点击切换」）：
       触发方式由「悬停 / 聚焦自动展开」改为**点击标题切换** ——
       悬停在触屏上没有真正的 hover（点一下会"粘住"），且鼠标扫过时一闪而过，
       用户还没来得及读就消失了。点击是显式的：要么开着，要么关着。
       展开状态记在 .band-txt 的 .is-open 类上（不是全局 state）：
       它是**这一块**标题行的局部 UI 状态，与语言/主题那种全局状态不同源。
       重绘时由 renderBand 重新渲染，展开态自然复位为收起 —— 与
       v6 的 subOpen 不同（那个要跨重绘保留，因为它是筛选条件）。
       无障碍：标题渲染成 <button aria-expanded>，键盘 Enter/Space 切换、
       Esc 收起、点空白处收起，见 wireRangeToggle。 */
    var range = qcDataRange();
    var rangeEl = range ? '<p class="band-range" id="qcRangePop">' +
      '<i class="ph ph-chart-bar" aria-hidden="true"></i>' +
      '<span>' + esc(tf('qc.range', { a: range[0], b: range[1] })) + '</span></p>' : '';
    /* 环（.ring / .ring-btn）已随「30 天达标率」一起删除，见上面那段说明。 */
    box.innerHTML =
      '<div class="band-h">' +
        /* 标题与区间竖着叠成一块，再与右侧的心跳/刷新同处一行 ——
           若把 rangeEl 直接放在 .band-h 下，它会被 flex 排到标题**右边**，
           在宽屏上与心跳挤在一起（两点之间隔着 900px 空白，读起来像两块无关信息）。
           套一层 .band-txt（CXO 那边同款容器）让它与标题成为同一个文本块。 */
        '<div class="band-txt">' +
          /* 有区间时才把标题做成按钮（没区间就没有可切换的东西，
             做成按钮会让用户点了没反应 —— 比不给按钮更糟）。
             aria-controls 指向气泡 id，读屏会念出两者关系。 */
          (range
            ? '<button type="button" class="band-k band-range-btn" ' +
              'aria-expanded="false" aria-controls="qcRangePop" ' +
              'title="' + esc(t('qc.rangeHint')) + '">' + esc(t('qc.title')) + '</button>'
            : '<div class="band-k">' + esc(t('qc.title')) + '</div>') +
          rangeEl +
        '</div>' +
        '<span class="band-sp" aria-hidden="true"></span>' +
        live +
        '<button type="button" class="gb" data-act="qc-reload" title="' + esc(t('qc.reload')) + '">' +
          ic('refresh') + esc(t('qc.reload')) + '</button>' +
      '</div><div class="qc-grid">' + cards + '</div>';
    wireRangeToggle(box);
  }
  /* 数据区间气泡的点击切换（2026-09-28 加，用户要求「改成点击切换」）。
     为什么不用事件委托挂在 document 上：这块面板每次 renderBand 都会整体重绘，
     委托虽然能活下来，但"点外面收起"需要知道当前展开了哪一个，
     还得额外维护一份全局状态；直接绑在当前这棵 DOM 上，重绘时旧的自动回收，
     状态天然跟着节点走（节点没了，状态也就没了），不会泄漏。
     收起的三条路径都给了：再点一次标题、按 Esc、点气泡外的任意位置。
     最后一条对"点击切换"是必需的 —— 只给"再点一次"会让用户以为关不掉。 */
  function wireRangeToggle(box) {
    var wrap = box.querySelector('.band-txt');
    if (!wrap) return;
    var btn = wrap.querySelector('.band-range-btn');
    if (!btn) return;   /* 没有区间数据时标题不是按钮，无需接线 */
    function setOpen(on) {
      wrap.classList.toggle('is-open', on);
      btn.setAttribute('aria-expanded', on ? 'true' : 'false');
    }
    btn.addEventListener('click', function () {
      setOpen(!wrap.classList.contains('is-open'));
    });
    /* Esc 收起并把焦点还给按钮：键盘用户按 Esc 后如果焦点留在空气里，
       下一次 Tab 会从文档开头重来，等于把用户弹回页首。 */
    wrap.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && wrap.classList.contains('is-open')) {
        setOpen(false);
        btn.focus();
      }
    });
    /* 点别处收起。用 pointerdown 而不是 click：click 要等鼠标抬起，
       用户在别处按下、拖动、再抬起时 click 可能落在别的元素上而收不起来。
       用捕获阶段，保证在别的处理器 stopPropagation 之前就执行到。 */
    document.addEventListener('pointerdown', function onDoc(e) {
      /* 节点已被下次重绘换掉 -> 自己摘掉监听，避免越积越多。
         这是替代"重绘前解绑"的低成本写法：不需要记住解绑时机。 */
      if (!document.contains(wrap)) { document.removeEventListener('pointerdown', onDoc, true); return; }
      if (!wrap.contains(e.target)) setOpen(false);
    }, true);
  }
  /* 统计数据覆盖的真实时间区间（2026-09-28 加）。
     从**已经取回来的**趋势序列里读，不额外发请求：
     每一格的价值都来自 state，另发一次接口可能出现「标题说 A 区间、柱子画 B 区间」。
     为什么用趋势序列而不是 summary 的 generated_at：
       generated_at 是"这次跑统计的时刻"（今天 16:38 这种单点），
       而用户要的是"统计数字所包含的时间范围"——那是**一段**区间。
     口径：取所有指标的 labels（已由 qcTrendSeries / qcStockSeries 对齐到连续轴）
     里最早与最晚的一格；小时轴显示到 "HH:00"，天轴只显示到日期。
     返回 null 表示还没有任何序列可读，调用方据此不渲染这一行。 */
  function qcDataRange() {
    var first = null, last = null;
    function eat(labels) {
      if (!labels || !labels.length) return;
      var a = labels[0], b = labels[labels.length - 1];
      if (!first || a < first) first = a;
      if (!last || b > last) last = b;
    }
    (DATA.QC_TREND_METRICS || []).forEach(function (id) {
      var t = qcTrendSeries(id);
      if (t) eat(t.labels);
    });
    ['cr', 'pmt'].forEach(function (id) {
      var s = qcStockSeries(id);
      if (s) eat(s.labels);
    });
    if (!first || !last) return null;
    /* 小时格子 "2026-09-28 16:00" 原样；天格子 "2026-09-28" 原样。
       两端直接用源格式，不做二次格式化 —— 格式化只会在两端之间引入不一致
       （比如把天轴补成 00:00，看起来像"精确到小时"）。 */
    return [first, last];
  }

  /* ==================================================================== v1 ==
     CXO Daily Dashboard 指标带（2026-09-24 加，同日改成富卡片）
     ----------------------------------------------------------------------------
     当前形态（按用户 2026-09-24 的要求）：**六张卡一行**
       前三张「富卡片」：Total Traffic / Active Users /
                         Valid Throughput of Video Download
                         —— 大数字 + 单位、Latest/As of 行、WoW/MoM 徽章、
                            30 点迷你走势、Max/Avg/Min 页脚
       后三张「简卡片」：2G / 3G / 4G 当月可用率（沿用 .qc-card 原样，
                          用户明确说这三张不动）
     六张一行，所以 4 张富卡片的版本（含 video_tb 视频流量）已被用户否掉；
     本带因此用**基类 .qc-grid**（6 列），不再需要单独的列数覆盖。

     ── 数据源：/api/olib-soc-dashboard/overview?days=90 ──────────────────────
     富卡片全部走这一路。它是 my_app `?page=vmaxCxoDashboard_90Days` 那个 90 天
     经营看板的只读接口（源库 data/olib_soc_report/olib_soc_report.sqlite3），
     一张卡就带齐了本页要的一切：
       latest{date,value} / avg / n / max{date,value} / min{date,value}
       wow_pct + wow_base / mom_pct + mom_base / spark[30] / better / note

     ⚠️ 为什么不再用 /api/vmax-cxo-daily/grid（2026-09-24 移除）
        那个接口只保留 8 天（响应里 retention_days=8），给不出 90 天极值和月同比，
        做不出这张富卡片。两者**在重叠区间上是同一个指标**（实测 2026-09-23：
        vmax 268.15 TB vs olib 268.17 TB），所以换成 olib 不是换口径。
        差别只在「哪一天」：vmax 给的是**当日进行中**（partial，下午只有几个小时），
        olib 给的是**昨日完整值** —— 后者才能和 WoW/MoM/极值自洽。
        用户已确认接受「不再显示今天跑到多少」。
        整条 vmax 通路（含 KPI_VMAX_IDS / kpiConvert / kpiSpec / kpiAvg /
        kpiToday / kpiDays）已随之删除，不留兼容层；要恢复可参考快照
        assets/olbr.js_bak_20260924_Traffic改TB前。

     ── 展示口径覆盖（unit / digits / div）────────────────────────────────────
     接口字典（olib_soc_kpi_store.METRICS）给的单位是 GB / K / kbps / TB。
     本页对其中两个做**渲染层**换算，理由与 2/3/4G 那三张把 0~1 乘 100 一致：
     改后端会串到别处（同一接口还给 my_app 自己的看板用）：
       · traffic_gb    源给 GB，用户要求按 TB 显示 → ÷1024（1 TB = 1024 GB，存储口径）
       · video_thr_kbps 源给 kbps（实测 14391），按 Mbps 显示 → ÷1000，读起来不至于挤
     另两个（K / TB）照抄接口。div 只影响显示，不影响 tooltip 里的口径说明。 */
  function olibCard(id) {
    var cs = (state.kpi.olib && state.kpi.olib.cards) || [];
    for (var i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i];
    return null;
  }
  /* 迷你走势：纯 SVG，不额外起 ECharts 实例（一张卡一个实例，四张卡就是四个
     常驻 canvas，代价远大于这条 30 点折线）。
     **刻意复用 QC 卡那条走势的既有类名**：`.qc-spark` / `.sp-area` / `.sp-line`
     已经定义好了尺寸与主题色（面积取 --qc-accent-soft、线取 --qc-accent，
     而这两个变量就定义在 .qc-card 上，富卡片本身也是 .qc-card，直接继承）。
     另起一套 .qc-rspark 只会得到两份长得一样、却要各自维护的走势样式。
     结构也要跟着既有约定走：外层是 <span class="qc-spark">，svg 在里层。 */
  function kpiSpark(values) {
    var pts = (values || []).filter(function (v) {
      return v != null && isFinite(Number(v));
    }).map(Number);
    if (pts.length < 2) return '';
    var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    var span = (max - min) || 1, n = pts.length, step = 100 / (n - 1);
    var line = pts.map(function (v, i) {
      /* y 压进 2~24：贴边会被卡片的 overflow:hidden 切掉半个线宽 */
      return (i * step).toFixed(2) + ',' + (24 - ((v - min) / span * 22)).toFixed(2);
    }).join(' ');
    return '<span class="qc-spark" aria-hidden="true">' +
      '<svg viewBox="0 0 100 26" preserveAspectRatio="none">' +
        '<polygon class="sp-area" points="0,26 ' + line + ' 100,26"/>' +
        '<polyline class="sp-line" points="' + line + '"/></svg></span>';
  }
  /* WoW / MoM 徽章配色：better 由接口给（都是 up=越大越好），不在这里另写一份判断。
     涨跌 <0.05% 视为持平 —— 否则 0.01% 也会被涂成红/绿，读起来像有事发生。 */
  function kpiChip(label, pctVal, better) {
    var cls = 'neu', txt = '—';
    if (pctVal != null && isFinite(Number(pctVal))) {
      var v = Number(pctVal);
      txt = (v > 0 ? '+' : '') + v.toFixed(1) + '%';
      if (better !== 'flat' && Math.abs(v) >= 0.05) {
        var good = (better === 'down') ? (v < 0) : (v > 0);
        cls = good ? 'up' : 'down';
      }
    }
    return '<span class="qc-chip ' + cls + '">' + esc(label) + ' ' + esc(txt) + '</span>';
  }
  /* 四张富卡片之一。c = olib cards[] 里的那张，spec = DATA.KPI_RICH 里的展示口径。
     缺数据时**整张卡仍然画出来**（页脚/走势留空、数字显示 —），
     而不是把卡片抽掉 —— 抽掉会让上面那一排从 4 张变 3 张，
     看起来像"这个指标被下架了"，而实际只是今天没取到数。 */
  function kpiRichHtml(spec, c) {
    var digits = spec.digits;
    var asOf = (state.kpi.olib && state.kpi.olib.as_of) || '';
    var val = function (v, on) {
      if (!on || v == null || v === '' || isNaN(Number(v))) return '—';
      return kpiNum(Number(v) / spec.div, digits);
    };
    var dateOf = function (o) { return (o && o.date) ? o.date : '—'; };
    var latest = c && c.latest ? c.latest : null;
    var max = c && c.max ? c.max : null;
    var min = c && c.min ? c.min : null;
    /* 门户显示名：spec.label_en / label_zh（若有）最优先 —— 用于在**不改后端
       共享口径**的前提下，把过长的接口标题在门户换成短名（见 KPI_RICH 第三张
       的 label_en 及注释）；没有覆盖时仍用接口返回的 title / title_en。 */
    var name = c
      ? ((state.lang === 'en'
          ? (spec.label_en || c.title_en || c.title)
          : (spec.label_zh || c.title || c.title_en)) || spec.id)
      : (state.lang === 'en' ? (spec.label_en || spec.en)
                             : (spec.label_zh || spec.zh));
    var better = (c && c.better) || 'up';
    /* tooltip 说清三件事：这个指标是什么、大数字是哪天的、同比各自对比哪一天。
       只写"来源：某某看板"在这里不够用 —— 同屏三个数字都不是当天的。
       所有带标点的句子都走 tf()：标点必须跟着语言走（见字典里的说明）。 */
    var tip = tf('kpi.tipName', { n: name, u: spec.unit });
    if (c && c.note) tip += '\n' + (state.lang === 'en' ? (c.note_en || c.note) : c.note);
    tip += '\n' + t('kpi.tipRich');
    if (latest) tip += '\n' + tf('kpi.tipLatest', { d: latest.date });
    /* WoW / MoM 各自写明"跟哪一天比、那天的值是多少" ——
       只给一个百分比，读的人无法判断是不是跟一个异常日比出来的。 */
    if (c && c.wow_base) tip += '\n' + tf('kpi.tipBase', {
      k: t('kpi.wow'), d: c.wow_base.date, v: val(c.wow_base.value, true), u: spec.unit });
    if (c && c.mom_base) tip += '\n' + tf('kpi.tipBase', {
      k: t('kpi.mom'), d: c.mom_base.date, v: val(c.mom_base.value, true), u: spec.unit });
    var na = !latest || latest.value == null || isNaN(Number(latest.value));
    /* ---- 整卡可点跳转（2026-09-29 加，用户要求）--------------------------------
       点这张卡打开它**真正的那份完整看板**。目标页来自 spec.page
       （见 olbr-data.js 的 KPI_RICH），不是写在这里的常量 —— 同 QC_BOARD_PAGE
       那条约束：页面归属属于数据，不属于渲染。

       为什么用 <a> 包住整张卡，而不是给 <div> 挂 click 监听：
         · <a href> 天然带「中键新标签页 / 右键复制链接 / 悬停看状态栏地址 / 键盘
           Enter 打开」这一整套行为，用 div + onclick 这些全要自己补一遍，
           补不全就是「键盘用户点不动」；
         · 语义正确：读屏会念成链接，明确告诉用户"这里能跳走"。
       卡内**没有其它可交互元素**（「重试」按钮在带标题行 .band-h 里，不在卡内），
       所以不存在 a 套 button 的非法嵌套。

       为什么加 target="_blank"：本页是**门户**，跳走等于把用户的目录弄丢了；
       且 my_app 那份看板是 90 天的大盘，用户看完多半还要回门户点别的。
       配 rel="noopener"（防 tabnabbing，与 #qcOpenBoard 既有写法一致）。

       ⚠️ 相对路径 /myapp/ 而**不是** http://localhost/myapp/：
       门户与 my_app 经同一个 nginx，同源相对路径在换 IP / 换域名时不用改代码；
       写死 localhost 的话，用户用 IP 访问门户时这个链接会指向**访问者自己那台机器**。
       与 olbr.js 里 mapItems()/applyDrillTitle 的既有约定一致。
       ------------------------------------------------------------------------ */
    var open = spec.page
      ? '<a class="qc-card qc-card--rich qc-card--open' + (na ? ' is-na' : '') + '" href="' +
        esc('/myapp/?page=' + encodeURIComponent(spec.page) + langQs()) + '" target="_blank" ' +
        'rel="noopener nofollow" title="' +
        esc(tf('kpi.openTip', { n: name, b: t('kpi.boardRich') }) + '\n\n' + tip) + '">'
      : '<div class="qc-card qc-card--rich' + (na ? ' is-na' : '') + '" title="' + esc(tip) + '">';
    var close = spec.page ? '</a>' : '</div>';
    return open +
      /* 卡名加 title：英文名较长（如 "Valid Throughput of Video Download"），
         而 .qc-ttl b 是 nowrap + ellipsis（窄卡必然截断成 "Valid Throughput o…"）。
         悬停在**卡名本身**上显示全文，补足被省略号切掉的部分。
         ⚠️ 这里的 title 覆盖外层卡片已有的提示 —— 那是刻意的：
            鼠标落在卡名上时，用户想看的正是"这个被截断的标题全称"，
            而不是整卡的说明；移出卡名、落到卡面别处时，外层提示照常。
         同理见下方 kpiCardHtml 的可用率卡。 */
      '<div class="qc-ttl"><b title="' + esc(name) + '">' + esc(name) + '</b><i>' + esc(spec.unit) + '</i></div>' +
      '<div class="qc-val"><span>' + esc(val(latest && latest.value, true)) + '</span>' +
        '<em>' + esc(spec.unit) + '</em></div>' +
      '<div class="qc-asof">' + esc(tf('kpi.asofFmt', { d: dateOf(latest), a: asOf || '—' })) + '</div>' +
      '<div class="qc-chips">' +
        kpiChip(t('kpi.wow'), c && c.wow_pct, better) +
        kpiChip(t('kpi.mom'), c && c.mom_pct, better) +
      '</div>' +
      kpiSpark(c && c.spark) +
      '<div class="qc-ext">' +
        '<div class="hi"><span>' + esc(t('kpi.max')) + '</span><b>' +
          esc(val(max && max.value, true)) + '</b><span>' + esc(dateOf(max)) + '</span></div>' +
        '<div><span>' + esc(t('kpi.avg')) + '</span><b>' +
          esc(val(c && c.avg, true)) + '</b><span>' +
          esc(t('kpi.days').replace('{n}', String((c && c.n) != null ? c.n : '—'))) + '</span></div>' +
        '<div class="lo"><span>' + esc(t('kpi.min')) + '</span><b>' +
          esc(val(min && min.value, true)) + '</b><span>' + esc(dateOf(min)) + '</span></div>' +
      '</div>' + close;
  }
  /* 2G/3G/4G 可用率「富卡片」（2026-10-01 加，用户要求 Network Status Overview
     右边三张与左边三张在格式、内容上尽量对齐）。
     DOM 结构与 kpiRichHtml **逐行相同**：.qc-ttl / .qc-val / .qc-asof /
     .qc-chips / .qc-spark / .qc-ext(Max/Avg/Min)，所以外层也挂 qc-card--rich。
     数据全部来自可用率 row（month_avg / latest / series / latest_date）与阈值，
     **不编造**：可用率接口没有 WoW / MoM，chips 位置改放两枚真实徽章——
     「目标阈值」与「距阈值差距」（原底部的合规信息上移到此，不丢失）；
     底部三格改为与富卡片一致的 Max / Avg / Min，由 series 逐日值现算。 */
  function availRichHtml(spec, row) {
    var pct = function (x) {
      return (x == null || isNaN(Number(x))) ? null : Number(x) * 100;
    };
    /* 阈值已是百分数（99.65），不走 pct()（同 renderKpi 旧逻辑的警告） */
    var thr = (state.kpi.avail && state.kpi.avail.threshold_pct != null)
      ? Number(state.kpi.avail.threshold_pct) : null;
    if (thr != null && isNaN(thr)) thr = null;

    /* series（0~1 小数）清洗成百分数日点 {d, v}；先挡 null/''，Number(null)===0
       会被当成「那天可用率 0%」（同 availSpark 的既有处理）。 */
    var pts = ((row && row.series) || []).map(function (p) {
      if (!p || p.v == null || p.v === '') return null;
      var n = Number(p.v) * 100;
      return isFinite(n) ? { d: p.d, v: n } : null;
    }).filter(Boolean);

    var monthV = pct(row && row.month_avg);
    var lastV = pct(row && row.latest);
    var na = monthV == null || isNaN(monthV);

    /* 30 天日序列现算 Max / Avg / Min。
       ⚠️ 必须显式标注类型：tsc 的控制流分析看到 `var maxP = null`、
       而赋值只发生在下面的回调里（它不认为回调一定会执行），
       于是把 maxP 窄化成 never，用到 maxP.v / maxP.d 时就报
       "Property 'v' does not exist on type 'never'"。
       这不是运行时错误（守卫写对了），纯粹是类型标注缺失。 */
    /** @type {{d: string, v: number}|null} */
    var maxP = null;
    /** @type {{d: string, v: number}|null} */
    var minP = null;
    var sum = 0, cnt = 0;
    pts.forEach(function (p) {
      if (maxP === null || p.v > maxP.v) maxP = p;
      if (minP === null || p.v < minP.v) minP = p;
      sum += p.v; cnt++;
    });
    var avgV = cnt ? sum / cnt : null;

    var name = spec.key + ' ' + t('kpi.avail');
    var gap = (lastV != null && thr != null) ? lastV - thr : null;
    var gapCls = gap == null ? 'neu' : (gap < 0 ? 'down' : 'up');

    var tip = t('kpi.tipAvail').replace('{board}', 'Daily_Availability_KPI') +
      '\n' + t('kpi.tipAvailFoot');
    var open = spec.page
      ? '<a class="qc-card qc-card--rich qc-card--open' + (na ? ' is-na' : '') + '" href="' +
        esc('/myapp/?page=' + encodeURIComponent(spec.page) + langQs()) + '" target="_blank" ' +
        'rel="noopener nofollow" title="' +
        esc(tf('kpi.openTip', { n: name, b: t('kpi.boardAvail') }) + '\n\n' + tip) + '">'
      : '<div class="qc-card qc-card--rich' + (na ? ' is-na' : '') + '" title="' + esc(tip) + '">';
    var close = spec.page ? '</a>' : '</div>';

    /* chips：目标阈值（中性）+ 距阈值差距（达标绿/未达标红），复用 .qc-chip 配色，
       替代可用率缺失的 WoW/MoM，两枚均为真实数据。 */
    var thrChip = '<span class="qc-chip neu">' + esc(t('kpi.thr')) + ' ' +
      (thr == null ? '—' : kpiNum(thr, 2)) + '%</span>';
    var gapChip = '<span class="qc-chip ' + gapCls + '">' + esc(t('kpi.gapThr')) + ' ' +
      (gap == null ? '—' : (gap > 0 ? '+' : '') + gap.toFixed(2)) + 'pp</span>';

    return open +
      '<div class="qc-ttl"><b title="' + esc(name) + '">' + esc(name) + '</b><i>%</i></div>' +
      '<div class="qc-val"><span>' + (na ? '—' : kpiNum(monthV, 2)) + '</span><em>%</em></div>' +
      '<div class="qc-asof">' +
        esc(tf('kpi.availAsof', { d: (row && row.latest_date) || '—' })) + '</div>' +
      '<div class="qc-chips">' + thrChip + gapChip + '</div>' +
      kpiSpark(pts.map(function (p) { return p.v; })) +
      '<div class="qc-ext">' +
        '<div class="hi"><span>' + esc(t('kpi.max')) + '</span><b>' +
          (maxP ? kpiNum(maxP.v, 2) : '—') + '</b><span>' + (maxP ? maxP.d : '—') + '</span></div>' +
        '<div><span>' + esc(t('kpi.avg')) + '</span><b>' +
          (avgV == null ? '—' : kpiNum(avgV, 2)) + '</b><span>' +
          esc(t('kpi.days').replace('{n}', String(cnt || '—'))) + '</span></div>' +
        '<div class="lo"><span>' + esc(t('kpi.min')) + '</span><b>' +
          (minP ? kpiNum(minP.v, 2) : '—') + '</b><span>' + (minP ? minP.d : '—') + '</span></div>' +
      '</div>' + close;
  }
  /* 按接口自己给的 digits 格式化，绝不 toFixed(2) 一把抓：
     Active User 是 (K) 两位小数、可用率是百分数两位小数，混用会让
     0.98 这种可用率显示成 98.00% 或者反过来。 */
  function kpiNum(v, digits) {
    if (v == null || v === '' || isNaN(Number(v))) return '—';
    var n = Number(v), d = digits == null ? 2 : digits;
    return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function kpiCardHtml(o) {
    /* o = { name, unit, value:'<已格式化或 —>', na:bool, sub, tip, age, href,
             foot:[{label, num, foot, cls}] }
       ⚠️ 2026-09-28：**没有 icon 字段了**（用户要求「2G/3G/4G Availability 卡片前面的
       图标删除，不要图标，跟其他卡片保持一致」）。同一排的富卡片（kpiRichHtml）
       标题行本来就只有一个名字、没有图标，只有这三张可用率卡带图标 ——
       六张并排时那三张的卡名被图标挤右 26px，与左邻的标题起点对不齐。
       所以连同 .qc-ico 的渲染一起去掉，而不是给富卡片也补图标
       （那会改到用户没有要求的部分）。
       foot 是本卡底部的三段页脚，与富卡片的 .qc-ext 共用同一套样式与结构，
       这样同一排 6 张卡的页脚在同一水平线上、字号字重也一致。
       只有"内容天然比邻居矮"的卡才需要它（可用率卡）；没有 foot 的卡
       不会渲染 .qc-ext，也不会带上 has-foot（避免多一个空盒子）。

       ⚠️ 2026-09-29 加 href（整卡可点，用户要求「2G/3G/4G Availability 卡片
       点击跳转到 /myapp/?page=avail_ms」）。
       这里是**可选参数**而不是写死跳转，因为本函数是共用实现：
       将来任何不带 href 的卡（例如别处复用它做一张纯展示卡）
       都会照旧渲染成不可点的 <div>，不会莫名其妙变成链接。
       有 href 时整张卡渲染成 <a>，理由与 kpiRichHtml 那处完全一致
       （中键新标签 / 右键复制链接 / 键盘 Enter / 读屏念成链接，
       这些用 div + onclick 都要自己补，补不全就是键盘用户点不动）。
       卡内**没有其它可交互元素**，不存在 a 套 button 的非法嵌套。 */
    var foot = '';
    if (o.foot && o.foot.length) {
      foot = '<div class="qc-ext">' + o.foot.map(function (s) {
        return '<div' + (s.cls ? ' class="' + esc(s.cls) + '"' : '') + '>' +
          '<span>' + esc(s.label) + '</span><b>' + esc(s.num) + '</b>' +
          '<span>' + esc(s.foot == null ? '' : s.foot) + '</span></div>';
      }).join('') + '</div>';
    }
    /* 可点时把「去哪儿」写进 title 的第一句，与富卡片同一套写法：
       原来那句 o.tip（口径说明）整段接在后面，不丢任何一行。 */
    var tip = o.tip || '';
    if (o.href) {
      tip = tf('kpi.openTip', { n: o.name, b: t('kpi.boardAvail') }) + '\n\n' + tip;
    }
    var open = o.href
      ? '<a class="qc-card qc-card--open' + (foot ? ' has-foot' : '') +
        '" href="' + esc(o.href) + '" target="_blank" rel="noopener nofollow" ' +
        'title="' + esc(tip) + '">'
      : '<div class="qc-card' + (foot ? ' has-foot' : '') + '" title="' + esc(tip) + '">';
    return open +
      /* 2026-09-28：这一行原本是「.qc-ico 图标 + .qc-name」，图标已按要求去掉，
         结构退回与告警带六张卡同款的「只有卡名」（qcCardHtml 那边同样只输出 .qc-name）。
         .qc-hd 这层仍然保留：它是卡内唯一撑满整宽的行，
         .qc-name 的单行省略依赖它给的 min-width:0。 */
      '<span class="qc-hd">' +
        /* 同 kpiRichHtml 的 .qc-ttl b：.qc-name 也是 nowrap+ellipsis，
           卡名过长会被截断，故补 title 显示全文。 */
        '<span class="qc-name" title="' + esc(o.name) + '">' + esc(o.name) + '</span></span>' +
      '<span class="qc-numrow"><span class="qc-num' + (o.na ? ' is-na' : '') + '">' +
        esc(o.value) + (o.unit ? '<span class="qc-unit"> ' + esc(o.unit) + '</span>' : '') + '</span></span>' +
      /* 趋势位（2026-09-25 加）：可用率卡此前没有走势，比同排富卡片矮 70+px。
         插在数字与副行之间，与富卡片的迷你走势位置一致。 */
      (o.spark || '') +
      '<span class="qc-sub">' + esc(o.sub) + '</span>' +
      (o.age ? '<span class="qc-age">' + esc(o.age) + '</span>' : '') +
      foot +
      (o.href ? '</a>' : '</div>');
  }
  function availRow(group) {
    var rows = (state.kpi.avail && state.kpi.avail.rows) || [];
    for (var i = 0; i < rows.length; i++) if (rows[i].cell_group === group) return rows[i];
    return null;
  }
  /* 可用率的迷你走势（2026-09-25 加）。
     数据来自 /api/alarm-dashboard/alarm-overview 的 network_availability[].series
     （后端 2026-09-25 起返回最近 30 天的逐日值 {d,v}），单位是 0~1 的小数 —— 与
     卡片大数字走同一次响应，所以线上的末端点必然与「昨日」那一格对得上。

     ⚠️ 这里**不补点**：源文件实测 4 组各 425 天连续无缺口，但万一将来缺一天，
     折线会断开（qcSparkSvg 对 null 的处理）—— 补 0 会画出「可用率跌到 0」的
     假谷底，那比一段缺口严重得多。 */
  function availSpark(row) {
    var s = row && row.series;
    if (!s || !s.length) return '';
    var pts = s.map(function (p) {
      /* 同 qcStockSeries：先挡 null/'' 再 Number()，Number(null) === 0 是有限数，
         会被当成「那天可用率 0%」。 */
      if (!p || p.v == null || p.v === '') return null;
      var n = Number(p.v) * 100;    // 0~1 → 百分数，与卡片上 97.38% 同量纲
      return isFinite(n) ? n : null;
    });
    if (pts.filter(function (n) { return n != null; }).length < 2) return '';
    /* 2026-09-28（用户确认）：这三张可用率卡**保持折线**，不改柱状。
       用户的「曲线换成柱状」是针对 Daily Operation Overview 那六张告警卡说的；
       我当时按「同屏一半折线一半柱状会像没改完」自作主张把这里也换了，
       用户随即明确要求还原 —— 记在这里，避免下次又"顺手统一"。
       保持折线的另一个实质理由：可用率是**百分比且极差极小**（97~99%），
       qcBarsSvg 按 0 起算会让三根柱子几乎等高、看不出任何起伏；
       折线按 min~max 拉伸，恰好能把这点差异显出来。图种要服务于"看得出变化"，
       不是服务于"同屏统一"。 */
    var svg = qcSparkSvg(pts);
    if (!svg) return '';
    var days = pts.length;
    var tip = tf('kpi.availTrendTip', { n: days });
    /* ⚠️ 2026-09-28（用户要求「卡片里面类似 Last 30 days … 的备注删除」）：
       折线下方的 .qc-spark-cap（"Last 30 days"）不再输出。
       它只是"这条线覆盖多少天"，而线本身已经画在那了；
       真正需要这句话的场景是"点数与预期不符"，那属于排查、不属于日常读数，
       所以整句挪进 title（hover 可见，仍然带 n 这个真实天数）。
       要恢复就把 '<span class="qc-spark-cap">…</span>' 加回来。 */
    return '<span class="qc-spark-wrap" title="' + esc(tip) + '">' + svg + '</span>';
  }
  /* ==================================================================== v1 ==
     Benchmark 行的两张走势图（2026-10-01 加，用户要求「卡片能跟 Network Status
     Overview 里的卡片一样添加图」）
     ----------------------------------------------------------------------------
     上面那三张可用率卡画的是**单条**折线（availSpark → qcSparkSvg）。
     Benchmark 这一排的卡内是**两家并排**（Orange / MTN），所以线也是两条 ——
     这是本排与上面那排唯一的画法差异，其余（.qc-spark 类名、26px 高度、
     preserveAspectRatio="none"、遇到 null 断开）**全部沿用**既有那一套，
     不另开一套样式：同一屏上两组折线的粗细、圆角、面积透明度必须一致。

     为什么必须是两条而不是把两家平均成一条：
     这一排六张卡的主题就是"两家 PK"—— 卡内两行数是两家的区间均值，
     若图只画一条，读者无法判断那条线是谁的；合成平均更是把一个
     不存在的量画出来（口径里没有"两家平均"这个指标）。

     为什么用两条 qcSparkSvg + 一个图例，而不是改 qcSparkSvg 支持多序列：
     那个函数被上面三张可用率卡与 QC 那几条走势共用（qcTrendSlot /
     qcStockSlot），给它加"多序列 + 配色"参数会让一个 30 行的纯画线函数
     长出一套配色 API，而那三个调用点一个都用不上。
     这里改成：**同一个 qcSparkSvg 调两次**（各自一份 vals），外面套一个
     相对定位的容器把两张 SVG 叠在一起 —— 两份输入共用同一个 min/max 与
     同一个横轴长度，所以叠加后两家的点必然落在同一像素列上，
     不会出现"Orange 的第 12 天"与"MTN 的第 12 天"错开一格。
     ⚠️ min/max 必须由调用方**同时**把两家的值合起来算（见 benchSpark 的
     lo/hi 入参），否则两次调用各按自己的极值拉伸，两条线会被拉成同一条
     形状 —— 那样看图的人会以为两家走势完全一样。 */
  /* 叠放两张单线 SVG 的容器。两条线用绝对定位重合，
     第二张直接铺在第一张上面（两张的 viewBox 与 padding 完全一致）。 */
  function benchSparkLayers(a, b) {
    if (!a || !b) return '';
    return '<span class="bf-spark"><span class="bf-spark-l l-o">' + a + '</span>' +
      '<span class="bf-spark-l l-m">' + b + '</span></span>';
  }
  /* 一条「两家 × 一个指标」的走势。
   * spec: { key, digits, kind }，rows: 逐日记录数组，
   *   get: function(row, brand) → 该品牌该日的原始值（null = 那天没数据）
   * 返回 '' 表示画不出来（点数不足），调用方**不要**因此把卡片改形 ——
   * 与 availSpark 同一降级：图这一格不占位，卡片靠 has-foot 把页脚沉底。
   *
   * ⚠️ 两家的点**分别**喂给 qcSparkSvg，缺的那天各自推 null（不补 0）：
   * 实测这份数据是按天导入的，个别日子只有一家有测试 —— 补 0 会画出
   * 「那天 MTN 速率掉到 0」的假谷底，比一段缺口严重得多（同 availSpark）。 */
  function benchSpark(spec, rows, get, tipKey) {
    if (!rows || !rows.length) return '';
    var brands = DATA.BENCH_BRANDS;
    var series = brands.map(function (b) {
      return rows.map(function (r) {
        var v = get(r, b);
        /* 先挡 null/'' 再 Number()：Number(null) === 0 是有限数，
           会被当成「那天是 0 Mbps」收进来（同 qcStockSeries 的教训）。 */
        if (v == null || v === '') return null;
        var n = Number(v);
        return isFinite(n) ? n : null;
      });
    });
    /* 极值取两家的**全部真实点**：只按一家算会把另一家画出界外
       （qcSparkSvg 不裁剪，超出部分会盖到邻居头上）。 */
    var all = series[0].concat(series[1]).filter(function (n) { return n != null; });
    if (all.length < 2) return '';
    /* 任一家的有效点 < 2 就整体不画：只有一条线时，读者会以为
       "另一家这段时间没有数据"是对的，但更常见的情况是它整个窗口都没采到 ——
       那种情况下这条线表达的是"数据缺失"而不是"趋势"。 */
    var okBoth = series.every(function (s) {
      return s.filter(function (n) { return n != null; }).length >= 2;
    });
    if (!okBoth) return '';
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    /* ⚠️ 两家在这段时间完全相等（实测可能出现：某窗口两家均值同分）：
       qcSparkSvg 内部对 span 有 `|| 1` 兜底，两条线会重合成一条，
       看起来像"只画了一家"。这是**如实**的呈现，不额外处理 ——
       硬把两条拉开就是篡改数据。图例里仍然标出两家颜色。 */
    var svgO = qcSparkSvg(scaleTo(series[0], lo, hi));
    var svgM = qcSparkSvg(scaleTo(series[1], lo, hi));
    if (!svgO || !svgM) return '';
    var days = rows.length;
    /* 品牌展示名取后端 label（Orange / MTN），**不直接用 brands 里的键**——
       键是 'ORANGE'（全大写，供接口与字典用），直接塞进 tooltip / 图例会写成
       "上排是 ORANGE"，与卡内两行显示的 "Orange" 不是同一个写法（实测：
       第一版就是这样，图例里是 Orange、tooltip 里是 ORANGE）。
       后端没给 label 时退回键，**不在这里写死一份名字表**：那是第三份真相源
       （同 speedCardHtml 里那一处注释）。 */
    var label = brandLabels();
    var tip = tf(tipKey, { n: days, o: label[brands[0]], m: label[brands[1]] });
    /* 图例：只写两家的名字（后端 label 与卡内每行一致），颜色点用 CSS 类给色 ——
       ⚠️ 颜色不写在这里：它必须与 .bf-spark-l 里两条线的颜色出自**同一个令牌**，
       写两份迟早分叉（改主题时只改了一处）。 */
    var lg = brands.map(function (b) {
      return '<span class="bf-spark-k k-' + (b === brands[0] ? 'o' : 'm') + '">' +
        '<i aria-hidden="true"></i>' + esc(label[b]) + '</span>';
    }).join('');
    return '<span class="qc-spark-wrap bf-spark-wrap" title="' + esc(tip) + '">' +
      benchSparkLayers(svgO, svgM) + '<span class="bf-spark-lg">' + lg + '</span></span>';
  }
  /* 两家的展示名（Orange / MTN）。两个接口的 summary[brand].label 都有这个字段，
     优先取 speedtest 那份（与卡内两行数字同一次响应），取不到再用 meta 那份。
     ⚠️ 为什么不在这里写一张 { ORANGE:'Orange', MTN:'MTN' } 的常量表：
     那会是第三份真相源（前两份是 bm_speedtest_caliber / bm_meta_caliber 的
     BRAND_LABELS）。后端改一次品牌写法，这里就会悄悄对不上。
     两处调用（tooltip 与图例）**必须共用这一个函数** —— 分开取就会出现
     "图例写 Orange、tooltip 写 ORANGE"这种同一张卡上两种写法的问题。 */
  function brandLabels() {
    var s = (state.kpi.speed && state.kpi.speed.summary) || null;
    var mm = (state.kpi.meta && state.kpi.meta.summary) || null;
    var out = {};
    DATA.BENCH_BRANDS.forEach(function (b) {
      out[b] = (s && s[b] && s[b].label) || (mm && mm[b] && mm[b].label) || b;
    });
    return out;
  }
  /* 把一串值线性映射到给定的 [lo, hi]。
     为什么要这一步：qcSparkSvg 内部是**按传入值自己的 min/max** 拉伸的，
     两次调用各拉各的，两条线就会长得一模一样（都占满整高）。
     先在这里按统一的 lo/hi 归一化，再交给 qcSparkSvg —— 它内部那次
     拉伸就变成"对已经同尺度的数据做同一变换"，两条线的相对高低才成立。 */
  function scaleTo(vals, lo, hi) {
    var span = (hi - lo) || 1;
    return vals.map(function (n) {
      return n == null ? null : (n - lo) / span;
    });
  }
  /* ==================================================================== v1 ==
     Benchmark 行：Network Benchmark View（2026-10-01 加）
     ----------------------------------------------------------------------------
     用户要求：「Network Status Overview 组件下面，新增一行，使用
     /myapp/?page=bm_speedtest 页面的、最近 30 天、Key metrics comparison 的
     Download / Upload / Latency 卡片来展示」。

     三张卡 = 三个指标（download / upload / latency），每张卡内是两家并排。
     ⚠️ **不是**「两个品牌 × 三个指标 = 六张卡」：
     源页面那张卡的粒度就是「一个指标一张卡、卡里并排两家」，
     改成六张卡会让"同一指标的对比"散到两张卡上，用户要来回看。

     数据源 /api/bm-speedtest/overview?start=&end=（见 loadKpi 里的取数说明）。
     口径唯一真相源是 my_app `backend/services/bm_speedtest_caliber.py`，
     本处只做展示，**不重算任何指标** —— 胜者、胜率、分位数全部直接用接口给的，
     在渲染层重新比一遍大小就等于给同一个问题造了第二个答案。

     与上面两排的关系：**同一张卡的两种排布**。这一行用 .qc-card--bf
     （左对齐、卡内多行），上面富卡片是居中的大数字。刻意不复用 .qc-card--rich：
     那个类的字号与行数是为「一个大数字 + 芯片 + 走势 + 三段页脚」定的，
     塞两组品牌进来会把它的排版意图搅乱；而这一排要的是"两组数上下对齐"。
     共用的是**外层**（.qc-card 的底/边/hover/内发光/--qc-accent）与
     .qc-ext 页脚结构，所以三排卡片的边框、悬停手感、页脚基线仍是一致的。 */
  function speedCardHtml(spec) {
    var sp = state.kpi.speed;
    var rows = (sp && sp.summary) || null;
    var win = (sp && sp.days) || null;
    /* 窗口说明。n 取不到时不编一个数出来 —— 走 'kpi.bf.sub' 里没有 {n} 的那半边，
       否则卡上会写着一个与数据无关的天数。 */
    var winTxt = win != null
      ? tf('kpi.bf.sub', { n: win })
      : t('kpi.bf.subNone');
    var name = t(DATA.SPEED_ROW_LABEL[spec.key]);
    var na = true;
    /* 逐项格式化。速度 1 位小数、时延 0 位 —— 与 my_app 页面的 digits 一致
       （见 BmSpeedtest.tsx 的 kpiCards 与 bms.metric 的单位）；
       latency 给 1 位小数会在卡片上多出没有信息量的尾数。 */
    var fmt = function (v) {
      if (v == null || v === '' || isNaN(Number(v))) return '—';
      return kpiNum(Number(v), spec.digits);
    };
    /* 领先方：速率取大、时延取小。**只用来标一个徽章**，
       与 wins（逐日胜率）是两件事 —— 一个说"区间均值谁高"，
       另一个说"多少天里谁赢"，可能不一致（均值被单日极值拉偏时）。
       两个都显示、且措辞分开，用户才不会把它们当成同一个结论。 */
    var pair = DATA.BENCH_BRANDS.map(function (b) {
      return { key: b, v: rows && rows[b] ? rows[b][spec.key] : null };
    });
    var lead = null;
    if (pair[0].v != null && pair[1].v != null && Number(pair[0].v) !== Number(pair[1].v)) {
      var a = Number(pair[0].v), c = Number(pair[1].v);
      lead = spec.kind === 'speed' ? (a > c ? pair[0].key : pair[1].key)
                                   : (a < c ? pair[0].key : pair[1].key);
    }
    if (pair.some(function (p) { return p.v != null; })) na = false;
    var body = pair.map(function (p) {
      var s = (rows && rows[p.key]) || {};
      var isLead = lead === p.key;
      var pc = (s.pcts && s.pcts[spec.key]) || {};
      var cell = sp && sp.wins && sp.wins.metrics && sp.wins.metrics[spec.key];
      var w = cell ? (p.key === 'ORANGE' ? cell.orange_wins : cell.mtn_wins) : null;
      var rate = cell ? (p.key === 'ORANGE' ? cell.orange_win_rate : cell.mtn_win_rate) : null;
      if (p.v != null) na = false;
      /* 品牌名用后端给的 label（Orange / MTN）—— 它也是 my_app 页面上显示的写法。
         后端没给时退回品牌键，**不在这里写死一份名字表**：那是第三份真相源。 */
      var bl = s.label || p.key;
      var rowTip = [tf('kpi.bf.tipName', { n: bl, u: spec.unit })];
      if (w != null && win != null) {
        rowTip.push(tf('kpi.bf.winTip', { m: name, n: bl, d: win, w: w, r: kpiNum(rate, 1) }));
      }
      rowTip.push(tf('kpi.bf.tipTests', { n: bl, t: kpiNum(s.tests, 0), dev: kpiNum(s.devices, 0) }));
      return '<div class="bf-row' + (isLead ? ' is-lead' : '') + '" title="' + esc(rowTip.join('\n')) + '">' +
        '<span class="bf-brand"><i>' + esc(bl) + '</i>' +
          '<span class="bf-val">' + esc(fmt(p.v)) + '</span></span>' +
        '<span class="bf-meta">' +
          '<span class="bf-pct">' + esc(tf('kpi.bf.pctCap', { a: fmt(pc.p50), b: fmt(pc.p90) })) + '</span>' +
          '<span class="bf-win">' + esc(rate == null ? '—' : tf('kpi.bf.win', { n: kpiNum(rate, 1) })) + '</span>' +
        '</span>' +
      '</div>';
    }).join('');
    /* tooltip：口径必须写全 —— 这一排的数是"区间均值"，
       而上面两排分别是"昨日值"和"当月均值"，同屏三个区间，
       不写清窗口就没人能判断哪个数能跟哪个比。 */
    var tip = [tf('kpi.bf.tipName', { n: name, u: spec.unit }),
               t('kpi.bf.tipSrc'),
               winTxt,
               tf('kpi.bf.tipAvg', { win: win == null ? '—' : win }),
               t('kpi.bf.tipPcts')];
    if (lead) tip.push(t('kpi.bf.tipLead'));
    if (na) tip.push(t('kpi.bf.na'));
    tip.push(tf('kpi.openTip', { n: name, b: t('kpi.bf.board') }));
    var href = '/myapp/?page=' + encodeURIComponent(spec.page) + langQs();
    /* 整卡可点（<a> 而非 div + onclick），理由与 kpiRichHtml 那段完全一致：
       中键新标签 / 右键复制链接 / 键盘 Enter / 读屏念成链接都是白拿的。
       rel="noopener nofollow" 与同页其它外跳一致。 */
    return '<a class="qc-card qc-card--bf qc-card--open' + (na ? ' is-na' : '') + '" href="' +
        esc(href) + '" target="_blank" rel="noopener nofollow" title="' + esc(tip.join('\n')) + '">' +
      '<div class="bf-hd"><b>' + esc(name) + '</b><i>' + esc(spec.unit) + '</i>' +
        (lead ? '<span class="bf-lead">' + esc(tf('kpi.bf.lead', { n: (rows[lead] && rows[lead].label) || lead })) + '</span>' : '') +
      '</div>' +
      '<div class="bf-rows">' + body + '</div>' +
      /* 走势图（2026-10-01 加）：插在「两家两行数」与页脚之间 ——
         与上面富卡片「大数字 → 走势 → 页脚」的次序一致，
         所以三排卡片的视觉节奏都是"先读当前值、再看趋势、最后看口径"。
         数据来自**同一次 overview 响应**的 daily（见 loadKpi 的取数说明），
         所以线的末端就是卡上那两天数所在窗口的最后一天，不会各说各话。
         ⚠️ 不给这条线做"再发一个 /trend 请求"：overview 已经把整个窗口的
         逐日值带回来了（daily_returned 实测 30 = 窗口天数），
         多打一次接口只会多一个"图与大数字不同时刻"的分叉点。 */
      benchSpark(spec, sp && sp.daily, function (r, b) {
        return r[b === 'ORANGE' ? 'orange_' + spec.key : 'mtn_' + spec.key];
      }, 'kpi.bf.sparkTip') +
      /* 页脚与上面两排共用 .qc-ext 结构与基线，但内容换成这一排**真正需要**的
         「这个数是哪个窗口、覆盖多少天、两家各测了多少」——
         不写"区间均值"这类已经在标题与 tooltip 里说过的重复话。
         tests 取两家之和：卡上是"这次对比基于多少测试"，单看一家会让
         测试量悬殊时（实测 Orange 562 / MTN 485）读者低估样本。
         ⚠️ 第三格的 Speedtest by Ookla 标识已**移除**（2026-10-15，用户要求
         「右下角的 LOGO 不要了，跟标题重复了」）—— 组头标题（qcGroupHtml
         的 .qc-group-logo）2026-10-13 起已直接显示同一份 Ookla 图形，
         卡内再放一次是同一标识在一屏里出现两遍。来源说明改由 tooltip 承担
         （kpi.bf.tipSrc，见下面 tip 数组），信息没丢，只是不再占版面。
         同理 .qc-ext 从"两格文字 + 一个标识"变回纯两格文字页脚。 */
      '<div class="qc-ext"><div><span>' + esc(t('kpi.bf.range')) + '</span><b>' +
        esc(win == null ? '—' : String(win)) + '</b><span>' + esc(t('kpi.bf.days')) + '</span></div>' +
      '<div><span>' + esc(t('kpi.bf.tests')) + '</span><b>' +
        esc(kpiNum(speedTests(), 0)) + '</b><span>' + esc(t('kpi.bf.testsUnit')) + '</span></div>' +
      '</div>' +
    '</a>';
  }
  /* 两家在该窗口内的测试数之和。任一家缺失时按 0 计会把总数说小，
     所以只要有一家没有有效值就整体返回 null（卡片显示 —），
     与全页「取不到显示 —、不显示 0」的约定一致。 */
  function speedTests() {
    var rows = (state.kpi.speed && state.kpi.speed.summary) || null;
    if (!rows) return null;
    var total = 0;
    for (var i = 0; i < DATA.BENCH_BRANDS.length; i++) {
      var s = rows[DATA.BENCH_BRANDS[i]];
      if (!s || s.tests == null || isNaN(Number(s.tests))) return null;
      total += Number(s.tests);
    }
    return total;
  }
  /* ==================================================================== v1 ==
     Benchmark 行第二组：Meta 基准报告（2026-09-30 加）
     ----------------------------------------------------------------------------
     用户要求：「参考 my_app `?page=bm_meta` 的数据，在同一行再补 3 张卡，
     尽量包含 Orange · Speed / MTN · Speed / 综合评分与胜场 /
     区间范围(Orange) / 区间范围(MTN) / BP；卡片与同排尽量保持一致」。

     3 张卡的分工（用户 2026-09-30 选定的分组，不是随手摊的）：
       ① 速率（kpi.mm.speed）—— 两家的区间均值 + 各自逐日区间
       ② 综合评分与胜场     —— 两家的相对分 + 各自的「领先 x / y 天」
       ③ BP                —— 网络侧 KPI：均值 + 逐日区间
     为什么这么并：左边那 3 张 Ookla 卡就是「一个指标一张卡、卡里并排两家」，
     若这一组改成「一家一张卡」，同一指标的对比就被拆到两张卡上，用户得来回看
     （与 speedCardHtml 那段同一条理由）。而 BP 是网络侧 KPI、**不属于任何一家**，
     所以它单独一张、卡里没有品牌行 —— 塞进任何一边都是口径错误（见
     `bm_meta_caliber` 对 BRAND_METRICS / NETWORK_METRICS 的分组说明）。

     与左边 3 张的关系：**结构一致、数据无关**。同为 .qc-card--bf
     （左对齐、卡内多行、.qc-ext 页脚），所以六张卡的边框、悬停手感、
     页脚基线仍是一套；但卡名与口径说明各写各的 —— 左边那套文案第一句就是
     "Speedtest by Ookla"，套到这里就是假话，所以不复用 kpi.bf.* 的整句。

     数据来源 /api/bm-meta/overview（见 loadKpi），口径唯一真相源是 my_app
     `backend/services/bm_meta_caliber.py` + `bm_meta_service.py`：
     本处只做展示，**不重算任何指标** —— 均值、极值、评分、胜负全用接口给的。
     ⚠️ 两条最容易读错的必须写进 tooltip：① 综合评分是**相对分**（强者恒为 100）；
     ② 「区间」是**逐日值**的极值，与大数字（区间均值）不是同一个统计量。 */
  function metaCardHtml(spec) {
    var mm = state.kpi.meta;
    var sum = (mm && mm.summary) || null;
    var net = (sum && sum.network) || null;
    var scores = (mm && mm.scores) || null;
    var wins = (mm && mm.wins) || null;
    var win = (mm && mm.days) || null;
    var covered = (mm && mm.covered != null) ? mm.covered : null;
    var at = (mm && mm.at) || '';
    var name = t(spec.name);
    var unit = t(spec.unit);
    /* 位数与 my_app 页面一致（速率 1 位、评分 1 位、BP 2 位）。
       空值一律走 kpiNum → 「—」，**不显示 0**（本页硬约定）。 */
    var fmt = function (v) { return kpiNum(v, spec.digits); };
    /* 平局那句话（卡级与行级 tooltip 共用一份）：实测 2026-09 那个窗口
       两家各领先 11 天、可比 22 天，两个 x 相加正好等于 y，卡面看着像
       "两家平分"，其实是另有 1 天平局。my_app 把平局单列了一行
       （BmMeta.tsx:496），这张卡没有那个位置，就在 tooltip 里补上。
       ties 缺失时报"无平局"而不是留空 —— 那句话本身也是口径说明，
       读者需要知道这一行只统计了两家分出胜负的日子。 */
    var tieTxt = function () {
      var tie = (wins && wins.ties != null) ? Number(wins.ties) : null;
      return (tie != null && tie > 0)
        ? tf('kpi.mm.tieN', { n: kpiNum(tie, 0) }) : t('kpi.mm.tie0');
    };
    var na = true;
    var lead = null;
    /* 一行 = 左「名字 + 数值」、右「补充说明」，与 Ookla 卡同一套 .bf-row 结构。
       tip 是这一行自己的 tooltip（行数少，读屏/悬停要能单独解释一行）。 */
    var bfRow = function (label, value, metaTxt, tip, isLead) {
      return '<div class="bf-row' + (isLead ? ' is-lead' : '') + '" title="' + esc(tip) + '">' +
        '<span class="bf-brand"><i>' + esc(label) + '</i>' +
          '<span class="bf-val">' + esc(value) + '</span></span>' +
        '<span class="bf-meta"><span class="bf-pct">' + esc(metaTxt) + '</span></span>' +
      '</div>';
    };
    var body;
    if (spec.kind === 'network') {
      /* BP：网络侧 KPI，不属于任何一家 —— 卡里只有一行（均值 + 逐日区间），
         没有品牌行、没有领先方徽章。这一行短，靠 .has-foot 把页脚沉到卡底，
         与同排其余 5 张卡的页脚落在同一条基线上（见 olbr.css 的 has-foot）。 */
      var avg = net ? net[spec.key] : null;
      var mn = net ? net[spec.key + '_min'] : null;
      var mx = net ? net[spec.key + '_max'] : null;
      if (avg != null) na = false;
      var netRange = tf('kpi.mm.obsRange', { a: fmt(mn), b: fmt(mx) });
      body = bfRow(t('kpi.mm.avg'), fmt(avg), netRange,
        [tf('kpi.mm.tipName', { n: name, u: unit }), netRange,
         tf('kpi.mm.rowDays', { n: kpiNum(covered, 0) })].join('\n'), false);
    } else {
      /* 两家并排。领先方一律按「越大越好」定 —— 本组进 PK 的两个指标（速率、
         综合评分）都是这个方向，与 my_app 的 score_brands 同向（强者分更高）。
         ⚠️ 这一点**不是**照抄 KPI_SPEED 的做法：那边有时延（越小越好），
         才需要逐条标一个 kind 方向；本组没有反向指标，多一个开关只会多一处写错。 */
      var rowsOfBrands = DATA.BENCH_BRANDS.map(function (b) {
        var s = (sum && sum[b]) || {};
        var label = s.label || b;
        var v, metaTxt, rowTip;
        if (spec.key === 'speed') {
          v = s.speed;
          metaTxt = tf('kpi.mm.obsRange', { a: fmt(s.speed_min), b: fmt(s.speed_max) });
          rowTip = [tf('kpi.mm.tipName', { n: label, u: unit }), metaTxt,
                    tf('kpi.mm.rowDays', { n: kpiNum(covered, 0) })];
        } else {
          v = (scores && scores[b]) ? scores[b].score : null;
          /* 胜场直接用接口的 orange_wins / mtn_wins 与 paired_days，
             与 my_app 那张卡同一套字段、同一个说法（本处不重算胜率）。 */
          var w = b === 'ORANGE' ? (wins && wins.orange_wins) : (wins && wins.mtn_wins);
          metaTxt = tf('kpi.mm.leadDays', {
            w: kpiNum(w, 0), d: kpiNum(wins && wins.paired_days, 0)
          });
          /* 行级 tooltip 也带上平局：用户是把鼠标停在这一行上问"两家怎么都是 11"，
             答案要在这里就能看到，不必再去卡级 tooltip 找。 */
          rowTip = [tf('kpi.mm.tipName', { n: label, u: unit }),
                    tf('kpi.mm.rowScore', { v: fmt(v), u: unit }), metaTxt,
                    tieTxt()];
        }
        if (v != null) na = false;
        return { label: label, v: v, metaTxt: metaTxt, tip: rowTip.join('\n') };
      });
      /* 两家都有值且不相等才评领先方：缺一边或打平时不挂徽章 ——
         「打平也算某方领先」是造数据，见 caliber.winner_of 的同一条处理。 */
      if (rowsOfBrands[0].v != null && rowsOfBrands[1].v != null &&
          Number(rowsOfBrands[0].v) !== Number(rowsOfBrands[1].v)) {
        lead = Number(rowsOfBrands[0].v) > Number(rowsOfBrands[1].v)
          ? DATA.BENCH_BRANDS[0] : DATA.BENCH_BRANDS[1];
      }
      body = rowsOfBrands.map(function (r, i) {
        return bfRow(r.label, fmt(r.v), r.metaTxt, r.tip, lead === DATA.BENCH_BRANDS[i]);
      }).join('');
    }
    /* 页脚三格与 Ookla 卡**同结构**（左窗口、中覆盖、右来源标识），但内容不同：
       中格是「窗口里有几天真有数」—— 这份数据是导入快照（实测数据截至
       2026-09-23），而窗口取「最近 30 天」，最近几天根本没有数；不写清这一点，
       读者会以为大数字覆盖了整整 30 天。这一格与 Ookla 卡的中格（测试量）
       表达的是同一件事：这次统计到底站在多少数据上。 */
    var foot = '<div class="qc-ext">' +
      '<div><span>' + esc(t('kpi.mm.win')) + '</span><b>' +
        esc(win == null ? '—' : String(win)) + '</b><span>' + esc(t('kpi.mm.days')) + '</span></div>' +
      '<div><span>' + esc(t('kpi.mm.cover')) + '</span><b>' +
        esc(kpiNum(covered, 0)) + '</b><span>' + esc(t('kpi.mm.days')) + '</span></div>' +
      /* 第三格按**数据源**分两种（2026-09-30 按用户要求）：
         · 速率 / 综合评分 来自 Meta 基准报告 → 原先放 META_LOGO 标识；
           该标识已**移除**（2026-10-15，用户要求「右下角的 LOGO 不要了，
           跟标题重复了」）—— 组头标题（qcGroupHtml 的 .qc-group-logo）
           2026-10-13 起已直接显示同一份 Meta 图形，卡内再放是同一标识
           在一屏出现两遍。来源说明改由 tooltip 承担（kpi.mm.tipSrc），
           信息没丢，只是不再占版面。
         · BP 是**网络侧 KPI**（Radio 侧 FDD 指标），不属于 Meta 报告那组指标 →
           仍用纯文字徽章。它没有可用的品牌资产，也**绝不能**拿 Meta 的标识
           去标一份非 Meta 报告的指标；且它与组头 logo 不重复，故保留。 */
      (spec.kind === 'brand'
        ? ''
        : '<span class="bf-src">' + esc(t('kpi.mm.srcNet')) + '</span>') +
    '</div>';
    /* tooltip 的顺序：来源 → 这个数是什么 → 窗口与覆盖面 → 空数据 → 打开哪一页。
       与 Ookla 卡同一套顺序，用户在两张卡上看到的解释次序是一致的。
       来源那一句按 kind 分两种：BP 卡若沿用 Meta 报告那句，
       就会出现"徽章写网络侧 KPI、悬停说 Meta 报告"的自相矛盾。 */
    var tip = [tf('kpi.mm.tipName', { n: name, u: unit }),
               spec.kind === 'brand' ? t('kpi.mm.tipSrc') : t('kpi.mm.tipSrcNet')];
    if (spec.kind === 'network') tip.push(t('kpi.mm.tipBp'));
    if (spec.key === 'scores') {
      tip.push(t('kpi.mm.tipScore'));
      tip.push(tf('kpi.mm.tipLead', { tie: tieTxt() }));
    }
    tip.push(t('kpi.mm.tipRange'));
    tip.push(tf('kpi.mm.tipWin', { win: win == null ? '—' : win }));
    tip.push(tf('kpi.mm.tipCover', { n: kpiNum(covered, 0), d: at || '—' }));
    if (na) tip.push(t('kpi.mm.na'));
    /* ⚠️ 最后一行说「点开哪一页」，目标看板名必须跟随**这张卡自己的 kind**
       （2026-10-07 修）。此前这里对所有 Meta 卡写死 kpi.mm.board
       （「Meta 基准报告」），而 BP 卡的目标页已改成 bp_report
       （BP Cells Report）—— 写死就会出现「悬停说 Meta 基准报告、
       点下去到 BP Cells Report」。与组头链接同一条约束：
       说要去哪儿，就必须真是去哪儿。 */
    tip.push(tf('kpi.openTip', { n: name,
      b: t(spec.kind === 'network' ? 'kpi.bp.board' : 'kpi.mm.board') }));
    var href = '/myapp/?page=' + encodeURIComponent(spec.page) + langQs();
    /* 整卡可点（<a> 而非 div + onclick）：与 speedCardHtml 同一条理由
       （中键新标签 / 右键复制链接 / 键盘 Enter / 读屏念成链接都是白拿的）。
       has-foot 见上面 BP 那段说明：它让内容少的卡把页脚沉到卡底。 */
    return '<a class="qc-card qc-card--bf qc-card--open has-foot' + (na ? ' is-na' : '') +
        '" href="' + esc(href) + '" target="_blank" rel="noopener nofollow" title="' +
        esc(tip.join('\n')) + '">' +
      '<div class="bf-hd"><b>' + esc(name) + '</b><i>' + esc(unit) + '</i>' +
        (lead
          ? '<span class="bf-lead">' + esc(tf('kpi.mm.lead', {
              n: (sum && sum[lead] && sum[lead].label) || lead
            })) + '</span>'
          : '') +
      '</div>' +
      '<div class="bf-rows">' + body + '</div>' +
      metaSpark(spec, mm) +
      foot +
    '</a>';
  }
  /* Meta 组三张卡的走势图（2026-10-01 加）。
   * 与左边 Ookla 三张的区别只有**数据来源**，画法与容器完全相同
   * （都走 benchSpark，所以两条线的粗细/透明度/图例排布是一套）。
   *
   * ⚠️ 这里**不复用** sp.daily —— 那是 bm_speedtest 的表，与 Meta 报告是两份数据。
   * 用的是 /api/bm-meta/overview 的 daily：
   *   · speed   → daily[].orange_speed / mtn_speed（逐日速率，与卡上大数字同源）
   *   · scores  → daily 里**没有**逐日评分（后端只回区间汇总分），
   *               所以这张卡的图改画**逐日速率**并明确标注 —— 见下方注释；
   *   · bp      → daily[].bp（网络侧 KPI，单线，不属于任何一家）
   *
   * ⚠️ 「综合评分」那张卡为什么画速率而不是评分：
   * 后端的 score_brands 只在**整段窗口**上算一次（bm_meta_caliber.score_brands），
   * 逐日评分在接口里根本不存在。要在图上画"逐日评分"就必须在这里重算一遍
   * 相对分 —— 那等于给同一个指标造第二个答案（本文件多处已立此约定：
   * 渲染层不重算口径）。所以这张卡的图画**它真正有的逐日数据（速率）**，
   * 并在 tooltip 里说明"这条线是速率，不是评分"，避免读者把两者当成一回事。 */
  function metaSpark(spec, mm) {
    var daily = (mm && mm.daily) || null;
    if (!daily || !daily.length) return '';
    if (spec.kind === 'network') {
      /* BP：单线。不属于任何一家，所以既没有双线叠加、也没有图例 ——
         画成两条会把"这是两家之一"这个错误信息传达出去。 */
      var pts = daily.map(function (r) {
        var v = r[spec.key];
        if (v == null || v === '') return null;
        var n = Number(v);
        return isFinite(n) ? n : null;
      });
      var real = pts.filter(function (n) { return n != null; });
      if (real.length < 2) return '';
      var lo = Math.min.apply(null, real), hi = Math.max.apply(null, real);
      var svg = qcSparkSvg(scaleTo(pts, lo, hi));
      if (!svg) return '';
      var tip = tf('kpi.mm.sparkTipNet', { n: real.length, m: t(spec.name) });
      /* ⚠️ 类名必须是 `qc-spark-wrap bf-spark-wrap`（两个都要），
         并且要补一个空的 .bf-spark-lg 占位 —— 2026-10-01 用户反馈
         「右边的 3 个横坐标太偏上了」修的就是这里：
           · `bf-spark-wrap` 是这一排"图沉底 + 与页脚固定 5px"那一套规则的钩子
             （olbr.css 的 .qc-card--bf .bf-spark-wrap），BP 早先只写了
             qc-spark-wrap，于是它**完全不参与**那套对齐，图比另外五张高 49.7px；
           · 另外五张卡有图例（高 14.4px），BP 是单线卡没有图例，
             整块因此矮 14.4px —— 对齐要求"图 + 图例"整块等高，
             所以这里补一个**空的图例格**占住同样的高度。
         空 span 不给 aria-hidden 之外的内容：它不是给读屏念的，
         只是排版占位（BP 只有一条线，本来就没有"哪条是哪家"可标）。 */
      return '<span class="qc-spark-wrap bf-spark-wrap" title="' + esc(tip) + '">' + svg +
        '<span class="bf-spark-lg" aria-hidden="true"></span></span>';
    }
    /* 速率卡与综合评分卡：都是两家 PK 的形态，画同一份逐日速率的双线。
       评分卡的那条提示语不同（说明画的是速率），由 tipKey 区分。 */
    var tipKey = spec.key === 'scores' ? 'kpi.mm.sparkTipScore' : 'kpi.mm.sparkTip';
    return benchSpark(spec, daily, function (r, b) {
      return r[b === 'ORANGE' ? 'orange_speed' : 'mtn_speed'];
    }, tipKey);
  }
  /* ---- 连体卡组的渲染（2026-10-07 加）--------------------------------------
     一组 = 一个 .qc-group，里面是「组头 + 连体卡排」。组头左边是组名
     （= 目标看板的业务名），右边是一个显式的「打开完整看板 ↗」链接，
     指向与本组每张卡**同一个** page。

      ⚠️ 为什么需要在卡片之外再来一个链接：
        每张卡自己已经能点（href 就是同一个 page），但那件事要逐张 hover
        才知道。组头的链接把「这一组只有↓一个去处」写在脸上，
        正是"容易让人误解成 N 个不同页面"这个问题的直接解法。
        它**不是**多余的重复入口：卡片链接是"点这个指标"，组头链接是
        "这个组属于哪份看板"，两者的读法不同。

      ⚠️ 组头链接与卡片链接必须同源：两者都取 g.page / spec.page，
        而这两处都由 olbr-data.js 声明，本函数**不写死任何页面** ——
        写死就会出现"组头去 A、点卡去 B"（BP 组正是靠这条才改对的）。

      ⚠️ 链接文案说的是"打开这个看板"，不说"这些卡的详细数据"：
        BP 组链接去的是 bp_report（RAN_UME 重算），而卡上的数来自
        bm_meta 快照，**不是同一份数据**。措辞不能替它们许下同源的承诺。

      g = olbr-data.js 里 KPI_GROUPS / BF_GROUPS 的成员，
      cards 是已经渲染好的卡片 HTML（顺序即声明顺序）。
      卡数取 g.items.length —— 组头说明里的 {n} 与 CSS 的列数都用它，
      不再另传一个数进来（传两个数就会有不一致的那天）。 */
  function qcGroupHtml(g, cards) {
    var n = (g.items && g.items.length) || 0;
    var board = t(g.name);
    /* {s} 只被英文那条用到（"1 card" / "3 cards"）；中文那条不带这个占位符，
       tf() 里多余的键不会渲染出来，所以两边共用一个调用。
       ⚠️ 别把单复数判断塞进中文文案：中文没有复数形态，
       分了反而多一条永远走不到的分支。 */
    var tip = tf('kpi.grp.tip', {
      n: String(n), b: board, s: t(n === 1 ? 'kpi.grp.one' : 'kpi.grp.many')
    });
    /* 组头链接与卡片一样走 langQs()：不带语言参数的话，
       点进去会掉回 my_app 的默认语言，与门户当前语言不一致。 */
    var href = '/myapp/?page=' + encodeURIComponent(g.page) + langQs();
    /* 组头显示什么（2026-10-13 加）：有 g.logo 时显示**品牌标识图形**，
       否则回落到原来的文字名。用户要求「标题改成卡片左下角的 logo」——
       logo 用的是 DATA.OOKLA_LOGO / DATA.META_LOGO 常量，不是另画一份。
       ⚠️ 2026-10-15 起这里是这两个常量的**唯一**渲染处：同一品牌在卡片页脚
       右下角的那份标识已按用户要求删除（「不要了，跟标题重复了」）——
       组头已经用图形表达了品牌，卡内再放一次是同一标识在一屏出现两遍。
       ⚠️ 图形用 role="img" + aria-label 提供无障碍名称、且 SVG 自身
       focusable="false"（不带 aria-label，见 olbr-data.js 的说明）——
       否则读屏会把 "SPEEDTEST by OOKLA" 这串图形文字当正文念一遍。
       ⚠️ 文字名 board **仍然保留**在 title / aria-label / 组级 tooltip 里：
       图形只替换"看得见的那个词"，不替换任何"要读出来的地方"，
       否则 hover 提示与读屏名称会退化成 "ookla" / "meta" 这类无上下文的串。 */
    var logoHtml = g.logo === 'ookla' ? DATA.OOKLA_LOGO
                 : g.logo === 'meta'  ? DATA.META_LOGO
                 : '';
    var headInner = logoHtml
      ? '<span class="qc-group-n qc-group-logo" role="img" aria-label="' + esc(board) +
          '" title="' + esc(tip) + '">' + logoHtml + '</span>'
      : '<span class="qc-group-n" title="' + esc(tip) + '">' + esc(board) + '</span>';
    return '<section class="qc-group" data-grp="' + esc(g.id) + '" aria-label="' + esc(board) + '">' +
        '<div class="qc-group-h">' +
          headInner +
          '<a class="qc-group-go" href="' + esc(href) + '" target="_blank" rel="noopener nofollow" ' +
            'title="' + esc(tip) + '">' + esc(t('kpi.grp.go')) +
            ic('arrow-up-right') + '</a>' +
        '</div>' +
        /* ⚠️ data-n 给 CSS 用：列数由卡数决定，不写死 3 列 ——
           BF 行的两组分别是 3 / 2 张（2026-10-12 移除 bp 组前是 3 / 2 / 1），
           写死列数会让 2 张卡的那组拉出一个空列。 */
        '<div class="qc-group-b" data-n="' + n + '">' + cards + '</div>' +
      '</section>';
  }
  /* 把一组卡按 group 定义渲染出来。render 是"一张卡怎么画"的函数。 */
  function qcGroupCards(g, render) {
    return g.items.map(render).join('');
  }
  function renderKpi() {
    var box = $('#kpi');
    if (!box) return;
    var k = state.kpi;
    var hasR = !!(k.olib && k.olib.cards && k.olib.cards.length);
    var hasA = !!(k.avail && k.avail.rows && k.avail.rows.length);
    var hasS = !!(k.speed && k.speed.summary);
    /* Benchmark 行第二组（Meta）也是"有数据就能画"的一路：四路请求各回各的，
       不能用 hasS 代表整行 —— 那样 speedtest 先回来、bm-meta 慢一拍时，
       会先画出 3 张卡再整行重排成 5 张（同一行的卡数变一次，视线要跳一下）。
       （2026-10-12 移除 bp 组前，这里是从 3 张重排成 6 张。） */
    var hasM = !!(k.meta && k.meta.summary);
    /* ⚠️ 2026-10-15：meta 组里现在有一张**来自 bm-speedtest 的时延卡**（见
       bfKinds 上方那段），所以"这一行能不能画"从此有**跨源依赖**。
       刻意**不**把 hasS 也并进这里的判断，也不给 meta 组单开一条渲染条件 ——
       KPI_META / KPI_SPEED 都是静态数组，卡数恒定，两条接口一先一后到齐时
       不会发生"卡数变化→整行重排"（这正是下面这段注释要防的事）；
       先到的那张只是内容显示「—」，后到原地补齐，符合全页
       「取不到显示 —、不显示 0」的约定。若在这里加 hasS，反而会让
       speedtest 慢一拍时**整行晚出现**，那才是新引入的跳动。
       后人看到"meta 组为什么依赖 speed 数据"时，请先读 bfKinds 那段再动手。 */

    if (k.loading && !hasR && !hasA && !hasS && !hasM) {
      /* 骨架屏也照两排摆，且**与真实结构 1:1**（2026-10-07 起含连体卡组）。
         骨架若还是 5 张平铺，数据到位那一刻会连"组头"一起凭空长出来，
         整块高度往下弹 —— 这正是骨架屏要避免的事。
         （2026-10-12 移除 bp 组前是 6 张平铺。）
         所以骨架也走同一个 qcGroupHtml：组头（组名 + 链接）是真的，
         只有卡身换成 .sk 灰条。组头文案此时已可取（组名来自数据文件，
         不依赖接口），所以骨架阶段就能显示正确的看板名。
         ⚠️ 口径说明（kpi.sub）不直接占一行，改挂到标题的 title 上，hover 才出。
         理由两条：① 用户要求（2026-09-25）——这一行是「解读说明」，不是数据，
         常驻会把整块标题区撑高、也让卡片的视线起点下移；
         ② DESIGN.md:76「长文本用 truncate，并把完整内容放 title 属性，
         不要靠换行撑高卡片」，本来就是这么规定的。
         骨架屏阶段也要挂同样的 title，否则数据到位那一刻标题的悬浮提示会"突然出现"。
         cursor:help 由 .band-k[title] 给（见 olbr.css），不在这里写死。 */
      /* ---- 骨架卡：**按真卡的分段同构地搭**（2026-10-07 重做）-------------
         ⚠️ 这里踩过一个坑，写下来免得下次又踩：
         旧写法只丢几条 .sk 灰条进卡片，看着"像个骨架"，但 .sk 是
         **固定 12px 高 + 外边距**的小方块，五条加起来才 90px 上下；
         而真卡的内部是一条有固定高度的链
         （富卡：标题 19 + 数值 25 + 日期 14 + 徽章 21 + 走势 26 + 页脚 51，
          加外边距 27 与内边距 19 = 203px）。
         实测差异：上排骨架 155px vs 真卡 237px（差 82），
         Benchmark 行 208 vs 254（差 46）—— 数据到位时整块往下弹 129px。
         所以骨架必须**复用真卡的分段类名**（.qc-ttl / .qc-val / .qc-asof /
         .qc-chips / .qc-spark / .qc-ext），让每一段自己撑出该有的高度。
         新造一套类名等于把"卡内长什么样"抄成两份，两边迟早漂移。
         ⚠️ 灰条给显式高度，是为了让占位块等于它替的那段（数值 25 / 走势 26），
         不是随便定一个好看的数字。 */
      /* 页脚是最高的一段（真卡实测 51px：三格，每格是"小标签 + 数值 + 单位"
         两行文字，格内 45px）。骨架里每格只放一条 12px 灰条的话，
         整段只有 18px —— 这一段就是骨架矮 30px 的主因。
         所以每格给一条 45px 的占位，等于它替的那一格。 */
      var skFoot = function () {
        return '<div class="qc-ext"><span class="sk" style="height:45px;width:70%"></span>' +
          '<span class="sk" style="height:45px;width:70%"></span>' +
          '<span class="sk" style="height:45px;width:70%"></span></div>';
      };
      var skRich = function () {
        /* ⚠️ 不加 has-foot：真卡里富卡与可用率卡都**没有**这个类
           （它只给 Benchmark 那几张内容少的卡用）。多挂一个 has-foot 会让
           .qc-ext 吃到 margin-top:auto，骨架的页脚被顶到卡底、多出 6px。 */
        return '<div class="qc-card qc-card--rich">' +
          '<div class="qc-ttl"><span class="sk" style="height:19px;width:56%"></span></div>' +
          '<div class="qc-val"><span class="sk" style="height:25px;width:62%"></span></div>' +
          /* ⚠️ 用真卡的 .qc-asof / .qc-spark 包一层，不要直接放裸 .sk：
             这两段的高度里有**外边距**的贡献（.qc-asof margin-top:2px、
             .qc-spark margin-top:8px），裸 span 拿不到那 10px ——
             实测正是这 10px 让骨架比真卡矮一截。 */
          '<div class="qc-asof"><span class="sk" style="height:14px;width:40%"></span></div>' +
          '<div class="qc-chips"><span class="sk" style="height:21px;width:80%"></span></div>' +
          '<div class="qc-spark"><span class="sk" style="height:26px"></span></div>' +
          skFoot() +
        '</div>';
      };
      /* 可用率卡与富卡同构（2026-10-01 起两者逐行对齐），所以骨架也同一套，
         只在数据段少一条 —— 真卡里两者就是同样的分段。 */
      var skAvail = skRich;
      /* Benchmark 行的骨架卡。
         ⚠️ 光"有 5 条灰条"是不够的：真卡的内部是一条**有固定高度的链**
         （标题 21 + 数据行 41~74 + 走势 43 + 页脚 51 + 内边距 19 = 220px），
         而灰条是固定 12px 高 + 外边距，5 条加起来只有 90px 上下。
         实测：改之前骨架行 176px、真行 222px，**数据到位时整块往下弹 46px**
         （2026-10-07 量到，与本次分组无关，是既有缺陷）。
         这里按真卡的分段同构地补上对应节点（标题 / 两行数据 / 走势 / 三格页脚），
         让骨架自己就有 220px 高。不去写死一个 min-height：
         写死高度会在改真卡排版时立刻失配，而同构的节点会自己跟着长。
         ⚠️ 类名复用真卡的 .bf-hd / .bf-rows / .qc-ext，**故意不新造一套** ——
         新造一套就等于把"卡片内部长什么样"抄成两份，两边必然漂移。 */
      var skBf = function () {
        /* ⚠️ 页脚**只有两格**（2026-10-15 起）：Benchmark 卡真卡的页脚是
           「窗口 n 天 / 两家合计 N 次」，第三格那个来源标识已按用户要求删除。
           这里刻意**不用** skFoot()（它是三格，给富卡/可用率卡用的）——
           骨架要与真卡同构，多摆一格会让数据到位时页脚少一格、整排卡片的
           文字基线横向错位一下。每格仍给 45px 高，与真卡那一格等高。 */
        return '<div class="qc-card qc-card--bf has-foot">' +
          '<div class="bf-hd"><span class="sk" style="height:21px;width:44%"></span></div>' +
          /* 数据行按**最高的那一组**留位（Ookla 卡实测 74px）：
             骨架阶段还不知道哪张卡会拿到几行数，取最高值即"最坏情况"，
             保证数据到位只会变矮、不会把下面的内容顶下去。
             Meta 41px / BP 19px 都比它矮，所以它们的数据到位时会有
             一点向上的收缩 —— 这比"先矮后弹"好，因为下方的元素不会位移。 */
          '<div class="bf-rows"><span class="sk" style="height:74px"></span></div>' +
          '<span class="sk" style="height:43px;margin-top:auto"></span>' +
          '<div class="qc-ext"><span class="sk" style="height:45px;width:70%"></span>' +
            '<span class="sk" style="height:45px;width:70%"></span></div>' +
        '</div>';
      };
      /* 上排两组：富卡片（KPI_RICH）+ 可用率（KPI_AVAIL_ROWS）。 */
      var skTop = DATA.KPI_GROUPS.map(function (g) {
        return qcGroupHtml(g, g.items.map(g.id === 'rich' ? skRich : skAvail).join(''));
      }).join('');
      /* Benchmark 行的骨架屏（2026-10-01 加；2026-10-07 起是连体组）。
         它**必须**在这里就画出来：这一行是四路请求里最慢的一路
         （speedtest 与 bm-meta 各要跑几段 SQL），
         若等数据回来才渲染，整块的高度会在数据到位那一刻往下弹一下。
         ⚠️ 骨架的**组数与每组卡数**必须与真实行一致（3 / 2，共 5 张；
         2026-10-12 移除 bp 组前是 3 / 2 / 1，共 6 张），
         这样"骨架 → 数据"是替换而不是位移。
         遍历 BF_GROUPS 而不是写死组数：将来一组卡增减时不会漏改骨架。 */
      var skBfRow = DATA.BF_GROUPS.map(function (g) {
        return qcGroupHtml(g, g.items.map(skBf).join(''));
      }).join('');
      box.innerHTML = '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
        esc(t('kpi.sub')) + '">' + esc(t('kpi.title')) + '</div></div></div>' +
        '<div class="qc-grid">' + skTop + '</div>' +
        '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
          esc(tf('kpi.bf.subBoth', { n: (k.speed && k.speed.days) || '—' })) + '">' +
          esc(t('kpi.bf.title')) + '</div></div></div>' +
        '<div class="qc-grid">' + skBfRow + '</div>';
      return;
    }
    /* ---- ① 四张富卡片 / ② 三张可用率卡：**各自成组**（2026-10-07 改）------
        这两组去的 my_app 页面不同（vmaxCxoDashboard_90Days / avail_ms），
        此前六张卡在同一个 .qc-grid 里平铺、外观一致，看不出"左三张一个入口、
        右三张另一个入口"。现在各包一层 .qc-group，组头写明各自的目标看板。
        渲染函数按组成员逐个调用对应的卡片函数：组成员来自 DATA.KPI_GROUPS.items
        （引用 KPI_RICH / KPI_AVAIL_ROWS 本身），所以表里增删卡这里自动跟。 */
    var richKinds = {
      rich: function (spec) { return kpiRichHtml(spec, olibCard(spec.id)); },
      avail: function (spec) { return availRichHtml(spec, availRow(spec.group)); }
    };
    var top = DATA.KPI_GROUPS.map(function (g) {
      return qcGroupHtml(g, qcGroupCards(g, richKinds[g.id]));
    }).join('');
    /* 顶栏时间戳取 olib 的写入时间（富卡片的主数据源）。
       取 vmax 的话会显示另一个接口的时间，与卡上数字对不上。 */
    var stamp = (k.olib && k.olib.updated_at) || '';
    var err = k.err ? '<p class="band-n" style="color:var(--crit)">' + esc(t('kpi.err') + ': ' + k.err) + '</p>' : '';
    /* ---- Benchmark 行（2026-10-01 加）：用户要求「在 Network Status Overview
       组件下面新增一行」。它挂在**同一个 #kpi 容器内**、紧跟第一行之后，
       而不是新开一个 <section>：这一行是同一个组件的第二排，
       分出去会让"Network Status Overview"这个标题与它的数据脱钩，
       也会在 section 之间多出一道栅格间距。
       标题行沿用与上面同款的 .band-h/.band-txt/.band-k 结构，
       但**不挂时间戳与重试按钮** —— 那两个是整块组件的刷新状态
       （重试会同时重拉四路），在第二行再放一套会让人以为可以单独刷这一排。
       数据本身的时间口径（data_max_date）写在卡片的 tooltip 里。

       2026-09-30：这一行由 3 张变 6 张，后 3 张来自**另一个数据源**
       （my_app bm_meta）。标题的 tooltip 换成 kpi.bf.subBoth ——
       kpi.bf.sub 只说得清左 3 张，挂在整行标题上会让人以为 6 张都是 Ookla 的数。

       2026-10-07：本行改成**连体卡组**（当时是 3 + 2 + 1）。各组的目标页
       **互不相同**（bm_speedtest / bm_meta / bp_report），所以"这一行去几个
       页面"这件事此前完全看不出来；连体组 + 组头链接就是为它而加的。
       ⚠️ 组内"连体"（共享外框、只在相邻处留一条细缝）而组间留正常栅格间距 ——
       这件事必须一眼看得出，光靠间距大小是看不出的。

       2026-10-12（v2 专有）：bp 组（BP Cells Report）已按用户要求移除 ——
       它不是 benchmark 的内容。本行现为**两个连体组**（3 + 2，共 5 张），
       两个组的目标页仍互不相同（bm_speedtest / bm_meta）。 */
    var bf = '';
    if (hasS || hasM || !k.loading) {
      /* 组成员逐个交给对应的卡片函数。speed 组 3 张（下载/上传/时延）、
          meta 组 3 张（速率/综合评分/时延，2026-10-15）。
         ⚠️ 派发按**每一项自己的 src**（'speed' | 'meta'），**不是**按组 id（2026-10-15 改）。
         起因：meta 组要加一张时延卡，而 Meta 报告上游根本没有时延列，
         那张卡取的是 Ookla 的真实时延 —— 于是**同一个组里出现了两个数据源**，
         按组派发（bfKinds[g.id]）再也表达不了。
         每条 KPI 项在 olbr-data.js 里显式声明 src，就是"这张卡的数据从哪来"的
         唯一真相源；渲染层据此选函数，不按 key 特判、也不猜。
         ⚠️ 刻意**不写** `key === 'latency' ? speedCardHtml : metaCardHtml` 这类特判：
         那会把"跨源"这件事藏进一个 if 里，下一个混源组还得再付一次代价。
         ⚠️ 旧的 `bp` 派发项已删除：BF_GROUPS 里早已没有 bp 组（2026-10-12 移除），
         留着是永不执行的死代码。将来若恢复 BP 卡，给它标 src:'meta' 即可。 */
      var srcKind = {
        speed: function (spec) { return speedCardHtml(spec); },
        meta:  function (spec) { return metaCardHtml(spec); }
      };
      bf = '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
          esc(tf('kpi.bf.subBoth', { n: (k.speed && k.speed.days) || '—' })) + '">' +
          esc(t('kpi.bf.title')) + '</div></div></div>' +
        '<div class="qc-grid">' +
          DATA.BF_GROUPS.map(function (g) {
            return qcGroupHtml(g, qcGroupCards(g, function (sp) {
              return srcKind[sp.src](sp);
            }));
          }).join('') +
        '</div>';
    }
    box.innerHTML =
      '<div class="band-h">' +
        /* kpi.sub 挂 title，不占行 —— 理由见上面骨架屏那一处。
           ⚠️ err（接口报错）**保持可见**，绝不能一起收进 title：
           隐藏说明是取舍，隐藏错误是让人以为数据正常。 */
        '<div class="band-txt"><div class="band-k" title="' + esc(t('kpi.sub')) + '">' +
          esc(t('kpi.title')) + '</div>' + err + '</div>' +
        /* 2026-09-28：时间戳与「重试」按钮原来紧跟标题（实测 x=286/489），
           与上面 Daily Operation Overview 的排布不一致 —— 那边两者贴在卡片右缘
           （x=1221/1452）。这里补一个与那边同款的 .band-sp 弹性占位把它们顶到右边，
           两个组件的标题行于是都是「左标题 / 右状态与操作」。
           用同一个 .band-sp 类而不是新写一条 margin-left:auto：
           占位的宽度语义（flex:1 1 0 + min-width:0）在两处必须一致，
           否则窄屏折行时的行为会分叉。 */
        '<span class="band-sp" aria-hidden="true"></span>' +
        (stamp ? '<span class="qc-live"><i class="ph ph-clock" aria-hidden="true"></i>' +
          '<span class="qc-when">' + esc(t('kpi.updated').replace('{t}', stamp)) + '</span></span>' : '') +
        '<button type="button" class="gb" data-act="kpi-reload" title="' + esc(t('kpi.retry')) + '">' +
          ic('refresh') + esc(t('kpi.retry')) + '</button>' +
      '</div><div class="qc-grid">' + top + '</div>' + bf;
  }

  /* ==================================================================== v1 ==
     六个视图入口卡（2026-09-24 加）
     ----------------------------------------------------------------------------
     按需求「CXO VIEW / SP View / MS VIEW / FLM View / FO VIEW / BO VIEW 等
     也作为卡片的形式，里面展示部分报告名字，用户点击跳转对应的页面」实现。

     与下面 L1 页签的关系：**并存，不替代**。页签是"看这一组里所有的卡"，
     这里是"从报告名直接跳到那一个"。所以本块只列 V6_LIMIT 条（默认 2），
     其余靠「展开其余 N 项」按需展开 —— 把 51 个看板全列在首屏，等于把
     页签那块重做一遍，还占掉地图的位置。

     列表怎么来的：直接用 allowed()（= 目录 ∩ 当前用户权限），
     按目录顺序取前 N 条。**不写死报告名** —— 写死的话，目录一改
     （改名、下架、换链接）这里就成了错的第二份真相源；
     而目录本身是可以在本页编辑的，两边一定会漂移。
     权限过滤也一定要走 allowed()：把用户看不到的看板名摆出来，
     点进去是 403，比不显示更糟。 */
  /* 六个入口卡的图标。键必须取 DATA.PH 表里真实存在的键 ——
     表里没有的会静默退回 dashboard（方块图标），不报错但六张卡长得一样。 */
  var V6_ICONS = {
    'CXO View': 'chart-line', 'SP View': 'package', 'MS View': 'gauge',
    'FLM View': 'wrench', 'FO View': 'bell', 'BO View': 'cpu'
  };
  var V6_LIMIT = 2;
  /* 列头标题的跳转目标（2026-09-26 加，用户要求「卡片的标题也要能点击打开下级页面」）。
     实测口径：点「SP View」应进入 viewer.html?no=34&gid=SP%20View ——
     即该分组**按当前排序的第一条**看板，与列内第一行是同一个目的地。
     为什么取"第一条"而不是另配一份"分组代表看板"：
       · 列里已经按 sorter(gid) 排好，第一行就是用户在本卡里最先看到、最近点过的那个；
         再定一份代表看板等于给同一个问题两个答案，目录一改就会对不上（第二真相源）；
       · 该分组为空时（或全部被权限过滤掉时）**不渲染链接**，退回原来的纯文本标题 ——
         宁可点不动，也不要链到一个不存在的看板。
     ⚠️ gid 必须跟着链接走：viewer 靠 gid 决定面包屑与"同组其余看板"的上下文，
     漏掉它会退化成"从全部看板里点进来的"，与本卡表达的"进入这个视图"不符。 */
  /* 列头链接：点「标题」进本组第一条看板。
     ⚠️ 2026-09-28（用户要求「改成点击标题所在的行就开始跳转」）：
     链接**不再只包住标题文字**，而是包住整个 .v6-t-top 那一行（标题 + 右上箭头）。
     做法是把返回的 <a> 移出 v6-t-top 之外、改成包住它 —— 见 renderViews6 里的调用处。
     这里仍返回同一个 <a> 开标签，语义与样式钩子（.v6-t-link）不变。
     为什么不是"给整行加 click 事件"：<a href target=_blank> 的默认行为
     自带中键新标签、右键"在新标签打开"、悬停显示 URL、键盘 Tab 聚焦 ——
     换成 JS 监听要逐条补回来，且失去 href 的可访问性语义。
     行内其余部分（计数徽章、编辑工具按钮）仍在链接**外**：
     它们不是"进入某个视图"的一部分，包进来会出现「点计数也跳走」。 */
  function v6HeadLink(gid, list) {
    var it = list && list[0];
    if (!it) return '';
    return '<a class="v6-t v6-t-link" href="' + esc(vlink(it, gid)) + '" target="_blank" ' +
      'rel="noopener noreferrer" title="' + esc(tf('v6.headTip', { n: titleOf(it) })) + '">';
  }
  /* 六个入口卡显示哪六列。这是**固定的一份名单**，不是「目录里所有分组」——
     用户明确要求本页只显示这六张卡，不要因为目录里多了一个分组就多长出一列
     （新增分组是给 /olbrportal/ 与 MsPortal 用的；本页新建的分组不会多出一列，
     但会立刻出现在目录里，那两处能看到，本页也可通过卡片的「分组」按钮把看板挂进去）。

     ⚠️ 2026-10-07：名单仍是这六个 id（**成员**没有变），但**顺序**改为可调整 ——
     见 v6Gids()。常量退化成"成员名单 + 出厂顺序"两个角色里的前者，
     顺序真相源交给 catalog.groups（与服务端目录同一份）。 */
  var V6_GROUPS = ['CXO View', 'SP View', 'MS View', 'FLM View', 'FO View', 'BO View'];
  /* 六列的**实际渲染顺序**（2026-10-07 加，用户要求「group 的顺序也要能调整」）。

     为什么不能再用 V6_GROUPS 直接 forEach：那份常量是出厂顺序，用户拖不动。
     而服务端目录里的 catalog.groups **本来就是有序的**（后端注释：
     `数组顺序即展示顺序、id 不可改`，见 routers/portal_catalog.py 的模块说明），
     左栏筛选条 chips（2026-10-16 已随检索轨移除）当年也一直按它渲染 ——
     只有这六张入口卡还在读死常量，
     于是同一个页面里出现了**两套分组顺序**（实测：catalog.groups 是
     CXO→MS→FLM→SP→FO→BO，而卡片渲染成 CXO→SP→MS→FLM→FO→BO）。
     本函数把顺序统一到那一份上，顺手消掉这个自相矛盾。

     过滤而不是直接映射：state.groups 里可能还有 System Admin / Knowledge Q&A /
     Friends Link / Archived 等分组，它们不属于这六张卡，必须滤掉（成员名单不变）。
     state.groups 尚未加载时（或老目录里缺某个 id）用 V6_GROUPS 兜底补全 ——
     宁可顺序退回出厂值，也不能让某一列凭空消失。

     ⚠️ 2026-10-19：本函数读 state.groups，而 loadCatalog 只在 `c.groups` **非空**
     时才覆盖它（见该函数）。所以「服务端目录缺 groups」时本页会退回内置
     olbr-data.js 的 T0+T1+T2 顺序（CXO→SP→MS→FLM→FO→BO），
     而 MsPortal 的 allGroups() 读它自己那份 data.js，Base 顺序本就不同。
     真正的统一点是服务端 catalog.groups：有它，读写它的页面就一致。
     排查「列顺序对不上」先看 /api/portal-catalog 返回的 catalog.groups。 */
  function v6Gids() {
    var known = {};
    V6_GROUPS.forEach(function (g) { known[g] = 1; });
    var out = [], seen = {};
    (state.groups || []).forEach(function (g) {
      var id = g && g.id;
      if (!id || !known[id] || seen[id]) return;
      seen[id] = 1; out.push(id);
    });
    V6_GROUPS.forEach(function (g) { if (!seen[g]) { seen[g] = 1; out.push(g); } });
    return out;
  }
  /* 把六列的新顺序写回 catalog.groups（服务端持久化）。
     只重排这六个 id 之间的相对位置，**其余分组的绝对位置全部保持不动** ——
     目录里还住着 System Admin 等本页不渲染的分组，如果粗暴地"六列排前面、
     其余的往后一丢"，一次拖动就会把 MsPortal 与本页目录分组（当时还有左栏 chips）
     的分组顺序改掉，
     而用户在六张卡上根本没看到那些分组（等于改了看不见的东西）。
     做法：取出这六列当前占据的槽位，把新顺序依次填回去 —— 槽位集合不变，
     于是"被拖动的只有这六个"，其余分组相对彼此的次序原样保留。

     与 order/subGroups/groups 的其余改动同一条路：走 commit()，
     它会做「乐观改 → 重绘 → PUT → 失败整批回滚」。 */
  function reorderV6Groups(next) {
    var cur = state.groups || [];
    var slots = [];
    cur.forEach(function (g, i) { if (V6_GROUPS.indexOf(g.id) !== -1) slots.push(i); });
    if (slots.length !== next.length) return;            /* 长度对不上 = 名单不一致，宁可不改 */
    var byId = {};
    cur.forEach(function (g) { byId[g.id] = g; });
    var out = cur.slice();
    slots.forEach(function (idx, k) { out[idx] = byId[next[k]]; });
    var same = out.every(function (g, i) { return g === cur[i]; });
    if (same) return;                                    /* 拖回原位：不发多余的 PUT */
    commit(function () { state.groups = out; }, t('edit.grpOrderOk'));
  }
  /* 拖动一列到另一列的前/后：算出六列的新顺序，交给 reorderV6Groups 落盘。
     只在**六列这一层**做 splice —— 传入的是 v6Gids() 的结果（恰好六个），
     拖完把新数组交回去，reorderV6Groups 再按槽位填回 catalog.groups。
     这样"拖动"这件事的语义只在一处定义，提交那一侧不必知道用户拖了哪一格。 */
  function moveGroupOrder(from, to, before) {
    if (!from || !to || from === to) return;
    var seq = v6Gids(), i = seq.indexOf(from), j = seq.indexOf(to);
    if (i === -1 || j === -1) return;
    seq.splice(i, 1);
    /* ⚠️ 必须在**移除 from 之后**重新取 to 的下标：j 是移除前的下标，
       当 from 原本在 to 左边时，移除会让 to 整体左移一格。
       不重取的话"把第 1 列拖到第 3 列右边"会落成"拖到第 2 列右边"，
       表现为拖了没到想去的位置、还差一格。 */
    j = seq.indexOf(to);
    if (j === -1) return;
    seq.splice(before ? j : j + 1, 0, from);
    reorderV6Groups(seq);
  }
  /* 六列在网格里的落点判定：按主轴（|dx| 与 |dy| 谁大）决定"插到左边那列之前还是之后"，
     与卡片排序的 sideOf() 是同一套手感（网格一行多列，只看上下会把"插到左边那列之前"
     判成插到后面）。返回 true = 插到目标列之前。 */
  function v6BeforeOf(col, e) {
    var r = col.getBoundingClientRect();
    var dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
    if (Math.abs(dx) > Math.abs(dy)) return dx < 0;
    return dy < 0;
  }
  /* 六个视图入口卡（CXO / SP / MS / FLM / FO / BO）。
     每一列 = 一个分组，列内是该分组的看板行。

     ⚠️ 这一块**就是本页的编辑对象**（2026-09-26 恢复编辑能力时定的）：
     本页没有 /olbrportal/ 那种 L1 分组页签面板，可编辑的卡片只有这里，
     所以编辑态把行条目从「纯链接」升级成「卡片」：
       · 加 a.card.is-ed 类 + draggable + data-gid/data-no
         —— bindEdit() 里的拖拽三件套（dragstart/dragover/drop）只认
            `a.card.is-ed`，不改这里拖拽就完全没反应；
       · 行尾补上改名 / 分组两颗按钮（edBtns）；
       · 列头补上分组改名 / 新增分组两颗按钮（v6HeadTools）。
     只读态保持原样：纯链接、无按钮、无 draggable（见下面的 else 分支）。 */
  /* 渲染单个视图入口条目（只读 = 纯链接；编辑态 = 可拖拽的 a.card）。
     2026-10-12 从 renderViews6 里抽出：BO View「全部」分组显示时也要逐条渲染，
     两处必须共用同一份行模板，否则编辑态与只读态的行会长得不一样。 */
  function v6RowHtml(it, gid, ed) {
    var txt = ic(it.icon) + '<span>' + esc(titleOf(it)) + '</span>' +
      (it.status === 'beta' ? '<em>' + esc(stOf(it)) + '</em>' : '');
    /* 只读态：纯链接，交给浏览器默认行为（target=_blank），不拦截。 */
    if (!ed) {
      return '<a class="v6-row" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" ' +
        'title="' + esc(descOf(it) || titleOf(it)) + '">' + txt +
        '<i class="ph ph-arrow-up-right go" aria-hidden="true"></i></a>';
    }
    /* 编辑态：与 itemCard 同构 —— 外层是 <a>，所以「分组」按钮必须 preventDefault，
       否则会顺手把查看器开一个新标签（onEditClick 里已拦）。 */
    return '<a class="card v6-row is-ed" href="' + esc(vlink(it, gid)) + '" target="_blank" ' +
      'rel="noopener noreferrer" title="' + esc(descOf(it) || titleOf(it)) + '"' +
      ' data-no="' + esc(it.no) + '" draggable="true" data-gid="' + esc(gid) + '">' + txt +
      edBtns(it, gid, true) +
      '<i class="ph ph-arrow-up-right go" aria-hidden="true"></i></a>';
  }

  function renderViews6() {
    var box = $('#views6');
    if (!box) return;
    var items = allowed();
    var ed = canEdit();
    var html = '';
    /* 列顺序取 v6Gids()（= catalog.groups 里这六个 id 的先后），不再是常量顺序。
       tools 那一段要判"是不是最后一列"，用这个数组而不是 V6_GROUPS 常量 ——
       拖动之后最后一列会变，读常量会把「新增分组」留在旧的那一列上。 */
    var gids = v6Gids();
    gids.forEach(function (gid) {
      var list = items.filter(function (it) { return inGroup(it, gid); });
      /* 先把条目按「本组的目录顺序」排好（与 L1 页签用同一个 sorter），
         否则这里列出来的前几条会与页签里看到的头几张卡对不上。
         编辑态有新拖出来的顺序就按它排 —— 否则拖完顺序不回显，看起来像没保存。 */
      list = list.slice().sort(sorter(gid));
      /* 二级子分组页签（BO View 的 RAN/IP/MW/CN/OCS）：
         必须在分页 slice 之前筛 —— 它的作用是「把本列换成这一桶的看板」，
         放在 slice 之后就只能筛到已经露出来的那两条，点 MW 会显示空。
         ⚠️ 编辑态**不筛**：拖拽要在整列范围内重新排序，筛掉一部分会让
         「把卡拖到另一个子分组旁边」做不到（与 v6Open 编辑态一律全列同理）。 */
      var sub = ed ? { html: '', list: list, grouped: '' } : v6SubBar(gid, list, list);
      list = sub.list;
      var open = !!state.v6Open[gid];
      var show = open || ed ? list : list.slice(0, V6_LIMIT);
      /* 2026-10-12：选中「全部」且该分组有子分组时，sub.grouped 是一段
         **按专业域分段**的 HTML（照 MsPortal viewer 的分组显示）。此时整列
         不再平铺，也不再有「展开其余 N 项」——分段视图本身就列全了每一桶。
         选中某个具体桶、或没有子分组时，grouped 为空串，仍走下面的平铺。 */
      var body;
      if (sub.grouped) {
        body = sub.grouped;
      } else {
        body = list.length
          ? show.map(function (it) { return v6RowHtml(it, gid, ed); }).join('')
          : '<div class="v6-empty">' + esc(t('v6.empty')) + '</div>';
      }
      /* 编辑态一律列出全部：折起来的话「拖到看不见的那几张之间」根本做不到。 */
      if (!ed && !sub.grouped && list.length > V6_LIMIT) {
        body += '<button type="button" class="v6-more" data-act="v6-toggle" data-gid="' + esc(gid) +
          '" aria-expanded="' + (open ? 'true' : 'false') + '">' +
          '<i class="ph ph-' + (open ? 'caret-up' : 'caret-down') + '" aria-hidden="true"></i>' +
          '<span>' + esc(open ? t('v6.less') : tf('v6.more', { n: list.length - V6_LIMIT })) + '</span></button>';
      }
      /* 编辑态列头给四颗工具：改本列分组名 / 重置本列顺序 / 新增看板 / 新建分组。
         「重置顺序」沿用 panelHead 的口径 —— 只在该列真有自定义顺序时才出现，
         没有顺序还给按钮就是噪声。本页没有 L1 面板，这颗按钮原先只存在于
         panelHead 里，不在这里补一颗的话：一旦拖过就再也回不到默认排序。
         「新增看板」每列都有（要往哪一列加就得在那一列上点），而「新增分组」
         仍然只出现在最后一列 —— 分组是全页共用的一个列表，每列都摆一颗是纯噪声。 */
      var hasOrd = canEdit() && (state.order[gid] || []).length;
      var tools = !ed ? '' :
        (hasOrd
          ? '<button type="button" class="ct ct--rst" data-act="rst-order" data-gid="' + esc(gid) +
            '" title="' + esc(t('edit.resetTip')) + '"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>' +
            esc(t('edit.reset')) + '</button>'
          : '') +
        '<button type="button" class="ct" data-act="item-add" data-gid="' + esc(gid) +
          '" title="' + esc(t('edit.itemAddTip')) + '"><i class="ph ph-plus-circle" aria-hidden="true"></i>' +
          esc(t('edit.itemAdd')) + '</button>' +
        '<button type="button" class="ct" data-act="grp-edit" data-gid="' + esc(gid) +
          '" title="' + esc(t('edit.grpEditTip')) + '"><i class="ph ph-tag" aria-hidden="true"></i>' +
          esc(t('edit.grpEdit')) + '</button>' +
        (gid === gids[gids.length - 1]
          ? '<button type="button" class="ct" data-act="grp-add" title="' + esc(t('edit.grpAddTip')) +
            '"><i class="ph ph-folder-plus" aria-hidden="true"></i>' + esc(t('edit.grpAdd')) + '</button>'
          : '');
      /* 整列可拖（2026-10-07 加，用户要求「group 的顺序也要能调整」）。
         draggable + data-col-gid 只加在**编辑态**：只读访客的列不该出现抓手光标，
         更不该拖得动（拖也存不进去，落点高亮会变成一次假反馈）。
         与行条目（a.card.is-ed）区分开的关键是属性名：卡片用 data-gid，
         列用 data-col-gid —— 拖拽三件套靠 closest 分别认这两种。
         ⚠️ 不加 is-ed 类：`a.card.is-ed` 是卡片拖拽的判据，列是 div.v6 不是 a.card，
         加一个用不上的类只会让下次读代码的人以为两者共用一条路径。 */
      html += '<div class="v6' + (ed ? ' is-col-ed' : '') + '" data-gid="' + esc(gid) + '"' +
        (ed ? ' draggable="true" data-col-gid="' + esc(gid) + '"' : '') + '>' +
        '<div class="v6-h"><span class="v6-ico" aria-hidden="true">' + ic(V6_ICONS[gid]) + '</span>' +
          /* 名称取目录（gName），不另建一份 i18n 文案：
             目录里的分组名本来就是可以在本页编辑、且 MsPortal 共用的一份，
             再写一套 sec.* 字典会出现「改了分组名，这里还是旧的」。
             ⚠️ 2026-09-28（用户要求「点击标题所在的行就开始跳转」）改：
             原先 v6HeadLink 返回的 <a> 只包住标题文字，箭头 .v6-t-go 在 <a> 外面，
             于是「点标题跳、点箭头不跳」—— 箭头本身就是最像可点目标的那一颗。
             现在把 <a> **上移到包住整个 .v6-t-top 行**（标题 + 箭头都在里面），
             于是这一行的任意位置都能点开。
             右侧计数/子分组页签/编辑工具仍在链接**外**：它们不是"进入某个视图"
             的一部分，包进来会出现「点计数也跳走」，与行内按钮抢点击。
             结构上 .v6-t-link 仍挂在 <a> 上（样式钩子不变），只是它现在
             是 .v6-h 的直接子元素，而 .v6-t-top 变成它的子元素
             —— CSS 里 .v6-t-top > span 的单行省略规则不受影响。 */
          v6HeadLink(gid, list) +
            /* 标题文字与箭头各占一层：文字那一颗负责单行省略（CSS 的
               .v6-t-top > span），箭头必须留在它外面 —— 一起裁掉的话，
               长标题在窄列里就完全看不出「这里可以点」。

               ⚠️ 2026-09-27：分组说明 gSub（如 BO View 的
               "Back Office Expert Support"）**已从这一行移除**，不再渲染。
               它先是从"标题下方独占一行"改成与标题并排（用户要求），
               但并排后实测列头一行需要 649px
               （图标36 + 标题与说明316 + 六颗页签239 + 计数40 + 缝），
               而三列网格每列只有 474-577px —— 差 70-175px，
               六个页签在常见屏幕上**必然**被挤到第二行。
               用户选择"去掉说明，腾地方给页签"，故此处不再输出 <small>。
               gSub 本身仍留在目录里（MsPortal 与编辑面板还在用），
               只是本页列头不显示 —— 不是删数据。 */
            '<span class="v6-t-top"><span>' + esc(gName(gid) || gid) + '</span>' +
              '<i class="ph ph-arrow-up-right v6-t-go" aria-hidden="true"></i></span>' +
          (list.length ? '</a>' : '') +
          /* 子分组页签（BO View 的 RAN/IP/MW/CN/OCS）。
             ⚠️ 2026-09-27 改：原来夹在 .v6-h 与 .v6-list 之间、自己占一整行；
             用户要求跟标题那行放一起（"也放到同一行，可以适当小一点"），
             所以挪进 .v6-h，位置在「标题链接之后、计数徽章之前」。

             为什么放在 .v6-n **前面**：.v6-n 带 margin-left:auto，
             它是这一行的"右对齐锚点"。页签插在它后面就等于把自己也推到最右，
             跟计数徽章挤在一起；插在它前面，页签贴着标题向右延伸，
             计数徽章仍钉在卡片右边缘（与改动前一致，不算破格）。

             去掉说明后这一行的账（1600px 视口、可用 474px）：
             图标36 + 标题82 + 页签239 + 计数40 + 3道缝18 = 415px，放得下。

             为什么不做成可滚动容器：列宽只有网格的 1/3（实测约 490px），
             六个页签要跟标题、说明、计数挤在一行。放不下时**应该**换行
             （见 CSS 的 flex-wrap），而不是横向滚动 —— 滚动条在这么窄的
             卡头里既难操作、又会把行高顶起来，还不如老老实实折成两行。 */
          (sub.html || '') +
          '<span class="v6-n">' + list.length + '</span>' + tools + '</div>' +
        /* ⚠️ 页签已挪进 .v6-h（见上），这里不再重复输出 sub.html。
            仍然不放进 .v6-list：它会跟着列表一起被滚动/裁剪，
            页签要始终贴在卡片顶部（它是这一列的控制器，不是内容）。 */
        '<div class="v6-list">' + body + '</div></div>';
    });
    box.innerHTML =
      /* ⚠️ 2026-09-28（用户要求「不要 Click a report name to open that dashboard」）：
         标题下方那行 <p class="band-n"> 已整段去掉，不再渲染。
         这行是"怎么用"的说明文字，而卡片本身已经把可点这件事表达清楚了
         （每行尾巴带 ↗ 箭头、悬停有 title、光标是手型），常驻一句使用说明
         只是在标题区占高。文案键 v6.sub 仍留在字典里（MsPortal 侧可能还用，
         本页不渲染 ≠ 删文案）；要恢复就把这一行加回来。
         去掉后 .band-txt 里只剩 .band-k 一行 —— 容器本身保留，
         它同时是 .band-h 的 flex 左侧项（右侧无内容，故不再需要占位）。 */
      '<div class="band-h"><div class="band-txt"><div class="band-k">' + esc(t('v6.title')) + '</div></div></div>' +
      '<div class="v6-grid">' + html + '</div>';
  }

  /* 列内二级子分组页签条（2026-09-27 加）。
     按需求「BO View 要建立 sub group 页签，RAN/IP/MW/CN/OCS」实现。

     只给**配了子分组的分组**渲染（当前只有 BO View）：subGroupsOf() 返回空数组时
     整条不出现，所以另外五张卡的外形一个像素都不变。返回空串而不是空容器 ——
     留一个 <div class="v6-subs"> 会在卡片里撑出一段没有内容的间距。

     与只读态两个口径的取舍：
       · 「全部」页签的计数用 all.length（该列全部看板），各子桶计数用桶内条数，
         两者都是**过滤后**的集合（allowed ∩ 搜索/筛选）—— 与列头 .v6-n 同源。
         在这里显示全量计数会与列头数字打架，用户会以为页签漏了卡。
       · 空桶**不隐藏**：页签是「这个视图按专业域的完整切分」，把 OCS 藏起来
         等于告诉用户「BO View 没有 OCS 这一域」，而事实是暂时没挂看板。
         但空桶点进去会是空列表，所以给它 disabled —— 点不动比点开一片空白诚实。

     选中态存 state.v6Sub[gid]（按分组分开记），不跨分组串：
     在 BO 选了 MW 再去看 SP，不该让 SP 也被筛成 MW。 */
  function v6SubBar(gid, all, list) {
    var subs = subGroupsOf(gid);
    if (!subs.length) return { html: '', list: list };
    var sid = state.v6Sub[gid] || '';
    /* 先算各桶：用 all（本列过滤后的全量）而不是 list（可能已被上次选中筛过），
       否则切换页签时别的桶计数会跟着变小 —— 那是「桶里没卡」的假象。 */
    var buckets = subs.map(function (s) {
      return {
        id: s.id, label: subChipLabel(s), full: subName(s),
        list: all.filter(function (it) { return subOfItem(it, gid) === s.id; })
      };
    });
    /* 归属为空 / 指向已删子分组的看板：兜底桶。**只在真有这种卡时**才出现 ——
       没有漏网之鱼时摆一个「未归类 0」是纯噪声。 */
    var rest = all.filter(function (it) {
      return !subs.some(function (s) { return s.id === subOfItem(it, gid); });
    });
    if (rest.length) buckets.push({ id: SUB_NONE, label: t('v.subOther'), full: t('v.subOther'), list: rest });
    /* 选中的桶若已不存在（子分组被删 / 权限变化后空了），退回「全部」——
       否则下面会筛出一个永远空、且页签上找不到对应选中态的列表。 */
    if (sid && !buckets.some(function (b) { return b.id === sid && b.list.length; })) sid = '';
    var picked = sid ? buckets.filter(function (b) { return b.id === sid; })[0] : null;
    var btn = function (id, label, full, n) {
      var on = id === sid;
      /* title 用**全称**、可见文字用短缩写：列宽只有网格的 1/3（约 500px），
         五个域的全称（"RAN · Radio Access Network"）会把页签条撑成 5 行 217px，
         把卡片内容整个挤下去。缩写 + 悬停给全称，是这块唯一能兼顾
         「一眼看清有哪几个域」与「不占掉半张卡」的做法。 */
      var tip = n ? (full || label) : t('v6.subEmptyTip');
      return '<button type="button" class="v6-sub" data-sub="' + esc(id) + '"' +
        ' data-gid="' + esc(gid) + '" aria-pressed="' + (on ? 'true' : 'false') + '"' +
        (n ? '' : ' disabled') + ' title="' + esc(tip) + '"' +
        /* aria-label 给全称：读屏用的人听到的应该是「RAN 无线接入网」而不是「RAN」，
           可见文字为了排版被压缩了，这里要把语义补回来。 */
        ' aria-label="' + esc((full || label) + ' ' + n) + '">' +
        esc(label) + '<small>' + n + '</small></button>';
    };
    /* 2026-10-12（v2 专有改动）：选中「全部」时，本列改为**按专业域分段**显示 ——
       照 MsPortal/viewer.html?gid=BO View 的分组显示（renderList/subSectionHtml，
       MsPortal/assets/viewer.js:481-520）。每桶一个可折叠标题行（caret + 域短名 +
       计数），下面跟该桶条目；归属落空的卡进「未归类」兜底段。
       用户 2026-10-12 要求「BO View 为 all 的时候要跟 MsPortal viewer 一样的分组显示」。
       ⚠️ 只在「全部」时分段：选中某个具体桶时仍只显示那一桶（页签已是过滤器），
          编辑态根本不进这里（renderViews6 里 ed 时 sub 恒为 {html:''}）。
       ⚠️ 分段视图一次列全每一桶，故不再有「展开其余 N 项」的折叠入口
          （renderViews6 里判断 sub.grouped 非空即跳过 v6-more）。
       折叠状态存 state.v6SubFold（默认展开、**不持久化**）—— 与 viewer 的
       state.subOpen 同一取舍：「我这次翻到哪了」是临时视图状态。 */
    var grouped = '';
    if (!sid) {
      var segs = buckets.map(function (b) {
        return v6SegHtml(gid, b.id, b.label, b.full, b.list);
      }).join('');
      grouped = segs || '<div class="v6-empty">' + esc(t('v6.empty')) + '</div>';
    }
    return {
      html: '<div class="v6-subs" role="group" aria-label="' + esc(t('v6.subAria')) + '">' +
        btn('', t('v6.all'), t('v6.all'), all.length) +
        buckets.map(function (b) { return btn(b.id, b.label, b.full, b.list.length); }).join('') +
        '</div>',
      list: picked ? picked.list : list,
      grouped: grouped
    };
  }

  /* 一个专业域分段（.v6-seg）：可折叠标题行 + 该域条目。
     点标题翻转折叠、标题带域短名与计数。行条目复用 v6RowHtml（只读态）。

     ⚠️ 2026-10-12（用户要求「BO View 里面 all 默认也是显示 2 条，内容默认不展开，
     每段默认全折叠」）：与 MsPortal viewer 的 subSectionHtml（默认展开）**相反** ——
     这里**默认全部折叠**，只显示段头（域短名 + 计数），点段头才展开该域条目。
     即 state.v6SubFold[sid] 的判定由 `!== false`（默认开）改为 `=== true`（默认关）。 */
  function v6SegHtml(gid, sid, label, full, list) {
    var open = state.v6SubFold[sid] === true;   // 默认折叠
    var head = '<button type="button" class="v6-seg-h' + (open ? '' : ' closed') +
      '" data-act="v6-seg" data-sub="' + esc(sid) + '" data-gid="' + esc(gid) + '"' +
      ' aria-expanded="' + (open ? 'true' : 'false') + '" title="' + esc(full || label) + '">' +
      '<i class="ph ph-caret-down" aria-hidden="true"></i>' +
      '<span class="v6-seg-t">' + esc(label) + '</span>' +
      '<span class="v6-seg-n">' + list.length + '</span></button>';
    return head + (open ? list.map(function (it) { return v6RowHtml(it, gid, false); }).join('') : '');
  }

  /* ⚠️ 2026-09-29（用户要求「GIS Map 添加并只显示 /myapp/?page=mwRealTime 的地图组件，
     reload 和 openlink 放到最右边」，随后澄清「GIS Map 和 mwRealTime 都要显示」）：
     本栏**内嵌** my_app 的地图页（iframe），当前**三个页签**：
       · gis         —— 「Alarm」（GIS 页）
       · person      —— 「Person」（人员位置地图，2026-10-19 按用户要求加在 Alarm 之后）
       · mwRealTime  —— 「MW」（微波实时）
     概念上分两层，读代码时别搞混：
       · 屏幕上方那行标题叫 **GIS Map** —— 那是**栏标题**，来自 map.title
         （headTitleText()，可改名，也可被 catalog.tabLabels.__head 覆盖）；
       · 标题下面那条页签决定**这一栏里显示哪一页**，取自 DATA.MAP_TABS。
     当天中途我曾把本栏误改成"只用 mwRealTime 顶掉 gis"——那是我把
     「添加并只显示 …mwRealTime 的地图组件」读成了"替换"，实际是"新增"。
     现已恢复成两个页签，页签条也在（有两个页签就必须有地方切换）。

     页签与地图的关系：mapItems() 把 DATA.MAP_TABS 展开成页签，
     state.mapTab 记住当前选中项，curMap() 取出它。
     ⚠️ 页签**不按目录过滤** —— 详见 mapItems() 上方那段（曾因此在线上少一个页签）。

     src 为什么带 mwembed=1：
     my_app 侧认这个参数判定「处于门户内嵌上下文」（2026-09-29 起主要用于
     隐藏 my_app 自己那套工具栏/KPI，见 mw_real_time.html 的 html.mw-embed 规则）。
     ⚠️ 它**不再**影响滚轮缩放：原先 MapWheelZoomOnClick.tsx 靠它决定
     「点击后才允许滚轮缩放」，该组件已于 2026-09-29 按用户要求删除；
     内层页本身现在一律允许滚轮缩放。门户这一侧**自己**在 2026-10-22 加了
     「缩放锁」（默认锁定）来挡误触，见下方 applyMapWheelLock 整段说明 ——
     两者互不相关：内层页放行，锁是门户在外面施加的。
     参数本身仍必须带 —— 去掉会让内嵌页把自己的 header/KPI 一起显示出来。
     **这两页都不接受 msportal-embed / msportal-theme 消息**，
     所以主题只能靠 URL 的 theme= 带一次。

     ⚠️ 两页的**嵌套深度不同**，取景相关的结论别互相照抄：
       · gis        —— 单层：Leaflet 直接在门户 iframe 里；不暴露任何全局，
                       refitLeaflet 对它无效。它自己落 zoom 7，由 zoomOnce 放大一级。
       · mwRealTime —— 双层：外层 React 壳 + 内层 mw_real_time.html；
                       会往 window 上挂 fitAllSites()，refitLeaflet 生效（含放大）。
     两页**都落在 zoom 7**（内层页自己的取景档，实测），
     放大一级后的落点见 MAP_ZOOM_IN_BY_PAGE 处（2026-10-16 起按页配置：
     Alarm/gis 不放大、MW/mwRealTime 放大）。 */
  /* 兜底页：mapItems() 展开后为空时（理论上不会，MAP_TABS 非空）用它兜底，
     否则 curMap() 取不到对象、下面各处读 .src/.page 会抛错。 */
  var MAP_FALLBACK = { page: '', src: 'about:blank', title: '' };

  /* 把 DATA.MAP_TABS 展开成页签数组。
     ⚠️ 2026-09-29 修：**不再按"目录里有对应看板"过滤**。
     原实现抄自 MsPortal（`... .filter(m => !!m.item)`），但那是错的：
     MAP_TABS 是这份壳自己声明的**固定地图页清单**，而目录是用户可增删的业务数据 ——
     线上目录里 `page=gis` 的看板早被删掉了（出厂默认 portal-default.json 里
     有 custom-gis-map，线上 /api/portal-catalog 的 56 条里没有），
     于是 gis 页签被这层过滤静默滤掉，本栏只剩一个页签、页签条整条不渲染，
     表现就是用户报的「GIS Map 没有了」。
     ✔ 正确口径：页签由 MAP_TABS 决定（写死的两页就该有两个页签）；
       目录只用来取**显示标题**（取不到就回落 i18n 文案键），不影响页签是否存在。
     MsPortal 那边仍带 item 过滤（它还有 tellEmbed/权限等其它依赖），
     两边在这里**故意不一致**，改之前先确认那边是否也已修。 */
  function mapItems() {
    var all = allowed();
    return DATA.MAP_TABS.map(function (m) {
      var it = all.filter(function (x) { return String(x.url || '').indexOf('page=' + m.page) !== -1; })[0];
      return {
        page: m.page, key: m.key, icon: m.icon, item: it,
        /* 标题优先级：目录里的看板名 → i18n 文案键（map.gis / map.mw）。
           只认当前语言，缺值回落另一个语言是 MsPortal 的老口径，这里沿用。 */
        title: it ? (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) : t(m.key),
        /* ⚠️ gisShift=1 是 **v2 专属**开关，别再把它并进 mwembed。
           ---- 它解决什么 ----
           用户要求「地图右移 10% + 上移 3%，避开本栏左侧的告警排名面板」**只在
           本门户内嵌时生效**，直开 /myapp/?page=gis 要保持默认居中取景。
           但四个壳内嵌 gis 时 src **都带 mwembed=1**（本文件 / MsPortal/portal.js:4016
           / olbrportal/olbr.js:1235 / v1 那三个），my_app 侧据此**分不出**是不是 v2，
           故必须另起一个只有本壳才带的参数。
           ---- 为什么只给 gis 加、MW 页不加 ----
           左侧那两条面板（.gis-rank-overlay / #gis-layers-panel）**只在 Alarm 页**
           （page=gis）存在；MW 页没有，给它平移是纯损失（会把地图推得偏掉）。
           这与 my_app 侧 SHIFT_WEST_PX 常量注释里「只服务 Alarm 页」的结论一致。
           ---- 与 portalFiles=1 是同一套做法 ----
           参见 my_app 的 EmailReports.tsx（isPortalFilesMode）—— 那边也是「本壳专属
           参数、只有本壳的 iframe src 带」，并明确记了「不能用 mwembed /
           isShellLessEmbed 判定，那些对所有壳都命中」这条教训。 */
        /* 2026-10-19：补 `embed=1`。my_app 自 2026-10-18 起不再把「?page=」当作
           隐藏外壳的开关（见 App.tsx readBareModule），门户内嵌若只带 page 与
           mwembed，iframe 里会连 Header / 侧栏一起渲染出来。emailSrc 同一处理。 */
        /* 2026-10-19：person 页再带 `maponly=1`。用户要求「设计成跟其他页签一样，
           只显示地图」—— 该页默认是完整看板（筛选条/KPI/图表/人员表），
           由 my_app 侧按这个参数切成"只有 Leaflet 画布"的形态（见 PersonMap.tsx
           的 readMapOnlyMode 注释：为什么不让门户用 MAP_STRIP_CSS 去剥）。 */
        src: '/myapp/?page=' + m.page + '&mwembed=1&embed=1'
          + (m.page === 'gis' ? '&gisShift=1' : '')
          + (m.page === 'person' ? '&maponly=1' : '')
          + (state.theme === 'dark' ? '&theme=dark' : '') + langQs()
      };
    });
  }
  /* 当前选中的地图页。state.mapTab 若指向已不在 MAP_TABS 里的页（旧会话残留），
     回落到第一项。MAP_TABS 非空是硬约束，故正常路径取不到才会用到 MAP_FALLBACK。 */
  function curMap() {
    var ms = mapItems();
    return ms.filter(function (m) { return m.page === state.mapTab; })[0] || ms[0] || MAP_FALLBACK;
  }

  /* 内嵌地址：用相对路径 /myapp/… 而不是写死 http://localhost/myapp/…：
     门户换机房/换域名时（见 src/config.ts 的单一真相源约定）这边不用跟着改，
     而 iframe 的跨域剥离逻辑（stripFrame 读 contentDocument）**要求同源**，
     写死 localhost 会在用 IP 访问门户时变成跨域、剥离与取景全部静默失效。 */
  function mapSrc() {
    return curMap().src;
  }
  /* Open Link 的地址（2026-10-19 用户：「Open Link 打开完整页面」）。
     内嵌 src 里的 `maponly=1` 只服务**门户栏内**的"只显示地图"形态；
     新窗口是给人看的完整页，必须去掉它（Person 页默认就是「筛选条 + KPI +
     图表 + 地图 + 人员表」的完整看板）。
     ⚠️ 只剥这一个参数，其余（mwembed / embed / lang / theme）原样保留：
     它们与本页的取景、语言、主题一致，去掉反而会让新窗口与门户里看到的不一样。 */
  function mapOpenSrc() {
    return mapSrc().replace(/([?&])maponly=[^&#]*(&?)/, function (all, pre, post) {
      if (pre === '?') return post ? '?' : '';
      return post ? pre : '';
    }).replace(/[?&]$/, '');
  }

  /* 地图栏的面板头 + 页签 + 工具按钮（2026-09-23 抽出）。
     抽出来的原因：快速路径（renderL0(true)）只重画左栏，改名后必须就地刷新这块，
     否则「改完标题还是旧的」会被当成没保存成功。整份 HTML 由 renderL0 与快速路径共用，
     避免两处走样（页签里含 tabLabelOf 的结果，必须跟着 tabLabels 变）。
     2026-09-29：页签条随「本栏恢复 gis + mwRealTime 两页」加回来。 */
  function mapHeadHtml() {
    var ed = canEdit();
    var maps = mapItems();
    /* ⚠️ 结构要点：.p-head 的**直接子元素必须是三个**（.p-hd / .map-tabs / .map-tools），
       页签才能靠左右两条等宽弹簧居中。写成 .p-hd 包住后两者是错的 ——
       那样 .p-head 只有一颗子元素，弹簧无从谈起（实测页签偏左 236px）。
       所以标题那颗 <span class="p-hd"> 在这里**单独闭合**，不要跨到页签。 */
    return '<div class="p-head"><span class="p-hd">' +
      (ed
        ? '<button type="button" class="p-t p-t-edit t-orange" data-act="map-head" title="' + esc(t('edit.maptabTip')) + '">' +
          esc(headTitleText()) + '<i class="ph ph-pencil-simple maptab-pen" aria-hidden="true"></i></button>'
        : '<span class="p-t t-orange">' + esc(headTitleText()) + '</span>') +
      /* 标题右侧的副标题 .p-s 仍不输出：它与主标题同为 "GIS Map"，写两遍是冗余
         （2026-09-28 用户要求）。headSubText() 保留给改名浮层读，
         恢复方式就是在这里加回一颗 <span>。 */
      '</span>' +
      /* 2026-09-29 用户要求「两个页签居中显示」。原来的结构是：
           标题 ──── .map-tabs（页签+按钮，margin-left:auto 整体贴右）
         页签因此在**按钮旁边**、跟着一起贴右，看着偏右而不是居中。
         现在拆成**三段**（左标题 / 中页签 / 右按钮），各用一条 flex 规则定位：
           · .p-hd       flex:1 1 0 + min-width:0 —— 弹簧①，标题超长自己省略
           · .map-tabs   flex:none —— 内容宽，被两侧弹簧顶到正中
           · .map-tools  flex:1 1 0 + margin-left:auto —— 弹簧②，内容自己贴右
         居中原理见 olbr.css 的 .map-tabs 段：左右两条弹簧等长，页签自然落正中。
         这样不用绝对定位，页签也不会盖住标题或按钮（长标题时标题自己省略）。
         ⚠️ 之前那种「margin-left:auto 让整块贴右」的写法与居中互斥，已去掉；
         贴右改由 .map-tools 自己的 margin-left:auto 负责（实测最后一颗按钮右缘
         仍等于标题条右缘）。 */
      '<div class="map-tabs">' +
      /* 页签条：只在真的有 2 个以上页签时输出 —— 只剩一页时它是纯装饰，
         点它没有任何状态可切，反而让人以为还有别的地图可看。 */
      (maps.length > 1
        ? '<div class="tabs' + (ed ? ' is-renaming' : '') + '" role="tablist">' + maps.map(function (m) {
            return '<button type="button" class="tab" role="tab" data-map="' + esc(m.page) + '" aria-selected="' +
              (m.page === curMap().page ? 'true' : 'false') + '" title="' +
              esc(ed ? t('edit.maptabTip') : m.title) + '">' + ic(m.icon) + esc(tabLabelOf(m.page, m.key)) +
              (ed ? '<i class="ph ph-pencil-simple maptab-pen" aria-hidden="true"></i>' : '') + '</button>';
          }).join('') + '</div>'
        : '') +
      '</div>' +
      /* 工具按钮独立成 .map-tools：与页签分开，才能让页签真正居中而按钮仍贴右。
         2026-09-29 用户要求「reload 和 openlink 放到最右边」——这条继续成立。 */
      /* 整段由 mapToolsHtml() 产出（2026-10-22）：缩放锁切换时要就地替换这一段，
         留在 inline 会变成两份、改一处走样。 */
      mapToolsHtml() + '</div>';
  }

  /* 地图容器渲染：把内嵌面板写进 #l0Map。
     函数名沿用 renderL0 是为了不动 render() / renderCatalog() / 主题切换那几处调用点。 */
  function renderL0(keepMap) {
    var mapBox = $('#l0Map');
    if (!mapBox) return;
    /* 快速路径：iframe 一旦离开文档，Chrome 就直接丢弃它的内容文档 ——
       「先抓节点再搬回来」救不回来（实测 sameNode:true / sameWindow:false），
       代价是改一个字拓扑图重载几十秒。所以只要地图还在，就整块不动。
       但 p-head 要就地刷新：改名走的是 renderCatalog → renderL0(true)，
       不重画标题的话「改完标题没变」会被当成没保存成功。 */
    if (keepMap && mapBox.querySelector('.map')) {
      var phead = mapBox.querySelector('.p-head');
      if (phead) phead.innerHTML = mapHeadHtml();
      return;
    }
    mapBox.innerHTML = '<section class="panel map" data-tier="0" aria-label="GIS Map">' +
      mapHeadHtml() +
      '<div class="canvas"><iframe id="mapFrame" title="' + esc(headTitleText()) + '" src="' + esc(mapSrc()) + '"></iframe>' +
      '<div class="canvas-note"><span>' + esc(t('map.title')) + '</span>' +
      '<span>/myapp/?page=' + esc(curMap().page) + '</span></div></div></section>';
    wireMap();
  }

  /* 二级子分组：与 MsPortal 同一份口径，定义随服务端目录落盘（catalog.subGroups）。
     归属只认 item.subOf[gid]；boSub 仅在整条 subOf 都不存在时作迁移前兜底，
     且要用「该分组下确实有这个子分组」校验过才认 —— 一个看板可以同挂多个分组
     （实测 no=11/12/13/18/36 同时在 FO + FLM），拿 boSub 直接套用会把 A 分组的
     归属串到 B 分组。内置三份是 data.js 打底用的，文案抄 portal.js 的 I18N 原值。 */
  /* ⚠️ 2026-09-27 改：BO View 的子分组由「wireless / core / ip」三个
     改为按**专业域**切分的 RAN / IP / MW / CN / OCS 五个（用户要求
     「BO View 要建立 sub group 页签，RAN/IP/MW/CN/OCS」）。

     为什么必须换掉旧的三个 id，而不是往上加两个：
     旧口径是按「职责笼统归堆」切的（wireless 一桶里混了微波 MW 与 IP 丢包，
     core 一桶里混了防火墙 FW 与基站动力），16 张卡里没有一张能被
     「RAN / MW / CN / OCS」正确选中；留着旧 id 只会让归属分成两套互不相干的名字。

     ⚠️ 这份 SUB_BUILTIN **只是打底默认**，不是生效的来源：
     线上服务端目录 /api/portal-catalog 里已经有一份 BO View 子分组
     （catalog.subGroups），subGroupsOf 的规则是「服务端有这个键就用服务端的」。
     真正让人看到五个页签的，是**服务端目录被改成新口径**；
     改这里是为了让「服务端目录读不到时」（fetch 失败 / 换机器还没同步）
     页面仍然长成 RAN/IP/MW/CN/OCS，而不是退回旧的三个 id。

     id 用专业域缩写（ran/ip/mw/cn/ocs）而不是 title 那串中文：
       · id 是存在看板归属里、且**建好就不再改**的东西（改 id 等于让已有归属
         指向不存在的子分组），中文名将来要润色时不该牵连数据；
       · 缩写在目录导出、URL 与 MsPortal 侧都更好认。 */
  var SUB_BUILTIN = {
    'BO View': [
      { id: 'ran', zh: 'RAN 无线接入网', en: 'RAN · Radio Access Network' },
      { id: 'ip', zh: 'IP 承载网', en: 'IP · Bearer Network' },
      { id: 'mw', zh: 'MW 微波传输', en: 'MW · Microwave Transmission' },
      { id: 'cn', zh: 'CN 核心网', en: 'CN · Core Network' },
      { id: 'ocs', zh: 'OCS 在线计费', en: 'OCS · Online Charging System' }
    ]
  };
  /* 旧 BO 子分组 id → 新专业域 id 的迁移映射。
     ⚠️ 线上服务端目录（/api/portal-catalog）**已经有一份** BO View 子分组，
     且它优先于下面这份 SUB_BUILTIN（subGroupsOf 里键存在就用服务端的）。
     所以这张表不是「主方案」，而是**兜底**：服务端还没迁到新口径时
     （换机器、目录回滚、MsPortal 侧存了旧值），读到的旧 id 在这里被翻成新域，
     界面不会因为「页签换了名字」而把看板丢掉。

     旧口径的三个 id（wireless / core / ip）与新五域不是一对一：
     wireless 那桶里混着微波、IP 丢包与基站动力，所以**逐条判定**见 SUB_KEEP_REMAP，
     这里只兜「按桶名能对上」的部分。 */
  var SUB_MIGRATE = { wireless: 'ran', core: 'cn', ip: 'ip', MW: 'mw', OCS: 'ocs' };
  /* 旧归属的**逐条覆盖表**：no → 新子分组 id。优先级高于 SUB_MIGRATE。
     为什么需要它：旧口径本身分错了（微波 MW 与 IP 丢包都躺在 wireless 桶里），
     按桶名映射只会把错误继续带下去。这几条按看板号直接给结论。

     归属依据（2026-09-27 与用户逐条确认，看板号取自**线上目录**）：
       26 Packet Loss  → IP（IP RAN 回传链路丢包，传输与 IP 网管部）
       27/28 MW        → MW
       36 Battery      → RAN（蓄电池属基站动力配套，站点侧随无线）
       23 FW_Daily     → CN（防火墙/安全设备归核心网域）
       51/66 OCS       → OCS（客户业务 KPI + OCS iMonitor）
     其余按桶名映射即可（wireless→ran 的 20/21/22、core→cn 的 24/25、
     ip→ip 的 29/30/31/32），所以不在这里重复列出 —— 名单越短越不容易漂移。 */
  var SUB_KEEP_REMAP = { '23': 'cn', '26': 'ip', '27': 'mw', '28': 'mw', '36': 'ran', '51': 'ocs', '66': 'ocs' };
  var SUB_NONE = '__none';    /* 该分组下没写归属的看板：兜底桶，宁可单列也不丢条目 */
  function normalizeSubMap(v) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
    var out = {};
    Object.keys(v).forEach(function (gid) {
      if (!Array.isArray(v[gid])) return;
      out[gid] = v[gid].filter(function (s) { return s && typeof s === 'object' && s.id; })
        .map(function (s) { return { id: String(s.id), zh: s.zh || '', en: s.en || '' }; });
    });
    return Object.keys(out).length ? out : null;
  }
  /* 键不存在 = 用内置；键存在但数组为空 = 该分组显式没有子分组（服务端能存下这个区别） */
  function subGroupsOf(gid) {
    var m = state.subGroups;
    if (m && Object.prototype.hasOwnProperty.call(m, gid)) return Array.isArray(m[gid]) ? m[gid] : [];
    return SUB_BUILTIN[gid] || [];
  }
  function subOfItem(it, gid) {
    var m = it && it.subOf, has = m && typeof m === 'object' && !Array.isArray(m);
    if (has) {
      var sid = String(m[gid] || '');
      /* BO View 走口径迁移：读的时候就把旧 id 翻成新域，屏幕上不会再出现
         「页签找不到这张卡」的情况。别的分组按原值返回（见 migrateBoSubOf 注释）。 */
      if (!sid) return '';
      return gid === 'BO View' ? boSubValid(migrateBoSubOf(sid, it.no)) : sid;
    }
    /* 迁移前的旧数据：boSub 只有一个值，要拿「该分组下确实有这个子分组」校验过才认 ——
       一个看板可以同挂多个分组（实测 no=11/12/13/18/36 同时在 FO + FLM），
       拿 boSub 直接套用会把 A 分组的归属串到 B 分组。 */
    var legacy = it && it.boSub ? String(it.boSub) : '';
    if (!legacy) return '';
    var cand = gid === 'BO View' ? migrateBoSubOf(legacy, it.no) : legacy;
    return subGroupsOf(gid).some(function (s) { return s.id === cand; }) ? cand : '';
  }
  function subName(s) { return state.lang === 'en' ? (s.en || s.zh || s.id) : (s.zh || s.en || s.id); }
  /* 页签上的**短标签**：只取专业域缩写（RAN / IP / MW / CN / OCS），
     全称留给 title 与 aria-label（见 v6SubBar）。

     为什么不直接用 subName()：列宽只有网格的 1/3（实测约 500px），
     英文全称 "RAN · Radio Access Network" 把页签条撑成 5 行、高 217px，
     卡片内容被整个挤下去 —— 而这五个域的名字本来就已经带缩写前缀
     （「RAN 无线接入网」/「RAN · Radio Access Network」），缩写是天然可读的。

     取值口径：名字里第一段**全大写/数字的字母**（长度 2-4）就是域缩写；
     取不到（用户把子分组改名成了纯中文，例如「核心网」）就退回整名 ——
     宁可显示长一点，也不要为了排版把名字截成看不懂的碎片。 */
  function subChipLabel(s) {
    var full = subName(s);
    var m = /^\s*([A-Z][A-Z0-9]{1,3})(?=[\s·\-–—]|$)/.exec(full);
    return m ? m[1] : full;
  }

  /* -------------------------------------------------- 目录写入（编辑态） -- */
  /* 三个入口（拖拽排序 / 子分组 / 分组归属）最后都走 save() 这同一条路：
     一次改动 = 一次整份 PUT。刻意不攒「批量保存」——
     后端没有版本号 / ETag，谁最后 PUT 谁赢，攒得越久越容易把别人这段时间的
     改动整份盖掉。⚠️ items 一律取 ITEMS 全量（服务端原样那份），
     绝不能取屏幕上筛选/权限过滤后的列表，否则一次带搜索的保存会把别的看板抹掉。 */
  function canEdit() { return !!(state.editing && state.catalogEditable); }
  function itemsAll() { return ITEMS; }
  function applyItems(next) { setCatalog(next); }
  function cloneSub(s) { return { id: String(s.id), zh: s.zh || '', en: s.en || '' }; }
  function patchItem(no, fn) {
    return itemsAll().map(function (it) { return String(it.no) === String(no) ? fn(it) : it; });
  }
  /* withSubOf / migrateSubOf 与 MsPortal 同一套语义（照抄，不是重写）：
     归属只认 subOf[父分组]，boSub 退化成只读镜像。看板可同时属于多个分组
     （实测 no=11/12/13/18/36 同挂 FO + FLM），共用一个 boSub 会让两个分组互相串改。 */
  function withSubOf(it, gid, sid) {
    var c = {}, m = {};
    Object.keys(it).forEach(function (k) { c[k] = it[k]; });
    if (it.subOf && typeof it.subOf === 'object' && !Array.isArray(it.subOf)) {
      Object.keys(it.subOf).forEach(function (k) { m[k] = it.subOf[k]; });
    }
    /* ⚠️ BO View 这一维必须先归一：目录里可能还躺着旧 id（wireless/core）。
       不归一就直接写别的分组时，旧的坏值会被原样复制进新对象 ——
       一次「改 FO 归属」的保存会把 BO 那维的旧 id 一起固化下来，
       于是迁移永远做不干净（读的时候虽然能翻，但存回去的仍是旧值）。 */
    if (gid === 'BO View' && m[gid]) m[gid] = migrateBoSubOf(String(m[gid]), it.no);
    if (sid) m[gid] = sid; else delete m[gid];
    if (Object.keys(m).length) c.subOf = m; else delete c.subOf;
    var mirror = '';
    groupsOf(c).forEach(function (g) { if (!mirror && m[g]) mirror = m[g]; });
    if (mirror) c.boSub = mirror; else delete c.boSub;
    return c;
  }
  function migrateSubOf(items) {
    return (items || []).map(function (it) {
      if (!it || typeof it !== 'object') return it;
      var legacy = it.boSub ? String(it.boSub) : '';
      if (!legacy) return it;
      var has = it.subOf && typeof it.subOf === 'object' && !Array.isArray(it.subOf);
      var owner = groupsOf(it).filter(function (g) {
        return subGroupsOf(g).some(function (s) { return s.id === legacy; });
      })[0];
      if (!owner) return it;
      if (has && it.subOf[owner]) return it;
      var c = {}, m = {};
      Object.keys(it).forEach(function (k) { c[k] = it[k]; });
      if (has) Object.keys(it.subOf).forEach(function (k) { m[k] = it.subOf[k]; });
      m[owner] = legacy;
      c.subOf = m;
      return c;
    });
  }
  /* ---- BO 子分组口径迁移（2026-09-27 加）----
     把历史归属里的旧 BO 子分组 id（wireless / core / ip）改写为新的
     专业域 id（ran / ip / mw / cn / ocs）。三层判定，顺序不能反：

       ① SUB_KEEP_REMAP 点名 —— 优先级最高。旧口径本身分错了（微波 MW 与
          IP 丢包都躺在 wireless 桶里），按桶名映射只会把错误继续带下去，
          所以这几条按看板号直接给定论；
       ② SUB_MIGRATE 按桶名映射 —— 剩下的条目里，旧桶名与新域是同义的
          （wireless→ran、core→cn、ip→ip）；
       ③ 新 id 原样保留 —— 目录里已经是新口径的（用过编辑态改过归属的），
          不做任何加工，这是幂等的关键：本函数会被反复调用。

     ⚠️ 只在 BO View 这一维上迁移：别的分组将来也可能有自己的子分组，
     它们的 id 不该被这张 BO 专用表改写。 */
  function migrateBoSubOf(sid, no) {
    var keep = SUB_KEEP_REMAP[String(no)];
    if (keep) return keep;
    var subs = subGroupsOf('BO View');
    if (subs.some(function (s) { return s.id === sid; })) return sid;   /* ③ 已是新 id */
    return SUB_MIGRATE[sid] || sid;                                     /* ② 旧桶名映射 */
  }
  /* 迁移后仍指向不存在的子分组 = 这条归属是坏的（比如旧目录里写了个
     早已删掉的子分组）：返回空串让它落进「未归类」兜底桶 ——
     宁可单列也不丢条目，且不会在页签上凭空多出一个点不开的桶。 */
  function boSubValid(sid) {
    return subGroupsOf('BO View').some(function (s) { return s.id === sid; }) ? sid : '';
  }
  function normOrderMap(v) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
    var out = {};
    Object.keys(v).forEach(function (gid) {
      if (!Array.isArray(v[gid])) return;
      var seq = [];
      v[gid].forEach(function (x) {
        var n = parseInt(x, 10);
        if (!isNaN(n) && n >= 0 && seq.indexOf(n) === -1) seq.push(n);   /* 去重：indexOf 只认第一个 */
      });
      out[gid] = seq;
    });
    return out;
  }
  /* ---- 拓扑地图页签改名（2026-09-23 加）----
     服务端 catalog.tabLabels 只存 {page:{zh,en}}，**不做语言回落**：某个语言缺值就当
     没配、用 i18n 字典里的内置文案。与后端 _normalize_tab_labels 的语义严格对齐 ——
     两边不一致会出现「后端存了 A、前端显示成 B」这种最难查的错位。 */
  function normTabLabels(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    var out = {};
    DATA.RENAME_KEYS.forEach(function (page) {
      var v = raw[page];
      if (!v || typeof v !== 'object') return;
      var zh = typeof v.zh === 'string' ? v.zh.trim() : '';
      var en = typeof v.en === 'string' ? v.en.trim() : '';
      if (!zh && !en) return;               /* 全空 = 没配（后端也会丢弃空壳） */
      out[page] = { zh: zh, en: en };
    });
    return out;
  }
  /** 页签显示名：目录里配过就用它，否则回落 i18n 字典的内置文案（t(key)）。
      2026-09-29：本栏恢复成 gis + mwRealTime 两个页签后重新启用
      （当天中途曾随"单页化"删掉过一次）。 */
  function tabLabelOf(page, key) {
    var v = state.tabLabels && state.tabLabels[page];
    if (v) {
      var s = state.lang === 'en' ? (v.en || '') : (v.zh || '');
      if (s) return s;                      /* 只认当前语言的值，缺就回落内置 */
    }
    return t(key);
  }
  /* 本栏标题 / 副标题（2026-09-23 纳入可改名）。
     ⚠️ olbrportal 的用法与 MsPortal **相反**：这里是 title=中文、sub=英文
     （'map.title' 中文值「利比里亚网络拓扑全景」、英文值 "Central Liberia Regional
     Topology"；'map.sub' 是 "Network panorama"）。所以：
       · 上方标题 ← 中文名（zh）
       · 下方副标题 ← 英文名（en）
     后端只存"中/英"两个值，由各前端决定谁显示在上 —— 改这里之前先确认没把上下搞反。
     ⚠️ 回落用 tIn 而不是 t：t 按**界面当前语言**取值，而改名浮层是同时给出
     zh / en 两个框的 —— 用 t 会把当前语言的值同时填进两个框（中文界面下英文框
     也是中文），用户一点保存就把英文名覆盖成中文。tIn 按"这份数据属于哪个语言"取。
     当前 map.title / map.sub 在中英两栏里值相同（都是 'GIS Map'，见 olbr-data.js:125/528），
     所以这个缺陷眼下看不出来；但两栏文案一旦不同就会显形，故提前修掉。 */
  function headTitleText() {
    var v = state.tabLabels && state.tabLabels[DATA.RENAME_HEAD];
    if (v && v.zh) return v.zh;
    return tIn('zh', 'map.title');
  }
  function headSubText() {
    var v = state.tabLabels && state.tabLabels[DATA.RENAME_HEAD];
    if (v && v.en) return v.en;
    return tIn('en', 'map.sub');
  }
  function putCatalog(cat) {    return fetch('/api/portal-catalog', {
      method: 'PUT', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ catalog: cat })
    }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      /* 403 的原文是「仅本机可修改」，直接抛给用户体验太差；这里换成能看懂的一句话。
         非 JSON 同理 —— my_app 的 catch-all 会把没注册的路径回成 SPA 的 index.html。 */
      if (r.status === 403) throw new Error(t('edit.readonly'));
      if (!r.ok || ct.indexOf('json') === -1) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  /* 乐观改 → 立刻重绘 → PUT；失败整批回滚，画面不会停在「看起来存好了」的状态。 */
  function commit(mutate, msg) {
    if (state.saving) { toast(t('edit.busy')); return; }
    if (!state.catalogEditable) { toast(t('edit.readonly')); return; }
    var snap = { items: itemsAll(), subs: state.subGroups, order: state.order, groups: state.groups, labels: state.tabLabels };
    mutate();
    renderCatalog();
    var cat = { items: itemsAll() };
    if (state.subGroups) cat.subGroups = state.subGroups;
    /* order 必须跟着**每一次** PUT 走：后端是整体替换，不带就是删掉，
       否则「改一个子分组名字」会顺手把所有人的拖拽顺序抹干净。 */
    if (state.order && Object.keys(state.order).length) cat.order = state.order;
    /* groups 同理 —— 一级分组定义也是整份替换；后端只在非空时落键，
       所以「和内置一模一样」时也照发不误（多发一次不会改变出厂语义）。 */
    var sentGroups = !!(state.groups && state.groups.length);
    if (sentGroups) cat.groups = state.groups;
    /* 地图页签名覆盖（2026-09-23 加）：与 order/groups 同理必须**每次都带** ——
       后端是整体替换，不带就等于删掉，「改一个子分组名字」会把页签名还原成内置文案。 */
    var sentLabels = !!(state.tabLabels && Object.keys(state.tabLabels).length);
    if (sentLabels) cat.tabLabels = state.tabLabels;
    var sentSubs = !!state.subGroups, sentOrder = !!(cat.order && Object.keys(cat.order).length);
    state.saving = true; syncEditBtn();
    putCatalog(cat).then(function (d) {
      state.saving = false;
      var c = d && d.catalog;
      if (c && Array.isArray(c.items) && c.items.length) {
        state.catalogEditable = !!(d.editable == null || d.editable);
        state.subGroups = normalizeSubMap(c.subGroups);
        state.order = normOrderMap(c.order);
        if (Array.isArray(c.groups) && c.groups.length) state.groups = normalizeGroupList(c.groups);
        state.tabLabels = normTabLabels(c.tabLabels);
        applyItems(migrateSubOf(c.items));
      }
      var lost = [];
      /* 后端若是旧版（改了 portal_catalog.py 但没重启），会静默不认识 subGroups / order / groups
         并把键丢掉 → 提示「已保存」而刷新后变回去，属于最难查的假成功，必须说出来。 */
      if (sentSubs && !state.subGroups) lost.push(t('edit.kSub'));
      if (sentOrder && !(state.order && Object.keys(state.order).length)) lost.push(t('edit.kOrder'));
      if (sentGroups && !(c && Array.isArray(c.groups) && c.groups.length)) lost.push(t('edit.kGroups'));
      if (sentLabels && !(state.tabLabels && Object.keys(state.tabLabels).length)) lost.push(t('edit.kLabels'));
      toast(msg + ' · ' + (lost.length ? tf('edit.lost', { k: lost.join(' / ') }) : t('edit.saved')));
      renderCatalog();
    }).catch(function (e) {
      state.saving = false; rollback(snap); renderCatalog();
      toast(tf('edit.err', { e: (e && e.message) || e }));
    }).then(function () { state.saving = false; syncEditBtn(); });
  }
  function rollback(snap) {
    applyItems(snap.items); state.subGroups = snap.subs; state.order = snap.order;
    state.groups = snap.groups; state.tabLabels = snap.labels;
  }

  /* ---- 拖拽排序：order[父分组] = [看板编号,…]，数组顺序即展示顺序 ---- */
  /* 为什么不是给每个看板加一个 order 数字：一张卡可以同时挂在多个分组，
     看板级 order 会让「在 A 组拖到第 1 位」把 B 组里的同一张卡也顶到第 1 位 ——
     与 subOf 当初要解决的串改是同一类问题。 */
  function groupSeq(gid) {
    /* 刻意用**全量**（不筛、不过权限）：只按筛过的子集存顺序表的话，
       没被筛中的看板会因为「不在表里」被一律甩到末尾，一次带搜索的拖动就把整块打乱。 */
    return itemsAll().filter(function (it) { return inGroup(it, gid); })
      .sort(sorter(gid)).map(function (it) { return it.no; });
  }
  function moveOrder(gid, dragNo, targetNo, before) {
    if (!gid || dragNo === targetNo) return;
    var seq = groupSeq(gid), from = seq.indexOf(dragNo);
    if (from === -1) return;
    seq.splice(from, 1);
    var to = seq.indexOf(targetNo);
    if (to === -1) return;
    seq.splice(before ? to : to + 1, 0, dragNo);
    commit(function () { var o = shallow(state.order); o[gid] = seq; state.order = o; }, t('edit.orderOk'));
  }
  function resetOrder(gid) {
    /* 空数组 = 显式「这个分组没有自定义顺序」，与「键不存在」语义不同（后端两者都能存），
       所以这里落 [] 而不是删键。 */
    commit(function () { var o = shallow(state.order); o[gid] = []; state.order = o; }, t('edit.orderReset'));
  }
  function shallow(o) { var r = {}; Object.keys(o || {}).forEach(function (k) { r[k] = o[k]; }); return r; }

  /* ---- 子分组：定义随目录落盘，数组顺序即展示顺序；id 建好就不改（归属存的是 id） ---- */
  function writeSubMap(gid, next) {
    var m = shallow(state.subGroups);
    Object.keys(state.subGroups || {}).forEach(function (k) { m[k] = (state.subGroups[k] || []).map(cloneSub); });
    m[gid] = next.map(cloneSub);
    state.subGroups = m;
  }
  function addSub(gid, zh, en) {
    zh = String(zh || '').trim(); en = String(en || '').trim();
    if (!zh && !en) { toast(t('edit.needName')); return; }
    /* id 直接取显示名（与 MsPortal 一致），因为归属里存的就是它。
       代价是 id 不可改：改 id 等于让已有归属指向不存在的子分组 —— 所以编辑态只开 zh/en。 */
    var id = en || zh;
    var subs = subGroupsOf(gid);
    if (subs.some(function (s) { return s.id.toLowerCase() === id.toLowerCase(); })) { toast(t('edit.dupName')); return; }
    commit(function () { writeSubMap(gid, subs.concat([{ id: id, zh: zh, en: en }])); }, t('edit.subAdded'));
  }
  function renameSub(gid, sid, zh, en) {
    zh = String(zh || '').trim(); en = String(en || '').trim();
    if (!zh && !en) { toast(t('edit.needName')); return; }
    commit(function () {
      writeSubMap(gid, subGroupsOf(gid).map(function (s) {
        return s.id === sid ? { id: s.id, zh: zh, en: en } : cloneSub(s);
      }));
    }, t('edit.subRenamed'));
  }
  function delSub(gid, sid) {
    var s = subGroupsOf(gid).filter(function (x) { return x.id === sid; })[0];
    if (!s) return;
    if (!window.confirm(tf('edit.delConfirm', { n: subName(s) }))) return;
    commit(function () {
      writeSubMap(gid, subGroupsOf(gid).filter(function (x) { return x.id !== sid; }));
      /* 指向已删定义的归属一律清空：前端本来也会落到「未归类」，
         但留着脏 id 会让下一次 rename 之后又神秘地匹配上，不如当场洗干净。 */
      applyItems(patchAllSubOf(gid, function (v) { return v === sid ? '' : v; }));
    }, t('edit.subDeleted'));
  }
  function patchAllSubOf(gid, fn) {
    return itemsAll().map(function (it) {
      var v = subOfItem(it, gid), nv = fn(v);
      return nv === v ? it : withSubOf(it, gid, nv);
    });
  }
  function assignSub(no, gid, sid) {
    if (!gid) return;
    var cur = '';
    itemsAll().forEach(function (it) { if (String(it.no) === String(no)) cur = subOfItem(it, gid); });
    if (cur === (sid || '')) return;                        /* 原地拖回：不产生写请求 */
    commit(function () { applyItems(patchItem(no, function (it) { return withSubOf(it, gid, sid); })); }, t('edit.subMoved'));
  }
  /* ---- 分组归属：item.groups 是服务端字段，勾一次存一次 ---- */
  function setGroups(no, gids) {
    commit(function () {
      applyItems(patchItem(no, function (it) {
        var c = /** @type {Record<string, any>} */ ({}), before = groupsOf(it), gone = [];
        Object.keys(it).forEach(function (k) { c[k] = it[k]; });
        c.groups = gids;
        before.forEach(function (g) { if (gids.indexOf(g) === -1) gone.push(g); });
        /* 移出某组时把该组的二级归属一起清掉：留着指向不存在分组的格子不会显示，
           但下一次把看板加回来时会「神秘地」恢复旧归属，说清楚比留着好。 */
        gone.forEach(function (g) { c = withSubOf(c, g, ''); });
        return c;
      }));
    }, t('edit.grpOk'));
  }

  /* ---- 一级分组定义：2026-09-22 起随目录一起落盘，改名/新增/删除都是全局的 ---- */
  /* id 一旦定下就不再改：item.groups、order 的键、subGroups 的键全都按 id 引用。
     改名只动 zh/en/subZh/subEn，所以一处改名不会把三处引用打断（与子分组同一规则）。 */
  function normalizeGroupList(list) {
    var out = [], seen = {};
    (Array.isArray(list) ? list : []).forEach(function (g) {
      if (!g || typeof g !== 'object') return;
      var zh = String(g.zh || '').trim(), en = String(g.en || '').trim();
      var id = String(g.id || en || zh).trim();
      if (!id || seen[id]) return;
      seen[id] = 1;
      out.push({ id: id, zh: zh || id, en: en || id,
        subZh: String(g.subZh || '').trim(), subEn: String(g.subEn || '').trim(),
        style: String(g.style || '').trim() });
    });
    return out;
  }
  function groupDefOf(gid) {
    return state.groups.filter(function (x) { return x.id === gid; })[0] || { id: gid, zh: gid, en: gid, subZh: '', subEn: '', style: '' };
  }
  function isBuiltinGroup(gid) {
    return (D.groups || []).some(function (g) { return g.id === gid; });
  }
  function renameGroup(gid, patch) {
    var next = state.groups.map(function (g) {
      if (g.id !== gid) return g;
      var c = {}; Object.keys(g).forEach(function (k) { c[k] = g[k]; });
      ['zh', 'en', 'subZh', 'subEn'].forEach(function (k) {
        if (patch[k] != null) c[k] = String(patch[k]).trim();
      });
      /* 中英文名都清空等于把分组变成无名，界面上会出现一个空白页签 —— 回落用 id */
      if (!c.zh) c.zh = gid; if (!c.en) c.en = gid;
      return c;
    });
    commit(function () { state.groups = next; }, t('edit.grpRenamed'));
  }
  /* 拓扑地图页签改名（2026-09-23 加）。写的是服务端共享目录 catalog.tabLabels，
     所有人刷新都能看到 —— 与分组改名同一个语义层级。 */
  function renameTab(page, zh, en) {
    if (DATA.RENAME_KEYS.indexOf(page) === -1) return;
    zh = String(zh || '').trim(); en = String(en || '').trim();
    var next = {};
    Object.keys(state.tabLabels || {}).forEach(function (k) { next[k] = state.tabLabels[k]; });
    /* 中英文都清空 = 恢复内置文案（而不是把页签变成空白）。
       与后端「全空对象直接丢弃」的语义一致，这样"清空"是一个可用的还原动作。 */
    if (!zh && !en) delete next[page];
    else next[page] = { zh: zh, en: en };
    commit(function () { state.tabLabels = Object.keys(next).length ? next : null; },
      t('edit.maptabRenamed'));
  }
  function addGroup(zh, en) {
    zh = String(zh || '').trim(); en = String(en || '').trim();
    var id = en || zh;
    if (!id) { toast(t('edit.grpNeedName')); return; }
    if (state.groups.some(function (g) { return g.id === id; })) { toast(t('edit.grpDup')); return; }
    var next = state.groups.concat([{ id: id, zh: zh || id, en: en || id, subZh: '', subEn: '', style: 'card' }]);
    /* 不切 state.viewTab：那是 L1 页签面板的选中态，本页没有面板。
       新分组只进目录（六张入口卡是固定名单，不会因此多一列），
       要把它挂到某个已有列里，用卡片的「分组」按钮勾选即可。 */
    commit(function () { state.groups = next; state.viewSub = ''; }, t('edit.grpAdded'));
  }
  /* 删除一级分组比看起来危险：分组名只是标签，看板才是内容 —— 所以先把该分组从每张
     卡片的 groups 里摘掉，并且**先检查有没有人会因此无家可归**。

     ⚠️ 2026-09-28 改：原来只要有任何一张卡会因为这次删除变成零归属，就整批拒绝
     （edit.grpHomeless）。现在有了归档这条兜底路，改判据为"能不能立刻兜住"：
       · 卡片**还有别的分组** → 直接摘掉本组即可，与以前一致；
       · 卡片**只有本组**       → 摘掉的同时补上归档，不再拒绝。
     于是"删一个分组"不再可能把看板弄丢：要么它本来就有别处可去，要么进归档。
     归档分区自己（DATA.ARCHIVE）不允许删除（见下），否则既没有兜底、又回到老问题。 */
  function delGroup(gid) {
    if (!gid || isBuiltinGroup(gid)) { toast(t('edit.grpBuiltin')); return; }
    /* 归档是兜底分区：删掉它会让下面的补归档逻辑写进一个不存在的分组。
       与内置分组同样处理（报"只能改名不能删除"），而不是另外编一句文案。 */
    if (isArchiveGid(gid)) { toast(t('edit.grpBuiltin')); return; }
    /* 有没有卡片会因此掉进归档 —— 用来在确认框里说清后果，不是用来拦。 */
    var homeless = itemsAll().filter(function (it) {
      return groupsOf(it).length === 1 && inGroup(it, gid);
    });
    if (homeless.length) { toast(tf('edit.grpHomeless', { n: homeless.length })); }
    if (!window.confirm(tf('edit.grpDelConfirm', { n: gid }) + (homeless.length ? '\n\n' + tf('edit.archived', {}) : ''))) return;
    var nextGroups = state.groups.filter(function (g) { return g.id !== gid; });
    if (homeless.length) ensureArchiveGroup();
    var nextItems = itemsAll().map(function (it) {
      if (!inGroup(it, gid)) return it;
      var c = {}; Object.keys(it).forEach(function (k) { c[k] = it[k]; });
      c.groups = groupsOf(it).filter(function (g) { return g !== gid; });
      if (!c.groups.length) c.groups = [DATA.ARCHIVE];
      return withSubOf(c, gid, '');
    });
    var nextOrder = shallow(state.order); delete nextOrder[gid];
    var nextSubs = state.subGroups ? shallow(state.subGroups) : null;
    if (nextSubs) delete nextSubs[gid];
    commit(function () {
      state.groups = nextGroups; applyItems(nextItems);
      state.order = nextOrder; state.subGroups = nextSubs;
      if (state.viewTab === gid) { state.viewTab = ''; state.viewSub = ''; }
      /* 入口卡那一列也跟着清：分组都没了，v6Sub 里留着的选中 id 会一直
         假装「BO View 选了 MW」—— 分组重建后同名 id 可能已经不存在，
         而 v6SubBar 只在渲染时兜底，state 里的脏值会一直躺着。 */
      delete state.v6Sub[gid];
    }, t('edit.grpDeleted'));
  }

  /* ---- 看板标题：items.titleZh/titleEn 本来就是服务端字段，只是以前没有入口 ---- */
  /* 只收 http(s)。目录里的 url 最终会进 viewer 的 iframe src 与「新标签打开」的 <a href>，
     放行 javascript:/data: 等于给自己开一个 XSS 口子 —— 而这条目录是所有门户共用的。
     新增与改名**共用这一条判定**，不各写一份正则（两处规则分叉是这类校验最典型的腐烂方式）。 */
  function isHttpUrl(u) { return /^https?:\/\//i.test(String(u || '').trim()); }
  /* 改看板：名字与链接一起改（2026-09-26 起把 url 并进来）。
     原先链接**没有任何编辑入口** —— 想换一张看板打开什么，只能手改服务端 JSON。
     而卡片点下去的地址栏显示的是 /MsPortal/viewer.html?no=…&gid=…（vlink 硬编码的），
     真正的地址由 viewer 读本字段决定，所以「替换看板的链接」就是改这里。

     校验顺序：名字 → 非空 → http(s)。链接一律要求合法，不留「只改名不动链接」的后门 ——
     实测目录 54 条全部是 http(s)，放宽只会让非法值有路可走。 */
  function renameItem(no, zh, en, url) {
    zh = String(zh || '').trim(); en = String(en || '').trim(); url = String(url || '').trim();
    if (!zh && !en) { toast(t('edit.needTitle')); return; }
    if (!url) { toast(t('edit.itemNeedUrl')); return; }
    if (!isHttpUrl(url)) { toast(t('edit.itemBadUrl')); return; }
    commit(function () {
      applyItems(patchItem(no, function (it) {
        var c = {}; Object.keys(it).forEach(function (k) { c[k] = it[k]; });
        c.titleZh = zh; c.titleEn = en; c.url = url;
        return c;
      }));
    }, t('edit.titleOk'));
  }

  /* -------------------------------------- 看板条目本身的增删（2026-09-26） -- */
  /* 与上面「分组」三件事的区别：这里动的是 **条目本身**，不是它挂在哪个分组。

     ⚠️ 2026-09-28 改：原先只剩一个分组时直接拒绝并提示 edit.itemLastGrp
     （"这是它唯一的分组，移出后就没地方放了 —— 真要移除请用「删除看板」"）。
     用户读到的正是这句话。问题不在于拦得对不对，而在于**它没有给出路**：
     想"别让它出现在这个视图里"是合理诉求，而被指向的是不可逆的「删除看板」。

     现在改成：摘掉当前分组后若一个分组都不剩，就自动移入归档（Archived），
     并且仍然只做**一次** commit —— 摘归属与补归档必须在同一份 items 上完成。
     分成两次 commit 会在中间态产生"零归属条目"，而那个状态正是本项目
     一直要避免的（渲染不出来）。 */
  function dropItemFromGroup(no, gid) {
    var it = itemsAll().filter(function (x) { return String(x.no) === String(no); })[0];
    if (!it || !gid) return;
    if (!inGroup(it, gid)) return;
    /* 移出的是归档本身（在归档区点「移出本列」）没有任何去处，
       直接指路到归档行上的「取消归档」—— 那把按钮才有明确的落点。 */
    if (isArchiveGid(gid)) { toast(t('arch.unarchiveTip')); return; }
    var last = groupsOf(it).length <= 1;
    /* 归档区默认隐藏（见 renderArchive），所以"这次归档了"要在这里显式开闸：
       否则用户点完「移出本列」只看到卡消失，落点要等下次刷新才可能想起来找。
       只在 last 时开 —— 只有这一条路径真的会补进归档。 */
    if (last) state.recall = true;
    commit(function () {
      if (last) ensureArchiveGroup();
      applyItems(patchItem(no, function (x) {
        var c = {}; Object.keys(x).forEach(function (k) { c[k] = x[k]; });
        c.groups = groupsOf(x).filter(function (g) { return g !== gid; });
        /* 一个都不剩 = 刚从唯一分组移出：补上归档，绝不留下零归属条目。 */
        if (!c.groups.length) c.groups = [DATA.ARCHIVE];
        /* 子分组归属也要一起摘掉：留着会在「该分组 → 子分组」的映射里
           留下一个指向已不属于该组的条目的悬挂 key（与 delGroup 同一处理）。 */
        return withSubOf(c, gid, '');
      }));
    }, last ? t('edit.archived') : t('edit.itemDropped'));
  }
  /* 取消归档：把归档项放回一个**用户选定**的视图。
     刻意不自动挑一个分组（比如"第一个非归档组"）：那等于替用户决定它属于哪个业务视图，
     而归档项之所以被移出，往往就是因为哪个视图都不合适。落点必须由人来定。 */
  function unarchiveItem(no, gid) {
    var it = itemsAll().filter(function (x) { return String(x.no) === String(no); })[0];
    if (!it || !gid || isArchiveGid(gid)) return;
    commit(function () {
      applyItems(patchItem(no, function (x) {
        var c = {}; Object.keys(x).forEach(function (k) { c[k] = x[k]; });
        var next = groupsOf(x).filter(function (g) { return !isArchiveGid(g); });
        if (next.indexOf(gid) === -1) next.push(gid);
        c.groups = next;
        return c;
      }));
    }, t('edit.grpOk'));
  }
  /* 彻底删除条目。⚠️ 这是本页唯一不可逆的操作，且改的是所有人共享的目录
     （/olbrportal/ 与 MsPortal 都读同一份），所以：
       · 二次确认里写清看板名 + 「所有人可见、无法撤销」；
       · 顺手把 no 从**所有** order[gid] 里摘掉 —— 否则会留下一个指向不存在看板的
         悬挂编号，下次 sorter() 按它排位时那张卡的位置就成了空洞；
       · 不回收 no（不复用已删编号）：历史链接与别人的 order 数组都可能还记着它，
         复用会让旧编号指向一张**别的**看板。新编号一律取 max(no)+1。 */
  function deleteItem(no) {
    var it = itemsAll().filter(function (x) { return String(x.no) === String(no); })[0];
    if (!it) return;
    if (!window.confirm(tf('edit.itemDelConfirm', { n: titleOf(it) }))) return;
    var nextOrder = {};
    Object.keys(state.order || {}).forEach(function (g) {
      nextOrder[g] = (state.order[g] || []).filter(function (n) { return String(n) !== String(no); });
    });
    commit(function () {
      applyItems(itemsAll().filter(function (x) { return String(x.no) !== String(no); }));
      state.order = nextOrder;
    }, t('edit.itemDeleted'));
  }
  /* 新增看板：照一个已有看板当模板（用户选定的口径）。
     模板值继承 icon / platform / descZh / descEn / owner / dept / tags / status / freq，
     用户只填名字与链接 —— 从零填十几个字段没人愿意填，而这些字段又都有合理默认。 */
  function addItemFromTemplate(tplNo, gid, zh, en, url) {
    zh = String(zh || '').trim(); en = String(en || '').trim(); url = String(url || '').trim();
    if (!zh && !en) { toast(t('edit.needTitle')); return; }
    if (!url) { toast(t('edit.itemNeedUrl')); return; }
    if (!isHttpUrl(url)) { toast(t('edit.itemBadUrl')); return; }
    var tpl = itemsAll().filter(function (x) { return String(x.no) === String(tplNo); })[0];
    if (!tpl) return;
    var maxNo = itemsAll().reduce(function (m, x) { return Math.max(m, parseInt(x.no, 10) || 0); }, 0);
    var c = {}; Object.keys(tpl).forEach(function (k) { c[k] = tpl[k]; });
    /* 从模板复制来的字段里，这几个必须重写 —— 照抄会让新卡片顶着模板的身份：
       no 要唯一、clicks 归零（它渲染成热度）、groups 只进本列、
       subOf/qc 是模板在别的分组里的归属与下钻配置，与本列无关。
       custom 同理：那是「用户自建」标记，新条目算自建，但保留模板的值没有意义。 */
    c.no = maxNo + 1;
    c.titleZh = zh || en; c.titleEn = en || zh;
    c.url = url;
    c.groups = [gid];
    c.clicks = 0;
    delete c.subOf; delete c.boSub; delete c.qc; delete c.custom;
    commit(function () { applyItems(itemsAll().concat([c])); }, t('edit.itemAdded'));
  }

  /* ------------------------------------------------ 编辑态：拖拽 / 浮层 -- */
  /* 拖拽有三种落点，语义互不重叠：
       卡片 → 卡片   = 同一分组内改顺序（order[gid]）
       卡片 → 子分组 = 改二级归属（item.subOf[gid]）
       列   → 列     = 改六张入口卡的**分组顺序**（catalog.groups，2026-10-07 加）
     刻意**不支持**「卡片 → 另一个页签」来改分组归属：那与浮层里的勾选是同一件事，
     两处入口只会让人猜哪处才是真的（MsPortal 也是同一个判断：跨区块拖一律不落）。

     ⚠️ 列的拖动与卡片的拖动**必须在 dragstart 处就分流**，不能共用 dragNo：
     卡片用 dragNo（数字看板号）+ dragGid，列用 dragCol（分组 id），
     两者的判据、落点高亮类、提交函数全不一样。混用一个变量的话，
     「从列里拖出一张卡」会同时被当成一次列拖动（列也是 draggable，
     dragstart 会从卡片冒泡到列上，两次赋值互相覆盖）。 */
  var dragEl = null, dragNo = null, dragGid = '', hotEl = null, hotCls = '', noClickAt = 0;
  var dragCol = '', dragColEl = null;   /* 正在拖的**列**；空 = 当前拖的是卡片 */
  function hotReset() { if (hotEl) hotEl.classList.remove(hotCls); hotEl = null; hotCls = ''; }
  function hotSet(el, cls) {
    if (hotEl === el && hotCls === cls) return;
    hotReset(); hotEl = el; hotCls = cls; el.classList.add(cls);
  }
  function dragReset() {
    if (dragEl) dragEl.classList.remove('is-drag');
    /* 列的压暗类与卡片的**分开**（见 dragstart 里的说明），所以这里也要分开清 */
    if (dragColEl) dragColEl.classList.remove('is-drag-col');
    hotReset();
    dragEl = null; dragNo = null; dragGid = ''; dragCol = ''; dragColEl = null;
    noClickAt = Date.now();
  }
  function cardOf(e) { return e.target && e.target.closest ? e.target.closest('a.card.is-ed') : null; }
  function subOf(e) { return e.target && e.target.closest ? e.target.closest('.subv[data-drop-sub]') : null; }
  /* 可拖的列。只认编辑态渲染出来的那一层（.is-col-ed）——
     只读态的 div.v6 上既没有 data-col-gid 也没有这个类，不会误命中。 */
  function colOf(e) { return e.target && e.target.closest ? e.target.closest('.v6.is-col-ed[data-col-gid]') : null; }
  /* 指针落在卡片的哪半边决定插到它前面还是后面：网格一行有好几张卡，
     只看上下会把「插到左边那张之前」判成插到后面，所以按主轴（|dx| 与 |dy| 谁大）判。 */
  function sideOf(card, e) {
    var r = card.getBoundingClientRect();
    var dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
    if (Math.abs(dx) > Math.abs(dy)) return dx < 0;
    return dy < 0;
  }
  function bindEdit() {
    document.addEventListener('dragstart', function (e) {
      if (!canEdit()) return;
      /* 先判卡片：卡片是列的**后代**，dragstart 会继续冒泡到列上。
         若先判列，从列里拖一张卡会被当成拖整列（用户想排卡片顺序，
         结果整列跟着走）—— 这是本次改动最容易踩的一处，顺序不能反。 */
      var c = cardOf(e);
      if (c) {
        dragNo = parseInt(c.getAttribute('data-no'), 10);
        dragGid = c.getAttribute('data-gid') || '';
        if (isNaN(dragNo)) return;
        dragEl = c; c.classList.add('is-drag');
        try {
          e.dataTransfer.setData('text/plain', String(dragNo));
          e.dataTransfer.effectAllowed = 'move';
        } catch (err) { /* 个别环境不允许设 dataTransfer，不影响排序本身 */ }
        return;
      }
      /* 卡片没命中才看列：此时拖的是**整列**（改六张入口卡的排列顺序）。
         ⚠️ 拖着卡片经过列头时不会走到这里（上面已经 return），
         所以「拖卡片」与「拖列」不会互相抢。 */
      var col = colOf(e);
      if (!col) return;
      dragCol = col.getAttribute('data-col-gid') || '';
      if (!dragCol) return;
      /* 列用**自己的**压暗类，不塞进 dragEl：dragEl 是 cardOf 那套的状态，
         共用会让 dragReset 在 `dragEl.classList.remove('is-drag')` 上
         把整列一起改掉。分开之后读代码的人也一眼分得清拖的是哪种。 */
      dragColEl = col; col.classList.add('is-drag-col');
      try {
        e.dataTransfer.setData('text/plain', dragCol);
        e.dataTransfer.effectAllowed = 'move';
      } catch (err) { /* 同上，不影响排序本身 */ }
    });
    document.addEventListener('dragover', function (e) {
      /* ---- 分支一：正在拖列，落点只能是别的列 ---- */
      if (dragCol) {
        var t0 = colOf(e);
        if (!t0 || t0.getAttribute('data-col-gid') === dragCol) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        hotSet(t0, v6BeforeOf(t0, e) ? 'is-col-A' : 'is-col-B');
        return;
      }
      if (dragNo === null) return;
      var s = subOf(e);
      /* 只接「当前面板自己的」子分组条：从 L0 的 SP View 卡片拖过来不算归类 */
      if (s && dragGid === state.viewTab) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        hotSet(s, 'is-hot'); return;
      }
      var c = cardOf(e);
      if (!c || c.getAttribute('data-gid') !== dragGid) return;
      if (parseInt(c.getAttribute('data-no'), 10) === dragNo) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
      hotSet(c, sideOf(c, e) ? 'is-in-A' : 'is-in-B');
    });
    document.addEventListener('drop', function (e) {
      /* ---- 分支一：落列（改六张入口卡的分组顺序）----
         先算好目标位置再 dragReset()：dragReset 会清掉 hotEl/hotCls，
         反过来先 reset 就读不到"插到前面还是后面"了（卡片那一支也是这个顺序）。 */
      if (dragCol) {
        var t1 = colOf(e);
        if (!t1 || t1.getAttribute('data-col-gid') === dragCol) { dragReset(); return; }
        e.preventDefault();
        var from = dragCol;
        var to = t1.getAttribute('data-col-gid');
        var before = !!(hotEl === t1 && hotCls === 'is-col-A');
        dragReset();
        moveGroupOrder(from, to, before);
        return;
      }
      if (dragNo === null) return;
      var s = subOf(e);
      if (s && dragGid === state.viewTab) {
        e.preventDefault();
        var sid = s.getAttribute('data-drop-sub') || '';
        var gid = dragGid, no = dragNo;
        dragReset();
        assignSub(no, gid, sid);
        return;
      }
      var c = cardOf(e);
      if (!c || c.getAttribute('data-gid') !== dragGid) return;
      e.preventDefault();
      var g = dragGid, dn = dragNo, tn = parseInt(c.getAttribute('data-no'), 10);
      var before = !!(hotEl === c && hotCls === 'is-in-A');
      dragReset();
      moveOrder(g, dn, tn, before);
    });
    document.addEventListener('dragend', dragReset);
    /* 拖完那一下浏览器一般不会补 click，但 Firefox 系会 —— 不拦就会顺手开一个查看器标签。 */
    document.addEventListener('click', /** @param {Event & {target: Element}} e */ function (e) {
      if (Date.now() - noClickAt > 250) return;
      var c = e.target.closest && e.target.closest('a.card');
      if (c) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    /* 编辑模式开关（只有 editable 的会话才看得到这颗按钮） */
    $('#editBtn').addEventListener('click', function () { setEditing(!state.editing); });
    $('#editBar').addEventListener('click', /** @param {Event & {target: Element}} e */ function (e) {
      if (e.target.closest('[data-act="edit-leave"]')) setEditing(false);
    });
    /* v1：#views 与 #l0 的 onEditClick / keydown 两处委托随那两块容器一起去掉了
       （卡片没了，委托也就没有对象；onEditClick 本身保留，见 setEditing 上方的说明）。
       $() 在元素不存在时返回 null，直接绑会抛 "Cannot read properties of null"，
       所以这里是**删除**而不是保留。 */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (state.popForm) closeForm();
      else if (state.grpFor !== null) closeGrp();
    });
    document.addEventListener('mousedown', /** @param {Event & {target: Element}} e */ function (e) {
      if (!e.target.closest) return;
      /* ⚠️ 这份"点它不算点外面"的名单必须列全所有会 openForm 的触发点，
         否则 mousedown 先 closeForm()、紧接着 click 又 openForm()：
         同一个元素上先关后开，表现为浮层闪一下，且第二次点变成"切换关闭"。
         2026-09-23 加页签/标题改名时漏了后两个选择器（.tab 与 [data-act=map-head]），
         症状是点标题浮层一闪、点同一个页签第二次不弹。
         ⚠️ 2026-09-29：页签条（.tab）当天中途曾随「本栏只内嵌一页地图」删掉、
         同日恢复两页时加回，所以 **[data-map] 选择器也必须一起回来** ——
         编辑态下点页签是"改这个页签的名字"，它同样会 openForm，漏掉它就会
         退回上面那个"点同一个页签第二次不弹 / 浮层一闪"的老毛病。
         **[data-act="map-head"] 也必须留着** —— 地图标题改名的铅笔按钮
         仍在 mapHeadHtml 里渲染，漏掉它同样会一闪。 */
      if (state.popForm && !e.target.closest('#editPop') &&
          !e.target.closest('[data-act="grp-edit"],[data-act="grp-add"],[data-act="title"],' +
                            '[data-act="map-head"],[data-map]')) closeForm();
      if (state.grpFor !== null && !e.target.closest('#grpPop') && !e.target.closest('[data-act="grp"]')) closeGrp();
    });
  }
  function onEditClick(/** @type {Event & {target: Element}} */ e) {
    var b = e.target.closest ? e.target.closest('[data-act]') : null;
    if (!b) return;
    var act = b.getAttribute('data-act'), gid = b.getAttribute('data-gid') || '';
    var sid = b.getAttribute('data-subx') || '';
    if (act === 'grp') { e.preventDefault(); e.stopPropagation(); openGrp(b); return; }
    if (!canEdit()) return;
    /** @type {any} */ var row, zh, en;
    if (act === 'grp-edit') { openForm('grp', gid, b); }
    else if (act === 'grp-add') { openForm('grpadd', '', b); }
    else if (act === 'title') { e.preventDefault(); e.stopPropagation(); openForm('title', b.getAttribute('data-no'), b); }
    else if (act === 'rst-order') { resetOrder(gid); }
    /* 看板条目本身的增删（2026-09-26）。
       这两颗也在 <a> 里面，同样要拦默认行为，否则点「删除」会顺手开一个新标签。 */
    else if (act === 'item-drop') {
      e.preventDefault(); e.stopPropagation();
      dropItemFromGroup(b.getAttribute('data-no'), gid);
    }
    else if (act === 'item-del') {
      e.preventDefault(); e.stopPropagation();
      deleteItem(b.getAttribute('data-no'));
    }
    /* 新增看板：先开「选模板」浮层（不是直接开表单）—— 模板决定了表单里
       要继承哪些字段，没有模板就没法填表。 */
    else if (act === 'item-add') { e.preventDefault(); e.stopPropagation(); openTplPick(gid, b); }
    /* v1：这两支原本调 renderViews()（重画 L1 面板里的子分组行），函数已随面板删除。
       改调 renderCatalog() —— 它做的是「目录变了，把看得懂目录的几块重画一遍」，
       语义正确且不碰地图 iframe；万一以后恢复编辑模式，这里也是对的落点。 */
    else if (act === 'sub-re') { state.subEdit = sid; renderCatalog(); }
    else if (act === 'sub-no') { state.subEdit = ''; renderCatalog(); }
    else if (act === 'sub-ok') {
      row = b.closest('.subv');
      zh = row.querySelector('[data-ren="zh"]').value;
      en = row.querySelector('[data-ren="en"]').value;
      /* 先退出改名态再提交：commit 里会重绘，改名框还留着的话会看见「保存完了输入框还在」 */
      state.subEdit = '';
      renameSub(gid, sid, zh, en);
    } else if (act === 'sub-del') { state.subEdit = ''; delSub(gid, sid); }
    else if (act === 'sub-add') {
      row = b.closest('.sub-add');
      zh = row.querySelector('[data-new="zh"]'); en = row.querySelector('[data-new="en"]');
      addSub(gid, zh.value, en.value);
      zh.value = ''; en.value = '';
    }
  }

  /* 分组归属浮层：勾一次存一次（没有「保存」按钮 —— 与其余编辑保持同一口径）。
     用 fixed 定位贴在卡片旁边而不是 modal：改归属时还得看见卡片本身，遮罩会把上下文全挡住。 */
  function grpGids() {
    var out = DATA.T0.concat(DATA.T1, DATA.T2), seen = {};
    out.forEach(function (g) { seen[g] = 1; });
    itemsAll().forEach(function (it) {
      groupsOf(it).forEach(function (g) { if (!seen[g]) { seen[g] = 1; out.push(g); } });
    });
    state.groups.forEach(function (g) { if (!seen[g.id]) { seen[g.id] = 1; out.push(g.id); } });
    return out;
  }
  function openGrp(btn) {
    var no = parseInt(btn.getAttribute('data-no'), 10), it = itemsAll().filter(function (x) { return x.no === no; })[0];
    if (!it) return;
    if (state.grpFor === no) { closeGrp(); return; }
    closeGrp();
    var cur = groupsOf(it), pop = $('#grpPop');
    pop.hidden = false;
    pop.innerHTML = '<div class="gp-hd"><b>' + esc(titleOf(it)) + '</b><span>' + esc(t('edit.groupsTip')) + '</span></div>' +
      '<div class="gp-list">' + grpGids().map(function (g) {
        /* ⚠️ 2026-09-29（用户要求）：归档那一项加计数标记。
           起因：归档区改成默认隐藏之后，「事后回头翻归档」在 v1 上就没有直接入口了
           （唯一显式的「取消归档」按钮在归档区里）—— 于是这里必须补上一个
           "看得见里面有几张" 的读数，否则用户根本不知道归档里有没有东西。

           为什么是计数而不是一句 "这里有东西"：
           Arch 是用户自己造的普通分组，下面这些也是 —— 在浮层里只给 Arch 单独发一条
           文字提示，等于把"它是特殊的"这件事泄露到 UI 上，而这个浮层的语义是
           "这张卡属于哪些分组"，不是"哪一组更特别"。计数不带立场：0 就是没有。

           ⚠️ 计数**不能跟着 state.recall 走**（第一版就是这么写错的，实测恒为空）。
           recall 的含义是"本次会话归档过"，而这里的用途恰恰相反：
           它要回答的是"**打开页面时**归档里有没有东西"—— 那必然发生在 recall 还是
           false 的时候。两处闸门的方向是反的，所以这里不做任何 recall 判断。
           —— 这正是"归档区默认隐藏"留下的那个洞的补丁：归档区自己藏起来了，
           这个计数是页面上唯一一处**在什么都不做的情况下**就能看见归档里有几张的地方。

           ⚠️ Arch 为空时**不渲染这个 0**：一个恒亮的 0 每天占着位置，
           反而让人以为那里有东西。CSS 用的是 :empty 而不是条件拼接 ——
           这样"0 不显示"这条规则只有一个真相源（拼串处只负责"有几张"）。
           实测线上目录：Arch 3 是常态，0 只在有人清空归档后出现。

           ⚠️ 刻意**不加**"Archived"这几个字的任何说明性文案：这个浮层是全站最容易
           漂移的一处 UI（MsPortal / olbrportal / v1 / v2 四份实现），并且 v1 与 v2
           是"并列共存的两份副本、改哪版只动哪版"。让文案保持中性，词典就不用跟着涨。 */
        /* ⚠️ 只有 Arch 这一项带计数（isArchiveGid(g) 不能省 —— 第一版漏了它，
           实测 10 个分组每个都顶着个 3）。其余分组的分量在各入口卡上
           已经写过一遍，这里再补一份只会让浮层变吵。 */
        var n = isArchiveGid(g) ? archivedItems().length : 0;
        return '<label class="gp-i"><input type="checkbox" data-g="' + esc(g) + '"' +
          (cur.indexOf(g) !== -1 ? ' checked' : '') + '><span>' + esc(gName(g)) + '</span>' +
          '<em class="gp-n" title="' + esc(tf('edit.archCount', { n: n })) + '">' + (n ? n : '') + '</em></label>';
      }).join('') + '</div>' +
      /* 专业域（子分组）区（2026-10-12 加，用户要求「如何手动指定专业」）：
         只对**该卡片当前所属、且定义了子分组**的分组渲染（当前仅 BO View）。
         单选（radio 语义）—— 一张卡在一个父分组下只属于一个专业域（subOf[gid] 是单值），
         这与顶层「分组」的多选不同（那张卡可同属多个分组）。
         ⚠️ 用 radio 而不是 checkbox：多选会得到"选择后互相覆盖"的假象。
         归属为空时给一个「未指定」项，让用户能把卡退回未归类。 */
      subDomainHtml(it, cur);
    placePop(pop, btn);
    state.grpFor = no;
    var first = pop.querySelector('input'); if (first) first.focus();
  }
  /* 「专业域」选择区：对 it 当前所属（groups 里）**有子分组定义**的每个父分组，
     渲染一组单选。当前只有 BO View 有子分组（RAN/IP/MW/CN/OCS），
     其余分组 subGroupsOf() 返回空数组，整段不输出。 */
  function subDomainHtml(it, curGroups) {
    var html = '';
    curGroups.forEach(function (g) {
      var subs = subGroupsOf(g);
      if (!subs.length) return;
      var cur = subOfItem(it, g);            /* 当前专业域 id（'' = 未指定） */
      html += '<div class="gp-sec"><div class="gp-sec-h">' + esc(t('edit.subDomain')) +
        '<span class="gp-sec-p">' + esc(gName(g)) + '</span></div>' +
        '<div class="gp-sub-list">' +
          '<label class="gp-i gp-i--sub"><input type="radio" name="sub-' + esc(g) + '"' +
            ' data-sub-for="' + esc(g) + '" data-sub-id=""' + (cur ? '' : ' checked') + '>' +
            '<span>' + esc(t('edit.subNone')) + '</span></label>' +
          subs.map(function (s) {
            return '<label class="gp-i gp-i--sub"><input type="radio" name="sub-' + esc(g) + '"' +
              ' data-sub-for="' + esc(g) + '" data-sub-id="' + esc(s.id) + '"' +
              (cur === s.id ? ' checked' : '') + '>' +
              '<span>' + esc(subName(s)) + '</span></label>';
          }).join('') +
        '</div></div>';
    });
    return html;
  }
  /* 贴在触发按钮旁边的 fixed 浮层：先归零再量，带着旧位置量出来的高度会跳；
     贴不下（靠近视口底部）就翻到按钮上方。两颗浮层共用这一套算法。 */
  function placePop(pop, btn) {
    var r = btn.getBoundingClientRect();
    pop.style.left = '0px'; pop.style.top = '0px';
    var pr = pop.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pr.width - 8)) + 'px';
    pop.style.top = (r.bottom + pr.height > window.innerHeight - 8
      ? Math.max(8, r.top - pr.height - 6) : r.bottom + 6) + 'px';
  }
  function closeGrp() {
    state.grpFor = null;
    /* tplPick 与 grpFor 共用这颗浮层，收起时两个状态都要清 ——
       只清一个的话，下次点「新增看板」会走到「浮层没开但状态还在」的岔路上。 */
    state.tplPick = null;
    var pop = $('#grpPop'); if (pop) { pop.hidden = true; pop.innerHTML = ''; }
  }
  function bindGrpPop() {
    var pop = $('#grpPop');
    pop.addEventListener('change', function (e) {
      /* 专业域单选（2026-10-12 加）：data-sub-for=父分组 id、data-sub-id=专业域 id（''=未指定）。
         走 withSubOf 写 subOf[gid]（单值），与顶层多选分组是两条独立的写入路径。 */
      var sb = e.target.closest ? e.target.closest('input[data-sub-for]') : null;
      if (sb && state.grpFor !== null) {
        var fg = sb.getAttribute('data-sub-for');
        var fv = sb.getAttribute('data-sub-id') || '';
        var itS = itemsAll().filter(function (x) { return x.no === state.grpFor; })[0];
        if (!itS) return;
        state.subEdit = '';
        commit(function () {
          applyItems(patchItem(state.grpFor, function (it) { return withSubOf(it, fg, fv); }));
        }, t('edit.subMoved'));
        renderGroupsPop();     /* 重画浮层：让勾选态跟随最新目录 */
        return;
      }
      var cb = e.target.closest ? e.target.closest('input[data-g]') : null;
      if (!cb || state.grpFor === null) return;
      var g = cb.getAttribute('data-g');
      var it = itemsAll().filter(function (x) { return x.no === state.grpFor; })[0];
      if (!it) return;
      var next = groupsOf(it).slice();
      var i = next.indexOf(g);
      if (cb.checked && i === -1) next.push(g);
      if (!cb.checked && i !== -1) next.splice(i, 1);
      /* 一张都不勾 = 看板从所有分组消失。2026-09-28 起不再直接拒绝，而是补上归档 ——
         与「移出本列」同一个落点，两条路径的兜底行为必须一致，否则
         "取消勾选最后一个"和"移出本列"会给出两种不同的结果，用户没法预期。 */
      if (!next.length) { next = [DATA.ARCHIVE]; ensureArchiveGroup(); state.recall = true; }
      setGroups(state.grpFor, next);
      renderGroupsPop();
    });
  }
  function renderGroupsPop() {
    var no = state.grpFor;
    closeGrp();
    var b = btnFor(no);
    if (b) openGrp(b);            /* 卡片还在当前面板里：把勾选状态按新目录重画一遍 */
  }
  function btnFor(no) { return document.querySelector('[data-act="grp"][data-no="' + no + '"]'); }

  /* ---- 新增看板的第一步：选模板 ------------------------------------------
     用 #grpPop 这颗浮层（同一种「贴按钮的 fixed 小面板」），不另开容器。
     目录里 55 条要能搜 —— 让它滚动找是不现实的。
     选定后 state.tplPick 记下模板 no，交给 openForm('itemadd') 填表；
     表单里那颗「换一个模板」再把状态倒回这一步。 */
  function openTplPick(gid, btn) {
    var pop = $('#grpPop'); if (!pop) return;
    closeForm();
    /* 先把可能开着的「分组归属」浮层收掉，再设 tplPick ——
       顺序不能反：closeGrp() 现在会顺手清掉 tplPick。 */
    closeGrp();
    state.tplPick = { gid: gid, tpl: null, q: '' };
    state.tplBtn = btn;
    paintTplPick();
  }
  function paintTplPick() {
    var pop = $('#grpPop'), st = state.tplPick;
    if (!pop || !st) return;
    var q = String(st.q || '').toLowerCase();
    var list = itemsAll().filter(function (it) {
      if (!q) return true;
      var hay = [it.titleZh, it.titleEn, '#' + it.no, it.url].join(' ').toLowerCase();
      return hay.indexOf(q) !== -1;
    });
    pop.hidden = false;
    pop.innerHTML = '<div class="gp-hd"><b>' + esc(t('edit.itemAdd')) + '</b><span>' + esc(t('edit.itemAddPick')) + '</span></div>' +
      '<div class="gp-search"><input type="search" id="tplQ" autocomplete="off" placeholder="' +
        esc(t('edit.itemAddSearch')) + '" value="' + esc(st.q || '') + '"></div>' +
      '<div class="gp-list gp-list--tpl">' + (list.length
        ? list.map(function (it) {
            return '<button type="button" class="gp-tpl" data-act="tpl-pick" data-no="' + esc(it.no) + '">' +
              '<i class="ph ph-' + esc(it.icon || 'app-window') + '" aria-hidden="true"></i>' +
              '<span class="gp-tpl-t">' + esc(titleOf(it)) + '</span>' +
              '<span class="gp-tpl-n">#' + esc(it.no) + '</span></button>';
          }).join('')
        : '<div class="gp-none">' + esc(t('v.emptyFilter')) + '</div>') + '</div>';
    if (state.tplBtn) placePop(pop, state.tplBtn);
    var inp = pop.querySelector('#tplQ');
    if (inp) {
      inp.focus();
      /* 光标放到末尾：重画后默认全选，下一键就把搜索词替掉，很难继续输入 */
      var n = inp.value.length;
      try { inp.setSelectionRange(n, n); } catch (err) { /* search 输入框在老浏览器上可能不支持，忽略 */ }
    }
  }
  /* 搜索框 input 事件（不是 click）单独绑一次：inp.value 边打边重画会把
     输入法组合状态打断，所以这里只改 state 再重画，重画时把光标放回末尾。 */
  function bindTplPick() {
    var pop = $('#grpPop'); if (!pop) return;
    /* 点一条模板 → 开 fill-in 表单。
       这条委托与 bindGrpPop 的 change 委托共存：那个只在勾选 input[data-g] 时动作，
       两者选择器不重叠，不会互相抢。 */
    pop.addEventListener('click', function (e) {
      if (!state.tplPick) return;
      var b = e.target.closest ? e.target.closest('[data-act="tpl-pick"]') : null;
      if (!b) return;
      e.preventDefault();
      var gid = state.tplPick.gid, no = b.getAttribute('data-no');
      /* 换模板时把上一轮已填的名字/链接带过去（backToTplPick 存的），
         没带过就用空 → openForm 里会按模板重新预填。 */
      state.tplPick = null;
      var btn = state.tplBtn;
      /* ⚠️ 目标分组必须在这一步就存下来：openForm 里会调 closeGrp()，
         而 closeGrp() 现在会连带清掉 tplPick —— 等到 submitForm 再回头读
         state.tplPick.gid 只会拿到 null，新增的看板就悄悄落到了第一列。 */
      state.addGid = gid;
      openForm('itemadd', no, btn);
      var carry = state.tplCarry; state.tplCarry = null;
      if (carry) {
        [['itemZh', carry.zh], ['itemEn', carry.en], ['itemUrl', carry.url]].forEach(function (p) {
          var el = $('#editPop').querySelector('[data-f="' + p[0] + '"]');
          if (el && p[1]) el.value = p[1];
        });
      }
    });
    pop.addEventListener('input', function (e) {
      if (!state.tplPick) return;
      var i = e.target.closest ? e.target.closest('#tplQ') : null;
      if (!i) return;
      state.tplPick.q = i.value;
      var sel = i.selectionStart;
      paintTplPick();
      var again = $('#grpPop').querySelector('#tplQ');
      if (again) { again.focus(); try { again.setSelectionRange(sel, sel); } catch (err) { /* 同上 */ } }
    });
  }

  /* ---- 第二颗浮层：改名类表单（一级分组改名 / 新增分组 / 看板改标题）----
     三者都是「两三个输入框 + 保存」，共用一套渲染与定位，省掉三套近似代码。
     仍然不是 modal：改的时候要看见被改的东西长什么样，遮罩会把上下文全挡住。 */
  var FORMS = {
    grp: { fields: ['zh', 'en', 'subZh', 'subEn'], tip: 'edit.grpEditTip', ok: 'edit.formSave' },
    grpadd: { fields: ['zh', 'en'], tip: 'edit.grpAddTip', ok: 'edit.formAdd' },
    /* title = 改看板（名字 + 链接）。字段沿用 itemUrl 而不是另起一个 url：
       submitForm 已经在收集 vi.itemUrl，i18n 的 edit.f.itemUrl / edit.fph.itemUrl 也已存在，
       两处共用一份字段名与一份文案，少一套重复定义。 */
    title: { fields: ['zh', 'en', 'itemUrl'], tip: 'edit.titleTip', ok: 'edit.formSave' },
    /* 拓扑地图页签名（2026-09-23 加）：字段与 title 相同，独立的 kind 只为让提示语
       说清「改的是地图页签」并走 renameTab 这条路（写的是 catalog.tabLabels）。 */
    maptab: { fields: ['zh', 'en'], tip: 'edit.maptabTip', ok: 'edit.formSave' },
    /* 新增看板（2026-09-26 加）：字段名带 item 前缀，与 title 的 zh/en 区分开 ——
       两者都是「中英文名」，复用 zh/en 会让 submitForm 分不清该走 renameItem
       还是 addItemFromTemplate，多一个前缀比多一层 if 清楚。 */
    itemadd: { fields: ['itemZh', 'itemEn', 'itemUrl'], tip: 'edit.itemAddTip', ok: 'edit.formAdd' }
  };
  function openForm(kind, id, btn) {
    var f = FORMS[kind], pop = $('#editPop');
    if (!f || !pop) return;
    if (state.popForm && state.popForm.kind === kind && String(state.popForm.id) === String(id)) { closeForm(); return; }
    closeForm(); closeGrp();
    var vals = {};
    if (kind === 'grp') { var g = groupDefOf(id); vals = { zh: g.zh, en: g.en, subZh: g.subZh, subEn: g.subEn }; }
    else if (kind === 'title') {
      var it = itemsAll().filter(function (x) { return String(x.no) === String(id); })[0];
      if (!it) return;
      /* 链接预填当前值：改链接时通常只想动其中一段（如 page=ttwo → page=v1_ttwo），
         空着会让人以为「链接本来就没有」，也容易被顺手覆盖掉带 token 的查询串。 */
      vals = { zh: it.titleZh || '', en: it.titleEn || '', itemUrl: it.url || '' };
    }
    /* 新增看板：预填模板的名字（加「副本」后缀，免得新卡片与模板同名到分不出来），
       链接**留空** —— 照抄模板链接会造出一张指向同一个页面的重复看板，
       这正是最该避免的误操作；留空强制用户自己填。 */
    else if (kind === 'itemadd') {
      var tpl = itemsAll().filter(function (x) { return String(x.no) === String(id); })[0];
      if (!tpl) return;
      vals = {
        itemZh: (tpl.titleZh || tpl.titleEn || '') + ' 副本',
        itemEn: (tpl.titleEn || tpl.titleZh || '') + ' Copy',
        itemUrl: '',
        /* 只用于表单底部那行「模板：#1 NUR Dashboard」，让人确认继承的是哪一张 */
        __tplFrom: '#' + tpl.no + ' ' + titleOf(tpl)
      };
    }
    else if (kind === 'maptab') {
      /* 两个入口共用这一支：
        · id === '__head'（DATA.RENAME_HEAD）→ 改**本栏标题**，
          取值回落 headTitleText / headSubText；
        · 否则 id 是页签名（gis / mwRealTime）→ 改**该页签的显示名**，
          取值回落 DATA.MAP_TABS 里配的 i18n 文案键（map.gis / map.mw）。
       当前值一律「配过就是配置里的，没配过用内置文案」—— 不要让输入框空着，
       空框会让人以为「本来就没名字」，而实际是有内置名的。
       __head 的 zh/en 与页签同口径（zh=中文、en=英文），本门户标题在上用的是 zh，
       取值时直接照 headTitleText/headSubText 的映射来。
       renameTab(id, zh, en) 写的是同一份 catalog.tabLabels，前后端按 page 组合键。 */
      var cv = (state.tabLabels && state.tabLabels[id]) || {};
      if (id === DATA.RENAME_HEAD) {
        vals = { zh: cv.zh || headTitleText(), en: cv.en || headSubText() };
      } else {
        var mt = DATA.MAP_TABS.filter(function (m) { return m.page === id; })[0];
        if (!mt) return;               /* 未知页签名：不开框，免得存下孤儿记录 */
        /* ⚠️ 两个框各取各的语言（tIn），不能用 t(mt.key) —— 后者只按当前语言取值，
           会把同一个值填进两个框（中文界面下英文框也是中文），保存即写坏英文名。 */
        vals = { zh: cv.zh || tIn('zh', mt.key), en: cv.en || tIn('en', mt.key) };
      }
    }
    var hd = kind === 'grp' ? gName(id) : kind === 'title' ? ('#' + id + ' ' + (vals.zh || vals.en))
      : kind === 'maptab' ? (t('map.title') + ' · ' + (vals.zh || vals.en))
      : kind === 'itemadd' ? t('edit.itemAdd') : t('edit.grpAdd');
    pop.hidden = false;
    pop.innerHTML = '<div class="gp-hd"><b>' + esc(hd) + '</b><span>' + esc(t(f.tip)) + '</span></div>' +
      f.fields.map(function (k) {
        /* URL 是长串，64 太短会截断带 token 的 myapp 链接；其余沿用 64。
           子分组说明 200（原有口径）。 */
        var ml = /Url$/.test(k) ? 512 : (/^sub/.test(k) ? 200 : 64);
        return '<label class="gf"><span>' + esc(t('edit.f.' + k)) + '</span>' +
          '<input type="text" class="gf-i" data-f="' + k + '" maxlength="' + ml +
          '" value="' + esc(vals[k] || '') + '" placeholder="' + esc(t('edit.fph.' + k)) + '"></label>';
      }).join('') +
      '<div class="gf-b"><button type="button" class="gb gf-ok" data-act="form-ok"><i class="ph ph-check" aria-hidden="true"></i>' + esc(t(f.ok)) + '</button>' +
      (kind === 'grp' && !isBuiltinGroup(id)
        ? '<button type="button" class="gb gf-del" data-act="form-del"><i class="ph ph-trash" aria-hidden="true"></i>' + esc(t('edit.grpDel')) + '</button>' : '') +
      /* 选错了模板不用关掉重来 —— 退回第一步重选，已填的名字/链接不丢（见 backToTplPick）。 */
      (kind === 'itemadd'
        ? '<button type="button" class="gb gf-back" data-act="form-tpl"><i class="ph ph-swap" aria-hidden="true"></i>' + esc(t('edit.itemAddBack')) + '</button>' : '') +
      '</div>' +
      (kind === 'itemadd' && vals.__tplFrom
        ? '<div class="gf-note">' + esc(tf('edit.itemTplFrom', { n: vals.__tplFrom })) + '</div>' : '');
    placePop(pop, btn);
    state.popForm = { kind: kind, id: id };
    var first = pop.querySelector('input'); if (first) { first.focus(); first.select(); }
  }
  function closeForm() {
    state.popForm = null;
    var pop = $('#editPop'); if (pop) { pop.hidden = true; pop.innerHTML = ''; }
  }
  function formVal(k) {
    var pop = $('#editPop'), el = pop.querySelector('[data-f="' + k + '"]');
    return el ? el.value : '';
  }
  function submitForm() {
    var pf = state.popForm; if (!pf) return;
    var kind = pf.kind, id = pf.id;
    /* 取值必须在 closeForm 之前：closeForm 会清空 innerHTML，
       先关后取只会读到空串，表现为「点了保存、名字被清空」。 */
    var v = { zh: formVal('zh'), en: formVal('en'), subZh: formVal('subZh'), subEn: formVal('subEn') };
    var vi = { itemZh: formVal('itemZh'), itemEn: formVal('itemEn'), itemUrl: formVal('itemUrl') };
    closeForm();                                    /* 先收浮层再提交：commit 会重绘，留着会看见「保存完了框还在」 */
    if (kind === 'grp') renameGroup(id, v);
    else if (kind === 'grpadd') addGroup(v.zh, v.en);
    else if (kind === 'maptab') renameTab(id, v.zh, v.en);
    else if (kind === 'itemadd') {
      /* 目标分组在选模板那一步就存进 state.addGid 了（不能在提交时读 tplPick：
         openForm 里的 closeGrp() 会把它清掉）。取不到才退回第一列，不静默丢弃。 */
      addItemFromTemplate(id, state.addGid || V6_GROUPS[0], vi.itemZh, vi.itemEn, vi.itemUrl);
    }
    else renameItem(id, v.zh, v.en, vi.itemUrl);
  }
  /* 表单里「换一个模板」：退回第一步重选，并把已填的名字/链接带过去。
     没填过就还原本来的预填值，不会把输入框清空。 */
  function backToTplPick() {
    var pf = state.popForm; if (!pf || pf.kind !== 'itemadd') return;
    var keep = { zh: formVal('itemZh'), en: formVal('itemEn'), url: formVal('itemUrl') };
    var gid = state.addGid || V6_GROUPS[0];
    closeForm();
    state.tplPick = { gid: gid, tpl: null, q: '' };
    state.tplCarry = keep;
    paintTplPick();
  }
  function bindFormPop() {
    var pop = $('#editPop'); if (!pop) return;
    pop.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!b) return;
      var act = b.getAttribute('data-act');
      if (act === 'form-ok') { submitForm(); return; }
      if (act === 'form-tpl') { backToTplPick(); return; }
      if (act === 'form-del') { var id = state.popForm && state.popForm.id; closeForm(); if (id) delGroup(id); return; }
    });
    pop.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || !e.target.closest('input')) return;
      e.preventDefault(); submitForm();
    });
  }

  /* 编辑开关：只认服务端 GET 回的 editable。默认永远关 ——
     这是一支会改**全站共享目录**的笔，不该在用户打开页面时就已经握着。
     `?edit=1` 深链可以自动进入（与 MsPortal 同一入口），但同样要 editable 为真。

     ⚠️ v1（2026-09-26 修正，此前整块停用）：
     早前把编辑模式整块关掉，理由是「onEditClick 的委托挂在 #views 与 #l0 上，
     这两块已按要求删掉，开起来只剩一条横幅、没有可编辑对象」——
     那个判断漏了一点：**本页真正的卡片容器是 #views6**（六个视图入口卡），
     它一直都在渲染，只是行条目当时不参与编辑。
     于是恢复的做法不是把 #views 整块搬回来（那正是用户不要的：
     六个入口卡已经覆盖 CXO/SP/MS/FLM/FO/BO，再铺一层页签是同一批内容的第二份入口），
     而是**让 #views6 的行条目自己成为编辑对象** —— 见 renderViews6()。
     目录是全站共享的一份，改目录请走本页、/olbrportal/ 或 MsPortal。 */
  function setEditing(on) {
    state.editing = !!on && !!state.catalogEditable;
    state.subEdit = ''; closeGrp(); closeForm();
    root.classList.toggle('is-edit', state.editing);
    syncEditBtn(); renderCatalog();
  }
  function syncUserMenu() {
    var menu = $('#userMenu'), panel = $('#userMenuPanel'), trigger = $('#userMenuBtn');
    if (!menu || !panel || !trigger) return;
    panel.hidden = !state.userMenuOpen;
    trigger.setAttribute('aria-expanded', state.userMenuOpen ? 'true' : 'false');
    menu.classList.toggle('is-open', state.userMenuOpen);
  }
  function closeUserMenu() { state.userMenuOpen = false; syncUserMenu(); }
  function toggleUserMenu() { state.userMenuOpen = !state.userMenuOpen; syncUserMenu(); }
  /* System Management 子菜单的展开态（2026-10-12 加）。与主菜单同一套：点击展开/收起，
     **不持久化**（每次打开用户菜单都回到收起，避免菜单一出来就长长一条）。 */
  function syncSysMenu() {
    var panel = $('#sysMenuPanel'), btn = $('#sysBtn'), wrap = $('#sysMenu');
    if (!panel || !btn) return;
    panel.hidden = !state.sysMenuOpen;
    btn.setAttribute('aria-expanded', state.sysMenuOpen ? 'true' : 'false');
    if (wrap) wrap.classList.toggle('is-open', state.sysMenuOpen);
  }
  function toggleSysMenu() { state.sysMenuOpen = !state.sysMenuOpen; syncSysMenu(); }
  function syncEditBtn() {
    var b = $('#editBtn'); if (!b) return;
    /* 只有「目录可写」的会话才看得到这颗开关：目录是全局共享的，
       局域网访客看到纯只读页是**有意**的，不是加载失败。 */
    b.hidden = !state.catalogEditable;
    b.classList.toggle('on', !!state.editing);
    b.setAttribute('aria-pressed', state.editing ? 'true' : 'false');
    var ico = b.querySelector('i'), lab = b.querySelector('span');
    if (ico) ico.className = 'ph ' + (state.editing ? 'ph-x-circle' : 'ph-pencil-simple');
    if (lab) lab.textContent = t(state.editing ? 'mast.editOn' : 'mast.edit');
    var editing = $('#userMenuEditing'); if (editing) editing.hidden = !state.editing;
    b.title = t(state.editing ? 'edit.tipOff' : 'edit.tipOn');
    var bar = $('#editBar');
    if (bar) {
      bar.hidden = !state.editing;
      var h = bar.querySelector('.edit-hint'), l = bar.querySelector('.edit-leave');
      if (h) h.textContent = t('edit.hint');
      if (l) l.textContent = t('mast.editOn');
    }
  }

  /* 只读态的二级子页签 = 纯定位器：空桶不出现，切完就把下面的卡片筛到那一桶。
     刻意不做管理动作 —— 不在编辑态的人连「删除」按钮都不该看见。 */
  function subLocatorHtml(gid, all, list) {
    var subs = subGroupsOf(gid);
    if (subs.length < 2) return { html: '', list: list };
    var buckets = subs.map(function (s) {
      return { id: s.id, label: subName(s), list: list.filter(function (it) { return subOfItem(it, gid) === s.id; }) };
    });
    var rest = list.filter(function (it) { return !subOfItem(it, gid); });
    if (rest.length) buckets.push({ id: SUB_NONE, label: t('v.subOther'), list: rest });
    buckets = buckets.filter(function (b) { return b.list.length; });
    if (buckets.length < 2) return { html: '', list: list };
    var sid = state.viewSub;
    if (sid && !buckets.some(function (b) { return b.id === sid; })) sid = '';
    state.viewSub = sid;
    if (sid) list = buckets.filter(function (b) { return b.id === sid; })[0].list;
    return {
      html: '<div class="subs-v">' +
        '<button type="button" class="subv" data-sub="" aria-pressed="' + (sid ? 'false' : 'true') + '">' +
        esc(t('v6.all')) + '<small>' + all.length + '</small></button>' +
        buckets.map(function (b) {
          return '<button type="button" class="subv" data-sub="' + esc(b.id) + '" aria-pressed="' +
            (b.id === sid ? 'true' : 'false') + '">' + esc(b.label) + '<small>' + b.list.length + '</small></button>';
        }).join('') + '</div>',
      list: list
    };
  }

  /* 编辑态的子分组条 = 定位器 + 管理器。与只读态的三点差别：
     1 空桶也画 —— 新加的子分组里还没有看板，不给它落点就永远拖不进去；
     2 计数用**全量**（不受搜索/筛选影响）：管理时看的是「这一桶里有几条看板」，
       不是「当前筛出几条」，否则带词筛选时计数会骗人；
     3 每条带改名 / 删除，末尾一行「新增」。改名只开 zh/en 两个标签，id 建好就不改
       （归属里存的就是 id，改 id 等于让已有归属指向不存在的子分组）。 */
  function subManageHtml(gid, all, list) {
    var full = itemsAll().filter(function (it) { return inGroup(it, gid); });
    var subs = subGroupsOf(gid), ids = subs.map(function (s) { return s.id; });
    var restN = full.filter(function (it) { return ids.indexOf(subOfItem(it, gid)) === -1; }).length;
    var sid = state.viewSub;
    if (sid && sid !== SUB_NONE && ids.indexOf(sid) === -1) sid = '';
    state.viewSub = sid;
    if (sid === SUB_NONE) list = list.filter(function (it) { return ids.indexOf(subOfItem(it, gid)) === -1; });
    else if (sid) list = list.filter(function (it) { return subOfItem(it, gid) === sid; });

    var sel = function (on) { return ' aria-pressed="' + (on ? 'true' : 'false') + '"'; };
    var btn = function (act, icon, label, tip, attrs) {
      return '<button type="button" class="sub-x" data-act="' + act + '"' + (attrs || '') +
        ' title="' + esc(tip) + '" aria-label="' + esc(tip) + '"><i class="ph ph-' + icon + '" aria-hidden="true"></i>' +
        (label ? '<span>' + esc(label) + '</span>' : '') + '</button>';
    };
    var html = '<button type="button" class="subv" data-sub="" aria-pressed="' + (sid ? 'false' : 'true') + '">' +
        esc(t('v6.all')) + '<small>' + all.length + '</small></button>' +
      subs.map(function (s) {
        var n = full.filter(function (it) { return subOfItem(it, gid) === s.id; }).length;
        if (state.subEdit === s.id) {
          return '<span class="subv is-ren">' +
            '<input type="text" class="sub-i" data-ren="zh" maxlength="64" value="' + esc(s.zh) + '" placeholder="' + esc(t('edit.subZhPh')) + '">' +
            '<input type="text" class="sub-i" data-ren="en" maxlength="64" value="' + esc(s.en) + '" placeholder="' + esc(t('edit.subEnPh')) + '">' +
            btn('sub-ok', 'check', t('edit.subOk'), '', ' data-gid="' + esc(gid) + '" data-subx="' + esc(s.id) + '"') +
            btn('sub-no', 'x', t('edit.subCancel'), '', '') + '</span>';
        }
        return '<span class="subv is-drop' + (sid === s.id ? ' is-on' : '') + '" data-drop-sub="' + esc(s.id) + '"' +
          ' title="' + esc(t('edit.dropSub')) + '">' +
          '<button type="button" class="sub-t" data-sub="' + esc(s.id) + '"' + sel(sid === s.id) + '>' +
          esc(subName(s)) + '<small>' + n + '</small></button>' +
          btn('sub-re', 'pencil-line', '', t('edit.subRename'), ' data-gid="' + esc(gid) + '" data-subx="' + esc(s.id) + '"') +
          btn('sub-del', 'trash', '', t('edit.subDelTip'), ' data-gid="' + esc(gid) + '" data-subx="' + esc(s.id) + '"') +
          '</span>';
      }).join('');
    /* 「未归类」不是一条存储的定义，而是每次按当前定义算出来的兜底桶：
       没有 id、不能改名也不能删除 —— 所以这里只给落点，不给那两颗按钮。 */
    html += '<span class="subv is-drop' + (sid === SUB_NONE ? ' is-on' : '') + '" data-drop-sub=""' +
      ' title="' + esc(t('edit.dropSub')) + '">' +
      '<button type="button" class="sub-t" data-sub="' + SUB_NONE + '"' + sel(sid === SUB_NONE) + '>' +
      esc(t('v.subOther')) + '<small>' + restN + '</small></button></span>';
    html += '<span class="sub-add">' +
      '<input type="text" class="sub-i" data-new="zh" maxlength="64" placeholder="' + esc(t('edit.subZhPh')) + '">' +
      '<input type="text" class="sub-i" data-new="en" maxlength="64" placeholder="' + esc(t('edit.subEnPh')) + '">' +
      btn('sub-add', 'plus', t('edit.subAdd'), '', ' data-gid="' + esc(gid) + '"') + '</span>';
    return { html: '<div class="subs-v is-mgr">' + html + '</div>', list: list };
  }

  /* ------------------------------------------------- L1 页签面板（v1 已去掉） --
     ⚠️ 这里原本是 renderViews()：MS / FLM / FO / BO 四个分组各一个页签、
     一次只展开一组，面板里按子分组再叠一行轻量子页签，最右边固定一颗
     「报告文件」页签（内嵌 my_app 的 /myapp/?page=email_reports）。
     整块约 77 行，随 #views 容器一起去掉了。

     去掉的理由：上面新增的六张视图入口卡已经覆盖 CXO / SP / MS / FLM / FO / BO
     六个视图，并且能直接点进具体报告 —— 页签面板是同一批内容的第二份入口，
     一屏里出现两次。用户的原话是「上面已经有了」。

     ⚠️ 但「报告文件」不是视图，六张卡里没有它的入口，跟着删就是功能丢失。
     所以把它单独摘出来渲染进 #emailSlot（地图右边那一栏），
     见下面的 renderEmailSection()。

     随之失去的能力（如实记录，避免以后当成 bug 排查）：
       · 按分组 / 状态 / 关键词筛选看板卡片 —— 筛选只作用于 #views 与 #l0，
         两者都没了，当时只剩 #aux 那三个辅助分组还吃筛选
         （检索轨 2026-10-16 整块移除后，这个尾巴也没有了：现在没有任何区块吃筛选）；
       · 编辑模式下的卡片级操作（改名 / 删除 / 新增看板 / 分子分组）——
         onEditClick 的委托原本只挂在 #views 与 #l0 上，现在没有可编辑对象了。
         目录编辑仍可在 /olbrportal/ 与 MsPortal 里做。 */

  /* ---------------------------------------------------- 报告文件内嵌页签 --
     四条规矩从 MsPortal 的同名卡照搬（那边实测踩出来的，换门户不换个道理）：
       ① 未登录不建 iframe —— 否则内层会渲染 my_app 自己的英文报错登录页，
          比这块空着更难看（本页通常整块被 #gate 盖住，这里只是兜住边界情况）；
       ② 只有 canSee(那块看板) 才加载，与目录 / 搜索同一套权限口径；
       ③ 主题：my_app 只在启动时读一次 localStorage['myapp-theme']（theme.ts 的
          detectMode，没有父窗口消息通道），所以切主题必须「先写键、再重设 src」；
       ④ 骨架只在「首次 / 切语言 / 被门禁清空」时重建 —— 搜索框每敲一个字都会走
          render()，跟着重建就等于每敲一个字重下一遍整页。
     第 ④ 条在本页还多一层：#vEmail 整棵子树从建立起就不再 innerHTML，
     iframe 一旦离开文档 Chrome 就直接丢弃它的内容文档（见 renderL0 里地图那段同样的
     结论），所以切页签只动 hidden，不动内容。 */
  var emailLang = null;      /* 报告文件骨架上次渲染时用的语言 */
  var qaLang = null;         /* 知识问答骨架上次渲染时用的语言（2026-10-12 加） */

  /* 这条看板在**服务端全局目录里没有**（实测：服务端 49 条、内置 51 条，缺的 17 条里
     就有 no=41 Task Report Files —— MsPortal 那张卡同样读不到，才要靠它自己的兜底文案）。
     所以查归属时把内置那份接在后面一起找：查得到才谈权限，查不到不等于「这块不存在」，
     这一页签本来就是本页固定功能，不是目录条目渲染出来的。 */
  function emailItem() {
    var pool = ITEMS.concat(D.items || []);
    return pool.filter(function (x) { return String(x.url || '').indexOf('page=' + DATA.EMAIL_PAGE) !== -1; })[0] || null;
  }
  function emailAllowed() { var it = emailItem(); return !!it && canSee(it); }
  /* 相对路径：门户从 localhost 还是局域网 IP 打开都自适应（与地图同一考虑）。
     深链自身就是 bare 模式（自己的侧栏 / Header 都隐藏），不用地图那套 DATA.MAP_STRIP_CSS。
     ⚠️ `portalFiles=1` 是**本页（v2）这块面板专属**的精简显示开关：my_app 的
        EmailReports 页读到它后只渲染 Latest Email 一个页签、并把表头换成
        Auto Email / Report Name / Email Attachment File（见 EmailReports.tsx 的
        isPortalFilesMode 与 i18n 的 emailReports.portalCol* 三条文案）。
        只有这里带上它 —— MsPortal / 根 olbrportal / v1 的内嵌 src 都不带，故它们
        与「直接打开 /myapp/?page=email_reports&lang=en」仍显示全部 4 个页签与旧表头。 */
  /* ⚠️ 2026-10-19（用户反馈「Auto Report 里又出现 Task Report Files 标题了」）：
     `embed=1` **必须带**。2026-10-18 起 my_app 的 App.tsx 把「是否隐藏外壳」的判据
     从「URL 带 ?page=」改成了**只看 `?embed=1` / `?layout=bare`**
     （readBareModule 的注释：?page= 是应用内导航常态参数，不能当开关）。
     门户内嵌页一率走 `?page=…`，于是不再进 bare 模式：my_app 的 Header、侧栏
     以及 EmailReports 自己的 Card 标题「Task Report Files」全部回来，压在
     本面板的「Auto Report」下面 —— 这正是用户看到的现象。
     地图那边同一原因，见 mapItems 的 src（同样补了 embed=1）。
     与 portalFiles=1 是两个独立开关：前者管**外壳**，后者管 EmailReports 的
     **精简列/单页签**，缺一不可。 */
  function emailSrc() { return '/myapp/?page=' + DATA.EMAIL_PAGE + langQs() + '&portalFiles=1&embed=1'; }

  function emailSectionHtml() {
    return '<div class="p-head"><span class="p-hd"><span class="p-t t-orange">' + esc(t('email.title')) + '</span></span>' +
      /* ⚠️ 2026-09-28（用户要求「Auto Report Files 组件。不要
         Task report file center (Email Reports)」）：标题右侧那颗副标题
         .p-s（email.sub）已整段不再输出。它是本组件的**实现说明**
         （点名了 Email Reports 这套后端），对看数据的人没有信息量。
         文案键 email.sub 仍留在字典里（本页不渲染 ≠ 删文案），要恢复就加回这行。 */
      '<button type="button" class="gb gb--t" data-act="email-reload" title="' + esc(t('map.reload')) + '">' +
      '<i class="ph ph-arrow-clockwise" aria-hidden="true"></i><span>' + esc(t('map.reload')) + '</span></button>' +
      '<a class="gb gb--t" id="emailOpen" href="' + esc(emailSrc()) + '" target="_blank" rel="noopener noreferrer"' +
      ' title="' + esc(t('map.open')) + '"><i class="ph ph-arrow-square-out" aria-hidden="true"></i><span>' +
      esc(t('map.open')) + '</span></a></div>' +
      '<div class="canvas" id="emailHost">' +
      '<div class="embed-boot" id="emailBoot"><i class="embed-ring" aria-hidden="true"></i>' +
      '<span>' + esc(t('map.load')) + '</span></div></div>';
  }

  function emailNote(msg) {
    var host = $('#emailHost'); if (!host) return;
    var el = $('#emailNote');
    if (!el) {
      el = document.createElement('div');
      el.id = 'emailNote'; el.className = 'embed-boot';
      host.appendChild(el);
    }
    el.innerHTML = '<i class="ph ph-shield-warning" aria-hidden="true"></i><span>' + esc(msg) + '</span>';
    var boot = $('#emailBoot'); if (boot) boot.hidden = true;
  }
  function clearEmailNote() {
    var el = $('#emailNote');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }
  function syncEmailBoot() {
    var boot = $('#emailBoot'); if (!boot) return;
    var f = $('#emailFrame');
    boot.hidden = !!(f && f.getAttribute('src') && f.dataset.loaded === '1');
  }

  function ensureEmail() {
    var host = $('#emailHost'); if (!host) return;
    if (!state.authOk) { emailNote(t('email.needLogin')); return; }
    if (!emailAllowed()) { emailNote(t('email.noAccess')); return; }
    clearEmailNote();

    var f = $('#emailFrame');
    if (!f) {
      f = document.createElement('iframe');
      f.id = 'emailFrame';
      f.setAttribute('title', t('email.title'));
      // 没设 src 的 iframe 也会先 load 一次 about:blank，所以判据必须是「有没有 src」
      f.addEventListener('load', function () {
        if (!f.getAttribute('src')) return;
        f.dataset.loaded = '1';
        syncEmailBoot();
      });
      host.appendChild(f);
    }
    var want = state.theme === 'dark' ? 'dark' : 'light';
    /* 语言也进重建判据：my_app 只在启动时读一次 URL 的 lang（见 i18n.tsx detectLocale），
       换语言若不重设 src，这块会停在旧语言 —— 与上面 theme 那条同一个理由。 */
    var wantLang = langVal();
    if (!f.getAttribute('src') || f.dataset.theme !== want || f.dataset.lang !== wantLang) {
      if (ls('myapp-theme', '') !== want) ss('myapp-theme', want);   // ⚠️ 必须在设 src 之前
      f.dataset.theme = want;
      f.dataset.lang = wantLang;
      delete f.dataset.loaded;
      f.setAttribute('src', emailSrc());
    }
    var open = $('#emailOpen'); if (open) open.href = emailSrc();
    syncEmailBoot();
  }

  /* 报告文件现在渲染进 #emailSlot（地图右边那一栏），不再是 #views 里的一个页签。
     v1：L1 页签面板整块去掉后，这里是它唯一的调用入口。 */
  function renderEmailSection() {
    var el = $('#emailSlot'); if (!el) return;
    if (emailLang !== state.lang || !el.querySelector('#emailHost')) {
      el.innerHTML = emailSectionHtml();
      emailLang = state.lang;
    }
    ensureEmail();
  }

  /* ==================================================================== v2
     知识问答（RAG / eFlow 两页签）+ OSS 门户登录（2026-10-12 加）
     ----------------------------------------------------------------------------
     用户要求：
       · 「Knowledge Q&A 里面的 RAG Knowledge Q&A 和 eFlow Knowledge Base
          作为两个页签，放到 Q&A 里面，放到 GIS Map 下面，高度和 GIS Map 一样」；
       · 「OSS Portal Login 的内容展开放到 Auto Report Files 下面，
          高度和 Q&A 一样，再同一行」。
     两块的 DOM 目标：#qaSlot（左）、#ossSlot（右），见 index.html 的 .qarow。

     数据来源：两项都是目录里的普通看板条目，**不写死** ——
     按 url 里的 page 值在目录里现查（与 mapItems 同一条口径）：
       · RAG   → 目录里 url 含 `192.168.100.27`（Open WebUI，**外域 https**）
       · eFlow → 目录里 url 含 `page=eflow_qa`
     取不到条目（被人删了 / 权限看不到）时整个页签不渲染，不摆一个空壳。
     ⚠️ 2026-10-12：RAG 已由 `http://192.168.100.27:3000/` 改成 https。
        匹配串只写主机名 `192.168.100.27`，这样新旧两种形态都能命中 ——
        目录若还没同步改到新地址，也不会在这里漏掉。
        上 https 后，门户（https）内嵌它**不再触发混合内容拦截**，页签能正常显示。
     ⚠️ 2026-10-14：**最终地址定为 `https://192.168.100.27:8443/`**（见下方 qaSrc）。
        Open WebUI 侧按地址区分身份：443 是 admin 管理入口（本人用），
        8443 是 NOC 使用入口（**自动登录为 NOC，无需密码**）。门户是使用方，
        必须走 8443 —— 走 443 会以 admin 身份打开，属越权，严禁。 */
  function qaItems() {
    var all = allowed();
    var pick = function (needle) {
      return all.filter(function (x) { return String(x.url || '').indexOf(needle) !== -1; })[0] || null;
    };
    /* 优先匹配新地址（https 无端口），回落旧地址（http:3000）—— 目录过渡期两种都可能存在。 */
    var rag = pick('192.168.100.27/') || pick('192.168.100.27');
    var eflow = pick('page=eflow_qa');
    /* ⚠️ 2026-10-12（用户要求「把 eflow 放到前面」）：顺序改为 **eFlow 在前、RAG 在后**。
       这个数组的顺序就是页签条的顺序，也是未指定 state.qaTab 时的默认选中项
       （curQa 取 list[0]）—— 故这里的先后同时决定了「谁排第一」与「默认展示谁」。 */
    return [eflow && { key: 'eflow', item: eflow }, rag && { key: 'rag', item: rag }].filter(Boolean);
  }
  /* 页签上显示的**短标签**（2026-10-12 改）：目录标题太长
     （"RAG Knowledge Q&A (本地知识问答 / Open WebUI)"），
     直接当页签名会把页签条撑得很长。改用专门定义的短名（qa.tabRag / qa.tabEflow），
     全称仍由 titleOf() 挂在 title / aria 上（见 qaSectionHtml 的 title 属性），
     鼠标悬停可见完整标题。与六视图列的 subChipLabel 同一套做法。 */
  function qaTabLabel(tab) {
    if (tab.key === 'rag') return t('qa.tabRag');
    if (tab.key === 'eflow') return t('qa.tabEflow');
    return titleOf(tab.item);
  }
  /* 页签的 title 全称：短名之外仍要让用户看得到完整标题（含说明），
     故 title 用目录标题 titleOf()，而不是短名。 */
  function qaTabTitle(tab) { return titleOf(tab.item); }
  function curQa() {
    var list = qaItems();
    return list.filter(function (x) { return x.key === state.qaTab; })[0] || list[0] || null;
  }
  /* 内嵌 src：目录 url 原样用（RAG 是绝对外域、eFlow 是绝对 .20 → 但门户经
     同源 /myapp/ 更稳）。这里对 my_app 页面统一转成**同源相对路径**，
     与地图 mapSrc() 同一理由：换机房/换域名时不用跟着改，且 stripFrame 的
     同源要求才成立。外域（RAG）保持原样。 */
  function qaSrc(tab) {
    if (!tab) return 'about:blank';
    var u = String(tab.item.url || '');
    var m = /\/myapp\/\?/.exec(u);
    if (m) {
      var q = u.slice(m.index + '/myapp/'.length);   // '?page=eflow_qa'
      /* ⚠️ 2026-10-19：补 `embed=1`。my_app 自 2026-10-18 起只看 ?embed=1 /
         ?layout=bare 隐藏外壳（App.tsx readBareModule），不再认 ?page=；
         不补则 eFlow 页签的 iframe 里会连 Header 与侧栏一起显示出来。
         与 mapItems / emailSrc 同一处理。 */
      return '/myapp/' + q + '&embed=1' + (state.theme === 'dark' ? '&theme=dark' : '') + langQs();
    }
    /* RAG（外域）：目录若还停在旧地址（`http://192.168.100.27:3000/` 或
       `https://192.168.100.27/`），这里**无条件归一到使用入口** `https://192.168.100.27:8443/`：
         · 否则 https 门户内嵌明文 http 会被混合内容拦截成空白；
         · 更要紧的是身份 —— 443 进去是 admin，8443 进去才是 NOC（自动登录）。
           门户是使用方，**只认 8443**，故这里必须强制归一，不能依赖目录值。
       这一步是幂等的：目录已改成 8443 时，归一回自身、无害。

       ⚠️ 2026-10-15：补 `?lang=` —— 用户报「英文下 RAG 页签里还是中文」。
       Open WebUI v0.12.0 的 i18next 初始化里 `lookupQuerystring` 就是 `lang`，
       `fallbackLng.default` 是 en-US，且 detection.order **不含 cookie**
       （["querystring","localStorage","defaultLocale","navigator"]）——
       所以跨域 iframe 里靠 URL 参数切语言完全可靠，不受分区影响。
       语言值写死 'en'（此分支只在英文下进入，无需 encodeURIComponent）；
       这里用 `?` 不是 `&`：RAG 的 URL 结尾是 `/`、**没有已有 query**
       （与 my_app 分支的 `&lang=` 不同）。只在语言为英文时补参数：
       中文时 Open WebUI 走它自己的 navigator/默认判定，且避免给中文用户
       多带一个无谓参数。 */
    if (u.indexOf('192.168.100.27') !== -1) {
      return 'https://192.168.100.27:8443/' +
        (state.lang === 'en' ? '?lang=en' : '');
    }
    return u || 'about:blank';
  }
  /* 2026-10-14 删除：RAG 页签上原有的「登录凭据」提示条（.qa-cred）整条链路。
     Open WebUI 现按地址区分身份（8443 = NOC 自动登录、免密码），门户走 8443
     后**根本没有凭据可展示**，留着只会误导。
     随之删除：qaCredHtml()、loadQaCred()、qaCredLoaded/qaCredTried、
     olbr.css 的 .qa-cred 系列、globals.d.ts 的 __RAG_CRED 声明、
     olbr-data.js 的 qa.credTip 词条（zh/en），以及磁盘上的
     assets/_local-credentials.js（该文件本就被 `_*` 规则忽略、从未入库）。 */
  function qaSectionHtml() {
    var list = qaItems();
    if (!list.length) return '';
    var cur = curQa();
    var tabs = list.length > 1
      ? '<div class="tabs" role="tablist">' + list.map(function (x) {
          return '<button type="button" class="tab" role="tab" data-qa="' + esc(x.key) +
            '" aria-selected="' + (cur && x.key === cur.key ? 'true' : 'false') + '" title="' +
            esc(qaTabTitle(x)) + '" aria-label="' + esc(qaTabTitle(x)) + '">' +
            ic(x.item.icon) + esc(qaTabLabel(x)) + '</button>';
        }).join('') + '</div>'
      : '';
    return '<div class="p-head"><span class="p-hd"><span class="p-t t-orange">' +
        esc(t('aux.qa')) + '</span></span>' +
      '<div class="map-tabs">' + tabs + '</div>' +
      '<div class="map-tools">' +
        /* 刷新按钮（2026-10-12 加，用户要求「Knowledge Q&A 组件也要个刷新按钮」）：
           与 GIS Map 的 map-reload、Auto Report Files 的 email-reload 同一套
           （同一颗箭头图标 + map.reload 文案）。点了重载当前页签的 iframe。 */
        (cur ? '<button type="button" class="gb gb--t" id="qaReload" data-act="qa-reload" title="' +
          esc(t('map.reload')) + '"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i><span>' +
          esc(t('map.reload')) + '</span></button>' : '') +
        (cur ? '<a class="gb gb--t" id="qaOpen" href="' + esc(cur.item.url || '#') +
          '" target="_blank" rel="noopener noreferrer" title="' + esc(t('map.open')) + '">' +
          '<i class="ph ph-arrow-square-out" aria-hidden="true"></i><span>' + esc(t('map.open')) + '</span></a>' : '') +
      '</div></div>' +
      '<div class="canvas">' +
        (cur ? '<iframe id="qaFrame" title="' + esc(qaTabTitle(cur)) + '" src="' + esc(qaSrc(cur)) + '"></iframe>'
             : '<div class="canvas-note"><span>' + esc(t('v.empty')) + '</span></div>') +
      '</div>';
  }
  function renderQaSection() {
    var el = $('#qaSlot'); if (!el) return;
    /* 只重建一次骨架；切页签只换 iframe 的 src（不重画整块，避免闪一下）。
       ⚠️ 换语言要整块重画：页签名与标题都随语言变，与 renderEmailSection 同理。 */
    if (qaLang !== state.lang || !el.querySelector('#qaFrame')) {
      el.innerHTML = qaSectionHtml();
      qaLang = state.lang;
    }
  }

  /* OSS 门户登录：Friends Link（AUX_TITLES 里显示的标题就是 aux.friends =
     "OSS Portal Login"）那一组的全部条目，**展开**平铺（去掉 AUX_ROWS 折叠）。

     2026-10-12（用户要求「展示形式使用项目的卡片的形式，现在里面大量空白不好看」）：
     由原来的 .lrow **行列表**改成**卡片网格**（.oss-card）——
     行列表在右栏里是单列窄条，条目少时下方一大片空白；卡片网格按自适应列铺开，
     图标+名字成一格，既填满高度又更好点。
     卡片样式收在 olbr.css 的 .oss-grid / .oss-card（不与六视图入口卡共用 ——
     那套是 .v6-row，语义是"看板入口 + 状态徽章"，这里的对象是外部系统登录，
     两者本就不该长一样）。 */
  function ossSectionHtml() {
    var list = groupItems('Friends Link');
    var cards = list.map(function (it) {
      return '<a class="oss-card" href="' + esc(vlink(it, 'Friends Link')) +
        '" target="_blank" rel="noopener noreferrer" title="' + esc(descOf(it) || titleOf(it)) + '">' +
        '<span class="oss-card-ico">' + ic(it.icon) + '</span>' +
        '<span class="oss-card-t">' + esc(titleOf(it)) + '</span></a>';
    }).join('');
    /* 2026-10-13（用户要求「根据卡片数自动分两行，列数自动平分」）：
       列数 = ceil(卡片数 / 2)，当时写成行内样式。
       ⚠️ 2026-10-15（用户要求「每行改为 3 个卡片平分宽度」）：**列数改为固定 3**，
       由 CSS 的 .oss-slot .oss-grid（repeat(3, minmax(0,1fr))）负责，
       这里删掉行内 grid-template-columns —— 行内样式的特异性高于类选择器，
       留着会盖掉 CSS 里定好的 3 列，变成"看起来改了其实没生效"。
       行数因此完全由卡片数决定（3 张一行，行高 auto，见 CSS 注释）。 */
    return '<div class="p-head"><span class="p-hd"><span class="p-t t-orange">' +
        esc(t('aux.friends')) + '</span></span>' +
      '<div class="map-tools"><span class="cnt">' + list.length + '</span></div></div>' +
      '<div class="oss-grid">' +
        (cards || '<span class="oss-card is-empty">' + esc(t('v.empty')) + '</span>') + '</div>';
  }
  function renderOssSection() {
    var el = $('#ossSlot'); if (!el) return;
    /* 标题/计数随语言与筛选变，总是重画（这块没有 iframe，重画代价可忽略）。 */
    el.innerHTML = ossSectionHtml();
  }

  /* viewsShell() 随 #views 一起去掉了：它搭的是 .view-1 / #vTabs / #vGroup / #vEmail
     这层页签骨架，现在没有页签，骨架也就没有意义。
     报告文件的骨架由 renderEmailSection() 直接写进 #emailSlot。 */

  /* 辅助区分组标题：默认只露 DATA.AUX_ROWS 行，多出来的靠「展开 / 收起」按钮。
     收缩用 CSS 隐藏第 3 条起的 li（而不是 max-height），避免半行被裁一半。 */
  function auxHead(key, label, n) {
    var open = !!state.auxOpen[key], cut = n > DATA.AUX_ROWS;
    return '<h3 class="aux-h"><span class="aux-n t-orange">' + esc(label) + '</span><span class="cnt">' + n + '</span>' +
      (cut ? '<button type="button" class="aux-x" data-act="aux-toggle" data-key="' + esc(key) +
        '" aria-expanded="' + (open ? 'true' : 'false') + '"><i class="ph ph-' + (open ? 'caret-up' : 'caret-down') +
        '" aria-hidden="true"></i><span>' + esc(open ? t('aux.less') : tf('aux.more', { n: n - DATA.AUX_ROWS })) +
        '</span></button>' : '') + '</h3>';
  }
  function auxRow(it, gid) {
    return '<li><a class="lrow" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer">' +
      ic(it.icon) + '<span>' + esc(titleOf(it)) + '</span>' +
      (it.status === 'beta' ? '<em>' + esc(stOf(it)) + '</em>' : '') +
      '<i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>';
  }
  /* 归档区（2026-09-28 加）。
     ----------------------------------------------------------------------------
     为什么必须有这一块：「移出本列」把看板送进归档后，如果归档不渲染，
     用户看到的就是"卡凭空消失"—— 那和直接删掉没有区别，兜底也就白做了。

     为什么默认折叠（只露 AUX_ROWS 行）：归档是"收起来"的地方，不是要天天看的清单。

     ⚠️ 2026-09-29 更正：下面这句「**不能完全隐藏**：管理员需要能确认"它还在"」
     已被用户需求推翻 —— 现在是**默认整块隐藏**，只有本会话真的归档过东西才露出来。
     新的理由、以及"那怎么确认它还在"的替代回执，都写在 renderArchive() 里。

     为什么只显示"只属于归档"的条目：一张卡可以同时挂在正常视图和归档里
     （用「分组」浮层就能勾成这样）。那种条目在正常视图里已经看得见，
     再在归档区列一遍会让人以为有两份。所以归档区**只列"除此之外没有别处"的条目**，
     语义是"这些是只在这里的东西"。
     —— 注意与 delGroup/dropItemFromGroup 的补归档口径一致：补进去的必然是唯一归属。 */
  function archivedItems() {
    return allowed().filter(function (it) {
      var g = groupsOf(it);
      return g.length === 1 && isArchiveGid(g[0]);
    });
  }
  function renderArchive() {
    var box = $('#arch');
    if (!box) return;
    var list = archivedItems();
    /* 没有归档项就整块不渲染（不是渲染一个空框）：绝大多数会话用不到它，
       常驻一个"归档为空的框"只是噪声。 */
    if (!list.length) { box.innerHTML = ''; box.hidden = true; return; }
    /* ⚠️ 2026-09-29（用户要求）：归档区**默认隐藏**。
       ============================================================================
       上面 auxRow 前面那段 9/28 的注释写着「**不能完全隐藏**：管理员需要能确认它还在」，
       那句已被这条需求推翻 —— 现行为是：**正常的浏览会话里，归档区一个像素都不露**。

       为什么"留一行标题 + 计数"也被否掉：归档是**例外状态**，不是版面。
       常驻一行等于每次开会都在主屏上留一个"有东西被收起来了"的暗示，
       而它绝大多数时候是 0/空；那行存在的唯一意义是证明"没弄丢"，
       不足以占住 L2 辅助区的一格。

       ⚠️ 为什么判据是 `state.recall`，而不是"本会话渲染过归档区"（第一版就错在这）：
       第一版写成"renderArchive 渲染到有内容的归档区就置 sawArchive=true"，
       实测**反而永远看得见** —— 因为 `boot()` 在探测登录态**之前**先裸调了一次
       `render()`（见文件末尾 `boot`），那一次就把闸门置成了 true，
       随后 `start()` → renderCatalog() 再渲染时它早已失效。
       所以判据必须是"**用户当场做了归档这个动作**"：recall 只由 dropItemFromGroup()
       与分组浮层的 setGroups() 显式打开，刷新即丢（session 级、不落盘）。
       这样既不占版面、又不依赖 render 的调用时序。

       ⚠️ 那"点「移出本列」后卡凭空消失"怎么办（这正是 9/28 加这块的理由）：
       隐藏的是**渲染**，不是**回执**。三条回执一条没少，且都在归档**之外**：
         ① toast 照旧弹「已移入归档」（edit.archived）；
         ② 「分组」浮层里归档照旧是可勾选的真分组 —— 归档项在那里看得见、勾得回来；
         ③ 归档动作发生时就置 recall=true，归档区立刻露出来给用户一个落点。

       ⚠️ 检索轨（含侧栏分组 chips）已于 2026-10-16 整块移除，这条闸门只剩
       renderArchive() 自己在用 —— 保留口径不变：用户当场归档过才露出来。 */
    if (!state.recall) { box.innerHTML = ''; box.hidden = true; return; }
    box.hidden = false;
    list = list.slice().sort(sorter(DATA.ARCHIVE));
    var open = !!state.auxOpen[DATA.ARCHIVE], cut = list.length > DATA.AUX_ROWS;
    var show = open || !cut ? list : list.slice(0, DATA.AUX_ROWS);
    box.innerHTML =
      '<div class="aux-g arch-g" data-key="' + esc(DATA.ARCHIVE) + '" data-open="' + (open ? '1' : '0') + '">' +
        '<h3 class="aux-h"><span class="aux-n t-orange">' + esc(archiveName()) + '</span>' +
        '<span class="cnt">' + list.length + '</span>' +
        (cut ? '<button type="button" class="aux-x" data-act="aux-toggle" data-key="' + esc(DATA.ARCHIVE) +
          '" aria-expanded="' + (open ? 'true' : 'false') + '"><i class="ph ph-' + (open ? 'caret-up' : 'caret-down') +
          '" aria-hidden="true"></i><span>' + esc(open ? t('aux.less') : tf('aux.more', { n: list.length - DATA.AUX_ROWS })) +
          '</span></button>' : '') + '</h3>' +
        '<p class="arch-hint">' + esc(t('arch.hint')) + '</p>' +
        '<ul>' + show.map(function (it) {
          return '<li><a class="lrow" href="' + esc(vlink(it, DATA.ARCHIVE)) + '" target="_blank" rel="noopener noreferrer">' +
            ic(it.icon) + '<span>' + esc(titleOf(it)) + '</span>' +
            (it.status === 'beta' ? '<em>' + esc(stOf(it)) + '</em>' : '') +
            '<i class="ph ph-arrow-right go" aria-hidden="true"></i></a>' +
            /* 回去的路：没有它，"可逆"就只是注释里的一句话。
               只在编辑态给（与其余编辑按钮同一口径）。 */
            (canEdit() ? '<button type="button" class="ct" data-act="unarchive" data-no="' + esc(it.no) +
              '" title="' + esc(t('arch.unarchiveTip')) + '"><i class="ph ph-arrow-u-up-left" aria-hidden="true"></i>' +
              esc(t('arch.unarchive')) + '</button>' : '') +
            '</li>';
        }).join('') + '</ul></div>';
  }
  function renderAux() {
    var box = $('#aux'), html = '';
    /* 2026-10-12（v2 专有）：这三组已各有了新的去处，底部辅助区不再重复渲染 ——
         · Knowledge Q&A → .qarow 左栏（renderQaSection）
         · Friends Link（OSS Portal Login）→ .qarow 右栏（renderOssSection）
         · System Admin（System Management）→ 右上角用户菜单（renderSysMenu）
       用户在底部看到 System Management，而右上角用户菜单里已经有一份，属重复入口，
       2026-10-12 要求去掉底部的这一份。
       ⚠️ DATA.T2 / AUX_TITLES / 目录数据**都不删**（本页不渲染 ≠ 删数据），
          要恢复就把对应 gid 从下面这张表移除。
       ⚠️ 副作用（已知悉）：System Admin 在用户菜单里只对 role==='admin' 显示，
          故去掉底部这份后，**非管理员将看不到该组入口**。 */
    var AUX_MOVED = { 'Knowledge Q&A': 1, 'Friends Link': 1, 'System Admin': 1 };
    DATA.T2.forEach(function (gid) {
      if (AUX_MOVED[gid]) return;
      var list = groupItems(gid);
      if (!list.length) return;
      html += '<div class="aux-g" data-key="' + esc(gid) + '" data-open="' + (state.auxOpen[gid] ? '1' : '0') + '">' +
        auxHead(gid, t(DATA.AUX_TITLES[gid] || gid), list.length) + '<ul>' +
        (list.length ? list.map(function (it) { return auxRow(it, gid); }).join('')
          : '<li><span class="lrow">' + esc(t('v.empty')) + '</span></li>') + '</ul></div>';
    });
    /* v1 改：这里原来是第四张辅助卡「本页相关 / About this page」，装两条行链接
       （管理门户 /MsPortal/、统一门户 /uniplam/）。按要求整块去掉。
       去掉的理由不只是"少两块"：那两条在**顶栏已经各有一颗按钮**（管理门户、
       统一门户，就在用户名字旁边），页脚还写着版本号与"安全合规模式运行" ——
       同一个信息在首屏出现三次，其中一次还占着 L2 辅助区的一整格。
       按钮本身的 href 与文案都没动，只是不再在这块重复一遍。
       注意：i18n 里的 'aux.tools' / 'aux.ms' / 'aux.uni' 三个键**保留**，
       不删 —— 它们与 MsPortal 共用同一套词典命名，且以后若要恢复这张卡，
       文案还在原处；删掉反而会留下一个"键没了"的坑。 */
    box.innerHTML = html;
  }

  /* v1：升级机制默认展开，且默认只显示**前 4 行**。
     ----------------------------------------------------------------------------
     需求原话「Escalation Matrix 要默认显示前 4 行」。三处与 /olbrportal/ 原版不同：

     ① state.escOpen 初值 true（原版 false，默认收成一条 52px 的值班带）。
        这张表是"出事时第一个要看的东西"，默认藏起来等于每次都要多点一次。

     ② 默认只渲染前 ESC_DEFAULT_ROWS = 4 行。
        ⚠️ 为什么是"前 4 行"而不是"前 4 行 LEVEL1"：
        源表 21 行本身是按档位分块排的，前 4 行天然全部落在 LEVEL1 里，
        所以这里直接对整表切前 4 行 —— 语义就是"表最上面那 4 行"，
        与用户看到表格时的直觉一致，不引入额外的分组概念。

     ③ 顶部那排 LEVEL1~LEVEL4 档位按钮**整排去掉**（2026-09-25 按要求）。
        原版点了会把表切成某一档；v1 早先把它退化成可反选的细看入口，现在
        连入口一起删除 —— 见下面「为什么去掉」一段。

     ---------------------------------------------------------------------------
     为什么去掉档位按钮（而不是只去掉它的点击）：
       需求原话是「把 L1/L2/L3/L4 的点击按钮去掉」。若只摘掉 click 监听而留着
       按钮，用户点下去毫无反应 —— 比"按钮不存在"更像坏了。所以整排 DOM 一起删。
       被一并移除的能力只有"按档过滤"一项，而它是**冗余**的：表本身已按档分块排序，
       每行首列也印着 L1~L4 档位，21 行一屏可读；「展开全部」仍能把整表摊开。
       随之失去的隐藏功能是"按档筛选时显示该档的说明文字"（原来吊在脚注上），
       该说明随按钮一起消失，脚注只留数据来源。

     ---------------------------------------------------------------------------
     行数由**单一开关** escAll 决定（曾经有 escLv/escAll 两个正交开关）：

       escAll = true   → 全部 21 行（点「展开全部」）
       escAll = false  → 前 4 行（默认）

     ⚠️ state.escLv 已随之删除，不要再加回来：它是档位按钮的专属状态，
     留着只会是一个永远为空、却让人以为"还有按档筛选"的悬空字段。 */
  var ESC_DEFAULT_ROWS = 4;
  function renderEsc() {
    var box = $('#esc'), E = D.escalation || {}, rows = E.rows || [], lv = E.levels || [];
    if (!rows.length) { box.hidden = true; return; }
    /* 两态：展开全部 > 默认前 4 行。档位筛选那一支已随按钮删除。 */
    var filtered = state.escAll ? rows : rows.slice(0, ESC_DEFAULT_ROWS);
    /* 还藏着多少条。展开全部时为 0（全部都在屏幕上，不提示）。 */
    var hidden = Math.max(0, rows.length - filtered.length);
    /* 按钮文案：默认态说"展开全部 (21)"，展开态说"只看前 4 行"。
       注意不能写成「收起」——那是 escOpen 的语义（整表收成一条带），
       而这里要收起的是"多出来的 17 行"，两者混用会让用户以为点下去表会消失。 */
    var btn = state.escAll ? t('esc.lessRows') : tf('esc.expand', { n: rows.length });
    var html = '<div class="esc-bar"><span class="esc-t t-orange">' + esc(t('esc.title')) + '</span>' +
      '<span class="esc-s">' + esc(tf('esc.count', { n: rows.length, lv: lv.length })) + ' · ' + esc(t('esc.sub')) + '</span>' +
      /* 这里原是 LEVEL1~LEVEL4 那排档位按钮（.lvchip），2026-09-25 按要求整排删除。
         上方的 esc.count 仍用 lv.length 报档位数「4 levels」—— 那是**描述这张表
         有几档**，不是可点的筛选器，所以数字保留，只是不再对应任何按钮。 */
      '<span class="esc-lv">' +
      /* 收起态下面这颗按钮的语义是"把整张表摊开"，展开态才是"4 行 / 全部"的切换。 */
      (state.escOpen
        ? '<button type="button" class="gb" data-act="esc-toggle"><i class="ph ph-' + (state.escAll ? 'caret-up' : 'caret-down') + '"></i>' + esc(btn) + '</button>'
        : '<button type="button" class="gb" data-act="esc-toggle"><i class="ph ph-caret-down"></i>' +
          esc(tf('esc.expand', { n: rows.length })) + '</button>') +
      '</span></div>';
    if (state.escOpen) {
      html += '<div class="esc-body"><div class="esc-scroll"><table class="grid"><thead><tr>' +
        '<th>' + esc(t('esc.lv')) + '</th><th>' + esc(t('esc.pos')) + '</th><th>' + esc(t('esc.name')) + '</th>' +
        '<th class="num">Orange</th><th class="num">LONESTAR</th><th>' + esc(t('esc.mail')) + '</th></tr></thead><tbody>' +
        filtered.map(function (r) {
          /* ⚠️ 2026-09-28（用户要求「表格按照 Level 显示不同的颜色，注意深浅两种主题背景」）：
             <tr> 上补一个 data-lv="1..4"，配色交给 CSS 的 [data-lv="n"] 规则。
             为什么用属性而不是在这里拼 class/style：
               · 颜色必须**按主题给两套值**，内联 style 只能写死一套，
                 深色主题下要么对比不足、要么刺眼；
               · 属性选择器让"哪一级是什么颜色"集中在样式表里，改配色不用动 JS。
             data-lv 取 "L1" 尾部的数字；取不到（后端冒出第 5 级或空值）时**不写该属性**，
             此时 CSS 的默认样式（原来的品牌色）兜底，不会出现"没配色的白板行"。 */
          var lvn = /^LEVEL(\d+)$/.exec(String(r.level || ''));
          return '<tr' + (lvn ? ' data-lv="' + lvn[1] + '"' : '') + '>' +
            '<td class="lv">' + esc(String(r.level || '').replace('LEVEL', 'L')) + '</td>' +
            '<td>' + esc(r.position || '—') + '</td><td>' + esc(r.name || '—') + '</td>' +
            '<td class="num">' + esc(r.orange || '—') + '</td><td class="num">' + esc(r.lonestar || '—') + '</td>' +
            '<td>' + (r.email ? '<a href="mailto:' + esc(r.email) + '">' + esc(r.email) + '</a>' : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        /* 只显示 4 行时必须说清"还有 N 条没显示"，否则会被当成表就这么多行。
           提示语里点名"展开全部"这颗按钮，用户才知道该点哪里（就是他这次反馈的那点）。 */
        (hidden ? '<p class="esc-note esc-note--more"><i class="ph ph-info" aria-hidden="true"></i>' +
          esc(tf('esc.moreRows', { n: hidden })) + '</p>' : '') +
        /* 脚注原来还跟着「当前档位的说明文字」（按档筛选时才非空）。
           档位按钮删掉后它恒为空，留着就是一句永远拼不出来的尾巴，故整段去掉。 */
        '<p class="esc-note">' + esc(t('esc.src')) + ' · ' +
        '<button type="button" class="gb" data-act="esc-copy" style="margin-left:8px"><i class="ph ph-copy"></i>' + esc(t('esc.copy')) + '</button></p></div>';
    }
    box.innerHTML = html;
  }

  function render() { renderBand(); renderKpi(); renderViews6(); renderL0(); renderEsc(); renderEmailSection(); renderQaSection(); renderOssSection(); renderAux(); renderArchive(); applyI18n(); }

  /* 目录保存后的重绘：只画「看得懂目录改动」的那几块，且**不重新加载地图**。
     ⚠️ 不能图省事调 render()：MsPortal 当年就是这么把 4 个地图 iframe 全重建了一遍，
     地图重新加载几十秒，验证脚本从 18/18 掉到 11/18（症状是「no leaflet」）。
     本页面只有一个地图，但同样的坑：改一次排序就闪一下地图，谁都会以为保存把页面弄坏了。
     所以 renderL0 传 true 走 iframe 保活快速路径（只就地重画 p-head）。
     v1 加入 renderViews6()：它列的报告名直接来自目录，改了标题 / 归属必须跟着变；
     而它不碰任何 iframe，放进这条快速路径是安全的。
     v1：原先这里还调 renderViews()（L1 页签面板），面板已去掉，改成
     renderEmailSection() —— 报告文件挂在目录条目上（emailItem 查 url 里的 page=），
     所以目录一改它也要跟着重判一次权限与文案。 */
  function renderCatalog() { renderViews6(); renderL0(true); renderEmailSection(); renderQaSection(); renderOssSection(); renderAux(); renderArchive(); }

  /* --------------------------------------------------------------- auth -- */
  /* 与 MsPortal 共用 PORTAL_TOKEN_KEY：新页面登录不会把 MsPortal 顶掉（同一份会话），
     而查看器 /MsPortal/viewer.html 又必须读得到这个键，所以不复用就会把打开动作搞挂。 */
  var TOKEN_KEY = 'liberia_noc_auth_v1';
  function tok() { return ls(TOKEN_KEY, null); }

  /* 两个端点返回的主体不一样，取用顺序照 MsPortal 的 probeSession()：
       · /uniplam/api/auth/me  —— 真正的门户账号，**带 role / allowedGroups / allowedCards**，
         权限判定只认这一份；
       · /api/auth/me          —— my_app 的会话身份（本机回环是占位的 {username:'local'}），
         没有权限字段，只用来认「登没登录」和显示用户名。
     两者都是 {user:{…}} 信封，必须剥 .user —— 早先直接存了信封，
     结果 #whoBadge 取 u.username 永远为空，徽标和退出按钮都不出现。 */
  function probe() {
    var unwrap = function (j) { return j && j.user ? j.user : null; };
    var p1 = fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; }).then(unwrap).catch(function () { return null; });
    var tk = tok();
    var p2 = tk ? fetch('/uniplam/api/auth/me', {
      credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tk, Accept: 'application/json' }
    }).then(function (r) { return r.ok ? r.json() : null; }).then(unwrap).catch(function () { return null; }) : Promise.resolve(null);
    return Promise.all([p1, p2]).then(function (a) {
      state.user = a[1] || a[0] || null;
      state.authOk = !!state.user;
      renderWho();
    });
  }
  /* 用户菜单里的「System Management」子菜单（2026-10-12 加）：
     条目从目录的 **System Admin 分组**现取（当前是 Task Manager / Settings），
     不写死 —— 目录里加/删/改名自动跟随，与六视图入口卡同一条"不建第二份真相源"约定。
     用 groupItems() 而不是 allowed()：它按 System Admin 分组过滤 + 点击排序，
     与当初底部辅助区渲染这一组的口径一致（本页把 System Admin 留在 #aux，
     这里是同一批条目的第二个入口，两者同源）。 */
  function renderSysMenu() {
    var panel = $('#sysMenuPanel'); if (!panel) return;
    var list = groupItems('System Admin');
    panel.innerHTML = list.length
      ? list.map(function (it) {
          return '<a class="mp-user-sub-item" role="menuitem" href="' + esc(vlink(it, 'System Admin')) +
            '" target="_blank" rel="noopener noreferrer" title="' + esc(descOf(it) || titleOf(it)) + '">' +
            ic(it.icon) + '<span>' + esc(titleOf(it)) + '</span></a>';
        }).join('')
      : '<span class="mp-user-sub-item is-empty">' + esc(t('v.empty')) + '</span>';
  }
  function renderWho() {
    var menu = $('#userMenu'), b = $('#whoBadge'), o = $('#logoutBtn'), u = state.user;
    var n = u && (u.username || u.id || u.name);
    var role = u && u.role === 'admin' ? t('um.roleAdmin') : t('um.roleViewer');
    if (menu) menu.hidden = !state.authOk;
    if (b) { b.textContent = n || ''; }
    var acct = $('#userMenuAccount'); if (acct) acct.textContent = n || '';
    var roleEl = $('#userMenuRole'); if (roleEl) { roleEl.hidden = !n; roleEl.textContent = n ? role : ''; }
    if (o) o.hidden = !state.authOk;
    /* 用户管理入口对管理员**一律可见**（2026-09-25 改）。
       原判定是 `role === 'admin' && u.id`，把本机回环的占位身份排除在外 ——
       占位身份（/api/auth/me 给的 {username:'local', role:'admin'}）确实是 admin
       但调不动门户接口，当年的处理是「与其点了弹提示，不如干脆不显示」。
       副作用是一个走不出去的闭环：按钮没了 → 没有任何提示说明为什么 → 页面上也
       没有别的登录入口（顶栏两个门户外链 2026-09-24 已按要求删掉，登录框又被
       authOk 藏起来）→ 用户永远拿不到能让按钮出现的会话。
       改为照常显示，点下去由 openUserMgmt 分流：没有门户账号就唤起登录/注册闸门。
       这里只判 role，不再判 id —— 真正的权限边界在后端 /uniplam/api/auth/* 上，
       前端只负责别把入口藏成一个谜。 */
    var m = $('#umBtn');
    if (m) m.hidden = !(u && u.role === 'admin');
    /* System Management 子菜单：显示条件与「用户管理」同一套（role === 'admin'）。
       条目与展开态由 renderSysMenu / syncSysMenu 管。 */
    var sm = $('#sysMenu');
    if (sm) sm.hidden = !(u && u.role === 'admin');
    renderSysMenu();
    syncSysMenu();
    var editing = $('#userMenuEditing'); if (editing) editing.hidden = !state.editing;
    syncUserMenu();
  }
  /* 登录闸门。两种形态，与 /uniplam/ 的 src/components/LoginView.tsx 对齐：
       login   —— 用户名 + 密码，打 POST /uniplam/api/auth/login；
       request —— 自助注册申请，打 POST /uniplam/api/auth/register-request，
                  提交后由管理员在「用户管理 → 待审批申请」里批准。
     标题两个形态共用 gate.title，只换副标题 —— LoginView 也是这个做法
     （标题恒为 app.title，副标题在 auth.subtitle / ar.subtitle 之间切）。
     可见性：真未登录时必现；已经以占位身份登着（authOk 为真）时，只有用户主动
     要进门户（state.gateOpen，例如点了当前身份管不了的「用户管理」）才唤起，
     并给一个「取消」退回原来的只读界面 —— 加了登录不能把原来能看的页面变成登录墙。 */
  function renderGate() {
    var box = $('#gate');
    var forced = state.gateOpen;
    if (state.authOk && !forced) { box.hidden = true; box.innerHTML = ''; return; }
    var isReq = state.gateMode === 'request';
    var h = '<div class="gate"><div class="gate-c"><h2>' + esc(t('gate.title')) + '</h2>' +
      '<p>' + esc(isReq ? t('ar.subtitle') : t('gate.sub')) + '</p>' +
      (forced ? '<div class="gate-hint">' + esc(t('gate.hintNoPortal')) + '</div>' : '');
    if (isReq) {
      h += '<form id="rf">' +
        '<label class="fld"><span>' + esc(t('ar.usernamePh')) + '</span><input id="ru" autocomplete="username" required></label>' +
        '<label class="fld"><span>' + esc(t('ar.passwordPh')) + '</span><input id="rp" type="password" autocomplete="new-password" required></label>' +
        '<label class="fld"><span>' + esc(t('ar.confirmPh')) + '</span><input id="rp2" type="password" autocomplete="new-password" required></label>' +
        '<label class="fld"><span>' + esc(t('ar.notePh')) + '</span><input id="rn"></label>' +
        '<div class="gate-err" id="re" hidden></div><div class="gate-ok" id="ro" hidden></div>' +
        '<div class="gate-ft"><button class="btn" type="button" id="gback">' + esc(t('ar.backToLogin')) + '</button>' +
        '<button class="btn primary" type="submit" id="rgo">' + esc(t('ar.submit')) + '</button></div></form>';
    } else {
      h += '<form id="lf">' +
        '<label class="fld"><span>' + esc(t('gate.user')) + '</span><input id="lu" autocomplete="username" required></label>' +
        '<label class="fld"><span>' + esc(t('gate.pass')) + '</span><input id="lp" type="password" autocomplete="current-password" required></label>' +
        '<div class="gate-err" id="le" hidden></div>' +
        '<div class="gate-ft">' +
        /* 主动唤起时左位放「取消」（退回只读界面），而不是门户外链 ——
           这一档的用户本来就登着本页，最需要的是「我不想登录了，让我回去看数据」。
           真未登录时左位保持原有的「管理门户」外链。 */
        (forced
          ? '<button class="btn" type="button" id="gclose">' + esc(t('gate.cancel')) + '</button>'
          : '<a class="btn" href="/MsPortal/?lang=' + encodeURIComponent(langVal()) + '">' + esc(t('mast.admin')) + '</a>') +
        '<button class="btn primary" type="submit" id="lgo">' + esc(t('gate.go')) + '</button></div>' +
        '<div class="gate-alt"><button type="button" class="gate-link" id="gmreq">' +
        esc(t('ar.requestLink')) + '</button></div></form>';
    }
    h += '</div></div>';
    box.hidden = false;
    box.innerHTML = h;
    mainLocked(true);
  }
  /* 关掉闸门、退回只读界面。只有「主动唤起」那一档用得到 ——
     真未登录时关掉会让页面停在没有任何出口的状态，所以那一档不给关闭按钮。 */
  function closeGate() {
    state.gateOpen = false;
    state.gateMode = 'login';
    renderGate();
    mainLocked(false);
  }
  /* 未登录时把主内容整块藏掉（#gate 盖在上面）。
     ⚠️ v1 修：这份清单原来只列了原版的五块，v1 新增的 #kpi / #views6 / #l0Map
     没被加进来 —— 后果是没登录时这三块**照样显示**在登录框下面（数字还是空的
     「—」，但边框、标题、六张入口卡都在），比整块留白更像坏了。
     现在按 main 里的实际区块补全；#emailSlot 是内嵌 iframe，同样必须一起藏。 */
  function mainLocked(on) {
    ['#band', '#kpi', '#views6', '#l0Map', '#emailSlot', '#qaSlot', '#ossSlot', '#esc', '#aux']
      .forEach(function (s) { var e = $(s); if (e) e.hidden = on; });
  }
  function login(u, p) {
    return fetch('/uniplam/api/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok || !d.token || !d.user) { var e = new Error(d.detail || 'login failed'); e.code = r.status === 429 ? 'locked' : r.status === 401 ? 'bad' : 'net'; throw e; }
        ss(TOKEN_KEY, d.token);
        state.user = d.user; state.authOk = true;
        /* 登录成功把闸门收回 —— 它可能是被「用户管理」主动唤起的，
           不收的话 renderGate 会因为 gateOpen 仍然为真而继续显示。 */
        state.gateOpen = false; state.gateMode = 'login';
        return fetch('/api/auth/portal-login', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ token: d.token })
        }).catch(function () {});
      });
    });
  }
  /* 自助注册申请（2026-09-25 加）。与 /uniplam/ 的 LoginView.handleRequest 同一套：
     公开接口、不需要 token，提交后进「待审批申请」队列，等管理员批准。
     错误码是后端约定的 detail 字符串（server/auth.ts 的 POST /register-request 那一支），
     照 LoginView 的映射逐条翻，不要自己另立一套口径 —— 同一件事在两页必须说一样的话。 */
  function register(u, p, note) {
    return fetch('/uniplam/api/auth/register-request', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: u, password: p, note: note })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok) return true;
        var detail = String((d && d.detail) || '');
        var e = new Error(detail || ('HTTP ' + r.status));
        /* detail → 文案键。**必须覆盖后端所有会返回的 detail**，漏掉的那个会被
           当成网络故障报出去。2026-09-30 实测事故：用户名带 @ 或大写时后端返回
           400 invalid_username，这里没有对应分支 → 落到下面的 'server' → 页面显示
           「无法连接鉴权服务，请检查网络后重试」，用户以为是网络问题，换到
           /uniplam/ 反复试到猜对用户名为止（nginx access log 里 7 次 400、
           每次响应体 29 字节 = {"detail":"invalid_username"}）。
           格式类错误合并到 invalidInput 一条 —— 后端对用户名/密码规则的说法
           （invalid_username / password_too_short / invalid JSON payload）对用户
           没有区别，逐条翻译只会多出三个几乎同义的键。
           最后那个 'server' 分支是**有意的兜底**：认不出的 detail 就原样显示后端
           的话（err.message），不冒充网络故障。'net' 从此只留给真正的 fetch 失败。 */
        e.code = detail === 'username_taken' ? 'duplicate'
          : detail === 'request_pending' ? 'pendingDup'
            : detail === 'too_many_requests' ? 'tooMany'
              : detail === 'invalid_username' ? 'invalidInput'
                : detail === 'password_too_short' ? 'invalidInput'
                  : detail === 'invalid JSON payload' ? 'invalidInput'
                    : 'server';
        throw e;
      });
    }, function () {
      var e = new Error('network'); e.code = 'net'; throw e;
    });
  }
  function logout() {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
    var tk = tok();
    if (tk) fetch('/uniplam/api/auth/logout', {
      method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tk }
    }).catch(function () {});
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    state.user = null; state.authOk = false; renderGate(); renderWho();
  }

  /* =============================================================== 用户管理 -- */
  /* 目标：让 http://localhost/olbrportal/ 与 http://localhost/uniplam/ 一样能管账号。
     天然同库，不是「同步」：本页没有自己的用户表，所有读写都打到
     /uniplam/api/auth/* —— 那是 server/auth.ts 挂在门户 vite 服务上的同一组接口，
     落盘 <项目根>/auth-data/portal-auth.db。所以在这一页建/删/改权限，
     /uniplam/ 与 /MsPortal/ 刷新即可见。功能与 src/components/UserManagementModal.tsx
     逐条对齐（存储位置 / 待审批 / 新增 / 删除 / 重置密码 / 页面配置）。

     ⚠️ 两个容易写错的语义，都是照 MsPortal 那一份移植过来的：
       · allowedGroups 是「分组规范名/ id」数组，而三边的分组体系不同 —— 所以面板给
         两组 chips（本页分组 + 统一门户业务分组），同写进一个 allowedGroups。
         只提供本侧一组，保存就会把对方设的白名单整条覆盖掉。
       · landing 是整对象替换，必须 view + cardId 一起回填一起提交，否则落地视图被清。
     与 MsPortal 唯一有意的差别：文案里「本页」指 /olbrportal/，白名单空了会立刻
     体现在本页自己的卡片流上（同一份 access.js），所以保存自己时顺手走 renderCatalog()。 */
  var UM_API = '/uniplam/api/auth';

  function umCall(path, init) {
    var headers = { Accept: 'application/json' };
    var token = tok();
    if (token) headers.Authorization = 'Bearer ' + token;
    var opts = /** @type {RequestInit} */ ({ method: (init && init.method) || 'GET', credentials: 'same-origin', headers: headers });
    if (init && init.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(init.body);
    }
    return fetch(UM_API + path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        if (r.status === 401) umDropSession();
        return { ok: r.ok, status: r.status, data: data || {} };
      });
    });
  }

  /* 会话过期：清本地 token 回到登录门禁（与 uniplam 的 apiFetch 一致）。
     弹窗必须一起关掉 —— 留着一个调不动接口的空壳，只会让人以为是自己点错了。 */
  function umDropSession() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    state.user = null; state.authOk = false;
    closeUserMgmt();
    renderGate(); renderWho();
  }

  /** 服务端错误文案 → 当前语言的可读提示（认不出的原因原样透出，便于排查） */
  function umErrorText(status, detail) {
    var d = String(detail || '');
    if (d === 'cannot delete yourself') return t('um.selfDelete');
    if (d === 'cannot delete the last admin') return t('um.lastAdmin');
    if (status === 409) return t('um.duplicate');
    if (d === 'admin role required') return t('um.needAdmin');
    if (d === 'request not found, already handled, or username taken') return t('um.notFound');
    if (d === 'request not found or already handled') return t('um.notFound');
    if (d.indexOf('password must be at least') === 0) return t('um.pwdTooShort');
    if (d.indexOf('username must be') === 0) return t('um.invalidInput');
    if (status === 400) return t('um.invalidInput');
    return d || ('HTTP ' + status);
  }

  function umSet(patch) {
    Object.keys(patch).forEach(function (k) { state.um[k] = patch[k]; });
    renderUserMgmt();
  }

  /** 顶部提示条：成功 3 秒后自动消失，失败一直留着（用户要看清原因） */
  function umFlash(kind, msg) {
    var patch = { success: kind === 'ok' ? msg : '', error: kind === 'err' ? msg : '' };
    umSet(patch);
    if (kind === 'ok') {
      // @ts-expect-error 函数对象上挂 setTimeout 句柄用于防重入清除
      clearTimeout(umFlash._t);
      // @ts-expect-error 同上：umFlash._t 是 timeout 句柄，非函数自身属性
      umFlash._t = setTimeout(function () {
        if (state.um.success === msg) umSet({ success: '' });
      }, 3000);
    }
  }

  /** 本页的视图分组清单：value = 分组 id（如 'BO View'），标签跟着语言走 */
  function umMsGroups() {
    return state.groups.map(function (g) { return { id: g.id, label: gName(g.id) }; });
  }

  /** 统一门户的业务分组：来自 GET /uniplam/api/portal-default 的 groups。
      拿不到时返回 null，面板给出说明而不是画空列表。 */
  function umPortalGroups() {
    var g = state.um.portalGroups;
    if (!Array.isArray(g) || !g.length) return null;
    return g.map(function (name) { return { id: String(name), label: String(name) }; });
  }

  function umPortalGroupLabel(cat) {
    var map = state.um.portalGroupLabels;
    if (map && typeof map === 'object' && map[cat]) return String(map[cat]);
    return String(cat || '');
  }

  /** 跨门户共用的看板 id（access.js 的映射表）；ACC 只剩兜底 stub 时退回按编号推导 */
  function accId(it) {
    return typeof ACC.dashboardAccessId === 'function' ? ACC.dashboardAccessId(it) : ('ms-item-' + (it && it.no));
  }

  /** 「按看板」候选项是否来自统一门户的全局目录。
      只有这一份的 id 是 DashboardItem.id —— allowedCards 存的就是它。
      读不到时退化成按映射表推导的 id，此时面板会锁住候选项并给出说明：
      在这种状态下保存会往共用字段里写对方认不出的值。 */
  function umCardsAreShared() {
    return !!(state.um.portalDashboards && state.um.portalDashboards.length);
  }

  function umCards() {
    var shared = state.um.portalDashboards;
    if (Array.isArray(shared) && shared.length) {
      return shared.map(function (d) {
        return { id: String(d.id), label: String(d.title || d.id), group: umPortalGroupLabel(d.category) };
      });
    }
    return ITEMS.map(function (it) {
      return { id: accId(it), label: titleOf(it), group: gName((it.groups || [])[0]) };
    });
  }

  /** 拉齐弹窗要用的四份数据。任一项失败都不影响其余项展示。 */
  function loadUserMgmt() {
    state.um.loading = true;
    state.um.error = '';
    renderUserMgmt();

    var jobs = [
      umCall('/users').then(function (r) {
        if (!r.ok) {
          state.um.error = tf('um.requestFail', { msg: umErrorText(r.status, r.data && r.data.detail) });
          return;
        }
        state.um.users = Array.isArray(r.data.users) ? r.data.users : [];
      }),
      umCall('/register-requests').then(function (r) {
        if (r.ok && Array.isArray(r.data.requests)) state.um.requests = r.data.requests;
      }),
      umCall('/storage').then(function (r) {
        if (r.ok && r.data.storage) state.um.storage = r.data.storage;
      }),
      fetch('/uniplam/api/portal-default', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          state.um.portalGroups = d && Array.isArray(d.groups) ? d.groups : null;
          state.um.portalGroupLabels = d && d.groupLabels && typeof d.groupLabels === 'object' ? d.groupLabels : null;
          state.um.portalDashboards = d && Array.isArray(d.dashboards) ? d.dashboards : null;
          state.um.portalGroupsErr = !(d && Array.isArray(d.groups) && d.groups.length);
        })
        .catch(function () {
          state.um.portalGroups = null;
          state.um.portalGroupLabels = null;
          state.um.portalDashboards = null;
          state.um.portalGroupsErr = true;
        })
    ];

    return Promise.all(jobs).then(function () {
      state.um.loading = false;
      renderUserMgmt();
    });
  }

  function openUserMgmt() {
    var mask = $('#umMask');
    if (!mask) return;
    var user = state.user;
    if (!user || user.role !== 'admin') { toast(t('um.needAdmin')); return; }
    /* 没有 id = 这是 my_app 的占位身份（本机 local / 免登录 dev-admin），不是门户账号；
       门户的用户接口只认门户会话。原来这里只弹一句「请先登录」就返回 ——
       而当时页面上并没有任何登录入口（见 renderWho 的注释），等于把人指向一个
       不存在的地方。现在直接把登录/注册闸门唤起来（「主动唤起」那一档，带取消，
       随时能退回只读界面），并记下意图：登录成功后自动把用户管理面板打开。 */
    if (!user.id) {
      state.gateMode = 'login'; state.gateOpen = true; state.umAfterLogin = true;
      renderGate();
      window.scrollTo(0, 0);
      toast(t('um.needPortalLogin'));
      return;
    }
    state.um.open = true;
    /* 每次打开都清掉上一轮的草稿与提示，避免「上次没保存的勾选」被当成现状 */
    state.um.error = ''; state.um.success = '';
    state.um.nu = ''; state.um.np = ''; state.um.nr = 'viewer';
    state.um.resetId = ''; state.um.resetPwd = '';
    state.um.approveRoles = {};
    state.um.profileId = '';
    state.um.saving = false;
    state.um.busy = '';
    mask.hidden = false;
    loadUserMgmt();
  }

  function closeUserMgmt() {
    var mask = $('#umMask');
    if (mask) mask.hidden = true;
    state.um.open = false;
  }

  /** 页面配置面板：用服务端返回的账号数据回填（含 view，避免保存时把落地视图清掉） */
  function umOpenProfile(u) {
    var landing = u.landing || {};
    state.um.profileId = u.id;
    state.um.pv = landing.view || '';
    state.um.pc = landing.cardId || '';
    state.um.restricted = u.allowedGroups != null || u.allowedCards != null;
    state.um.groups = Array.isArray(u.allowedGroups) ? u.allowedGroups.slice() : [];
    state.um.cards = Array.isArray(u.allowedCards) ? u.allowedCards.slice() : [];
    state.um.error = '';
    state.um.success = '';
    renderUserMgmt();
    var el = $('[data-um="landing-view"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }

  function umToggle(list, value) {
    var next = list.slice();
    var i = next.indexOf(value);
    if (i === -1) next.push(value); else next.splice(i, 1);
    return next;
  }

  function umHasProfile(u) {
    return !!u.landing || u.allowedGroups != null || u.allowedCards != null;
  }

  var UM_VIEWS = ['grid', 'list', 'matrix', 'tasks'];
  function umViewLabel(v) {
    return { grid: t('um.viewGrid'), list: t('um.viewList'), matrix: t('um.viewMatrix'), tasks: t('um.viewTasks') }[v] || v;
  }

  /* ------------------------------------------------------ 用户管理：渲染 -- */

  /* 与 MsPortal/assets/portal.js 同名函数同一口径：后端给的是服务器绝对路径，
     整条上屏会暴露部署目录，且路径里的中文目录名在英文模式下是漏翻。只留文件名。 */
  function storageNameOf(loc) {
    var s = String(loc || '');
    var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function umStorageHtml() {
    var st = state.um.storage;
    if (!st) return '';
    var bits = [
      '<span class="um-tag">' + esc(st.backend === 'sqlite' ? t('um.storageSqlite') : t('um.storageJson')) + '</span>',
      '<span>' + esc(tf('um.backups', { n: (st.backups || []).length })) + '</span>'
    ];
    if (st.lastWriteAt) {
      bits.push('<span>' + esc(t('um.lastWrite')) + ' ' +
        esc(String(st.lastWriteAt).slice(0, 19).replace('T', ' ')) + '</span>');
    }
    if (st.migratedFromJson) bits.push('<span class="um-warn">' + esc(t('um.migrated')) + '</span>');
    return '<div class="um-storage">' + ic('table') +
      '<div class="um-storage-txt">' +
        '<div class="um-storage-row"><b>' + esc(t('um.storage')) + '</b>' + bits.join('') + '</div>' +
        '<div class="um-mono" title="' + esc(storageNameOf(st.location)) + '">' + esc(storageNameOf(st.location)) + '</div>' +
      '</div></div>';
  }

  function umRequestsHtml() {
    var list = state.um.requests || [];
    var rows = list.length
      ? list.map(function (r) {
          var role = state.um.approveRoles[r.id] || 'viewer';
          return '<tr>' +
            '<td class="um-strong">' + esc(r.username) + '</td>' +
            '<td class="um-dim um-ellipsis" title="' + esc(r.note || '') + '">' + esc(r.note || '—') + '</td>' +
            '<td class="um-dim um-mono">' + esc(String(r.createdAt || '').slice(0, 19).replace('T', ' ')) + '</td>' +
            '<td class="um-dim um-mono">' + esc(r.ip || '') + '</td>' +
            '<td class="um-right"><span class="um-row-actions">' +
              '<select data-um="approve-role" data-id="' + esc(r.id) + '" aria-label="' + esc(t('um.colRole')) + '">' +
                '<option value="viewer"' + (role === 'viewer' ? ' selected' : '') + '>' + esc(t('um.roleViewer')) + '</option>' +
                '<option value="admin"' + (role === 'admin' ? ' selected' : '') + '>' + esc(t('um.roleAdmin')) + '</option>' +
              '</select>' +
              '<button type="button" class="gb um-primary" data-um="approve" data-id="' + esc(r.id) + '"' +
                (state.um.busy === 'decide' ? ' disabled' : '') + '>' + ic('user-check') + esc(t('um.approve')) + '</button>' +
              '<button type="button" class="gb um-danger" data-um="reject" data-id="' + esc(r.id) + '"' +
                (state.um.busy === 'decide' ? ' disabled' : '') + '>' + ic('user-x') + esc(t('um.reject')) + '</button>' +
            '</span></td></tr>';
        }).join('')
      : '<tr><td colspan="5" class="um-empty">' + esc(t('um.pendingEmpty')) + '</td></tr>';

    return '<div class="um-box um-box-warn">' +
      '<div class="um-box-head">' + ic('clock') + '<span>' + esc(t('um.pendingTitle')) + '</span>' +
        (list.length ? '<span class="um-pill">' + list.length + '</span>' : '') +
      '</div>' +
      '<div class="um-scroll"><table class="um-table">' +
        '<thead><tr>' +
          '<th>' + esc(t('um.colApplicant')) + '</th>' +
          '<th>' + esc(t('um.colNote')) + '</th>' +
          '<th>' + esc(t('um.colTime')) + '</th>' +
          '<th>' + esc(t('um.colIp')) + '</th>' +
          '<th class="um-right">' + esc(t('um.colActions')) + '</th>' +
        '</tr></thead><tbody>' + rows + '</tbody>' +
      '</table></div></div>';
  }

  function umAddFormHtml() {
    var busy = state.um.busy === 'add';
    return '<form class="um-box um-add" id="umAddForm">' +
      '<div class="um-box-head">' + ic('user-plus') + '<span>' + esc(t('um.addTitle')) + '</span></div>' +
      '<div class="um-add-row">' +
        '<input type="text" id="umNewUser" autocomplete="off" placeholder="' + esc(t('um.usernamePh')) + '" value="' + esc(state.um.nu) + '">' +
        '<input type="password" id="umNewPass" autocomplete="new-password" placeholder="' + esc(t('um.passwordPh')) + '" value="' + esc(state.um.np) + '">' +
        '<select id="umNewRole">' +
          '<option value="viewer"' + (state.um.nr === 'viewer' ? ' selected' : '') + '>' + esc(t('um.roleViewer')) + '</option>' +
          '<option value="admin"' + (state.um.nr === 'admin' ? ' selected' : '') + '>' + esc(t('um.roleAdmin')) + '</option>' +
        '</select>' +
        '<button type="submit" class="gb um-primary" id="umAddBtn"' +
          (busy ? ' disabled' : '') + '>' + ic('plus') + esc(t('um.add')) + '</button>' +
      '</div></form>';
  }

  function umProfileHtml(u) {
    var msGroups = umMsGroups();
    var portalGroups = umPortalGroups();
    var cards = umCards();

    function chips(kind, list, locked) {
      return list.map(function (g) {
        var on = state.um[kind].indexOf(g.id) !== -1;
        return '<button type="button" class="um-chip' + (on ? ' is-on' : '') + '"' +
          (locked ? ' disabled aria-disabled="true"' : '') +
          ' aria-pressed="' + (on ? 'true' : 'false') + '"' +
          ' data-um="' + (kind === 'groups' ? 'group' : 'card') + '" data-val="' + esc(g.id) + '">' +
          esc(g.label) + '</button>';
      }).join('');
    }

    var landingCards = '<option value="">' + esc(t('um.landingNoCard')) + '</option>' +
      cards.map(function (c) {
        return '<option value="' + esc(c.id) + '"' + (state.um.pc === c.id ? ' selected' : '') + '>' +
          esc(c.group) + ' · ' + esc(c.label) + '</option>';
      }).join('');

    return '<tr class="um-profile-row"><td colspan="4">' +
      '<div class="um-profile">' +
        '<div class="um-profile-head">' + ic('dashboard') +
          '<b>' + esc(tf('um.pagesTitle', { name: u.username })) + '</b>' +
          '<span class="um-dim">' + esc(t('um.pagesSubtitle')) + '</span></div>' +

        '<div class="um-field">' +
          '<span class="um-label">' + esc(t('um.landing')) + '</span>' +
          '<select data-um="landing-view" aria-label="' + esc(t('um.landing')) + '">' +
            '<option value="">' + esc(t('um.landingNone')) + '</option>' +
            UM_VIEWS.map(function (v) {
              return '<option value="' + v + '"' + (state.um.pv === v ? ' selected' : '') + '>' + esc(umViewLabel(v)) + '</option>';
            }).join('') +
          '</select>' +
          '<select data-um="landing-card" aria-label="' + esc(t('um.landingNoCard')) + '">' + landingCards + '</select>' +
        '</div>' +

        '<div class="um-field um-field-col">' +
          '<label class="um-check">' +
            '<input type="checkbox" data-um="restricted"' + (state.um.restricted ? ' checked' : '') + '>' +
            '<span>' + esc(state.um.restricted ? t('um.allowedCustom') : t('um.allowedAll')) + '</span>' +
          '</label>' +
        '</div>' +

        (state.um.restricted ?
          '<div class="um-groups">' +
            '<div class="um-group-block">' +
              '<p class="um-label">' + esc(t('um.groupsMsportal')) + '（' + state.um.groups.filter(function (g) {
                return msGroups.some(function (x) { return x.id === g; });
              }).length + '/' + msGroups.length + '）</p>' +
              '<div class="um-chips">' + chips('groups', msGroups) + '</div>' +
            '</div>' +
            '<div class="um-group-block">' +
              '<p class="um-label">' + esc(t('um.groupsPortal')) + (portalGroups ?
                '（' + state.um.groups.filter(function (g) {
                  return portalGroups.some(function (x) { return x.id === g; });
                }).length + '/' + portalGroups.length + '）' : '') + '</p>' +
              (portalGroups
                ? '<div class="um-chips">' + chips('groups', portalGroups) + '</div>'
                : '<p class="um-dim">' + esc(t('um.groupsPortalNone')) + '</p>') +
            '</div>' +
            '<div class="um-group-block">' +
              '<p class="um-label">' + esc(t('um.allowedCards')) + '（' + state.um.cards.length + '/' + cards.length + '）</p>' +
              '<div class="um-chips">' + chips('cards', cards, !umCardsAreShared()) + '</div>' +
              (umCardsAreShared() ? '' : '<p class="um-warn">' + ic('warning') + esc(t('um.cardsLocalOnly')) + '</p>') +
            '</div>' +
            (state.um.groups.length === 0 && state.um.cards.length === 0
              ? '<p class="um-warn">' + ic('warning') + esc(t('um.allowedEmpty')) + '</p>' : '') +
          '</div>' : '') +

        '<p class="um-dim um-hint">' + esc(t('um.allowedHint')) + ' ' + esc(t('um.navVisibilityOnly')) + '</p>' +
      '</div></td></tr>';
  }

  /* 账号表。两张表（待审批 / 账号）tr 结构相似，排查时需要一个明确锚点区分，
     所以外层带 data-um="users-table"。 */
  function umUsersHtml() {
    var u = state.um;
    if (u.loading && !u.users.length) {
      return '<div class="um-box" data-um="users-table"><div class="um-empty">' + esc(t('um.loading')) + '</div></div>';
    }
    var admins = u.users.filter(function (x) { return x.role === 'admin'; }).length;
    var me = state.user;

    var rows = u.users.map(function (x) {
      var isSelf = !!me && me.id === x.id;
      var lastAdmin = x.role === 'admin' && admins <= 1;
      var blocked = isSelf || lastAdmin;
      var open = u.profileId === x.id;
      var out = '<tr' + (open ? ' class="is-open"' : '') + '>' +
        '<td class="um-strong">' + esc(x.username) +
          (isSelf ? '<span class="um-self">' + esc(t('um.self')) + '</span>' : '') + '</td>' +
        '<td><span class="um-role' + (x.role === 'admin' ? ' is-admin' : '') + '">' +
          (x.role === 'admin' ? ic('shield') : '') +
          esc(x.role === 'admin' ? t('um.roleAdmin') : t('um.roleViewer')) + '</span></td>' +
        '<td class="um-dim um-mono">' + esc(String(x.createdAt || '').slice(0, 19).replace('T', ' ')) + '</td>' +
        '<td class="um-right"><span class="um-row-actions">' +
          '<button type="button" class="um-icon-btn' + (umHasProfile(x) ? ' is-on' : '') + '" data-um="profile" data-id="' + esc(x.id) + '"' +
            ' title="' + esc(t('um.pages')) + '" aria-label="' + esc(t('um.pages')) + '">' + ic('dashboard') + '</button>' +
          '<button type="button" class="um-icon-btn" data-um="reset" data-id="' + esc(x.id) + '"' +
            ' title="' + esc(t('um.reset')) + '" aria-label="' + esc(t('um.reset')) + '">' + ic('key') + '</button>' +
          '<button type="button" class="um-icon-btn is-danger" data-um="delete" data-id="' + esc(x.id) + '"' +
            (blocked ? ' disabled' : '') +
            ' title="' + esc(blocked ? (isSelf ? t('um.selfDelete') : t('um.lastAdmin')) : t('um.delete')) + '"' +
            ' aria-label="' + esc(t('um.delete')) + '">' + ic('trash') + '</button>' +
        '</span></td></tr>';

      if (u.resetId === x.id) {
        out += '<tr class="um-inline-row"><td colspan="4"><div class="um-inline">' +
          '<span class="um-dim">' + esc(tf('um.resetHint', { name: x.username })) + '</span>' +
          '<input type="password" data-um="reset-pwd" autocomplete="new-password" placeholder="' +
            esc(t('um.passwordPh')) + '" value="' + esc(u.resetPwd) + '">' +
          '<button type="button" class="gb um-primary" data-um="reset-confirm" data-id="' + esc(x.id) + '"' +
            (u.busy === 'reset' || !u.resetPwd ? ' disabled' : '') + '>' + ic('check') + esc(t('um.resetConfirm')) + '</button>' +
        '</div></td></tr>';
      }
      if (open) out += umProfileHtml(x);
      return out;
    }).join('');

    return '<div class="um-box" data-um="users-table"><div class="um-scroll"><table class="um-table">' +
      '<thead><tr>' +
        '<th>' + esc(t('um.colUser')) + '</th>' +
        '<th>' + esc(t('um.colRole')) + '</th>' +
        '<th>' + esc(t('um.colCreated')) + '</th>' +
        '<th class="um-right">' + esc(t('um.colActions')) + '</th>' +
      '</tr></thead><tbody>' +
      (rows || '<tr><td colspan="4" class="um-empty">' + esc(t('um.empty')) + '</td></tr>') +
      '</tbody></table></div></div>';
  }

  /** 整块重画弹窗体（输入到一半的值都取自 state.um，不会被清掉） */
  function renderUserMgmt() {
    var body = $('#umBody');
    if (!body) return;
    var u = state.um;

    var html = '';
    if (u.success) html += '<div class="um-banner is-ok">' + ic('check-circle') + '<span>' + esc(u.success) + '</span></div>';
    if (u.error) html += '<div class="um-banner is-err">' + ic('warning') + '<span>' + esc(u.error) + '</span></div>';
    html += umStorageHtml() + umRequestsHtml() + umAddFormHtml() + umUsersHtml();
    body.innerHTML = html;

    /* 底部固定操作栏：只在页面配置面板展开时出现（与 uniplam 的布局一致） */
    var foot = $('#umFoot');
    var profileUser = null;
    for (var i = 0; i < u.users.length; i++) {
      if (u.users[i].id === u.profileId) { profileUser = u.users[i]; break; }
    }
    if (foot) {
      foot.hidden = !profileUser;
      var who = $('#umFootWho');
      if (who) who.textContent = profileUser ? tf('um.pagesTitle', { name: profileUser.username }) : '';
      var save = $('#umSaveBtn');
      if (save) save.disabled = !!u.saving;
    }
  }

  /* ------------------------------------------------------ 用户管理：动作 -- */

  function umAddUser() {
    if (state.um.busy === 'add') return;
    var username = String(state.um.nu || '').trim().toLowerCase();
    var password = String(state.um.np || '');
    if (password.length < 8) { umFlash('err', t('um.pwdTooShort')); return; }
    state.um.busy = 'add';
    renderUserMgmt();
    umCall('/users', { method: 'POST', body: { username: username, password: password, role: state.um.nr } })
      .then(function (r) {
        if (!r.ok) { umFlash('err', umErrorText(r.status, r.data && r.data.detail)); return; }
        state.um.nu = ''; state.um.np = ''; state.um.nr = 'viewer';
        umFlash('ok', t('um.added'));
        return loadUserMgmt();
      })
      .catch(function (e) { umFlash('err', String(e)); })
      .then(function () { state.um.busy = ''; renderUserMgmt(); });
  }

  function umDeleteUser(id) {
    var target = state.um.users.filter(function (x) { return x.id === id; })[0];
    if (!target) return;
    if (!window.confirm(tf('um.confirmDelete', { name: target.username }))) return;
    umCall('/users/delete', { method: 'POST', body: { id: id } })
      .then(function (r) {
        if (!r.ok) { umFlash('err', umErrorText(r.status, r.data && r.data.detail)); return; }
        if (state.um.profileId === id) state.um.profileId = '';
        return loadUserMgmt();
      })
      .catch(function (e) { umFlash('err', String(e)); });
  }

  function umResetPassword(id) {
    if (state.um.busy === 'reset') return;
    var target = state.um.users.filter(function (x) { return x.id === id; })[0];
    var pwd = String(state.um.resetPwd || '');
    if (pwd.length < 8) { umFlash('err', t('um.pwdTooShort')); return; }
    state.um.busy = 'reset';
    renderUserMgmt();
    umCall('/users/reset-password', { method: 'POST', body: { id: id, newPassword: pwd } })
      .then(function (r) {
        if (!r.ok) { umFlash('err', umErrorText(r.status, r.data && r.data.detail)); return; }
        state.um.resetId = ''; state.um.resetPwd = '';
        umFlash('ok', tf('um.resetOk', { name: target ? target.username : '' }));
        return loadUserMgmt();
      })
      .catch(function (e) { umFlash('err', String(e)); })
      .then(function () { state.um.busy = ''; renderUserMgmt(); });
  }

  function umDecide(id, action) {
    var target = state.um.requests.filter(function (r) { return r.id === id; })[0];
    if (!target) return;
    var ask = action === 'approve'
      ? tf('um.approveConfirm', { name: target.username })
      : tf('um.rejectConfirm', { name: target.username });
    if (!window.confirm(ask)) return;
    var body = action === 'approve'
      ? { id: id, role: state.um.approveRoles[id] || 'viewer' }
      : { id: id };
    state.um.busy = 'decide';
    renderUserMgmt();
    umCall('/register-requests/' + action, { method: 'POST', body: body })
      .then(function (r) {
        if (!r.ok) { umFlash('err', umErrorText(r.status, r.data && r.data.detail)); return; }
        umFlash('ok', tf(action === 'approve' ? 'um.approved' : 'um.rejected', { name: target.username }));
        return loadUserMgmt();
      })
      .catch(function (e) { umFlash('err', String(e)); })
      .then(function () { state.um.busy = ''; renderUserMgmt(); });
  }

  /** 保存页面配置。
      不受限 → 两个维度都传 null；受限 → 传勾选结果（空数组 = 什么都看不到）。
      landing 必须带 view + cardId 一起提交：服务端是整对象替换。 */
  function umSaveProfile() {
    if (state.um.saving) return;
    var id = state.um.profileId;
    var target = state.um.users.filter(function (x) { return x.id === id; })[0];
    if (!target) return;
    state.um.saving = true;
    renderUserMgmt();

    var landing = (state.um.pv || state.um.pc)
      ? (function () {
          var o = {};
          if (state.um.pv) o.view = state.um.pv;
          if (state.um.pc) o.cardId = state.um.pc;
          return o;
        })()
      : null;

    umCall('/users/profile', {
      method: 'POST',
      body: {
        id: id,
        landing: landing,
        allowedGroups: state.um.restricted ? state.um.groups : null,
        allowedCards: state.um.restricted ? state.um.cards : null
      }
    }).then(function (r) {
      if (!r.ok || !r.data.user) { umFlash('err', umErrorText(r.status, r.data && r.data.detail)); return; }
      var saved = r.data.user;
      state.um.users = state.um.users.map(function (x) { return x.id === saved.id ? saved : x; });
      state.um.profileId = '';
      umFlash('ok', tf('um.pagesSaved', { name: target.username }));
      /* 改的是自己 → 本页可见范围当场变了（canSee 读的就是这一份），必须重画。
         走 renderCatalog() 而不是 render()：后者会重建地图 iframe。 */
      if (state.user && state.user.id === saved.id) {
        state.user = saved;
        renderCatalog();
      }
    }).catch(function (e) {
      umFlash('err', String(e));
    }).then(function () {
      state.um.saving = false;
      renderUserMgmt();
    });
  }

  /** 重置密码输入框内容变化时只切「确认重置」的可用态，避免整块重绘丢焦点 */
  function syncUmResetBtn() {
    var btn = $('[data-um="reset-confirm"]');
    if (btn) btn.disabled = !String(state.um.resetPwd || '');
  }

  /** 用户管理弹窗的文档级事件委托（面板是整块重画的，不能逐个 addEventListener） */
  function bindUserMgmt() {
    var mask = $('#umMask');
    if (!mask) return;

    $('#umBtn').addEventListener('click', openUserMgmt);
    $('#umClose').addEventListener('click', closeUserMgmt);
    mask.addEventListener('click', function (e) { if (e.target === mask) closeUserMgmt(); });
    $('#umReload').addEventListener('click', function () { loadUserMgmt(); });
    $('#umCancelBtn').addEventListener('click', function () {
      state.um.profileId = '';
      renderUserMgmt();
    });
    $('#umSaveBtn').addEventListener('click', umSaveProfile);

    /* 输入类：直接写回 state.um，不做重绘（重绘会打断输入） */
    mask.addEventListener('input', function (e) {
      var el = e.target;
      var act = el.getAttribute && el.getAttribute('data-um');
      if (act === 'reset-pwd') { state.um.resetPwd = el.value; syncUmResetBtn(); return; }
      if (el.id === 'umNewUser') { state.um.nu = el.value; return; }
      if (el.id === 'umNewPass') { state.um.np = el.value; return; }
    });
    mask.addEventListener('change', function (e) {
      var el = e.target;
      var act = el.getAttribute && el.getAttribute('data-um');
      if (el.id === 'umNewRole') { state.um.nr = el.value; return; }
      if (act === 'approve-role') { state.um.approveRoles[el.getAttribute('data-id')] = el.value; return; }
      if (act === 'landing-view') { state.um.pv = el.value; return; }
      if (act === 'landing-card') { state.um.pc = el.value; return; }
      if (act === 'restricted') { state.um.restricted = !!el.checked; renderUserMgmt(); return; }
    });
    mask.addEventListener('submit', function (e) {
      if (e.target && e.target.id === 'umAddForm') { e.preventDefault(); umAddUser(); }
    });

    mask.addEventListener('click', function (e) {
      var el = e.target.closest ? e.target.closest('[data-um]') : null;
      if (!el) return;
      var act = el.getAttribute('data-um');
      var id = el.getAttribute('data-id');
      if (act === 'group') { state.um.groups = umToggle(state.um.groups, el.getAttribute('data-val')); renderUserMgmt(); return; }
      /* 全局目录读不到时「按看板」候选项是 disabled 的（id 空间不对，见 umCardsAreShared），
         这里再挡一次：disabled 只是渲染属性，不能当成唯一防线。 */
      if (act === 'card') {
        if (!umCardsAreShared()) { toast(t('um.cardsLocalOnly')); return; }
        state.um.cards = umToggle(state.um.cards, el.getAttribute('data-val'));
        renderUserMgmt(); return;
      }
      if (act === 'profile') {
        if (state.um.profileId === id) { state.um.profileId = ''; renderUserMgmt(); }
        else {
          var uu = state.um.users.filter(function (x) { return x.id === id; })[0];
          if (uu) umOpenProfile(uu);
        }
        return;
      }
      if (act === 'reset') {
        state.um.resetId = state.um.resetId === id ? '' : id;
        state.um.resetPwd = '';
        state.um.error = '';
        renderUserMgmt();
        var inp = $('[data-um="reset-pwd"]');
        if (inp) inp.focus();
        return;
      }
      if (act === 'reset-confirm') { umResetPassword(id); return; }
      if (act === 'delete') { umDeleteUser(id); return; }
      if (act === 'approve') { umDecide(id, 'approve'); return; }
      if (act === 'reject') { umDecide(id, 'reject'); return; }
    });
  }

  /* ---------------------------------------------------------------- QC -- */
  function api(u) {
    return fetch(u, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      if (!r.ok) throw new Error('HTTP ' + r.status);
      /* my_app 的 catch-all 会把未注册的 /api/* 也回成 SPA 的 index.html（200 + text/html） */
      if (ct.indexOf('json') === -1) throw new Error('non-JSON');
      return r.json();
    });
  }
  var qcFullBusy = false, qcAlarmBusy = false;
  function loadQc(force) {
    if (qcFullBusy) return;
    qcFullBusy = true;
    api('/api/portal-qc/summary' + (force ? '?refresh=1' : '')).then(function (d) {
      qcFullBusy = false;
      var m = d.metrics || {};
      state.qc = { loading: false, err: '', at: d.generated_at ? new Date(d.generated_at).getTime() : Date.now(), m: m };
      state.qcFullAt = d.generated_at || '';
      /* 全量响应里也带 alarm（同一口径、同一段 SQL），一并接管：首屏在第一次 ?only=alarm
         回来之前就有配对的数字与时间戳；点「刷新」走全量，也不会出现「数是新的、
         时间戳还是 5 分钟前那份」。失败分支不动 alarm —— 它有自己的循环和错误态。 */
      if (m.alarm) state.qcAlarm = m.alarm;
      if (state.qcFullAt) state.qcAlarmAt = state.qcFullAt;
      renderBand();
      fetchQcTrend();          /* 趋势粒度是小时/天，跟全量同节奏就够 */
      /* 紧跟在 fetchQcTrend 之后，且必须在 stats 已写入 state 之后调用：
         快照的采集点在统计更新之后，先拉 history 会少掉最新那个点，
         CRs / PMT 的线就会比卡片上的大数字「旧一格」。 */
      fetchQcHistory();
    }).catch(function (e) {
      qcFullBusy = false;
      state.qc = { loading: false, err: (e && e.message) || String(e), at: 0, m: {} };
      state.qcFullAt = '';
      renderBand();
    });
  }
  /* 只刷「未清除的断站告警」：走 ?only=alarm，后端只跑那一条 COUNT。
     失败时把 alarm 置成 error 态而不是保留旧值 —— 宁可显示「不可用」，
     也不要让一小时前的告警数冒充实时值，这是这块面板最要紧的一格。 */
  function loadQcAlarm() {
    if (qcAlarmBusy) return;
    qcAlarmBusy = true;
    api('/api/portal-qc/summary?only=alarm').then(function (d) {
      qcAlarmBusy = false;
      var m = d && d.metrics && d.metrics.alarm;
      if (!m) throw new Error(t('qc.na'));
      state.qcAlarm = m;
      state.qcAlarmAt = (d && d.generated_at) || '';
      renderBand();
    }).catch(function (e) {
      qcAlarmBusy = false;
      state.qcAlarm = { value: null, error: (e && e.message) || String(e) };
      state.qcAlarmAt = '';
      renderBand();
    });
  }
  /* ==================================================================== v1 ==
     CXO 每日经营指标 + 2/3/4G 当月可用率的数据装载（2026-09-24 加）

     三个接口并行各发一次，互不阻塞：
       · /api/olib-soc-dashboard/overview?days=90
                                          → 四张富卡片（昨日完整值 + 90 天
                                            极值 + WoW/MoM + 30 点迷你走势）
       · /api/vmax-cxo-daily/grid         → 当日进行中的 Total Traffic /
                                            Active User / Video DL Throughput
                                            （富卡片不再用它的大数字，但 tooltip
                                             里的「当日进行中」仍靠它对照）
       · /api/alarm-dashboard/alarm-overview → network_availability[]（2G/3G/FDD）

     为什么允许三路各自成败：三个上游完全独立（一个读 my_app 的 olib 日粒度 KPI 库、
     一个读 vmax 汇总表、一个读 Daily_Availability_KPI.xlsx）。串成 Promise.all 的话，
     xlsx 被占用打不开就会让四张富卡片一起空掉 —— 而它们的数据其实好好地在库里。
     所以各自 catch、各自写自己那一半 state，最后统一重绘一次。

     刷新节奏：日粒度数据，上游一天才动一次。这里跟全量 QC 同一档（每小时 :06:30）
     已经绰绰有余，不再单开一个更快的循环 —— 白跑只会给上游加压。
     切回前台时跟 QC 一起补一发（后台标签页定时器会被冻结，不补会看到昨天的数）。 */
  var kpiBusy = false;
  function loadKpi() {
    if (kpiBusy) return;
    kpiBusy = true;
    /* 四路并行（第四路见下方 meta），所以计数是 4。
       ⚠️ 漏改这个数字的后果很隐蔽：done() 永远等不到 0，
       state.kpi.loading 一直为 true、renderKpi 不执行 ——
       页面看上去只是"一直停在骨架屏"，不报任何错。 */
    var left = 4;
    function done() { if (--left === 0) { kpiBusy = false; state.kpi.loading = false; renderKpi(); } }
    /* 富卡片的主数据源。它自己带 status/error。
       失败时**不清空** state.kpi.olib：把上一次的数字擦成 —，
       会让「接口抖了一下」看起来像「指标突然没有了」。保留旧值 + 顶部报错更诚实。 */
    api('/api/olib-soc-dashboard/overview?days=90').then(function (d) {
      if (d && d.status === 'ok' && d.cards && d.cards.length) {
        state.kpi.olib = d;
        state.kpi.err = '';
      } else {
        state.kpi.err = (d && d.error) || t('kpi.err');
      }
      done();
    }).catch(function (e) {
      state.kpi.err = (e && e.message) || String(e);
      done();
    });
    api('/api/alarm-dashboard/alarm-overview').then(function (d) {
      state.kpi.avail = {
        rows: (d && d.network_availability) || [],
        latest_month: (d && d.network_latest_month) || '',
        /* 达标阈值（百分数，如 99.65）。随接口一起取回来，卡片页脚要用它算
           「距阈值」——不要在渲染时另发一个请求，否则同一张卡的数字
           可能来自两次不同时刻的响应（一个已经刷新、一个还没）。 */
        threshold_pct: (d && d.network_threshold_pct != null) ? Number(d.network_threshold_pct) : null,
        updated_at: (d && d.generated_at) || ''
      };
      done();
    }).catch(function () { done(); });
    /* Benchmark 行第一组（2026-10-01 加）：ORANGE vs MTN 的下载/上传/时延对比。
       窗口**由后端给**（传空 start/end，服务端按 default_window(90) 回落，
       但我们只要最近 30 天，所以显式算一个左闭右开的窗口传过去）。
       在**前端**算日期而不是让后端默认 90 天：卡片标题要写「最近 {n} 天」，
       写死的 n 与后端实际窗口一旦不一致，卡上的说明就变成假的。
       算完的 start/end 再回读做 n，两者必然同源。
       失败时**不清空** state.kpi.speed（与 olib 同一条理由：
       接口抖一下不该让三张卡从有数字变成「—」），但也不写 err ——
       这一行的错误不占用标题行那颗全局错误提示，由卡片自己显示「—」。 */
    var sw = recentWindow(30);
    api('/api/bm-speedtest/overview?start=' + sw.start + '&end=' + sw.end).then(function (d) {
      if (d && d.summary) {
        state.kpi.speed = {
          summary: d.summary,
          wins: d.wins || null,
          /* 逐日记录（2026-10-01 加，卡片走势图要用）。
             ⚠️ 直接存 overview 的 daily，**不再打一次 /trend**：同一个窗口下
             /trend 的 series 与 overview 的 daily 是同一段 SQL 的结果，
             多打一次只会多一个"图与大数字来自不同时刻"的分叉点。
             ⚠️ overview 对超过 400 天的窗口会截断（daily_truncated），
             本页窗口固定 30 天，够用；真被截断时图只会短一截，
             不会画错 —— 但那时卡片标题的天数与线的长度会对不上，
             所以这里把截断标志一起留着，将来要提示有据可依。 */
          daily: d.daily || [],
          dailyTruncated: !!(d.meta && d.meta.daily_truncated),
          meta: d.meta || {},
          /* 窗口天数取**接口回显的** start/end 算，不取我们请求时那个数：
             后端在 start >= end 时会回落到默认窗口，那时请求的 30 就不是真实窗口了。 */
          days: windowDays(d.meta, sw),
          at: (d.meta && d.meta.data_max_date) || ''
        };
      }
      done();
    }).catch(function () { done(); });
    /* Benchmark 行第二组（2026-09-30 加）：Meta 基准报告（my_app `?page=bm_meta`）。
       与上面那路**共用同一个窗口对象 sw**，而不是各算一次「最近 30 天」：
       两次 new Date() 跨过午夜时（或一先一后落在不同秒），两组卡上的窗口会差一天，
       而它们印在同一个标题底下、页脚还分别写着「统计窗口 30 天」——
       差一天就是两个窗口，读者无法判断哪张卡跟哪张卡能比。
       接口默认窗口是 365 天（见 bm_meta_caliber.default_window），
       所以这里**必须**显式传 start/end。
       失败时同样**不清空** state.kpi.meta：接口抖一下不该让 3 张卡从有数字变成「—」；
       错误也不写 kpi.err（理由同上：这一行由卡片自己显示「—」）。 */
    api('/api/bm-meta/overview?start=' + sw.start + '&end=' + sw.end).then(function (d) {
      if (d && d.summary) {
        state.kpi.meta = {
          summary: d.summary,
          scores: d.scores || null,
          wins: d.wins || null,
          /* covered 用**实际拿到的逐日条数**，不用 meta.daily_returned：
             后者是后端自己对同一次的表述，而卡片要说的正是"我手里有几天"。
             两者正常情况下相等，一旦不等（例如将来加了截断），
             页脚会跟着真正在渲染的数据走，不会出现"说 358 天、其实只画了 90 天"。 */
          covered: (d.daily || []).length,
          /* 逐日记录（2026-10-01 加，卡片走势图要用）。与 covered 取的是
             **同一个数组**：页脚说"覆盖 N 天"与图上画的点数必须同源，
             分别取两次的话（一处用 d.daily.length、一处用 meta.daily_returned）
             将来加了截断就会出现"页脚 358 天、图上只有 90 个点"。
             speed / scores 两张卡用其中的 orange_speed / mtn_speed，
             bp 那张用 bp 列（见 metaSpark）。 */
          daily: d.daily || [],
          /* 窗口天数同样回读接口回显的 start/end（与 speed 一路同一套算法）。 */
          days: windowDays(d.meta, sw),
          at: (d.meta && d.meta.data_max_date) || ''
        };
      }
      done();
    }).catch(function () { done(); });
  }
  /* Benchmark 行两组的统计窗口：最近 n 天，**左闭右开**（end 为次日）。
     与后端 caliber.default_window 完全同一套算法 —— 但这里不能复用它的返回值，
     因为它算的是 90 / 365 天。dayjs 在本页没引，所以直接用 Date 算 UTC 日期串：
     用本地时间的话，跨时区访问门户会得到差一天的窗口，而卡片会把那个天数写在脸上。
     ⚠️ 两组（Ookla / Meta）共用本函数**返回的同一个对象**，见 loadKpi 的说明。 */
  function recentWindow(n) {
    var end = new Date();
    end.setUTCDate(end.getUTCDate() + 1);   // 次日，构成左闭右开
    var start = new Date(end.getTime());
    start.setUTCDate(start.getUTCDate() - n);
    var iso = function (d) { return d.toISOString().slice(0, 10); };
    return { start: iso(start), end: iso(end), n: n };
  }
  /* 真实窗口天数 = 接口回显的 end - start。回显缺失时回落到请求时算的 n。
     ⚠️ 只认 meta 里的 start/end：它们与 summary 出自同一次查询，
     拿本地时间现算会和数据本身对不上（例如接口回落到 90 天时）。
     ⚠️ 必须写 .getTime() 再相减：本文件顶部有 // @ts-check，
     而 TS 不允许直接对两个 Date 做算术（TS2362/TS2363），
     由 npm run lint:shells 把关 —— 直接相减会挡下整个 v1/v2 的类型检查。 */
  function windowDays(meta, fallback) {
    var s = meta && meta.start, e = meta && meta.end;
    if (!s || !e) return fallback ? fallback.n : null;
    var d = (new Date(e + 'T00:00:00Z').getTime() -
             new Date(s + 'T00:00:00Z').getTime()) / 86400000;
    return isFinite(d) && d > 0 ? Math.round(d) : (fallback ? fallback.n : null);
  }

  /* 只请求后端确实有趋势的四个（cr / pmt 回 no_trend，不必白跑一个来回）。
     失败不清空已有趋势：拿不到线只是不画，不是错误状态。 */
  function fetchQcTrend() {
    DATA.QC_TREND_METRICS.forEach(function (id) {
      api('/api/portal-qc/trend?metric=' + id + '&days=30').then(function (d) {
        if (!d || !d.points) return;
        state.qcTrend = state.qcTrend || {};
        state.qcTrend[id] = d;
        renderBand();
      }).catch(function () {});
    });
  }
  /* 存量趋势（2026-09-25 加，给 CRs / PMT 用）。
     与 fetchQcTrend 是**两种口径**，不是同一件事的两次取数：
       /trend   按源表时间列分桶的「新增量」——cr/pmt 回 no_trend，画不出
       /history 每小时快照的「存量」        ——正好补上这两张卡
     后端把 cr/cpmt 的存量放在同一个 series 对象里（cr / pmt / sla 各一条），
     一次请求全拿到，不必按指标发多次。

     ⚠️ 必须在 fetchQcStats **之后**调用：快照的采集点在统计更新之后，
     先拉 history 会少掉最新那个点，卡片上的线就会比大数字「旧一格」。
     失败时**不清空** qcHistory：接口抖一下就抹掉整条线，比留着上一次的线更糟。 */
  function fetchQcHistory() {
    api('/api/portal-qc/history?hours=168').then(function (d) {
      if (!d || !d.series) return;
      state.qcHistory = d.series;
      renderBand();
    }).catch(function () {});
  }
  /* ======================================================== QC 下钻弹窗 --
     2026-09-23 统一：本段由「右侧抽屉」改写为与 /MsPortal/ **同构**的实现。

     改版前本页是 .drawer（右侧滑入）+ table.grid，能力只有「搜索 + 翻页」；
     MsPortal 是居中弹窗 + 可排序表头 + 导出 Excel + 跳完整看板。两边取的是
     同一个接口（/api/portal-qc/detail，同样的 total/rows/columns），
     于是同一个数字点开是两个长相、两种能力 —— 用户会以为是两个系统。

     现在两边的 DOM 类名（.qc-mask/.qc-modal/.qc-table…）与函数行为逐条对齐，
     样式共用 /MsPortal/assets/qcDrill.css。改这里时请对照
     MsPortal/assets/portal.js 的 openQcDrill / closeQcDrill / fetchQcDrill /
     renderQcDrill / exportQcExcel —— 两边要一起改，别只改一边
     （与下面 map embed 那段「两份若要改动，请同时改」是同一条约定）。

     仍然保持只读版的三条红线：不写 msportal.* 键、不 PUT 目录、不改权限判定。
     下面只发 GET /api/portal-qc/* 与本地导出，不触碰任何写接口。 */

  /* 弹窗标题 = 卡片名 + 「· 明细」，并顺带维护「打开完整看板」按钮。
     映射只给**目录里确实存在对应看板**的维度（源码见 MsPortal/portal.js 的
     QC_BOARD_PAGE）：配一个错的链接比不给链接更糟，故不存在的维度一律不配、
     按钮不出现（否则用户点开一个 404 页面，比按钮干脆不出现更难排查）。

     2026-09-26：spms 由 sp_material 改为 **sp_report**，与 MsPortal 同步
     （理由见 MsPortal/assets/portal.js 的 QC_BOARD_PAGE 注释：
     spms 明细是出入库单，sp_report 才是同一批单子的报表）。

     2026-09-26（v1 独有，MsPortal 那两个文件**刻意不改**）：补上 cr / pmt。
     改版前这两项不在这里，理由是「my_app 侧没有对应页面」；现在 my_app 已经有了
     与它们同口径的分析页，这个理由不再成立，于是把按钮接上：
       cr  → cr_analysis   （变更单分析，CrChangeAnalysis）
       pmt → pm_analysis   （预防性维护执行分析，PmExecutionAnalysis）
     ⚠️ 这里必须用 my_app `App.tsx` 的 **PageKey**（`cr_analysis` / `pm_analysis`），
     不是卡片 id（`cr` / `pmt`）也不是接口用的 metric 名 —— `?page=` 走的是
     my_app 的 VALID_PAGES 白名单，写错会被静默回落到概览页，
     表现为「点了按钮跳过去了，但打开的是别的页」。 */
  /* 2026-09-29（用户要求）：tt / wo 不再双双合流到 `ttwo`。
     此前这两张卡都指向 `?page=ttwo`（TT/WO **合并**页），可它们的明细本来就是
     分开取的（metric=tt 是故障工单生命周期，metric=wo 是派单闭环），点过去却落在
     同一个合并页，用户还得在里面自己再切一次页签 —— 按钮上写的是「打开完整看板」，
     落到的却不是这张卡的完整版。现在各指 my_app 的独立页：
       tt → tt（TTs 故障工单，TTDashboard）
       wo → wo（WOs 任务工单，WODashboard）
     注意 'tt' / 'wo' / 'ttwo' / 'v1_ttwo' 是 my_app 里**四个不同的页面**，
     四个 key 都在 VALID_PAGES 白名单内，写错哪一个都会被静默回落成概览页。

     本次**只改 v1 这一份**，另外两处同名映射仍是 ttwo：
       olbrportal/assets/olbr.js、MsPortal/assets/portal.js
     理由：用户实际在看的只有 /v1/olbrportal/（见 docs/user-guide.md 第六之二节），
     且上面 cr / pmt 已有「v1 独有、别处刻意不改」的先例；一并漫改会让用户没要求的
     /olbrportal/ 与 MsPortal 跟着变行为。将来要拉齐就改上面这两处。

     ⚠️ 2026-10-01：这里原先把 `v2/olbrportal/assets/olbr.js` 列为「仍是 ttwo 的第三处」。
     v2 那份已确认弃用（改动全部落在 v1，v2 自 09-30 起停更）并整目录移入
     `_quarantine_20261001_v2_olbrportal\`，故从清单中删除 —— 留一个已不在磁盘上的
     路径会误导后来者去找它。 */
  var QC_BOARD_PAGE = {
    alarm: 'realtime_alarm',
    tt: 'tt',
    wo: 'wo',
    spms: 'sp_report',
    cr: 'cr_analysis',
    pmt: 'pm_analysis'
  };

  /* metric id → 界面上显示的名字。**唯一定义处**（弹窗标题与导出 Sheet 名都用它），
     所以不存在「标题与导出文件名两处不一致」的问题。
     D.qc 只有面板上那六张卡（定义在 /MsPortal/assets/data.js）。
     2026-09-25：达标率环（metric=sla）已从标题行删除，本页不再有任何地方能点出
     metric='sla' 的弹窗；但**保留这条回落**——弹窗是共用实现，MsPortal 那边仍会把
     sla 传进来，删掉它会让那边的标题退化成英文小写 id 'sla · 明细'。
     找不到名字时也不能直接回落 id，那正是上面要避免的。 */
  function qcMetricLabel(id) {
    var q = (D.qc || []).filter(function (x) { return x.id === id; })[0];
    if (q) return state.lang === 'en' ? q.en : q.zh;
    return id === 'sla' ? t('qc.sla') : id;
  }

  function applyDrillTitle() {
    var id = state.drill.metric;
    $('#qcTitle').textContent = qcMetricLabel(id) + t('dr.drillSuffix');

    var link = $('#qcOpenBoard');
    if (link) {
      var page = QC_BOARD_PAGE[id];
      if (page) {
        /* 同源相对路径：门户与 my_app 经同一个 nginx，用相对路径就不会把
           「本机 192.168.100.20」写死进代码（换 IP / 换域名时不用改这里）。 */
        link.href = '/myapp/?page=' + encodeURIComponent(page) + langQs();
        link.hidden = false;
      } else {
        link.removeAttribute('href');
        link.hidden = true;
      }
    }
  }

  /* anchor：触发下钻的那次点击的屏幕坐标。2026-09-23 加 —— 弹窗改为
     「以点击位置为中心弹出」（对齐 myapp 的 DraggableClickModal），
     所以要把坐标从事件里带进来；键盘触发（无坐标）时传 null = 居中于屏幕。
     与 MsPortal/portal.js 的 openQcDrill(id, anchor) 同签名。 */
  function openDrill(id, anchor) {
    /* 这里原先用 `if (!def) return;` 把关 ——「D.qc 里没有这个 id 就不给开」。
       2026-09-25 起不能再这么判：sla **本来就不在 D.qc 里**（见 qcMetricLabel），
       照旧判会让点 88.7% 变成一个完全没反应的死按钮，且不报任何错。
       改成只拦「参数是空的」这种真无效调用；至于 id 认不认识，
       后端 `/api/portal-qc/detail` 才是权威（它不认识会回 400，
       弹窗里会显示错误，比静默 return 好排查得多）。 */
    if (!id) return;
    /* sort/dir 必须一起重置：换一张卡还沿用上一张的排序列，后端会因为该列不在
       本 metric 的列白名单里而忽略它，看上去像「排序点了没反应」。 */
    state.drill = { metric: id, q: '', page: 1, size: 50, sort: '', dir: 'desc',
                    rows: [], columns: [], total: 0, loading: true, err: '' };
    $('#qcSearch').value = '';
    applyDrillTitle();
    $('#qcMask').hidden = false;
    /* 先量尺寸再定位：position() 读 offsetWidth/Height，
       必须在弹窗已可见（hidden=false）之后调用，否则量到 0 会定位到左上角。 */
    if (window.QcDrill) window.QcDrill.position(anchor || null);
    fetchDrill();
  }

  function closeDrill() {
    drillSeq++;                 /* 作废在途请求，避免关掉后又被写回 */
    state.drill.metric = '';
    state.drill.loading = false;
    $('#qcMask').hidden = true;
  }

  var drillSeq = 0;
  function fetchDrill() {
    var d = state.drill; if (!d.metric) return;
    var seq = ++drillSeq;
    d.loading = true; d.err = ''; renderDrill();
    api('/api/portal-qc/detail?metric=' + encodeURIComponent(d.metric) +
        '&page=' + d.page + '&size=' + d.size +
        (d.q ? '&q=' + encodeURIComponent(d.q) : '') +
        /* 排序下发到服务端（不是只排当前页）。后端会拿 sort 去撞该 metric 的
           列白名单，撞不上就忽略 —— 前端不需要知道后端有哪些列。
           MsPortal 走的是同一个参数口径。 */
        (d.sort ? '&sort=' + encodeURIComponent(d.sort) + '&dir=' + encodeURIComponent(d.dir) : ''))
      .then(function (r) {
        if (seq !== drillSeq || state.drill.metric !== d.metric) return;   /* 过期响应 */
        d.loading = false; d.total = r.total || 0; d.rows = r.rows || []; d.columns = r.columns || [];
        renderDrill();
      })
      .catch(function (e) {
        if (seq !== drillSeq || state.drill.metric !== d.metric) return;
        d.loading = false; d.err = (e && e.message) || String(e); renderDrill();
      });
  }

  /* 单元格显示。与 MsPortal 的 qcCell 同一口径，只做两件轻格式化：
       · 13 位纯数字 → 按 epoch 毫秒转本地时间（realtime_alarm.alarmraisedtime 就是这种）
       · 整数型 numeric 的尾巴 .0 去掉（PG 的 auxiliarycount 会回 '2.0'）
     接口一律回文本，所以这里不做数字千分位（旧 drawer 版会 toFixed/toLocaleString，
     于是同一个值在两个门户上显示成 1234 与 1,234 —— 统一后一律按 MsPortal 的口径）。 */
  function drillCell(v) {
    if (v == null || v === '') return '';
    var s = String(v);
    if (/^\d{13}$/.test(s)) {
      var dt = new Date(Number(s));
      if (!isNaN(dt.getTime())) {
        var p = function (n) { return (n < 10 ? '0' : '') + n; };
        return dt.getFullYear() + '-' + p(dt.getMonth() + 1) + '-' + p(dt.getDate()) +
          ' ' + p(dt.getHours()) + ':' + p(dt.getMinutes()) + ':' + p(dt.getSeconds());
      }
    }
    return s.replace(/^(-?\d+)\.0+$/, '$1');
  }

  /** 「空」判定：除 null / 空串，还要吃掉字面量 'empty' —— 源表里 alarm 的 tt_id
      既有空串也有字符串 'empty'（实测 51 行里 22 行如此），直接摊给用户看像是页面出错。
      只影响**显示**，不改任何统计口径：被替换成 — 的行仍在表里、仍参与计数。 */
  function drillIsEmpty(v) {
    if (v == null) return true;
    var s = String(v).trim();
    return s === '' || s.toLowerCase() === 'empty';
  }

  function drillCellHtml(v) {
    if (drillIsEmpty(v)) return '<span class="qc-null">—</span>';
    return esc(drillCell(v));
  }

  function renderDrill() {
    var d = state.drill;
    if (!d.metric) return;
    var thead = $('#qcThead'), tbody = $('#qcTbody');
    if (!thead || !tbody) return;

    var span = Math.max(1, d.columns.length);
    /* 表头可点排序。用 <button> 而不是给 <th> 绑 onclick：键盘 Tab 能到、
       回车能触发，aria-sort 也能正确播报当前列与方向。
       首列加 qc-sticky-col —— 明细最长 12 列，横向滚动时首列滚出视野后，
       剩下的数字列就失去了参照物（「这一行是谁」看不见了）。 */
    thead.innerHTML = '<tr>' + d.columns.map(function (c, i) {
      var active = d.sort === c.key;
      var dir = active ? d.dir : '';
      return '<th class="qc-sortable' + (i === 0 ? ' qc-sticky-col' : '') +
        '" aria-sort="' + (active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none') + '">' +
        '<button type="button" data-act="drill-sort" data-key="' + esc(c.key) + '">' +
          '<span>' + esc(c.label || c.key) + '</span>' +
          '<span class="qc-sort-ico" aria-hidden="true">' +
            (active ? (dir === 'asc' ? '▲' : '▼') : '⇅') +
          '</span>' +
        '</button></th>';
    }).join('') + '</tr>';

    var ph;
    if (d.err) ph = '<span class="qc-err">' + esc(t('dr.err').replace(/\{e\}.*$/, '')) + '<br>' + esc(d.err) + '</span>';
    else if (d.loading && !d.rows.length) ph = esc(t('dr.load'));
    else if (!d.rows.length) ph = esc(t('dr.empty'));

    if (ph) {
      tbody.innerHTML = '<tr><td colspan="' + span + '"><div class="qc-empty">' + ph + '</div></td></tr>';
    } else {
      tbody.innerHTML = d.rows.map(function (row) {
        return '<tr>' + d.columns.map(function (c, i) {
          var cls = [];
          if (i === 0) cls.push('qc-sticky-col');
          return '<td' + (cls.length ? ' class="' + cls.join(' ') + '"' : '') + '>' +
            drillCellHtml(row[c.key]) + '</td>';
        }).join('') + '</tr>';
      }).join('');
    }

    var pages = Math.max(1, Math.ceil(d.total / d.size));
    $('#qcCount').textContent = d.err ? '' : tf('dr.total', { n: fmt(d.total) });
    $('#qcPage').textContent = tf('dr.page', { p: d.page, q: pages });
    $('#qcPrev').disabled = d.loading || d.page <= 1;
    $('#qcNext').disabled = d.loading || d.page >= pages;
  }

  /* ---- 导出：当前搜索条件下的**全部行** → .xlsx（my_app 统一格式）----
     与 MsPortal 的 exportQcExcel 同一口径、同一个库（MsExcelReport）：
       1) 范围：不是只导当前页，而是按当前搜索关键字把 total 拉满
          （后端 _MAX_PAGE_SIZE=200，逐页取）—— 弹窗底部写着「共 N 条」，
          导出却只有 50 条说不通。
       2) 格式：UNIFIED_EXCEL_V1（标题行 + Generated 副标题 + 深蓝表头 +
          隔行底纹 + 细边框 + 冻结表头 + 自动筛选），与 /myapp/ 各看板同款。
     单元格取值仍走 drillCell()，保证 Excel 里的值与屏幕上看到的逐字一致。 */
  var DRILL_EXPORT_SIZE = 200;      /* = my_app backend/routers/portal_qc.py 的 _MAX_PAGE_SIZE */
  var DRILL_EXPORT_MAX_PAGES = 100; /* 兜底：最多 2 万行，避免异常 total 把页面拖死 */
  var drillExporting = false;

  function drillPad2(n) { return (n < 10 ? '0' : '') + n; }
  function drillFileStamp() {
    var d = new Date();
    return d.getFullYear() + drillPad2(d.getMonth() + 1) + drillPad2(d.getDate()) + '_' +
      drillPad2(d.getHours()) + drillPad2(d.getMinutes()) + drillPad2(d.getSeconds());
  }
  function drillTextStamp() {
    var d = new Date();
    return d.getFullYear() + '-' + drillPad2(d.getMonth() + 1) + '-' + drillPad2(d.getDate()) + ' ' +
      drillPad2(d.getHours()) + ':' + drillPad2(d.getMinutes()) + ':' + drillPad2(d.getSeconds());
  }

  function exportDrillExcel() {
    var d = state.drill;
    if (!d.metric || drillExporting) return;
    if (!window.MsExcelReport) { toast(t('dr.exportErr') + ': MsExcelReport'); return; }

    drillExporting = true;
    var btn = $('#qcExport'); if (btn) btn.disabled = true;

    var metric = d.metric;
    var keyword = d.q || '';
    var label = qcMetricLabel(metric);

    var columns = d.columns.slice();
    var rows = [];
    var reset = function () { drillExporting = false; if (btn) btn.disabled = false; };

    /* 逐页取满。第一页顺便拿 columns/total；中途某页失败就用手上已有的行导出，
       而不是整单作废 —— 导出一半也好过什么都拿不到（失败原因最后一起 toast）。 */
    var page = 1, total = null, failed = null;
    function nextPage() {
      return api('/api/portal-qc/detail?metric=' + encodeURIComponent(metric) +
                 '&page=' + page + '&size=' + DRILL_EXPORT_SIZE +
                 (keyword ? '&q=' + encodeURIComponent(keyword) : ''))
        .then(function (data) {
          if (total === null) {
            total = data.total || 0;
            if (data.columns && data.columns.length) columns = data.columns;
          }
          var got = data.rows || [];
          rows = rows.concat(got);
          if (got.length && rows.length < total && page < DRILL_EXPORT_MAX_PAGES) {
            page += 1;
            return nextPage();
          }
          return null;
        });
    }

    nextPage()
      .catch(function (e) { failed = (e && e.message) || String(e); })
      .then(function () {
        if (!rows.length) {
          reset();
          toast(failed ? t('dr.exportErr') + ': ' + failed : t('dr.noData'));
          return null;
        }
        var sheetName = String(label).replace(/[\\\/\?\*\[\]:]/g, ' ').slice(0, 31);
        var subtitle = 'Generated: ' + drillTextStamp() + '    |    Sheet: ' + sheetName +
          (keyword ? '    |    Search: ' + keyword : '');
        return window.MsExcelReport.exportAoaReport({
          filename: 'qc-' + metric + '-' + drillFileStamp() + '.xlsx',
          sheetName: sheetName,
          title: label + t('dr.drillSuffix'),
          subtitle: subtitle,
          header: columns.map(function (c) { return c.label || c.key; }),
          rows: rows.map(function (row) {
            return columns.map(function (c) { return drillCell(row[c.key]); });
          })
        });
      })
      .then(function () {
        reset();
        if (failed) toast(t('dr.exportErr') + ': ' + failed);
      })
      .catch(function (e) {
        reset();
        toast(t('dr.exportErr') + ': ' + ((e && e.message) || String(e)));
      });
  }

  /* ---------------------------------------------------------- map embed -- */
  /* 下面这一段（keepOnlyMap / invalidateLeaflet / refitLeaflet / stripFrame）
     是从 MsPortal/assets/portal.js 的同名实现**逐字搬过来**的，不是重写：
     地图页（尤其 mwRealTime）的内层结构不归本页面管，那套剥离 + 重算尺寸 +
     重新取景的时序是 MsPortal 实测踩出来的（容器高度从 88px 被 CSS 拉到 378px 后
     Leaflet 内部 _size 仍是旧值 → tile 按旧尺寸铺出去再被 overflow:hidden 裁掉，
     表现就是「地图只露一小块、还不在正中」）。
     不改成 import 共用是因为：那是 portal.js 的私有函数、没有导出，
     而 portal.js 一加载就会把整个 MsPortal 首页跑起来 —— 只读版不能引它。
     两份若要改动，请同时改，别只改一边。 */
  /* ⚠️ 2026-09-29：本函数在「改外链卡」那版里被删过一次，现在随内嵌地图一起恢复，
     但**只服务地图这一个 iframe**（报告文件有它自己的 ensureEmail 时序，
     不共用这里的三次重试节奏）。 */
  function wireMap() {
    var f = $('#mapFrame'); if (!f) return;
    var go = function () { tellEmbed(f, 0); stripFrame(f, 0); };
    f.addEventListener('load', go);
    go();
    window.setTimeout(go, 1400); window.setTimeout(go, 3400);
  }
  function tellEmbed(f, depth) {
    try {
      if (f.contentWindow) {
        f.contentWindow.postMessage({ __type: 'msportal-embed', theme: state.theme, depth: depth || 0 }, '*');
      }
    } catch (e) { /* 跨域静默 */ }
  }
  /* 内层纯静态页（mw_real_time.html）：从 Leaflet 画布逐层向上把兄弟节点整块藏掉。
     这里只能用内联样式 —— 它是静态页，没有 React 会重渲染把 style 覆盖回去。 */
  /* ⚠️ 2026-10-03：「藏兄弟」时必须**跳过的浮层白名单**。
     用户反馈「GIS Map 组件的 ALARM 都能点击弹出下钻，MW 能不能一样」——
     点 MW 的链路时链路会高亮（说明 selectEdge 跑到了、DOM 也填好了），
     但抽屉不弹出。根因有两层，这是**第二层、也是真正拦住的这一层**：
       · 第一层在 my_app 侧：mw_real_time.html 的 html.mw-embed 规则里
         #drawer/#drawer-mask 被 display:none !important（2026-10-03 已摘除）；
       · 第二层就是这里：下面的 while 循环从 .leaflet-container 逐层向上，
         把每一层祖先的**所有兄弟节点**统统刷成 display:none !important。
         MW 页里 .leaflet-container 挂在 #topo-leaflet → #topo-wrap → #left → #main，
         于是走到 #main 这一层时，#drawer 与 #drawer-mask（body 的直接子元素、
         与 #main 同级，见 mw_real_time.html 的 body 结构）被一并刷成 display:none。
         而且这是**内联样式的 !important**，优先级高于页面自己的任何 CSS ——
         所以只改 mw_real_time.html 的 CSS 是没用的，这里必须同步放行。
       · 另外上面还把 body 设成 overflow:hidden，position:fixed 的抽屉本身不受影响，
         但遮罩 #drawer-mask 需要能盖住整屏，故两者都要留下。

     为什么不干脆「只留地图、其余全藏」保持不变，而是开这个口子：
       抽屉与遮罩不是「地图外的另一套 UI」，它们是**地图自身的下钻出口**。
       藏掉它们 = 把地图点选这个功能整个砍掉，与「只要地图」的初衷相悖
       （初衷是去掉页面自带的工具栏/KPI/侧栏那类**重复**控件）。
     判据用 id，不用 :has()/class 猜：mw_real_time.html 里这两个节点的 id 是稳定的，
       且 mw_ume_topology.html 等其它内层页也用同名 id（同一套抽屉实现）。
       一并放行 kpi-modal / kpi-modal-mask：那是 KPI 卡的明细弹窗，同属**点击下钻**出口。
     ⚠️ 实测留档（TMP/_probe_mw_drawer_embed.py，改前/改后各跑一次做对照）：
       改前：#drawer 被刷 display:none，getBoundingClientRect() 全 0；
       改后：抽屉 rect=[465,0,420,858]、computed right=0px、遮罩 display:block，
             抽屉内的趋势图也渲染出来（用户症状「点了没反应」消失）。
     ⚠️ 与「地图右侧空白」无关：经对照实测（TMP/_probe_mw_rightgap.py），
       该空白在**本白名单生效前后都存在**（缝隙 151px ↔ 153px），属既存问题，
       不是本改动引入的 —— 别把它记到这条改动头上。
     ⚠️ MsPortal/assets/portal.js 与 olbrportal/assets/olbr.js 各有一份孪生实现，
       改这里时三份都要改，否则同一份 my_app 页在不同门户入口下表现不一致。 */
  var KEEP_OVERLAY_IDS = { 'drawer': 1, 'drawer-mask': 1, 'kpi-modal': 1, 'kpi-modal-mask': 1 };
  function keepOnlyMap(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var chain = [], node = lc;
    while (node && node !== doc.body && node.parentElement) {
      chain.push(node);
      var parent = node.parentElement;
      Array.prototype.forEach.call(parent.children, function (sib) {
        if (sib === node) return;
        var tag = sib.tagName;
        if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'LINK') return;
        /* 浮层白名单：抽屉 / 遮罩 / KPI 弹窗留给用户点选与查阅，见上方注释。
           这些节点都是 position:fixed，即便祖先被设成 overflow:hidden 也照样浮在上层。 */
        if (KEEP_OVERLAY_IDS[sib.id]) return;
        sib.style.setProperty('display', 'none', 'important');
      });
      node = parent;
    }
    [doc.documentElement, doc.body].forEach(function (el) {
      if (!el) return;
      el.style.setProperty('margin', '0', 'important');
      el.style.setProperty('padding', '0', 'important');
      el.style.setProperty('height', '100%', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
    });
    chain.forEach(function (el) {
      ['height', 'width'].forEach(function (p) { el.style.setProperty(p, '100%', 'important'); });
      el.style.setProperty('min-height', '0', 'important');
      el.style.setProperty('max-height', 'none', 'important');
      el.style.setProperty('margin', '0', 'important');
      el.style.setProperty('padding', '0', 'important');
      /* ⚠️ 2026-09-29 修「MW 页地图右边一块空白、不自适应填满」：
         光设 width:100% 不够 —— 祖先若处在**弹性行**里，真正决定它宽度的是
         flex-basis，而 flex-basis 的优先级高于 width。mwRealTime 页的内层版式
         正是这样：#main{display:flex} 里 #left{flex:0 0 75%}、#right{flex:1 1 25%}
         （左地图 / 右 Top Risk 栏）。上面那段循环已经把 #right 设成 display:none，
         于是左边成了**唯一**的弹性项，但它的 basis 仍是 75% ——
         结果地图只占 75%，右边 25%（实测 194px）空着。
         这里把 basis/增长/收缩一并放开，让留下的那一项自己吃满整行。
         实测（TMP/_diag_mwflex.cjs）：放开后 .leaflet-container 由 575px → 767px
         （body 769px），瓦片随之铺满；不放开则恒定 575px。
         ⚠️ 顺序有意义：这一步必须在上面「藏兄弟」之后跑，否则 basis 会被算进
         两侧的比例分配里，反而分不到全宽。 */
      el.style.setProperty('flex-basis', 'auto', 'important');
      el.style.setProperty('flex-grow', '1', 'important');
      el.style.setProperty('flex-shrink', '1', 'important');
    });
    lc.style.setProperty('height', '100%', 'important');
    lc.style.setProperty('min-height', '0', 'important');
    lc.style.setProperty('width', '100%', 'important');
    try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e) { /* ignore */ }
    return true;
  }
  /* 从 Leaflet 画布反查地图实例：四条常见挂载点 + React  fiber 兜底。
     （原来这段长在 invalidateLeaflet 里，加一级缩放也要用它，故抽出来。） */
  function findLeafletMap(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return null;
    var map = null;
    ['_leaflet_map', '__leaflet_map', '_map', 'map'].forEach(function (k) {
      if (!map && lc[k] && typeof lc[k].invalidateSize === 'function') map = lc[k];
    });
    if (map) return map;
    try {
      var fk = Object.keys(lc).filter(function (k) { return k.indexOf('__reactFiber') === 0; })[0];
      if (!fk) return null;
      var seen = new Set(), stack = [lc[fk]], guard = 0;
      while (stack.length && guard++ < 4000) {
        var n = stack.pop();
        if (!n || seen.has(n)) continue;
        seen.add(n);
        if (n.stateNode && typeof n.stateNode.invalidateSize === 'function') return n.stateNode;
        var mp = n.memoizedProps || n.pendingProps;
        if (mp) {
          for (var key in mp) {
            var v = mp[key];
            if (v && typeof v === 'object' && typeof v.invalidateSize === 'function') return v;
          }
        }
        if (n.child) stack.push(n.child);
        if (n.sibling) stack.push(n.sibling);
      }
    } catch (e) { /* ignore */ }
    return null;
  }
  function invalidateLeaflet(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var map = findLeafletMap(doc);
    if (map) {
      try {
        map.invalidateSize(false);
        setTimeout(function () { try { map.invalidateSize(false); } catch (e) {} }, 300);
        return true;
      } catch (e) { /* 落到路 3 */ }
    }
    try {
      lc.style.setProperty('height', 'calc(100% - 1px)', 'important');
      doc.defaultView.requestAnimationFrame(function () {
        lc.style.setProperty('height', '100%', 'important');
        try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e) {}
      });
    } catch (e) {
      try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e2) {}
    }
    return false;
  }
  /* 默认取景：**打开就比内层页自己的取景再放大一级**（= 用户点一次 + 号的效果）。
     需求演化（同一栏、同一位用户，四次表态，全部记录在案）：
       · 2026-09-22：「跟手动点一次加号一个效果」→ 默认在前一级基础上再放大一级。
       · 2026-09-25：「打开不能是点一下减号的效果，并且要保持利比里亚居中」
                    → 回到内层页自己的全国 fitBounds 取景（不加一级）。
       · 2026-10-02：「两个地图能打开后要默认显示比当前大一号的，类似鼠标点击了一下+号」
                    → 要回放大一级（本次）。
       · 2026-10-02（同日复述）：「实际上只要能做到居中，放大一级（zoom 8）是正好，
                                  7 的话有点小了」
                    → **确认 zoom 8 就是目标档位**；那点裁边可以接受，**居中**才是判据。
     故本开关置 true：zoomOnce（gis）与 refitLeaflet（mwRealTime）两条路径都放大一级。
     置 false 即回到 2026-09-25 的「完整居中显示全国」行为（两条路径的代码都在，
     改一个布尔即可，不需要恢复实现）。

     ⚠️ zoom 8 会裁掉国土**极窄**一条南北边缘，但这是用户拍板要的效果，不是缺陷：
         各档可视范围 vs 国土跨度（LB_BOUNDS 4.85°纬 × 4.40°经）：
           zoom 7 → 约 9.66°纬 × 8.87°经，全境装得下，但**四周留白多、显小**（用户嫌小）
           zoom 8 → 约 4.83°纬 × 4.43°经，纬向只差 0.02°（≈2km 量级）
        别被"裁边了"误导成"切掉一半"—— 实际只裁掉一条边，主体完整。
        用户 2026-10-02 明确「7 有点小了」，所以
        **不要再单凭"裁边了"就把开关改回 false**；要改先问清是哪一侧的需求变了。

     ✅ 居中已实测（TMP/_probe_v1_centered.cjs，4 条断言全绿）—— 这是本节最该看的数据：
        · mwRealTime：649 个站点真实经纬的包围盒中心 = 6.405N/9.493W，
                      与国土中心 6.325N/9.500W 偏差 **1.6% 纬 / 0.2% 经**，几乎正中。
        · gis       ：站点像素包围盒中心相对容器中心偏移 **9.8% 横 / 1.9% 纵**。
        即：放大一级之后**本来就是居中的**，无需为"居中"再补任何取景逻辑。

     ⚠️ 2026-09-29 的旧结论「两页都落在 zoom 7，所以一个全局开关就够」**仍然成立**，
     但当时写在本处的推论「改 true 会让两级放大叠在已经正确的 zoom 7 上、直接裁边」
     只对**当时的实现**成立：那时 mwRealTime 的 zoomOnce 会因暴露 fitAllSites 而早退，
     只有 refitLeaflet 一条路；现在两页各走一条路（见 zoomOnce / refitLeaflet），
     每页都只放大**一次**，不会叠加。

     ✅ 2026-10-02 验收（TMP/_verify_v1_defaultzoom.cjs，7 条断言全绿，连续 3 轮复跑）：
        · mwRealTime —— 打开后**不加任何操作**，栅格瓦片级别 = 8（内层全国档 7 +1，
                        网络层证据）；再点一次 `-` 回到 7，证明没有累加。
        · gis        —— 打开态站点要素像素跨度是「缩小一级」后的 **2.00 倍**
                        （752px vs 376px），恰好一级；静置 12s 跨度不变，不会继续放大。
        · 两页 `.leaflet-control-zoom-in` 都在（hasZoomBtn=true），
          说明「点控件」这条路径对两页都可用，不依赖任何地图实例挂载点。
        截图留档：TMP/_shot_defaultzoom_gis.png、TMP/_shot_defaultzoom_mwRealTime.png
        （由 TMP/_shot_v1_defaultzoom.cjs 生成）。
     ✅ 2026-09-29 基线实测（TMP/_probe_v1_mwfit.cjs）：
        内层页自己落 zoom 7、画面约 9.66°纬 × 8.87°经、站点全在画面内。
        反向校验（TMP/_probe_v1_mwfit_neg.cjs）：视野按 zoom+1 腰斩后纬向只剩
        4.83° < 国土 4.85°，判据会失败 —— 证明该判据确实分辨得出多放大一级。 */
  /* 打开后是否自动放大的**分页**开关（2026-10-16 起由单一布尔改为按页配置）。
     ---- 需求演变（四次，按时间）----
       2026-09-22 用户：跟手动点一次加号一个效果            → 两页都放大
       2026-09-25 用户：别放大了                            → 两页都不放大
       2026-10-02 用户：又改回「打开就大一号」                → 两页都放大
       2026-10-16 用户：「alarm 这个地图不要在点一次放大了」   → **只关 gis，MW 保持放大**
     所以不能再用一个全局布尔：需求已经**按页分叉**了。键就是 MAP_TABS 的 page 值，
     将来某一个页要单独调整，只改它自己那一行，不会误伤另一页。
     ⚠️ 目前两页各走一条独立实现（见 zoomOnce / refitLeaflet 的说明）：
          · gis（= 界面上那个 "Alarm" 页签）→ zoomOnce
          · mwRealTime（= "MW" 页签）        → refitLeaflet
        两个函数各自查自己那一页的开关，互不影响。 */
  var MAP_ZOOM_IN_BY_PAGE = {
    /* 2026-10-16：用户要求 Alarm 页不要再自动放大，就用它自己的默认取景。
       实测该页默认落在 zoom 7（内层 React 页自己的取景），即"打开即所见"。 */
    gis: false,
    /* ⚠️ 2026-10-12（v2 专有）：MW 页由 true 改为 **false** —— 不再自动放大。
       起因：地图容器高度从 860px 降到 573px（.maprow --maprow-h 的 2/3 改动）。
       原 zoom 8 是 2026-10-02 在**860px 高度下**按用户"7 有点太小、放大一级正好"
       拍板的（见下方 MAP_ZOOM_* 段落的长注释）；容器矮了 2/3 之后，同样 zoom 8
       会让地图内容相对容器显得更大、裁得更多。用户 2026-10-12 要求"地图小一号"，
       故降回内层页自己的 zoom 7 —— 与 Alarm 页一致，两页统一。
       ⚠️ 改回 true 之前先读下方那段历史注释：zoom 8 的取舍是"高度 860px"为前提的，
          换高度就要重新拍板，不要单凭"裁边了/太小了"来回翻。 */
    mwRealTime: false,
    /* 2026-10-19 加 person（"Person" 页签，?page=person）：与 Alarm 同理，
       内层页自己落在 zoom 7.5 装下全境，门户不再自动放大。
       该页不暴露 fitAllSites，走 zoomOnce 那条路 —— 本项为 false 时 zoomOnce
       对它早退，即"打开即所见"。 */
    person: false
  };
  /* 打开后自动**缩小一级**的页（2026-10-12 加，2026-10-13 清空）。
     与 MAP_ZOOM_IN_BY_PAGE 是两个方向、互斥使用：同一页不会既放大又缩小。
     为什么不让 MAP_ZOOM_IN_BY_PAGE 用负数表达：那个键的语义是"是否放大一级"，
     塞进"缩小"会让读代码的人以为它能双向；单独一个集合，一眼看清"哪些页要缩"。

     ---- 为什么现在整张表为空（2026-10-13）----
     用户要求「GIS Map 加载 ALARM 地图后不用再缩小了，保持默认的大小」——
     即取消打开后的那次自动缩小。
     ---- 这次缩小的来历（别误读成"从来没需要过"）----
     2026-10-12 容器高度从 860px 砍到 573px（--maprow-h 的 2/3 改动），
     gis 页自己落 zoom 7，在矮容器里显得偏大，故打开后缩一级到 zoom 6 迁就。
     2026-10-13 高度改回 860px（olbr.css 的 --maprow-h），前提消失：
     在 860px 下 zoom 7 已经装得下全国且留白合适，无需再缩 —— 老需求的两半
     （高度 + 缩放）本就是配套的，本次一起回退，不要只回退其中一半。
     ⚠️ 保留这个集合与 shouldZoomOut 的机制而不是删掉：MAP_ZOOM_OUT_PAGES
        同时被 zoomOnce 与 shouldZoomOut 引用，留空表即等价于"没有任何页要缩"，
        语义清晰且将来某个页要缩时改一行即可（同 MAP_ZOOM_IN_BY_PAGE 的做法）。 */
  var MAP_ZOOM_OUT_PAGES = {};
  function shouldZoomOut(page) { return MAP_ZOOM_OUT_PAGES[page] === true; }
  /* 取某页是否要自动放大。未知页（例如将来新增的地图页）默认**不放大** ——
     宁可不放大（用户看得见全境、最多觉得小），也不要擅自改变他的视野。 */
  function shouldZoomIn(page) {
    return MAP_ZOOM_IN_BY_PAGE[page] === true;
  }
  /* 从 iframe 反查它属于哪一页：src 形如 /myapp/?page=gis&mwembed=1… */
  function framePage(f) {
    try {
      var src = (f && (f.getAttribute('src') || '')) || '';
      var m = /[?&]page=([^&#]+)/.exec(src);
      return m ? decodeURIComponent(m[1]) : null;
    } catch (e) { return null; }
  }

  /* 默认比内层页自己的取景再近一级（2026-09-22 用户：「跟手动点一次加号一个效果」）。
     只在本页面这一侧做：/myapp/ 是两个门户共用的预编译产物，改它的默认 zoom 等于
     把展示版的偏好推给 MsPortal，而且要连带重新发布一批与本次无关的源码。
     先点内层页自己的 + 控件（走它自己的行为链，maxZoom 和它自己的 zoomend 都由它管），
     控件不存在（有的内层页关了 zoomControl）才退到直接改地图实例。
     ⚠️ 只有 shouldZoomIn('gis')=true 时才会真正放大（2026-10-16 起为 false，
        见 MAP_ZOOM_IN_BY_PAGE；2026-09-25~10-02 期间也曾整体关闭过）。
     ⚠️ 调用方有**两个**，一页一个，别让同一页同时走到两条：
        · zoomOnce（gis，React 页，无 fitAllSites）
        · refitLeaflet（mwRealTime，每轮 fit 之后）
     ✅ 2026-10-02 实测：两页的 .leaflet-control-zoom-in 都在，
        所以「点控件」这条主路径对两页都成立；退到实例那条路（findLeafletMap）
        对 PMTiles 的 gis 页拿不到实例（栅格瓦片无 src 级别段、也无挂载点），
        但既然控件在，就不影响本需求 —— 万一将来内层页关掉 zoomControl，
        gis 页会静默不放大（不报错、不白屏），届时需另找入口。 */
  function zoomInLeaflet(d) {
    var btn = d.querySelector('.leaflet-control-zoom-in');
    if (btn) { try { btn.click(); return true; } catch (e) { /* 落到实例 */ } }
    var map = findLeafletMap(d);
    if (!map) return false;
    try {
      var z = map.getZoom(), mz = map.getMaxZoom();
      if (mz != null && z >= mz) return true;         // 已经在最大档：算成了，不用再试
      map.setZoom(z + 1);
      return true;
    } catch (e) { return false; }
  }
  /* 缩小一级（2026-10-12 加，用户要求「Alarm 页地图小一号」= zoom 7→6）。
     与 zoomInLeaflet 对称：优先点 Leaflet 自带的 .leaflet-control-zoom-out，
     点不到再落到 map 实例的 setZoom(z-1)。用于 gis 页 —— 它自己落 zoom 7，
     容器高度从 860 降到 573 后显得偏大，故打开后主动缩一级。 */
  /* 2026-10-13（用户：「主要是加载完成后的缩小地图导致的，缩小一号整个动作触发的
     哪里没有同步」）—— 这条就是那处「没有同步」。
     ---- 症状 ----
     每缩一级，地图右侧就多出一条**竖直白条**，且不会自行恢复。
     ---- 根因（Playwright 实测，TMP/_probe_size.json 的三态对照）----
     地图内容被 MAP_STRIP_CSS 的 `.leaflet-map-pane{margin-left:-89px}` 整体左移
     （避让右上 MAINTENANCE ALERTS 面板）。Leaflet 把瓦片铺成**整数列**的网格，
     每列的宽度是固定的 256px，而 Leaflet 是**按容器尺寸**决定铺几列的；
     缩一级之后它认为 4 列够用，于是网格总宽只有 4×256 = 1024px：
       · 缩小前   5 列 = 1280px，网格 -286..994 → 超出容器右缘(885) 109px
                  → 109 > 89，**扛得住**那 89px 左移，不露白（实测 rightGap -109）
       · 缩一级后 4 列 = 1024px，网格 -222..802 → 只剩 6px 余量
                  → 6 < 89，**扛不住**左移，右侧露出 89-6 = 83px 白条
                  （实测 rightGap +83、纯白 28 列；再缩一级仍差 +51px）
     所以这不是"阴影"或"滚动条"，而是**瓦片列数从 5 掉到 4 之后，那 89px 左移
     再也盖不住右边**。缩小动作本身没错，错在没有在缩放后让 Leaflet 重算网格。
     ---- 为什么以前没被修掉 ----
     stripFrame 只在 0 / 400 / 1200ms 调 invalidateLeaflet，而自动缩小在 **1800ms**
     才发生（MAP_ZOOM_DELAY）—— 缩小之后**没有任何一次尺寸同步**，
     网格缺的那一列永远补不回来。
     ---- 修复口径（实测验证过的那条路）----
     缩放后**制造一次容器尺寸抖动**，逼 Leaflet 重新量尺寸、重铺瓦片。
     ⚠️ 为什么不用 map.invalidateSize()：gis 页**拿不到 map 实例**
        （实测容器的自有属性只有 _leaflet_events 与 _leaflet_id，
         与 findLeafletMap 上方注释所述一致），所以只能从 DOM 侧下手。
     ⚠️ 抖动为什么是"高度 100% → calc(100%-1px) → 100%"：
        沿用 invalidateLeaflet 里已验证的那一招，只改 1px、下一帧还原，
        用户看不见，但 Leaflet 的 ResizeObserver / window.resize 会因此重算。
     ---- 实测效果 ----
     缩一级后（4 列，-89px 位移保持不动，paneLeft 仍为 -89）：
       修复前  网格 -222..802  rightGap +83  白条 28 列
       抖动后  网格 -133..891  rightGap  -6  白条  0 列  ✅
     ---- 调用点 ----
     挂在 zoomOutLeaflet / zoomInLeaflet 两条路上，所以**手动点 ± 与门户自动缩放
     都**受益（用户报的是"加载完成后的缩小"，但手动缩放在修复前同样有问题）。 */
  /* ⚠️ 2026-10-13：**曾经**想在这里加一个 resyncAfterZoom（缩放后抖一下容器尺寸，
     逼 Leaflet 重新铺瓦片）来修「缩小后右侧竖白条」。**实测证明它无效，已删除**，
     别再重新发明它。原因见下面这段——那 83px 缺口不是"没同步"，而是**位移量本身
     超过了瓦片网格的余量**，抖尺寸改变不了这个余量。

     ---- 「缩小后右侧竖白条」的真正机制（Playwright 实测 TMP/_probe_matrix.json）----
     MAP_STRIP_CSS 给 `.leaflet-map-pane` 加了 `margin-left:-89px`（避让右上
     MAINTENANCE ALERTS 面板，见 olbr-data.js 的 MAP_STRIP_CSS 段）。
     Leaflet 的瓦片是按 **256px 整数列**铺成网格的，网格总宽 = 列数 × 256，
     而**列数只由容器尺寸决定**。于是"网格右缘超出容器右缘多少"（= 余量）是
     一个随缩放级/宽度跳变的值，实测：
        · 缩一级前   5 列 = 1280px → 网格 -286..994，余量 109px  → 109 > 89 扛得住
        · 缩一级后   4 列 = 1024px → 网格 -222..802，余量   6px  →   6 < 89 露白 83px
     即 **rightGap = 余量 − 89**，实测线性成立（扫 margin-left 得到）：
        margin-left  -89px → rightGap +83    ← 问题态
                     -60px → rightGap +54
                     -30px → rightGap +24
                       0px → rightGap  -6    ← 铺满
     ⚠️ 所以只要余量 < 89px 就一定露白，而余量在 0~255 之间随宽度/级别循环，
        这意味着**这个位移在任何时刻都可能是坏的** —— 不是"缩小"这个动作有错，
        是"固定平移 89px"这个做法与"瓦片网格余量不可控"根本不相容。
     ---- 结论：修在位移上，不要修在同步上 ----
     正确做法是**不要再平移地图画布**（见 olbr-data.js 里 MAP_STRIP_CSS 的那一行
     已改为 0），改用不给地图制造裁切缺口的方式避让浮层。 */

  function zoomOutLeaflet(d) {
    var btn = d.querySelector('.leaflet-control-zoom-out');
    if (btn) { try { btn.click(); return true; } catch (e) { /* 落到实例 */ } }
    var map = findLeafletMap(d);
    if (!map) return false;
    try {
      var z = map.getZoom(), mz = map.getMinZoom();
      if (mz != null && z <= mz) return true;         // 已经最小档：算成了
      map.setZoom(z - 1);
      return true;
    } catch (e) { return false; }
  }
  /* 延迟到 1.8s：内层 React 应用在挂载时才 setView，早于它的取景加一级会被盖掉。
     stripFrame 在 0 / 1.4s / 3.4s 会被反复调用，所以 zoomOnce 必须靠 d.__olbrZoomed
     去重（否则 +3）；refitLeaflet 那条路不需要去重，理由见它内部的说明。 */
  var MAP_ZOOM_DELAY = 1800;
  function zoomOnce(d) {
    var w = d.defaultView;
    /* 会自己重新取景的内层页（暴露 fitAllSites）**不走这条路**：它每次 fit 都会把视野
       拉回「刚好包住所有站点」，在这里加一级会被随后的 fit 盖掉。它由
       refitLeaflet 在**每次 fit 之后**加一级（见那里），两条路各管一页、互不重叠：
         · gis（React 页，无 fitAllSites）      → 本函数
         · mwRealTime（暴露 fitAllSites）        → refitLeaflet
        所以两页都开启放大时每页仍只放大一次，不会叠加两级；
       2026-10-16 起 gis 那项已关，实际只有 mwRealTime 会放大。 */
    if (!w || typeof w.fitAllSites === 'function') return;
    /* 本函数只服务「不暴露 fitAllSites 的页」—— 除 gis（"Alarm"）外，
       2026-10-19 起的 person（"Person"）也走这里：按 iframe src 里的 page 取开关，
       两页各自查自己那一项（都是 false，故都早退、保持内层页默认取景）。
       ⚠️ 别写死 'gis'：那样 person 页会被当成 gis 处理，改一页的开关会误伤另一页。
       2026-10-12：gis 曾由"是否放大"改为"是否缩小" —— 容器高度 860→573 后偏大，
       故打开后缩一级（zoom 7→6）。两条分支互斥：同一页只会执行其中一条。
       2026-10-13：高度改回 860px，缩放这一半一并回退 ——
       MAP_ZOOM_OUT_PAGES 清空、MAP_ZOOM_IN_BY_PAGE.gis 仍为 false，
       于是本函数对 gis 早退，地图保持内层页自己的默认取景（即"打开即所见"）。 */
    /* 由 stripFrame 在调用前把所属 iframe 记到 d.__olbrFrame 上（那样 framePage
       才能从它真正的 src 反查 page）；拿不到时回落 gis，与改动前的行为一致。 */
    var page = framePage(d.__olbrFrame || null) || 'gis';
    var out = shouldZoomOut(page);
    if (!out && !shouldZoomIn(page)) return;
    if (d.__olbrZoomed) return;
    window.setTimeout(function () {
      if (d.__olbrZoomed || !d.querySelector('.leaflet-container')) return;
      var ok = out ? zoomOutLeaflet(d) : zoomInLeaflet(d);
      if (ok) d.__olbrZoomed = true;
    }, MAP_ZOOM_DELAY);
  }
  /* 只有暴露了 fitAllSites 的内层页（当前是 mwRealTime）需要重新取景：
     fitBounds 跑在容器还矮的时刻，zoom 会低一级。容器高度每落定一次就重跑一次，
     直到约 12s 的观察窗口结束 —— 中途存在「前 strip 的假稳态」，只做一次会被骗。
     ⚠️ 它同时也是 mwRealTime 的**放大一路**（zoomOnce 对暴露 fitAllSites 的页早退）：
     见下方 apply() 里的说明，两页各走一条路、互不重叠。 */
  function refitLeaflet(d) {
    var w = d.defaultView;
    if (!w || typeof w.fitAllSites !== 'function') return false;
    if (d.__olbrRefitState) return false;
    var st = d.__olbrRefitState = { lastH: -1, tries: 0, timer: null };
    var apply = function () {
      st.timer = null;
      var lc = d.querySelector('.leaflet-container');
      if (!lc) return;
      var h = Math.round(lc.getBoundingClientRect().height);
      if (h <= 0 || h !== st.lastH) return;
      try { w.fitAllSites(); } catch (e) { /* 内层页自己会兜底 */ }
      /* fit 之后才加一级（fit 会重置视野）；再晚一点：fit 带动画时立刻 setZoom 会被忽略。
         这里不去重是刻意的 —— 每轮都是「重新 fit + 一级」，不会累加：
         fitAllSites() 内部是 fitBounds(全国, animate:false)，**每次都会把 zoom 重新压回 7**，
         所以每轮「fit → +1」都收敛到同一个 8，而不是 8→9→10。
         ✅ 2026-10-02 实测（TMP/_verify_v1_defaultzoom.cjs 的 A3 断言）：点一次 `-` 即回到 7，
            而不是 6/5 —— 证明重复 apply 没有累加。
         2026-10-02：MAP_ZOOM_IN_BY_PAGE 重新开启时（打开即大一号），故本段生效；
         置 false 时整段跳过，只保留 fitAllSites 的全国取景（2026-09-25 的行为）。 */
      /* 2026-10-16：开关改为**按页**。本函数只服务 mwRealTime（界面上的 "MW" 页签），
         故查 'mwRealTime' 那一项，当前仍为 true —— **MW 页行为不变**。
         同一轮里 gis（"Alarm" 页签）那一项被置为 false，由 zoomOnce 提前早退实现。 */
      if (shouldZoomIn('mwRealTime')) {
        window.setTimeout(function () { zoomInLeaflet(d); }, 700);
      }
    };
    (function tick() {
      var lc = d.querySelector('.leaflet-container');
      if (lc) {
        var h = Math.round(lc.getBoundingClientRect().height);
        if (h > 0 && h !== st.lastH) {
          st.lastH = h;
          if (st.timer) clearTimeout(st.timer);
          st.timer = setTimeout(apply, 500);
        }
      }
      if (st.tries++ < 40) setTimeout(tick, 300);
    })();
    return true;
  }
  /* ------------------------------------------------- 地图滚轮缩放锁（2026-10-22）--
     需求：用户在门户里往下滚页面时，滚轮一旦划过内嵌地图就被 Leaflet 吃掉
     （变成缩放地图），页面卡住不动 —— 用户原话「鼠标下滑的时候容易出现在地图里面下滑」。

     为什么选「工具栏开关」而不是「点击激活」：
       · 点击激活（内嵌时默认关、点一下地图才开、鼠标移出又收回）**本项目做过又删了** ——
         my_app 的 MapWheelZoomOnClick 组件，2026-09-29 按用户要求整体撤销
         （GISMap.tsx:1157 与 olbr.js 上方 mapSrc() 那段注释都留了记录）。
         再上等于把同一个决定来回翻第二次。
       · 更要紧的是**语义撞车**：这两个地图页的主交互就是「点站点弹窗 / 点链路下钻」，
         左键点击已经被占用了，再让它兼职"开启滚轮缩放"，用户点开一个弹窗回来
         发现滚轮又失灵，只会觉得坏了。
       · 开关是**显式且可记忆**的：锁定态下滚动永远滚页面，要精细浏览时自己解锁一次，
         之后一直有效 —— 不需要每看一次地图就点一次。

     实施的两条路**都要走**（缺一不可）：
       ① 实例路：`map.scrollWheelZoom.disable()` —— Leaflet 官方开关，最干净。
          但已知 gis（= 界面上的 "Alarm" 页签）**可能拿不到实例**（见 findLeafletMap
          上方那段实测），此时这条静默失败。
       ② 拦截路：在内层 document 上挂 **capture 阶段**的 wheel 监听，
          `preventDefault` + `stopImmediatePropagation`，把事件挡在 Leaflet 自己的
          处理器之前。不依赖任何实例，两页通用 —— 这是 ① 拿不到实例时的退路。
          两路同时存在不会重复：① 关掉后 Leaflet 自己的处理器不动，② 只是兜底。

     ⚠️ 两个不做就会静默失效的点（改之前先读）：
       a. **必须 `{ passive: false }`**。Chrome 把 document/window 上的 wheel/touch
          监听默认当 passive，passive 监听里调 preventDefault 会被忽略
          （控制台只留一行 "Unable to preventDefault inside passive event listener"），
          表现是"锁了但地图照样缩放"。
       b. **光拦不够，还要把滚动还给最外层门户窗口**。内层页被 stripFrame 刷成
          `overflow:hidden`（见 keepOnlyMap），本身的滚动容器已经没有了；
          拦掉滚轮只是"地图不缩放"，页面**不会**因此自己往下走 ——
          必须由本函数把 deltaY 转交给外层窗口的 scrollBy（见 outerScrollWindow）。

     ⚠️ 为什么必须**反复重新施加**：iframe 一重载（切页签 / Reload / 主题切换重设 src），
        内层 document 和地图实例全换成新的，之前挂的监听器与 disable 一起蒸发。
        所以 applyMapWheelLock 挂在 stripFrame 的**每一个**时机后面（0 / 1.4 / 3.4s），
        而不是只在 wireMap 里调一次 —— 只调一次的表现是"锁了又自己开了"。

     ⚠️ 但**光靠 stripFrame 还不够**（2026-10-22 实测踩到）：stripFrame 只在
        0 / 1.4 / 3.4 秒这几个**固定时刻**跑，而 MW 页是三层嵌套
        （门户 → React 壳 → mw_real_time.html），三层各自还要跑 React 挂载与地图初始化；
        点「重新加载」之后，最内层那个 document 往往在这三个时刻**都还没被创建出来**
        （实测：三个时刻过后内层 document 上 data-olbr-wheel-lock 仍是 null，
        地图照常缩放，而按钮还显示"已锁定" —— 界面在说谎）。
        所以另有 keepMapWheelLock() 的定时补施加兜底（见下），它只认状态、不管时机。
        两处都保留：stripFrame 那条负责"第一时间生效"，定时那条负责"最终一定生效"。

     ⚠️ 刻意**不拦**的：双击缩放、+/- 按钮、拖拽平移全都不动。锁定的只是"滚轮"这个
        最容易误触的通道，地图本身的功能一个没少。 */
  var MAP_WHEEL_LOCK_MARK = '__olbrWheelLock';
  /** 取「真正该滚动的那个窗口」= 最外层门户窗口。
      ⚠️ 不能直接用监听器所在的 window：监听器挂在内层 iframe 的 document 上，
        那里的 window 是内层页自己的 —— 它被 keepOnlyMap 刷成 overflow:hidden，
        scrollBy 上去一动不动（实测过：拦住了缩放，页面却不走）。
        MW 页是**双层** iframe（门户 → React 壳 → mw_real_time.html），
        中间那层同样不可滚，所以必须一路走到顶。 */
  function outerScrollWindow(f) {
    var w = null;
    try { w = f && f.ownerDocument && f.ownerDocument.defaultView; } catch (e) { return null; }
    if (!w) return null;
    while (w.parent && w.parent !== w) {
      /* 同源才能继续往上；跨域访问 parent.document 会抛，抛了就停在当前层。 */
      try { if (!w.parent.document) break; w = w.parent; } catch (e) { break; }
    }
    return w;
  }
  /** 锁定（true）/ 解锁（false）地图滚轮缩放。lock 省略时以 state.mapWheelLock 为准。 */
  function applyMapWheelLock(f, lock) {
    var on = lock == null ? state.mapWheelLock : !!lock;
    var d = null;
    try { d = f && f.contentDocument; } catch (e) { /* 跨域静默 */ }
    if (!d || !d.documentElement) return;
    var map = findLeafletMap(d);
    if (map && map.scrollWheelZoom) {
      try {
        if (on) map.scrollWheelZoom.disable(); else map.scrollWheelZoom.enable();
      } catch (e) { /* 落到拦截路 */ }
    }
    /* 拦截路：挂在内层 document 上，capture 先于 Leaflet 容器上的处理器执行。
       用标记位保证同一个 document 只挂一次 —— stripFrame 会在 0/1.4/3.4s 反复跑，
       重复 addEventListener 是**不同函数对象**，浏览器不去重，会挂三层。 */
    if (!d[MAP_WHEEL_LOCK_MARK]) {
      var h = function (ev) {
        /* 每次都读最新状态：解锁后不移除监听器，只是放行 —— 省掉"移除/重挂"这对
           容易漏掉一半的操作（漏掉移除 = 解锁了仍被拦）。 */
        if (!state.mapWheelLock) return;
        /* 只拦**纯滚轮**。按住 Ctrl/⌘ 的滚轮是浏览器/触控板的"缩放页面"手势，
           拦下来会让手势失效且没有任何替代，故放行（交给内层页自己的行为）。 */
        if (ev.ctrlKey || ev.metaKey) return;
        /* 把滚动还给**最外层门户窗口**（内层滚不动，见 outerScrollWindow 的说明）。
           deltaMode：0=像素（Chrome 鼠标/触控板），1=行，2=页。 */
        var dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaMode === 2 ? ev.deltaY * 100 : ev.deltaY;
        var out = outerScrollWindow(f);
        if (out && dy) {
          try { out.scrollBy(0, dy); } catch (e) { /* ignore */ }
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
      };
      d[MAP_WHEEL_LOCK_MARK] = h;
      /* ⚠️ passive:false 是必需的（见上方要点 a）：不加就拦不住 Leaflet。 */
      try { d.addEventListener('wheel', h, { capture: true, passive: false }); } catch (e) { /* ignore */ }
    }
    /* 排查标记：控制台看 document.documentElement 的 data-olbr-wheel-lock 就知道
       当前施加的是哪一态（值为 '1' 锁定 / '0' 解锁）。 */
    try { d.documentElement.setAttribute('data-olbr-wheel-lock', on ? '1' : '0'); } catch (e) { /* ignore */ }
  }
  /* 定时补施加（自愈）。为什么需要它，见上方「光靠 stripFrame 还不够」那段实测。
     做法：每 2 秒把**当前**的地图 iframe 树扫一遍，对每个还没被标记过的 document
     补挂监听器并 disable 实例。开销极小（applyMapWheelLock 内部有标记位，
     已挂过的 document 直接跳过；典型只有 1~3 个 document）。
     ⚠️ 只有**锁定**态才需要它：解锁态下"没被施加"= 本来就要的效果，不必空转。
     ⚠️ 它不重建、不重载任何东西，纯粹是幂等地重放一次开关状态。 */
  var mapLockTimer = null;
  function sweepMapWheelLock() {
    if (!state.mapWheelLock) return;
    var f = $('#mapFrame');
    if (!f) return;
    applyMapWheelLock(f);
    /* MW 页的深层 iframe：逐层往下补（与 stripFrame 同样的两层上限，
       超过两层就不是地图页了）。 */
    var walk = function (frame, depth) {
      if (depth > 2) return;
      var d = null;
      try { d = frame.contentDocument; } catch (e) { return; }
      if (!d) return;
      applyMapWheelLock(frame, true);
      Array.prototype.forEach.call(d.querySelectorAll('iframe'), function (inner) {
        walk(inner, depth + 1);
      });
    };
    walk(f, 0);
  }
  function startMapWheelLockTimer() {
    if (mapLockTimer) return;
    mapLockTimer = window.setInterval(sweepMapWheelLock, 2000);
  }
  /* 切换开关：写盘 → 立刻施加到当前 iframe → 重画工具条（图标与 title 要跟着变）。
     不重建 iframe（renderL0 不给 keepMap）—— 重建会让地图重载几十秒，
     见 renderL0 上方「快速路径」那段实测。 */
  function toggleMapWheelLock() {
    state.mapWheelLock = !state.mapWheelLock;
    ss('olbr.mapwheellock', state.mapWheelLock ? '1' : '0');
    var f = $('#mapFrame');
    if (f) applyMapWheelLock(f);
    /* 解锁时立刻把内层实例**真的**恢复滚轮缩放：applyMapWheelLock 里那条
       `enable()` 已覆盖，这里只是再扫一遍深层 iframe（MW 三层嵌套），
       让"点了解锁马上就能滚"没有延迟。 */
    if (!state.mapWheelLock) sweepMapWheelLock();
    /* 只换工具条那一段：p-head 是 renderL0 / 快速路径共用的同一份 HTML，
       整块 innerHTML 重写会影响页签的选中态与改名铅笔，故就地替换 .map-tools。 */
    var box = $('#l0Map .map-tools');
    if (box) box.outerHTML = mapToolsHtml();
  }
  /* 工具条单独抽出来：toggleMapWheelLock 要就地替换它，而 mapHeadHtml 还被
     renderL0 与快速路径共用 —— 抽出来才能两处都只写一份。 */
  function mapToolsHtml() {
    var on = state.mapWheelLock;
    return '<div class="map-tools">' +
      '<button type="button" class="gb gb--t' + (on ? '' : ' unlocked') + '" data-act="map-zoomlock" aria-pressed="' +
      (on ? 'true' : 'false') + '" title="' + esc(t(on ? 'map.zoomlockOn' : 'map.zoomlockOff')) + '">' +
      '<i class="ph ' + (on ? DATA.PH.lock : DATA.PH['lock-open']) + '" aria-hidden="true"></i>' +
      '<span>' + esc(t('map.zoomlock')) + '</span></button>' +
      '<button type="button" class="gb gb--t" data-act="map-reload" title="' + esc(t('map.reload')) + '"><i class="ph ph-arrow-clockwise"></i><span>' + esc(t('map.reload')) + '</span></button>' +
      /* href 用 mapOpenSrc() 而不是 mapSrc()：新窗口要给完整页面，见上方注释。 */
      '<a class="gb gb--t" id="mapOpen" href="' + esc(mapOpenSrc()) + '" target="_blank" rel="noopener noreferrer" title="' + esc(t('map.open')) + '"><i class="ph ph-arrow-square-out"></i><span>' + esc(t('map.open')) + '</span></a>' +
      '</div>';
  }
  function stripFrame(f, depth) {
    depth = depth || 0;
    try {
      var d = f.contentDocument;
      if (!d || !d.head) return;
      var s = d.getElementById('olbrStrip');
      if (!s) { s = d.createElement('style'); s.id = 'olbrStrip'; d.head.appendChild(s); }
      if (s.textContent !== DATA.MAP_STRIP_CSS) s.textContent = DATA.MAP_STRIP_CSS;
      /* 记下这份 document 属于哪个 iframe（2026-10-19，为 zoomOnce 按页取开关）。
         document.defaultView.frameElement 在**同源**时可用，与本函数其余部分的前提一致；
         跨域时下面整段已被 catch 静默跳过。内层嵌套的 iframe 同样会被记录，无害。 */
      try { d.__olbrFrame = (d.defaultView && d.defaultView.frameElement) || null; } catch (e) { /* ignore */ }
      /* 缩放锁：只要拿到 document 就先挂一次拦截路（不依赖地图有没有挂载），
         下面拿到实例再补①那条路。见 applyMapWheelLock 上方的说明。 */
      applyMapWheelLock(f);

      if (d.querySelector('.leaflet-container')) {
        if (depth > 0) keepOnlyMap(d);
        invalidateLeaflet(d);
        refitLeaflet(d);
        setTimeout(function () { invalidateLeaflet(d); }, 400);
        setTimeout(function () { invalidateLeaflet(d); }, 1200);
        zoomOnce(d);
        /* 地图实例到位之后再补一次：这次能把 scrollWheelZoom 真正 disable 掉。 */
        applyMapWheelLock(f);
        return;
      }
      if (depth >= 2) return;
      Array.prototype.forEach.call(d.querySelectorAll('iframe'), function (inner) {
        var go = function () {
          tellEmbed(inner, depth + 1);
          stripFrame(inner, depth + 1);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 1200);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 3200);
        };
        if (inner.dataset.olbrStripped === '1') { go(); return; }
        inner.dataset.olbrStripped = '1';
        inner.addEventListener('load', go);
        try {
          if (inner.contentDocument && inner.contentDocument.readyState === 'complete') go();
        } catch (e) { /* ignore */ }
      });
    } catch (e) { /* 跨域时静默跳过 */ }
  }

  /* ------------------------------------------------------------ chrome -- */
  /* applyI18n 是所有语言相关输出的唯一出口：setLang / boot / 任何 render 都会走这里，
     所以动态写入的文案（envLabel、标题、meta）也必须在这里，
     否则切完语言它们留在旧语言 —— 之前「英文模式下页脚还是本机」就是这个漏的。 */
  function applyI18n() {
    var en = state.lang === 'en';
    root.setAttribute('lang', en ? 'en' : 'zh-CN');
    document.title = t('doc.title');
    var md = $('meta[name="description"]'); if (md) md.setAttribute('content', t('doc.desc'));
    $$('[data-i18n]').forEach(function (e) { e.textContent = t(e.getAttribute('data-i18n')); });
    $$('[data-i18n-attr]').forEach(function (e) {
      e.getAttribute('data-i18n-attr').split(',').forEach(function (pair) {
        var kv = pair.split(':');
        if (kv.length === 2) e.setAttribute(kv[0].trim(), t(kv[1].trim()));
      });
    });
    $$('.mast .seg-b[data-lang]').forEach(function (b) {
      var on = b.getAttribute('data-lang') === state.lang;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      /* 2026-09-24：顶栏改成 MsPortal 那套结构后，语言选中态的样式钩子换人了 ——
         MsPortal 的 masthead.css 把选中 pill 画在 `.seg-btn.is-active` 上
         （background #0d6fe0 / color #fff），而这里历史上只写 aria-pressed。
         两个钩子都写：`.is-active` 给 MsPortal 那份顶栏样式用，
         `aria-pressed` 保留给无障碍朗读（以及万一有旧样式还在看它）。 */
      b.classList.toggle('is-active', on);
    });
    $('#themeBtn').innerHTML = '<i class="ph ph-' + (state.theme === 'dark' ? 'sun' : 'moon') + '" aria-hidden="true"></i>';
    /* ⚠️ 2026-09-28（用户要求「Header 里面的 Local host，不要显示，只显示图标」）：
       环境徽标只留那颗探活状态圆点，文字（Local host / Liberia）不再上屏。
       为什么写成**空字符串**而不是删掉整个 #envBadge：
         · 那颗圆点是本页**唯一**的后端探活出口（envBadge() 靠它变红，
           见下方 setEnvDown），删掉徽标等于把「后端挂了」这件事在顶栏抹掉；
         · 空文本的 span 不占宽（.mp-env 是 inline-flex + gap，
           没有子文本节点就不产生额外间距），所以视觉上就只剩一个圆点。
       仍然是「赋值」而不是 remove：language 切换时这里会再写一次，
       保持这个出口对所有动态顶栏文案统一，不给 envLabel 开特例。
       环境区分能力没有丢：圆点本身只有绿/红两态，而"这是本机还是利比里亚"
       属于部署事实、不是运行状态 —— 需要时看 URL 即可。 */
    $('#envLabel').textContent = '';
    /* ⚠️ local 变量随这次改动失去唯一调用点，一并删掉。
       要恢复「显示环境名」见 olbr.js.bak_20260928_柱状图与顶栏调整前。 */
    var src = D.meta || {};
    $('#footSrc').textContent = tf('foot.src', { n: (D.stats && D.stats.total) || ITEMS.length, d: src.generated || '' });
    /* 编辑按钮的文案 / 提示是动态写的（语言一换要跟着换），所以也归这里出口 */
    syncEditBtn();
    /* 用户管理弹窗整块是 JS 画的，语言换了不重绘就会留着上一门语言 */
    if (state.um.open) renderUserMgmt();
  }
  function setTheme(v) {
    state.theme = v; root.classList.toggle('dark', v === 'dark'); ss('olbr.theme', v);
    /* 2026-09-23：本页的深色主题要能带到 /MsPortal/viewer.html（「打开看板」整个交给它）。
       那个查看器是两个门户共用的，它要判断「msportal.theme.v1 与 olbr.theme 谁更新」，
       所以这里显式记一个写入时间戳当依据。放在值之后写：查看器只认 '*.t' 这个键，
       顺序不影响它，但先值后戳更像一份完整的「这次设置」记录。
       ⚠️ 改这里请对照 MsPortal/assets/viewer.js 的 portalTheme()/lastWriteAt()。 */
    ss('olbr.theme.t', String(Date.now()));
    applyI18n();
    /* 地图是内嵌 iframe：my_app 只在启动时读一次主题（且这页不收 postMessage），
       所以换主题必须重设 src 才能让地图跟着变深浅色。 */
    var f = $('#mapFrame'); if (f) { f.src = mapSrc(); }
    /* 报告文件那块不看 URL 参数也不收 postMessage（my_app 只在启动时读 myapp-theme），
       只能靠 ensureEmail 里的「上次主题 ≠ 本次」判据重设 src。
       v1：报告文件常驻（不再是"切到那个页签才渲染"），所以这里无条件调一次。 */
    renderEmailSection();
  }
  function setLang(v) { state.lang = v; ss('olbr.lang', v); render(); }
  function toast(msg) {
    var el = $('#toast'); el.textContent = msg; el.hidden = false;
    el.className = 'toast';
    window.setTimeout(function () { el.hidden = true; }, 2200);
  }
  function tick() {
    $('#clock').textContent = fmtTime(Date.now());
    /* 倒计时只改文本、不重画整块面板：renderBand 会重建 iframe 之外的所有卡片，
       每秒一次既浪费也会让 hover / tooltip 状态被冲掉。 */
    var nx = $('#qcNextIn');
    if (nx) nx.textContent = tf('qc.next', { t: qcCountdown() });
  }

  /* --------------------------------------------------------- env badge -- */
  /* 只探活，文案由 applyI18n 写（语言切换才会跟着变）。
     2026-09-24：顶栏换成 MsPortal 那套结构后，红点的样式钩子有两个名字 ——
     MsPortal 的 masthead.css 认 `.mp-env.is-down`，本页历史上的 olbr.css 认 `.env.bad`。
     两个类一起写（toggle 的第二个参数保证成对增删，不会出现只加不删的半状态），
     这样无论最终哪份样式生效，后端挂了红点都一定会亮。
     注意：这是**唯一**的探活告警出口，漏写就等于后端挂了顶栏还显绿。 */
  function envBadge() {
    api('/api/portal-qc/summary').then(function () { setEnvDown(false); })
      .catch(function () { setEnvDown(true); });
  }
  function setEnvDown(down) {
    var b = $('#envBadge'); if (!b) return;
    b.classList.toggle('bad', down);
    b.classList.toggle('is-down', down);
  }

  /* ------------------------------------------------------------ events -- */
  function bind() {
    var userMenuBtn = $('#userMenuBtn');
    if (userMenuBtn) userMenuBtn.addEventListener('click', function () { toggleUserMenu(); });
    var userMenu = $('#userMenu');
    if (userMenu) userMenu.addEventListener('click', function (e) {
      /* System Management 的展开/收起（2026-10-12 加）：先于下面那行判 ——
         它是子菜单开关，点了**不要**关掉整个用户菜单（那会看不到展开的条目）。
         #sysBtn 刻意不在下面这条 close 名单里。 */
      if (e.target.closest('#sysBtn')) { e.preventDefault(); toggleSysMenu(); return; }
      if (e.target.closest('#editBtn,#umBtn,#logoutBtn')) closeUserMenu();
    });
    document.addEventListener('mousedown', function (e) {
      if (state.userMenuOpen && userMenu && !userMenu.contains(e.target)) closeUserMenu();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (state.userMenuOpen) { closeUserMenu(); return; }
        /* 弹窗优先吃掉 Esc：用户管理里有未保存的白名单草稿，让它先于下钻弹窗关闭 */
        if (state.um.open) closeUserMgmt();
        else if (state.drill.metric) closeDrill();
      }
    });
    $('#themeBtn').addEventListener('click', function () { setTheme(state.theme === 'dark' ? 'light' : 'dark'); });

    /* 系统主题跟随（2026-09-30 加）：用户**没有**显式选择过主题时，页面跟着
       操作系统的深色/浅色偏好走。三个前提，缺一不可：
       ① 只在「无选择」时跟随 —— 一旦用户点过主题按钮，'olbr.theme' 有值，
          这里就再也不会覆盖他的选择（setTheme 已写该键）；
       ② 用 addEventListener('change') 而不是轮询 —— matchMedia 变化时才回调；
       ③ 兜一层 typeof 判断：老浏览器 / 无 matchMedia 环境直接跳过，
          不影响页面其余部分（宁可不动，也不要因为装饰性能力报错）。
       为什么需要「运行期」跟随而不是只在首帧：用户把系统切到深色时，
       本页若正开着，应当即时响应，而不是要刷新才变。 */
    if (window.matchMedia) {
      try {
        var mqDark = window.matchMedia('(prefers-color-scheme: dark)');
        var onSysTheme = function (ev) {
          if (hasThemeChoice()) return;              // 用户已选，尊重选择
          var want = ev.matches ? 'dark' : 'light';
          if (want !== state.theme) setTheme(want);  // setTheme 会同步图标/地图/报告文件
        };
        if (mqDark.addEventListener) mqDark.addEventListener('change', onSysTheme);
        else if (mqDark.addListener) mqDark.addListener(onSysTheme);  // Safari < 14 回退
      } catch (e) { /* matchMedia 不可用则静默跳过，不影响页面 */ }
    }
    $$('.mast .seg-b[data-lang]').forEach(function (b) {
      b.addEventListener('click', function () { setLang(b.getAttribute('data-lang')); });
    });
    $('#logoutBtn').addEventListener('click', logout);
    bindUserMgmt();

    $('#band').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="qc-reload"]')) { loadQc(true); return; }
      /* 把点击坐标带给 openDrill —— 弹窗以点击位置为中心弹出。
         键盘触发（Enter/Space）时 clientX/clientY 都是 0，那种情况交给
         qcDrill 判空并回落到「居中于屏幕」（myapp 同样是 anchor 为空即居中）。 */
      /* 2026-09-25：认定条件由 .qc-card 放宽到 [data-qc]，当下 #band 里带 data-qc 的
         只有六张指标卡（达标率的环连同它的 data-qc="sla" 已删除）。
         保留这个宽条件而不是缩回 .qc-card：弹窗触发与「卡片」这个概念本就不必绑定，
         复用同一条委托，是为了让「点这个数字会发生什么」只有一处实现。 */
      var m = e.target.closest('[data-qc]');
      if (m && m.getAttribute('data-qc')) {
        var anchor = (e.clientX || e.clientY) ? { x: e.clientX, y: e.clientY } : null;
        openDrill(m.getAttribute('data-qc'), anchor);
      }
    });
    /* v1：CXO 指标带这里只处理「重试」一颗按钮。
       ⚠️ 2026-09-29 改：原先这里写着「卡片本身不可点 —— 这里的数字是派生值，
       点开没有对应明细接口」，据此不给点击。用户随后要求「三张卡点击后跳转到
       http://localhost/myapp/?page=vmaxCxoDashboard_90Days」，这条判断被推翻。
       推翻它是对的，理由有两条：
         ① 三张卡的数**本来就全部来自那一页的接口**
            （/api/olib-soc-dashboard/overview?days=90），
            所以「点开没有对应明细」这个前提不成立 —— 有对应页面，只是不是明细弹窗；
         ② .qc-card 从上线起就带 cursor:pointer + hover 抬升，
            视觉一直在暗示可点。此前是「看起来能点、点了没反应」，
            比不给点击暗示更糟。
       跳转**不由这里的事件委托实现**：kpiRichHtml 直接把整张卡渲染成 <a href>，
       浏览器原生负责跳转与中键/键盘行为，比挂 click 监听更稳。
       下面这条只保留「重试」—— 卡片点击不会冒泡到这里被误当成重试。 */
    $('#kpi').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="kpi-reload"]')) loadKpi();
    });
    /* v1：六个入口卡。这里同时是**本页唯一的编辑入口**（2026-09-26 起）——
       编辑态的行条目带改名 / 分组按钮、列头带分组改名 / 新建分组按钮，
       统一交给 onEditClick 处理；「展开其余 N 项」是另一条支线。
       两条必须分开判：onEditClick 是先 `closest('[data-act]')` 再看 canEdit()，
       把 v6-toggle 也丢进去会走进它的空分支什么也不做，展开就失灵了。 */
    $('#views6').addEventListener('click', function (e) {
      /* 子分组页签（BO View 的 RAN/IP/MW/CN/OCS，2026-09-27 加）必须排在
         onEditClick 之前：后者是先 closest('[data-act]') 再看 canEdit()，
         我们的按钮没有 data-act，走进去只会落到它的空分支什么也不做。
         用 closest 而不是直接判 target —— 按钮里包着 <small> 计数，
         点数字上时 target 是那个 <small>，直接判 target 会整个失灵。 */
      var sb = e.target.closest && e.target.closest('.v6-sub');
      if (sb) {
        /* disabled 的桶（空桶）浏览器本就不会派发 click，
           这里再判一次是为了兜住「按钮在按下与松开之间变成了空桶」的边界。 */
        if (sb.disabled) return;
        var sg = sb.getAttribute('data-gid');
        var sv = sb.getAttribute('data-sub') || '';
        /* 点已选中的那颗 = 取消选择回到全部：页签条上「全部」那一颗
           与「再点一次当前桶」应该得到同一个结果，否则用户在 OCS 上
           点两下会以为坏了（第一下没反应是因为本来就是当前态）。 */
        var cur = state.v6Sub[sg] || '';
        state.v6Sub[sg] = (sv && sv !== cur) ? sv : '';
        /* 切桶后把这一列的展开态收回去：展开着的「其余 N 项」在新桶里
           没有意义（那个 N 是按旧桶算的），留着会显示成一张拉长的卡。 */
        state.v6Open[sg] = false;
        renderViews6();
        return;
      }
      /* 「全部」视图里专业域分段的折叠（2026-10-12 加）。排在 onEditClick 之前，
         理由与上面 .v6-sub 同：这些按钮带 data-act，但只读态下 canEdit() 为假，
         丢给 onEditClick 只会落进空分支。直接判 class 更稳。 */
      var seg = e.target.closest && e.target.closest('.v6-seg-h');
      if (seg) {
        var ssid = seg.getAttribute('data-sub');
        /* 默认折叠 ⇒ 翻转规则也反过来：不是 true 就置 true（展开），已 true 则置 false。
           与 v6SegHtml 的 `=== true` 互为反义。 */
        state.v6SubFold[ssid] = state.v6SubFold[ssid] !== true;
        renderViews6();
        return;
      }
      if (e.target.closest && e.target.closest('[data-act="v6-toggle"]')) {
        var b = e.target.closest('[data-act="v6-toggle"]');
        var gid = b.getAttribute('data-gid');
        /* 直接翻转布尔值，与 aux-toggle 同一口径：没有"全开/全关"的中间态。 */
        state.v6Open[gid] = !state.v6Open[gid];
        renderViews6();
        return;
      }
      onEditClick(e);
    });
    /* v1：地图的页签 / 标题改名 / 刷新三颗按钮挂在 #l0Map 上。
       页签那一支 2026-09-29 曾随「本栏只内嵌一页地图」删掉，同日恢复两页时加回。
       这些按钮都在 p-head 里，而 p-head 会被 renderL0 重建，
       所以走事件委托而不是绑按钮本身。 */
    var mapClick = function (e) {
      /* 页签：编辑态下点是「改这个页签的名字」，非编辑态才是切换地图。
         与 MsPortal 侧同一套语义（改名的入口藏在页签自身上，不另开设置页）。 */
      var tb = e.target.closest('[data-map]');
      if (tb) {
        e.preventDefault();
        var pg = tb.getAttribute('data-map');
        if (canEdit()) { openForm('maptab', pg, tb); return; }
        if (pg === state.mapTab) return;                 /* 点当前页签：什么都不做，不白刷一次地图 */
        state.mapTab = pg;
        ss('olbr.maptab', state.mapTab);
        /* 切换必须整块重建（renderL0 不给 keepMap）：不同 page 是不同的内层页，
           iframe 留着只会显示旧图。 */
        renderL0();
        return;
      }
      if (e.target.closest('[data-act="map-head"]')) {
        e.preventDefault();
        openForm('maptab', DATA.RENAME_HEAD, e.target.closest('[data-act="map-head"]'));
        return;
      }
      if (e.target.closest('[data-act="map-reload"]')) {
        var f = $('#mapFrame'); if (f) f.src = mapSrc();
        /* 重载后的内层 document 是新的，锁要重新施加 —— 由 wireMap 的 load 钩子
           里的 stripFrame → applyMapWheelLock 负责，这里不用再调一次。 */
        return;
      }
      /* 缩放锁：编辑态下也照常可用 —— 它只改**本机的**滚轮行为，不写共享目录，
         与"编辑态点页签=改名"那套让路规则无关，故放在 canEdit() 判断之外。 */
      if (e.target.closest('[data-act="map-zoomlock"]')) { toggleMapWheelLock(); return; }
    };
    $('#l0Map').addEventListener('click', mapClick);
    /* v1：报告文件的「刷新」委托从 #views 搬到 #emailSlot。
       原先这个监听器还兼管子分组页签（[data-sub]）与主分组页签（[data-view]）的切换，
       那些页签随 L1 面板一起去掉了，这里只剩「刷新」这一支。 */
    $('#emailSlot').addEventListener('click', function (e) {
      /* 「刷新」不能等 data-act 让路规则：它不属于编辑态那套动作 */
      if (e.target.closest('[data-act="email-reload"]')) {
        var ef = $('#emailFrame');
        if (ef && ef.getAttribute('src')) { delete ef.dataset.loaded; syncEmailBoot(); ef.src = emailSrc(); }
        else renderEmailSection();
      }
    });
    /* v2（2026-10-12）：知识问答栏的页签切换（RAG / eFlow）。
       切页签只换 iframe 的 src（不整块重画）—— 页签条与标题不变，
       重画会让整块闪一下、也会丢掉另一页已加载的文档。
       ⚠️ 与地图页签同一取舍：不同 page 是不同的内层页，必须换 src。 */
    $('#qaSlot').addEventListener('click', function (e) {
      /* 刷新按钮（2026-10-12 加）：重载当前页签的 iframe。
         必须在下面判页签之前处理 —— 刷新按钮没有 data-qa，先判页签会直接 return。
         做法与 email-reload 一致：重设 src 即触发重载（iframe 的 src 相同也会重载）。 */
      if (e.target.closest('[data-act="qa-reload"]')) {
        e.preventDefault();
        var c2 = curQa();
        var cf = $('#qaFrame');
        if (cf && c2) {
          /* ⚠️ 先清空 src 再赋同值：部分浏览器对"src 未变"的赋值不做重载。
             与 email-reload 的"重设 src"同一目的，这里更保险一步。 */
          cf.setAttribute('src', 'about:blank');
          cf.setAttribute('src', qaSrc(c2));
        } else {
          renderQaSection();
        }
        return;
      }
      var tb = e.target.closest('[data-qa]');
      if (!tb) return;
      e.preventDefault();
      var key = tb.getAttribute('data-qa');
      if (key === state.qaTab) return;              /* 点当前页签：不白刷一次 */
      state.qaTab = key;
      ss('olbr.qatab', state.qaTab);
      var cur = curQa();
      var f = $('#qaFrame');
      if (f && cur) f.setAttribute('src', qaSrc(cur));
      /* 页签选中态与右上「打开」按钮的 href 都要跟着更新，故就地重画整块 ——
         这块没有需要保命的东西（iframe 换 src 本来就重载），重画代价可忽略。 */
      var el = $('#qaSlot');
      if (el) el.innerHTML = qaSectionHtml();
    });
    $('#esc').addEventListener('click', function (e) {
      /* v1：档位按钮（data-lv）的点击分支已删除 —— 那排按钮 2026-09-25 整排去掉了。
         留在这里的分支永远匹配不到任何元素，是死代码，且会让人以为还有按档筛选。
         现在本区只剩两颗按钮：展开/收起（esc-toggle）与复制（esc-copy）。 */
      if (e.target.closest('[data-act="esc-toggle"]')) {
        /* 收起态 → 先摊开整张表（保留当前 4 行/全部的口径）；
           展开态 → 在「前 4 行」与「全部 21 行」之间切换。 */
        if (!state.escOpen) state.escOpen = true;
        else state.escAll = !state.escAll;
        renderEsc(); return;
      }
      if (e.target.closest('[data-act="esc-copy"]')) { copyEsc(); return; }
    });
    /* ⚠️ 归档区（#arch）与 T2 辅助区（#aux）是**两块独立的 DOM**，
       所以这段逻辑不能只挂在 #aux 上 —— 实测过：只挂 #aux 时归档行的
       「取消归档」和「展开其余 N 项」点了完全没反应（事件根本冒泡不到那里）。
       这里把监听挂到一个共同的祖先（.aux 与 #arch 都在 <main> 里），
       而不是给 #arch 再复制一份同样的处理器 —— 同一套动作写两遍必然漂移。 */
    $('main').addEventListener('click', function (e) {
      /* 归档行的「取消归档」：先把条目放回一个**用户选定**的视图，再刷新。
         落点只能由用户当场指定：归档项没有"当前面板"，代码无从知道它该回哪个视图。
         可选项取 tabGids()（真正渲染得出来的分组），而不是 grpGids()（含只被引用过、
         却不在版面里的 id）—— 选到一个渲染不出来的分组等于换个地方弄丢，
         与本次改动要解决的问题正好相反。 */
      var u = e.target.closest('[data-act="unarchive"]');
      if (u) {
        var no = u.getAttribute('data-no');
        var opts = tabGids().filter(function (g) { return !isArchiveGid(g); });
        if (!opts.length) { toast(t('edit.needGroup')); return; }
        var pick = window.prompt(t('arch.unarchiveTip') + '\n\n' +
          opts.map(function (g, i) { return (i + 1) + '. ' + gName(g); }).join('\n'), '1');
        if (pick === null) return;
        var idx = parseInt(pick, 10) - 1;
        if (!(idx >= 0 && idx < opts.length)) { toast(t('edit.needGroup')); return; }
        unarchiveItem(no, opts[idx]);
        return;
      }
      var b = e.target.closest('[data-act="aux-toggle"]'); if (!b) return;
      var k = b.getAttribute('data-key');
      state.auxOpen[k] = !state.auxOpen[k];
      /* 归档区与 T2 辅助区是两块独立的 DOM（#arch / #aux），
         只调 renderAux() 的话点归档的展开按钮会毫无反应。 */
      if (isArchiveGid(k)) renderArchive(); else renderAux();
    });
    /* ---- QC 下钻弹窗（骨架见 index.html 的「QC 下钻弹窗」块）----
       2026-09-23：元素 id 换成与 MsPortal 的 QcDrillModal 同名的一套
       （qcMask/qcClose/qcSearch/qcReload/qcExport/qcPrev/qcNext…）。 */
    var qcSearch = $('#qcSearch');
    $('#qcClose').addEventListener('click', closeDrill);
    /* 点遮罩**不关闭**（2026-09-23 改）。原来这里是
       `if (e.target === qcMask) closeDrill()`，与 myapp 的 DraggableClickModal
       不一致 —— 那边的注释写明是刻意的：「仅通过右上角 × 与 Esc 关闭，
       点遮罩不关闭（避免误触）」。弹窗可拖动后更容易拖到边缘误点遮罩，
       关掉一个正在看的明细代价更大。关闭只保留 × 与 Esc 两条路径。 */
    $('#qcReload').addEventListener('click', fetchDrill);
    $('#qcExport').addEventListener('click', exportDrillExcel);
    $('#qcPrev').addEventListener('click', function () { if (state.drill.page > 1) { state.drill.page--; fetchDrill(); } });
    $('#qcNext').addEventListener('click', function () {
      var pages = Math.max(1, Math.ceil(state.drill.total / state.drill.size));
      if (state.drill.page < pages) { state.drill.page++; fetchDrill(); }
    });
    /* 表头排序走事件委托：表头每次 render 都会重建 innerHTML，
       直接绑在 <button> 上会在第一次渲染后就失效。

       方向口径与 MsPortal/portal.js 的 [data-act="qc-sort"] 分支**必须一致**：
       同一列再点一次切换升降序；换列则从 desc 起（明细表都是「最近的先看」）。
       写成 asc 起会让同一张表在两个门户上第一次点击得到相反的排列 ——
       这正是本次统一要消掉的那类差异。 */
    $('#qcThead').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act="drill-sort"]'); if (!b) return;
      var key = b.getAttribute('data-key');
      var d = state.drill;
      if (!d.metric) return;
      if (d.sort === key) {
        d.dir = (d.dir === 'asc' ? 'desc' : 'asc');
      } else {
        d.sort = key;
        d.dir = 'desc';
      }
      d.page = 1;
      fetchDrill();
    });
    var dq = qcSearch, dd;
    dq.addEventListener('input', function () {
      window.clearTimeout(dd);
      dd = window.setTimeout(function () { state.drill.q = dq.value || ''; state.drill.page = 1; fetchDrill(); }, 300);
    });
    $('#gate').addEventListener('submit', function (e) {
      e.preventDefault();
      if (e.target.id === 'lf') {
        var err = $('#le'), go = $('#lgo'); go.disabled = true; go.textContent = t('gate.busy'); err.hidden = true;
        login($('#lu').value.trim(), $('#lp').value).then(function () {
          /* renderWho 必须一起调：login() 只把 state.user / authOk 写好，
             徽标、退出按钮、用户管理入口三处的可见性全在 renderWho 里判。
             少了这一行，在本页登录完顶栏仍是「没人登录」的样子，要刷新才恢复。 */
          renderGate(); renderWho(); mainLocked(false); start();
          /* 用户是点「用户管理」被带到这里的，登录完直接把面板打开，
             别让他再回头找一次入口。 */
          if (state.umAfterLogin) { state.umAfterLogin = false; openUserMgmt(); }
        }).catch(function (x) {
          err.textContent = t('gate.' + (x.code || 'net')); err.hidden = false;
          go.disabled = false; go.textContent = t('gate.go');
        });
        return;
      }
      if (e.target.id === 'rf') {
        var re = $('#re'), ro = $('#ro'), rgo = $('#rgo');
        var rp = $('#rp').value, rp2 = $('#rp2').value;
        re.hidden = true; ro.hidden = true;
        /* 本地先拦两道，口径照 LoginView.handleRequest：长度 8 → 两次一致。
           后端也会拦，但先拦能省一次往返，提示也更准（不用等网络）。 */
        if (rp.length < 8) { re.textContent = t('ar.pwdTooShort'); re.hidden = false; return; }
        if (rp !== rp2) { re.textContent = t('ar.pwdMismatch'); re.hidden = false; return; }
        rgo.disabled = true; rgo.textContent = t('ar.submitting');
        register($('#ru').value.trim(), rp, $('#rn').value).then(function () {
          ro.textContent = t('ar.ok'); ro.hidden = false;
          $('#ru').value = ''; $('#rp').value = ''; $('#rp2').value = ''; $('#rn').value = '';
        }).catch(function (x) {
          /* register() 给的 code 里 'net' 要翻成 ar.networkError，其余（duplicate /
             pendingDup / tooMany / invalidInput）与键名同名，直接拼。别漏了这一支，
             否则网络故障会显示成裸 key「ar.net」。
             'server' 是 register() 的兜底档：后端返回了认不出的 detail。这一档**不能**
             显示成 networkError（那正是 2026-09-30 那次误报的成因），也不能显示成
             裸 key「ar.server」—— 直接把 x.message（后端原文或 "HTTP <status>"）摆出来，
             运维至少知道是服务端在拒绝、拒绝理由是什么。 */
          re.textContent = x.code === 'net' ? t('ar.networkError')
            : x.code === 'server' ? (x.message || t('ar.networkError'))
              : t('ar.' + x.code);
          re.hidden = false;
        }).then(function () {
          rgo.disabled = false; rgo.textContent = t('ar.submit');
        });
        return;
      }
    });
    /* 闸门里的按钮每次 renderGate 都被重建，所以照样用事件委托挂在 #gate 上
       （#gate 是 index.html 里的固定节点，innerHTML 换掉不影响它自身的监听）。 */
    $('#gate').addEventListener('click', function (e) {
      var id = e.target && e.target.id;
      if (id === 'gmreq') { state.gateMode = 'request'; renderGate(); }
      else if (id === 'gback') { state.gateMode = 'login'; renderGate(); }
      else if (id === 'gclose') { closeGate(); }
    });
    bindEdit();
    bindGrpPop();
    bindTplPick();
    bindFormPop();
  }
  function copyEsc() {
    var rows = (D.escalation || {}).rows || [];
    /* 复制的内容必须**与屏幕上看到的一致**，所以这里与 renderEsc 用同一套
       两态取行逻辑（展开全部 → 21 行；否则 → 前 4 行）。
       ⚠️ 原来还有一支 rows.filter(r => r.level === state.escLv)，已随档位按钮删除；
       若要恢复按档筛选，必须同时在 renderEsc 里恢复同样的分支，否则
       「看到的」与「复制到的」会再次对不上。 */
    var show = state.escAll ? rows : rows.slice(0, ESC_DEFAULT_ROWS);
    var txt = show
      .map(function (r) { return [r.position, r.name, r.orange, r.lonestar, r.email].filter(Boolean).join('\t'); }).join('\n');
    var done = function () { toast(t('esc.copied')); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, done);
    else done();
  }

  /* -------------------------------------------------------------- boot -- */
  /* 分两档刷新（与 MsPortal 同一口径，别改回单一定时器）：
       - 全量（其余五项 + 达标率）：每小时 :06:30，紧跟 eflow_sync 跑完；
       - 告警单项：每 5 分钟 :00:30，紧跟 eflow_active_alarm 的整表 replace。
     都用 setTimeout 自链而不是 setInterval —— 对齐按墙上的钟算，interval 只会从进页面
     那一刻起累加，进页面时若是 :07，下一轮就整体偏了。 */
  function startQcLoops() {
    (function qcLoopFull() {
      /* v1：CXO 指标带搭这一档的便车（同一小时刻度）。它是日粒度数据，
         一小时刷一次已经远快于上游变化，不值得为它单开一个定时器。 */
      window.setTimeout(function () { loadQc(); loadKpi(); qcLoopFull(); },
        qcNextDelay(DATA.QC_FULL_MIN, DATA.QC_FULL_OFFSET));
    })();
    (function qcLoopAlarm() {
      /* 开页时先补一发 ?only=alarm：首屏那三个告警数字是从全量借来的、时间戳走全量
         的时间轴（:06:30），而这一档的刻度是 :00:30。不补的话刚进来时「告警最近」
         可能是一小时前的旧时间，要等下一个 5 分钟刻度才被刷新。 */
      window.setTimeout(loadQcAlarm, 0);
      window.setTimeout(function () { loadQcAlarm(); qcLoopAlarm(); },
        qcNextDelay(DATA.QC_ALARM_MIN, DATA.QC_ALARM_OFFSET));
    })();
    /* 切回前台补一发全量：后台标签页的定时器会被降频甚至冻结，不补的话回到页面看到的
       可能是几小时前的数字 —— 比「延迟刷新」更容易被误读成故障。 */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { loadQc(); loadQcAlarm(); loadKpi(); }
    });
  }
  function start() {
    loadQc();
    /* v1：CXO 指标带与 QC 并行发，不串在 loadQc 后面 ——
       两个上游互不相干，串起来只会让下面那三张卡晚一拍上屏。
       它自己跟着全量 QC 那一档（每小时）刷新，见 DATA.QC_FULL_MIN。 */
    loadKpi();
    startQcLoops();
    loadCatalog();
  }
  function loadCatalog() {
    api('/api/portal-catalog').then(function (d) {
      var c = d && d.catalog;
      /* editable 与 PUT 的判据共用服务端那一份（is_privileged），
         自己猜「我在 localhost 所以应该能改」会出现「前端以为能改、一保存 403」。 */
      state.catalogEditable = !!(d && d.editable);
      if (c && Array.isArray(c.items) && c.items.length) {
        /* 顺序：subGroups 必须先落好，migrateSubOf 靠它判断 boSub 真正属于哪个分组 */
        state.subGroups = normalizeSubMap(c.subGroups);
        state.order = normOrderMap(c.order);
        state.tabLabels = normTabLabels(c.tabLabels);
        setCatalog(migrateSubOf(c.items));
        state.groups = Array.isArray(c.groups) && c.groups.length ? normalizeGroupList(c.groups) : state.groups;
      }
      render();
      /* 目录到位后必须重跑一次 renderWho（2026-10-12 修）：
         renderSysMenu()（用户菜单里的 System Management 条目）读的是**当前目录**的
         System Admin 组。而首次 renderWho() 在 start() 之前就跑了（见登录成功那处），
         那时 ITEMS 还是内置 data.js —— 于是菜单里列出的是内置那 6 项
         （Table Browser / Data Upload …），而不是服务端目录真正的
         Task Manager / Settings。用户报「System Management 里没有 Task Manager」
         就是这个原因。这里补一次，让菜单跟随实时目录刷新。 */
      renderWho();
      /* `?edit=1` 深链（与 MsPortal 同一入口）：仍要 editable 为真，setEditing 里已兜 */
      if (/[?&]edit=1(&|$)/.test(location.search)) setEditing(true);
    }).catch(function () { /* 服务端没有目录就用内置 data.js，首屏已经渲染过了（编辑按钮保持隐藏） */ });
  }

  function boot() {
    applyI18n();
    mainLocked(true);
    bind();
    tick(); window.setInterval(tick, 1000);
    /* 缩放锁的自愈定时器：与地图是否已经渲染无关，只管每 2 秒把"锁定"这个状态
       补施加到当前存在的 iframe 树上（解锁时它自己空转，见 sweepMapWheelLock）。
       放这里而不是 wireMap 里：地图会被重建（切页签 / 换主题），wireMap 也会重跑，
       定时器必须只有**一个**。 */
    startMapWheelLockTimer();
    envBadge();
    probe().then(function () {
      if (!state.authOk) { renderGate(); return; }
      renderGate(); mainLocked(false); start();
    });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();