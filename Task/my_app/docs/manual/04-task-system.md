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
| `u` | 11 | RAN UME 单账号会话，必须串行（并发会被踢会话） | `ran_ume_daily`, `main_kpi_sync`, `cell_availability_sync`, `network_kpi_sync`, `packet_loss_sync`, `packet_loss_email`, `battery_kpi_sync`, `ipran_kpi_sync`, `cm_data_sync`, `cells_kpi_sync`, `avail_recon_sync` |
| `n` | 14 | eFlow API / config-center 同源会话（2026-09-27 由 17 项收窄，VMAX→`v`、SFTP→`s`、MW UME→`w` 已分头拆出） | `eflow_sync`, `eflow_sync_full`, `eflow_active_alarm`, `eflow_history_alarm`, `eflow_tt_rules_check`, `ms_sla_full`, `cnn_kpi_sync`, `fw_kpi_sync`, `sp_online_sync`, `sp_material_sync`, `eflow_alarm_rules_collect`, `eflow_push_rules_collect`, `ume_in_kpi_sync`, `ume_in_osg_report` |
| `s` | 1 | SP 备件 SFTP（独立 SFTP 服务器 + UNC 镜像库）。2026-09-27 从 `n` 拆出：它是 `n` 组最大单体负载（实测 347min/天）且是已知挂死源（SFTP channel 读挂死 5.5h 曾拖停整组） | `sp_data_sync` |
| `w` | 2 | MW UME 微波网管（凭证分组 `mw_ume`），独立会话。2026-09-27 从 `n` 拆出：`mw_ume_kpi_sync_rt` 为 `*/15` 高频任务，此前每次排在 `sp_data_sync` 后，实测队列等待 964s（全场最久） | `mw_ume_kpi_sync`, `mw_ume_kpi_sync_rt` |
| `v` | 3 | VMAX 门户（本机 8790 单会话代理）：三个任务共用同一个 VMAX 会话，必须彼此串行；2026-09-18 从 `n` 组拆出（原先排在 `sp_data_sync` 这类 1.5~2h 长任务后面，小时级采集滞后一个多小时） | `cxo_dashboard_cache_sync`, `vmax_cxo_daily_sync`, `vmax_multi_data_sync` |
| `m` | 33 | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 + VMAX 数仓 GBase 直连取数 | `site_outage_screenshot`, `whatsapp_send`, `whatsapp_send_ext`, `tt_alarm_whatsapp_alert`, `liberia_email_1h`, `liberia_email_8h`, `kpi_ms_contract`, `kpi_ms_wo_sla`, `kpi_sp_spareparts`, `kpi_sp_consumables`, `kpi_ran_availability`, `email_recovery`, `ipran_m6k_chart_email`, `ccn_free_rating_chart_email`, `battery_email`, `mailbox_cleanup`, `incident_overview_sync`, `auto_retry_failed`, `db_freshness_check`, `sp_report_generate`, `sp_email_details`, `sp_online_report_generate`, `sp_online_report_send`, `sp_whatsapp_report`, `sp_material_report`, `finebi_report_sync`, `pg_to_sqlite_sync`, `log_cleanup`, `tmp_cleanup`, `mttr_tt_sync`, `progress_sync`, `olib_soc_kpi_daily_sync`, `olib_soc_vmax_report` |
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

## 全量任务清单（默认 cron）

下表与 `GROUP_TASK_MAP` 逐一对应（task_id 覆盖与组名由 `tests/test_worker_group_coverage.py` 校验，其中组名校验针对前端帮助；本表本身无守卫，新增任务后请手工补行）。

