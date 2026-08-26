# -*- coding: utf-8 -*-
"""
owa_mail_service.py
===================

通过 EWS (Exchange Web Services) 登录 Orange OWA 邮箱并发送邮件。

目标服务器: https://exchmail.orange-cit.ci/owa/
账号示例   : ZTENOC_OLR / Postcode@202608
邮箱地址   : ztenoc.olr@orange.com

设计要点
--------
1. 使用 `exchangelib` 通过 EWS 协议（/EWS/Exchange.asmx）操作，比浏览器自动化稳定高效。
2. 服务器证书链在 Windows Python 下无法本地验证，使用 exchangelib 内置的
   `NoVerifyHTTPAdapter` 关闭证书链校验（仍然走 HTTPS 加密通道）。
3. 认证方式 NTLM，用户名使用裸账号名 `ZTENOC_OLR`（不要带域名前缀或 @orange.com）。
4. 配置通过环境变量覆盖，便于集成到调度脚本而无需修改代码。
5. 输出强制 UTF-8；统计并打印从开始到运行完成的耗时（秒）。
6. 目标文件被占用时，新文件名追加 `_序号` 后缀生成（通用工具函数）。

扩展能力（2026-07-31）
----------------------
7. 支持 **内嵌图片（inline image）**：把 PNG 以 `cid:` 方式嵌入 HTML 正文，类似截图直显。
8. 支持 **自动发现** 数据目录下「最新 Excel」与「3 张默认 PNG（Summary / Open Tickets /
   Prolong Tickets）」，无需调用方手动指定。

CLI 用法
--------
    # 自动取 data/ 下最新 Excel（主题=Excel文件名）并把 3 张 PNG 内嵌发送
    python owa_mail_service.py --to team@orange.com --cc manager@orange.com

    # 指定数据目录（覆盖默认 data/）
    python owa_mail_service.py --to a@b.com \
        --data-dir "D:/01_RPA/Task/my_app/data/eflow/tt_reports" \
        --excel-name "Liberia Orange Site Down hourly Report"

    # 自定义 Excel / 图片 / 主题
    python owa_mail_service.py --to a@b.com \
        --excel ./data/my_report.xlsx \
        --images "./img/a.png,./img/b.png" \
        --subject "自定义主题"

    # 纯附件（不走内嵌图片）
    python owa_mail_service.py --to a@b.com --no-inline

    # 自测（发给自己）
    python owa_mail_service.py --self-test

环境变量（均可选，均有默认值）
------------------------------
    OWA_SERVER          默认 exchmail.orange-cit.ci
    OWA_USERNAME        默认 ZTENOC_OLR
    OWA_PASSWORD        默认 Postcode@202608
    OWA_SMTP            默认 ztenoc.olr@orange.com
    OWA_AUTH_TYPE       默认 NTLM  (可选 BASIC)
    OWA_VERIFY_SSL      默认 false (证书链在 Windows 上校验失败，默认关闭)
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

_AUTH_MAP = {"NTLM": NTLM, "BASIC": BASIC}
if OWA_AUTH_TYPE not in _AUTH_MAP:
    raise SystemExit(f"不支持的 OWA_AUTH_TYPE={OWA_AUTH_TYPE!r}，可选: {list(_AUTH_MAP)}")

# 关闭证书链校验（Windows certifi 缺少中间证书，链校验会失败）
if not OWA_VERIFY_SSL:
    Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter


# =====================================================================
# 数据目录与默认图片
# =====================================================================
_SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = _SCRIPT_DIR / "data"
# 内嵌图片顺序固定：Summary → Open Tickets → Prolong Tickets（与截图展示顺序一致）
DEFAULT_IMAGE_NAMES = ["Summary.png", "Open Tickets.png", "Prolong Tickets.png"]

# 默认 Excel 报告名筛选（按文件名子串）
DEFAULT_EXCEL_NAME = "Liberia Orange Site Down 8 hours Report"

# 收件人/抄送默认从脚本同级的名单文件读取（一行/分号/逗号分隔多个地址）
SS_EMAIL_FILE = _SCRIPT_DIR / "ss_email.txt"
CC_EMAIL_FILE = _SCRIPT_DIR / "cc_email.txt"

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
    """在目录中查找最新的 Excel 文件。

    name_filter: 若提供，则只在文件名包含该子串的 xlsx 中筛选（用于区分
    同目录下多个不同报告，例如只取 "Liberia Orange Site Down hourly Report"）。
    """
    if not dir_path.is_dir():
        return None
    candidates: List[Path] = []
    for f in dir_path.glob("*.xlsx"):
        # Office creates temporary lock files while a workbook is open. They
        # are not valid attachments and can otherwise win the mtime sort.
        if f.name.startswith("~$"):
            continue
        if name_filter and name_filter not in f.name:
            continue
        candidates.append(f)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def find_default_images(dir_path: Path) -> List[Path]:
    """按 DEFAULT_IMAGE_NAMES 顺序查找目录中的 PNG，缺失的打印警告但继续。"""
    found: List[Path] = []
    for name in DEFAULT_IMAGE_NAMES:
        p = dir_path / name
        if p.is_file():
            found.append(p)
        else:
            print(f"[WARN] 未找到内嵌图片: {p}")
    return found


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
EWS_VERSION = Version(build=EXCHANGE_2016, api_version="Exchange2016")
# 缩短 EWS SOAP/连接超时（默认 120s → 60s）：Protocol 是缓存工厂，不能
# 直接 Protocol(timeout=60) 构造（会 KeyError: 'config'），只能改类属性。
Protocol.TIMEOUT = OWA_SOAP_TIMEOUT


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
        # Retries transient EWS throttling / server-busy failures only. Do not
        # add an application-level retry around send_mail(), which could send
        # the same email twice if the server accepted it before a timeout.
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
    """发送一封邮件。

    Parameters
    ----------
    account : exchangelib.Account
        已登录的账号。
    to : str | list[str]
        收件人邮箱（单个或多个）。
    subject : str
        主题。
    body : str
        正文（纯文本或 HTML）。
    cc : str | list[str], optional
        抄送。
    attachments : iterable of path, optional
        普通附件路径列表（Excel 等）。
    inline_images : iterable of path, optional
        内嵌图片路径列表（PNG），会以 cid: 方式嵌入 HTML 正文。
    html : bool
        正文是否为 HTML。默认 False（纯文本）。
    save_to_sent : bool
        是否保存到已发送文件夹。默认 True。
    """
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

    # ---- 组装 HTML 正文与内嵌图片 ----
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

    # ---- 普通附件 ----
    if attachments:
        for fp in attachments:
            p = Path(fp)
            if not p.is_file():
                raise FileNotFoundError(f"附件不存在: {p}")
            with p.open("rb") as f:
                msg.attach(FileAttachment(name=p.name, content=f.read()))

    # ---- 内嵌图片（作为 inline attachment 挂到邮件）----
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
    """从名单文件读取邮箱地址（支持逗号/分号/换行分隔，去重且忽略空行）。"""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    addrs: List[str] = []
    for raw in re.split(r"[;,\s]+", text):
        a = raw.strip()
        if a and a not in addrs:
            addrs.append(a)
    return addrs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="通过 EWS 登录 Orange OWA 邮箱并发送邮件（支持内嵌图片 + 自动发现最新报告）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "环境变量 OWA_SERVER/OWA_USERNAME/OWA_PASSWORD/OWA_SMTP/OWA_AUTH_TYPE/"
            "OWA_VERIFY_SSL 可覆盖默认配置。"
        ),
    )
    parser.add_argument("--to", help="收件人邮箱（多个用逗号或分号分隔）；省略时从 ss_email.txt 读取")
    parser.add_argument("--cc", help="抄送邮箱（多个用逗号或分号分隔）；省略时从 cc_email.txt 读取")
    parser.add_argument("--subject", default="(No Subject)", help="邮件主题（默认取 Excel 文件名）")
    parser.add_argument("--body", help="邮件正文（纯文本或 HTML）")
    parser.add_argument("--body-file", help="从文件读取正文（UTF-8）")
    parser.add_argument("--html", action="store_true", help="正文按 HTML 处理")
    parser.add_argument("--attach", action="append", default=[], help="额外附件路径，可多次指定")
    parser.add_argument("--self-test", action="store_true", help="自测：发一封邮件给自己")

    # ---- 自动发现 / 内嵌图片相关 ----
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="数据目录（默认脚本同级的 data/），用于自动发现 Excel 与图片")
    parser.add_argument("--excel", help="指定 Excel 附件路径（默认取 data-dir 下最新 xlsx）")
    parser.add_argument("--excel-name", default=DEFAULT_EXCEL_NAME,
                        help=f"Excel 文件名包含的子串，用于从多个报告中筛选（默认: '{DEFAULT_EXCEL_NAME}'）")
    parser.add_argument("--images", help="指定内嵌图片路径，逗号分隔；默认取 data-dir 下 Summary/Open Tickets/Prolong Tickets.png")
    parser.add_argument("--no-inline", action="store_true", help="不使用内嵌图片（图片作为普通附件）")
    parser.add_argument("--no-save-sent", action="store_true", help="不保存到已发送文件夹")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    data_dir = Path(args.data_dir).resolve()

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
            to = _read_addresses_from_file(SS_EMAIL_FILE)
            if not to:
                raise SystemExit(f"[ERROR] 未提供 --to 且在 {SS_EMAIL_FILE} 未找到任何收件人")
        # 抄送：优先 --cc（显式传空串 "" 表示不抄送），否则从 cc_email.txt 读取
        if args.cc is not None:
            cc = _split_addresses(args.cc)
        else:
            cc = _read_addresses_from_file(CC_EMAIL_FILE)
        print(f"[RECIPIENTS] 主送 {len(to)} 人（来源: {'--to' if args.to else 'ss_email.txt'}），"
              f"抄送 {len(cc)} 人（来源: {'--cc' if args.cc else 'cc_email.txt'}）")

        # ---- 自动发现 Excel ----
        excel_path: Optional[Path]
        if args.excel:
            excel_path = Path(args.excel)
            if not excel_path.is_file():
                parser.error(f"--excel 指定的文件不存在: {excel_path}")
        else:
            excel_path = find_latest_excel(data_dir, name_filter=args.excel_name)
            if not excel_path:
                raise SystemExit(
                    f"[ERROR] 未在 {data_dir} 找到"
                    + (f" 名称包含 {args.excel_name!r} 的" if args.excel_name else "")
                    + " Excel 文件"
                )
        print(f"[DISCOVER] 选用 Excel: {excel_path}")

        # ---- 自动发现图片 ----
        image_paths: List[Path] = []
        if args.images:
            image_paths = [Path(x.strip()) for x in args.images.split(",") if x.strip()]
        else:
            image_paths = find_default_images(data_dir)
        print(f"[DISCOVER] 内嵌图片({len(image_paths)}): "
              + ", ".join(p.name for p in image_paths) if image_paths else "[DISCOVER] 无内嵌图片")

        # 普通附件：Excel + 额外附件
        attachments = [excel_path] + [Path(x) for x in args.attach]

        # 内嵌图片（--no-inline 时改为普通附件）
        if args.no_inline:
            attachments += image_paths
            inline_images = None
            use_html = args.html
        else:
            inline_images = image_paths
            use_html = True

        # 主题默认 = Excel 文件名（不含扩展名）
        if args.subject == "(No Subject)":
            subject = excel_path.stem
        else:
            subject = args.subject

        # 正文：用户自定义优先；否则用默认 HTML 模板（含占位符）
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        elif args.body is not None:
            body = args.body
        else:
            body = (
                "<h3>Dear Team,</h3>"
                "<p>Please find the <strong>Liberia Orange Site Down 8 hours Report</strong> attached.</p>"
                "<p>Summary and open tickets details are shown below:</p>"
                f"<p><em>Report: {excel_path.name}</em></p>"
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
