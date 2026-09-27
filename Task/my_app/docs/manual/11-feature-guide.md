# 11 功能页使用手册

按左侧菜单从上到下的顺序编号（菜单定义 `frontend/src/App.tsx:182-206`）。每个页面可用 `?page=<key>` 直接打开，例如 `http://localhost:7090/myapp/?page=battery`。

**先记住两件事**

- 有 **7 个页面是 iframe 壳**（下表标注「iframe」），真正界面在 `frontend/public/*.html` 里，React 只负责加载与注入语言。这类页面样式/交互和 React 页不一致，改了 React 代码不会影响它们。
- 只有「任务管理」有常驻轮询（60s 刷列表 + 30s 时基，`pages/DataSync.tsx:165,173`）。其他页面的"自动刷新"来自**顶栏全局设置**（默认 300 秒，可改 0/30/60/300/600/900/1800）。看板数据看起来不动，先看顶栏刷新间隔。

| # | 菜单 | key | 形态 |
| --- | --- | --- | --- |
| 1 | 任务管理 / Task Manager | `sync` | React |
| 2 | 任务报告文件 / Task Report Files | `email_reports` | React |
| 3 | 实时告警看板 / Alarm Dashboard | `alarm` | React |
| 4 | TT&WO 看板 | `ttwo` | React |
| 4b | TT&WO 看板（v1·仅上半部分） | `v1_ttwo` | React（同组件切片） |
| 5 | NUR 看板 | `nur` | React |
| 6 | MS Operation KPI 看板 | `ms_sla` | React |
| 7 | CXO 经营看板 | `cxoDashboard` | **iframe** |
| 8 | MW 微波拓扑 | `mwUmeTopology` | **iframe** |
| 9 | MW 微波实时 | `mwRealTime` | **iframe** |
| 10 | GIS 地图 | `gis` | React |
| 11 | 实时告警地图 | `realtime_alarm` | React（同组件另一模式） |
| 12 | 告警管理看板 | `alarmManagement` | **iframe** |
| 13 | 丢包看板 | `packet_loss` | React |
| 14 | 电池看板 | `battery` | React |
| 15 | IP 链路探测 | `ip_trace` | **iframe** |
| 16 | 事件总览 | `incident_overview` | **iframe** |
| 17 | 仓库看板 | `warehouse` | **iframe** |
| 18 | 数据总览 | `overview` | React |
| 19 | 表浏览器 | `tables` | React |
| 20 | 数据上传 | `upload` | React |
| 21 | 分析归档 | `archive` | React |
| 22 | 分析仪表盘 | `dashboard` | React |
| 23 | 系统设置 | `settings` | React（4 页签） |
| 24 | 门户一键登录 | `portalLogin` | React |

---

## 1. 任务管理（`?page=sync`）— 全站控制中心

看所有定时任务的状态、手动执行、改排程、查历史。**遇到"数据没更新"，第一个该打开的页面就是这里。**

- **筛选**：关键字搜索 + 状态 / 分类 / 排序（`DataSync.tsx:841-875`）。
- **统计卡**：点击卡片即为筛选条件（运行中/成功/失败…）。
- **单任务操作**：`执行`(:231)、`停止`(:266)、`启用/停用`(:285)、`历史`(:296)、`排程`（弹窗改 cron，:961）。改排程写入 `task_schedule_config`，重启不丢。
- **批量**：`一键全部启用/停用`（:745 → `POST /api/tasks/toggle-all`）。
- **失败聚合**：按天汇总失败任务（:181 → `GET /api/tasks/failures?days=`），排查"昨晚是不是又挂了"用这个而不是翻列表。
- **全局历史**：跨任务执行记录（:978，组件 `pages/datasync/GlobalHistoryModal.tsx:85`）；单任务历史 `TaskHistoryModal.tsx:31`。
- **语音播报**：开关在 :806，任务完成时播报。
- 接口：`GET /api/tasks`、`POST /api/tasks/{id}/run|stop|toggle|schedule`、`GET /api/tasks/{id}`、`GET /api/tasks/failures`。

⚠️ 常见误判：任务列表里长期 `pending` 不动，多半是该任务**没被归入任何 worker 组**（`04-task-system.md` 有事故先例），不是"还没到点"。

## 2. 任务报告文件（`?page=email_reports`）

取回三类产物并下载：**邮件附件**、**FineBI 报表**、**eFlow TT 规则检查结果**。

- 三页签切换（`EmailReports.tsx:331`）；可设「保留最近 N 份」（:348）。
- 各页独立刷新按钮（:350 / :377 / :407）；行内下载（:231 / :277 / 表格内「下载」列）。
- eFlow 规则页有**三个手动触发按钮**（:463/:471/:479），点击后 3 秒做一次刷新（:157，**不是轮询**，任务慢时得手动再点刷新）：
  | 按钮 | 触发任务 | 端点 |
  | --- | --- | --- |
  | 立即检查 | `eflow_tt_rules_check`（拉 TT 规则 + 匹配矫正） | `POST /api/tasks/eflow_tt_rules_check/run` |
  | 收集告警规则 | `eflow_alarm_rules_collect` | `POST /api/tasks/eflow_alarm_rules_collect/run` |
  | 收集推单规则 | `eflow_push_rules_collect` | `POST /api/tasks/eflow_push_rules_collect/run` |

  后两个任务原本只在**每 3 天 23:59** 跑，页面上等不到最新规则，故补手动入口（三个按钮各自独立 loading，由 `eflowRunningTask` 记录当前触发的 task_id）。
- **eFlow 规则页底部列出「从 eFlow 获取的全部规则表」**（2026-09-23 新增）：TT 级别矫正规则 `eflow_TT_rules.xlsx`、告警关联规则 `eflow_alarm_rules*.xlsx`、推单/配置规则 `eflow_push_rules*.xlsx`，外加本次检查产物（级别矫正表 / 匹配报告）。此前只暴露 TT 规则表，另外两份规则收集任务的产物在界面上**无处可下**。
  - 文件清单由 `backend/routers/email_reports.py` 的 `_EFLOW_FILE_SPECS` 定义（`kind=rule|report` + 中英展示名），排序为「规则表在前（TT → 告警 → 推单）、检查产物在后」。
  - ⚠ `_EFLOW_FILE_SPECS` 的 pattern 必须与 `_SOURCES` 中 `eflow_tt_rules_check` 源的 `patterns` 一致 —— 下载接口 `_resolve_download_file` 按 `patterns` 做白名单校验，只改一处会出现「列得出来、点下载 403」。
- 接口：`GET /api/email-reports/latest`、`GET /api/finebi-reports/latest`、`GET /api/email-reports/eflow_tt_rules_check`、下载 `GET /api/.../download/{source}/{file}`。
- **导出 Excel**（2026-09-27 新增）：**每个页签各一个导出按钮**，导的是该页签表格当前的全量行
  （这些表 `pagination={false}`，无分页截断）——
  - 邮件报表 `exportEmail` → `EmailReports_*.xlsx`（任务/类型/文件/大小/时间，不含「下载」操作列）；
  - FineBI 报表 `exportFinebi` → `finebi_reports_*.xlsx`（文件夹/文件/大小/时间）；
  - eFlow 规则检查 `exportEflowCheck` → `eflow_tt_rules_check_*.xlsx`，多 sheet：`Summary`（统计卡 + 变更方向）、
    `Rules`（规则明细，变更列走数值着色）、`Files`（可下载产物清单）。

## 3. 实时告警看板（`?page=alarm`）

全网当前告警的综合视图，深空蓝底 + 数字可下钻（`AlarmDashboard.tsx:1-2`）。

- 概览指标 `GET /api/alarm-dashboard/overview`（经 `cache.ts` 缓存，:133）。
- **点任意数字弹出下钻表**（`DraggableClickModal`），历史口径走 `/history-drilldown?metric=&limit=500`，实时口径走 `/realtime-drilldown?dimension=&value=&limit=500`（:158-163）。下钻表可搜索。
- **页面级导出 Excel**（2026-09-27 新增）：导出当前页显示的全部汇总维度。此前本页唯一的导出按钮在下钻弹窗内（导下钻明细行），页面上没有导出入口。
- 与其他看板不同：这里的"实时"来自 `eflow_active_alarm`（每 30 分钟）写入的数据，**不是秒级推送**。

## 4. TT&WO 看板（`?page=ttwo`）

故障工单（TT）与工作单（WO）的处理量、时效、积压趋势。

- 筛选：下拉 + `Segmented` + 日期区间（`TTWODashboard.tsx` 引入 Select/Segmented/DatePicker）。**默认时间窗是「近 30 天」**（`timePreset` 初值 `last30`）：7 天对周/月粒度只剩 1~2 个桶，看不出趋势，30 天在日/周/月三档分别约 30 / 5 / 2 个点。
- **归属过滤 ZTE / 3rd**（2026-09-26 新增）：`owner=zte` → `wo_no` 非空；`owner=3rd` → `wo_no` 为空。口径由后端 `_owner_where()` 单点定义，overview 与 drilldown 共用（`tt_wo_dashboard.py`），因此筛出来的数字与下钻行数严格相等。
- **高级过滤**（2026-09-26 新增，参照 `GISMap` 的「高级筛选」）：`adv` 参数传 JSON 对象 `{站点列名: 精确值}`，作用于站点表 JOIN 上的**精确匹配**（不用 LIKE）。可选列由后端按**真实表结构**白名单给出（`_detect_schema()` 的 `site_filter_fields`），候选值经 `filters.filter_options` 下发，前端不硬编码列名 —— 换库（my_app / MTN_Comsal）时下拉自动跟着变。非白名单列一律丢弃（列名不来自请求输入，值走占位符），无注入面。
- 接口：`GET /api/tt-wo-dashboard/overview`（缓存，:125）、`GET /api/tt-wo-dashboard/drilldown`（:156）。两个端点都接受 `time_start/time_end/region/owner/adv`，**过滤口径必须逐条一致**。
- 页头显示"最近同步/是否已同步"（`useDataTimestamps`，:16,77）。
- 数据来自 `eflow_sync`（每小时 :22）与每日全量兜底 `eflow_sync_full`（01:00）。
- **TT 统计不含 Alarm Severity**（2026-09-26 按业务要求移除）：该维度与 Ticket Severity 高度重复。`tt_stats.alarm_severity` / `category` 后端仍返回（其他页面与下钻维度在用），只是本页不再渲染。
- **TT 统计三个维度（工单严重度 / SLA 状态 / 工单状态）全部用数字卡片**（2026-09-27 改）：每取值一张卡（左色条 + 名称 + 大数字 + 占比），点卡下钻。三者共用同一个渲染器 `renderStatCards()`，只是换色表与下钻维度；卡片走项目统一组件 `CardBase`（AGENTS.md 第三节第 3 条），宽度按取值个数自适应（`span = max(4, 24/取值数)`，4~5 个取值一行铺满）。分组用「维度小标题 + 卡片网格」(`StatDimTitle`)，**不是**大卡套小卡 —— 嵌套卡片层级会糊、两层边框压掉内边距。改卡片前的 Tag 胶囊块在高密度取值下会换行成一团、数字不突出。
  - 占比分母是该维度**自身**的合计（看单维度内部构成），不是 TT 总数。
  - 取不到值显示 `—` 而非 `0`（`fmt()` 本身对 null 返回 `'0'`，卡片里显式挡掉）。
- **MTTR 趋势：柱 = TT 数量 + 线 = MTTR，左右双轴**（2026-09-27 改），并按 Ticket Severity 拆成 4 张图（P1/P2/P3/P4），**用页签切 日 / 周 / 月 三档粒度**。数据来自 `mttr_series[粒度][级别]`，每项三个字段语义必须分清：
  - `total` = 该桶该级别的**全部 TT 单数**（柱状图画的就是它），只要能定位到桶就计，**不论能否算出 MTTR**。所以柱子等于「那个时段那个级别有多少单」，与下钻行数对得上（实测 15 个抽样桶 × 3 粒度全部相等）。
  - `count` = 其中**真正计入 MTTR 均值**的单数（`0<dur<43200`）。`total - count` 的差额就是缺关单时间或时长越界的单；`total ≠ count` 时 tooltip 用 `ttwo.mttrSampleNote` 把差额说明白（实测全库差额仅 3 条：P3×2、P4×1，且这 3 条的 `alarm_occur_time` 为 NULL —— 落不到任何时间轴，属固有不可归属，非丢数）。
  - `mttr` = `count` 这批单的时长均值；`count=0` 时为 `None`（柱在、线断），**不是 0**。
  - 桶取 `total` 与 `count` 的**并集**：只有单数、没有有效时长的桶也出点，柱照画、线断开 —— 否则会凭空丢掉「有单但算不出时长」的时段。
  - **三档一次请求全拿到**（overview 一次返回），切页签是纯前端切换、不重新请求。
  - 口径与整页 `mttr_weekly` 完全一致（同一时间字段、同一 `0<dur<43200` 剔除），只是额外按 `级别 × 粒度` 分桶；三档都走后端 `_period_label()` 同一个解析入口，所以**周上的 total = 该周 7 个日点的 total 之和**（实测 178 个「周×级别」组合，0 处不一致）。
  - **某桶该级别没有单时不画柱也不画点（`connectNulls:false` 断线），不补 0** —— 「没有单」与「MTTR 为 0」是两回事，补零会把曲线压到地上误导值班判断。`ticket_severity` 为空的单不进任何级别序列。
  - 四图共用一条 x 轴（该粒度下各级别的桶并集），并加入同一个 echarts group（`MTTR_CHART_GROUP`），**tooltip 与 dataZoom 联动**。
  - 柱用中性色（成交量是中性的量，级别身份交给 MTTR 折线表达），深浅主题各一套实值 —— ECharts canvas 解析不了 `WH.*` 这类 CSS 变量。
  - 日粒度在「全部时间」下近 300 个点（实测 298 桶），超过 60 点时自动开启缩放（滚轮 + 底部滑杆）与标签抽稀（`hideOverlap`），并隐藏点上 symbol。
  - **点图上任意点可下钻**：维度即当前页签的粒度（`day` / `week` / `month`），drilldown 的 `dimension` 判定已同步支持这三种（`tt_wo_dashboard.py` 的 `_MTTR_GRANULARITIES`），与 overview 同源同桶。
  - **兼容是追加式的**：`mttr_weekly` / `mttr_weekly_by_severity` 原样保留（后者由 `mttr_series["week"]` 改名派生、连 `total` 一起带，不会分叉），老前端仍可用。前端若遇到未返回 `mttr_series` 的旧后端，日/月页签会明确提示「该粒度数据暂不可用」而**不是**假的「无工单」空态；老后端无 `total` 时柱退回用 `count` 画。


### 4b. TT&WO 看板 v1（`?page=v1_ttwo`）—— 只保留上半部分

`TTWODashboard.tsx` 的**切片直链页**，壳是 `pages/V1TTWODashboard.tsx`（`<TTWODashboard only="summary" />`）。

- **出什么**：汇总卡（TT 总数 / WO 总数 / WO 编号唯一）→ TT 统计（工单严重度 / SLA 状态 / 工单状态，**三者都是数字卡片网格**）→ **MTTR 趋势（含 `SectionTitle` 标题、日/周/月页签，每个粒度下四张「柱=TT 数量 + 线=MTTR」双轴分级图）**。默认时间窗近 30 天。
- **不出什么**：「MTTR 趋势」标题之下的三个区块整体不渲染 —— 领域与根因分析（按领域统计 TT / 根因主 / 根因子）、工单分析（按来源统计 WO / 按状态统计 WO）、站点信息（Power Sources / Power Vendor / Maintenance Team / Site Class）。切片开关见 `TTWODashboard.tsx` 的 `summaryOnly`，包裹位置在「Domain + Root Cause」`SectionTitle` 之前。
- **与 `page=ttwo` 的关系**：**不是复制实现，是同一份实现的切片**（先例：`MsNurOnly.tsx` / `MsSlaOnly.tsx` 之于 `NurDashboard.tsx`）。筛选条、下钻弹窗、Excel 导出、主题取色、卡片渲染器、MTTR 三档粒度与双轴图全部共用，且两页调同一个 `GET /api/tt-wo-dashboard/overview`，所以**数字必然一致**，上游改口径时两页同步生效。
- 下钻端点 `GET /api/tt-wo-dashboard/drilldown` 与 `page=ttwo` 完全相同；MTTR 图上的点仍可点击下钻，维度随当前页签（`onChartClick(gran)`）。
- **页面级导出 Excel**（`exportOverview`，2026-09-27 新增）：筛选条上「高级过滤」右侧的导出按钮。
  ⚠ **此前两页在页面上都看不到导出按钮** —— `TTWODashboard.tsx` 唯一的导出按钮在**下钻弹窗内部**（导的是下钻明细行），并非页面级入口；`only="summary"` 的切片开关只管区块渲染，不生成任何按钮。本节曾把它记作"Excel 导出全部共用"，是**误记**，2026-09-27 已纠正。
  导出内容为**当前筛选条件下的全部汇总数据**（同一次 `/overview` 响应，不另发请求），按 `summaryOnly` 决定 sheet 范围，保证「导出内容 = 页面所见」：
  | sheet | 内容 | v1_ttwo |
  | --- | --- | --- |
  | `Summary` | TT 总数 / WO 总数 / WO 编号唯一 | ✅ |
  | `TT Stats` | 严重度 / 工单严重度 / SLA 状态 / 状态 四维摊平 | ✅ |
  | `MTTR` | 日/周/月三档 × P1~P4，列：粒度·级别 / 时段 / 单量 / MTTR | ✅ |
  | `WO Stats` | 按来源、按状态 | ❌（切片不渲染该区块） |
  | `Domain-RootCause` | 按领域 / 根因主 / 根因子 | ❌ |
  | `Site Stats` | Power Sources / Power Vendor / Maintenance Team 等 | ❌ |
  空块自动跳过；MTTR 某桶无单时导出空单元格而非 `0`，与页面「断点 ≠ MTTR=0」口径一致。副标题写明时间窗、区域、归属与高级过滤条件数。
- **筛选条常驻**：直链（`?page=` 进入的 bare 模式，无侧栏/Header）下，筛选条卡片一度只剩 2px —— 页面根 `pageWrap` 是纵向 flex 容器，筛选条作为第一个子项被 flex 压缩到边框最小值，`Card` 的 `overflow:hidden` 把内容全裁掉，表现为"最上面那行整个不见了，怎么滚都没有"。修法是在 `theme.ts` 的 `controlCardStyle` 加 `flex-shrink:0`（`ttwo` / `v1_ttwo` 及 `GISMap` / `Dashboard` / `DataSync` / `TableBrowser` 共用），`AlarmDashboard.tsx` 的同类横幅单独加。成因、自查条件与已验证结论见 `component-api.md` 第二节「三个已踩过的坑」③。

