# MyApp ↔ Portal 共享接口契约（稳定部分，2026-10-31）

> 只记录稳定契约，不记录实现细节。实现变更不触发本文件更新；
> 契约变更由 Human / Architect 评审后更新。

- API Base：门户经 nginx `/api/` → my_app 7038；门户自身 API 必须带 `/uniplam/api` 前缀，
  不得写绝对路径 `/api/...`（否则命中通用 `location /api/` 被回 405，
  见 `architecture.md` 一、`/uniplam/api 与 /api 必须分清`）。
- 主机单一真相源：`liberia-noc_soc-数据看板统一门户/src/config.ts`，
  换机房只改这一处。
- 看板聚合：门户不复制业务数据，只存相对路径 `rel`，运行时「主机 + rel」拼完整 URL；
  已持久化到 `localStorage` 的旧数据自动跟随主机变更。
- 任务状态轮询：门户每 60 秒拉 `${PORTAL_API}/api/...`（如 `/api/tasks`），
  离线降级为静态快照，不白屏。
- QC 两档刷新：全量每小时 `:06:30`（跟 `eflow_sync` 跑完），告警每 5 分钟
  `:00:30`/`:05:30`…（跟 `eflow_active_alarm` 同步），墙钟对齐。
- 部署路径：`Task/_fe_dist/` 为线上服务目录（nginx 直接读），
  Worktree 内禁做覆盖式 `npm run build`。
