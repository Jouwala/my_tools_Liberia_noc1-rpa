# eFlow 自动派单规则核查清单（2026-11-03）

> 起因：2026-11-03 06:17:52 站点 **Nwrokia（3467，Grand_Kru，Hub 站）** 上报 **9995 MW LINK DOWN（Critical）**，持续 2 小时仍未生成 TT。
> 我们从 eFlow 活动告警接口取到这条告警的派单字段是**全空**的（Assign RuleName / Assign Delay / Assigned Status / TT ID 均无值），
> 说明它**一条自动派单规则都没有命中**，不是"派单失败"，是"根本没排上派单"。
> 下面第一部分是请配置人核对的问题，第二部分是我们按同样口径扫出来的其他潜在漏派项。

## 0. 先看这条告警的定位信息（便于直接复现）

| 项 | 值 |
| --- | --- |
| 站点 / 站号 | Nwrokia / 3467（Region=Grand_Kru，Hub Site Flag=YES，Downstream Site Count=13） |
| 告警码 / 名称 | 9995 / MW LINK DOWN（Critical，Communication Alarm，来源 RCA） |
| 升起时间 | 2026-11-03 06:17:52（eFlow 服务器时间，Africa/Monrovia = UTC+0） |
| alarmkey | `zte.ran.nodeb@9995@3467@1793686715628` |
| aid / id / sequence | 1793686715628 / 1764221015309 / 71287173 |
| 父子关系 | relationflag=1，`Root`（影响站点 3467,4112,4125，共 3 个） |
| Reason Type | **POWER**（originalreasontype 仍是 TRM；relatedruletype 比同期两条已建单的 9995 多一个包 `com.zte.oes.ufm.upkg.alarm_1233789154`，即电源归因包） |
| 派单字段 | Assign RuleName / Assign Delay / Assigned Status / TT ID **全部为空** |

复现方法：当前告警界面把「派单规则名 / 派单延迟 / 派单状态 / 工单号」四列拉出来筛空值，今天全网 67 条活动告警里，除 4 条 4758 之外**只有这一条**四列全空。

---

## 一、请配置人核对的问题

### Q1　自动派单规则在 10-23 和 11-02 各动过一次？现在哪套在生效？

- 现象：规则名出现了带 `-imported` 后缀的同名副本，最早命中是 **2026-10-23 01:53**（`SITE_OUTAGE-imported`），但当时只有零星命中；到 **11-02 上午，旧名字的规则集体停止命中**：

  | 旧规则 | 命中数（镜像内） | 最后一次命中 |
  | --- | --- | --- |
  | `SITE_OUTAGE` | 4696 | 2026-11-02 08:43 |
  | `CELL_OUTAGE_REGULAR_NORMAL` | 1151 | 2026-11-02 08:13 |
  | `SITE_OUTAGE_ERA` | 1436 | 2026-11-02 03:48 |
  | `SITEOUTAGE_REGULAR_COOL` | 869 | 2026-11-01 23:12 |

  同日 09:28 起改由 `SITE_OUTAGE-imported` 接手（9910/9920/9970/9990/99933），`SITE_OUTAGE_ERA-imported` 11:33 起接手 9980。
- 请确认：① 11-02 上午是不是做了一次导入/停用（旧规则是 STOP 还是被删）；② 新旧是否并存、优先级顺序如何；③ 导入有没有改写条件 —— 因为这直接影响下面 Q2~Q4。
- 在哪看：UFM →【运维监控】→【告警管理】→【告警设置】→【规则设置】→ 自动派单规则(103)。

### Q2　`SITE_OUTAGE-imported` 的告警码条件里还有 9995 吗？

- 现象：旧 `SITE_OUTAGE` 在镜像内（2026-08-01 起）命中过 9995 共 **321 条**；站号 3467 自己历史上的 7 条 9995（10-03 及 8 月那批，告警里的站名分别写作 Nwrokia / Gee City / Sasstown (G. Kru)）**全部由它接住并建单**。而 `SITE_OUTAGE-imported` 的命中码只有 9910 / 9920 / 9970 / 9990 / 99933，**9995 命中数 = 0**（最后一条 9995 走 SITE_OUTAGE 是 11-01 17:16）。
- 请确认：9995 是被有意移出，还是导入时漏了。

### Q3　`LINK_OUTAGE_9995_REGULAR_COOL` 是否已经变成"只匹配 COOL"？

- 现象：该规则命中 130 条 9995，其中 `RAN Site Type=REGULAR` 的最后一次命中是 **2026-09-13 20:11**，之后命中的全是 COOL。名字里带 "REGULAR_COOL"，但实际只吃 COOL。
- 请确认：这条规则的站点类型条件现在写的是什么（`ran_site_type`？`site_attribute`？），REGULAR 是否被挪走了。

