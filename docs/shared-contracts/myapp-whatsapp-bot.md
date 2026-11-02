# MyApp ↔ WhatsApp Bot 共享接口契约（稳定部分，2026-10-31）

> Bot 不得直接读取或修改 MyApp 内部业务实现；只经本契约与测试样例联调。

- Bot 可调用的业务 API：以 my_app `/api/*` 已发布端点为准，字段以契约为准，
  Frontend/Backend 变更字段时同步更新 `.agent-work/contracts/` 并通知对方。
- 认证：Bot 持有的凭据走环境变量 / 本地 secrets，`.env` 不入库；
  `config.json` 中 `chatApiKey` 为空、`chatApiKeyEnv` 为键名引用（2026-10-31 实测），
  保持「键名入库、键值不入库」。
- 超时与重试：业务 API 调用必须设超时，失败走固定评测集验证；
  P1 告警主通道（Baileys）失败时走 ext 通道 fallback（见 `architecture.md` 2026-10-08 ADR），
  不得再叠第三层自动化。
- 审计：工具调用记录调用链（Intent / 工具 / 参数 / 结果），敏感信息脱敏后落盘。
- 评测：`Task/whatsapp-kb-bot/evals/` 固定评测集为改 RAG/工具路由后的必跑门禁。
- 生产边界：真实 WhatsApp 账号操作、生产凭据变更、生产部署由负责人审批。
