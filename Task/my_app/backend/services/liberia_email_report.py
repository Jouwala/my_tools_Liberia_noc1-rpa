"""
import logging
Liberia 站点宕报告邮件任务
==========================

通过子进程调用 ``email_reports/`` 下的自包含脚本发送邮件。

注意：后端（Task Manager）运行在系统 Python 3.12，未安装 exchangelib；
而邮件脚本依赖 exchangelib。因此本模块用**托管 venv 的 python**
（已装 exchangelib）来执行脚本，后端本身只负责编排与结果回收。

- 收件人名单（主送/抄送）由**本模块（Python 后端）从 email_reports/ 下的
  ss_email.txt / cc_email.txt 读取**，再传给邮件脚本；而非在脚本内部读取，
  保证名单的唯一来源就是这两个 txt 文件（测试时可覆盖 to/cc）。
- 生产调度（不传 to/cc）：读取完整名单发送。
- 测试（传 to="dong.xinmin@zte.com.cn", cc=""）：只发给测试地址，不抄送。
"""
import subprocess
import sys
import time
import threading
from pathlib import Path

# .../Task/my_app
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
EMAIL_REPORTS_DIR = MY_APP_DIR / "email_reports"
DATA_DIR = MY_APP_DIR / "data" / "eflow" / "tt_reports"

# 收件人名单（主送/抄送）文件：唯一来源，由本模块读取后传给邮件脚本
SS_EMAIL_FILE = EMAIL_REPORTS_DIR / "ss_email.txt"
CC_EMAIL_FILE = EMAIL_REPORTS_DIR / "cc_email.txt"

# 托管 venv（已装 exchangelib）。后端系统 Python 无此依赖，必须用它来跑脚本。
_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

# 可重试的瞬时错误关键字（Orange EWS 偶发连接重置）
_TRANSIENT_KEYS = (
    "ConnectionReset",
    "TransportError",
    "10054",
    "timed out",
    "Connection aborted",
    "RemoteDisconnected",
    "ConnectionError",
)


def _resolve_python() -> str:
    """优先用托管 venv python（有 exchangelib），否则回退当前 python。"""
    if Path(_MANAGED_VENV_PY).is_file():
        return _MANAGED_VENV_PY
    return sys.executable


def _read_addresses(path: Path) -> list:
    """从名单文件读取邮箱地址（支持 ; 或 , 分隔，忽略空行/空白）。"""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for part in line.replace(";", ",").split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


def _resolve_recipients(to: str = None, cc: str = None):
    """解析收件人：传入的 to/cc 优先（测试用）；否则从 ss/cc_email.txt 读取。

    返回 (to_arg, cc_arg) 用于拼接到命令行：
      - to_arg: 拼接后的字符串，或 None（文件也为空时由脚本兜底）
      - cc_arg: 拼接后的字符串；空串表示不抄送
    """
    to_arg = to if to is not None else ";".join(_read_addresses(SS_EMAIL_FILE)) or None
    cc_arg = cc if cc is not None else ";".join(_read_addresses(CC_EMAIL_FILE))
    return to_arg, cc_arg


def _run_script(
    script_name: str,
    to: str = None,
    cc: str = None,
    retries: int = 2,
    per_attempt_timeout: int = 90,
    budget: int = 210,
) -> dict:
    """调用指定邮件脚本，返回 {success, message/detail/error}。

    异步/防阻塞设计：实际发送在后台 daemon 线程中执行，主线程最多等待 ``budget``
    秒后返回，避免 EWS 服务端降级时一个邮件任务长期霸占调度 worker、吞掉后续整点任务。
    - 正常情况下（数分钟内完成）会在 budget 内拿到真实结果并返回。
    - 极端缓慢时（超过 budget）脱离主线程返回失败，后台线程继续发送；
      这类「超时脱离」不会被 email_recovery 重复补发（错误关键字不匹配 EWS 失败）。
    """
    py = _resolve_python()
    script = EMAIL_REPORTS_DIR / script_name
    if not script.is_file():
        return {"success": False, "error": f"脚本不存在: {script}"}
    if not DATA_DIR.is_dir():
        return {"success": False, "error": f"数据目录不存在: {DATA_DIR}"}

    cmd = [py, str(script), "--data-dir", str(DATA_DIR)]
    if to is not None:
        cmd += ["--to", to]
    if cc is not None:
        cmd += ["--cc", cc]

    holder: dict = {}

    def _attempt_all():
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=per_attempt_timeout,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 0:
                    tail = "\n".join(out.strip().splitlines()[-15:])
                    return {
                        "success": True,
                        "message": f"{script_name} 发送成功 (attempt {attempt})",
                        "detail": tail,
                    }
                transient = any(k in out for k in _TRANSIENT_KEYS)
                last_err = f"returncode={proc.returncode}\n{out[-2000:]}"
                if (not transient) or attempt == retries:
                    return {"success": False, "error": last_err}
                time.sleep(5)
                continue
            except subprocess.TimeoutExpired as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _attempt_all: exception swallowed", exc_info=True)
                last_err = f"timeout: {e}"
                if attempt == retries:
                    return {"success": False, "error": last_err}
                time.sleep(5)
        return {"success": False, "error": last_err or "unknown error"}

    t = threading.Thread(target=lambda: holder.setdefault("r", _attempt_all()), daemon=True)
    t.start()
    t.join(timeout=budget)
    if t.is_alive():
        # 发送仍在进行（服务端极慢），脱离主线程，释放调度 worker。
        return {
            "success": False,
            "error": (
                f"BUDGET_EXCEEDED: 邮件发送超过 {budget}s 预算上限，已脱离主线程"
                f"（后台继续发送；email_recovery 仅对 EWS 失败补发，不会重复本任务）"
            ),
        }
    return holder.get("r", {"success": False, "error": "no result"})


def run_1h_report(to: str = None, cc: str = None) -> dict:
    """Liberia 站点宕 1 小时报告邮件。

    收件人名单来源（优先级）：
      - 传入 to/cc（测试用，如 to="dong.xinmin@zte.com.cn", cc=""）→ 只发测试地址
      - 否则从 email_reports/ss_email.txt / cc_email.txt 读取完整名单
    """
    to_arg, cc_arg = _resolve_recipients(to, cc)
    return _run_script("owa_mail_1hour_TT_Report.py", to=to_arg, cc=cc_arg)


def run_8h_report(to: str = None, cc: str = None) -> dict:
    """Liberia 站点宕 8 小时报告邮件。

    收件人名单来源（优先级）：
      - 传入 to/cc（测试用，如 to="dong.xinmin@zte.com.cn", cc=""）→ 只发测试地址
      - 否则从 email_reports/ss_email.txt / cc_email.txt 读取完整名单
    """
    to_arg, cc_arg = _resolve_recipients(to, cc)
    return _run_script("owa_mail_8hour_TT_Report.py", to=to_arg, cc=cc_arg)
