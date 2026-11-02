# 项目边界（指针，2026-10-31）

> 本文件是指针，不复制各子系统手册的现状细节。
> 真相源：各子系统 `docs/manual/` 与 `README.md`；
> 历史档案 `Task/my_app/PROJECT_DOCS.md` 不写回现状（总纲第四节第 5 条）。

| 项目 / 目录 | 负责人 Agent | 独立程度 | 约束入口 |
|---|---|---|---|
| `Task/my_app/backend/` | MyApp Backend Agent | 高 | `Task/my_app/AGENTS.md` 三.1/1b/3/4、三.5、六 |
| `Task/my_app/frontend/` | MyApp Frontend Agent | 高，需接口契约 | 同上 + `16-new-page-guide.md` |
| `liberia-noc_soc-数据看板统一门户/` | Portal Agent（Phase 3） | 高 | 门户 `AGENTS.md`、`DESIGN.md`、`vite.config.ts:242-267` |
| `Task/MTN_Comsal/my_app/` | Comsal Agent（Phase 3） | 高 | 该目录 `README.md` |
| `Task/whatsapp-kb-bot/` | WhatsApp Bot Agent | 高 | `.env.example`、本表 §Bot 约束 |
| `Site_outage/`、`ticket_export_rpa/`、`Task/RAN/`、`Task/ORANGE/`、`Task/Monthly_Report/` | RPA Agent（Phase 3，按脚本拆） | 中至高 | 各任务目录 `README.md` |
| `Unified_Tools/` | Shared Tools Agent | 中 | 权威源（见 `architecture.md` 2026-10-31 ADR）；`Task/Unified_Tools/` 为历史副本，不得新增引用 |
| `openclaw_api_selector/` | API Selector Agent | 高 | 该目录 `README` |
| 全仓库架构/质量 | QA / Architect Agent | 只读优先 | 本方案 §5.6、本仓库门禁（check:i18n、tsc/lint、build、alembic、help 生成器） |

Bot 约束：只经 `docs/shared-contracts/myapp-whatsapp-bot.md` 契约调用 MyApp API；
`.env` 不入库；已跟踪的 `config.json` 只改键名与读取逻辑，不把敏感值写回；
`config.json.tmpdel_*`、`*.bak_*` 为过程产物，不入库（根 `.gitignore` 已覆盖）。

VMAX 禁区（全 Agent）：数仓 `zxvmax` 只许 SELECT/SHOW/DESC，
禁区规则见 `D:\01_RPA\AGENTS.md` 第四节第 8 条。
