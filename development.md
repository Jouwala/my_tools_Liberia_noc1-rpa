# 07 development.md —— 开发方式、命令与回归清单

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> **本文是统一入口。** 各子系统的完整步骤在各自手册：
> - my_app：`Task\my_app\docs\manual\10-quickstart.md`（环境、依赖、启动停止、首次配置）、`12-configuration.md`
> - 门户：`liberia-noc_soc-数据看板统一门户\README.md`（本地运行、构建部署）

## 一、环境前置

| 项 | 要求 |
| --- | --- |
| Node.js | 18+（门户用 React 19 / Vite 6 / Tailwind v4） |
| Python | 3.12（my_app；虚拟环境在 `Task\my_app\.venv`） |
| 端口 | **7038**（my_app 后端）、**7090**（my_app 前端）、**9267**（门户 dev）——**已被占用，不可复用** |
| 网络 | 本地 dev 需能访问 `192.168.100.19`（生产 nginx / 后端） |

## 二、命令速查

### 统一门户（`liberia-noc_soc-数据看板统一门户\`）

```powershell
npm install
npm run dev        # http://localhost:9267   （预置脚本会先拉起 wa-service）
npm run build      # 产物输出 dist/
npm run lint       # = tsc --noEmit，类型检查（改完必跑）
npm run preview    # 预览构建产物
npm run clean      # 删除 dist / server.js
```

- 本地 dev 已配置 `/api` 代理到 `http://192.168.100.19`，任务调度部件可直连生产后端。
- 部署到子路径时需在 `vite.config.ts` 设 `base: '/portal/'` **后重新构建**，否则静态资源 404。

### my_app（`Task\my_app\`）

完整步骤以 `docs\manual\10-quickstart.md` 为准，要点：

```powershell
# 0) 前置：Python 3.12 + 虚拟环境（.venv 已存在；Lib/Scripts 已在 .gitignore）
# 1) 后端依赖：区间版装当前兼容最新；要复刻现网用 requirements.lock.txt 精确锁版
# 2) 配置：新建 backend\.env（参照 backend\.env.example 的最小可用集）
# 3) 建表：Alembic
# 4) 前端构建：产物目录必须是 _fe_dist，否则后端找不到静态文件
# 5) 启动：start.bat / start_ensure.bat / start_hidden.ps1（生产由看门狗守护）
```

- **前端产物目录必须是 `_fe_dist`**——这是 my_app 后端查找静态文件的既定路径，改了会白屏。
- 生成的帮助文档：改 `frontend\src\pages\helpContent.ts` 与 `helpTaskDocs.ts` 后跑
  `cd frontend && node scripts\generate-help-doc.mjs` 重新生成，**不要手改 `docs\manual\15-user-help*.md`**。

### 工作区根

```powershell
git status --porcelain     # 全域变更复查（本仓库为单体仓库）
git log --oneline -20      # 看最近在做什么
```

## 三、改代码前的纪律（每一条都有历史代价）

