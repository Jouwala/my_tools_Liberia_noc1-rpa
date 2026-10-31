# 01 AGENTS.md —— AI 进入本项目首先需要知道的信息

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\AGENTS.md`（工作区级约束，**先读那个**）

## 一、这个项目是什么

**my_app / Data Insight MVP** —— 利比里亚电信网络运维的**自研数据平台**，是整个工作区的数据底座。它负责把上游系统（UME、eFlow、CCN、PM、邮件、WhatsApp 等）的数据采集、入库、计算、展示，并提供 23+ 个功能页面与 40+ 个定时任务。

**技术栈**：后端 FastAPI + SQLAlchemy（SQLite / PostgreSQL 双模）+ Alembic + APScheduler；前端 React + Vite；任务由多组 worker 进程执行 + 看门狗守护。

**权威文档**：`docs\manual\`（13 份手册，**现状以它为准**）。

## 二、新会话上手顺序

```
1. 本文（约束与地图）
2. docs\manual\README.md     —— 手册导航与"三条阅读路径"
3. docs\manual\01-overview.md    —— 项目定位、能力边界、术语表
4. docs\manual\02-architecture.md —— 进程拓扑、请求链路、分层约定
5. 按任务类型选读：
   - 加功能页     → docs\manual\16-new-page-guide.md + 复制 frontend\src\pages\_TemplatePage.tsx
   - 改功能页     → docs\manual\11-feature-guide.md
   - 改数据层     → docs\manual\03-data-layer.md
   - 改任务/调度  → docs\manual\04-task-system.md（+ backend\WORKER.md）
   - 配置/环境    → docs\manual\12-configuration.md
   - 排障/日志    → docs\manual\13-operations.md
   - 接口/任务速查 → docs\manual\90-appendix.md
