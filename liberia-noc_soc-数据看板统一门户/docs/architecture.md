# 05 architecture.md —— 架构和数据流

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\architecture.md`（全域拓扑与 my_app 内部架构见那里，本文不重复）

## 一、运行时拓扑

```
                      nginx  192.168.100.19:80
                             │
        ┌────────────────────┼────────────────────┐
        │ /myapp/            │ /api/              │ /uniplam/
        ▼                    ▼                    ▼
  my_app 前端          my_app 后端           本门户
  vite :7090           uvicorn :7038          :9267
  base=/myapp/         (FastAPI)              前端 + 门户后端 API
        │                                          │
        └──────── 看板页面 URL = 主机 + rel ────────┘
```

**开发端口 9267**（`npm run dev`）。7038 / 7090 已被 my_app 占用，**不可复用**。

## 二、`/uniplam` 前缀为什么是必须的

这是本项目最容易踩的架构坑，原文在 `src\config.ts` 顶部注释：

```
门户页面挂在 nginx 的 /uniplam/ 子路径下。
前端若请求绝对路径 /api/auth/login，会命中 nginx 的通用 location /api/
  → 打到 my_app 后端 7038
  → 7038 上 GET /api/auth/login 是 SPA 兜底静态页（仅允许 GET）
  → POST 被回成 405 Method Not Allowed
  → 这正是"其他电脑（走 80 端口 nginx）登录失败"的原因
```

修复方式：门户所有 API 请求带应用 base 前缀，即 `/uniplam/api/...`，天然落在 `location /uniplam/`（→ 9267 门户自身服务）里，与 my_app 的 `/api/` 彻底不冲突。

**代码里用 `PORTAL_API` 常量**（`src\config.ts` 导出）：

```ts
export const PORTAL_API = `${(import.meta.env.BASE_URL || '/').replace(/\/+$/, '')}/api`;
```

本地直连 `http://localhost:9267/uniplam/` 同样走这个前缀，行为一致。

## 三、配置优先级与"主机 + rel"模型

### 优先级

```
localStorage 覆盖  >  VITE_* 环境变量  >  src\config.ts 硬编码兜底
```

`src\config.ts` 是**单一真相源**。`EnvConfig` 三个字段：

| 字段 | 含义 |
| --- | --- |
| `finebiHost` | FineBI 决策平台主机 |
| `myappHost` | my_app 主机 |
| `myappApiBase` | my_app API 基址；留空=同源（`/api/...`），跨域时填完整基址 |

### 看板 URL 的组装

```
看板条目只存相对路径 rel  ──►  运行时 = 主机 + rel  ──►  完整 URL
```

这样做的收益：

- 换 IP/域名时**只改主机一处**（或界面上「环境配置」一键切换），全站生效；
- **已持久化到 localStorage 的旧数据也能自动跟随**——因为存的是 `rel` 不是绝对 URL。

这是本项目最重要的设计决策之一，改数据模型时不要退化成存绝对 URL。

## 四、数据流

### 流 1：加载看板目录

```
浏览器 → /uniplam/ → 门户前端 :9267
  ① 读内置初始数据 src\data\initialDashboards.ts
  ② 读门户后端 GET /uniplam/api/portal-default
  ③ 读 localStorage（键 liberia_noc_dashboards_v3）——【优先级最高】
  → 合并后渲染；每张卡 URL = 主机 + rel
```

> **本地优先**是有意为之（用户可自定义并导出），代价是改代码里的初值后用户看不到——需「恢复初始默认看板」或清缓存。

### 流 2：实时任务调度部件

```
TaskSyncWidget ──每 60s──► GET /uniplam/api/tasks
    → （同源部署）nginx → my_app :7038 /api/tasks
    → 成功：渲染任务列表（含 recent_runs 最近运行、耗时、成功与否）
    → 失败：降级为内置静态快照，【不白屏】
```

部件接口模型（`TaskSyncWidget.tsx`）：入参 `ApiTask`（`task_id`/`name_zh`/`name_en`/`category`/`current_cron`/`enabled`/`running`/`recent_runs`），内部归一为 `TaskItem`（`id`/`name`/`category`/`cron`/`enabled`/`running`/`lastSuccess`/`lastElapsed`）。

