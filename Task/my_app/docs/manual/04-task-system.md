# 04 任务与调度系统

my_app 的"心脏"。41 个定时任务负责全部数据采集与报表投递，页面上看到的数据新鲜度、失败告警、补跑行为都在这里定义。

> 另有两个**模块级说明文件**更贴近代码：`backend/WORKER.md`（worker 进程架构、容错、启停、环境变量）与 `backend/task_registry.md`（注册表字段与对外接口）。本章是归口叙述，改动这两处代码时请同步更新三份文档。

## 一条任务的一生

```
APScheduler 到点 (backend 进程内)
   └─► enqueue_task()  写 task_queue 一行（task_runner.py:153）
         └─► worker 进程 UPDATE ... RETURNING 原子认领（worker.py:196-217）
               └─► run_task() 执行真正的 service 函数（task_runner.py:379）
                     └─► _finish() 回写终态 + task_execution_log（worker.py:219）
```

关键点：

- **注册是代码注册表，不是配置文件**。41 条声明集中在 `backend/task_registry.py:72-403` 的 `TASK_SPECS`，启动时 `register_all_tasks()`（:405-429）逐条登记，采用懒加载包装（:58-64）——每条二选一给 `func`（需要特殊包装）或 `loader`（`("module.path","func_name")` 元组）。
- **cron 可以被库里覆盖**：默认值写在 `default_cron`，实际排程读 `task_schedule_config` 表（`task_runner.py:241-296`），所以在"任务管理"页改排程会立即生效且重启不丢。
- 另有一套**任务配置文件框架** `services/task_configs_registry.py:1-30`，优先级 `环境变量 > 配置文件 > 默认值`，用于任务的业务参数（不是排程）。
- **状态回传是纯 HTTP 轮询，没有 WebSocket**：`/api/tasks`、`/api/tasks/{id}/status|history|stats`。
- **降级模式**：未设 `MY_APP_TASK_QUEUE=1` 时，任务退回调度器进程内线程执行（`task_runner.py:527-553`），不经过队列、也不由 worker 认领。生产启停脚本会注入该开关（`backend_watchdog.py:137`）。

## worker 分组：组内串行、组间并行

分组动机写在 `worker_watchdog.py:41-44`：按"上游会话是否互斥/是否写同一库"分组，**同组串行等价于旧的单 worker 行为，组间并行**。

| 组 | 任务数 | 约束原因 | 成员 task_id |
| --- | --- | --- | --- |
| `u` | 12 | RAN UME 单账号会话，必须串行（并发会被踢会话）。`bp_report_sync` 也读 RAN UME，且必须排在 `main_kpi_sync` 之后（否则读到昨天的 KPI） | `ran_ume_daily`, `main_kpi_sync`, `cell_availability_sync`, `network_kpi_sync`, `packet_loss_sync`, `packet_loss_email`, `battery_kpi_sync`, `ipran_kpi_sync`, `cm_data_sync`, `cells_kpi_sync`, `avail_recon_sync`, `bp_report_sync` |
| `n` | 14 | eFlow API / config-center 同源会话（2026-09-27 由 17 项收窄，VMAX→`v`、SFTP→`s`、MW UME→`w` 已分头拆出） | `eflow_sync`, `eflow_sync_full`, `eflow_active_alarm`, `eflow_history_alarm`, `eflow_tt_rules_check`, `ms_sla_full`, `cnn_kpi_sync`, `fw_kpi_sync`, `sp_online_sync`, `sp_material_sync`, `eflow_alarm_rules_collect`, `eflow_push_rules_collect`, `ume_in_kpi_sync`, `ume_in_osg_report` |
| `s` | 1 | SP 备件 SFTP（独立 SFTP 服务器 + UNC 镜像库）。2026-09-27 从 `n` 拆出：它是 `n` 组最大单体负载（实测 347min/天）且是已知挂死源（SFTP channel 读挂死 5.5h 曾拖停整组） | `sp_data_sync` |
| `w` | 2 | MW UME 微波网管（凭证分组 `mw_ume`），独立会话。2026-09-27 从 `n` 拆出：`mw_ume_kpi_sync_rt` 为 `*/15` 高频任务，此前每次排在 `sp_data_sync` 后，实测队列等待 964s（全场最久） | `mw_ume_kpi_sync`, `mw_ume_kpi_sync_rt` |
| `v` | 3 | VMAX 门户（本机 8790 单会话代理）：三个任务共用同一个 VMAX 会话，必须彼此串行；2026-09-18 从 `n` 组拆出（原先排在 `sp_data_sync` 这类 1.5~2h 长任务后面，小时级采集滞后一个多小时） | `cxo_dashboard_cache_sync`, `vmax_cxo_daily_sync`, `vmax_multi_data_sync` |
| `m` | 35 | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 + VMAX 数仓 GBase 直连取数 | `site_outage_screenshot`, `whatsapp_send`, `whatsapp_send_ext`, `tt_alarm_whatsapp_alert`, `liberia_email_1h`, `liberia_email_8h`, `kpi_ms_contract`, `kpi_ms_wo_sla`, `kpi_sp_spareparts`, `kpi_sp_consumables`, `kpi_ran_availability`, `email_recovery`, `ipran_m6k_chart_email`, `ccn_free_rating_chart_email`, `battery_email`, `mailbox_cleanup`, `incident_overview_sync`, `auto_retry_failed`, `db_freshness_check`, `sp_report_generate`, `sp_email_details`, `sp_details_files_email`, `sp_online_report_generate`, `sp_online_report_send`, `sp_whatsapp_report`, `sp_material_report`, `finebi_report_sync`, `pg_to_sqlite_sync`, `log_cleanup`, `tmp_cleanup`, `mttr_tt_sync`, `progress_sync`, `olib_soc_kpi_daily_sync`, `olib_soc_vmax_report`, `tt_mttr_report_generate` |
| `c` | 2 | CN EMS 独立会话，两个任务共享 `_pmcache`/`daily_raw.json`，同组保证互斥 | `ems_kpi_cache_sync`, `ems_kpi_daily` |

> **2026-09-27 拆组（`n` → `n`/`s`/`w`）的实测依据**：`n` 组近 24h 单 worker 串行占用
> `sp_data_sync` 347min + `eflow_sync` 236min + `eflow_active_alarm` 103min ≈ 686min，
> 即约 48% 时间在忙且全挤在一条串行道上；队列实测最长等待 `mw_ume_kpi_sync_rt` 964s。
> 拆组后三组并行消费，且 `sp_data_sync` 再次挂死时**只影响 `s` 组**（不再拖停实时告警与 MW 实时看板）。

`m` 组末尾几条有注释记录：`finebi_report_sync`/`pg_to_sqlite_sync`（2026-08-25）、`whatsapp_send_ext`（08-31）、`sp_email_details`（09-01）、`cells_kpi_sync`/`sp_material_sync`（09-09~11）在启用分组模式后都因**未归入任何组而无人认领，队列 pending 卡死断档**才补进来（`worker_watchdog.py` 内的补录注释）。

> **新增任务必须同时登记进 `GROUP_TASK_MAP`；新增/调整「组」必须同步两处**：`worker_watchdog.py::GROUP_TASK_MAP` 的键、`start_hidden.ps1` 的 `$env:MY_APP_WORKER_GROUPS`（`restart_workers.py::ALL_GROUPS` 已改为从 `GROUP_TASK_MAP` 取键，无需单独维护；`start_hidden.ps1` 另有约 :250 的 `$groups` 等待清单也要同步）。只加分组表不改启动脚本 = 该组 worker 从不被拉起，症状与漏登记完全一样。
>
> 只写进 `TASK_SPECS` 而不分组 = 任务入队后永远 pending，且不报任何错。这是本项目已发生**四次**的事故模式，2026-09-18 第四次（`olib_soc_kpi_daily_sync`、`olib_soc_vmax_report`、`vmax_multi_data_sync` 上线后一次也没跑过，90 天经营看板停在 09-16）之后上了三道防线：
> ① `tests/test_worker_group_coverage.py`（不依赖 pytest，`python tests\test_worker_group_coverage.py` 即可跑，2026-09-18 实跑 PASS=5）—— 5 个用例：任务覆盖（缺项 + 幽灵 id）、同组不重复、三处组集合一致、共用 8790 会话的任务必须同组、前端任务帮助（`frontend/src/pages/helpTaskDocs.ts` 的 `TASK_DOCS`）与分组表一一对应且组名相同；任一项失配在跑测试时就失败。**跑它必须用 PATH 上的 `python`（系统 3.12）**，工作区的 `Scripts\python.exe` 与 `.venv\Scripts\python.exe` 都没装 apscheduler，用错解释器会报 `ModuleNotFoundError: apscheduler` 而“假失败”（看着像分组配错了）；
> ② `worker.py::_expire_orphan_pending`（每 300s）—— pending 超过 `STALE_PENDING_SECONDS`（默认 6h）仍无人认领就置 failed 并补执行日志，释放被它占住的单飞名额，让下一次调度能正常入队（以前一条陈旧 pending 会把该任务**之后每一次**调度静默挡在门外）；
> ③ `worker_watchdog.py::main()` 启动自检 —— 分组表与 `MY_APP_WORKER_GROUPS` 两侧任一漏改，看门狗启动时打 warning（只告警不退出）。

