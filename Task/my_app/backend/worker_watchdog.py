"""Worker 看门狗 (Watchdog) —— 保证 backend.worker 持续运行、崩溃自动拉起

设计要点：
- 本进程是 worker 的父进程（subprocess 托管），轮询子进程存活；
- worker 异常退出（崩溃 / 被误杀）后，按退避策略自动重新拉起；
  worker.py 自身仍会把 PID 写入 backend/worker.pid，stop.bat 原机制继续可用；
- 停止：stop.bat 树杀本进程 (taskkill /PID <watchdog> /T /F)，连带 worker 一起停，
  且本进程被树杀后不会再复活 worker（_shutdown 置位）；
- 自身 PID 写入 backend/worker_watchdog.pid，供 stop.bat 定位。

启动（替代原 start.bat 中的 `python -m backend.worker`）：
    python -m backend.worker_watchdog
"""
import os
import sys
import time
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# 项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

PID_FILE = Path(os.environ.get(
    "MY_APP_WORKER_WATCHDOG_PID",
    str(BACKEND_DIR / "worker_watchdog.pid")
))
LOG_DIR = PROJECT_ROOT / "log"
WORKER_LOG = LOG_DIR / "worker_runtime.log"
WATCHDOG_LOG = LOG_DIR / "worker_watchdog.log"

POLL_INTERVAL = 2.0        # 子进程状态轮询间隔（秒）
CRASH_THRESHOLD = 10.0     # 子进程存活短于此值（秒）视为异常崩溃
MAX_BACKOFF = 30.0         # 最大退避间隔（秒）
STARTUP_FAIL_LIMIT = 10    # 连续快速崩溃达到此次数则放弃并告警

# ===== 多 worker 分组配置 =====
# MY_APP_WORKER_GROUPS=u,n,m：按数据源会话/写库把任务分成互不干扰的组，
# 每组一个独立 worker 进程并行消费；组内串行（与旧行为完全一致），组间并行
# （行为等价并发）。每组任务清单见 GROUP_TASK_MAP；未配置时保持单 worker 全量。
GROUP_TASK_MAP = {
    "u": (  # UME 192.168.170.2 单账号会话：必须串行
        "ran_ume_daily,main_kpi_sync,network_kpi_sync,packet_loss_sync,"
        "battery_kpi_sync,ipran_kpi_sync"),
    "n": (  # 网管 / eFlow API / 远程系统：各自独立但保守同组
        "eflow_sync,eflow_sync_full,eflow_active_alarm,eflow_history_alarm,"
        "ms_sla_full,cnn_kpi_sync,fw_kpi_sync,sp_data_sync"),
    "m": (  # 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖
        "site_outage_screenshot,whatsapp_send,liberia_email_1h,liberia_email_8h,"
        "kpi_ms_contract,kpi_ms_wo_sla,kpi_sp_spareparts,kpi_sp_consumables,"
        "kpi_ran_availability,email_recovery,ipran_m6k_chart_email,"
        "ccn_free_rating_chart_email,battery_email,mailbox_cleanup,"
        "incident_overview_sync,auto_retry_failed"),
}
_WORKER_GROUPS = [g.strip() for g in
                  os.environ.get("MY_APP_WORKER_GROUPS", "").split(",") if g.strip()]
_GROUPS = _WORKER_GROUPS or ["default"]

logger = logging.getLogger("worker_watchdog")

_shutdown = False
_children = {}          # group -> Popen
_spawn_time = {}        # group -> spawn 时间戳
_crashes = {}           # group -> 连续崩溃计数
_backoff = {}           # group -> 当前退避秒数


def _request_shutdown(signum, _frame):
    global _shutdown
    _shutdown = True
    logger.info(f"收到退出信号 ({signum})，准备停止 worker 并退出...")


def _another_watchdog_running() -> bool:
    """检查是否已有 watchdog 实例在跑（避免重复托管导致双 worker 抢队列）。"""
    if not PID_FILE.exists():
        return False
    try:
        pid_text = PID_FILE.read_text(encoding="utf-8").strip()
        if not pid_text:
            return False
        pid = int(pid_text)
    except (ValueError, OSError):
        return False
    if pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if h:
                kernel32.CloseHandle(h)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, AttributeError, Exception):
        return False


