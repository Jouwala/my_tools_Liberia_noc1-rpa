"""Backend 看门狗 (Watchdog) —— 保证 uvicorn backend 持续运行、崩溃/被杀自动拉起

设计要点（与 backend.worker_watchdog 对齐）：
- 本进程是 uvicorn 的父进程（subprocess 托管），轮询子进程存活；
- uvicorn 异常退出（崩溃 / 被误杀）后，按退避策略自动重新拉起；
- 除进程存活外，额外做端口探活：若进程活着但端口 7038 长时间未监听，
  判定为"启动挂死 / 内部卡死"，主动重启，避免僵尸 backend 占着坑不服务；
- 停止：stop.bat 树杀本进程 (taskkill /PID <watchdog> /T /F)，连带 uvicorn 一起停，
  且本进程被树杀后不会再复活 uvicorn（_shutdown 置位）；
- 自身 PID 写入 backend/backend_watchdog.pid，供 stop.bat 定位。

启动（替代原 start.bat 中的 `start "Backend" ... uvicorn ...`）：
    python -m backend.backend_watchdog
"""
import os
import sys
import time
import json
import signal
import logging
import subprocess
import socket
from datetime import datetime
from pathlib import Path

# 项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

PID_FILE = Path(os.environ.get(
    "MY_APP_BACKEND_WATCHDOG_PID",
    str(BACKEND_DIR / "backend_watchdog.pid")
))
LOG_DIR = PROJECT_ROOT / "log"
BACKEND_LOG = LOG_DIR / "backend_runtime.log"
WATCHDOG_LOG = LOG_DIR / "backend_watchdog.log"

PORT = int(os.environ.get("MY_APP_BACKEND_PORT", "7038"))

POLL_INTERVAL = 2.0        # 子进程状态轮询间隔（秒）
CRASH_THRESHOLD = 10.0     # 子进程存活短于此值（秒）视为异常崩溃
MAX_BACKOFF = 30.0         # 最大退避间隔（秒）
STARTUP_FAIL_LIMIT = 10    # 连续快速崩溃达到此次数则放弃并告警
STARTUP_GRACE = 60.0       # 进程存活但端口未监听超过此时长，判定启动挂死

logger = logging.getLogger("backend_watchdog")

_shutdown = False
_child = None              # uvicorn 子进程 Popen
_spawn_time = 0.0          # 最近一次拉起时间戳
_crashes = 0               # 连续崩溃计数
_backoff = 0.0             # 当前退避秒数

# 心跳文件：供外部守护（start_hidden.ps1 / MyApp_EnsureRunning）判断看门狗是否卡死。
# 进程在但心跳超过 3 分钟未更新 → 判定 hung，由守护脚本强杀后重新拉起。
HB_FILE = LOG_DIR / "heartbeat_backend_watchdog.json"
_last_hb = 0.0
_HB_INTERVAL = 15.0        # 心跳写入间隔（秒），2s 轮询循环下约每 15s 落盘一次


def _request_shutdown(signum, _frame):
    global _shutdown
    _shutdown = True
    logger.info(f"收到退出信号 ({signum})，准备停止 backend 并退出...")


def _another_watchdog_running() -> bool:
    """检查是否已有 watchdog 实例在跑（避免重复托管导致双 backend 抢端口）。"""
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
            # 显式 restype：ctypes 默认按 32 位 int 截断 64 位句柄，存活进程
            # 可能被误判为不存在 → 重复启动第二个 backend 抢 7038 端口。
            #
            # 用 PROCESS_QUERY_LIMITED_INFORMATION(0x1000)，不要用
            # PROCESS_QUERY_INFORMATION(0x0400)：后者受 Windows 完整性级别(MIC)
            # 约束——由计划任务 MyApp_AutoStart(RunLevel=Highest) 启动的进程完整性
            # 级别为 High，普通会话/定时任务(Medium) 对其 OpenProcess(0x0400) 直接
            # 返回 NULL，于是被误判为"watchdog 已死"并拉起第二个实例，两个 watchdog
            # 争抢 7038 端口导致 backend 反复 exit_code=3 崩溃。
            # 0x1000 仅查询进程存在性，不受 MIC 限制，足以完成存活判定。
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                kernel32.CloseHandle(h)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, AttributeError, Exception):
        return False


