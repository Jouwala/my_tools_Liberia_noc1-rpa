
# Herdr + OMP 多项目并行开发落地方案

**适用仓库：** `Jouwala/my_tools_Liberia_noc1-rpa`  
**目标：** 将仓库内多个应用和自动化项目拆分为可独立开发的 Agent 工作单元，同时通过共享接口契约、Git Worktree 和统一验证流程，避免 Agent 之间互相覆盖代码。

---

## 1. 实施目标

本方案不追求一次性启动大量 Agent，而是建立稳定的多项目开发机制：

1. 每个相对独立的项目由专属 Agent 负责。
2. 每个并行开发任务使用独立 Git Worktree 和分支。
3. 同一文件同一时间只能有一个写入 Agent。
4. 跨项目依赖通过 API 契约、文档和测试数据共享，不直接共享工作目录。
5. Herdr 负责组织工作区、终端和 Agent 任务状态。
6. OMP 负责具体代码分析、开发、测试和修复。
7. 人类负责人负责任务拆分、跨项目决策、合并和生产发布。

## 2. 仓库项目边界

| 项目 / 模块 | 建议 Agent | 独立开发程度 | 说明 |
|---|---|---:|---|
| `Task/my_app/` 后端 | MyApp Backend Agent | 高 | FastAPI、业务服务、API、任务注册、数据处理 |
| `Task/my_app/` 前端 | MyApp Frontend Agent | 高，但需接口契约 | React 页面、GIS、KPI、TT/WO Dashboard、i18n |
| `liberia-noc_soc-数据看板统一门户/` | Portal Agent | 高 | 独立门户前端、Express 服务、认证、团队门户、看板聚合 |
| `Task/MTN_Comsal/my_app/` | Comsal Agent | 高 | 独立数据分析应用，前后端和业务模块 |
| `Task/whatsapp-kb-bot/` | WhatsApp Bot Agent | 高 | WhatsApp 接入、RAG、知识问答、工具路由和 API 集成 |
| `Site_outage/`、`ticket_export_rpa/`、`Task/RAN/`、`Task/ORANGE/`、`Task/Monthly_Report/` | RPA Agent | 中至高 | 按具体脚本或业务流程拆分任务，避免多个 Agent 同时修改公共脚本 |
| `Unified_Tools/`、`Task/Unified_Tools/` | Shared Tools Agent | 中 | 公共工具、运维脚本、部署辅助工具；先确认重复目录的权威来源 |
| `openclaw_api_selector/` | API Selector Agent | 高 | 独立 API 选择/路由相关模块 |
| 全仓库架构与质量 | Architect / QA Agent | 只读优先 | 架构审查、依赖检查、测试、风险分析 |

### 首批建议启用的 Agent

第一阶段只启动以下 4 个：

1. **MyApp Backend Agent**
2. **MyApp Frontend Agent**
3. **WhatsApp Bot Agent**
4. **QA / Architecture Agent（只读）**

Portal 和 Comsal 在第一批流程稳定后加入。不要一开始让所有 Agent 同时修改代码。

---

## 3. Herdr 工作区组织

建议 Herdr 中按项目建立 Workspace，而不是按 Agent 数量建立大量无关 Workspace。

```text
Herdr
├── MyApp
│   ├── backend
│   ├── frontend
│   ├── tests
│   └── review
├── WhatsApp Bot
│   ├── bot-service
│   ├── rag-evaluation
│   └── tests
├── Portal
│   ├── frontend
│   ├── server
│   └── tests
├── Comsal
│   ├── backend
│   ├── frontend
│   └── tests
├── RPA
│   ├── site-outage
│   ├── ticket-export
│   ├── ran
│   └── reports
└── Shared Tools
    ├── utilities
    ├── deployment
    └── review
```

每个 Workspace 内的终端进入对应的 Git Worktree，再启动 OMP。

建议命名规范：

```text
Workspace：WhatsApp Bot
Worktree：.agent-worktrees/whatsapp-bot
Branch：agent/whatsapp-bot
```

---

## 4. Git Worktree 隔离策略

### 4.1 基本原则

- 每个并行任务创建独立 Worktree。
- 每个 Worktree 使用独立分支。
- 不允许多个 OMP Agent 在同一个 Worktree 中同时执行写入任务。
- 不允许 Agent 直接修改主工作目录或 `master` 分支。
- 合并前必须通过项目测试和 QA 检查。
- Worktree 只隔离工作目录，不会自动解决逻辑冲突；仍需遵守单文件单写入者原则。

