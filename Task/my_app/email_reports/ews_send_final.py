# -*- coding: utf-8 -*-
"""EWS 邮件发送 - 最终修正版

已知问题修复：
- ✅ 密码更新为正确值：Postcode@202608
- ✅ 附件上传语法修正
- ✅ Rate Limit 处理改进
"""

import time
import logging
from pathlib import Path
from typing import List, Optional
from exchangelib import Account, Configuration, Credentials, Mailbox, Message


# === CONFIGURATION ===
OWA_SERVER = "exchmail.orange-cit.ci"
OWA_USERNAME = "ZTENOC_OLR"
# 不要在这里写密码字面量：设置页改完密码后常量仍是旧值，会拿失效密码去认证。
# 统一走 email_reports/owa_credentials.py（环境变量 > 设置页 > 代码默认值）。
FROM_EMAIL = "ZTENOC_OLR@orange-cit.ci"  # Use mailbox's own email

try:                                    # 包内导入 / 直接运行 两种方式都能用
    from email_reports.owa_credentials import resolve_owa_credentials
except ImportError:
    from owa_credentials import resolve_owa_credentials


def send_via_ews(
    to: str | List[str],
    subject: str,
    body: str,
    server: str = OWA_SERVER,
    username: Optional[str] = None,
    password: Optional[str] = None,
    from_email: str = FROM_EMAIL,
    attachments: Optional[List[str]] = None,
    max_retries: int = 5,
) -> dict:
    """EWS sender with retry logic"""
    
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

    # 凭据统一解析（原本是硬编码旧密码的模块常量 + 参数默认值）
    username, password = resolve_owa_credentials(username, password)
    
    # Create configuration
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Monkey-patch SSL verification
    import requests
    original_request = requests.Session.request
    def patched_request(self, *args, **kwargs):
        kwargs['verify'] = False
        return original_request(self, *args, **kwargs)
    requests.Session.request = patched_request
    
    config = Configuration(
        server=server,
        credentials=Credentials(username=username, password=password),
        auth_type='NTLM',
    )
    
    account = Account(
        primary_smtp_address=from_email,
        config=config,
        autodiscover=False,
    )
    
    log.info(f"✓ Connected as: {account.primary_smtp_address}")
    
    # Recipients
    if isinstance(to, str):
        to_addresses = [Mailbox(email_address=email.strip()) for email in to.split(',') if email.strip()]
    else:
        to_addresses = [Mailbox(email_address=email.strip()) for email in to if email.strip()]
    
    if not to_addresses:
        return {"success": False, "error": "No recipients"}
    
    msg = Message(account=account, subject=subject, body=body, to_recipients=to_addresses)
    
    # Attachments - DON'T USE attach() with file parameter!
    all_files = []
    if attachments:
        all_files.extend([Path(a) for a in attachments])
    
    if all_files:
        log.info(f"📎 Attaching {len(all_files)} files...")
        for fp in all_files:
            try:
                with open(fp, 'rb') as f:
                    content = f.read()
                from exchangelib import File
                attachment = File(name=fp.name, content=content)
                msg.attach(attachment)
                log.info(f"  ✓ {fp.name} ({len(content)/1024:.1f} KB)")
            except Exception as e:
                log.warning(f"  ✗ {fp.name}: {str(e)[:100]}")
    
    # Send with retry
    for attempt in range(max_retries):
        try:
            log.info(f"📧 Sending (attempt {attempt + 1}/{max_retries})...")
            msg.send()
            
            log.info("✅ Email sent successfully!")
            return {
                "success": True, 
                "message": "Sent via EWS", 
                "attempts": attempt + 1,
                "msg_id": getattr(msg, 'id', None)
            }
            
        except Exception as e:
            error = str(e).lower()
            
            # Rate limit or throttling - back off
            if "rate limit" in error or "throttl" in error or "back off" in error:
                wait = min(30 * (2 ** attempt), 180)
                log.warning(f"⏱️ Rate limit/Back-off. Waiting {wait}s...")
                time.sleep(wait)
                continue
            
            # Auth errors - don't retry wrong password!
            if "auth" in error or "unauthorized" in error or "credentials" in error:
                return {"success": False, "error": f"❌ Authentication failed: {str(e)[:300]}"}
            
            # Timeout - retry
            if "timeout" in error and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)
                log.warning(f"⏱️ Timeout. Retrying after {wait}s...")
                time.sleep(wait)
                continue
            
            # Other errors - stop
            log.error(f"❌ Error: {str(e)[:300]}")
            return {"success": False, "error": str(e)[:500]}
    
    return {"success": False, "error": f"Failed after {max_retries} attempts"}


if __name__ == "__main__":
    print("=" * 60)
    print("EWS 邮件发送测试 - 密码已更新为：Postcode@202608")
    print("=" * 60)
    
    result = send_via_ews(
        to="dong.xinmin@zte.com.cn",
        subject="[测试] EWS 密码验证 - 第 1 次",
        body="""您好，

这是使用新密码 Postcode@202608 的测试邮件。

如果收到此邮件，说明：
✅ 密码正确
✅ EWS 认证成功
✅ 邮件发送成功

ZTENOC OLR 自动化系统
2026-08-25""",
        attachments=None,
        max_retries=3,
    )
    
    print("\n结果:", result)
