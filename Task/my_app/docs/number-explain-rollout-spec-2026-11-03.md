# 数字悬浮说明铺开规格（第②–⑥批）

> 生成日期：2026-11-03　|　规则出处：`Task\my_app\AGENTS.md` 三.3c、根 `AGENTS.md` 四.10b
> 进度条目：`D:\01_RPA\TODO.md`「数字悬浮说明铺开」
> **本文是后续会话的实施规格，不是现状手册** —— 现状仍以 `docs/manual/` 为准。
> 每条口径都带 `文件:行号` 证据（由只读调研代理从后端代码核实，2026-11-03）。
> ⚠️ 行号会漂移，实施前请重新 grep 确认；「可疑点」是**待用户决定的口径问题**，不要顺手改数字逻辑。

## 0. 已完成（范本）

| 页 | 做法 | 提交 |
| --- | --- | --- |
| `avail_county` | KPI 卡 ⓘ + 三制式列头 ⓘ + 每个数字的该格构成气泡 + 下钻弹窗列头 ⓘ | `f71ccccb` |
| `avail_ms` / `avail_flm` | 同上；两页共用 `pages/availSumRatio.ts` + i18n `availSum.*`；矩阵数字原 `Tooltip title=` 已换 `ExplainPopover` | 未提交 |

实施模板（每页都是这四步）：
1. 列头/卡标题挂 `ExplainIcon`（讲这一列），数字本身挂 `ExplainPopover`（讲这一格）。
2. 气泡文本在页面目录的 `xxxHelpers.tsx` 里拼，**字段一律取接口既有值**。
3. i18n 中英两处加键；键名用显式字面量或 `switch`，**禁止模板串拼键**（`check:i18n` 会拦）。
4. 手册 `11-feature-guide.md` + `helpContent.ts`（改完跑 `npm run docs`）+ `npm run build` + 实机悬浮验证。

---

## ② MS SLA / NUR 族

### MsSlaDashboard（`?page=ms_sla`，接口 `/api/ms-sla-dashboard/overview`）
- 数字：NUR 表（Global/2G/3G/4G × 期间，`:821-825`）、NUR Trend（×100000）、Network KPIs 7 项（`:845`）、Per-Site KPIs 11 项（`:858`）、WO 表 Total/Within SLA/Achieve（`WoTable:408-446`）、Achieve Trend 4 分面（`:468-500`）、顶部两个时间标（`:745-750`）。
- 算法：NUR = `round(Σ(小区数×MTTR)×60 / (分母小区数×GR), 8)`，`nur_calc.py:1036`；样本仅 `0<MTTR<43200 分` 且已清除、`cells_weight>0`（`:620,:1002`）；小区数按**站名**优先、site_id 回退（`attach_cells:528-601`）；Global = 各制式分子和 ÷ 小区数和（`:1030-1031`），**不是均值**；WO `achieve=round(pass/total,4)`（`:1044-1069`）；Network = 快照库 `ms_sla_kpi` 原样取列（`ms_sla_report.py:335-395`）；PS_* = 阈值达标行数 ÷ 该期总行数（`:397-438`，如 `PS_CSSR_2G ≥0.97`、`PS_DCR_2G ≤0.02`）；`PS_NUR_2G/3G` 例外，换成「站点 NUR×1e5 < 350 的站点数 ÷ 该制式有小区站点数」（`nur_calc.py:691-743`）。
- 已有：`NurCalcChainNote`（`:807-812`，6 段口径）+ 常驻未匹配告警。**无 MetricExplain**。
- 气泡要写：×100000 与 ×100 只是显示缩放，后端给的是原始比率。

### MsSlaOnly / MsNurOnly
- 都是 `MsSlaDashboard` 的 `only` 切片（各 1 行透传）。`ms_sla_only` **当前零口径说明**（`NurCalcChainNote` 被 `showNur` 跳过）；`nur` 切片有 note 但数字级仍缺。

### NurDashboard（`?page=nur`）
- 数字：NUR 三档表 + Trend + 卡右侧 `Denominator: 2G=/3G=/4G=/5G=`（`:825-844`）、`TT: n` 与排除名单标签（`:796-806`）、SLA 表（`SlaTable:243-325`）、SLA Trend（`:421-463`）。
- 算法：`tt_total=len(df)` 是**筛选后**行数（`nur_calc.py:1093`）；`denominator_cells=denom`（`:1092`）；`achieve=round(pass/count,4)`（`:1069`）；排除规则 `exclude` 空与 `N` 同义、只有 `Y` 才扣单（`:897-928`）。

