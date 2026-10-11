# 02 架构设计

## 进程拓扑

一台机器上同时存在 5 类进程，全部由启停脚本托管（脚本细节见 `13-operations.md`）：

| 进程 | 监听 | 由谁拉起 | 职责 |
| --- | --- | --- | --- |
| nginx | `:80` | 人工/系统服务 | 生产入口，把 `/myapp/` 反代到 vite preview |
| vite preview | `:7090`（`0.0.0.0`） | `start_hidden.ps1:244` | 托管前端构建产物 + `/api` 反代到 7038 |
| uvicorn (backend) | `:7038`（`0.0.0.0`） | `backend_watchdog.py:147-150` | FastAPI，提供 `/api/*` 与 SPA 兜底 |
| worker × 5 组 | 无端口 | `worker_watchdog.py:36-66` | 消费 `task_queue`，执行采集/报表任务 |
| realtime proxy | `127.0.0.1:8787`、`:8790` | backend 启动线程（`main.py:216-250`） | 代理 FMS/VMAX 实时抓取，**只绑回环** |

worker 组的实际启用集合由环境变量 `MY_APP_WORKER_GROUPS='u,n,s,w,m,c,v'` 决定（`start_hidden.ps1:135`）：`u`=RAN UME 会话、`n`=eFlow API/config-center 同源会话、`s`=SP 备件 SFTP、`w`=MW UME 微波网管、`v`=VMAX 门户（8790 单会话）、`m`=内务轻任务、`c`=CN EMS。**分组表、启动脚本两处必须同步**（`restart_workers.py::ALL_GROUPS` 已改为从 `GROUP_TASK_MAP` 取键，不再单独维护），否则该组任务永远 pending（详见 `04-task-system.md`）。

## 后端启动序列

`backend/main.py` 的 startup 钩子按序做四件事（`main.py:216-250`）：

1. **建库/连接重试** — 数据库不可用时不直接崩，重试后再判定。
2. **抢单实例锁** `db/instance.lock`（`main.py:145-171`）— 已有实例则拒绝启动，防止两个后端写同一库。
3. **注册任务** — `register_all_tasks()`（`task_registry.py:405-429`）把 41 条 `TASK_SPECS` 写进调度器，cron 可被库表 `task_schedule_config` 覆盖。
4. **起 APScheduler + 实时代理线程**。

中间件只有一个 CORS（`main.py:86-92`），白名单默认放行 7038/5173 两端口，可用 `MY_APP_CORS_ORIGINS` 覆盖（`main.py:80-85`）。

> ⚠️ **当前没有全局异常处理器**：全仓库无 `@app.exception_handler`。未捕获异常由 FastAPI 默认行为返回 500，堆栈只进 `log/backend_runtime.log`，响应体不含原因——排障时先看日志而不是看浏览器报错。

## 静态资源与 SPA 兜底

`main.py:258-295` 挂载：`_fe_dist` 根、`/assets`、`/myapp/assets`，并注册 `GET /{full_path:path}` 兜底回 `index.html`；`index.html` 显式禁缓存（`main.py:263-267`），避免发版后浏览器拿旧壳。

## 分层约定（以及实际偏差）

```
routers/   HTTP 层：解析参数、调 service、组织响应
services/  业务层：抓取、清洗、计算、写库、发邮件（60+ 模块 + 子包）
models/    SQLAlchemy 表定义（10 个文件，共 374 行；__init__.py:5-11 主库、:13-18 独立库）
schemas/   预留，实际为空
```

**三条真实偏差，改代码时按现状对待，不要按"理想分层"想当然**：

1. **Pydantic 模型内联在 router**（如 `routers/credentials.py:37`），`schemas/__init__.py` 是空文件。新增请求体模型请放在对应 router 里，与现状一致。
2. **部分 router 直接裸 SQL 取数**，未经 service：`routers/tables.py`（10 处）、`routers/gis.py`（9 处）、`routers/alarm_dashboard.py`（7 处）调用 `get_raw_connection`。新功能不建议模仿，但重构这三处要留意回归成本。
3. **超大文件仍然存在**，行数（已验证）：`services/ms_sla_report.py` 1697、`services/eflow_data_mapper.py` 1505、`services/ran_ume_network_kpi.py` 1481、`services/task_runner.py` 1164、`routers/gis.py` 895、`routers/alarm_dashboard.py` 843。GIS 只拆出了无路由的辅助模块 `gis_geometry.py`，路由本身未拆。

## 前端架构

**没有用 react-router**（`frontend/package.json:11-36` 无该依赖，`main.tsx:6-10` 直接渲染 `<App/>`）。

- 页面切换是 App 内 state：合法页 key 定义在 `App.tsx:68-70`（23 个），入口读 `?page=xxx` 查询参数，非法或缺省回退默认页 `'sync'`（`App.tsx:117-120`），分发在 `renderPage()` 的 switch（`App.tsx:266-317`）。
- 因此**定位一个页面的方式是 URL 查询参数**，例如 `/myapp/?page=battery`；右键"在新标签页打开"就是生成这个参数（`App.tsx:241-246`），`document.title` 同步页面名（`App.tsx:249-252`）。
- 全部页面 `lazy()` 代码分割（`App.tsx:43-64`），外层 `Suspense` 居中 Spin。
- 菜单数组内联在 `App.tsx:182-206`，单层 `mode="inline"`，**无分组无子菜单**；仅整个 Sider 可折叠（`collapsedWidth=0`，默认收起，持久化 `localStorage['myapp_sider_collapsed']`，`App.tsx:122-134`）。
- `gis` 与 `realtime_alarm` 复用同一组件：`<GISMap/>` 与 `<GISMap mode="realtime"/>`（`App.tsx:286-289`）。
- 共享组件只有 4 个：`DraggableClickModal`（下钻弹窗）、`LegacyToolFrame`（iframe 壳）、`MetricExplain`（指标口径说明）、`SearchableExportTable`（可搜索导出表）。