| task_id | 名称 | 默认 cron | 组 |
| --- | --- | --- | --- |
| `eflow_sync` | eFlow 数据同步 | `22 * * * *` | n |
| `eflow_sync_full` | eFlow 每日全量同步 | `0 1 * * *` | n |
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
| `incident_overview_sync` | Incident Overview 数据同步 | `0 * * * *` | m |
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
| `tt_alarm_whatsapp_alert` | eFlow P1 告警 WhatsApp 推送（**可在「任务配置」页调级别/告警码/时间窗/群组**） | `*/15 * * * *` | m |
| `cells_kpi_sync` | RAN Cells KPI 同步 | `50 4 * * *` | u |
| `sp_email_details` | SP 备件明细报表邮件 | `0 7 * * *` | m |
| `sp_material_report` | SP 物料库存与消耗报表邮件 | `33 7 * * *` | m |
| `sp_online_report_generate` | SP 在线未关闭单报表生成 | `0 6 * * *` | m |
| `sp_online_report_send` | SP 在线未关闭单报表发送 | `20 6 * * *` | m |
| `sp_whatsapp_report` | Comsumables&SpareParts Report Whatsapp | `15 7 * * *` | m |
| `sp_online_sync` | SP Online 工单同步 | `35 * * * *` | n |
| `sp_material_sync` | SP 物料主数据同步 | `55 4 * * *` | n |
| `ume_in_kpi_sync` | 客户业务 KPI 同步 | `45 5 * * *` | n |
| `ume_in_osg_report` | 客户业务 KPI + OSG 周报邮件 | `30 6 * * *` | n |
| `eflow_alarm_rules_collect` | eFlow 告警规则收集 | `59 23 */3 * *` | n |
| `eflow_push_rules_collect` | eFlow 推单规则收集 | `59 23 */3 * *` | n |
| `log_cleanup` | 日志文件清理 | `17 3 * * *` | m |
| `cxo_dashboard_cache_sync` | CXO看板数据缓存同步 | `*/10 * * * *` | v |
| `vmax_cxo_daily_sync` | VMAX CXO天粒度日值归档 | `15 * * * *` | v |
| `avail_recon_sync` | 可用率核对宽表重建 | `10 6 * * *` | u |
| `tmp_cleanup` | TMP 目录清理 | `47 3 * * *` | m |
| `mttr_tt_sync` | MTTR/TT 宽表重建 | `40 7 * * *` | m |
| `progress_sync` | Progress 宽表重建 | `50 7 * * *` | m |

### `sp_data_sync` 的两个已知缺陷（2026-09-27 实测定位）

排查「`n` 组为什么总是堵」时定位到两个独立问题。**缺陷一的"静默"部分已修复，根因待远端处理；
缺陷二已通过拆组 + 分段计时处理。**

**缺陷一：FineBI 镜像库自 2026-09-24 起 100% 失败。**

`sp_data_sync` 的 `result_json` 里有 `mirror_success: false` 与 `mirror_errors`（5 张表全失败），
`detail` 统一是 `database is locked`（`get_sp_table.py` 的 `_connect_mirror`，
`MIRROR_BUSY_TIMEOUT_MS=30000`、`MIRROR_RETRIES=2`）。实测 14 天内 **76 次执行、75 次镜像失败**，
最早一次是 `2026-09-24T12:10`。

根因在**远端主机**，不在本任务：镜像目标
`\\DESKTOP-D4GF62\...\WareHouseDashBoard\inventory.db` 处于 **WAL 模式且被远端活进程长期持有**。
2026-09-27 逐项排除后的确切结论：

| 探测 | 结果 | 含义 |
| --- | --- | --- |
| 裸 `open()` 读主库 | **成功**（`SQLite format 3`） | 文件本身完好、共享可达 |
| 复制主库到本机再打开 | **成功**，`journal_mode=wal`，5 张表齐全 | **数据库没坏** |
| 删除远端 `-shm` / `-wal` | `WinError 33/32` 拒绝 | 远端有活进程正持锁 |
| 在同一 SMB 目录**新建** sqlite 库 | **成功** | SMB 本身能跑 SQLite |
| 打开**已存在的 WAL 库** | 失败，`database is locked`（`timeout`=1/30 均失败） | WAL 的共享内存锁在 SMB 上无法建立 |

结论：**SQLite-WAL over SMB 的架构限制**，不是锁竞争。
`busy_timeout` 调多大都没用 —— 每次尝试都必然失败。
真正修复需在**远端侧**改（让写库进程自己在本地落库后导出 `inventory.db`，
或改为提供接口/定时快照），本仓库无法单方面解决。

> **已做的代码侧改进（2026-09-27）**：
> 1. **不再静默**：镜像失败会追加进 `result["warnings"]`，并由
>    `task_runner.py` 在 `success=True` 时也消费 warnings 发出**降级告警**
>    （此前告警只在 `success=False` 触发，所以看板停更半个月而监控全绿）。
> 2. **诊断可执行**：新增 `_diagnose_mirror_failure()`，主动探测 `-shm` 可开性，
>    把 `database is locked` 翻译成"这是 WAL-over-SMB 架构限制，调超时无效"，
>    避免下一个人继续在超时参数上打转。
> 3. 守卫用例 `tests/test_engineering_guards.py::test_mirror_failure_is_surfaced_as_warning`
>    钉住上述两条，防止退回静默。

