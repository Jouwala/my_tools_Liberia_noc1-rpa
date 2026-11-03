# eFlow 告警「压缩 / 派单」规则审计报告（2026-11-03）

> 审计对象：`alarmcode=199083023`、站点 `Nwrokia`（Site ID 3467）、AID `1764221015205`
> 审计方式：全程只读（eFlow FM 只读接口 + 本地 PO 只读查询 + 本地规则镜像 xlsx），未做任何写操作
> 审计时间：2026-11-03（样本在查询时仍为 active，`durationname="3h 33min 18s"`）
> **2026-11-03 修订：按 Assign Delay 口径校正 9990 建单率结论。** 原文「9990 命中规则名 100% 但建单率约 1.5%／建单率塌陷」**已作废**——告警在延迟窗口内自行清除本就不该建单。按 7 天 138 条 `relationflag=1` 分桶：**A=136（延迟内恢复，预期不建单）、B=0（真缺口）、C=2（有单）**。详见 1.3 与 3.4 节。
> 面向读者的可执行变更清单见 [eflow-alarm-rule-change-checklist-2026-11-03.md](eflow-alarm-rule-change-checklist-2026-11-03.md)；
> 9995 / Nwrokia 事故的人工核对问题见既有文档 [eflow-dispatch-rule-gap-checklist.md](eflow-dispatch-rule-gap-checklist.md)（本报告不重复其内容，只引用结论）。

---

## 一、结论速览

### 1.1 这条样本为什么被漏掉

**一句话：它是一条「只有叶子、没有父、也没有派单规则」的告警——压缩层的输入条件不满足，派单层的规则里根本没有这个告警码。**

四层证据链（逐层实证见第三节）：

| 层 | 应发生的事 | 实际状态 | 判定 |
| --- | --- | --- | --- |
| L1 接口原始行 | 存在 | ✅ 存在，`clearstate=0`（active） | 通过 |
| L2 压缩（服务端） | 被 `zte-3g-sitedown` 打成 9990 的子告警 | ❌ `relationflag=0`、`parentinfo=null` | **断点 ①** |
| L3 自动派单（建 TT） | 命中某条自动派单规则并建 TT | ❌ `assign_rulename=null`、`tt_id="empty"` | **断点 ②** |
| L4 FOAccept 推单路由 | 已有 TT 再推给处理组 | ❌ 无 TT，无从推 | 未到达 |
| L5 本地 `realtime_alarm` / `history_alarm` | 可被本地审计 | ❌ 白名单不含该码 + history 只留「有 TT」的行 | **观测盲区 ③** |

**断点 ①（不压缩）的构成原因**：`zte-3g-sitedown`（`backend/services/eflow_rules/eflow_alarm_rules.xlsx` 的 `Alarm_Rules` 工作表第 10 行，ENABLED，规则 ID `rule_1788853932033`，规则包 `OUTAGE`）要求 `siteAlarmCode=199083023` 作为**输入**，再叠加小区退服 `199083022` 或关联码（`2365980930,198097062,9971,9981,9991`）才会派生出 `9990`。实测三路输入全部缺失：

- 同站（Site ID 3467）事故窗口 06:00–06:45 内 `199083022` 共 41 条，**落在本站的是 0 条**（18 条 RNC103、9 条 RNC105 其它站等）；
- 7 天内站点 3467 的 `9990` / `9991` 均为 **0 条**（按 Site ID、`alarmkey`、`positionname` 三种方式各查一遍，全 0）；
- 关联码 `9971/9981/2365980930/198097062`、UMM `2365981958` 在 05:30–07:30 窗口内，命中本站为 0 / 全 0。

配套字段也印证了这件事：`originalspecificproblem="NCP link failure"`、`object_name="MRNC:RNC=105@NODEB=3467"`——这是 RNC/Iub 侧链路故障导致 NodeB 退服，不是「站点 + 小区全挂」的典型断站形态，因此 `cellBlock=true` 的小区告警根本没产生，压缩规则缺了必需的一半输入。

**断点 ②（不派单）的构成原因**：`199083023` 在 `backend/services/eflow_rules/eflow_push_rules.xlsx` 的 `Push_Rules` 143 行里**一次都没出现**（逐行核对 `Push_Rules` 第 2 行 ID 200、第 3 行 ID 201、第 58 行 ID 203、第 59 行 ID 204、第 32 行 ID 253、第 57 行 ID 154、第 136 行 ID 164 的 `alarmCode` 条件）。这不是偶发：最新 2000 条该码历史行中 `Assign RuleName=null` 为 **2000/2000**、`TT ID=empty` 为 **2000/2000**；`eflow_tt` 全表 40,614 条里该码 **0 条**（对比 `199083022` 33 条、`9990` 255 条、`9991` 610 条）。

**同场事故整体未建单**：同站同刻 AID `1764221015309`（`alarmcode=9995` MW LINK DOWN，`alarmraisedtime=1793686672000` → 06:17:52 UTC，比样本晚 3 秒，`relationflag=1` 是 Root、`reason_type="POWER"`、hub=YES、下挂 13 站）同样 `tt_id=null`、`assign_rulename=null`。说明这不是「199083023 单码问题」，而是**整场事故在派单层被整体放过**（该事故的人工核对问题已在 `docs/eflow-dispatch-rule-gap-checklist.md` 第 0 节与 Q2/Q4 登记，本报告不重复）。

### 1.2 最该修的 3 条规则

