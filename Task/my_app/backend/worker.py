"""独立任务执行 Worker 进程 —— 架构优化 Phase 3（调度与执行解耦）

架构：
- Web 进程（uvicorn backend.main:app）：只负责 APScheduler 定时触发与 API 手动触发，
  两者均仅向 task_queue 表投递（MY_APP_TASK_QUEUE=1），不再在 Web 进程内执行任务，
  避免 27 个定时任务与 HTTP 请求争抢线程 / SQLite 写锁。
- 本进程：轮询 task_queue，原子认领（UPDATE ... RETURNING）pending 记录并串行执行
  （复用 task_runner.run_task，执行日志照常写入 task_execution_log，跨进程可见）。
- 不依赖 Redis/RabbitMQ：SQLite task_queue 表即跨进程队列（busy_timeout 已配置）。

启动（在 my_app 根目录，由 start.bat 自动拉起）：
    python -m backend.worker

环境变量：
    MY_APP_WORKER_POLL   轮询间隔秒数（默认 2）
    MY_APP_WORKER_PID    PID 文件路径（默认 backend/worker.pid，供 stop.bat 精确停止）

容错：
- Worker 停止后 pending 任务不丢失，下次启动继续执行；
- 启动时将上次异常退出残留的 running 记录标记为 failed，避免永久卡死；
- 队列投递失败时 Web 端自动降级为进程内线程执行（见 task_runner.run_task_async）。
"""
import time
import json
import logging
import signal
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

_start_ts = time.time()

# 确保可以 import backend 模块（与 main.py 一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_raw_connection
from backend.services import task_runner
from backend.services.task_runner import DB_PATH, _ensure_queue_table
from backend.task_registry import register_all_tasks

logger = logging.getLogger("task_worker")

try:
    POLL_INTERVAL = max(1, int(os.environ.get("MY_APP_WORKER_POLL", "2")))
except (TypeError, ValueError):
    POLL_INTERVAL = 2

PID_FILE = Path(os.environ.get("MY_APP_WORKER_PID", str(Path(__file__).parent / "worker.pid")))

# 多 worker 分流：MY_APP_WORKER_TASKS=task1,task2,...（逗号分隔）时，本 worker
# 只认领清单内的任务；未设置 = 全量认领（与旧行为一致）。
# 分组由 worker_watchdog 按 MY_APP_WORKER_GROUPS 配置下发，保证同一数据源
# （UME/网管/eFlow 会话、写库）的任务永远落在同一 worker 串行执行，
# 不同数据源的任务跨 worker 并行（行为等价并发）。
_WORKER_TASKS = os.environ.get("MY_APP_WORKER_TASKS", "")
_worker_task_ids = {t.strip() for t in _WORKER_TASKS.split(",") if t.strip()} if _WORKER_TASKS else None

_shutdown = False


def _request_shutdown(signum, _frame):
    """信号处理：标记退出（当前任务执行完再退出，不中断运行中的任务）"""
    global _shutdown
    _shutdown = True
    logger.info(f"收到退出信号 ({signum})，当前任务完成后退出...")


# 残留 running 回收阈值：started_at 距今超过该秒数才视为残留。
# 多 worker 并发场景下，其他 worker 正在执行的任务也是 running 状态（可能长达
# 11 分钟），无时间门槛会把在跑任务误标 failed；异常退出后的残留最多延迟一个
# 阈值周期被回收，不会永久占用单飞名额。
STALE_RUNNING_SECONDS = 2 * 3600


def _recover_stale_running():
    """启动时回收上次 Worker 异常退出残留的 running 记录。

    仅回收 started_at 距今超过 STALE_RUNNING_SECONDS 的记录，避免误伤
    并行 worker 正在执行的任务。
    残留 running 若不处理会永久占用任务的单飞名额，导致该任务再也无法投递。

    防假阳性：回收前核对 task_execution_log——若该任务在「本次运行开始时间
    (started_at) 之后」已有 success=1 的执行记录，说明任务实际已成功、只是
    队列行未回写 finished（_finish 写库遇锁/超时失败，或进程在 run_task 返回与
    _finish 之间被强杀）。此时仅把队列行置为 done，不再补写失败记录，避免
    「成功却被记成失败」导致前端失败横幅多算；否则才按原逻辑标 failed 并补记录。
    """
    try:
        stale_cutoff = (datetime.now() - timedelta(seconds=STALE_RUNNING_SECONDS)).isoformat()
        recovered = []  # (task_id, trigger_type, started_at, marked_done)
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            task_runner._ensure_task_log_table(conn)
            rows = conn.execute(
                "SELECT id, task_id, trigger_type, started_at FROM task_queue "
                "WHERE status = 'running' AND started_at < ?",
                (stale_cutoff,),
            ).fetchall()
            now_iso = datetime.now().isoformat()
            for qid, task_id, trigger_type, started_at in rows:
                already_done = conn.execute(
                    "SELECT 1 FROM task_execution_log "
                    "WHERE task_id = ? AND success = 1 AND started_at >= ? LIMIT 1",
                    (task_id, started_at),
                ).fetchone()
                if already_done:
                    conn.execute(
                        "UPDATE task_queue SET status = 'done', finished_at = ? WHERE id = ?",
                        (now_iso, qid),
                    )
                    recovered.append((task_id, trigger_type, started_at, True))
                else:
                    conn.execute(
                        "UPDATE task_queue SET status = 'failed', finished_at = ?, "
                        "error = 'Worker 进程中断，任务未完成（启动时自动回收）' WHERE id = ?",
                        (now_iso, qid),
                    )
                    recovered.append((task_id, trigger_type, started_at, False))
            conn.commit()
            conn.close()
        for task_id, trigger_type, started_at, marked_done in recovered:
            if not marked_done:
                task_runner._save_task_result({
                    "task_id": task_id,
                    "task_name": task_runner._task_registry.get(task_id, {}).get("name"),
                    "category": task_runner._task_registry.get(task_id, {}).get("category"),
                    "trigger": trigger_type or "scheduled",
                    "success": False,
                    "started_at": started_at,
                    "completed_at": datetime.now().isoformat(),
                    "elapsed_seconds": None,
                    "result": None,
                    "error": "Worker 进程中断，任务未完成（启动时自动回收）",
                    "error_trace": None,
                })
        if recovered:
            real_failed = [r for r in recovered if not r[3]]
            logger.warning(
                f"已回收 {len(recovered)} 条上次 Worker 残留的 running 记录"
                + (f"（其中 {len(real_failed)} 条确为失败，{len(recovered) - len(real_failed)} 条实为成功已置 done）"
                   if real_failed else "（均为成功执行，未补写失败记录）")
            )
    except Exception as e:
        logger.warning(f"回收残留 running 记录失败: {e}")


