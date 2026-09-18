# -*- coding: utf-8 -*-
"""
import logging
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

import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path
from typing import List, Optional

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

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
_SP_DATA = "/01_RPA/LBR_Tools/SP/sp_report"                        # 远程 FTP（已弃用，见 _SP_LOCAL_DATA）
_SP_EMAIL = "/01_RPA/LBR_Tools/SP/sp_report/email"                  # 远程 FTP（已弃用，见 _SP_EMAIL_UNC）
# SP 报表：生成端已集成到 my_app（sp_report_gen 服务），产物输出到本地 data/sp_email；
# 邮件收件人名单仍用远程共享路径（用户指定）
_SP_LOCAL_DATA = MY_APP_DIR / "data" / "sp_email"
from backend.config.remote_host import get_remote_host
_SP_EMAIL_UNC = rf"\\{get_remote_host()}\e\01_RPA\LBR_Tools\SP\sp_report\email"
_SP_GEN_SCRIPT = Path(__file__).resolve().parent / "sp_report_gen" / "gernarate_sp_report.py"
# SP 备件明细：data/sp_email/data 下 4 份明细 xlsx 合并为一个工作簿（sheet:
# Inventory/Inbound/Outbound/Transfer）整包发送，主题与附件名携带时间戳
_SP_DETAILS_DATA = MY_APP_DIR / "data" / "sp_email" / "data"
_SP_DETAILS_DEFAULT_TO = "ansah.boadu@zte.com.cn"
_SP_DETAILS_DEFAULT_CC = "dong.xinmin@zte.com.cn"
# SP 物料库存与消耗报表（page=sp_material / SpMaterialSummary）：
# 数据由 sp_material_summary_service.get_material_summary() 实时算出（读 PG/app.db 的
# inventory_details + outband_details），Excel 落盘 data/sp_material_report 后作为附件发送。
_SP_MATERIAL_REPORT_DIR = MY_APP_DIR / "data" / "sp_material_report"
_SP_MATERIAL_DEFAULT_TO = (
    "ztenoc.olr@orange.com;"
    "akpoue.paul@zte.com.cn;nathaniel.seku@zte.com.cn;"
    "pountounyinyi.emmanuel@zte.com.cn;ahmed.youssif@zte.com.cn;"
    "franklin.peter@zte.com.cn;zeeshan.mazhar2@zte.com.cn;"
    "festus.emmanuel1@zte.com.cn;varfee.sarnor@zte.com.cn;"
    "yu.guojun@zte.com.cn;zhang.wanqing3@zte.com.cn;"
    "dong.xinmin@zte.com.cn;gorson.t@zte.com.cn;"
    "marcus.nyomah@zte.com.cn;bakare.gbenga@zte.com.cn"
)
_SP_MATERIAL_DEFAULT_CC = "zhang.wanqing3@zte.com.cn;dong.xinmin@zte.com.cn"
# UME Dong customer 客户业务 KPI + OSG 周报（任务 ume_in_osg_report，2026-09-18 新增）：
# 附件 = backend/services/ume_in/t_osg_build.py 生成的
#        data/in_data/OSG Weekly QoS Analysis Report_<起>_<止>.xlsx
# 收件人为主送/抄送默认值（用户指定），可在 Settings → Email Recipient Settings 覆盖。
_UME_IN_OSG_DEFAULT_TO = "djoumene.reussite1@zte.com.cn"
_UME_IN_OSG_DEFAULT_CC = "dong.xinmin@zte.com.cn"
_UME_IN_OSG_DATA = MY_APP_DIR / "data" / "in_data"
_UME_IN_OSG_NAME_PREFIX = "OSG Weekly QoS Analysis Report"
# 带窗口日期的产物名（模板本体 "OSG Weekly QoS Analysis Report.xlsx" 不匹配）
_UME_IN_OSG_WINDOW_RE = re.compile(
    r"^OSG Weekly QoS Analysis Report_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$"
)
# SP 在线未关闭单报表：sp_report_gen/generate_sp_online_report.py 产出 PNG+XLSX
_SP_ONLINE_DATA = MY_APP_DIR / "data" / "sp_email" / "sp_online"
_SP_ONLINE_GEN_SCRIPT = Path(__file__).resolve().parent / "sp_report_gen" / "generate_sp_online_report.py"
# WhatsApp 目标群组（用户指定，独立于 WHATSAPP_GROUPS）
_SP_ONLINE_WA_GROUPS = ["WH&SP Management"]
# Comsumables & SpareParts 报表 WhatsApp 发送目标群组（07:15）
_SP_WA_GROUPS = ["WH&SP Management"]
# Comsumables & SpareParts 报表 WhatsApp 发送的报表类别（与邮件任务口径一致）
_SP_WA_REPORT_LABELS = ("Comsumables", "SpareParts")
# SP 备件明细报表（sp_email_details）邮件发出后，同步把同一份合并 Excel
# 作为文档发到该群（用户 2026-09-14 指定，独立于 WHATSAPP_GROUPS）
_SP_DETAILS_WA_GROUPS = ["WH&SP Management"]
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
    images: Optional[list] = None,
    attach: Optional[list] = None,
    subject: Optional[str] = None,
    retries: int = 3,
    per_attempt_timeout: int = 300,
    budget: int = 360,
) -> dict:
    """调用通用邮件脚本，返回 {success, message/detail/error}。

    对 EWS / FTP 偶发连接重置（10054 / ConnectionReset / TransportError 等）做
    指数退避重试：Orange 邮件网关在版本协商握手阶段偶发被远端强制断开，但通常在
    数秒~数十秒内自愈。多试几次可显著降低日报漏发。

    异步/防阻塞：实际发送在后台 daemon 线程执行，主线程最多等待 ``budget`` 秒后返回，
    避免 EWS 降级时一个邮件任务长期霸占调度 worker。正常情况会在 budget 内拿到真实结果。

    ⚠️ 超时预算 120/180 → 300/360（2026-09-18）。原值对**冷启动**太紧：实测一次
    完整发送（NTLM 握手 + 附件上传 5.6MB + CreateItem/SendItem）冷启动耗时
    **198.49s**，被 ``per_attempt_timeout=120`` 直接杀掉，任务记为失败却可能已经发出。
    网络本身没问题（同一封邮件热态只需 5.36s，裸上传速率 1.3MB/s），所以放宽即可。
    与 ``liberia_email_report._run_script`` 的 300/360 保持一致。
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
    if images:
        # 显式指定内嵌图片，避免目录残留旧 PNG 被一并发现导致重复内嵌
        for img in images:
            cmd += ["--images", str(img)]
    if attach:
        # 多附件：每份文件用一次 --attach（脚本 action="append"）
        for a in attach:
            cmd += ["--attach", str(a)]
    if subject:
        cmd += ["--subject", subject]
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
                    creationflags=_SUBPROCESS_FLAGS,
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
                # 超时后立即返回，不重试：服务端可能已接收邮件只是响应慢，
                # 重试会导致同一封邮件发送两次。
                logging.getLogger(__name__).warning(
                    "[kpi_email] 邮件脚本超时（%ss），不重试（避免重复发送）",
                    per_attempt_timeout,
                )
                return {"success": False, "error": f"timeout: {e}"}
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
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("kpi_ms_contract", to, cc)
    return _run_script(
        data_dir=_MS_SLA_DATA,
        name_filter="MS Contract KPIs Achievements Daily Report",
        to=to_arg,
        cc=cc_arg,
    )


def run_ms_wo_sla(to: str = None, cc: str = None) -> dict:
    """MS WOs SLA Achievements Daily Report 邮件（数据本地）。"""
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("kpi_ms_wo_sla", to, cc)
    return _run_script(
        data_dir=_MS_SLA_DATA,
        name_filter="MS WOs SLA Achievements Daily Report",
        to=to_arg,
        cc=cc_arg,
    )