**自动刷新**（`App.tsx` 顶部「自动刷新（大屏 / NOC 值班场景）」注释块与 `performAutoRefresh`）：顶栏统一控制，间隔存 `localStorage['myapp_auto_refresh_sec']`，可选 `[0,30,60,300,600,900,1800]` 秒、看板页默认 300 秒。

- **白名单制**：只有「看板 / 展示页」参与自动刷新（`AR_BOARD_PAGES`）；配置、操作、工具类页面（如 `settings` / `upload` / `tables` / `ip_trace` / `eflow_*` 等）的生效间隔恒为 0，**完全不刷新**，顶栏选择器对它们禁用。
- **两条刷新路径**：软刷新页（`AR_SOFT_REFRESH_PAGES`）由外壳广播 `postMessage({__type:'myapp-refresh'})` 在 iframe 内原地重拉；其余看板页走硬重挂载（`key={refreshTick}` 变化 → 组件重挂载）。广播无副作用，**在 `arInteractionInProgress()` 拦截之前发出**，故全屏 / 后台也照发；硬重挂载有副作用，才受「用户正忙」与 `document.fullscreenElement` 拦截。
- **生效间隔**通过 `localStorage['myapp_auto_refresh_effective']` 公开给 legacy 页，并写 `localStorage['myapp_auto_refresh_is_board']`（`'1'/'0'`）标记本页是否看板。
- **legacy 页自刷新安全网**：7 个 iframe 看板页 + 2 个 React 内嵌页统一引入 `public/myapp-refresh-protocol.js`（`MyAppRefresh.install`）—— 父外壳广播即「提前触发」原地重拉，广播被挡时按生效间隔自调度兜底；非看板页不启用；看板页全屏时忽略「关闭」按本页默认兜底。`alarm-management.html` 有自身 live 模式，仅补广播入口。

这与下面两个 Context 无关。

**两个全局 hook 的职责容易混，注意区别**：

- `TaskStatusContext.tsx:19-57`：轮询 `GET /api/tasks`（有任务运行时 2s、否则 8s，`:39`），暴露 `runningMap`/`isRunning`。**只有任务管理页在用**（`pages/DataSync.tsx:39,65`），表现为运行中卡片的转圈图标。别的应用场景想复用它，需要先确认 Provider 覆盖到了（挂在 `App.tsx:643`）。
- `useDataTimestamps.ts:14-49`：**单次**请求 `GET /data-source/timestamps`（`:19-22`，无轮询），返回 `lastSync`/`alarmLastSync`/`latestData`/`isSynced`，空值显示 `t('datasource.noData')`。使用者是 Dashboard（`pages/Dashboard.tsx:8,33`）、GISMap（`pages/GISMap.tsx:11,43`）、TT&WO 看板（`pages/TTWODashboard.tsx:16,77`），表现为页头的"已同步/最近同步时间"标签。
- 两者与顶栏的"自动刷新"（下一段）互不相干。

**i18n**：`i18n.tsx` 内 `translations` 双字典 zh/en；`t(key, params)` 查当前语言 → 回退中文 → 回退 key 本身，`{x}` 占位符做字符串替换（`i18n.tsx:1783-1789`）。语言存 `localStorage['app-locale']`，缺失时按 `navigator.language` 判定（`i18n.tsx:1750-1755`）。切换语言会同步后端（`setApiLocale`）、设置 `<html lang>`、并向 iframe `postMessage myapp-locale`（`i18n.tsx:1763-1772`）——**新增文案必须 zh/en 两处同名 key 各加一行**，只加一处的结果是英文环境显示中文（该缺陷历史上出现过两次，见 PROJECT_DOCS.md 的 i18n 审计章节）。

## 构建产物

`vite.config.ts`：`base: '/myapp/'`（:6）；dev/preview 同为 `0.0.0.0:7090` 且带 `strictPort`，`/api` 与 `/myapp/api` 代理到 `http://localhost:7038`（:9-21,27-41）；`chunkSizeWarningLimit:1200` + 手工 vendor 分包（:55-68）。

脚本只有三条（`frontend/package.json:7-9`）：`dev` / `build`（`tsc && vite build`）/ `preview`，其中 dev 与 preview 走 `../scripts/start-app.mjs` 包装。

> ⚠️ **已知约束**：`build.outDir` 是绝对路径 `D:/01_RPA/Task/_fe_dist`（`vite.config.ts:49`），**在 my_app 之外**（:43-48 注释说明原因是 IDE 句柄占用与 `emptyOutDir:false`）。这与仓库规则「my_app 项目下的引用不要放到外面」冲突：单独把 `my_app` 目录发给别人，前端产物链是断的。需要移交时应连带 `_fe_dist`，或把 outDir 改回 `frontend/dist` 并同步 nginx 指向。历史遗留的 `frontend/dist`、`dist2`、`dist3` 与 `_fe_dist` 里若干 legacy html（`alarm-management.html`、`cxo_dashboard.html`、`incident-overview.html`、`ip-trace.html` 等）仍在被 iframe 引用，见 `11-feature-guide.md` 的"iframe 页"标注。