## 任务健康告警（漏跑不再靠人肉发现）

`db_freshness_check`（每小时 `15 * * * *`）除了查数据滞后，还算五类**任务执行健康异常**：

| kind | 判据 | 备注 |
| --- | --- | --- |
| `group_missing` | `TASK_SPECS` 有、`GROUP_TASK_MAP` 无 | 未登记 = 永不认领 |
| `silent` | 注册任务在回看窗口（`TASK_HEALTH_LOOKBACK_HOURS`，默认 24h）内**完全没有执行记录** | 按 cron 收紧：调度间隔大于窗口的低频任务（如 `59 23 */3 * *`）未到下一期不报；cron 解析不出来则宁可多报 |
| `stuck` | `task_queue` 滞留 pending>`10min` / running>`30min` | running 超时由 worker 周期回收补写失败 |
| `overdue` | 上次成功后按 cron 过一个完整周期（+grace）仍无新的成功 | 与 `silent` 互补：小时级任务中断 3 小时，`silent` 因当天有记录而不报 |
| `overdue_dependency` | `overdue` 的**子集**：最新一次失败是「外部依赖不可用」（EWS 401 / 连接失败 / 子进程超时）而非任务自身停摆 | 2026-09-18 新增。`overdue` 仍保留该任务（用于算 `status` 与 STALE 清单），本类只把告警**聚合成一条**并改文案，见下 |

2026-09-18 之前这些结果**只进日志没人看**（本次停摆两天是用户先发现的），故新增 `backend/services/task_health_alert.py` 把 findings 推到人前：

- **翻转去重**：以 `kind:task_id` 为键，状态文件 `TMP/task_health_alert_state.json`（原子写 tmp + `os.replace`）。新增异常通知一次、恢复通知一次，不再每小时刷屏；
- **持续重提**：同一异常持续超过 `TASK_HEALTH_ALERT_RENOTIFY_HOURS`（默认 24h）再提一次；
- **发送失败不记为已通知**：`notified_at` 留空，下一轮巡检自动重试；
- **通道**：微信 `weixin_notifier.send_weixin_message` + 邮件 `email_notifier.send_status_email`（复用 task_runner 的同两套凭据）；
- **降噪**：`overdue` 只收「近 24h 连尝试都没有」的真停摆；「跑了但一直失败」由 `task_runner` 的失败告警通道负责，不重复刷两条；
- **再降噪（2026-09-18 晚，`overdue_dependency`）**：`overdue` 中「最新失败是外部依赖不可用」的任务（EWS 401 / 连接失败 / 子进程超时）另归一类，**聚合成一条**告警并给出依赖侧（凭据/网络）修复指引。理由：一次 EWS 故障会连带十几个报表任务各自"逾期"，逐条推送等于刷屏，而真正要看的只有"EWS 挂了"这一条；
- **静音**：`TASK_HEALTH_ALERT_ENABLED=0`（维护窗口用）；
- 告警本身**不影响巡检结论**（异常置 `success=False` 会让巡检被 auto_retry 反复重跑），通知失败只记 warning。

> 同期修掉两个既有缺陷：`_cron_next_and_interval` 因 aware/naive datetime 相减抛 `TypeError` 被裸 `except` 吞掉，「成功逾期」维度自 2026-08-13 上线以来**从未生效**；以及「24h 无执行记录」对每 3 天跑一次的低频任务每小时误报一次。守卫见 `tests/test_task_health_detect.py`（检测判据）与 `tests/test_task_health_alert.py`（告警翻转去重，6 场景）。

### 测试任务不得进入运维告警（2026-10-06）

**现象**：运维收到一封失败告警邮件，内容为「统计失败 / `agg failure sample`」，堆栈落在 `tests/test_task_runner.py`。

**根因**：`tests/test_task_runner.py::test_get_task_stats_and_failures` 会**故意注册并运行一个必失败的任务** `__t_stat_bad__`（`raise RuntimeError("agg failure sample")`），以验证失败统计与失败聚类。测试 fixture 只 `monkeypatch` 了微信通知 `notify_task_failure`，**漏了邮件通知 `notify_task_failure_email`** —— 于是 `run_task` 的失败分支每次都会真发一封告警邮件给 126 邮箱。测试任务用 `__t_` 前缀命名，但统计/告警查询并未排除它们。

**修复（两层防御）**：

1. **测试侧堵源**：fixture 补 `monkeypatch.setattr(tr, "notify_task_failure_email", ...)`，与微信通知一起屏蔽；`test_get_task_stats_and_failures` 的失败聚合断言改用**非测试 ID**，并新增「`__t_` 任务不得出现在聚合里」的契约断言。
2. **运维视图隔离**：`backend/services/task_stats.py` 新增 `TEST_TASK_PREFIX = "__t_"`，在面向运维/前端的查询里排除测试任务 —— `get_recent_failures`（失败聚类 + active/recovered/needs_attention 分层）、`get_task_history`（最近历史）、`get_global_history`（含内存兜底）、`_fetch_latest_runs`（任务卡片最新记录）。`get_task_stats` / `get_task_history_by_task` 是**按 ID 精确查**，不过滤，以免破坏测试自身断言。
3. **`run_task` 新增 `is_test` 开关**（`register_task(..., is_test=...)`，默认 `False`）：测试任务仍正常落库（便于测试断言 `task_execution_log`），但**跳过微信/邮件/降级通知**。默认不影响线上行为。

> 约定：单元测试注册的任务一律以 `__t_` 开头。

## 全量任务清单（默认 cron）

下表与 `GROUP_TASK_MAP` 逐一对应（task_id 覆盖与组名由 `tests/test_worker_group_coverage.py` 校验，其中组名校验针对前端帮助；本表本身无守卫，新增任务后请手工补行）。

