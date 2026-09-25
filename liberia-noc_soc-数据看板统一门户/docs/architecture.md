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

> **2026-09-25 重构**：原单文件 `server\auth.ts`（928 行，越过本项目 500 行红线，
> 混了类型/密码/状态/守卫/路由五类职责）已拆为 `server\auth\` 模块。设计与验收见
> `auth-module-design.md`。**行为零变化**，仅结构改变；同时修掉循环依赖与限流分桶缺陷（见下）。

| 文件 | 职责 |
| --- | --- |
| `server\auth\types.ts` | 类型、常量、纯函数（无 IO、无状态） |
| `server\auth\password.ts` | scrypt 加盐哈希与校验（N=16384,r=8,p=1） |
| `server\auth\store.ts` | `AuthStore`：用户 / 申请 / 会话 / 限流；导出 `getAuthStore` 单例 |
| `server\auth\guard.ts` | **鉴权决策唯一入口** `resolveCaller(req, store)`；含免登录旁路与 `DEV_ADMIN` |
| `server\auth\routes.ts` | HTTP 路由分发 + vite 插件挂载；`clientIp()` 取真实来源 IP |
| `server\auth\index.ts` | 对外出口（保留原 `./server/auth` 导入面） |
| `server\authDb.ts` | 鉴权持久化；**只依赖 `auth/types`**（依赖 `auth/index` 会形成环） |
| `server\authSwitch.ts` | 鉴权总开关 |
| `src\auth\AuthContext.tsx` | 前端鉴权上下文（`apiFetch` 自动注入 Bearer，401 自动回登录态） |
| `src\components\RequireAuth.tsx` | 前端鉴权门组件（新页面接入用） |
| `src\utils\groups.ts` | 分组 |

### 依赖方向（单向，无环）

```
types ← password ← store ← guard ← routes ← index
                     ↑
                  authDb（只取 types）
```

### 新页面接入鉴权（三种形态）

| 形态 | 接入方式 | 成本 |
| --- | --- | --- |
| 门户内新 React 页 | `<RequireAuth>` 包住 + `useAuth()` 取身份 + `apiFetch(PORTAL_API+...)`；照抄 `src\pages\_TemplatePage.tsx` | 低 |
| `MsPortal\` 静态壳 | 已各自实现（登录/`/me` 探针/用户管理）；再新增壳需照抄 `portal.js` 的验签流程 | 中 |
| 远程系统深链 | 已实现：门户 token → `?t=` → 对方回调门户 `/me` 验签 → 签自己的会话（见 `Task\my_app\backend\services\portal_auth.py`） | 低（复用） |

> **服务端才是强制点。** `allowedGroups` / `allowedCards` 目前只在前端
> `App.tsx` 过滤（显示层），服务端不拒答——见 `auth-module-design.md` 第五节 S4。

### 已知缺陷（已登记，未修）

| # | 缺陷 | 影响 |
| --- | --- | --- |
| S1 | 门户 token 经 URL query（`?t=`）传递 | 进入浏览器历史 / Referer / nginx access log；token 有 12h 滑动续期 |
| S2 | 门户会话仅存进程内存 | 门户重启即全员掉线（my_app 侧已用 SQLite 落盘解决） |
| S4 | 看板目录接口未登录可读 | 白名单是显示层规则，非强制边界 |

> **S3（登录限流全站共用 `127.0.0.1` 一个桶，可被单人锁死全站 60 秒）已于 2026-09-25 修复**：
> `server\auth\routes.ts` 的 `clientIp()` 在直连方为本机回环时改读 nginx 下发的
> `X-Real-IP`（`nginx.conf:364`），并保留 socket 地址作为不可信来源的回退，防伪造。

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