### Q4　`SITE_OUTAGE_9995_VICTIMS_2-4` 的 "2-4" 绑的是哪个字段？上限之外谁接？

- 现象：该规则命中 6 条 9995，全部是 `RAN Site Type=REGULAR`、Hub=YES、**下游站点数 2~4**、影响站点数 2~3。
- 关键矛盾：Nwrokia 这条 影响站点数=3（落在 2-4 内），但**下游站点数=13**。它没有命中这条规则 → 说明 "2-4" 判的是**下游站点数（downstream site count）**而不是影响站点数。
- 请确认：① 条件字段与阈值到底是哪个；② **REGULAR 型 Hub 站、下游站点数 ≥5 的 9995 现在由哪条规则负责**（目前数据看是无人接手，Nwrokia 就是这个洞）；③ 这类"下游挂站多"的根告警本应是最需要派单的，是否反而漏了。

### Q5　`LINK_OUTAGE_9995_ERA` 同样有上限吗？

- 现象：5 条命中全部 ERA、影响站点数 2~4，最后一次 10-18 12:14。
- 请确认：ERA 站 9995 影响站点数 >4 时谁接。

### Q6　Reason Type 被电源归因改写成 POWER，是否预期？是否影响派单？

- 现象：Nwrokia 这条 `originalreasontype=TRM`、`reason_type=POWER`，`relatedruletype` 比同期已建单的两条 9995 多出电源归因包 `com.zte.oes.ufm.upkg.alarm_1233789154`。历史 463 条已清除的 9995 里 462 条 reason=TRM，只有 1 条 POWER（Samukai Town 11-02 15:55，走 `SITE_OUTAGE_9995_VICTIMS_2-4` 并建了单）→ 所以 POWER 本身不是绝对阻断，但**派单/抑制规则里是否写了 reasonType 条件**请确认。
- 另请确认：微波链路中断被归因成 POWER 是否是期望逻辑（会连带影响 TT 推单规则 200/201 的去向：POWER 走 3rd_Power，非 POWER 走 FO）。

### Q7　是否存在针对 MW 根告警的抑制派单规则？

- 请确认：抑制派单规则(102) 里是否有命中 9995 / `MW Layer=1` / 大下游 Hub 站 / POWER 的条件（手册明确"符合抑制规则的告警不参与派单"，抑制规则与派单规则配合使用）。

### Q8　4758 Fiber Break 有意不做自动派单吗？

- 现象：4758 在我们镜像里全历史 **10307 条**告警，规则名与工单号**全部为空**，eFlow 侧一张单都没派过。目前由我们的 RPA 按 15 分钟阈值代派。
- 请确认：这是不是既定设计？如果 eFlow 侧准备接手，请告知目标处理组与延迟，我们好把代派关掉避免重复建单。

### Q9　`SITE_OUTAGE_ERA` / `SITEOUTAGE_REGULAR_COOL` 系列的派单延迟 14400s（4 小时）是否符合预期？

- 现象：这两族规则的 `Assign Delay=14400s`，实测「告警升起 → 建 TT」平均 **240~277 分钟**；而 `SITE_OUTAGE` / `LINK_OUTAGE_9995_*` / `CELL_OUTAGE_*` 是 900s，实测平均 15.4~25.7 分钟（9995 为 17.5 分钟，Zolowo 那条 05:27:04 升起 → 05:42:50 建单）。
- 后果：ERA 站的 9980/99933、COOL 站的 9920/99933 在**头 4 小时内没有任何工单**，SLA 却在计时。请确认这是有意设置（防闪断）还是配置漂移。

### Q10　补派单参数现在是多少？为什么没有把 Nwrokia 这条补上？

- 配置项：「最近 N 天」（将最近 N 天内符合派单规则的告警补派单，最多重试 5 次）、「间隔时间(分钟)」、"白名单"（已派单父告警恢复后对白名单内的活跃子告警重新派单，格式 `alarmcode@restype`）。
- 请确认：① 当前 N / 间隔；② 补派单只补"符合派单规则"的告警 —— 这条根本没命中规则，所以补派单也不会救它，是否符合预期；③ 白名单里是否包含 `9995@zte.ran.nodeb`。

### Q11　两条 `assigned_status=5` 的多日滞留是什么原因？

| 站点 | 告警码 | 命中规则 | 升起时间 | 已滞留 |
| --- | --- | --- | --- | --- |
| Tailing Storage Facility (4847) | 9971 4G CELL DOWN | CELL_OUTAGE_REGULAR_NORMAL（900s） | 2026-10-28 21:55 | 5 天 |
| Belimu (3747) | 9920 CSD | SITEOUTAGE_REGULAR_COOL | 2026-10-20 17:40 | 14 天 |