> **排查 FineBI 仓库看板数据不动时**：不要只看任务成功状态 —— 看
> `result_json` 的 `mirror_success`，或看是否收到过 `[降级]` 通知。

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

### `olib_soc_kpi_daily_sync` 的两类自愈（2026-09-24 加固）

该任务给 VMAX 90 天经营看板（`?page=vmaxCxoDashboard_90Days`）供数，每天 06:20 只补
`daily_kpi` 里缺的天。它的「缺口」判定有**两类**，缺一不可：

| 类型 | 判定函数 | 背景 |
| --- | --- | --- |
| 整天没有行 | `olib_soc_kpi_store.gap_days()` | 任务被跳过 / 数仓分区晚到 |
| **有行但关键指标为 NULL** | `olib_soc_kpi_store.incomplete_days()` | 单个块临时取数失败，仍写入一行，只是该块那列为 NULL |

第二类是 2026-09-24 的线上事故：`blocks_ok` 从 7 掉到 6 却**不报错**，
`gap_days` 也不认为缺天，于是 `active_user` 在 2026-09-18~23 **连丢 6 天**且永久残留
（看板「Active Users」停在 17 号）。判定列见 `olib_soc_kpi_store.REQUIRED_COLUMNS`
（`traffic_tb` / `active_user` / `video_tb`）；取数幂等，重取一次即自愈。

> 排查同类问题的第一步：`SELECT day, blocks_ok FROM daily_kpi ORDER BY day DESC`，
> **`blocks_ok` 小于块总数（看板为 7）的那天就是残缺日**。

### `tt_alarm_whatsapp_alert` 的口径与三个实测坑（2026-09-28）

每 15 分钟把「近 3 小时内 + 告警未清除 + 告警码在白名单内 + `ticket_severity` 命中级别」
的 TT 单渲染成文本推送到 WhatsApp，发送状态落 `eflow_tt_whatsapp_alert_log`。

**这张单的四个口径都可在页面上配置** —— 「设置 → 任务配置 → `eFlow P1 Alarm WhatsApp Push`」
（配置文件 `backend/services/tt_alert_whatsapp_config.json`，注册在
`backend/services/task_configs_registry.py`，读写实现见 `backend/services/task_config_files.py`）：

| 配置项 | 页面标签 | 留空 / 默认的含义 |
| --- | --- | --- |
| `window_minutes` | 时间窗（分钟） | 默认 180（=「近 3 小时」） |
| `resend_minutes` | 重推间隔（分钟） | 默认 20 |
| `severities` | 级别 | 默认 `P1`；**留空 = 不限级别**（P1/P2/…全推） |
| `alarm_codes` | 告警码 | 默认不含 `99933`；**这是白名单**，留空 = 不限告警码 |
| `groups` | WhatsApp 群组 | 默认 `test123`；**留空会回退到测试群并在结果里告警**（见下） |

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

**口径来源**：「告警未清除」= `alarm_clear_time` 为空。实测（2026-09-28，全表 36348 行）
该列为空的形态**只有 NULL 一种**（74 行；空串 / `'None'` / `'nan'` 均为 0 行），
故当前数据上等价于 `alarm_clear_time IS NULL`；代码仍保留空串防御分支，与
`backend/routers/portal_qc.py` 的 `_TT_UNCLEARED` 逐字一致 —— 两处必须同源，
不要各写一份。

**窗口锚点是 `alarm_occur_time`（告警发生时间）**，不是 `created_time` 也不是
`last_modified_time`。三者选错**不会报错**，只会静默漏单/多单，故用
`test_window_anchor_is_alarm_occur_time_not_created_or_modified`（三张时间字段互相
矛盾的单）锁死。配置优先级为**环境变量 > 配置文件 > 内置默认**，且在**模块导入期**
解析一次 —— 故页面保存后由 `PUT /api/task-configs/{task_id}` 触发 worker 分组重启才生效
（`backend/routers/task_configs.py`）。

**重推语义**：同一单距上次**成功发送**满 `resend_minutes`（默认 20）分钟后继续推，
与单子是否更新无关（工单没更新也照推）。15 分钟调度 × 20 分钟节流
⇒ 实际约每 30 分钟重推一次。判定函数 `tt_alarm_whatsapp_service.is_due()`。

三个**实测**坑，改这个任务前务必知道（都有单测守着，见
`tests/test_tt_alarm_whatsapp_service.py`）：

