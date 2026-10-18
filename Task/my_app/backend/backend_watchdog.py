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
import ctypes
import ctypes.wintypes  # noqa: F401  _SECURITY_ATTRIBUTES 需要 DWORD/BOOL
import logging
import subprocess
import socket
from datetime import datetime
from pathlib import Path

# 项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

# 2026-09-11：日志不再把句柄交给子进程继承，改由父进程 pipe 泵 + 按大小轮转
# （详见 backend/log_writer.py 的模块说明）。
try:
    from backend.log_writer import attach_rotating_output
except ImportError:  # 以脚本方式直接启动时 PROJECT_ROOT 可能不在 sys.path
    sys.path.insert(0, str(PROJECT_ROOT))
    from backend.log_writer import attach_rotating_output

PID_FILE = Path(os.environ.get(
    "MY_APP_BACKEND_WATCHDOG_PID",
    str(BACKEND_DIR / "backend_watchdog.pid")
))
LOG_DIR = PROJECT_ROOT / "log"
# 2026-09-11：日志文件名带启动日期，配合 log_cleanup 定时任务做 7 天保留。
# Windows 下被进程占用的文件无法被外部重命名/删除，因此必须在「写入方」按日期分文件
# （此前 backend_runtime.log 等 4 个文件合计 466MB 且无大小上限，只能靠重启截断）。
_LOG_DATE = datetime.now().strftime("%Y%m%d")
BACKEND_LOG = LOG_DIR / f"backend_runtime_{_LOG_DATE}.log"
WATCHDOG_LOG = LOG_DIR / f"backend_watchdog_{_LOG_DATE}.log"

PORT = int(os.environ.get("MY_APP_BACKEND_PORT", "7038"))

POLL_INTERVAL = 2.0        # 子进程状态轮询间隔（秒）
CRASH_THRESHOLD = 10.0     # 子进程存活短于此值（秒）视为异常崩溃
MAX_BACKOFF = 30.0         # 最大退避间隔（秒）
STARTUP_FAIL_LIMIT = 10    # 连续快速崩溃达到此次数则降级为慢速重试（不再永久放弃）
SLOW_RETRY_INTERVAL = 300.0  # 降级后的重试间隔（秒）。取 5 分钟：既让瞬时故障自愈，
                             # 又不至于形成"崩溃↔重启"风暴（每 5 分钟一次可接受）。
STARTUP_GRACE = 60.0       # 进程存活但端口未监听超过此时长，判定启动挂死
# 端口被孤儿占用时，两次「主动清理」之间的最小间隔（秒）。
# 取 30s 的理由：清理要起 netstat + taskkill 两个子进程，每轮（2s）都做反而成为
# 新的开销；而孤儿不会在两秒内变化。30s 也远小于 SLOW_RETRY_INTERVAL，
# 保证即便进入降级模式，孤儿窗口也不会拖到 5 分钟。
ORPHAN_CLEAN_INTERVAL = float(os.environ.get("MY_APP_ORPHAN_CLEAN_INTERVAL", "30"))

