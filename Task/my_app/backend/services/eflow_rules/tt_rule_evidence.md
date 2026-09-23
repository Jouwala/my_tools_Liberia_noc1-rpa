# tt_rule_evidence.py 说明

## 作用
给「TT 快速分析 → AI 分析结论（TT单分析技能）」提供**确定性**的规则命中证据：
命中了哪条规则、规则来自哪个文件、规则谁维护、工单当前谁在处理。

AI 文本是"推断"，本模块是"事实"——页面把两者并列展示，结论里的级别可以直接核对。

## 口径来源（**不产生第二套判定**）
| 内容 | 来源 |
| --- | --- |
| 命中规则 / 目标级别 / 逐条匹配详情 | `eflow_rules/tt_batch_severity.check_batch()`（内部复用 `eflow_rules_matcher`） |
| 规则明细（类型 / 工单类型 / 触发步骤 / 维护人 / 时间 / 条件原文） | `eflow_rules/eflow_TT_rules.xlsx` 的 `TT_Rules` 工作表 |
| 规则条数与最近一次「收集 + 匹配」时间 | `eflow_rules/eflow_tt_rules_check_latest.json` |
| **推单规则**（谁推单 / 推给谁 / 谁自动处理） | `eflow_rules/eflow_push_rules.xlsx` 的 `Push_Rules` 工作表（`eflow_Push_Rule_Collector` 落盘） |

与每天 04:20 的定时任务 `eflow_tt_rules_check`、以及 Email Reports →
`eFlow TT Rules Check` 页签里的矫正表**同源**，因此三处的「命中规则」逐字一致。

## 两类规则，别混
| | 级别规则 `ttLevelRule` | 推单规则 `ttPushOrderRule` |
| --- | --- | --- |
| 回答的问题 | 这单**该是什么级别** | 这单**会不会自动推 WO、推给谁、谁自动处理** |
| 规则文件 | `eflow_TT_rules.xlsx` | `eflow_push_rules.xlsx` |
| 生效步骤 | `ticketSeverity_autoCreateTT` | `FOAccept`（决定自动建 WO 的那一步，与 `tt_postmortem._analyze_dispatch_reason` 的 `target_step` 同口径） |
| 返回字段 | `evidence.matched` | `evidence.push_rules` |

## 对外接口
- `build_rule_evidence(tt_no, handler=None) -> dict`
  返回 `available / found / level_status / current_severity / expected_severity /
  matched{...} / push_rules{...} / rules_file{...} / handler{...}`；**任何异常都不抛出**，
  失败时 `available=false` + `error`（人读原因），由页面与 AI 提示自行降级。
- `build_push_rule_evidence(tt_no) -> dict`（2026-09-23 新增）
  返回 `available / error / rules_file / matched[] / matched_count /
  other_steps[] / other_steps_count / evaluated / undecidable / undecidable_rules / fields`。
  每条命中规则含 `rule_name / rule_type_text / trigger_step_text / push_path /
  auto_operator / target_handler / priority / condition / match_details`。
- `render_evidence_text(evidence, lang) -> str`
  渲染成给大模型的「本地规则引擎预判定」文本块（zh/en）；`available=false` 时返回空串。
- `render_local_conclusion(evidence, report=None, lang, reason='') -> str`（2026-09-23 新增）
  **程序化结论**：模型全档失败时用它兜底，输出 Markdown（工单字段表 → 判定结论 →
  规则来源与责任人（含**推单规则**六字段） → 处置建议 → 失败原因附注）。全部由本地数据推出，
  无模型参与；规则明细的完整版仍由页面「规则命中证据」块展示，这里只给摘要，避免重复。

## 推单规则的三个坑（2026-09-23 实测）
1. **两份表的 `条件` 列格式不同**，不能直接喂同一个解析器：
   级别规则是 `AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980' (string)`（连接词后**有 `|`**），
   推单规则由 `eflow_Push_Rule_Collector._fmt_rows` 生成，是 `AND eflow_...alarmCode in '…' (string)`（**没有 `|`**）。
   `parse_conditions` 会跳过不含 `|` 的片段 → 表现为「所有推单规则都不命中」。
   解法是 `_parse_push_conditions()` 先补分隔符再复用 `parse_conditions`（求值语义一字不改）。
