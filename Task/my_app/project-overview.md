# 04 project-overview.md —— 项目整体说明

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\project-overview.md`

> **本文是入口页，不重复手册内容。** 详细说明以手册为权威：
> - 项目定位、能力边界、术语表 → `docs\manual\01-overview.md`
> - 23+ 个功能页逐个说明（按导航顺序）→ `docs\manual\11-feature-guide.md`
> - 面向使用者的一站式帮助（44 个任务工作流、25 个页面指南、FAQ）→ `docs\manual\15-user-help.md`（英文版 `15-user-help-en.md`）

## 一、项目定位

**my_app / Data Insight MVP** 是利比里亚电信网络运维的**自研数据平台**，也是整个 RPA 工作区的**数据底座**。

它解决的问题是：网络运维数据散落在多个上游系统（UME、eFlow、CCN、PM、邮件、WhatsApp 等），口径不一、取用困难。my_app 把这些数据**统一采集、入库、计算、展示**，并提供定时任务自动化。

## 二、能力边界

| 做什么 | 不做什么 |
| --- | --- |
| 从上游系统定时采集数据并入库 | **不**替代上游系统（不反向写回 UME/eFlow 等） |
| 计算 KPI、SLA、告警、库存等指标 | **不**做 FineBI 那样的自助式 BI 建模 |
| 提供 23+ 个业务功能页 | **不**做通用报表设计器 |
| 定时任务调度与执行（44+ 任务） | **不**引入 Redis/RabbitMQ（队列用 SQLite 表） |
| 邮件/WhatsApp 报表分发 | — |

> 完整术语表见 `docs\manual\01-overview.md`。

## 三、技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI + SQLAlchemy + Alembic + APScheduler |
| 数据库 | SQLite（主）/ PostgreSQL（双模，`MY_APP_DB_MODE`） |
| 前端 | React + Vite + TypeScript + ECharts |
| 任务执行 | 独立 worker 进程（分组）+ 双层看门狗 |
| 队列 | SQLite `task_queue` 表（`pending/running/done/failed`） |

## 四、功能模块（按业务域）

> 逐页说明见 `docs\manual\11-feature-guide.md`。页面 key 用于门户直链 `?page=<PageKey>`。

| 业务域 | 页面 key（部分） |
| --- | --- |
| 数据同步与任务 | `sync`、`tables`、`upload`、`archive` |
| 告警与故障 | `alarm`、`realtime_alarm`、`alarmManagement`、`incident_overview` |
| 工单流程 | `ttwo`、`nur` |
| 网络性能 KPI | `packet_loss`、`ip_trace`、`gis`、`dashboard` |
| MS SLA / 合同报表 | `ms_sla`、SP 系列报表、FME 工程师排名 |
| 资源与供应链 | `warehouse` |
| 电源 | `battery` |
| 管理与设置 | `settings`、`overview`、`cxoDashboard` |
| 知识问答 | eFlow Q&A |
| 邮件 / WhatsApp | 收件人设置、邮件报表、WhatsApp 通知 |

## 五、部署与访问

| 项 | 值 |
| --- | --- |
| 前端 | vite `7090`，`base=/myapp/`，产物目录 **`_fe_dist`** |
| 后端 | uvicorn `7038` |
| 对外入口 | `192.168.100.19:80` nginx 反代 `/myapp/` 与 `/api/` |
| 页面直链 | `http://192.168.100.19/myapp/?page=<PageKey>`（**查询参数，非 hash 路由**） |
| 远端 DB 写入服务 | `8765` |

细节见 `architecture.md` 与 `D:\01_RPA\architecture.md`。

## 六、上游系统

完整清单与数据流方向见 `docs\manual\14-integrations.md`。概览：

| 上游 | 用途 |
| --- | --- |
| **UME** | 网管系统，KPI 与大屏数据 |
| **eFlow** | 工单流水（`eflow_tt`） |
| **CCN** | KPI 数据 |
| **PM (cn_ems)** | 性能数据 |
| **FineBI** | 既有报表平台（**正在迁移为 my_app 自研页面**） |
| **邮件 / WhatsApp** | 报表分发通道 |

## 七、三种读者怎么用这套文档

| 你是 | 从这里开始 |
| --- | --- |
| **第一次接触项目** | `docs\manual\01-overview.md` → `10-quickstart.md` → `11-feature-guide.md` |
| **要改代码/加功能** | `docs\manual\02-architecture.md` → `03-data-layer.md` → `04-task-system.md` → `05-security-and-credentials.md` |
| **系统出问题/要看日志** | `docs\manual\13-operations.md`（先查排障 FAQ）→ `12-configuration.md` → `90-appendix.md` |

（这三条路径是 `docs\manual\README.md` 官方定义的三条阅读路径。）

## 八、"现状" vs "历史"（重要）

| 文件 | 装什么 | 什么时候看 |
| --- | --- | --- |
| **`docs\manual\`** | 项目**现在是什么样**、**怎么用**、**怎么运维** | 上手、日常使用、排障 |
| **`PROJECT_DOCS.md`** | 历史**计划、评估、复盘、审计报告**（迁移计划、架构论证、i18n 审计、失败复盘） | 想知道"当初为什么这么做/踩过什么坑" |

> **手册只写已被代码验证的现状；`PROJECT_DOCS.md` 是历史档案。** 不要把现状写回 `PROJECT_DOCS.md`。

## 九、相关文档

| 内容 | 去哪里 |
| --- | --- |
| AI 上手须知（约束与地图） | `AGENTS.md` |
| 手册导航 | `docs\manual\README.md` |
| 项目定位与术语表 | `docs\manual\01-overview.md` |
| 逐页功能说明 | `docs\manual\11-feature-guide.md` |
| 使用者一站式帮助 | `docs\manual\15-user-help.md` |
| 架构与数据流 | `architecture.md` |
| 开发与回归 | `development.md` |
| 当前任务 | `TODO.md` |

> **工具负责整理，人与 AI 负责协作执行。**
