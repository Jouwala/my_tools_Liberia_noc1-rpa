"""实时代理进程控制 —— 让前端「启用实时刷新」开关按需拉起/关闭本地代理。

设计要点：
- 两个本地代理（与 scripts/start-app.mjs 的 PROXIES 对齐）：
    · 8787 realtime_proxy.py      -> FMS  (Alarm Management 看板)
    · 8790 realtime_proxy_vmax.py -> VMAX (CXO 经营看板)
- 代理以 **DETACHED** 方式拉起（脱离 uvicorn 父进程），因此 backend 重启不会误杀代理；
  控制面只按「端口健康」判断，不持有 Popen 句柄，backend 重启后也能复用已有实例。
- 前端开关「启用实时刷新」→ POST /api/realtime-proxy/start（确保两个代理都就绪）；
  「关闭实时刷新」不会自动杀代理（避免影响另一个仍打开的看板），需要停止可 POST /stop。
- cwd 固定为 scripts/，保证 fms_session.json / vmax_session.json 落在确定位置；
  python 解释器优先用 scripts/python.exe（含 cryptography 依赖的 venv）。
"""
import os
import re
import sys
import time
import socket
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# 代理清单（与 tools/start-app.mjs 的 PROXIES 对齐）
PROXIES = [
    {"port": 8787, "script": "realtime_proxy.py", "label": "FMS"},
    {"port": 8790, "script": "realtime_proxy_vmax.py", "label": "VMAX"},
]

# my_app 仓库根（backend/services/ -> 上溯两级到 my_app）
_ROOT = Path(__file__).resolve().parent.parent.parent

# 2026-10-03：代理脚本从 scripts/ 迁到 tools/。
# 起因：scripts/ 命中 my_app/.gitignore 的 /Scripts/（Windows 下大小写不敏感），
# 脚本写在那里**永远不会入库**，换机器 clone 后两个看板的实时数据全灭。
# tools/ 不被忽略，脚本随仓库走。
#
# 注意这里刻意拆成两个常量，二者职责不同，不可合并：
#   _TOOLS   —— 脚本源码所在，随 git 走
#   _RUNTIME —— venv 解释器 + 会话文件落点，是本机运行时状态，不入库
_TOOLS = _ROOT / "tools"
_RUNTIME = _ROOT / "scripts"

try:
    from backend.log_writer import resolve_free_path
except ImportError:  # pragma: no cover - 兼容非包方式导入
    sys.path.insert(0, str(_ROOT))
    from backend.log_writer import resolve_free_path


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# 代理只用到 stdlib + cryptography（requests/urllib3 都不需要 —— 实测那个 venv 反倒缺
# requests/urllib3）。所以判定解释器可用要靠 **import 探测**，不能只看文件在不在：
# 探不过会拉起一个"能启动、一跑就 ImportError"的进程，那种崩溃只在 console.log 里留一行，
# 端口永远不起来，排障时最容易误判成"上游问题"。
_PROXY_IMPORT_PROBE = "import cryptography, ssl, http.server, urllib.request"
_PY_CHOSEN = None


def _proxy_python_candidates():
    """按优先级给出代理解释器候选：显式环境变量 > 系统 Python312 > 仓库 venv > PATH。"""
    cands = []
    env = (os.environ.get("MY_APP_PROXY_PY") or "").strip()
    if env:
        cands.append(env)
    cands.append(r"C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe")
    cands.append(str(_RUNTIME / "python.exe"))
    cands.append("python.exe")
    return cands


def _python_can_run_proxy(exe: str) -> bool:
    try:
        p = subprocess.run(
            [exe, "-c", _PROXY_IMPORT_PROBE],
            capture_output=True, timeout=15, creationflags=_CREATE_NO_WINDOW,
        )
        return p.returncode == 0
    except Exception as e:  # noqa: BLE001 - 探测不过就等于"这个解释器不能用"，接着试下一个
        logger.debug("[realtime_proxy_ctl] import probe failed for %s: %s", exe, e)
        return False


