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
