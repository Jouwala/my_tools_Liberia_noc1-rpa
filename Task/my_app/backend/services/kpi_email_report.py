# -*- coding: utf-8 -*-
"""
KPI / SP / RAN 各类日报邮件任务
================================

通过子进程调用 ``email_reports/owa_mail_report.py``（通用版）发送邮件。

后端（Task Manager）运行在系统 Python 3.12，未安装 exchangelib；
邮件脚本依赖 exchangelib，因此用**托管 venv 的 python**（已装 exchangelib）执行，
后端本身只负责编排与结果回收。

数据来源
--------
- MS Contract KPIs / MS WOs SLA 两份日报：数据在**本地** ``Task/my_app/data/ms_sla``。
- SpareParts / Comsumables 备件报表：数据在**远程 FTP** ``/01_RPA/LBR_Tools/SP/sp_report``
  （每次运行下载到本地缓存目录）。
- MS Network Availability 可用性报告：数据在**远程 FTP** ``/01_RPA/LBR_Tools/KPI/RAN/ORANGE``
  （仅图片，无 Excel）。

收件人名单（主送/抄送）
----------------------
全部在**远程 FTP** 上，由各报告的 ``.../email/ss_email.txt`` 与 ``cc_email.txt`` 提供：
  - MS_SLA : /01_RPA/LBR_Tools/KPI/MS_SLA/email
  - SP     : /01_RPA/LBR_Tools/SP/sp_report/email
  - RAN    : /01_RPA/LBR_Tools/KPI/RAN/ORANGE/email
后端实时读取并传给脚本（--to / --cc），测试时可传 to/cc 覆盖为单一测试地址。

报告清单（5 个邮件任务）
------------------------
1. kpi_ms_contract    : MS Contract KPIs Achievements Daily Report  (本地数据)
2. kpi_ms_wo_sla      : MS WOs SLA Achievements Daily Report       (本地数据)
3. kpi_sp_spareparts  : SpareParts 备件报表                        (远程数据)
4. kpi_sp_consumables : Comsumables 耗材报表                       (远程数据)
5. kpi_ran_availability: MS Network Availability Daily Report     (远程图片, 无 Excel)
"""
from __future__ import annotations

import random
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import List, Optional

# .../Task/my_app
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
EMAIL_REPORTS_DIR = MY_APP_DIR / "email_reports"

# 托管 venv（已装 exchangelib）。后端系统 Python 无此依赖，必须用它来跑脚本。
_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

# ---- 数据 / 名单目录（远程用 FTP 路径字符串；本地用 Path）----
_MS_SLA_DATA = MY_APP_DIR / "data" / "ms_sla"                       # 本地
_MS_SLA_EMAIL = "/01_RPA/LBR_Tools/KPI/MS_SLA/email"                # 远程 FTP
_SP_DATA = "/01_RPA/LBR_Tools/SP/sp_report"                        # 远程 FTP
_SP_EMAIL = "/01_RPA/LBR_Tools/SP/sp_report/email"                  # 远程 FTP
_RAN_DATA = "/01_RPA/LBR_Tools/KPI/RAN/ORANGE"                      # 远程 FTP
_RAN_EMAIL = "/01_RPA/LBR_Tools/KPI/RAN/ORANGE/email"               # 远程 FTP

# 远程下载的本地缓存根目录
_CACHE_ROOT = MY_APP_DIR / "data" / "_remote_kpi"

# 可重试的瞬时错误关键字（Orange EWS / FTP 偶发连接重置）
_TRANSIENT_KEYS = (
    "ConnectionReset",
    "TransportError",
    "10054",
    "timed out",
    "Connection aborted",
    "RemoteDisconnected",
    "ConnectionError",
    "FTP",
    "timeout",
)


def _resolve_python() -> str:
    """优先用托管 venv python（有 exchangelib），否则回退当前 python。"""
    if Path(_MANAGED_VENV_PY).is_file():
        return _MANAGED_VENV_PY
    return sys.executable


def _resolve_recipients_remote(email_dir_remote: str, to: Optional[str], cc: Optional[str]):
    """从远程 FTP 名单读取主送/抄送。to/cc 显式传入时优先（测试用）。"""
    import backend.services.remote_ftp as rf

    ss_text = rf.read_text(f"{email_dir_remote}/ss_email.txt")
    cc_text = rf.read_text(f"{email_dir_remote}/cc_email.txt")
    to_list = rf.parse_addresses(ss_text)
    cc_list = rf.parse_addresses(cc_text)
    to_arg = to if to is not None else (";".join(to_list) or None)
    cc_arg = cc if cc is not None else ";".join(cc_list)
    return to_arg, cc_arg


def _pick_consolidated(files: List[Path]) -> Optional[Path]:
    """在下载的 Excel 中优先选「非分站点」的合并总表（文件名不含 ' - Liberia'）；
    否则按 mtime 取最新。返回 None 表示没有 Excel。"""
    xlsxs = [f for f in files if f.suffix.lower() == ".xlsx" and not f.name.startswith("~$")]
    if not xlsxs:
        return None
    consolidated = [f for f in xlsxs if " - Liberia" not in f.name]
    pool = consolidated if consolidated else xlsxs
    pool.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pool[0]


