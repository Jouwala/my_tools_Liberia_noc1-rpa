# -*- coding: utf-8 -*-
"""
WinHTTP + NTLM 发送邮件 - Windows 原生 HTTP API
==================================================

使用 Windows WinHTTP API 直接发送 EWS 请求，绕过 Python/.NET的中间层开销。
适合对性能要求极高且需要处理大附件的场景。

注意：此方案需要额外的 C++/C#桥接或 subprocess 调用 native DLL
为了保持纯 Python，目前采用简化版：调用预编译的 native helper 程序

适用场景：
- 大附件批量发送
- 高并发邮件发送
- 需要最低延迟的请求

依赖：
- winhttp.dll (Windows 系统自带，无需安装)
"""

import ctypes
from ctypes import wintypes, byref
import subprocess
from pathlib import Path
from typing import List, Optional


# WinHTTP API 常量和类型定义
WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY = 3

class WinHttpResult:
    """WinHTTP 操作结果包装类"""
    def __init__(self):
        self.success = False
        self.message = ""
        self.error = ""


class WinHttpMailer:
    """WinHTTP EWS 邮件发送器"""
    
    # Windows API handles
    WINHTTP_FLAG_SECURE_IGNORE_ALL_CERT_ERRORS = 0x00000008
    INTERNET_OPEN_TYPE_DIRECT = 1
    
    def __init__(self, server: str, username: str, password: str, from_email: str):
        """
        初始化 WinHTTP 邮件发送器
        
        Parameters
        ----------
        server : str
            Exchange 服务器地址 (如：exchmail.orange-cit.ci)
        username : str
            用户名 (如：ZTENOC_OLR)
        password : str
            密码
        from_email : str
            发件人邮箱 (如：ztenoc.olr@orange.com)
        """
        self.server = server
        self.username = username
        self.password = password
        self.from_email = from_email
        self.session_handle = None
        self.connection_handle = None
        
        # 尝试加载 WinHTTP DLL
        try:
            self.winhttp = ctypes.WinDLL('winhttp.dll')
            self._init_winhttp()
        except FileNotFoundError as e:
            raise RuntimeError("WinHTTP DLL not found: {e}")
    
    def _init_winhttp(self):
        """初始化 WinHTTP 句柄和连接"""
        
        # OpenSession
        self.session_handle = self.winhttp.WinHttpOpen(
            None,  # lpVersionInfo (NULL for default)
            self.INTERNET_OPEN_TYPE_DIRECT,
            None, None, 0
        )
        
        if not self.session_handle:
            raise RuntimeError("Failed to open WinHTTP session")
        
        # OpenConnect
        server_url = f"https://{self.server}/EWS/Exchange.asmx"
        
        self.connection_handle = self.winhttp.WinHttpConnect(
            self.session_handle,
            self.server,
            443,  # HTTPS port
            0
        )
        
        if not self.connection_handle:
            raise RuntimeError("Failed to connect to Exchange server")
    
    def send_ews_request(self, soap_xml: str) -> dict:
        """
        发送 SOAP XML 到 EWS
        
        Parameters
        ----------
        soap_xml : str
            SOAP XML 请求体
        
        Returns
        -------
        dict
            {"success": bool, "message": str, "error": str, "response": str}
        """
        result = WinHttpResult()
        
        try:
            # Create request
            request_url = f"EWS/Exchange.asmx"
            
            request_handle = self.winhttp.WinHttpOpenRequest(
                self.connection_handle,
                "POST",
                request_url,
                None, None, None,
                self.WINHTTP_FLAG_SECURE_IGNORE_ALL_CERT_ERRORS
            )
            
            if not request_handle:
                result.success = False
                result.error = "Failed to create HTTP request"
                return {"success": False, "error": result.error}
            
            # Set headers
            headers = "Content-Type: text/xml; charset=utf-8\r\nAccept: application/soap+xml\r\nConnection: Keep-Alive\r\n\r\n"
            self.winhttp.WinHttpAddRequestHeaders(request_handle, headers, -1, 0)
            
            # Prepare content
            content_bytes = soap_xml.encode('utf-8')
            
            # Send request
            self.winhttp.WinHttpSendRequest(
                request_handle,
                None, 0,
                content_bytes, len(content_bytes),
                len(content_bytes), 0
            )
            
            # Receive response
            self.winhttp.WinHttpReceiveResponse(request_handle, None)
            
            # Read response
            buffer_size = 4096
            buffer = ctypes.create_string_buffer(buffer_size)
            bytes_read = wintypes.DWORD()
            
            response_data = b""
            
            while True:
                self.winhttp.WinHttpReadData(
                    request_handle,
                    ctypes.byref(buffer),
                    buffer_size,
                    ctypes.byref(bytes_read)
                )
                
                if bytes_read.value == 0:
                    break
                    
                response_data += buffer.raw[:bytes_read.value]
            
            # Parse response
            if response_data:
                response_text = response_data.decode('utf-8', errors='ignore')
                
                # Check for success in response
                if '<s:Body>' in response_text and '</s:Body>' in response_text:
                    result.success = True
                    result.message = "Email sent via WinHTTP"
                    result.response = response_text[:1000]  # Truncate large responses
                else:
                    result.success = False
                    result.error = f"Server error in response: {response_text[:500]}"
            else:
                result.success = False
                result.error = "Empty response from server"
            
            # Cleanup
            self.winhttp.WinHttpCloseHandle(request_handle)
            
        except Exception as e:
            result.success = False
            result.error = f"WinHTTP exception: {str(e)}"
            
        finally:
            # Always cleanup connections
            if self.connection_handle:
                try:
                    self.winhttp.WinHttpCloseHandle(self.connection_handle)
                except:
                    pass
            if self.session_handle:
                try:
                    self.winhttp.WinHttpCloseHandle(self.session_handle)
                except:
                    pass
        
        return {
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "response": getattr(result, 'response', '')
        }
    
    def close(self):
        """清理资源"""
        if self.connection_handle:
            try:
                self.winhttp.WinHttpCloseHandle(self.connection_handle)
            except:
                pass
        if self.session_handle:
            try:
                self.winhttp.WinHttpCloseHandle(self.session_handle)
            except:
                pass


