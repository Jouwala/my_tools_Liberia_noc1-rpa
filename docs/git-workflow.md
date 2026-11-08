# Git 开发流程治理 —— Agent → Branch → Commit → PR → Review → Merge

> 基准日期：2026-11-08　|　仓库：`my_tools_Liberia_noc1-rpa`（Jouwala）
> 本文件是多 Agent 并行开发的分支与合并规约，配合根 `AGENTS.md` 第六节「自主执行契约」使用。
> 本文件只管**合并与评审流程**，不管业务模块边界 —— 业务边界见 `docs/project-boundaries.md` 与各子系统 `AGENTS.md`。

## 1. 诊察结论（2026-11-08 审计）

### 1.1 仓库现状

| 事实 | 实测值 |
| --- | --- |
| 默认分支 | `master`（`origin/HEAD -> origin/master`） |
| 官方工作流 | `.github/workflows/docs-consistency.yml`（push 全分支 + PR 都跑，`--no-verify` 也兜不住） |
| 本地钩子 | `.githooks/pre-commit` 随仓库分发，`core.hooksPath` 需各机跑一次 `node scripts/setup-git-hooks.mjs` |
| 删除风险 | 目前**没有** PR 模板、CODEOWNERS、分支卫生检查；`master` 尚未确认开启分支保护 |
| 当前工作区 | 本地 `git status` 约 34 个未提交文件，说明未提交的在途改动无法从 GitHub 看到 |

### 1.2 两个开发分支的真实关系

```
merge-base(master, 两分支) = 227c7b9a
master..feat/vmax-cca-diagnosis-workspace      = 7 提交 / 120 文件（diff master...）
master..feat/feedback-permission-scope          = 8 提交 / 125 文件
feat/vmax → feat/feedback                       = 1 提交（f394f860），5 文件（实 7 含文档）
feat/feedback → feat/vmax                       = 0
```

**它不是「两个独立功能分支高度重叠」，而是「栈叠分支 + 单个巨型汇总提交」**：

| 提交 | 内容 | 文件 | 归类 |
| --- | --- | --- | --- |
| `c178426e` | VMAX 智能诊断工作台（CCA 投诉驱动单页） | 22 | **干净的 VMAX 功能** |
| `f4e8bc6d`/`ce071a72` | WhatsApp 知识库同步改临时文件承接 | — | WhatsApp |
| `998e96f3`/`83fed29f`/`dbcfd59a` | Portal 修复（viewer / 用户管理 / 团队门户资产） | — | Portal |
| `eaf3e573` | **「汇总提交当前工作区改动」** —— 把工作区在途的 100+ 文件一次性打包 | 约 100+ | **跨模块混合提交** |
| `f394f860` | 用户反馈权限收敛（feedback 专属） | 7 | Feedback |

`eaf3e573` 内部实际跨了：VMAX 诊断（`backend/routers/vmax_diagnosis*.py`、`services/vmax_cca/`、`services/vmax_multi_data/`）、IPT（`services/ipt_data/`）、eFlow（`services/eflow_assign/`、`eflow_fiber/`、`eflow_site_update_task.py`）、RAN（`services/RANElementManagement/`）、任务系统（`task_registry.py`、`task_runner.py`、`worker*.py`、`db_writer_client.py`）、Portal（`liberia-noc_soc-数据看板统一门户/` 约 12 文件）、my_app 前端（38 文件）。

这就是「120 个共同文件」的来源 —— **两分支共享了这个汇总提交自然共同**，不是各自独立开发又互串。

### 1.3 风险定级

- **不是代码错误**：两个分支的叠加关系本身是连贯的，VMAX 功能核心干净，最外层 feedback 提交边界清晰。
- **是审核风险**：`eaf3e573` 一个提交里跨 6 个业务域，Code Review 时无人敢逐行看，最终被整体吞下。继续按这个模式，后续 `feat/dashboard`、`feat/gis` 只会更难。
- **暂不merge的两个理由**：① `eaf3e573` 需做逐域拆分审计才能签字；② 34 个未提交文件（当前工作区）完全不在 GitHub 视野里，合并前先提交或 stash。

## 2. 分支模型

### 2.1 分支类型

| 类别 | 命名 | 用途 | 生命周期 |
| --- | --- | --- | --- |
| 主干 | `master` | 生产稳定版本，只接受已审 PR | 长期 |
| 功能 | `feat/<模块>-<slug>` | 新功能 | 合并即删 |
| 修复 | `fix/<模块>-<slug>` | 缺陷修复 | 合并即删 |
| Agent | `agent/<agent名>-<模块>-<slug>` | Agent 常驻工作分支（Herdr 多 Agent 场景） | 长期 |
| 紧急 | `hotfix/<模块>-<slug>` | 生产事故热修 | 合并即删 |

