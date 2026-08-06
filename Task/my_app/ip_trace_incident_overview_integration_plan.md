# 集成计划：IP_Trace_Tool + incident_overview → my_app

> 目标：将 `D:\01_RPA\Task\Unified_Tools` 下的 `IP_Trace_Tool` 与 `incident_overview` 两个独立 Flask 工具
> 以 my_app 现有架构规范（FastAPI router/service + React/antd 页面）集成进 my_app，
> 做到风格统一、依赖不冗余、不影响现有功能。

---

## 一、现状分析

### 1.1 源模块分析（Unified_Tools）

#### IP_Trace_Tool（Flask 独立服务，端口 7090）

| 项目 | 说明 |
|---|---|
| 核心文件 | `ip_detect_tool.py`（1862 行）、`templates/index.html`（Tailwind 单页 UI） |
| 功能实现 | tracert 路由追踪 → 对每跳持续 ICMP + TCP 双协议 ping → 统计时延/抖动/丢包 → AI 智能分析 → Leaflet 链路地图 |
| 对外接口 | `POST /trace`、`POST /stop`、`GET /status`、`POST /analyze`、`POST /shutdown` |
| 数据存储 | 多会话内存态（session_id 隔离）+ JSON/CSV 落盘到 `data/` 目录 |
| 配置文件 | 代码内 AI API 配置（Gemini/OpenAI/通义/豆包默认 key、base_url、模型列表），优先级：用户输入 > 环境变量 > 默认配置 |
| 依赖项 | flask、requests、geoip2（可选，GeoLite2-City.mmdb 地理位置库） |

#### incident_overview（Flask 独立服务，端口 7038）

| 项目 | 说明 |
|---|---|
| 核心文件 | `app.py`（1726 行）、`index.html`（7059 行单页 UI） |
| 功能实现 | 读取 Excel 七个 sheet（Status / TT Quality / Owner1 / ZTE / 3rd / Details1 / Details）→ 状态卡片、严重度×状态矩阵、SLA 分布、明细表、工单日志分页表、利比里亚地图、AI 助手、虚拟助手（电话/短信/浏览器语音/桌面通知） |
| 对外接口 | `/api/all`、`/api/status`、`/api/tt-quality`、`/api/severity`、`/api/sla/<vendor>`、`/api/details`、`/api/incident_log`（mtime 缓存 + 分页）、`/api/debug`、`/api/ai/*`（openai/gemini/doubao/qianwen/glm/deepseek 六个端点）、`/api/assistant/call`、`/api/assistant/sms`、`/lr-all.geo.json` |
| 数据存储 | `data/incident_overview.xlsx`（按文件 mtime 缓存解析结果）；`lr-all.geo.json` 利比里亚地图边界 |
| 配置文件 | `.env`（python-dotenv 可选）；电话/短信服务商由环境变量 `PHONE_SERVICE_PROVIDER`、`SMS_SERVICE_PROVIDER` 控制（twilio/aliyun/tencent/none 模拟模式） |
| 依赖项 | flask、flask-cors、pandas、openpyxl、requests、python-dotenv、openai（仅 deepseek 端点） |

### 1.2 my_app 架构分析（集成目标规范）

| 维度 | 现状 |
|---|---|
| 整体架构 | FastAPI 后端（端口 8000，`backend/main.py`）+ React 前端（Vite dev 5173，生产由后端挂载 `frontend/dist`） |
| 目录组织 | `backend/routers/`（API 层）、`backend/services/`（业务逻辑层）、`backend/models`、`backend/schemas`、`frontend/src/pages`、`frontend/src/components` |
| 模块注册 | 路由：`backend/routers/*.py` 定义 `APIRouter(prefix="/api/<module>", tags=[...])`，在 `main.py` 中 `app.include_router()`；页面：`App.tsx` 中 `lazy()` 懒加载 + `menuItems` + `renderPage()` switch |
| 任务调度 | `backend/task_registry.py` 声明式 TASK_SPECS + `task_runner` 通用调度（本次集成为在线交互功能，无需注册定时任务） |
| UI 风格 | React 19 + antd 6 + echarts + leaflet/react-leaflet；深色主题（背景 `#0a1929`、主色 teal `#13c2c2`，`theme.ts` 的 `WH` 常量）；中英双语 `i18n.tsx` |
| 命名规范 | router 文件名 snake_case（如 `alarm_dashboard.py`），页面组件 PascalCase（如 `AlarmDashboard.tsx`），API 前缀 kebab-case（如 `/api/alarm-dashboard`） |
| 配置管理 | 环境变量 + `credentials` 表（凭据集中管理，`CredentialSettings` 页面）；CORS 由 `MY_APP_CORS_ORIGINS` 控制 |
| 公共能力 | `logging`（禁裸 print）、`get_raw_connection`（SQLite）、`backend/security.py`（受保护接口）、`api.ts` 统一 axios 实例（baseURL `/api`，timeout 120s） |
| 依赖管理 | 根 `requirements.txt` + `requirements.lock.txt`；前端 `package.json` |

