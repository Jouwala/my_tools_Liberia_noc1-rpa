# openwebui_client.py 说明

## 作用
给 TT 工单做「TT单分析」，被 `/api/eflow-qa/tt-ai` 端点使用。
模型走两档：**主用 = 本地 WorkBuddy 代理（codebuddy_proxy，OpenAI 兼容）**，
**备用 = Open WebUI**（http://192.168.100.27:3000 的 `TT_PROVITY` 技能 + agnes 系列模型）。
主用档不依赖内网，Open WebUI 停机/断网时 TT 分析照常出结论。

## 依赖
- Python 标准库 urllib（无第三方 HTTP 依赖）
- openpyxl：读本地 `eflow_TT_rules.xlsx`（TT_Rules 工作表，状态=ACTIVE 的规则）
- python-dotenv：读 `backend/.env`
- 主用档需要一个在跑的本地代理，默认监听 `127.0.0.1:8788`
  （启动方法见 `~/.codex/start-workbuddy-chain.ps1`）

安装：`pip install -r requirements_openwebui_client.txt`

## 配置（backend/.env）
| 变量 | 说明 | 默认 |
| --- | --- | --- |
| WORKBUDDY_ENABLED | 1/0，是否把本地代理作为主用档 | 1 |
| WORKBUDDY_BASE_URL | 本地代理根地址（OpenAI 兼容，自带 `/v1`） | http://127.0.0.1:8788/v1 |
| WORKBUDDY_MODEL | 主用模型 ID | deepseek-v4.1-flash |
| OPENWEBUI_BASE_URL | Open WebUI 地址 | http://192.168.100.27:3000 |
| OPENWEBUI_EMAIL | 登录邮箱 | 无（备用档必填） |
| OPENWEBUI_PASSWORD | 登录密码 | 无（备用档必填） |
| OPENWEBUI_MODEL | 备用模型：固定 ID，或 `auto` / `auto:<pattern>` 自动选最新 flash | agnes-2.5-flash |
| OPENWEBUI_META_TIMEOUT | 登录/取技能/取模型列表的超时秒数（短超时，避免卡住页面） | 8 |
| EFLOW_TT_RULES_XLSX | 规则表路径 | backend/services/eflow_rules/eflow_TT_rules.xlsx |

换主用模型只改 `WORKBUDDY_MODEL`（改完要重启后端）；`WORKBUDDY_ENABLED=0` 可整体退回纯 Open WebUI。

## 关键实现
- 调用链：`[workbuddy:WORKBUDDY_MODEL] + [openwebui:<备用候选>]`，逐档尝试；
  连接失败、404/模型下线、上游 5xx、响应结构异常都会换下一档，全部失败才报错
- 对话：两边都是 `stream=false` 的 chat/completions，system 消息恒为首条
  （WorkBuddy 网关要求首条必须是 system，否则 `code 11128` → HTTP 400）
- 登录：POST /api/v1/auths/signin，JWT 缓存 60 分钟，对话遇 401 自动重登重试一次；
  **登录失败不再让整条链路失败**，只降级为「无 token + 本地技能缓存 + 仅主用档」
