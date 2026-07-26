"""
邮件发送示例脚本
演示如何发送仪表板报表邮件
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from shared.email_sender import EmailSender, create_email_sender
from shared.dashboard_email_renderer import DashboardEmailRenderer, create_renderer


def example_send_email():
    """示例：发送仪表板报表邮件"""
    
    # 邮件服务器配置 (126邮箱)
    email_config = {
        "smtp_server": "smtp.126.com",  # 126邮箱SMTP服务器
        "smtp_port": 465,  # SSL加密端口
        "sender_email": "your_email@126.com",  # 发件人邮箱
        "sender_password": "your_authorization_code",  # SMTP授权码（不是登录密码）
        "db_path": os.path.join(os.path.dirname(__file__), "WareHouseDashBoard", "inventory.db")
    }
    
    # 创建邮件发送器
    sender = create_email_sender(email_config)
    
    # 添加订阅用户（只需执行一次）
    sender.add_subscriber("recipient1@example.com", "User 1", "all")
    sender.add_subscriber("recipient2@example.com", "User 2", "lbr")
    
    # 创建仪表板渲染器
    renderer = create_renderer(email_config["db_path"])
    
    # 获取仪表板数据
    dashboard_data = renderer.get_dashboard_data(
        date_start="2026-03-01",
        date_end="2026-03-04"
    )
    
    # 渲染HTML内容
    html_content = renderer.render_email_html(
        dashboard_name="LBR Warehouse Dashboard",
        data=dashboard_data
    )
    
    # 发送邮件给订阅用户
    result = sender.send_dashboard_report(
        dashboard_type="lbr",
        html_content=html_content,
        custom_subject="LBR Warehouse Daily Report - 2026-03-04"
    )
    
    print(f"发送结果: {result}")
    
    return result


def example_send_to_specific_emails():
    """示例：发送邮件给指定邮箱列表"""
    
    email_config = {
        "smtp_server": "smtp.126.com",
        "smtp_port": 465,
        "sender_email": "your_email@126.com",
        "sender_password": "your_authorization_code",
        "db_path": os.path.join(os.path.dirname(__file__), "WareHouseDashBoard", "inventory.db")
    }
    
    sender = create_email_sender(email_config)
    renderer = create_renderer(email_config["db_path"])
    
    dashboard_data = renderer.get_dashboard_data()
    html_content = renderer.render_email_html(
        dashboard_name="Warehouse Dashboard Report",
        data=dashboard_data
    )
    
    # 直接发送给指定邮箱列表
    result = sender.send_email(
        to_emails=["user1@example.com", "user2@example.com"],
        subject="Warehouse Dashboard Report",
        html_content=html_content
    )
    
    print(f"发送结果: {result}")
    
    return result


def example_async_send():
    """示例：异步发送邮件"""
    
    email_config = {
        "smtp_server": "smtp.126.com",
        "smtp_port": 465,
        "sender_email": "your_email@126.com",
        "sender_password": "your_authorization_code",
        "db_path": os.path.join(os.path.dirname(__file__), "WareHouseDashBoard", "inventory.db")
    }
    
    sender = create_email_sender(email_config)
    renderer = create_renderer(email_config["db_path"])
    
    dashboard_data = renderer.get_dashboard_data()
    html_content = renderer.render_email_html(
        dashboard_name="Warehouse Dashboard",
        data=dashboard_data
    )
    
    def callback(result):
        print(f"异步发送完成: {result}")
    
    # 异步发送
    sender.send_async(
        to_emails=["user@example.com"],
        subject="Async Dashboard Report",
        html_content=html_content,
        callback=callback
    )
    
    print("邮件正在异步发送中...")


if __name__ == "__main__":
    print("=" * 50)
    print("邮件发送示例")
    print("=" * 50)
    print()
    print("请先配置邮件服务器信息后再运行此脚本")
    print("1. 修改 smtp_server, smtp_port (默认126邮箱)")
    print("2. 设置 sender_email 和 sender_password")
    print("   注意: 密码是SMTP授权码，不是登录密码")
    print("   获取方式: 登录126邮箱 -> 设置 -> POP3/SMTP/IMAP -> 开启SMTP服务 -> 获取授权码")
    print("3. 添加订阅用户邮箱")
    print()
    print("示例函数:")
    print("  - example_send_email(): 发送给订阅用户")
    print("  - example_send_to_specific_emails(): 发送给指定邮箱")
    print("  - example_async_send(): 异步发送")