| task_id | 名称 | 默认 cron | 组 |
| --- | --- | --- | --- |
| `eflow_sync` | eFlow 数据同步 | `22 * * * *` | n |
| `eflow_sync_full` | eFlow 每日全量同步（大窗口下 TT/WO **分段拉取**，默认 30 天/段，避免单次大导出超过 120s 轮询窗口而 500 失败；TT/WO 缺失即判失败，不再静默成功） | `0 1 * * *` | n |
| `ran_ume_daily` | RAN UME 日报 | `0 2 * * *` | u |
| `site_outage_screenshot` | Site Outage 截图 | `0 1 * * *` | m |
| `whatsapp_send` | WhatsApp 消息发送 | `0 3 * * *` | m |
| `ms_sla_full` | MS SLA 完整同步 | `0 */6 * * *` | n |
| `eflow_active_alarm` | eFlow 实时告警同步 | `*/30 * * * *` | n |
| `eflow_history_alarm` | eFlow 历史告警同步 | `0 */3 * * *` | n |
| `eflow_tt_rules_check` | eFlow TT 规则收集与匹配检查 | `20 4 * * *` | n |
| `main_kpi_sync` | RAN Main KPI 同步 | `0 4 * * *` | u |
| `cell_availability_sync` | RAN 小区可用性 1-Day 同步 | `30 4 * * *` | u |
| `network_kpi_sync` | RAN Network KPI 同步 | `0 5 * * *` | u |
| `cnn_kpi_sync` | CNN UME KPI 同步 | `0 6 * * *` | n |
| `sp_data_sync` | SP 备件数据同步 | `10 * * * *` | s |
| `ipran_kpi_sync` | iPRAN UME KPI 同步 | `0 8 * * *` | u |
| `liberia_email_1h` | Liberia 宕站 1小时报告邮件 | `5 * * * *` | m |
| `liberia_email_8h` | Liberia 宕站 8小时报告邮件 | `10 */8 * * *` | m |
| `kpi_ms_contract` | MS Contract KPIs 日报邮件 | `30 17 * * *` | m |
| `kpi_ms_wo_sla` | MS WOs SLA 日报邮件 | `35 17 * * *` | m |
| `kpi_sp_spareparts` | SpareParts 备件报表邮件 | `45 9 * * *` | m |
| `kpi_sp_consumables` | Comsumables 耗材报表邮件 | `50 9 * * *` | m |
| `sp_report_generate` | SP 备件报表生成 | `15 5 * * *` | m |
| `kpi_ran_availability` | MS Network Availability 日报邮件 | `30 9 * * *` | m |
| `email_recovery` | EWS 恢复后邮件补发 | `*/20 * * * *` | m |
| `packet_loss_sync` | Packet Loss 丢包同步 | `30 6 * * *` | u |
| `packet_loss_email` | Packet Loss 丢包日报邮件 | `45 6 * * *` | u |
| `ipran_m6k_chart_email` | IP RAN M6K-FW 图表邮件 | `45 6 * * *` | m |
| `ccn_free_rating_chart_email` | CNN Free Rating 图表邮件 | `45 7 * * *` | m |
| `fw_kpi_sync` | FW 吞吐 KPI 同步+图表邮件 | `15 7 * * *` | n |
| `battery_kpi_sync` | 电池 KPI 同步 | `5 * * * *` | u |
| `battery_email` | 电池 KPI 邮件 | `0 7,19 * * *` | m |
| `mailbox_cleanup` | 邮箱空间清理 | `0 * * * *` | m |
| `incident_overview_sync` | Incident Overview 数据同步 | `20 * * * *` | m |
| `finebi_report_sync` | FineBI 报表文件同步 | `10 * * * *` | m |
| `db_freshness_check` | 数据库数据新鲜度巡检 | `15 * * * *` | m |
| `auto_retry_failed` | 失败任务自动重试 | `*/10 * * * *` | m |
| `cm_data_sync` | RAN CM 小区数据同步 | `30 8 * * *` | u |
| `pg_to_sqlite_sync` | PG→SQLite 数据快照 | `45 * * * *` | m |
| `mw_ume_kpi_sync` | MW UME KPI 同步 | `15 5 * * *` | w |
| `mw_ume_kpi_sync_rt` | MW UME KPI 实时同步（15 分钟粒度） | `*/15 * * * *` | w |
| `ems_kpi_cache_sync` | CN EMS KPI 缓存同步 | `*/15 * * * *` | c |
| `ems_kpi_daily` | CN EMS KPI 日粒度CSV | `20 0 * * *` | c |
| `vmax_multi_data_sync` | VMAX 多报表指标采集 | `45 * * * *` | v |
| `olib_soc_vmax_report` | OLIB SOC VMAX 例行报表 | `30 7 1 * *` | m |
| `olib_soc_kpi_daily_sync` | OLIB SOC 看板 KPI 增量 | `20 6 * * *` | m |
| `whatsapp_send_ext` | WhatsApp 消息发送（扩展） | `0 3 * * *` | m |
| `whatsapp_send_baileys` | WhatsApp 消息发送（Baileys；**默认禁用**，需在「任务管理」页手动启用） | `0 4 * * *` | m |
| `tt_alarm_whatsapp_alert` | eFlow P1 告警 WhatsApp 推送（**可在「任务配置」页调级别/告警码/触发窗口/重报间隔/群组**） | `*/5 * * * *` | m |
| `cells_kpi_sync` | RAN Cells KPI 同步 | `50 4 * * *` | u |
| `sp_email_details` | SP 备件明细报表邮件 | `5 7 * * *` | m |
| `sp_details_files_email` | SP 备件明细分文件邮件（6 份 xlsx 一文件一邮件发 NOC） | `5 10 * * *` | m |
| `sp_material_report` | SP 物料库存与消耗报表邮件 | `33 7 * * *` | m |
| `sp_online_report_generate` | SP 在线未关闭单报表生成（Inbound 读明细 xlsx；**Outbound 读库表 `sp_outbound`**，跟踪等待更新/等待归还/等待确认） | `0 6 * * *` | m |
| `sp_online_report_send` | SP 在线未关闭单报表发送 | `35 6 * * *` | m |
| `sp_whatsapp_report` | Comsumables&SpareParts Report Whatsapp | `55 7 * * *` | m |
| `sp_online_sync` | SP Online 工单同步（原始 filter 与状态全集 filter **取并集**，避免过滤条件与返回结果自相矛盾时静默取错数据；表语义=上游快照，**全量重建**删除上游已消失的单据，拉取不完整时只 upsert 不删除） | `35 */6 * * *` | n |
| `sp_material_sync` | SP 物料主数据同步（表语义=上游快照，**全量重建**删除上游已消失的物料，拉取不完整时只 upsert 不删除） | `55 4 * * *` | n |
| `ume_in_kpi_sync` | 客户业务 KPI 同步 | `45 5 * * *` | n |
| `ume_in_osg_report` | 客户业务 KPI + OSG 周报邮件 | `30 6 * * *` | n |
| `eflow_alarm_rules_collect` | eFlow 告警规则收集 | `59 23 */3 * *` | n |
| `eflow_push_rules_collect` | eFlow 推单规则收集 | `59 23 */3 * *` | n |
| `log_cleanup` | 日志文件清理 | `17 3 * * *` | m |
| `cxo_dashboard_cache_sync` | CXO看板数据缓存同步 | `*/10 * * * *` | v |
| `vmax_cxo_daily_sync` | VMAX CXO天粒度日值归档 | `15 * * * *` | v |
| `avail_recon_sync` | 可用率核对宽表重建 | `10 6 * * *` | u |
| `bp_report_sync` | BP Cells Report 更新（RAN_UME 增量 + UME 小时级活跃用户 + 周月重算 + 判定回填） | `20 6 * * *` | u |
| `tmp_cleanup` | TMP 目录清理 | `47 3 * * *` | m |
| `mttr_tt_sync` | MTTR/TT 宽表重建 | `40 7 * * *` | m |
| `progress_sync` | Progress 宽表重建 | `50 7 * * *` | m |
| `tt_mttr_report_generate` | TTs and MTTR 报表生成（供 EmailReports 页「TTs and MTTR」页签下载） | `20 7 * * *` | m |

### WhatsApp 发送通道矩阵（2026-10-08）

目前 `site_outage` 截图与文档的发送有**三种并行实现**，共享同一份图片目录
（`backend/services/data/site_outage/`）与群组配置（`WHATSAPP_GROUPS`），
但走完全不同的发送链路：

| 任务 | 通道 | 确认送达 | 依赖 | 默认 | 用途 |
|---|---|---|---|---|---|
| `whatsapp_send` | Playwright 自启 Chrome + WhatsApp Web DOM | 数 DOM 气泡（**假成功风险**——2026-09-15 SP Details Report 1.5MB 静默漏发） | 浏览器、Playwright、Node session 持久化 | `0 3 * * *` | 原版主通道 |
| `whatsapp_send_ext` | 浏览器扩展 + 已登录的 WhatsApp Web 标签页 | 数 DOM 气泡 + 双信号 | 浏览器开着 + WhatsApp Web 已登录 | `0 3 * * *`，但**已豁免主开关**（长期关闭） | 兜底 + 侧栏手动 |
| `whatsapp_send_baileys` | Baileys 协议直发（不走 Web） | **服务端 message id**（真实回执） | `whatsapp-kb-bot/src/notify.js` 常驻 + `auth-notify/` 凭据 | `0 4 * * *`，但**默认禁用**（`enabled=False`） | 治本通道（取代扩展、补充 Playwright） |

**为什么保留三条**：每条都有不同故障域——Playwright 任务会随 WhatsApp Web 改版失效；
扩展依赖浏览器开着 + 人工扫码登录；Baileys 走非官方库违反 ToS 有封号风险。
三条并存 = 任一通道挂了另两条兜底。半年内**不删**任何一条（避免单点）。

**Baileys 通道的额外要求**（与聊天机器人 / P1 告警推送共用 `whatsapp-kb-bot`）：

- **必须**用副号，不与员工工作号同号（参见 `whatsapp-kb-bot/README.md`「风险与前提」）；
- 启用前确认 `whatsapp-kb-bot/src/notify.js` 在跑、且 `data/notify_heartbeat.json` 新鲜（< 5 分钟）；
- 启用时**先在「任务管理」页手动执行一次**验证群内是否真的收到图+文档；
- 单作业配额由 `whatsapp-kb-bot` 的 `NOTIFY_FILE_SEND`（`.env`）/ `config.js → notify.fileSend` 控制。
  2026-10-11 起放宽为**图片 8 + 文档 3**（原默认 6 + 1）——SP 报表需一次发 2 份 xlsx，
  默认 1 份会把第 2 份**静默跳过**。my_app 侧 `whatsapp_dispatch` 的默认配额与之对齐，
  **两边改一个必须改另一个**；
- **已被主开关豁免**（`MASTER_SWITCH_EXEMPT_IDS`），批量切换不参与，避免「一键启用」把它打开。

#### SP 报表任务的双通道回退（2026-10-11）

`sp_email_details` / `sp_online_report_send` / `sp_whatsapp_report` 三个任务**不再直接**
调 Playwright，改为经 `backend/services/whatsapp_dispatch.send_with_fallback` 编排：
**Baileys 主通道 → Playwright 回退**（回退判据：投递失败 / 超时 / 零确认 / 任一单项有错）。
编排层细节与设计理由见 `architecture.md` 第八节决策记录。

- 发送者由「用户桌面 WA 主号」变为「Baileys 副号」（用户 2026-10-11 决策并接受）；
- 应急退场：设 `WHATSAPP_DISPATCH_CHANNEL=playwright` 可把三个任务整体打回 Playwright；
- 任务结果里带 `channel` / `fell_back` 字段，便于执行历史里区分实际走的哪条通道。

**「默认禁用」的实操**：`task_registry.py` 里 `whatsapp_send_baileys` 的 spec 带
`enabled=False`，`register_all_tasks` 会把它传给 `register_task`；首次启动后该任务
`enabled` 为 False、未排进 APScheduler。在「任务管理」页点开关（启用）即把
`enabled=1, current_cron='0 4 * * *'` 落库到 `task_schedule_config`，并触发
`schedule_task` 把它加进调度器。

### FineBI `schedule/` 的重算空档：读它的任务一律排在 :06 之后（2026-09-30）

