# Data Agent 能力评估 —— my_app / Data Insight MVP

> 评估日期：2026-09-25　|　评估范围：在 my_app 引入「Data Agent」类能力（自然语言取数 + 告警归因）
> 结论摘要：**有条件可行**。定时报表与看板数字**不得** Agent 化；仅「只读临时取数」与「告警归因」两个窄场景值得做。
> 配套实现：`backend/services/sql_guard.py`、`backend/services/nl2sql_service.py`、`backend/services/alarm_attribution_service.py`

## 一、这份文档要回答什么

「Data Agent」有两种含义，本项目的取舍完全不同：

| 含义 | 说明 | 本项目结论 |
| --- | --- | --- |
| **A. 广义数据智能体** | LLM 自主规划、多步调工具、自动出结论 | **不做**。项目是单机确定性数据平台，自主决策带来不可预期的报表差异 |
| **B. 只读 NL2SQL / 归因副驾** | 自然语言 → 受限只读 SQL → 结果；或把既有指标翻译成结论 | **做**，但必须加硬护栏（见第五节） |

本文档只论证 B。

## 二、现状基线（实测，非推测）

### 2.1 数据层

- 运行模式为 **PostgreSQL（`MY_APP_DB_MODE=pg`）**，`/api/health` 返回 `db_mode=pg`。
- `_PsycopgRaw` 设 `autocommit = True`（`backend/database.py:324`）——
  **这意味着不存在「靠事务回滚兜住写操作」的保护**，只读必须靠语句层面的拦截，不能靠事务。
- `get_raw_connection()` 的 search_path 是
  `app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,ran_ume_ro,public`
  （`backend/database.py:320`）。

### 2.2 同名表跨 schema 分叉（本次评估最重要的发现）

实测 `information_schema` 结果：

| 表 | schema | 行数 | 列数 | 列名风格 |
| --- | --- | --- | --- | --- |
| `eflow_tt` | `app` | 36,226 | 161 | `title` / `wo_no` … snake_case |
| `eflow_tt` | `eflow` | 28,455 | 161 | `Title` / `WO No.` … Title Case |
| `history_alarm` | `app` | 12,338 | 173 | `site_name` / `alarmchangedtime` |
| `history_alarm` | `eflow` | — | 36 | `Site Name` / `Alarm Title` |
| `realtime_alarm` | `app` | 46 | 149 | snake_case |

**两个后果，都会静默出错：**

1. **行数不同**（36,226 vs 28,455）—— 查错 schema 不报错，只是数字不一样。
2. **列名大小写/空格不同** —— `WHERE "Title"` 在 `app.eflow_tt` 上直接报错；
   而 `title` 在 `eflow.eflow_tt` 上报错。**自动生成的 SQL 猜列名必然踩雷。**

这直接决定了设计：**NL2SQL 不能自由生成 SQL，必须先把表名+列名收敛成白名单再生成。**

### 2.3 已知的数据源陷阱（`AGENTS.md` 第六节，仍然成立）

- 裸 `sqlite3.connect` 绕过 `get_raw_connection`：`ipran_chart_service.py:233`、`fw_kpi_services.py:488`。
- `db_ps_cs_cn` 本地文件是 **0 字节占位**，真数据在远端 HTTP 8765 —— 查它会得到**空结果而不是报错**。
- `eflow_tt` 双库：同步任务只写 `app.db`。

> **对 Agent 的含义**：这三条是「看起来对、实际是空/旧数据」的典型来源。
> 人类工程师知道这些，**LLM 不知道**。所以表清单必须由服务端白名单给，不能让模型自己列。

### 2.4 现有 AI 能力

- `backend/services/incident_ai_service.py`（**恰好 500 行，已达项目单文件上限**）
  已实现 7 个 provider 的分发：openai / gemini / doubao / qianwen / glm-coding / deepseek / agnes，
  含模型回退、超时重试、SSE 流式（`stream_deepseek`）。
