# eFlow 告警规则变更清单（2026-11-03）

> 面向：eFlow / UFM 规则管理员（config-center 操作方）
> 来源：本清单由 [eflow-alarm-audit-2026-11-03.md](eflow-alarm-audit-2026-11-03.md) 的审计结论转化而来，逐条给出可执行改动与验收口径。
> 与既有文档的关系：[eflow-dispatch-rule-gap-checklist.md](eflow-dispatch-rule-gap-checklist.md) 记录的是 **2026-11-03 06:17 Nwrokia(3467) 9995 事故的人工核对问题（Q1–Q12）**，本清单**不重写它的内容**；凡涉及 9995 规则族覆盖空洞、`SITE_OUTAGE-imported` 接管、4 小时延迟族等，请直接查阅该文档对应编号。
> 数据口径：本地规则镜像 `backend/services/eflow_rules/eflow_alarm_rules.xlsx`（压缩规则）与 `eflow_push_rules.xlsx`（`ttPushOrderRule`，143 条），均采集于 2026-11-02；**镜像不等于 config-center 实时配置**，改动前请以配置中心原文核对。
> **2026-11-03 修订：按 Assign Delay 口径校正 9990 建单率结论。** C-4 由「建单率塌陷诊断」改写为「按延迟窗口分桶后的真缺口清单」；9990 分桶结果 **A=136 / B=0 / C=2**，**无真缺口**，A 桶为预期行为、不得计为漏单。
> 敏感值约定：本清单只写规则名、规则 ID、告警码、字段名与阈值，不含任何凭据、Token、账号或内网地址。

---

## 0. 变更总表（先看这张）

| 编号 | 优先级 | 目标层 | 一句话 | 执行方 |
| --- | --- | --- | --- | --- |
| C-1 | **P0** | 自动派单规则(103) | 给 5 个「仅压缩输入」站断码补派单兜底 | eFlow 管理员 |
| C-2 | **P0** | 压缩规则 `mwlink-outage-new` | 把 `199083023` 并入 `siteAlarmCode`，无小区告警也能派生 9995 | eFlow 管理员 |
| C-3 | **P0** | 压缩规则 `zte-3g-sitedown` | 关联码清单过窄 + `cellBlock=true` 组合导致单告警形态永不压缩 | eFlow 管理员 |
| C-4 | **P1** | 自动派单规则(103) 的延迟口径 | 按 `Assign Delay` 分桶后列真缺口（9990 已为 B=0） | eFlow 管理员 + 我方 |
| C-5 | **P1** | `ttPushOrderRule` 规则 200/201 | REGULAR `99933` 补 FOAccept 路由 | eFlow 管理员 |
| C-6 | **P1（需决策）** | 压缩规则 `mpf-outage` | 是否恢复被停用的电源断站衍生 | eFlow 管理员 + 业务 |
| C-7 | P2 | 我方本地同步 | `history_alarm` 只留 TT 行造成观测盲区 | 我方（不改 eFlow 规则） |
| C-8 | P2 | 我方代码 | `eflow_ume_link.py:202` 的 `or 1` 缺陷 | 我方（**代码侧，不改规则**） |
| C-9 | P2 | 我方本地同步 | 采集白名单不含 199083023，本地完全不可见 | 我方（不改 eFlow 规则） |

> 前置要求（所有 C-1 ~ C-6）：改动前在配置中心**导出当前规则快照**（含规则名、ID、状态、条件原文、优先级、延迟），并记录改动时间与操作人；每改一条立即验证，不要批量改完再验。

---

## C-1　给 5 个「仅压缩输入」站断码补派单兜底