**① 自动派单规则(103) 补 199083023 等 5 个「仅压缩输入」站断码**（优先级最高）
这 5 个码在 eFlow 里**只作为压缩输入**存在，却不在任何 `Push_Rules`（FOAccept）或自动派单规则的 `alarmCode` 条件里：`199083023`（3G）、`198094422` / `2114322696` / `198200011`（4G）、`199087337`（2G）。压缩失败时它们就是彻底孤儿。修复方向：在 `SITE_OUTAGE` / `SITE_OUTAGE-imported` 一类的站点级规则里把这些码列为**兜底触发码**（或让压缩规则派生不出 9990 时直接对原码建单）。

**② 修 `zte-3g-sitedown` 在「无小区告警」场景下的派生逻辑**
`Alarm_Rules` 第 10 行要求 199083022 / 关联码至少命中一路。而 `cellBlock=true` 意味着小区告警被阻塞后，规则在现实中拿不到那一路输入——**规则自身把最常见的一种断站形态（Iub/传输故障引发的 NodeB 退服）排除在外**。修复方向：把 `199083023` 并入 `mwlink-outage-new` 的 `siteAlarmCode`（该规则当前是 `9970,9980,9990,9910,9920`，同样不含 199083023），或为 `zte-3g-sitedown` 增加「站点级单告警 + 传输原因（`originalspecificproblem` 含 link/NCP）→ 直接派 9990」的分支。

**③ 补 REGULAR `99933` 的 FOAccept 路由缺口（原「9990 建单率塌陷」已按 delay 口径排除）**
原判断「`9990` 命中规则名 135 条但仅 2 条有 TT、建单率塌陷」**已被推翻**：`Assign Delay` 是告警命中自动派单规则后到建 TT 之间的延迟窗口（出处与取值见 1.3），告警在窗口内自行清除本就**不应建单**。按 7 天 138 条 `relationflag=1` 分桶：**A 桶（延迟内恢复）136 条、B 桶（超延迟仍无单）0 条、C 桶（有单）2 条**——9990 **没有真缺口**。真正的规则缺口仍在 FOAccept 侧：`Push_Rules` 200/201 的 `alarmCode` 不含 `99933`，只有 ERA 专用规则 203 含它，REGULAR 站点的电源断站 `99933` 建了 TT 也推不出去。另：`9995`（160/195 无 TT）、`99933`（376/646 无 TT）**尚未按 delay 口径分桶**，暂不能判为缺口，列为待复核项。

### 1.3 按 Assign Delay 口径的分桶校正（2026-11-03 修订）

**delay 参数的真实出处与值**

| 项 | 证据 |
| --- | --- |
| 字段名 | **`Assign Delay`**，是 FM 告警行自带的一列（`backend/services/eflow_alarm_service.py:151-159` 的 `ALARM_COLUMNS`，第 158 行），归一后列名为 `assign_delay` |
| 解析方式 | `backend/routers/alarm_dashboard.py:74-76`：`'900s' -> 900`（正则取数字）；`backend/routers/gis.py:163`：兼容 `'900s'` / `'14400s'` / 纯秒数 |
| 作用层 | **自动派单规则(103)**：告警命中规则后先进入延迟窗口，窗口内清除则不建 TT。FOAccept 的 `ttPushOrderRule` 作用于**已建 TT 之后**，不产生延迟（`backend/services/eflow_rules/eflow_push_rule_eval.py:34` 的 `DECISION_STEP = "FOAccept"`） |
| 真实取值（9990，7 天，rf=1，138 条） | **`900s` 103 条、`14400s` 35 条**，无第三种取值、无空值 |
| 交叉印证 | 与 `docs/eflow-dispatch-rule-gap-checklist.md` Q9 记载的两族延迟一致（`SITE_OUTAGE` / `LINK_OUTAGE_9995_*` / `CELL_OUTAGE_*` = 900s；`SITE_OUTAGE_ERA*` / `SITEOUTAGE_REGULAR_COOL*` = 14400s） |
| 未证实项 | 延迟窗口从「告警升起」还是「规则命中/First Match Time」起算，接口只给 `Assign Start Time` / `First Match Time` 两列，本文分桶统一按**升起时刻**起算（保守口径：若实际从命中时刻起算，A 桶只会更多、B 桶不会更多） |

**分桶规则**：`tt_id` 非空 → C；否则以 `clearstate` / `alarmclearedtime` 计算持续时长，`≤ Assign Delay` → A，`> Assign Delay` → B，`assign_delay` 缺失 → D（无法判定）。
证据来源：历史告警只读接口（`/api/fm-history/v1/hisalarms/pageinfo`）7 天窗口，`alarmcodeconds=[{restype: zte.ran.nodeb, alarmcode: 9990}]`，按 `id` 去重共 1,504 行，其中 `relationflag=1` 138 行。

| 桶 | 条数 | 占比 | 判定 |
| --- | --- | --- | --- |
| **A｜延迟内自行恢复** | **136** | **98.6%** | 预期不建单，**不算缺口** |
| **B｜超延迟仍无单（真缺口）** | **0** | **0.0%** | 无 |
| **C｜有单** | **2** | **1.4%** | 见下表 |
| D｜delay 缺失、无法判定 | 0 | 0.0% | — |

C 桶明细（说明它们与 A 桶的唯一差别是「告警持续超过了延迟」）：

