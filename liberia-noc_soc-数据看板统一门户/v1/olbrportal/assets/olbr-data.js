// ============================================================================
// olbr-data.js — olbr.js 的纯数据/常量母本（IIFE 外，供主文件读取）
// ----------------------------------------------------------------------------
// 本文件是 olbr.js 拆分的第一步（2026-09-25）：把零闭包依赖的纯数据块从
// 4595 行的主 IIFE 里摘出来，集中挂到 window.OLBR_DATA。主文件只读不写，
// 不改任何运行时行为，只为让 i18n 字典、图标映射、阈值表、KPI 规格等
// 「长而不变的数据」与逻辑分离——改文案时不用碰主文件。
//
// 约束（与 olbr.js 头部「三条红线」同源）：
//  · 本文件**不得**引用 olbr.js 的 IIFE 闭包变量（state / D / $ / ITEMS 等）——
//    那些是主文件私有的，这里拿不到。所有数据必须是自包含字面量或仅依赖本文件
//    内部其他常量的计算（如 RENAME_KEYS 依赖 MAP_TABS）。
//  · 主文件引用时一律走 window.OLBR_DATA.XXX，不裸写名字。
//  · 加载顺序：index.html 里本文件必须在 olbr.js **之前**（与 data.js / terms.js
//    同模式）——否则主文件 boot 时 OLBR_DATA 还没就绪。
//  · 守卫：本文件顶部 // @ts-check，由 npm run lint:shells 覆盖。
//
// 搬出时保留了原注释（包括「为何这么写」的设计决策），改这些数据时先读注释。
// ============================================================================

// @ts-check