def _resolve_recipients_unc(email_dir_unc: str, to: Optional[str], cc: Optional[str]):
    """从远程共享路径(UNC)名单读取主送/抄送。to/cc 显式传入时优先（测试用）。"""
    import backend.services.remote_ftp as rf

    def _read(name: str) -> str:
        p = Path(email_dir_unc) / name
        try:
            return p.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            return ""

    to_list = rf.parse_addresses(_read("ss_email.txt"))
    cc_list = rf.parse_addresses(_read("cc_email.txt"))
    to_arg = to if to is not None else (";".join(to_list) or None)
    cc_arg = cc if cc is not None else ";".join(cc_list)
    return to_arg, cc_arg


def run_sp_report_generate(to: str = None, cc: str = None) -> dict:
    """SP 备件报表生成：从 SFTP 下载数据，生成 Comsumables / SpareParts
    Inbound&Outbound&Inventory 报表到本地 data/sp_email（邮件任务随后发送）。

    生成脚本需要 pandas/paramiko/openpyxl/PIL，托管 venv 缺 paramiko，
    因此必须用后端系统 Python（sys.executable，已装全部依赖）执行。
    """
    script = _SP_GEN_SCRIPT
    if not script.is_file():
        return {"success": False, "error": f"生成脚本不存在: {script}"}

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "报表生成超时(>600s)，SFTP 或报表生成过慢"}
    except Exception as e:
        return {"success": False, "error": f"报表生成启动失败: {e}"}

    out = (proc.stdout or "") + (proc.stderr or "")
    elapsed = time.time() - t0
    if proc.returncode != 0:
        return {"success": False, "error": f"报表生成失败 returncode={proc.returncode}\n{out[-2000:]}"}

    # 生成结果完整性校验：两类总表 xlsx 必须存在
    missing = []
    for prefix in ("Comsumables Inbound&Outbound&Inventory ", "SpareParts Inbound&Outbound&Inventory "):
        hits = list(_SP_LOCAL_DATA.glob(f"{prefix}*.xlsx")) if _SP_LOCAL_DATA.is_dir() else []
        if not hits:
            missing.append(prefix)
    if missing:
        return {"success": False, "error": f"报表生成未产出完整文件，缺失: {missing}"}

    tail = "\n".join(out.strip().splitlines()[-15:])
    return {"success": True, "message": f"报表生成成功 ({elapsed:.1f}s)", "detail": tail}


def run_sp_spareparts(to: str = None, cc: str = None) -> dict:
    """SpareParts 备件报表邮件（数据本地 sp_email 生成端产出，名单远程共享路径）。"""
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("kpi_sp_spareparts", to, cc)
    if not _SP_LOCAL_DATA.is_dir():
        return {"success": False, "error": f"报表目录不存在: {_SP_LOCAL_DATA}（请先运行 sp_report_generate 任务）"}
    excel = _pick_consolidated([f for f in _SP_LOCAL_DATA.glob("*.xlsx") if "SpareParts" in f.name])
    if excel is None:
        return {"success": False, "error": f"未在 {_SP_LOCAL_DATA} 找到 SpareParts 报表，请检查 sp_report_generate 任务"}
    return _run_script(
        data_dir=_SP_LOCAL_DATA,
        name_filter="SpareParts",
        to=to_arg,
        cc=cc_arg,
        excel=excel,
    )


def run_sp_consumables(to: str = None, cc: str = None) -> dict:
    """Comsumables 耗材报表邮件（数据本地 sp_email 生成端产出，名单远程共享路径）。"""
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("kpi_sp_consumables", to, cc)
    if not _SP_LOCAL_DATA.is_dir():
        return {"success": False, "error": f"报表目录不存在: {_SP_LOCAL_DATA}（请先运行 sp_report_generate 任务）"}
    excel = _pick_consolidated([f for f in _SP_LOCAL_DATA.glob("*.xlsx") if "Comsumables" in f.name])
    if excel is None:
        return {"success": False, "error": f"未在 {_SP_LOCAL_DATA} 找到 Comsumables 报表，请检查 sp_report_generate 任务"}
    return _run_script(
        data_dir=_SP_LOCAL_DATA,
        name_filter="Comsumables",
        to=to_arg,
        cc=cc_arg,
        excel=excel,
    )


def _merge_sp_details_workbook(out_path: Path) -> dict:
    """把 data/sp_email/data 下的明细 xlsx 合并为**一个**工作簿（每个明细一个 sheet）。

    sheet 对应关系（明细已在 sp_report_generate 里过滤过，这里原样合并、不再加工）：
      Inventory       <- inventory_details.xlsx
      Inbound         <- inband_details.xlsx
      Outbound        <- outband_details.xlsx
      Transfer        <- transfer_details.xlsx
      Transfer Return <- transfer_return_details.xlsx（可选）

    返回 {sheet_name: 行数}；前 4 份任一缺失抛 FileNotFoundError，
    可选明细（Transfer Return）缺失时只告警并跳过，不影响整包发送。
    """
    import pandas as pd

    sheet_sources = [
        ("Inventory", "inventory_details.xlsx", True),
        ("Inbound", "inband_details.xlsx", True),
        ("Outbound", "outband_details.xlsx", True),
        ("Transfer", "transfer_details.xlsx", True),
        ("Transfer Return", "transfer_return_details.xlsx", False),
    ]
    row_counts = {}
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet_name, fname, required in sheet_sources:
            src = _SP_DETAILS_DATA / fname
            if not src.is_file():
                if required:
                    raise FileNotFoundError(f"明细源文件缺失: {src}")
                logging.getLogger(__name__).warning(
                    "[sp_details] 可选明细缺失，跳过 sheet %s: %s", sheet_name, src
                )
                continue
            df = pd.read_excel(src)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            row_counts[sheet_name] = int(len(df))
    return row_counts


def _prune_sp_details_reports(keep: "Path") -> int:
    """只保留最新一份合并报表：删除 data/sp_email/data 下除 keep 之外的
    所有 "SP Details Report *.xlsx"。

    删除失败（如文件被 Excel 占用）仅记录告警，不影响本次发送。
    返回实际删除的文件数。
    """
    removed = 0
    try:
        keep_key = str(keep.resolve()).lower()
    except Exception:
        keep_key = str(keep).lower()
    for old in _SP_DETAILS_DATA.glob("SP Details Report *.xlsx"):
        try:
            if str(old.resolve()).lower() == keep_key:
                continue
            old.unlink()
            removed += 1
        except Exception as e:  # 被占用/权限问题
            logging.getLogger(__name__).warning(
                "[sp_details] 删除历史合并文件失败: %s (%s)", old.name, e
            )
    return removed


def _send_sp_details_to_whatsapp(merged_path: Path) -> dict:
    """把合并后的 SP Details Report 作为**文档**发到 WhatsApp 群 WH&SP Management。

    复用 ``whatsapp_service.run_whatsapp_send`` 的 Playwright 机制（与
    sp_online_report_send / sp_whatsapp_report 同一套）。

    ⚠️ ``photos=[]`` 必须显式传入：``photos=None`` 会触发
    ``_collect_photos_and_captions()``，把站点中断截图一并灌进这个管理群。
    """
    try:
        from backend.services.whatsapp_service import run_whatsapp_send
        return run_whatsapp_send(
            photos=[],
            captions=[],
            files=[str(merged_path)],
            groups=_SP_DETAILS_WA_GROUPS,
        )
    except Exception as e:
        return {"success": False, "groups_sent": [], "errors": [f"WhatsApp 发送异常: {e}"]}