| 项 | 内容 |
| --- | --- |
| **优先级** | P0（本周内） |
| **规则 ID / 规则包** | 自动派单规则(103)，规则包 `SITE_OUTAGE` / `SITE_OUTAGE-imported`（具体规则名以配置中心为准；本地镜像**不含**该层，无法给出 ID） |
| **现状** | 下列 5 个码在本地镜像的 143 行 `Push_Rules` 中**一次都没出现**，同时也没有任何自动派单规则实际为它们建过单：<br>· `199083023`（3G NodeB out of service）<br>· `198094422`、`2114322696`、`198200011`（4G 站断）<br>· `199087337`（2G 站断）<br>这 5 个码在压缩规则里**只是输入**（派生 9990 / 9970 / 9980），压缩不成立时即彻底孤儿。实证：`199083023` 最新 2000 条历史行 `Assign RuleName=null` **2000/2000**、`TT ID=empty` **2000/2000**；`eflow_tt` 全表 40,614 条中该码 **0 条**。 |
| **改成什么** | 在站点级自动派单规则的 `alarmCode` 条件里加入上述 5 个码：`alarmCode in {199083023, 198094422, 2114322696, 198200011, 199087337}`。条件维度建议与现有站点级规则一致（`siteSubType` / `assetType` / `reasonType` 保持与同族规则相同），**不要**新增 `RAT` 之外的额外限制，否则仍会漏。 |
| **变更后预期** | 压缩失败（`relationflag=0`）时，原始站断码也能直接建 TT；`199083023` 周建单数从 0 变为 >0；Nwrokia 这类「Iub/NCP 引发的 NodeB 退服」不再只能靠人工补单。 |
| **验收查询 / 验收标准** | ① 变更后 24h：`eflow_tt WHERE alarm_code IN (5 码) AND created_time >= <变更时间>` 计数 >0；<br>② 抽 10 条新单核对 `site_id` 与告警站点一致、`alarm_occur_time` 与 `alarmraisedtime` 差值 ≤ 规则延迟 + 5 分钟；<br>③ 反向检查：同一事故若 `9990` 也已建单，确认没有出现**双单**（见风险）。 |
| **风险与回滚** | 风险：压缩成功时 `9990` 与原始码同时建单 → 重复工单。缓解：在规则里加「同站 + 同制式 + 10 分钟内去重」，或明确 `9990` 优先、原始码仅在 `relationflag=0` 时触发（若派单规则支持 `relationflag` 条件）。<br>回滚：用改动前导出的规则快照恢复该条规则（状态 + 条件 + 优先级 + 延迟），无需数据回滚；已建出的重复单由工单侧合并/关单处理。 |

---

## C-2　把 `199083023` 并入 `mwlink-outage-new` 的 `siteAlarmCode`

| 项 | 内容 |
| --- | --- |
| **优先级** | P0（本周内） |
| **规则 ID / 规则包** | `mwlink-outage-new`，规则包 `OUTAGE`；镜像位置 `Alarm_Rules` 第 14 行（该行 ID 未被完整导出，按 `rule_name` 定位） |
| **现状** | 该规则当前 `siteAlarmCode=9970,9980,9990,9910,9920`、root=`9995`、`timeWindow1=180s`、`relationTimeWindow=360s`、`delay=30s`、ENABLED。**不含 `199083023`**。本样本（NCP link failure / Iub 链路故障导致的 NodeB 退服）因此既拿不到 9990（见 C-3），也派生不出 9995；同站 9995 那条（AID 1764221015309）是**独立升起**的，不是由本样本派生。 |
| **改成什么** | `siteAlarmCode` 追加 `199083023`，保持其余参数不变：建议最终为 `9970,9980,9990,9910,9920,199083023`；若配置中心对单条规则的码数有上限，则单独复制一条同参数规则专管 `199083023`（新规则名建议 `mwlink-outage-new-3g`，避免改动既有规则影响面）。 |
| **变更后预期** | 传输 / 链路类 3G 站断会派生 `9995` 根告警，`9995` 已有 SITE_OUTAGE 派单规则族接单；缓解 `199083023` 的「无父告警」问题。 |
| **验收查询 / 验收标准** | ① 取变更后新发生的 `199083023`，检查其 `relationflag`：应变为 `1`（Root）或作为 `parentinfo` 的 root 出现；<br>② 该站应出现一条 `alarmcode=9995`、`parentinfo` 指向该 `199083023` 的记录，时间差 ≤ `delayCreateTimeWindow`(30s) + 一个采集周期；<br>③ 该 `9995` 的 `Assign RuleName` 非空。 |
| **风险与回滚** | 风险：`mwlink-outage-new` 影响面广（5 个既有码），误改会波及所有微波链路中断的根告警派生；可能造成 9995 数量上涨、派单量上涨。<br>回滚：优先采用「新增独立规则」方案，回滚=停用该新规则；若直接改原规则，用快照恢复 `siteAlarmCode`。<br>建议先低峰单站试跑（选 1 个 NCP 类故障站点，观察 24h）。 |