- 说明：在已清除的历史告警里 `assigned_status=5` 为 **0 条**，即它不是正常终态，而是"规则命中了但单子一直没落地"。
- 请确认：派单失败的错误记录在哪个日志/界面（工单系统对接侧），是否需要我们提供告警明细。

### Q12　站点主数据核对

- Nwrokia(3467) 在告警上的属性是 `RAN Site Type=REGULAR`、`Site Attribute=REGULAR`、`Site Class=NORMAL`、`Site VIP Level=NO`、Hub=YES、下游 13 站。
- 请对照 CMDB 确认这些属性是否正确 —— 如果它实际是 COOL 型站点，那就是主数据错导致没命中规则（同站历史上 9995 都是靠 `SITE_OUTAGE` 接住的）。

---

## 二、按同一口径扫出的其他潜在漏项（供参考，不一定都要改）

| # | 类别 | 数据 | 影响 |
| --- | --- | --- | --- |
| 1 | **9995 覆盖矩阵出现空洞** | 11-02 之后还能接住 9995 的规则只剩四条：`LINK_OUTAGE_9995_REGULAR_COOL`（COOL）、`LINK_OUTAGE_9995_REGULAR_COOL_VICTIMS_2-4`（COOL + 下游 4）、`SITE_OUTAGE_9995_VICTIMS_2-4`（REGULAR + 下游 2~4）、`LINK_OUTAGE_9995_ERA`（ERA，影响 2~4） | REGULAR + 下游 ≥5 的 Hub 站（Nwrokia 即此类）无任何规则命中 → 不建单 |
| 2 | **4758 整码不派单** | 全历史 10307 条，0 命中规则、0 建单；今天 4 条活动，其中 3 条分别起于 05-27 / 09-29 / 10-31（僵尸告警） | 只能靠我们 RPA 代派；我们的线又有两类失败：ME 名是 UUID 时站点解析不出（近两天多次 `N`）、超 180 分钟不再派 |
| 3 | **4 小时延迟规则族** | `SITE_OUTAGE_ERA*` / `SITEOUTAGE_REGULAR_COOL*` 的 Delay=14400s，实测建单耗时 240~277 分钟 | 99933 / 9980 / 9920 头 4 小时无单，SLA 已在计时 |
| 4 | **并单（Assign-AppendCopy）导致"看起来没单"** | 今天 6 条活动告警 `TT ID` 为空但 `Append TTID` 有单号（如 TT202611020033 / TT202611020024 / TT202611020049） | 外部只读 TT ID 列会误判成"未派单"；请确认这类子/根并单场景下正确的读法是哪一列 |
| 5 | **命中规则但单子没落地** | `assigned_status=5` 活动告警 2 条（5 天 / 14 天）；`assigned_status=4` 表示仍在延迟计时窗口 | 需要 eFlow 侧看派单失败原因 |
| 6 | **建了单但级别太低** | Nwrokia 今天 06:28:12 由我们的光纤任务建的 `TT202611030034`（4758）为 **P4**，至今 Waiting for FO Accept；同一故障的 MW 根告警按级别规则 277（Hub + 下游≥5 + 断站≤4）应为 **P2** | 派了单也没人接；请一并核对 9995/4758 的级别规则与接单提醒 |

---

## 三、我们的数据口径（便于复核）

- 实时部分：直接调用 eFlow 活动告警接口（与告警看板/同步任务同一套 payload），字段名按接口原文 `Assign RuleName` / `Assign Delay` / `Assigned Status` / `TT ID` / `Append TTID`。
- 历史部分：本地镜像 `app.history_alarm`（已清除告警，含 `assign_rulename` / `assign_delay` / `assigned_*` / `tt_id` / `ran_site_type` / `hub_site_flag` / `downstream_site_count` / `impact_site_number` / `reason_type`）与 `app.eflow_tt`（工单表，`created_time` / `alarm_occur_time` / `creator`）。
- 统计窗口：规则指纹与建单延迟取镜像内全部已清除告警（本地 `history_alarm` 最早约到 2026-08-01），4758 亦为同一口径；活动告警取 2026-11-03 08:30 前后快照（67 条）。
- 时间基准：统一按 eFlow 服务器时间（Africa/Monrovia = UTC+0），与工单表 created_time 可直接相减。
- 结论边界：我们只能看到"**命中了哪条规则**"，看不到规则条件原文；上面所有关于条件、阈值的判断都是反推，最终以 eFlow 配置中心的原文为准。

## 四、眼下需要人工处置的

1. **9995 / Nwrokia(3467)**：请派单侧人工补一张 TT，或确认由 06:28 那张 `TT202611030034` 接管并提级到 P2、推到 FO 接单。
2. 该站下游 13 个站、影响站点 3467/4112/4125，若 4112/4125 后续再报断站，同样会落进 Q4 的空洞（同为 REGULAR Hub 型）。