**现象**：`incident_overview_sync` 报 `在 /webroot/WEB-INF/schedule/TT_WO 及其子目录下未找到 incident_overview.xlsx`，
2026-09-30 一天 18 次跑挂 8 次（05/08/09/11/12/13/16/17 点），微信+邮件每小时误报一次；
同一天 `finebi_report_sync` 报 `NUR_SLA: 未找到 Excel`。

**根因（实测，不是代码问题）**：FineBI 每小时 **:53** 触发重算，**先删掉上一轮的
`<报表>/<YYYY-MM-DD>/<HHMM>/通用结果/` 目录**，新副本约 **:02–:05** 才落盘。任意时刻源树只保留一份副本
（一层只有一个日期目录、再一层只有一个 HHMM 目录），因此 **:53 → :05 约 12 分钟里目录是空的**。
该任务的 cron 存在 `task_schedule_config`（库里 `3 * * * *`，与注册表默认 `0 * * * *` 已经不一致），
两个分钟都落在空档里。14:03/15:03 那两次"成功"是赶上落盘瞬间——远程 mtime 与任务认领时间同秒。
旁证：跑在 :10 的 `finebi_report_sync` 同期只有 NUR_SLA 一次缺文件。

**处理（三处，缺一不可）**：

1. **排期避开空档**：`incident_overview_sync` 的生效 cron 改为 `20 * * * *`（经
   `POST /api/tasks/{id}/schedule` 落到 `task_schedule_config`），注册表
   `backend/task_registry.py` 的 `default_cron` 一并改掉，避免新环境回到整点。
2. **把「源正在重算」与「源断了」分开判定**：`services/incident_overview_sync.py` 取不到文件时先看
   本地最新副本年龄，`NO_SOURCE_GRACE_MINUTES=90` 内返回 `success + skipped + note`（不告警），
   超龄才算失败并把年龄写进错误信息。`services/finebi_report_sync.py` 同理：单个目录本轮没有 Excel
   而本机已有历史副本 → 只记进 `missing`，**不再把整任务拖红**（一个目录的空档会连带其余已同步成功的
   报表一起被判失败）；本机连历史副本都没有才算 `error`。
3. **让"数据陈旧"本身可见**：`services/db_freshness_check.py` 新增 `FILE_CHECKS`（第 2b 类检查），
   按本机最新文件的落盘年龄判定文件型看板源（首条即事件总览的 `data/incident_overview/incident_overview_*.xlsx`，
   `max_age_hours=2.0`）。**取数任务红/绿 与 页面数据是几小时前的 是两件事**——2026-09-30 那次只有人
   看到任务告警，没人看到"页面停在 15:03 那份"。

   第 2、3 条是 `services/*.py` 代码，**必须重启认领它们的 `m` 组 worker 才生效**（模块已被长驻进程
   import，与本文件下方 `sp_data_sync` 一节「改动需重启 `s` 组 worker 才生效」同一回事）：
   `python restart_workers.py --groups m --mode worker --reason "..."`。
   只用 `--groups m`，**别顺手加 `--mode watchdog`**——那种模式会连 watchdog 一起杀，七组 worker 全部重来，
   只有在改分组清单时才必要（分组清单在 watchdog 内存里）。

**新增读 `/webroot/WEB-INF/schedule/` 的任务时**：cron 分钟 **≥ 06**；「未找到文件」默认按上游常态处理；
若该文件是某个页面的真相源，同步在 `FILE_CHECKS` 里加一条。**别再加第二条链路拉同一个文件**
（TT_WO 这份目前被 `incident_overview_sync` 与 `finebi_report_sync` 各拉一次到两个目录，属待合并的重复来源）。

### `sp_data_sync` 的镜像问题（2026-09-30 已根治 + 一次 worker 挂死事故）

排查「`n` 组为什么总是堵」时定位到两个独立问题。**缺陷一的根因已在 2026-09-30 查清并
从代码侧彻底解决（改为本地构建+整文件推送）；缺陷二已通过拆组 + 分段计时处理。**

**缺陷一（已修）：FineBI 镜像库长期写不进去，且会把 worker 永久卡死。**

`sp_data_sync` 的 `result_json` 里有 `mirror_success: false` 与 `mirror_errors`（5 张表全失败），
`detail` 统一是 `database is locked`。

> **⚠ 修正 2026-09-27 的结论（当时判断有两处错误）。**
> 1. **不是「WAL-over-SMB 天生不可用」。** 2026-09-30 实测：在同一 SMB 目录新建库、
>    甚至把它切成 WAL，只要**没有远端持有者**，本机打开与读写**都正常**。
> 2. **不是「本仓库无法单方面解决」。** 该结论建立在「`inventory.db` 的唯一写入方就是
>    my_app」这一错误推断上；实测远端确有其它活进程持库。而绕开它并不需要远端配合。

确切根因：**远端主机上有活进程长期持有该库的 `-shm` 字节范围锁**
（`inventory.db` 处于 WAL 模式，模式持久化在文件头）。SMB 无法代理这套共享内存语义，
于是本机**每一次** `sqlite3.connect()` 都被拒 —— 而且是以**永久阻塞**的形式，
不是抛异常，`timeout` / `busy_timeout` 对它完全没有作用。

2026-09-30 逐项排除后的实测对照：

| 探测 | 结果 | 含义 |
| --- | --- | --- |
| 裸 `open()` 读主库 | **成功**（`SQLite format 3`） | 文件本身完好、共享可达 |
| 复制主库到本机再打开 | **成功**，`journal_mode=wal`，5 张表齐全 | **数据库没坏** |
| 在同一 SMB 目录**新建** sqlite 库 | **成功** | SMB 本身能跑 SQLite |
| 把该新库切成 WAL 后打开 | **成功** | WAL 本身在 SMB 上可用 |
| 独占打开远端 `inventory.db-wal` | 被拒（`being used by another process`） | 远端有活进程持锁 |
| 独占打开远端 `inventory.db-shm` | 被拒（`another process has locked a portion`） | **持的是 `-shm` 字节锁** |
| 打开生产 `inventory.db` | **立即** `database is locked` | 本机永远连不上 |
| **整文件 `copyfile` 覆盖生产库** | **成功（即使库正被占用）** | ← 这就是修法的依据 |

**修法：不再直连远端库，改为「本地构建 + 整文件推送」**
（`backend/services/sp_mirror_push.py`）。
在本机临时目录建一个新库（`journal_mode=delete`、单文件），再用 `shutil.copyfile`
整文件覆盖过去 —— **整文件覆盖不需要 SMB 字节锁**，因此远端持库也不影响。

> 关键简化：**不再需要旧的「远端反连接增量追加」**。镜像内容直接取自 `app.db`，
> 而 `app.db` 的 `inventory_details` 本身就是「历史累计 + 保留期清理」后的全量结果
> （`get_sp_table._write_table` 的 APPEND 分支已完成合并去重），
> 因此本地构建出的库与 `app.db` **天然同口径**，比旧实现更简单也更准。

实测效果：本地构建 1.0s + 推送 0.5s（约 90MB/s），**一轮镜像合计约 2s**，
对比旧路径的「永久阻塞直到人工重启」。同时生产库从 113MB（含 14.7MB 未 checkpoint 的
`-wal`）降到 47.7MB 单文件，`integrity_check=ok`，`ocrule_details` 表此前在远端**整个缺失**，
现已补齐。

> **回滚路径**：`sp_sftp_config.json` 的 `mirror_mode` 设为 `"direct"` 可切回旧的直连实现
> （保留在 `get_sp_table._mirror_write_all_direct`，**默认禁用**）；设为 `mirror_enabled=false`
> 则完全关闭镜像。

**并发事故（2026-09-30）：镜像挂死会把整组 worker 卡死 6 小时以上。**

09:10 那轮 `sp_data_sync` 卡在镜像阶段，worker 进程 `64468` 一直存活（单线程、CPU 零增长），
持有远端 `inventory.db` 与 `inventory.db-wal` 句柄。它直到 10:22 服务栈重启才被判失败回收，
且它持有的句柄让后续每一轮镜像继续撞 `database is locked`。
任务页面上的报错是 `❌ Worker 进程中断，任务未完成（启动时自动回收）`
—— **但它并没有"中断"**，pid 一直活着。

对应修复两条：

1. **镜像阶段加进程级硬超时**（`get_sp_table._run_mirror_with_timeout`，
   `MIRROR_HARD_TIMEOUT_SECONDS=900`）。`sqlite3` 的 `timeout`/`busy_timeout` 管不到
   SMB 层的 open 与字节锁，所以必须由调用方给上限。
2. **回收文案区分「进程已失效」与「任务挂死」**（`worker.py`）。旧文案一律写
   `Worker 进程中断`，而实测那次 pid 存活、真实故障是**任务挂死**——
   照字面排查会被引向"崩溃"这个错误方向。

> **回滚/排障时注意**：`worker.py` 的时间阈值回收（`TASK_MAX_RUNNING_SECONDS`，默认 4h）
> 与本次的 15min 镜像硬超时是**两层不同的兜底**，前者兜「任何任务挂死」，后者兜「镜像这一处」。