### MsWoSLReport（`?page=ms_wo_sla`，`/api/ms-kpi-report/summary?kind=wo_sla`）
- 数字：6 张统计卡（`:153-204`）、5 个指标卡（`MetricCards:264` → `MsKpiShared.tsx:349-370`）、达成率日趋势（`:86-109`）、矩阵 Month 行与日行、趋势弹窗 `min/max/avg/met_days/below_days`。
- 算法：源是工作簿 `data/ms_sla/ZTE OLR MS WOs SLA Achievements Daily Report_*.xlsx`（任务 `kpi_ms_wo_sla`）；`Total/Within SLA/Achieve` 是**角色列**，整组一个指标、取值列=Achieve（`ms_kpi_report_service.py:489-506`）；`min/max/avg` = 有值日行的算术平均（`:574-576`）；`days` = 矩阵日行数，**不是自然月天数**（`:745`）；单元格值全是工作簿原值，无除法重算（`ms_sla_report.py:441-502`）。
- 已有：**常驻 `<ul>` 口径块**（`:337-347`）→ 按三.3b 本应迁 `CalcChainNote`。

### MsContractKpiReport（`?page=ms_contract_kpi`，`kind=contract_kpi`）
- 数字：6 张概览卡（`:408-445`）、分类达标卡（`:448-467`）、worst/best 标签、27 个 KPI 卡、页签 `(records)`、WO 页签 5 指标月值。
- 算法：Contract 表每个叶子列各自是一个 KPI（`:507-510`，无角色列）；`worst/best` 按相对目标差距 `gap=(t-v)/|t|` 排序取前 5（`:731-749`）；`unknown_count = met is None`。

### ② 可疑点（需用户决定，勿顺手改）
1. **颜色方向错**：前端一律 `v>=0.95 绿`（`MsSlaDashboard.tsx:225`、`NurDashboard.tsx:293`），但 `2G_DCR/3G_DCR/3G_DCR_HSDPA` 是**越小越好**（`ms_sla_report.py:157`，生成端用 `<=` 着色）→ 这几列恒红。气泡**绝不能**把颜色说成达标。
2. `WO_ACHIEVE_TARGET=0.95` 是前端唯一阈值，后端逐项阈值不同、TTR 目标 0.98。
3. `5G_NUR` 后端算了但 `NUR_METRIC_MAP` 只映 4 键（`routers/ms_sla_dashboard.py:58-63`）→ 永久不显示。
4. 本页 `TTR_P1..P4` 只是严重度分组，**无 4h/8h/16h/2Days 时限判定**；与 `ms_wo_sla` 的 `TTR_P1_4h` 同名不同口径，不可互引。
5. `Total/Within SLA` 是整数条数，前端 `fmtNum().toFixed(2)` → 显示成 `12.00`（`:110-113`）。
6. **MsWoSL 卡片颜色在前端重算达标**（`:180-183` 用 `month_achieve >= metrics[0].target`），后端已给 `met`（`ms_kpi_report_service.py:570`）却没用 → 违反三.3c，应改取 `met`。
   **更正（2026-11-03 复查代码）**：本条原写「`num(null)=0` 会把目标缺失判成达标」**不成立** —— 该表达式带守卫 `month_achieve != null && target !== null && num(a) >= num(t)`，任一侧为空则整个条件为 false → 判 `WH.danger`（红）。真实缺陷是**反过来**的：「没有目标值」被涂成未达标的红色。修的时候按 `met === null` 不染色处理。
7. `month_achieve ≠ month_within/month_total`（三者各取工作簿单元格，`:495-501`），页面并列展示，代码无法证明自洽。
8. 达标方向靠 KPI 名关键字（`_LOWER_KEYWORDS:264-266`）；`TTR_P1_4h` 本期无数据 → 整列空。
9. **PerSite 目标 90% 是代码硬编码**（`PERSITE_TARGET`，`_parse_kpi_matrix:397-408`）且不读工作簿目标行，而 `msKpi.doc.persite` 称「与生成端条件格式一致」—— 生成端 PerSite 是逐指标阈值占比（阈值 0.9965/0.97/0.98/0.95/0.02），**两种说法不等价**。
10. `avg` 是等权算术平均，界面只说「平均」，与 `month_value`（工作簿 Month 行）并存时必然对不上。
11. `gap` 在 `target∈{None,0}` 时返回 `0.0` → 该 KPI 永不进 worst。

---

## ③ TT / WO 族

> `TTDashboard` / `WODashboard` / `V1TTWODashboard` 都是 `TTWODashboard` 的切片（各自 `:19/:33/:21`），主体只讲一次。

### TTWODashboard（`?page=ttwo`）
- 数字：TT 总数 / WO 总数 / WO 编号唯一徽标（`:1846-1853`）、严重度卡（大数+占比%，`:1868→1333/1336`）、SLA 状态卡（`:1872`）、Workflow 里程碑（`:1567/1568/1585`）、MTTR 四图（`:968-977,1015-1020`）、领域/根因/WO 来源/WO 状态/站点图（`:1092,1136,1168,1967`）、下钻记录数（`:1980`）。
- 算法（`backend/routers/tt_wo_dashboard.py`）：时间字段一律 `alarm_occur_time`，`time_end` +1 天排他（`:94-105`）；`tt_total=len(行)`（`:383`）；`wo_no_count`=TT 行非空 `wo_no` 去重（`:419,384`）；severity/sla **排除 Unknown**（`:120-131,153,409-414`）；**MTTR = (alarm_clear_time − alarm_occur_time) 分钟均值，剔除 ≤0 或 ≥43200 分钟**（`:441-457`），`total`=该桶该级别全部单、`count`=入均值样本、`mttr=null` 断线非 0（`:284-318`）；ZTE/3rd = `wo_no` 空/非空（`:168-179`）。
- 已有：`ExplainIcon` 已挂徽标、维度小标题、MTTR、根因；里程碑有构成级 `milestoneTooltip`（`:1365-1383`）。**缺口只在卡片大数字/占比与图表点位**。