## 5. NUR 看板（`?page=nur`）

网络不可用率（NUR）的日/周/月趋势与站点达标情况。口径见 `01-overview.md` 术语表。

- 粒度切换 `daily|weekly|monthly`（`NurDashboard.tsx:29-30`）、日期区间、多维下拉（`GET /api/nur/options`，:421）。
- 主数据 `GET /api/nur/overview`（:411）；点数字下钻明细表 `GET /api/nur/detail`（:448），下钻表带列内筛选与排序（`strSorter`/`getUniqueFilters`，:17-27）。
- **导出**：分两级，别混淆 ——
  - **下钻弹窗内**：导出当前下钻明细行（`exportToExcel`）；
  - **页面级**（2026-09-27 新增）：导出当前筛选下的全部汇总数据。
  > 本节曾把弹窗内那个按钮记作本页的「导出」，读起来像是页面上有导出入口，**实为误记**（同 `page=ttwo` 的问题），2026-09-27 已纠正。
  - **页面级**（2026-09-27 新增）：筛选条末尾的导出按钮，多 sheet（`汇总` + `KPI List NUR/SLA` 日/周/月各一档）。
    导出当前 Vendor / Project / Exclude / 时间范围筛选后的汇总卡与三档 NUR+SLA；四项筛选条件写进每个 sheet 的 `subtitle`（含各档粒度与 NUR 量纲说明）。
    **派生页 `?page=ms_nur_only`（`MsNurOnly.tsx`）自动获得该按钮**（同上，参数化复用 + 顶部工具栏）。
- 表格与趋势图复用同一套"项目统一下钻规范"，与 TT&WO / MS SLA 三页保持一致。

## 6. MS Operation KPI 看板（`?page=ms_sla`）

MS 合同 KPI（Contract KPIs）与工单 SLA（WOs SLA）达成情况。

- 一次请求拿全部：`getMsSlaOverview()` → `GET /api/ms-sla-dashboard/overview`（`frontend/src/api.ts:17-18`），返回 NUR / SLA / Network KPI / Per-Site / WO SLA + 数据新鲜度 meta（`backend/routers/ms_sla_dashboard.py:7-8`）。
- 粒度只有 `daily|monthly`（`MsSlaDashboard.tsx:29`）；返回结构是"**指标为行、期间为列**"，与 NUR 页的表格对齐（`ms_sla_dashboard.py:10-11`）。
- 下钻复用 `GET /api/nur/detail`（:447）。
- **页面级导出 Excel**（2026-09-27 新增）：筛选条刷新按钮右侧，多 sheet（`Overview` 粒度/同步时间、
  `Value Scale` 各表量纲、`KPI List NUR`/`KPI List SLA`/`Network KPIs`/`Per-Site KPIs`、`WOs SLA` 多层合并表头）。
  导出当前粒度与时间范围下的全期值，筛选条件写进每个 sheet 的 `subtitle`；空块自动跳过。
  **派生页 `?page=ms_sla_only`（`MsSlaOnly.tsx`）自动获得该按钮** —— 它是 `<MsSlaDashboard only="sla" />` 的参数化复用，
  按钮在顶部工具栏 Card 内（不受 `showNur`/`showSla` 条件包裹），导出内容则按切片用 `showSla` 守卫收敛。
- **口径提示**：2026-08 起 NUR/SLA/WO 以 `nur_calc` 实时计算为准（`ms_sla_dashboard.py:13-14`），所以本页数字与 `data/ms_sla/ms_sla_dashboard.sqlite3` 里的快照**可能对不上**，以本页为准。

## 7. CXO 经营看板（`?page=cxoDashboard`）— iframe

Service / Network / Summary / Healthscore 四视图经营看板（`CxoDashboard.tsx`）。

- 壳：`LegacyToolFrame` 载入 `public/cxo_dashboard.html`。
- **数据三层叠加**（2026-09-02 起）：
  1. HTML 内嵌快照（构建时冻结，保底渲染）；
  2. **last-known-good 缓存**：worker 任务 `cxo_dashboard_cache_sync`（每 10 分钟，v 组）经本机 8790 VMAX 代理拉全量接口、**空值保留旧值**，落盘 `data/cxo_dashboard/last_known_good.json`，页面打开/每 5 分钟自动刷新时经 `GET /api/cxo-dashboard/cache` 应用；
  3. 实时拉取（经 `/api/realtime-proxy/cxo` 转发 8790 代理）成功则覆盖缓存。
  实时不可用时页面显示最近可用缓存数据（状态行 `offline · cached data`），Health 页 live 为空时回退缓存并在标题标注 `cached <时间>`。
- 缓存任务详情见 `backend/services/cxo_dashboard_cache.md`；每次运行还向 `data/cxo_dashboard/history.jsonl` 追加一行 Summary KPI + Health 概要（积累趋势用）。
- **轮播（大屏值守）**：页头 `Carousel` 按钮（2026-09-02 起）每 15 秒轮换 Service→Network→Summary→Healthscore 四页签并**进入全屏**（同 Alarm Management：再点按钮停止并退全屏；Esc 退出全屏会联动停轮播；手动点页签视为接管、停轮播但保留全屏）。
- 图表尺寸自适应：所有图表 setOption 后统一排队一次 rAF `resize()`（`queueResizeAll`）——trend-grid 卡片逐个 append 时列宽多次回流，不补偿会把 1570px 画布塞进 359px 卡片（x 轴标签挤压、线条重叠的根因）；实时刷新按代次（`REFRESH_GEN`）管理，切页/轮播后旧刷新静默作废，不在隐藏视图上重建图表、也不覆盖状态行。
- 数据源是 VMAX 实时保障看板，凭据在「系统设置 → 凭据 → `vmax_cxo`」。
- 已知限制：Healthscore 的 VMAX 源头分区 `aggr_ds_cxo_score` 为空时综合分显示 `—`（页面有说明横幅），需数据侧聚合后才能填充，缓存只能保证"有过的数据不再丢"。

## 8. MW 微波拓扑（`?page=mwUmeTopology`）— iframe

ZXMW 微波网络拓扑与带宽利用率 NOC 看板（`MwUmeDashboard.tsx:4-8`）。

- 壳载入 `public/mw_ume_topology.html`（:17）。
- 数据来自 `GET /api/mw-ume/topology`，底层表 `mw_ume_bw_ultilazation` 由 `mw_ume_kpi_sync` **每天 05:15** 写入（`backend/services/mw_ume/mw_ume_topology.py`）。所以本页一天只变一次，早上看到的还是昨天的数。

## 9. MW 微波实时（`?page=mwRealTime`）— iframe

与第 8 页同构的 15 分钟粒度实时版（`MwRealTimeDashboard.tsx`）。

- 壳载入 `public/mw_real_time.html`；页面默认 900 秒自动刷新，且支持软刷新（不重载 iframe）。
- 数据来自 `GET /api/mw-ume/realtime`，底层表 `mw_ume_bw_ultilazation_rt` 由 `mw_ume_kpi_sync_rt` **每 15 分钟**（`*/15 * * * *`）写入：取最近 2 小时、`gr=900` 的 FINBI 数据，看板默认只展示**最新一个 15 分钟槽位**，滑杆可回看窗口内的历史槽位。
- 与日粒度页的区别仅此而已：拓扑骨架、风险榜、抽屉、趋势图逻辑完全一致。

## 10 / 11. GIS 地图 与 实时告警地图（`?page=gis` / `?page=realtime_alarm`）

同一个组件 `<GISMap/>` 的两种模式（`App.tsx:286-289`），实时模式传 `mode="realtime"`。站点在地图上的告警/工单分布与下钻。

- **区域**下拉（`GISMap.tsx:431`）、**边界三选一** `Segmented`（不显示 / 大区 / 县界，**默认县界**；:467）、**图层 Tag** 点击开关、**图例点击隐藏**该类图层、MW 链路 `Switch`（:460，**默认开**）、时间 `Segmented` + 自定义区间、高级筛选与清除。

**默认视图（2026-09-25 起）：`?page=gis` 打开时只显示「实时告警 + MW 链路」。**

| | 默认状态 | 说明 |
| --- | --- | --- |
| 实时告警 `rt_alarm` | **开** | 唯一默认开启的站点图层（实测 38 站） |
| MW 链路 `showTopology` | **开** | 默认拉取并绘制 844 条 `kml_mw_links` 链路 |
| 普通站点 `normal` | **隐藏** | 「无任何告警/工单」的站点（实测 739 站），数量最多，默认铺满会把告警站淹没 |
| VIP `vip` | 显示 | 50 站。**刻意保留**：VIP 是重要站点，即使当前无告警也需可见 |
| 历史告警 / TT / WO | 关 | 用户点击图层 Tag 自行打开 |
| 边界蒙层 | 县界 | 沿用上一版默认 |

- **默认实际绘制 88 站**（38 实时告警 + 50 VIP）＋ 844 条链路，而非全量 827 站。
- 两套控制机制并存，别混淆：**图层 Tag** 控 `activeLayers`（历史告警/TT/WO），**图例点击**控 `hiddenLegends`（normal/VIP）。`normal` 走的是后者，初值 `new Set(['normal'])`（`GISMap.tsx:75`），所以图例上它以删除线+「已隐藏」呈现，用户**点一下即可恢复**——这是刻意的，比完全移除该项更好发现。
- **⚠️ 图层开关不只是配色**：`getSiteCategory` + `filteredSites`（`GISMap.tsx:264-268,288`）会据 `activeLayers` 与 `hiddenLegends` 把该类别站点从地图上**过滤掉**。地图站点变少是「只显示实时告警」的预期效果，不是漏画。
- 实时告警地图（`?page=realtime_alarm`）**未改动**，仍是 `rt_alarm + tt + wo`：那里的 TT/WO 由告警的 `tt_id` 派生，属于告警的关联信息，不算「用户额外打开的图层」。`normal` 的隐藏初值也**不影响它** —— 该页的 `filteredSites` 分支只认 `rt_alarm_overdue`/`rt_alarm_ontime`/`tt`/`wo`/`vip`，不含 `normal`。
- 图层开关状态不做持久化（存在组件 `activeLayers` / `hiddenLegends` 里），刷新页面即回到上述默认值。
- **点站点 → 右侧抽屉**（组件 `pages/gismap/SiteDrilldownDrawer.tsx`）四个页签，可搜索、可导 Excel。
- **导出站点清单**（`exportSites`，2026-09-27 新增）：图例下方的导出按钮，导的是**地图上当前可见的站点**
  （`filteredSites`）—— 与图例开关、图层、高级筛选后的那批点**口径完全一致**，而不是后端返回的全量 `sites`。
  列含站点/区域/县/制式/经纬度/TT·WO·告警数/VIP·Hub/TRM/FME，副标题写明「可见数/总数」与筛选条件数。
- 接口：`/api/gis/sites` 与 `/api/gis/realtime/sites`（按模式二选一）、`/api/gis/topology`（**读 `kml_mw_links`**，见 10c）、`/api/gis/region-boundaries`、**`/api/gis/county-boundaries`**、`/api/gis/drilldown/{site_id}` 与 `/api/gis/realtime/drilldown/{site_id}`。均走 `cache.ts` 缓存。
- 地图控件在 `pages/gismap/MapController.tsx`。
- **区分两页的口径**：实时告警地图带红色"实时"Tag，数据来自 `eflow_active_alarm`（每 30 分钟）；普通 GIS 页走历史/工单口径。
- 页头同样消费 `useDataTimestamps` 显示同步状态。

### 10b. 边界蒙层：大区（Voronoi）与县界（真实行政边界）

「边界」`Segmented` 提供**互斥的三选一**（`BoundaryMode = 'none' | 'region' | 'county'`）。两个蒙层语义不同，不可互相替代，同时开启会互相遮盖，故做成三选一而非两个开关：

| 模式 | 数据来源 | 性质 |
| --- | --- | --- |
| 不显示 | — | 只留站点，背景最干净 |
| **大区** | `GET /api/gis/region-boundaries`（`gis.py:1584`） | 由 827 个站点坐标 **Voronoi 推算**的 3 个大区（Montserrado / North East / South West） |
| **县界** | `GET /api/gis/county-boundaries`（`gis.py:1624`） | 利比里亚 **15 个县的真实行政边界**（GeoJSON 静态资源） |

**县界实现要点（2026-09-25 新增）：**

- **数据源**：`backend/data/gis/liberia_counties.geojson`（15 个 feature，含 `properties.name` / `db_name`）与 `liberia_country.geojson`（国界，16 个 MultiPolygon）。由用户提供的「利比里亚地图文件_国家边界含州名.txt」离线转换而来，**几何是静态数据**，故后端缓存 1 小时（`_COUNTY_TTL`）。
- **加载器**：`gis_geometry.py` 的 `load_county_boundaries()` / `load_country_boundary()` / `_merge_multipolygon_payload()`。文件缺失或解析失败返回 `[]` 并记日志，**不抛 500**——边界属增强显示，不该让整张地图挂掉。
- **坐标约定**：GeoJSON 标准是 `[lng, lat]`，本项目的 `polygons` 已按 **Leaflet 约定写成 `[lat, lng]`**（转换脚本完成交换）。`load_county_boundaries` **不再二次交换**，否则地图会画到南极洲。
- **⚠️ 县名映射（唯一一处命名差异）**：GeoJSON 里叫 `Rivercess`，而站点表 `province_county` 的值是 `River Cess`（库里还存在脏值 `River cess`，共 9 站）。因此 feature 上同时存 `name`（展示用）与 `db_name`（与 DB 对齐，下钻筛选用）。**点击县界用的是 `db_name`**（`GISMap.tsx` 的 `handleCountyClick`）；`site_count` 计算时也对 DB 值做 `\s+`→单空格归一化后累加，保证两种写法都计入。
- **口径一致性（AGENTS.md 三-1b）**：`/county-boundaries` 的站点计数与 `/gis/sites` 使用**完全相同的 WHERE**（同样要求经纬度非空且非 0）。实测 15 县合计 **827 站**，与 `/gis/sites` 的 `total` 一致，逐县核对全部相等。
- **标签数字口径（2026-09-25 用户要求改为告警数）**：端点同时返回两个计数，**地图标签显示 `alarm_site_count` 而非 `site_count`**：

  | 字段 | 含义 | 口径来源 | 实测合计 |
  | --- | --- | --- | --- |
  | `site_count` | 该县站点**总数** | 同 `/gis/sites` | 827 |
  | `alarm_site_count` | 该县**有实时告警的站点数**（`COUNT(DISTINCT site_id)`，非告警条数） | 同 `/gis/realtime/sites`（`realtime_alarm` JOIN 站点表 + 经纬度有效） | **38** |

  - 合计 **38 = `/gis/realtime/sites` 的站点数**，两处口径严格对齐。主表 JOIN 不上的告警（实测 4 站）**不计入任何县**，与实时页一致。
  - 标签写成 `Bong (7 告警)` 形式 —— 单个裸数字无法区分「站数」还是「告警数」，故带单位小字。用户要看站点总数时，点县界会打开高级筛选，抽屉与图例都给得出。
- **交互**：县界用「描边 + 淡色底块」（浅色主题 `fillOpacity 0.14` / 深色 `0.10`，深底同透明度会显脏），虚线描边以区分于大区实线；县名 + 告警站点数用 Leaflet `Tooltip(permanent)` 常驻在县域质心（样式见 `index.css` 的 `.gis-county-label`）。**点击县界 → 复用既有的 `province_county` 高级筛选**形成下钻闭环。
- **性能**：县界 GeoJSON 约 384KB，前端**只在首次切到「县界」模式时拉取**（`GISMap.tsx` 的 effect 带 `boundaryMode !== 'county'` 守卫），不影响默认打开速度。

### 10c. MW 链路数据源与配色（2026-09-25 换源 + 修撞色）

**换源（`gis.py` 的 `get_topology`）：`topology` 表 → `kml_mw_links` 表。**

| | 旧（`topology` 表） | 新（`kml_mw_links` 表） |
| --- | --- | --- |
| 行数 | 515 行，两次 JOIN `master_site_db` 后仅剩 **507** | **844** 条 link，端点自带坐标、**不 JOIN** |
| 丢线原因 | `site_a_id/site_b_id` 是站点编号，主数据缺行即被 `WHERE a.latitude IS NOT NULL` 静默过滤 | 无此问题 |
| 线色 | 无，前端按 `is_hub_link` 二分（红/蓝） | 自带 KML 4 色：红 27 / 黄 12 / 蓝 573 / 绿 232 |
| hub 标记 | 有 `a_is_hub`/`b_is_hub` | **无** |

- **响应结构保持兼容**：仍返回 `site_a_name`/`lat_a`/`lng_a`/`is_hub_link` 等旧字段，仅新增 `name` 与 `color`。`hop_count` 恒 `0`、`is_hub_link` 恒 `false`（kml 无此语义）。
- **⚠️ 连带影响（已同步修复）**：`PacketLossDashboard.tsx` 也复用 `/api/gis/topology`，它原用 `is_hub_link` 决定线宽加粗（`PacketLossDashboard.tsx:599,603`）。`is_hub_link` 恒 false 会让所有链路一起变细，故改为**按 KML 线色判定重点链路**（红/黄 = 重点，蓝/绿 = 常规）。
- **前端图例**：GIS 页图例由「Hub/普通」改为**按真实线色 4 档**（`KML_LINK_COLORS`，键 `gis.topologyColorRed/Yellow/Blue/Green`）；旧的 `gis.topologyHubLink`/`gis.topologyNormalLink` 已删除（无引用，遵循 AGENTS.md 三.10 删除优于兼容）。
- **颜色同源约束**：前端 `KML_LINK_COLORS` 与后端 `mw_links_store.py` 的 `STYLE_COLORS` 是同一组 4 色，**改一处必须改另一处**。
- 链路本身由 `?page=mwUmeTopology` 的页面上传 KML 维护（写 `kml_mw_links`，见 `mw_links_store.py` 与第 8 节）。

**配色修正：History Alarm 由橙 `#ffa94d` 改灰 `#8b95a5`。**

