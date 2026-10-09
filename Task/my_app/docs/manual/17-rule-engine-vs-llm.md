# 17 规则匹配与 AI 选型

> 基准日期：2026-10-09　|　范围：eFlow 告警/工单处理链路
> 配套文档：[`backend/services/eflow_rules/RULE_ENGINE_VS_LLM.md`](../services/eflow_rules/RULE_ENGINE_VS_LLM.md)（本手册是它的精简版 + 选型依据）

## 17.1 选型结论（一句话）

**eFlow 告警的级别判定走程序化规则匹配，AI 仅承担"自然语言解释"**。任何"让 AI 判告警级别"的提案在动手前必须先在 `audit_rule_coverage.py` 里证明该告警码无程序化规则覆盖。

## 17.2 为什么这么选

### 17.2.1 程序化匹配是"事实"，不是"对手"

`backend/services/eflow_rules/eflow_rules_matcher.py` 把 eFlow 配置中心的 15+ 条 `ttLevelRule` 全部解析成结构化条件，再 pandas 向量化匹配。生产定时任务 `eflow_tt_rules_check`（`backend/task_registry.py:278`，每天 04:20）已经在跑，零外部依赖，0 误判。

这条路径被三处生产代码 import：

| 位置 | 用途 |
| --- | --- |
| `backend/services/eflow_rules/tt_batch_severity.py:21` | Web 批量核查接口 `/api/eflow-qa/batch-check` |
| `backend/services/eflow_rules/tt_rule_evidence.py` | AI 路径的事实锚点 |
| `backend/services/eflow_rules/eflow_tt_rules_check_task.py:104` | 每天 04:20 定时任务 |

**改 matcher 等于改所有页签、Email Reports、批量核查、AI 提示锚点**。它不是"可选优化"，是基础设施。

### 17.2.2 AI 路径是把结构化结论"翻译成人话"

`backend/routers/eflow_qa.py::tt_ai` 是 LLM 入口。它先调 `tt_rule_evidence.build_rule_evidence()` 拿到**程序化匹配的事实**（命中规则 ID、目标级别、逐条 `match_details`），再把"事实 + 工单上下文"一起发给模型，让模型写"为什么这个级别、什么时候回滚"。

`ai.ok=false`（模型失败）时回退到 `tt_rule_evidence.render_local_conclusion()`，输出纯本地数据推出的 Markdown 结论。**业务上不依赖模型就能出结论** —— 这是这条路径"程序化为底、模型为表"的标准写法。

### 17.2.3 现场数据对比

数据来源：[`MATCHING_REPORT.md`](../services/eflow_rules/MATCHING_REPORT.md)（2026-10-09 04:20 跑出）

| 维度 | 程序化（matcher v2）| LLM 自由问答（实测）|
| --- | --- | --- |
| 1000 条样本命中率 | 1000 / 1000 | 通常 90~95% |
| 误判率 | 0（与 eFlow 配置中心逐字一致）| 5% 会被人工推翻 |
| 单条耗时 | ~0.02 秒 | 1~3 秒 |
| 决策可解释 | 逐条 `Match_Details` | 模型无法逐条解释 |
| 失败降级 | 切 SQLite / 关闭 worker | prompt 改坏不易回退 |

5% 误判在告警场景会被放大成**误升级 / 漏升级**，直接影响夜班对 P1 的响应节奏。

## 17.3 哪些事适合 AI

边界已经划定，避免新功能走偏：

| 适合 | 理由 |
| --- | --- |
| 自然语言解释（"为什么是 P1"）| 结构化字段不能直接转人话 |
| 历史相似工单召回（embedding + RAG）| 但**结论仍要回到程序化判定** |
| 多源摘要（UME / eFlow / CCN 三处状态合并）| 跨数据源自然语言合并 |
| 变更分析 | 走 `audit_rule_coverage.py`，LLM 没必要 |

**反例（不要让 AI 干这些事）**：

- 判告警级别 → 走 `eflow_rules_matcher`
- 判告警码 → 走 `eflow_rules_matcher`
- 判走哪条规则 → 走 `eflow_rules_matcher`
- 写兜底结论 → 走 `render_local_conclusion`

## 17.4 相关代码

| 文件 | 作用 | 行号 |
| --- | --- | --- |
| `backend/services/eflow_rules/eflow_rules_matcher.py` | 程序化匹配主实现 | — |
| `backend/services/eflow_rules/tt_batch_severity.py` | 批量核查 Web 接口 | `:21` |
| `backend/services/eflow_rules/tt_rule_evidence.py` | AI 路径事实锚点 + 兜底结论 | — |
| `backend/services/eflow_rules/audit_rule_coverage.py` | 规则缺口体检（事前设计阶段用） | — |
| `backend/services/eflow_rules/eflow_tt_rules_check_task.py` | 每天 04:20 定时任务 | `:104` |
| `backend/routers/eflow_qa.py::tt_ai` | AI 路径入口（兜底逻辑在这里） | — |
| `backend/task_registry.py` | `eflow_tt_rules_check` 任务登记 | `:278` |
| `docs/manual/14-integrations.md` | eFlow 集成概览 | — |

## 17.5 回退条件

若出现以下任一情况，**立即**回退到全程序化并停止 LLM 路径：

- 程序化匹配误判率（人工抽样核对）连续两周 > 1%。
- 任何 LLM"判级"结果被现场采纳后又被人工推翻 ≥ 3 次/月。
- 告警链路关键页面（`/api/eflow-qa/tt-ai` 等）P95 延迟 > 5 秒。

## 17.6 决策日志

| 日期 | 决策 | 出处 |
| --- | --- | --- |
| 2026-10-09 | 告警级别判定 = 程序化为唯一权威，AI 仅承担自然语言解释层 | 告警 2114322696 复盘（`MATCHING_REPORT.md` v2） |

> **结论一句话**：程序化匹配是这道题的正确答案，LLM 是写在答案旁边的人话翻译。
