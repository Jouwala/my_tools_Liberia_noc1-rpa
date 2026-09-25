# 07 development.md —— 开发方式、命令和回归清单

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\development.md`

## 一、环境前置

| 项 | 要求 |
| --- | --- |
| Node.js | 18+ |
| 端口 | **9267**（本项目 dev）；7038 / 7090 已被 my_app 占用，**不可复用** |
| 网络 | 本地 dev 需能访问 `192.168.100.19`（生产后端） |

## 二、命令

```powershell
npm install
npm run dev        # http://localhost:9267（predev 会先拉起 wa-service）
npm run build      # 产物输出 dist/
npm run lint       # = tsc --noEmit  —— 改完必跑
npm run preview    # 预览构建产物
npm run clean      # 删除 dist / server.js
```

- 本地 dev 已配置 `/api` 代理到 `http://192.168.100.19`，任务调度部件可直连生产后端。
- 部署到子路径需在 `vite.config.ts` 设 `base` **后重新构建**。

### 仓库整洁度（2026-09-25 起有机器守卫）

背景：AGENTS.md 第四节第 7 条「探针落 `TMP\` 并自清」失效过三次，2026-09-24 审计发现门户 506 个跟踪文件里 347 个是探针/转储/快照。现在由三件东西兜底：

| 机制 | 命令 | 作用 |
| --- | --- | --- |
| 提交前拦截 | `.git\hooks\pre-commit`（工作区根，随 git 生效） | 提交时自动跑 audit，探针/快照/日志入库就拦下 |
| 手工体检 | `npm run check:clean` | 随时自查版本库有没有混入噪声文件 |
| TMP 清理 | `npm run tmp:clean` / `npm run tmp:clean:apply` | 报告 / 真删 `TMP\` 里早于 7 天的积压（脚本加 `--days=N` 可调） |

判断逻辑全在 `scripts\check-cleanliness.mjs`，钩子与手工命令是同一份代码，不会分叉。它管**已跟踪文件**（不该入库却入了库的），`.gitignore` 管**未跟踪文件**（防止新增入库），两者互补。

- 被钩子拦下但确实要提交：`git commit --no-verify`（先确认文件真的是源码）。
- `_*` 前缀的真源码（如 `src\`、`server\` 下的下划线文件）在脚本里有豁免清单，新增类似文件时记得同步该清单。

## 三、代码结构约定

### 状态中枢只有一个

`src\App.tsx` 持有全部状态（看板、分组、鉴权、视图、搜索排序、弹窗开关、持久化）。**没有引入状态库**，组件靠 props 拿数据和回调。

### 新增一个弹窗：必须改三处

以 `DesignGuideModal` / `DocsIndexModal` 为模板：

1. **`src\App.tsx`**
   ```tsx
   const [isXxxModalOpen, setIsXxxModalOpen] = useState(false);
   // …
   <Navbar onOpenXxxModal={() => setIsXxxModalOpen(true)} … />
   // …
   <XxxModal isOpen={isXxxModalOpen} onClose={() => setIsXxxModalOpen(false)} />
   ```
2. **`src\components\Navbar.tsx`**：`NavbarProps` 加 `onOpenXxxModal: () => void`，并在**桌面端与移动端两处**都加入口（漏一处 = 手机上找不到）。
3. **`src\i18n.tsx`**：`zh` 与 `en` **两份**字典都加文案键。

### 组件骨架

```tsx
import React from 'react';
import { useI18n } from '../i18n';

interface XxxModalProps { isOpen: boolean; onClose: () => void; }

