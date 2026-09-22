# 08 component-api.md —— 组件 API

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> **基准快照，不是契约。** props 会演进，**以源码为准**——本文用于快速定位"哪个组件干什么、大概收什么"。
> 全部组件命名导出，均为 `React.FC`。

## 一、总览

| 分类 | 组件 |
| --- | --- |
| 导航与框架 | `Navbar`、`AnnouncementBanner`、`FilterBar`、`QuickStatsBar` |
| 看板视图 | `DashboardCard`、`DashboardListView`、`DashboardMatrixView` |
| 看板操作 | `DashboardModal`、`PreviewDrawer`、`QRCodeModal`、`EndpointSettingsModal`、`GroupManagerModal` |
| 鉴权与用户 | `LoginView`、`ChangePasswordModal`、`PasswordInput`、`UserManagementModal`、`AuthSwitchModal` |
| 数据与状态 | `TaskSyncWidget`、`WhatsAppTasksView` |
| 工具 | `DynamicIcon`、`DesignGuideModal`、`DocsIndexModal` |

路径统一为 `src\components\<名字>.tsx`（`AuthContext` 例外，在 `src\auth\`）。

## 二、导航与框架

### `Navbar`

顶栏，所有功能入口（**桌面端与移动端两套，新增入口两处都要加**）。

```ts
interface NavbarProps {
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onOpenAddModal: () => void;
  onOpenEnvironmentModal: () => void;
  onOpenDesignGuideModal: () => void;
  onOpenDocsIndexModal: () => void;      // 文档索引
  onExportJson: () => void;
  onImportJson: () => void;
  onResetDefaults: () => void;
  canSaveDefault: boolean;
  onSaveDefault: () => void;
  user: AuthUser;
  onChangePassword: () => void;
  onOpenUserManagement: () => void;
  onOpenAuthSwitch: () => void;
  onLogout: () => void;
  // 视图/搜索等回调（见源码 NavbarProps 完整定义）
}
```

> **纯回调组件**：自己不管状态，全部由 `App.tsx` 通过 props 注入。

### `AnnouncementBanner`

顶部公告横幅，**无 props**。注意深浅双模适配。

### `FilterBar`

筛选栏：分组、分类、平台、收藏、隐藏、搜索、排序、视图模式、布局编辑。

```ts
interface FilterBarProps {
  groups: string[];
  labelOf: (name: string) => string;
  onManageGroups: () => void;
  selectedCategory: CategoryType;
  onSelectCategory: (cat: CategoryType) => void;
  selectedPlatform: 'all' | PlatformType;
  onSelectPlatform: (platform: 'all' | PlatformType) => void;
  onlyFavorites: boolean;
  onToggleOnlyFavorites: () => void;
  showHidden: boolean;
  onToggleShowHidden: () => void;
  hiddenCount: number;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  sortOption: SortOption;
  onSortChange: (sort: SortOption) => void;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  isLayoutEditing: boolean;
  onToggleLayoutEditing: () => void;
  onResetLayout: () => void;
  totalFilteredCount: number;
}
```

### `QuickStatsBar`

快捷统计条。props 见源码 `QuickStatsBarProps`。

## 三、看板视图

三个视图组件**职责对称**：收 `DashboardItem[]` + 一组操作回调，不持有数据。

### `DashboardCard` —— 卡片网格视图的单卡

```ts
interface DashboardCardProps {
  dashboard: DashboardItem;
  onOpen: (d: DashboardItem) => void;
  onPreview: (d: DashboardItem) => void;
  onShowQR: (d: DashboardItem) => void;
  onToggleFavorite: (id: string) => void;
  onToggleHidden: (id: string) => void;
  onEdit: (d: DashboardItem) => void;
  onDelete: (id: string) => void;
  isLayoutEditing?: boolean;
}
```

### `DashboardListView` / `DashboardMatrixView`

高密清单视图 / 业务分类矩阵视图。props 均为 `DashboardListViewProps` / `DashboardMatrixViewProps`（见源码），形态与 `DashboardCard` 一致：数据 + 操作回调。

## 四、看板操作

### `DashboardModal` —— 新增/编辑看板

```ts
interface DashboardModalProps { /* 见源码第 28 行 */ }
```

管名称、URL、分类、部门、标签、主题色、平台等字段的编辑。

### `PreviewDrawer` —— 右侧预览抽屉

iframe 内嵌打开看板，不离开门户。props 见 `PreviewDrawerProps`。

### `QRCodeModal` —— 二维码

```ts
interface QRCodeModalProps { dashboard: DashboardItem | null; onClose: () => void; }
```

> 用 `dashboard`（可为 null）而非 `isOpen` 控制显隐——与其它弹窗的 `isOpen` 模式不同，注意别照抄错。

### `EndpointSettingsModal` —— 环境配置

```ts
interface EndpointSettingsModalProps { isOpen: boolean; onClose: () => void; }
```

批量替换主机/域名（生产 nginx、vite 7090 直连、本机调试预设 + 自定义）。

### `GroupManagerModal` —— 分组管理

```ts
export interface GroupOpFeedback { /* 操作反馈类型，供调用方展示结果 */ }
interface GroupManagerModalProps { isOpen: boolean; onClose: () => void; /* … */ }
```

## 五、鉴权与用户

### `LoginView`

登录页，**无 props**。

### `PasswordInput` —— 带显隐切换的密码框

```ts
type PasswordInputProps =
  Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> & {
    toggleId?: string;   // 眼睛按钮的 aria-label / data-testid 后缀，便于端到端脚本定位
  };