| AID | 站点 | 升起 | 清除 | 持续 | Assign Delay | 命中规则 | TT |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1764220905133 | 4344 / Duala Market 2 | 1793632115000 | 1793633255000 | **19 min** | 900s | `SITE_OUTAGE-imported` | TT202611020056 |
| 1764220394832 | 5096 / Mamba Point | 1793367093000 | 1793368046000 | **15 min 53 s** | 900s | `SITE_OUTAGE` | TT202610300051 |

**结论**：9990 的「133/135 无单」是**延迟窗口内自行恢复**，属预期行为；**B 桶为 0，9990 没有建单缺口**。原报告中「规则名 100% 命中但建单率 1.5%」「9990 建单率塌陷」「命中规则名 ≠ 建单的独立断点」等表述**全部作废**。

**样本按同一口径复核**：`199083023`（AID 1764221015205）`assign_rulename=null`、**`assign_delay=null`** → 它**从未命中任何自动派单规则，也就没有延迟起点**，延迟口径不适用；且查询时已持续 3h33m、复核时 **4.18h** 仍未清除（`clearstate=0`）。因此「延迟内恢复」不能解释它，**缺单判断依然成立**。
（措辞订正：原文说「远超任何合理延迟窗口」并不精确——查询时 3h33m 尚未超过最长的 14400s（4h）族，但该族只属于 ERA / COOL 站点且本样本未命中；现在 4.18h 已超过全部已知延迟取值。）

**其他「看似缺口、其实预期」的模式（一并纠正）**

| 模式 | 是否预期 | 判定依据 | 状态 |
| --- | --- | --- | --- |
| 压缩子告警（`relationflag=2`）`tt_id` 为空 | **是，预期** | 压缩链路由父告警（`relationflag=1`）建单，子告警只是跟随；`relationflag` 语义见 2.1 节 | 已按设计确认 |
| 告警在 `Assign Delay` 内清除 | **是，预期** | 本文 1.3 分桶；9990 实测 A=136/138 | **已实证** |
| `SITE_OUTAGE-imported` 接管后「旧规则名不再命中」 | **是，预期** | `docs/eflow-dispatch-rule-gap-checklist.md` Q1/Q2；本文 C 桶中 1 条正是由 `SITE_OUTAGE-imported` 建的 TT | 已实证（该规则确实建单） |
| 只对 P1 / 特定 severity 建单 | **可能是预期** | `Push_Rules` 中 ID 253 的条件为 `alarmCode=9920 且 ticketSeverity=P1` | **未证实**（9990 的 C 桶样本未涉及该规则） |
| `9995` / `99933` 无 TT | **未知** | 尚未按 delay 口径分桶 | **待复核，不得计为缺口** |

---

## 二、过滤链梳理（从接口到 TT）

```
eFlow FM API（active / history / relatedAlarms）
        │ ① 本地同步：ALARM_CONDITION 白名单 + 分页 + TT-only 过滤
        ▼
本地 realtime_alarm / history_alarm      ← 只读审计视角（有盲区）
        │
eFlow 服务端（UEA / config-center）：
        │ ② 压缩规则（Alarm_Rules，本厂商 OUTAGE 规则集）
        │    relationflag / parentinfo 是压缩结果的**唯一可观测输出**
        ▼
        │ ③ 自动派单规则(103) —— 不在本地镜像，只在结果里留 Assign RuleName
        ▼
TT（工单）
        │ ④ ttPushOrderRule（FOAccept / BOAccept）—— 本地镜像 143 条，作用于**已存在**的 TT
        ▼
WO / 处理组
        │ ⑤ eflow_tt 同步入库
        ▼
本地 eflow_tt + eflow_push_rules_checker 评估
```

### 2.1 各层判定条件与代码位置

| 层 | 判定条件 | 代码 / 规则位置 | 本样本结果 |
| --- | --- | --- | --- |
| ① 采集条件 | `alarm_code_conds` 白名单 16 项（`99933,9920,9995,9981,9991,9990,9970,9971,9910,9980,4758` 等 + restype） | `backend/services/eflow_alarm_config.json:9-74` | ❌ 不含 199083023 / 199083022 |
| ① 采集窗口 | active 全量；history `his_alarm_hours=48`、`his_alarm_days_back=1`、`his_alarm_page_size=5000` | `backend/services/eflow_alarm_config.json:5-8`；`backend/services/eflow_alarm_service.py:220`（active 用 `ALARM_CONDITION`）、`:300`（history 用 `HIS_ALARM_CONDITION`） | 不适用（本地不采） |
| ① 入库过滤 | **只保留 `tt_id` 非空的行** | `backend/services/eflow_alarm_service.py:265-278`（`_filter_rows_with_tt_id`），`:791` 调用 | ❌ 无 TT → 连 history 也不进 |
| ② 压缩 | 本厂商 OUTAGE 规则：`zte-3g-sitedown`（3G）、`zte-4g-siteoutage`（4G）、`zte-2g-siteoutage`（2G）、`mwlink-outage-new`、`zte-3g-celloutage`、`csd-outage`；`mpf-outage` **DISABLED** | `eflow_alarm_rules.xlsx` `Alarm_Rules` 第 9 / 10 / 11 / 12 / 14 / 16 / 19 行 | ❌ 断点①（见 1.1）；`mpf-outage` 关闭也解释了本站 7 天无 `99933` |
| ② 压缩键 | `rootResType + siteAlarmCode + (cellAlarmList 或 relationAlarmCode)`；输出 `parentinfo` / `relationflag`（0=原始、1=Root、2=Secondary、3=Secondary Root） | 规则参数列 `siteAlarmNeType` / `siteAlarmCode` / `cellAlarmList` / `relationAlarmCode` / `supportrelation` / `cellBlock` | `relationflag=0`、`parentinfo=null` |
| ③ 建 TT | 自动派单规则(103)：`siteSubType` / `assetType` / `alarmCode` / `reasonType` / `ticketSeverity` | **本地无镜像**；结果字段 `assign_rulename` / `tt_id` 是唯一实证 | ❌ `assign_rulename=null`、`tt_id="empty"` |
| ④ 推单路由 | `ttPushOrderRule`：`alarmCode` / `siteSubType` / `assetType` / `reasonType` / `ticketSeverity` / `vipSite` / `hubSite` / `downstreamSites` / `netWorkType`；触发步骤 `FOAccept` | `eflow_push_rules.xlsx` `Push_Rules` 第 2 / 3 / 58 / 59 / 32 / 57 / 136 行；求值 `backend/services/eflow_rules/eflow_push_rule_eval.py:86-90`（已知字段白名单）、`:115-119`（优先级升序→条件数降序→ID 升序） | 未到达（无 TT） |
| ⑤ 本地评估 | 取最新 N 条**有 alarm_code** 的 `eflow_tt`，`ORDER BY created_time DESC` | `backend/services/eflow_rules/eflow_push_rules_checker.py:96-137` | 不适用（表内 0 条） |

