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
#    ⚠️ 这条命令的**基线不是 0**，别把它当回归信号一刀切。2026-09-30 实测总数 3451，
#    由两部分组成，处置方式完全相反：
#      a) 3419 条 = `_myapp_trash_20260913/`（隔离桶，第四节第 4 条已登记，待整体退跟踪）；
#      b) 32 条 = **真源码被过宽的根规则误命中**，一条都不许动。按命中规则分组：
#         `data_base/` 10（`Task\data_base\` 的 cell_group 与 db_writer 系列）、
#         `*.ico` 8（各看板 favicon）、`*.png` 7（顶栏 logo、leaflet 图层图标）、
#         `*.svg` 6（frontend/public 图标）、`data/` 1（门户 `src\data\initialDashboards.ts`）。
#         它们没坏 —— gitignore 本来就不作用于已入库文件，所以是「规则写得比需要的宽，
#         但历史已入库的源码安然无事」。看到这 32 条就 `git rm --cached` 的话，
#         换机器 clone 出来就是缺文件破图 / 后端起不来，正是 `AGENTS.md` 第四节第 4 条
#         反复强调的那个失败模式。
#    所以正确的读法是：**总数减去 3419 再减去 32，余量才是新漂移**。
#    分组命令（⚠️ 必须用 `-z`，普通 `git ls-files` 会把中文路径转成八进制引号串，
#    后面每一步都会对不上）：
git ls-files -z -i -c --exclude-standard | grep -zv '^_myapp_trash_20260913/' |
  xargs -0 -n1 git check-ignore --no-index -v | cut -f1 | sed 's/.*gitignore:[0-9]*://' |
  sort | uniq -c | sort -rn