| 坑 | 现象 | 正确做法 |
| --- | --- | --- |
| `alarm_code` 形态不一 | 库里 `'99933'`（2159 行）与 `'99933.0'`（16599 行）**并存** | 匹配**必须**在 Python 侧走 `norm_alarm_code()` 归一化后判等；写进 SQL 的 `<> '99933'` 会漏掉 `.0` 那批，`CAST(... AS INTEGER)` 又会在文本告警码上抛错（库里有 `'Ethernet Physical (ETPI)…'` 这类值） |
| `down_site_count` 的 `'0'` 是有效值 | 全表 27254 行为 `'0'`；`site_outage` 是 `'Yes'/'No'` 文本 | 只在 `> 0` 时输出 `N site(s) down`；只有 `site_outage='Yes'` 才算断站。旧写法把 `'0'` 当假值、把 `'No'` 当断站，两条都错 |
| 历史单的告警对象字段为空 | `sub_alarm_*` 在近 30 天单上填充率 >95%，但在**未清除的老单上 100% 为空** | 回退链：`sub_alarm_ne_name → ne_name`、`sub_alarm_name → specific_problem → alarm_description` |

> ⚠️ **「每轮 0 条」是正常结果，不是故障**：`eflow_tt` 里「未清除 + P1」的单绝大多数是
> 历史遗留（2026-09-28 实测 16 单中最新一单 `alarm_occur_time` 停在 2026-06-24），
> 近 7 天只有 2 张 P1 单且都已清除。要扩大推送面，在**页面上**把级别改成 `P1,P2`
> 或放宽时间窗即可，**不需要改代码**。

> **发送通道与当前边界**：后端只投递作业（`data/tt_alert_job.json`），由 Chrome 扩展在
> 已登录的 WhatsApp Web 里发送并回报。**扩展侧的纯文本发送能力尚未实现**（现有扩展
> 只发图片）；在此之前作业会被投递但无人认领，`send_status` 停在 `'N'` 并记 `last_error`
> —— 这是刻意设计：**宁可状态如实为未发送，也不写假 `'Y'`**。
> 群组在页面上配置，留空回退测试群 `test123` 并显式告警（见上文）。
> 对接端点：`GET /api/whatsapp/tt-alert/job`（认领）、`POST /api/whatsapp/tt-alert/job/result`（回报）、
> `GET /api/whatsapp/tt-alert/log`（核对发送状态）。

**模块拆分**（单文件 500 行上限，故按职责拆开；改哪块去哪个文件）：

| 文件 | 职责 |
| --- | --- |
| `backend/services/tt_alarm_whatsapp_service.py` | 取数、节流、编排（任务入口 `run_tt_alarm_whatsapp_alert`） |
| `backend/services/tt_alarm_config.py` | 配置读取、归一化、「留空」语义 |
| `backend/services/tt_alarm_message.py` | 消息渲染（纯函数） |
| `backend/services/tt_alarm_job.py` | 投递作业状态机（`pending → running → done/failed`） |
| `backend/services/tt_alarm_store.py` | 日志表建表与读写 |

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

- `backend_watchdog.py`：托管 uvicorn，端口探活，启动宽限 `STARTUP_GRACE=60s`，崩溃退避 `min(30, 2^n)`，**连崩 10 次放弃并告警**（:38-44）。
- `worker_watchdog.py`：同参数托管 5 组 worker（u/n/v/m/c，:36-39）。子进程存活 <`CRASH_THRESHOLD=10s` 视为异常崩溃。
- 心跳：`log/heartbeat_*.json`，15s 一次。启动脚本判定"心跳超过 3 分钟未更新即 hung"并强杀重拉（`start_hidden.ps1:63,154-158`）。

## 加一个任务的最小步骤

1. `backend/task_registry.py` 的 `TASK_SPECS` 追加一条 `dict(task_id, name, name_en, description, description_en, loader|func, default_cron, category)`；
2. **`worker_watchdog.py` 的 `GROUP_TASK_MAP` 选定归属组**（漏了就会 pending 卡死；新建组则两处同步，见上方分组章）；
3. 业务函数放 `backend/services/`，抛异常即算失败，不要自己吞异常；
4. 重启后端（`stop.bat` → `start.bat`）让注册表重载；只改分组清单无需重启后端，`python restart_workers.py --mode watchdog --force`（**需管理员权限**，否则 watchdog 进程杀不掉而静默失败，旧组清单会一直在内存里生效）；
5. 在任务管理页手动"执行"一次验证链路，再更新本页任务清单表格与前端帮助（`frontend/src/pages/helpTaskDocs.ts`，改完跑 `npm run docs`）。
