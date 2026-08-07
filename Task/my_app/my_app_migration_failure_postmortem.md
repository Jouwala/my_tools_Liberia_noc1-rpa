# my_app 迁移失败复盘报告（Failure Post-Mortem）

> 文档性质：**预防性复盘**。迁移尚未执行（状态=规划定稿）。本报告基于 `D:\01_RPA\Task\my_app` 的**代码级全量枚举**（非抽样），记录"若迁移失败，会怎么失败、能否回退、根因是什么"，并把规划阶段已暴露的方法论失误一并归档。
> 配套基线：`my_app_migration_plan.md`（含 Phase R 回退方案 + 第 7/8 节）。
> 生成时间：2026-08-07；**2026-08-07 二次复核（本轮，全量枚举重跑，见 1.5 节）**

---

## 0. 一句话结论

- **功能是否会受影响**：按修订后计划（含本轮回查补的 3 个缺口 + 二次复核补的 4 个缺口）执行，**影响可控且可逆**；但**不亲手执行+回归就无法 100% 保证零影响**。
- **能否保证回退**：在 **R7（`DB_MODE` 熔断开关落地）+ 风险 10/11 引擎接线守卫 + R8 鉴权库硬排除 + 任务队列基础设施（task_runner/task_stats/worker）纳入 DB_MODE 分支** 四项闭环前，**回退不保证**；全部落地并演练后，**回退强保证**。
- **当前最大的"保证缺口"不是技术，是 `DB_MODE` 开关还没写**——它只是计划文字，不是代码（二次复核 grep 确认 backend 下 `DB_MODE` 零命中）。

---

## 1. 已验证事实（硬证据，非推测）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 全项目**唯一** `create_engine` 在 `database.py:12`，模块加载即绑定 sqlite；`DATABASE_URL=f"sqlite:///{DB_PATH}"` 硬编码 | `database.py:9-17` |
| F2 | 主连接入口 `get_raw_connection(db_path)`（`database.py:88`）被 **9 个 router + 多数 service** 使用；`main.py:103` 启动期 `Base.metadata.create_all(bind=engine)` | grep `get_raw_connection` 计数 + `main.py:103` |
| F3 | 运行期存在 **4 处裸 `sqlite3.connect` 绕过 `get_raw_connection`**：`ipran_chart_service.py:233`、`fw_kpi/fw_kpi_services.py:488`、`credential_store.py:154`、`battery_kpi_service.py:268`(兜底) | `grep -rn "sqlite3.connect(" backend` |
| F4 | 独立 ORM 基类：`PlBase`(`models/packet_loss.py:10`)、`BatteryBase`(`models/battery.py:9`)，**无各自 `create_engine`**（全项目仅 F1 一处） | grep `create_engine` + 读两 model 文件 |
| F5 | `eflow_tt` 唯一活写源 = `app.db`（`sync_from_eflow_api.py:20,531,364` 明确"不再依赖 eflow.sqlite3"），eflow.sqlite3 那份是遗留快照 | 代码注释 + 行号 |
| F6 | `realtime_alarm`/`history_alarm` 页面只读 `app.db`（`alarm_dashboard.py:38` 等 `get_raw_connection()`→默认 app.db） | 路由代码 |
| F7 | 本地 `db_ps_cs_cn.sqlite3` **已不存在**（二次复核修正：非"0 字节占位"而是文件已缺失，`db/` 与 `data/cnn_ume/` 两处均 MISSING）；真数据在远端 `192.168.100.19:8765`（FINEBI 在用），代码仅以逻辑名 `"db_ps_cs_cn.sqlite3"` 经 HTTP 引用（`ccn_ume_kpi_service.py:92`、`remote_db_reader.py:101`） | `Test-Path` 双路径 MISSING + grep 仅逻辑名命中 |
| F8 | **28 个**定时任务（`task_registry.py`，二次复核修正：非 27），其中 site_outage/whatsapp/kpi_sp/kpi_ran/mailbox_cleanup/cnn 图表等**不碰本地 sqlite**；**⚠️ email_recovery 例外**（见 D2） | `task_registry.py` 全文正则计数 |