### 流 3：QC 指标与下钻

```
QC 卡片 ──► 门户后端 /uniplam/api/portal-qc/*
    │
    └─ 点击下钻 → GET /uniplam/api/portal-qc/detail
                     ?metric=<id>&page=<n>&size=50[&q=<搜索>]
                  → { total, rows, columns }
```

**两档刷新节奏**（用**墙上时钟**对齐，不是 interval 累加）：

| 档 | 网格 | 偏移 | 对应后端 |
| --- | --- | --- | --- |
| 全量 | 60 分钟 | +390 秒 | 每小时 `:06:30`，紧跟 `eflow_sync` 跑完 |
| 告警 | 5 分钟 | +30 秒 | `:00:30` / `:05:30` …，紧跟 `eflow_active_alarm` 每 5 分钟的同步 |

**为什么不用 interval 累加**：interval 从进页面那一刻起算，进页面时若是 `:07`，`:06` 已同步好的数据要再等 59 分钟才上屏。网格以「本地当天 0 点」为原点（而非 epoch），这样 `+05:30` 这类半小时时区也能对齐到本地的 `:06`。

## 五、状态管理

`src\App.tsx` 是**唯一状态中枢**（43KB）——看板数组、分组、鉴权、视图模式、搜索排序、所有弹窗开关、localStorage 持久化都在这里。组件通过 props 接收回调，**没有引入 Redux/Zustand 等状态库**。

新增弹窗必须同时改三处：

1. `App.tsx`：`useState` 开关 + 渲染组件 + 把回调传给 `Navbar`；
2. `Navbar.tsx`：`NavbarProps` 加回调 + 桌面端与移动端两个入口；
3. `i18n.tsx`：`zh` 与 `en` 两份字典加入口文案。

（`DesignGuideModal` 与本项目的 `DocsIndexModal` 都是这个模式，可作模板。）

## 六、请求竞态处理

异步请求用**序号作废**模式，避免过期响应写回界面。以 QC 下钻为例：

```ts
var seq = ++qcDrillSeq;
// ...fetch...
.then(function (data) {
  if (seq !== qcDrillSeq || state.qcDrill.metric !== d.metric) return;  // 过期响应，丢弃
  // ...
});
// 关闭弹窗时：qcDrillSeq++   ← 作废在途请求，避免关掉后又被写回
```

> 看到别的模块也用 `xxxSeq` 变量，是同一套约定。新增异步列表/弹窗时照做。

## 七、构建与部署

- 构建：`npm run build` → `dist/`
- 部署到 nginx 子路径时**必须**在 `vite.config.ts` 设 `base: '/portal/'` 后**重新构建**，否则静态资源 404。
- `vite.config.ts` 还负责把门户后端（`server\`）挂进 dev server。

## 八、鉴权架构

| 文件 | 职责 |
| --- | --- |
| `server\auth.ts`（34KB） | 鉴权主逻辑 |
| `server\authDb.ts` | 鉴权用户库（存储在 `auth-data\`） |
| `server\authSwitch.ts` | 鉴权开关 |
| `src\auth\AuthContext.tsx` | 前端鉴权上下文 |
| `src\utils\groups.ts` | 分组 |

- 鉴权开关状态在 `auth-switch.json`，操作入口 `auth_switch.bat` / `auth_switch.py`，说明见 `D:\01_RPA\AUTH_SWITCH.md`。
- **`auth-data\` 含加盐密码哈希，已在 `.gitignore`，严禁入库。**

## 九、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 全域拓扑与 my_app 架构 | `D:\01_RPA\architecture.md` |
| my_app 内部架构 | `Task\my_app\docs\manual\02-architecture.md` |
| 配置项与优先级原文 | `src\config.ts` 顶部注释 |
| 组件 API | `component-api.md` |
| 开发与部署 | `development.md` / `README.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |

> **工具负责整理，人与 AI 负责协作执行。**
