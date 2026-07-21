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