---

## C-3　修 `zte-3g-sitedown` 的关联码过窄与 `cellBlock=true` 组合

| 项 | 内容 |
| --- | --- |
| **优先级** | P0（与 C-1 同批，C-1 是兜底、C-3 是治本） |
| **规则 ID / 规则包** | `zte-3g-sitedown`，规则 ID `rule_1788853932033`，规则包 `OUTAGE`，镜像 `Alarm_Rules` 第 10 行，ENABLED |
| **现状** | 参数原文：`rootResType=zte.ran.nodeb`、`rootAlarmCode=9990`、`siteAlarmNeType=zte.ran.nodeb`、`siteAlarmCode=199083023`、`cellAlarmNeType=zte.ran.nodeb`、`cellAlarmList=199083022`、`supportCoreAlarm=true`、`siteCoreAlarmCode=2365981958`、`supportrelation=true`、`relationAlarmCode=2365980930,198097062,9971,9981,9991`、`cellBlock=true`、`delayCreateTimeWindow=10s`、`delayClearTimeWindow=120s`。<br>问题：规则要求「站点退服 + 小区退服」或「站点退服 + 关联码」至少一路；但 `cellBlock=true` 会抑制小区告警，Iub/传输类退服（`cell_name="empty"`）根本产不出 `199083022`。实测：`199083023` 最新 2000 条中 `relationflag=0`（未压缩）**330 条（16.5%）**；`IubLink ≠ SiteID` 时未压缩率 **21.7%**，是 `IubLink == SiteID`（10.2%）的约 2.1 倍。 |
| **改成什么** | 三选一（按风险从低到高）：<br>**方案 A（推荐）**：`relationAlarmCode` 追加传输类常见码 `2365980930,198097062,9971,9981,9991` 之外的**实测高频未压缩码**——先按 P3 巡检取 rf=0 的 `alarmcode` top-N，再决定追加清单；不要凭猜加码。<br>**方案 B**：新增同参数规则专管「站点级单告警」形态：`siteAlarmCode=199083023`、不配 `cellAlarmList`、`supportrelation=false`、`cellBlock=false`、root=`9990`；缺点是可能与 A 规则双派生。<br>**方案 C**：维持现状，接受 16.5% 不压缩，由 C-1 的派单兜底保证「不压缩也能建单」。 |
| **变更后预期** | 单告警形态（无小区、无关联码）也能派生 9990；`199083023` 的未压缩率从 16.5% 显著下降；Nwrokia 场景应出现 9990 根告警。 |
| **验收查询 / 验收标准** | ① 变更后 7 天，`199083023` 的 rf=0 占比从 16.5% 降至目标值（建议 <8%）；<br>② 变更后新发生的 rf=0 样本中，`IubLink ≠ SiteID` 组占比明显下降；<br>③ 抽查 5 个新派生的 9990，`parentinfo` 能正确指回原始 `199083023`（`alarmkey` / `id` 对应）。 |
| **风险与回滚** | 风险：`cellBlock` 与「单告警派生」并存会出现**父告警数量上涨**，可能触发下游 99933 / 派单量上涨；也可能是业务不想要的（抑制刷屏的本意被削弱）。<br>回滚：用快照恢复 `relationAlarmCode` 与 `supportrelation`；若采用方案 B，直接停用新规则。<br>决策点：方案 C 是否需要业务书面确认「接受 16.5% 不压缩」。 |

---

## C-4　按 delay 口径分桶后的真缺口清单（9990 已无缺口）

> **2026-11-03 修订**：本条原为「查清 9990 命中规则名却 133/135 不建单」，结论「建单率塌陷」已被推翻。以下为校正后版本。

