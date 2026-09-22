/* ============================================================================
   olbr.js — OLR MS 门户「只读展示版」
   ----------------------------------------------------------------------------
   数据来源：
     · /MsPortal/assets/data.js   → window.MS_PORTAL_DATA（51 个看板 / 9 分组 / QC 定义 / 升级机制）
     · /MsPortal/assets/access.js → window.MSPortalAccess.canSee（与门户、查看器同一套权限判定）
     · GET/PUT /api/portal-catalog → 服务端全局目录（有则覆盖内置，无则用内置；编辑态可写）
     · GET /api/portal-qc/*       → 六个实时指标与下钻明细
     · /MsPortal/viewer.html      → 看板查看器（打开动作整个交给它，本页不重复实现）
   本页提供「分组 / 子分组 + 排序」的编辑（2026-09-22 加），不提供看板维护 / 用户管理
   —— 后两样仍归 /MsPortal/。编辑态只在服务端 GET 回 `editable:true` 时出现（= 服务器
   本机或持 X-API-Token），局域网访客看到的仍是纯只读页。改动走 PUT 落到**全局共享**的
   目录，与 MsPortal 同一份文档、同一套语义（subGroups / order / item.subOf），
   所以这边一存，MsPortal 刷新后就是同一个结果；反之 MsPortal 的改动这里也能读到。
   ⚠️ 三条不能碰的红线：
     1  绝不写 `msportal.*` 那几个 localStorage 键（那是 MsPortal 的**个人层**：
        order / assign / groups / renames，跟着写会把别人的界面悄悄改掉）；
        本页自己的持久化只有 `olbr.*`，且只有主题 / 语言 / 页签，不含目录。
     2  PUT 是**整份文档替换**（后端 `_normalize_catalog` 重建字典，没带的键等于删掉），
        所以每次写都要把 items + subGroups + order 三份发全，且 items 用服务端原样那份
        （ITEMS 全量），不是屏幕上的筛选子集 —— 少发一条，全站就少一条看板。
     3  后端**没有版本号 / ETag**，谁最后 PUT 谁赢。因此保存中禁用重复提交（state.saving），
        且一次只改一个字段就立刻落盘，不攒批量改动放大覆盖窗口。

   与 MsPortal 刻意不同的四处（都是上一轮评审的结论）：
     1  搜索与筛选常驻、且**不持久化**。MsPortal 会把上次的筛选写进 localStorage，
        下次打开时 13 个面板里 7 个显示空态，用户以为系统坏了。
     2  筛选生效时**隐藏没有结果的分组面板**，而不是给每个面板摆一个空态框。
     3  升级机制默认收成一条值班带（52px），展开才出全表（原来常驻 583px）。
     4  卡片只有两种、强调色只有两个色相，图标砖不再按分组上实色。
   ========================================================================== */
