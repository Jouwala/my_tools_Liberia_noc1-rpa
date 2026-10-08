# 排障复盘：站点告警答成 tickets:0 ／ answered=0 ／ degraded=1

> **受众**：后续维护本机器人的开发者 / Agent。读完应能**复现现象、定位根因、理解改动、独立验收**。
> **日期**：2026-10-08
> **项目根**：`D:\01_RPA\Task\whatsapp-kb-bot`（网络映射 `Y:\Task\whatsapp-kb-bot`）
> **触发**：群里 @机器人 问「*Palm Bay* check if this site is up or not? and if have TT?」，
> 机器人回了一句 `2026-10-08 / tickets: 0`；同一批提问里还有几条回「Sorry, something went wrong」。
> **关联文件**：`src/tools.js`、`src/rag.js`、`src/index.js`、`src/ttquery.js`、`src/ttsource.js`、
> `scripts/eflow-live-alarms.py`（新）、`src/sitealarms.js`（新）。

---

## 0. 一句话结论

用户问的是**「这个站点现在有没有告警」**（实时事实），但当时机器人**根本没有「按站点查告警」这个工具**，
只能把问题硬塞进 `query_tickets`（工单数量统计）。工单表按**站名**匹配≈0 单，于是回了一句 `tickets: 0` ——
**「0 张工单」被读成了「站点没告警」**。这是一个**自信的错误答案**，比报错严重得多。

同时暴露两个独立问题：嵌入模型缺失导致 `answered=0`，本地副本口径导致 `degraded=1`。

---

## 1. 现象与定性（先分清「答错」还是「没答上」）

群里实际对话：

```
[20:03] Dong: @bot *Palm Bay* check if this site is up or not? and if have TT?
[20:03] bot : 2026-10-08
             tickets: 0
[20:06] Dong: @bot *check alarm for site name Palm Bay form eflow
[20:06] bot : Searching the knowledge base and ticket DB — will get back to you in a moment.
[20:06] bot : Sorry, something went wrong on my side. Please try again in a moment.
[20:06] Dong: @bot check alarm for site name Palm Bay form eflow   ← 去掉 * 重发
[20:06] bot : 2026-10-08
             tickets: 0
```

三种结局，**必须分开定性**（混在一起就会修错）：

| 表现 | 定性 | 判据来源 |
| --- | --- | --- |
| `tickets: 0` | **答了，但答非所问** | 最危险：看起来"跑通了" |
| `Sorry, something went wrong` | **没答上**（真故障） | 嵌入服务异常 |
| `degraded=1`（本地副本） | **答了，但口径可疑** | 数据可能滞后 |

### 1.1 权威判据是 `data/qa.sqlite`，不是 `data/logs/*.log`

`logs/bot-YYYY-MM-DD.log` 只记**提问**与元数据（`命中=true` 只代表"产出了一条消息"，
**不代表答对了**）。真正的判据在问答库 `data/qa.sqlite` 的 `qa_log` 表：

```sql
-- 最近 10 条，看 answered / channel / degraded
SELECT id, ts, sender, question, answer, answered, channel, tool, via, ms, lang, degraded
FROM qa_log ORDER BY id DESC LIMIT 10;
```

关键列语义（见 `src/qalog.js` 建表注释）：

- `answered`：1=答上了，0=没答上（未命中/失败）。**这是"有没有答"的唯一权威**。
- `channel`：`tt` / `stats` / `kb` / `lookup` / **`error`**（= 抛异常了）。
- `degraded`：是否走了本地 SQLite 副本（口径可能滞后）。

> ⚠️ 教训：**只看服务器日志会把 `answered=0` 误判成成功**。日志里 `[回复] 命中=true` 出现过，
> 但同一时刻 qa_log 里 `answered=0, channel=error`。两者不矛盾——日志记的是"发了消息"，
> 发的内容是那句固定的错误话术。

---

## 2. 根因链（三个症状，三个独立根因）

```
用户问「Palm Bay 有没有告警」
        │
        ├─ 理想：调 eFlow 告警接口（按站点）→ 返回实时告警列表
        │
        └─ 现实：TOOL_SPEC 里**没有**这个工具（src/tools.js）
                 ├─ 落到 query_tickets（模型层选的）→ 站名非空 →
                 │    ttsource.js 强制走本地 SQLite → 匹配≈0 单 → "tickets: 0"
                 └─ 若落 search_knowledge → 需要 bge-m3 嵌入 → 404 → answered=0
```

### 根因 A：工具集缺口（治本要务）

`src/tools.js` 的 `TOOL_SPEC` 原本只有 5 个工具：

| 工具 | 维度 |
| --- | --- |
| `query_tickets` | **工单数量**（start/end/severity/status/site） |
| `analyze_ticket` | 单票详情（按 TT/WO 单号） |
| `lookup_alarm_code` / `lookup_compress` / `lookup_level_rule` | 静态**查表**（告警码含义/压缩/级别规则） |
| `search_knowledge` | 知识库向量检索 |

