# WhatsApp Bot 5天英文问题测试计划

> **目标**：验证机器人在英文提问场景下的各通道正确性  
> **日期**：2026-10-09 ~ 2026-10-13  
> **测试方式**：离线脚本验证（`npm run ask`）+ 真实群测

---

## 📋 测试概览

| 天数 | 主题 | 覆盖通道 | 重点验证 |
|------|------|----------|----------|
| Day 1 | 基础路由与语言判定 | 路由/语言 | 分流是否正确 |
| Day 2 | 知识库问答（KB） | RAG | 检索命中 + 英文回复 |
| Day 3 | 工单统计 | Stats | 数字准确性 + 语言 |
| Day 4 | 工单分析 + 告警码 | TT/Lookup | 单票分析 + 级别规则 |
| Day 5 | 边界与回归 | 全通道 | 极端情况 + 回归检查 |

---

## 📅 Day 1：路由与语言判定

### 目标
验证英文问题被正确路由到对应通道，且回复语言正确。

### 测试用例

```bash
# === 英文日期解析 ===
npm run ask -- "how many tickets today"
npm run ask -- "how many P1 tickets this week"
npm run ask -- "how many tickets yesterday"
npm run ask -- "how many tickets last month"

# === 英文问题路由 ===
npm run ask -- "what is a P1 ticket"
npm run ask -- "how many P1 tickets today"
# 上面两句只差 "many" + 日期，路由必须不同

# === 英文语言判定边界 ===
npm run ask -- "analyze TT202609110023？"   # 全角问号
npm run ask -- "analyze TT202609110023?"    # 半角问号
# 两种问号都应判为英文
```

### 验证标准

| 检查项 | 预期结果 |
|--------|----------|
| 日期解析 | 英文 "today/yesterday/this week/last month" 正确解析 |
| 路由正确 | "what is P1" → KB, "how many P1 today" → Stats |
| 回复语言 | 英文提问 → 英文回复（无中文残留） |

### 离线回归

```bash
node scripts/test-tools.mjs    # 验证路由规则
node scripts/test-lang.mjs     # 验证语言判定
```

---

## 📅 Day 2：知识库问答（RAG）

### 目标
验证英文问题能正确检索知识库并生成英文回复。

### 测试用例

```bash
# === 基础概念（知识库里有） ===
npm run ask -- "What is a Trouble Ticket"
npm run ask -- "What does P1 mean in NOC"
npm run ask -- "How does a TT get created"
npm run ask -- "What is alarm compression"

# === 英文版 SOP/规则 ===
npm run ask -- "What is the TT creation workflow"
npm run ask -- "How to assign a TT to FO"
npm run ask -- "What are the TT severity levels"

# === 操作手册（07_ 文件，通常排除）===
npm run ask -- "How to create a user group in eFlow"
npm run ask -- "How to configure an alarm rule"

# === 未命中测试（知识库没有） ===
npm run ask -- "What is the weather in Monrovia today"
npm run ask -- "Who won the football match yesterday"
```

### 验证标准

| 检查项 | 预期结果 |
|--------|----------|
| 命中回复 | 有依据的提问 → 有来源标注的回复 |
| 未命中回复 | 无依据的提问 → 英文 "not found" 文案 |
| 检索诊断 | `npm run ask -- --debug` 查看 top1/gap 值 |

### 离线校准

```bash
# 先看当前阈值是否适合英文语料
node scripts/calibrate.mjs \
  --label hit "What is a Trouble Ticket" \
  --label hit "How does alarm compression work" \
  --label miss "What is the weather today" \
  --label miss "Who is the president of Liberia"
```

---

## 📅 Day 3：工单统计（Stats）

### 目标
验证英文日期 + 级别 + 数量的统计查询正确返回数字。

### 测试用例

```bash
# === 基本统计（英文）===
npm run ask -- "how many tickets today"
npm run ask -- "how many P1 tickets today"
npm run ask -- "how many P2 tickets yesterday"
npm run ask -- "how many open tickets this week"

# === 带单号名单 ===
npm run ask -- "how many P1 tickets this month, give me the ticket IDs"
npm run ask -- "show me the P2 ticket IDs for this week"

# === 站点过滤（英文）===
npm run ask -- "how many tickets at Wood camp today"
npm run ask -- "how many P1 tickets in Montserrado"

# === 英文列表意图 ===
npm run ask -- "give me the ticket IDs"
npm run ask -- "show me the tickets"
npm run ask -- "which tickets are open"
```

### 验证标准

| 检查项 | 预期结果 |
|--------|----------|
| 数字准确性 | 回复中的数字来自脚本渲染，非模型编造 |
| 英文回复 | "P1: X tickets" / "Open: Y tickets" |
| 列表格式 | 要 ID 时显示单号列表 |
| 路由 | 统计类问题走 stats 通道（不是 KB） |