> **已做的代码侧改进（2026-09-27，保留）**：
> 1. **不再静默**：镜像失败会追加进 `result["warnings"]`，并由
>    `task_runner.py` 在 `success=True` 时也消费 warnings 发出**降级告警**
>    （此前告警只在 `success=False` 触发，所以看板停更半个月而监控全绿）。
> 2. **诊断可执行**：`_diagnose_mirror_failure()` 把 `database is locked` 翻译成可执行结论
>    （其旧文案里"WAL-over-SMB 架构限制、本仓库无法解决"的措辞已按上文更正）。
> 3. 守卫用例 `tests/test_engineering_guards.py` 的
>    `test_mirror_failure_is_surfaced_as_warning`、
>    `test_mirror_never_connects_remote_db_directly`、
>    `test_mirror_stage_has_hard_timeout`、
>    `test_worker_recovery_message_distinguishes_hang_from_crash`
>    钉住上述结论，防止退回静默或退回直连。

> **排查 FineBI 仓库看板数据不动时**：不要只看任务成功状态 —— 看
> `result_json` 的 `mirror_success`，或看是否收到过 `[降级]` 通知。
> 2026-09-30 起还可直接看日志里的 `[耗时] 镜像本地构建 Xs` 与 `[镜像] 推送完成`。

> **⚠ 2026-09-28 已修的回归（上面第 2 条改进自己引入的）。** `_diagnose_mirror_failure()`
> 把诊断**字符串**塞进了 `_mirror_write_all()` 返回值的 `_diagnosis` 键，而消费侧
> `run_sp_data_sync()` 原先按 `v.get("status")` 遍历该返回值的全部键，于是在镜像失败的
> 每一轮都抛 `AttributeError: 'str' object has no attribute 'get'`。异常被外层 `try` 捕获后
> 包装成 **"SFTP 连接/同步失败(第N次尝试)"** —— 三个后果都误导排查：
> ① 报错文案指向 SFTP，而实测 `[耗时] SFTP下载+入库 ≈17s` 说明下载入库一直是好的；
> ② 触发 `SFTP_MAX_ATTEMPTS=3` **整轮重试**（重新下载 5 份报表 × 3 + 每轮 2 次镜像重试与
> SMB 探测），单轮耗时从 ≈534s 涨到实测 **1576s**；
> ③ 任务被判 `success=False`，上面第 1 条精心加的**降级告警根本没走到**，
> 报告里只显示含糊的 `'str' object has no attribute 'get'`。
> **修法**：遍历只取表条目（`not t.startswith("_")` 且 `isinstance(v, dict)`），
> 见 `get_sp_table.py` 的 `mirror_errs` 推导式。**改动需重启 `s` 组 worker 才生效**
> （`python restart_workers.py --groups s --reason "..."`，模块已被长驻进程 import）。
> 教训：**往聚合返回值里混入与业务条目不同形状（str）的元数据键时，所有遍历该 dict 的
> 消费点都要同步收紧**，否则诊断信息反而成了崩溃源。

**缺陷二：单次固定耗时约 534s，正好吞掉 `:15` 触发点。**

实测 76 次中位 534s、区间 484~545s，极稳定。它在每小时 `:10` 启动、占线到 `:19`，
而 `eflow_active_alarm` 是 `*/5`（`:10/:15/:20`）——`:15` 那次必然排队。

> **分段计时已补（2026-09-27）**：`get_sp_table.py` 现在打两行
> `[耗时] SFTP下载+入库 Xs` 与 `[耗时] 镜像写入 Xs`，并把数值写进
> `result_json` 的 `sftp_seconds` / `mirror_seconds`。
> 此前只能靠 SFTP 会话起止粗估（`[完成]` 先于会话关闭打印，两者混在一起无法区分）。
> 拿到这两行后即可确认 534s 的真实构成。

这解释了 `eflow_active_alarm` 实测 **419 次/天（理论 `*/5`×24h=288 次，超 1.45 倍）**：
超出的不是"重试"，而是**队列在 worker 忙碌期间累积后补跑**，实测平均等待 59s、最长 688s。
`2026-09-27` 拆组（`sp_data_sync` → `s` 组）后两者不再互相阻塞，此现象应随之消失；
**若拆组后 `eflow_active_alarm` 仍显著超过 288 次/天，则另有一个独立成因待查。**

### `cn_kpi` 页面的两条供数链路：一条自动、一条人工（2026-10-01）

`?page=cn_kpi` 读的 `db_ps_cs_cn` 里，同一个 KPI 可能有**两张同名不同源**的表，
分属两条**彼此独立**的流水线 —— 这是该页曾经整块空白的根因，改这里的东西前必须先分清：

| 表后缀 | 写入方 | 触发 | 覆盖范围 |
| --- | --- | --- | --- |
| `_EMS` | `Task\PS_CS_CORE_Scripts\ps_cs_core.py`（**不是本项目的任务，不进 `TASK_SPECS`**） | **人工**导出 CSV 后手动运行 | 8+ 个模板，含 USSD / LOCATION_UPDATE |
| `_UME` | 任务 `cnn_kpi_sync`（本项目，每天 06:00，`ccn_ume_kpi_service.py`） | 自动 | **仅 8 个模板**（`CNN_KPI_QUERY_CONFIGS`） |

**两条链路的三个不对称**（都实测过，别再踩）：

1. **覆盖面不同**：`USSD_RATIO` 与 `LOCATION_UPDATE` **没有 UME 孪生表**，
   只有人工链路。人工不跑 → 这两个 KPI 永远停在最后一次导出。
2. **写入模式不同**：`ps_cs_core.write_via_api()` 用 `mode="full_replace"`（**整表覆盖**），
   `ccn_ume_kpi_service` 用 `mode="upsert"`。所以人工导出会把整表**连粒度一起换掉** ——
   选了「2026-04-01 ~ 10-01」导出，表就从 `1Day(s)` 变成 `1Month(s)` 的 6 行。
3. **停摆表现不同**：`_EMS` 停摆是**静默的**（表还在、只是没新行），
   页面原先不会报错，只是图变空或点变少 —— 这正是最难排查的一类故障。

**因此**：`cn_kpi_service.py` 实现了三级降级取数 + 粒度标注，
判定规则与排查手段见 `11-feature-guide.md` 第 33 节。
**不要把「图是空的」直接归因为「数据库里没有」** ——
先按 33.6 的三步确认是停摆还是粒度漂移（2026-10-01 的实例：
USSD 的日表当时只剩 2026-08-25~27 三行，而月表里有完整的 6 个月）。


### `olib_soc_kpi_daily_sync` 的三类自愈（2026-09-24 首次加固，2026-10-11 再次加固）

该任务给 VMAX 90 天经营看板（`?page=vmaxCxoDashboard_90Days`）供数，每天 06:20 只补
`daily_kpi` 里缺的天。它的「缺口」判定有**三类**，缺一不可：

| 类型 | 判定函数 | 背景 |
| --- | --- | --- |
| 整天没有行 | `olib_soc_kpi_store.gap_days()` | 任务被跳过 / 数仓分区晚到 |
| **有行但关键指标为 NULL（窗口内）** | `olib_soc_kpi_store.incomplete_days()` | 单个块临时取数失败，仍写入一行，只是该块那列为 NULL |
| **有行但关键指标为 NULL（窗口外）** | `olib_soc_kpi_store.all_incomplete_days()` | 同上但不限回看窗口，补滑出窗口的历史残留 |

第二类是 2026-09-24 的线上事故：`blocks_ok` 从 7 掉到 6 却**不报错**，
`gap_days` 也不认为缺天，于是 `active_user` 在 2026-09-18~23 **连丢 6 天**且永久残留
（看板「Active Users」停在 17 号）。判定列见 `olib_soc_kpi_store.REQUIRED_COLUMNS`
（**全部主数值列**，不再只是 `traffic_tb` / `active_user` / `video_tb`）；取数幂等，重取一次即自愈。

第三类是 2026-10-11 加固：`incomplete_days()` 只看最近 N 天，历史残留一旦滑出窗口就永远补不到
（实测 2026-09-07 的 `traffic_tb` 残留了整整一个月）。同步任务现在额外扫全表，
把窗口外的残缺日**单独跑一次**（不并进主 `gaps`，否则区间会暴涨）。

**取数侧**（2026-10-11）：`run_block()` 新增 `days_empty` —— 「分区缺失」或「分区在但查出 0 行」
都算该块某天没取到数，块降级 `partial`；`BLOCKS_ALLOW_EMPTY_DAY`（TOP 业务/游戏）例外。

> 排查同类问题的第一步：`SELECT day, blocks_ok FROM daily_kpi ORDER BY day DESC`，
> **`blocks_ok` 小于块总数（看板为 7）的那天就是残缺日**。
> 也可以直接 `curl /api/olib-soc-dashboard/status` 看 `incomplete_days` 计数；
> 看板页面顶部在存在缺口日时会显示「数据完整 x/y 天 · 缺 n 天」提示条，明细表对应行标「数据残缺」。

### `tt_alarm_whatsapp_alert` 的口径与实测坑（2026-09-28 首版，2026-10-05 机制切换）