### 2.2 关系链解析的代码缺陷（影响可观测性，不直接改压缩结果）

`backend/services/eflow_ume_link.py:202`：

```python
"relationflag": root_relationflag or 1,
```

`relationflag=0`（原始告警，正是本样本）被 `or 1` 静默改写成 1。随后 `backend/services/eflow_ume_link.py:285-296` 把该值放进 `relatedalarmrequestbeans` 请求 `fm-history/relatedAlarms/table`。后果：**所有 `relationflag=0` 的原始告警，关系链查询恒为空**——排查「这条为什么没被压缩」时会被这个 bug 误导成「接口没数据」。调用方 `backend/routers/eflow_qa.py:459` 与 `:515` 均未显式传 `root_relationflag`，全部踩中。

---

## 三、样本逐层实证

### 3.1 原始行关键字段（AID 1764221015205）

| 字段 | 值 | 判读 |
| --- | --- | --- |
| `alarmcode` / `codename` | `199083023` / `NodeB is out of service` | 3G 站点退服 |
| `moc` / `restype` | `zte.ran.nodeb` / `zte.ran.nodeb` | 与 `zte-3g-sitedown` 的 `rootResType` / `siteAlarmNeType` 一致 |
| `Site ID` / `Site Name` / `type` | `3467` / `Nwrokia` / `3467-3G` | 与规则站点维度一致 |
| `positionname` | `...OriginalSiteName:Nrokwia` | 名称拼写 `Nrokwia` ≠ `Nwrokia`（按名字 join 会漏） |
| **`relationflag`** | **`0`** | **未压缩，是原始告警** |
| **`parentinfo`** | **`null`** | **无压缩父告警** |
| **`tt_id` / `append_ttid`** | **`"empty"` / `null`** | **无工单** |
| **`assign_rulename`** | **`null`** | **未命中自动派单规则(103)** |
| `assigned_status` / `reason_type` | `"0"` / `null` | 派单未发生 |
| `clearstate` | `0` | active（排除「已清除所以查不到」） |
| `alarmraisedtime` / `servertime` | `1793686669000` / `1793686669685` | 2026-11-03 **06:17:49 UTC**（14:17:49 +08），同一秒 |
| `durationname` | `3h 33min 18s` | 查询时仍在持续 |
| `originalspecificproblem` / `oss_specific_problem` | `NCP link failure` / `NCP link failure` | **Iub/RNC 链路故障**，非物理断电断站 |
| `object_name` / `original_me` | `MRNC:RNC=105@NODEB=3467` / `RNC105(105)` | 对象锚在 RNC105 下的 NODEB 3467 |
| `perceivedseverityname` | `Critical` | 高等级（排除「level 被过滤」） |
| `cell_name` | `"empty"` | **无小区维度** → 拿不到 199083022 输入 |
| `ran_site_type` / `hub_site_flag` / `downstream_site_count` | `REGULAR` / `YES` / `13` | hub 站，13 个下游——影响面大 |
| `transmission_type` | `MW` | 微波传输 |

### 3.2 逐层状态表