# ===== 看门狗单例锁（2026-10-18 新增）=====
# 背景：本模块此前**没有任何单实例保护** —— 既没有 Mutex，也不查 PID 是否已被另一
# 个活着的 watchdog 持有。任何入口（计划任务、手动 npm/python 启动、修后端的脚本）
# 都能再起一套，两套各自拉起一个 uvicorn。
#
# 2026-10-16 实测后果：当天累计 3,487 次 backend 进程启动、17,349 条
# 「端口疑似被不受管理的孤儿进程占用」告警（backend_watchdog_20261016.log 5.3MB）。
# 2026-10-18 09:03 又一次复现，机制如下：
#   08:39 watchdog A 拉起 backend 18148
#   09:03:14 18148 退出 → A 拉起 25852
#   09:03:22 watchdog B 启动 → 拉起 31000（B 抢到调度器锁 instance.lock）
#   09:03:41 25852 绑不上 7038（被 31000 占了），exit_code=3 退出
#   之后 31000 成为**孤儿**独占 7038，A 每轮拉起的新子进程都在约 8 秒后绑失败退出
#
# 之所以会形成死循环（见 _loop_once 里「端口在监听但子进程存活过短」分支）：
# 孤儿不被杀掉 → 端口永远在监听 → A 的心跳一直新鲜 → start_hidden.ps1 判定
# watchdog 健康、跳过 -Force 清理端口分支 → 孤儿永不被清理。自愈完全失效。
#
# 修法沿用 backend/worker_watchdog.py 的成熟实现（同一套 SDDL / 命名空间回退策略），
# 不另写一份：两个看门狗面对的是同一个 Windows 完整性级别问题，
# 各写一份必然漂移。详见该模块 SINGLETON_MUTEX_* 的注释。
SINGLETON_MUTEX_GLOBAL = "Global\\MyApp_BackendWatchdog_Singleton"
SINGLETON_MUTEX_LOCAL = "Local\\MyApp_BackendWatchdog_Singleton"
SINGLETON_MUTEX_SDDL = "D:(A;;GA;;;AU)(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;LW)"

_MUTEX_QUERY_STATE = 0x0001
_MUTEX_SYNCHRONIZE = 0x00100000
_MUTEX_OPEN_ACCESS = _MUTEX_SYNCHRONIZE | _MUTEX_QUERY_STATE
_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_NOT_FOUND = 2
_ERROR_ACCESS_DENIED = 5

_singleton_handle = None  # 锁本体就是这个句柄：持有到进程退出，不写任何文件


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.wintypes.BOOL),
    ]