(function () {
  'use strict';

  var D = window.MS_PORTAL_DATA || {};
  var ACC = window.MSPortalAccess || { canSee: function () { return true; } };
  var root = document.documentElement;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* --------------------------------------------------------------- i18n -- */
  var S = {
    zh: {
      'tagline': '更智能的运维 · 更高的效率 · 更好的网络',
      'mast.admin': '管理门户', 'mast.uni': '统一门户', 'mast.logout': '退出',
      'skip': '跳到主内容',
      'search.ph': '搜索看板名称、描述、责任人、标签…',
      'rail.all': '全部', 'rail.clear': '清除筛选',
      'count.all': '{n} 个看板 · {g} 个分组',
      'count.hit': '{n} / {t} 个看板命中',
      'qc.title': 'Quality Control 质量监控核心指标',
      'qc.sub': '未清除告警 / 工单 / 变更 / 维护 / 备件 · 30 天达标口径',
      'qc.sla': '30 天达标率', 'qc.of': '{p} / {q} 站点',
      'qc.when': '告警每 5 分钟 · 其余每小时 :06 · 更新于 {t}',
      'qc.err': '指标接口不可用：{e}', 'qc.retry': '重试',
      'qc.drill': '点击查看明细',
      'cxo.title': 'CXO View 决策战略层', 'cxo.sub': '统一总控与运营视窗',
      'map.title': '利比里亚网络拓扑全景', 'map.sub': 'Central Liberia Regional Topology',
      'map.gis': 'GIS 地图', 'map.mw': '微波实时', 'map.alarm': '实时告警', 'map.loss': '传输丢包',
      'map.open': '新窗口打开', 'map.reload': '重新加载', 'map.load': '加载中…',
      'esc.title': '升级机制 Escalation Matrix',
      'esc.sub': '值班升级联系人 · Orange / LONESTAR 双网号码',
      'esc.expand': '展开全部 {n} 条', 'esc.collapse': '收起',
      'esc.now': '当前值班', 'esc.copy': '复制本级号码', 'esc.copied': '已复制',
      'esc.lv': '职级', 'esc.pos': '岗位', 'esc.name': '姓名', 'esc.mail': '邮箱',
      'esc.count': '{n} 条 · {lv} 级', 'esc.src': '数据源：升级机制.xlsx',
      'v.open': '查看全部', 'v.empty': '该分组暂无看板',
      'v.subOther': '未归类',
      'mast.edit': '编辑分组', 'mast.editOn': '退出编辑',
      'edit.tipOn': '进入编辑：改分组 / 子分组与排序，保存到服务端全局目录（所有人可见）',
      'edit.tipOff': '退出编辑',
      'edit.banner': '编辑模式 · 改动立即写入服务端全局目录，MsPortal 和本页的所有人都会看到',
      'edit.bannerK': '编辑模式',
      'edit.hint': '拖动卡片＝组内排序 · 拖到子分组＝归类 · 点「分组」＝改归属',
      'edit.reset': '重置顺序', 'edit.resetTip': '清掉本分组的自定义顺序，回到按访问量排序',
      'edit.subAdd': '添加子分组', 'edit.subZhPh': '中文名', 'edit.subEnPh': '英文名',
      'edit.subDel': '删除', 'edit.subDelTip': '删除该子分组（里面的看板落到「未归类」，不会丢看板）',
      'edit.subRename': '改名', 'edit.subOk': '重命名', 'edit.subCancel': '取消',
      'edit.delConfirm': '删除子分组「{n}」？里面的看板会落到「未归类」，看板本身不会丢。',
      'edit.dupName': '这个子分组已经存在了', 'edit.needName': '先填一个名字',
      'edit.groups': '分组', 'edit.groupsTip': '勾选这张看板要出现在哪些分组里',
      'edit.saved': '已保存到服务端 · 所有人可见', 'edit.err': '保存失败：{e}',
      'edit.readonly': '当前身份只能读目录（需在服务器本机或带 X-API-Token 才能改）',
      'edit.busy': '上一条还在保存，请先等它完成',
      'edit.noServer': '还没读到服务端目录，暂时不能编辑',
      'edit.dropSub': '拖到这里＝归入该子分组',
      'edit.orderOk': '顺序已更新', 'edit.orderReset': '已恢复默认排序',
      'edit.subAdded': '子分组已添加', 'edit.subRenamed': '子分组已改名',
      'edit.subDeleted': '子分组已删除', 'edit.subMoved': '子分组归属已更新',
      'edit.grpOk': '分组归属已更新',
      'edit.kSub': '子分组', 'edit.kOrder': '自定义顺序',
      'edit.needGroup': '至少要属于一个分组',
      'edit.lost': '服务端没有保存 {k}（后端可能是旧版，需要重启 my_app）',
      'edit.saving': '保存中…',
      /* 一级分组改名 / 新增 / 删除 + 看板标题（2026-09-22 加，全部写服务端全局目录） */
      'edit.grpEdit': '改分组名', 'edit.grpEditTip': '改这个分组的显示名与说明（分组 id 不变，归属/排序/子分组都不会被打断）',
      'edit.grpAdd': '新增分组', 'edit.grpAddTip': '新建一个一级分组，会出现在页签条最右边',
      'edit.grpDel': '删除该分组',
      'edit.grpRenamed': '分组已改名', 'edit.grpAdded': '分组已新增', 'edit.grpDeleted': '分组已删除',
      'edit.grpNeedName': '先填一个分组名', 'edit.grpDup': '这个分组名已经存在了',
      'edit.grpBuiltin': '内置分组只能改名，不能删除',
      'edit.grpDelConfirm': '删除分组「{n}」？其中的看板只是从这个分组移出（仍留在别的分组里），此操作对所有人生效。',
      'edit.grpHomeless': '有 {n} 张看板只属于这个分组，先给它们勾上别的分组再删',
      'edit.title': '改名字', 'edit.titleTip': '改这张看板的中文名 / 英文名（存服务端，所有人可见）',
      'edit.titleOk': '看板名字已更新', 'edit.needTitle': '中英文名不能同时为空',
      'edit.formSave': '保存', 'edit.formAdd': '添加',
      'edit.f.zh': '中文名', 'edit.f.en': '英文名', 'edit.f.subZh': '中文说明', 'edit.f.subEn': '英文说明',
      'edit.fph.zh': '显示给中文用户', 'edit.fph.en': 'Shown to English users',
      'edit.fph.subZh': '一句话说明这一组是什么', 'edit.fph.subEn': 'Optional one-line description',
      'edit.kGroups': '一级分组',
      'v.emptyFilter': '当前筛选下没有看板', 'v.adjust': '调整关键词或清除筛选',
      'aux.qa': '知识库与技术支持', 'aux.friends': '生态协作入口', 'aux.admin': '系统与运维配置',
      'aux.reports': '任务报告文件', 'aux.tools': '本页相关',
      'aux.ms': '在 MsPortal 维护分组 / 看板 / 账号', 'aux.uni': '统一门户看板门户',
      'aux.more': '展开其余 {n} 项', 'aux.less': '收起',
      'foot.branch': '利比里亚办事处网络运营中心 (OLR MS)', 'foot.ok': '安全合规模式运行',
      'foot.src': '目录：{n} 个看板 · 生成于 {d}',
      'st.online': '在线', 'st.beta': '试用',
      'pf.myapp': '自研 my_app', 'pf.finebi': 'FineBI', 'pf.external': '外部系统',
      'gate.title': '登录统一门户', 'gate.sub': '与 /uniplam/、/MsPortal/ 共用同一套账号与权限。',
      'gate.user': '用户名', 'gate.pass': '密码', 'gate.go': '登录', 'gate.busy': '登录中…',
      'gate.bad': '用户名或密码错误', 'gate.locked': '尝试次数过多，稍后再试',
      'gate.net': '无法连接认证服务', 'gate.cancel': '取消',
      'dr.title': '明细', 'dr.rows': '{n} 条', 'dr.page': '{p} / {q}',
      'dr.load': '正在读取明细…', 'dr.empty': '没有匹配的记录', 'dr.err': '明细读取失败：{e}',
      'dr.none': '暂无数据', 'dr.qPh': '过滤明细…',
      'env.local': '本机', 'env.lr': '利比里亚',
      'foot.ver': 'Ver 1.0-OLBR · 展示版',
      'doc.title': 'OLR MS 门户 · Liberia NOC/SOC 统一入口 (ZTE OLR MS Portal)',
      'doc.desc': 'ZTE OLR MS 门户看板 —— 利比里亚 NOC/SOC 自动化工具平台入口（展示版）。',
      'attr.theme': '深色 / 浅色',
      'attr.adminTitle': '看板维护 / 用户管理仍在 MsPortal 完成（本页只改分组、子分组与排序）',
      'attr.searchAria': '搜索看板', 'attr.chipsAria': '分组筛选', 'attr.statusAria': '状态筛选',
      'attr.drQAria': '过滤明细'
    },
    en: {
      'tagline': 'Smarter Operations · Higher Efficiency · Better Network',
      'mast.admin': 'Admin portal', 'mast.uni': 'Unified portal', 'mast.logout': 'Sign out',
      'skip': 'Skip to main content',
      'search.ph': 'Search dashboards, owners, tags…',
      'rail.all': 'All', 'rail.clear': 'Clear filters',
      'count.all': '{n} dashboards · {g} groups',
      'count.hit': '{n} / {t} dashboards match',
      'qc.title': 'Quality Control — key indicators',
      'qc.sub': 'Active alarms / tickets / changes / PMT / spares · 30-day compliance',
      'qc.sla': '30-day compliance', 'qc.of': '{p} / {q} sites',
      'qc.when': 'alarms every 5 min · others hourly :06 · updated {t}',
      'qc.err': 'Indicator API unavailable: {e}', 'qc.retry': 'Retry',
      'qc.drill': 'Click for details',
      'cxo.title': 'CXO View', 'cxo.sub': 'Executive strategy & operation window',
      'map.title': 'Central Liberia Regional Topology', 'map.sub': 'Network panorama',
      'map.gis': 'GIS map', 'map.mw': 'MW real-time', 'map.alarm': 'Live alarms', 'map.loss': 'Packet loss',
      'map.open': 'Open in new tab', 'map.reload': 'Reload', 'map.load': 'Loading…',
      'esc.title': 'Escalation Matrix',
      'esc.sub': 'Duty contacts · Orange / LONESTAR numbers',
      'esc.expand': 'Expand all {n} rows', 'esc.collapse': 'Collapse',
      'esc.now': 'On duty', 'esc.copy': 'Copy this level', 'esc.copied': 'Copied',
      'esc.lv': 'Level', 'esc.pos': 'Position', 'esc.name': 'Name', 'esc.mail': 'E-mail',
      'esc.count': '{n} rows · {lv} levels', 'esc.src': 'Source: escalation matrix',
      'v.open': 'Full list', 'v.empty': 'No dashboard in this group',
      'v.subOther': 'Unassigned',
      'mast.edit': 'Edit groups', 'mast.editOn': 'Done',
      'edit.tipOn': 'Edit groups / sub-groups and order — saved to the shared server catalog (visible to everyone)',
      'edit.tipOff': 'Leave editing',
      'edit.banner': 'Editing · changes go straight into the shared server catalog, visible in MsPortal and here for everyone',
      'edit.hint': 'Drag a card = reorder · drag onto a sub-group chip = assign · “Groups” = change membership',
      'edit.reset': 'Reset order', 'edit.resetTip': 'Drop the custom order for this group and sort by usage again',
      'edit.subAdd': 'Add sub-group', 'edit.subZhPh': 'Name (zh)', 'edit.subEnPh': 'Name (en)',
      'edit.subDel': 'Delete', 'edit.subDelTip': 'Delete this sub-group (its dashboards fall into “Unassigned”, none is lost)',
      'edit.subRename': 'Rename', 'edit.subOk': 'OK', 'edit.subCancel': 'Cancel',
      'edit.delConfirm': 'Delete the sub-group “{n}”? Its dashboards move to “Unassigned”; no dashboard is lost.',
      'edit.dupName': 'That sub-group already exists', 'edit.needName': 'Type a name first',
      'edit.groups': 'Groups', 'edit.groupsTip': 'Tick the groups this dashboard should appear in',
      'edit.saved': 'Saved to the server · visible to everyone', 'edit.err': 'Save failed: {e}',
      'edit.readonly': 'This session can only read the catalog (run on the server host, or send X-API-Token, to edit)',
      'edit.busy': 'The previous change is still saving — wait for it',
      'edit.noServer': 'Server catalog not loaded yet — editing is unavailable',
      'edit.dropSub': 'Drop here to assign this sub-group',
      'edit.orderOk': 'Order updated', 'edit.orderReset': 'Back to usage order',
      'edit.subAdded': 'Sub-group added', 'edit.subRenamed': 'Sub-group renamed',
      'edit.subDeleted': 'Sub-group deleted', 'edit.subMoved': 'Sub-group assignment updated',
      'edit.grpOk': 'Group membership updated',
      'edit.kSub': 'sub-groups', 'edit.kOrder': 'custom order',
      'edit.needGroup': 'A dashboard must stay in at least one group',
      'edit.lost': 'the server did not store {k} (an older backend may need a my_app restart)',
      'edit.saving': 'Saving…',
      'edit.grpEdit': 'Rename group', 'edit.grpEditTip': 'Edit this group label and description (the group id never changes, so membership / order / sub-groups all survive)',
      'edit.grpAdd': 'New group', 'edit.grpAddTip': 'Create a first-level group; it appears at the right end of the tab strip',
      'edit.grpDel': 'Delete this group',
      'edit.grpRenamed': 'Group renamed', 'edit.grpAdded': 'Group added', 'edit.grpDeleted': 'Group deleted',
      'edit.grpNeedName': 'Type a group name first', 'edit.grpDup': 'That group name already exists',
      'edit.grpBuiltin': 'Built-in groups can be renamed but not deleted',
      'edit.grpDelConfirm': 'Delete group “{n}”? Dashboards are only removed from this group (they stay in their other groups). Applies to everyone.',
      'edit.grpHomeless': '{n} dashboard(s) belong to this group only — give them another group before deleting',
      'edit.title': 'Rename', 'edit.titleTip': 'Edit this dashboard’s Chinese / English title (stored on the server, visible to everyone)',
      'edit.titleOk': 'Dashboard title updated', 'edit.needTitle': 'The two titles cannot both be empty',
      'edit.formSave': 'Save', 'edit.formAdd': 'Add',
      'edit.f.zh': 'Chinese name', 'edit.f.en': 'English name', 'edit.f.subZh': 'Chinese note', 'edit.f.subEn': 'English note',
      'edit.fph.zh': 'Shown to Chinese users', 'edit.fph.en': 'Shown to English users',
      'edit.fph.subZh': 'One-line description of this group', 'edit.fph.subEn': 'Optional one-line description',
      'edit.kGroups': 'first-level groups',
      'v.emptyFilter': 'Nothing matches the current filters', 'v.adjust': 'Adjust keywords or clear filters',
      'aux.qa': 'Knowledge & support', 'aux.friends': 'Ecosystem entries', 'aux.admin': 'System & O&M',
      'aux.reports': 'Task report files', 'aux.tools': 'About this page',
      'aux.ms': 'Manage groups / dashboards / accounts in MsPortal', 'aux.uni': 'Unified dashboard portal',
      'aux.more': 'Show {n} more', 'aux.less': 'Show less',
      'foot.branch': 'Liberia Office · Network Operation Center (OLR MS)', 'foot.ok': 'Compliance mode',
      'foot.src': 'Catalog: {n} dashboards · built {d}',
      'st.online': 'online', 'st.beta': 'beta',
      'pf.myapp': 'my_app', 'pf.finebi': 'FineBI', 'pf.external': 'external',
      'gate.title': 'Sign in to the unified portal',
      'gate.sub': 'Same account and permissions as /uniplam/ and /MsPortal/.',
      'gate.user': 'Username', 'gate.pass': 'Password', 'gate.go': 'Sign in', 'gate.busy': 'Signing in…',
      'gate.bad': 'Wrong username or password', 'gate.locked': 'Too many attempts, try later',
      'gate.net': 'Cannot reach the auth service', 'gate.cancel': 'Cancel',
      'dr.title': 'Details', 'dr.rows': '{n} rows', 'dr.page': '{p} / {q}',
      'dr.load': 'Loading details…', 'dr.empty': 'No matching record', 'dr.err': 'Detail failed: {e}',
      'dr.none': 'No data', 'dr.qPh': 'Filter rows…',
      'env.local': 'Local host', 'env.lr': 'Liberia',
      'foot.ver': 'Ver 1.0-OLBR · showcase edition',
      'doc.title': 'OLR MS Portal · Liberia NOC/SOC unified entry',
      'doc.desc': 'ZTE OLR MS portal — entry to the Liberia NOC/SOC automation tool platform (showcase edition).',
      'attr.theme': 'Dark / Light',
      'attr.adminTitle': 'Dashboard maintenance and user management stay in MsPortal (this page edits groups, sub-groups and order only)',
      'attr.searchAria': 'Search dashboards', 'attr.chipsAria': 'Group filter', 'attr.statusAria': 'Status filter',
      'attr.drQAria': 'Filter rows'
    }
  };

  function t(k) { var a = S[state.lang] || S.zh; return a[k] != null ? a[k] : (S.zh[k] != null ? S.zh[k] : k); }
  function tf(k, m) { return String(t(k)).replace(/\{(\w+)\}/g, function (_, x) { return m && m[x] != null ? m[x] : ''; }); }

  /* ------------------------------------------------------------- helpers -- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function ls(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function ss(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  function fmtTime(ms) {
    var d = new Date(ms); if (isNaN(d)) return '';
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
  var PH = {
    'chart-polar': 'ph-chart-polar', gauge: 'ph-gauge', bell: 'ph-bell', map: 'ph-map-trifold',
    ticket: 'ph-ticket', siren: 'ph-siren', clock: 'ph-clock', 'chart-line': 'ph-chart-line',
    link: 'ph-link', cpu: 'ph-cpu', broadcast: 'ph-broadcast', battery: 'ph-battery-charging',
    package: 'ph-package', wrench: 'ph-wrench', upload: 'ph-cloud-arrow-up', table: 'ph-table',
    archive: 'ph-archive', chat: 'ph-chat-circle-dots', book: 'ph-book-open-text', gear: 'ph-gear',
    dashboard: 'ph-squares-four', key: 'ph-lock-key', warning: 'ph-warning', briefcase: 'ph-briefcase',
    git: 'ph-git-pull-request', user: 'ph-user', flame: 'ph-fire', folder: 'ph-folder-open',
    'arrow-up-right': 'ph-arrow-up-right', 'shield': 'ph-shield-check', 'globe': 'ph-globe-hemisphere-west'
  };
  function ic(name) { return '<i class="ph ' + (PH[name] || PH.dashboard) + '" aria-hidden="true"></i>'; }

  /* ------------------------------------------------------------- layout -- */
  /* 三级层级的归属写在这里（数据里没有 tier 字段）。
     T0 = 左栏焦点区（CXO 用大卡、SP 用行式，两块叠在地图左边）；
     T1 = 主视图：一组一个页签，一次只展开一个面板，面板内是卡片流；
     T2 = 辅助：默认只显示 2 行。 */
  var T0 = ['CXO View', 'SP View'];
  var T1 = ['MS View', 'FLM View', 'FO View', 'BO View'];
  var T2 = ['Knowledge Q&A', 'Friends Link', 'System Admin'];
  var AUX_ROWS = 2;           /* 辅助分组默认露出的行数 */
  var OTHER = '__other';      /* 不属于任何已知分组的看板，在页签里单列一项 */
  var AUX_TITLES = {
    'Knowledge Q&A': 'aux.qa', 'Friends Link': 'aux.friends', 'System Admin': 'aux.admin'
  };
  var MAP_TABS = [
    { page: 'gis', key: 'map.gis', icon: 'map' },
    { page: 'mwRealTime', key: 'map.mw', icon: 'broadcast' },
    { page: 'realtime_alarm', key: 'map.alarm', icon: 'bell' },
    { page: 'packet_loss', key: 'map.loss', icon: 'link' }
  ];
  /* 与 MsPortal 同一份剥离样式：让同源 iframe 只留 Leaflet 画布，
     否则地图外面会套着该页面自己的筛选栏 / KPI 卡 / 侧栏。 */
  var MAP_STRIP_CSS = [
    'html,body{margin:0!important;padding:0!important;height:100%!important;overflow:hidden!important;background:transparent!important}',
    '#root,.ant-layout,.ant-layout-content{height:100%!important;min-height:0!important;margin:0!important;padding:0!important;background:transparent!important}',
    'main#main-content{height:100%!important;padding:0!important;margin:0!important;overflow:hidden!important}',
    'main#main-content > div{height:100%!important;padding:0!important;margin:0!important;display:block!important}',
    'main#main-content > div > *:not(:has(.leaflet-container)):not(:has(iframe)):not(iframe){display:none!important}',
    'main#main-content > div > iframe,main#main-content > div > *:has(iframe){width:100%!important;height:100%!important;border:0!important;display:block!important;margin:0!important;padding:0!important}',
    'main#main-content *:has(.leaflet-container){height:100%!important;min-height:0!important;max-height:none!important}',
    'main#main-content .ant-card:has(.leaflet-container){height:100%!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;background:transparent!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-head{display:none!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-body{height:100%!important;padding:0!important}',
    'main#main-content .ant-card-body:has(.leaflet-container){position:relative!important}',
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
    '.leaflet-container{height:100%!important;min-height:0!important;max-height:none!important;width:100%!important;border-radius:0!important}'
  ].join('');

  /* -------------------------------------------------------------- state -- */
  /* 默认语言跟随浏览器（与 index.html 首帧脚本的 guessLang 同一口径，
     两边不一致会闪一下另一种语言）。有用户选择时永远以选择为准。 */
  function detectLang() {
    var v = ls('olbr.lang', '');
    if (v === 'en' || v === 'zh') return v;
    var nav = (navigator.language || navigator.userLanguage || 'zh') + '';
    return nav.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }
  var state = {
    lang: detectLang(),
    theme: root.classList.contains('dark') ? 'dark' : 'light',
    q: '', group: 'all', status: 'all',
    user: null, authOk: false, booted: false,
    items: (D.items || []).slice(), groups: (D.groups || []).slice(), order: {},
    qc: { loading: true, err: '', at: 0, m: {} },
    escOpen: false, escLv: 'LEVEL1',
    auxOpen: {},
    mapTab: ls('olbr.maptab', 'gis'),
    /* 默认落在 BO View：16 张卡、五个子分组，是这块最能说明「门户里到底有什么」的一组 */
    viewTab: ls('olbr.viewtab', 'BO View'),
    viewSub: '',                          /* 当前分组下的二级子页签，不跨分组记 */
    subGroups: null,                      /* catalog.subGroups 归一化后的定义，null = 用内置 */
    /* ---- 编辑态（2026-09-22 加）---- */
    /* catalogEditable 只认服务端 GET 回的 `editable`（= 服务器本机 / 持 X-API-Token），
       不写死、也不从本地推断 —— 猜错的表现是「点了保存才 403」。 */
    catalogEditable: false, editing: false, saving: false,
    subEdit: '',                          /* 正在改名的子分组 id（同时只开一个） */
    grpFor: null,                         /* 分组归属浮层当前挂在看板编号上 */
    popForm: null,                        /* 改名类浮层：{kind:'grp'|'grpadd'|'title', id} */
    dragKind: '', dragNo: null, dragGid: '', dragEl: null, dragBefore: false,
    drill: { metric: '', title: '', q: '', page: 1, size: 25, rows: [], columns: [], total: 0, loading: false, err: '' }
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

  /* 搜索：多词 AND，命中集覆盖标题 / 描述 / 责任人 / 部门 / 标签 / 平台。
     英文模式下搜 "Hourly" 也该命中，所以把 terms.js 的映射值一起塞进 haystack。 */
  function tokens() {
    return String(state.q || '').toLowerCase().split(/\s+/).filter(Boolean);
  }
  function hay(it) {
    return [it.titleZh, it.titleEn, it.descZh, it.descEn, it.owner, it.ownerEn, term('owner', it.owner),
      it.dept, it.deptEn, term('dept', it.dept),
      (it.tags || []).join(' '), it.platform, it.platformZh, it.status, it.freq, term('freq', it.freq)]
      .filter(Boolean).join(' ').toLowerCase();
  }
  function match(it, tk) { if (!tk.length) return true; var h = hay(it); return tk.every(function (x) { return h.indexOf(x) !== -1; }); }
  function filtered(gid) {
    var tk = tokens();
    return allowed().filter(function (it) {
      if (gid && !inGroup(it, gid)) return false;
      if (state.group !== 'all' && !inGroup(it, state.group)) return false;
      if (state.status !== 'all' && it.status !== state.status) return false;
      return match(it, tk);
    }).sort(sorter(gid || ''));
  }
  function filtering() { return !!tokens().length || state.group !== 'all' || state.status !== 'all'; }
  function knownGids() {
    var seen = {}; state.groups.forEach(function (g) { seen[g.id] = 1; });
    T0.concat(T1, T2).forEach(function (g) { seen[g] = 1; });
    return Object.keys(seen);
  }
  function groupsOf(it) { return it.groups || []; }
  /* 页签条上的分组 = 固定四个 + 服务端新增的分组（按 groups 数组顺序排在后面）。
     新增分组没有专门的 tier 字段，一律落到 L1 页签：它是「用户自己造的一级分组」，
     出现在最显眼的那一排最不容易让人找不到。 */
  function tabGids() {
    var out = T1.slice(), seen = {};
    T0.concat(T1, T2).forEach(function (g) { seen[g] = 1; });
    state.groups.forEach(function (g) { if (g && g.id && !seen[g.id]) { seen[g.id] = 1; out.push(g.id); } });
    return out;
  }
  /* 已经被版面安置的分组：左栏 + 页签 + 辅助区。用于「其他看板」兜底与主分组判定。 */
  function placedGids() { return T0.concat(tabGids(), T2); }
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
     这里再 esc() 会和 hl()/esc() 叠成 &amp;amp;，页面上就露出 &amp; 这种字面实体。 */
  function titleOf(it) { return (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) || '#' + it.no; }
  function descOf(it) { return state.lang === 'en' ? (it.descEn || it.descZh || '') : (it.descZh || it.descEn || ''); }
  function ownerOf(it) { return state.lang === 'en' ? enOf(it.ownerEn, 'owner', it.owner) : it.owner; }
  function freqOf(it) { return state.lang === 'en' ? term('freq', it.freq) : it.freq; }
  function pfOf(it) { return t('pf.' + it.platform) || it.platform; }
  function stOf(it) { return it.status === 'beta' ? t('st.beta') : t('st.online'); }
  function vlink(it, gid) {
    return '/MsPortal/viewer.html?no=' + encodeURIComponent(it.no) +
      '&gid=' + encodeURIComponent(gid || primaryGroup(it) || '');
  }
  /* 高亮命中词。必须**单趟**扫描 + 分段转义，不能「先 esc 再逐词 replace」：
       · 逐词链式 replace 会让第 2 个词命中第 1 个词刚注入的 <span class="hit">
         （搜 "hit" 就把自己套进去，属性直接被打断）；
       · 反过来先 esc 再替换，命中的可能是 &amp; 里的 "amp" 这种实体残片。
     所以：在原文上用一个合并后的 alternation 正则走一遍，
     每段原文各自 esc()，注入的标签只在两个安全片段之间。 */
  function hl(s) {
    var raw = String(s == null ? '' : s);
    var tk = tokens();
    if (!tk.length) return esc(raw);
    var re = new RegExp('(' + tk.map(function (x) {
      return x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('|') + ')', 'ig');
    var out = '', last = 0, m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index === last && m[0] === '') { re.lastIndex++; continue; }
      out += esc(raw.slice(last, m.index)) + '<span class="hit">' + esc(m[0]) + '</span>';
      last = m.index + m[0].length;
    }
    return out + esc(raw.slice(last));
  }

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
     所以 L0 的 CXO 焦点卡只给改标题；页签/SP 清单两张都给。 */
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
      '<span class="c-bd"><span class="c-t">' + hl(titleOf(it)) + '</span>' +
      '<span class="c-d">' + hl(descOf(it)) + '</span>' + metaHtml(it) +
      (ed ? edBtns(it, gid, true) : '') + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }
  function focusCard(it, gid) {
    var ed = canEdit();
    return '<a class="fcard' + (ed ? ' is-ed' : '') + '" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer" data-no="' + it.no + '">' +
      '<span class="ic-ico">' + ic(it.icon) + '</span>' +
      '<span class="ic-bd"><span class="ttl">' + hl(titleOf(it)) + '</span>' +
      '<span class="dsc">' + hl(descOf(it)) + '</span>' + metaHtml(it) +
      (ed ? edBtns(it, gid, false) : '') + '</span>' +
      '<i class="ph ph-arrow-up-right ic-go" aria-hidden="true"></i></a>';
  }

  /* -------------------------------------------------------------- render -- */
  function panelHead(gid, extraTools, nArg) {
    var n = nArg == null ? filtered(gid).length : nArg;
    /* 「重置顺序」只在该分组真有自定义顺序时才出现 —— 没有顺序还给按钮就是噪声。
       落盘写的是 order[gid] = []（显式空数组），不是删键：两者对前端的含义不同。 */
    var rst = canEdit() && (state.order[gid] || []).length
      ? '<button type="button" class="ct ct--rst" data-act="rst-order" data-gid="' + esc(gid) +
        '" title="' + esc(t('edit.resetTip')) + '"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>' +
        esc(t('edit.reset')) + '</button>' : '';
    var gt = '';
    if (canEdit() && gid && gid !== OTHER) {
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
      '<a class="p-x" href="/MsPortal/viewer.html?gid=' + encodeURIComponent(gid) +
      '" target="_blank" rel="noopener noreferrer">' + t('v.open') + ' <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a></div>';
  }

  function renderRail() {
    var all = allowed(), tk = tokens(), box = $('#chips');
    var mk = function (id, label, n, on) {
      return '<button type="button" class="chip" data-gid="' + esc(id) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
        esc(label) + '<small>' + n + '</small></button>';
    };
    var html = mk('all', t('rail.all'), all.filter(function (it) { return match(it, tk) && (state.status === 'all' || it.status === state.status); }).length, state.group === 'all');
    state.groups.forEach(function (g) {
      var n = filtered(g.id).length;
      if (!n && filtering()) return;                       /* 筛选中且不命中的分组直接从 chips 里退场 */
      html += mk(g.id, gName(g.id), n, state.group === g.id);
    });
    box.innerHTML = html;
    $$('.seg-b[data-status]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-status') === state.status ? 'true' : 'false');
    });
    var hit = all.filter(function (it) {
      return match(it, tk) && (state.status === 'all' || it.status === state.status) &&
        (state.group === 'all' || inGroup(it, state.group));
    }).length;
    $('#count').innerHTML = filtering()
      ? '<b>' + hit + '</b> / ' + all.length + ' ' + esc(state.lang === 'en' ? 'match' : '命中')
      : '<b>' + all.length + '</b> ' + esc(t('rail.all')) + ' · ' + state.groups.length + ' ' + esc(state.lang === 'en' ? 'groups' : '个分组');
    $('#clearBtn').hidden = !filtering();
    $('#rail').classList.toggle('is-filtered', filtering());
  }

  function renderBand() {
    var box = $('#band'), q = state.qc;
    if (q.loading) {
      box.innerHTML = '<div class="band-l"><span class="sk" style="width:96px;height:96px;border-radius:50%"></span>' +
        '<div class="band-txt" style="flex:1"><span class="sk" style="width:52%"></span>' +
        '<span class="sk s" style="width:72%"></span><span class="sk s" style="width:40%"></span></div></div>' +
        '<div class="metrics">' + (D.qc || []).map(function () {
          return '<div class="metric"><span class="sk" style="width:56%"></span><span class="sk v"></span><span class="sk s"></span></div>';
        }).join('') + '</div>';
      return;
    }
    if (q.err) {
      /* 上一版这里直接显示「—」，六个格子全是破折号，读起来像系统坏了 */
      box.innerHTML = '<div class="band-l"><div class="band-txt"><div class="band-k">' + esc(t('qc.title')) +
        '</div><p class="band-n" style="color:var(--crit)">' + esc(tf('qc.err', { e: q.err })) + '</p></div></div>' +
        '<div class="metrics" style="align-content:center"><button class="gb" data-act="qc-retry">' +
        esc(t('qc.retry')) + '</button></div>';
      return;
    }
    var m = q.m, sla = m.sla || {}, defs = D.qc || [];
    var pct = sla.value == null ? 0 : Math.max(0, Math.min(100, +sla.value));
    var tone = function (id, v) {
      if (id === 'alarm') return v > 0 ? 'crit' : 'ok';
      return '';
    };
    var sub = function (id) {
      var x = m[id] || {};
      if (id === 'alarm') return (x.sites != null ? x.sites + ' ' + esc(state.lang === 'en' ? 'sites down' : '断站站点') : '');
      if (id === 'pmt') return x.overdue != null ? (state.lang === 'en' ? 'overdue ' : '超期 ') + x.overdue : '';
      if (id === 'spms' && x.tables) return Object.keys(x.tables).map(function (k) { return k + ' ' + x.tables[k]; }).join(' · ');
      return '';
    };
    box.innerHTML =
      '<div class="band-l"><div class="ring" style="--v:' + pct + '"><b>' + (sla.value == null ? '—' : pct.toFixed(1) + '%') + '</b></div>' +
      '<div class="band-txt"><div class="band-k">' + esc(t('qc.sla')) + '</div>' +
      '<p class="band-n">' + esc(t('qc.title')) + ' · <em>' + (sla.pass || 0) + '</em> / <em>' + (sla.total || 0) + '</em></p>' +
      '<p class="band-when">' + esc(tf('qc.when', { t: q.at ? fmtTime(q.at).slice(11) : '--:--:--' })) + '</p></div></div>' +
      '<div class="metrics">' + defs.map(function (d) {
        var v = m[d.id] && m[d.id].value, err = m[d.id] && m[d.id].error;
        var tn = err ? 'err' : tone(d.id, v);
        return '<button type="button" class="metric" data-qc="' + esc(d.id) + '" data-tone="' + tn + '" ' +
          'title="' + esc(tf('qc.drill')) + ' · ' + esc(state.lang === 'en' ? d.subEn : d.subZh) + '">' +
          '<span class="metric-k">' + ic(d.icon) + esc(state.lang === 'en' ? d.en : d.zh) + '</span>' +
          '<span class="metric-v">' + (err ? esc(state.lang === 'en' ? 'n/a' : '不可用') : (v == null ? '—' : Number(v).toLocaleString('en-US'))) + '</span>' +
          '<span class="metric-s">' + (sub(d.id) || esc(state.lang === 'en' ? d.subEn : d.subZh)) + '</span>' +
          '<span class="metric-tick"></span></button>';
      }).join('') + '</div>';
  }

  function renderL0(keepMap) {
    var box = $('#l0');
    var maps = mapItems();
    var cxo = filtered('CXO View'), sp = filtered('SP View');
    /* 左栏：CXO 焦点卡在上、SP View 行式清单在下（按需求放在 CXO 下面），
       两块一起和右边的地图并排；窄到 1240 以下时地图整宽换行。 */
    var side = '';
    if (cxo.length || !filtering()) {
      side += '<section class="panel" data-tier="0" data-gid="CXO View" aria-label="CXO View">' +
        panelHead('CXO View') +
        (cxo.length ? cxo.map(function (it) { return focusCard(it, 'CXO View'); }).join('')
          : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') + '</section>';
    }
    if (sp.length || !filtering()) {
      side += '<section class="panel" data-tier="0" data-gid="SP View" aria-label="SP View">' +
        panelHead('SP View') +
        (sp.length ? '<div class="cards">' + sp.map(function (it) { return itemCard(it, 'SP View'); }).join('') + '</div>'
          : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') + '</section>';
    }
    /* 快速路径：目录保存 / 搜索 / 切语言都会重画 L0，但地图那一栏里的 iframe 一旦离开
       文档，Chrome 就直接丢弃它的内容文档 —— 「先抓节点再搬回来」救不回来（实测
       sameNode:true / sameWindow:false），代价是改一个字拓扑图重载几十秒。
       所以 src 没变时整块 map 不动，只换左栏；页签点击是 #l0 上的事件委托，不重绑也在。 */
    if (keepMap) {
      var col = document.getElementById('l0Col'), mp = document.getElementById('l0Map');
      if (col && mp && maps.length) {
        col.innerHTML = side;
        box.classList.toggle('no-side', !side);
        return;
      }
    }
    var html = '<div class="l0-col" id="l0Col">' + side + '</div>';
    box.classList.toggle('no-side', !side);
    if (maps.length) {
      html += '<section class="panel map" id="l0Map" data-tier="0" aria-label="Topology">' +
        '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(t('map.title')) + '</span>' +
        '<span class="p-s">' + esc(t('map.sub')) + '</span></span>' +
        '<div class="map-tabs"><div class="tabs" role="tablist">' + maps.map(function (m) {
          return '<button type="button" class="tab" role="tab" data-map="' + esc(m.page) + '" aria-selected="' +
            (m.page === state.mapTab ? 'true' : 'false') + '">' + ic(m.icon) + esc(t(m.key)) + '</button>';
        }).join('') + '</div>' +
        '<button type="button" class="gb gb--t" data-act="map-reload" title="' + esc(t('map.reload')) + '"><i class="ph ph-arrow-clockwise"></i><span>' + esc(t('map.reload')) + '</span></button>' +
        '<a class="gb gb--t" id="mapOpen" href="' + esc(curMap().src) + '" target="_blank" rel="noopener noreferrer" title="' + esc(t('map.open')) + '"><i class="ph ph-arrow-square-out"></i><span>' + esc(t('map.open')) + '</span></a>' +
        '</div></div>' +
        '<div class="canvas"><iframe id="mapFrame" title="' + esc(t('map.title')) + '" src="' + esc(curMap().src) + '"></iframe>' +
        '<div class="canvas-note"><span>' + esc(curMap().title) + '</span>' +
        '<span>/myapp/?page=' + esc(curMap().page) + '</span></div></div></section>';
    }
    box.innerHTML = html;
    wireMap();
  }

  function mapItems() {
    var all = allowed();
    return MAP_TABS.map(function (m) {
      var it = all.filter(function (x) { return String(x.url || '').indexOf('page=' + m.page) !== -1; })[0];
      return {
        page: m.page, key: m.key, icon: m.icon, item: it,
        title: it ? (state.lang === 'en' ? (it.titleEn || it.titleZh) : (it.titleZh || it.titleEn)) : m.page,
        src: '/myapp/?page=' + m.page + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : '')
      };
    }).filter(function (m) { return !!m.item; });
  }
  function curMap() {
    var ms = mapItems();
    return ms.filter(function (m) { return m.page === state.mapTab; })[0] || ms[0] || { page: '', src: 'about:blank', title: '' };
  }

  /* 二级子分组：与 MsPortal 同一份口径，定义随服务端目录落盘（catalog.subGroups）。
     归属只认 item.subOf[gid]；boSub 仅在整条 subOf 都不存在时作迁移前兜底，
     且要用「该分组下确实有这个子分组」校验过才认 —— 一个看板可以同挂多个分组
     （实测 no=11/12/13/18/36 同时在 FO + FLM），拿 boSub 直接套用会把 A 分组的
     归属串到 B 分组。内置三份是 data.js 打底用的，文案抄 portal.js 的 I18N 原值。 */
  var SUB_BUILTIN = {
    'BO View': [
      { id: 'wireless', zh: '无线射频、动力与外场排班', en: 'Radio, Power & Field Dispatch' },
      { id: 'core', zh: '核心网 (CS/PS) 及运营月报', en: 'Core Network (CS/PS) & Monthly Report' },
      { id: 'ip', zh: 'IP 承载网与工程专家支持', en: 'IP Bearer & Engineering Expert Support' }
    ]
  };
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
    if (has) return String(m[gid] || '');
    var legacy = it && it.boSub ? String(it.boSub) : '';
    if (!legacy) return '';
    return subGroupsOf(gid).some(function (s) { return s.id === legacy; }) ? legacy : '';
  }
  function subName(s) { return state.lang === 'en' ? (s.en || s.zh || s.id) : (s.zh || s.en || s.id); }

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
  function putCatalog(cat) {
    return fetch('/api/portal-catalog', {
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
    var snap = { items: itemsAll(), subs: state.subGroups, order: state.order, groups: state.groups };
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
        applyItems(migrateSubOf(c.items));
      }
      var lost = [];
      /* 后端若是旧版（改了 portal_catalog.py 但没重启），会静默不认识 subGroups / order / groups
         并把键丢掉 → 提示「已保存」而刷新后变回去，属于最难查的假成功，必须说出来。 */
      if (sentSubs && !state.subGroups) lost.push(t('edit.kSub'));
      if (sentOrder && !(state.order && Object.keys(state.order).length)) lost.push(t('edit.kOrder'));
      if (sentGroups && !(c && Array.isArray(c.groups) && c.groups.length)) lost.push(t('edit.kGroups'));
      toast(msg + ' · ' + (lost.length ? tf('edit.lost', { k: lost.join(' / ') }) : t('edit.saved')));
      renderCatalog();
    }).catch(function (e) {
      state.saving = false; rollback(snap); renderCatalog();
      toast(tf('edit.err', { e: (e && e.message) || e }));
    }).then(function () { state.saving = false; syncEditBtn(); });
  }
  function rollback(snap) {
    applyItems(snap.items); state.subGroups = snap.subs; state.order = snap.order;
    state.groups = snap.groups;
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
        var c = {}, before = groupsOf(it), gone = [];
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
  function addGroup(zh, en) {
    zh = String(zh || '').trim(); en = String(en || '').trim();
    var id = en || zh;
    if (!id) { toast(t('edit.grpNeedName')); return; }
    if (state.groups.some(function (g) { return g.id === id; })) { toast(t('edit.grpDup')); return; }
    var next = state.groups.concat([{ id: id, zh: zh || id, en: en || id, subZh: '', subEn: '', style: 'card' }]);
    /* 直接切到新分组：新建的分组是空的，留在当前页签就等于「没反应」，
       切过去才能立刻看到那颗空面板和它头上的改名/删除入口。 */
    commit(function () { state.groups = next; state.viewTab = id; state.viewSub = ''; }, t('edit.grpAdded'));
  }
  /* 删除一级分组比看起来危险：分组名只是标签，看板才是内容 —— 所以先把该分组从每张
     卡片的 groups 里摘掉，并且**先检查有没有人会因此无家可归**。任何一张卡会因为这次删除
     而属于零个分组，就直接拒绝并说明数量：门户里没有「不属于任何分组的看板」这种状态，
     那些卡在页签视图里是看不见的，删完才发现就等于把看板弄丢了。 */
  function delGroup(gid) {
    if (!gid || isBuiltinGroup(gid)) { toast(t('edit.grpBuiltin')); return; }
    var homeless = itemsAll().filter(function (it) {
      return groupsOf(it).length === 1 && inGroup(it, gid);
    });
    if (homeless.length) { toast(tf('edit.grpHomeless', { n: homeless.length })); return; }
    if (!window.confirm(tf('edit.grpDelConfirm', { n: gid }))) return;
    var nextGroups = state.groups.filter(function (g) { return g.id !== gid; });
    var nextItems = itemsAll().map(function (it) {
      if (!inGroup(it, gid)) return it;
      var c = {}; Object.keys(it).forEach(function (k) { c[k] = it[k]; });
      c.groups = groupsOf(it).filter(function (g) { return g !== gid; });
      return withSubOf(c, gid, '');
    });
    var nextOrder = shallow(state.order); delete nextOrder[gid];
    var nextSubs = state.subGroups ? shallow(state.subGroups) : null;
    if (nextSubs) delete nextSubs[gid];
    commit(function () {
      state.groups = nextGroups; applyItems(nextItems);
      state.order = nextOrder; state.subGroups = nextSubs;
      if (state.viewTab === gid) { state.viewTab = ''; state.viewSub = ''; }
    }, t('edit.grpDeleted'));
  }

  /* ---- 看板标题：items.titleZh/titleEn 本来就是服务端字段，只是以前没有入口 ---- */
  function renameItem(no, zh, en) {
    zh = String(zh || '').trim(); en = String(en || '').trim();
    if (!zh && !en) { toast(t('edit.needTitle')); return; }
    commit(function () {
      applyItems(patchItem(no, function (it) {
        var c = {}; Object.keys(it).forEach(function (k) { c[k] = it[k]; });
        c.titleZh = zh; c.titleEn = en;
        return c;
      }));
    }, t('edit.titleOk'));
  }


  /* ------------------------------------------------ 编辑态：拖拽 / 浮层 -- */
  /* 拖拽只有两种落点，语义互不重叠：
       卡片 → 卡片   = 同一分组内改顺序（order[gid]）
       卡片 → 子分组 = 改二级归属（item.subOf[gid]）
     刻意**不支持**「卡片 → 另一个页签」来改分组归属：那与浮层里的勾选是同一件事，
     两处入口只会让人猜哪处才是真的（MsPortal 也是同一个判断：跨区块拖一律不落）。 */
  var dragEl = null, dragNo = null, dragGid = '', hotEl = null, hotCls = '', noClickAt = 0;
  function hotReset() { if (hotEl) hotEl.classList.remove(hotCls); hotEl = null; hotCls = ''; }
  function hotSet(el, cls) {
    if (hotEl === el && hotCls === cls) return;
    hotReset(); hotEl = el; hotCls = cls; el.classList.add(cls);
  }
  function dragReset() {
    if (dragEl) dragEl.classList.remove('is-drag');
    hotReset();
    dragEl = null; dragNo = null; dragGid = '';
    noClickAt = Date.now();
  }
  function cardOf(e) { return e.target && e.target.closest ? e.target.closest('a.card.is-ed') : null; }
  function subOf(e) { return e.target && e.target.closest ? e.target.closest('.subv[data-drop-sub]') : null; }
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
      var c = cardOf(e); if (!c) return;
      dragNo = parseInt(c.getAttribute('data-no'), 10);
      dragGid = c.getAttribute('data-gid') || '';
      if (isNaN(dragNo)) return;
      dragEl = c; c.classList.add('is-drag');
      try {
        e.dataTransfer.setData('text/plain', String(dragNo));
        e.dataTransfer.effectAllowed = 'move';
      } catch (err) { /* 个别环境不允许设 dataTransfer，不影响排序本身 */ }
    });
    document.addEventListener('dragover', function (e) {
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
    document.addEventListener('click', function (e) {
      if (Date.now() - noClickAt > 250) return;
      var c = e.target.closest && e.target.closest('a.card');
      if (c) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    /* 编辑模式开关（只有 editable 的会话才看得到这颗按钮） */
    $('#editBtn').addEventListener('click', function () { setEditing(!state.editing); });
    $('#editBar').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="edit-leave"]')) setEditing(false);
    });
    $('#views').addEventListener('click', onEditClick);
    $('#l0').addEventListener('click', onEditClick);
    $('#views').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      var i = e.target.closest && e.target.closest('.sub-add');
      if (i) { i.querySelector('[data-act="sub-add"]').click(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (state.popForm) closeForm();
      else if (state.grpFor !== null) closeGrp();
    });
    document.addEventListener('mousedown', function (e) {
      if (!e.target.closest) return;
      if (state.popForm && !e.target.closest('#editPop') && !e.target.closest('[data-act="grp-edit"],[data-act="grp-add"],[data-act="title"]')) closeForm();
      if (state.grpFor !== null && !e.target.closest('#grpPop') && !e.target.closest('[data-act="grp"]')) closeGrp();
    });
  }
  function onEditClick(e) {
    var b = e.target.closest ? e.target.closest('[data-act]') : null;
    if (!b) return;
    var act = b.getAttribute('data-act'), gid = b.getAttribute('data-gid') || '';
    var sid = b.getAttribute('data-subx') || '';
    if (act === 'grp') { e.preventDefault(); e.stopPropagation(); openGrp(b); return; }
    if (!canEdit()) return;
    var row, zh, en;
    if (act === 'grp-edit') { openForm('grp', gid, b); }
    else if (act === 'grp-add') { openForm('grpadd', '', b); }
    else if (act === 'title') { e.preventDefault(); e.stopPropagation(); openForm('title', b.getAttribute('data-no'), b); }
    else if (act === 'rst-order') { resetOrder(gid); }
    else if (act === 'sub-re') { state.subEdit = sid; renderViews(); }
    else if (act === 'sub-no') { state.subEdit = ''; renderViews(); }
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
    var out = T0.concat(T1, T2), seen = {};
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
        return '<label class="gp-i"><input type="checkbox" data-g="' + esc(g) + '"' +
          (cur.indexOf(g) !== -1 ? ' checked' : '') + '><span>' + esc(gName(g)) + '</span></label>';
      }).join('') + '</div>';
    placePop(pop, btn);
    state.grpFor = no;
    var first = pop.querySelector('input'); if (first) first.focus();
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
    var pop = $('#grpPop'); if (pop) { pop.hidden = true; pop.innerHTML = ''; }
  }
  function bindGrpPop() {
    var pop = $('#grpPop');
    pop.addEventListener('change', function (e) {
      var cb = e.target.closest ? e.target.closest('input[data-g]') : null;
      if (!cb || state.grpFor === null) return;
      var g = cb.getAttribute('data-g');
      var it = itemsAll().filter(function (x) { return x.no === state.grpFor; })[0];
      if (!it) return;
      var next = groupsOf(it).slice();
      var i = next.indexOf(g);
      if (cb.checked && i === -1) next.push(g);
      if (!cb.checked && i !== -1) next.splice(i, 1);
      if (!next.length) { toast(t('edit.needGroup')); renderGroupsPop(); return; }   /* 一张都不勾 = 看板从所有分组消失 */
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

  /* ---- 第二颗浮层：改名类表单（一级分组改名 / 新增分组 / 看板改标题）----
     三者都是「两三个输入框 + 保存」，共用一套渲染与定位，省掉三套近似代码。
     仍然不是 modal：改的时候要看见被改的东西长什么样，遮罩会把上下文全挡住。 */
  var FORMS = {
    grp: { fields: ['zh', 'en', 'subZh', 'subEn'], tip: 'edit.grpEditTip', ok: 'edit.formSave' },
    grpadd: { fields: ['zh', 'en'], tip: 'edit.grpAddTip', ok: 'edit.formAdd' },
    title: { fields: ['zh', 'en'], tip: 'edit.titleTip', ok: 'edit.formSave' }
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
      vals = { zh: it.titleZh || '', en: it.titleEn || '' };
    }
    var hd = kind === 'grp' ? gName(id) : kind === 'title' ? ('#' + id + ' ' + (vals.zh || vals.en)) : t('edit.grpAdd');
    pop.hidden = false;
    pop.innerHTML = '<div class="gp-hd"><b>' + esc(hd) + '</b><span>' + esc(t(f.tip)) + '</span></div>' +
      f.fields.map(function (k) {
        return '<label class="gf"><span>' + esc(t('edit.f.' + k)) + '</span>' +
          '<input type="text" class="gf-i" data-f="' + k + '" maxlength="' + (/^sub/.test(k) ? 200 : 64) +
          '" value="' + esc(vals[k] || '') + '" placeholder="' + esc(t('edit.fph.' + k)) + '"></label>';
      }).join('') +
      '<div class="gf-b"><button type="button" class="gb gf-ok" data-act="form-ok"><i class="ph ph-check" aria-hidden="true"></i>' + esc(t(f.ok)) + '</button>' +
      (kind === 'grp' && !isBuiltinGroup(id)
        ? '<button type="button" class="gb gf-del" data-act="form-del"><i class="ph ph-trash" aria-hidden="true"></i>' + esc(t('edit.grpDel')) + '</button>' : '') +
      '</div>';
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
    closeForm();                                    /* 先收浮层再提交：commit 会重绘，留着会看见「保存完了框还在」 */
    if (kind === 'grp') renameGroup(id, v);
    else if (kind === 'grpadd') addGroup(v.zh, v.en);
    else renameItem(id, v.zh, v.en);
  }
  function bindFormPop() {
    var pop = $('#editPop'); if (!pop) return;
    pop.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!b) return;
      var act = b.getAttribute('data-act');
      if (act === 'form-ok') { submitForm(); return; }
      if (act === 'form-del') { var id = state.popForm && state.popForm.id; closeForm(); if (id) delGroup(id); return; }
    });
    pop.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || !e.target.closest('input')) return;
      e.preventDefault(); submitForm();
    });
  }

  /* 编辑开关：只认服务端 GET 回的 editable。默认永远关 ——
     这是一支会改**全站共享目录**的笔，不该在用户打开页面时就已经握着。
     `?edit=1` 深链可以自动进入（与 MsPortal 同一入口），但同样要 editable 为真。 */
  function setEditing(on) {
    state.editing = !!on && !!state.catalogEditable;
    state.subEdit = ''; closeGrp(); closeForm();
    root.classList.toggle('is-edit', state.editing);
    syncEditBtn(); renderCatalog();
  }
  function syncEditBtn() {
    var b = $('#editBtn'); if (!b) return;
    b.hidden = !state.catalogEditable;
    b.classList.toggle('on', !!state.editing);
    b.setAttribute('aria-pressed', state.editing ? 'true' : 'false');
    var ico = b.querySelector('i'), lab = b.querySelector('span');
    if (ico) ico.className = 'ph ' + (state.editing ? 'ph-x-circle' : 'ph-pencil-simple');
    if (lab) lab.textContent = t(state.editing ? 'mast.editOn' : 'mast.edit');
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
        esc(t('rail.all')) + '<small>' + all.length + '</small></button>' +
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
        esc(t('rail.all')) + '<small>' + all.length + '</small></button>' +
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


  /* L1 主视图改成页签：一次只展开一个分组。四个面板全叠着时，光 BO View 的 16 张卡
     就能把页面拖到三千多 px；页签条沿用顶部筛选 chip 的胶囊样式，但语义是 tab。
     空分组不进页签（没有可看内容的页签只是噪声），全空才出「无匹配」占位。
     BO 这类配了子分组的分组，面板里再叠一行轻量子页签把 16 张卡切小 ——
     默认仍是「全部」，子页签只是定位器，不拿它藏内容。 */
  function renderViews() {
    var box = $('#views');
    var tabs = tabGids().map(function (gid) { return { id: gid, label: gName(gid), list: filtered(gid) }; });
    var others = allowed().filter(function (it) {
      return !placedGids().some(function (g) { return inGroup(it, g); }) &&
        (state.group === 'all' || inGroup(it, state.group)) && match(it, tokens()) &&
        (state.status === 'all' || it.status === state.status);
    });
    if (others.length) tabs.push({ id: OTHER, label: state.lang === 'en' ? 'Other dashboards' : '其他看板', list: others });
    /* 空分组不进页签（没有可看内容的页签只是噪声）—— 但编辑态要留住**自建**的空分组：
       「新增分组」当下这张卡里还没有任何看板，一起滤掉就等于点了按钮什么都没发生。
       内置分组不豁免：它们的空只代表「当前筛选没有命中」。 */
    tabs = tabs.filter(function (x) {
      return x.list.length || (state.editing && x.id !== OTHER && !isBuiltinGroup(x.id));
    });
    if (!tabs.length) {
      box.innerHTML = '<div class="panel empty"><b>' + esc(t('v.emptyFilter')) + '</b> — ' + esc(t('v.adjust')) + '</div>';
      return;
    }
    var cur = tabs.some(function (x) { return x.id === state.viewTab; }) ? state.viewTab : tabs[0].id;
    state.viewTab = cur; ss('olbr.viewtab', cur);
    var act = tabs.filter(function (x) { return x.id === cur; })[0];
    /* 「其他看板」不是数据里真实存在的分组名，往下传会拼出 gid=__other 的死链接，
       传空串让 vlink 回退到条目自己的主分组。 */
    var gid = cur === OTHER ? '' : cur;
    var list = act.list, subRow = '';
    if (gid) {
      var sub = (canEdit() ? subManageHtml : subLocatorHtml)(gid, act.list, list);
      subRow = sub.html; list = sub.list;
    }
    if (!subRow) state.viewSub = '';
    var head = cur === OTHER
      ? '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(act.label) + '</span></span>' +
        '<span class="cnt">' + list.length + '</span></div>'
      : panelHead(cur, '', list.length);
    box.innerHTML =
      '<div class="view-1"><div class="tabs-v" role="tablist">' + tabs.map(function (x) {
        return '<button type="button" class="tabv" role="tab" data-view="' + esc(x.id) +
          '" aria-selected="' + (x.id === cur ? 'true' : 'false') + '">' + esc(x.label) +
          '<small>' + x.list.length + '</small></button>';
      }).join('') + '</div>' +
      '<section class="panel" data-tier="1" data-gid="' + esc(gid) + '" aria-label="' + esc(act.label) + '">' +
      head + subRow + '<div class="cards">' + (list.length
        ? list.map(function (it) { return itemCard(it, gid); }).join('')
        : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') +
      '</div></section></div>';
  }

  /* 辅助区分组标题：默认只露 AUX_ROWS 行，多出来的靠「展开 / 收起」按钮。
     收缩用 CSS 隐藏第 3 条起的 li（而不是 max-height），避免半行被裁一半。 */
  function auxHead(key, label, n) {
    var open = !!state.auxOpen[key], cut = n > AUX_ROWS;
    return '<h3 class="aux-h"><span class="aux-n">' + esc(label) + '</span><span class="cnt">' + n + '</span>' +
      (cut ? '<button type="button" class="aux-x" data-act="aux-toggle" data-key="' + esc(key) +
        '" aria-expanded="' + (open ? 'true' : 'false') + '"><i class="ph ph-' + (open ? 'caret-up' : 'caret-down') +
        '" aria-hidden="true"></i><span>' + esc(open ? t('aux.less') : tf('aux.more', { n: n - AUX_ROWS })) +
        '</span></button>' : '') + '</h3>';
  }
  function auxRow(it, gid) {
    return '<li><a class="lrow" href="' + esc(vlink(it, gid)) + '" target="_blank" rel="noopener noreferrer">' +
      ic(it.icon) + '<span>' + hl(titleOf(it)) + '</span>' +
      (it.status === 'beta' ? '<em>' + esc(stOf(it)) + '</em>' : '') +
      '<i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>';
  }
  function renderAux() {
    var box = $('#aux'), html = '';
    T2.forEach(function (gid) {
      var list = filtered(gid);
      if (!list.length && filtering()) return;
      html += '<div class="aux-g" data-key="' + esc(gid) + '" data-open="' + (state.auxOpen[gid] ? '1' : '0') + '">' +
        auxHead(gid, t(AUX_TITLES[gid] || gid), list.length) + '<ul>' +
        (list.length ? list.map(function (it) { return auxRow(it, gid); }).join('')
          : '<li><span class="lrow">' + esc(t('v.empty')) + '</span></li>') + '</ul></div>';
    });
    var tools = '<li><a class="lrow" href="/MsPortal/">' + ic('wrench') + '<span>' + esc(t('aux.ms')) + '</span><i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>' +
      '<li><a class="lrow" href="/uniplam/">' + ic('globe') + '<span>' + esc(t('aux.uni')) + '</span><i class="ph ph-arrow-right go" aria-hidden="true"></i></a></li>';
    html += '<div class="aux-g" data-key="_tools" data-open="1">' + auxHead('_tools', t('aux.tools'), 2) + '<ul>' + tools + '</ul></div>';
    box.innerHTML = html;
  }

  function renderEsc() {
    var box = $('#esc'), E = D.escalation || {}, rows = E.rows || [], lv = E.levels || [];
    if (!rows.length) { box.hidden = true; return; }
    var cnt = {}; rows.forEach(function (r) { cnt[r.level] = (cnt[r.level] || 0) + 1; });
    var html = '<div class="esc-bar"><span class="esc-t">' + esc(t('esc.title')) + '</span>' +
      '<span class="esc-s">' + esc(tf('esc.count', { n: rows.length, lv: lv.length })) + ' · ' + esc(t('esc.sub')) + '</span>' +
      '<span class="esc-lv">' + lv.map(function (l) {
        return '<button type="button" class="lvchip" data-lv="' + esc(l.id) + '" data-now="' + (l.id === state.escLv ? '1' : '0') + '">' +
          esc(l.id.replace('LEVEL', 'L')) + ' <b>' + (cnt[l.id] || 0) + '</b></button>';
      }).join('') +
      '<button type="button" class="gb" data-act="esc-toggle"><i class="ph ph-' + (state.escOpen ? 'caret-up' : 'caret-down') + '"></i>' +
      esc(state.escOpen ? t('esc.collapse') : tf('esc.expand', { n: rows.length })) + '</button></span></div>';
    if (state.escOpen) {
      var show = rows.filter(function (r) { return !state.escLv || r.level === state.escLv; });
      html += '<div class="esc-body"><div class="esc-scroll"><table class="grid"><thead><tr>' +
        '<th>' + esc(t('esc.lv')) + '</th><th>' + esc(t('esc.pos')) + '</th><th>' + esc(t('esc.name')) + '</th>' +
        '<th class="num">Orange</th><th class="num">LONESTAR</th><th>' + esc(t('esc.mail')) + '</th></tr></thead><tbody>' +
        show.map(function (r) {
          return '<tr><td class="lv">' + esc(String(r.level || '').replace('LEVEL', 'L')) + '</td>' +
            '<td>' + esc(r.position || '—') + '</td><td>' + esc(r.name || '—') + '</td>' +
            '<td class="num">' + esc(r.orange || '—') + '</td><td class="num">' + esc(r.lonestar || '—') + '</td>' +
            '<td>' + (r.email ? '<a href="mailto:' + esc(r.email) + '">' + esc(r.email) + '</a>' : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="esc-note">' + esc(t('esc.src')) + ' · ' +
        esc((lv.filter(function (l) { return l.id === state.escLv; })[0] || [])[state.lang === 'en' ? 'en' : 'zh'] || '') +
        ' <button type="button" class="gb" data-act="esc-copy" style="margin-left:8px"><i class="ph ph-copy"></i>' + esc(t('esc.copy')) + '</button></p></div>';
    }
    box.innerHTML = html;
  }

  function render() { renderRail(); renderBand(); renderL0(); renderEsc(); renderViews(); renderAux(); applyI18n(); }

  /* 目录保存后的重绘：只画「看得懂目录改动」的那几块，且**不重新加载地图**。
     ⚠️ 不能图省事调 render()：MsPortal 当年就是这么把 4 个地图 iframe 全重建了一遍，
     地图重新加载几十秒，验证脚本从 18/18 掉到 11/18（症状是「no leaflet」）。
     本页面只有一个地图，但同样的坑：改一次排序就闪一下拓扑图，谁都会以为保存把页面弄坏了。 */
  function renderCatalog() { renderL0(true); renderViews(); renderRail(); renderAux(); }

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
  function renderWho() {
    var b = $('#whoBadge'), o = $('#logoutBtn'), u = state.user;
    var n = u && (u.username || u.id || u.name);
    if (b) { b.hidden = !n; b.textContent = n || ''; }
    if (o) o.hidden = !state.authOk;
  }
  function renderGate() {
    var box = $('#gate');
    if (state.authOk) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<div class="gate"><div class="gate-c"><h2>' + esc(t('gate.title')) + '</h2>' +
      '<p>' + esc(t('gate.sub')) + '</p><form id="lf">' +
      '<label class="fld"><span>' + esc(t('gate.user')) + '</span><input id="lu" autocomplete="username" required></label>' +
      '<label class="fld"><span>' + esc(t('gate.pass')) + '</span><input id="lp" type="password" autocomplete="current-password" required></label>' +
      '<div class="gate-err" id="le" hidden></div>' +
      '<div class="gate-ft"><a class="btn" href="/MsPortal/">' + esc(t('mast.admin')) + '</a>' +
      '<button class="btn primary" type="submit" id="lgo">' + esc(t('gate.go')) + '</button></div></form></div></div>';
    mainLocked(true);
  }
  function mainLocked(on) {
    ['#band', '#l0', '#esc', '#views', '#aux'].forEach(function (s) { var e = $(s); if (e) e.hidden = on; });
    var r = $('#rail'); if (r) r.style.display = on ? 'none' : '';
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
        return fetch('/api/auth/portal-login', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ token: d.token })
        }).catch(function () {});
      });
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
  function loadQc() {
    api('/api/portal-qc/summary').then(function (d) {
      state.qc = { loading: false, err: '', at: d.generated_at ? new Date(d.generated_at).getTime() : Date.now(), m: d.metrics || {} };
      renderBand();
    }).catch(function (e) {
      state.qc = { loading: false, err: (e && e.message) || String(e), at: 0, m: {} };
      renderBand();
    });
  }
  function openDrill(id) {
    var def = (D.qc || []).filter(function (x) { return x.id === id; })[0];
    if (!def) return;
    state.drill = { metric: id, title: state.lang === 'en' ? def.en : def.zh, q: '', page: 1, size: 25, rows: [], columns: [], total: 0, loading: true, err: '' };
    var d = $('#drawer');
    d.hidden = false; $('#scrim').hidden = false;
    /* 用一次强制重排而不是 requestAnimationFrame 来做「unhide → 加类」的帧间隔：
       页面在后台时 rAF 根本不会回调，抽屉就永远停在关上的位置。 */
    void d.offsetWidth;
    d.classList.add('open');
    $('#drQ').value = '';
    fetchDrill();
  }
  function closeDrill() {
    $('.drawer').classList.remove('open');
    state.drill.metric = '';
    window.setTimeout(function () { $('#drawer').hidden = true; $('#scrim').hidden = true; }, 220);
  }
  var drillSeq = 0;
  function fetchDrill() {
    var d = state.drill; if (!d.metric) return;
    var seq = ++drillSeq;
    d.loading = true; d.err = ''; renderDrill();
    api('/api/portal-qc/detail?metric=' + encodeURIComponent(d.metric) + '&page=' + d.page + '&size=' + d.size +
      (d.q ? '&q=' + encodeURIComponent(d.q) : ''))
      .then(function (r) {
        if (seq !== drillSeq) return;
        d.loading = false; d.total = r.total || 0; d.rows = r.rows || []; d.columns = r.columns || [];
        renderDrill();
      })
      .catch(function (e) { if (seq !== drillSeq) return; d.loading = false; d.err = (e && e.message) || String(e); renderDrill(); });
  }
  function cell(k, v) {
    if (v == null || v === '') return '—';
    if (/^(raised|closed|update|created)/i.test(k) && typeof v === 'number') return esc(fmtTime(v).slice(5));
    if (typeof v === 'number') return esc(v % 1 ? v.toFixed(1) : v.toLocaleString('en-US'));
    return esc(v);
  }
  function renderDrill() {
    var d = state.drill, box = $('#drBody');
    $('#drTitle').textContent = d.title || t('dr.title');
    $('#drSub').textContent = t('qc.sub');
    $('#drCount').textContent = d.loading ? '…' : tf('dr.rows', { n: d.total });
    $('#drPage').textContent = tf('dr.page', { p: d.page, q: Math.max(1, Math.ceil(d.total / d.size)) });
    $('#drPrev').disabled = d.page <= 1; $('#drNext').disabled = d.page * d.size >= d.total;
    if (d.loading) { box.innerHTML = '<div class="dr-empty">' + esc(t('dr.load')) + '</div>'; return; }
    if (d.err) { box.innerHTML = '<div class="dr-empty" style="color:var(--crit)">' + esc(tf('dr.err', { e: d.err })) + '</div>'; return; }
    if (!d.rows.length) { box.innerHTML = '<div class="dr-empty">' + esc(t('dr.empty')) + '</div>'; return; }
    box.innerHTML = '<table class="grid"><thead><tr>' + d.columns.map(function (c) {
      return '<th' + (typeof d.rows[0][c.key] === 'number' ? ' class="num"' : '') + '>' + esc(c.label || c.key) + '</th>';
    }).join('') + '</tr></thead><tbody>' + d.rows.map(function (r) {
      return '<tr>' + d.columns.map(function (c) {
        return '<td' + (typeof r[c.key] === 'number' ? ' class="num"' : '') + '>' + cell(c.key, r[c.key]) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</tbody></table>';
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
    });
    lc.style.setProperty('height', '100%', 'important');
    lc.style.setProperty('min-height', '0', 'important');
    lc.style.setProperty('width', '100%', 'important');
    try { doc.defaultView.dispatchEvent(new Event('resize')); } catch (e) { /* ignore */ }
    return true;
  }
  function invalidateLeaflet(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var map = null;
    ['_leaflet_map', '__leaflet_map', '_map', 'map'].forEach(function (k) {
      if (!map && lc[k] && typeof lc[k].invalidateSize === 'function') map = lc[k];
    });
    if (!map) {
      try {
        var fk = Object.keys(lc).filter(function (k) { return k.indexOf('__reactFiber') === 0; })[0];
        if (fk) {
          var seen = new Set(), stack = [lc[fk]], guard = 0;
          while (stack.length && guard++ < 4000) {
            var n = stack.pop();
            if (!n || seen.has(n)) continue;
            seen.add(n);
            if (n.stateNode && typeof n.stateNode.invalidateSize === 'function') { map = n.stateNode; break; }
            var mp = n.memoizedProps || n.pendingProps;
            if (mp) {
              for (var key in mp) {
                var v = mp[key];
                if (v && typeof v === 'object' && typeof v.invalidateSize === 'function') { map = v; break; }
              }
              if (map) break;
            }
            if (n.child) stack.push(n.child);
            if (n.sibling) stack.push(n.sibling);
          }
        }
      } catch (e) { /* ignore */ }
    }
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
  /* 只有暴露了 fitAllSites 的内层页（当前是 mw_real_time.html）需要重新取景：
     fitBounds 跑在容器还矮的时刻，zoom 会低一级。容器高度每落定一次就重跑一次，
     直到约 12s 的观察窗口结束 —— 中途存在「前 strip 的假稳态」，只做一次会被骗。 */
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
  function stripFrame(f, depth) {
    depth = depth || 0;
    try {
      var d = f.contentDocument;
      if (!d || !d.head) return;
      var s = d.getElementById('olbrStrip');
      if (!s) { s = d.createElement('style'); s.id = 'olbrStrip'; d.head.appendChild(s); }
      if (s.textContent !== MAP_STRIP_CSS) s.textContent = MAP_STRIP_CSS;

      if (d.querySelector('.leaflet-container')) {
        if (depth > 0) keepOnlyMap(d);
        invalidateLeaflet(d);
        refitLeaflet(d);
        setTimeout(function () { invalidateLeaflet(d); }, 400);
        setTimeout(function () { invalidateLeaflet(d); }, 1200);
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
      b.setAttribute('aria-pressed', b.getAttribute('data-lang') === state.lang ? 'true' : 'false');
    });
    $('#themeBtn').innerHTML = '<i class="ph ph-' + (state.theme === 'dark' ? 'sun' : 'moon') + '" aria-hidden="true"></i>';
    var local = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    $('#envLabel').textContent = local ? t('env.local') : t('env.lr');
    var src = D.meta || {};
    $('#footSrc').textContent = tf('foot.src', { n: (D.stats && D.stats.total) || ITEMS.length, d: src.generated || '' });
    /* 编辑按钮的文案 / 提示是动态写的（语言一换要跟着换），所以也归这里出口 */
    syncEditBtn();
  }
  function setTheme(v) {
    state.theme = v; root.classList.toggle('dark', v === 'dark'); ss('olbr.theme', v);
    applyI18n();
    var f = $('#mapFrame'); if (f) { f.src = curMap().src; }
  }
  function setLang(v) { state.lang = v; ss('olbr.lang', v); render(); }
  function toast(msg) {
    var el = $('#toast'); el.textContent = msg; el.hidden = false;
    el.className = 'toast';
    window.setTimeout(function () { el.hidden = true; }, 2200);
  }
  function tick() { $('#clock').textContent = fmtTime(Date.now()); }

  /* --------------------------------------------------------- env badge -- */
  /* 只探活，文案由 applyI18n 写（语言切换才会跟着变）。 */
  function envBadge() {
    api('/api/portal-qc/summary').then(function () { $('#envBadge').classList.remove('bad'); })
      .catch(function () { $('#envBadge').classList.add('bad'); });
  }

  /* ------------------------------------------------------------ events -- */
  function bind() {
    var qEl = $('#q'), deb;
    qEl.addEventListener('input', function () {
      window.clearTimeout(deb);
      deb = window.setTimeout(function () { state.q = qEl.value || ''; render(); }, 120);
    });
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); qEl.focus(); qEl.select(); }
      if (e.key === 'Escape') { if (state.drill.metric) closeDrill(); else if (qEl === document.activeElement) { qEl.value = ''; state.q = ''; render(); } }
    });
    $('#chips').addEventListener('click', function (e) {
      var c = e.target.closest('.chip'); if (!c) return;
      state.group = c.getAttribute('data-gid');
      /* 点分组 chip 时把主视图页签一起切过去：不然筛选条件变了、下面展示的却还是上一个分组，
         看起来像是筛选没生效。'all' 和辅助分组不动页签。 */
      if (T1.indexOf(state.group) !== -1) state.viewTab = state.group;
      render();
    });
    /* 直接绑在按钮上：index.html 里带 data-status 的是 .seg-b，容器 .seg 没有这个属性，
       原先写成 $$('.seg[data-status]') → 一个都选不到，状态筛选整条是死的。 */
    $$('.seg-b[data-status]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.status = b.getAttribute('data-status'); render();
      });
    });
    $('#clearBtn').addEventListener('click', function () {
      state.q = ''; state.group = 'all'; state.status = 'all'; qEl.value = ''; render();
    });
    $('#themeBtn').addEventListener('click', function () { setTheme(state.theme === 'dark' ? 'light' : 'dark'); });
    $$('.mast .seg-b[data-lang]').forEach(function (b) {
      b.addEventListener('click', function () { setLang(b.getAttribute('data-lang')); });
    });
    $('#logoutBtn').addEventListener('click', logout);

    $('#band').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="qc-retry"]')) { state.qc.loading = true; renderBand(); loadQc(); return; }
      var m = e.target.closest('.metric'); if (m && m.getAttribute('data-qc')) openDrill(m.getAttribute('data-qc'));
    });
    $('#l0').addEventListener('click', function (e) {
      var tb = e.target.closest('[data-map]');
      if (tb) {
        state.mapTab = tb.getAttribute('data-map'); ss('olbr.maptab', state.mapTab); renderL0(); return;
      }
      if (e.target.closest('[data-act="map-reload"]')) { var f = $('#mapFrame'); if (f) f.src = curMap().src; }
    });
    $('#views').addEventListener('click', function (e) {
      /* 编辑态的小按钮（改名 / 删除 / 新增 / 分组）交给 onEditClick 统一处理，
         这里先让路：不然点「改名」会连带把子页签切一次、多渲染一遍。 */
      if (e.target.closest('[data-act]')) return;
      var sb = e.target.closest('[data-sub]');
      if (sb) { state.viewSub = sb.getAttribute('data-sub'); renderViews(); return; }
      var tb = e.target.closest('[data-view]'); if (!tb) return;
      /* 换分组时二级子页签归零：subOf 是按分组分别记的，跨分组沿用会挑出空桶 */
      state.viewTab = tb.getAttribute('data-view');
      state.viewSub = '';
      ss('olbr.viewtab', state.viewTab); renderViews();
    });
    $('#esc').addEventListener('click', function (e) {
      var lv = e.target.closest('[data-lv]');
      if (lv) { state.escLv = lv.getAttribute('data-lv'); if (!state.escOpen) state.escOpen = true; renderEsc(); return; }
      if (e.target.closest('[data-act="esc-toggle"]')) { state.escOpen = !state.escOpen; renderEsc(); return; }
      if (e.target.closest('[data-act="esc-copy"]')) { copyEsc(); return; }
    });
    $('#aux').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act="aux-toggle"]'); if (!b) return;
      var k = b.getAttribute('data-key');
      state.auxOpen[k] = !state.auxOpen[k]; renderAux();
    });
    $('#drClose').addEventListener('click', closeDrill);
    $('#scrim').addEventListener('click', closeDrill);
    $('#drReload').addEventListener('click', fetchDrill);
    $('#drPrev').addEventListener('click', function () { if (state.drill.page > 1) { state.drill.page--; fetchDrill(); } });
    $('#drNext').addEventListener('click', function () { state.drill.page++; fetchDrill(); });
    var dq = $('#drQ'), dd;
    dq.addEventListener('input', function () {
      window.clearTimeout(dd);
      dd = window.setTimeout(function () { state.drill.q = dq.value || ''; state.drill.page = 1; fetchDrill(); }, 220);
    });
    $('#gate').addEventListener('submit', function (e) {
      if (e.target.id !== 'lf') return;
      e.preventDefault();
      var err = $('#le'), go = $('#lgo'); go.disabled = true; go.textContent = t('gate.busy'); err.hidden = true;
      login($('#lu').value.trim(), $('#lp').value).then(function () {
        renderGate(); mainLocked(false); start();
      }).catch(function (x) {
        err.textContent = t('gate.' + (x.code || 'net')); err.hidden = false;
        go.disabled = false; go.textContent = t('gate.go');
      });
    });
    bindEdit();
    bindGrpPop();
    bindFormPop();
  }
  function copyEsc() {
    var rows = (D.escalation || {}).rows || [];
    var txt = rows.filter(function (r) { return r.level === state.escLv; })
      .map(function (r) { return [r.position, r.name, r.orange, r.lonestar, r.email].filter(Boolean).join('\t'); }).join('\n');
    var done = function () { toast(t('esc.copied')); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, done);
    else done();
  }

  /* -------------------------------------------------------------- boot -- */
  function start() {
    loadQc();
    window.setInterval(loadQc, 300000);           /* 与「告警每 5 分钟」的口径对齐 */
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
        setCatalog(migrateSubOf(c.items));
        state.groups = Array.isArray(c.groups) && c.groups.length ? normalizeGroupList(c.groups) : state.groups;
      }
      render();
      /* `?edit=1` 深链（与 MsPortal 同一入口）：仍要 editable 为真，setEditing 里已兜 */
      if (/[?&]edit=1(&|$)/.test(location.search)) setEditing(true);
    }).catch(function () { /* 服务端没有目录就用内置 data.js，首屏已经渲染过了（编辑按钮保持隐藏） */ });
  }

  function boot() {
    applyI18n();
    mainLocked(true);
    bind();
    tick(); window.setInterval(tick, 1000);
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
