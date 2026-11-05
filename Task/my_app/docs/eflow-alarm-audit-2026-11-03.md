# eFlow 告警「压缩 / 派单」规则审计报告（2026-11-03）

> 审计对象：`alarmcode=199083023`、站点 `Nwrokia`（Site ID 3467）、AID `1764221015205`
> 审计方式：全程只读（eFlow FM 只读接口 + 本地 PO 只读查询 + 本地规则镜像 xlsx），未做任何写操作
> 审计时间：2026-11-03（样本在查询时仍为 active，`durationname="3h 33min 18s"`）
> **2026-11-03 修订：按 Assign Delay 口径校正 9990 建单率结论。** 原文「9990 命中规则名 100% 但建单率约 1.5%／建单率塌陷」**已作废**——告警在延迟窗口内自行清除本就不该建单。按 7 天 138 条 `relationflag=1` 分桶：**A=136（延迟内恢复，预期不建单）、B=0（真缺口）、C=2（有单）**。详见 1.3 与 3.4 节。
> **2026-11-04 修订：把同一口径外推到 `9995` / `99933` / `199083022`。** 三码均已分桶（明细见 1.4）：`9995` rf=1 **A=84 / B=2 / C=28 / D=36**；`99933` **A=321 / B=12 / C=241 / D=0**；`199083022` 原始告警（rf=0）**A=457 / B=4 / C=2 / D=507**。真缺口为 `9995` B=2、`99933` B=12、`199083022` rf=0 B=4、`199083022` 子告警链级 B=27/D=12；`relationflag=2/3` 的子告警无 TT 属结构预期（由父告警建单），不重复计缺口。
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
原判断「`9990` 命中规则名 135 条但仅 2 条有 TT、建单率塌陷」**已被推翻**：`Assign Delay` 是告警命中自动派单规则后到建 TT 之间的延迟窗口（出处与取值见 1.3），告警在窗口内自行清除本就**不应建单**。按 7 天 138 条 `relationflag=1` 分桶：**A 桶（延迟内恢复）136 条、B 桶（超延迟仍无单）0 条、C 桶（有单）2 条**——9990 **没有真缺口**。真正的规则缺口仍在 FOAccept 侧：`Push_Rules` 200/201 的 `alarmCode` 不含 `99933`，只有 ERA 专用规则 203 含它，REGULAR 站点的电源断站 `99933` 建了 TT 也推不出去。另：`9995` / `99933` 已于 **2026-11-04** 按同一口径分桶（见 1.4）：`9995` B=2、`99933` B=12 为真缺口，其余为延迟内恢复或有单——不要再把「无 TT 数」直接当缺口。

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
| `relationflag=3`（Secondary Root）无 TT | **是，预期** | 它是派生次级根，TT 归父告警：`9995` 47 条全部有 `parentinfo`，父桶 C=31 / A=10 / B=6 | **已实证（2026-11-04）** |
| `relationflag=2` 子告警（`199083022`）无 TT | **是，结构预期** | 6,918 条全部有 `parentinfo`；可解析的 2,345 条父链终端 A=1,841 / B=27 / C=465 / D=12 | **已实证（2026-11-04）** |
| `9995` / `99933` 无 TT | **部分预期、部分真缺口** | `9995` A=84 / B=2 / C=28 / D=36；`99933` A=321 / B=12 / C=241 / D=0 | **已实证（2026-11-04）** |

### 1.4 四桶口径外推：9995 / 99933 / 199083022（2026-11-04 修订）

**查询口径（与 1.3 一致，仅换告警码）**

