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

## 3. 实时告警看板（`?page=alarm`）

全网当前告警的综合视图，深空蓝底 + 数字可下钻（`AlarmDashboard.tsx:1-2`）。

- 概览指标 `GET /api/alarm-dashboard/overview`（经 `cache.ts` 缓存，:133）。
- **点任意数字弹出下钻表**（`DraggableClickModal`），历史口径走 `/history-drilldown?metric=&limit=500`，实时口径走 `/realtime-drilldown?dimension=&value=&limit=500`（:158-163）。下钻表可搜索。
- 与其他看板不同：这里的"实时"来自 `eflow_active_alarm`（每 30 分钟）写入的数据，**不是秒级推送**。

## 4. TT&WO 看板（`?page=ttwo`）

故障工单（TT）与工作单（WO）的处理量、时效、积压趋势。

- 筛选：下拉 + `Segmented` + 日期区间（`TTWODashboard.tsx` 引入 Select/Segmented/DatePicker）。
- 接口：`GET /api/tt-wo-dashboard/overview`（缓存，:125）、`GET /api/tt-wo-dashboard/drilldown`（:156）。
- 页头显示"最近同步/是否已同步"（`useDataTimestamps`，:16,77）。
- 数据来自 `eflow_sync`（每小时 :22）与每日全量兜底 `eflow_sync_full`（01:00）。

## 5. NUR 看板（`?page=nur`）

网络不可用率（NUR）的日/周/月趋势与站点达标情况。口径见 `01-overview.md` 术语表。

- 粒度切换 `daily|weekly|monthly`（`NurDashboard.tsx:29-30`）、日期区间、多维下拉（`GET /api/nur/options`，:421）。
- 主数据 `GET /api/nur/overview`（:411）；点数字下钻明细表 `GET /api/nur/detail`（:448），下钻表带列内筛选与排序（`strSorter`/`getUniqueFilters`，:17-27）。
- **导出**：`DownloadOutlined` + `xlsx` 直接在前端导出当前明细。
- 表格与趋势图复用同一套"项目统一下钻规范"，与 TT&WO / MS SLA 三页保持一致。

## 6. MS Operation KPI 看板（`?page=ms_sla`）

MS 合同 KPI（Contract KPIs）与工单 SLA（WOs SLA）达成情况。

- 一次请求拿全部：`getMsSlaOverview()` → `GET /api/ms-sla-dashboard/overview`（`frontend/src/api.ts:17-18`），返回 NUR / SLA / Network KPI / Per-Site / WO SLA + 数据新鲜度 meta（`backend/routers/ms_sla_dashboard.py:7-8`）。
- 粒度只有 `daily|monthly`（`MsSlaDashboard.tsx:29`）；返回结构是"**指标为行、期间为列**"，与 NUR 页的表格对齐（`ms_sla_dashboard.py:10-11`）。
- 下钻复用 `GET /api/nur/detail`（:447）。
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

- **区域**下拉（:329）、**图层 Tag** 点击开关（:370）、**图例点击隐藏**该类图层（:426）、拓扑线与区域面 `Switch`（:357,:361）、时间 `Segmented` + 自定义区间（:397）、高级筛选与清除（:481,:491）。
- **点站点 → 右侧抽屉**（:647，组件 `pages/gismap/SiteDrilldownDrawer.tsx`）四个页签，可搜索、可导 Excel。
- 接口：`/api/gis/sites` 与 `/api/gis/realtime/sites`（:73 按模式二选一）、`/api/gis/topology`（:94）、`/api/gis/region-boundaries`（:101）、`/api/gis/drilldown/{site_id}` 与 `/api/gis/realtime/drilldown/{site_id}`（:111）。均走 `cache.ts` 缓存。
- 地图控件在 `pages/gismap/MapController.tsx`。
- **区分两页的口径**：实时告警地图带红色"实时"Tag（`GISMap.tsx:421`），数据来自 `eflow_active_alarm`（每 30 分钟）；普通 GIS 页走历史/工单口径。
- 页头同样消费 `useDataTimestamps`（:11,43）显示同步状态。

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
- 操作：`Switch` 控制是否包含 OK 站点（`include_ok`，:249）、Popover 显示口径说明、下钻 `GET /api/packet-loss-dashboard/drilldown?status=&limit=800`（:273）、拓扑叠加复用 `GET /api/gis/topology`（:222）。
- 接口：`/api/packet-loss-dashboard/overview`、`/map-sites`、`/drilldown`。
- 数据由 `packet_loss_sync`（06:30）写入 `lte_pl.sqlite3`。

## 14. 电池看板（`?page=battery`）

站点电池健康度 / SOC / 充放电状态。

- **第一维度是"数据新鲜度"**：实测约一半电池读数超过 7 天（最老到 2024 年），因此所有均值/状态/低电量指标**默认只统计 ≤24h 的新鲜子集**——不过滤时"放电中"338 块，过滤后真实值只有 24 块（`BatteryDashboard.tsx:4-8`）。看数字前先确认新鲜度开关。
- 健康度几乎无方差（98~100 占 99%），所以主视图用"健康度分级 + 无数据占比"而不是直方图（:8）。
- 接口：`GET /api/battery-dashboard/all`、`/trend?days=`（:161-162）、单站下钻 `/api/battery-dashboard/site/{site}`（:315）。
- 数据由 `battery_kpi_sync` 每小时 :05 写入 `data/battery/battery_kpi.sqlite3`。

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

### 界面落点

| 位置 | 内容 |
| --- | --- |
| NOC 操作人分析 顶部 | `Segmented`：ZTE 自派 / IPT 第三方 / 全部（默认 ZTE），并显示各档单量 |
| NOC 操作人分析 第 2 层 TT 明细 | 新增「承接方」列（可筛选）+「未派 WO」红标（**仅 ZTE 行**显示） |
| NOC 时间轴聚合 未派 WO 清单 | 告警码列悬浮显示告警名 |
| TT 复盘抽屉 | TT 信息区新增「承接方」，带悬浮显示判定依据 |
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
页面侧按表头名动态读列，**无需改代码**；`SpReportBase.tsx` 的
`DISPLAY_COLUMNS['Summary-Current']` 已把两列列入默认显示列。

### 界面的三段结构

统计卡片（汇总 KPI + 补库告警，**点告警卡即筛选**）→ 分表卡片（点即切表）→
明细数据卡片（Segmented 切 5 张表）。`Summary-Changed` 渲染成「天 × 仓库」矩阵，
不走 `/rows`，也就没有分页与列控制（`SpReportBase.tsx:784` 的分支）。

### 显示列可自定义（每个分表各记一套）

「明细数据」卡片筛选条上的**显示列**按钮打开 `components/ColumnPicker.tsx`：

- 列的可选集是**后端真实返回的 `columns`**，不是页面写死的清单 —— 上游报表增删列会自动跟上；
- 页面默认列见 `SpReportBase.tsx` 的 `DISPLAY_COLUMNS`（按 sheet 声明"优先展示"，
  实际存在的才显示；全都对不上时退回全列，避免空表）；
- 选择按 **kind + sheet** 存 `localStorage`（key 前缀 `myapp_sp_report_cols_v1`），
  刷新和重开都还在；读回时会按当前真实列集过滤，上游改了列名不会渲染成空表；
- **勾满全部列 = 未自定义**，会清掉存储，这样报表以后新增列能自动带上；
- 「恢复默认」按钮回到 `DISPLAY_COLUMNS`；行详情弹窗始终显示全部列，不受此处影响。

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