---

## 二、集成方案（改写而非复制）

### 2.1 后端改动（my_app/backend）

| 类型 | 文件 | 说明 |
|---|---|---|
| 新增 | `services/ip_trace_service.py` | 追踪/双协议 ping/多会话管理/GeoIP/AI 分析核心逻辑。改造点：`print` → `logging`；数据落盘目录改为 `my_app/data/ip_trace/`；移除硬编码 OpenAI API key，改环境变量注入；显示加载耗时 |
| 新增 | `routers/ip_trace.py` | `APIRouter(prefix="/api/ip-trace")`：`POST /trace`、`POST /stop`、`GET /status`、`POST /analyze`。去掉 `/shutdown`（服务生命周期由 my_app 统一管理） |
| 新增 | `services/incident_overview_service.py` | Excel 读取、向量化解析（pandas `to_dict('records')`）、mtime 缓存。数据文件路径改为 `my_app/data/incident_overview/incident_overview.xlsx` |
| 新增 | `routers/incident_overview.py` | `APIRouter(prefix="/api/incident-overview")`：`GET /all`、`/status`、`/tt-quality`、`/severity`、`/sla/{vendor}`、`/details`、`/incident_log`（分页）、`/geojson`；`POST /ai/analyze`（6 个提供商端点合并为统一分发，provider 参数选择，deepseek 亦改 requests 走 OpenAI 兼容接口）；`POST /assistant/call`、`POST /assistant/sms`（保留 twilio/aliyun/tencent/none 模拟模式） |
| 修改 | `main.py` | 导入并 `include_router` 两个新路由（约 +4 行） |
| 新增数据 | `data/incident_overview/` | 复制 `incident_overview.xlsx`、`lr-all.geo.json` |
| 新增文档 | `services/ip_trace_service.md`、`services/incident_overview_service.md` | 遵循项目规则：新 py 文件同目录配 MD 文档 |
| 修改 | `backend/requirements.txt` | 补充 `requests`（实际已被使用但未声明）、`geoip2`（注释标注可选） |

### 2.2 前端改动（my_app/frontend）

| 类型 | 文件 | 说明 |
|---|---|---|
| 新增 | `src/pages/IpTrace.tsx` | React 重写：目标输入/启停按钮、跳数表格（ICMP/TCP 实时统计，轮询 `/api/ip-trace/status`）、echarts 时延趋势图、leaflet 链路地图（跳点坐标连线）、AI 分析面板（提供商选择，默认本地规则免 API） |
| 新增 | `src/pages/IncidentOverview.tsx` | React 重写：状态卡片（antd Statistic）、TT Quality、严重度×状态矩阵表、ZTE/3rd SLA 柱状图（echarts）、Details 表、Incident Log 服务端分页表、利比里亚地图（leaflet + `/api/incident-overview/geojson`）、AI 助手弹窗、虚拟助手（浏览器语音播报 + 桌面通知，纯前端实现） |
| 修改 | `src/App.tsx` | 懒加载两个新页面；`PageKey` 增加 `ip_trace`、`incident_overview`；`menuItems` 增加两项（图标：`AimOutlined`、`FileSearchOutlined`）；`renderPage()` 增加两个 case |
| 修改 | `src/i18n.tsx` | 新增 `nav.ipTrace`、`nav.incidentOverview` 及页面内中英词条 |

