# my_app 使用帮助

> 面向使用者的平台功能与操作指南。本文件由「使用帮助」页面同源生成（frontend/src/helpMarkdown.ts），内容依据 docs/manual/ 各章与 backend/task_registry.py 整理。生成日期：2026-09-02。

> 站内入口：侧边栏「使用帮助」，或直链 `http://<host>/myapp/?page=help`。

---

## 目录

- [1. 平台简介](#1-平台简介)
- [2. 通用操作](#2-通用操作)
- [3. 任务管理详解（44 个任务）](#3-任务管理详解)
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
| 自动刷新 | 顶栏下拉选择间隔（默认 5 分钟，可选 0/30s~30min）；正在输入、弹窗打开或标签页在后台时本轮自动跳过，不打断操作。 |
| 主题与语言 | 右上角切换深/浅色主题与中/英文界面，偏好自动保存在本机（localStorage）。 |
| 数据新鲜度 | 部分页面页头显示「最近同步」时间。看板数据由定时任务写入，各任务频率不同（告警 30 分钟、微波拓扑每天 05:15、丢包每天 06:30 等），完整清单见「任务管理详解」。 |

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
| **m** | 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖 |
| **c** | CN EMS 独立会话：缓存同步与日聚合共享 _pmcache，同组保证互斥 |

> ⚠️ **新增任务必须同时登记进 `worker_watchdog.py` 的 `GROUP_TASK_MAP`** —— 只写 `TASK_SPECS` 不分组 = 任务入队后永远 pending。这是本项目已发生过三次的事故模式（finebi_report_sync / whatsapp_send_ext / sp_email_details）。

### 3.3 全量任务清单（44 个）

| 任务 | task_id | 默认 cron | 组 | 工作流脚本 |
| --- | --- | --- | --- | --- |
| eFlow 数据同步 | `eflow_sync` | `22 * * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")` |
| eFlow 每日全量同步 | `eflow_sync_full` | `0 1 * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")` |
| RAN UME 日报 | `ran_ume_daily` | `0 2 * * *` | u | `services/ran_ume_service.py → run_ran_ume_full_task` |
| Site Outage 截图 | `site_outage_screenshot` | `0 1 * * *` | m | `services/site_outage_service.py → run_site_outage_screenshot` |
| WhatsApp 消息发送 | `whatsapp_send` | `0 3 * * *` | m | `services/whatsapp_service.py → run_whatsapp_send` |
| WhatsApp 消息发送（扩展） | `whatsapp_send_ext` | `0 3 * * *` | m | `services/whatsapp_ext_service.py → run_whatsapp_send_ext` |
| MS SLA 完整同步 | `ms_sla_full` | `0 */6 * * *` | n | `services/ms_sla_service.py → run_full_sync` |
| eFlow 实时告警同步 | `eflow_active_alarm` | `*/30 * * * *` | n | `services/eflow_api_client.py → fetch_and_save_active_alarm` |
| eFlow 历史告警同步 | `eflow_history_alarm` | `0 */3 * * *` | n | `services/eflow_api_client.py → fetch_and_save_history_alarm` |
| eFlow TT 规则收集与匹配检查 | `eflow_tt_rules_check` | `20 4 * * *` | n | `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check` |
| RAN Main KPI 同步 | `main_kpi_sync` | `0 4 * * *` | u | `services/ran_ume_main_kpi.py → run_main_kpi_sync` |
| RAN 小区可用性 1-Day 同步 | `cell_availability_sync` | `30 4 * * *` | u | `services/ran_cell_availability_sync.py → run_cell_availability_sync` |
| RAN Network KPI 同步 | `network_kpi_sync` | `0 5 * * *` | u | `services/ran_ume_network_kpi.py → run_network_kpi_sync` |
| CNN UME KPI 同步 | `cnn_kpi_sync` | `0 6 * * *` | n | `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync` |
| SP 备件数据同步 | `sp_data_sync` | `0 7 * * *` | n | `services/get_sp_table.py → run_sp_data_sync` |
| iPRAN UME KPI 同步 | `ipran_kpi_sync` | `0 8 * * *` | u | `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync` |
| Liberia 宕站 1小时报告邮件 | `liberia_email_1h` | `5 * * * *` | m | `services/liberia_email_report.py → run_1h_report` |
| Liberia 宕站 8小时报告邮件 | `liberia_email_8h` | `10 */8 * * *` | m | `services/liberia_email_report.py → run_8h_report` |
| MS Contract KPIs 日报邮件 | `kpi_ms_contract` | `30 17 * * *` | m | `services/kpi_email_report.py → run_ms_contract_kpi` |
| MS WOs SLA 日报邮件 | `kpi_ms_wo_sla` | `35 17 * * *` | m | `services/kpi_email_report.py → run_ms_wo_sla` |
| SpareParts 备件报表邮件 | `kpi_sp_spareparts` | `45 9 * * *` | m | `services/kpi_email_report.py → run_sp_spareparts` |
| Comsumables 耗材报表邮件 | `kpi_sp_consumables` | `50 9 * * *` | m | `services/kpi_email_report.py → run_sp_consumables` |
| SP 备件报表生成 | `sp_report_generate` | `15 5 * * *` | m | `services/kpi_email_report.py → run_sp_report_generate` |
| SP 备件明细报表邮件 | `sp_email_details` | `0 7 * * *` | m | `services/kpi_email_report.py → run_sp_details_email` |
| MS Network Availability 日报邮件 | `kpi_ran_availability` | `30 9 * * *` | m | `services/kpi_email_report.py → run_ran_availability` |
| EWS 恢复后邮件补发 | `email_recovery` | `*/20 * * * *` | m | `services/email_recovery.py → run_email_recovery_task` |
| Packet Loss 丢包同步 | `packet_loss_sync` | `30 6 * * *` | u | `services/packet_loss_service.py → run_packet_loss_sync` |
| Packet Loss 丢包日报邮件 | `packet_loss_email` | `45 6 * * *` | u | `services/kpi_email_report.py → run_packet_loss_email` |
| IP RAN M6K-FW 图表邮件 | `ipran_m6k_chart_email` | `45 6 * * *` | m | `services/ipran_chart_service.py → run_ipran_m6k_chart_email` |
| CNN Free Rating 图表邮件 | `ccn_free_rating_chart_email` | `45 7 * * *` | m | `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email` |
| FW 吞吐 KPI 同步+图表邮件 | `fw_kpi_sync` | `15 7 * * *` | n | `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync` |
| 电池 KPI 同步 | `battery_kpi_sync` | `5 * * * *` | u | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync` |
| 电池 KPI 邮件 | `battery_email` | `0 7,19 * * *` | m | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email` |
| 邮箱空间清理 | `mailbox_cleanup` | `0 * * * *` | m | `services/mailbox_cleanup.py → run_mailbox_cleanup` |
| Incident Overview 数据同步 | `incident_overview_sync` | `0 * * * *` | m | `services/incident_overview_sync.py → run_incident_overview_sync` |
| FineBI 报表文件同步 | `finebi_report_sync` | `10 * * * *` | m | `services/finebi_report_sync.py → run_finebi_report_sync` |
| 数据库数据新鲜度巡检 | `db_freshness_check` | `15 * * * *` | m | `services/db_freshness_check.py → run_db_freshness_check` |
| 失败任务自动重试 | `auto_retry_failed` | `*/10 * * * *` | m | `services/auto_retry.py → run_auto_retry_task` |
| RAN CM 小区数据同步 | `cm_data_sync` | `30 8 * * *` | u | `services/cm_data/cm_data_export.py → run_cm_data_sync` |
| PG→SQLite 数据快照 | `pg_to_sqlite_sync` | `45 * * * *` | m | `backend/scripts/sync_pg_to_sqlite.py → main` |
| MW UME KPI 同步 | `mw_ume_kpi_sync` | `15 5 * * *` | n | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync` |
| MW UME KPI 实时同步 | `mw_ume_kpi_sync_rt` | `*/15 * * * *` | n | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt` |
| CN EMS KPI 缓存同步 | `ems_kpi_cache_sync` | `*/15 * * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync` |
| CN EMS KPI 日粒度CSV | `ems_kpi_daily` | `20 0 * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily` |

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

**功能**: eFlow 全量兜底：拉全量窗口（默认自 2026-01-01），补齐增量遗漏并刷新报告

**工作流与数据流**:

1. 每天 01:00 按全量窗口拉取全部记录
1. 与增量写同一批主库表，去重覆盖
1. 完成后刷新相关报告产物

**维护要点**:

- 白天发现 eFlow 缺数的首要修复手段，可在任务管理页手动执行一次
- 全量窗口起点可配置，调整时注意拉取时长

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

#### MS SLA 完整同步（`ms_sla_full`）

- 默认 cron: `0 */6 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ms_sla_service.py → run_full_sync`

**功能**: SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）

**工作流与数据流**:

1. 每 6 小时按 nur_calc 实时口径重算 NUR/SLA/WO 指标
1. 写 data/ms_sla/ms_sla_dashboard.sqlite3
1. 供 MS SLA 看板与两份日报邮件使用

**维护要点**:

- 看板数字以本任务的实时计算为准（与历史快照文件可能不一致）
- 口径调整改 backend/services/nur_calc.py

#### eFlow 实时告警同步（`eflow_active_alarm`）

- 默认 cron: `*/30 * * * *`　|　worker 组: **n**
- 工作流脚本: `services/eflow_api_client.py → fetch_and_save_active_alarm`

**功能**: 从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite

**工作流与数据流**:

1. 每 30 分钟拉 FM Active 活跃告警
1. 双写 app.db 的 realtime_alarm 与 eflow.sqlite3 副本（副本仅供报表）
1. 供实时告警看板 / 实时告警地图 / 告警管理看板使用

**维护要点**:

- 页面只读 app.db；「实时」即 30 分钟粒度，并非秒级推送
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

#### RAN Network KPI 同步（`network_kpi_sync`）

- 默认 cron: `0 5 * * *`　|　worker 组: **u**
- 工作流脚本: `services/ran_ume_network_kpi.py → run_network_kpi_sync`

**功能**: RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G × Group/NW），导出 Excel 并导入 SQLite + FTP 上传

**工作流与数据流**:

1. 登录 RAN UME（Zeenshan）按 Group/NW 维度查 Network KPI 历史
1. 导出 Excel、导入 SQLite、FTP 上传

**维护要点**:

- 查询模板在 services/network_kpi_config.json

#### CNN UME KPI 同步（`cnn_kpi_sync`）

- 默认 cron: `0 6 * * *`　|　worker 组: **n**
- 工作流脚本: `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync`

**功能**: CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN

**工作流与数据流**:

1. 登录 CNN UME 查核心网 KPI（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating）
1. 经 API 写入远程 DB CNN

**维护要点**:

- Free Rating 数据同时供 ccn_free_rating_chart_email 出图

#### SP 备件数据同步（`sp_data_sync`）

- 默认 cron: `0 7 * * *`　|　worker 组: **n**
- 工作流脚本: `services/get_sp_table.py → run_sp_data_sync`

**功能**: 从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db，并镜像写入 FineBI 服务器上的 WareHouseDashBoard/inventory.db

**工作流与数据流**:

1. 登录备件 SFTP（凭据分组 sftp_sp）
1. 拉取 Inbound/Outbound/Inventory/OC Rule/Transfer 5 份报表
1. 清洗后写主库，供仓库看板与 SP 报表使用
1. 全部落库后镜像写入 `\\DESKTOP-D4GF62\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db`（Inbound/Outbound/OC Rule/Transfer 整表替换；Inventory 按键只追加新行，不删改远端历史）

**维护要点**:

- 仓库看板 iframe 读的就是这批数据；报表缺失先看本任务是否成功
- FineBI inventory.db 镜像失败会在任务消息中提示（`镜像写入 FineBI inventory.db 失败: ...`），不影响 app.db；路径/开关在 Settings → 任务配置 → SP 备件数据（`mirror_db_path` / `mirror_enabled`）
- 远端库被 FineBI 占用读锁时靠 busy_timeout 自动等待；网络抖动整体重试 2 次

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

- 默认 cron: `5 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/liberia_email_report.py → run_1h_report`

**功能**: 发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单

**工作流与数据流**:

1. 每小时 :05 汇总最近 1 小时宕站数据
1. 生成内嵌图 + Excel 报表
1. 发送到主送/抄送名单（收件人在系统设置维护）

**维护要点**:

- EWS 不可用时漏发由 email_recovery（每 20 分钟）自动补发

#### Liberia 宕站 8小时报告邮件（`liberia_email_8h`）

- 默认 cron: `10 */8 * * *`　|　worker 组: **m**
- 工作流脚本: `services/liberia_email_report.py → run_8h_report`

**功能**: 发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单

**工作流与数据流**:

1. 每 8 小时（00/08/16 时 :10）汇总窗口内宕站数据
1. 生成内嵌图 + Excel 报表并发送

**维护要点**:

- 与 1 小时版同一脚本不同入口；收件人名单改动后两种报表同时生效

#### MS Contract KPIs 日报邮件（`kpi_ms_contract`）

- 默认 cron: `30 17 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_ms_contract_kpi`

**功能**: 发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）

**工作流与数据流**:

1. 读取 ms_sla_full（每 6 小时）产出的本地 ms_sla 数据
1. 生成 Contract KPIs 日报
1. 发送到远程名单中的收件人

**维护要点**:

- 数据来自 ms_sla_full；17:30 发送时用的是 16:00 那一轮同步的数

#### MS WOs SLA 日报邮件（`kpi_ms_wo_sla`）

- 默认 cron: `35 17 * * *`　|　worker 组: **m**
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
1. 落盘 data/sp_email 供 09:45/09:50 两个邮件任务与 07:00 明细邮件使用

**维护要点**:

- 是 3 个 SP 邮件任务的上游，失败会导致当天备件邮件整体缺报

#### SP 备件明细报表邮件（`sp_email_details`）

- 默认 cron: `0 7 * * *`　|　worker 组: **m**
- 工作流脚本: `services/kpi_email_report.py → run_sp_details_email`

**功能**: 每天 07:00 把 data/sp_email/data 下 4 份备件明细（inventory/inband/outband/transfer）合并为一个 Excel（sheet: Inventory/Inbound/Outbound/Transfer），附件名与主题均携带发送时间戳发送

**工作流与数据流**:

1. 收集 data/sp_email/data 下 4 份 *_details.xlsx（inventory/inband/outband/transfer）
1. 合并为 `SP Details Report <YYYY-MM-DD HH-MM-SS>.xlsx`（4 个 sheet，保持原始明细内容）
1. 以主题 `SP Spare Parts Details Report <YYYY-MM-DD HH-MM-SS>` 发送（默认收件人为固定地址，可在系统设置 → 邮件收件人覆盖）

**维护要点**:

- 2026-09-01 上线时曾漏分组导致 pending 卡死，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP

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

- 默认 cron: `*/20 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/email_recovery.py → run_email_recovery_task`

**功能**: 每 20 分钟探测 EWS 是否恢复；恢复后自动补发近 3 小时内因 EWS 超时失败的邮件任务

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

- 默认 cron: `0 7,19 * * *`　|　worker 组: **m**
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

- 默认 cron: `0 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/incident_overview_sync.py → run_incident_overview_sync`

**功能**: 每小时整点从 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，版本化落盘 + current.json 指针

**工作流与数据流**:

1. 每小时整点扫描 FineBI FTP 的 TT_WO/ 全部子目录
1. 取最新 incident_overview.xlsx 落盘为版本化文件 + current.json 指针
1. best-effort 刷新 incident_overview.xlsx 快照，供事件总览页使用

**维护要点**:

- 版本化设计使上游 Excel 被打开占用时也不会取数失败——这是历史踩坑后的修复，勿改回直接覆盖

#### FineBI 报表文件同步（`finebi_report_sync`）

- 默认 cron: `10 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/finebi_report_sync.py → run_finebi_report_sync`

**功能**: 每小时从 FineBI FTP /webroot/WEB-INF/schedule 的每个子文件夹取最新一份 Excel，下载到本地 data/finebi_reports 供任务报告文件页下载

**工作流与数据流**:

1. 每小时 :10 遍历 schedule 下每个子文件夹
1. 各取最新一份 Excel 下载到 data/finebi_reports
1. 「任务报告文件 → FINEBI report」页签展示与下载

**维护要点**:

- 2026-08-25 分组模式启用时曾因未归组而 pending 卡死断档，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP

#### 数据库数据新鲜度巡检（`db_freshness_check`）

- 默认 cron: `15 * * * *`　|　worker 组: **m**
- 工作流脚本: `services/db_freshness_check.py → run_db_freshness_check`

**功能**: 每小时巡检远程 DB（db_writer_api）与本地回退库各表最新数据日期，滞后时输出调用链路与检查方向

**工作流与数据流**:

1. 每小时 :15 巡检远程库与本地回退库各表的最新数据日期
1. 滞后时在执行日志输出调用链与排查方向

**维护要点**:

- 怀疑「某类数据停更」时先看它的执行历史，按给出的调用链排查，比翻任务列表快

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

- 默认 cron: `15 5 * * *`　|　worker 组: **n**
- 工作流脚本: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync`

**功能**: MW UME（ZXMW 微波）KPI 历史指标同步（FINBI 模板 1 天粒度），内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation

**工作流与数据流**:

1. 每天 05:15 经 FINBI 模板导出 1 天粒度 KPI（内存处理，不落临时文件）
1. 按 Begin Time + 元素标识列联合去重后写主库 mw_ume_bw_ultilazation

**维护要点**:

- 微波拓扑看板一天只变一次（05:15 后）；表名 ultilazation 是历史拼写，勿改

#### MW UME KPI 实时同步（`mw_ume_kpi_sync_rt`）

- 默认 cron: `*/15 * * * *`　|　worker 组: **n**
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

### 3.4 可靠性机制（超时 / 重试 / 自愈）

| 机制 | 说明 |
| --- | --- |
| **僵尸 running 回收** | 无 per-task 超时（设计缺口）。worker 每 300s 扫描：running 超 30 分钟（STALE_RUNNING_SECONDS）且 PID 已死亡的记录按失败回收。 |
| **失败自动重试** | auto_retry_failed 每 10 分钟扫描：失败任务先判断数据缺口是否已被后续成功执行补上，未补上且未超 MAX_ATTEMPTS=2 才重投；超过 24h 硬上限直接放弃。 |
| **漏跑补投** | 时效窗口内应触发却完全没有执行记录的任务自动补投一次（MISS_GRACE_MIN=15 宽限；邮件类默认排除，由 EWS 补发机制负责）。 |
| **失败通知** | 任务失败经微信 + 邮件双通道告警（services/weixin_notifier.py 支持 openclaw/wecom/serverchan/pushplus）。 |
| **进程自愈** | backend_watchdog / worker_watchdog 托管进程：端口探活、崩溃退避重拉（连崩 10 次放弃并告警）；心跳 log/heartbeat_*.json 超 3 分钟未更新判定 hung 强杀重拉。 |
| **保留期** | task_queue 与 task_execution_log 保留 3 天（task_runner.py / worker.py 自动清理），无需手工。 |

### 3.5 任务维护指南

**改排程（cron）** 「任务管理 → 排程」弹窗修改，写入主库 task_schedule_config 表，立即生效、重启不丢；无需改代码。

**改业务参数** 「系统设置 → 任务配置」页签（注意在系统设置里，不在任务管理页）。优先级：环境变量 > 配置文件 > 默认值。

**改上游账号口令** 「系统设置 → 凭据」选分组更新，点「测试连接」验证（凭据明文存于 db/app.db 的 credentials 表，缓存 30s）。

**改收件人** 「系统设置 → 邮件收件人」分组编辑，可重置默认；改完对所有 kpi_* / *_email 任务生效。

**手动执行 / 停止** 任务管理页「执行」立即投递一次、「停止」中断长任务。验证新排程/新脚本后应先手动跑一次看执行历史。

**新增一个任务** ① task_registry.py 的 TASK_SPECS 追加声明（task_id/name/cron/loader）；② worker_watchdog.py 的 GROUP_TASK_MAP 登记分组（漏了永远 pending，已三次踩坑）；③ 业务函数放 backend/services/ 且抛异常不吞；④ stop.bat → start.bat 重启加载注册表；⑤ 手动执行验证并更新文档（04-task-system.md 清单与本帮助页）。

**改工作流脚本** 脚本都在 backend/services/ 下（任务清单有对应路径）。改动时注意：① 别改历史拼写名（packet_lost、battary_kpi_fetch、ultilazation 等，多处按字符串引用）；② 动态采集表不进 Alembic；③ 同步更新 task_registry.md / WORKER.md / 本帮助数据（frontend/src/pages/helpTaskDocs.ts）。

**任务卡 pending / failed 排查顺序** ① pending 不动 → 查是否漏分组；② failed → log/worker_runtime.log 找 task_id 堆栈 → 凭据「测试连接」；③ 数据停更 → db_freshness_check 的执行历史有调用链。

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
- 「全局历史」跨任务检索执行记录；任务完成后语音播报可在本页开关

#### 任务报告文件（`email_reports`）

汇总三类任务产物并供下载：邮件发送的最新报告附件、FineBI FTP 报表、eFlow TT 规则检查结果（规则表/矫正表/报告）。

- 顶部页签切换类别，点文件名或「下载」保存；可设每类保留最近 N 份
- eFlow 规则页签可「立即执行」手动触发一次检查（3 秒后自动刷新一次，任务慢时需手动再刷）

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
- 「实时」数据来自 eFlow 活动告警（eflow_active_alarm 每 30 分钟同步），并非秒级推送

#### TT&WO 看板（`ttwo`）

故障工单（TT）与工作单（WO）的处理量、时效、积压趋势分析。

- 下拉 + 分段控件 + 日期区间组合筛选，点数字下钻明细
- 页头显示数据最近同步时间；数据来自 eFlow 每小时同步（eflow_sync）与每日全量兜底（eflow_sync_full）

#### NUR 看板（`nur`）

网络不可用率（NUR）的日/周/月趋势、多维分析与站点达标情况。

- 切换粒度与日期区间，多维下拉筛选
- 点数字下钻明细表（支持列内筛选与排序），可一键导出 Excel

#### MS Operation KPI 看板（`ms_sla`）

MS 合同 KPI 与工单 SLA 达成情况：NUR / SLA / Network KPI / Per-Site / WO SLA（指标为行、期间为列）。

- 粒度只有日/月两档；下钻明细与 NUR 页一致
- 数字以 nur_calc 实时计算为准（ms_sla_full 每 6 小时驱动），可能与历史快照文件不一致——以本页为准

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

#### 丢包看板（`packet_loss`）

LTE 丢包看板（RAN UME SDR / IPRAN IPPD）：最近 7 个完整自然日、小时粒度，当天没过完不展示。

- 口径与 Packet_Loss 自动化 Excel 报告完全一致；Popover 可查看口径说明
- Switch 控制是否包含 OK 站点；支持下钻明细与拓扑叠加

#### 电池看板（`battery`）

站点电池健康度 / SOC / 充放电状态与告警明细。

- 第一维度是「数据新鲜度」：默认只统计 24 小时内的新鲜读数（battery_kpi_sync 每小时 :05），关闭「仅新鲜」会混入旧数据导致失真
- 点站点名下钻电池明细与历史读数；支持导出 Excel

#### GIS地图（`gis`）

站点地图：告警/工单在地图上的分布、拓扑线、区域面与多维筛选（历史/工单口径）。

- 区域下拉 + 图层 Tag 开关筛选；图例点击可隐藏该类图层；时间支持分段切换与自定义区间
- 点站点打开右侧抽屉，四个页签明细可搜索、可导出 Excel

#### 实时告警地图（`realtime_alarm`）

GIS 地图的实时模式：当前活跃告警站点的地图分布（带红色「实时」标识）。

- 操作与 GIS 地图页一致
- 数据来自 eFlow 活动告警（eflow_active_alarm），每 30 分钟同步一次

#### 事件总览（`incident_overview`，iframe 页）

OLR 事件（Incident）总览看板：卡片、矩阵、SLA 图表、分页明细与地图。

- 数据每小时整点由 incident_overview_sync 从 FineBI FTP 取最新 incident_overview.xlsx（版本化落盘，上游文件被占用也不会取数失败）

#### 仓库看板（`warehouse`，iframe 页）

备件/耗材库存看板（Spare Management），与原工具看板完全一致。

- 数据来自 sp_data_sync（每天 07:00 从 SFTP 拉取的 5 份备件报表）
- 按仓库/备件类型查看库存与明细

### 4.3 分析与工具

#### eFlow 知识库（`eflow_qa`）

eFlow TT 判定规则知识库：规则/案例文档全文检索，并内置 TT 快速分析。

- 空格分隔多关键词检索，或从左侧目录选择文章
- 输入 TT 单号一键分析：派单归属、时间差、根因分布与结论要点

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

### 4.4 系统管理

#### 系统设置（`settings`）

系统设置：凭据、邮件收件人、远程主机、任务配置四个页签。

- 凭据：12 组上游账号，支持测试连接与显示明文（默认掩码；明文存于 db/app.db 的 credentials 表）
- 邮件收件人：分组编辑，可重置为默认
- 远程主机：改完即时生效无需重启（写 backend/data/settings.json）
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
| `—` | worker × 4 组（u/n/m/c，消费 task_queue） | worker_watchdog.py |

### 5.2 日常巡检（5 分钟）

- 任务管理页：有没有 failed、有没有长期 pending（失败聚合视图比翻列表快）
- 页头同步标签：GIS / TT&WO / Dashboard 的「最近同步」是否在预期窗口内
- 数据总览页：表数量与行数是否明显异常
- 命令行：五个关键进程是否都在、心跳 heartbeat_*.json 是否新鲜（超 3 分钟会被强杀重拉）
- 数据库新鲜度由 db_freshness_check 每小时 :15 自动巡检，滞后会给出调用链与排查方向

### 5.3 日志速查

| 日志文件（log/） | 内容 |
| --- | --- |
| `log/worker_runtime.log` | 任务执行主日志——排障首选，按 task_id 搜堆栈 |
| `log/backend_runtime.log` | 后端业务日志（API、调度、代理） |
| `log/backend_watchdog.log / worker_watchdog.log` | 进程拉起与崩溃退避记录（连崩 10 次放弃并告警） |
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

三层配置，优先级从高到低：环境变量（backend/.env，147 个键，改后需重启） > 数据库/配置文件（凭据、收件人、排程、远程主机、任务参数——界面改，即时生效） > 代码默认值。

- 12 个凭据分组：zte_ume、vmax_cxo、ipran_ume、ccn_ume、eflow、fms_portal、fw_kpi、mw_ume、sftp_sp、mail_126、owa_mail、weixin（系统设置 → 凭据 统一维护）
- 读取优先级：环境变量 > 数据库 > 空；列表接口返回掩码，「显示明文」与「测试连接」单独提供
- 凭据明文存于 db/app.db 的 credentials 表（credential_store 直连 SQLite，绕过 MY_APP_DB_MODE）——备份必带该文件，且按敏感介质保管
- backend/services/auth_cache/ 里的会话 cookie 等同有效登录态，不外发、不入 git、不进截图

---

## 6. 常见问题

**看板数据没有更新？**

① 先到「任务管理」查看对应任务的最近执行结果与失败聚合；② 检查顶栏「自动刷新」间隔是否被调成关闭；③ 注意部分数据本身低频同步：实时告警每 30 分钟、微波拓扑每天 05:15、丢包每天 06:30、事件总览每小时整点。仍不对可看「数据库数据新鲜度巡检」的执行日志，它会输出调用链与排查方向。

**页面数字与预期口径不一致？**

注意各页口径：电池看板默认只统计 24 小时内新鲜读数；MS SLA 看板以实时计算为准（可能与快照文件不一致）；丢包看板只展示最近 7 个完整自然日；CXO 看板内嵌快照，重跑同步任务才更新。

**任务长期停在 pending 不执行？**

多半是该任务未被归入任何 worker 组（GROUP_TASK_MAP），队列里永远无人认领——这是本项目已发生过三次的事故模式（finebi_report_sync、whatsapp_send_ext、sp_email_details）。新增任务必须在 worker_watchdog.py 的 GROUP_TASK_MAP 登记分组。

**任务反复 failed？**

到 log/worker_runtime.log 找该 task_id 的堆栈（排障首选日志）。上游不可达 → 先到「系统设置 → 凭据」点「测试连接」；口令变了 → 更新凭据。auto_retry_failed 每 10 分钟自动重试（MAX_ATTEMPTS=2，超 24 小时放弃），无需手动反复点执行。

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
