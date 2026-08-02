"""
任务失败 -> 微信 通知服务 (多种后端, 均不经过 OpenClaw 的 agnes 推理)

后端通过 MODE 切换:
  "openclaw"  -> 经 OpenClaw 网关的 weixin 会话直发(agent --deliver --session-key)。
                 注意: 个人微信通道是 OpenClaw 插件, 底层腾讯 API 强制要 contextToken,
                 无法完全脱离 OpenClaw; 且 agnes 推理偶发卡死, 不推荐用于通知。
  "wecom"     -> 企业微信群机器人 webhook, 纯 HTTP POST, 最稳, 发到企业微信。
  "serverchan"-> Server酱(方糖), 纯 HTTP POST, 推送到【个人微信】服务通知。
  "pushplus"  -> 推送加, 纯 HTTP POST, 推送到【个人微信】。

通知失败仅记录日志, 绝不影响任务本身的结果记录。
同一任务在冷却窗口内只通知一次, 避免定时任务反复失败时刷屏。
"""
import subprocess
import sys
import time
import json
import logging
import threading
import urllib.request
import urllib.error

logger = logging.getLogger("weixin_notifier")

# ========== 配置 ==========
# 系统 Node v24（托管版 22.22.2 不满足 openclaw CLI）
NODE24 = r"C:\Program Files\nodejs\node.exe"
OC = r"C:\Users\ZTEEMS\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs"

# OpenClaw weixin 个人微信会话 key（MODE="openclaw" 时用）
SESSION_KEY = "agent:main:openclaw-weixin:direct:o9cq800ivtut3q2rfe2faywl9fzw@im.wechat"

# 企业微信群机器人 webhook（MODE="wecom" 时填）
WECOM_WEBHOOK_URL = ""

# Server酱 SendKey（MODE="serverchan" 时填, 形如 SCTxxxxxxxxxxxx）
SERVERCHAN_SENDKEY = "SCT389311TrwFJS9k0ZxfX5Plb9g0gozix"

# 推送加 Token（MODE="pushplus" 时填）
PUSHPLUS_TOKEN = "f9cf7778112f486ab618d153456e2553"

# 发送后端: openclaw | wecom | serverchan | pushplus
MODE = "pushplus"

# 超时（秒）
OPENCLAW_AGENT_TIMEOUT = 280
SUBPROCESS_TIMEOUT = 300
WECOM_TIMEOUT = 15
PUSH_TIMEOUT = 15

# 同一任务冷却窗口（秒）：窗口内重复失败只通知一次
COOLDOWN_SECONDS = 30 * 60

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_lock = threading.Lock()
_last_notify: dict[str, float] = {}


def _send_openclaw(text: str):
    cmd = [
        NODE24, OC, "agent",
        "--session-key", SESSION_KEY,
        "--message",
        f"把下面这条消息原样发到用户微信，不要添加任何解释、问候或前缀，只输出消息本身:\n{text}",
        "--deliver", "--json",
        "--timeout", str(OPENCLAW_AGENT_TIMEOUT),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=SUBPROCESS_TIMEOUT, creationflags=_SUBPROCESS_FLAGS,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        return False, err or f"exit={proc.returncode}"
    return True, ""


def _post_json(url: str, payload: dict, timeout: int):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send_wecom(text: str):
    if not WECOM_WEBHOOK_URL:
        return False, "WECOM_WEBHOOK_URL 未配置"
    try:
        body = _post_json(WECOM_WEBHOOK_URL,
                          {"msgtype": "text", "text": {"content": text}},
                          WECOM_TIMEOUT)
        if body.get("errcode") == 0:
            return True, ""
        return False, str(body)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _send_serverchan(text: str):
    if not SERVERCHAN_SENDKEY:
        return False, "SERVERCHAN_SENDKEY 未配置"
    title = "⚠️ 任务执行失败"
    try:
        body = _post_json(
            f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send",
            {"title": title, "desp": text}, PUSH_TIMEOUT,
        )
        if body.get("code") == 0:
            return True, ""
        return False, str(body)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _send_pushplus(text: str):
    if not PUSHPLUS_TOKEN:
        return False, "PUSHPLUS_TOKEN 未配置"
    title = "⚠️ 任务执行失败"
    try:
        body = _post_json(
            "http://www.pushplus.plus/send",
            {"token": PUSHPLUS_TOKEN, "title": title,
             "content": text, "template": "txt"}, PUSH_TIMEOUT,
        )
        if body.get("code") == 200:
            return True, ""
        return False, str(body)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


_DISPATCH = {
    "openclaw": _send_openclaw,
    "wecom": _send_wecom,
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
}


def send_weixin_message(text: str) -> dict:
    """发送一条微信消息，返回 {"success": bool, "error": str}。"""
    fn = _DISPATCH.get(MODE, _send_openclaw)
    backend = MODE
    try:
        ok, err = fn(text)
        if ok:
            return {"success": True, "error": ""}
        logger.warning(f"[weixin] {backend} 发送失败: {err}")
        return {"success": False, "error": err}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[weixin] {backend} 发送异常: {e}")
        return {"success": False, "error": str(e)}


def notify_task_failure(task_id: str, task_name: str, error: str, traceback_text: str | None = None) -> None:
    """任务失败时调用：带冷却去重地推送微信失败通知。

    traceback_text: 可选，完整异常堆栈。会截取前若干行附在消息尾部，
    便于在手机端快速定位根因（不依赖回前端查日志）。
    """
    now = time.time()
    with _lock:
        last = _last_notify.get(task_id)
        if last and (now - last) < COOLDOWN_SECONDS:
            logger.info(
                f"[{task_id}] 失败通知冷却中，跳过（距上次 {int(now - last)}s）"
            )
            return
        _last_notify[task_id] = now

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"任务：{task_name}（{task_id}）\n"
        f"时间：{ts}\n"
        f"错误：{str(error)[:300]}"
    )
    # 附首行堆栈（去掉空行，最多 5 行 / 500 字），避免消息过长被截断
    if traceback_text:
        tb_lines = [ln for ln in str(traceback_text).splitlines() if ln.strip()]
        if tb_lines:
            snippet = "\n".join(tb_lines[:5])
            text += f"\n堆栈：\n{snippet[:500]}"
    logger.info(f"[{task_id}] 推送微信失败通知...")
    res = send_weixin_message(text)
    if res["success"]:
        logger.info(f"[{task_id}] 微信失败通知已发送")
    else:
        logger.error(f"[{task_id}] 微信失败通知发送失败: {res['error']}")