代码里甚至有一条注释明说这个取舍：

```js
// 刻意只列**当前真能用**的工具 —— 写进去一个没有实现的 query_alarms，
// 模型会真的去调它，然后得到一个"工具不存在"的失败，比没有这个工具更糟。
```

**"告警"这个概念，机器人当时只认识"告警码字典/压缩/级别规则"（静态知识），
不认识"某站点当前的告警事件"（实时数据）。** 而用户问的恰恰是后者。

### 根因 B：`site` 非空 = 强制本地副本（degraded 的来源）

`src/ttsource.js` 的 `queryTickets`：

```js
const httpEnabled = CONFIG.ttStatsHttp !== false && !!CONFIG.myAppApiBase;
if (httpEnabled && !q.site) {          // ← site 非空时，跳过 my_app HTTP
  // 走 my_app HTTP（PG 实时）
} else {
  // 走本地 SQLite 副本（有同步延迟）→ degraded=true
}
```

设计意图是"本地库有 site_name 能做模糊匹配"，代价是**按站点查必然走本地副本**，
天然带 `degraded=1`。这不是 bug，但在本案里叠加了"A 的误路由"，
让 `tickets: 0` 看起来更像"站点正常"。

### 根因 C：嵌入模型缺失（answered=0 的直接原因）

`logs/bot-2026-10-08.log` 里四条失败全是同一异常：

```
Error: Ollama /api/embed 返回 404：model "bge-m3:latest" not found, try pulling it first
    at async answer (…/src/rag.js:740) → runTool → routeWithTools → routeAnswer → onQuestion
```

`config.json` 的 `ollamaUrl: http://192.168.100.27:11434`、`embedModel: bge-m3:latest`，
**那台 .27 上 bge-m3 没拉**。凡是落到 `search_knowledge` 兜底的提问，嵌入 404 → 异常上抛 → `errorText`。

> 注：`src/index.js` 原有 `qaAvailable` 启动探针，但只在**启动时**查一次；
> 模型在运行中被卸载/删除后无运行时复检，探针挡不住。

---

## 3. 改动清单（都已落地）

### 3.1 新增：按站点查实时告警（治本）

| 文件 | 作用 |
| --- | --- |
| `scripts/eflow-live-alarms.py`（新） | 桥接：复用 my_app 的 `eflow_alarm_service._fetch_alarm_pipeline` 拉**全量活动告警**，本地按站名规范化匹配后输出 JSON |
| `src/sitealarms.js`（新） | Node 执行模块：spawn 上面的脚本，解析退出码，渲染中英双语文案 |

**为什么"拉全量再本地过滤"而不是"让 eFlow 按站点过滤"**：
仓库里**没有** `/api/fm-active/v1/activealarms/table` 带站点过滤的抓包样例
（`my_app/backend/services/URL_EFLOW_ALARM.txt` 只有 detail/subtab 调用），
键名靠猜会 400 **或静默返回空**——后者最危险，会把"查不了"伪装成"没告警"。
活动告警总量很小（实测 60 条量级），拉全量再本地过滤代价可忽略。

**退出码语义（与 `eflow-live-tt.py` 对齐，绝不混淆"无告警"与"查不了"）**：

| 退出码 | 含义 | 语义 |
| --- | --- | --- |
| 0 | 查到站点且**有**活动告警 | answered，附明细 |
| 1 | 站点**干净**（无活动告警） | answered，明确说"当前无活动告警" |
| 2 | 通道不可用（缺解释器/依赖） | **未答**，让用户去 eFlow 看板 |
| 3 | 真出错（登录/网络） | **未答**，可重试 |
| 4 | 查无此站 | **未答**，提示核对站名 |

**凭据**：只读 my_app 那一份（`eflow_api_client` → `credential_store`/`auth_manager`），
机器人侧**不另存密码**。

### 3.2 `src/tools.js`

- `TOOL_SPEC` 加 `query_site_alarms`（含参数 `site`）。
- `parseByRule` 加 **站点告警意图**（`SITE_ALARM_INTENT` + `extractSiteName`），
  规则层能抓到站名时**直接命中**（省一次模型调用）；抓不到则弃权交模型层。
  - 判据锚在**告警状态语义**上（告警/alarm/up/down/掉站/断站…），光有站名不算。
  - 抽出**带 `!extractAlarmCode(q)` 守卫**：有告警码的问题仍走 `lookup_*`。
- `runTool` 加执行分支，返回 `channel: 'sitealarm'`。
- `ROUTER_PROMPT` 加规则，并**明确禁止**把"站点 up/告警"类问题路由到 `query_tickets`。

### 3.3 `src/rag.js` —— 嵌入失败就地降级

`answer()` 里的 `await embedOne(question)` 改为 try/catch：
嵌入异常不再冒泡成含糊的 `errorText`，而是回一句**说清原因、可行动**的话
（"知识库此刻不可用（嵌入服务异常：…），可改问 XX站有没有告警 / 查 TT单号"）。
`answered` 仍为 false（确实没答上），但语义明确。