# ④ 门户专用：改忽略规则时，.gitignore 与 vite.config.ts 的 server.watch.ignored
#    是同一套判断的两个副本，必须一起改
#    （2026-09-30 补：这条不是机械的「两处都写」。同一条规则的**匹配方向**在两边可能不同 ——
#     根 .gitignore 新加的 SQLite 边车规则就不需要往 watch 清单镜像，因为
#     `**/scripts/**`、`**/auth-data/**` 早就把那些目录整片忽略了。先查另一侧是否已覆盖，
#     已覆盖就不要重复登记。）
# ⑤ 快照有没有混进库（应输出空；规则见根 .gitignore 的「备份文件 / 手工快照」段）
git ls-files -- ':(glob)**/*_bak_*' ':(glob)**/*.bak' ':(glob)**/*.bak.*' ':(glob)**/*.bak_*' ':(glob)**/*.bak-*'
#    ⚠️ 陷阱：git check-ignore 对**已被跟踪**的文件一律返回「未忽略」(exit 1)，
#    因为忽略规则本来就不作用于已入库的文件。所以「规则到底写对没有」必须这样问，
#    否则会把写对的规则误判成写错（2026-09-25 实测踩到）：
git check-ignore -v --no-index -- Task\my_app\backend\main.py_bak_20260913_authswitch
# ⑥ 磁盘侧的探针残留（**git 完全看不见它们** —— 规则已生效，所以 ①③⑤ 都是空的，
#    但 `dir` 照样一屏乱码。只能直接数文件）：
$roots = 'liberia-noc_soc-数据看板统一门户','Task\my_app','.'
foreach ($r in $roots) {
  Get-ChildItem -LiteralPath $r -Recurse -File |
    Where-Object { $_.Name -match '^_|^\.?tmp_|^temp_|^seg\d.*\.txt$|^(listing|out)\.txt$' } |
    Where-Object { $_.FullName -notmatch '\\(node_modules|dist|TMP|log|\.git|\.venv|venv|Lib|Scripts|__pycache__|browser_session|chrome-win|_quarantine_[^\\]*|_myapp_trash_[^\\]*)\\' } |
    Where-Object { $_.FullName -notmatch '\\(src|server|backend|frontend)\\' } | Measure-Object
}
#    2026-09-30 实测基线：门户 **0**、`Task\my_app` **4**、工作区根 **78**。
#    门户的 0 是 2026-09-25 归档的结果（220 个挪到 `_quarantine_20260925\portal_probes\`，
#    逐文件明细见该目录下 `_MANIFEST.tsv`）。后两处**还没有清过**，具体是什么：
#      - `Task\my_app\` 根目录：`_p.py` `_s.py` `_slice1.txt` `_tmp_view.txt`
#        —— 正好落在第四节第 7 条禁止的位置（venv 根目录，不是 `TMP\`）。
#      - 工作区根：`tmp_qc*.txt` 78 个 / 359KB，最大的 7.9KB。
#      - `Task\my_app\log\` 另有 7 个 `_probe_*.txt` / `_procs*.txt`（09-13/09-16 的），
#        被上面的 `log` 排除项挡住了，属于「运行日志目录里的探针」，同样该清。
#    ⚠️ 上面那两条 `Where-Object` 的排除项**不是可选的**，去掉就会拿到假的巨大数字：
#    `Task\my_app` 是 venv 根，`Lib\site-packages\` 里 numpy/playwright/PIL 自己的
#    `_*` 模块就有 700+ 个（实测整棵树数出来 820），全是被 git 忽略的第三方包。
#    同理 `backend\services\_playwright_utils.py`（被 `site_outage_service.py:22` import）、
#    门户 `src\pages\_TemplatePage.tsx` 都带下划线但是**真源码**，一条都不能算噪声 ——
#    这也是排除列表里要写 `src|server|backend|frontend` 的原因。
#    非 0 就是本次会话又落了新探针，按第四节第 7 条清掉。
#    ⚠️ 上面这段粘进交互控制台可以直接跑；**存成 .ps1 就不行** —— 路径里有中文，
#    本机 PowerShell 5.1 把无 BOM 的 UTF-8 脚本按 ANSI 读，中文路径会碎成乱码并报
#    Cannot find path（2026-09-25 实测）。存脚本时先 ASCII 通配定位目录：
#      Get-ChildItem -LiteralPath 'D:\01_RPA' -Directory | ? { $_.Name -like 'liberia-noc_soc*' }
# ⑦ 本仓库是**多人 / 多会话共用一个工作区**的，`git rm --cached` 这类只动索引的改动
#    **不持久**。2026-09-30 实测：本会话在 14:5x 退跟踪 39 个运行时文件并当场验证过
#    （索引 4956→4917、`git status` 出现 39 条 `D `），15:02:21 另一个会话执行了
#    `git reset: moving to HEAD` 再提交 `7244412f`，索引被重建，那 39 条**全部回到跟踪状态**，
#    而新提交里既没有这 39 条删除、也没带上了改动过的 `.gitignore` —— 于是出现
#    「规则已生效、文件仍被跟踪」的分叉态，比原来更隐蔽。
#    所以：
#      a) 做完退跟踪**立刻**重跑 ①③ 复查，不要把成果只留在索引里；
#      b) 要么当次把它提交掉，要么在 `TODO.md` 留一条待办，否则下一次别人的 reset 就冲没了；
#      c) `git reflog --date=iso -3` 是判断「 HEAD / 索引是不是被别的会话动过」的最快证据，
#         数字对不上时先查它，不要以为自己在跟鬼打架。
```

可复用的诊断脚本（**不删**，按第四节第 7 条记录用途；都在 `TMP\` 下，不入库）：

| 脚本 | 用途 |
| --- | --- |
| `Task\my_app\TMP\_audit_fe_dist.mjs` | 前端构建产物的**可达性审计 + 孤儿剪枝**：从 HTML 入口做传递可达性（跟随 `assets/` 引用与相对 chunk import），算出「在用的」「历次构建遗留的孤儿」，按 mtime 月龄分桶。判据经交叉验证：最新一次构建产出的文件数与可达集大小一致。默认**只读**；`--apply` 才会挪文件，且候选**只取 `assets/` 下、不可达、且月龄 ≥ `--min-age-days`（默认 8）**的孤儿，同盘 `rename` 进隔离区不删除，并写 `_MANIFEST.tsv`。两道硬保险：候选与可达集有交集就 `exit 1` 拒绝移动；`lib\`、`legacy-*.css`、`*.geojson`、备份命名 HTML **一律不碰**（可达性跟不到 `lib/` 引用，没进可达集≠没人用）。用法：`node Task\my_app\TMP\_audit_fe_dist.mjs [--min-age-days=N] [--apply] [--dest=目录]`。2026-09-30 首次 `--apply`：挪走 2741 个 / 61.9MB，复跑审计在用集不变（14 HTML / 79 chunk），14 个在用页面与入口引用的 7 个资源逐个 200，还原说明见 `_quarantine_20260930\fe_dist_stale\_RESTORE.md` |
| `TMP\_mk_untrack_list.mjs` | 从「已跟踪但被忽略规则命中」的集合里按**白名单**挑出可安全脱离跟踪的文件，硬排除真源码（`Task\data_base\`、门户 `src\data\` 会被历史规则 `data_base/`、`*/data/` 误命中）。输出 NUL 清单 `TMP\_tountrack.nul` 供 `git rm --cached --pathspec-file-nul` 使用 |
| 门户 `TMP\_plan_snapshot_archive.mjs` | **手工快照配额执行器**（`AGENTS.md` 第四节第 7 条「同母本只留最近 3 份」的机器版）。按 `bak` 命名变体收磁盘快照，用**文件名里的日期**（不是 mtime，它会被复制/移动改写）归组排序，超出 3 份的用同盘 `rename` 挪进隔离区。默认 dry-run，`--apply` 才动；动之前逐条比对 `git ls-files` 并报出**仍被跟踪**的那几个（必须先 `git rm --cached`，否则冒出工作区删除），并把「`bak` 前无分隔符」的不规则命名（如 `portal.js.qcbak`）单独告警而不是静默放行。**不碰 `src\`、`server\`、`TMP\`、`node_modules\`、`dist\`** |
| 门户 `TMP\v1_render_test.cjs` | `/v1/olbrportal/` 的**渲染回归**：用 DOM 桩跑真实 `olbr.js`，断言两排卡片数（QC 6 张 / CXO 6 张 = 3 富 + 3 可用率）、富卡片结构、走势点数、可用率页脚三格、`is-nospark` 2/4 拆分、`>视频流量<` 不得回归、以及**不再请求** `/api/vmax-cxo-daily/grid`。夹具 `TMP\{alarm_overview,catalog,olib_overview}.json`。结果写 `TMP\v1_out.txt`，失败 exit 1。用法：`node TMP\v1_render_test.cjs` |
| 门户 `TMP\v1_interact_test.cjs` | `/v1/olbrportal/` 的**交互回归**：KPI 重试按钮、六个视图卡展开、Escalation Matrix 展开与取消选中。结果写 `TMP\v1_interact_out.txt`，失败 exit 1 |
| 门户 `TMP\probe_rich_cards.py` | 浏览器实测：把 CXO 富卡片渲染出的大数字/徽章/极值**逐个与 `/api/olib-soc-dashboard/overview` 的返回核对**，并记录亮暗两主题的列数与卡片宽度。写 `TMP\_rich_cards.json`。需要 Playwright（`Python312`） |
| 门户 `TMP\probe_shot.py` | 给任意区块截图（亮/暗各一张）做人工目视比对。用法：`python TMP\probe_shot.py [选择器] [文件名前缀] [--click s1,s2] [--lang zh\|en]`，默认 `#kpi` → `TMP\_shot_<theme>.png`。例：`python TMP\probe_shot.py "#band" _band`；截登录闸门要先点开：`python TMP\probe_shot.py "#gate" _gate --click "#umBtn,#gmreq"`。脚本会先清掉门户 token，否则已登录状态下截不到闸门 |
| 门户 `TMP\v1_auth_test.py` | `/v1/olbrportal/` 的**鉴权链路回归**：入口可达（`local` 占位身份下 `#umBtn` 必须可见）→ 点击唤起闸门 → 取消退回 → 登录/注册两态切换 → 本地校验（不足 8 位 / 两次不一致，且**不得发请求**）→ 注册成功（校验 `{username,password,note}` 载荷与 `ar.ok` 文案）→ 四种错误码文案映射（`username_taken`/`request_pending`/`too_many_requests`/断网）→ 登录成功（token 落共享键、闸门收起、用户管理面板自动打开）。结果写 `TMP\_auth_out.json`，失败 exit 1。**关键：全程用 Playwright 路由拦截替掉后端** —— 真发一次注册申请会往 `auth-data\portal-auth.db` 写一行真实待审批记录，只有管理员能删，所以这个测试刻意不碰真库。用法：`python TMP\v1_auth_test.py` |
| 门户 `TMP\probe_sweep.py` | 地图/报告文件那一行的列宽与 Leaflet 像素高度核对（`--maprow-h` 与 `GISMap.tsx` 的 `zoom=8` 绑定，改 zoom 要重跑） |
| `Task\my_app\TMP\_pull_readiness_check.py` | **提交并推送之后的「别人 pull 能不能跑」总自检**（2026-09-27 加，当天就靠它抓到 `db/uploads` 那个让后端起不来的缺陷；2026-09-30 因 TMP 被清重写了一遍，口径按下面的实测改过）。做法是**从 GitHub 做 depth=1 真克隆**再验，不是本地 copy：① 克隆里 `import backend.main` 数注册接口；② 门户 `server\`+`src\`、kb-bot `src\`、my_app `frontend\src\` 的相对 import 是否都落到文件（跳过注释行，否则 `components/cards/index.ts` 里的示例代码会误报）—— **门户目录只有一个**：`liberia-noc_soc-…`（主）；2026-10-01 前存在的连字符目录 `liberia-noc-soc-…`（只放 `OlrPortal` 壳）已合入主门户的 `OlrPortal\`。脚本仍按 `liberia-noc*` 前缀收齐再遍历，将来再出现静态壳目录时不会漏检；③ kb-bot 逐文件 `node --check`；④ 静态壳的资源引用：绝对路径按 nginx 路由前缀放行，且 **js/css 里的 `src`/`href` 要按壳根解析、html 里的按自身目录解析**（浏览器是按加载它的页面解析的，按文件目录算会误报），`_bak_` 快照整个跳过（不是线上入口）；⑤ 22 项关键运行文件（requirements / alembic.ini / pyproject / 两个 watchdog / 两份 geojson / `Task\my_app\nginx\` 的三段 conf / 门户 config 等 —— nginx 主配置不在库里，见第四节第 6b 条）。用法：`git clone --depth 1 <远端> Task\my_app\TMP\_clone` 然后 `python Task\my_app\TMP\_pull_readiness_check.py Task\my_app\TMP\_clone`；不想等网络也可以 `git worktree add --detach Task\my_app\TMP\_wt HEAD` 拿 HEAD 的独立检出跑同一份检查（用完 `git worktree remove --force`）。**只读**，退出码 0 = 全通过。⚠️ 正常少 1 个接口：SPA 兜底路由 `/{full_path}` 只在 `Task\_fe_dist` 存在时挂载，产物按约定不入库 |
| `Task\my_app\TMP\_secret_scan_staged.py` | **提交前的凭据扫描**：只扫 `git show :路径` 的**已暂存内容**（不是工作树），八类模式（password/secret/token 字面量、Bearer 头、私钥块、AKIA、Slack/Telegram 长串、带口令的 URL），并逐条与 `git show HEAD:路径` 对比，**只报本次新增的命中** —— 否则仓库里既有的配置项名会被当成新泄露反复报，报三次之后人就免疫了。用法：`git add -A` 之后 `python Task\my_app\TMP\_secret_scan_staged.py`，新增命中为 0 才 exit 0。注意它**不匹配** `default_secret` 这种复合键名（词边界不成立），那是刻意的：凭据组的 `default_user/default_secret` 按既定约定照原样入库（见 `docs\manual\05-security-and-credentials.md`），要复核的是**新出现的**明文字面量 |

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
- [ ] **改了 `nginx-1.28.0\conf\` 下任一份配置后，已同步回 `docs\nginx-reference\`**（否则副本立刻变成新的分叉源，见 `docs\新机器部署清单.md` §2）
- [ ] 子路径部署时 `vite.config.ts` 的 `base` 已同步并**重新构建**
- [ ] 日志轮转任务正常（`install_nginx_log_rotate_task.bat`、`rotate_nginx_logs.ps1`）
- [ ] 不在值班高峰期重启生产服务（7038/7090/9267）
- [ ] **换机器 / 新克隆后跑过 `python Task\my_app\tools\clone_doctor.py`**（期望 0 FAIL）

> **新机器搭建全流程**见 `docs\新机器部署清单.md`：哪些必须上传、哪些必须重建、哪些只能手工拷贝。
> **换机器 / 排查环境缺失时，先跑这一条**（只读，列出全部缺失项与补法）：
> ```
> cd Task\my_app && python tools\clone_doctor.py
> ```
> 三条最容易踩的：① **真实数据在 PostgreSQL（`MY_APP_DB_MODE=pg`，97 张表 / 310 万行），不是 `db\app.db`**；
> ② **启动脚本按「有无依赖」选解释器**，仓库内 `Scripts\` 是 8787/8790 实时代理专用的另一个 venv；
> ③ `nginx-1.28.0\` 二进制不上传，但配置文本已在 `docs\nginx-reference\`。
> 库迁移用 `Task\my_app\tools\pg_migrate.ps1 dump|restore`。
> ⚠ **两个实时代理脚本现已迁到 `Task\my_app\tools\`**（`realtime_proxy.py` / `realtime_proxy_vmax.py` /
> `start-app.mjs`，2026-10-03）。它们原先在 `scripts\` 里被 `/Scripts/` 静默忽略、换机器即丢失。
> `scripts\` 现在只剩 venv（launcher + 解释器）与会话文件，**仍然不可删**。
> ⚠ **`Task\my_app\scripts\` 是陷阱目录**：`.gitignore:9` 的 `/Scripts/` 在本机**大小写不敏感**生效，
> 写在这个目录里的任何新文件都**不会入库**；而它同时又装着不可重建的 FMS/VMAX 实时代理脚本
> + venv launcher。**别往这里放源码，也别整个删掉** —— 2026-10-03 已因此丢过一次代理脚本。

## 五、常见开发陷阱

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| 门户 API 用 `/api` | 命中 my_app，POST 回 405 | 用 `PORTAL_API`（`/uniplam/api`） |
| 只加中文 i18n 键 | 英文界面显示 key 原文 | `zh` 与 `en` 两份都加 |
| my_app 前端产物目录改名 | 后端找不到静态文件，白屏 | 保持 `_fe_dist` |
| 改了初始看板数据就以为生效 | 被 localStorage 覆盖，看不到 | 清缓存 / 「恢复初始默认看板」 |
| 数字取不到时显示 0 | 运维误判为"已清空" | 显示 `—` |
| 用 interval 累加做定时刷新 | 进页面时机不对要等一整个周期 | 用墙上时钟对齐网格（见 `architecture.md` 流 2） |
| 只提交「引用方」，漏掉被引用的新文件 | **别人 pull 后前端构建直接中断 / 后端起不来**。实测两次：`App.tsx` 自 `b9f2c6a8` 起就 `import('./pages/BmSpeedtest')` 而页面文件一直停在未跟踪；`main.py:94` import 了未跟踪的 `routers/bm_speedtest.py`。**注意提交顺序** —— 引用方先落地，仓库就在那个提交上坏掉，直到补文件的那个提交才好（期间任何人 checkout 到中间提交都构建不了） | `git add -A` 之后跑 `python Task\my_app\TMP\_pull_readiness_check.py`（它对克隆里每一条相对 import 去找落点文件，落空即报）；推之前还可以 `git worktree add --detach Task\my_app\TMP\_wt HEAD` 用 HEAD 的独立检出跑同一份自检，跑完 `git worktree remove --force`。**两点补充（2026-09-30）**：① 脚本本体在 `TMP\`，按约定不入库，换机器/清理后会没有，照本行的用法重建即可；② 新增页面或路由时必须把它点名的文件补进脚本末尾的 `KEY` 清单 —— `lazy(() => import('./pages/X'))` 和 `import('./pages/X')` 这种动态导入，相对 import 检查是**看不见**的（`b9f2c6a8` 那次就是这么漏掉 `BmSpeedtest.tsx` 的），只有 `KEY` 逐项点名才拦得住 |
| 探针脚本写在仓库根 | 误入库（已有 98 个的历史教训） | 放 `TMP\` |
| 探针写在门户 `TMP\` 里且带语法错 | **`npm run lint` 直接挂**：根 `tsconfig.json` 没有 `include` 且 `allowJs: true`，tsc 默认收整个项目目录，`exclude` 原本只有 `node_modules/dist/scripts` —— `TMP\` 因此在类型检查范围内（实测 `TMP/probe_color_inventory.cjs` 自 9 月 17 日起就打挂了 lint） | 已在 `exclude` 补 `TMP`/`log`/`auth-data`（2026-09-25）。跑 lint 报错时先确认报错文件属不属于自己这次的改动范围，别顺手改别人的在途代码 |
| 快照用 `_bak_` 以外的写法命名 | **悄悄入库**。`.gitignore` 原本只有 `*.bak` / `*.bak_*` / `*_bak_*`，实测门户 134 个快照有 5 种写法（`_bak_` 99 / `.bak_` 31 / `.bak-` 2 / `.bak.` 1 / 裸后缀 `qcbak` 1），最后那种连第 ⑤ 条自检的 glob 也一起漏掉，`portal.js.qcbak` 315KB 在 HEAD 里躺到 2026-09-25 | 新快照一律 `_bak_<日期>_<说明>`；命名规则变了要**同时**改 `.gitignore` 和 `vite.config.ts` 的 `server.watch.ignored` |
| 用 `*.wal` / `*.shm` 挡 SQLite 边车 | **挡不住，12 个边车一直在库里**。边车文件的命名是 `<主库名>-wal` / `<主库名>-shm`，主库叫 `db.sqlite3` 时边车就是 `db.sqlite3-shm` —— 结尾是**连字符**不是点，所以 `*.shm`（要求以 `.shm` 结尾）和 `*.db-shm` 两条都不命中，`git check-ignore -v` 直接无输出。更麻烦的是这类文件**会自己出现又自己消失**：SQLite 在最后一个连接正常关闭时会删掉 `-wal/-shm`，下次连接再重建，于是它们反复生成 ` D` / `??` 噪声（实测 `Task\RAN\db.sqlite3-shm/-wal` 提交时就在 ` D` 状态）。| 根 `.gitignore` 已补 `*.sqlite-shm/wal`、`*.sqlite3-shm/wal`、`*.db-journal`、`*-journal`；判断规则名能不能命中，**拿真实文件名去问 `check-ignore --no-index`**，不要看规则字面像不像 |
| 运行产出的 `.md` 当文档入库 | **每天 +1 的提交噪声**，还把业务对话内容写进了版本历史。门户 `scripts\whatsapp_analysis\reports\` 由 node-cron 逐日生成，它自己的 README 写着「所有数据只保存在本机（`data\assistant.db` 与 `reports\`）」，实测已有 26 份在库里。同目录的 `data\` 被根规则的 `data/` 挡住了，`reports\` 因为名字里没有 data 而漏网 —— 规则按**目录名关键字**写，就会漏掉语义相同、名字不同的那一个 | 按「是不是运行产出」判，不按扩展名或目录名关键字判；数据类目录一律显式点名（见门户 `.gitignore` 的 `scripts/whatsapp_analysis/reports/`） |

| 把 db/log 加进版本库 | 956M / 152M 进 git | 已被 `.gitignore` 忽略，别绕开 |
| 以为「拷 `db\app.db` 就有数据」 | **白忙**：当前 `MY_APP_DB_MODE=pg`（`backend\.env`），真数据在 PostgreSQL `myapp`（2183MB / 97 张表 / 约 310 万行），`db\app.db` 在 pg 模式下**根本没被读**。它是 `MY_APP_DB_MODE=sqlite` 熔断回退（`database.py:23-26`）的落点，不可删但也不够用。且 `alembic\versions\` 5 个迁移里**只有 CREATE INDEX、零 INSERT**，`git ls-files db/` = 0 → **无任何 seed 可重建** | 迁移库用 `Task\my_app\tools\pg_migrate.ps1 dump\|restore`。页面数据实际分三处（PG / `data\*.sqlite3` / `db\app.db`），**漏任一处都是「页面能开但数据空」**。详见 `docs\新机器部署清单.md` §3 |
| `pg_dump -n public` 做迁移备份 | **得到一个「成功但空」的备份**。本库的表**根本不在 public** —— `search_path` 是 `app, eflow, lte_pl, battery, ms_sla, fw, ipran_ume, ran_ume, public`，实测 `pg_dump -t 'public.*'` 直接报 `no matching tables were found` | **不加 `-n`**（dump 全部非系统 schema）。`pg_migrate.ps1` 已内建此防护，并会先打印将要备份的 11 个 schema |
| 用业务账号建库 | `createdb -U myapp` 报「创建数据库权限不够」—— 实测 `myapp` 的 `rolcreatedb=f / rolsuper=f`。**但这不代表业务账号不能恢复数据**：已验证它能建 schema、建表、写入 | 建库用超级用户（`pg_migrate.ps1 restore -SuperUser postgres`），**恢复数据仍用业务账号**；新库 **owner 必须是业务账号** |
| 把新脚本写进 `Task\my_app\scripts\` | **它会静默不入库**：`Task\my_app\.gitignore:9` 的 `/Scripts/` 在本机大小写不敏感，`scripts\` 一起被忽略。实测 `git check-ignore -v Task/my_app/scripts/x.py` → `Task/my_app/.gitignore:9:/Scripts/`。换机器后别人**根本没有这个文件** | 源码放 **`Task\my_app\tools\`**（已验证不被忽略）。写完先 `git check-ignore -v <路径>` 确认能进库 |
| `Remove-Item scripts -Recurse -Force`「清空目录」 | **`scripts\` 不是空目录，也不只是 venv**：它是 venv 的 launcher 目录（`python.exe`/`pip.exe`/`activate.*`），2026-10-03 前**还**装着 `realtime_proxy.py`(940 行)、`realtime_proxy_vmax.py`、`start-app.mjs` —— 三者当时**从未入库、无处可 clone**。2026-10-03 实际发生，代理脚本被删（8787/8790 靠进程内存续命，靠 `.pyc` 才反推回来） | **删目录前先 `Get-ChildItem -Force -Recurse` 列一眼**。`Remove-Item` 对非空目录不报错。真要清理只删具体文件，别删目录。脚本现已迁 `tools\` 入库，但 venv 仍在，**依然不可删** |
| `python -m venv --upgrade <my_app 根>` | **会把 `.gitignore` 覆盖成 venv 的 2 行样板（内容就一个 `*`）**。该 `*` 忽略 `my_app\` 下所有**未跟踪**文件 —— 已跟踪的不受影响，所以 `git status` 看着正常，**但新写的源码永远不出现**（本项目历史上因此连续三周漏提交）。2026-10-03 实际发生 | `.gitignore` 在 HEAD 里是完好的 146 行版本：`git checkout HEAD -- Task/my_app/.gitignore` 即可复原。只想补 launcher 就别跑 venv，改逐包 `pip install --force-reinstall` 或直接复制 `activate.*` 模板 |
| 把代理会话文件当成普通运行时文件 | `fms_session.json` / `vmax_session.json` 内含两个内网门户的**有效登录 Cookie + csrf**，等同凭据。脚本迁到 `tools\` 后它们**跟着落到 `tools\`**，而旧的 `/Scripts/` 忽略规则**不再覆盖**，一旦 `git add -A` 就会把凭据推到远端 | 已在 `Task\my_app\.gitignore` 加 `/tools/*_session.json`（2026-10-03）。新增同类文件后**务必 `git check-ignore -v` 复核**；文件本身可随时删，下次启动重新登录 |
| 往仓库里的 `Scripts\` 或 `.venv\` 装依赖 | **装错地方，后端依然起不来**。`start_hidden.ps1` 的解析顺序是「① PATH → ② 4 个硬编码系统路径 → ③ 最后才 `$base\Scripts\pythonw.exe`」，实测 7038 的进程来自 `%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe`；`.\Scripts\python.exe -c "import fastapi"` 直接 `ModuleNotFoundError`。**注意 `Scripts\` 不是废 venv**：它的 `pyvenv.cfg` 指向 `.workbuddy` 的 Python 3.13，装着 numpy/opencv/pywin32，服务 8787/8790 两个实时代理，**不要清掉** | 先 `python -c "import sys; print(sys.executable)"` 确认**会被选中的**解释器，再往里装 `pip install -r requirements.txt`；Playwright 浏览器另跑 `playwright install`。2026-10-03 起 `start_hidden.ps1` 已改为**按有无依赖探测**并打印选中项，装错地方会显式 `[FAIL]` 而不是只报「45 秒内未监听」 |
| 新机器缺 nginx 配置 | **页面打不开**，且现象隐蔽（少一条 `location` 只在某个 URL 上 404，不容易联想到配置缺失）。`nginx-1.28.0\` 整目录被根 `.gitignore:264` 忽略，其 `conf\` 下三份配置（`nginx.conf` / `portal_ports.conf` / `portal_eflow_common.conf`，共约 47KB）此前**零入库副本** | 配置文本副本已入库在 `docs\nginx-reference\`（2026-10-03 补）。**改完生效配置并 reload 成功后必须同步回副本** —— 加上 `.19` 那台，实际是**三份**要保持一致 |
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
| **新机器部署清单** | `docs\新机器部署清单.md`（上传/重建/手拷三类清单） |
| **nginx 配置参考副本** | `docs\nginx-reference\`（改配置后须同步） |
| 鉴权开关 | `AUTH_SWITCH.md` |
| 架构与数据流 | `architecture.md` |
| 视觉规则 | `DESIGN.md` |

> **工具负责整理，人与 AI 负责协作执行。**
