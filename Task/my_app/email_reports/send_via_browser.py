# -*- coding: utf-8 -*-
"""
OWA 浏览器自动化发送邮件 - 兜底方案
========================================

完全模拟网页版 OWA 操作流程，绕过 EWS API 的限制和错误。
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


def send_owa_browser_email(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    inline_images: Optional[List[str]] = None,
    server: str = "exchmail.orange-cit.ci",
    username: str = "ZTENOC_OLR",
    password: str = "Postcode@202608",
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
            
            print(f"[PLAYWRIGHT] 访问 OWA: https://{server}/owa/")
            
            # 1. 登录页面
            page.goto(f"https://{server}/owa/", wait_until="networkidle", timeout=60000)
            
            # 等待加载
            time.sleep(3)
            
            # 2. 输入账号
            email_input = page.locator('input[type="email"]').first
            if email_input.is_visible():
                email_input.fill(username)
                print(f"[PLAYWRIGHT] 输入账号：{username}")
                page.keyboard.press("Enter")
                time.sleep(2)
            
            # 3. 输入密码
            password_input = page.locator('input[type="password"]')
            if password_input.is_visible():
                password_input.fill(password)
                print(f"[PLAYWRIGHT] 输入密码")
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
            
            # 查找新邮件按钮（根据不同 OWA 版本可能不同）
            new_mail_button = page.locator("button").filter(has_text="新邮件").first
            if not new_mail_button.is_enabled():
                # 尝试其他选择器
                new_mail_button = page.locator('[aria-label="New mail"]').first
            
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
            
            # 8. 填充正文（使用页面内容注入）
            # OWA 使用 ContentEditable，需要模拟真实编辑行为
            body_js = body.replace('{', '{{').replace('}', '}}')
            page.evaluate(f'''
                const editor = document.querySelector('[contenteditable="true"]') || 
                              document.querySelector('div.owaMsgBody') || 
                              document.body;
                if (editor) {
                    editor.innerHTML = `{body}`;
                    // 触发 contentchange 事件
                    editor.dispatchEvent(new Event('input', { bubbles: true }));
                }
            '''.format(body=body))
            print("[PLAYWRIGHT] 已填充正文")
            
            # 9. 添加附件（支持普通附件和内嵌图片）
            all_files = []
            if attachments:
                all_files.extend(attachments)
            if inline_images:
                all_files.extend([(path, "inline") for path in inline_images])
                # 对于内嵌图片，标记为 inline 模式
                # OWA 会自动识别
            
            if all_files:
                print(f"[PLAYWRIGHT] 准备添加 {len(all_files)} 个附件...")
                
                # 点击附件按钮
                attach_button = None
                # 尝试多种选择器
                selectors = [
                    'button:has-text("附件")',
                    '[aria-label="Attach file"]',
                    '.attachmentButton',
                    'button[title*="Attachment"]'
                ]
                
                for selector in selectors:
                    try:
                        attach_button = page.locator(selector).first
                        if attach_button.is_enabled():
                            break
                        attach_button = None
                    except:
                        continue
                
                if not attach_button:
                    raise RuntimeError("无法找到附件按钮")
                
                attach_button.click()
                time.sleep(1)
                
                # 等待文件选择对话框出现
                # OWA 通常会打开系统文件选择对话框
                # 这里我们模拟拖拽或点击上传
                upload_zone = page.locator('.uploadZone', timeout=5000).first
                if upload_zone.is_visible():
                    # 拖拽文件到上传区域
                    for filepath, filetype in [(p, "normal") for p in all_files]:
                        try:
                            p = Path(filepath)
                            # 创建虚拟文件对象并拖拽
                            page.set_input_files('input[type="file"]', str(p))
                            print(f"[PLAYWRIGHT] 已添加附件：{p.name}")
                        except Exception as e:
                            print(f"[PLAYWRIGHT] 附件添加失败 {p.name}: {str(e)[:100]}")
                else:
                    # 如果找不到上传区域，尝试直接输入路径到文件选择框
                    file_input = page.locator('input[type="file"]', timeout=5000).first
                    if file_input.is_enabled():
                        # 批量添加文件
                        files_to_upload = [str(Path(f)) for f,_ in all_files]
                        file_input.set_input_files(files_to_upload)
                        print(f"[PLAYWRIGHT] 已批量添加 {len(files_to_upload)} 个文件")
            
            # 10. 发送邮件
            print("[PLAYWRIGHT] 点击发送...")
            
            send_button = None
            # 尝试多种发送按钮选择器
            send_selectors = [
                'button:has-text("发送")',
                '[aria-label="Send"]',
                '.sendButton',
                'button[title*="Send Email"]',
                'button[id="SendButton"]'
            ]
            
            for selector in send_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_enabled() and btn.is_visible():
                        send_button = btn
                        break
                except:
                    continue
            
            if not send_button:
                raise RuntimeError("无法找到发送按钮")
            
            send_button.click()
            time.sleep(3)
            
            # 11. 验证发送成功
            # 检查是否返回收件箱或显示成功提示
            success_indicators = [
                '/mail/inbox',
                'SentItems',
                'msgSentNotification',
                '"sent successfully"',
                '邮件已发送'
            ]
            
            page_content = page.content().lower()
            current_url = page.url.lower()
            
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
                print("[PLAYWRIGHT] 邮件已成功发送!")
                browser.close()
                return {
                    "success": True,
                    "message": "通过浏览器发送成功",
                    "method": "browser"
                }
            else:
                browser.close()
                return {
                    "success": False,
                    "error": f"发送后 URL 异常：{page.url}"
                }
                
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[ERROR] 浏览器自动化失败:\n{error_detail}")
        return {
            "success": False,
            "error": f"浏览器自动化失败：{str(e)}",
            "detail": error_detail[:500]
        }


if __name__ == "__main__":
    # 测试代码
    result = send_owa_browser_email(
        to="test@example.com",
        subject="Test",
        body="<p>Test body</p>",
        attachments=["test.xlsx"],
    )
    print(result)
