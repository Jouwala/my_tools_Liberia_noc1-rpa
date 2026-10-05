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
| G6 | **强制 LIMIT**：无 LIMIT 自动补，超上限自动压到 `MAX_LIMIT` | `sql_guard.py` | 防全表扫描拖垮生产库 |
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

### 8.3 重启验证（2026-10-05 已完成）

后端 :7038 运行中且**未带 `--reload`**，故新路由需重启进程才生效。
**2026-10-05 已通过看门狗完成重启并逐条验证**（详见第十节），以下清单当时全部通过：

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

## 十、2026-10-05 修正：base_url 死参数与三处一致性问题

用户反馈「Ask AI 不能用，也没有配置 base URL」。排查结论：**链路是好的**，
`GET /api/data-agent/schema` 实测 200（53 张可见表），`POST /ask` 带有效 key 能真正打到
provider —— 界面不显示 base URL 框是**设计如此**（端点由服务端按 provider 内置，
见 `nl2sql_service.py:215-222`），不是缺陷。顺手查出并修掉四处真问题：

| # | 问题 | 原状 | 修正 |
| --- | --- | --- | --- |
| 1 | **归因链路 `base_url` 被静默丢弃** | `AttributeIn.base_url` 声明了、`attribute()` 也收下了，但转手调 `ai_svc.dispatch()` 时**没放进 payload**（`dispatch` 只认 api_key/prompt/model），想接自建模型的人得不到任何反馈 | 显式给 `base_url` 时改走本服务自己的 `_call_openai_compatible()`；留空则保持原 dispatch 路径不变 |
| 2 | **`gemini` 是无法打通的选项** | 前端下拉有 7 项，NL2SQL 的 `defaults` 只有 6 项（无 gemini），选中必报「需提供 base_url」——**诱导用户去填一个必然失败的地址** | NL2SQL 侧显式说明 generateContent 协议不同构；前端下拉就地标注「不支持问数」 |
| 3 | **G6 存在静默灰区** | `LIMIT 500`（介于 `DEFAULT_LIMIT=200` 与 `MAX_LIMIT=1000`）既不被收敛，执行端也不置 `truncated`（`nl2sql_service.py:298` 比较对象是 `DEFAULT_LIMIT`），用户无法判断是否拿到全量 | `enforce_limit()` 改为**一律压到 `MAX_LIMIT`**，不再抛错；请求值与护栏上限始终自洽 |
| 4 | **缺 key 时无操作指引** | 只回「缺少 API key」，新用户不知道 key 从哪来、也不知道 base URL 不必填 | 界面常驻提示条 + 空 key 时前置拦截，文案说明「Key 仅存本机浏览器、端点无需配置」 |

### 设计取舍（记录理由，便于日后回看）

- **为什么 `base_url` 选「接通」而不是「删除」**：本项目原则 10 是「删除优于兼容」，
  但该字段已在 `AskIn` / `AttributeIn` 两个 schema 中公开声明，删除会让既有调用方
  从「静默失效」变成「请求失败」；且自建/代理模型是真实需求（数据不出内网）。
  故按「让声明的能力真正生效」处理。
- **`incident_ai_service.py` 一行未改**：该文件恰好 500 行（项目单文件上限），
  其 `PROVIDERS` 分发表的结构无法表达自定义端点，因此自建端点逻辑放在
  `alarm_attribution_service.py` 内自行实现，返回形状与 `dispatch()` 保持
  `(payload, status)` 一致，调用方无需分支。
- **协议边界如实暴露**：Gemini 走 `generateContent`，与 OpenAI 兼容的
  `/chat/completions` 不同构，**即便给了 base_url 也不适用**。此处选择显式报错，
  而不是发一个必然 404 的请求让用户去猜。

### 验证状态（2026-10-05 实测，后端已重启）

- ✅ `pytest tests/test_sql_guard.py` —— 34 例全通过（含 3 例新增/改写的 LIMIT 收敛用例）。
- ✅ 归因带 `base_url` → 报错中出现**用户指定的地址** `127.0.0.1:9`，证明参数真正生效。
- ✅ 归因 `gemini` + `base_url` → 明确回「gemini 使用 generateContent 协议，不支持自定义 base_url」（降级本地规则，非 500）。
- ✅ 归因 `provider=local` → 正常降级，无 `note`，与改动前一致。
- ✅ NL2SQL `gemini` → 明确的中文原因；带自定义 `base_url` → 错误中出现该地址。
- ✅ NL2SQL 空 key → 「缺少 API key」（前端已前置拦截，此路径为兜底）。
- ✅ `LIMIT 999999` → 收敛为 `LIMIT 1000` 并返回数据（此前为 400 拒绝）。
- ✅ `npm run check:i18n` 通过；`npm run build` 成功。
- ✅ 产物已上线：`index.html` 与服务端返回均为 `index-DEbRlaYj.js`，
  新代码在 `_fe_dist/assets/TableBrowser-gj8oIvFC.js` 与 `index-DEbRlaYj.js` 中。