| 项 | 内容 |
| --- | --- |
| **优先级** | P1（本月内） |
| **规则 ID / 规则包** | 自动派单规则(103)（规则包 `SITE_OUTAGE` / `SITE_OUTAGE-imported` / `SITEOUTAGE_REGULAR_COOL`）；本条只读取告警行的 `Assign Delay`，**不改规则** |
| **现状** | `Assign Delay`（告警行自带列，`backend/services/eflow_alarm_service.py:158`；解析 `backend/routers/alarm_dashboard.py:74-76`）是**自动派单规则(103) 命中后到建 TT 之间的延迟窗口**，告警在窗口内清除则不建单。9990 实测取值：`900s` 103 条、`14400s` 35 条。按 7 天 138 条 `relationflag=1` 分桶：<br>· **A｜延迟内恢复 136 条（98.6%）→ 预期不建单，不算缺口**<br>· **B｜超延迟仍无单 0 条（0.0%）→ 真缺口**<br>· **C｜有单 2 条（1.4%）**：`1764220905133`（Duala Market 2，19min，`SITE_OUTAGE-imported`，TT202611020056）、`1764220394832`（Mamba Point，15min53s，`SITE_OUTAGE`，TT202610300051）<br>· D｜delay 缺失 0 条<br>结论：**9990 没有建单缺口**；原「133/135 无单」是延迟窗口内自行恢复。`9995`（160/195 无 TT）、`99933`（376/646 无 TT）**尚未按此口径分桶，不得计为缺口**。 |
| **改成什么** | **本条不改任何 eFlow 规则**（已证 9990 无缺口，改规则只会制造重复单）。要做的是把口径固化并外推：<br>① 把 A/B/C/D 分桶固化到审计脚本与看板：`tt_id` 非空→C；否则 `alarmclearedtime - alarmraisedtime ≤ Assign Delay`→A；`>`→B；`assign_delay` 为空→D；<br>② 用同一口径复算 `9995` / `99933` / `199083022`，输出四桶条数与占比；<br>③ 仅当 B 桶 >0 时，才按「站点 / 命中规则名 / 持续时长」拆解并进入规则改动流程。 |
| **变更后预期** | 得到一份**只含真缺口**的清单：9990 的 B 桶保持 0；`9995` / `99933` 若 B 桶 >0，其条数即真实漏单量，替代此前「无 TT 数」的误判口径。A 桶在任何报表中显示为「延迟内恢复（预期）」，不进入漏单统计。 |
| **验收查询 / 验收标准** | ① 交付 9990 / 9995 / 99933 三张四桶表（A/B/C/D 条数 + 占比）；<br>② **B 桶（超延迟未建单）条数目标：9990 = 0（已达成），9995 / 99933 首次复算后给出基线并逐步下降**；<br>③ A 桶必须显式标注「`Assign Delay` 内恢复，预期行为，不得计为漏单」；<br>④ 若 B 桶 >0，附 Top 10 明细（站点 / 告警时刻 / 持续时长 / 命中规则名 / `assigned_status`）。 |
| **风险与回滚** | 本条**无规则改动 → 无需回滚**。真正的风险是**误把 A 桶当缺口去改规则**：那会为「几秒到几分钟就恢复」的闪断告警建单，造成工单洪水与重复单。若后续确实需要调整延迟，请单独走 C 类变更（附延迟调整前后的 B 桶对比），并以 `docs/eflow-dispatch-rule-gap-checklist.md` Q9 的 4 小时延迟族为参照。 |

---

## C-5　REGULAR `99933` 补 FOAccept 路由

