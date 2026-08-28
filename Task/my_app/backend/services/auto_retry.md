# 失败任务自动重试（auto_retry）

Task Manager 通用失败重试机制：对「最新一条执行记录为失败」的任务，若仍处于其调度周期的**时效窗口**内，自动重新投递运行。

## 运行方式

- 作为定时任务 `auto_retry_failed` 注册（默认 `*/10 * * * *`，每 10 分钟扫描一次）。
- 也可手动执行：`python backend/services/auto_retry.py` 或在 Task Manager 点击"立即执行"。
- 运行开始/结束均打印日志，并返回 `elapsed_seconds`（秒）。

## 时效窗口判定

- 用任务当前 cron 计算「失败时刻之后的下一个调度触发时刻」作为窗口终点：
  - `now < 下一触发时刻`：仍在失败那一期的周期内，重试产出的还是同一期数据 → 重试；
  - `now >= 下一触发时刻`：已进入新一期 → 放弃（记为 expired）。
- cron 无法解析时降级为固定 24 小时窗口。

## 过滤条件（任一命中即跳过）

| 条件 | 说明 |
| --- | --- |
| 排除集 | 自身 `auto_retry_failed`；邮件类任务（由 `email_recovery` 专属补发，避免双重补发） |
| 重试次数上限 | 同一失败链（上次成功之后）最多 `AUTO_RETRY_MAX_ATTEMPTS` 次 |
| 冷却时间 | 两次自动重试间隔不小于 `AUTO_RETRY_COOLDOWN_MIN` 分钟 |
| 永久错误 | 错误信息含 `BUDGET_EXCEEDED` / `已禁用` / `未找到` / `无效的 cron` |
| 运行中 | `is_task_running` 为真（兼容队列模式跨进程状态） |
| 单次风暴保护 | 单次扫描最多触发 `AUTO_RETRY_MAX_PER_RUN` 个重试 |

失败后若已有成功记录（正常调度 / recovery 补发），最新记录不再是失败，天然跳过。

## 重试投递

调用 `task_runner.run_task_async(task_id, trigger="auto_retry")`：
- 队列模式下投递 `task_queue` 由 Worker 执行，自动受单飞保护；
- 重试记录以 `trigger_type='auto_retry'` 写入 `task_execution_log`，Run History 可见。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AUTO_RETRY_ENABLED` | `1` | 总开关 |
| `AUTO_RETRY_MAX_ATTEMPTS` | `2` | 同一失败链最多自动重试次数 |
| `AUTO_RETRY_COOLDOWN_MIN` | `15` | 两次自动重试最小间隔（分钟） |
| `AUTO_RETRY_SCAN_WINDOW_HOURS` | `24` | 失败记录扫描窗口（小时），兼作 cron 解析失败的降级窗口 |
| `AUTO_RETRY_MAX_PER_RUN` | `3` | 单次扫描最多触发的重试个数 |
| `AUTO_RETRY_EXTRA_EXCLUDE` | 空 | 追加排除的 task_id（逗号分隔） |
| `AUTO_RETRY_INCLUDE_EMAIL` | `0` | `=1` 时把邮件类任务也纳入（默认排除） |

## 相关文件

- `backend/services/auto_retry.py` —— 本机制实现
- `backend/task_registry.py` —— `auto_retry_failed` 任务注册
- `backend/worker_watchdog.py` —— Worker 分组（m 组）认领清单
- `frontend/src/pages/DataSync.tsx` —— Task Manager "失败自愈" 分组展示
