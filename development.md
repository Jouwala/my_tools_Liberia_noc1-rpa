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

**版本库整洁自检**（`AGENTS.md` 第四节第 4/7 条的落地命令，2026-09-24 加）：

```powershell
# ① 本次改动里有没有夹带探针/产物（?? 行应当全是要提交的真文件）
git status --porcelain | Select-String '^\?\?'
# ② 某个文件为什么没被跟踪（会打印命中的规则与 .gitignore 行号）
git check-ignore -v Task\_fe_dist\assets\index-xxxx.js
# ③ 有没有「已被跟踪、但按规则本该忽略」的漂移（输出非空就要处理）
git ls-files -i -c --exclude-standard
# ④ 门户专用：改忽略规则时，.gitignore 与 vite.config.ts 的 server.watch.ignored
#    是同一套判断的两个副本，必须一起改
# ⑤ 快照有没有混进库（应输出空；规则见根 .gitignore 的「备份文件 / 手工快照」段）
git ls-files -- ':(glob)**/*_bak_*' ':(glob)**/*.bak' ':(glob)**/*.bak.*' ':(glob)**/*.bak_*' ':(glob)**/*.bak-*'
#    ⚠️ 陷阱：git check-ignore 对**已被跟踪**的文件一律返回「未忽略」(exit 1)，
#    因为忽略规则本来就不作用于已入库的文件。所以「规则到底写对没有」必须这样问，
#    否则会把写对的规则误判成写错（2026-09-25 实测踩到）：
git check-ignore -v --no-index -- Task\my_app\backend\main.py_bak_20260913_authswitch
# ⑥ 磁盘侧的探针残留（**git 完全看不见它们** —— 规则已生效，所以 ①③⑤ 都是空的，
#    但 `dir` 照样一屏乱码。只能直接数文件）：
Get-ChildItem -LiteralPath 'liberia-noc_soc-数据看板统一门户' -Recurse -File |
  Where-Object { $_.Name -match '^_|^\.?tmp_|^temp_|^seg\d.*\.txt$|^(listing|out)\.txt$' } |
  Where-Object { $_.FullName -notmatch '\\(node_modules|dist|TMP|\.git)\\' -and
                 $_.FullName -notmatch '\\(src|server)\\' } | Measure-Object
#    2026-09-25 归档后基线 = **0**（220 个已整体挪到 `_quarantine_20260925\portal_probes\`，
#    逐文件明细见该目录下 `_MANIFEST.tsv`）。非 0 就是本次会话又落了新探针，按第四节第 7 条清掉。
#    ⚠️ 上面这段粘进交互控制台可以直接跑；**存成 .ps1 就不行** —— 路径里有中文，
#    本机 PowerShell 5.1 把无 BOM 的 UTF-8 脚本按 ANSI 读，中文路径会碎成乱码并报
#    Cannot find path（2026-09-25 实测）。存脚本时先 ASCII 通配定位目录：
#      Get-ChildItem -LiteralPath 'D:\01_RPA' -Directory | ? { $_.Name -like 'liberia-noc_soc*' }
```

