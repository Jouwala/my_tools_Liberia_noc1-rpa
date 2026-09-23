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
| `u` | 10 | RAN UME 单账号会话，必须串行（并发会被踢会话） | `ran_ume_daily`, `main_kpi_sync`, `cell_availability_sync`, `network_kpi_sync`, `packet_loss_sync`, `packet_loss_email`, `battery_kpi_sync`, `ipran_kpi_sync`, `cm_data_sync`, `cells_kpi_sync` |
| `n` | 16 | 网管/eFlow API/远程系统：彼此独立但保守同组 | `eflow_sync`, `eflow_sync_full`, `eflow_active_alarm`, `eflow_history_alarm`, `eflow_tt_rules_check`, `ms_sla_full`, `cnn_kpi_sync`, `fw_kpi_sync`, `sp_data_sync`, `mw_ume_kpi_sync`, `mw_ume_kpi_sync_rt`, `sp_online_sync`, `sp_material_sync`, `eflow_alarm_rules_collect`, `eflow_push_rules_collect`, `ume_in_kpi_sync` |
| `v` | 3 | VMAX 门户（本机 8790 单会话代理）：三个任务共用同一个 VMAX 会话，必须彼此串行；2026-09-18 从 `n` 组拆出（原先排在 `sp_data_sync` 这类 1.5~2h 长任务后面，小时级采集滞后一个多小时） | `cxo_dashboard_cache_sync`, `vmax_cxo_daily_sync`, `vmax_multi_data_sync` |
| `m` | 29 | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 + VMAX 数仓 GBase 直连取数 | `site_outage_screenshot`, `whatsapp_send`, `whatsapp_send_ext`, `liberia_email_1h`, `liberia_email_8h`, `kpi_ms_contract`, `kpi_ms_wo_sla`, `kpi_sp_spareparts`, `kpi_sp_consumables`, `kpi_ran_availability`, `email_recovery`, `ipran_m6k_chart_email`, `ccn_free_rating_chart_email`, `battery_email`, `mailbox_cleanup`, `incident_overview_sync`, `auto_retry_failed`, `db_freshness_check`, `sp_report_generate`, `sp_email_details`, `sp_online_report_generate`, `sp_online_report_send`, `sp_whatsapp_report`, `sp_material_report`, `finebi_report_sync`, `pg_to_sqlite_sync`, `log_cleanup`, `olib_soc_kpi_daily_sync`, `olib_soc_vmax_report` |
| `c` | 2 | CN EMS 独立会话，两个任务共享 `_pmcache`/`daily_raw.json`，同组保证互斥 | `ems_kpi_cache_sync`, `ems_kpi_daily` |

`m` 组末尾几条有注释记录：`finebi_report_sync`/`pg_to_sqlite_sync`（2026-08-25）、`whatsapp_send_ext`（08-31）、`sp_email_details`（09-01）、`cells_kpi_sync`/`sp_material_sync`（09-09~11）在启用分组模式后都因**未归入任何组而无人认领，队列 pending 卡死断档**才补进来（`worker_watchdog.py` 内的补录注释）。

> **新增任务必须同时登记进 `GROUP_TASK_MAP`；新增/调整「组」必须同步三处**：`worker_watchdog.py::GROUP_TASK_MAP` 的键、`start_hidden.ps1` 的 `$env:MY_APP_WORKER_GROUPS`、`restart_workers.py` 的 `ALL_GROUPS`。只加分组表不改启动脚本 = 该组 worker 从不被拉起，症状与漏登记完全一样。
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
| `mw_ume_kpi_sync_rt` | MW UME KPI 实时同步（15 分钟粒度） | `*/15 * * * *` | n |
| `ems_kpi_cache_sync` | CN EMS KPI 缓存同步 | `*/15 * * * *` | c |
| `ems_kpi_daily` | CN EMS KPI 日粒度CSV | `20 0 * * *` | c |
| `vmax_multi_data_sync` | VMAX 多报表指标采集 | `45 * * * *` | v |
| `olib_soc_vmax_report` | OLIB SOC VMAX 例行报表 | `30 7 1 * *` | m |
| `olib_soc_kpi_daily_sync` | OLIB SOC 看板 KPI 增量 | `20 6 * * *` | m |
| `whatsapp_send_ext` | WhatsApp 消息发送（扩展） | `0 3 * * *` | m |
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
2. **`worker_watchdog.py` 的 `GROUP_TASK_MAP` 选定归属组**（漏了就会 pending 卡死；新建组则三处同步，见上方分组章）；
3. 业务函数放 `backend/services/`，抛异常即算失败，不要自己吞异常；
4. 重启后端（`stop.bat` → `start.bat`）让注册表重载；只改分组清单无需重启后端，`python restart_workers.py --mode watchdog --force`（**需管理员权限**，否则 watchdog 进程杀不掉而静默失败，旧组清单会一直在内存里生效）；
5. 在任务管理页手动"执行"一次验证链路，再更新本页任务清单表格与前端帮助（`frontend/src/pages/helpTaskDocs.ts`，改完跑 `npm run docs`）。