def _win_apis():
    """返回 (kernel32, advapi32)，非 Windows 或加载失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        a32 = ctypes.WinDLL("advapi32", use_last_error=True)
        return k32, a32
    except Exception:
        return None


def _mutex_sd(apis):
    """按 SDDL 造安全描述符；失败返回 None（用系统默认 DACL，仍能挡住同级别实例）。"""
    _k32, a32 = apis
    a32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.wintypes.BOOL
    a32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.wintypes.DWORD)]
    sd = ctypes.c_void_p()
    if a32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            SINGLETON_MUTEX_SDDL, 1, ctypes.byref(sd), None):
        return sd
    return None


def _create_mutex(apis, name):
    """CreateMutexW：返回 (handle, last_error)。"""
    k32, _a32 = apis
    k32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.POINTER(_SECURITY_ATTRIBUTES),
                                 ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    k32.LocalFree.restype = ctypes.c_void_p
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    sd = _mutex_sd(apis)
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(_SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = sd.value if sd else None
    sa.bInheritHandle = False
    try:
        h = k32.CreateMutexW(ctypes.byref(sa), False, name)
    finally:
        if sd:
            k32.LocalFree(sd)
    return h, ctypes.get_last_error()


def _open_mutex(apis, name):
    """OpenMutexW：只查不建。返回 (handle, last_error)。"""
    k32, _a32 = apis
    k32.OpenMutexW.restype = ctypes.wintypes.HANDLE
    k32.OpenMutexW.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL,
                               ctypes.wintypes.LPCWSTR]
    h = k32.OpenMutexW(_MUTEX_OPEN_ACCESS, False, name)
    return h, ctypes.get_last_error()


def _acquire_singleton_lock() -> str:
    """尝试持有单例锁。返回 acquired / held / unavailable。

    unavailable 只代表"本机建不了锁"（非 Windows / API 异常），此时**不阻塞启动**，
    交由 PID 文件与端口检查兜底 —— 宁可少一道保险，也不能让 backend 无人托管。
    """
    global _singleton_handle
    apis = _win_apis()
    if not apis:
        return "unavailable"
    k32, _a32 = apis
    h, err = _create_mutex(apis, SINGLETON_MUTEX_GLOBAL)
    if h is None and err == _ERROR_ACCESS_DENIED:
        # 缺 SeCreateGlobalPrivilege → 先确认 Global 上没人，再退到会话内 Local
        gh, gerr = _open_mutex(apis, SINGLETON_MUTEX_GLOBAL)
        if gh:
            k32.CloseHandle(gh)
            return "held"
        if gerr == _ERROR_ACCESS_DENIED:
            return "held"
        if gerr != _ERROR_FILE_NOT_FOUND:
            return "unavailable"
        h, err = _create_mutex(apis, SINGLETON_MUTEX_LOCAL)
    if not h:
        return "held" if err == _ERROR_ACCESS_DENIED else "unavailable"
    if err == _ERROR_ALREADY_EXISTS:
        k32.CloseHandle(h)
        return "held"
    _singleton_handle = h
    return "acquired"


def _release_singleton_lock() -> None:
    global _singleton_handle
    h, _singleton_handle = _singleton_handle, None
    if not h:
        return
    try:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(h)
    except Exception:
        pass


def _probe_singleton_lock() -> str:
    """只回答"是否已有看门狗持有锁"，不创建对象、不干扰持有权。

    供 start_hidden.ps1 在拉起新实例前先问一次（与 worker_watchdog 的 --probe 同契约）。
    """
    apis = _win_apis()
    if not apis:
        return "unavailable"
    k32, _a32 = apis
    for name in (SINGLETON_MUTEX_GLOBAL, SINGLETON_MUTEX_LOCAL):
        h, err = _open_mutex(apis, name)
        if h:
            k32.CloseHandle(h)
            return "held"
        if err == _ERROR_FILE_NOT_FOUND:
            continue
        if err == _ERROR_ACCESS_DENIED:
            return "held"     # 对象在但权限不够：保守判"已有"
        return "unavailable"
    return "free"


PROBE_EXIT_CODES = {"held": 0, "free": 3, "unavailable": 4}


def _cli_probe() -> int:
    """`python -m backend.backend_watchdog --probe`：0=已有 / 3=没有 / 4=判不了。"""
    state = _probe_singleton_lock()
    try:
        print(f"backend_watchdog singleton={state}")
    except Exception:
        pass
    return PROBE_EXIT_CODES[state]


logger = logging.getLogger("backend_watchdog")

_shutdown = False
_child = None              # uvicorn 子进程 Popen
_spawn_time = 0.0          # 最近一次拉起时间戳
_crashes = 0               # 连续崩溃计数
_backoff = 0.0             # 当前退避秒数
_degraded = False          # 是否已降级为慢速重试（仅用于"降级只播报一次"）
# 上次尝试清理端口孤儿的时间戳（节流用，见 _loop_once 里的孤儿清理分支）。
# 初始为 0 —— 首轮就允许尝试一次，不必空等一个间隔。
_last_orphan_clean = 0.0
# 上次处理过的端口占用者 pid。用于区分"同一个孤儿还在（走节流）"
# 与"换了个新孤儿（立即处理）" —— 见 _loop_once 里的锁相说明。
_last_orphan_owner = None

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


def _port_owner_pid(port: int):
    """返回当前 LISTEN 该端口的进程 pid；查不到返回 None。

    实现用 `netstat -ano` 而不是 psutil/Get-NetTCPConnection：
      · psutil 不在本项目的依赖里（requirements.txt 未声明，不能擅自新增）；
      · netstat 是 Windows 自带，可在 Restricted 计划任务环境下运行。
    失败一律返回 None —— 清理孤儿必须"确认不了就不动"，宁可留着下轮再看，
    也不能因为解析出错把无辜的进程杀掉。
    """
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except Exception:
        return None
    # 形如：  TCP    127.0.0.1:7038    0.0.0.0:0    LISTENING    31000
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local, state, pid_text = parts[1], parts[3], parts[4]
        if state.upper() != "LISTENING":
            continue
        if local.rsplit(":", 1)[-1] != str(port):
            continue
        try:
            return int(pid_text)
        except ValueError:
            return None
    return None


def _process_parent_pid(pid: int):
    """返回 pid 的父进程 pid；查不到返回 None（进程不存在 / 查询失败）。

    用 WMIC 已弃用，改用 PowerShell 的 CIM 查询。之所以不在纯 Python 里做：
    取父进程 ID 需要 NtQueryInformationProcess 或 WMI，跨进程查询用命令行
    最省事且不新增依赖。调用频率很低（仅在"端口被占"的异常路径上），
    起一次子进程的开销可以接受。
    """
    if sys.platform != "win32":
        return None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' "
             f"-ErrorAction SilentlyContinue).ParentProcessId"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    txt = (r.stdout or "").strip()
    if not txt:
        return None
    try:
        ppid = int(txt)
    except ValueError:
        return None
    return ppid if ppid > 0 else None


def _is_own_child(pid: int) -> bool:
    """pid 是否为本进程直接拉起的子进程（缺陷 B 的判据②）。

    只看**直接父子关系**，不追父链：uvicorn 由本进程直接 Popen，
    它的父进程必然是 os.getpid()。追父链反而会把"曾孙级"的辅助进程
    也算进来，扩大误判面。
    """
    if pid is None:
        return False
    return _process_parent_pid(pid) == os.getpid()


def _terminate_orphan_on_port(port: int) -> bool:
    """杀掉占用 `port` 且**不属于本看门狗子进程**的孤儿，返回是否已清理干净。

    为什么必须由看门狗自己做（而不是靠 start_hidden.ps1 的 -Force 分支）：
    那个分支只有在看门狗**被判为不健康**时才会执行。而本看门狗只要活着、
    心跳新鲜，就永远被判为健康 —— 于是「端口被孤儿占着、子进程每 8 秒死一次」
    这个循环会一直持续、无人干预。2026-10-16 因此刷出 17,349 条告警、
    3,487 次无效拉起；2026-10-18 09:03 再次复现。

    安全约束（少一条都可能误杀生产进程）：
      · 只杀 **端口占用者** 这一个 pid，不做树杀、不按名字杀；
      · 若占用者是本看门狗的子进程 → 不杀（那是正常状态）；
      · 若拿不准它是不是自己的 → **一律不杀**（宁可不清理，也不能误杀）；
      · kill 之后**复核**端口是否释放，没释放就如实返回 False 并升级日志级别。

    ## 缺陷 B（2026-10-18）：不能用 `_child.pid == owner` 判断归属

    原实现只比对 `_child` 这一个 pid。一旦 `_child` 失真（见缺陷 A：上一代
    子进程被覆盖丢失），正在服务的后端就不再等于 `_child.pid`，于是被误判
    为孤儿并杀掉。2026-10-18 09:48 实测：pid=11276 是**本看门狗自己拉起的**
    后端，却因该判断被误杀，服务中断约 4 秒。

    改为两层判据，任一层命中即认定"是自己的"：
      ① `_child` 存在且 pid 相同（快路径，覆盖绝大多数情况）；
      ② 端口占用者的**父进程**就是本进程 —— 这是 OS 维护的事实，
         不依赖任何内部状态，即使 `_child` 失真也不会误判。
    第 ② 层同样能覆盖缺陷 A 遗留的"脱离跟踪但仍是自己生的"进程。
    """
    owner = _port_owner_pid(port)
    if owner is None:
        return False
    child = _child
    if child is not None and child.pid == owner:
        return False        # 端口由自己托管的子进程持有：正常，不动
    # 第 ② 层：查该 pid 的父进程是不是自己。
    # 返回 None 表示查不到 —— 此时按"不是自己的"继续走清理，
    # 因为 start_hidden 的 -Force 分支同样能兜住，两处都保守不动会让死锁永存。
    if _is_own_child(owner):
        logger.warning(
            f"端口 {port} 由本看门狗的另一个子进程 pid={owner} 持有"
            f"（_child 跟踪已失真，见缺陷 A）—— 这不是孤儿，不杀；"
            f"请检查是否出现了两个 backend"
        )
        return False
    logger.error(
        f"端口 {port} 被不受管理的孤儿进程 pid={owner} 占用，"
        f"本看门狗的子进程无法绑定 —— 主动清理该孤儿（这是自愈死锁的根因）"
    )
    try:
        subprocess.run(
            ["taskkill", "/PID", str(owner), "/T", "/F"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        logger.error(f"清理孤儿 pid={owner} 时出错：{e}")
        return False
    # 复核：杀不掉（通常是权限不足）必须说清楚，不能假装成功。
    time.sleep(1.0)
    still = _port_owner_pid(port)
    if still == owner:
        logger.error(
            f"孤儿 pid={owner} 仍占用端口 {port}（taskkill 可能被权限拒绝）。"
            f"需要人工执行 stop.bat（会带提权重试）后重新启动。"
        )
        return False
    if still is None:
        logger.info(f"孤儿 pid={owner} 已清理，端口 {port} 已释放")
    else:
        logger.warning(f"端口 {port} 已改由 pid={still} 占用（疑似竞态），下一轮再判定")
    return True


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
    与 start.bat 保持一致：MY_APP_TASK_QUEUE=1，并清除 WorkBuddy 安全删除守卫变量。

    ## 缺陷 A（2026-10-18）：旧子进程还活着时不得直接覆盖 `_child`

    原实现无条件 `_child = proc`。若此时上一代 uvicorn 仍然存活（它正占着
    7038、正常服务），它就从跟踪里**丢失**了 —— 变成事实上的孤儿，
    但仍持有端口。后果是双向的：

      · 看门狗再也收不到它的退出状态，`proc.poll()` 永远对着新的那个；
      · `_terminate_orphan_on_port` 按 `_child.pid == owner` 判断归属，
        `_child` 已指向别的进程，于是把**自己拉起的、正在服务的**
        后端误判成孤儿并杀掉（2026-10-18 09:48 实测误杀 pid=11276，
        服务中断约 4 秒，由看门狗自行拉起）。

    现在的约定：`_spawn_backend` 只负责"确实没有存活子进程时"的拉起。
    调用方若发现旧进程还活着，应当先结束它再调用，或直接复用。
    """
    global _child, _spawn_time
    # 前置守卫：绝不静默覆盖一个仍然存活的子进程。
    # 这里选择"拒绝拉起"而不是"先杀掉旧的"——杀不杀是策略，由调用方决定；
    # 本函数只保证不产生失真状态。
    old = _child
    if old is not None and old.poll() is None:
        logger.error(
            f"[缺陷A守卫] 拒绝拉起新的 backend：上一代子进程 pid={old.pid} 仍然存活。"
            f"若确需重启，请先调用 _terminate_child()。"
        )
        return old.pid
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
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
        # B4 安全整改（2026-10-01）：绑定收回到回环。
        # 原因：后端把「socket 对端是 127.0.0.1」当作管理员信任
        # （backend/services/portal_auth.py + security.py）。此前监听 0.0.0.0，
        # 任何"把外部请求转成回环对端"的本机反代入口（如曾绑 0.0.0.0 的 vite preview:7090）
        # 都能让 LAN 上的匿名请求直接拿到管理员身份并读走凭据库。
        # 对外访问一律经 nginx（.20 本机 80 端口）反代到本回环，因此收回环不影响正常使用。
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(PORT),
         # nginx 直连本机 7038 时，靠 X-Forwarded-For 还原真实客户端地址；
         # 否则所有请求都显示为 127.0.0.1，会绕过 require_protected 的远程限制。
         "--proxy-headers"],
        cwd=str(PROJECT_ROOT),
        env=env,
        # stdout/stderr 由父进程接管（不再是继承的文件句柄），日志写满
        # LOG_ROTATE_MAX_MB 后自动切 _pN 分片，无需重启 uvicorn。
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    attach_rotating_output(proc, BACKEND_LOG, name="backend")
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


