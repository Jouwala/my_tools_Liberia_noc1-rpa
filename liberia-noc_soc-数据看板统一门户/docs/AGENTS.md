# 01 AGENTS.md —— AI 进入本项目首先需要知道的信息

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\AGENTS.md`（工作区级约束，**先读那个**）

## 一、这个项目是什么

**Liberia NOC/SOC 数据看板统一门户**：把 FineBI 决策报表中心与自研系统 my_app（Data Insight MVP）的看板聚合到一个入口，给 NOC/SOC 值班、网优、管理层使用。

**技术栈**：React 19 + Vite 6 + Tailwind CSS v4 + lucide-react + TypeScript；门户自身后端在 `server\`（Express/TS），构建配置在 `vite.config.ts`。

**新会话上手顺序**：本文 → `DESIGN.md` → `project-overview.md` → `architecture.md` → `development.md`。命令与回归清单在 `development.md`。

## 二、硬性约束（违反会直接出问题）

1. **门户 API 必须带 `/uniplam` 前缀。** 用 `PORTAL_API`（来自 `src\config.ts`），**不要**写绝对路径 `/api/...`。写错会命中 nginx 的通用 `location /api/` 打到 my_app 后端 7038，POST 被回 `405 Method Not Allowed`——这正是"其他电脑经 80 端口登录失败"的历史原因。原因全文在 `src\config.ts` 顶部注释。
2. **改文案必须同时改 `src\i18n.tsx` 的 `zh`（第 20 行起）与 `en`（第 516 行起）两份字典。** 只加一份，英文界面会直接显示 key 原文（形如 `qc.updated`）。
3. **主机/域名只改 `src\config.ts`（`DEFAULT_HOST`）。** 其它任何地方不要再出现 IP。看板只存**相对路径 `rel`**，运行时用「主机 + rel」拼完整 URL。
4. **不写敏感值。** 文档与代码里不得出现口令、Token、授权码、账号、密码哈希。`auth-data\` 目录**含加盐密码哈希，已 .gitignore，严禁入库**。
5. **中文注释。** 本项目注释、文档、提交信息全部中文。
6. **数字绝不撒谎。** 取不到数据必须显示 `—`，**绝不显示 `0`**——统计里的 `0` 是"真的一个都没有"，与"没取到"必须能分辨，否则运维会误判成"已清空"。这条在 QC 面板是硬需求。
7. **不要给整张数据卡加渐变。** QC 卡改版已明确去掉整卡渐变（"贴纸感"降低数据可信度），改为纯白/纯深底 + 细边框 + 柔和阴影。
8. **改动前先备份。** 本项目既有习惯是给被改文件留时间戳快照（如 `index.html_bak_20260922_QC卡片改版前`）。改大文件（`App.tsx` 43KB、`i18n.tsx` 117KB、`MsPortal\index.html` 48KB）前先建备份。

## 三、不入库清单

`.gitignore` 已忽略，**不要**为了"备份"而绕开：

| 忽略项 | 原因 |
| --- | --- |
| `node_modules/`、`dist/`、`build/`、`coverage/` | 可重建 |
| `*.log` | 运行日志 |
| `.env*`（保留 `!.env.example`） | 可能含密钥 |
| `portal-default.json` | **运行时**由「保存为默认目录」写入的全局默认看板目录 |
| `auth-data/` | **含加盐密码哈希，严禁入库** |

另有 `.tmp_*.txt` / `_*.txt` / `_qc*.txt` / `tmp_*.txt` 大量过程产物散落在根与 `MsPortal\`——**不要**新增这类文件到仓库，探针请放 `TMP\`。

## 四、关键文件地图

| 文件 | 作用 |
| --- | --- |
| `src\App.tsx`（43KB） | **状态中枢**：看板数组、分组、鉴权、视图模式、所有弹窗开关、localStorage 持久化 |
| `src\config.ts` | **环境单一真相源**：主机、API 前缀（`PORTAL_API`）、入口 URL；优先级 localStorage > `VITE_*` > 硬编码 |
| `src\i18n.tsx`（117KB） | 中英双字典 + `useI18n()`；另有看板业务数据的独立翻译表 |
| `src\components\Navbar.tsx` | 顶栏，所有功能入口（桌面 + 移动两套） |
| `src\components\DynamicIcon.tsx` | 按名字符串渲染 lucide 图标（找不到回退 `LayoutGrid`） |
| `src\data\initialDashboards.ts`（44KB） | 初始看板数据 |
| `server\` | 门户后端：`auth.ts`、`authDb.ts`、`authSwitch.ts` |
| `MsPortal\index.html`（48KB） | 早期复刻版单页（QC 面板等大量内联实现） |
| `vite.config.ts` | 构建配置（含 `base`、代理、门户后端挂载） |

## 五、改代码前的检查清单

- [ ] 读了 `src\config.ts` 顶部注释（API 前缀的坑）
- [ ] 文案改动同时进了 `zh` 与 `en` 两份字典
- [ ] 新组件弹窗照抄 `DesignGuideModal.tsx` 的骨架（`isOpen` + `onClose`、`fixed inset-0 z-50`、`spatial-modal-surface`）
- [ ] 新图标用 `DynamicIcon` 传名称，不新引图标库
- [ ] 没有硬编码 IP
- [ ] 没有提交 `auth-data\`、`portal-default.json`
- [ ] 改了大文件前建了 `_bak_<日期>` 快照

## 六、本项目的 8 份体系文档

| # | 文件 | 内容 |
| --- | --- | --- |
| 01 | `AGENTS.md` | 本文 |
| 02 | `DESIGN.md` | 视觉规则 |
| 03 | `TODO.md` | 当前任务与优先级 |
| 04 | `project-overview.md` | 项目整体说明 |
| 05 | `architecture.md` | 架构与数据流 |
| 06 | `user-guide.md` | 面向使用者的说明 |
| 07 | `development.md` | 开发方式、命令与回归清单 |
| 08 | `component-api.md` | 组件 API |

> 均在 `docs\` 目录下。索引页见门户内「文档索引」入口。

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 工作区总纲 | `D:\01_RPA\AGENTS.md` |
| 功能概览（质量较高） | `README.md` |
| QC 面板优化建议 | `MsPortal\QC面板展示优化建议_20260922.md` |
| 三列对齐方案与实测 | `MsPortal\三列对齐_可行性方案与实测_20260918.md` |
| 配色对齐记录 | `MsPortal\配色对齐VMAX90天看板_可行性结论与实施记录_20260918.md` |
| 商用就绪度检测与整改 | `MsPortal 商用就绪度检测 —— 结论与整改方案.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |

> **工具负责整理，人与 AI 负责协作执行。**