export const XxxModal: React.FC<XxxModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* 头部 / 内容 / 底部 */}
      </div>
    </div>
  );
};
```

### 图标

用 `DynamicIcon` 传 lucide 名称字符串：

```tsx
import { DynamicIcon } from './DynamicIcon';
<DynamicIcon name="ListChecks" className="w-5 h-5" />
```

找不到的图标名会**静默回退** `LayoutGrid`——传错名字不会报错，只会显示错图标，改完要肉眼确认。

### 异步请求的竞态

用序号作废模式（见 `fetchQcDrill`）：

```ts
var seq = ++qcDrillSeq;
// …fetch…
.then((data) => { if (seq !== qcDrillSeq) return; /* 过期响应丢弃 */ });
// 关闭弹窗时：qcDrillSeq++;
```

## 四、改代码前的纪律

1. **读 `src\config.ts` 顶部注释**——API 前缀 `/uniplam/api` 的坑，写错直接 405。
2. **文案改两份字典**（`zh` 第 20 行起、`en` 第 516 行起）。
3. **不硬编码 IP**，主机只在 `config.ts`。
4. **不写敏感值**；不提交 `auth-data\`、`portal-default.json`。
5. **中文注释。**
6. **改大文件前建 `_bak_<日期>_<说明>` 快照**：`App.tsx`（43KB）、`i18n.tsx`（117KB）、`MsPortal\index.html`（48KB）。本项目既有习惯，如 `index.html_bak_20260922_QC展示全面改版前`。
7. **探针文件放 `TMP\`**，不要污染根目录（根目录已有大量 `_*.txt` / `_qc*.txt` 历史残留）。
8. **只改样式就只改样式**，别搭车改数据口径。
9. **提交信息带影响面前缀**：`feat(portal): …`、`fix(assets): …`、`chore: …`。

## 五、回归清单

改完逐项验证，**打勾前请真的跑过**。

### 必跑（任何改动）

- [ ] `npm run lint`（`tsc --noEmit`）通过
- [ ] `npm run build` 通过
- [ ] `npm run dev` 后刷新页面，改动**实际可见**
- [ ] `git status --porcelain` 复查：没有 `dist/`、`node_modules/`、`auth-data/`、`portal-default.json`、`*.log`、探针文件混入
- [ ] `npm run check:clean` 通过（探针/快照/日志没被 git 跟踪；pre-commit 钩子也会自动拦）

### 文案 / i18n

- [ ] **中文界面**文案正确
- [ ] **切到英文**，所有新文案正常显示，**没有出现 `xxx.yyy` 形式的 key 原文**
- [ ] 看板业务数据（名称/分类/部门）仍是原值，**没有被误翻译**

### 视觉

- [ ] **深色主题**下正常
- [ ] **浅色主题**下正常（只验一套 = 漏测一半）
- [ ] 新弹窗：遮罩、圆角、阴影、关闭按钮、点击遮罩关闭都正常
- [ ] 窄屏 / 移动端不塌，导航入口在移动端也能找到

### 弹窗接线（新增弹窗时）

- [ ] `App.tsx` 状态、渲染、回调三处都加了
- [ ] `Navbar.tsx` **桌面端与移动端两个入口**都加了
- [ ] 打开 / 关闭 / 反复开关不残留状态

### 接口相关

- [ ] 请求走的是 **`/uniplam/api/*`**，不是 `/api/*`（否则 405）
- [ ] 在浏览器 Network 面板确认请求真的成功（不是靠界面"看起来对"）
- [ ] 请求失败时有降级或错误提示，**不是白屏**
- [ ] 快速连续操作 / 关闭弹窗时，**过期响应没有写回界面**

### 数据相关

- [ ] 改了初值数据时：清掉 `localStorage` 的 `liberia_noc_dashboards_v3`，确认「恢复初始默认看板」后新数据出现
- [ ] 环境切换后所有看板链接都跟着变
- [ ] QC 面板：数字**居中**、标题与副行**左对齐**、取不到显示 `—` 而非 `0`、失败时不留旧数字
- [ ] 时钟 / 倒计时**不抖动**（定宽、补零）

### 大文件改动（`App.tsx` / `i18n.tsx` / `MsPortal\index.html`）

- [ ] 建了 `_bak_<日期>_<说明>` 快照
- [ ] 改动范围最小化，没有误伤相邻代码块
- [ ] 对照 `MsPortal\` 三份专项记录（QC 优化、三列对齐、配色对齐），确认没有回退已定结论

## 六、常见陷阱

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| API 用 `/api` | 命中 my_app，POST 回 405 | 用 `PORTAL_API`（`/uniplam/api`） |
| 只加中文 i18n 键 | 英文界面显示 key 原文 | `zh` 与 `en` 都加 |
| 只加桌面端入口 | 手机上找不到功能 | `Navbar` 两处都加 |
| 图标名写错 | 静默回退 `LayoutGrid`，不报错 | 改完肉眼确认图标 |
| 硬编码 IP | 换机器要全局搜替换 | 只在 `config.ts` 定义主机 |
| 看板存绝对 URL | 换环境时历史数据失效 | 只存相对路径 `rel` |
| 数字取不到显示 0 | 运维误判为"已清空" | 显示 `—` |
| 整卡加渐变 | "贴纸感"，数据可信度下降 | 纯底 + 细边框 + 柔和阴影 |
| 整卡 `text-center` | 标题与口径被挪走，超范围改动 | 只让数字居中 |
| 用 interval 累加做刷新 | 进页面时机不对要等一整周期 | 墙上时钟对齐网格 |
| 未作废在途请求 | 关掉弹窗后又被写回 | 序号作废模式 |
| 提交 `auth-data/` | 泄露加盐密码哈希 | 已在 `.gitignore`，别绕开 |
| 探针写在根目录 | 历史残留已 76+ 个 | 放 `TMP\` |

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 本地运行 / 部署（含 nginx 片段） | `README.md` |
| 架构与数据流 | `architecture.md` |
| 视觉规则 | `DESIGN.md` |
| 组件 API | `component-api.md` |
| AI 上手须知 | `AGENTS.md` |
| 全域开发规范 | `D:\01_RPA\development.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |

> **工具负责整理，人与 AI 负责协作执行。**