def _enter_slow_retry() -> None:
    """连续快速崩溃达上限后的降级处理：改为固定间隔慢速重试，不再永久退出。

    2026-10-06 变更（原实现：_crashes >= STARTUP_FAIL_LIMIT 即 return False 永久退出）。
    动机：本机 Smart App Control 处于强制模式，会**间歇性**拦截未签名的 Python 扩展模块 ——
    实测触发 "An Application Control policy has blocked this file" 的至少有两个：
    sqlalchemy/util/_collections_cy.cp312-win_amd64.pyd（10-05 事故）与
    scipy/linalg/_linalg_pythran（10-06 09:48，连崩 4 次后才侥幸起来），
    即"任意未签名 .pyd"都可能被拦（PyPI 这些二进制均为 NotSigned）；
    backend 因此每次启动 1s 内即以 exit_code=1 退出。
    此类拦截随后会自行消失（同日复测该导入已恢复正常），但原实现用满 10 次机会就永久退出，
    导致 2026-10-05 21:27 起后端停摆 12 小时无人自动恢复
    （证据：log/backend_watchdog_20261005.log 末尾"连续崩溃 10 次，停止自动拉起"）。

    降级后每 SLOW_RETRY_INTERVAL 秒重试一次且永不放弃：持续崩溃仍会周期性告警，
    瞬时故障（策略拦截、7038 端口争用）则可自愈，不必人工重跑 start.bat。

    对 keepalive 链的影响（刻意）：本函数不返回 False 意味着 watchdog 进程不再退出，
    backend_watchdog.pid 与 heartbeat 持续存在，start_hidden.ps1:241 会一直判为 ok 而不再介入。
    自愈责任因此由 watchdog 自身承担，MyApp_EnsureRunning 降为第二道保险。
    """
    global _backoff, _degraded
    _backoff = SLOW_RETRY_INTERVAL
    if not _degraded:
        _degraded = True
        logger.error(
            f"backend 连续崩溃 {STARTUP_FAIL_LIMIT} 次，降级为每 {SLOW_RETRY_INTERVAL:.0f}s "
            f"慢速重试（不再放弃）。请检查 {BACKEND_LOG.name} 定位根因。"
        )