def _find_python() -> str:
    """选出跑代理脚本的解释器，结果缓存（探测要起子进程，不能每次 ensure 都跑一遍）。

    ⚠ 2026-10-10：把系统 Python312 排到仓库 venv 前面。起因是实测当时在听的两个代理进程
    （PID 50996 / 46704）的真实镜像路径是
    `C:\\Users\\ZTEEMS\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe`，
    父进程才是 `D:\\01_RPA\\Task\\my_app\\scripts\\python.exe` —— venv 的重定向器会派生
    **基础解释器**作为真正执行代码的子进程，于是这两个代理在进程谱系上算 WorkBuddy 的。
    任何按镜像路径清理 WorkBuddy python 的动作都会把它们**成对**带走（当天 11:11:31 的
    8790 与 11:13:54 的 8787 成对消失、代理自身日志没有崩溃痕迹，正是外部 `taskkill /F`
    的形状；之后 3 分 36 秒的空档靠人工点前端「启用实时刷新」才补上，那条告警就是撞在
    这个窗口里的）。`stop.bat:55-58` 早在 2026-09-04 就为同一件事把 8787/8790 从它的
    端口清理列表里摘了出去，注释里写的"属于 WorkBuddy 的 MCP 服务"就是这个谱系。

    选 `python.exe` 而不是 `pythonw.exe`：与 backend/worker 的镜像名区分开，免得将来
    任何按 `/IM pythonw.exe` 的清理把后端和代理一锅端；拉起侧本来就用 CREATE_NO_WINDOW
    （见 ensure_proxy 里 2026-08-16 那段实测注释），不会有黑窗弹出来打断在看板的人。

    这里只新增一个模块级 _CREATE_NO_WINDOW 给探测用；_kill_port / ensure_proxy 里原有的
    同名局部写法**没有一并替换** —— 那两处各自带着"为什么不能用 DETACHED_PROCESS"这类
    实测注释，是既有事实的载体，动了它们反而丢上下文。
    """
    global _PY_CHOSEN
    if _PY_CHOSEN:
        return _PY_CHOSEN
    for cand in _proxy_python_candidates():
        if cand != "python.exe" and not Path(cand).exists():
            # 路径写错也要留一行 —— 现场用 MY_APP_PROXY_PY 应急指解释器时，
            # 静默跳过会让人以为环境变量没生效，其实是被当成不存在忽略了。
            logger.warning("[realtime_proxy_ctl] interpreter path not found, skipped: %s", cand)
            continue
        if _python_can_run_proxy(cand):
            _PY_CHOSEN = cand
            logger.info("[realtime_proxy_ctl] proxy interpreter chosen: %s", cand)
            return _PY_CHOSEN
        logger.warning(
            "[realtime_proxy_ctl] interpreter unusable for proxy (import probe failed): %s", cand
        )
    _PY_CHOSEN = "python.exe"
    logger.warning("[realtime_proxy_ctl] no verified interpreter, falling back to PATH python.exe")
    return _PY_CHOSEN