> **UI 路径**：`TableBrowser` → 页签「智能问答 → Ask AI」。
> 填写自己的 API Key 即可提问；端点默认由服务端内置，无需配置，需要接自建模型时再点「高级设置」。

## 十一、2026-10-05 二次修正：`_extract_sql` 误命中散文中的 `with`

用户用 `agnes-2.5-flash` 提问「查找告警已经清除后派单的TT」，界面报：

```
Query failed
错误:  语法错误 在 "AND" 或附近的
LINE 5: AND created_time > alarm_clear_time
SELECT site_name, COUNT(*) AS alarm_count FROM eflow_tt GROUP BY ... LIMIT 10
```

**这条报错的形状本身就是线索**：SQL 看着是完整的 `SELECT … LIMIT 10`，
可报错却说第 5 行有个悬空的 `AND` —— 说明**真正拿去执行的字符串不是显示的这一条**。

### 根因（已确定性复现）

`_extract_sql()` 原来用 `re.search(r"\b(select|with)\b", t)` 在**全文**找语句起点。
`with` 是普通英文词，模型又常先写一句解释：

```
I will build this by joining tickets with their alarm records.   ← 这个 with 被命中
```sql
SELECT site_name, COUNT(*) AS alarm_count FROM eflow_tt ... LIMIT 10
```
AND created_time > alarm_clear_time                              ← 悬空尾句
```

正则从散文里的 `with` 处截断，于是**代码围栏被绕过、散文被当成 SQL 开头**，
残留尾句就成了悬空的 `AND`。致命之处在于：截取结果以 `with` 开头，
能**通过** `sql_guard.py:216` 的 `SELECT|WITH` 白名单，一路跑到数据库才炸 ——
用户看到的是 PostgreSQL 原始错误，完全无从下手。

### 修正

`_extract_sql()` 改为按可靠性取来源（`nl2sql_service.py`，新增 `_anchor_statement` 辅助）：

