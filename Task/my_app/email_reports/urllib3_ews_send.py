# -*- coding: utf-8 -*-
"""
urllib3/requests EWS 邮件发送器
================================

使用纯 Python HTTP 库手动构造 SOAP 请求发送到 Exchange Web Services。
适合需要高度定制化和调试的场景。

依赖：
    pip install urllib3 requests

特点：
- 完全可控的 HTTP 请求
- 支持自定义 headers 和 proxies
- 易于调试和添加日志
- 可处理基本认证和 NTLM

适用场景：
- 调试 EWS API 问题
- 需要特殊 HTTP 配置
- 作为备用 fallback 方案
"""

import uuid
from pathlib import Path
from typing import List, Optional, Tuple
import urllib3
from urllib3.util.retry import Retry
from urllib3.poolmanager import PoolManager

try:
    import requests_ntlm
    HAS_REQUESTS_NTLM = True
except ImportError:
    HAS_REQUESTS_NTLM = False


# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class NTLMAdapter(urllib3.HTTPAdapter):
    """NTLM 认证适配器"""
    
    def __init__(self, auth=None, *args, **kwargs):
        self.auth = auth
        super().__init__(*args, **kwargs)
    
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs
        )


def build_ews_soap_message(
    to_recipients: List[str],
    subject: str,
    body: str,
    from_email: str,
    message_disposition: str = "SendAndSaveCopy",
    cc_recipients: Optional[List[str]] = None
) -> str:
    """
    构建 EWS SOAP XML 消息
    
    Parameters
    ----------
    to_recipients : list of str
        收件人邮箱列表
    subject : str
        邮件主题
    body : str
        邮件正文
    from_email : str
        发件人邮箱
    message_disposition : str
        消息处置方式 ("SendAndSaveCopy" or "SendOnly")
    cc_recipients : list of str, optional
        抄送列表
    
    Returns
    -------
    str
        SOAP XML 字符串
    """
    
    # 转义 XML 字符
    def xml_escape(text: str) -> str:
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))
    
    # 构建收件人 XML
    to_xml = "".join([
        f'<t:Mailbox><t:EmailAddress>{xml_escape(email)}</t:EmailAddress></t:Mailbox>'
        for email in to_recipients
    ])
    
    # 构建抄送 XML
    cc_xml = ""
    if cc_recipients and len(cc_recipients) > 0:
        cc_xml = "".join([
            f'<t:Mailbox><t:EmailAddress>{xml_escape(email)}</t:EmailAddress></t:Mailbox>'
            for email in cc_recipients
        ])
    
    soap = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:SendItem MessageDisposition="{message_disposition}">
      <m:Items>
        <t:Message>
          <t:Subject>{xml_escape(subject)}</t:Subject>
          <t:Body BodyType="HTML">{xml_escape(body)}</t:Body>
          <t:ToRecipients>{to_xml}</t:ToRecipients>
          {f"<t:CcRecipients>{cc_xml}</t:CcRecipients>" if cc_xml else ""}
          <t:From><t:Mailbox><t:EmailAddress>{xml_escape(from_email)}</t:EmailAddress></t:Mailbox></t:From>
        </t:Message>
      </m:Items>
    </m:SendItem>
  </soap:Body>
