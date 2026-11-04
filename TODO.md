# 03 TODO.md —— 当前任务、优先级和开发进度

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> **本文只放"当前在办"的少数几项。** 历史清单与已完成规划**不进本文**——那些看 `git log`、
> `Task\my_app\PROJECT_DOCS.md`（历史档案）以及各子系统手册。

## 一、进度快照

| 系统 | 状态 |
| --- | --- |
| 统一门户 | **活跃开发中**。近期连续 6 次提交集中在门户：QC 看板改版、MS KPI/SP 报表、UME 大屏接口、FME 工程师排名、GIS 站点下钻、QC 弹窗拖拽、静态资源补全 |
| my_app | 运行中（后端 7038 + 多 worker + 看门狗）。近期以稳定性与数据正确性为主 |
| 门户后端 / 鉴权 | 已通过「用户管理」验收（见 `vite.config.ts_bak_20260920_用户管理已验收`），鉴权开关机制已落地 |
| FineBI 迁移 | 进行中。门户内 FineBI 条目仍有**目录占位链接**待替换 |
| SQLite → PostgreSQL 迁移 | **规划定稿，未执行**（`PROJECT_DOCS.md` §2）。执行前提见下 |
| 商用就绪度整改 | 有专项结论文档，未全部闭环（见 `MsPortal 商用就绪度检测 —— 结论与整改方案.md`） |

## 二、当前在办（按优先级）

### P0 —— 阻塞使用者，优先处理

- [ ] **替换门户内的 FineBI 占位链接。** 现状部分报表仍是目录占位（标签"链接待更新"、状态 beta），用户点了到不了实际报表。需在门户「编辑看板配置」逐条替换。（`README.md` 已明示此状态）
- [ ] **QC 面板改版的验收闭环。** 卡片改版（左侧状态竖条、纯白底、数字居中、标题/副行左对齐）已提交，需确认线上两档刷新节奏（全量 `:06:30` / 告警每 5 分钟）与失败态展示符合预期，并核对 `MsPortal\QC面板展示优化建议_20260922.md` 中的建议项是否已全部落地或明确不做。
- [ ] **商用就绪度整改项收口。** 按 `MsPortal 商用就绪度检测 —— 结论与整改方案.md` 逐条确认状态。

### P1 —— 数据正确性与稳定性