def _claim_next():
    """原子认领一条 pending 记录：UPDATE+RETURNING 保证同一记录只会被一个执行者认领。
    设置了 MY_APP_WORKER_TASKS 时仅认领清单内任务（多 worker 分流）。"""
    with get_raw_connection(str(DB_PATH), timeout=30) as conn:
        _ensure_queue_table(conn)
        extra_where = ""
        params = [datetime.now().isoformat(), os.getpid()]
        if _worker_task_ids:
            marks = ",".join("?" for _ in _worker_task_ids)
            extra_where = f" AND task_id IN ({marks})"
            params.extend(sorted(_worker_task_ids))
        row = conn.execute(
            f"""UPDATE task_queue
               SET status = 'running', started_at = ?, worker_pid = ?
               WHERE id = (SELECT id FROM task_queue WHERE status = 'pending'{extra_where} ORDER BY id LIMIT 1)
               RETURNING id, task_id, trigger_type""",
            tuple(params),
        ).fetchone()
        conn.commit()
        conn.close()
    return row


def _finish(queue_id: int, success: bool, result, error: str | None):
    """回写队列记录终态，并按保留期清理历史（与执行日志同保留期）"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            # 若该队列记录已被用户停止（cancelled），不再覆盖为 done/failed，
            # 保留停止状态——避免「已停止却被回写为成功」的歧义（STOPPED_BY_USER
            # 执行日志已由停止逻辑写入）。否则会出现「停止日志 + 成功日志」并存。
            _cur = conn.execute(
                "SELECT status FROM task_queue WHERE id = ?", (queue_id,)
            ).fetchone()
            if _cur and _cur[0] == "cancelled":
                logger.info(f"队列记录 queue_id={queue_id} 已被用户停止(cancelled)，跳过回写终态")
                conn.close()
                return
            conn.execute(
                "UPDATE task_queue SET status = ?, finished_at = ?, result_json = ?, error = ? WHERE id = ?",
                ("done" if success else "failed", datetime.now().isoformat(),
                 json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                 error, queue_id),
            )
            try:
                _retention_days = max(1, int(os.environ.get("TASK_LOG_RETENTION_DAYS", "3")))
            except (TypeError, ValueError):
                _retention_days = 3
            # PG 无 datetime('now', '-N days')；改用 Python 计算截止时间，双模通用
            from datetime import timedelta
            _cutoff = (datetime.now() - timedelta(days=_retention_days)).isoformat()
            conn.execute(
                "DELETE FROM task_queue WHERE status IN ('done', 'failed', 'cancelled') "
                "AND created_at < ?",
                (_cutoff,),
            )
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"队列记录回写失败 (queue_id={queue_id}): {e}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    # PID 文件：供 stop.bat 精确定位并停止本进程
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"PID 文件写入失败（stop.bat 可能无法停止本进程）: {e}")

    n = register_all_tasks(task_runner)
    _recover_stale_running()
    logger.info(f"Task Worker 已启动：注册 {n} 个任务，轮询间隔 {POLL_INTERVAL}s，db={DB_PATH}")

    executed = 0
    last_recover_ts = time.time()
    try:
        while not _shutdown:
            # 周期性回收滞留的 running/pending 队列记录（不只启动时），避免陈旧记录长期
            # 滞留导致 running 状态卡死、手动触发被拒。每 300s 一次，开销极低。
            if time.time() - last_recover_ts >= 300:
                try:
                    _recover_stale_running()
                except Exception as e:
                    logger.warning(f"周期性回收残留记录失败: {e}")
                last_recover_ts = time.time()
            try:
                row = _claim_next()
            except Exception as e:
                logger.warning(f"轮询任务队列失败: {e}")
                row = None
            if row is None:
                time.sleep(POLL_INTERVAL)
                continue
            queue_id, task_id, trigger_type = row[0], row[1], row[2] or "scheduled"
            logger.info(f"认领任务 queue_id={queue_id} task={task_id} trigger={trigger_type}")
            if task_id not in task_runner._task_registry:
                _finish(queue_id, False, None, f"任务 {task_id} 未在 Worker 注册")
                continue
            t0 = time.time()
            result = task_runner.run_task(task_id, trigger=trigger_type)
            _finish(queue_id, bool(result.get("success")), result.get("result"), result.get("error"))
            executed += 1
            logger.info(
                f"任务完成 queue_id={queue_id} task={task_id} "
                f"success={result.get('success')} elapsed={time.time() - t0:.2f}s"
            )
    finally:
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass
        logger.info(f"Task Worker 已退出：本次执行 {executed} 个任务，总运行时长 {time.time() - _start_ts:.2f} 秒")


if __name__ == "__main__":
    main()