### TTDashboard（`page=tt`）/ WODashboard（`page=wo`）/ V1TTWODashboard
- 只出上半部分（`isSlicePage`，`:372`）。**wo 走 `/api/wo-dashboard/overview`，数据源 `eflow_wo`**，SLA 取 `LEFT JOIN eflow_tt` 的 `sla_status`（`wo_dashboard_service.py:97,100-104`），MTTR 用 WO 自身 occur/clear（`:150-162`）。

### EflowFlow（`?page=eflow_flow`）
- 数字：节点标注 `active_rule_count/rule_count`（`:282`）、KPI「已走步骤」`reached_ids.length`（`:667-669`）、「流程规则」`graph.rules_total`（`:676-678`）、卡头「生效 N / 共 N」（`:750-751`）。
- 算法（`backend/services/eflow_flow.py`）：规则来自 `ocrule_details` 全表无 WHERE（`_load_rules:250`）；`rule_count`=按 (name,rule_type,trigger_step) 去重且 triggerStep 命中声明列表且 `wo_type==eflow-tt/eflow-wo`（`:574-597`）；`active_rule_count`=`status=="ACTIVE"` 严格大小写（`:598`）；`rules_total=len(rules)` 整表（`:647`）；`reached_ids`：**alarm/create 无条件打点**（`:692-701`）。
- 已有：无 CalcChainNote/MetricExplain，仅 ECharts 节点 tooltip。

### NocAnalyst（`?page=noc_analyst`）
- 数字：KPI 六卡（`:2431-2470`）、排名表（`:1831-1936`）、聚合视图各卡（`:2585-2837`）、站点层（`:2147-2189`）。
- 算法（`backend/services/tt_postmortem/__init__.py`）：源 `eflow_tt`，`WHERE last_processer 非空 AND alarm_occur_time ∈ [月初,次月初)`（`:3128-3145`），月窗按本机时钟=UTC（`:3030-3041`）；**`mismatch_pct = mismatch / with_root_cause`（分母是已填根因单数，不是 total）**（`:3232`）；`avg_duration_h = duration_sum_s/duration_count`，时长来自 `*_detail` 文本正则、>7 天剔除（`:1567-1599,:3200`）；`night_pct = night_total/total`，夜班取 `fo_accept_detail` 的 22–06（`:3023,3052-3057`）；SLA 只认 Pass/Failed 入分母（`:3209-3215`）；红旗阈值 30%/12h/50%（`:3283-3288`）。
- 已有：常驻小字 `noc.timeFieldNote/nightWindow/ownerNote*`；单元格 Tooltip 已给 `mismatch_count/with_root_cause`、`Pass/Fail/Total`；`noc.explain.topNoc/bottomSla` 已解释错位率公式 → **新气泡别重写这三段**。

### ③ 可疑点
1. `ttwo.explain.*` 文案硬写「TT 按 …」，但 `page=wo` 用同一批键渲染 `eflow_wo` → 说明文字对 wo 页是错的（要么分键，要么改中性措辞）。
2. **占比与里程碑合计全是前端合成**（`:1313`、`:644-695`），接口无 `pct` 字段 → 与「气泡只取接口字段」冲突。
3. `page=ttwo` 的 `owner` 只过滤 TT 不过滤 WO（`:371-372`）→ 切 ZTE/3rd 时 TT 变、WO 不变。
4. **page=wo 与 page=tt 的 MTTR 是两个数**（手册实测同周 P3：WO 943.2 / TT 910.3 分钟），文案不可共用一句。
5. 导出 sheet 读 `sStats?.severity`（`:813`），后端键是 `alarm_severity`/`category` → 该 sheet 恒空。
6. 手册 `11-feature-guide.md:392` 写「0<dur<43200 **秒**」，代码是**分钟**（`tt_wo_dashboard.py:450`）→ 手册错。
7. `WODashboard.tsx:12-13` 与 `wo_dashboard_service.py:22-27` 注释都称「JOIN 不上计 Unknown，保证卡片之和=WO 总数」，但 `:119-124` 实际**排除 Unknown** → 注释与实现相反。
8. **`_mismatch_of:3069` 把 root_cause `.upper()`，而 `:3081` 豁免元组是混合大小写**（`Auto-recovery`/`Uknown`/`Force Majeure`/`Planned work`）→ 豁免永不命中，自恢复/不可抗力单被计进错位率（影响数字本身）。
9. KPI `avg_mismatch_pct`、`avg_duration_h` 是**各人均值的算术平均**（每人等权，`:3266-3273`），而 `overall_sla_pass_rate_pct` 是合并口径 Σpass/Σtotal（`:3274-3277`）→ 同排三张卡口径不同，不能写同一句式。
10. `dispatch_rate_pct = dispatched / parsed`（全月解析单量），分母不是 `should_dispatch`。
11. 「偏离总数 / 缺失动作总数」两张卡由前端 `reduce` 求和（`:2639,2649`），后端未给合计 → 违反三.3c，需后端补字段。
12. 概览 `noc_filter` 用 `LIKE %x%`（`:3091`），下钻用 `last_processer = ?` 精确（`:3377`）→ 模糊命中多人时两处行数口径可不同。
13. 夜班只解析 `fo_accept_detail`，IPT/第三方单无该字段 → `night_pct` 对 IPT 恒 0。
14. 红旗 `reasons` 中文串在后端拼死（`:3284-3288`），英文界面显示中文。

