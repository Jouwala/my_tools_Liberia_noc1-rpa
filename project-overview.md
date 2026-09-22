# 04 project-overview.md —— 工作区整体说明

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录

## 一、这个工作区是什么

`D:\01_RPA` 是**利比里亚（Liberia）电信网络运维（NOC/SOC）的自动化与数据看板工作区**，服务于 ZTE 侧的网络运维交付。它把三类东西收在一起：

1. **自研数据平台**（`my_app` / Data Insight MVP）—— 网络 KPI、告警、工单、库存等数据的采集、入库与展示；
2. **统一门户**（`liberia-noc_soc-数据看板统一门户`）—— 把 FineBI 报表与 my_app 页面聚合到一个入口，给不同角色看；
3. **交付任务与工具**（`Task\`、`LBR_Tools\`、`Unified_Tools\`、各类 RPA 脚本）—— 按需交付的报表、导出、通知等。

三者不是并列的独立项目，而是**一条数据链**：上游系统 → my_app 采集与入库 → 门户聚合呈现 → 人（值班/管理）决策。

## 二、三个主要系统

### 1. my_app —— Data Insight MVP（自研主系统）

- **位置**：`Task\my_app\`
- **定位**：网络运维数据的**唯一自研数据底座**。23+ 个功能页（同步、告警、工单、SLA、GIS、库存、电池、丢包、IP Trace 等），44+ 个定时任务。
- **技术栈**：后端 FastAPI + SQLAlchemy（SQLite / PostgreSQL 双模）+ Alembic；前端 React + Vite；任务经 worker 分组执行 + 看门狗守护。
- **部署**：前端 vite `7090`（`base=/myapp/`）、后端 uvicorn `7038`，由 `192.168.100.19:80` 的 nginx 反代。
- **文档**：`Task\my_app\docs\manual\`（13 份手册，**现状以此为准**）；`Task\my_app\PROJECT_DOCS.md` 是历史档案。

### 2. liberia-noc_soc-数据看板统一门户 —— 统一入口

- **位置**：`liberia-noc_soc-数据看板统一门户\`
- **定位**：**聚合入口**。内置 my_app 真实页面直链（`?page=` 查询参数格式）+ FineBI 报表分类条目，提供卡片网格 / 高密清单 / 业务分类矩阵三种视图。
- **技术栈**：React 19 + Vite 6 + Tailwind v4 + lucide-react；门户自身后端（Express/server 目录）提供鉴权、看板配置、QC 指标接口等。
- **关键能力**：环境一键切换（批量替换 IP/域名）、深浅双模、中英文国际化、收藏置顶、访问热度、JSON 导入导出、二维码扫码与 iframe 预览、实时任务调度部件（每 60s 拉 `/api/tasks`）。
- **部署**：挂在 nginx `/uniplam/` 子路径下，门户后端 API 前缀为 `/uniplam/api/*`（**不是** `/api/*`，见 `src/config.ts` 中的原因说明）。
- **文档**：`README.md`（功能概览，质量较高）；`MsPortal\` 下有若干专项记录（QC 面板优化、三列对齐、配色对齐、商用就绪度检测）。

### 3. FineBI 决策报表中心（Liberia Data Portal）

- **定位**：上游既有 BI 平台，承载历史与官方口径的报表。
- **入口**：`http://192.168.100.19/webroot/decision`
- **状态**：部分报表链接仍为**目录占位**（标签含"链接待更新"、状态 beta），需在门户内"编辑看板配置"逐条替换为实际 URL。已在 `README.md` 中明示。
- **方向**：正在把 FineBI 看板逐步迁移为 my_app 自研页面（见 `Task\my_app\docs\FINEBI_MIGRATION.md`、门户 `scripts\migrate_finebi_to_myapp.py`）。

## 三、数据流（一页看懂）

```
 网络设备 / 上游系统 (UME、eFlow、CCN、PM、邮件、WhatsApp ...)
        │  采集（定时任务，44+ 个，worker 分组执行）
        ▼
   my_app 后端 (7038)  ──►  SQLite / PostgreSQL  (eflow_tt、realtime_alarm、history_alarm、packet_loss ...)
        │                        │
        │  REST /api/*          │ 报表/图片取数
        ▼                        ▼
   my_app 前端 (7090,/myapp/)   FineBI (192.168.100.19:/webroot/decision)
        │                        │
        └────────┬───────────────┘
                 ▼
        统一门户 (9267, /uniplam/)  ← 人在这里看
```

细节与端口级拓扑见 `architecture.md`。

## 四、角色与关注点

| 角色 | 关心什么 | 主要看哪 |
| --- | --- | --- |
| NOC/SOC 值班 | 实时告警、掉站、工单、任务是否在跑 | 门户告警/QC 面板、my_app 实时页 |
| 网络优化工程师 | KPI 趋势、SLA、地理分布 | FineBI 报表、my_app KPI/GIS 页 |
| 管理层 | 达标率、超期、宏观概览 | 门户矩阵视图、CXO 看板 |
| 交付/开发 | 数据能否采到、任务有没有挂 | `13-operations.md`、worker 日志 |

## 五、目录速查

| 目录 | 内容 |
| --- | --- |
| `Task\` | 交付任务集合（`my_app` 在 `Task\my_app\`；另有 `eflow_Q&A`、`RAN`、`ORANGE`、`MTN_Comsal`、`Monthly_Report`、`Unified_Tools`、`data_base` 等） |
| `LBR_Tools\` | 报表/工具脚本（含远端 SQLite 服务，如 `KPI\db_ps_cs_cn.sqlite3` 经 HTTP 8765 提供） |
| `Unified_Tools\` | 统一工具集 |
| `openclaw_api_selector\` | API 选择器 |
| `ticket_export_rpa\` | 工单导出 RPA |
| `Site_outage\` | 掉站相关处理 |
| `WareHouseDashBoard\` | 仓库看板 |
| `whatsapp\` / `whatsapp_session\` | WhatsApp 通知与登录态 |
| `nginx-1.28.0\` / `chrome-win\` | 运行时依赖（含 `chrome-win.zip` 大包） |
| `report\` / `scheduler_logs\` / `debug\` / `TMP\` / `V_Tmp\` | 产出与日志，**不入库** |
| `_fe_dist\` | my_app 前端构建产物目录 |

## 六、术语表

| 术语 | 含义 |
| --- | --- |
| **my_app** / Data Insight MVP | 自研网络运维数据平台 |
| **门户 / uniplam** | Liberia NOC/SOC 数据看板统一门户（部署路径 `/uniplam/`） |
| **FineBI** | 上游决策报表平台 |
| **QC** | Quality Control，门户上的质量指标卡面板（告警、PMT、超期等） |
| **eflow / eflow_tt** | 工单流水数据源与工单表 |
| **TT** | Trouble Ticket，故障工单 |
| **PMT** | 待处理/超期工单指标 |
| **SLA** | 服务等级协议（MS SLA 为一等公民指标） |
| **UME** | 上游网管系统（大屏接口来源） |
| **PM** | Performance Management，性能数据（`cn_ems` 相关） |
| **掉站 / Site out** | 基站退服 |
| **worker** | my_app 的任务执行进程（多个分组 + 看门狗） |
| **`_fe_dist`** | my_app 前端构建产物目录（后端按此路径找静态文件） |

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 工作区地图与 AI 约束 | `AGENTS.md` |
| 架构与数据流细节 | `architecture.md` |
| 当前在办事项 | `TODO.md` |
| 使用者说明 | `user-guide.md` |
| 开发与回归 | `development.md` |
| 视觉规则 | `DESIGN.md` |
| my_app 现状（权威） | `Task\my_app\docs\manual\01-overview.md`、`11-feature-guide.md` |
| 门户功能概览（权威） | `liberia-noc_soc-数据看板统一门户\README.md` |

> **工具负责整理，人与 AI 负责协作执行。**
