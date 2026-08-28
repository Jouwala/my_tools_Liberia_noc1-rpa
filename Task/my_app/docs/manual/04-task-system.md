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
| `u` | 9 | RAN UME 单账号会话，必须串行（并发会被踢会话） | `ran_ume_daily`, `main_kpi_sync`, `cell_availability_sync`, `network_kpi_sync`, `packet_loss_sync`, `packet_loss_email`, `battery_kpi_sync`, `ipran_kpi_sync`, `cm_data_sync` |
| `n` | 10 | 网管/eFlow API/远程系统，彼此独立但保守同组 | `eflow_sync`, `eflow_sync_full`, `eflow_active_alarm`, `eflow_history_alarm`, `eflow_tt_rules_check`, `ms_sla_full`, `cnn_kpi_sync`, `fw_kpi_sync`, `sp_data_sync`, `mw_ume_kpi_sync` |
| `m` | 20 | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 | `site_outage_screenshot`, `whatsapp_send`, `liberia_email_1h`, `liberia_email_8h`, `kpi_ms_contract`, `kpi_ms_wo_sla`, `kpi_sp_spareparts`, `kpi_sp_consumables`, `kpi_ran_availability`, `email_recovery`, `ipran_m6k_chart_email`, `ccn_free_rating_chart_email`, `battery_email`, `mailbox_cleanup`, `incident_overview_sync`, `auto_retry_failed`, `db_freshness_check`, `sp_report_generate`, `finebi_report_sync`, `pg_to_sqlite_sync` |
| `c` | 2 | CN EMS 独立会话，两个任务共享 `_pmcache`/`daily_raw.json`，同组保证互斥 | `ems_kpi_cache_sync`, `ems_kpi_daily` |

`m` 组末尾两条有注释记录：`finebi_report_sync`/`pg_to_sqlite_sync` 在 2026-08-25 启用分组模式后因**未归入任何组而无人认领，队列 pending 卡死断档**，才补进来的（`worker_watchdog.py:58-60`）。

> **新增任务必须同时登记进 `GROUP_TASK_MAP`。** 只写进 `TASK_SPECS` 而不分组 = 任务入队后永远 pending。这是本项目已发生过的事故模式。

## 全量任务清单（默认 cron）

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
| `sp_data_sync` | SP 备件数据同步 | `0 7 * * *` | n |
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
| `mw_ume_kpi_sync` | MW UME KPI 同步 | `15 5 * * *` | n |
| `ems_kpi_cache_sync` | CN EMS KPI 缓存同步 | `*/15 * * * *` | c |
| `ems_kpi_daily` | CN EMS KPI 日粒度CSV | `20 0 * * *` | c |

## 超时、僵尸与自动重试

| 机制 | 参数 | 出处 |
| --- | --- | --- |
| **没有** per-task 超时 | — | 调度器不主动杀长任务，这是设计缺口 |
| 僵尸 running 回收 | `STALE_RUNNING_SECONDS = 30min`，并用 PID 存活核对，每 300s 扫一次 | `worker.py:78,82,302` |
| 失败自动重试 | `AUTO_RETRY_ENABLED=1`、`MAX_ATTEMPTS=2`、`COOLDOWN_MIN=15`、`SCAN_WINDOW_HOURS=24`、`MAX_PER_RUN=3` | `services/auto_retry.py:75-82` |
| 漏跑补投 | `MISS_GRACE_MIN=15`、`MISS_MIN_INTERVAL_MIN=30`（时效窗口内完全没有执行记录才补投） | 同上 |
| 邮件类不参与补投 | 由 EWS 恢复补发机制 `email_recovery` 负责，默认排除 | `task_registry.py:320` |
| 失败通知 | 微信 + 邮件双通道 | `task_runner.py:52-62` |
| 保留期 | 队列与执行日志保留 **3 天** | `task_runner.py:764`、`worker.py:240` |

重试的判定不是"失败就重跑"，而是**先看数据缺口是否已被后续成功执行补上**；超过 24h 硬上限直接放弃（`task_registry.py:320`）。

## 看门狗与自愈

- `backend_watchdog.py`：托管 uvicorn，端口探活，启动宽限 `STARTUP_GRACE=60s`，崩溃退避 `min(30, 2^n)`，**连崩 10 次放弃并告警**（:38-44）。
- `worker_watchdog.py`：同参数托管 4 组 worker（:36-39）。子进程存活 <`CRASH_THRESHOLD=10s` 视为异常崩溃。
- 心跳：`log/heartbeat_*.json`，15s 一次。启动脚本判定"心跳超过 3 分钟未更新即 hung"并强杀重拉（`start_hidden.ps1:63,154-158`）。

## 加一个任务的最小步骤

1. `backend/task_registry.py` 的 `TASK_SPECS` 追加一条 `dict(task_id, name, name_en, description, description_en, loader|func, default_cron, category)`；
2. **`worker_watchdog.py` 的 `GROUP_TASK_MAP` 选定归属组**（漏了就会 pending 卡死）；
3. 业务函数放 `backend/services/`，抛异常即算失败，不要自己吞异常；
4. 重启后端（`stop.bat` → `start.bat`）让注册表重载；
5. 在任务管理页手动"执行"一次验证链路，再更新本页任务清单表格。