- **问题**：`his_alarm`(#ffa94d 橙) 与 `rt_alarm_ontime`(#ffd400 黄) 在深色底图上几乎无法区分，而二者分属「历史/实时」互斥通道，同色会误导判断。
- **改法**：改为灰色 `#8b95a5` —— 灰色天然表达「历史/已归档」语义，且与高饱和实时色在明度、饱和度两个维度都拉开距离。
- **⚠️ 不要改用 `#94a3b8`**：那是 `normal`（无告警站点）的灰，会与「历史告警站点」混淆。
- **配色单一真相源**：`GISMap.tsx` 顶部新增 `SITE_COLORS` 常量，图例 / 标记 / 图层 Tag / 弹窗文案四处共用。此前四处各写一遍，改一处漏三处，正是本次撞色的成因。**值必须是十六进制实值**（Leaflet canvas 解析不了 `WH.xxx` CSS 变量）。

**图例假 0 修正（`?page=gis`）。** `rt_alarm_overdue` / `rt_alarm_ontime` 是**实时模式专属**（`categoryCounts` 只在 `mode==='realtime'` 计数），但原 `legendItems` 的 filter 只在 realtime 模式过滤 `rt_alarm`/`his_alarm`，未在 all 模式过滤这两个键，于是 `?page=gis` 上出现「Realtime Alarm (Overdue) (0)」这种看着像故障的空指标。现按模式**对称过滤**：all 模式隐藏实时专属项，realtime 模式隐藏历史专属项。

**图例与图层是两套控制（易混淆，2026-09-25 明确）。** 同一行图例上并存两种交互，作用于不同 state：

| 交互 | 作用 state | 控制的类别 | 图例上的呈现 |
| --- | --- | --- | --- |
| **图层 Tag**（`layerOptions`，`GISMap.tsx:448`） | `activeLayers` | 实时告警 / 历史告警 / TT / WO | 独立一行 Tag，不勾选即关闭 |
| **图例点击**（`legendItems`，`GISMap.tsx:581`） | `hiddenLegends` | 全部 8 类，含 `normal` / `vip` | 该行加删除线＋「已隐藏」 |

两者的类别来源都是 `getSiteCategory`，最终在 `filteredSites`（`GISMap.tsx:271-295`）里合并生效。`normal` 的默认隐藏走的是 `hiddenLegends` 初值，因此它**仍在图例里可见**（带删除线），用户点一下就能恢复 —— 这是刻意选择：直接删掉图例项会让用户不知道还能显示普通站点。

## 12. 告警管理看板（`?page=alarmManagement`）— iframe

`AlarmManagement.tsx:6` → `public/alarm-management.html`，其 `<title>` 是 **Site Outages Monitor Dashboard · Alarm Management**，即**宕站（Site Outage）监控看板**。菜单名"告警管理"容易和第 3 页混，区别是：

| | 第 3 页 实时告警看板 | 本页 告警管理看板 |
| --- | --- | --- |
| 视角 | 全网告警按维度统计与下钻 | **站点是否宕** 的监控视角 |
| 与任务的关系 | 消费 `eflow_active_alarm` 数据 | 被 `site_outage_screenshot`（每天 01:00）截图，截图再由 `whatsapp_send`（03:00）发到 WhatsApp 群 |

`site_outage_screenshot` 的截图对象正是本看板的 **ERA / Regular / ALL 三个视图**（`task_registry.py:95-99`）。**改这个 iframe 页的 DOM 会连带影响自动截图任务**——改前先确认截图选择器还找得到。界面能力以该 HTML 自身为准。

## 13. 丢包看板（`?page=packet_loss`）

LTE 丢包（RAN UME SDR/IPRAN IPPD），最近 **7 个完整自然日、小时粒度**，当天没过完不展示（`PacketLossDashboard.tsx:2-5`）。

- 口径与 Excel 报告 `Packet_Loss_Status_Output Automation` **完全一致**：`STATUS` 是 0~23 的标志块，最近 3 天同整点丢包均 >0.5% 记 1，全 0 为 OK；`FINAL_STATUS` 在 OK 时强制 `No Packet loss[<0.1]`，否则按 Last 1 day Max PL 五级分类（:3-5）。
- 操作：`Switch` 控制是否包含 OK 站点（`include_ok`，:249）、Popover 显示口径说明、下钻 `GET /api/packet-loss-dashboard/drilldown?status=&limit=800`（:273）、拓扑叠加复用 `GET /api/gis/topology`（:224，该端点 2026-09-25 起读 `kml_mw_links`；本页线宽加粗按 KML 线色判定，见 10c）。
- 接口：`/api/packet-loss-dashboard/overview`、`/map-sites`、`/drilldown`。
- 数据由 `packet_loss_sync`（06:30）写入 `lte_pl.sqlite3`。

## 14. 电池看板（`?page=battery`）

站点电池健康度 / SOC / 充放电状态。

- **第一维度是"数据新鲜度"**：实测约一半电池读数超过 7 天（最老到 2024 年），因此所有均值/状态/低电量指标**默认只统计 ≤24h 的新鲜子集**——不过滤时"放电中"338 块，过滤后真实值只有 24 块（`BatteryDashboard.tsx:4-8`）。看数字前先确认新鲜度开关。
- 健康度几乎无方差（98~100 占 99%），所以主视图用"健康度分级 + 无数据占比"而不是直方图（:8）。
- 接口：`GET /api/battery-dashboard/all`、`/trend?days=`（:161-162）、单站下钻 `/api/battery-dashboard/site/{site}`（:315）。
- 数据由 `battery_kpi_sync` 每小时 :05 写入 `data/battery/battery_kpi.sqlite3`。

## 14i. 站点可用率（`?page=site_avail`）

按站点看四个制式（2G/3G/4G/TDD）的月度可用率与未达标天数。

- 两段式请求：`GET /api/site-availability/overview`（站点级月度值）+ 选项接口拿 Supervisor / FME / 省份等下拉（`SiteAvailability.tsx:411` 附近）。
- **未达标天数在前端按 `daily` 明细重算**，口径由页面上的阈值输入框（默认 99.65%）与视图（按周/按天）共同决定 —— 改阈值会实时改变"未达标"结果，不是固定后端值。
- **搜索框会过滤导出行**：`sites` 这个 `useMemo` 已含 search 过滤，导出直接复用它。
- **页面级导出**（2026-09-27 新增，筛选条刷新按钮右侧）：多 sheet —— `汇总指标`（站点数、各制式月均、未达标站点数、本月工单 TT 及其闭环情况、当前阈值/视图/搜索词/生成时间）+ `站点明细`（站点属性 + 四制式月均 + 当前制式最低值 + 未达标天/有数据天 + 按视图展开的时间维度动态列 + 工单三列）。
  导出**完全复用页面既有 `useMemo`**（`sites`/`belowSites`/`withDataSites`/`avgOfTech`），不在导出里另算一套。
  subtitle 写全 8 项筛选：月份 / Supervisor / FME / 制式 / 视图 / 阈值 / 仅看有数据 / 搜索词 + 生成时间。

## 14j. FME 排名（`?page=fme_ranking`）

按 FME（现场维护工程师）看可用率 / 工单量 / SLA 三类排名与前后三名榜单。

- 时间维度只有月度（`FmeRanking.tsx` 的 month 选择器）；维度下拉有 制式 / Supervisor / FME，另有搜索框。
- 三组榜单（可用率、WO、SLA）各取**前 3 与后 3**，名次由 `availRanked.length - i` 得到，导出里的名次与卡片上印的 `#号` 一致。
- **页面级导出**（2026-09-27 重写，位置未变，仍是工具栏刷新按钮之后）：3 个 sheet ——
  `Summary`（6 张概览统计卡 + 阈值 + 生成时间 + WO 源数据/已匹配/未匹配/时间字段等口径元信息）、
  `榜单（前/后三名）`（6 组榜单摊平成长表）、`FME 排名明细`（可用率/SLA/WO 三类排名与站点数、未达标站点、工单闭环数）。
  排名表取 `data.rows` **全量**，不受搜索框分页影响。
- **此前该按钮只导排名主表，且用的是已被搜索框过滤的 `rows`**，6 张统计卡与三组榜单卡全都没进文件 —— 现在补齐。
- 后端未返回的指标**整行跳过**，不用 `0` 冒充"确实是 0"；`availability`/`sla_rate` 为 `null` 时输出 `-`。

## 14k. RAN 小区 KPI（`?page=ran_cells_kpi`）

按制式（2G/3G/4G）看小区的逐日可用率矩阵与月度达标情况。

- 逐日矩阵是「**指标为行、日期为列**」的布局，页面只展示有数据的日期列（`activeDays`）。
- 制式筛选决定渲染哪几张表（`shownTechs`），阈值决定达标/未达标的判定。
- **页面级导出**（2026-09-27 重写，位置未变）：`Summary`（每制式一行，即页面上那排 StatCard 展开：月均可用率 / 小区名册 / 有数据天数 / 小区总数 / 达标数 / 未达标数 / 两向占比）
  + 每制式一张 `<制式>_Cells_KPI` 逐日矩阵（7 个指标行 × 有数据的日期列，列头 `D-MMM-YYYY`，与页面明细表同布局同口径）。
- **此前该按钮只导逐日矩阵，月度汇总 StatCard 完全没进去** —— 现在补齐。
- Sheet1 刻意命名为 `Summary` 而**不是** `{制式}_Cells_KPI`：否则若某制式 label 恰好也叫 `Summary`，会被 `excelReport.uniqueSheetName()` 改写成 `Summary_2`（`utils/excelReport.ts:229-240`），用户会看到两张像"汇总"的表。
- 百分比以**数值**写出（如 `99.65`）而非字符串 `99.65%`，Excel 里可直接计算。
- 下钻弹窗内另有导出按钮（导下钻明细），与页面级入口是两回事。

## 14l. UME 客户 KPI（`?page=ume_in_kpi`）

UME 侧 KPI 的采集结果：业务量、成功率、失败分因（系统侧 / 用户侧）、资源利用率与阈值告警。

- 顶部「立即同步」手动触发一次抓取（约 10~60 秒）；日常由 `ume_in_kpi_sync` 任务每天 05:45 自动同步。
- **天数筛选**决定统计窗口；页面按天聚合，数据窗口以 `latest_day` 为准。
- **页面级导出**（2026-09-27 新增，头部 Card 右侧工具栏）：5 个 sheet ——
  `Overview`（7 项数量统计 + 状态分布 + 4 项元信息，恒存在）、
  `KPI Summary`（KPI / 业务量 / 成功 / 失败 / 成功率 / 系统侧失败及其占比 / 用户侧失败 / 状态）、
  `Resource`（KPI / SERVICE / 日均 / 峰值 / 已用内存 / 状态）、
  `Alerts`（仅非 info 级 `hardAlerts`）、`Analysis Notes`（仅 info 级 `infoAlerts`）。
  后 4 个 sheet 按 `length` 判空跳过。
- subtitle 为 `数据日期 | 统计天数 | 数据窗口`，把天数筛选写进文件便于对账；取不到数据显示 `—`。
- 页面上另有一个原有的「全量导出」按钮；下钻明细不在本次页面级导出范围内（弹窗内已有）。

## 14b. NOC 操作人分析（`?page=noc_analyst`）—— 四层全量下钻

> 2026-09-23 重做：此前只有一张排名表和 3 条不可点的样本，**做不到"能下钻尽下钻"**；
> 本次补齐到「人 → 单 → 站点 → 告警链路」四层，页面上每个数字都可点。

基于 `eflow_tt.last_processer` 量化每位 NOC 的根因错位率、平均处理时长、夜班单占比与 SLA 通过率。
页面 `frontend/src/pages/NocAnalyst.tsx`，后端服务 `backend/services/tt_postmortem/__init__.py`，
路由 `backend/routers/eflow_qa.py`（`_tt_postmortem_noc*` 与 `_tt_postmortem_tt_detail`）。

### 口径（两层必须一致，否则表格数字与下钻行数对不上）

- **月份归属用 `alarm_occur_time`（告警发生时间）**，不是 `last_modified_time`。
  否则"上月发生、本月才闭环"的单会被算进本月（实测 2026-08 两种口径分别是 3459 / 5296 单）。
- **夜班** = `fo_accept_detail` 的 Accept 操作时间落在 `22:00–06:00`。
- **错位判定**以 `history_alarm.reason_type` 为权威，与 NOC 填报的 `root_cause` 比对；
  典型错位是 `POWER<-TRM`（NOC 填供电、系统指向传输）。概览与单 TT 详情**共用
  `_mismatch_of()`**，不存在两套结论。
- 错位率分母是**已填报根因的单数**（`with_root_cause`），不是总单数。

### 四层下钻

| 层 | 入口 | 接口 |
| --- | --- | --- |
| 1 | 概览数字卡 / Top3·Bottom3 卡片 / ECharts 柱状图 / 排名表每列 / 红旗人名 | 进弹窗 |
| 2 | 弹窗内 5 种切片：全部 / 根因错位 / 夜班 / SLA Fail / 慢单（≥12h） | `GET /api/eflow-qa/_tt_postmortem_noc_tt?noc=&month=&slice=` |
| 3 | 「异常站点」页签按站点聚合，点站点看该站全部 TT | `GET /api/eflow-qa/_tt_postmortem_noc_sites?noc=&month=&only_abnormal=` |
| 4 | 点 TT 单号 → 工单信息 / 阶段时长 / NOC 填报层 vs 系统判定层 / 告警链路明细 | `GET /api/eflow-qa/_tt_postmortem_tt_detail?tt_no=` |

### 为什么下钻是"重查"而不是"前端过滤"

`build_noc_tt_drilldown` / `build_noc_site_drilldown` 与概览端点的 WHERE 条件**完全一致**
（同一 `alarm_occur_time` 区间 + 同一 `last_processer` 精确匹配），切片在 Python 侧过滤
——因为错位/夜班依赖文本解析（`fo_accept_detail` 的 Operation Time），无法下推到 SQL。
这样保证「表格里的 1978 单 == 下钻 all 的 1978 行」。

### 三个已修正的坑

1. **`limit` 曾静默截断**：站点聚合原默认 `limit=1000`，而单人月峰值实测 1978 单，
   导致站点 `total` 求和只有 1000、与概览对不上。现三个端点默认 20000，超限时
   `meta.truncated` 为 true 且前端弹黄色告警条。
2. **路由 `limit` 上限过小**：`_tt_postmortem_noc` 原是 `le=10000`，前端按 10000 请求属边界
   侥幸通过；现放宽到 `le=50000`。
3. **动态拼 i18n key 会被守卫拦下**：`t('noc.slice.' + s)` 让 `scripts/check-i18n.mjs`
   误报「字典缺失 `noc.slice.`」。改成 `sliceLabelKey()` / `linkageLabelKey()` 显式 switch。

### 界面约定

- 卡片走 `components/cards` 的 `CardBase` / `StatCard`；下钻弹窗走 `DraggableClickModal`；
  导出走 `utils/excelReport` 的 `exportAoaReport`（导出的是**当前切片 + 当前搜索结果**）。
- ECharts 用 `useTheme()` 的 `palette.sev.*` 实值——`palette` 上没有 `ok`/`danger`，
  那是 `WH` 令牌，canvas 解析不了 CSS 变量。

### 14b-1. 时间归因区「时间都花哪了」（2026-09-23 新增）

> 目标是回答**"时间都浪费到哪里"**：把整月工单逐单按「TT 复盘报告」的口径解析一遍，
> 再聚合。页面上多出一块「时间归因与流程偏离」，位置在红旗告警之下、Top3 卡片之上。

**数据来源**：`GET /api/eflow-qa/_tt_postmortem_noc_timeline?month=&limit=&noc=&owner=&refresh=`，
实现在 `backend/services/tt_postmortem/__init__.py` 的 `build_noc_timeline_agg()`
（与单张 TT 的 `build_tt_timeline()` **同源同口径**，不另立一套结论）。

**展示内容**（每个数字都可点）：

| 区块 | 回答什么问题 |
| --- | --- |
| **顶部「承接方」三档切换（ZTE 自派 / IPT 第三方 / 全部）** | 把**派给第三方的单**与自派单分开看。默认 ZTE |
| 6 张数字卡（复盘单量 / 平均总历时 / 最大瓶颈环节 / 应派未派 WO / 偏离总数 / 缺失必需动作） | 总量与最刺眼的三个数；点卡片进「逐单清单」 |
| 饼图「各环节占时比例」+ 偏离类型分布柱状图 | 时间总量压在哪个环节、偏离主要是哪一类 |
| 分段表「时间都花哪了」 | 全流程切成互不重叠的区间，含合计/平均/P90/最长/超阈值单数 |
| 里程碑表「里程碑耗时分布」 | 9 个契约里程碑各自的 P50/P90/最长与时限；P50 就超时限的用红色标出 |
| **「应派未派 WO 明细」** | **高等级断站却没派现场工单**，按总历时降序，点 TT 号进单 TT 复盘。告警码与派单分类**悬浮可看名字与规则** |
| 「偏离清单（应做 vs 实做）」 | 8 类偏离按严重度排序，每条给 **15 条**样本单可点（原为 5 条） |
| 「缺失的必需动作」 | 契约要求但无确凿时间戳的动作及样本单 |
| 「按 NOC 归因」 | 谁的瓶颈最长、谁的偏离/未派 WO 最多；人名可点回第 2 层下钻 |

**承接方（IPT / ZTE）为什么要分开 —— 这是口径问题，不是展示问题。**

排给第三方（IPT）的单**本来就不建 WO**（第三方有自己的施工体系），但
「高等级断站未派 WO」原本只看"是否断站类 + 高等级/VIP/Hub + 无 WO"三个条件，
于是**把所有 IPT 单都算成了"规则失效"**。实测 2026-09：该判据共命中 1140 单，
其中 **844 单其实是派给 IPT 的**，属误报；修正后 ZTE 档只剩 **296 单**，
这才是真正"该派自派 WO 却没派"的量（差 3.8 倍）。

- **判据**：`_dispatch_owner(t)` —— 以 `eflow_tt.third_accept_detail` 有值为主，
  `last_processer = 'IPT(IPT)'` 为辅（两者取并集）。
  实测本月 `third_accept_detail` 有值 1369 单、`last_processer='IPT(IPT)'` 1180 单，
  后者被前者**严格包含**（第三方一接单就有值，`last_processer` 要等关单才写）。
  不要改用 `last_processer` 单独判断，会漏掉在途的第三方单。
- **切档三档合计自洽**：ZTE 1260 + IPT 1379 = 全部 2639（2026-09 实测）。
- **性能要点**：`owner` **不参与缓存键**。磁盘上只存一份"全部承接方"的完整结果
  （每单都带 `dispatch_owner`），三档共用这一份，切档是**纯内存重汇总**（≈2s）。
  若让 owner 参与缓存键，切一次档就要重新逐单复盘全月（冷算 ≈230s），
  默认档首屏直接打不开 —— 这是已踩过的坑。
- **切档必须重算派生统计**，不能只过滤 `tickets`：卡片/偏离清单读的是
  `deviation_stats`、`wo_stats` 等聚合值，只切 tickets 会出现
  "表格 1260 行、卡片还是 2639"的自相矛盾（AGENTS.md §3.1b）。

**悬浮看名字：告警码与规则分类都不再是"光秃秃的 ID"。**

界面上原本只有 `99933`、`rule_stopped` 这类码值，看的人得自己去查。现在鼠标悬浮即出名字
（带虚线底边的元素都可悬浮）：

| 悬浮对象 | 显示内容 | 来源 |
| --- | --- | --- |
| 告警码（`99933`） | 官方告警名（`SITE DOWN DUE TO POWER OFF`） | `eflow_tt.alarm_description` |
| 派单分类（`rule_stopped`） | 成因说明 + 命中的推单规则名与状态 | `_infer_dispatch_path().explanation` / `.related_rules` |

- **告警名统一走 `resolve_alarm_name()`**（`backend/services/tt_postmortem/__init__.py:100`），
  优先级 `alarm_description` → `ALARM_CODE_SEMANTICS` 静态表 → `title`。
  **不要只查静态表** —— 它只收录 11 个码，而本月实际出现 25 个不同告警码；
  实测 3374 单里仅 7 单缺 `alarm_description`，兜底链足以覆盖。
  `build_tt_timeline` 原先只查静态表，未收录的码会得到 `None`，界面上就只剩 ID。
- **规则名为什么必须带出来**：`rule_stopped` 这个分类码只说明"规则停了"，
  看不出**是哪条规则、谁停的**。悬浮提示补上规则名与 `ACTIVE`/`STOP` 状态后，
  一眼就能确认 `Regular断站故障手动到FO（STOP）` 才是本单无 WO 的原因，
  而 `ERA断站推单到ZTE WO（ACTIVE）` 是另一条本该生效的规则。
- 说明文字是**后端生成的中文散文**，前端原样渲染 —— 与既有「偏离清单」的
  `label` 字段（如 `缺少「Confirm 关单」`）同一做法，未做二次翻译。

**第 4 层扩展为完整复盘视图**：点「应派未派 WO 明细」的 TT 号或逐单清单里的单号，
打开的不再只是"告警链路"，而是按复盘报告章节顺序的 5 个页签——
`时间归因 / 里程碑时间轴 / 应做·实做 / 偏离清单 / 告警链路`，
数据来自 `GET /api/eflow-qa/_tt_postmortem_timeline/{tt_no}`。

**性能**：首次计算要逐单解析全月约 2600 张单，实测冷算 **≈150–230s**；结果按
`data/tt_timeline_cache/noc_timeline_<month>_v<版本>.json` 落盘缓存，之后读取 **≈2s**
（`meta.cache_hit=true`）。改了聚合口径必须**同时递增 `_TIMELINE_CACHE_VERSION`**，
否则会读到结构过时的旧缓存。该目录已被 `.gitignore` 覆盖。
带 `noc=` 过滤时**不写缓存**（避免把局部结果当成全月结果复用）；
带 `owner=` 切档时**照常写缓存**（缓存里存的是全量结果，切档在返回前完成）。

**口径要点（与单 TT 报告一致）**：

- **NOC 归属不用 `eflow_tt.last_processer`** —— 那是最后处理人（通常是关单的 FE，
  实测 2016/2295 单落在 `FE Robot(fe_robot)`）。改为取里程碑里第一个
  `fo_accept` / `fo_process` 节点的 `operator`，回退到 `people.fo_acceptor` / `fo_processer`。
- **WO 号在 `dispatch_path.wo_no`**，不在 `wo` 块（`build_tt_timeline` 的 `wo` 恒为 `null`）。
- `wo_stats.should_dispatch` 与 `missing_dispatch` 由**同一条判定**（偏离 4
  `no_wo_for_critical_outage`）构造，二者恒等，所以"未派占比"恒为 100%，**不要展示**；
  对外只用 `dispatch_rate_pct`（派单覆盖率 = dispatched / 全月单量，实测 39.7%）。

**手写 TS 类型必须与真实响应核对**：前端类型是手写的，字段名写错 `tsc` **不会报错**。
本页开发中已连踩三次（`wo.wo_no`、`expected_actions.reason`、时间轴节点的
`operator`/`gap_from_prev_s`/`wo_steps` 均不存在）。新增字段时用真实响应逐个比对，
里程碑的"距上一跳"要前端按上一个有时间戳的节点现算（节点上**没有** gap 字段）。

### 14b-2. 现场处置及时性（WO 生命周期）与 NOC 人工动作（2026-09-23 新增）

> 承接 14b-1 的诉求：原来「FO 接单 → 提交关单」只是一段总时长，
> **回答不了"NOC/现场人员及不及时"**。本次把 WO 的生命周期拆开，补上"工单建好后
> 压了多久才有人接"这类关键指标。

**新增两个区块**（都在「时间归因与流程偏离」内）：

| 区块 | 数据字段 | 回答什么问题 |
| --- | --- | --- |
| 阶段归并「时间压在谁手里」 | `phase_stats` | 把事件驱动的细分段按**阶段**合并（建单时延/接单等待/现场响应等待/现场作业/告警清除/提交关单/关单确认），比较 NOC / 现场 / 系统 各占多久 |
| 全月 WO 各跳耗时分布 | `wo_gap_stats` | 工单建单→FE 接单、接单→出发、在途、现场作业、关单各跳的 平均/中位/P90/最长 |
| NOC / 人工动作及时性 | `human_action_stats` | 每个**人工动作**等了多久、是否超过契约时限、超时限占比 |

**单 TT 弹窗（第 4 层）新增**：

- 「时间归因」页签的分段表新增**阶段**列（`phase`），一眼看出该单时间压在哪一类；
- 同页签底部新增「现场处置时间轴（WO 生命周期）」：WO 的
  建单 → FE 接单 → 出发 → 到场 → 处理完成 → 关单 → 离场 逐跳，含操作人与距上一跳时长。
- 无 WO 的单显式提示「本单无 WO（未派现场工单）」，**不再是一片空白**。

> **⚠ 分段模型已于同日改为事件驱动（本节的子段方案已废弃）**：
> `_build_time_spent()` 不再使用固定的 4 段 `_TIME_SEGMENTS`（detect/assign/handle/close），
> 改为**相邻真实事件的间隔**（锚点来自 `timeline` 里所有 `time_present` 的节点 + WO 现场步骤）。
> 原因见源码注释：固定分段会把现场等待挤进"提交→确认关单"，且窗口终点取
> `last_modified_time` 时会让整段等待**落在窗口之外**，页面显示"总历时 18 分钟"而时间轴横跨 16 小时。
> 因此 `segments[]` 现在带 `phase` / `phase_label`，且**不再有 `sub_segments`**
> （曾经实现的"handle 段细分"随固定分段一起作废，前端对应 UI 已移除）。
> 回归校验见 `TMP/_wo_inv.py`（四条不变量）与 `TMP/_contract2.py`（手写类型 vs 真实响应）。

**关键实现口径**：

- 时间口径：`eflow_wo.created_time` 与 `eflow_tt.created_time` **同时区**（同一单相差约 2 秒），
  可直接与 WO 的 `*_detail` / epoch 明细相减。`start_trip/arrive_site/leave_site` 是 JSON 数组，
  `operationtime` 为 **epoch 毫秒**；`accept/process/confirm` 是
  `Operation Time:YYYY-M-D HH:MM:SS` 文本。空数组 `[]` 表示该步未发生，**不能当成耗时 0**。
- `_WO_STAGE_SPECS` 定义 7 跳；`build_wo_timeline()` 产出 `stages` / `gaps` / `summary`。
- `onsite`（现场作业）**不能**复用 `fo_accept → fo_process`（那与 `process` 完全同值，
  实测两条都是 8.88h/2325 条，纯重复）；必须按 WO 的 `到场 → 处理完成` 算，无 WO 则不产出该条。
- **后端返回的 `label` / `phase_label` 都是中文硬编码**，直接渲染会让英文界面出现中文。
  前端按稳定的 `key` / `phase` 经 `switch` 映射到 i18n 键
  （`woGapLabelKey()` / `humanActLabelKey()` / `phaseLabelKey()`），查不到才回落后端值。
  **不可用 `t('noc.woGw.' + key)` 动态拼键**，会被 `check:i18n` 拦下。
- 阶段归并必须满足 **阶段之和 == 分段之和**（已做成不变量回归项）。
- **偏离清单样本数 = 15**（源码 `backend/services/tt_postmortem/__init__.py` 里
  `if len(e["sample_tts"]) < 15`）。原为 5 条，用户反馈"太少了"——
  高发偏离（根因错位 1361 单）取 5 条时几乎全是同一批人/同一站点，
  看不出分布，会被误读成"样本就这么多"。
  注意「缺失的必需动作」是**另一处**（同为 `sample_tts` 但独立累加，
  且界面上是行内平铺而非表格列），**仍保持 5 条** ——
  那里 15 条会变成一堵链接墙。改计数时别把两处一起改。

**性能**：本次口径变更**递增了 `_TIMELINE_CACHE_VERSION`（1 → 2 → 3 → 4 → 5）**，
旧缓存因版本号与必需键校验（`wo_gap_stats` / `human_action_stats` / `phase_stats`）双重把关而自动失效重算，
冷算约 **150–180s**。改聚合口径时务必同步递增版本号。

实测（2026-09，2325 单）阶段归并：提交关单 34.0% / 关单确认 22.5% /
**现场响应等待 15.2%（中位数 6.43h）** / 告警清除 14.7% / 建单时延 6.5% /
接单等待 6.2% / 现场作业 0.8%。
WO 侧更直白：**WO 建单 → FE 接单 中位数 11.0h、P90 41.9h、最长 192.4h**，
而接单之后（出发/在途/现场作业）中位数都只要几分钟。
即**现场动作本身很快，慢的是"没人接单"这一段**——
这正是本次要暴露的结论，也是原来看不出来的。

## 14c. TT 复盘报告 · 里程碑时间轴与偏离检测（2026-09-23 增强）

入口：`EflowQa` 页 →「TT 复盘报告生成」抽屉（`components/TtPostmortemPanel.tsx`），
输入单号 → `GET /api/eflow-qa/_tt_postmortem/{tt_no}`；Markdown 导出走
`POST /api/eflow-qa/_tt_postmortem_export_md/{tt_no}`。
实现：`backend/services/tt_postmortem/__init__.py` 的 `build_tt_timeline()`，
由 `build_tt_postmortem()` 以子视图方式并入返回体（构建失败不拖垮主报告）。

### 返回体新增字段

| 字段 | 含义 |
| --- | --- |
| `timeline` | 9 跳里程碑，每跳含 `time / time_present / actor(system\|human) / operator / detail / source / raw / gap_from_prev_s` |
| `expected_actions` | 契约逐项对照：`required`（必需/条件）× `done`（应做/实做） |
| `missing_actions` | 必需动作但库里取不到时间戳的清单 |
| `deviations` | 偏离清单，按 `severity` 排序（critical → major → minor） |
| `site_history` | 同站历史告警指纹（判定「反复同源故障」的佐证） |
| `timeline_meta` | 窗口、总历时、跳数统计、阈值、口径说明 |
| `time_spent` | **时间都花哪了**：`segments[]`（分段耗时/占比/责任方/是否超阈值）+ `bottleneck_note` + `unaccounted_s` |
| `sla` | SLA 关键信息：`status / is_breached / total_text / deadline / over_seconds / over_source / cause` |
| `people` | **责任人**：建单人（含 `creator_kind` 人工/系统自动）/ FO 接单人 / FO 填报人 / 关单人 / WO 建单人 / WO 当前处理人 / `wo_people[]`（现场动作责任人） |
| `dispatch_analysis` | **为什么走人工派单**：按 TT Push Order Rule 逐条比对，见下方 14d 节 |
| `assignment` | **这单指派给谁了**：建单 `Assign To` / `Assignee Group` / `current_handler` / 群组池规则，见下方 14f 节 |
| `ticket` | TT 单信息（面板顶部卡片读的字段）：`ticket_severity / alarm_severity / alarm_code / status / domain / title / alarm_occur_time / alarm_clear_time / created_time / last_modified_time / fault_duration_time / impacted_service / wo_no`。**`wo_no` 是「Handled by」旁边那句红字（in-house 单无 WO = 异常）的唯一判据**，见 14h 节末尾 |

> 界面顺序（`TtPostmortemPanel.tsx`）：**SLA 告警条 → TT 单信息（含责任人） → ⏱ 时间都花哪了
> → ① 里程碑时间轴 → ② 该做的动作 → ③ 偏离清单 → ④ 根因对比 → ⑤ WO 派单机制 → ⑥ 阶段时长 → ⑦ 改进建议**。
> Markdown 导出把「时间都花哪了」编为 **0 节**（复盘重点前置），其后 1~7 节编号不变。

### 时间归因（`time_spent`）的分段口径

**分段由真实事件链生成，不是写死的 4 个文档流程段。** 做法：把时间轴上所有
有确凿时间戳的跳 + WO 现场步骤（出发/到场/离场）按时间排序，相邻两事件之间的
间隔就是一段。同一秒的多个事件合并成一个锚点（代表事件取契约位置最靠前的那个）。

| `phase` | 阶段名 | 含义 |
| --- | --- | --- |
| `detect` | 建单时延 | 告警发生 → TT 建单 |
| `assign` | 接单等待 | TT 建单 → FO 接单 |
| `dispatch` | 派单 | FO 接单 → WO 派单 |
| `onsite_wait` | **现场响应等待** | 派单/上一事件 → 现场出发（**最容易出大数的一段**） |
| `onsite_work` | 现场作业 | 出发 → 到场 → 处理 |
| `clear` | 告警清除 | → 告警清除/自愈 |
| `handle` | 提交关单 | → FO 提交关单 |
| `close` | 关单确认 | → 确认关单 |

- **统计窗口的终点取"所有已知活动的最晚时间"**（`confirm_detail` / `last_modified_time` /
  `alarm_clear_time` / 最后一个事件取最大），不再只用 `last_modified_time`。原因见下方坑 10。
- 四段**互不重叠**且**按构造必然覆盖全窗口**，因此 200 单回归 `unaccounted_s` 全为 0。
- `bottleneck_note` 一句话点明瓶颈**阶段名**、占比、责任方、超额量。
- **单未走完流程时末段标签会说实话**：没有 Confirm 就显示「… → 至今（未见关单）」。

### 「责任人」的取数口径

| 角色 | 取自 | 备注 |
| --- | --- | --- |
| 建单人 | `create_by` 或 `creator` | `assign_rule` / `fe_robot` / `auto_robot` / `system` 判为「系统自动」 |
| FO 接单人 / 填报人 | `fo_accept_detail` / `fo_process_detail` 的 `Operator:` | 文本 `Operation Time:` 格式；**可能是机器人**，见下方坑 8 |
| 关单人 | `confirm_detail` | `auto_robot` 出现在此处属正常（自动关单） |
| WO 现场动作人 | `eflow_wo.start_trip_detail` 等 | **JSON 数组**，见下方坑 5 |
| WO 建单人 | `eflow_wo.creator` | 额外给 `wo_creator_kind`（系统自动 / 人工），见下方坑 8 |

### 「执行方」与「实际动作」都是三态，不是两态（2026-09-23 修正）

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `actor` | `system` / `human` / **`unknown`** | `unknown` = **未证实**：取不到证据，也不能断定没做 |
| `status` | `done` / **`unproven`** / `missing` | 已执行 / **未证实** / 未执行（必需动作确实缺失） |

- 界面：未证实用**金色问号**，缺失用**红色叉**，两者视觉上必须能区分。
- Markdown §2 对 `unproven` 单独加一段说明，**不写成"未执行"**——把"查不到"说成"没做"是误导。
- 三态的出现原因见下方坑 8：`eflow_tt` 没有独立到场字段，`eflow_wo` 的现场明细又常常为空，
  此时**既不能证明有人到过现场，也不能证明没人去过**。

### 里程碑契约（`STAGE_CONTRACT`，顺序即期望顺序）

```
告警发生 → TT 自动建单 → 派单路由决定 → FO Accept 接单 → WO 派单(*)
        → 现场处置(*) → 告警清除/自愈 → FO Process 填报 → Confirm 关单
```

带 `(*)` 的是**条件动作**（`expected=False`），缺失不计入 `missing_actions`，
但会由偏离规则单独判定——例如"高等级断站未派 WO"。

### 偏离的 4 类（`kind`）与判定阈值

| kind | 含义 | 判定 |
| --- | --- | --- |
| `missing` | 应有动作缺失 | 必需跳无时间戳；或断站码 + P1/P2/VIP/Hub 却无 WO |
| `late` | 做了但超时 | `STAGE_THRESHOLDS`：建单/接单 30min、Accept→Process 8h、清除→关单 2h |
| `out_of_order` | 动作越序 | **仅对契约上有先后约束的相邻对**判（见下方坑 3） |
| `data_conflict` | 字段冲突 | **仅** `POWER<-TRM` 一类（见下方坑 2） |

### 十三个已修正的坑（都会静默出错，务必留意）

1. **`_parse_dt` 会算错不补零的时间**——eFlow 的 `*_detail` 里是 `2026-9-21 23:25:35`
   （月/日不补零）。原实现只试补零格式，失败后回落到 `datetime.fromisoformat`，
   而它会把 `2026-9-2` 读成 9 月 2 日再把 `1 23:25:35` 当别的字段，**不抛异常**：
   实测 `23:25:35` 被静默解析成 `23:25:03`。修复：先正则规范化月/日补零，
   且**不再无条件回落 `fromisoformat` 去猜**（猜错比失败更危险）。
   该 bug 会让**所有阶段时长集体偏差**，不只影响本页。
2. **`_qcol` 在 PG 下会折叠大小写**——`ocrule_details` 的列是 camelCase
   （`ruleName` / `ruleType`…），PG 把未加引号的标识符折成小写后报「字段 rulename 不存在」，
   导致 `_load_push_rules` 整条查询失败并**静默返回空**：页面上「断站类码 ACTIVE 覆盖」
   永远显示「（无）」、`active_rule_count` 恒为 0，而派单分类却仍给结论（两处证据自相矛盾）。
   修复：`_qcol` **一律加双引号**（sqlite 同样合法），且 `ORDER BY` 改用原始列名。
3. **越序只对契约相邻对判定**——曾经对时间轴上所有相邻跳判倒挂，结果
   「告警清除 → FO Process」被判越序，实测 120 单里 86 单如此。但**告警自愈本就
   早于文书流程，这是常态不是异常**，误判会淹没真问题。现只保留
   `_ORDER_PAIRS` 里的 4 对。
4. **根因错位不能全量入偏离**——NOC 的 `root_cause`（POWER/RAN/Fiber/Planned work…）
   与系统 `alarm_reason_type`（实测本库 99% 是 TRM）是**两套不同粒度的分类法**，
   直接比对会让几乎 100% 的单子"错位"、报告失去区分度。现偏离只收
   **语义确凿冲突的 `POWER<-TRM`**（复盘报告 §4 已用 2,529 张单验证过的系统性误填）；
   其余组合仍在正文「根因对比」表里并列展示，只是不判偏离。
   > 注：**概览/下钻页的「错位率」口径不变**（`_mismatch_of` 仍返回 `其它` 类），
   > 那里是人工逐条复核的列表场景，宽口径更合适。两者用途不同，勿强行统一。
5. **WO 的现场步骤是 JSON 数组，不是 `Operation Time:` 文本**——`start_trip_detail`
   / `arrive_site_detail` / `leave_site_detail` 存的是
   `[{"opname":"Start Trip","operator":"FE_FE_133","operationtime":1790149109856,...}]`，
   只有 `accept_detail` / `process_detail` / `confirm_detail` 才是文本格式。
   原实现统一套文本解析器，实测 **9,950 条** `start_trip_detail` 全部解析为空，
   「现场处置」这一跳永远显示缺失。修复：新增 `_parse_wo_json_step()`，
   两条路径都走；`operationtime` 是 **epoch 毫秒**，用 `_norm_wo_time()` 转换；
   展示名优先取 `candidateoperator[0].name`（否则报告上只有 `FE_FE_133` 这种工号，无法点名）。
6. **时间轴必须按真实发生顺序排，不能按契约顺序硬排**——WO 派单、现场到场、告警清除
   三者在真实世界里会交错。实测 `TT202609230005`：WO 在 `00:27` 派、现场 `07:38` 到场、
   告警 `07:27` 清除；若按契约顺序把「现场处置」排在「告警清除」之前再算相邻跳间隔，
   就会出现 `-7.00 小时`的**负间隔**，读者会以为数据错了。修复：构建完成后按时间升序
   重排（无时间戳的缺失跳沉底），并**重算** `gap_from_prev_s`（沿用排序前的间隔同样会错）。
7. **时间归因必须覆盖全窗口，缺口要显式暴露**——末段终点若写死 `confirm`，遇到
   「未走完流程（无 Confirm）」的单子，分段之和会远小于总历时，出现说不清去向的黑洞
   （实测 `TT202609220068` 差 4.6h）。修复：末段终点缺失时回落到全流程终点，并返回
   `unaccounted_s` / `unaccounted_note`；跑 200 单回归，仅 4 单有缺口（最大一单
   `TT202609220123` 缺 `fo_accept`，缺口 8.84h，note 已如实说明）。
   同时 `time_spent.total_seconds` 与 `timeline_meta.total_seconds` 统一为**同一口径**，
   避免页面「总历时」与「合计」两个数字打架。
8. **「存在 WO」不等于「现场有人」——不要把 WO 创建时间当现场处置时间**——
   旧实现把 `eflow_wo.created_time` 当作现场处置的时间戳、`actor` 写死 `human`、
   `ok = has_wo`，于是报告里出现「现场处置 ｜ 人工 ｜ 2026-09-22 16:53:51」这种
   **无依据的结论**。实测该单（`WO202609220068`）的 WO 由 **`fe_robot` 自动创建**，
   真正的现场动作在**次日 08:44**（`Stanley Biney(FE_FE_101)` 出发/到场），
   比 WO 创建晚了 16 小时——原写法连时间都是错的。
   根因：`eflow_tt` **没有独立到场字段**，`eflow_wo` 的出发/到场/离场明细又常为空。
   修复：以 `start_trip_detail` / `arrive_site_detail` / `leave_site_detail` **明细**为唯一证据；
   取不到时 `actor=unknown`、不给时间、`status=unproven`，并在说明里点明
   「WO 由 `fe_robot`（系统自动）创建，**不能据此推定现场有人**」。
   200 单回归实测：**86 张有 WO 的单里只有 18 张有真实现场明细**，另 68 张从
   "现场处置 人工"改判为"未证实"——这是本次修正影响面最大的一处。
   > 顺带修正：告警清除的说明不能笼统写「有现场动作明细」。上例告警在 `16:55` 就清了，
   > 现场动作却在次日 `08:44`，两者相隔 16 小时。现按先后关系分别输出
   > 「告警先清除，现场动作在其后」/「现场动作早于告警清除」。
9. **机器人操作人不能被记成「人工」**——`fo_accept_detail` 的 `Operator:` 可能是
   `FE Robot(fe_robot)`（机器人自动接单），但旧实现把 `fo_accept` / `fo_process` 的
   `actor` 写死 `human`，报告里就出现「FO Accept 接单 ｜ 人工 ｜ `FE Robot(fe_robot)`」
   这种自相矛盾的结论。修复：新增 `_is_robot_operator()` / `_actor_of()`，
   命中 `fe_robot` / `auto_robot` / `assign_rule` / `system` / `robot` / `auto_` 即判为 `system`，
   并在说明里补「（机器人自动接单）」。
   200 单回归实测：`fo_accept` **165/200 是机器人**，`fo_process` **163/200 是机器人**。
   注意 `_is_robot_operator` 是**子串**匹配（要能认出 `FE Robot(fe_robot)` 这种展示名），
   所以不要拿它去判站点名之类的业务文本。

10. **写死的分段端点会把最大的一块时间藏起来**——旧实现固定 4 段
    （detect/assign/handle/close，端点全是文档流程节点），遇到"机器人秒填文书、
    人在第二天才到现场"的单子就全错。实测 `TT202609220139`：
    WO 派单 `2026-09-22 16:53:51`、现场到场 `2026-09-23 08:44:25`，
    中间**等现场响应 15.81 小时**；但 `fo_process` 被机器人秒填在同一秒，
    这段等待全挤进"提交 → 确认关单"，而窗口终点又取 `last_modified_time`
    （停在 `16:56`，早于现场动作）→ **整段落在窗口之外**，
    页面显示"总历时 18 分钟"，与时间轴上横跨 16 小时的记录直接矛盾。
    修复：① 窗口终点取所有已知活动的最晚时间；② 分段改由真实事件链生成。
    修正后该单总历时 `16.10h`，瓶颈如实显示为「现场响应等待 15.81h（98.2%）」。
11. **`create_detail` 的字段之间用句点分隔，模糊匹配会把句点当值**——
    `Assign To:. Assignee Group:.` 用"值到下一个大写词"的正则去取，
    得到的是 `'.'` 而不是空，于是报告写成"建单即指派到人：."。
    修复：用**字段名联合前瞻** `(A|B|C):(.*?)(?=(?:A|B|C):|$)` 逐字段取值，
    再 `strip(".")` 并把空串归一为 `None`。
    > 这个 bug 的危险在于"看起来有值"，会把**未指派**误报成**已指派**——
    > 而"未指派到人"恰恰是长时间无人响应的关键线索。

12. **取字段值的正则必须把所有字段都列为边界，且长名在前**——
    `Operation Result` 的取值原本只以 `Next Status` 为界，于是
    `operation_result` 变成 `'FO Accept. Operation Time:2026-9-23 11:57:55. Operator:assign_rule(assign_rule)'`。
    修法：把 `Operation Time` / `Operator` 也列进 `_CREATE_FIELDS`。
    **`Operator Group` 必须排在 `Operator` 前面**（正则择先匹配），
    否则 `Operator Group:` 会被 `Operator` 抢先吃掉。
13. **"未指派到人"的结论不能只看 TT**——见 14f 节。曾经据此断言
    `TT202609220139`/`TT202609230055` "没有任何人被指派"，实际两者都已在 **WO 层**
    指派到具体个人（`P:` 前缀）。真正的分布是
    `create_unassigned 199/200` 但 `scope=person 89`——
    **建单环节未指派 ≠ 这单没人负责**，两句话混用就是错误结论。

### 每条结论都可回溯

`timeline` 每跳都带 `source`（取自库中哪个字段）与 `raw`（原始 `*_detail` 文本），
前端悬停「[原文]」可看。这是本节的设计底线：报告给出判断，但人要能自己核对到原始记录。

### SLA 超期时长的两个口径（别混）

| 值 | 口径 | 示例（TT202609210140） |
| --- | --- | --- |
| `over_seconds` | 关单时间 − SLA 期限 | 3.83h（优先用 `sla_remain_time` 的负值） |
| 阶段 `over_by_s` | 该阶段耗时 − **阶段阈值**（`STAGE_THRESHOLDS`） | 3.86h（8h 阈值） |

两者**基准不同**（一个对 SLA 期限、一个对阶段阈值），数值接近但不是同一个数，
报告里不要互相套用。`over_source` 字段说明本次超期时长是怎么算出来的。
> `_parse_sla_duration('0d8h0m')` 曾经返回 `None`（正则分组位置错位），
> 导致 `sla.total_s` 恒为空。现按 d/h/m 分段可选匹配并逐单位取值。

## 14d. 为什么走人工派单 —— TT Push Order Rule 逐条比对（2026-09-23 新增）

回答「这单为什么需要人工派单、为什么没自动建 WO」。返回体字段 `dispatch_analysis`，
报告 Markdown 落在 **§5b**，界面是 **⑤b 卡片**。
实现：`backend/services/tt_postmortem/__init__.py` 的 `_analyze_dispatch_reason()`
（规则目录 `_load_rule_catalog()`、特征归一 `_ticket_signature()`、目标判定 `_rule_target()`）。

### 判定链路（eFlow 三段式）

```
1. ttDispatchRule（triggerStep=autoDispatch）决定 TT 落 BO 还是 FO 通道
2. ttPushOrderRule（triggerStep=FOAccept）决定 FO 接单时**是否自动建 WO**
3. 第 2 步无 ACTIVE 规则命中 → 不建 WO → FO 人工接单，现场出人无系统保证
```

### `overall` 的 8 种取值

| overall | 含义 |
| --- | --- |
| `auto_dispatched` | 已产生 WO，规则生效 |
| `manual_by_design` | 唯一适用规则的名字里写着「手动」（如 `Regular断站故障手动到FO`）→ 人工是设计意图 |
| `no_wo_by_design_multi` | 多条规则同时适用，但**没有一条会建 WO** → 无 WO 的结果确定 |
| `routed_to_other_system` | 命中的 ACTIVE 规则目标是别的系统（如 IPT），不建 WO 属预期 |
| `rule_should_have_fired` | **异常**：有 ACTIVE 且适用的建 WO 规则，却没建 WO |
| `no_active_rule_matched` | 唯一适用规则已停用，其余均不适用 |
| `rule_vacuum` | 没有任何适用规则，无规则可依 |
| `ambiguous` | 多条目标不同的规则竞争且其中有建 WO 的，需人工按优先级确认 |

### 四个必须整词/按目标判定的坑

1. **`cell` 必须整词匹配**——站点名 `Qcell LMTI (Marshall)` 含 `cell` 子串，
   用 `"cell" in text` 会把「Partial site down (PSD)」这类**站点级**断站误判成
   **小区级**故障，错误套用「小区故障派ZTE WO」，在 200 单回归里造出 **7 个**
   "应建 WO 却没建"的假异常。修复：`_has_word()` 加字母边界（`qcell` 因 `q` 紧邻而不命中），
   且**不把 `title` 纳入比对文本**（title 嵌了站点名，专有名词可能含特征词）。
   同理规则描述里的 `operation` 会因含 `era` 被误判为「针对 ERA 站点」。
2. **必须区分规则的「派发目标」**——`Regular电源故障推送TT到IPT` 是 ACTIVE 且常命中
   （200 单里 81 单），但它的目标是 **IPT 而不是建 WO**。若把它当成"应建 WO 却未建"，
   会把正常行为误报成 89 单规则失效（真实为 0）。修复：`_rule_target()` 分
   WO / IPT / BO / MANUAL / UNKNOWN，只有 `WO` 目标才算"应建 WO"。
3. **「手动」类规则不算故障**——`Regular断站故障手动到FO` 的设计意图本就是人工处理
   （描述 `Normal+COOL站点`），所以 REGULAR 站断站不建 WO 是**设计如此**。
   这个区分决定复盘结论的方向：是"要改规则"还是"要改流程预期"。
4. **`dispatch_analysis` 只能算一次**——`build_tt_postmortem` 曾自己另算一份，
   但它的 `SELECT` 没有 `alarm_description` → 特征识别不到「断站」→ 规则匹配静默变 0 命中，
   导致「改进建议」与报告 §5b 自相矛盾。修复：把 `build_tt_timeline` 提到
   `suggested_actions` **之前**构建，两者共用同一份结果。

> **口径边界**：规则适用范围由规则名/描述关键词**反推**（看不到 eFlow 规则表达式），
> 输出里始终带 `caveat` 并把规则原文并列展示，供人工复核。不要把它当成引擎的权威判定。

## 14e. eFlow 知识库 · TT 快速分析的「规则命中证据」（2026-09-23 新增）

页面 `?page=eflow_qa`（门户 `MsPortal/viewer.html?gid=Knowledge Q&A&no=47` 内嵌的就是它）。
输入 TT 单号后，「AI 分析结论（TT单分析技能）」卡片在 AI 正文之下多出一块
**规则命中证据（本地规则引擎）**，回答「这条结论依据哪条规则、规则在哪个文件、
谁维护、工单谁在处理」。

### 两块内容的分工（关键）

| 块 | 性质 | 来源 |
| --- | --- | --- |
| AI 正文（Markdown） | **模型推断**，可读性好、可解释 | 本地 WorkBuddy 代理主用 → Open WebUI 备用（`backend/services/openwebui_client.py`） |
| 规则命中证据 | **确定性事实**，与矫正表逐字一致 | `backend/services/eflow_rules/tt_rule_evidence.py` |

两者**不是同一套判定**，页面并列展示正是为了让 AI 结论可以直接被核对；
证据块不会因为模型不可用而消失（`ai.ok=false` 时照样渲染）。

### 数据链路

```
GET /api/eflow-qa/tt-ai?tt=<单号>&lang=zh|en      （backend/routers/eflow_qa.py）
  ├─ _tt_context()                        本地库/ eFlow 实时兜底拿工单 + 告警 → report
  ├─ tt_rule_evidence.build_rule_evidence()   本地规则引擎判定（权威）
  │    └─ tt_batch_severity.check_batch()   ← 与每天 04:20 的 eflow_tt_rules_check 同源
  │    └─ eflow_TT_rules.xlsx               ← 规则明细（类型/触发步骤/维护人/条件原文）
  │    └─ eflow_tt_rules_check_latest.json  ← 规则条数与最近一次收集+匹配时间
  ├─ render_evidence_text()                → 证据文本块，随 user 消息下发
  └─ openwebui_client.analyze_tt(..., evidence_text=...)
返回 ai.rules（结构化，页面明细块） + ai.evidence（下发的证据原文，排查用）
```

证据块展示的内容：命中规则名称 + ID、优先级、目标级别、逐条条件匹配
（`assetType=COOL = COOL ✓` 这种，来自 `eflow_rules_matcher._fmt_detail`）、
规则条件原文（折叠）、规则来源文件 `eflow_TT_rules.xlsx` 与 `MATCHING_REPORT.md`
（**可下载**，走 Email Reports 的白名单下载接口）、ACTIVE 规则条数、规则表更新时间、
最近一次收集+匹配时间、规则维护人（创建人/更新人）、工单处理人
（`last_processer` / `last_processer_group`，取自 `inspect_tt` 报告的「派单」段，不额外查库）。

### 三个必须知道的坑

1. **规则引擎判定只在本地 `eflow_tt` 有该单时有效**：工单只存在于 eFlow 实时接口时
   `found=false` → `available=false`，证据块显示「规则引擎未判定」并给出原因，
   AI 走原有纯文本判定路径。不要把这个当成报错。
2. **证据文本必须与规则表同时给出**：`analyze_tt` 的 system 消息里已经内嵌了全部 ACTIVE
   规则（外部模型不走 Open WebUI 的 RAG），证据块是**补充权威判定**，
   不是替代规则文本 —— 少了规则文本，模型无法解释未命中原因。
3. **下载地址受白名单约束**：`/api/email-reports/download/eflow_tt_rules_check/<文件名>`
   只放行 `backend/routers/email_reports.py` 中 `_SOURCES`/`_EFLOW_FILE_SPECS` 里登记过的
   文件名。新增产物文件必须两处同步登记，否则「能列出却下载 403」。

### 14e-1. 模型全档失败时的「程序化结论」（2026-09-23 新增）

原先模型不可用时页面只有一行
`AI analysis failed: RuntimeError: 所有候选模型均失败 ['workbuddy:…','openwebui:…']`，
用户拿不到任何判定。现在 `tt_ai` 会在 `ai.ok=false` 时再调
`tt_rule_evidence.render_local_conclusion()`，**由本地规则引擎程序化生成一份 Markdown 结论**：

```
ai.ok                    false（语义不变：这次不是模型给的）
ai.error                 真实失败原因（原样保留，便于排障）
ai.fallback              true
ai.fallback_conclusion   程序化结论 Markdown（工单字段表 → 判定结论 → 规则来源与责任人 → 处置建议 → 失败原因）
ai.rules                 结构化证据（页面「规则命中证据」块，正常/失败两种情况都用）
```

页面（`EflowQa.tsx`）在 `!ai.ok` 时渲染顺序为：错误 Alert → 「程序化判定（本地规则引擎）」
标签 + 结论 Markdown → 规则命中证据块 → 耗时。**不要把 `ai.ok` 改成 true** ——
那会让「模型给的结论」和「引擎给的结论」再也分不开。

四段内容全部可程序化推出，无模型参与：字段表取 `inspect_tt` 报告的列值（数值列去掉 `.0` 尾巴），
判定取 `level_status`（`ok`/`adjust`/`unknown` 三分支各有一套处置建议），
规则来源/维护人取规则表列，处理人取「派单」段。

> **两个口径别混**：规则引擎按 `eflow_tt` 列判定（「逐条匹配」里的就是实际取值），
> 而技能 prompt 的部分字段（如 `downSiteCount`）取自告警行，实测同一单可能一个是 1、
> 一个是 6。程序化结论里已显式标注「以逐条匹配为准」，改这里时别把两者当成同源。

### 14e-2. 推单规则证据：这单会不会自动推 WO、推给谁（2026-09-23 新增）

「规则来源与责任人」原先只有**级别规则**（`ttLevelRule`，回答「该是什么级别」），
缺了**推单规则**（`ttPushOrderRule`，回答「会不会自动推 WO、推给谁、谁自动处理」）。
现在两套都给：页面「规则命中证据」块下面多一个推单规则子块，程序化结论的
「### 3. 规则来源与责任人」里也多一段 `#### 推单规则（TT Push Order Rule，触发步骤 FOAccept）`：

```
- Rule Name: ERA断站推单到ZTE WO（ID 203，优先级 2）
- Rule Type: TT Push Order Rule
- Rule Trigger Step: FO Accept
- Push Order Path: FOAccept > FOProcess > FOProcess
- *Auto Operator: FE Robot (fe_robot)
- Target Handler: ZTE_NOC_FO [ZTE_NOC_FO]
```

数据源是 `eflow_push_rules.xlsx` 的 `Push_Rules` 工作表（`eflow_Push_Rule_Collector`
落盘，就是 Email Reports → eFlow TT Rules Check 页签里可下载的那份），
字段名沿用 eFlow 规则页签的英文写法。返回字段 `ai.rules.push_rules`：

| 字段 | 含义 |
| --- | --- |
| `matched[]` | `triggerStep=FOAccept` 命中的推单规则（决定自动建 WO 的那一步） |
| `other_steps[]` | 其他步骤（如 `Confirm`）命中的规则，单列，避免把兜底规则混进「责任人」 |
| `evaluated` / `undecidable` | 参与判定的规则数 / 条件字段本地取不到、判不了的规则数 |
| `rules_file` | `eflow_push_rules.xlsx` 的路径、条数、更新时间、下载地址 |

**三个必须知道的坑**（实测踩过，详见 `backend/services/eflow_rules/tt_rule_evidence.md`）：

1. **两份表的 `条件` 列格式不同**：级别规则是 `AND | eflow_...alarmCode in '…' (string)`
   （连接词后有 `|`），推单规则是 `AND eflow_...alarmCode in '…' (string)`（**没有 `|`**）。
   直接喂 `parse_conditions` 会得到空列表，表现为「所有推单规则都不命中」。
   `_parse_push_conditions()` 先补分隔符再复用同一解析器。
2. **本地只有 5 个字段可评估**：`alarmCode / vipSite / siteSubType / netWorkType / downSiteCount`。
   引用 `alarmName`（如 `TT自动推单给BO-MW组`）等字段的规则本地判不了，
   计入 `undecidable` 并在界面注明 —— **不能算「未命中」**。
3. **`Confirm` 步骤的规则是兜底**：`TT_push_confirm_to_close`（ID 119）几乎命中所有 TT，
   但它不决定推 WO；只有 `FOAccept` 的规则才是推单决策（与
   `tt_postmortem._analyze_dispatch_reason` 的 `target_step` 同口径）。

> 实测：`TT202609220128`（ERA 站，alarmCode 99933）命中 #203 `ERA断站推单到ZTE WO`，
> 自动处理人是 `fe_robot`、目标处理人是 `ZTE_NOC_FO`；
> `TT202609230017`（COOL 站）在 FOAccept **无**推单规则命中 → 不会自动推 WO。
> 注意 `siteSubType` 取 `eflow_tt.site_type`，为空才回退 `site_information`
> （见 `eflow_rules_matcher.build_value_frame`）—— 该单 `site_type=COOL`、`site_information=REGULAR`，
> 所以按 `COOL` 判，`Regular断站故障手动到FO`（要求 `REGULAR`）不命中。

## 14f. 这单指派给谁了 —— 指派归因（2026-09-23 新增）

返回体字段 `assignment`，报告 Markdown 落在 **§5c**，界面是 **⑤c 卡片**。
实现：`backend/services/tt_postmortem/__init__.py` 的 `_resolve_assignment()`
（建单明细解析 `_parse_create_detail()`）。

### 为什么必须单独做一节

eFlow 的"指派"不是一条规则说了算，**分三层**，只看一层会得出错误结论：

| 层 | 规则类型 / 字段 | 实际职责 |
| --- | --- | --- |
| ① 通道 | `ttDispatchRule`（`triggerStep=autoDispatch`） | **只决定走 BO 还是 FO 通道**。实测其 `targetHandlerName` / `targetHandlerId` **全为 `None`**，根本不承担"派给谁" |
| ② 建单群组池 | `ttGroupDefaultRule`（`GroupDefault_Create`） | 决定单子落进哪个**群组池**（如 `default_FO_creat rule` → `NOC_FO_101~120`） |
| ③ 环节群组 | `ttGroupConfigRule`（`GroupConfig_FOAccept` / `_FOProcess` / `_Confirm`） | 决定各环节的**候选人范围**，同样不指定个人 |

**真正落到某个人**要看 `create_detail` 的 `Assign To` / `Assignee Group`，以及
`eflow_tt.current_handler`。

### 判定要同时看 TT 层和 WO 层（2026-09-23 修正）

**只看 `eflow_tt` 会得出错误结论。** 曾经据此写下
「建单**未指派到任何人**，仅落入群组池 `G:ZTE_NOC_FO`」，用户指出 `TT202609230055` 不对：

| 层 | 字段 | TT202609230055 实测值 |
| --- | --- | --- |
| TT 建单明细 | `Assign To` / `Assignee Group` | **都是空** |
| TT | `current_handler` | `G:ZTE_NOC_FO`（群组） |
| **WO 建单明细** | `Assign To` | **`P:Festus Emmanuel(FE_MG_104),P:Kelvin Kollie(FE_FE_120)`** |
| **WO** | `current_handler` | **`P:Kelvin Kollie,P:Festus Emmanuel`** |

这单**明明已经指派到两个具体的人**，只是指派发生在 **WO 层**，
而 TT 的 `current_handler` 一直停在群组池没更新。

**取数优先级（越靠前越具体）**：
① WO 的 `current_handler` / `Assign To` 里的 `P:` → ② TT 的 `Assign To` 里的 `P:` → ③ 只有 `G:` 群组 → ④ 全空。

**前缀语义（实测）**：`P:` = Person（个人），`G:` = Group（群组）。

**必须区分两个字段**，混用会把"建单慢"误报成"没人管"：

| 字段 | 含义 |
| --- | --- |
| `create_unassigned` | **建单那一刻**是否指派到人（TT 建单明细的事实）—— 是"为什么一开始没人动"的证据 |
| `unassigned` | **最终**是否没有任何人（WO + TT 合并结果）—— 才是"这单没人管"的结论 |

200 单实测分布（**与旧结论差异巨大**）：

```
create_unassigned: True 199 / False 1     ← 建单环节几乎从不指派到人
effective_scope:   person 89 / group 19 / none 92
```

即：**建单时 199/200 未指派到人，但其中 89 单后续由 WO 指派到了具体个人**。
所以"未指派到人"这句话只能限定在**建单环节**说，不能说成"这单没人负责"。

> 连带影响：`TT202609220139` 的现场响应等待 15.81h **不是"无人接手"**，
> 而是"已指派到 Stanley Biney 但未及时出发"——两者是完全不同的问题，
> 瓶颈建议的措辞已按 `assigned_persons` 是否为空分别给出。

### 人名去重：同一个人有两种写法

WO 的 `current_handler` 是 `P:Kelvin Kollie`（只有姓名），
建单明细 `Assign To` 是 `P:Kelvin Kollie(FE_FE_120)`（姓名+工号）。
直接合并会出现「Kelvin Kollie、Kelvin Kollie(FE_FE_120)」同人重复。
`_dedup_people()` 按"去掉括号工号后的姓名"归并，保留信息更全的那份。

### 改进建议已改为「跟着瓶颈走」

`suggested_actions` 现在除了派单规则，还从**两个新来源**产出：

1. **时间瓶颈**：`time_spent.bottleneck` 超过 2 小时时，按 `phase` 给出对应建议
   （`onsite_wait` → 建"到场时限 + 超时升级/改派"；`detect` → 查告警采集/建单时延；…）。
2. **指派**：`assignment.unassigned` 为真时，指出"未指派到人"是结构性原因。

> 修正前 `TT202609220139`（瓶颈 15.81 小时）**一条建议都没有** ——
> 因为建议只跟着派单规则走，而这单的派单没问题、问题全在现场响应等待上。
> 复盘的价值就在于"最大的那块时间"能对应到一个可执行动作。

## 14g. eFlow 全流程查询（`?page=eflow_flow`）

输入**告警**（告警 ID / 告警码）或 **TT 单号**，画出该单在 eFlow 里的全流程图 ——
规则驱动的完整状态机 + 该单**实际走过**的路径高亮。与 `14e eFlow 知识库`（规则证据）、
`14f 指派归因`同属 eFlow 数据链路，规则口径三处共用一份。

- **两种图叠在一张画布上**：底图是 `ocrule_details` 的规则骨架（节点下方的"生效/总数"
  是该步骤绑定的规则条数），叠加层是该单的实际路径 —— 绿色=已走过、黄色=当前步骤
  （取 `eflow_tt.operation_type`）、粗青线=实际连线。一眼看出"走到哪一步、卡在哪"。
- **状态机主干**（`backend/services/eflow_flow.py` 的 `_FLOW_NODES`）：
  告警发生 → TT 建单 → 自动派单 → FO/BO 接单 → FO/BO 处理 → 第三方接单/处理 → 确认 → 关单，
  外加 TT 派生的 **WO 现场子流程**独立一条流水线（`wo_create`→`wo_accept`→`wo_process`→`wo_confirm`→`wo_closed`）。
- **告警 → TT 的定位**：① 告警表 `tt_id` 直连（realtime/history）；② TT 自己的 `alarm_id`
  与告警表 `id`/`aid` **归一后**比对。⚠ 后者必须归一 —— `eflow_tt.alarm_id` 存的是浮点文本
  `'1764213625912.0'`，直接与整数 `id` 比较**永远 0 行**。
- ⚠ **realtime_alarm(149 列) 与 history_alarm(173 列) 列集不同**：`alarmclearedtime` 只在
  history、`clearstatename` 只在 realtime。给两表写同一条 SELECT 会抛 `UndefinedColumn`，
  被 `except` 吞掉后表现为"关联告警永远是 0 条"。故只选两表**交集列**（同处已注明）。
- **规则挂载按工单类型分区**：TT 节点只挂 `eflow-tt` 规则、WO 节点只挂 `eflow-wo` 规则。
  两者都有 `Confirm` 这一 `triggerStep`，不区分会把 `TT_confirm` 挂到 `wo_confirm` 上。
- 接口：`GET /api/eflow-flow/query?q=&lang=`（主查询，q 支持 TT 单号/告警 ID/告警码）、
  `/graph`（仅规则骨架）、`/rules`（规则清单，可按 `wo_type`/`rule_type` 过滤，`:eflow_flow.py`）。
- 规则表由 `eflow_push_rules_collect` / `eflow_alarm_rules_collect` 每 3 天 23:59 采集，
  规则变更后流程图自动反映（每次请求按 mtime 热加载）。
- **导出 Excel**（`EflowFlow.tsx` 的 `exportFlow`，2026-09-27 新增）：查询命中后工具条出现导出按钮，
  一个工作簿最多四个 sheet —— `Nodes`（全流程节点：规则数/生效规则数/是否走过）、
  `Rules`（规则明细：未选中节点时退化为全部节点并加一列节点名）、
  `Reached`（实际经过步骤时间轴）、`Alarms`（关联告警）。空块自动跳过（如无告警则不生成 `Alarms`）。
  走 `utils/excelReport` 的 `exportReport`（多 sheet），与 `noc_analyst` 的导出同构。

## 14h. 承接方归属：ZTE 自维 vs IPT 第三方（2026-09-24 新增）

**要解决的问题**：有一类单子**根本不走 WO**，而是被推到第三方
（IPT / HUAWEI / NANOTECH / OLIB）去处理。如果和 ZTE 自维的单子混在一起看，
会得出两个错误结论：

1. **「无 WO 的比例很高」** —— 其实第三方单按设计就不建 WO；
2. **「没人处理 / 未指派」** —— 其实是派给了外部厂商，不归 NOC 管。

用户原话：「排到第三方的单子没有 WO，涉及的规则为 `mpf-outage`、
Root Alarm Code `SITE DOWN DUE TO POWER OFF(99933)`，这类要单独分开」。

### 判定：`_dispatch_owner()`（唯一真相源）

`backend/services/tt_postmortem/__init__.py`，三档递进，**越靠前越权威**：

| 档 | 判据 | 说明 |
| --- | --- | --- |
| ① | `third_accept_detail` 非空 | 第三方接单明细，实测 1369 单，**第三方一接单就有值** |
| ② | `last_processer` 以 `IPT(` 开头 | 实测 1180 单，与①100% 吻合，但**单子没关时为空** |
| ③ | `status` 含 `Third Accept`/`Third Process`，或 `current_handler`/`last_processer_group` 含厂商词 | **在途单兜底**：还没接单，①②都留不下痕迹 |

> 第③档是 2026-09-24 新加的。实测近 800 单里有 **93 单**属于
> 「已推到第三方但还没接单」（Third Accept 68 + Third Process 25），
> `current_handler` 为 `G:3rd_Power`，只靠①②会被误判成 ZTE。
>
> ⚠ 本判定**只有一个真相源**，不要再写第二套 `classify_owner()` ——
> 两个函数对同一张单给出不同归属，比没有归属更糟。

### ⚠ 不能按规则名匹配

用户提到的 `mpf-outage` 在**本地库完全查不到**（全表扫描 0 命中，
见 `TMP/_probe_ipt.py`）——它是 eFlow 侧的规则名，本地 `ocrule_details` 没有同步。
所以只能按上面的**分支/厂商特征**判定，不要试图按规则名匹配。

### 实测分布（2026-09 全月，2478 单）

```
ZTE 1260 单 / IPT 1218 单        （owner=None 与 ALL 一致）
ZTE + IPT == 全部  ✅  （2478 == 2478）
```

**IPT 单 100% 无 WO**（近 800 单抽样：`('IPT','无WO'): 388`，无一例外），
与用户描述完全吻合。真正的异常是 **ZTE 自维却没有 WO 的 93 单**——
这才是值得关注的「应派未派」，而不是笼统的 288 单「无 WO」。

用户举的两个 99933 例子正好一分为二，可直接回归：

| TT | 99933 | WO | owner | 依据 |
| --- | --- | --- | --- | --- |
| `TT202609240041` | ✓ | 无 | **IPT** | `last_processer=IPT` |
| `TT202609240044` | ✓ | `WO202609240018` | **ZTE** | — |

### 三条使用铁律

1. **下钻的 owner 必须跟概览一致**。`build_noc_tt_drilldown(owner=...)` 与
   `build_noc_analyst_report(owner=...)` 同参同口径，否则「表格里的数字」按 ZTE 统计、
   「下钻的行数」却是全部，用户会当成 bug（同 14b 节的下钻铁律）。
2. **筛选后必须校验分档可加**：`ZTE + IPT == 全部`。已加进端到端回归。
3. **界面要说明口径**：IPT 单不建 WO 是设计如此，不能显示成红色告警；
   `no_wo_zt`（ZTE 自维未建 WO）才用红色。界面文案见 `noc.ownerNote*`。

### 复盘抽屉的「Handled by」红字判据（2026-09-27 修正）

TT 复盘抽屉（`TtPostmortemPanel.tsx:693-710`）的红字
「A ZTE in-house ticket with no WO — needs attention」判据是
`report.dispatch_owner !== 'IPT' && !report.ticket?.wo_no`，
而 `ticket.wo_no` 要由 `build_tt_postmortem()` 的 `ticket` 块提供
（`backend/services/tt_postmortem/__init__.py:1357-1379`）。

**当时的缺陷**：`ticket` 块**根本没有 `wo_no` 这个键** → `!report.ticket.wo_no`
恒为真 → **已经有 WO 的正常单也被打成红色「需要关注」**。
用户报的单：`TT202609270029` 实际有 `WO202609270012`
（创建者 `NOC_FO_104`，处理人 `P:Melvin Gono,P:Festus Emmanuel`）。

同一块还有两处字段名对不上（一并修正）：

| 键 | 原来 | 问题 |
| --- | --- | --- |
| `wo_no` | 缺失 | 有 WO 的单被误报成「in-house 且无 WO —— 需要关注」（本次用户报的问题） |
| `created_time` | 写成 `create_time` | `eflow_tt` 没有 `create_time` 列（真列名 `created_time`/"Created Time"），取到永远为 None，界面「TT created」永远显示 `-` |
| `title` / `fault_duration_time` / `impacted_service` | 缺失 | 这三格在界面上永远是 `-`（列在 `eflow_tt` 里都有） |

> ⚠ **回归口径**：`ticket.wo_no` 与 `wo.wo_no` 同源，都在
> `build_tt_postmortem()` 里由 `wo_no = (wo_record or {}).get("wo_no") or t.get("wo_no")`
> 取一次（`:1329-1331`）。判「这单有没有 WO」只看这一处，
> 不要在前端另接 `dispatch_path.wo_no` 之类做兜底 —— 那会掩盖本类字段错配。
> 验证用例：`TT202609270029`（有 WO → 不出红字）；`TT202609270025` /
> `TT202609270013`（真无 WO 的 ZTE 单 → 红字仍在）。

### 「Handled by」这一格最终显示什么（2026-09-27 改）

只有分类标签答不出「到底有没有人在做」，所以按**有没有 WO** 分四种显示
（`TtPostmortemPanel.tsx`，文案键 `ttPm.owner*`）：

| 情形 | 显示 | 文案键 |
| --- | --- | --- |
| 有 WO（无论归属） | `ZTE (in-house)` / `IPT (3rd party)` + **`WO {号} 已派给 {处理人}`** | `ttPm.ownerWoDispatched` |
| 有 WO 但未指派到人 | 标签 + `WO {号} 已建单但未指派到人` | `ttPm.ownerWoUnassigned` |
| 无 WO + IPT | 标签 + 蓝字「第三方单按设计不建 WO」 | `ttPm.ownerIptNoWo` |
| 无 WO + ZTE | 标签 + **红字**「ZTE 自维单却没有 WO —— 需关注」 | `ttPm.ownerZteNoWo` |

处理人取 `assignment.assigned_persons`（WO 层解析结果，已去重且带工号）；
时间轴子视图构建失败时退回 `eflow_wo.current_handler` 原文。

### 界面落点

| 位置 | 内容 |
| --- | --- |
| NOC 操作人分析 顶部 | `Segmented`：ZTE 自派 / IPT 第三方 / 全部（默认 ZTE），并显示各档单量 |
| NOC 操作人分析 第 2 层 TT 明细 | 新增「承接方」列（可筛选）+「未派 WO」红标（**仅 ZTE 行**显示） |
| NOC 时间轴聚合 未派 WO 清单 | 告警码列悬浮显示告警名 |
| TT 复盘抽屉 | TT 信息区新增「承接方」，带悬浮显示判定依据；有 WO 时并列显示「WO 号 + 派给谁」 |
| eFlow Q&A 批量分析 | 告警码列悬浮显示告警名；命中规则列**以规则名为主**，ID/优先级进悬浮 |

### 告警名解析：`resolve_alarm_name()`

优先级：`alarm_description`（实际告警文本）→ `ALARM_CODE_SEMANTICS` 静态表 →
`fallback`（`title`）。界面原来只显示告警 ID（如 `9995.0`），
悬浮才看得出是 `MW LINK DOWN`。

> 批量分析（`tt_batch_severity._row_from_match`）里用的是**延迟导入**
> `resolve_alarm_name` —— 该模块是 `tt_postmortem` 的下游，模块级导入会成环。

## 15. IP 链路探测（`?page=ip_trace`）— iframe
`IpTrace.tsx:16` → `public/ip-trace.html`（`<title>` 为 **IP Trace & Node Detection Dashboard**），接口由内页自调：`/api/ip-trace/trace`、`/status`、`/stop`、`/analyze`。用于从服务器侧探测到目标站点的链路连通性与路径；`/stop` 说明探测是**可中断的长任务**，卡住时可以手动停。

## 16. 事件总览（`?page=incident_overview`）— iframe

`IncidentOverview.tsx:17` → `public/incident-overview.html`（`<title>` 为 **OLR Incident Dashboard**），接口 `/api/incident-overview`。数据由 `incident_overview_sync` **每小时整点**从 FineBI FTP 调度目录取最新 `incident_overview.xlsx`，以"版本化文件 + `current.json` 指针"落盘（`task_registry.py:296-301`）——这样即使上游 Excel 一直被打开占用，取数也不会失败。

## 17. 仓库看板（`?page=warehouse`）— iframe

备件/耗材库存看板（菜单 i18n key 是 `nav.sp`，HTML `<title>` 为 **OLR Spare Management Dashboard**）。`WarehouseDashboard.tsx:7-11` 说明它**完整复用** `Unified_Tools/WareHouseDashBoard/templates/index.html` 以保证与原看板"完全一样"，React 侧只用 `<iframe>` 加载 `public/warehouse-dashboard.html` 并在 `load` 事件后注入样式/DOM（:20-51）。内页调 `/api/data`、`/api/warehouses`、`/api/details`（`routers/sp_dashboard.py:25-55`）。

## 18. 数据总览（`?page=overview`）

库里有多少表、每张表多少行的**体检页**。`GET /api/db/info`（`Overview.tsx:24`），Top10 规模排名，「行数」列可排序（:151）。**没有其它按钮**——它只回答"数据在不在、大不大"。

- **导出 Excel**（`exportTables`，2026-09-27 新增）：表格卡右上角导出按钮，导的是**全部核心表**
  （过滤掉 `_` 前缀的内部表，按行数倒序），不是页面上只显示 Top10 的那两张图。
  副标题写明表数/总行数与库名，便于对账。

## 19. 表浏览器（`?page=tables`）

不写 SQL 就能翻任意表、看字段画像、导文件。**最常用的兜底工具**。

- 表下拉（:366）→ `GET /api/tables`；数据分页 `GET /api/tables/{t}/data`（:207，带取消请求）。
- **关键字搜索**防抖（:376,251）。
- **导出** xlsx / CSV（:402 → `GET /api/tables/{t}/export`，:284）。
- **列显隐 + 视图模板**：保存/套用/删除（:415,312,324 → `/api/tables/view-templates`）。同一张表经常只看固定几列时，存个模板比每次勾选快。
- **导入**（:412 → `POST /api/tables/import`，:149，`multipart/form-data`）。
- **画像页签**：字段级统计（:572 → `GET /api/tables/{t}/profile`，:273），与"数据"页签并列（:548）。

## 20. 数据上传（`?page=upload`）

拖拽 Excel/CSV 入库，并给出**数据质量评分**。

- 拖拽区（`DataUpload.tsx:69`，`accept` 见 :40）→ `POST /api/upload`（:50）。
- 上传后先看**问题面板 / 结论面板**（:101）再决定用不用这批数据。
- 历史列表可手动刷新（:144 → `GET /api/upload/history`）。

## 21. 分析归档（`?page=archive`）

历史分析结果的检索与删除，与分析仪表盘配套。

- 搜索（:187）、刷新（:193）、分页（:206 → `GET /api/analysis?search=&page=&page_size=20`）。
- 查看详情（:119 → `GET /api/analysis/{id}`）：含结论文字 + **图表快照**（:234,:246）。
- 删除需确认（:122 → `DELETE /api/analysis/{id}`）。
- **导出 Excel**（`exportList`，2026-09-27 新增）：工具条导出按钮。
  ⚠ 列表是**服务端分页**（每页 20 条），导出的是**当前页**这 20 条，
  副标题写明「第 x-y 条 / 共 N 条」与当前搜索词 —— 不要把它当成全量归档导出。

## 22. 分析仪表盘（`?page=dashboard`）

选一张表自动生成多维图表和结论，并可归档。

- 表下拉（:299）、修改分析名称（:306）、生成分析（:314）、归档（:317）。
- **联动筛选开关**（:320）：开启后点饼图/柱图即设置筛选，再点取消（:84,:328）。
- 接口：`GET /api/tables`（:37）、`POST /api/analysis`（:56 生成、:72 归档）。
- 用 `components/MetricExplain` 展示指标口径，页头同步标签来自 `useDataTimestamps`。

## 23. 系统设置（`?page=settings`）

四个页签（`Settings.tsx:11-35`，默认打开「凭据」）：

| 页签 | 组件 | 能配什么 |
| --- | --- | --- |
| 凭据 | `CredentialSettings.tsx` | 12 组上游账号：搜索（:8 区）、保存 `PUT /api/credentials`（:83）、**测试连接** `POST /api/credentials/test`（:100）、**显示明文** `GET /api/credentials/{key}/reveal`（:118）。列表默认掩码显示 |
| 邮件收件人 | `EmailRecipientsSettings.tsx` | 分组收件人名单：编辑 `PUT /api/email-recipients`（:77）、**重置为默认** `POST /api/email-recipients/reset`（:95）。`GET /api/email-recipients`（:31） |
| 远程主机 | `RemoteHostSettings.tsx` | 一个 `host` 字段：`GET`/`PUT /api/settings/remote-host`（:20,:44）+ 连通性测试 `POST /api/settings/test-connection`（:68）。**改完即时生效，无需重启**（写 `backend/data/settings.json`） |
| 任务配置 | `datasync/TaskConfigTab.tsx` | 任务的业务参数（非排程）。优先级 `环境变量 > 配置文件 > 默认值` |

> ⚠️ **容易找错位置**：「任务配置」页签在**系统设置**里，不在任务管理页。虽然它的文件在 `pages/datasync/` 目录下。

## 24. 门户一键登录（`?page=portalLogin`）

用已保存的凭据替你把上游门户登录好，省得逐个手输账号口令。

- 门户清单由后端下发：`GET /api/portals`（`PortalLogin.tsx:106`），响应体含 `client_is_local`（访问者是否就在服务器本机）。
- 登录：`POST /api/portals/login {system}`（:202）→ 轮询 `GET /api/portals/login/status?job_id=`（:128）→ 打开门户窗口。
- 关闭：`POST /api/portals/close {system}`（:213）。
- 与其他页面**共用同一份凭据**（`credential_store` 分组），不必重复填。
- 会话 cookie 会缓存到 `backend/services/auth_cache/`，等价于有效登录态——按 `05-security-and-credentials.md` 的要求对待该目录。

### 门户清单（`backend/services/portal_login_service.py::PORTALS`）

| key | 门户 | 地址 | 登录方式 |
|---|---|---|---|
| `zte_ume` / `ccn_ume` / `ipran_ume` / `mw_ume` | 各 UME 网管 | 见 `PORTALS` 默认值 | ZTE OAuth2 登录页填表（客户端模式反代 8081/8082/8083/8084） |
| `eflow` | eFlow 告警系统 | 10.100.20.8:28001 | **直接鉴权**（复刻 RSA+OAuth2 拿会话 → CDP 种 cookie） |
| `rais` | RAIS 统一权限平台 | 10.100.20.9:8766 | **直接鉴权**（AES-256-CBC 加密密码换 SSO token → CDP 种 cookie） |
| `fw_kpi` | FW 整机吞吐 UMC | 10.100.2.101:443 | 登录页填表（客户端模式反代 8085） |
| `vmax_cxo` | VMAX CXO 经营看板 | 10.123.255.12:26180 | 登录页填表（客户端模式反代 8086） |
| `ume_in` | UME iMonitor 大屏 | 172.17.208.1:28808 | 登录页填表（客户端模式反代 **8088**；同时被 `?page=imonitor` 复用） |

> 反代端口分配：**8081 ZTE UME / 8082 CCN UME / 8083 iPRAN UME / 8084 MW UME / 8085 FW UMC / 8086 VMAX CXO / 8088 UME iMonitor**。
> ⚠️ **8087 不能用**——被 ShadowBot（RPA 工具）占用且绑在回环上，`localhost:8087` 会落到它而不是 nginx。

### 两种模式

页面右上角切换，选择存在浏览器 `localStorage.myapp_portal_login_mode`：

- **客户端（默认）**：在访问者自己的浏览器里打开门户，会话落在访问者本机。非直连门户经 nginx 同源反代 + 注入 `/api/portals/inject.js` 自动填表。
- **服务器**：在 my_app 服务器桌面弹 Chrome。`eflow`/`rais` 走「直接鉴权」，**完全免手工**，直接落到已登录主页。

> **直连门户（`eflow`/`rais`）的特殊处理**（`handleLogin` 的 `localDirect` 分支）：
> 这两个门户**不能用反代**——实测经 nginx 同源反代后「能登录但告警数据全 0」
> （`All Alarms 0 / 0`，HTTP 无错，门户报 *Failed to Query Active Alarm Columns and
> Default Templates*），因为它们的前端把根地址/实时通道写死成上游绝对地址。
> 所以：
> - 访问者就在服务器本机（`/api/portals` 的 `client_is_local=true`，或页面主机名是回环）→
>   点「登录」**自动改走服务器端直接鉴权**，弹出来的窗口就在他自己桌面上（不必手动切「服务器」）；
> - 远程访问者 → 只打开上游登录页（不会填表，卡片标「已打开页面，请手动登录」），
>   要一键登录得把「登录位置」切到「服务器」。

> 实现注意（判定「已登录」）：
> 1. 不能只看 URL——RAIS 的 hash 路由切到 `#/homepage` 是瞬时的，必须等首屏真正渲染出内容
>    （`PORTALS['rais']['ready_js']`）。
> 2. eFlow 必须**等启动页真正落到门户源**再写 `localStorage.csrftoken`：Chrome 一启动
>    `DevToolsActivePort` 就有，此时页面还在 `about:blank`（origin=null），
>    `localStorage.setItem` 会抛 SecurityError → 整页渲染
>    `Your session is error. Please login again.`（窗口打开了但没登录）。
> 3. 成功判定要「正证据 + 连续两次」（`PORTAL_READY_JS` + `_SESSION_ERR_RE`）：正文 ≥120 字、
>    无会话错误文案、无可见 `input[type=password]`；只判 URL 或「innerText 非空就 break」
>    会把中间态/会话错误页误报成「已登录」。
> 4. **不能在 Chrome 启动页还 loading 时就 `Page.navigate` 改 hash**，否则会得到一个
>    `readyState=complete` 但 JS 从未执行的空白页，且不会自愈。

## 25. UME iMonitor 大屏（`?page=imonitor`）— 原版门户页面嵌入

把 UME 门户（172.17.208.1:28808）的原版监控大屏 `guard-imonitor-iui` 的
`#/screen/screen-view?screen_id=1` **原样**嵌进 myapp，并自动完成 em-portal 登录。
形态与 `vmaxCxoDashboard` 同属「原版页面嵌入」，但这个页面**必须登录**，且**不能直连上游**。

- 页面：`frontend/src/pages/ImonitorScreen.tsx`（不是 `LegacyToolFrame`——需要工具条与登录编排）
- 反代：`nginx/portal_ume_in_8088.conf`（线上生效的那份在 nginx 安装目录的 `conf/portal_ports.conf`）
- 门户注册：`portal_login_service.py` 的 `PORTALS['ume_in']` + `PROXY_PREFIXES['ume_in']`
- 凭据：`credential_store` key=`ume_in`（与客户业务 KPI 看板同一套 em-portal 账号）

### 为什么必须走反代，不能直接 iframe 上游

1. **同源才能带会话**：浏览器要带门户 Cookie 才能打开大屏，而 Cookie 只能由门户自己种；
   myapp(80) 与门户(172.17.208.1:28808) 不同源 → 既种不了也读不了。
2. **上游禁止被嵌**：上游返回 `Content-Security-Policy: frame-ancestors 'self'`，
   直接 iframe 会被浏览器拦死（Chromium 报 `Framing ... violates ... frame-ancestors 'self'`），
   页面只剩一个 chrome-error。反代必须 `proxy_hide_header Content-Security-Policy`（连 XFO/HSTS 一起摘）。
3. **上游有 frame-bust**（三处，实测确诊）：
   - 登录页内联 `if (self === top) {} else { top.location = self.location; }`
   - `login.min.js`：`top!=self&&(top.location=self.location)`
   - `security.min.js`：登录成功后 `redirectToUrl(top.location, home)`
   前两者可被 nginx `sub_filter` 改掉；三者都靠 **iframe `sandbox`（不含 `allow-top-navigation`）**
   从浏览器层封死——没有它，用户刚点过 myapp（激活窗口约 5 秒内）时登录页就可能把整个 myapp
   标签页导航走、冲掉外壳。**两处都要保留，别只留一处。**

### 登录时序（首次访问自动发生）

```
iframe 载入大屏 → SPA 调 /api/guard-imonitor-service/v1/largescreen/screen?_id=1
→ 401 → SPA 自己跳到 /api/oauth2/v1/authorize?redirect_uri=/iui/guard-imonitor-iui/
→ 注入脚本(/api/portals/inject.js?system=ume_in)填表并提交，同时 postMessage 通知宿主
→ login_rsa 200 → 门户把浏览器送到 redirect_uri 的根路径（hash 必丢）
→ 宿主收到 postMessage 后等 3s 把 iframe 重指回 #/screen/screen-view?screen_id=1
```

实测：3.0s 出 401 → 3.0s 提交登录 → 6.1s 大屏接口 200 并出图。

⚠️ 最后一步不能省：门户登录成功只回落到 `redirect_uri` 根路径，`#/screen/screen-view?screen_id=1`
这段 hash 路由在跳转中必然丢失。这也是 `build_inject_js` 里那条 `myapp-portal-autologin`
postMessage 的唯一用途。自愈循环上限 4 次（`MAX_AUTO_RELOGIN`），工具条手动「刷新/重新登录」会重新武装。

### 其它注意

- 自动刷新：本页登记在 `AR_SOFT_REFRESH_PAGES`，顶栏到点时外壳广播 `myapp-refresh`、
  由页面在 iframe 内原地重载（跨端口 iframe 重挂载会整页闪白）。
- 端口号有**三处**必须一致：页面 `PORTAL_PORT` / `PROXY_PREFIXES['ume_in']` / nginx conf。
  `tests/test_imonitor_screen.py` 会离线核对这三处。
- Cookie 按**主机**共享、不分端口，所以门户 Cookie 名带端口后缀（`Z-AUTH-CODE-28808` 等）。
  同主机的 `ccn_ume`（10.121.1.2:28808，反代 8082）与 `ume_in`（172.17.208.1:28808，反代 8088）
  Cookie 名**相同**，两个门户不要在同一浏览器里同时登录。
- 离线测试：`python tests/test_imonitor_screen.py`（不连门户、不起浏览器）。

## 26. SP 备件 / 耗材汇总报表（`?page=sp_report` / `?page=com_report`）

同一条代码路径服务两个页面，只是 `kind` 不同（`spareparts` / `consumables`）：
页面包装 `SpReport.tsx` / `ComReport.tsx` → 共用 `SpReportBase.tsx`，
后端 `backend/routers/sp_report.py` → `backend/services/sp_report_service.py`。

数据源是任务 `sp_report_generate`（每天 05:15）产出的汇总工作簿
`data/sp_email/<前缀> <时间戳>.xlsx`，与邮件/WhatsApp 发出去的是**同一份文件**，
页面不做二次加工（口径说明由接口 `notes` 原样透传，见
`backend/services/sp_report_service.py` 顶部 docstring）。

工作簿五张 sheet：`Summary-Current`（汇总）/ `Summary-Changed`（每日矩阵）/
`Inbound` / `Outbound` / `Inventory`。前两张走 `/summary`，其余三张走
`/rows`（分页 + 筛选 + 排序）。

### Summary 表的 Outbound 拆分（2026-09-24 新增）

`Summary-Current` 在 `Outbound Qty` 右侧新增两列（由**生成端**产出，不是页面算的，
口径见 `backend/services/sp_report_gen/README.md` 与 `gernarate_sp_report.build_summary`）：

| 列 | 口径 |
| --- | --- |
| `Outbound Repair Qty` | 出库明细中 `Outbound Type = 'Repair Outbound'`（报修出库）的 `Outbound Qty` 合计 |
| `Outbound Site Qty` | `Outbound Qty` − `Outbound Repair Qty` |

**`Outbound Site Qty` + `Outbound Repair Qty` ≡ `Outbound Qty` 恒成立**：
Site 列用减法而非再筛一类，所以上游日后新增 Outbound Type（当前有 Install / Borrow /
Others / Inventory Lost / Repair 五种）或出现空白值，都会自动落到 Site 列。

> ⚠️ 与补库消耗口径**不同**，别混：`Avg Monthly Consumption` 还额外剔除了两张异常单据
> （`REPLENISH_EXCLUDE_ORDERS`）与 Repair Outbound，而 `Outbound Qty` 及本次拆出的
> 两列都是**未剔除的原值**。

⚠️ 这两列只在**重新生成报表后**才出现（`sp_report_generate` 每天 05:15）。
页面侧按表头名动态读列，**无需改代码**。

> **Summary 表默认只显示 8 列**（2026-09-24 起，用户要求精简）：
> `Material Name` / `Domain` / `Inbound Qty` / `Outbound Site Qty` / `Inventory Qty` /
> `Safety Stock` / `Replenishment Qty` / `Alert Level`。
> 默认**隐藏**这 5 列：`Outbound Qty`、`Outbound Repair Qty`、`Difference`、
> `Avg Monthly Consumption`、`Remark` —— 它们在「显示列」里仍可勾回来，
> 行详情弹窗也始终显示全列。
> 注意 `Outbound Qty` 与 `Outbound Repair Qty` 是一对（Site + Repair = Outbound），
> 默认一并隐藏；`Outbound Site Qty` 保留显示。

### 界面的三段结构

统计卡片（汇总 KPI + 补库告警，**点告警卡即筛选**）→ 分表卡片（点即切表）→
明细数据卡片（Segmented 切 5 张表）。`Summary-Changed` 渲染成「天 × 仓库」矩阵，
不走 `/rows`，也就没有分页与列控制（`SpReportBase.tsx:784` 的分支）。

### 显示列可自定义（每个分表各记一套）

「明细数据」卡片筛选条上的**显示列**按钮打开 `components/ColumnPicker.tsx`：

- 列的可选集是**后端真实返回的 `columns`**，不是页面写死的清单 —— 上游报表增删列会自动跟上；
- 页面默认列见 `SpReportBase.tsx` 的 `DISPLAY_COLUMNS`（按 sheet 声明"优先展示"，
  实际存在的才显示；全都对不上时退回全列，避免空表）。
  **Summary 表的默认列表 2026-09-24 起精简为 8 列**，`Outbound Qty` /
  `Outbound Repair Qty` / `Difference` / `Avg Monthly Consumption` / `Remark` 默认隐藏
  （原因见上一节）；
- 选择按 **kind + sheet** 存 `localStorage`（key 前缀 `myapp_sp_report_cols_v1`），
  刷新和重开都还在；读回时会按当前真实列集过滤，上游改了列名不会渲染成空表；
- **勾满全部列 = 未自定义**，会清掉存储，这样报表以后新增列能自动带上；
- 「恢复默认」按钮回到 `DISPLAY_COLUMNS`；行详情弹窗始终显示全部列，不受此处影响。
- ⚠️ **改默认列不会影响已自定义过的用户**：存储 key 前缀是 `myapp_sp_report_cols_v1`，
  没动版本号（2026-09-24 调整 Summary 默认列时刻意不升 `v2`）——
  之前手动改过列的人维持自己的选择，从没改过的人（大多数）自动采用新默认。
  想统一到新默认，点一次「恢复默认」即可。

> 列偏好只在浏览器本地，不落库 —— 换机器/换浏览器不跟随，这是有意的：
> 它是个人的视图偏好，不是业务配置，不该走 `/api` 与数据库。

### 分页

明细表默认**每页 20 行**（`DEFAULT_PAGE_SIZE`，`SpReportBase.tsx` 顶部常量），
分页器可切 20 / 50 / 100 / 200 —— 用户切页大小会同步改后端 `page_size` 请求参数。
导出不受分页影响：`exportCurrent` 另取一次 `page_size = min(total, 5000)` 拉全量。

### 排障

- 页面整体 404 → 工作簿不存在，按提示先跑 `sp_report_generate`；
- 有表头无数据 / 部分 sheet 空 → 看接口返回的 `warnings`（页面顶部橙色告警条原样显示）；
- 页面与 Excel 数字对不上，先看 `notes` 里的口径说明，再查
  `backend/services/sp_report_service.py`，**不要**在页面层改口径。

## 27. CR 变更分析（`?page=cr_analysis`）—— 按 change_category 看计划与完成（2026-09-25 新增）

数据源 `eflow_cr`（eFlow 同步的动态建表），回答一个问题：**各类变更计划排了多少、
实际执行了多少、其中多少按时**。

- 后端路由：`backend/routers/cr_analysis.py`（3 个只读端点）
- **口径层（唯一真相源）**：`backend/services/cr_caliber.py` —— 表名、时间字段、
  终态词表、按时/延期判定、窗口规整、`bucket_expr()`、`base_where()` 全在这里
- 服务层：`backend/services/cr_analysis_service.py`（拼聚合与下钻 SQL）
- 前端页面：`frontend/src/pages/CrChangeAnalysis.tsx`
- 前端配套：`frontend/src/pages/crAnalysis/` 下 `crTypes.ts`（类型/常量/纯函数）、
  `crCharts.ts`（ECharts option）、`crColumns.tsx`（表格列定义）、
  `CrDrillModal.tsx`（明细弹窗）

> 📁 **模块划分说明**：本页初版把后端口径与取数、前端页面与图表都写在单文件里，
> 分别达到 535 / 897 行，超过 `AGENTS.md` 第三节 2 的「单文件不超过 500 行」。
> 2026-09-25 按单一职责拆成上述模块：**后端把「口径」与「取数」分开**
> （口径是最需要单独审视、也最容易被改坏的部分），**前端把「编排取数」与
> 「图表/列/弹窗」分开**。拆分后各文件 87~468 行，行为与拆分前逐位一致
> （63 对 category 下钻、33 对 sub_category、9 对 month 全部复测通过）。

### 口径（改口径只改 `cr_caliber.py` 一处）

时间字段用 **`request_registration_time`**（CR 登记时间），不是 `planned_start_time` ——
计划时间会被改期，拿它做窗口会让同一个 CR 在不同月份重复出现。
实测 247 行该字段 100% 非空且长度全为 19，字典序即时间序，可直接做字符串比较
（PG / SQLite 双模一致）。

四个核心计数（`cr_caliber.py` 的 `bucket_expr()`，概览与下钻**共用这一份**）：

| 计数 | 判定 |
| --- | --- |
| 已排期 `planned` | `planned_start_time` 非空 |
| 已执行 `executed` | `actual_start_time` 非空 |
| 未执行 `unexecuted` | 排了期但实际开始为空 |
| 按时 `on_time` / 延期 `delayed` | 实际开始 `<=` / `>` 计划开始 |

三个比率：

- **计划达成率** = `executed ÷ planned`（用 planned 做分母：没排期的谈不上"达成"）
- **按时执行率** = `on_time ÷ executed`（⚠️ 分母是**已执行**，不是全部 CR。
  分母为 0 时后端返回 `null`，界面渲染 `—` —— 不是 `0`）
- **关闭率** = `closed ÷ total`

终态：`Closed`。CR 另有 `Canceled` 也是终态（与 `routers/portal_qc.py:102` 的
`_CR_OPEN` 约定一致），实测本表当前没有 Canceled，仍单列一类以避免上游将来出现时口径漂移。

### 全量下钻（AGENTS.md 第三节 1b 的硬要求）

页面上**每个数字都可点**：8 个 KPI 卡、类别表格的每一格、子类别表格、堆叠柱状图的柱子、
按时率环、月度趋势柱 —— 全部落到明细弹窗。

保证"卡片数字 == 明细行数"的三个机制：

1. `build_overview` 与 `build_drilldown` **共用** `cr_caliber.base_where()` 与
   `cr_caliber.bucket_expr()`（前者用于 `SUM(CASE ...)`，后者直接当 `WHERE` 谓词）；
2. 类别用 `=` 精确匹配，不用 `LIKE`；
3. 取样上限 `MAX_DETAIL_ROWS = 5000` 显著大于单页最大 200 行，截断时
   返回 `truncated=True` + `meta.warnings`，界面显示黄色告警条。

> **已验证**：每个类别 × 9 个 metric（共 63 对）+ 汇总级 9 对，
> 卡片数字与下钻行数全部一致；子类别 33 对、月份 9 对同样全部一致；
> 且 `sum(rows)` 与 `summary` 逐字段相等。（2026-09-25 实测）

### 一个真实踩坑：SQL 别名与 Python 字段名不一致

首版把 `SUM(CASE ...) AS open_cnt` 写进 SQL，但 Python 侧的字段累加元组写的是 `"open"`，
于是概览里 `open` 恒为 0，而下钻（走 `WHERE` 谓词、不经过别名）返回 38 ——
**下钻把概览的 bug 暴露了出来**。这正是"概览与下钻口径必须一致"这条规则的价值：
两者不一致时，先怀疑口径，不要先怀疑用户。

### 已知数据特征（影响观感，不是 bug）

- 默认窗口取**全表实际范围**（`get_filters()` 的 `min_time`），不是"今天往前 30 天" ——
  实测全表仅 247 行、跨度 2026-01-02 ~ 2026-09-09，30 天窗口会几乎空白；
- `planned_start_time` 100% 非空，故「已排期」恒等于「变更总量」，这是数据特征而非口径错误；
- 按时执行率整体很低（3.2%），因为多数 CR 的实际开始时间晚于计划开始时刻（常见于
  计划填 `00:00:00`、实际当天上午执行）。**这是真实业务现象**，页面照实呈现。


## 28. PM 执行分析（`?page=pm_analysis`）—— 按 PM 计划看完成与超期（2026-09-25 新增）

数据源 `eflow_pm`（eFlow 同步的动态建表），回答一个问题：**各 PM 计划（预防性维护
工单 PMT）执行到哪一步、多少超期、卡在谁那里**。

- 后端路由：`backend/routers/pm_analysis.py`（3 个只读端点）
- **口径层（唯一真相源）**：`backend/services/pm_caliber.py` —— 表名、时间字段、
  终态、超期判定、真实流程顺序、窗口规整、`bucket_expr()`、`base_where()` 全在这里
- 服务层：`backend/services/pm_analysis_service.py`（拼聚合与下钻 SQL）
- 前端页面：`frontend/src/pages/PmExecutionAnalysis.tsx`
- 前端配套：`frontend/src/pages/pmAnalysis/` 下 `pmTypes.ts`、`pmCharts.ts`、
  `pmColumns.tsx`、`PmDrillModal.tsx`

> 📁 **模块划分**：与第 27 节的 CR 页**同构**（口径层 / 取数层 / 页面 / 四件套），
> 照搬已经过验证的结构，不另起一套。各文件 87~470 行，均在 500 行以内。

### ⚠️ 字段名有误导性（本节最重要的一条）

`eflow_pm` 的流程时间字段**按名字猜顺序会全错**。实测 694 条含完整链条的记录，
真实时序 100% 是：

```
created_time → last_create_time → last_schedule_time → last_accept_time
  → last_pm_manager_approve_time → last_process_time → last_flm_leader_approve_time → Closed
```

关键反直觉点（`pm_caliber.py` 的模块 docstring 已记录）：

- `last_accept_time` **早于** `last_process_time`（1233/1233 成立）——
  "Accept" 是受理/签收，不是"验收"；
- `last_flm_leader_approve_time` **最晚**（707/707 晚于 `last_process_time`）——
  FLM 领导审批是**收尾**环节，不是流程起点；
- `last_process_time` 与 `last_pm_manager_approve_time` 实测同时刻。

所以页面的「流程推进情况」漏斗按**上述真实时序**渲染
（`pmTypes.ts` 的 `STEP_KEYS` 数组顺序即真实时序），**不要**改成字段名字母序。

### 口径（改口径只改 `pm_caliber.py` 一处）

时间字段用 **`created_time`**（工单生成时间），不是任务窗口
`current_task_start_time` —— 任务窗口会被改期，拿它做窗口会让同一工单
在窗口移动时反复进出统计。实测 `created_time` 100% 非空、长度全为 19，
字典序即时间序，PG / SQLite 双模可直接字符串比较。

核心计数（`bucket_expr()`，概览与下钻**共用这一份**）：

| 计数 | 判定 |
| --- | --- |
| 已完成 `closed` | `status = 'Closed'` |
| 未完成 `open` | `status <> 'Closed'`（含 5 种等待态） |
| 已超期 `overdue` | 源表 `pmt_overdue = 'Yes'` |
| 未超期 `on_time` | 源表 `pmt_overdue <> 'Yes'` |
| 未开始 `not_started` | `CAST(completed_items AS INTEGER) = 0` |
| 完成但超期 `closed_overdue` | `closed AND overdue` |
| 未完成且超期 `open_overdue` | `open AND overdue` **← 真正压着的，优先看** |

三个比率：

- **工单关闭率** = `closed ÷ total`
- **超期率** = `overdue ÷ total`（递增为差，界面用 `rateColorDesc()` 反向染色）
- **已启动率** = `(total - not_started) ÷ total`

分母为 0 时后端返回 `null`，界面渲染 `—` —— 不是 `0`。

**超期为什么直接用源表标记而不自己按日期算**：实测两种定义并不等价 ——
`pmt_overdue='Yes'` 有 701 条，而"任务窗口已过且未 Closed"有 855 条。
上游的标记还含时区与工作日历修正，自己按 `current_task_end_time` 比会与上游口径漂移。
语义上它表示"**未在任务窗口内完成**"：已完成却标 Yes 的 229 条，其
`last_accept_time` 都远晚于 `current_task_end_time`（属事后补录/迟交）。

### 全量下钻（AGENTS.md 第三节 1b 的硬要求）

页面上**每个数字都可点**：8 个 KPI 卡、3 个比率卡、计划堆叠柱、超期环、状态饼、
月度趋势柱、流程漏斗（无下钻，仅展示）、超期站点条形图、计划表格每一格、站点表格每一格。

保证"卡片数字 == 明细行数"的三个机制（与 CR 页同款）：

1. `build_overview` 与 `build_drilldown` **共用** `pm_caliber.base_where()` 与
   `bucket_expr()`（前者用于 `SUM(CASE ...)`，后者直接当 `WHERE` 谓词）；
2. 维度用 `=` 精确匹配，不用 `LIKE`；月份用 `>= / <` 前缀范围而不是 `LIKE`
   （`LIKE` 必须把通配符放进参数值，而 PG 包装层会转义 `%`）；
3. 取样上限 `MAX_DETAIL_ROWS = 5000` 显著大于单页最大 200 行，截断时
   返回 `truncated=True` + `meta.warnings`，界面显示黄色告警条。

> **已验证**（2026-09-25 实测）：27 个 PM 计划 × 9 个 metric（共 243 对）+
> 6 个状态 × 2、6 个月 × 3、20 个站点 × 3 全部一致；`sum(rows)` 与 `summary`
> 逐字段相等；三条口径恒等式（`overdue == closed_overdue + open_overdue`、
> `total == closed + open`、`open == open_overdue + open_on_time`）均成立。

### 计划号筛选（2026-09-25 修订）

「PM 计划执行明细」卡片右上角提供 **PM Plan No. 多选筛选**（可搜索、可清空）。
选中的计划号经 `rows` 的 `useMemo` 过滤后，**同时驱动表格、小计行与「各 PM 计划的
完成情况」堆叠柱**（三者共用 `rows`），所以筛选后三者口径始终一致。

三条设计约束（改这块前先读）：

- **选项来源是后端 `filters.pmp_nos`**（`get_filters()` 从全表取，按工单量倒序），
  不是只列前 8 个 —— 27 个计划号都要能筛到。**不在前端重排**：顺序即业务优先级。
- **筛选是前端过滤，不下推给 `/overview`**。因此「工单状态分布」「月度趋势」
  「流程漏斗」「超期站点」四块仍显示**全量**（`pm.chart.status.hint` 已写明
  "全量，不随计划筛选变化"）；若要一致，需要给后端加 `pmp_no` 参数并让
  `build_overview` 的每个聚合都带上，属于口径变更而非展示调整。
- **上限 `MAX_ACTIVE_PLANS = 30`**，超限保留前 30 个并弹黄色告警条
  （`pm.filter.planNoMax`）——**不静默丢弃**。空态另分两句话术：窗口内无数据
  （`pm.empty`）vs 有数据但被筛没（`pm.empty.filtered`），避免用户误去放宽时间范围。

> 原实现是 `Tag.CheckableTag` 平铺前 8 个计划号，计划号有 27 个时其余筛不到，
> 且标签占满标题行；2026-09-25 换为上述下拉控件。

### 计划号归一后二次合并

`''` 与 `NULL` 在 `GROUP BY` 里是两类（PG 中 NULL 自成一类），归一到兜底名
`(无计划号)` 后可能出现两行同名。不合并会让同一计划出现两行，且比率各用各自分母算，
与下钻（按归一后名字精确匹配）对不上。故 `_shape_plan_rows()` 归一后**再合并一次**
再算比率，`sites` 取最大值而不是相加（避免站点数虚高）。

### 已知数据特征（影响观感，不是 bug）

- 默认窗口取**全表实际范围**（`get_filters()` 的 `min_time`）——
  实测全表 1632 行、跨度 2025-11-29 ~ 2026-07-28（`created_time`），
  比"今天往前 300 天"更早，故 `get_filters()` 会把窗口撑到实际起点；
- `service_classification` 与 `source` 全表只有一个值（`AC` / `Created by System`），
  **不可作为维度**，页面未使用；
- 模板分布高度集中：1495/1632 是同一个模板（`Solar, RAN, EHS, Vsat, Microwave, IPRAN, DWAR`），
  故未把 `template` 做成主维度；`site_name` 有 775 个，站点下拉取超期最多的前 60 个；
- 条目完成度合计 172496 / 215607 = 80.0%，但分布两极：134/134（1176 条）与
  0/134（288 条），故「未开始」是比"平均完成度"更有信息量的口径；
- 超期率按状态差异极大：Wait Process 96.7%、Wait Accept 90.2%、Closed 31.2%、
  Wait FLM Leader Approve 26.4% —— **等待中的工单比已完成的超期率更高**，
  说明卡点在审批环节，这正是「流程推进情况」漏斗存在的意义。


## 29. FineBI 原生看板（`?page=finebi_<slug>`，共 17 个）

由通用引擎 `frontend/src/pages/NativeBoard.tsx` 渲染，看板定义（含每条 SQL）来自
`backend/services/native_catalog.py` 的 `BY_SLUG`，数据经 `GET /api/native-boards/{slug}`
取本机派生库或远端只读 SQL API。迁移背景见 `docs/FINEBI_MIGRATION.md`。

### 29a. MTTR 看板（`?page=finebi_mttr`）—— 日/周/月 页签（2026-09-27 改造）

**改了什么**：
- **删除** 4 个组件：`MTTR`（月总量）、`MTTR Weekly`（周总量）、`MTTR_Range`、`MTTR Distribution Month`；
- **新增** 12 个组件：P1~P4 × 日/周/月，**同一指标按粒度分页签**，每行 2 图；
- 保留 `update`（页头最新数据时间）与 `TT Details` 明细表。

**页签怎么来的**：组件 id 用 `<前缀>_<粒度>` 命名（`mttr_p1_day` / `_week` / `_month`），
`NativeBoard.tsx` 的 `BOARD_LAYOUT.mttr.tabs` 按后缀归组。非页签看板走原平铺路径，
`tabs` 为空即行为不变 —— 改造只影响 `mttr` 一个看板。

**粒度口径**（三档同源，`native_catalog.py` 的 mttr 段）：

| 页签 | 分组列 | 实测桶数 |
| --- | --- | --- |
| 日 | `substr("Alarm Occur Time",1,10)` | 228~272 |
| 周 | `WK`（`YEAR-Www`，周一起） | 40 |
| 月 | `Month`（= `LEFT("Alarm Occur Time",7)`） | 10 |

**⚠ 口径变更（重要）**：MTTR 由 `MAX("MTTR2")` 改为 **`AVG("MTTR2")`**。
原 SQL 取的是「当期最长的那一单」，与 MTTR（平均修复时长）的字面定义不符；
2026-09-27 按业务确认改为均值。**因此本页数字与 FineBI 原版及历史截图不再一致**，
对账时以本页为准。

**筛选口径**（12 张图完全一致，只有粒度与级别不同）：
`Ticket Severity IN (P1,P2,P3,P4)` AND `Month` 非空且非 `NaT`/`nan`
AND `Site ID != 'VMAX-DC'` AND `MTTR2 >= 0.25`。每张图两列：
`Records`（该桶该级别计入均值的单量）+ `MTTR2`（均值，单位小时）。

**已验证**：日/周/月三档在时间窗口下均可过滤（`mttr_*_day` 的 `date_field` 自动识别为 `d`）；
窗口 2026-08 下日粒度返回 22~31 桶。改完**需重启后端**才生效 ——
目录在导入期加载，uvicorn 未开 `--reload`（见 `13-operations.md`）。



