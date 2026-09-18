# 01 项目总览

## 一句话定位

my_app 是一个**单机的网络运维数据平台**：把 eFlow、各制式网管（UME/CNN/iPRAN/MW/EMS）、FineBI、FTP、邮箱等上游系统的数据按时抓回来，落进数据库，再产出**看板**、**Excel 报表**和**定时邮件/微信通知**。

它服务的是"每天要看板、要发报表、报表不能漏"的 NOC 运维场景，不是一个通用 BI 工具，也不是给外部用户注册的 SaaS。

## 能力边界

**它做什么**

- **41 个定时任务**驱动数据采集与报表投递（`backend/task_registry.py:72-403`）。
- **23 个功能页**在一个 SPA 里，中英文可切换（`frontend/src/App.tsx:68-70,182-206`）。
- 数据可**下钻**：看板上点指标弹出明细（TT&WO / 告警 / 丢包 / NUR / MS SLA / GIS 均为该模式）。
- 提供**通用表能力**：任意表浏览、字段画像、Excel/CSV 导入导出、视图模板（TableBrowser）。
- **自动补漏**：失败任务自动重试、漏跑任务自动补投（`backend/services/auto_retry.py:75-82`）。
- **进程自愈**：后端与 worker 各由看门狗托管，心跳超时即强杀重拉。

**它不做什么**（避免误解）

- **没有多用户体系**：没有注册、没有角色权限、没有审计日志。详见 `05-security-and-credentials.md`。
- **不对外提供 HTTPS**：后端直接明文 HTTP 监听，TLS 需由前置 nginx 终结。
- **不做数据编辑**：数据是"抓进来只读"的，页面上没有业务写回上游的能力（仅凭据、收件人、排程等配置可写）。
- **不是高可用服务**：单实例锁（`db/instance.lock`）保证同机只跑一份，没有集群与故障转移。

## 数据从哪来、到哪去

```
上游系统                     my_app                        出口
────────────────────────────────────────────────────────────────────
eFlow API/FTP      ─┐
RAN/CNN/iPRAN UME   ├─► 定时任务 ─► PostgreSQL(主) ─► API ─► 看板页面
MW UME / CN EMS    ─┤                    │                    │
FineBI FTP         ─┤                    └─► SQLite 快照      └─► 表浏览器
远程主机 FTP/SMB   ─┤                       (离线回退/备份)          下钻导出
Exchange/OWA 邮箱  ─┘                                                  │
                                                                       ▼
                                                          Excel 报表 + 邮件
                                                          微信/OpenClaw 通知
```

外部系统逐项清单见 `14-integrations.md`。

## 术语表

| 术语 | 含义（口径来源） |
| --- | --- |
| **TT** | Trouble Ticket，故障工单。eFlow 同步的核心对象之一 |
| **WO** | Work Order，工作单。`kpi_ms_wo_sla` 任务即统计 WO SLA |
| **SLA** | 服务等级协议达成率。MS SLA 看板 = MS Contract KPIs + MS WOs SLA（`backend/routers/ms_sla_dashboard.py:2`） |
| **NUR** | 网络不可用率。全网口径 `Σ(小区数×MTTR)×60 / (小区数×GR)`；站点级达标阈值 `NUR×100000 < 350`（`backend/services/nur_calc.py:367-373`）。有效 MTTR 限定 `>0 且 <43200 分钟`，未清除故障不计入（`nur_calc.py:304`） |
| **UME** | 网管系统统称（RAN UME / iPRAN UME / CNN UME / MW UME / FMS Portal），凭据按制式分组存储 |
| **eFlow** | ZTE 工单/告警平台，提供 TT/WO/CR/PM/Site/Person 接口与 FM Active/FM History 告警接口 |
| **FineBI** | 报表平台。my_app 从它的 FTP 调度目录定时抓取最新 Excel（`finebi_report_sync`） |
| **SP** | Spare Parts，备件/耗材。`sp_data_sync` / `sp_report_generate` / 仓库看板 |
| **CN EMS** | 华为/中兴之外的中文 EMS 采集源，原始 PM 文件服务器仅保留约 1 天，故需 15 分钟增量缓存（`task_registry.py:346-350`） |
| **MW UME** | ZXMW 微波网管，KPI 每日 05:15 入库，拓扑看板读 `mw_ume_bw_ultilazation` |
| **FW KPI** | 防火墙吞吐 KPI（`fw_kpi_sync`，含图表邮件） |
| **CXO** | 经营层看板，数据源是 VMAX 实时保障看板快照（`public/cxo_dashboard.html` 内嵌快照） |
| **丢包看板** | 数据源 `lte_pl.sqlite3`，STATUS 为 0~23 小时标志块，最近 3 天同整点丢包均 >0.5% 记 1（`frontend/src/pages/PacketLossDashboard.tsx:2-5`） |
| **worker 组 u/n/v/m/c** | 5 组独立 worker 进程，组内任务串行执行（`v`=VMAX 门户 8790 单会话，2026-09-18 从 `n` 拆出），见 `04-task-system.md` |
| **task_id** | 任务唯一键，同时是 URL 片段（`/api/tasks/{task_id}/run`）与队列表主键 |

## 阅读下一步

- 直接跑起来 → `10-quickstart.md`
- 先搞懂结构再动手 → `02-architecture.md`
