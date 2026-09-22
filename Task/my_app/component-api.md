# 08 component-api.md —— 组件索引

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\component-api.md`
> **本文是索引，不是契约。** props 会演进，**以源码为准**。

## 一、两端组件概览

| 端 | 位置 | 规模 |
| --- | --- | --- |
| **前端页面** | `frontend\src\pages\` | 60+ 个 `.tsx`（含 `*_bak_*` 备份） |
| **前端通用组件** | `frontend\src\components\` | 8 个 `.tsx` + `cards\` 子目录（卡片统一入口） |
| **前端基础设施** | `frontend\src\*.ts(x)` | `api.ts`、`theme.ts`、`i18n.tsx`、`TaskStatusContext.tsx`、`cache.ts`、`datetime.ts`、`useDataTimestamps.ts`、`helpMarkdown.ts` |
| **后端服务** | `backend\services\` | 业务服务层（各数据源采集与计算） |
| **后端路由** | `backend\routers\` | API 端点 |

> 逐页功能说明（按导航顺序）见 `docs\manual\11-feature-guide.md` —— 那是**页面级**的权威文档。

## 二、通用组件（`frontend\src\components\`）

### 卡片：项目默认组件（⚠️ 新代码必读）

**卡片一律从 `components\cards` 导入，不要直接 `import { Card } from 'antd'`。**

```tsx
// ❌ 不要
import { Card } from 'antd'
<Card size="small" title={<span style={{fontSize:'0.8125rem',fontWeight:600}}>标题</span>} style={cardStyle}>
  <ReactECharts option={opt} />
</Card>

// ✅ 要
import { CardBase, StatCard } from '../components/cards'
<CardBase title="标题">
  <ReactECharts option={opt} />