| 项 | 内容 |
| --- | --- |
| **优先级** | P1（本月内） |
| **规则 ID / 规则包** | `ttPushOrderRule` 规则 **200**（`Regular电源故障推送TT到IPT`）、**201**（`Regular断站故障手动到FO`）；规则包 `ttPushOrderRule`，镜像 `Push_Rules` 第 2 / 3 行（第 58 行规则 203 为 ERA 专用） |
| **现状** | 规则 200 的 `alarmCode in {9920,9910,9995,9970,9980,9990}` + `siteSubType=REGULAR` + `assetType in {NORMAL,COOL}` + `reasonType in POWER`；规则 201 的 `alarmCode in {9970,9980,9990,9910,9920,9995}` + `reasonType not in POWER`；规则 203（`ERA断站推单到ZTE WO`）才含 `99933`。→ **REGULAR 站点的 99933 在 FOAccept 层没有任何规则受理**，即使前面建了 TT 也推不出去。 |
| **改成什么** | 在规则 200 与 201 的 `alarmCode` 条件中追加 `99933`（两条件分支各一份，保持 `reasonType` 的 POWER / 非 POWER 分流不变）。若担心影响既有 99933 分流，可新增一条同条件规则专管 `99933` 并置于更低优先级（数值更小者优先，见 `eflow_push_rule_eval.py:115-119`）。 |
| **变更后预期** | 非 ERA 站点的电源断站 99933 能进入 FO / 3rd_Power 分流，不再止步于「有 TT 无 WO」。 |
| **验收查询 / 验收标准** | ① 取变更后新发生的 `99933` TT 10 条，检查 `fo_accept_detail` 非空、`current_handler` 有值；<br>② `eflow_push_rules_checker` 复跑：`99933` 的 `unmatched` 从当前水平降到 0（原为最新 1000 条样本中 `unmatched=592`）；<br>③ 不能把原本走 203 的 ERA 99933 抢过来 → 核对 ERA 站样本仍命中 203。 |
| **风险与回滚** | 风险：99933 是高频码（7 天 646 条、`eflow_tt` 内 9,046 条），放量会让 FO / 电源组接单量上升；优先级设置不当会与 203 冲突。<br>回滚：用快照恢复 `alarmCode` 条件；新规则方案则停用即可。 |

---

## C-6　`mpf-outage` 是否恢复（需业务决策）

| 项 | 内容 |
| --- | --- |
| **优先级** | P1（本月底前给出结论） |
| **规则 ID / 规则包** | `mpf-outage`，规则 ID `rule_1774597491326`，规则包 `OUTAGE`，镜像 `Alarm_Rules` 第 12 行，**DISABLED** |
| **现状** | 规则语义：「某物理站出现断站告警（2G/3G/4G 任一），时间窗内存在任一电源相关告警，则衍生电源断站告警」。参数：`siteAlarmCode=9910,9920,9980,9990,9970` → root `99933`、`timeWindow1=259200s`（3 天）、`delay=30s`、DISABLED。当前处于停用，本站 7 天内无 `99933`（与之一致）。 |
| **改成什么** | 二选一，需业务书面确认：<br>**恢复**：ENABLED，但先把 `timeWindow1` 从 259200s 收到与业务可接受的范围（建议 3600–14400s），避免「3 天内任意电源告警都把断站归到电源」造成误派生；<br>**维持停用**：在 `docs/eflow-dispatch-rule-gap-checklist.md` 的规则变更记录里补一条「mpf-outage 停用为预期设计，99933 仅由其它链路产生」。 |
| **变更后预期** | 恢复：电源类断站会重新派生 99933，弥补 REGULAR 电源断站缺口；维持停用：减少误派生，但电源类断站只能靠 9990/9995 等父告警承担。 |
| **验收查询 / 验收标准** | 若恢复：① 变更后 7 天，`99933` 的派生来源分布中「由 mpf-outage 产生」占合理比例（按站抽样核对 `parentinfo`）；② 误派生率抽查：随机 10 条新 99933，确认站内 3 小时窗口内确有电源告警；③ `99933` 总量增幅 ≤ 20%。 |
| **风险与回滚** | 风险：`timeWindow1=259200s` 原值过大，直接恢复易造成大量误派生与派单洪水；恢复前必须先收窄时间窗。另需确认 99933 的派单与 FOAccept 路由已就绪（见 C-5），否则「压缩出来也没单」。<br>回滚：改回 DISABLED（一条状态位，风险低）。 |

---

## C-7　本地 `history_alarm` 的 TT-only 观测盲区（我方，不需要 eFlow 改规则）