### 3.4 `src/index.js` —— 去掉 `qaAvailable` 整条短路

**旧行为**：`qaAvailable=false` 时，`onQuestion` 直接返回"知识库不可用"——
把**不依赖嵌入**的通道（TT 单号分析、工单统计、按站点查告警、告警码查表）也一起挡死。
"坏一半"被升级成"全坏"。

**新行为**：交给 `routeAnswer` 正常路由。工具通道照常工作；
知识库通道由 `rag.js` 就地捕获（见 3.3）。`qaAvailable` 仅保留作启动自检打印。

### 3.5 `src/ttquery.js` —— 站点+0 单的措辞

`renderStats` 在 `site` 非空且 `total===0` 时，用专门文案点明**这是工单数量**：

```
工单：0（站点 Palm Bay；这是工单数量，不代表该站没有告警，查告警请直接问「Palm Bay 有没有告警」）
tickets: 0 (site Palm Bay; this is a ticket count, not an alarm status — ask "Palm Bay alarms" for live alarms)
```

其余零结果（纯级别 0、无条件 0）**保持原样**，不误伤。

### 3.6 `config.json` / `src/config.js`

新增 `ttSiteAlarmFallback`（默认开）+ `ttSiteAlarmTimeoutMs`（默认 180000），
环境变量 `TT_SITE_ALARM_FALLBACK` / `TT_SITE_ALARM_TIMEOUT_MS` 可覆盖。

### 3.7 `scripts/test-tools.mjs`

加 `[3d] 站点告警意图 → query_site_alarms` 段（10 项，含 5 条反向断言）。

---

## 4. 验收（怎么证明修好了）

### 4.1 单元测试（离线，全绿）

```powershell
cd D:\01_RPA\Task\whatsapp-kb-bot
node scripts/test-tools.mjs      # 102 项
```

本次相关套件结果：test-tools 102、test-mentions 39、test-chunking 34、test-dedupe 21、
test-runtime 54、test-lang 81、test-tt-extract 32、test-lookups 58、test-retrieve-policy 42 —— 全绿。

### 4.2 脚本直测（在机器人机器上，需能连 eFlow 10.100.20.8）

```powershell
python scripts\eflow-live-alarms.py --which            # 应打印一个解释器路径
python scripts\eflow-live-alarms.py "Gbonebu"          # 有告警→exit 0；干净→exit 1
```

### 4.3 端到端（群里）

```
@bot Gbonebu check if this site is up or not? and if have TT?
→ Gbonebu has *no* active alarms right now (not present in the eFlow live active-alarm list).
```
（2026-10-08 22:06 实测通过。）

---

## 5. 遗留与注意

1. **`ollama pull bge-m3`（.27）** —— 已在 2026-10-08 执行，`answered=0` 的直接根因已消除。
   仍需注意：模型可能被后续操作卸载，`rag.js` 的降级（3.3）是兜底，不是解决方案。
2. **`degraded=1` 的语义** —— 按站点查告警**不走** `ttsource.js` 的工单统计路径，
   所以新工具不受 `degraded` 影响；但用户若问"某站的**工单**"，仍会走本地副本、仍带 `degraded=1`。
   这是设计（`ttStatsHttp` 只在无 site 时走 HTTP），**不是本次要改的**。
3. **站名匹配是"规范化包含"**（去空格 + 大小写不敏感）。
   站名如高度相似（`Palm Bay` vs `Palm hill`）不会误配（前者含 "palmbay" 后者含 "palmhill"）。
   若日后出现真正歧义站名，需引入 `master_site_db` 的 site_id 做精确解析。
4. **"有告警但没建单"** —— 脚本输出里 `tt` 字段为空即代表该活动告警尚无 TT。
   这正好可复用于回答"为什么还没建单"，是下一步的自然延伸（本次未做）。
5. **不要**把站点过滤下推给 eFlow 活接口，除非先抓到真实的带站点过滤的请求样例 ——
   见 §3.1 的理由。

---

## 6. 给下一个人的排查顺序（口诀）

1. **先分清"答错"还是"没答上"** → 查 `data/qa.sqlite` 的 `answered`/`channel`，**别只看 logs**。
2. `channel=error` → 看同刻日志的异常栈（多半是 Ollama 嵌入，见 §2 根因 C）。
3. `answered=1` 但内容不对 → 看 `tool`/`via`，**是工具选错了**（本案就是 `query_tickets` 顶替了告警查询）。
4. `degraded=1` → 说明走了本地副本，口径需打问号（`ttsource.js` 的 `!q.site` 分支）。
5. 修"工具选错"两类手段：**(a)** 规则层加意图（省钱、可控）；**(b)** 改 `ROUTER_PROMPT`（兜长尾）。
   两者都要配 `test-tools.mjs` 的**反向断言**，防止误伤其它通道。