---

## 1.5 二次复核增量发现（2026-08-07，全量枚举重跑）

| # | 发现 | 证据 | 对计划的影响 |
|---|---|---|---|
| D1 | **F7 过时**：本地 `db_ps_cs_cn.sqlite3` 两处副本**文件已不存在**（非 0 字节）。结论不变（无本地真副本可迁、整体排除），但"0 字节占位"表述作废 | `Test-Path` 双路径 MISSING | 计划 0.6/第 1 节措辞修正 |
| D2 | **email_recovery 并非"不碰本地 sqlite"**：`email_recovery.py:231,310` 经 `get_raw_connection(DB_PATH)` 查询 `app.db.task_execution_log`（失败邮件扫描/成功记录比对）。F8/7.2 矩阵将其归入"不影响"**有误** | grep + 源码阅读 | 该任务实际**受 app.db 迁移影响**，纳入回归清单 |
| D3 | **任务队列基础设施未列入影响矩阵**：`worker.py`(3 处)、`task_runner.py`(7 处 get_raw_connection + `INSERT OR REPLACE INTO task_schedule_config` :199/204 + AUTOINCREMENT :90 + `PRAGMA table_info` :169)、`task_stats.py`(5 处 + AUTOINCREMENT :27 + PRAGMA :42)。这些是 FastAPI 优化 Phase 3 新增，全部走 app.db，sqlite 方言密集 | grep 全量枚举 | Phase 3 改写清单 + R7 的 `DB_MODE` 分支**必须覆盖队列三件套**，否则迁移后定时/手动任务调度即坏，且回退无开关 |
| D4 | **ipran 图表本地库已是 0 字节**：`data/ipran_ume/ipran_ume_kpi.sqlite3 = 0 bytes`。`ipran_ume_kpi_service` 写入为 **API 优先远程、本地 sqlite 仅兜底**（:706-722），故本地库长期为空；`ipran_chart_service.py:233` 裸连读的正是这个空库 → **图表取数空是既有现状，不是迁移引入**。迁移时需决策：ipran 图表改读远端 API/PG，否则迁一个空库只是把"空"搬到 PG | 文件大小 0 + `ipran_ume_kpi_service.py:706-722` | 风险 S4 改写："迁移后静默坏图" → "迁移前已空，迁移是修复机会而非新风险；但必须定读源，不能原样搬空库" |
| D5 | **sqlite 方言耦合面大于计划清单**：全量计数 sqlite_master **20 处**（计划仅点名 ~3 处，漏：`tt_wo_dashboard.py:21`、`get_sp_table.py:294`、`fw_kpi_services.py:523`、`sync_from_eflow_api.py:680/694`、`analysis.py:38`、`ms_sla_report.py:338/391`、`packet_loss_dashboard.py:50`、`ran_ume_network_kpi.py:813`、`eflow_alarm_service.py:535`、`ran_ume_main_kpi.py:898`、`battery_dashboard.py:73`、`gis.py:31`、`system.py:85`、`eflow_data_mapper.py:1144`、`battery_kpi_service.py:402`、`alarm_dashboard.py:32`、`scripts/init_db.py:222`）；PRAGMA **53 处**；INSERT OR REPLACE/IGNORE **19 处**；rowid **7 处**；to_sql **13 处** | backend 全量正则计数 | Phase 3 改写面被低估，**墙钟 60–100 min 乐观**，建议上调或以"全量清单驱动"而非"点名驱动"执行 |
| D6 | `get_raw_connection` 调用点实测 **76 处**（9 router + 17 service + worker + scripts + main.py），注册表必须全覆盖 | 全量 grep 行号清单 | Phase 1 验收标准 = 76 处全部经注册表 |
| D7 | ms_sla 库实际文件名 `data/ms_sla/lbr_ms_sla_kpi.sqlite3`（`ms_sla_service.py:78`），计划范围表写"ms_sla"未错但需防搬运脚本按错名找文件 | 源码确认 | P5 搬运脚本库名清单以本节为准 |

