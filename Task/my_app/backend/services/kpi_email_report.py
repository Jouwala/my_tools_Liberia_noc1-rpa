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
    if images:
        # 显式指定内嵌图片，避免目录残留旧 PNG 被一并发现导致重复内嵌
        for img in images:
            cmd += ["--images", str(img)]
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
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _attempt_all: exception swallowed", exc_info=True)
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
_PL_SCREENSHOT_NAME = "_dashboard_screenshot.png"


def _capture_packet_loss_screenshot() -> Path:
    """用 Playwright 截取丢包看板页面截图（英文界面 + 已加载 + 无左侧栏 + 地图铺满）。

    关键：Leaflet 地图不会随 full_page 的视口拉伸自动重算尺寸，导致地图停留在
    初始高度、其余内容却撑开，截图里地图"没到底"。解决方案：不用 full_page，
    而是把视口高度设成页面真实高度（让地图按满高初始化），并 dispatch resize
    事件触发 Leaflet invalidateSize()，最后按视口截图。
    """
    from playwright.sync_api import sync_playwright

    out = _PL_DATA_DIR / _PL_SCREENSHOT_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    url = "http://localhost:7038/myapp/"

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

        # 2) 点击「Packet Loss」菜单（英文优先）
        for label in ("Packet Loss", "丢包看板", "PacketLoss"):
            try:
                loc = page.get_by_text(label, exact=False).first
                if loc.count() > 0:
                    loc.click(timeout=5000)
                    break
            except Exception:
                continue

        # 3) 等数据真正加载（spinner 消失 + 关键指标出现）
        try:
            page.wait_for_selector("text=加载中...", state="hidden", timeout=15000)
        except Exception:
            pass
        # 硬性渲染校验：看板必须出现关键指标文本，否则视为未渲染（白屏/数据缺失）
        rendered = False
        for kw in ("Total Sites", "Affected Sites", "Critical", "667"):
            try:
                el = page.get_by_text(kw, exact=False).first
                el.wait_for(state="visible", timeout=8000)
                rendered = True
                break
            except Exception:
                continue
        if not rendered:
            page.screenshot(path=str(out), full_page=False)
            browser.close()
            raise RuntimeError(
                "看板未渲染：关键指标文本（Total Sites/Affected Sites/Critical/667）均未出现，"
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
