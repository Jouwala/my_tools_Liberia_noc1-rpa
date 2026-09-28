# -*- coding: utf-8 -*-
"""EWS 邮件发送 - 简洁实用版"""

import os
import re
import sys
import time
import uuid
import logging
from pathlib import Path
from typing import List, Optional
from exchangelib import (
    Account,
    Configuration,
    Credentials,
    DELEGATE,
    FileAttachment,
    HTMLBody,
    Mailbox,
    Message,
    Version,
)
from exchangelib.protocol import NoVerifyHTTPAdapter, Protocol
from exchangelib.version import EXCHANGE_2016

# 与 owa_mail_1hour_TT_Report.py 保持一致：正文里的内嵌图片占位符
_INLINE_PLACEHOLDER = "<!-- inline images inserted here -->"


def _make_cid(path: Path) -> str:
    """为内嵌图片生成唯一 content_id（仅含安全字符）。"""
    safe = re.sub(r"\W+", "", path.stem) or "img"
    return f"{safe}_{uuid.uuid4().hex}"


# 凭据一律经 owa_credentials.resolve_owa_credentials 解析（见下方 _resolve_credentials）。
# 2026-09-27 删除这里的 _DEFAULT_USER / _DEFAULT_PASSWORD 两个字面量：
# 它们是**完全未被引用**的死代码（模块内无任何读取点），只把口令明文留在了版本库里；
# 真正的回退值集中在 owa_credentials.py（该处是刻意的最后兜底，保留）。


def _resolve_credentials(username: Optional[str], password: Optional[str]) -> tuple:
    """解析生效凭据：显式传入 > 环境变量 > 数据库(设置页) > 代码默认值。

    2026-09-18：本模块原先只有硬编码默认值、完全不读 credential_store，
    导致调用方即使已在设置页更新密码，这里仍拿旧密码认证并报
    "Invalid credentials"（liberia_email_1h 每小时必失败）。此处补齐兜底，
    避免今后再有调用方踩同一个坑。

    实现在 ``email_reports/owa_credentials.py``（全项目唯一一处凭据解析逻辑）。
    """
    try:
        from email_reports.owa_credentials import resolve_owa_credentials
    except ImportError:
        from owa_credentials import resolve_owa_credentials
    return resolve_owa_credentials(username, password)


def send_via_ews_enhanced(
    to: str | List[str],
    subject: str,
    body: str,
    server: str = "exchmail.orange-cit.ci",
    username: Optional[str] = None,
    password: Optional[str] = None,
    from_email: str = "ztenoc.olr@orange.com",
    cc: Optional[str | List[str]] = None,
    attachments: Optional[List[str]] = None,
    inline_images: Optional[List[str]] = None,
    max_retries: int = 5,
) -> dict:
    """Simple EWS sender with retry logic"""
    
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

    # 凭据兜底：不传/传旧默认值时自动改用设置页里的当前密码
    username, password = _resolve_credentials(username, password)
    
    # Windows 下无法本地验证 Orange 证书链 → 关闭 SSL 校验（仍走 HTTPS 加密通道）
    Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

    config = Configuration(
        server=server,
        credentials=Credentials(username=username, password=password),
        auth_type='NTLM',
        version=Version(build=EXCHANGE_2016, api_version="Exchange2016"),
    )
    
    account = Account(
        primary_smtp_address=from_email,
        config=config,
        # 必须显式 DELEGATE：只把凭据放进 config 时，exchangelib 会误判为
        # impersonation 模式并添加 ConnectingSID 头，被服务器拒绝
        # （"The account does not have permission to impersonate the requested user"）。
        access_type=DELEGATE,
        autodiscover=False,
    )
    
    log.info(f"Connected as: {account.primary_smtp_address}")
    
    # Recipients
    if isinstance(to, str):
        to_addresses = [Mailbox(email_address=email.strip()) for email in to.split(',') if email.strip()]
    else:
        to_addresses = [Mailbox(email_address=email.strip()) for email in to if email.strip()]
    
    if not to_addresses:
        return {"success": False, "error": "No recipients"}

    # CC recipients
    cc_addresses = []
    if cc:
        if isinstance(cc, str):
            cc_addresses = [Mailbox(email_address=email.strip()) for email in cc.split(',') if email.strip()]
        else:
            cc_addresses = [Mailbox(email_address=email.strip()) for email in cc if email.strip()]

    # ---- 内嵌图片：以 cid: 方式嵌入 HTML 正文（恢复之前的格式），而非普通附件 ----
    inline_specs: List[tuple] = []  # [(Path, cid), ...]
    if inline_images:
        image_blocks: List[str] = []
        for img in inline_images:
            p = Path(img)
            if not p.is_file():
                log.warning(f"内嵌图片不存在，跳过: {p}")
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
        if image_blocks:
            all_images_html = "".join(image_blocks)
            if _INLINE_PLACEHOLDER in body:
                body = body.replace(_INLINE_PLACEHOLDER, all_images_html, 1)
            else:
                body = body + all_images_html

    # 正文为 HTML（含内嵌图片或含标签）时用 HTMLBody，保持内嵌/富文本格式
    if inline_specs or "<" in body:
        msg_body = HTMLBody(body)
    else:
        msg_body = body

    msg = Message(account=account, subject=subject, body=msg_body, to_recipients=to_addresses)
    if cc_addresses:
        msg.cc_recipients = cc_addresses

    # ---- 普通附件（Excel 等，保持独立附件）----
    if attachments:
        log.info(f"Attaching {len(attachments)} files...")
        for a in attachments:
            fp = Path(a)
            try:
                with open(fp, 'rb') as f:
                    content = f.read()
                attachment = FileAttachment(name=fp.name, content=content)
                msg.attach(attachment)
                log.info(f"  ✓ {fp.name}")
            except Exception as e:
                log.warning(f"  ✗ {fp.name}: {e}")

    # ---- 内嵌图片作为 inline attachment 挂到邮件（is_inline=True + content_id）----
    for p, cid in inline_specs:
        try:
            with open(p, 'rb') as f:
                content = f.read()
            msg.attach(FileAttachment(name=p.name, content=content, content_id=cid, is_inline=True))
        except Exception as e:
            log.warning(f"  ✗ inline {p.name}: {e}")
    
    # Send with retry
    for attempt in range(max_retries):
        try:
            log.info(f"Sending (attempt {attempt + 1}/{max_retries})...")
            msg.send()
            
            log.info("✓ Email sent!")
            return {"success": True, "message": "Sent via EWS", "attempts": attempt + 1}
            
        except Exception as e:
            error = str(e).lower()
            
            # Rate limit or throttling - back off
            if "rate limit" in error or "throttl" in error:
                wait = min(30 * (2 ** attempt), 180)
                log.warning(f"Rate limit. Backing off {wait}s...")
                time.sleep(wait)
                continue
            
            # Auth/permission errors - don't retry
            if "auth" in error or "unauthorized" in error:
                return {"success": False, "error": f"Auth error: {str(e)[:200]}"}
            
            # Timeout - retry
            if "timeout" in error and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)
                log.warning(f"Timeout. Retrying after {wait}s...")
                time.sleep(wait)
                continue
            
            # Other errors - stop
            log.error(f"Error: {str(e)[:300]}")
            return {"success": False, "error": str(e)[:500]}
    
    return {"success": False, "error": f"Failed after {max_retries} attempts"}


if __name__ == "__main__":
    result = send_via_ews_enhanced(
        to="test@example.com",
        subject="Test",
        body="<p>Test</p>",
    )
    print(result)