模块名统一用：`vmax` `portal` `dashboard` `whatsapp` `gis` `eflow` `ipt` `feedback` `myapp`（含 my_app 前后端）。

### 2.2 规则

1. **Agent 永不直接向 `master` push**（见第 4 节分支保护）。
2. **分支从 `master` 分叉，禁止三类分叉**：① 从未合入的 feat 分支上再开 feat（本次事故正源于此，得到栈叠分支）；② 从脏工作区（大量未提交）直接开分支；③ 从 `docs/git-workflow.md` 的治理分支分叉功能。
3. **栈叠分支 例外处理**：确需依赖未合入功能时（如 feedback 依赖 VMAX 工作台），分支必须注明基分支并走 **stack PR**（后开的 PR 的 base 指向前开分支），合并时按栈顺序合入，下一个 PR 自动 rebase。禁止两个分支都以 `master` 为 base 却共享未审提交。
4. **一个 PR = 一个业务功能**。`git diff --stat` 超过 50 文件即视为超限，CI `branch-hygiene` 会红并要求拆分（拆分见第 5 节）。
5. **提交信息必须带前缀**：`feat(vmax): ...` / `fix(portal): ...`。禁止 `feat(workspace)`、`汇总提交`、`WIP` 等。

## 3. PR 工作流

```
Agent 开发（独立 feat/agent 分支）
       │  git diff --stat 自查文件数
       ▼
Push → 开 PR（套用 .github/pull_request_template.md，必须填影响面/测试证据/文档检查）
       │  CI: docs-consistency + branch-hygiene 必绿
       ▼
Code Review（两人：模块 Owner + 任意 Reviewer；CODEOWNERS 自动指派）
       │  冲突检查：master 先合入（rebase）再复审
       ▼
Merge（Squash and merge，保留模块前缀）→ 删除分支 → GitHub 翻译 commit 进 master
       ▼
生产：master 即生产稳定版本
```

### 3.1 PR 模板 mandatory 字段

- **影响面**：单选 `my_app / portal / whatsapp / eflow / ipt / gis / governance`，禁止多选（多选=拆 PR 的信号）。
- **提交范围**：`git diff --stat master...HEAD` 的文件数；>50 文件说明为何未拆。
- **测试证据**：`node scripts/agent-done-check.mjs`（含 --full 时需贴输出）；无输出=未完成。
- **文档检查**：`docs-consistency` 两边 6 道守卫结果，`check:i18n`、`check:docs` 结果。

### 3.2 Review 要求

| 级别 | 规则 |
| --- | --- |
| 1 人 | 模块 Owner（CODEOWNERS）+ 1 名任意人；两者不可同一人 |
| 必查 | diff 是否只含单一模块；`AGENTS.md` 约定（任务登记 / 三处同步 / i18n）是否齐；测试证据是否存在 |
| 阻断 | 超 50 文件无拆分理由；`feat(workspace)` 汇总提交；`eaf3e573` 式跨域打包；文档与代码对不上（CI 红即自动阻断） |

## 4. 分支保护（GitHub 侧，**已于 2026-11-08 生效**）

### 4.1 已落地的实际配置（真相源，改动前先核对这里）

用 **Ruleset**（不是 Classic —— Classic 能力更弱，且无法做「仅对 PR 生效」的旁路）。

| 项 | 值 |
| --- | --- |
| Ruleset 名称 / id | `protect-master` / `26797641` |
| 页面 | `Settings → Rules → Rulesets → protect-master`（https://github.com/Jouwala/my_tools_Liberia_noc1-rpa/rules/26797641） |
| Enforcement | `active` |
| Target | `~DEFAULT_BRANCH`（即 `refs/heads/master`，**不是 all branches**） |
| 规则 | `deletion` · `non_fast_forward` · `required_linear_history` · `pull_request` · `required_status_checks` |
| PR 要求 | required_approving_review_count = 1 · dismiss_stale_reviews_on_push = true · required_review_thread_resolution = true · require_code_owner_review = **false（待第二阶段）** |
| 状态检查 | `my_app 文档一致性` · `门户文档一致性`（strict：合并前必须基于最新 master） |
| Bypass | RepositoryRole admin，`bypass_mode = pull_request`（**仅对 PR 生效**） |
| Classic protection | **未启用**（`GET /branches/master/protection` 返回 404）。两套同时开会叠加，出问题无法判断来源 |

仓库合并方式已同步收敛（`Settings → General → Pull Requests`）：
`allow_squash_merge=true`、`allow_merge_commit=false`、`allow_rebase_merge=false`、
`delete_branch_on_merge=true`、`allow_auto_merge=true`。