- [ ] **站点可用率取数改走本地 PG（2026-10-15，已定性、待观察上游）。** 站点可用率已从远端 UME HTTP（`192.168.100.19:8765`）改为**本地 PG 优先、远端回退**，代码在 `Task\my_app\backend\services\site_availability_service.py`（`PG_SPEC` / `_load_pg_tech` / `_load_tech`，快照 `..._bak_20261015_PG双模前`）。
  - **2G / 3G 两源等价**：重叠键 100% 一致、零值差异；且 PG 严格超集（另有 47 个站点在 `master_site_db` 里但远端查不到 —— 切换后这些站从"空白"变为有数据）。同时去掉对 .19 HTTP API 的运行时依赖。
  - **4G 已定性（2026-10-15 实测 UME 直查）**：用 MS SLA 的 FDD 模板对 2026-10 整月直查 UME 自身（`10.100.28.27:28001`）当裁判，5342 条：
    - 只切换 `indexfillingtype`（`default` vs `zeroDenominator`）→ **5342/5342 逐行完全相同**，故**该设置不是差异根因**（原假设已证伪）。
    - **UME == PG = 99.4%**（排除最新一天的同步滞后后达 **99.9%**，仅 4 条残差）；**UME == 远端 = 85.8%**，且排除最新几天后仍卡在 ~86%。
    - **结论：PG 就是 UME 的值，4G 走 PG 正确，无需回退远端。** 远端 `4G_Main_Kpi_Site_Daily`（`FDD_KPIs_ZTE_OLR_FB` 模板 + `layer: Sites`）的 4G 可用率**系统性偏高约 14%**，是独立的上游数据质量问题。
  **待办**：把"远端 4G 可用率偏高约 14%"作为**上游数据问题**反馈（本条不再阻塞本站点可用率看板）；`docs\manual\` 的站点可用率口径说明如需同步为"PG 与 UME 一致"，一并更新。**观察点**：PG 的 4G 当天值有增量同步滞后（当天可能尚未吸收终值，如 `2026-10-14` 有 27 条残差），看板若要求当天实时终值需另评估。
- [ ] **P1 告警推送加 ext 通道 fallback（2026-10-08）。** Baileys 主通道失败（群名解析不到 JID / 凭据过期 / WhatsApp 流控 428）时，自动把同一批 `messages` 投到 `data/tt_alert_job.json`，由已登录的 WhatsApp Web 扩展兜底。改动已落到 `Task\my_app\backend\services\tt_alarm_whatsapp_service.py`（新增 `try_ext_fallback`、在两个失败分支调用） + 4 条 stub 用例 + `architecture.md` 8.x ADR；**待验证**：① 重启 `m` 组 worker 后第一次跑 0 候选 → 任务历史页面要能看到新字段 `ext_fallback` 为空（`attempted: false`）；② 手动制造一次 Baileys 失败（把 `GROUPS` 临时改成一个不存在的群名跑一次）→ ext 通道应兜住（前提：Chrome 开着 + 扩展已登录）→ `out.success=True` + `warnings` 含"兜住 N/M 单"。**回滚手段**：revert 三个文件即可。
- [ ] **数据层裸连接治理（前置调研，非立即改造）。** 运行期已知存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`（如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488`），是**图表数据源**，改造会静默坏图。当前动作：**不再新增**裸连接，并把已有点位登记成清单。
- [ ] **`eflow_tt` 双库归属固化。** 明确"同步只写 `app.db`、`eflow.sqlite3` 副本仅作只读快照"，避免后续有人读错库。结论已在 `PROJECT_DOCS.md` §2 Phase 0.5 闭环，待落到代码注释与手册。
- [ ] **五个关键进程的巡检常态化。** 确认 worker 分组 + 双看门狗在异常退出后确实自愈（步骤见 `docs\manual\13-operations.md`）。

### P2 —— 体验与工程规范

- [ ] **数字悬浮说明铺开（2026-11-03 立，规则见 `Task\my_app\AGENTS.md` 三.3c / 根 `AGENTS.md` 四.10b）。**
      新约定：收起的 `CalcChainNote`（这页整体怎么算）之外，**每个数字还要能悬浮问到「这个数怎么算」**
      （列头/标题用 `MetricExplain::ExplainIcon`，数字本身用 `ExplainPopover` 列出该格构成）。
      **实测盘子**（`Task\my_app\frontend\src\pages\*.tsx`，72 个顶层文件，2026-11-03 数）：
      iframe 页 11 个（`LegacyToolFrame`，数字不在我们 DOM 里 → **不适用**）；
      非 iframe 61 个里已用 `CalcChainNote` 或 `MetricExplain` 的 14 个、两者都没用的 47 个；
      **`ExplainPopover`（数字本身）全站只有 2 页有** —— `PacketLossDashboard`（自写气泡，5 处）与
      `AvailCounty`（本次新接）。即「列头级」缺口约 47 页，「数字级」缺口约 59 页。
      61 个文件里还含 `AvailTrend.tsx` / `MsKpiShared.tsx` / `SpReportBase.tsx` 这类**共用组件与基类**
      （改一处覆盖多页，优先级应高于逐页铺）。
      **已完成**：`avail_county`（三层：KPI 卡 ⓘ + 三制式列头 ⓘ + 每个可用率数字的该格构成气泡，
      下钻弹窗列头一并加），提交 `f71ccccb`，实机中英两套文案与四层气泡均已验证。
      **批① 可用率族已完成（未提交）**：`avail_ms` + `avail_flm` —— 矩阵每个数字的
      `Tooltip title=` 原生提示换成 `ExplainPopover`（分子/分母 + 站点-日加权语义 + 环比），
      三张矩阵卡标题、4 张制式卡、3 张区域卡、未匹配占比卡各挂 ⓘ；两页共用一份文案
      `frontend/src/pages/availSumRatio.ts` + i18n `availSum.*`（同口径不许各写一份）。
      分子/分母语义实测确认（日档 681/717、周档 1363/1435 ≈ ×2 → 分母是**站点-日**观测数）。
      实机验证：`avail_ms` 气泡显示 `分子 681 / 分母 717`、`avail_flm` 显示 `分子 262 / 分母 268`，
      与 `/api/avail-ms/matrix` 同格逐位相同。
      **批④ 第一页已完成（未提交）**：`site_avail` —— 顶部 6 项统计与「月均 / 最低 / 未达标天 / 周」列头挂 ⓘ，
      数字本身挂气泡；原生 `Tooltip title=` 全部换掉（`minDayTip` 删除），实测表头 12 个 ⓘ、顶部 6 个 ⓘ。
      顺手在气泡里说清两处坑：顶部三个数是**按搜索过滤后的站点集现算**（非后端全量），
      「未达标天」与月均气泡共用同一个 `belowDaysOf()`（阈值前端可调），刻意不用后端 `days_below` 以免打架。
      **批② MS SLA / NUR 族已完成**：`ms_sla` + `ms_sla_only`（`c762c263`）、`nur` + `ms_nur_only`（`5d1225b7`）、
      `ms_wo_sla` + `ms_contract_kpi`（`5d1225b7` 共用组件 + `403dd9e8` 两页各自概览卡）。
      **批③ TT / WO 族已完成**：`ttwo`（含 `tt` / `wo` / `v1_ttwo` 切片，同一组件自动同享）、`eflow_flow`、
      `noc_analyst`、`repeat_site_down`。要点：`renderStatCards()` 加第 7 个入参 `cellNote` 并把大数字与占比包
      `ExplainPopover`；标题旁三个汇总徽标从 `Tooltip title=` 换成统一气泡；`StatCard` 新增 `explainText`
      （只包数字、不包标题，避免与 ⓘ 叠两个气泡）；`eflow_flow` 从零说明补齐（ⓘ + 数字气泡 + `CalcChainNote` 四段 +
      节点 tooltip 补判据）；`noc_analyst` 六张卡 + Top3/Bottom3 数字条补齐，并把「三人均值的算术平均 vs 合并口径」
      的差异与 `_mismatch_of` 豁免永不命中**写进气泡而不是藏起来**；`repeat_site_down` 一排硬编码英文表头补进中英字典、
      `counting_rule` 原生 Tooltip 迁 `CalcChainNote`、`malformed_time_rows` 改常驻告警。
      实机验证（内嵌浏览器 `evaluate_script` 悬浮，7090 直连）：`repeat_site_down` 卡 3076 / 450 / 318 / 峰值 2026-10-15(186)
      与单元格「132 次 / 9 个自然日」逐条对上；`eflow_flow` 搜 `TT202611030074` 出「4 / 11 步、规则 143 条、命中 33 条」；
      `ttwo` P1 卡出「13 ÷ 3,683 = 0.4% + Unknown 剔除说明」；`noc_analyst` 出「93.3% 等权平均」「99.2% 合并口径」。
      本批另核实三处「注释/帮助与实现不符」并登记在规格文档 ③ 可疑点 15~17（**未改数字**）。
      **下一批（④）剩**：`ran_cells_kpi` / `cn_kpi` / `cn_kpi_5mins` / `ume_in_kpi` / `alarm`（ⓘ 已有，缺数字级）。
      **批④ 告警 / RAN / CN 族已完成**：`ran_cells_kpi`（月度卡 ⓘ + 数字气泡含实际数据源；矩阵 7 行行头 ⓘ + 单元格气泡；
      删掉 `title={t('rck.drillHint')}` 原生提示）、`cn_kpi`（此前**既无口径条也无任何 ⓘ**，现补组件卡 ⓘ + 页头单值卡气泡 +
      四段 `CalcChainNote`；气泡直接把后端下发的 `sql` 原文给出来可复制核对）、
      `cn_kpi_5mins`（11 个组件按 id 逐条字面量映射聚合式 SUM/AVG、RG 拆分、15 分钟档稀疏点；vs 昨日 ±% 明说**前端现算**；
      页头三枚标签补齐）、`ume_in_kpi`（概览七卡从 `Tooltip title=` 换统一气泡 + 资源日均/峰值气泡）、
      `alarm`（该页 8 卡 3 图的 ⓘ 早已存在，本次只补数字级：区域画像条数、各类型条数、类型 Top 卡标题 ⓘ）。
      ⚠ **本批推翻了调研规格里两条「重点可疑」**：`ume_in_kpi` 不是「概览 = N 天窗口累计」，恰恰相反 ——
      每张卡只聚**最新一天**（`agg(latest_rows)`），概览是把这些最新一天的值相加，而页面标签写着「近 30 天」；
      `alarm` 的「市电柱」其实是 `transmission_type == "MW"`（字段名叫 `region_mains_count`，命名与判据不一致）。
      两条都已按代码写进界面并登记在规格文档 ④ 可疑点 1~6（**均未改数字**）。
      实机验证：`ran_cells_kpi` 月度卡出「3 个有效日等权平均 96.96% / 观测 9,882 / 名册 3,296 / 物化库 source」且单元格 3100+196=3296 自洽；
      `cn_kpi` 组件气泡出「32 行 × 2 列 / 粒度日 / SQL 原文」；`cn_kpi_5mins` xGW License 出「AVG 非加权非峰值 + 15 分钟档」；
      `ume_in_kpi` 出「最新一天 2026-11-03，不是窗口累计」；`alarm` 区域出「4 条 / MW 1 条 / 站点 3 个」。
      **下一批（⑤）剩**：`SpReportBase`（一处覆盖 `sp_report` + `com_report`）、`SpDetailsReport`、`SpMaterialSummary`、
      `WarehouseSummary`、`BpReport`、`CrChangeAnalysis`、`PmExecutionAnalysis`；`WarehouseDashboard` 是 iframe 豁免。
      **批⑤ 已完成五页（2026-11-04）**：`sp_report` + `com_report`（一处覆盖两页）、`sp_details`、`warehouse_summary`、
      `cr_analysis`。**并修掉一个显示错数字的缺陷**（用户批准）：`_overlay_db_open_counts` 文档写「只对备件生效」、
      代码没有 kind 判断 → `com_report` 的「未关闭单」被**备件库表**覆盖（实测 `?kind=consumables` 的 Outbound=15 全是备件的）。
      加 `if normalize_kind(kind) != "spareparts": return` 后离线对拍 `spareparts 17+source=db / consumables 1 回到 Excel`，
      `tests/test_sp_open_count_caliber.py` 19 项全过；**线上 7038 未重启，重启由用户执行**。
      两处「要后端补字段才合规」的前端重算**当时**保留原样、只在气泡直说，随后用户批准「要动后端」已全部清掉：
      ① `warehouse_summary.urgent` 改取接口既有字段 `overview.urgent`（后端在 Summary-Current **全表**上按
      Alert Level 等值计数，`sp_report_service.py:609`），实测两条路径都等于 **62**、数字未变；
      ② `cr_analysis` 整块 KPI 收到后端 —— `cr_caliber.base_where(..., categories=…)` 用
      `TRIM(COALESCE(col,'')) IN (?,?,…)`（值走占位符），`build_overview` / `build_drilldown` 共用同一谓词，
      前端直接用 `ov.summary`、比率不再复制；离线对拍选两类时**逐项相等**（136/136/89/47/3/86/96/40，
      比率 65.4/3.4/70.6）。同批 `noc_analyst` 两张卡也改为后端下发 `deviation_total` / `missing_total`
      并把 `_TIMELINE_CACHE_VERSION` 6 → 7。⚠ **三处后端改动都要重启 7038 才生效，重启由用户执行。**
      **批⑤ 收尾三页已完成（2026-11-04）**：`sp_material`（单元格气泡 + 列头 ⓘ，常驻口径条迁 `CalcChainNote`、
      「消耗为负」告警保持常驻；下钻弹窗合计判定为**合法客户端聚合**不必动后端，气泡写明筛过的行数与全量行数）、
      `bp_report`（占比列头 ⓘ + 每格气泡；重点讲清 `avg_ratio = AVG(bp_ratio)` 是**各期等权平均**、
      不是 ΣBP ÷ Σ全网，气泡把两个数并列作对照）、`pm_analysis`（8 张计数卡 + 3 张比率卡全接，
      「总数」卡单拆 `pm.tip.countTotal` 以免读成「自己占自己」；`pmt_overdue` **直接采用源表判定、页面不推算**
      这条写进 ⓘ）。实机验证：`sp_material` 1st WH 期初 771 与「期初 − 当前」消耗构成对上；
      `pm_analysis` 总数卡出「= 接口 summary 的 total = 2458」、超期 ⓘ 出 `UPPER(TRIM(pmt_overdue))='YES'`；
      `bp_report` 平均占比气泡出对照句式（该区间当前无数据，三项均为 `—`，正是「取不到显示 —、不当 0」）。
      **⑤ 族全部做完**；`warehouse_dashboard` 是 iframe 豁免。下一批 ⑥：`BmSpeedtest` / `BmMeta` /
      `BatteryDashboard` / `FmeRanking` / `GISMap` / `Dashboard` / `Overview` 补数字级。
      **⑥ 先做机器盘点再动手**（`App.tsx` 的 `VALID_PAGES` 65 − `PAGE_LIST` 里 `iframe:true` 12 = 53 个自研页，
      ①—⑤ 覆盖 30 个 key，剩 23 个），盘子与分组写进规格文档 ⑥ 一节，别再凭记忆数列。
      **批⑥a 已完成五页（2026-11-04）**：`bm_speedtest`、`bm_meta`、`packet_loss`、`dashboard`、`overview`。
      实机验证（内嵌浏览器悬浮）：`bm_speedtest` KPI 出「49 行等权平均 / 1,432 次 / min 16.34 max 987.25」、
      评分出「100.0 vs 58.6 + 权重 35/20/30/15 + 相对分不是绝对水平」、胜率出「33/48 = 68.8%」、
      月度格出「2026-08 该月 25 个日点的日均值再平均」；`bm_meta` 评分出「12.38 vs 14.04 → 88.2」（公式逐位对上）、
      BP 卡出「9.56%，最小 4.42 / 最大 16.50，取自 323 行 + 比率后端已 ×100」、结论卡出「279/322 = 86.6% + 平局 1 天」；
      `overview` 核心表数出「前端数出不以 _ 开头的表 / PG 下 = 表总数（实测 115 = 115）」；
      `dashboard` 12 个 ⓘ、页头出「LIMIT 10000 样本口径」。
      **顺带改掉三处「解释本身是错的」**（都不动数字）：
      ① `bmm.hint.bp` 中英两份都写「BP 比率越大越好」，而 caliber 判据 `kind:'lower'` —— BP 是劣化小区占比，**越小越好**；
      这段文字同时出现在网络卡、趋势下方与导出表头，此前用户在三个地方读到反的解释。
      ② `overview.explain.totalTables` 写「排除 `_` 开头的表」—— 实际只排 `sqlite_%`，`_` 前缀仍在总数里；
      `overview.explain.coreTables` 写「排除分析/归档表」—— 卡片只滤 `_` 前缀，那两个是 Top10 那一步才排除的。
      ③ `PacketLossDashboard` 有两份**自写气泡**（`MetricExplainPopover` + 卡内联 `Popover`，各自一套复制按钮/主题/强调渲染），
      已删除并统一走 `components/MetricExplain`。
      另修两处显示层问题：`bm_speedtest` 的测试/设备卡原 `?? 0`（区间无记录时把「没测」显示成 0）改按 `days` 判空显示 `—`；
      `BmMeta` 下钻 `String(drillMeta.limit)` 缺字段时显示 `undefined`，改 `?? '—'`。
      **⑥a 还剩两页被业务决定卡住（本轮已停手，等用户点头）**：`battery` 的 8 张 KPI 卡 + 五种分布 + 告警计数
      全是前端重算（`BatteryDashboard.tsx:224-297`），而接口 `/all` 已下发 `kpi`/`dist`/`alarm_summary` **整块未用**
      （`battery_dashboard.py:292-350`）；`fme_ranking` 的卡片名次也是前端重排（`FmeRanking.tsx:227-244,778-809`），
      且 **`wo_rank` 方向与后端相反**（后端 `fme_ranking_service.py:257-262` 升序、#1=工单最少；前端降序标 #1，
      与表列 `wo_rank` 自相矛盾）。这两处「改用后端字段」会**改变界面显示的数字**（还含均值保留位数 1 位 vs 2 位），
      属业务口径决定，按第五节第 3 条停下来问用户，不擅自统一。
      **分批计划**（每批一个数据族，共用组件优先；每批都要 `npm run build` + 实机悬浮验证 + 手册/站内帮助同步）：
      ① 可用率族 `AvailMs` / `AvailFlm` / 共用 `AvailTrend`（与已完成的 avail_county 同一套口径，最先做）；
      ② MS SLA / NUR 族（`MsSlaDashboard` / `MsSlaOnly` / `MsNurOnly` / `NurDashboard` / `MsWoSLReport` / `MsContractKpiReport`）；
      ③ TT/WO 族（`TTDashboard` / `WODashboard` / `TTWODashboard` / `V1TTWODashboard` / `EflowFlow` / `NocAnalyst` / `RepeatSiteDown`）；
      ④ 告警与 RAN 族（`AlarmDashboard` / `SiteAvailability` / `RanCellsKpi` / `CnKpi` / `CnKpi5mins` / `UmeInKpi`）；
      ⑤ 报表族（`Sp*Report` / `ComReport` / `BpReport` / `Warehouse*` / `CrChangeAnalysis` / `PmExecutionAnalysis`）；
      ⑥ 其余（`BmSpeedtest` / `BmMeta` / `BatteryDashboard` / `FmeRanking` / `GISMap` / `Dashboard` / `Overview` 补数字级）。
      **不做**：设置/凭据/上传/帮助/登录等无数字页（约 14 个，见上表 note=icon=pop=0 的 Settings 类）。
      **实施规格已固化**：`Task\my_app\docs\number-explain-rollout-spec-2026-11-03.md`
      —— ②③④⑤ 四批共 28 页的「数字清单 / 后端算法与 `文件:行号` 证据 / 已有说明 / 可疑点」全部写好，
      后续会话照该文档实施即可，**不必重做调研**（四份调研实读后端代码，成本约 1700 万 token）。
      该文档同时登记了调研顺手挖出的**实现级问题**（不是文案缺口）：前端重算违反三.3c 的 5 处
      （CrChangeAnalysis 整块 KPI、WarehouseSummary 的 urgent、SpMaterialSummary 弹窗合计、
      NocAnalyst 两张卡、MsWoSL 卡片颜色判达标）、`NocAnalyst._mismatch_of` 大小写不匹配导致
      **豁免永不命中**（错位率偏高）、`ms_sla`/`nur` 的 DCR 列颜色方向错（越小越好却按 ≥0.95 判绿）、
      `RepeatSiteDown` 整页标题硬编码英文无 i18n 键、`sp_dashboard._db_exists()` 在 PG 模式下
      静默返回 0、手册 `11-feature-guide.md:392` 把 MTTR 的 43200 **分钟**写成秒。
      这些改的是**数字本身**，属业务口径决定，已列在文档「可疑点」，**未擅自修改**。
      **每条口径文字必须从后端聚合代码核实**，不得照抄手册 —— 本条立项时就抓到手册与
      `avail_county_aggregate.summary_by_tech()` 相反（手册写「不是县等权平均」，实测逐位相等），
      该错误已随 `f71ccccb` 更正。

- [x] **`PersonMapView.tsx` 拆分收尾（2026-10-24 立，同日完成）。** 县标签（2026-10-23）与「默认站点」
      辖区模式（2026-10-24）两次迭代把它从 ~495 行推到 714 行。已完成拆分（714 → **489 行**，行为不变）：
      `personmap/useCountyTags.ts`（新，114 行：COUNTY_PALETTE / 填充透明度 / TRM·CAT 常量表 /
      typeCountsLine / 县→类别色与两行统计文本派生）、`personPinHtml.ts`（新，97 行：人员针图标拼装，
      悬停不进图表的实测契约随文件头搬走）、`CountyLabels.tsx`（新，91 行：县名标签避让 effect + 渲染 +
      countyLabelPane）、`SitesLayer.tsx`（新，56 行：站点圆点与提示，siteColor 由调用方传入与连线共用）、
      `TerritoryToggle.tsx`（新，38 行：开关浮层）；`NoSitesNote.tsx` 新增 `MapNoSitesNote`
      （底部居中定位外壳），抽屉仍用裸 `NoSitesNote`，文案两处同源。
      验证：`npm run build`（check-i18n + tsc + vite build）通过；无头浏览器三态实测 ——
      县标签 15 个三行齐全、开关默认关且打开后 overlay path 15→1849、点针开抽屉 + 选中变红、
      取消选中/点地图空白/抽屉 × 三条清除路径符合手册 11a、控制台零错误；手册 11a 文件指针已同步。
      **未提交**：工作区有他人在途改动（EmailReports / GISMap / 凭据等），提交需择干净窗口、只提 personmap 相关文件。
- [ ] **地图页「点别处取消选中」还剩两处未收口（2026-10-21 立）。** `?page=person` 已修
      （`Task\my_app\frontend\src\useClearOnOutsideClick.ts`，实测点 KPI 卡/表格/筛选条/页面背景均取消、
      点抽屉内部与表格行不误取消）。盘点其余带地图的页面后剩两处：
  1. **`?page=gis` / `?page=realtime_alarm` 的人员图层。** `gismap/PersonnelLayer.tsx:187-220` 的
     `clearSelection` 只挂在 `map.on('click')` 上，所以选中人后点右侧卡片/表格，
     人员高亮与路线仍挂着 —— 与 person 页改前同一症状。接同一个 hook 即可。
     **刻意没顺手改**：`pages/GISMap.tsx` 当时有他人 **1069 行未提交改动**在途，叠上去容易被旧缓冲回滚。
  2. **两个 MW 遗留静态壳。** `frontend/public/mw_ume_topology.html`（节点点击高亮在 `:1463` 的
     marker `on('click')`，非 map 级）与 `mw_real_time.html`（`:1753` 同构），
     选中链路/节点后点地图空白不清，只有关抽屉（`#drawer-mask` / × / Esc）才清。
     属 iframe 里的原生 JS，不在 React 体系内，要各自加 `leafMap.on('click')`。
     **刻意没顺手改**：`mw_real_time.html` 同样有他人在途改动，且这类壳由 nginx 直接 alias 发布、
     改错会直接影响线上页。
  附带结论（不用改）：`DraggableClickModal` 点遮罩不关闭是**刻意设计**（该文件第 5 行注释「避免误触」）；
  `GISMap` 的 `selectedSite` 虽无清除路径，但它只当抽屉取数的键、**地图上没有任何渲染依赖它**，
  不构成可见的卡死选中。