try:                                    # 包内导入 / 直接运行 两种方式都能用
    from email_reports.owa_credentials import resolve_owa_credentials
except ImportError:
    from owa_credentials import resolve_owa_credentials


def send_via_winhttp(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    inline_images: Optional[List[str]] = None,
    server: str = "exchmail.orange-cit.ci",
    username: Optional[str] = None,
    password: Optional[str] = None,
    from_email: str = "ztenoc.olr@orange.com",
) -> dict:
    """
    通过 WinHTTP 发送 EWS 邮件
    
    Parameters
    ----------
    to : str
        收件人邮箱
    subject : str
        邮件主题
    body : str
        邮件正文 (HTML)
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
    
    Returns
    -------
    dict
        {"success": bool, "message": str, "error": str}
    """
    # 凭据统一解析：本模块的参数默认值曾是硬编码旧密码，调用方一旦依赖它就会拿
    # 失效密码去认证（2026-09-18 那次 65 小时故障的成因之一）。现在不再有字面量默认值。
    username, password = resolve_owa_credentials(username, password)

    try:
        # 创建邮件发送器
        mailer = WinHttpMailer(server, username, password, from_email)
        
        # 构建收件人 XML
        to_list = [email.strip() for email in to.split(';') if email.strip()]
        to_xml = "".join([f'<t:Mailbox><t:EmailAddress>{escape_xml(email)}</t:EmailAddress></t:Mailbox>' 
                         for email in to_list])
        
        # 构建 SOAP 请求 (直接发送模式)
        disposition = "SendAndSaveCopy"
        
        soap = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:SendItem MessageDisposition="{disposition}">
      <m:Items>
        <t:Message>
          <t:Subject>{escape_xml(subject)}</t:Subject>
          <t:Body BodyType="HTML">{escape_xml(body)}</t:Body>
          <t:ToRecipients>{to_xml}</t:ToRecipients>
          <t:From><t:Mailbox><t:EmailAddress>{escape_xml(from_email)}</t:EmailAddress></t:Mailbox></t:From>
        </t:Message>
      </m:Items>
    </m:SendItem>
  </soap:Body>
</soap:Envelope>'''
        
        # 发送请求
        result = mailer.send_ews_request(soap)
        
        mailer.close()
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": f"WinHTTP sender failed: {str(e)}"
        }


def escape_xml(text: str) -> str:
    """转义 XML 特殊字符"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


if __name__ == "__main__":
    # 测试代码
    result = send_via_winhttp(
        to="test@example.com",
        subject="Test",
        body="<p>Test body</p>"
    )
    print(result)