- **api_key 一律由前端请求体传入，服务端不落盘、不日志** —— 这是既有安全约定，必须沿用。
- `backend/services/incident_overview_service.py:566` 的 `analyze_with_ai()` 已有
  「provider 不可用时回退本地规则」的降级路径。

## 三、为什么定时报表/看板**不**应该 Agent 化

项目定位写明「报表不能漏」（`docs/manual/01-overview.md:7`）。LLM 的三个性质与之直接冲突：

| LLM 性质 | 与需求的冲突 |
| --- | --- |
| 非确定性（同输入可能不同输出） | 每天的 KPI 邮件数字会漂移，无法对账 |
| 幻觉 | 可能编出一个不存在的站点/指标 |
| 无法保证复杂度/耗时 | 定时任务有窗口，超时会顶掉后续排程 |

**这些路径保持确定性实现**（现有 SQL/Python 计算），Agent 只在「人主动提问」的交互场景使用。
这条边界是本评估的核心结论。

## 四、值得做的两个窄场景

### 4.1 只读 NL2SQL（TableBrowser 内验证）

**价值**：项目有 23 个功能页 + 40+ 定时任务，但用户的临时问题（"上周哪个区域丢包最严重"）
既没有页面也没有接口。现状只能「找人写个新页」。这是真实且高频的摩擦。

**为什么选 TableBrowser 作为落点**：
- TableBrowser **已经是只读浏览语义**（`docs/manual/01-overview.md:16`），风险面天然最小；
- `backend/routers/tables.py:_column_metadata()` **已有双模列元数据**
  （sqlite 走 `pragma_table_info`，PG 走 `information_schema`）—— 这正是 NL2SQL 最难的部分，已经现成；
- **不碰任何生产报表链路**，失败只影响一个探索性页面。

**关键设计**：先给模型「表名 + 列名 + 类型」的**白名单样本**，让它只在这个空间里生成，
而不是让它凭空写 SQL。这一条把 2.2 节的跨 schema 陷阱从「必然踩」变成「结构上不可能踩」。

### 4.2 告警归因（复用 `incident_ai_service.py`）

**价值**：`realtime_alarm`（46 行活跃告警）/ `history_alarm`（12,338 行）/ `eflow_tt`（36,226 行 TT）
已有数据，但现状只呈现「数字」。把「这个站点为什么反复告警」从「人去翻三张表」
变成「一段带下钻路径的结论」是真实提升。

**实现约束**：
- `incident_ai_service.py` **已达 500 行上限**（项目硬约束），
- 因此**不修改该文件**，新归因逻辑放独立文件，**import 复用**其 `PROVIDERS` / `dispatch` 分发能力。

## 五、硬护栏（缺一不可）

原型实现了以下护栏，全部为**服务端强制**，不依赖模型自觉：

| # | 护栏 | 位置 | 作用 |
| --- | --- | --- | --- |
| G1 | **只读语句白名单**：仅允许单条 `SELECT` / `WITH` | `sql_guard.py` | 从源头阻断 DML/DDL |
| G2 | **写关键字黑名单**（含 `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/COPY/…`） | `sql_guard.py` | 防白名单绕过 |
| G3 | **多语句阻断**：禁止 `;` 分隔的第二条语句 | `sql_guard.py` | 防 `SELECT 1; DROP …` |
| G4 | **注释/字符串剥离后再校验** | `sql_guard.py` | 防 `/* */` 与引号内藏关键字 |
| G5 | **表名白名单**：SQL 中出现的表必须来自真实 `list_tables()` | `sql_guard.py` | 防跨 schema 乱查 |
| G6 | **强制 LIMIT**：无 LIMIT 自动补，超上限自动压 | `sql_guard.py` | 防全表扫描拖垮生产库 |
| G7 | **`_` 前缀内部表不可见** | `nl2sql_service.py` | 与 TableBrowser 既有约定一致 |
| G8 | **PG 只读事务**：`SET TRANSACTION READ ONLY` | `nl2sql_service.py` | 纵深防御（注意：连接是 autocommit，此项为显式加设） |

