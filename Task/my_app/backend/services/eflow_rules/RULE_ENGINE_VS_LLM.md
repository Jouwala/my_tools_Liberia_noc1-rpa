# eFlow 告警处理：程序化规则匹配 vs LLM 选型

> 基准日期：2026-10-09　|　范围：`backend/services/eflow_rules/` 子系统
> 维护：my_app 后端组
> 出处：本文件讨论的「程序化匹配」对应 `eflow_rules_matcher.py`（生产定时任务 `eflow_tt_rules_check` 与 `tt_batch_severity` 同源），「LLM 路径」对应 `backend/services/eflow_qa.py::tt_ai`（OpenWebUI / WorkBuddy 转发）。

## 一、为什么写这份选型

2026-10-09 现场对告警 2114322696 复盘时，团队内部出现两个并存方案：

- **方案 A（程序化）**：把 eFlow 配置中心的 15+ 条 `ttLevelRule` 全部解析成结构化条件，再用 pandas 向量化匹配。`MATCHING_REPORT.md` 显示 1000 条样本全部命中，0 条误判。
- **方案 B（LLM）**：把工单 + 告警 + 规则文本一股脑塞进 prompt，让大模型自己判「这条该什么级别」。

**结论是 A 是必选、B 是辅助**。本文件记录三条具体理由与现场实测数据，避免后续有人再花时间重做一遍对比。

## 二、为什么程序化匹配必须作为主路径

### 2.1 准确率不是 95% vs 99% 的差距，是 100% vs 不可控的差距

eFlow 规则引擎在生产环境已稳定运行多年，它的目标级别是**业务契约**。`MATCHING_REPORT.md` 的 v2 修正版数据：

| 指标 | 程序化（matcher v2）| LLM 自由问答（实测）|
| --- | --- | --- |
| 命中率 | 1000 / 1000（100%） | 取决于 prompt 长度，通常 90%~95% |
| 误判率 | 0（与 eFlow 配置中心逐字一致） | 常见错误：把 P2 推成 P1、把告警码 9995 漏掉 `downSiteCount` 分流条件 |
| 决策可解释 | 每条逐条 `Match_Details`（field=value 符号 期望 ✓/✗）| 模型无法逐条解释，只能"看起来对" |
| 漂移风险 | 0：规则刷新 = 重新拉 `eflow_TT_rules.xlsx` 再跑一次 | 同一 prompt 两次回答可能不一致 |

LLM 的 5% 误差在告警场景会被放大成**误升级 / 漏升级**，直接影响夜班值班对 P1 的响应节奏。

### 2.2 程序化匹配是 LLM 的"前置事实"，不是它的对手

LLM 在 eFlow 场景真正擅长的是**自然语言解释**而不是"判级别"。所以生产路径是：

```
1. 程序化匹配（eflow_rules_matcher）→ 命中规则、目标级别、逐条 match_details
2. 把上面事实 + 工单上下文 + 历史变更一起塞进 LLM
3. LLM 只负责"用人话解释为什么这个级别、要不要升级、什么时候回滚"
```

`tt_rule_evidence.py` 正是这条路径的载体：它先跑 `eflow_rules_matcher` 拿到结构化结论，再把它当作 prompt 的**事实锚点**喂给模型。模型即便编故事，结论里的"命中规则 225 P1" 仍能反向核对。

`backend/routers/eflow_qa.py::tt_ai` 在模型失败时调用 `render_local_conclusion()` 兜底，输出纯本地数据推出的结论（命中规则 + 维护人 + 处置建议），**没有模型参与**。这条兜底路径的存在本身就说明：业务上不能依赖模型。

### 2.3 现场成本对比

| 维度 | 程序化 | LLM |
| --- | --- | --- |
| 单条耗时 | ~0.02 秒（1000 条 × pandas 向量化 ~20 秒）| 单条约 1~3 秒（外网 + WorkBuddy 代理 + 上下文） |
| 依赖 | pandas / openpyxl（项目已有）| OpenWebUI 或 WorkBuddy 代理可达 + 模型未限流 |
| 失败模式 | xlsx 没拉到 → 降级使用上次缓存 | 网络抖动 / 模型超时 / token 超限 → 整条结论降级 |
| 回滚 | 切回 SQLite 模式 / 关闭 worker 即可 | 改 prompt 不易定位"哪次改坏" |

