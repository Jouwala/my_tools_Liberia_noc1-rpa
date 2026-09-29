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
        本页自己的持久化只有 `olbr.*`，且只有主题 / 语言 / 页签，不含目录。
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
      /* 检索轨默认收起成一条（2026-09-22）：入口要图标 + 文字，光一个放大镜图标不够直白 */
      'rail.btn': '搜索与筛选', 'rail.tip': '展开搜索框与分组 / 状态筛选（Ctrl K）',
      'count.all': '{n} 个看板 · {g} 个分组',
      'count.hit': '{n} / {t} 个看板命中',
      'qc.title': 'Quality Control 质量监控核心指标',
      'qc.sub': '未清除告警 / 工单 / 变更 / 维护 / 备件 · 30 天达标口径',
      'qc.sla': '30 天达标率',
      'qc.slaTip': '近 {d} 天创建的 TT 中 SLA 判定为 Pass 的占比（分母只含已判定 Pass/Failed 的单，'
        + '在途未判定的不计入）：{pass} / {total}',
      'qc.err': '数据库统计不可用', 'qc.retry': '重试',
      'qc.drill': '点击查看明细',
      /* QC 指标卡与 MsPortal 的 Quality Control 对齐（2026-09-22）。
         阈值、趋势口径、两档刷新节奏都照抄 portal.js，文案也沿用同一套说法 ——
         同一个数字在两个门户上被读成两件事，比样式不一致更糟。 */
      'qc.updated': '更新于', 'qc.next': '下次 {t}', 'qc.reload': '刷新', 'qc.loading': '加载中…',
      'qc.na': '不可用',
      'qc.lv.ok': '正常', 'qc.lv.warn': '关注', 'qc.lv.crit': '严重', 'qc.lv.na': '不可用',
      'qc.dataAt': '数据 {t}（{ago}）',
      'qc.ago.now': '刚刚', 'qc.ago.min': '{n} 分钟前', 'qc.ago.hour': '{n} 小时前', 'qc.ago.day': '{n} 天前',
      'qc.sites': '断站站点', 'qc.overdue': '超期', 'qc.inbound': '入库', 'qc.outbound': '出库',
      'qc.sub.alarm': '未清除的断站告警', 'qc.sub.tt': '告警未清除的故障工单 (TT)',
      'qc.sub.wo': '告警未清除的任务工单 (WO)', 'qc.sub.cr': '未关闭变更单 (CR)',
      'qc.sub.pmt': '未完成的预防性维护 (PMT)',
      'qc.sub.spms': '未关闭出入库单 (SPMS，不含 WaitingForUpdate)',
      'qc.targetTip.up': '分级阈值：关注 ≥ {warn} · 严重 ≥ {crit}（数值越大越差）',
      'qc.targetTip.down': '分级阈值：关注 < {crit} · 严重 < {warn}（数值越大越好）',
      'qc.trend.cap': '近 {n} 天新增 {total} 次（每格 {unit}）',
      'qc.trend.capToday': '今天 {total} 次（每格 {unit}）',
      'qc.trend.hours': '1 小时', 'qc.trend.days': '1 天',
      'qc.trend.tip': '按源表时间列分桶的「新增量」（近 {n} 天，每格 {unit}）。\n'
                    + '空档补 0：那段时间确实没有新增。\n'
                    + '注意这是「来单速度」，不是卡片上那个「存量」，两者量级不同、不能互相印证。',
      'qc.trend.tipToday': '按源表时间列分桶的「新增量」（今天 00:00 至 23:00，每格 {unit}）。\n'
                    + '空档补 0：那个小时确实没有新告警。\n'
                    + '最后一格是「尚未走完的当前小时」，值会随分钟继续增长。\n'
                    + '注意这是「新告警速度」，不是卡片上那个「存量」，两者不能互相印证。',
      'qc.trend.starving': '趋势数据不足',
      'qc.cadenceTip': '本面板分两档刷新：断站告警每 5 分钟（源 eflow_active_alarm 每 5 分钟同步，最近 {a}）；'
                     + 'TT/WO/CR/PMT/SPMS 与达标率每小时 :06（源 eflow_sync 每小时 :00 起跑、实测约 :06 跑完，'
                     + 'SP 备件明细 sp_data_sync 每小时 :10，最近 {f}）。切回本页或点「刷新」会立刻重拉全量。',
      'cxo.title': 'CXO View 决策战略层', 'cxo.sub': '统一总控与运营视窗',
      'map.title': '利比里亚网络拓扑全景', 'map.sub': 'Central Liberia Regional Topology',
      'map.gis': '全球地图', 'map.mw': '微波实时', 'map.alarm': '实时告警', 'map.loss': '传输丢包',
      'map.open': '新窗口打开', 'map.reload': '重新加载', 'map.load': '加载中…',
      /* 报告文件页签（2026-09-22 加）：内嵌 my_app 的任务报告文件中心，
         标题说法与 MsPortal 那张 Task Report Files 卡一致，同一内容在两个门户不该有两名。 */
      'email.tab': '报告文件',
      'email.title': 'Task Report Files', 'email.sub': '任务报告文件中心（Email Reports）',
      'email.needLogin': '登录后显示报告文件',
      'email.noAccess': '当前账号没有「Task Report Files」这块看板的权限',
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
      'edit.kGroups': '一级分组', 'edit.kLabels': '地图页签名',
      'edit.maptabTip': '改这个地图页签的中文名 / 英文名（存服务端，所有人可见；两项都清空则恢复默认）',
      'edit.maptabRenamed': '地图页签名已更新',
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
      /* 2026-09-23 统一下钻弹窗：补齐与 MsPortal 同名同义的文案键。
         MsPortal 侧对应 qc.reload / qc.export / qc.openBoard / qc.filterHint /
         qc.loading / qc.page / qc.total / qc.drillSuffix / qc.exportErr。 */
      'dr.reload': '刷新', 'dr.export': '导出 Excel', 'dr.openBoard': '打开完整看板',
      'dr.filterHint': '提示：按维度筛选看板列表请用筛选条，这个弹窗只下钻明细。',
      'dr.drillSuffix': ' · 明细', 'dr.total': '共 {n} 条', 'dr.exportErr': '导出失败',
      'dr.noData': '没有可导出的数据',
      'env.local': '本机', 'env.lr': '利比里亚',
      'foot.ver': 'Ver 1.0-OLBR · 展示版',
      'doc.title': 'OLR MS 门户 · Liberia NOC/SOC 统一入口 (ZTE OLR MS Portal)',
      'doc.desc': 'ZTE OLR MS 门户看板 —— 利比里亚 NOC/SOC 自动化工具平台入口（展示版）。',
      'attr.theme': '深色 / 浅色',
      'attr.adminTitle': '看板维护仍在 MsPortal 完成（本页改分组、子分组、排序与用户权限）',
      'attr.searchAria': '搜索看板', 'attr.chipsAria': '分组筛选', 'attr.statusAria': '状态筛选',
      'attr.drQAria': '过滤明细',
      /* ---- 用户管理（2026-09-22 加）----
         文案与 /uniplam/ 的 UserManagementModal、/MsPortal/ 的移植版同一口径，
         因为三者操作的是**同一份用户数据库**（auth-data/portal-auth.db）：
         本页只调 /uniplam/api/auth/*，不复制用户表，改完另一边刷新即可见。
         只有提到「本页」的两处把 MsPortal 换成了 olbrportal —— 分组体系按本页算。 */
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
      'um.groupsMsportal': '按分组 · 本页（/olbrportal/）',
      'um.groupsPortal': '按分组 · 统一门户（/uniplam/）',
      'um.groupsPortalNone': '统一门户未保存全局目录，暂不能按业务分组授权',
      'um.allowedCards': '按看板（两边通用）',
      'um.cardsLocalOnly': '读不到统一门户的全局目录，候选项暂时锁住：这里的看板 id 是按 URL 推导的，与 /uniplam/ 实际使用的那套不一致，勾选后保存会让对方认不出来。请刷新重试。',
      'um.allowedHint': '「按看板」用的是两套门户共用的看板 id，勾选后在 /olbrportal/ 与 /uniplam/ 同时生效；两组「按分组」各自只在本侧生效，可都勾。',
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
      'um.notFound': '申请不存在或已被处理'
    },
    en: {
      'tagline': 'Smarter Operations · Higher Efficiency · Better Network',
      'mast.admin': 'Admin portal', 'mast.uni': 'Unified portal', 'mast.logout': 'Sign out',
      'skip': 'Skip to main content',
      'search.ph': 'Search dashboards, owners, tags…',
      'rail.all': 'All', 'rail.clear': 'Clear filters',
      'rail.btn': 'Search & filters', 'rail.tip': 'Open the search box and the group / status filters (Ctrl K)',
      'count.all': '{n} dashboards · {g} groups',
      'count.hit': '{n} / {t} dashboards match',
      'qc.title': 'Quality Control — key indicators',
      'qc.sub': 'Active alarms / tickets / changes / PMT / spares · 30-day compliance',
      'qc.sla': '30-day compliance',
      'qc.slaTip': 'Share of TTs created in the last {d} days rated Pass on SLA (the denominator counts '
        + 'only tickets already judged Pass/Failed; in-flight ones are excluded): {pass} / {total}',
      'qc.err': 'Database stats unavailable', 'qc.retry': 'Retry',
      'qc.drill': 'Click for details',
      'qc.updated': 'Updated', 'qc.next': 'next {t}', 'qc.reload': 'Refresh', 'qc.loading': 'Loading…',
      'qc.na': 'n/a',
      'qc.lv.ok': 'OK', 'qc.lv.warn': 'Watch', 'qc.lv.crit': 'Critical', 'qc.lv.na': 'N/A',
      'qc.dataAt': 'data {t} ({ago})',
      'qc.ago.now': 'just now', 'qc.ago.min': '{n}m ago', 'qc.ago.hour': '{n}h ago', 'qc.ago.day': '{n}d ago',
      'qc.sites': 'sites down', 'qc.overdue': 'overdue', 'qc.inbound': 'Inbound', 'qc.outbound': 'Outbound',
      'qc.sub.alarm': 'Uncleared site-outage alarms', 'qc.sub.tt': 'Trouble tickets with uncleared alarm',
      'qc.sub.wo': 'Work orders with uncleared alarm', 'qc.sub.cr': 'Unclosed change requests',
      'qc.sub.pmt': 'Pending preventive maintenance',
      'qc.sub.spms': 'Unclosed inbound/outbound orders (excl. WaitingForUpdate)',
      'qc.targetTip.up': 'Thresholds: watch ≥ {warn} · critical ≥ {crit} (higher is worse)',
      'qc.targetTip.down': 'Thresholds: watch < {crit} · critical < {warn} (higher is better)',
      'qc.trend.cap': 'New in last {n}d: {total} (per {unit})',
      'qc.trend.capToday': 'Today: {total} (per {unit})',
      'qc.trend.hours': '1h', 'qc.trend.days': '1 day',
      'qc.trend.tip': 'New items bucketed by the source time column (last {n} days, per {unit}).\n'
                    + 'Empty buckets are filled with 0 (nothing was raised then).\n'
                    + 'Note: this is incoming rate, not the backlog shown above.',
      'qc.trend.tipToday': 'New items bucketed by the source time column (today 00:00-23:00, per {unit}).\n'
                    + 'Empty buckets are filled with 0 (no new alarm in that hour).\n'
                    + 'The last bucket is the current, still-running hour.\n'
                    + 'Note: this is the incoming alarm rate, not the backlog shown above.',
      'qc.trend.starving': 'Not enough trend data',
      'qc.cadenceTip': 'Two refresh cadences: site-outage alarms every 5 min (source eflow_active_alarm syncs every '
                     + '5 min, latest {a}); TT/WO/CR/PMT/SPMS and the SLA rate hourly at :06 (eflow_sync starts at '
                     + ':00 and takes ~6 min, the SP spare-part details sync sp_data_sync runs hourly at :10, '
                     + 'latest {f}). Coming back to this tab or clicking Refresh re-pulls the full set immediately.',
      'cxo.title': 'CXO View', 'cxo.sub': 'Executive strategy & operation window',
      'map.title': 'Central Liberia Regional Topology', 'map.sub': 'Network panorama',
      'map.gis': 'Global Map', 'map.mw': 'MW real-time', 'map.alarm': 'Live alarms', 'map.loss': 'Packet loss',
      'map.open': 'Open in new tab', 'map.reload': 'Reload', 'map.load': 'Loading…',
      'email.tab': 'Report files',
      'email.title': 'Task Report Files', 'email.sub': 'Task report file center (Email Reports)',
      'email.needLogin': 'Sign in to view the report files',
      'email.noAccess': 'This account has no access to the "Task Report Files" dashboard',
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
      /* bannerK 是横幅左侧的短标签，与 banner 成对出现；之前只登记了 zh，
         t() 未命中时回落 zh，导致英文模式这里漏出「编辑模式」。 */
      'edit.bannerK': 'Editing',
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
      'edit.kGroups': 'first-level groups', 'edit.kLabels': 'map tab labels',
      'edit.maptabTip': 'Edit this map tab’s Chinese / English name (stored on the server, visible to everyone; clear both to restore the default)',
      'edit.maptabRenamed': 'Map tab label updated',
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
      'dr.reload': 'Refresh', 'dr.export': 'Export Excel', 'dr.openBoard': 'Open full dashboard',
      'dr.filterHint': 'Note: filtering the catalogue by dimension lives on the filter bar chips; this dialog only drills into details.',
      'dr.drillSuffix': ' · Details', 'dr.total': '{n} rows in total', 'dr.exportErr': 'Export failed',
      'dr.noData': 'Nothing to export',
      'env.local': 'Local host', 'env.lr': 'Liberia',
      'foot.ver': 'Ver 1.0-OLBR · showcase edition',
      'doc.title': 'OLR MS Portal · Liberia NOC/SOC unified entry',
      'doc.desc': 'ZTE OLR MS portal — entry to the Liberia NOC/SOC automation tool platform (showcase edition).',
      'attr.theme': 'Dark / Light',
      'attr.adminTitle': 'Dashboard maintenance stays in MsPortal (this page edits groups, sub-groups, order and user access)',
      'attr.searchAria': 'Search dashboards', 'attr.chipsAria': 'Group filter', 'attr.statusAria': 'Status filter',
      'attr.drQAria': 'Filter rows',
      /* ---- User management (added 2026-09-22) ---- mirrors the zh um.* set 1:1 */
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
      'um.groupsMsportal': 'By group · this page (/olbrportal/)',
      'um.groupsPortal': 'By group · unified portal (/uniplam/)',
      'um.groupsPortalNone': 'The unified portal has no saved global catalog, so business groups cannot be granted yet',
      'um.allowedCards': 'By dashboard (shared by both)',
      'um.cardsLocalOnly': 'The unified-portal global catalogue could not be read, so these options are locked: the dashboard ids here are derived from URLs and do not match the set /uniplam/ actually uses — saving them would leave values it cannot recognise. Please refresh and retry.',
      'um.allowedHint': 'The dashboard allowlist uses ids shared by both portals, so it applies to /olbrportal/ and /uniplam/ at once; each group list only affects its own side, and both may be used together.',
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
      'um.pendingTitle': 'Pending requests',
      'um.pendingEmpty': 'No pending requests',
      'um.colApplicant': 'Applicant',
      'um.colNote': 'Note',
      'um.colTime': 'Requested',
      'um.colIp': 'Source IP',
      'um.approve': 'Approve',
      'um.reject': 'Reject',
      'um.approveConfirm': 'Approve the account request from {name}?',
      'um.rejectConfirm': 'Reject the account request from {name}?',
      'um.approved': 'Approved {name}: the password they chose is now active, change required at first login',
      'um.rejected': 'Rejected the account request from {name}',
      'um.notFound': 'Request not found or already handled'
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
    'arrow-up-right': 'ph-arrow-up-right', 'shield': 'ph-shield-check', 'globe': 'ph-globe-hemisphere-west',
    refresh: 'ph-arrows-clockwise',
    /* 用户管理弹窗用的几个（MsPortal 那边是内联 svg，本页统一走 phosphor 字体图标） */
    plus: 'ph-plus', check: 'ph-check', 'check-circle': 'ph-check-circle', trash: 'ph-trash',
    'user-plus': 'ph-user-plus', 'user-check': 'ph-user-check', 'user-x': 'ph-user-x'
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
  /* 保留伪页签 key：本栏标题/副标题不是地图页签，但与页签共用同一份
     catalog.tabLabels 存储和改名浮层（2026-09-23 加）。__ 前缀与上面的 OTHER 同一约定，
     且 my_app 的 page 值（gis/mwRealTime/…）不会以双下划线开头，不会撞名。
     后端 TAB_PAGES 里有同名白名单，两处必须一起改。 */
  var RENAME_HEAD = '__head';
  /** 所有可从界面上改名的项：4 个页签 + 本栏标题/副标题。 */
  var RENAME_KEYS = MAP_TABS.map(function (m) { return m.page; }).concat([RENAME_HEAD]);
  /* 页签条最右边的「报告文件」：内嵌 my_app 的任务报告文件中心（MsPortal 右列同名卡）。
     EMAIL_TAB 不是分组 id —— 它没有 gid，不进目录、不参与筛选与计数，所以往下任何
     一处拿到它都不能拼 viewer 链接（vlink / groupHref 只认看板的 no / 真分组）。 */
  var EMAIL_PAGE = 'email_reports';
  var EMAIL_TAB = '__email';
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
    /* 2026-10-14：加 `:not(.gis-legend-overlay)` —— 该选择器会命中 GIS 地图上的
       图例浮层（.ant-card-body 里唯一「不是 .leaflet-container」的直接子元素），
       给它刷 !important 白底、盖掉 index.css 的 transparent，使门户内嵌与
       直开 /myapp/?page=gis 的图例观感不一致。完整推导见
       v1/olbrportal/assets/olbr-data.js 同一行。 */
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)):not(.gis-legend-overlay){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
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
    /* 断站告警单独一档（每 5 分钟），其余五项 + 达标率一小时一档：
       六项里只有告警的源表高频变化，用全量轮询追它等于每小时白跑十一次。 */
    qcAlarm: null, qcFullAt: '', qcAlarmAt: '', qcTrend: {},
    escOpen: false, escLv: 'LEVEL1',
    auxOpen: {},
    /* 检索轨（搜索 + 分组 / 状态筛选）默认收起。刻意不写 localStorage：
       用户的预期就是「每次进来都是干净的一条」，跟筛选条件一样不跨会话。 */
    railOpen: false,
    mapTab: ls('olbr.maptab', 'gis'),
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
    popForm: null,                        /* 改名类浮层：{kind:'grp'|'grpadd'|'title'|'maptab', id} */
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
    /* 收起态唯一的一条信息出口：不写「49 全部」这种在展开区里读得通、单看一条却莫名其妙的话，
       直接走 count.all / count.hit 两句完整文案，后面再缀上「是按什么筛的」。
       没有这行，收起时就变成「下面的卡莫名其妙少了」—— 所以它跟清除按钮同生同灭。 */
    var sum = $('#railSum');
    if (sum) {
      var bits = [];
      if (tk.length) bits.push('「' + esc(String(state.q).trim()) + '」');
      if (state.group !== 'all') bits.push(esc(gName(state.group)));
      if (state.status !== 'all') bits.push(esc(state.status));
      sum.innerHTML = (filtering() ? tf('count.hit', { n: '<b>' + hit + '</b>', t: all.length })
        : tf('count.all', { n: '<b>' + all.length + '</b>', g: state.groups.length })) +
        (bits.length ? ' <i class="dot">·</i> ' + bits.map(function (x) { return '<em>' + x + '</em>'; }).join(' ') : '');
    }
  }

  /** 展开 / 收起检索轨。展开态不进 localStorage（见 state.railOpen），只负责把 DOM 和 aria 对齐。 */
  function setRailOpen(on) {
    state.railOpen = !!on;
    var rail = $('#rail'), inp = $('#railIn'), btn = $('#railBtn');
    if (!rail || !inp || !btn) return;
    rail.classList.toggle('is-open', state.railOpen);
    inp.hidden = !state.railOpen;
    btn.setAttribute('aria-expanded', state.railOpen ? 'true' : 'false');
  }

  /* =============== QC 指标卡（与 MsPortal 的 Quality Control 同一套口径）===============
     阈值 / 趋势分桶 / 两档刷新节奏照抄 MsPortal/assets/portal.js 的 2026-09-22 改版实现，
     连文案都沿用同一份 —— 同一个数字在两个门户上给出不同的红黄判定，比样式不一致更糟。
     ⚠️ QC_TARGETS 是**首版默认值**（依据只有实测量级 + NOC 常识），不是业务方给的目标值；
        正式目标到位后只改这一处，并且记得同步 MsPortal 那份。 */
  var QC_TARGETS = {
    alarm: { dir: 'up', warn: 10, crit: 30 },
    tt: { dir: 'up', warn: 30, crit: 80 },
    wo: { dir: 'up', warn: 50, crit: 150 },
    cr: { dir: 'up', warn: 100, crit: 250 },
    pmt: { dir: 'up', warn: 1000, crit: 2000 },
    spms: { dir: 'up', warn: 150, crit: 400 },
    sla: { dir: 'down', warn: 90, crit: 95 }
  };
  /* 主卡 = 当班要立刻有人动的；次卡 = 周期性消化的积压。
     六张等宽同排后「主/次」靠字号表达，不再各占一行分组小标题。 */
  var QC_PRIMARY_ORDER = ['alarm', 'tt', 'wo'];
  var QC_SECONDARY_ORDER = ['cr', 'pmt', 'spms'];
  /* 只有这四项后端提供「新增量」趋势（cr / pmt 明确回 no_trend）：不发请求、也不画线。 */
  var QC_TREND_METRICS = ['alarm', 'tt', 'wo', 'spms'];
  var QC_SUB_KEY = { alarm: 'qc.sub.alarm', tt: 'qc.sub.tt', wo: 'qc.sub.wo',
    cr: 'qc.sub.cr', pmt: 'qc.sub.pmt', spms: 'qc.sub.spms' };
  var QC_LV_KEY = { ok: 'qc.lv.ok', warn: 'qc.lv.warn', crit: 'qc.lv.crit', na: 'qc.lv.na' };
  /* 全量每小时 :06:30（紧跟 eflow_sync 跑完），告警每 5 分钟 :00:30（紧跟整表 replace）。 */
  var QC_FULL_MIN = 60, QC_FULL_OFFSET = 390, QC_ALARM_MIN = 5, QC_ALARM_OFFSET = 30;

  function fmt(n) { return n == null || isNaN(Number(n)) ? '—' : Number(n).toLocaleString('en-US'); }
  /* 分级只看数值：无值 / 非数字 / 没配阈值一律 'na'，绝不当成 0、也绝不当成正常。
     达标率必须走 dir='down'，否则 95% 这种好值会被判进最严重一档 —— 分级一旦出现
     这种反向误报，运维就会整体忽略它。 */
  function qcLevel(id, v) {
    var tg = QC_TARGETS[id];
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
      qcNextDelay(QC_FULL_MIN, QC_FULL_OFFSET),
      qcNextDelay(QC_ALARM_MIN, QC_ALARM_OFFSET)) / 1000));
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
    if (Math.round((end - start) / stepMs) + 1 > MAX_SLOTS) {
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
     preserveAspectRatio=none 让它随卡宽拉伸，所以刻意不画端点圆点（会被拉成椭圆）。 */
  function qcSpark(id) {
    var s = qcTrendSeries(id);
    if (!s || s.vals.length < 2) return '';
    var vals = s.vals, W = 300, H = 26, PAD = 4;
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    var span = (max - min) || 1, step = W / (vals.length - 1);
    var pts = vals.map(function (n, i) {
      return [i * step, PAD + (H - PAD * 2) * (1 - (n - min) / span)];
    });
    var line = pts.map(function (p, i) {
      return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
    }).join(' ');
    return '<span class="qc-spark" aria-hidden="true"><svg viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none"><path class="sp-area" d="' + line + ' L' + W + ' ' + H +
      ' L0 ' + H + ' Z"/><path class="sp-line" d="' + line +
      '" vector-effect="non-scaling-stroke"/></svg></span>';
  }
  /* 三种状态要分清，否则首屏三行「趋势积累中」看着像报错：
       有趋势且点够 → 画线 + 说明；接口通了但点不够 → 只给说明；无趋势 → 不占位。
     说明文字带「窗口 + 每格时长」：折线是流量（新增量）、大数字是存量（积压），
     不说清单位就没法把两者对上。 */
  function qcSparkSlot(id) {
    var s = qcTrendSeries(id), spark = qcSpark(id);
    if (!spark) return s ? '<span class="qc-spark-empty">' + esc(t('qc.trend.starving')) + '</span>' : '';
    var v = { total: fmt(s.total), unit: t(s.grain === 'day' ? 'qc.trend.days' : 'qc.trend.hours'),
      n: s.days || s.labels.length };
    var c = s.window === 'today' ? { k: 'qc.trend.capToday', tip: 'qc.trend.tipToday' }
                                 : { k: 'qc.trend.cap', tip: 'qc.trend.tip' };
    return '<span class="qc-spark-wrap" title="' + esc(tf(c.tip, v)) + '">' + spark +
      '<span class="qc-spark-cap">' + esc(tf(c.k, v)) + '</span></span>';
  }

  function qcCardHtml(d) {
    var m = qcMetric(d.id);
    /* 失败分两种：整体取不到（全量都没回来）与单项失败（后端逐项容错）。
       两种都按「不可用」呈现，绝不能留上一次的旧数字冒充实时值。 */
    var failed = !!(m && m.error) || (!!state.qc.err && !state.qc.at);
    var errMsg = (m && m.error) || state.qc.err || '';
    var v = m && m.value != null ? m.value : null;
    var lv = (failed || v == null) ? 'na' : qcLevel(d.id, v);
    var big = QC_PRIMARY_ORDER.indexOf(d.id) !== -1;
    var def = t(QC_SUB_KEY[d.id]) || (state.lang === 'en' ? d.subEn : d.subZh);
    var sub;
    if (failed) sub = t('qc.err') + (errMsg ? ': ' + errMsg : '');
    else if (d.id === 'alarm' && m && m.sites != null) sub = fmt(m.sites) + ' ' + t('qc.sites');
    else if (d.id === 'pmt' && m && m.overdue != null) sub = t('qc.overdue') + ' ' + fmt(m.overdue);
    else if (d.id === 'spms' && m && m.tables) {
      sub = t('qc.inbound') + ' ' + fmt(m.tables.inband_details || 0) +
            ' · ' + t('qc.outbound') + ' ' + fmt(m.tables.outband_details || 0);
    } else sub = def;
    /* tooltip = 口径 + 阈值 + 点击提示。阈值必须写出来，否则分级是黑盒：
       看到红色也说不出「凭什么算红」。 */
    var tg = QC_TARGETS[d.id], tips = [def];
    if (tg) tips.push(tf(tg.dir === 'down' ? 'qc.targetTip.down' : 'qc.targetTip.up',
      { warn: fmt(tg.warn), crit: fmt(tg.crit) }));
    if (!failed) tips.push(t('qc.drill'));
    var at = qcMetricAt(d.id);
    /* 数字没取到一律 —，绝不显示 0：统计里的 0 是「真的一个都没有」，
       与「没取到」必须能分辨，否则会被误读成「已清空」。 */
    return '<button type="button" class="qc-card qc-lv-' + lv + (big ? ' qc-card--lg' : ' qc-card--sm') +
      (failed ? ' is-failed' : '') + '" data-qc="' + esc(d.id) + '" title="' + esc(tips.join('\n')) + '">' +
      '<span class="qc-hd"><span class="qc-ico" aria-hidden="true">' + ic(d.icon) + '</span>' +
        '<span class="qc-name">' + esc(state.lang === 'en' ? d.en : d.zh) + '</span></span>' +
      /* 等级徽章单独一行：六张卡并排每张只有 ~240px，挤在标题行会把卡名截断。
         颜色之外再给一枚文字徽章 —— 只靠颜色传意对色盲和黑白打印都不可读。 */
      '<span class="qc-lvchip">' + esc(t(QC_LV_KEY[lv])) + '</span>' +
      '<span class="qc-numrow"><span class="qc-num' + (v == null ? ' is-na' : '') + '">' +
        esc(v == null ? '—' : fmt(v)) + '</span></span>' +
      (big || QC_TREND_METRICS.indexOf(d.id) !== -1 ? qcSparkSlot(d.id) : '') +
      '<span class="qc-sub" title="' + esc(sub) + '">' + esc(sub) + '</span>' +
      (at ? '<span class="qc-age">' + esc(tf('qc.dataAt', { t: qcClock(at), ago: qcAgo(at) })) + '</span>' : '') +
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
    var cards = QC_PRIMARY_ORDER.concat(QC_SECONDARY_ORDER).map(function (id) {
      return byId[id] ? qcCardHtml(byId[id]) : '';
    }).join('');
    var sla = qcMetric('sla') || {}, pct = sla.value == null ? 0 : Math.max(0, Math.min(100, Number(sla.value)));
    var slaLv = sla.value == null ? 'na' : qcLevel('sla', sla.value);
    /* 环上的百分比必须自带分母口径：不写清「近 30 天已判定 Pass 的占比」，
       88.5% 会被读成「工单完成率」—— 而这两件事在 NOC 语境下完全不同。 */
    var slaTip = (sla.total ? tf('qc.slaTip', { d: sla.days || 30, pass: fmt(sla.pass), total: fmt(sla.total) })
      : (sla.error ? t('qc.err') + ': ' + sla.error : t('qc.loading'))) + '\n' +
      tf('qc.targetTip.down', { warn: fmt(QC_TARGETS.sla.warn), crit: fmt(QC_TARGETS.sla.crit) });
    var stamp = qcLatestStamp();
    /* 心跳点：取不到数据时变红且不脉冲 —— 绿色脉冲 = 这块面板确实在自动刷新。
       秒必须精确到秒：只到分钟时，轮询 + 后端 60s 缓存叠起来会出现「一分钟没变」的错觉。 */
    var live = '<span class="qc-live" title="' +
      esc(tf('qc.cadenceTip', { a: state.qcAlarmAt ? qcClock(state.qcAlarmAt) : '—',
        f: state.qcFullAt ? qcClock(state.qcFullAt) : '—' })) + '">' +
      '<span class="' + (q.err && !has ? 'qc-dot qc-dot-bad' : 'qc-dot') + '" aria-hidden="true"></span>' +
      '<span class="qc-when">' + esc(stamp ? t('qc.updated') + ' ' + qcClock(stamp) : t('qc.loading')) + '</span>' +
      '<span class="qc-sep">·</span><span id="qcNextIn">' + esc(tf('qc.next', { t: qcCountdown() })) + '</span></span>';
    box.innerHTML =
      '<div class="band-h">' +
        '<div class="ring qc-lv-' + slaLv + '" style="--v:' + pct + '" title="' + esc(slaTip) + '"><b>' +
          (sla.value == null ? '—' : pct.toFixed(1) + '%') + '</b></div>' +
        '<div class="band-txt"><div class="band-k">' + esc(t('qc.sla')) + '</div>' +
          '<p class="band-n">' + esc(t('qc.title')) + ' · <em>' + (sla.pass || 0) + '</em> / <em>' +
          (sla.total || 0) + '</em></p></div>' +
        live +
        '<button type="button" class="gb" data-act="qc-reload" title="' + esc(t('qc.reload')) + '">' +
          ic('refresh') + esc(t('qc.reload')) + '</button>' +
      '</div><div class="qc-grid">' + cards + '</div>';
  }

  /* 地图栏的面板头 + 页签 + 工具按钮（2026-09-23 抽出）。
     抽出来的原因：快速路径（renderL0(true)）只重画左栏，改名后必须就地刷新这块，
     否则「改完标题还是旧的」会被当成没保存成功。整份 HTML 由 renderL0 与快速路径共用，
     避免两处走样（页签里含 tabLabelOf 的结果，必须跟着 tabLabels 变）。 */
  function mapHeadHtml(maps) {
    var ed = canEdit();
    return '<div class="p-head"><span class="p-hd">' +
      (ed
        ? '<button type="button" class="p-t p-t-edit" data-act="map-head" title="' + esc(t('edit.maptabTip')) + '">' +
          esc(headTitleText()) + '<i class="ph ph-pencil-simple maptab-pen" aria-hidden="true"></i></button>'
        : '<span class="p-t">' + esc(headTitleText()) + '</span>') +
      '<span class="p-s">' + esc(headSubText()) + '</span></span>' +
      '<div class="map-tabs"><div class="tabs' + (ed ? ' is-renaming' : '') + '" role="tablist">' + maps.map(function (m) {
        return '<button type="button" class="tab" role="tab" data-map="' + esc(m.page) + '" aria-selected="' +
          (m.page === state.mapTab ? 'true' : 'false') + '" title="' +
          esc(ed ? t('edit.maptabTip') : m.title) + '">' + ic(m.icon) + esc(tabLabelOf(m.page, m.key)) +
          (ed ? '<i class="ph ph-pencil-simple maptab-pen" aria-hidden="true"></i>' : '') + '</button>';
      }).join('') + '</div>' +
      '<button type="button" class="gb gb--t" data-act="map-reload" title="' + esc(t('map.reload')) + '"><i class="ph ph-arrow-clockwise"></i><span>' + esc(t('map.reload')) + '</span></button>' +
      '<a class="gb gb--t" id="mapOpen" href="' + esc(curMap().src) + '" target="_blank" rel="noopener noreferrer" title="' + esc(t('map.open')) + '"><i class="ph ph-arrow-square-out"></i><span>' + esc(t('map.open')) + '</span></a>' +
      '</div></div>';
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
        /* 标题/页签那块要就地刷新（2026-09-23 加）：改名走的是 renderCatalog →
           renderL0(true)，走快速路径时只换左栏，不重画 p-head 的话
           「改完标题没变」会被当成没保存成功。这里只写 p-head 的 innerHTML，
           不碰 iframe —— 不会触发那个几十秒的拓扑重载。 */
        var phead = mp.querySelector('.p-head');
        if (phead) phead.innerHTML = mapHeadHtml(maps);
        box.classList.toggle('no-side', !side);
        return;
      }
    }
    var html = '<div class="l0-col" id="l0Col">' + side + '</div>';
    box.classList.toggle('no-side', !side);
    if (maps.length) {
      html += '<section class="panel map" id="l0Map" data-tier="0" aria-label="Topology">' +
        mapHeadHtml(maps) +
        '<div class="canvas"><iframe id="mapFrame" title="' + esc(headTitleText()) + '" src="' + esc(curMap().src) + '"></iframe>' +
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
  /* ---- 拓扑地图页签改名（2026-09-23 加）----
     服务端 catalog.tabLabels 只存 {page:{zh,en}}，**不做语言回落**：某个语言缺值就当
     没配、用 i18n 字典里的内置文案。与后端 _normalize_tab_labels 的语义严格对齐 ——
     两边不一致会出现「后端存了 A、前端显示成 B」这种最难查的错位。 */
  function normTabLabels(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    var out = {};
    RENAME_KEYS.forEach(function (page) {
      var v = raw[page];
      if (!v || typeof v !== 'object') return;
      var zh = typeof v.zh === 'string' ? v.zh.trim() : '';
      var en = typeof v.en === 'string' ? v.en.trim() : '';
      if (!zh && !en) return;               /* 全空 = 没配（后端也会丢弃空壳） */
      out[page] = { zh: zh, en: en };
    });
    return out;
  }
  /** 页签显示名：目录里配过就用它，否则回落 i18n 字典的内置文案（t(key)）。 */
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
     后端只存"中/英"两个值，由各前端决定谁显示在上 —— 改这里之前先确认没把上下搞反。 */
  function headTitleText() {
    var v = state.tabLabels && state.tabLabels[RENAME_HEAD];
    if (v && v.zh) return v.zh;
    return t('map.title');
  }
  function headSubText() {
    var v = state.tabLabels && state.tabLabels[RENAME_HEAD];
    if (v && v.en) return v.en;
    return t('map.sub');
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
  /* 拓扑地图页签改名（2026-09-23 加）。写的是服务端共享目录 catalog.tabLabels，
     所有人刷新都能看到 —— 与分组改名同一个语义层级。 */
  function renameTab(page, zh, en) {
    if (RENAME_KEYS.indexOf(page) === -1) return;
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
      /* ⚠️ 这份"点它不算点外面"的名单必须列全所有会 openForm 的触发点，
         否则 mousedown 先 closeForm()、紧接着 click 又 openForm()：
         同一个元素上先关后开，表现为浮层闪一下，且第二次点变成"切换关闭"。
         2026-09-23 加页签/标题改名时漏了后两个选择器（.tab 与 [data-act=map-head]），
         症状是点标题浮层一闪、点同一个页签第二次不弹。 */
      if (state.popForm && !e.target.closest('#editPop') &&
          !e.target.closest('[data-act="grp-edit"],[data-act="grp-add"],[data-act="title"],' +
                            '[data-act="map-head"],#l0Map .tab')) closeForm();
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
    title: { fields: ['zh', 'en'], tip: 'edit.titleTip', ok: 'edit.formSave' },
    /* 拓扑地图页签名（2026-09-23 加）：字段与 title 相同，独立的 kind 只为让提示语
       说清「改的是地图页签」并走 renameTab 这条路（写的是 catalog.tabLabels）。 */
    maptab: { fields: ['zh', 'en'], tip: 'edit.maptabTip', ok: 'edit.formSave' }
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
    else if (kind === 'maptab') {
      /* 当前值：配过就是配置里的，没配过用内置文案（不要让输入框空着 ——
         空框会让人以为「本来就没名字」，而实际是有内置名的）。
         __head 的 zh/en 与页签同口径（zh=中文、en=英文），本门户标题在上用的是 zh，
         取值时直接照 headTitleText/headSubText 的映射来。 */
      var cv = (state.tabLabels && state.tabLabels[id]) || {};
      if (id === RENAME_HEAD) {
        vals = { zh: cv.zh || headTitleText(), en: cv.en || headSubText() };
      } else {
        var mt = mapItems().filter(function (x) { return x.page === id; })[0];
        if (!mt) return;
        vals = { zh: cv.zh || tabLabelOf(id, mt.key), en: cv.en || tabLabelOf(id, mt.key) };
      }
    }
    var hd = kind === 'grp' ? gName(id) : kind === 'title' ? ('#' + id + ' ' + (vals.zh || vals.en))
      : kind === 'maptab' ? (t('map.title') + ' · ' + (vals.zh || vals.en)) : t('edit.grpAdd');
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
    else if (kind === 'maptab') renameTab(id, v.zh, v.en);
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
     默认仍是「全部」，子页签只是定位器，不拿它藏内容。
     最右边固定一颗「报告文件」页签（2026-09-22 加）：内嵌 my_app 的
     /myapp/?page=email_reports，与 MsPortal 右列那张 Task Report Files 卡同一内容。
     它不是分组，所以不吃搜索 / 状态筛选、也没有条数可报。 */
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
    if (emailItem()) tabs.push({ id: EMAIL_TAB, label: t('email.tab'), email: true });
    var gtabs = tabs.filter(function (x) { return !x.email; });
    if (!tabs.length) {
      box.innerHTML = '<div class="panel empty"><b>' + esc(t('v.emptyFilter')) + '</b> — ' + esc(t('v.adjust')) + '</div>';
      emailLang = null;                 /* 骨架跟着 .view-1 一起没了，回来时要重建 */
      return;
    }
    viewsShell();
    var hasEmail = !!emailItem();
    var cur = state.viewTab === EMAIL_TAB && hasEmail ? EMAIL_TAB
      : gtabs.filter(function (x) { return x.id === state.viewTab; })[0] ? state.viewTab
        : (gtabs.length ? gtabs[0].id : EMAIL_TAB);
    /* 兜底到「报告文件」的那一次不写回：分组全被筛掉不代表用户想离开 BO View，
       存下去等他清掉关键词，位置就真没了。 */
    if (cur !== EMAIL_TAB || state.viewTab === EMAIL_TAB) { state.viewTab = cur; ss('olbr.viewtab', cur); }
    var onEmail = cur === EMAIL_TAB;
    $('#vTabs').innerHTML = tabs.map(function (x) {
      return '<button type="button" class="tabv" role="tab" data-view="' + esc(x.id) +
        '" aria-selected="' + (x.id === cur ? 'true' : 'false') + '">' + esc(x.label) +
        (x.email ? '' : '<small>' + x.list.length + '</small>') + '</button>';
    }).join('');
    var gPanel = $('#vGroup'), ePanel = $('#vEmail');
    var act = gtabs.filter(function (x) { return x.id === cur; })[0] || gtabs[0] || null;
    if (act) {
      /* 「其他看板」不是数据里真实存在的分组名，往下传会拼出 gid=__other 的死链接，
         传空串让 vlink 回退到条目自己的主分组。 */
      var gid = act.id === OTHER ? '' : act.id;
      var list = act.list, subRow = '';
      if (gid) {
        var sub = (canEdit() ? subManageHtml : subLocatorHtml)(gid, act.list, list);
        subRow = sub.html; list = sub.list;
      }
      if (!subRow) state.viewSub = '';
      var head = act.id === OTHER
        ? '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(act.label) + '</span></span>' +
          '<span class="cnt">' + list.length + '</span></div>'
        : panelHead(act.id, '', list.length);
      /* 停在报告文件页签时这份内容照画、只把整块藏起来：切回来立刻就是最新的，
         不用等一次重渲染（而 .view-1 只有两行，谁在上面由 hidden 说了算）。 */
      gPanel.hidden = onEmail;
      gPanel.setAttribute('data-gid', esc(gid));
      gPanel.setAttribute('aria-label', esc(act.label));
      gPanel.innerHTML = head + subRow + '<div class="cards">' + (list.length
        ? list.map(function (it) { return itemCard(it, gid); }).join('')
        : '<div class="empty"><b>' + esc(t('v.empty')) + '</b></div>') +
        '</div>';
    } else {
      gPanel.hidden = onEmail;
      gPanel.removeAttribute('data-gid');
      gPanel.innerHTML = '<div class="empty"><b>' + esc(t('v.emptyFilter')) + '</b> — ' + esc(t('v.adjust')) + '</div>';
    }
    ePanel.hidden = !onEmail;
    if (onEmail) renderEmailSection();
  }

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

  /* 这条看板在**服务端全局目录里没有**（实测：服务端 49 条、内置 51 条，缺的 17 条里
     就有 no=41 Task Report Files —— MsPortal 那张卡同样读不到，才要靠它自己的兜底文案）。
     所以查归属时把内置那份接在后面一起找：查得到才谈权限，查不到不等于「这块不存在」，
     这一页签本来就是本页固定功能，不是目录条目渲染出来的。 */
  function emailItem() {
    var pool = ITEMS.concat(D.items || []);
    return pool.filter(function (x) { return String(x.url || '').indexOf('page=' + EMAIL_PAGE) !== -1; })[0] || null;
  }
  function emailAllowed() { var it = emailItem(); return !!it && canSee(it); }
  /* 相对路径：门户从 localhost 还是局域网 IP 打开都自适应（与地图同一考虑）。
     深链自身就是 bare 模式（自己的侧栏 / Header 都隐藏），不用地图那套 MAP_STRIP_CSS。 */
  function emailSrc() { return '/myapp/?page=' + EMAIL_PAGE; }

  function emailSectionHtml() {
    return '<div class="p-head"><span class="p-hd"><span class="p-t">' + esc(t('email.title')) + '</span>' +
      '<span class="p-s">' + esc(t('email.sub')) + '</span></span>' +
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
    if (!f.getAttribute('src') || f.dataset.theme !== want) {
      if (ls('myapp-theme', '') !== want) ss('myapp-theme', want);   // ⚠️ 必须在设 src 之前
      f.dataset.theme = want;
      delete f.dataset.loaded;
      f.setAttribute('src', emailSrc());
    }
    var open = $('#emailOpen'); if (open) open.href = emailSrc();
    syncEmailBoot();
  }

  function renderEmailSection() {
    var el = $('#vEmail'); if (!el) return;
    if (emailLang !== state.lang || !el.querySelector('#emailHost')) {
      el.innerHTML = emailSectionHtml();
      emailLang = state.lang;
    }
    ensureEmail();
  }

  /* .view-1 建好就一直留着：#vTabs / #vGroup 每次换内容，#vEmail 只切显隐（见上面第 ④ 条） */
  function viewsShell() {
    var box = $('#views');
    if (box.querySelector('.view-1')) return;
    box.innerHTML = '<div class="view-1">' +
      '<div class="tabs-v" id="vTabs" role="tablist"></div>' +
      '<section class="panel" id="vGroup" data-tier="1"></section>' +
      '<section class="panel" id="vEmail" data-tier="1" aria-label="' + esc(t('email.title')) + '" hidden></section>' +
      '</div>';
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
    /* 用户管理入口只对「真门户管理员」开：role 判定照 uniplam/MsPortal 两处，
       还要有 id —— 本机回环下 my_app 给的占位身份也是 admin，但调不动门户接口，
       与其点了弹一句「请先登录」，不如干脆不显示。 */
    var m = $('#umBtn');
    if (m) m.hidden = !(u && u.role === 'admin' && u.id);
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
    var opts = { method: (init && init.method) || 'GET', credentials: 'same-origin', headers: headers };
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
      clearTimeout(umFlash._t);
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
       门户的用户接口只认门户会话，先去登录再回来。 */
    if (!user.id) { toast(t('um.needPortalLogin')); return; }
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
  /* 只请求后端确实有趋势的四个（cr / pmt 回 no_trend，不必白跑一个来回）。
     失败不清空已有趋势：拿不到线只是不画，不是错误状态。 */
  function fetchQcTrend() {
    QC_TREND_METRICS.forEach(function (id) {
      api('/api/portal-qc/trend?metric=' + id + '&days=30').then(function (d) {
        if (!d || !d.points) return;
        state.qcTrend = state.qcTrend || {};
        state.qcTrend[id] = d;
        renderBand();
      }).catch(function () {});
    });
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
     （与文件顶部 wireMap 那段「两份若要改动，请同时改」是同一条约定）。

     仍然保持只读版的三条红线：不写 msportal.* 键、不 PUT 目录、不改权限判定。
     下面只发 GET /api/portal-qc/* 与本地导出，不触碰任何写接口。 */

  /* 弹窗标题 = 卡片名 + 「· 明细」，并顺带维护「打开完整看板」按钮。
     映射只给**目录里确实存在对应看板**的维度（源码见 MsPortal/portal.js 的
     QC_BOARD_PAGE）：cr / pmt 在 my_app 侧没有对应页面 ——
     配一个错的链接比不给链接更糟，故不配、按钮不出现。

     2026-09-26：spms 由 sp_material 改为 **sp_report**，与 MsPortal 同步
     （理由见 MsPortal/assets/portal.js 的 QC_BOARD_PAGE 注释：
     spms 明细是出入库单，sp_report 才是同一批单子的报表）。 */
  var QC_BOARD_PAGE = {
    alarm: 'realtime_alarm',
    tt: 'ttwo',
    wo: 'ttwo',
    spms: 'sp_report'
  };

  function applyDrillTitle() {
    var id = state.drill.metric;
    var q = (D.qc || []).filter(function (x) { return x.id === id; })[0];
    $('#qcTitle').textContent = (q ? (state.lang === 'en' ? q.en : q.zh) : id) + t('dr.drillSuffix');

    var link = $('#qcOpenBoard');
    if (link) {
      var page = QC_BOARD_PAGE[id];
      if (page) {
        /* 同源相对路径：门户与 my_app 经同一个 nginx，用相对路径就不会把
           「本机 192.168.100.20」写死进代码（换 IP / 换域名时不用改这里）。 */
        link.href = '/myapp/?page=' + encodeURIComponent(page);
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
    var def = (D.qc || []).filter(function (x) { return x.id === id; })[0];
    if (!def) return;
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
    var label = (function () {
      var q = (D.qc || []).filter(function (x) { return x.id === metric; })[0];
      return q ? (state.lang === 'en' ? q.en : q.zh) : metric;
    })();

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
  /* 默认比内层页自己的取景再近一级（2026-09-22 用户：「跟手动点一次加号一个效果」）。
     只在本页面这一侧做：/myapp/ 是两个门户共用的预编译产物，改它的默认 zoom 等于
     把展示版的偏好推给 MsPortal，而且要连带重新发布一批与本次无关的源码。
     先点内层页自己的 + 控件（走它自己的行为链，maxZoom 和它自己的 zoomend 都由它管），
     控件不存在（有的内层页关了 zoomControl）才退到直接改地图实例。 */
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
  /* stripFrame 在 0 / 1.4s / 3.4s 会被反复调用，所以必须去重，否则变成 +3。
     延迟到 1.8s：内层 React 应用在挂载时才 setView，早于它的取景加一级会被盖掉。 */
  var MAP_ZOOM_DELAY = 1800;
  function zoomOnce(d) {
    var w = d.defaultView;
    /* 会自己重新取景的内层页（暴露 fitAllSites）不在这里加：它每次 fit 都会把视野
       拉回「刚好包住所有站点」，加一级得跟在每次 fit 之后做，见 refitLeaflet。 */
    if (!w || typeof w.fitAllSites === 'function') return;
    if (d.__olbrZoomed) return;
    window.setTimeout(function () {
      if (d.__olbrZoomed || !d.querySelector('.leaflet-container')) return;
      if (zoomInLeaflet(d)) d.__olbrZoomed = true;
    }, MAP_ZOOM_DELAY);
  }
  /* 只有暴露了 fitAllSites 的内层页（当前是 mwRealTime）需要重新取景：
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
      /* fit 之后才加一级（fit 会重置视野）；再晚一点：fit 带动画时立刻 setZoom 会被忽略。
         这里不去重是刻意的 —— 每轮都是「重新 fit + 一级」，反复收敛到 fit+1，不会累加。 */
      window.setTimeout(function () { zoomInLeaflet(d); }, 700);
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
        zoomOnce(d);
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
    var f = $('#mapFrame'); if (f) { f.src = curMap().src; }
    /* 报告文件那块不看 URL 参数也不收 postMessage（my_app 只在启动时读 myapp-theme），
       只能靠 ensureEmail 里的「上次主题 ≠ 本次」判据重设 src；不在这一档时不用管，
       切过去自然会走同样的判断。 */
    if (state.viewTab === EMAIL_TAB) renderEmailSection();
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
  /* 只探活，文案由 applyI18n 写（语言切换才会跟着变）。 */
  function envBadge() {
    api('/api/portal-qc/summary').then(function () { $('#envBadge').classList.remove('bad'); })
      .catch(function () { $('#envBadge').classList.add('bad'); });
  }

  /* ------------------------------------------------------------ events -- */
  function bind() {
    var qEl = $('#q'), deb;
    $('#railBtn').addEventListener('click', function () {
      setRailOpen(!state.railOpen);
      if (state.railOpen) qEl.focus();          /* 展开就是为了输东西，顺手把光标放进去 */
    });
    qEl.addEventListener('input', function () {
      window.clearTimeout(deb);
      deb = window.setTimeout(function () { state.q = qEl.value || ''; render(); }, 120);
    });
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        /* 收起态下 #railIn 是 display:none，对隐藏元素 focus() 是空操作 —— 必须先展开 */
        setRailOpen(true); qEl.focus(); qEl.select();
      }
      if (e.key === 'Escape') {
        /* 弹窗优先吃掉 Esc：用户管理里有未保存的白名单草稿，让它先于下钻 / 检索轨关闭 */
        if (state.um.open) closeUserMgmt();
        else if (state.drill.metric) closeDrill();
        else if (qEl === document.activeElement) {
          /* 有词先清词、没词才收轨：一步到位会让「按两次 Esc」这种肌肉记忆失去其中一档 */
          if (qEl.value) { qEl.value = ''; state.q = ''; render(); }
          else { setRailOpen(false); qEl.blur(); }
        }
      }
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
    bindUserMgmt();

    $('#band').addEventListener('click', function (e) {
      if (e.target.closest('[data-act="qc-reload"]')) { loadQc(true); return; }
      /* 把点击坐标带给 openDrill —— 弹窗以点击位置为中心弹出。
         键盘触发（Enter/Space）时 clientX/clientY 都是 0，那种情况交给
         qcDrill 判空并回落到「居中于屏幕」（myapp 同样是 anchor 为空即居中）。 */
      var m = e.target.closest('.qc-card');
      if (m && m.getAttribute('data-qc')) {
        var anchor = (e.clientX || e.clientY) ? { x: e.clientX, y: e.clientY } : null;
        openDrill(m.getAttribute('data-qc'), anchor);
      }
    });
    $('#l0').addEventListener('click', function (e) {
      var tb = e.target.closest('[data-map]');
      if (tb) {
        var pg = tb.getAttribute('data-map');
        /* 编辑模式：点页签 = 改名浮层；非编辑模式：照旧切地图。
           两者必须分开 —— 同时生效会让「想看看微波实时」变成误开改名框。 */
        if (canEdit()) { openForm('maptab', pg, tb); return; }
        state.mapTab = pg; ss('olbr.maptab', state.mapTab); renderL0(); return;
      }
      /* 标题改名（2026-09-23 加）：按钮在 #l0Map 的 p-head 里，那块会被 renderL0 重建，
         所以走这里的事件委托而不是绑按钮本身。 */
      if (e.target.closest('[data-act="map-head"]')) {
        e.preventDefault();
        openForm('maptab', RENAME_HEAD, e.target.closest('[data-act="map-head"]'));
        return;
      }
      if (e.target.closest('[data-act="map-reload"]')) { var f = $('#mapFrame'); if (f) f.src = curMap().src; }
    });
    $('#views').addEventListener('click', function (e) {
      /* 「刷新」不能等下面的 data-act 让路规则：它不属于编辑态那套动作 */
      if (e.target.closest('[data-act="email-reload"]')) {
        var ef = $('#emailFrame');
        if (ef && ef.getAttribute('src')) { delete ef.dataset.loaded; syncEmailBoot(); ef.src = emailSrc(); }
        else renderEmailSection();
        return;
      }
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
      if (e.target.id !== 'lf') return;
      e.preventDefault();
      var err = $('#le'), go = $('#lgo'); go.disabled = true; go.textContent = t('gate.busy'); err.hidden = true;
      login($('#lu').value.trim(), $('#lp').value).then(function () {
        /* renderWho 必须一起调：login() 只把 state.user / authOk 写好，
           徽标、退出按钮、用户管理入口三处的可见性全在 renderWho 里判。
           少了这一行，在本页登录完顶栏仍是「没人登录」的样子，要刷新才恢复。 */
        renderGate(); renderWho(); mainLocked(false); start();
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
  /* 分两档刷新（与 MsPortal 同一口径，别改回单一定时器）：
       - 全量（其余五项 + 达标率）：每小时 :06:30，紧跟 eflow_sync 跑完；
       - 告警单项：每 5 分钟 :00:30，紧跟 eflow_active_alarm 的整表 replace。
     都用 setTimeout 自链而不是 setInterval —— 对齐按墙上的钟算，interval 只会从进页面
     那一刻起累加，进页面时若是 :07，下一轮就整体偏了。 */
  function startQcLoops() {
    (function qcLoopFull() {
      window.setTimeout(function () { loadQc(); qcLoopFull(); },
        qcNextDelay(QC_FULL_MIN, QC_FULL_OFFSET));
    })();
    (function qcLoopAlarm() {
      /* 开页时先补一发 ?only=alarm：首屏那三个告警数字是从全量借来的、时间戳走全量
         的时间轴（:06:30），而这一档的刻度是 :00:30。不补的话刚进来时「告警最近」
         可能是一小时前的旧时间，要等下一个 5 分钟刻度才被刷新。 */
      window.setTimeout(loadQcAlarm, 0);
      window.setTimeout(function () { loadQcAlarm(); qcLoopAlarm(); },
        qcNextDelay(QC_ALARM_MIN, QC_ALARM_OFFSET));
    })();
    /* 切回前台补一发全量：后台标签页的定时器会被降频甚至冻结，不补的话回到页面看到的
       可能是几小时前的数字 —— 比「延迟刷新」更容易被误读成故障。 */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { loadQc(); loadQcAlarm(); }
    });
  }
  function start() {
    loadQc();
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