- [ ] **主开关「跳过手动停止」的后续项（2026-10-21 立）。** 功能与根因修复已落地
      （`task_runner.toggle_all_tasks` 双向跳过 `manually_stopped=1`；
      `tools/fix_task_schedule_dupes.py` 修掉 SQLite 缺主键导致 146 行的漂移）。
      遗留：
  1. **旋转那批明文口令（需仓库外动作，2026-10-21 已查清分布）。**
     黑名单共 17 条（`tests/test_engineering_guards.py::_KNOWN_SECRETS`），对应 17 个凭据组
     （`zte_ume`/`mw_ume`/`rais`/`ccn_ume`/`ipran_ume`/`fw_kpi`/`mail_126`/`sftp_sp`/
     `owa_mail`/`weixin`×2/`eflow`/`fms_portal`/`ume_in`/`vmax_cxo`/`vmax_gbase` 等）。
     **分布（按文件区分后核实，2026-10-21 修正过一次误判）**：
     - **全部 17 条都明文存放在黑名单文件自身**（`tests/test_engineering_guards.py`
       的 `_KNOWN_SECRETS` 元组）—— 该文件自 `b8a4c0c3` 起就已入库，
       此前 12 条、`a30045ba` 补到 17 条，**历次提交都把全量口令带进了历史**。
     - **另有 3 条**（`zte_ume`/`ccn_ume`/`ipran_ume`）在黑名单之外也出现过：
       `docs/manual/13-operations.md` 与 `frontend/public/manual.html`，
       涉及提交 `b54ceed3` / `7c86e0d2`（`manual.html` 的残留已于 `20c3469e` 清除）。
     - 其余 14 条**未在黑名单之外的文件里出现过**。
     ⚠️ **轮换范围是 17 条全部，不止那 3 条** —— 黑名单文件本身就是一条明文泄露通道。
     源码与文档已清、守卫已拦「再写回」（2026-10-21 另补了 `.html` 后缀，
     堵住 `manual.html` 这类生成产物的盲区）。但**进过历史的口令只能轮换才算消除**，
     需拉运维在 UME / 各凭据后台改密，属仓库外的动作。
     （仓库为**私有**，外部暴露风险有限；但私有库同样不该存明文口令。）
  2. **`MASTER_SWITCH_EXEMPT_IDS` 与 `manually_stopped` 的语义分层**：`whatsapp_send_ext`
     已于 2026-10-21 移出豁免名单（改由「用户手动关 + 主开关不覆盖」保证单通道）。
     若日后仍需「按业务长期钉死关闭」这一类，应新增独立的 `master_switch_pinned_off`
     概念，而不是把 ID 塞回豁免名单 —— 豁免（不参与主开关）与「参与但被用户手动关住」
     是两种意图，混用会再次出现 2026-10-20「关不掉 / 又自己跑起来」那类症状。
  3. **`task_schedule_config` 双库无自动同步**：本表靠约定人工保持 SQLite 与 PG 一致
     （`tools/sync_manual_stop_to_pg.py` 补 `manually_stopped`）。是否要加自动同步或
     干脆二选一，待定。
  4. ~~**重启 7038 才会加载**~~ → **已于 2026-10-21 重启并验证**：豁免名单只剩
     `whatsapp_send_baileys`，三个目标任务运行态均为 `manually_stopped=True`；
     OFF→ON 完整往返后「启用集合」与「手动停止集合」与基线**完全一致**。