```

## 三、硬性约束（违反会直接出问题）

1. **新增功能页必须三处同步**：`frontend\src\App.tsx` 的菜单数组 + `frontend\src\i18n.tsx` 中英**两处** + `docs\manual\11-feature-guide.md`。**漏一处，手册就和界面对不上**（`docs\manual\README.md` 维护约定第 1 条）。
   - 已存在的功能页若**从未登记**，同样要补：`noc_analyst` / `fme_ranking` / `site_avail` / `repeat_site_down` 四个页面此前都缺 `11-feature-guide.md` 条目与站内帮助（2026-09-23 已补）。
   - 站内帮助另有三处要同步：`helpContent.ts` 的 **`PAGE_DOCS`（zh/en 两份）+ `PAGE_LIST` + `NAV_KEY_MAP`**，并加进 `CATEGORIES` 的某个分类。**只加 `PAGE_DOCS` 不会显示** —— 页面清单由 `PAGE_LIST` 驱动。
1b. **看板页"能下钻尽下钻"是硬要求**：页面上**每个数字都要可点**并落到对应明细，不允许只有汇总数字没有下钻路径。`noc_analyst` 是参考实现（四层：人 → 切片明细 → 站点 → 单 TT 告警链路，见 `docs\manual\11-feature-guide.md` 的 14b 节）。做下钻时三条铁律：
   - **下钻端点的 WHERE 必须与概览端点完全一致**（同一时间字段、同一精确匹配），否则"表格里的数字"与"下钻的行数"对不上，用户会当成 bug。**不要用 `LIKE` 做下钻、用 `=` 做概览**这类不一致写法。
   - **取样 `limit` 必须显著大于单页最大数据量**，且截断时要显式暴露（`meta.truncated` + 界面告警条）。默认值过小会**静默截断**，让下钻行数少于表格数字。
   - **动态拼 i18n key 会被 `check:i18n` 拦下**：`t('noc.slice.' + s)` 会被守卫读成键名 `noc.slice.` 而报"字典缺失"。改成显式 `switch` 返回字面量键（参考 `NocAnalyst.tsx` 的 `sliceLabelKey()` / `linkageLabelKey()`）。
2. **新增功能页请从模板复制**：`frontend\src\pages\_TemplatePage.tsx` —— 它是**可编译的骨架**，照抄即自动获得项目统一风格（统一卡片、统一导出、统一令牌、统一弹窗）。不要凭记忆重写一套。
3. **UI 一律走项目统一组件，禁止自造**：

   | 要做什么 | 必须用 | 禁止 |
   | --- | --- | --- |
   | 卡片（含带图标卡） | `import { CardBase, StatCard } from '../components/cards'` | `import { Card } from 'antd'`、页面里写 `style={cardStyle}` |
   | 导出 Excel | `import { exportAoaReport, exportReport } from '../utils/excelReport'` | 裸 `xlsx`（`XLSX.utils.*` / `XLSX.writeFile`） |
   | 下钻弹窗 | `components/DraggableClickModal` | 各页自写弹窗骨架 |
   | 主题取色 | DOM 用 `WH`（`var(--wh-*)`）；ECharts 用 `useTheme()` + `DARK/LIGHT` **实值** | 在 ECharts 里写 `WH.xxx`（canvas 解析不了 CSS 变量）；写死十六进制 |
   | 文案 | `t('key')`，`i18n.tsx` **中英两处**都要加 | 界面里写中文字面量；`t(key, { defaultValue })` —— `t()` 第二参数是**插值参数**，不是 options 对象，键不存在时它会原样返回 key，界面直接显示 `xxx.yyy` |
   | 时间格式 | `frontend\src\datetime.ts` | 各页各写一套 |

   > **卡片、Excel、弹窗的详细契约**见 `component-api.md` 第二节与 `docs\EXCEL_EXPORT_STANDARD.md`。
   > **国际化漏键有自动守卫**：`cd frontend && npm run check:i18n`（已内置进 `npm run build`，不通过会**中断构建**）。机制与踩坑案例见 `docs\manual\16-new-page-guide.md` 3.6。
4. **新增定时任务必须登记** `backend\task_registry.py` 的 `TASK_SPECS`，否则**根本不会被执行**；同时更新 `docs\manual\04-task-system.md` 的分组表。
5. **前端构建产物目录必须是 `_fe_dist`**，否则后端找不到静态文件会白屏（`docs\manual\10-quickstart.md`）。改完前端源码须重新 `npm run build`；产物非 HMR，需刷新页面。
   **验证改动是否真的上线，要看产物而不是看时间戳**：`vite preview` 直接读 `_fe_dist`，但浏览器会缓存 `index.html`。三步确认：
   ```
   cd frontend && npm run build
   # ① 看 index.html 引用的入口 hash 是不是新的
   Get-Content D:\01_RPA\Task\_fe_dist\index.html | Select-String 'index-.*\.js'
   # ② 服务端返回的是不是同一份（直连 7090，绕过浏览器缓存）
   (Invoke-WebRequest http://127.0.0.1:7090/myapp/ -UseBasicParsing).Content
   # ③ 改动的代码是否真在那个 chunk 里（按特征串搜）
   Select-String -Path D:\01_RPA\Task\_fe_dist\assets\*.js -Pattern '你的新增端点或文案key'
   ```
   ① 与 ② 一致、③ 命中 = 已上线，此时"界面没变"就是**浏览器缓存**，硬刷新（Ctrl+F5）即可。
   > 排查"改了没生效"时**不要**只凭 `_fe_dist` 里存在旧文件名就断定构建失败 —— 见第四节 `emptyOutDir: false` 的说明。
6. **帮助文档是生成文件，不要手改。** `docs\manual\15-user-help.md` 与 `15-user-help-en.md` 的源在 `frontend\src\pages\helpContent.ts` 与 `helpTaskDocs.ts`；改完跑 `cd frontend && node scripts\generate-help-doc.mjs` 重新生成。改了 TS 不重新生成 = 站内帮助与 MD 不一致。
7. **不写敏感值。** 手册里可写**配置项名称**、**环境变量键名**、**分组 key**；**不得**写口令、Token、授权码、内网主机名、账号。参见 `docs\manual\05-security-and-credentials.md` 末尾的禁写清单。
8. **每条论断带出处。** 写"某某行为"时标注 `文件路径:行号`，便于代码演进后定位失效内容（`docs\manual\README.md` 维护约定第 4 条）。
9. **不要把现状写回 `PROJECT_DOCS.md`。** 那是**历史档案**（迁移计划、架构评估、i18n 审计、失败复盘），其 README 已声明"现状以 `docs\manual\` 为准"。
10. **中文注释。**
11. **不入库。** 见下节。

## 四、不入库清单（`.gitignore` 已覆盖，禁止绕开）

| 忽略项 | 原因 |
| --- | --- |
| `/db/` | SQLite 约 956M（`db\app.db` 是真库） |
| `/log/` | 运行日志约 152M |
| `/TMP/` | 运行时产出与探针（截图/抓包/Chrome 临时 profile） |
| `/Lib/`、`/Scripts/`、`/include/`、`pyvenv.cfg`、`/.venv/` | 虚拟环境（Lib 352M / Scripts 6.4M） |
| `auth_cache/`、`**/auth_cache/`、`*.local.json` | 鉴权缓存与本地凭据（**含敏感信息**） |
| `*.pid` | 进程锁文件 |
| `*.bak_*` | 带时间戳的备份 |
| `/_myapp_trash_*/` | 代码清洁归档 |
| `/backend/app.db` | **误建的空 sqlite 占位**（真库是 `/db/app.db`） |
| `/backend/data/native_board_cache/` | 原生看板磁盘缓存（运行时可重建，单页可达数 MB） |
| `/backend/services/cn_ems/_pmcache/` | PM 性能数据下载缓存（19 万量级） |
| `**/battary_kpi_fetch/auth_info.json` | 电池 UME 鉴权快照（**含有效会话 cookie**，由 `ensure_auth_info()` 自动生成/刷新） |
| `/data/portal_profiles/_tmp_*/` | Chrome 临时 profile |
| `*-wal` / `*-shm` | SQLite 边车文件 |
| `/_tmp_*` | 根目录一次性探针脚本 |

> **注意 `backend\app.db` 是误建的空占位**，真库在 `db\app.db`。读错库会得到"空的但不报错"的结果。
>
> **前端构建产物不在 `my_app` 内**：`vite.config.ts` 的 `outDir` 是 `D:/01_RPA/Task/_fe_dist`（在**仓库根**下、`my_app` 的**上一级**），且 `emptyOutDir: false`。
> 两个后果，都会让人误判：
> 1. 产物目录**只增不减** —— 改版后旧页面 chunk（如旧版 `NocAnalyst-*.js` 8KB）会和新 chunk（34KB）**同时存在**。看到旧文件名不代表构建失败，`index.html` 里引用的那个才是真正生效的。
> 2. `my_app\_fe_dist` **不存在**，别在那里找产物；`cd frontend && npm run build` 的输出路径前缀是 `../../_fe_dist/`。

## 五、关键文件地图

| 文件 | 作用 |
| --- | --- |
| `backend\main.py`（25KB） | FastAPI 入口、路由挂载、生命周期 |
| `backend\task_registry.py`（68KB） | **任务唯一登记处** `TASK_SPECS`（懒加载注册） |
| `backend\task_registry.md` | 任务注册表说明（字段、对外接口） |
| `backend\worker.py`（28KB） | 独立任务执行 worker |
| `backend\worker_watchdog.py`（32KB） | worker 看门狗（崩溃自动重拉） |
| `backend\backend_watchdog.py` | 后端看门狗 |
| `backend\WORKER.md` | worker 架构、容错设计、启停 |
| `backend\database.py`（17KB） | 数据访问层（`get_raw_connection` 等） |
| `backend\dialect_helpers.py` | SQLite/PG 方言适配 |
| `backend\services\` | 业务服务层（各数据源采集与计算） |
| `backend\routers\` | API 路由 |
| `backend\models\`、`schemas\` | ORM 模型与 Pydantic schema |
| `backend\.env`（不入库） | 运行配置，参照 `.env.example` |
| `frontend\src\App.tsx`（98KB） | 前端主入口与路由/菜单 |
| `frontend\src\i18n.tsx`（204KB） | 中英双字典 |
| `frontend\src\api.ts` | 前端 API 封装 |
| `frontend\src\theme.ts`、`index.css` | 主题与样式 |
| `frontend\src\pages\` | 各功能页（60+ 个 `.tsx`） |
| **`frontend\src\pages\_TemplatePage.tsx`** | **新功能页模板（可编译骨架）—— 加页先看它** |
| `frontend\src\components\cards\` | **统一卡片组件入口**（`CardBase` / `StatCard` / `CardTitle`） |
| `frontend\src\utils\excelReport.ts` | **统一 Excel 导出**（UNIFIED_EXCEL_V1） |
| `frontend\scripts\generate-help-doc.mjs` | 帮助文档生成器 |
| `alembic\`、`alembic.ini` | 数据库迁移 |
| `tests\` | 测试 |

## 六、改数据层前必读（高破坏风险）

以下事实来自 `PROJECT_DOCS.md` §2 的全量稽核，**任何"统一改数据访问层"的改动都会静默坏图**：

1. **存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`**，已知如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488` —— 它们是**图表数据源**。
2. `get_raw_connection` 调用点实测约 **76 处**，不要假设能一次性替换。
3. `eflow_tt` 有**双库**（`app.db` 与 `eflow.sqlite3`）：同步任务**只写 `app.db`**；`eflow.sqlite3` 的副本是旧流水线遗留快照。
4. `db_ps_cs_cn` 的**真数据在远端**（经 HTTP `8765` 读），项目内同名文件是 **0 字节占位** —— 误当数据源会得到空结果而非报错。
5. 告警表 `realtime_alarm` / `history_alarm` 被**同时写** `app.db` 与 `eflow.sqlite3`，但**页面只读 `app.db`**。

> **⚠ 现状已是 PostgreSQL 为主（2026-09-23 实测更正）。**
> 上文第 3~5 条来自 `PROJECT_DOCS.md` §2 的迁移前稽核，其中"SQLite 为主、PG 迁移未执行"**已过时**：
> `backend\.env` 实际为 `MY_APP_DB_MODE=pg`，`/api/health` 返回 `db_mode=pg / database=postgresql`。
> 但上面前 5 条**仍然成立且更要小心** —— 熔断开关（`backend\database.py:23-37`，回退方案 R7）还在，
> `MY_APP_DB_MODE=sqlite` 一个环境变量就能切回去，所以任何改动**必须两种方言都能跑**：
> - `get_raw_connection()` 在 pg 模式下返回 psycopg2 连接，并把 `?` 占位符自动转成 `%s`（`:216-260`）；
>   别名裸 `sqlite3.connect` 的代码在 pg 模式下**必然失败** —— 这正是不要新增裸连接的原因。
> - 鉴权库（`auth_cache`）被硬排除在 PG 之外（R8，`:39`），无论 `DB_MODE` 为何值都走 SQLite。
> - 想确认当前跑在哪个库，**不要猜**，问 `/api/health` 或看 `MY_APP_DB_MODE`。
>
> **⚠ 第 6 条（2026-10-31 新增，与上面同级硬性）：VMAX 数仓 GBase 8a（库 `zxvmax`）是生产环境 —— 只允许 SELECT/SHOW/DESC 查询，禁止在其上做任何修改或创建（建表/临时表/视图/回写/改权限一概不行）。需要数仓侧改动时：停止编码并告知用户，由用户找领导申请；获批后数仓操作由用户方执行，代码只做只读接线。新增 SELECT 不必申请，但须先评估负载、低峰试跑单日、与既有同步任务错开窗口。完整规则（含覆盖链路与降级要求）见工作区总纲 `D:\01_RPA\AGENTS.md` 第四节第 8 条 —— 那里是真相源，本条只是指针。** 代码侧兜底：`backend\services\vmax_gbase\vmax_gbase_client.py` 的只读断言（仅放行 SELECT/SHOW/DESC），**断言是防误操作，不是授权**，不得绕过或放宽；`soc_trend_sync` / `olib_soc_*` 任务全部走该客户端。

## 七、进程与运维

生产不是"一个后端进程"：

```
uvicorn 后端 (:7038)
   ├── worker 分组进程（u / n / v / m / c …，各有 .pid）
   ├── worker_watchdog.py   —— worker 崩溃自动重拉
   └── backend_watchdog.py  —— 后端守护
```

- 启动：`start.bat` / `start_ensure.bat` / `start_hidden.ps1`（由看门狗托管 worker）
- 停止：`stop.bat`
- 巡检：`docs\manual\13-operations.md`（**五个关键进程是否都在**）
- 任务队列：SQLite `task_queue` 表（`pending/running/done/failed`），**不引入 Redis/RabbitMQ**；worker 串行执行，投递前查重防重复。

## 八、改代码前的检查清单

- [ ] 读了 `docs\manual\README.md` 的维护约定
- [ ] **新功能页：从 `frontend\src\pages\_TemplatePage.tsx` 复制骨架**（不要凭记忆重写）
- [ ] 新功能页：`App.tsx` + `i18n.tsx`（中英）+ `11-feature-guide.md` 三处同步
- [ ] **`npm run check:i18n` 通过**（漏键、`t(key,{defaultValue})` 错签名、残留 `tpl.*` 都会被拦下）
- [ ] **卡片用 `components/cards`，没有 `import { Card } from 'antd'`**
- [ ] **导出用 `utils/excelReport`，没有裸 `XLSX.utils.*` / `XLSX.writeFile`**
- [ ] **ECharts 里没有写 `WH.xxx`**（canvas 解析不了 CSS 变量，必须用 `DARK/LIGHT` 实值）
- [ ] 没有写死的十六进制颜色（DOM 层应走 `WH` 令牌）
- [ ] 新任务：`TASK_SPECS` 已登记，且 `04-task-system.md` 已更新
- [ ] 前端产物目录仍是 `_fe_dist`，且已重新 `npm run build`
- [ ] 帮助内容改动后已重跑 `generate-help-doc.mjs`
- [ ] 没有新增裸 `sqlite3.connect`
- [ ] 没有把 `db\`、`log\`、`TMP\`、`auth_cache\`、`*.pid` 加进版本库
- [ ] 没有写敏感值
- [ ] 改大文件前建了 `_bak_<日期>_<说明>` 快照（本项目既有习惯）

## 九、本项目的 8 份体系文档

| # | 文件 | 内容 |
| --- | --- | --- |
| 01 | `AGENTS.md` | 本文 |
| 02 | `DESIGN.md` | 视觉规则 |
| 03 | `TODO.md` | 当前任务与优先级 |
| 04 | `project-overview.md` | 项目整体说明（指向手册） |
| 05 | `architecture.md` | 架构与数据流（指向手册） |
| 06 | `user-guide.md` | 面向使用者的说明（指向手册） |
| 07 | `development.md` | 开发方式、命令与回归清单 |
| 08 | `component-api.md` | 组件索引 |

> 均在 `Task\my_app\` 根目录（与 `PROJECT_DOCS.md` 同级）。
> **手册（`docs\manual\`）仍是详细内容的权威来源**，这 8 份负责"入口与约束"。

## 十、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 工作区总纲 | `D:\01_RPA\AGENTS.md` |
| 手册导航 | `docs\manual\README.md` |
| 代码清理指南 | `docs\CODE_CLEANUP_GUIDE.md` |
| Excel 导出规范 | `docs\EXCEL_EXPORT_STANDARD.md` |
| FineBI 迁移 | `docs\FINEBI_MIGRATION.md` |
| 历史档案 | `PROJECT_DOCS.md`、`PROJECT_DOCS_ARCHIVE.md` |
| 统一门户 | `D:\01_RPA\liberia-noc_soc-数据看板统一门户\docs\AGENTS.md` |

> **工具负责整理，人与 AI 负责协作执行。**