| 层 | 检查项 | 结果 | 数据来源 / 查询条件 |
| --- | --- | --- | --- |
| 接口原始行 | active 接口能否按 id 取到 | ✅ 有 | `find_alarm_by_id`（`secondarycondition.id = 1764221015205` 精确匹配） |
| 入库（realtime） | `realtime_alarm` 是否有该 AID | ❌ 无（白名单不含该码） | `eflow_alarm_config.json:9-74` |
| 入库（history） | `history_alarm` 是否有该 AID | ❌ 无（且 history 只留 TT 行） | `eflow_alarm_service.py:265-278,791` |
| 压缩子告警 | `relationflag=2` + `parentinfo` 指向 9990 | ❌ `relationflag=0`、`parentinfo=null` | 接口原始行 |
| 压缩父告警 | 本站 7 天内 9990 / 9991 | ❌ **0 条**（三种关联方式均 0） | `Site ID=3467` / `alarmkey LIKE '%3467%'` / `positionname LIKE '%3467%' OR LIKE '%Nwrokia%'` |
| 压缩输入 199083022 | 本站事故窗口内小区退服 | ❌ **0 条**（全窗口 41 条全在别站） | `alarmcode=199083022`，06:00–06:45，按 `Site ID` 分组 |
| 关联码输入 | 9971 / 9981 / 2365980930 / 198097062 / UMM 2365981958 | ❌ 命中本站 0 条（9991 全窗口 8 条也 0 条本站） | 05:30–07:30 窗口，按 `Site ID` 过滤 |
| 自动派单 | `assign_rulename` | ❌ null | 原始行 |
| TT | `tt_id` / `eflow_tt` | ❌ `"empty"` / 表内 0 条 | `eflow_tt WHERE alarm_code='199083023'` = 0（全表 40,614） |
| 同站同刻 9995 | `relationflag=1`、`reason_type=POWER`、hub=YES | ⚠️ Root 但 `tt_id=null`、`assign=null` | AID `1764221015309` |

### 3.3 压缩层的统计口径证据（证明这不是偶发）

对 `199083023` 取最新 2000 条历史行（7 天总量 7,772 行，历史接口单页上限 2000，故为近似窗口）：

| 指标 | 数值 |
| --- | --- |
| `relationflag=2`（有 `parentinfo`，成功压缩） | **1,670（83.5%）** |
| `relationflag=0`（无 `parentinfo`，**未压缩**） | **330（16.5%）** |
| `relationflag=1`（Root） | 0 |
| `Assign RuleName=null` | **2,000 / 2,000** |
| `TT ID=empty` | **2,000 / 2,000** |

未压缩率 16.5% 是这条规则的结构性漏损，不是单点故障。进一步分组（rf=0 的 330 条）：按站点 top 为 R2 53、Troupe 37、Johnsonville 32、Lango Number 2 26、Ducor 25；**`IubLink == SiteID` 时 rf=0 率 92/901（10.2%），`IubLink ≠ SiteID` 时 238/1099（21.7%）**——即「对象挂在 IubLink 上而非站点上」时，压缩规则更容易失效（压缩键按站点聚合，无法把 IubLink 告警归到站点）。

### 3.4 派单层证据（为什么压缩成功了也可能没单）

| 告警码 | 7 天行数 | rf=1（Root） | 有 `Assign RuleName` | 实际有 TT |
| --- | --- | --- | --- | --- |
| `199083023` | 7,772 | 0 | **0 / 2,000**（抽样；且 `assign_delay` 为空） | **0 / 40,614**（全表） |
| `9990` | 1,504（7 天去重） | 138 | **138 / 138（100%）** | **2 条 = C 桶**；A=136 / B=0 / C=2（见 1.3） |
| `99933` | 646 | 646 | — | 270 有 / 376 无（**未按 delay 分桶，不能判缺口**） |
| `9995` | 195 | — | 有（SITE_OUTAGE 等） | 35 有 / 160 无（**未按 delay 分桶，不能判缺口**） |
| `199083022` | 7,889 | — | 有 `CELL_OUTAGE*` | 多为空（压缩子告警形态，未逐一验证父单归属） |

**2026-11-03 修订（原结论已推翻）**：原报告把 `9990`「规则名 100% 命中但只有 2 条 TT」称为「建单率塌陷／最尖锐的发现」，这是**口径错误**——`Assign Delay`（9990 实测为 `900s` 103 条、`14400s` 35 条）决定告警在窗口内清除时**本就不建单**。按 delay 分桶后：**A=136、B=0、C=2**，9990 **没有建单缺口**；TT 创建链路并未出现独立断点。
`9995` / `99933` 的「无 TT」数字同样**不能直接当缺口**，两者尚未按 delay 口径分桶（列为待复核，见第四节）。`docs/eflow-dispatch-rule-gap-checklist.md` Q1/Q2 记录的是「规则名覆盖变化」这一独立事实，与本节的延迟口径不冲突。`199083023` 的特殊性在于 `assign_rulename=null` 且 `assign_delay=null`——**它从未进入任何规则的延迟窗口**，所以延迟解释不适用。

---

## 四、同类会被遗漏的告警清单（按影响排序）

