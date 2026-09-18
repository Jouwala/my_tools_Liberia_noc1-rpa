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
- 各页独立刷新按钮（:350 / :377 / :407）；行内下载（:231 / :277 / :472）。
- eFlow 规则页有**「立即执行」**（:404 → `POST /api/tasks/eflow_tt_rules_check/run`），点击后 3 秒做一次刷新（:157，**不是轮询**，任务慢时得手动再点刷新）。
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