- 端点：`/api/fm-history/v1/hisalarms/pageinfo`（只读）。
- 窗口：2026-10-27T17:46Z ~ 2026-11-03T17:46Z，按 7 个 24h 窗口查询，`size=2000`、`from` 翻页、按 `id` 去重。
- 条件：`alarmcodeconds=[{restype: "zte.ran.nodeb", alarmcode: X}]`，沿用 `HIS_ALARM_CONDITION`（`backend/services/eflow_alarm_service.py:107-116`）；其中 `extensionconds.maintainstatus=["0"]`（同文件 `:114`）会排除维护态告警，本结论只覆盖非维护态。
- 实测行数：`9995` **197**、`99933` **574**、`199083022` **7,888**。与 11-03 基线的 195 / 646 / 7,889 略有差异，原因是 7×24h 窗口边界与 `id` 去重，不是数据矛盾。
- 保守口径：延迟一律按 `alarmraisedtime` 起算；`alarmclearedtime` 缺失或 ≤0 时按查询时刻计持续时长。**`clearstate` 在本批响应中恒为 `0`、`clearstatename` 恒空，不能用于判定 active/cleared**，故不使用该字段。
- `relationflag` 分列：`1`=Root（唯一建单主体）、`2`=Secondary（压缩子告警）、`3`=Secondary Root（派生次级根，仍跟随父告警），语义见 2.1 节。

**delay 分布（先看桶边界）**

| 告警码 | `Assign Delay` 取值 | 空值 | 是否有 14400s 长延迟族 |
| --- | --- | --- | --- |
| `9995` | `900s` **161**（rf=1 114 + rf=3 47） | **36**（rf=1） | **否**，全部 900s |
| `99933` | `900s` **256**、`14400s` **318** | 0 | **是**：`SITE_OUTAGE_ERA` / `SITEOUTAGE_REGULAR_COOL`，与已知 ERA/COOL 4h 族一致 |
| `199083022` | `900s` **7,369** | **519**（rf=0 507 + rf=2 12） | **否**，全部 900s |

> 桶边界因此不同：`9995` / `199083022` 只需 900s 一条边界；`99933` 必须按 900s / 14400s 分别判定——若统一用 900s，会把 ERA/COOL 族中「900s~4h 之间恢复」的告警误判为 B。

**`9995`（rf=1，n=150）**

| 桶 | 条数 | 占比 | 判定 |
| --- | --- | --- | --- |
| **A｜延迟内恢复** | 84 | 56.0% | 预期不建单，**不算缺口** |
| **B｜超延迟仍无单** | **2** | **1.3%** | **真缺口** |
| **C｜有单** | 28 | 18.7% | — |
| **D｜delay 缺失（从未命中规则）** | **36** | **24.0%** | **规则覆盖缺口** |

`9995` 另有 `relationflag=3` 47 条（Secondary Root）：自身按 900s 口径看似 B 的 26 条，逐条追 `parentinfo` 后父告警桶为 **C=31 / A=10 / B=6**——前 20 条的父为 C/A（预期），后 6 条的父正是下表 `99933` B 桶的 Lofa Bridge / Gold Medal / Jacob Town 同一条根告警，**属同一缺口，不重复计入**。

**`99933`（rf=1，n=574）**

| 桶 | 条数 | 占比 | 判定 |
| --- | --- | --- | --- |
| **A｜延迟内恢复** | 321 | 55.9% | 预期不建单，**不算缺口** |
| **B｜超延迟仍无单** | **12** | **2.1%** | **真缺口** |
| **C｜有单** | 241 | 42.0% | — |
| **D｜delay 缺失** | 0 | 0.0% | 无 |

> `14400s` 族全部落在 ERA/COOL 规则；B 桶 12 条中 11 条为 `SITE_OUTAGE`（900s）、1 条为 `SITE_OUTAGE_ERA`（14400s）——长延迟族也没有自动兜住，超 4h 仍无单那条同样算真缺口。
> 另：`99933` 在最后一个 24h 窗口（11-02T17:46Z~11-03T17:46Z）为 **0 条**，与 `mpf-outage` 于 11-02 停用的时点接近（因果未证实，见 C-6）。

**`199083022`：原始告警（rf=0，n=970）**

| 桶 | 条数 | 占比 | 判定 |
| --- | --- | --- | --- |
| **A｜延迟内恢复** | 457 | 47.1% | 预期不建单，**不算缺口** |
| **B｜超延迟仍无单** | **4** | **0.4%** | **真缺口** |
| **C｜有单** | 2 | 0.2% | — |
| **D｜delay 缺失（从未命中规则）** | **507** | **52.3%** | **规则覆盖缺口** |