# 上一轮的状态快照，供 _trace_state 只在**变化时**打印（2 秒一轮，全打会刷屏）。
_last_trace = None


def _trace_state(proc) -> None:
    """记录每轮的判定依据：_child、端口占用者、存活时长、退避。

    只在状态变化时输出，用来定位「明明没有 '已退出' 日志、却出现 '已拉起'」
    这类路径异常（2026-10-18 未解之谜）。一旦问题复现，日志里会直接看到
    `_child.pid` 与端口占用者是否一致 —— 这两者不一致就是状态失真的铁证。
    """
    global _last_trace
    try:
        # _backoff / _crashes 只读，无需 global
        child_pid = proc.pid if proc is not None else None
        child_alive = proc.poll() is None if proc is not None else None
        owner = _port_owner_pid(PORT)
        lived = (time.time() - _spawn_time) if _spawn_time else 0.0
        # ⚠️ 快照里**不能**放 lived —— 它每轮都在变，会让"只在变化时打印"
        # 永远成立，退化成每 2 秒一条的刷屏（2026-10-18 实测，1 分钟刷了 78 条）。
        # 只比那些真正表示"状态"的量：子进程 pid、是否存活、端口归谁。
        snap = (child_pid, child_alive, owner)
        if snap == _last_trace:
            return
        _last_trace = snap
        mismatch = ""
        if owner is not None and child_pid is not None and owner != child_pid:
            mismatch = "  ⚠ 端口占用者与 _child 不一致（状态失真）"
        if owner is not None and child_pid is None:
            mismatch = "  ⚠ 端口有主但 _child 为空（状态失真）"
        logger.info(
            f"[诊断] _child.pid={child_pid} 存活={child_alive} "
            f"端口{PORT}占用者={owner} 存活{lived:.1f}s 退避{_backoff:.1f}s"
            f" 崩溃{_crashes}{mismatch}"
        )
    except Exception as e:
        # 诊断绝不能影响主流程
        logger.debug(f"[诊断] 记录失败: {e}")


