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
`sp_report_generate` 无历史记录）。每小时随巡检执行，4 个维度：

1. **注册表 vs 分组清单覆盖**（`group_missing`）：`task_registry.py::TASK_SPECS` 的 task_id 是否全部在
   `worker_watchdog.py::GROUP_TASK_MAP` 中（缺失 → 永远无 worker 认领；当前分组 u/n/v/m/c）
2. **回看窗口无执行记录**（`silent`）：`task_execution_log` 按任务 `MAX(started_at)` 一次 GROUP BY 取全，
   最近 24h 无记录则告警（已禁用任务从 `task_schedule_config` 排除）。
   2026-09-18 收紧：按任务 cron 缩放阈值——调度间隔大于窗口的低频任务（如每 3 天的
   `59 23 */3 * *`）未到下一期不算异常；cron 解析不出来则宁可多报（helper `_silent_task_candidates`）
3. **队列滞留**（`stuck`）：`task_queue` 中 pending 超 `TASK_HEALTH_PENDING_MAX_MINUTES`（10）分钟 /
   running 超 `TASK_HEALTH_RUNNING_MAX_MINUTES`（30）分钟的滞留记录（与 worker.py 回收阈值同源）
4. **成功逾期**（`overdue`）：上次成功之后按 cron 应再产出的周期已过（+一个周期 grace）仍无成功，
   补「24h 无记录」对小时级任务不敏感的盲区。2026-09-18 才发现：
   `_cron_next_and_interval` 把 aware 时间与 naive 时间相减抛 `TypeError` 被裸 `except` 吞掉，
   **本维度自 2026-08-13 上线以来默默禁用**（先算间隔再去时区，解析失败改为打 warning）
5. **逾期（外部依赖不可用）**（`overdue_dependency`，2026-09-18 晚新增）：`overdue` 的**子集**——
   该任务最新一次失败的 error 命中 `_DEPENDENCY_FAIL_KEYS`（EWS 401 / 连接失败 / 子进程超时等），
   即「任务跑了，是被外部依赖拖死的」而非自身停摆。判定只多查一次 `fail_latest`（`_task_health_db_query`
   返回值第 7 项，`{task_id: (error, started_at)}`），**不再多打一次库**。
   该任务**仍留在 `overdue` 里**（`status`/STALE 判定依赖它），本类只决定告警形态：
   全部依赖类任务聚合成**一条** STALE 项 + 一条告警，文案给出 EWS 侧修复指引；
   真停摆仍逐条报。理由：一次 EWS 故障会连带十几个报表任务各自"逾期"，逐条推送等于刷屏

均通过 `backend.database.get_raw_connection` 只读查询本机历史库（pg/sqlite 双模兼容），
表不存在（开发环境）视为“无可检查”不告警。

### 健康告警推送（2026-09-18 新增）

上面五类结果以前**只进日志**（本次停摆两天是用户先发现的），现接入 `backend/services/task_health_alert.py`
把 findings 推到人前（微信 `weixin_notifier` + 邮件 `email_notifier.send_status_email`）：

- **翻转去重**：以 `kind:task_id` 为键，状态文件 `TMP/task_health_alert_state.json`（原子写 tmp + `os.replace`），
  新增/恢复各通知一次，不再每小时刷屏
- **持续重提**：同一异常超过 `TASK_HEALTH_ALERT_RENOTIFY_HOURS`（默认 24h）再提一次
- **发送失败不算已通知**：`notified_at` 留空，下轮巡检自动重试
- **降噪**：`overdue` 只收“近 24h 连尝试都没有”的真停摆；“跑了但始终失败”已由
  `task_runner` 的失败告警通道通知过，不重复刷第二条（实跑发现：EWS 发信故障会连带 14 个报表任务“逾期”）
- **再降噪（`overdue_dependency`）**：上述连带里「最新失败是外部依赖不可用」的（EWS 401 / 连接失败 /
  子进程超时）聚合成一条，文案指向依赖侧（凭据/网络）；真停摆才逐条报
- **静音**：`TASK_HEALTH_ALERT_ENABLED=0`；告警异常不影响巡检结论（只记 warning）
- 自测：`python -m backend.services.task_health_alert`（演练不发真信）、
  `python tests\test_task_health_alert.py`、`python tests\test_task_health_detect.py`

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
- 扩展字段：`task_health_ok`（健康检查手段是否可用）、`task_health_issues`（异常项数）、
  `task_health_alert`（本次告警结果：new/renotify/resolved 条数，或静音/失败原因）

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