---

## ④ 告警 / RAN / CN 族

> 统一时区口径：后端 `date.today()/datetime.now()/SQLite date('now')` 都按本机时钟=UTC，无时区转换。

### AlarmDashboard（`?page=alarm`）
- 数字：4 核心卡 `total_alarms/affected_sites/total_alarm_hours/severity_stats.Critical`（`:687/696/707/717`）、4 历史卡（`:731/740/750/760`）、制式卡站/小区（`:814-815`）、时长双柱（`:455`）、区域三量（`:494`）、类型 Top（`:550`）、区域画像 count（`:916`）。
- 算法（`backend/routers/alarm_dashboard.py`）：`total=len(rows)`（`:423`）；`affected_sites=len({site_id})` 去重（`:525`）；`total_alarm_hours=round(Σ _hours,1)`，`_hours` 由 `durationname` 正则解析（`:528,:353-370`）；severity 按 `perceivedseverity` 1/2/3/4 → Critical/Major/Warning/Info（`:471-478`）；时长 6 档 `<2/2-4/4-6/6-12/12-24/>48`，**24–48 也落 `>48`**（`:37,373`）；市电柱 = `transmission_type=='MW'`（`:467`）；历史四项：派单延迟 `Assigned-servertime > assign_delay*1.1*1000`、获取 `servertime-alarmraisedtime>300000ms`、超期=两者都超（`:86-90`）。
- 已有：**本页已大量使用 `ExplainCorner`/`ExplainIcon`**（`:19,56,87,776,830,835`），8 卡 + 3 图标题已挂 ⓘ，键 `alarm.explain.*` → **勿重写这些键**，只补区域三量、类型 Top 等未覆盖数字。
- 可疑：`total_alarm_hours` 是**活动告警** `durationname` 求和，不是历史累计（文案若写「累计」会误读）；`generated_at` 是任务最后成功同步时刻（`:333`），不是数据时间。

### SiteAvailability（`?page=site_avail`）
- 数字：顶部 6 项 `sites/monthAvg/withData/below/monthTickets/generatedAt`（`:581-592`）；表内四制式月均、最低值、未达标天、周/日列、工单列（`:440-505`）。
- 算法（`site_availability_service.py`）：`month_avg` = 本月有值日期的算术平均（`:545`）；`daily` = UME 站点级原值（G/U/L 直读；TDD = `AVG(Cell Service Time)/86400` 派生，`:316`）；`weekly` = 自然周内有值日均值（`:543`）；`min` = 最低日值（`:546`）；`days_below` = 日值<阈值天数（`:548`）；`by_tech.avg` = **跨站点月均值再取算术平均（站点等权，非流量加权）**（`:586`）；阈值默认 0.9965（`:96`）；工单按 `created_time` 落月、`status!='Closed'` 为未闭环（`:439,447`），站点归属 site_id 精确→站名规范化（`:493`）。
- 已有：**只有 `Collapse` 文档块**（`siteAvail.doc1-5`，`:629`），列头用 `Tooltip title=`（`siteAvail.monthAvgTip/minTip/minDayTip/daysBelowTip/weekTip`）→ 按三.3c 应把 `title=` 换成 ⓘ/气泡，数字级全缺。
- **重点可疑**：顶部 `avgOfTech / withDataSites / belowSites` 是**前端按「搜索框过滤后」的站点集现算**（`:199-207`），与后端全量 `summary.by_tech` 不同口径且随搜索变化。`belowSites` 因阈值前端可调而必须现算（合理），但「月均」是纯重算 —— 气泡必须写清「只统计过滤后看到的 N 个站点，清空搜索框才是全网值」。
- 4G 已知上游差异：PG `[FDD]Cell Availability` 与远端 `4G_Main_Kpi` 系统性偏差约 14%（`service:23-25`），远端仅作回退。