| 项 | 内容 |
| --- | --- |
| **优先级** | P2（本季） |
| **规则 ID / 规则包** | **不涉及 eFlow 规则**；我方同步代码 `backend/services/eflow_alarm_service.py:265-278`（`_filter_rows_with_tt_id`）与 `:791` 调用点 |
| **现状** | 本地 `history_alarm` **只保留 `tt_id` 非空的行**。后果：所有「应建单而未建单」的告警在本地历史里**根本不存在**，无法用 SQL 审计漏单——本样本（AID 1764221015205）与同站 9995 都属于此类，只能靠 FM 只读接口手查。 |
| **改成什么** | 两种做法（建议 A）：<br>**A**：新增一张旁路表（如 `history_alarm_audit`），对白名单内所有告警落库、不做 TT 过滤，仅用于审计与看板；原 `history_alarm` 口径不变，避免影响既有页面。<br>**B**：把 `_filter_rows_with_tt_id` 改为配置开关（`alarm_config.json` 增加 `history_keep_all` 布尔项），默认关闭以保持现状。 |
| **变更后预期** | 本地可以按「`tt_id IS NULL` 且 `assign_rulename IS NULL`」直接查出漏单集合，不必依赖接口逐条查；`eflow_push_rules_checker` 的样本盲区被补上（当前其样本只取「已有 TT」的 `eflow_tt`，天然看不到没建单的告警）。 |
| **验收查询 / 验收标准** | ① 变更后 24h，旁路表行数 ≈ 接口 history 行数（误差 <1%，去重后）；<br>② 用旁路表能查到 AID `1764221015205` 与 `1764221015309`；<br>③ 既有页面（依赖 `history_alarm`）的行数与变更前一致（无回归）。 |
| **风险与回滚** | 风险：数据量上升（48h 窗口 + 白名单 16 码，估算可控）；写入耗时增加。直接改原表口径会影响所有读 `history_alarm` 的页面，**不建议**。<br>回滚：停用新表 / 关闭开关，原表不受影响。 |

---

## C-8　`eflow_ume_link.py:202` 的 `or 1` 缺陷（代码侧，不需要改规则）

| 项 | 内容 |
| --- | --- |
| **优先级** | P2（本季；一条一行改动，建议随下个迭代带上） |
| **规则 ID / 规则包** | **不涉及任何 eFlow 规则**；我方代码 `backend/services/eflow_ume_link.py:202`，调用方 `backend/routers/eflow_qa.py:459` 与 `:515` |
| **现状** | 代码 `"relationflag": root_relationflag or 1` → `relationflag=0`（原始告警，合法值）被当成 falsy 静默改写为 1，导致关系链查询（`backend/services/eflow_ume_link.py:285-296`，请求 `fm-history/relatedAlarms/table`）对**所有原始告警**返回空。排查「为什么没被压缩」时会被误导成「接口没数据」。 |
| **改成什么** | 改为显式判空：`"relationflag": 1 if root_relationflag is None else int(root_relationflag)`。同时建议 `resolve_alarm_chain` 增加一个可选入参，让调用方（`eflow_qa.py:459/515`）显式传入原始行的 `relationflag`，不依赖内部 meta。 |
| **变更后预期** | `relationflag=0` 的样本能正常返回关系链；「未压缩」与「接口无数据」可区分开。 |
| **验收查询 / 验收标准** | ① 用 AID `1764221015205` 调 `resolve_alarm_chain`，返回值非空（或明确返回「无关联告警」而不是异常/空结构）；<br>② 取 3 条已知 `relationflag=2`（已压缩）样本回归，关系链结果不变；<br>③ 单测覆盖 `relationflag` 取 0 / 1 / 2 / None 四种入参。 |
| **风险与回滚** | 风险：几乎为零（只影响排查工具的取值）。若调用方依赖「永远传 1」的旧行为，需同步检查 `eflow_qa` 的两处显示逻辑。<br>回滚：还原该行。 |

---

## C-9　本地采集白名单不含 199083023（我方，不需要 eFlow 改规则）