def _run_script(
    data_dir: Path,
    name_filter: str,
    to: Optional[str],
    cc: Optional[str],
    no_excel: bool = False,
    subject_prefix: str = "",
    excel: Optional[Path] = None,
    body_file: Optional[Path] = None,
    retries: int = 3,
    per_attempt_timeout: int = 120,
    budget: int = 300,
) -> dict:
    """调用通用邮件脚本，返回 {success, message/detail/error}。

    对 EWS / FTP 偶发连接重置（10054 / ConnectionReset / TransportError 等）做
    指数退避重试：Orange 邮件网关在版本协商握手阶段偶发被远端强制断开，但通常在
    数秒~数十秒内自愈。多试几次可显著降低日报漏发。

    异步/防阻塞：实际发送在后台 daemon 线程执行，主线程最多等待 ``budget`` 秒后返回，
    避免 EWS 降级时一个邮件任务长期霸占调度 worker。正常情况会在 budget 内拿到真实结果。
    """
    py = _resolve_python()
    script = EMAIL_REPORTS_DIR / "owa_mail_report.py"
    if not script.is_file():
        return {"success": False, "error": f"脚本不存在: {script}"}
    if not Path(data_dir).is_dir():
        return {"success": False, "error": f"数据目录不存在: {data_dir}"}

    cmd = [py, str(script), "--data-dir", str(data_dir), "--name-filter", name_filter]
    if no_excel:
        cmd += ["--no-excel"]
    if subject_prefix:
        cmd += ["--subject-prefix", subject_prefix]
    if excel:
        cmd += ["--excel", str(excel)]
    if body_file:
        cmd += ["--body-file", str(body_file)]
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
                        "message": f"发送成功 (attempt {attempt})",
                        "detail": tail,
                    }
                transient = any(k in out for k in _TRANSIENT_KEYS)
                last_err = f"returncode={proc.returncode}\n{out[-2000:]}"
                if (not transient) or attempt == retries:
                    return {"success": False, "error": last_err}
                backoff = min(60, 5 * (2 ** (attempt - 1))) + random.uniform(0, 3)
                time.sleep(backoff)
                continue
            except subprocess.TimeoutExpired as e:
                last_err = f"timeout: {e}"
                if attempt == retries:
                    return {"success": False, "error": last_err}
                backoff = min(60, 5 * (2 ** (attempt - 1))) + random.uniform(0, 3)
                time.sleep(backoff)
        return {"success": False, "error": last_err or "unknown error"}

    t = threading.Thread(target=lambda: holder.setdefault("r", _attempt_all()), daemon=True)
    t.start()
    t.join(timeout=budget)
    if t.is_alive():
        return {
            "success": False,
            "error": (
                f"BUDGET_EXCEEDED: 邮件发送超过 {budget}s 预算上限，已脱离主线程"
                f"（后台继续发送；email_recovery 仅对 EWS 失败补发，不会重复本任务）"
            ),
        }
    return holder.get("r", {"success": False, "error": "no result"})


# =====================================================================
# 5 个邮件任务
# =====================================================================
def run_ms_contract_kpi(to: str = None, cc: str = None) -> dict:
    """MS Contract KPIs Achievements Daily Report 邮件（数据本地）。"""
    to_arg, cc_arg = _resolve_recipients_remote(_MS_SLA_EMAIL, to, cc)
    return _run_script(
        data_dir=_MS_SLA_DATA,
        name_filter="MS Contract KPIs Achievements Daily Report",
        to=to_arg,
        cc=cc_arg,
    )


def run_ms_wo_sla(to: str = None, cc: str = None) -> dict:
    """MS WOs SLA Achievements Daily Report 邮件（数据本地）。"""
    to_arg, cc_arg = _resolve_recipients_remote(_MS_SLA_EMAIL, to, cc)
    return _run_script(
        data_dir=_MS_SLA_DATA,
        name_filter="MS WOs SLA Achievements Daily Report",
        to=to_arg,
        cc=cc_arg,
    )


def run_sp_spareparts(to: str = None, cc: str = None) -> dict:
    """SpareParts 备件报表邮件（数据远程 FTP，下载到本地缓存）。"""
    import backend.services.remote_ftp as rf

    to_arg, cc_arg = _resolve_recipients_remote(_SP_EMAIL, to, cc)
    cache = _CACHE_ROOT / "sp_spareparts"
    files = rf.download_filtered(_SP_DATA, cache, name_filter="SpareParts")
    excel = _pick_consolidated(files)
    return _run_script(
        data_dir=cache,
        name_filter="SpareParts",
        to=to_arg,
        cc=cc_arg,
        excel=excel,
    )


def run_sp_consumables(to: str = None, cc: str = None) -> dict:
    """Comsumables 耗材报表邮件（数据远程 FTP，下载到本地缓存）。"""
    import backend.services.remote_ftp as rf

    to_arg, cc_arg = _resolve_recipients_remote(_SP_EMAIL, to, cc)
    cache = _CACHE_ROOT / "sp_consumables"
    files = rf.download_filtered(_SP_DATA, cache, name_filter="Comsumables")
    excel = _pick_consolidated(files)
    return _run_script(
        data_dir=cache,
        name_filter="Comsumables",
        to=to_arg,
        cc=cc_arg,
        excel=excel,
    )


def run_ran_availability(to: str = None, cc: str = None) -> dict:
    """MS Network Availability Daily Report 邮件（仅图片，无 Excel，数据远程 FTP）。"""
    import backend.services.remote_ftp as rf

    to_arg, cc_arg = _resolve_recipients_remote(_RAN_EMAIL, to, cc)
    cache = _CACHE_ROOT / "ran_availability"
    rf.download_filtered(_RAN_DATA, cache, name_filter="Availability")
    # 正文使用远程 content_email.txt（"Dear All: ... Please Review, Thanks."）
    body = rf.read_text(f"{_RAN_EMAIL}/content_email.txt")
    body_file = cache / "_body.txt"
    body_file.write_text(body, encoding="utf-8")
    return _run_script(
        data_dir=cache,
        name_filter="Availability",
        to=to_arg,
        cc=cc_arg,
        no_excel=True,
        subject_prefix="MS Network Availability Daily Report",
        body_file=body_file,
    )