- [ ] **后端 `logger.info` 此前一条都没落盘（2026-10-21 已修，需持续观察）。**
      `backend/main.py` 从未配置根 logger（`root.handlers == []`、level=WARNING），
      Python 的 `logging.lastResort` 只兜 WARNING 及以上，**INFO 全被静默丢弃** ——
      `task_runner` 里 14 处 `logger.info` 全是死的（写代码的人以为留了痕，实际没有）。
      已在 `backend/main.py:25-56` 给 root 挂 `StreamHandler(stdout)`，级别 INFO
      （可用 `MY_APP_LOG_LEVEL` 覆盖）。**观察点**：① INFO 级别下日志量上升，
      `backend_runtime_<日期>.log` 单文件上限 100MB 自动切分，确认 `log/` 不会爆；
      ② `force=True` 是否与 uvicorn 自己的 handler 打架导致**重复输出**
      （当前实测无重复，uvicorn 访问日志仍只出现一次）。

- [ ] **7038 找个空闲时段重启，让 TT 快速分析的两项已落盘改动生效（2026-10-19 立，10-20 补充）。**
  1. **结论卡片正文还是旧文案** —— `> The AI model was unavailable…` 加末行
     `*Model failure reason: 程序化先行（/tt-ai-fast）…*`。磁盘代码是干净的（离线渲染已确认会输出
     `No model is involved` / `无模型参与`），旧文案只来自进程内的旧字节码。
  2. **`provider` 已从 `openwebui` 改成 `both`**（写在 `Task\my_app\backend\services\ai_model_config.json`），
     但 `ai_model_config._cached` 是进程内缓存，所以 `GET /api/ai-model-settings/chain` 仍回 `openwebui`。
     改这一项的原因：Open WebUI（.27，0.12.0）启用了 trusted-header SSO，邮箱密码登录被服务端**永久**关死
     （带真实账密试遍 11 个头名 + 3 组双头全是同一个 400，明细见 `Task\my_app\backend\services\openwebui_client.md`），
     而 `provider=openwebui` 时候选链里只有云端一档、本地 WorkBuddy 档根本不进链，一次 400 就整条失败；
     `both` 让 WorkBuddy 先进链（实测在线、一次对话约 2 秒）。
     **执行**（PowerShell 不支持 `&&`，逐行跑）：
     `netstat -ano | Select-String ':7038\s'` 取 PID → `Stop-Process -Id <PID> -Force`（`backend_watchdog` 数秒内自动拉起）。
     **自查**：
     `(Invoke-RestMethod "http://127.0.0.1:7038/api/eflow-qa/tt-ai-fast?tt=TT202610190094&lang=en").ai.conclusion | Select-String 'No model is involved'` 要命中；
     `(Invoke-RestMethod "http://127.0.0.1:7038/api/ai-model-settings/chain").provider` 要是 `both`。
     **回滚**：把该 json 里的 provider 改回 `openwebui`（文件不入库，只在本机生效）。
     界面不受这两项影响：`?page=eflow_qa` 已只调 `/tt-ai-fast`，线上包 `index-BQiCP-wf.js` 里查不到 `/tt-ai`；
     回归守卫 `tests\test_engineering_guards.py::test_tt_quick_analysis_is_programmatic_only` 已就位（1 passed）。