> **G4 的必要性**：朴素的正则黑名单会被 `SELECT 'a; DROP TABLE x'` 或
> `SELECT 1 /* ; DELETE */` 绕过。必须先剥离注释与字符串字面量，再在「剩余代码」上判定。

## 六、风险与未做项（诚实清单）

| 风险 | 现状 | 缓解 |
| --- | --- | --- |
| **无多用户体系**（`01-overview.md:22`：无注册/角色/审计） | 未解决 | Agent 查到的数据 = 该页面本就能看到的数据，**不扩大权限面**。若要开放给 NOC 分析师，须先补权限体系 |
| **api_key 由前端传入** | 沿用既有约定 | 服务端不落盘、不日志；与 `incident_ai_service.py` 一致 |
| **LLM 可能生成语义错误但语法正确的 SQL** | 无法自动消除 | 结果附**实际执行的 SQL + 行数**，让用户能自行核对；不宣称「结论正确」 |
| **`db_ps_cs_cn` 等空占位数据源** | 不在白名单内 | G5 表白名单天然排除 |
| 跨 schema 同名表 | 已实测确认 | G5 + 2.2 节，列名由服务端提供而非模型猜测 |
| 大表扫描影响生产库 | 部分缓解 | G6 强制 LIMIT；仍未加超时熔断 —— **列为后续项** |
| 提示注入（表内数据含指令） | 未处理 | **列为后续项**：归因结果只呈现，不回写任何数据 |

**明确不做的事**：
- 不做自主多步规划（不做含义 A）；
- 不自动回写数据库、不发邮件、不改报表；
- 不新增裸 `sqlite3.connect`（`AGENTS.md` 第六节第 1 条）。

## 七、结论与建议顺序

| 方向 | 结论 |
| --- | --- |
| 定时报表 / 邮件 / 看板数字 | **不 Agent 化**，保持确定性 |
| TableBrowser 只读 NL2SQL | **做**（已实现原型），探索性场景，风险可控 |
| 告警归因 | **做**（已实现原型），复用既有 provider 分发 |
| 开放给多用户使用 | **先补权限体系**，否则是拿安全换便利 |

**建议顺序**：数据层裸连接治理（`TODO.md` P1）→ 本原型在 TableBrowser 试运行 →
再评估是否扩展到别的页面。理由：Agent 的答案质量完全取决于数据层可信度，
在裸连接与空占位数据源治理前扩大 Agent 面，只会把数据层的坑放大成「AI 说的」，更难排查。

## 八、交付物与验证状态

### 8.1 文件清单

| 文件 | 作用 |
| --- | --- |
| `backend/services/sql_guard.py` | **只读 SQL 护栏**（G1–G6），安全关键件 |
| `backend/services/nl2sql_service.py` | NL2SQL：schema 上下文 → 生成 → 校验 → 执行 |
| `backend/services/alarm_attribution_service.py` | 告警归因：客观统计 + AI 解读 + 本地降级 |
| `backend/routers/data_agent.py` | 路由 `/api/data-agent/*`（4 个端点，**无写接口**） |
| `frontend/src/components/DataAgentBar.tsx` | TableBrowser 内嵌「智能问答」页签 |
| `tests/test_sql_guard.py` | 护栏测试（33 例，含绕过尝试） |

`backend/main.py` 仅在 `include_router` 列表追加一行 + 注册一行；`TableBrowser.tsx` 仅追加一个页签。
**未修改 `incident_ai_service.py`**（已达 500 行上限，只 import 复用其 `PROVIDERS` / `dispatch`）。

### 8.2 已验证（2026-09-25 实测）