1. **代码围栏优先**（```sql / ```）—— 模型明确标注的 SQL，最可信；
2. **行首锚定** —— 找真正以 `SELECT` 开头的**行**；`WITH` 要求后接
   `RECURSIVE` 或「标识符 + `AS`(」的 CTE 形态，排除散文里的 `with`；
3. 都没有 → 原样返回，交给 `sql_guard` 明确拒绝（宁可拒绝，不可猜错后误执行）。

> 顺带说明：这条路径此前**没有测试覆盖**，所以坏了很久没人发现。
> 新增 `tests/test_nl2sql_extract.py`（12 例）用**确定性**用例锁住，
> 不需要联网、不依赖模型行为。

### 关于「同一次提问、SQL 却不一样」

实测同一问题连跑 4 次，`agnes-2.5-flash` 的**输出形态会变**（有/无围栏、有/无前置说明），
甚至偶发返回 `CANNOT_ANSWER`。这是 LLM 的固有非确定性，与本次缺陷叠加后表现为
「时好时坏」。修复后无论哪种形态都能正确提取。

### 验证状态

- ✅ `pytest tests/test_nl2sql_extract.py` —— 12 例全通过（含线上故障的最小复现）。
- ✅ 用故障原文回放：提取结果不再含悬空 `AND`，护栏放行后**执行成功返回 10 行**。
- ✅ 全量相关测试 49 例通过（`test_sql_guard` 34 + `test_nl2sql_extract` 12 + `test_ms_sla_warning_details` 3）。

## 十二、2026-10-05 三次修正：NUR 未匹配站点清单在 `page=ms_sla` 上丢失

用户问「337 条告警的站点在 cm_site_summary 中找不到…这个能点击显示全部站点名字吗」。

**能力其实已经实现**（`NurCalcChainNote.tsx:112-206` 的 `UnmatchedSitesAlert`，
含可搜索、可按影响行数排序的弹层），但**只在 `page=nur` 上能用，`page=ms_sla` 上点不开**。

### 根因

`backend/routers/ms_sla_dashboard.py:_load_overview()` 只把上游 `nur_calc` 的
`warnings` 拷进响应，**漏拷了配对的 `warning_details`**：

- 上游 `_load_live_nur_sla()` 实际**已经**透传了 `warning_details`（该文件 `:196`）；
- 但 `_load_overview()` 在 `:248` 只写 `out["warnings"] = live.get("warnings")`，
  明细被丢在 `live` 里没往上传；
- 前端 `NurCalcChainNote.tsx:128-131` 找不到 `kind == "unmatched_sites"` 的明细，
  就**退化成不可点击的纯文案**（该组件刻意不做「点了没反应」的死入口）。

所以现象是「**文案完全正常、入口凭空消失**」—— 比直接报错更难发现。
两个端点行为不一致也是这个原因：`/api/nur/overview` 直接返回
`nur_calc.compute_overview()`（`nur_dashboard.py:56`），字段是齐的。

### 修正

`_load_overview()` 补上 `out["warning_details"] = live.get("warning_details") or []`，
与 `warnings` 成对透传；空值兜底为空列表，前端可安全 `.find()`。

> 这类「两个字段必须成对透传」的漏拷，静态读代码很难发现，故用
> `tests/test_ms_sla_warning_details.py`（3 例）锁住，其中一例专门断言
> **空值时也必须是 `[]` 而不是 `None`/缺字段**。

### 验证状态（后端已重启，PID 78560）

| 端点 | 修复前 | 修复后 |
| --- | --- | --- |
| `/api/ms-sla-dashboard/overview`（page=ms_sla） | `warning_details` **为空** | **26 个站点 / 480 行** |
| `/api/nur/overview`（page=nur） | 26 个站点（本就正常） | 26 个站点（未受影响） |

实测拿到全部 26 个站点及各自影响行数，其中 `VMAX-DC` **336 行**、`HQ_Site` 24 行、
`Cow field 2` 37 行、`Gbarplay` 20 行 —— 点开即可知道该先修哪个站点。

> 注：文案里的数字会随数据更新变化（用户看到 337 条 / 19 个站点，
> 本次验证时为 480 条 / 26 个站点），这是**正常的时间漂移**，不是缺陷。

## 十三、2026-10-05 新增：手动 SQL 模式 + 结果导出

用户诉求：「除了 AI 查询，把手动查询的窗口也显示出来，手动输入查询命令查询，
并且查询结果要可以导出。」

### 关键发现：后端早就支持，缺的只是入口

`POST /api/data-agent/ask` 的 `sql` 字段**非空时跳过 AI 生成、直接执行**
（`nl2sql_service.py:362-365` 的 `if sql:` 分支）。所以手动 SQL 能力一直存在，
只是**界面把它藏在「AI 问完一次之后」**：

- 旧交互要先配 API key → 跑一次 AI 问数 → 结果区出现 SQL 框 → 改 SQL → 点「按当前 SQL 重跑」；
- 想直接写 SQL 的人被迫先配一个**根本用不到的 key**。

新增 `Segmented` 模式切换（AI 问数 / 手动 SQL），手动模式下：

- **不需要 API key**、不选 provider、不填模型 —— 这组控件整块隐藏，
  因为留着会让人以为「不填 key 也能跑 AI」，也会让手动模式看起来仍依赖 AI；
- SQL 直接写在主输入框（等宽字体、Ctrl/Cmd+Enter 执行；回车保持换行，因为 SQL 天然多行）；
- 提供「示例」按钮一键填入用户给的例句
  `SELECT * FROM eflow_tt WHERE alarm_clear_time < created_time`。

### 导出

用项目统一入口 `utils/excelReport.exportAoaReport`（**没有**裸 `XLSX.*`，
符合 `Task/my_app/AGENTS.md` 第三节第 3 条）。三个刻意的设计决定：

1. **只导出已返回的行，不重新查询全量。** 结果被服务端 LIMIT 截断时拿到的就是这一批，
   导出一个「看起来是全量」的文件是更坏的行为。
2. **截断时显式告知。** 新增 `dataAgent.truncatedExport` 文案，在原有的截断告警条里
   补一句「导出的是当前返回的这批数据，不是全量」。
3. `null`/`undefined` 导出为**空单元格**（而非界面上的 `—`）——
   表格里的 `—` 是给人看的占位，Excel 里应是真空值，便于排序与筛选。

### 护栏在手动模式下**不打折**

手动模式复用同一个 `run()` 请求函数与同一个服务端端点 —— 若另写一套请求，
迟早出现「AI 模式拦住了 DROP、手动模式没拦住」。实测：

| 手动输入 | 结果 |
| --- | --- |
| `SELECT * FROM eflow_tt WHERE alarm_clear_time < created_time` | ✅ 200 行（161 列） |
| `DROP TABLE eflow_tt` | ❌ 只允许 SELECT 或 WITH 开头的只读查询 |
| `SELECT 1; DROP TABLE eflow_tt` | ❌ 只允许执行单条语句（检测到分号分隔的多条语句） |

### 验证状态

- ✅ `tests/test_manual_sql_mode.py` —— 11 例全通过。其中两例专门把
  **「手动模式不需要 API key」**这条契约钉死：`ask()` 的 key 校验在 `generate_sql()`
  内部，只要有人把校验提到 `ask()` 开头「统一收口」，手动模式就会立刻开始要求一个
  用不到的 key。另一例用「把 `generate_sql` 换成会抛异常的实现」证明手动模式
  **完全不产生 AI 请求**。
- ✅ 相关测试共 60 例通过。
- ✅ `npm run check:i18n` 通过、`npm run build` 成功，产物 `index-DoFY7Iwx.js` 已上线，
  新文案键与导出逻辑均可在 bundle 中查到。
