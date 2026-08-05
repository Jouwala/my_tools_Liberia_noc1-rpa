"""
邮件发送模块
支持发送HTML格式的仪表板报表邮件
"""

import smtplib
import sqlite3
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional, List
import threading


class EmailSender:
    """邮件发送器"""
    
    def __init__(self, smtp_server: str, smtp_port: int, 
                 sender_email: str, sender_password: str,
                 db_path: Optional[str] = None):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.db_path = db_path
        
        # 邮件列表文件路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.mail_list_dir = os.path.join(base_dir, "MailList")
        self.to_list_file = os.path.join(self.mail_list_dir, "s_list.txt")
        self.cc_list_file = os.path.join(self.mail_list_dir, "cc_list.txt")
    
    def _read_email_list_from_file(self, file_path: str) -> List[str]:
        """从文件中读取邮件列表"""
        if not os.path.exists(file_path):
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # 邮件地址以分号分隔
                emails = [email.strip() for email in content.split(';') if email.strip()]
                return emails
        except Exception as e:
            print(f"[EmailSender] Error reading email list from {file_path}: {e}")
            return []
    
    def get_subscribers(self, dashboard_type: str = "all") -> List[dict]:
        """
        从数据库获取订阅用户列表
        
        Args:
            dashboard_type: 仪表板类型 (all, lbr, ug, cg, mmr, npl)
        
        Returns:
            订阅用户列表 [{"email": "...", "name": "..."}]
        """
        if not self.db_path or not os.path.exists(self.db_path):
            return []
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT,
                    dashboard_type TEXT DEFAULT 'all',
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            
            if dashboard_type == "all":
                cursor.execute(
                    "SELECT email, name FROM email_subscribers WHERE is_active = 1"
                )
            else:
                cursor.execute(
                    "SELECT email, name FROM email_subscribers WHERE is_active = 1 AND (dashboard_type = ? OR dashboard_type = 'all')",
                    (dashboard_type,)
                )
            
            rows = cursor.fetchall()
            return [{"email": row["email"], "name": row["name"]} for row in rows]
        finally:
            conn.close()
    
    def add_subscriber(self, email: str, name: str = "", dashboard_type: str = "all") -> bool:
        """添加订阅用户"""
        if not self.db_path:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT,
                    dashboard_type TEXT DEFAULT 'all',
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute(
                "INSERT OR REPLACE INTO email_subscribers (email, name, dashboard_type) VALUES (?, ?, ?)",
                (email, name, dashboard_type)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[EmailSender] Error adding subscriber: {e}")
            return False
        finally:
            conn.close()
    
    def remove_subscriber(self, email: str) -> bool:
        """移除订阅用户"""
        if not self.db_path:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE email_subscribers SET is_active = 0 WHERE email = ?",
                (email,)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[EmailSender] Error removing subscriber: {e}")
            return False
        finally:
            conn.close()
    
    def send_email(self, to_emails: List[str], subject: str, 
                   html_content: str, text_content: str = "", 
                   cc_emails: List[str] = None) -> dict:
        """
        发送邮件
        
        Args:
            to_emails: 收件人邮箱列表
            subject: 邮件主题
            html_content: HTML格式的邮件正文
            text_content: 纯文本格式的邮件正文（备用）
            cc_emails: 抄送邮箱列表
        
        Returns:
            {"success": bool, "message": str, "sent_count": int}
        """
        if not to_emails:
            return {"success": False, "message": "No recipients", "sent_count": 0}
        
        msg = MIMEMultipart("alternative")
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject
        msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z")
        
        if cc_emails:
            msg["Cc"] = ", ".join(cc_emails)
        
        if text_content:
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
        
        msg.attach(MIMEText(html_content, "html", "utf-8"))
        
        all_recipients = to_emails + (cc_emails if cc_emails else [])
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                if self.smtp_port == 465:
                    with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=60) as server:
                        server.ehlo()
                        server.login(self.sender_email, self.sender_password)
                        server.sendmail(self.sender_email, all_recipients, msg.as_string())
                else:
                    with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=60) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(self.sender_email, self.sender_password)
                        server.sendmail(self.sender_email, all_recipients, msg.as_string())
                
                return {
                    "success": True,
                    "message": f"Email sent successfully to {len(all_recipients)} recipients",
                    "sent_count": len(all_recipients)
                }
            except smtplib.SMTPAuthenticationError as e:
                return {
                    "success": False,
                    "message": f"SMTP Authentication failed. Please check your email and authorization code: {str(e)}",
                    "sent_count": 0
                }
            except (smtplib.SMTPServerDisconnected, ConnectionError, OSError) as e:
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay)
                    continue
                return {
                    "success": False,
                    "message": f"Connection error after {max_retries} attempts: {str(e)}",
                    "sent_count": 0
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Failed to send email: {str(e)}",
                    "sent_count": 0
                }
        
        return {
            "success": False,
            "message": "Failed to send email after all retries",
            "sent_count": 0
        }
    
    def send_dashboard_report(self, dashboard_type: str, html_content: str,
                              custom_subject: str = None) -> dict:
        """
        发送仪表板报表邮件给订阅用户
        
        Args:
            dashboard_type: 仪表板类型 (lbr, ug, cg, mmr, npl)
            html_content: HTML格式的仪表板内容
            custom_subject: 自定义邮件主题
        
        Returns:
            {"success": bool, "message": str, "sent_count": int, "recipients": list}
        """
        # 从文件中读取邮件列表
        to_emails = self._read_email_list_from_file(self.to_list_file)
        cc_emails = self._read_email_list_from_file(self.cc_list_file)
        
        # 如果文件中没有邮件列表，则从数据库中读取订阅用户
        if not to_emails:
            subscribers = self.get_subscribers(dashboard_type)
            if subscribers:
                to_emails = [sub["email"] for sub in subscribers]
        
        if not to_emails:
            return {
                "success": False,
                "message": "No active subscribers found",
                "sent_count": 0,
                "recipients": []
            }
        
        dashboard_names = {
            "lbr": "LBR Warehouse Dashboard",
            "ug": "UG Warehouse Dashboard",
            "cg": "CG Warehouse Dashboard",
            "mmr": "MMR Warehouse Dashboard",
            "npl": "NPL Warehouse Dashboard"
        }
        
        dashboard_name = dashboard_names.get(dashboard_type, "Warehouse Dashboard")
        subject = custom_subject or f"{dashboard_name} Report - {datetime.now().strftime('%Y-%m-%d')}"
        
        result = self.send_email(to_emails, subject, html_content, cc_emails=cc_emails)
        result["recipients"] = to_emails
        result["cc_recipients"] = cc_emails
        
        return result
    
    def send_async(self, to_emails: List[str], subject: str, 
                   html_content: str, callback=None):
        """
        异步发送邮件
        
        Args:
            to_emails: 收件人邮箱列表
            subject: 邮件主题
            html_content: HTML格式的邮件正文
            callback: 发送完成后的回调函数 callback(result: dict)
        """
        def _send():
            result = self.send_email(to_emails, subject, html_content)
            if callback:
                callback(result)
        
        thread = threading.Thread(target=_send, daemon=True)
        thread.start()


def create_email_sender(config: dict) -> EmailSender:
    """
    创建邮件发送器实例
    
    Args:
        config: 配置字典，包含 smtp_server, smtp_port, sender_email, sender_password, db_path
    
    Returns:
        EmailSender 实例
    
    默认使用126邮箱配置:
        - SMTP服务器: smtp.126.com
        - SMTP端口: 465 (SSL加密)
        - 需要使用SMTP授权码（不是登录密码）
    """
    return EmailSender(
        smtp_server=config.get("smtp_server", "smtp.126.com"),
        smtp_port=config.get("smtp_port", 465),
        sender_email=config.get("sender_email", ""),
        sender_password=config.get("sender_password", ""),
        db_path=config.get("db_path")
    )
