# _agents —— AI 编码工具规则真源

本目录是工作区所有 AI 编码工具的**规则细则真源**。
入口与总纲是根目录 [AGENTS.md](../AGENTS.md)（项目地图、构建/测试/git 约定、硬性约束、自主执行契约）。

## 目录结构

| 路径 | 内容 | 如何被读到 |
| --- | --- | --- |
| `rules\shell_safe.md` | Shell 命令安全规范（PowerShell/bat）：禁止内联复杂命令、临时脚本规范、编码陷阱等 | `AGENTS.md` 第七节 `@` 导入 + Qoder junction |
| `rules\code_rules.md` | Python 文件生成规范（requirements/MD 伴随、运行计时、向量化查询） | 同上 |
| `rules\my_app.md` | my_app 项目引用不外移的约定 | 同上 |
| `rules\modern_web_guidance.md` | modern-web-guidance 技能的调用约定（运行器选型、环境障碍、与本工作区规范的优先级） | 同上 |
| `rules\execution_efficiency.md` | 执行效率与编排规范（并行批量、命令成本预估、队友验收上限、只读验收优先；2026-11-11 会话耗时实测沉淀） | 同上 |
| `rules\jcodemunch_first.md` | 代码探索优先用 jcodemunch MCP 的工具约定 | **仅 Qoder**（见下「为什么不导入」） |
| `_backup\<日期>\` | 历史快照（`AGENTS.md`、`.gitignore`、`.qoder\rules\*` 的改前完整备份），**不入库**（`.gitignore` 已忽略） | — |

## 各工具如何接入同一真源

| 工具 | 接入方式 | 实际读到的规则 |
| --- | --- | --- |
| **Claude Code** | 2.1.277+ **原生读 `AGENTS.md`**，根 `AGENTS.md` 用 `@_agents/rules/*.md` 导入细则 | 全套（除 jcodemunch） |
| **Qoder** | `.qoder\rules\` 是指向本目录的 **junction**（含 `trigger: always_on` frontmatter） | 全套 |
| **Cursor / Trae / ZCode / Agnes** | 读根 `AGENTS.md`（Cursor 与 Trae 官方都支持 `AGENTS.md`） | 全套（除 jcodemunch） |
| **WorkBuddy / QoderCN** | 盘点（2026-11-02）确认无独立规则文件，仅 memory / mcp.json 等运行时数据 | 无 |

### ⚠️ 不要再建 `.claude\CLAUDE.md`

2026-11-02 曾按「老办法」建过 `.claude\CLAUDE.md` 内含 `@../AGENTS.md`，**当天就撤销了**。

原因（[官方文档 memory](https://code.claude.com/docs/en/memory) 原文）：

> **Count, so Claude reads them instead of `AGENTS.md`**: a `CLAUDE.md`, `.claude/CLAUDE.md`, or
> `CLAUDE.local.md` in your working directory or any directory above it

只要工作目录或其**任一上级目录**存在这三个文件名之一，Claude Code 就**只读 CLAUDE.md 系列，完全不读任何 `AGENTS.md`**（包括子目录里懒加载的）。后果：

- `Task\my_app\AGENTS.md`（215 行硬约束：功能页三处同步 / 任务登记 `TASK_SPECS` / UI 统一组件 / 改数据层前必读）**整份丢失**；
- 在 `Task\my_app` 启动时 `@../AGENTS.md` 解析到 cwd 之外，属 external import，还要弹授权框。

`.claude\rules\` 下的文件**不算**数（文档列在「Don't count」一侧），所以真要放 Claude 专属规则，放那里，不要建 `CLAUDE.md`。

### 为什么不导入 `jcodemunch_first.md`

那条规则要求「代码探索优先用 jcodemunch MCP，**不要**用 Read/Grep/Glob/Bash 做代码导航」。但该 MCP 目前**只配在 Qoder**（`.qoder-cn\mcp.json`，包 `jcodemunch-mcp` 已装在系统 Python）：

```
顶层 mcpServers: []          ← Claude Code 用户级
D:/01_RPA -> (无)            ← Claude Code 项目级
```

无条件注入会让 Claude Code / Cursor 这类没有该 MCP 的环境**放弃代码探索**却无替代手段。等哪天它在所有工具里都配好了，再把这一行加进 `AGENTS.md` 第七节。

## 新机器初始化（两件都不随 git 分发）

```powershell
node scripts\setup-git-hooks.mjs           # 一次装齐：core.hooksPath + .qoder\rules junction
node scripts\setup-git-hooks.mjs --check   # 查状态，退出码非 0 就是没装好
```

`core.hooksPath` 与 junction 都**不入库**（前者写在 `.git\config`，后者因 `.qoder\` 整目录被 `.gitignore:129` 挡住）。两者都是「每台机器做一次，不做就静默失效」的同一类问题，所以并进同一个脚本。

> 注：`AGENTS.md` 第七节的 `@` 导入**不依赖 junction** —— 即使 junction 没建，Claude Code / Cursor 仍能通过 `AGENTS.md` 读到全套细则；受影响的只有 Qoder。

## 修改约定

- 改规则正文：直接改本目录 `rules\` 下的文件；**不要**改 `.qoder\rules\` 链接路径下的内容（那是同一份文件）。
- **不要**在 `AGENTS.md` 里重复细则内容，只放 `@` 导入行。
- 改项目级约定（构建/测试/git/目录说明）：改根 `AGENTS.md`。
- 重大结构调整在根 `AGENTS.md` 或本文件追加带日期的说明，不留裸变更。
