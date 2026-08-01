# iPRAN UME KPI 数据同步服务

## 概述

从 ZTE iPRAN UME 网管系统（https://10.100.2.99:28001/portal-athena）自动采集 IP RAN M6000 系列路由器性能指标（KPI），导出 Excel 并导入本地 SQLite 数据库，最后上传至 FTP 服务器。

## 任务信息

| 项目 | 值 |
|------|-----|
| task_id | `ipran_kpi_sync` |
| 分类 | `ipran_kpi` |
| 默认调度 | 每天凌晨 8 点（`0 8 * * *`） |
| 服务文件 | `backend/services/ipran_ume_kpi_service.py` |
| 数据目录 | `data/ipran_ume/` |
| 数据库 | `data/ipran_ume/ipran_ume_kpi.sqlite3` |
| FTP 目标 | `192.168.100.19:/01_RPA/LBR_Tools/KPI/IPRAN` |

## 执行流程

```
登录 iPRAN UME → 并行创建 KPI 查询 → 轮询等待完成 → 导出 Excel
→ 导入 SQLite（临时表去重）→ FTP 上传数据库 → 清理临时文件
```

## 查询配置

当前内置配置：

| 配置键 | 名称 | 粒度 | 表名 |
|--------|------|------|------|
| HQ_M6K_FW | HQ M6K-FW | 15mins (gr=900) | HQ_M6K_FW_bnctp_15mins |

扩展配置：将 `ipran_configs_generated.py` 放入 `backend/services/` 目录，导出 `IPRAN_KPI_QUERY_CONFIGS` 和 `IPRAN_KPI_TASKS` 即可自动加载。

## 去重策略

- 联合主键：`Begin Time` + 标识列（NE / ME / Managed Element / SERVICE / Measurement Object）
- 使用 SQL 临时表：DELETE 匹配行 → INSERT 新数据 → DROP 临时表

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| IPRAN_KPI_TIME_RANGE | 1month | 查询时间范围，可选值：`7days` / `14days` / `1month`（优先级高于 MONTHS_BACK） |
| IPRAN_KPI_MONTHS_BACK | 1 | 查询回溯月数（仅在 TIME_RANGE=1month 时生效） |
| IPRAN_KPI_PARALLEL_WORKERS | 4 | 并行查询线程数 |

## 依赖

- openpyxl
- cryptography（RSA 登录加密）

## 自包含说明

本服务完全自包含于 my_app 项目内，无外部目录引用：
- 数据存放：`data/ipran_ume/exports/`
- 数据库：`data/ipran_ume/ipran_ume_kpi.sqlite3`
- 配置扩展（可选）：`backend/services/ipran_configs_generated.py`