- ✅ `pytest tests/test_sql_guard.py` —— **33 例全通过**（含多语句、注释/字符串藏关键字、`pg_read_file`、schema 前缀、未知表、超大 LIMIT）。
- ✅ 只读链路直连真库跑通：`history_alarm` 按类型聚合返回真实数据。
- ✅ 备份表过滤生效：53 张可见表，`kml_mw_links_bak_*` 已被排除。
- ✅ 归因三源（`realtime_alarm` / `history_alarm` / `eflow_tt`）均取到数据。
- ✅ `npm run check:i18n` **通过**（「代码用到的所有文案键在 zh / en 两份字典中均存在」）。
- ✅ `npm run build` 成功；产物已确认含新代码：
  `data-agent` 串在 `_fe_dist/assets/TableBrowser-CEBzGtOc.js`，i18n 键在 `index-Bu15-OGP.js`。
- ✅ `main.py` 导入无副作用：OpenAPI 共 227 条路径，含 4 条 `data-agent`，既有路由未受影响。

### 8.3 待重启验证（**需你操作**）

后端 :7038 运行中且**未带 `--reload`**，故新路由要重启进程才生效。
当前鉴权已开启（`auth-switch.json` 的 `authEnabled=true`），重启会有数秒中断，故未自行执行。

重启后按此清单确认：

```
# ① 端点已注册（回环免鉴权，返回 JSON 而非 SPA 的 HTML）
Invoke-WebRequest http://127.0.0.1:7038/api/data-agent/schema -UseBasicParsing
#    -> 200 且 body 是 {"tables":[...],"table_count":53,...}
#    若返回 <!doctype html> 说明仍是旧的 SPA 兜底，即未重启成功

# ② 护栏在 HTTP 层同样生效（DROP 必须 400）
Invoke-WebRequest http://127.0.0.1:7038/api/data-agent/ask -Method POST `
  -ContentType 'application/json' -Body '{"sql":"DROP TABLE eflow_tt","provider":"local","api_key":"x"}' -UseBasicParsing
#    -> 400 {"error":"只允许 SELECT 或 WITH 开头的只读查询"}

# ③ 界面入口：TableBrowser 页 ->「智能问答」页签（硬刷新 Ctrl+F5）
```

**界面路径**：`TableBrowser` → 页签「智能问答」。填入自己的 API Key（仅存本机浏览器）后提问。

> 注：`tests/test_sql_guard.py` 是新文件，若项目 CI 未自动收集 `tests/`，需手动跑一次。
> `scripts/python.exe` 与 `.venv` 都**缺依赖**，实测可用的解释器是
> `C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe`（即后端进程所用）。

## 九、出处索引

| 论断 | 出处 |
| --- | --- |
| 报表不能漏的定位 | `docs/manual/01-overview.md:7` |
| TableBrowser 只读语义 | `docs/manual/01-overview.md:16` |
| 无多用户体系 | `docs/manual/01-overview.md:22` |
| autocommit 的 PG 连接 | `backend/database.py:320,324` |
| 双模列元数据 | `backend/routers/tables.py:116` |
| provider 分发 | `backend/services/incident_ai_service.py:477-500` |
| AI 失败回退本地规则 | `backend/services/incident_overview_service.py:576-597` |
| 裸连接点位 | `AGENTS.md` 第六节；`ipran_chart_service.py:233`、`fw_kpi_services.py:488` |
| `db_ps_cs_cn` 空占位 | `AGENTS.md` 第六节第 4 条 |
| 表/行数实测 | 2026-09-25 直连 PG `information_schema` 查询（见 2.2） |
| 鉴权总开关现状 | `D:\01_RPA\auth-switch.json`（`authEnabled=true`） |
| 回环免鉴权规则 | `backend/main.py:288`（`portal_auth.client_is_local`） |
| 非公开路径默认要求会话 | `backend/main.py:262-291`（`_PUBLIC_API` 不含 `data-agent`） |
