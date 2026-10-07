# WhatsApp 知识库助手：准确率商用优化 —— AGENT 执行手册

> **受众**：后续进入本目录的 AI Agent / 开发者。读完应能**直接改代码、写测试、跑命令、验收**，不必再做一轮架构调研。  
> **基准日期**：2026-10-07  
> **项目根**：`D:\01_RPA\Task\whatsapp-kb-bot`  
> **工作区总纲**：先读 `D:\01_RPA\AGENTS.md`（中文注释、不写敏感值、PowerShell 不用 `&&`、破坏性操作先确认）。  
> **现状权威说明**：本目录 `README.md`（架构、踩坑、命令）。本文只补充「为什么不准、怎么改到可值班」，**不要**把本文内容再抄回根 `TODO.md`。  
> **不要提交密钥 / `data/auth/` / `data/*.sqlite*` / `.env`。** 不要把口令写进文档或日志。

---

## 0. 执行 Agent 开场必做（5 分钟）

1. 读本文第 0–4 节 + 第 12 节「禁止事项」。未读完禁止改检索阈值或放开 `systemPrompt`。
2. 确认工作目录是 `D:\01_RPA\Task\whatsapp-kb-bot`，不是仓库根。
3. 跑一次只读体检（PowerShell，分号分隔）：

```powershell
cd D:\01_RPA\Task\whatsapp-kb-bot
node -e "const i=require('fs').readFileSync('data/index.json','utf8'); const d=JSON.parse(i); console.log(d.meta)"
Get-ChildItem knowledge | Select-Object Name,Length,LastWriteTime
```

4. **重启问答进程前必须向用户确认。** 本机问答由计划任务 / `autostart.ps1` 拉起，误重启会打断群里正在用的人（工作区硬性约束 6）。`npm run ingest` **只写** `data/index.json`，**不会**让已运行进程换索引——ingest 后若不重启，群里仍用旧内存快照。
5. 用户未要求 git commit 时不要提交。一次提交会影响整个 `D:\01_RPA` 仓库，信息前缀用 `feat(wa-bot):` / `fix(wa-bot):`。
6. 一次性探针只许落 `D:\01_RPA\Task\whatsapp-kb-bot\TMP\`（或 `Task\my_app\TMP\`），任务结束前删除。禁止在项目根写 `_dump.txt`。

### 0.1 本手册的目标（可验收）

把「知识库通道答不准」提升到**值班可当依据**的水准。工单通道（单票 / 统计）已经按「数字由脚本渲染、模型不碰数」设计，**不要推倒**。

完成 P0 后应满足：

| 验收项 | 标准 |
| --- | --- |
| 索引含 `08_级别缺失与排查.md` | `index.meta.sources` 含该文件 |
| 默认检索不被 `07_` 手册占满 topK | 领域题 topK 中 `07_` 占比可配置且默认可排除 |
| 告警码含义 / 压缩结果 / 级别规则问法 | 走查表工具，**不经 LLM 自由生成** |
| 每条知识回答 | 带出处（文件名 + 规则 ID 或告警码） |
| 黄金集 | 至少 30 条离线题，`npm run eval:kb`（新建）可跑 |
| 既有单测 | `npm run test:js` 全绿 |

完成 P1 后应满足第 8 节指标。P2 是产品/合规，代码可做准备，**不要擅自换 WhatsApp 官方 API 或停 Baileys**。

### 0.2 明确不在本次范围

- 不把 Baileys 换成官方 Cloud API（官方进不了已有大群，见 README 开头）。
- 不引入 Chroma/Qdrant/Redis，除非索引块数上万且有实测瓶颈。
- 不放开 `systemPrompt` 允许用通用知识补全运维参数。
- 不把 `minAbs` 调低来「多答一点」。
- 不改 `notify.js` 凭据目录、不让问答与推送共用 `data/auth/`。
- 不把 `07_` 手册内容打进文档示例（ZTE CONFIDENTIAL）。讨论时只写文件名。

---

## 1. 系统是什么（执行时不要走错通道）

```
群内 @机器人
    → src/whatsapp.js 抽问题、会话历史、排队
    → src/index.js onQuestion
    → src/answer.js routeAnswer
    → src/tools.js routeWithTools
         ├─ analyze_ticket  → src/tt.js → scripts/tt-analyze.py（工单事实，脚本渲染）
         ├─ query_tickets   → src/ttquery.js / src/ttsource.js（统计，脚本渲染）
         └─ search_knowledge → src/rag.js answer()（向量 + LLM 生成）← 不准的主战场