| # | 类别 | 触发条件 | 影响范围 | 验证方式 |
| --- | --- | --- | --- | --- |
| **P0-1** | **「仅压缩输入」站断码**（5 个：`199083023`、`198094422`、`2114322696`、`198200011`、`199087337`） | 压缩规则未触发（缺小区告警 / 关联码 / 对象不在站点） | 所有 3G / 4G / 2G 站断，且**永不建 TT**（不在任何派单规则） | 用码集查 `eflow_tt.alarm_code` 命中数（全 0）；查 `assign_rulename` 空率 |
| **P0-2** | **`IubLink ≠ SiteID` 的对象锚定告警** | 传输 / 链路故障导致对象挂在 IubLink 而非站点 | `199083023` rf=0 率 21.7% vs 10.2%，约 **2.1 倍** | 按 `object_name` / `positionname` 拆 `IubLink==SiteID` 与 `!=` 两组比 rf=0 率 |
| **P0-3** | **`supportrelation=true` + `cellBlock=true` 的规则组合** | 小区告警被阻塞后，规则需要的 `cellAlarmList` 输入不可见 | 3G / 4G / 2G 三条 OUTAGE 规则全部（`Alarm_Rules` 第 9/10/11 行都是 `cellBlock=true`） | 取 rf=0 样本，±120s 同站查 `cellAlarmList` 码，为 0 即命中此模式 |
| **P1-1** | **`9995` / `99933` 的「无 TT」尚未按 delay 分桶（待复核，目前不计缺口）** | 只统计了「有/无 TT」，未扣除延迟窗口内自行恢复的告警 | `9995` 160/195 无 TT、`99933` 376/646 无 TT | 按 1.3 的 A/B/C/D 口径重算；只有 B 桶才计缺口 |
| **P1-2** | **REGULAR 99933 无 FOAccept 路由** | `Push_Rules` 200/201 的 `alarmCode` 不含 `99933`，仅 ERA 规则 203 含 | 所有非 ERA 的电源断站 `99933` | 用 `alarmCode` 条件反查 `Push_Rules` 覆盖矩阵 |
| **P1-3** | **`mpf-outage` DISABLED** | 电源类断站衍生关闭（`Alarm_Rules` 第 12 行） | 2G / 3G / 4G 任一断站 + 时间窗内电源告警 → 不再派生 `99933`（`timeWindow1=259200s`） | 查某站断站告警前后 3 天内是否有 `99933` |
| **P1-4** | **本地 `history_alarm` 只留 TT 行** | `_filter_rows_with_tt_id` | 所有「应建单未建单」的告警在本地**不可审计**（只能靠 API 直查） | `history_alarm` 行数 vs 接口 history 行数 |
| **P2-1** | **`relationflag=0` 关系链恒空**（代码 bug） | `eflow_ume_link.py:202` 的 `or 1` | 所有原始告警的关系链排查（`eflow_qa.py:459/515`） | 用 rf=0 的 AID 调 `resolve_alarm_chain`，返回空即命中 |
| **P2-2** | **站点名拼写不一致** | `site_name=Nwrokia` vs `positionname` 的 `OriginalSiteName:Nrokwia` | 任何按名称 join 的本地关联都会漏（eFlow 自身按 Site ID 关联，不受影响） | `site_name` 与 `positionname` 抽名做 diff |
| **P2-3** | **hub 站影响面放大** | `hub_site_flag=YES` + `downstream_site_count=13` 但未建单 | 单条漏单实际覆盖 13 个下游 | `hub_site_flag=YES AND tt_id IS NULL` 计数 |
| **P3-1** | **关联码覆盖不全** | `relationAlarmCode` 只列固定几码（`zte-3g-sitedown` 仅 5 个） | 新型传输告警码（不在清单）无法触发压缩 | 取 rf=0 样本的 `alarmcode` 分布，看是否有高频码不在任何 `relationAlarmCode` |
| **P3-2** | **`perceivedseverity` 维度未知** | 压缩规则表无 level 条件，但派单规则有 `ticketSeverity` | 低等级告警可能被 `ticketSeverity=P1` 类规则排除 | 按 `ticketSeverity` 条件反查 `Push_Rules` |

---

## 五、「设计如此」与「规则缺陷」的区分

### 5.1 规则设计如此（不算 bug，但需业务确认）

1. **`cellBlock=true` 的设计意图**：小区告警被抑制以免刷屏，代价是压缩规则只认「站点 + 小区」的完整形态。这是**配置取舍**，不是代码 bug——但意味着 Iub / 传输类退服天然落在规则外（这是 P0-3 的根源，需业务决定是否接受）。
2. **`mpf-outage` 处于 DISABLED**：电源断站衍生被主动关闭，因此 `99933` 不再从电源告警派生。若这是 2026-11-02 的规则调整，属预期行为（需管理员确认）。
3. **`SITE_OUTAGE-imported` 接管 REGULAR**（见 `docs/eflow-dispatch-rule-gap-checklist.md` Q1/Q2）：11-02 后 REGULAR `9995` 不再建单是**规则变更的预期结果**，但变更未覆盖「整场事故」场景，需补一条事故级兜底。
4. **本地只采 16 个告警码 + 只留 TT 行**：这是本地审计视图的口径选择，不是 eFlow 行为。
5. **告警在 `Assign Delay` 窗口内自行清除 → 不建单**：这是规则本意（防闪断），不是漏单。9990 已实证 A=136/138（见 1.3）；压缩子告警无 TT 同理属预期（由父告警建单）。

### 5.2 规则缺陷（应当修）

1. **`eflow_ume_link.py:202`** `root_relationflag or 1` —— 明确的代码 bug，`0` 是合法值被 `or` 吞掉。修复：`1 if root_relationflag is None else int(root_relationflag)`。
2. **5 个「仅压缩输入」码不在任何派单规则** —— 覆盖矩阵缺口，压缩失败即永久孤儿。
3. ~~**`9990` 命中规则名但 133/135 不建单** —— 派单执行链路缺口~~：**2026-11-03 修订已推翻**。按 `Assign Delay` 分桶 A=136 / B=0 / C=2，属预期行为（延迟窗口内恢复），**不是缺陷**；`9995` / `99933` 是否同属预期尚未分桶验证。
4. **`Push_Rules` 200/201 不含 `99933`** —— REGULAR 电源断站的 FOAccept 路由空档。
5. **`zte-3g-sitedown` 的关联码清单过窄**（仅 `2365980930,198097062,9971,9981,9991`），未包含「单告警即可派生」的分支。
6. **本地 history 的 TT-only 过滤** —— 让「漏单」在本地完全不可见，属观测性缺陷。