**`199083022`：压缩子告警（rf=2，n=6,918）**

这些行 `tt_id` 全空，但**不能按子告警自身时长判 B**——子告警不建单，TT 归属在父链。按 `parentinfo` 沿 9990 / 9991 → 9995 / 99933 追到终端：

| 父链终端 | 条数 | 占比 | 判定 |
| --- | --- | --- | --- |
| A | 1,841 | 26.6% | 预期（父告警延迟内恢复） |
| B | **27** | **0.4%** | **真缺口（父告警超延迟无单）** |
| C | 465 | 6.7% | 预期（父告警有单） |
| D | **12** | **0.2%** | **规则覆盖缺口（父告警 delay 缺失）** |
| 未解析 | 4,573 | 66.1% | 父告警不在本次 9990/9991/9995/99933 数据集内（未证实） |

> 子告警自身按 900s 套算会得到 B=872（12.6%），这是**无效口径**：子告警从不建单，必须看父链终端。链级 27 条 B 集中在 **72nd Road 18 条、Duala Market 2 9 条**；12 条 D 全部挂在同一条 `9995` D 桶根告警（Omega Community，AID `1764220987159`）。

**B 桶明细（真缺口）**

`9995` rf=1（2 条）：

| 站点 | 升起（+08） | 持续 | `Assign Delay` | 命中规则 | AID |
| --- | --- | --- | --- | --- | --- |
| Zowienta(4066) | 2026-10-31 16:15:15 | 1.68h | 900s | `SITE_OUTAGE` | 1764220531463 |
| Flumpa(4104) | 2026-10-28 08:10:10 | 0.40h | 900s | `LINK_OUTAGE_9995_ERA` | 1764219966711 |

`99933`（12 条，按持续时长降序）：

| 站点 | 升起（+08） | 持续 | `Assign Delay` | 命中规则 | AID |
| --- | --- | --- | --- | --- | --- |
| Lofa Bridge(4652) | 2026-10-29 20:17:22 | 9.76h | 900s | `SITE_OUTAGE` | 1764220296067 |
| Does Village (Gborwuzohn)(9186) | 2026-10-31 10:44:00 | 4.68h | 14400s | `SITE_OUTAGE_ERA` | 1764220514612 |
| Gold Medal(4119) | 2026-11-01 10:24:18 | 3.72h | 900s | `SITE_OUTAGE` | 1764220675032 |
| Gold Medal(4119) | 2026-11-02 01:17:00 | 3.59h | 900s | `SITE_OUTAGE` | 1764220788306 |
| Jacob Logan Town(3466) | 2026-10-28 21:09:37 | 2.03h | 900s | `SITE_OUTAGE` | 1764220066008 |
| Gold Medal(4119) | 2026-11-01 22:03:55 | 1.01h | 900s | `SITE_OUTAGE` | 1764220748643 |
| Bahn(3106) | 2026-10-30 21:47:44 | 0.29h | 900s | `SITE_OUTAGE` | 1764220400131 |
| Boundary(4538) | 2026-11-01 20:57:09 | 0.27h | 900s | `SITE_OUTAGE` | 1764220730193 |
| Tubmanburg Town(4274) | 2026-11-01 15:03:35 | 0.27h | 900s | `SITE_OUTAGE` | 1764220692383 |
| Jacob Town(5025) | 2026-11-01 11:09:21 | 0.26h | 900s | `SITE_OUTAGE` | 1764220672624 |
| Duala Market 2(4344) | 2026-10-28 01:57:58 | 0.26h | 900s | `SITE_OUTAGE` | 1764219914170 |
| Randall Street(4080) | 2026-10-28 01:50:13 | 0.25h | 900s | `SITE_OUTAGE` | 1764219913187 |

`199083022` rf=0（4 条）：

