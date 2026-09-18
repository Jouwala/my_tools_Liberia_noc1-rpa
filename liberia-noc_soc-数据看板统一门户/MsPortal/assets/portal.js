/* ==========================================================================
   MsPortal — 应用逻辑 (i18n / 深浅主题 / 分组归属编辑 / 渲染)
   --------------------------------------------------------------------------
   · 数据     window.MS_PORTAL_DATA  (assets/data.js)
   · 版式     1:1 对照 ref.html（ZTE OLR MS 布局稿）：
               CXO View → Quality Control → 三列核心区 (3:5:4) → 底部双面板
   · 样式     assets/tailwind.css（由 TMP/build_tailwind.mjs 用 Tailwind v4 编译，零 CDN 依赖）
              改过本文件里的 Tailwind 类名后，必须重跑一次：
                node TMP/build_tailwind.mjs
              否则新类名不会出现在产物里，且页面不报错、只是静默失效。
   · 地图     中间列内嵌 my_app 地图看板（同源 /myapp/），注入 CSS 只保留地图组件
   · 用户改动（分组归属 / 自建分组 / 语言 / 主题）只写入本机 localStorage，
     不会改写服务端 portal-default.json，因此完全不影响 /uniplam/ 门户。
   ========================================================================== */
(function () {
  'use strict';

  var DATA = window.MS_PORTAL_DATA || { items: [], groups: [], qc: [], stats: {} };

  var LS = {
    theme: 'msportal.theme.v1',
    lang: 'msportal.lang.v1',
    assign: 'msportal.assign.v1',
    groups: 'msportal.groups.v1',
    renames: 'msportal.renames.v1',
    filter: 'msportal.filter.v1',
    mapTab: 'msportal.maptab.v1',
    fontStep: 'msportal.fontstep.v1',
    /* 看板目录的本机兜底（2026-09-17 加）。服务端 /api/portal-catalog 不可写时的
       临时落点；服务端有目录时以服务端为准，并清掉这里的副本。 */
    catalog: 'msportal.catalog.v1'
  };

  /* ------------------------------------------------------------- i18n ---- */
  var I18N = {
    zh: {
      'header.live': '生产运行',
      'search.placeholder': '搜索看板名称、描述、责任人、标签…',
      'section.searchPh': '在本区块内搜索看板…',
      'section.hit': '匹配 {n}',
      'section.noHit': '本区块无匹配',
      /* 区块内折叠 / 顶栏控制条折叠（2026-09-17 加） */
      'sec.more': '展开全部',
      'sec.less': '收起',
      'bar.toggle': '搜索与筛选',
      'btn.editGroups': '编辑分组归属',
      'btn.editGroupsOn': '退出编辑',
      'btn.manageGroups': '分组管理',
      'btn.export': '导出 JSON',
      'btn.import': '导入 JSON',
      'btn.reset': '恢复默认',
      'btn.addBoard': '新增看板',
      'btn.boardReset': '恢复出厂目录',
      'btn.aPlus': '放大字号',
      'btn.aMinus': '缩小字号',
      'toast.fontScale': '字号 {p}%（仅本机浏览器）',
      'edit.hint': '编辑模式：卡片右上角的 ✎ / 🗑 可编辑或删除看板，分组标签的 × 可移出该分组；改动保存到服务器，所有人可见。',
      /* ---- 看板新增 / 编辑弹窗（2026-09-17 加） ---- */
      'board.addTitle': '新增看板',
      'board.editTitle': '编辑看板',
      'board.cancel': '取消',
      'board.save': '保存',
      'board.edit': '编辑此看板',
      'board.del': '删除此看板',
      'board.added': '已新增看板',
      'board.saved': '已保存看板',
      'board.deleted': '已删除看板',
      'board.savedServer': '已同步到服务器，所有人可见',
      'board.savedLocal': '仅保存在本机浏览器（服务端不可写）',
      'board.saveFail': '保存失败',
      'board.readonly': '仅可在服务器本机编辑',
      'board.confirmDel': '确定删除看板「{name}」？该改动对所有访问者生效。',
      'board.resetConfirm': '确定恢复出厂目录？将删除服务器上的全局看板目录，所有人回到内置的看板清单。',
      'board.resetDone': '已恢复出厂目录',
      'board.errTitle': '请填写看板标题（中文或英文至少一项）',
      'board.errUrl': '请填写以 http:// 或 https:// 开头的链接',
      'board.errGroups': '请至少选择一个归属分组，否则看板不会出现在任何区块',
      'board.serverNote': '保存后立即写入服务器，所有人打开门户都会看到。',
      'board.localNote': '当前服务端不可写，改动只保存在本机浏览器。',
      'board.fTitleZh': '标题（中文）*',
      'board.fTitleEn': '标题（English）',
      'board.fUrl': '链接 URL *',
      'board.fDescZh': '描述（中文）',
      'board.fDescEn': '描述（English）',
      'board.fPlatform': '平台',
      'board.fStatus': '状态',
      'board.fOwner': '责任人（中文）',
      'board.fOwnerEn': '责任人（English）',
      'board.fDept': '部门（中文）',
      'board.fDeptEn': '部门（English）',
      'board.fFreq': '更新频率',
      'board.fIcon': '图标',
      'board.fClicks': '访问量',
      'board.fTags': '标签（逗号分隔）',
      'board.fGroups': '归属分组 *（可多选）',
      'chip.all': '全部',
      'sec.cxo.title': 'CXO View',
      'sec.cxo.sub': '| 决策战略层统一总控与运营视窗',
      'sec.cxo.tool': '战略大屏直通率:',
      'sec.cxo.link': '完整系统目录',
      'sec.qc.title': 'Quality Control',
      'sec.qc.sub': '| 质量监控核心指标 (Key Performance Indicators)',
      'sec.qc.sla.label': '达标率',
      'sec.qc.sla.tip': '近 {d} 天创建的 TT 中 SLA 判定为 Pass 的占比（分母只含已判定 Pass/Failed 的单，在途未超期的不计入）：{pass} / {total}',
      'sec.count': '个系统',
      'sec.ms.sub': '综合运维管理层',
      'sec.flm.sub': '一线外场维护',
      'sec.sp.sub': '备品备件管理 (Spare Parts)',
      'sec.fo.sub': '前端网络运营中心 (Front Office / NOC)',
      'sec.bo.sub': '后端专家技术支撑 (Back Office)',
      'sec.admin.title': 'System Admin',
      'sec.admin.sub': '系统与运维配置',
      'sec.qa.title': 'Knowledge Q/A',
      'sec.qa.sub': '| 知识库与技术支持 (Operation Manual & Guidance)',
      'sec.qa.link': '知识检索中心',
      'sec.friends.title': 'Friends Links',
      'sec.friends.sub': '| 集团中台与生态协作统一入口',
      'sec.friends.link': '企业导航地图',
      /* ---- 升级机制表格（2026-09-18 加，内容来自 升级机制.xlsx，见 data.js 的 escalation） ---- */
      'esc.title': '升级机制 (Escalation Matrix)',
      'esc.sub': '值班升级联系人 · Orange / LONESTAR 双网号码',
      'esc.count': '{n} 条 · {lv} 级',
      'esc.col.level': '职级',
      'esc.col.position': '岗位',
      'esc.col.name': '姓名',
      'esc.col.orange': 'Orange',
      'esc.col.lonestar': 'LONESTAR',
      'esc.col.email': '邮箱',
      'esc.empty': '升级机制数据未加载',
      'esc.srcNote': '数据源：升级机制.xlsx',
      'esc.pax': '{n} 人',
      'esc.expand': '放大查看',
      'esc.expandTip': '表格在中列放不全（6 列需 796px），点开按全宽查看完整 21 条',
      'esc.modalTitle': '升级机制 (Escalation Matrix)',
      'esc.modalNote': 'LEVEL1 为一线值班热线与专业工程师，逐级上报至 LEVEL4 中方 PD。',
      'esc.close': '关闭',
      'qc.click': '点击查看明细',
      /* 2026-09-17：随大数字改为数据库统计，删掉了 qc.self / qc.bi / qc.linked ——
         那是旧语义的残留（大数字原本=本维度挂了几块看板，故标注「关联看板」并按
         自研/FineBI 拆开计数）。数字换成「未关闭 TT 数」这类业务量后，再接
         「关联看板」就是把业务量标成看板数，属于错误信息，故一并移除。 */
      /* 2026-09-17：QC 六卡改为数据库实时统计（/api/portal-qc/summary），点击下钻明细 */
      'qc.drillSuffix': ' · 明细',
      'qc.search': '搜索…',
      'qc.reload': '刷新',
      'qc.export': '导出 CSV',
      'qc.updated': '更新于',
      'qc.loading': '加载中…',
      'qc.err': '数据库统计不可用',
      'qc.empty': '没有匹配的记录',
      'qc.noCsv': '当前没有可导出的数据',
      'qc.page': '第 {p} / {n} 页',
      'qc.total': '共 {n} 条',
      'qc.sites': '断站站点',
      'qc.overdue': '超期',
      'qc.filterHint': '提示：按维度筛选看板目录的功能在筛选栏的对应标签上，本弹窗只做明细下钻。',
      'qc.sub.alarm': '未清除的断站告警',
      'qc.sub.tt': '未关闭故障工单 (TT)',
      'qc.sub.wo': '未关闭任务工单 (WO)',
      'qc.sub.cr': '未关闭变更单 (CR)',
      'qc.sub.pmt': '未完成的预防性维护 (PMT)',
      'qc.sub.spms': '未关闭出入库单 (SPMS)',
      'status.online': '在线',
      'status.beta': '试运行',
      'tag.new': '新增',
      'open': '打开',
      'views': '访问',
      'empty': '暂无看板，可在「编辑分组归属」中把其他看板移入本组',
      'emptyFilter': '没有匹配的看板，请调整搜索或筛选条件',
      'topo.title': 'Central Liberia Regional Topology',
      'topo.sub': '利比里亚网络拓扑全景',
      'topo.live': '实时',
      'map.tab.gis': 'GIS 地图',
      'map.tab.mw': '微波实时',
      'map.tab.alarm': '实时告警',
      'map.tab.loss': '传输丢包',
      'map.refresh': '刷新',
      'map.open': '新窗口',
      'map.loading': '正在加载地图…',
      'auth.title': '需要登录统一门户',
      'auth.tip': '本页面可直接使用统一门户的同一套账号、密码和权限登录。',
      'auth.login': '本页直接登录',
      'auth.portal': '在统一门户登录',
      'auth.retry': '我已登录，重试',
      'auth.checking': '正在校验登录状态…',
      'auth.directTitle': '登录统一门户',
      'auth.username': '用户名',
      'auth.password': '密码',
      'auth.sameAccount': '使用统一门户同一套账号、密码和权限。',
      'auth.submit': '登录',
      'auth.cancel': '取消',
      'auth.logout': '退出登录',
      'auth.loggingIn': '登录中…',
      'auth.badCredentials': '用户名或密码错误',
      'auth.locked': '登录失败次数过多，请稍后再试',
      'auth.networkError': '登录服务不可用，请检查门户服务',
      'auth.mustChange': '当前账号需要先修改密码，请前往统一门户完成修改。',
      'auth.noMap': '当前账号没有地图权限',
      'map.auth.title': '地图需要登录后查看',
      'map.auth.tip': '地图数据需通过统一门户登录后访问。登录后回到本页即可正常显示。',
      'map.auth.login': '本页直接登录',
      'map.auth.retry': '我已登录，重试',
      'map.auth.checking': '正在校验登录状态…',
      'topo.stat.total': '门户看板总数',
      'topo.stat.online': '在线运行看板',
      'topo.stat.clicks': '累计访问量',
      'modal.title': '分组管理',
      'modal.colZh': '分组名称（中文）',
      'modal.colEn': '分组名称（English）',
      'modal.colCount': '看板数',
      'modal.add': '新增分组',
      'modal.del': '删除',
      'modal.confirmDel': '确认删除该分组？组内看板仍可通过编辑归属改派到其他分组。',
      'modal.note': '分组改名 / 新增会立即生效并保存在本机浏览器；删除分组只影响归属展示，不会删除看板本身。',
      'assign.label': '归属分组',
      'assign.add': '+ 加入分组',
      'assign.only': '至少保留一个分组',
      'toast.reset': '已恢复默认分组归属',
      'toast.exported': '已导出配置 JSON',
      'toast.imported': '已导入配置',
      'toast.importFail': '导入失败：文件格式不正确',
      'toast.groupAdded': '已新增分组',
      'toast.groupRemoved': '已删除分组',
      'footer.copy': '中兴通讯股份有限公司 版权所有',
      'footer.branch': '利比里亚办事处网络运营中心 (OLR MS)',
      'footer.compliance': '安全合规模式运行',
      'footer.source': '分组依据：看板清单 (分组优化）',
      'plat.myapp': '自研 my_app',
      'plat.finebi': 'FineBI 报表',
      'plat.external': '外部系统',
      'platShort.myapp': 'my_app',
      'platShort.finebi': 'FineBI',
      'platShort.external': 'External',
      'sub.wireless': '无线射频、动力与外场排班',
      'sub.core': '核心网 (CS/PS) 及运营月报',
      'sub.ip': 'IP 承载网与工程专家支持',
      'sub.others': '其他系统'
    },
    en: {
      'header.live': 'Production',
      'search.placeholder': 'Search dashboards by name, description, owner or tag…',
      'section.searchPh': 'Filter dashboards in this section…',
      'section.hit': '{n} match',
      'section.noHit': 'No match in this section',
      /* 区块内折叠 / 顶栏控制条折叠（2026-09-17 加） */
      'sec.more': 'Show all',
      'sec.less': 'Collapse',
      'bar.toggle': 'Search & filters',
      'btn.editGroups': 'Edit group assignment',
      'btn.editGroupsOn': 'Exit editing',
      'btn.manageGroups': 'Manage groups',
      'btn.export': 'Export JSON',
      'btn.import': 'Import JSON',
      'btn.reset': 'Reset default',
      'btn.addBoard': 'Add dashboard',
      'btn.boardReset': 'Restore factory catalogue',
      'btn.aPlus': 'Larger text',
      'btn.aMinus': 'Smaller text',
      'toast.fontScale': 'Text size {p}% (this browser only)',
      'edit.hint': 'Edit mode: use the ✎ / 🗑 buttons on a card to edit or delete it, × on a group tag to remove it from that group. Changes are saved to the server and visible to everyone.',
      'board.addTitle': 'Add dashboard',
      'board.editTitle': 'Edit dashboard',
      'board.cancel': 'Cancel',
      'board.save': 'Save',
      'board.edit': 'Edit this dashboard',
      'board.del': 'Delete this dashboard',
      'board.added': 'Dashboard added',
      'board.saved': 'Dashboard saved',
      'board.deleted': 'Dashboard deleted',
      'board.savedServer': 'synced to the server — visible to everyone',
      'board.savedLocal': 'stored in this browser only (server not writable)',
      'board.saveFail': 'Save failed',
      'board.readonly': 'only editable on the server host',
      'board.confirmDel': 'Delete dashboard "{name}"? This affects every visitor.',
      'board.resetConfirm': 'Restore the factory catalogue? The global catalogue on the server will be removed and everyone falls back to the built-in list.',
      'board.resetDone': 'Factory catalogue restored',
      'board.errTitle': 'Enter a title (Chinese or English, at least one)',
      'board.errUrl': 'Enter a link starting with http:// or https://',
      'board.errGroups': 'Pick at least one group — otherwise the dashboard shows up in no section',
      'board.serverNote': 'Saved to the server immediately — everyone opening the portal sees it.',
      'board.localNote': 'Server is not writable right now; changes stay in this browser.',
      'board.fTitleZh': 'Title (Chinese) *',
      'board.fTitleEn': 'Title (English)',
      'board.fUrl': 'Link URL *',
      'board.fDescZh': 'Description (Chinese)',
      'board.fDescEn': 'Description (English)',
      'board.fPlatform': 'Platform',
      'board.fStatus': 'Status',
      'board.fOwner': 'Owner (Chinese)',
      'board.fOwnerEn': 'Owner (English)',
      'board.fDept': 'Department (Chinese)',
      'board.fDeptEn': 'Department (English)',
      'board.fFreq': 'Update frequency',
      'board.fIcon': 'Icon',
      'board.fClicks': 'Views',
      'board.fTags': 'Tags (comma separated)',
      'board.fGroups': 'Groups * (multi-select)',
      'chip.all': 'All',
      'sec.cxo.title': 'CXO View',
      'sec.cxo.sub': '| Executive strategy & operation window',
      'sec.cxo.tool': 'Strategy pass rate:',
      'sec.cxo.link': 'Full catalogue',
      'sec.qc.title': 'Quality Control',
      'sec.qc.sub': '| Key Performance Indicators',
      'sec.qc.sla.label': 'Compliance',
      'sec.qc.sla.tip': 'Share of TTs created in the last {d} days rated Pass on SLA (denominator counts only tickets already judged Pass/Failed; in-flight ones are excluded): {pass} / {total}',
      'sec.count': 'systems',
      'sec.ms.sub': 'Integrated O&M Management',
      'sec.flm.sub': 'Field Level Maintenance',
      'sec.sp.sub': 'Spare Parts Management',
      'sec.fo.sub': 'Front Office / NOC',
      'sec.bo.sub': 'Back Office Expert Support',
      'sec.admin.title': 'System Admin',
      'sec.admin.sub': 'System & O&M Configuration',
      'sec.qa.title': 'Knowledge Q/A',
      'sec.qa.sub': '| Operation Manual & Guidance',
      'sec.qa.link': 'Knowledge centre',
      'sec.friends.title': 'Friends Links',
      'sec.friends.sub': '| Group middle-platform & ecosystem SSO',
      'sec.friends.link': 'Enterprise nav map',
      /* ---- Escalation matrix table (added 2026-09-18; data from 升级机制.xlsx, see data.js) ---- */
      'esc.title': 'Escalation Matrix',
      'esc.sub': 'Duty escalation contacts · Orange / LONESTAR numbers',
      'esc.count': '{n} rows · {lv} levels',
      'esc.col.level': 'Level',
      'esc.col.position': 'Position',
      'esc.col.name': 'Name',
      'esc.col.orange': 'Orange',
      'esc.col.lonestar': 'LONESTAR',
      'esc.col.email': 'Email',
      'esc.empty': 'Escalation data not loaded',
      'esc.srcNote': 'Source: 升级机制.xlsx',
      'esc.pax': '{n} pax',
      'esc.expand': 'Expand',
      'esc.expandTip': 'All 6 columns need 796px; open the full-width view for the complete matrix',
      'esc.modalTitle': 'Escalation Matrix',
      'esc.modalNote': 'LEVEL1 is the duty hotline and discipline engineers; escalates step by step up to LEVEL4 Chinese PD.',
      'esc.close': 'Close',
      'qc.click': 'Click for details',
      'qc.drillSuffix': ' · Details',
      'qc.search': 'Search…',
      'qc.reload': 'Refresh',
      'qc.export': 'Export CSV',
      'qc.updated': 'Updated',
      'qc.loading': 'Loading…',
      'qc.err': 'Database stats unavailable',
      'qc.empty': 'No matching records',
      'qc.noCsv': 'Nothing to export',
      'qc.page': 'Page {p} / {n}',
      'qc.total': '{n} records',
      'qc.sites': 'sites down',
      'qc.overdue': 'overdue',
      'qc.filterHint': 'Note: filtering the catalogue by dimension lives on the filter bar chips; this dialog only drills into details.',
      'qc.sub.alarm': 'Uncleared site-outage alarms',
      'qc.sub.tt': 'Unclosed trouble tickets',
      'qc.sub.wo': 'Unclosed work orders',
      'qc.sub.cr': 'Unclosed change requests',
      'qc.sub.pmt': 'Pending preventive maintenance',
      'qc.sub.spms': 'Unclosed inbound/outbound orders',
      'status.online': 'Online',
      'status.beta': 'Beta',
      'tag.new': 'New',
      'open': 'Open',
      'views': 'views',
      'empty': 'No dashboard here yet — use "Edit group assignment" to move dashboards into this group',
      'emptyFilter': 'No dashboard matches the current search or filter',
      'topo.title': 'Central Liberia Regional Topology',
      'topo.sub': 'Liberia regional network topology',
      'topo.live': 'Live',
      'map.tab.gis': 'GIS Map',
      'map.tab.mw': 'MW Real-Time',
      'map.tab.alarm': 'Realtime Alarm',
      'map.tab.loss': 'Packet Loss',
      'map.refresh': 'Refresh',
      'map.open': 'New window',
      'map.loading': 'Loading map…',
      'auth.title': 'Sign-in required',
      'auth.tip': 'Use the same unified-portal account, password and permissions to sign in directly on this page.',
      'auth.login': 'Sign in here',
      'auth.portal': 'Sign in at portal',
      'auth.retry': 'I have signed in — retry',
      'auth.checking': 'Checking session…',
      'auth.directTitle': 'Unified portal sign-in',
      'auth.username': 'Username',
      'auth.password': 'Password',
      'auth.sameAccount': 'Uses the same unified-portal account, password and permissions.',
      'auth.submit': 'Sign in',
      'auth.cancel': 'Cancel',
      'auth.logout': 'Sign out',
      'auth.loggingIn': 'Signing in…',
      'auth.badCredentials': 'Invalid username or password',
      'auth.locked': 'Too many failed attempts; try again later',
      'auth.networkError': 'The sign-in service is unavailable',
      'auth.mustChange': 'This account must change its password first. Open the unified portal to complete the change.',
      'auth.noMap': 'This account has no map permission',
      'map.auth.title': 'Sign-in required for maps',
      'map.auth.tip': 'Map data is available after signing in via the unified portal. Sign in, then return to this page.',
      'map.auth.login': 'Sign in here',
      'map.auth.retry': 'I have signed in — retry',
      'map.auth.checking': 'Checking session…',
      'topo.stat.total': 'Portal dashboards',
      'topo.stat.online': 'Online dashboards',
      'topo.stat.clicks': 'Total visits',
      'modal.title': 'Manage groups',
      'modal.colZh': 'Group name (中文)',
      'modal.colEn': 'Group name (English)',
      'modal.colCount': 'Dashboards',
      'modal.add': 'Add group',
      'modal.del': 'Delete',
      'modal.confirmDel': 'Delete this group? Its dashboards can still be reassigned afterwards.',
      'modal.note': 'Renaming or adding a group applies immediately and is stored in this browser; deleting a group only affects the display, never the dashboard itself.',
      'assign.label': 'Groups',
      'assign.add': '+ Add to group',
      'assign.only': 'Keep at least one group',
      'toast.reset': 'Group assignment reset to default',
      'toast.exported': 'Configuration exported',
      'toast.imported': 'Configuration imported',
      'toast.importFail': 'Import failed: invalid file',
      'toast.groupAdded': 'Group added',
      'toast.groupRemoved': 'Group deleted',
      'footer.copy': 'ZTE Corporation. All rights reserved',
      'footer.branch': 'Liberia Branch Network Operation Center (OLR MS)',
      'footer.compliance': 'Running in security compliance mode',
      'footer.source': 'Grouping source: 看板清单 (分组优化）',
      'plat.myapp': 'In-house my_app',
      'plat.finebi': 'FineBI Report',
      'plat.external': 'External System',
      'platShort.myapp': 'my_app',
      'platShort.finebi': 'FineBI',
      'platShort.external': 'External',
      'sub.wireless': 'Radio, Power & Field Dispatch',
      'sub.core': 'Core Network (CS/PS) & Monthly Report',
      'sub.ip': 'IP Bearer & Engineering Expert Support',
      'sub.others': 'Other systems'
    }
  };

  /* ------------------------------------------------------------ icons ---- */
  /* Phosphor 图标（assets/icons/phosphor.css），名称为图标类的完整字面量 */
  var PH = {
    'chart-polar': 'ph-chart-polar',
    'gauge': 'ph-gauge',
    'bell': 'ph-bell',
    'map': 'ph-map-trifold',
    'ticket': 'ph-ticket',
    'siren': 'ph-siren',
    'clock': 'ph-clock',
    'chart-line': 'ph-chart-line',
    'link': 'ph-link',
    'cpu': 'ph-cpu',
    'broadcast': 'ph-broadcast',
    'battery': 'ph-battery-charging',
    'package': 'ph-package',
    'wrench': 'ph-wrench',
    'upload': 'ph-cloud-arrow-up',
    'table': 'ph-table',
    'archive': 'ph-archive',
    'chat': 'ph-chat-circle-dots',
    'book': 'ph-book-open-text',
    'gear': 'ph-gear',
    'dashboard': 'ph-squares-four',
    'key': 'ph-lock-key',
    'warning': 'ph-warning',
    'briefcase': 'ph-briefcase',
    'git': 'ph-git-pull-request',
    'user': 'ph-user',
    'eye': 'ph-eye',
    'flame': 'ph-fire',
    'arrow': 'ph-arrow-right',
    'arrow-up-right': 'ph-arrow-up-right',
    'chevron': 'ph-caret-down',
    'chevron-down': 'ph-caret-down',
    'chevron-up': 'ph-caret-up',
    'plus': 'ph-plus',
    'folder': 'ph-folder-open',
    'check-circle': 'ph-check-circle',
    'check': 'ph-check',
    'arrow-up': 'ph-arrow-up',
    'arrows-lr': 'ph-arrows-left-right',
    'warning-circle': 'ph-warning-circle',
    'shield': 'ph-shield-check',
    'refresh': 'ph-arrow-clockwise',
    'external': 'ph-arrow-square-out',
    'search': 'ph-magnifying-glass',
    'map-pin': 'ph-map-pin',
    'circle-check': 'ph-circle-wavy-check',
    'buildings': 'ph-buildings',
    'sun': 'ph-sun',
    'moon': 'ph-moon',
    'edit': 'ph-pencil-simple',
    'trash': 'ph-trash',
    'floppy': 'ph-floppy-disk',
    'expand': 'ph-arrows-out'
  };

  function ico(name, cls) {
    return '<i class="ph ' + (PH[name] || PH.dashboard) + (cls ? ' ' + cls : '') + '" aria-hidden="true"></i>';
  }

  /* ------------------------------------------------------- local storage -- */
  function readLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function writeLS(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  function readJSON(k, d) {
    try { var raw = localStorage.getItem(k); return raw ? JSON.parse(raw) : d; } catch (e) { return d; }
  }
  function writeJSON(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } }

  /* ---------------------------------------------------------- deep links -- */
  var QS = (function () { try { return new URLSearchParams(location.search); } catch (e) { return null; } })();
  function qp(name) { return QS ? QS.get(name) : null; }

  /* ------------------------------------------------------------- state --- */
  var state = {
    lang: readLS(LS.lang) === 'en' ? 'en' : 'zh',
    theme: readLS(LS.theme) === 'dark' ? 'dark' : 'light',
    editing: false,
    assign: readJSON(LS.assign, {}),
    groups: readJSON(LS.groups, []),
    renames: readJSON(LS.renames, []),
    filter: readLS(LS.filter) || 'all',
    query: '',
    /* 区块内搜索（2026-09-17 加）：{ 组id: 关键词 }，与顶栏全局 query 相互独立。
       刻意不落 localStorage —— 它是"临时找一下"的动作，持久化会让用户下次打开
       看到被筛过的区块却想不起为什么。 */
    secQuery: {},
    /* 各区块「展开全部」的状态 { 组id: true }（2026-09-17 加）。
       与 secQuery 同理刻意不落 localStorage —— 默认只展示最常用的几个才是版式本身，
       持久化会让"展开过一次"变成新默认，区块又慢慢长回去。 */
    secExpanded: {},
    /* 顶栏「搜索与筛选」那一整行是否展开（2026-09-17 加）。
       默认 false = 收起（用户要求「默认收起，点击才展开」），同样不落 localStorage。 */
    barOpen: false,
    /* 默认页签 = MW Real-Time（2026-09-17 按需求改，原为 'gis'）。
       仅当用户从未手动切过页签时才用这个默认值；切过就会写 LS.mapTab 覆盖。
       想恢复成 GIS 默认：把这里改回 'gis'，或访问 ?map=gis 后再点任意页签。 */
    mapTab: readLS(LS.mapTab) || 'mwRealTime',
    /* 地图数据在 my_app 侧要登录；null=未探测，true=已登录，false=未登录。
       my_app 的鉴权中间件对「本机回环」放行，所以本机开发时这里恒为 true。 */
    authOk: null,
    /* /uniplam/api/auth/me 返回的同库用户主体，包含 role / allowedGroups / allowedCards。 */
    authUser: null,
    /* Quality Control 的数据库统计（2026-09-17 加）。
       qcStats = GET /api/portal-qc/summary 的原样响应；qcErr = 失败原因（字符串）。
       两者都不落 localStorage —— 统计是瞬时值，缓存下来的旧数字比没有更误导。 */
    qcStats: null,
    qcErr: '',
    /* 下钻明细弹窗状态。metric=null 表示弹窗关闭。 */
    qcDrill: { metric: null, page: 1, size: 50, q: '', total: 0, rows: [], columns: [], loading: false, err: '' },

    /* ---- 看板目录（2026-09-17 加：组件内的看板可增删改，参考 uniplam 的设计）----
       目录真相源优先级：服务端全局目录 > 本机 localStorage 兜底 > data.js 内置。
       与 uniplam 的 INITIAL_DASHBOARDS / portal-default.json 关系一致：
       内置是出厂值，服务端是运行时覆盖，DELETE 接口即可回滚。
       catalog=null 表示「服务端从未保存过」，此时用 data.js 内置目录。 */
    catalog: readJSON(LS.catalog, null),
    /* 服务端下发的写权限：仅服务器本机（回环）为 true。非本机一律只读，
       编辑按钮不出现 —— 与后端 require_protected 的判据同源，不会「点了才 403」。 */
    catalogEditable: false,
    /* 目录来源：'server' | 'local'（本机兜底）| 'builtin'。仅用于提示文案。 */
    catalogSource: 'builtin',
    /* 服务端目录只拉一次：它是全局的，不会因为本机操作而变化。
       首次渲染时 authOk 还是 null（未探测），所以拉取时机放在 render() 里
       —— 等登录态确认后再拉，避免未登录时白打一次 401。 */
    catalogLoaded: false,
    /* 看板编辑弹窗：boardNo=null 表示新增；弹窗是否打开看 #boardMask 的 hidden。 */
    boardNo: null
  };
  var authProbeBusy = false;

  /* 字号整体放缩（2026-09-17 加）：默认 0 = 100%，即"基准字号"。
     背景：全部字号类名（含 text-[11px] 这种任意值）在 index.html / portal.js 里被整体上调了一档，
     这里再叠一层「根字号 + 整页 zoom」的口子，方便现场按显示器/视距微调，
     且**不需要重编译 tailwind.css**（不用改类名）。
     实现：html.style.fontSize 让所有 rem 单位（间距/圆角/尺寸）同比放大；
           同值的 body zoom 让任意值 px、CSS 里写死的 px 字号**绝对**变大。
     两者相乘才是用户感知的"整页缩放"，所以地图 iframe 要除以 zoom 抵消一次。 */
  var FONT_STEPS = [-0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2, 0.3];
  var fontStep = (function () {
    var v = parseFloat(readLS(LS.fontStep));
    return isNaN(v) || FONT_STEPS.indexOf(v) === -1 ? 0 : v;
  })();

  function fontFactor() { return 1 + fontStep; }

  /** 整页缩放：根字号按因子放大（rem 家族），body 再按同因子 zoom（px 家族）。 */
  function applyFontScale() {
    var f = fontFactor();
    document.documentElement.style.fontSize = (16 * f) + 'px';
    document.body.style.zoom = String(f);
  }

  /** 地图 iframe 需要抵消一次缩放：父级 zoom 会把它整体放大 f 倍，
      而它内部是 px 布局，用 /f 回退一档就回到"和字号放大前一样"的高度，
      不会被撑出容器（容器高度是 CSS 里那一行 px，本来就固定）。

      ⚠️ 必须写 `style.zoom` 而不是 `style.setProperty('zoom', ...)`：
      后者会在内联样式里留下**分号分隔**的 zoom，而 `el.style.zoom = '0.87'` 是直接
      覆盖同一处声明 —— Chrome 上两者并存时前者赢，曾导致整页放大 15% 后地图仍按 1.0
      渲染。（2026-09-17 实测：整页 zoom 1.15 时地图没被裁，原因就在这里。） */
  function syncMapZoom() {
    var z = String(1 / fontFactor());
    document.querySelectorAll('.map-canvas > iframe').forEach(function (el) {
      el.style.zoom = z;
    });
  }

  /* 未登录时是否隐藏整个看板目录（只留登录提示）。
     true  = 未登录访客看不到看板清单/链接/统计（当前行为）
     false = 门户骨架对访客可见，仅地图区提示要登录（原行为）
     注意：本机回环会被 my_app 放行，所以本机打开永远是"已登录"态。 */
  var REQUIRE_LOGIN_FOR_CATALOG = true;

  /* 地图「按最终尺寸重新取景」开关（2026-09-18 加）。
     背景：stripFrame() 注入 MAP_STRIP_CSS 把地图撑满后，只调 invalidateLeaflet()
     重测尺寸、**不重算 zoom**；而内层页的 fitBounds 是在容器还矮的时候跑的
     （按高度受限 → zoom 低一级）。结果：地图停在 z6，国土只占画布宽 0.37，
     而按最终容器尺寸算应为 0.87（实测见 TMP/probe_map_refit_ab.cjs）。
     置 false 即回到「只重测尺寸、不重新取景」的原行为。 */
  var MAP_REFIT_ON_STRIP = true;

  function t(key) {
    var d = I18N[state.lang] || I18N.zh;
    return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : (I18N.zh[key] || key);
  }

  /* -------------------------------------------------------------- model -- */

  /* ------------------------------------------------------- 看板目录 -- */
  /* 2026-09-17 加。原来的目录只有 data.js 一份（由 xlsx 自动生成，写死在前端），
     页面上的编辑只能改本机 localStorage —— 与 my_app 侧栏菜单当年一样的问题：
     **A 改了，B 看不到；同一套门户不该有两份目录。**
     现在改为「服务端全局目录 + 本机兜底 + 内置出厂值」三层，见 state.catalog 注释。 */

  /** 当前生效的看板列表。所有渲染/统计都必须走这里，不要再直接读 DATA.items。 */
  function catalogItems() {
    if (state.catalog && state.catalog.length) return state.catalog;
    return DATA.items || [];
  }

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
    'http://192.168.100.27:3000/': 'external-rag-knowledge-qa'
  };

  function dashboardAccessId(item) {
    if (item && item.id) return String(item.id);
    var raw = String(item && item.url || '');
    try {
      var u = new URL(raw, location.href);
      var page = u.searchParams.get('page');
      if (page && MYAPP_ACCESS_IDS[page]) return MYAPP_ACCESS_IDS[page];
      var path = u.pathname;
      if (FINEBI_ACCESS_IDS[path]) return FINEBI_ACCESS_IDS[path];
      var exact = u.origin + u.pathname;
      if (EXTERNAL_ACCESS_IDS[exact]) return EXTERNAL_ACCESS_IDS[exact];
    } catch (e) { /* malformed/custom URL: fall through to local ids */ }
    return item && item.id ? String(item.id) : String(item && item.no || '');
  }

  function canSeeDashboard(item) {
    var user = state.authUser;
    if (!user) return true;
    var restricted = user.allowedGroups != null || user.allowedCards != null;
    if (!restricted) return true;
    var groups = Array.isArray(user.allowedGroups) ? user.allowedGroups : [];
    if (groups.some(function (g) { return groupsOf(item).indexOf(g) !== -1; })) return true;
    var cards = Array.isArray(user.allowedCards) ? user.allowedCards : [];
    var id = dashboardAccessId(item);
    return cards.indexOf(id) !== -1 || cards.indexOf(String(item && item.no)) !== -1;
  }

  function visibleCatalogItems() {
    return catalogItems().filter(canSeeDashboard);
  }

  function canRenderGroup(gid) {
    return visibleCatalogItems().some(function (it) { return groupsOf(it).indexOf(gid) !== -1; });
  }

  /** 只重绘「看板目录相关」的部分：筛选栏计数 + 各看板区块 + 工具栏按钮。
      ⚠️ **绝不能换成 render()**：render() 里有一行 `#secTopo.innerHTML = topoSection()`，
      那等于把 4 个地图 iframe 全部重建、地图重新加载几十秒。目录的增删改与地图毫无关系。
      （2026-09-17 实测：一开始图省事调了 render()，首屏地图被多加载一次，
       `verify_map_breakpoints` 从 18/18 掉到 11/18、`verify_map_auth` 掉到 13/14，
      症状是「no leaflet」——地图还没加载完脚本就断言了。） */
  function renderCatalog() {
    chipHtml();
    renderSections();
    syncCatalogBtns();
  }

  /** 拉取服务端全局目录。首屏先用内置目录渲染（不白屏），回来后再覆盖一次。
      未登录（401）/ 接口未注册（非 JSON）都视为「没有服务端目录」，保持内置，
      同时**关掉写权限** —— 状态不明时不允许写，免得把服务端目录覆盖成空。 */
  function loadCatalog() {
    fetch('/api/portal-catalog', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok) throw new Error('HTTP ' + r.status);
        // my_app 末尾的 @app.get("/{full_path:path}") 会把未注册的 /api/xxx 也回成
        // SPA 的 index.html（200 + text/html）。不校验就会把一坨 HTML 当目录读。
        if (ct.indexOf('json') === -1) throw new Error('非 JSON 响应（接口未注册或后端未重启）');
        return r.json();
      })
      .then(function (data) {
        state.catalogEditable = !!data.editable;
        if (data.catalog && data.catalog.items && data.catalog.items.length) {
          state.catalog = data.catalog.items;
          state.catalogSource = 'server';
          // 服务端为准：清掉本机兜底副本，避免两份目录长期不一致
          try { localStorage.removeItem(LS.catalog); } catch (e) { /* ignore */ }
        }
        /* ⚠️ 必须重绘，不能只调 syncCatalogBtns()：卡片上的「编辑 / 删除」按钮是
           重绘时按 catalogEditable 生成进 assignHtml 的，syncCatalogBtns() 只管工具栏
           那两个按钮。只调后者的话，「?edit=1 深链 + 服务端目录为空（出厂状态）」这条
           路径上卡片按钮永远不会出现（实测踩到）。
           但要用 renderCatalog()（不碰地图），不能用 render()。 */
        renderCatalog();
      })
      .catch(function () {
        state.catalogEditable = false;
        syncCatalogBtns();
      });
  }

  /** 把整个目录写到服务端（仅服务器本机可写）。
      **先落本机兜底再发请求**：请求失败时刷新页面也不丢改动，但绝不能让人误以为
      已经全局生效 —— 失败时 toast 明确说「仅保存在本机」。 */
  function saveCatalog(items, okMsg) {
    state.catalog = items;
    writeJSON(LS.catalog, items);
    renderCatalog();
    return fetch('/api/portal-catalog', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ catalog: { items: items } })
    }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      if (!r.ok || ct.indexOf('json') === -1) {
        throw new Error(r.status === 403 ? t('board.readonly') : 'HTTP ' + r.status);
      }
      return r.json();
    }).then(function (data) {
      // 以服务端归一化后的结果为准（后端会丢弃缺标题/链接的条目、截断超长文本）
      if (data.catalog && data.catalog.items) state.catalog = data.catalog.items;
      state.catalogSource = 'server';
      state.catalogEditable = !!data.editable;
      try { localStorage.removeItem(LS.catalog); } catch (e) { /* ignore */ }
      renderCatalog();
      toast(okMsg + ' · ' + t('board.savedServer'));
      return true;
    }).catch(function (e) {
      state.catalogSource = 'local';
      toast(okMsg + ' · ' + t('board.savedLocal') + '（' + ((e && e.message) || e) + '）');
      return false;
    });
  }

  /** 删除服务端目录，所有人回到 data.js 内置的 51 个看板。影响所有电脑，需二次确认。 */
  function resetCatalog() {
    if (!window.confirm(t('board.resetConfirm'))) return;
    fetch('/api/portal-catalog', { method: 'DELETE', credentials: 'same-origin',
      headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok || ct.indexOf('json') === -1) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function () {
        state.catalog = null;
        state.catalogSource = 'builtin';
        try { localStorage.removeItem(LS.catalog); } catch (e) { /* ignore */ }
        renderCatalog();
        toast(t('board.resetDone'));
      })
      .catch(function (e) {
        toast(t('board.saveFail') + '（' + ((e && e.message) || e) + '）');
      });
  }

  /** 新增 / 编辑 / 删除后把对应卡片滚到视野中间并闪一下 —— 看板是按访问量排序的，
      新增的卡片（clicks=0）会排在区块最后，不定位用户会以为「没加上」。 */
  function highlightBoard(no) {
    setTimeout(function () {
      var el = document.querySelector('[data-board-no="' + String(no) + '"]');
      if (!el) return;
      try { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { el.scrollIntoView(); }
      el.classList.add('is-flash');
      setTimeout(function () { el.classList.remove('is-flash'); }, 2600);
    }, 60);
  }

  /** 「新增看板 / 恢复出厂目录」按钮的显隐（编辑态 + 服务端可写才出现）。 */
  function syncCatalogBtns() {
    var canEdit = !!state.editing && !!state.catalogEditable;
    ['addBoardBtn', 'boardResetBtn'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.hidden = !canEdit;
    });
  }

  function allGroups() {
    var out = DATA.groups.map(function (g) {
      return { id: g.id, zh: g.zh, en: g.en, subZh: g.subZh, subEn: g.subEn, style: g.style };
    });
    var known = {};
    out.forEach(function (g) { known[g.id] = true; });
    (state.groups || []).forEach(function (g) {
      if (g && g.id && !known[g.id]) {
        known[g.id] = true;
        out.push({ id: g.id, zh: g.zh || g.id, en: g.en || g.id,
                   subZh: g.subZh || '', subEn: g.subEn || '', style: g.style || 'card' });
      }
    });
    (state.renames || []).forEach(function (o) {
      var g = out.filter(function (x) { return x.id === o.id; })[0];
      if (g) { if (o.zh) g.zh = o.zh; if (o.en) g.en = o.en; }
    });
    return out;
  }

  function groupLabel(g) { return state.lang === 'en' ? (g.en || g.zh || g.id) : (g.zh || g.en || g.id); }
  function groupSub(g) { return state.lang === 'en' ? (g.subEn || '') : (g.subZh || ''); }
  function groupById(id) {
    return allGroups().filter(function (g) { return g.id === id; })[0] || { id: id, zh: id, en: id };
  }

  function groupsOf(item) {
    var a = state.assign[String(item.no)];
    return (a && a.length) ? a.slice() : item.groups.slice();
  }

  function setGroups(item, list) {
    var uniq = [];
    list.forEach(function (g) { if (g && uniq.indexOf(g) === -1) uniq.push(g); });
    if (!uniq.length) { toast(t('assign.only')); return; }
    state.assign[String(item.no)] = uniq;
    writeJSON(LS.assign, state.assign);
    render();
  }

  function titleOf(item) { return state.lang === 'en' ? (item.titleEn || item.titleZh) : item.titleZh; }
  function descOf(item) { return state.lang === 'en' ? (item.descEn || item.descZh) : item.descZh; }
  function platLabel(item) { return t('plat.' + item.platform); }
  function platShort(item) { return t('platShort.' + item.platform); }
  function ownerOf(item) { return state.lang === 'en' ? (item.ownerEn || item.owner) : item.owner; }
  function deptOf(item) { return state.lang === 'en' ? (item.deptEn || item.dept) : item.dept; }
  function statusText(item) { return item.status === 'beta' ? t('status.beta') : t('status.online'); }

  function filtered() {
    return visibleCatalogItems().filter(function (it) {
      if (state.filter !== 'all') {
        if ((it.qc || []).indexOf(state.filter) === -1 &&
            groupsOf(it).indexOf(state.filter) === -1) return false;
      }
      if (!state.query) return true;
      return matchQuery(it, state.query);
    });
  }

  /* ------------------------------------------------ 区块内模糊搜索（2026-09-17 加） --
     「每个组件下面可以模糊搜索看板名字」：顶栏那个搜索框是全局的，会把整页所有区块
     一起筛掉；这里给每个区块各自一个输入框，只筛该区块的看板。
     - 与顶栏共用同一套匹配口径（matchQuery），避免同一关键词在两处命中不一致；
     - 两者是「与」的关系：顶栏筛掉的看板不会因为区块内搜索而回来（区块范围 =
       filtered() ∩ 本组），否则会出现「全局搜 A、区块搜 B 却搜出 B 的非 A 结果」；
     - 匹配范围包含 中英文标题/描述/责任人/部门/标签/平台 与看板编号 ——
       用户说"搜看板名字"，但只匹配名字会让人搜"暗号"（如 no=50）时一无所获。 */
  function matchQuery(it, q) {
    var blob = [it.titleZh, it.titleEn, it.descZh, it.descEn,
                it.owner, it.ownerEn, it.dept, it.deptEn,
                platShort(it), platLabel(it),
                'no' + it.no + ' #' + it.no,
                (it.tags || []).join(' ')].join(' ').toLowerCase();
    return blob.indexOf(q) !== -1;
  }

  /** 区块内搜索的过滤函数（q 为空时原样返回） */
  function bySectionQuery(q) {
    if (!q) return function () { return true; };
    return function (it) { return matchQuery(it, q); };
  }

  /** 区块内搜索框。放在 headHtml 的 tools 位，不改变各区块原有的排版结构。 */
  function sectionSearchHtml(gid, hit) {
    var q = state.secQuery[gid] || '';
    var badge = '';
    if (q) {
      badge = '<span class="text-[12px] px-1.5 py-0.5 rounded font-mono shrink-0 ' +
        (hit > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600') + '">' +
        esc(hit > 0 ? t('section.hit').replace('{n}', String(hit)) : t('section.noHit')) + '</span>';
    }
    return '<label class="section-search">' +
      ico('search', 'text-[14px]') +
      '<input type="search" class="sec-search-input" data-sec="' + esc(gid) + '" value="' + esc(q) + '" ' +
        'placeholder="' + esc(t('section.searchPh')) + '" aria-label="' + esc(t('section.searchPh')) + '">' +
      '</label>' + badge;
  }

  /** 反查某个看板属于哪些区块（供区块内搜索判定用，和 sectionItems 同口径） */
  function inGroup(gid) {
    return function (it) { return groupsOf(it).indexOf(gid) !== -1; };
  }

  /** 按使用量（访问量）降序，同值保持源表序号顺序 */
  function byUsage(a, b) {
    return (b.clicks || 0) - (a.clicks || 0) || (a.no - b.no);
  }

  /* ------------------------------------------------ 区块内折叠（2026-09-17 加） --
     「都设定默认展示最多看的几个，剩下的隐藏，点击后展示」。
     背景：MS View 这类分组会一直加看板，越长就把同排其他列甩出一大截空白。
     规则：
       · 默认只画访问量最高的 SEC_SHOW_N 个（byUsage 已按 clicks 降序）；
       · 隐藏数不足 SEC_MIN_HIDDEN 个就不给折叠按钮 —— 为了藏 1~2 行加个按钮不值当；
       · 区块内搜索有词时**强制全展开**：此刻用户是"来找东西的"，
         还要他再点一次「展开全部」才看到命中项就太别扭；
       · 展开状态不落 localStorage（理由见 state.secExpanded 的注释）。 */
  var SEC_SHOW_N = 6;
  /* 个别区块的默认展示条数覆盖（2026-09-18 加）。
     FLM View 用 5：它只有 8 条，按全局的 6 折叠时「隐藏数 2 < SEC_MIN_HIDDEN(3)」
     根本不会折叠，8 条全铺出来；用户明确要求「FLM View 显示 5 个」。
     设成 5 后隐藏数 = 3，正好达到 SEC_MIN_HIDDEN，按钮自然出现，无需另加判断。 */
  var SEC_SHOW_N_BY = { 'FLM View': 5 };
  var SEC_MIN_HIDDEN = 3;

  /** 某个分组下的看板（按访问量降序；超出 SEC_SHOW_N 的部分默认折叠）。
      —— 计数口径：total = 该分组下（经全局筛选后）的全部看板数；
         hit = 再经本区块搜索后命中的数量；list = 本次真正画出来的。
         三者必须分开：以前 total 与 hit 都取过滤后的长度，
         区块内搜索时会显示成「3 / 3」，看不出"11 个里命中了 3 个"。 */
  function sectionItems(gid) {
    var q = state.secQuery[gid] || '';
    var all = filtered().filter(inGroup(gid)).sort(byUsage);
    var total = all.length;
    var matched = q ? all.filter(bySectionQuery(q)) : all;
    var limit = SEC_SHOW_N_BY[gid] || SEC_SHOW_N;
    var foldable = total - limit >= SEC_MIN_HIDDEN;
    var open = !!q || !!state.secExpanded[gid];
    var shown = (foldable && !open) ? matched.slice(0, limit) : matched;
    return {
      list: shown,
      /* matched = 该分组下（经全局筛选 + 区块内搜索后）的**全部**看板，未做折叠截断。
         BO View 的子组标题要拿它算「本子组真实有几项」，否则折叠态会显示成
         「画出来的数量」（3 个子组全写 2 项），与区块级胶囊的「6 / 16」口径对不上。 */
      matched: matched,
      total: total,
      query: q,
      hit: matched.length,
      /* 折叠元信息，供 sectionHtml 决定计数怎么写、要不要画按钮 */
      foldable: foldable,
      folded: foldable && !open,
      hiddenN: matched.length - shown.length
    };
  }

  /** 「展开全部 / 收起」按钮。放在卡片列表**下方**而不是标题栏里：
      标题栏右侧已经挤了计数胶囊 + 区块内搜索框，再塞一个按钮窄屏必换行。 */
  function moreHtml(g, pack) {
    if (!pack.foldable || pack.query) return '';
    var inner = pack.folded
      ? '<span>' + esc(t('sec.more')) + '</span>' +
        '<span class="font-mono opacity-70">+' + pack.hiddenN + '</span>' +
        ico('chevron-down', 'text-[13px]')
      : '<span>' + esc(t('sec.less')) + '</span>' + ico('chevron-up', 'text-[13px]');
    return '<div class="sec-more-row">' +
      '<button type="button" class="sec-more" data-act="sec-toggle" data-gid="' + esc(g.id) + '" ' +
        'aria-expanded="' + (pack.folded ? 'false' : 'true') + '">' + inner + '</button>' +
      '</div>';
  }

  /* ---------------------------------------------------------- html utils -- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function fmt(n) { return String(n == null ? 0 : n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

  /* ---------------------------------------------------------- 静态 class -- */
  /* 平台徽章（完整字面量，供 Tailwind 扫描） */
  var PLAT_TAG = {
    myapp: 'text-[12px] px-2 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200',
    finebi: 'text-[12px] px-2 py-0.5 rounded bg-cyan-50 text-cyan-700 border border-cyan-200',
    external: 'text-[12px] px-2 py-0.5 rounded bg-violet-50 text-violet-700 border border-violet-200'
  };
  /* CXO 大卡图标渐变 */
  var CXO_GRADS = [
    'from-blue-700 to-indigo-600',
    'from-cyan-600 to-blue-600',
    'from-violet-600 to-blue-600',
    'from-emerald-600 to-teal-600'
  ];
  /* MS View 行图标底色 */
  var ROW_TONES = [
    'bg-blue-100 text-blue-700',
    'bg-cyan-100 text-cyan-700',
    'bg-indigo-100 text-indigo-700',
    'bg-sky-100 text-sky-700',
    'bg-rose-100 text-rose-700',
    'bg-teal-100 text-teal-700',
    'bg-amber-100 text-amber-700',
    'bg-emerald-100 text-emerald-700',
    'bg-purple-100 text-purple-700',
    'bg-slate-100 text-slate-700'
  ];
  /* FLM / FO 小卡图标底色 */
  var SOLID_TONES = [
    'bg-blue-600', 'bg-emerald-600', 'bg-amber-600', 'bg-cyan-600',
    'bg-rose-600', 'bg-teal-600', 'bg-indigo-600', 'bg-slate-600'
  ];
  /* Knowledge Q/A 渐变图标 */
  var QA_GRADS = [
    'from-emerald-500 to-teal-400',
    'from-blue-600 to-cyan-500',
    'from-indigo-500 to-purple-500',
    'from-rose-500 to-orange-400'
  ];
  /* Friends Links 纯色图标 */
  var FR_ICONS = [
    'bg-emerald-500', 'bg-blue-600', 'bg-indigo-500', 'bg-blue-500',
    'bg-sky-500', 'bg-teal-500', 'bg-sky-400', 'bg-blue-600',
    'bg-cyan-500', 'bg-violet-500'
  ];

  /* -------------------------------------------------------------- pieces -- */
  /* 看板卡片链接：默认走「看板查看器」外壳（viewer.html），在新页面左侧提供
     同组其他看板导航。仅 Friends Link 保持直连外链（本就是快速跳转的第三方链接）。
     gid 取当前区块（bodyHtml 里写入 state._curGid），CXO 等未走 bodyHtml 的区块
     回退到该看板所属的第一个组。 */
  function cardHref(item) {
    var gid = state._curGid || (item.groups && item.groups[0]) || '';
    if (gid === 'Friends Link') return item.url;
    return 'viewer.html?no=' + encodeURIComponent(item.no) +
      (gid ? '&gid=' + encodeURIComponent(gid) : '');
  }

  function shell(cls, item, inner) {
    // data-board-no：编辑/删除后的定位锚点（看板按访问量排序，新增的会排到最后）
    var noAttr = ' data-board-no="' + esc(item.no) + '"';
    if (state.editing) return '<div class="' + cls + ' relative"' + noAttr + '>' + inner + '</div>';
    return '<a class="' + cls + '"' + noAttr + ' href="' + esc(cardHref(item)) + '" target="_blank" ' +
      'rel="noopener noreferrer" title="' + esc(titleOf(item)) + '">' + inner + '</a>';
  }

  /** 编辑模式下的卡片工具条（非编辑模式返回空，不影响 ref 外观）：
      「编辑 / 删除」看板 + 分组标签 + 「+ 加入分组」。
      「编辑 / 删除」只在服务端可写（= 服务器本机）时出现，非本机一律只读。 */
  function assignHtml(item) {
    if (!state.editing) return '';
    var chips = groupsOf(item).map(function (gid) {
      return '<span class="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200">' +
        esc(groupLabel(groupById(gid))) +
        '<button type="button" class="text-blue-400 hover:text-rose-600 leading-none" data-act="unassign" data-no="' + item.no +
        '" data-gid="' + esc(gid) + '" title="移出 / remove">×</button></span>';
    }).join('');
    var tools = '';
    if (state.catalogEditable) {
      tools = '<button type="button" class="board-tool" data-act="board-edit" data-no="' + esc(item.no) + '" ' +
          'title="' + esc(t('board.edit')) + '" aria-label="' + esc(t('board.edit')) + '">' + ico('edit') + '</button>' +
        '<button type="button" class="board-tool danger" data-act="board-del" data-no="' + esc(item.no) + '" ' +
          'title="' + esc(t('board.del')) + '" aria-label="' + esc(t('board.del')) + '">' + ico('trash') + '</button>';
    }
    return '<span class="absolute top-1 right-1 z-10 flex flex-wrap items-center justify-end gap-1 max-w-[85%]">' +
      tools + chips +
      '<button type="button" class="text-[12px] px-2 py-1 rounded bg-slate-100 text-slate-600 border border-slate-200 hover:bg-blue-50" ' +
      'data-act="assign-menu" data-no="' + item.no + '">' + esc(t('assign.add')) + '</button></span>';
  }

  /** 状态徽章：在线 / 试运行 */
  function statusTag(item) {
    if (item.status === 'beta') {
      return '<span class="text-[12px] px-2 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-200 font-mono">β</span>';
    }
    return '';
  }

  function viewsTag(item) {
    var hl = hotLine();
    var hot = (item.clicks || 0) >= hl && hl > 0;
    return '<span class="text-[12px] font-mono ' + (hot ? 'text-rose-500' : 'text-slate-400') + '">' +
      ico(hot ? 'flame' : 'eye', 'text-[12px]') + ' ' + fmt(item.clicks || 0) + '</span>';
  }
  /* 「热门」分界线 = 全部看板访问量第 5 名。目录可编辑后不能再在模块加载时算一次
     （编辑完数字就过时了），改成按目录数组引用缓存的函数：目录一换就重算。 */
  var hotLineCache = { src: null, val: 0 };
  function hotLine() {
    var items = catalogItems();
    if (hotLineCache.src === items) return hotLineCache.val;
    var arr = items.map(function (i) { return i.clicks || 0; }).sort(function (a, b) { return b - a; });
    hotLineCache.src = items;
    hotLineCache.val = arr.length >= 5 ? arr[4] : 0;
    return hotLineCache.val;
  }

  function emptyHtml() {
    var isFiltering = !!state.query || state.filter !== 'all';
    return '<div class="text-center text-slate-400 text-sm py-8 border border-dashed border-slate-200 rounded-lg">' +
      esc(isFiltering ? t('emptyFilter') : t('empty')) + '</div>';
  }

  /** 区块空态：区分「本区块内搜索没命中」与「本来就没看板 / 被全局条件筛掉」，
      否则用户搜了没结果会以为该区块本身是空的。 */
  function sectionEmpty(pack) {
    if (pack && pack.query && !pack.hit) {
      return '<div class="col-span-full text-center text-slate-400 text-sm py-6 border border-dashed border-slate-200 rounded-lg">' +
        esc(t('emptyFilter')) + '</div>';
    }
    return emptyHtml();
  }

  /* ------------------------------------------------ 区块标题行（照 ref） -- */
  /** kind: 'square-red' | 'square-rose' | 'dot-red' | 'dot-slate'
      subInline: 副标题是否写在 h2 内部（ref 里 CXO/QC/QA 是 inline，MS/FLM/FO/BO/Admin 是独立 span） */
  function headHtml(opts) {
    var dot = {
      'square-red': 'w-2.5 h-2.5 rounded-sm bg-red-600',
      'square-rose': 'w-2.5 h-2.5 rounded-sm bg-rose-500',
      'dot-red': 'w-2.5 h-2.5 rounded-full bg-red-600',
      'dot-slate': 'w-2.5 h-2.5 rounded-full bg-slate-700'
    }[opts.kind] || 'w-2.5 h-2.5 rounded-sm bg-red-600';
    var titleCls = opts.kind === 'dot-slate' ? 'text-slate-800' : 'text-red-600';

    var title = '<h2 class="text-[19px] font-bold tracking-tight ' + titleCls +
      (opts.subInline ? ' flex items-center gap-2' : '') + '">' + esc(opts.title) +
      (opts.subInline && opts.sub ? ' <span class="text-[13px] text-slate-500 font-normal">' + esc(opts.sub) + '</span>' : '') +
      '</h2>' +
      (!opts.subInline && opts.sub ? '<span class="text-[13px] text-slate-500 font-normal">' + esc(opts.sub) + '</span>' : '');

    var wrap = opts.subInline
      ? '<div class="flex items-center gap-2"><span class="' + dot + '"></span>' + title + '</div>'
      : '<div class="flex items-center gap-1.5"><span class="' + dot + '"></span>' + title + '</div>';

    return '<div class="flex items-center justify-between mb-3.5 pb-2.5 border-b border-slate-100 gap-2 flex-wrap">' +
      wrap + (opts.tools ? '<div class="flex items-center gap-3 text-[14px]">' + opts.tools + '</div>' : '') +
      '</div>';
  }

  /* ------------------------------------------------------------- 卡片们 -- */
  /** CXO View 大卡 */
  function cxoCard(item, idx) {
    var inner =
      '<div class="w-13 h-13 rounded-xl bg-gradient-to-tr ' + CXO_GRADS[idx % CXO_GRADS.length] +
        ' text-white flex items-center justify-center text-[30px] shadow-sm group-hover:scale-105 transition shrink-0">' +
        ico(item.icon) + '</div>' +
      '<div class="flex-1 min-w-0">' +
        '<div class="flex items-center justify-between gap-1">' +
          '<span class="text-[15px] font-bold text-slate-800 group-hover:text-blue-600 truncate">' + esc(titleOf(item)) + '</span>' +
          '<span class="' + (PLAT_TAG[item.platform] || PLAT_TAG.external) + ' font-mono shrink-0">' + esc(platShort(item)) + '</span>' +
        '</div>' +
        '<p class="text-[13px] text-slate-500 mt-1 truncate">' + esc(descOf(item)) + '</p>' +
        '<div class="mt-2 text-[12px] text-slate-400 flex items-center gap-2">' +
          '<span class="' + (item.status === 'beta' ? 'text-amber-600' : 'text-emerald-600') + ' flex items-center">' +
            ico(item.status === 'beta' ? 'warning-circle' : 'circle-check', 'mr-0.5') + esc(statusText(item)) + '</span>' +
          '<span class="truncate">' + esc(deptOf(item)) + '</span>' +
          '<span class="ml-auto shrink-0">' + viewsTag(item) + '</span>' +
        '</div>' +
      '</div>' + assignHtml(item);
    return shell('flex items-start gap-3 p-3.5 rounded-lg border border-slate-200/80 bg-gradient-to-br from-slate-50/80 to-white hover:border-blue-400 hover:shadow-md transition group', item, inner);
  }

  /** MS View 单列行卡 */
  function msRow(item, idx) {
    var inner =
      '<div class="flex items-center gap-2.5 min-w-0">' +
        '<div class="w-9 h-9 rounded-md ' + ROW_TONES[idx % ROW_TONES.length] +
          ' flex items-center justify-center text-[18px] font-bold shrink-0 group-hover:bg-blue-600 group-hover:text-white transition">' +
          ico(item.icon) + '</div>' +
        '<div class="truncate">' +
          '<div class="text-[14px] font-semibold text-slate-800 group-hover:text-blue-700 truncate">' + esc(titleOf(item)) + '</div>' +
          '<div class="text-[12px] text-slate-500 truncate">' + esc(descOf(item)) + '</div>' +
        '</div>' +
      '</div>' +
      '<span class="shrink-0 ml-2 flex items-center gap-1.5">' + statusTag(item) + viewsTag(item) +
        ico('arrow-up-right', 'text-[14px] text-slate-300 group-hover:text-blue-600') + '</span>' +
      assignHtml(item);
    return shell('flex items-center justify-between p-2.5 rounded-lg hover:bg-blue-50/70 border border-slate-100 transition group', item, inner);
  }

  /** FLM / FO 小卡 */
  function solidCard(item, idx, showViews) {
    var inner =
      '<div class="w-10 h-10 rounded-lg ' + SOLID_TONES[idx % SOLID_TONES.length] +
        ' text-white flex items-center justify-center text-[20px] shrink-0">' + ico(item.icon) + '</div>' +
      '<div class="min-w-0 flex-1">' +
        '<div class="text-[14px] font-bold text-slate-800 group-hover:text-blue-600 truncate">' + esc(titleOf(item)) + '</div>' +
        '<div class="text-[12px] text-slate-500 truncate">' + esc(descOf(item)) + '</div>' +
        (showViews ? '<div class="mt-1 flex items-center gap-1.5">' + statusTag(item) + viewsTag(item) + '</div>' : '') +
      '</div>' + assignHtml(item);
    return shell('p-3 rounded-lg border border-slate-200 hover:border-blue-400 hover:bg-blue-50/50 transition group flex items-start gap-2.5', item, inner);
  }

  /** BO View 小卡
      2026-09-18 按需求「如果显示两行，则里面的内容要大一点」：卡片保持两行（标题 + 描述），
      字号整体上调一档（标题 13→14px、描述 12→13px）、内边距 2→2.5。
      配合 boBody() 把网格从 4 列改成每行 2 个 —— 卡片宽度 140px → 287px，
      标题可见字符数从约 10 个涨到约 20 个，右侧不再留空。 */
  function boCard(item) {
    var inner =
      '<div class="text-[14px] font-bold text-slate-700 group-hover:text-blue-700 truncate flex items-center gap-1">' +
        (item.status === 'beta' ? '<span class="text-amber-500">β</span>' : '') + esc(titleOf(item)) + '</div>' +
      '<div class="text-[13px] text-slate-500 truncate">' + esc(descOf(item)) + '</div>' + assignHtml(item);
    return shell('p-2.5 rounded border border-slate-100 bg-slate-50 hover:bg-blue-50 hover:border-blue-200 transition group text-left', item, inner);
  }

  /** System Admin 图标卡 */
  function adminCard(item) {
    var inner =
      '<div class="w-9 h-9 rounded-md bg-slate-100 group-hover:bg-blue-600 group-hover:text-white flex items-center justify-center text-slate-600 text-[18px] transition shrink-0">' +
        ico(item.icon) + '</div>' +
      '<div class="min-w-0">' +
        '<div class="font-bold text-slate-800 group-hover:text-blue-600 text-[13px] truncate">' + esc(titleOf(item)) + '</div>' +
        '<div class="text-[12px] text-slate-400 truncate">' + esc(descOf(item)) + '</div>' +
      '</div>' + assignHtml(item);
    return shell('p-2.5 rounded-lg border border-slate-200 hover:border-blue-400 hover:bg-blue-50/50 transition flex items-center gap-2.5 group', item, inner);
  }

  /** Knowledge Q/A 渐变卡 */
  function qaCard(item, idx) {
    var inner =
      '<div class="w-12 h-12 rounded-xl bg-gradient-to-tr ' + QA_GRADS[idx % QA_GRADS.length] +
        ' text-white flex items-center justify-center text-[26px] shadow-sm group-hover:scale-105 transition shrink-0">' +
        ico(item.icon) + '</div>' +
      '<div class="min-w-0">' +
        '<div class="text-[14px] font-bold text-slate-800 group-hover:text-blue-600 truncate">' + esc(titleOf(item)) + '</div>' +
        '<div class="text-[12px] text-slate-500 truncate">' + esc(descOf(item)) + '</div>' +
        '<div class="text-[11px] text-emerald-600 mt-1 truncate">' + esc(deptOf(item)) + '</div>' +
      '</div>' + assignHtml(item);
    return shell('flex items-start gap-3 p-3 rounded-lg border border-slate-200 hover:border-blue-400 hover:bg-slate-50 transition group', item, inner);
  }

  /** Friends Links 图标卡 */
  function friendsCard(item, idx) {
    var inner =
      '<div class="w-11 h-11 rounded-xl ' + FR_ICONS[idx % FR_ICONS.length] +
        ' text-white flex items-center justify-center text-[24px] shadow-sm group-hover:scale-105 transition">' +
        ico(item.icon) + '</div>' +
      '<span class="mt-1.5 text-[12px] text-slate-600 group-hover:text-blue-600 truncate w-full text-center">' +
        esc(titleOf(item)) + '</span>' + assignHtml(item);
    return shell('group flex flex-col items-center p-1 rounded-lg hover:bg-slate-50 transition w-[104px]', item, inner);
  }

  /* ------------------------------------------------------------ 各区块 -- */
  var BO_SUBS = [
    { id: 'wireless', key: 'sub.wireless' },
    { id: 'core', key: 'sub.core' },
    { id: 'ip', key: 'sub.ip' }
  ];

  function gridOpen(cls) { return '<div class="' + cls + '">'; }

  function bodyHtml(g, items, pack) {
    state._curGid = g.id; // 供 shell() 生成查看器链接时确定「同组」上下文
    if (!items.length) return sectionEmpty(pack);
    switch (g.id) {
      case 'CXO View':
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 gap-3') + items.map(cxoCard).join('') + '</div>';
      case 'MS View':
        return '<div class="space-y-1.5">' + items.map(msRow).join('') + '</div>';
      case 'FLM View':
        /* 2026-09-18 按需求「FLM View 字体大小风格跟 MS View 要一致」：
           原来用 solidCard（实心彩底图标 w-10/h-10 + 标题 font-bold + p-3 + 双列网格），
           与 MS View 的 msRow（浅色底图标 w-9/h-9 + 标题 font-semibold + p-2.5 + 单列）
           在字号字重、图标尺寸、内边距上都不一致。这里直接复用 msRow，
           连右侧的状态/访问量徽章与箭头也一并统一。 */
        return '<div class="space-y-1.5">' + items.map(msRow).join('') + '</div>';
      case 'SP View':
        /* 2026-09-18 加：SP View 紧贴 FLM View 下方，沿用同一套 msRow 行卡，
           两个区块上下相邻时字号/行高/图标尺寸完全一致，不会看起来像两个系统。 */
        return '<div class="space-y-1.5">' + items.map(msRow).join('') + '</div>';
      case 'FO View':
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 2xl:grid-cols-3 gap-2.5') +
          items.map(function (it, i) { return solidCard(it, i, true); }).join('') + '</div>';
      case 'System Admin':
        return gridOpen('grid grid-cols-2 gap-2 text-xs') + items.map(adminCard).join('') + '</div>';
      case 'Knowledge Q&A':
        return gridOpen('grid grid-cols-2 sm:grid-cols-4 gap-2.5') + items.map(qaCard).join('') + '</div>';
      case 'Friends Link':
        return '<div class="flex flex-wrap gap-1">' + items.map(friendsCard).join('') + '</div>';
      case 'BO View':
        return boBody(items, pack);
      default:
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 gap-2.5') +
          items.map(function (it, i) { return solidCard(it, i, true); }).join('') + '</div>';
    }
  }

  /* BO View 正文：按 BO_SUBS 分桶，每桶「标题行 + 每行 2 个的网格」。
     items  = 本次真正要画的（折叠态已被截到 limit 条）；
     pack   = sectionItems 的返回，pack.matched 是未截断的全量。
     计数口径（2026-09-18 对齐）：折叠态写「画出来的 / 本子组真实数」（如「2 / 8 项」），
     与区块级胶囊的「6 / 16 个系统」一致；不折叠时只写真实数（如「8 项」）。
     早前这里直接写 list.length，折叠态三个子组会全写「2 项」，看着像数据错了。 */
  function boBody(items, pack) {
    var full = (pack && pack.matched) || items;
    var used = {}, html = '';
    function subHead(key, drawn, realN) {
      var n = (drawn < realN) ? drawn + ' / ' + realN : String(realN);
      return '<div class="text-[13px] font-semibold text-slate-600 bg-slate-100 px-2.5 py-1.5 rounded flex items-center justify-between mb-2">' +
        '<span>' + esc(t(key)) + '</span>' +
        '<span class="text-[12px] text-slate-400 font-mono">' + n + ' 项</span></div>';
    }
    BO_SUBS.forEach(function (s) {
      var list = items.filter(function (it) { return it.boSub === s.id; });
      var realN = full.filter(function (it) { return it.boSub === s.id; }).length;
      list.forEach(function (it) { used[it.no] = true; });
      if (!list.length) return;
      html += subHead(s.key, list.length, realN) +
        gridOpen('grid grid-cols-2 gap-2.5') + list.map(boCard).join('') + '</div>';
    });
    var rest = items.filter(function (it) { return !used[it.no]; });
    if (rest.length) {
      var restReal = full.filter(function (it) { return BO_SUBS.every(function (s) { return it.boSub !== s.id; }); }).length;
      html += subHead('sub.others', rest.length, restReal) +
        gridOpen('grid grid-cols-2 gap-2.5') + rest.map(boCard).join('') + '</div>';
    }
    return '<div class="space-y-3">' + html + '</div>';
  }

  /** CXO View —— 只放系统卡，整行铺满。
      2026-09-17 按需求移除了右侧那三张 KPI 小卡（门户看板总数 / 在线运行 / 累计访问量）：
      用户明确要求「CXO View 下面要能看见看板，不要只写那几个数字」，
      同时左侧看板卡由 xl:col-span-7 放开成整行，卡片有更多横向空间。
      注：拓扑区底部原本也有一份同样的统计小卡，早前已因「与这里重复」移除；
      现在两处都不再展示这组数字 —— 汇总数字的落点见页头统计条。 */
  function cxoSection() {
    state._curGid = 'CXO View'; // CXO 不经 bodyHtml，显式设定，避免 shell() 读到上一区块的残留 gid
    var pack = sectionItems('CXO View');
    var body =
      '<div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3.5">' +
        (pack.list.length ? pack.list.map(cxoCard).join('') : sectionEmpty(pack)) +
      '</div>';

    return headHtml({
      kind: 'square-red', title: t('sec.cxo.title'), sub: t('sec.cxo.sub'), subInline: true,
      tools: sectionSearchHtml('CXO View', pack.hit) +
        '<span class="text-slate-500 hidden sm:inline">' + esc(t('sec.cxo.tool')) +
        ' <strong class="text-emerald-600 font-mono">100%</strong></span>' +
        '<span class="text-blue-600 flex items-center gap-1">' + esc(t('sec.cxo.link')) + ico('arrow', 'text-[13px]') + '</span>'
    }) + body;
  }

  /** Quality Control —— 6 张指标卡。
      2026-09-17 起大数字改为数据库实时统计（GET /api/portal-qc/summary，
      见 my_app backend/routers/portal_qc.py），点击卡片改为下钻明细弹窗。
      注意语义变化：原来点卡片是「按该维度筛选看板目录」，该能力**没有丢** ——
      仍在筛选栏的 chip 上（同 id 的 data-act="filter"），两处互不影响。

      刻意**不加区块内搜索框**：本区块列的是 6 个「质量维度」
      （Alarm / TTs / WOs / CRs / PMT / SPMS），不是看板清单 ——
      底下没有"看板名字"可筛，给个搜索框只会是个筛不出东西的摆设。
      其余 8 个区块（CXO/MS/FLM/FO/BO/Admin/QA/Friends）都是看板清单，均已加搜索框。 */
  var QC_SUB_KEY = {
    alarm: 'qc.sub.alarm', tt: 'qc.sub.tt', wo: 'qc.sub.wo',
    cr: 'qc.sub.cr', pmt: 'qc.sub.pmt', spms: 'qc.sub.spms'
  };

  /** i18n 插值：t() 只做查表，{p}/{n} 这类占位在调用层替换。 */
  function tf(key, vars) {
    var s = t(key);
    Object.keys(vars || {}).forEach(function (k) {
      s = s.split('{' + k + '}').join(String(vars[k]));
    });
    return s;
  }

  function qcMetric(id) {
    var m = state.qcStats && state.qcStats.metrics;
    return (m && m[id]) || null;
  }

  function qcSection() {
    var upd = state.qcStats && state.qcStats.generated_at
      ? t('qc.updated') + ' ' + String(state.qcStats.generated_at).slice(11, 16)
      : '';

    var cards = DATA.qc.map(function (q) {
      var on = state.filter === q.id;

      var m = qcMetric(q.id);
      /* 失败分两种：整体取不到（state.qcStats 为空）与单项失败（m.error，后端逐项容错）。
         两种情况都要按「不可用」呈现 —— 绝不能把上一次的旧数字留在屏幕上冒充实时值。 */
      var failed = !!(m && m.error) || (!!state.qcErr && !state.qcStats);
      var v = m && m.value != null ? m.value : null;
      var errMsg = (m && m.error) || state.qcErr || '';

      /* 副行 = 数据库口径；Alarm 追加去重站点数、PMT 追加超期数（同样来自接口）。 */
      var sub = t(QC_SUB_KEY[q.id] || '') || (state.lang === 'en' ? q.subEn : q.subZh);
      if (m && !failed) {
        if (q.id === 'alarm' && m.sites != null) {
          sub += ' · ' + fmt(m.sites) + ' ' + t('qc.sites');
        } else if (q.id === 'pmt' && m.overdue != null) {
          sub += ' · ' + t('qc.overdue') + ' ' + fmt(m.overdue);
        }
      } else if (failed) {
        sub = t('qc.err') + (errMsg ? ': ' + errMsg : '');
      }

      /* 数字为 null（未加载 / 拉取失败）一律显示 —，绝不显示 0 —— 统计里的 0 是真的
         一个都没有，与"没取到"必须能分辨，否则运维会误判成"已清空"。 */
      var num = v == null ? '—' : fmt(v);
      var numCls = v == null ? 'text-slate-300' : 'text-lime-600';
      var tip = failed ? sub : t('qc.click');

      return '<button type="button" class="text-left bg-gradient-to-br from-slate-50 to-white rounded-lg p-3.5 border ' +
        (on ? 'border-blue-400 ring-1 ring-blue-200' : 'border-slate-200') +
        ' hover:border-blue-400 hover:shadow-md transition group" data-act="qc" data-qc="' + esc(q.id) + '" title="' + esc(tip) + '">' +
        '<div class="flex items-center justify-between text-[14px] font-bold text-slate-700 mb-1">' +
          '<span class="truncate">' + esc(state.lang === 'en' ? q.en : q.zh) + '</span>' +
          '<span class="p-1 rounded bg-blue-50 text-blue-600 shrink-0">' + ico(q.icon) + '</span>' +
        '</div>' +
        '<div class="text-[30px] lg:text-[36px] font-extrabold ' + numCls + ' font-mono tracking-tight group-hover:scale-105 transition-transform mt-1">' +
          num + '</div>' +
        '<div class="text-[12px] mt-1.5 truncate ' + (failed ? 'text-rose-500' : 'text-slate-500') + '" title="' + esc(sub) + '">' +
          esc(sub) + '</div>' +
      '</button>';
    }).join('');

    /* 标题栏「达标率」：原来是写死的字符串，2026-09-17 改为接口算出的真实值
       （近 30 天 TT 的 SLA Pass 占比）。取不到就显示 —，不保留假数字。 */
    var sla = qcMetric('sla');
    var slaVal = sla && sla.value != null ? Number(sla.value).toFixed(1) + '%' : '—';
    var slaTip = sla && sla.total
      ? tf('sec.qc.sla.tip', { d: sla.days, pass: fmt(sla.pass), total: fmt(sla.total) })
      : (sla && sla.error ? t('qc.err') + ': ' + sla.error : t('qc.loading'));

    return headHtml({
      kind: 'square-rose', title: t('sec.qc.title'), sub: t('sec.qc.sub'), subInline: true,
      tools: '<span class="text-slate-400 hidden md:inline text-[13px] font-mono">' +
          esc(upd || t('qc.loading')) + '</span>' +
        '<button type="button" class="btn-soft" data-act="qc-reload" title="' + esc(t('qc.reload')) + '">' +
          ico('refresh') + esc(t('qc.reload')) + '</button>' +
        '<span class="inline-flex items-center px-2.5 py-1 rounded text-[13px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200" title="' + esc(slaTip) + '">' +
          ico('shield', 'mr-1') + esc(t('sec.qc.sla.label')) + ' <strong class="font-mono">' + esc(slaVal) + '</strong></span>'
    }) + '<div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3.5">' + cards + '</div>';
  }
  /* ================================================ QC 统计 / 明细下钻 ==
     数据来自 my_app 的只读接口（backend/routers/portal_qc.py），经 nginx 的
     /api/ 兜底同源转发到本机 7038 —— 前端拿不到、也不需要任何数据库凭证。

     **必须校验响是不是 JSON**：my_app 末尾的 `@app.get("/{full_path:path}")`
     会把任何未注册的 /api/xxx 也回成 SPA 的 index.html（200 + text/html）。
     不校验就会把一坨 HTML 当统计读，页面静默变成一排「—」且查不出原因。 */
  var QC_POLL_MS = 60000;
  var QC_MONO_KEY = /^(tt_no|wo_no|cr_id|pmt_no|doc_no|site_id|alarmcode|raised)$/;

  var qcStatsBusy = false;
  var qcDrillSeq = 0;

  function qcApi(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok) throw new Error('HTTP ' + r.status);
        if (ct.indexOf('json') === -1) throw new Error('非 JSON 响应（接口未注册或后端未重启）');
        return r.json();
      });
  }

  /** 只重绘 #secQc。刻意不调 render()：render() 会走 ensureMap()，
      把当前地图 iframe 再 strip 一遍；统计刷新与地图无关，不该每分钟打扰一次。 */
  function paintQc() {
    if (REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true) return;
    var el = document.getElementById('secQc');
    if (el) el.innerHTML = qcSection();
  }

  function fetchQcStats(force) {
    if (qcStatsBusy) return;
    if (REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true) return;
    qcStatsBusy = true;
    qcApi('/api/portal-qc/summary' + (force ? '?refresh=1' : ''))
      .then(function (data) {
        qcStatsBusy = false;
        state.qcStats = data;
        state.qcErr = '';
        paintQc();
        renderQcDrill();          // 弹窗开着时同步刷新（分页/搜索不变）
      })
      .catch(function (e) {
        qcStatsBusy = false;
        state.qcErr = (e && e.message) || String(e);
        // 清空旧值：宁可显示 —，也不要把上一次的数字留在屏幕上冒充实时统计
        state.qcStats = null;
        paintQc();
        renderQcDrill();
      });
  }

  /* ------------------------------------------------------------ 明细下钻 -- */
  /** 弹窗标题 = 卡片名 + 「· 明细」。切语言时要重算，故单独抽出来。 */
  function applyQcDrillTitle() {
    var id = state.qcDrill.metric;
    var q = DATA.qc.filter(function (x) { return x.id === id; })[0];
    document.getElementById('qcTitle').textContent =
      (q ? (state.lang === 'en' ? q.en : q.zh) : id) + t('qc.drillSuffix');
  }

  function openQcDrill(id) {
    document.getElementById('qcSearch').value = '';
    state.qcDrill = { metric: id, page: 1, size: 50, q: '', total: 0,
                      rows: [], columns: [], loading: true, err: '' };
    applyQcDrillTitle();
    document.getElementById('qcMask').hidden = false;
    fetchQcDrill();
  }

  function closeQcDrill() {
    qcDrillSeq++;                       // 作废在途请求，避免关掉后又被写回
    state.qcDrill.metric = null;
    state.qcDrill.loading = false;
    document.getElementById('qcMask').hidden = true;
  }

  function fetchQcDrill() {
    var d = state.qcDrill;
    if (!d.metric) return;
    var seq = ++qcDrillSeq;
    d.loading = true; d.err = '';
    renderQcDrill();
    qcApi('/api/portal-qc/detail?metric=' + encodeURIComponent(d.metric) +
          '&page=' + d.page + '&size=' + d.size +
          (d.q ? '&q=' + encodeURIComponent(d.q) : ''))
      .then(function (data) {
        if (seq !== qcDrillSeq || state.qcDrill.metric !== d.metric) return;   // 过期响应
        d.loading = false;
        d.total = data.total;
        d.rows = data.rows || [];
        d.columns = data.columns || [];
        renderQcDrill();
      })
      .catch(function (e) {
        if (seq !== qcDrillSeq || state.qcDrill.metric !== d.metric) return;
        d.loading = false;
        d.err = (e && e.message) || String(e);
        renderQcDrill();
      });
  }

  /** 单元格显示。接口一律回文本，这里只做两件轻格式化：
      · 13 位纯数字 → 按 epoch 毫秒转本地时间（realtime_alarm.alarmraisedtime 就是这种）
      · 整数型 numeric 的尾巴 .0 去掉（PG 的 auxiliarycount 会回 '2.0'） */
  function qcCell(v) {
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

  function renderQcDrill() {
    var d = state.qcDrill;
    if (!d.metric) return;
    var thead = document.getElementById('qcThead');
    var tbody = document.getElementById('qcTbody');
    if (!thead || !tbody) return;

    var span = Math.max(1, d.columns.length);
    thead.innerHTML = '<tr>' + d.columns.map(function (c) {
      return '<th>' + esc(c.label) + '</th>';
    }).join('') + '</tr>';

    var ph;
    if (d.err) ph = '<span class="qc-err">' + esc(t('qc.err')) + '<br>' + esc(d.err) + '</span>';
    else if (d.loading && !d.rows.length) ph = esc(t('qc.loading'));
    else if (!d.rows.length) ph = esc(t('qc.empty'));

    if (ph) {
      tbody.innerHTML = '<tr><td colspan="' + span + '"><div class="qc-empty">' + ph + '</div></td></tr>';
    } else {
      tbody.innerHTML = d.rows.map(function (row) {
        return '<tr>' + d.columns.map(function (c) {
          var val = qcCell(row[c.key]);
          return '<td' + (QC_MONO_KEY.test(c.key) ? ' class="mono"' : '') + '>' + esc(val) + '</td>';
        }).join('') + '</tr>';
      }).join('');
    }

    var pages = Math.max(1, Math.ceil(d.total / d.size));
    document.getElementById('qcCount').textContent =
      d.err ? '' : tf('qc.total', { n: fmt(d.total) });
    document.getElementById('qcPage').textContent = tf('qc.page', { p: d.page, n: pages });
    document.getElementById('qcPrev').disabled = d.loading || d.page <= 1;
    document.getElementById('qcNext').disabled = d.loading || d.page >= pages;
  }

  /** 导出当前页 CSV。首字符加 BOM，否则 Excel 打开中文是乱码。 */
  function exportQcCsv() {
    var d = state.qcDrill;
    if (!d.metric || !d.rows.length) { toast(t('qc.noCsv')); return; }
    var cell = function (v) {
      var s = qcCell(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    var lines = [d.columns.map(function (c) { return cell(c.label); }).join(',')];
    d.rows.forEach(function (row) {
      lines.push(d.columns.map(function (c) { return cell(row[c.key]); }).join(','));
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'qc-' + d.metric + '-p' + d.page + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  /** 通用分组区块（MS / FLM / FO / BO / Admin / QA / Friends / 自建组） */
  var SEC_META = {
    'MS View': { kind: 'dot-red', subKey: 'sec.ms.sub' },
    'FLM View': { kind: 'dot-red', subKey: 'sec.flm.sub' },
    'SP View': { kind: 'dot-red', subKey: 'sec.sp.sub' },
    'FO View': { kind: 'dot-red', subKey: 'sec.fo.sub' },
    'BO View': { kind: 'dot-red', subKey: 'sec.bo.sub' },
    'System Admin': { kind: 'dot-slate', subKey: 'sec.admin.sub' },
    'Knowledge Q&A': { kind: 'square-red', subKey: 'sec.qa.sub' },
    'Friends Link': { kind: 'square-red', subKey: 'sec.friends.sub' }
  };

  function sectionHtml(g, pack) {
    var meta = SEC_META[g.id] || { kind: 'dot-slate', subKey: '' };
    var sub = meta.subKey ? t(meta.subKey) : groupSub(g);
    /* 计数：折叠或区块内搜索时显示「画出来的 / 总数」，否则只显示总数。
       只写总数会在筛过 / 折过之后误导 —— 底下只画了 6 张却写「11 个系统」。
       两边都是同一个口径：分子 = 眼睛能看到的，分母 = 该区块的全部。 */
    var countTxt = (pack.query || pack.folded)
      ? pack.list.length + ' / ' + pack.total + ' ' + esc(t('sec.count'))
      : pack.total + ' ' + esc(t('sec.count'));
    var tools = '<span class="text-[12px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">' +
      countTxt + '</span>' + sectionSearchHtml(g.id, pack.hit);

    if (g.id === 'Knowledge Q&A') {
      tools += '<span class="text-blue-600 flex items-center gap-0.5">' + esc(t('sec.qa.link')) + ico('arrow', 'text-[13px]') + '</span>';
    }
    if (g.id === 'Friends Link') {
      tools += '<span class="text-blue-600 flex items-center gap-0.5">' + esc(t('sec.friends.link')) + ico('arrow', 'text-[13px]') + '</span>';
    }
    if (!SEC_META[g.id] && state.editing) {
      tools += '<button type="button" class="text-[12px] px-2 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-200" ' +
        'data-act="del-group" data-gid="' + esc(g.id) + '">' + esc(t('modal.del')) + '</button>';
    }

    return headHtml({ kind: meta.kind, title: groupLabel(g), sub: sub, subInline: false, tools: tools }) +
      bodyHtml(g, pack.list, pack) + moreHtml(g, pack);
  }

  /* -------------------------------------------- 拓扑地图页签（内嵌 iframe） */
  /* 这 4 个看板由 nginx /myapp/ 同源反代，服务端未设置 X-Frame-Options，可直接内嵌。
     用相对路径而不是数据里的绝对 IP，门户无论从 localhost 还是 LAN IP 访问都能用。
     —— 用户只想要「地图组件」本身：iframe 加载后注入 CSS，把该页面上与地图无关的
     组件（顶部筛选工具栏 / 统计卡 / 分析图表 / 侧栏）整块隐藏，只留 Leaflet 画布。 */
  var MAP_TABS = [
    { page: 'gis',            key: 'map.tab.gis',   icon: 'map' },
    { page: 'mwRealTime',     key: 'map.tab.mw',    icon: 'broadcast' },
    { page: 'realtime_alarm', key: 'map.tab.alarm', icon: 'bell' },
    { page: 'packet_loss',    key: 'map.tab.loss',  icon: 'link' }
  ];

  /* 只保留含地图的那一块，其余顶层区块整块隐藏；地图卡片去壳后铺满。
     —— 对 gis / realtime_alarm / packet_loss（React SPA）纯 CSS 即可。
     —— 对 mwRealTime：它外层不含 Leaflet，地图藏在同源内层 iframe
        (/myapp/mw_real_time.html) 里，所以这里额外放行 iframe，再由 JS 递归剥离。 */
  var MAP_STRIP_CSS = [
    'html,body{margin:0!important;padding:0!important;height:100%!important;overflow:hidden!important;background:transparent!important}',
    '#root,.ant-layout,.ant-layout-content{height:100%!important;min-height:0!important;margin:0!important;padding:0!important;background:transparent!important}',
    'main#main-content{height:100%!important;padding:0!important;margin:0!important;overflow:hidden!important}',
    'main#main-content > div{height:100%!important;padding:0!important;margin:0!important;display:block!important}',
    'main#main-content > div > *:not(:has(.leaflet-container)):not(:has(iframe)):not(iframe){display:none!important}',
    'main#main-content > div > iframe,main#main-content > div > *:has(iframe){width:100%!important;height:100%!important;border:0!important;display:block!important;margin:0!important;padding:0!important}',
    // 地图的每一层祖先都必须有确定高度，否则 .leaflet-container 的 height:100%
    // 会退化成 auto，地图就停在页面自己算的那个高度上（丢包分析页实测 292px vs 378px）
    'main#main-content *:has(.leaflet-container){height:100%!important;min-height:0!important;max-height:none!important}',
    'main#main-content .ant-card:has(.leaflet-container){height:100%!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;background:transparent!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-head{display:none!important}',
    'main#main-content .ant-card:has(.leaflet-container) > .ant-card-body{height:100%!important;padding:0!important}',
    // 地图卡片里与地图同级的小块（实测是「Critical/Major/Minor/Warning/OK」图例）
    // 若让它参与普通流，地图撑满后它会被挤出卡片裁掉 —— 改成贴底浮层，两者都留
    'main#main-content .ant-card-body:has(.leaflet-container){position:relative!important}',
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
    '.leaflet-container{height:100%!important;min-height:0!important;max-height:none!important;width:100%!important;border-radius:0!important}'
  ].join('');

  /** 内层纯静态页（mw_real_time.html）：从 Leaflet 画布逐层向上隐藏所有兄弟，
      只留地图，并让整条祖先链撑满 iframe，最后触发 resize 让 Leaflet 重算尺寸。 */
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
      el.style.setProperty('height', '100%', 'important');
      el.style.setProperty('width', '100%', 'important');
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

  /** 让 Leaflet 重新测量容器尺寸。
      —— 为什么需要：MAP_STRIP_CSS 用 height:100%!important 把 .leaflet-container
      从「页面自己算的 88px」拉到「iframe 的 378px」，但 Leaflet 实例内部缓存的
      _size 还是旧值。容器长大了、tile 图层没跟着重算，就会按旧尺寸铺出来超出容器，
      再被 overflow:hidden 裁掉 —— 表现就是「地图只露出一小块、不在正中」。
      Leaflet 1.x 没有全局实例表，但每个 map 都会给容器挂 _leaflet_id，
      而 map 实例本身可通过容器的私有属性拿到；拿不到时退回最通用的做法：
      把容器尺寸「抖一下」（改一个像素再改回来）逼 Leaflet 的
      ResizeObserver / 内部 _onResize 重新走一遍 onResize。
      两条路都失败时，最后再补一次 window.resize 事件，尽力而为。 */
  function invalidateLeaflet(doc) {
    var lc = doc.querySelector('.leaflet-container');
    if (!lc) return false;
    var map = null;

    // 路 1：leaflet 把 map 实例存在容器元素上（不同封装版本属性名不同）
    ['_leaflet_map', '__leaflet_map', '_map', 'map'].forEach(function (k) {
      if (!map && lc[k] && typeof lc[k].invalidateSize === 'function') map = lc[k];
    });

    // 路 2：React fiber 树里找带 invalidateSize 的节点（my_app 是 React 应用）
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
        // 容器尺寸变化后，若地图中心被 Leaflet 判断为「越界」会自己漂移，
        // 用不带 pan 的 invalidateSize 保住原中心点；再补一帧确认。
        setTimeout(function () { try { map.invalidateSize(false); } catch (e) {} }, 300);
        return true;
      } catch (e) { /* 落到路 3 */ }
    }

    // 路 3：抖尺寸 + resize 事件，逼 Leaflet 自己重算
    try {
      var h = lc.style.height;
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

  /** 让内层页按**最终**容器尺寸重新取景（2026-09-18 加）。
      为什么需要：stripFrame 注入 CSS 把地图撑满后，invalidateLeaflet 只重测尺寸、
      不重算 zoom；而内层页的 fitBounds 跑在容器还矮的时刻 → zoom 低一级。
      做法：在加载期观察容器高度，**每次高度落定（500ms 内不再变）就重新取景一次**，
      直到观察窗口结束。最后一次必然对应最终尺寸。
      ⚠️ 不能只做「第一次落定就收工」：实测容器会在**前 strip 的 318px 假稳态**
         停留 1s 以上再跳到 856px，只做一次会被假稳态骗到、锁死在 z6
         （2026-09-18 踩过，见 TMP/verify_need123.cjs 的落定门控注释）。
      守卫：① 只对暴露了 fitAllSites 的内层页生效 —— 当前只有 mw_real_time.html；
            其余三个页签是 React SPA，GISMap.tsx 写死 zoom=8（设计如此），
            没有 fitAllSites，直接跳过；
            ② 每个 document 只挂一次观察器（reload 后自动重置）；
            ③ 观察窗口约 12s 后停止 —— 之后只有用户改布局才可能改容器高度，
            不会因为平移/缩放而误触发；
            ④ MAP_REFIT_ON_STRIP 总开关。 */
  function refitLeaflet(d) {
    if (!MAP_REFIT_ON_STRIP) return false;
    var w = d.defaultView;
    if (!w || typeof w.fitAllSites !== 'function') return false;
    if (d.__msRefitState) return false;
    var st = d.__msRefitState = { lastH: -1, tries: 0, timer: null };
    function apply() {
      st.timer = null;
      var lc = d.querySelector('.leaflet-container');
      if (!lc) return;
      var h = Math.round(lc.getBoundingClientRect().height);
      if (h <= 0 || h !== st.lastH) return;   // 期间又变了，等下一轮
      try { w.fitAllSites(); } catch (e) { /* 内层页自己会兜底 */ }
    }
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
      if (st.tries++ < 40) setTimeout(tick, 300);   // 观察窗口 ≈ 12s
    })();
    return true;
  }

  /** 给 iframe 注入「只留地图」样式；React 重渲染后重新确认。
      depth 用于穿透同源内层 iframe（最多 2 层）。 */
  function stripFrame(f, depth) {
    depth = depth || 0;
    try {
      var d = f.contentDocument;
      if (!d || !d.head) return;
      var s = d.getElementById('msportal-strip');
      if (!s) {
        s = d.createElement('style');
        s.id = 'msportal-strip';
        d.head.appendChild(s);
      }
      if (s.textContent !== MAP_STRIP_CSS) s.textContent = MAP_STRIP_CSS;

      // 本层就有地图
      if (d.querySelector('.leaflet-container')) {
        // 外层 React 页面靠 CSS 即可（写内联样式会被 React 重渲染覆盖）；
        // 内层纯静态页用 JS 逐层剥离，只留 Leaflet 画布
        if (depth > 0) keepOnlyMap(d);
        // 关键：注入 CSS 改变了容器高度，必须让 Leaflet 重算尺寸，
        // 否则 tile 会按旧尺寸铺出去被裁掉（见 invalidateLeaflet 注释）。
        invalidateLeaflet(d);
        // 尺寸重算完还不够：fitBounds 是在容器还矮时跑的，zoom 会低一级。
        // 等布局稳定后按最终尺寸重新取景一次（内部有三重守卫，见 refitLeaflet）。
        refitLeaflet(d);
        setTimeout(function () { invalidateLeaflet(d); }, 400);
        setTimeout(function () { invalidateLeaflet(d); }, 1200);
        return;
      }

      // 本层没有地图 → 往下找同源 iframe 递归处理
      if (depth >= 2) return;
      Array.prototype.forEach.call(d.querySelectorAll('iframe'), function (inner) {
        var go = function () {
          tellEmbed(inner, depth + 1);
          stripFrame(inner, depth + 1);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 1200);
          setTimeout(function () { tellEmbed(inner, depth + 1); stripFrame(inner, depth + 1); }, 3200);
        };        if (inner.dataset.msStripped === '1') { go(); return; }
        inner.dataset.msStripped = '1';
        inner.addEventListener('load', go);
        try {
          if (inner.contentDocument && inner.contentDocument.readyState === 'complete') go();
        } catch (e) { /* ignore */ }
      });
    } catch (e) { /* 跨域时静默跳过 */ }
  }

  /** 通知被嵌页面「你在门户里」——它据此隐藏自己那套工具栏/KPI/图表，并切底图主题。
      为什么必须走 postMessage 而不是 URL 参数（2026-09-17 实测踩过）：
        mwRealTime 是三层 iframe：
          MsPortal ─> /myapp/?page=mwRealTime（React 外壳，认 URL 参数）
                       └─> /myapp/mw_real_time.html?_=<ts>（真正的地图页）
        内层 src 由 LegacyToolFrame.tsx 拼成 `${BASE_URL}${file}?_=${cacheBust}`，
        **会把外层的 query 全丢掉** —— ?mwembed=1 根本传不进去。
        所以对本层每个同源 iframe 直接投递消息：外壳那一层收不到也不影响
        （它没有对应监听，静默忽略），真正的接收方是第 2 层的 mw_real_time.html。
        与 my_app 自有的 myapp-theme / myapp-locale 同一套协议思路。
      theme 取门户当前主题，是「视觉决定」而非安全边界。 */
  function tellEmbed(f, depth) {
    try {
      if (!f.contentWindow) return false;
      f.contentWindow.postMessage(
        { __type: 'msportal-embed', theme: state.theme, depth: depth || 0 }, '*');
      return true;
    } catch (e) { return false; }
  }

  function mapItems() {
    var out = MAP_TABS.map(function (m) {
      var item = catalogItems().filter(function (x) {
        return String(x.url || '').indexOf('page=' + m.page + '&') !== -1 || String(x.url || '').indexOf('page=' + m.page) !== -1;
      })[0];
      return {
        allowed: !!item && canSeeDashboard(item),
        page: m.page, key: m.key, icon: m.icon, item: item,
        title: item ? titleOf(item) : m.page,
        /* mwembed=1 / theme=dark 是给 /myapp/?page=* 这层（React 外壳）的 URL 参数。
           ⚠️ 实测：对 mwRealTime 无效 —— 外壳里的 LegacyToolFrame 会用写死的
           `${BASE_URL}${file}?_=<cacheBust>` 去加载内层，门户给的 query 到这里就断了。
           mwRealTime 真正的控制通道是 tellEmbed() 的 postMessage；
           这两个参数留着是因为：直开本页（不经门户）时仍然有用，
           且将来若有页签直接从 URL 读，也不必再回来改。
           其余 3 个页签（React SPA）不认这两个参数，带了也无副作用。 */
        src: '/myapp/?page=' + m.page + '&mwembed=1' + (state.theme === 'dark' ? '&theme=dark' : '')
      };
    });
    out = out.filter(function (m) { return m.allowed; });
    if (out.length && !out.some(function (m) { return m.page === state.mapTab; })) state.mapTab = out[0].page;
    return out;
  }

  function topoSection() {
    var head =
      '<div class="flex flex-wrap items-center justify-between pb-2.5 mb-3 border-b border-slate-100 gap-2">' +
        '<div class="flex items-center gap-2 min-w-0">' +
          '<span class="p-1.5 rounded bg-teal-50 text-teal-600 shrink-0">' + ico('map-pin', 'text-[20px]') + '</span>' +
          '<div class="min-w-0">' +
            '<h3 class="text-[17px] font-bold text-slate-800 truncate">' + esc(t('topo.title')) + '</h3>' +
            '<span class="text-[13px] text-slate-400 truncate block">' + esc(t('topo.sub')) + '</span>' +
          '</div>' +
        '</div>' +
        /* 2026-09-18 加 flex-wrap + justify-end：这组按钮（实时状态 + 4 个页签 + 刷新 + 新窗口打开）
           最小内容宽约 410px，而窄屏下本行可用宽度只有 356px（#secTopo 388 − p-4 两侧）。
           原来是 nowrap，子元素又都缩不到内容宽以下 → 整组撑到 443px，**横向溢出视口 23px**
           （420px 下实测；`verify_msportal` 的「全断点无横向溢出」一直红的就是这条）。
           改换行后：≥640px 有空间时行为不变，只在 <480px 左右才折成两行。 */
        '<div class="flex flex-wrap items-center justify-end gap-1.5">' +
          '<span class="text-[13px] text-emerald-600 flex items-center gap-1 mr-1">' +
            '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500 status-pulse-green"></span>' + esc(t('topo.live')) + '</span>' +
          '<div class="flex items-center gap-0.5 bg-slate-100 p-0.5 rounded-lg text-[13px]" id="mapTabs" role="tablist" aria-label="Topology maps"></div>' +
          '<button type="button" class="text-[13px] px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-blue-400 hover:text-blue-600 transition flex items-center gap-1" id="mapRefresh">' +
            ico('refresh', 'text-[13px]') + '<span class="hidden 2xl:inline">' + esc(t('map.refresh')) + '</span></button>' +
          '<a class="text-[13px] px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-blue-400 hover:text-blue-600 transition flex items-center gap-1" id="mapOpen" href="#" target="_blank" rel="noopener noreferrer">' +
            ico('external', 'text-[13px]') + '<span class="hidden 2xl:inline">' + esc(t('map.open')) + '</span></a>' +
        '</div>' +
      '</div>';

    var canvas =
      '<div class="map-canvas map-pattern" id="mapHost">' +
        '<div class="absolute inset-0 flex items-center justify-center gap-2 text-slate-400 text-[14px]" id="mapBoot">' +
          '<span class="w-4 h-4 rounded-full border-2 border-slate-300 border-t-blue-600 animate-spin"></span>' +
          '<span>' + esc(t('map.loading')) + '</span>' +
        '</div>' +
      '</div>';

    /* 这里原本还有一排 3 张统计小卡（门户看板总数 51 / 在线运行 34 / 累计访问量 24,289 · TOP 1,652）。
       2026-09-17 按需求移除 —— 拓扑区块只保留「标题栏 + 地图画布」，
       这些汇总数字在 CXO View 右侧已经有一份，不必重复占地图的高度。 */
    return head + canvas;
  }

  /* ------------------------------------------------- 升级机制表格（2026-09-18 加） --
     内容来自 升级机制.xlsx，逐格照抄在 data.js 的 MS_PORTAL_DATA.escalation 里
     （源表的缺号 / 空格一律保留，理由见那边的注释）。

     版式决策：
       · LEVEL 列用 rowspan 合并，与源表的合并单元格一致 —— 22 行里 15 行是 LEVEL1，
         每行重复写一遍既啰嗦又把列宽浪费掉；合并后一眼能看出"这一档有几个人"。
       · 号码 / 邮箱用等宽字体；邮箱做成 mailto 链接（值班时点一下就能发）。
         号码**不做 tel: 链接** —— 源表是利比里亚本地号（077…/088…），
         加 +231 是猜测，猜错比不给链接更糟。
       · 中列在 xl 断点只有 3/12 宽（≈360px），6 列必然放不下，所以外层 .esc-scroll
         横向滚动兜底，绝不让表格把整页撑出横向滚动条。
       · 高度给 420px 上限 + 内部纵向滚动：22 行全铺开约 700px，
         会把中列甩出左/右列一大截（版式平衡的实测见 index.html 里 Admin 那段的注释）。
       · 本区块是静态参考信息：不参与搜索/筛选/折叠/编辑模式，只在 render() 里建。 */
  var ESC_LV_CLS = {
    LEVEL1: 'esc-lv-1', LEVEL2: 'esc-lv-2', LEVEL3: 'esc-lv-3', LEVEL4: 'esc-lv-4'
  };

  /** 某一档的中/英文说明（如 "LEVEL 1 · 值班热线与专业工程师"），取不到就退回 id */
  function escLevelLabel(id) {
    var lv = (((DATA.escalation || {}).levels) || []).filter(function (l) { return l.id === id; })[0];
    if (!lv) return id;
    return state.lang === 'en' ? (lv.en || lv.zh || id) : (lv.zh || lv.en || id);
  }

  /** 空值统一画成灰色破折号 —— 源表里确实有空格（IP/DWDM/OLT 那行缺两个号码），
      留白会让人以为是渲染漏了，写 "—" 才读得出"源表就没有"。 */
  function escVal(v) {
    return v ? esc(v) : '<span class="esc-dash">—</span>';
  }

  /** 号码里的 "/" 后面插一个 <wbr>：源表有 "-0773777115/0774777115" 这种双号写法，
      列宽按单号（10~11 位）定的，不给断点的话这个格子会把整列顶宽 60px。
      只给断点、不改写内容 —— 显示出来还是原样的两个号。 */
  function escNum(v) {
    if (!v) return '<span class="esc-dash">—</span>';
    return esc(v).replace(/\//g, '/<wbr>');
  }

  /** 表格本体（页内小表与「放大查看」弹窗共用一份）。
      wide=false → 页内版：table-layout: fixed + min-width 640，装不下由 .esc-scroll 滚；
      wide=true  → 弹窗版：min-width 归零、不限高，列宽按同比例放大到全宽，
                   6 列全部单行（浏览器实测 796px 即可全单行，弹窗宽 ≥1000px）。
      —— 两份 HTML 由同一个函数生成，避免"页内改了、弹窗忘了改"两处走样。 */
  function escTableHtml(wide) {
    var E = DATA.escalation;
    var rows = E.rows;

    /* 同 level 的行必须连续（源表本来就是分档排列）；断开就当成新的一档重新起 rowspan，
       这样即使以后源表顺序被打乱，也不会把不相邻的行算进同一个合并格里。 */
    var starts = {};
    var curKey = null;
    rows.forEach(function (r, i) {
      if (i === 0 || rows[i - 1].level !== r.level) {
        starts[i] = { id: r.level, n: 1 };
        curKey = i;
      } else {
        starts[curKey].n++;
      }
    });

    var body = rows.map(function (r, i) {
      var g = starts[i];
      var lvCell = '';
      if (g) {
        var lbl = escLevelLabel(g.id) + ' · ' + tf('esc.pax', { n: g.n });
        lvCell = '<td class="esc-lv ' + (ESC_LV_CLS[g.id] || 'esc-lv-1') + '" rowspan="' + g.n + '" title="' + esc(lbl) + '">' +
            '<span class="esc-lv-badge">' + esc(g.id) + '</span>' +
            '<span class="esc-lv-n">' + esc(tf('esc.pax', { n: g.n })) + '</span>' +
          '</td>';
      }
      var mail = r.email
        ? '<a href="mailto:' + esc(r.email) + '" title="' + esc(r.email) + '">' + esc(r.email) + '</a>'
        : '<span class="esc-dash">—</span>';
      return '<tr class="' + (ESC_LV_CLS[r.level] || 'esc-lv-1') + '">' + lvCell +
          '<td class="esc-pos">' + escVal(r.position) + '</td>' +
          '<td class="esc-name">' + escVal(r.name) + '</td>' +
          '<td class="esc-num">' + escNum(r.orange) + '</td>' +
          '<td class="esc-num">' + escNum(r.lonestar) + '</td>' +
          '<td class="esc-mail">' + mail + '</td>' +
        '</tr>';
    }).join('');

    return '<div class="esc-scroll' + (wide ? ' esc-scroll--wide' : '') + '">' +
        '<table class="esc-table">' +
          '<thead><tr>' +
            '<th class="esc-th-lv">' + esc(t('esc.col.level')) + '</th>' +
            '<th>' + esc(t('esc.col.position')) + '</th>' +
            '<th>' + esc(t('esc.col.name')) + '</th>' +
            '<th>' + esc(t('esc.col.orange')) + '</th>' +
            '<th>' + esc(t('esc.col.lonestar')) + '</th>' +
            '<th>' + esc(t('esc.col.email')) + '</th>' +
          '</tr></thead>' +
          '<tbody>' + body + '</tbody>' +
        '</table>' +
      '</div>';
  }

  /** 四档职级说明（弹窗里有横向空间，就把页内只能塞进 tooltip 的档位名摆出来） */
  function escLegendHtml() {
    var E = DATA.escalation;
    var counts = {};
    E.rows.forEach(function (r) { counts[r.level] = (counts[r.level] || 0) + 1; });
    return '<div class="esc-legend">' + (E.levels || []).map(function (lv) {
      return '<span class="esc-legend-item ' + (ESC_LV_CLS[lv.id] || 'esc-lv-1') + '">' +
          '<b>' + esc(lv.id) + '</b>' +
          '<span>' + esc(escLevelLabel(lv.id).replace(new RegExp('^' + lv.id + '\\s*·\\s*'), '')) + '</span>' +
          '<i>' + esc(tf('esc.pax', { n: counts[lv.id] || 0 })) + '</i>' +
        '</span>';
    }).join('') + '</div>';
  }

  function escSection() {
    var E = DATA.escalation;
    if (!E || !E.rows || !E.rows.length) {
      return headHtml({ kind: 'square-red', title: t('esc.title'), sub: t('esc.sub'), subInline: false, tools: '' }) +
        '<div class="esc-empty">' + esc(t('esc.empty')) + '</div>';
    }

    var tools = '<span class="text-[12px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">' +
        esc(tf('esc.count', { n: E.rows.length, lv: (E.levels || []).length })) + '</span>' +
      /* 「放大查看」：中列只有 394~582px，6 列表格必须横向滚动才看得全邮箱。
         弹窗里表格按全宽放大、6 列全部单行 —— 位置仍按需求留在地图正下方。 */
      '<button type="button" class="btn-soft" data-act="esc-expand" title="' + esc(t('esc.expandTip')) + '">' +
        ico('expand', 'text-[13px]') + '<span>' + esc(t('esc.expand')) + '</span></button>';

    return headHtml({
      kind: 'square-red', title: t('esc.title'), sub: t('esc.sub'), subInline: false, tools: tools
    }) +
      escTableHtml(false) +
      '<p class="esc-note">' + esc(t('esc.srcNote')) + '</p>';
  }

  /* 「放大查看」弹窗：骨架在 index.html 的 EscalationModal，内容每次打开时重建
     （表体是静态数据，没有异步，不需要像 QC 那样维护加载态）。 */
  function openEscModal() {
    var mask = document.getElementById('escMask');
    var host = document.getElementById('escModalBody');
    if (!mask || !host) return;
    host.innerHTML = escLegendHtml() + escTableHtml(true) +
      '<p class="esc-note">' + esc(t('esc.srcNote')) + '</p>';
    mask.hidden = false;
  }

  function closeEscModal() {
    var mask = document.getElementById('escMask');
    if (mask) mask.hidden = true;
  }


  function renderMapTabs() {
    var host = document.getElementById('mapTabs');
    if (!host) return;
    /* whitespace-nowrap：中列窄，中文页签名（"GIS 地图"/"告警实时"）会被挤成两行，
       行高不定还把页签栏撑高。禁止换行，宁可让文字稍长也不折行。 */
    host.innerHTML = mapItems().map(function (m) {
      var on = state.mapTab === m.page;
      return '<button type="button" role="tab" aria-selected="' + on + '" data-page="' + esc(m.page) + '" title="' + esc(m.title) + '" ' +
        'class="px-2.5 py-1 rounded transition flex items-center gap-1 whitespace-nowrap ' +
        (on ? 'bg-white text-slate-800 font-medium shadow-sm' : 'text-slate-600 hover:text-slate-900') + '">' +
        esc(t(m.key)) + (m.item && m.item.status === 'beta' ? '<span class="text-amber-500">β</span>' : '') + '</button>';
    }).join('');
  }

  /** 加载遮罩：当前页签的 iframe 真正加载完成才隐藏 */
  function syncMapBoot() {
    var boot = document.getElementById('mapBoot');
    if (!boot) return;
    // 未登录时地图区交给 #mapAuth 接管，遮罩必须让位（否则会盖在提示上面）
    if (state.authOk === false) { boot.hidden = true; return; }
    var active = document.getElementById('mapFrame-' + state.mapTab);
    boot.hidden = !!(active && active.getAttribute('src') && active.dataset.loaded === '1');
  }

  /** 未登录提示卡片。prefix 决定按钮 id（mapAuth* / gate*），其余参数是 i18n key。 */
  function authCardHtml(prefix, titleKey, tipKey, loginKey, retryKey) {
    return '<div class="map-auth-card">' +
        '<div class="map-auth-ico">' + ico('key', 'text-[22px]') + '</div>' +
        '<div class="map-auth-title">' + esc(t(titleKey)) + '</div>' +
        '<p class="map-auth-tip">' + esc(t(tipKey)) + '</p>' +
        '<div class="map-auth-actions">' +
          '<button type="button" class="map-auth-btn is-primary" id="' + prefix + 'Login" data-auth-act="login">' +
            ico('key', 'text-[14px]') + '<span>' + esc(t(loginKey)) + '</span></button>' +
          '<a class="map-auth-btn" href="/uniplam/" target="_blank" rel="noopener noreferrer">' +
            ico('external', 'text-[14px]') + '<span>' + esc(t('auth.portal')) + '</span></a>' +
          '<button type="button" class="map-auth-btn" id="' + prefix + 'Retry" data-auth-act="retry">' +
            ico('refresh', 'text-[14px]') + '<span>' + esc(t(retryKey)) + '</span></button>' +
        '</div>' +
      '</div>';
  }

  /** 地图数据在 my_app 侧要登录。未登录时不加载 iframe，只给一句提示 + 登录入口，
      避免 4 个 iframe 各自去渲染 my_app 自带的「Sign in required」英文报错页。 */
  function renderMapAuth() {
    var host = document.getElementById('mapHost');
    if (!host) return;
    var el = document.getElementById('mapAuth');
    if (!el) {
      el = document.createElement('div');
      el.id = 'mapAuth';
      host.appendChild(el);
    }
    el.innerHTML = authCardHtml('mapAuth', 'map.auth.title', 'map.auth.tip', 'map.auth.login', 'map.auth.retry');
  }

  function clearMapAuth() {
    var el = document.getElementById('mapAuth');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function renderMapNoAccess() {
    var host = document.getElementById('mapHost');
    if (!host) return;
    var el = document.getElementById('mapAuth');
    if (!el) {
      el = document.createElement('div');
      el.id = 'mapAuth';
      host.appendChild(el);
    }
    el.innerHTML = '<div class="map-auth-card">' +
      '<div class="map-auth-ico">' + ico('shield', 'text-[22px]') + '</div>' +
      '<div class="map-auth-title">' + esc(t('auth.noMap')) + '</div>' +
      '</div>';
  }

  /** 整页门禁：未登录（或登录态还没探完）时只留 #secGate，
      看板目录 / 统计 / 筛选栏一律不出 —— 否则未登录访客能看到整份看板清单。
      想回到「门户骨架对访客可见」的原行为，把 REQUIRE_LOGIN_FOR_CATALOG 改 false。 */
  function applyGate() {
    var mainEl = document.querySelector('main');
    var gate = document.getElementById('secGate');
    var bar = document.querySelector('.control-bar');
    var gated = REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true;

    if (mainEl) mainEl.classList.toggle('is-gated', gated);
    if (bar) bar.hidden = gated;
    if (!gate) return;

    gate.hidden = !gated;
    if (!gated) { gate.innerHTML = ''; return; }

    // 还在探会话：先给个转圈，别让目录闪一下再被换掉
    if (state.authOk === null) {
      gate.innerHTML =
        '<div class="map-auth-card">' +
          '<div class="map-auth-ico">' +
            '<span class="w-4 h-4 rounded-full border-2 border-slate-300 border-t-blue-600 animate-spin"></span>' +
          '</div>' +
          '<div class="map-auth-title">' + esc(t('auth.checking')) + '</div>' +
        '</div>';
      return;
    }
    gate.innerHTML = authCardHtml('gate', 'auth.title', 'auth.tip', 'auth.login', 'auth.retry');
  }

  /** 门户登录态在 localStorage 的键，三处必须一致：
      uniplam 门户 src/auth/AuthContext.tsx、my_app frontend/src/api.ts、这里。
      门户挂在同一个 origin（http://<host>/uniplam/），所以本页能直接读到它的 token。 */
  var PORTAL_TOKEN_KEY = 'liberia_noc_auth_v1';

  function readPortalToken() {
    try { return localStorage.getItem(PORTAL_TOKEN_KEY) || null; } catch (e) { return null; }
  }

  function writePortalToken(token) {
    try { localStorage.setItem(PORTAL_TOKEN_KEY, token); } catch (e) { /* ignore */ }
  }

  function removePortalToken() {
    try { localStorage.removeItem(PORTAL_TOKEN_KEY); } catch (e) { /* ignore */ }
  }

  function openLogin() {
    var mask = document.getElementById('loginMask');
    var error = document.getElementById('loginError');
    if (error) { error.hidden = true; error.textContent = ''; }
    if (mask) mask.hidden = false;
    setTimeout(function () {
      var input = document.getElementById('loginUsername');
      if (input) input.focus();
    }, 30);
  }

  function closeLogin() {
    var mask = document.getElementById('loginMask');
    if (mask) mask.hidden = true;
  }

  function loginErrorText(err) {
    var code = err && err.code;
    if (code === 'credentials') return t('auth.badCredentials');
    if (code === 'locked') return t('auth.locked');
    if (code === 'network') return t('auth.networkError');
    return (err && err.message) || t('auth.networkError');
  }

  /** 用门户 token 换 myapp 会话 Cookie（对齐 my_app 前端的 bootstrapAuth）。 */
  function exchangePortalToken(token) {
    return fetch('/api/auth/portal-login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: token })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        return { ok: r.ok, user: data.user || null, detail: data.detail || '' };
      });
    }).catch(function () { return { ok: false, user: null, detail: '' }; });
  }

  /** MsPortal 直接调用 uniplam 的登录接口：密码校验、限流、SQLite/JSON 数据库和权限
      全部复用 server/auth.ts，不在静态页面复制一套用户表。 */
  function directLogin(username, password) {
    var submit = document.getElementById('loginSubmit');
    var error = document.getElementById('loginError');
    if (submit) { submit.disabled = true; submit.textContent = t('auth.loggingIn'); }
    if (error) { error.hidden = true; error.textContent = ''; }
    return fetch('/uniplam/api/auth/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: username, password: password })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok || !data.token || !data.user) {
          var e = new Error(data.detail || 'login failed');
          e.code = r.status === 429 ? 'locked' : (r.status === 401 ? 'credentials' : 'network');
          throw e;
        }
        writePortalToken(data.token);
        state.authUser = data.user;
        /* 与 uniplam App 的强制改密行为保持一致：先回统一门户完成改密，
           不在这里把 mustChangePassword 账号直接放进 myapp。 */
        if (data.user.mustChangePassword) {
          closeLogin();
          window.location.href = '/uniplam/';
          return null;
        }
        return exchangePortalToken(data.token).then(function (swapped) {
          if (!swapped.ok) {
            var e2 = new Error(t('auth.networkError'));
            e2.code = 'network';
            throw e2;
          }
          closeLogin();
          state.authOk = null;
          render();
        });
      });
    }).catch(function (err) {
      if (error) { error.textContent = loginErrorText(err); error.hidden = false; }
      throw err;
    }).finally(function () {
      if (submit) { submit.disabled = false; submit.textContent = t('auth.submit'); }
    });
  }

  function portalUserFromToken(token) {
    if (!token) return Promise.resolve(null);
    return fetch('/uniplam/api/auth/me', {
      credentials: 'same-origin', headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' }
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { return data && data.user ? data.user : null; })
      .catch(function () { return null; });
  }

  function logout() {
    var token = readPortalToken();
    var requests = [fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {})];
    if (token) requests.push(fetch('/uniplam/api/auth/logout', {
      method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' }
    }).catch(function () {}));
    Promise.all(requests).then(function () {
      removePortalToken();
      state.authUser = null;
      state.authOk = null;
      state.catalog = null;
      state.catalogLoaded = false;
      state.editing = false;
      render();
    });
  }

  function syncAuthUi() {
    var badge = document.getElementById('authUserBadge');
    var out = document.getElementById('logoutBtn');
    var user = state.authUser;
    var name = user && (user.username || user.id);
    if (badge) { badge.hidden = !name; badge.textContent = name ? String(name) : ''; }
    if (out) out.hidden = !name;
  }

  /** 探一次 my_app 会话；若只有统一门户 token，则先换成 myapp_session Cookie。 */
  function probeSession() {
    if (authProbeBusy) return;
    authProbeBusy = true;
    var done = function (ok, me) {
      authProbeBusy = false;
      state.authOk = ok;
      if (me) state.authUser = me;
      render();
      if (ok) fetchQcStats();
    };
    var askMe = function () {
      return fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { return data && data.user ? data.user : null; })
        .catch(function () { return null; });
    };
    askMe().then(function (me) {
      var token = readPortalToken();
      if (me) {
        if (!token) { done(true, me); return; }
        portalUserFromToken(token).then(function (portalUser) { done(true, portalUser || me); });
        return;
      }
      if (!token) { done(false, null); return; }
      exchangePortalToken(token).then(function (swapped) {
        if (!swapped.ok) { done(false, null); return; }
        askMe().then(function (next) { done(!!next, next); });
      });
    });
  }

  /** 按需创建 iframe；已加载的页签切走不销毁，切回即时显示（不重复请求） */
  function ensureMap() {
    var host = document.getElementById('mapHost');
    if (!host) return;

    // 先定登录态，再决定要不要建 iframe
    if (state.authOk === null) {
      clearMapAuth();
      syncMapBoot();
      probeSession();
      return;
    }
    if (state.authOk === false) {
      renderMapAuth();
      syncMapBoot();
      // 「新窗口」按钮此时还没被赋过 href，保持 # 会让页面跳到顶部
      var na = mapItems().filter(function (m) { return m.page === state.mapTab; })[0];
      var nopen = document.getElementById('mapOpen');
      if (na && nopen) nopen.href = na.src;
      return;
    }
    clearMapAuth();

    var items = mapItems();
    if (!items.length) {
      renderMapNoAccess();
      syncMapBoot();
      return;
    }
    clearMapAuth();

    items.forEach(function (m) {
      var f = document.getElementById('mapFrame-' + m.page);
      if (!f) {
        f = document.createElement('iframe');
        f.id = 'mapFrame-' + m.page;
        f.setAttribute('title', m.title);
        f.setAttribute('loading', 'lazy');
        // 未设 src 的 iframe 会先加载 about:blank 并触发 load，
        // 必须用「是否已设 src」区分，否则遮罩会被提前隐藏
        f.addEventListener('load', function () {
          if (!f.getAttribute('src')) return;
          f.dataset.loaded = '1';
          stripFrame(f);
          // React 首屏挂载后 DOM 还会变，稍后再确认一次
          setTimeout(function () { stripFrame(f); }, 900);
          setTimeout(function () { stripFrame(f); }, 2600);
          syncMapBoot();
        });
        host.appendChild(f);
      }
      var on = state.mapTab === m.page;
      f.className = 'absolute inset-0 w-full h-full border-0' + (on ? '' : ' hidden');
      // 抵消一次整页 zoom，地图不会随字号放大被撑出容器（见 syncMapZoom）
      f.style.zoom = String(1 / fontFactor());
      if (on && !f.getAttribute('src')) {
        delete f.dataset.loaded;
        f.setAttribute('src', m.src);
      }
      if (on && f.getAttribute('src') && f.dataset.loaded === '1') stripFrame(f);
    });

    var cur = items.filter(function (m) { return m.page === state.mapTab; })[0];
    var open = document.getElementById('mapOpen');
    if (cur && open) open.href = cur.src;
    syncMapBoot();
  }

  function bindMap() {
    var tabs = document.getElementById('mapTabs');
    if (tabs) {
      tabs.addEventListener('click', function (e) {
        var b = e.target.closest('[data-page]');
        if (!b) return;
        state.mapTab = b.getAttribute('data-page');
        writeLS(LS.mapTab, state.mapTab);
        renderMapTabs();
        ensureMap();
      });
    }

    var rf = document.getElementById('mapRefresh');
    if (rf) rf.addEventListener('click', function () {
      var f = document.getElementById('mapFrame-' + state.mapTab);
      var boot = document.getElementById('mapBoot');
      if (boot) boot.hidden = false;
      if (!f) { ensureMap(); return; }
      delete f.dataset.loaded;
      try { f.contentWindow.location.reload(); }
      catch (err) {
        var m = mapItems().filter(function (x) { return x.page === state.mapTab; })[0];
        if (m) f.setAttribute('src', m.src);
      }
    });
  }

  /* --------------------------------------------------------- 字号放缩 UI -- */
  /* 按钮放在「编辑分组归属」旁边（manageBtn 之前），并在 render() 里随编辑模式一起显隐。
     用 −/+ 两个按钮而不是滑杆：控制栏在窄屏会换行，滑杆宽度不好控。 */
  function buildFontBtns() {
    if (document.getElementById('fontMinus')) return;
    var host = document.querySelector('.control-actions');
    if (!host) return;
    var ref = document.getElementById('manageBtn');
    var html =
      '<button type="button" class="btn-soft" id="fontMinus" data-i18n-title="btn.aMinus">' +
        '<span class="font-mono font-bold">A−</span></button>' +
      '<button type="button" class="btn-soft" id="fontPlus" data-i18n-title="btn.aPlus">' +
        '<span class="font-mono font-bold">A+</span></button>';
    if (ref) ref.insertAdjacentHTML('beforebegin', html);
    else host.insertAdjacentHTML('afterbegin', html);
  }

  /** 到了步进区间两端就禁用，避免按了没反应还以为是坏了 */
  function syncFontBtns() {
    var minus = document.getElementById('fontMinus');
    var plus = document.getElementById('fontPlus');
    if (!minus || !plus) return;
    var editing = !!state.editing;
    [minus, plus].forEach(function (b) {
      b.hidden = !editing;
      b.classList.toggle('is-on', fontStep !== 0);
    });
    minus.disabled = fontStep <= FONT_STEPS[0];
    plus.disabled = fontStep >= FONT_STEPS[FONT_STEPS.length - 1];
    minus.style.opacity = minus.disabled ? '.45' : '';
    plus.style.opacity = plus.disabled ? '.45' : '';
    minus.style.cursor = minus.disabled ? 'not-allowed' : 'pointer';
    plus.style.cursor = plus.disabled ? 'not-allowed' : 'pointer';
    var label = fontStep === 0 ? '100%' : Math.round(fontFactor() * 100) + '%';
    minus.title = t('btn.aMinus') + '  ·  ' + label;
    plus.title = t('btn.aPlus') + '  ·  ' + label;
  }

  /* ------------------------------------------------- 顶栏控制条折叠（2026-09-17 加） --
     用户要求：搜索 / 筛选那一整行默认收起，点击才展开。
     —— 不落 localStorage：默认收起是版式的一部分，持久化会让"打开过一次"
        变成新默认，等于没折叠（同 state.secQuery / secExpanded 的理由）。
     —— 折叠态下把「当前生效的搜索词 / 筛选」回显在按钮里：否则用户看到
        "怎么只剩 3 个看板"却找不到原因（chip 和搜索框都被收起来了）。 */
  function setBarOpen(open) {
    state.barOpen = !!open;
    var bar = document.getElementById('controlBar');
    var btn = document.getElementById('controlToggle');
    if (bar) bar.classList.toggle('is-collapsed', !state.barOpen);
    if (btn) btn.setAttribute('aria-expanded', state.barOpen ? 'true' : 'false');
    syncBarSummary();
  }

  /** 折叠时在开关按钮里回显当前筛选条件；展开时清空（用户已经能直接看到） */
  function syncBarSummary() {
    var el = document.getElementById('barSummary');
    if (!el) return;
    if (state.barOpen) { el.hidden = true; el.textContent = ''; return; }
    var parts = [];
    if (state.query) parts.push('“' + state.query + '”');
    if (state.filter !== 'all') {
      var g = allGroups().filter(function (x) { return x.id === state.filter; })[0];
      var qc = (DATA.qc || []).filter(function (x) { return x.id === state.filter; })[0];
      parts.push(g ? groupLabel(g) : (qc ? (state.lang === 'en' ? qc.en : qc.zh) : state.filter));
    }
    if (parts.length) parts.push(filtered().length + ' ' + t('sec.count'));
    el.textContent = parts.join('  ·  ');
    el.hidden = !parts.length;
  }

  /* ------------------------------------------------------------- chips -- */
  function chipHtml() {
    var counts = {};
    var visible = visibleCatalogItems();
    visible.forEach(function (it) {
      groupsOf(it).forEach(function (g) { counts[g] = (counts[g] || 0) + 1; });
    });
    var list = [{ id: 'all', label: t('chip.all'), n: visible.length }];
    allGroups().forEach(function (g) {
      if (counts[g.id]) list.push({ id: g.id, label: groupLabel(g), n: counts[g.id] });
    });
    DATA.qc.forEach(function (q) {
      list.push({ id: q.id, label: state.lang === 'en' ? q.en : q.zh, n: (q.ids || []).length });
    });

    document.getElementById('filterChips').innerHTML = list.map(function (c) {
      var on = state.filter === c.id;
      return '<button type="button" data-act="filter" data-filter="' + esc(c.id) + '" ' +
        'class="px-3 py-1.5 rounded-full text-[13px] border transition ' +
        (on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-200 hover:border-blue-400 hover:text-blue-600') + '">' +
        esc(c.label) + ' <span class="font-mono opacity-70">' + c.n + '</span></button>';
    }).join('');
  }

  /* -------------------------------------------------------------- render -- */
  var SLOT = {
    'MS View': 'secMs', 'FLM View': 'secFlm', 'SP View': 'secSp', 'FO View': 'secFo',
    'BO View': 'secBo', 'System Admin': 'secAdmin',
    'Knowledge Q&A': 'secQa', 'Friends Link': 'secFriends'
  };

  function render() {
    document.documentElement.setAttribute('lang', state.lang === 'en' ? 'en' : 'zh-CN');
    document.documentElement.classList.toggle('dark', state.theme === 'dark');
    document.body.classList.toggle('editing', state.editing);

    // 字号放缩：每次 render 都重算（末尾 buildFontBtns 会更新按钮的可用状态）
    applyFontScale();

    document.querySelectorAll('[data-lang]').forEach(function (b) {
      b.classList.toggle('is-active', b.getAttribute('data-lang') === state.lang);
    });
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    document.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      el.getAttribute('data-i18n-attr').split(',').forEach(function (pair) {
        var kv = pair.split(':');
        if (kv.length === 2) el.setAttribute(kv[0].trim(), t(kv[1].trim()));
      });
    });
    syncAuthUi();
    /* 下钻弹窗里除 data-i18n 覆盖的静态文案外，标题/计数/页码都是本文件动态写入的，
       切语言不会自动跟着变 —— 弹窗开着就重刷一遍（静态文案由上面的 data-i18n 循环处理）。 */
    if (state.qcDrill.metric) { applyQcDrillTitle(); renderQcDrill(); }
    /* 升级机制弹窗的表体也是本文件动态写入的（含职级说明、人数单位），
       弹窗开着时切语言要跟着重建 —— 静态文案（标题/脚注）由上面的 data-i18n 循环处理。 */
    var escMaskEl = document.getElementById('escMask');
    if (escMaskEl && !escMaskEl.hidden) openEscModal();

    var eb = document.getElementById('editBtn');
    eb.querySelector('span').textContent = state.editing ? t('btn.editGroupsOn') : t('btn.editGroups');
    eb.classList.toggle('is-on', state.editing);
    ['manageBtn', 'exportBtn', 'importBtn', 'resetBtn'].forEach(function (id) {
      document.getElementById(id).hidden = !state.editing;
    });
    /* 「新增看板 / 恢复出厂目录」还要看服务端写权限：非服务器本机只读（见 syncCatalogBtns） */
    syncCatalogBtns();
    /* 必须在上面那个循环**之后**调用：那个循环会把 fontMinus/fontPlus 的 disabled 清掉
       （它们也在 .control-actions 里、也不是 button[disabled] 特殊选择器），
       顺序反了就会出现「A− 已经是 0% 下限却仍然可点」的假可用状态。 */
    syncFontBtns();
    document.getElementById('editHint').hidden = !state.editing;

    chipHtml();
    /* 控制条折叠态下要回显「当前生效的搜索词 / 筛选」——
       筛选或搜索一变就得同步，否则折叠着的按钮里还写着上一轮的旧条件。 */
    syncBarSummary();

    // 未登录门禁：门禁生效时不再渲染任何看板区块（目录/链接/统计都不能漏出去）
    applyGate();
    if (REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true) {
      // 清掉可能残留的旧内容，避免只是被 CSS 藏起来
      ['secCxo', 'secQc', 'secTopo', 'secEsc', 'secMs', 'secFlm', 'secSp', 'secFo', 'secBo',
       'secAdmin', 'secQa', 'secFriends', 'secExtra'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = '';
      });
      // 这条路径不会走到 ensureMap()，登录态得在这里探
      if (state.authOk === null) probeSession();
      return;
    }

    renderSections();
    /* 服务端全局看板目录：登录态确认后才拉（未登录时接口 401，拉了也没意义），
       只拉一次。拉到后 loadCatalog() 内部会再 render 一遍把目录换掉。 */
    if (state.authOk === true && !state.catalogLoaded) {
      state.catalogLoaded = true;
      loadCatalog();
    }
    /* 拓扑区只在 render() 里建，且**必须在 renderSections() 之后**：
       topoSection() 会重置 #mapHost 的内容（4 个 iframe 的家），
       如果先建拓扑再跑 renderSections，虽然后者不碰 secTopo、看起来也一样，
       但一旦以后有人给 renderSections 加了 secTopo 就会互相覆盖 —— 明确分开职责。 */
    document.getElementById('secTopo').innerHTML = topoSection();
    renderMapTabs();
    ensureMap();
    /* 升级机制表格：与地图同理只在 render() 里建一次（不放进 renderSections()）。
       它是静态参考信息，不参与搜索/筛选/折叠，重建代价虽小但没必要跟着每次
       区块搜索一起重画 —— 而且放这里可以保证「未登录门禁」那条 return 之前
       不会被单独渲染出来（门禁分支已把 secEsc 一起清空）。 */
    var escEl = document.getElementById('secEsc');
    if (escEl) escEl.innerHTML = escSection();
  }

  /** 只重画看板区块（不动地图）。区块内搜索每次输入都走这里 ——
      render() 会顺带跑 ensureMap()，而 ensureMap 对当前页签 iframe 会再 stripFrame
      一遍，连续打字就等于连续打扰地图（见 bind() 里区块搜索的注释）。
      刻意**不重画拓扑区**：它是 4 个 iframe 的宿主，重建 = 地图重新加载几十秒。 */
  function renderSections() {
    // 特殊区块：CXO / Quality Control / 拓扑地图（拓扑区只在 render() 里建一次，
    // 这里必须跳过 —— 重建 #secTopo 会让 4 个地图 iframe 全部重新加载）
    document.getElementById('secCxo').innerHTML = cxoSection();
    document.getElementById('secQc').innerHTML = qcSection();

    // 其余分组区块
    var bySlot = {}, extra = [];
    allGroups().filter(function (g) { return canRenderGroup(g.id); }).forEach(function (g) {
      if (g.id === 'CXO View') return;   // 已由 cxoSection() 专用渲染
      var html = sectionHtml(g, sectionItems(g.id));
      if (SLOT[g.id]) bySlot[SLOT[g.id]] = html; else extra.push(html);
    });
    Object.keys(SLOT).forEach(function (k) {
      var el = document.getElementById(SLOT[k]);
      if (el) el.innerHTML = bySlot[SLOT[k]] || '';
    });
    document.getElementById('secExtra').innerHTML = extra.map(function (h) {
      return '<section class="bg-white rounded-xl p-4 lg:p-5 shadow-card border border-slate-200/80">' + h + '</section>';
    }).join('');
  }

  /* ------------------------------------------------------------- actions -- */
  function toast(msg) {
    var el = document.getElementById('toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.hidden = true; }, 2200);
  }

  function findItem(no) {
    return catalogItems().filter(function (it) { return String(it.no) === String(no); })[0];
  }

  /* ---------------------------------------------- 看板新增 / 编辑弹窗 -- */
  /* 2026-09-17 加，参考 uniplam 的 DashboardModal：一个弹窗同时承担「新增」与「编辑」，
     字段与 data.js 的看板对象一一对应。

     ⚠️ 表单里编辑的是**源数据（中文规范值）**，不做 i18n 翻译 —— 否则在英文界面
     保存一次就把英文写回目录，而标题/描述没有反向映射，中文界面从此再也看不到
     原中文（uniplam 在 DashboardModal 的 useEffect 里踩过这个坑，特意留了注释）。 */

  var BOARD_PLATFORMS = ['myapp', 'finebi', 'external'];
  var BOARD_STATUSES = ['online', 'beta'];
  /* 图标下拉：PH 映射表里的键，按固定顺序展示（含当前 51 个看板用到的全部图标） */
  var BOARD_ICONS = ['dashboard', 'chart-line', 'table', 'archive', 'chat', 'book', 'gear',
    'key', 'warning', 'briefcase', 'git', 'user', 'eye', 'flame', 'shield', 'refresh',
    'external', 'map-pin', 'buildings', 'folder', 'check-circle', 'arrow-up', 'arrows-lr'];

  function bf(id) { return document.getElementById(id); }

  /** 新增看板的编号：内置最大号 + 1（no 是分组覆盖与卡片锚点的键，必须唯一且稳定） */
  function nextBoardNo() {
    var max = 0;
    catalogItems().forEach(function (it) {
      var n = parseInt(it.no, 10);
      if (!isNaN(n) && n > max) max = n;
    });
    return max + 1;
  }

  function openBoardForm(no) {
    state.boardNo = (no == null || no === '') ? null : String(no);
    fillBoardForm(state.boardNo ? findItem(state.boardNo) : null);
    bf('boardMask').hidden = false;
    setTimeout(function () { var el = bf('bfTitleZh'); if (el) el.focus(); }, 30);
  }

  function closeBoardForm() {
    bf('boardMask').hidden = true;
    state.boardNo = null;
  }

  /** 填充表单。item=null → 新增模式。 */
  function fillBoardForm(item) {
    bf('boardTitle').textContent = t(item ? 'board.editTitle' : 'board.addTitle');

    // select 的 option 文本随语言重建（data-i18n 只管静态文案，option 得自己来）
    bf('bfPlatform').innerHTML = BOARD_PLATFORMS.map(function (p) {
      return '<option value="' + p + '">' + esc(t('plat.' + p)) + '</option>';
    }).join('');
    bf('bfStatus').innerHTML = BOARD_STATUSES.map(function (s) {
      return '<option value="' + s + '">' + esc(t('status.' + s)) + '</option>';
    }).join('');
    bf('bfIcon').innerHTML = BOARD_ICONS.map(function (k) {
      return '<option value="' + k + '">' + esc(k) + '</option>';
    }).join('');

    // 分组多选：当前全部分组（内置 + 自建 + 改名后的显示名）
    var cur = item ? groupsOf(item) : [];
    bf('bfGroups').innerHTML = allGroups().map(function (g) {
      var on = cur.indexOf(g.id) !== -1;
      return '<label class="bf-group' + (on ? ' is-on' : '') + '">' +
        '<input type="checkbox" value="' + esc(g.id) + '"' + (on ? ' checked' : '') + '>' +
        '<span>' + esc(groupLabel(g)) + '</span></label>';
    }).join('');

    bf('bfTitleZh').value = item ? (item.titleZh || '') : '';
    bf('bfTitleEn').value = item ? (item.titleEn || '') : '';
    bf('bfUrl').value = item ? (item.url || '') : '';
    bf('bfDescZh').value = item ? (item.descZh || '') : '';
    bf('bfDescEn').value = item ? (item.descEn || '') : '';
    bf('bfPlatform').value = item ? (item.platform || 'myapp') : 'myapp';
    bf('bfStatus').value = item ? (item.status || 'online') : 'online';
    bf('bfOwner').value = item ? (item.owner || '') : '';
    bf('bfOwnerEn').value = item ? (item.ownerEn || '') : '';
    bf('bfDept').value = item ? (item.dept || '') : '';
    bf('bfDeptEn').value = item ? (item.deptEn || '') : '';
    bf('bfFreq').value = item ? (item.freq || '') : '';
    bf('bfClicks').value = String(item ? (item.clicks || 0) : 0);
    bf('bfTags').value = item ? (item.tags || []).join(', ') : '';
    bf('bfIcon').value = (item && BOARD_ICONS.indexOf(item.icon) !== -1) ? item.icon : 'dashboard';

    bf('boardNote').textContent = state.catalogSource === 'local' ? t('board.localNote') : t('board.serverNote');
  }

  /** 从表单收集并校验。返回 {item} 或 {error}。 */
  function collectBoardForm() {
    var titleZh = bf('bfTitleZh').value.trim();
    var titleEn = bf('bfTitleEn').value.trim();
    var url = bf('bfUrl').value.trim();
    if (!titleZh && !titleEn) return { error: t('board.errTitle') };
    if (!/^https?:\/\//i.test(url)) return { error: t('board.errUrl') };
    var groups = Array.prototype.slice.call(bf('bfGroups').querySelectorAll('input:checked'))
      .map(function (i) { return i.value; });
    /* 至少一个分组是硬性要求：看板只按分组渲染，没有分组的卡片不会出现在任何区块，
       用户会以为「加上了但看不见」。（后端不做这个校验，保持宽容。） */
    if (!groups.length) return { error: t('board.errGroups') };

    var base = state.boardNo ? findItem(state.boardNo) : null;
    var tags = bf('bfTags').value.split(/[,，]/).map(function (s) { return s.trim(); })
      .filter(function (s) { return s; });
    var item = {
      // 编辑保留原 no；新增取最大号 + 1
      no: base ? base.no : nextBoardNo(),
      groups: groups,
      titleZh: titleZh,
      titleEn: titleEn || titleZh,
      descZh: bf('bfDescZh').value.trim(),
      descEn: bf('bfDescEn').value.trim(),
      platform: bf('bfPlatform').value,
      url: url,
      tags: tags,
      owner: bf('bfOwner').value.trim(),
      ownerEn: bf('bfOwnerEn').value.trim() || bf('bfOwner').value.trim(),
      dept: bf('bfDept').value.trim(),
      deptEn: bf('bfDeptEn').value.trim() || bf('bfDept').value.trim(),
      status: bf('bfStatus').value,
      freq: bf('bfFreq').value.trim(),
      clicks: Math.max(0, parseInt(bf('bfClicks').value, 10) || 0),
      icon: bf('bfIcon').value
    };
    // 表单里没有的字段原样保留（QC 关联、BO 子分组、新上线标记）
    if (base) {
      if (base.qc) item.qc = base.qc.slice();
      if (base.boSub) item.boSub = base.boSub;
      if (base.isNew) item.isNew = base.isNew;
      if (base.custom) item.custom = true;
    } else {
      item.custom = true;
    }
    return { item: item };
  }

  function saveBoardForm() {
    var r = collectBoardForm();
    if (r.error) { toast(r.error); return; }
    var items = catalogItems().slice();
    var isNew = !state.boardNo;
    var no = r.item.no;
    if (isNew) {
      items.unshift(r.item);
    } else {
      var idx = -1;
      items.forEach(function (x, i) { if (String(x.no) === String(no)) idx = i; });
      if (idx < 0) { closeBoardForm(); return; }
      items[idx] = r.item;
    }
    /* 分组归属若被「编辑分组归属」覆盖过（state.assign），会压住目录里的 groups ——
       用户在弹窗里改了分组却看不到变化。这里清掉该看板的本机覆盖，让目录值生效
       （此刻用户的意图就是改分组）。 */
    state.assign = state.assign || {};
    if (Object.prototype.hasOwnProperty.call(state.assign, String(no))) {
      delete state.assign[String(no)];
      writeJSON(LS.assign, state.assign);
    }
    closeBoardForm();
    // 高亮放在保存完成之后：PUT 回来还会再 render 一次，提前高亮会被那次重绘抹掉
    saveCatalog(items, isNew ? t('board.added') : t('board.saved')).then(function () {
      highlightBoard(no);
    });
  }

  function deleteBoard(no) {
    var it = findItem(no);
    if (!it) return;
    if (!window.confirm(t('board.confirmDel').replace('{name}', titleOf(it)))) return;
    var items = catalogItems().filter(function (x) { return String(x.no) !== String(no); });
    state.assign = state.assign || {};
    if (Object.prototype.hasOwnProperty.call(state.assign, String(no))) {
      delete state.assign[String(no)];
      writeJSON(LS.assign, state.assign);
    }
    saveCatalog(items, t('board.deleted'));
  }

  function closeMenu() {
    var m = document.querySelector('.g-menu');
    if (m) m.remove();
  }

  /** 按档步进整页字号。**不用重新 render**：字号只靠 html.style / body.style 生效，
      重建 DOM 反而会闪、还会把地图 iframe 重新加载一遍（几十秒）。 */
  function stepFont(dir) {
    var i = FONT_STEPS.indexOf(fontStep);
    if (i === -1) i = FONT_STEPS.indexOf(0);
    var next = FONT_STEPS[Math.max(0, Math.min(FONT_STEPS.length - 1, i + dir))];
    if (next === fontStep) return;
    fontStep = next;
    writeLS(LS.fontStep, String(fontStep));
    applyFontScale();
    syncFontBtns();
    syncMapZoom();
    toast(t('toast.fontScale').replace('{p}', String(Math.round(fontFactor() * 100))));
  }

  function openAssignMenu(btn, item) {
    closeMenu();
    var mine = groupsOf(item);
    var menu = document.createElement('div');
    menu.className = 'g-menu';
    menu.innerHTML = allGroups().map(function (g) {
      return '<button type="button" data-pick="' + esc(g.id) + '">' + esc(groupLabel(g)) +
        (mine.indexOf(g.id) !== -1 ? '<span class="mark">✓</span>' : '') + '</button>';
    }).join('');
    document.body.appendChild(menu);
    var r = btn.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - 200)) + 'px';
    menu.style.top = (r.bottom + window.scrollY + 4) + 'px';

    menu.addEventListener('click', function (e) {
      var b = e.target.closest('[data-pick]');
      if (!b) return;
      var gid = b.getAttribute('data-pick');
      var list = groupsOf(item);
      var idx = list.indexOf(gid);
      if (idx === -1) list.push(gid); else list.splice(idx, 1);
      setGroups(item, list);
      closeMenu();
    });
  }

  function isBuiltinGroup(gid) {
    return DATA.groups.some(function (x) { return x.id === gid; });
  }

  function renderGroupTable() {
    document.getElementById('groupTableBody').innerHTML = allGroups().map(function (g) {
      var n = catalogItems().filter(function (it) { return groupsOf(it).indexOf(g.id) !== -1; }).length;
      return '<tr data-gid="' + esc(g.id) + '">' +
        '<td><input type="text" data-field="zh" value="' + esc(g.zh || g.id) + '"></td>' +
        '<td><input type="text" data-field="en" value="' + esc(g.en || g.id) + '"></td>' +
        '<td class="cnt">' + n + '</td>' +
        '<td>' + (isBuiltinGroup(g.id) ? '' : '<button type="button" class="del" data-act="del-group" data-gid="' +
          esc(g.id) + '">' + esc(t('modal.del')) + '</button>') + '</td>' +
      '</tr>';
    }).join('');
  }

  function saveGroupTable() {
    var custom = [], renamed = [];
    document.querySelectorAll('#groupTableBody tr').forEach(function (tr) {
      var gid = tr.getAttribute('data-gid');
      var zh = tr.querySelector('[data-field="zh"]').value.trim();
      var en = tr.querySelector('[data-field="en"]').value.trim();
      var isBuiltin = DATA.groups.some(function (x) { return x.id === gid; });
      if (isBuiltin) {
        var base = DATA.groups.filter(function (x) { return x.id === gid; })[0];
        var o = { id: gid };
        if (zh && zh !== base.zh) o.zh = zh;
        if (en && en !== base.en) o.en = en;
        if (o.zh || o.en) {
          var cur = (state.renames || []).filter(function (r) { return r.id === gid; })[0] || { id: gid };
          if (o.zh) cur.zh = o.zh;
          if (o.en) cur.en = o.en;
          renamed.push(cur);
        }
      } else {
        var old = (state.groups || []).filter(function (g) { return g.id === gid; })[0] || {};
        custom.push({ id: gid, zh: zh || gid, en: en || gid,
                      subZh: old.subZh || '', subEn: old.subEn || '', style: old.style || 'card' });
      }
    });
    state.groups = custom;
    state.renames = renamed;
    writeJSON(LS.groups, custom);
    writeJSON(LS.renames, renamed);
    render();
  }

  function exportCfg() {
    /* catalog 一并导出：目录现在存服务端，但导出一份 JSON 仍是最快的备份/迁移手段
       （拿到别的机器上用「导入 JSON」即可复现同一套目录）。 */
    var blob = new Blob([JSON.stringify({
      assign: state.assign, groups: state.groups, renames: state.renames, lang: state.lang,
      catalog: state.catalog || null
    }, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'msportal-config.json';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 3000);
    toast(t('toast.exported'));
  }

  function importCfg(file) {
    var r = new FileReader();
    r.onload = function () {
      try {
        var o = JSON.parse(String(r.result));
        if (o.assign && typeof o.assign === 'object') { state.assign = o.assign; writeJSON(LS.assign, o.assign); }
        if (Array.isArray(o.groups)) { state.groups = o.groups; writeJSON(LS.groups, o.groups); }
        /* 目录随配置一起导入：写本机兜底并立刻尝试同步到服务端（本机才写得动）。
           直接改 state.catalog 不落 LS 会刷新即丢，所以先落 LS 再发请求。 */
        if (Array.isArray(o.catalog) && o.catalog.length) {
          saveCatalog(o.catalog, t('board.saved'));
        }
        if (Array.isArray(o.renames)) { state.renames = o.renames; writeJSON(LS.renames, o.renames); }
        if (o.lang === 'en' || o.lang === 'zh') { state.lang = o.lang; writeLS(LS.lang, o.lang); }
        render();
        toast(t('toast.imported'));
      } catch (e) { toast(t('toast.importFail')); }
    };
    r.readAsText(file);
  }

  /* ---------------------------------------------------------------- init -- */
  function bind() {
    document.getElementById('themeBtn').addEventListener('click', function () {
      state.theme = state.theme === 'dark' ? 'light' : 'dark';
      writeLS(LS.theme, state.theme);
      render();
    });

    var loginMask = document.getElementById('loginMask');
    var loginForm = document.getElementById('loginForm');
    var loginClose = document.getElementById('loginClose');
    var loginCancel = document.getElementById('loginCancel');
    if (loginClose) loginClose.addEventListener('click', closeLogin);
    if (loginCancel) loginCancel.addEventListener('click', closeLogin);
    if (loginMask) loginMask.addEventListener('click', function (e) { if (e.target === loginMask) closeLogin(); });
    if (loginForm) loginForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var username = document.getElementById('loginUsername').value.trim();
      var password = document.getElementById('loginPassword').value;
      if (username && password) directLogin(username, password).catch(function () {});
    });
    var logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.addEventListener('click', logout);

    document.querySelectorAll('[data-lang]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.lang = b.getAttribute('data-lang');
        writeLS(LS.lang, state.lang);
        render();
      });
    });

    var si = document.getElementById('searchInput');
    si.addEventListener('input', function () {
      state.query = si.value.trim().toLowerCase();
      render();
    });

    /* 区块内搜索（2026-09-17 加）。两件事必须注意：
       1) **走 renderSections() 而不是 render()** —— render() 会调 ensureMap()，
          而 ensureMap 里对已加载的当前页签 iframe 会再跑一次 stripFrame，
          字打快一点就会持续打扰地图；区块内搜索与地图毫无关系，不该碰它。
       2) **不能每次输入都重建 input 本身** —— 那会丢焦点与光标位置。
          renderSections() 会重建整个区块 HTML，所以这里在重建后把焦点与光标
          手动还回去（下面 restoreFocus）。 */
    document.addEventListener('input', function (e) {
      var inp = e.target.closest && e.target.closest('.sec-search-input');
      if (!inp) return;
      var gid = inp.getAttribute('data-sec');
      var q = inp.value.trim().toLowerCase();
      // 与"空字符串"等价时不要反复重绘（否则清空后每按一次删除键都重画）
      if ((state.secQuery[gid] || '') === q) return;
      state.secQuery[gid] = q;
      renderSections();
      var again = document.querySelector('.sec-search-input[data-sec="' + gid.replace(/"/g, '\\"') + '"]');
      if (again) {
        again.focus();
        try { again.setSelectionRange(again.value.length, again.value.length); } catch (err) {}
      }
    });

    /* 清空按钮（type=search 的 ×）在部分浏览器走 search 事件而非 input，
       这里补一发，避免"点了 × 但列表没恢复"。 */
    document.addEventListener('search', function (e) {
      var inp = e.target.closest && e.target.closest('.sec-search-input');
      if (!inp) return;
      var gid = inp.getAttribute('data-sec');
      var q = inp.value.trim().toLowerCase();
      if ((state.secQuery[gid] || '') === q) return;
      state.secQuery[gid] = q;
      renderSections();
    });

    /* ---- 顶栏「搜索与筛选」整行的展开 / 收起（2026-09-17 加） ---- */
    document.getElementById('controlToggle').addEventListener('click', function () {
      setBarOpen(!state.barOpen);
    });
    /* 首屏同步一次：index.html 里已经写成 .is-collapsed（避免展开态闪一下），
       这里把 aria-expanded 与折叠回显对齐。 */
    setBarOpen(state.barOpen);

    document.getElementById('editBtn').addEventListener('click', function () {
      state.editing = !state.editing;
      closeMenu();
      /* 进编辑模式就把控制条展开：编辑用的按钮（新增看板 / 分组管理 / 导出 /
         恢复默认）全在那一行里，收着等于功能"消失"，用户会以为没做。 */
      if (state.editing) setBarOpen(true);
      render();
    });

    /* ---- 看板新增 / 编辑弹窗（骨架见 index.html 的 BoardEditModal） ---- */
    var boardMask = document.getElementById('boardMask');
    document.getElementById('addBoardBtn').addEventListener('click', function () { openBoardForm(null); });
    document.getElementById('boardClose').addEventListener('click', closeBoardForm);
    document.getElementById('boardCancel').addEventListener('click', closeBoardForm);
    document.getElementById('boardSave').addEventListener('click', saveBoardForm);
    boardMask.addEventListener('click', function (e) { if (e.target === boardMask) closeBoardForm(); });
    /* 表单里回车即保存（单行 input 上；textarea 里回车是换行，不该保存） */
    boardMask.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT') {
        e.preventDefault();
        saveBoardForm();
      }
    });
    document.getElementById('boardResetBtn').addEventListener('click', resetCatalog);

    /* 字号 −/+：只在编辑模式显示（syncFontBtns 控制显隐） */
    document.getElementById('fontMinus').addEventListener('click', function () { stepFont(-1); });
    document.getElementById('fontPlus').addEventListener('click', function () { stepFont(1); });

    var mask = document.getElementById('modalMask');
    document.getElementById('manageBtn').addEventListener('click', function () {
      renderGroupTable();
      mask.hidden = false;
    });
    document.getElementById('modalClose').addEventListener('click', function () {
      saveGroupTable(); mask.hidden = true;
    });
    mask.addEventListener('click', function (e) {
      if (e.target === mask) { saveGroupTable(); mask.hidden = true; }
    });

    /* ---- QC 下钻弹窗（骨架见 index.html 的 QcDrillModal） ---- */
    var qcMask = document.getElementById('qcMask');
    var qcSearch = document.getElementById('qcSearch');
    document.getElementById('qcClose').addEventListener('click', closeQcDrill);
    qcMask.addEventListener('click', function (e) { if (e.target === qcMask) closeQcDrill(); });
    document.getElementById('qcReload').addEventListener('click', function () { fetchQcDrill(); });
    document.getElementById('qcExport').addEventListener('click', exportQcCsv);
    document.getElementById('qcPrev').addEventListener('click', function () {
      if (state.qcDrill.page > 1) { state.qcDrill.page--; fetchQcDrill(); }
    });
    document.getElementById('qcNext').addEventListener('click', function () {
      var pages = Math.max(1, Math.ceil(state.qcDrill.total / state.qcDrill.size));
      if (state.qcDrill.page < pages) { state.qcDrill.page++; fetchQcDrill(); }
    });
    /* 搜索防抖 300ms：每敲一个字就打一次库没必要（TT 表 2.8 万行） */
    var qcTimer;
    qcSearch.addEventListener('input', function () {
      clearTimeout(qcTimer);
      qcTimer = setTimeout(function () {
        var v = qcSearch.value.trim();
        if (v === state.qcDrill.q) return;
        state.qcDrill.q = v;
        state.qcDrill.page = 1;
        fetchQcDrill();
      }, 300);
    });
    /* Esc 关闭。只在弹窗真的开着时接管，不影响其它 Esc 行为。 */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (!qcMask.hidden) { closeQcDrill(); return; }
      var em = document.getElementById('escMask');
      if (em && !em.hidden) closeEscModal();
    });

    /* ---- 升级机制「放大查看」弹窗（骨架见 index.html 的 EscalationModal） ----
       打开按钮画在 #secEsc 里，而那个区块每次 render() 都会重建 innerHTML，
       所以走下面那个 document 级事件委托（data-act="esc-expand"），
       这里只绑静态的关闭控件。 */
    var escMask = document.getElementById('escMask');
    if (escMask) {
      document.getElementById('escClose').addEventListener('click', closeEscModal);
      escMask.addEventListener('click', function (e) { if (e.target === escMask) closeEscModal(); });
    }

    document.getElementById('addGroupBtn').addEventListener('click', function () {
      var zh = document.getElementById('newGroupZh').value.trim();
      var en = document.getElementById('newGroupEn').value.trim();
      if (!zh && !en) return;
      var id = (en || zh).trim();
      if (allGroups().some(function (g) { return g.id.toLowerCase() === id.toLowerCase(); })) {
        toast(t('toast.groupAdded')); return;
      }
      state.groups = (state.groups || []).concat([{ id: id, zh: zh || id, en: en || id,
        subZh: '', subEn: '', style: 'card' }]);
      writeJSON(LS.groups, state.groups);
      document.getElementById('newGroupZh').value = '';
      document.getElementById('newGroupEn').value = '';
      renderGroupTable();
      render();
      toast(t('toast.groupAdded'));
    });

    document.getElementById('exportBtn').addEventListener('click', exportCfg);
    document.getElementById('importBtn').addEventListener('click', function () {
      document.getElementById('importFile').click();
    });
    document.getElementById('importFile').addEventListener('change', function () {
      if (this.files && this.files[0]) importCfg(this.files[0]);
      this.value = '';
    });
    document.getElementById('resetBtn').addEventListener('click', function () {
      state.assign = {}; state.groups = []; state.renames = [];
      writeJSON(LS.assign, {}); writeJSON(LS.groups, []); writeJSON(LS.renames, []);
      render();
      toast(t('toast.reset'));
    });

    /* 地图区交互用事件委托绑定（区块 HTML 每次 render 会重建） */
    document.addEventListener('click', function (e) {
      /* 升级机制「放大查看」（按钮在 #secEsc 里，每次 render 会重建，必须走委托） */
      var escBtn = e.target.closest('[data-act="esc-expand"]');
      if (escBtn) {
        e.preventDefault(); e.stopPropagation();
        openEscModal();
        return;
      }

      var menuBtn = e.target.closest('[data-act="assign-menu"]');
      if (menuBtn) {
        e.preventDefault(); e.stopPropagation();
        var it = findItem(menuBtn.getAttribute('data-no'));
        if (it) openAssignMenu(menuBtn, it);
        return;
      }

      var un = e.target.closest('[data-act="unassign"]');
      if (un) {
        e.preventDefault(); e.stopPropagation();
        var item = findItem(un.getAttribute('data-no'));
        if (item) {
          var gid0 = un.getAttribute('data-gid');
          setGroups(item, groupsOf(item).filter(function (g) { return g !== gid0; }));
        }
        return;
      }

      /* 看板本身的编辑 / 删除（仅服务端可写时按钮才渲染出来，见 assignHtml） */
      var be = e.target.closest('[data-act="board-edit"]');
      if (be) {
        e.preventDefault(); e.stopPropagation();
        openBoardForm(be.getAttribute('data-no'));
        return;
      }
      var bd = e.target.closest('[data-act="board-del"]');
      if (bd) {
        e.preventDefault(); e.stopPropagation();
        deleteBoard(bd.getAttribute('data-no'));
        return;
      }

      /* QC 卡片：点开数据库明细弹窗（2026-09-17 改，原为「按该维度筛选看板目录」）。
         筛选能力没有丢 —— 仍在筛选栏的 chip 上（见下面那个 data-act="filter" 分支）。 */
      var qc = e.target.closest('[data-act="qc"]');
      if (qc) {
        e.preventDefault();
        openQcDrill(qc.getAttribute('data-qc'));
        return;
      }

      // QC 区块标题栏的「刷新」：绕过后端 60s 缓存强制取数
      if (e.target.closest('[data-act="qc-reload"]')) {
        e.preventDefault();
        fetchQcStats(true);
        return;
      }

      var flt = e.target.closest('[data-act="filter"]');
      if (flt) {
        e.preventDefault();
        state.filter = flt.getAttribute('data-filter');
        writeLS(LS.filter, state.filter);
        render();
        return;
      }

      /* 区块「展开全部 / 收起」：只重画区块，**不碰拓扑区** ——
         render() 会顺带跑 ensureMap()，重建 #secTopo 等于 4 个地图 iframe 重新加载。 */
      var st = e.target.closest('[data-act="sec-toggle"]');
      if (st) {
        e.preventDefault();
        var gid3 = st.getAttribute('data-gid');
        if (state.secExpanded[gid3]) delete state.secExpanded[gid3];
        else state.secExpanded[gid3] = true;
        renderSections();
        return;
      }

      // 未登录门禁中的「本页直接登录」
      if (e.target.closest('[data-auth-act="login"]')) {
        e.preventDefault();
        openLogin();
        return;
      }

      // 「我已登录，重试」：地图区与整页门禁共用（用户在新标签页登录完回来点）
      if (e.target.closest('[data-auth-act="retry"]')) {
        e.preventDefault();
        state.authOk = null;
        authProbeBusy = false;
        render();
        return;
      }

      var mt = e.target.closest('#mapTabs [data-page]');
      if (mt) {
        state.mapTab = mt.getAttribute('data-page');
        writeLS(LS.mapTab, state.mapTab);
        renderMapTabs();
        ensureMap();
        return;
      }

      var mrf = e.target.closest('#mapRefresh');
      if (mrf) {
        e.preventDefault();
        var f = document.getElementById('mapFrame-' + state.mapTab);
        var boot = document.getElementById('mapBoot');
        if (boot) boot.hidden = false;
        if (f) {
          delete f.dataset.loaded;
          try { f.contentWindow.location.reload(); }
          catch (err) { f.setAttribute('src', '/myapp/?page=' + state.mapTab); }
        }
        return;
      }

      var dg = e.target.closest('[data-act="del-group"]');
      if (dg) {
        e.preventDefault();
        var gid2 = dg.getAttribute('data-gid');
        if (!window.confirm(t('modal.confirmDel'))) return;
        state.groups = (state.groups || []).filter(function (g) { return g.id !== gid2; });
        writeJSON(LS.groups, state.groups);
        Object.keys(state.assign).forEach(function (k) {
          state.assign[k] = state.assign[k].filter(function (g) { return g !== gid2; });
          if (!state.assign[k].length) delete state.assign[k];
        });
        writeJSON(LS.assign, state.assign);
        if (state.filter === gid2) { state.filter = 'all'; writeLS(LS.filter, 'all'); }
        render();
        if (!mask.hidden) renderGroupTable();
        toast(t('toast.groupRemoved'));
        return;
      }

      if (!e.target.closest('.g-menu') && !e.target.closest('[data-act="assign-menu"]')) closeMenu();
    });

    var clock = document.getElementById('clock');
    function pad(v) { return String(v).padStart(2, '0'); }
    function tick() {
      var n = new Date();
      clock.textContent = n.getFullYear() + '-' + pad(n.getMonth() + 1) + '-' + pad(n.getDate()) +
        ' ' + pad(n.getHours()) + ':' + pad(n.getMinutes()) + ':' + pad(n.getSeconds());
    }
    tick();
    setInterval(tick, 1000);

    window.addEventListener('resize', closeMenu);
    window.addEventListener('scroll', closeMenu, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeMenu();
        mask.hidden = true;
        if (loginMask) loginMask.hidden = true;
        if (!boardMask.hidden) closeBoardForm();
      }
    });
  }

  function applyDeepLink() {
    var l = qp('lang');
    if (l === 'en' || l === 'zh') { state.lang = l; writeLS(LS.lang, l); }
    var th = qp('theme');
    if (th === 'dark' || th === 'light') { state.theme = th; writeLS(LS.theme, th); }
    if (qp('edit') === '1' || qp('edit') === 'true') state.editing = true;
    var fl = qp('filter');
    if (fl) state.filter = fl;
    var q = qp('q');
    if (q) {
      state.query = q.toLowerCase();
      var si = document.getElementById('searchInput');
      if (si) si.value = q;
    }
    var mt = qp('map');
    if (mt && MAP_TABS.some(function (m) { return m.page === mt; })) state.mapTab = mt;
    /* ?font=1.05 / ?font=105 —— 便于把某个固定显示器的观感直接做成书签 */
    var fq = qp('font');
    if (fq) {
      var fv = parseFloat(fq);
      if (!isNaN(fv) && fv > 3) fv = fv / 100;               // 传 105 这种百分数也认
      var target = Math.round((fv - 1) * 100) / 100;
      if (FONT_STEPS.indexOf(target) !== -1) { fontStep = target; writeLS(LS.fontStep, String(fontStep)); }
    }
  }

  buildFontBtns();
  bind();
  applyDeepLink();
  render();
  syncMapZoom();

  /* QC 统计轮询：首次由 probeSession 登录成功后触发，此后每分钟一次。
     切回前台再补一次 —— 后台标签页的 setInterval 会被浏览器降频甚至冻结，
     不补的话回到页面时看到的可能是几分钟前的数字。 */
  setInterval(fetchQcStats, QC_POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) fetchQcStats();
  });
})();
