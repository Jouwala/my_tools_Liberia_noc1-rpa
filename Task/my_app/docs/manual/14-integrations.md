# 14 外部系统与数据流

my_app 本身不产生数据，它的价值取决于上游是否连得通。本章列出所有对接方、方向、参与任务与凭据分组。**内网地址、端口、账号一律不写**，具体值看「系统设置 → 凭据」和 `services/*_config.json`。

## 上游（读）

| 系统 | 方向与方式 | 相关任务 | 凭据分组 | 喂给哪些页面 |
| --- | --- | --- | --- | --- |
| **eFlow**（工单/告警平台） | API（TT/WO/CR/PM/Site/Person）+ FM Active/FM History 告警 + FTP 导出 | `eflow_sync`、`eflow_sync_full`、`eflow_active_alarm`、`eflow_history_alarm`、`eflow_tt_rules_check` | `eflow` | 任务报告文件、实时告警看板、TT&WO、GIS 两页、告警管理。**告警级别判定走程序化规则匹配，AI 仅承担自然语言解释**，选型依据见 [17-rule-engine-vs-llm.md](17-rule-engine-vs-llm.md) |
| **RAN UME** | 网管查询 API，RSA 加密登录 | `ran_ume_daily`、`main_kpi_sync`、`cell_availability_sync`、`network_kpi_sync`、`cm_data_sync`、`packet_loss_sync`、`battery_kpi_sync` | `zte_ume` | TT&WO、NUR、MS SLA、丢包、电池、GIS |
| **iPRAN UME** | 同上 | `ipran_kpi_sync`、`ipran_m6k_chart_email` | `ipran_ume` | iPRAN 相关 KPI 与图表邮件 |
| **CNN UME** | 同上 | `cnn_kpi_sync`、`ccn_free_rating_chart_email` | `ccn_ume` | Free Rating 图表邮件 |
| **MW UME**（ZXMW 微波） | FINBI 模板导出，1 天粒度，**内存处理不落盘**，直写 `mw_ume_bw_ultilazation` | `mw_ume_kpi_sync`（每天 05:15） | `mw_ume` | MW 微波拓扑 |
| **MW UME**（ZXMW 微波） | 同一 FINBI 模板，`gr=900` 15 分钟粒度，取最近 2 小时，直写 `mw_ume_bw_ultilazation_rt` | `mw_ume_kpi_sync_rt`（每 15 分钟） | `mw_ume` | MW 微波实时 |
| **CN EMS** | SFTP 取原始 PM 文件；**服务器只保留约 1 天**，故每 15 分钟增量缓存到 `_pmcache` | `ems_kpi_cache_sync`、`ems_kpi_daily` | （`services/cn_ems/ems_config.json` 内） | CN EMS KPI 相关 |
| **FW**（防火墙吞吐） | 网管 KPI + 出图 | `fw_kpi_sync` | `fw_kpi` | FW 图表邮件 |
| **FMS Portal** | 门户登录 + 实时抓取（经 `127.0.0.1:8787` 实时代理） | 实时代理线程 | `fms_portal` | 实时告警看板、实时告警地图 |
| **VMAX** | 实时保障看板（经 `127.0.0.1:8790` 代理），快照内嵌在 `cxo_dashboard.html` | 代理线程 | `vmax_cxo` | CXO 经营看板 |
| **VMAX（DIM 明细查询）** | 同一 8790 代理打 `/query/v2/history`（RSA `encryptLong` 参数），取 `1hour` 明细本地聚合为日值（共 **50 个指标**：6 个 CXO 趋势 + 14 个网络 KPI + 30 个服务/OTT KPI；汇总/视频类走 `interfaceid=11&rat=6`，RAN 网络类与服务/OTT 类走空过滤）。指标按监控**多列合批**取数（每周期仅 8 个请求，实测 14 列一次返回 0.06s），**响应列顺序由服务端决定、与请求顺序不同，必须按列名映射**。日值口径：流量/次数 SUM、用户数 PEAK、其余率/时延/吞吐/MOS/频次一律取未加权小时均值。**上游无天粒度、明细仅保留约 8 天**，故必须每日落盘累积 | `vmax_cxo_daily_sync`（每小时 :15，v 组） | `vmax_cxo` | VMAX CXO 天粒度看板（`vmaxCxoDashboard_Daily`，页签与参考看板 `vmaxCxoDashboard` 一致：汇总 / 网络（5 子页签）/ 服务（9 子页签）） |
| **VMAX（数仓 GBase 直连）** | MySQL 协议直连数仓 **GBase 8a**（`10.123.255.12:5258`，库 `zxvmax`，pymysql），按 `_day_` 分区表逐日取数：9 段业务 SQL 移植自用户 notebook `OLIB SOC VMAX Routine Report`（流量/活跃用户/缓存/核心网/视频/游戏/TCP/TOP业务/TOP视频）。**明细只保留约 90 天**；当天分区持续累积，故只统计已完成日。日粒度 KPI 落 `data/olib_soc_report/olib_soc_report.sqlite3` 的 `daily_kpi` 表（原始值落库、占比类查询时现算，保证周汇总精确加权） | `olib_soc_vmax_report`（每月 1 日 07:30）、`olib_soc_kpi_daily_sync`（每天 06:20，只补缺口） | `vmax_gbase` | VMAX 90 天经营看板（`vmaxCxoDashboard_90Days`：CEO 卡片 + 业务/网络质量趋势 + 近 14 天明细）、OLIB SOC VMAX 月报 Excel |
| **VMAX（CCA 用户查询）** | 门户接口直连（独立登录，不经 8790 代理），CCA 投诉页前端协议复刻：RSA `encryptedStr` GET 信封（与 vReport 同一把静态公钥，复用 `encrypt_long`）+ `X-Content-Type` 头。按号码查 `query_imsimdn`（用户/IMSI）与 `query_terminal`（终端），只读透传不落库、无定时任务。协议记录见 `backend/services/vmax_cca/README.md` | 无（页面查询即时触发） | `vmax_cca` | VMAX 用户查询（`vmax_user_query`） |
| **FineBI** | FTP 读 `/webroot/WEB-INF/schedule` 各子目录最新 Excel | `finebi_report_sync`、`incident_overview_sync` | `sftp_sp` 体系/FTP 变量 | 任务报告文件、事件总览、丢包/仓库 |
| **远程主机（文件与 DB 写入服务）** | FTP/SMB + HTTP 写库 API（`DB_WRITER_PORT`=8765、`FTP_PORT`=21）。地址由「系统设置 → 远程主机」维护，改后即时生效 | `cm_data_sync`、`sp_data_sync`、各报表上传 | `sftp_sp` | 几乎所有采集任务的落库/上传 |
| **Exchange / OWA 邮箱** | `exchangelib`（EWS）读邮件附件、清理空间 | `mailbox_cleanup`（每小时）、`email_recovery`（每 20 分钟） | `owa_mail` | 任务报告文件 |
| **126 邮箱** | SMTP 发送 | 多个邮件任务 | `mail_126` | — |
| **GeoIP / 拓扑文件** | 本地 Excel `db/ZTE OLR MS MW Topology _OSS.xlsx` | `backend/import_topology.py:11` | — | GIS、MW 拓扑 |