### RanCellsKpi（`?page=ran_cells_kpi`）
- 数字：月度汇总卡 `tb.month.availability`（`:497-507`）、逐日矩阵 7 指标 `total/meeting/below/blank/pctMeeting/pctBelow/availability`（`METRICS:103`，单元格 `:545-573`）、`roster_cells/days_with_data` 副文本、下钻 count。
- 算法（`ran_cells_kpi_service.py`）：小区可用率 2G = 可用信道/(可用+不可用)（`:260`），3G/4G = 服务时长/86400（`:276`）；逐日 `total`=当天有效小区数、`meeting/below`=相对 threshold 计数、`blank`=roster−total（`:380-386`）；`availability`=当天有效小区可用率的**算术平均**（`:394`）；**月 `availability` = 各有效日 availability 的等权平均（日等权，不按小区数加权）**（`:400`）；`pct_*` = `*/total`（`:392`）；默认读物化库 `cells_kpi_daily`（`prefer_db=1`，`:693`），缺失回退实时算原始库；阈值 0.9965（`:67`）。
- 已有：整页口径 `Popover`（`rck.sourceTitle/sourceDesc`，`:451`），**无数字级 ⓘ**。
- 可疑：本页「可用率」是**小区级**均值，与 SiteAvailability 的**站点级 UME 原值不可比**；月均是「日等权」非「小区数加权」；数据源是独立 sqlite `data/ran_kpi_avalability_1day.sqlite3`，4G 原始列名含 `\xa0`，注释警示双引号误用会静默返错值（`:299-303`）。

### CnKpi（`?page=cn_kpi`）
- 数字：18 个组件图（值即后端 SQL 结果）、页头 `meta.count/failed/elapsed_ms/cached`（`:439-445`）、`degradedWidgets` 计数（`:359`）、「最新数据日期」（`:224-237`）。
- 算法（`cn_kpi_service.py`）：读远端 `db_ps_cs_cn.sqlite3`（`:86`），SQL 内 `{{LO}}/{{HI}}` 默认近 31 天（`:498`）；分层取数 主表(EMS 日)→`fallback`(UME 日)→`monthly_table`(月粒度)（`:671-745`），降级写回 `degraded`/`granularity`/`fallback_from`；粒度由数据推断（`_detect_granularity:586`）；GB 类组件值已在 SQL `/1e9` 换算。
- 已有：**既无 CalcChainNote 也无 MetricExplain**。气泡建议复用 `w.sql / w.granularity / w.fallback_from` 字段，勿前端重算。
- 可疑：同一 KPI 库里有 OSS/EMS 两张同名表，EMS 停更时降级到 UME/月表（`:21-38`）→ 月粒度点易被读成日值（前端已有 `monthly` Tag + `degraded` 告警条）。

### CnKpi5mins（`?page=cn_kpi_5mins`，CalcChainNote 参考实现）
- 数字：8 组件曲线值、页头 `elapsed_ms/failed/cached`（`:381-384`）、`withData`（`:312`）。
- 算法（`cn_kpi_5mins_service.py`）：读远端 `5mins_*` 表（由 `cnn_kpi_sync_5mins` 每 15 分钟写入，`:5-6`）；每图叠 Day0/Day1/Day7 三线，日切 `substr("End Time",1,10)`、x 轴 `substr("End Time",12,5)`（`:19-25`）；聚合 `SUM(...)`（订阅/话务/流量）或 `ROUND(AVG(Throughput Usage(%)))`、`AVG(Peak vCPU(%))`（License/CPU 取均值）（`:117-226`）；RG 系列按 `"Measurement Object"='30/12/11/6'` 拆分（`:160`）；上游无该粒度→`empty`+`empty_reason`（`:297-336`）。
- 已有：`CalcChainNote`（`:434`，键 `cnkpi5.note.*`）覆盖 ① 粒度混用 ② 空卡原因。**缺数字级**：组件卡标题无 ⓘ，未讲该线是 SUM 还是 AVG、GB 换算、RG 过滤、License/CPU 是「百分比的算术平均（非加权）」、Day0/1/7 对齐基准。
- 可疑：**5 分钟 / 15 分钟粒度混用** —— xGW License/CPU、3G FDD 三条实为 15 分钟档（行数约 1/3，稀疏点不是缺数）（`:190-226`）；Day7 是否有线取决于库里攒够 8 天（`:27-32`）。

