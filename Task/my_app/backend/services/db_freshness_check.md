# 数据库数据新鲜度巡检（db_freshness_check）

## 背景

2026-08-11 曾发生：远程库 `ran_kpi_daily.sqlite3` 损坏 → db_writer_api 写入 HTTP 500 →
客户端静默回退本地 → 每日任务"假成功"但远程库长期断档。本巡检为该事件的兜底监控，
每小时自动核对远程库与本地回退库的数据是否为最新。

## 任务信息

| 项 | 值 |
|---|---|
| task_id | `db_freshness_check` |
| cron | `15 * * * *`（每小时第 15 分钟，避开各同步任务整点运行窗口） |
| 入口 | `backend/services/db_freshness_check.py::run_db_freshness_check` |
| category / gateway | `general` / `system` |

## 巡检范围

### 远程库（db_writer_api @ 192.168.100.19:8765）

| 库 | 粒度 | 新鲜度期望 | 产出任务 |
|---|---|---|---|
| ran_kpi_daily.sqlite3 | daily | 05:00 后期望有昨天数据（T+1） | network_kpi_sync |
| ran_kpi_daily_202606.sqlite3 | daily | 02:30 后 T+1 | ran_ume_daily |
| db.sqlite3 | daily | 04:30 后 T+1（Hourly 表设计上不同步，跳过） | main_kpi_sync |
| db_ps_cs_cn.sqlite3 | daily + monthly | 06:30 后 T+1；monthly 表 ≤33 天 | cnn_kpi_sync |
| ipran_ume_kpi.sqlite3 | 15min | 最新时间戳距 now ≤2h | ipran_kpi_sync |
| lbr_ms_sla_kpi.sqlite3 | 1day（日粒度 00:00:00） | 06:30 后 T+1 | ms_sla_full |

### 本地回退库（API 失败时的兜底写入位置）

- `backend/services/ran_kpi_daily.sqlite3`（network_kpi_sync 回退库）
- `data/ipran_ume/ipran_ume_kpi.sqlite3`
- `data/ms_sla/lbr_ms_sla_kpi.sqlite3`

本地库以只读方式打开（`mode=ro`），只记录最新日期供对照，不判定滞后
（本地库只在远程失败时才写入，无固定新鲜度要求）。

### 任务执行健康检查（2026-08-12 新增）

补齐“任务注册但从未执行”盲区（曾因 worker 分组清单漏配导致 `db_freshness_check`、
`sp_report_generate` 无历史记录）。每小时随巡检执行，3 个维度：

1. **注册表 vs 分组清单覆盖**：`task_registry.py::TASK_SPECS` 的 task_id 是否全部在
   `worker_watchdog.py::GROUP_TASK_MAP` 中（缺失 → 永远无 worker 认领）
2. **24h 无执行记录**：`task_execution_log` 按任务 `MAX(started_at)` 一次 GROUP BY 取全，
   最近 24h 无记录则告警（已禁用任务从 `task_schedule_config` 排除，避免误报）
3. **队列滞留**：`task_queue` 中 pending 超 10 分钟 / running 超 2 小时（参考 worker.py
   回收阈值）的滞留记录

均通过 `backend.database.get_raw_connection` 只读查询本机历史库（pg/sqlite 双模兼容），
表不存在（开发环境）视为“无可检查”不告警。

## 输出与判定

- `success`：仅表示“检查手段是否可用”（API 不可达 **或** 任务健康检查手段不可用
  （历史库连不上/配置加载失败）→ False，交给 auto_retry 重试）
- `fresh`：全部表数据新鲜且检查手段可用
- `stale[]`：滞后/异常清单（含数据滞后与任务健康异常两类）。每项包含：
  - **调用链路**：定时任务 → 服务函数 → 写入方式 → db_writer_api → 远程库文件
  - **检查方向**：任务运行历史、worker_runtime*.log（按 worker 分组）关键字、/health、
    integrity_check/.recover、UME 数据源、手动回补等 6 步
  - 若本地回退库已有数据，会额外提示“数据在本地，重跑任务即可回补”
  - 任务健康异常项输出对应修复指引（补分组清单、查队列滞留、确认 worker 存活等）
- 扩展字段：`task_health_ok`（健康检查手段是否可用）、`task_health_issues`（异常项数）

## 设计约定

- 数据滞后 / 任务健康异常均不置 `success=False`，避免 auto_retry 反复重跑巡检本身
- 全程只读，不写任何库
- 远程查询不传 `columns` 参数（服务端对带引号列名会报 SQL 语法错误），客户端求 max
- 任务历史查询用单条 `GROUP BY` 聚合（一次取全所有任务，避免逐任务 N+1）

## 运行

```powershell
# 手动执行一次
python d:\01_RPA\Task\my_app\backend\services\db_freshness_check.py
```

## 依赖

- 核心逻辑仅 Python 标准库；任务健康检查经 `backend.database` 连历史库，
  pg 模式下需 `psycopg2`、`python-dotenv`，见 `requirements_db_freshness_check.txt`。