`backend/services/eflow_qa.py` 与 `tt_alarm_whatsapp_alert` 任务都明确**"模型失败时降级到本地结论"**，这是工程上"程序化为底、模型为表"的标准做法。

## 三、什么场景值得引入 LLM

明确边界，避免滥用：

1. **自然语言解释**："这条 9995 告警为什么是 P1 而不是 P2？业务上影响什么？" → 适合 LLM，理由是结构化字段不能直接转成可读解释。
2. **历史相似工单召回**："过去 30 天同类 9995 站点都怎么处理的？" → 适合 LLM（embedding + RAG），但**结论仍要回到程序化级别判定**。
3. **多源摘要**："这条 TT 在 UME / eFlow / CCN 三处的状态分别是什么？" → 适合 LLM（跨数据源自然语言合并）。
4. **变更分析**："近一周告警级别有没有被自动改过、改成什么？" → 程序化（`audit_rule_coverage.py`）即可，LLM 没必要。

**反例（不要让 LLM 干这些事）**：

- 判级别 → 走 matcher
- 判告警码 → 走 matcher
- 判走哪个规则 → 走 matcher
- 写兜底结论 → 走 `render_local_conclusion`

## 四、三条已落地的工程事实（写代码时会被反复引用）

1. **生产定时任务 `eflow_tt_rules_check`**（`backend/task_registry.py:278`，每天 04:20）已经走 `eflow_rules_matcher.run()`。**改 matcher 等于改所有页签、Email Reports、批量核查、AI 提示锚点**。
2. **`tt_rule_evidence.py` 是 AI 路径的事实锚点**：所有 prompt 必须以 `evidence.matched` 为准，模型不得编造命中规则。
3. **Lark / AI 模型降级路径已写好**（`eflow_qa.py::tt_ai` 的 `ai.ok=false` 走 `render_local_conclusion`），现场不会因为模型挂掉而丢结论。

## 五、决策与回退条件

**当前决策**（2026-10-09 立）：

- 告警级别判定 = **程序化为唯一权威**，LLM 仅承担自然语言解释层。
- 新增任何"AI 判级"功能前，必须先在 `audit_rule_coverage.py` 里证明该告警码在程序化路径下无规则覆盖。

**回退条件**：若出现以下任一情况，**立即**回退到全程序化并停止 LLM 路径：

- 程序化匹配误判率（人工抽样核对）连续两周 > 1%。
- 任何 LLM"判级"结果被现场采纳后又被人工推翻 ≥ 3 次/月。
- 告警链路关键页面（`/api/eflow-qa/tt-ai` 等）P95 延迟 > 5 秒。

## 六、相关文件

| 文件 | 作用 |
| --- | --- |
| `eflow_rules_matcher.py` | 程序化匹配主实现（每天 04:20 跑，零外部依赖） |
| `tt_batch_severity.py` | 批量核查接口，Web 路径 |
| `tt_rule_evidence.py` | AI 路径事实锚点（`backend/routers/eflow_qa.py::tt_ai` 用） |
| `audit_rule_coverage.py` | 规则缺口体检（事前设计阶段用） |
| `eflow_tt_rules_check_task.py` | 定时任务入口 |
| `MATCHING_REPORT.md` | 匹配分析报告（每天 04:20 重写） |
| `LLM_TEST_REPORT.md` | 本地 3 个对话模型对告警 2114322696 的实测（时延 + 准确性，证明模型不可用于判级） |
| `backend/routers/eflow_qa.py::tt_ai` | AI 路径入口（兜底逻辑在这里） |
| `docs/manual/05-security-and-credentials.md` | 凭据与敏感值规范（任何 AI 调用都不能写值） |

> **结论一句话**：程序化匹配是这道题的正确答案，LLM 是写在答案旁边的人话翻译。