| 站点 | 升起（+08） | 持续 | `Assign Delay` | 命中规则 | AID |
| --- | --- | --- | --- | --- | --- |
| Nwrokia(3467) | 2026-10-29 04:37:50 | 4.23h | 900s | `CELL_OUTAGE_REGULAR_NORMAL` | 1764220133429 |
| Nwrokia(3467) | 2026-10-29 04:37:50 | 4.22h | 900s | `CELL_OUTAGE_REGULAR_NORMAL` | 1764220133431 |
| Libassa(5546) | 2026-10-31 23:43:15 | 0.52h | 900s | `CELL_OUTAGE_REGULAR_NORMAL` | 1764220587600 |
| Libassa(5546) | 2026-10-31 23:43:15 | 0.52h | 900s | `CELL_OUTAGE_REGULAR_NORMAL` | 1764220587601 |

`199083022` 链级 B（27 条子告警）集中在两个站点：72nd Road(4507) 18 条（命中 `CELL_OUTAGE_REGULAR_NORMAL`，持续 1.96–7.70h）、Duala Market 2(4344) 9 条（命中 `SITE_OUTAGE`）。
**是否值得单独建单**：上表前列（≥0.5h）均值得；`99933` 0.25–0.29h 的 4 条刚过 900s 边界，建议先观察、不因它们单独改规则；`9995` 两条、`199083022` 的 Nwrokia 两条与链级 72nd Road / Duala Market 2 都值得补单。

**D 桶明细（`assign_delay` 为空且无 TT，从未命中任何规则）**

- `9995` **36 条**：`Assign RuleName` 与 `Assign Delay` 全空；站点 Mamba Point 10、Greenville 3、FDA 3、Kanweakan 2、Harbel 2、Whein Town 2，其余 13 站各 1；持续最长 Nwrokia 5.05h、Harbel 1.34h、Greenville 1.10h。
- `99933` **0 条**。
- `199083022` rf=0 **507 条**：`Assign RuleName` 空 **507/507**；站点 Ducor 176、`--` 132（Site ID 为 RNC103 114 / RNC105 18，对象锚在 RNC 而非站点）、Tubman High School 33、Samukai Town 27、Yargaryah 21、Samukai Town 2 20、Nykles Town 16、Lofa Bridge 13、Sugar Hill Community 10、Ndablama 9 等；持续 <1min 407、1–10min 88、10min–1h 3、>1h 9。
- `199083022` rf=2 链级 D **12 条**：全部指向同一条 `9995` D 桶根告警（Omega Community，AID `1764220987159`），与上面的 `9995` D 桶是同一事件。

**结论**

1. **`9995`**：B=2 是真缺口，值得建单；D=36 是规则覆盖缺口（从未命中规则），其中 Mamba Point 10 条集中出现，需按该站 `siteSubType` / `assetType` / `reasonType` 与规则条件逐项核对（具体是哪一项不满足**未证实**）。
2. **`99933`**：B=12 是真缺口（>0.5h 的 6 条明确值得建单），规则覆盖完整（D=0），缺口在「命中后超延迟仍未建 TT」的执行侧。
3. **`199083022`**：rf=0 B=4（Nwrokia 2 ×4.2h、Libassa 2 ×0.52h）值得建单；D=507 中 407 条 <1min 属闪断、不建议建单，9 条 >1h 与 132 条 RNC 锚定告警是对象模型/规则覆盖的真问题。rf=2 子告警无 TT 属结构预期；链级仅 27 B / 12 D，且集中在 72nd Road / Duala Market 2 与一条 Omega Community 9995 根告警。
4. **基线（本次 7×24h 窗口）**：`9995` A/B/C/D=84/2/28/36；`99933`=321/12/241/0；`199083022` rf=0=457/4/2/507；`199083022` rf=2 链级=1,841/27/465/12（另 4,573 未解析）。后续按周复算时，只有 B 桶计真缺口，D 桶单列为规则覆盖缺口，A 桶不得计入漏单。

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
| `99933` | 574（2026-11-04 重查） | 574 | 574 / 574 | A=321 / B=12 / C=241 / D=0（见 1.4） |
| `9995` | 197（2026-11-04 重查） | 150 | 150 / 150 | A=84 / B=2 / C=28 / D=36；另 rf=3 47 条单列（见 1.4） |
| `199083022` | 7,888（2026-11-04 重查） | rf=0 970 / rf=2 6,918 | rf=0 463 / 970；rf=2 6,906 / 6,918 | rf=0 A=457 / B=4 / C=2 / D=507；rf=2 链级 A=1,841 / B=27 / C=465 / D=12 / 未解析 4,573（见 1.4） |