| 项 | 内容 |
| --- | --- |
| **优先级** | P2（本季，与 C-7 同批） |
| **规则 ID / 规则包** | **不涉及 eFlow 规则**；我方 `backend/services/eflow_alarm_config.json:9-74` 的 `alarm_code_conds` |
| **现状** | 白名单 16 项，含 `99933/9920/9995/9981/9991/9990/9970/9971/9910/9980/4758` 等，**不含 `199083023` / `199083022`**。因此实时表与历史表都没有这两码，本地看板与审计完全不可见。 |
| **改成什么** | 在 `alarm_code_conds` 中追加 `199083023@zte.ran.nodeb` 与 `199083022@zte.ran.nodeb`（restype 必须是 `zte.ran.nodeb`，否则会漏）；同时把 C-1 的 5 个孤儿码一并纳入，保证「压缩层输入」全程可见。 |
| **变更后预期** | 本地可观测 3G 站断与小区退服的压缩全过程；C-7 的旁路表才有意义（否则白名单先行过滤，旁路表也看不到）。 |
| **验收查询 / 验收标准** | ① 变更后 24h，本地表能按 AID `1764221015205` 命中；<br>② 采集行数增幅在预期内（`199083023` 7 天约 7,772 行、`199083022` 约 7,889 行）；<br>③ 采集任务耗时无显著上升（对比变更前后单轮耗时）。 |
| **风险与回滚** | 风险：采集量与写库量上升（约 +1.5 万行/7 天，可控）；如遇接口限流需分页调整。<br>回滚：从白名单移除对应项。 |

---

## 附录 A　通用验收查询（只读）

> 以下查询在本地只读执行，DB 走 `backend.database.get_raw_connection()`（pg 模式用 `?` 占位符，自动转 `%s`）。时间字段注意：eFlow `alarmraisedtime` / `servertime` 是 13 位毫秒，`alarmOccurTime` 是 10 位秒。

| 用途 | 查询要点 |
| --- | --- |
| 孤儿码是否开始建单 | `SELECT alarm_code, COUNT(*) FROM eflow_tt WHERE alarm_code IN (199083023,198094422,2114322696,198200011,199087337) AND created_time >= <变更时间> GROUP BY alarm_code` |
| 压缩是否生效 | 取新 `199083023` 行，检查 `relationflag` 与 `parentinfo`；再按 `parentinfo` 找 9990 / 9995 的 `alarmkey` |
| 建单率（**不得只看有无 TT**） | 先按 `Assign Delay` 分桶，再算 `B 桶 / (A+B+C)`；直接算 `tt_id IS NULL` 占比会把「延迟内恢复」误计为漏单 |
| FOAccept 是否接住 | 查 `eflow_tt.fo_accept_detail` / `current_handler` 是否非空；用 `eflow_push_rules_checker` 复跑看 `unmatched` |
| 漏单集合（C-7 完成后） | 旁路表中 `tt_id IS NULL AND assign_rulename IS NULL AND clearstate=0` |
| 漏单分桶（C-4 核心） | 取 rf=1 行 → `Assign Delay`（`900s`/`14400s`）+ `alarmclearedtime`/`clearstate` → A（`持续时间 ≤ delay`）/ B（`> delay` 且 `tt_id` 空）/ C（有 TT）/ D（delay 缺失）；**只有 B 桶计漏单** |
| 规则覆盖差的静态核对 | 用 `eflow_push_rules.xlsx` `Push_Rules` 的 `alarmCode` 条件与「压缩规则引用的全部码」做集合差，差集即孤儿码候选 |

## 附录 B　改动记录模板（建议每次变更填一行）

| 日期 | 变更编号 | 规则名 / ID | 改前快照路径 | 改动内容 | 操作人 | 验证结果 | 回滚点 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-XX | C-1 | SITE_OUTAGE(imported) | （导出文件名） | alarmCode +5 码 | — | 验收①②③ | 快照恢复 |

---

*本清单只读产出，未修改任何 eFlow 配置、数据库或生产数据，也未重启生产进程。清单中标注「我方」的条目需要在代码/同步层实施，实施前请按项目 `AGENTS.md` 的回归清单执行。*