**触发制**（2026-10-05 起）：每 **5 分钟**扫 `realtime_alarm`（由 `eflow_active_alarm`
同步的实时告警表，注册表默认 `*/30`、**实际周期以任务配置页的调度为准**，生产已配
`*/5`），挑出「带 TT（`tt_id` 非空）+ 告警升起时间
（`alarmraisedtime`，epoch 毫秒）在触发窗口内 + 告警码在白名单内」的告警，
随后**实时回 eFlow 查单**（`eflow_data_mapper.fetch_tt_live_batch`，一次分页遍历
匹配全部目标单）拿当前 `ticket_severity` / `last_modified_time` / `alarm_clear_time`，
只推级别命中的单。发送状态落 `eflow_tt_whatsapp_alert_log`。

> **为什么触发源不是 `eflow_tt`**：那张表由 `eflow_sync` 每小时 :22 才落库，
> 旧机制（每 15 分钟扫它的 3 小时窗口）端到端时延 45~75 分钟，对 P1 太慢。
> `realtime_alarm` 新鲜度（生产 `*/5` 同步）+ 本任务 5 分钟轮询 + 实时查单，
> 首推时延压到分钟级。触发扫描的完整口径见
> `backend/services/tt_alarm_trigger.py` 的模块 docstring；三层单据来源
> （实时/镜像/触发行）的取舍见 `tt_alarm_sources.py`。

**消息内容 = `whatsapp-kb-bot` 的完整 TT 分析**（2026-09-29 按用户要求改）：

| 段落 | 内容 |
| --- | --- |
| 头部 8 行 | 单号·站点｜标题 / 告警 / 告警对象 / 影响 / 级别 / 命中规则 / 判定依据 |
| `[Milestone timeline]` | 9 个里程碑（告警发生→建单→接单→派单→填报→…），带耗时与经办人 |
| `[Assignment basis]` | 创建/派单命中了哪条规则、路由到哪个组、命中条件 |
| `[Timeliness]` | SLA 达成情况、目标时长、截止与剩余、故障持续时长 |

> **不在本任务里自己拼这套格式**，而是子进程调
> `Task/whatsapp-kb-bot/scripts/tt-analyze.py`（2175 行，纯标准库 + openpyxl）：
> 那是**群里机器人回答问题时用的同一个引擎**，两份分析逻辑并存必然分叉，
> 而「群里的分析」与「告警推送里的分析」不一致是最难排查的那类问题。
> 封装见 `backend/services/tt_alarm_render.py`。
>
> **引擎读的是 SQLite 副本 `db/app.db`，不是生产的 PG**（`tt-analyze.py:57`），
> 而该副本由 `pg_to_sqlite_sync` **每小时第 45 分**才刷新一次 —— 本任务每 5 分钟跑一次。
> 2026-09-29 实测到最坏情况：副本落后 **84 分钟**（SQLite 最新 `alarm_occur_time` 16:17
> vs PG 17:41；17 点这一小时 PG 有 5 单、SQLite **0 单**）。
>
> 后果：**副本落后期间每一条新告警都会降级成 7 行模板** —— 这不是偶发异常，
> 而是这个任务的常态，也正是用户报「发的信息不是我想要的」的真正原因。
>
> 修法是渲染前用 `tt_alarm_render._snapshot_tt()` 造一份「这一单」的新鲜快照指给引擎
> （只抄一单，开销与单量无关，实测每次 <50ms）：本地镜像已有该单时从 PG 抄；
> **刚触发、镜像里还没有的新单直接用实时查单行造快照**（引擎读快照时按
> `PRAGMA table_info` 与自己的列清单取交集，实时行的紧凑字段集不会让它报错）。
> 拿不到快照时退回镜像库 —— 宁可降级，也不能因快照失败就漏发整条告警。
> 不去改引擎本身：它是 `whatsapp-kb-bot` 的共享组件（群机器人也在用），
> 且它依赖 `immutable=1` 打开 SQLite，改成 PG 会牵动全文。
>
> **降级会在任务结果里显式暴露**（`degraded` 计数 + `errors` 里逐单原因），
> 因为降级**不报错、照样发得出去**，只是内容从 ~30 行缩成 6 行 ——
> 没有这个字段，运维只能靠群里的人问「这次信息怎么这么少」才发现。
> 看到 `degraded > 0`，第一件事是查快照是否失败（`[TTAlert] 取 PG 单行失败`）。
>
> ⚠️ **超时是踩过的坑（2026-09-29）**：引擎单独跑只要 **0.3~0.5 秒**，
> 但与 `pytest` 全量**并发**时曾超过 60 秒被判超时（读 1.5G 的 `app.db` + 两张 xlsx，
> 抢磁盘所致，机器有 28 核并不慢）。故默认超时放宽到 **120 秒**
> （`TT_ALERT_ANALYZE_TIMEOUT`）—— 这个引擎的耗时**对磁盘 IO 竞争极其敏感**，
> 正常值是秒级，一旦排队就是几十秒，余量给足远好过把完整消息降级成残篇。
>
> 语言由 `TT_ALERT_LANG` 控制（默认 `en`）；超时 `TT_ALERT_ANALYZE_TIMEOUT`（默认 120s）；
> 引擎路径可用 `TT_ALERT_ANALYZE_SCRIPT` 覆盖。引擎不存在时同样降级。
> 契约由 `tests/test_tt_alarm_render.py` 锁定，其中真实层用真实单号逐字回放，
> 新鲜度链路（快照建/删/传参/失败退回）另有 5 条单测 + 1 条突变验证防回归。

**这张单的四个口径都可在页面上配置** —— 「设置 → 任务配置 → `eFlow P1 Alarm WhatsApp Push`」
（配置文件 `backend/services/tt_alert_whatsapp_config.json`，注册在
`backend/services/task_configs_registry.py`，读写实现见 `backend/services/task_config_files.py`）：

| 配置项 | 页面标签 | 留空 / 默认的含义 |
| --- | --- | --- |
| `window_minutes` | 触发窗口（分钟） | 默认 180；**2026-10-05 语义已变** —— 指 realtime_alarm 中 `alarmraisedtime` 距今 N 分钟内才触发首推（兼防首次部署把历史积压一次性全推出），不再是 eflow_tt 的 occur 窗口 |
| `resend_minutes` | 重报间隔·有更新档（分钟） | 默认 30；自上次发送以来工单**有更新**（有人在处理）→ 距上次发送满 N 分钟才重报（较缓） |
| `stall_minutes` | 重报间隔·无更新档（分钟） | 默认 10；自上次发送以来工单**没更新**（一直没人动）→ 距上次发送满 N 分钟即催报（较勤） |
| `severities` | 级别 | 默认 `P1`；**留空 = 不限级别**（P1/P2/…全推） |
| `alarm_codes` | 告警码 | 默认不含 `99933`；**这是白名单**，留空 = 不限告警码 |
| `groups` | WhatsApp 群组 | 默认 `test123`；**留空会回退到测试群并在结果里告警**（见下） |
| `mail_enabled` | 邮件开关 | 默认 `true`；控制首次通报/结束汇总邮件是否发送（收件人在「邮件收件人」页，不在此表） |

> **两个语义容易记反，改配置前先确认**（2026-09-28 按用户要求调整为现状）：
> 1. **告警码是「白名单」而不是「排除表」**。`99933` 之所以默认不推，只是因为它**不在**
>    默认白名单里 —— 用户把它填进白名单就会推送。空 = 不过滤（全推），不是「全不推」。
> 2. **群组留空回退到 `test123`，不再拒发**。回退时任务结果的 `group_fallback` 为 `true`，
>    并在 `errors` 里带一条「正在发往测试群」的告警 —— 这是刻意的：**避免有人清空配置后
>    生产 P1 告警静默消失**。看到这条告警说明群组没配对，请去页面补上真实群名。

> ⚠️ **「空集当无条件」这个坑实际发生过**：过滤写成 `x not in SEVERITIES` 时，级别留空会让
> 集合为空、`in` 恒为假，于是**每一单都被丢掉**（界面标签却写着「留空=不限」）。已修为
> `if SEVERITIES and ... not in SEVERITIES`，并有变异测试守着
> （`tests/test_tt_alarm_config.py::test_empty_severities_means_no_filter_not_drop_all`）。

### 同步发邮件（2026-10-06 新增，Orange EWS）

用户要求：**发 WhatsApp 的同时也发邮件**，主题英文 `P1 TT Progress Notification`。
时序与范围由用户当面明确为两条，实现严格照此：

| 时机 | 发什么 | 幂等键（日志表列） |
| --- | --- | --- |
| 每单**第一次**通报**确认发出后** | 完整分析（与 WhatsApp **同一份内容**，原样内嵌不重渲染） | `mail_notified_time` |
| 该单**结束**（`alarm_clear_time` 非空） | 生命周期时间轴 + 总历时 | `mail_summary_time` |

重报（20 分钟停滞再推）**不发**邮件。两列非空即「已发过」，**永不重发**。

**收件人不写死在代码里** —— 走已有的「Settings → 邮件收件人」页
（`backend/services/email_recipient_store.py` 的 `tt_alarm_p1_email` 组，
默认 `dong.xinmin@zte.com.cn`）。该页是收件人的**唯一真相源**：页面保存值优先、
30 秒缓存生效、无需重启。开关是任务配置页的 `mail_enabled`
（环境变量 `TT_ALERT_MAIL_ENABLED`，默认开）。

