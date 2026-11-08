<!-- 填写说明：本模板是强制性的，缺字段等于未完成。符合 docs/git-workflow.md 第 3 节。 -->

## 影响面（只选一个，多选请拆 PR）
- [ ] my_app（Data Insight MVP 后端/前端）
- [ ] portal（数据看板统一门户）
- [ ] whatsapp（WhatsApp Bot）
- [ ] eflow（eFlow 工单）
- [ ] ipt（IPT 动环 / 电力）
- [ ] gis（GIS 地图）
- [ ] feedback（用户反馈/权限）
- [ ] governance（Git/CI/文档治理）

## 变更范围自查
- [ ] `git diff --stat master...HEAD` 文件数：______（>50 文件必须在此说明为何未拆）
- [ ] 本 PR 只含一个业务功能：是 / 否（否必须写明拆分计划）
- [ ] 提交信息带模块前缀（如 `feat(vmax): ...`）：是（禁止 `feat(workspace)` / 汇总提交）

## 测试证据（必填，无则视为未完成）
- [ ] `node scripts/agent-done-check.mjs` 输出：贴关键行（PASS / FAIL）
- [ ] 若改过前端/后端：`--full` 输出（含 build/pytest/tsc）
- [ ] CI：docs-consistency（my_app + 门户 6 道守卫）+ branch-hygiene 绿

## 文档与约定检查
- [ ] 改了源码：对应 `docs/manual/` / 门户 `README.md` 已同步（CI docs-consistency 会拦下）
- [ ] 新增页面/任务：App 菜单 + i18n(zh/en) + 功能指南 三处同步
- [ ] 没有敏感值进代码/文档/日志（见 AGENTS.md 第四节第 2 条）

## 回滚方式
- [ ] 是 Squash and merge（一功能一 PR，可独立 revert）：是

## 备注
