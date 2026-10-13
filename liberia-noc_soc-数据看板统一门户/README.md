# Liberia NOC/SOC 数据看板统一门户

聚合 **FineBI 决策报表中心（Liberia Data Portal）** 与 **Data Insight MVP 自研系统（my_app）** 全部看板的统一入口门户。React + Vite + Tailwind CSS v4 实现，默认深色 NOC 值班主题，配色对齐 my_app（深海军蓝底 + teal/cyan 点缀）。

## 功能概览

| 能力 | 说明 |
| --- | --- |
| 看板聚合 | 内置 21 个 my_app 真实页面直链（`?page=` 格式）+ 19 个 FineBI 报表分类条目 |
| 实时任务调度 | 顶部 TaskSyncWidget 每 60 秒拉取 `/api/tasks`，展示 my_app 后端 34 个定时任务运行状态；接口离线时自动降级为静态快照 |
| 三种视图 | 卡片网格 / 高密清单 / 业务分类矩阵（MS 综合运维、告警监控、工单流程、网络性能、资源供应链等） |
| 环境切换 | 一键批量替换所有看板链接的 IP/域名（预设：生产 nginx、vite 7090 直连、本机调试） |
| 深浅双模 | 默认深色（navy 渐变），可切换浅色日间模式（含 TaskSyncWidget/公告横幅浅色适配） |
| 中英文国际化 | 导航栏 Languages 按钮一键切换中/英文，选择持久化到 localStorage（键 `liberia_noc_lang`）；看板业务数据（名称/分类/部门）保持原值不翻译 |
| 收藏与置顶 | 星标收藏、置顶、访问热度排序、JSON 导入导出备份 |
| 移动端 | 每个看板支持二维码扫码（需同网段 WiFi）与 iframe 内嵌预览 |

## 数据源与部署拓扑

```
192.168.100.19:80 (nginx)
 ├── /myapp/   → 127.0.0.1:7090   (Data Insight MVP 前端, vite base=/myapp/)
 ├── /api/     → 7090 → 127.0.0.1:7038 (my_app FastAPI 后端, /api/tasks 等)
 └── /webroot/decision            (FineBI 决策平台)
```

- my_app 页面直链格式：`http://192.168.100.19/myapp/?page=<PageKey>`（query 参数，**非** hash 路由），PageKey 含 `sync / alarm / ttwo / nur / ms_sla / cxoDashboard / gis / realtime_alarm / alarmManagement / packet_loss / battery / ip_trace / incident_overview / warehouse / overview / tables / upload / archive / dashboard / settings`。
- FineBI 入口：`http://192.168.100.19/webroot/decision#/directory?activeTab=dec-tabs-homepage`。
- **FineBI 具体报表链接为目录占位（标签含"链接待更新"，状态 beta），请在门户内"编辑看板配置"逐条替换为实际报表 URL。**

## 新机器启动（干净 clone 后）

**前置：** Node.js 18+

生产入口（`start.bat` → `npm run start`）跑的是 Express（`server/index.ts`），它从磁盘 `dist/` 直接读构建产物，**不会自动构建**。因此干净 clone 后必须走完整三步：

```powershell
# ① 门户主项目依赖
npm install

# ② WhatsApp 本地分析服务是**独立子项目**，有自己的 package.json / node_modules，
#    必须单独安装一次。漏掉它不会报错 —— start-wa-service.mjs 会打印一行
#    "tsx not installed ... Skipping." 后静默跳过，门户页则显示"无法连接本地分析服务"。
cd scripts\whatsapp_analysis
npm install
cd ..\..

# ③ 启动（start.bat 会自动拉起 9267 门户 + 9268 WhatsApp 服务；
#     门户主项目已在 package.json 配 prestart，会替你先跑 npm run build）
start.bat
#    → http://localhost:9267/uniplam/
```

**首次登录：** 鉴权数据目录 `auth-data/` 不入库（含加盐密码哈希）。首次启动会自动播种 `admin`，随机初始密码写入 `auth-data\initial-admin-password.txt`，首次登录强制改密（改完请删除该文件）。

> 只 pull 门户、不部署 my_app / FineBI 的新机器上：页面能打开、UI 能渲染、TaskSyncWidget 走静态快照兜底，但**所有 my_app 看板直链与 FineBI 报表链接都会 404** —— 门户只是聚合壳，这两端是 nginx 直接 alias 的仓库外服务（`Task/_fe_dist/`、`/webroot/decision`），刻意不入库。

## 开发调试

```powershell
npm run dev        # Vite dev server，默认 http://localhost:9267（7038/7090 已被 my_app 后端/前端占用，不可复用）
```

`predev` 会自动尝试拉起 WhatsApp 服务（仍要求上面第 ② 步先装好依赖）。本地 dev 时 `vite.config.ts` 已配置 `/api` 代理到 `http://192.168.100.19`，任务调度部件可直连生产后端。

## 构建与部署

```powershell
npm run build      # 产物输出 dist/；npm run start / start.bat 会经 prestart 自动触发
```

部署到 192.168.100.19 同一台 nginx 时（推荐，API 走同源 `/api/tasks` 无需跨域）：

```nginx
location /portal/ {
    alias  D:/path/to/dist/;
    index  index.html;
    try_files $uri $uri/ /portal/index.html;
}
```

> 部署到子路径时，需在 `vite.config.ts` 设置 `base: '/portal/'` 后重新构建。

## 配置项

见 [.env.example](.env.example)：

- `VITE_MYAPP_API_BASE`：my_app API 基址。同源部署或本地 dev 留空即可；跨机部署填完整基址。
- 主机地址集中在 `src/config.ts`（`DEFAULT_HOST`），换机房只改这一处。

## 目录结构

```
src/
 ├── config.ts               # 全局环境配置（API/主机/入口 URL）
 ├── data/initialDashboards.ts  # 22 个 my_app + 15 个 FineBI 初始看板数据
 ├── types/dashboard.ts      # 数据模型（themeColor 含 teal）
 ├── components/
 │    ├── TaskSyncWidget.tsx # 实时任务调度部件（/api/tasks + 静态快照兜底）
 │    ├── DashboardCard.tsx  # 卡片视图（含 teal 主题色）
 │    └── ...                # 导航/筛选/弹窗/预览/二维码等
 └── App.tsx                 # 状态管理 + localStorage 持久化（v3）
```

> 看板数据持久化在浏览器 `localStorage`（键 `liberia_noc_dashboards_v3`）。升级后如未看到新数据，点击导航栏"恢复初始默认看板"或清除站点数据。
