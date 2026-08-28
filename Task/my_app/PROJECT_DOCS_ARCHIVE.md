# PROJECT_DOCS 归档原文

> 这里是 `PROJECT_DOCS.md` 中被精简掉的**原文逐字备份**（迁移到 `docs/manual/` 手册的那些说明性章节）。
> 保留原因：`PROJECT_DOCS.md` 未被 git 跟踪（仓库 `.gitignore` 内容为 `*`），删除即不可恢复。
> 精简日期：2026-08-27。现状描述请看 `docs/manual/`，本文件不作为依据。


---

## 原 §1 逐字备份（PROJECT_DOCS.md 第 20-170 行）

# 1. 项目说明 README

# 数据洞察 SaaS MVP

上传工作簿、自动识别字段与质量问题、生成多维图表和结论，GIS展示与下钻，分析归档检索。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (SQLite) |
| 前端 | React + Vite + TypeScript |
| UI | Ant Design 5 |
| 图表 | ECharts 5 |
| 地图 | Leaflet + OpenStreetMap |
| 数据库 | SQLite3 |

## 项目结构

```
my_app/
├── backend/                 # FastAPI后端
│   ├── main.py             # 主入口
│   ├── database.py         # 数据库连接
│   ├── models/             # ORM模型
│   ├── routers/            # API路由
│   │   ├── tables.py       # 表浏览
│   │   ├── upload.py       # 文件上传
│   │   ├── analysis.py     # 分析归档
│   │   ├── gis.py          # GIS地理信息
│   │   └── tt_wo_dashboard.py  # TT&WO Dashboard
│   ├── services/
│   │   └── profiler.py     # 数据质量分析引擎
│   └── scripts/
│       └── init_db.py      # Excel转SQLite
├── frontend/               # React前端
│   └── src/
│       ├── pages/          # 页面组件
│       │   └── TTWODashboard.tsx  # TT&WO Dashboard
│       ├── api.ts          # API客户端
│       └── App.tsx         # 主应用
├── db/                     # 数据库目录
│   ├── app.db              # SQLite数据库
│   └── uploads/            # 上传文件存储
└── requirements.txt
```

## 快速启动

### 1. 初始化数据库（Excel转SQLite）

```powershell
cd D:\01_RPA\Task\my_app
python backend/scripts/init_db.py
```

### 2. 启动后端