def _spawn_worker(group: str):
    """拉起一组 worker 子进程，stdout/stderr 重定向到 worker_runtime.log（追加）。
    分组 worker 带 MY_APP_WORKER_TASKS（仅认领本组任务）与独立 PID 文件。"""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_fh = open(WORKER_LOG, "ab", buffering=0)
    env = os.environ.copy()
    # eFlow API 超时加固（与 backend_watchdog 一致）：连 10s / 读 30s / 重试 2 次。
    # worker 才是 eflow_sync 的实际执行方，必须同样注入，否则仍用默认 90s 读超时。
    env["EFLOW_CONNECT_TIMEOUT"] = os.environ.get("EFLOW_CONNECT_TIMEOUT", "10")
    env["EFLOW_READ_TIMEOUT"] = os.environ.get("EFLOW_READ_TIMEOUT", "30")
    env["EFLOW_HTTP_MAX_RETRIES"] = os.environ.get("EFLOW_HTTP_MAX_RETRIES", "2")
    task_list = GROUP_TASK_MAP.get(group, "")
    if task_list:
        env["MY_APP_WORKER_TASKS"] = task_list
        env["MY_APP_WORKER_PID"] = str(BACKEND_DIR / f"worker_{group}.pid")
    else:
        # default 组（未分组场景）：保持原 PID 文件，stop.bat 兼容
        env.pop("MY_APP_WORKER_TASKS", None)
        env.pop("MY_APP_WORKER_PID", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.worker"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        creationflags=creationflags,
    )
    _children[group] = proc
    _spawn_time[group] = time.time()
    logger.info(f"已拉起 worker[{group}]: pid={proc.pid} tasks={task_list or '全部'}")
    return proc.pid


def _terminate_child():
    """终止所有 worker 子进程（按组）。"""
    for group, proc in list(_children.items()):
        try:
            if proc.poll() is None:
                proc.kill()  # TerminateProcess：确保子进程退出
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as e:
            logger.warning(f"终止 worker[{group}] 子进程失败: {e}")
    _children.clear()


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(WATCHDOG_LOG, encoding="utf-8")]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=handlers,
    )
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    if _another_watchdog_running():
        logger.error("已有 watchdog 在运行，拒绝重复启动。退出。")
        sys.exit(1)

    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"watchdog PID 文件写入失败: {e}")

    logger.info(f"Worker Watchdog 启动: project_root={PROJECT_ROOT}, worker_log={WORKER_LOG}, "
                f"groups={_GROUPS}")

    try:
        while not _shutdown:
            for group in _GROUPS:
                proc = _children.get(group)
                # 1) 确保该组 worker 在跑
                if proc is None or proc.poll() is not None:
                    if proc is not None:
                        exit_code = proc.returncode
                        lived = time.time() - _spawn_time.get(group, 0.0)
                        logger.warning(
                            f"worker[{group}] 已退出 (exit_code={exit_code}, 存活 {lived:.1f}s)，准备重新拉起"
                        )
                        _children.pop(group, None)
                    # 退避：连续快速崩溃时延迟重拉，避免死循环
                    if _backoff.get(group, 0.0) > 0:
                        logger.info(f"worker[{group}] 退避等待 {_backoff[group]:.1f}s 后重拉")
                        waited = 0.0
                        while waited < _backoff[group] and not _shutdown:
                            time.sleep(min(POLL_INTERVAL, _backoff[group] - waited))
                            waited += POLL_INTERVAL
                        if _shutdown:
                            break
                    _spawn_worker(group)
                    _crashes[group] = 0
                    _backoff[group] = 0.0
                    continue
                # 2) 该组 worker 存活，轮询等待（超时即仍在运行）
                try:
                    proc.wait(timeout=POLL_INTERVAL)
                except subprocess.TimeoutExpired:
                    if time.time() - _spawn_time.get(group, 0.0) >= CRASH_THRESHOLD:
                        _crashes[group] = 0
                        _backoff[group] = 0.0
                    continue
                # 3) worker 退出（wait 返回且 poll 非 None）
                exit_code = proc.returncode
                lived = time.time() - _spawn_time.get(group, 0.0)
                logger.warning(f"worker[{group}] 退出 (exit_code={exit_code}, 存活 {lived:.1f}s)")
                _children.pop(group, None)
                if _shutdown:
                    break
                if lived < CRASH_THRESHOLD:
                    _crashes[group] = _crashes.get(group, 0) + 1
                    _backoff[group] = min(MAX_BACKOFF, 2 ** _crashes[group])
                    logger.warning(
                        f"worker[{group}] 异常崩溃（存活过短），连续崩溃 {_crashes[group]} 次，"
                        f"下次退避 {_backoff[group]:.1f}s"
                    )
                    if _crashes[group] >= STARTUP_FAIL_LIMIT:
                        logger.error(
                            f"worker[{group}] 连续崩溃 {STARTUP_FAIL_LIMIT} 次，停止自动拉起"
                            f"（请检查 worker_runtime.log）。"
                        )
                        _GROUPS.remove(group)
                else:
                    _crashes[group] = 0
                    _backoff[group] = 0.0
    finally:
        _terminate_child()
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass
        logger.info("Worker Watchdog 已退出")


if __name__ == "__main__":
    main()