- [ ] **本 8 份文档体系的落地与首轮校验。** 根目录、门户 `docs\`、`Task\my_app\` 三处已建立；待办：确认三处文件名一致、互链可达，并把索引页接进门户导航。
- [ ] **门户移动端体验复查。** 二维码扫码要求同网段 WiFi，需确认现场网络条件下可用。
- [ ] **根目录过程产物清理。** 根目录残留大量 `tmp_qc*.txt`（76 个）、`_*` 探针与切片文件，属一次性产物。历史教训见 `7b1d33b`（98 个探针脚本误入库）。**清理前先确认无脚本引用。**
  > 2026-09-30 复核并扩范围：实测三处都有，`development.md` 自检 ⑥ 已给出可直接跑的命令与基线。
  > 根目录 78 个 / 359KB（其中 `tmp_qc*` 76 个，与上面一致）；`Task\my_app\` 根目录 4 个
  > （`_p.py` `_s.py` `_slice1.txt` `_tmp_view.txt` —— 落在 venv 根，正是第四节第 7 条禁止的位置）；
  > `Task\my_app\log\` 另有 7 个 `_probe_*.txt` / `_procs*.txt`（09-13/09-16）。门户侧已归零。
  > 计数时**必须排除** `Lib\site-packages\`（numpy/playwright 自己的 `_*` 模块 700+ 个）和
  > `backend\services\_playwright_utils.py`、`src\pages\_TemplatePage.tsx` 这类带下划线的真源码，
  > 否则数字全是假的。按既有约定同盘挪进 `_quarantine_*/`，不做删除。

- [ ] **版本库整洁收口（2026-09-30）。** 本条已提交为独立 chore 提交 `3eaecdb3`（只提索引，没夹带任何在途功能改动），保留在此是为了对照下一次的验收数字。
  1. **39 个运行时文件已退跟踪。** 明细：12 个 SQLite 边车（`Task\RAN\*`、`Task\ip_ran\`、`ticket_export_rpa\` 的 `.sqlite3-shm/-wal`）、`Task\my_app\backend\services\battary_kpi_fetch\output_socket\.email_send.lock`、门户 `scripts\whatsapp_analysis\reports\` 的 26 份日报。忽略规则同时补好（根 `.gitignore` 的 `*.sqlite3-shm/wal` + `*-journal`，门户 `.gitignore` 的 `scripts/whatsapp_analysis/reports/`），**磁盘一个文件都没删**（边车与 27 份报告仍在原位）。教训见 `development.md` 自检 ⑦：本会话第一次做完就被并发会话的 `git reset` 复原过一次，所以**只动索引的改动必须当次提交掉**。
     验收标准（`3eaecdb3` 之后）：`git ls-files -i -c --exclude-standard` 总数应 = **32**（全是真源码基线，一条都不许动），`_myapp_trash_20260913` 与 `git ls-files` 里的 `sqlite3-shm/wal`、`.email_send.lock`、`whatsapp_analysis/reports/` 均为 0；索引总文件数 **1498**。
  2. **`_myapp_trash_20260913` 的 3419 条跟踪 —— 已 `git rm --cached -r` 并随 `3eaecdb3` 提交，HEAD 里现在为 0。** 内容实测 3378 个在 `B_portal_profiles\`（Chrome profile 的 woff/ttf、`.tflite`、`.pb`），其余 41 个是 `A_root_junk`/`B_tmp`/`B_outputs` 的转储，没有一个是源码。退跟踪后索引从 4917 降到 **1498**，磁盘 21253 个文件原样不动（该路径是 09-25 建的符号链接，指向 `_quarantine_20260925\_myapp_trash_20260913`，**链接本身要留着** —— 它让历史记忆里记录的还原路径继续可解析）。⚠️ 顺序教训（本次验证过）：必须先 `git rm --cached -r`，再动这个链接；反了的话 git 会把它当普通目录，3419 条变成工作区删除噪声。
  3. **`Task\_fe_dist` 剪枝 —— 2026-09-30 已清完「月龄 ≥ 8 天」那一档，剩下两档待做。** 首次执行挪走 2741 个孤儿 chunk / 61.9MB 到 `_quarantine_20260930\fe_dist_stale\`（同盘 `rename`，**一个都没删**；清单 `_MANIFEST.tsv`、说明与还原命令 `_RESTORE.md`）。产物目录 12955 → **10214** 个文件、336 → **269 MB**。复跑审计在用集不变（14 HTML / 79 可达 chunk），14 个在用页面与入口引用的 7 个资源逐个 200，git 零影响（`_fe_dist/` 与 `/_quarantine_*/` 本来都在忽略清单里）。脚本已升级出 `--apply` / `--min-age-days` / `--dest`，默认仍是只读 dry-run，登记在 `development.md` 的可复用脚本表。
     ⚠️ 该目录是**线上服务目录**（7090 由 vite preview 读它，`nginx.conf` 里没有它的 alias），只能同盘挪、不能删；`emptyOutDir:false` 是实测约束（安全删除钩子会中断 vite 的 `prepare-out-dir`），**不许**改成 true —— 所以这件事**要周期性重跑，不会自己好**。剩余不可达 **10074 个 / 224.2MB**（0-1 天 4017、2-7 天 5991）。下一轮 `--min-age-days=2` 之前注意两点：a) 阈值参数拿不到默认值会变成 NaN，而 `age >= NaN` 恒假 → 候选归零（失败方向是安全的，但会让人误以为清过了；本次实测踩过，脚本已加显式校验）；b) 0-1 天那批里混着**当天正在被人验证的构建**，清它等于赌没人持有旧 `index.html` 的缓存，要挑没人看页面的时段做。
- [ ] **开源许可合规收尾（2026-09-28 核查后的剩余项）。** 已完成：`react-leaflet`（Hippocratic-2.1，非 OSI）连同 `@react-leaflet/core` 一并移除，改为 `Task\my_app\frontend\src\components\LeafletMap.tsx` 的原生 leaflet 封装；`@google/genai`（未使用）与 `@turf/*`（无依赖方）清理；`requirements.lock.txt` 补齐 8 个声明却缺失的运行时依赖。剩余：
  1. `Task\my_app\docs\THIRD-PARTY-NOTICES.md` 需补全 Apache-2.0 / MIT 的署名与许可全文义务，并核对 `xlsx`（SheetJS CDN 版）、`psycopg2-binary`（LGPL，动态链接）两项的表述；
  2. 把许可检查接进 lint / CI，避免再次引入非 OSI 许可（本次即为人工核查才发现）；
  3. **团队约定待写入手册**：`pymupdf`（AGPL-3.0/商业双许可）虽当前零引用，仍应明令 my_app 禁止 `import fitz`，改用 `pypdf`（BSD）；
  4. `GeoLite2-City.mmdb` 尚未落盘，将来下载时需接受 MaxMind EULA（见 `backend/services/ip_trace_service.py:55`）。
  > 本次修复的两个真实缺陷值得留档：`TileLayer`/`CircleMarker`/`Popup`/`Tooltip` 若把 `pane: undefined` 直接塞进 options，会覆盖 Leaflet 的类默认 pane，导致 `getPane()` 返回 `undefined` 并在 `appendChild` 处崩溃（**tsc 与 vite build 均无法发现，只有真实浏览器渲染才暴露**）。冒烟校验应包含「地图页能出瓦片 + 点站点能弹 Popup」。

### 待定 —— 需要决策后才能排期

- [ ] **SQLite → PostgreSQL 迁移是否启动。** 规划已定稿（单 PG 实例 + 每域一个 schema `app_`/`eflow_`、同机 Docker、连接池 `pool_size=20 / max_overflow=10`、低峰切流）。**执行前提**（四项全部落地才可动）：
  1. 回退保证 R7；
  2. 风险 10 / 11 有对策；
  3. 风险 R8 有对策；
  4. 队列层覆盖到位。
  > 范围注意：`db_ps_cs_cn` **整体移出迁移范围**（真数据在远端，经 HTTP 8765 读）；本地同名文件是 0 字节占位。
- [ ] **`db_ps_cs_cn` 本地占位文件是否删除。** 极易被误当数据源（读出来是空的而不是报错）。
- [ ] **门户与 my_app 的视觉规范是否合并为一份。** 目前总则在根 `DESIGN.md`，细节各自维护。
- [ ] **BP Cells Report：`2026-07-01 ~ 07-21` 的四个指标永久缺失，是否接受。**（2026-09-30 记）
  上游远端主日表 `4G_Main_Kpi_Cell_Daily` 在这 21 天是**真实空洞**，UME PM API 侧也只有
  `2026-07-02` 起的数据 —— 两个源都补不了。因此该区间的下钻明细里
  PRB 利用率 / DL 吞吐 / 活跃用户(忙时) / DL 流量 恒为 `—`，页面已按此显示。
  **待业务确认**：这个空洞是上游采集故障还是正常的保留期策略；
  若要补齐，需要上游侧先把这 21 天的历史重新入库。
  另：`2026-06-25 ~ 06-30` 远端有行但 **AU 取不到**，补数会把 `bp_cells` 清零，
  已明确排除（详见 `docs/manual/11-feature-guide.md` §30 的「四个指标只在近期有」）。
- [ ] **BP 历史回填的口径差异是否接受（−13%~−14%）。**（2026-09-30 记）
  已按用户确认完成 `2026-07-22 ~ 09-21`（62 天）的回填，走 bp-v3 忙时口径，
  **覆盖**了这些天原有的 Excel 值：`bp_cells` 系统性低约 13~14%，
  且 `total_cells`（BP 占比分母）从"umlaut 报告过的小区"变成"全网小区"。
  用户已明确接受该副作用。**待办**：确认历史曲线与对外报表的口径说明是否需要同步调整。
  回滚手段：`TMP/_bak_bp_report_*.sqlite3` 快照。

- [ ] **TT 分析「先快后准」备灾（2026-10-08）→ 已转正为纯程序化（2026-10-19）。** 本地规则引擎 + 毫秒级 `GET /api/eflow-qa/tt-ai-fast`
  + `TT_AI_LOCAL_ONLY=1` env 开关，三层兜底详见
  `Task\my_app\backend\routers\eflow_qa.py:564-719`、`backend\services\eflow_rules\tt_rule_evidence.py:858`。
  前端 `EflowQa.tsx` 原先是「fast 立即显示 → 原端点 AI 替换」模式；**2026-10-19 用户要求不再用 AI**，
  页面已改为**只调 `/tt-ai-fast`**，结论文案与徽标统一为「判定结论（本地规则引擎）/ 程序化判定，无模型参与」，
  模型路径 `/tt-ai` 保留但界面不再依赖（`openwebui_client` 仍服务「系统设置 → AI 模型」连通性测试）。
  **待办**：(1) `git status --porcelain` 复查
  `Task\my_app\frontend\src\pages\EflowQa.tsx`、`i18n.tsx`、`backend\routers\eflow_qa.py`
  改动在版本控制下；(2) 提交（`docs\manual\11-feature-guide.md` 14e / 14e-1 与
  `17-rule-engine-vs-llm.md` 17.2.2 已于 2026-10-19 改写为「页面只走程序化」；
  `04-task-system.md` 并没有「TT AI 兜底」一节，无需再等它）。
  回滚手段：`git revert` 本次提交；env `TT_AI_LOCAL_ONLY` 对本页已无作用。

## 三、已完成（近期，供对照）

| 提交 | 内容 |
| --- | --- |
| `e9ec342` | FME 工程师排名、GIS 站点下钻图表拆分与 QC 弹窗拖拽 |
| `58ab07a` | 补齐被引用但从未入库的静态资源，消除拉取后 404 |
| `e448816` | MS KPI/SP 报表、UME 大屏接口与看板深色改版 |
| `0cee167` | QC 看板改版并新增指标快照历史 |
| `7b1d33b` | 清理根目录 98 个一次性探针脚本 |
| `af64f44` / `b88a42b` | 鉴权与自动登录、用户权限、统一界面优化 |

## 四、维护本文的约定

1. **只留在办项。** 做完了就移到「已完成」或直接删掉——`git log` 已经是完整的完成记录，本文不需要再抄一遍。
2. **每条要可执行。** 写"改哪个文件、在哪个界面、验收标准是什么"，不写"优化一下体验"。
3. **标注阻塞原因。** 待定项必须写清"等什么决策/等什么前置"。
4. **定期与 `git log` 对齐。** 每次迭代结束时核对一次，避免本文变成过期的许愿池。
5. **不写敏感值。** 口令、Token、账号一律不出现。

## 五、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 完整提交历史 | `git log --oneline` |
| my_app 历史规划与复盘 | `Task\my_app\PROJECT_DOCS.md` |
| my_app 待清理残留清单 | `Task\my_app\docs\manual\90-appendix.md` |
| 商用就绪度整改 | `liberia-noc_soc-数据看板统一门户\MsPortal 商用就绪度检测 —— 结论与整改方案.md` |
| 迁移专项 | `Task\my_app\docs\FINEBI_MIGRATION.md` |
| 架构与已知风险 | `architecture.md` |
| 开发与回归清单 | `development.md` |

> **工具负责整理，人与 AI 负责协作执行。**
