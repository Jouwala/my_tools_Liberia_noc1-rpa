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
import sqlite3
import sys
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

_start_ts = time.time()

# 确保可以 import backend 模块（与 main.py 一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_raw_connection
from backend.services import task_runner
from backend.services.task_runner import DB_PATH, _ensure_queue_table
from backend.task_registry import register_all_tasks, preload_common_deps

logger = logging.getLogger("task_worker")

try:
    POLL_INTERVAL = max(1, int(os.environ.get("MY_APP_WORKER_POLL", "2")))
except (TypeError, ValueError):
    POLL_INTERVAL = 2

PID_FILE = Path(os.environ.get("MY_APP_WORKER_PID", str(Path(__file__).parent / "worker.pid")))

# ---------------------------------------------------------------
# 日志落盘 + 孤儿 worker 自退（2026-11-04 新增）
#
# 背景（2026-11-03 eflow_sync 连续失败的根因）：
# watchdog 用 Popen(stdout=PIPE, stderr=STDOUT) 拉起 worker，再由 **watchdog 进程内**
# 的 daemon 泵线程把子进程输出写进日志文件（backend/log_writer.py）。watchdog 一死，
# 管道读端随之消失；仍存活的孤儿 worker 再写 stdout/stderr 就得到
# `OSError: [Errno 22] Invalid argument`，并因 traceback.print_exc 未受保护而升级成
# 任务失败（`同步异常: [Errno 22] Invalid argument`）。当日实测：旧 worker_pid=61920
# 在 watchdog 重启后未被杀掉，与新 worker 同组抢同一张 task_queue。
#
# 两道防线：
# 1) 本进程直接写「按组按日」的日志文件，不再依赖 stdout 管道（管道只作镜像）；
# 2) 由 watchdog 拉起时（注入 MY_APP_WORKER_WATCHDOG_PID / MY_APP_WORKER_GROUP），
#    周期检查父进程是否仍在；父进程消失立即退出，不再抢队列、不再写断管道。
#    手动 `python -m backend.worker` 调试时父进程是终端/命令行，不启用守卫。
# ---------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent.parent / "log"
_WORKER_GROUP = (os.environ.get("MY_APP_WORKER_GROUP") or "default").strip() or "default"
_WATCHDOG_PID = os.environ.get("MY_APP_WORKER_WATCHDOG_PID", "").strip()
_PARENT_GUARD_INTERVAL = 5.0   # 秒；远小于一次调度周期，孤儿最多存活一轮
# 守卫状态：enabled / expected_pid / self_ticks（Windows 进程创建时间，用于识别 PID 复用）
_PARENT_GUARD_STATE = {"enabled": False, "expected": None, "self_ticks": None}


class _TolerantTextStream:
    """stdout/stderr 容错包装：管道读端消失时静默丢弃，不让裸 print 打断任务。

    2026-11-05 修复（承接 2026-11-04 的两道防线的第 3 道）：
    watchdog 用 ``Popen(stdout=PIPE, stderr=STDOUT)`` 拉起 worker，父进程退出或
    泵线程关闭读端后，子进程再写 stdout/stderr 会在 Windows 上抛
    ``OSError: [Errno 22] Invalid argument``。11-04 的修复让 **worker 自身**的
    logging 改走独占文件句柄，但业务模块里的裸 ``print()`` 仍直接打在管道上：
      - battary_kpi_fetch_socket.log()          -> print(...)，battery_kpi_sync 抛 Errno 22
      - db_writer_client._request()/write_data  -> print(...)，ipran/cnn 写入抛 Errno 22
      - eflow_sync                             -> 同步异常: [Errno 22] Invalid argument
    近 5 天共 20+ 次失败源于此，且错误文本伪装成网络/数据库故障，极易误判。

    worker 已有 _DailyFileHandler 独立落盘，控制台输出只是镜像，丢几行不影响排障；
    因此这里把写异常吞掉（logging 的 handleError 也是同一哲学），绝不让日志拖垮业务。
    手动调试（stdout 是 tty）时不包装，行为完全不变。
    """

    def __init__(self, inner):
        self._inner = inner

    def write(self, s):
        try:
            return self._inner.write(s)
        except (OSError, ValueError):
            # 模拟成功写入，避免 print() 内部据此再次抛错
            return len(s) if isinstance(s, str) else 0

    def flush(self):
        try:
            return self._inner.flush()
        except (OSError, ValueError):
            return None

    def __getattr__(self, name):
        # isatty / fileno / reconfigure / buffer / encoding 等一律转发给底层流
        return getattr(self._inner, name)