- 登录 400「trusted header」（2026-10-19 实测，Open WebUI 0.12.0）：服务端
  `GET /api/config` 返回 `features.auth_trusted_header=true`、`enable_signup=false`，
  即已切换为 trusted-header 单点登录，**邮箱密码登录被服务端禁用**，改密码无用。
  头名猜测已排除：响应头 `server: uvicorn`（应用自己拒绝，不是反代拦截），带**真实账密 body**
  依次试 `X-User-Email / X-Forwarded-Email / X-Auth-Request-Email / X-Auth-Email / X-Email /
  Remote-Email / X-WEBAUTH-USER / X-Authenticated-User / X-SSO-Email / X-Remote-Email / Email`
  再加三组 email+name 双头组合，**全部同一个 400** —— 启用 SSO 后这条路由就是关死的，别再试头名。
  `signin()` 已把这条 400 翻译成可执行建议（保留服务端原文），见 `_TRUSTED_HEADER_HINT`。
  让 AI 重新可用**不需要改代码**，两选一：
  ① 「系统设置 → AI 模型」主用模型方选 `both` 或 `local`，走 WorkBuddy 本地代理
  （实测 127.0.0.1:8788 在线，一次对话约 2 秒；模型列表 claude-3.7 / claude-4.0 / gpt-5 /
  gemini-2.5-flash / auto-chat …，`deepseek-v4.1-flash` 不在列表里但代理照收）；
  ② 该页选 `custom`，Base URL 填 `http://<openwebui>/api/v1`、API Key 填 Open WebUI
  用户设置里签发的 API Key、Model 填模型 id —— 实测 `POST /api/v1/chat/completions`
  路由存在且按 Bearer 校验（无 token 401 Not authenticated，假 token 401 token is invalid），
  与 `chat(provider="custom")` 的拼法正好对上。
  注意 `provider=openwebui` 时候选链里**没有本地档**，单点失败即整条失败；这条 400 也**不触发**
  `_mark_owu_down()` 的 120 秒短路（只认 `UnreachableError`），所以别把它当「服务挂了」查网络
- 短路：Open WebUI 连接超时/拒绝后 120 秒内不再尝试登录、取模型列表和备用档对话，
  否则内网断开时每个请求都要重复付两次 TCP 超时
- 技能：GET /api/v1/prompts/list 按 command=TT_PROVITY 取内容作 system 提示，
  每次成功都落盘 `backend/services/eflow_rules/tt_proivity_skill.json`；
  拿不到用缓存（`skill_source=cache`），缓存也没有用内置提示词（`skill_source=builtin`）
- 规则：外部模型不走 Open WebUI 知识库 RAG，必须把 ACTIVE 规则文本内嵌进 system 消息；
  条件里的 eflow_ticket_ticket_xxx. 前缀会被剥离，映射到技能入参字段名（vipSite/alarmCode/...）
- 规则命中证据（2026-09-23 新增）：`analyze_tt(..., evidence_text=...)` 可把**本地规则引擎**
  算出的「命中规则 / 规则来源文件 / 规则维护人 / 工单处理人」预判定块随 user 消息下发，
  要求模型以此为准并写明规则名称与规则文件；留空则行为与旧版完全一致。
  文本由 `backend/services/eflow_rules/tt_rule_evidence.py` 的 `render_evidence_text()` 生成，
  判定口径与定时任务 eflow_tt_rules_check 同源（见 `eflow_rules/tt_rule_evidence.md`）
- 英文输出：`lang=en` 时若结论仍含成段中文，用刚验证可用的同一档模型再翻译一次
  （`language_rewritten=true`）

## 自测
```bash
python -X utf8 -m backend.services.openwebui_client
```
返回 JSON 并打印总运行秒数：
`{ok, conclusion, provider, model, model_policy, failover_tried, skill_title, skill_source, language, language_rewritten, elapsed_sec}`

页面侧：2026-10-19 起「TT 快速分析」只调 `GET /api/eflow-qa/tt-ai-fast`（纯本地规则引擎，
不调模型），本文件描述的 `GET /api/eflow-qa/tt-ai` **界面已不依赖**，只用于排障与
「系统设置 → AI 模型」连通性测试（后端 :7038，改配置或代码后需重启生效）。
`ai.provider` / `ai.model` 用来确认这次实际走的是主用还是备用档。
`ai.rules` 是本地规则引擎的命中证据（结构化，页面「命中规则」明细块直接用，含
`push_rules` 推单规则），`ai.evidence` 是下发给模型的证据原文（排查用）。
**所有候选档都失败时**（`ai.ok=false`）端点不会只回错误：`eflow_qa.tt_ai` 会用
`tt_rule_evidence.render_local_conclusion()` 程序化生成 `ai.fallback_conclusion`
（`ai.fallback=true`），页面照常出结论；`ai.ok` 仍为 false、`ai.error` 保留真实原因。