### 4.2 创建 Worktree

在仓库根目录执行：

```powershell
git worktree add .agent-worktrees/myapp-backend `
  -b agent/myapp-backend master

git worktree add .agent-worktrees/myapp-frontend `
  -b agent/myapp-frontend master

git worktree add .agent-worktrees/whatsapp-bot `
  -b agent/whatsapp-bot master

git worktree add .agent-worktrees/portal `
  -b agent/portal master

git worktree add .agent-worktrees/comsal `
  -b agent/comsal master
```

如果任务需要基于最新开发分支，应先确认基线分支，再创建 Worktree。

### 4.3 查看与清理

```powershell
git worktree list
```

任务合并完成后：

```powershell
git worktree remove .agent-worktrees/whatsapp-bot
git branch -d agent/whatsapp-bot
```

清理前确认该 Worktree 没有未提交修改。

---

## 5. OMP Agent 职责与权限

### 5.1 MyApp Backend Agent

**允许修改：**

- `Task/my_app/` 后端业务模块
- API Router、Service、数据处理逻辑
- 后端测试
- 后端相关文档

**默认禁止修改：**

- 前端页面和样式
- Portal 项目
- WhatsApp Bot 项目
- 根目录部署配置
- 生产环境配置和凭据

**交付内容：**

- 修改文件清单
- API 变更说明
- 测试结果
- 数据库或配置变更说明
- 前端需要配合的接口契约

### 5.2 MyApp Frontend Agent

**允许修改：**

- `Task/my_app/` 前端页面、组件、样式
- 前端路由和交互
- 前端 i18n
- 前端测试

**默认禁止修改：**

- 后端 API 实现
- Portal 前端
- Bot 服务
- 全局部署文件

**约束：**

- API 字段必须来自已确认的接口契约。
- 不得自行猜测后端字段。
- 修改公共路由、导航或 i18n 入口前，先登记文件锁。

### 5.3 WhatsApp Bot Agent

**允许修改：**

- `Task/whatsapp-kb-bot/`
- Bot 专属测试和评测数据
- Bot 专属文档
- Bot 的 RAG、工具路由、消息处理和 API Client

**默认禁止修改：**

- `Task/my_app/` 主系统代码
- Portal
- Comsal
- 根目录部署脚本
- 其他 RPA 项目

**交付内容：**

- Bot 功能说明
- 工具调用流程
- RAG / 问答评测结果
- API 依赖清单
- 错误处理与日志说明
- 配置项和环境变量清单

### 5.4 Portal Agent

负责门户自身的前端、Express 服务、认证和聚合逻辑。与 MyApp 的联动通过 API 契约完成，不直接修改 MyApp 代码。

### 5.5 Comsal Agent

负责 Comsal 独立应用。除非任务明确涉及公共工具，否则不得修改 MyApp、Portal 或 Bot。

### 5.6 QA / Architecture Agent

默认只读。

负责：

- 检查变更是否越过项目边界
- 检查接口契约是否一致
- 执行测试和静态检查
- 检查安全风险
- 检查是否存在不必要的跨项目修改
- 输出合并建议

QA Agent 不应在没有明确授权的情况下直接修复其他 Agent 的代码。

---

## 6. 共享上下文设计

共享上下文分为三层，避免每个 Agent 读取整个仓库后自行理解。

### L1：全仓库上下文

建议维护：

```text
AGENTS.md
docs/
├── architecture.md
├── project-boundaries.md
├── development.md
├── shared-contracts/
└── decisions/
```

内容包括：

- 仓库总体架构
- 项目边界
- Git 和 Worktree 规则
- 安全规范
- 测试与合并规则
- 跨项目依赖关系

### L2：项目上下文

每个项目维护自己的 `AGENTS.md` 或项目说明文档。

例如：

```text
Task/my_app/AGENTS.md
Task/whatsapp-kb-bot/AGENTS.md
liberia-noc_soc-数据看板统一门户/docs/AGENTS.md
```

项目文档应说明：

- 项目用途
- 技术栈
- 目录结构
- 启动方式
- 测试方式
- 关键模块
- 允许修改的范围
- 禁止修改的范围

### L3：任务上下文

每个任务必须有独立任务说明：

```text
.agent-work/
├── tasks/
│   ├── active/
│   └── completed/
├── contracts/
├── decisions/
└── file-ownership.md
```

任务说明至少包含：

```markdown
# Task ID