window.OLBR_DATA = (function () {
  'use strict';

  /* --------------------------------------------------------------- i18n -- */
  // t(k) 在主文件里读 S[state.lang]，未命中时回落 zh；新加键两份字典都要加。
  // 带标点的整句一律走 {占位符} 模板，标点跟着语言走（中文全角、英文半角）。
  var S = {
    zh: {
      /* 2026-09-28（用户要求）：原「更智能的运维 · 更高的效率 · 更好的网络」，
         换成用户点名的「Ultimate Services · Leading Ecosystem」。
         ⚠️ 两份字典写**同一串英文**：用户给的是英文口号，它不是"待翻译的文案"，
         而是品牌标语本身 —— 与 qc.sub.* / map.open 那几次同一条约定
         （用户点名的写法不翻译）。所以中文环境下也照显英文，不要改成中文。 */
      'tagline': 'Ultimate Services · Leading Ecosystem',
      'mast.admin': '管理门户', 'mast.uni': '统一门户', 'mast.logout': '退出',
      'skip': '跳到主内容',
      'search.ph': '搜索看板名称、描述、责任人、标签…',
      'rail.all': '全部', 'rail.clear': '清除筛选',
      /* 检索轨默认收起成一条（2026-09-22）：入口要图标 + 文字，光一个放大镜图标不够直白 */
      'rail.btn': '搜索与筛选', 'rail.tip': '展开搜索框与分组 / 状态筛选（Ctrl K）',
      'count.all': '{n} 个看板 · {g} 个分组',
      'count.hit': '{n} / {t} 个看板命中',
      /* 2026-09-25 按用户要求改名：原「Quality Control 质量监控核心指标」→
         「Daily Operation Overview」。⚠️ 现在**中英两份字典同值**（都用这个英文名），
         不是漏翻 —— 用户明确要求两边都改成新名称，不要"顺手补齐"中文。
         下面的 qc.sub / qc.sla 等键仍是中英双语，不受影响。 */
      'qc.title': 'Daily Operation Overview',
      'qc.sub': '未清除告警 / 工单 / 变更 / 维护 / 备件 · 30 天达标口径',
      'qc.sla': '30 天达标率',
      /* 2026-09-25 删：qc.slaTip / qc.slaDrillTip / qc.slaPending 三条随标题行的
         「30 天达标率 + 圆环」一起移除（用户要求去掉 30-day compliance 与圆环图）。
         ⚠️ qc.sla 本页**只剩 qcMetricLabel 的回落**在用（弹窗共用实现，
         MsPortal 仍会传 metric=sla 进来），所以保留，不要跟着一起删。
         要恢复整块请看 assets/olbr.js.bak_20260925_去30天达标率与ALARM图标前。 */
      'qc.err': '数据库统计不可用', 'qc.retry': '重试',
      'qc.drill': '点击查看明细',
      /* QC 指标卡与 MsPortal 的 Quality Control 对齐（2026-09-22）。
         阈值、趋势口径、两档刷新节奏都照抄 portal.js，文案也沿用同一套说法 ——
         同一个数字在两个门户上被读成两件事，比样式不一致更糟。 */
      'qc.updated': '更新于', 'qc.next': '下次 {t}', 'qc.reload': '刷新', 'qc.loading': '加载中…',
      /* 数据区间（2026-09-28 加）：显示统计数字实际覆盖的起止时间。
         用 {a} ~ {b} 而不是硬编码前后缀 —— 两端的顺序与连接符要跟着语言走。 */
      'qc.range': '数据范围 {a} ~ {b}',
      /* 2026-09-28：点击切换的按钮提示（title / 读屏）。
         写「查看」而不是「切换」：用户视角里他是要"看这段数据覆盖哪段时间"，
         "切换"描述的是控件内部状态，对用户没有意义。 */
      'qc.rangeHint': '点击查看数据范围',
      'qc.na': '不可用',
      'qc.lv.ok': '正常', 'qc.lv.warn': '关注', 'qc.lv.crit': '严重', 'qc.lv.na': '不可用',
      'qc.dataAt': '数据 {t}（{ago}）',
      'qc.ago.now': '刚刚', 'qc.ago.min': '{n} 分钟前', 'qc.ago.hour': '{n} 小时前', 'qc.ago.day': '{n} 天前',
      'qc.sites': 'Cells/ Sites Outage', 'qc.overdue': '超期', 'qc.inbound': '入库', 'qc.outbound': '出库',
      /* 2026-09-28 按用户逐条指定的文案改名（原值见
         olbr-data.js.bak_20260928_柱状图与顶栏调整前）。用户给的是**中英同值**的
         英文写法，中文这份也照写 —— 与 qc.title 那次改名同一个处理
         （用户明确要这个名字，不要"顺手补中文"）。
         ⚠️ 只有 alarm 那一条带数字前缀（`75 Cells/ Sites Outage`），
         所以上面 qc.sites 保持为纯文案，数字仍由 qcCardHtml 拼在前面。 */
      'qc.sub.alarm': 'Cells/ Sites Outage', 'qc.sub.tt': 'Ongoing TTs',
      'qc.sub.wo': 'Ongoing WOs', 'qc.sub.cr': 'Unclosed CRs',
      'qc.sub.pmt': 'Unclosed PMTs',
      'qc.sub.spms': 'Unclosed SPMS',
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
      /* 存量趋势（2026-09-25 加，给 CRs / PMT 两张卡用）。
         与上面的「新增量」是两种口径，回答不同问题：
           新增量 → 最近来单变多了还是变少了（源表时间列，立即有数据）
           存量   → 积压是在堆积还是在消化（每小时快照，要从上线那刻起攒）
         措辞必须与新增量**明显不同**，否则用户会把「近 30 天新增 43 次」与
         「近 89 小时存量」读成同一件事。取数见 /api/portal-qc/history。 */
      'qc.stock.cap': '近 {n} 小时存量',
      'qc.stock.tip': '按每小时快照取样的「存量」（近 {n} 小时，每格 1 小时）。\n'
                    + 'CRs / PMT 的源表时间列近 30 天没有数据，画「新增量」会是一条贴 0 的直线，\n'
                    + '所以这两张卡改用快照存量 —— 它回答的是「积压是在堆积还是在消化」。\n'
                    + '注意：快照只在门户被打开过的小时才有，断档处折线会断开，**不补 0**\n'
                    + '（补 0 会画出一个「积压突然清零」的假谷底）。',
      'qc.stock.capPmt': '近 {n} 小时超期数',
      'qc.stock.tipPmt': '按每小时快照取样的「超期未完成 PMT 数」（近 {n} 小时，每格 1 小时）。\n'
                       + '与卡片大数字（未完成 PMT 总数）是同一批数据的不同侧面：\n'
                       + '总数看积压有多大，这条线看超期那部分是在堆积还是在消化。\n'
                       + '注意：快照只在门户被打开过的小时才有，断档处折线会断开，**不补 0**。',
      'qc.stock.starving': '存量样本不足',
      'qc.cadenceTip': '本面板分两档刷新：断站告警每 5 分钟（源 eflow_active_alarm 每 5 分钟同步，最近 {a}）；'
                     + 'TT/WO/CR/PMT/SPMS 与达标率每小时 :06（源 eflow_sync 每小时 :00 起跑、实测约 :06 跑完，'
                     + 'SP 备件明细 sp_data_sync 每小时 :10，最近 {f}）。切回本页或点「刷新」会立刻重拉全量。',
      'cxo.title': 'CXO View 决策战略层', 'cxo.sub': '统一总控与运营视窗',
      /* 2026-09-25 改名：标题行由「利比里亚网络拓扑全景 / Central Liberia Regional
         Topology」改成「GIS Map / GIS Map」。⚠️ 这一栏上下两行按设计是**同一个 key 的
         zh 与 en**（map.title 显示在上、map.sub 显示在下），改名后两行同值；
         想恢复"上中文下英文"的观感，就把 map.sub 改成别的副标题，
         但不要动 map.title 的中文名 —— 它是用户点名要的新标题。 */
      'map.title': 'GIS Map', 'map.sub': 'GIS Map',
      /* 2026-09-29 按用户要求把两个地图页签改名成 **Alarm / MW**
         （原来中英分别是「全球地图」/ "Global Map" 与「微波实时」/ "MW real-time"）。
         用户给的是英文短名，两份字典**照写同一串** —— 与 map.reload/map.open 那次
         改成 "Open Link" 同一条约定：用户点名的写法不翻译。
         键名保留 map.gis / map.mw 没动：键是**内部标识**（MAP_TABS.key 指过来），
         显示名与键名本来就不必一致 —— 页签的 page 值也一样，仍是 gis / mwRealTime。
         不动键名与 page，历史上存过的 catalog.tabLabels 记录就不会失配。
         map.alarm / map.loss 是**已下线**页签（2026-09-25 删）留下的键，
         保留是为了将来恢复时不用重写文案，与后端 TAB_PAGES 白名单同口径。 */
      'map.gis': 'Alarm', 'map.mw': 'MW', 'map.alarm': '实时告警', 'map.loss': '传输丢包',
      /* 2026-09-28 按用户要求把按钮文案改成 "Open Link"（原来中英分别是
         「新窗口打开」/ "Open in new tab"）。用户给的是英文串，
         两份字典都照写（与 qc.sub.* 那次改名同一条约定：用户点名的写法不翻译）。
         这个键同时被 GIS Map 与 Auto Report Files 两处按钮使用（items 12/13），
         所以改这一处两处一起生效 —— 不要在调用点各写一遍字符串。 */
      'map.open': 'Open Link', 'map.reload': '重新加载', 'map.load': '加载中…',
      /* 报告文件页签（2026-09-22 加）：内嵌 my_app 的任务报告文件中心，
         标题说法与 MsPortal 那张 Task Report Files 卡一致，同一内容在两个门户不该有两名。 */
      'email.tab': '报告文件',
      'email.title': 'Auto Report Files', 'email.sub': '任务报告文件中心（Email Reports）',
      'email.needLogin': '登录后显示报告文件',
      'email.noAccess': '当前账号没有「Task Report Files」这块看板的权限',
      'esc.title': '升级机制 Escalation Matrix',
      'esc.sub': '值班升级联系人 · Orange / LONESTAR 双网号码',
      'esc.expand': '展开全部 {n} 条', 'esc.collapse': '收起',
      /* 「展开全部」之后那颗按钮的文案。刻意不叫「收起」：
         收起是"整张表收成一条值班带"（escOpen），而这里只是把多出来的行折回去，
         表还在屏幕上 —— 混用会让用户以为点下去表会消失。 */
      'esc.lessRows': '只看前 4 行',
      'esc.now': '当前值班', 'esc.copy': '复制本级号码', 'esc.copied': '已复制',
      'esc.lv': '职级', 'esc.pos': '岗位', 'esc.name': '姓名', 'esc.mail': '邮箱',
      'esc.count': '{n} 条 · {lv} 级', 'esc.src': '数据源：升级机制.xlsx',
      /* v1：默认只显示前 4 行，必须明说还有多少条没显示 —— 否则会被当成表就这么多行 */
      'esc.moreRows': '仅显示前 4 行，另有 {n} 条 · 点右上「展开全部」查看',
      'v.open': '查看全部', 'v.empty': '该分组暂无看板',
      'v.subOther': '未归类',
      'mast.edit': '编辑分组', 'mast.editOn': '退出编辑', 'mast.editing': '编辑中', 'mast.userMenuTip': '打开用户菜单',
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
      'edit.title': '编辑', 'edit.titleTip': '改这张看板的中文名 / 英文名与链接（存服务端，所有人可见）',
      'edit.titleOk': '看板已更新', 'edit.needTitle': '中英文名不能同时为空',
      'edit.formSave': '保存', 'edit.formAdd': '添加',
      'edit.f.zh': '中文名', 'edit.f.en': '英文名', 'edit.f.subZh': '中文说明', 'edit.f.subEn': '英文说明',
      'edit.fph.zh': '显示给中文用户', 'edit.fph.en': 'Shown to English users',
      'edit.fph.subZh': '一句话说明这一组是什么', 'edit.fph.subEn': 'Optional one-line description',
      'edit.kGroups': '一级分组', 'edit.kLabels': '地图页签名',
      'edit.maptabTip': '改这个地图页签的中文名 / 英文名（存服务端，所有人可见；两项都清空则恢复默认）',
      'edit.maptabRenamed': '地图页签名已更新',
      /* 看板条目本身的增删（2026-09-26 加）。
         ⚠️ 「移出本列」与「删除看板」是两件不同的事，文案必须让人一眼分清：
         前者只摘掉一个分组归属（可逆），后者把条目从共享目录里拿走（不可逆）。
         命名上刻意避开 'edit.del*'（那是子分组的），免得上下一读就混。 */
      'edit.itemDrop': '移出本列', 'edit.itemDropTip': '把这张看板移出当前分组；只要它没有别的分组，就自动移入「归档」—— 看板本身还在，随时能勾回来',
      'edit.itemDel': '删除看板', 'edit.itemDelTip': '从共享目录里彻底删除这张看板，所有人刷新后都不再看到，无法撤销',
      'edit.itemDropped': '已从本分组移出', 'edit.itemDeleted': '看板已删除',
      /* 2026-09-28：原先只剩一个分组时会拒绝移出并提示 edit.itemLastGrp。
         现在改成自动移入归档 —— 「想收起来」不该被迫用不可逆的「删除看板」。
         本条文案保留（英文同步保留，见 en 字典），但已无代码引用：
         将来若有人要恢复"唯一分组不许移出"的老口径，按 git 历史取回调用即可。 */
      'edit.itemLastGrp': '这是它唯一的分组，移出后就没地方放了 —— 真要移除请用「删除看板」',
      'edit.itemDelConfirm': '彻底删除看板「{n}」？\n\n它会从共享目录里移除，/olbrportal/ 与 MsPortal 也不再显示，所有人刷新后都会少这一条。\n此操作无法撤销。',
      /* ---- 归档分组（2026-09-28 加）----
         「移出本列」的落点：一个真实的兜底分组，让"收起来"变成可逆的动作。
         文案要把三件事说清：① 看板没丢；② 去哪找它；③ 怎么勾回来。 */
      'edit.archived': '没有别的分组，已移入「归档」', 'edit.archivedTip': '它还在目录里，展开下方「归档」区即可看到，也可用「分组」勾回任一视图',
      'arch.title': '归档', 'arch.hint': '这里的看板已从各视图移出，仍保留在目录中 · 用「分组」可随时勾回',
      'arch.empty': '归档区是空的',
      'arch.unarchive': '取消归档', 'arch.unarchiveTip': '把这唯一的分组改回你选定的视图',
      /* 新增看板：先选一个现有看板当模板，再改名字与链接。
         模板值继承图标 / 平台 / 描述 / 负责人等，避免每次从零填十几个字段。 */
      'edit.itemAdd': '新增看板', 'edit.itemAddTip': '照着一个已有看板新建一张（图标 / 平台 / 描述等沿用模板，只改名字与链接）',
      'edit.itemAddPick': '先选一个已有看板当模板（可搜索）',
      'edit.itemAddSearch': '搜索看板名…',
      'edit.itemAddBack': '换一个模板',
      'edit.itemAdded': '看板已新增',
      'edit.itemNeedUrl': '先填链接（http:// 或 https:// 开头）',
      'edit.itemBadUrl': '链接要以 http:// 或 https:// 开头',
      /* 归档项在「分组」浮层里的计数提示（2026-09-29 加）。
         ⚠️ 计数徽章本身是**数字**，不是文案；这条只给 title 悬停说明用。
         为什么中英都要一条：{n} 是数字，中文说「张」、英文说 "dashboards"，
         不能靠拼 "N + 单位"。 */
      'edit.archCount': '归档里有 {n} 张看板',
      'edit.f.itemZh': '看板名（中文）', 'edit.f.itemEn': '看板名（英文）', 'edit.f.itemUrl': '链接',
      'edit.fph.itemZh': '例如 NUR Dashboard', 'edit.fph.itemEn': 'Shown to English users',
      'edit.fph.itemUrl': 'http://192.168.100.20/myapp/?page=xxx',
      'edit.itemTplFrom': '模板：{n}',
      'v.emptyFilter': '当前筛选下没有看板', 'v.adjust': '调整关键词或清除筛选',
      /* ---- v1 新增：CXO Daily Dashboard 指标带（renderKpi）----
         上排四张富卡片的数值全部来自 /api/olib-soc-dashboard/overview?days=90
         （= my_app `?page=vmaxCxoDashboard_90Days` 那个 90 天经营看板），
         口径是**昨日完整值**，不是当日进行中；下排三张是 2/3/4G 当月可用率
         （/api/alarm-dashboard/alarm-overview 的 network_availability）。 */
      'kpi.title': 'Network Status Overview',
      'kpi.sub': '昨日完整值 · 90 天区间 · 2G / 3G / 4G 当月可用率',
      'kpi.updated': '数据 {t}',
      'kpi.err': '指标读取失败',
      'kpi.retry': '重试',
      'kpi.month': '{m} 月均值',
      /* 可用率三张卡的卡名。⚠️ 不能复用 'qc.sla'（=「30 天达标率」）：
         那是 Quality Control 带的 SLA 结单达标率，与网络可用率是**两个完全不同的指标**，
         并排放在同一屏上极易被读成同一件事。这里给一个独立的措辞。 */
      'kpi.avail': '可用率',
      'kpi.noMonth': '当月数据未生成',
      /* 可用率卡页脚三格：昨日实际值 / 达标阈值 / 昨日与阈值的差。
         pp = percentage point（百分点），不是百分比 —— 97.38% 与 99.65%
         相差 2.27 个百分点，写成 "2.27%" 是错的。 */
      'kpi.yday': '昨日',
      'kpi.thr': '阈值',
      'kpi.thrLine': '达标线',
      'kpi.gapThr': '距阈值',
      'kpi.pp': 'pp',
      /* ---- 富卡片专用文案（kpiRichHtml）---- */
      'kpi.wow': '周同比',
      'kpi.mom': '月同比',
      'kpi.max': '最高',
      'kpi.avg': '平均',
      'kpi.min': '最低',
      'kpi.days': '近 {n} 天',
      /* 带标点的整句一律走 {占位符} 模板，标点跟着语言走：
         中文用全角（）：，英文用半角 ():。
         曾把「（」「：」硬写进 JS 模板，结果英文界面冒出
         "Latest · 2026-09-24（As of 2026-09-24）" 这种中英混排
         ——2026-09-25 实测踩到。新加带标点的文案请照这个写法。 */
      'kpi.tipName': '{n}（{u}）',
      'kpi.tipLatest': '最新：{d}',
      'kpi.tipBase': '{k} 对比日：{d}（{v} {u}）',
      'kpi.asofFmt': '最新 · {d}（数据截至 {a}）',
      /* 富卡片的 tooltip 第一句：口径必须写明，否则四个数字都不是当天的，
         而页面上其它看板大多是当日/实时，很容易被当成"今天的数"。 */
      'kpi.tipRich': '来源：CXO 90 天经营看板（昨日完整值，当天仍在累积不计入）',
      /* 整卡可点的提示（2026-09-29 加）。
         六张卡从上线起就带 cursor:pointer + hover 抬升（.qc-card 的既有样式），
         却一直没有点击行为 —— 视觉在暗示可点、点下去没反应，是既有的一处言行不一。
         现在补上跳转，hover 文案要说清「点哪儿、去哪儿」：
         只写「点击查看」的话，用户不知道会离开本页、也不知道开到哪个看板。
         {n} = 卡名（「Total Traffic」「2G 可用率」），{b} = 目标看板的业务名。
         ⚠️ 目标看板名必须由调用方传入（富卡片传「CXO 90 天经营看板」、
         可用率卡传「Daily Availability KPI」）—— 两排卡去的是**两个不同的页面**，
         写死一个名字会让另一排的提示直接说错。
         与 v6.headTip 同一条约定：把要去的地方写出来，点之前就知道会去哪儿。
         标点跟着语言走：中文全角（）与「」，英文半角 () 与引号。 */
      'kpi.openTip': '打开「{n}」的完整看板（{b}）',
      'kpi.boardRich': 'CXO 90 天经营看板',
      'kpi.boardAvail': 'Daily Availability KPI',
      'kpi.tipAvail': '来源：Daily Availability KPI（Availability-NW 页）按 Cell Group 汇总，口径与 {board} 一致',
      'kpi.tipAvailFoot': '大数字是当月均值；页脚三格依次为昨日实际值、达标阈值、昨日与阈值的差（pp = 百分点，负值表示昨日未达标）。',
      /* 可用率迷你走势（2026-09-25 加）。窗口按返回的点数算，不写死 30 ——
         写死的话后端一改窗口，卡片上的说明就会与线本身对不上。 */
      'kpi.availTrendCap': '近 {n} 天',
      'kpi.availTrendTip': '近 {n} 天的逐日 Cell Availability（每格 1 天）。\n'
                         + '与大数字、页脚同源（同一次接口响应），所以线的末端就是「昨日」那一格。\n'
                         + '注意纵轴只覆盖这段时间自身的波动范围，**不从 0 起** ——\n'
                         + '可用率长期在 97~99% 之间，从 0 起会把所有起伏压成一条直线，什么也看不出来。\n'
                         + '判断达标仍以页脚的「距阈值」为准，这条线只用来判断趋势。',
      /* 可用率卡对齐富卡片（2026-10-01 加）：大数字是当月（month-to-date）均值，
         截至昨日，用本键填富卡片 .qc-asof 那一行（富卡片是 Latest · 日期）。 */
      'kpi.availAsof': '当月均值 · 数据截至 {d}',
      /* ---- Benchmark 行（Network Benchmark View，2026-10-01 加）--------------
         ORANGE vs MTN 的下载/上传/时延对比，数据来自 /api/bm-speedtest/overview
         （my_app `?page=bm_speedtest` 的「Key metrics comparison」那组卡）。
         标题用用户点名的英文串，中英两份字典**照写同一串** ——
         与 map.gis / map.open 那几次同一条约定：用户点名的写法不翻译。
         三张卡之间用同一条口径说明（kpi.bf.sub），窗口天数由接口给，不写死。 */
      'kpi.bf.title': 'Network Benchmark View',
      'kpi.bf.sub': 'Orange 与 MTN 的 Speedtest 对比 · 区间均值 · 最近 {n} 天',
      /* 天数取不到时（接口没回 meta.start/end）的兜底 —— 刻意**不说天数**，
         也不编一个 30 出来：卡片上一个与数据无关的天数是错误信息。 */
      'kpi.bf.subNone': 'Orange 与 MTN 的 Speedtest 对比 · 区间均值',
      'kpi.bf.download': '下载速率', 'kpi.bf.upload': '上传速率', 'kpi.bf.latency': '时延',
      /* 卡片大数字是**区间均值**，必须与 p50/p90（逐日分位数）在措辞上分开：
         两个数都叫「平均」的话，用户会以为它们该相等。 */
      'kpi.bf.avgCap': '区间均值',
      'kpi.bf.pctCap': 'P50 {a} / P90 {b}',
      'kpi.bf.lead': '{n} 领先',
      'kpi.bf.win': '逐日胜率 {n}%',
      'kpi.bf.winTip': '「{m}」上 {n} 在最近 {d} 天里胜出 {w} 天（胜率 {r}%）。\n'
                     + '只统计**两家当天都有数据**的日子，只测了一家那天不计入胜负。',
      'kpi.bf.tipName': '{n}（{u}）',
      /* 数据来源。**必须点出 Speedtest by Ookla** —— 卡片右下角那个 logo
         是 Ookla 的注册商标，标识已经画出来了，文字这边就要说明"数据来自它"，
         这是商标的正当使用（指明来源），也免得读者以为那只是一个装饰图标。 */
      'kpi.bf.tipSrc': '数据来源：Speedtest by Ookla · my_app bm_speedtest 竞对分析，口径与「Key metrics comparison」一致',
      'kpi.bf.ooklaTip': 'Speedtest by Ookla',
      /* 'kpi.bf.tipAvg' 的 {win} 是**天数**（"最近 30 天"里的 30），
         不是整句 'kpi.bf.sub' —— 实测把整句插进来会得到
         「大数字是Orange 与 MTN 的 Speedtest 对比 · 区间均值 · 最近 30 天内两家的…」
         这种读不通的话。两个键各自只表达一件事，不要互相嵌套。 */
      'kpi.bf.tipAvg': '大数字是最近 {win} 天内两家的**区间均值**（逐日均值再平均），不是某一天的快照。',
      'kpi.bf.tipPcts': 'P50 / P90 是**逐日值**的分位数，与大数字（区间均值）不是同一个统计量，两者不必相等。',
      'kpi.bf.tipLead': '领先方在本区间该指标上更强 —— 速率取大、时延取小。',
      'kpi.bf.tipTests': '{n}：{t} 次测试 · {dev} 台设备',
      /* 页脚两格：左「窗口 30 天」、右「合计测试数」。
         单位与数字分成两行（.qc-ext 的 <b> 与 <span>），所以这里只给单位词。 */
      'kpi.bf.range': '统计窗口', 'kpi.bf.days': '天',
      'kpi.bf.tests': '测试量', 'kpi.bf.testsUnit': '两家合计',
      'kpi.bf.na': '区间内无数据',
      'kpi.bf.board': 'Speedtest 竞对分析',
      /* ---- 卡片走势图的 tooltip（2026-10-01 加）--------------------------------
         用户要求「Network Benchmark View 里面的卡片能跟 Network Status Overview
         里的卡片一样添加图」。三排卡片的图走同一套画法（.qc-spark 折线），
         但**这一排的图是两条线**（Orange / MTN），与上面三张可用率卡的单线不同 ——
         tooltip 必须点明这一点，否则读者会以为那是同一个指标的两次采样。
         {o} / {m} 是两家的展示名（Orange / MTN），由后端 label 给，不写死。
         ⚠️ 与 kpi.availTrendTip 同一条原则：不写"Last 30 days"这类下方说明行，
         该说的都在 title 里（本排卡片比上面那排更窄，没有位置放说明行）。 */
      'kpi.bf.sparkTip': '近 {n} 天逐日走势（每格 1 天），上排是 {o}、下排是 {m}。\n'
                       + '与卡片上的两行大数字**同源**（同一次接口响应），'
                       + '所以线的末端就是统计窗口的最后一天。\n'
                       + '⚠️ 纵轴只覆盖这段时间自身两家合起来的波动范围，**不从 0 起**；'
                       + '缺测的那天线会断开，不补 0。',
      /* 行标题（.band-k）的 tooltip。**这一行现在是两个数据源**（2026-09-30 起）：
         上面那句 kpi.bf.sub 只说得清左 3 张 Ookla 卡，挂在整行标题上就成了假话，
         所以标题另用这一条，把「两组各是什么、为什么不能互相比」讲全。
         ⚠️ 卡片自己的 tooltip 仍走 kpi.bf.sub* / kpi.mm.*：那里各说各的来源，
         混在一起会让 Ookla 卡的口径说明里冒出 Meta 的话。 */
      'kpi.bf.subBoth': 'Orange 与 MTN 的对比 · 本行 6 张卡来自两个数据源：'
                      + '3 张 Speedtest by Ookla（最近 {n} 天，my_app bm_speedtest 竞对分析），'
                      + '3 张 my_app Meta 基准报告（bm_meta，同一窗口）。'
                      + '两组都是「区间均值」，但样本与测量方式不同，**数字不可直接对比**。',
      /* ---- Benchmark 行第二组：Meta 基准报告（2026-09-30 加）-----------------
         数据源 /api/bm-meta/overview，即 my_app `?page=bm_meta`
         （`meta_data` 表，Excel 导入的静态快照）。它与左边 3 张 Ookla 卡
         **同一排、同一窗口**，但**是另一份数据** —— 所以卡名、口径说明、
         页脚来源标识全部另立一套，不复用 kpi.bf.* 里的整句：
         那套第一句就写着「Speedtest by Ookla」，套到 meta 卡上就是假话。
         卡名照抄 my_app 的 bmm.* 写法（同一件事在两个门户不能有两个名字）。 */
      'kpi.mm.speed': '速率',
      'kpi.mm.scores': '综合评分与胜场',
      'kpi.mm.bp': 'BP',
      /* 单位。中英只有「评分」不同（分 / pts），另两个同值 ——
         同值也照样进字典：渲染层一律走 t()，不留"中文里硬编码 Mbps"的分支。 */
      'kpi.mm.unitMbps': 'Mbps', 'kpi.mm.unitScore': '分', 'kpi.mm.unitPct': '%',
      /* 逐日区间。my_app 那张卡叫「区间范围」（bmm.card.rangeLabel），
         这里压成行内前缀 —— 卡里是两行并排，写满四个字会把左列挤宽。 */
      'kpi.mm.obsRange': '区间 {a} ~ {b}',
      /* 胜场。**照抄 my_app 的 bmm.card.winDaysFmt**（领先 {w} / {d} 天）：
         同一件事在两页必须同一个说法，否则用户会以为是两个指标。 */
      'kpi.mm.leadDays': '领先 {w} / {d} 天',
      'kpi.mm.avg': '均值',
      'kpi.mm.lead': '{n} 领先',
      /* 页脚两格：左「统计窗口 30 天」、右「覆盖 23 天」。
         第二格是窗口内**真正有数据**的天数，存在的理由：窗口取「最近 30 天」，
         而这份数据是导入快照（实测数据截至 2026-09-23），最近几天根本没有数 ——
         不写清楚，读者会以为大数字覆盖了整整 30 天。 */
      'kpi.mm.win': '统计窗口', 'kpi.mm.days': '天', 'kpi.mm.cover': '覆盖',
      /* 页脚第三格：Meta 那两张卡放**标识**（META_LOGO，见 olbr-data.js 末尾），
         这个键是它的无障碍名（role="img" 的 aria-label）——
         与 Ookla 标识同一个做法（图形本身不带 aria-label，名字由外层给）。
         徽章上不再有文字，所以这个键只出现在读屏与悬停里。 */
      'kpi.mm.srcAlt': 'Meta 报告',
      /* BP 那张卡的来源标识（**纯文字**，2026-09-30 按用户要求改）。
         为什么不是 Meta 报告：BP 与 FDD 吞吐 / PRB 利用率 / 流量 / RRC 用户数
         是同一组「网络侧 KPI」（Radio 侧 FDD 指标），不属于任何一家；
         沿用 my_app 对同一组指标的既有叫法（bmm.sec.network），
         两个门户对同一组指标只有一个名字。 */
      'kpi.mm.srcNet': '网络侧 KPI',
      'kpi.mm.tipName': '{n}（{u}）',
      'kpi.mm.tipSrc': '数据来源：my_app Meta 基准报告（bm_meta）· meta_data 表（Excel 导入的静态快照）。'
                     + '与左边 3 张 Ookla 卡是**两份不同的数据**，两边的数不可直接比。',
      /* BP 等网络侧 KPI 的来源，与上面那条**分开写**：它们的来源标识不同
         （网络侧 KPI ≠ Meta 报告），用同一句话会出现"徽章写网络侧 KPI、
         悬停说 Meta 报告"的自相矛盾。 */
      'kpi.mm.tipSrcNet': '数据来源：网络侧 KPI（BP、FDD 下行吞吐、DL/UL PRB 利用率、流量、RRC 用户数），'
                        + '属 Radio 侧 FDD 指标，不属于任何一家、不参与 PK 与综合评分。'
                        + '它与上面两张卡的「Meta 报告」**不是同一组指标**，'
                        + '门户随 my_app bm_meta 接口的同一份快照取到它。',
      'kpi.mm.tipWin': '大数字是最近 {win} 天窗口内的**区间均值**（逐日均值再平均），不是某一天的快照。',
      'kpi.mm.tipCover': '窗口内真正有数据的是 {n} 天 —— 这份数据是导入快照，数据截至 {d}。',
      'kpi.mm.tipRange': '「区间」是该家**逐日值**的最小 ~ 最大（每格 1 天），'
                       + '与大数字（区间均值）不是同一个统计量，两者不必相等。',
      'kpi.mm.tipScore': '综合评分是**相对分**：更强的一方为 100，另一方按比值折算；'
                       + '它不是绝对分，也不代表网络质量本身。',
      'kpi.mm.tipLead': '「领先 x / y 天」= 两家都有数据的 y 天里，这家速率更高的有 x 天；'
                      + '两家相同的那天不计入任何一方。'
                      + '⚠️ 所以两家的 x 相加**可能小于 y**：差额就是打平的天数。'
                      + '{tie} —— 打平的日子在两个门户都不算任何一方赢，不是缺数据。',
      /* {tie} 的取值见 olbr.js：有平局时报「本窗口打平 {n} 天」，无平局时报「本窗口无平局」。
         为什么要单独有一句：实测 2026-09 那个窗口两家各领先 11 天、y=22，
         相加正好等于 y —— 卡面看上去像"两家平分"，其实是另有 1 天平局。
         my_app 那边把平局单列了一行（BmMeta.tsx:496），
         这张卡没有那个位置，就把平局放进 tooltip 说清楚。 */
      'kpi.mm.tieN': '本窗口打平 {n} 天',
      'kpi.mm.tie0': '本窗口无平局',
      'kpi.mm.tipBp': 'BP 是**网络侧 KPI**，所以这张卡里没有品牌行、没有领先方徽章，'
                    + '只有区间均值与逐日区间。库里存的是小数比率，接口已换算成百分数。',
      'kpi.mm.rowDays': '{n} 天有数据',
      'kpi.mm.rowScore': '综合评分 {v} {u}',
      'kpi.mm.na': '区间内无数据',
      'kpi.mm.board': 'Meta 基准报告',
      /* ---- Meta 组三张卡的走势图 tooltip（2026-10-01 加）------------------------
         与 kpi.bf.sparkTip 同一套画法（两条线、每格 1 天、缺测断开），
         但**来源不同**：这三张走 bm_meta 的快照，不是 Ookla 的测试库。
         所以整句另写，不复用 kpi.bf.sparkTip —— 那条第一句就写着 Ookla 的口径。
         {n} 是真正有数据的点数（不是窗口天数）：这份是导入快照，
         实测最近几天根本没有数，用窗口天数会让人以为线覆盖了整整 30 天
         （与卡片页脚「覆盖 N 天」同一条理由，见 kpi.mm.tipCover）。 */
      'kpi.mm.sparkTip': '近 {n} 天有数据的逐日速率（每格 1 天），上排是 {o}、下排是 {m}。\n'
                       + '与卡片上的两行大数字**同源**（同一次接口响应）。\n'
                       + '⚠️ 纵轴只覆盖这段时间自身两家合起来的波动范围，**不从 0 起**；'
                       + '缺测的那天线会断开，不补 0。',
      /* 「综合评分与胜场」那张卡专用的走势说明。
         ⚠️ 必须与上面那条分开：这张卡的图**画的是速率，不是评分** ——
         后端的逐日评分不存在（bm_meta_caliber.score_brands 只在整段窗口上算一次），
         要在图上画逐日评分就得在这里重算相对分，那等于给同一个指标造第二个答案。
         所以图画它真正有的逐日数据，并把这件事写在 tooltip 里说清楚，
         否则读者会把这条线当成"评分在波动"。 */
      'kpi.mm.sparkTipScore': '近 {n} 天有数据的逐日速率（每格 1 天），上排是 {o}、下排是 {m}。\n'
                            + '⚠️ 这条线是**速率**，不是综合评分：评分是整段窗口的相对分，'
                            + '接口没有逐日评分。两者量纲与含义都不同，不要互相对照。\n'
                            + '纵轴只覆盖这段时间自身两家合起来的波动范围，不从 0 起；'
                            + '缺测的那天线会断开，不补 0。',
      /* BP 那张卡：单线（网络侧 KPI 不属于任何一家，所以没有图例、没有第二条线）。
         {m} 是卡名，让 tooltip 自己说明画的是哪个指标。 */
      'kpi.mm.sparkTipNet': '{m}：近 {n} 天有数据的逐日走势（每格 1 天）。\n'
                          + '它是**网络侧 KPI**，不属于任何一家，所以这里只有一条线。\n'
                          + '与卡片上的大数字**同源**（同一次接口响应）。\n'
                          + '⚠️ 纵轴只覆盖这段时间自身的波动范围，**不从 0 起**；'
                          + '缺测的那天会断开，不补 0。',
      /* ---- v1 新增：六个视图入口卡（renderViews6）----
         每张卡列出的报告名就是目录里真实存在的看板标题，点击即打开。
         数量由 V6_LIMIT 控制（默认 2 条），多出来的走「展开其余 N 项」。 */
      'v6.title': 'Team Dashboard Overview',
      'v6.sub': '点击报告名直接打开对应看板',
      /* 列头标题现在是链接（2026-09-26 加）：点它打开该视图下的第一条看板。
         tooltip 写成「进入本视图：<实际要去的那张看板>」——
         只写「进入 SP View」的话，点下去开出来的是某个**具体看板**，用户会以为点错了；
         把要打开的那张看板名一起写出来，点之前就知道会去哪儿。
         标点跟着语言走（中文全角冒号、英文半角），别把「：」硬写进 JS 模板。 */
      'v6.headTip': '进入本视图：{n}',
      'v6.more': '展开其余 {n} 项',
      'v6.less': '收起',
      'v6.empty': '该视图下暂无可打开的看板',
      /* 二级子分组页签（2026-09-27 加，BO View 的 RAN/IP/MW/CN/OCS）。
         子分组**名字**不在这里 —— 它跟着目录（SUB_BUILTIN / catalog.subGroups）
         走，因为那是可以在编辑态改、且 MsPortal 共用的一份。
         这里只放页签条自己的两条固定文案。 */
      'v6.subAria': '按专业域筛选本视图',
      'v6.subEmptyTip': '该专业域下暂无看板',
      'aux.qa': 'Knowledge Q&A', 'aux.friends': 'OSS Portal Login', 'aux.admin': 'System Management',
      'aux.reports': 'Task report files', 'aux.tools': '本页相关',
      'aux.ms': '在 MsPortal 维护分组 / 看板 / 账号', 'aux.uni': '统一门户看板门户',
      'aux.more': '展开其余 {n} 项', 'aux.less': '收起',
      /* 2026-09-28：foot.branch 已删除 —— 版权行的后半段改成公司法律实体名
         「ZTE LIBERIA· INC」，中英同形、不需要翻译，已直接写死在 index.html。
         原值：'利比里亚办事处网络运营中心 (OLR MS)'。 */
      'foot.ok': '安全合规模式运行',
      'foot.src': '目录：{n} 个看板 · 生成于 {d}',
      'st.online': '在线', 'st.beta': '试用',
      'pf.myapp': '自研 my_app', 'pf.finebi': 'FineBI', 'pf.external': '外部系统',
      'gate.title': '登录统一门户', 'gate.sub': '与 /uniplam/、/MsPortal/ 共用同一套账号与权限。',
      'gate.user': '用户名', 'gate.pass': '密码', 'gate.go': '登录', 'gate.busy': '登录中…',
      'gate.bad': '用户名或密码错误', 'gate.locked': '尝试次数过多，稍后再试',
      'gate.net': '无法连接认证服务', 'gate.cancel': '取消',
      'gate.hintNoPortal': '本页现在是免登录身份。管理用户需要统一门户账号 —— 登录，或申请一个。',
      /* 自助注册（2026-09-25 加）。文案与 /uniplam/ 的 src/components/LoginView.tsx、
         src/i18n.tsx 的 ar.* 逐条同一口径 —— 申请人在这两处看到的提示必须一致，
         别再自创一套。这里只搬登录页用得到的那批键；管理端的「待审批申请」
         在下方 um.* 里已经有了，不要重复建键。 */
      'ar.requestLink': '没有账号？申请一个', 'ar.backToLogin': '返回登录',
      'ar.subtitle': '提交后由管理员审批，通过后即可用申请时设置的密码登录',
      'ar.usernamePh': '用户名（2-32 位字母/数字/_.-）',
      'ar.passwordPh': '设置密码（至少 8 位）',
      'ar.confirmPh': '再次输入密码',
      'ar.notePh': '申请说明（选填，如所属团队、用途）',
      'ar.submit': '提交申请', 'ar.submitting': '提交中…',
      'ar.ok': '申请已提交，请等待管理员审批',
      'ar.pwdMismatch': '两次输入的密码不一致', 'ar.pwdTooShort': '密码至少需要 8 个字符',
      'ar.invalidInput': '用户名或密码格式不符合要求',
      'ar.duplicate': '该用户名已存在，请直接登录',
      'ar.pendingDup': '该用户名已有待审批的申请，请勿重复提交',
      'ar.tooMany': '待审批申请过多或提交过于频繁，请稍后再试',
      'ar.networkError': '无法连接鉴权服务，请检查网络后重试',
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
      /* 2026-09-25 改名：门户整体品牌由「OLR MS 门户 · Liberia NOC/SOC 统一入口
         (ZTE OLR MS Portal)」统一为「ZTE OLR MS O&M Tools Platform」，
         中英两份字典同值（用户点名要这个名字）。
         ⚠️ doc.title 会写进 document.title（olbr.js:3635），
         顶栏 h1 是 index.html 里的静态结构（.mp-title），两处必须一起改。 */
      'doc.title': 'ZTE OLR MS O&M Tools Platform',
      'doc.desc': 'ZTE OLR MS O&M Tools Platform —— 利比里亚 NOC/SOC 自动化工具平台入口（展示版）。',
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
      /* 2026-09-28：与 zh 同值 —— 品牌标语不翻译，见 zh 处的说明。 */
      'tagline': 'Ultimate Services · Leading Ecosystem',
      'mast.admin': 'Admin portal', 'mast.uni': 'Unified portal', 'mast.logout': 'Sign out',
      'skip': 'Skip to main content',
      'search.ph': 'Search dashboards, owners, tags…',
      'rail.all': 'All', 'rail.clear': 'Clear filters',
      'rail.btn': 'Search & filters', 'rail.tip': 'Open the search box and the group / status filters (Ctrl K)',
      'count.all': '{n} dashboards · {g} groups',
      'count.hit': '{n} / {t} dashboards match',
      /* 2026-09-25 renamed: "Quality Control — key indicators" → "Daily Operation
         Overview" (same value as the zh dict — the user asked for this title in both). */
      'qc.title': 'Daily Operation Overview',
      'qc.sub': 'Active alarms / tickets / changes / PMT / spares · 30-day compliance',
      'qc.sla': '30-day compliance',
      /* 2026-09-25: 'qc.slaTip' / 'qc.slaDrillTip' / 'qc.slaPending' removed with the
         30-day compliance ring block. 'qc.sla' itself stays — only qcMetricLabel's
         fallback uses it (the drill modal is shared with MsPortal, which still
         passes metric=sla). See the zh dict above for the rollback snapshot name. */
      'qc.err': 'Database stats unavailable', 'qc.retry': 'Retry',
      'qc.drill': 'Click for details',
      'qc.updated': 'Updated', 'qc.next': 'next {t}', 'qc.reload': 'Refresh', 'qc.loading': 'Loading…',
      /* 数据区间（2026-09-28 加）。与中文那份同一条约定：连接符必须跟着语言走。 */
      'qc.range': 'Data range {a} ~ {b}',
      /* 2026-09-28：见 zh 处说明。 */
      'qc.rangeHint': 'Click to view data range',
      'qc.na': 'n/a',
      'qc.lv.ok': 'OK', 'qc.lv.warn': 'Watch', 'qc.lv.crit': 'Critical', 'qc.lv.na': 'N/A',
      'qc.dataAt': 'data {t} ({ago})',
      'qc.ago.now': 'just now', 'qc.ago.min': '{n}m ago', 'qc.ago.hour': '{n}h ago', 'qc.ago.day': '{n}d ago',
      'qc.sites': 'Cells/ Sites Outage', 'qc.overdue': 'overdue', 'qc.inbound': 'Inbound', 'qc.outbound': 'Outbound',
      /* 2026-09-28 按用户逐条指定的文案改名。中英两份**同值** ——
         用户给的就是这一串英文，中文那份也照写，不要"顺手翻译回去"。
         （与 qc.title 的中英同值是同一条约定。） */
      'qc.sub.alarm': 'Cells/ Sites Outage', 'qc.sub.tt': 'Ongoing TTs',
      'qc.sub.wo': 'Ongoing WOs', 'qc.sub.cr': 'Unclosed CRs',
      'qc.sub.pmt': 'Unclosed PMTs',
      'qc.sub.spms': 'Unclosed SPMS',
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
      'qc.stock.cap': 'Stock, last {n} h',
      'qc.stock.tip': 'Sampled hourly snapshots of the backlog (last {n} hours, 1 h per slot).\n'
                    + 'The source time column for CRs / PMT has no data in the last 30 days, so an\n'
                    + '"inflow" line would just hug zero — these two cards use the snapshot instead,\n'
                    + 'which answers "is the backlog piling up or draining?".\n'
                    + 'Snapshots only exist for hours the portal was open, so gaps break the line\n'
                    + 'and are NEVER filled with 0 (that would fake a "backlog suddenly cleared" dip).',
      'qc.stock.capPmt': 'Overdue, last {n} h',
      'qc.stock.tipPmt': 'Sampled hourly snapshots of overdue (unfinished) PMT count (last {n} hours, 1 h per slot).\n'
                       + 'Same data as the card\'s big number, seen from a different side: the total shows\n'
                       + 'how large the backlog is, this line shows whether the overdue part is piling up or draining.\n'
                       + 'Snapshots only exist for hours the portal was open, so gaps break the line and are NEVER filled with 0.',
      'qc.stock.starving': 'Not enough samples',
      'qc.cadenceTip': 'Two refresh cadences: site-outage alarms every 5 min (source eflow_active_alarm syncs every '
                     + '5 min, latest {a}); TT/WO/CR/PMT/SPMS and the SLA rate hourly at :06 (eflow_sync starts at '
                     + ':00 and takes ~6 min, the SP spare-part details sync sp_data_sync runs hourly at :10, '
                     + 'latest {f}). Coming back to this tab or clicking Refresh re-pulls the full set immediately.',
      'cxo.title': 'CXO View', 'cxo.sub': 'Executive strategy & operation window',
      'map.title': 'GIS Map', 'map.sub': 'GIS Map',
      'map.gis': 'Alarm', 'map.mw': 'MW', 'map.alarm': 'Live alarms', 'map.loss': 'Packet loss',
      /* 2026-09-28：改为用户点名的 "Open Link"（原为 "Open in new tab"）。
         中文那份同值 —— 用户要的就是这一串英文。 */
      'map.open': 'Open Link', 'map.reload': 'Reload', 'map.load': 'Loading…',
      'email.tab': 'Report files',
      'email.title': 'Auto Report Files', 'email.sub': 'Task report file center (Email Reports)',
      'email.needLogin': 'Sign in to view the report files',
      'email.noAccess': 'This account has no access to the "Auto Report Files" dashboard',
      'esc.title': 'Escalation Matrix',
      'esc.sub': 'Duty contacts · Orange / LONESTAR numbers',
      'esc.expand': 'Expand all {n} rows', 'esc.collapse': 'Collapse',
      /* Label after "Expand all". Deliberately not "Collapse": collapsing means
         hiding the whole table (escOpen), whereas this folds back only the
         extra rows — the table stays on screen. */
      'esc.lessRows': 'Show first 4 rows only',
      'esc.now': 'On duty', 'esc.copy': 'Copy this level', 'esc.copied': 'Copied',
      'esc.lv': 'Level', 'esc.pos': 'Position', 'esc.name': 'Name', 'esc.mail': 'E-mail',
      'esc.count': '{n} rows · {lv} levels', 'esc.src': 'Source: escalation matrix',
      /* v1: only the first 4 rows are shown by default; say so explicitly */
      'esc.moreRows': 'Showing the first 4 rows only — {n} more. Use “Expand all” (top right) to see them.',
      'v.open': 'Full list', 'v.empty': 'No dashboard in this group',
      'v.subOther': 'Unassigned',
      'mast.edit': 'Edit groups', 'mast.editOn': 'Done', 'mast.editing': 'Editing', 'mast.userMenuTip': 'Open user menu',
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
      'edit.title': 'Edit', 'edit.titleTip': 'Edit this dashboard’s Chinese / English title and link (stored on the server, visible to everyone)',
      'edit.titleOk': 'Dashboard updated', 'edit.needTitle': 'The two titles cannot both be empty',
      'edit.formSave': 'Save', 'edit.formAdd': 'Add',
      'edit.f.zh': 'Chinese name', 'edit.f.en': 'English name', 'edit.f.subZh': 'Chinese note', 'edit.f.subEn': 'English note',
      'edit.fph.zh': 'Shown to Chinese users', 'edit.fph.en': 'Shown to English users',
      'edit.fph.subZh': 'One-line description of this group', 'edit.fph.subEn': 'Optional one-line description',
      'edit.kGroups': 'first-level groups', 'edit.kLabels': 'map tab labels',
      'edit.maptabTip': 'Edit this map tab’s Chinese / English name (stored on the server, visible to everyone; clear both to restore the default)',
      'edit.maptabRenamed': 'Map tab label updated',
      /* Dashboard entry add / delete (added 2026-09-26). Mirror of the zh block:
         "移出本列" = drop one group membership (reversible),
         "删除看板" = remove the entry from the shared catalog (irreversible).
         Keep the two clearly distinct in wording — this is the whole point. */
      'edit.itemDrop': 'Remove from column', 'edit.itemDropTip': 'Takes this dashboard out of the current group; if it has no other group it moves to "Archived" — the dashboard itself stays and can be ticked back at any time',
      'edit.itemDel': 'Delete dashboard', 'edit.itemDelTip': 'Removes this dashboard from the shared catalog for everyone; cannot be undone',
      'edit.itemDropped': 'Removed from this group', 'edit.itemDeleted': 'Dashboard deleted',
      /* Kept for parity with the zh dictionary; no longer referenced after the archive
         change (2026-09-28) — see the zh block for why it is kept rather than deleted. */
      'edit.itemLastGrp': 'This is its only group, so removing it would leave the dashboard nowhere to live — use "Delete dashboard" if you really want it gone',
      'edit.itemDelConfirm': 'Permanently delete the dashboard “{n}”?\n\nIt will be removed from the shared catalog, so /olbrportal/ and MsPortal will stop showing it and everyone loses this entry on refresh.\nThis cannot be undone.',
      /* Archive group (added 2026-09-28): the reversible landing spot for "Remove from column". */
      'edit.archived': 'No other group, so it moved to "Archived"', 'edit.archivedTip': 'Still in the catalog — expand the "Archived" section below, or tick it back into any view under "Groups"',
      'arch.title': 'Archived', 'arch.hint': 'These dashboards are out of every view but still in the catalog · tick them back under "Groups"',
      'arch.empty': 'Nothing archived',
      'arch.unarchive': 'Unarchive', 'arch.unarchiveTip': 'Put this only group back to a view you pick',
      'edit.itemAdd': 'New dashboard', 'edit.itemAddTip': 'Create a dashboard from an existing one (icon / platform / description are inherited; you only set the name and link)',
      'edit.itemAddPick': 'Pick an existing dashboard as the template (searchable)',
      'edit.itemAddSearch': 'Search dashboard names…',
      'edit.itemAddBack': 'Change template',
      'edit.itemAdded': 'Dashboard added',
      'edit.itemNeedUrl': 'Enter a link first',
      'edit.itemBadUrl': 'The link must start with http:// or https://',
      'edit.archCount': '{n} dashboard(s) in Archived',
      'edit.f.itemZh': 'Dashboard name (Chinese)', 'edit.f.itemEn': 'Dashboard name (English)', 'edit.f.itemUrl': 'Link',
      'edit.fph.itemZh': 'e.g. NUR Dashboard', 'edit.fph.itemEn': 'Shown to English users',
      'edit.fph.itemUrl': 'http://192.168.100.20/myapp/?page=xxx',
      'edit.itemTplFrom': 'Template: {n}',
      'v.emptyFilter': 'Nothing matches the current filters', 'v.adjust': 'Adjust keywords or clear filters',
      /* ---- v1 additions: CXO daily KPI band (renderKpi) ---- */
      'kpi.title': 'Network Status Overview',
      /* ⚠️ 口径必须与中文一致：卡上四个数字都是「昨日完整值」，
         写成 "Today's …" 会让人以为这是实时数（本页其它看板多为实时，
         更容易误读）。2026-09-24 改口径时只改了中文、漏了这里，
         是用户 09-25 的截图里发现的。改口径时**两份字典一起改**。 */
      'kpi.sub': 'Last complete day · 90-day window · 2G / 3G / 4G month-to-date availability',
      'kpi.updated': 'Data {t}',
      'kpi.err': 'Metrics unavailable',
      'kpi.retry': 'Retry',
      'kpi.month': '{m} month-to-date avg',
      /* Availability card title. ⚠️ Deliberately NOT reusing 'qc.sla'
         ("30-day compliance"), which is a different metric entirely. */
      'kpi.avail': 'Availability',
      'kpi.noMonth': 'No month-to-date value yet',
      /* Availability-card footer: yesterday / target threshold / gap to target.
         "pp" = percentage point — 97.38% vs 99.65% differ by 2.27 points,
         so writing "2.27%" there would be wrong. */
      'kpi.yday': 'Yesterday',
      'kpi.thr': 'Threshold',
      'kpi.thrLine': 'Target',
      'kpi.gapThr': 'vs target',
      'kpi.pp': 'pp',
      /* ---- Rich-card strings (kpiRichHtml) ----
         Anything containing punctuation goes through a {placeholder} template so
         the punctuation follows the language (full-width for zh, ASCII for en).
         Do NOT hardcode （）／： in the JS template — that produced
         "Latest · 2026-09-24（As of 2026-09-24）" in the English UI. */
      'kpi.wow': 'WoW',
      'kpi.mom': 'MoM',
      'kpi.max': 'Max',
      'kpi.avg': 'Avg',
      'kpi.min': 'Min',
      'kpi.days': '{n} days',
      'kpi.tipName': '{n} ({u})',
      'kpi.tipLatest': 'Latest: {d}',
      'kpi.tipBase': '{k} vs {d} ({v} {u})',
      'kpi.asofFmt': 'Latest · {d} (as of {a})',
      /* First line of the rich-card tooltip. The definition must be stated:
         none of these four numbers is for today, while most boards on this
         page are live/today — easy to misread. */
      'kpi.tipRich': 'Source: CXO 90-day business board (last complete day; today is still accumulating and excluded)',
      'kpi.openTip': 'Open the full dashboard for "{n}" ({b})',
      'kpi.boardRich': 'CXO 90-day business board',
      'kpi.boardAvail': 'Daily Availability KPI',
      'kpi.tipAvail': 'Source: Daily Availability KPI (Availability-NW sheet) aggregated by Cell Group, same definition as {board}',
      'kpi.tipAvailFoot': 'The big number is the month-to-date average; the footer shows yesterday, the target threshold, and yesterday minus the target (pp = percentage points; negative means yesterday was below target).',
      'kpi.availTrendCap': 'Last {n} days',
      'kpi.availTrendTip': 'Daily Cell Availability over the last {n} days (1 day per slot).\n'
                         + 'Same response as the big number and the footer, so the end of the line IS the "yesterday" slot.\n'
                         + 'The vertical axis covers only this window\'s own range and does NOT start at 0 —\n'
                         + 'availability sits at 97-99%, so a zero-based axis would flatten every movement into a straight line.\n'
                         + 'Use the footer\'s "gap to target" to judge compliance; this line is only for the trend.',
      'kpi.availAsof': 'Month to date · as of {d}',
      /* ---- Benchmark row (Network Benchmark View, added 2026-10-01) ----------
         The title is the exact string the user asked for, so zh and en hold the
         SAME value (same rule as map.gis / map.open). */
      'kpi.bf.title': 'Network Benchmark View',
      'kpi.bf.sub': 'Orange vs MTN Speedtest comparison · range average · last {n} days',
      'kpi.bf.subNone': 'Orange vs MTN Speedtest comparison · range average',
      'kpi.bf.download': 'Download', 'kpi.bf.upload': 'Upload', 'kpi.bf.latency': 'Latency',
      /* The big number is a range average; it must read differently from
         p50/p90 (per-day percentiles) or users will expect them to match. */
      'kpi.bf.avgCap': 'range avg',
      'kpi.bf.pctCap': 'P50 {a} / P90 {b}',
      'kpi.bf.lead': '{n} leads',
      'kpi.bf.win': 'Daily win rate {n}%',
      'kpi.bf.winTip': 'On "{m}", {n} won {w} of the last {d} days (win rate {r}%).\n'
                     + 'Only days where BOTH brands have data are counted; a day with one brand only is not a win or a loss.',
      'kpi.bf.tipName': '{n} ({u})',
      /* Data source. Naming "Speedtest by Ookla" is required: the logo in the
         card's bottom-right corner is Ookla's registered trademark, so the text
         states where the data comes from (nominative use) and stops readers
         from mistaking the mark for a decorative icon. */
      'kpi.bf.tipSrc': 'Source: Speedtest by Ookla · my_app bm_speedtest competitor analysis, same definition as "Key metrics comparison"',
      'kpi.bf.ooklaTip': 'Speedtest by Ookla',
      /* {win} in 'kpi.bf.tipAvg' is a DAY COUNT (the 30 of "last 30 days"),
         NOT the whole sentence from 'kpi.bf.sub'. Nesting the full sentence
         produced unreadable text; each key states exactly one thing. */
      'kpi.bf.tipAvg': 'The big number is the **range average** over the last {win} days (mean of daily means), not a single day snapshot.',
      'kpi.bf.tipPcts': 'P50 / P90 are percentiles of **daily values**, a different statistic from the range average — the two need not match.',
      'kpi.bf.tipLead': 'The leader is the stronger brand on this metric in the range — higher speed, lower latency.',
      'kpi.bf.tipTests': '{n}: {t} tests · {dev} devices',
      'kpi.bf.range': 'Window', 'kpi.bf.days': 'days',
      'kpi.bf.tests': 'Tests', 'kpi.bf.testsUnit': 'both brands',
      'kpi.bf.na': 'No data in range',
      'kpi.bf.board': 'Speedtest competitor analysis',
      /* Card sparkline tooltips (added 2026-10-01). Same drawing method as the
         Network Status Overview cards (.qc-spark line), but THIS row draws two
         lines (Orange / MTN) instead of the single line used by the three
         availability cards — the tooltip has to say so, otherwise a reader takes
         it for two samples of one metric.
         {o} / {m} are the brand labels from the backend, never hard-coded.
         No "Last 30 days" caption line below the chart: these cards are narrower
         than the row above, and everything the caption would say is in the title. */
      'kpi.bf.sparkTip': 'Daily trend over the last {n} days (one cell = one day); '
                       + '{o} on top, {m} below.\n'
                       + 'Same response as the two big numbers on this card, so the end of the line '
                       + 'is the last day of the window.\n'
                       + '⚠️ The y-axis spans only this period\'s combined range for the two brands — '
                       + 'it does **not** start at zero; a missing day breaks the line rather than plotting 0.',
      /* Tooltip for the row title (.band-k). The row carries TWO data sources
         since 2026-09-30, so kpi.bf.sub (which only describes the three Ookla
         cards) can no longer sit on the whole-row title without being wrong.
         Card tooltips still use kpi.bf.sub* / kpi.mm.*: each card states its
         own source, and mixing them would put Meta text on an Ookla card. */
      'kpi.bf.subBoth': 'Orange vs MTN · the six cards in this row come from two sources: '
                      + 'three Speedtest by Ookla cards (last {n} days, my_app bm_speedtest competitor analysis) and '
                      + 'three my_app Meta benchmark report cards (bm_meta, same window). '
                      + 'Both are range averages, but the samples and the test methods differ, '
                      + 'so the numbers are **not directly comparable**.',
      /* ---- Benchmark row, second group: Meta benchmark report (added 2026-09-30) --
         Source /api/bm-meta/overview, i.e. my_app `?page=bm_meta` (the
         `meta_data` table, a static Excel-imported snapshot). Same row and same
         window as the three Ookla cards, but a DIFFERENT dataset — hence its own
         card names, definitions and source badge instead of reusing kpi.bf.*:
         that block's first sentence says "Speedtest by Ookla", which would be a
         lie on a Meta card. Card names are copied from my_app's bmm.* keys so
         one metric never has two names across the two portals. */
      'kpi.mm.speed': 'Speed',
      'kpi.mm.scores': 'Composite score and wins',
      'kpi.mm.bp': 'BP',
      /* Units. Only the score differs between languages (分 / pts); the other two
         are identical here — they still live in the dictionary so the renderer
         always goes through t() and never hardcodes "Mbps" on the zh branch. */
      'kpi.mm.unitMbps': 'Mbps', 'kpi.mm.unitScore': 'pts', 'kpi.mm.unitPct': '%',
      /* Per-day observed range. my_app calls this card "Observed range"
         (bmm.card.rangeLabel); shortened here into an inline prefix because the
         card holds two side-by-side rows. */
      'kpi.mm.obsRange': 'range {a} ~ {b}',
      /* Wins. Copied verbatim from my_app's bmm.card.winDaysFmt — one fact must
         read the same on both pages or users will think they are two metrics. */
      'kpi.mm.leadDays': 'leads {w} of {d} days',
      'kpi.mm.avg': 'Average',
      'kpi.mm.lead': '{n} leads',
      /* Footer cells: left "Window 30 days", right "Coverage 23". The second one
         is the number of days that actually hold data: the window is "last 30
         days" while this dataset is an imported snapshot (data ends 2026-09-23),
         so without it a reader assumes the average covers all 30 days. */
      'kpi.mm.win': 'Window', 'kpi.mm.days': 'days', 'kpi.mm.cover': 'Coverage',
      /* Footer cell 3 on the two Meta cards holds the LOGO (META_LOGO at the end
         of this file); this key is its accessible name (the role="img" aria-label),
         exactly like the Ookla badge — the artwork itself carries no aria-label.
         The badge has no text any more, so this string only surfaces in screen
         readers and on hover. */
      'kpi.mm.srcAlt': 'Meta report',
      /* Source badge of the BP card (plain text, changed 2026-09-30 on request).
         Why not "Meta report": BP, FDD throughput, PRB utilization, traffic volume
         and RRC users form one group of network-side KPIs (Radio-side FDD
         counters) belonging to no operator. Reuses my_app's name for that group
         (bmm.sec.network) so one group has one name across both portals. */
      'kpi.mm.srcNet': 'Network-side KPIs',
      'kpi.mm.tipName': '{n} ({u})',
      'kpi.mm.tipSrc': 'Source: my_app Meta benchmark report (bm_meta) · meta_data table (static Excel import). '
                     + 'This is a DIFFERENT dataset from the three Ookla cards on the left; '
                     + 'the two sets of numbers are not directly comparable.',
      /* Source line for the network-side KPIs, kept SEPARATE from the one above:
         their source badge differs (Network-side KPIs ≠ Meta report), and sharing
         one sentence would have the badge say one thing while the tooltip says
         another. */
      'kpi.mm.tipSrcNet': 'Source: network-side KPIs (BP, FDD DL IP throughput, DL/UL PRB utilization, traffic volume, RRC users) — '
                        + 'Radio-side FDD counters that belong to neither operator and are excluded from the head-to-head and the composite score. '
                        + 'They are NOT the same metric group as the "Meta report" cards above; '
                        + 'the portal reads them from the same my_app bm_meta snapshot.',
      'kpi.mm.tipWin': 'The big number is the **range average** over the last {win} days (mean of daily means), not a single-day snapshot.',
      'kpi.mm.tipCover': 'Only {n} days in the window actually hold data — this dataset is an imported snapshot, data ends {d}.',
      'kpi.mm.tipRange': '"range" is the min ~ max of **daily values** (one slot per day), '
                       + 'a different statistic from the range average — the two need not match.',
      'kpi.mm.tipScore': 'The composite score is **relative**: the stronger brand scores 100 and the other scales by ratio. '
                       + 'It is not an absolute score and does not describe network quality itself.',
      'kpi.mm.tipLead': '"leads x of y days" = on the y days where both brands have data, this brand had the higher speed on x of them; '
                      + 'a day where the two are equal counts for neither. '
                      + 'Warning: the two x values may therefore add up to less than y — the difference is tied days. '
                      + '{tie} Ties count as a win for neither brand on either portal; they are not missing data.',
      'kpi.mm.tieN': '{n} tied days in this window',
      'kpi.mm.tie0': 'no tied days in this window',
      'kpi.mm.tipBp': 'BP is a **network-side KPI**, so this card has no brand rows and no leader badge — '
                    + 'only the range average and the daily range. The database stores a decimal ratio; the API returns a percentage.',
      'kpi.mm.rowDays': '{n} days with data',
      'kpi.mm.rowScore': 'Composite score {v} {u}',
      'kpi.mm.na': 'No data in range',
      'kpi.mm.board': 'Meta benchmark report',
      /* Sparkline tooltips for the three Meta cards (added 2026-10-01).
         Same drawing method as kpi.bf.sparkTip, but a different data source
         (the bm_meta snapshot, not Ookla's test database), so the wording is
         written separately — the Ookla one names Ookla in its first sentence.
         {n} is the number of days that actually have data, not the window
         length: this is an imported snapshot and the last few days are empty,
         so the window length would suggest the line covers all 30 days. */
      'kpi.mm.sparkTip': 'Daily speed for the {n} days that have data (one cell = one day); '
                       + '{o} on top, {m} below.\n'
                       + 'Same response as the two big numbers on this card.\n'
                       + '⚠️ The y-axis spans only this period\'s combined range for the two brands — '
                       + 'it does **not** start at zero; a missing day breaks the line rather than plotting 0.',
      /* Used only by the "Composite score and wins" card. It must differ from the
         tooltip above: this card's chart plots SPEED, not score. A daily score
         does not exist on the backend (bm_meta_caliber.score_brands computes a
         single relative score for the whole window); drawing one would mean
         recomputing the definition here, i.e. a second answer to the same
         question. So the chart shows the daily data that does exist, and the
         tooltip says so — otherwise the line reads as "the score fluctuating". */
      'kpi.mm.sparkTipScore': 'Daily speed for the {n} days that have data (one cell = one day); '
                            + '{o} on top, {m} below.\n'
                            + '⚠️ This line is **speed**, not the composite score: the score is a '
                            + 'relative figure for the whole window and the API has no daily score. '
                            + 'Different units and meaning — do not read one against the other.\n'
                            + 'The y-axis spans only this period\'s combined range, not from zero; '
                            + 'a missing day breaks the line rather than plotting 0.',
      /* The BP card: a single line (a network-side KPI belongs to no brand, so no
         legend and no second line). {m} is the card name, so the tooltip names
         the metric it draws. */
      'kpi.mm.sparkTipNet': '{m}: daily trend for the {n} days that have data (one cell = one day).\n'
                          + 'This is a **network-side KPI**, not brand-specific, hence a single line.\n'
                          + 'Same response as the big number on this card.\n'
                          + '⚠️ The y-axis spans only this period\'s own range — it does **not** start '
                          + 'at zero; a missing day breaks the line rather than plotting 0.',
      /* ---- v1 additions: six view-entry cards (renderViews6) ---- */
      'v6.title': 'Team Dashboard Overview',
      'v6.sub': 'Click a report name to open that dashboard',
      'v6.headTip': 'Enter this view: {n}',
      'v6.more': 'Show {n} more',
      'v6.less': 'Show less',
      'v6.empty': 'No dashboard available under this view',
      'v6.subAria': 'Filter this view by technology domain',
      'v6.subEmptyTip': 'No dashboard under this domain yet',
      'aux.qa': 'Knowledge Q&A', 'aux.friends': 'OSS Portal Login', 'aux.admin': 'System Management',
      'aux.reports': 'Task report files', 'aux.tools': 'About this page',
      'aux.ms': 'Manage groups / dashboards / accounts in MsPortal', 'aux.uni': 'Unified dashboard portal',
      'aux.more': 'Show {n} more', 'aux.less': 'Show less',
      /* 2026-09-28：foot.branch 已删除，见 zh 处的说明。
         原值：'Liberia Office · Network Operation Center (OLR MS)'。 */
      'foot.ok': 'Compliance mode',
      'foot.src': 'Catalog: {n} dashboards · built {d}',
      'st.online': 'online', 'st.beta': 'beta',
      'pf.myapp': 'my_app', 'pf.finebi': 'FineBI', 'pf.external': 'external',
      'gate.title': 'Sign in to the unified portal',
      'gate.sub': 'Same account and permissions as /uniplam/ and /MsPortal/.',
      'gate.user': 'Username', 'gate.pass': 'Password', 'gate.go': 'Sign in', 'gate.busy': 'Signing in…',
      'gate.bad': 'Wrong username or password', 'gate.locked': 'Too many attempts, try later',
      'gate.net': 'Cannot reach the auth service', 'gate.cancel': 'Cancel',
      'gate.hintNoPortal': 'This page is currently on the no-sign-in identity. Managing users needs a unified-portal account — sign in, or request one.',
      /* Self-service registration (added 2026-09-25). Wording mirrors
         src/components/LoginView.tsx and the ar.* keys in src/i18n.tsx
         one-for-one — applicants must see the same messages on both pages. */
      'ar.requestLink': 'No account? Request one', 'ar.backToLogin': 'Back to sign in',
      'ar.subtitle': 'An admin will review your request; once approved, sign in with the password you set here',
      'ar.usernamePh': 'username (2-32 chars a-z 0-9 _.-)',
      'ar.passwordPh': 'set a password (min 8 chars)',
      'ar.confirmPh': 'confirm password',
      'ar.notePh': 'reason / team (optional)',
      'ar.submit': 'Submit request', 'ar.submitting': 'Submitting…',
      'ar.ok': 'Request submitted, waiting for admin approval',
      'ar.pwdMismatch': 'The two passwords do not match', 'ar.pwdTooShort': 'Password must be at least 8 characters',
      'ar.invalidInput': 'Invalid username or password format',
      'ar.duplicate': 'That username already exists, please sign in',
      'ar.pendingDup': 'A request for that username is already pending',
      'ar.tooMany': 'Too many pending requests, please try again later',
      'ar.networkError': 'Cannot reach the auth service, please check your network',
      'dr.title': 'Details', 'dr.rows': '{n} rows', 'dr.page': '{p} / {q}',
      'dr.load': 'Loading details…', 'dr.empty': 'No matching record', 'dr.err': 'Detail failed: {e}',
      'dr.none': 'No data', 'dr.qPh': 'Filter rows…',
      'dr.reload': 'Refresh', 'dr.export': 'Export Excel', 'dr.openBoard': 'Open full dashboard',
      'dr.filterHint': 'Note: filtering the catalogue by dimension lives on the filter bar chips; this dialog only drills into details.',
      'dr.drillSuffix': ' · Details', 'dr.total': '{n} rows in total', 'dr.exportErr': 'Export failed',
      'dr.noData': 'Nothing to export',
      'env.local': 'Local host', 'env.lr': 'Liberia',
      'foot.ver': 'Ver 1.0-OLBR · showcase edition',
      'doc.title': 'ZTE OLR MS O&M Tools Platform',
      'doc.desc': 'ZTE OLR MS O&M Tools Platform — entry to the Liberia NOC/SOC automation tool platform (showcase edition).',
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
      'um.confirmDelete': 'Are you sure you want to delete user {name}? This cannot be undone.',
      'um.selfDelete': 'You cannot delete the account you are signed in with',
      'um.lastAdmin': 'You cannot delete the last admin',
      'um.pages': 'Page setup',
      'um.pagesTitle': 'Page setup · {name}',
      'um.pagesSubtitle': 'Pick which dashboard opens after sign-in and which dashboards are visible (same record as /uniplam/)',
      'um.landing': 'Landing dashboard',
      'um.landingNone': 'No override (stay on all dashboards)',
      'um.landingNoCard': 'No specific dashboard',
      'um.viewGrid': 'Card grid (unified portal)',
      'um.viewList': 'List (unified portal)',
      'um.viewMatrix': 'Group matrix (unified portal)',
      'um.viewTasks': 'Task view (unified portal)',
      'um.allowed': 'Visible scope',
      'um.allowedAll': 'No restriction (all groups and dashboards)',
      'um.allowedCustom': 'Custom allowlist',
      'um.groupsMsportal': 'By group · this page (/olbrportal/)',
      'um.groupsPortal': 'By group · unified portal (/uniplam/)',
      'um.groupsPortalNone': 'The unified portal has no global catalog saved; group-based auth is unavailable',
      'um.allowedCards': 'By dashboard (shared by both portals)',
      'um.cardsLocalOnly': 'The unified portal catalog could not be loaded; the options are locked: the dashboard ids here are inferred from the URL and do not match what /uniplam/ actually uses — saving a selection would make it unreadable there. Please refresh and retry.',
      'um.allowedHint': '“By dashboard” uses ids shared by both portals; it takes effect on /olbrportal/ and /uniplam/ at once. The two “by group” scopes are per-side only; both can be ticked.',
      'um.allowedEmpty': 'Empty allowlist: this account will see no dashboards after sign-in.',
      'um.navVisibilityOnly': 'Affects only the portal navigation visibility, not access control; hidden dashboards remain reachable by direct link.',
      'um.pagesSaved': 'Saved page setup for {name}',
      'um.pagesSave': 'Save page setup',
      'um.pagesCancel': 'Collapse',
      'um.storage': 'Storage',
      'um.storageSqlite': 'SQLite database',
      'um.storageJson': 'JSON file',
      'um.backups': 'Auto-backups: {n}',
      'um.lastWrite': 'Last write',
      'um.migrated': 'Migrated from the old JSON',
      'um.requestFail': 'User data load failed: {msg}',
      'um.needAdmin': 'Admins only',
      'um.needPortalLogin': 'User management needs a unified-portal account; sign in here first',
      'um.pendingTitle': 'Pending requests',
      'um.pendingEmpty': 'No pending requests',
      'um.colApplicant': 'Applicant',
      'um.colNote': 'Note',
      'um.colTime': 'Time',
      'um.colIp': 'Source IP',
      'um.approve': 'Approve',
      'um.reject': 'Reject',
      'um.approveConfirm': 'Approve the account request from {name}?',
      'um.rejectConfirm': 'Reject the account request from {name}?',
      'um.approved': 'Approved {name}: the password set during the request is now active; a change is required at first sign-in',
      'um.rejected': 'Rejected the account request from {name}',
      'um.notFound': 'Request not found or already handled'
    }
  };

  /* --------------------------------------------------------------- icons -- */
  // phosphor 图标 class 名映射。ic(name) 在主文件里读 PH[name]，未命中回 dashboard。
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

  /* ------------------------------------------------------------ layout -- */
  // 三级层级的归属写在这里（数据里没有 tier 字段）。
  //   T0 = 左栏焦点区（CXO 用大卡、SP 用行式，两块叠在地图左边）；
  //   T1 = 主视图：一组一个页签，一次只展开一个面板，面板内是卡片流；
  //   T2 = 辅助：默认只显示 2 行。
  var T0 = ['CXO View', 'SP View'];
  var T1 = ['MS View', 'FLM View', 'FO View', 'BO View'];
  var T2 = ['Knowledge Q&A', 'Friends Link', 'System Admin'];
  var AUX_ROWS = 2;           /* 辅助分组默认露出的行数 */
  var OTHER = '__other';      /* 不属于任何已知分组的看板，在页签里单列一项 */
  /* 归档分组（2026-09-28 加）：看板真正的"收起来"去处。
     ----------------------------------------------------------------------------
     背景：「移出本列」原先只剩一个分组时直接拒绝（edit.itemLastGrp / itemDel 提示），
     因为本项目**没有"不属于任何分组的看板"这种状态** —— 零归属的条目在页签、
     入口卡、MsPortal 的区块里全都渲染不出来，移出等于弄丢。

     归档把这件事变成**可逆**的：条目只是换到一个真实的兜底分组里，仍留在共享目录、
     仍能在归档区看到、也能被「分组」浮层一键勾回去。于是：
       · 「移出本列」不再需要"这是唯一分组"的拦截；
       · 想"收起来"不必动用不可逆的「删除看板」。

     ⚠️ id 不叫 __archive：带 __ 前缀的是**伪分组**（OTHER = 不属于任何已知分组、
     RENAME_HEAD = 页签改名的伪 key，见 DATA.OTHER / DATA.RENAME_HEAD）。
     归档是一个真实分组（有 zh/en、会进 groups 定义、要随目录落盘），
     用普通 id，免得与那套"伪"约定混在一起。

     ⚠️ 刻意不进 T1/T2：它不是常驻版面的一部分。作为**自定义分组**出现在 L1 页签条，
     由 ensureArchiveGroup() 在首次真的归档时创建，只在有内容时才渲染（见 renderAux）。 */
  var ARCHIVE = 'Archived';
  var AUX_TITLES = {
    'Knowledge Q&A': 'aux.qa', 'Friends Link': 'aux.friends', 'System Admin': 'aux.admin'
  };
  /* 2026-09-25 按需求删掉 realtime_alarm 与 packet_loss 两个页签 —— 本栏只保留
     「GIS 地图」与「微波实时」，与 MsPortal 侧保持一致（那边同日同样删了两个）。
     后端 TAB_PAGES 白名单里这四个 page 值**刻意保留**：服务端已存过的 tabLabels
     改名记录不会因为白名单收窄而被丢弃，将来若要恢复页签不用重新改名。

     ⚠️ 2026-09-29 更正：本栏是**两个页签**，gis（GIS 地图）与 mwRealTime（微波实时）
     都要显示。当天更早的一次改动曾把数组收窄成只剩 mwRealTime，那是我把用户的
     「添加并只显示 page=mwRealTime 的地图组件」误读成了"用 mwRealTime 顶掉 gis"；
     用户随后澄清「GIS Map 和 mwRealTime 都要显示」，故恢复成两条。
     页签条保留（有两个页签就必须有地方切换）。

     ⚠️ 这份数组是页签的**唯一真相源**：olbr.js 的 mapItems() 直接把这两条展开成页签，
     **不再**按"目录里有没有对应看板"过滤（原实现抄了 MsPortal 的 .filter(m => !!m.item)，
     而线上目录里 page=gis 的看板早被删了 —— 出厂默认 portal-default.json 里有
     custom-gis-map，线上 /api/portal-catalog 的 56 条里没有 —— 于是 gis 页签被
     静默滤掉、页签条整条不渲染，表现就是「GIS Map 没有了」）。
     目录只用来取显示标题，取不到就回落这里的 key（map.gis / map.mw）。
     要改页签数量/顺序就改这里，不要再去动目录。 */
  var MAP_TABS = [
    { page: 'gis', key: 'map.gis', icon: 'map' },
    { page: 'mwRealTime', key: 'map.mw', icon: 'broadcast' }
  ];
  /* 保留伪页签 key：本栏标题/副标题不是地图页签，但与页签共用同一份
     catalog.tabLabels 存储和改名浮层（2026-09-23 加）。__ 前缀与上面的 OTHER 同一约定，
     且 my_app 的 page 值（gis/mwRealTime/…）不会以双下划线开头，不会撞名。
     后端 TAB_PAGES 里有同名白名单，两处必须一起改。 */
  var RENAME_HEAD = '__head';
  /** 所有可从界面上改名的项：2 个页签 + 本栏标题/副标题。 */
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
    /* 地图卡片里与地图同级的小块贴底浮层。
       ⚠️ 2026-10-14：原注释说这里针对的是「Critical/Major/Minor/Warning/OK」那块
       **卡片内**图例 —— 它早已不存在（GIS 图例 2026-09-28 起移到地图上，成了
       .gis-legend-overlay 这个绝对定位浮层，自带 bottom/left/z-index，不需要这条规则
       把它摆到底部）。而这条选择器**恰好会命中它**：浮层是 .ant-card-body 里
       唯一「不是 .leaflet-container」的直接子元素，于是被刷上 rgba(255,255,255,.88)
       的 !important 白底，盖掉 index.css 里 :root[data-theme] 的 transparent
       （实测命中两条 background 规则，注入的这条胜出）。
       表现：门户内嵌时图例永远是一块不透明白底，直开 /myapp/?page=gis 才是透明浮字 ——
       同一份 CSS 在两种入口下观感不同。
       故把浮层排除在外。**保留**这条规则本身：将来若有别的小块与地图同级，
       仍需「贴底浮层」这个待遇，删掉它会静默退回「被地图挤出裁掉」。 */
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)):not(.gis-legend-overlay){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
    '.leaflet-container{height:100%!important;min-height:0!important;max-height:none!important;width:100%!important;border-radius:0!important}'
  ].join('');

  /* ----------------------------------------------------- qc thresholds -- */
  // QC 指标阈值表。与 MsPortal 的 Quality Control 逐字对应（同一个数字在两个门户上
  // 被读成两件事，比样式不一致更糟）。
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
  /* v1：等级徽章整块不再渲染，这个键表和下面的 qcLevel() 因此**在当前版本没有调用点**。
     刻意保留而不是删掉，理由：
       · 它们是「分档」这件事的唯一实现，与 MsPortal 那份逐字对应；
         以后若要恢复徽章（或在 tooltip 里重新给阈值），直接接回去即可，
         不用从 MsPortal 再抄一遍 —— 抄一遍就有抄歪的风险。
       · 删掉 QC_TARGETS 的阈值定义会连带删掉 qc.targetTip.* 两处文案，
         而 v1 只是"不显示"，并不是"不认可这套阈值"。
     ⚠️ 但它们**确实不再被渲染**，读代码的人不要以为屏幕上还有分档。 */
  var QC_LV_KEY = { ok: 'qc.lv.ok', warn: 'qc.lv.warn', crit: 'qc.lv.crit', na: 'qc.lv.na' };
  /* 全量每小时 :06:30（紧跟 eflow_sync 跑完），告警每 5 分钟 :00:30（紧跟整表 replace）。 */
  var QC_FULL_MIN = 60, QC_FULL_OFFSET = 390, QC_ALARM_MIN = 5, QC_ALARM_OFFSET = 30;

  /* --------------------------------------------------------- kpi specs -- */
  // id 必须与 olib 接口 cards[].id 完全一致，写错会静默变成一张「—」卡。
  // zh/en 是本页自带的名字，**只在接口那张卡缺失时兜底**（例如 KPI 库还没跑）。
  // 接口在时一律用接口的名字（它才是指标字典这份唯一真相源）。
  // 这张表**没有 icon 字段**：富卡片的排版里不放图标，kpiRichHtml 从不读它。
  // page：点这张卡要打开的 my_app 页面（2026-09-29 加）。
  //   三张卡同源 —— 数值全部取自 /api/olib-soc-dashboard/overview?days=90，
  //   那就是 my_app `?page=vmaxCxoDashboard_90Days` 的只读接口，所以三张卡
  //   指向**同一个页面**，这里逐条写而不是在渲染函数里写一个共用常量：
  //   将来若三张卡拆到不同页面（比如流量看 90 天、用户看当期），
  //   改动就只发生在这个数据表里，渲染函数一行都不用动。
  //   ⚠️ 值必须是 my_app `App.tsx` 的 PageKey（见 VALID_PAGES 白名单），
  //   写错会被静默回落到概览页，表现为「点了却打开别的页」——
  //   与 QC_BOARD_PAGE（olbr.js）同一条约束。
  var KPI_RICH = [
    { id: 'traffic_gb',     unit: 'TB',   digits: 2, div: 1024,
      page: 'vmaxCxoDashboard_90Days',
      zh: '总流量',           en: 'Total Traffic' },
    { id: 'active_user_k',  unit: 'K',    digits: 1, div: 1,
      page: 'vmaxCxoDashboard_90Days',
      zh: '活跃用户',         en: 'Active Users' },
    { id: 'video_thr_kbps', unit: 'Mbps', digits: 2, div: 1000,
      page: 'vmaxCxoDashboard_90Days',
      zh: '视频下载速率',     en: 'Video Throughput',
      /* 门户显示名覆盖（2026-10-01 加）：后端接口返回的 title_en 是
         "Valid Throughput of Video Download"（太长、窄卡必然截断）。
         label_en 只在**门户**覆盖成更短的显示名，不改后端共享口径 ——
         my_app 90 天看板页仍显示后端原名。中文「视频下载速率」本就短，
         不设 label_zh。要恢复后端原名，删掉 label_en 这一行即可。 */
      label_en: 'Video Throughput' }
    /* 2026-09-24：曾加过第四张 video_tb（视频流量，与源看板截图一致），
       用户随后要求去掉、恢复六张卡一行 —— 故此处只有三张。
       要恢复只需把 { id: 'video_tb', unit: 'TB', digits: 1, div: 1,
       zh: '视频流量', en: 'Video Traffic' } 加回来，
       并把 .qc-grid 的列数从 6 改回 4。 */
  ];
  /* 2G / 3G / 4G 分别对应 xlsx 里的哪个 Cell Group。写成显式映射而不是
     startsWith('2G') 去猜：源表以后加了 "2G ERA" 之类的档位时，
     前缀匹配会悄悄命中错的那一行，而这张卡上一个错的可用率没人能一眼看出来。

     page：点这张卡要打开的 my_app 页面（2026-09-29 加，用户要求）。
     三张卡都指向可用率页 —— 它们的大数字（当月均值）与页脚的昨日/阈值/距阈值
     就来自那一页同口径的汇总，所以"点卡看完整看板"是成立的，
     不是随便配一个链接凑数。
     ⚠️ 与 KPI_RICH.page 同一条约束：值必须是 my_app App.tsx 的 PageKey
     （见 VALID_PAGES 白名单），写错会被静默回落到概览页，
     表现为「点了却打开别的页」。
     逐条写而不是在渲染函数里写一个共用常量，理由同 KPI_RICH：
     将来若三张卡拆到不同页面，改动只发生在这张表里。 */
  var KPI_AVAIL_ROWS = [
    { key: '2G', group: '2G ALL', page: 'avail_ms' },
    { key: '3G', group: '3G ALL', page: 'avail_ms' },
    { key: '4G', group: 'FDD ALL', page: 'avail_ms' }
  ];
  /* ---- Benchmark（竞对速率）三张卡：ORANGE vs MTN 关键指标对比 ----------
     数据源 /api/bm-speedtest/overview?start=&end=，即 my_app
     `?page=bm_speedtest` 那个页面「Key metrics comparison」那组卡的只读接口。
     口径（唯一真相源）在 my_app `backend/services/bm_speedtest_caliber.py`：
     大数字是**区间均值**（summary[brand][metric]），不是某一天的快照 ——
     所以卡上必须写明窗口（窗口天数由后端 meta 给，见 speedWinDays()）。
     p50/p90 取 summary[brand].pcts[metric]，是**逐日值**的分位数，
     与大数字（整体均值）不是同一个统计量，卡片上用中性的措辞区分开。

     ⚠️ 只列 download / upload / latency 三项，**不含 jitter**：
     用户点名只要这三张（源页面那张卡里还有第四张 Jitter，
     这里是**刻意少一张**，不是漏了）。要补就把 jitter 加进这张表 ——
     每项的 key 必须与 caliber.METRICS 的键完全一致（写错会得到一张全 — 的卡）。

     kind: 'speed' 越大越好 / 'latency' 越小越好 —— 只用来决定「领先方」徽章的
     比较方向，**不**在这里重算一遍胜负（胜率另有 wins.metrics 那份权威数据）。
     unit: 照抄 caliber.METRICS 的单位（download/upload 是 Mbps、latency 是 ms），
     卡片上的单位与源页面必须一致，否则两个门户对同一个数给出两种量纲。
     page: 点这张卡打开的 my_app 页面。三张卡同源同页，但**逐条写**而不是
     在渲染函数里写一个共用常量 —— 与 KPI_RICH.page 同一条理由
     （将来若拆到不同页面，改动只发生在这张表里）。
     ⚠️ 值必须是 my_app App.tsx 的 PageKey（见 VALID_PAGES 白名单），
     写错会被静默回落到概览页，表现为「点了却打开别的页」。 */
  var KPI_SPEED = [
    { key: 'download', kind: 'speed',   unit: 'Mbps', digits: 1, page: 'bm_speedtest' },
    { key: 'upload',   kind: 'speed',   unit: 'Mbps', digits: 1, page: 'bm_speedtest' },
    { key: 'latency',  kind: 'latency', unit: 'ms',   digits: 0, page: 'bm_speedtest' }
  ];
  /* 卡名照抄 bms.metric.* 的中文/英文写法（my_app i18n），两个门户对同一个
     指标不能有两个名字。{n} = 品牌展示名（Orange / MTN），由后端 BRAND_LABELS 给。 */
  var SPEED_ROW_LABEL = { download: 'kpi.bf.download', upload: 'kpi.bf.upload', latency: 'kpi.bf.latency' };
  /* Benchmark 行两组的品牌顺序（**两条数据源共用**，2026-09-30 由 SPEED_BRANDS 改名）：
     Ookla 那 3 张按 download/upload/latency 比两家，Meta 那 3 张按速率/评分比两家，
     顺序都是「先 ORANGE 后 MTN」—— 这不是巧合，两边都来自 my_app 各自的
     caliber.BRANDS = ("ORANGE", "MTN")。所以顺序只有一处定义，改这里两组一起跟。
     ⚠️ 若哪天两个源的品牌集不再相同（例如 meta 表多了一家），**必须**拆成两份，
     不能在这一个数组里凑一个"两边的并集"：那会让某一组的卡里多出一行没数据的品牌。 */
  var BENCH_BRANDS = ['ORANGE', 'MTN'];

  /* ---- Benchmark 行第二组：Meta 基准报告（`?page=bm_meta`）的 3 张卡（2026-09-30 加）
     ----------------------------------------------------------------------------
     数据源 /api/bm-meta/overview?start=&end=，窗口由 olbr.js 统一算
     （最近 30 天，与同排 3 张 Ookla 卡**同一档** —— 用户 2026-09-30 选定）。

     key 与接口字段的对应（字段名以 my_app `bm_meta_service.build_overview` 为准）：
       speed  → summary[brand].speed / speed_min / speed_max
       scores → scores[brand].score + wins.orange_wins / mtn_wins / paired_days
       bp     → summary.network.bp / bp_min / bp_max

     kind：'brand' 两家 PK（卡内两行 + 领先方徽章）/ 'network' 网络侧 KPI
     （单值 + 逐日区间，**不做两家比较**）。这条分界不是我定的，是口径模块定的：
     `bm_meta_caliber` 把 9 个指标分成 BRAND_METRICS 与 NETWORK_METRICS，
     后者「不属于任何一家」，混进 PK 会得到假结论 —— 所以 BP 那张卡里
     既没有品牌行，也没有徽章。

     digits：与 my_app 页面一致（速率 1 位、评分 1 位、BP 2 位）。位数不一致会让
     两个门户对同一个数给出两种精度。

     name / unit 给的是 **i18n 键**（评分单位中英不同：分 / pts），
     逐条写而不是在渲染函数里按 key 拼字符串 —— 拼键在字典里查不到时
     会静默显示键名本身，而这类错误只有切到英文界面才看得见。
     page 是 my_app App.tsx 的 PageKey（见 VALID_PAGES 白名单），
     写错会被静默回落到概览页，表现为「点了却打开别的页」。 */
  var KPI_META = [
    { key: 'speed',  kind: 'brand',   name: 'kpi.mm.speed',  unit: 'kpi.mm.unitMbps',  digits: 1, page: 'bm_meta' },
    { key: 'scores', kind: 'brand',   name: 'kpi.mm.scores', unit: 'kpi.mm.unitScore', digits: 1, page: 'bm_meta' },
    { key: 'bp',     kind: 'network', name: 'kpi.mm.bp',     unit: 'kpi.mm.unitPct',   digits: 2, page: 'bm_meta' }
  ];

  /* ---- Speedtest by Ookla 品牌标识（2026-10-01 加）-------------------------
     用户要求「新增的 3 个卡片上体现 Ookla 的图标，表明是 Speedtest」，
     并给了参考图：仪表盘标记 + SPEEDTEST 字标 + by OOKLA，摆在页脚右侧。

     几何取自参考图的实测像素（下文的坐标都按"标记外缘左上角 = (0,0)"定，
     与参考图逐项对齐，实测值 → 本 SVG）：
       · 标记   宽 38 / 高 32（外缘）→ 外半径 19、描边 4.5
       · 间距   标记右缘 → 字标左缘 11
       · 字标   SPEEDTEST 宽 124、大写高 15（基线在 y=22）
       · 副行   by OOKLA 宽 61、左缩进 13（x 62）、基线 y=41
       · 整块   173 × 44
     viewBox 用 **负原点 -0.5**：标记的外缘正好落在 x=0/y=0 上，
     不留边距的话抗锯齿会在最左/最上各削掉半像素（实测探针报"边缘有墨=被裁"）。
     -0.5 的四周留白只影响外框比例 1.7%，换来描边不被裁。

     ⚠️ **这是按参考图比例手工复刻的字体版近似，不是 Ookla 的官方矢量资产。**
     要换成官方资产：把官方 SVG 的内容替换掉本字符串即可（接口不变，
     olbr.js 的 speedCardHtml 不用动）—— 对外分发/商用前应当这么做，
     并按 Ookla 的品牌规范使用。字体复刻只保证"看起来是它"，不保证字形一致。

     为什么用内联 SVG，而不是从参考图裁一张 PNG：
       · **深浅两套主题**：本页 html.dark 一翻，卡片底色从浅青变深海军蓝。
         SVG 用 currentColor，颜色交给 CSS 令牌（--ookla-ink），两套主题自动都对；
         从截图裁的 PNG 会把参考图那份浅色底一起烤进去，深色主题下就是一块白斑。
       · PNG 进不了版本库：根 .gitignore 忽略 *.png，新加的图不会被跟踪，
         换台机器拉下来就没有这个图标（这与"忽略跟踪≠可删除"的 _fe_dist 不同，
         它是真的会丢）。内联 SVG 是纯文本，跟着 JS 一起入库。
       · SVG 在任意尺寸下都清晰，不依赖 2x 图。

     刻意**不**画 ® 上标：参考图里那两个 ® 只有 1~2px，
     而卡片实际渲染宽度约 106px（6 列栅格下每张卡 257px），
     ® 会退化成看不清的灰点、像渲染瑕疵。商标归属改为写在卡片 tooltip 里
     （kpi.bf.tipSrc）—— 那里是能读到的。

     ⚠️ SVG 本身**不带 aria-label**（只带 focusable="false"，避免被 Tab 键选中）。
     无障碍名称由外层 <span class="bf-ookla" role="img" aria-label="..."> 提供，
     见 olbr.js 的 speedCardHtml —— 放在那边是因为要用 t('kpi.bf.ooklaTip')，
     而这个文件是个纯数据模块，拿不到 i18n 的 t()。
     两处都写会把"这个标识叫什么"变成两个真相源，所以这里刻意留空。 */
  var OOKLA_LOGO =
    '<svg class="ookla-svg" viewBox="-0.5 -0.5 174 45" focusable="false">' +
      /* 圆弧：M 起点(左下 135°)，A 弧半径 16.75 = 外半径 19 − 半个描边 2.25，
         large-arc=1 + sweep=1 → 走 270° 的"长边"（经过正上方），
         缺口留在正下方 90°。圆心 (19,19) 使外缘左上角正好落在 (0,0)。 */
      '<g fill="none" stroke="currentColor" stroke-linecap="round">' +
        '<path d="M7.16 30.84A16.75 16.75 0 1 1 30.84 30.84" stroke-width="4.5"/>' +
        /* 指针：自圆心指向右上 45°，长度 10（= 参考图实测的针尖距圆心 11.67
           减去圆头半径 1.8），描边比圆环略细（参考图实测 ≈3.5 vs 4） */
        '<path d="M19 19L26.07 11.93" stroke-width="3.6"/>' +
      '</g>' +
      /* 字标。textLength 把宽度锁成参考图实测值（SPEEDTEST 124 / by OOKLA 61），
         lengthAdjust="spacing" 只调字距、不拉伸字形 —— 这样即使落在
         Segoe UI / Roboto 这类与 Ookla 自有字体不同的字体上，
         整块的**外框比例**仍与参考图一致，不会因为字体宽窄把卡片撑变形。
         ⚠️ 副行字号 13 是"不与 textLength 打架"的上限：参考图那行的大写高
         折合字号约 17，但 Segoe UI 在这个字号下自然宽 80px > 目标 61px，
         被 textLength 压回去会让字母叠在一起。取 13 时自然宽 61.5 ≈ 目标，
         字距几乎不用调 —— 宁可副行略小，也不要字母粘连。 */
      '<g fill="currentColor" stroke="none">' +
        '<text x="49" y="22" font-size="20.8" font-weight="800" ' +
          'textLength="124" lengthAdjust="spacing">SPEEDTEST</text>' +
        '<text x="62" y="41" font-size="13" textLength="61" lengthAdjust="spacing">' +
          '<tspan font-weight="500">by </tspan><tspan font-weight="700">OOKLA</tspan></text>' +
      '</g>' +
    '</svg>';

  /* ---- Meta 基准报告标识（2026-09-30 加）-----------------------------------
     用户要求「可以放到新增的两个 meta report」并给了参考图：
     圆标（蓝底 + 白 f）+ Facebook 字标，摆在页脚右侧 —— 与 Ookla 标识同一格、
     同一用意（说明这张卡的数从哪来）。字标按用户 2026-09-30 的选择写成 **Meta**
     （与门户既有徽章文案、my_app 页面名「Meta 基准报告」同名，
     读者在三个地方看到的是同一个来源名）。

     几何取自参考图的实测像素（176×60 的 PNG，逐像素量的）：
       · 圆标   直径 33（正圆）
       · 间距   圆标右缘 → 字标左缘 10
       · 字标   大写高 13、宽 85（那是 "Facebook"；本处字标是 "Meta"，
                 宽度在**本机页面字体**下实测 18px 时 43.66 → 折到 18.6px 约 45，
                 用 textLength 锁成 45，见下）
       · 基线   y=22（= 圆标顶 0 + 实测大写顶 9 + 大写高 13）
       · 整块   88 × 33
     viewBox 同样用 **负原点 -0.5**（与 OOKLA_LOGO 同一条理由：
     外缘正好落在 x=0/y=0 时抗锯齿会各削掉半像素）。

     ⚠️ **这里嵌的是 Simple Icons（CC0）的 facebook.svg 路径，不是 Meta 官方矢量资产。**
     路径是 24×24 的原始数据、原样内联，只在外层套 scale(1.375) 放大到 33，
     这样"换成官方资产"只是替换 d 的值，本文件与 olbr.js 都不用动 ——
     **对外分发/商用前应当换成官方 SVG** 并按 Meta 的品牌规范使用（与 Ookla 那段同一口径）。
     路径本身把 f **挖空**（描的是一整个圆盘轮廓，f 是其中的缺口），
     所以下面垫了一个白色圆：不垫的话 f 会露出卡片底色，
     深色主题下 f 直接变成深色、对比度掉一半。
     圆盘用 Meta 品牌蓝 #0866FF 固定值，不跟主题走 —— 它是商标的组成部分；
     字标走 currentColor（主题墨色），因为参考图那份深海军蓝在深色主题下会看不见。

     为什么用内联 SVG 而不是把参考图裁一张 PNG（与 OOKLA_LOGO 完全同一条理由）：
     PNG 进不了版本库（根 .gitignore 忽略 *.png，换台机器拉下来就丢图），
     而且参考图把浅色底烤进了像素、深色主题下会是一块白斑。

     刻意**不**画 ® 上标、**不**给 SVG 加 aria-label：
     前者在页脚实际尺寸下会退化成看不见的灰点；
     后者由外层 <span class="bf-metalogo" role="img" aria-label="..."> 提供
     （见 olbr.js 的 metaCardHtml）—— 这个文件是纯数据模块，拿不到 i18n 的 t()。 */
  var META_LOGO =
    '<svg class="meta-svg" viewBox="-0.5 -0.5 89 34" focusable="false">' +
      '<g transform="scale(1.375)">' +
        /* 白底圆：被上面的路径完整覆盖，只在 f 的缺口处露出来（见文件头的说明）。 */
        '<circle cx="12" cy="12" r="12" fill="#fff"/>' +
        '<path fill="#0866FF" d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"/>' +
      '</g>' +
      /* 字标。字号 18.6 是"大写高 = 参考图实测的 13"反推的
         （Segoe UI Bold 的大写高约 0.70em），textLength 锁成本机实测自然宽 45：
         lengthAdjust="spacing" 只调字距、不拉伸字形，
         换台字体不同的机器时整块外框比例不变、字母也不会粘连。 */
      '<text x="43" y="22" font-size="18.6" font-weight="700" textLength="45" ' +
        'lengthAdjust="spacing" fill="currentColor">Meta</text>' +
    '</svg>';

  return {
    S: S, PH: PH,
    T0: T0, T1: T1, T2: T2, AUX_ROWS: AUX_ROWS, OTHER: OTHER, ARCHIVE: ARCHIVE, AUX_TITLES: AUX_TITLES,
    MAP_TABS: MAP_TABS, RENAME_HEAD: RENAME_HEAD, RENAME_KEYS: RENAME_KEYS,
    EMAIL_PAGE: EMAIL_PAGE, EMAIL_TAB: EMAIL_TAB, MAP_STRIP_CSS: MAP_STRIP_CSS,
    QC_TARGETS: QC_TARGETS, QC_PRIMARY_ORDER: QC_PRIMARY_ORDER, QC_SECONDARY_ORDER: QC_SECONDARY_ORDER,
    QC_TREND_METRICS: QC_TREND_METRICS, QC_SUB_KEY: QC_SUB_KEY, QC_LV_KEY: QC_LV_KEY,
    QC_FULL_MIN: QC_FULL_MIN, QC_FULL_OFFSET: QC_FULL_OFFSET,
    QC_ALARM_MIN: QC_ALARM_MIN, QC_ALARM_OFFSET: QC_ALARM_OFFSET,
    KPI_RICH: KPI_RICH, KPI_AVAIL_ROWS: KPI_AVAIL_ROWS,
    KPI_SPEED: KPI_SPEED, SPEED_ROW_LABEL: SPEED_ROW_LABEL, BENCH_BRANDS: BENCH_BRANDS,
    KPI_META: KPI_META,
    OOKLA_LOGO: OOKLA_LOGO, META_LOGO: META_LOGO
  };
})();