def _loop_once() -> bool:
    """单轮主循环：确保 backend 存活 + 端口探活 + 等待退出。

    返回 False 表示应退出看门狗（现仅剩"收到停止信号"一种情况：
    连续崩溃达上限已改为降级慢速重试，见 _enter_slow_retry）；
    抛出的未预期异常由 main() 统一捕获记录，防止看门狗静默死亡。
    """
    global _child, _crashes, _backoff, _spawn_time, _degraded
    proc = _child
    # ---- 诊断（2026-10-18 追加）：定位「无前置日志却出现『已拉起 backend』」----
    # 现象：09:43:18 直接出现 "已拉起 backend: pid=38756"，而此前既没有
    # "Backend Watchdog 启动"（说明不是第二条 main），也没有 "backend 已退出"
    # （说明不是本函数第 1 步）。已排除：PIPE+wait 冲突、日志轮转、双实例持锁、
    # pyc 未更新。仍未能定位具体路径，故在此记录每轮的判定依据，供事后归因。
    # 只在状态变化时打印（对比上一轮），避免 2 秒一轮刷屏。
    _trace_state(proc)
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
                    # 不再 return False：降级后继续走下方退避 → 重拉
                    # （_backoff 已被抬到 SLOW_RETRY_INTERVAL），使瞬时故障可自愈。
                    _enter_slow_retry()
            else:
                _crashes = 0
                _backoff = 0.0
                _degraded = False   # 已恢复健康：下次再崩溃时重新播报降级
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
        # 2026-09-11 修复（端口被孤儿进程占用 → 无限重拉且永不熔断）：
        # 原实现是「端口通就把 _crashes 归零」，无法区分端口究竟是谁在监听 ——
        # 是本 watchdog 拉起的子进程，还是一个不受管理的孤儿 uvicorn。
        # 后者的实际表现（2026-09-11 实测）：旧实例独占 7038，本 watchdog 的子进程
        # 每次绑定失败、约 4s 即以 exit_code=3 退出；但端口探活始终成功，
        # _crashes 被反复清零，STARTUP_FAIL_LIMIT(10) 永远达不到 ——
        # 单日无效拉起 1500+ 次、日志持续膨胀；又因 watchdog 心跳一直新鲜，
        # start_hidden.ps1 的 -Force 清理端口占用者分支永不执行，形成自愈死锁。
        # 修复：只有子进程已稳定存活 >= CRASH_THRESHOLD，才认定端口确由自己托管。
        #
        # ⚠️ 2026-10-18 二次修正：上面这条"按存活时长推断归属"只是**权宜之计**，
        # 它在启动瞬间会误报 —— 子进程刚拉起、端口刚绑上（说明它**正是**端口的主人），
        # 但 lived 还不到 10 秒，于是被判成"端口疑似被孤儿占用"。
        # 实测每次重启都会稳定出现一条这样的 warning，措辞还很有指向性
        # （"疑似被不受管理的孤儿进程占用"），很容易让人把正常启动当成故障去排查。
        #
        # 正确的判据是**直接问端口归谁**：netstat 拿占用者 pid（实测 25ms），
        # 与 _child.pid 比对即可。相等 = 自己的子进程在正常监听，与活了多久无关。
        # 只有"端口有主但不是自己"时才需要走孤儿那条路。
        lived = time.time() - _spawn_time
        owner_pid = _port_owner_pid(PORT)
        owns_port = (owner_pid is not None and proc is not None and owner_pid == proc.pid)
        if lived >= CRASH_THRESHOLD or owns_port:
            _crashes = 0
            _backoff = 0.0
            _degraded = False   # 托管实例确已稳定存活：重置降级标记
            if owns_port and lived < CRASH_THRESHOLD:
                # 启动期：端口已由自己的子进程绑定，只是还没满 10 秒。
                # 这**不是**异常，不该打 warning；记一行 debug 备查即可。
                logger.debug(
                    f"端口 {PORT} 已由本 watchdog 的子进程 pid={proc.pid} 绑定"
                    f"（存活 {lived:.1f}s，启动宽限内）"
                )
        else:
            # 孤儿清理：这是 2026-10-16/18 两次「无限重拉」事故的治本点。
            #
            # 旧行为只是打警告然后继续等 —— 但孤儿永远不会自己消失，
            # 子进程永远绑不上端口，于是每 8 秒一轮、一天上万条。日志淹没了真正的
            # 错误，也让「看门狗活着」这个信号失去意义（它活着却什么也托管不了）。
            #
            # 节流 ORPHAN_CLEAN_INTERVAL：清理本身要起 netstat + taskkill 两个子进程，
            # 每轮（2s）都做会成为新的开销来源；而孤儿不会在两秒内变化。
            #
            # ⚠️ 2026-10-18 修正：**首次发现失真时不节流，立即清理一次**。
            # 原实现无条件按 30 秒节流，而看门狗的崩溃退避也正好是 30 秒 ——
            # 两个周期相同会**锁相**：每轮重拉都落在节流窗口内，孤儿永远轮不到清理。
            # 实测后果：10:28~10:30 端口被孤儿 pid=13840 连续占用，日志里
            # 一条「主动清理」都没有，而重拉照常刷屏。
            # 现在改成：**端口归属发生变化的当轮立即尝试**，之后才进入间隔节流。
            # `_last_orphan_owner` 记录上次处理过的占用者 pid，用它判断"是不是新面孔"。
            global _last_orphan_clean, _last_orphan_owner
            now_ts = time.time()
            is_new_owner = (owner_pid != _last_orphan_owner)
            if is_new_owner or (now_ts - _last_orphan_clean >= ORPHAN_CLEAN_INTERVAL):
                _last_orphan_clean = now_ts
                _last_orphan_owner = owner_pid
                if _terminate_orphan_on_port(PORT):
                    logger.warning(
                        f"孤儿已清理，端口 {PORT} 应已释放；下一轮将重新拉起 backend"
                    )
                    _child = None
                    _crashes = 0
                    _backoff = 0.0
                    # 杀掉孤儿后立刻收掉自己那个已经绑不上的子进程，
                    # 否则它会再撑几秒才退出，白占一个进程位。
                    try:
                        proc.kill()
                        proc.wait(timeout=10)
                    except Exception:
                        pass
                    return True
                logger.warning(
                    f"端口 {PORT} 已在监听，但本 watchdog 拉起的子进程仅存活 {lived:.1f}s"
                    f"（< {CRASH_THRESHOLD:.0f}s）：端口疑似被不受管理的孤儿进程占用，"
                    f"本次不计为健康（不清除崩溃计数，当前 {_crashes} 次）"
                )
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
                _enter_slow_retry()
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

    # 单例判定分两道，缺一不可：
    #   ① Mutex（主判据）—— 不依赖任何文件，持有者一退出即自动消失；
    #   ② PID 文件（兜底）—— Mutex 不可用（非 Windows / API 异常）时才生效。
    #
    # 为什么必须以 Mutex 为主：2026-10-16/18 两次事故里 PID 文件检查**都**放行了
    # 第二个 watchdog（文件被删 / 被覆写），于是两套各自拉起一个 uvicorn，
    # 抢同一把 instance.lock，落败的那个绑不上端口、8 秒后 code=3 退出，
    # 而胜出的那个成为孤儿独占 7038，看门狗再无限重拉 —— 详见 SINGLETON_MUTEX_* 注释。
    lock_state = _acquire_singleton_lock()
    if lock_state == "held":
        logger.error("已有 backend watchdog 在运行（单例锁被占用），拒绝重复启动。退出。")
        sys.exit(1)
    if lock_state == "acquired":
        logger.info("已获得 backend watchdog 单例锁")
    else:
        # 建不了锁不是致命错误：宁可少一道保险，也不能让 backend 无人托管。
        logger.warning("backend watchdog 单例锁不可用，退回 PID 文件检查")
        if _another_watchdog_running():
            logger.error("已有 backend watchdog 在运行（PID 文件检出），拒绝重复启动。退出。")
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
        _release_singleton_lock()
        logger.info("Backend Watchdog 已退出")


if __name__ == "__main__":
    # --probe：供 start_hidden.ps1 在拉起前询问"是否已有看门狗"。
    # 用退出码而不是 stdout —— pythonw 下没有控制台，调用方只能拿到返回码。
    if "--probe" in sys.argv[1:]:
        sys.exit(_cli_probe())
    main()