### UmeInKpi（`?page=ume_in_kpi`）
- 数字：汇总 `sum.kpi/service/attempts/failed/systemFailed/userFailed`（`:1726-1731`）、成功率/系统失败率/用户侧占比卡（`:1521` 导出、`:1879` 渲染）、资源卡 `avg/top`（`:2008`）。
- 算法（`ume_in/ume_in_kpi_service.py`，日粒度 gr=86400）：`success_rate=Σsuccess/Σattempts`（**按 attempts 加权**，`:1005`）；`system_fail_rate=Σsystem_failed/Σattempts`（`:1006`）；`user_fail_ratio=Σuser_failed/Σfailed`（`:1007`）；资源 `avg`=当天各 SERVICE 主列算术平均、`top`=峰值（`:1080-1082,1102`）；阈值 `SUCCESS_WARN=0.99 / SYS_FAIL_WARN=0.001 / RES_WARN=80`，env 可覆盖（`:83-91`）。
- 已有：仅一个 `Collapse` 文档块（`:1827`）+ `/specs` 阈值接口，**无数字级 ⓘ**。
- **重点可疑**：**KPI 大卡数字只统计「最后一天」**（`_analyze_success_kpi` 卡头 `total=agg(latest_rows)` `:1049`、资源 `rs_latest` `:1101`），而 `summary.total_attempts` 等是**整个 N 天窗口求和**（`:1243`）→ 页头总量 ≠ 卡上量，气泡必须写清「卡=最新一天，汇总条=窗口累计」。告警只来自系统侧失败率与资源，用户侧失败集中只给 info（`:1115-1116`）。

### RepeatSiteDown（`?page=repeat_site_down`）
- 数字：4 张 Statistic（`summary.outage_events/affected_sites/repeat_sites/peak_day`，`:52`）、逐日柱/线（`:33`）、排名表 `outage_count/repeat_days`（`:48`）。
- 算法（`repeat_site_down/repeat_site_down_service.py`）：源 `eflow_tt` LEFT JOIN `eflow_site`，筛选 `site_outage ∈ yes/y/1/true`（`:96`）；发生时间列取 `alarm_occur_time`→`created_time`→`last_modified_time` 首个存在者（`:39`）；默认近 30 天按本机 `date.today()`（`:63`）；`outage_events` = 1 行 = 1 次中断（`:139`，`counting_rule` 见 `:74`）；`affected_sites` = 唯一站点键数（site_id 或规范化站名，`:133-139`）；`repeat_sites` = `repeat_days>1` 的站数；`peak_day` = daily 中 `outage_count` 最大日。
- 已有：`meta.counting_rule` 挂在卡片 extra Tooltip（`:52`），未展开到每个数字。**本页标题全为硬编码英文，无 i18n 键** → 加气泡时要一并补键（否则中英不齐，`check:i18n` 也查不到这些既有硬编码）。
- 可疑：`affected_sites` 按 `site_id or norm(site_name)` 去重，与 AlarmDashboard 的纯 `site_id` 口径不同；`repeat_days` 是「有中断的自然日数」非连续天数。

---

## ⑤ 报表 / 仓库 / 分析族

### SpReportBase（改一处覆盖 `sp_report` + `com_report` 两页）
- 数字：8 张总览卡（`:533-556`）、5 张补库卡（`:748-753`）、分表卡（`:819-847`）、矩阵 `inbound_total/outbound_total`（`:579-582`）、标签头 `filtered_qty_total/qty_total`（`:929`）`total/records`（`:936`）。
- 算法（`sp_report_service.py`）：数据源是 **Excel 汇总工作簿**（任务 `sp_report_generate` 05:15），不是 DB。前 7 张卡 = `Summary-Current` 的 **Total 行逐列取值**（`tot():586-591`，非数值/缺列→`0.0`）；`urgent/replenish/redundant/failure_rate/actual_consumption` = `_counter_top` 的**行数**（单位是「物料条数」，与卡的 qty 单位不同，`:593-596,609-613`）；`material_count = len(sd.rows)` 是**行数不是去重物料数**（`:599`）；`records/qty_total/warehouse_count/latest_time`（`:553-579`）；`open_count` 仅 spareparts 用 DB `count_open_docs` 覆盖并置 `open_count_source='db'`（`:781-838`、`sp_common.py:137-154`）。
- 染色：`difference<0`→Critical（`:545`）、`urgent>0`→Critical+emphasis（`:552-553`）；取不到→`0`（`?? 0`），**没有 `—`**。
- 已有：`spRep.hint.*` 常驻小字 + 底部 `summary.notes` 口径条（`:988-998`，来自 Excel 单元格文本）。**无 CalcChainNote/MetricExplain**。
- 可疑：①「未关闭单」全站三套口径（本页按单号去重+全词表 / `sp_details_service.py:442-443,469` 按**行**且只判 `"closed" not in status.lower()` / `sp_dashboard.py:385` 精确等值 `=="closed"`）→ 同一业务三页三个数；② **同页 kind 分叉**：sp=实时 DB、com=05:15 Excel 快照（`:810-814`），界面渲染完全一致不标来源 → 气泡写「实时未关闭单」对 com 是错的；③ `:851-856` 把 `Summary-Current` 的 `qty_total` 覆写为 `Inventory Qty` 合计，与其余 sheet 不同构。