---

## 六、修复建议（按优先级）

### P0（当周）

**P0-1 补齐 5 个孤儿码的派单兜底**
- 改哪里：eFlow config-center 的自动派单规则(103)，把 `199083023`、`198094422`、`2114322696`、`198200011`、`199087337` 加入站点级建单规则的 `alarmCode` 条件。
- 验收：`eflow_tt` 中这 5 个码的周新增数从 0 变为 >0；且与压缩是否成功无关（压缩失败也建单）。
- 风险：可能造成重复建单（压缩成功时 `9990` 与原始码同时建单）——需要在规则里加「同站同制式 10 分钟内去重」或由 `9990` 优先。

**P0-2 修 `eflow_ume_link.py:202`**
- 一行改动，只影响排查工具，不影响生产派单；改后 `relationflag=0` 的样本能正常拉到关系链。

**P0-3 把 `199083023` 并入 `mwlink-outage-new` 的 `siteAlarmCode`**
- 该规则当前 `siteAlarmCode=9970,9980,9990,9910,9920`（`Alarm_Rules` 第 14 行），root=`9995`、`timeWindow1=180s`、`relationTimeWindow=360s`。加入 199083023 后，NCP / link 类 NodeB 退服会派生 `9995`，而 `9995` 已有 SITE_OUTAGE 派单规则（其是否存在 B 桶真缺口尚待按 delay 口径复核，见 P1-1）。
- 验收：复跑 Nwrokia 场景，`9995` 的 `parentinfo` 应指向该站 `199083023`。

### P1（本月）

**P1-1 复核 `9995` / `99933` 的「无 TT」是否真缺口**
- 用 1.3 同一口径重算：取 7 天 rf=1 行，按 `Assign Delay`（`900s` / `14400s`）+ `alarmclearedtime` 分 A/B/C/D。
- 只有 **B 桶（超过延迟仍无 TT）** 才计缺口；A 桶一律标记为「预期不建单」，**不得计入漏单率**。
- 验收：给出两者的 A/B/C/D 四桶条数与占比；若 B 桶显著 >0，再按站点/规则名拆解。

**P1-2 给 REGULAR `99933` 补 FOAccept 路由**
- 在 `Push_Rules` 规则 200/201 的 `alarmCode` 条件里加入 `99933`（当前仅 ERA 规则 203 含）。

**P1-3 决定 `mpf-outage` 是否恢复**
- 若恢复：注意 `timeWindow1=259200s`（3 天）会让断站派生延迟极大，需评估误派生风险。

**P1-4 本地审计补一条「无 TT 也应可见」的路径**
- 建议：`history_alarm` 增加一个旁路表（或把 `_filter_rows_with_tt_id` 改为可配置开关），否则「该建单未建单」永远只能靠 API 手查。

### P2（本季）

- 压缩规则纳入 `IubLink ≠ SiteID` 的对象模型（或增加「按 `object_name` 中的 `NODEB=` 段回填 Site ID」的预处理）。
- 站点名归一（`Nwrokia` / `Nrokwia`）——至少在本地关联前做别名表，避免未来按名字 join 的代码出错。
- 给 `relationAlarmCode` 加「高频未压缩码」巡检：每周对 rf=0 的 `alarmcode` 做 top-N，与规则清单 diff。

---

## 七、不确定性说明

1. **压缩规则的内部执行不可观测**：压缩在 eFlow 服务端（UEA / config-center）执行，本地只能看到 `relationflag` / `parentinfo` 的**结果**。因此「`zte-3g-sitedown` 为何没触发」的结论是**基于输入全缺的推断**（`199083022` / `9990` / `9991` / 关联码 / UMM 五路全 0 + `cell_name="empty"`），不是规则引擎日志的直接证据。要拿直接证据需 eFlow 侧开压缩规则调试日志。
2. **自动派单规则(103) 本地无镜像**：`eflow_push_rules.xlsx` 只覆盖 `ttPushOrderRule`（FOAccept / BOAccept，143 条），**不包含**负责建 TT 的自动派单规则。因此「`199083023` 未命中派单」的实证依据是 `Assign RuleName=null` 与 `eflow_tt` 0 条这两个**结果字段**，不能断言「eFlow 里没有任何规则提到它」——只可断言「它未被任何规则实际建单」。
3. **7 天统计是近似值**：历史 FM 接口单页上限 2000（请求 `size=5000` 仍返回 2000，`from` 翻页会重复），统计已按 `id` 去重，但「`9990` 7 天 1536 / 1538 条」出现过两种计数，差异来自翻页重复行的去重边界。趋势结论（rf=1 全有规则名、仅 2 条有 TT）不受影响。
4. **`eflow_push_rules_check_latest.json` 的统计不能直接当「漏单率」**：其样本是最新 1000 条**已有 TT** 的 `eflow_tt`，`unmatched=592`、`should_have_wo=159`、`mismatch=160`、`correct=248`、`dispatch_unparsed=298` 的分母是「已建单的样本」，**天然看不到「根本没建单」的告警**——这正是本样本的盲区。
5. **站点归属**：3467 是 **ZTE** 站点（`organization=ZTE`、BSC1 / RNC105），不是猜测的 Nokia 站点；`ran_site_type=REGULAR`、`site_class=P1`、`hubsite=Yes`。若按「Nokia 设备」去找，会找不到这条。
6. **时间字段口径**：`alarmraisedtime` / `servertime` 是 13 位毫秒（`1793686669000` → 06:17:49 UTC），`alarmOccurTime` 是 10 位秒；两者不可混用比较。
7. **规则镜像的采集时点**：`eflow_alarm_rules.xlsx` / `eflow_push_rules.xlsx` 采集于 2026-11-02（后者 10:20），反映的是镜像时点的配置，不等于当前 config-center 的实时状态，最终以 eFlow 配置中心原文为准。
8. **延迟窗口的起算点未证实**：接口同时提供 `alarmraisedtime`、`Assign Start Time`、`First Match Time`，代码侧只解析 `assign_delay` 的数值（`backend/routers/alarm_dashboard.py:74-76`），未见「从哪个时刻起算」的实现。本文统一按**告警升起时刻**起算，这是保守口径（若实际从规则命中时刻起算，A 桶只会更多、B 桶不会增加）。
9. **分桶只做了 9990**：`9995` / `99933` / `199083022` 尚未按同一口径重算，因此本报告中它们的「无 TT」数字**不得**作为缺口结论；其真实缺口需等 P1-1 复核完成。
10. **`relationflag=2` 子告警是否由父告警建单未逐条验证**：本文按 `relationflag` 语义（1=Root、2=Secondary）判定「子告警不建单属预期」，但未逐条把子告警的 `parentinfo` 与父告警的 `tt_id` 做配对验证。