class _DailyFileHandler(logging.FileHandler):
    """按「组 + 日期」命名的日志文件，跨零点自动切换。

    为什么不用 TimedRotatingFileHandler：它的命名是 ``base.log.YYYY-MM-DD``，
    与运维约定的 ``worker_<group>_<date>.log`` 不一致；而 worker 可能长驻数日，
    只用启动时日期命名会把后几天的日志写进旧文件，排障时按日期找会漏。
    """

    def __init__(self, log_dir: Path, group: str):
        self._log_dir = Path(log_dir)
        self._group = group
        self._date = datetime.now().strftime("%Y%m%d")
        super().__init__(str(self._path()), encoding="utf-8", delay=False)

    def _path(self) -> Path:
        return self._log_dir / f"worker_{self._group}_{self._date}.log"

    def emit(self, record):
        # 切换文件本身的失败不能影响正常日志（emit 内异常由 logging 内部吞掉）
        try:
            today = datetime.now().strftime("%Y%m%d")
            if today != self._date:
                self._date = today
                self._flush_and_close_stream()
                self.baseFilename = str(self._path())
                self.stream = self._open()
        except Exception:
            pass
        super().emit(record)

    def _flush_and_close_stream(self):
        try:
            if self.stream is not None:
                self.stream.flush()
                self.stream.close()
        except Exception:
            pass
        self.stream = None