## Objective
要完成什么。

## Scope
允许修改的目录和文件。

## Out of Scope
明确禁止修改的内容。

## Dependencies
依赖哪些 API、模块或其他 Agent。

## Acceptance Criteria
如何判断任务完成。

## Validation
必须执行的测试。

## Owner
唯一写入 Agent。

## Integration Notes
需要通知哪些项目或 Agent。
```

---

## 7. 跨项目共享接口契约

### 7.1 MyApp 与 Portal

共享内容：

- API Base URL
- 认证方式
- API 路径
- 请求和响应结构
- 错误格式
- 页面跳转规则
- 部署路径

建议将稳定接口记录在：

```text
docs/shared-contracts/myapp-portal.md
```

### 7.2 MyApp 与 WhatsApp Bot

共享内容：

- Bot 可调用的业务 API
- 认证方式
- 权限范围
- 请求参数和响应字段
- 错误码
- 超时和重试规则
- 工具调用的审计要求

建议记录在：

```text
docs/shared-contracts/myapp-whatsapp-bot.md
```

Bot Agent 不应直接读取或修改 MyApp 内部业务实现；优先使用 API 契约和测试样例。

### 7.3 Bot 知识库与评测

建议维护：

```text
Task/whatsapp-kb-bot/
├── docs/
├── evals/
│   ├── questions.jsonl
│   └── expected_answers.jsonl
├── tests/
└── config/
```

知识库文档、测试问题和标准答案应与程序代码分开管理，避免代码 Agent 在修改业务逻辑时意外覆盖知识资料。

---

## 8. 文件冲突管理

建立：

```text
.agent-work/file-ownership.md
```

示例：

```markdown
| File / Directory | Owner | Status | Notes |
|---|---|---|---|
| Task/my_app/backend/** | MyApp Backend Agent | Active | Backend task |
| Task/my_app/frontend/** | MyApp Frontend Agent | Active | Frontend task |
| Task/whatsapp-kb-bot/** | WhatsApp Bot Agent | Active | Bot task |
| Task/my_app/frontend/src/App.tsx | MyApp Frontend Agent | Locked | Shared routing entry |
| Task/my_app/frontend/src/i18n.tsx | MyApp Frontend Agent | Locked | Shared i18n entry |
| docs/shared-contracts/** | Human / Architect | Review required | Shared contracts |
| AGENTS.md | Human / Architect | Review required | Global rules |
```

### 文件锁规则

1. 任务开始前登记文件范围。
2. 修改公共入口文件时，必须显式登记。
3. 如果两个任务需要修改同一文件，拆成先后任务或由一个 Agent 统一修改。
4. Agent 发现需要越界修改时，暂停并提出请求。
5. 合并前检查实际变更文件是否符合任务范围。

特别注意以下高冲突文件：

- `Task/my_app/frontend/src/App.tsx`
- `Task/my_app/frontend/src/i18n.tsx`
- MyApp 后端任务注册或统一入口文件
- Portal 的 `App.tsx`、i18n 和配置入口
- 根目录 `AGENTS.md`、架构文档
- Nginx、启动脚本和生产部署配置

---

## 9. 标准开发流程

```text
人类负责人定义任务
        ↓
确认项目边界和接口依赖
        ↓
创建 Git Worktree + Branch
        ↓
登记文件所有权
        ↓
OMP Agent 分析任务并列出计划
        ↓
负责人确认计划
        ↓
Agent 实现代码
        ↓
Agent 执行项目测试
        ↓
QA Agent 只读审查
        ↓
修复问题
        ↓
负责人合并 PR / 分支
        ↓
集成测试
        ↓
更新文档和任务状态
```

### 每个 Agent 的完成标准

任务不能仅以“代码已修改”作为完成条件，必须提供：

- 修改文件清单
- 实现摘要
- 测试命令和结果
- 未解决问题
- 接口或配置变更
- 是否需要其他项目配合
- 建议的合并方式

---

## 10. WhatsApp Bot 专项落地步骤

### 阶段 A：安全与结构审查

由 WhatsApp Bot Agent 只读检查：

- 项目入口和启动方式
- 消息接入流程
- RAG 检索流程
- 工具调用路由
- API 依赖
- 配置文件
- 日志和错误处理
- 测试覆盖情况

重点检查配置文件中是否包含：

- API Key
- WhatsApp Token
- 账号凭据
- Session / Cookie
- 数据库连接密码

敏感配置应移入环境变量或本地 secrets 文件，并确保不提交到 Git。

### 阶段 B：建立稳定边界

将 Bot 内部模块划分为：

```text
WhatsApp Adapter
    ↓
Message Handler
    ↓
Intent / Tool Router
    ├── Knowledge RAG
    ├── Business API Tools
    └── Fallback / Human Escalation
    ↓
Response Formatter
    ↓
WhatsApp Adapter
```

建议将业务 API 调用封装在独立 Client 层，避免消息处理逻辑直接耦合 MyApp 的内部结构。

### 阶段 C：测试与评测

至少建立以下测试：

- 普通知识问答
- 无答案问题
- 多轮上下文
- 工具调用成功
- 工具调用失败
- API 超时
- 权限不足
- 错误参数
- 中英文问题
- 敏感信息处理

每次修改 RAG 或工具路由后，执行固定评测集，避免只凭人工试问判断质量。

### 阶段 D：独立部署验证

Bot Agent 负责本地或测试环境验证。生产部署、真实 WhatsApp 账号操作和生产凭据变更由负责人审批。

---

## 11. 现有并行编排工具的处理

仓库已有：

```text
Unified_Tools/parallel_orchestrator/
```

建议第一阶段保留现有工具，不立即重写。

使用规则：

- 现有 orchestrator 继续处理它已经支持的批量任务。
- OMP 负责新建的项目级交互开发任务。
- 不允许现有 orchestrator 和 OMP 同时写入同一个 Worktree。
- 如果未来需要统一调度，先定义任务状态、分支命名、日志和结果格式，再考虑整合。

同时检查：

```text
Unified_Tools/
Task/Unified_Tools/
```

确认两处目录是独立用途、历史副本还是重复实现，并在架构文档中明确权威位置。

---

## 12. 分阶段实施计划

### Phase 1：基础设施与规则

- [ ] 检查根目录 `AGENTS.md`
- [ ] 新建 `docs/project-boundaries.md`
- [ ] 新建 `.agent-work/file-ownership.md`
- [ ] 建立 Worktree 命名规范
- [ ] 确认 `master` 是当前任务基线
- [ ] 检查配置文件和 secrets
- [ ] 确认重复工具目录的职责

### Phase 2：三个项目试运行

- [ ] MyApp Backend Agent
- [ ] MyApp Frontend Agent
- [ ] WhatsApp Bot Agent
- [ ] QA Agent 只读审查
- [ ] 建立 MyApp-Bot API 契约
- [ ] 使用独立 Worktree 完成至少一个真实任务
- [ ] 记录冲突和流程问题

### Phase 3：扩大并行范围

- [ ] 加入 Portal Agent
- [ ] 加入 Comsal Agent
- [ ] 将 RPA 任务按业务脚本拆分
- [ ] 建立跨项目集成测试
- [ ] 逐步接入现有 orchestrator 的任务状态

### Phase 4：稳定运行

- [ ] 形成可复用任务模板
- [ ] 建立自动化测试门禁
- [ ] 建立 Agent 变更范围检查
- [ ] 形成定期架构审查机制
- [ ] 根据实际冲突率调整 Agent 数量

---

## 13. 建议的首个试点任务

选择三个互相依赖较少的任务：

**任务 A：MyApp 后端**
- 只读分析指定 API 模块
- 补充测试和接口文档
- 不修改前端

**任务 B：WhatsApp Bot**
- 梳理工具调用链
- 增加 API 超时和错误处理测试
- 不修改 MyApp 后端

**任务 C：MyApp 前端**
- 完成一个明确限定页面的 UI 优化
- 不修改公共路由和全局 i18n，除非提前登记

QA Agent 对三个任务进行只读检查，负责人统一合并。

---

## 14. 最终原则

1. **一个项目一个主要 Agent。**
2. **一个并行任务一个 Worktree。**
3. **一个文件同一时间一个写入者。**
4. **跨项目共享契约，不共享工作目录。**
5. **公共入口文件需要显式锁定和审批。**
6. **QA Agent 默认只读。**
7. **生产配置、凭据和部署由负责人控制。**
8. **先稳定 3 个 Agent，再扩展到 7 个以上。**

最终目标不是让 Agent 数量越多越好，而是让每个 Agent 都拥有清晰的职责、明确的修改边界、可验证的交付标准，以及不会影响其他项目的独立开发环境。