> 仍成立的硬事实：F1（唯一 `create_engine` at `database.py:12`）、F3（恰 4 处裸 connect）、F4（PlBase/BatteryBase 无引擎）、F5（eflow_tt 唯一活写源 app.db，`sync_from_eflow_api.py:364,496`）、F6（告警页面只读 app.db）、R7 未实现（`DB_MODE` backend 下零命中）、`main.py:103 create_all`（且 :108 另有一处 AUTOINCREMENT DDL 同样需 `DB_MODE` 守卫）。

---

## 2. 功能影响面全量（回答"迁移后功能会不会有影响"）

- **受影响的功能** = 所有"本地 sqlite 取数/写数"的端点与任务。渲染层（openpyxl / matplotlib / PIL）操作内存 DataFrame，对底层 DB 无感，**产出形态不受影响**。
- **不受影响的功能**：site_outage 截图、whatsapp 发送、远端 FTP 报表（kpi_sp/kpi_ran）、cnn 图表（读 RemoteDBReader 远端）、mailbox_cleanup —— 它们不碰本地 sqlite，迁移对其透明。
- **⚠️ email_recovery 受影响**（D2 修正）：读 `app.db.task_execution_log`，迁移后须回归验证补发扫描仍工作。
- **⚠️ 任务队列三件套受影响**（D3 新增）：worker/task_runner/task_stats 全走 app.db 且 sqlite 方言密集，是生产调度心脏，迁移优先级最高、回归必测。
- **可控盲区**：ipran 图表(:233)、fw 图表(:488) 此前裸连 sqlite，已在 Phase 1 双层拦截 + Phase 3 改写覆盖；其中 ipran 本地库已是 0 字节（D4），迁移是修复机会。
- **本轮回查新增缺口**（计划已补）：PlBase/BatteryBase 独立引擎（风险 10）、`main.py:103 create_all` 双管理（风险 11）、credential_store 硬排除（风险 9）。

详细端点/任务矩阵见 `my_app_migration_plan.md` 第 7 节。

---

## 3. 失败情景树（每种失败：触发 → 检测信号 → 回退动作 → 回退是否保证）