def _setup_worker_logging():
    """info 级日志：文件（按组按日，UTF-8）+ stderr 镜像（供 watchdog 泵写 worker_runtime）。

    文件句柄由本进程独占，watchdog 死亡不影响它；stderr 写失败由 logging 的
    handleError 内部吞掉，不会像裸 print/write 那样抛出 Errno 22。
    """
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    handlers = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = _DailyFileHandler(LOG_DIR, _WORKER_GROUP)
        fh.setFormatter(fmt)
        handlers.append(fh)
    except Exception as e:  # 文件日志不可用时不阻塞启动，stderr 镜像仍工作
        sys.stderr.write(f"worker 文件日志初始化失败（降级为仅控制台）: {e}\n")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    handlers.append(sh)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def _win_proc_info(pid):
    """Windows：返回 (进程创建时间FILETIME, 是否仍存活)；查询失败返回 None。

    创建时间用于识别 **PID 复用**：父进程死后其 PID 可能被系统分给新进程，
    此时 open 父 PID 仍成功，但新进程的创建时间一定晚于本 worker —— 据此判定孤儿。
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            k32.GetProcessTimes.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(wintypes.FILETIME),
                                            ctypes.POINTER(wintypes.FILETIME),
                                            ctypes.POINTER(wintypes.FILETIME),
                                            ctypes.POINTER(wintypes.FILETIME)]
            creation, exit_t, kernel_t, user_t = (
                wintypes.FILETIME(), wintypes.FILETIME(),
                wintypes.FILETIME(), wintypes.FILETIME(),
            )
            if not k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_t),
                                       ctypes.byref(kernel_t), ctypes.byref(user_t)):
                return None
            ec = wintypes.DWORD()
            k32.GetExitCodeProcess.restype = ctypes.c_int
            k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(wintypes.DWORD)]
            alive = bool(k32.GetExitCodeProcess(h, ctypes.byref(ec))) and ec.value == 259
            return (creation.dwHighDateTime << 32) | creation.dwLowDateTime, alive
        finally:
            try:
                k32.CloseHandle(h)
            except Exception:
                pass
    except Exception:
        return None


def _parent_alive() -> bool:
    """父进程（watchdog）是否仍存活。仅在守卫启用时被调用。"""
    st = _PARENT_GUARD_STATE
    ppid = os.getppid()
    if ppid <= 0:
        return False
    expected = st["expected"]
    if expected and ppid != expected:
        # 父进程变了：本进程已被系统重新挂到别的父进程（孤儿）
        return False
    if sys.platform == "win32":
        info = _win_proc_info(ppid)
        if info is None:
            return False                      # 父进程已不存在
        ticks, alive = info
        if not alive:
            return False                      # 已终止未回收的僵尸
        if st["self_ticks"] and ticks > st["self_ticks"]:
            return False                      # PID 被复用
        return True
    try:
        os.kill(ppid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _die_as_orphan():
    """判定为孤儿：刷日志后硬退出（不能回队列、不能再写断管道）。"""
    logger.critical(
        f"父进程 watchdog(pid={_PARENT_GUARD_STATE['expected']}) 已消失，"
        f"本 worker (group={_WORKER_GROUP}, pid={os.getpid()}) 判定为孤儿，立即退出"
    )
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    os._exit(3)


def _start_parent_guard():
    """由 watchdog 托管时启用父进程存活守卫（后台线程，避免长任务阻塞检测）。"""
    if not _WATCHDOG_PID:
        logger.info("未由 watchdog 托管（无 MY_APP_WORKER_WATCHDOG_PID），跳过父进程存活守卫")
        return
    try:
        expected = int(_WATCHDOG_PID)
    except ValueError:
        logger.warning(f"MY_APP_WORKER_WATCHDOG_PID 非法（{_WATCHDOG_PID!r}），跳过父进程存活守卫")
        return
    self_ticks = None
    if sys.platform == "win32":
        info = _win_proc_info(os.getpid())
        self_ticks = info[0] if info else None
    _PARENT_GUARD_STATE.update(enabled=True, expected=expected, self_ticks=self_ticks)

    def _loop():
        while True:
            try:
                if not _parent_alive():
                    _die_as_orphan()
            except Exception as e:  # 检查本身出错不误杀，留给下一轮
                logger.warning(f"父进程存活检查异常（忽略本轮）: {e}")
            time.sleep(_PARENT_GUARD_INTERVAL)

    threading.Thread(target=_loop, name="worker-parent-guard", daemon=True).start()
    logger.info(f"父进程存活守卫已启用: watchdog_pid={expected}, 间隔={_PARENT_GUARD_INTERVAL}s")


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
# 多 worker 并发场景下，其他 worker 正在执行的任务也是 running 状态，无时间门槛
# 会把在跑任务误标 failed；异常退出后的残留最多延迟一个阈值周期被回收。
# 2026-08-13 教训：旧值 2h 造成「失败不可见」盲区——失败后 2 小时内无失败日志
# （auto_retry 扫不到）且僵尸 running 挡住后续所有调度（eflow_sync 断档 3 小时）。
# 现改为 30 分钟，且配合 worker_pid 存活核对：pid 已死（或被无关进程复用）立即
# 回收；pid 存活且属于已知 worker 则不回收（pg_to_sqlite_sync 等长任务可跑 1h+，
# 2026-08-31 教训：按时间阈值回收在跑任务会导致重复投递 + SQLite 并发写坏快照）。
# 时间阈值仅在记录无 worker_pid（无法核对）时兜底。
try:
    STALE_RUNNING_SECONDS = max(300, int(os.environ.get("WORKER_STALE_RUNNING_SECONDS", str(30 * 60))))
except (TypeError, ValueError):
    STALE_RUNNING_SECONDS = 30 * 60

# 任务运行时长上限（2026-09-20 新增）：已知 worker 存活、但单条 running 记录超过
# 该时长时，判定为「进程活着但任务挂死」，由周期回收逻辑强杀该 worker（watchdog
# 会自动重拉），并把残留行标 failed 释放单飞名额。这是对「无超时网络调用」类
# 挂死的最终兜底——sp_data_sync 2026-09-20 事故中 SFTP channel 读挂死 5.5h，
# 整个 n 组（含 MW 实时看板、实时告警）停摆，旧回收逻辑因「pid 存活且已知」
# 永不回收。阈值默认 4h：sp_data_sync 实测最长 1.5~2h、pg_to_sqlite 全量 1h+，
# 4h 足够避开一切合法长任务。可用环境变量 WORKER_TASK_MAX_SECONDS 覆盖。
try:
    TASK_MAX_RUNNING_SECONDS = max(1800, int(os.environ.get("WORKER_TASK_MAX_SECONDS", str(4 * 3600))))
except (TypeError, ValueError):
    TASK_MAX_RUNNING_SECONDS = 4 * 3600

# 陈旧 pending 过期阈值（2026-09-18 新增）：分组模式下每个 worker 只认领
# MY_APP_WORKER_TASKS 白名单内的任务，一旦某任务漏登记 worker_watchdog.GROUP_TASK_MAP，
# 没有任何 worker 会认领它 → 这条 pending 永久滞留，并且占住 enqueue_task 的单飞名额
# （WHERE NOT EXISTS pending/running），把该任务之后的每一次调度静默挡掉。
# 2026-09-16 上线的 olib_soc_kpi_daily_sync / olib_soc_vmax_report / vmax_multi_data_sync
# 正是这样停摆：队列里挂着 09-16T19:45 / 09-17T02:20 两条 pending，task_execution_log
# 0 条记录，任务管理页却一直显示「队列中等待」，看门狗只在本组日志里打 STALE。
# 现在超过阈值仍无人认领的 pending 直接置 failed 并补一条执行日志（让巡检/自动重试
# 看得见、也能顺势重新投递），单飞名额同时释放，下一次调度恢复正常入队。
# 阈值取 6h：远大于正常积压（同组串行排队一般分钟级），不会误伤合法排队中的任务。
try:
    STALE_PENDING_SECONDS = max(1800, int(os.environ.get("WORKER_STALE_PENDING_SECONDS", str(6 * 3600))))
except (TypeError, ValueError):
    STALE_PENDING_SECONDS = 6 * 3600

# ---------------------------------------------------------------
# 人为停机标记（2026-10-06 新增）：把「重启打断」与「进程崩溃」区分开
#
# 背景：stop.bat 用 taskkill /F 硬杀 worker，正在跑的任务必然留下 running 残留。
# 下一轮启动时 _recover_stale_running 会把它标 **failed** 并补一条失败日志 →
# 任务管理页立刻出现失败横幅。用户实测「stop all / start all 后任务显示失败」，
# 但任务本身没错（只是被重启打断）。
#
# 方案：停机前由 stop.bat 写 backend/worker_stopping.flag；_recover_stale_running
# 读到该标记时，把打断的任务**重新入队（running→pending）**而不是判失败 ——
# 新 worker 启动后会重新执行它，等价于「优雅中断、稍后继续」。
#
# 安全性：
#   * 标记有**时效**（STOPPING_FLAG_TTL_SECONDS，默认 30 分钟）—— 过期即忽略，
#     避免上次停机遗留的标记永久掩盖真实的进程崩溃；
#   * 重新入队前仍走 already_done 检查：若该任务在 started_at 之后已成功执行过，
#     只置 done，不再重复投递（杜绝重复执行）；
#   * worker 启动完成回收后**立即删除标记**，防止同一标记被后续启动复用；
#   * 无标记时行为与旧版**逐字节一致**（仍判 failed），崩溃诊断能力不受影响。
# ---------------------------------------------------------------
STOPPING_FLAG_FILE = Path(os.environ.get(
    "MY_APP_WORKER_STOPPING_FLAG",
    str(Path(__file__).parent / "worker_stopping.flag")))
try:
    STOPPING_FLAG_TTL_SECONDS = max(
        60, int(os.environ.get("WORKER_STOPPING_FLAG_TTL_SECONDS", str(30 * 60))))
except (TypeError, ValueError):
    STOPPING_FLAG_TTL_SECONDS = 30 * 60


def _is_stopping_flagged() -> bool:
    """是否存在**新鲜的**人为停机标记（供 _recover_stale_running 判定）。

    过期（mtime 早于 TTL）或读取失败的标记一律视为不存在 —— 宁可回归
    「判失败」的保守行为，也不能让陈旧标记掩盖真实崩溃。
    """
    try:
        if not STOPPING_FLAG_FILE.exists():
            return False
        age = time.time() - STOPPING_FLAG_FILE.stat().st_mtime
        return age <= STOPPING_FLAG_TTL_SECONDS
    except OSError:
        return False


def _clear_stopping_flag() -> None:
    """回收完成后清除停机标记（防止被后续启动复用）。"""
    try:
        if STOPPING_FLAG_FILE.exists():
            STOPPING_FLAG_FILE.unlink()
    except OSError as e:
        logger.warning(f"清除停机标记失败: {e}")


def _pid_alive(pid) -> bool:
    """核对 worker_pid 是否仍存活（Windows 用 OpenProcess，POSIX 用 kill 0）。
    无法判定（pid 非法/权限异常）时保守返回 True，交给时间阈值兜底。

    2026-09-20 加固：Windows 上还要核对退出码。taskkill /F 对卡在内核调用
    （如无超时 SFTP 读）的进程发起终止后，进程对象可能长时间处于
    「已终止(exit_code=1) 但未回收」状态——OpenProcess 仍成功，但用户线程
    已全部销毁、不可能再执行任何任务。此前这种僵尸被判为"存活"，导致
    sp_data_sync 残留 running 行占用单飞名额 5.5h+。显式核对
    GetExitCodeProcess != STILL_ACTIVE(259) 即视为已死。"""
    try:
        pid = int(pid)
        if pid <= 0:
            return True  # 旧记录无 pid 信息，无法核对
    except (TypeError, ValueError):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes  # noqa: F401  确保 DWORD 可用
            kernel32 = ctypes.windll.kernel32
            # 必须显式设置 restype：ctypes 默认按 32 位有符号 int 解释返回值，
            # 64 位句柄高位被截断后可能变成 0/负数，把存活进程误判为不存在
            # （2026-08-14 事故：运行中任务被周期回收误标 failed，产生
            # 同一任务既成功又失败的矛盾记录）。
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False  # 打开失败=进程不存在（或无权限，本机自身进程不会无权限）
            try:
                STILL_ACTIVE = 259
                exit_code = ctypes.wintypes.DWORD()
                # GetExitCodeProcess 同样需要显式 restype/argtypes（64 位安全）
                kernel32.GetExitCodeProcess.restype = ctypes.c_int
                kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                                        ctypes.POINTER(ctypes.wintypes.DWORD)]
                if kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                    if exit_code.value != STILL_ACTIVE:
                        return False  # 已终止未回收的僵尸：不可能再执行任务
                # 退出码查询失败时保守视为存活，交由时间阈值兜底
            finally:
                kernel32.CloseHandle(h)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _recover_stale_running():
    """回收 Worker 异常退出残留的 running 记录（启动时 + 运行中每 300s 周期执行）。

    回收条件二选一：worker_pid 已死（进程崩溃，立即回收）或 started_at 超过
    STALE_RUNNING_SECONDS（pid 无法核对时的兜底）。核对 pid 可避免误伤并行
    worker 正在执行的任务。残留 running 若不处理会永久占用任务的单飞名额，
    导致后续调度触发被单飞保护拦截。

    防假阳性：回收前核对 task_execution_log——若该任务在「本次运行开始时间
    (started_at) 之后」已有 success=1 的执行记录，说明任务实际已成功、只是
    队列行未回写 finished（_finish 写库遇锁/超时失败，或进程在 run_task 返回与
    _finish 之间被强杀）。此时仅把队列行置为 done，不再补写失败记录，避免
    「成功却被记成失败」导致前端失败横幅多算；否则才按原逻辑标 failed 并补记录。

    人为停机（2026-10-06 新增）：若存在**新鲜的**停机标记（stop.bat 停机前写入，
    见 `_is_stopping_flagged`），说明这次残留是「被重启打断」而非「进程崩溃」——
    此时把任务 **重新入队（running→pending）** 而不是判失败，新 worker 启动后
    会重新执行它。已有成功记录（already_done）的情况仍优先置 done，杜绝重复执行。
    """
    try:
        stopping = _is_stopping_flagged()
        if stopping:
            logger.info("检测到人为停机标记：本次残留 running 将重新入队而非判失败")
        stale_cutoff = (datetime.now() - timedelta(seconds=STALE_RUNNING_SECONDS)).isoformat()
        recovered = []  # (task_id, trigger_type, started_at, marked_done)
        requeued = []   # (task_id, trigger_type, started_at)
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            task_runner._ensure_task_log_table(conn)
            rows = conn.execute(
                "SELECT id, task_id, trigger_type, started_at, worker_pid FROM task_queue "
                "WHERE status = 'running'",
            ).fetchall()
            now_iso = datetime.now().isoformat()
            for qid, task_id, trigger_type, started_at, worker_pid in rows:
                # 回收条件（2026-08-31 修复：pg_to_sqlite_sync 全量同步 1.5GB+ 可跑
                # 1 小时以上，旧逻辑 pid_alive OR too_old 会在 30 分钟时把仍在执行的
                # 任务误标 failed → 单飞保护失效 → 下一轮调度重复投递 → 两个同步进程
                # 同时 DROP/CREATE app.db，产生 database is locked / table already exists）：
                #   a) worker_pid 存活且属于已知 worker → 正在合法执行，无论多久都不回收；
                #   b) worker_pid 已死，或存活但不属于任何已知 worker（PID 被无关进程
                #      复用）→ 立即回收；
                #   c) 无 worker_pid（旧记录无法核对）→ 超过时间阈值才回收（原兜底）。
                pid_dead = False
                too_old = False
                try:
                    _pid_int = int(worker_pid)
                except (TypeError, ValueError):
                    _pid_int = None  # 无/坏 pid 信息：无法核对，走时间阈值兜底
                if _pid_int is not None:
                    if _pid_alive(_pid_int):
                        if task_runner._is_known_worker_pid(_pid_int):
                            # 活 worker 正在执行（长任务合法），正常不回收。
                            # 2026-09-20 兜底：单条记录运行超过 TASK_MAX_RUNNING_SECONDS
                            # 视为任务挂死（进程活着但不干活），强杀 worker 释放整组
                            # ——watchdog 会自动重拉，_pid_alive 的僵尸识别兜住回收窗口。
                            if started_at:
                                try:
                                    _ran = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds()
                                except ValueError:
                                    _ran = 0
                                if _ran > TASK_MAX_RUNNING_SECONDS:
                                    logger.error(
                                        f"任务 {task_id} 已运行 {_ran/3600:.1f}h 超过上限 "
                                        f"{TASK_MAX_RUNNING_SECONDS/3600:.1f}h，判定挂死，"
                                        f"强杀 worker(pid={_pid_int}) 释放单飞名额（watchdog 将自动重拉）"
                                    )
                                    task_runner._kill_worker_process(_pid_int)
                                    time.sleep(3)
                                    if _pid_alive(_pid_int):
                                        continue  # 击杀未生效（权限等）：不动它，下轮再试
                                    pid_dead = True
                                else:
                                    continue
                            else:
                                continue
                        # 2026-10-16：不在 pid 文件里 ≠ 原 worker 已死。当天叠了 5 套
                        # 看门狗，最后一套覆写了全部组 pid 文件，另外 4 套（32 个）正在
                        # 正常执行的 worker 因此全被判成"进程已失效"，12:00 后刷出 128 条
                        # 假失败。改为向操作系统核实：进程存活且镜像是 python/pythonw，
                        # 就认定它仍在合法执行、**不判失败**。但归属无法证明，所以不
                        # 强杀它（强杀只认 pid 文件，见 task_runner._kill_worker_process），
                        # 仅在超过 4h 上限时回收队列行，防止真挂死永久占住单飞名额。
                        if task_runner._looks_like_live_worker(_pid_int):
                            if started_at:
                                try:
                                    _ran = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds()
                                except ValueError:
                                    _ran = 0
                                if _ran > TASK_MAX_RUNNING_SECONDS:
                                    err = (f"任务超过 {TASK_MAX_RUNNING_SECONDS // 3600}h 未完成"
                                           f"（执行者 pid={_pid_int} 不在 Worker 注册表，"
                                           f"仅回收队列名额、不强杀进程）")
                                    conn.execute(
                                        "UPDATE task_queue SET status = 'failed', finished_at = ?, "
                                        "error = ? WHERE id = ?",
                                        (now_iso, err, qid),
                                    )
                                    recovered.append((task_id, trigger_type, started_at, False, err))
                            continue
                        pid_dead = True  # 进程已死，或 PID 被非 python 进程复用
                    else:
                        pid_dead = True
                else:
                    too_old = bool(started_at) and started_at < stale_cutoff
                if not (pid_dead or too_old):
                    continue
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
                    recovered.append((task_id, trigger_type, started_at, True, ""))
                elif stopping and pid_dead:
                    # 人为停机打断（stop.bat 写了标记）→ 重新入队，不判失败。
                    # 置回 pending 并清空 running 相关字段（started_at/worker_pid），
                    # 让新 worker 像对待一条普通待执行记录那样重新认领。
                    # 注意：这里只处理 pid_dead（进程确实已退出）。too_old 兜底
                    # （无 pid 无法核对，pid_dead 为 False）不走此分支，保持保守判失败。
                    conn.execute(
                        "UPDATE task_queue SET status = 'pending', started_at = NULL, "
                        "worker_pid = NULL WHERE id = ?",
                        (qid,),
                    )
                    requeued.append((task_id, trigger_type, started_at))
                else:
                    # 2026-09-30 修复措辞：旧文案一律写"Worker 进程中断"，但 pid 存活、
                    # 只是被新 worker 判定为"不属于已知 worker"时，进程其实**没中断**
                    # （典型：长任务挂死后人工重启服务栈，旧进程仍在后台挂着）。
                    # 那种情况写"进程中断"会把排查引向崩溃方向，而真实原因是任务挂死。
                    _reason = (
                        "Worker 进程已失效（PID 已退出或被重复占用），任务未完成"
                        if pid_dead else
                        f"任务超过 {TASK_MAX_RUNNING_SECONDS//3600}h 未完成（判定挂死），"
                        f"已回收队列名额"
                    )
                    err = f"{_reason}（启动/周期自动回收）"
                    conn.execute(
                        "UPDATE task_queue SET status = 'failed', finished_at = ?, "
                        "error = ? WHERE id = ?",
                        (now_iso, err, qid),
                    )
                    recovered.append((task_id, trigger_type, started_at, False, err))
            conn.commit()
            conn.close()
        for task_id, trigger_type, started_at, marked_done, err_text in recovered:
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
                    "error": err_text,
                    "error_trace": None,
                })
        if requeued:
            logger.warning(
                f"人为停机打断：{len(requeued)} 条 running 记录已**重新入队**"
                f"（不判失败）: " + "、".join(t for t, _, _ in requeued)
            )
        if recovered:
            real_failed = [r for r in recovered if not r[3]]
            logger.warning(
                f"已回收 {len(recovered)} 条上次 Worker 残留的 running 记录"
                + (f"（其中 {len(real_failed)} 条确为失败，{len(recovered) - len(real_failed)} 条实为成功已置 done）"
                   if real_failed else "（均为成功执行，未补写失败记录）")
            )
        # 回收处理完毕即清除停机标记，防止被后续启动复用（否则后续的真实崩溃
        # 一旦落在 TTL 窗口内会被误判为「人为停机」而重新入队，掩盖问题）。
        if stopping:
            _clear_stopping_flag()
    except Exception as e:
        logger.warning(f"回收残留 running 记录失败: {e}")


def _expire_orphan_pending():
    """把长期无人认领的 pending 队列记录置为失败（防陈旧 pending 永久占住单飞名额）。

    与 _recover_stale_running 同频调用（仅每 300s 的周期分支，启动时不调用，
    见主循环注释：要让刚分组好的 worker 先认领到积压的那条 pending）。
    判定只看 created_at：
    running 的回收要靠 PID 核对以免误伤在跑的长任务，而 pending 从未被执行过，
    过期即置失败没有数据风险，最多是让一个确实排不到队的任务显式失败一次。
    不写 error_trace、也不触发失败通知（通知在 run_task 内），只留执行日志供排查。
    """
    try:
        cutoff = (datetime.now() - timedelta(seconds=STALE_PENDING_SECONDS)).isoformat()
        expired = []
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            rows = conn.execute(
                "SELECT id, task_id, trigger_type, created_at FROM task_queue "
                "WHERE status = 'pending' AND created_at < ? ORDER BY id",
                (cutoff,),
            ).fetchall()
            now_iso = datetime.now().isoformat()
            err = (f"队列 pending 超过 {STALE_PENDING_SECONDS // 3600}h 无人认领："
                   f"多为任务未登记 worker_watchdog.GROUP_TASK_MAP 分组（无 worker 认领该 task_id）")
            for qid, task_id, trigger_type, created_at in rows:
                conn.execute(
                    "UPDATE task_queue SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
                    (now_iso, err, qid),
                )
                expired.append((qid, task_id, trigger_type, created_at))
            conn.commit()
            conn.close()
        for qid, task_id, trigger_type, created_at in expired:
            task_runner._save_task_result({
                "task_id": task_id,
                "task_name": task_runner._task_registry.get(task_id, {}).get("name"),
                "category": task_runner._task_registry.get(task_id, {}).get("category"),
                "trigger": trigger_type or "scheduled",
                "success": False,
                "started_at": created_at,
                "completed_at": datetime.now().isoformat(),
                "elapsed_seconds": None,
                "result": None,
                "error": "队列 pending 超时无人认领（未登记 worker 分组？）",
                "error_trace": None,
            })
            logger.warning(
                f"已过期 {STALE_PENDING_SECONDS // 3600}h 无人认领的排队记录: "
                f"queue_id={qid} task={task_id} created={created_at} → failed（单飞名额已释放）"
            )
    except Exception as e:
        logger.warning(f"过期陈旧 pending 记录失败: {e}")


def _claim_next():
    """原子认领一条 pending 记录，同一行只会被一个执行者认领。

    设置了 MY_APP_WORKER_TASKS 时仅认领清单内任务（多 worker 分流）。

    ⚠ 2026-10-16 修掉的"看着原子、实际不原子"：旧写法是
        UPDATE ... WHERE id = (SELECT id ... WHERE status='pending' LIMIT 1) RETURNING ...
    注释写着"UPDATE+RETURNING 保证只会被一个执行者认领"，但那只对 SQLite 成立。
    PG 里子查询是 InitPlan，**在行锁之前就取好了 id**；执行器拿到行锁后按
    READ COMMITTED 用最新行版本复查 WHERE，而复查的条件只有"id = 那个 id"，
    照样成立 → 第二个 worker 同样更新成功、同一行执行两遍。实测（40 个 worker
    抢队列）：`认领任务 queue_id=83151` 在 16:31:00 连续出现两次，12:00 之后
    同任务同分钟"重复成功"18 次，含 WhatsApp 告警重发与邮件重发。
    修法（PG 分支）：子查询 `FOR UPDATE SKIP LOCKED` 真锁行且互不阻塞，
    外层再补 `status = 'pending'` —— 这是复查时唯一会失败的谓词。
    SQLite 单写者 + 语句内快照，原形态本就原子，且不支持 FOR UPDATE，保持不动。
    """
    with get_raw_connection(str(DB_PATH), timeout=30) as conn:
        _ensure_queue_table(conn)
        now_iso = datetime.now().isoformat()
        my_pid = os.getpid()
        task_ids = sorted(_worker_task_ids) if _worker_task_ids else []
        marks = ",".join("?" for _ in task_ids)
        extra_where = f" AND task_id IN ({marks})" if task_ids else ""
        # 方言判定沿用 dialect_helpers 的约定（database.py 返回 sqlite3.Connection
        # 或 _PsycopgRaw 包装，二者不会混淆）
        is_pg = not isinstance(conn, sqlite3.Connection)
        # ⚠ 参数顺序必须与 SQL 里 '?' 出现的先后一致。PG 分支的白名单在 CTE 里，
        # 位置在 SET 的两个参数**之前**；照抄 SQLite 的顺序会让 started_at 收到 pid、
        # worker_pid 收到任务名（2026-10-16 首次上线即由生产日志暴露：
        # `无效的类型 integer 输入语法: "eflow_active_alarm"`）。
        if is_pg:
            sql = f"""WITH picked AS (
                         SELECT id FROM task_queue
                          WHERE status = 'pending'{extra_where}
                          ORDER BY id LIMIT 1
                          FOR UPDATE SKIP LOCKED)
                       UPDATE task_queue
                          SET status = 'running', started_at = ?, worker_pid = ?
                         FROM picked
                        WHERE task_queue.id = picked.id
                          AND task_queue.status = 'pending'
                     RETURNING task_queue.id, task_queue.task_id, task_queue.trigger_type"""
            params = tuple(task_ids + [now_iso, my_pid])
        else:
            sql = f"""UPDATE task_queue
                         SET status = 'running', started_at = ?, worker_pid = ?
                       WHERE id = (SELECT id FROM task_queue
                                    WHERE status = 'pending'{extra_where}
                                    ORDER BY id LIMIT 1)
                          AND status = 'pending'
                     RETURNING id, task_id, trigger_type"""
            params = tuple([now_iso, my_pid] + task_ids)
        row = conn.execute(sql, params).fetchone()
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
            row_state = conn.execute(
                "SELECT status FROM task_queue WHERE id = ?", (queue_id,)
            ).fetchone()
            if row_state and row_state[0] == "cancelled":
                logger.info(f"队列记录 queue_id={queue_id} 已被用户停止(cancelled)，跳过回写终态")
                conn.close()
                return
            # 归属校验（2026-10-16）：只回写"自己认领的那一行"。此前只按 id 回写，
            # 于是重复栈里另一个执行者认领同一行后，谁先跑完谁就把终态盖在别人身上
            # （已被回收→重新入队→被第三个 worker 认领的任务也会被写成 done，
            # 那一轮真实执行在队列里凭空消失）。
            wrote = conn.execute(
                "UPDATE task_queue SET status = ?, finished_at = ?, result_json = ?, error = ? "
                "WHERE id = ? AND status = 'running' AND worker_pid = ?",
                ("done" if success else "failed", datetime.now().isoformat(),
                 json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                 error, queue_id, os.getpid()),
            ).rowcount
            if not wrote:
                logger.warning(
                    f"队列记录 queue_id={queue_id} 归属已变更（非本次执行者持有），"
                    f"跳过回写终态 —— 说明该行被回收或重复认领过"
                )
            # 2026-09-11：保留期由 3 天放宽为 7 天（一周），与 task_runner 执行日志一致
            try:
                _retention_days = max(1, int(os.environ.get("TASK_LOG_RETENTION_DAYS", "7")))
            except (TypeError, ValueError):
                _retention_days = 7
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
    # 2026-08-14 修复：Worker 继承看门狗 CMD 窗口的控制台，当窗口被关闭时
    # Windows 发送 CTRL_CLOSE_EVENT 给所有继承该控制台的进程，导致所有 worker
    # 同时以 exit_code=1 (0xC000013A STATUS_CONTROL_C_EXIT) 退出。
    # FreeConsole() 让 worker 脱离父进程控制台，不再受 CTRL_CLOSE_EVENT 影响。
    # 仅在 stdout 已被重定向到文件时脱离（即由看门狗托管时），开发模式不受影响。
    if sys.platform == "win32" and not sys.stdout.isatty():
        try:
            import ctypes
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    # 与 backend/main.py 一致：worker 的 stdout/stderr 被重定向到日志文件（charmap 编码），
    # 中文日志会 UnicodeEncodeError。强制 UTF-8 避免截图等链路被静默打断。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 2026-11-05：第 3 道防线 —— 业务模块的裸 print 也走容错流。
    # 必须在 reconfigure 之后（包装类靠 __getattr__ 转发 reconfigure/isatty），
    # 也要在 _setup_worker_logging 之前（让 StreamHandler 拿到包装后的 stderr）。
    if not sys.stdout.isatty():
        sys.stdout = _TolerantTextStream(sys.stdout)
        sys.stderr = _TolerantTextStream(sys.stderr)
    # 日志：文件（按组按日，UTF-8，进程独占句柄）+ stderr 镜像。
    # 文件句柄不依赖 watchdog 的 pipe 泵，watchdog 死亡后日志仍能落盘。
    _setup_worker_logging()
    # 由 watchdog 托管时启用孤儿自退守卫（手动单跑不启用，父进程为终端）
    _start_parent_guard()
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
    # 启动期串行预热公共重依赖（2026-09-10 修复）：
    # worker 进程内 QUEUE_ENABLED=0 时，auto_retry 会经 task_runner.run_task_async 的
    # threading.Thread 分支在【同一进程内并发】拉起多个任务；若把 requests 等重依赖
    # 留到运行期首次导入，多线程会撞 import 竞态并留下半成品模块，导致任务 import 失败
    # （cannot import name 'HTTPAdapter' from partially initialized module
    # 'requests.adapters'）。这里提前到启动期单线程导入，消除该窗口。
    try:
        ok, failed = preload_common_deps()
        logger.info(
            f"公共依赖预热完成：{len(ok)} 个成功"
            + (f"，{len(failed)} 个失败: {'; '.join(failed)}" if failed else "")
        )
    except Exception as e:
        logger.warning(f"公共依赖预热异常（不影响启动）: {e}")
    logger.info(
        f"Task Worker 已启动：注册 {n} 个任务，轮询间隔 {POLL_INTERVAL}s，"
        f"queue_mode={task_runner.QUEUE_ENABLED}, db={DB_PATH}"
    )

    executed = 0
    last_recover_ts = time.time()
    try:
        while not _shutdown:
            # 主循环每轮也检查一次父进程；长任务执行期间由守护线程覆盖。
            if _PARENT_GUARD_STATE["enabled"] and not _parent_alive():
                _die_as_orphan()
            # 周期性回收滞留的 running/pending 队列记录（不只启动时），避免陈旧记录长期
            # 滞留导致 running 状态卡死、手动触发被拒。每 300s 一次，开销极低。
            # 注：陈旧 pending 的过期只放在周期分支、不放在启动时 —— 启动瞬间
            # 新分组的 worker 还没来得及认领队列里那条 pending（它就是等了两天的调度），
            # 先让它被认领执行，5 分钟后再把仍无人认领的过期掉。
            if time.time() - last_recover_ts >= 300:
                try:
                    _recover_stale_running()
                    _expire_orphan_pending()
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
