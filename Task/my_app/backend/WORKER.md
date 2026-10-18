# backend/worker.py — 独立任务执行 Worker（架构优化 Phase 3，2026-08-06）

## 目标

把 27 个定时任务的**执行**从 Web 进程中剥离，避免重型任务（RAN UME、eFlow 同步、
邮件类等）与 HTTP 请求争抢线程和 SQLite 写锁。

## 架构

```
Web 进程 (uvicorn backend.main:app, MY_APP_TASK_QUEUE=1)
  ├─ APScheduler 定时触发 ──┐
  └─ API 手动触发 /api/tasks/{id}/run ──┤── enqueue_task() ──> task_queue 表 (app.db, status=pending)
                                                                    │
Worker 进程 (python -m backend.worker)  <──────────────────────────┘
  └─ 轮询认领 (UPDATE...RETURNING 原子操作) ──> task_runner.run_task()
       └─ 执行日志写 task_execution_log（跨进程可见）+ 回写队列终态 done/failed

Watchdog 进程 (python -m backend.worker_watchdog)  ── 父进程托管 worker
  └─ worker 崩溃/被杀后按退避策略自动重拉，保证 Last 不会因 worker 静默死亡而冻结
  └─ stop.bat 树杀 watchdog PID，连带 worker 一起停（不会复活）
```

- 队列载体：SQLite `task_queue` 表（status: pending / running / done / failed），
  不引入 Redis/RabbitMQ。
- 单飞保护：投递前检查同任务是否已有 pending/running 队列记录，拒绝重复投递。
- 串行执行：Worker 一次只执行一个任务（UME 单会话互踢、FTP 独占等资源约束与原语义一致）。

## 容错设计

| 场景 | 行为 |
|---|---|
| Worker 停止，队列有 pending | 任务不丢失，Worker 重启后继续执行 |
| Worker 异常退出留下 running | 下次启动自动标记 failed，并补一条 task_execution_log |
| **人为停机打断留下 running**（`stop.bat` 写过 `worker_stopping.flag`） | **重新入队**（running→pending）而非判失败，新 worker 会重新执行它；标记有 30 分钟 TTL，回收后即删（2026-10-06 修复） |
| Web 投递队列失败（DB 锁等） | 自动降级为进程内线程执行，任务不卡死 |
| 未启用队列（无 MY_APP_TASK_QUEUE=1） | 行为与改造前完全一致（进程内线程执行） |
| Worker 进程静默死亡（无 watchdog） | Last 冻结、任务不再执行且无任何报错（本次事故根因） |
| 看门狗托管（worker_watchdog） | worker 退出后自动重拉（异常崩溃退避最大 30s，连续 10 次放弃） |
| **重复启动看门狗**（PID 文件被删却没杀进程） | **第二个看门狗拒绝启动**：单例由命名互斥量保证，不看 PID 文件。2026-10-16 实测：只看 PID 文件的互斥检查当天叠出 5 套栈 / 40 个 worker → 128 条假失败 + 同一任务被执行两遍（WhatsApp 告警与邮件重发）。详见 `docs/manual/13-operations.md`「重复 worker 栈」 |

> **为什么要有「人为停机」这条分支**（2026-10-06 用户实测）：`stop.bat` 用
> `taskkill /T /F` 树杀看门狗，worker 随之中断，`finally` 里的 PID 文件自清来不及执行，
> 于是库里留下一条 `running` 残留。而 `stop.bat` 又会**删除** `backend\worker_*.pid`，
> 导致下次启动时 `task_runner._is_known_worker_pid()`（只读 PID **文件**、不核验进程）
> 认不出那个仍然存活的 PID，`worker.py` 便把它判成「PID 被无关进程复用 → 原 worker 已死」，
> 补写一条**失败**记录。任务本身没错，只是被重启打断 —— 但任务管理页会出现失败横幅。
> 修复：停机前先写 `worker_stopping.flag`，回收时读到新鲜标记就**重新入队**。
> 注意标记**必须有 TTL**：否则一台机器上遗留的旧标记会把真实的进程崩溃也误判成
> 「人为停机」而重新入队，反而**掩盖故障**。回归守卫见
> `tests/test_engineering_guards.py` 的守卫 11，标记文件的入库禁令见守卫 12。

## 启停

- 启动：`start.bat` / `start_hidden.vbs` 自动拉起**看门狗**（`python -m backend.worker_watchdog`，
  窗口标题 TaskWorkerWatchdog，日志 `worker_watchdog.log`），由看门狗托管 worker
  （**每组一个日志文件**：`worker_runtime_u_<日期>.log` / `_n_` / `_v_` / `_m_` / `_c_`，2026-09-11 起带日期以配合
  `log_cleanup` 做 7 天保留；未分组时用 `worker_runtime_<日期>.log`）
- 停止：`stop.bat` **先树杀看门狗**（`backend/worker_watchdog.pid` + `taskkill /T /F`），连带 worker 一起停且不会复活；
  随后按 `backend/worker.pid` 兜底清理（看门狗未启用时仍可用）
- 查"是否已有看门狗"：`python -m backend.worker_watchdog --probe`（退出码 `0=已有 / 3=没有 / 4=判不了`）。
  互斥量在 `Global\` 建；缺 `SeCreateGlobalPrivilege` 的普通会话退到 `Local\`，
  但**打开**已存在的 Global 对象不需要该特权，所以跨完整性级别仍能检出（打不开一律保守判"已有"）。
- ⚠ **禁止只删 `backend/*.pid` 当作"已经停了"**：PID 文件是 `stop.bat` 定位进程用的索引，
  不是存活判据。撕了索引而进程照跑，`start_hidden.ps1` / `restart_workers.py` 就会再叠一套栈。
  重启只准 `stop.bat` → `start.bat`（管理员），或 `restart_workers.py --mode watchdog`。
- 手动启动看门狗：在 my_app 根目录执行 `python -m backend.worker_watchdog`
- 手动启动 worker（无看门狗）：在 my_app 根目录执行 `python -m backend.worker`

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| MY_APP_TASK_QUEUE | 0 | Web 进程设为 1 时启用队列投递 |
| MY_APP_WORKER_POLL | 2 | Worker 轮询间隔（秒） |
| MY_APP_WORKER_PID | backend/worker.pid | PID 文件路径 |
| MY_APP_WORKER_WATCHDOG_PID | backend/worker_watchdog.pid | 看门狗 PID 文件路径（供 stop.bat 树杀） |
| TASK_LOG_RETENTION_DAYS | 7 | 队列历史记录保留天数（与执行日志一致，2026-09-11 由 3 天放宽为 7 天） |

## 依赖

无新增依赖（标准库 + 已有 backend 模块），见 backend/requirements.txt。