```powershell
cd D:\01_RPA\Task\my_app
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 启动前端

```powershell
cd D:\01_RPA\Task\my_app\frontend
npm run dev
```

### 4. 访问

- 前端: http://localhost:5173
- 后端API: http://localhost:8000/docs (Swagger文档)

## 功能模块

### 数据总览
- 数据库概览统计
- 表数据量排行
- 数据分布图

### 表浏览器
- 分页浏览数据
- 字段画像分析（空值率、唯一值、分布、离群值）
- 自动类型推断与质量评分

### 数据上传
- 拖拽上传Excel/CSV
- 自动字段识别与建表
- 实时质量分析

### 分析仪表盘
- 自动生成多维图表
- 饼图（分类分布）
- 柱状图（维度对比）
- 折线图（时间趋势）
- 雷达图（质量评分）
- 热力图（SLA达成/交叉分析）
- 图表联动筛选（点击饼图/柱状图过滤关联图表）
- 归档保存

### TT&WO Dashboard
- 时间窗口/区域筛选 + 同步状态
- TT统计卡片：Alarm/Ticket Severity、SLA Status、Status
- MTTR周趋势图（折线MTTR + 柱状TT数量）
- Domain分布柱状图
- Root Cause/Sub Root Cause双饼图联动
- WO Source/Status分类柱状图
- 站点Power Sources、Power Vendor、维护团队统计

### GIS地图
- 站点地理分布（805个站点，自动修正经纬度交换错误）
- 按区域筛选
- 站点着色（严重/警告/VIP/正常）
- 时间窗口过滤（全部/近7天/近30天/近3月/近6月/自定义）
- 区域蒙层（IQR+距离双层离群点过滤，凸包边界）
- 拓扑连线（Hub站加粗，可开关）
- 点击下钻：TT/WO明细、SLA达成、字段排序/筛选/搜索/导出

### 数据同步
- FTP定时同步（每小时第22分钟自动下载TT/WO文件）
- 手动触发同步
- 同步状态实时显示（Synced/Not synced）
- 同步历史记录

### 分析归档
- 永久保存分析结果
- 关键词检索
- 完整快照回看

### 全局自动刷新（大屏 / NOC 场景，2026-08 新增）
- 顶栏「自动刷新」控件：关闭 / 30秒 / 1分钟 / 5分钟 / 10分钟 / 15分钟 / 30分钟，选择持久化到 localStorage（`myapp_auto_refresh_sec`）
- 未显式选择时所有页面默认开启，每 5 分钟刷新；顶栏可随时调整或关闭（全局生效）
- 刷新机制（App.tsx 外壳层统一实现，无需逐页改造）：到点后重挂载当前页面组件（`Fragment key` 变化 → 各页面 useEffect 重新取数；legacy iframe 页面因 cacheBust 变化整体重载）
- 软刷新协议：mw_ume_topology.html 监听 `postMessage {__type:'myapp-refresh'}`，在 iframe 内原地重拉 `/api/mw-ume/topology`（走后端 5 分钟 TTL 缓存），不重载文档——保留布局/日期/筛选/浏览器全屏状态，大屏不闪屏；独立直开该 HTML 时每 5 分钟自刷新兜底
- 防打扰：标签页在后台（document.hidden）、正在输入（焦点在 INPUT/TEXTAREA/SELECT/contenteditable）、antd 弹层打开（Modal/ImagePreview 锁 body 滚动，Drawer/Select/DatePicker open 态）、元素级全屏中跳过硬重挂载——本轮跳过、下个间隔再试

## 数据源

| 文件 | 表名 | 行数 | 说明 |
|------|------|------|------|
| Eflow_TT_FB.xlsx | eflow_tt | 23,769 | 故障工单 |
| Eflow_WO_FB.xlsx | eflow_wo | 3,732 | 工作单 |
| ZTE OLR MS Master Site Database.xlsx | master_site_db | 805 | 站点主数据 |
| 同上 | flm_database | 767 | FLM数据库 |
| 同上 | victim_topology | 764 | 拓扑关系 |
| 同上 | era_sites | 209 | ERA站点 |
| 同上 | satellite_sites | 187 | 卫星站点 |




---

## 原 §7 逐字备份（PROJECT_DOCS.md 第 1621-1682 行）

# 7. MS SLA 服务

# MS SLA / NUR 服务说明

## 概述

`ms_sla_service.py` 整合了原 `D:\01_RPA\Task\RAN\MS_SLA\ran_ume_sla.py` 和 `update_contract_kpis_report.py`，
作为 my_app 任务管理系统中的可调度任务运行。

## 任务列表

| task_id | 名称 | 默认调度 | 说明 |
|---|---|---|---|
| ms_sla_sync | RAN UME SLA 同步 | 每6小时 | 登录 RAN UME 网管 API，查询 GSM/UMTS/FDD SLA 指标，导入 SQLite 并上传 FTP |
| contract_kpis_report | Contract KPIs 报表 | 每天 4:00 | 更新 Contract KPIs 和 WOs SLA 报表并导出上传 |

## 数据流

### SLA 指标同步
```
RAN UME API (10.100.28.27:28001)
  → 登录鉴权 (RSA 加密)
  → 12 个并行查询 (3 tech × Sites/NW × 1Day/1Month)
  → 导出 xlsx → SQLite (lbr_ms_sla_kpi.sqlite3)
  → FTP 上传 → 清理本地文件