</CardBase>
```

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `CardBase` | `components\cards\CardBase.tsx` | **皮肤外壳**：任意内容（图表/表格/表单/列表）。支持 `level` 等级染色、`interactive` 悬停、`as="div"` 裸容器 |
| `CardTitle` | `components\cards\CardBase.tsx` | 项目统一卡头文字排版（此前在 12 处各写一份内联 span） |
| barrel | `components\cards\index.ts` | **唯一入口**，页面只从这里导入 |
| `StatCard` | `components\StatCard.tsx` | 数字卡（标题+大数字+图标），经 barrel 转出 |

`CardBase` 关键 props：`title`（传**字符串**自动套统一排版；传 ReactNode 原样保留）、`extra`、`level`（`'default'|'ok'|'warn'|'crit'`）、`interactive`、`as`、`bodyStyle`。

> **卡片皮肤的三层结构**：令牌层（`index.css` 的 `:root`）→ 类规则层（`index.css` 的「卡片层」区块）→ 组件层（`CardBase` 只挂 className，不写样式值）。
> **改卡片外观去令牌层改，不要在组件或页面里写死颜色。**
>
> **两个已踩过的坑**：
> ① `theme.ts` 的 `cardStyle` 是**行内样式**，优先级高于所有 CSS 类 —— 里面只允许放 `var(--wh-*)`，写死具体值会永久锁死该属性（历史 bug：`boxShadow` 写死导致全局卡片皮肤改不动）。
> ② CSS 自定义属性在**声明它的元素**上求值 —— 在卡片上改 `--wh-card-accent` 不会让 `:root` 的 `--wh-card-glow` 重算，故 `.wh-card-lv-*` 里必须重算依赖 accent 的合成值。
>
> **卡片 CSS 契约**（以 `frontend\src\index.css` 为准）：`.wh-card`（官方入口类）、`.wh-card-interactive`、`.wh-card-lv-ok|warn|crit`、`.wh-card-glow`、`.wh-card-head`；令牌 `--wh-card-shadow`（阴影总成）/ `--wh-card-accent` / `-soft` / `-line`。
>
> **收敛进度**：全文约 **173 处** `<Card>`、**143 处** `cardStyle`（40+ 页面）。策略是**新代码走 `CardBase`，存量改到哪页顺手换哪页**，不做一次性批量替换。
> 已收敛：`PacketLossDashboard.tsx`（参考实现）；`MsKpiShared.tsx` / `SpReportBase.tsx` / `SpDetailsReport.tsx` 的页面内联 StatCard。
> ⚠️ **已知重复**：`StatCard` 在上述三个文件里各有一份同名不同签名的页面级实现（用 `label` 而非 `title`），属历史遗留，新增页面**不要再加第四份**。

### 其余通用组件

| 组件 | 职责 |
| --- | --- |
| `DraggableClickModal.tsx` | 可拖拽的点击弹窗（7KB）。**注意**：门户也有同名问题的 QC 弹窗拖拽需求，两端可互相参照 |
| `LegacyToolFrame.tsx` | 遗留工具页容器框架（iframe 包装旧工具） |
| `MapWheelZoomOnClick.tsx` | 「点击后才启用地图滚轮缩放」的行为包装 —— 解决地图嵌在长页面里时滚轮被地图吃掉的问题 |
| `MetricExplain.tsx` | 指标口径解释（悬浮/展开说明这个数字怎么算出来的） |
| `SearchableExportTable.tsx` | 可搜索 + 可导出的表格（导出遵循 `docs\EXCEL_EXPORT_STANDARD.md`） |
| `StatCard.tsx` | 统计卡片（大数字 + 标题 + 副行） |

### 使用约定

- **卡片走 `components\cards`**（见第二节），不要直接 `import { Card } from 'antd'`。
- **主题取值分两层**：DOM 层用 `WH`（CSS 变量，随主题自动切换），**ECharts/canvas 层必须用 `DARK`/`LIGHT` 实值**。详见 `DESIGN.md` 第一节。
- **文案走 `i18n.tsx`**，中英两处都要有。
- **改组件前建 `_bak_<日期>_<说明>` 快照**（本项目既有习惯）。

## 三、前端基础设施（比组件更常用）

| 文件 | 职责 |
| --- | --- |
| `api.ts`（19KB） | **统一的 API 封装**。所有后端调用走这里，不要在各页面裸写 `fetch` |
| `theme.ts` | 设计令牌与 `useTheme()`（`WH` / `DARK` / `LIGHT` / `WH_COLORS` / `LIGHT_COLORS`） |
| `i18n.tsx`（204KB） | 中英双字典。新增文案**两处都要加** |
| `TaskStatusContext.tsx` | 任务状态上下文（跨页面共享任务运行态） |
| `cache.ts` | 前端缓存工具 |
| `datetime.ts` | 时间处理（**时间戳格式化统一走这里**，避免各页面各写一套） |
| `useDataTimestamps.ts` | 数据时间戳 Hook（"更新于"类展示） |
| `helpMarkdown.ts` | 帮助内容 Markdown 处理 |

## 四、页面（`frontend\src\pages\`）—— 按业务域索引

> 每个页面的**功能说明**在 `docs\manual\11-feature-guide.md`；这里只做**定位索引**。

### 数据同步与任务

| 文件 | 说明 |
| --- | --- |
| `DataSync.tsx`（77KB） | 数据同步主页面（最大的页面之一） |
| `TableBrowser.tsx`（34KB） | 数据表浏览 |
| `DataUpload.tsx` | 数据上传 |
| `ArchiveList.tsx` | 归档列表 |
| `datasync\`（子目录） | 同步相关子组件 |

### 告警与故障

| 文件 | 说明 |
| --- | --- |
| `AlarmDashboard.tsx`（40KB） | 告警看板 |
| `AlarmManagement.tsx` | 告警管理 |
| `IncidentOverview.tsx` | 故障概览 |
| `RepeatSiteDown.tsx` | 重复掉站 |
| `IssueFeedback.tsx` | 问题反馈 |

### 工单与可用率

| 文件 | 说明 |
| --- | --- |
| `TTWODashboard.tsx`（36KB） | TT/WO 工单看板 |
| `NurDashboard.tsx`（29KB） | NUR（网络不可用率） |
| `SiteAvailability.tsx`（26KB） | 站点可用率 |

### 网络性能

| 文件 | 说明 |
| --- | --- |
| `PacketLossDashboard.tsx`（35KB） | 丢包看板 |
| `RanCellsKpi.tsx`（28KB） | RAN 小区 KPI |
| `CnKpi.tsx` | CCN KPI |
| `UmeInKpi.tsx`（85KB） | UME IN KPI（**最大的页面**） |
| `IpTrace.tsx` | IP Trace |
| `GISMap.tsx`（34KB） | GIS 地图（含 `gismap\` 子目录） |
| `MapWheelZoomOnClick`（组件） | 地图滚轮缩放行为包装 |

### MS SLA / 合同报表

| 文件 | 说明 |
| --- | --- |
| `MsSlaDashboard.tsx`（32KB） | MS SLA 看板 |
| `MsKpiShared.tsx`（22KB） | MS KPI 共享逻辑 |
| `MsContractKpiReport.tsx`（27KB） | 合同 KPI 报表 |
| `MsWoSLReport.tsx` | WO SLA 报表 |
| `MsNurOnly.tsx` / `MsSlaOnly.tsx` | 单指标页 |
| `SpReportBase.tsx`（38KB） | SP 报表基类 |
| `SpDetailsReport.tsx`（28KB） | SP 明细报表 |
| `SpMaterialSummary.tsx`（27KB） | SP 物料汇总 |
| `SpReport.tsx` | SP 报表入口 |
| `FmeRanking.tsx`（32KB） | FME 工程师排名 |

### 大屏与看板

| 文件 | 说明 |
| --- | --- |
| `NativeBoard.tsx`（24KB） | 原生看板（含磁盘缓存 `backend\data\native_board_cache\`） |
| `ImonitorScreen.tsx` | iMonitor 大屏 |
| `CxoDashboard.tsx` | CXO 看板 |
| `VmaxCxoDashboard.tsx` / `VmaxCxoDashboard90Days.tsx` / `VmaxCxoDashboardDaily.tsx` | VMAX CXO 系列（90 天/日报） |
| `Dashboard.tsx` | 通用看板 |
| `Overview.tsx` | 系统概览 |
| `MwRealTimeDashboard.tsx` / `MwUmeDashboard.tsx` | MW 系列 |
| `WarehouseDashboard.tsx` | 仓库看板 |
| `BatteryDashboard.tsx`（44KB） | 电池看板 |
| `ComReport.tsx` | 通信报表 |

### 知识问答与设置

| 文件 | 说明 |
| --- | --- |
| `EflowQa.tsx`（80KB） | eFlow 知识问答 |
| `Settings.tsx` | 设置页入口 |
| `CredentialSettings.tsx` | 凭据设置（明文存 `db/app.db` 的 `credentials` 表，见 `docs\manual\05-security-and-credentials.md`） |
| `EmailRecipientsSettings.tsx` | 邮件收件人设置 |
| `RemoteHostSettings.tsx` | 远程主机设置 |
| `EmailReports.tsx` | 邮件报表 |
| `PortalLogin.tsx` | 门户登录集成 |
| `Help.tsx`（30KB） | **站内使用帮助**（与 `docs\manual\15-user-help.md` 同源生成） |

### 帮助内容源（生成文件的输入）

| 文件 | 说明 |
| --- | --- |
| `helpContent.ts`（66KB） | 帮助内容源 |
| `helpTaskDocs.ts`（95KB） | 44 个任务的工作流文档源 |

> **改这两个 TS 后必须跑 `cd frontend && node scripts\generate-help-doc.mjs` 重新生成 MD。不要手改 MD。**

## 五、后端组件

### 入口与注册

| 文件 | 职责 |
| --- | --- |
| `backend\main.py` | FastAPI 入口、路由挂载、生命周期 |
| `backend\task_registry.py` | **任务唯一登记处** `TASK_SPECS` + `register_all_tasks()` |
| `backend\task_registry.md` | 任务注册表说明 |

### 执行与守护

| 文件 | 职责 |
| --- | --- |
| `backend\worker.py` | 独立任务执行 worker（轮询认领、串行执行） |
| `backend\worker_watchdog.py` | worker 看门狗（崩溃自动重拉） |
| `backend\backend_watchdog.py` | 后端看门狗 |
| `backend\restart_marker.py` | 重启标记 |
| `backend\WORKER.md` | worker 架构与容错设计文档 |

### 数据访问

| 文件 | 职责 |
| --- | --- |
| `backend\database.py` | 连接管理、`get_raw_connection()` |
| `backend\dialect_helpers.py` | SQLite/PG 方言适配 |
| `backend\import_topology.py` | 拓扑导入 |
| `backend\log_writer.py` | 日志写入 |

### 安全

| 文件 | 职责 |
| --- | --- |
| `backend\security.py` | 安全基础 |
| `backend\security_tls.py` | TLS |
| `backend\auth_switch.py` | 鉴权开关（对应工作区 `AUTH_SWITCH.md`） |

### 业务服务与 API

| 目录 | 职责 |
| --- | --- |
| `backend\services\` | 各数据源采集、指标计算（含 `cn_ems`、`eflow_rules` 等子目录） |
| `backend\routers\` | API 端点 |
| `backend\models\` | SQLAlchemy ORM |
| `backend\schemas\` | Pydantic schema |
| `backend\migrations\` | 迁移脚本（含 `smoke_test_pg.py`） |

> 接口与任务 ID 速查表见 `docs\manual\90-appendix.md`。

## 六、自己查（比读文档可靠）

```powershell
cd "D:\01_RPA\Task\my_app"