| 情景 | 触发条件 | 检测信号 | 回退动作 | 回退保证 |
|---|---|---|---|---|
| S1 引擎切换即崩 | `database.py` 改 PG 后 `psycopg2` 缺失 / DSN 错 | 启动即 `ImportError` / 连接拒 | `DB_MODE` 切回 sqlite（R7） | ⚠️ 取决于 R7 是否落地 |
| S2 动态 DDL 改写错 | `_upsert_df` 的 `ON CONFLICT`/唯一键推断错 → 写入丢列/报错 | 同步任务持续异常、`eflow_tt` 行数偏差 | 停双写 + `DB_MODE` 回 sqlite；PG 用 `pg_restore` 基线 | ✅（sqlite 未删、双写领先） |
| S3 方言漏改 | 某处 `sqlite_master`/`datetime('now')` 未改 → 报表读空 | 报告 Excel 行数=0 / PNG 尺寸异常 | R1 影子对账拦截切流 + 回 sqlite | ✅（切流前已拦） |
| S4 ipran/fw 图表裸连漏处理 | Phase 1 双层拦截漏掉 :233 / :488 | 图表 PNG 空/报错（邮件发出但图坏） | 代码补拦截 + 回 sqlite | ✅（已纳入 P7 回归强制校验） |
| S5 **PlBase/BatteryBase 未接线**（风险 10） | Phase 2 只改 `database.py`，packet_loss/battery 仍连 sqlite | 部分表在 sqlite、部分在 PG，状态分裂 | 分别接线 + `DB_MODE` 分支回退 | ⚠️ 须风险 10 闭环 |
| S6 **create_all 与 Alembic 冲突**（风险 11） | PG 模式下 `main.py:103 create_all` 仍跑 | 启动报错 / 表被抢建 | `DB_MODE` 守卫后回 sqlite | ⚠️ 须风险 11 闭环 |
| S7 **credential_store 误迁移**（风险 9） | 注册表工厂未硬排除 → 鉴权库也走 PG | **全员登录失败 / 锁死** | 鉴权库本就未动 → 不受影响 | ✅（R8 硬排除后） |
| S8 PG 连接池耗尽 | 高并发写 + 池参数不当 | API 5xx / 任务超时堆积 | `DB_MODE` 回 sqlite + 调池参数 | ✅（sqlite 未删） |
| S9 数据偏差超阈值 | 搬运类型推断错（全 NULL 列→REAL 等） | R5 对账差异 >0.1% | 不切流 + 重跑 P5（`DELETE` 重导） | ✅（幂等） |
| S10 FW 锁旋转残留 | :496-505 逻辑未删 → 仍生成孤儿 sqlite 文件 | 磁盘出现 `fw_*.sqlite3_序号` | 删残留文件 + 代码删锁逻辑 | ✅（文件级，可清理） |
| S11 **任务队列三件套漏改**（D3） | worker/task_runner/task_stats 的 AUTOINCREMENT/INSERT OR REPLACE/PRAGMA 未改 PG 方言 | 定时任务不触发、手动触发 500、执行日志不落库 | `DB_MODE` 切回 sqlite（队列三件套须纳入分支） | ⚠️ 取决于 R7 覆盖队列层 |
| S12 ipran 图表读源未定（D4） | 原样把 0 字节本地库搬 PG，图表继续读空 | ipran 图表邮件持续空图（既有问题延续） | 非回退问题：决策改读远端 API/PG 数据源 | ✅（现状无恶化风险） |

**结论**：所有情景的回退都依赖"sqlite 原文件不删 + `DB_MODE` 秒级切回"这一底座；**S1/S5/S6/S11 的回退保证取决于 R7（含队列层）/R10/R11 是否落地**，这是当前唯一的真缺口。

---

## 4. 回退保障审计（能否"保证正常回退"）

### 4.1 已强保证
- sqlite 文件从不删除直到稳定期结束（双写期 sqlite 领先，回退数据不丢）。
- `pg_dump` 每段基线 + 增量 dump（PG 损坏可恢复）。
- 影子/双写闸门（R1）+ 切流 gating（R2）：未全绿不切，天然不破坏 sqlite。
- 分阶段幂等（R4）：P5 脚本可 `DELETE` 重导。
- credential_store 硬排除（R8）：鉴权库本就不动。

### 4.2 当前不能保证（切流前必须闭环）
1. **R7 `DB_MODE` 熔断开关未实现**（二次复核确认 backend 下零命中）——只是计划文字。若切流后发现问题但开关没落地，回退需手动改代码+配置，存在窗口风险。**切流前必须实现并演练"切回 sqlite = 全量回到原态"**。
2. **风险 10 独立引擎接线**——PlBase/BatteryBase 须带 `DB_MODE` 分支，否则出现 sqlite/PG 分裂态。
3. **风险 11 create_all 守卫**——PG 模式下必须跳过启动期 `create_all`，否则启动失败。
4. **任务队列三件套的 `DB_MODE` 覆盖**（D3 新增）——worker/task_runner/task_stats 是调度心脏，其 sqlite 方言改写必须与 `DB_MODE` 分支同步落地，否则回退时调度层回不去。

### 4.3 唯一真正确认零影响的方式
P7 影子比对（R5）+ 报告生成回归（逐一实跑 eFlow/ran_ume/packet_loss/battery/ipran/fw 报告并比对 Excel 行数/PNG 尺寸）+ 回退演练（R6）。**这三件事之前，任何"无影响"的断言都是未证实的。**