2. **本地只有 5 个字段可评估**：`alarmCode / vipSite / siteSubType(assetType) / netWorkType / downSiteCount`
   （见 `eflow_rules_matcher.build_value_frame`）。引用 `alarmName`、`category`、
   `previousOperationStep`、`alarmDurationTime` 等的规则**本地判不了**，单独计入
   `undecidable` 并在界面注明 —— **不能算作「未命中」**（实测 `TT自动推单给BO-MW组` 就引用 `alarmName`）。
3. **`Confirm` 步骤的规则是兜底**：`TT_push_confirm_to_close`（ID 119，`netWorkType not in 'VMAX'`）
   几乎命中所有 TT，但它不决定是否推 WO。只有 `triggerStep=FOAccept` 的规则才是「推单决策」，
   其余放进 `other_steps` 单独展示，避免把兜底规则混进「责任人」。

## 字段展示口径（与 eFlow 规则页签一致）
| 展示 | 原始值 | 处理 |
| --- | --- | --- |
| `Rule Type: TT Push Order Rule` | `ttPushOrderRule` | 驼峰拆词 + 首段大写（`_camel_text`） |
| `Rule Trigger Step: FO Accept` | `FOAccept` | 同上 |
| `Push Order Path: FOAccept > FOProcess > FOProcess` | `FOAccept,2>FOProcess,8>FOProcess` | 去掉每段的 `,N` 步骤序号，`>` 两侧补空格 |
| `*Auto Operator: FE Robot (fe_robot)` | `动态项(JSON).autoOperator` | `名称 (账号)` |
| `Target Handler: ZTE_NOC_FO [ZTE_NOC_FO]` | `动态项(JSON).targetHandler` | `名称 [编码]`；分组 id 是 UUID 时编码用分组名（eFlow 页签即如此显示） |

## 调用方
- `backend/routers/eflow_qa.py::tt_ai` —— 先算证据，再连同证据问模型；
  结果挂在 `ai.rules`（结构化，含 `push_rules`）与 `ai.evidence`（下发的原文）。
  **模型失败时**（`ai.ok=false`）再调 `render_local_conclusion()`，挂在
  `ai.fallback_conclusion` 并置 `ai.fallback=true`；`ai.ok` 仍为 false、
  `ai.error` 保留真实原因，便于区分「模型给的」与「引擎给的」。
- 前端 `frontend/src/pages/EflowQa.tsx`：
  `TtRuleEvidence` 组件渲染 `ai.rules`（级别规则 + 推单规则两个子块）；
  `!ai.ok` 时先显示错误 Alert，再渲染 `ai.fallback_conclusion`（带「程序化判定」标签）与证据块。

## 注意
- 规则表按 mtime 缓存（规则每天刷新一次，Web 请求路径上不重复解析 xlsx）。
- 本地 `eflow_tt` 没有该工单（只有 eFlow 实时单）时 `found=false`，
  规则引擎无法判定 —— 此时仍会返回规则文件信息，AI 走原有纯文本判定路径，
  程序化结论则给出「本地无该单 + 人工核查」的结论。
- **两个口径别混**：规则引擎按 `eflow_tt` 列判定（`match_details` 里的就是实际取值），
  而技能 prompt 的部分字段（如 `downSiteCount`）取自告警行，两者可能不同值。
  程序化结论里已显式标注「以逐条匹配为准」。
- 下载地址复用 Email Reports 的白名单接口：
  `/api/email-reports/download/eflow_tt_rules_check/<文件名>`；
  新增文件名必须同步登记在 `backend/routers/email_reports.py` 的 `_SOURCES`
  与 `_EFLOW_FILE_SPECS`，否则能列出却下载不了。
