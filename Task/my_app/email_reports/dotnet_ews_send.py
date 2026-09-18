# -*- coding: utf-8 -*-
"""通过 PowerShell .NET HttpWebRequest + NTLM 发送 EWS 邮件。

替代 exchangelib 的 send_mail()，解决 Python requests_ntlm 在 Orange Exchange
服务器上 NTLM 握手挂起/被拒的问题。.NET HttpWebRequest 使用 Windows SSPI
（与浏览器同一套认证栈），完美兼容 Exchange 2016 的 NTLM + EPA。

用法：
    from dotnet_ews_send import send_mail_dotnet
    send_mail_dotnet(
        to="a@b.com;c@d.com",
        subject="Test",
        body="<p>Hello</p>",
        attachments=["report.xlsx"],
        inline_images=["chart.png"],
    )
"""
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

log = logging.getLogger(__name__)


def resolve_owa_credentials() -> Tuple[str, str]:
    """解析当前生效的 OWA 凭据，返回 (username, password)。

    实现在 ``email_reports/owa_credentials.py``（全项目唯一一处凭据解析逻辑）；
    优先级：环境变量(OWA_USERNAME/OWA_PASSWORD) > 数据库(设置页) > 代码默认值。
    ``email_reports/ews_probe.py`` 会调用本函数做「各发送方凭据一致性」校验。
    """
    try:
        from email_reports.owa_credentials import resolve_owa_credentials as _resolve
    except ImportError:
        from owa_credentials import resolve_owa_credentials as _resolve
    return _resolve()

# DotNetEwsSender.ps1 路径（本文件同目录）
# 注意：固定使用原始三阶段版 DotNetEwsSender.ps1 ——
#   CreateItem(SaveOnly) -> CreateAttachment -> SendItem，
#   内嵌图片以 IsInline=true + ContentId 嵌入正文（即"之前的格式"）。
# 不要使用 DotNetEwsSender_Fixed.ps1 / DotNetEwsSender_Optimized.ps1：
#   这两个实验版用单请求 CreateItem 直接内嵌 FileAttachment，EWS 会报
#   "Set action is invalid for property"，且优化版完全未处理附件/内嵌图片。
_default_script = Path(__file__).resolve().parent / "DotNetEwsSender.ps1"
_PS_SCRIPT = _default_script

# 内嵌图片占位符（与各邮件脚本保持一致）
_INLINE_PLACEHOLDER = "<!-- inline images inserted here -->"


def _make_cid(path: Path) -> str:
    """为内嵌图片生成唯一 content_id。"""
    safe = re.sub(r"\W+", "", path.stem) or "img"
    return f"{safe}_{uuid.uuid4().hex}"


def _wrap_plain_to_html(body: str) -> str:
    """纯文本 → HTML。"""
    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = escaped.split("\n")
    return "<p>" + "</p><p>".join(lines) + "</p>"


def _split_addresses(s: str) -> List[str]:
    return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]


def _format_addresses(addrs) -> str:
    """将地址列表/字符串转为分号分隔的字符串。"""
    if addrs is None:
        return ""
    if isinstance(addrs, str):
        return ";".join(_split_addresses(addrs))
    return ";".join(str(x).strip() for x in addrs if x and str(x).strip())


def send_mail_dotnet(
    to: Union[str, List[str]],
    subject: str,
    body: str,
    cc: Optional[Union[str, List[str]]] = None,
    attachments: Optional[Iterable[Union[str, Path]]] = None,
    inline_images: Optional[Iterable[Union[str, Path]]] = None,
    html: bool = False,
    save_to_sent: bool = True,
    server: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    smtp: Optional[str] = None,
    timeout: int = 300,
) -> dict:
    """通过 PowerShell .NET HttpWebRequest + NTLM 发送 EWS 邮件。

    参数与 owa_mail_*_TT_Report.py 的 send_mail() 兼容，但不需要 account 参数。

    Returns
    -------
    dict
        {"success": bool, "message": str, "error": str}
    """
    # ── 获取凭据 ──
    # 从环境变量或邮件脚本导入默认值
    if server is None:
        server = os.getenv("OWA_SERVER", "exchmail.orange-cit.ci")
    if smtp is None:
        smtp = os.getenv("OWA_SMTP", "ztenoc.olr@orange.com")

    # 从 credential_store 获取凭据（统一走 resolve_owa_credentials）
    _user, _pwd = resolve_owa_credentials()
    if username is None:
        username = _user
    if password is None:
        password = _pwd

    # ── 构建收件人字符串 ──
    to_str = _format_addresses(to)
    cc_str = _format_addresses(cc)
    if not to_str:
        return {"success": False, "error": "No recipients specified"}

    # ── 构建正文（含内嵌图片 HTML） ──
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
                log.warning("内嵌图片不存在，跳过: %s", p)
                continue
            cid = _make_cid(p)
            inline_specs.append((p, cid))
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

    # ── 构建附件参数 ──
    att_str = ""
    if attachments:
        att_paths = []
        for fp in attachments:
            p = Path(fp)
            if not p.is_file():
                return {"success": False, "error": f"附件不存在: {p}"}
            att_paths.append(str(p))
        att_str = ";".join(att_paths)

    # 构建内嵌图片参数 (格式: path|cid;path|cid;...)
    inline_str = ""
    if inline_specs:
        inline_str = ";".join(f"{p}|{cid}" for p, cid in inline_specs)

    # ── 调用 PowerShell 脚本 ──
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(_PS_SCRIPT),
        "-Server", server,
        "-User", username,
        "-Password", password,
        "-From", smtp,
        "-To", to_str,
        "-Subject", subject,
        "-Body", content,
        "-SaveToSent", "true" if save_to_sent else "false",
    ]
    if cc_str:
        cmd.extend(["-Cc", cc_str])
    if att_str:
        cmd.extend(["-Attachment", att_str])
    if inline_str:
        cmd.extend(["-InlineImage", inline_str])

    log.info("[dotnet-ews] 调用 PowerShell EWS 发送 (to=%s, subject=%s, att=%d, inline=%d)",
             to_str, subject, len(att_str.split(";")) if att_str else 0,
             len(inline_specs))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"PowerShell 超时 ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": f"subprocess 异常: {type(e).__name__}: {e}"}

    # 解析 JSON 输出
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if not stdout:
        # 没有 stdout，可能是 PowerShell 错误
        return {"success": False, "error": f"PowerShell 无输出. stderr: {stderr[:500]}"}

    try:
        resp = json.loads(stdout)
    except json.JSONDecodeError:
        # 尝试在输出中查找 JSON
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    resp = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return {"success": False, "error": f"无法解析输出: {stdout[:300]}"}

    if not resp.get("success"):
        return {"success": False, "error": resp.get("error", "Unknown error")}

    log.info("[dotnet-ews] 发送成功: %s", resp.get("message", ""))
    return {"success": True, "message": resp.get("message", "OK")}