### 2.3 依赖合并策略

| 依赖 | 处理 |
|---|---|
| flask / flask-cors | **不引入**，全部改写为 FastAPI router |
| python-dotenv | **不引入**，沿用 my_app 环境变量方式 |
| openai SDK | **不引入**，deepseek 端点改为 requests 直调 ModelScope OpenAI 兼容接口 |
| requests | 环境已安装，补声明到 requirements |
| pandas / openpyxl / numpy | my_app 已有，直接复用 |
| geoip2 | 可选依赖（mmdb 文件缺失时地理位置降级为"未知"） |
| 前端 | antd / echarts / leaflet / react-leaflet / axios / dayjs 全部已有，**零新增 npm 依赖** |

---

## 三、关键风险与对策

| 风险 | 对策 |
|---|---|
| 源码硬编码 OpenAI API key 泄露 | 不迁移明文 key，改为环境变量 `OPENAI_API_KEY` 等注入 |
| 路径引用遗漏导致无法运行 | 遵守 my_app 自包含约束，所有文件与数据均在 `my_app/` 目录内 |
| 影响现有功能 | 仅新增 router/页面，不修改任何现有路由与组件 |
| API 路径冲突 | 现有 `/api/details` 已被 SP 看板占用，新模块统一使用 `/api/incident-overview/*` 前缀隔离 |
| GeoIP mmdb 文件不存在 | 与原逻辑一致：降级为"位置未知"，功能可用 |
| 大 Excel 解析性能 | 保留 mtime 缓存 + pandas 向量化，与原优化一致 |

---

## 四、集成后文件改动清单（预期）

### 新增
```
my_app/
├── backend/
│   ├── routers/ip_trace.py
│   ├── routers/incident_overview.py
│   ├── services/ip_trace_service.py
│   ├── services/ip_trace_service.md
│   ├── services/incident_overview_service.py
│   └── services/incident_overview_service.md
├── data/incident_overview/
│   ├── incident_overview.xlsx          （复制自源项目）
│   └── lr-all.geo.json                 （复制自源项目）
└── frontend/src/pages/
    ├── IpTrace.tsx
    └── IncidentOverview.tsx
```

### 修改
```
my_app/backend/main.py                    （注册 2 个新 router）
my_app/backend/requirements.txt           （补 requests、geoip2 可选）
my_app/requirements.txt                   （补 requests）
my_app/frontend/src/App.tsx               （菜单 + 路由注册）
my_app/frontend/src/i18n.tsx              （新增词条）
```

### 新增入口位置
- 前端左侧导航栏新增两个菜单项：**IP Trace**（IP 链路探测）、**Incident Overview**（事件总览），位于现有功能菜单中
- 后端 API 前缀：`/api/ip-trace/*`、`/api/incident-overview/*`

---

## 五、验证方式

### 5.1 后端验证
1. 启动后端（8000 端口），确认启动日志无异常、注册任务数不变之外无回归
2. `GET /api/health` 正常
3. `GET /api/incident-overview/all` 返回 status / tt_quality / severity / sla_zte / sla_3rd / details 六段数据
4. `GET /api/incident-overview/incident_log?page=1&limit=20` 分页正常，二次请求命中缓存（日志显示 from cache）
5. `POST /api/ip-trace/trace`（target=127.0.0.1 或公网域名）→ `GET /api/ip-trace/status` 持续返回 ping 数据 → `POST /api/ip-trace/stop` 停止
6. `POST /api/ip-trace/analyze`（provider=local）返回本地规则分析报告

### 5.2 现有功能回归
- `GET /api/tasks`、`GET /api/data`、`GET /api/sp-data/summary`、`GET /api/db/info` 抽查正常
- 现有页面（DataSync、AlarmDashboard 等）菜单与功能不受影响

### 5.3 前端验证
1. `npm run build`（tsc + vite）编译通过
2. 启动 dev server，打开 IP Trace 页面：输入目标 → 开始 → 表格实时刷新 / 地图渲染 / 停止
3. 打开 Incident Overview 页面：卡片、矩阵、SLA 图表、分页表、地图、AI 助手弹窗逐项验证
4. 切换中英文，词条无缺失
