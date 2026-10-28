# my_app 使用帮助

> 面向使用者的平台功能与操作指南。本文件由「使用帮助」页面同源生成（frontend/src/helpMarkdown.ts），内容依据 docs/manual/ 各章与 backend/task_registry.py 整理。生成日期：2026-10-27。

> 站内入口：侧边栏「使用帮助」，或直链 `http://<host>/myapp/?page=help`。

---

## 目录

- [1. 平台简介](#1-平台简介)
- [2. 通用操作](#2-通用操作)
- [3. 任务管理详解（78 个任务）](#3-任务管理详解)
- [4. 页面指南](#4-页面指南)
- [5. 运维与排障](#5-运维与排障)
- [6. 常见问题](#6-常见问题)

## 1. 平台简介

面向网络运维的自动化数据平台：定时从 eFlow、各制式网管（RAN/iPRAN/CNN/MW UME、CN EMS）、FineBI、FTP、邮箱等上游系统采集与同步数据，统一入库后以看板、表格与报告的形式呈现。

典型链路：定时任务采集 → 数据入库（PostgreSQL 主库 + 各任务独立 SQLite）→ 看板展示 / Excel 报表与邮件、WhatsApp 分发 → 告警与工单闭环分析。

服务场景是「每天要看板、要发报表、报表不能漏」的 NOC 运维：41+ 个定时任务、20+ 个功能页、失败自动重试与漏跑补投、进程级看门狗自愈。

**它做什么**

- 41+ 个定时任务驱动数据采集与报表投递（backend/task_registry.py 统一注册）
- 所有功能页在一个 SPA 内，中英文可切换，看板指标可点击下钻
- 通用表能力：任意表浏览、字段画像、Excel/CSV 导入导出、视图模板
- 自动补漏：失败任务自动重试、漏跑任务自动补投；进程自愈：看门狗托管 + 心跳强杀重拉

**它不做什么（能力边界）**

- 没有多用户体系：没有注册/角色/审计，任何能访问入口的人都拥有完整操作能力
- 不对外提供 HTTPS：TLS 需由前置 nginx 终结；上游证书校验默认关闭
- 不做数据编辑：数据「抓进来只读」，页面无业务写回上游的能力（仅凭据/收件人/排程等配置可写）
- 不是高可用服务：单实例锁（db/instance.lock）保证同机只跑一份，无集群与故障转移

---

## 2. 通用操作

| 操作 | 说明 |
| --- | --- |
| 侧边栏导航 | 侧边栏默认收起，点左上角 ☰ 按钮展开/收起；移动端以抽屉浮层从顶栏下方滑出。 |
| 新标签页打开 | 在左侧菜单项上右键 → 「在新标签页打开」，适合大屏/多屏分屏值守。 |
| 直链访问 | 任何页面都可用 ?page=<key> 直接打开，例如 /myapp/?page=battery，可收藏、可分享。 |
| 自动刷新 | 顶栏下拉选择间隔（默认 5 分钟，可选 0/30s~30min）；正在输入、弹窗打开或标签页在后台时本轮自动跳过，不打断操作。仅「看板 / 展示页」参与自动刷新，配置与操作页（如系统设置、上传、表浏览、IP 探测）不刷新、选择器为禁用态；看板页全屏挂机时即使选「关闭」也会按本页默认间隔兜底刷新。 |
| 主题与语言 | 右上角切换深/浅色主题与中/英文界面，偏好自动保存在本机（localStorage）。 |
| 数据新鲜度 | 部分页面页头显示「最近同步」时间。看板数据由定时任务写入，各任务频率不同（实时告警每分钟、微波拓扑每天 05:15、丢包每天 06:30 等），完整清单见「任务管理详解」。 |

---

## 3. 任务管理详解

### 3.1 一条任务的一生

**① 调度到点** APScheduler 在后端进程内按 cron 到点触发（backend/task_runner.py）。默认 cron 写在 task_registry.py 的 TASK_SPECS，实际排程读 task_schedule_config 表——所以在页面改排程立即生效且重启不丢。

**② 入队** enqueue_task() 向主库 task_queue 写一行待执行记录。

**③ worker 认领** 对应分组的 worker 进程用 UPDATE…RETURNING 原子认领该行（backend/worker.py）。MY_APP_TASK_QUEUE=1 未设置时退化为调度器进程内线程执行。

**④ 执行** run_task() 调用真正的 service 函数（task_registry.py 里每条任务声明 func 或 loader=("模块路径","函数名") 懒加载）。业务函数抛异常即记为失败——不要在业务代码里吞异常。

**⑤ 回写终态** _finish() 回写任务终态并写 task_execution_log 执行历史（队列与执行日志保留 3 天）。失败时经微信 + 邮件双通道通知。

### 3.2 Worker 分组：组内串行、组间并行

| 组 | 约束原因 |
| --- | --- |
| **u** | RAN UME 单账号会话，组内必须串行（并发会被踢会话） |
| **n** | 网管 / eFlow API / 远程系统：彼此独立但保守同组 |
| **v** | VMAX 门户（本机 8790 单会话代理）：三个任务共用同一会话必须串行；2026-09-18 从 n 组拆出，不再被 1.5~2h 长任务堵住 |
| **m** | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 |
| **c** | CN EMS 独立会话：缓存同步与日聚合共享 _pmcache，同组保证互斥 |
| **x** | 实时告警专属组：2026-10-15 从 n 组拆出，独占一条道不再排在 eflow_sync 等长任务后面（此前最差排队 854s） |
| **g** | RAN Greenplum 取数组：2026-10-19 新增。上游是 control1 两跳 SSH，与 eFlow/UME/VMAX GBase 无会话交集。独立成组的理由是故障域而非时长（实测单轮 72.6s）—— 这条链路每一跳都可能挂死在网络层，与当年 s 组 sp_data_sync 挂死 5.5h 拖停整组同型，而 m 组跑着每分钟的告警 WhatsApp 推送 |

> ⚠️ **新增任务必须同时登记进 `worker_watchdog.py` 的 `GROUP_TASK_MAP`** —— 只写 `TASK_SPECS` 不分组 = 任务入队后永远 pending。这是本项目已发生过四次的事故模式（finebi_report_sync / whatsapp_send_ext / sp_email_details / 2026-09-18 的 olib_soc 与 vmax_multi_data_sync）。

### 3.3 全量任务清单（78 个）

| 任务 | task_id | 默认 cron | 组 | 工作流脚本 |
| --- | --- | --- | --- | --- |
| eFlow 数据同步 | `eflow_sync` | `22 * * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")` |
| eFlow 每日全量同步 | `eflow_sync_full` | `0 1 * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")` |
| RAN UME 日报 | `ran_ume_daily` | `0 2 * * *` | u | `services/ran_ume_service.py → run_ran_ume_full_task` |
| Site Outage 截图 | `site_outage_screenshot` | `0 1 * * *` | m | `services/site_outage_service.py → run_site_outage_screenshot` |
| WhatsApp 消息发送 | `whatsapp_send` | `0 3 * * *` | m | `services/whatsapp_service.py → run_whatsapp_send` |
| WhatsApp 消息发送（扩展） | `whatsapp_send_ext` | `0 3 * * *` | m | `services/whatsapp_ext_service.py → run_whatsapp_send_ext` |
| WhatsApp 消息发送（Baileys） | `whatsapp_send_baileys` | `0 4 * * *` | m | `services/whatsapp_send_baileys_service.py → run_whatsapp_send_baileys` |
| eFlow P1 告警 WhatsApp 推送 | `tt_alarm_whatsapp_alert` | `2-59/5 * * * *` | m | `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert` |
| MS SLA 完整同步 | `ms_sla_full` | `0 5 * * *` | n | `services/ms_sla_service.py → run_full_sync` |
| DC server 告警 WhatsApp 推送 | `ume_alarm_whatsapp_alert` | `* * * * *` | m | `services/ume_alarm_whatsapp_service.py → run_ume_alarm_whatsapp` |
| Fiber Break 告警自动派单 | `eflow_fiber_assign` | `3-59/5 * * * *` | m | `services/eflow_fiber/fiber_assign_service.py → run_fiber_assign` |
| eFlow 实时告警同步 | `eflow_active_alarm` | `*/1 * * * *` | x | `services/eflow_api_client.py → fetch_and_save_active_alarm` |
| eFlow 历史告警同步 | `eflow_history_alarm` | `0 */3 * * *` | n | `services/eflow_api_client.py → fetch_and_save_history_alarm` |
| eFlow TT 规则收集与匹配检查 | `eflow_tt_rules_check` | `20 4 * * *` | n | `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check` |
| RAN Main KPI 同步 | `main_kpi_sync` | `0 4 * * *` | u | `services/ran_ume_main_kpi.py → run_main_kpi_sync` |
| RAN 小区可用性 1-Day 同步 | `cell_availability_sync` | `30 4 * * *` | u | `services/ran_cell_availability_sync.py → run_cell_availability_sync` |
| RAN Cells KPI 同步 | `cells_kpi_sync` | `50 4 * * *` | u | `services/ran_cells_kpi_sync.py → run_cells_kpi_sync` |
| RAN Network KPI 同步 | `network_kpi_sync` | `0 5 * * *` | u | `services/ran_ume_network_kpi.py → run_network_kpi_sync` |
| 可用率核对宽表重建 | `avail_recon_sync` | `10 6 * * *` | u | `services/avail_recon_sync.py → run_avail_recon_sync` |
| BP Cells Report 更新 | `bp_report_sync` | `20 6 * * *` | u | `services/bp_report_sync.py → run_bp_report_sync` |
| CNN UME KPI 同步 | `cnn_kpi_sync` | `0 6 * * *` | n | `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync` |
| CNN UME KPI 5分钟同步 | `cnn_kpi_sync_5mins` | `*/15 * * * *` | n | `services/cnn_ume_kpi_5mins_service.py → run_cnn_kpi_sync_5mins` |
| SP 备件数据同步 | `sp_data_sync` | `10 * * * *` | s | `services/get_sp_table.py → run_sp_data_sync` |
| iPRAN UME KPI 同步 | `ipran_kpi_sync` | `0 8 * * *` | u | `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync` |
| Liberia 宕站 1小时报告邮件 | `liberia_email_1h` | `15 * * * *` | m | `services/liberia_email_report.py → run_1h_report` |
| Liberia 宕站 8小时报告邮件 | `liberia_email_8h` | `20 */8 * * *` | m | `services/liberia_email_report.py → run_8h_report` |
| MS Contract KPIs 日报邮件 | `kpi_ms_contract` | `30 5 * * *` | m | `services/kpi_email_report.py → run_ms_contract_kpi` |
| MS WOs SLA 日报邮件 | `kpi_ms_wo_sla` | `35 5 * * *` | m | `services/kpi_email_report.py → run_ms_wo_sla` |
| SpareParts 备件报表邮件 | `kpi_sp_spareparts` | `45 9 * * *` | m | `services/kpi_email_report.py → run_sp_spareparts` |
| Comsumables 耗材报表邮件 | `kpi_sp_consumables` | `50 9 * * *` | m | `services/kpi_email_report.py → run_sp_consumables` |
| SP 备件报表生成 | `sp_report_generate` | `15 5 * * *` | m | `services/kpi_email_report.py → run_sp_report_generate` |
| SP 备件明细报表邮件 | `sp_email_details` | `5 7 * * *` | m | `services/kpi_email_report.py → run_sp_details_email` |
| SP 备件明细分文件邮件 | `sp_details_files_email` | `5 10 * * *` | m | `services/kpi_email_report.py → run_sp_details_files_email` |
| Comsumables&SpareParts Report Whatsapp | `sp_whatsapp_report` | `55 7 * * *` | m | `services/kpi_email_report.py → run_sp_whatsapp_report` |
| SP 物料库存与消耗报表邮件 | `sp_material_report` | `45 7 * * *` | m | `services/kpi_email_report.py → run_sp_material_stock_consumption` |
| MS Network Availability 日报邮件 | `kpi_ran_availability` | `30 9 * * *` | m | `services/kpi_email_report.py → run_ran_availability` |
| EWS 恢复后邮件补发 | `email_recovery` | `*/10 * * * *` | m | `services/email_recovery.py → run_email_recovery_task` |
| Packet Loss 丢包同步 | `packet_loss_sync` | `30 6 * * *` | u | `services/packet_loss_service.py → run_packet_loss_sync` |
| Packet Loss 丢包日报邮件 | `packet_loss_email` | `45 6 * * *` | u | `services/kpi_email_report.py → run_packet_loss_email` |
| IP RAN M6K-FW 图表邮件 | `ipran_m6k_chart_email` | `45 6 * * *` | m | `services/ipran_chart_service.py → run_ipran_m6k_chart_email` |
| CNN Free Rating 图表邮件 | `ccn_free_rating_chart_email` | `45 7 * * *` | m | `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email` |
| FW 吞吐 KPI 同步+图表邮件 | `fw_kpi_sync` | `15 7 * * *` | n | `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync` |
| 电池 KPI 同步 | `battery_kpi_sync` | `5 * * * *` | u | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync` |
| 电池 KPI 邮件 | `battery_email` | `10 7,19 * * *` | m | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email` |
| 邮箱空间清理 | `mailbox_cleanup` | `0 * * * *` | m | `services/mailbox_cleanup.py → run_mailbox_cleanup` |
| Incident Overview 数据同步 | `incident_overview_sync` | `20 * * * *` | m | `services/incident_overview_sync.py → run_incident_overview_sync` |
| FineBI 报表文件同步 | `finebi_report_sync` | `10 * * * *` | m | `services/finebi_report_sync.py → run_finebi_report_sync` |
| 数据库数据新鲜度巡检 | `db_freshness_check` | `15 * * * *` | m | `services/db_freshness_check.py → run_db_freshness_check` |
| MTTR/TT 宽表重建 | `mttr_tt_sync` | `40 7 * * *` | m | `services/mttr_tt_sync.py → run_mttr_tt_sync` |
| Progress 宽表重建 | `progress_sync` | `50 7 * * *` | m | `services/progress_sync.py → run_progress_sync` |
| 失败任务自动重试 | `auto_retry_failed` | `*/10 * * * *` | m | `services/auto_retry.py → run_auto_retry_task` |
| RAN CM 小区数据同步 | `cm_data_sync` | `30 8 * * *` | u | `services/cm_data/cm_data_export.py → run_cm_data_sync` |
| PG→SQLite 数据快照 | `pg_to_sqlite_sync` | `45 * * * *` | m | `backend/scripts/sync_pg_to_sqlite.py → main` |
| MW UME KPI 同步 | `mw_ume_kpi_sync` | `15 5 * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync` |
| MW UME KPI 实时同步 | `mw_ume_kpi_sync_rt` | `*/15 * * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt` |
| CN EMS KPI 缓存同步 | `ems_kpi_cache_sync` | `*/15 * * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync` |
| CN EMS KPI 日粒度CSV | `ems_kpi_daily` | `20 0 * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily` |
| CXO 看板数据缓存同步 | `cxo_dashboard_cache_sync` | `*/10 * * * *` | v | `services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync` |
| VMAX CXO 天粒度日值归档 | `vmax_cxo_daily_sync` | `15 * * * *` | v | `services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync` |
| VMAX 多报表指标采集 | `vmax_multi_data_sync` | `45 * * * *` | v | `services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync` |
| OLIB SOC 看板 KPI 增量 | `olib_soc_kpi_daily_sync` | `20 6 * * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync` |
| OLIB SOC VMAX 例行报表 | `olib_soc_vmax_report` | `30 7 1 * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report` |
| 客户业务 KPI 同步 | `ume_in_kpi_sync` | `45 5 * * *` | n | `services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync` |
| 客户业务 KPI + OSG 周报邮件 | `ume_in_osg_report` | `30 6 * * *` | n | `services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）` |
| SP Online 工单同步 | `sp_online_sync` | `35 */6 * * *` | n | `services/sp_online_sync.py → run_sp_online_sync` |
| SP 物料主数据同步 | `sp_material_sync` | `55 4 * * *` | n | `services/sp_material_sync.py → run_sp_material_sync` |
| SP 在线未关闭单报表生成 | `sp_online_report_generate` | `0 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report_generate` |
| SP 在线未关闭单报表发送 | `sp_online_report_send` | `35 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report` |
| eFlow 告警规则收集 | `eflow_alarm_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules` |
| eFlow 推单规则收集 | `eflow_push_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules` |
| eFlow 推单规则检查 | `eflow_push_rules_check` | `10 5 * * 2` | n | `services/eflow_rules/eflow_push_rules_check_task.py → run_eflow_push_rules_check` |
| WhatsApp 知识库同步（推单规则） | `whatsapp_kb_sync_push_rules` | `4 0 */3 * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_push_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| WhatsApp 知识库同步（告警规则） | `whatsapp_kb_sync_alarm_rules` | `4 0 */3 * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_alarm_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| WhatsApp 知识库同步（TT 级别规则） | `whatsapp_kb_sync_tt_rules` | `35 4 * * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_tt_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| 日志文件清理 | `log_cleanup` | `17 3 * * *` | m | `services/log_cleanup.py → run_log_cleanup` |
| TMP 目录清理 | `tmp_cleanup` | `47 3 * * *` | m | `services/tmp_cleanup.py → run_tmp_cleanup` |
| TTs and MTTR 报表生成 | `tt_mttr_report_generate` | `20 7 * * *` | m | `services/tt_mttr_report.py → run_tt_mttr_report` |
| RAN 用户身份清单（VoLTE/N78） | `gp_ran_user_sync` | `20 13 * * *` | g | `services/gp_ran/gp_ran_sync.py → run_gp_ran_user_sync` |

每个任务的工作流与维护要点：

#### eFlow 数据同步（`eflow_sync`）

- 默认 cron: `22 * * * *`　|　worker 组: **n**
- 工作流脚本: `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")`

**功能**: 从 ZTE eFlow API 增量同步 TT/WO/CR/PM/Site/Person 六类数据

**工作流与数据流**:

1. 每小时 :22 调 eFlow API 增量拉取 TT/WO/CR/PM/Site/Person
1. 清洗后写主库动态 eFlow 表（运行时按上游字段建表，不进 Alembic）
1. 为 TT&WO / 告警 / GIS / eFlow 知识库等页面供数

**维护要点**:

- 增量只拉新变更；发现漏数据靠次日 eflow_sync_full 全量兜底
- 凭据分组 eflow；会话被踢会连续 failed，由 auto_retry_failed 自动重试

#### eFlow 每日全量同步（`eflow_sync_full`）

- 默认 cron: `0 1 * * *`　|　worker 组: **n**
- 工作流脚本: `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")`

**功能**: eFlow 全量兜底：拉全量窗口（默认自 2026-01-01），补齐增量遗漏并刷新报告。大窗口下 TT/WO 分段拉取，避免单次大导出失败；TT/WO 缺失即判任务失败

**工作流与数据流**:

1. 每天 01:00 按全量窗口拉取全部记录
1. 窗口跨度大时 TT/WO **分段拉取**（默认 30 天/段）后合并去重，避免单次大导出超过 120s 轮询窗口而 500 失败
1. 与增量写同一批主库表，去重覆盖
1. 完成后刷新相关报告产物

**维护要点**:

- 白天发现 eFlow 缺数的首要修复手段，可在任务管理页手动执行一次
- 全量窗口起点可配置，调整时注意拉取时长；段长由 EFLOW_FULL_SEGMENT_DAYS 控制（默认 30 天）
- 2026-10-09 修复：此前 TT/WO 全量导出连续多日 500 失败，而任务仍报 success=True（缺失键被静默 continue）。现 TT/WO 缺失即写 errors → success=False

#### RAN UME 日报（`ran_ume_daily`）

- 默认 cron: `0 2 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_ume_service.py → run_ran_ume_full_task`

**功能**: RAN UME PM 数据获取 + Daily Availability KPI 报表生成 + FTP 上传

**工作流与数据流**:

1. RSA 加密登录 RAN UME 网管查询 PM 数据
1. 生成 Daily Availability KPI 报表
1. 报表经 FTP 上传远程主机，供后续邮件/看板使用

**维护要点**:

- 凭据分组 zte_ume；u 组内串行，前序任务卡住会顺延
- 查询模板与回溯天数在 services/ran_ume_config.json

#### Site Outage 截图（`site_outage_screenshot`）

- 默认 cron: `0 1 * * *`　|　worker 组: **m**
- 工作流脚本: `services/site_outage_service.py → run_site_outage_screenshot`

**功能**: 对告警管理看板（Site Outage Monitor）的 ERA/Regular/ALL 三个视图自动截图

**工作流与数据流**:

1. Playwright 打开告警管理看板页面
1. 分别对 ERA / Regular / ALL 视图截图落盘
1. 产出供 03:00 的 whatsapp_send 发送

**维护要点**:

- 截图对象是 iframe 页 alarm-management.html——改该页 DOM 前先确认截图选择器仍找得到
- 与 whatsapp_send 同在 m 组，靠 cron 时间顺序（01:00 → 03:00）保证先后

#### WhatsApp 消息发送（`whatsapp_send`）

- 默认 cron: `0 3 * * *`　|　worker 组: **m**
- 工作流脚本: `services/whatsapp_service.py → run_whatsapp_send`

**功能**: 发送 Site Outage 截图和文件到 WhatsApp 群组（Playwright 自动化）

**工作流与数据流**:

1. 读取 01:00 site_outage_screenshot 产出的截图
1. Playwright 操作 WhatsApp Web 发送到群组

**维护要点**:

- 依赖截图任务先成功；WhatsApp Web 登录态失效时需人工重新扫码

#### WhatsApp 消息发送（扩展）（`whatsapp_send_ext`）

- 默认 cron: `0 3 * * *`　|　worker 组: **m**
- 工作流脚本: `services/whatsapp_ext_service.py → run_whatsapp_send_ext`

**功能**: WhatsApp 发送（扩展版）：投递发送作业，由浏览器扩展在已登录的 WhatsApp Web 中发送，与 Playwright 版并存

**工作流与数据流**:

1. 投递发送作业到队列
1. 浏览器扩展（whatsapp_sender_extension）在已登录的 WhatsApp Web 标签页中实际发送

**维护要点**:

- 2026-08-31 上线时曾漏登记 worker 分组导致 pending 卡死，后补入 m 组——新增任务务必同步登记 GROUP_TASK_MAP

#### WhatsApp 消息发送（Baileys）（`whatsapp_send_baileys`）

- 默认 cron: `0 4 * * *`　|　worker 组: **m**
- 工作流脚本: `services/whatsapp_send_baileys_service.py → run_whatsapp_send_baileys`

**功能**: 第三种 WhatsApp 发图通道：走 Baileys 协议直发（不依赖浏览器/Playwright），与 Playwright/扩展版并存；默认禁用，必须在「任务管理」页手动启用（Baileys 违反 WhatsApp ToS，启用前须走人工审批）

**工作流与数据流**:

1. 本任务扫 SITE_OUTAGE_DIR（与 whatsapp_send / whatsapp_send_ext 共享同一份图片目录与 GROUPS 配置）并把 items（含磁盘绝对路径）写进作业文件 data/whatsapp_send_baileys_job.json
1. whatsapp-kb-bot/src/notify.js 进程的轮询器认领（claim 即置 running + 原子写回），按 (群 × 文件) 调 sock.sendMessage({ image|document, ... })
1. 服务端回执（res.key.id）确认送达才计入 sent；单条失败不重试到群（避免重复），由 my_app 的 auto_retry_failed 决定
1. notify.js 回写 result 到作业文件；本任务轮询到 done/failed 后返回（task_runner 据此记任务历史）

**维护要点**:

- 默认 enabled=False——新部署不会自动跑，必须先确认 whatsapp-kb-bot notify 进程在跑、auth-notify/ 凭据有效，再在「任务管理」页手动启用
- 已被主开关豁免（MASTER_SWITCH_EXEMPT_IDS），批量切换不参与
- 与 whatsapp_send（Playwright 0 3 * * *）默认并存而非互斥；时间错开 1 小时避免同时投递双份图
- 回执是服务端 message id（不是猜的），与扩展通道的「数 DOM 气泡」判据不同；这是治本 2026-09-15 SP Details Report 1.5MB 静默漏发事故的根因
- 群发限频由 whatsapp-kb-bot/config.json 的 notify.fileSend 控制（默认 6 图 + 1 文档 / 作业）

#### eFlow P1 告警 WhatsApp 推送（`tt_alarm_whatsapp_alert`）

- 默认 cron: `2-59/5 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert`

**功能**: 触发制推送：每 5 分钟（相位 2-59/5，与上游同步错开 2 分钟）扫 realtime_alarm 实时告警表，发现「带 TT + 触发窗口内 + 告警码白名单」的 P1 告警后实时回 eFlow 查单，首推后按双档重报（无更新满 10 分钟催报、有更新满 30 分钟才报，均带 REMINDER 横幅），告警清除即止损。发送状态（是否已发/发了几次）落 eflow_tt_whatsapp_alert_log

**工作流与数据流**:

1. 扫 realtime_alarm（由 eflow_active_alarm 同步，注册表默认与生产配置均为 */1）：tt_id 非空、alarmraisedtime 在触发窗口内、告警码过白名单，按 tt_id 去重
1. 对触发单实时回 eFlow 查单（fetch_tt_live_batch，一次分页遍历），拿最新 ticket_severity / last_modified_time / alarm_clear_time；实时查不到回退本地 eflow_tt 镜像
1. 级别命中才推：首推发精简分析（分析引擎 --brief），重报双档——自上次发送后工单无更新满 10 分钟催报、有更新满 30 分钟才报（均带 ⚠️ REMINDER #N 横幅），未满间隔只记跟踪字段不打扰群里
1. 消息经 Baileys 推送进程（whatsapp-kb-bot/src/notify.js）发出，服务端回执确认后才把该单 send_status 置 Y（send_count 记发送次数）

**维护要点**:

- 2026-10-05 机制切换：触发源由 eflow_tt 定时扫描改为 realtime_alarm 触发 + 实时查单，首推时延从 45~75 分钟压到分钟级；window_minutes 语义变为「触发窗口」
- 依赖 eflow_active_alarm 的同步周期：realtime_alarm 的 _sync_time 滞后超过「实际调度周期 × 1.5」（自适应，现 */1 下约 1.5 分钟）会在任务结果里告警（触发面静默变空的预防项）
- 99933 的排除在 Python 侧做——告警码 '99933' 与 '99933.0' 并存，写进 SQL 会漏；白名单留空 = 不过滤
- 从未确认送达的单按同一节流重试；一轮全部未确认会通过 warnings 走微信/邮件主动喊人（2026-10-01「群内静默」事故的治本项）
- 群组留空会回退测试群 test123 并在任务结果里显式告警（group_fallback=true），不会静默消失

#### MS SLA 完整同步（`ms_sla_full`）

- 默认 cron: `0 5 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ms_sla_service.py → run_full_sync`

**功能**: SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）

**工作流与数据流**:

1. 每 6 小时按 nur_calc 实时口径重算 NUR/SLA/WO 指标
1. 写 data/ms_sla/ms_sla_dashboard.sqlite3
1. 供 MS SLA 看板与两份日报邮件使用

**维护要点**:

- 看板数字以本任务的实时计算为准（与历史快照文件可能不一致）
- 口径调整改 backend/services/nur_calc.py

#### DC server 告警 WhatsApp 推送（`ume_alarm_whatsapp_alert`）

- 默认 cron: `* * * * *`　|　worker 组: **m**
- 工作流脚本: `services/ume_alarm_whatsapp_service.py → run_ume_alarm_whatsapp`

**功能**: 每分钟直连 ZTE UME 网管（10.121.8.2）拉当前告警，命中精确「告警码:级别」对（默认 89029:major、89006:major）才推送到指定群；未清除告警按配置间隔催报（带 REMINDER 横幅），曾推送过的告警从上游消失则补发「已恢复」；首轮只登记不发送（防存量刷群），状态落 ume_alarm 相关表

**工作流与数据流**:

1. 每分钟从 UME 拉取当前告警快照
1. 按「告警码:级别」精确配对过滤
1. 经 WhatsApp 推送；未清除的按间隔催报，消失的补发恢复通知

**维护要点**:

- 首轮只登记不发送，避免把存量告警一次性刷进群
- 与 eflow 系列的 tt_alarm_whatsapp_alert 是两条独立通道（不同上游、不同告警码体系）

#### Fiber Break 告警自动派单（`eflow_fiber_assign`）

- 默认 cron: `3-59/5 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/eflow_fiber/fiber_assign_service.py → run_fiber_assign`

**功能**: 查 eFlow 实时告警，命中告警码白名单（默认 4758 Fiber Break，页面可配）、存续时长满 15 分钟（派单等待时长，页面可配）、在触发窗口内、且同站点同时间窗口无 99933 告警时，把 ME 名解析成站点 ID+站点名后派单到指定用户组；派单后回查 ttid 确认真建出（内置重试）才通报到 WhatsApp 群。默认演练模式

**工作流与数据流**:

1. 查 eFlow 实时告警（未清除）
1. 按告警码 + 存续满 15 分钟（派单等待时长）+ 触发窗口 + 同站点无 99933 过滤（站名对不上则按「无关联」继续派单）
1. 跳过上游已有 TT（ttid 非空）与已派过的告警
1. ME 名解析成站点名 → cmdb 查数字站点 ID（精确 → 归一化 → 等长元音近似）
1. 调派单接口建 TT → 回查 ttid 确认 → WhatsApp 通报

**维护要点**:

- 派单等待时长 15 分钟：告警升起后要先存在满 15 分钟才派单并发 WhatsApp（业务口径「告警发生到选择超过 15 分钟才派」）——不是一升起就派，留这段时间让短时闪断自然清除；配 0 可恢复立即派单
- 默认 dry_run 演练（只匹配记录不真派单），核对无误后到「任务配置」关掉
- 关联 99933 无法判定时（fiber 只有 ME 推导站名、与 cmdb 写法不同，如 luogan/luogon）按「没有关联」继续派单并记 correlation_undetermined 留痕——不能因为站名匹配不到就长期漏派
- 站点解析失败（cmdb 无此站点，如实测 Tokadeh）时自动派不了：记 N 并在群里发一条「需人工在 eFlow 处理」通报，同一条只发一次（send_status 抑制），不静默漏派
- Fiber 派单必须带数字站点 ID + 站点名，只传 ME 名接口回 success 却不建 TT（实测教训）
- Fiber 派单时灵时不灵，故内置重试，且以回查到 ttid 才判成功（不信接口的 status:true）
- 告警上游已有 ttid 时直接跳过：eFlow 自己的派单规则会先建 TT，不跳过就会重复建单（实测 Zardun 两条）
- 关联 99933 的站点比对按「数字站号 + 站点名」多键取交集（4758 与 99933 的 site/mename 形态不同，单键比对会漏判）
- 站点名近似匹配只接受「等长且仅元音互换」（如 luogan→luogon）：扫生产 cmdb 830 站，通用 0.9 相似度会把 Garplay/Gbarplay、Butuo/Buutuo、Sanniquillie 5/1 这些不同站点判成同一个；另拒绝分期站点(X/X2)与歧义候选。命中会写 warnings 并在通报里附提示，需人工核对
- eFlow 侧 ttstatus 非 0 不再阻断派单（2026-10-27 业务要求：不能被 ME 未绑定站点挡住）：照派，但只用最小预算（1 次尝试 × 2 次回查）；派不出时记 N 并在群里通报一次「需人工在 eFlow 处理」，ME 绑定修好后下一轮自动派单成功
- 同一次光纤中断只派一个 TT（2026-10-27 需求）：一条光缆断掉会让链路上多个站点同时告警（实测 14:21 一次故障 9 秒内 5 条告警、建出 5 个重复单）；升起时间落在合并窗口（group_window_minutes，默认 10 分钟）内的告警合并成一个 TT，以组内最早的那条为组长建单，其余登记同一个单号，通报正文列出本单实际涵盖的站点；配 0 = 关闭合并（回滚开关）。判据用时间窗而非拓扑，是因为现有数据判不出同一条光纤：probeid 全库同一个 UUID、impact_site_list/link_path 全空、flm_database.fdn 被 96 个站点共用（太粗）、victim_topology 里 R.I.A 与 Tower Hill 互不包含且各是独立网关、eFlow relatedAlarms 返回 0 条
- 状态落 eflow_fiber_assign_log：Y=已派成功/上游已有 TT，D=演练（关掉演练会重新处理），N=失败下轮重试
- TT 标题由 eFlow 自动生成，格式 `<site>.[<站点名>]<告警名>`，接口不接受自定义标题
- 通报正文一律英文（2026-10-27 要求）：字段标签、警示语、失败原因全英文；中文只留在状态表 last_error、结果 warnings 与日志里，因为群是一线英文环境

#### eFlow 实时告警同步（`eflow_active_alarm`）

- 默认 cron: `*/1 * * * *`　|　worker 组: **x**
- 工作流脚本: `services/eflow_api_client.py → fetch_and_save_active_alarm`

**功能**: 从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite（每分钟）

**工作流与数据流**:

1. 每分钟拉 FM Active 活跃告警（注册表默认与生产配置均为 */1）
1. 双写 app.db 的 realtime_alarm 与 eflow.sqlite3 副本（副本仅供报表）
1. 供实时告警看板 / 实时告警地图 / 告警管理看板使用，同时是 P1 告警 WhatsApp 推送的触发源

**维护要点**:

- 页面只读 app.db；「实时」粒度 = 实际调度周期（现为 1 分钟），并非秒级推送
- 改调度请在「任务配置」页操作（写 task_schedule_config 表，该行优先于注册表默认值）
- 本任务 2026-10-15 从 n 组拆到 x 组单独一组：原先与 eflow_sync 共用一条串行道，改 cron 也会被长任务挡住（实测最差排队 854s）
- ⚠️ 每分钟跑的可行性依赖会话复用（ensure_login 命中进程内/磁盘缓存而不再登录），若改动会话逻辑需重新评估频率
- 告警字段映射在 services/eflow_alarm_config.json

#### eFlow 历史告警同步（`eflow_history_alarm`）

- 默认 cron: `0 */3 * * *`　|　worker 组: **n**
- 工作流脚本: `services/eflow_api_client.py → fetch_and_save_history_alarm`

**功能**: 从 eFlow FM History 接口获取近 7 天历史告警，过滤 TT ID，保存 CSV + SQLite

**工作流与数据流**:

1. 每 3 小时拉近 7 天 FM History 告警
1. 过滤出关联 TT 的记录后入库 history_alarm

**维护要点**:

- 7 天窗口固定；更早的历史需查主库保留数据

#### eFlow TT 规则收集与匹配检查（`eflow_tt_rules_check`）

- 默认 cron: `20 4 * * *`　|　worker 组: **n**
- 工作流脚本: `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check`

**功能**: 每天 04:20 从 eFlow 拉取激活的 TT Update Severity Rule，对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正

**工作流与数据流**:

1. 拉取最新规则生成 eflow_TT_rules.xlsx（正式规则表）
1. 对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正
1. 规则/矫正表/报告落盘，供任务报告文件页下载

**维护要点**:

- 正式规则表是 backend/services/eflow_rules/eflow_TT_rules.xlsx——根目录同名文件只是副本，改它不生效
- 「任务报告文件」页的 eFlow 规则页签可「立即执行」手动触发一次

#### RAN Main KPI 同步（`main_kpi_sync`）

- 默认 cron: `0 4 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_ume_main_kpi.py → run_main_kpi_sync`

**功能**: RAN UME Main KPI 历史指标同步（2G/3G/4G × Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传

**工作流与数据流**:

1. 登录 RAN UME 按 2G/3G/4G 模板查询 Main KPI 历史
1. 导出 Excel、增量更新 SQLite、FTP 上传远程主机

**维护要点**:

- 查询模板与回溯天数在 services/main_kpi_config.json（days_back）
- u 组串行，04:00 执行，前面任务（02:00 日报）卡住会顺延

#### RAN 小区可用性 1-Day 同步（`cell_availability_sync`）

- 默认 cron: `30 4 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_cell_availability_sync.py → run_cell_availability_sync`

**功能**: RAN UME 小区可用性天粒度 KPI 同步（FDD/UMTS/GSM/TDD 4 模板），写 ran_kpi_avalability_1day.sqlite3 + FTP 上传

**工作流与数据流**:

1. 按 FDD/UMTS/GSM/TDD 4 个模板查询小区可用性天粒度 KPI
1. 写 data/ran_kpi_avalability_1day.sqlite3
1. FTP 上传远程主机

**维护要点**:

- 库名 ran_kpi_avalability_1day.sqlite3 的 avalability 是历史拼写，多处按字符串引用，不要改名

#### RAN Cells KPI 同步（`cells_kpi_sync`）

- 默认 cron: `50 4 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_cells_kpi_sync.py → run_cells_kpi_sync`

**功能**: RAN UME 小区数据（2G/3G/4G）每日同步，聚合 Cells KPI（达标值 99.65%）物化写 ran_cells_kpi.sqlite3，只保留当月

**工作流与数据流**:

1. 复用小区可用性同步的 UME 获取方法拉取 GSM/UMTS/FDD 小区数据
1. 按小区逐条折算可用率并统计达标/未达标/无数据
1. 物化写 data/ran_cells_kpi.sqlite3（表 cells_kpi_daily，只保留当月）

**维护要点**:

- 口径与达标值定义在 services/ran_cells_kpi_service.py 顶部；2G 用信道折算，3G/4G 用服务时长/86400
- 看板 RAN 小区 KPI 优先读物化库，缺失时回退实时聚合 ran_kpi_avalability_1day.sqlite3

#### RAN Network KPI 同步（`network_kpi_sync`）

- 默认 cron: `0 5 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_ume_network_kpi.py → run_network_kpi_sync`

**功能**: RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G × Group/NW），导出 Excel 并导入 SQLite + FTP 上传

**工作流与数据流**:

1. 登录 RAN UME（Zeenshan）按 Group/NW 维度查 Network KPI 历史
1. 导出 Excel、导入 SQLite、FTP 上传

**维护要点**:

- 查询模板在 services/network_kpi_config.json

#### 可用率核对宽表重建（`avail_recon_sync`）

- 默认 cron: `10 6 * * *`　|　worker 组: **u**
- 工作流脚本: `services/avail_recon_sync.py → run_avail_recon_sync`

**功能**: 重建 avail_recon 可用率核对宽表（远端 Site_Daily × Master_Site_Database Region 近似聚合），写本机 data/avail_recon.sqlite3，供 Daily Availability KPI / Availability(TT) 看板

**工作流与数据流**:

1. 读远端 olbr_ms_master_database 的站点主数据（Site_Name → Region）
1. 按 Region 把站点名单内联进 SQL，在远端聚合 2G/3G/4G_Main_Kpi_Site_Daily 的 AVG(可用率)
1. 原子替换本机 data/avail_recon.sqlite3（表 availability_daily）

**维护要点**:

- 口径在 services/avail_recon_sync.py 顶部：Cell_Availability=AVG(rate)，不是「达标站点占比」（v1 曾算错，值域 40~100%）
- 看板侧经 dashboard_service.DB_ALIASES 把 avail_recon.sqlite3 解析到本机库；新增派生库照此登记
- 本任务 2026-09-21 上线前，该表由已退役的 my-finebi 手工 ETL 维护，无人调度导致冻结在 2026-09-13、看板静默停更

#### BP Cells Report 更新（`bp_report_sync`）

- 默认 cron: `20 6 * * *`　|　worker 组: **u**
- 工作流脚本: `services/bp_report_sync.py → run_bp_report_sync`

**功能**: 从 RAN_UME 读取 4G 小区级 PRB/吞吐/流量与小时级活跃用户数，按 umlaut 忙时口径重算 BP 劣化小区（日/周/月），更新本机 data/bp_report.sqlite3 并与 Excel 真值对账

**工作流与数据流**:

1. 按天从远端读 4G_Main_Kpi_Cell_Daily 的 PRB 利用率 / DL IP 吞吐 / DL+UL 流量（逐日一条 SQL，避免撞远端 5 万行上限被静默截断）
1. 经独立小时粒度通道取 Average DL Active User Number 与同小时的 PRB/吞吐（该指标日粒度不可用），按「活跃用户最大的那个小时」聚合出当天三值
1. 关联 bp_cell_dict 补上 Cluster/Layer（RAN_UME 无此维度，字典来自 Excel 的 BP Cells List）
1. 按口径重算每小区每日 is_bp，并重算日/周/月汇总（周 4/7 天、月 3/4 个完整周）；周/月为纯 INSERT（只写新周期，不动 Excel 既存行），判定列另由 backfill_period_verdicts 填空
1. 与 Excel 的 bp_cells_excel 逐日对账，差异与口径说明一并写入 bp_sync_meta

**维护要点**:

- 口径唯一真相源在 services/bp_caliber.py：日（忙时三值）、周 4/7、月 3/4
- ⚠️ Average DL Active User Number 只在**小时粒度**可用：日粒度下 UME 返回 HTTP 200 + 合法 queryid 但**静默丢弃该列**、无任何报错，故走 services/bp_active_user.py 的独立通道（C373384373 + 1638004469342 + 1638004469332）。取不到时该日 is_bp=NULL（不可判定），**绝不当 0**
- ⚠️ UME 返回的数值是字符串且 PRB 带百分号（如 "2.46%"），必须去 % 再 /100；且 itemsposition 必须全为 0，写成 [0,1,2] 会返回 0001619999 拒绝查询
- ⚠️ PRB 利用率在源表里是**小数**（0~1，实测 max 0.9751），阈值是 0.80 不是 80；写成 80 会让条件永不成立且不报错
- ⚠️ 源表列名 "E-UTRAN\xa0FDD\xa0Cell Name" 里的分隔符是**不换行空格**；写成普通空格时 SQLite 不报错，而是把双引号标识符当字符串字面量返回，整列变成列名文本（bp_caliber.assert_columns_exist / assert_no_literal_fallback 就是为此加的守卫）
- Excel 的 BP Cells List 最后一天（2026-09-26）只有 53 行、远少于当日真值 486，属导出未完成；对账时不要把该日差异当实现缺陷
- ⚠️ 周/月重算**必须是纯 INSERT**（先查该周期是否已存在，存在就跳过）：曾经按整月聚合 + ON CONFLICT DO UPDATE，把 Excel 的 2026-W39/W40/2026-09 三行覆盖成 bp_cells=0；既存 Excel 行的指标真值一律不动，判定列为 NULL 时由 backfill_period_verdicts 单独填空
- ⚠️ 周/月判定需要的完整周数：week_days_in_month 实测 2026-09 只有 3 个完整周、而 MONTH_TOTAL_WEEKS=4，故该月 is_bp_month 恒为 NULL（口径与日历错配，非缺数据）；界面显示成因而非仅「不可判定」

#### CNN UME KPI 同步（`cnn_kpi_sync`）

- 默认 cron: `0 6 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync`

**功能**: CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN

**工作流与数据流**:

1. 登录 CNN UME 查核心网 KPI（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating）
1. 经 API 写入远程 DB CNN

**维护要点**:

- Free Rating 数据同时供 ccn_free_rating_chart_email 出图

#### CNN UME KPI 5分钟同步（`cnn_kpi_sync_5mins`）

- 默认 cron: `*/15 * * * *`　|　worker 组: **n**
- 工作流脚本: `services/cnn_ume_kpi_5mins_service.py → run_cnn_kpi_sync_5mins`

**功能**: 与「CNN UME KPI 同步」同源同账号，但取细粒度（5 个模板 5 分钟、3 个模板 15 分钟）、窗口为昨天 00:00 至现在，API 写入 DB CNN 的 5mins_* 新表，供「CN KPI 5分钟」看板做 Day0/Day1/Day7 叠画；日/月粒度表不受影响

**工作流与数据流**:

1. 登录 CNN UME（与 cnn_kpi_sync 共用会话缓存）
1. 按 8 个模板并发查询 5 分钟粒度数据（昨天 00:00 至现在）
1. 写入 db_ps_cs_cn 的 5mins_<原表名> 表（upsert）

**维护要点**:

- ⚠ 混合粒度：Voice/VLR/Data/4G FDD/Free Rating 用 5 分钟档（gr=300）；xGW License、xGW CPU、3G FDD 的原模板没有 5 分钟档，改走上游 2026-10-19 补建的 15 分钟档模板（gr=900，见 FIFTEEN_MIN_TEMPLATES）
- ⚠ 本任务保留「0 行 → 跳过该表且不计失败」的兜底（原 cnn_kpi_sync 的逻辑是 0 行即报错，本任务刻意不同），上游再调整档位时不会让任务每 15 分钟失败一次
- ⚠ 实测单轮约 105 秒（Free Rating 一天就有 1.4 万行）；若耗时逼近 15 分钟，需降低并发或放宽节拍
- 与 cnn_kpi_sync 同在 n 组串行，避免两个任务各自登录同一账号互踢
- 页面为本任务的唯一消费方：?page=cn_kpi_5mins（services/cn_kpi_5mins_service.py 读 5mins_* 表）

#### SP 备件数据同步（`sp_data_sync`）

- 默认 cron: `10 * * * *`　|　worker 组: **s**
- 工作流脚本: `services/get_sp_table.py → run_sp_data_sync`

**功能**: 从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db，并镜像写入 FineBI WareHouseDashBoard inventory.db

**工作流与数据流**:

1. 登录备件 SFTP（凭据分组 sftp_sp）
1. 拉取 Inbound/Outbound/Inventory/OC Rule/Transfer 5 份报表
1. 清洗后写主库，供仓库看板与 SP 报表使用
1. 全部落库后镜像写入 FineBI inventory.db（UNC 路径；普通表整表替换、Inventory 只追加新行）
1. 最后按保留期清理 Inventory 历史快照（app.db 与镜像库同口径，默认 180 天）

**维护要点**:

- 仓库看板 iframe 读的就是这批数据；报表缺失先看本任务是否成功
- 镜像失败会在任务消息提示但影响不到 app.db；路径/开关在 Settings → 任务配置（mirror_db_path / mirror_enabled）
- inventory_details 只追加不覆盖，靠保留期控制体积：Settings → 任务配置 inventory_retention_days（默认 180）。清理基准取表内最新 update_date，上游断流时不会清空整表
- 仓库看板「Inventory Quantity Trend」直接读取本表全部日期（无日期参数时返回全量），调小保留天数会直接缩短趋势图历史
- 2026-09-20 起由每天 07:00 改为每小时 :10：上游 SFTP 本就每小时 :00:03 导出一份，而 MsPortal 的 QC 面板 SPMS 卡读本任务写的 inband_details/outband_details，按天同步时那个数字最长滞后 24 小时。排 :10 是为了避开同组的 eflow_sync(:00) 与 sp_online_sync(:35)
- 单次耗时被末尾的 FineBI 镜像拖长（UNC inventory.db 偶发 database is locked，实测 1~9min）；队列有单飞保护，上一轮没跑完会跳过本轮触发，不会堆叠，但那一小时的数据就是旧的。若 QC 面板其它指标（TT/WO/CR/PMT）跟着一起变慢，先查本任务是否占住了 n 组 worker

#### iPRAN UME KPI 同步（`ipran_kpi_sync`）

- 默认 cron: `0 8 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync`

**功能**: iPRAN UME M6000 路由器 KPI 同步（HQ M6K-FW 等），导出 Excel 并导入 SQLite + FTP 上传

**工作流与数据流**:

1. 登录 iPRAN UME 查 M6000 路由器 KPI
1. 导出 Excel、写 data/ipran_ume/ipran_ume_kpi.sqlite3、FTP 上传

**维护要点**:

- 产出同时供 ipran_m6k_chart_email（06:45）出图；u 组内排在 08:00

#### Liberia 宕站 1小时报告邮件（`liberia_email_1h`）

- 默认 cron: `15 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/liberia_email_report.py → run_1h_report`

**功能**: 发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单

**工作流与数据流**:

1. 每小时 :05 汇总最近 1 小时宕站数据
1. 生成内嵌图 + Excel 报表
1. 发送到主送/抄送名单（收件人在系统设置维护）

**维护要点**:

- EWS 不可用时漏发由 email_recovery（每 10 分钟）自动补发

#### Liberia 宕站 8小时报告邮件（`liberia_email_8h`）

- 默认 cron: `20 */8 * * *`　|　worker 组: **m**
- 工作流脚本: `services/liberia_email_report.py → run_8h_report`

**功能**: 发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单

**工作流与数据流**:

1. 每 8 小时（00/08/16 时 :10）汇总窗口内宕站数据
1. 生成内嵌图 + Excel 报表并发送

**维护要点**:

- 与 1 小时版同一脚本不同入口；收件人名单改动后两种报表同时生效

#### MS Contract KPIs 日报邮件（`kpi_ms_contract`）

- 默认 cron: `30 5 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_ms_contract_kpi`

**功能**: 发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）

**工作流与数据流**:

1. 读取 ms_sla_full（05:00）产出的本地 ms_sla 数据
1. 生成 Contract KPIs 日报
1. 发送到远程名单中的收件人

**维护要点**:

- 数据来自 ms_sla_full（05:00 同步，约 05:11 完成）；本任务 05:30 发送，用的是当天这一轮的数

#### MS WOs SLA 日报邮件（`kpi_ms_wo_sla`）

- 默认 cron: `35 5 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_ms_wo_sla`

**功能**: 发送 MS WOs SLA Achievements Daily Report（本地数据 + 远程名单）

**工作流与数据流**:

1. 读取本地 ms_sla 数据
1. 生成 WOs SLA 日报并发送到远程名单

**维护要点**:

- 与 kpi_ms_contract 同一脚本不同入口，只差 5 分钟错峰

#### SpareParts 备件报表邮件（`kpi_sp_spareparts`）

- 默认 cron: `45 9 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_spareparts`

**功能**: 发送 SpareParts 报表（本地 sp_email 数据 + 远程共享名单）

**工作流与数据流**:

1. 读取 sp_report_generate（05:15）生成到 data/sp_email 的报表
1. 发送 SpareParts 报表到远程共享名单

**维护要点**:

- 报表文件缺失说明 05:15 的生成任务失败，先修上游再重发本任务

#### Comsumables 耗材报表邮件（`kpi_sp_consumables`）

- 默认 cron: `50 9 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_consumables`

**功能**: 发送 Comsumables 报表（本地 sp_email 数据 + 远程共享名单）

**工作流与数据流**:

1. 读取 data/sp_email 下 sp_report_generate 产出的耗材报表
1. 发送到远程共享名单

**维护要点**:

- 任务名 Comsumables 是历史拼写（实为 Consumables），注册表按此引用，勿改

#### SP 备件报表生成（`sp_report_generate`）

- 默认 cron: `15 5 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_report_generate`

**功能**: 从 SFTP 下载备件数据，生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表到本地 data/sp_email

**工作流与数据流**:

1. 登录 SFTP 下载备件原始数据
1. 生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表
1. 落盘 data/sp_email 供 09:45/09:50 两个邮件任务与 07:05 明细邮件使用

**维护要点**:

- 是 3 个 SP 邮件任务的上游，失败会导致当天备件邮件整体缺报

#### SP 备件明细报表邮件（`sp_email_details`）

- 默认 cron: `5 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_details_email`

**功能**: 把 data/sp_email/data 下 4 份备件明细（inventory/inband/outband/transfer）合并为一个 Excel（sheet: Inventory/Inbound/Outbound/Transfer）发送邮件，邮件发出后把同一份 Excel 作为文档发到 WhatsApp 群 WH&SP Management

**工作流与数据流**:

1. 合并 data/sp_email/data 下 4 份 *_details.xlsx（inventory/inband/outband/transfer）为一个工作簿，附件名与主题带时间戳
1. 邮件发送（默认收件人为固定地址，可在系统设置 → 邮件收件人覆盖）
1. 邮件之后把同一份合并 Excel 作为文档发到 WhatsApp 群 WH&SP Management（2026-09-14 新增）

**维护要点**:

- 2026-09-01 上线时曾漏分组导致 pending 卡死，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP
- 本任务在 EMAIL_TASK_IDS 内：WhatsApp 侧失败时 error 只写 WHATSAPP_FAIL 固定标记，不拼底层异常原文，避免命中 EWS 关键字触发 email_recovery 整链补发（11 位收件人重复收报表）
- 上游是 sp_report_generate（05:15）：它不产出明细文件，本任务合并即失败，邮件与群都不发
- 2026-10-11 起 WhatsApp 侧改走「Baileys 主通道 → Playwright 回退」（whatsapp_dispatch）；发送者变为 Baileys 副号

#### SP 备件明细分文件邮件（`sp_details_files_email`）

- 默认 cron: `5 10 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_details_files_email`

**功能**: 每天 10:05 把 data/sp_email/data 下的 6 份备件明细**一份文件一封邮件**逐个发给 NOC，主题 Liberia OLR W.H <文件名> <日期时间>

**工作流与数据流**:

1. 逐份选取明细：优先未过滤的 *_source.xlsx 原始快照（sp_report_generate 05:15 在任何过滤之前留的 SFTP 快照），缺失时回退过滤后的 *_details.xlsx
1. 先整体校验 6 份是否齐全：缺任一份即整体失败、**一封都不发**（宁可一封不发，也不让收件人拿到不完整的一套报表）
1. 按**对外文件名**在 TMP 下各落一份副本（磁盘上是 inband/outband，对外写成 inbound/outbound），发完即清
1. 逐个发送，每封只挂 1 个附件，主题为「Liberia OLR W.H <附件文件名> <日期时间>」（例：Liberia OLR W.H inbound_details_source.xlsx 2026-09-30 10-05-00）
1. 单封发送失败不中断后续：已成功的继续发完，最后把失败项汇总进 error 供人工只补发缺的那几封

**维护要点**:

- 默认主送 MS.NOC@zte.com.cn，抄送 li.jing132@zte.com.cn / luo.wutao@zte.com.cn，可在系统设置 → 邮件收件人 的 sp_details_files 分组覆盖
- 对外文件名与磁盘源名不同（用户指定）：inband/outband → inbound/outbound，且 6 份一律带 _source 后缀，故附件需先按对外名落副本再发（owa_mail_report 取 Path(fp).name 作附件名）
- 与 sp_email_details（05:00）同数据源但打包方式不同：那个合并成一个多 sheet 工作簿并发 WhatsApp 群，本任务一文件一邮件发 NOC，互不影响
- 一文件一邮件 => 一次任务最多 6 次 EWS 会话，耗时约为单封的 6 倍；任务在 m 组串行，长时间占用会推迟同组其它轻任务
- 单封失败时 error 只写 SEND_FAIL 固定标记 + 文件名，**不拼底层异常原文**——否则命中 EWS 关键字会让 email_recovery 把 6 封全部补发，已成功的重复投递；底层细节在 result.failed 里
- ocrule_details 没有 *_source 快照，磁盘上只读过滤版；但对外名按用户要求统一带 _source（2026-10-09），故「名字带 _source、内容是过滤版」是预期行为，不是取错文件
- 上游是 sp_report_generate（m 组 05:15）：明细文件缺失先查它，而不是本任务

#### Comsumables&SpareParts Report Whatsapp（`sp_whatsapp_report`）

- 默认 cron: `55 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_whatsapp_report`

**功能**: 每天 07:55 把 Comsumables / SpareParts 两个邮件任务的同一批产物（合并总表 XLSX + 报表 PNG）发送到 WhatsApp 群 WH&SP Management

**工作流与数据流**:

1. 在 data/sp_email 下选取 Comsumables / SpareParts 的合并总表 XLSX（不含 " - Liberia" 分站点）
1. 收集两类报表的 PNG（主图在前、Summary-Changed 在后）
1. 经 whatsapp_dispatch 发送：Baileys 主通道 → Playwright 回退，发到群 WH&SP Management

**维护要点**:

- 上游是 sp_report_generate（m 组 05:15），它失败会导致本任务找不到报表文件
- 不发送邮件——邮件由 kpi_sp_consumables / kpi_sp_spareparts 负责
- 2026-10-11 起走「Baileys → Playwright」双通道；本任务发 4 图 + 2 xlsx，需 Baileys 单作业文档配额 ≥2（已放宽为 8 图 / 3 文档）

#### SP 物料库存与消耗报表邮件（`sp_material_report`）

- 默认 cron: `45 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_material_stock_consumption`

**功能**: 每天 07:45 把 SP 物料库存与消耗汇总（同「SP 物料库存与消耗统计」页面 page=sp_material 的口径）导出为 UNIFIED_EXCEL_V1 版式 Excel 附件 + 同内容 PNG 内嵌正文并邮件发送

**工作流与数据流**:

1. 调用 sp_material_summary_service.get_material_summary()（inventory_details 每日快照 + outband_details 报修出库）
1. 生成 UNIFIED_EXCEL_V1 版式 Excel（标题 / 副标题 / 两行合并表头 / 合计行在前 / 13 列 + Info 页），与页面「导出 Excel」逐格一致
1. 用 Pillow 把同一张汇总表画成 PNG（手法同 SP 报表图片：蓝表头 + 橙色区块条 + 斑马纹）
1. 落盘 data/sp_material_report（只保留最新一份）：Excel 作附件、PNG 内嵌正文发送

**维护要点**:

- 默认 15 主送 + 2 抄送，可在系统设置 → 邮件收件人 覆盖
- 汇总表无数据行时跳过发送并记为失败（多为上游 SP 数据同步未跑）
- PNG 生成失败只告警不阻断，邮件仍带 Excel 发出

#### MS Network Availability 日报邮件（`kpi_ran_availability`）

- 默认 cron: `30 9 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_ran_availability`

**功能**: 发送 MS Network Availability Daily Report（远程 FTP 图片 + 远程名单，无 Excel）

**工作流与数据流**:

1. 从远程 FTP 拉取已生成的可用性图片（由 ran_ume_daily 02:00 产出并上传）
1. 组装日报（无 Excel 附件）发送到远程名单

**维护要点**:

- 图片缺失通常是 ran_ume_daily（u 组 02:00）失败——查它而不是本任务

#### EWS 恢复后邮件补发（`email_recovery`）

- 默认 cron: `*/10 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/email_recovery.py → run_email_recovery_task`

**功能**: 每 10 分钟探测 EWS 是否恢复；恢复后自动补发近 3 小时内因 EWS 超时失败的邮件任务

**工作流与数据流**:

1. 探测 Exchange（EWS）连通性
1. 扫描近 3 小时内因 EWS 超时失败的邮件任务
1. 恢复后逐个补发

**维护要点**:

- 邮件没收到先查它的执行历史，而不是手动重跑原邮件任务

#### Packet Loss 丢包同步（`packet_loss_sync`）

- 默认 cron: `30 6 * * *`　|　worker 组: **u**
- 工作流脚本: `services/packet_loss_service.py → run_packet_loss_sync`

**功能**: RAN UME 丢包率（SDR/IPRAN IPPD）同步，入库 lte_pl.sqlite3 并生成丢包报告；只展示最近 7 个完整自然日

**工作流与数据流**:

1. 登录 RAN UME 拉丢包率（SDR/IPRAN IPPD）
1. 计算 STATUS（0~23 小时标志块）与 FINAL_STATUS 五级分类
1. 写 data/packet_lost/lte_pl.sqlite3（注意目录名是 packet_lost）并生成报告

**维护要点**:

- 看板与报告口径与 Packet_Loss 自动化 Excel 完全一致；当天没过完不展示
- 目录名 packet_lost 是历史拼写，不要改名

#### Packet Loss 丢包日报邮件（`packet_loss_email`）

- 默认 cron: `45 6 * * *`　|　worker 组: **u**
- 工作流脚本: `services/kpi_email_report.py → run_packet_loss_email`

**功能**: 发送 Packet Loss 丢包看板日报邮件（本地截图 + 最新报告 xlsx + 远程收件人清单），经 OWA 账户发送

**工作流与数据流**:

1. 截取丢包看板画面 + 取 06:30 同步生成的最新报告 xlsx
1. 经 OWA 账户发送到远程收件人清单

**维护要点**:

- 排在 06:45，紧跟 06:30 同步任务（同在 u 组串行，顺序有保证）

#### IP RAN M6K-FW 图表邮件（`ipran_m6k_chart_email`）

- 默认 cron: `45 6 * * *`　|　worker 组: **m**
- 工作流脚本: `services/ipran_chart_service.py → run_ipran_m6k_chart_email`

**功能**: 从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成 3 张利用率折线图并发送

**工作流与数据流**:

1. 查询 ipran_ume_kpi.sqlite3 的 HQ_M6K_FW_bnctp_15mins 表
1. 按 ME+SmartGroup 生成 3 张利用率折线图
1. 发送图表邮件

**维护要点**:

- 依赖前一天 08:00 ipran_kpi_sync 的数据；u 组任务失败时本邮件会出空图或失败

#### CNN Free Rating 图表邮件（`ccn_free_rating_chart_email`）

- 默认 cron: `45 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email`

**功能**: 从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成 4 张柱状图并发送

**工作流与数据流**:

1. 查询 db_ps_cs_cn.sqlite3 的 FREE_RATING 模板表
1. 按 MO 生成 4 张柱状图并发送

**维护要点**:

- 数据来自 cnn_kpi_sync（n 组，每天 06:00）写入的 DB CNN

#### FW 吞吐 KPI 同步+图表邮件（`fw_kpi_sync`）

- 默认 cron: `15 7 * * *`　|　worker 组: **n**
- 工作流脚本: `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync`

**功能**: 从 DPtech UMC 拉取整机吞吐数据，经 API 写入远程 fw_db.sqlite，生成近 14 天吞吐折线图并邮件发送

**工作流与数据流**:

1. 登录 DPtech UMC（凭据分组 fw_kpi）拉整机吞吐
1. 经 API 写入远程 fw_db.sqlite
1. 生成近 14 天吞吐折线图并发送

**维护要点**:

- 同步与出图发信在同一个任务里完成，失败时整链路（入库+邮件）都停

#### 电池 KPI 同步（`battery_kpi_sync`）

- 默认 cron: `5 * * * *`　|　worker 组: **u**
- 工作流脚本: `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync`

**功能**: 从 UME 拉取电池实时 KPI（健康度/SOC/充放电状态），全程内存不落盘，写入 battery_kpi.sqlite3 供电池看板使用

**工作流与数据流**:

1. 每小时 :05 登录 UME 拉电池实时 KPI
1. 全程内存处理（中间不落盘）
1. 写 data/battery/battery_kpi.sqlite3

**维护要点**:

- 电池看板默认只统计 24h 内新鲜读数（BATT_FRESH_HOURS 等环境变量控制阈值）
- 注意模块目录名是 battary_kpi_fetch（历史拼写），勿改

#### 电池 KPI 邮件（`battery_email`）

- 默认 cron: `10 7,19 * * *`　|　worker 组: **m**
- 工作流脚本: `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email`

**功能**: 将电池 KPI 报表（Excel）发送至远程名单中的邮箱，每日 07:00 与 19:00 各一次

**工作流与数据流**:

1. 从 battery_kpi.sqlite3 生成 Excel 报表
1. 发送到远程名单中的邮箱（每天两次）

**维护要点**:

- 与同步任务同脚本不同入口；收件人来自远程 FTP 名单

#### 邮箱空间清理（`mailbox_cleanup`）

- 默认 cron: `0 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/mailbox_cleanup.py → run_mailbox_cleanup`

**功能**: 每小时检查 Exchange 邮箱：邮件数 >500 且空间 >70% 时，硬删除最旧 200 封邮件，避免 storage limit 告警

**工作流与数据流**:

1. 每小时 :00 检查 Exchange 邮箱（exchangelib/EWS）
1. 邮件数 >500 且空间 >70% 时硬删除最旧 200 封

**维护要点**:

- 删除的是发件箱历史（含已发报表邮件），是防止报表发不出去的守卫任务，不要停用

#### Incident Overview 数据同步（`incident_overview_sync`）

- 默认 cron: `20 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/incident_overview_sync.py → run_incident_overview_sync`

**功能**: 每小时第 20 分钟从 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，版本化落盘 + current.json 指针

**工作流与数据流**:

1. 每小时第 20 分钟扫描 FineBI FTP 的 TT_WO/ 全部子目录
1. 取最新 incident_overview.xlsx 落盘为版本化文件 + current.json 指针
1. best-effort 刷新 incident_overview.xlsx 快照，供事件总览页使用

**维护要点**:

- 版本化设计使上游 Excel 被打开占用时也不会取数失败——这是历史踩坑后的修复，勿改回直接覆盖
- 调度必须留在 :20，不要改回整点——FineBI 每小时 :53 会先删掉上一轮输出目录，新副本约 :02–:05 才落盘，整点取数正好撞空档（2026-09 曾因此每小时误报「未找到 incident_overview.xlsx」）；撞上空档时只要本地副本不超过 90 分钟就沿用上、不判失败

#### FineBI 报表文件同步（`finebi_report_sync`）

- 默认 cron: `10 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/finebi_report_sync.py → run_finebi_report_sync`

**功能**: 每小时从 FineBI FTP /webroot/WEB-INF/schedule 的每个子文件夹取最新一份 Excel，下载到本地 data/finebi_reports 供任务报告文件页下载；某个目录本轮没有 Excel 只记缺失，不把整任务判失败

**工作流与数据流**:

1. 每小时 :10 遍历 schedule 下每个子文件夹
1. 各取最新一份 Excel 下载到 data/finebi_reports
1. 目录本轮无文件且本机有历史副本 → 记入 missing 继续跑下一个
1. 「任务报告文件 → FINEBI report」页签展示与下载

**维护要点**:

- 2026-08-25 分组模式启用时曾因未归组而 pending 卡死断档，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP
- FineBI 每小时 :53 会先删掉上一轮输出目录、新副本约 :02–:05 才落盘，单个目录取不到文件是常态：只有本机连历史副本都没有才算 error，否则一个目录的空档会把其余已同步成功的报表一起拖红

#### 数据库数据新鲜度巡检（`db_freshness_check`）

- 默认 cron: `15 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/db_freshness_check.py → run_db_freshness_check`

**功能**: 每小时巡检远程 DB（db_writer_api）、本地回退库各表最新数据日期，以及本机文件型数据源（FTP 落盘的 Excel）的落盘年龄，滞后时输出调用链路与检查方向

**工作流与数据流**:

1. 每小时 :15 巡检远程库与本地回退库各表的最新数据日期
1. 同时按最新文件的落盘年龄判定本机文件型源（如事件总览的 incident_overview.xlsx）
1. 滞后时在执行日志输出调用链与排查方向

**维护要点**:

- 怀疑「某类数据停更」时先看它的执行历史，按给出的调用链排查，比翻任务列表快
- 取数任务"成功/失败"和数据"几小时没更新"是两件事：2026-09-30 事件总览滞后 2 小时却只表现为任务告警，因此文件年龄单独进巡检（FILE_CHECKS），新增文件型看板数据源时在这里补一条

#### MTTR/TT 宽表重建（`mttr_tt_sync`）

- 默认 cron: `40 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/mttr_tt_sync.py → run_mttr_tt_sync`

**功能**: 重建 mttr_tt 宽表（Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category 参考库），写本机 data/mttr_tt.sqlite3，供 MTTR 看板（日/周/月）

**工作流与数据流**:

1. 读本机参考库 data/excel_ds.sqlite3（Site ID→Site Category、Site Name→各制式小区数）
1. 经只读 API 读远端 Eflow_TT_FB 全量
1. 推导 Vender/MTTR1/MTTR2/MTTR_RANG_2H/Month/WK/Outage_Mins 后原子替换 data/mttr_tt.sqlite3

**维护要点**:

- 口径解析自 FineDB 数据集 4bc5a679，定义在 services/mttr_tt_sync.py 顶部；MTTR2 只在 0<MTTR1<48h 时非空
- 参考库 excel_ds.sqlite3 是从 my-finebi 固化的静态文件（114KB，2026-08-31 后未变）；FineBI 侧 Excel 数据集若更新需重新导出覆盖
- 2026-09-21 上线前该表由已退役 my-finebi 的手工 ETL 维护，无调度 → 冻结在 2026-08-31

#### Progress 宽表重建（`progress_sync`）

- 默认 cron: `50 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/progress_sync.py → run_progress_sync`

**功能**: 重建 progress 宽表（Eflow_TT_FB LEFT JOIN Eflow_WO_FB，复刻 FineBI Progress 计算列），写本机 data/progress.sqlite3，供 Progress / Progress V3 看板

**工作流与数据流**:

1. 经只读 API 读远端 Eflow_TT_FB 与 Eflow_WO_FB（按 WO No. 1:1 关联）
1. 逐行复刻 FineDB 数据集 4bc5a679 的 Progress 计算列（各环节 ORG/STATUS、FB_* 级联、ORG_Handler、Month、MTTR1/2、clear_null）
1. 原子替换 data/progress.sqlite3

**维护要点**:

- Duration(Hours)/SLA(%) 依赖「当前时间」，刻意不落库，组件 SQL 用 julianday('now','localtime') 实时算
- 口径在 services/progress_sync.py 的 _derive()；SWITCH 级联逐字移植，改动前先对照原脚本 TMP/etl_progress.py
- 2026-09-21 上线前该表由已退役 my-finebi 的手工 ETL 维护，无调度 → 冻结在 2026-08-31

#### 失败任务自动重试（`auto_retry_failed`）

- 默认 cron: `*/10 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/auto_retry.py → run_auto_retry_task`

**功能**: 每 10 分钟扫描：失败任务若数据缺口尚未被后续成功执行补上则自动重投（MAX_ATTEMPTS=2，超 24h 放弃）；漏跑任务在时效窗口内无任何执行记录时补投一次

**工作流与数据流**:

1. 每 10 分钟扫描最近 24 小时执行记录
1. 失败任务：先判断数据缺口是否已被后续成功执行补上，未补上且未超次数上限才重投
1. 漏跑任务：时效窗口内应触发却无任何执行记录时补投（15 分钟宽限）；邮件任务默认排除（归 EWS 补发）

**维护要点**:

- 重试不是「失败就重跑」——缺口已被补上就不重投；环境变量 AUTO_RETRY_* 可调

#### RAN CM 小区数据同步（`cm_data_sync`）

- 默认 cron: `30 8 * * *`　|　worker 组: **u**
- 工作流脚本: `services/cm_data/cm_data_export.py → run_cm_data_sync`

**功能**: 从 RAN UME 获取 GSM/UMTS/LTE/NR 小区配置数据，经 API 全量替换写入远程 db.sqlite3（cm_cell_data/cm_site_summary），本地仅保留一份最新 Excel

**工作流与数据流**:

1. 登录 RAN UME 按 services/cm_data/cm_flows.json 定义的流程导出小区配置
1. 经远程主机 API 全量替换 db.sqlite3 的 cm_cell_data / cm_site_summary
1. 本地仅保留一份最新 Excel

**维护要点**:

- 导出流程（flows/payload/moc）在 services/cm_data/cm_flows.json 维护；网管界面改版后优先检查这里

#### PG→SQLite 数据快照（`pg_to_sqlite_sync`）

- 默认 cron: `45 * * * *`　|　worker 组: **m**
- 工作流脚本: `backend/scripts/sync_pg_to_sqlite.py → main`

**功能**: 把远程 PostgreSQL 全库数据同步到本地 db/app.db 作为离线备份/回退快照

**工作流与数据流**:

1. 每小时 :45 全量同步远程 PG 到本地 db/app.db
1. app.db 兼作凭据表（credentials，明文）宿主

**维护要点**:

- app.db 里的业务表是「上一小时的镜像」，别在它上面做实时假设；也不要把它当垃圾删除（含凭据 + 快照，≈954MB）

#### MW UME KPI 同步（`mw_ume_kpi_sync`）

- 默认 cron: `15 5 * * *`　|　worker 组: **w**
- 工作流脚本: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync`

**功能**: MW UME（ZXMW 微波）KPI 历史指标同步（FINBI 模板 1 天粒度），内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation

**工作流与数据流**:

1. 每天 05:15 经 FINBI 模板导出 1 天粒度 KPI（内存处理，不落临时文件）
1. 按 Begin Time + 元素标识列联合去重后写主库 mw_ume_bw_ultilazation

**维护要点**:

- 微波拓扑看板一天只变一次（05:15 后）；表名 ultilazation 是历史拼写，勿改

#### MW UME KPI 实时同步（`mw_ume_kpi_sync_rt`）

- 默认 cron: `*/15 * * * *`　|　worker 组: **w**
- 工作流脚本: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt`

**功能**: MW UME KPI 实时同步（FINBI 模板 15 分钟粒度），每 15 分钟取最近 2 小时数据，直写 app.db 表 mw_ume_bw_ultilazation_rt

**工作流与数据流**:

1. 每 15 分钟经 FINBI 模板（gr=900）取最近 2 小时数据
1. 内存导出直写 mw_ume_bw_ultilazation_rt（覆盖窗口内槽位）
1. 微波实时看板默认只取最新一个 15 分钟槽位，滑杆可回看

**维护要点**:

- 与日粒度任务共用网管会话，同在 n 组串行；看板默认 900 秒自动刷新且支持软刷新

#### CN EMS KPI 缓存同步（`ems_kpi_cache_sync`）

- 默认 cron: `*/15 * * * *`　|　worker 组: **c**
- 工作流脚本: `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync`

**功能**: 每 15 分钟增量下载 CN EMS 当日（UTC）原始 PM 测量文件到本地 _pmcache（服务器仅保留约 1 天；只下载缺失文件不解析）

**工作流与数据流**:

1. 每 15 分钟经 SFTP 增量下载当日 UTC 原始 PM 文件
1. 只下载缺失文件，不做解析（轻量）
1. 落到本地 _pmcache 缓存

**维护要点**:

- CN EMS 服务器只保留约 1 天原始文件——本任务是把整天数据在服务端清理前抢回来的关键，不要停用

#### CN EMS KPI 日粒度CSV（`ems_kpi_daily`）

- 默认 cron: `20 0 * * *`　|　worker 组: **c**
- 工作流脚本: `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily`

**功能**: 聚合前一个完整 UTC 日的 CN EMS KPI 并生成 csv_out/<模板名>.csv（VLR/USSD/语音/位置更新/License/TDD/Data 订阅者 7 模板）

**工作流与数据流**:

1. 每天 00:20 UTC（北京 08:20）先 best-effort 补抓前一日窗口
1. 纯本地 _pmcache 缓存聚合（不再依赖服务端）
1. 按 Query_Template.xml + samples 公式输出 csv_out/<模板名>.csv，共 7 个模板

**维护要点**:

- 与缓存同步共享 _pmcache/daily_raw.json，同在 c 组串行保证互斥

#### CXO 看板数据缓存同步（`cxo_dashboard_cache_sync`）

- 默认 cron: `*/10 * * * *`　|　worker 组: **v**
- 工作流脚本: `services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync`

**功能**: 每 10 分钟经本机 8790 VMAX 代理拉取 CXO 看板全量接口，按接口粒度合并为 last-known-good 缓存（空值保留旧值），供看板兜底展示

**工作流与数据流**:

1. 每 10 分钟经 127.0.0.1:8790 VMAX 代理拉取 CXO 看板全部接口
1. 按接口粒度合并 last-known-good：某接口本轮取空只保留旧值，不把看板打成空白
1. 落盘 data/cxo_dashboard/last_known_good.json

**维护要点**:

- 2026-09-18 与另两个 8790 任务一起从 n 组拆到 v 组：同会话必须串行，但不再排在 sp_data_sync（1.5~2h）后面
- 上线时曾漏登记 GROUP_TASK_MAP → 队列 pending 卡死、看板停在旧日期（第四次踩坑）
- 8790 会话失效时本任务失败，而看板会继续用 last-known-good 展示（看着正常其实已停更）——以任务执行历史为准

#### VMAX CXO 天粒度日值归档（`vmax_cxo_daily_sync`）

- 默认 cron: `15 * * * *`　|　worker 组: **v**
- 工作流脚本: `services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync`

**功能**: 每小时经 8790 VMAX 代理按监控批量拉取最近 8 天的 1hour 明细（50 个指标压成 8 个多列请求），聚合为日值落盘，供页签化天粒度看板累积回看约三周

**工作流与数据流**:

1. 每小时 :15 按监控批量拉最近 8 天的 1hour 明细（6 个 CXO 趋势 + 14 个网络 KPI + 30 个服务/OTT KPI）
1. 按流量 SUM / 用户 PEAK / 速率 AVG 聚合为日值
1. 落盘 data/vmax_cxo_daily/daily.json

**维护要点**:

- 与 cxo_dashboard_cache_sync、vmax_multi_data_sync 共用 8790 单会话，同在 v 组串行
- 日值由小时明细聚合：错过几个小时可由 8 天窗口自动补回，无需人工回填

#### VMAX 多报表指标采集（`vmax_multi_data_sync`）

- 默认 cron: `45 * * * *`　|　worker 组: **v**
- 工作流脚本: `services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync`

**功能**: 每小时经 8790 VMAX 代理抓取 url.txt 记录的 vreport 报表（5GSA 流量 / 5GSA 视频）指标明细，落盘 latest.json 与 vmax_multi_data.sqlite3

**工作流与数据流**:

1. 每小时 :45 经 8790 代理请求 vreport 报表（sys_5gsa_traffic_ciservice / sys_5gsa_video_ciservice）
1. report_query 参数走 RSA 分块加密
1. 落盘 data/vmax_multi_data/<报表>_latest.json 与 vmax_multi_data.sqlite3（kpi_rows 明细 + sync_runs 运行记录）

**维护要点**:

- 2026-09-18 补登记分组前从未执行过（第四次踩坑），现与另两个 8790 任务同属 v 组
- 页面取的是 latest.json 快照，任务失败时页面仍显示上一次数据，不会报错

#### OLIB SOC 看板 KPI 增量（`olib_soc_kpi_daily_sync`）

- 默认 cron: `20 6 * * *`　|　worker 组: **m**
- 工作流脚本: `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync`

**功能**: 每日增量补齐 VMAX 90 天经营看板的 KPI 库（daily_kpi 表）：只跑 7 个看板块，只取缺的日期 + 重取最新 1 天，不出 Excel

**工作流与数据流**:

1. 每天 06:20 直连 VMAX 数仓 GBase（10.123.255.12:5258，库 zxvmax）
1. 只跑流量/活跃用户/缓存/视频/游戏/TCP/TOP 业务 7 个块
1. 只取缺失日期 + 重取最新 1 天（默认回看 7 天，幂等自愈），写 data/olib_soc_report/olib_soc_report.sqlite3 的 daily_kpi

**维护要点**:

- 数仓分区只保留约 90 天，回看窗口必须落在保留期内
- GBase 不可达时本任务失败；链路恢复后 days_back=7 会自动补齐断档，无需人工回填
- 上线时漏登记分组→ 90 天看板停在旧日期（2026-09-18 补录 m 组）

#### OLIB SOC VMAX 例行报表（`olib_soc_vmax_report`）

- 默认 cron: `30 7 1 * *`　|　worker 组: **m**
- 工作流脚本: `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report`

**功能**: 直连 VMAX 数仓 GBase 按日分区跑 notebook 移植的 9 段 SQL，生成多 sheet Excel 与运行记录；默认出上一个自然月

**工作流与数据流**:

1. 每月 1 日 07:30 直连 GBase 按日分区跑 9 段 SQL（traffic/Active_user/cache/GUW/Video/game/TCP/TOP 业务/TOP 视频）
1. 生成多 sheet Excel 与运行记录，默认窗口为上一个自然月（可配 last_n_days/weekly/explicit）
1. 窗口自动截断到数仓约 90 天保留期内

**维护要点**:

- 低频任务（每月一次）：健康巡检按 cron 间隔判定，不会因为“24h 没跑”被误报
- 配置在 services/olib_soc_report/ 的 json（range_mode/days/mail.enabled）；GBase 口令走凭据分组 vmax_gbase

#### 客户业务 KPI 同步（`ume_in_kpi_sync`）

- 默认 cron: `45 5 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync`

**功能**: 从 UME 门户 172.17.208.1:28808 抓取 Dong customer 周期业务 KPI（IVR/P4M/VC/USSD/PPS/CPU/Memory 共 7 个模板，1 天粒度，默认回看 7 天），直写主库表 ume_in_customer_kpi

**工作流与数据流**:

1. 每天 05:45 登录 UME 门户抓 7 个模板的 1 天粒度 KPI
1. 内存导出不落盘
1. 直写主库表 ume_in_customer_kpi（Begin Time + KPI + NE + SERVICE 联合去重）

**维护要点**:

- 与其它网管类任务同在 n 组串行
- 默认回看 7 天幂等：门户侧延迟出数会自动补回

#### 客户业务 KPI + OSG 周报邮件（`ume_in_osg_report`）

- 默认 cron: `30 6 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）`

**功能**: 每天早上分步执行：先做一次 ume_in KPI 同步，再按 ume_in_customer_kpi 最新 7 天生成 OSG Weekly QoS Analysis Report Excel，最后把该 Excel 作为附件发给 djoumene.reussite1@zte.com.cn（抄送 dong.xinmin@zte.com.cn）

**工作流与数据流**:

1. 06:30 ① 调 ume_in_kpi_service.run_ume_in_kpi_sync() 同步 7 个模板到 ume_in_customer_kpi（与 ume_in_kpi_sync 同一门户会话）
1. ② 调 services/ume_in/t_osg_build.py 取表里最新 7 天填充 OSG 模板，产出 data/in_data/OSG Weekly QoS Analysis Report_<起>_<止>.xlsx（图表/条件格式/样式不动；派生列按原模板公式写入公式+缓存值：PPS 的 C/E/J、USSD 的 C/E/I、VC 的 H、IVR 的 E）
1. ③ 附件经 Orange EWS 发给主送 djoumene.reussite1@zte.com.cn、抄送 dong.xinmin@zte.com.cn

**维护要点**:

- 与 ume_in_kpi_sync 同组 n 串行：同一步骤共用 UME Dong 门户单会话
- 第 1 步同步失败即中止，不会把上一窗口的旧数据当新报告发出去
- 收件人可在 Settings → Email Recipient Settings 的 ume_in_osg_report 组覆盖；产物只保留最近 10 份

#### SP Online 工单同步（`sp_online_sync`）

- 默认 cron: `35 */6 * * *`　|　worker 组: **n**
- 工作流脚本: `services/sp_online_sync.py → run_sp_online_sync`

**功能**: 每 6 小时从 eFlow SP 接口拉在线工单（sp-outbound / sp-inbound / sp-transfer），写库表对应三张表。取「原始 filter」与「状态全集 filter」两份结果的并集，避免 filter 与其返回结果自相矛盾时静默取错数据。表语义=上游当前快照：全量重建，删除上游已消失的单据

**工作流与数据流**:

1. 每 6 小时 :35 请求 eFlow SP 三个接口，同一接口用原始 filter 与状态全集 filter 各拉一次
1. 两份结果按 woId 合并去重后写库表 sp_outbound / sp_inbound / sp_transfer
1. 全量重建：upsert 后删除表中不在本轮 woId 集合里的行（表=上游快照）；拉取不完整时只 upsert、不删除
1. 返回行的状态若全不在 filter 枚举内则告警（过滤条件与结果自相矛盾）
1. 「表浏览器」可直查；sp_online_report_generate 的 Outbound 支路直接消费 sp_outbound 表

**维护要点**:

- 上游账号走 eflow 凭据分组；eFlow 会话被踢时表现为该组任务连续 failed，由 auto_retry_failed 兜底
- 2026-09-30 由「原始 filter 取到 0 行才回退全集」改为取并集：旧判据会把「该 filter 本就没有匹配」误判成「filter 坏了」，inbound 因此把「查在途」变成了「查历史关闭单」（282 行全 Closed）且无告警
- 实测上游并不真正遵循 filter 的收窄语义（inbound 用 4 个在途态与 15 态全集请求返回同一份数据），故不要依赖 filter 精确性
- 2026-10-09 增加全量重建：旧实现只 upsert 从不删除，上游已消失的单据会永久残留（sp_outbound 积了 37 条僵尸 WaitingForUpdate，被 sp_online 报表原样呈现）。安全阀：仅当端点两份 filter 全部成功且结果非空才删除，否则退化为只 upsert

#### SP 物料主数据同步（`sp_material_sync`）

- 默认 cron: `55 4 * * *`　|　worker 组: **n**
- 工作流脚本: `services/sp_material_sync.py → run_sp_material_sync`

**功能**: 从 eFlow SP 物料接口（eflow-sp-material）拉全量物料主数据，按 materialNo 唯一键 upsert 写 app.db 表 sp_material。表语义=上游当前快照：全量重建，删除上游已消失的物料

**工作流与数据流**:

1. 每天 04:55 拉 eflow-sp-material 全量物料主数据
1. 按 materialNo upsert 写 app.db 表 sp_material
1. 全量重建：删除表中不在本轮 materialNo 集合里的行（表=上游快照）；拉取不完整时只 upsert、不删除
1. 「表浏览器」可查，下游 sp_material_report 出库存与消耗报表

**维护要点**:

- 下游 sp_material_report（07:45）只读表不拉接口：本任务停更时邮件仍会正常发，但内容是旧数据（db_freshness_check 已覆盖 sp_material 新鲜度）
- 2026-10-09 增加全量重建：旧实现只 upsert 从不删除，上游停用/删除的物料会永久残留（与 sp_online 同型）。安全阀：仅当 fetch_all 完整拉取（未达 MAX_PAGES 上限、非 0 行）才删除，否则退化为只 upsert

#### SP 在线未关闭单报表生成（`sp_online_report_generate`）

- 默认 cron: `0 6 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_online_report_generate`

**功能**: 生成 sp_online 下未关闭单报表（PNG+XLSX，Create Time 倒序）：Inbound 读明细 xlsx 未关闭单，Outbound 读库表 sp_outbound 跟踪 WaitingForUpdate / WaitingForReturn / WaitingForConfirm

**工作流与数据流**:

1. 每天 06:00 生成 data/sp_email/sp_online 的 Inbound/Outbound 报表（PNG + XLSX）
1. Inbound：读 data/sp_email/data 最新 inband_details.xlsx，过滤未关闭单
1. Outbound：读库表 sp_outbound（sp_online_sync 每小时拉 eFlow），取等待更新/等待归还/等待确认三类在途单

**维护要点**:

- 纯生成不发信，发送由 06:20 的 sp_online_report_send 负责——两者拆开后重跑发送不必重新取数
- Outbound 曾读 SFTP 明细 xlsx，因该导出不含 WaitingForUpdate（等待更新）而于 2026-09-30 改读库表 sp_outbound，见 sp_report_gen/README.md

#### SP 在线未关闭单报表发送（`sp_online_report_send`）

- 默认 cron: `35 6 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_online_report`

**功能**: 发送 sp_online 未关闭单报表：邮件（PNG 内嵌 + XLSX 附件，默认复用 SP 报表远程名单）+ WhatsApp 群

**工作流与数据流**:

1. 每天 06:35 取 sp_online 最新报表文件
1. 邮件：Inbound/Outbound PNG 内嵌 + XLSX 附件
1. 同时经 whatsapp_dispatch（Baileys → Playwright）发到 WhatsApp 群，收件人可在「系统设置 → 邮件收件人」覆盖

**维护要点**:

- 依赖 06:00 的 sp_online_report_generate 产物，上游缺文件时本任务直接失败
- 属邮件类任务：默认不参与漏跑补投，EWS 恢复后由 email_recovery 补发
- 本任务在 EMAIL_TASK_IDS 内：WhatsApp 失败时 error 只写固定标记，不拼底层异常原文（避免命中 EWS 关键字触发邮件重复补发）
- 2026-10-11 起 WhatsApp 侧走「Baileys → Playwright」双通道；发送者变为 Baileys 副号

#### eFlow 告警规则收集（`eflow_alarm_rules_collect`）

- 默认 cron: `59 23 */3 * *`　|　worker 组: **n**
- 工作流脚本: `services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules`

**功能**: 每 3 天 23:59 从 eFlow 拉取规则类型目录与告警关联规则（correlation-mgt），导出 eflow_alarm_rules.xlsx

**工作流与数据流**:

1. 每 3 天 23:59 拉 eFlow 规则类型目录与告警关联规则（correlation-mgt）
1. 导出 backend/services/eflow_rules/eflow_alarm_rules.xlsx（Alarm_Rules + Rule_Types 两个 Sheet）

**维护要点**:

- 低频任务（每 3 天）：健康巡检按 cron 间隔判定，不会因“24h 未执行”被误报
- 导出的 xlsx 是下游规则比对的输入，属代码资产，不要手工改动

#### eFlow 推单规则收集（`eflow_push_rules_collect`）

- 默认 cron: `59 23 */3 * *`　|　worker 组: **n**
- 工作流脚本: `services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules`

**功能**: 每 3 天 23:59 从 eFlow config-center 拉取全部规则（推单/升级/分组/自动关闭等 28 种类型），逐条合并 detail 后导出 eflow_push_rules.xlsx

**工作流与数据流**:

1. 每 3 天 23:59 以 query filter="" 拉 config-center 全部规则（28 种类型）
1. 逐条合并规则 detail
1. 导出 backend/services/eflow_rules/eflow_push_rules.xlsx（Push_Rules + Rule_Type_Summary）

**维护要点**:

- 低频任务（每 3 天），与告警规则收集同组同周期
- 与 eflow_tt_rules_check 用的规则表同处 services/eflow_rules/，目录与文件名不要改名

#### eFlow 推单规则检查（`eflow_push_rules_check`）

- 默认 cron: `10 5 * * 2`　|　worker 组: **n**
- 工作流脚本: `services/eflow_rules/eflow_push_rules_check_task.py → run_eflow_push_rules_check`

**功能**: 每周二 05:10：先用最新推单规则（ttPushOrderRule / 触发步骤 FOAccept）批量评估最新 1000 条 eflow_tt，逐单比出「规则判定」与「实际派单」是否一致，并留周快照供跨次对比

**工作流与数据流**:

1. 子进程跑 eflow_Push_Rule_Collector 刷新 eflow_push_rules.xlsx（失败则降级用已有规则）
1. 取与 eflow_tt_rules_check 同一批样本（created_time 最新 1000 条、alarm_code 非空）
1. 按 FOAccept 推单规则逐单判定：命中规则 / 是否建 WO / 目标处理人 / 推送路径
1. 解析实际派单（wo_no + fo_accept_detail 的 Operator / Assignee Group）
1. 分类为 一致 / 不一致 / 无法判定 / 无规则适用，导出 xlsx 并在 push_rules_snapshots/ 留快照

**维护要点**:

- 样本口径必须与 eflow_tt_rules_check 保持一致，否则两个页签的「总 TT」会对不上
- 与 eflow_push_rules_collect 同组（n）：两者登录同一 eFlow 账号，跨组并发会互踢会话
- 规则表「历史建 WO 率」用 Python 侧算好的截止时间传参 —— datetime('now') 只有 SQLite 有
- 快照只保留最近 10 份（_SNAPSHOT_KEEP），如需长期留存请另存

#### WhatsApp 知识库同步（推单规则）（`whatsapp_kb_sync_push_rules`）

- 默认 cron: `4 0 */3 * *`　|　worker 组: **n**
- 工作流脚本: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_push_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**功能**: eFlow 推单规则收集完成后触发：比对规则 xlsx 指纹，有变化才重导知识文档、重建索引并重启 whatsapp-kb-bot

**工作流与数据流**:

1. 比对四份规则 xlsx 的 size+mtime 指纹
1. 无变化直接退出（不重启 bot，避免与提问竞态）
1. 有变化时执行 export-kb → ingest → 重启 bot → 核对索引一致

**维护要点**:

- 幂等设计：绝大多数轮次什么都不做，不会频繁重启 bot
- 指纹只覆盖规则 xlsx；手改 knowledge/ 下的 md 不会被发现，靠 @bot ping 的「磁盘知识比索引新」告警兜底
- 同一批规则还有实时通道（带 TT 单号提问）直接读 xlsx，不走本任务也不会答错

#### WhatsApp 知识库同步（告警规则）（`whatsapp_kb_sync_alarm_rules`）

- 默认 cron: `4 0 */3 * *`　|　worker 组: **n**
- 工作流脚本: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_alarm_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**功能**: eFlow 告警规则收集完成后触发知识库同步；告警压缩规则来自 eflow_alarm_rules.xlsx，无变化自动跳过

**工作流与数据流**:

1. 比对规则 xlsx 指纹
1. 有变化时重导 TT单-告警压缩规则.md 并重建索引、重启 bot
1. 无变化直接退出

**维护要点**:

- 与推单规则同步共用同一套 sync-kb.mjs 逻辑，只是触发时机不同
- 压缩规则影响「某个告警码会压缩成什么」这类知识库问答

#### WhatsApp 知识库同步（TT 级别规则）（`whatsapp_kb_sync_tt_rules`）

- 默认 cron: `35 4 * * *`　|　worker 组: **n**
- 工作流脚本: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_tt_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**功能**: eFlow TT 级别规则收集（每日 04:20）完成后触发知识库同步；级别规则来自 eflow_TT_rules.xlsx

**工作流与数据流**:

1. 04:35 触发（比 04:20 的规则采集晚 15 分钟，确保 xlsx 已落盘）
1. 比对指纹，有变化才重导 TT单-级别判定规则.md 并重建索引、重启 bot

**维护要点**:

- 级别规则每天采集一次，所以本任务也是每日节拍
- 无变化时不做任何事，不会每天重启 bot

#### 日志文件清理（`log_cleanup`）

- 默认 cron: `17 3 * * *`　|　worker 组: **m**
- 工作流脚本: `services/log_cleanup.py → run_log_cleanup`

**功能**: 每天清理 my_app/log 下超过保留期（默认 7 天，LOG_RETENTION_DAYS 可调）的日志，并把已无进程写入的旧命名日志补上日期后缀

**工作流与数据流**:

1. 每天 03:17 扫描 log/ 下符合日志特征的文件
1. 删除超过保留期的（LOG_CLEANUP_DRY_RUN=1 只报告不删）
1. 给已无进程写入的旧命名日志补日期后缀，与各 watchdog 的按日期命名配合滚动保留

**维护要点**:

- Windows 下被进程占用的日志无法外部重命名/删除，只能由写入方按日期分文件——这就是日志名带日期的原因
- db/app.db（含凭据表）、backend/services/auth_cache/、data/ 下任务产物不在清理范围

#### TMP 目录清理（`tmp_cleanup`）

- 默认 cron: `47 3 * * *`　|　worker 组: **m**
- 工作流脚本: `services/tmp_cleanup.py → run_tmp_cleanup`

**功能**: 两段式回收 my_app/TMP 下超过保留期（默认 7 天）的临时产物：先同盘移进 TMP/_quarantine_YYYYMMDD/（可还原），隔离再满 7 天才真删

**工作流与数据流**:

1. 每天 03:47 扫描 TMP/ 下超过保留期的条目
1. 同盘 mv 进 _quarantine_<日期>/ 隔离（不直接删，留一次反悔机会）
1. 隔离期满 7 天后彻底删除；服务在用路径按 WHITELIST 跳过

**维护要点**:

- TMP/ 是临时产物的固定去处，但体积没人管（上线首日实测 462MB）——清理是必需的
- charts/dl/状态文件等服务在用路径在 WHITELIST 里，永不处理；新增此类路径要补白名单
- 与 log_cleanup（03:17）错峰，避免同一时段两次全盘扫描

#### TTs and MTTR 报表生成（`tt_mttr_report_generate`）

- 默认 cron: `20 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/tt_mttr_report.py → run_tt_mttr_report`

**功能**: 从最新一份 Site Down hourly Report 生成 TTs and MTTR (Hour) 月粒度工作簿，供邮件报告页「TTs and MTTR」页签下载

**工作流与数据流**:

1. 每天 07:20 读 data/eflow/tt_reports 下最新的 hourly Report（Processed Data 页）
1. 筛出有 WO 的工单进 Raw Data，再按「告警发生→告警清除历时 < 48 小时 + Site Category 非空 + 告警月份 ≥ 2026-01」进 ZTE 页
1. Summary 页用 COUNTIFS/AVERAGEIFS 公式分月统计 P1~P4 的 TTs 与 MTTR，并插 4 张组合图（柱=TTs、青线=MTTR、红线=SLA 目标）
1. 产物文件名带时间戳，同目录只保留最新 1 份：新报告写出后自动删掉旧的

**维护要点**:

- SLA 达成一律按「告警发生 → 告警清除」的实际历时算，不看源表的 SLA Time 目标列（那是目标值不是耗时）
- 未填 Ticket Severity 的工单单列 N/A 块统计，不出图（无 SLA 目标），否则这部分工单会被静默丢掉
- MTTR 纵轴上限交给 Excel 自动缩放：超标月份（如 P1 2026-05 的 16.37h）不能被裁掉
- 口径改动前先跑一次并把 Summary 与 pandas 独立复算对拍；产物不在 _cleanup_old_tt_reports 的清理名单里，靠本任务自己的 KEEP_FILES 控制体积

#### RAN 用户身份清单（VoLTE/N78）（`gp_ran_user_sync`）

- 默认 cron: `20 13 * * *`　|　worker 组: **g**
- 工作流脚本: `services/gp_ran/gp_ran_sync.py → run_gp_ran_user_sync`

**功能**: 经 control1 两跳 SSH 到 RAN Greenplum，以 gpadmin 跑 psql，取最近 7 个完整 UTC 日的 VoLTE / N78 去重 IMSI 清单，落成 CSV 并记录计数；全程只读，数仓侧不落盘

**工作流与数据流**:

1. 每天 13:20 UTC 连 control1（10.100.29.12:22），在它上面开一条 direct-tcpip 通道转发到数据库主节点 193.168.0.6:22
1. 主节点上 sudo -S → su - gpadmin → psql（库 netmaxdb），SQL 以 base64 传输避开三层 shell 的引号嵌套
1. 窗口取 [今天-7, 今天) 的完整 UTC 日，不含仍在累积的当天；两个口径各跑一次 COPY ... TO STDOUT WITH (FORMAT csv, HEADER true)
1. CSV 原子写入 backend/data/gp_ran/（volte_起_止.csv / n78_起_止.csv），旁路 sqlite 只记计数与路径，只读守卫拒绝任何写语句与 TO PROGRAM

**维护要点**:

- 口令在「设置 → 凭据管理」的 gp_ran_control 分组；gp_ran_master 留空即自动复用同一口令，不要抄成第二份
- cron 定在 13:20 UTC 是因为实测数仓落库延迟约 10.5 小时（16:11 UTC 时最新记录才 05:44 UTC），「昨天」要到约 10:30 UTC 才完整；提前跑会静默少一天
- D023 是 IMSI（618=利比里亚 MCC，15 位）不是电话号码；要 MSISDN 必须另找关联表，别把这份清单当可拨打号码交付
- 明细里 85% 的 D023 为空，SQL 已加 D023 <> '' 排掉；现场人工语句没有这一条，照抄会多出一个空值
- 现场给的 volte 语句缺括号：C031=1 OR C032=1 OR C033=1 AND 时间窗 会被解析成时间窗只管 C033，等于全历史。本任务已补括号，**不要改回去**（VoLTE 覆盖 98% 属预期，需求方 2026-10-19 确认）
- 这套 psql 是 9.4 / Greenplum 6，不认 --csv（那是 PG 12 才有的）；CSV 必须由 COPY ... TO STDOUT 产出
- L_T216 按 D027 做 12 小时一个分区，最早分区约 62 天前，窗口天数（GP_RAN_WINDOW_DAYS，默认 7）超过就没有数据了
- 换机房只改环境变量 GP_RAN_CONTROL_HOST / GP_RAN_MASTER_HOST / GP_RAN_DB，不要改代码；主节点 IP 可在 control1 上 cat /home/gpadmin/paas_hosts_master.cc 查到
- 链路诊断：python -m backend.services.gp_ran.gp_ran_check --check（逐层打印两跳、sudo、psql、表与分区）

### 3.4 可靠性机制（超时 / 重试 / 自愈）

| 机制 | 说明 |
| --- | --- |
| **僵尸 running 回收** | 无 per-task 超时（设计缺口）。worker 每 300s 扫描：running 超 30 分钟（STALE_RUNNING_SECONDS）且 PID 已死亡的记录按失败回收。 |
| **失败自动重试** | auto_retry_failed 每 10 分钟扫描：失败任务先判断数据缺口是否已被后续成功执行补上，未补上且未超 MAX_ATTEMPTS=2 才重投；超过 24h 硬上限直接放弃。 |
| **漏跑补投** | 时效窗口内应触发却完全没有执行记录的任务自动补投一次（MISS_GRACE_MIN=15 宽限；邮件类默认排除，由 EWS 补发机制负责）。 |
| **陈旧 pending 过期** | pending 超 6 小时无人认领（典型原因：漏登记 worker 分组）会被置 failed 并补写执行日志，释放被它占住的单飞名额，让下一次调度能正常入队（否则一条陈旧记录会挡住该任务之后的每一次调度）。 |
| **失败通知** | 任务失败经微信 + 邮件双通道告警（services/weixin_notifier.py 支持 openclaw/wecom/serverchan/pushplus）。 |
| **漏跑/停摆主动告警** | db_freshness_check 每小时算四类健康异常（未归组 / 超出周期无执行记录 / 队列滞留 / 上次成功后逾期无新成功），由 services/task_health_alert.py 按「新异常通知一次、恢复通知一次、持续超 24h 再提一次」推微信+邮件，不必等看板没数据了才人工发现（2026-09-18 上线）。 |
| **进程自愈** | backend_watchdog / worker_watchdog 托管进程：端口探活、崩溃退避重拉（backend 连崩 10 次降级为每 5 分钟慢速重试、不再放弃；worker 仍是连崩 10 次摘除不再拉起）；心跳 log/heartbeat_*.json 超 3 分钟未更新判定 hung 强杀重拉。 |
| **保留期** | task_queue 与 task_execution_log 保留 3 天（task_runner.py / worker.py 自动清理），无需手工。 |

### 3.5 任务维护指南

**改排程（cron）** 「任务管理 → 排程」弹窗修改，写入主库 task_schedule_config 表，立即生效、重启不丢；无需改代码。

**改业务参数** 「系统设置 → 任务配置」页签（注意在系统设置里，不在任务管理页）。优先级：环境变量 > 配置文件 > 默认值。

**改上游账号口令** 「系统设置 → 凭据」选分组更新，点「测试连接」验证（凭据明文存于 db/app.db 的 credentials 表，缓存 30s）。

**改收件人** 「系统设置 → 邮件收件人」分组编辑，可重置默认；改完对所有 kpi_* / *_email 任务生效。

**手动执行 / 停止** 任务管理页「执行」立即投递一次、「停止」中断长任务。验证新排程/新脚本后应先手动跑一次看执行历史。

**新增一个任务** ① task_registry.py 的 TASK_SPECS 追加声明（task_id/name/cron/loader）；② worker_watchdog.py 的 GROUP_TASK_MAP 登记分组（漏了永远 pending，已四次踩坑；tests/test_worker_group_coverage.py 交叉校验 task_id 覆盖与两处组集合一致）；新建组则必须同步 GROUP_TASK_MAP 键与 start_hidden.ps1 的 MY_APP_WORKER_GROUPS、$groups 两处（restart_workers.py 的 ALL_GROUPS 自动取自 GROUP_TASK_MAP）；③ 业务函数放 backend/services/ 且抛异常不吞；④ stop.bat → start.bat 重启加载注册表（只改分组清单则 python restart_workers.py --mode watchdog --force，**要管理员权限**）；⑤ 手动执行验证并更新文档（04-task-system.md 清单与本帮助数据 helpTaskDocs.ts，改完跑 npm run docs）。

**改工作流脚本** 脚本都在 backend/services/ 下（任务清单有对应路径）。改动时注意：① 别改历史拼写名（packet_lost、battary_kpi_fetch、ultilazation 等，多处按字符串引用）；② 动态采集表不进 Alembic；③ 同步更新 task_registry.md / WORKER.md / 本帮助数据（frontend/src/pages/helpTaskDocs.ts）。

**任务卡 pending / failed 排查顺序** ① pending 不动 → 查是否漏分组；② failed → log/worker_runtime*.log（每组 worker 一个文件）找 task_id 堆栈 → 凭据「测试连接」；③ 数据停更 → db_freshness_check 的执行历史有调用链。

### 3.6 上游不可用时怎么表现

| 上游异常 | 表现 | 自愈手段 |
| --- | --- | --- |
| eFlow / 各 UME 会话被踢 | 该组任务连续 failed | auto_retry_failed 每 10 分钟重试；凭据「测试连接」验证账号 |
| Exchange (EWS) 挂了 | 邮件任务失败、报表漏发 | email_recovery 恢复后自动补发近 3 小时失败邮件 |
| 远程主机不可达 | 写库/上传失败、新鲜度巡检告警 | db_freshness_check 输出调用链与检查方向；查「系统设置 → 远程主机」连通性 |
| FineBI 文件被占用 | （历史问题）取数失败 | 已改为版本化文件 + current.json 指针，被打开也不会失败 |
| CN EMS 服务端清理原始文件 | 当日 KPI 缺失 | ems_kpi_cache_sync 每 15 分钟增量缓存抢在清理前保住数据 |

---

## 4. 页面指南

所有页面可用 `?page=<key>` 直链打开，例如 `http://<host>/myapp/?page=battery`；或右键菜单项「在新标签页打开」。标注 iframe 的页面实际界面在 `frontend/public/*.html`，样式与 React 页面略有差异。

### 4.1 任务与数据

#### 任务管理（`sync`）

全站控制中心：查看所有定时同步/采集任务的状态与排程，手动执行、停止、启停、修改 cron 排程，查看执行历史与按天失败聚合。详见本页「任务管理详解」。

- 数据没更新时第一个打开这里：点统计卡即筛选，用「失败聚合」排查昨天夜里哪些任务挂了
- 单任务「排程」弹窗修改 cron（写入 task_schedule_config，持久化，重启不丢）
- 「统一开关」一键启用/禁用全部任务；**你手动关掉的任务会被跳过**，卡片上标「手动停止」，要重开请单独点它的开关
- 「全局历史」跨任务检索执行记录；任务完成后语音播报可在本页开关

#### 任务报告文件（`email_reports`）

汇总四类任务产物并供下载：邮件发送的最新报告附件、FineBI FTP 报表、eFlow 规则检查结果、TTs and MTTR 月粒度报表。eFlow 页签底部列出**从 eFlow 获取的全部规则表**（TT 级别矫正规则 / 告警关联规则 / 推单·配置规则）与本次检查产物（级别矫正表 / 匹配报告）。

- 顶部页签切换类别，点文件名或「下载」保存；可设每类保留最近 N 份
- eFlow 页签三个「立即…」按钮分别手动触发对应任务：立即检查（TT 规则 + 匹配矫正）、收集告警规则、收集推单规则；触发后 3 秒自动刷新一次，任务慢时需手动再刷
- eFlow 页签底部表格：蓝色标签为规则表（TT 规则随每日 04:20 检查刷新；告警/推单规则原本每 3 天 23:59 刷新，可用上面的「收集…」按钮随时刷新），灰色为本次检查产物
- 「TTs and MTTR」页签的「立即生成」投一次 `tt_mttr_report_generate`（定时为每天 07:20，要更高频在任务管理页改排程），页面按文件生成时间轮询，出现更新的文件才提示「报告已生成」；口径：有 WO + 告警发生→告警清除历时 < 48 小时 + Site Category 非空 + 告警月份 ≥ 2026-01

#### 数据上传（`upload`）

拖拽 Excel/CSV 入库，并给出数据质量评分。

- 拖文件到上传区即可；上传后先看「问题面板 / 结论面板」再决定用不用这批数据
- 历史列表可手动刷新

#### 表浏览器（`tables`）

表浏览器：不写 SQL 就能翻看任意表、看字段画像、导入导出，是最常用的兜底工具。

- 表下拉选表 → 分页浏览，关键字搜索防抖；导出 xlsx / CSV
- 列显隐可保存为视图模板（同一张表常看固定几列时先存模板）
- 「画像」页签查看字段级统计；支持 Excel/CSV 导入

#### 数据总览（`overview`）

数据库体检页：库内有多少张表、每张表多少行、Top10 规模排名。

- 「行数」列可排序；页面只读——只回答「数据在不在、大不大」

### 4.2 监控看板

#### 实时告警看板（`alarm`）

全网当前活跃告警的综合视图：总量、级别、站点等多维统计与趋势。

- 点任意数字弹出可搜索的下钻明细表
- 「实时」数据来自 eFlow 活动告警（eflow_active_alarm 每分钟同步），并非秒级推送

#### TT&WO 看板（`ttwo`）

故障工单（TT）与工作单（WO）的处理量、时效、积压趋势分析。TT 统计的三个维度（工单严重度 / SLA 状态 / 工单状态）都用数字卡片，点卡片下钻；MTTR 趋势按 Ticket Severity（P1/P2/P3/P4）拆成 4 张图，每张图是「柱 = TT 数量 + 线 = MTTR」双轴，并用页签切 日 / 周 / 月 三档粒度。默认时间窗近 30 天。

- 下拉 + 分段控件 + 日期区间组合筛选，点卡片或图上的点下钻明细；默认时间窗为近 30 天（周/月粒度在 7 天里只剩一两个桶，看不出趋势）
- 「全部归属」可切 ZTE / 3rd：WO 编号非空 = ZTE（我方派单），为空 = 3rd（第三方处理）
- 「高级过滤」按钮展开站点维度筛选（区域/省县/网络制式/站点类型/VIP/TRM/主管/FME/供电方式/供电厂商/站点等级），选项来自站点表
- TT 统计卡片上的占比，分母是**该维度自身**的合计（看这一个维度内部的构成），不是 TT 总数
- MTTR 趋势上方页签切 日/周/月：三档一次加载，切换即时；周上的 TT 数量就是该周 7 个日点的合并，可互相印证
- 每张 MTTR 图是双轴：柱子是「该时段该级别的 TT 单数」（左轴），折线是「MTTR 分钟均值」（右轴）。某时段该级别没有单时柱和线都不画，不是 0（「没有单」与「MTTR 为 0」是两回事）
- 柱高与线高不是同一量纲：柱子看「量」，折线看「快慢」。线的样本量少时均值会跳，悬停提示里会补一句「其中 N 单计入 MTTR」说明实际参与计算的有多少单
- 四张图的悬停提示与缩放（滚轮/底部滑杆）联动，拖任一张另外三张同步；日粒度点数多时会自动出现缩放条
- 点图上任意点可下钻该时段的工单明细
- 页头显示数据最近同步时间；数据来自 eFlow 每小时同步（eflow_sync）与每日全量兜底（eflow_sync_full）

#### TT&WO 看板（v1·仅上半部分）（`v1_ttwo`）

TT&WO 看板的「只保留上半部分」版：渲染到「MTTR 趋势」（含标题、日/周/月页签，每档四张「柱=TT 数量 + 线=MTTR」双轴分级图）为止，即 汇总卡（TT 总数 / WO 总数 / WO 编号唯一）+ TT 统计（工单严重度 / SLA 状态 / 工单状态，均为数字卡片）+ MTTR 趋势（P1/P2/P3/P4 × 日/周/月）；其下的领域与根因分析、工单分析、站点信息三个区块整体不出。默认时间窗近 30 天。

- 筛选条（含全部归属 ZTE/3rd 与高级过滤）、MTTR 日/周/月页签与双轴图、卡片下钻明细与导出与 TT&WO 看板完全同源（共用 /tt-wo-dashboard/overview 端点），用法一致、数字必然相同
- 直链 http://<host>/myapp/?page=v1_ttwo；完整版见 page=ttwo

#### TT 看板（`tt`）

TT&WO 看板的「只看 TT」版（数据源 eflow_tt）：汇总卡只留「TT 总数」→ 统计（严重度 / SLA 状态 / 状态，均为数字卡片，点卡下钻）→ MTTR 趋势（P1/P2/P3/P4 × 日/周/月，每张图为「柱=TT 数量 + 线=MTTR」双轴）。MTTR 趋势之下的下半部分整体不出：领域与根因分析、工单分析（按来源统计 WO / 按状态统计 WO）、站点信息；WO 总数 / WO 编号(唯一) 两张汇总卡也不出。默认时间窗近 30 天。

- 分区标题为「统计」，严重度维度标题为「严重度」（完整版 TT&WO 看板上仍叫「TT 统计」「工单严重度」）
- MTTR 趋势每张图是双轴：柱子（中兴蓝 #0072BC）是「该时段该级别的 TT 单数」，折线（橙色）是「MTTR 分钟均值」。四张图的柱/线颜色固定不变 —— 级别由图本身（P1/P2/P3/P4 四张图）区分，颜色只用来分「量」与「时长」这两个量纲。某时段该级别没有单时柱和线都不画，不是 0
- 筛选条（含全部归属 ZTE/3rd 与高级过滤）、卡片下钻明细、页面级 Excel 导出与 TT&WO 看板完全同源（共用 /tt-wo-dashboard/overview 端点），数字必然相同；导出文件名前缀为 TTWO_tt_
- 直链 http://<host>/myapp/?page=tt；完整版见 page=ttwo，只看 WO 见 page=wo（版式与本页相同，数据源换成 eflow_wo）

#### WO 看板（`wo`）

TT 看板的「WO 数据源」版：版式与 page=tt 逐块一致，只是数据来自 eflow_wo。汇总卡只留「WO 总数」→ 统计（严重度 / SLA 状态 / 状态）→ MTTR 趋势（P1/P2/P3/P4 × 日/周/月双轴图）。MTTR 趋势之下的下半部分（领域与根因分析、工单分析、站点信息）与 page=tt 一样不出。默认时间窗近 30 天。

- 点统计卡片或 MTTR 图上的点，弹出可搜索的 WO 明细下钻表
- SLA 状态取自关联的 TT（eflow_wo 没有该列，SLA 属 TT 侧概念）：按 wo.tt_no = tt.tt_no 关联，关联不上的计入 Unknown，所以各卡片之和 = WO 总数
- MTTR 用的是 WO 自己的 alarm_occur_time / alarm_clear_time，所以本页的 MTTR 是「WO 的周转时效」，与 page=tt 的 TT 时效是两个数
- 汇总卡只留「WO 总数」一张：本页每行本身就是一个 WO，「WO 编号(唯一)」会与它一模一样；「TT 总数」算的是另一张表的行数，放在本页没有意义
- ZTE/3rd 归属下拉在本页不显示：该归属定义在「TT 的 wo_no」上，WO 表本身没有这个概念
- 筛选条（区域 / 高级过滤）、下钻明细与页面级 Excel 导出与 TT&WO 看板同源，只是数据端点用 /wo-dashboard/overview；导出文件名前缀为 TTWO_wo_
- 直链 http://<host>/myapp/?page=wo；完整版见 page=ttwo，只看 TT 见 page=tt

#### NUR 看板（`nur`）

网络不可用率（NUR）的日/周/月趋势、多维分析与站点达标情况。

- 切换粒度与日期区间，多维下拉筛选
- 站点维度可再按 TRM 类型 / 站点等级 / 省县 / 区域 / 星链近期迁移筛选（属性取自站点主数据，精确匹配；分子与分母同口径，NUR 仍表示这批站点的不可用率）
- 点数字下钻明细表（支持列内筛选与排序），可一键导出 Excel；下钻自动继承当前全部筛选

#### NUR 看板（仅 NUR）（`ms_nur_only`）

NUR 看板的「只保留 NUR」版：内容与 page=nur 的 NUR 部分完全一致（NUR 日/周/月 的表格 + 趋势），不再渲染 SLA 三档，适合只看 NUR 的值班位或大屏。

- 筛选条、下钻明细与导出与 NUR 看板同源，用法一致（含站点维度：TRM 类型 / 站点等级 / 省县 / 区域 / 星链近期迁移）
- 直链 http://<host>/myapp/?page=ms_nur_only；另一半内容见 page=ms_sla_only（SLA 口径，来自 MS Operation KPI 看板）

#### MS Operation KPI 看板（`ms_sla`）

MS 合同 KPI 与工单 SLA 达成情况：NUR / Network KPI / Per-Site / WO SLA（指标为行、期间为列）。

- 粒度三档「天 / 周 / 月」；Network KPIs 与 Per-Site KPIs 只有天/月两档（来自快照库），切到周档位时这两块不显示并给出提示
- 切换天/周/月会重置时间范围为该档默认窗口（天=当月至今，周=最近 12 周，月=最近 9 个自然月），横幅上会写明当前区间
- SLA 达成率（TTR / TTR_P1~P4）统一由 WOs SLA 区以「表格 + 趋势」呈现，不再另设 KPI List SLA 卡片
- 下钻明细与 NUR 页一致；数字以 nur_calc 实时计算为准（ms_sla_full 每 6 小时驱动），可能与历史快照文件不一致——以本页为准

#### MS KPI 看板（仅 SLA）（`ms_sla_only`）

MS Operation KPI 看板的「只保留 SLA」版：WOs SLA 区的工单 SLA 达成率（TTR / TTR_P1~P4 的 Total / Within SLA / Achieve + 趋势），不渲染 NUR、Network、Per-Site。

- 达成率 ≥95% 显示绿色、低于目标标红，与 page=ms_sla 同一口径
- 粒度三档「天 / 周 / 月」：天默认当月至今、周默认最近 12 周、月默认 2026-01 至今；切档会重置时间范围（横幅上有说明）
- 单元格与数据点可点击下钻 TT 明细，并可导出 Excel

#### CXO 经营看板（`cxoDashboard`，iframe 页）

Service / Network / Summary 三层经营看板（源自 VMAX 实时保障看板）。

- iframe 页面内嵌一份完整数据快照：上游不可用时仍能完整渲染，代价是看到的可能不是最新数据
- 要最新数据需重跑对应同步任务；凭据在「系统设置 → 凭据 → vmax_cxo」

#### MW 微波拓扑（`mwUmeTopology`，iframe 页）

ZXMW 微波网络拓扑与带宽利用率 NOC 看板（日粒度）。

- 数据每天 05:15 由 mw_ume_kpi_sync 写入 mw_ume_bw_ultilazation，本页一天只变一次
- 风险榜、抽屉、趋势图均可交互

#### MW 微波实时（`mwRealTime`，iframe 页）

与微波拓扑同构的 15 分钟粒度实时版（拓扑骨架、风险榜、抽屉、趋势完全一致）。

- 默认只展示最新一个 15 分钟槽位，滑杆可回看最近 2 小时窗口
- 页面默认 900 秒自动刷新，且支持「软刷新」（不重载 iframe、不闪屏）

#### 告警管理看板（`alarmManagement`，iframe 页）

宕站（Site Outage）监控看板：以「站点是否宕」为视角，ERA / Regular / ALL 三个视图。

- 每天 01:00 site_outage_screenshot 自动对本页截图，03:00 whatsapp_send 发送到 WhatsApp 群
- 注意：改动此页面 DOM 会连带影响自动截图任务，改前先确认截图选择器仍有效

#### fme_ranking（`fme_ranking`）

FME 排名看板：按 FME 统计站点可用率、工单量与 SLA 达成率，并排名。

- Top3 / Bottom3 卡片与排名表可点击下钻该 FME 的站点级可用率与 WO 明细
- 两张条形图分别看可用率「Top5」与「尾部 5 个」：横向条形按名次自上而下排列，条端直接标出可用率数值；柱子用组内真实值域（而非固定 0~100），否则同一组都在 99% 以上时柱子会一样长、看不出差异
- 条形图里的 WO 数量（蓝线）与 SLA 达成率（橙虚线）只在**该组内确实存在差异**时才出现；若全组数值相同则不画，避免一条贴地直线占满图例被误读成趋势
- 点条形图的任一条可下钻到该 FME 的站点明细；下钻弹窗内还可切换到 WO 维度

#### site_avail（`site_avail`）

站点可用率看板：站点级可用率排名与达标情况。

- 点站点名下钻该站的可用率明细
- 可用率按站点统计口径计算，与 FME 排名页同源

#### avail_ms（`avail_ms`）

MS Availability（可用率多维矩阵）：把全网可用率按「区域 / 制式 / 站点类型」三个维度呈现，日 / 周 / 月用页签切换粒度。数据来自本机派生库 avail_recon.sqlite3（任务 avail_recon_sync 每天 06:10 重建，口径为站点级加权可用率 SUM(分子)/SUM(分母)）。

- 每张矩阵上方有该维度的趋势曲线（日 30 期 / 周 12 期 / 月 12 期，随页签变化）：一条线一个维度取值，所有点都按 SUM(分子)/SUM(分母) 加权，与表格数字严格一致
- 曲线上的点也能点开下钻，打开的是**那个点自己的周期**（例如月档停在 2026-09 时点 2026-08 的点，弹窗就是 2026-08 的明细）
- 区域那张曲线不含「未匹配主数据」（量级太低会把纵轴压扁），图下有一行说明，它的数据在表格末行
- 点任意可用率数字下钻：弹窗内含近 30 期趋势、按日明细与「按调度组」的构成分解，第二个页签可看该组合相关的 TT 工单
- 阈值输入框（默认 99.65%）决定「未达标」判定：低于阈值显示为红色，会实时重算，不改变数字本身
- 区域维度的 ALL 行含「未匹配主数据」的站点，因此 ALL 不等于三个区域相加；末行单列该桶，点它只能看可用率明细、不能下钻 TT（派生库里没有那批站点的名单）
- 4G 的 NERA 属未映射调度组：计入制式 4G 总量，在站点类型维度单列「其它」，只出现在 2025-12 ~ 2026-01 的月份；此时页面会出现黄色口径提示条
- 取不到数据显示「—」而不是 0；页面顶部显示「数据截至」，派生库停更时能一眼看出来

#### avail_flm（`avail_flm`）

FLM 可用率：只看三个 FLM 区域（Montserrado / North East / South West）的可用率，行是区域、列分别是制式（2G/3G/4G）与站点类型（Regular / Cooli / ERA，列名用数据原值，需求表写作 Cool.i）；日 / 周 / 月用页签切换粒度。数据与「可用率多维矩阵」同源（本机派生库 avail_recon.sqlite3，口径 SUM(分子)/SUM(分母)），另外把「影响可用率的 TT 列表」直接列在页面上。

- 两张表上方各有一条曲线：上面那条是三个区域的可用率走势（一个区域一条线），下面那条是三种站点类型的走势；日 30 期 / 周 12 期 / 月 12 期，随页签变化
- 曲线上的点也能点开下钻，打开的是**那个点自己的周期**；阈值虚线（默认 99.65%）与表格的红色判定同一个值
- 点任意可用率数字下钻：弹窗内含近 30 期趋势、按日明细与「按调度组」的构成分解，第二个页签是该切片的全部 TT 工单
- 三个区域各有一张 KPI 卡（该区域全部制式合计），点卡片同样能下钻
- 站点类型不做范围限制：三个区域都会显示 Regular / Cooli / ERA 三列（列名用数据原值）。需求里写的「NE 只有 Regular/Cool.i」与两个数据源都不符（NE 有 123 个 ERA 站点、派生库里 NE 的 ERA 分母 6.5 万），硬留空反而会让人以为 NE 没有 ERA 站点
- 末行「未匹配主数据」是远端站点名匹配失败的部分：它不在三个区域之内，也不画进曲线（量级大会压扁纵轴），单列出来只为对账，点它只能看可用率明细、不能下钻 TT
- 页面级「影响可用率的 TT 列表」列出**本期全部工单**，不做「是否影响业务」的判定（判定字段与 site_outage 在本期数据上完全一致，取其一都会让口径看起来比实际精确）；每行给出 2G/3G/4G 断站数与 MTTR，由使用者自己判断相关性
- TT 列表可按区域筛选（全部 / 三个区域）；月档工单数可达 3600+ 条，超过展示上限时页面会显示黄色提示，只有明细条数受影响、可用率数字不受影响
- 点工单号可反查该工单所属「区域 × 站点类型」的可用率与同期全部工单
- 4G 的 NERA 属未映射调度组：计入制式 4G 总量，但本页站点类型列只有三种，此时 4G 行会大于三列相加，页面会出现黄色口径提示条
- 取不到数据显示「—」而不是 0；页面顶部显示「数据截至」，派生库停更时能一眼看出来

#### bm_speedtest（`bm_speedtest`）

Speedtest 基准报告：把两家运营商（Orange 与 MTN）的网速实测数据并排比较，回答「谁更快 / 谁时延更低 / 领先多少 / 优势在扩大还是在缩小」。数据来自 speedtest_data（Speedtest.xlsx 导入，854 行，2025-07-16 ~ 2026-09-24，全国 cellular 中位数口径）。页面分五块：综合竞争力评分 → 关键指标汇总卡（下载/上传/时延/抖动，各含均值与 P50/P90）→ 趋势对比图（可切指标、可设滚动均值窗口）→ 逐日胜负统计 → 月度对比表与逐日对决明细表。

- 顶部快捷区间（近 30 / 90 / 180 天 / 近一年 / 全部区间）配合日期选择器；时间窗是**左闭右开**，界面显示的是闭区间
- 「综合竞争力评分」是**两家的相对分**：每项指标领先方 100 分、另一方按比例得分，再按下载 35% / 上传 20% / 时延 30% / 抖动 15% 加权。它只回答「这两家谁更强、强多少」，不评价绝对水平好不好；某项指标任一方缺数据时该指标不参与、权重分给其余指标
- 关键指标卡里每个数字都可点：点品牌数字看该品牌该指标的全部明细；点「胜率」看**该指标胜出的那些天**（行数与胜场天数严格相等，都是同一份配对比较算出来的）
- 趋势图用分段控件切下载/上传/时延/抖动，右侧下拉设滚动均值窗口（3/7/14/30 天）。实线是逐日原始值、虚线是滚动均值；速率「越高越好」、时延「越低越好」，图下方有文字提示
- 「逐日胜负统计」给出每项指标两家各赢多少天与胜率，同样可点开下钻
- 点明细表里的日期可下钻那天两家各自的原始行
- 区间内只有一家有测试数据的日子**不计入胜负**（页面顶部有蓝色提示条说明有几天）：「那天没测」不等于「那天输了」
- 逐日曲线超过 400 天时图上只画最近 400 天，页面会有黄色提示条，完整逐日数据看下方表格或导出 Excel
- 数据里 location / device / 制式 / 聚合方式都只有一个有效取值（全国 / cellular / median），所以**这四个维度没有筛选器**，不是漏做
- 取不到数据显示「—」而不是 0；导出统一走页面右上角与各卡片的「导出 Excel」

#### bm_meta（`bm_meta`）

Meta 基准报告：基于 meta_data（Meta_20260923.xlsx 导入，612 行，2025-01-18 ~ 2026-09-23）回答两件事——①「Orange 与 MTN 谁的速率更高、领先多少、优势在扩大还是缩小」；②「同时段网络侧的 BP / FDD 下行吞吐 / 上下行 PRB 利用率 / 流量 / RRC 用户数是什么水平」。这两件事**刻意分开**：只有「速率」是两家的直接对比，其余 6 项是网络侧 KPI，不属于任何一家。页面分两大层：两家 PK 层（综合评分 → 速率汇总卡 → 双线趋势 → 逐日胜负 → 月度对比与逐日明细）+ 网络侧 KPI 层（汇总卡 + 单线趋势）。

- 顶部快捷区间（近 90 / 180 / 365 天 / 全部）配合日期选择器；时间窗是**左闭右开**，界面显示的是闭区间。默认窗口是近 365 天而不是 90 天——本表跨度 612 天，短窗口会把长期趋势结论切掉
- 「综合竞争力评分」是**两家的相对分**：领先方 100 分、另一方按比例得分。它只回答「这两家谁更强、强多少」，不评价绝对水平好不好
- **为什么网络侧 KPI 不参与评分**：把「Orange 比 MTN 快多少」和「全网 PRB 利用率多高」混进同一个评分，等于把两件不同的事算成同一件事的两个选手，结论是假的。所以网络侧 6 项只做趋势与汇总，没有胜负、没有评分
- 「速率」是两家的下载速率对比值（库中 orange_liberia / mtn_liberia 两个固定列），每天一行；两家相同时记为「持平」，**不计入任何一方胜场**（页面顶部有提示条说明有几天）
- 页面上每个数字都可点开下钻：点品牌数字或「领先 N / M 天」看**该品牌领先的那些天**（行数与胜场天数严格相等，同一份比较逻辑算出来的）；点逐日/月度表里的任意格看当天原始明细
- 趋势图右侧分段控件切 7 个指标（速率 + 6 项网络侧 KPI），下拉设滚动均值窗口（3/7/14/30/60 天）。切到网络侧 KPI 时图变单线且**不出现运营商图例**——因为它不属于任何一家
- BP 与上下行 PRB 利用率在库里是**小数比率**（如 0.1956），页面统一换算成百分数显示（19.56%）；胜负与评分用原始比率算，不受显示换算影响
- 流量（GB）与 RRC 用户数带千分位显示；取不到数据显示「—」而不是 0
- 导出 Excel 含三张 sheet（汇总 / 月度对比 / 逐日明细），汇总 sheet 里两家 PK 与网络侧 KPI 分组列示，避免被读成同一件事

#### noc_analyst（`noc_analyst`）

NOC 操作人分析：基于 eflow_tt.last_processer 量化每位 NOC 的根因错位率、平均处理时长、夜班单占比与 SLA 通过率，并给出红旗告警。页面按「能下钻尽下钻」设计——从人一路下钻到 TT，再下钻到告警链路。

- 口径：按告警发生时间（alarm_occur_time）归属月份，而非最后修改时间；夜班 = Accept 操作时间落在 22:00–06:00
- 错位率 = 错位单数 / 已填报根因单数；错位判定以 history_alarm.reason_type 为权威，与 NOC 填报的 root_cause 比对（典型为 POWER←TRM，即 NOC 填供电、系统指向传输）
- 第 1 层下钻：概览数字卡、Top3/Bottom3 卡片、ECharts 柱状图、排名表每一列与红旗告警里的人名，全部可点
- 第 2 层下钻：弹窗内按「全部 / 根因错位 / 夜班单 / SLA Fail / 慢单（≥12h）」五种切片切换，行数与该 NOC 的对应指标严格一致
- 第 3 层下钻：切到「异常站点」页签按站点聚合（错位 / SLA Fail / 慢单 / 夜班），点站点名再看该站的全部 TT
- 第 4 层下钻：点任意 TT 单号打开单 TT 复盘报告——按「时间归因 / 里程碑时间轴 / 应做·实做 / 偏离清单 / 告警链路」五个页签展开，与 EflowQa 页的程序化复盘报告同源同口径
- 时间归因区「时间都花哪了」：把整月工单逐单解析后聚合，回答时间浪费在哪个环节。含 6 张可点数字卡、各环节占时比例饼图、偏离类型分布、分段表（合计/平均/P90/最长/超阈值单数）、里程碑耗时分布表
- 「应派未派 WO 明细」：高等级断站（P1/P2、VIP、Hub）却没派现场工单的单子，按总历时降序，点 TT 号直接进该单的复盘报告「偏离清单」页签
- 鼠标悬浮看名字：告警码（如 99933）悬浮显示官方告警名（SITE DOWN DUE TO POWER OFF）；「派单分类」（如 rule_stopped）悬浮显示成因说明与命中的推单规则名及状态（ACTIVE/STOP），一眼看出"为什么这单没建 WO"
- 顶部「承接方」三档切换（ZTE 自派 / IPT 第三方 / 全部，默认 ZTE）：排给第三方（IPT）的单本来就不建 WO，若与自派单混在一起看，会把「应派未派 WO」抬高近 4 倍（实测 1140 → 修正后 296）。切换到「IPT 第三方」可单独复盘第三方的履约情况（该档「应派未派 WO」恒为 0，属正常）
- 现场处置及时性「全月 WO 各跳耗时分布」：把现场工单的生命周期拆成 工单建单→FE 接单→出发→到场→处理完成→关单 各跳，看哪一跳最卡。实测最慢的是「工单建单 → FE 接单」（中位数约 11 小时），而接单之后的动作都只要几分钟
- 「NOC / 人工动作及时性」：每个该由人完成的动作（FO Accept 接单、FO Process 填报、现场作业）等了多久、是否超过契约时限、超时限占比是多少
- 单 TT 复盘「时间归因」页签里，分段表带「阶段」列可直接看出该单时间压在哪一类；下方还有该单的「现场处置时间轴（WO 生命周期）」逐跳明细（含操作人）；未派 WO 的单会明确提示"本单无 WO"，不会空白
- 「阶段归并：时间压在谁手里」：把细分段按阶段合并（建单时延/接单等待/现场响应等待/现场作业/告警清除/提交关单/关单确认），便于比较 NOC、现场、系统各占多久。实测全月现场响应等待占 15.2%（中位数 6.4 小时）
- 时间归因首次计算要逐单复盘全月工单（实测约 150 秒），结果按月份落盘缓存，之后打开是毫秒级；需要强制重算时点右上角「重新计算」
- 弹窗内每个表格都可全字段搜索、列筛选与排序，并可导出 Excel（导出的是当前切片、当前搜索结果）

#### repeat_site_down（`repeat_site_down`）

重复宕站看板：识别在统计窗口内反复宕站的站点，用于定位「修不好的站」。

- 按日粒度统计站点宕站次数，点数字下钻该日宕站明细
- 数据来自 eflow_tt 与 eflow_site，与告警看板口径互补

#### cr_analysis（`cr_analysis`）

CR 变更分析：既看「现在卡在哪」（状态分布、审批流程滞留），也看「过去做得怎样」（计划达成、按时、关闭率），回答「还有多少没走完、卡在哪一步、谁那边最慢」。

- 数据来自 eflow_cr（eFlow 同步），默认区间取全表实际时间范围
- 最上面是 <b>Workflow 里程碑条</b>，顺序与 eFlow 的 Workflow History 完全一致：创建 → BO/FO 负责人审批 → 域技术总监审批 → 变更经理审批 → 开始实施 → 结果反馈 → 已关闭。每个节点显示「已完成」与「等待中」两个数，「等待中」最大的那个节点会标红为<b>瓶颈</b>，并显示最久已等待多少天
- 里程碑按流程节点归并：驳回到 BO/FO 的「Waiting for Update」并入 BO/FO 审批节点，不单独成环。若要看 7 个原始状态的精确分布，看下方「状态分布」环形图
- 状态名是上游原值，不做翻译；「Waiting for Implement」表示审批已全部通过、正在等实施，不是「等待审批」
- 四个核心计数：「已排期」= 有计划开始时间；「已执行」= 有实际开始时间；「未执行」= 排了期但没动；「按时/延期」= 实际开始早于 / 晚于计划开始
- 三个比率的分母写在数字下方：计划达成率 = 已执行 ÷ 已排期，按时执行率 = 按时 ÷ 已执行，关闭率 = 已关闭 ÷ 总量。分母为 0 时显示「—」而不是 0
- 「审批流程与停留耗时」解析源表的步骤记录：到达数 = 走过该步的 CR 数；平均/最长停留 = 该步用了多久；当前滞留 = 还停在该步的 CR 数；最久已等待 = 其中等得最长的那张已等多少天。步骤按**实际流程顺序**（创建 → BO/FO 审批 → 域技术总监审批 → 变更经理审批 → 实施 → 结果反馈），不是源表列名字母序
- 「当前滞留」的数字往往就是最该看的：某一步滞留多、等待久，说明该审批环节是瓶颈
- 页面上每个数字都可点：状态卡、环形图扇区、KPI 卡、比率卡、类别表格、图表柱子、流程步骤、月度趋势、子类别表格都能下钻到明细，明细行数与卡片数字严格一致
- 下钻明细被截断时会显示黄色告警条，提示缩小时间范围——不要忽略它

#### pm_analysis（`pm_analysis`）

PM 执行分析：按 PM 计划号（pmp_no）看预防性维护工单（PMT）的完成与超期情况，回答「计划执行到哪一步、多少超期、卡在谁那里」。

- 数据来自 eflow_pm（eFlow 同步），默认区间取全表实际时间范围
- 四个核心计数：「已完成」= 状态为 Closed；「未完成」= 尚未 Closed；「已超期」= 源表 pmt_overdue 为 Yes（直接用上游判定，不自己按日期算）；「未开始」= 已完成条目数为 0
- 两个细分口径：「完成但超期」= 事后补录/迟交；「未完成且超期」= 真正压着没做完的，优先看这个
- 三个比率的分母写在数字下方：工单关闭率 = 已完成 ÷ 工单总量，超期率 = 已超期 ÷ 工单总量（越低越好），已启动率 = 条目完成数 > 0 的占比。分母为 0 时显示「—」而不是 0
- 页面顶部的「审批流程里程碑」严格按 eFlow 的 Workflow History 排列：创建 → 排期 → 受理 → 处理 → PM 经理审批 → FLM 领导审批 → 已关闭。每格显示「已完成」（走过该节点）与「当前滞留」（正卡在该节点等下一环节），滞留最多的节点会加「瓶颈」标记；点数字可看该节点的工单明细与已等待天数
- ⚠️ 源表字段名有误导性：last_process_time 记录的是「进入处理」的时刻，早于 PM 经理审批时间，不要按字段名猜顺序
- 在计划号筛选里只选 1 个计划号时，里程碑同步按该计划过滤；选多个时里程碑按全部计划统计（页面会给出提示），与下方表格小计可能不同
- 页面上每个数字都可点：KPI 卡、比率卡、图表柱子、月度趋势、站点条形图、计划表格都能下钻到明细，明细行数与卡片数字严格一致
- 下钻明细被截断时会显示黄色告警条，提示缩小时间范围——不要忽略它

#### bp_report（`bp_report`）

BP Cells Report：umlaut 口径的 Bad Performance 小区统计，支持按日/周/月查看并下钻到小区明细。

- 口径（忙时三值）：取「活跃用户最大的那个小时」的 PRB / DL 吞吐 / 活跃用户数判三条件 —— DL PRB 利用率 > 80% 且 DL 吞吐 < 3 Mbps 且活跃用户数 > 2.5；周 = 一周 4/7 天为 BP；月 = 一个月 3/4 个完整周为 BP
- 该忙时口径经 Excel 标定：与 umlaut 明细逐小区一致（Jaccard=1.00）；日均值口径会漏判约 97% 的 BP 小区
- ⚠️ 「平均活跃用户数」只在 RAN_UME 的小时粒度可用，日粒度查询会静默丢弃该列，故走独立通道按小时取数；取不到时该日记「不可判定」，绝不当 0
- 每个数字都能点开下钻：BP 小区数、明细行数、不可判定数、趋势图柱子、四张数字卡、分区图、分层表的 BP 数，行数与展示数字严格一致（同一查询条件）
- 下钻明细表含「站点 ID」（即 ManagedElement ID / 网元 ID）与「站点名」两列，便于把小区落到具体站点；站点名按网元 ID 关联站点库得到，覆盖约 98%，个别查不到的显示 —
- 「全网小区数」列仅 RAN_UME 来源的期可下钻（分母即明细行数）；Excel 来源的期未提供名单，置灰并给出提示
- 「明细行数」列显示 Excel BP Cells List 里该期实际有多少行，括号内是与展示值的差额——上游 Excel 各 sheet 本身就不一致，差异如实展示
- 2023 年与 2024 年部分日期在 Excel 的 BP Cells List 里没有明细，这些期的下钻入口会置灰
- 「最新一期 BP 小区数」卡显示该期 BP 小区数及其占评估总数的比例；「最新一期判定」卡周/月给出是/否，不可判定时会说明成因 —— 本周没过完（等待即可）与本月完整周数不足（如 2026-09 只有 3 个完整周 < 口径要求 4 个，该月永远判不出来，是口径与日历错配而非缺数据）
- 分区（Cluster1~6 / Rural / ERA）只能在 Excel 里维护，RAN_UME 没有这套维度；新增小区若不在字典内会归为 Unknown
- 趋势支持按日/周/月三种粒度切换；切到周或月时若只看到空图，先确认日期范围是否覆盖了有数据的周期
- ⚠️ 下钻明细里的 PRB 利用率 / DL 吞吐 / 活跃用户(忙时) / DL 流量 四列只有 2026-07-22 之后才有：BP Report.xlsx 本身只存日期/网元/小区/分区/频层，从不含这四个指标，只能从上游重新取；而上游对 2026-07-01~07-21 这 21 天没有留存（UME 侧同样只到 07-02 起），故该区间显示 — 且无法补
- 2026-07-22~09-21 的四个指标已从上游补回，这些天的行数因而是「全网小区」而非「umlaut 报告过的小区」，BP 数与该期 Excel 原值相比低约 13~14%，占比分母口径也随之不同
- 数据由 bp_report_sync 任务每天 06:20 从 RAN_UME 增量更新

#### 丢包看板（`packet_loss`）

LTE 丢包看板（RAN UME SDR / IPRAN IPPD）：最近 7 个完整自然日、小时粒度，当天没过完不展示。

- 口径与 Packet_Loss 自动化 Excel 报告完全一致；Popover 可查看口径说明
- Switch 控制是否包含 OK 站点；支持下钻明细与拓扑叠加

#### 电池看板（`battery`）

站点电池健康度 / SOC / 充放电状态与告警明细。

- 第一维度是「数据新鲜度」：默认只统计 24 小时内的新鲜读数（battery_kpi_sync 每小时 :05），关闭「仅新鲜」会混入旧数据导致失真
- 点站点名下钻电池明细与历史读数；支持导出 Excel

#### ume_in_kpi（`ume_in_kpi`）

客户业务 KPI 看板：从 UME 门户（172.17.208.1:28808）抓取 Dong customer 周度业务指标，覆盖 IVR / P4M / VC / USSD / PPS / CPU / Memory 共 7 个模板（1 天粒度）。除业务量与成功率外，本页把失败按「系统侧 / 用户侧」归因——只有系统侧失败率与资源利用率会触发告警，因此像 PPS 的「余额不足」、USSD 的「用户失败」这类业务正常结果不会被误报为故障。

- 顶部「立即同步」手动触发一次抓取（约 10~60 秒）；日常由 ume_in_kpi_sync 任务每天 05:45 自动同步
- 「近 7 / 14 / 30 天」切换趋势回看窗口；表头可排序、可按状态筛选
- 业务 KPI 表点行首展开，查看每个 SERVICE 的业务量、成功率、系统侧/用户侧失败与失败原因标签
- 「失败率构成」按归因堆叠显示各 KPI 的失败率；「成功率多日趋势」看逐日变化
- 资源利用率以「日均」判定（≥80% 关注、≥90% 异常），峰值仅作参考——瞬时打满属正常尖峰
- 「导出 Excel」输出 6 个 sheet：KPI 汇总 / 服务明细 / 失败分解 / 资源 / 趋势 / 告警

#### cn_kpi（`cn_kpi`）

CN KPI 看板：原 FineBI「CN KPI」看板的原生重建，18 个组件（VLR / Voice / Data 用户数、USSD 成功率、位置更新成功率、USPP / MSC / xGW 利用率、FDD / TDD 流量、RG-6/11/12/30 等）。数据经远端只读 SQL API 读 db_ps_cs_cn，不依赖 my-finebi 进程。⚠ 本页数据来自两条彼此独立的流水线：人工导出的 _EMS 表（会停摆，且**粒度随导出区间变化**）与自动同步的 _UME 表；因此取数会逐级降级，并在卡片与页头**显式标注粒度**。

- 默认为「近 31 天」；改时间区间后点查询，月粒度组件会自动改用近 13 个月窗口
- 卡片右上角橙色「月粒度」标签表示该点代表一个月，**不是某一天**；金色「已切源」表示原表停更、已改用自动同步的同名数据源
- 页头橙色告警条会列出所有降级组件及成因，看到它请先确认是否有人需要重新跑一次网管导出
- 「导出 Excel」输出各组件数据与执行口径（SQL），便于与网管侧对账

#### cn_kpi_5mins（`cn_kpi_5mins`）

CN KPI 5 分钟看板：把「今天（Day0）」「昨天（Day1）」「7 天前（Day7，与今天同一个星期几）」叠在同一张图上，对比同一时刻的核心网 KPI 走势。数据由任务 cnn_kpi_sync_5mins 每 15 分钟采集一次（窗口为昨天 00:00 至现在），写入 db_ps_cs_cn 的 5mins_* 新表，与按天/月的 CN KPI 看板互不影响。⚠ 本页是**混合粒度**：Voice / VLR / Data / 4G FDD / Free Rating 为 5 分钟粒度；xGW License、xGW CPU、3G FDD 因原模板无 5 分钟档，走上游 2026-10-19 补建的 15 分钟档模板。

- 每张图最多三条线：Day0 今天、Day1 昨天、Day7 七天前（同一个星期几，用来看「这周比上周同一天的同一时刻是涨了还是跌了」，比单纯跟昨天比更不容易被周中/周末的差异误导）；横轴为时刻（HH:MM），同一个横坐标即同一时刻
- Day7 依赖库里已攒下的历史：采集窗口只取「昨天 → 现在」，但写库是 upsert 且不清理，所以每个日子在其次日被采到后就永久留下 —— 库里攒够 8 天才画得出 Day7，不足时页头只列已有那几天并明说，需要更早的历史得做回补
- 页面无需选日期：窗口固定为「今天 + 昨天 + 7 天前」，每 15 分钟随任务自动更新一次（可在顶栏设置自动刷新）
- xGW License / xGW CPU / 3G FDD 三张卡片的点是 15 分钟间隔（比其他图稀疏 3 倍），这是上游模板档位决定的，不是数据缺失；页头蓝条会提示
- 「导出 Excel」每个组件一张表，按时刻展开 Day0 / Day1 / Day7 列（只出该组件实际有数据的日子），便于对账

#### UME iMonitor 大屏（`imonitor`，iframe 页）

UME iMonitor 大屏（guard-imonitor-iui，screen_id=1）：把 UME 门户（172.17.208.1:28808）的原版监控大屏原样嵌进 myapp，保留其全部图表与交互。页面经 nginx 8088 反代到上游（门户独立端口方案），首次进入会由注入脚本自动完成 em-portal 登录（账号取自 Settings → 凭据的「UME 客户业务 KPI 门户」，即 ume_in），无需手工输入；登录页的 frame-bust 已在反代里中和、iframe 另加 sandbox，保证登录过程不会把 myapp 外壳冲掉。

- 首次进入约 3~6 秒完成自动登录后出图；会话有效期内再次进入直接秒开
- 会话过期时大屏 SPA 会自己跳登录页，注入脚本自动重新登录并把 iframe 拉回 screen_id=1，全程无需干预
- 工具条「重新登录」强制重走一次门户登录（换账号 / 门户把会话顶掉时用）；「刷新」只重载大屏页面
- 「新窗口打开」在独立标签页里看这块大屏（与页内共用同一份浏览器会话，Cookie 按主机共享、不分端口）
- 自动刷新（顶栏）到点后由本页在 iframe 内原地重载，不会整页闪白；该页已登记在 AR_SOFT_REFRESH_PAGES
- 上游把 Content-Security-Policy: frame-ancestors 设为 self，故必须走反代（nginx/portal_ume_in_8088.conf）而不能直连；反代端口 8088 与 nginx 配置、PROXY_PREFIXES 三处需保持一致

#### GIS地图（`gis`）

站点地图：告警/工单在地图上的分布、拓扑线、区域面与多维筛选（历史/工单口径）。

- 区域下拉 + 图层 Tag 开关筛选；图例点击可隐藏该类图层；时间支持分段切换与自定义区间
- 「高级筛选」面板第一格是「站点名称」输入框：按名称片段模糊匹配（不区分大小写），其余是区域/等级/站型/FME 等下拉；
- 筛选后统计同步变化：站点总数与 ERA/COOL/NORMAL 分档、地图图例、县块颜色与县名标注、右上角「MAINTENANCE ALERTS」区域排名条都按筛选后的站点重新统计，不再显示全量数字；
- 点站点打开右侧抽屉，四个页签明细可搜索、可导出 Excel
- 「链路利用率」开关（默认开）：把 MW 微波实时页同一 15 分钟槽位的链路利用率叠加到地图链路线上，按 4 级着色（>80% 紧急 / ≥70% 重要 / ≥60% 次要 / <60% 正常），线越粗表示利用率越高
- 点链路线可看该链路的最高/发送/接收利用率与匹配到的 MW 站点；显示「无 KPI 数据」的链路表示未匹配到实时指标（保持 KML 原线色），不是 0%
- 叠加口径见图例下方说明：844 条 KML 链路中约 360 条能匹配到实时指标，其余仍在 MW 微波实时页查看

#### 实时告警地图（`realtime_alarm`）

GIS 地图的实时模式：当前活跃告警站点的地图分布（带红色「实时」标识），含根因聚合分析。

- 操作与 GIS 地图页一致
- 数据来自 eFlow 活动告警（eflow_active_alarm），每分钟同步一次
- 「根因聚合分析」卡片：把当前高级筛选范围内的断站聚成簇 —— 拓扑根因（上游站断，其传输链下挂站跟着断）/ 同因聚集（无链路站按告警问题 + 10 分钟时间窗聚集），并给出根因类型、受影响站数与置信度；点条目可看成员明细与证据（链路路径、时间窗、eFlow 影响面），成员站名可点开下钻抽屉
- 标题括号里的「已归因/总」与 Site Stats 同为**站数**单位：已归因 = 进入共享根因簇的站数；其余是孤立故障（上游没告警、没有同窗同伴，根因就是它自己）—— 点脚注可打开未归因**告警明细**（与点击 Alarm Stats 条目打开的是同一张项目默认明细表：站点/TT/优先级/告警时间/时长/超时），对地图逐点核验
- 根因站可能落在高级筛选范围之外（标「范围外」）—— 断站原因往往在当前视野之外，属正常且有价值的输出
- 「AI 解读」按钮：用自备 LLM Key 生成自然语言结论（Key 仅存本机浏览器）；AI 不可用时自动降级为本地规则结论并标注，不影响簇列表本身

#### 事件总览（`incident_overview`，iframe 页）

OLR 事件（Incident）总览看板：卡片、矩阵、SLA 图表、分页明细与地图。

- 数据每小时第 20 分钟由 incident_overview_sync 从 FineBI FTP 取最新 incident_overview.xlsx（版本化落盘，上游文件被占用也不会取数失败；排在这个分钟是因为 FineBI 每小时 :53 会先删掉上一轮输出目录、新副本约 :02–:05 才落盘）

#### 仓库看板（`warehouse`，iframe 页）

备件/耗材库存看板（Spare Management），与原工具看板完全一致。

- 数据来自 sp_data_sync（每天 07:00 从 SFTP 拉取的 5 份备件报表）
- 按仓库/备件类型查看库存与明细

#### sp_material（`sp_material`）

备件物料统计汇总：按专业域/物料看入库、出库与库存的汇总分布。

- 数据来自 sp_data_sync 拉取的备件报表
- 点任意汇总数字可下钻到对应物料明细

#### sp_details（`sp_details`）

SP 备件明细报表：与邮件任务发出的合并工作簿是同一份文件，含 Inventory / Inbound / Outbound / Transfer 四张表。

- 分页 + 筛选 + 排序；「未关闭」= Status 不含 Closed 的行
- 表格只展示常用列，点任意一行查看该表全部列
- 导出为当前筛选结果（最多 5000 行）

#### sp_report（`sp_report`）

备件 Inbound & Outbound & Inventory 汇总报表：与邮件/WhatsApp 发出去的是同一份工作簿（每天 05:15 由 sp_report_generate 产出），含 Summary-Current / Summary-Changed / Inbound / Outbound / Inventory 五张表。

- 统计卡片看总量与补库告警，点告警卡即筛选
- Summary-Changed 渲染成「天 × 仓库」矩阵
- 「显示列」可按分表自定义并本地记住；行详情弹窗始终显示全列

#### com_report（`com_report`）

耗材 Inbound & Outbound & Inventory 汇总报表：与备件页版式一致，只是数据源换成耗材工作簿。

- 口径与备件页完全相同，见页面底部「报表口径说明」
- 页面与 Excel 数字不一致时先看口径说明，不要在页面层改口径

#### warehouse_summary（`warehouse_summary`）

仓库汇总报表：按仓库汇总报表（WarehouseSummaryReport.xlsx）复刻，页签对应该文件的两个 sheet——Spars Parts / Consumables。每个页签含两段：WH/DOP 库存与消耗汇总（当前库存 / 累计 / 本月 / 本周消耗），以及高频消耗物料（每页 10 行，可翻完全部物料）。

- 页签切换备件/耗材；两段表的每个数字都可点击下钻到明细
- 高频物料按消耗量降序分页显示全部，Total 行是全量合计且不随翻页变化
- 消耗口径是 Outbound Site Qty（站点出库），段②标题右侧有标签提示

### 4.3 分析与工具

#### eFlow 知识库（`eflow_qa`）

eFlow TT 判定规则知识库：规则/案例文档全文检索，并内置 TT 快速分析与 TT 批量核查。

- 空格分隔多关键词检索，或从左侧目录选择文章
- 输入 TT 单号一键分析：派单归属、时间差、根因分布与结论要点
- 结论卡片与下方「规则命中证据」都由本地规则引擎程序化算出（与 Email Reports → eFlow TT Rules Check 页签同源）：命中规则名称与 ID、逐条条件匹配详情、规则来源文件 eflow_TT_rules.xlsx（可下载）、规则维护人与工单处理人
- 判定不调用任何模型（2026-10-19 起）：毫秒级返回，级别判定、命中规则、规则来源与处置建议全部由本地规则引擎按 eFlow「TT Update Severity Rule」推出，与每天 04:20 的 eflow_tt_rules_check 定时任务逐字一致
- 「规则来源与责任人」另给推单规则（TT Push Order Rule，触发步骤 FO Accept）：Rule Name / Rule Type / Rule Trigger Step / Push Order Path / *Auto Operator / Target Handler，说明这单会不会自动推 WO、推给谁、谁自动处理（来源 eflow_push_rules.xlsx，可下载）
- TT 批量核查：上传 xlsx/csv/txt 单号清单或直接粘贴，逐单判定工单级别是否正常（正常/需调整/无法判定），可导出 Excel
- TT 批量核查支持「下载模板 → 填写 → 上传核查」闭环：点「下载模板」得到带表头的 xlsx，填好单号后把同一个文件传回来即可

#### eflow_flow（`eflow_flow`）

eFlow 全流程查询：输入告警（告警 ID / 告警码）或 TT 单号，画出该单在 eFlow 里的全流程图 —— 规则驱动的完整状态机 + 该单实际走过的路径高亮。

- 输入框支持三种输入：TT 单号（TT202609230060）、告警 ID（告警表的 id/aid）、告警码（如 99933）；按告警码查询会列出该码最近的 TT 供切换
- 底图是规则驱动的状态机：告警发生 → TT 建单 → 自动派单 → FO/BO 接单 → FO/BO 处理 → 第三方接单/处理 → 确认 → 关单，节点下方的「生效/总数」是该步骤绑定的规则条数
- 绿色节点 = 该单实际走过的步骤，黄色节点 = 当前所处步骤（来自 operation_type 字段），灰色 = 未涉及；粗青色连线 = 实际路径
- 点击图中任意节点，下方「规则明细」表即切到该步骤绑定的规则（规则名 / 类型 / 触发步骤 / 状态 / 优先级 / 目标处理人 / 推送路径），再点「显示全部」可看全量规则
- 「实际流程路径」表按时间列出该单真实走过的里程碑、操作人与说明；「TT 工单信息」表给出级别、当前处理人、SLA、根因等字段
- TT 若已派生现场工单，另有「WO 现场子流程」区块：WO 的 接单 → 处理 → 确认 → 关单 独立一条流水线，并列出各环节处理明细（来自 eflow_wo 的 *Detail 字段）
- 「关联告警」表列出触发该 TT 的告警（realtime_alarm / history_alarm 的 tt_id 或 alarm_id 关联），含告警码、站点、网元、级别与发生时间
- 判定口径与「NOC 操作人分析」「单 TT 复盘报告」同源：规则统一读 ocrule_details，因此不会出现「流程图说 A、复盘说 B」
- 规则表由 eflow_push_rules_collect / eflow_alarm_rules_collect 定时采集（每 3 天 23:59），规则更新后流程图自动反映

#### 分析仪表盘（`dashboard`）

分析仪表盘：选一张表自动生成多维图表与结论，可归档保存。

- 选表 → 修改分析名称 → 生成分析 → 归档
- 开启「联动筛选」后点饼图/柱图即设置筛选，再点取消

#### 分析归档（`archive`）

分析归档：历史分析结果的检索、详情查看与删除，与分析仪表盘配套。

- 关键字搜索 + 分页浏览；详情含结论文字与图表快照
- 删除需二次确认，谨慎操作

#### IP 链路探测（`ip_trace`，iframe 页）

IP 链路探测：从服务器侧探测到目标站点的链路连通性与路径节点。

- 输入目标开始探测，结果表格/地图实时刷新
- 探测是可中断的长任务，卡住时可手动停止

#### vmax_user_query（`vmax_user_query`）

VMAX 用户信息查询：输入用户号码与时间窗，从 VMAX CCA 投诉系统查询用户信息（IMSI/MSISDN 映射）、终端信息（IMEI/机型/厂商/运营商）、窗口内按应用流量与驻留小区列表（含每小区 KPI 明细）。

- 必须用 231 开头的完整号码（如 231777777322），纯数字；本地 9 位格式上游查不到（2026-10-24 实测）
- 时间窗精确到分钟（5 分钟步进），默认今天 00:00 到当前时刻，跨度最多 31 天，不能选未来；流量与驻留小区按窗口查询，终端/用户信息与窗口无关
- 「查无此号」「流量为空」都是业务正常返回，不是故障；接口报错时先检查 设置→凭据管理 的 vmax_cca 组是否已录入账号密码
- 驻留小区行内点 KPI 弹出该小区指标明细（ppc 码已映射 KPI 英文名，缺码显示原始码）
- 根因分析卡列出窗口内投诉根因（置信度降序），点详情看劣化描述、处理建议与逐时段判定；大窗口（7 天级）该查询可能超时，不影响其它卡片
- 查询走 VMAX 门户会话（串行复用），请勿连续大量点击，避免占用上游会话
- 结果只读透传不落库；但「执行过的查询」条件会写进地址栏，刷新、浏览器前进后退或把链接发给同事，重进时会自动按同一条件重查一次
- 链接里带号码与时间窗（msisdn / vqStart 等参数），转发前确认接收方可以看这个号码
- 三个视图（概览 / 信令详单 / XDR 记录）切换不会丢已查到的结果，来回对比不用重查
- 「信令详单」页签（2026-10-26 并入）：号码沿用上方输入框，从 Talon XDR 平台查该号码逐条信令记录，可下钻到单次会话/过程
- 信令详单支持 5G 会话（1100）、信令面（1300）、用户面业务（1301）与 RAN 无线侧（32）；时间窗默认近 2 小时，列由上游列头动态生成（46~88 列，可横向滚动）
- 各类型可回溯时长不同：5G 系类 72 小时，RAN 无线侧只有 24 小时。超出保留期的时段选择器会置灰——那是上游不保留旧数据，不是故障
- RAN 无线侧（32）已接入，含 RSRP/SINR 等空口测量列，排查无线质量用它；33/34 尚未接入
- 「导出 Excel」导出的是**整个查询结果**而非当前页（自动分批拉全，上限 5000 条）；超限会在文件名副标题里写明已截断，此时请缩小时间窗分批导出
- 「XDR 记录」页签（2026-10-27 新增）：按**单张 XDR 表**查（32 下为 UEMR_XDR / UU_XDR / X2_XDR，33/34 同类），列由该表列头决定；UEMR_XDR 含 RSRP/SINR 等空口测量列，排查无线质量用它
- 点击任意记录行看全字段详情，可「存档」到本地库长期保留（上游只留 24~72 小时，过期就查不到了）；「已存记录」弹窗里另有查询历史（号码打码、按登录用户隔离，用于合规审计）

### 4.4 系统管理

#### 系统设置（`settings`）

系统设置：凭据、邮件收件人、远程主机、AI 模型、WhatsApp 登录、任务配置六个页签。

- 凭据：12 组上游账号，支持测试连接与显示明文（默认掩码；明文存于 db/app.db 的 credentials 表）
- 邮件收件人：分组编辑，可重置为默认
- 远程主机：改完即时生效无需重启（写 backend/data/settings.json）
- WhatsApp 登录：为 notify / bot 两个「已关联设备」网页扫码登录，点击后生成二维码，手机扫码即生效（旧凭据只改名备份，不删除）
- 任务配置：任务的业务参数（非排程），优先级 环境变量 > 配置文件 > 默认值

#### 门户一键登录（`portalLogin`）

门户一键登录：用已保存的凭据自动登录上游门户（Playwright 自动化），省去逐个手输账号口令。

- 点「登录」后轮询状态并打开门户窗口；「关闭窗口」可关掉会话
- 与系统设置共用同一份凭据；会话 cookie 缓存在后端 auth_cache/，请按敏感信息对待

---

## 5. 运维与排障

### 5.1 进程与端口速查

| 端口 | 进程 | 谁负责活着 |
| --- | --- | --- |
| `7038` | uvicorn / FastAPI 后端（/api/*、/docs） | backend_watchdog.py |
| `7090` | vite preview 前端（生产经 nginx /myapp/ 反代） | start_hidden.ps1 |
| `5432` | PostgreSQL 16 主库 | 自启脚本 pg_ctl 拉起 |
| `8787 / 8790` | FMS / VMAX 实时代理（仅 127.0.0.1） | backend 启动线程 |
| `—` | worker × 5 组（u/n/v/m/c，消费 task_queue） | worker_watchdog.py |

### 5.2 日常巡检（5 分钟）

- 任务管理页：有没有 failed、有没有长期 pending（失败聚合视图比翻列表快）
- 页头同步标签：GIS / TT&WO / Dashboard 的「最近同步」是否在预期窗口内
- 数据总览页：表数量与行数是否明显异常
- 命令行：五个关键进程是否都在、心跳 heartbeat_*.json 是否新鲜（超 3 分钟会被强杀重拉）
- 数据库新鲜度由 db_freshness_check 每小时 :15 自动巡检，滞后会给出调用链与排查方向；任务本身漏跑/停摆（未归组、无执行记录、队列滞留、成功逾期）也会在同一巡检里主动微信+邮件告警，不需要人工等看板空了才发现

### 5.3 日志速查

| 日志文件（log/） | 内容 |
| --- | --- |
| `log/worker_runtime*.log` | 任务执行主日志——排障首选，按 task_id 搜堆栈（每组 worker 一个文件：_u/_n/_v/_m/_c） |
| `log/backend_runtime.log` | 后端业务日志（API、调度、代理） |
| `log/backend_watchdog.log / worker_watchdog.log` | 进程拉起与崩溃退避记录（backend 连崩 10 次降级为慢速重试；worker 连崩 10 次摘除不再拉起） |
| `log/start_hidden_result.txt` | 上一次启动的逐条结果——启动失败先看这个 |
| `log/heartbeat_*.json` | 后端与 worker 心跳（15s 一次，超 3 分钟判 hung） |
| `log/*_console.log(.err)` | 各子进程 stdout/stderr |

> ⚠️ 全仓库没有日志轮转，`log/` 只会一直涨，需人工定期清理；部分日志报错原文含账号，外发前先扫一遍。

### 5.4 备份（三处都要备，缺一不完整）

- **远程 PostgreSQL（主库）**: pg_dump 备份业务数据与 task_queue/task_execution_log/task_schedule_config；pg_to_sqlite_sync 每小时 :45 已提供一份镜像到 db/app.db
- **db/app.db（SQLite）**: credentials 凭据表（明文）不随 PG 走——只备份 PG 会丢凭据，只备份 app.db 会丢业务数据，两者都要
- **data/ + backend/data/**: 各任务报表产物与 settings.json（丢 settings.json 会退回内置默认远程主机）
- **backend/services/*.json**: 上游连接参数与 TT 规则表等，属代码资产随仓库走

### 5.5 定期清理：什么能删、什么别动

**可以清理**

- 运行日志 log/*.log（大文件先停服务再清，避免句柄占用；没有日志轮转，会一直涨）
- 一次性调试产物：log/edge_cleanup*.txt、killlog*.txt、backend/restart_dbg.log 等
- 历史空库 data/app.db、data/my_app.db（0 字节）；旧构建目录 frontend/dist、dist2、dist3（删前确认 nginx 未指向）

**不要动**

- db/app.db —— 含凭据表（明文）与 PG 快照镜像，约 954MB，绝对不是垃圾文件
- backend/services/auth_cache/ —— 上游站点会话 cookie（等同有效登录态），不得外发
- data/ 下各任务目录 —— 报表产物与任务专用 SQLite
- backend/services/eflow_rules/eflow_TT_rules.xlsx —— 正式 TT 规则表（根目录同名文件只是副本）
- 历史拼写目录/文件名（data/packet_lost、battary_kpi_fetch、mw_ume_bw_ultilazation 等）——多处按字符串引用，不要顺手改名

### 5.6 配置与凭据

三层配置，优先级从高到低：环境变量（backend/.env，203 个键，改后需重启） > 数据库/配置文件（凭据、收件人、排程、远程主机、任务参数——界面改，即时生效） > 代码默认值。

- 12 个凭据分组：zte_ume、vmax_cxo、ipran_ume、ccn_ume、eflow、fms_portal、fw_kpi、mw_ume、sftp_sp、mail_126、owa_mail、weixin（系统设置 → 凭据 统一维护）
- 读取优先级：环境变量 > 数据库 > 空；列表接口返回掩码，「显示明文」与「测试连接」单独提供
- 凭据明文存于 db/app.db 的 credentials 表（credential_store 直连 SQLite，绕过 MY_APP_DB_MODE）——备份必带该文件，且按敏感介质保管
- backend/services/auth_cache/ 里的会话 cookie 等同有效登录态，不外发、不入 git、不进截图

---

## 6. 常见问题

**看板数据没有更新？**

① 先到「任务管理」查看对应任务的最近执行结果与失败聚合；② 检查顶栏「自动刷新」间隔是否被调成关闭；③ 注意部分数据本身低频同步：实时告警每分钟、微波拓扑每天 05:15、丢包每天 06:30、事件总览每小时第 20 分钟。仍不对可看「数据库数据新鲜度巡检」的执行日志，它会输出调用链与排查方向（含文件型数据源的落盘年龄）。

**页面数字与预期口径不一致？**

注意各页口径：电池看板默认只统计 24 小时内新鲜读数；MS SLA 看板以实时计算为准（可能与快照文件不一致）；丢包看板只展示最近 7 个完整自然日；CXO 看板内嵌快照，重跑同步任务才更新。

**任务长期停在 pending 不执行？**

多半是该任务未被归入任何 worker 组（GROUP_TASK_MAP），队列里永远无人认领——这是本项目已发生过四次的事故模式（finebi_report_sync、whatsapp_send_ext、sp_email_details，以及 2026-09-18 查出的 olib_soc 看板增量与 vmax_multi_data_sync）。新增任务必须在 worker_watchdog.py 的 GROUP_TASK_MAP 登记分组；陈旧 pending 占住的单飞名额 6 小时后会被 worker 自动过期释放。2026-09-18 起这类停摆不再靠人肉发现：db_freshness_check（每小时）会把未归组 / 无执行记录 / 队列滞留 / 成功逾期四类健康异常按翻转去重主动微信+邮件通知。

**任务反复 failed？**

到 log/worker_runtime*.log 找该 task_id 的堆栈（排障首选日志；每组 worker 一个文件，任务所属组见执行认领日志）。上游不可达 → 先到「系统设置 → 凭据」点「测试连接」；口令变了 → 更新凭据。auto_retry_failed 每 10 分钟自动重试（MAX_ATTEMPTS=2，超 24 小时放弃），无需手动反复点执行。

**任务一直「执行中」不动？**

调度器没有 per-task 超时（设计缺口）。僵尸运行态由 worker 每 300 秒扫描回收（30 分钟 + PID 存活核对），无需手工干预；若任务真在长跑（如 Playwright 探测），可在任务管理页手动「停止」。

**邮件没发出去？**

EWS 邮箱故障时邮件任务会失败，email_recovery（每 20 分钟）会在恢复后自动补发近 3 小时内失败的邮件——先查它的执行历史，而不是手动重跑原邮件任务。邮箱空间满由 mailbox_cleanup（每小时）守卫。

**如何在大屏/另一个标签页打开看板？**

右键点击左侧菜单项 → 「在新标签页打开」；或直接访问直链 http://<host>/myapp/?page=<key>。配合顶栏「自动刷新」即可长期挂机展示。

**上传的数据质量如何确认？**

「数据上传」页入库后会给出问题面板与质量评分；确认无问题后可到「表浏览器」查看数据与字段画像，再用「分析仪表盘」出图。

**忘记某个指标/术语的定义？**

多数看板的指标旁有口径说明图标（Metric Explain）；更完整的术语表与逐页手册见项目文档 docs/manual/（01-overview 术语表、11-feature-guide 功能页手册）。

---

*更多细节参见项目文档：docs/manual/（01 总览与术语表 · 04 任务系统 · 11 功能页手册 · 13 运维手册 · 14 外部系统与数据流）。*