</soap:Envelope>'''
    
    return soap


class UrllibEwsSender:
    """urllib3 EWS 邮件发送器"""
    
    def __init__(self, server: str, username: str, password: str, from_email: str):
        """
        初始化 EWS 发送器
        
        Parameters
        ----------
        server : str
            Exchange 服务器地址
        username : str
            用户名
        password : str
            密码
        from_email : str
            发件人邮箱
        """
        self.server = server
        self.username = username
        self.password = password
        self.from_email = from_email
        self.ews_url = f"https://{server}/EWS/Exchange.asmx"
        
        # 创建带有重试策略的 session
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[408, 429, 500, 502, 503, 504]
        )
        
        adapter = urllib3.HTTPAdapter(max_retries=retry_strategy)
        self.http = urllib3.PoolManager()
        
        self._session = None
    
    def _get_session(self):
        """获取会话对象"""
        if self._session is None:
            self._session = requests.Session()
            
            if HAS_REQUESTS_NTLM:
                # 设置 NTLM 认证
                self._session.auth = requests_ntlm.NtlmAuth(
                    f"{self.username}",
                    f"{self.password}"
                )
            else:
                raise RuntimeError("Please install requests_ntlm: pip install requests-ntlm")
        
        return self._session
    
    def send_mail(
        self,
        to: str | List[str],
        subject: str,
        body: str,
        cc: Optional[str | List[str]] = None
    ) -> dict:
        """
        发送邮件
        
        Parameters
        ----------
        to : str or list of str
            收件人邮箱
        subject : str
            邮件主题
        body : str
            邮件正文
        cc : str or list of str, optional
            抄送
            
        Returns
        -------
        dict
            {"success": bool, "message": str, "error": str, "response": str}
        """
        
        # 规范化输入
        if isinstance(to, str):
            to_list = [email.strip() for email in to.split(';') if email.strip()]
        else:
            to_list = [email.strip() for email in to if email.strip()]
        
        if isinstance(cc, str):
            cc_list = [email.strip() for email in cc.split(';') if email.strip()]
        elif cc:
            cc_list = [email.strip() for email in cc if email.strip()]
        else:
            cc_list = []
        
        # 构建 SOAP 请求
        soap_xml = build_ews_soap_message(
            to_recipients=to_list,
            subject=subject,
            body=body,
            from_email=self.from_email,
            message_disposition="SendAndSaveCopy",
            cc_recipients=cc_list
        )
        
        try:
            # 设置请求头
            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'Accept': 'application/soap+xml',
                'Connection': 'Keep-Alive',
                'X-AnchorMailbox': self.from_email
            }
            
            # 发送请求
            response = self.http.request(
                'POST',
                self.ews_url,
                body=soap_xml.encode('utf-8'),
                headers=headers,
                timeout=300,
                retries=3,
                assert_fingerprint=None  # 忽略证书验证
            )
            
            # 解析响应
            response_body = response.data.decode('utf-8', errors='ignore')
            
            if response.status == 200:
                # 检查响应中是否有错误信息
                if '<s:Body>' in response_body:
                    if '</s:Fault>' not in response_body:
                        return {
                            "success": True,
                            "message": "Email sent successfully via urllib3",
                            "response": response_body[:1000]
                        }
                return {
                    "success": False,
                    "error": f"Server returned 200 but no valid response: {response_body[:500]}"
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status}: {response_body[:500]}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"urllib3 exception: {str(e)}"
            }


try:                                    # 包内导入 / 直接运行 两种方式都能用
    from email_reports.owa_credentials import resolve_owa_credentials
except ImportError:
    from owa_credentials import resolve_owa_credentials


def send_via_urllib3(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    inline_images: Optional[List[str]] = None,
    server: str = "exchmail.orange-cit.ci",
    username: Optional[str] = None,
    password: Optional[str] = None,
    from_email: str = "ztenoc.olr@orange.com",
    cc: Optional[str] = None
) -> dict:
    """
    通过 urllib3 发送 EWS 邮件
    
    Parameters
    ----------
    to : str
        收件人邮箱
    subject : str
        邮件主题
    body : str
        邮件正文
    attachments : list of str, optional
        附件路径列表
    inline_images : list of str, optional
        内嵌图片路径列表
    server : str
        Exchange 服务器
    username : str
        用户名
    password : str
        密码
    from_email : str
        发件人邮箱
    cc : str, optional
        抄送
    
    Returns
    -------
    dict
        {"success": bool, "message": str, "error": str}
    """
    # 凭据统一解析（原本是硬编码旧密码的参数默认值，见 owa_credentials 模块说明）
    username, password = resolve_owa_credentials(username, password)

    sender = UrllibEwsSender(server, username, password, from_email)
    return sender.send_mail(to=to, subject=subject, body=body, cc=cc)


if __name__ == "__main__":
    # 测试代码
    result = send_via_urllib3(
        to="test@example.com",
        subject="Test",
        body="<p>Test body</p>"
    )
    print(result)