### SpDetailsReport
- 数字：7 张卡（`:423-432`）、分表卡（`:545-568`）、数量与行数标签（`:639-646`）。
- 算法（`sp_details_service.py:515-557`）：`total_records=Σ len(rows)`；`distinct_materials`=Material No. 并集去重（`:490,533-537`）；`warehouses`=仓库列并集（Transfer 取 Original+Target 两侧，`:136`）；各 qty = 各 sheet `qty_total`（`QTY_COLUMN:118-124`）；`open_tickets=Σ 行级 open_count`（`:469,544`）。
- 可疑：本页读 `_source` **任何过滤之前**的快照，而 SpReport/ComReport 读过滤后的汇总簿 → 同日同名指标本页系统性偏大，**文案不能与 ① 共用**；底部口径是写死的 `spDet.doc1-4`（`:699-705`），非后端下发，易与代码漂移。

### SpMaterialSummary
- 数字：17 个可加列 ×（4/5 分组行 + Total 行）（`:380-464`）；下钻弹窗 `spMat.totalQty`（`:574-582`）。
- 算法（`sp_material_summary_service.py`）：`inventory_details` 按快照日 `update_date IN (锚点/当前/月初/周初)` 一次 `GROUP BY` 聚合 `SUM(Stock Qty)`（`:306-325`），仓库名经 `ROW_GROUPS:126-157` 精确/前缀匹配归组，未命中落 Others；分桶 `:346-351`（`mstatus=='damage'`→damage；否则 mtype 含 `spare`→spare_good；含 `consum`→consumables）；消耗 = 期初−期末（三窗口各自减当前，`:581-615`）；`anchor_total = a_spare + a_cons`（**不含 damage**）；`repair_outbound` 来自另一张表另一段时间（`outband_details` 且 `Outbound Type='Repair Outbound'`，`:110-115`）；缺快照→回退「≤目标日最近快照」+warning（`:56-57`）；分组无数据→按 0 +warning（`:622-626`）；Others 全 0 隐藏（`:630`）；Total 含 Others（`:639-646`）。
- 已有：**常驻展开**口径条 `spMat.doc1-5`（`:467-470,552-561`）→ 按三.3b 应顺手迁 `CalcChainNote`。
- 可疑：① 弹窗 `totalQty` 是前端对**筛过的子集** `reduce` 求和（`:574-582`）→ 违反三.3c，需后端下发字段；② `spare_good` 的 "good" 名不副实（只判 `!= 'damage'`，无 good 白名单，`:346-349`）；③ `anchor_total` 不含 damage 而 `total` 含 → 两数天然不等，气泡不写清会被当成对不上账；④ 消耗不做入库/调拨回补，负值合法并另有 warning 点名（`:648-659`）—— 按 3b 判断：解释→收起，异常→常驻。

### WarehouseSummary
- 数字：6 张 KPI 卡（`:459-485`）、段① 4 列 + Total 行（`:342-344,583-599`）、段② `consumption_qty/inventory_qty`（`:372-376`）、Total 行（`:640-654`）、标签（`:611-616`）。
- 算法（`sp_report_service.py:662-730`）：仓库集合 = Outbound∪Inventory（缺失侧计 0，`:665-666`）；`current_inventory` = Inventory 的 `Stock Qty` 求和（`:709`）；三个 consumption = Outbound 的 `Outbound Qty` 求和，month/week 用 `_outbound_time` 按 `OUTBOUND_TIME_COLUMNS` 优先级回落（`:650-659`）与 `_period_starts`（周一起算，`:641-647`）比较；`_frequent_materials` 的 `consumption_qty` 取 `Outbound Site Qty`，缺列回落 `Outbound Qty`（`:739-740`）；Total 按**全量**算再排序不截断（`:761-772`）。
- 可疑：① **`:481-483` 前端重算 `urgent`**（`rows.filter(alert_level==='Urgent Replenish').length`）→ 新规则下必须改接口字段（后端等价物 `overview.urgent`，`sp_report_service.py:609`，本接口未下发，**需后端补字段而非前端继续算**）；② `whSum.kpi.materials` 与 `spRep.card.materials` 都叫「物料数」且都是行数，而 SpDetailsReport 的 `distinct_materials` 是真去重；③ `consumption_column` 动态回落，气泡必须用下发值不能写死列名。