### 离线回归

```bash
node scripts/test-tools.mjs   # 验证 parseListIntent 等
```

---

## 📅 Day 4：工单分析与告警码

### 目标
验证单票分析 + 告警码查表的英文回复。

### 测试用例

```bash
# === TT 单分析（英文）===
npm run ask -- "analyze TT202609110023"
npm run ask -- "please check TT202609150073"
npm run ask -- "what is the status of TT202609110023"

# === WO 单（自动回溯到 TT）===
npm run ask -- "analyze WO202609220055"
npm run ask -- "check WO202609220056 please"

# === 告警码查表（Lookup 通道）===
npm run ask -- "what does alarm code 9991 mean"
npm run ask -- "what is alarm code 9990"
npm run ask -- "99933 alarm code"
npm run ask -- "CSD alarm is which level"
npm run ask -- "Fiber Break alarm code"

# === 告警压缩 ===
npm run ask -- "what will alarm code 198094422 be compressed to"
npm run ask -- "alarm compression for 9990"

# === 级别规则 ===
npm run ask -- "what level is a 3G CELL DOWN alarm"
npm run ask -- "P1 rules in TT system"
npm run ask -- "alarm code 9990 NORMAL non-VIP level"
```

### 验证标准

| 检查项 | 预期结果 |
|--------|----------|
| TT 分析 | 完整报告（级别、站点、状态、链路） |
| WO 回溯 | WO 自动解析为父 TT |
| 告警码 | 英文解释 + 级别判定 |
| 英文渲染 | "Level: P4 (consistent with rules)" / "Site: XXX" |

### 离线回归

```bash
npm run tt -- TT202609110023                    # 单票分析
node scripts/test-tt-extract.mjs               # 单号抽取
node scripts/test-lookups.mjs                   # 查表功能
```

---

## 📅 Day 5：边界与回归

### 目标
测试极端情况 + 回归检查，确保无退化。

### 测试用例

```bash
# === 追问（历史上下文）===
# 先问一个统计问题
npm run ask -- "how many P1 tickets today"
# 再追问（依赖会话历史）
npm run ask -- "which site has the most"
# 再追问（无主语）
npm run ask -- "the unresolved one"
# 再追问（无日期）
npm run ask -- "show me the ticket ID"

# === 多单分析 ===
npm run ask -- "check TT202609140078, TT202609140077"
npm run ask -- "analyze these TT202609140078 TT202609140077"

# === 混合语言 ===
npm run ask -- "今天有几个P1，and how many today"
npm run ask -- "analyze TT202609110023，please"

# === 空提问边界 ===
npm run ask -- "ping"                          # 内置命令
npm run ask -- "help"                          # 帮助信息

# === 错误处理 ===
npm run ask -- "analyze TT202609999999"        # 不存在的单号
npm run ask -- "analyze TT123456"              # 格式正确但不存在
```

### 验证标准

| 检查项 | 预期结果 |
|--------|----------|
| 追问继承 | 日期/级别/站点从历史继承 |
| 多单分析 | 最多 3 单，超限提示 |
| 混合语言 | 含汉字判中文 |
| 错误处理 | 不存在单号 → 英文 not found 文案 |

### 全量回归

```bash
# 运行所有离线测试
npm test

# 黄金集评测（需索引）
npm run eval:kb:offline
```

---

## 📊 测试记录模板

```markdown
## Day X 测试记录

**日期**：2026-10-0X
**测试者**：<name>

### 通过的用例 ✓
- [ ] <用例> - <结果>
- [ ] ...

### 失败的用例 ✗
- [ ] <用例> - <期望> vs <实际>
- [ ] ...

### 问题记录
| # | 问题描述 | 严重性 | 通道 |
|---|----------|--------|------|
| 1 | ... | 高/中/低 | KB/TT/Stats |

### 备注
...
```

---

## 🚨 快速排查

| 问题 | 排查命令 |
|------|----------|
| 路由走错通道 | `npm run ask -- --debug <question>` → 看 channel |
| 检索未命中 | 看 top1/gap 值，低于阈值则调低 |
| 中文残留 | `node scripts/test-lang.mjs` |
| 单号抽取失败 | `node scripts/test-tt-extract.mjs` |
| 英文日期不认 | `node scripts/test-tools.mjs` |

---

## ✅ 完成标准

- [ ] 5 天测试全部完成
- [ ] 所有离线回归测试通过
- [ ] 英文回复无中文残留
- [ ] 各通道路由正确
- [ ] QA 日志分析：`npm run qa:miss` 为空或可解释