## 下游（写/发）

| 出口 | 方式 | 来源 |
| --- | --- | --- |
| **报表邮件** | 多个 `kpi_*` / `*_email` 任务发 Excel/图表邮件 | 收件人来自「系统设置 → 收件人」（`email_reports/` 下的 `cc_email.txt`、`ss_email.txt` 及子目录同名文件） |
| **微信 / OpenClaw 通知** | `services/weixin_notifier.py:5,29,43` 支持 `openclaw` \| `wecom` \| `serverchan` \| `pushplus` 四种通道；OpenClaw 走本机 npm 全局 CLI + Node v24 | 任务失败告警、报表完成通知 |
| **WhatsApp** | `whatsapp_send` 发 Site Outage 截图与文件（依赖 `site_outage_screenshot` 先出图） | 同组 `m` 内串行保证顺序 |
| **FTP 上传** | 报表产物回传远程主机目录 | 各报表任务 |
| **`email_reports/` 目录** | 邮件发送实现集（**5 种发送通道对比见 `email_reports/EMAIL_SEND_MODES.md:1-20`**）。要改"怎么发信"先看这份对比，别直接改任务代码 | — |

## 发送通道选型（照抄自 `EMAIL_SEND_MODES.md`）

同一份报表有 5 条可选投递路径，可靠性/依赖/是否留痕各不相同。**新项目默认沿用现有任务的通道**，改动前先读那份对比，理由是历史上换通道踩过坑（EWS 不可用 → 才有 `email_recovery` 补发机制与 `mailbox_cleanup` 空间守卫）。

## 上游不可用时怎么表现

| 上游 | 表现 | 自愈手段 |
| --- | --- | --- |
| eFlow / UME 会话被踢 | 该组任务连续 failed | `auto_retry_failed` 每 10 分钟重试，`MAX_ATTEMPTS=2`、超 24h 放弃 |
| Exchange(EWS) 挂了 | 邮件漏发 | `email_recovery` 恢复后补发（每 20 分钟） |
| 远程主机不可达 | 写库失败、新鲜度巡检告警 | `db_freshness_check` 会输出调用链与检查方向 |
| FineBI 文件被占用 | 曾导致取数失败 | 已改为"版本化文件 + `current.json` 指针"，Excel 一直开着也不会失败 |
| CN EMS 原始文件被服务端清掉 | 历史 KPI 缺失 | 靠 15 分钟增量缓存抢在服务端清理前保住 |

**共同缺口**：调度器**没有 per-task 超时**，卡死的上游会让任务挂着直到 30 分钟僵尸回收（`04-task-system.md`）。

## 接入一个新的上游系统（检查清单）

1. 凭据分组：在 `credential_store.py` 注册组元数据（`key`/`name`/`usage`/`user_label`/`secret_label`/`env_user`/`env_secret`/`testable`），使「系统设置 → 凭据」能填能测。
2. 采集模块放 `backend/services/`，**抛异常**而不是返回错误码（否则重试与失败通知都不生效）。
3. 注册 `TASK_SPECS` + **选定 `GROUP_TASK_MAP` 分组**（同会话互斥的必须同组；漏分组 = 入队后无 worker 认领、永远 pending 且不报错，已踩四次）。守卫：`tests/test_worker_group_coverage.py`（任务覆盖/重复/幽灵 id + 三处组集合一致 + 8790 任务同组 + 前端任务帮助一致，`python tests\test_worker_group_coverage.py` 直跑）；新建组要同步 `start_hidden.ps1` 的 `MY_APP_WORKER_GROUPS` 与 `restart_workers.py` 的 `ALL_GROUPS`，并把该任务写进 `frontend/src/pages/helpTaskDocs.ts`。
4. 若需要新库表：结构表走 Alembic；动态采集表按 `03-data-layer.md` 约定不进 migration。
5. 产物若供页面下载，落到 `data/<task_id>/` 并在任务报告文件页登记。
6. 更新本章表格与 `04-task-system.md` 的任务清单。
7. **文档里不写内网地址与口令**，只写分组 key 与配置字段名。