def _port_alive(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _proxy_healthy(port: int) -> bool:
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            j = json.loads(r.read().decode())
        return bool(j.get("status") == "ok" and j.get("proxy") == "ready")
    except Exception:
        return False


def _kill_port(port: int):
    """按端口杀掉占用进程（清理僵死旧代理）。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    if sys.platform != "win32":
        try:
            out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True).stdout
            for pid in out.split():
                subprocess.run(["kill", "-9", pid], capture_output=True)
        except Exception:
            pass
        return
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            creationflags=flags,
        ).stdout
        pids = set()
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                m = re.search(r"LISTENING\s+(\d+)", line, re.I)
                if m:
                    pids.add(m.group(1))
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", pid, "/F", "/T"],
                capture_output=True,
                creationflags=flags,
            )
    except Exception as e:
        logger.warning("[realtime_proxy_ctl] kill_port(%s) failed: %s", port, e)


def ensure_proxy(cfg: dict, timeout: int = 25) -> dict:
    """确保某个代理就绪：已健康则复用；端口被僵死进程占则清理后重拉；否则拉起。"""
    port = cfg["port"]
    label = cfg["label"]
    if _port_alive(port) and _proxy_healthy(port):
        return {"port": port, "label": label, "status": "running", "action": "reuse"}

    if _port_alive(port):
        # 端口在听但不健康 -> 清掉僵死实例再拉
        _kill_port(port)
        time.sleep(0.8)

    script = _TOOLS / cfg["script"]
    if not script.exists():
        return {"port": port, "label": label, "status": "missing",
                "error": f"缺少 {cfg['script']}（脚本未部署）"}

    py = _find_python()
    log_dir = _ROOT / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    # 2026-09-11：文件名加启动日期，配合 log_cleanup 定时任务做 7 天保留。
    # 另外：代理是 DETACHED 拉起的（生命周期与拉起者不同），不能改用 pipe 泵
    # —— 父进程退出后 pipe 读端消失，代理会 broken pipe 甚至被缓冲区堵死。
    # 因此这里只在【拉起时】挑一个还没写满的分片（resolve_free_path），写满后
    # 靠下一次重启继续切；删除/轮转仍由 log_cleanup 按 7 天保留处理。
    _base_log = log_dir / f"realtime_proxy_{label.lower()}_{time.strftime('%Y%m%d')}_console.log"
    log_path = resolve_free_path(_base_log)

    creationflags = 0
    if sys.platform == "win32":
        # 注意：只能用 CREATE_NO_WINDOW，不能叠加 DETACHED_PROCESS！
        # 实证（2026-08-16）：DETACHED_PROCESS|CREATE_NO_WINDOW 组合下，
        # venv 重定向器 scripts\python.exe 的子进程（真实解释器）会自分配
        # 可见控制台（OpenConsole/Windows Terminal 黑窗弹出）；
        # 仅 CREATE_NO_WINDOW 时整条链路无可见窗口。
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # 强制 UTF-8：代理脚本启动时有中文 print，若 stdout 是 cp1252(charmap) 流会
    # UnicodeEncodeError 直接崩（与 worker 进程同坑，见项目 memory）。PYTHONUTF8=1
    # 让子进程无视控制台/文件编码用 UTF-8 输出。
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"

    try:
        with open(log_path, "ab") as logf:
            subprocess.Popen(
                [py, str(script)],
                # cwd 固定为 scripts/（venv launcher 目录），仅保证运行目录确定；
                # 会话文件不依赖 cwd —— 两个代理都用
                # SESSION_FILE = dirname(abspath(__file__)) 定位，即随脚本落在
                # tools\（fms_session.json / vmax_session.json，已确认不被忽略，
                # 但属运行时状态、无需入库）。
                cwd=str(_RUNTIME),
                stdout=logf,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
                env=env,
            )
    except Exception as e:
        return {"port": port, "label": label, "status": "error", "error": f"拉起失败: {e}"}

    # 等待健康（代理需先登录 FMS/VMAX，可能要几秒）
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_alive(port) and _proxy_healthy(port):
            return {"port": port, "label": label, "status": "running", "action": "started"}
        time.sleep(1.0)
    # 超时仍未健康：进程已拉起但上游登录可能慢/失败，返回 starting 让前端继续轮询
    return {"port": port, "label": label, "status": "starting", "action": "started",
            "note": "进程已拉起但尚未通过健康检查（上游登录可能较慢或失败，详见日志）"}


def kill_proxy(cfg: dict) -> dict:
    port = cfg["port"]
    if not _port_alive(port):
        return {"port": port, "label": cfg["label"], "status": "stopped", "action": "none"}
    _kill_port(port)
    time.sleep(0.5)
    if _port_alive(port):
        return {"port": port, "label": cfg["label"], "status": "still_alive", "action": "kill_failed"}
    return {"port": port, "label": cfg["label"], "status": "stopped", "action": "killed"}


def ensure_all() -> list:
    return [ensure_proxy(c) for c in PROXIES]


def kill_all() -> list:
    return [kill_proxy(c) for c in PROXIES]


def status_all() -> list:
    return [
        {
            "port": c["port"],
            "label": c["label"],
            "alive": _port_alive(c["port"]),
            "healthy": _proxy_healthy(c["port"]),
        }
        for c in PROXIES
    ]