```

| 文件 | 职责 | 改准确率时 |
| --- | --- | --- |
| `src/tools.js` | 规则层 / 模型层路由；`TOOL_SPEC` | **P0 查表工具挂这里** |
| `src/rag.js` | 分块、检索、命中、生成、改写二跳 | P0 降权/出处；P1 rerank |
| `src/ingest.js` | 扫 `knowledge/`、去重、嵌入、写 `data/index.json` | P0 哈希/lookup 旁路文件 |
| `src/config.js` + `config.json` | 唯一配置源 | 新开关必须两处都加，环境变量可覆盖 |
| `src/llm.js` | 对话（云端 Agnes / 本地 Ollama） | 查表通道不要走这里 |
| `src/index.js` | 启动时 `loadIndex()` 一次 | P0 启动校验索引过期 |
| `src/whatsapp.js` | 发送、记忆、`recordQa` | P0 扩展 qa 列时改 INSERT |
| `src/qalog.js` | `data/qa.sqlite` | 旁路，写失败不得影响回复 |
| `scripts/ask.mjs` | 离线走**与群里同一条** `routeAnswer` | 验收必用 |
| `scripts/test-tools.mjs` | 路由纯函数离线测 | 每次改路由必加用例 |
| `scripts/calibrate.mjs` | 阈值校准 | 必须用领域题，禁止用年假/报销 |
| `scripts/export-tt-knowledge.py` | 从 my_app Excel 导出压缩规则/字典 | 不要手改它产出的 md |
| `autostart.ps1` | 拉起/停止问答进程 | 重启走它，先确认 |

对话模型当前：`config.json` → `chatProvider=openai`，`chatModel=agnes-3.0-flash`。  
嵌入：始终 Ollama `bge-m3:latest`，本机 `.20` **没有** Ollama，地址是内网 `.27`（`config.json` 的 `ollamaUrl`）。ingest / 检索都依赖它活着。

---

## 2. 2026-10-07 实测基线（改之前先对照，防止「改了却更差」）

在本机读取 `data/index.json` 得到：

| 项 | 值 |
| --- | --- |
| `meta.builtAt` | `2026-09-25T11:21:29.948Z`（ingest 后已过 12 天） |
| `meta.files` | **9** |
| `meta.chunks` | **816** |
| `embedModel` | `bge-m3:latest`，dim 1024 |
| `chunkSize` / `overlap` | 420 / 80 |

分文件块数（执行后应复测）：

| source | 块数 | 约占 |
| --- | --- | --- |
| `knowledge/07_iMind-eFlow-Function-Operation-Guide.md` | 421 | **52%** |
| `knowledge/TT单-告警压缩规则.md` | 110 | 13% |
| `knowledge/TT单-告警码字典.md` | 107 | 13% |
| `knowledge/02_告警衍生规则.md` | 51 | 6% |
| `knowledge/04_TT指派与推单规则.md` | 51 | 6% |
| `knowledge/03_TT级别规则.md` | 32 | 4% |
| `knowledge/01_告警到TT到指派_端到端链路总览.md` | 21 | 3% |
| `knowledge/05_指派一致性校验.md` | 14 | 2% |
| `knowledge/06_配置巡检与排障SOP.md` | 9 | 1% |
| `knowledge/08_级别缺失与排查.md` | **0（未进索引）** | — |

磁盘 `knowledge/` 当时有 **10** 个 md（含 `08_`）。索引 `sources` **没有** `08_`。  
这是现场高频问「为什么没级别 / 没 Severity」仍答「资料没有」的直接原因。README 已写：检索调参救不了没有的内容。

`data/qa.sqlite` 在 2026-10-07 体检时**不存在**。代码已接 `recordQa`（`src/whatsapp.js` 约 580 行），但进程若未跑新代码或库未创建，就没有优化样本。P0 必须确认启动日志出现 `问答记录：...qa.sqlite`。

命中阈值（`config.json`）：`minAbs=0.43`，`minGap=0.05`，`semanticWeight=0.78`，`lexicalWeight=0.22`，`idBonus=0.15`，`topK=6`。  
README 里的校准示例题是「年假/报销/天气」——**与当前 TT 语料无关**，阈值不可视为已校准。

---

## 3. 不准的根因（改代码时对号入座）

按伤害排序。每条都给出「改哪里 / 不要改错成什么」。

### 3.1 索引过期 + 启动只读一次

- `src/ingest.js` 写 `meta.builtAt` 与 `meta.sources`（约 172–185 行）。
- `src/index.js` 启动时 `loadIndex()`（约 128 行），之后内存快照不再刷新。
- **修法**：启动对比磁盘 `knowledge/` 文件集合 + mtime 与 `meta`；不一致则日志打 `⚠️ 索引过期`，`ping` 输出同样警告。ingest 后仍须重启进程才生效。
- **不要**：做热更新监听去重载 800+ 维向量（可做，但是 P2；P0 用告警即可）。

### 3.2 `07_` 手册语义黑洞

英文操作手册占一半块。中文问「级别/压缩」时，向量容易漂到通用操作段落，`topK=6` 被同一文件占满。  
`07_` 文首为 ZTE CONFIDENTIAL，命中块会随 `search_knowledge` 送到云端对话模型——合规风险与准确率问题叠加。

**修法（P0）**：默认检索排除或强降权 `07_`；仅当问法匹配「界面/菜单/如何创建用户组/how to create」时才搜手册。见任务 A3。

### 3.3 规则表被切碎后让 LLM 总结

`03_TT级别规则.md` 是表格 + 完整条件原文。`chunkText`（`src/rag.js` 约 91–149 行）按 420 字切，标题处强制断块，但**表格行仍会被切断**，AND/OR 与结论分离。  
同质「告警码 X → 父码 Y」块靠 `idBonus`（仅查询含 ≥4 位数字时）部分缓解；问「CSD 定几级」没有长数字时仍会召回错行。

**修法**：结构化查表（任务 A4），生成通道只处理真正的叙述题。

### 3.4 命中闸在 rerank 之前，且无出处、无忠实度校验

`retrieve()`（`src/rag.js` 约 181–229 行）：全库余弦 + 字符 bigram → 中位数 gap → `confident`。  
`buildMessages()`（约 263–282 行）只拼 `【i】正文`，没有文件名/标题路径。  
`systemPrompt`（`config.json`）要求 5 行以内、禁止表格——规则题会被压掉关键条件。  
`maxTokens=512`，`agnes-3.0-flash`，`temperature=0.2`。

**修法**：查表不走 LLM；叙述题强制出处；P1 再上 reranker / 摘录式作答。

### 3.5 路由静默答错面仍在

`leftoverTerms()`（`src/tools.js` 约 203–244 行）：纯中文残余只保留匹配 `SITE_WORD` 的，**中文站名/区域名会被扔掉**，规则层可能带 `site:''` 答全网。  
`help`（`src/index.js` 约 182–192 行）仍写「两类问题」，漏了统计通道。

### 3.6 没有领域黄金集，qa 资产未形成

校准脚本存在，但题集错误。无 `eval` 门禁时，任何检索改动都可能「感觉更好、实际更幻觉」。

### 3.7 商用通道约束（产品，不是调参）

Baileys 违反 WhatsApp ToS（README 开篇）。准确率做到位 ≠ 可以按商业产品卖「进现有群的 WhatsApp 机器人」。引擎（HTTP/网页）与触达（群）必须分开讲。P2 再议，P0/P1 **保持 Baileys 行为不变**。

---

## 4. 工程约定（所有任务共用）

- 注释、文档、提交说明：**中文**。
- 新增 `config.json` 字段必须：① 文件里带 `$字段名` 注释；② `src/config.js` 用环境变量覆盖；③ README 配置表补一行（若改了对外行为）。
- 新工具必须进 `TOOL_SPEC`；**未实现的工具名禁止写进 prompt**（`test-tools.mjs` [4] 已钉 `query_alarms` → null）。
- 数字、规则 ID、告警码：**脚本/查表输出原文**，禁止 LLM 改写。
- 中英固定文案成对：`src/lang.js` 的 `pickText`；加固定回复必须改 `config.json` 的 `*Text` / `*TextEn`，并补 `scripts/test-lang.mjs`。
- 回归：改 JS 后 `npm run test:js`；改路由加 `scripts/test-tools.mjs`；改分块加 `scripts/test-chunking.mjs`。
- PowerShell 多条命令用 `;`，不要 `&&`。`package.json` 的 `npm test` 内部可以用 npm 自己的 `&&`。
- 大文件改前按项目习惯在同目录留 `_bak_YYYYMMDD_说明` 快照（已 gitignore，不入库）。`src/rag.js` / `src/tools.js` / `config.json` 改动前建议快照。

---

## 5. P0 任务清单（按顺序执行，不要跳）

每条格式：**目标 / 读哪些 / 改哪些 / 怎么做 / 测试 / 命令 / 完成定义**。

---

### 任务 A1 —— 重建索引并让「过期」可见

**目标**：`08_` 进入索引；运行中的进程和 `ping` 能发现「磁盘知识 ≠ 内存索引」。

**先读**：`src/ingest.js` 全文；`src/index.js` 的 `loadIndex` 与 `builtins.ping`（约 150–180 行）；`src/buildinfo.js`（代码指纹，可对照写索引指纹）。

**改**：

1. `src/ingest.js`  
   - `meta` 增加：`knowledgeFiles`（相对路径数组，已有 `sources` 可复用）、`fileMtimes`（ISO 或 epoch）、`knowledgeHash`（所有 md 的 mtime+size 拼串的 sha256，或逐文件 `{rel,size,mtimeMs}`）。  
   - 不要把文件正文哈希得太重；size+mtime 足够发现「加了 08_ / 改了规则导出」。
2. 新建 `src/indexFreshness.js`（纯函数，便于单测）：  
   - `scanKnowledge(dir) → [{rel,size,mtimeMs}]`  
   - `diffIndex(meta, scan) → {ok, missingInIndex, extraInIndex, newerOnDisk}`  
   - `ok` 当且仅当集合一致且磁盘没有比 `builtAt` 更新年份的文件（或 mtime > builtAt）。
3. `src/index.js` 启动 `loadIndex()` 之后调用 `diffIndex`；不 `exit(1)`（Ollama 挂了都不该让 ping 死，索引过期同理），只打印警告。把结果交给 `builtins.ping`。
4. `ping` 增加两行示例：

```
知识库：816 块 / 9 个文件
⚠️ 磁盘知识比索引新：未入库 knowledge/08_级别缺失与排查.md —— 请 npm run ingest 后重启进程
```

**测试**：`scripts/test-index-freshness.mjs`  
- 假 meta 缺一个文件 → `ok=false`，`missingInIndex` 含该文件。  
- 集合一致且 mtime 都早于 builtAt → `ok=true`。  
- 钉住：过期**不抛异常**。

**命令**：

```powershell
cd D:\01_RPA\Task\whatsapp-kb-bot
npm run doctor
npm run ingest
```

ingest 依赖 `.27` 上的 `bge-m3`。失败时不要改 `ollamaUrl` 回 `127.0.0.1`（2026-10-01 事故）。

**ingest 成功后的断言**（Agent 必须打印并核对）：

- `meta.files >= 10`
- `sources` 含 `knowledge/08_级别缺失与排查.md`
- 块数应 **> 816**（08_ 会增加若干块；07_ 若仍纳入则总数上升）

**重启**：ingest **不等于**线上生效。向用户确认后：

```powershell
cd D:\01_RPA\Task\whatsapp-kb-bot
.\autostart.ps1 -Status
# 用户同意后再：
.\autostart.ps1 -Stop
.\autostart.ps1
```

只停 `index.js` 问答进程，**不要**动 `notify.js` / `autostart-notify.ps1`。

**完成定义**：`diffIndex` 在 ingest 刚完成时 `ok=true`；未重启的旧进程 `ping` 能报代码或索引过期（代码指纹已有；索引过期是本任务新增）。

---

### 任务 A2 —— 确认问答日志在写，并补「为什么答错」字段

**目标**：事后能用 SQL 看到通道、工具、检索 top1、命中文件，而不是只有运行日志一行 gap。

**先读**：`src/qalog.js`（SCHEMA 约 54–74 行；`recordQa` 约 111–136 行）；`src/whatsapp.js` 约 580–593、622–632 行；`scripts/qa-report.mjs`；`scripts/test-qalog.mjs`（若有）。

**现状局限**（文件头注释已写）：没有 gap/top/召回块，无法从库回答「为什么走错通道」。

**改**：

1. `qa_log` 用 `ALTER TABLE` **兼容旧库**（库可能已存在）。`openQaLog` 在 `CREATE TABLE IF NOT EXISTS` 之后对缺列 `ALTER TABLE ADD COLUMN`，列不存在才加。需要的新列：

| 列 | 类型 | 来源 |
| --- | --- | --- |
| `top_base` | REAL | `result.retrieval.topBase` |
| `gap` | REAL | `result.retrieval.gap` |
| `hit_source` | TEXT | top1 的 `source`，多个用 `\|` 拼前 3 个 confident 来源 |
| `route_args` | TEXT | 统计/查表的 JSON 参数（**不要**塞完整工单正文） |

2. `recordQa` 增加对应 bind；缺字段当 null。  
3. `scripts/qa-report.mjs --miss` 输出增加 `channel, tool, hit_source, top_base`。  
4. **隐私**：继续存真实号码；文件已在 `data/`，确认 gitignore 挡住 `*.sqlite*`。文档和 commit 里不要贴 sender。

**测试**：`test-qalog.mjs` 用临时库：旧 SCHEMA 打开 → 迁移出新列 → insert 一条带 `top_base` 的记录 → select 回来。

**完成定义**：本地 `npm run ask` **不会**写 qa（ask 不走 whatsapp）。可在单测里验证写入。群里验证留给重启后；Agent 在文档任务收尾写一句「需用户在群里 ping 后 `npm run qa` 应有行」。

---

### 任务 A3 —— 默认检索降权 / 排除 `07_` 手册

**目标**：领域规则题的 topK 不再被操作手册占满。问「怎么在 eFlow 里点菜单」仍能命中 `07_`。

**先读**：`retrieve()` `src/rag.js` 181–229 行；`answer()` 428–500 行；`config.json` 的 `topK` 段。

**配置（建议名，保持可关）**：

```json
"$kbSourcePolicy": "默认检索排除这些相对路径（操作手册体量大、且含厂商机密）。问法命中 kbManualIntent 时才纳入。",
"kbExcludeSources": ["knowledge/07_iMind-eFlow-Function-Operation-Guide.md"],
"kbManualIntent": "(用户组|角色|菜单|界面|如何创建|怎么创建|how to (create|open|configure)|Creating A User Group|Function Operation)"
```

`src/config.js` 增加 `kbExcludeSources`（JSON 数组或逗号分隔 env `KB_EXCLUDE_SOURCES`）、`kbManualIntent`。

**实现**：

1. `retrieve({ ..., queryText, index, cfg })` 在打分循环里：若 `!manualIntent(queryText, cfg)` 且 `chunk.source` 命中排除列表，则 **跳过**（不要给 0 分占位，否则中位数基线被拉歪）。  
2. 排除后若剩余块 < 4，`useGap` 逻辑已有 `n>=4` 退化，保持。  
3. `onDebug` 增加 `excluded: 07 count` 便于 ask --debug。  
4. **合规旁路**：排除后，这些块不会进 `buildMessages`，也就不会上传云端。这是 P0 对机密手册最有效的控制。不要在日志里打印 `07_` 正文。

**测试**（可放 `scripts/test-retrieve-policy.mjs`，用假 index 2 个块：一个 03_ 一个 07_）：

- 问题「P1 怎么判定」+ 排除开启 → hits 不含 07_。  
- 问题「how to create a user group」→ 含 07_。  
- `kbExcludeSources: []` 行为与现在一致。

**离线抽查**（ingest 之后，需 Ollama）：

```powershell
npm run ask -- --debug "告警码 198094422 会被压缩成什么"
npm run ask -- --debug "为什么TT没有级别"
npm run ask -- --debug "怎么创建一个用户组"
```

期望：前两题 candidates 的 source **不应**全部/主要是 `07_`；第三题允许 `07_`。

**完成定义**：假 index 单测绿；debug 抽查符合上表。不要为了让第三题更好而重新纳入所有 07_ 块到默认检索。

---

### 任务 A4 —— 结构化查表工具（准确率最大杠杆）

**目标**：下列问法**禁止**走 RAG 生成。由脚本查表，模板渲染，带出处。

| 用户问法（中英都要） | 工具名 | 答案形态 |
| --- | --- | --- |
| 「告警码 99933 是什么意思」「what is alarm code 9920」 | `lookup_alarm_code` | 码、含义、可选累计单数（字典里有就带，没有就省略） |
| 「198094422 会被压缩成什么」「压缩后的父告警」 | `lookup_compress` | 子码 → 父码、规则名、父告警名称、ENABLED/DISABLED |
| 「告警码 9990 NORMAL 非 VIP 是几级」「P1 规则有哪些」 | `lookup_level_rule` | 匹配到的规则 ID/名称/级别/条件摘要；纯「P1 是什么」给 P1 规则列表而非编定义 |

**不要**新增一个没有实现的 `query_alarms` 到 `TOOL_SPEC`。

#### A4.1 旁路数据文件（ingest 时生成）

新建 `src/lookups.js` + ingest 末尾写 `data/lookups.json`（gitignore：确认 `data/*.json` 规则；若 `index.json` 已被忽略，把 `lookups.json` 同样忽略。源数据在 `knowledge/*.md` 与 Excel）。

建议结构（字段名固定，渲染与测试都依赖）：

```json
{
  "builtAt": "ISO",
  "alarmCodes": {
    "99933": { "code": "99933", "name": "SITE DOWN DUE TO POWER OFF", "source": "knowledge/TT单-告警码字典.md" }
  },
  "compress": [
    {
      "ruleId": "zte-4g-siteoutage",
      "childCodes": ["198094422", "2114322696", "198094419"],
      "parentCode": "9970",
      "parentName": "4G site down",
      "status": "ENABLED",
      "source": "knowledge/TT单-告警压缩规则.md"
    }
  ],
  "levelRules": [
    {
      "id": "227",
      "name": "无线断站级别重定义-P2-new",
      "severity": "P2",
      "priority": 3,
      "alarmCodes": ["9970", "9980", "9990", "9910", "9920", "99933"],
      "when": "assetType=NORMAL AND vipSite=0 AND alarmCode in ...",
      "source": "knowledge/03_TT级别规则.md"
    }
  ]
}
```

**解析来源（优先 markdown，与线上语料一致）**：

- 字典：`### 告警码 (\d+)` + 下一行 `- 含义：`（见 `knowledge/TT单-告警码字典.md`）。
- 压缩：`### 压缩规则速览：(\S+)` 段里的「基础告警」「衍生告警（父告警）根告警码」（见该文件第 7 行起）。同一码可能出现在多条规则（ENABLED 优先于 DISABLED 展示，DISABLED 必须标注，禁止当启用规则输出）。
- 级别：`03_TT级别规则.md` 开头表格列「优先级 / ID / 规则名称 / 级别 / 条件」；告警码从条件列抽 `\d{3,}`。完整 matcher 与 `scripts/tt-analyze.py` 对齐是 P1；P0 先做到「按码列出候选规则 + 条件原文」，**不要在 P0 实现一套会与 eFlow 不一致的伪匹配引擎**。若用户同时给了站点属性（VIP/NORMAL/ERA），只**过滤**表格里写明该条件的行；吃不准就列出候选并写「未做完整规则引擎匹配，请用分析 TT 单号核实」。

解析失败要在 ingest 日志里报「lookup 某节 0 条」，不要静默空对象。

`loadLookups()` 与 `loadIndex()` 一样启动时读一次；文件缺失时查表工具返回「查找表未构建，请 npm run ingest」，**不要** fallback 进 RAG 装懂。

#### A4.2 规则层识别（`parseByRule`）

在 `src/tools.js` 的 `parseByRule` 里，**单号仍最优先**（已有 `extractTtNos`）。然后：

```
若问题抽到 ≥1 个长数字（建议 \d{3,}，注意级别规则里也有 8、47 这种短码——短码只在「告警码」上下文触发）
且问法匹配：
  含义/是什么意思/what is / meaning / 字典     → lookup_alarm_code
  压缩/父告警/compress/parent / 会被压        → lookup_compress
  级别/定级/P1~P4怎么判/severity rule         → lookup_level_rule
```

与统计意图冲突时：有「多少/几个」走 `query_tickets`（已有）；「告警码 198094422 会被压缩成什么」已有测试要求不得当统计（`test-tools.mjs` [3] q8）。

无数字但问「P1 是什么级别 / P1 怎么判定」→ `lookup_level_rule` 且 args `{ severity: "P1" }`，不要 RAG。

中文站名任务见 A6，不要和本任务缠在一起。

#### A4.3 模型层 `TOOL_SPEC`

给三个新工具各写 **args JSON 示例**。`routeByModel` 的 prompt 增加：

- 有告警码且问含义/压缩/级别 → 对应 lookup，**不要** `search_knowledge`。
- 拿不准且无码 → `search_knowledge`。

`runTool` 分支：查表 → `renderLookup*(data, lang)` 纯函数。失败/未找到：固定文案，`answered=false`，可附 `webUiFallback`（已有 `withWebHint`）。

#### A4.4 渲染要求（中英）

中文示例（压缩）：

```
告警码 198094422 → 压缩父告警 9970（4G site down）
规则：zte-4g-siteoutage（ENABLED）
来源：TT单-告警压缩规则.md
```

未找到：

```
知识库告警码表里没有 12345。我不会按通用知识猜。
```

英文走 `*TextEn` 风格，数据字段（规则中文名）保持原文，与 TT 通道「数据行不翻译」一致（README 回复语言节）。

**禁止**：把查表结果再交给 `chat()` 润色。

#### A4.5 测试

`scripts/test-lookups.mjs`（纯离线，读仓库内 knowledge md 或内嵌样例字符串）：

- 解析字典：`99933` → 名称含 `SITE DOWN` 或 `POWER`。  
- 解析压缩：`198094422` → parent `9970`，ENABLED 规则优先。  
- `parseByRule('告警码 198094422 会被压缩成什么')` → `lookup_compress`。  
- `parseByRule('P1 是什么级别')` → `lookup_level_rule` 或至少不是 `query_tickets`。  
- 渲染函数：输出含来源文件名；不含 Markdown 标题 `#`。

把该脚本加入 `package.json` 的 `test` 与 `test:js`。

**完成定义**：`npm run ask -- "告警码 198094422 会被压缩成什么"` 的 `describeRoute` 显示新工具名（需在 `src/answer.js` `describeRoute` 增加 `channel==='lookup'` 或复用 `tool=`）。回答含 `9970` 且含「来源」。

---

### 任务 A5 —— 知识生成通道强制出处；缩短幻觉面

**目标**：仍走 RAG 的叙述题（流程、为什么、SOP）必须列出依据文件；模型改写数字时宁可拒答。

**改 `buildMessages()`**：每个 confident 块前缀改为：

```
【1｜knowledge/03_TT级别规则.md｜标题】
正文
```

**改 `systemPrompt`**（`config.json`）增加硬规则：

- 结论后用一行 `来源：文件名`（可多个）。  
- 不得输出资料中未出现的规则 ID、告警码、阈值。  
- 资料不够时只说覆盖部分（已有第 4 条），不要补全。  
- **放宽「5 行以内」为「优先短，规则/条件需要时可到 12 行」**，避免把 AND/OR 剪掉。这是准确率优先于聊天美观。  
- 仍禁止编表格代码块也可以，但允许短横线列点超过 5 条。

**改 `looksLikeMiss` 之后**：若生成文本含数字（`\d{3,}`）而所有 confident 块拼接串**都不含**该数字 → 丢弃生成，改回 `notFoundText` 或只返回 top1 原文摘录（前 400 字）+ 来源。实现放 `src/rag.js`，纯函数 `ungroundedIds(answer, hits)` 便于单测。

**测试**：假 hits 正文只有 `9970`，模型假输出（单测里直接测 `ungroundedIds`，不要 mock 网络）含 `12345678` → 判定 ungrounded。

**不要**在 P0 把 temperature 改到 0 以外大改模型供应商。

---

### 任务 A6 —— 中文专名不要被 leftoverTerms 吃掉；help 补第三通道

**目标**：避免「蒙塞拉多昨天几单」规则层带空站点答全网。

**改 `leftoverTerms`**：删除「纯中文只保留 SITE_WORD」的短路，或改为：剥完已知词后，长度 ≥ 2 的中文片段一律视为残余专名 → `parseByRule` 返回 null 交模型。  
误伤：「昨天一共有多少单」剥完应仍为空（已有测试）。补充用例：

- `leftoverTerms('蒙塞拉多昨天有多少单')` 非空。  
- `parseByRule('蒙塞拉多昨天有多少单', NOW) === null`。

**改** `src/index.js` `help` 与英文若有：增加「今天/昨天有几个 P1 → 查工单统计」。`scripts/test-lang.mjs` 若断言 help 全文，一并改。

**完成定义**：`test-tools.mjs` 新用例绿；help 含统计通道。

---

### 任务 A7 —— 领域黄金集 + `npm run eval:kb`

**目标**：以后改检索/路由必须先跑题集。P0 至少 **30 条**，不要求全自动判语义，先判通道 + 关键子串。

**新建** `evals/kb-golden.jsonl`（入库，不含敏感号码）。每行：

```json
{
  "id": "cmp-198094422",
  "q": "告警码 198094422 会被压缩成什么",
  "lang": "zh",
  "expectChannel": "lookup",
  "expectTool": "lookup_compress",
  "mustInclude": ["9970"],
  "mustNotInclude": ["专利"],
  "notes": "压缩查表"
}
```

建议题（必须覆盖）：

**lookup / 知识**

1. 告警码 198094422 会被压缩成什么 → 9970  
2. 99933 是什么意思 → POWER / SITE DOWN  
3. 9920 是什么告警 → Complete site down / CSD  
4. P1 是什么级别 / P1 怎么判定 → 不得走 query_tickets；应出现规则 225/226 或「vip/downSite」相关条件  
5. 为什么 TT 没有级别 / 为什么没有 Severity → 命中 08_ 或查表说明「级别来自 ttLevelRule 不是告警 Severity」  
6. 告警驱动如何创建 TT / autoCreateTT  
7. Regular 电源故障推给谁（规则 #200 相关，若语料有）  
8. 英文：how is a TT created from an alarm  
9. 英文：what does alarm code 9991 mean  
10. 无关：今天北京天气怎么样 → answered false 或 notFound 文案特征  

**路由（可不调 LLM）**

11. 今天有p1的单子吗 → query_tickets  
12. 昨天一共有多少单 → query_tickets  
13. P1 是什么级别 → 非 query_tickets  
14. TT202609150073 → analyze_ticket  
15. WO202609220055 → analyze_ticket  
16. Wood camp 这个站昨天有几个单 → parseByRule null（模型层）  
17. 本月有几个P1的单子，请输出TT单的ID给我 → query_tickets + list  

**stats/tt 的 mustInclude** 在 eval 脚本里对 `parseByRule` 断言即可，避免 eval 打生产库。标 `"offlineOnly": true` 的行只测纯函数。

**新建** `scripts/eval-kb.mjs`：

- 读 jsonl。  
- `offlineOnly`：只 `parseByRule` / lookup 纯函数。  
- 其余：`routeAnswer`（需索引 + 嵌入 + 可能云端）。`--offline` 跳过后者。  
- 退出码：有失败则 1。打印表格：id, channel, tool, pass。  
- `package.json`：`"eval:kb": "node --env-file-if-exists=.env scripts/eval-kb.mjs"`，`"eval:kb:offline": "... --offline"`。

**校准**：用黄金集里 label 为知识命中/无关的题跑 `scripts/calibrate.mjs`，把建议 `minAbs/minGap` 写回 `config.json` **仅当**间隔足够且回测 ≥ 黄金集 miss 题全拒。间隔过窄不要硬改，在 PR 说明里写实测数字。

**完成定义**：`npm run eval:kb:offline` 全绿；在线 eval 在 ingest 后尽量跑，失败的题记入 jsonl `notes` 而不是删题。

---

### 任务 A8 —— README / help 与手册同步（短）

在 `README.md`「工具路由怎么决定走哪条通道」表增加第 ④ 行「告警码/压缩/级别查表」。  
不要把本文全文贴进 README。README 顶部加一句链到本文：

`准确率与商用改造步骤见 docs/准确率商用优化-AGENT执行手册.md`

---

## 6. P0 推荐实施顺序与依赖

```
A1 ingest 可见性（代码） ─┬─→ 用户确认后 ingest + 重启
A3 07 排除（可与 A1 并行）┘
A4 lookups 解析 + 路由     ── 依赖 knowledge md 稳定；ingest 写 lookups.json
A5 出处与数字护栏          ── 不依赖 A4，但 A4 之后 RAG 流量变少
A6 leftover + help
A2 qa 列                   ── 可并行
A7 黄金集                  ── 依赖 A4 工具名稳定，最后写 eval
A8 README 链接
```

同一 PR 可包含 A3–A6 + A7 offline。A1 的真实 ingest 需要网络到 `.27`，可单独操作窗口。

---

## 7. P1 任务（P0 完成后再开；本文仍写细，避免下个 Agent 重新设计）

### B1 Parent-child 分块

- ingest 时每个 chunk 增加 `parent`：所属 `##` 标题路径、`ruleId`/`alarmCodes[]`（正则从块内抽）。  
- 检索仍用小块；`buildMessages` 把同一 parent 的相邻 seq 块合并，上限例如 1200 字。  
- 回归：`test-chunking.mjs` 不变量「单块 ≤ chunkSize」仍必须成立。

### B2 词级 BM25 + 向量；命中改在融合之后

- 不要引入 ES。JS 可用轻量 BM25（自行实现 idf + tf 即可，中文按字 bigram 已有，英文按 token）。  
- 融合后再取 topK，再跑现有 minAbs/minGap（或改为对 rerank 分）。  
- 配置 `lexicalWeight` 对英文 token 与中文 bigram 可分开。

### B3 Reranker

- 候选先取 top 20（融合分），用 Ollama 上的 rerank 模型或本地小 cross-encoder 打分，截 topK=6。  
- **先确认 `.27` 能否 pull rerank 模型、内存是否与 bge-m3 并存**（README 写过 `OLLAMA_MAX_LOADED_MODELS`）。本机 `.20` 无 Ollama，不要假设本机能跑。  
- 若 rerank 不可用：代码降级到现融合分，启动警告，不要 exit(1)。

### B4 MMR 多样性

- topK 内同一 `source` 默认最多 3 块，可配 `mmrMaxPerSource`。  
- 单测：6 个候选 5 个同 source → 截断后该 source ≤ 3。

### B5 级别规则真匹配（可选，高价值）

- 不要复制一份会漂移的 JS matcher。  
- 做法：`lookup_level_rule` 在用户给了码+属性时，调现有 `scripts/tt-analyze.py` 的 `build_value_frame` + `eval`（抽成可 import 的函数），或加 `--lookup-level code=9990 asset=NORMAL vip=0` CLI。  
- 口径必须与工单分析一致。缺字段时输出 `incomplete`，措辞对齐实时通道「未能核对规则」（README 实时行一节）。

### B6 站点别名

- 从 `eflow_tt` 或站点表导出 `site_id / site_name` 小缓存（gitignore）。  
- 模型抽 `Wood camp` 后用别名规范化再查统计。  
- 注意：`query_tickets` 带站名目前走 SQLite 降级（README）。不要为了别名去改 PG overview 的 adv JSON，除非同时改 my_app 并写手册。

### B7 生成改为摘录优先

- 叙述题：回答 = 排序后块的原文句子抽取 + 一行来源，LLM 只做句子选择不改数字。  
- 若继续用 flash：仅用于改写问句 / 路由 JSON。

### B8 eval 扩到 80–100 条并接入习惯命令

- 从 `npm run qa:miss` 人工挑错题进 jsonl。  
- 不把真实手机号写入 jsonl。

---

## 8. P2 商用形态（决策项，代码 Agent 默认不做）

写在这里是为了避免有人把 P0 当成「已经商用」。

| 项 | 说明 | Agent 默认 |
| --- | --- | --- |
| WhatsApp ToS | Baileys 进现有群不合规，有封号风险 | 不改通道 |
| 机密出域 | `07_` 不得进免费云模型 | P0 排除已缓解；不要再把 07_ 全文塞进 prompt |
| 问答引擎 API | 给网页 `webUiFallbackUrl`、门户复用同一 `routeAnswer` | 未要求则不做 HTTP 服务 |
| SLA | 嵌入 `.27` 依赖、Agnes 免费额度 | 不换供应商，除非用户指定 |
| 多角色知识隔离 | FO/FE 看到的手册不同 | 未要求不做 |
| 人工反馈 | 群里「这条不对」写入 qa | 未要求不做 |

若用户明确要求「商用交付清单」，输出独立文档，不要在本仓库实现官方 WhatsApp 接入，除非产品已经接受「不能进已有大群」。

---

## 9. 商用验收指标（对照用）

| 指标 | P0 后 | P1 后（建议门槛） |
| --- | --- | --- |
| `eval:kb:offline` | 100% | 100% |
| 在线黄金集通道正确率 | ≥ 90% | ≥ 95% |
| 在线 `mustInclude` | ≥ 85% | ≥ 90% |
| 无关问题拒答 | 黄金集 miss 全过 | ≥ 95% |
| 幻觉（答了资料没有的码） | A5 护栏拦截 | &lt; 2%（人工抽 50 条） |
| 工单统计与看板口径 | 不改现有即可 | 保持 100% 脚本渲染 |
| 出处 | RAG 与 lookup 均有文件名 | 有章节/规则 ID |
| 索引新鲜度 | ping 可见 | ingest 流水线与 export-kb 绑定 |

未达 P1 门槛前，不要对值班承诺「可以当派单依据」。lookup 通道可以先承诺「码表与导出文档一致」。

---

## 10. 命令速查（Agent 复制区）

工作目录一律先 `cd D:\01_RPA\Task\whatsapp-kb-bot`。

```powershell
npm run doctor
npm run test:js
npm run ingest
npm run ask -- --debug "为什么TT没有级别"
npm run ask -- "告警码 198094422 会被压缩成什么"
npm run eval:kb:offline
npm run eval:kb
npm run qa
npm run qa:miss
.\autostart.ps1 -Status
```

单测只跑路由：

```powershell
node scripts/test-tools.mjs
```

**不要**在文档或命令里写 `AGNES_API_KEY` 的值。需要云端 ask 时使用已有 `.env`（已 gitignore）。

---

## 11. 建议的文件变更清单（P0）

新建：

- `src/indexFreshness.js`
- `src/lookups.js`
- `scripts/test-index-freshness.mjs`
- `scripts/test-lookups.mjs`
- `scripts/test-retrieve-policy.mjs`
- `scripts/eval-kb.mjs`
- `evals/kb-golden.jsonl`
- `docs/准确率商用优化-AGENT执行手册.md`（本文）

修改：

- `src/ingest.js` — meta 哈希、写 `data/lookups.json`
- `src/index.js` — 启动校验、ping、help、loadLookups
- `src/rag.js` — 排除源、buildMessages 出处、ungrounded 检测
- `src/tools.js` — parseByRule、TOOL_SPEC、runTool
- `src/answer.js` — describeRoute 识别 lookup
- `src/config.js` / `config.json` — 排除列表、lookup 路径
- `src/qalog.js` / `src/whatsapp.js` — 新列
- `scripts/qa-report.mjs` — 展示新列
- `scripts/test-tools.mjs` — A4/A6 用例
- `package.json` — test / eval 脚本
- `README.md` — 链到本文、第四通道

**不要修改**（除非任务明确点名）：

- `src/notify.js`、`data/auth-notify/`
- `nginx` 配置
- `scripts/tt-analyze.py` 的匹配口径（B5 才能扩 CLI，且要单测）
- `knowledge/07_*.md` 正文（机密；最多不检索）
- 手工编辑 `TT单-告警压缩规则.md` / `TT单-告警码字典.md`（下次 `export-kb` 会覆盖）

---

## 12. 禁止事项（违反即视为执行失败）

1. 用降低 `minAbs` / `minGap` 换更高「有回答率」。  
2. 把 `systemPrompt` 改成允许资料外知识。  
3. 查表结果再送进 LLM 润色。  
4. `TOOL_SPEC` 写未实现工具。  
5. ingest 后不提醒用户重启，却宣称「08_ 已生效」。  
6. 重启 `notify.js` 或共用 `data/auth/`。  
7. 把 `07_` 正文、API Key、群成员号码写进 commit / 新文档 / 黄金集。  
8. 为调参在仓库根或 `src/` 下生成 `_dump.txt`、把 `index.json` 强制 add 进 git（确认 ignore）。  
9. 用年假/报销题跑 calibrate 并覆盖 `config.json`。  
10. PowerShell 里对用户环境执行 `git push` / `force` / 改 git config。

---

## 13. 给执行 Agent 的自检报告模板

任务结束时用中文输出（不要只说「已完成」）：

```
## 改了哪些文件
## ingest：是否已跑 / meta.files / 是否含 08_ / 块数
## 是否已请用户确认重启 / 用户怎么说
## npm run test:js：通过或失败摘要
## npm run eval:kb:offline：通过数
## ask 抽查：3 条问题的通道 + 是否含必须子串
## 未做项与原因（对照 P0 清单）
## 风险：仍可能静默答错的问法
```

---

## 14. 设计决策（避免下个 Agent 改回去）

1. **工单数字永远脚本渲染** —— 2026-10-06「今天有 P1」曾被当成知识题。不要合并通道。  
2. **答错不如弃权** —— 规则层对残余专名返回 null。不要为了少一次模型调用而带空 `site` 短路。  
3. **重复块按全文去空白精确去重** —— 不要用前缀去重（`chunkOverlap` 会误删）。见 `dedupeChunks`。  
4. **440 不重连** —— 与准确率无关，但改 whatsapp 接入时不许改回。  
5. **删除优于兼容** —— 内部路由不要同时保留「纯 RAG 回答规则题」和 lookup 双写；规则题走 lookup 后，RAG 不再承担码表。`toolsEnabled=false` 仍可整段退回纯知识库，作为排障开关保留。

---

## 15. 背景会话

本手册来自 2026-10-07 对 `whatsapp-kb-bot` 的准确率评审：知识通道召回被过期索引、`07_` 占比、规则表切碎 + flash 生成共同拖累；工单通道设计正确。用户要求输出「可让其他 AGENT 直接执行」的详细 MD，即本文。