可复用的诊断脚本（**不删**，按第四节第 7 条记录用途；都在 `TMP\` 下，不入库）：

| 脚本 | 用途 |
| --- | --- |
| `Task\my_app\TMP\_audit_fe_dist.mjs` | 只读审计前端构建产物：从 HTML 入口做传递可达性，算出「在用的 chunk」与「历次构建遗留的不可达 chunk」，按 mtime 月龄分桶。判据经交叉验证：最新一次构建产出的文件数与可达集大小一致。**不写不删不移**。用法：`node Task\my_app\TMP\_audit_fe_dist.mjs [别的dist路径]` |
| `TMP\_mk_untrack_list.mjs` | 从「已跟踪但被忽略规则命中」的集合里按**白名单**挑出可安全脱离跟踪的文件，硬排除真源码（`Task\data_base\`、门户 `src\data\` 会被历史规则 `data_base/`、`*/data/` 误命中）。输出 NUL 清单 `TMP\_tountrack.nul` 供 `git rm --cached --pathspec-file-nul` 使用 |
| 门户 `TMP\_plan_snapshot_archive.mjs` | **手工快照配额执行器**（`AGENTS.md` 第四节第 7 条「同母本只留最近 3 份」的机器版）。按 `bak` 命名变体收磁盘快照，用**文件名里的日期**（不是 mtime，它会被复制/移动改写）归组排序，超出 3 份的用同盘 `rename` 挪进隔离区。默认 dry-run，`--apply` 才动；动之前逐条比对 `git ls-files` 并报出**仍被跟踪**的那几个（必须先 `git rm --cached`，否则冒出工作区删除），并把「`bak` 前无分隔符」的不规则命名（如 `portal.js.qcbak`）单独告警而不是静默放行。**不碰 `src\`、`server\`、`TMP\`、`node_modules\`、`dist\`** |
| 门户 `TMP\v1_render_test.cjs` | `/v1/olbrportal/` 的**渲染回归**：用 DOM 桩跑真实 `olbr.js`，断言两排卡片数（QC 6 张 / CXO 6 张 = 3 富 + 3 可用率）、富卡片结构、走势点数、可用率页脚三格、`is-nospark` 2/4 拆分、`>视频流量<` 不得回归、以及**不再请求** `/api/vmax-cxo-daily/grid`。夹具 `TMP\{alarm_overview,catalog,olib_overview}.json`。结果写 `TMP\v1_out.txt`，失败 exit 1。用法：`node TMP\v1_render_test.cjs` |
| 门户 `TMP\v1_interact_test.cjs` | `/v1/olbrportal/` 的**交互回归**：KPI 重试按钮、六个视图卡展开、Escalation Matrix 展开与取消选中。结果写 `TMP\v1_interact_out.txt`，失败 exit 1 |
| 门户 `TMP\probe_rich_cards.py` | 浏览器实测：把 CXO 富卡片渲染出的大数字/徽章/极值**逐个与 `/api/olib-soc-dashboard/overview` 的返回核对**，并记录亮暗两主题的列数与卡片宽度。写 `TMP\_rich_cards.json`。需要 Playwright（`Python312`） |
| 门户 `TMP\probe_shot.py` | 给任意区块截图（亮/暗各一张）做人工目视比对。用法：`python TMP\probe_shot.py [选择器] [文件名前缀] [--click s1,s2] [--lang zh\|en]`，默认 `#kpi` → `TMP\_shot_<theme>.png`。例：`python TMP\probe_shot.py "#band" _band`；截登录闸门要先点开：`python TMP\probe_shot.py "#gate" _gate --click "#umBtn,#gmreq"`。脚本会先清掉门户 token，否则已登录状态下截不到闸门 |
| 门户 `TMP\v1_auth_test.py` | `/v1/olbrportal/` 的**鉴权链路回归**：入口可达（`local` 占位身份下 `#umBtn` 必须可见）→ 点击唤起闸门 → 取消退回 → 登录/注册两态切换 → 本地校验（不足 8 位 / 两次不一致，且**不得发请求**）→ 注册成功（校验 `{username,password,note}` 载荷与 `ar.ok` 文案）→ 四种错误码文案映射（`username_taken`/`request_pending`/`too_many_requests`/断网）→ 登录成功（token 落共享键、闸门收起、用户管理面板自动打开）。结果写 `TMP\_auth_out.json`，失败 exit 1。**关键：全程用 Playwright 路由拦截替掉后端** —— 真发一次注册申请会往 `auth-data\portal-auth.db` 写一行真实待审批记录，只有管理员能删，所以这个测试刻意不碰真库。用法：`python TMP\v1_auth_test.py` |
| 门户 `TMP\probe_sweep.py` | 地图/报告文件那一行的列宽与 Leaflet 像素高度核对（`--maprow-h` 与 `GISMap.tsx` 的 `zoom=8` 绑定，改 zoom 要重跑） |
| `Task\my_app\TMP\_pull_readiness_check.py` | **提交并推送之后的「别人 pull 能不能跑」总自检**（2026-09-27 加，当天就靠它抓到 `db/uploads` 那个让后端起不来的缺陷）。做法是**从 GitHub 做 depth=1 真克隆**再验，不是本地 copy：① 克隆里 `import backend.main` 数注册接口；② 门户 `server\`+`src\`、kb-bot `src\`、my_app `frontend\src\` 的相对 import 是否都落到文件（跳过注释行，否则 `components/cards/index.ts` 里的示例代码会误报）；③ kb-bot 逐文件 `node --check`；④ 四份静态壳的资源引用 —— 绝对路径按 nginx 路由前缀放行，否则会误报 15 条；⑤ 21 项关键运行文件（requirements / alembic.ini / 两个 watchdog / 两份 geojson / nginx.conf / 门户 config 等）。用法：`git clone --depth 1 <远端> Task\my_app\TMP\_clone` 然后 `python Task\my_app\TMP\_pull_readiness_check.py Task\my_app\TMP\_clone`。**只读**，退出码 0 = 全通过。⚠️ 正常少 1 个接口：SPA 兜底路由 `/{full_path}` 只在 `Task\_fe_dist` 存在时挂载，产物按约定不入库 |

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
| 探针写在门户 `TMP\` 里且带语法错 | **`npm run lint` 直接挂**：根 `tsconfig.json` 没有 `include` 且 `allowJs: true`，tsc 默认收整个项目目录，`exclude` 原本只有 `node_modules/dist/scripts` —— `TMP\` 因此在类型检查范围内（实测 `TMP/probe_color_inventory.cjs` 自 9 月 17 日起就打挂了 lint） | 已在 `exclude` 补 `TMP`/`log`/`auth-data`（2026-09-25）。跑 lint 报错时先确认报错文件属不属于自己这次的改动范围，别顺手改别人的在途代码 |
| 快照用 `_bak_` 以外的写法命名 | **悄悄入库**。`.gitignore` 原本只有 `*.bak` / `*.bak_*` / `*_bak_*`，实测门户 134 个快照有 5 种写法（`_bak_` 99 / `.bak_` 31 / `.bak-` 2 / `.bak.` 1 / 裸后缀 `qcbak` 1），最后那种连第 ⑤ 条自检的 glob 也一起漏掉，`portal.js.qcbak` 315KB 在 HEAD 里躺到 2026-09-25 | 新快照一律 `_bak_<日期>_<说明>`；命名规则变了要**同时**改 `.gitignore` 和 `vite.config.ts` 的 `server.watch.ignored` |
| 把 db/log 加进版本库 | 956M / 152M 进 git | 已被 `.gitignore` 忽略，别绕开 |
| 模块级 `Path(...).mkdir(exist_ok=True)` 建在 `db\`、`data\` 这类被忽略目录下 | **别人 pull 完后端直接起不来**：全新克隆里没有 `db\`，`import backend.routers.upload` 在 `:20` 抛 `FileNotFoundError`，连 `init_db` 都跑不到（2026-09-27 实测，`routers/mw_links.py:27` 同病） | 一律 `mkdir(parents=True, exist_ok=True)`（Node 侧 `{recursive:true}`）；推送后跑 `Task\my_app\TMP\_pull_readiness_check.py` 验一遍 |

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
