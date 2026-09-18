# -*- coding: utf-8 -*-
"""
OWA 浏览器发送邮件 - 超快速版本 v10
==================================

核心逻辑：
1. 直接访问 https://server/owa/?ex=compose (已登录状态)
2. 填充收件人、主题、正文  
3. 添加附件（如有）
4. 点击发送

注意：依赖当前浏览器会话已登录 OWA
"""

import time
from pathlib import Path
from typing import List, Optional


try:                                    # 包内导入 / 直接运行 两种方式都能用
    from email_reports.owa_credentials import resolve_owa_credentials
except ImportError:
    from owa_credentials import resolve_owa_credentials


def send_owa_simple(
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
    """简单快速的 OWA 发送邮件"""
    # 凭据统一解析（原本是硬编码旧密码的参数默认值，见 owa_credentials 模块说明）
    username, password = resolve_owa_credentials(username, password)
    
    try:
        from playwright.sync_api import sync_playwright
        
        print(f"[PLAYWRIGHT] 启动浏览器...\n")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # ====== 步骤 1: 直接进入 compose 模式 ======
            compose_url = f"https://{server}/owa/?ex=compose"
            print(f"[PLAYWRIGHT] 访问：{compose_url}")
            page.goto(compose_url, wait_until="networkidle", timeout=90000)
            time.sleep(5)
            
            # 截图调试
            try:
                page.screenshot(path="debug_compose_v10.png", full_page=True)
                print("[DEBUG] 已保存截图：debug_compose_v10.png")
            except:
                pass
            
            # ====== 步骤 2: 填充收件人 ======
            print("[PLAYWRIGHT] 填充收件人...")
            # 多种可能的选择器
            for selector in ['input[name="to"]', 'input[id="To"]', '[placeholder*="收件人"]']:
                try:
                    inp = page.locator(selector, timeout=3000).first
                    if inp.is_visible():
                        inp.fill(to)
                        print(f"[✅] 收件人：{to}")
                        break
                except:
                    continue
            
            # ====== 步骤 3: 填充主题 ======
            print("[PLAYWRIGHT] 填充主题...")
            for selector in ['input[name="subject"]', 'input[id="Subject"]', '[placeholder*="主题"]']:
                try:
                    inp = page.locator(selector, timeout=3000).first
                    if inp.is_visible():
                        inp.fill(subject)
                        print(f"[✅] 主题：{subject[:30]}...")
                        break
                except:
                    continue
            
            # ====== 步骤 4: 填充正文 ======
            print("[PLAYWRIGHT] 填充正文...")
            # OWA 正文是 contenteditable 区域
            for selector in ['div[contenteditable="true"]', 'div.owaMsgBody', 'div[id$="_Body"]']:
                try:
                    editor = page.locator(selector, timeout=3000).first
                    if editor.is_visible():
                        # 注入 HTML 内容
                        editor.evaluate(f'element => {{ element.innerHTML = `{body.replace("$", "\\$").replace("`", "\\`")}`; }}')
                        print("[✅] 正文已填充")
                        break
                except:
                    continue
            
            # ====== 步骤 5: 添加附件 ======
            all_files = []
            if attachments:
                all_files.extend([(Path(p), "normal") for p in attachments])
            if inline_images:
                all_files.extend([(Path(p), "inline") for p in inline_images])
            
            if all_files:
                print(f"[PLAYWRIGHT] 添加 {len(all_files)} 个附件...")
                
                # 尝试查找附件按钮
                attach_selectors = [
                    'button:has-text("附件")',
                    'button:has-text("Attach")',
                    '.attachmentButton',
                    '[aria-label="Attach file"]'
                ]
                
                attach_btn = None
                for selector in attach_selectors:
                    try:
                        btn = page.locator(selector, timeout=3000).first
                        if btn.is_visible():
                            attach_btn = btn
                            break
                    except:
                        continue
                
                if attach_btn:
                    attach_btn.click()
                    time.sleep(1)
                    
                    # 上传文件
                    try:
                        file_input = page.locator('input[type="file"]', timeout=5000).first
                        files_to_upload = [str(p) for p, _ in all_files]
                        file_input.set_input_files(files_to_upload)
                        print(f"[✅] 已添加 {len(files_to_upload)} 个附件")
                    except Exception as e:
                        print(f"[⚠️] 附件上传异常：{str(e)[:100]}")
            
            # ====== 步骤 6: 发送邮件 ======
            print("[PLAYWRIGHT] 点击发送...")
            
            for selector in [
                'button:has-text("发送")',
                'button:has-text("Send")',
                '.sendButton',
                '[id="SendButton"]'
            ]:
                try:
                    btn = page.locator(selector, timeout=3000).first
                    if btn.is_enabled() and btn.is_visible():
                        btn.click()
                        print(f"[✅] 已点击发送按钮 ({selector})")
                        break
                except:
                    continue
            
            time.sleep(5)  # 等待发送完成
            
            # ====== 步骤 7: 更智能的验证 ======
            # 方案 A: 检查 URL 跳转
            current_url = page.url.lower()
            if '/mail/inbox' in current_url or 'sentitems' in current_url:
                print("\n[✅] 🎉 邮件已成功发送！(URL 跳转)")
                browser.close()
                return {"success": True, "message": "通过浏览器发送成功", "url": current_url}
            
            # 方案 B: 检查成功通知弹窗/提示框
            notification_selectors = [
                '[class*="notification"]',
                '[id*="Notification"]',
                '.msgSentNotification',
                'div[role="alert"]',
                '[aria-label*="sent"]'
            ]
            
            found_notification = False
            for selector in notification_selectors:
                try:
                    elem = page.locator(selector, timeout=2000).first
                    if elem.is_visible():
                        text = elem.inner_text()[:100]
                        print(f"\n[INFO] 检测到通知：{text}")
                        found_notification = True
                        break
                except:
                    pass
            
            if found_notification:
                print("\n[✅] 🎉 邮件已成功发送！(检测到通知)")
                browser.close()
                return {"success": True, "message": "通过浏览器发送成功 (通知确认)", "url": current_url}
            
            # 方案 C: 检查是否停留在 compose 页面但所有字段已填充（可能已发送）
            if '/owa/?ex=compose' in current_url and len(all_files) > 0:
                # 可能是 OWA 在后台处理，不立即跳转
                print("\n[⚠️] 检测到 compose 页面 + 附件")
                print("[INFO] OWA 可能在后台发送邮件...")
                
                # 再等 3 秒看是否跳转
                time.sleep(3)
                new_url = page.url.lower()
                if new_url != current_url:
                    
                    print(f"\n[✅] 🎉 URL 已跳转到：{new_url[:80]}")
                    browser.close()
                    return {"success": True, "message": "延迟跳转确认成功", "url": new_url}
                
            # 如果到这里说明发送失败
            print("\n[❌] ❌ OWA 邮件发送失败")
            browser.close()
            return {
                "success": False,
                "error": "所有验证方法均未检测到发送成功",
                "url": current_url
            }
            
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"浏览器自动化失败：{str(e)}",
            "traceback": traceback.format_exc()[-500:]
        }


if __name__ == "__main__":
    # 快速测试
    result = send_owa_simple(
        to="test@example.com",
        subject="Test v10",
        body="<p>Test body</p>",
        attachments=["test.xlsx"],
    )
    print(result)