def run_sp_details_email(to: str = None, cc: str = None) -> dict:
    """SP 备件明细报表：邮件 + WhatsApp（每天一班，时间见 task_registry / 调度配置）。

    把 data/sp_email/data 下 4 份明细 xlsx（inventory/inband/outband/transfer）
    合并为一个 Excel 工作簿（sheet：Inventory/Inbound/Outbound/Transfer），
    附件与主题均携带发送时间戳，例如：
      附件: SP Details Report 2026-09-04 11-32-00.xlsx
      主题: SP Spare Parts Details Report 2026-09-04 11-32-00

    发送渠道（顺序执行，互不阻塞）：
      1. 邮件：附件为该合并工作簿。收件人固定：主送 ansah.boadu@zte.com.cn，
         抄送 dong.xinmin@zte.com.cn；可在 Settings → Email Recipient Settings 覆盖。
      2. WhatsApp：邮件之后把**同一份**合并 Excel 作为文档发到群 WH&SP Management
         （2026-09-14 新增）。WhatsApp 侧失败不会重发邮件，见下方 error 组装注释。
    """
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("sp_email_details", to, cc)
    if not _SP_DETAILS_DATA.is_dir():
        return {"success": False, "error": f"数据目录不存在: {_SP_DETAILS_DATA}"}
    if not to_arg:
        return {"success": False, "error": "主送收件人为空，请在 Settings → Email Recipient Settings 配置 sp_email_details"}

    # 主题与附件共用同一时间戳（格式如 2026-09-04 11-32-00）
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    merged_path = _SP_DETAILS_DATA / f"SP Details Report {stamp}.xlsx"

    try:
        row_counts = _merge_sp_details_workbook(merged_path)
    except Exception as e:
        return {"success": False, "error": f"明细合并失败: {e}"}

    # 只保留最新一份：新文件生成成功后，删除同目录下其它历史 SP Details Report
    pruned = _prune_sp_details_reports(keep=merged_path)

    logging.getLogger(__name__).info(
        "[sp_details] 合并完成: %s rows=%s 清理历史文件=%d",
        merged_path.name, row_counts, pruned,
    )

    email_res = _run_script(
        data_dir=_SP_DETAILS_DATA,
        name_filter="",
        to=to_arg,
        cc=cc_arg,
        no_excel=True,
        attach=[str(merged_path)],
        subject=f"SP Spare Parts Details Report {stamp}",
    )

    # 邮件之后同步发一份到 WhatsApp 群 WH&SP Management（2026-09-14 新增）。
    # 与邮件互不阻塞：邮件失败也照发群，避免一个渠道故障把另一个渠道一起拖掉。
    wa_res = _send_sp_details_to_whatsapp(merged_path)

    email_ok = bool(email_res.get("success"))
    wa_ok = bool(wa_res.get("success"))
    res = {
        "success": email_ok and wa_ok,
        "message": (
            f"Email={'OK' if email_ok else 'FAIL'}, WhatsApp={'OK' if wa_ok else 'FAIL'}"
            f" (groups_sent={wa_res.get('groups_sent')}) | "
            f"合并 {merged_path.name} rows={row_counts} 清理历史={pruned}"
        ),
        "merged_file": str(merged_path),
        "row_counts": row_counts,
        "pruned": pruned,
        "email": email_res,
        "whatsapp": {
            k: wa_res.get(k)
            for k in ("success", "groups_sent", "errors", "elapsed_seconds")
        },
    }

    # error 的组装必须小心：本任务在 email_recovery.EMAIL_TASK_IDS 内，一旦 error
    # 文本命中 EWS 关键字（timed out / ConnectionError / 10054 ...），
    # email_recovery 会把整条失败链「补发」= 11 位收件人重复收到同一份报表邮件。
    # 所以 WhatsApp 侧只写固定标记，底层异常原文留在 res["whatsapp"]["errors"] 里。
    if not email_ok:
        res["error"] = f"Email: {email_res.get('error')}"
    if not wa_ok:
        wa_mark = (
            f"WHATSAPP_FAIL: WhatsApp 发送失败（群 {';'.join(_SP_DETAILS_WA_GROUPS)}）"
        )
        res["error"] = f"{res['error']} | {wa_mark}" if res.get("error") else wa_mark
    return res


# =============================================================================
# SP 物料库存与消耗报表（page=sp_material 的邮件版）
# =============================================================================
# 列定义与页面 frontend/src/pages/SpMaterialSummary.tsx 的 exportExcel 逐格一致：
# 13 列 = WH/DOP + 期初(2) + Current Date(2) + Need Repair + Repair Outbound + 3 个消耗窗口(各 2)
_SP_MATERIAL_SUB_HEADS = (
    "WH/DOP",
    "Spare Part (Good)", "Consumables",       # 期初
    "Spare Part (Good)", "Consumables",       # Current Date
    "Need Repair", "Repair Outbound",
    "Spare Part", "Consumables",              # Consumption from <anchor>
    "Spare Part", "Consumables",              # Consumption this Month
    "Spare Part", "Consumables",              # Consumption this week
)
_SP_MATERIAL_NUM_KEYS = (
    "anchor_spare_good", "anchor_consumables",
    "current_spare_good", "current_consumables",
    "need_repair", "repair_outbound",
    "consumption_from_anchor_spare", "consumption_from_anchor_cons",
    "consumption_month_spare", "consumption_month_cons",
    "consumption_week_spare", "consumption_week_cons",
)
_SP_MATERIAL_SHEET = "SP Material Summary"
_SP_MATERIAL_TITLE = "Spare Parts Inbound & Outbound & Inventory Summary"
# 消耗列（0 基 7~12）套用 0 灰 / 正绿 / 负红，与页面 valueColors: [7..12] 一致
_SP_MATERIAL_VALUE_COLOR_COLS = (7, 8, 9, 10, 11, 12)

# ---- UNIFIED_EXCEL_V1 样式常量（与 frontend/src/utils/excelReport.ts 同源）----
_XLS_FONT = "Calibri"
_XLS_TITLE_TEXT = "1F3864"
_XLS_SUBTITLE_TEXT = "808080"
_XLS_HEADER_TEXT = "FFFFFF"
_XLS_HEADER_FILL = "2F5496"
_XLS_TOTAL_TEXT = "1F3864"
_XLS_TOTAL_FILL = "D6DCE4"
_XLS_ZEBRA_FILL = "F2F2F2"
_XLS_ZERO_TEXT = "C0C0C0"
_XLS_POS_TEXT = "006100"
_XLS_NEG_TEXT = "9C0006"
_XLS_THIN = "B4C6E7"
_XLS_MEDIUM = "4472C4"


def _sp_material_header_cells(anchor: str):
    """两行合并表头，元素为 (row_offset, col_start, text, row_span, col_span)。

    列位置与页面 HeaderCell[][] 的分组逐格一致；被 rowSpan 覆盖的列
    （WH/DOP、Need Repair、Repair Outbound）在第 2 行不再重复占位。
    """
    return [
        # 第 1 行
        (0, 1, "WH/DOP", 2, 1),
        (0, 2, anchor, 1, 2),
        (0, 4, "Current Date", 1, 2),
        (0, 6, "Need Repair", 2, 1),
        (0, 7, "Repair Outbound", 2, 1),
        (0, 8, f"Total Consumption from {anchor}", 1, 2),
        (0, 10, "Total Consumption this Month", 1, 2),
        (0, 12, "Total Consumption this week", 1, 2),
        # 第 2 行（子表头）
        (1, 2, "Spare Part (Good)", 1, 1),
        (1, 3, "Consumables", 1, 1),
        (1, 4, "Spare Part (Good)", 1, 1),
        (1, 5, "Consumables", 1, 1),
        (1, 8, "Spare Part", 1, 1),
        (1, 9, "Consumables", 1, 1),
        (1, 10, "Spare Part", 1, 1),
        (1, 11, "Consumables", 1, 1),
        (1, 12, "Spare Part", 1, 1),
        (1, 13, "Consumables", 1, 1),
    ]


def _sp_material_rows(summary: dict):
    """返回 (total_row, data_rows)，均为 13 列；合计行在前（与页面导出 / 报表规范一致）。"""
    def _to_row(r: dict):
        return (["Total" if r.get("is_total") else (r.get("label") or "")]
                + [int(r.get(k) or 0) for k in _SP_MATERIAL_NUM_KEYS])

    rows = summary.get("rows") or []
    total = next((_to_row(r) for r in rows if r.get("is_total")), None)
    data = [_to_row(r) for r in rows if not r.get("is_total")]
    return total, data