**2026-11-03 修订（原结论已推翻）**：原报告把 `9990`「规则名 100% 命中但只有 2 条 TT」称为「建单率塌陷／最尖锐的发现」，这是**口径错误**——`Assign Delay`（9990 实测为 `900s` 103 条、`14400s` 35 条）决定告警在窗口内清除时**本就不建单**。按 delay 分桶后：**A=136、B=0、C=2**，9990 **没有建单缺口**；TT 创建链路并未出现独立断点。
`9995` / `99933` / `199083022` 已于 **2026-11-04** 按同一口径完成分桶（见 1.4），不再列为「待复核」：`9995` B=2、`99933` B=12、`199083022` rf=0 B=4 与 rf=2 链级 B=27 是本次新确认的真缺口；D 桶（`9995` 36、`199083022` rf=0 507）单列为规则覆盖缺口。`docs/eflow-dispatch-rule-gap-checklist.md` Q1/Q2 记录的是「规则名覆盖变化」这一独立事实，与本节的延迟口径不冲突。`199083023` 的特殊性在于 `assign_rulename=null` 且 `assign_delay=null`——**它从未进入任何规则的延迟窗口**，所以延迟解释不适用。

---

## 四、同类会被遗漏的告警清单（按影响排序）

| # | 类别 | 触发条件 | 影响范围 | 验证方式 |
| --- | --- | --- | --- | --- |
| **P0-1** | **「仅压缩输入」站断码**（5 个：`199083023`、`198094422`、`2114322696`、`198200011`、`199087337`） | 压缩规则未触发（缺小区告警 / 关联码 / 对象不在站点） | 所有 3G / 4G / 2G 站断，且**永不建 TT**（不在任何派单规则） | 用码集查 `eflow_tt.alarm_code` 命中数（全 0）；查 `assign_rulename` 空率 |
| **P0-2** | **`IubLink ≠ SiteID` 的对象锚定告警** | 传输 / 链路故障导致对象挂在 IubLink 而非站点 | `199083023` rf=0 率 21.7% vs 10.2%，约 **2.1 倍** | 按 `object_name` / `positionname` 拆 `IubLink==SiteID` 与 `!=` 两组比 rf=0 率 |
| **P0-3** | **`supportrelation=true` + `cellBlock=true` 的规则组合** | 小区告警被阻塞后，规则需要的 `cellAlarmList` 输入不可见 | 3G / 4G / 2G 三条 OUTAGE 规则全部（`Alarm_Rules` 第 9/10/11 行都是 `cellBlock=true`） | 取 rf=0 样本，±120s 同站查 `cellAlarmList` 码，为 0 即命中此模式 |
| **P1-1** | **`9995` / `99933` / `199083022` 已按 delay 分桶（2026-11-04 完成）** | 只统计「有/无 TT」会把延迟内恢复误计为缺口 | `9995` A/B/C/D=84/2/28/36；`99933`=321/12/241/0；`199083022` rf=0=457/4/2/507 | 已按 1.3 口径重算；B 桶计缺口、D 桶单列规则覆盖缺口，A 桶不计 |
| **P1-1a** | **B 桶真缺口（45 条子行，集中在少数根告警）** | 命中规则后超过 `Assign Delay` 仍未建 TT | `9995` 2 条、`99933` 12 条、`199083022` rf=0 4 条 + 链级 27 条（72nd Road 18 / Duala Market 2 9） | 按 1.4 的 B 桶明细逐条核查建单执行日志（见变更清单 C-10） |
| **P1-1b** | **D 桶规则覆盖缺口（从未命中任何规则）** | `assign_delay` 与 `Assign RuleName` 均为空，与延迟无关 | `9995` 36 条（Mamba Point 10 集中）、`199083022` rf=0 507 条（含 132 条 RNC 锚定、407 条 <1min）、rf=2 链级 12 条 | 按 1.4 的 D 桶站点分布核对规则条件/对象模型 |
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
3. ~~**`9990` 命中规则名但 133/135 不建单** —— 派单执行链路缺口~~：**2026-11-03 修订已推翻**。按 `Assign Delay` 分桶 A=136 / B=0 / C=2，属预期行为（延迟窗口内恢复），**不是缺陷**；`9995` / `99933` / `199083022` 已于 **2026-11-04** 分桶：`9995` B=2、`99933` B=12、`199083022` rf=0 B=4 + 链级 B=27 才是真缺口，其余为 A/C 桶（见 1.4）。
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
- 该规则当前 `siteAlarmCode=9970,9980,9990,9910,9920`（`Alarm_Rules` 第 14 行），root=`9995`、`timeWindow1=180s`、`relationTimeWindow=360s`。加入 199083023 后，NCP / link 类 NodeB 退服会派生 `9995`，而 `9995` 已有 SITE_OUTAGE 派单规则（2026-11-04 分桶后 B=2，见 1.4 / P1-1）。
- 验收：复跑 Nwrokia 场景，`9995` 的 `parentinfo` 应指向该站 `199083023`。

