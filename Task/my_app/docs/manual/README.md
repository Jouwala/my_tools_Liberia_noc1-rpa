# my_app 手册

> 网络运维数据平台的**设计手册 + 使用手册**。
> 基准日期：2026-08-27　|　适用版本：master 分支当前代码

## 这份手册和 PROJECT_DOCS.md 有什么区别

| 文件 | 装什么 | 什么时候看 |
| --- | --- | --- |
| `docs/manual/`（本目录） | 项目**现在是什么样**、**怎么用**、**怎么运维** | 上手、日常使用、排障 |
| `PROJECT_DOCS.md`（仓库根） | 历史**计划、评估、复盘、审计报告**（迁移计划、架构论证、i18n 审计、失败复盘） | 想知道"当初为什么这么做/踩过什么坑" |

手册只写已被代码验证的现状；PROJECT_DOCS.md 里的说明性内容（README、局域网访问、MS SLA 服务说明）已迁入本手册，原文保留在 PROJECT_DOCS.md 作为历史档案。

## 三条阅读路径

**第一次接触项目** → `01-overview.md` → `10-quickstart.md` → `11-feature-guide.md`
**要改代码/加功能** → `16-new-page-guide.md`（加页面必读）→ `02-architecture.md` → `03-data-layer.md` → `04-task-system.md` → `05-security-and-credentials.md`
**系统出问题/要看日志** → `13-operations.md`（先查排障 FAQ）→ `12-configuration.md` → `90-appendix.md`（接口与任务速查）

## 目录

### 设计篇

| 文件 | 内容 |
| --- | --- |
| [01-overview.md](01-overview.md) | 项目定位、能力边界、术语表 |
| [02-architecture.md](02-architecture.md) | 进程拓扑、请求链路、目录结构、前后端分层约定 |
| [03-data-layer.md](03-data-layer.md) | SQLite/PostgreSQL 双模、方言适配、Alembic、数据落盘目录 |
| [04-task-system.md](04-task-system.md) | 任务注册、队列、worker 分组、看门狗、自动重试 |
| [05-security-and-credentials.md](05-security-and-credentials.md) | 访问控制现状、凭据存储、TLS、**已知风险清单** |

### 使用篇

| 文件 | 内容 |
| --- | --- |
| [10-quickstart.md](10-quickstart.md) | 环境要求、依赖安装、启动停止、首次配置 |
| [11-feature-guide.md](11-feature-guide.md) | 23 个功能页逐个说明（导航顺序一致） |
| [12-configuration.md](12-configuration.md) | 设置页可配项、配置文件、环境变量分组速查 |
| [13-operations.md](13-operations.md) | 日常巡检、日志、排障 FAQ、清理与备份 |
| [14-integrations.md](14-integrations.md) | 上游系统清单与数据流方向 |
| [15-user-help.md](15-user-help.md) | **面向使用者的一站式帮助**（与站内「使用帮助」页同源生成）：平台简介、44 个任务的工作流与维护、25 个页面指南、运维排障与 FAQ；英文版 [15-user-help-en.md](15-user-help-en.md) |
| [16-new-page-guide.md](16-new-page-guide.md) | **新增功能页规范**：五步流程、统一组件约定、页面标准骨架。配套可编译模板 `frontend\src\pages\_TemplatePage.tsx` |
| [90-appendix.md](90-appendix.md) | API 前缀速查、任务 ID 速查、待清理残留清单 |

## 手册维护约定

1. **新增功能页**：**先看 `16-new-page-guide.md` 并复制 `frontend\src\pages\_TemplatePage.tsx`**，再在 `11-feature-guide.md` 按导航顺序插入一节，同时在 `App.tsx` 的菜单数组与 `i18n.tsx` 中英两处登记（这三处漏一处，手册就和界面对不上）。
2. **新增定时任务**：在 `backend\task_registry.py` 的 `TASK_SPECS` 登记后，同步更新 `04-task-system.md` 的分组表。
3. **不写敏感值**：手册里可以出现配置项**名称**、环境变量**键名**、分组 key，**不得**出现口令、Token、授权码、内网 IP/主机名、账号。参见 `05-security-and-credentials.md` 末尾的禁写清单。
4. **每条论断带出处**：写"某某行为"时标注 `文件路径:行号`，便于代码演进后定位失效内容。
5. **15-user-help（-en）是生成文件**：内容源在 `frontend/src/pages/helpContent.ts` 与 `helpTaskDocs.ts`，站内帮助页、导出按钮、MD 文档三处同源；改内容改 TS 后跑 `cd frontend && node scripts/generate-help-doc.mjs` 重新生成，**不要手改 MD**。
6. **UI 统一组件不许绕开**：卡片走 `components/cards`、导出走 `utils/excelReport`、图表取色分 DOM/canvas 两层。细则见 `16-new-page-guide.md` 第三节，校验清单见 `AGENTS.md` 第八节。
