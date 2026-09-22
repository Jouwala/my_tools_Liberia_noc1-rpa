# 08 component-api.md —— 组件索引

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> **本文只做索引**（哪个组件在哪、干什么），**不复制 props 签名**——API 细节以源码为准，避免文档漂移。
> 权威正文：门户 `liberia-noc_soc-数据看板统一门户\docs\component-api.md`；my_app `Task\my_app\component-api.md`。

## 一、跨项目组件总览

| 项目 | 组件位置 | 数量 | 技术 |
| --- | --- | --- | --- |
| 统一门户 | `liberia-noc_soc-数据看板统一门户\src\components\` | 21 个 `.tsx` | React 19 + Tailwind v4 + lucide-react |
| 门户页面级 | `...\src\App.tsx` | 状态中枢 | 非组件化，状态与持久化都在这 |
| my_app 前端 | `Task\my_app\frontend\src\` | 见 my_app 索引 | React + Vite |
| 门户静态页 | `...\MsPortal\` | `index.html` / `viewer.html` | 原生 HTML（复刻参考与查看器） |

## 二、门户组件索引（`src\components\`）

> 全部为 `React.FC`，命名导出。props 详情见各文件顶部 `interface XxxProps`。

### 导航与框架

| 组件 | 职责 |
| --- | --- |
| `Navbar.tsx` | 顶栏：视图切换、搜索、主题、语言、环境配置、各类弹窗入口（桌面 + 移动端两套） |
| `AnnouncementBanner.tsx` | 顶部公告横幅（深浅双模适配） |
| `FilterBar.tsx` | 筛选栏：分类 / 部门 / 标签 / 平台等过滤与排序 |
| `QuickStatsBar.tsx` | 快捷统计条 |

### 看板视图（三种视图各一个）

| 组件 | 职责 |
| --- | --- |
| `DashboardCard.tsx` | **卡片网格视图**的单卡（含主题色，teal 为自研系统色） |
| `DashboardListView.tsx` | **高密清单视图** |
| `DashboardMatrixView.tsx` | **业务分类矩阵视图** |

### 看板操作弹窗 / 抽屉

| 组件 | 职责 |
| --- | --- |
| `DashboardModal.tsx` | 看板**新增/编辑**（改名称、URL、分类、部门、标签等） |
| `PreviewDrawer.tsx` | 右侧 iframe 预览抽屉（不跳走就能看） |
| `QRCodeModal.tsx` | 生成看板二维码（手机同网段扫码打开） |
| `EndpointSettingsModal.tsx` | **环境配置**：批量替换主机/域名（IP、nginx、vite 直连预设） |
| `GroupManagerModal.tsx` | 分组管理（导出 `GroupOpFeedback` 反馈类型） |

### 鉴权与用户

| 组件 | 职责 |
| --- | --- |
| `LoginView.tsx` | 登录页 |
| `AuthContext.tsx`（在 `src\auth\`） | 鉴权上下文 |
| `ChangePasswordModal.tsx` | 修改密码 |
| `PasswordInput.tsx` | 带显隐切换的密码输入框 |
| `UserManagementModal.tsx` | 用户管理（门户内最大的组件之一，44KB） |
| `AuthSwitchModal.tsx` | 鉴权开关切换 |

### 数据与状态部件

| 组件 | 职责 |
| --- | --- |
| `TaskSyncWidget.tsx` | **实时任务调度部件**：每 60s 拉任务状态，接口离线降级为静态快照 |
| `WhatsAppTasksView.tsx` | WhatsApp 任务视图 |

### 工具组件

| 组件 | 职责 |
| --- | --- |
| `DynamicIcon.tsx` | 按**图标名字符串**动态渲染 lucide 图标，找不到回退 `LayoutGrid`。**新增图标只需传名字，不用改这个文件** |
| `DesignGuideModal.tsx` | 设计指南弹窗（门户视觉规范的可视化呈现） |
| `DocsIndexModal.tsx` | **文档索引弹窗**：本工作区 8 份体系文档的两列导航 |

### 使用约定

- **图标**：一律 `import { DynamicIcon }`，传 lucide 名称；不要直接 `import * as Icons from 'lucide-react'` 到处用。
- **文案**：一律走 `useI18n()` 的 `t('key')`，键写在 `src\i18n.tsx` 的 `zh` 与 `en` **两份**字典里。
- **主题色**：用 Tailwind 语义类 + `dark:` 变体，不要写死十六进制。
- **弹窗模式**：统一 `isOpen` + `onClose` 两 prop，外层用 `fixed inset-0 z-50` + 遮罩，面板用 `spatial-modal-surface`。新加弹窗照抄 `DesignGuideModal.tsx` 的骨架。

## 三、门户静态页（`MsPortal\`）

| 文件 | 职责 |
| --- | --- |
| `index.html`（48KB） | 早期复刻版门户单页，含 QC 面板等大量内联实现；`_bak_*` 为各次改版前快照 |
| `viewer.html` | 看板查看器页（含权限收口） |
| `tailwind.src.css` | Tailwind 源样式 |

> `MsPortal\` 下有大量 `_*.txt` / `_qc*.txt` 探针与切片文件，属过程产物，**不是** API 文档。

## 四、my_app 前端组件

见 `Task\my_app\component-api.md`。目录为 `Task\my_app\frontend\src\`（`pages\` 页面组件 + `components\` 通用组件），逐页功能说明在 `Task\my_app\docs\manual\11-feature-guide.md`。

## 五、如何自己查（比读文档更可靠）

```powershell
# 门户：列出所有组件及其导出
Get-ChildItem "liberia-noc_soc-数据看板统一门户\src\components" -Filter *.tsx |
  Where-Object { $_.Name -notlike "*_bak*" } |
  ForEach-Object { $_.Name; Select-String -Path $_.FullName -Pattern "^export (const|function|interface)" }

# 查某个组件被谁用了
Select-String -Path "liberia-noc_soc-数据看板统一门户\src\*.tsx","liberia-noc_soc-数据看板统一门户\src\components\*.tsx" -Pattern "DynamicIcon"
```

## 六、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 门户组件权威说明 | `liberia-noc_soc-数据看板统一门户\docs\component-api.md` |
| my_app 组件权威说明 | `Task\my_app\component-api.md` |
| 视觉规则 | `DESIGN.md`、`liberia-noc_soc-数据看板统一门户\DESIGN.md` |
| 使用者视角的功能说明 | `user-guide.md` |
| 整体架构 | `architecture.md` |

> **工具负责整理，人与 AI 负责协作执行。**