### BpReport
- 数字：4 张卡（`:788-853`）、趋势表 `bp_cells/total_cells/bp_ratio/traffic_tb/detail_cells/detail_diff/undecidable`（`:432-580`）、分区图柱（`:290`）、分层表（`:885-905`）。
- 算法（`bp_report_service.py`）：trend/summary 直查 `bp_overall_daily|week|month`（`GRAIN_SPEC:35-37`），展示值取汇总表不重算（`:228`）；`summary` = `COUNT(*)/SUM(bp_cells)/SUM(total_cells)/SUM(traffic_tb)/AVG(bp_ratio)`（`:209-213,334-345`）；`detail_cells/undecidable/drillable` 由 `bp_cell_daily` 逐日聚合再按 ISO 周/月归并（`:247-303`），`total_drillable` 仅 `source='ume'` 且行数==total_cells 时为真（`:300-303`）；判定阈值 `bp_caliber.py:55`（吞吐<3Mbps）`:62`（PRB>0.80）`:68-73`（周 4/7、月 3/4 完整周），口径版本 `bp-v3`。
- 已有：`CalcChainNote`（`:729-737`，仅 `au.available` 时）+ **常驻** ⑧ 口径卡（`:929-959`，`bp.caliber.*` 五条）→ 新增气泡不得重复这五条。
- 可疑：① **`avg_ratio` 是各期比率的算术平均（`AVG(bp_ratio)`），不是 `SUM(bp_cells)/SUM(total_cells)`**，而该卡下钻落到区间全量 BP 明细 → 数字与点开行数无对应关系，气泡必须写「期比率的等权平均」；② `bp_cells` 有两个分母（excel 来源期的 `total_cells` 是 Excel 全网数、无名单，`:141-156`）；③ 分区/分层的 `bp_number/total_cell` 是**按天累加**非去重小区数（`:454-455,498-499`），分层已知不可对账并禁用下钻（注释 `:893-899`），但分区图柱仍可点（`:421-429`）→ 同一字段两处行为分叉。

### CrChangeAnalysis
- 数字：8 张计数卡（`:210-220`）、3 张比率卡（`:222-236`）、表列与合计行（`:444-450`）、`filters.row_count`（`:252`）。
- 算法（`cr_analysis_service.py:97-149`）：表 `eflow_cr`（`cr_caliber.py:17`），时间列 `request_registration_time`（`:20`），默认 240 天窗口（`:47`）；计数 = 一条 SQL 的 `SUM(CASE WHEN <bucket> THEN 1 ELSE 0 END)`（`:77-79`）；`planned`=planned_start_time 非空、`executed`=actual_start_time 非空、`on_time`=executed 且 `actual_start_time <= planned_start_time`（**文本字典序**，`cr_caliber.py:85-86`）、`unexecuted`=planned 且 actual 空、`closed/canceled/open`=status 归一后等值/NOT IN（`:63-104`）；比率 `_rate:70-74` 分母 0 → None → 界面 `—`；染色阈值 80/50 在前端（`crTypes.ts:158-171`，注释自称「业务约定」）。
- 可疑：① **`:130` 整块前端重算**（`summarize(rows)` 自算 8 计数 + 3 比率），且 `rows` 又被 `activeCats` 前端二次过滤（`:127`）→ 卡片数字是「前端筛过的类别子集」，后端 `summary`（`:188-192`）**被完全忽略**。这是本页最大改造点：要么后端按 categories 下发，要么去掉 activeCats 对 KPI 的影响；② 三个比率分母各不相同（`completion=executed/planned`、`on_time=on_time/executed`、`closure=closed/total`），且 `planned ≠ executed + unexecuted`（有 actual 无 planned 的行两边都不计）；③ 文本比较依赖上游格式一致，注释已承认是假设。

### WarehouseDashboard —— **本页不适用**
`:58-61` 是 `<iframe src=public/warehouse-dashboard.html>`，数字不在 React DOM 里（三.3c 豁免 iframe）。若仍要做，只能改 `frontend/public/warehouse-dashboard.html` 本体。
顺带记录（后端口径与缺陷）：`sp_dashboard.py:404-440` Inventory 卡**仅取 `MAX(update_date)` 单快照**，`:423` 注释明确 date_start/date_end 对本卡不生效；Borrow/Repair/Lost 按 `Outbound No.` 去重，SLA 阈值 45/180/1 天**写死在调用处**（`:683-685`）不是配置；`_db_exists()`（`:30,66-67`）判据是 `db/app.db` 文件存在，但项目实跑 PG（`MY_APP_DB_MODE=pg`）→ app.db 缺失时整页**静默返回 0 而非报错**（与 `battery_dashboard` 已修掉的同类缺陷）；「未关闭」判据是第三套（精确等值 `=="closed"`，`:385`）。

---

## ⑥ 其余页面（未调研，实施前先按本页模板自查）

`BatteryDashboard` / `BmMeta` / `BmSpeedtest` / `Dashboard` / `FmeRanking` / `GISMap` / `Overview` / `PacketLossDashboard`（已有自写 `MetricExplainPopover` 5 处，建议迁到统一组件）/ `PersonMap` / `PmExecutionAnalysis` / `VmaxUserQuery` / `NativeBoard` / `DataSync` / `EmailReports` / `TableBrowser` / `ApCenter` / `IssueFeedback` / `ImonitorScreen` / `ArchiveList`。

**判定「不适用」并直接跳过**（无「算出来的数字」，硬凑违反三.3c）：
`AIModelSettings`、`CredentialSettings`、`DataUpload`、`EmailRecipientsSettings`、`Help`、`IssueFeedback`(仅计数，可只给一句)、`PortalLogin`、`RemoteHostSettings`、`Settings`、`WhatsAppSettings`。
`DataSync`/`TableBrowser`/`ApCenter` 的数字是「行/任务计数」，气泡只写「统计的是当前筛选后的行数，不是全表」即可，不要编造聚合口径。
