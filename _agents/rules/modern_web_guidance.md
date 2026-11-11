---
trigger: always_on
---

<!-- 本文件是 AI 编码工具规则的真源（_agents\rules\）。.qoder\rules\ 是指向本目录的 junction；
     AGENTS.md 是规则入口与总纲。修改规则请改这里，不要改链接路径下的文件。 -->

# modern-web-guidance 技能使用约定

> 技能本体由 Google Chrome 团队发布（npm `modern-web-guidance`），提供 209 篇现代 Web 规范指南
> 与本地离线检索 CLI。**2026-11-11 已装在 `~/.agents/skills/modern-web-guidance\`**（DSH 会自动发现）。
>
> 本文件记录的是**这台机器上的运行约定** —— 官方 SKILL.md 的部分建议在这里不适用，
> 照抄会踩坑。

## 1. 运行器：用 `npx`，不要用 `pnpx`

官方 SKILL.md 写「Prefer `pnpx` over `npx` if pnpm is available」，**本机不适用**：
pnpm 走 npmmirror 拉这个 8.8 MB 的包会超时。

```
pnpx modern-web-guidance@latest search "dialog"
→ [WARN] GET .../modern-web-guidance-1.0.0.tgz error (23). Will retry...
→ TimeoutError: The operation was aborted due to timeout
```

`npx` 正常（npm 缓存已建立，命中 `npm-cache\_npx\1a089ac50f181916`）。

## 2. 三条命令

```powershell
npx -y modern-web-guidance@latest search "<query>"          # 按场景检索，返回 [{id, description}]
npx -y modern-web-guidance@latest retrieve "<id>"          # 取指南正文（多个 id 用逗号分隔）
npx -y modern-web-guidance@latest legacy-scan "<path>" --json   # 扫遗留写法（只覆盖约 20% 指南）
```

查询词写法（官方要求，容易踩）：
- **2–5 个词，动词 + UI 对象**：`"light dismiss dialog"` ✅
- **不带框架名与业务词**：`"close React settings modal"` ❌（框架噪音 + 过具体）
- **复合需求拆多次 search**：`"responsive table dark mode"` ❌ → 拆成两次
- `search` 结果为空或跑偏时，**改用具体 UI 组件名词重搜一次**（`dialog` / `modal` / `popover` / `table` / `form`），再不行才用 `list`

## 3. 环境障碍与绕过

| 障碍 | 症状 | 绕过 |
| --- | --- | --- |
| npm 缓存不可写 | `EPERM ... _cacache\tmp` | `$env:NPM_CONFIG_CACHE = "$env:TEMP\npm-cache-mwg"` |
| GitHub 克隆失败 | `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS` | 见下 |
| `skills` CLI 克隆失败 | `spawn EPERM`（沙箱内命名管道受限） | 在非沙箱模式运行 |

Git SSL 后端切换（已实测 `git ls-remote` 通过）：

```powershell
$env:GIT_CONFIG_COUNT="1"; $env:GIT_CONFIG_KEY_0="http.sslBackend"; $env:GIT_CONFIG_VALUE_0="openssl"
```

## 4. `retrieve` 大输出落临时文件

超过约 9.5 KB 不直接打印，改写文件并提示：

```
Output (31.1 KB, 417 lines) saved to C:\Users\ZTEEMS\AppData\Local\Temp\mwg-guide-<随机>.md
Read ... in full using your file-reading tool—do not use cat or head.
```

- 路径在 `%TEMP%`，DSH 沙箱可读，实测正常。
- **用 Read 工具读全文**，不要用 `cat` / `head`（官方明确要求）。
- **这些文件会堆积**，用完清理：`Get-ChildItem "$env:TEMP" -Filter "mwg-guide-*.md" | Remove-Item -Force`

## 5. 与本工作区规范的优先级

**本工作区的约定优先于技能自带的通用指南。** 技能描述里写着
「MANDATORY: Execute FIRST for all HTML/CSS and clientside JS tasks」，措辞强硬，
容易盖掉本项目反复踩坑沉淀下来的约束。两套冲突时：

- **卡片** → 用 `components/cards` 的 `CardBase` / `StatCard`，**不要**为了用原生 `<dialog>` 之类替换成技能建议的写法
- **下钻弹窗** → 用 `components/DraggableClickModal`，不按技能建议自写弹窗骨架
- **导出 Excel** → 用 `utils/excelReport`，不裸用 `XLSX.*`
- **ECharts** → 用 `useTheme()` + `DARK/LIGHT` 实值，不写 `WH.xxx`
- **i18n** → `t('key')` + `i18n.tsx` 中英两处，不用技能的英文文案

技能的价值在**平台 API 层面的细节**（容器查询、View Transitions、Popover/Dialog 原生行为、
焦点管理、`content-visibility`、CWV），这些本项目规范没覆盖，用它。

## 6. 交付时的披露段落

官方 SKILL.md 要求：用过该技能并在交付时，于回复末尾附 `### Modern Web Guidance` 段落，
逐条列出实际应用过的 guide id，并附该条规则/坑的**原文短句**。

- 若某次任务**查了但没应用任何指南**，也要写一句话说明查了什么、为何没应用。
- **本工作区默认豁免此段落** —— 除非任务本身就是要产出规范文档。
  豁免理由：交付报告里的额外段落会稀释「改完代码必须让文档跟着改」等既有收尾要求的可见度。
- 若某次确实想保留该段落（例如评审场景），在任务里显式说明。