**通道是项目的 Orange 邮箱**（发件人 `ztenoc.olr@orange.com`，凭据组 `owa_mail`），
不是 126 —— 用户 2026-10-06 明确指定。实现见 `backend/services/tt_alarm_mailer.py`。

> ⚠️ **汇总不能挂在活跃告警循环上（本特性最容易做错的一点）**：告警一清除，该单就
> 从 `realtime_alarm` **彻底消失**（2026-10-06 实测：4 个已清除单在实时表里 **0 命中**，
> 而 `eflow_tt` 里 4/4 都在）。所以主循环里那个 `if cleared:` 分支**几乎永不命中** ——
> 汇总若挂在那里，**一封都发不出去**。故汇总走**独立的日志表扫描**
> （`store.pending_summary_mail()` 选「发过通报 + 未发汇总」的候选，再回 `eflow_tt`
> 查 `alarm_clear_time`），与告警是否还活跃无关。三条早退路径
> （无候选 / 无 due / 投递失败）**都必须调用** `run_summary_mail_scan()`
> —— 「本轮没有新告警」恰恰是最常发生的情况，而「某单该发汇总了」与之无关。

> ⚠️ **幂等列不能被 upsert 抹掉**：日志表 upsert 是**整行覆盖**，一旦
> `mail_summary_time` 被写成 NULL，同一单的汇总会被**反复重发**（清除是持久事实，
> 不会自己消失）。`store.base_record` 原样保留这两列，且 `record_result` 在调用方
> 未传 `existing` 时会主动回查一次兜底。`tests/test_tt_alarm_mail.py` 有两条
> 突变验证守着（故意破坏即失败）。

**邮件失败绝不影响推送**：`tt_alarm_mailer.send_mail()` 只返回 bool、不抛异常，
失败只记进任务结果的 `warnings` 与 `mail_notified_failed` / `mail_summary_failed`
计数 —— 邮件是 WhatsApp 之外的附加通道，它挂掉不能让告警推送"失败"。

> **两个实测坑（写进 `tt_alarm_mailer.py` 模块 docstring，勿重犯）**：
> ① `EXCHANGE_2016` 是 `Build` 不是 `Version`，必须包
> `Version(build=EXCHANGE_2016, api_version="Exchange2016")`，否则 `InvalidTypeError`；
> ② 内网 EWS 自签证书，必须设 `Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter`，
> 否则 `SSLCertVerificationError: unable to get local issuer certificate`。
> 另：`liberia_email_report.py` 里「后端未装 exchangelib、须用托管 venv 子进程」的
> 注释**已过时** —— 实测后端 Python 3.12 自带 exchangelib 5.6.0，本通道**进程内直发**。

> 🔴 **测试误发真信事故（2026-10-06，本特性引入，已修）** —— 加外部副作用时必读。
>
> **现象**：用户收到十几封 `P1 TT Progress Notification`，正文是
> `TT No: TT1 / Site: s / Alarm: 9920`，即**测试夹具值**而非真实单号。
>
> **根因**：本特性给 `run_tt_alarm_whatsapp_alert()` 加了"发信"这个**外部副作用**。
> 而 `tests/test_tt_alarm_render.py` 里两条**早就存在**的用例
> （`test_task_result_surfaces_degradation`、`test_task_result_reports_due_count`）
> 会调用这个真实函数，它们只桩了 `dispatch` / `wait_for_job_result` /
> `render_message_ex` —— 因为**当时还没有邮件这回事**。于是每跑一次全量回归
> 就真发 2 封，我反复跑了几轮回归，累计十几封。
> 实测证伪：关掉下面的防线后单跑那条用例，`real_send_attempts = 2`。
>
> **这不是"某条用例忘了桩"**，而是**给被测试直接调用的函数新增了外部副作用** ——
> 指望每个写测试的人记得桩新通道，是治标的。故按纵深防御在**入口统一封死**：
>
> | 层 | 位置 | 作用 |
> | --- | --- | --- |
> | 主防线 | `tests/conftest.py` 的 `_block_real_email`（autouse fixture） | 把 `send_mail` 换成"记录但不发"的替身，返回记录列表供断言 |
> | 兜底 | `tt_alarm_mailer.send_mail()` 函数体内 | `"pytest" in sys.modules` 时拒发 |
>
> ⚠️ **兜底闸门必须放在收件人解析之后**。放到函数开头会把「空收件人不发」这条
> 校验也一起短路掉，于是测它的用例即使断言写错也会恒返回 False 而"通过" ——
> **假绿比不过更危险**（这个坑在本次修复过程中真的踩到了，5 条用例先"通过"后暴露）。
> 需要测闸门之后的真实异常逻辑时，用 `tests/test_tt_alarm_mail.py` 的
> `fresh_mailer` fixture（从磁盘再加载一份未打补丁的同源副本，
> 并把 `_get_account` 换成地雷，因此仍然不碰网络）。
>
> **验证真实发信能力请手工跑探针**（`.qoder/rules` 的一次性探针约定），
> 不要在 pytest 里放开。回归锁见 `tests/test_tt_alarm_mail.py::TestNoRealMailFromTests`。

**级别过滤口径**：以**实时查单行**的 `ticket_severity` 为准（镜像兜底）；留空语义见
`tt_alarm_config.py`（级别/告警码留空 = 不过滤）。在跟单的级别若被 eFlow 改掉
（P1→P2），同样停止推送。配置优先级为**环境变量 > 配置文件 > 内置默认**，且在
**模块导入期**解析一次 —— 故页面保存后由 `PUT /api/task-configs/{task_id}` 触发
worker 分组重启才生效（`backend/routers/task_configs.py`）。

**重报语义（2026-10-08 起双档，判定函数 `decide_push()`）**：

1. **首推** —— 单子首次触发（日志表无记录）**立即推**；
2. **重报**（按「自上次发送以来工单有没有更新」分两档，消息头带
   `⚠️ REMINDER #N · open Xh Ym · no update for Zm` 横幅，N = 该单第几次发送）：
   * **无更新**档 —— 距上次成功发送满 `stall_minutes`（默认 **10**）→ 催报
     （一直没人动，勤提醒）；
   * **有更新**档 —— 距上次成功发送满 `resend_minutes`（默认 **30**）→ 重报
     （有人在处理，缓报别打扰）；
3. **不报** —— 未满所在档间隔（冷却中）只刷新跟踪字段；告警清除
   （`alarm_clear_time` 非空，或告警从 realtime_alarm 消失）自然止损；
   更新时间完全不可知时按**无更新档**（较短）节流，**绝不静默停推**。

> 两档差的是**间隔长短**，不是「有更新就不报」：有更新仍旧重报，只是缓到 30 分钟。
> 检测（从 eFlow 实时查单）恒为每 5 分钟一轮，与重报窗口无关。

三个**实测**坑，改这个任务前务必知道（都有单测守着，见
`tests/test_tt_alarm_whatsapp_service.py`）：

| 坑 | 现象 | 正确做法 |
| --- | --- | --- |
| `alarm_code` 形态不一 | 库里 `'99933'`（2159 行）与 `'99933.0'`（16599 行）**并存** | 匹配**必须**在 Python 侧走 `norm_alarm_code()` 归一化后判等；写进 SQL 的 `<> '99933'` 会漏掉 `.0` 那批，`CAST(... AS INTEGER)` 又会在文本告警码上抛错（库里有 `'Ethernet Physical (ETPI)…'` 这类值） |
| `down_site_count` 的 `'0'` 是有效值 | 全表 27254 行为 `'0'`；`site_outage` 是 `'Yes'/'No'` 文本 | 只在 `> 0` 时输出 `N site(s) down`；只有 `site_outage='Yes'` 才算断站。旧写法把 `'0'` 当假值、把 `'No'` 当断站，两条都错 |
| 历史单的告警对象字段为空 | `sub_alarm_*` 在近 30 天单上填充率 >95%，但在**未清除的老单上 100% 为空** | 回退链：`sub_alarm_ne_name → ne_name`、`sub_alarm_name → specific_problem → alarm_description` |

> ⚠️ **「每轮 0 条」是正常结果，不是故障**：触发窗口内「带 TT + P1 + 白名单告警码」
> 的实时告警本来就少（告警升起 → eFlow 建 TT 有时差，power-off 类 99933 告警默认不推），
> 每轮候选为 0 是常态。要扩大推送面，在**页面上**把级别改成 `P1,P2`、放宽触发窗口
> 或把 `99933` 填进告警码白名单即可，**不需要改代码**。