def _sp_material_subtitle(summary: dict) -> str:
    return (
        f"Generated: {summary.get('generated_at') or time.strftime('%Y-%m-%d %H:%M:%S')}"
        f"    |    Sheet: {_SP_MATERIAL_SHEET}"
        f"    |    Current Date: {summary.get('current_date') or '-'}"
        f"    |    Baseline: {summary.get('anchor_date') or '-'}"
        f"    |    Need Repair / Repair Outbound window: "
        f"{summary.get('repair_outbound_start') or '-'} ~ {summary.get('repair_outbound_end') or '-'}"
    )


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _build_sp_material_workbook(out_path: Path, summary: dict) -> dict:
    """生成 UNIFIED_EXCEL_V1 版式的汇总工作簿（与页面「导出 Excel」逐格一致）。

    版式：行1 标题 / 行2 副标题 / 行3-4 两行合并表头（#2F5496）/ 行5 合计行（#D6DCE4）
    / 行6+ 数据行（斑马纹，仅消耗列做 0 灰 / 正绿 / 负红着色）；冻结表头、自动筛选、
    列宽 min(max(最长内容 + 2, 10), 42)、横向按宽缩放 1 页、标签页 #2F5496。
    另加 "Info" sheet 记录口径参数与 warnings。
    返回 {"rows": 数据行数(不含合计行), "warnings", "anchor_date", "current_date"}。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    total_row, data_rows = _sp_material_rows(summary)
    if total_row is None and not data_rows:
        raise ValueError("汇总表没有数据行（inventory_details 可能尚未同步）")

    anchor = summary.get("anchor_date") or ""
    ncol = len(_SP_MATERIAL_SUB_HEADS)
    title = _SP_MATERIAL_TITLE
    subtitle = _sp_material_subtitle(summary)

    wb = Workbook()
    ws = wb.active
    ws.title = _SP_MATERIAL_SHEET
    ws.sheet_properties.tabColor = _XLS_HEADER_FILL

    thin = Side(style="thin", color=_XLS_THIN)
    medium = Side(style="medium", color=_XLS_MEDIUM)
    border_header = Border(left=thin, right=thin, top=thin, bottom=medium)
    border_cell = Border(left=thin, right=thin, top=thin, bottom=thin)
    border_total = Border(left=thin, right=thin, top=medium, bottom=medium)

    def _fill(argb):
        return PatternFill("solid", fgColor=argb)

    # ---- 行 1/2：标题 + 副标题（横向合并整表，左对齐）----
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    c = ws.cell(1, 1, title)
    c.font = Font(name=_XLS_FONT, size=14, bold=True, color=_XLS_TITLE_TEXT)
    c.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
    c = ws.cell(2, 1, subtitle)
    c.font = Font(name=_XLS_FONT, size=9, color=_XLS_SUBTITLE_TEXT)
    c.alignment = Alignment(horizontal="left", vertical="center")

    # ---- 行 3/4：两行合并表头 ----
    header_start = 3
    for row_off, c1, text, row_span, col_span in _sp_material_header_cells(anchor):
        r1 = header_start + row_off
        r2 = r1 + row_span - 1
        c2 = c1 + col_span - 1
        if row_span > 1 or col_span > 1:
            ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
        ws.cell(r1, c1, text)
        for rr in range(r1, r2 + 1):
            for cc in range(c1, c2 + 1):
                cell = ws.cell(rr, cc)
                cell.font = Font(name=_XLS_FONT, size=11, bold=True, color=_XLS_HEADER_TEXT)
                cell.fill = _fill(_XLS_HEADER_FILL)
                cell.alignment = Alignment(horizontal="center", vertical="center",
                                           wrap_text=True)
                cell.border = border_header
    header_end = header_start + 1

    def _style_plain(cell, val, ci: int):
        if _is_num(val):
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.number_format = "#,##0"
        elif ci == 1:
            cell.alignment = Alignment(vertical="center")
        else:
            cell.alignment = Alignment(horizontal="right", vertical="center")

    # ---- 合计行（紧接表头，套用 Total 样式）----
    r = header_end + 1
    if total_row is not None:
        for ci, val in enumerate(total_row, start=1):
            cell = ws.cell(r, ci, val)
            cell.font = Font(name=_XLS_FONT, size=11, bold=True, color=_XLS_TOTAL_TEXT)
            cell.fill = _fill(_XLS_TOTAL_FILL)
            cell.border = border_total
            _style_plain(cell, val, ci)
        r += 1

    # ---- 数据行（斑马纹 + 消耗列着色）----
    for row in data_rows:
        zebra = (r % 2 == 0)
        for ci, val in enumerate(row, start=1):
            cell = ws.cell(r, ci, val)
            cell.fill = _fill(_XLS_ZEBRA_FILL if zebra else "FFFFFF")
            cell.border = border_cell
            if (ci - 1) in _SP_MATERIAL_VALUE_COLOR_COLS and _is_num(val):
                if val == 0:
                    cell.font = Font(name=_XLS_FONT, size=10, color=_XLS_ZERO_TEXT)
                elif val > 0:
                    cell.font = Font(name=_XLS_FONT, size=10, bold=True, color=_XLS_POS_TEXT)
                else:
                    cell.font = Font(name=_XLS_FONT, size=10, bold=True, color=_XLS_NEG_TEXT)
            else:
                cell.font = Font(name=_XLS_FONT, size=10)
            _style_plain(cell, val, ci)
        r += 1
    last_row = r - 1

    # ---- 列宽：min(max(最长内容 + 2, 10), 42)，最多扫前 200 行 ----
    scan_to = min(last_row, header_end + 200)
    for ci in range(1, ncol + 1):
        max_len = 0
        if ci == 1:
            max_len = max(len(title), len(subtitle))
        for rr in range(header_start, scan_to + 1):
            v = ws.cell(rr, ci).value
            if v is not None:
                max_len = max(max_len, len(str(v)))
        ws.column_dimensions[get_column_letter(ci)].width = min(max(max_len + 2, 10), 42)

    # ---- 冻结表头 + 自动筛选 ----
    ws.freeze_panes = ws.cell(header_end + 1, 1)
    if last_row >= header_end:
        ws.auto_filter.ref = f"A{header_end}:{get_column_letter(ncol)}{last_row}"

    # ---- 页面设置：横向、按宽缩放到 1 页（写入失败不影响内容）----
    try:
        from openpyxl.worksheet.page import PageMargins
        from openpyxl.worksheet.properties import PageSetupProperties

        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5,
                                      header=0.3, footer=0.3)
    except Exception:
        logging.getLogger(__name__).warning(
            "[sp_material] 页面设置写入失败（忽略）", exc_info=True)

    # ---- Info sheet：口径参数 + 数据提示 ----
    info = wb.create_sheet("Info")
    info.append(["Field", "Value"])
    for label, val in (
        ("Generated At", summary.get("generated_at") or ""),
        ("Anchor Date", anchor),
        ("Current Date", summary.get("current_date") or ""),
        ("Latest Snapshot", summary.get("latest_snapshot") or ""),
        ("Month Start", summary.get("month_start") or ""),
        ("Week Start", summary.get("week_start") or ""),
        ("Repair Outbound Window",
         f"{summary.get('repair_outbound_start') or ''} → "
         f"{summary.get('repair_outbound_end') or ''}"),
    ):
        info.append([label, val])
    for c in info[1]:
        c.font = Font(name=_XLS_FONT, size=11, bold=True)
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 96
    warns = summary.get("warnings") or []
    info.append([])
    info.append(["Warnings", f"{len(warns)} 条"])
    for w in warns:
        info.append(["", w])
    for row in info.iter_rows(min_col=2, max_col=2):
        row[0].alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(out_path)
    return {
        "rows": len(data_rows),
        "warnings": warns,
        "anchor_date": anchor,
        "current_date": summary.get("current_date") or "",
    }


def _sp_material_sections(anchor: str):
    """区块表头 [(label, start_col, end_col)]（0 基闭区间），对应 Excel 的分组表头。"""
    return [
        (f"Opening {anchor}", 1, 2),
        ("Current Date", 3, 4),
        (f"Consumption from {anchor}", 7, 8),
        ("Consumption this Month", 9, 10),
        ("Consumption this week", 11, 12),
    ]


def _render_sp_material_image(summary: dict, out_img_path: Path) -> dict:
    """把 SP 物料库存与消耗汇总渲染成 PNG（Pillow 手绘表格）。

    渲染手法对齐 backend/services/sp_report_gen/gernarate_sp_report.py 的
    ``_render_summary_image``：Arial 字体、蓝色表头 #2F5496、橙色区块条 #FF8C00、
    浅蓝网格线 #B4C6E7、斑马纹、0 值浅灰、文字居中。行序与 Excel 一致（合计行在前）。
    返回 {"image_path", "width", "height", "rows"}。
    """
    from PIL import Image, ImageDraw, ImageFont

    total_row, data_rows = _sp_material_rows(summary)
    has_total = total_row is not None
    body = ([total_row] if has_total else []) + data_rows
    if not body:
        raise ValueError("汇总表没有数据行，无法生成图片")

    anchor = summary.get("anchor_date") or ""
    current = summary.get("current_date") or ""
    sections = _sp_material_sections(anchor)
    title = f"{_SP_MATERIAL_TITLE}  |  {anchor} → {current}"

    font_size = 15
    row_h = 34
    padding = 16
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
        font_bold = ImageFont.truetype("arialbd.ttf", font_size)
        font_title = ImageFont.truetype("arialbd.ttf", font_size + 4)
    except Exception:  # 字体缺失时退回默认位图字体（与 gernarate_sp_report 一致）
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def _tw(text, f) -> int:
        try:
            return int(scratch.textlength(str(text), font=f))
        except Exception:
            return len(str(text)) * 8

    header_h = font_size + 18
    section_h = font_size + 16
    title_h = font_size + 26

    n_cols = len(_SP_MATERIAL_SUB_HEADS)
    # 列宽 = 表头/单元格内容最大宽度 + 余量；再让区块标签把所属列撑开，避免文字越界
    col_w = []
    for i in range(n_cols):
        w = _tw(_SP_MATERIAL_SUB_HEADS[i], font_bold)
        for br in body:
            f = font_bold if br[0] == "Total" else font
            w = max(w, _tw(br[i], f))
        col_w.append(w + 18)
    for label, s, e in sections:
        need = _tw(label, font_bold) + 16
        have = sum(col_w[s:e + 1])
        if need > have:
            share = int((need - have) / (e - s + 1)) + 1
            for i in range(s, e + 1):
                col_w[i] += share

    table_w = sum(col_w) + padding * 2
    total_w = max(table_w, _tw(title, font_title) + padding * 2)
    total_h = padding + title_h + section_h + header_h + len(body) * row_h + padding

    BLUE = (47, 84, 150)
    ORANGE = (255, 140, 0)
    LINE = (180, 198, 231)
    ZEBRA = (242, 242, 242)
    TOTAL_BG = (214, 220, 228)
    ZERO_FG = (192, 192, 192)
    TOTAL_FG = (31, 56, 100)

    img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    def _col_x(i: int) -> int:
        return padding + sum(col_w[:i])

    y = padding
    draw.text((padding, y), title, fill=BLUE, font=font_title)
    y += title_h

    # 区块表头：整行蓝底 + 各区块橙底居中白字
    x = padding
    for i in range(n_cols):
        draw.rectangle([x, y, x + col_w[i], y + section_h], fill=BLUE, outline=LINE)
        x += col_w[i]
    for label, s, e in sections:
        x0, x1 = _col_x(s), _col_x(e) + col_w[e]
        draw.rectangle([x0, y, x1, y + section_h], fill=ORANGE, outline=LINE)
        tw = _tw(label, font_bold)
        draw.text((x0 + (x1 - x0 - tw) // 2, y + (section_h - font_size) // 2 - 2),
                  label, fill=(255, 255, 255), font=font_bold)
    y += section_h

    # 列名表头
    x = padding
    for i in range(n_cols):
        draw.rectangle([x, y, x + col_w[i], y + header_h], fill=BLUE, outline=LINE)
        tw = _tw(_SP_MATERIAL_SUB_HEADS[i], font_bold)
        draw.text((x + (col_w[i] - tw) // 2, y + (header_h - font_size) // 2 - 2),
                  _SP_MATERIAL_SUB_HEADS[i], fill=(255, 255, 255), font=font_bold)
        x += col_w[i]
    y += header_h

    # 数据行（合计行在前：灰底加粗；0 值浅灰；斑马纹与 Excel 同序）
    for idx, br in enumerate(body):
        is_total = has_total and idx == 0
        data_idx = idx - (1 if has_total else 0)
        for i, val in enumerate(br):
            x = _col_x(i)
            if is_total:
                bg = TOTAL_BG
            elif data_idx % 2 == 0:
                bg = ZEBRA
            else:
                bg = (255, 255, 255)
            draw.rectangle([x, y, x + col_w[i], y + row_h], fill=bg, outline=LINE)
            txt = f"{val:,}" if isinstance(val, int) else str(val)
            f = font_bold if is_total else font
            tw = _tw(txt, f)
            if is_total:
                fg = TOTAL_FG
            elif isinstance(val, int) and val == 0:
                fg = ZERO_FG
            else:
                fg = (0, 0, 0)
            draw.text((x + (col_w[i] - tw) // 2, y + (row_h - font_size) // 2 - 2),
                      txt, fill=fg, font=f)
        y += row_h

    out_img_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_img_path, "PNG")
    return {"image_path": str(out_img_path), "width": total_w,
            "height": total_h, "rows": len(body)}


def _prune_sp_material_reports(*keep: Path) -> int:
    """只保留本次生成的报表：删除 data/sp_material_report 下其它
    "SP_Material_Summary*" 的 xlsx / png。删除失败仅告警，不影响本次发送。"""
    keep_keys = set()
    for k in keep:
        try:
            keep_keys.add(str(k.resolve()).lower())
        except Exception:
            keep_keys.add(str(k).lower())
    removed = 0
    for old in _SP_MATERIAL_REPORT_DIR.glob("SP_Material_Summary*"):
        if old.suffix.lower() not in (".xlsx", ".png"):
            continue
        try:
            if str(old.resolve()).lower() in keep_keys:
                continue
            old.unlink()
            removed += 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "[sp_material] 删除历史报表失败: %s (%s)", old.name, e
            )
    return removed


def run_sp_material_stock_consumption(to: str = None, cc: str = None) -> dict:
    """SP Material Stock & Consumption 报表邮件（每天 07:33）。

    数据来源与页面 myapp/?page=sp_material 完全一致：
    backend.services.sp_material_summary_service.get_material_summary()
    （inventory_details 每日全量快照 + outband_details 报修出库）。

    产出两份同名报表（沿用页面导出的文件名，便于与手工导出对齐）：
      - Excel：UNIFIED_EXCEL_V1 版式（标题 / 副标题 / 两行合并表头 / 合计行在前 /
        13 列数据 + Info sheet），与页面「导出 Excel」逐格一致
      - PNG ：同一张汇总表的手绘图片（Pillow，手法同 sp_report_gen 的报表图片），
        作为正文内嵌图片展示，收件人无需打开附件即可看数
      附件: SP_Material_Summary_2026-09-11.xlsx
      图片: SP_Material_Summary_2026-09-11.png（内嵌正文）
      主题: SP Material Stock & Consumption Report 2026-09-11
    图片生成失败不阻断发送（只发 Excel 并告警）。
    收件人默认 15 主送 + 2 抄送（见 _SP_MATERIAL_DEFAULT_TO/_CC），
    可在 Settings → 邮件收件人 覆盖。
    """
    from backend.services.email_recipient_store import get_email_recipients
    from backend.services.sp_material_summary_service import get_material_summary

    to_arg, cc_arg = get_email_recipients("sp_material_report", to, cc)
    if not to_arg:
        return {"success": False,
                "error": "主送收件人为空，请在 Settings → 邮件收件人 配置 sp_material_report"}

    try:
        summary = get_material_summary()
    except Exception as e:
        return {"success": False, "error": f"汇总数据计算失败: {e}"}

    if not (summary.get("rows") or []):
        warns = "；".join(summary.get("warnings") or []) or "无数据行"
        return {"success": False, "error": f"汇总表无数据，跳过发送（{warns}）"}

    try:
        _SP_MATERIAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": f"创建报表目录失败: {_SP_MATERIAL_REPORT_DIR} ({e})"}

    stamp = summary.get("current_date") or time.strftime("%Y-%m-%d")
    out_path = _SP_MATERIAL_REPORT_DIR / f"SP_Material_Summary_{stamp}.xlsx"
    img_path = _SP_MATERIAL_REPORT_DIR / f"SP_Material_Summary_{stamp}.png"

    try:
        meta = _build_sp_material_workbook(out_path, summary)
    except Exception as e:
        return {"success": False, "error": f"Excel 生成失败: {e}"}

    img_meta = None
    try:
        img_meta = _render_sp_material_image(summary, img_path)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "[sp_material] 图片生成失败（仍发送 Excel）: %s", e)

    pruned = _prune_sp_material_reports(out_path, img_path)
    logging.getLogger(__name__).info(
        "[sp_material] 报表已生成: %s rows=%s image=%s anchor=%s current=%s 清理历史=%d warnings=%d",
        out_path.name, meta["rows"], (img_meta or {}).get("image_path") or "FAILED",
        meta["anchor_date"], meta["current_date"], pruned, len(meta["warnings"]),
    )

    res = _run_script(
        data_dir=_SP_MATERIAL_REPORT_DIR,
        name_filter="",
        to=to_arg,
        cc=cc_arg,
        no_excel=True,
        images=[str(img_path)] if img_meta else None,
        attach=[str(out_path)],
        subject=f"SP Material Stock & Consumption Report {stamp}",
    )
    res["report_path"] = str(out_path)
    res["image_path"] = (img_meta or {}).get("image_path")
    res["report_rows"] = meta["rows"]
    res["report_warnings"] = meta["warnings"]
    return res


def run_sp_online_report_generate() -> dict:
    """SP 在线未关闭单报表生成（每天 06:00）：基于 data/sp_email/data 最新
    inband/outband 明细生成 sp_online 下 Inbound/Outbound 的 PNG + XLSX，
    作为 06:20 sp_online_report_send 任务的数据来源。
    """
    script = _SP_ONLINE_GEN_SCRIPT
    if not script.is_file():
        return {"success": False, "error": f"生成脚本不存在: {script}"}

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "在线报表生成超时(>300s)"}
    except Exception as e:
        return {"success": False, "error": f"生成启动失败: {e}"}

    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return {"success": False, "error": f"生成失败 returncode={proc.returncode}\n{out[-2000:]}"}

    missing = [n for n in ("Inbound.xlsx", "Outbound.xlsx") if not (_SP_ONLINE_DATA / n).is_file()]
    if missing:
        return {"success": False, "error": f"生成未产出完整文件，缺失: {missing}"}

    tail = "\n".join(out.strip().splitlines()[-10:])
    return {"success": True, "message": f"在线报表生成成功 ({time.time() - t0:.1f}s)", "detail": tail}


def run_sp_online_report(to: str = None, cc: str = None) -> dict:
    """SP 在线未关闭单报表发送（每天 06:20）：邮件 + WhatsApp。

    邮件：sp_online 下 Inbound/Outbound PNG 内嵌正文 + 两份 XLSX 附件；
    WhatsApp：两张 PNG 带备注发群，两份 XLSX 以文件发送（复用 whatsapp_service
    的 Playwright 发送机制，群组固定 WH&SP Management，不走 WHATSAPP_GROUPS）。
    收件人默认复用 SP 报表远程共享名单，可在 Settings → Email Recipient Settings 覆盖。
    """
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("sp_online_report", to, cc)
    if not _SP_ONLINE_DATA.is_dir():
        return {"success": False, "error": f"报表目录不存在: {_SP_ONLINE_DATA}（请先运行 sp_online_report_generate 任务）"}
    images = [str(_SP_ONLINE_DATA / n) for n in ("Inbound.png", "Outbound.png")
              if (_SP_ONLINE_DATA / n).is_file()]
    attach = [str(_SP_ONLINE_DATA / n) for n in ("Inbound.xlsx", "Outbound.xlsx")
              if (_SP_ONLINE_DATA / n).is_file()]
    if not attach:
        return {"success": False, "error": f"未在 {_SP_ONLINE_DATA} 找到 Inbound/Outbound XLSX（请先运行 sp_online_report_generate 任务）"}
    if not to_arg:
        return {"success": False, "error": "主送收件人为空，请在 Settings → Email Recipient Settings 配置 sp_online_report"}

    email_res = _run_script(
        data_dir=_SP_ONLINE_DATA,
        name_filter="",
        to=to_arg,
        cc=cc_arg,
        no_excel=True,
        images=images,
        attach=attach,
        subject="SP Online Open Tickets Report (Inbound & Outbound)",
    )

    try:
        from backend.services.whatsapp_service import run_whatsapp_send
        wa_res = run_whatsapp_send(
            photos=images,
            captions=[f"*SP Online {Path(p).stem}* (Open Tickets)" for p in images],
            files=attach,
            groups=_SP_ONLINE_WA_GROUPS,
        )
    except Exception as e:
        wa_res = {"success": False, "groups_sent": [], "errors": [f"WhatsApp 发送异常: {e}"]}

    email_ok = bool(email_res.get("success"))
    wa_ok = bool(wa_res.get("success"))
    errors = []
    if not email_ok:
        errors.append(f"Email: {email_res.get('error')}")
    if not wa_ok:
        errors.append(f"WhatsApp: {'; '.join(wa_res.get('errors') or [])}")
    res = {
        "success": email_ok and wa_ok,
        "message": f"Email={'OK' if email_ok else 'FAIL'}, "
                   f"WhatsApp={'OK' if wa_ok else 'FAIL'} (groups_sent={wa_res.get('groups_sent')})",
        "email": email_res,
        "whatsapp": {k: wa_res.get(k) for k in ("success", "groups_sent", "errors", "elapsed_seconds")},
    }
    if errors:
        res["error"] = " | ".join(errors)
    return res


def _pick_sp_report_assets(name_filter: str):
    """在 data/sp_email 下选取某类报表（Comsumables / SpareParts）的「邮件同款」产物。

    与邮件任务保持同一口径：
      - Excel：``_pick_consolidated`` 选出的合并总表（文件名不含 " - Liberia"），
        与 run_sp_spareparts / run_sp_consumables 发给收件人的那份一致；
      - 图片：该类报表的全部 PNG，主图在前、"Summary-Changed" 摘要图在后。
    """
    xlsxs = [f for f in _SP_LOCAL_DATA.glob("*.xlsx")
             if not f.name.startswith("~$") and name_filter in f.name]
    excel = _pick_consolidated(xlsxs)
    pngs = [f for f in list(_SP_LOCAL_DATA.glob("*.png")) + list(_SP_LOCAL_DATA.glob("*.jpg"))
            if not f.name.startswith("~$") and name_filter in f.name]
    pngs.sort(key=lambda p: (1 if "Summary-Changed" in p.name else 0, p.name))
    return excel, pngs


def run_sp_whatsapp_report() -> dict:
    """Comsumables & SpareParts 报表 WhatsApp 发送（每天 07:15）。

    把 kpi_sp_consumables / kpi_sp_spareparts 两个邮件任务使用的同一批产物
    （各类报表的合并总表 XLSX + 报表 PNG）发送到 WhatsApp 群 WH&SP Management。
    只发 WhatsApp，不重复发邮件。
    """
    if not _SP_LOCAL_DATA.is_dir():
        return {"success": False, "error": f"报表目录不存在: {_SP_LOCAL_DATA}（请先运行 sp_report_generate 任务）"}

    photos: List[str] = []
    captions: List[str] = []
    files: List[str] = []
    for label in _SP_WA_REPORT_LABELS:
        excel, pngs = _pick_sp_report_assets(label)
        if excel is None:
            return {"success": False, "error": f"未在 {_SP_LOCAL_DATA} 找到 {label} 报表 XLSX（请先运行 sp_report_generate 任务）"}
        if not pngs:
            return {"success": False, "error": f"未在 {_SP_LOCAL_DATA} 找到 {label} 报表图片（请先运行 sp_report_generate 任务）"}
        files.append(str(excel))
        for p in pngs:
            photos.append(str(p))
            captions.append(f"*{label} {p.stem}*")

    try:
        from backend.services.whatsapp_service import run_whatsapp_send
        wa_res = run_whatsapp_send(
            photos=photos,
            captions=captions,
            files=files,
            groups=_SP_WA_GROUPS,
        )
    except Exception as e:
        wa_res = {"success": False, "groups_sent": [], "errors": [f"WhatsApp 发送异常: {e}"]}

    wa_ok = bool(wa_res.get("success"))
    res = {
        "success": wa_ok,
        "message": f"WhatsApp={'OK' if wa_ok else 'FAIL'} (groups_sent={wa_res.get('groups_sent')})",
        "photos": photos,
        "files": files,
        "whatsapp": {k: wa_res.get(k) for k in ("success", "groups_sent", "errors", "elapsed_seconds")},
    }
    if not wa_ok:
        res["error"] = "; ".join(wa_res.get("errors") or ["WhatsApp 发送失败"])
    return res


def _write_body_file(cache: Path, body: str) -> Path:
    """把邮件正文写入 cache 下的「唯一临时文件」，并对 Windows 文件锁做短重试。

    根因：本机存在 WPS 云同步 + Windows Defender 实时扫描 + Search Indexer
    三重文件锁（见 fix_file_lock.ps1），Python 写固定名 _body.txt 时偶被外部进程
    短暂独占，触发 ``[Errno 13] Permission denied``。

    对策：
      1) 每次运行用 tempfile 生成唯一文件名（``_body_<随机>.txt``），避免多实例 /
         恢复补发并发复用同一固定名造成的互相锁争用；
      2) 写失败按 0.4 / 0.8 / 1.2 / 1.6s 退避重试最多 5 次，吸收瞬时外锁。
    返回临时文件路径，调用方用完后应 unlink 清理。
    """
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = ""
    fd, tmp = tempfile.mkstemp(prefix="_body_", suffix=".txt", dir=str(cache))
    os.close(fd)
    tmp = Path(tmp)
    last_err = None
    for attempt in range(1, 6):
        try:
            tmp.write_text(body, encoding="utf-8")
            return tmp
        except PermissionError as e:  # 外锁（Defender / 索引 / WPS 云同步）
            last_err = e
            if attempt < 5:
                time.sleep(0.4 * attempt)
                continue
    raise last_err  # type: ignore[misc]


def run_ran_availability(to: str = None, cc: str = None) -> dict:
    """MS Network Availability Daily Report 邮件（仅图片，无 Excel，数据远程 FTP）。"""
    import backend.services.remote_ftp as rf

    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("kpi_ran_availability", to, cc)
    cache = _CACHE_ROOT / "ran_availability"
    rf.download_filtered(_RAN_DATA, cache, name_filter="Availability")
    # 正文使用远程 content_email.txt（"Dear All: ... Please Review, Thanks."）
    body = rf.read_text(f"{_RAN_EMAIL}/content_email.txt")
    # 用唯一临时文件写入正文，并对 Windows 三重锁做重试（见 _write_body_file）
    body_file = _write_body_file(cache, body)
    try:
        return _run_script(
            data_dir=cache,
            name_filter="Availability",
            to=to_arg,
            cc=cc_arg,
            no_excel=True,
            subject_prefix="MS Network Availability Daily Report",
            body_file=body_file,
        )
    finally:
        # 清理唯一临时正文文件（后台预算超时仍在读则忽略，避免残留锁报错）
        try:
            if body_file.exists():
                body_file.unlink()
        except Exception:
            pass


# =====================================================================
# 6. Packet Loss 丢包看板日报邮件
# =====================================================================
_PL_EMAIL = "/01_RPA/LBR_Tools/KPI/packet_lost/pl_email"
_PL_DATA_DIR = MY_APP_DIR / "data" / "packet_lost"
_PL_SCREENSHOT_PREFIX = "_dashboard_screenshot"
_PL_DASHBOARD_URL = "http://192.168.100.20/myapp/?page=packet_loss"


def _capture_packet_loss_screenshot() -> Path:
    """用 Playwright 截取丢包看板页面截图（英文界面 + 已加载 + 无左侧栏 + 地图铺满）。

    关键：Leaflet 地图不会随 full_page 的视口拉伸自动重算尺寸，导致地图停留在
    初始高度、其余内容却撑开，截图里地图"没到底"。解决方案：不用 full_page，
    而是把视口高度设成页面真实高度（让地图按满高初始化），并 dispatch resize
    事件触发 Leaflet invalidateSize()，最后按视口截图。
    """
    from playwright.sync_api import sync_playwright

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 用唯一时间戳文件名：固定名 _dashboard_screenshot.png 曾被外部进程(Defender/索引/
    # WPS 云同步/IDE 预览)持续锁住，导致 page.screenshot 写盘 Errno 13 Permission denied，
    # 邮件因此无图。唯一名从根本上避开该锁。
    out = _PL_DATA_DIR / f"{_PL_SCREENSHOT_PREFIX}_{ts}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # 清理历史截图，避免无限堆积；被外部进程锁住的旧固定文件(_dashboard_screenshot.png)
    # 可能删不掉，忽略即可，不影响新文件写入。
    try:
        for _old in _PL_DATA_DIR.glob(f"{_PL_SCREENSHOT_PREFIX}*.png"):
            if _old != out and _old.name != "_dashboard_screenshot.png":
                try:
                    _old.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    url = _PL_DASHBOARD_URL

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 初始给一个偏高的视口，让页面能完整布局
        page = browser.new_page(viewport={"width": 1920, "height": 1600})

        # 1) 进入页面后强制英文，再 reload 让 React 读取 localStorage
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("localStorage.setItem('app-locale', 'en');")
        page.reload(wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        current_locale = page.evaluate("localStorage.getItem('app-locale')")
        logging.getLogger(__name__).info("[PL-SHOT] locale=%s", current_locale)

        # 2) 等数据真正加载（spinner 消失 + 关键指标出现）
        try:
            page.wait_for_selector("text=加载中...", state="hidden", timeout=15000)
        except Exception:
            pass
        # 硬性渲染校验：看板必须出现关键指标文本，否则视为未渲染（白屏/数据缺失）
        rendered = False
        for kw in ("Total Sites", "Affected Sites", "Critical", "Major"):
            try:
                el = page.get_by_text(kw, exact=False).first
                el.wait_for(state="visible", timeout=8000)
                rendered = True
                break
            except Exception:
                continue
        if not rendered:
            # 失败时不覆盖正式截图文件，避免留下错误的 Task Manager 首页截图
            fail_out = out.with_stem(out.stem + "_failed")
            page.screenshot(path=str(fail_out), full_page=False)
            browser.close()
            raise RuntimeError(
                "看板未渲染：关键指标文本（Total Sites/Affected Sites/Critical/Major）均未出现，"
                "可能后端/API 未就绪或前端加载失败"
            )
        # 额外确认 Leaflet 地图瓦片已绘制（避免地图区域空白）
        try:
            page.wait_for_function(
                "() => { const lf = document.querySelector('.leaflet-container');"
                " if (!lf) return false;"
                " const imgs = lf.querySelectorAll('img.leaflet-tile');"
                " return imgs.length > 0 && lf.getBoundingClientRect().height > 200; }",
                timeout=15000,
            )
        except Exception:
            logging.getLogger(__name__).warning("[PL-SHOT] 地图瓦片未检出，仍继续截图")
        page.wait_for_timeout(3000)  # 图表/地图缓冲

        # 4) 隐藏左侧栏（antd Sider），并让右侧地图列拉伸、地图 flex-grow 铺满整列
        #    （地图原 style=calc(100vh-180px) 只认视口高度，截图视口≠页面高会导致地图
        #     停在半空；用 !important flex-grow 覆盖内联高度，使其填满与左栏等高的列）
        page.add_style_tag(content="""
            .ant-layout-sider { display: none !important; }
            div[style*="33.333%"] {
                align-self: stretch !important;
                height: auto !important;
                position: relative !important;
                display: flex !important;
                flex-direction: column !important;
            }
            div[style*="33.333%"] > .ant-card {
                flex: 1 1 auto !important; display: flex !important; flex-direction: column !important;
            }
            div[style*="33.333%"] > .ant-card > .ant-card-body {
                flex: 1 1 auto !important; display: flex !important; flex-direction: column !important;
            }
            .leaflet-container {
                flex: 1 1 auto !important; height: auto !important; min-height: 420px !important;
            }
        """)
        page.wait_for_timeout(500)

        # 5) 量出真实内容高度，把视口高度设成该值，并 dispatch resize 让 Leaflet 重算铺满
        content_h = page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        target_h = min(max(content_h, 800), 4000)  # 安全范围
        page.set_viewport_size({"width": 1920, "height": target_h})
        page.evaluate("window.dispatchEvent(new Event('resize'));")
        page.wait_for_timeout(1500)  # 等 Leaflet invalidateSize + 重绘
        # 验证地图是否铺满：leaflet 容器高度应接近内容列高
        lf_h = page.evaluate("""() => {
            const lf = document.querySelector('.leaflet-container');
            if (!lf) return null;
            const r = lf.getBoundingClientRect();
            return { h: Math.round(r.height), bottom: Math.round(r.bottom), top: Math.round(r.top) };
        }""")
        logging.getLogger(__name__).info("[PL-SHOT] content_h=%s target_h=%s leaflet=%s", content_h, target_h, lf_h)

        page.screenshot(path=str(out), full_page=False)
        browser.close()

    # 像素级校验：纯白/近白页面视为渲染失败，抛错以便上层跳过该图（避免白图入邮件）。
    # 取代原先的 `st_size > 10000` 字节断言——空白 PNG 也能轻松超过 10KB，导致白图被发出。
    _assert_not_blank(out)
    return out


def _assert_not_blank(out: Path) -> None:
    """截图若基本全白（白屏），抛错，让 run_packet_loss_email 跳过该图而非发出白图。

    - 先做一个最小文件体积兜底（避免附带 0 字节/损坏文件）；
    - 再按像素判定：三通道最值都接近纯白，或近白像素占比 > 98% 即判为白屏。
    - 无 PIL 时仅告警并放行，退回元素级渲染校验。
    """
    out = Path(out)
    if not out.exists():
        raise RuntimeError(f"截图文件缺失，已跳过：{out}")
    if out.stat().st_size < 2000:
        raise RuntimeError(f"截图文件异常小（{out.stat().st_size}B），已跳过：{out}")
    try:
        from PIL import Image
    except Exception:
        logging.getLogger(__name__).warning("[PL-SHOT] PIL 不可用，跳过像素级白屏校验")
        return
    try:
        im = Image.open(out).convert("RGB")
        extrema = im.getextrema()  # ((rmin,rmax),(gmin,gmax),(bmin,bmax))
        if all(mn >= 250 and mx <= 255 for (mn, mx) in extrema):
            raise RuntimeError(f"截图疑似白屏（像素全白），已跳过：{out}")
        px = list(im.getdata())
        white = sum(1 for r, g, b in px if r > 248 and g > 248 and b > 248)
        ratio = white / len(px) if px else 1.0
        if ratio > 0.98:
            raise RuntimeError(f"截图近白（{ratio*100:.0f}% 白像素），已跳过：{out}")
    except RuntimeError:
        raise
    except Exception as e:
        logging.getLogger(__name__).warning("[PL-SHOT] 像素校验异常: %s", e)


def find_latest_excel(directory: Path, name_filter: str) -> Optional[Path]:
    """Return the most recently modified xlsx file matching *name_filter* in *directory*."""
    import glob
    pattern = str(directory / f"{name_filter}*.xlsx")
    candidates = sorted(glob.glob(pattern), key=lambda f: Path(f).stat().st_mtime, reverse=True)
    return Path(candidates[0]) if candidates else None


def run_packet_loss_email(to: str = None, cc: str = None) -> dict:
    """Packet Loss 丢包看板日报邮件（本地数据 + 本地截图 + 远程收件人名单）。

    附件：最新生成的 Packet_Loss_Status_Output Automation *.xlsx。
    内嵌图片：丢包看板网页全屏截图（Playwright headless）。
    收件人/抄送：远程 ``_PL_EMAIL`` 的 ss_email.txt / cc_email.txt；
               显式传 ``to`` / ``cc`` 时覆盖（用于测试）。
    """
    import backend.services.remote_ftp as rf

    # ---- 1. 截图 ----
    try:
        screenshot = _capture_packet_loss_screenshot()
        logging.getLogger(__name__).info("[PL-EMAIL] 截图完成: %s (%d bytes)", str(screenshot), screenshot.stat().st_size)
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] PL screenshot failed: %s", e)
        screenshot = None

    # ---- 2. 收件人 ----
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("packet_loss_email", to, cc)

    # ---- 3. 最新报告 ----
    excel = find_latest_excel(_PL_DATA_DIR, name_filter="Packet_Loss_Status_Output Automation")
    if not excel:
        return {"success": False, "error": f"未在 {_PL_DATA_DIR} 找到 Packet_Loss_Status_Output Automation 报告"}

    # ---- 4. 发送 ----
    cmd_parts = {
        "data_dir": str(_PL_DATA_DIR),
        "name_filter": "Packet_Loss_Status_Output Automation",
        "excel": str(excel),
        "to": to_arg,
        "cc": cc_arg,
    }
    if screenshot:
        cmd_parts["images"] = [str(screenshot)]

    result = _run_script(
        data_dir=_PL_DATA_DIR,
        name_filter="Packet_Loss_Status_Output Automation",
        excel=excel,
        images=[screenshot] if screenshot else None,
        to=to_arg,
        cc=cc_arg,
    )
    return result


# =============================================================================
# 客户业务 KPI + OSG 周报邮件（任务 ume_in_osg_report）
# =============================================================================
def _latest_osg_report() -> Optional[Path]:
    """data/in_data 下最新一份带窗口日期的 OSG 周报（忽略模板本体与 Excel 临时文件）。"""
    try:
        cands = [p for p in _UME_IN_OSG_DATA.glob(f"{_UME_IN_OSG_NAME_PREFIX}_*.xlsx")
                 if _UME_IN_OSG_WINDOW_RE.match(p.stem) and not p.name.startswith("~$")]
    except OSError:
        return None
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def run_ume_in_osg_report_email(report_path=None, to: str = None, cc: str = None) -> dict:
    """发送客户业务 KPI + OSG 周报（附件 = t_osg_build 生成的 Excel）。

    收件人：主送 djoumene.reussite1@zte.com.cn，抄送 dong.xinmin@zte.com.cn
    （可在 Settings → Email Recipient Settings 的 ``ume_in_osg_report`` 组覆盖）。

    Args:
        report_path: 指定附件；省略时取 data/in_data 下最新一份带窗口日期的 OSG 周报。
        to / cc: 显式覆盖收件人（测试用）。
    """
    from backend.services.email_recipient_store import get_email_recipients

    to_arg, cc_arg = get_email_recipients("ume_in_osg_report", to, cc)
    if not to_arg:
        return {"success": False,
                "error": "主送收件人为空，请在 Settings → Email Recipient Settings 配置 ume_in_osg_report"}

    report = Path(report_path) if report_path else _latest_osg_report()
    if report is None or not Path(report).is_file():
        return {"success": False,
                "error": f"未找到 OSG 周报 Excel（目录 {_UME_IN_OSG_DATA}）"}
    report = Path(report)

    # 主题带报告窗口（文件名形如 OSG Weekly QoS Analysis Report_2026-09-08_2026-09-14.xlsx）
    m = _UME_IN_OSG_WINDOW_RE.match(report.stem)
    subject = (f"{_UME_IN_OSG_NAME_PREFIX} {m.group(1)} ~ {m.group(2)}" if m
               else f"{_UME_IN_OSG_NAME_PREFIX} {time.strftime('%Y-%m-%d %H:%M:%S')}")

    return _run_script(
        data_dir=_UME_IN_OSG_DATA,
        name_filter="",          # 不按名称自动发现 Excel，附件由 --attach 显式指定
        to=to_arg,
        cc=cc_arg,
        no_excel=True,
        attach=[str(report)],
        subject=subject,
    )
