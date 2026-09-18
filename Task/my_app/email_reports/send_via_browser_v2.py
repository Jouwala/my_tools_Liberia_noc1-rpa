# -*- coding: utf-8 -*-
"""
OWA 浏览器自动化发送邮件 - Playwright 实现（最终修复版）
===========================================================

完全模拟网页版 OWA 操作流程，绕过 EWS API 的权限限制。
使用 Playwright 进行浏览器自动化。

适用场景：
- EWS API 限流/失败时
- CreateItem 权限问题
- 需要 100% 复刻网页版操作流程

注意：
- 首次运行需要先安装 playwright: pip install playwright
- 需要安装浏览器：playwright install chromium
- 速度比 EWS 慢，但稳定性最高
"""

import time
from pathlib import Path
from typing import List, Optional


try:                                    # 包内导入 / 直接运行 两种方式都能用
    from email_reports.owa_credentials import resolve_owa_credentials
except ImportError:
    from owa_credentials import resolve_owa_credentials


def send_owa_browser_email(
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
    通过浏览器自动化发送 OWA 邮件
    
    Parameters
    ----------
    to : str
        收件人邮箱地址
    subject : str
        邮件主题
    body : str
        邮件正文（HTML）
    attachments : list of str, optional
        附件文件路径列表
    inline_images : list of str, optional
        内嵌图片路径列表
    server : str
        EWS 服务器地址
    username : str
        OWA 登录用户名
    password : str
        OWA 登录密码
    from_email : str
        发件人邮箱
    
    Returns
    -------
    dict
        {"success": bool, "message": str, "error": str}
    """
    # 凭据统一解析（原本是硬编码旧密码的参数默认值，见 owa_credentials 模块说明）
    username, password = resolve_owa_credentials(username, password)

    try:
        # 检查 Playwright 是否安装
        import importlib.util
        if not importlib.util.find_spec("playwright"):
            raise RuntimeError("请先安装 playwright: pip install playwright")
        
        from playwright.sync_api import sync_playwright
        
        print(f"\n[PLAYWRIGHT] 启动浏览器...")
        
        with sync_playwright() as p:
            # 使用 Chromium（无头模式）
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # ====== 直接进入新邮件Compose模式（跳过登录页面找按钮）======
            compose_url = f"https://{server}/owa/?ex=compose"
            print(f"[PLAYWRIGHT] 访问新邮件：{compose_url}")
                        
            # 1. 直接访问 compose URL
            page.goto(compose_url, wait_until="networkidle", timeout=90000)
            time.sleep(5)
                        
            # 2. 检查是否已经在 compose 模式（有收件人/主题输入框）
            in_compose_mode = page.is_visible('input[name="to"]') or page.is_visible('input[name="subject"]')
            if not in_compose_mode:
                # 如果没有输入框，说明未登录或错误，尝试重新登录
                print("[PLAYWRIGHT] ⚠️ 未进入 compose 模式，尝试重新登录...")
                page.goto(f"https://{server}/owa/", wait_until="networkidle")
                time.sleep(3)
                print("[PLAYWRIGHT] 已完成登录检查!")
            else:
                print("[PLAYWRIGHT] ✅ 已在 compose 模式，无需登录!")
            
            # ====== 如果需要登录 ======
            # 检查是否需要输入账号密码（通过是否有 input[type="email"] 判断）
            email_input = None
            if page.is_visible('input[type="email"]') or page.is_visible('input[name="username"]'):
                print("[PLAYWRIGHT] 需要登录...")
            email_selectors = [
                'input[type="email"]',
                'input[name="username"]',
                '[id="i0116"]'
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    inp = page.locator(selector, timeout=5000).first
                    if inp.is_visible():
                        email_input = inp
                        break
                except:
                    continue
            
            if email_input:
                email_input.fill(username)
                print(f"[PLAYWRIGHT] 输入账号：{username}")
                page.keyboard.press("Enter")
                time.sleep(2)
            
            # 3. 输入密码
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                '[id="i0118"]'
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    inp = page.locator(selector, timeout=5000).first
                    if inp.is_visible():
                        password_input = inp
                        break
                except:
                    continue
            
            if password_input:
                password_input.fill(password)
                print("[PLAYWRIGHT] 输入密码")
                page.keyboard.press("Enter")
                time.sleep(5)
            
            # 4. 验证是否登录成功
            if page.url.startswith(f"https://{server}/owa/"):
                print("[PLAYWRIGHT] 登录成功!")
            else:
                return {
                    "success": False,
                    "error": f"登录失败，跳转到：{page.url}"
                }
            
            # 5. 新建邮件
            print("[PLAYWRIGHT] 点击新邮件按钮...")
            
            # 截图调试
            try:
                page.screenshot(path="debug_owa_login.png", full_page=True)
                print("[DEBUG] 已保存登录后的截图：debug_owa_login.png")
            except:
                pass
            
            # 查找新邮件按钮（多种选择器，支持中英文）
            new_mail_selectors = [
                'button:has-text("新邮件")',
                'button:has-text("New mail")',
                '[aria-label="New mail"]',
                '.newMailButton',
                '[id="Ribbon.MailActions.NewMessage"]',
                '.owa-new-mail-button'
            ]
            
            new_mail_button = None
            for selector in new_mail_selectors:
                try:
                    btn = page.locator(selector, timeout=5000).first
                    if btn.is_visible():
                        new_mail_button = btn
                        break
                except Exception as e:
                    pass
            
            # 如果还是没找到，尝试点击"+"或创建图标
            if not new_mail_button:
                print("[PLAYWRIGHT] 尝试点击 '+' 图标...")
                try:
                    btn = page.locator('button:has-text("+")', timeout=3000).first
                    if btn.is_visible():
                        new_mail_button = btn
                except:
                    pass
            
            # 最后尝试：直接访问新邮件 URL
            if not new_mail_button:
                print("[PLAYWRIGHT] 尝试直接访问新邮件 URL...")
                try:
                    page.goto(f"https://{server}/owa/?ex=Compose")
                    time.sleep(2)
                    # 重新查找按钮
                    btn = page.locator('button:has-text("发送")', timeout=3000).first
                    if btn.is_visible():
                        new_mail_button = btn  # 成功进入 compose 模式
                        print("[PLAYWRIGHT] ✅ 通过 URL 进入新邮件模式!")
                except:
                    pass
            
            if not new_mail_button:
                return {"success": False, "error": f"无法找到新邮件按钮 (请查看 debug_owa_login.png)"}
            
            new_mail_button.click()
            time.sleep(3)
            
            # 6. 填写收件人
            to_input = page.locator('input[name="to"]', timeout=10000).first
            to_input.fill(to)
            print(f"[PLAYWRIGHT] 收件人：{to}")
            
            # 7. 填写主题
            subject_input = page.locator('input[name="subject"]', timeout=10000)
            subject_input.fill(subject)
            print(f"[PLAYWRIGHT] 主题：{subject}")
            
            # 8. 填充正文
            print("[PLAYWRIGHT] 正在填充正文...")
            
            # 查找正文编辑器
            editor = page.locator('[contenteditable="true"]').first
            if editor.is_visible():
                editor.evaluate(f'''element => {{
                    element.innerHTML = `''' + body.replace('`', '\\`').replace('${', '$$') + '''`;
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}''')
                print("[PLAYWRIGHT] 已填充正文")
            else:
                print("[PLAYWRIGHT] 警告：未找到内容可编辑区域")
            
            # 9. 添加附件
            all_files = []
            if attachments:
                all_files.extend([(p, "normal") for p in attachments])
            if inline_images:
                all_files.extend([(p, "inline") for p in inline_images])
            
            if all_files:
                print(f"[PLAYWRIGHT] 准备添加 {len(all_files)} 个附件...")
                
                # 点击附件按钮
                attach_selectors = [
                    'button:has-text("附件")',
                    '[aria-label="Attach file"]',
                    '.attachmentButton'
                ]
                
                attach_btn = None
                for selector in attach_selectors:
                    try:
                        attach_btn = page.locator(selector).first
                        if attach_btn.is_enabled():
                            break
                        attach_btn = None
                    except:
                        continue
                
                if attach_btn:
                    attach_btn.click()
                    time.sleep(1)
                    
                    # 上传文件
                    file_input = page.locator('input[type="file"]', timeout=5000).first
                    if file_input.is_enabled():
                        files_to_upload = [str(Path(f)) for f,_ in all_files]
                        file_input.set_input_files(files_to_upload)
                        print(f"[PLAYWRIGHT] ✅ 已添加 {len(files_to_upload)} 个附件")
                    else:
                        print("[PLAYWRIGHT] ⚠️  找不到文件上传控件")
                else:
                    print("[PLAYWRIGHT] ⚠️  找不到附件按钮")
            
            # 10. 发送邮件
            print("[PLAYWRIGHT] 点击发送...")
            
            send_selectors = [
                'button:has-text("发送")',
                '[aria-label="Send"]',
                '.sendButton',
                'button[id="SendButton"]'
            ]
            
            send_btn = None
            for selector in send_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_enabled() and btn.is_visible():
                        send_btn = btn
                        break
                except:
                    continue
            
            if send_btn:
                send_btn.click()
                time.sleep(3)
                
                # 11. 验证发送成功
                success_indicators = [
                    '/mail/inbox',
                    'SentItems',
                    'msgSentNotification',
                    '"sent successfully"',
                    '邮件已发送'
                ]
                
                current_url = page.url.lower()
                page_content = page.content().lower()
                
                is_sent = any(ind in current_url or ind in page_content for ind in success_indicators)
                
                if is_sent:
                    print("[PLAYWRIGHT] ✅ 邮件已成功发送!")
                    browser.close()
                    return {
                        "success": True,
                        "message": "通过浏览器发送成功",
                        "method": "browser",
                        "url": current_url
                    }
                else:
                    return {
                        "success": False,
                        "error": f"发送后状态异常：{current_url}"
                    }
            else:
                return {
                    "success": False,
                    "error": "无法找到发送按钮"
                }
                
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[ERROR] 浏览器自动化失败:\n{error_detail[:500]}")
        return {
            "success": False,
            "error": f"浏览器自动化失败：{str(e)}",
            "detail": error_detail[:500]
        }


if __name__ == "__main__":
    # 测试代码
    result = send_owa_browser_email(
        to="test@example.com",
        subject="Test Email",
        body="<p>Test body</p>",
        attachments=["test.xlsx"],
    )
    print(result)
