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
    catalog: 'msportal.catalog.v1',
    /* 子分组定义的本机兜底（2026-09-19 加）。与服务端目录同一份文档
       （catalog.subGroups），这里只在服务端写失败时留一份，口径同 catalog。 */
    subGroups: 'msportal.subgroups.v1',
    /* 拖拽排序的**个人层**（2026-09-20 加）。与 catalog/subGroups 不同，这一份
       刻意**不**往服务端同步：它就是「只有我这么看」的那一层，见 byOrder 上方说明。 */
    order: 'msportal.order.v1'
  };

  /* ------------------------------------------------------------- i18n ---- */
  var I18N = {
    zh: {
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
      /* 2026-09-20 改名：原为「访问量」。这个字段**从来没有任何东西在统计**——
         全项目没有 clicks 自增、没有埋点、没有上报接口，它只是管理员手输的一个数字，
         唯一作用是决定卡片顺序。展示它的「访问量」徽标已在 2026-09-19 删除，
         现在顺序主要靠拖拽（「调整顺序」按钮），这个数字退化成「没被拖过的看板按它排」。 */
      'board.fClicks': '初始排序权重',
      'board.fTags': '标签（逗号分隔）',
      'board.fGroups': '归属分组 *（可多选）',
      'chip.all': '全部',
      'sec.cxo.title': 'CXO View',
      'sec.cxo.sub': '| 决策战略层统一总控与运营视窗',
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
      'sec.friends.title': 'Friends Links',
      'sec.friends.sub': '| 集团中台与生态协作统一入口',
      /* 区块标题可点（2026-09-18 加）：点标题 = 进入该区块的下级页面
         （viewer.html?gid=xxx，列出同组全部看板），与卡片一样新标签页打开。 */
      'sec.openTip': '在新标签页打开「{name}」的下级页面（该分组看板列表）',
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
      /* 2026-09-20：导出由「当前页 CSV」改为「当前搜索条件下的全部行 .xlsx」，
         格式套 my_app 的统一格式 UNIFIED_EXCEL_V1（见 assets/excelReport.js）。
         文案必须跟着改：按钮写「导出 CSV」而给的是 xlsx，用户会以为没生效。 */
      'qc.export': '导出 Excel',
      'qc.exporting': '导出中…',
      'qc.exportErr': '导出失败',
      'qc.updated': '更新于',
      /* 2026-09-18：把「刷新节奏」和「数据源节奏」摆到标题栏上。
         起因：用户看到 QC 数字长时间不变，无法判断是「页面没在刷新」还是
         「源数据本来就没到下一个同步点」——而 eflow_sync 每小时 :00 才跑（实测约 374s，
         ≈:06 跑完）、SP 备件明细 sp_data_sync 每小时 :10、断站告警每 5 分钟，所以 TT/WO/CR/PMT 这类数字
         一小时才变一次是**数据源的节奏**。
         最终节奏（同日第三轮，用户定）：**告警 5 分钟级 / 其余每小时** ——
         六项里只有 realtime_alarm 高频变化（源 eflow_active_alarm 每 5 分钟 replace 一次），
         其余五项 + 达标率的源都是每小时才动。见 QC_FULL_MIN / QC_ALARM_MIN。 */
      'qc.cadence': '告警 5 分钟 · 其余每小时 :06',
      'qc.next': '下次 {t}',
      'qc.cadenceTip': '本面板分两档刷新：断站告警每 5 分钟（源 eflow_active_alarm 每 5 分钟同步，最近 {a}）；TT/WO/CR/PMT/SPMS 与达标率每小时 :06（源 eflow_sync 每小时 :00 起跑、实测约 :06 跑完，SP 备件明细 sp_data_sync 每小时 :10，最近 {f}）。切回本页或点「刷新」会立刻重拉全量。',
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
      /* 2026-09-20 按需求改口径：TT / WO 的大数字不再是「未关闭工单数」，
         而是「告警未清除的单数」—— 即 my_app 侧 eflow_tt / eflow_wo 的
         alarm_clear_time 为空。副行文案必须跟着改，否则卡片标题在说一件事、
         数字在说另一件事（旧文案「未关闭」会让人以为数字还是 8000 那一档）。 */
      'qc.sub.tt': '告警未清除的故障工单 (TT)',
      'qc.sub.wo': '告警未清除的任务工单 (WO)',
      'qc.sub.cr': '未关闭变更单 (CR)',
      'qc.sub.pmt': '未完成的预防性维护 (PMT)',
      /* 2026-09-20 按需求加口径：Status = WaitingForUpdate 的出入库单（尚未生效的在途单）
         既不计入大数字、也不进下钻明细（后端 portal_qc.py 的 SP_IGNORED_WORDS）。
         副行必须写出来，否则运维拿这里和 SP 报表的「未关闭单」对不上时会以为数字错了。 */
      'qc.sub.spms': '未关闭出入库单 (SPMS，不含 WaitingForUpdate)',
      'status.online': '在线',
      'status.beta': '试运行',
      /* 卡片徽标的 hover 备注（2026-09-19 加）。
         「在线」这个词最容易被读成「此刻在线」，实际它只是目录里的一个静态状态字段，
         所以必须把口径写出来。平台 / 部门同理 —— 值本身是真的，但没说清是什么。 */
      'tag.online.tip': '该看板已上线运行（取自目录的状态字段，不是实时在线探测）',
      'tag.beta.tip': '该看板试运行中（取自目录的状态字段）',
      'tag.plat.tip': '看板所属平台：{p}',
      'tag.dept.tip': '责任部门：{d}',
      'tag.new': '新增',
      /* ---- 拖拽排序（2026-09-20 加）---- */
      'btn.order': '调整顺序',
      'btn.orderOn': '退出排序',
      'order.dragTip': '按住拖动可调整本区块内的顺序',
      'order.hintLocal': '排序模式：在本区块内按住卡片拖动即可调顺序 · 只影响你自己的浏览器',
      'order.hintGlobal': '排序模式：在本区块内按住卡片拖动即可调顺序 · 保存后所有人可见',
      'order.scopeLocal': '仅我可见',
      'order.scopeGlobal': '所有人可见',
      'order.resetLocal': '恢复默认顺序',
      'order.resetConfirm': '清掉你在这台电脑上拖过的全部顺序，回到初始排序权重？\n（不影响服务器上「所有人可见」的顺序）',
      'order.resetDone': '已恢复默认顺序',
      'order.noLocal': '这台电脑上还没有拖过顺序',
      'order.savedGlobal': '顺序已保存',
      'order.backendOld': '但服务器未重启，顺序只在服务器本机生效（order 键被丢弃）',
      'open': '打开',
      'empty': '暂无看板，可在「编辑分组归属」中把其他看板移入本组',
      'emptyFilter': '没有匹配的看板，请调整搜索或筛选条件',
      'topo.title': 'Central Liberia Regional Topology',
      'topo.sub': '利比里亚网络拓扑全景',
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
      /* ---- 用户管理（2026-09-20 加）----
         与 /uniplam/ 的 UserManagementModal 同一套文案口径，且**同一份用户数据库**：
         账号、密码哈希、页面权限都存在门户的 auth-data/portal-auth.db 里，
         本页只通过 /uniplam/api/auth/* 读写，所以两边改完立刻互相可见。 */
      'um.entry': '用户管理',
      'um.entryTip': '管理统一门户账号（与 /uniplam/ 共用同一份用户数据库）',
      'um.title': '用户管理',
      'um.subtitle': '统一门户账号的增删与权限设置（仅管理员可见，与 /uniplam/ 同库同步）',
      'um.reload': '刷新',
      'um.openPortal': '在统一门户打开',
      'um.addTitle': '新增用户',
      'um.usernamePh': '用户名（2-32 位小写字母/数字/_.-）',
      'um.passwordPh': '初始密码（至少 8 位）',
      'um.roleAdmin': '管理员',
      'um.roleViewer': '普通用户',
      'um.add': '添加',
      'um.added': '用户已创建，其首次登录将被强制修改密码',
      'um.duplicate': '用户名已存在',
      'um.invalidInput': '用户名或密码格式不符合要求',
      'um.pwdTooShort': '密码至少需要 8 个字符',
      'um.colUser': '用户',
      'um.colRole': '角色',
      'um.colCreated': '创建时间',
      'um.colActions': '操作',
      'um.loading': '加载中…',
      'um.empty': '暂无账号',
      'um.self': '我',
      'um.reset': '重置密码',
      'um.resetHint': '为 {name} 设置新密码',
      'um.resetConfirm': '确认重置',
      'um.resetOk': '已重置 {name} 的密码，其下次登录需修改密码',
      'um.delete': '删除用户',
      'um.confirmDelete': '确定要删除用户 {name} 吗？该操作不可恢复。',
      'um.selfDelete': '不能删除当前登录的自己',
      'um.lastAdmin': '不能删除最后一个管理员',
      'um.pages': '页面配置',
      'um.pagesTitle': '页面配置 · {name}',
      'um.pagesSubtitle': '指定登录后打开哪个看板、以及可见的看板范围（与 /uniplam/ 同一条记录）',
      'um.landing': '登录后落地',
      'um.landingNone': '不干预（停在全部看板）',
      'um.landingNoCard': '不指定看板',
      'um.viewGrid': '卡片网格（统一门户）',
      'um.viewList': '列表（统一门户）',
      'um.viewMatrix': '分组矩阵（统一门户）',
      'um.viewTasks': '任务视图（统一门户）',
      'um.allowed': '可见范围',
      'um.allowedAll': '不限制（可见全部分组与看板）',
      'um.allowedCustom': '自定义白名单',
      'um.groupsMsportal': '按分组 · 本页（/MsPortal/）',
      'um.groupsPortal': '按分组 · 统一门户（/uniplam/）',
      'um.groupsPortalNone': '统一门户未保存全局目录，暂不能按业务分组授权',
      'um.allowedCards': '按看板（两边通用）',
      'um.cardsLocalOnly': '读不到统一门户的全局目录，候选项暂时锁住：这里的看板 id 是按 URL 推导的，与 /uniplam/ 实际使用的那套不一致，勾选后保存会让对方认不出来。请刷新重试。',
      'um.allowedHint': '「按看板」用的是两套门户共用的看板 id，勾选后在 /MsPortal/ 与 /uniplam/ 同时生效；两组「按分组」各自只在本侧生效，可都勾。',
      'um.allowedEmpty': '白名单为空：该账号登录后将看不到任何看板。',
      'um.navVisibilityOnly': '仅影响门户的导航可见性，不是访问控制；被隐藏的看板仍可通过直链打开。',
      'um.pagesSaved': '已保存 {name} 的页面配置',
      'um.pagesSave': '保存页面配置',
      'um.pagesCancel': '收起',
      'um.storage': '存储位置',
      'um.storageSqlite': 'SQLite 数据库',
      'um.storageJson': 'JSON 文件',
      'um.backups': '自动备份 {n} 份',
      'um.lastWrite': '最后写入',
      'um.migrated': '已从旧 JSON 迁移',
      'um.requestFail': '用户数据加载失败：{msg}',
      'um.needAdmin': '仅管理员可管理用户',
      /* 本机回环访问时 my_app 会把请求当成管理员（占位身份，没有门户 id），
         那种身份调不动门户的用户接口，所以这里明确引导去登录门户账号。 */
      'um.needPortalLogin': '用户管理需要统一门户账号登录，请先在本页登录',
      'um.pendingTitle': '待审批申请',
      'um.pendingEmpty': '暂无待审批申请',
      'um.colApplicant': '申请人',
      'um.colNote': '申请说明',
      'um.colTime': '申请时间',
      'um.colIp': '来源 IP',
      'um.approve': '批准',
      'um.reject': '驳回',
      'um.approveConfirm': '确定批准 {name} 的账号申请吗？',
      'um.rejectConfirm': '确定驳回 {name} 的账号申请吗？',
      'um.approved': '已批准 {name}：申请时设置的密码即刻生效，其首次登录需修改密码',
      'um.rejected': '已驳回 {name} 的账号申请',
      'um.notFound': '申请不存在或已被处理',
      /* ---- Task Report Files 内嵌卡（2026-09-18 加）----
         原 System Admin 的位置改为直接显示 /myapp/?page=email_reports 的页面内容，
         所以这里要一套「报告文件」版的标题/加载/登录文案：
         未登录与无权限分开写，因为处置完全不同 —— 前者登录即可，后者登录也没用。 */
      'email.title': 'Task Report Files',
      'email.sub': '| 任务报告文件中心（Email Reports）',
      'email.refresh': '刷新',
      'email.open': '新窗口',
      /* 标题可点（2026-09-18 加）：与其他区块标题同款，只是目标是报告文件中心本身 */
      'email.openTip': '在新标签页打开「Task Report Files」任务报告文件中心',
      'email.loading': '正在加载报告文件…',
      'email.auth.title': '报告文件需要登录后查看',
      'email.auth.tip': '任务报告文件需通过统一门户登录后访问。登录后回到本页即可正常显示。',
      'email.auth.login': '本页直接登录',
      'email.auth.retry': '我已登录，重试',
      'email.noAccess': '当前账号没有「Task Report Files」这块看板的权限',
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
      'sub.others': '其他系统',
      /* ---- 子分组管理（二级分组，2026-09-19 加） ---- */
      'subm.title': '子分组',
      'subm.expand': '展开子分组',
      'subm.collapse': '收起子分组',
      'subm.add': '新增子分组',
      'subm.addZh': '子分组中文名',
      'subm.addEn': 'English name',
      'subm.del': '删除',
      'subm.delConfirm': '确认删除子分组「{name}」？组内 {n} 个看板会移入「其他系统」，不会删除看板本身。',
      'subm.emptyName': '子分组名称不能为空',
      'subm.dup': '已有同名子分组',
      'subm.saved': '子分组已同步到服务器',
      'subm.unassigned': '已移入「其他系统」',
      'subm.readonly': '仅服务器本机可修改子分组',
      'subm.backendOld': '后端未升级，子分组未保存（需重启 my_app 后端）',
      'subm.noBoards': '暂无看板',
      'subm.save': '保存子分组',
      'subm.dirty': '子分组有未保存的改动',
      'subm.unsaved': '子分组还有未保存的改动，要先保存吗？\n\n「确定」= 保存并关闭，「取消」= 回到弹窗继续编辑。',
      'subm.others': '其他系统（未归类）',
      'subm.othersAuto': '自动',
      'subm.othersTip': '这是自动汇总的兜底区，不是可编辑的子分组：没有二级归属、或归属的子分组已被删除的看板都会落在这里。它无法删除（删掉下一帧又会出现）——要让这里变空，请给看板指定一个子分组，或把它们移出本分组。',
      'subm.othersEmpty': '暂无未归类的看板',
      'subm.dropHint': '拖到此处',
      'subm.pick': '加入看板',
      'subm.pickNone': '没有可加入的看板',
      'subm.remove': '移出子分组',
      'subm.hint': '子分组定义与看板归属保存在服务器，所有人打开门户看到的一致；拖动看板可在子分组之间移动，拖到「其他系统」即取消归类。',
      'subm.readonlyHint': '当前不是服务器本机访问，子分组只读。',
    },
    en: {
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
      /* Renamed 2026-09-20 (was "Views"): nothing ever counted clicks — it is a
         hand-typed number whose only job is card order. The "views" badge that
         displayed it was removed 2026-09-19; ordering is now done by dragging
         (the "Sort order" button), so this is the fallback weight only. */
      'board.fClicks': 'Initial sort weight',
      'board.fTags': 'Tags (comma separated)',
      'board.fGroups': 'Groups * (multi-select)',
      'chip.all': 'All',
      'sec.cxo.title': 'CXO View',
      'sec.cxo.sub': '| Executive strategy & operation window',
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
      'sec.friends.title': 'Friends Links',
      'sec.friends.sub': '| Group middle-platform & ecosystem SSO',
      'sec.openTip': 'Open the {name} sub-page (its dashboard list) in a new tab',
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
      /* 2026-09-20：CSV -> xlsx（my_app 统一格式 UNIFIED_EXCEL_V1），见中文块同名键。 */
      'qc.export': 'Export Excel',
      'qc.exporting': 'Exporting…',
      'qc.exportErr': 'Export failed',
      'qc.updated': 'Updated',
      /* 2026-09-18：见中文块同名键的注释（刷新节奏 / 数据源节奏写到标题栏）。 */
      'qc.cadence': 'alarms 5 min · rest hourly :06',
      'qc.next': 'next {t}',
      'qc.cadenceTip': 'Two refresh cadences: site-outage alarms every 5 min (source eflow_active_alarm syncs every 5 min, latest {a}); TT/WO/CR/PMT/SPMS and the SLA rate hourly at :06 (eflow_sync starts at :00 and takes ~6 min, the SP spare-part details sync sp_data_sync runs hourly at :10, latest {f}). Coming back to this tab or clicking Refresh re-pulls the full set immediately.',
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
      'qc.sub.tt': 'Trouble tickets with uncleared alarm',
      'qc.sub.wo': 'Work orders with uncleared alarm',
      'qc.sub.cr': 'Unclosed change requests',
      'qc.sub.pmt': 'Pending preventive maintenance',
      /* 2026-09-20: WaitingForUpdate rows are excluded — see the zh block. */
      'qc.sub.spms': 'Unclosed inbound/outbound orders (excl. WaitingForUpdate)',
      'status.online': 'Online',
      'status.beta': 'Beta',
      /* Hover notes for the card badges (added 2026-09-19) — see the zh block. */
      'tag.online.tip': 'Dashboard is live (a catalogue status field, not a live health probe)',
      'tag.beta.tip': 'Dashboard is in trial / beta (a catalogue status field)',
      'tag.plat.tip': 'Owning platform: {p}',
      'tag.dept.tip': 'Owning department: {d}',
      'tag.new': 'New',
      /* ---- Drag to reorder (added 2026-09-20) ---- */
      'btn.order': 'Sort order',
      'btn.orderOn': 'Exit sorting',
      'order.dragTip': 'Drag to change the order inside this section',
      'order.hintLocal': 'Sort mode: drag a card inside its section to reorder it · affects only this browser',
      'order.hintGlobal': 'Sort mode: drag a card inside its section to reorder it · visible to everyone once saved',
      'order.scopeLocal': 'Only me',
      'order.scopeGlobal': 'Everyone',
      'order.resetLocal': 'Reset order',
      'order.resetConfirm': 'Discard every order you dragged on this computer and go back to the initial sort weight?\n(The server-side "Everyone" order is not affected.)',
      'order.resetDone': 'Order reset',
      'order.noLocal': 'You have not dragged any order on this computer yet',
      'order.savedGlobal': 'Order saved',
      'order.backendOld': 'but the server was not restarted, so the order only applies on the server host (the "order" key was dropped)',
      'open': 'Open',
      'empty': 'No dashboard here yet — use "Edit group assignment" to move dashboards into this group',
      'emptyFilter': 'No dashboard matches the current search or filter',
      'topo.title': 'Central Liberia Regional Topology',
      'topo.sub': 'Liberia regional network topology',
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
      /* ---- User management (added 2026-09-20) ----
         Same wording as /uniplam/'s UserManagementModal and, more importantly,
         the SAME user database: accounts, password hashes and page permissions all
         live in the portal's auth-data/portal-auth.db, reached here over
         /uniplam/api/auth/* — so a change made on either side shows up on the other. */
      'um.entry': 'User Management',
      'um.entryTip': 'Manage unified-portal accounts (shares the same user database as /uniplam/)',
      'um.title': 'User Management',
      'um.subtitle': 'Add, remove and configure unified-portal accounts (admin only, same DB as /uniplam/)',
      'um.reload': 'Refresh',
      'um.openPortal': 'Open in unified portal',
      'um.addTitle': 'Add User',
      'um.usernamePh': 'username (2-32 chars a-z 0-9 _.-)',
      'um.passwordPh': 'initial password (min 8 chars)',
      'um.roleAdmin': 'Admin',
      'um.roleViewer': 'Viewer',
      'um.add': 'Add',
      'um.added': 'User created; password change required at first login',
      'um.duplicate': 'Username already exists',
      'um.invalidInput': 'Invalid username or password format',
      'um.pwdTooShort': 'Password must be at least 8 characters',
      'um.colUser': 'User',
      'um.colRole': 'Role',
      'um.colCreated': 'Created',
      'um.colActions': 'Actions',
      'um.loading': 'Loading…',
      'um.empty': 'No accounts yet',
      'um.self': 'You',
      'um.reset': 'Reset password',
      'um.resetHint': 'Set a new password for {name}',
      'um.resetConfirm': 'Reset',
      'um.resetOk': 'Password reset for {name}; change required at next login',
      'um.delete': 'Delete user',
      'um.confirmDelete': 'Delete user {name}? This cannot be undone.',
      'um.selfDelete': 'You cannot delete yourself',
      'um.lastAdmin': 'Cannot delete the last admin',
      'um.pages': 'Page access',
      'um.pagesTitle': 'Page access · {name}',
      'um.pagesSubtitle': 'Set the landing dashboard after login and which dashboards are visible (same record as /uniplam/)',
      'um.landing': 'Landing',
      'um.landingNone': 'No redirect (stay on all dashboards)',
      'um.landingNoCard': 'No specific dashboard',
      'um.viewGrid': 'Card grid (unified portal)',
      'um.viewList': 'List (unified portal)',
      'um.viewMatrix': 'Group matrix (unified portal)',
      'um.viewTasks': 'Task view (unified portal)',
      'um.allowed': 'Visible range',
      'um.allowedAll': 'Unrestricted (all groups and dashboards)',
      'um.allowedCustom': 'Custom allowlist',
      'um.groupsMsportal': 'By group · this page (/MsPortal/)',
      'um.groupsPortal': 'By group · unified portal (/uniplam/)',
      'um.groupsPortalNone': 'The unified portal has no saved global catalog, so business groups cannot be granted yet',
      'um.allowedCards': 'By dashboard (shared by both)',
      'um.cardsLocalOnly': 'The unified-portal global catalogue could not be read, so these options are locked: the dashboard ids here are derived from URLs and do not match the set /uniplam/ actually uses — saving them would leave values it cannot recognise. Please refresh and retry.',
      'um.allowedHint': 'The dashboard allowlist uses ids shared by both portals, so it applies to /MsPortal/ and /uniplam/ at once; each group list only affects its own side, and both may be used together.',
      'um.allowedEmpty': 'Allowlist is empty: this account will see no dashboard at all.',
      'um.navVisibilityOnly': 'Affects portal navigation visibility only, not access control; hidden dashboards are still reachable by direct URL.',
      'um.pagesSaved': 'Page access saved for {name}',
      'um.pagesSave': 'Save page access',
      'um.pagesCancel': 'Collapse',
      'um.storage': 'Storage',
      'um.storageSqlite': 'SQLite database',
      'um.storageJson': 'JSON file',
      'um.backups': '{n} auto backup(s)',
      'um.lastWrite': 'Last write',
      'um.migrated': 'migrated from legacy JSON',
      'um.requestFail': 'Failed to load user data: {msg}',
      'um.needAdmin': 'Admin role required to manage users',
      'um.needPortalLogin': 'User management needs a unified-portal sign-in — please sign in on this page first',
      'um.pendingTitle': 'Pending Requests',
      'um.pendingEmpty': 'No pending requests',
      'um.colApplicant': 'Applicant',
      'um.colNote': 'Reason',
      'um.colTime': 'Requested At',
      'um.colIp': 'Source IP',
      'um.approve': 'Approve',
      'um.reject': 'Reject',
      'um.approveConfirm': 'Approve the account request from {name}?',
      'um.rejectConfirm': 'Reject the account request from {name}?',
      'um.approved': 'Approved {name}: the password set at sign-up is now active (password change required at first login)',
      'um.rejected': 'Rejected the account request from {name}',
      'um.notFound': 'Request not found or already handled',
      /* ---- Task Report Files embed card (added 2026-09-18) ---- */
      'email.title': 'Task Report Files',
      'email.sub': '| Task report file center (Email Reports)',
      'email.refresh': 'Refresh',
      'email.open': 'New window',
      /* Clickable title (added 2026-09-18): same as other section titles, target is the center itself */
      'email.openTip': 'Open the Task Report Files center in a new tab',
      'email.loading': 'Loading report files…',
      'email.auth.title': 'Sign in to view report files',
      'email.auth.tip': 'Task report files require a unified-portal sign-in. Sign in, then return to this page.',
      'email.auth.login': 'Sign in here',
      'email.auth.retry': 'I have signed in — retry',
      'email.noAccess': 'This account has no access to the "Task Report Files" dashboard',
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
      'sub.others': 'Other systems',
      /* ---- Sub-group management (2026-09-19) ---- */
      'subm.title': 'Sub-groups',
      'subm.expand': 'Expand sub-groups',
      'subm.collapse': 'Collapse sub-groups',
      'subm.add': 'Add sub-group',
      'subm.addZh': 'Sub-group name (中文)',
      'subm.addEn': 'English name',
      'subm.del': 'Delete',
      'subm.delConfirm': 'Delete sub-group "{name}"? Its {n} dashboard(s) move to "Other systems"; no dashboard is deleted.',
      'subm.emptyName': 'Sub-group name cannot be empty',
      'subm.dup': 'A sub-group with this name already exists',
      'subm.saved': 'Sub-groups synced to server',
      'subm.unassigned': 'Moved to "Other systems"',
      'subm.readonly': 'Sub-groups can only be changed from the server host',
      'subm.backendOld': 'Backend not upgraded — sub-groups were not saved (restart my_app backend)',
      'subm.noBoards': 'No dashboards',
      'subm.save': 'Save sub-groups',
      'subm.dirty': 'Sub-group changes are not saved yet',
      'subm.unsaved': 'Sub-group changes are not saved yet. Save them now?\n\nOK = save and close, Cancel = go back and keep editing.',
      'subm.others': 'Other systems (unassigned)',
      'subm.othersAuto': 'auto',
      'subm.othersTip': 'This is an automatically computed catch-all, not an editable sub-group: dashboards with no sub-group, or whose sub-group was deleted, land here. It cannot be deleted (it reappears immediately) — to empty it, assign those dashboards to a sub-group or move them out of this group.',
      'subm.othersEmpty': 'No unassigned dashboards',
      'subm.dropHint': 'Drop here',
      'subm.pick': 'Add dashboard',
      'subm.pickNone': 'No dashboard left to add',
      'subm.remove': 'Remove from sub-group',
      'subm.hint': 'Sub-group definitions and dashboard membership are stored on the server, so everyone sees the same; drag a dashboard between sub-groups, or onto "Other systems" to unassign it.',
      'subm.readonlyHint': 'Not opened from the server host — sub-groups are read-only.'
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
    /* 拖拽排序模式（2026-09-20 加）。与 editing 互斥：进一个就退出另一个 ——
       编辑模式卡片右上角是「编辑 / 删除」按钮、拖拽模式下整张卡是拖拽柄，
       两种命中区叠在一起会互相抢手势。 */
    ordering: false,
    /* 拖拽写到哪一层：'local' = 只影响自己浏览器（默认，安全）；'global' = 写服务端
       目录、所有人可见（仅 catalogEditable 时可选）。 */
    orderScope: 'local',
    /* 个人层顺序 { 分组id: [看板编号,…] }，落 localStorage。 */
    orderLocal: readJSON(LS.order, {}),
    /* 全局层顺序，来自服务端 catalog.order；未加载/未配置时为 null。 */
    orderGlobal: null,
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
    /* 断站告警的「单项」数据（2026-09-18 加，走 GET /api/portal-qc/summary?only=alarm）。
       为什么要单独一份：六项里只有告警是高频变化的（源 eflow_active_alarm 每 5 分钟），
       其余五项 + 达标率的源每小时才动 —— 面板按「告警 5 分钟 / 其余每小时」分频刷新，
       告警那份**只覆盖 alarm 这一格**，绝不能拿它替换 state.qcStats（会把其余五项清空）。 */
    qcAlarm: null,
    /* 两档刷新各自的「数据时间」（后端 generated_at，字符串）：full = 全量那份、
       alarm = 告警那份。标题栏的「更新于」取两者中较新的一个。 */
    qcFullAt: '',
    qcAlarmAt: '',
    /* 下钻明细弹窗状态。metric=null 表示弹窗关闭。 */
    qcDrill: { metric: null, page: 1, size: 50, q: '', total: 0, rows: [], columns: [], loading: false, err: '' },

    /* ---- 看板目录（2026-09-17 加：组件内的看板可增删改，参考 uniplam 的设计）----
       目录真相源优先级：服务端全局目录 > 本机 localStorage 兜底 > data.js 内置。
       与 uniplam 的 INITIAL_DASHBOARDS / portal-default.json 关系一致：
       内置是出厂值，服务端是运行时覆盖，DELETE 接口即可回滚。
       catalog=null 表示「服务端从未保存过」，此时用 data.js 内置目录。 */
    catalog: readJSON(LS.catalog, null),
    /* 子分组定义（2026-09-19 加）：{ 父分组 id: [{id, zh, en}, …] }，数组顺序即展示顺序。
       与服务端目录同一份文档（catalog.subGroups），优先级也一致：
       服务端 > 本机兜底 > 内置（见 builtinSubGroups）。
       null = 服务端从未存过 → 用内置的三个子分组；
       {'BO View': []} = 显式「BO View 没有子分组」—— 两者语义不同，不能混。 */
    subGroups: readJSON(LS.subGroups, null),
    /* 分组管理弹窗里当前展开子分组面板的分组 id（null = 全部收起）。只活在本次会话。 */
    subOpen: null,
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
    boardNo: null,

    /* ---- 用户管理弹窗（2026-09-20 加）----
       与 /uniplam/ 的 UserManagementModal 功能对齐，并且**读写同一份用户数据库**：
       账号、密码哈希、页面权限都在门户的 auth-data/portal-auth.db（SQLite）里，
       本页只经 /uniplam/api/auth/* 访问，所以两边任何一处改动立刻互相可见。
       只对管理员开放；非管理员连入口按钮都不渲染（见 syncAuthUi）。

       为什么把状态全放在 state.um 里而不是散在各处：renderUserMgmt() 是整块重建
       innerHTML 的，凡是「输入到一半不能丢」的值（新用户表单、重置密码、页面配置
       草稿）都必须先落在状态里再画出来，否则每次重绘都会把用户正在敲的内容清掉。 */
    um: {
      open: false,
      users: [],
      requests: [],
      storage: null,
      /* 统一门户全局目录（GET /uniplam/api/portal-default）：
         groups 用于「按业务分组」授权（那套分组名由 /uniplam/ 消费）；
         groupLabels + dashboards 用于「按看板」—— 必须用**这一份** id 空间
         （DashboardItem.id），否则勾出来的值 /uniplam/ 认不出来。 */
      portalGroups: null,
      portalGroupLabels: null,
      portalDashboards: null,
      portalGroupsErr: false,
      loading: false,
      error: '',
      success: '',
      /* 新增用户表单 */
      nu: '', np: '', nr: 'viewer',
      /* 行内重置密码：正在重置的账号 id + 输入框内容 */
      resetId: '', resetPwd: '',
      /* 待审批申请：每条申请行内选择的批准角色 */
      approveRoles: {},
      /* 页面配置面板：正在编辑的账号 id（'' = 收起） */
      profileId: '',
      pv: '', pc: '', restricted: false, groups: [], cards: [],
      saving: false,
      /* 正在进行的异步动作（禁用按钮防重复提交）：'' | 'add' | 'decide' | 'reset' | 'delete' */
      busy: ''
    }
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
     仍按统一门户的原语义生效，而不是只做一个「有 token 就能看全部」的门禁。
     映射表本身已移到 assets/access.js（viewer.js 也要用同一份，见下方转发）。 */

  /* 看板 id 映射与权限判定都抽到 assets/access.js 了（2026-09-20）——
     因为看板查看器（viewer.js）也必须用同一套：它原先没有任何权限判定，
     受限用户改一下 URL 就能在查看器里看到被禁止的报告（实测确认过）。
     映射表有 30+ 条页面键 / 17 条 FineBI 链接，复制一份必然漂移，所以只留一份。
     下面两个函数只做转发，语义与抽出前逐字一致。 */
  function dashboardAccessId(item) {
    return window.MSPortalAccess.dashboardAccessId(item);
  }

  function canSeeDashboard(item) {
    return window.MSPortalAccess.canSee(state.authUser, item);
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
          /* 子分组定义与服务端目录同一份文档：catalog=null（从未保存过）时这里也是
             null → 回落内置三个子分组。 */
          state.subGroups = normalizeSubMap(data.catalog.subGroups);
          /* 全局层拖拽顺序（2026-09-20 加）。未配置时为 null → byOrder 回落到
             「初始排序权重」，与这个功能上线前的顺序完全一致。 */
          state.orderGlobal = normOrderMap(data.catalog.order);
          /* 旧数据迁移必须在任何编辑之前跑：把老的 boSub 搬进 subOf。
             否则「在 FO View 下改一张本来靠 boSub 归属 BO View 的看板」会因为
             subOf 一旦存在就说了算，把 BO View 的归属悄悄丢掉。 */
          state.catalog = migrateSubOf(state.catalog);
          state.catalogSource = 'server';
          // 服务端为准：清掉本机兜底副本，避免两份目录长期不一致
          try {
            localStorage.removeItem(LS.catalog);
            localStorage.removeItem(LS.subGroups);
          } catch (e) { /* ignore */ }
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
      已经全局生效 —— 失败时 toast 明确说「仅保存在本机」。

      subGroups 省略时沿用 state.subGroups（看板增删改走的都是这条路，
      所以改一张看板不会把子分组定义顺手抹掉）；显式传 null 表示「不要子分组键」。 */
  function saveCatalog(items, okMsg, subGroups) {
    var subs = (subGroups === undefined) ? state.subGroups : subGroups;
    state.catalog = items;
    state.subGroups = subs || null;
    writeJSON(LS.catalog, items);
    if (state.subGroups) writeJSON(LS.subGroups, state.subGroups);
    else { try { localStorage.removeItem(LS.subGroups); } catch (e) { /* ignore */ } }
    renderCatalog();
    var payload = { items: items };
    if (state.subGroups) payload.subGroups = state.subGroups;
    /* 全局层拖拽顺序（2026-09-20 加）：跟着**每一次**整体 PUT 一起带上 ——
       否则「改一张看板的标题」会顺手把全局顺序抹掉（后端是整体替换，不带就是删掉）。 */
    var sentOrder = !!(state.orderGlobal && Object.keys(state.orderGlobal).length);
    if (sentOrder) payload.order = state.orderGlobal;
    /* 发请求前记下「这次到底带没带子分组」：后端若是旧版（未重启/未升级），
       _normalize_catalog 会把 subGroups 丢掉并原样返回 —— 不比对就会提示「已同步到服务器」，
       而刷新后子分组悄悄变回内置三个，属于最难查的那类假成功。order 同理。 */
    var sentSubs = !!state.subGroups;
    return fetch('/api/portal-catalog', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ catalog: payload })
    }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      if (!r.ok || ct.indexOf('json') === -1) {
        throw new Error(r.status === 403 ? t('board.readonly') : 'HTTP ' + r.status);
      }
      return r.json();
    }).then(function (data) {
      // 以服务端归一化后的结果为准（后端会丢弃缺标题/链接的条目、截断超长文本）
      if (data.catalog && data.catalog.items) state.catalog = migrateSubOf(data.catalog.items);
      state.catalogSource = 'server';
      state.catalogEditable = !!data.editable;
      state.subGroups = normalizeSubMap(data.catalog && data.catalog.subGroups);
      state.orderGlobal = normOrderMap(data.catalog && data.catalog.order);
      try {
        localStorage.removeItem(LS.catalog);
        localStorage.removeItem(LS.subGroups);
      } catch (e) { /* ignore */ }
      renderCatalog();
      /* 后端旧版（未重启）会静默丢掉 order 键：这时必须说出来，
         否则「提示已同步、刷新后顺序变回去」又是一次假成功。 */
      if (sentOrder && !(state.orderGlobal && Object.keys(state.orderGlobal).length)) {
        toast(okMsg + ' · ' + t('order.backendOld'));
      } else if (sentSubs && !state.subGroups) toast(okMsg + ' · ' + t('subm.backendOld'));
      else toast(okMsg + ' · ' + t('board.savedServer'));
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
        state.subGroups = null;
        state.catalogSource = 'builtin';
        try {
          localStorage.removeItem(LS.catalog);
          localStorage.removeItem(LS.subGroups);
        } catch (e) { /* ignore */ }
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

  /** 按使用量（初始排序权重）降序，同值保持源表序号顺序 */
  function byUsage(a, b) {
    return (b.clicks || 0) - (a.clicks || 0) || (a.no - b.no);
  }

  /* ================================================ 拖拽排序（2026-09-20 加）==
     两层顺序，优先级从高到低：
       ① 个人层 state.orderLocal（localStorage，只有自己看得见）
       ② 全局层 state.orderGlobal（服务端 catalog.order，所有人共用）
       ③ 初始排序权重 item.clicks（byUsage，即这个功能上线前的排序）
     ③ 是**兜底**而不是被取代：没被拖过的分组/看板仍按老规则排，
     所以这个功能上线当天，任何分组的现有顺序都不会发生变化。

     ⚠️ 为什么顺序表是「按分组存 [编号,…]」而不是给每个看板加一个 order 数字：
     一张看板可以同时挂在多个分组（实测 no=11/12/13/18/36 同时属于 FO View + FLM View）。
     看板级 order 会出现在 A 组把它拖到第 1 位、B 组里的同一张卡也被顶到第 1 位的问题 ——
     与 subOf 当初要解决的「串改」是同一类。按分组各存一份顺序表就没有这个问题。

     ⚠️ 顺序表里**没有**的看板一律排到有编号的后面（彼此仍按 byUsage）：
     新增的看板因此默认落在末尾，符合直觉；被筛掉的看板也不会因为一次拖动就乱序。 */
  function normOrderMap(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    var out = {};
    Object.keys(raw).forEach(function (gid) {
      var arr = raw[gid];
      if (!Array.isArray(arr)) return;
      var seq = [];
      arr.forEach(function (x) {
        var n = parseInt(x, 10);
        // 去重必须做：indexOf 只认第一个，重复编号会让后面的位置永远排不上
        if (!isNaN(n) && n >= 0 && seq.indexOf(n) === -1) seq.push(n);
      });
      out[gid] = seq;
    });
    return out;
  }

  /** 某分组当前生效的顺序表；两层都没有则返回 null = 按初始排序权重。 */
  function orderNosFor(gid) {
    var loc = state.orderLocal && state.orderLocal[gid];
    if (loc && loc.length) return loc;
    var glob = state.orderGlobal && state.orderGlobal[gid];
    if (glob && glob.length) return glob;
    return null;
  }

  /** 该分组当前用的是哪一层（供提示条回显；null = 还没拖过）。 */
  function orderLayerOf(gid) {
    var loc = state.orderLocal && state.orderLocal[gid];
    if (loc && loc.length) return 'local';
    var glob = state.orderGlobal && state.orderGlobal[gid];
    if (glob && glob.length) return 'global';
    return null;
  }

  /** 排序比较器：在顺序表里的按表内位置，不在表里的排到后面。 */
  function byOrder(gid) {
    var list = orderNosFor(gid);
    if (!list) return byUsage;
    return function (a, b) {
      var ia = list.indexOf(a.no);
      var ib = list.indexOf(b.no);
      if (ia === -1 && ib === -1) return byUsage(a, b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    };
  }

  /** 该分组「全部」看板的编号，按当前生效顺序 —— 拖拽落点就是在这个数组里挪一项。
      刻意用 catalogItems() 而不是 filtered()：若只按筛过的子集存顺序表，
      没被筛中的看板会因为「不在表里」被一律甩到末尾，一次带筛选的拖动就会把整个区块打乱。 */
  function orderSequenceOf(gid) {
    return catalogItems().filter(inGroup(gid)).sort(byOrder(gid)).map(function (it) { return it.no; });
  }

  /** 把 dragNo 挪到 targetNo 的前/后，返回新的完整顺序表；任一编号不在组内返回 null。 */
  function reorderSequence(gid, dragNo, targetNo, before) {
    if (String(dragNo) === String(targetNo)) return null;
    var seq = orderSequenceOf(gid);
    var from = seq.indexOf(dragNo);
    if (from === -1) return null;
    seq.splice(from, 1);
    var to = seq.indexOf(targetNo);
    if (to === -1) return null;
    seq.splice(before ? to : to + 1, 0, dragNo);
    return seq;
  }

  /** 落一层顺序。scope='local' 只写本机；'global' 写服务端目录（仅本机可写）。 */
  function saveOrder(gid, nos, scope) {
    if (scope === 'global') {
      var next = {};
      Object.keys(state.orderGlobal || {}).forEach(function (k) { next[k] = state.orderGlobal[k]; });
      next[gid] = nos;
      state.orderGlobal = next;
      /* 全局顺序落地后必须把这一组的**个人覆盖**清掉：否则个人层优先级更高，
         管理员会看到「提示已同步到服务器、画面却没变」这种最难查的假成功。 */
      if (state.orderLocal && state.orderLocal[gid]) {
        delete state.orderLocal[gid];
        writeJSON(LS.order, state.orderLocal);
      }
      saveCatalog(catalogItems(), t('order.savedGlobal'));
      return;
    }
    state.orderLocal = state.orderLocal || {};
    state.orderLocal[gid] = nos;
    writeJSON(LS.order, state.orderLocal);
    renderSections();
  }

  /** 清掉某分组的个人层顺序（全局层不动）。 */
  function clearLocalOrder(gid) {
    if (!state.orderLocal || !state.orderLocal[gid]) return false;
    delete state.orderLocal[gid];
    writeJSON(LS.order, state.orderLocal);
    renderSections();
    return true;
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
    var all = filtered().filter(inGroup(gid)).sort(byOrder(gid));
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

  /** 区块标题的下级页面：该分组的看板查看器（viewer.html?gid=xxx）。
      与卡片链接同一套规则 —— 编辑态不给链接（卡片在编辑态也退化成 div），
      免得正在改分组归属时一点标题就跳走。 */
  function groupHref(gid) {
    if (state.editing || state.ordering || !gid) return '';
    return 'viewer.html?gid=' + encodeURIComponent(gid);
  }

  function shell(cls, item, inner) {
    // data-board-no：编辑/删除后的定位锚点，也是拖拽排序的键
    var noAttr = ' data-board-no="' + esc(item.no) + '"';
    /* data-gid：拖拽时判定「在哪个区块里排」。必须挂在卡片上而不是区块容器上 ——
       同一张看板可以同时出现在多个区块，只有卡片自己知道这一张画的是哪个区块。 */
    var gidAttr = state._curGid ? ' data-gid="' + esc(state._curGid) + '"' : '';
    /* 拖拽排序模式下卡片退化成 div（与编辑态同理）：
       ① <a> 默认就是可拖的（拖出的是链接），会盖掉我们的排序拖拽；
       ② 排序时不应该一点就跳走。 */
    if (state.ordering) {
      return '<div class="' + cls + ' relative mp-drag-card" draggable="true"' + noAttr + gidAttr +
        ' title="' + esc(t('order.dragTip')) + '">' + inner + '</div>';
    }
    if (state.editing) return '<div class="' + cls + ' relative"' + noAttr + gidAttr + '>' + inner + '</div>';
    return '<a class="' + cls + '"' + noAttr + gidAttr + ' href="' + esc(cardHref(item)) + '" target="_blank" ' +
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

  /** 状态徽章：试运行（在线的不挂徽章）
      2026-09-19：加了 hover 备注 —— 「在线 / 试运行」是目录里的静态状态字段，
      不是实时在线探测，不写清楚会被读成「此刻在线」。 */
  function statusTag(item) {
    if (item.status === 'beta') {
      return '<span class="text-[12px] px-2 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-200 font-mono" ' +
        'title="' + esc(t('tag.beta.tip')) + '">β</span>';
    }
    return '';
  }

  /* 2026-09-19 按用户要求删除「访问量」徽标（原 viewsTag + hotLine + hotLineCache）。
     删除理由（有据可查，不是猜测）：
       · 它显示成「访问量」，但全项目**没有任何东西在统计访问** ——
         grep 不到 clicks 自增、没有埋点、没有上报接口（portal.js 里唯一的 POST 是登录/登出）；
       · 后端 backend/routers/portal_catalog.py 只是把 clicks 原样存取；
       · 编辑看板的表单里 bfClicks 是管理员手输框（board.fClicks = 访问量）；
       · data.js 自己的注释写明 clicks=1000 是刻意的，只为让新卡稳定排在 CXO View 第一张。
     即：它是人工维护的排序权重，被当成统计值展示。按门户一贯的「绝不显示假数字」
     原则（同 2026-09-17 删掉的写死 98.7%），这里把展示删掉。
     clicks 字段本身**保留**：CXO View 仍按它降序排（见 byUsage），排序行为不变。 */

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
  /** 区块标题行。
      kind: 'square-red' | 'square-rose' | 'dot-red' | 'dot-slate'
      subInline: 副标题是否写在 h2 内部（ref 里 CXO/QC/QA 是 inline，MS/FLM/FO/BO/Admin 是独立 span）
      href:     传了就把「色块 + 标题 + 副标题」整块变成链接 —— 点标题进入该区块的**下级页面**
                （viewer.html?gid=xxx，即该分组的看板查看器，与卡片一样新标签页打开）。
                默认外观与 ref 1:1 一致，hover / focus 才出现主题色、下划线与柔光底
                （见 portal.css 的 .sec-head-link），所以传 href 不会改变静止态的版式。 */
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

    var inner = '<span class="' + dot + '"></span>' + title;
    var wrapCls = opts.subInline ? 'flex items-center gap-2' : 'flex items-center gap-1.5';
    /* 刻意**不**在标题右边挂箭头图标：实测标题行右侧的空隙在 1920px 的 FO View 只有 12px、
       1600px 的 FLM View 只有 11px（TMP/verify_titlelink_hover_layout.cjs），
       14px 的箭头必然压到右侧计数胶囊上。可点提示改由 portal.css 的 hover 柔光底承担
       （只向外扩 5px，全断点都安全，且不参与布局、不挤动工具条）。 */
    var wrap = opts.href
      ? '<a class="' + wrapCls + ' sec-head-link" href="' + esc(opts.href) + '" target="_blank" ' +
        'rel="noopener noreferrer" title="' + esc(opts.hrefTip || opts.title) + '">' +
        inner + '</a>'
      : '<div class="' + wrapCls + '">' + inner + '</div>';

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
          '<span class="' + (PLAT_TAG[item.platform] || PLAT_TAG.external) + ' font-mono shrink-0" ' +
            'title="' + esc(tf('tag.plat.tip', { p: platLabel(item) })) + '">' + esc(platShort(item)) + '</span>' +
        '</div>' +
        '<p class="text-[13px] text-slate-500 mt-1 truncate">' + esc(descOf(item)) + '</p>' +
        '<div class="mt-2 text-[12px] text-slate-400 flex items-center gap-2">' +
          '<span class="' + (item.status === 'beta' ? 'text-amber-600' : 'text-emerald-600') + ' flex items-center" ' +
            'title="' + esc(t(item.status === 'beta' ? 'tag.beta.tip' : 'tag.online.tip')) + '">' +
            ico(item.status === 'beta' ? 'warning-circle' : 'circle-check', 'mr-0.5') + esc(statusText(item)) + '</span>' +
          '<span class="truncate" title="' + esc(tf('tag.dept.tip', { d: deptOf(item) })) + '">' + esc(deptOf(item)) + '</span>' +
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
      '<span class="shrink-0 ml-2 flex items-center gap-1.5">' + statusTag(item) +
        ico('arrow-up-right', 'text-[14px] text-slate-300 group-hover:text-blue-600') + '</span>' +
      assignHtml(item);
    return shell('flex items-center justify-between p-2.5 rounded-lg hover:bg-blue-50/70 border border-slate-100 transition group', item, inner);
  }

  /** FLM / FO 小卡
      2026-09-19：删掉「访问量」徽标后，这里只剩状态徽章（只有试运行才有）。
      必须**判空再渲染**整行 —— 原来 viewsTag 恒定返回一个 span，所以那行永远非空；
      现在在线看板没有徽章，再无条件输出 <div class="mt-1"> 就会留一条 4px 的空白，
      卡片高度跟着变。showViews 参数保留（调用方一律传 true），语义改为「要不要带徽章行」。 */
  function solidCard(item, idx, showViews) {
    var tag = statusTag(item);
    var tagRow = (showViews && tag) ? '<div class="mt-1 flex items-center gap-1.5">' + tag + '</div>' : '';
    var inner =
      '<div class="w-10 h-10 rounded-lg ' + SOLID_TONES[idx % SOLID_TONES.length] +
        ' text-white flex items-center justify-center text-[20px] shrink-0">' + ico(item.icon) + '</div>' +
      '<div class="min-w-0 flex-1">' +
        '<div class="text-[14px] font-bold text-slate-800 group-hover:text-blue-600 truncate">' + esc(titleOf(item)) + '</div>' +
        '<div class="text-[12px] text-slate-500 truncate">' + esc(descOf(item)) + '</div>' +
        tagRow +
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
        '<div class="text-[11px] text-emerald-600 mt-1 truncate" title="' + esc(tf('tag.dept.tip', { d: deptOf(item) })) + '">' + esc(deptOf(item)) + '</div>' +
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

  /* -------------------------------------------------------- 子分组（二级） -- */
  /* 2026-09-19 改：BO View 正文里的「Radio, Power & Field Dispatch / Core Network /
     IP Bearer」原来是这里的写死常量 BO_SUBS + i18n 文案，只能改代码、改完还要刷所有人的缓存。
     现在定义随服务端目录一起落盘（catalog.subGroups，见 my_app 的 portal_catalog.py），
     并可在「分组管理」弹窗里增删改 + 拖动看板调整归属，所有人看到同一份。

     数据形状：{ <父分组 id>: [ { id, zh, en }, … ] }，数组顺序 = 展示顺序。
     看板归属仍用 item.boSub（= 子分组 id）：
       · boSub 为空 / 指向不存在的 id → 落到「其他系统」兜底桶（不报错、不丢看板）；
       · 键不存在 = 用内置兜底；键存在但数组为空 = 显式「该分组没有子分组」。
     后端同样按这个语义落盘（空数组不会被吃掉，否则「删干净」会悄悄变回出厂三个）。 */

  /* 允许配置子分组的父分组：**所有分组**（2026-09-19 按需求放开，原来只有 BO View）。
     分组管理弹窗里每个分组都能展开出二级子分组；BO View 正文额外会按子分组分桶渲染
     （见 boBody），其余分组的正文暂不分区显示 —— 但定义与归属都真实存下来，
     将来给某个分组加分区渲染时数据已经就位。 */
  function subCapable(gid) { return !!gid; }

  /** 内置子分组（= 改造前写死的 BO_SUBS）。文案仍走 i18n，中英各取一份 ——
      这样默认态下英文界面显示英文名，且不用把两份文案硬编码进这里。
      ⚠️ 只给 BO View 铺底：其它分组出厂就是「没有子分组」，
      否则一放开就会出现一堆空标题把每个区块撑高。 */
  function builtinSubGroups() {
    return {
      'BO View': [
        { id: 'wireless', zh: I18N.zh['sub.wireless'], en: I18N.en['sub.wireless'] },
        { id: 'core', zh: I18N.zh['sub.core'], en: I18N.en['sub.core'] },
        { id: 'ip', zh: I18N.zh['sub.ip'], en: I18N.en['sub.ip'] }
      ]
    };
  }

  /** 归一化服务端下发的 subGroups：非对象 → null（回落内置）；
      数组里缺 id 的条目丢掉；保留空数组（语义见上）。 */
  function normalizeSubMap(v) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
    var out = {};
    Object.keys(v).forEach(function (gid) {
      if (!Array.isArray(v[gid])) return;
      out[gid] = v[gid].filter(function (s) {
        return s && typeof s === 'object' && s.id;
      }).map(function (s) {
        return { id: String(s.id), zh: s.zh || '', en: s.en || '' };
      });
    });
    return Object.keys(out).length ? out : null;
  }

  /** 某父分组当前生效的子分组定义（服务端优先，缺省回落内置）。 */
  function subGroupsOf(gid) {
    var m = state.subGroups;
    if (m && Object.prototype.hasOwnProperty.call(m, gid)) {
      return Array.isArray(m[gid]) ? m[gid] : [];
    }
    return builtinSubGroups()[gid] || [];
  }

  /** 某看板在**指定父分组**下的二级归属。
      subOf 是权威来源（按分组分别记录）；boSub 只作**迁移前的兜底**：
      仅当整条 subOf 都不存在时，才拿 boSub 去当前分组的定义里校验 ——
      校验通过才认，避免 A 分组的归属被当成 B 分组的（那会串改、甚至丢归属）。
      为什么必须按分组读：一个看板可以同时属于多个分组（实测 no=11/12/13/18/36
      同时挂在 FO View + FLM View），而 boSub 只有一个值。 */
  function subOfItem(it, gid) {
    var m = it && it.subOf;
    var hasSubOf = m && typeof m === 'object' && !Array.isArray(m);
    if (hasSubOf && m[gid]) return String(m[gid]);
    if (hasSubOf) return '';          // subOf 已存在：它说了算，绝不回落（防串改）
    var legacy = (it && it.boSub) ? String(it.boSub) : '';
    if (!legacy) return '';
    /* 迁移前的旧数据：boSub 只对它真正所属的分组有效 ——
       用「该分组下确实有这个名字的子分组」来判定，判不出来就当没有。 */
    return subGroupsOf(gid).some(function (s) { return s.id === legacy; }) ? legacy : '';
  }

  /** 写回归属：只动指定父分组这一格，其它分组的值原样保留（避免串改）。 */
  function withSubOf(it, gid, sid) {
    var c = {};
    Object.keys(it).forEach(function (k) { c[k] = it[k]; });
    var m = {};
    if (it.subOf && typeof it.subOf === 'object' && !Array.isArray(it.subOf)) {
      Object.keys(it.subOf).forEach(function (k) { m[k] = it.subOf[k]; });
    }
    if (sid) m[gid] = sid; else delete m[gid];
    if (Object.keys(m).length) c.subOf = m; else delete c.subOf;
    /* boSub 退化为**只读镜像**（给还没升级的读取方看）：取分组顺序里第一个有归属的值。
       关键点：渲染永远只信 subOf，所以这个镜像再怎么写错，也不会把 A 分组的归属
       泄漏到 B 分组去 —— 之前正是「同步写 boSub + 读取回落 boSub」凑成了串改。 */
    var mirror = '';
    groupsOf(c).forEach(function (g) { if (!mirror && m[g]) mirror = m[g]; });
    if (mirror) c.boSub = mirror; else delete c.boSub;
    return c;
  }

  /** 旧数据迁移：把 boSub 搬进 subOf[真正所属的分组]。
      只在加载时跑一次；subOf 里已有的格子一律不动（它是权威）。
      boSub 仍保留在数据里当镜像，老读取方不受影响。
      判定「真正所属」的依据：该分组下确实定义了同名的子分组。 */
  function migrateSubOf(items) {
    return (items || []).map(function (it) {
      if (!it || typeof it !== 'object') return it;
      var legacy = it.boSub ? String(it.boSub) : '';
      if (!legacy) return it;
      var hasSubOf = it.subOf && typeof it.subOf === 'object' && !Array.isArray(it.subOf);
      /* 定义了这个名字的分组（可能有多个，取第一个；其余分组留空，不猜测） */
      var owner = groupsOf(it).filter(function (g) {
        return subGroupsOf(g).some(function (s) { return s.id === legacy; });
      })[0];
      if (!owner) return it;                                  // 判不出来：原样保留
      if (hasSubOf && it.subOf[owner]) return it;             // 该格已有权威值：不动
      var c = {};
      Object.keys(it).forEach(function (k) { c[k] = it[k]; });
      var m = {};
      if (hasSubOf) Object.keys(it.subOf).forEach(function (k) { m[k] = it.subOf[k]; });
      m[owner] = legacy;
      c.subOf = m;
      return c;
    });
  }

  function subLabel(s) {
    if (!s) return '';
    return state.lang === 'en' ? (s.en || s.zh || s.id) : (s.zh || s.en || s.id);
  }

  /** 某子分组的成员看板（限该父分组内）。 */
  function subMembers(gid, sid) {
    return catalogItems().filter(function (it) {
      return groupsOf(it).indexOf(gid) !== -1 && subOfItem(it, gid) === sid;
    });
  }

  /** 「其他系统」桶：在该父分组里，但二级归属为空或指向已不存在的子分组。
      ⚠️ 它**不是一个存储的实体**，而是每次按当前定义算出来的 ——
      所以它没有 id、不能改名、也不能删除（删了它下一帧又会被算出来）。
      要「清掉」它只有两条路：给里面的看板指定一个子分组，或把它们移出该分组。 */
  function subOthers(gid) {
    var ids = subGroupsOf(gid).map(function (s) { return s.id; });
    return catalogItems().filter(function (it) {
      return groupsOf(it).indexOf(gid) !== -1 && ids.indexOf(subOfItem(it, gid)) === -1;
    });
  }

  function gridOpen(cls) { return '<div class="' + cls + '">'; }

  function bodyHtml(g, items, pack) {
    state._curGid = g.id; // 供 shell() 生成查看器链接时确定「同组」上下文
    if (!items.length) return sectionEmpty(pack);
    /* 该分组配了子分组时，正文一律走「按子分组分区」渲染（2026-09-19 从 BO View 推广到所有分组）。
       原来只有 BO View 会分桶，其它分组即便配了子分组也看不出来 ——
       那等于「改了没反应」。这里统一先分桶，桶内再套用该分组原本的卡片样式，
       所以放开子分组不会改变任何分组「没配子分组时」的观感。 */
    if (subGroupsOf(g.id).length) return subBody(g, items, pack);
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
      default:
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 gap-2.5') +
          items.map(function (it, i) { return solidCard(it, i, true); }).join('') + '</div>';
    }
  }

  /** 该分组「不分子分组时」的正文 HTML —— 供 subBody 的每个桶复用，
      保证分区渲染只是把同一套卡片分堆，不引入第二套样式。 */
  function plainBodyHtml(gid, items) {
    switch (gid) {
      case 'CXO View':
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 gap-3') + items.map(cxoCard).join('') + '</div>';
      case 'MS View':
      case 'FLM View':
      case 'SP View':
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
        return gridOpen('grid grid-cols-2 gap-2.5') + items.map(boCard).join('') + '</div>';
      default:
        return gridOpen('grid grid-cols-1 sm:grid-cols-2 gap-2.5') +
          items.map(function (it, i) { return solidCard(it, i, true); }).join('') + '</div>';
    }
  }

  /* 通用「按子分组分区」正文（2026-09-19 从 BO View 的 boBody 推广而来）。
     items  = 本次真正要画的（折叠态已被截到 limit 条）；
     pack   = sectionItems 的返回，pack.matched 是未截断的全量。
     计数口径（2026-09-18 对齐）：折叠态写「画出来的 / 本子组真实数」（如「2 / 8 项」），
     与区块级胶囊的「6 / 16 个系统」一致；不折叠时只写真实数（如「8 项」）。
     早前这里直接写 list.length，折叠态三个子组会全写「2 项」，看着像数据错了。 */
  function subBody(g, items, pack) {
    var full = (pack && pack.matched) || items;
    var gid = g.id;
    var subs = subGroupsOf(gid);
    var used = {}, html = '';
    function subHead(label, drawn, realN) {
      var n = (drawn < realN) ? drawn + ' / ' + realN : String(realN);
      return '<div class="text-[13px] font-semibold text-slate-600 bg-slate-100 px-2.5 py-1.5 rounded flex items-center justify-between mb-2">' +
        '<span>' + esc(label) + '</span>' +
        '<span class="text-[12px] text-slate-400 font-mono">' + n + ' 项</span></div>';
    }
    subs.forEach(function (s) {
      var list = items.filter(function (it) { return subOfItem(it, gid) === s.id; });
      var realN = full.filter(function (it) { return subOfItem(it, gid) === s.id; }).length;
      list.forEach(function (it) { used[it.no] = true; });
      /* 空子分组不画标题行：默认是折叠态，给没内容的桶留一行空标题会把区块撑高，
         也让「刚建的子分组还没放看板」看起来像渲染出错。 */
      if (!list.length) return;
      html += subHead(subLabel(s), list.length, realN) + plainBodyHtml(gid, list);
    });
    var rest = items.filter(function (it) { return !used[it.no]; });
    if (rest.length) {
      var ids = subs.map(function (s) { return s.id; });
      var restReal = full.filter(function (it) { return ids.indexOf(subOfItem(it, gid)) === -1; }).length;
      html += subHead(t('sub.others'), rest.length, restReal) + plainBodyHtml(gid, rest);
    }
    return '<div class="space-y-3">' + html + '</div>';
  }

  /* BO View 正文：沿用通用分区渲染（保留函数名，调用点无需改）。
     它的子分组是出厂内置的三个（Radio, Power & Field Dispatch / Core Network / IP Bearer），
     现在同样可在「分组管理」里增删改。 */
  function boBody(items, pack) {
    return subBody({ id: 'BO View' }, items, pack);
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
      /* 标题可点：进入 CXO View 的下级页面（该分组看板列表） */
      href: groupHref('CXO View'),
      hrefTip: tf('sec.openTip', { name: t('sec.cxo.title') }),
      /* 2026-09-18 按需求移除标题栏右侧两处「无时间维度、也无实际用途」的文字：
         ·「战略大屏直通率: 100%」—— 100% 是模板里写死的常量，没有任何后端来源，
           永远显示 100%，既不随时间变化也不反映任何真实指标；
         ·「完整系统目录」—— 是个不可点的 <span>（看着像链接，点了没反应），
           真正的下级入口是左侧标题（href=viewer.html?gid=CXO View），功能没丢。
         区块内搜索框是能用的，保留。 */
      tools: sectionSearchHtml('CXO View', pack.hit)
    }) + body;
  }

  /** Quality Control —— 6 张指标卡。
      2026-09-17 起大数字改为数据库实时统计（GET /api/portal-qc/summary，
      见 my_app backend/routers/portal_qc.py），点击卡片改为下钻明细弹窗。
      注意语义变化：原来点卡片是「按该维度筛选看板目录」，该能力**没有丢** ——
      仍在筛选栏的 chip 上（同 id 的 data-act="filter"），两处互不影响。

      2026-09-20 两处口径/列改动（都在后端 portal_qc.py，前端只跟文案）：
      ① TT / WO 的大数字从「未关闭工单数」改为「告警未清除的单数」
         （alarm_clear_time 为空），见 qc.sub.tt / qc.sub.wo 的注释；
      ② TT / WO 下钻的明细列与 my_app 的 TT&WO 看板（?page=ttwo）逐字对齐，
         表头也走那边同一条「下划线转空格 + 首字母大写」规则 ——
         弹窗表头由后端 columns 下发，前端不另写一份，避免两处漂移。

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
    /* 告警优先用「5 分钟级」那份（state.qcAlarm）：它比全量那份新，且失败时会被
       置成 error 态（见 fetchQcAlarm），不会把旧数字留在屏幕上冒充实时值。 */
    if (id === 'alarm' && state.qcAlarm) return state.qcAlarm;
    var m = state.qcStats && state.qcStats.metrics;
    return (m && m[id]) || null;
  }

  /** 面板「更新于」= 两档里较新的那份数据时间（都交给 qcClock 按本地时区渲染）。 */
  function qcLatestStamp() {
    var a = state.qcAlarmAt, f = state.qcFullAt;
    if (a && f) {
      var da = new Date(a).getTime(), df = new Date(f).getTime();
      if (!isNaN(da) && !isNaN(df)) return da >= df ? a : f;
    }
    return a || f || '';
  }

  /** 后端 generated_at → 浏览器本地 HH:MM:SS。
      2026-09-18：后端 portal_qc.py 的时间戳写死 +08:00（datetime.now(timezone(hours=8))），
      而页面右上角时钟用的是浏览器本地时区（本机 = 利比里亚 UTC）—— 直接切字符串会看到
      「时钟 18:07」旁边写着「更新于 02:07」，像是 8 小时前的旧数据，这也是「QC 好像没在
      自动更新」这类误判的来源之一。这里按浏览器本地时区重算，与页面时钟同一把尺子；
      解析失败（后端换了格式）退回原字符串截取，不显示 Invalid Date。 */
  function qcClock(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(11, 19);
    function p(v) { return String(v).padStart(2, '0'); }
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  /** 距下一个「stepMin 分钟的网格 + offsetSec 秒」还有多少毫秒（2026-09-18 加）。
      两档节奏共用：全量 = 60 分钟网格 + 390s（每小时 :06:30，紧跟 eflow_sync 跑完）；
      告警 = 5 分钟网格 + 30s（:00:30 / :05:30 / …，紧跟 eflow_active_alarm 每 5 分钟的同步）。

      用**墙上的钟**算，而不是 interval 累加：interval 从进页面那一刻起算，
      进页面时若是 :07，:06 同步好的数据就要再等 59 分钟才上屏。
      网格以「本地当天 0 点」为原点（而不是 epoch），这样 +05:30 这类半小时时区
      也能对齐到本地的 :06，不会整体偏 30 分钟。 */
  function qcNextDelay(stepMin, offsetSec, now) {
    var n = now || new Date();
    var step = stepMin * 60000;
    var dayStart = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    var since = n.getTime() - dayStart;                 // 本地当天已过的毫秒
    var target = dayStart + Math.floor(since / step) * step + offsetSec * 1000;
    if (target <= n.getTime()) target += step;
    return target - n.getTime();
  }

  /** 倒计时文本 MM:SS（定宽，避免标题栏每秒抖动）。取两档里更近的那次刷新。 */
  function qcCountdown() {
    var left = Math.max(0, Math.round(Math.min(
      qcNextDelay(QC_FULL_MIN, QC_FULL_OFFSET),
      qcNextDelay(QC_ALARM_MIN, QC_ALARM_OFFSET)
    ) / 1000));
    function p(v) { return String(v).padStart(2, '0'); }
    return p(Math.floor(left / 60)) + ':' + p(left % 60);
  }

  function qcSection() {
    /* 精确到秒（原为 HH:MM）：秒在跳，才看得出「页面确实在自动刷新」；
       只到分钟时，轮询 + 后端 60s 缓存叠起来会出现「一分钟没变」的错觉。 */
    var stamp = qcLatestStamp();
    var upd = stamp ? t('qc.updated') + ' ' + qcClock(stamp) : '';
    /* 心跳点：取不到数据时变红且不脉冲 —— 绿色脉冲 = 这个面板正在自动刷新。 */
    var liveDot = (state.qcErr && !state.qcStats)
      ? '<span class="w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0"></span>'
      : '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500 status-pulse-green shrink-0"></span>';
    /* 悬浮说明里带上两档各自的数据时间：分频刷新后，「更新于」只反映较新的那份，
       想知道「其余五项到底多旧」只能看这里。 */
    var tip = tf('qc.cadenceTip', {
      a: state.qcAlarmAt ? qcClock(state.qcAlarmAt) : '—',
      f: state.qcFullAt ? qcClock(state.qcFullAt) : '—',
    });
    var cadence = '<span class="qc-live text-slate-400 text-[13px] font-mono" title="' +
        esc(tip) + '">' + liveDot +
        '<span>' + esc(t('qc.cadence')) + '</span>' +
        '<span class="text-slate-500">·</span>' +
        '<span>' + esc(upd || t('qc.loading')) + '</span>' +
        '<span class="text-slate-500">·</span>' +
        /* 倒计时由 1s 心跳（tick）刷新，不随 paintQc 的重绘走。
           id 必须与下钻弹窗的分页按钮（index.html 的 id="qcNext"）区分开：
           同名时 getElementById 只返回文档里靠前的那个，而 #secQc 在弹窗之前 —— 
           会把弹窗「下一页」按钮的 disabled 打到这个 span 上。 */
        '<span id="qcNextIn">' + esc(tf('qc.next', { t: qcCountdown() })) + '</span>' +
      '</span>';

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

      /* 2026-09-19：大数字由「左对齐」改为「居中」（num 那行加 text-center）。
         标题行（名称 + 图标）与副行（口径 / 报错）**仍保持左对齐** ——
         卡内三行只让数字居中，是需求原话（"卡片上的数字要居中"），
         把整卡都改成 text-center 会连标题和口径一起挪，属于超范围改动。 */
      return '<button type="button" class="text-left bg-gradient-to-br from-slate-50 to-white rounded-lg p-3.5 border ' +
        (on ? 'border-blue-400 ring-1 ring-blue-200' : 'border-slate-200') +
        ' hover:border-blue-400 hover:shadow-md transition group" data-act="qc" data-qc="' + esc(q.id) + '" title="' + esc(tip) + '">' +
        '<div class="flex items-center justify-between text-[14px] font-bold text-slate-700 mb-1">' +
          '<span class="truncate">' + esc(state.lang === 'en' ? q.en : q.zh) + '</span>' +
          '<span class="p-1 rounded bg-blue-50 text-blue-600 shrink-0">' + ico(q.icon) + '</span>' +
        '</div>' +
        '<div class="text-center text-[30px] lg:text-[36px] font-extrabold ' + numCls + ' font-mono tracking-tight group-hover:scale-105 transition-transform mt-1">' +
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
      tools: cadence +
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
  /* QC 刷新节奏（2026-09-18，第三轮定稿：**告警 5 分钟级 / 其余每小时**）。
     先把事实量清楚，再决定节奏 —— 数据源的实际 cron（`GET /api/tasks` 的 current_cron，
     不是 default_cron）：eflow_sync 每小时 :00 起跑、实测约 374s（≈:06 完成，TT/WO/CR/PMT
     的源）；eflow_active_alarm 每 5 分钟（断站告警）。
     SPMS 的源（2026-09-20 更正）：不是 sp_online_sync（那个每小时 :35，写的是
     sp_inbound/sp_outbound/sp_transfer 三张表，本面板根本不读），而是 **sp_data_sync
     「SP 备件数据同步」** —— 它写 inband_details / outband_details，本面板的 SPMS 就是
     数这两张表；该任务 2026-09-20 起由每天 07:00 改为**每小时 :10**（上游 SFTP 本就
     每小时 :00:03 导出一份），所以 SPMS 现在也是小时级，只是它 :10 起跑、末尾还要写
     FineBI 镜像，落在 :06:30 这次刷新之后 → 面板上看到的是上一小时 :10 那份（约 50 分钟前）。
     所以：
       - 全量（tt/wo/cr/pmt/spms/sla + alarm 兜底）：每小时 :06:30 —— 紧跟 eflow_sync 跑完，
         而不是「从进页面起算 60 分钟」（那样 :06 同步好的数据最多要再等 54 分钟才上屏）；
       - 告警单项：每 5 分钟 :00:30/:05:30… —— 它的源每 5 分钟 replace 一次整表，
         按小时刷新会让告警卡最长滞后 1 小时，这是 NOC 看板上最不该旧的一项。
     告警走 `?only=alarm`（后端只算这一项，不重跑 6 条全表 COUNT），前端只覆盖 alarm 一格。
     加载即拉全量、切回前台补拉全量、点「刷新」强制拉全量。 */
  var QC_FULL_MIN = 60;        // 全量：小时网格
  var QC_FULL_OFFSET = 390;    // + :06:30（6*60+30）
  var QC_ALARM_MIN = 5;        // 告警：5 分钟网格
  var QC_ALARM_OFFSET = 30;    // + :00:30
  var QC_MONO_KEY = /^(tt_no|wo_no|cr_id|pmt_no|doc_no|site_id|alarmcode|raised)$/;

  var qcStatsBusy = false;
  var qcAlarmBusy = false;
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
        state.qcFullAt = (data && data.generated_at) || '';
        /* 全量响应里也带 alarm（同一口径、同一段 SQL），把它一并接管：
           ① 首屏就用它给「告警最近」打底，否则 tooltip 在第一次 ?only=alarm 之前显示「—」；
           ② 点「刷新」走的是全量，这样刷新后的告警数与它自己的时间戳成对一致，
              不会出现「数是新的、时间戳还是 5 分钟前那份」。
           失败分支**不动** alarm：它由自己的 5 分钟循环独立维护、有自己的错误态，
           全量挂了不代表告警那份也挂了。 */
        var fa = data && data.metrics && data.metrics.alarm;
        if (fa) state.qcAlarm = fa;
        if (state.qcFullAt) state.qcAlarmAt = state.qcFullAt;
        state.qcErr = '';
        paintQc();
        renderQcDrill();          // 弹窗开着时同步刷新（分页/搜索不变）
      })
      .catch(function (e) {
        qcStatsBusy = false;
        state.qcErr = (e && e.message) || String(e);
        // 清空旧值：宁可显示 —，也不要把上一次的数字留在屏幕上冒充实时统计
        state.qcStats = null;
        state.qcFullAt = '';
        paintQc();
        renderQcDrill();
      });
  }

  /** 只刷「未清除的断站告警」这一项（2026-09-18 加，每 5 分钟一次）。
      走 ?only=alarm：后端只跑那一条 COUNT，不重算其余六项 —— 分频刷新的意义就在这里，
      否则每 5 分钟一次的全量刷新等于把「其余每小时」白做了。
      失败时把 alarm 置成 error 态（而不是保留旧值）：宁可显示「不可用」，
      也不要让一小时前的告警数继续冒充实时值 —— 这是本面板最要紧的一格。 */
  function fetchQcAlarm() {
    if (qcAlarmBusy) return;
    if (REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true) return;
    qcAlarmBusy = true;
    qcApi('/api/portal-qc/summary?only=alarm')
      .then(function (data) {
        qcAlarmBusy = false;
        var m = data && data.metrics && data.metrics.alarm;
        if (!m) throw new Error('响应里没有 metrics.alarm');
        state.qcAlarm = m;
        state.qcAlarmAt = (data && data.generated_at) || '';
        paintQc();
      })
      .catch(function (e) {
        qcAlarmBusy = false;
        state.qcAlarm = { value: null, error: (e && e.message) || String(e) };
        state.qcAlarmAt = '';
        paintQc();
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
        var cls = qcRowClass(row);
        return '<tr' + (cls ? ' class="' + cls + '"' : '') + '>' + d.columns.map(function (c) {
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

  /* ---- 导出：当前搜索条件下的**全部行** → .xlsx（my_app 统一格式）----
     与旧版「导出当前页 CSV」的差别有两点，都是刻意的：

      1) 范围：翻到第 3 页再点导出，旧版只给第 3 页那 50 条；现在按当前搜索关键字把
         total 拉满（后端 _MAX_PAGE_SIZE=200，逐页取），导出的就是「这套筛选结果的全部」
         —— 弹窗底部写着「共 N 条」，导出却只有 50 条说不通。
      2) 格式：套 my_app 的统一格式 UNIFIED_EXCEL_V1（assets/excelReport.js），与
         /myapp/ 各看板的「导出 Excel」同款：标题行 + Generated 副标题 + 深蓝表头 +
         隔行底纹 + 细边框 + 冻结表头 + 自动筛选；不再是裸 CSV。

     单元格取值仍走 qcCell()，保证 Excel 里的值与屏幕上看到的逐字一致。
     注意 toast 里的 qc.noCsv 键名保留（含义已从「没有可导出的 CSV」变成
     「没有可导出的数据」）。 */
  var QC_EXPORT_SIZE = 200;     // = my_app backend/routers/portal_qc.py 的 _MAX_PAGE_SIZE
  var QC_EXPORT_MAX_PAGES = 100; // 兜底：最多 2 万行，避免异常 total 把页面拖死
  var qcExporting = false;

  function qcPad2(n) { return (n < 10 ? '0' : '') + n; }

  /** 文件名时间戳 20260920_141230 */
  function qcFileStamp() {
    var d = new Date();
    return d.getFullYear() + qcPad2(d.getMonth() + 1) + qcPad2(d.getDate()) + '_' +
      qcPad2(d.getHours()) + qcPad2(d.getMinutes()) + qcPad2(d.getSeconds());
  }

  /** 报表副标题时间戳 2026-09-20 14:12:30（与统一格式的默认副标题同形） */
  function qcTextStamp() {
    var d = new Date();
    return d.getFullYear() + '-' + qcPad2(d.getMonth() + 1) + '-' + qcPad2(d.getDate()) + ' ' +
      qcPad2(d.getHours()) + ':' + qcPad2(d.getMinutes()) + ':' + qcPad2(d.getSeconds());
  }

  /** 卡片名（当前语言）→ 报表标题 / sheet 名。Excel 的 sheet 名有字符与长度限制。 */
  function qcMetricLabel(metric) {
    var q = DATA.qc.filter(function (x) { return x.id === metric; })[0];
    return q ? (state.lang === 'en' ? q.en : q.zh) : metric;
  }

  function exportQcExcel() {
    var d = state.qcDrill;
    if (!d.metric) { toast(t('qc.noCsv')); return; }
    if (qcExporting) return;                       // 连点不重复跑
    if (!window.MsExcelReport) { toast(t('qc.exportErr')); return; }

    var metric = d.metric;
    var keyword = d.q || '';
    var label = qcMetricLabel(metric);
    var columns = d.columns.slice();
    var rows = [];
    var btn = document.getElementById('qcExport');
    var btnText = btn ? btn.textContent : '';

    qcExporting = true;
    if (btn) { btn.disabled = true; btn.textContent = t('qc.exporting'); }
    var reset = function () {
      qcExporting = false;
      if (btn) { btn.disabled = false; btn.textContent = btnText; }
    };

    /* 逐页取满。第一页顺便拿 columns/total；中途某页失败就用手上已有的行导出，
       而不是整单作废 —— 导出一半也好过什么都拿不到（失败原因最后一起 toast）。 */
    var page = 1;
    var total = null;
    var failed = null;

    function nextPage() {
      return qcApi('/api/portal-qc/detail?metric=' + encodeURIComponent(metric) +
                   '&page=' + page + '&size=' + QC_EXPORT_SIZE +
                   (keyword ? '&q=' + encodeURIComponent(keyword) : ''))
        .then(function (data) {
          if (total === null) {
            total = data.total || 0;
            if (data.columns && data.columns.length) columns = data.columns;
          }
          var got = data.rows || [];
          rows = rows.concat(got);
          if (got.length && rows.length < total && page < QC_EXPORT_MAX_PAGES) {
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
          toast(failed ? t('qc.exportErr') + ': ' + failed : t('qc.noCsv'));
          return null;
        }
        var sheetName = String(label).replace(/[\\\/\?\*\[\]:]/g, ' ').slice(0, 31);
        var subtitle = 'Generated: ' + qcTextStamp() + '    |    Sheet: ' + sheetName +
          (keyword ? '    |    Search: ' + keyword : '');
        return window.MsExcelReport.exportAoaReport({
          filename: 'qc-' + metric + '-' + qcFileStamp() + '.xlsx',
          sheetName: sheetName,
          title: label + t('qc.drillSuffix'),
          subtitle: subtitle,
          header: columns.map(function (c) { return c.label; }),
          rows: rows.map(function (row) {
            return columns.map(function (c) { return qcCell(row[c.key]); });
          })
        });
      })
      .then(function () {
        reset();
        if (failed) toast(t('qc.exportErr') + ': ' + failed);
      })
      .catch(function (e) {
        reset();
        toast(t('qc.exportErr') + ': ' + ((e && e.message) || String(e)));
      });
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

    /* 2026-09-18 按需求删掉了 Knowledge Q&A 的「知识检索中心 ›」与 Friends Link 的
       「企业导航地图 ›」：与 CXO 的「完整系统目录」同一种写法 —— 蓝色文字 + 箭头，
       但都是不可点的 <span>（无 href / 无 data-act），点了没有任何反应，
       也不带时间维度。区块真正的下级入口是左侧标题（headHtml 的 href）。
       注：其余 6 个区块本来就只挂「计数胶囊 + 区块内搜索框」，不受影响。 */

    if (!SEC_META[g.id] && state.editing) {
      tools += '<button type="button" class="text-[12px] px-2 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-200" ' +
        'data-act="del-group" data-gid="' + esc(g.id) + '">' + esc(t('modal.del')) + '</button>';
    }

    return headHtml({
      kind: meta.kind, title: groupLabel(g), sub: sub, subInline: false,
      /* 标题可点：进入本区块的下级页面（viewer.html?gid=本分组，列出同组全部看板）。
         编辑态 groupHref() 返回空串 → headHtml 退回普通 div，不会误跳走。 */
      href: groupHref(g.id),
      hrefTip: tf('sec.openTip', { name: groupLabel(g) }),
      tools: tools
    }) +
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
        /* 2026-09-18 加 flex-wrap + justify-end：这组按钮（4 个页签 + 刷新 + 新窗口打开）
           最小内容宽约 410px，而窄屏下本行可用宽度只有 356px（#secTopo 388 − p-4 两侧）。
           原来是 nowrap，子元素又都缩不到内容宽以下 → 整组撑到 443px，**横向溢出视口 23px**
           （420px 下实测；`verify_msportal` 的「全断点无横向溢出」一直红的就是这条）。
           改换行后：≥640px 有空间时行为不变，只在 <480px 左右才折成两行。
           同日按需求删掉了行首的绿色「实时」状态点：它只是个常亮动画，
           既不代表地图真的连通、也不带任何时间信息（页面本身的时钟在页头右上角）。 */
        '<div class="flex flex-wrap items-center justify-end gap-1.5">' +
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
    if (badge) {
      badge.hidden = !name;
      badge.textContent = name ? String(name) : '';
      /* 管理员徽标：与 /uniplam/ 的导航一致，让「谁能进用户管理」一眼可辨 */
      badge.setAttribute('data-role', user && user.role === 'admin' ? 'admin' : 'viewer');
    }
    if (out) out.hidden = !name;
    /* 用户管理入口只对管理员出现。
       ⚠️ 但「管理员」在 MsPortal 里有两种来源，必须分清：
         · 门户账号（state.authUser 来自 /uniplam/api/auth/me）—— 带 id，
           这正是能调 /uniplam/api/auth/users* 的身份；
         · my_app 的占位身份（本机回环的 {username:'local'} / 免登录的
           {username:'dev-admin'}）—— **没有 id**，调门户接口只会 401。
       所以按钮按 role 显示（便于发现入口），真正的门户身份校验放在 openUserMgmt()，
       没有门户身份时引导去登录，而不是让用户点开一个必然报错的弹窗。 */
    var umBtn = document.getElementById('userMgmtBtn');
    if (umBtn) {
      umBtn.hidden = !(user && user.role === 'admin');
      umBtn.setAttribute('title', t('um.entryTip'));
    }
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

  /* ==========================================================================
     用户管理（2026-09-20 加）
     --------------------------------------------------------------------------
     目标：让 http://localhost/MsPortal/ 与 http://localhost/uniplam/ 一样能设置
     用户信息（账号、角色、密码、页面/看板权限），并且**两边是同一份数据**。

     为什么天然同库：MsPortal 是 nginx 直接 alias 出去的静态页面，自己没有后端，
     也没有第二份用户表。这里所有读写都打到 /uniplam/api/auth/*，那正是
     server/auth.ts 挂在门户 vite 服务上的同一组接口，落盘在
     <项目根>/auth-data/portal-auth.db（SQLite，WAL + 单事务 + 自动滚动备份）。
     所以在 MsPortal 建/删/改的账号，刷新 /uniplam/ 立刻可见，反之亦然 ——
     不存在「两边各一份、需要同步」的问题，因为从头到尾只有一份。

     与 uniplam 版（src/components/UserManagementModal.tsx）的功能对齐：
       · 存储位置与备份情况   GET  /auth/storage
       · 待审批账号申请       GET  /auth/register-requests  + approve / reject
       · 新增账号             POST /auth/users
       · 删除账号             POST /auth/users/delete
       · 重置密码             POST /auth/users/reset-password
       · 页面配置（落地 + 可见范围）POST /auth/users/profile

     ⚠️ 权限字段的「跨门户」语义（写之前必须搞清楚，否则会互相覆盖）：
       · allowedCards 用的是**两套门户共用的看板 id**（见 dashboardAccessId()：
         myapp 的 ?page= 与 FineBI 的 /webroot/decision/link/... 都映射到
         uniplam 全局目录里的 DashboardItem.id）。实测 51 个看板里 50 个能映射上，
         因此这一项在 /MsPortal/ 与 /uniplam/ 同时生效，是真正通用的那一维。
       · allowedGroups 只是「分组规范名」字符串数组，而两边的分组体系不同：
         MsPortal 用视图分组（MS View / FLM View …），uniplam 用业务分组
         （MS 运维管理 / 告警看板 …）。所以这里给**两组** chips，分别写进同一个
         allowedGroups：各自只在本侧命中，勾了哪边就管哪边。
         这一点很关键 —— 若只提供本侧分组，从 MsPortal 保存就会把管理员在
         /uniplam/ 里设的业务分组白名单整条覆盖掉，形成「改一边丢一边」的假同步。
       · landing 是**整对象替换**（服务端 sanitizeLanding 后整体覆盖），
         所以面板必须把 view 与 cardId 一起回填并一起提交，不能只提交 cardId，
         否则会把 uniplam 侧设的落地视图悄悄清掉。
     ========================================================================== */

  /** 门户鉴权接口基址：与登录/登出同一条路径，经 nginx 落在门户 vite 服务上 */
  var UM_API = '/uniplam/api/auth';

  /** 带 Bearer token 的门户接口调用；401 视为会话失效，回到登录态。 */
  function umCall(path, init) {
    var headers = { Accept: 'application/json' };
    var token = readPortalToken();
    if (token) headers.Authorization = 'Bearer ' + token;
    var opts = { method: (init && init.method) || 'GET', credentials: 'same-origin', headers: headers };
    if (init && init.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(init.body);
    }
    return fetch(UM_API + path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        if (r.status === 401) {
          /* 会话过期：清掉本地 token，让页面回到登录门禁（与 uniplam 的 apiFetch 一致） */
          removePortalToken();
          state.authUser = null;
          state.authOk = null;
        }
        return { ok: r.ok, status: r.status, data: data || {} };
      });
    });
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
      clearTimeout(umFlash._t);
      umFlash._t = setTimeout(function () {
        if (state.um.success === msg) umSet({ success: '' });
      }, 3000);
    }
  }

  /** 本页（MsPortal）的视图分组清单：value = 分组 id（如 'MS View'） */
  function umMsGroups() {
    return allGroups().map(function (g) { return { id: g.id, label: groupLabel(g) }; });
  }

  /** 统一门户的业务分组清单：来自 GET /uniplam/api/portal-default 的 groups。
      拿不到（接口未保存 / 服务未起）时返回 null，面板会给出说明而不是画空列表。 */
  function umPortalGroups() {
    var g = state.um.portalGroups;
    if (!Array.isArray(g) || !g.length) return null;
    return g.map(function (name) { return { id: String(name), label: String(name) }; });
  }

  /** 统一门户业务分组名的显示标签（英文界面下 /uniplam/ 用 groupLabels 映射） */
  function umPortalGroupLabel(cat) {
    var map = state.um.portalGroupLabels;
    if (map && typeof map === 'object' && map[cat]) return String(map[cat]);
    return String(cat || '');
  }

  /** 「按看板」候选项是否来自统一门户的全局目录。
      只有这一份的 id 是 DashboardItem.id —— allowedCards 存的就是它，
      /uniplam/ 侧按同一个字段过滤，所以两边可选项必须同源。
      读不到时会退化成按 URL 推导的本地 id，此时面板会锁住候选项并给出说明。 */
  function umCardsAreShared() {
    return !!(state.um.portalDashboards && state.um.portalDashboards.length);
  }

  /** 本页看板清单（含跨门户共用的 id）：用于「按看板」授权与落地看板选择。
      ⚠️ 优先用 /uniplam/ 的全局目录：MsPortal 自己的目录是另一套 id
      （由 URL 推导），拿它当候选项会勾出一批 /uniplam/ 认不出的值。 */
  function umCards() {
    var shared = state.um.portalDashboards;
    if (Array.isArray(shared) && shared.length) {
      return shared.map(function (d) {
        return {
          id: String(d.id),
          label: String(d.title || d.id),
          group: umPortalGroupLabel(d.category)
        };
      });
    }
    return catalogItems().map(function (it) {
      return { id: dashboardAccessId(it), label: titleOf(it), group: groupLabel(groupById(groupsOf(it)[0])) };
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
          /* 主列表失败才是真失败，包一层「用户数据加载失败：…」让人一眼看出是整块没拉到 */
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
      /* 业务分组来自统一门户的全局目录；GET 是公开的（不需要管理员），
         失败就置 portalGroupsErr，面板会提示「暂不能按业务分组授权」。 */
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
    var mask = document.getElementById('umMask');
    if (!mask) return;
    var user = state.authUser;
    if (!user || user.role !== 'admin') { toast(t('um.needAdmin')); return; }
    /* 没有 id = 这是 my_app 的占位身份（本机 local / 免登录 dev-admin），不是门户账号；
       门户的用户接口只认门户会话，先去登录再回来。 */
    if (!user.id) { toast(t('um.needPortalLogin')); openLogin(); return; }
    state.um.open = true;
    /* 每次打开都清掉上一轮的草稿与提示，避免「上次没保存的勾选」被当成现状 */
    state.um.error = '';
    state.um.success = '';
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
    var mask = document.getElementById('umMask');
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
    var el = document.querySelector('[data-um="landing-view"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }

  function umToggle(list, value) {
    var next = list.slice();
    var i = next.indexOf(value);
    if (i === -1) next.push(value); else next.splice(i, 1);
    return next;
  }

  /** 是否已配置页面（按钮高亮用） */
  function umHasProfile(u) {
    return !!u.landing || u.allowedGroups != null || u.allowedCards != null;
  }

  var UM_VIEWS = ['grid', 'list', 'matrix', 'tasks'];
  function umViewLabel(v) {
    return { grid: t('um.viewGrid'), list: t('um.viewList'), matrix: t('um.viewMatrix'), tasks: t('um.viewTasks') }[v] || v;
  }

  /* ---------------------------------------------------------- 渲染 -- */

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
    return '<div class="um-storage" data-um="storage">' + ico('table', 'um-storage-ico') +
      '<div class="um-storage-txt">' +
        '<div class="um-storage-row"><b>' + esc(t('um.storage')) + '</b>' + bits.join('') + '</div>' +
        '<div class="um-mono" title="' + esc(st.location) + '">' + esc(st.location) + '</div>' +
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
              '<button type="button" class="btn-soft primary" data-um="approve" data-id="' + esc(r.id) + '"' +
                (state.um.busy === 'decide' ? ' disabled' : '') + '>' + ico('check') + esc(t('um.approve')) + '</button>' +
              '<button type="button" class="btn-soft danger" data-um="reject" data-id="' + esc(r.id) + '"' +
                (state.um.busy === 'decide' ? ' disabled' : '') + '>' + ico('trash') + esc(t('um.reject')) + '</button>' +
            '</span></td></tr>';
        }).join('')
      : '<tr><td colspan="5" class="um-empty">' + esc(t('um.pendingEmpty')) + '</td></tr>';

    return '<div class="um-box um-box-warn" data-um="requests-table">' +
      '<div class="um-box-head">' + ico('clock') + '<span>' + esc(t('um.pendingTitle')) + '</span>' +
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
      '<div class="um-box-head">' + ico('plus') + '<span>' + esc(t('um.addTitle')) + '</span></div>' +
      '<div class="um-add-row">' +
        '<input type="text" id="umNewUser" autocomplete="off" placeholder="' + esc(t('um.usernamePh')) + '" value="' + esc(state.um.nu) + '">' +
        '<input type="password" id="umNewPass" autocomplete="new-password" placeholder="' + esc(t('um.passwordPh')) + '" value="' + esc(state.um.np) + '">' +
        '<select id="umNewRole">' +
          '<option value="viewer"' + (state.um.nr === 'viewer' ? ' selected' : '') + '>' + esc(t('um.roleViewer')) + '</option>' +
          '<option value="admin"' + (state.um.nr === 'admin' ? ' selected' : '') + '>' + esc(t('um.roleAdmin')) + '</option>' +
        '</select>' +
        '<button type="submit" class="btn-soft primary" id="umAddBtn"' +
          (busy ? ' disabled' : '') + '>' + ico('plus') + esc(t('um.add')) + '</button>' +
      '</div></form>';
  }

  function umProfileHtml(u) {
    var msGroups = umMsGroups();
    var portalGroups = umPortalGroups();
    var cards = umCards();

    /* locked=true 时按钮渲染成 disabled（见下方「按看板」）：
       统一门户全局目录读不到时，候选 id 是「按 URL 推导」的，与 /uniplam/ 的
       DashboardItem.id 不是同一套 —— 让管理员在这种状态下勾选并保存，等于往共用
       字段里写对方认不出的 id。宁可锁住并说明，也不给一个会写坏数据的开关。 */
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
        '<div class="um-profile-head">' + ico('dashboard') +
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
              (umCardsAreShared() ? '' : '<p class="um-warn">' + ico('warning') + esc(t('um.cardsLocalOnly')) + '</p>') +
            '</div>' +
            (state.um.groups.length === 0 && state.um.cards.length === 0
              ? '<p class="um-warn">' + ico('warning') + esc(t('um.allowedEmpty')) + '</p>' : '') +
          '</div>' : '') +

        '<p class="um-dim um-hint">' + esc(t('um.allowedHint')) + ' ' + esc(t('um.navVisibilityOnly')) + '</p>' +
      '</div></td></tr>';
  }

  /* 账号表。外面挂 data-um="users-table"：面板里还有一张「待审批申请」表，
     两张表的 tr 结构相似，自动化脚本/排查时需要一个明确的锚点来区分
     （否则「等表格出现」会被申请表的空行提前满足）。 */
  function umUsersHtml() {
    var u = state.um;
    if (u.loading && !u.users.length) {
      return '<div class="um-box um-table-wrap" data-um="users-table"><div class="um-empty">' + esc(t('um.loading')) + '</div></div>';
    }
    var admins = u.users.filter(function (x) { return x.role === 'admin'; }).length;
    var me = state.authUser;

    var rows = u.users.map(function (x) {
      var isSelf = !!me && me.id === x.id;
      var lastAdmin = x.role === 'admin' && admins <= 1;
      var blocked = isSelf || lastAdmin;
      var open = u.profileId === x.id;
      var out = '<tr' + (open ? ' class="is-open"' : '') + '>' +
        '<td class="um-strong">' + esc(x.username) +
          (isSelf ? '<span class="um-self">' + esc(t('um.self')) + '</span>' : '') + '</td>' +
        '<td><span class="um-role' + (x.role === 'admin' ? ' is-admin' : '') + '">' +
          (x.role === 'admin' ? ico('shield') : '') +
          esc(x.role === 'admin' ? t('um.roleAdmin') : t('um.roleViewer')) + '</span></td>' +
        '<td class="um-dim um-mono">' + esc(String(x.createdAt || '').slice(0, 19).replace('T', ' ')) + '</td>' +
        '<td class="um-right"><span class="um-row-actions">' +
          '<button type="button" class="um-icon-btn' + (umHasProfile(x) ? ' is-on' : '') + '" data-um="profile" data-id="' + esc(x.id) + '"' +
            ' title="' + esc(t('um.pages')) + '" aria-label="' + esc(t('um.pages')) + '">' + ico('dashboard') + '</button>' +
          '<button type="button" class="um-icon-btn" data-um="reset" data-id="' + esc(x.id) + '"' +
            ' title="' + esc(t('um.reset')) + '" aria-label="' + esc(t('um.reset')) + '">' + ico('key') + '</button>' +
          '<button type="button" class="um-icon-btn is-danger" data-um="delete" data-id="' + esc(x.id) + '"' +
            (blocked ? ' disabled' : '') +
            ' title="' + esc(blocked ? (isSelf ? t('um.selfDelete') : t('um.lastAdmin')) : t('um.delete')) + '"' +
            ' aria-label="' + esc(t('um.delete')) + '">' + ico('trash') + '</button>' +
        '</span></td></tr>';

      if (u.resetId === x.id) {
        out += '<tr class="um-inline-row"><td colspan="4"><div class="um-inline">' +
          '<span class="um-dim">' + esc(tf('um.resetHint', { name: x.username })) + '</span>' +
          '<input type="password" data-um="reset-pwd" autocomplete="new-password" placeholder="' +
            esc(t('um.passwordPh')) + '" value="' + esc(u.resetPwd) + '">' +
          '<button type="button" class="btn-soft primary" data-um="reset-confirm" data-id="' + esc(x.id) + '"' +
            (u.busy === 'reset' || !u.resetPwd ? ' disabled' : '') + '>' + ico('check') + esc(t('um.resetConfirm')) + '</button>' +
        '</div></td></tr>';
      }
      if (open) out += umProfileHtml(x);
      return out;
    }).join('');

    return '<div class="um-box um-table-wrap" data-um="users-table"><div class="um-scroll"><table class="um-table">' +
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
    var body = document.getElementById('umBody');
    if (!body) return;
    var u = state.um;

    var html = '';
    if (u.success) html += '<div class="um-banner is-ok">' + ico('check-circle') + '<span>' + esc(u.success) + '</span></div>';
    if (u.error) html += '<div class="um-banner is-err">' + ico('warning') + '<span>' + esc(u.error) + '</span></div>';
    html += umStorageHtml() + umRequestsHtml() + umAddFormHtml() + umUsersHtml();
    body.innerHTML = html;

    /* 底部固定操作栏：只在页面配置面板展开时出现（与 uniplam 的布局一致） */
    var foot = document.getElementById('umFoot');
    var profileUser = null;
    for (var i = 0; i < u.users.length; i++) {
      if (u.users[i].id === u.profileId) { profileUser = u.users[i]; break; }
    }
    if (foot) {
      foot.hidden = !profileUser;
      var who = document.getElementById('umFootWho');
      if (who) who.textContent = profileUser ? tf('um.pagesTitle', { name: profileUser.username }) : '';
      var save = document.getElementById('umSaveBtn');
      if (save) save.disabled = !!u.saving;
    }
  }

  /* -------------------------------------------------------- 动作 -- */

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
      不受限 → 两个维度都传 null；受限 → 传勾选结果（空数组 = 什么都看不到，语义与
      uniplam 一致）。landing 必须带 view + cardId 一起提交：服务端是整对象替换。 */
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
      /* 以服务端返回的账号为准回填，避免界面与实际配置不一致 */
      var saved = r.data.user;
      state.um.users = state.um.users.map(function (x) { return x.id === saved.id ? saved : x; });
      state.um.profileId = '';
      umFlash('ok', tf('um.pagesSaved', { name: target.username }));
      /* 改的是自己 → 本页可见范围可能变了，刷新登录主体并整体重绘 */
      if (state.authUser && state.authUser.id === saved.id) {
        state.authUser = saved;
        render();
      }
    }).catch(function (e) {
      umFlash('err', String(e));
    }).then(function () {
      state.um.saving = false;
      renderUserMgmt();
    });
  }

  /** 用户管理弹窗的文档级事件委托（面板是整块重画的，不能逐个 addEventListener） */
  function bindUserMgmt() {
    var mask = document.getElementById('umMask');
    if (!mask) return;

    document.getElementById('userMgmtBtn').addEventListener('click', openUserMgmt);
    document.getElementById('umClose').addEventListener('click', closeUserMgmt);
    mask.addEventListener('click', function (e) { if (e.target === mask) closeUserMgmt(); });
    document.getElementById('umReload').addEventListener('click', function () { loadUserMgmt(); });
    document.getElementById('umCancelBtn').addEventListener('click', function () {
      state.um.profileId = '';
      renderUserMgmt();
    });
    document.getElementById('umSaveBtn').addEventListener('click', umSaveProfile);

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
          var u = state.um.users.filter(function (x) { return x.id === id; })[0];
          if (u) umOpenProfile(u);
        }
        return;
      }
      if (act === 'reset') {
        state.um.resetId = state.um.resetId === id ? '' : id;
        state.um.resetPwd = '';
        state.um.error = '';
        renderUserMgmt();
        var inp = document.querySelector('[data-um="reset-pwd"]');
        if (inp) inp.focus();
        return;
      }
      if (act === 'reset-confirm') { umResetPassword(id); return; }
      if (act === 'delete') { umDeleteUser(id); return; }
      if (act === 'approve') { umDecide(id, 'approve'); return; }
      if (act === 'reject') { umDecide(id, 'reject'); return; }
    });
  }

  /** 重置密码输入框的内容变化时只切换「确认重置」按钮的可用态，避免整块重绘丢焦点 */
  function syncUmResetBtn() {
    var btn = document.querySelector('[data-um="reset-confirm"]');
    if (btn) btn.disabled = !String(state.um.resetPwd || '');
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

  /* --------------------------------------- Task Report Files 内嵌卡（2026-09-18 加） --
     位置：右列第三格（原 System Admin 的位置）。按需求改为**直接显示**
     /myapp/?page=email_reports 的页面内容 —— 也就是 my_app 的「任务报告文件中心」。

     为什么不用地图那套 MAP_STRIP_CSS：
       地图卡要注入 CSS 把工具栏/KPI/图表整块隐藏，只留 Leaflet 画布；
       而 my_app 的深链（URL 带 ?page=）**自身就进 bare 模式**，会隐藏它自己的侧栏与
       Header（这一点与 viewer.html 内嵌看板时用的是同一套机制，见 assets/viewer.js 开头），
       所以这里只要一个同源 iframe 就是干净的内容区，不需要再剥壳。

     与地图区对齐的四条规矩：
       ① 未登录**不建** iframe —— 否则会渲染 my_app 自带的英文 "Sign in required" 报错页；
       ② 只有 canSeeDashboard(该看板) 才加载（与目录/搜索口径一致）；
       ③ 主题：my_app 只在**启动时**读一次 localStorage['myapp-theme']，也没有监听父窗口的
          主题消息，所以切主题必须「先写键、再重设 src」（与 viewer.js 的 syncEmbedTheme 同款，
          ⚠️ 同一跨应用副作用：写过之后直接打开 /myapp/ 也是同一主题）；
       ④ 骨架只在「首次渲染 / 切语言 / 被门禁清空」时重建 —— 全局搜索每敲一个字都会走
          render()，若跟着重建，iframe 会被销毁重建、每打一个字都重新请求整个页面。 */
  var EMAIL_PAGE = 'email_reports';
  var emailBuiltLang = null;

  /** 目录里那块 email_reports 看板（拿不到就退回 null，按「无权限」处理） */
  function emailItem() {
    return catalogItems().filter(function (x) {
      return String(x.url || '').indexOf('page=' + EMAIL_PAGE) !== -1;
    })[0] || null;
  }

  function emailAllowed() {
    var item = emailItem();
    return !!item && canSeeDashboard(item);
  }

  /** 内嵌地址：相对路径（门户从 localhost 或 LAN IP 访问都自适应，与地图同一考虑）。
      不带 mwembed=1 —— 那个参数是给地图页用的（my_app 的 isEmbeddedInPortal() 判的是
      ?mwembed=1 或 window.self !== window.top，iframe 内两种都成立），这里带了无副作用
      但也无用，索性保持 URL 与「新窗口打开」完全一致。 */
  function emailSrc() {
    return '/myapp/?page=' + EMAIL_PAGE;
  }

  /** 骨架：标题栏 + 画布，与 topoSection() 同构（同样的类名，保证两卡的观感一致） */
  function emailSection() {
    /* 标题可点（2026-09-18 加，与其余区块标题同款）：点「Task Report Files」= 新标签页直接
       打开报告文件中心全页 /myapp/?page=email_reports —— 与右上角「新窗口」同一个目标
       （用户确认选的方案）。本卡是**单看板内嵌卡**，没有分组下级页，所以不走 groupHref()。
       链接始终可点（未登录 / 无权限时也一样）：目标页自己会出登录页，与「新窗口」按钮
       在未登录时照样赋 href 的口径一致（见 ensureEmail）。
       可点反馈沿用 portal.css 的 .sec-head-link（hover 柔光底 + 标题变色下划线），
       静止态版式不变 —— 与其余区块标题「静止态 1:1、hover 才给反馈」的约定一致。 */
    var head =
      '<div class="flex flex-wrap items-center justify-between pb-2.5 mb-3 border-b border-slate-100 gap-2">' +
        '<a class="flex items-center gap-2 min-w-0 sec-head-link" href="' + esc(emailSrc()) + '" target="_blank" ' +
          'rel="noopener noreferrer" title="' + esc(t('email.openTip')) + '">' +
          '<span class="p-1.5 rounded bg-teal-50 text-teal-600 shrink-0">' + ico('folder', 'text-[20px]') + '</span>' +
          '<div class="min-w-0">' +
            '<h3 class="text-[17px] font-bold text-slate-800 truncate">' + esc(t('email.title')) + '</h3>' +
            '<span class="text-[13px] text-slate-400 truncate block">' + esc(t('email.sub')) + '</span>' +
          '</div>' +
        '</a>' +
        '<div class="flex flex-wrap items-center justify-end gap-1.5">' +
          '<button type="button" class="text-[13px] px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-blue-400 hover:text-blue-600 transition flex items-center gap-1" id="emailRefresh">' +
            ico('refresh', 'text-[13px]') + '<span class="hidden 2xl:inline">' + esc(t('email.refresh')) + '</span></button>' +
          '<a class="text-[13px] px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-blue-400 hover:text-blue-600 transition flex items-center gap-1" id="emailOpen" href="#" target="_blank" rel="noopener noreferrer">' +
            ico('external', 'text-[13px]') + '<span class="hidden 2xl:inline">' + esc(t('email.open')) + '</span></a>' +
        '</div>' +
      '</div>';

    var canvas =
      '<div class="map-canvas embed-canvas map-pattern" id="emailHost">' +
        '<div class="absolute inset-0 flex items-center justify-center gap-2 text-slate-400 text-[14px]" id="emailBoot">' +
          '<span class="w-4 h-4 rounded-full border-2 border-slate-300 border-t-blue-600 animate-spin"></span>' +
          '<span>' + esc(t('email.loading')) + '</span>' +
        '</div>' +
      '</div>';

    return head + canvas;
  }

  /** 加载遮罩：iframe 真正加载完成才隐藏（与 syncMapBoot 同一口径） */
  function syncEmailBoot() {
    var boot = document.getElementById('emailBoot');
    if (!boot) return;
    if (state.authOk === false) { boot.hidden = true; return; }
    var f = document.getElementById('emailFrame');
    boot.hidden = !!(f && f.getAttribute('src') && f.dataset.loaded === '1');
  }

  function renderEmailAuth() {
    var host = document.getElementById('emailHost');
    if (!host) return;
    var el = document.getElementById('emailAuth');
    if (!el) {
      el = document.createElement('div');
      el.id = 'emailAuth';
      host.appendChild(el);
    }
    el.innerHTML = authCardHtml('emailAuth', 'email.auth.title', 'email.auth.tip', 'email.auth.login', 'email.auth.retry');
  }

  function renderEmailNoAccess() {
    var host = document.getElementById('emailHost');
    if (!host) return;
    var el = document.getElementById('emailAuth');
    if (!el) {
      el = document.createElement('div');
      el.id = 'emailAuth';
      host.appendChild(el);
    }
    el.innerHTML = '<div class="map-auth-card">' +
      '<div class="map-auth-ico">' + ico('shield', 'text-[22px]') + '</div>' +
      '<div class="map-auth-title">' + esc(t('email.noAccess')) + '</div>' +
      '</div>';
  }

  function clearEmailAuth() {
    var el = document.getElementById('emailAuth');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  /** 把门户主题写给 my_app（键与 viewer.js 的 EMBED_THEME_KEY 必须一致）。
      必须在赋 src **之前**调用：my_app 只在启动时读一次这个键。 */
  function syncEmailTheme() {
    try {
      var want = state.theme === 'dark' ? 'dark' : 'light';
      if (localStorage.getItem('myapp-theme') !== want) localStorage.setItem('myapp-theme', want);
    } catch (e) { /* 隐私模式下写不了，忽略 */ }
  }

  function ensureEmail() {
    var host = document.getElementById('emailHost');
    if (!host) return;

    // 先定登录态，再决定要不要建 iframe
    if (state.authOk === null) {
      clearEmailAuth();
      syncEmailBoot();
      probeSession();
      return;
    }
    if (state.authOk === false) {
      renderEmailAuth();
      syncEmailBoot();
      // 「新窗口」按钮此时还没被赋过 href，保持 # 会让页面跳到顶部
      var no = document.getElementById('emailOpen');
      if (no) no.href = emailSrc();
      return;
    }
    if (!emailAllowed()) {
      renderEmailNoAccess();
      syncEmailBoot();
      return;
    }
    clearEmailAuth();

    var f = document.getElementById('emailFrame');
    if (!f) {
      f = document.createElement('iframe');
      f.id = 'emailFrame';
      f.setAttribute('title', t('email.title'));
      f.setAttribute('loading', 'lazy');
      // 未设 src 的 iframe 会先加载 about:blank 并触发 load，必须用「是否已设 src」区分
      f.addEventListener('load', function () {
        if (!f.getAttribute('src')) return;
        f.dataset.loaded = '1';
        syncEmailBoot();
      });
      host.appendChild(f);
    }
    f.className = 'absolute inset-0 w-full h-full border-0';
    // 抵消一次整页 zoom，内嵌页不会随门户字号放大被撑出容器（与地图同一处理）
    f.style.zoom = String(1 / fontFactor());

    /* 主题变了要重设 src（my_app 只在启动时读 localStorage，见 syncEmailTheme）。
       判据是「上次加载用的主题」而不是 src 本身 —— emailSrc() 里没有主题参数，
       src 永远不变，拿它比就永远发现不了切主题。用 dataset 记状态而不是另开一个模块级
       变量：这样「首次建 frame」「切主题」「门禁放行后回来」三条路径共用同一段判断，
       不会出现某个入口忘了同步。 */
    var wantTheme = state.theme === 'dark' ? 'dark' : 'light';
    if (!f.getAttribute('src') || f.dataset.theme !== wantTheme) {
      syncEmailTheme();
      f.dataset.theme = wantTheme;
      delete f.dataset.loaded;
      f.setAttribute('src', emailSrc());
    }

    var open = document.getElementById('emailOpen');
    if (open) open.href = emailSrc();
    syncEmailBoot();
  }

  /** 只在必要时重建骨架（首次 / 切语言 / 被未登录门禁清空），见文件头 ④ 的说明 */
  function renderEmailSection() {
    var el = document.getElementById('secEmail');
    if (!el) return;
    if (emailBuiltLang !== state.lang || !el.querySelector('#emailHost')) {
      el.innerHTML = emailSection();
      emailBuiltLang = state.lang;
    }
    ensureEmail();
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
  /* --------------------------------------------------- 拖拽排序 UI（2026-09-20 加） --
     与「编辑分组归属」并列的独立模式，理由：编辑模式的卡片右上角是「编辑 / 删除」按钮，
     拖拽模式下整张卡是拖拽柄 —— 两种命中区叠在一张卡上会互相抢手势。

     层选择只在**能写服务端目录**（catalogEditable，= 服务器本机 / 持令牌）时出现：
     普通局域网用户只能写个人层，给他一个「所有人可见」的开关等于给一个按了没反应的按钮。 */
  function syncOrderUI() {
    var btn = document.getElementById('orderBtn');
    var hint = document.getElementById('orderHint');
    if (!btn || !hint) return;
    var sp = btn.querySelector('span');
    if (sp) sp.textContent = state.ordering ? t('btn.orderOn') : t('btn.order');
    btn.classList.toggle('is-on', !!state.ordering);
    /* 拖拽模式下「编辑分组归属」按不动：两个模式互斥，留着可点会让人以为能同时开 */
    var eb = document.getElementById('editBtn');
    if (eb) {
      eb.disabled = !!state.ordering;
      eb.style.opacity = state.ordering ? '.45' : '';
      eb.style.cursor = state.ordering ? 'not-allowed' : '';
    }
    hint.hidden = !state.ordering;
    if (!state.ordering) return;
    hint.innerHTML = orderHintHtml();
    bindOrderHint();
  }

  /** 提示条：说明 + 层选择 + 恢复默认顺序。用 data-act 交给 bindOrderHint 代理，
      避免每次 syncOrderUI 重写 innerHTML 后监听器丢失。
      样式全部走**内联 + currentColor**：门户的 tailwind.css 是预编译的（没有构建步骤），
      现造类名不会生效；而写死颜色又会在暗色主题下变成一块白底。 */
  function orderHintHtml() {
    var scope = state.orderScope === 'global' ? 'global' : 'local';
    var segBtn = 'padding:0 8px;font:inherit;cursor:pointer;border:1px solid currentColor;' +
      'background:transparent;color:inherit;border-radius:4px;';
    var seg = '';
    if (state.catalogEditable) {
      seg = '<span style="display:inline-flex;margin-left:10px;vertical-align:middle;gap:4px">' +
        ['local', 'global'].map(function (k) {
          var on = scope === k;
          return '<button type="button" data-act="order-scope" data-scope="' + k + '" ' +
            'style="' + segBtn + (on ? 'font-weight:700;opacity:1;' : 'opacity:.6;') + '">' +
            esc(t(k === 'local' ? 'order.scopeLocal' : 'order.scopeGlobal')) + '</button>';
        }).join('') + '</span>';
    }
    return '<span>' + esc(t(scope === 'global' ? 'order.hintGlobal' : 'order.hintLocal')) + '</span>' +
      seg +
      '<button type="button" data-act="order-reset" ' +
      'style="' + segBtn + 'margin-left:10px;opacity:.6;">' + esc(t('order.resetLocal')) + '</button>';
  }

  function bindOrderHint() {
    var hint = document.getElementById('orderHint');
    if (!hint || hint._bound) return;
    hint._bound = true;
    hint.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!b) return;
      var act = b.getAttribute('data-act');
      if (act === 'order-scope') {
        state.orderScope = b.getAttribute('data-scope') === 'global' ? 'global' : 'local';
        syncOrderUI();
      } else if (act === 'order-reset') {
        var gids = Object.keys(state.orderLocal || {});
        if (!gids.length) { toast(t('order.noLocal')); return; }
        if (!window.confirm(t('order.resetConfirm'))) return;
        state.orderLocal = {};
        writeJSON(LS.order, {});
        renderSections();
        toast(t('order.resetDone'));
      }
    });
  }

  /* --------------------------------------------------- 拖拽排序手势（2026-09-20 加） --
     用原生 HTML5 DnD（与「分组管理」弹窗里的拖动同一套），不引第三方库。
     监听挂在 document 上做事件委托：卡片每次 renderSections() 都会整块重建，
     逐张绑监听器会在下一次重绘后全部失效，而且 50+ 张卡逐个绑也没必要。 */
  var orderDragNo = null, orderDragGid = '', orderDragEl = null;
  var orderDropTarget = null, orderDropBefore = false;

  /** 清掉落点提示线（**不动**被拖那张卡的变暗：dragover 换目标时会频繁调用，
      顺手把它也清了会让拖拽过程中卡片一闪一闪）。 */
  function orderDropClear() {
    Array.prototype.forEach.call(document.querySelectorAll('.mp-drag-card'), function (c) {
      c.style.boxShadow = '';
    });
    orderDropTarget = null;
  }

  function orderDragReset() {
    orderDropClear();
    if (orderDragEl) orderDragEl.style.opacity = '';
    orderDragEl = null;
    orderDragNo = null;
    orderDragGid = '';
  }

  /** 指针落在卡片的哪半边 —— 决定插到它前面还是后面。
      网格布局里同一行有两张卡，只看上下会把「插到左边那张之前」判成插到后面，
      所以按主轴（|dx| 与 |dy| 谁大）分别判定，并把提示线画在对应的那一边。 */
  function orderSideOf(card, e) {
    var r = card.getBoundingClientRect();
    var dx = e.clientX - (r.left + r.width / 2);
    var dy = e.clientY - (r.top + r.height / 2);
    var edge;
    if (Math.abs(dx) > Math.abs(dy)) edge = dx < 0 ? 'inset 4px 0 0 0 #2563eb' : 'inset -4px 0 0 0 #2563eb';
    else edge = dy < 0 ? 'inset 0 4px 0 0 #2563eb' : 'inset 0 -4px 0 0 #2563eb';
    return { before: (dx + dy) < 0, edge: edge };
  }

  function bindOrderDrag() {
    document.addEventListener('dragstart', function (e) {
      if (!state.ordering) return;
      var card = e.target.closest ? e.target.closest('.mp-drag-card[data-board-no]') : null;
      if (!card) return;
      orderDragNo = parseInt(card.getAttribute('data-board-no'), 10);
      orderDragGid = card.getAttribute('data-gid') || '';
      orderDragEl = card;
      card.style.opacity = '.4';
      try {
        e.dataTransfer.setData('text/plain', String(orderDragNo));
        e.dataTransfer.effectAllowed = 'move';
      } catch (err) { /* 少数环境不允许设 dataTransfer，不影响排序本身 */ }
    });

    document.addEventListener('dragover', function (e) {
      if (!state.ordering || orderDragNo === null) return;
      var card = e.target.closest ? e.target.closest('.mp-drag-card[data-board-no]') : null;
      /* 只在**同一区块内**排序。跨区块拖属于「改分组归属」，归「分组管理」弹窗管 ——
         两处入口都做同一件事只会让人困惑。不 preventDefault 就不会触发 drop，
         所以「不同区块」天然落不下去，不需要额外的失败提示。 */
      if (!card || card.getAttribute('data-gid') !== orderDragGid) return;
      if (parseInt(card.getAttribute('data-board-no'), 10) === orderDragNo) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
      var side = orderSideOf(card, e);
      if (orderDropTarget !== card) {
        orderDropClear();
        orderDropTarget = card;
      }
      orderDropBefore = side.before;
      card.style.boxShadow = side.edge;
    });

    document.addEventListener('drop', function (e) {
      if (!state.ordering || orderDragNo === null) return;
      var card = e.target.closest ? e.target.closest('.mp-drag-card[data-board-no]') : null;
      if (!card || card.getAttribute('data-gid') !== orderDragGid) return;
      e.preventDefault();
      var gid = orderDragGid, dragNo = orderDragNo;
      var seq = reorderSequence(gid, dragNo, parseInt(card.getAttribute('data-board-no'), 10), orderDropBefore);
      orderDragReset();
      if (!seq) return;
      /* 层选择：只有能写服务端目录的人才能选「所有人可见」，
         其余一律落个人层（前端这里再兜一次，避免出现「选了全局但 403」的假失败）。 */
      var scope = (state.catalogEditable && state.orderScope === 'global') ? 'global' : 'local';
      saveOrder(gid, seq, scope);
    });

    document.addEventListener('dragend', orderDragReset);
  }

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
    /* 用户管理面板的表头/按钮/提示都是本文件动态写入的，切语言要跟着重建
       （静态文案由上面的 data-i18n 循环处理）。弹窗开着才重画，避免白做功。 */
    if (state.um.open) renderUserMgmt();

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
    syncOrderUI();

    chipHtml();
    /* 控制条折叠态下要回显「当前生效的搜索词 / 筛选」——
       筛选或搜索一变就得同步，否则折叠着的按钮里还写着上一轮的旧条件。 */
    syncBarSummary();

    // 未登录门禁：门禁生效时不再渲染任何看板区块（目录/链接/统计都不能漏出去）
    applyGate();
    if (REQUIRE_LOGIN_FOR_CATALOG && state.authOk !== true) {
      // 清掉可能残留的旧内容，避免只是被 CSS 藏起来
      ['secCxo', 'secQc', 'secTopo', 'secEsc', 'secMs', 'secFlm', 'secSp', 'secFo', 'secBo',
       'secAdmin', 'secEmail', 'secQa', 'secFriends', 'secExtra'].forEach(function (id) {
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
    /* Task Report Files 内嵌卡（原 System Admin 的位置）：与地图/升级机制同理只在 render()
       里建，不放进 renderSections()。区别是它**自带 iframe**，所以内部再分一层
       renderEmailSection()：骨架按需重建，iframe 尽量复用（理由见该函数上方 ④）。 */
    renderEmailSection();
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
    var editable = !!state.catalogEditable;
    document.getElementById('groupTableBody').innerHTML = allGroups().map(function (g) {
      var n = catalogItems().filter(function (it) { return groupsOf(it).indexOf(g.id) !== -1; }).length;
      var open = subCapable(g.id) && state.subOpen === g.id;
      return '<tr data-gid="' + esc(g.id) + '"' + (open ? ' class="sub-open"' : '') + '>' +
        '<td class="tree">' + (subCapable(g.id) ? subToggleHtml(g.id, open) : '') + '</td>' +
        '<td><input type="text" data-field="zh" value="' + esc(g.zh || g.id) + '"></td>' +
        '<td><input type="text" data-field="en" value="' + esc(g.en || g.id) + '"></td>' +
        '<td class="cnt">' + n + '</td>' +
        '<td>' + (isBuiltinGroup(g.id) ? '' : '<button type="button" class="del" data-act="del-group" data-gid="' +
          esc(g.id) + '">' + esc(t('modal.del')) + '</button>') + '</td>' +
      '</tr>' + (open ? subPanelHtml(g.id, editable) : '');
    }).join('');
    /* 子分组说明按当前权限换一份：非本机（局域网）访问时整块是只读的，
       不写清楚的话用户会以为「拖不动是坏了」。 */
    var note = document.getElementById('groupSubNote');
    if (note) note.textContent = editable ? t('subm.hint') : t('subm.readonlyHint');
  }

  /** 树形展开箭头。用内联 SVG 而不是字符，避免不同字体下 ▸/▾ 大小不一。 */
  function subToggleHtml(gid, open) {
    return '<button type="button" class="sub-toggle' + (open ? ' open' : '') + '"' +
      ' data-act="toggle-subs" data-gid="' + esc(gid) + '"' +
      ' aria-expanded="' + (open ? 'true' : 'false') + '"' +
      ' title="' + esc(open ? t('subm.collapse') : t('subm.expand')) + '">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"></polyline></svg>' +
      '</button>';
  }

  /** 二级子分组面板：每个子分组一行（名称 + 计数 + 成员看板 chips + 加入选择器），
      末尾是「其他系统」兜底桶与「新增子分组」行。
      chips 容器始终渲染（哪怕为空）—— 它是拖拽的落点，空的时候也得能接住拖动。 */
  function subPanelHtml(gid, editable) {
    var subs = subGroupsOf(gid);
    var html = subs.map(function (s) {
      var members = subMembers(gid, s.id);
      return '<tr class="sub-row" data-parent="' + esc(gid) + '" data-sub="' + esc(s.id) + '">' +
        '<td class="sub-rail"></td>' +
        '<td colspan="4">' +
          '<div class="sub-line">' +
            (editable
              ? '<input type="text" class="sub-name" data-subfield="zh" maxlength="64" value="' + esc(s.zh || '') +
                  '" placeholder="' + esc(t('subm.addZh')) + '">' +
                '<input type="text" class="sub-name" data-subfield="en" maxlength="64" value="' + esc(s.en || '') +
                  '" placeholder="' + esc(t('subm.addEn')) + '">'
              : '<span class="sub-label">' + esc(subLabel(s)) + '</span>') +
            '<span class="sub-cnt" title="' + esc(t('modal.colCount')) + '">' + members.length + '</span>' +
            (editable
              ? '<button type="button" class="del" data-act="del-sub" data-gid="' + esc(gid) +
                  '" data-sub="' + esc(s.id) + '">' + esc(t('subm.del')) + '</button>'
              : '') +
          '</div>' +
          subChipsHtml(gid, s.id, members, editable) +
          (editable ? subPickerHtml(gid, s.id) : '') +
        '</td></tr>';
    }).join('');

    /* 「其他系统」兜底桶：**不是一条存储的定义**，而是每次按当前子分组算出来的 ——
       subOfItem(it, gid) 为空、或指向一个已被删掉的子分组 id 的看板，都落在这里。
       所以它没有 id、不能改名、也不能删除：删掉它下一帧又会被算出来。
       要让它变空只有两条路 —— 给里面的看板指定一个子分组，或把它们移出本分组。
       这里显式打上 auto 标记与 title 说明，免得用户反复找「删除」按钮。 */
    var others = subOthers(gid);
    html += '<tr class="sub-row sub-others" data-parent="' + esc(gid) + '" data-sub="">' +
      '<td class="sub-rail"></td>' +
      '<td colspan="4">' +
        '<div class="sub-line">' +
          '<span class="sub-label" title="' + esc(t('subm.othersTip')) + '">' + esc(t('subm.others')) + '</span>' +
          '<span class="sub-auto" title="' + esc(t('subm.othersTip')) + '">' + esc(t('subm.othersAuto')) + '</span>' +
          '<span class="sub-cnt">' + others.length + '</span>' +
        '</div>' +
        subChipsHtml(gid, '', others, editable) +
        (others.length ? '' : '<div class="sub-pick none">' + esc(t('subm.othersEmpty')) + '</div>') +
      '</td></tr>';

    if (editable) {
      /* ⚠️ tr 的类名刻意叫 sub-add-tr 而不是 sub-add-row：后者是里面那个 div 的类，
         两者同名时 `.sub-add-row{display:flex}` 会命中 <tr>，表格行布局垮掉、
         输入框被压成几十像素宽（2026-09-19 实测踩到并修复）。 */
      html += '<tr class="sub-row sub-add-tr" data-parent="' + esc(gid) + '">' +
        '<td class="sub-rail"></td>' +
        '<td colspan="4">' +
          '<div class="sub-add-row">' +
            '<input type="text" data-subnew="zh" maxlength="64" placeholder="' + esc(t('subm.addZh')) + '">' +
            '<input type="text" data-subnew="en" maxlength="64" placeholder="' + esc(t('subm.addEn')) + '">' +
            '<button type="button" class="btn-soft primary" data-act="add-sub" data-gid="' + esc(gid) + '">' +
              esc(t('subm.add')) + '</button>' +
          '</div>' +
        '</td></tr>';
    }
    return html;
  }

  function subChipsHtml(gid, sid, members, editable) {
    var chips = members.map(function (it) {
      var no = esc(it.no);
      return '<span class="sub-chip"' + (editable ? ' draggable="true"' : '') + ' data-no="' + no + '">' +
        '<span class="chip-title">' + esc(titleOf(it)) + '</span>' +
        /* 「其他系统」桶里的卡片不给「移出」按钮 —— 它已经在桶里了，再移出是无操作 */
        (editable && sid
          ? '<button type="button" class="chip-x" data-act="sub-remove" data-gid="' + esc(gid) +
              '" data-sub="' + esc(sid) + '" data-no="' + no + '" title="' + esc(t('subm.remove')) + '">×</button>'
          : '') +
      '</span>';
    }).join('');
    return '<div class="sub-chips' + (members.length ? '' : ' empty') + '"' +
      ' data-drop="' + esc(gid) + '" data-drop-sub="' + esc(sid) + '">' +
      (chips || '<span class="sub-empty">' + esc(t('subm.noBoards')) + '</span>') +
    '</div>';
  }

  /** 非拖拽路径：下拉选择把某张看板直接放进本子分组（键盘/触屏/无障碍用）。
      池子 = 本分组下「归属不等于本子分组」的看板，所以「其他系统」桶里的看板
      也能从这里被指定进某个子分组（那正是清空兜底桶的正规做法）。
      判重必须走 subOfItem(it, gid)：直接读 boSub 会把别的分组的归属也算进来。 */
  function subPickerHtml(gid, sid) {
    var pool = catalogItems().filter(function (it) {
      return groupsOf(it).indexOf(gid) !== -1 && subOfItem(it, gid) !== sid;
    });
    if (!pool.length) return '<div class="sub-pick none">' + esc(t('subm.pickNone')) + '</div>';
    return '<div class="sub-pick"><select data-act="sub-add-board" data-gid="' + esc(gid) +
      '" data-sub="' + esc(sid) + '"><option value="">' + esc(t('subm.pick')) + '…</option>' +
      pool.map(function (it) {
        return '<option value="' + esc(it.no) + '">' + esc(titleOf(it)) + '</option>';
      }).join('') +
    '</select></div>';
  }

  function saveGroupTable() {
    var custom = [], renamed = [];
    document.querySelectorAll('#groupTableBody tr').forEach(function (tr) {
      var gid = tr.getAttribute('data-gid');
      /* 二级子分组行（subPanelHtml 产出）也在同一张表里，它们没有 data-gid。
         不过滤的话会被当成一个 id=null 的分组塞进 state.groups，把自建分组表弄脏。 */
      if (!gid) return;
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
      catalog: state.catalog || null, subGroups: state.subGroups || null
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
        /* 子分组先落 state：紧接着的 saveCatalog(o.catalog) 会把 state.subGroups
           一并带给服务端（省略参数 = 沿用 state），所以顺序不能颠倒。 */
        if (o.subGroups && typeof o.subGroups === 'object') {
          state.subGroups = normalizeSubMap(o.subGroups);
          if (state.subGroups) writeJSON(LS.subGroups, state.subGroups);
        }
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

    /* 用户管理弹窗（2026-09-20 加）：入口按钮 + 整块重画的面板事件委托 */
    bindUserMgmt();

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

    document.getElementById('orderBtn').addEventListener('click', function () {
      state.ordering = !state.ordering;
      closeMenu();
      if (state.ordering) {
        /* 与编辑模式互斥：编辑模式的卡片上有「编辑 / 删除」按钮，
           拖拽模式下整张卡是拖拽柄，两个一起开必然互相抢手势。 */
        state.editing = false;
        setBarOpen(true);   // 提示条与层选择都在控制条那一行里，收着等于功能"消失"
      }
      render();
    });
    bindOrderDrag();

    document.getElementById('editBtn').addEventListener('click', function () {
      state.editing = !state.editing;
      closeMenu();
      /* 进编辑模式就把控制条展开：编辑用的按钮（新增看板 / 分组管理 / 导出 /
         恢复默认）全在那一行里，收着等于功能"消失"，用户会以为没做。 */
      if (state.editing) { state.ordering = false; setBarOpen(true); }
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
      subDraft = null;                 // 每次打开都从服务器当前值重新开始
      renderGroupTable();
      syncSubSaveBtn();
      mask.hidden = false;
    });
    document.getElementById('modalClose').addEventListener('click', function () {
      if (!resolveDraftBeforeClose()) return;   // 有未保存改动：先问，取消则留在弹窗
      saveGroupTable(); mask.hidden = true;
    });
    mask.addEventListener('click', function (e) {
      if (e.target !== mask) return;
      if (!resolveDraftBeforeClose()) return;
      saveGroupTable(); mask.hidden = true;
    });
    var subSaveBtn = document.getElementById('subSaveBtn');
    if (subSaveBtn) subSaveBtn.addEventListener('click', function () { commitDraft(); });

    /* ================= 分组管理弹窗：子分组（二级分组，2026-09-19 加） =================
       行的 HTML 由 renderGroupTable() 每次重建，所以交互全部走 #groupTableBody 上的
       事件委托 —— 挂在 tbody 元素本身（它不重建）比挂 document 更收敛，也不会和
       文档级那套 [data-act] 委托互相抢事件。

       持久化走的是 /api/portal-catalog 的**整体 PUT**：子分组定义（catalog.subGroups）
       与看板归属（item.boSub）在同一份文档里，一次请求原子生效 ——
       所以「删子分组」和「把成员移进其他系统」必须一起提交，不能分两次。 */
    var gtBody = document.getElementById('groupTableBody');

    /** 当前生效的完整子分组定义（内置铺底 + 已定义分组覆盖）。
        提交时必须给全量：PUT 是整体替换，只发一个父分组会把别的分组定义抹掉。 */
    function currentSubMap() {
      var out = {}, base = builtinSubGroups(), m = state.subGroups || {};
      Object.keys(base).forEach(function (k) { out[k] = base[k].slice(); });
      Object.keys(m).forEach(function (k) {
        out[k] = (m[k] || []).map(function (s) { return { id: s.id, zh: s.zh || '', en: s.en || '' }; });
      });
      return out;
    }

    /* ---- 草稿态（2026-09-19 按需求加）----
       原来子分组是「点一下立刻 PUT 到服务器」：用户看不到任何保存入口，
       改完不知道到底存没存、也没法反悔。现在改为先在内存里改草稿，
       底部出现「保存子分组」按钮，点了才整体提交一次。

       草稿只活在弹窗打开期间：关闭弹窗时若还有未保存改动会先问一句，
       避免「改了半天、顺手点关闭、全丢了」。 */
    var subDraft = null;   // {map, items} —— null = 当前没有未保存改动

    function draftActive() { return !!subDraft; }

    /** 取草稿（没有就用当前生效值开一份）。map = 子分组定义，items = 看板目录。 */
    function ensureDraft() {
      if (!subDraft) {
        subDraft = {
          map: currentSubMap(),
          items: catalogItems().map(function (it) {
            var c = {};
            Object.keys(it).forEach(function (k) { c[k] = it[k]; });
            return c;
          })
        };
      }
      return subDraft;
    }

    /** 把草稿同步进 state（不落盘），让弹窗里的面板立刻反映刚才的改动。 */
    function applyDraft() {
      if (!subDraft) return;
      state.subGroups = subDraft.map;
      state.catalog = subDraft.items;
      renderGroupTable();
      syncSubSaveBtn();
    }

    /** 底部「保存子分组」按钮的可用态：没改动 / 只读时禁用，改动数写在按钮上。 */
    function syncSubSaveBtn() {
      var btn = document.getElementById('subSaveBtn');
      var hint = document.getElementById('subDirtyHint');
      if (!btn) return;
      var dirty = draftActive() && state.catalogEditable;
      btn.disabled = !dirty;
      if (hint) hint.hidden = !dirty;
      btn.title = state.catalogEditable ? '' : t('subm.readonly');
    }

    /** 提交草稿：定义 + 归属 + 目录一次性整体 PUT（同一份文档，原子生效）。 */
    function commitDraft() {
      if (!state.catalogEditable) { toast(t('subm.readonly')); return; }
      if (!subDraft) return;
      var d = subDraft;
      subDraft = null;
      var p = saveCatalog(d.items, t('subm.saved'), d.map);
      p.then(function () {
        if (!mask.hidden) { renderGroupTable(); syncSubSaveBtn(); }
      });
      /* 立即重绘：saveCatalog 已同步改过 state，面板先按提交后的值显示，
         服务端回来（成功用归一化结果 / 失败回本机兜底）再对齐一次。 */
      renderGroupTable();
      syncSubSaveBtn();
    }

    /** 关闭弹窗前处理未保存草稿：确认则保存，取消则留在弹窗里。 */
    function resolveDraftBeforeClose() {
      if (!draftActive()) return true;
      if (!window.confirm(t('subm.unsaved'))) return false;
      commitDraft();
      return true;
    }

    /** 保存子分组（兼容旧调用点）：草稿存在则提交草稿，否则按传入值直接提交。 */
    function persistSubGroups(map, okMsg, items) {
      if (!state.catalogEditable) { toast(t('subm.readonly')); return; }
      var p = saveCatalog(items || catalogItems(), okMsg || t('subm.saved'), map);
      /* 乐观刷新：saveCatalog 已经同步改过 state，先把弹窗里的 chips 挪到位，
         请求回来（成功用服务端归一化结果 / 失败回本机兜底）再刷一次对齐。 */
      if (!mask.hidden) renderGroupTable();
      p.then(function () { if (!mask.hidden) renderGroupTable(); });
    }

    /** 改某张看板在**指定父分组**下的子分组归属：sid 为空 = 移入「其他系统」。
        只动 subOf[父分组] 这一格，其它分组的值原样保留 —— 看板可同时属于多个分组
        （no=11/12/13/18/36），共用一个 boSub 会让两个分组互相串改。 */
    function itemsWithBoardSub(no, gid, sid) {
      return catalogItems().map(function (it) {
        return String(it.no) === String(no) ? withSubOf(it, gid, sid) : it;
      });
    }

    /** 改归属 → 进草稿（不再立刻写服务端）。 */
    function moveBoard(no, gid, sid) {
      if (!state.catalogEditable) { toast(t('subm.readonly')); return; }
      var d = ensureDraft();
      var idx = -1;
      d.items.forEach(function (it, i) { if (String(it.no) === String(no)) idx = i; });
      if (idx < 0) return;
      if (subOfItem(d.items[idx], gid) === (sid || '')) return;   // 原地拖回：不产生改动
      d.items[idx] = withSubOf(d.items[idx], gid, sid);
      applyDraft();
    }

    function addSubGroup(btn) {
      if (!state.catalogEditable) { toast(t('subm.readonly')); return; }
      var row = btn.closest('.sub-add-row');
      if (!row) return;
      var zh = row.querySelector('[data-subnew="zh"]').value.trim();
      var en = row.querySelector('[data-subnew="en"]').value.trim();
      if (!zh && !en) { toast(t('subm.emptyName')); return; }
      var gid = btn.getAttribute('data-gid');
      /* id 直接取显示名（与「新增分组」同一套做法），因为归属里存的就是它。
         代价是 id 不可改：改 id 等于让已有归属全部指向一个不存在的子分组，
         所以编辑态只开放 zh/en 两个标签（见 commitSubName）。 */
      var id = (en || zh).trim();
      var d = ensureDraft();
      var list = d.map[gid] || [];
      if (list.some(function (s) { return s.id.toLowerCase() === id.toLowerCase(); })) {
        toast(t('subm.dup'));
        return;
      }
      list.push({ id: id, zh: zh || id, en: en || id });
      d.map[gid] = list;
      applyDraft();
    }

    function deleteSubGroup(gid, sid) {
      if (!state.catalogEditable) { toast(t('subm.readonly')); return; }
      var s = subGroupsOf(gid).filter(function (x) { return x.id === sid; })[0];
      var members = subMembers(gid, sid);
      if (!window.confirm(tf('subm.delConfirm', { name: s ? subLabel(s) : sid, n: members.length }))) return;
      var d = ensureDraft();
      d.map[gid] = (d.map[gid] || []).filter(function (x) { return x.id !== sid; });
      /* 成员落回「其他系统」：顺手把指向该子分组的归属清掉（只清这个分组那一格）。
         不清的话服务端会留一批指向不存在子分组的看板 —— 前端有兜底不会出错，
         但下次谁再建一个同名 id 的子分组，这批看板会「自己跳回去」，很吓人。 */
      d.items = d.items.map(function (it) {
        if (groupsOf(it).indexOf(gid) === -1 || subOfItem(it, gid) !== sid) return it;
        return withSubOf(it, gid, '');
      });
      applyDraft();
    }

    /** 子分组改名：只动 zh/en 两个标签，id 保持不动（id 是归属的取值）。
        同样只进草稿，等用户点「保存子分组」才落盘。 */
    function commitSubName(inp) {
      if (!state.catalogEditable) return;
      var tr = inp.closest('[data-sub]');
      if (!tr) return;
      var gid = tr.getAttribute('data-parent');
      var sid = tr.getAttribute('data-sub');
      if (!gid || !sid) return;                      // 「其他系统」桶没有名字可改
      var zhEl = tr.querySelector('[data-subfield="zh"]');
      var enEl = tr.querySelector('[data-subfield="en"]');
      if (!zhEl || !enEl) return;
      var zh = zhEl.value.trim(), en = enEl.value.trim();
      var cur = subGroupsOf(gid).filter(function (x) { return x.id === sid; })[0];
      if (!cur) return;
      if (cur.zh === zh && cur.en === en) return;    // 没改就不开草稿（blur 触发很频繁）
      if (!zh && !en) { toast(t('subm.emptyName')); renderGroupTable(); return; }
      var d = ensureDraft();
      var s = (d.map[gid] || []).filter(function (x) { return x.id === sid; })[0];
      if (!s) return;
      s.zh = zh || en;
      s.en = en || zh;
      applyDraft();
    }

    gtBody.addEventListener('click', function (e) {
      var tg = e.target.closest('[data-act="toggle-subs"]');
      if (tg) {
        var gid = tg.getAttribute('data-gid');
        state.subOpen = (state.subOpen === gid) ? null : gid;
        renderGroupTable();
        return;
      }
      var add = e.target.closest('[data-act="add-sub"]');
      if (add) { addSubGroup(add); return; }
      var del = e.target.closest('[data-act="del-sub"]');
      if (del) { deleteSubGroup(del.getAttribute('data-gid'), del.getAttribute('data-sub')); return; }
      var rm = e.target.closest('[data-act="sub-remove"]');
      if (rm) { moveBoard(rm.getAttribute('data-no'), rm.getAttribute('data-gid'), ''); return; }
    });

    /* 非拖拽路径：下拉选一张看板直接放进本子分组（键盘 / 触屏 / 无障碍） */
    gtBody.addEventListener('change', function (e) {
      var sel = e.target.closest('[data-act="sub-add-board"]');
      if (!sel || !sel.value) return;
      moveBoard(sel.value, sel.getAttribute('data-gid'), sel.getAttribute('data-sub'));
    });

    /* blur 不冒泡，必须用捕获阶段才收得到子分组名输入框的失焦提交 */
    gtBody.addEventListener('blur', function (e) {
      var inp = e.target && e.target.closest ? e.target.closest('[data-subfield]') : null;
      if (inp) commitSubName(inp);
    }, true);

    /* 回车即提交子分组改名（不用先点别处再等 blur）；blur 那条是兜底。
       提交后 state 已乐观更新，所以随后的 blur 会在 commitSubName 里提前 return。 */
    gtBody.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      var inp = e.target && e.target.closest ? e.target.closest('[data-subfield]') : null;
      if (!inp) return;
      e.preventDefault();
      commitSubName(inp);
      inp.blur();
    });

    /* ---- 拖拽：chip 从一个子分组拖到另一个；拖进「其他系统」= 取消归类 ---- */
    var subDragNo = null;
    gtBody.addEventListener('dragstart', function (e) {
      var chip = e.target.closest ? e.target.closest('.sub-chip[draggable="true"]') : null;
      if (!chip) return;
      subDragNo = chip.getAttribute('data-no');
      try { e.dataTransfer.setData('text/plain', subDragNo); } catch (err) { /* 某些浏览器只允许在 dragstart 里设 */ }
      e.dataTransfer.effectAllowed = 'move';
      chip.classList.add('dragging');
    });
    gtBody.addEventListener('dragover', function (e) {
      if (subDragNo === null) return;
      var zone = e.target.closest ? e.target.closest('[data-drop]') : null;
      if (!zone) return;
      e.preventDefault();                 // 不 preventDefault 就不会触发 drop
      e.dataTransfer.dropEffect = 'move';
      zone.classList.add('drop-hot');
    });
    gtBody.addEventListener('dragleave', function (e) {
      var zone = e.target.closest ? e.target.closest('[data-drop]') : null;
      if (zone) zone.classList.remove('drop-hot');
    });
    gtBody.addEventListener('drop', function (e) {
      var zone = e.target.closest ? e.target.closest('[data-drop]') : null;
      if (!zone || subDragNo === null) return;
      e.preventDefault();
      zone.classList.remove('drop-hot');
      var no = subDragNo;
      subDragNo = null;
      moveBoard(no, zone.getAttribute('data-drop'), zone.getAttribute('data-drop-sub') || '');
    });
    gtBody.addEventListener('dragend', function () {
      subDragNo = null;
      Array.prototype.forEach.call(gtBody.querySelectorAll('.sub-chips.drop-hot'), function (z) {
        z.classList.remove('drop-hot');
      });
    });

    /* ---- QC 下钻弹窗（骨架见 index.html 的 QcDrillModal） ---- */
    var qcMask = document.getElementById('qcMask');
    var qcSearch = document.getElementById('qcSearch');
    document.getElementById('qcClose').addEventListener('click', closeQcDrill);
    qcMask.addEventListener('click', function (e) { if (e.target === qcMask) closeQcDrill(); });
    document.getElementById('qcReload').addEventListener('click', function () { fetchQcDrill(); });
    document.getElementById('qcExport').addEventListener('click', exportQcExcel);
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
      /* 个人层拖拽顺序也一起清（2026-09-20 加）：「恢复默认」的语义是
         「我这边所有本机改动都回到默认」，只清分组归属而留着顺序，
         用户会看到「点了恢复默认，卡片顺序却没变」。全局层顺序不在这里清 ——
         它存在服务端、影响所有人，入口是「恢复出厂目录」。 */
      state.orderLocal = {};
      writeJSON(LS.assign, {}); writeJSON(LS.groups, []); writeJSON(LS.renames, []);
      writeJSON(LS.order, {});
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

      /* Task Report Files 内嵌卡的「刷新」：与地图同一个道理 —— 按钮在 #secEmail 里，
         而那个区块每次 render() 都可能重建骨架，所以只能走文档级事件委托。 */
      var erf = e.target.closest('#emailRefresh');
      if (erf) {
        e.preventDefault();
        var ef = document.getElementById('emailFrame');
        var eboot = document.getElementById('emailBoot');
        if (eboot) eboot.hidden = false;
        if (!ef) { ensureEmail(); return; }
        delete ef.dataset.loaded;
        try { ef.contentWindow.location.reload(); }
        catch (err) { ef.setAttribute('src', emailSrc()); }
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
      /* QC 标题栏「下次 MM:SS」倒计时（2026-09-18 加）：paintQc() 只在自己那一轮重绘
         #secQc，倒计时若跟着它走就会长时间不动、看着像卡死；这里借页面本来就有的 1s 心跳刷新。
         元素不存在（未登录 / 窄屏 / 区块重建中）时静默跳过。
         id 用 qcNextIn：下钻弹窗的分页按钮（index.html）已占用 qcNext，
         同名会让 getElementById 只认文档里靠前的那个（#secQc 在弹窗之前）。 */
      var next = document.getElementById('qcNextIn');
      if (next) next.textContent = tf('qc.next', { t: qcCountdown() });
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
        if (state.um.open) closeUserMgmt();
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
  /* 本机兜底目录里的旧数据也要迁移：服务端目录在 loadCatalog() 里迁移，
     但「服务端目录为空 / 未登录」时用的是 localStorage 或 data.js 那份，
     不迁的话老 boSub 会在 subOf 出现后被当成「无归属」。 */
  if (state.catalog) state.catalog = migrateSubOf(state.catalog);
  render();
  syncMapZoom();

  /* QC 统计的两档自动刷新（2026-09-18）：
       - 全量（其余五项 + 达标率 + 告警兜底）：每小时 :06:30 对齐，紧跟 eflow_sync 跑完；
       - 告警单项：每 5 分钟 :00:30/:05:30… 对齐，紧跟 eflow_active_alarm 的整表 replace。
     两者都用 setTimeout 自链而不是 setInterval —— 对齐要按墙上的钟算，
     interval 只会从进页面那一刻起累加，进页面时若是 :07，下一轮就整体偏了。
     首次数据由 probeSession 登录成功后拉全量（已含告警），故这里不必再补首屏。
     切回前台补一次全量：后台标签页的定时器会被浏览器降频甚至冻结，
     不补的话回到页面时看到的可能是几小时前的数字（比「延迟刷新」更容易被误读成故障）。 */
  (function qcLoopFull() {
    setTimeout(function () {
      fetchQcStats();
      qcLoopFull();
    }, qcNextDelay(QC_FULL_MIN, QC_FULL_OFFSET));
  })();
  (function qcLoopAlarm() {
    /* 开页面时先补一发 ?only=alarm：首屏那三个告警数字是从全量里借来的，
       时间戳走的也是全量的时间轴（每小时 :06:30），而告警这里的刻度是 :00:30/:05:30。
       不补的话页面刚进来时「告警最近」可能是近一小时前的旧时间，得等下一个 5 分钟
       刻度才被刷新 —— 期间 tooltip 显示的时间与真实新鲜度对不上。 */
    setTimeout(fetchQcAlarm, 0);
    setTimeout(function () {
      fetchQcAlarm();
      qcLoopAlarm();
    }, qcNextDelay(QC_ALARM_MIN, QC_ALARM_OFFSET));
  })();
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { fetchQcStats(); fetchQcAlarm(); }
  });
})();
