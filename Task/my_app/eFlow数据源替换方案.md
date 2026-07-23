# eFlow API 数据源替换方案

## 1. 背景与目标

`my_app` 原先依赖 Excel/FTP 方式导入 TT、WO、Site、Alarm 等数据。为了数据更实时、减少手工操作，决定将数据源整体替换为 `get_eflow_table.py` 和 `get_eflow_realtime_alarm.py` 从 eFlow API 拉取的数据。

**核心目标：**

- 除拓扑数据外，所有看板数据均改为 API 数据源
- 保留 CR、PM 数据
- TT 的 `netWorkType` 字段用于 "Domain & Root Cause Analysis" 的 domain 维度
- 清理不再使用的旧表，减少数据库噪音

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          eFlow API                                   │
│  get_eflow_table.py  (TT/WO/CR/PM/Site/Person)                       │
│  get_eflow_realtime_alarm.py  (realtime_alarm)                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ 生成 eflow.sqlite3
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│            sync_from_eflow_api.py (字段映射 + 清洗)                   │
│   TT.Network Type ──► domain                                        │
│   WO.Domain ──► domain                                              │
│   毫秒时间戳 ──► 可读日期字符串                                       │
│   CR/PM 保留为独立表                                                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ 写入
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        my_app/db/app.db                              │
│  eflow_tt / eflow_wo / eflow_cr / eflow_pm / master_site_db          │
│  realtime_alarm / person / topology(保留)                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 文件变更清单

### 3.1 新增文件
| 文件 | 说明 |
|------|------|
| `backend/services/sync_from_eflow_api.py` | eFlow 数据同步核心服务 |

### 3.2 修改文件
| 文件 | 变更内容 |
|------|---------|
| `backend/main.py` | FTP 调度器 → eFlow API 同步调度器 |
| `backend/scripts/init_db.py` | 支持从 eflow.sqlite3 初始化 |
| `frontend/src/pages/DataSync.tsx` | FTP 配置界面 → eFlow API 配置界面 |
| `frontend/src/useDataTimestamps.ts` | `last_ftp_sync` → `last_sync` |
| `frontend/src/i18n.tsx` | FTP 相关翻译 → eFlow API 翻译 |

### 3.3 保留不变
| 文件 | 说明 |
|------|------|
| `backend/services/ftp_sync.py` | 保留作为备用方案 |
| `backend/import_topology.py` | 拓扑数据来源不变 |

---

## 4. 字段映射规则

### 4.1 TT 字段映射 (eflow.sqlite3 → app.db)
| eflow.sqlite3 列名 | app.db 列名 | 说明 |
|---------------------|-------------|------|
| Title | title | 工单标题 |
| WO No. | wo_no | 关联工单号 |
| Status | status | 状态 |
| Network Type | **domain** | 网络类型→域 |
| Alarm Severity | alarm_severity | 告警级别 |
| Ticket Severity | ticket_severity | 工单级别 |
| Site ID | site_id | 站点ID |
| Asset Name | site_name | 站点名称 |
| Created Time | created_time | 创建时间 |
| Occurrence Time | alarm_occur_time | 告警发生时间 |
| Alarm Clearing Time | alarm_clear_time | 告警清除时间 |
| SLA Status | sla_status | SLA状态 |
| Region Level1 | region_level1 | 一级区域 |

### 4.2 WO 字段映射
| eflow.sqlite3 列名 | app.db 列名 | 说明 |
|---------------------|-------------|------|
| WO No. | wo_no | 工单号 |
| TT NO. | tt_no | 关联TT号 |
| Work Order Title | title | 工单标题 |
| Domain | **domain** | 域 |
| RCA Main Category | rc_main_category | 根因主类 |
| RCA Sub Category | rc_sub_category | 根因子类 |

### 4.3 Site 字段映射 (→ master_site_db)
| eflow.sqlite3 列名 | app.db 列名 | 说明 |
|---------------------|-------------|------|
| Site ID | site_id | 站点ID |
| Site Name | site_name | 站点名称 |
| Region | region | 区域 |
| Province | province_county | 省/县 |
| Latitude | latitude | 纬度 |
| Longitude | longitude | 经度 |
| Site Maintainer | updated_fme_name_new | 维护团队 |

---

## 5. API 接口变更

### 旧接口 (FTP)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ftp/sync` | 手动触发FTP同步 |
| GET | `/api/ftp/status` | FTP同步状态 |

### 新接口 (eFlow API)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/eflow/sync` | 手动触发eFlow数据同步 |
| GET | `/api/eflow/status` | eFlow同步状态 |

### 数据时间戳接口变更
`GET /api/data-source/timestamps` 返回值：
- `last_ftp_sync` → `last_sync`
- 其他字段保持不变

---

## 6. 数据流

1. **数据采集**: `get_eflow_table.py` + `get_eflow_realtime_alarm.py` 定时运行，从 eFlow API 拉取数据写入 `ticket_export_rpa/eflow.sqlite3`
2. **数据同步**: `sync_from_eflow_api.py` 读取 `eflow.sqlite3`，进行字段映射和清洗后写入 `my_app/db/app.db`
3. **定时触发**: FastAPI 服务内 APScheduler 每小时第22分钟自动触发同步
4. **手动触发**: 前端"数据同步"页面或 API `POST /api/eflow/sync`

---

## 7. 运行方式

```bash
# 手动运行同步
cd d:\01_RPA\Task\my_app
python -m backend.services.sync_from_eflow_api

# 指定自定义路径
python -m backend.services.sync_from_eflow_api "path/to/eflow.sqlite3"

# 初始化数据库（优先使用 eFlow API 数据源）
python backend/scripts/init_db.py
```
