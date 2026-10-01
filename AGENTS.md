# 01 AGENTS.md —— AI 进入本项目首先需要知道的信息

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> 本目录（`D:\01_RPA`）是**整个 RPA 工作区的总纲**。各子系统的细节一律看各自的 `AGENTS.md` 与手册，**不要**把子系统细节抄到这里。

## 一、先读什么（阅读顺序）

| 顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `AGENTS.md`（本文） | 工作区地图、工程原则与硬性约束 |
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
| `chrome-win\`、`whatsapp*\`、`scheduler_logs\`、`report\` | 运行时依赖与产出 | — | 一般不直接改。nginx 也在运行时依赖之列：本机 (.20) 生效目录是 `D:\01_RPA\nginx-1.28.0\`（2026-10-01 从 Y: 网络映射盘搬回本地，已加入 `.gitignore`）；`Y:\01_RPA\nginx-1.28.0\` 是 **.19 那台**在用的，不要动（见第四节第 6b 条） |

### 环境拓扑（速查）

```
192.168.100.19:80  (nginx)
 ├── /myapp/            → 127.0.0.1:7090   my_app 前端 (vite, base=/myapp/)
 ├── /api/              → 7090 → 127.0.0.1:7038   my_app FastAPI 后端
 ├── /webroot/decision  → FineBI 决策报表平台
 └── /uniplam/          → 9267  统一门户自身（含 /uniplam/api/* 门户后端）
```

> 主机名与端口以 `liberia-noc_soc-数据看板统一门户\src\config.ts` 为准（那里是**单一真相源**，换机房只改这一处）。细节见 `architecture.md`。

## 三、核心工程原则

> 十条通用纪律，适用于本工作区所有子系统。与第四节的「硬性约束」相抵时，**以第四节为准** —— 那些是本仓库已实测验证的具体事实，本节是方向。

1. **架构与领域优先。** 计划阶段先明确业务目标、领域边界、模块职责、依赖方向与数据流，形成符合领域规律、面向长期维护且可持续演进的设计后再编码；不得以短期实现便利牺牲整体设计。设计必须完整，实现应当克制：不做推测性抽象，抽象延迟到**第二个真实用例**出现时才引入，单一场景直接实现。
2. **追求优雅的代码模块。** 模块高内聚、低耦合，用精简且稳定的接口封装内部复杂度，让职责、命名、依赖和扩展方式清晰自然；代码按单一职责拆分。**新增/新建文件单个不超过 500 行**，接近上限时优先重构模块边界。存量超限文件（`backend\task_registry.py` 68KB、`frontend\src\i18n.tsx` 204KB、`frontend\src\App.tsx` 98KB）列入待重构清单，**不要求一次性拆分**，但改到它们时不得继续无度膨胀。
3. **保持边界与数据流清晰。** 协议模型（Pydantic `schemas\`）、领域模型、持久化模型（SQLAlchemy `models\`）与视图模型不得相互泄漏；数据必须在边界处完成校验和独立转换，避免跨层共享可变状态。
4. **安全与隔离默认开启。** 所有功能按多租户、多用户场景设计，明确认证、授权与数据隔离边界（my_app 的角色与凭据体系见 `Task\my_app\docs\manual\05-security-and-credentials.md`）；遵循最小权限，任何外部输入均视为不可信，敏感信息不得进入代码、日志或响应（落地写法见第四节第 2 条）。
5. **面向并发与故障设计。** 后端主动考虑幂等性、竞态、事务边界、超时、取消、重试、背压和资源释放；不得通过无边界重试、吞错或隐式共享状态掩盖问题。本工作区的 RPA 采集与 worker 任务尤其要显式处理「上游返回半截数据」与重复投递（投递前查重见 `Task\my_app\docs\manual\04-task-system.md`）。
6. **保障完整前端体验。** 控制渲染成本、异步状态与并发请求，保持清晰的 UI 结构；用户流程必须覆盖加载、空状态、错误、重试、反馈与可访问性。取不到数据显示 `—`，不得显示成 `0`。
7. **复用稳定的业务语义。** 优先复用已有模块与能力（my_app 的 `components/cards`、`utils/excelReport`、`components/DraggableClickModal` 等统一组件是**强制入口**，细则见 `Task\my_app\AGENTS.md` 第三节第 3 条），但不要仅因外形相似就过早抽象；确需重复实现时，必须在注释中说明其独立演进或暂不抽象的原因。**新增依赖前先核查本处已有依赖** —— 本仓库没有统一的根 `package.json`，`Task\my_app\frontend\package.json` 与门户 `package.json` 各自独立，Python 依赖看各任务目录的 `requirements.txt`（如 `Task\my_app\requirements.txt`）。先查这些文件、库的文档与类型定义，不臆断已有库缺功能；确需引入时选成熟且维护良好的库，不重复实现通用功能。
8. **为未来维护者保留上下文。** 代码、注释、测试与架构文档是跨越时间的协作媒介。非显然的设计决策、兼容约束、已知缺陷和临时方案，必须记录原因、影响范围、潜在风险与移除条件；技术债务要关联可追踪的归属（`TODO.md` 条目），**禁止**留下没有上下文的裸 `TODO`。本仓库当前**没有独立 ADR 目录**，重大架构决策请在 `architecture.md` 追加带日期的决策小节，形成事实上的 ADR，并按 `Task\my_app\AGENTS.md` 第三节第 8 条标注 `文件路径:行号` 出处。
9. **确保变更可验证、可观测、可回滚。** 每项改动都应行为可测试、运行状态可观测、故障可定位，并兼顾向后兼容和回滚路径；错误与日志必须保留诊断上下文，但不得泄露敏感信息。回滚手段在本仓库是实打实的：表结构走 `alembic downgrade`，进程有 `worker_watchdog.py` / `backend_watchdog.py` 守护，改大文件前先建 `_bak_<日期>_<说明>` 快照。
10. **删除优于兼容。** 内部路径重构时直接删除过时实现，**禁止**新增兼容层、deprecated shim 或双写逻辑；对外契约（`/api/*`、`/uniplam/api/*` 等稳定接口与数据库迁移）的兼容性按协议契约单独评估 —— 那是合同义务，不是迁就旧代码。

> **变更速查（本仓库真实命令）**。完整回归清单以 `development.md` 第四节的表为准，不要在这里另起一套。
>
> - 通用：提交前 `git status --porcelain` 复查，没有运行时产物混入。
> - **收尾自检（第四节第 7 条的机器可验证版本）**：`git status --porcelain` 里 `??` 行必须为空或全部是你本次要提交的真文件；出现 `_*.txt` / `*.bak_*` / `TMP/` 之类的行说明探针落了错误的地方。怀疑某个文件为何没被跟踪时问 `git check-ignore -v <路径>`，它会把命中的规则与所在文件行号打出来。
> - my_app 前端：`cd Task\my_app\frontend` → `npm run check:i18n`（漏键守卫）→ `npm run build`（内含 `tsc`；产物必须落在 `Task\_fe_dist`，否则后端白屏）。
> - 门户前端：`cd liberia-noc_soc-数据看板统一门户` → `npm run lint`（`tsc --noEmit`）→ `npm run build`。
> - 改表结构：`cd Task\my_app` → `alembic revision --autogenerate -m "<模块>-<变更>"` → `alembic upgrade head`（回退 `alembic downgrade base`；动态 eFlow 表不进 migration，见 `Task\my_app\docs\manual\03-data-layer.md`）。
> - 存量数据搬迁/修复/回填：回填脚本随迁移版本一起提交，`upgrade head` 之后执行并核对行数。
> - PowerShell 不支持 `&&`，多条命令用 `;` 分隔（`.qoder\rules\shell_safe.md`）。

## 四、给 AI 的硬性约束

1. **中文优先。** 本工作区的注释、文档、提交信息全部是中文。新写的文档、代码注释、提交信息也用中文。用户的业务数据（看板名称、分类、部门）保持原值不翻译。
2. **绝不写敏感值。** 文档里可以出现**配置项名称**、**环境变量键名**、**分组 key**，**不得**出现口令、Token、授权码、账号、密码哈希。这是 `Task\my_app\docs\manual\README.md` 已确立的维护约定，全域适用。内网 IP（`192.168.100.19` / `.20`）在既有代码与文档中已是公开事实，沿用其写法即可。
3. **改前先读，别猜。** 每个子系统都有约定（例如 my_app 的任务必须登记在 `backend/task_registry.py` 的 `TASK_SPECS`；门户的文案必须同时加进 `src/i18n.tsx` 的 `zh` 与 `en` 两份字典）。跳过这些约定会做出「看起来对、实际坏」的改动。
4. **先看 `.gitignore` 再 `git add`。** 工作区里有大量运行时产物被显式忽略，禁止入库：
   - 根 `.gitignore`：`*.zip` / `*.exe` / `*.dll` / `*.db` / `*.sqlite3` / `*.xlsx` / `*.csv` / `*.png|jpg|svg` 等二进制与文档；**`Task\_fe_dist\`、`Task\_fe_dist_tmp\`、`Task\_fe_dist_bak_*\`、`Task\_fe_cloud\` 整目录（vite 构建产物及其手工副本，2026-09-24 起脱离跟踪）** —— 但只有 `Task\_fe_dist\` 是**线上服务目录**（`nginx.conf:150/160` 用 alias 从磁盘直接读它，不经任何构建步骤），所以**忽略跟踪 ≠ 可以删除**，它必须留在磁盘上；其余三份是历史副本，2026-09-25 已移入 `_quarantine_20260925\`。另有 `/_quarantine_*/`（隔离区）、`/_myapp_trash_*/`、`*.rpltmp`、`*.tsbuildinfo`、`*.log.err`。
   - `Task\my_app\.gitignore`：`/db/`（SQLite 约 1.5G）、`/log/`、`/TMP/`、`/Lib/`、`/Scripts/`、`auth_cache/`、`*.pid`、`*.bak_*`、`_myapp_trash_*/`、`/backend/data/native_board_cache/`、**根目录 `/_*`（一次性探针）**。注意 `/_*` **刻意没有**写成 `**/_*` —— `backend/services/_playwright_utils.py`（被 `site_outage_service.py:22` import）、`_gen_native_catalog.py`、`frontend/src/pages/_TemplatePage.tsx` 都是带下划线的**真源码**，必须保持在版本库里。
   - 门户 `.gitignore`：`node_modules/`、`dist/`、`*.log`、`.env*`、`portal-default.json`（运行时写入）、`auth-data/`（含加盐密码哈希，**严禁入库**）、**`_*` / `.tmp_*` / `tmp_*` / `seg*.txt` / `listing.txt` / `out.txt`（一次性转储）、`*.bak` / `*.bak_*` / `*_bak_*`（手工快照）、`log/`、`tsconfig.tsbuildinfo`**。`MsPortal\`、`OlrPortal\`、`olbrportal\` 是**手写静态壳**（`nginx.conf:102/108` 直接 alias 发它们），是源码，上面这些规则刻意没有整目录忽略它们。
   - **门户的 `.gitignore` 与 `vite.config.ts` 的 `server.watch.ignored`（约 :242-267）是同一套判断的两个副本。** 那份 watch 清单早就把「什么不是源码、什么会触发无意义整页刷新」逐条写了理由，只是从没同步给 git，于是同一个文件在 dev 里被当垃圾、在版本库里却被当源码跟踪。**改一个必须改另一个**，否则两边立刻重新分叉。
   - 提交前用 `git status --porcelain` 复查有没有被忽略规则漏掉的运行时文件混进来。
5. **不要新增第二个真相源。** 现状文档以各子系统的 `docs/manual/` 与 `README.md` 为准；`Task\my_app\PROJECT_DOCS.md`（151KB）是**历史档案**（迁移计划、架构评估、i18n 审计、失败复盘），其自身 README 已声明「现状以 `docs/manual/` 为准」。**不要**把现状写回 `PROJECT_DOCS.md`。
6. **破坏性操作先确认。** 删除目录、批量移动、改数据库、动 nginx 配置、重启生产服务（7038/7090/9267）前，先说明影响面并取得确认。工作区里有多个 `start.bat` / `stop.bat` / `*_ensure.bat`，误跑会打断在看板上看数据的人。
6b. **本机（MSNOC1 / .20）nginx 的生效目录是 `D:\01_RPA\nginx-1.28.0\`（本地盘）。2026-10-01 起如此。** 这条经历过两次事故，务必按现状操作：
   - **生效位置**：`D:\01_RPA\nginx-1.28.0\`，nginx 进程的 `ExecutablePath` 就来自这里。**改本机配置只改 `D:\01_RPA\nginx-1.28.0\conf\nginx.conf`。**
   - **为什么搬离 Y 盘（2026-10-01）**：此前本机 nginx 跑在 `Y:\01_RPA\nginx-1.28.0\`（网络映射 `\\192.168.100.19\e`，即 .19 的 E 盘），nginx.exe、conf、logs、temp **全在网络盘上**。2026-09-30 21:56~22:15 nginx 猝死，`error.log` **无 crash 痕迹**（仅 warning 级 buffered-to-temp），系统日志也无崩溃/关机事件，判定为 **SMB 网络盘 I/O 阻塞**。遂复制一份到本地 D 盘运行。
   - **`.19` 仍使用 Y: 上那份**：搬移方式是**复制而非移动**，`Y:\01_RPA\nginx-1.28.0\` **保持原样、不要删也不要改**（那是 .19 的线上目录）。所以现在有**两份配置**，改配置前先想清楚改的是哪台机器的：
     - 本机 .20 生效：`D:\01_RPA\nginx-1.28.0\conf\nginx.conf` ← **改这个**
     - .19 生效：`\\192.168.100.19\e\01_RPA\nginx-1.28.0\conf\nginx.conf`
   - **执行 `-s reload` / `-s quit` 必须先进到该 nginx 自己的目录**。nginx 从**自己所在目录**的 `logs\nginx.pid` 读 master pid；在错误目录执行会读到已死 pid，信号发给不存在的进程——**命令不报错到操作者眼前，只在日志里留一行 `OpenEvent(...) failed`**。2026-09-28 实测：reload 打到 `91864`，真正的 master 完全未收到信号，nginx 随后停止服务直至人工重启。
   - **正确写法**（先验证语法再重载）：
     ```
     cd D:\01_RPA\nginx-1.28.0
     .\nginx.exe -t              # 改配置后先验证
     .\nginx.exe -s reload       # 平滑重载
     ```
     ⚠ 桌面 `olbr_app\nginx-Stop.lnk` 的 `WorkingDirectory` **仍指向 Y 盘**（2026-10-01 未同步更新），它现在停的是 .19 那台，**对本机无效**。停本机请用上面 `cd D:` 的写法。
   - **存活监控**：计划任务 `Nginx_EnsureRunning`（每 5 分钟）调 `Task\my_app\monitor_fixes\nginx_monitor.ps1` 巡检本机 80 端口，挂了自动拉起；日志在 `Task\nginx_monitor.log`。脚本的 `NginxExe`/`NginxDir` 已同步改为 `D:\01_RPA\nginx-1.28.0`（Version 4）。**日志轮转 `门户\rotate_nginx_logs.ps1` 的 `-Prefix` 默认值必须与之一致**，否则会去轮转 Y: 上的旧目录。
   - **已隔离的历史副本**：早期 `D:\01_RPA\nginx-1.28.0\` 曾是另一份**配置分叉**的发行包（缺 `/v2/olbrportal/`），已于 2026-09-29 移入 `_quarantine_20260929_nginx_dup\`。**注意：它与现在这份新的 D 盘目录同名但无关** —— 那份是历史遗留，这份是 2026-10-01 从 Y: 复制来的现役副本。
   - **`D:\01_RPA\nginx-1.28.0\` 已加入根 `.gitignore`**（第三方发行包，非源码）。**忽略跟踪 ≠ 可以删除**：它是本机线上服务目录，`nginx.exe` 与 `conf\` 必须留在磁盘上。


7. **一次性探针与转储只能落 `TMP\`，并且任务结束前自清。** 这条约定已经失效过三次，每次都有记录：`7b1d33b`（根目录 98 个探针脚本随提交入库）、`_myapp_trash_20260918\`、以及 2026-09-24 的审计（门户 506 个被跟踪文件里 347 个是探针/转储/手工快照/日志，`Task\_fe_dist` 有 5240 个构建产物入库）。所以拆成可执行的四条：

   - **先问：这个文件非落盘不可吗？** 绝大多数「想看看结果」不需要文件 —— 让命令直接输出 stdout，或用 Read/Grep 读原文件。**「写个 `_dump.txt` 再回头读它」是这两个仓库噪声的第一来源**：它把一次性的中间思考固化成了仓库里的长期资产。
   - **必须落盘时只有一个去处**：所在子系统的 `TMP\`（`Task\my_app\TMP\`、门户 `TMP\`、工作区根 `TMP\`），文件名带 `_` 前缀。这三处都已被忽略规则覆盖，带 `_` 前缀是为了让人一眼认出它不是产物。
   - **收尾自清**：任务结束前删掉本次创建的一次性探针（`.qoder\rules\shell_safe.md` 第 2 条已要求，此前没有落实）。**可复用的诊断/审计脚本不删**，但必须留在 `TMP\` 里并在对应手册写一行用途 —— 否则下一个 agent 会重写一遍，仓库里就出现三份功能相同的 `_check_*.py`。
   - **手工快照继续允许**（第三节原则 9 的 `_bak_<日期>_<说明>` 是本项目既有习惯），但**2026-09-24 起快照一律不进版本库**：`.gitignore` 已覆盖 `*.bak`/`*.bak_*`/`*_bak_*`。也就是说快照是**本机磁盘上**的回滚手段，git 历史只保留正式改动。同一个源文件的快照只留最近 3 份，更早的自己清。

## 五、子系统深潜

| 你要做什么 | 去哪读 |
| --- | --- |
| 改门户界面 / 看板配置 / 鉴权 | `liberia-noc_soc-数据看板统一门户\AGENTS.md` → `DESIGN.md` → `development.md` |
| 改 my_app 后端 / 任务 / 数据层 | `Task\my_app\AGENTS.md` → `Task\my_app\docs\manual\02-architecture.md`、`04-task-system.md` |
| 加一个 my_app 功能页 | `Task\my_app\docs\manual\README.md` 的「手册维护约定」第 1 条（三处必须同步） |
| 排查线上问题 | 门户 → `Task\my_app\docs\manual\13-operations.md` |
| 新任务交付 | `Task\` 下对应目录 |
| 整体视觉规则 | `DESIGN.md` |

## 六、本工作区的 8 份体系文档

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