1. **先 `git status`。** 单体仓库，工作区常有大量在途变更，别把别人的改动卷进你的提交。
2. **看 `.gitignore`。** `db\`、`log\`、`TMP\`、`auth-data\`、`*.pid`、`portal-default.json`、`native_board_cache\` 都禁止入库。用完探针脚本放 `TMP\`。
3. **中文注释。** 全域一致。
4. **不写敏感值。** 口令、Token、授权码、账号一律不进文档与代码。
5. **门户改文案要改两处。** `src\i18n.tsx` 的 `zh` 与 `en` **两份字典都要加**，只加一份在英文界面会直接显示 key 本身。
6. **my_app 加功能页要改三处。** `App.tsx` 菜单数组 + `i18n.tsx` 中英 + `docs\manual\11-feature-guide.md`——**漏一处手册就和界面对不上**（`docs\manual\README.md` 维护约定第 1 条）。
7. **my_app 加定时任务要登记。** 写进 `backend\task_registry.py` 的 `TASK_SPECS`，否则不会执行；同时更新 `04-task-system.md` 分组表。
8. **别再造真相源。** 现状以各子系统 `docs/manual/` 与 `README.md` 为准，不要写回 `PROJECT_DOCS.md`（历史档案）。
9. **提交信息带影响面前缀**，沿用既有习惯：`feat(portal): ...`、`fix(assets): ...`、`chore: ...`。

## 四、回归清单

改完**按下表逐项验证**。打勾前请真的跑过，不要凭印象。

### A. 通用（任何改动）

- [ ] `git status --porcelain` 复查：没有运行时产物（db/log/pid/缓存）混入
- [ ] 没有提交任何敏感值（口令、Token、账号、IP 之外的内网主机名）
- [ ] 改动涉及的文档已同步（见第三节第 6/7/8 条）

### B. 门户（`liberia-noc_soc-数据看板统一门户\`）

- [ ] `npm run lint`（`tsc --noEmit`）通过
- [ ] `npm run build` 通过
- [ ] `npm run dev` 后刷新页面，改动**实际可见**
- [ ] **深色与浅色两套主题都看过**（只验一套等于漏测一半）
- [ ] **中英文都切过**，没有显示成 `key` 原文的文案
- [ ] 改动涉及接口时：确认请求走的是 `/uniplam/api/*` 而**不是** `/api/*`（否则 405）
- [ ] 改动涉及看板数据时：清掉 `localStorage` 的 `liberia_noc_dashboards_v3`，确认"恢复初始默认看板"后新数据出现
- [ ] 改动涉及 QC 面板时：数字仍居中、标题与副行仍左对齐；取不到数据显示 `—` 而非 `0`
- [ ] 响应式：窄屏下导航与网格不塌

### C. my_app（`Task\my_app\`）

- [ ] 后端能起来（`7038`），前端产物是 `_fe_dist`
- [ ] `tests\` 下的测试通过
- [ ] 前端类型检查 / 构建通过
- [ ] **五个关键进程都在**（看 `docs\manual\13-operations.md` 的巡检步骤）
- [ ] 新增/修改的定时任务已登记 `TASK_SPECS`，且能在任务列表里看到
- [ ] 涉及数据层的改动：**没有引入新的裸 `sqlite3.connect`**（会绕过统一数据访问层，静默坏图）
- [ ] 涉及图表的改动：图表**真的出图**，不是空白（图表数据源有已知的裸连接点）
- [ ] 涉及的库确认没读错（`eflow_tt` 双库、`db_ps_cs_cn` 真数据在远端——见 `architecture.md`）
- [ ] 改了帮助内容时：已重跑 `generate-help-doc.mjs`，站内帮助与 MD 同源

### D. 部署相关

- [ ] nginx 配置改动后 `nginx -t` 通过
- [ ] 子路径部署时 `vite.config.ts` 的 `base` 已同步并**重新构建**
- [ ] 日志轮转任务正常（`install_nginx_log_rotate_task.bat`、`rotate_nginx_logs.ps1`）
- [ ] 不在值班高峰期重启生产服务（7038/7090/9267）

## 五、常见开发陷阱

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| 门户 API 用 `/api` | 命中 my_app，POST 回 405 | 用 `PORTAL_API`（`/uniplam/api`） |
| 只加中文 i18n 键 | 英文界面显示 key 原文 | `zh` 与 `en` 两份都加 |
| my_app 前端产物目录改名 | 后端找不到静态文件，白屏 | 保持 `_fe_dist` |
| 改了初始看板数据就以为生效 | 被 localStorage 覆盖，看不到 | 清缓存 / 「恢复初始默认看板」 |
| 数字取不到时显示 0 | 运维误判为"已清空" | 显示 `—` |
| 用 interval 累加做定时刷新 | 进页面时机不对要等一整个周期 | 用墙上时钟对齐网格（见 `architecture.md` 流 2） |
| 探针脚本写在仓库根 | 误入库（已有 98 个的历史教训） | 放 `TMP\` |
| 把 db/log 加进版本库 | 956M / 152M 进 git | 已被 `.gitignore` 忽略，别绕开 |

## 六、相关文档

| 内容 | 去哪里 |
| --- | --- |
| my_app 快速上手 | `Task\my_app\docs\manual\10-quickstart.md` |
| my_app 配置项 | `Task\my_app\docs\manual\12-configuration.md` |
| my_app 运维与排障 | `Task\my_app\docs\manual\13-operations.md` |
| my_app 代码清理 | `Task\my_app\docs\CODE_CLEANUP_GUIDE.md` |
| 导出规范 | `Task\my_app\docs\EXCEL_EXPORT_STANDARD.md` |
| 门户构建部署 | `liberia-noc_soc-数据看板统一门户\README.md` |
| 鉴权开关 | `AUTH_SWITCH.md` |
| 架构与数据流 | `architecture.md` |
| 视觉规则 | `DESIGN.md` |

> **工具负责整理，人与 AI 负责协作执行。**
