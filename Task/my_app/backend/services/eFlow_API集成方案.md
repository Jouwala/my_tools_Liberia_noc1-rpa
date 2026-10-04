# eFlow API 数据源集成方案

## 概述

将 `get_eflow_table.py` 和 `get_eflow_realtime_alarm.py` 两个外部脚本集成到 my_app 内部，实现 **API 直连模式**：直接从 ZTE 网管系统 eFlow API 获取数据并写入 app.db，无需中间 eflow.sqlite3 文件。

## 架构

```
eFlow API Client (eflow_api_client.py)
    ├── login() → 鉴权 (OAuth2 + RSA)
    ├── _fetch_tt_pipeline() → TT 工单数据
    ├── _fetch_wo_pipeline() → WO 工单数据
    ├── _fetch_cr_pipeline() → CR 变更数据
    ├── _fetch_pm_pipeline() → PM 巡检数据
    ├── _fetch_site_pipeline() → 站点数据
    ├── _fetch_person_pipeline() → 人员数据
    ├── _fetch_alarm_pipeline() → 实时告警数据
    └── fetch_all_data() → 并发获取所有数据
            │
            ▼
sync_from_eflow_api.py
    ├── _sync_tt() → eflow_tt 表 (字段映射: Network Type → domain)
    ├── _sync_wo() → eflow_wo 表 (字段映射: Domain → domain)
    ├── _sync_site() → master_site_db 表
    ├── _sync_realtime_alarm() → realtime_alarm 表
    ├── _sync_generic() → eflow_cr / eflow_pm / person 表
    └── sync_from_eflow_api() → 主同步入口
```

## 核心文件

| 文件 | 说明 |
|------|------|
| `backend/services/eflow_api_client.py` | API 客户端（登录 + 数据获取），合并原 get_eflow_table.py 和 get_eflow_realtime_alarm.py |
| `backend/services/sync_from_eflow_api.py` | 同步服务（字段映射 + 写入 app.db） |
| `backend/main.py` | FastAPI 主入口 + 定时同步调度器 |
| `backend/scripts/init_db.py` | 数据库初始化脚本 |
| `backend/requirements.txt` | Python 依赖 |

## 关键改进

1. **去掉 eflow.sqlite3 中间环节**：数据直接从 API 写入 app.db，无需依赖外部脚本
2. **统一日志**：使用 Python logging 替代 print
3. **环境变量配置**：HOST/PORT/用户名密码支持环境变量覆盖
4. **自动回退**：init_db.py 在 API 失败时自动回退到 Excel 文件初始化
5. **定时同步**：APScheduler 每小时第22分钟自动同步

## 数据流

```
ZTE eFlow API → eflow_api_client.py → dict{sheet_name: records}
                                              ↓
                          sync_from_eflow_api.py → app.db
```

### 同步的表

| API 数据 | app.db 表名 | 说明 |
|----------|-------------|------|
| eFlow TT | eflow_tt | TT 工单（Network Type → domain） |
| eFlow WO | eflow_wo | WO 工单（Domain → domain） |
| eFlow CR | eflow_cr | CR 变更单 |
| eFlow PM | eflow_pm | PM 巡检任务 |
| CMDB Site | master_site_db | 站点主数据 |
| CMDB Person | person | 人员数据 |
| FM Active Alarm | realtime_alarm | 实时告警 |

## 运行方式

### 手动触发同步

```bash
cd d:\01_RPA\Task\my_app
python -m backend.services.sync_from_eflow_api
```

### 通过 FastAPI 触发

```
POST http://localhost:8000/api/eflow/sync
GET  http://localhost:8000/api/eflow/status
```

### 定时自动同步

启动 FastAPI 服务后，APScheduler 每小时第22分钟自动执行同步。

## 依赖

新增依赖（已添加到 requirements.txt）：
- `cryptography>=41.0.0` — RSA 加密（登录鉴权）
- `apscheduler>=3.10.0` — 定时任务调度
- `xlsxwriter>=3.0.0` — Excel 导出（可选）

## 环境变量（可选）

```
EFLOW_HOST=10.100.20.8    # eFlow 服务器地址
EFLOW_PORT=28001           # eFlow 端口
EFLOW_USER=admin           # 登录用户名
EFLOW_PASS=<口令>          # 登录密码。优先级：环境变量 > 凭据库 eflow 组（设置页）
                           # 不设此变量时走设置页，改密免重启即时生效。
                           # ⚠ 不要把口令写进本文档（AGENTS.md 四.2）
```

## 运行验证结果

```
=== 数据库表汇总 ===
  eflow_tt: 25778 rows
  eflow_wo: 10000 rows
  eflow_cr: 192 rows
  eflow_pm: 1580 rows
  master_site_db: 808 rows
  person: 131 rows
  realtime_alarm: 0~8120 rows (视实时告警数量)

domain 字段分布:
  eflow_tt: RAN=25247, VMAX=241, TRM_IPRAN=189, TRM_MW=35
  eflow_wo: RAN=9805, TRM_MW=151, 4G=15
```