### P1（本月）

**P1-1 复核 `9995` / `99933` / `199083022` 的「无 TT」是否真缺口 —— 2026-11-04 已完成**
- 用 1.3 同一口径重算（7×24h 窗口、`size=2000`、按 `id` 去重、rf 分列）：`9995` rf=1 **A=84 / B=2 / C=28 / D=36**；`99933` **A=321 / B=12 / C=241 / D=0**；`199083022` rf=0 **A=457 / B=4 / C=2 / D=507**，rf=2 链级 **A=1,841 / B=27 / C=465 / D=12**（另 4,573 未解析）。明细见 1.4。
- 结论：只有 **B 桶（超过延迟仍无 TT）** 计缺口；A 桶一律标记为「预期不建单」，**不得计入漏单率**；D 桶单列为「从未命中规则」的覆盖缺口。`relationflag=2/3` 的子告警无 TT 属结构预期，不重复计缺口。

**P1-1b 处理 B 桶真缺口与 D 桶覆盖缺口（2026-11-04 新增）**
- B 桶：`9995` 2 条（Zowienta、Flumpa）、`99933` 12 条（Gold Medal 3、Lofa Bridge、Does Village、Jacob Logan Town 等）、`199083022` rf=0 4 条（Nwrokia 2、Libassa 2）+ 链级 27 条（72nd Road 18、Duala Market 2 9）。先在 eFlow 侧核对「超延迟后为何未建 TT」的执行日志，再决定补规则还是补兜底（见变更清单 C-10）。
- D 桶：`9995` 36 条（Mamba Point 10 集中）、`199083022` rf=0 507 条（其中 132 条对象锚在 RNC、407 条 <1min）。前者按站点属性核对规则条件；后者先区分闪断与持续告警，RNC 锚定的对象模型问题单独立项。
- 验收：同一查询下周复算，B 桶应下降且不得把 A 桶计入；D 桶的 132 条 RNC 锚定告警在对象回填后应可命中规则。

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
8. **延迟窗口的起算点未证实**：接口同时提供 `alarmraisedtime`、`First Match Time`、`Latest Match Time`，但 `ALARM_COLUMNS` 只映射 `Latest Match Time` / `First Match Time` / `Assign Delay`（`backend/services/eflow_alarm_service.py:151-159`），未见 `Assign Start Time` 的列映射；代码侧只解析 `assign_delay` 的数值（`backend/routers/alarm_dashboard.py:74-76`），未见「从哪个时刻起算」的实现。本文统一按**告警升起时刻**起算，这是保守口径（若实际从规则命中时刻起算，A 桶只会更多、B 桶不会增加）。
9. **分桶已覆盖四个码，但口径仍为单窗口**：`9990` 为 2026-11-03 数据；`9995` / `99933` / `199083022` 为 2026-11-04 重查的 7×24h 窗口数据（见 1.4）。`99933` 最后 24h 为 0 条，与 `mpf-outage` 停用时点接近，但**因果未证实**，因此本次 `99933` 的 574 行低于 11-03 基线的 646 行不能归因于单一规则变更。
10. **`relationflag=2/3` 的父单归属已做链级验证，但未全量配对**：`9995` rf=3 47 条全部有 `parentinfo`，其中 31 条父告警有 TT；`199083022` rf=2 6,918 条全部有 `parentinfo`，可解析的 2,345 条父链终端为 A=1,841 / B=27 / C=465 / D=12，**另有 4,573 条父告警不在本次 9990/9991/9995/99933 数据集内**（可能属于未抓取的告警码或早于窗口），其父单归属**未证实**。
11. **`clearstate` 字段不可用**：本批 `9995` / `99933` / `199083022` 的历史响应中 `clearstate` 恒为 `0`、`clearstatename` 恒空，不能用于判定 active / cleared；本次分桶一律以 `alarmclearedtime` 为准（缺失或 ≤0 时按查询时刻计持续时长，仍为保守口径）。
12. **维护态告警被排除**：查询沿用 `HIS_ALARM_CONDITION`，其中 `extensionconds.maintainstatus=["0"]`（`backend/services/eflow_alarm_service.py:114`），维护窗口内的告警不在本结论范围内；若维护态里存在超延迟无单，需单独放开口径复核。
13. **`9995` 的 `relationflag=3` 不是根告警**：它是 Secondary Root，TT 归父告警。若按 rf=1 口径把它的 26 条「超 900s 无 TT」直接计 B，会与 `99933` 的 6 条父 B 桶重复计数；本文已按父链去重。

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
| 建单率（**须按 delay 分桶**） | 取 rf=1 行 → `Assign Delay`（`900s` / `14400s`）+ `alarmclearedtime` → 分 A（`≤delay`）/ B（`>delay` 且无 TT）/ C（有 TT）/ D（delay 缺失）；只有 B 桶计缺口。**`clearstate` 不可用**（本批响应恒为 0），不再纳入判据 |
| 四桶外推（2026-11-04） | 同一条件分别取 `alarmcode=9995 / 99933 / 199083022`（`restype=zte.ran.nodeb`）；7 个 24h 窗口 2026-10-27T17:46Z~11-03T17:46Z，`size=2000`、`from` 翻页、按 `id` 去重；rf 分列 |
| 199083022 父链归属 | 抓 `9990` / `9991` 同窗口（`restype=zte.ran.nodeb`），按 rf=2 行 `parentinfo` 的倒数第二段取父 AID，逐层追到无 `parentinfo` 的终端；终端桶决定子告警归属；未命中数据集记为「未解析」 |
| 9995 rf=3 父单归属 | 取 rf=3 行 `parentinfo` 的父 AID（`99933`）→ 父 `tt_id` / `Assign Delay` / `alarmclearedtime` 判桶；47 条全部命中，31 条父有 TT，6 条父为 B（与 `99933` B 桶同一条根告警） |
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

*本报告只读产出，未修改数据库、未改生产数据、未在数仓侧做任何写操作，也未重启任何生产进程。审计期间使用的一次性只读脚本（`_tmp_eflow_*.py`、`_tmp_site_*.py` 等）与产物（`TMP/_eflow_*.txt`）已清理；2026-11-04 的四桶外推同样只用 FM 只读端点与本地 `get_raw_connection()`，临时脚本 `TMP/_tmp_eflow_bucket_*.py` / `_tmp_eflow_*_20261104.json` 已清理。*