```

### 报表更新
```
FTP 下载 KPI List → 读取 NUR/SLA 数据 → 查询 SQLite → 更新 Excel 报表
→ 导出 xlsx/html/png → FTP 上传 → 清理旧文件
```

## 数据存放位置

- 数据根目录: `d:\01_RPA\Task\my_app\data\ms_sla\`
- 数据库: `data\ms_sla\lbr_ms_sla_kpi.sqlite3`
- 目标报表: `data\ms_sla\ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx`
- KPI List: `data\ms_sla\KPI list - Operation.xlsx`
- SLA 导出临时目录: `data\ms_sla\sla_exports\`

## FTP 配置

- 上传: `192.168.100.19` (ZTEEMS) → `/01_RPA/LBR_Tools/KPI/MS_SLA`
- 下载: `192.168.100.19` (FINEBI) → `/webroot/WEB-INF/schedule/NUR_SLA`

## RAN UME 网管配置

- 地址: `10.100.28.27:28001` (HTTPS)
- 用户: NOC
- 查询技术: GSM / UMTS / FDD
- 粒度: 1Day (86400s) / 1Month (2592000s)
- 层级: Sites / NW
- 并行线程: 4 (环境变量 SLA_PARALLEL_WORKERS)
- 回溯天数: 32 (环境变量 SLA_DAYS_BACK)

## 额外依赖

- `Pillow` (PNG 导出，可选)
- `cryptography` (RSA 登录加密，必须)




---

## 原 §9 逐字备份（PROJECT_DOCS.md 第 1842-1939 行）

# 9. 局域网访问（LAN Access）

# 局域网访问配置

Data Insight MVP 项目支持局域网内其他电脑通过 IP 地址访问。

> **注意**：本项目与 MTN_Comsal 项目共用端口（7038/7090），**不可同时运行**。

## 端口配置

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端 (FastAPI) | 7038 | uvicorn 监听 0.0.0.0 |
| 前端 (Vite) | 7090 | Vite dev server 监听 0.0.0.0 |
| PostgreSQL | 5432 | 允许局域网内其他电脑的 my_app 连接 |

## PostgreSQL 数据库局域网访问

其他电脑上的 my_app 需要连接本机 PostgreSQL 时，分两步：

1. 在本机以 **管理员身份** 运行 `setup_pg_lan_access.bat`，它会自动：
   - 在 `pg_hba.conf` 添加当前局域网网段的 scram-sha-256 访问规则
   - 重载 PostgreSQL 配置
   - Windows 防火墙放行 TCP 5432
2. 其他电脑的 `backend/.env` 中，`DATABASE_URL` 指向本机局域网 IP：

   ```
   DATABASE_URL=postgresql://myapp:密码@<本机IP>:5432/myapp
   MY_APP_DB_MODE=pg
   ```

   例如本机 IP 为 `192.168.100.20` 时写为 `postgresql://myapp:密码@192.168.100.20:5432/myapp`。

注意：如果本机 IP 在 DHCP 下变化，需要同步修改各电脑 `.env` 中的 IP。

## 配置步骤

### 1. 配置防火墙（首次运行）

右键以**管理员身份**运行 `firewall_setup.bat`，自动放行 7090 和 7038 端口。

### 2. 启动服务

双击 `start.bat` 启动前后端服务。启动成功后会显示本机 IP 地址：

```
============================================
  Data Insight MVP is running!
============================================

  Local access:
    Frontend: http://localhost:7090
    Backend:  http://localhost:7038

  LAN access (for other computers):
    Frontend: http://192.168.1.101:7090
    Backend:  http://192.168.1.101:7038
```

### 3. 其他电脑访问

在浏览器输入本机 IP + 端口号：
- 前端：`http://<本机IP>:7090`
- 后端：`http://<本机IP>:7038`

## 确认本机 IP

如果不确定本机 IP，在命令行执行：

```batch
ipconfig | findstr /i "IPv4"
```

输出示例：
```
IPv4 Address. . . . . . . . . . . : 192.168.1.101
```

## 常见问题

### Q: 防火墙已配置，但其他电脑仍无法访问？

1. **确认 IP 地址正确**：本机 IP 可能变化，使用 `ipconfig` 重新查看
2. **确认服务已启动**：`start.bat` 窗口保持运行状态
3. **确认防火墙规则**：以管理员身份重新运行 `firewall_setup.bat`
4. **确认无端口冲突**：本项目与 MTN_Comsal 不可同时运行

### Q: 修改端口后如何更新配置？

需要同步修改以下 3 个文件：

1. `frontend/vite.config.ts` - 修改 `port` 和 `proxy.target`
2. `start.bat` - 修改 uvicorn 启动参数和显示信息
3. `firewall_setup.bat` - 修改端口号

修改完成后重新运行 `firewall_setup.bat` 更新防火墙规则。