```

> **`className` 建议自带 `pr-10`**，给右侧眼睛按钮留空间。
> 服务端只存 scrypt 加盐哈希，**任何地方都不存在明文密码**；这里的"显示"仅作用于当前输入框。

### `ChangePasswordModal` / `UserManagementModal`

```ts
interface ChangePasswordModalProps { isOpen: boolean; onClose: () => void; }
interface UserManagementModalProps { isOpen: boolean; onClose: () => void; /* … */ }
```

`UserManagementModal` 是门户最大组件（44KB），内部还有 `AccessRequest`、`StorageInfo` 两个接口类型。

### `AuthSwitchModal` —— 鉴权开关

```ts
interface AuthSwitchModalProps { isOpen: boolean; onClose: () => void; }

// 内部状态模型
interface AuthSwitchStatus {
  authEnabled: boolean;
  mode: 'enforced' | 'bypass';
  source: 'env' | 'file' | 'default' | 'guard';
  env: string;
  envOverride: boolean;
  reason: string | null;
  canDisable: boolean;
  canEnable: boolean;
  realLogin: boolean;
  updatedAt: string | null;
  updatedBy: string | null;
}
```

依赖 `useAuth()` 的 `apiFetch` / `refreshAuthMode` / `realLogin`。背景见 `D:\01_RPA\AUTH_SWITCH.md`。

## 六、数据与状态部件

### `TaskSyncWidget`

**无 props**，自管理。每 60s 拉任务状态，离线降级为静态快照。

```ts
interface ApiTaskRun { success: boolean; started_at?: string; elapsed_seconds?: number; }
interface ApiTask {
  task_id: string; name?: string; name_en?: string; name_zh?: string;
  category?: string; current_cron?: string; enabled?: boolean;
  running?: boolean; recent_runs?: ApiTaskRun[];
}
interface TaskItem {   // 内部归一化后的模型
  id: string; name: string; category: string; cron: string;
  enabled: boolean; running: boolean;
  lastSuccess: boolean | null; lastElapsed: number | null;
}
```

> 注意 `ApiTask` 是**接口模型**、`TaskItem` 是**视图模型**，二者分离——接口字段变了只改映射，不动渲染。

### `WhatsAppTasksView`

WhatsApp 任务视图，功能较独立（17KB）。

## 七、工具组件

### `DynamicIcon` —— 动态图标

```ts
interface DynamicIconProps { name: string; className?: string; size?: number; }
```

按**名字符串**从 lucide-react 取图标，取不到回退 `LayoutGrid`。

```tsx
<DynamicIcon name="ListChecks" className="w-5 h-5" />
```

> **传错名字不报错**，只会显示错图标——改完要肉眼确认。

### `DesignGuideModal` —— 设计指南

```ts
interface DesignGuideModalProps { isOpen: boolean; onClose: () => void; }
```

门户视觉规范的可视化呈现，文案键 `guide.*`（`i18n.tsx` 第 311 行起）。

### `DocsIndexModal` —— 文档索引

```ts
interface DocsIndexModalProps { isOpen: boolean; onClose: () => void; }
```

本 8 份体系文档的导航页（两列、编号、图标、说明）。

## 八、弹窗统一约定

除 `QRCodeModal`（用 `dashboard`）外，所有弹窗均为：

```ts
{ isOpen: boolean; onClose: () => void }
```

- `isOpen` 为 falsy 时组件 `return null`；
- 遮罩 `fixed inset-0 z-50 … bg-black/60 backdrop-blur-sm animate-fadeIn`；
- 面板 `spatial-modal-surface bg-white dark:bg-slate-900 … rounded-2xl shadow-2xl`；
- 点击遮罩关闭 + 明确关闭按钮。

**新增弹窗请照抄 `DesignGuideModal.tsx`**，并同时改 `App.tsx` / `Navbar.tsx`（桌面+移动两端）/ `i18n.tsx`（`zh`+`en`）三处。

## 九、自己查（比读文档可靠）

```powershell
cd "D:\01_RPA\liberia-noc_soc-数据看板统一门户"

# 列出所有组件及其导出
Get-ChildItem src\components -Filter *.tsx | Where-Object { $_.Name -notlike "*_bak*" } |
  ForEach-Object { $_.Name; Select-String -Path $_.FullName -Pattern "^(export )?(const|function|interface|type)" }

# 看某个组件被谁用了
Select-String -Path src\*.tsx,src\components\*.tsx -Pattern "<DynamicIcon"

# 看某组件的完整 props
Get-Content src\components\Navbar.tsx | Select-Object -First 60
```

## 十、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 视觉规则 | `DESIGN.md` |
| 架构与状态管理 | `architecture.md` |
| 开发与回归 | `development.md` |
| AI 上手须知 | `AGENTS.md` |
| 全域组件索引 | `D:\01_RPA\component-api.md` |

> **工具负责整理，人与 AI 负责协作执行。**
