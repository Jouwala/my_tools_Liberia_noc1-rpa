# -*- coding: utf-8 -*-
"""
owa_mail_report.py  (通用版)
===========================

通过 EWS (Exchange Web Services) 登录 Orange OWA 邮箱并发送**带内嵌图片 + Excel 附件**的邮件。

相比 owa_mail_1hour_TT_Report.py 的专用版，本脚本是**通用**的：
  - 通过 --data-dir 指定报告数据目录（Excel + 图片所在处）
  - 通过 --email-dir 指定收件人名单目录（内含 ss_email.txt / cc_email.txt）
  - 通过 --name-filter 同时筛选「Excel 文件名」与「内嵌图片文件名」（按子串匹配）
  - 通过 --no-excel 关闭 Excel 附件（如仅有图片的可用性报告），此时主题可用
    --subject-prefix + 发送时间戳（如 "MS Network Availability Daily Report_2026-07-31 08:20:27"）

收件人/抄送名单始终来自 <email-dir>/ss_email.txt 与 <email-dir>/cc_email.txt
（仅当显式传 --to / --cc 时覆盖，用于测试）。

设计要点
--------
1. 使用 exchangelib 走 EWS（/EWS/Exchange.asmx），比浏览器自动化稳定高效。
2. 服务器证书链在 Windows Python 下无法本地验证，用 NoVerifyHTTPAdapter 关闭证书链校验（仍走 HTTPS）。
3. 认证 NTLM，用户名用裸账号名 ZTENOC_OLR。
4. 配置通过环境变量覆盖，便于调度。
5. 内嵌图片以 cid: 方式嵌入 HTML 正文，并在每张图片上方用文件名（不含扩展名）作为注释。
6. 输出强制 UTF-8，打印总耗时。

CLI 用法
--------
    # MS Contract KPIs 日报（自动在 data-dir 找含该子串的最新 xlsx，并内嵌同名图片）
    python owa_mail_report.py \
        --data-dir "D:/01_RPA/Task/my_app/data/ms_sla" \
        --email-dir "D:/01_RPA/LBR_Tools/KPI/MS_SLA/email" \
        --name-filter "MS Contract KPIs Achievements Daily Report"

    # 可用性报告（无 Excel，主题 = 前缀 + 发送时间）
    python owa_mail_report.py \
        --data-dir "D:/01_RPA/LBR_Tools/KPI/RAN/ORANGE" \
        --email-dir "D:/01_RPA/LBR_Tools/KPI/RAN/ORANGE/email" \
        --name-filter "Availability" --no-excel \
        --subject-prefix "MS Network Availability Daily Report"
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def _read_text_retry(path: Path, max_attempts: int = 5) -> str:
    """读取 UTF-8 文本，遇 Windows 文件锁（Defender/索引/WPS 云同步，见 fix_file_lock.ps1）
    导致的 PermissionError 时按 0.4/0.8/1.2/1.6s 退避重试，吸收瞬时外锁。"""
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return Path(path).read_text(encoding="utf-8")
        except PermissionError as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(0.4 * attempt)
                continue
    raise last_err  # type: ignore[misc]


# ---- 强制 stdout/stderr 使用 UTF-8（兼容 IDLE/PyCharm 等无 reconfigure/buffer 的环境）----
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

# ---- 抑制 urllib3 InsecureRequestWarning（仅当关闭 SSL 校验时）----
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from exchangelib import (  # noqa: E402
    BASIC,
    NTLM,
    Account,
    Configuration,
    Credentials,
    DELEGATE,
    FaultTolerance,
    FileAttachment,
    HTMLBody,
    Mailbox,
    Message,
    Version,
)
from exchangelib.protocol import NoVerifyHTTPAdapter, Protocol  # noqa: E402
from exchangelib.version import EXCHANGE_2016  # noqa: E402

# EWS 服务器已探测为 Microsoft Exchange Server 2016（build 15.1.2507.61）。
# 显式锁定版本，跳过 exchangelib 的 Version.guess() 握手——该握手偶发被远端
# 10054 强制断开，是 kpi_ms_wo_sla / kpi_sp_consumables 等邮件任务瞬断失败的根因。
EWS_VERSION = Version(build=EXCHANGE_2016, api_version="Exchange2016")

# =====================================================================
# 配置（环境变量优先，便于集成调度）
# =====================================================================
OWA_SERVER = os.getenv("OWA_SERVER", "exchmail.orange-cit.ci")
OWA_USERNAME = os.getenv("OWA_USERNAME", "ZTENOC_OLR")
OWA_PASSWORD = os.getenv("OWA_PASSWORD", "Postcode@202608")
OWA_SMTP = os.getenv("OWA_SMTP", "ztenoc.olr@orange.com")
OWA_AUTH_TYPE = os.getenv("OWA_AUTH_TYPE", "NTLM").upper()
OWA_VERIFY_SSL = os.getenv("OWA_VERIFY_SSL", "false").lower() in ("1", "true", "yes", "on")
OWA_MAX_CONNECTIONS = max(1, int(os.getenv("OWA_MAX_CONNECTIONS", "2")))
OWA_RETRY_MAX_WAIT = max(1, int(os.getenv("OWA_RETRY_MAX_WAIT", "60")))
# EWS SOAP 单次请求超时（秒）。Orange EWS 服务端响应偏慢但功能正常，
# 实测 SendItem 响应常 >120s，60s 远不够。设为 300s 给慢服务器充足余量。
# 仍可用环境变量 OWA_SOAP_TIMEOUT 覆盖。
OWA_SOAP_TIMEOUT = max(10, int(os.getenv("OWA_SOAP_TIMEOUT", "300")))

# Protocol 是缓存工厂，不能直接 Protocol(timeout=N) 构造（会 KeyError: 'config'），
# 只能改类属性。
# 注意：必须在 OWA_SOAP_TIMEOUT 定义之后执行，否则模块导入即 NameError。
Protocol.TIMEOUT = OWA_SOAP_TIMEOUT

_AUTH_MAP = {"NTLM": NTLM, "BASIC": BASIC}
if OWA_AUTH_TYPE not in _AUTH_MAP:
    raise SystemExit(f"不支持的 OWA_AUTH_TYPE={OWA_AUTH_TYPE!r}，可选: {list(_AUTH_MAP)}")

# 关闭证书链校验（Windows certifi 缺少中间证书，链校验会失败）
if not OWA_VERIFY_SSL:
    Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter


# =====================================================================
# 目录与默认
# =====================================================================
_SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = _SCRIPT_DIR / "data"

# HTML 正文中内嵌图片的插入占位符（找不到则追加到末尾）
_INLINE_PLACEHOLDER = "<!-- inline images inserted here -->"


# =====================================================================
# 工具函数
# =====================================================================
def safe_write_path(path: str | Path) -> Path:
    """若目标文件已存在/被占用，返回带 `_序号` 的新路径。"""
    p = Path(path).resolve()
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    idx = 1
    while True:
        candidate = p.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def find_latest_excel(dir_path: Path, name_filter: Optional[str] = None) -> Optional[Path]:
    """在目录中查找最新的 Excel 文件（可按文件名子串筛选）。"""
    if not dir_path.is_dir():
        return None
    candidates: List[Path] = []
    for f in dir_path.glob("*.xlsx"):
        if f.name.startswith("~$"):
            continue
        if name_filter and name_filter not in f.name:
            continue
        candidates.append(f)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _image_base_key(name: str) -> str:
    """同一图表可能因下载撞锁同时存在「固定名」与「时间戳_随机名」多份，
    归并到同一 key，供 find_images 去重（只取最新一份）。"""
    import re
    # 先去掉扩展名再匹配，避免 _<hex> 后面跟 .png 导致正则不命中
    stem = re.sub(r"\.(png|jpe?g)$", "", name, flags=re.IGNORECASE)
    key = re.sub(r"_\d{8}_\d{6}(_[0-9a-fA-F]{4,12})?$", "", stem)
    key = re.sub(r"_[0-9a-fA-F]{6,12}$", "", key)
    return key


def find_images(dir_path: Path, name_filter: Optional[str] = None) -> List[Path]:
    """在目录中查找图片（png/jpg/jpeg），可按文件名子串筛选。

    去重：同一图表（如 Availability-COOL）可能同时存在固定名与若干时间戳/随机名
    副本（下载撞锁走 fallback 时），只保留每个图表最新的一份，避免邮件重复内嵌。
    """
    if not dir_path.is_dir():
        return []
    found: List[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for f in dir_path.glob(ext):
            if f.name.startswith("~$") or f.name.startswith("."):
                continue
            if name_filter and name_filter not in f.name:
                continue
            found.append(f)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    seen: set = set()
    deduped: List[Path] = []
    for f in found:
        key = _image_base_key(f.name)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def _make_cid(path: Path) -> str:
    """为内嵌图片生成唯一 content_id（仅含安全字符）。"""
    safe = re.sub(r"\W+", "", path.stem) or "img"
    return f"{safe}_{uuid.uuid4().hex}"


def _wrap_plain_to_html(body: str) -> str:
    """把纯文本正文转成最简单 HTML（保留换行）。"""
    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = escaped.split("\n")
    return "<p>" + "</p><p>".join(lines) + "</p>"


# =====================================================================
# 核心：登录 + 发送邮件
# =====================================================================
def get_account(
    server: str = OWA_SERVER,
    username: str = OWA_USERNAME,
    password: str = OWA_PASSWORD,
    smtp: str = OWA_SMTP,
    auth_type: str = OWA_AUTH_TYPE,
) -> Account:
    """登录 OWA 并返回 exchangelib Account 对象。"""
    # 凭据优先级：环境变量(OWA_USERNAME/OWA_PASSWORD) > 数据库(设置页) > 代码默认值
    # 这样在「设置」页改完 OWA 邮箱密码后，无需改代码、无需重启即可生效。
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        import sys as _sys
        _myapp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _myapp not in _sys.path:
            _sys.path.insert(0, _myapp)
        from backend.services.credential_store import get_credential
    _owa_user, _owa_pass = get_credential(
        "owa_mail", OWA_USERNAME, OWA_PASSWORD,
        env_user="OWA_USERNAME", env_secret="OWA_PASSWORD",
    )
    if username == OWA_USERNAME and _owa_user:
        username = _owa_user
    if password == OWA_PASSWORD and _owa_pass:
        password = _owa_pass
    auth_type = auth_type.upper()
    if auth_type not in _AUTH_MAP:
        raise ValueError(f"Unsupported auth type: {auth_type!r}")
    creds = Credentials(username=username, password=password)
    config = Configuration(
        server=server,
        credentials=creds,
        auth_type=_AUTH_MAP[auth_type],
        version=EWS_VERSION,
        max_connections=OWA_MAX_CONNECTIONS,
        retry_policy=FaultTolerance(max_wait=OWA_RETRY_MAX_WAIT),
    )
    account = Account(
        primary_smtp_address=smtp,
        config=config,
        access_type=DELEGATE,
        autodiscover=False,
    )
    return account


def send_mail(
    account: Account,
    to: str | List[str],
    subject: str,
    body: str,
    cc: Optional[str | List[str]] = None,
    attachments: Optional[Iterable[str | Path]] = None,
    inline_images: Optional[Iterable[str | Path]] = None,
    html: bool = False,
    save_to_sent: bool = True,
) -> Message:
    """发送一封邮件（支持内嵌图片 + 普通附件）。"""

    def _to_mailboxes(v) -> List[Mailbox]:
        if v is None:
            return []
        if isinstance(v, str):
            values = _split_addresses(v)
        else:
            values = [str(x).strip() for x in v if x and str(x).strip()]
        return [Mailbox(email_address=value) for value in values]

    to_recipients = _to_mailboxes(to)
    if not to_recipients:
        raise ValueError("At least one recipient is required")

    is_html = html
    content = body
    inline_specs: List[Tuple[Path, str]] = []  # (path, cid)

    if inline_images:
        if not is_html:
            content = _wrap_plain_to_html(body)
            is_html = True
        image_blocks: List[str] = []
        for fp in inline_images:
            p = Path(fp)
            if not p.is_file():
                print(f"[WARN] 内嵌图片不存在，跳过: {p}")
                continue
            cid = _make_cid(p)
            inline_specs.append((p, cid))
            # 用图片文件名（不含扩展名）作为上方注释说明
            caption = p.stem
            image_blocks.append(
                f'<div style="margin:12px 0;">'
                f'<p style="margin:0 0 4px 0;font-weight:bold;">{caption}</p>'
                f'<img src="cid:{cid}" alt="{p.name}" '
                f'style="max-width:100%;border:1px solid #ddd;border-radius:6px;">'
                f'</div>'
            )

        all_images_html = "".join(image_blocks)
        if _INLINE_PLACEHOLDER in content:
            content = content.replace(_INLINE_PLACEHOLDER, all_images_html, 1)
        else:
            content += all_images_html

    msg = Message(
        account=account,
        subject=subject,
        body=HTMLBody(content) if is_html else body,
        to_recipients=to_recipients,
        cc_recipients=_to_mailboxes(cc),
    )

    if attachments:
        for fp in attachments:
            p = Path(fp)
            if not p.is_file():
                raise FileNotFoundError(f"附件不存在: {p}")
            with p.open("rb") as f:
                msg.attach(FileAttachment(name=p.name, content=f.read()))

    for p, cid in inline_specs:
        with p.open("rb") as f:
            msg.attach(
                FileAttachment(
                    name=p.name,
                    content=f.read(),
                    content_id=cid,
                    is_inline=True,
                )
            )

    if save_to_sent:
        msg.send_and_save()
    else:
        msg.send()
    return msg


# =====================================================================
# CLI
# =====================================================================
def _split_addresses(s: str) -> List[str]:
    """支持逗号/分号分隔的多个邮箱。"""
    return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]


def _read_addresses_from_file(path: Path) -> List[str]:
    """从名单文件读取邮箱地址（支持逗号/分号/换行分隔，去重且忽略空行与 # 注释行）。"""
    if not path.is_file():
        return []
    addrs: List[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in re.split(r"[;,\s]+", line):
            a = raw.strip()
            if a and a not in addrs:
                addrs.append(a)
    return addrs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="通过 EWS 登录 Orange OWA 发送带内嵌图片 + Excel 附件的邮件（通用版）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "环境变量 OWA_SERVER/OWA_USERNAME/OWA_PASSWORD/OWA_SMTP/OWA_AUTH_TYPE/"
            "OWA_VERIFY_SSL 可覆盖默认配置。"
        ),
    )
    parser.add_argument("--to", help="收件人邮箱（多个用逗号或分号分隔）；省略时从 ss_email.txt 读取")
    parser.add_argument("--cc", help="抄送邮箱（多个用逗号或分号分隔）；省略时从 cc_email.txt 读取；传空串表示不抄送")
    parser.add_argument("--subject", help="邮件主题（默认：有 Excel 取 Excel 文件名；无 Excel 取 --subject-prefix + 时间戳）")
    parser.add_argument("--body", help="邮件正文（纯文本或 HTML）")
    parser.add_argument("--body-file", help="从文件读取正文（UTF-8）")
    parser.add_argument("--html", action="store_true", help="正文按 HTML 处理")
    parser.add_argument("--attach", action="append", default=[], help="额外附件路径，可多次指定")
    parser.add_argument("--self-test", action="store_true", help="自测：发一封邮件给自己")

    # ---- 数据 / 名单 / 筛选 ----
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="报告数据目录（Excel + 图片所在处）")
    parser.add_argument("--email-dir", default=str(_SCRIPT_DIR),
                        help="收件人名单目录（内含 ss_email.txt / cc_email.txt）")
    parser.add_argument("--excel", help="指定 Excel 附件路径（默认自动发现）")
    parser.add_argument("--name-filter", default=None,
                        help="文件名包含的子串，用于同时筛选 Excel 与内嵌图片（如 'MS Contract KPIs Achievements Daily Report'）")
    parser.add_argument("--excel-name", dest="name_filter", help="--name-filter 的别名")
    parser.add_argument("--images", action="append", default=None,
                        help="指定内嵌图片路径，可多次指定或用逗号分隔多个；默认按 --name-filter 或目录内所有图片")
    parser.add_argument("--no-excel", action="store_true", help="不附加 Excel（如仅图片的可用性报告）")
    parser.add_argument("--subject-prefix", default="",
                        help="--no-excel 时主题的固定前缀（会与发送时间戳拼接）")
    parser.add_argument("--no-inline", action="store_true", help="不使用内嵌图片（图片作为普通附件）")
    parser.add_argument("--no-save-sent", action="store_true", help="不保存到已发送文件夹")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    data_dir = Path(args.data_dir).resolve()
    email_dir = Path(args.email_dir).resolve()
    ss_file = email_dir / "ss_email.txt"
    cc_file = email_dir / "cc_email.txt"

    # 自测模式
    if args.self_test:
        print(f"[INFO] 自测模式：发邮件给自己 ({OWA_SMTP})")
        to = OWA_SMTP
        subject = "[OWA Self-Test] EWS 登录与发送测试"
        body = (
            "你好，\n\n"
            "这是一封通过 EWS (exchangelib) 自动发送的测试邮件。\n"
            "UTF-8 编码测试：中文 ✓ Emoji ✓ 数字 12345\n\n"
            "请忽略此邮件。"
        )
        cc = None
        attachments = None
        inline_images = None
        use_html = False
    else:
        # 主送：优先 --to，否则从 ss_email.txt 读取
        if args.to:
            to = _split_addresses(args.to)
        else:
            to = _read_addresses_from_file(ss_file)
            if not to:
                raise SystemExit(f"[ERROR] 未提供 --to 且在 {ss_file} 未找到任何收件人")
        # 抄送：优先 --cc（显式传空串 "" 表示不抄送），否则从 cc_email.txt 读取
        if args.cc is not None:
            cc = _split_addresses(args.cc)
        else:
            cc = _read_addresses_from_file(cc_file)
        print(f"[RECIPIENTS] 主送 {len(to)} 人（来源: {'--to' if args.to else str(ss_file)}），"
              f"抄送 {len(cc)} 人（来源: {'--cc' if args.cc is not None else str(cc_file)}）")

        # ---- 自动发现 Excel ----
        excel_path: Optional[Path] = None
        if not args.no_excel:
            if args.excel:
                excel_path = Path(args.excel)
                if not excel_path.is_file():
                    parser.error(f"--excel 指定的文件不存在: {excel_path}")
            else:
                excel_path = find_latest_excel(data_dir, name_filter=args.name_filter)
                if not excel_path:
                    raise SystemExit(
                        f"[ERROR] 未在 {data_dir} 找到"
                        + (f" 名称包含 {args.name_filter!r} 的" if args.name_filter else "")
                        + " Excel 文件"
                    )
            print(f"[DISCOVER] 选用 Excel: {excel_path}")

        # ---- 自动发现图片 ----
        image_paths: List[Path] = []
        if args.images:
            # --images 可多次指定（action=append），每次的值还可能是逗号分隔的多个路径
            _flat: List[Path] = []
            for chunk in args.images:
                for part in chunk.split(","):
                    p = Path(part.strip())
                    if p.is_file():
                        _flat.append(p)
                    else:
                        print(f"[WARN] 图片不存在，跳过: {p}")
            image_paths = _flat
        elif args.name_filter:
            image_paths = find_images(data_dir, name_filter=args.name_filter)
        else:
            image_paths = find_images(data_dir)
        print(f"[DISCOVER] 内嵌图片({len(image_paths)}): "
              + (", ".join(p.name for p in image_paths) if image_paths else "无"))

        # 普通附件：Excel + 额外附件
        attachments = ([excel_path] if excel_path else []) + [Path(x) for x in args.attach]

        # 内嵌图片（--no-inline 时改为普通附件）
        if args.no_inline:
            attachments += image_paths
            inline_images = None
            use_html = args.html
        else:
            inline_images = image_paths
            use_html = True

        # 主题
        if args.subject:
            subject = args.subject
        elif args.no_excel:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            subject = f"{args.subject_prefix}_{stamp}" if args.subject_prefix else stamp
        else:
            subject = excel_path.stem  # type: ignore[union-attr]

        # 正文：用户自定义优先；否则用默认 HTML 模板（含占位符）
        if args.body_file:
            body = _read_text_retry(Path(args.body_file))
        elif args.body is not None:
            body = args.body
        else:
            report_label = excel_path.name if excel_path else subject
            body = (
                "<h3>Dear Team,</h3>"
                "<p>Please find the report attached.</p>"
                "<p>Details are shown below:</p>"
                f"<p><em>Report: {report_label}</em></p>"
                f"{_INLINE_PLACEHOLDER}"
                "<br><p>Best regards,<br>ZTENOC OLR</p>"
            )

    # ---- 通过 PowerShell .NET HttpWebRequest + NTLM 发送 ----
    # 替代 exchangelib send_mail()，解决 Python requests_ntlm 在 Orange Exchange
    # 服务器上 NTLM 握手挂起/被拒的问题。.NET 使用 Windows SSPI（与浏览器同套）。
    from dotnet_ews_send import send_mail_dotnet

    print(f"[SEND] 通过 .NET HttpWebRequest + NTLM 发送到 {OWA_SERVER}...")
    print(f"       To : {to}")
    if cc:
        print(f"       Cc : {cc}")
    print(f"       Sub: {subject}")
    if attachments:
        print(f"       Att: {[str(p) for p in attachments]}")
    if inline_images:
        print(f"       Img: {[p.name for p in inline_images]} (inline)")

    try:
        result = send_mail_dotnet(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            attachments=attachments,
            inline_images=inline_images,
            html=use_html,
            save_to_sent=not args.no_save_sent,
        )
    except Exception as e:
        print(f"[SEND][FAIL] {type(e).__name__}: {e}")
        return 3

    if not result.get("success"):
        print(f"[SEND][FAIL] {result.get('error', 'Unknown error')}")
        return 3

    suffix = "并保存到已发送文件夹" if not args.no_save_sent else "（未保存）"
    print(f"[SEND][OK] 邮件已发送{suffix}。")
    elapsed = time.perf_counter() - t0
    print(f"[DONE] 总耗时: {elapsed:.2f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
