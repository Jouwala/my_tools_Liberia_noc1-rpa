# 01 AGENTS.md —— AI 进入本项目首先需要知道的信息

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> 本目录（`D:\01_RPA`）是**整个 RPA 工作区的总纲**。各子系统的细节一律看各自的 `AGENTS.md` 与手册，**不要**把子系统细节抄到这里。

## 一、先读什么（阅读顺序）

| 顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `AGENTS.md`（本文） | 工作区地图与硬性约束 |
| 2 | `project-overview.md` | 整个工作区是干什么的 |
| 3 | `architecture.md` | 三个主要系统如何连在一起 |
| 4 | `TODO.md` | 当前在办的事 |
| 5 | 进入具体子系统后 | 读该子系统的 `AGENTS.md`，再读其 `docs/manual/` |

## 二、工作区地图

**这是一个单体 git 仓库，不是多个仓库。** 已在 `Task\my_app` 下执行 `git rev-parse --show-toplevel` 验证，顶层返回 `D:/01_RPA`。这意味着：

- 一次提交会同时影响工作区里所有子系统；
- 不存在「门户的提交」「my_app 的提交」这种隔离，提交信息里要用 `feat(portal):` / `fix(assets):` 这类**前缀标明影响面**（沿用既有习惯）；
- 改动前先 `git status` 看全域未提交变更，避免把别人的在途改动一起卷进你的提交。

### 主要子系统

| 目录 | 是什么 | 技术栈 | 该处文档入口 |
| --- | --- | --- | --- |
| `Task\my_app\` | **Data Insight MVP**（网络运维数据平台，自研主系统） | FastAPI + SQLite/PG + React | `Task\my_app\AGENTS.md`、`Task\my_app\docs\manual\` |
| `liberia-noc_soc-数据看板统一门户\` | **Liberia NOC/SOC 数据看板统一门户**（聚合 FineBI 与 my_app 看板） | React 19 + Vite + Tailwind v4 | `...\AGENTS.md`、`...\README.md` |
| `Task\` | 各类交付任务（eflow_Q&A、RAN、ORANGE、MTN_Comsal、Monthly_Report 等） | 混合 | 各任务目录内的 `README.md` |
| `LBR_Tools\`、`Unified_Tools\`、`openclaw_api_selector\`、`ticket_export_rpa\` | 工具与 RPA 脚本集 | Python / 混合 | 各自目录 |
| `nginx-1.28.0\`、`chrome-win\`、`whatsapp*\`、`scheduler_logs\`、`report\` | 运行时依赖与产出 | — | 一般不直接改 |

### 环境拓扑（速查）

```
192.168.100.19:80  (nginx)
 ├── /myapp/            → 127.0.0.1:7090   my_app 前端 (vite, base=/myapp/)
 ├── /api/              → 7090 → 127.0.0.1:7038   my_app FastAPI 后端
 ├── /webroot/decision  → FineBI 决策报表平台
 └── /uniplam/          → 9267  统一门户自身（含 /uniplam/api/* 门户后端）
```

> 主机名与端口以 `liberia-noc_soc-数据看板统一门户\src\config.ts` 为准（那里是**单一真相源**，换机房只改这一处）。细节见 `architecture.md`。

## 三、给 AI 的硬性约束

1. **中文优先。** 本工作区的注释、文档、提交信息全部是中文。新写的文档、代码注释、提交信息也用中文。用户的业务数据（看板名称、分类、部门）保持原值不翻译。
2. **绝不写敏感值。** 文档里可以出现**配置项名称**、**环境变量键名**、**分组 key**，**不得**出现口令、Token、授权码、账号、密码哈希。这是 `Task\my_app\docs\manual\README.md` 已确立的维护约定，全域适用。内网 IP（`192.168.100.19` / `.20`）在既有代码与文档中已是公开事实，沿用其写法即可。
3. **改前先读，别猜。** 每个子系统都有约定（例如 my_app 的任务必须登记在 `backend/task_registry.py` 的 `TASK_SPECS`；门户的文案必须同时加进 `src/i18n.tsx` 的 `zh` 与 `en` 两份字典）。跳过这些约定会做出「看起来对、实际坏」的改动。
4. **先看 `.gitignore` 再 `git add`。** 工作区里有大量运行时产物被显式忽略，禁止入库：
   - 根 `.gitignore`：`*.zip` / `*.exe` / `*.dll` / `*.db` / `*.sqlite3` / `*.xlsx` / `*.csv` / `*.png|jpg|svg` 等二进制与文档；
   - `Task\my_app\.gitignore`：`/db/`（SQLite 956M）、`/log/`（152M）、`/TMP/`、`/Lib/`、`/Scripts/`、`auth_cache/`、`*.pid`、`*.bak_*`、`_myapp_trash_*/`、`/backend/data/native_board_cache/`；
   - 门户 `.gitignore`：`node_modules/`、`dist/`、`*.log`、`.env*`、`portal-default.json`（运行时写入）、`auth-data/`（含加盐密码哈希，**严禁入库**）。
   - 提交前用 `git status --porcelain` 复查有没有被忽略规则漏掉的运行时文件混进来。
5. **不要新增第二个真相源。** 现状文档以各子系统的 `docs/manual/` 与 `README.md` 为准；`Task\my_app\PROJECT_DOCS.md`（151KB）是**历史档案**（迁移计划、架构评估、i18n 审计、失败复盘），其自身 README 已声明「现状以 `docs/manual/` 为准」。**不要**把现状写回 `PROJECT_DOCS.md`。
6. **破坏性操作先确认。** 删除目录、批量移动、改数据库、动 nginx 配置、重启生产服务（7038/7090/9267）前，先说明影响面并取得确认。工作区里有多个 `start.bat` / `stop.bat` / `*_ensure.bat`，误跑会打断在看板上看数据的人。
7. **临时产物放 `TMP\` 或 `tmp_*`/`_*` 命名**，并且**不要入库**。根目录已有历史教训：98 个一次性探针脚本曾误随提交入库（见 `7b1d33b chore: 清理根目录 98 个一次性探针脚本`）。写探针请放 `TMP\`。

## 四、子系统深潜

| 你要做什么 | 去哪读 |
| --- | --- |
| 改门户界面 / 看板配置 / 鉴权 | `liberia-noc_soc-数据看板统一门户\AGENTS.md` → `DESIGN.md` → `development.md` |
| 改 my_app 后端 / 任务 / 数据层 | `Task\my_app\AGENTS.md` → `Task\my_app\docs\manual\02-architecture.md`、`04-task-system.md` |
| 加一个 my_app 功能页 | `Task\my_app\docs\manual\README.md` 的「手册维护约定」第 1 条（三处必须同步） |
| 排查线上问题 | 门户 → `Task\my_app\docs\manual\13-operations.md` |
| 新任务交付 | `Task\` 下对应目录 |
| 整体视觉规则 | `DESIGN.md` |

## 五、本工作区的 8 份体系文档

| # | 文件 | 内容 |
| --- | --- | --- |
| 01 | `AGENTS.md` | 本文。AI 首先需要知道的信息 |
| 02 | `DESIGN.md` | 视觉规则 |
| 03 | `TODO.md` | 当前任务、优先级与进度 |
| 04 | `project-overview.md` | 工作区整体说明 |
| 05 | `architecture.md` | 架构与数据流 |
| 06 | `user-guide.md` | 面向使用者的功能说明 |
| 07 | `development.md` | 开发方式、命令与回归清单 |
| 08 | `component-api.md` | 组件索引 |

> **工具负责整理，人与 AI 负责协作执行。**
