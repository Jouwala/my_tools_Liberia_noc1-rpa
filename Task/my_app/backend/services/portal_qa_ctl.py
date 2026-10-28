# -*- coding: utf-8 -*-
"""portal_qa_ctl.py - 门户「问答助手」进程控制（按需拉起 whatsapp-kb-bot 的 HTTP 服务）
====================================================================================

门户 v3（/v3/olbrportal/）右下角的问答助手需要 `Task/whatsapp-kb-bot/src/http-server.js`
在 127.0.0.1:9269 上监听。那个服务只绑回环、不注册开机自启 —— 所以由后端做控制面：

- 有人第一次提问时，后端若发现 9269 不通，就**以 DETACHED 方式**拉起 node 进程；
- 之后复用同一实例（控制面只按端口健康判断，不持有 Popen 句柄，
  backend 重启也不会误杀 —— 与 `realtime_proxy_ctl` 同一套取舍）；
- 端口在听但 `/health` 不通 = 僵死实例，杀掉重拉。

为什么不放进 Task Scheduler / autostart.ps1：
那个脚本管的是**群机器人**（src/index.js，要维持 WhatsApp 长连接，必须常驻）；
网页问答服务是**按需服务**，没人提问时不该占着 100~300MB 内存，也不需要登录态。
按需拉起还有一层好处：改了 src/http-server.js 后，只要停掉进程，下次提问自动用新代码。

日志：`<my_app>/log/portal_qa_YYYYMMDD_console.log`（与 realtime 代理同目录、同 7 天保留策略）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORTAL_QA_PORT", "9269"))
# my_app 仓库根（backend/services/ -> 上溯两级）
_ROOT = Path(__file__).resolve().parent.parent.parent
BOT_DIR = _ROOT.parent / "whatsapp-kb-bot"
SCRIPT = "src/http-server.js"

try:
    from backend.log_writer import resolve_free_path
except ImportError:  # pragma: no cover - 兼容非包方式导入
    sys.path.insert(0, str(_ROOT))
    from backend.log_writer import resolve_free_path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# 并发提问时只允许一个线程去拉进程，否则会起出好几个 node 抢 9269
_spawn_lock = threading.Lock()


def _port_alive(port: int = PORT) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _health(port: int = PORT, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _healthy() -> bool:
    h = _health()
    return bool(h and h.get("ok"))


def _kill_port(port: int = PORT) -> None:
    """按端口杀掉僵死实例（只用于「端口在听但 /health 不通」这一种情况）。"""
    if sys.platform != "win32":
        try:
            out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True).stdout
            for pid in out.split():
                subprocess.run(["kill", "-9", pid], capture_output=True)
        except Exception:  # noqa: BLE001 - 清理失败不阻断后续拉起
            pass
        return
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             creationflags=_CREATE_NO_WINDOW).stdout
        pids = set()
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line.upper():
                m = re.search(r"LISTENING\s+(\d+)", line, re.I)
                if m:
                    pids.add(m.group(1))
        for pid in pids:
            logger.warning("[portal_qa_ctl] kill stale instance on :%s pid=%s", port, pid)
            subprocess.run(["taskkill", "/PID", pid, "/F", "/T"],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        logger.warning("[portal_qa_ctl] kill_port(%s) failed: %s", port, e)


def _node_exe() -> str:
    """node 解释器：环境变量优先，其次 PATH 上的 node.exe。"""
    env = (os.environ.get("PORTAL_QA_NODE") or "").strip()
    if env:
        return env
    return "node.exe" if sys.platform == "win32" else "node"


def _node_usable(exe: str) -> bool:
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, timeout=10,
                           creationflags=_CREATE_NO_WINDOW)
        return p.returncode == 0
    except Exception as e:  # noqa: BLE001
        logger.debug("[portal_qa_ctl] node probe failed for %s: %s", exe, e)
        return False


def ensure_service(timeout: float = 25.0) -> dict:
    """确保问答服务就绪。已健康则复用；僵死则清理重拉。

    @returns {{status: 'running'|'missing'|'error'|'starting', action, port, error?, note?}}
    """
    if _healthy():
        return {"status": "running", "action": "reuse", "port": PORT}

    with _spawn_lock:
        # 拿到锁后再判一次：前一个请求可能刚拉起来
        if _healthy():
            return {"status": "running", "action": "reuse", "port": PORT}

        if _port_alive():
            # 端口在听但健康检查不通 → 多半是启动中或僵死。先等一小会儿再判。
            for _ in range(3):
                time.sleep(1.0)
                if _healthy():
                    return {"status": "running", "action": "reuse", "port": PORT}
            _kill_port()
            time.sleep(0.8)

        script = BOT_DIR / SCRIPT
        if not script.exists():
            return {"status": "missing", "port": PORT,
                    "error": f"缺少 {BOT_DIR / SCRIPT}（whatsapp-kb-bot 未部署）"}

        node = _node_exe()
        if not _node_usable(node):
            return {"status": "error", "port": PORT,
                    "error": f"找不到可用的 node 解释器（{node}）；可用 PORTAL_QA_NODE 指定"}

        log_dir = _ROOT / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        base_log = log_dir / f"portal_qa_{time.strftime('%Y%m%d')}_console.log"
        log_path = resolve_free_path(base_log)

        env = dict(os.environ)
        # node 的 --env-file-if-exists 会读 bot 目录里的 .env（含 OPENWEBUI_API_KEY 等）
        env.setdefault("PYTHONUTF8", "1")

        try:
            with open(log_path, "ab") as logf:
                subprocess.Popen(
                    [node, "--env-file-if-exists=.env", SCRIPT],
                    cwd=str(BOT_DIR),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    creationflags=_CREATE_NO_WINDOW,
                    env=env,
                )
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "port": PORT, "error": f"拉起失败: {e}"}

        logger.info("[portal_qa_ctl] spawned QA service on :%s (log=%s)", PORT, log_path)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _healthy():
                return {"status": "running", "action": "started", "port": PORT}
            time.sleep(1.0)

        return {"status": "starting", "action": "started", "port": PORT,
                "note": "进程已拉起但尚未健康（索引/模型自检较慢），详见 log/portal_qa_*.log"}


def status() -> dict:
    h = _health()
    return {
        "port": PORT,
        "alive": _port_alive(),
        "healthy": bool(h and h.get("ok")),
        "detail": h,
    }