# 前端：列出页面与通用组件（排除备份）
Get-ChildItem frontend\src\pages -Filter *.tsx | Where-Object { $_.Name -notlike "*_bak*" } | Select-Object Name,Length
Get-ChildItem frontend\src\components -Filter *.tsx | Where-Object { $_.Name -notlike "*_bak*" } | Select-Object Name,Length

# 后端：列出服务与路由
Get-ChildItem backend\services -Filter *.py | Where-Object { $_.Name -ne "__init__.py" } | Select-Object Name
Get-ChildItem backend\routers -Filter *.py | Select-Object Name

# 查某个函数/组件被谁用了
Select-String -Path frontend\src\pages\*.tsx,frontend\src\components\*.tsx -Pattern "StatCard"

# 卡片收敛进度：还有多少处直接用了 antd Card
Select-String -Path frontend\src\*.tsx,frontend\src\pages\*.tsx,frontend\src\pages\*\*.tsx `
  -Pattern "import \{[^}]*\bCard\b[^}]*\} from 'antd'"

# 卡片 CSS 契约（类名与令牌）
Select-String -Path frontend\src\index.css -Pattern "wh-card"

# 任务清单（唯一来源）
Select-String -Path backend\task_registry.py -Pattern "task_id=" | Select-Object -First 50
```

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| **逐页功能说明（权威）** | `docs\manual\11-feature-guide.md` |
| 接口与任务 ID 速查 | `docs\manual\90-appendix.md` |
| 设计令牌与主题 | `DESIGN.md`、`frontend\src\theme.ts` |
| 架构与分层 | `architecture.md`、`docs\manual\02-architecture.md` |
| Excel 导出规范 | `docs\EXCEL_EXPORT_STANDARD.md` |
| AI 上手须知 | `AGENTS.md` |
| 全域组件索引 | `D:\01_RPA\component-api.md` |
| 统一门户组件 | `..\..\liberia-noc_soc-数据看板统一门户\docs\component-api.md` |

> **工具负责整理，人与 AI 负责协作执行。**