---

## 八、证据附录（可复现的查询条件）

> 所有查询均为只读；接口调用使用 FM 只读端点（`/api/fm-active/v1/activealarms/table`、`/api/fm-history/v1/hisalarms/pageinfo`、`relatedAlarms/table`），未记录任何凭据或主机地址。DB 走 `backend.database.get_raw_connection()`（pg 模式，`?` 占位符自动转 `%s`）。

| 目的 | 查询条件 / 方法 |
| --- | --- |
| 定位样本 | active / history `secondarycondition.id = 1764221015205` 精确匹配 |
| 站点模糊 | `Site Name` ILIKE `%Nwro%` / `%Nrokw%`；`Site ID = 3467` |
| 压缩状态 | 同码历史行统计 `relationflag` 分布 + `parentinfo IS NULL` 计数 |
| 父告警缺失 | `Site ID=3467` 且 `alarmcode IN (9990,9991)`，7 天 = 0；另用 `positionname LIKE '%3467%'`、`alarmkey LIKE '%3467%'` 复核 = 0 |
| 小区输入缺失 | `alarmcode=199083022`，窗口 06:00–06:45，按 `Site ID` 分组 → 41 条，`3467` 计 0 |
| 关联码输入 | 窗口 05:30–07:30，码 `9971,9981` / UMM `2365981958` / `2365980930,198097062`，按 `Site ID` 过滤 = 0 |
| 派单 / TT | `assign_rulename IS NULL AND tt_id='empty'`；`eflow_tt WHERE alarm_code='199083023'` = 0 / 全表 40,614 |
| 规则覆盖矩阵 | `eflow_push_rules.xlsx` `Push_Rules` 逐行解析 `alarmCode` 条件，与 5 个孤儿码做集合差 |
| 建单率（**须按 delay 分桶**） | 取 rf=1 行 → `Assign Delay`（`900s` / `14400s`）+ `alarmclearedtime` / `clearstate` → 分 A（`≤delay`）/ B（`>delay` 且无 TT）/ C（有 TT）/ D（delay 缺失）；只有 B 桶计缺口 |
| delay 字段取证 | 告警行 `Assign Delay` 列（`backend/services/eflow_alarm_service.py:158`）；解析 `backend/routers/alarm_dashboard.py:74-76`、`backend/routers/gis.py:163` |
| 代码位置 | 见第二、三、五节各条的 `文件:行号` |

### 8.1 规则镜像定位速查

| 规则 | 规则 ID | 规则包 | 镜像位置 |
| --- | --- | --- | --- |
| `zte-3g-sitedown` | `rule_1788853932033` | OUTAGE | `Alarm_Rules` 第 10 行 |
| `zte-4g-siteoutage` | `rule_1788854291338` | OUTAGE | `Alarm_Rules` 第 9 行 |
| `zte-2g-siteoutage` | `rule_1788853290890` | OUTAGE | `Alarm_Rules` 第 11 行 |
| `mpf-outage`（DISABLED） | `rule_1774597491326` | OUTAGE | `Alarm_Rules` 第 12 行 |
| `mwlink-outage-new` | 镜像未完整导出 ID，按 `rule_name` 定位 | OUTAGE | `Alarm_Rules` 第 14 行 |
| `zte-3g-celloutage` | 镜像未完整导出 ID，按 `rule_name` 定位 | OUTAGE | `Alarm_Rules` 第 16 行 |
| `csd-outage` | 镜像未完整导出 ID，按 `rule_name` 定位 | OUTAGE | `Alarm_Rules` 第 19 行 |
| FOAccept 200 / 201 / 203 / 204 | `200` / `201` / `203` / `204` | ttPushOrderRule | `Push_Rules` 第 2 / 3 / 58 / 59 行 |

---

*本报告只读产出，未修改数据库、未改生产数据、未在数仓侧做任何写操作，也未重启任何生产进程。审计期间使用的一次性只读脚本（`_tmp_eflow_*.py`、`_tmp_site_*.py` 等）与产物（`TMP/_eflow_*.txt`）已清理。*
