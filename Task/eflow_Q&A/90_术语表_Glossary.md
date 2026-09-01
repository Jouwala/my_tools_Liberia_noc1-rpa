---
标题: eFlow 术语与缩写表
状态: 部分待验证
最后更新: 2026-09-01
作者: 如意
来源: 代码读取 + 数据库读取
---

# eFlow 术语与缩写表

> 分两部分：**已确认**（有代码/文档/数据依据）与 **待确认**（仅从字段名推测，未验证）。
> 对待确认的术语，AI 回答时必须提示用户核实。

---

## 一、已确认

| 缩写 | 全称 | 含义 | 依据 |
|---|---|---|---|
| **TT** | Trouble Ticket | 故障工单。告警自动或人工创建，是 eFlow 的核心对象 | `eFlow_API集成方案.md`；表 `eflow_tt` |
| **WO** | Work Order | 作业工单，挂在 TT 下执行（表中有 `TT NO.` 关联列） | `eFlow_API集成方案.md`；表 `eflow_wo` |
| **CR** | Change Request | 变更申请单 | `eFlow_API集成方案.md`；表 `eflow_cr` |
| **PM** | Preventive Maintenance | 预防性维护，即巡检任务 | `eFlow_API集成方案.md`；表 `eflow_pm` |
| **P1–P4** | Ticket Severity | 工单严重级别，P1 最严重 | `eflow_rules/README` 中 `Ticket Severity (P1-P4)` |
| **ttLevelRule** | — | TT 严重级别规则类型，eFlow 配置中心的规则分类 | `eflow_rules_README.md` |
| **autoCreateTT** | — | 规则触发步骤之一，告警自动创建 TT | `eflow_rules_README.md` |
| **NOC** | Network Operations Center | 网络运维中心 | 通用 |
| **SLA** | Service Level Agreement | 服务等级协议 | 通用 |
| **CSD** | Complete Site Down | **全部掉站**。出现在告警名 `sub_alarm_name` 中，如 `Complete site down (CSD)` | 库中共 14,292 条工单含此标记 |
| **PSD** | Partial Site Down | **部分掉站**。同上，出现在告警名中 | 库中共 2,882 条 |
| **G:3rd_Power** | — | 三方电源处理组，派单归属字段 `last_processer_group` 的取值之一 | 根因 POWER 的工单 73.1% 派往此处 |
| **G:ZTE_NOC_FO** | — | ZTE 自维一线现场组（FO = Field Operation？） | 待确认 FO 全称 |
| **TRM** | Transmission？ | `alarm_reason_type` 的取值之一 | ⚠️ 推测，待确认 |
| **Assign Delay** | — | eFlow 历史告警字段：派单规则内置延迟（秒）。SITEOUTAGE 类规则为 **14400s = 4 小时**，即告警后等 4 小时未自愈才自动派单 | `Assign Start Time = 告警发生 + Delay` 分秒吻合 |
| **SITEOUTAGE_REGULAR_COOL** | — | 自动派单规则名。SITEOUTAGE=掉站类，REGULAR=普通站（Site Attribute），COOL=站点电源类型（site_type） | 待确认各维度取值全集 |
| **Assign-Append** | — | 派单类型：告警发生后按延迟规则**追加**到已有 TT。后续发生的告警（如 3G）会追加进早期建的 TT，导致 TT 上的 `impacted_service`/`sub_alarm_name` 与派单时刻的真实状态不一致 | TT202608220047 实证 |

> ⚠️ **CSD 不等于「所有制式都掉」**：库中确实存在只掉 2G+4G（3G 正常）却标记为 CSD 的告警。
> CSD/PSD 由**上游网管 UFM 判定**并随告警名送来，eFlow 只是接收，不负责判定。

---

## 二、待确认 ⚠️

> 以下术语**仅从数据库字段名推测，未找到权威定义**。使用前请找熟悉 eFlow 的同事核实，核实后请上移到第一部分。

| 缩写 / 字段名 | 推测含义 | 出现在 | 备注 |
|---|---|---|---|
| **MOC** | Managed Object Class（管理对象类别）？ | `eflow_wo` | 也可能指维护对象分类，需确认 |
| **PMP No.** | PM Plan 编号？ | `eflow_pm` | 与 `PMT NO.` 的关系不明 |
| **PMT NO.** | PM Task 编号？ | `eflow_pm` | 猜测是巡检任务单号 |
| **fdn** | Full Distinguished Name | `site` | 网管系统常见，指网元全路径标识 |
| **Commune** | 村镇/社区 | `site` | 站点地址层级：Region > Province > District > Commune |
| **GS Type** | ？ | `site` | 可能指 GSM Site Type，待确认 |
| **TRM Type** | Transmission Type？ | `site` | 与 `Transmission Type` 是否同义待确认 |
| **Vender** | Vendor（厂商） | `eflow_wo` | ⚠️ 注意：库中拼写为 **Vender** 而非 Vendor，写 SQL 时别拼错 |
| **restypename** | 资源类型名称 | `realtime_alarm` / `history_alarm` | |
| **MW Layer** | 微波层 | `realtime_alarm` / `site` | MW = Microwave |
| **RAN Site Type** | 无线接入网站点类型 | `realtime_alarm` | |
| **MOC / MOP** | ？ | — | 若出现 MOP（Method of Procedure），指变更操作流程文档 |

---

## 三、容易混淆的一对

| | TT | WO |
|---|---|---|
| 是什么 | 故障工单（一个故障） | 作业工单（一次作业） |
| 关系 | 父 | 子，通过 `WO.TT NO.` 关联 |
| 数量级 | 约 2.8 万行 | 约 1 万行 |
| 典型场景 | 基站断站 → 建 TT | TT 派单给现场 → 建 WO |

> 数据来源：`D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`，2026-09-01 实际读取。

---

## 四、补充术语

新增术语请追加到对应表格，并在「依据」列写明来源。
把「待确认」变成「已确认」是最高价值的贡献——**这条只花你 2 分钟，但能省掉后面所有人 20 分钟。**