> **为什么 bypass 要设成 `pull_request`**：仓库只有 1 个维护者，GitHub 不允许自批。
> `pull_request` 模式让 Owner **必须开 PR、但可以自己点合并**；直接 `push master` 依旧被拒。
> 这解决了「1 人 + 要求 1 批准 = 永久合不了」的死锁，同时不牺牲「禁止直推」。

### 4.2 验证方法（不要只看 Active 徽章）

```powershell
# ① master 上实际生效的规则（[] 表示没生效）
gh api repos/Jouwala/my_tools_Liberia_noc1-rpa/rules/branches/master
# ② ruleset 的完整配置
gh api repos/Jouwala/my_tools_Liberia_noc1-rpa/rulesets/26797641
```

⚠ `GET /branches/master` 返回的 `"protected": false` **不代表没保护** —— 那个字段只反映
Classic protection，Ruleset 不改它。判据一律用上面两个接口。

### 4.3 第二阶段（治理 PR 合进 master 之后再做）

下面两项目前**故意没开**，因为它们在 `master` 上还不存在，提前开会让 PR 永久 pending：

1. 把 `branch-hygiene（文件数与提交前缀）` 加进 required status checks
   （`.github/workflows/branch-hygiene.yml` 目前只在功能分支上）。
2. 打开 `require_code_owner_review`（`CODEOWNERS` 目前只在功能分支上）。

补法：`gh api -X PUT repos/Jouwala/my_tools_Liberia_noc1-rpa/rulesets/26797641 --input <json>`，
或页面里勾。改完按 4.2 回读。

### 4.4 已知限制

- 规则只管**之后**的 push，不追溯已存在的 `master` 历史提交。
- 功能分支不受此规则影响，`git push origin feat/xxx` 照常。
- 失败提示形如 `GH006: Protected branch update failed` —— 看到它就说明规则在工作。

## 5. 历史大提交拆分指南（`eaf3e573` 式）

当一个 PR 的 diff > 50 文件或跨模块时，按下面顺序拆（不要 force-push 改历史，用新增拆分提交）：

1. `git log --name-only master..HEAD` 拉文件清单。
2. 按模块分组（`docs/project-boundaries.md` 的域口径）：`vmax` / `ipt` / `eflow` / `ran` / `portal` / `myapp` / `docs`。
3. 从 `master` 重新开一个个独立分支，逐组 cherry-pick 或重提；每组单独 PR。
4. `master` 上 eaf3e573 的原始打包提交，被拆完后的小 PR 集合替代；拆分前不接受 ingest。

本次两分支的处置见第 6 节（不建议硬拆 eaf3e573 —— 先验证它内部各域改动是否有实质缺陷，没缺陷则整体合回并记录边界）。

## 6. 本次行动序列（两分支的落地顺序）

> 状态：**已确认不直接合并**。以下为 recommended 序列，按序执行。

| 步骤 | 动作 | 命令 / 位置 | 证据 |
| --- | --- | --- | --- |
| ① | 先保存工作区：34 个未提交文件提交或 stash | `git status --porcelain` 复查；`git stash push -m "wip-..."` 或分批 commit | 脏文件清单归档 |
| ② | 开 `feat/vmax-cca-diagnosis-workspace` → master PR | PR 标题 `feat(vmax): VMAX 智能诊断工作台 + 在途修复汇总`，在 Description 里显式声明 eaf3e573 跨域 | PR 说明影响面 + branch-hygiene 绿 |
| ③ | Review + CI 绿后合入 master，删除分支 | GitHub Web | master 含 `c178426e` 22 文件 VMAX 核心 + eaf3e573 汇总 |
| ④ | rebase `feat/feedback-permission-scope` | `git checkout feat/feedback-permission-scope && git rebase master`（仅 1 提交，预期干净） | rebase 后 diff 应仅 5-7 文件 |
| ⑤ | 开 `feat/feedback-permission-scope` → master PR | 标题 `fix(myapp): 用户反馈权限范围` | diff 仅 feedback 组 |
| ⑥ | Review + 合入 master，删除分支 | GitHub Web | — |
| ⑦ | 开启分支保护（第 4 节）+ 本文件合入 master | PR `docs(git): Git 工作流治理` | 所有后续 PR 自动走红线 |

**合并形态**：本仓库是 squash-merge 友好（每个功能独立 squash，diff 清晰）；除 stack PR 例外，禁止 merge commit 混入多功能。

**审查拆分判断**：`eaf3e573` 若审查发现某个域（比如 IPT 或 Portal）有高风险改动，先 cherry-pick 那域到独立 PR 修复，再合整体；不要因此拖住 VMAX 合并 —— VMAX 所属文件（22 个）是干净的，可以先合 VMAX 子集。