---

## 5. 规划阶段已暴露的方法论失误（必须归档，防止重犯）

| 失误 | 发生轮次 | 后果 | 修正 |
|---|---|---|---|
| **抽样即 generalization** | 早期评估只查 3 条报告链路就下"全部经 `get_raw_connection`、完全可控"结论 | 漏掉 ipran/fw 图表裸连盲区，用户判断"方案风险很大"正确 | 全量 `grep` 枚举（F3），推翻原结论 |
| **单一拦截点假设** | 初版把"拦截 `get_raw_connection`"当唯一兜底 | 裸连绕过点会被静默漏改 | Phase 1 升级为**双层拦截** |
| **漏算独立 ORM 引擎** | 本轮回查前未注意 PlBase/BatteryBase | 仅靠改 `database.py` 绑不到 packet_loss/battery 的 PG 连接 | Phase 2 补显式接线（风险 10） |
| **漏算启动期 create_all** | 本轮回查前未注意 `main.py:103` | PG 模式下与 Alembic 抢建/启动失败 | Phase 2 补 `DB_MODE` 守卫（风险 11） |
| **回退方案缺失** | 初版计划无 Phase R | 用户指出"为什么没回退方案" | 补 Phase R（R0–R8） |
| **影响矩阵漏新增基础设施** | 二次复核发现任务队列三件套（worker/task_runner/task_stats）与 email_recovery 未列入/误分类 | 调度心脏与邮件补发在迁移后可能静默坏 | 影响矩阵补 D2/D3，回归清单补对应项 |
| **事实不复核即引用** | "0 字节占位""27 任务"在文件/代码已变化后仍被沿用 | 结论虽未错但证据失效，损害计划可信度 | 二次复核全量重跑（1.5 节），以 D1/D5 实测数为准 |

> 根因：规划阶段沿用了"前向线性拆活"思维，注意力全在"怎么迁过去"，把"失败怎么办/怎么回退"和"sqlite 方言耦合全貌"两条独立工作流漏掉。对一套**两个库在生产、旁边挂着 FINEBI** 的系统，这是不可接受的。本复盘即对此的纠正。

---

## 6. 切流前置条件清单（全部打勾后才允许切 PG）

- [ ] R7 `DB_MODE` 熔断开关已实现，且演练"切回 sqlite = 全量回到原态"通过
- [ ] **R7 覆盖任务队列三件套**（worker/task_runner/task_stats，D3）
- [ ] 风险 10：PlBase / BatteryBase 显式绑定 PG 引擎（带 `DB_MODE` 分支）
- [ ] 风险 11：`main.py:103 create_all` 已由 `DB_MODE` 守卫
- [ ] R8：credential_store 注册表工厂硬排除（强制返回原 sqlite）
- [ ] Phase 1 双层拦截覆盖 4 处裸连（ipran:233 / fw:488 / credential / battery 兜底）
- [ ] Phase 1 注册表覆盖全部 76 处 `get_raw_connection` 调用点（D6）
- [ ] Phase 3 按全量方言清单执行：sqlite_master 20 处 / PRAGMA 53 处 / INSERT OR REPLACE 19 处 / rowid 7 处 / to_sql 13 处（D5）
- [ ] ipran 图表读源决策：改读远端 API/PG，不搬 0 字节空库（D4）
- [ ] R1 影子双写跑通，R5 对账差异 <0.1%
- [ ] P7 报告回归全绿（含 ipran/fw PNG 非空校验 + email_recovery 补发扫描 + 任务队列触发→落库链路）
- [ ] R6 回退演练一次（用备份库跑通切回）
- [ ] 你（人）在 R2 gating 全绿后拍板切流

---

*本复盘随 `my_app_migration_plan.md` 同步更新。任何一条前置条件未闭合，切流即视为违规。*
