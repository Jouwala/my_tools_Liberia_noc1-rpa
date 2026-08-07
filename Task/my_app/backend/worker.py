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
from datetime import datetime
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

_shutdown = False


def _request_shutdown(signum, _frame):
    """信号处理：标记退出（当前任务执行完再退出，不中断运行中的任务）"""
    global _shutdown
    _shutdown = True
    logger.info(f"收到退出信号 ({signum})，当前任务完成后退出...")


def _recover_stale_running():
    """启动时把上次 Worker 异常退出残留的 running 记录标记为 failed。

    残留 running 若不处理会永久占用任务的单飞名额，导致该任务再也无法投递。
    同时补一条 task_execution_log 失败记录，保证执行历史完整可追溯。
    """
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            rows = conn.execute(
                "SELECT id, task_id, trigger_type, started_at FROM task_queue WHERE status = 'running'"
            ).fetchall()
            if rows:
                conn.execute(
                    "UPDATE task_queue SET status = 'failed', finished_at = ?, "
                    "error = 'Worker 进程中断，任务未完成（启动时自动回收）' WHERE status = 'running'",
                    (datetime.now().isoformat(),),
                )
            conn.commit()
            conn.close()
        for qid, task_id, trigger_type, started_at in rows:
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
        if rows:
            logger.warning(f"已回收 {len(rows)} 条上次 Worker 残留的 running 记录")
    except Exception as e:
        logger.warning(f"回收残留 running 记录失败: {e}")


def _claim_next():
    """原子认领一条 pending 记录：UPDATE+RETURNING 保证同一记录只会被一个执行者认领。"""
    with get_raw_connection(str(DB_PATH), timeout=30) as conn:
        _ensure_queue_table(conn)
        row = conn.execute(
            """UPDATE task_queue
               SET status = 'running', started_at = ?
               WHERE id = (SELECT id FROM task_queue WHERE status = 'pending' ORDER BY id LIMIT 1)
               RETURNING id, task_id, trigger_type""",
            (datetime.now().isoformat(),),
        ).fetchone()
        conn.commit()
        conn.close()
    return row


def _finish(queue_id: int, success: bool, result, error: str | None):
    """回写队列记录终态，并按保留期清理历史（与执行日志同保留期）"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
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
                "DELETE FROM task_queue WHERE status IN ('done', 'failed') "
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
    try:
        while not _shutdown:
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