def _port_listening(port: int) -> bool:
    """端口探活：能否连上 127.0.0.1:port。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _write_heartbeat():
    """周期性写心跳文件（节流），供外部守护检测看门狗卡死。"""
    global _last_hb
    now = time.time()
    if now - _last_hb < _HB_INTERVAL:
        return
    _last_hb = now
    try:
        HB_FILE.write_text(
            json.dumps({
                "name": "backend_watchdog",
                "pid": os.getpid(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _spawn_backend():
    """拉起 uvicorn 子进程，stdout/stderr 重定向到 backend_runtime.log（追加）。
    与 start.bat 保持一致：MY_APP_TASK_QUEUE=1，并清除 WorkBuddy 安全删除守卫变量。"""
    global _child, _spawn_time
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    log_fh = open(BACKEND_LOG, "ab", buffering=0)
    env = os.environ.copy()
    env["MY_APP_TASK_QUEUE"] = "1"
    # eFlow API 超时加固：默认连 10s / 读 30s / 重试 2 次（可由外部环境变量覆盖）。
    # 原默认读超时 90s 且多次重试会叠加，eFlow 接口偶发变慢时单任务可被拖数十分钟，
    # 表现为「同步很久 / 假运行中」。缩短后慢接口更快失败并被重试，不再无限卡。
    env["EFLOW_CONNECT_TIMEOUT"] = os.environ.get("EFLOW_CONNECT_TIMEOUT", "10")
    env["EFLOW_READ_TIMEOUT"] = os.environ.get("EFLOW_READ_TIMEOUT", "30")
    env["EFLOW_HTTP_MAX_RETRIES"] = os.environ.get("EFLOW_HTTP_MAX_RETRIES", "2")
    env.pop("CODEBUDDY_SESSION_ID", None)
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("CODEBUDDY_SAFE_DELETE_SANDBOX", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "0.0.0.0", "--port", str(PORT),
         # nginx 直连本机 7038 时，靠 X-Forwarded-For 还原真实客户端地址；
         # 否则所有请求都显示为 127.0.0.1，会绕过 require_protected 的远程限制。
         "--proxy-headers"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        creationflags=creationflags,
    )
    _child = proc
    _spawn_time = time.time()
    logger.info(f"已拉起 backend: pid={proc.pid} (port={PORT}, task_queue=1)")
    return proc.pid


def _terminate_child():
    """终止 uvicorn 子进程。"""
    global _child
    if _child is not None:
        try:
            if _child.poll() is None:
                _child.kill()  # TerminateProcess：确保子进程退出
                try:
                    _child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as e:
            logger.warning(f"终止 backend 子进程失败: {e}")
    _child = None


def _loop_once() -> bool:
    """单轮主循环：确保 backend 存活 + 端口探活 + 等待退出。

    返回 False 表示应退出看门狗（收到停止信号 / 连续崩溃达上限）；
    抛出的未预期异常由 main() 统一捕获记录，防止看门狗静默死亡。
    """
    global _child, _crashes, _backoff, _spawn_time
    proc = _child
    # 1) 确保 backend 在跑
    if proc is None or proc.poll() is not None:
        if proc is not None:
            exit_code = proc.returncode
            lived = time.time() - _spawn_time
            logger.warning(
                f"backend 已退出 (exit_code={exit_code}, 存活 {lived:.1f}s)，准备重新拉起"
            )
            _child = None
            if _shutdown:
                return False
            if lived < CRASH_THRESHOLD:
                _crashes += 1
                _backoff = min(MAX_BACKOFF, 2 ** _crashes)
                logger.warning(
                    f"backend 异常崩溃（存活过短），连续崩溃 {_crashes} 次，"
                    f"下次退避 {_backoff:.1f}s"
                )
                if _crashes >= STARTUP_FAIL_LIMIT:
                    logger.error(
                        f"backend 连续崩溃 {STARTUP_FAIL_LIMIT} 次，停止自动拉起"
                        f"（请检查 backend_runtime.log）。"
                    )
                    return False
            else:
                _crashes = 0
                _backoff = 0.0
        # 退避：连续快速崩溃时延迟重拉，避免死循环
        if _backoff > 0:
            logger.info(f"backend 退避等待 {_backoff:.1f}s 后重拉")
            waited = 0.0
            while waited < _backoff and not _shutdown:
                time.sleep(min(POLL_INTERVAL, _backoff - waited))
                waited += POLL_INTERVAL
            if _shutdown:
                return False
        _spawn_backend()
        return True
    # 2) backend 存活：端口探活（检测"进程在但端口没起来"的挂死）
    if _port_listening(PORT):
        _crashes = 0
        _backoff = 0.0
    else:
        no_port_for = time.time() - _spawn_time
        if no_port_for > STARTUP_GRACE:
            logger.warning(
                f"backend 进程存活但端口 {PORT} 超过 {STARTUP_GRACE:.0f}s 未监听，"
                f"判定启动挂死，重启"
            )
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
            _child = None
            _crashes += 1
            _backoff = min(MAX_BACKOFF, 2 ** _crashes)
            if _crashes >= STARTUP_FAIL_LIMIT:
                logger.error(
                    f"backend 连续崩溃 {STARTUP_FAIL_LIMIT} 次，停止自动拉起"
                    f"（请检查 backend_runtime.log）。"
                )
                return False
            return True
    # 3) 等待子进程（超时即仍在运行）
    try:
        proc.wait(timeout=POLL_INTERVAL)
    except subprocess.TimeoutExpired:
        pass
    # 4) backend 退出（wait 返回且 poll 非 None）→ 下一轮循环处理
    return True


def main():
    global _child, _crashes, _backoff, _spawn_time
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
        logger.error("已有 backend watchdog 在运行，拒绝重复启动。退出。")
        sys.exit(1)

    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"watchdog PID 文件写入失败: {e}")

    logger.info(f"Backend Watchdog 启动: project_root={PROJECT_ROOT}, backend_log={BACKEND_LOG}, port={PORT}")

    try:
        # 首拉（若 7038 已被外部进程占用，uvicorn 会绑定失败并退出，进入崩溃退避，
        # 不会造成双实例；运维上由启动脚本在拉起前清理孤儿端口）。
        _spawn_backend()
        while not _shutdown:
            try:
                _write_heartbeat()
                if not _loop_once():
                    break
            except Exception:
                # 2026-08-15 加固：主循环任何未预期异常都必须记录并继续，
                # 否则看门狗会静默死亡（无日志），自愈链断裂。
                logger.exception("backend_watchdog 主循环异常，已捕获并继续（防止看门狗静默死亡）")
                try:
                    time.sleep(5)
                except Exception:
                    pass
    finally:
        _terminate_child()
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass
        logger.info("Backend Watchdog 已退出")


if __name__ == "__main__":
    main()
