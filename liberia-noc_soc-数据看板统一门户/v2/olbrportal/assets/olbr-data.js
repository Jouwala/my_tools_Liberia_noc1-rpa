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
      'map.gis': '全球地图', 'map.mw': '微波实时', 'map.alarm': '实时告警', 'map.loss': '传输丢包',
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
      'edit.itemDrop': '移出本列', 'edit.itemDropTip': '只是把这张看板从当前分组移出，看板本身还在（可再用「分组」勾回来）',
      'edit.itemDel': '删除看板', 'edit.itemDelTip': '从共享目录里彻底删除这张看板，所有人刷新后都不再看到，无法撤销',
      'edit.itemDropped': '已从本分组移出', 'edit.itemDeleted': '看板已删除',
      'edit.itemLastGrp': '这是它唯一的分组，移出后就没地方放了 —— 真要移除请用「删除看板」',
      'edit.itemDelConfirm': '彻底删除看板「{n}」？\n\n它会从共享目录里移除，/olbrportal/ 与 MsPortal 也不再显示，所有人刷新后都会少这一条。\n此操作无法撤销。',
      /* 新增看板：先选一个现有看板当模板，再改名字与链接。
         模板值继承图标 / 平台 / 描述 / 负责人等，避免每次从零填十几个字段。 */
      'edit.itemAdd': '新增看板', 'edit.itemAddTip': '照着一个已有看板新建一张（图标 / 平台 / 描述等沿用模板，只改名字与链接）',
      'edit.itemAddPick': '先选一个已有看板当模板（可搜索）',
      'edit.itemAddSearch': '搜索看板名…',
      'edit.itemAddBack': '换一个模板',
      'edit.itemAdded': '看板已新增',
      'edit.itemNeedUrl': '先填链接（http:// 或 https:// 开头）',
      'edit.itemBadUrl': '链接要以 http:// 或 https:// 开头',
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
      'foot.branch': '利比里亚办事处网络运营中心 (OLR MS)', 'foot.ok': '安全合规模式运行',
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
      'map.gis': 'Global Map', 'map.mw': 'MW real-time', 'map.alarm': 'Live alarms', 'map.loss': 'Packet loss',
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
      'edit.itemDrop': 'Remove from column', 'edit.itemDropTip': 'Only takes this dashboard out of the current group; the dashboard itself stays (re-tick it under "Groups")',
      'edit.itemDel': 'Delete dashboard', 'edit.itemDelTip': 'Removes this dashboard from the shared catalog for everyone; cannot be undone',
      'edit.itemDropped': 'Removed from this group', 'edit.itemDeleted': 'Dashboard deleted',
      'edit.itemLastGrp': 'This is its only group, so removing it would leave the dashboard nowhere to live — use "Delete dashboard" if you really want it gone',
      'edit.itemDelConfirm': 'Permanently delete the dashboard “{n}”?\n\nIt will be removed from the shared catalog, so /olbrportal/ and MsPortal will stop showing it and everyone loses this entry on refresh.\nThis cannot be undone.',
      'edit.itemAdd': 'New dashboard', 'edit.itemAddTip': 'Create a dashboard from an existing one (icon / platform / description are inherited; you only set the name and link)',
      'edit.itemAddPick': 'Pick an existing dashboard as the template (searchable)',
      'edit.itemAddSearch': 'Search dashboard names…',
      'edit.itemAddBack': 'Change template',
      'edit.itemAdded': 'Dashboard added',
      'edit.itemNeedUrl': 'Enter a link first',
      'edit.itemBadUrl': 'The link must start with http:// or https://',
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
      'kpi.tipAvail': 'Source: Daily Availability KPI (Availability-NW sheet) aggregated by Cell Group, same definition as {board}',
      'kpi.tipAvailFoot': 'The big number is the month-to-date average; the footer shows yesterday, the target threshold, and yesterday minus the target (pp = percentage points; negative means yesterday was below target).',
      'kpi.availTrendCap': 'Last {n} days',
      'kpi.availTrendTip': 'Daily Cell Availability over the last {n} days (1 day per slot).\n'
                         + 'Same response as the big number and the footer, so the end of the line IS the "yesterday" slot.\n'
                         + 'The vertical axis covers only this window\'s own range and does NOT start at 0 —\n'
                         + 'availability sits at 97-99%, so a zero-based axis would flatten every movement into a straight line.\n'
                         + 'Use the footer\'s "gap to target" to judge compliance; this line is only for the trend.',
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
      'foot.branch': 'Liberia Office · Network Operation Center (OLR MS)', 'foot.ok': 'Compliance mode',
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
  var AUX_TITLES = {
    'Knowledge Q&A': 'aux.qa', 'Friends Link': 'aux.friends', 'System Admin': 'aux.admin'
  };
  /* 2026-09-25 按需求删掉 realtime_alarm 与 packet_loss 两个页签 —— 本栏只保留
     「GIS 地图」与「微波实时」，与 MsPortal 侧保持一致（那边同日同样删了两个）。
     后端 TAB_PAGES 白名单里这两个 page 值**刻意保留**：服务端已存过的 tabLabels
     改名记录不会因为白名单收窄而被丢弃，将来若要恢复页签不用重新改名。 */
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
    'main#main-content .ant-card-body:has(.leaflet-container) > *:not(.leaflet-container):not(:has(.leaflet-container)){position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:900!important;background:rgba(255,255,255,.88)!important;margin:0!important;padding:2px 8px!important}',
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
  var KPI_RICH = [
    { id: 'traffic_gb',     unit: 'TB',   digits: 2, div: 1024,
      zh: '总流量',           en: 'Total Traffic' },
    { id: 'active_user_k',  unit: 'K',    digits: 1, div: 1,
      zh: '活跃用户',         en: 'Active Users' },
    { id: 'video_thr_kbps', unit: 'Mbps', digits: 2, div: 1000,
      zh: '视频下载速率',     en: 'Valid Throughput of Video Download' }
    /* 2026-09-24：曾加过第四张 video_tb（视频流量，与源看板截图一致），
       用户随后要求去掉、恢复六张卡一行 —— 故此处只有三张。
       要恢复只需把 { id: 'video_tb', unit: 'TB', digits: 1, div: 1,
       zh: '视频流量', en: 'Video Traffic' } 加回来，
       并把 .qc-grid 的列数从 6 改回 4。 */
  ];
  /* 2G / 3G / 4G 分别对应 xlsx 里的哪个 Cell Group。写成显式映射而不是
     startsWith('2G') 去猜：源表以后加了 "2G ERA" 之类的档位时，
     前缀匹配会悄悄命中错的那一行，而这张卡上一个错的可用率没人能一眼看出来。 */
  var KPI_AVAIL_ROWS = [
    { key: '2G', group: '2G ALL' },
    { key: '3G', group: '3G ALL' },
    { key: '4G', group: 'FDD ALL' }
  ];

  return {
    S: S, PH: PH,
    T0: T0, T1: T1, T2: T2, AUX_ROWS: AUX_ROWS, OTHER: OTHER, AUX_TITLES: AUX_TITLES,
    MAP_TABS: MAP_TABS, RENAME_HEAD: RENAME_HEAD, RENAME_KEYS: RENAME_KEYS,
    EMAIL_PAGE: EMAIL_PAGE, EMAIL_TAB: EMAIL_TAB, MAP_STRIP_CSS: MAP_STRIP_CSS,
    QC_TARGETS: QC_TARGETS, QC_PRIMARY_ORDER: QC_PRIMARY_ORDER, QC_SECONDARY_ORDER: QC_SECONDARY_ORDER,
    QC_TREND_METRICS: QC_TREND_METRICS, QC_SUB_KEY: QC_SUB_KEY, QC_LV_KEY: QC_LV_KEY,
    QC_FULL_MIN: QC_FULL_MIN, QC_FULL_OFFSET: QC_FULL_OFFSET,
    QC_ALARM_MIN: QC_ALARM_MIN, QC_ALARM_OFFSET: QC_ALARM_OFFSET,
    KPI_RICH: KPI_RICH, KPI_AVAIL_ROWS: KPI_AVAIL_ROWS
  };
})();