> **发送通道（2026-10-01 起为 Baileys 推送进程，不再依赖浏览器）**：后端把文本作业
> 写进 `whatsapp-kb-bot/data/notify_job.json`，常驻的 `src/notify.js`（Baileys，
> WhatsApp WebSocket 协议，凭据独立于问答 bot）轮询消费，`sendMessage()` 返回的
> **服务端 message id** 就是发送回执。切换理由与两通道对比见
> `backend/services/wa_notify_service.py` 的模块 docstring；通道在线检查、投递前
> 心跳预检也都在该模块。
> 无论何时，**只有推送进程回报的 `sent` 列表里的 `tt_no` 才会被置 `'Y'`** —— 超时或
> 未确认一律写 `'N'` + `last_error`，**绝不写假 `'Y'`**；一条都没确认发出的轮次会
> 通过 `warnings` 走微信/邮件主动喊人（2026-10-01「群内静默数小时」事故的治本项）。
>
> 群组在页面上配置，留空回退测试群 `test123` 并显式告警（见上文）。
>
> `GET /api/whatsapp/tt-alert/log` 可核对发送状态；`GET/POST
> /api/whatsapp/tt-alert/job[/result]` 是旧扩展通道的**自测端点**（P1 文本作业
> 2026-10-01 起已不走扩展）。

**模块拆分**（单文件 500 行上限，故按职责拆开；改哪块去哪个文件）：

| 文件 | 职责 |
| --- | --- |
| `backend/services/tt_alarm_whatsapp_service.py` | 编排与**发送决策** `decide_push()`（任务入口 `run_tt_alarm_whatsapp_alert`） |
| `backend/services/tt_alarm_trigger.py` | **触发扫描**：realtime_alarm 里带 TT 的白名单告警 + 表新鲜度检查 |
| `backend/services/tt_alarm_sources.py` | **单据来源层**：实时查单 / 本地镜像兜底 / 三层合并 |
| `backend/services/tt_alarm_config.py` | 配置读取、归一化、「留空」语义 |
| `backend/services/tt_alarm_message.py` | 消息渲染（纯函数，**降级模板**：头部 7 行 + 重报横幅） |
| `backend/services/tt_alarm_render.py` | **主渲染路径**：子进程调 kb-bot 分析引擎出完整消息 |
| `backend/services/tt_alarm_store.py` | 日志表建表、幂等补列（含邮件幂等列）与读写 |
| `backend/services/tt_alarm_mailer.py` | **邮件发送通道**（Orange EWS，进程内直发，失败不抛异常） |
| `backend/services/tt_alarm_mail_body.py` | 邮件正文构造（首次通报 / 结束汇总，纯函数） |
| `backend/services/wa_notify_service.py` | **Baileys 发送通道**（投递/回报/心跳/通道预检） |
| `backend/services/eflow_data_mapper.py` | 实时查单实现（`fetch_tt_live_batch`，base/list 分页遍历） |

## 任务凭据分组对应表

任务失败若报"鉴权失败 / 登录失败 / 未获取到 Cookie"，先到**「设置 → 凭据管理」**
核对下表中对应分组的账号密码（改完最迟 30 秒生效，无需重启）。

| 任务 | 凭据分组 key | 上游系统 |
| --- | --- | --- |
| `ran_ume_daily`、`main_kpi_sync`、`network_kpi_sync`、`ms_sla_sync`、`cells_kpi_sync` | `zte_ume` | RAN UME 网管 |
| `battery_kpi_sync`、`battery_email` | **`battery_ume`** | Battery UME 电池网管 |
| `cm_data_sync` | **`cm_data`** | RAN UME 网管（CM 取数） |
| `ipran_kpi_sync` | `ipran_ume` | iPRAN UME 网管 |
| `ccn_kpi`、`ccn_free_rating_chart_email` | `ccn_ume` | CCN UME 网管 |
| `eflow_sync`、`site_outage_screenshot` 等 eFlow 系 | `eflow` | eFlow 告警系统 |
| `fw_kpi_sync` | `fw_kpi` | FW UMC |
| `mw_ume_kpi_sync`、`mw_ume_kpi_sync_rt` | `mw_ume` | MW UME 微波网管 |
| `ume_in_kpi_sync`、`ume_in_osg_report` | `ume_in` | UME em-portal |
| `vmax_multi_data_sync`、`cxo_dashboard_cache_sync`、`vmax_cxo_daily_sync` | `vmax_cxo` | VMAX CXO 门户 |
| `olib_soc_vmax_report` | `vmax_gbase` | VMAX 数仓 GBase 8a |
| `sp_data_sync`、`sp_report_generate` 等备件系 | `sftp_sp` | SFTP 备件服务器 |
| `liberia_email_*`、`kpi_*` 等邮件类 | `mail_126` / `owa_mail` | 126 邮箱 / Exchange OWA |

> ⚠️ **`battery_ume` 与 `zte_ume` 不是同一台设备**（Battery UME 是 `192.168.170.2:443`，
> RAN UME 是 `10.100.28.27:28001`），账号**不通用**，不要拿 RAN UME 的账号去配 Battery UME。
> 该 UME **未进「一键门户登录」的 direct 反代**，若启用图形验证码需人工登录一次（见下）。

### Battery UME 鉴权失败排查

任务报 `Battery UME 鉴权失败：RSA 登录未成功且无可用 auth_info.json` 时，按序检查：

1. **凭据**：「设置 → 凭据管理 → Battery UME」点"测试连接"，失败则更新账号密码；
2. **图形验证码**：该 UME 若启用了验证码，RSA 纯接口登录必然失败 ——
   到「门户登录」页选 **Battery UME** 人工登录一次；
3. **回退文件**：`backend/services/battary_kpi_fetch/auth_info.json` 由
   `ensure_auth_info()` 用上述凭据调 RSA 接口自动生成（原生成脚本
   `battary_kpi_login.py` 与 playwright 依赖均已不在仓库，故内置此兜底）；
   超过 8 小时视为过期会被忽略并重新生成；
4. **环境变量覆盖**：若设了 `BATT_USERNAME`/`BATT_PASSWORD`，它们**优先于**页面配置，
   页面改了不生效时先查这里。

## 超时、僵尸与自动重试

| 机制 | 参数 | 出处 |
| --- | --- | --- |
| **没有** per-task 超时 | — | 调度器不主动杀长任务，这是设计缺口 |
| 僵尸 running 回收 | `STALE_RUNNING_SECONDS = 30min`，并用 PID 存活核对，每 300s 扫一次 | `worker.py:78,82,302` |
| 陈旧 pending 过期 | `STALE_PENDING_SECONDS = 6h`（漏分组/无 worker 认领时不再永久占住单飞名额），每 300s 扫一次 | `worker.py:_expire_orphan_pending` |
| 失败自动重试 | `AUTO_RETRY_ENABLED=1`、`MAX_ATTEMPTS=2`、`COOLDOWN_MIN=15`、`SCAN_WINDOW_HOURS=24`、`MAX_PER_RUN=3` | `services/auto_retry.py:75-82` |
| 漏跑补投 | `MISS_GRACE_MIN=15`、`MISS_MIN_INTERVAL_MIN=30`（时效窗口内完全没有执行记录才补投） | 同上 |
| 邮件类不参与补投 | 由 EWS 恢复补发机制 `email_recovery` 负责，默认排除 | `task_registry.py:320` |
| 失败通知 | 微信 + 邮件双通道 | `task_runner.py:52-62` |
| 漏跑/停摆通知 | 每小时巡检后按 `kind:task_id` 翻转去重推送（24h 重提） | `services/task_health_alert.py` |
| 保留期 | 队列与执行日志保留 **3 天** | `task_runner.py:764`、`worker.py:240` |

重试的判定不是"失败就重跑"，而是**先看数据缺口是否已被后续成功执行补上**；超过 24h 硬上限直接放弃（`task_registry.py:320`）。

## 看门狗与自愈

- `backend_watchdog.py`：托管 uvicorn，端口探活，启动宽限 `STARTUP_GRACE=60s`，崩溃退避 `min(30, 2^n)`，**连崩 10 次降级为 `SLOW_RETRY_INTERVAL=300s` 慢速重试、不再退出**（`:52-57`、`_enter_slow_retry()` `:212-240`；2026-10-06 改，原为"连崩 10 次永久退出"，事故经过见 `13-operations.md` 的「后端静默停摆」）。
- `worker_watchdog.py`：同参数托管 5 组 worker（u/n/v/m/c，:36-39）。子进程存活 <`CRASH_THRESHOLD=10s` 视为异常崩溃。⚠ **连崩 10 次仍是"摘除不再拉起"**（`:560-562`），与 backend 的降级语义不同。
- 心跳：`log/heartbeat_*.json`，15s 一次。启动脚本判定"心跳超过 3 分钟未更新即 hung"并强杀重拉（`start_hidden.ps1:63,154-158`）。

## 加一个任务的最小步骤

1. `backend/task_registry.py` 的 `TASK_SPECS` 追加一条 `dict(task_id, name, name_en, description, description_en, loader|func, default_cron, category)`；
2. **`worker_watchdog.py` 的 `GROUP_TASK_MAP` 选定归属组**（漏了就会 pending 卡死；新建组则两处同步，见上方分组章）；
3. 业务函数放 `backend/services/`，抛异常即算失败，不要自己吞异常；
4. 重启后端（`stop.bat` → `start.bat`）让注册表重载；只改分组清单无需重启后端，`python restart_workers.py --mode watchdog --force`（**需管理员权限**，否则 watchdog 进程杀不掉而静默失败，旧组清单会一直在内存里生效）；
5. 在任务管理页手动"执行"一次验证链路，再更新本页任务清单表格与前端帮助（`frontend/src/pages/helpTaskDocs.ts`，改完跑 `npm run docs`）。
